"""End-to-end effective-period propagation and historical ``as_of`` controls (ss-2zlv).

Proves ``rkaf:EffectivePeriod`` bounds (source ``effective_from`` /
``effective_through``) survive producer -> compact logical record -> validator
Parquet parity -> Parquet full view (3.3) -> columnar preflight -> compact
search view (1.2) -> DuckDB view / explorer / HTTP API -> SQLite Vocabulary
Pack, with before/start/end/after/undated controls evaluated separately from
lifecycle status (``current``/``superseded``/``rescinded``) and without
changing historical assertion identities or breaking legacy sealed views/packs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import sys
import threading
from datetime import UTC, date, datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError
from urllib.request import urlopen

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from refspec.atlas import explorer_cli
from refspec.atlas.compact_pack import (
    CompactPackError,
    CompactRecordRole,
    EffectiveAsOfDisposition,
    EffectivePeriodError,
    effective_as_of_disposition,
    is_effective_as_of,
    normalize_as_of_utc,
    normalize_compact_record,
    parse_as_of,
    validate_effective_period_bounds,
)
from refspec.atlas.duckdb_view import AtlasDuckDBView, AtlasDuckDBViewError
from refspec.atlas.explorer import (
    _statement_record,
    atlas_parquet_resource,
    build_atlas_explorer_model,
    open_atlas_explorer,
)
from refspec.atlas.parquet_artifact import (
    arrow_schema_sha256,
    canonical_payload_sha256,
    file_sha256,
)
from refspec.atlas.parquet_preflight import (
    APPROVED,
    REVIEW_METHODS,
    AtlasParquetPreflightError,
    validate_atlas_parquet_tables,
)
from refspec.atlas.parquet_search_view import (
    _LEGACY_1_1_SCHEMAS,
    _OMITTED_FIELDS,
    LEGACY_SEARCH_VIEW_SCHEMA_VERSION,
    SEARCH_VIEW_ID_PREFIX,
    SEARCH_VIEW_RECORD_TYPE,
    SEARCH_VIEW_SCHEMA_VERSION,
    build_atlas_parquet_search_view,
    verify_atlas_parquet_search_view,
)
from refspec.atlas.parquet_tables import (
    LEGACY_3_2_TABLE_SCHEMAS,
    TABLE_DIRECTORY,
    TABLE_NAMES,
    AtlasParquetTableWriter,
    logical_records_preserved,
    unpreserved_record_fields,
)
from refspec.atlas.parquet_view import (
    LEGACY_VIEW_SCHEMA_VERSION_3_2,
    VIEW_SCHEMA_VERSION,
    seal_atlas_parquet_view,
    verify_atlas_parquet_view,
)
from refspec.atlas.v3_registry_alignments import (
    load_unified_agenda_gao_cra_priority_mapping_release,
)
from refspec.atlas.vocabulary_pack import AtlasVocabularyPack, build_vocabulary_pack
from refspec.atlas.vocabulary_protocols import RelationPolicy, VocabularyInputError
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
import generate_atlas_v3_full as generator

ATLAS = generator.ATLAS
RKAF = generator.RKAF
SKOS = generator.SKOS
SKOSXL = generator.SKOSXL
DCTERMS = generator.DCTERMS
PROV = generator.PROV
ATLAS_VALIDATE = generator.ATLAS_VALIDATE

_D1 = "sha256:" + "1" * 64
_D2 = "sha256:" + "2" * 64
_D3 = "sha256:" + "3" * 64
_D4 = "sha256:" + "4" * 64

_EQUIVALENT_VALUE = str(ATLAS.equivalentValue)
_BROADER = str(SKOS.broader)


# ---------------------------------------------------------------------------
# 1. Canonical effective-period & as_of helper rules
# ---------------------------------------------------------------------------


def test_effective_period_bound_validation_matches_atlas_shacl_shape() -> None:
    assert validate_effective_period_bounds(None, None) == (None, None)
    assert validate_effective_period_bounds("2026-08-15T00:00:00+00:00", None) == (
        "2026-08-15T00:00:00+00:00",
        None,
    )
    assert validate_effective_period_bounds(
        "2026-08-15T00:00:00+00:00",
        "2026-08-15T23:59:59+00:00",
    ) == ("2026-08-15T00:00:00+00:00", "2026-08-15T23:59:59+00:00")

    with pytest.raises(EffectivePeriodError, match="requires effectivePeriodStart"):
        validate_effective_period_bounds(None, "2026-08-31T23:59:59+00:00")
    with pytest.raises(EffectivePeriodError, match="precedes effectivePeriodStart"):
        validate_effective_period_bounds(
            "2026-08-15T00:00:00+00:00",
            "2026-08-14T23:59:59+00:00",
        )
    for bad_start in (
        "2026-08-15",
        "2026-08-15T00:00:00Z",
        "2026-08-15T01:00:00+00:00",
        "2026-08-15T00:00:00-04:00",
        "2026-02-30T00:00:00+00:00",
    ):
        with pytest.raises(EffectivePeriodError):
            validate_effective_period_bounds(bad_start, None)
    for bad_end in (
        "2026-08-31",
        "2026-08-31T23:59:59Z",
        "2026-08-31T00:00:00+00:00",
        "2026-08-31T23:59:59-04:00",
        "2026-02-30T23:59:59+00:00",
    ):
        with pytest.raises(EffectivePeriodError):
            validate_effective_period_bounds("2026-01-01T00:00:00+00:00", bad_end)


def test_as_of_precision_timezone_inclusive_bounds_and_dispositions() -> None:
    start = "2026-08-15T00:00:00+00:00"
    end = "2026-08-31T23:59:59+00:00"
    est_minus_4 = timezone(timedelta(hours=-4))

    # Before / start / middle / end / after controls on bounded period [start, end]
    assert effective_as_of_disposition(start, end, "2026-08-14") is EffectiveAsOfDisposition.FUTURE_EFFECTIVE
    assert is_effective_as_of(start, end, "2026-08-14") is False
    assert is_effective_as_of(start, end, "2026-08-14T23:59:59+00:00") is False
    assert is_effective_as_of(start, end, "2026-08-14T19:59:59-04:00") is False

    assert effective_as_of_disposition(start, end, "2026-08-15") is EffectiveAsOfDisposition.EFFECTIVE
    assert is_effective_as_of(start, end, date(2026, 8, 15)) is True
    assert is_effective_as_of(start, end, "2026-08-15T00:00:00Z") is True
    assert is_effective_as_of(start, end, datetime(2026, 8, 14, 20, 0, 0, tzinfo=est_minus_4)) is True

    assert effective_as_of_disposition(start, end, "2026-08-31") is EffectiveAsOfDisposition.EFFECTIVE
    assert is_effective_as_of(start, end, "2026-08-31T23:59:59+00:00") is True
    assert is_effective_as_of(start, end, "2026-08-31T19:59:59-04:00") is True

    assert effective_as_of_disposition(start, end, "2026-09-01") is EffectiveAsOfDisposition.EXPIRED
    assert is_effective_as_of(start, end, "2026-09-01") is False
    assert is_effective_as_of(start, end, "2026-08-31T23:59:59.000001+00:00") is False
    assert is_effective_as_of(start, end, "2026-08-31T20:00:00-04:00") is False

    # Open-ended period [start, None] vs undated (None, None)
    assert effective_as_of_disposition(start, None, "2026-08-14") is EffectiveAsOfDisposition.FUTURE_EFFECTIVE
    assert effective_as_of_disposition(start, None, "2026-08-15") is EffectiveAsOfDisposition.EFFECTIVE_OPEN_ENDED
    assert effective_as_of_disposition(start, None, "2099-12-31") is EffectiveAsOfDisposition.EFFECTIVE_OPEN_ENDED
    assert is_effective_as_of(start, None, "2099-12-31") is True

    assert effective_as_of_disposition(None, None, "1990-01-01") is EffectiveAsOfDisposition.UNDATED
    assert effective_as_of_disposition(None, None, "2099-12-31") is EffectiveAsOfDisposition.UNDATED
    assert is_effective_as_of(None, None, "2026-08-14") is True
    assert is_effective_as_of(start, end, None) is True

    assert normalize_as_of_utc("2026-08-14T20:00:00-04:00") == "2026-08-15T00:00:00+00:00"
    assert parse_as_of(date(2026, 8, 15)) == datetime(2026, 8, 15, 0, 0, 0, tzinfo=UTC)

    # Ambiguous naive datetimes and malformed strings are refused.
    for bad in (
        datetime(2026, 8, 15, 12, 0, 0),  # noqa: DTZ001
        "2026-08-15T12:00:00",
        "2026-8-15",
        "2026-08-15 00:00:00+00:00",
        " 2026-08-15",
        "",
        "2026-02-30",
        "not-a-date",
        12345,
        True,
    ):
        with pytest.raises(EffectivePeriodError):
            parse_as_of(bad)  # type: ignore[arg-type]


def test_compact_statement_record_carries_and_validates_effective_periods() -> None:
    base = {
        "id": "urn:ref:atlas-assertion:" + "a" * 64,
        "statementType": "MappingAssertion",
        "subject": "urn:test:val:a",
        "predicate": _EQUIVALENT_VALUE,
        "object": "urn:test:val:b",
        "sourceRelease": "urn:test:rel:1",
        "targetRelease": "urn:test:rel:2",
        "policy": "urn:ref:atlas-policy:" + "6" * 64,
        "assertedAt": "2026-08-15T00:00:00+00:00",
        "assertionIdentityDigest": "sha256:" + "a" * 64,
        "semanticRing": "value",
    }

    undated = normalize_compact_record(CompactRecordRole.STATEMENT, base)
    assert "effectivePeriodStart" not in undated
    assert "effectivePeriodEnd" not in undated

    open_ended = normalize_compact_record(
        CompactRecordRole.STATEMENT,
        {**base, "effectivePeriodStart": "2026-08-15T00:00:00+00:00"},
    )
    assert open_ended["effectivePeriodStart"] == "2026-08-15T00:00:00+00:00"
    assert "effectivePeriodEnd" not in open_ended

    bounded = normalize_compact_record(
        CompactRecordRole.STATEMENT,
        {
            **base,
            "effectivePeriodStart": "2026-08-15T00:00:00+00:00",
            "effectivePeriodEnd": "2026-08-31T23:59:59+00:00",
        },
    )
    assert bounded["effectivePeriodStart"] == "2026-08-15T00:00:00+00:00"
    assert bounded["effectivePeriodEnd"] == "2026-08-31T23:59:59+00:00"
    assert unpreserved_record_fields() == {}
    assert logical_records_preserved() is True

    with pytest.raises(CompactPackError, match="requires effectivePeriodStart"):
        normalize_compact_record(
            CompactRecordRole.STATEMENT,
            {**base, "effectivePeriodEnd": "2026-08-31T23:59:59+00:00"},
        )
    with pytest.raises(CompactPackError, match="precedes effectivePeriodStart"):
        normalize_compact_record(
            CompactRecordRole.STATEMENT,
            {
                **base,
                "effectivePeriodStart": "2026-08-15T00:00:00+00:00",
                "effectivePeriodEnd": "2026-08-14T23:59:59+00:00",
            },
        )
    with pytest.raises(CompactPackError, match="null is forbidden"):
        normalize_compact_record(
            CompactRecordRole.STATEMENT,
            {**base, "effectivePeriodStart": None},
        )


# ---------------------------------------------------------------------------
# 2. Real producer UA-GAO dated mappings & validator parity
# ---------------------------------------------------------------------------


def test_real_ua_gao_producer_and_validator_preserve_effective_period_and_identity(
    tmp_path: Path,
) -> None:
    """Real retained UA-GAO mappings (effective_from=2026-08-15) propagate unchanged through producer, validator, and spool scan."""

    release = load_unified_agenda_gao_cra_priority_mapping_release(ROOT)
    graph = generator._expected_mapping_asserted_graph((release,))
    assertions = sorted(graph.subjects(RDF.type, ATLAS.MappingAssertion))
    assert len(assertions) == 5
    # Exact historical identity digest from ss-no7p stays unchanged.
    assert str(assertions[0]) == (
        "urn:ref:atlas-assertion:1e1194394e37300f243033dc782df5d58c8ec973de166d70c298b6fbf5ae73a5"
    )

    for assertion in assertions:
        compact = normalize_compact_record(
            CompactRecordRole.STATEMENT,
            generator._compact_record_from_graph(graph, assertion, CompactRecordRole.STATEMENT),
        )
        assert compact["effectivePeriodStart"] == "2026-08-15T00:00:00+00:00"
        assert "effectivePeriodEnd" not in compact

        # Independent binding validator parity matches the producer's Parquet row byte-for-byte.
        validator_row = ATLAS_VALIDATE.parquet_row_from_rdf(graph, assertion, "Statement")
        assert validator_row["effective_period_start"] == "2026-08-15T00:00:00+00:00"
        assert validator_row["effective_period_end"] is None
        ATLAS_VALIDATE.check_parquet_row_against_rdf(graph, assertion, "Statement", validator_row)

        # Tampering with effective_period_start or inventing effective_period_end fails parity.
        tampered = {**validator_row, "effective_period_end": "2026-12-31T23:59:59+00:00"}
        with pytest.raises(ATLAS_VALIDATE.AtlasValidationError) as err:
            ATLAS_VALIDATE.check_parquet_row_against_rdf(graph, assertion, "Statement", tampered)
        assert err.value.code == "construction.parquet"

    # Streaming spool sample re-derivation follows rkaf:hasEffectivePeriod across N-Quads lines.
    nq_path = tmp_path / "ua-gao.nq"
    graph_id = URIRef("urn:ref:atlas:graph:v3:asserted")
    with nq_path.open("w", encoding="utf-8", newline="") as handle:
        for s, p, o in graph:
            handle.write(ATLAS_VALIDATE.nquads_line(s, p, o, graph_id) + "\n")
    spool = SimpleNamespace(root=tmp_path, sorted_rdf_paths={(None, None): nq_path})
    derived = generator._StreamingGraphSpool._independent_rows_for_subjects(
        spool,
        [(str(assertions[0]), CompactRecordRole.STATEMENT)],
    )
    assert len(derived) == 1
    assert derived[0]["id"] == str(assertions[0])
    assert derived[0]["effective_period_start"] == "2026-08-15T00:00:00+00:00"
    assert derived[0]["effective_period_end"] is None


# ---------------------------------------------------------------------------
# 3. Full end-to-end fixture: producer -> Parquet 3.3 -> preflight ->
#    compact search view 1.2 -> DuckDB / Explorer / HTTP / VocabularyPack
# ---------------------------------------------------------------------------


def _payload_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)[:-1]).hexdigest()


def _build_end_to_end_dated_corpus(tmp_path: Path) -> dict[str, Any]:
    """Mint a real producer RDF graph with bounded, expired, future-effective, undated, superseded, and rescinded assertions,
    then seal full Parquet view (3.3), compact search view (1.2), and SQLite Vocabulary Pack."""

    graph = Graph()
    policy_payload = {"name": "test-effective-period-policy", "version": "1"}
    policy_bytes = canonical_json_bytes(policy_payload)
    policy_digest = sha256_digest(policy_bytes)
    policy = URIRef("urn:ref:atlas-policy:" + policy_digest.removeprefix("sha256:"))
    graph.add((policy, RDF.type, ATLAS.EditorialPolicy))
    graph.add((policy, ATLAS.policyPayload, Literal(policy_bytes.decode("utf-8").rstrip("\n"), datatype=RDF.JSON)))

    src_rel = URIRef("urn:test:source-release:v1")
    graph.add((src_rel, RDF.type, ATLAS.SourceRelease))
    graph.add((src_rel, ATLAS.sourceIssued, Literal("2025-01-01")))
    graph.add((src_rel, ATLAS.sourceDigest, Literal(_D1)))
    graph.add((src_rel, ATLAS.sourceLocator, URIRef("https://example.test/source-v1.json")))

    rel_a = URIRef("urn:test:atlas-release:val-a")
    rel_b = URIRef("urn:test:atlas-release:val-b")
    rel_sub = URIRef("urn:test:atlas-release:sub")
    scheme_a = URIRef("urn:test:scheme:val-a")
    scheme_b = URIRef("urn:test:scheme:val-b")
    scheme_sub = URIRef("urn:test:scheme:sub")

    for rel, ident, scheme, ring, profile in (
        (rel_a, "val-a-2025", scheme_a, ATLAS.value, ATLAS.codeScheme),
        (rel_b, "val-b-2026", scheme_b, ATLAS.value, ATLAS.codeScheme),
        (rel_sub, "sub-2026", scheme_sub, ATLAS.subject, ATLAS.conceptScheme),
    ):
        graph.add((rel, RDF.type, ATLAS.AtlasRelease))
        graph.add((rel, DCTERMS.identifier, Literal(ident)))
        graph.add((rel, DCTERMS.issued, Literal("2025-01-01")))
        graph.add((rel, ATLAS.inScheme, scheme))
        graph.add((rel, ATLAS.semanticRing, ring))
        graph.add((rel, ATLAS.resourceProfile, profile))
        graph.add((rel, RKAF.membershipMode, RKAF.completeMembership))

    def add_resource(
        res_uri: str,
        label_text: str,
        rel: URIRef,
        scheme: URIRef,
        ring: URIRef,
        profile: URIRef,
        src_index: str,
    ) -> tuple[URIRef, URIRef]:
        res = URIRef(res_uri)
        payload = {"id": res_uri, "label": label_text}
        payload_bytes = canonical_json_bytes(payload).rstrip(b"\n")
        payload_digest = sha256_digest(payload_bytes)
        src_rec = URIRef("urn:ref:atlas-source-record:" + src_index * 64)
        graph.add((src_rec, RDF.type, ATLAS.SourceRecord))
        graph.add((src_rec, ATLAS.inSourceRelease, src_rel))
        graph.add((src_rec, ATLAS.sourceDigest, Literal(payload_digest)))
        graph.add((src_rec, ATLAS.sourceLocator, URIRef(f"https://example.test/row/{src_index}")))
        graph.add((src_rec, ATLAS.nativePayload, Literal(payload_bytes.decode("utf-8"), datatype=RDF.JSON)))
        graph.add((src_rec, ATLAS.representsResource, res))

        graph.add((res, RDF.type, ATLAS.AtlasResource))
        graph.add((res, ATLAS.inRelease, rel))
        graph.add((res, ATLAS.inScheme, scheme))
        graph.add((res, ATLAS.semanticRing, ring))
        graph.add((res, ATLAS.resourceProfile, profile))
        graph.add((res, ATLAS.sourceRecord, src_rec))
        graph.add((res, ATLAS.recordStatus, Literal("active")))

        lbl = URIRef("urn:ref:atlas-label:" + src_index * 64)
        graph.add((lbl, RDF.type, SKOSXL.Label))
        graph.add((res, SKOSXL.prefLabel, lbl))
        graph.add((lbl, SKOSXL.literalForm, Literal(label_text, lang="en")))
        graph.add((lbl, ATLAS.inRelease, rel))
        graph.add((lbl, ATLAS.sourceRecord, src_rec))
        return res, src_rec

    val_seed, src_seed = add_resource("urn:test:val:seed", "Priority Seed", rel_a, scheme_a, ATLAS.value, ATLAS.codeScheme, "1")
    val_bounded, _ = add_resource("urn:test:val:bounded", "Bounded Target", rel_b, scheme_b, ATLAS.value, ATLAS.codeScheme, "2")
    val_expired, _ = add_resource("urn:test:val:expired", "Expired Target", rel_b, scheme_b, ATLAS.value, ATLAS.codeScheme, "3")
    val_future, _ = add_resource("urn:test:val:future", "Future Target", rel_b, scheme_b, ATLAS.value, ATLAS.codeScheme, "4")
    val_superseded_old, _ = add_resource("urn:test:val:sup-old", "Superseded Old Target", rel_b, scheme_b, ATLAS.value, ATLAS.codeScheme, "5")
    val_rescinded, _ = add_resource("urn:test:val:rescinded", "Rescinded Target", rel_b, scheme_b, ATLAS.value, ATLAS.codeScheme, "6")
    sub_child, src_sub = add_resource("urn:test:sub:child", "Subject Child", rel_sub, scheme_sub, ATLAS.subject, ATLAS.conceptScheme, "7")
    sub_parent, _ = add_resource("urn:test:sub:parent", "Subject Parent", rel_sub, scheme_sub, ATLAS.subject, ATLAS.conceptScheme, "8")

    # Mint assertions using the REAL producer _add_assertion()!
    st_bounded = generator._add_assertion(
        graph,
        assertion_type=ATLAS.MappingAssertion,
        ring=ATLAS.value,
        subject=val_seed,
        predicate=ATLAS.equivalentValue,
        obj=val_bounded,
        source_release=rel_a,
        target_release=rel_b,
        policy=policy,
        asserted_at="2026-08-01T00:00:00+00:00",
        effective_period=("2026-08-15T00:00:00+00:00", "2026-08-31T23:59:59+00:00"),
    )
    st_expired = generator._add_assertion(
        graph,
        assertion_type=ATLAS.MappingAssertion,
        ring=ATLAS.value,
        subject=val_seed,
        predicate=ATLAS.equivalentValue,
        obj=val_expired,
        source_release=rel_a,
        target_release=rel_b,
        policy=policy,
        asserted_at="2025-01-01T00:00:00+00:00",
        effective_period=("2025-01-01T00:00:00+00:00", "2025-12-31T23:59:59+00:00"),
    )
    st_future = generator._add_assertion(
        graph,
        assertion_type=ATLAS.MappingAssertion,
        ring=ATLAS.value,
        subject=val_seed,
        predicate=ATLAS.equivalentValue,
        obj=val_future,
        source_release=rel_a,
        target_release=rel_b,
        policy=policy,
        asserted_at="2026-08-01T00:00:00+00:00",
        effective_period=("2027-01-01T00:00:00+00:00", None),
    )
    st_superseded = generator._add_assertion(
        graph,
        assertion_type=ATLAS.MappingAssertion,
        ring=ATLAS.value,
        subject=val_seed,
        predicate=ATLAS.equivalentValue,
        obj=val_superseded_old,
        source_release=rel_a,
        target_release=rel_b,
        policy=policy,
        asserted_at="2026-01-01T00:00:00+00:00",
        effective_period=("2026-01-01T00:00:00+00:00", "2026-12-31T23:59:59+00:00"),
    )
    # st_bounded supersedes st_superseded (lifecycle supersession is separate from effective period!)
    graph.add((st_bounded, RKAF.supersedesAssertion, st_superseded))

    st_rescinded = generator._add_assertion(
        graph,
        assertion_type=ATLAS.MappingAssertion,
        ring=ATLAS.value,
        subject=val_seed,
        predicate=ATLAS.equivalentValue,
        obj=val_rescinded,
        source_release=rel_a,
        target_release=rel_b,
        policy=policy,
        asserted_at="2026-01-01T00:00:00+00:00",
        effective_period=("2026-01-01T00:00:00+00:00", "2026-12-31T23:59:59+00:00"),
    )
    st_undated = generator._add_assertion(
        graph,
        assertion_type=ATLAS.NativeRelationAssertion,
        ring=ATLAS.subject,
        subject=sub_child,
        predicate=SKOS.broader,
        obj=sub_parent,
        source_release=rel_sub,
        target_release=rel_sub,
        policy=policy,
        asserted_at="2026-01-01T00:00:00+00:00",
        effective_period=None,
    )

    # Rescission lifecycle event targeting st_rescinded (separate from effective period!)
    resc_event = URIRef("urn:ref:atlas-lifecycle:rescind-1")
    graph.add((resc_event, RDF.type, RKAF.LifecycleEvent))
    graph.add((resc_event, RKAF.appliesTo, st_rescinded))
    graph.add((resc_event, RKAF.lifecycleEventKind, RKAF.rescission))
    graph.add((resc_event, RKAF.effectiveDate, Literal("2026-06-01T00:00:00+00:00", datatype=XSD.dateTime)))
    graph.add((resc_event, ATLAS.fromRelease, rel_a))
    graph.add((resc_event, ATLAS.sourceRecord, src_seed))

    # Evidence bindings for all 6 statements (approved + officialSourceMetadata -> REF-035 default eligible)
    all_statements = [st_bounded, st_expired, st_future, st_superseded, st_rescinded, st_undated]
    for idx, stmt in enumerate(all_statements, start=1):
        src_for_stmt = src_sub if stmt == st_undated else src_seed
        src_digest = ATLAS_VALIDATE.rdf_node_digest(graph, src_for_stmt)
        ev_temp = URIRef(f"urn:temp:ev:{idx}")
        ev_graph = Graph()
        ev_graph.add((ev_temp, RDF.type, RKAF.EvidenceBinding))
        ev_graph.add((ev_temp, RKAF.bindsAssertion, stmt))
        ev_graph.add((ev_temp, ATLAS.evidenceSourceRecord, src_for_stmt))
        ev_graph.add((ev_temp, ATLAS.evidenceSourceDigest, Literal(src_digest)))
        ev_graph.add((ev_temp, RKAF.attestor, URIRef("urn:test:reviewer")))
        ev_graph.add((ev_temp, RKAF.attestorKind, RKAF.organization))
        ev_graph.add((ev_temp, RKAF.assertionOrigin, RKAF.imported))
        ev_graph.add((ev_temp, RKAF.epistemicBasis, RKAF.sourceExplicit))
        ev_graph.add((ev_temp, RKAF.evidenceRole, RKAF.officialSourceMetadata))
        ev_graph.add((ev_temp, RKAF.evidentiaryFunction, RKAF.supports))
        ev_graph.add((ev_temp, RKAF.decision, RKAF.approved))
        ev_graph.add((ev_temp, RKAF.attestedAt, Literal("2025-01-01T00:00:00+00:00", datatype=XSD.dateTime)))
        ev_digest = ATLAS_VALIDATE.rdf_node_digest(ev_graph, ev_temp)
        ev_iri = URIRef("urn:ref:atlas-evidence:" + ev_digest.removeprefix("sha256:"))
        for _, p, o in ev_graph:
            graph.add((ev_iri, p, o))
        graph.add((ev_iri, ATLAS.contentDigest, Literal(ev_digest)))

    # Project all RDF subjects through the REAL producer _compact_record_from_graph + normalize_compact_record
    role_markers = (
        (CompactRecordRole.RESOURCE, ATLAS.AtlasResource),
        (CompactRecordRole.LABEL, SKOSXL.Label),
        (CompactRecordRole.STATEMENT, ATLAS.RelationAssertion),
        (CompactRecordRole.EVIDENCE_BINDING, RKAF.EvidenceBinding),
        (CompactRecordRole.SOURCE_RECORD, ATLAS.SourceRecord),
        (CompactRecordRole.RELEASE, ATLAS.AtlasRelease),
        (CompactRecordRole.RELEASE, ATLAS.SourceRelease),
        (CompactRecordRole.LIFECYCLE_EVENT, RKAF.LifecycleEvent),
    )
    records_by_role: dict[CompactRecordRole, list[dict[str, Any]]] = {role: [] for role in CompactRecordRole}
    seen_subjects: dict[CompactRecordRole, set[URIRef]] = {role: set() for role in CompactRecordRole}
    for role, marker in role_markers:
        for subj in sorted(graph.subjects(RDF.type, marker), key=str):
            if subj in seen_subjects[role]:
                continue
            seen_subjects[role].add(subj)
            raw = generator._compact_record_from_graph(graph, subj, role)
            records_by_role[role].append(normalize_compact_record(role, raw))

    # Build distribution manifest stub + seal full Parquet view (3.3)
    dist_dir = tmp_path / "distribution"
    dist_dir.mkdir()
    empty_inventory = _payload_digest([])
    binding_digest = "sha256:" + "a" * 64
    summary = {
        "assertedInventoryDigest": empty_inventory,
        "contractDigest": binding_digest,
        "distributionId": "urn:test:effective-dates-dist",
        "type": "AtlasConstructionSummary",
        "version": "3.1",
    }
    summary["canonicalPayloadDigest"] = _payload_digest(summary)
    summary_raw = canonical_json_bytes(summary)
    (dist_dir / "atlas-construction-summary.json").write_bytes(summary_raw)
    dist_manifest: dict[str, Any] = {
        "binding": {
            "contractDigest": binding_digest,
            "ontologyDigest": binding_digest,
            "profileDigest": binding_digest,
            "shapesDigest": binding_digest,
            "validatorId": "refspec-atlas-conformance",
            "validatorVersion": "3.1",
            "version": "3.1",
        },
        "counts": {
            "crossRingRelationAssertions": 0,
            "derivedRelations": 0,
            "identifiers": 0,
            "labels": len(records_by_role[CompactRecordRole.LABEL]),
            "mappingAssertions": 5,
            "nativeRelationAssertions": 1,
            "projectedRelations": 0,
            "relationAssertions": 6,
            "releases": 3,
            "resources": len(records_by_role[CompactRecordRole.RESOURCE]),
            "sourceAssignments": 0,
            "sourceRecords": len(records_by_role[CompactRecordRole.SOURCE_RECORD]),
        },
        "createdAt": "2026-08-15T00:00:00+00:00",
        "distributionId": "urn:test:effective-dates-dist",
        "format": "refspec-atlas-packed-nquads-3.1",
        "graphs": [
            {"graphId": "urn:ref:atlas:graph:v3:asserted", "inventoryDigest": empty_inventory, "packCount": 0, "quadCount": 0, "role": "asserted"},
            {"graphId": "urn:ref:atlas:graph:v3:projection", "inventoryDigest": empty_inventory, "packCount": 0, "quadCount": 0, "role": "projection"},
            {"graphId": "urn:ref:atlas:graph:v3:derived", "inventoryDigest": empty_inventory, "packCount": 0, "quadCount": 0, "role": "derived"},
        ],
        "members": [
            {
                "byteLength": len(summary_raw),
                "digest": sha256_digest(summary_raw),
                "mediaType": "application/json",
                "path": "atlas-construction-summary.json",
                "role": "constructionSummary",
            }
        ],
        "packs": [],
        "schemaVersion": "3.1",
        "type": "AtlasManifest",
    }
    dist_manifest["canonicalPayloadDigest"] = _payload_digest(dist_manifest)
    dist_manifest_raw = canonical_json_bytes(dist_manifest)
    (dist_dir / "atlas-manifest.json").write_bytes(dist_manifest_raw)
    dist_pin = sha256_digest(dist_manifest_raw)

    staged = tmp_path / ".staged"
    with AtlasParquetTableWriter(staged) as writer:
        for role in CompactRecordRole:
            writer.extend(role, records_by_role[role])
        writer.close()

    full_view = tmp_path / "full-view"
    full_manifest = seal_atlas_parquet_view(
        dist_dir,
        staged,
        full_view,
        expected_manifest_digest=dist_pin,
        agency_projection={"status": "notEmitted", "missingReleaseKeys": ["regulations-gov-agencies-roster-2026-08-16"]},
        derived_relations={"status": "notEmitted"},
    )
    full_pin = sha256_digest((full_view / "view-manifest.json").read_bytes())

    search_view = tmp_path / "search-view"
    search_manifest = build_atlas_parquet_search_view(
        full_view,
        search_view,
        expected_manifest_digest=full_pin,
    )
    search_pin = sha256_digest((search_view / "search-view-manifest.json").read_bytes())

    pack_path = tmp_path / "vocab.sqlite"
    build_vocabulary_pack(
        search_view,
        pack_path,
        trusted_manifest_digest=search_pin,
        schemes=(str(scheme_a), str(scheme_b), str(scheme_sub)),
        languages=("en",),
        include_mappings=True,
        include_derived=False,
    )

    return {
        "graph": graph,
        "dist_manifest": dist_manifest,
        "full_view": full_view,
        "full_manifest": full_manifest,
        "full_pin": full_pin,
        "search_view": search_view,
        "search_manifest": search_manifest,
        "search_pin": search_pin,
        "pack_path": pack_path,
        "ids": {
            "bounded": str(st_bounded),
            "expired": str(st_expired),
            "future": str(st_future),
            "superseded": str(st_superseded),
            "rescinded": str(st_rescinded),
            "undated": str(st_undated),
            "val_seed": str(val_seed),
            "val_bounded": str(val_bounded),
            "val_expired": str(val_expired),
            "val_future": str(val_future),
            "val_superseded_old": str(val_superseded_old),
            "val_rescinded": str(val_rescinded),
            "sub_child": str(sub_child),
            "sub_parent": str(sub_parent),
            "rel_a": str(rel_a),
            "rel_b": str(rel_b),
            "rel_sub": str(rel_sub),
            "scheme_a": str(scheme_a),
            "scheme_b": str(scheme_b),
            "scheme_sub": str(scheme_sub),
        },
    }


def test_end_to_end_before_start_end_after_undated_and_lifecycle_separation(
    tmp_path: Path,
) -> None:
    """Prove effective-period controls end to end across validator, Parquet, DuckDB, explorer, HTTP API, and VocabularyPack."""

    corpus = _build_end_to_end_dated_corpus(tmp_path)
    ids = corpus["ids"]
    graph = corpus["graph"]

    # 1. Full Parquet view (3.3) & Validator RDF<->Parquet parity on EVERY statement row!
    assert corpus["full_manifest"]["schemaVersion"] == VIEW_SCHEMA_VERSION == "3.3"
    assert corpus["search_manifest"]["schemaVersion"] == SEARCH_VIEW_SCHEMA_VERSION == "1.2"
    full_stmt_rows = pq.read_table(corpus["full_view"] / "tables/statements.parquet").to_pylist()
    assert len(full_stmt_rows) == 6
    for row in full_stmt_rows:
        ATLAS_VALIDATE.check_parquet_row_against_rdf(graph, URIRef(row["id"]), "Statement", row)

    by_id = {row["id"]: row for row in full_stmt_rows}
    assert by_id[ids["bounded"]]["effective_period_start"] == "2026-08-15T00:00:00+00:00"
    assert by_id[ids["bounded"]]["effective_period_end"] == "2026-08-31T23:59:59+00:00"
    assert by_id[ids["future"]]["effective_period_start"] == "2027-01-01T00:00:00+00:00"
    assert by_id[ids["future"]]["effective_period_end"] is None
    assert by_id[ids["undated"]]["effective_period_start"] is None
    assert by_id[ids["undated"]]["effective_period_end"] is None

    # 2. Columnar preflight passes on the valid 3.3 Parquet tables.
    full_tables = {
        role.value: corpus["full_view"] / TABLE_DIRECTORY / TABLE_NAMES[role]
        for role in CompactRecordRole
    }
    preflight = validate_atlas_parquet_tables(
        full_tables,
        view_counts=corpus["full_manifest"]["counts"],
        distribution_counts=corpus["dist_manifest"]["counts"],
    )
    assert preflight["status"] == "passed"

    # 3. DuckDB view & explorer: before / start / end / after / undated / timezone controls!
    view = open_atlas_explorer(corpus["search_view"], trusted_manifest_digest=corpus["search_pin"])
    try:
        # Unfiltered (as_of=None) retains all 5 value assertions on val_seed.
        unfiltered = atlas_parquet_resource(view, ids["val_seed"])
        assert {r["id"] for r in unfiltered["relations"]} == {
            ids["bounded"],
            ids["expired"],
            ids["future"],
            ids["superseded"],
            ids["rescinded"],
        }

        # Before bounded start (2026-08-14): expired excluded, bounded excluded (future), future excluded;
        # superseded & rescinded (2026-01-01..2026-12-31) are within period (lifecycle is evaluated separately!).
        res_before = view.resource(ids["val_seed"], as_of="2026-08-14")
        assert {r["id"] for r in res_before["relations"]} == {ids["superseded"], ids["rescinded"]}

        # Start day (2026-08-15, inclusive): bounded INCLUDED!
        res_start = view.resource(ids["val_seed"], as_of="2026-08-15")
        assert {r["id"] for r in res_start["relations"]} == {ids["bounded"], ids["superseded"], ids["rescinded"]}
        bounded_rel = next(r for r in res_start["relations"] if r["id"] == ids["bounded"])
        assert bounded_rel["effective_period_start"] == "2026-08-15T00:00:00+00:00"
        assert bounded_rel["effective_period_end"] == "2026-08-31T23:59:59+00:00"

        # End day (2026-08-31 and exact UTC last second 2026-08-31T19:59:59-04:00, inclusive): bounded INCLUDED!
        res_end = view.resource(ids["val_seed"], as_of="2026-08-31T19:59:59-04:00")
        assert ids["bounded"] in {r["id"] for r in res_end["relations"]}

        # After end day (2026-09-01 and 2026-08-31T20:00:00-04:00 == 2026-09-01T00:00:00Z): bounded EXCLUDED!
        res_after = view.resource(ids["val_seed"], as_of="2026-08-31T20:00:00-04:00")
        assert ids["bounded"] not in {r["id"] for r in res_after["relations"]}
        assert {r["id"] for r in res_after["relations"]} == {ids["superseded"], ids["rescinded"]}

        # Historical expired window (2025-12-31): ONLY expired included!
        res_2025 = view.resource(ids["val_seed"], as_of="2025-12-31")
        assert {r["id"] for r in res_2025["relations"]} == {ids["expired"]}

        # Future open-ended start (2027-01-01): ONLY future included!
        res_2027 = view.resource(ids["val_seed"], as_of=date(2027, 1, 1))
        assert {r["id"] for r in res_2027["relations"]} == {ids["future"]}

        # Undated subject native relation is present across ALL dates (past, present, future)!
        for probe in ("2024-01-01", "2025-06-01", "2026-08-14", "2026-08-15", "2026-09-01", "2099-12-31"):
            sub_res = view.resource(ids["sub_child"], as_of=probe)
            assert [r["id"] for r in sub_res["relations"]] == [ids["undated"]]
            assert sub_res["relations"][0]["effective_period_start"] is None
            assert sub_res["relations"][0]["effective_period_end"] is None

        # overview(as_of=...) counts change accurately by date!
        ov_2025 = view.overview(as_of="2025-06-01")
        assert [(e["source"], e["target"], e["count"]) for e in ov_2025["edges"]] == [
            (ids["rel_a"], ids["rel_b"], 1)
        ]
        ov_start = view.overview(as_of="2026-08-15")
        assert [(e["source"], e["target"], e["count"]) for e in ov_start["edges"]] == [
            (ids["rel_a"], ids["rel_b"], 3)
        ]
        ov_after = view.overview(as_of="2026-09-01")
        assert [(e["source"], e["target"], e["count"]) for e in ov_after["edges"]] == [
            (ids["rel_a"], ids["rel_b"], 2)
        ]
        # release_graph(as_of=...) keeps undated internal relation across all dates.
        rg = view.release_graph(ids["rel_sub"], as_of="2024-01-01")
        assert rg["counts"]["relations"] == 1

        # Malformed as_of raises AtlasDuckDBViewError!
        with pytest.raises(AtlasDuckDBViewError):
            view.resource(ids["val_seed"], as_of="2026-08-15T00:00:00")

        # 4. Explorer model preserves lifecycle status (current/superseded/rescinded) SEPARATELY from as_of!
        model_all = build_atlas_explorer_model(view)
        status_all = {r["id"]: (r["status"], r["authoritative"]) for r in model_all["assertedRelations"]}
        assert status_all == {
            ids["bounded"]: ("current", True),
            ids["expired"]: ("current", True),
            ids["future"]: ("current", True),
            ids["superseded"]: ("superseded", False),
            ids["rescinded"]: ("rescinded", False),
            ids["undated"]: ("current", True),
        }

        # On 2026-08-15: future and expired current assertions are excluded, while bounded/superseded/rescinded/undated
        # keep their EXACT lifecycle status and assertion IDs unchanged!
        model_start = build_atlas_explorer_model(view, as_of="2026-08-15")
        status_start = {r["id"]: (r["status"], r["authoritative"]) for r in model_start["assertedRelations"]}
        assert status_start == {
            ids["bounded"]: ("current", True),
            ids["superseded"]: ("superseded", False),
            ids["rescinded"]: ("rescinded", False),
            ids["undated"]: ("current", True),
        }
        bounded_model_rel = next(r for r in model_start["assertedRelations"] if r["id"] == ids["bounded"])
        assert bounded_model_rel["effectivePeriodStart"] == "2026-08-15T00:00:00+00:00"
        assert bounded_model_rel["effectivePeriodEnd"] == "2026-08-31T23:59:59+00:00"
        undated_model_rel = next(r for r in model_start["assertedRelations"] if r["id"] == ids["undated"])
        assert "effectivePeriodStart" not in undated_model_rel
        assert "effectivePeriodEnd" not in undated_model_rel

        # Static shard statement record emits rkaf:effectivePeriodStart / rkaf:effectivePeriodEnd facts only when present.
        bounded_shard = _statement_record(by_id[ids["bounded"]])
        assert any(fact[0] == f"{RKAF}effectivePeriodStart" for fact in bounded_shard["facts"])
        assert any(fact[0] == f"{RKAF}effectivePeriodEnd" for fact in bounded_shard["facts"])
        undated_shard = _statement_record(by_id[ids["undated"]])
        assert not any("effectivePeriod" in fact[0] for fact in undated_shard["facts"])

        # 5. Explorer HTTP server routes ?as_of= to /api/resource and /api/overview, and returns 400 on bad as_of!
        server = ThreadingHTTPServer(("127.0.0.1", 0), explorer_cli._handler(view))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            with urlopen(f"{base_url}/api/resource?id={ids['val_seed']}&as_of=2026-08-15", timeout=5) as resp:
                payload = json.loads(resp.read())
            assert {r["id"] for r in payload["relations"]} == {ids["bounded"], ids["superseded"], ids["rescinded"]}

            with urlopen(f"{base_url}/api/resource?id={ids['val_seed']}&as_of=2026-09-01", timeout=5) as resp:
                payload_after = json.loads(resp.read())
            assert ids["bounded"] not in {r["id"] for r in payload_after["relations"]}

            with pytest.raises(HTTPError) as http_err:
                urlopen(f"{base_url}/api/resource?id={ids['val_seed']}&as_of=not-a-date", timeout=5)
            assert http_err.value.code == 400
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    finally:
        view.close()

    # 6. SQLite Vocabulary Pack: forward, symmetric inverse, expand_sync, RelationPolicy(as_of=...), and async API!
    seed_ref = {"id": ids["val_seed"], "scheme": ids["scheme_a"], "release": ids["rel_a"]}
    bounded_target_ref = {"id": ids["val_bounded"], "scheme": ids["scheme_b"], "release": ids["rel_b"]}
    sub_ref = {"id": ids["sub_child"], "scheme": ids["scheme_sub"], "release": ids["rel_sub"]}

    with AtlasVocabularyPack.open(corpus["pack_path"]) as pack:
        rel_before = pack.related_sync(seed_ref, include_mappings=True, as_of="2026-08-14")
        assert {r["relation"]["id"] for r in rel_before} == {ids["superseded"], ids["rescinded"]}

        rel_start = pack.related_sync(seed_ref, include_mappings=True, as_of="2026-08-15")
        assert {r["relation"]["id"] for r in rel_start} == {ids["bounded"], ids["superseded"], ids["rescinded"]}
        bounded_pack_rel = next(r["relation"] for r in rel_start if r["relation"]["id"] == ids["bounded"])
        assert bounded_pack_rel["effectivePeriodStart"] == "2026-08-15T00:00:00+00:00"
        assert bounded_pack_rel["effectivePeriodEnd"] == "2026-08-31T23:59:59+00:00"

        rel_end = pack.related_sync(seed_ref, include_mappings=True, as_of="2026-08-31")
        assert ids["bounded"] in {r["relation"]["id"] for r in rel_end}

        rel_after = pack.related_sync(seed_ref, include_mappings=True, as_of="2026-09-01")
        assert ids["bounded"] not in {r["relation"]["id"] for r in rel_after}

        rel_future = pack.related_sync(seed_ref, include_mappings=True, as_of="2027-01-01")
        assert [r["relation"]["id"] for r in rel_future] == [ids["future"]]
        assert rel_future[0]["relation"]["effectivePeriodStart"] == "2027-01-01T00:00:00+00:00"
        assert "effectivePeriodEnd" not in rel_future[0]["relation"]

        # Symmetric inverse (edges_rev) respects as_of identically!
        assert pack.related_sync(bounded_target_ref, include_mappings=True, as_of="2026-08-14") == []
        inv_start = pack.related_sync(bounded_target_ref, include_mappings=True, as_of="2026-08-15")
        assert len(inv_start) == 1
        assert inv_start[0]["relation"]["direction"] == "inverse"
        assert inv_start[0]["relation"]["id"] == ids["bounded"]
        assert inv_start[0]["relation"]["effectivePeriodStart"] == "2026-08-15T00:00:00+00:00"
        assert inv_start[0]["relation"]["effectivePeriodEnd"] == "2026-08-31T23:59:59+00:00"
        assert pack.related_sync(bounded_target_ref, include_mappings=True, as_of="2026-09-01") == []

        # expand_sync respects as_of on both forward and symmetric inverse traversals!
        exp_before = pack.expand_sync(bounded_target_ref, include_mappings=True, as_of="2026-08-14")
        assert exp_before == []
        exp_start_1hop = pack.expand_sync(bounded_target_ref, max_depth=1, include_mappings=True, as_of="2026-08-15")
        assert [row["concept"]["id"] for row in exp_start_1hop] == [ids["val_seed"]]
        exp_start_2hop = pack.expand_sync(bounded_target_ref, max_depth=2, include_mappings=True, as_of="2026-08-15")
        assert {row["concept"]["id"] for row in exp_start_2hop} == {
            ids["val_seed"],
            ids["val_superseded_old"],
            ids["val_rescinded"],
        }
        exp_after = pack.expand_sync(bounded_target_ref, include_mappings=True, as_of="2026-09-01")
        assert exp_after == []

        # Undated native edge remains visible across all as_of dates!
        sub_rel_rows = pack.related_sync(sub_ref, as_of="2024-01-01")
        assert [r["relation"]["id"] for r in sub_rel_rows] == [ids["undated"]]
        assert "effectivePeriodStart" not in sub_rel_rows[0]["relation"]

        # DI RelationPolicy(as_of=...) works seamlessly via with_dependencies() and async methods!
        scoped = pack.with_dependencies(relation_policy=RelationPolicy(include_mappings=True, as_of="2025-06-01"))
        scoped_rels = asyncio.run(scoped.related(reference=seed_ref))
        assert [r["relation"]["id"] for r in scoped_rels] == [ids["expired"]]
        scoped_exp = asyncio.run(scoped.expand(reference=seed_ref))
        assert [r["concept"]["id"] for r in scoped_exp] == [ids["val_expired"]]

        # Invalid as_of raises VocabularyInputError("invalid_as_of")!
        with pytest.raises(VocabularyInputError) as exc_info:
            pack.related_sync(seed_ref, include_mappings=True, as_of="2026-08-15T00:00:00")
        assert exc_info.value.code == "invalid_as_of"


# ---------------------------------------------------------------------------
# 4. Preflight refusals on malformed Parquet effective periods
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "start,end",
    [
        (None, "2026-08-31T23:59:59+00:00"),
        ("2026-08-15", None),
        ("2026-08-15T00:00:00Z", None),
        ("2026-08-15T00:00:00+00:00", "2026-08-14T23:59:59+00:00"),
        ("2026-08-15T00:00:00+00:00", "2026-08-31T00:00:00+00:00"),
    ],
)
def test_parquet_preflight_refuses_malformed_effective_period_columns(
    start: str | None,
    end: str | None,
) -> None:
    src_rel = "urn:test:sr"
    atlas_rel = "urn:test:ar"
    src_rec = "urn:test:rec"
    r1, r2 = "urn:test:r1", "urn:test:r2"
    stmt = "urn:test:stmt"
    digest = b"1" * 32
    tables = {
        CompactRecordRole.RESOURCE.value: pa.table(
            {
                "id": [r1, r2],
                "release": [atlas_rel, atlas_rel],
                "scheme": ["urn:test:s", "urn:test:s"],
                "semantic_ring": ["subject", "subject"],
                "resource_profile": ["conceptScheme", "conceptScheme"],
                "source_record": [src_rec, src_rec],
            }
        ),
        CompactRecordRole.LABEL.value: pa.table(
            {
                "id": ["urn:test:l1", "urn:test:l2"],
                "resource": [r1, r2],
                "label_role": ["preferred", "preferred"],
                "value": ["One", "Two"],
                "language": ["en", "en"],
                "release": [atlas_rel, atlas_rel],
                "source_record": [src_rec, src_rec],
            }
        ),
        CompactRecordRole.STATEMENT.value: pa.table(
            {
                "id": [stmt],
                "statement_type": ["NativeRelationAssertion"],
                "subject": [r1],
                "predicate": [_BROADER],
                "object": [r2],
                "source_release": [atlas_rel],
                "target_release": [atlas_rel],
                "semantic_ring": ["subject"],
                "source_ring": pa.array([None], type=pa.string()),
                "target_ring": pa.array([None], type=pa.string()),
                "supersedes_assertion": pa.array([None], type=pa.string()),
                "effective_period_start": pa.array([start], type=pa.string()),
                "effective_period_end": pa.array([end], type=pa.string()),
            }
        ),
        CompactRecordRole.EVIDENCE_BINDING.value: pa.table(
            {
                "id": ["urn:test:ev"],
                "statement": [stmt],
                "source_record": [src_rec],
                "evidence_source_digest": [digest],
                "decision": [APPROVED],
                "evidence_role": [min(REVIEW_METHODS)],
            }
        ),
        CompactRecordRole.SOURCE_RECORD.value: pa.table(
            {"id": [src_rec], "source_release": [src_rel], "content_digest": [digest]}
        ),
        CompactRecordRole.RELEASE.value: pa.table(
            {
                "id": [src_rel, atlas_rel],
                "release_type": ["SourceRelease", "AtlasRelease"],
                "resource_profile": [None, "conceptScheme"],
                "semantic_ring": [None, "subject"],
                "scheme": [None, "urn:test:s"],
            }
        ),
        CompactRecordRole.IDENTIFIER.value: pa.table(
            {
                "id": pa.array([], type=pa.string()),
                "identifier_value": pa.array([], type=pa.string()),
                "identifier_scheme": pa.array([], type=pa.string()),
                "identifies": pa.array([], type=pa.string()),
                "source_record": pa.array([], type=pa.string()),
            }
        ),
        CompactRecordRole.LIFECYCLE_EVENT.value: pa.table({"id": pa.array([], type=pa.string())}),
    }
    counts = {role: tbl.num_rows for role, tbl in tables.items()}
    dist_counts = {
        "crossRingRelationAssertions": 0,
        "identifiers": 0,
        "labels": 2,
        "mappingAssertions": 0,
        "nativeRelationAssertions": 1,
        "relationAssertions": 1,
        "releases": 1,
        "resources": 2,
        "sourceAssignments": 0,
        "sourceRecords": 1,
    }
    with pytest.raises(AtlasParquetPreflightError) as err:
        validate_atlas_parquet_tables(tables, view_counts=counts, distribution_counts=dist_counts)
    assert err.value.code == "preflight.effective-period"


# ---------------------------------------------------------------------------
# 5. Legacy backward compatibility: 3.2 full view, 1.1 search view, legacy SQLite pack
# ---------------------------------------------------------------------------


def test_legacy_3_2_full_view_and_1_1_search_view_and_legacy_sqlite_pack_stay_readable(
    tmp_path: Path,
) -> None:
    """Artifacts sealed before ss-2zlv (lacking effective_period_* columns) still verify, compact, open, and serve cleanly."""

    corpus = _build_end_to_end_dated_corpus(tmp_path)
    ids = corpus["ids"]

    # Build a synthetic legacy 3.2 full view by dropping effective_period_* from statements.parquet and sealing as 3.2.
    legacy_full = tmp_path / "legacy-3-2-full"
    (legacy_full / TABLE_DIRECTORY).mkdir(parents=True)
    legacy_members: list[dict[str, Any]] = []
    for member in corpus["full_manifest"]["members"]:
        role = CompactRecordRole(member["role"])
        src_path = corpus["full_view"] / member["path"]
        dst_path = legacy_full / member["path"]
        if role is CompactRecordRole.STATEMENT:
            tbl = pq.read_table(src_path).drop(["effective_period_start", "effective_period_end"])
            assert tbl.schema == LEGACY_3_2_TABLE_SCHEMAS[CompactRecordRole.STATEMENT]
            pq.write_table(tbl, dst_path, compression="zstd", version="2.6", data_page_version="2.0")
            stored_schema = pq.ParquetFile(dst_path).schema_arrow
            legacy_members.append(
                {
                    **member,
                    "byteLength": dst_path.stat().st_size,
                    "schemaDigest": arrow_schema_sha256(stored_schema),
                    "sha256": file_sha256(dst_path),
                }
            )
        else:
            dst_path.write_bytes(src_path.read_bytes())
            legacy_members.append(dict(member))
    legacy_full_manifest = {
        **corpus["full_manifest"],
        "members": legacy_members,
        "schemaVersion": LEGACY_VIEW_SCHEMA_VERSION_3_2,
    }
    legacy_full_manifest.pop("canonicalPayloadDigest")
    legacy_full_manifest["canonicalPayloadDigest"] = canonical_payload_sha256(legacy_full_manifest)
    (legacy_full / "view-manifest.json").write_bytes(canonical_json_bytes(legacy_full_manifest))
    legacy_full_pin = sha256_digest((legacy_full / "view-manifest.json").read_bytes())

    # Legacy 3.2 full view verifies cleanly!
    verified_3_2 = verify_atlas_parquet_view(legacy_full, expected_manifest_digest=legacy_full_pin)
    assert verified_3_2["schemaVersion"] == "3.2"

    # Compacting a legacy 3.2 full view produces a valid 1.2 search view with NULL (not invented) effective bounds!
    upgraded_search = tmp_path / "upgraded-search"
    upgraded_manifest = build_atlas_parquet_search_view(
        legacy_full,
        upgraded_search,
        expected_manifest_digest=legacy_full_pin,
    )
    assert upgraded_manifest["schemaVersion"] == SEARCH_VIEW_SCHEMA_VERSION == "1.2"
    upgraded_rows = pq.read_table(upgraded_search / "tables/statements.parquet").to_pylist()
    assert all(r["effective_period_start"] is None and r["effective_period_end"] is None for r in upgraded_rows)

    # Build a synthetic legacy 1.1 search view (lacking effective_period_* columns on statements.parquet).
    legacy_search = tmp_path / "legacy-1-1-search"
    (legacy_search / "tables").mkdir(parents=True)
    legacy_search_members: list[dict[str, Any]] = []
    for member in corpus["search_manifest"]["members"]:
        role = CompactRecordRole(member["role"])
        src_path = corpus["search_view"] / member["path"]
        dst_path = legacy_search / member["path"]
        if role is CompactRecordRole.STATEMENT:
            tbl = pq.read_table(src_path).drop(["effective_period_start", "effective_period_end"])
            assert tbl.schema == _LEGACY_1_1_SCHEMAS[CompactRecordRole.STATEMENT]
            pq.write_table(tbl, dst_path, compression="zstd", version="2.6", data_page_version="2.0")
            stored_schema = pq.ParquetFile(dst_path).schema_arrow
            legacy_search_members.append(
                {
                    **member,
                    "byteLength": dst_path.stat().st_size,
                    "schemaDigest": arrow_schema_sha256(stored_schema),
                    "sha256": file_sha256(dst_path),
                }
            )
        else:
            dst_path.write_bytes(src_path.read_bytes())
            legacy_search_members.append(dict(member))
    legacy_search_manifest = {
        **corpus["search_manifest"],
        "members": legacy_search_members,
        "schemaVersion": LEGACY_SEARCH_VIEW_SCHEMA_VERSION,
        "status": {
            "canonicalAtlas": False,
            "consumerViewOnly": True,
            "expansion": "not_used",
            "graphFactsPreserved": True,
            "logicalRecordsPreserved": False,
            "omittedFields": list(_OMITTED_FIELDS),
        },
        "recordType": SEARCH_VIEW_RECORD_TYPE,
        "viewId": SEARCH_VIEW_ID_PREFIX + "c" * 64,
    }
    legacy_search_manifest.pop("canonicalPayloadDigest")
    legacy_search_manifest["canonicalPayloadDigest"] = canonical_payload_sha256(legacy_search_manifest)
    (legacy_search / "search-view-manifest.json").write_bytes(canonical_json_bytes(legacy_search_manifest))
    legacy_search_pin = sha256_digest((legacy_search / "search-view-manifest.json").read_bytes())

    # Legacy 1.1 search view verifies and opens in AtlasDuckDBView, serving as_of queries cleanly as undated!
    verified_1_1 = verify_atlas_parquet_search_view(legacy_search, expected_manifest_digest=legacy_search_pin)
    assert verified_1_1["schemaVersion"] == "1.1"
    with AtlasDuckDBView.open(legacy_search, trusted_manifest_digest=legacy_search_pin) as legacy_duck:
        legacy_res = legacy_duck.resource(ids["val_seed"], as_of="2020-01-01")
        assert len(legacy_res["relations"]) == 5
        legacy_ov = legacy_duck.overview(as_of="2020-01-01")
        assert legacy_ov["edges"][0]["count"] == 5
        with pytest.raises(AtlasDuckDBViewError):
            legacy_duck.resource(ids["val_seed"], as_of="bad-date")

    # Legacy SQLite Vocabulary Pack (edges & edges_rev without effective_period_* columns) opens and serves cleanly!
    legacy_pack_path = tmp_path / "legacy-pack.sqlite"
    legacy_pack_path.write_bytes(corpus["pack_path"].read_bytes())
    con = sqlite3.connect(str(legacy_pack_path))
    con.executescript(
        """
        CREATE TABLE edges_old (
            src_rid INTEGER NOT NULL,
            stmt_kind INTEGER NOT NULL,
            pid INTEGER NOT NULL,
            stmt_pfx INTEGER NOT NULL,
            stmt_suffix TEXT NOT NULL,
            dst_rid INTEGER NOT NULL,
            ref035_default INTEGER NOT NULL,
            rule_id INTEGER NOT NULL,
            PRIMARY KEY (src_rid, stmt_kind, pid, stmt_pfx, stmt_suffix, dst_rid)
        ) WITHOUT ROWID;
        INSERT INTO edges_old
            SELECT src_rid, stmt_kind, pid, stmt_pfx, stmt_suffix, dst_rid, ref035_default, rule_id FROM edges;
        DROP TABLE edges;
        ALTER TABLE edges_old RENAME TO edges;

        CREATE TABLE edges_rev_old (
            dst_rid INTEGER NOT NULL,
            pid INTEGER NOT NULL,
            stmt_pfx INTEGER NOT NULL,
            stmt_suffix TEXT NOT NULL,
            src_rid INTEGER NOT NULL,
            ref035_default INTEGER NOT NULL,
            PRIMARY KEY (dst_rid, pid, stmt_pfx, stmt_suffix, src_rid)
        ) WITHOUT ROWID;
        INSERT INTO edges_rev_old
            SELECT dst_rid, pid, stmt_pfx, stmt_suffix, src_rid, ref035_default FROM edges_rev;
        DROP TABLE edges_rev;
        ALTER TABLE edges_rev_old RENAME TO edges_rev;
        """
    )
    con.commit()
    con.close()

    seed_ref = {"id": ids["val_seed"], "scheme": ids["scheme_a"], "release": ids["rel_a"]}
    with AtlasVocabularyPack.open(legacy_pack_path, verify_pack_digest=False) as legacy_pack:
        legacy_rels = legacy_pack.related_sync(seed_ref, include_mappings=True, as_of="2020-01-01")
        assert len(legacy_rels) == 5
        assert all("effectivePeriodStart" not in r["relation"] for r in legacy_rels)
        legacy_exp = legacy_pack.expand_sync(seed_ref, include_mappings=True, as_of="2020-01-01")
        assert len(legacy_exp) == 5
        with pytest.raises(VocabularyInputError) as exc_info:
            legacy_pack.related_sync(seed_ref, include_mappings=True, as_of="2026-8-15")
        assert exc_info.value.code == "invalid_as_of"
