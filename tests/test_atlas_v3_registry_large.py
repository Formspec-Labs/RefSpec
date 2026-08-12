"""Focused normalization checks for the large Atlas 3 registry loaders."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from refspec.atlas import v3_registry_large as large
from refspec.atlas.v3_source_data import RegistryInputPin
from refspec.registry import courtlistener_codes as courtlistener
from refspec.registry import fast_topical, naics_psc_codes, opm_workforce_codes
from refspec.registry.infrastructure.source_identity import validate_uuid7

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parents[1]
PLUM_REAL_SOURCE = ROOT / "output/registry-real-data-sources/OPM-PLUM-all-data-20260804.csv"


def _input_pin(tmp_path: Path, payload: bytes = b"exact source") -> RegistryInputPin:
    path = tmp_path / "source.bin"
    path.write_bytes(payload)
    return RegistryInputPin(
        path=path,
        logical_path="tests/source.bin",
        sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        byte_length=len(payload),
        source_iri="https://publisher.example/source",
    )


def _assert_readable_uuid7(iri: str, token: str) -> None:
    prefix = f"urn:ref:source-concept:v2:{token}:"
    assert iri.startswith(prefix)
    validate_uuid7(iri.removeprefix(prefix))


def test_fast_keeps_exact_ids_and_only_active_direct_hierarchy(
    tmp_path: Path,
) -> None:
    first = fast_topical.FASTTopicalNativeRow(
        numeric_id="100",
        legacy_fst_id="fst00000100",
        uri="http://id.worldcat.org/fast/100",
        heading="Export trade",
        alt_labels=("Exports", "", " Exports ", "   ", "International exports "),
        broader_ids=("200", "999"),
    )
    parent = fast_topical.FASTTopicalNativeRow(
        numeric_id="200",
        legacy_fst_id="fst00000200",
        uri="http://id.worldcat.org/fast/200",
        heading="International trade",
        alt_labels=(),
        broader_ids=(),
    )
    snapshot = fast_topical.ParsedFASTTopicalNativeSnapshot(
        base_sha256="sha256:" + "1" * 64,
        base_byte_length=1,
        base_active_count=2,
        change_summaries=(),
        topical_event_count=1,
        unique_changed_id_count=1,
        latest_change_status_counts={"x": 1},
        facet_migration_count=0,
        rows=(first, parent),
        tombstones=(
            fast_topical.FASTTopicalTombstone(
                numeric_id="999",
                status="x",
                replacement_ids=("200",),
                automatically_linked=True,
            ),
        ),
    )

    release = large._fast_release_from_snapshot(snapshot, (_input_pin(tmp_path),))

    assert release.profile == "conceptScheme"
    assert release.ring == "subject"
    assert release.resource_id == "fast-topical"
    assert release.scheme_iri == "urn:ref:atlas-resource-scheme:fast-topical"
    assert [resource.iri for resource in release.resources] == [first.uri, parent.uri]
    assert all(resource.source_digest == release.source_release_digest for resource in release.resources)
    assert [label.role for label in release.resources[0].labels] == [
        "preferred",
        "alternate",
        "alternate",
    ]
    assert [label.value for label in release.resources[0].labels] == [
        "Export trade",
        "Exports",
        "International exports",
    ]
    assert [(relation.subject, relation.object) for relation in release.relations] == [(first.uri, parent.uri)]
    assert release.metadata["tombstoneCount"] == 1
    assert release.metadata["tombstonesAreMembers"] is False
    assert release.metadata["droppedInactiveBroaderTargetCount"] == 1


def test_naics_and_psc_use_scoped_codes_without_inventing_hierarchy() -> None:
    naics = large.load_naics_release(
        FIXTURES / "naics_psc_codes/naics-2022-us-structure-2026-08-03.csv",
        parser_pin=naics_psc_codes.NAICS_CODES_2026_08_03,
    )
    psc = large.load_psc_release(
        FIXTURES / "naics_psc_codes/psc-manual-april-2025-2026-08-03.csv",
        parser_pin=naics_psc_codes.PSC_CODES_2026_08_03,
    )

    assert (len(naics.resources), len(psc.resources)) == (14, 8)
    assert naics.profile == psc.profile == "codeScheme"
    assert naics.ring == psc.ring == "value"
    assert (naics.resource_id, psc.resource_id) == ("naics", "psc")
    assert naics.scheme_iri == "urn:ref:atlas-resource-scheme:naics"
    assert psc.scheme_iri == "urn:ref:atlas-resource-scheme:psc"
    assert (naics.issued, psc.issued) == ("2022-01-01", "2025-04-01")
    _assert_readable_uuid7(naics.resources[0].iri, "naics-2022")
    _assert_readable_uuid7(psc.resources[0].iri, "psc-2025")
    assert naics.resources[0].notations == ("11",)
    assert psc.resources[0].notations == ("1005",)
    assert all(resource.source_digest == naics.inputs[0].sha256 for resource in naics.resources)
    assert all(resource.source_digest == psc.inputs[0].sha256 for resource in psc.resources)
    assert naics.source_release_digest == naics.inputs[0].sha256
    assert psc.source_release_digest == psc.inputs[0].sha256
    assert not naics.relations and not psc.relations
    assert naics.metadata["hierarchyRelationCount"] == 0


def test_courtlistener_keeps_platform_identity_and_activity() -> None:
    pin = courtlistener.CourtListenerJurisdictionsSnapshotPin(
        source_url=courtlistener.COURTLISTENER_JURISDICTIONS_URL,
        retrieved_at="2026-08-03T00:00:00Z",
        expected_sha256=("sha256:c85d10372cf161d1e1822de8a5a8ad5eca1be7ec47bef6552449fac500064f6c"),
        expected_byte_length=7_152,
    )
    release = large.load_courtlistener_jurisdictions_release(
        FIXTURES / "courtlistener_codes/courtlistener-jurisdictions-mini.html",
        parser_pin=pin,
        expected_count=6,
    )

    assert release.profile == "identifierScheme"
    assert release.ring == "entity"
    assert release.resource_id == "courtlistener-jurisdictions"
    assert release.scheme_iri == ("urn:ref:atlas-resource-scheme:courtlistener-jurisdictions")
    assert release.source_release_digest == release.inputs[0].sha256
    assert release.metadata["officialCourtIdentityClaimed"] is False
    scotus = next(resource for resource in release.resources if "scotus" in resource.notations)
    _assert_readable_uuid7(scotus.iri, "courtlistener")
    assert scotus.labels[0].value == "Supreme Court of the United States"
    assert scotus.status == "active"
    assert scotus.native_payload["identityStatus"] == "publisherPlatformIdentifier"


def test_federal_register_capture_ids_do_not_reuse_slugs_or_merge_2025() -> None:
    path = FIXTURES / "federal-register-topics-mini.json"
    payload = path.read_bytes()
    release = large.load_federal_register_topics_release(
        path,
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_byte_length=len(payload),
        expected_counts=(2, 1),
    )

    assert len(release.resources) == 3
    assert len(release.relations) == 1
    assert release.relations[0].predicate == large.SKOS_RELATED
    assert release.metadata["managedThesaurus2025Merged"] is False
    assert release.resource_id == "federal-register-api-topics"
    assert release.scheme_iri == ("urn:ref:atlas-resource-scheme:federal-register-api-topics")
    assert release.source_release_digest == release.inputs[0].sha256
    assert all(resource.native_payload["identityStatus"] == "sourceLocalCaptureRow" for resource in release.resources)
    assert all(not resource.iri.endswith(resource.notations[0]) for resource in release.resources if resource.notations)


def test_opm_ehri_uses_field_and_code_identity_and_keeps_past_as_metadata(
    tmp_path: Path,
) -> None:
    field_a = opm_workforce_codes.OPMEHRIDataElement(
        name="FIELD A",
        description="First field",
        data_format="Text",
        data_length="2",
        valid_values="Codes",
        current_values="CurrentValues",
        past_values="PastValues",
    )
    field_b = opm_workforce_codes.OPMEHRIDataElement(
        name="FIELD B",
        description="Second field",
        data_format="Text",
        data_length="2",
        valid_values="Codes",
        current_values="CurrentValues",
        past_values="PastValues",
    )
    current = (
        opm_workforce_codes.OPMEHRIValue("FIELD A", "AA", "Alpha", "2020-01-01", "PRESENT"),
        opm_workforce_codes.OPMEHRIValue("FIELD B", "AA", "Another alpha", "2021-01-01", "PRESENT"),
    )
    past = (
        opm_workforce_codes.OPMEHRIValue("FIELD A", "AA", "Old alpha", "2010-01-01", "2019-12-31"),
        opm_workforce_codes.OPMEHRIValue("FIELD A", "ZZ", "Past only", "2000-01-01", "2009-12-31"),
    )
    input_pin = _input_pin(tmp_path)
    export = opm_workforce_codes.OPMEHRIDataStandardsExport(
        source_sha256=input_pin.sha256,
        source_byte_length=input_pin.byte_length,
        fields=(field_a, field_b),
        current_values=current,
        past_values=past,
    )

    release = large._opm_ehri_release_from_export(
        export,
        input_pin,
        issued="2026-08-04",
    )

    assert len(release.resources) == 2
    assert release.resources[0].iri != release.resources[1].iri
    assert all(resource.notations == ("AA",) for resource in release.resources)
    assert release.resources[0].native_payload["pastLifecycle"][0]["explanation"] == "Old alpha"
    assert release.metadata["pastOnlyIdentityCount"] == 1
    assert release.metadata["pastValuesAreMembers"] is False
    assert release.metadata["bulkPlumRowsIncluded"] is False
    assert release.resource_id == "opm-ehri-workforce-codes"
    assert release.scheme_iri == ("urn:ref:atlas-resource-scheme:opm-ehri-workforce-codes")
    assert release.source_release_digest == input_pin.sha256
    assert all(resource.source_digest == input_pin.sha256 for resource in release.resources)


@pytest.mark.skipif(
    not PLUM_REAL_SOURCE.is_file(),
    reason="the pinned official OPM PLUM CSV is not present in this checkout",
)
def test_opm_plum_real_cache_publishes_only_closed_non_person_values() -> None:
    release = large.load_opm_plum_release(PLUM_REAL_SOURCE)

    resources_by_category: dict[str, list] = {}
    for resource in release.resources:
        category = resource.native_payload["category"]
        resources_by_category.setdefault(category, []).append(resource)

    assert {category: len(resources) for category, resources in resources_by_category.items()} == {
        "appointmentType": 12,
        "payPlan": 13,
        "positionStatus": 2,
    }
    assert len(release.resources) == 27
    assert not release.relations
    assert release.resource_id == "opm-plum-position-status-codes"
    assert release.profile == "codeScheme"
    assert release.ring == "value"
    assert release.scheme_iri == ("urn:ref:atlas-resource-scheme:opm-plum-position-status-codes")
    assert release.source_release_digest == large.OPM_PLUM_SHA256
    assert release.inputs[0].byte_length == large.OPM_PLUM_BYTE_LENGTH
    assert release.metadata["sourceRecordCount"] == 15_777
    assert release.metadata["emittedControlledValueCount"] == 27
    assert release.metadata["blankPayPlanRowCount"] > 0
    assert release.metadata["blankValuesAreMembers"] is False
    assert release.metadata["bulkPositionRowsIncluded"] is False
    assert release.metadata["personRowsIncluded"] is False
    assert release.metadata["personIdentityFieldsIncluded"] is False
    assert {resource.notations[0] for resource in resources_by_category["positionStatus"]} == {
        "Filled",
        "Vacant",
    }
    assert "" not in {resource.notations[0] for resources in resources_by_category.values() for resource in resources}
    assert len({resource.iri for resource in release.resources}) == 27
    for resource in release.resources:
        _assert_readable_uuid7(resource.iri, "opm-plum")
        assert resource.labels[0].role == "preferred"
        assert resource.labels[0].value == resource.notations[0]
        assert resource.source_digest == large.OPM_PLUM_SHA256
        assert set(resource.native_payload) == {
            "category",
            "identityScope",
            "identityStatus",
            "sourceColumn",
            "value",
        }

    serialized = json.dumps(
        {
            "metadata": release.metadata,
            "resources": [resource.native_payload for resource in release.resources],
        },
        sort_keys=True,
    )
    for forbidden_person_field in (
        "incumbentFirstName",
        "incumbentLastName",
        "incumbent_first_name",
        "incumbent_last_name",
    ):
        assert forbidden_person_field not in serialized


def test_large_loader_bindings_match_catalog_index_and_profile_map() -> None:
    catalog = json.loads((ROOT / "portfolio/resource-catalog-v0.json").read_bytes())
    atlas_index = json.loads((ROOT / "portfolio/atlas-index-v0.json").read_bytes())
    profile_map = json.loads((ROOT / "bindings/atlas/3.1/registry-resource-profiles.json").read_bytes())
    catalog_by_id = {row["resourceId"]: row for row in catalog["resources"]}
    index_by_id = {
        row["resourceId"]: row for row in atlas_index["rows"] if row["resourceId"] in large.LARGE_REGISTRY_BINDINGS
    }

    assert set(index_by_id) == set(large.LARGE_REGISTRY_BINDINGS)
    for resource_id, binding in large.LARGE_REGISTRY_BINDINGS.items():
        catalog_row = catalog_by_id[resource_id]
        index_row = index_by_id[resource_id]
        matching_profiles = [
            row["profile"] for row in profile_map["profiles"] if catalog_row["resourceKind"] in row["resourceKinds"]
        ]
        assert matching_profiles == [binding.profile]
        assert catalog_row["resourceKind"] == binding.resource_kind
        assert index_row["sourceModule"] == binding.source_module
        assert index_row["semanticRing"] == binding.ring
        assert binding.scheme_iri == f"urn:ref:atlas-resource-scheme:{resource_id}"


def test_loader_fails_closed_before_parsing_tampered_bytes(tmp_path: Path) -> None:
    source = tmp_path / "naics.csv"
    source.write_bytes((FIXTURES / "naics_psc_codes/naics-2022-us-structure-2026-08-03.csv").read_bytes() + b"\n")

    with pytest.raises(ValueError, match="input pin differs"):
        large.load_naics_release(
            source,
            parser_pin=naics_psc_codes.NAICS_CODES_2026_08_03,
        )
