"""Measure the Atlas 3.1 definition and note fidelity decision.

The program reads the exact eight bulk-SKOS scopes declared by the independent
source-fidelity auditor, then compares their pinned publisher claims with one
named Atlas distribution. It writes measurements only; it does not modify the
publisher inputs or the Atlas artifact.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import platform
import resource as process_resource
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from backports import zstd
from rdflib import Literal, URIRef

from tools import verify_atlas_source_fidelity as audit

MEASUREMENT_VERSION = "fidelity-definitions/1"
ASSERTED_GRAPH = URIRef("urn:ref:atlas:graph:v3:asserted")
RDF_VALUE = f"{audit.RDF}value"
RDFS_COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment"

SOURCE_ALIASES = {
    "eurovoc": "eurovoc-4.24",
    "elsst": "elsst-r6",
    "gemet": "gemet-4.2.3",
    "agrovoc": "agrovoc-c330-bounded-2026-08-03",
    "nasa-thesaurus": "nasa-thesaurus-skos",
    "osti": "doe-osti-semantic-thesaurus-2020",
    "eurovoc-domains": "eurovoc-domains-4.24",
    "nalt": "nalt-core-bounded-concepts-2026-08-03",
}

PREDICATES = {
    "skos:definition": audit.SKOS_DEFINITION,
    "skos:scopeNote": audit.SKOS_SCOPE_NOTE,
    "skos:note": audit.SKOS_NOTE,
    "skos:example": audit.SKOS_EXAMPLE,
    "skos:historyNote": audit.SKOS_HISTORY_NOTE,
    "skos:editorialNote": audit.SKOS_EDITORIAL_NOTE,
    "rdfs:comment": RDFS_COMMENT,
}

WIRE_PREDICATE = {
    "skos:definition": audit.ATLAS_DEFINITION,
    "skos:scopeNote": audit.ATLAS_NOTE,
    "skos:note": audit.ATLAS_NOTE,
    "skos:example": audit.ATLAS_NOTE,
    "skos:historyNote": audit.ATLAS_NOTE,
    "skos:editorialNote": audit.ATLAS_NOTE,
    "rdfs:comment": audit.ATLAS_NOTE,
}

PARQUET_SCHEMA = pa.schema(
    [
        pa.field("definition", pa.string()),
        pa.field("notes", pa.list_(pa.string())),
    ]
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--distribution", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load_rdf_canonical() -> Any:
    path = Path("bindings/atlas/3.1/tools/rdf_canonical.py").resolve()
    spec = importlib.util.spec_from_file_location("fidelity_rdf_canonical", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import canonical RDF renderer from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _construction_units(distribution: Path) -> tuple[dict[str, dict[str, Any]], str]:
    path = distribution / audit.CONSTRUCTION_SUMMARY
    payload = json.loads(path.read_bytes())
    releases = payload.get("releases")
    if not isinstance(releases, list):
        raise ValueError(f"{path}: releases must be an array")
    units: dict[str, dict[str, Any]] = {}
    for release in releases:
        if not isinstance(release, dict) or not isinstance(release.get("key"), str):
            raise ValueError(f"{path}: malformed release row")
        units[release["key"]] = release
    return units, _sha256(path)


def _pack_paths(spec: audit.SourceSpec, units: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    paths: list[str] = []
    for key in spec.release_keys:
        unit = units.get(key)
        if unit is None:
            raise ValueError(f"distribution omits construction unit {key!r}")
        packs = unit.get("rdfPacks")
        if not isinstance(packs, list):
            raise ValueError(f"construction unit {key!r} has malformed rdfPacks")
        for pack in packs:
            if not isinstance(pack, dict) or not isinstance(pack.get("path"), str):
                raise ValueError(f"construction unit {key!r} has malformed pack row")
            paths.append(pack["path"].removeprefix("packs/"))
    return tuple(paths)


def _source_claim_subjects(view: audit.PublisherView) -> frozenset[str]:
    schemes = {
        *view.schemes,
        *(scheme for _, scheme in view.memberships),
        *(scheme for _, scheme in view.top_concept_of),
        *(scheme for scheme, _ in view.has_top_concept),
    }
    return frozenset(
        {
            *view.concepts,
            *schemes,
            *view.resource_annotation_target_claim_counts,
            *(subject for subject, _, _ in view.relations),
            *(obj for _, _, obj in view.relations),
        }
    )


def _literal_key(value: audit.LiteralValue) -> tuple[str, str, str]:
    return (value.value, value.language or "", value.datatype or "")


def _publisher_predicate_claims(
    view: audit.PublisherView,
) -> tuple[
    dict[str, set[tuple[str, audit.LiteralValue]]],
    dict[str, set[tuple[str, str]]],
]:
    direct: dict[str, set[tuple[str, audit.LiteralValue]]] = {
        name: set() for name in PREDICATES
    }
    resource: dict[str, set[tuple[str, str]]] = {name: set() for name in PREDICATES}
    names_by_iri = {iri: name for name, iri in PREDICATES.items()}
    for subject, predicate, value in view.literal_claims:
        name = names_by_iri.get(predicate)
        if name is not None:
            direct[name].add((subject, value))
    for subject, predicate, target in view.iri_claims:
        name = names_by_iri.get(predicate)
        if name is not None:
            resource[name].add((subject, target))
    return direct, resource


def _atlas_values(
    atlas: audit.AtlasView, predicate: str
) -> dict[str, frozenset[audit.LiteralValue]]:
    return atlas.definitions if predicate == audit.ATLAS_DEFINITION else atlas.notes


def _claim_accounting(
    direct: dict[str, set[tuple[str, audit.LiteralValue]]],
    resource: dict[str, set[tuple[str, str]]],
    atlas: audit.AtlasView,
) -> tuple[dict[str, dict[str, int]], int]:
    rows: dict[str, dict[str, int]] = {}
    omitted_total = 0
    for name in PREDICATES:
        target = _atlas_values(atlas, WIRE_PREDICATE[name])
        carried = sum(value in target.get(subject, ()) for subject, value in direct[name])
        literal_count = len(direct[name])
        iri_count = len(resource[name])
        publisher_count = literal_count + iri_count
        omitted = publisher_count - carried
        rows[name] = {
            "publisherClaimCount": publisher_count,
            "publisherLiteralClaimCount": literal_count,
            "publisherIriClaimCount": iri_count,
            "atlasExactLiteralCarryCount": carried,
            "omittedClaimCount": omitted,
        }
        omitted_total += omitted
    return rows, omitted_total


def _english(value: audit.LiteralValue) -> bool:
    return value.language is not None and value.language.casefold() == "en"


def _resolved_english_values(
    view: audit.PublisherView,
    target: str,
) -> frozenset[audit.LiteralValue]:
    return frozenset(
        value
        for subject, predicate, value in view.literal_claims
        if subject == target and predicate == RDF_VALUE and _english(value)
    )


def _expected_english_definition_scope_wire(
    view: audit.PublisherView,
    direct: dict[str, set[tuple[str, audit.LiteralValue]]],
    resource: dict[str, set[tuple[str, str]]],
) -> tuple[
    set[tuple[str, str, audit.LiteralValue]],
    dict[str, int],
]:
    definitions: dict[str, set[audit.LiteralValue]] = defaultdict(set)
    scope_notes: dict[str, set[audit.LiteralValue]] = defaultdict(set)
    direct_claims = 0
    direct_claims_by_predicate = {
        "skos:definition": 0,
        "skos:scopeNote": 0,
    }
    iri_claims = 0
    resolved_iri_claims = 0
    empty_english_text_claims = 0

    for subject, value in direct["skos:definition"]:
        if _english(value):
            if not value.value:
                empty_english_text_claims += 1
                continue
            definitions[subject].add(value)
            direct_claims += 1
            direct_claims_by_predicate["skos:definition"] += 1
    for subject, value in direct["skos:scopeNote"]:
        if _english(value):
            if not value.value:
                empty_english_text_claims += 1
                continue
            scope_notes[subject].add(value)
            direct_claims += 1
            direct_claims_by_predicate["skos:scopeNote"] += 1

    for name, target_rows in (
        ("skos:definition", definitions),
        ("skos:scopeNote", scope_notes),
    ):
        for subject, target in resource[name]:
            iri_claims += 1
            values = frozenset(
                value for value in _resolved_english_values(view, target) if value.value
            )
            if values:
                resolved_iri_claims += 1
                target_rows[subject].update(values)

    expected: set[tuple[str, str, audit.LiteralValue]] = set()
    multi_definition_subject_count = 0
    for subject, values in definitions.items():
        ordered = sorted(values, key=_literal_key)
        if len(ordered) > 1:
            multi_definition_subject_count += 1
        expected.add((subject, audit.ATLAS_DEFINITION, ordered[0]))
        expected.update((subject, audit.ATLAS_NOTE, value) for value in ordered[1:])
    for subject, values in scope_notes.items():
        expected.update((subject, audit.ATLAS_NOTE, value) for value in values)

    return expected, {
        "eligibleDirectLiteralClaimCount": direct_claims,
        "eligibleDirectLiteralClaimsByPredicate": direct_claims_by_predicate,
        "eligibleIriClaimCount": iri_claims,
        "resolvedIriClaimCount": resolved_iri_claims,
        "unresolvedIriClaimCount": iri_claims - resolved_iri_claims,
        "emptyEnglishTextClaimCount": empty_english_text_claims,
        "multiDefinitionSubjectCount": multi_definition_subject_count,
    }


def _current_wire_claims(atlas: audit.AtlasView) -> set[tuple[str, str, audit.LiteralValue]]:
    rows = {
        (subject, audit.ATLAS_DEFINITION, value)
        for subject, values in atlas.definitions.items()
        for value in values
    }
    rows.update(
        (subject, audit.ATLAS_NOTE, value)
        for subject, values in atlas.notes.items()
        for value in values
    )
    return rows


def _nquads_payload(
    rows: set[tuple[str, str, audit.LiteralValue]], rdf_canonical: Any
) -> bytes:
    lines: list[str] = []
    for subject, predicate, value in sorted(
        rows,
        key=lambda row: (row[0], row[1], _literal_key(row[2])),
    ):
        literal = Literal(value.value, lang=value.language, datatype=value.datatype)
        lines.append(
            rdf_canonical.nquads_line(
                URIRef(subject), URIRef(predicate), literal, ASSERTED_GRAPH
            )
        )
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def _parquet_size(rows: list[dict[str, Any]]) -> int:
    sink = pa.BufferOutputStream()
    writer = pq.ParquetWriter(
        sink,
        PARQUET_SCHEMA,
        compression="zstd",
        compression_level=19,
        use_dictionary=[],
        write_statistics=True,
        version="2.6",
        data_page_version="2.0",
    )
    try:
        writer.write_table(
            pa.Table.from_pylist(rows, schema=PARQUET_SCHEMA),
            row_group_size=50_000,
        )
    finally:
        writer.close()
    return sink.getvalue().size


def _parquet_delta(
    atlas: audit.AtlasView,
    additions: set[tuple[str, str, audit.LiteralValue]],
) -> dict[str, int]:
    definitions = {
        subject: sorted(value.value for value in values)
        for subject, values in atlas.definitions.items()
    }
    notes = {
        subject: sorted({value.value for value in values})
        for subject, values in atlas.notes.items()
    }
    proposed_definitions = {subject: list(values) for subject, values in definitions.items()}
    proposed_notes = {subject: list(values) for subject, values in notes.items()}
    conflicts = 0
    for subject, predicate, value in additions:
        if predicate == audit.ATLAS_DEFINITION:
            current = proposed_definitions.setdefault(subject, [])
            if current and value.value not in current:
                conflicts += 1
            elif not current:
                current.append(value.value)
        else:
            current_notes = proposed_notes.setdefault(subject, [])
            if value.value not in current_notes:
                current_notes.append(value.value)
                current_notes.sort()

    resources = sorted(atlas.resources)

    def rows(
        definition_values: dict[str, list[str]], note_values: dict[str, list[str]]
    ) -> list[dict[str, Any]]:
        return [
            {
                "definition": (
                    definition_values.get(resource, [None])[0]
                    if definition_values.get(resource)
                    else None
                ),
                "notes": note_values.get(resource) or None,
            }
            for resource in resources
        ]

    current_size = _parquet_size(rows(definitions, notes))
    proposed_size = _parquet_size(rows(proposed_definitions, proposed_notes))
    return {
        "resourceRowCount": len(resources),
        "currentDefinitionNotesColumnBytes": current_size,
        "proposedDefinitionNotesColumnBytes": proposed_size,
        "incrementalDefinitionNotesColumnBytes": proposed_size - current_size,
        "definitionConflictCount": conflicts,
    }


def _measure_source(
    alias: str,
    spec: audit.SourceSpec,
    source_root: Path,
    distribution: Path,
    units: dict[str, dict[str, Any]],
    rdf_canonical: Any,
) -> dict[str, Any]:
    print(f"measuring {alias}: {spec.name}", flush=True)
    publisher = audit.read_publisher_inputs(source_root, spec)
    packs = _pack_paths(spec, units)
    atlas = audit.read_atlas_source(distribution, packs, _source_claim_subjects(publisher))
    if atlas.structural_failures:
        raise ValueError(
            f"{spec.name}: Atlas pack read failed: {'; '.join(atlas.structural_failures[:5])}"
        )

    direct, resource = _publisher_predicate_claims(publisher)
    claim_counts, omitted_claim_count = _claim_accounting(direct, resource, atlas)
    additional_predicates = (
        ()
        if spec.rdf_source is None
        else tuple(
            predicate
            for predicate in spec.rdf_source.additional_annotation_predicates
            if predicate not in PREDICATES.values()
        )
    )
    additional_annotation_counts = {
        predicate: {
            "publisherLiteralClaimCount": sum(
                claim_predicate == predicate
                for _, claim_predicate, _ in publisher.literal_claims
            ),
            "publisherIriClaimCount": sum(
                claim_predicate == predicate
                for _, claim_predicate, _ in publisher.iri_claims
            ),
        }
        for predicate in additional_predicates
    }
    expected, eligibility = _expected_english_definition_scope_wire(
        publisher, direct, resource
    )
    current = _current_wire_claims(atlas)
    additions = expected - current
    payload = _nquads_payload(additions, rdf_canonical)
    text_bytes = sum(len(value.value.encode("utf-8")) for _, _, value in additions)
    compressed = (
        zstd.compress(
            payload,
            options={zstd.CompressionParameter.compression_level: 19},
        )
        if payload
        else b""
    )
    parquet = _parquet_delta(atlas, additions)

    publisher_semantic_claim_count = len(publisher.literal_claims) + len(
        publisher.iri_claims
    )
    omission_percentage = (
        100.0 * omitted_claim_count / publisher_semantic_claim_count
        if publisher_semantic_claim_count
        else 0.0
    )
    atlas_definition_count = sum(len(values) for values in atlas.definitions.values())
    atlas_note_count = sum(len(values) for values in atlas.notes.values())
    atlas_quad_count = len(atlas.all_raw_iri_claims) + len(
        atlas.all_raw_literal_claims
    )
    return {
        "alias": alias,
        "auditorSourceName": spec.name,
        "auditorReleaseKeys": list(spec.release_keys),
        "publisherInputPins": [
            {
                "path": pin.path,
                "sha256": pin.sha256,
                "byteLength": pin.byte_length,
                "zipMember": pin.zip_member,
            }
            for pin in spec.inputs
        ],
        "publisherParsedContentDigests": dict(sorted(publisher.input_content_digests.items())),
        "publisherConceptCount": len(publisher.concepts),
        "publisherSemanticClaimCount": publisher_semantic_claim_count,
        "publisherAnnotationClaimsByPredicate": claim_counts,
        "publisherAdditionalAuditorAnnotationClaimsByPredicate": (
            additional_annotation_counts
        ),
        "atlasDefinitionCount": atlas_definition_count,
        "atlasNoteCount": atlas_note_count,
        "atlasQuadCount": atlas_quad_count,
        "omittedListedAnnotationClaimCount": omitted_claim_count,
        "omittedListedAnnotationsPercentOfPublisherSemanticClaims": round(
            omission_percentage, 6
        ),
        "carryEnglishDefinitionAndScopeNote": {
            **eligibility,
            "alreadyPresentWireQuadCount": len(expected & current),
            "incrementalWireQuadCount": len(additions),
            "incrementalDefinitionQuadCount": sum(
                predicate == audit.ATLAS_DEFINITION for _, predicate, _ in additions
            ),
            "incrementalNoteQuadCount": sum(
                predicate == audit.ATLAS_NOTE for _, predicate, _ in additions
            ),
            "incrementalTextUtf8Bytes": text_bytes,
            "incrementalCanonicalNQuadsBytes": len(payload),
            "incrementalCanonicalNQuadsZstd19Bytes": len(compressed),
            "parquetDefinitionNotesColumnEstimate": parquet,
        },
        "atlasPacks": [
            {
                "path": path,
                "sha256": atlas.checked_pack_transports[path][0],
                "byteLength": atlas.checked_pack_transports[path][1],
            }
            for path in packs
        ],
    }


def _totals(sources: list[dict[str, Any]]) -> dict[str, Any]:
    publisher_semantic = sum(row["publisherSemanticClaimCount"] for row in sources)
    omitted = sum(row["omittedListedAnnotationClaimCount"] for row in sources)
    carry = [row["carryEnglishDefinitionAndScopeNote"] for row in sources]
    return {
        "publisherSemanticClaimCount": publisher_semantic,
        "publisherListedAnnotationClaimCount": sum(
            detail["publisherClaimCount"]
            for row in sources
            for detail in row["publisherAnnotationClaimsByPredicate"].values()
        ),
        "atlasDefinitionCount": sum(row["atlasDefinitionCount"] for row in sources),
        "atlasNoteCount": sum(row["atlasNoteCount"] for row in sources),
        "atlasQuadCount": sum(row["atlasQuadCount"] for row in sources),
        "omittedListedAnnotationClaimCount": omitted,
        "omittedListedAnnotationsPercentOfPublisherSemanticClaims": round(
            100.0 * omitted / publisher_semantic if publisher_semantic else 0.0,
            6,
        ),
        "carryEnglishDefinitionAndScopeNote": {
            "incrementalWireQuadCount": sum(row["incrementalWireQuadCount"] for row in carry),
            "incrementalDefinitionQuadCount": sum(
                row["incrementalDefinitionQuadCount"] for row in carry
            ),
            "incrementalNoteQuadCount": sum(row["incrementalNoteQuadCount"] for row in carry),
            "incrementalTextUtf8Bytes": sum(row["incrementalTextUtf8Bytes"] for row in carry),
            "incrementalCanonicalNQuadsBytes": sum(
                row["incrementalCanonicalNQuadsBytes"] for row in carry
            ),
            "incrementalCanonicalNQuadsZstd19BytesPerSourceSum": sum(
                row["incrementalCanonicalNQuadsZstd19Bytes"] for row in carry
            ),
            "incrementalParquetDefinitionNotesColumnBytesPerSourceSum": sum(
                row["parquetDefinitionNotesColumnEstimate"][
                    "incrementalDefinitionNotesColumnBytes"
                ]
                for row in carry
            ),
        },
    }


def main() -> None:
    args = _parse_args()
    source_root = args.source_root.resolve()
    distribution = args.distribution.resolve()
    output = args.output.resolve()
    units, summary_digest = _construction_units(distribution)
    rdf_canonical = _load_rdf_canonical()
    specs = {spec.name: spec for spec in audit.SOURCES if spec.kind == "vocabulary"}

    expected_names = set(SOURCE_ALIASES.values())
    missing = expected_names - specs.keys()
    if missing:
        raise ValueError(f"auditor SOURCES omits expected bulk-SKOS scopes: {sorted(missing)}")

    source_rows: list[dict[str, Any]] = []
    for alias, source_name in SOURCE_ALIASES.items():
        source_rows.append(
            _measure_source(
                alias,
                specs[source_name],
                source_root,
                distribution,
                units,
                rdf_canonical,
            )
        )
        gc.collect()

    peak_rss = process_resource.getrusage(process_resource.RUSAGE_SELF).ru_maxrss
    peak_rss_bytes = peak_rss if platform.system() == "Darwin" else peak_rss * 1024
    payload = {
        "measurementVersion": MEASUREMENT_VERSION,
        "measurementScript": Path(__file__).name,
        "measurementScriptSha256": _sha256(Path(__file__)),
        "auditorVersion": audit.VERIFIER_VERSION,
        "sourceRoot": str(source_root),
        "distribution": str(distribution),
        "constructionSummarySha256": summary_digest,
        "execution": {
            "peakRssBytesObserved": peak_rss_bytes,
            "peakRssLimitBytes": 6 * 1024**3,
            "withinPeakRssLimit": peak_rss_bytes < 6 * 1024**3,
        },
        "method": {
            "sourceScope": (
                "The exact selected PublisherView for each named vocabulary SourceSpec in "
                "tools/verify_atlas_source_fidelity.py."
            ),
            "publisherSemanticClaimDenominator": (
                "Unique IRI-subject literal and IRI-object RDF claims retained in the "
                "auditor's selected publisher view; blank-node claims are outside this denominator."
            ),
            "publisherAnnotationNumerator": (
                "Unique claims using skos:definition, skos:scopeNote, skos:note, "
                "skos:example, skos:historyNote, skos:editorialNote, or rdfs:comment."
            ),
            "atlasCarry": (
                "An exact subject-and-literal match in atlas:definition or atlas:note. "
                "An IRI-valued publisher annotation is not counted as carried by those literal fields."
            ),
            "carryEstimate": (
                "English-tagged skos:definition and skos:scopeNote values only. IRI-valued "
                "annotations are resolved through English rdf:value. One sorted definition per "
                "subject maps to atlas:definition; additional definitions and scope notes map to atlas:note."
            ),
            "wireBytes": (
                "Exact canonical N-Quads rendering under the Atlas 3.1 asserted graph, plus "
                "Zstandard level-19 compression of each source's incremental lines in isolation."
            ),
            "parquetBytes": (
                "Difference between current and proposed definition/notes-only Parquet tables, "
                "using the search view's schema types, 50,000-row groups, Zstandard level 19, "
                "data page v2, and no dictionary encoding for these two columns. Per-file footer "
                "overhead makes this an estimate, not an expected whole-artifact byte delta."
            ),
        },
        "sources": source_rows,
        "totals": _totals(source_rows),
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"peak RSS: {peak_rss_bytes} bytes", flush=True)


if __name__ == "__main__":
    main()
