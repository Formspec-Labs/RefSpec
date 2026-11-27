"""Projecting REF-072 atlas:OrganizationChangeEvent into lifecycle-events.parquet and v3 AtlasVocabularyPack."""

from __future__ import annotations

import dataclasses
import hashlib
import os
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, XSD

from refspec.atlas.compact_pack import CompactRecordRole
from refspec.atlas.parquet_artifact import file_sha256
from refspec.atlas.parquet_tables import (
    TABLE_DIRECTORY,
    TABLE_NAMES,
    TABLE_SCHEMAS,
    AtlasParquetTableWriter,
)
from refspec.atlas.parquet_view import (
    MANIFEST_FILE as VIEW_MANIFEST_FILE,
)
from refspec.atlas.parquet_view import (
    seal_atlas_parquet_view,
    verify_atlas_parquet_view,
)
from refspec.atlas.v3_source_data import (
    RegistryChangeEvent,
    RegistryInputPin,
    RegistryMapping,
    RegistryMappingEvidence,
    RegistryMappingRelease,
    mapping_triple_digest,
)
from refspec.atlas.vocabulary_pack import AtlasVocabularyPack
from refspec.atlas.vocabulary_pack_build import build_vocabulary_pack
from tools import generate_atlas_v3_full as generator

ROOT = Path(__file__).resolve().parents[1]
ATLAS = generator.ATLAS
ATLAS_VALIDATE = generator.ATLAS_VALIDATE
OWNER_REVIEWER = "urn:ref:reviewer:refspec-owner"
FR_ENTITY_SCHEME_IRI = "urn:ref:atlas-resource-scheme:federal-register-native-controls:agencies"
ECFR_ENTITY_SCHEME_IRI = "urn:ref:atlas-resource-scheme:ecfr-agencies"
USDA_FR_IRI = "urn:ref:federal-register-agency:12"
USDA_ECFR_IRI = "urn:ref:ecfr-agency:agriculture-department"
FNS_IRI = "urn:ref:federal-register-agency:200"
FNA_IRI = "urn:ref:federal-register-agency:625"
INS_IRI = "urn:ref:federal-register-agency:232"
CBP_IRI = "urn:ref:federal-register-agency:499"
ICE_IRI = "urn:ref:federal-register-agency:501"
USCIS_IRI = "urn:ref:federal-register-agency:503"
TEST_CREATED_AT = "2026-11-27T00:00:00+00:00"


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _synthetic_agency_change_event_case(
    tmp_path: Path,
) -> tuple[tuple[generator.LoadedRelease, ...], tuple[RegistryMappingRelease, ...]]:
    """Build two synthetic entity-ring roster releases and one mapping release carrying 1 bridge + 2 change events."""

    fr_file = tmp_path / "fr-agencies-roster.json"
    fr_file.write_bytes(b'{"agencies":7}\n')
    fr_digest = _sha256_bytes(fr_file.read_bytes())
    fr_source_release = "urn:test:source-release:fr-agencies:2026-08-15"
    fr_atlas_release = "urn:test:atlas-release:fr-agencies:2026-08-15"

    def _fr_org(iri: str, name: str, fr_id: int) -> generator.SourceResource:
        payload = {"id": fr_id, "name": name}
        encoded = ATLAS_VALIDATE.canonical_native_json_bytes(payload)
        return generator.SourceResource(
            iri=iri,
            source_locator=f"https://www.federalregister.gov/agencies/{fr_id}",
            source_digest=_sha256_bytes(encoded),
            native_payload=payload,
            labels=(generator.SourceLabel(role="preferred", value=name, language="en", source_path="name"),),
        )

    fr_resources = (
        _fr_org(USDA_FR_IRI, "Agriculture Department", 12),
        _fr_org(FNS_IRI, "Food and Nutrition Service", 200),
        _fr_org(FNA_IRI, "Food and Nutrition Administration", 625),
        _fr_org(INS_IRI, "Immigration and Naturalization Service", 232),
        _fr_org(CBP_IRI, "U.S. Customs and Border Protection", 499),
        _fr_org(ICE_IRI, "U.S. Immigration and Customs Enforcement", 501),
        _fr_org(USCIS_IRI, "U.S. Citizenship and Immigration Services", 503),
    )
    fr_pin = RegistryInputPin(
        path=fr_file,
        logical_path="test/fr-agencies-roster.json",
        sha256=fr_digest,
        byte_length=fr_file.stat().st_size,
        source_iri="https://www.federalregister.gov/api/v1/agencies.json",
        role="publisherRoster",
    )
    fr_release = generator.LoadedRelease(
        spec=generator.SourceSpec(
            key="federal-register-agencies-roster-2026-08-15",
            kind="registryRelease",
            path=fr_file,
            logical_path="test/fr-agencies-roster.json",
            expected_digest=fr_digest,
            expected_resources=len(fr_resources),
            expected_relations=0,
            profile="codeScheme",
            ring="entity",
            emit_source_assignments=False,
            resource_id="federal-register-native-controls",
            source_module="refspec.atlas.v3_registry_rosters",
            scope="publisherRelease",
            input_pins=(fr_pin,),
        ),
        issued="2026-08-15",
        scheme_iri=FR_ENTITY_SCHEME_IRI,
        source_release_iri=fr_source_release,
        atlas_release_iri=fr_atlas_release,
        source_release_digest=fr_digest,
        resources=fr_resources,
        relations=(),
    )

    ecfr_file = tmp_path / "ecfr-agencies-roster.json"
    ecfr_file.write_bytes(b'{"agencies":1}\n')
    ecfr_digest = _sha256_bytes(ecfr_file.read_bytes())
    ecfr_source_release = "urn:test:source-release:ecfr-agencies:2026-08-15"
    ecfr_atlas_release = "urn:test:atlas-release:ecfr-agencies:2026-08-15"
    ecfr_payload = {"name": "Agriculture Department", "slug": "agriculture-department"}
    ecfr_resources = (
        generator.SourceResource(
            iri=USDA_ECFR_IRI,
            source_locator="https://www.ecfr.gov/api/admin/v1/agencies.json#agriculture-department",
            source_digest=_sha256_bytes(ATLAS_VALIDATE.canonical_native_json_bytes(ecfr_payload)),
            native_payload=ecfr_payload,
            labels=(
                generator.SourceLabel(
                    role="preferred",
                    value="Agriculture Department",
                    language="en",
                    source_path="name",
                ),
            ),
        ),
    )
    ecfr_pin = RegistryInputPin(
        path=ecfr_file,
        logical_path="test/ecfr-agencies-roster.json",
        sha256=ecfr_digest,
        byte_length=ecfr_file.stat().st_size,
        source_iri="https://www.ecfr.gov/api/admin/v1/agencies.json",
        role="publisherRoster",
    )
    ecfr_release = generator.LoadedRelease(
        spec=generator.SourceSpec(
            key="ecfr-agencies-roster-2026-08-15",
            kind="registryRelease",
            path=ecfr_file,
            logical_path="test/ecfr-agencies-roster.json",
            expected_digest=ecfr_digest,
            expected_resources=len(ecfr_resources),
            expected_relations=0,
            profile="codeScheme",
            ring="entity",
            emit_source_assignments=False,
            resource_id="ecfr-agencies",
            source_module="refspec.atlas.v3_registry_rosters",
            scope="publisherRelease",
            input_pins=(ecfr_pin,),
        ),
        issued="2026-08-15",
        scheme_iri=ECFR_ENTITY_SCHEME_IRI,
        source_release_iri=ecfr_source_release,
        atlas_release_iri=ecfr_atlas_release,
        source_release_digest=ecfr_digest,
        resources=ecfr_resources,
        relations=(),
    )

    decisions_file = tmp_path / "agency-change-decisions.json"
    decisions_file.write_bytes(b'{"events":2}\n')
    decisions_digest = _sha256_bytes(decisions_file.read_bytes())
    decisions_pin = RegistryInputPin(
        path=decisions_file,
        logical_path="test/agency-change-decisions.json",
        sha256=decisions_digest,
        byte_length=decisions_file.stat().st_size,
        source_iri="https://www.federalregister.gov/documents/2026/06/24/2026-12700/fns-to-fna",
        role="ownerDecisions",
    )

    bridge = RegistryMapping(
        subject=USDA_FR_IRI,
        predicate=str(ATLAS.sameEntityAs),
        object=USDA_ECFR_IRI,
        subject_atlas_release_iri=fr_atlas_release,
        object_atlas_release_iri=ecfr_atlas_release,
        asserted_at="2026-09-26T00:00:00+00:00",
        evidence=(
            RegistryMappingEvidence(
                source_locator=decisions_pin.source_iri,
                source_digest=decisions_digest,
                native_payload={
                    "mappingTripleDigest": mapping_triple_digest(
                        subject_iri=USDA_FR_IRI,
                        predicate_iri=str(ATLAS.sameEntityAs),
                        object_iri=USDA_ECFR_IRI,
                    ),
                    "objectIri": USDA_ECFR_IRI,
                    "predicateIri": str(ATLAS.sameEntityAs),
                    "subjectIri": USDA_FR_IRI,
                },
                review_warrant="humanReview",
                reviewer_iri=OWNER_REVIEWER,
                attested_at="2026-09-26T00:00:00+00:00",
            ),
        ),
    )

    fns_event = RegistryChangeEvent(
        originals=(FNS_IRI,),
        results=(FNA_IRI,),
        release_iris={FNS_IRI: fr_atlas_release, FNA_IRI: fr_atlas_release},
        effective_date="2026-06-24",
        asserted_at="2026-10-03T00:00:00+00:00",
        evidence=(
            RegistryMappingEvidence(
                source_locator="https://www.federalregister.gov/documents/2026/06/24/2026-12700/fns-to-fna",
                source_digest=decisions_digest,
                native_payload={
                    "citation": "91 FR 37779 (2026-06-24)",
                    "eventId": "event:fr200",
                    "kind": "frDocument",
                },
                review_warrant="humanReview",
                reviewer_iri=OWNER_REVIEWER,
                attested_at="2026-10-03T00:00:00+00:00",
            ),
        ),
    )
    ins_event = RegistryChangeEvent(
        originals=(INS_IRI,),
        results=(CBP_IRI, ICE_IRI, USCIS_IRI),
        release_iris={
            INS_IRI: fr_atlas_release,
            CBP_IRI: fr_atlas_release,
            ICE_IRI: fr_atlas_release,
            USCIS_IRI: fr_atlas_release,
        },
        effective_date="2003-03-01",
        asserted_at="2026-09-26T00:00:00+00:00",
        evidence=(
            RegistryMappingEvidence(
                source_locator="https://www.congress.gov/107/plaws/publ296/PLAW-107publ296.pdf",
                source_digest=decisions_digest,
                native_payload={
                    "citation": "Homeland Security Act of 2002, Pub. L. 107-296",
                    "eventId": "event:fr232",
                    "kind": "statute",
                },
                review_warrant="humanReview",
                reviewer_iri=OWNER_REVIEWER,
                attested_at="2026-09-26T00:00:00+00:00",
            ),
            RegistryMappingEvidence(
                source_locator="https://www.federalregister.gov/documents/2003/03/01/03-4820/ins-transfer",
                source_digest=decisions_digest,
                native_payload={
                    "citation": "68 FR 9824 (2003-02-28)",
                    "eventId": "event:fr232",
                    "kind": "frDocument",
                },
                review_warrant="humanReview",
                reviewer_iri=OWNER_REVIEWER,
                attested_at="2026-09-26T00:00:00+00:00",
            ),
        ),
    )
    mapping_release = RegistryMappingRelease(
        key="agency-registry-2026-09-26",
        resource_id="agency-registry",
        source_module="refspec.atlas.v3_registry_alignments_entity",
        ring="entity",
        scope="publisherRelease",
        issued="2026-09-26",
        source_release_iri="urn:test:source-release:agency-registry:2026-09-26",
        source_release_digest=decisions_digest,
        inputs=(decisions_pin,),
        mappings=(bridge,),
        change_events=(fns_event, ins_event),
        editorial_policy={"admission": "owner humanReview of dated public records", "profile": "test-ref-072"},
        metadata={"eventCount": 2},
    )
    return (fr_release, ecfr_release), (mapping_release,)


def _construction_seeds_for(
    releases: tuple[generator.LoadedRelease, ...],
    mapping_releases: tuple[RegistryMappingRelease, ...],
) -> tuple[generator.ReleaseConstructionSeed, ...]:
    return tuple(generator._release_construction_seeds(releases, mapping_releases))


def _seal_and_compile_pack(
    distribution: Path,
    staged_tables: Path,
    view_dir: Path,
    pack_path: Path,
) -> tuple[dict[str, Any], Any]:
    manifest_digest = file_sha256(distribution / "atlas-manifest.json")
    view_manifest = seal_atlas_parquet_view(
        distribution,
        staged_tables,
        view_dir,
        expected_manifest_digest=manifest_digest,
        agency_projection={
            "status": "notEmitted",
            "missingReleaseKeys": ["regulations-gov-agency-identity-2026-08-16"],
        },
        derived_relations={"status": "notEmitted"},
    )
    view_digest = file_sha256(view_dir / VIEW_MANIFEST_FILE)
    verify_atlas_parquet_view(view_dir, expected_manifest_digest=view_digest)
    pack_manifest = build_vocabulary_pack(
        view_dir,
        pack_path,
        trusted_manifest_digest=view_digest,
    )
    return view_manifest, pack_manifest


def test_organization_change_events_project_byte_identically_and_populate_vocabulary_pack(
    tmp_path: Path,
) -> None:
    """Whole-graph and streamed builders both emit non-empty lifecycle-events.parquet, pass parity, and populate v3 packs."""

    releases, mapping_releases = _synthetic_agency_change_event_case(tmp_path)
    inventory = generator.verify_inputs(releases, mapping_releases)
    compiled_rows = generator._validate_compiled_producer_rows(releases, mapping_releases)
    seeds = _construction_seeds_for(releases, mapping_releases)
    plans = generator._release_pack_plans(releases, mapping_releases)
    prebuild = generator.ProducerPrebuildValidation(
        compiled_rows=compiled_rows,
        construction_seeds=seeds,
        generation_report=generator._producer_generation_report(
            releases,
            mapping_releases,
            input_inventory=inventory,
            producer_validation=compiled_rows,
        ),
        input_inventory=inventory,
        pack_plans=plans,
    )

    # 1. Whole-graph build
    whole_dist = tmp_path / "whole" / "distribution"
    whole_staged = tmp_path / "whole" / "staged-tables"
    whole_view = tmp_path / "whole" / "parquet-view"
    whole_pack = tmp_path / "whole" / "vocab.sqlite"
    graphs = generator._build_graphs(releases, mapping_releases=mapping_releases, include_projection=False)
    try:
        compiled_validation = generator._validate_compiled_producer_output(
            releases,
            graphs,
            compiled_rows,
            mapping_releases,
        )
        whole_result, _whole_manifest = generator._write_candidate_distribution(
            whole_dist,
            graphs,
            releases=plans,
            compiled_validation=compiled_validation,
            construction_seeds=seeds,
            created_at=TEST_CREATED_AT,
            parquet_tables=whole_staged,
        )
    finally:
        graphs.release()

    assert whole_result["parquetViewParity"]["status"] == "passed"
    assert whole_result["parquetViewParity"]["sampledRowsAgainstRdf"] > 0

    # 2. Streamed build
    stream_dist = tmp_path / "stream" / "distribution"
    stream_staged = tmp_path / "stream" / "staged-tables"
    stream_view = tmp_path / "stream" / "parquet-view"
    stream_pack = tmp_path / "stream" / "vocab.sqlite"
    stream_root = tmp_path / "stream-spool"
    stream_root.mkdir()
    streamed = generator._stream_construct_graphs(
        list(releases),
        list(mapping_releases),
        prebuild=prebuild,
        spool_root=stream_root,
    )
    stream_result, _stream_manifest = generator._write_streamed_candidate_distribution(
        stream_dist,
        streamed,
        plans,
        created_at=TEST_CREATED_AT,
        construction_seeds=seeds,
        parquet_tables=stream_staged,
    )
    assert stream_result["parquetViewParity"]["status"] == "passed"
    assert stream_result["parquetViewParity"]["sampledRowsAgainstRdf"] > 0

    # Whole-graph and streamed lifecycle-events.parquet must be byte-identical and carry 2 events.
    whole_pq = whole_staged / TABLE_DIRECTORY / TABLE_NAMES[CompactRecordRole.LIFECYCLE_EVENT]
    stream_pq = stream_staged / TABLE_DIRECTORY / TABLE_NAMES[CompactRecordRole.LIFECYCLE_EVENT]
    assert whole_pq.read_bytes() == stream_pq.read_bytes()

    table = pq.read_table(whole_pq)
    assert table.schema == TABLE_SCHEMAS[CompactRecordRole.LIFECYCLE_EVENT]
    rows = table.to_pylist()
    assert len(rows) == 2
    by_org = {row["applies_to"]: row for row in rows}
    assert set(by_org) == {FNS_IRI, INS_IRI}
    assert by_org[FNS_IRI]["id"].startswith(ATLAS_VALIDATE.CHANGE_EVENT_IRI_PREFIX)
    assert by_org[FNS_IRI]["lifecycle_event_kind"] == str(ATLAS.OrganizationChangeEvent)
    assert by_org[FNS_IRI]["effective_date"] == "2026-06-24T00:00:00+00:00"
    assert len(by_org[FNS_IRI]["source_records"]) == 1
    assert by_org[FNS_IRI]["from_release"] is None
    assert by_org[FNS_IRI]["to_release"] is None
    assert by_org[FNS_IRI]["content_digest"] == bytes.fromhex(
        by_org[FNS_IRI]["id"].removeprefix(ATLAS_VALIDATE.CHANGE_EVENT_IRI_PREFIX)
    )
    assert by_org[INS_IRI]["effective_date"] == "2003-03-01T00:00:00+00:00"
    assert len(by_org[INS_IRI]["source_records"]) == 2

    # Standalone validator must still validate both distributions cleanly (including construction counts).
    assert ATLAS_VALIDATE.validate_distribution(whole_dist)["counts"]["resources"] == 8
    assert ATLAS_VALIDATE.validate_distribution(stream_dist)["counts"]["resources"] == 8

    # Seal both Parquet views and compile v3 AtlasVocabularyPack SQLite.
    whole_view_manifest, whole_pack_manifest = _seal_and_compile_pack(
        whole_dist, whole_staged, whole_view, whole_pack
    )
    stream_view_manifest, stream_pack_manifest = _seal_and_compile_pack(
        stream_dist, stream_staged, stream_view, stream_pack
    )
    assert whole_view_manifest["counts"]["LifecycleEvent"] == 2
    assert stream_view_manifest["counts"]["LifecycleEvent"] == 2
    assert whole_view_manifest["counts"]["EvidenceBinding"] == 1
    assert stream_view_manifest["counts"]["EvidenceBinding"] == 1
    assert whole_pack_manifest.agency_change_event_count == 2
    assert stream_pack_manifest.agency_change_event_count == 2

    view_digest = file_sha256(stream_view / VIEW_MANIFEST_FILE)
    with AtlasVocabularyPack.open(stream_pack, trusted_manifest_digest=view_digest) as pack:
        all_events = pack.agency_change_events_sync()
        assert len(all_events) == 2
        assert [event["effectiveDate"] for event in all_events] == [
            "2003-03-01T00:00:00+00:00",
            "2026-06-24T00:00:00+00:00",
        ]
        fns_events = pack.agency_change_events_sync(applies_to=FNS_IRI)
        assert len(fns_events) == 1
        assert fns_events[0]["appliesTo"] == FNS_IRI
        assert fns_events[0]["eventKind"] == str(ATLAS.OrganizationChangeEvent)
        assert fns_events[0]["effectiveDate"] == "2026-06-24T00:00:00+00:00"
        assert len(fns_events[0]["sourceRecords"]) == 1
        assert fns_events[0]["fromRelease"] is None
        assert fns_events[0]["toRelease"] is None

        by_kind = pack.agency_change_events_sync(event_kind=str(ATLAS.OrganizationChangeEvent))
        assert len(by_kind) == 2


def test_organization_change_event_parity_refuses_tampering_and_omission(
    tmp_path: Path,
) -> None:
    """Parquet parity refuses drifted change-event fields, dropped rows, and unasserted rows."""

    releases, mapping_releases = _synthetic_agency_change_event_case(tmp_path)
    graphs = generator._build_graphs(releases, mapping_releases=mapping_releases, include_projection=False)
    try:
        # RDF logical record ids keep LifecycleEvent = RKAF.LifecycleEvent only (for construction-summary counts),
        # while served view ids include OrganizationChangeEvent and continue omitting change-event bindings.
        rdf_ids = ATLAS_VALIDATE._rdf_record_ids_by_role(graphs.asserted)
        served_ids = ATLAS_VALIDATE._served_record_ids_by_role(graphs.asserted)
        assert rdf_ids["LifecycleEvent"] == set()
        assert len(served_ids["LifecycleEvent"]) == 2
        assert len(rdf_ids["EvidenceBinding"]) == 4
        assert len(served_ids["EvidenceBinding"]) == 1

        pack_root = tmp_path / "packed"
        pack_root.mkdir()
        tables = tmp_path / "parquet-tables"
        writer = AtlasParquetTableWriter(tables)
        record_counts: dict[str, dict[str, int]] = {}
        generator._write_asserted_packs(
            pack_root,
            graphs.asserted,
            generator._release_pack_plans(releases, mapping_releases),
            parquet=writer,
            record_counts=record_counts,
        )
        writer.close()
        # Construction summary counts stay zero for lifecycleEvents under REF-072.
        assert all(counts["lifecycleEvents"] == 0 for counts in record_counts.values())

        assert generator._check_parquet_view_against_graph(tables, graphs.asserted)["status"] == "passed"

        table_path = tables / TABLE_DIRECTORY / TABLE_NAMES[CompactRecordRole.LIFECYCLE_EVENT]
        original_table = pq.read_table(table_path)
        original_rows = original_table.to_pylist()
        assert len(original_rows) == 2

        # 1. Tamper effective_date -> construction.parquet refusal
        drifted = [dict(row) for row in original_rows]
        drifted[0]["effective_date"] = "1999-01-01T00:00:00+00:00"
        pq.write_table(pa.Table.from_pylist(drifted, schema=original_table.schema), table_path, compression="zstd")
        with pytest.raises(ATLAS_VALIDATE.AtlasValidationError) as exc_info:
            generator._check_parquet_view_against_graph(tables, graphs.asserted)
        assert exc_info.value.code == "construction.parquet"
        assert "effective_date" in exc_info.value.detail

        # 2. Drop one change-event row -> construction.reachability refusal
        pq.write_table(
            pa.Table.from_pylist(original_rows[:1], schema=original_table.schema),
            table_path,
            compression="zstd",
        )
        with pytest.raises(ATLAS_VALIDATE.AtlasValidationError) as exc_info:
            generator._check_parquet_view_against_graph(tables, graphs.asserted)
        assert exc_info.value.code == "construction.reachability"
        assert "unreachable=" in exc_info.value.detail

        # 3. Substitute an unasserted row id -> construction.reachability refusal
        substituted = [dict(row) for row in original_rows]
        substituted[0]["id"] = ATLAS_VALIDATE.CHANGE_EVENT_IRI_PREFIX + "0" * 64
        pq.write_table(
            pa.Table.from_pylist(substituted, schema=original_table.schema),
            table_path,
            compression="zstd",
        )
        with pytest.raises(ATLAS_VALIDATE.AtlasValidationError) as exc_info:
            generator._check_parquet_view_against_graph(tables, graphs.asserted)
        assert exc_info.value.code == "construction.reachability"
        assert "unasserted=" in exc_info.value.detail
    finally:
        graphs.release()


def test_real_agency_registry_release_populates_ten_lifecycle_events_in_vocabulary_pack(
    tmp_path: Path,
) -> None:
    """Real agency-registry-2026-09-26 (including FNS -> FNA) projects all 10 events into a v3 AtlasVocabularyPack."""

    source_root = Path(os.environ.get("REFSPEC_REAL_DATA_ROOT", str(ROOT)))
    if not (source_root / "output" / "registry-real-data-sources" / "EHRI-Data-Standards-20260804.xlsx").is_file():
        pytest.skip("pinned real agency roster inputs are absent; set REFSPEC_REAL_DATA_ROOT or fetch pinned inputs")

    from refspec.atlas import v3_registry_alignments_entity as entity
    from tools import analyze_agency_roster_identifiers as census

    rosters = census.load_five_agency_rosters(source_root)
    agency_mapping = entity.load_agency_registry_mapping_release(rosters)
    # Include the three rosters referenced by agency-registry-2026-09-26's 13 bridges and 10 events;
    # clear cross-ring relations on eCFR/FH so CFR titles and Treasury accounts are not needed here.
    referenced_keys = {
        "federal-register-agencies-roster-2026-08-15",
        "ecfr-agencies-roster-2026-08-15",
        "federal-hierarchy-orgs-complete-2026-08-15",
    }
    loaded_rosters = []
    for roster in rosters:
        if roster.key not in referenced_keys:
            continue
        roster_iris = {resource.iri for resource in roster.resources}
        intra_relations = tuple(
            relation
            for relation in roster.relations
            if relation.subject in roster_iris and relation.object in roster_iris
        )
        loaded_rosters.append(
            generator._adapt_registry_release(
                dataclasses.replace(
                    roster,
                    relations=intra_relations,
                    cross_ring_relations=(),
                )
            )
        )
    loaded_rosters_tuple = tuple(loaded_rosters)
    mapping_releases = (agency_mapping,)
    plans = generator._release_pack_plans(loaded_rosters_tuple, mapping_releases)
    seeds = _construction_seeds_for(loaded_rosters_tuple, mapping_releases)
    inventory = generator.verify_inputs(loaded_rosters_tuple, mapping_releases)
    compiled_rows = generator._validate_compiled_producer_rows(loaded_rosters_tuple, mapping_releases)
    prebuild = generator.ProducerPrebuildValidation(
        compiled_rows=compiled_rows,
        construction_seeds=seeds,
        generation_report=generator._producer_generation_report(
            loaded_rosters_tuple,
            mapping_releases,
            input_inventory=inventory,
            producer_validation=compiled_rows,
        ),
        input_inventory=inventory,
        pack_plans=plans,
    )

    dist = tmp_path / "real-agency" / "distribution"
    staged = tmp_path / "real-agency" / "staged-tables"
    view_dir = tmp_path / "real-agency" / "parquet-view"
    pack_path = tmp_path / "real-agency" / "vocab.sqlite"
    spool_root = tmp_path / "real-spool"
    spool_root.mkdir()

    streamed = generator._stream_construct_graphs(
        list(loaded_rosters_tuple),
        list(mapping_releases),
        prebuild=prebuild,
        spool_root=spool_root,
    )
    result, _manifest = generator._write_streamed_candidate_distribution(
        dist,
        streamed,
        plans,
        created_at=TEST_CREATED_AT,
        construction_seeds=seeds,
        parquet_tables=staged,
    )
    assert result["parquetViewParity"]["status"] == "passed"

    view_manifest, pack_manifest = _seal_and_compile_pack(dist, staged, view_dir, pack_path)
    assert view_manifest["counts"]["LifecycleEvent"] == 10
    assert pack_manifest.agency_change_event_count == 10

    view_digest = file_sha256(view_dir / VIEW_MANIFEST_FILE)
    with AtlasVocabularyPack.open(pack_path, trusted_manifest_digest=view_digest) as pack:
        all_events = pack.agency_change_events_sync()
        assert len(all_events) == 10
        fns_events = pack.agency_change_events_sync(applies_to=FNS_IRI)
        assert len(fns_events) == 1
        assert fns_events[0]["effectiveDate"] == "2026-06-24T00:00:00+00:00"
        assert fns_events[0]["eventKind"] == str(ATLAS.OrganizationChangeEvent)
        assert len(fns_events[0]["sourceRecords"]) == 3


def test_multi_original_merger_change_event_fails_closed() -> None:
    """A 2-original OrganizationChangeEvent merger fails closed instead of truncating originals[1:]."""

    rkaf = generator.RKAF
    event = URIRef(ATLAS_VALIDATE.CHANGE_EVENT_IRI_PREFIX + "0" * 64)
    binding = URIRef("urn:ref:atlas-evidence:merger-1")
    source_record = URIRef("urn:ref:atlas-source-record:merger-authority")
    graph = Graph()
    graph.add((event, RDF.type, ATLAS.OrganizationChangeEvent))
    graph.add((event, ATLAS.originalOrganization, URIRef(FNS_IRI)))
    graph.add((event, ATLAS.originalOrganization, URIRef(INS_IRI)))
    graph.add((event, ATLAS.resultingOrganization, URIRef(FNA_IRI)))
    graph.add((event, rkaf.effectiveDate, Literal("2026-06-24T00:00:00+00:00", datatype=XSD.dateTime)))
    graph.add((binding, RDF.type, rkaf.EvidenceBinding))
    graph.add((binding, rkaf.bindsAssertion, event))
    graph.add((binding, ATLAS.evidenceSourceRecord, source_record))

    with pytest.raises(ValueError, match="2 original organizations"):
        generator._compact_record_from_graph(graph, event, CompactRecordRole.LIFECYCLE_EVENT)

    with pytest.raises(ATLAS_VALIDATE.AtlasValidationError) as exc_info:
        ATLAS_VALIDATE.parquet_row_from_rdf(graph, event, "LifecycleEvent")
    assert exc_info.value.code == "construction.parquet"
    assert "2 original organizations" in exc_info.value.detail


def test_dual_typed_organization_change_event_fails_closed_with_and_without_parquet_view(
    tmp_path: Path,
) -> None:
    """A subject carrying OrganizationChangeEvent plus another compact carrier type fails closed everywhere."""

    rkaf = generator.RKAF
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    releases, mapping_releases = _synthetic_agency_change_event_case(inputs_dir)
    plans = generator._release_pack_plans(releases, mapping_releases)
    graphs = generator._build_graphs(releases, mapping_releases=mapping_releases, include_projection=False)
    try:
        events = sorted(graphs.asserted.subjects(RDF.type, ATLAS.OrganizationChangeEvent), key=str)
        assert events
        dual_event = events[0]
        pack_owners, releases_by_key = generator._release_subject_owners(graphs.asserted, plans)
        # Corrupt the event to also carry AtlasResource (and check --no-parquet-view too).
        graphs.asserted.add((dual_event, RDF.type, ATLAS.AtlasResource))

        with pytest.raises(ValueError, match="cannot also carry compact carrier type"):
            generator._project_logical_records(
                graphs.asserted,
                pack_owners=pack_owners,
                releases_by_key=releases_by_key,
                parquet=None,
            )

        with (
            AtlasParquetTableWriter(tmp_path / "tables") as writer,
            pytest.raises(ValueError, match="cannot also carry compact carrier type"),
        ):
            generator._project_logical_records(
                graphs.asserted,
                pack_owners=pack_owners,
                releases_by_key=releases_by_key,
                parquet=writer,
            )

        with pytest.raises(ATLAS_VALIDATE.AtlasValidationError) as exc_info:
            ATLAS_VALIDATE.parquet_row_from_rdf(graphs.asserted, dual_event, "LifecycleEvent")
        assert exc_info.value.code == "construction.sample"
        assert "cannot be both Resource and OrganizationChangeEvent" in exc_info.value.detail

        # Streamed spool append_graph must reject the same dual-typed subject immediately.
        spool_root = tmp_path / "dual-spool"
        spool_root.mkdir()
        mapping_plan = next(plan for plan in plans if plan.kind == "mapping")
        spool = generator._StreamingGraphSpool(
            spool_root,
            plans,
            resource_owner_tokens={},
            catalog=Graph(),
        )
        single_event_graph = Graph()
        for triple in graphs.asserted.triples((dual_event, None, None)):
            single_event_graph.add(triple)
        for binding in graphs.asserted.subjects(rkaf.bindsAssertion, dual_event):
            for triple in graphs.asserted.triples((binding, None, None)):
                single_event_graph.add(triple)
        with pytest.raises(ValueError, match="cannot also carry compact carrier type"):
            spool.append_graph(single_event_graph, mapping_plan)
    finally:
        graphs.release()


def test_cross_pack_change_event_and_effective_period_sampling_in_one_second_pass(
    tmp_path: Path,
) -> None:
    """_independent_rows_for_subjects resolves cross-pack change-event bindings and effective periods positionally."""

    rkaf = generator.RKAF
    graph_id = URIRef(generator._ROLE_GRAPH_IDS["asserted"])

    event = URIRef(ATLAS_VALIDATE.CHANGE_EVENT_IRI_PREFIX + "a" * 64)
    binding = URIRef("urn:ref:atlas-evidence:cross-pack-binding-1")
    source_record = URIRef("urn:ref:atlas-source-record:cross-pack-record-1")
    decoy_record = URIRef("urn:ref:atlas-source-record:decoy-literal-only")

    statement = URIRef("urn:ref:atlas-statement:cross-pack-dated-1")
    period = URIRef("urn:ref:atlas-effective-period:cross-pack-period-1")
    release_iri = URIRef("urn:ref:atlas-release:cross-pack-test")
    subject_iri = URIRef(FNS_IRI)
    object_iri = URIRef(FNA_IRI)

    # Pack A holds the event, the statement, and decoy literals mentioning predicate IRIs.
    pack_a_triples = [
        (event, RDF.type, ATLAS.OrganizationChangeEvent),
        (event, ATLAS.originalOrganization, URIRef(FNS_IRI)),
        (event, ATLAS.resultingOrganization, URIRef(FNA_IRI)),
        (event, rkaf.effectiveDate, Literal("2026-06-24T00:00:00+00:00", datatype=XSD.dateTime)),
        # Decoy literal containing `<bindsAssertion>` and `<evidenceSourceRecord>` text must not be matched.
        (
            decoy_record,
            ATLAS.nativePayload,
            Literal(f"<{binding}> <{rkaf.bindsAssertion}> <{event}> <{ATLAS.evidenceSourceRecord}> <{decoy_record}>"),
        ),
        (statement, RDF.type, ATLAS.RelationAssertion),
        (statement, RDF.type, ATLAS.MappingAssertion),
        (statement, RDF.subject, subject_iri),
        (statement, RDF.predicate, ATLAS.sameEntityAs),
        (statement, RDF.object, object_iri),
        (statement, ATLAS.sourceRelease, release_iri),
        (statement, ATLAS.targetRelease, release_iri),
        (statement, ATLAS.governedByPolicy, URIRef("urn:ref:atlas-policy:cross-pack-test")),
        (statement, rkaf.assertedAt, Literal("2026-06-24T00:00:00+00:00", datatype=XSD.dateTime)),
        (statement, ATLAS.semanticRing, ATLAS.entity),
        (statement, ATLAS.assertionIdentityDigest, Literal("sha256:" + "1" * 64)),
        (statement, rkaf.hasEffectivePeriod, period),
    ]
    # Pack B holds the event's binding (and its evidenceSourceRecord) PLUS the statement's EffectivePeriod.
    pack_b_triples = [
        (binding, RDF.type, rkaf.EvidenceBinding),
        (binding, rkaf.bindsAssertion, event),
        (binding, ATLAS.evidenceSourceRecord, source_record),
        (period, RDF.type, rkaf.EffectivePeriod),
        (period, rkaf.effectivePeriodStart, Literal("2026-01-01T00:00:00+00:00", datatype=XSD.dateTime)),
        (period, rkaf.effectivePeriodEnd, Literal("2026-12-31T23:59:59+00:00", datatype=XSD.dateTime)),
    ]

    spool_root = tmp_path / "cross-pack-spool"
    spool_root.mkdir()
    spool = generator._StreamingGraphSpool(
        spool_root,
        [],
        resource_owner_tokens={},
        catalog=Graph(),
    )
    pack_a = spool_root / "pack-a.sorted.nq"
    pack_b = spool_root / "pack-b.sorted.nq"
    pack_a.write_text(
        "".join(ATLAS_VALIDATE.nquads_line(s, p, o, graph_id) + "\n" for s, p, o in pack_a_triples),
        encoding="utf-8",
    )
    pack_b.write_text(
        "".join(ATLAS_VALIDATE.nquads_line(s, p, o, graph_id) + "\n" for s, p, o in pack_b_triples),
        encoding="utf-8",
    )
    spool.sorted_rdf_paths = {("pack-a", None): pack_a, ("pack-b", None): pack_b}

    rows = spool._independent_rows_for_subjects(
        [
            (str(event), CompactRecordRole.LIFECYCLE_EVENT),
            (str(statement), CompactRecordRole.STATEMENT),
        ]
    )
    assert len(rows) == 2
    event_row, stmt_row = rows
    assert event_row["id"] == str(event)
    assert event_row["applies_to"] == FNS_IRI
    assert event_row["source_records"] == [str(source_record)]
    assert stmt_row["id"] == str(statement)
    assert stmt_row["effective_period_start"] == "2026-01-01T00:00:00+00:00"
    assert stmt_row["effective_period_end"] == "2026-12-31T23:59:59+00:00"
