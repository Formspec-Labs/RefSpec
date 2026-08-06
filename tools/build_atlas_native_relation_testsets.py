"""Build per-source native-relation test sets from the Atlas 3 source-native import.

The Atlas 3 development build carries publisher-asserted intra-vocabulary
relations only (``mappingAssertions`` is zero).  Those relations are expert
editorial decisions that no RefSpec retrieval arm produced, so they are the
only large, independent, typed reference material currently available for the
six-release Atlas.  The 582 historical mapping assertions cannot serve that
role because the retired label-oriented generator produced them.

This tool emits one canonical test set per relation-bearing thesaurus:
Federal Register, ELSST R6, and ICPSR.  It is analysis-support tooling and is
deliberately outside qualification production code.  It asserts no mapping,
changes no release artifact, and makes no provider call.

Three properties of the source data drive the row shape:

* ELSST and ICPSR materialise every symmetric and inverse edge in both
  directions.  Emitting the raw relation list would double every hierarchy and
  associative edge and silently inflate any recall denominator, so rows are
  deduplicated to one canonical edge.
* Federal Register asserts ``skos:related`` in only one direction for part of
  its graph.  That asymmetry is preserved on each row rather than repaired,
  because it is a real property of the published thesaurus.
* Hierarchy is normalised to SKOS ``broader`` orientation, so ``subject`` is
  always the narrower concept and ``object`` always the broader one.

Consumers testing *directional discovery* must ablate hierarchy from the
retrieval input before scoring against the hierarchy rows.  The sparse and
graph arms read parent and child text, so an un-ablated run measures whether
retrieval recovers pairs it was handed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # Direct execution without an editable install.
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from refspec.storage import canonical_json

try:
    from tools import generate_atlas_v3_full as full_build
except ImportError:  # Direct execution places tools/ on sys.path.
    import generate_atlas_v3_full as full_build  # type: ignore[no-redef]


SKOS = "http://www.w3.org/2004/02/skos/core#"
ATLAS_V3 = "https://refspec.org/ns/atlas/v3#"

BROADER = f"{SKOS}broader"
NARROWER = f"{SKOS}narrower"
RELATED = f"{SKOS}related"
THESAURUS_USE = f"{ATLAS_V3}thesaurusUse"
THESAURUS_USED_FOR = f"{ATLAS_V3}thesaurusUsedFor"
THESAURUS_RELATED = f"{ATLAS_V3}thesaurusRelated"

#: Relation class per source predicate.  ``hierarchy`` rows are directed and
#: normalised to broader orientation.  ``associative`` rows are undirected.
#: ``equivalence`` rows are directed from the access term to the preferred one.
RELATION_CLASSES = {
    BROADER: "hierarchy",
    NARROWER: "hierarchy",
    RELATED: "associative",
    THESAURUS_RELATED: "associative",
    THESAURUS_USE: "equivalence",
    THESAURUS_USED_FOR: "equivalence",
}

#: Predicates whose SKOS semantics are symmetric, so a single asserted
#: direction is a publisher asymmetry rather than a directed claim.
SYMMETRIC_PREDICATES = frozenset({RELATED, THESAURUS_RELATED})

#: The three relation-bearing subject thesauri.  The other Atlas 3 releases
#: either carry no native relations or are outside the subject ring.
TEST_SET_SOURCES = ("federal-register-thesaurus-2025", "elsst-r6", "icpsr-subject-thesaurus")

DEFAULT_OUTPUT = ROOT / "research/evidence/atlas-v3-native-relation-testsets-2026-08-06"

SCHEMA_VERSION = "atlas-v3-native-relation-testset-v1"


def _sha256_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _row_id(source: str, relation_class: str, subject: str, obj: str) -> str:
    basis = canonical_json([source, relation_class, subject, obj]).encode("utf-8")
    return hashlib.sha256(basis).hexdigest()


def _concept_block(resource: Any) -> dict[str, Any]:
    """Render one endpoint with every field a retrieval harness may read.

    ICPSR publishes access terms as members whose only label carries the
    ``alternate`` role, so a preferred label is not always available.  ``label``
    is therefore the display label the publisher supplied and ``labelRole``
    records which role it holds.  An ``alternate`` role marks an access term
    rather than a preferred descriptor.
    """
    preferred: list[str] = []
    alternate: list[str] = []
    for label in resource.labels:
        (preferred if label.role == "preferred" else alternate).append(label.value)
    if not preferred and not alternate:
        raise ValueError(f"relation endpoint {resource.iri} carries no label")
    display_role = "preferred" if preferred else "alternate"
    ordered = preferred + alternate if preferred else alternate
    block: dict[str, Any] = {
        "iri": resource.iri,
        "label": ordered[0],
        "labelRole": display_role,
        "altLabels": sorted(set(ordered[1:])),
    }
    if resource.definition:
        block["definition"] = resource.definition
    if resource.notes:
        block["notes"] = list(resource.notes)
    if resource.notations:
        block["notations"] = list(resource.notations)
    return block


def _canonical_edge(predicate: str, subject: str, obj: str) -> tuple[str, str, str]:
    """Return ``(relation_class, canonical_subject, canonical_object)``.

    Hierarchy normalises to broader orientation so the subject is narrower.
    Associative edges are undirected and sort by IRI.  Equivalence normalises
    to access-term-to-preferred-term orientation.
    """
    relation_class = RELATION_CLASSES[predicate]
    if relation_class == "hierarchy":
        # ``A skos:broader B`` means B is broader, so A is already the subject.
        return (relation_class, subject, obj) if predicate == BROADER else (relation_class, obj, subject)
    if relation_class == "associative":
        return (relation_class, *sorted((subject, obj)))
    # ``A thesaurusUse B`` points from the access term to the preferred term.
    return (relation_class, subject, obj) if predicate == THESAURUS_USE else (relation_class, obj, subject)


def _rows_for_release(release: Any) -> list[dict[str, Any]]:
    """Deduplicate a release's native relations into canonical test-set rows."""
    resources = {resource.iri: resource for resource in release.resources}
    asserted: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    payloads: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    raw_directions: dict[tuple[str, str, str], set[tuple[str, str, str]]] = defaultdict(set)

    for relation in release.relations:
        if relation.predicate not in RELATION_CLASSES:
            raise ValueError(f"{release.spec.key}: unmapped native predicate {relation.predicate!r}")
        key = _canonical_edge(relation.predicate, relation.subject, relation.object)
        asserted[key].add(relation.predicate)
        payloads[key].append(relation.source_payload)
        raw_directions[key].add((relation.subject, relation.predicate, relation.object))

    rows: list[dict[str, Any]] = []
    for key in sorted(asserted):
        relation_class, subject_iri, object_iri = key
        for iri in (subject_iri, object_iri):
            if iri not in resources:
                raise ValueError(f"{release.spec.key}: relation endpoint {iri} is not a release member")
        predicates = sorted(asserted[key])
        symmetric = any(predicate in SYMMETRIC_PREDICATES for predicate in predicates)
        directions = raw_directions[key]
        # A symmetric relation asserted in one direction only, or a hierarchy
        # edge without its materialised inverse, is a publisher asymmetry.
        one_way = len(directions) == 1
        row: dict[str, Any] = {
            "id": _row_id(release.spec.key, relation_class, subject_iri, object_iri),
            "source": release.spec.key,
            "sourceRelease": release.atlas_release_iri,
            "relationClass": relation_class,
            "directionality": "undirected" if symmetric else "directed",
            "assertedPredicates": predicates,
            "assertedDirectionCount": len(directions),
            "oneWayInSource": one_way,
            "subject": _concept_block(resources[subject_iri]),
            "object": _concept_block(resources[object_iri]),
            "sourcePayloads": [json.loads(canonical_json(payload)) for payload in payloads[key]],
        }
        rows.append(row)
    return rows


def _relation_class_meaning() -> dict[str, str]:
    return {
        "hierarchy": "subject is the narrower concept; object is the broader concept (SKOS broader orientation)",
        "associative": "subject and object are associated; the row is undirected and sorted by IRI",
        "equivalence": "subject is the publisher access term; object is the preferred term it directs to",
    }


def _release_summary(release: Any, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    class_counts = Counter(str(row["relationClass"]) for row in rows)
    predicate_counts: Counter[str] = Counter()
    for row in rows:
        for predicate in row["assertedPredicates"]:
            predicate_counts[str(predicate)] += 1
    endpoints = {str(row["subject"]["iri"]) for row in rows} | {str(row["object"]["iri"]) for row in rows}
    return {
        "source": release.spec.key,
        "sourceRelease": release.atlas_release_iri,
        "sourceReleaseDigest": release.source_release_digest,
        "releaseResources": len(release.resources),
        "rawNativeRelations": len(release.relations),
        "canonicalRows": len(rows),
        "rowsByRelationClass": dict(sorted(class_counts.items())),
        "rowsByAssertedPredicate": dict(sorted(predicate_counts.items())),
        "oneWayInSourceRows": sum(1 for row in rows if row["oneWayInSource"]),
        "rowsWithAccessTermEndpoint": sum(
            1 for row in rows if "alternate" in (row["subject"]["labelRole"], row["object"]["labelRole"])
        ),
        "distinctEndpointsCovered": len(endpoints),
        "endpointCoverageOfRelease": round(len(endpoints) / len(release.resources), 6),
    }


def load_test_set_releases() -> tuple[Any, ...]:
    """Load only the three relation-bearing subject thesauri."""
    from refspec.atlas.v3_registry_vocabularies import (
        load_elsst_r6_release,
        load_federal_register_2025_release,
    )

    icpsr_spec = next(spec for spec in full_build.SOURCE_SPECS if spec.key == "icpsr-subject-thesaurus")
    releases = {
        "federal-register-thesaurus-2025": lambda: full_build._adapt_registry_release(
            load_federal_register_2025_release()
        ),
        "elsst-r6": lambda: full_build._adapt_registry_release(load_elsst_r6_release()),
        "icpsr-subject-thesaurus": lambda: full_build._load_icpsr(icpsr_spec),
    }
    return tuple(full_build._validate_loaded_release(releases[key]()) for key in TEST_SET_SOURCES)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> tuple[int, str]:
    payload = "".join(f"{canonical_json(row)}\n" for row in rows).encode("utf-8")
    path.write_bytes(payload)
    return len(payload), _sha256_bytes(payload)


def build_test_sets(output: Path) -> dict[str, Any]:
    """Emit one canonical JSON Lines test set per source plus a manifest."""
    output.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []

    for release in load_test_set_releases():
        rows = _rows_for_release(release)
        path = output / f"{release.spec.key}.jsonl"
        size, digest = _write_jsonl(path, rows)
        summaries.append(_release_summary(release, rows))
        files.append(
            {
                "source": release.spec.key,
                "path": path.name,
                "rows": len(rows),
                "bytes": size,
                "sha256": digest,
            }
        )

    manifest = {
        "type": "AtlasNativeRelationTestSetManifest",
        "schemaVersion": SCHEMA_VERSION,
        "languageScope": "en",
        "semanticRing": "subject",
        "provenance": {
            "assertionKind": "native",
            "reviewMethod": "publisherAssertion",
            "containsMappingAssertions": False,
            "note": (
                "Every row is a publisher-asserted intra-vocabulary relation. No RefSpec "
                "retrieval arm, scorer, or judge produced any row."
            ),
        },
        "canonicalisation": {
            "relationClassMeaning": _relation_class_meaning(),
            "deduplication": (
                "ELSST and ICPSR materialise symmetric and inverse edges in both directions; "
                "rows are deduplicated to one canonical edge per endpoint pair and relation class."
            ),
            "oneWayInSource": (
                "True when the publisher asserted only one direction for this edge. For symmetric "
                "SKOS predicates this records a source asymmetry rather than a directed claim."
            ),
            "endpointLabels": (
                "'label' is the publisher display label and is always present. 'labelRole' is "
                "'preferred' for a descriptor and 'alternate' for an access term, which ICPSR "
                "publishes as members carrying only an alternate-role label."
            ),
        },
        "ablationRequirement": (
            "Scoring retrieval against hierarchy rows requires removing broader and narrower text "
            "from the concept input first. The sparse and graph arms read parent and child labels, "
            "so an un-ablated run measures recovery of pairs the arms were handed."
        ),
        "totals": {
            "canonicalRows": sum(summary["canonicalRows"] for summary in summaries),
            "rawNativeRelations": sum(summary["rawNativeRelations"] for summary in summaries),
        },
        "sources": summaries,
        "files": files,
    }
    manifest_path = output / "manifest.json"
    manifest_bytes = f"{canonical_json(manifest)}\n".encode()
    manifest_path.write_bytes(manifest_bytes)
    manifest["manifestDigest"] = _sha256_bytes(manifest_bytes)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Directory for the emitted test sets.")
    args = parser.parse_args()

    manifest = build_test_sets(args.output)
    for summary in manifest["sources"]:
        classes = " ".join(f"{name}={count}" for name, count in summary["rowsByRelationClass"].items())
        print(
            f"{summary['source']:<34} raw={summary['rawNativeRelations']:>6} "
            f"rows={summary['canonicalRows']:>6}  {classes}"
        )
    print(f"total canonical rows: {manifest['totals']['canonicalRows']}")
    print(f"manifest: {args.output / 'manifest.json'} {manifest['manifestDigest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
