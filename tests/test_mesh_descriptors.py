"""Offline tests for streaming MeSH descriptor parsing and packaging."""

from __future__ import annotations

import hashlib
import os
from collections import Counter
from pathlib import Path

import pytest

from refspec.registry import mesh_descriptors as mesh

FIXTURES = Path(__file__).parent / "fixtures" / "mesh_descriptors"
FIXTURE_PATH = FIXTURES / "mesh-descriptors-mini.xml"
SOURCE_URL = "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/desc2026.xml"


def _fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


def _parse(**kwargs: object) -> mesh.MeshDescriptorSnapshot:
    return mesh.parse_mesh_descriptor_bytes(_fixture_bytes(), source_url=SOURCE_URL, **kwargs)


def test_real_full_distribution_shape_count_and_boundary_samples() -> None:
    source_path_text = os.environ.get("REFSPEC_MESH_DESCRIPTORS_PATH")
    if source_path_text is None:
        pytest.skip("real MeSH descriptor distribution is not configured")
    snapshot = mesh.parse_mesh_descriptor_file(Path(source_path_text), source_url=SOURCE_URL)

    assert snapshot.source_byte_length == 312_952_703
    assert snapshot.source_sha256 == (
        "sha256:9b034cad8bbd4d8d1ef43816d6fd78d33fada52eddff2a0b4455b1fca35cc5ba"
    )
    assert len(snapshot.descriptors) == 31_110
    assert Counter(descriptor.descriptor_class for descriptor in snapshot.descriptors) == {
        "1": 30_512,
        "2": 194,
        "3": 2,
        "4": 402,
    }
    assert sum(len(descriptor.tree_numbers) for descriptor in snapshot.descriptors) == 65_360
    assert sum(not descriptor.tree_numbers for descriptor in snapshot.descriptors) == 2
    # NLM publishes 134,904 non-permuted Term elements. One per descriptor is
    # the preferred heading, leaving these source-authored alternate labels.
    assert sum(len(descriptor.entry_terms) for descriptor in snapshot.descriptors) == 103_794
    assert (snapshot.descriptors[0].descriptor_ui, snapshot.descriptors[0].heading) == (
        "D000001",
        "Calcimycin",
    )
    assert (snapshot.descriptors[-1].descriptor_ui, snapshot.descriptors[-1].heading) == (
        "D000099317",
        "Hippo Kinases",
    )


def test_streaming_parser_extracts_the_descriptor_table_fields() -> None:
    snapshot = _parse()

    assert snapshot.language_code == "eng"
    assert len(snapshot.descriptors) == 3
    by_ui = {d.descriptor_ui: d for d in snapshot.descriptors}
    assert set(by_ui) == {"D000001", "D000002", "D000003"}

    calcimycin = by_ui["D000001"]
    assert calcimycin.heading == "Calcimycin"
    assert calcimycin.descriptor_class == "1"
    assert calcimycin.tree_numbers == (
        "D02.355.291.933.125",
        "D02.540.576.625.125",
        "D03.633.100.221.173",
        "D04.345.241.654.125",
        "D04.345.674.625.125",
    )
    assert "A-23187" in calcimycin.entry_terms
    assert "A23187" in calcimycin.entry_terms
    assert "A 23187" not in calcimycin.entry_terms
    assert "A23187, Antibiotic" not in calcimycin.entry_terms
    assert calcimycin.heading not in calcimycin.entry_terms
    assert calcimycin.concept_iri == "https://id.nlm.nih.gov/mesh/D000001"

    temefos = by_ui["D000002"]
    assert temefos.heading == "Temefos"
    assert temefos.entry_terms == ("Temephos", "Difos", "Abate")

    abattoirs = by_ui["D000003"]
    assert abattoirs.heading == "Abattoirs"
    assert "Slaughterhouses" in abattoirs.entry_terms
    assert "Slaughter House" in abattoirs.entry_terms
    assert "Slaughterhouse" not in abattoirs.entry_terms
    assert abattoirs.tree_numbers == ("J01.576.423.200.700.100", "J03.540.020")


def test_descriptor_ui_is_the_real_publisher_identifier_not_a_minted_one() -> None:
    snapshot = _parse()
    calcimycin = next(d for d in snapshot.descriptors if d.descriptor_ui == "D000001")
    identifier = calcimycin.identifiers[0]

    assert identifier.kind == "publisherDescriptorUI"
    assert identifier.value == "D000001"
    assert identifier.authority_uri == "https://id.nlm.nih.gov/mesh/"
    assert identifier.source_uri == SOURCE_URL
    assert identifier.source_digest == snapshot.source_sha256


def test_source_digest_and_byte_length_are_computed_from_the_exact_stream() -> None:
    payload = _fixture_bytes()

    snapshot = _parse()

    assert snapshot.source_byte_length == len(payload)
    assert snapshot.source_sha256 == ("sha256:" + hashlib.sha256(payload).hexdigest())


def test_observed_at_is_threaded_into_every_identifier() -> None:
    observed_at = "2026-08-03T00:00:00Z"

    snapshot = _parse(observed_at=observed_at)

    assert snapshot.observed_at == observed_at
    assert all(
        identifier.observed_at == observed_at for descriptor in snapshot.descriptors for identifier in descriptor.identifiers
    )


def test_observed_at_must_be_an_iso_date_or_date_time() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        _parse(observed_at="August 3, 2026")


def test_supplemental_concept_record_root_is_rejected_not_silently_read() -> None:
    payload = _fixture_bytes().replace(b"DescriptorRecordSet", b"SupplementalRecordSet")

    with pytest.raises(mesh.MeshDescriptorError, match="Supplemental Concept Record"):
        mesh.parse_mesh_descriptor_bytes(payload, source_url=SOURCE_URL)


def test_unexpected_root_tag_is_rejected() -> None:
    payload = _fixture_bytes().replace(b"DescriptorRecordSet", b"QualifierRecordSet")

    with pytest.raises(mesh.MeshDescriptorError, match="root must be"):
        mesh.parse_mesh_descriptor_bytes(payload, source_url=SOURCE_URL)


def test_non_english_language_code_is_rejected() -> None:
    payload = _fixture_bytes().replace(b'LanguageCode = "eng"', b'LanguageCode = "fre"')

    with pytest.raises(mesh.MeshDescriptorError, match="LanguageCode"):
        mesh.parse_mesh_descriptor_bytes(payload, source_url=SOURCE_URL)


def test_duplicate_descriptor_ui_is_rejected() -> None:
    payload = _fixture_bytes().replace(
        b"<DescriptorUI>D000002</DescriptorUI>",
        b"<DescriptorUI>D000001</DescriptorUI>",
        1,
    )

    with pytest.raises(mesh.MeshDescriptorError, match="repeats DescriptorUI"):
        mesh.parse_mesh_descriptor_bytes(payload, source_url=SOURCE_URL)


def test_malformed_descriptor_ui_is_rejected() -> None:
    payload = _fixture_bytes().replace(
        b"<DescriptorUI>D000003</DescriptorUI>",
        b"<DescriptorUI>X000003</DescriptorUI>",
        1,
    )

    with pytest.raises(mesh.MeshDescriptorError, match="malformed DescriptorUI"):
        mesh.parse_mesh_descriptor_bytes(payload, source_url=SOURCE_URL)


def test_unsupported_descriptor_class_is_rejected() -> None:
    payload = _fixture_bytes().replace(b'DescriptorClass = "1"', b'DescriptorClass = "9"', 1)

    with pytest.raises(mesh.MeshDescriptorError, match="DescriptorClass"):
        mesh.parse_mesh_descriptor_bytes(payload, source_url=SOURCE_URL)


def test_dtd_valid_descriptor_classes_five_and_six_are_accepted() -> None:
    for descriptor_class in ("5", "6"):
        payload = _fixture_bytes().replace(
            b'DescriptorClass = "1"',
            f'DescriptorClass = "{descriptor_class}"'.encode(),
            1,
        )
        snapshot = mesh.parse_mesh_descriptor_bytes(payload, source_url=SOURCE_URL)
        assert snapshot.descriptors[0].descriptor_class == descriptor_class


def test_missing_permutation_flag_fails_closed() -> None:
    payload = _fixture_bytes().replace(b' IsPermutedTermYN="N"', b"", 1)

    with pytest.raises(mesh.MeshDescriptorError, match="IsPermutedTermYN"):
        mesh.parse_mesh_descriptor_bytes(payload, source_url=SOURCE_URL)


def test_empty_descriptor_record_set_is_rejected() -> None:
    payload = (
        b'<?xml version="1.0"?>\n'
        b'<DescriptorRecordSet LanguageCode = "eng">\n'
        b"</DescriptorRecordSet>\n"
    )

    with pytest.raises(mesh.MeshDescriptorError, match="no DescriptorRecord"):
        mesh.parse_mesh_descriptor_bytes(payload, source_url=SOURCE_URL)


def test_custom_xml_entity_declaration_is_rejected_before_parsing() -> None:
    payload = (
        b'<?xml version="1.0"?>\n'
        b'<!DOCTYPE DescriptorRecordSet [<!ENTITY xxe "pwned">]>\n'
        b'<DescriptorRecordSet LanguageCode = "eng">\n'
        b"</DescriptorRecordSet>\n"
    )

    with pytest.raises(mesh.MeshDescriptorError, match="custom XML entities"):
        mesh.parse_mesh_descriptor_bytes(payload, source_url=SOURCE_URL)


def test_malformed_xml_fails_loudly_instead_of_partially_parsing() -> None:
    payload = _fixture_bytes()[:-40]

    with pytest.raises(mesh.MeshDescriptorError, match="malformed"):
        mesh.parse_mesh_descriptor_bytes(payload, source_url=SOURCE_URL)


def test_parse_from_file_streams_without_reading_bytes_up_front(tmp_path: Path) -> None:
    source = tmp_path / "desc-mini.xml"
    source.write_bytes(_fixture_bytes())

    snapshot = mesh.parse_mesh_descriptor_file(source, source_url=SOURCE_URL)

    assert len(snapshot.descriptors) == 3


def test_parse_from_file_rejects_a_symlink(tmp_path: Path) -> None:
    source = tmp_path / "desc-mini.xml"
    source.write_bytes(_fixture_bytes())
    link = tmp_path / "linked.xml"
    link.symlink_to(source)

    with pytest.raises(mesh.MeshDescriptorError, match="not a regular file"):
        mesh.parse_mesh_descriptor_file(link, source_url=SOURCE_URL)


def test_import_never_opens_a_network_connection() -> None:
    # The module only parses bytes it is handed; no fetcher exists to call.
    assert not hasattr(mesh, "fetch_mesh_descriptor_file")
    assert not hasattr(mesh, "acquire_mesh_descriptors")


def test_package_build_and_reopen_round_trip(tmp_path: Path) -> None:
    payload = _fixture_bytes()
    snapshot = mesh.parse_mesh_descriptor_bytes(
        payload,
        source_url=SOURCE_URL,
        observed_at="2026-08-03T00:00:00Z",
    )

    bundle = mesh.build_mesh_descriptor_package(
        snapshot,
        resource_id="mesh-descriptors-mini",
        title="MeSH descriptors, fixture capture",
        captured_at="2026-08-03T00:00:00Z",
        source_payload=payload,
    )

    assert bundle.resource_manifest["resourceKind"] == "sourceTermSnapshot"
    assert bundle.resource_manifest["identityStatus"] == "publisherIdentifiersPreserved"
    assert bundle.resource_manifest["acceptedOutputUseAuthorized"] is False
    assert bundle.resource_manifest["conceptIdentityClaimed"] is False
    assert bundle.resource_manifest["observationCount"] == 3
    assert bundle.coverage_report["reportStatus"] == "pass"

    destination = tmp_path / "mesh-descriptors-package"
    bundle.write_to(destination)

    view = mesh.MeshDescriptorPackageView.open(destination)
    calcimycin = view.lookup("D000001")
    assert calcimycin is not None
    assert calcimycin["labels"][0] == {"value": "Calcimycin", "language": "en", "role": "preferred"}
    assert "A-23187" in [label["value"] for label in calcimycin["labels"] if label["role"] == "alternate"]
    assert calcimycin["treeNumbers"][0] == "D02.355.291.933.125"
    assert calcimycin["descriptorClass"] == "1"
    assert calcimycin["conceptIdentityClaimed"] is False
    assert view.lookup("D999999") is None


def test_package_rejects_a_source_payload_that_does_not_match_the_snapshot() -> None:
    payload = _fixture_bytes()
    snapshot = mesh.parse_mesh_descriptor_bytes(
        payload,
        source_url=SOURCE_URL,
        observed_at="2026-08-03T00:00:00Z",
    )

    with pytest.raises(mesh.MeshDescriptorError, match="does not match"):
        mesh.build_mesh_descriptor_package(
            snapshot,
            resource_id="mesh-descriptors-mini",
            title="MeSH descriptors, fixture capture",
            captured_at="2026-08-03T00:00:00Z",
            source_payload=payload + b"\n",
        )


def test_package_requires_a_concrete_observed_at_on_every_identifier() -> None:
    payload = _fixture_bytes()
    snapshot = mesh.parse_mesh_descriptor_bytes(payload, source_url=SOURCE_URL)

    with pytest.raises(ValueError, match="observedAt must be non-empty text"):
        mesh.build_mesh_descriptor_package(
            snapshot,
            resource_id="mesh-descriptors-mini",
            title="MeSH descriptors, fixture capture",
            captured_at="2026-08-03T00:00:00Z",
            source_payload=payload,
        )
