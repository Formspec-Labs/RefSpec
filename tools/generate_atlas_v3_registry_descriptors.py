#!/usr/bin/env python3
"""Generate or verify the Atlas 3.0 RDF descriptors for the RefSpec registry."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import quote

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, SKOS

ROOT = Path(__file__).resolve().parents[1]
BINDING_TOOLS = ROOT / "bindings" / "atlas" / "3.0" / "tools"
sys.path.insert(0, str(BINDING_TOOLS))
from rdf_canonical import nquads_line, ntriples_term

from refspec.registry.infrastructure.semantic_foundation import SEMANTIC_RINGS

CATALOG = ROOT / "portfolio" / "resource-catalog-v0.json"
INDEX = ROOT / "portfolio" / "atlas-index-v0.json"
PROFILES = ROOT / "bindings" / "atlas" / "3.0" / "registry-resource-profiles.json"
DATASET_OUTPUT = ROOT / "bindings" / "atlas" / "3.0" / "tests" / "registry-descriptors.nq"
PROOF_OUTPUT = ROOT / "bindings" / "atlas" / "3.0" / "tests" / "registry-descriptors.json"

ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")
GRAPH_IRI = URIRef("urn:ref:atlas-v3:registry-descriptors")
EXPORT_FORMAT = "refspec-atlas-registry-descriptors/3.0"
PROFILE_FORMAT = "refspec-atlas-registry-resource-profiles/3.0"
SCHEMA_VERSION = "3.0"
RESOURCE_PROFILES = frozenset(
    {"codeScheme", "conceptScheme", "identifierScheme", "resourceCollection", "structureScheme"}
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

NON_MEMBER_DISPOSITIONS: Mapping[str, str] = {
    "cbo-cost-estimate-feed": "assignmentEvidenceOnly",
    "cfr-list-of-subjects": "assignmentEvidenceOnly",
    "cfr47-procedure": "noPublisherRecord",
    "cms-certification-number-authority": "definitionOnly",
    "court-identifiers-and-controls": "childReleaseOnly",
    "crs-native-controls": "childReleaseOnly",
    "ecfr-govinfo-cfr-structure": "childReleaseOnly",
    "entity-identifier-authorities": "childReleaseOnly",
    "eurovoc-lcsh-alignment": "mappingAssertionsOnly",
    "federal-legislative-identifiers": "childReleaseOnly",
    "federal-register-thesaurus-1995": "historicalEvidenceOnly",
    "frn-authority": "noPublisherRecord",
    "gao-native-controls": "assignmentEvidenceOnly",
    "gao-thesaurus-historical": "historicalEvidenceOnly",
    "lcsh-fast-mapping-references": "reviewWithheld",
    "lda-native-controls": "childReleaseOnly",
    "rin-authority": "assignmentEvidenceOnly",
    "specialist-subject-modules": "resourceFamily",
    "uslm": "noPublisherRecord",
}


class RegistryDescriptorError(ValueError):
    """Raised when the descriptor export inputs or checked artifacts are invalid."""


def _fail(detail: str) -> NoReturn:
    raise RegistryDescriptorError(detail)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _fail(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def load_json(path: Path) -> Mapping[str, Any]:
    """Load one JSON object while rejecting duplicate object keys."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegistryDescriptorError(f"cannot load {path}: {error}") from error
    if not isinstance(value, Mapping):
        _fail(f"{path} must contain a JSON object")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return the platform's compact, key-sorted UTF-8 JSON encoding."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def bytes_sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail(f"{location} must be a non-empty trimmed string")
    return value


def _digest(value: Any, location: str) -> str:
    result = _string(value, location)
    if not _DIGEST.fullmatch(result):
        _fail(f"{location} must be a lowercase SHA-256 digest")
    return result


def _list(value: Any, location: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _fail(f"{location} must be a list")
    return value


def _verify_embedded_digest(
    document: Mapping[str, Any],
    *,
    digest_field: str,
    identity_field: str | None,
    identity_prefix: str | None,
    location: str,
) -> str:
    claimed = _digest(document.get(digest_field), f"{location}.{digest_field}")
    excluded = {digest_field}
    if identity_field is not None:
        excluded.add(identity_field)
    basis = {key: value for key, value in document.items() if key not in excluded}
    actual = canonical_sha256(basis)
    if claimed != actual:
        _fail(f"{location}.{digest_field} differs: claimed={claimed}, actual={actual}")
    if identity_field is not None:
        if identity_prefix is None:
            _fail(f"{location} identity prefix is not configured")
        expected_identity = identity_prefix + claimed.removeprefix("sha256:")
        # Catalog and index use stable identities derived from their semantic digest.
        actual_identity = _string(document.get(identity_field), f"{location}.{identity_field}")
        if actual_identity != expected_identity:
            _fail(f"{location}.{identity_field} differs: expected={expected_identity}, actual={actual_identity}")
    return claimed


def _validated_inputs(
    catalog: Mapping[str, Any],
    index: Mapping[str, Any],
    profiles: Mapping[str, Any],
) -> tuple[
    dict[str, Mapping[str, Any]],
    dict[str, str],
    dict[str, frozenset[str]],
    dict[str, set[str]],
    dict[str, str],
]:
    catalog_digest = _verify_embedded_digest(
        catalog,
        digest_field="catalogDigest",
        identity_field="catalogId",
        identity_prefix="urn:ref:resource-catalog:",
        location="resource catalog",
    )
    index_digest = _verify_embedded_digest(
        index,
        digest_field="indexDigest",
        identity_field="indexId",
        identity_prefix="urn:ref:atlas-index:",
        location="atlas index",
    )
    profile_digest = _verify_embedded_digest(
        profiles,
        digest_field="profileDigest",
        identity_field=None,
        identity_prefix=None,
        location="registry resource profiles",
    )
    if index.get("resourceCatalogDigest") != catalog_digest:
        _fail("atlas index does not pin the supplied resource catalog digest")
    if profiles.get("format") != PROFILE_FORMAT or profiles.get("schemaVersion") != SCHEMA_VERSION:
        _fail("registry resource profiles must use the Atlas 3.0 profile format")
    if profiles.get("namespace") != str(ATLAS):
        _fail(f"registry resource profiles must use namespace {ATLAS}")

    profile_for_kind: dict[str, str] = {}
    rings_for_profile: dict[str, frozenset[str]] = {}
    profile_rows = _list(profiles.get("profiles"), "registry resource profiles.profiles")
    for position, raw_profile in enumerate(profile_rows):
        location = f"registry resource profiles.profiles[{position}]"
        if not isinstance(raw_profile, Mapping):
            _fail(f"{location} must be an object")
        profile = _string(raw_profile.get("profile"), f"{location}.profile")
        if profile not in RESOURCE_PROFILES:
            _fail(f"{location}.profile is unsupported: {profile!r}")
        if profile in rings_for_profile:
            _fail(f"duplicate registry resource profile {profile!r}")
        rings = frozenset(
            _string(value, f"{location}.applicableSemanticRings[{index}]")
            for index, value in enumerate(
                _list(raw_profile.get("applicableSemanticRings"), f"{location}.applicableSemanticRings")
            )
        )
        if not rings <= SEMANTIC_RINGS:
            _fail(f"{location}.applicableSemanticRings contains unsupported values")
        rings_for_profile[profile] = rings
        for kind_position, value in enumerate(_list(raw_profile.get("resourceKinds"), f"{location}.resourceKinds")):
            kind = _string(value, f"{location}.resourceKinds[{kind_position}]")
            if kind in profile_for_kind:
                _fail(f"resource kind {kind!r} is assigned to more than one profile")
            profile_for_kind[kind] = profile
    if set(rings_for_profile) != RESOURCE_PROFILES:
        _fail(
            "registry resource profiles differ; "
            f"missing={sorted(RESOURCE_PROFILES - set(rings_for_profile))}, "
            f"extra={sorted(set(rings_for_profile) - RESOURCE_PROFILES)}"
        )

    resources: dict[str, Mapping[str, Any]] = {}
    catalog_kinds: set[str] = set()
    for position, raw_resource in enumerate(_list(catalog.get("resources"), "resource catalog.resources")):
        location = f"resource catalog.resources[{position}]"
        if not isinstance(raw_resource, Mapping):
            _fail(f"{location} must be an object")
        resource_id = _string(raw_resource.get("resourceId"), f"{location}.resourceId")
        if resource_id in resources:
            _fail(f"duplicate resource catalog resourceId {resource_id!r}")
        kind = _string(raw_resource.get("resourceKind"), f"{location}.resourceKind")
        _string(raw_resource.get("title"), f"{location}.title")
        if kind not in profile_for_kind:
            _fail(f"resource kind {kind!r} has no Atlas 3.0 profile")
        resources[resource_id] = raw_resource
        catalog_kinds.add(kind)
    if catalog_kinds != set(profile_for_kind):
        _fail(
            "profile resource-kind coverage differs from the catalog; "
            f"missing={sorted(catalog_kinds - set(profile_for_kind))}, "
            f"stale={sorted(set(profile_for_kind) - catalog_kinds)}"
        )

    rings_by_resource: dict[str, set[str]] = defaultdict(set)
    rows = _list(index.get("rows"), "atlas index.rows")
    for position, raw_row in enumerate(rows):
        location = f"atlas index.rows[{position}]"
        if not isinstance(raw_row, Mapping):
            _fail(f"{location} must be an object")
        resource_id = _string(raw_row.get("resourceId"), f"{location}.resourceId")
        if resource_id not in resources:
            _fail(f"{location}.resourceId {resource_id!r} is absent from the catalog")
        ring = _string(raw_row.get("semanticRing"), f"{location}.semanticRing")
        if ring not in SEMANTIC_RINGS:
            _fail(f"{location}.semanticRing is unsupported: {ring!r}")
        profile = profile_for_kind[str(resources[resource_id]["resourceKind"])]
        if ring not in rings_for_profile[profile]:
            _fail(f"{location} ring {ring!r} is not supported by profile {profile!r}")
        rings_by_resource[resource_id].add(ring)

    inputs = {
        "atlasIndexDigest": index_digest,
        "registryResourceProfilesDigest": profile_digest,
        "resourceCatalogDigest": catalog_digest,
    }
    return resources, profile_for_kind, rings_for_profile, rings_by_resource, inputs


def scheme_iri(resource_id: str) -> URIRef:
    return URIRef("urn:ref:atlas-resource-scheme:" + quote(resource_id, safe="-._~"))


def source_descriptor_iri(resource_id: str) -> URIRef:
    return URIRef("urn:ref:atlas-source-descriptor:" + quote(resource_id, safe="-._~"))


def rdf_node_digest(graph: Graph, node: URIRef) -> str:
    """Digest sorted outgoing predicate-object N-Triples pairs, excluding the digest."""

    rows = sorted(
        f"{ntriples_term(predicate)} {ntriples_term(obj)} ."
        for predicate, obj in graph.predicate_objects(node)
        if predicate != ATLAS.contentDigest
    )
    if not rows:
        _fail(f"resource scheme {node} has no digestible RDF statements")
    return "sha256:" + hashlib.sha256(("\n".join(rows) + "\n").encode("utf-8")).hexdigest()


def serialize_nquads(graph: Graph) -> bytes:
    """Serialize one graph as sorted, unique, blank-node-free N-Quads."""

    rows: list[str] = []
    for subject, predicate, obj in graph:
        if any(isinstance(term, BNode) for term in (subject, predicate, obj)):
            _fail("registry descriptor graph must not contain blank nodes")
        rows.append(nquads_line(subject, predicate, obj, GRAPH_IRI))
    if len(rows) != len(set(rows)):
        _fail("registry descriptor graph contains duplicate statements")
    return ("\n".join(sorted(rows)) + "\n").encode("utf-8")


def build_registry_descriptors(
    catalog: Mapping[str, Any],
    index: Mapping[str, Any],
    profiles: Mapping[str, Any],
) -> tuple[bytes, bytes]:
    """Build the descriptor N-Quads and its canonical proof manifest."""

    resources, profile_for_kind, _, rings_by_resource, input_digests = _validated_inputs(catalog, index, profiles)
    stale_dispositions = set(NON_MEMBER_DISPOSITIONS) - set(resources)
    if stale_dispositions:
        _fail(f"member dispositions name resources absent from the catalog: {sorted(stale_dispositions)}")
    graph = Graph()
    concept_scheme_count = 0
    disposition_counts: Counter[str] = Counter()
    for resource_id in sorted(resources):
        resource = resources[resource_id]
        profile = profile_for_kind[str(resource["resourceKind"])]
        source_node = source_descriptor_iri(resource_id)
        node = scheme_iri(resource_id)

        graph.add((source_node, RDF.type, ATLAS.RegistrySource))
        graph.add((source_node, DCTERMS.identifier, Literal(resource_id)))
        graph.add((source_node, DCTERMS.title, Literal(str(resource["title"]))))
        disposition = NON_MEMBER_DISPOSITIONS.get(resource_id, "memberRelease")
        disposition_counts[disposition] += 1
        graph.add((source_node, ATLAS.memberDisposition, Literal(disposition)))
        graph.add(
            (
                source_node,
                ATLAS.descriptorPayload,
                Literal(canonical_json_bytes(resource).decode("utf-8"), datatype=RDF.JSON),
            )
        )
        graph.add((source_node, ATLAS.contentDigest, Literal(rdf_node_digest(graph, source_node))))

        # A mapping-only source owns evidence-bearing assertions, not members.
        # REF-014 allows a registry source to supply no ResourceScheme.
        if disposition == "mappingAssertionsOnly":
            continue

        graph.add((node, RDF.type, ATLAS.ResourceScheme))
        # A code list may still supply subject concepts. SKOS requires the
        # object of skos:inScheme to be a skos:ConceptScheme, independently of
        # Atlas's operational resource profile.
        if profile == "conceptScheme" or "subject" in rings_by_resource.get(
            resource_id,
            set(),
        ):
            graph.add((node, RDF.type, SKOS.ConceptScheme))
            concept_scheme_count += 1
        graph.add((node, DCTERMS.identifier, Literal(resource_id)))
        graph.add((node, DCTERMS.title, Literal(str(resource["title"]))))
        graph.add((node, ATLAS.resourceProfile, ATLAS[profile]))
        graph.add((node, ATLAS.sourceDescriptor, source_node))
        for ring in sorted(rings_by_resource.get(resource_id, set())):
            graph.add((node, ATLAS.supportedRing, ATLAS[ring]))
        graph.add((node, ATLAS.contentDigest, Literal(rdf_node_digest(graph, node))))

    dataset = serialize_nquads(graph)
    resource_ids = sorted(resources)
    index_rows = _list(index.get("rows"), "atlas index.rows")
    resource_scheme_count = len(set(graph.subjects(RDF.type, ATLAS.ResourceScheme)))
    supported_ring_statement_count = len(list(graph.triples((None, ATLAS.supportedRing, None))))
    proof: dict[str, Any] = {
        "artifact": {
            "byteLength": len(dataset),
            "path": "registry-descriptors.nq",
            "sha256": bytes_sha256(dataset),
        },
        "counts": {
            "atlasIndexPlacementCount": len(index_rows),
            "conceptSchemeCount": concept_scheme_count,
            "memberDispositionCounts": dict(sorted(disposition_counts.items())),
            "quadCount": len(graph),
            "registrySourceCount": len(resources),
            "resourceSchemeCount": resource_scheme_count,
            "supportedRingStatementCount": supported_ring_statement_count,
        },
        "format": EXPORT_FORMAT,
        "graphIri": str(GRAPH_IRI),
        "inputs": input_digests,
        "resourceIdSetDigest": canonical_sha256(resource_ids),
        "schemaVersion": SCHEMA_VERSION,
    }
    proof["proofDigest"] = canonical_sha256(proof)
    return dataset, canonical_json_bytes(proof) + b"\n"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify checked artifacts (default)")
    mode.add_argument("--write", action="store_true", help="write the generated artifacts")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        catalog = load_json(CATALOG)
        index = load_json(INDEX)
        profiles = load_json(PROFILES)
        dataset, proof = build_registry_descriptors(catalog, index, profiles)
        if args.write:
            DATASET_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            DATASET_OUTPUT.write_bytes(dataset)
            PROOF_OUTPUT.write_bytes(proof)
            print(f"wrote {DATASET_OUTPUT.relative_to(ROOT)}")
            print(f"wrote {PROOF_OUTPUT.relative_to(ROOT)}")
            return 0
        differences = []
        if not DATASET_OUTPUT.is_file() or DATASET_OUTPUT.read_bytes() != dataset:
            differences.append(DATASET_OUTPUT.relative_to(ROOT))
        if not PROOF_OUTPUT.is_file() or PROOF_OUTPUT.read_bytes() != proof:
            differences.append(PROOF_OUTPUT.relative_to(ROOT))
        if differences:
            _fail(
                "checked registry descriptors differ from generation for "
                f"{', '.join(map(str, differences))}; run "
                "tools/generate_atlas_v3_registry_descriptors.py --write"
            )
        proof_value = json.loads(proof)
        counts = proof_value["counts"]
        print(
            "Atlas 3.0 registry descriptors are current: "
            f"{counts['resourceSchemeCount']} schemes, "
            f"{counts['atlasIndexPlacementCount']} index placements, "
            f"{counts['quadCount']} quads"
        )
        return 0
    except (RegistryDescriptorError, OSError, TypeError, ValueError) as error:
        print(f"Atlas 3.0 registry descriptor error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
