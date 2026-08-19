from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import subprocess
import threading
from collections.abc import Mapping
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from rdflib import Namespace

from refspec.atlas import agency_projection, explorer_cli
from refspec.atlas.compact_pack import (
    CompactRecordRole,
    compact_record_fields,
    normalize_compact_record,
)
from refspec.atlas.derived_graph import (
    EVIDENCE_INPUT_SOURCE_RECORD,
    AssertedFactView,
    DerivationContext,
    DerivationRule,
    DerivedRelationRow,
    DerivedRuleOutcome,
    build_derived_row,
)
from refspec.atlas.duckdb_view import AtlasDuckDBView, AtlasDuckDBViewError
from refspec.atlas.explorer import (
    atlas_explorer_facets,
    atlas_parquet_resource,
    build_atlas_explorer_model,
    build_atlas_explorer_static_shards,
    open_atlas_explorer,
    render_atlas_parquet_explorer,
    render_atlas_v3_explorer,
    search_atlas_parquet,
)

RKAF = Namespace("https://rulespec.org/ns/v1#")

from refspec.atlas.explorer_data import AtlasExplorerData
from refspec.atlas.explorer_frontend import render_atlas_explorer_frontend
from refspec.atlas.parquet_artifact import (
    arrow_schema_sha256,
    canonical_payload_sha256,
    file_sha256,
)
from refspec.atlas.parquet_search_view import (
    SEARCH_VIEW_SCHEMA_VERSION,
    AtlasParquetSearchViewError,
    build_atlas_parquet_search_view,
    verify_atlas_parquet_search_view,
)
from refspec.atlas.parquet_tables import (
    AGENCY_PROJECTION_ROLE,
    AGENCY_PROJECTION_UNRESOLVED_ROLE,
    DERIVED_RELATION_ROLE,
    TABLE_SCHEMAS,
    AtlasParquetTableError,
    AtlasParquetTableWriter,
    column_name,
    derived_relation_manifest_metadata,
    derived_relation_parquet_row,
    logical_records_preserved,
    unpreserved_record_fields,
    write_agency_projection_tables,
    write_derived_relation_table,
)
from refspec.atlas.parquet_view import (
    VIEW_SCHEMA_VERSION,
    AtlasParquetViewError,
    seal_atlas_parquet_view,
    verify_atlas_parquet_view,
)
from refspec.atlas.registry_claim_input import (
    AtlasRegistryClaimInput,
    adapt_registry_claim_release,
    validate_atlas_parquet_registry_claims,
)
from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes, sha256_digest
from refspec.registry.infrastructure.registry_claim_release import (
    RegistryClaim,
    RegistryRawInput,
    build_registry_claim_release,
)
from refspec.release_model import canonical_native_json_bytes

_D1 = "sha256:" + "1" * 64
_D2 = "sha256:" + "2" * 64
_D3 = "sha256:" + "3" * 64
_D4 = "sha256:" + "4" * 64
_D5 = "sha256:" + "5" * 64


#: The rows each fixture distribution's served view carries, keyed by that
#: distribution's resolved path. The builder stages these tables during its own
#: graph walk; a test has no graph, so it re-stages them on demand.
_STAGED_RECORDS: dict[str, dict[CompactRecordRole, list[Mapping[str, object]]]] = {}


def _stage_tables(source: Path, staged: Path) -> None:
    writer = AtlasParquetTableWriter(staged)
    try:
        for role, records in _STAGED_RECORDS[str(source.resolve())].items():
            for record in records:
                writer.add(role, normalize_compact_record(role, record))
        writer.close()
    except BaseException:
        writer.__exit__()
        raise


def _seal_view(source: Path, output: Path, *, expected_manifest_digest: str) -> dict[str, object]:
    """Stage this fixture's tables the way the builder does, then seal them."""

    staged = output.parent / f".{output.name}.staged-tables"
    _stage_tables(source, staged)
    return seal_atlas_parquet_view(
        source,
        staged,
        output,
        expected_manifest_digest=expected_manifest_digest,
        agency_projection={
            "status": "notEmitted",
            "missingReleaseKeys": [
                "regulations-gov-agencies-roster-2026-08-16"
            ],
        },
        derived_relations={"status": "notEmitted"},
    )


#: A rule object shaped exactly like the registered ones, deliberately never
#: registered: `build_derived_row` takes the rule explicitly, and the view
#: machinery must not care which rules the producer registry holds.
_DERIVED_TEST_RULE = DerivationRule(
    rule_iri="urn:test:rule:test-broader",
    engine_iri="https://refspec.org/code/test-deriver",
    engine_version="1",
    evidence_input_kind=EVIDENCE_INPUT_SOURCE_RECORD,
    watch_predicates=frozenset(),
    evidence_nodes=lambda facts: frozenset(),
    derive=lambda context: DerivedRuleOutcome(rows=()),
    label="view-fixture rule",
)


def _canonical_sha256(payload: object, *, terminal_lf: bool) -> str:
    raw = canonical_json_bytes(payload)
    if not terminal_lf:
        raw = raw.rstrip(b"\n")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _derived_relation_rows() -> tuple[DerivedRelationRow, ...]:
    """Two real derived rows, identified by the binding's own formulas."""

    first_record = "urn:ref:atlas-source-record:" + "a" * 64
    second_record = "urn:ref:atlas-source-record:" + "b" * 64
    context = DerivationContext(
        facts=AssertedFactView(),
        node_digest={first_record: _D1, second_record: _D2},
        canonical_sha256=_canonical_sha256,
        generated_at="2026-08-16T00:00:00+00:00",
    )
    return (
        build_derived_row(
            rule=_DERIVED_TEST_RULE,
            subject="urn:test:resource",
            predicate="http://www.w3.org/2004/02/skos/core#broader",
            obj="urn:test:parent",
            ring="https://refspec.org/ns/atlas/v3#subject",
            evidence=(first_record, second_record),
            context=context,
        ),
        build_derived_row(
            rule=_DERIVED_TEST_RULE,
            subject="urn:test:parent",
            predicate="http://www.w3.org/2004/02/skos/core#broader",
            obj="urn:test:grandparent",
            ring="https://refspec.org/ns/atlas/v3#subject",
            evidence=(second_record,),
            context=context,
        ),
    )


def _seal_view_with_derived_relations(
    source: Path,
    output: Path,
    *,
    expected_manifest_digest: str,
    rows: tuple[DerivedRelationRow, ...],
) -> dict[str, object]:
    """Like ``_seal_view``, but also stages and declares the derived table."""

    staged = output.parent / f".{output.name}.staged-tables"
    _stage_tables(source, staged)
    write_derived_relation_table(staged, rows)
    return seal_atlas_parquet_view(
        source,
        staged,
        output,
        expected_manifest_digest=expected_manifest_digest,
        agency_projection={
            "status": "notEmitted",
            "missingReleaseKeys": [
                "regulations-gov-agencies-roster-2026-08-16"
            ],
        },
        derived_relations=derived_relation_manifest_metadata(rows),
    )


def _agency_projection_fixture() -> agency_projection.AgencyProjection:
    """A small, real REF-038-shaped projection: one resolved value, one abstention.

    Hand-built rather than derived from the real regulations.gov/Federal
    Register rosters -- tests/test_agency_projection.py already proves parity
    against those with the full 321/10-row projection -- so this stays a
    fast, self-contained fixture. Every field still goes through the same
    dataclass validation and content-derived digests
    (`agency_projection._digest`) the real projection does, and its resolved
    org points at ``_fixture_distribution``'s one resource so the projection
    lookup's cross-reference to a known Atlas resource is real too.
    """

    source_record = agency_projection.AgencyProjectionSourceRecord(
        release_key="test-regulations-gov-roster",
        release_digest=_D1,
        resource="urn:test:regulations-gov:EPA",
        source_locator="https://example.test/regulations-gov",
        source_digest=_D2,
        field="agencyId",
        value="EPA",
        publisher_name="Environmental Protection Agency",
    )
    target_record = agency_projection.AgencyProjectionSourceRecord(
        release_key="test-federal-register-roster",
        release_digest=_D3,
        resource="urn:test:resource",
        source_locator="https://example.test/federal-register",
        source_digest=_D4,
        field="name",
        value="Environmental Protection Agency",
        publisher_name="Environmental Protection Agency",
    )
    evidence_content = {
        "evidence_tier": "E4",
        "warrant": "humanReview",
        "reviewer": "urn:test:reviewer",
        "adjudicated_on": "2026-08-16",
        "decision_record": "docs/decisions.md#ref-038",
        "decision": "approved",
        "decision_basis": "exactPublisherNameEquality",
        "relation": agency_projection.ATLAS_SAME_ENTITY_AS,
        "name_similarity_used": False,
        "reasoning": "Exact publisher name equality between the two rosters.",
        "source_record": source_record.to_dict(),
        "target_record": target_record.to_dict(),
    }
    evidence_id = "urn:ref:agency-projection-evidence:" + agency_projection._digest(
        evidence_content
    ).removeprefix("sha256:")
    evidence = agency_projection.AgencyProjectionEvidenceRecord(
        record_id=evidence_id,
        evidence_tier="E4",
        warrant="humanReview",
        reviewer="urn:test:reviewer",
        adjudicated_on="2026-08-16",
        decision_record="docs/decisions.md#ref-038",
        decision="approved",
        decision_basis="exactPublisherNameEquality",
        relation=agency_projection.ATLAS_SAME_ENTITY_AS,
        name_similarity_used=False,
        reasoning="Exact publisher name equality between the two rosters.",
        source_record=source_record,
        target_record=target_record,
    )
    row = agency_projection.AgencyProjectionRow(
        source_value_kind="regulationsGovAgencyId",
        source_value="EPA",
        org="urn:test:resource",
        pref_label="Environmental Protection Agency",
        abbreviations=("EPA",),
        aliases=(),
        parent_org=None,
        relation=agency_projection.ATLAS_SAME_ENTITY_AS,
        evidence_tier="E4",
        warrant="humanReview",
        basis="exactPublisherNameEquality",
        evidence_records=(evidence,),
    )
    unresolved_row = agency_projection.AgencyProjectionUnresolvedRow(
        source_value_kind="regulationsGovAgencyId",
        source_value="ARCTICGAS",
        source_org="Arctic Gas Task Force",
        pref_label="Arctic Gas Task Force",
        source_parent_org=None,
        reason="noCounterpartInHeldRosters",
        reasoning="No held roster carries a counterpart entity for this docket prefix.",
        candidate_resources=(),
        closest_non_adopted_candidate=None,
    )
    coverage = agency_projection.AgencyProjectionCoverage(
        source_value_kind="regulationsGovAgencyId",
        source_value_count=2,
        resolved_value_count=1,
        unresolved_value_count=1,
        basis_counts={"exactPublisherNameEquality": 1},
        unresolved_reason_counts={"noCounterpartInHeldRosters": 1},
        rows_with_parent_org=0,
        evidence_record_count=1,
    )
    projection_content = {
        "rows": [row.to_dict()],
        "unresolved": [unresolved_row.to_dict()],
        "coverage": coverage.to_dict(),
    }
    return agency_projection.AgencyProjection(
        rows=(row,),
        unresolved=(unresolved_row,),
        coverage=coverage,
        digest=agency_projection._digest(projection_content),
    )


def _seal_view_with_agency_projection(
    source: Path,
    output: Path,
    *,
    expected_manifest_digest: str,
    projection: agency_projection.AgencyProjection,
) -> dict[str, object]:
    """Like ``_seal_view``, but also stages and declares REF-038's projection tables."""

    staged = output.parent / f".{output.name}.staged-tables"
    _stage_tables(source, staged)
    write_agency_projection_tables(staged, projection)
    return seal_atlas_parquet_view(
        source,
        staged,
        output,
        expected_manifest_digest=expected_manifest_digest,
        agency_projection={
            "status": "emitted",
            "decision": "REF-038",
            "digest": projection.digest,
            "coverage": projection.coverage.to_dict(),
        },
        derived_relations={"status": "notEmitted"},
    )


def _payload_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)[:-1]).hexdigest()


def _write_json(path: Path, value: dict[str, object]) -> bytes:
    payload = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _fixture_distribution(
    root: Path,
    *,
    staged_tables: Path | None = None,
    source_native_payload: Mapping[str, object] | None = None,
    source_digest: str = _D3,
    include_alias: bool = False,
    include_mapping: bool = False,
    derived_relation_count: int | None = None,
) -> str:
    release = "urn:test:atlas-release"
    source_record = "urn:ref:atlas-source-record:" + "5" * 64
    statement = "urn:ref:atlas-assertion:" + "3" * 64
    rows = {
        CompactRecordRole.RESOURCE: {
            "id": "urn:test:resource",
            "release": release,
            "scheme": "urn:test:scheme",
            "semanticRing": "subject",
            "resourceProfile": "conceptScheme",
            "sourceRecord": source_record,
            "definition": "A test resource.",
            "notes": ["A note."],
            "notations": ["T-1"],
            "recordStatus": "active",
            "contentDigest": _D1,
        },
        CompactRecordRole.LABEL: {
            "id": "urn:ref:atlas-label:" + "7" * 64,
            "resource": "urn:test:resource",
            "labelRole": "preferred",
            "value": "Test resource",
            "language": "en",
            "release": release,
            "sourceRecord": source_record,
            "contentDigest": _D2,
        },
        CompactRecordRole.STATEMENT: {
            "id": statement,
            "statementType": "NativeRelationAssertion",
            "subject": "urn:test:resource",
            "predicate": "http://www.w3.org/2004/02/skos/core#broader",
            "object": "urn:test:parent",
            "sourceRelease": release,
            "targetRelease": release,
            "policy": "urn:ref:atlas-policy:" + "6" * 64,
            "assertedAt": "2026-08-07T00:00:00+00:00",
            "assertionIdentityDigest": _D3,
            "semanticRing": "subject",
            "contentDigest": _D4,
        },
        CompactRecordRole.EVIDENCE_BINDING: {
            "id": "urn:ref:atlas-evidence:" + "2" * 64,
            "statement": statement,
            "sourceRecord": source_record,
            "evidenceSourceDigest": _D1,
            "attestor": "urn:test:reviewer",
            "attestorKind": "urn:test:attestor-kind",
            "assertionOrigin": "urn:test:origin",
            "epistemicBasis": "urn:test:basis",
            "evidenceRole": "urn:test:role",
            "evidentiaryFunction": "urn:test:function",
            "decision": "urn:test:approved",
            "attestedAt": "2026-08-07T00:00:00+00:00",
            "contentDigest": _D2,
        },
        CompactRecordRole.SOURCE_RECORD: {
            "id": source_record,
            "sourceRelease": "urn:test:source-release",
            "sourceDigest": source_digest,
            "sourceLocator": "https://example.test/source",
            "nativePayload": (
                {"publisher": "Example", "values": [1, 2]}
                if source_native_payload is None
                else source_native_payload
            ),
            "representsResource": "urn:test:resource",
            "contentDigest": _D4,
        },
        CompactRecordRole.RELEASE: {
            "id": release,
            "releaseType": "AtlasRelease",
            "identifier": "test-release",
            "issued": "2026-08-07",
            "resourceProfile": "conceptScheme",
            "semanticRing": "subject",
            "scheme": "urn:test:scheme",
            "membershipMode": "complete",
            "contentDigest": _D1,
        },
        CompactRecordRole.IDENTIFIER: {
            "id": "urn:ref:atlas-identifier:" + "8" * 64,
            "identifierValue": "T-1",
            "identifierScheme": "urn:test:identifier-scheme",
            "identifies": "urn:test:resource",
            "sourceRecord": source_record,
            "contentDigest": _D2,
        },
        CompactRecordRole.LIFECYCLE_EVENT: {
            "id": "urn:test:event",
            "appliesTo": "urn:test:resource",
            "lifecycleEventKind": "urn:test:created",
            "effectiveDate": "2026-08-07T00:00:00+00:00",
            "sourceRecords": [source_record],
            "toRelease": release,
            "contentDigest": _D3,
        },
    }
    records_by_role: dict[CompactRecordRole, list[Mapping[str, object]]] = {}
    for role, row in rows.items():
        records = [row]
        if include_alias and role is CompactRecordRole.LABEL:
            records.append(
                {
                    "id": "urn:ref:atlas-label:" + "9" * 64,
                    "resource": "urn:test:resource",
                    "labelRole": "alternate",
                    "value": "Fixture alias",
                    "language": "en",
                    "release": release,
                    "sourceRecord": source_record,
                    "contentDigest": _D3,
                }
            )
        if include_mapping and role is CompactRecordRole.RESOURCE:
            records.append(
                {
                    "id": "urn:test:parent",
                    "release": release,
                    "scheme": "urn:test:scheme",
                    "semanticRing": "subject",
                    "resourceProfile": "conceptScheme",
                    "sourceRecord": source_record,
                    "definition": "A parent resource.",
                    "notes": [],
                    "notations": [],
                    "recordStatus": "active",
                    "contentDigest": _D2,
                }
            )
        if include_mapping and role is CompactRecordRole.RELEASE:
            records.append(
                {
                    "id": "urn:test:atlas-release-b",
                    "releaseType": "AtlasRelease",
                    "identifier": "test-release-b",
                    "issued": "2026-08-07",
                    "resourceProfile": "conceptScheme",
                    "semanticRing": "subject",
                    "scheme": "urn:test:scheme-b",
                    "membershipMode": "complete",
                    "contentDigest": _D2,
                }
            )
        if include_mapping and role is CompactRecordRole.STATEMENT:
            for suffix, identity_digest, source_release, target_release in (
                ("4", _D4, release, "urn:test:atlas-release-b"),
                ("5", _D5, "urn:test:atlas-release-b", release),
            ):
                records.append(
                    {
                        "id": "urn:ref:atlas-assertion:" + suffix * 64,
                        "statementType": "MappingAssertion",
                        "subject": "urn:test:resource",
                        "predicate": "http://www.w3.org/2004/02/skos/core#exactMatch",
                        "object": "urn:test:parent",
                        "sourceRelease": source_release,
                        "targetRelease": target_release,
                        "policy": "urn:ref:atlas-policy:" + "6" * 64,
                        "assertedAt": "2026-08-07T00:00:00+00:00",
                        "assertionIdentityDigest": identity_digest,
                        "semanticRing": "subject",
                        "contentDigest": _D1,
                    }
                )
        records_by_role[role] = records
    _STAGED_RECORDS[str(root.resolve())] = records_by_role
    empty_inventory_digest = _payload_digest([])
    binding_digest = "sha256:" + "a" * 64
    summary: dict[str, object] = {
        "assertedInventoryDigest": empty_inventory_digest,
        "contractDigest": binding_digest,
        "distributionId": "urn:test:atlas-distribution",
        "type": "AtlasConstructionSummary",
        "version": "3.1",
    }
    summary["canonicalPayloadDigest"] = _payload_digest(summary)
    summary_raw = _write_json(root / "atlas-construction-summary.json", summary)
    member = {
        "byteLength": len(summary_raw),
        "digest": sha256_digest(summary_raw),
        "mediaType": "application/json",
        "path": "atlas-construction-summary.json",
        "role": "constructionSummary",
    }
    manifest: dict[str, object] = {
        "binding": {
            "contractDigest": binding_digest,
            "ontologyDigest": "sha256:" + "b" * 64,
        },
        "counts": {}
        if derived_relation_count is None
        else {"derivedRelations": derived_relation_count},
        "createdAt": "2026-08-07T00:00:00+00:00",
        "distributionId": "urn:test:atlas-distribution",
        "format": "refspec-atlas-packed-nquads-3.1",
        "graphs": [
            {
                "id": "urn:ref:atlas:graph:v3:asserted",
                "inventoryDigest": empty_inventory_digest,
                "packCount": 0,
                "quadCount": 0,
                "role": "asserted",
            },
            {
                "id": "urn:ref:atlas:graph:v3:projection",
                "inventoryDigest": empty_inventory_digest,
                "packCount": 0,
                "quadCount": 0,
                "role": "projection",
            },
            {
                "id": "urn:ref:atlas:graph:v3:derived",
                "inventoryDigest": empty_inventory_digest,
                "packCount": 0,
                "quadCount": 0,
                "role": "derived",
            },
        ],
        "members": [member],
        "packs": [],
        "schemaVersion": "3.1",
        "type": "AtlasManifest",
    }
    manifest["canonicalPayloadDigest"] = _payload_digest(manifest)
    manifest_raw = _write_json(root / "atlas-manifest.json", manifest)
    return sha256_digest(manifest_raw)


def test_builds_and_verifies_typed_lossless_logical_view(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    output = tmp_path / "view"

    manifest = _seal_view(source, output, expected_manifest_digest=source_pin)

    assert set(manifest["counts"]) == {role.value for role in CompactRecordRole}
    assert set(manifest["counts"].values()) == {1}
    assert manifest["status"] == {
        "canonicalAtlas": False,
        "containsExactRdfTable": False,
        "derivedView": True,
        "expansion": "not_used",
        "logicalRecordsPreserved": True,
    }
    resources = pq.read_table(output / "tables/resources.parquet").to_pylist()
    assert resources[0]["id"] == "urn:test:resource"
    assert resources[0]["content_digest"] == bytes.fromhex("1" * 64)
    source_records = pq.read_table(output / "tables/source-records.parquet").to_pylist()
    assert source_records[0]["native_payload"] == b'{"publisher":"Example","values":[1,2]}'
    view_pin = sha256_digest((output / "view-manifest.json").read_bytes())
    assert verify_atlas_parquet_view(output, expected_manifest_digest=view_pin) == manifest


def test_registry_claim_bundle_round_trips_through_atlas_parquet(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "claim-source.ttl"
    raw.write_bytes(b"claim source\n")
    source_digest = sha256_digest(raw.read_bytes())
    release_id = "urn:test:registry-claim-release"
    recipe_id = "urn:test:registry-claim-recipe"
    claim = RegistryClaim(
        release_id=release_id,
        subject="https://example.test/concept",
        predicate="http://www.w3.org/2004/02/skos/core#prefLabel",
        object_kind="literal",
        lexical_value=" Exact label ",
        language="en",
        source_record_id="https://example.test/concept",
        source_locator="https://example.test/source",
        source_path="raw/source.ttl#claim=1",
        source_digest=source_digest,
        origin="observed",
        recipe_id=recipe_id,
    )
    bundle = build_registry_claim_release(
        tmp_path / "claim-release",
        release_id=release_id,
        release_key="claim-test",
        issued="2026-08-07",
        release_scope={"complete": True, "mode": "completeCapture"},
        language_scope={"included": ["en"], "mode": "englishOnly"},
        recipes=({"id": recipe_id},),
        claims=(claim,),
        raw_inputs=(
            RegistryRawInput(
                path=raw,
                logical_path="raw/source.ttl",
                source_locator="https://example.test/source",
            ),
        ),
    )
    input_ = AtlasRegistryClaimInput(
        path=bundle.root,
        expected_manifest_digest=bundle.manifest_digest,
    )
    payload = adapt_registry_claim_release(input_).records[0].native_payload
    source = tmp_path / "atlas"
    source.mkdir()
    atlas_pin = _fixture_distribution(
        source,
        source_native_payload=payload,
        source_digest=source_digest,
    )
    atlas_view = tmp_path / "atlas-parquet"
    manifest = _seal_view(
        source,
        atlas_view,
        expected_manifest_digest=atlas_pin,
    )
    view_pin = sha256_digest(
        (atlas_view / "view-manifest.json").read_bytes()
    )

    report = validate_atlas_parquet_registry_claims(
        input_,
        atlas_view,
        expected_atlas_view_manifest_digest=view_pin,
    )

    assert manifest["counts"]["SourceRecord"] == 1
    assert report.passed is True
    assert report.exact_count == 1


def test_warrant_columns_carry_every_axis_and_the_optional_referent(
    tmp_path: Path,
) -> None:
    """All five warrant fields are columns, so a bad warrant is visible here.

    The defect that shipped in 2026-08 was a combination of axis values
    matching no sanctioned branch. A view that carried only `evidence_role`
    could not express the combination, let alone refuse it -- which is also
    why `logicalRecordsPreserved` was a false claim until now.
    """

    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    output = tmp_path / "view"
    manifest = _seal_view(source, output, expected_manifest_digest=source_pin)

    schema = pq.read_schema(output / "tables/evidence-bindings.parquet")
    warrant_columns = (
        "attestor_kind",
        "assertion_origin",
        "epistemic_basis",
        "evidence_role",
        "evidentiary_function",
        "based_on_attestation",
    )
    assert set(warrant_columns) <= set(schema.names)
    for column in warrant_columns[:-1]:
        assert schema.field(column).nullable is False
    assert schema.field("based_on_attestation").nullable is True

    row = pq.read_table(output / "tables/evidence-bindings.parquet").to_pylist()[0]
    assert row["attestor_kind"] == "urn:test:attestor-kind"
    assert row["assertion_origin"] == "urn:test:origin"
    assert row["epistemic_basis"] == "urn:test:basis"
    assert row["evidence_role"] == "urn:test:role"
    assert row["evidentiary_function"] == "urn:test:function"
    assert row["based_on_attestation"] is None
    assert manifest["schemaVersion"] == VIEW_SCHEMA_VERSION == "3.2"


def test_logical_records_preserved_is_computed_from_the_record_contract() -> None:
    """The manifest claim is derived, so it cannot outlive its truth.

    Every field a compact record can carry must have a column. Drop one and
    the derivation names it, the status claim goes False, and the manifest
    publishes the gap instead of asserting the opposite.
    """

    assert unpreserved_record_fields() == {}
    assert logical_records_preserved() is True
    for role in CompactRecordRole:
        columns = set(TABLE_SCHEMAS[role].names)
        assert {column_name(field) for field in compact_record_fields(role)} == columns


def test_native_payload_column_is_the_literal_lexical_bytes(tmp_path: Path) -> None:
    """One encoder, and the column is exactly what the RDF literal holds.

    The duplicate canonicalizer this replaces dropped publisher nulls, so the
    Parquet payload could not round-trip a source record that had any -- and
    its sha256 could not match the `sourceDigest` the record publishes.
    """

    payload = {"b": None, "a": [1, {"z": None}], "unicode": "café"}
    source = tmp_path / "atlas"
    source.mkdir()
    expected = canonical_native_json_bytes(payload)
    source_pin = _fixture_distribution(
        source,
        source_native_payload=payload,
        source_digest=sha256_digest(expected),
    )
    output = tmp_path / "view"
    _seal_view(source, output, expected_manifest_digest=source_pin)

    row = pq.read_table(output / "tables/source-records.parquet").to_pylist()[0]
    assert row["native_payload"] == expected
    assert expected == b'{"a":[1,{"z":null}],"b":null,"unicode":"caf\xc3\xa9"}'
    assert hashlib.sha256(row["native_payload"]).digest() == row["source_digest"]



def test_rebuild_is_byte_stable(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    first = _seal_view(source, tmp_path / "first", expected_manifest_digest=source_pin)
    second = _seal_view(source, tmp_path / "second", expected_manifest_digest=source_pin)
    assert first == second
    assert [row["sha256"] for row in first["members"]] == [row["sha256"] for row in second["members"]]


def test_refuses_input_manifest_drift_and_output_tampering(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    with pytest.raises(AtlasParquetViewError, match="digest differs"):
        _seal_view(source, tmp_path / "wrong", expected_manifest_digest=_D1)

    output = tmp_path / "view"
    _seal_view(source, output, expected_manifest_digest=source_pin)
    view_pin = sha256_digest((output / "view-manifest.json").read_bytes())
    with (output / "tables/resources.parquet").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(AtlasParquetViewError, match="member bytes differ"):
        verify_atlas_parquet_view(output, expected_manifest_digest=view_pin)


def test_refuses_extra_input_or_view_member(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    (source / "extra.txt").write_text("extra")
    with pytest.raises(AtlasParquetViewError, match="membership is not closed"):
        _seal_view(source, tmp_path / "view", expected_manifest_digest=source_pin)

    source = tmp_path / "atlas-2"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    output = tmp_path / "view-2"
    _seal_view(source, output, expected_manifest_digest=source_pin)
    view_pin = sha256_digest((output / "view-manifest.json").read_bytes())
    (output / "extra.txt").write_text("extra")
    with pytest.raises(AtlasParquetViewError, match="membership is not closed"):
        verify_atlas_parquet_view(output, expected_manifest_digest=view_pin)


def test_compact_search_view_preserves_graph_and_omits_native_payload(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    full = tmp_path / "full"
    _seal_view(source, full, expected_manifest_digest=source_pin)
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())

    compact = tmp_path / "compact"
    manifest = build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)

    assert "SourceRecord.nativePayload" in manifest["status"]["omittedFields"]
    assert manifest["status"]["graphFactsPreserved"] is True
    source_schema = pq.read_schema(compact / "tables/source-records.parquet")
    assert "native_payload" not in source_schema.names
    # REF-025: the canonical Label.id is on the wire, not omitted and not reminted.
    assert manifest["schemaVersion"] == SEARCH_VIEW_SCHEMA_VERSION == "1.1"
    assert "Label.id" not in manifest["status"]["omittedFields"]
    label_row = pq.read_table(compact / "tables/labels.parquet").to_pylist()[0]
    assert label_row["id"] == "urn:ref:atlas-label:" + "7" * 64
    assert label_row["id"] == pq.read_table(full / "tables/labels.parquet").to_pylist()[0]["id"]
    statement_row = pq.read_table(compact / "tables/statements.parquet").to_pylist()[0]
    assert statement_row["id"] == "urn:ref:atlas-assertion:" + "3" * 64
    assert statement_row["subject"] == "urn:test:resource"
    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())
    assert verify_atlas_parquet_search_view(compact, expected_manifest_digest=compact_pin) == manifest


def test_search_view_refuses_a_label_member_without_canonical_label_id(tmp_path: Path) -> None:
    """REF-025: a Label member without `id` is not a search view of this version.

    The member is rewritten without the column and the manifest is resealed
    around it, so every byte-level check passes. What is left is the one fact
    the version exists to carry, and both verifying and opening must refuse it.
    """

    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    full = tmp_path / "full"
    _seal_view(source, full, expected_manifest_digest=source_pin)
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())
    compact = tmp_path / "compact"
    manifest = build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)

    labels = compact / "tables/labels.parquet"
    pq.write_table(pq.read_table(labels).drop_columns(["id"]), labels, compression="zstd")
    member = next(
        row for row in manifest["members"] if row["role"] == CompactRecordRole.LABEL.value
    )
    member["byteLength"] = labels.stat().st_size
    member["schemaDigest"] = arrow_schema_sha256(pq.ParquetFile(labels).schema_arrow)
    member["sha256"] = file_sha256(labels)
    resealed = {key: value for key, value in manifest.items() if key != "canonicalPayloadDigest"}
    resealed["canonicalPayloadDigest"] = canonical_payload_sha256(resealed)
    manifest_path = compact / "search-view-manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(resealed))
    compact_pin = sha256_digest(manifest_path.read_bytes())

    with pytest.raises(AtlasParquetSearchViewError, match="REF-025"):
        verify_atlas_parquet_search_view(compact, expected_manifest_digest=compact_pin)
    with pytest.raises(AtlasDuckDBViewError, match="REF-025"):
        AtlasDuckDBView.open(compact, trusted_manifest_digest=compact_pin)


def test_compact_search_view_refuses_member_tampering(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    full = tmp_path / "full"
    _seal_view(source, full, expected_manifest_digest=source_pin)
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())
    compact = tmp_path / "compact"
    build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)
    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())
    with (compact / "tables/statements.parquet").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(AtlasParquetSearchViewError, match="member bytes differ"):
        verify_atlas_parquet_search_view(compact, expected_manifest_digest=compact_pin)


def test_compact_search_view_carries_agency_projection_tables_through(tmp_path: Path) -> None:
    """The reviewer's finding, closed: REF-038's tables reach the served view.

    Full chain: a full view WITH agency-projection tables compacts into a
    compact search view that carries them as first-class, closure-checked
    members whose bytes and digests are copied verbatim -- never recomputed
    -- from the verified full view. Then the real digest-verified
    ``AtlasDuckDBView.open()`` path opens it, and the real explorer_cli HTTP
    handler serves ``/agencies`` and ``/api/agency-projection`` with
    populated results.
    """

    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    projection = _agency_projection_fixture()
    full = tmp_path / "full"
    _seal_view_with_agency_projection(
        source, full, expected_manifest_digest=source_pin, projection=projection
    )
    full_manifest = json.loads((full / "view-manifest.json").read_text())
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())
    assert full_manifest["agencyProjection"]["status"] == "emitted"

    compact = tmp_path / "compact"
    manifest = build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)

    projection_roles = {AGENCY_PROJECTION_ROLE, AGENCY_PROJECTION_UNRESOLVED_ROLE}
    compact_members_by_role = {member["role"]: member for member in manifest["members"]}
    full_members_by_role = {member["role"]: member for member in full_manifest["members"]}
    assert projection_roles <= set(compact_members_by_role)
    for role in projection_roles:
        compact_member = compact_members_by_role[role]
        full_member = full_members_by_role[role]
        # Carried through, not recomputed: identical digests, size, and bytes.
        assert compact_member["sha256"] == full_member["sha256"]
        assert compact_member["byteLength"] == full_member["byteLength"]
        assert compact_member["schemaDigest"] == full_member["schemaDigest"]
        assert compact_member["rowCount"] == full_member["rowCount"]
        assert (compact / compact_member["path"]).read_bytes() == (full / full_member["path"]).read_bytes()
    assert manifest["counts"][AGENCY_PROJECTION_ROLE] == 1
    assert manifest["counts"][AGENCY_PROJECTION_UNRESOLVED_ROLE] == 1

    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())
    # Byte-for-byte deterministic: verifying re-derives exactly what was built.
    assert verify_atlas_parquet_search_view(compact, expected_manifest_digest=compact_pin) == manifest

    view = AtlasDuckDBView.open(compact, trusted_manifest_digest=compact_pin)
    try:
        assert view.agency_projection_available() is True
        resolved_result = view.agency_projection("EPA")
        assert resolved_result["available"] is True
        assert [row["source_value"] for row in resolved_result["resolved"]] == ["EPA"]
        assert resolved_result["resolved"][0]["basis"] == "exactPublisherNameEquality"
        assert resolved_result["resolved"][0]["org_known"] is True
        unresolved_result = view.agency_projection("ARCTICGAS")
        assert [row["source_value"] for row in unresolved_result["unresolved"]] == ["ARCTICGAS"]
        assert unresolved_result["resolved"] == []

        server = ThreadingHTTPServer(("127.0.0.1", 0), explorer_cli._handler(view))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            with urlopen(f"{base_url}/agencies", timeout=5) as response:
                assert response.status == 200
                assert response.headers["Content-Type"].startswith("text/html")
                assert "<html" in response.read().decode()
            with urlopen(f"{base_url}/api/agency-projection?q=EPA", timeout=5) as response:
                assert response.status == 200
                payload = json.loads(response.read())
            assert payload["available"] is True
            assert [row["source_value"] for row in payload["resolved"]] == ["EPA"]
            assert payload["unresolved"] == []
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    finally:
        view.close()


def test_compact_search_view_without_agency_projection_degrades_gracefully(tmp_path: Path) -> None:
    """Older/projection-less full views still compact cleanly: no projection
    members, and the served view's agency-projection path degrades rather
    than erroring -- through the same real ``.open()`` and HTTP-handler path
    the populated case above uses.
    """

    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    full = tmp_path / "full"
    _seal_view(source, full, expected_manifest_digest=source_pin)
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())

    compact = tmp_path / "compact"
    manifest = build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)
    assert {AGENCY_PROJECTION_ROLE, AGENCY_PROJECTION_UNRESOLVED_ROLE}.isdisjoint(
        member["role"] for member in manifest["members"]
    )
    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())
    assert verify_atlas_parquet_search_view(compact, expected_manifest_digest=compact_pin) == manifest

    view = AtlasDuckDBView.open(compact, trusted_manifest_digest=compact_pin)
    try:
        assert view.agency_projection_available() is False
        assert view.agency_projection("EPA") == {"available": False, "resolved": [], "unresolved": []}

        server = ThreadingHTTPServer(("127.0.0.1", 0), explorer_cli._handler(view))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            with urlopen(f"{base_url}/api/agency-projection", timeout=5) as response:
                assert response.status == 200
                assert json.loads(response.read()) == {
                    "available": False,
                    "resolved": [],
                    "unresolved": [],
                }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    finally:
        view.close()


def test_verify_refuses_a_partial_agency_projection_member_pair(tmp_path: Path) -> None:
    """The two projection tables are all-or-none, same as REF-038 requires
    for the full view -- verified again independently on the compact side.
    """

    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    projection = _agency_projection_fixture()
    full = tmp_path / "full"
    _seal_view_with_agency_projection(
        source, full, expected_manifest_digest=source_pin, projection=projection
    )
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())
    compact = tmp_path / "compact"
    manifest = build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)

    unresolved_member = next(
        member for member in manifest["members"] if member["role"] == AGENCY_PROJECTION_UNRESOLVED_ROLE
    )
    (compact / unresolved_member["path"]).unlink()
    tampered = dict(manifest)
    tampered["members"] = [
        member for member in manifest["members"] if member["role"] != AGENCY_PROJECTION_UNRESOLVED_ROLE
    ]
    tampered["counts"] = {
        key: value for key, value in manifest["counts"].items() if key != AGENCY_PROJECTION_UNRESOLVED_ROLE
    }
    resealed = {key: value for key, value in tampered.items() if key != "canonicalPayloadDigest"}
    resealed["canonicalPayloadDigest"] = canonical_payload_sha256(resealed)
    manifest_path = compact / "search-view-manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(resealed))
    compact_pin = sha256_digest(manifest_path.read_bytes())

    with pytest.raises(AtlasParquetSearchViewError, match="carried through together"):
        verify_atlas_parquet_search_view(compact, expected_manifest_digest=compact_pin)


def test_verify_still_refuses_an_undeclared_agency_projection_file(tmp_path: Path) -> None:
    """The original defect, guarded against regressing: a projection table
    present on disk but not declared in the manifest must still be refused --
    only carried-through, closure-checked members are ever admitted.
    """

    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    full = tmp_path / "full"
    _seal_view(source, full, expected_manifest_digest=source_pin)
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())
    compact = tmp_path / "compact"
    build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)
    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())

    write_agency_projection_tables(compact, _agency_projection_fixture())

    with pytest.raises(AtlasParquetSearchViewError, match="membership is not closed"):
        verify_atlas_parquet_search_view(compact, expected_manifest_digest=compact_pin)


def _resealed_manifest(manifest: dict[str, object], path: Path) -> str:
    """Recompute the payload digest around a tampered manifest and re-pin it."""

    resealed = {key: value for key, value in manifest.items() if key != "canonicalPayloadDigest"}
    resealed["canonicalPayloadDigest"] = canonical_payload_sha256(resealed)
    path.write_bytes(canonical_json_bytes(resealed))
    return sha256_digest(path.read_bytes())


def test_derived_relation_table_seals_compacts_and_never_mingles_with_statements(
    tmp_path: Path,
) -> None:
    """REF-042's derived graph reaches both views as its own table.

    A full view over a distribution that declares derived content carries a
    ``derived-relations.parquet`` whose rows carry the rule and the asserted
    nodes each edge was derived from; compaction copies it verbatim; and the
    statements table still holds exactly the asserted rows -- the derived
    graph's non-authoritative, opt-in contract survives being served.
    """

    rows = _derived_relation_rows()
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source, derived_relation_count=len(rows))
    full = tmp_path / "full"
    manifest = _seal_view_with_derived_relations(
        source, full, expected_manifest_digest=source_pin, rows=rows
    )
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())

    derived_metadata = manifest["derivedRelations"]
    assert derived_metadata["status"] == "emitted"
    assert derived_metadata["decision"] == "REF-042"
    assert derived_metadata["coverage"] == {
        "rowCount": 2,
        "ruleCounts": {"urn:test:rule:test-broader": 2},
        "predicateCounts": {"http://www.w3.org/2004/02/skos/core#broader": 2},
        "generatedAt": "2026-08-16T00:00:00+00:00",
    }
    assert manifest["counts"][DERIVED_RELATION_ROLE] == 2
    assert verify_atlas_parquet_view(full, expected_manifest_digest=full_pin) == manifest

    table = pq.read_table(full / "tables/derived-relations.parquet")
    assert table.num_rows == 2
    first = table.to_pylist()[0]
    assert first["id"] == "urn:ref:atlas-derived:" + bytes(first["content_digest"]).hex()
    assert first["subject"] == "urn:test:resource"
    assert first["semantic_ring"] == "subject"
    assert first["derivation_rule"] == "urn:test:rule:test-broader"
    assert first["derived_from_assertions"] == sorted(
        ["urn:ref:atlas-source-record:" + "a" * 64, "urn:ref:atlas-source-record:" + "b" * 64]
    )
    # The asserted statements table is untouched by the derived rows.
    statements = pq.read_table(full / "tables/statements.parquet")
    assert statements.num_rows == 1
    assert all(
        row["statement_type"] == "NativeRelationAssertion" for row in statements.to_pylist()
    )

    compact = tmp_path / "compact"
    compact_manifest = build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)
    compact_member = next(
        member for member in compact_manifest["members"] if member["role"] == DERIVED_RELATION_ROLE
    )
    full_member = next(
        member for member in manifest["members"] if member["role"] == DERIVED_RELATION_ROLE
    )
    assert compact_member["sha256"] == full_member["sha256"]
    assert (compact / compact_member["path"]).read_bytes() == (
        full / "tables/derived-relations.parquet"
    ).read_bytes()
    assert compact_manifest["counts"][DERIVED_RELATION_ROLE] == 2
    assert compact_manifest["counts"][CompactRecordRole.STATEMENT.value] == 1
    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())
    assert verify_atlas_parquet_search_view(compact, expected_manifest_digest=compact_pin) == compact_manifest


def test_derived_relation_table_is_optional_and_omitted_cleanly(tmp_path: Path) -> None:
    """A distribution with an empty derived graph yields no table, and the
    view and its compact descendant still verify -- every pre-2026-08-18
    build's shape.
    """

    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    full = tmp_path / "full"
    manifest = _seal_view(source, full, expected_manifest_digest=source_pin)

    assert manifest["derivedRelations"] == {"status": "notEmitted"}
    assert DERIVED_RELATION_ROLE not in manifest["counts"]
    assert not (full / "tables/derived-relations.parquet").exists()
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())
    assert verify_atlas_parquet_view(full, expected_manifest_digest=full_pin) == manifest

    compact = tmp_path / "compact"
    compact_manifest = build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)
    assert DERIVED_RELATION_ROLE not in compact_manifest["counts"]
    assert not (compact / "tables/derived-relations.parquet").exists()
    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())
    assert verify_atlas_parquet_search_view(compact, expected_manifest_digest=compact_pin) == compact_manifest


def test_seal_refuses_a_view_that_drops_derived_content_the_distribution_declares(
    tmp_path: Path,
) -> None:
    """The 2026-08-18 failure mode, made impossible: 42,519 derived relations
    sealed in the packs while the view silently shipped none. A view of a
    distribution that declares derived content must carry it.
    """

    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source, derived_relation_count=2)
    staged = tmp_path / ".staged-tables"
    _stage_tables(source, staged)
    with pytest.raises(AtlasParquetViewError, match="declares derived relations"):
        seal_atlas_parquet_view(
            source,
            staged,
            tmp_path / "view",
            expected_manifest_digest=source_pin,
            agency_projection={
                "status": "notEmitted",
                "missingReleaseKeys": ["regulations-gov-agencies-roster-2026-08-16"],
            },
            derived_relations={"status": "notEmitted"},
        )


def test_seal_ties_the_derived_table_to_the_distribution_declared_count(
    tmp_path: Path,
) -> None:
    """The emitted block is reconciled against the distribution's own
    authenticated count, not just against the table that happens to be staged.
    """

    rows = _derived_relation_rows()
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source, derived_relation_count=3)
    staged = tmp_path / ".staged-tables"
    _stage_tables(source, staged)
    write_derived_relation_table(staged, rows)
    with pytest.raises(AtlasParquetViewError, match="distribution's declared count"):
        seal_atlas_parquet_view(
            source,
            staged,
            tmp_path / "view",
            expected_manifest_digest=source_pin,
            agency_projection={
                "status": "notEmitted",
                "missingReleaseKeys": ["regulations-gov-agencies-roster-2026-08-16"],
            },
            derived_relations=derived_relation_manifest_metadata(rows),
        )


def test_verify_refuses_derived_coverage_that_differs_from_the_table_rows(
    tmp_path: Path,
) -> None:
    """Coverage is recomputed from the sealed bytes, so a manifest that
    disagrees with its own table is refused even under a fresh pin.
    """

    rows = _derived_relation_rows()
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source, derived_relation_count=len(rows))
    full = tmp_path / "full"
    manifest = _seal_view_with_derived_relations(
        source, full, expected_manifest_digest=source_pin, rows=rows
    )

    tampered = dict(manifest)
    tampered["derivedRelations"] = {
        **manifest["derivedRelations"],
        "coverage": {
            **manifest["derivedRelations"]["coverage"],
            "ruleCounts": {"urn:test:rule:someone-elses-rule": 2},
        },
    }
    view_pin = _resealed_manifest(tampered, full / "view-manifest.json")

    with pytest.raises(AtlasParquetViewError, match="coverage differs from table rows"):
        verify_atlas_parquet_view(full, expected_manifest_digest=view_pin)


def test_verify_refuses_a_derived_row_whose_identity_is_not_its_content_digest(
    tmp_path: Path,
) -> None:
    """A re-identified row breaks the one identity rule the table has: the
    identifier is the derived-relation prefix plus the row's own content
    digest -- the same fact `_suffix` enforces for compact statements.
    """

    rows = _derived_relation_rows()
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source, derived_relation_count=len(rows))
    full = tmp_path / "full"
    manifest = _seal_view_with_derived_relations(
        source, full, expected_manifest_digest=source_pin, rows=rows
    )

    derived_path = full / "tables/derived-relations.parquet"
    table = pq.read_table(derived_path)
    data = table.to_pylist()
    data[0] = {**data[0], "id": "urn:ref:atlas-derived:" + "0" * 64}
    pq.write_table(
        pa.Table.from_pylist(data, schema=table.schema),
        derived_path,
        compression="zstd",
    )
    member = next(
        member for member in manifest["members"] if member["role"] == DERIVED_RELATION_ROLE
    )
    member["byteLength"] = derived_path.stat().st_size
    member["sha256"] = file_sha256(derived_path)
    view_pin = _resealed_manifest(dict(manifest), full / "view-manifest.json")

    with pytest.raises(AtlasParquetViewError, match="differs from its contentDigest"):
        verify_atlas_parquet_view(full, expected_manifest_digest=view_pin)


def test_compact_view_refuses_an_undeclared_derived_relation_file(tmp_path: Path) -> None:
    """Closure on the compact side admits exactly the declared members: an
    undeclared derived table on disk is refused, exactly as an undeclared
    projection table is.
    """

    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source)
    full = tmp_path / "full"
    _seal_view(source, full, expected_manifest_digest=source_pin)
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())
    compact = tmp_path / "compact"
    build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)
    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())

    write_derived_relation_table(compact, _derived_relation_rows())

    with pytest.raises(AtlasParquetSearchViewError, match="membership is not closed"):
        verify_atlas_parquet_search_view(compact, expected_manifest_digest=compact_pin)


def test_derived_relation_row_projection_refuses_forbidden_rows() -> None:
    """The writer is the first gate: identity, ring, and evidence shape are
    refused here, before any table or manifest exists to carry them.
    """

    rows = _derived_relation_rows()
    with pytest.raises(AtlasParquetTableError, match="differs from its contentDigest"):
        derived_relation_parquet_row(
            dataclasses.replace(rows[0], node_iri="urn:ref:atlas-derived:" + "0" * 64)
        )
    with pytest.raises(AtlasParquetTableError, match="not an Atlas ring IRI"):
        derived_relation_parquet_row(dataclasses.replace(rows[0], ring="urn:test:not-a-ring"))
    with pytest.raises(AtlasParquetTableError, match="not a known ring"):
        derived_relation_parquet_row(
            dataclasses.replace(rows[0], ring="https://refspec.org/ns/atlas/v3#chaos")
        )
    with pytest.raises(AtlasParquetTableError, match="cites no asserted evidence rows"):
        derived_relation_parquet_row(dataclasses.replace(rows[0], evidence=()))


def test_explorer_reads_compact_parquet_view_without_rdf(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source, include_alias=True)
    full = tmp_path / "full"
    _seal_view(source, full, expected_manifest_digest=source_pin)
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())
    compact = tmp_path / "compact"
    build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)
    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())

    opened = open_atlas_explorer(compact, trusted_manifest_digest=compact_pin)
    assert isinstance(opened, AtlasExplorerData)
    assert isinstance(opened, AtlasDuckDBView)
    assert opened.database_path.parent != compact
    assert opened.table_name(CompactRecordRole.RESOURCE) == "atlas_resources"
    assert opened.query_rows("SELECT count(*) AS count FROM atlas_resources") == [{"count": 1}]
    assert opened.query_arrow("SELECT id FROM atlas_resources").to_pylist() == [
        {"id": "urn:test:resource"}
    ]
    bundle = build_atlas_explorer_static_shards(
        opened,
        tmp_path / "shards",
        url_prefix="shards",
    )
    model = build_atlas_explorer_model(opened, full_corpus=bundle)
    rendered = render_atlas_v3_explorer(model)

    assert model["distribution"]["manifestDigest"] == compact_pin
    assert model["summary"]["availableResources"] == 1
    assert model["resources"][0]["displayLabel"] == "Test resource"
    assert model["assertedRelations"][0]["predicateLabel"] == "broader"
    assert bundle["counts"]["resources"] == 1
    assert "Test resource" in rendered
    search_result = search_atlas_parquet(opened, "test")[0]
    assert search_result["id"] == "urn:test:resource"
    assert isinstance(search_result["score"], float)
    assert search_atlas_parquet(opened, "fixture alias")[0]["id"] == "urn:test:resource"
    assert search_atlas_parquet(opened, "T-1")[0]["id"] == "urn:test:resource"
    assert search_atlas_parquet(
        opened,
        "test",
        releases=("urn:test:atlas-release",),
    )[0]["id"] == "urn:test:resource"
    assert search_atlas_parquet(opened, "test", releases=("urn:test:other-release",)) == []
    assert search_atlas_parquet(opened, "test", offset=1) == []
    assert search_atlas_parquet(opened, "", offset=1) == []
    with pytest.raises(AtlasDuckDBViewError, match="offset"):
        search_atlas_parquet(opened, "test", offset=-1)
    assert atlas_explorer_facets(opened)["rings"] == [{"count": 1, "id": "subject"}]
    assert atlas_explorer_facets(opened)["graphs"] == [
        {
            "authority": "Verified Atlas relation records",
            "description": "All relations retained by the compact search view.",
            "relationCount": 1,
            "role": "asserted",
        }
    ]
    detail = atlas_parquet_resource(opened, "urn:test:resource")
    assert detail["relations"][0]["evidence_count"] == 1
    assert detail["relations"][0]["evidence"][0]["decision"] == "urn:test:approved"
    assert detail["relations"][0]["evidence"][0]["sourceLocator"] == "https://example.test/source"
    assert detail["relations"][0]["subject_label"] == "Test resource"
    assert detail["relations"][0]["object_label"] == "parent"
    assert atlas_explorer_facets(opened)["start"] == "urn:test:resource"
    database_path = opened.database_path
    opened.close()
    assert not database_path.exists()


def test_overview_maps_release_pairs_and_internal_relations(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source, include_mapping=True)
    full = tmp_path / "full"
    _seal_view(source, full, expected_manifest_digest=source_pin)
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())
    compact = tmp_path / "compact"
    build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)
    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())

    with AtlasDuckDBView.open(compact, trusted_manifest_digest=compact_pin) as view:
        overview = view.overview()

    assert overview["nodes"] == [
        {
            "id": "urn:test:atlas-release",
            "identifier": "test-release",
            "ring": "subject",
            "resources": 2,
            "internalRelations": 1,
            "satellite": False,
            "partner": None,
        },
        {
            "id": "urn:test:atlas-release-b",
            "identifier": "test-release-b",
            "ring": "subject",
            "resources": 0,
            "internalRelations": 0,
            "satellite": False,
            "partner": None,
        },
    ]
    # The two opposite-direction mappings collapse onto one undirected pair.
    assert overview["edges"] == [
        {
            "source": "urn:test:atlas-release",
            "target": "urn:test:atlas-release-b",
            "statement_type": "MappingAssertion",
            "count": 2,
        }
    ]


def test_release_graph_returns_the_full_vocabulary(tmp_path: Path) -> None:
    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source, include_mapping=True)
    full = tmp_path / "full"
    _seal_view(source, full, expected_manifest_digest=source_pin)
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())
    compact = tmp_path / "compact"
    build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)
    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())

    with AtlasDuckDBView.open(compact, trusted_manifest_digest=compact_pin) as view:
        graph = view.release_graph("urn:test:atlas-release")
        empty = view.release_graph("urn:test:atlas-release-b")
        with pytest.raises(AtlasDuckDBViewError, match="release is not present"):
            view.release_graph("urn:test:missing-release")

    assert graph["release"] == {
        "id": "urn:test:atlas-release",
        "identifier": "test-release",
        "ring": "subject",
    }
    assert graph["nodes"] == [
        ["urn:test:parent", "parent"],
        ["urn:test:resource", "Test resource"],
    ]
    # The one internal relation arrives as index tuples; the cross-release
    # mappings belong to the overview, not to either vocabulary's own graph.
    assert graph["edges"] == [[1, 0, 0, 0]]
    assert graph["predicates"] == ["http://www.w3.org/2004/02/skos/core#broader"]
    assert graph["types"] == ["NativeRelationAssertion"]
    assert graph["counts"] == {"droppedRelations": 0, "relations": 1, "resources": 2}
    assert empty["nodes"] == []
    assert empty["edges"] == []


def test_search_view_matches_whole_tokens_only(tmp_path: Path) -> None:
    """Pin the retrieval the view actually offers: whole tokens, nothing else.

    The Atlas 1.0 explorer ranked in process and advertised branches for
    one-edit typos and useful prefixes; the reviewed search corpus at
    ``research/vocabulary-atlas-v1-explorer-search-corpus-2026-08-05.json``
    names a category per branch. This view ranks with a DuckDB full-text index
    that has neither, so those expectations were not carried onto it. That
    reasoning is only sound while the substrate stays this one, so assert it:
    if prefix or fuzzy retrieval ever lands here, this fails and the corpus
    becomes portable again.
    """

    source = tmp_path / "atlas"
    source.mkdir()
    source_pin = _fixture_distribution(source, include_alias=True)
    full = tmp_path / "full"
    _seal_view(source, full, expected_manifest_digest=source_pin)
    full_pin = sha256_digest((full / "view-manifest.json").read_bytes())
    compact = tmp_path / "compact"
    build_atlas_parquet_search_view(full, compact, expected_manifest_digest=full_pin)
    compact_pin = sha256_digest((compact / "search-view-manifest.json").read_bytes())

    with AtlasDuckDBView.open(compact, trusted_manifest_digest=compact_pin) as view:
        # Whole tokens retrieve, through punctuation and case normalization.
        assert view.search("resource")[0]["id"] == "urn:test:resource"
        assert view.search("Test/resource   (alias)")[0]["id"] == "urn:test:resource"
        # A proper prefix of a retained token retrieves nothing.
        assert view.search("resourc") == []
        assert view.search("ali") == []
        # Neither does a single edit away from one.
        assert view.search("resourse") == []
        assert view.search("aliaz") == []


def test_parquet_explorer_renders_graph_as_primary_workspace() -> None:
    rendered = render_atlas_parquet_explorer()

    assert rendered == render_atlas_explorer_frontend()
    assert 'id="graph-workspace"' in rendered
    assert "class GraphView" in rendered
    assert 'this.canvas=this.element.querySelector("canvas")' in rendered
    assert "this.nodes=new Map()" in rendered
    assert "async function addGraph(id)" in rendered
    assert "function removeGraph(id)" in rendered
    assert "layout(){" in rendered
    assert "drawnEdges(){" in rendered
    assert "lineTo(to.x,to.y)" in rendered
    assert "Browse every resource or narrow the list" in rendered
    assert 'id="more-results"' not in rendered
    # The Atlas overview map opens first and stays open beside neighborhoods.
    assert "class OverviewView" in rendered
    assert (
        'async function loadOverview(){const data=await get('
        '`/api/overview?status=${statusParam()}&relations=${relationsParam()}`)'
    ) in rendered
    assert "workspace.prepend(this.element)" in rendered
    # Deprecated-status resources hide by default across search, graphs, and
    # the overview; one toggle flips all three to include them.
    assert 'id="show-deprecated"' in rendered
    assert 'function statusParam(){return showDeprecated.checked?"all":"active"}' in rendered
    assert "status:statusParam()" in rendered
    assert "reopenGraphsWithCurrentFilters" in rendered
    # Non-authoritative derived relations (REF-042) hide by default too, with
    # their own opt-in toggle -- hidden entirely when a view has none.
    assert 'id="show-derived-wrap" hidden' in rendered
    assert 'function relationsParam(){return showDerived.checked?"all":"asserted"}' in rendered
    assert 'DerivedRelation:"#c596e5"' in rendered
    assert "const count=graphs.size+(overview?1:0)" in rendered
    assert "overview?.refresh(fit)" in rendered
    # A selected vocabulary links to its full map, and the map links back into
    # a neighborhood through the ?open= deep link.
    assert 'href="/release?id=${encodeURIComponent(node.id)}" target="_blank"' in rendered
    assert "const params=new URLSearchParams(location.search)" in rendered
    assert "if(openTarget)await addGraph(openTarget)" in rendered
    # A ?q= deep link (e.g. from the agency-projection page) prefills search.
    assert "qTarget=params.get(\"q\")" in rendered
    # The explorer accepts concepts broadcast from vocabulary-map tabs by
    # adding a pane, and selecting an overview vocabulary must not re-filter
    # the neighborhoods that are already open.
    assert 'new BroadcastChannel("refspec-atlas-open")' in rendered
    assert 'openChannel.postMessage({type:"opened",id:data.id})' in rendered
    assert (
        "select(node){this.selected=node.id;releaseFilter.value=node.id;"
        "runSearch().catch(showSearchError);showOverviewNodeInspector(node)"
    ) in rendered
    script = re.search(r"<script>\n(.*?)</script>", rendered, re.DOTALL)
    assert script is not None
    subprocess.run(
        ["node", "--check", "-"],
        input=script.group(1),
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Show more" not in rendered
    assert 'id="search-status"' in rendered
    assert 'searchResults.addEventListener("scroll"' in rendered
    assert "app.searchHasMore" in rendered
    assert "offset:String(app.searchOffset)" in rendered
    assert 'input type="checkbox" data-resource=' in rendered
    assert 'input.checked?addGraph(input.dataset.resource):removeGraph(input.dataset.resource)' in rendered
    assert "await addGraph(app.startId)" not in rendered
    assert "[hidden]{display:none!important}" in rendered
    assert 'id="graph-catalog"' in rendered
    assert 'data-graph-role="${esc(row.role)}"' in rendered
    assert "Empty in this release" in rendered
    assert "Fit all views" in rendered
    assert 'id="clear-graphs"' in rendered
    assert 'aria-label="Remove ${esc(labelOf(this.root))} view"' in rendered
    assert "RefSpec vocabulary Atlas" in rendered
    assert "Explore the Atlas" in rendered
    assert "Concept inspector" in rendered
    assert "equivalent assertions" in rendered
    assert "Vocabulary relations" in rendered
    assert "Cross-vocabulary mappings" in rendered
    assert "Source assignments" in rendered
    assert "function relationMeaning(edge)" in rendered
    assert "function relationWhy(edge)" in rendered
    assert "controls-resizer" in rendered
    assert 'placeholder="Label, alias, notation, or IRI"' in rendered
    assert "Relation ID" in rendered
    assert "Property ID" in rendered
    assert "Federal Register topics" in rendered
    assert "compact Parquet" not in rendered
    assert ">NativeRelationAssertion<" not in rendered
    assert "<table" not in rendered


def test_agency_projection_page_looks_up_resolved_and_unresolved_source_values() -> None:
    from refspec.atlas.explorer_frontend import render_atlas_agency_projection_frontend

    rendered = render_atlas_agency_projection_frontend()

    assert "RefSpec Atlas agency projection" in rendered
    assert 'href="/"' in rendered
    assert 'placeholder="Docket prefix or agency name, e.g. EPA"' in rendered
    assert "/api/agency-projection?q=" in rendered
    # Graceful degradation: an older view without the tables never errors.
    assert "This view has no agency projection." in rendered
    assert "data.available" in rendered
    # Row click opens the resolved org through the same cross-tab inspector
    # channel the release map already uses, falling back to a search link.
    assert 'new BroadcastChannel("refspec-atlas-open")' in rendered
    assert 'channel.postMessage({type:"open",id})' in rendered
    assert 'row.dataset.orgKnown==="1"?openResource(row.dataset.org):openSearch(row.dataset.prefLabel)' in rendered
    assert "window.open(`/?q=${encodeURIComponent(term)}`" in rendered
    script = re.search(r"<script>\n(.*?)</script>", rendered, re.DOTALL)
    assert script is not None
    subprocess.run(
        ["node", "--check", "-"],
        input=script.group(1),
        check=True,
        capture_output=True,
        text=True,
    )


def test_release_map_page_draws_every_concept_and_links_back() -> None:
    from refspec.atlas.explorer import render_atlas_release_map
    from refspec.atlas.explorer_frontend import render_atlas_release_frontend

    rendered = render_atlas_release_map()

    assert rendered == render_atlas_release_frontend()
    assert "Every concept in this vocabulary" in rendered
    assert "/api/release-graph?id=" in rendered
    # All nodes stay drawable at scale: culling grid, dot fallback, and the
    # zoom-gated edge pass instead of a truncated node list.
    assert "function visibleNodes()" in rendered
    assert "visible.length>DOT_LIMIT" in rendered
    assert "zoom in to see relations" in rendered
    assert "state.adjacency" in rendered
    # Selecting a concept keeps this map open: the click selects in place and
    # shows the same full inspector the main explorer has — definition,
    # aliases, grouped relations, and per-relation meaning with evidence.
    assert 'id="inspector"' in rendered
    assert "if(state.drag&&!state.drag.moved)selectNode(hitNode(x,y))" in rendered
    assert "/api/resource?id=" in rendered
    assert "function connectionGroups(resource)" in rendered
    assert "function showEdgeDetail(index,group)" in rendered
    assert "equivalent assertions" in rendered
    assert "function relationMeaning(edge)" in rendered
    assert "Open source record" in rendered
    assert "Also known as" in rendered
    # The explicit action sends the concept to an already-open explorer tab,
    # opening a new tab only when no explorer answers.
    assert "window.open" not in rendered.split("function openSelected()")[0].split("<script>")[-1]
    assert 'new BroadcastChannel("refspec-atlas-open")' in rendered
    assert 'channel.postMessage({type:"open",id})' in rendered
    assert 'window.open(url,"_blank","noopener")' in rendered
    script = re.search(r"<script>\n(.*?)</script>", rendered, re.DOTALL)
    assert script is not None
    subprocess.run(
        ["node", "--check", "-"],
        input=script.group(1),
        check=True,
        capture_output=True,
        text=True,
    )
