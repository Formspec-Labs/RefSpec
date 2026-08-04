"""Publish a verified vocabulary atlas as a static, inspectable release.

The atlas manifest and N-Quads remain authoritative.  This module adds two
disposable delivery forms around those exact bytes:

* a deterministic gzip file for download; and
* a bounded JSON view plus an offline HTML explorer.

Neither form can add an atlas fact.  The publisher first opens the canonical
distribution with both external digests, and every generated file names those
same pins in ``publication-manifest.json``.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from rdflib import Dataset, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, PROV, RDF, SKOS

from refspec import binding
from refspec.storage import canonical_json

from .explorer import render_atlas_explorer
from .model import (
    ATLAS,
    RKAF,
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    _one_resource,
    _search_only_mapping_nodes,
    _search_only_mapping_validations,
)

PUBLICATION_MANIFEST = "publication-manifest.json"
EXPLORER_DATA = "atlas-explorer.json"
EXPLORER_HTML = "index.html"
COMPRESSED_ATLAS = "atlas.nq.gz"
ATLAS_MANIFEST = "atlas-manifest.json"
PUBLICATION_SCHEMA_VERSION = "1.0"
EXPLORER_SCHEMA_VERSION = "1.0"

_PUBLICATION_TYPE = "urn:ref:type:VocabularyAtlasPublicationManifest"
_EXPLORER_TYPE = "urn:ref:type:VocabularyAtlasExplorerView"
_DEFAULT_MAX_NODES = 640
_DEFAULT_MAX_MAPPINGS = 240
_DEFAULT_SHARED_CLUSTERS = 180


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _canonical_file_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _iri_tail(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        tail = parsed.path.rstrip("/").rsplit("/", 1)[-1] or parsed.netloc
    else:
        tail = value.rstrip(":/").rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    return " ".join(unquote(tail).replace("_", " ").replace("-", " ").split()) or value


def _default_release_label(release_id: str) -> str:
    lowered = release_id.casefold()
    if "federal-register-thesaurus" in lowered:
        return "Federal Register 2025"
    if "elsst.cessda.eu/id/" in lowered:
        version = release_id.rstrip("/").rsplit("/", 1)[-1]
        return f"ELSST {version}"
    if "icpsr" in lowered:
        return "ICPSR"
    parsed = urlparse(release_id)
    if parsed.scheme in {"http", "https"}:
        tail = _iri_tail(release_id)
        return f"{parsed.netloc} · {tail}" if tail != parsed.netloc else tail
    return _iri_tail(release_id).title()


def _label_for(graph: Graph, concept: URIRef) -> str:
    # Preferred labels first; then alternate labels, because ISO-25964
    # non-descriptor terms (ICPSR lead-in entries) carry only an altLabel on
    # their own URI. The IRI tail is a last resort, not a labelling policy.
    for predicate in (SKOS.prefLabel, SKOS.altLabel):
        chosen = _note_for(graph, concept, predicate)
        if chosen is not None:
            return chosen
    return _iri_tail(str(concept))


def _note_for(graph: Graph, concept: URIRef, predicate: URIRef) -> str | None:
    """Return one English-first literal for the predicate, or None."""

    choices: list[tuple[int, str, str]] = []
    for value in graph.objects(concept, predicate):
        if not isinstance(value, Literal):
            continue
        language = (value.language or "").casefold()
        priority = 0 if language == "en" else 1 if not language else 2
        choices.append((priority, language, str(value)))
    if choices:
        return min(choices, key=lambda item: (item[0], item[1], item[2].casefold(), item[2]))[2]
    return None


def _relation_label(relation: str) -> str:
    known = {
        str(SKOS.exactMatch): "exact match",
        str(SKOS.closeMatch): "close match",
        str(SKOS.broadMatch): "broader match",
        str(SKOS.narrowMatch): "narrower match",
        str(SKOS.relatedMatch): "related match",
    }
    return known.get(relation, _iri_tail(relation))


def _validation_reasons(analysis: Graph) -> dict[str, dict[str, str]]:
    """Each machine validation's sealed reason, labelled by the model that gave it.

    The label is the provider model id, because that is what distinguishes the
    two machines to a reader; the provider IRI is the independence claim and is
    already checked elsewhere.
    """

    reasons: dict[str, dict[str, str]] = {}
    for validation, value in analysis.subject_objects(ATLAS.reason):
        if not isinstance(validation, URIRef) or not isinstance(value, Literal):
            continue
        text = str(value).strip()
        if not text:
            continue
        label = next(
            (
                str(item)
                for item in analysis.objects(validation, ATLAS.providerModelId)
                if isinstance(item, Literal)
            ),
            "",
        )
        reasons[str(validation)] = {"label": label, "reason": text}
    return reasons


def _reason_rows(
    reasons: Mapping[str, Mapping[str, str]],
    validation_ids: Sequence[str],
) -> list[dict[str, str]]:
    """The reasons for one decision, ordered by label so two runs read alike."""

    rows = [dict(reasons[value]) for value in validation_ids if value in reasons]
    rows.sort(key=lambda row: (row["label"], row["reason"]))
    return rows


def _edge_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join((kind, *parts)).encode("utf-8")).hexdigest()
    return f"urn:ref:vocabulary-atlas-explorer-edge:{digest}"


def _round_robin(values: Mapping[str, list[dict[str, Any]]]) -> Sequence[dict[str, Any]]:
    queues = {key: deque(rows) for key, rows in sorted(values.items())}
    ordered: list[dict[str, Any]] = []
    while queues:
        exhausted: list[str] = []
        for key, rows in queues.items():
            if rows:
                ordered.append(rows.popleft())
            if not rows:
                exhausted.append(key)
        for key in exhausted:
            del queues[key]
    return ordered


def _parse_dataset(asset: VocabularyAtlasAsset) -> tuple[Graph, Graph]:
    asset._require_verified()
    dataset = Dataset(default_union=False)
    dataset.parse(data=asset.payload.decode("utf-8"), format="nquads")
    graph_rows = {str(row["role"]): row for row in asset.manifest["graphs"]}
    return (
        dataset.graph(URIRef(str(graph_rows["releaseFacts"]["id"]))),
        dataset.graph(URIRef(str(graph_rows["analysis"]["id"]))),
    )


def build_explorer_model(
    asset: VocabularyAtlasAsset,
    *,
    title: str = "RefSpec vocabulary atlas",
    release_labels: Mapping[str, str] | None = None,
    max_nodes: int = _DEFAULT_MAX_NODES,
    max_mappings: int = _DEFAULT_MAX_MAPPINGS,
    max_shared_clusters: int = _DEFAULT_SHARED_CLUSTERS,
) -> dict[str, Any]:
    """Build a bounded browser view from one already verified atlas.

    Qualified mappings are selected first, then cross-release equal-label
    clusters, one representative per otherwise unseen release, and immediate
    hierarchy context.  The selection is deterministic and is disclosed in
    the output; it never claims to be the complete graph.
    """

    if not title.strip():
        raise VocabularyAtlasError("atlas publication title must not be empty")
    if max_nodes < 2:
        raise VocabularyAtlasError("atlas explorer max nodes must be at least 2")
    if max_mappings < 0 or max_shared_clusters < 0:
        raise VocabularyAtlasError("atlas explorer limits must not be negative")
    overrides = {key: value.strip() for key, value in dict(release_labels or {}).items()}
    if any(not key or not value.strip() for key, value in overrides.items()):
        raise VocabularyAtlasError("release label overrides need a non-empty IRI and label")

    release_facts, analysis = _parse_dataset(asset)
    release_ids = tuple(
        sorted(
            str(value)
            for value in set(release_facts.subjects(RDF.type, RKAF.ReferenceResourceRelease))
            if isinstance(value, URIRef)
        )
    )
    if len(release_ids) > max_nodes:
        raise VocabularyAtlasError("atlas explorer max nodes is smaller than the number of releases")
    release_set = set(release_ids)
    unknown_overrides = set(overrides) - release_set
    if unknown_overrides:
        raise VocabularyAtlasError("release label override does not match an atlas reference release")
    release_names = {
        release_id: overrides.get(release_id, _default_release_label(release_id))
        for release_id in release_ids
    }
    member_releases: dict[str, set[str]] = defaultdict(set)
    for member, release in analysis.subject_objects(ATLAS.memberOfRelease):
        if isinstance(member, URIRef) and isinstance(release, URIRef) and str(release) in release_set:
            member_releases[str(member)].add(str(release))

    all_mappings: list[dict[str, Any]] = []
    for mapping in _search_only_mapping_nodes(analysis):
        source = str(_one_resource(analysis, mapping, RKAF.assertsSubject, "mapping source"))
        target = str(_one_resource(analysis, mapping, RKAF.assertsObject, "mapping target"))
        relation = str(_one_resource(analysis, mapping, RKAF.assertsPredicate, "mapping relation"))
        source_release = str(
            _one_resource(analysis, mapping, RKAF.sourceConceptRelease, "mapping source release")
        )
        target_release = str(
            _one_resource(analysis, mapping, RKAF.targetConceptRelease, "mapping target release")
        )
        all_mappings.append(
            {
                "id": str(mapping),
                "source": source,
                "target": target,
                "relation": relation,
                "relationLabel": _relation_label(relation),
                "sourceRelease": source_release,
                "targetRelease": target_release,
                "validationIds": [
                    str(value) for value in _search_only_mapping_validations(analysis, mapping)
                ],
            }
        )

    selected: set[str] = set()
    node_roles: dict[str, set[str]] = defaultdict(set)
    displayed_mappings: list[dict[str, Any]] = []
    for row in all_mappings[:max_mappings]:
        additions = {str(row["source"]), str(row["target"])} - selected
        if len(selected) + len(additions) > max_nodes:
            continue
        selected.update(additions)
        node_roles[str(row["source"])].add("mappingEndpoint")
        node_roles[str(row["target"])].add("mappingEndpoint")
        displayed_mappings.append(row)

    # Lifecycle facts are rare and load-bearing: every deprecated concept and
    # every replacement endpoint is shown, so a retirement is never invisible.
    lifecycle_members: set[str] = set()
    for concept in release_facts.subjects(OWL.deprecated, None):
        if isinstance(concept, URIRef):
            lifecycle_members.add(str(concept))
    for left, right in release_facts.subject_objects(DCTERMS.isReplacedBy):
        if isinstance(left, URIRef) and isinstance(right, URIRef):
            lifecycle_members.update((str(left), str(right)))
    for left, right in release_facts.subject_objects(DCTERMS.replaces):
        if isinstance(left, URIRef) and isinstance(right, URIRef):
            lifecycle_members.update((str(left), str(right)))
    for member in sorted(lifecycle_members):
        if len(selected) >= max_nodes:
            break
        if member in member_releases:
            selected.add(member)
            node_roles[member].add("lifecycle")

    cluster_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cluster in sorted(
        {
            value
            for value in analysis.subjects(RDF.type, ATLAS.LabelCluster)
            if isinstance(value, URIRef)
        },
        key=str,
    ):
        members = sorted(
            {
                str(value)
                for value in analysis.objects(cluster, ATLAS.member)
                if isinstance(value, URIRef)
            }
        )
        cluster_releases = sorted(
            {
                release
                for member in members
                for release in member_releases.get(member, ())
                if release in release_set
            }
        )
        if len(cluster_releases) < 2:
            continue
        # A single pathological label must not consume the whole browser view.
        release_first: list[str] = []
        remaining: list[str] = []
        seen_releases: set[str] = set()
        for member in members:
            member_release = next(
                (
                    release
                    for release in sorted(member_releases.get(member, ()))
                    if release in release_set
                ),
                "",
            )
            if member_release and member_release not in seen_releases:
                release_first.append(member)
                seen_releases.add(member_release)
            else:
                remaining.append(member)
        chosen_members = (release_first + remaining)[:8]
        normalized = next(
            (
                str(value)
                for value in analysis.objects(cluster, ATLAS.normalizedLabel)
                if isinstance(value, Literal)
            ),
            "",
        )
        cluster_groups["|".join(cluster_releases)].append(
            {
                "id": str(cluster),
                "members": chosen_members,
                "normalizedLabel": normalized,
            }
        )
    for rows in cluster_groups.values():
        rows.sort(key=lambda row: (str(row["normalizedLabel"]).casefold(), str(row["id"])))

    displayed_clusters: list[dict[str, Any]] = []
    for row in _round_robin(cluster_groups):
        if len(displayed_clusters) >= max_shared_clusters:
            break
        additions = set(row["members"]) - selected
        if len(selected) + len(additions) > max_nodes:
            continue
        selected.update(additions)
        for member in row["members"]:
            node_roles[str(member)].add("sharedLabel")
        displayed_clusters.append(row)

    # Show every reference release even when it has no qualified mapping or
    # selected cross-release label cluster.
    for release_id in release_ids:
        if any(release_id in member_releases.get(member, ()) for member in selected):
            continue
        representative = next(
            (
                str(value)
                for value in sorted(
                    {
                        member
                        for member in release_facts.objects(URIRef(release_id), PROV.hadMember)
                        if isinstance(member, URIRef)
                    },
                    key=str,
                )
                if str(value) in member_releases
            ),
            None,
        )
        if representative is not None and len(selected) < max_nodes:
            selected.add(representative)
            node_roles[representative].add("releaseRepresentative")

    # Immediate parents come before children because they explain where a
    # mapped or shared concept sits with fewer nodes in most thesauri. USE
    # targets and lead-in terms come with them: a non-descriptor without its
    # descriptor renders as a bare identifier.
    context_candidates: list[str] = []
    roots = tuple(sorted(selected))
    for member in roots:
        node = URIRef(member)
        parents = sorted(
            str(value) for value in release_facts.objects(node, SKOS.broader) if isinstance(value, URIRef)
        )
        children = sorted(
            str(value) for value in release_facts.subjects(SKOS.broader, node) if isinstance(value, URIRef)
        )
        use_neighbours = sorted(
            str(value)
            for predicate in (
                ATLAS.thesaurusUse,
                ATLAS.thesaurusUsedFor,
                DCTERMS.isReplacedBy,
                DCTERMS.replaces,
            )
            for value in release_facts.objects(node, predicate)
            if isinstance(value, URIRef)
        )
        context_candidates.extend(parents)
        context_candidates.extend(children)
        context_candidates.extend(use_neighbours)
    for member in context_candidates:
        if len(selected) >= max_nodes:
            break
        if member not in selected and member in member_releases:
            selected.add(member)
            node_roles[member].add("hierarchyContext")

    primary_release = {
        member: min(member_releases[member])
        for member in selected
        if member_releases.get(member)
    }
    nodes = []
    for member in sorted(primary_release):
        concept = URIRef(member)
        roles = set(node_roles.get(member, {"hierarchyContext"}))
        if next(release_facts.objects(concept, SKOS.topConceptOf), None) is not None or next(
            release_facts.subjects(SKOS.hasTopConcept, concept), None
        ) is not None:
            roles.add("topConcept")
        node: dict[str, Any] = {
            "id": member,
            "label": _label_for(release_facts, concept),
            "releaseId": primary_release[member],
            "roles": sorted(roles),
        }
        for field, predicate in (
            ("definition", SKOS.definition),
            ("scopeNote", SKOS.scopeNote),
            ("notation", SKOS.notation),
        ):
            value = _note_for(release_facts, concept, predicate)
            if value is not None:
                node[field] = value
        if any(
            isinstance(value, Literal) and str(value).casefold() == "true"
            for value in release_facts.objects(concept, OWL.deprecated)
        ):
            node["deprecated"] = True
        nodes.append(node)
    selected = {str(node["id"]) for node in nodes}

    # Reasons ride on the two edge types that carry a machine's judgement. A
    # shared label or a hierarchy edge is a release fact, not a decision, and
    # attaching prose to those would both mislead and inflate the payload.
    reasons = _validation_reasons(analysis)

    edges: list[dict[str, Any]] = []
    for row in displayed_mappings:
        if row["source"] not in selected or row["target"] not in selected:
            continue
        edges.append(
            {
                "id": row["id"],
                "type": "qualifiedMapping",
                "source": row["source"],
                "target": row["target"],
                "label": row["relationLabel"],
                "relation": row["relation"],
                "validationIds": row["validationIds"],
                "reasons": _reason_rows(reasons, row["validationIds"]),
            }
        )
    for cluster in displayed_clusters:
        members = [member for member in cluster["members"] if member in selected]
        if len(members) < 2:
            continue
        anchor = members[0]
        for member in members[1:]:
            edges.append(
                {
                    "id": _edge_id("sharedLabel", str(cluster["id"]), anchor, member),
                    "type": "sharedLabel",
                    "source": anchor,
                    "target": member,
                    "label": str(cluster["normalizedLabel"]),
                    "clusterId": str(cluster["id"]),
                }
            )
    for child, parent in release_facts.subject_objects(SKOS.broader):
        if not isinstance(child, URIRef) or not isinstance(parent, URIRef):
            continue
        child_id, parent_id = str(child), str(parent)
        if child_id in selected and parent_id in selected:
            edges.append(
                {
                    "id": _edge_id("broader", child_id, parent_id),
                    "type": "broader",
                    "source": child_id,
                    "target": parent_id,
                    "label": "broader concept",
                }
            )
    # One edge per USE reference: the stated thesaurusUse direction, with the
    # reciprocal thesaurusUsedFor inverted into it, because ICPSR's 479 USE and
    # 394 UF statements are not reciprocal and a viewer needs one line, not two.
    use_pairs: set[tuple[str, str]] = set()
    for lead_in, descriptor in release_facts.subject_objects(ATLAS.thesaurusUse):
        if isinstance(lead_in, URIRef) and isinstance(descriptor, URIRef):
            use_pairs.add((str(lead_in), str(descriptor)))
    for descriptor, lead_in in release_facts.subject_objects(ATLAS.thesaurusUsedFor):
        if isinstance(lead_in, URIRef) and isinstance(descriptor, URIRef):
            use_pairs.add((str(lead_in), str(descriptor)))
    for lead_in_id, descriptor_id in sorted(use_pairs):
        if lead_in_id in selected and descriptor_id in selected:
            edges.append(
                {
                    "id": _edge_id("use", lead_in_id, descriptor_id),
                    "type": "use",
                    "source": lead_in_id,
                    "target": descriptor_id,
                    "label": "USE (preferred term)",
                }
            )
    # skos:related is symmetric and thesauri state both directions; the pair
    # renders once, in canonical order.
    related_pairs: set[tuple[str, str]] = set()
    for left, right in release_facts.subject_objects(SKOS.related):
        if isinstance(left, URIRef) and isinstance(right, URIRef):
            related_pairs.add((min(str(left), str(right)), max(str(left), str(right))))
    for left_id, right_id in sorted(related_pairs):
        if left_id in selected and right_id in selected:
            edges.append(
                {
                    "id": _edge_id("related", left_id, right_id),
                    "type": "related",
                    "source": left_id,
                    "target": right_id,
                    "label": "related concept",
                }
            )
    # Lifecycle succession: a retired concept points at its replacement. The
    # stated isReplacedBy direction wins, with reciprocal dcterms:replaces
    # statements inverted into it so one succession is one edge.
    replaced_pairs: set[tuple[str, str]] = set()
    for retired, successor in release_facts.subject_objects(DCTERMS.isReplacedBy):
        if isinstance(retired, URIRef) and isinstance(successor, URIRef):
            replaced_pairs.add((str(retired), str(successor)))
    for successor, retired in release_facts.subject_objects(DCTERMS.replaces):
        if isinstance(retired, URIRef) and isinstance(successor, URIRef):
            replaced_pairs.add((str(retired), str(successor)))
    for retired_id, successor_id in sorted(replaced_pairs):
        if retired_id in selected and successor_id in selected:
            edges.append(
                {
                    "id": _edge_id("replacedBy", retired_id, successor_id),
                    "type": "replacedBy",
                    "source": retired_id,
                    "target": successor_id,
                    "label": "replaced by",
                }
            )
    # The gate's refusals, drawable but default-off in the viewer: every
    # candidate that failed two-independent-machine qualification.
    for candidate in sorted(analysis.subjects(RDF.type, ATLAS.MappingCandidate), key=str):
        if not isinstance(candidate, URIRef):
            continue
        if (candidate, RKAF.usageEligibility, RKAF.notEligible) not in analysis:
            continue
        source_member = next(analysis.objects(candidate, ATLAS.sourceMember), None)
        target_member = next(analysis.objects(candidate, ATLAS.targetMember), None)
        if not isinstance(source_member, URIRef) or not isinstance(target_member, URIRef):
            continue
        source_id, target_id = str(source_member), str(target_member)
        if source_id in selected and target_id in selected:
            # A refusal's validations are found through the candidate, since a
            # refused candidate has no mapping to cite them from.
            refused = sorted(
                str(value)
                for value in analysis.subjects(ATLAS.validates, candidate)
                if isinstance(value, URIRef)
            )
            edges.append(
                {
                    "id": _edge_id("rejectedCandidate", str(candidate)),
                    "type": "rejectedCandidate",
                    "source": source_id,
                    "target": target_id,
                    "label": "not qualified",
                    "candidateId": str(candidate),
                    "reasons": _reason_rows(reasons, refused),
                }
            )
    edges.sort(key=lambda row: (str(row["type"]), str(row["source"]), str(row["target"]), str(row["id"])))

    shown_by_release: dict[str, int] = defaultdict(int)
    for node in nodes:
        shown_by_release[str(node["releaseId"])] += 1
    releases = [
        {
            "id": release_id,
            "label": release_names[release_id],
            "memberCount": len(set(release_facts.objects(URIRef(release_id), PROV.hadMember))),
            "shownNodeCount": shown_by_release[release_id],
        }
        for release_id in release_ids
    ]
    managed_inputs = [
        {
            "manifestDigest": str(value["manifestDigest"]),
            "publicationReleaseId": str(value["publicationReleaseId"]),
            "rulespecGraph": {
                "id": str(value["rulespecGraph"]["id"]),
                "digest": str(value["rulespecGraph"]["digest"]),
            },
        }
        for value in asset.manifest["inputs"]
        if value.get("role") == "ManagedReleaseView"
    ]
    edge_counts = {
        kind: sum(1 for edge in edges if edge["type"] == kind)
        for kind in (
            "qualifiedMapping",
            "sharedLabel",
            "broader",
            "related",
            "use",
            "replacedBy",
            "rejectedCandidate",
        )
    }
    return {
        "type": _EXPLORER_TYPE,
        "schemaVersion": EXPLORER_SCHEMA_VERSION,
        "title": title.strip(),
        "atlas": {
            "assetId": str(asset.manifest["id"]),
            "manifestDigest": asset.manifest_digest,
            "distributionDigest": asset.output_digest,
            "counts": dict(asset.manifest["counts"]),
            "quadCount": int(asset.manifest["output"]["quadCount"]),
            "byteLength": int(asset.manifest["output"]["byteLength"]),
            "managedInputs": managed_inputs,
        },
        "selectionPolicy": {
            "id": "refspec-atlas-explorer-selection-v2",
            "maxNodes": max_nodes,
            "maxMappings": max_mappings,
            "maxSharedLabelClusters": max_shared_clusters,
            "order": [
                "qualifiedMappingEndpoints",
                "lifecycleConcepts",
                "crossReleaseSharedLabelsRoundRobinByReleaseSet",
                "missingReleaseRepresentatives",
                "immediateParentsThenChildrenThenUseNeighbours",
            ],
        },
        "summary": {
            "referenceReleaseCount": len(releases),
            "nodeCount": len(nodes),
            "edgeCount": len(edges),
            "qualifiedMappingCount": edge_counts["qualifiedMapping"],
            "availableQualifiedMappingCount": len(all_mappings),
            "sharedLabelEdgeCount": edge_counts["sharedLabel"],
            "sharedLabelClusterCount": len(displayed_clusters),
            "hierarchyEdgeCount": edge_counts["broader"],
            "relatedEdgeCount": edge_counts["related"],
            "useEdgeCount": edge_counts["use"],
            "replacedByEdgeCount": edge_counts["replacedBy"],
            "rejectedCandidateEdgeCount": edge_counts["rejectedCandidate"],
        },
        "releases": releases,
        "nodes": nodes,
        "edges": edges,
    }


def _gzip_bytes(payload: bytes) -> bytes:
    target = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=target, compresslevel=9, mtime=0) as stream:
        stream.write(payload)
    return target.getvalue()


def _artifact(
    *,
    path: str,
    role: str,
    media_type: str,
    payload: bytes,
    **extra: object,
) -> dict[str, Any]:
    return {
        "path": path,
        "role": role,
        "mediaType": media_type,
        "digest": _digest_bytes(payload),
        "byteLength": len(payload),
        **extra,
    }


@dataclass(frozen=True, slots=True)
class AtlasPublication:
    directory: Path
    manifest: Mapping[str, Any]

    @property
    def manifest_digest(self) -> str:
        return _digest_bytes(_canonical_file_bytes(dict(self.manifest)))


def publish_vocabulary_atlas(
    asset: VocabularyAtlasAsset,
    output: Path | str,
    *,
    title: str = "RefSpec vocabulary atlas",
    release_labels: Mapping[str, str] | None = None,
    max_nodes: int = _DEFAULT_MAX_NODES,
    max_mappings: int = _DEFAULT_MAX_MAPPINGS,
    max_shared_clusters: int = _DEFAULT_SHARED_CLUSTERS,
) -> AtlasPublication:
    """Write a deterministic static publication for one verified atlas."""

    target = Path(output)
    if target.exists() or target.is_symlink():
        raise VocabularyAtlasError("atlas publication output already exists")
    model = build_explorer_model(
        asset,
        title=title,
        release_labels=release_labels,
        max_nodes=max_nodes,
        max_mappings=max_mappings,
        max_shared_clusters=max_shared_clusters,
    )
    atlas_manifest_bytes = asset.manifest_bytes()
    compressed_bytes = _gzip_bytes(asset.payload)
    explorer_bytes = _canonical_file_bytes(model)
    html_bytes = render_atlas_explorer(model).encode("utf-8")
    artifacts = sorted(
        [
            _artifact(
                path=ATLAS_MANIFEST,
                role="canonicalAtlasManifest",
                media_type="application/json",
                payload=atlas_manifest_bytes,
            ),
            _artifact(
                path=COMPRESSED_ATLAS,
                role="compressedCanonicalAtlas",
                media_type="application/n-quads",
                payload=compressed_bytes,
                contentEncoding="gzip",
                uncompressedDigest=asset.output_digest,
                uncompressedByteLength=len(asset.payload),
            ),
            _artifact(
                path=EXPLORER_DATA,
                role="derivedExplorerData",
                media_type="application/json",
                payload=explorer_bytes,
            ),
            _artifact(
                path=EXPLORER_HTML,
                role="offlineExplorer",
                media_type="text/html; charset=utf-8",
                payload=html_bytes,
            ),
        ],
        key=lambda row: str(row["path"]),
    )
    atlas_pin = {
        "assetId": str(asset.manifest["id"]),
        "manifestDigest": asset.manifest_digest,
        "distributionDigest": asset.output_digest,
    }
    publication_digest = binding.canonical_sha256(
        {
            "atlas": atlas_pin,
            "artifacts": artifacts,
            "selectionPolicy": model["selectionPolicy"],
            "title": title.strip(),
        }
    )
    manifest: dict[str, Any] = {
        "id": "urn:ref:vocabulary-atlas-publication:" + publication_digest.removeprefix("sha256:"),
        "type": _PUBLICATION_TYPE,
        "schemaVersion": PUBLICATION_SCHEMA_VERSION,
        "publicationDigest": publication_digest,
        "title": title.strip(),
        "atlas": atlas_pin,
        "selectionPolicy": model["selectionPolicy"],
        "summary": model["summary"],
        "artifacts": artifacts,
    }
    manifest["canonicalPayloadDigest"] = binding.canonical_payload_digest(manifest)
    publication_bytes = _canonical_file_bytes(manifest)

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.mkdir()
    except FileExistsError as error:
        raise VocabularyAtlasError("atlas publication output already exists") from error
    (target / ATLAS_MANIFEST).write_bytes(atlas_manifest_bytes)
    (target / COMPRESSED_ATLAS).write_bytes(compressed_bytes)
    (target / EXPLORER_DATA).write_bytes(explorer_bytes)
    (target / EXPLORER_HTML).write_bytes(html_bytes)
    (target / PUBLICATION_MANIFEST).write_bytes(publication_bytes)
    return AtlasPublication(directory=target.resolve(), manifest=manifest)


def _release_label_overrides(values: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        release_id, separator, label = value.rpartition("=")
        if not separator or not release_id or not label.strip():
            raise VocabularyAtlasError("--release-label must be RELEASE_IRI=DISPLAY_NAME")
        if release_id in result:
            raise VocabularyAtlasError("--release-label repeats a release IRI")
        result[release_id] = label.strip()
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="refspec-publish-vocabulary-atlas")
    parser.add_argument("--atlas", type=Path, required=True, help="directory containing atlas-manifest.json and atlas.nq")
    parser.add_argument("--atlas-manifest-digest", required=True, help="exact SHA-256 pin for atlas-manifest.json")
    parser.add_argument("--atlas-output-digest", required=True, help="exact SHA-256 pin for atlas.nq")
    parser.add_argument("--output", type=Path, required=True, help="new static publication directory")
    parser.add_argument("--title", default="RefSpec vocabulary atlas")
    parser.add_argument(
        "--release-label",
        action="append",
        default=[],
        metavar="RELEASE_IRI=DISPLAY_NAME",
        help="optional display label for one reference release; repeat as needed",
    )
    parser.add_argument("--max-nodes", type=int, default=_DEFAULT_MAX_NODES)
    parser.add_argument("--max-mappings", type=int, default=_DEFAULT_MAX_MAPPINGS)
    parser.add_argument("--max-shared-clusters", type=int, default=_DEFAULT_SHARED_CLUSTERS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    asset = VocabularyAtlasAsset.open(
        args.atlas,
        expected_manifest_digest=args.atlas_manifest_digest,
        expected_output_digest=args.atlas_output_digest,
    )
    publication = publish_vocabulary_atlas(
        asset,
        args.output,
        title=args.title,
        release_labels=_release_label_overrides(args.release_label),
        max_nodes=args.max_nodes,
        max_mappings=args.max_mappings,
        max_shared_clusters=args.max_shared_clusters,
    )
    print(
        json.dumps(
            {
                "publicationId": publication.manifest["id"],
                "publicationManifestDigest": publication.manifest_digest,
                "atlas": publication.manifest["atlas"],
                "summary": publication.manifest["summary"],
                "outputDirectory": str(publication.directory),
                "explorer": str(publication.directory / EXPLORER_HTML),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


__all__ = [
    "ATLAS_MANIFEST",
    "COMPRESSED_ATLAS",
    "EXPLORER_DATA",
    "EXPLORER_HTML",
    "PUBLICATION_MANIFEST",
    "AtlasPublication",
    "build_explorer_model",
    "build_parser",
    "main",
    "publish_vocabulary_atlas",
]
