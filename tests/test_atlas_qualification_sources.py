"""Source-specific managed-release readers used by atlas qualification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

import refspec.registry.managed_releases.federal_register_thesaurus_2025_managed_release as federal_register_release
from refspec.atlas import qualification as qual
from refspec.atlas.federal_register import (
    FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI,
    PinnedFederalRegisterThesaurus2025AtlasRelease,
)
from refspec.atlas.icpsr import (
    ICPSR_RELEASE_IRI_PREFIX,
    PinnedIcpsrSubjectAtlasRelease,
)
from refspec.atlas.model import VocabularyAtlasError
from refspec.registry.federal_register_thesaurus_2025 import (
    load_packaged_federal_register_thesaurus_2025,
)
from refspec.registry.icpsr_subject import (
    build_icpsr_subject_index,
    parse_icpsr_subject_xml,
)
from refspec.registry.infrastructure.source_concept_release import SourceConceptReleaseView
from refspec.registry.managed_releases.federal_register_thesaurus_2025_managed_release import (
    build_federal_register_thesaurus_2025_managed_release,
)
from refspec.registry.managed_releases.icpsr_managed_release import (
    IcpsrManagedReleaseSources,
    build_icpsr_managed_release,
)
from refspec.storage import canonical_json

FIXTURES = Path(__file__).parent / "fixtures"
ROBOTS = b"User-agent: *\nDisallow: /cgi-bin/\n"
RECORDED_AT = "2026-07-30T16:00:00Z"
RECORDED_BY = "urn:test:agent:atlas-qualification-source"


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _federal_register_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    source_pdf = b"%PDF-1.7\ncomplete-705-concept-fixture\n"
    actual_sha256 = federal_register_release._sha256_bytes

    def fixture_sha256(payload: bytes) -> str:
        if payload == source_pdf:
            return federal_register_release.FEDERAL_REGISTER_THESAURUS_2025_SHA256
        return actual_sha256(payload)

    monkeypatch.setattr(federal_register_release, "_sha256_bytes", fixture_sha256)
    checked = load_packaged_federal_register_thesaurus_2025()
    parsed = replace(checked, source_artifact_bytes=source_pdf)
    release = build_federal_register_thesaurus_2025_managed_release(
        parsed,
        recorded_at="2026-07-31T00:00:00Z",
        recorded_by=RECORDED_BY,
    )
    return release.write_to(tmp_path / "federal-register-managed")["managed-release.json"]


def _icpsr_sources() -> IcpsrManagedReleaseSources:
    pages = {letter: (FIXTURES / f"icpsr-subject-index-{letter}-mini.html").read_bytes() for letter in ("a", "s", "t")}
    xml_payload = (FIXTURES / "icpsr-subject-mini.xml").read_bytes()
    index = build_icpsr_subject_index(
        pages,
        robots_body=ROBOTS,
        require_complete=False,
        observed_at=RECORDED_AT,
    )
    return IcpsrManagedReleaseSources(
        index=index,
        xml=parse_icpsr_subject_xml(xml_payload),
        source_capture_digest=index.capture_digest,
        source_manifest_digest="sha256:" + hashlib.sha256(b"fixture manifest").hexdigest(),
        source_artifacts={
            "index/robots.txt": ROBOTS,
            **{f"index/pages/{letter}.html": payload for letter, payload in pages.items()},
            "subject.xml": xml_payload,
        },
    )


def _icpsr_package(tmp_path: Path) -> Path:
    release = build_icpsr_managed_release(
        _icpsr_sources(),
        recorded_at=RECORDED_AT,
        recorded_by=RECORDED_BY,
        require_complete_index=False,
        expected_gap_counts=(0, 0),
    )
    return release.write_to(tmp_path / "icpsr-managed")


def _reseal(record: dict[str, object]) -> dict[str, object]:
    unsealed = {key: value for key, value in record.items() if key != "canonicalPayloadDigest"}
    digest = hashlib.sha256(canonical_json(unsealed).encode("utf-8")).hexdigest()
    return {**unsealed, "canonicalPayloadDigest": "sha256:" + digest}


def _forge_artifact(root: Path, relative: str, payload: bytes) -> None:
    manifest_path = root / "managed-release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    (root / relative).write_bytes(payload)
    manifest["artifacts"] = [
        (
            {
                **descriptor,
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "byteLength": len(payload),
            }
            if descriptor["path"] == relative
            else descriptor
        )
        for descriptor in manifest["artifacts"]
    ]
    manifest_path.write_text(canonical_json(_reseal(manifest)) + "\n", encoding="utf-8")


def test_federal_register_qualification_reader_exposes_the_complete_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _federal_register_package(tmp_path, monkeypatch)
    source = PinnedFederalRegisterThesaurus2025AtlasRelease.open(
        manifest_path,
        expected_manifest_digest=_file_digest(manifest_path),
    )
    view = source.verified_view()
    members = tuple(view.iter_members())
    expressions = tuple(view.iter_expressions())
    safety = next(
        member
        for member in members
        if member.record["http://www.w3.org/2004/02/skos/core#prefLabel"]["@value"] == "Safety"
    )

    assert len(members) == 705
    assert len(expressions) == 705 + 433
    assert safety.release_iri == FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI
    assert view.lookup_member(safety.member_iri) == safety
    assert source.pin()["manifestDigest"] == _file_digest(manifest_path)


def test_icpsr_qualification_reader_exposes_the_verified_fixture_subset(tmp_path: Path) -> None:
    manifest_path = _icpsr_package(tmp_path)
    source = PinnedIcpsrSubjectAtlasRelease.open(
        manifest_path,
        expected_manifest_digest=_file_digest(manifest_path),
    )
    view = source.verified_view()
    members = tuple(view.iter_members())
    expressions = tuple(view.iter_expressions())

    assert len(members) == 5
    assert view.reference_release_iri.startswith(ICPSR_RELEASE_IRI_PREFIX)
    assert {expression.original_literal for expression in expressions} >= {
        "ability",
        "talent",
        "Abolition movement",
    }
    assert all(view.lookup_member(member.member_iri) == member for member in members)
    assert source.pin()["manifestDigest"] == _file_digest(manifest_path)
    concepts = qual.concepts_from_view(view)
    abolition = next(concept for concept in concepts if concept.pref_label == "Abolition movement")
    social_movements = next(concept for concept in concepts if concept.pref_label == "social movements")
    assert tuple(parent.pref_label for parent in abolition.parents) == ("social movements",)
    assert tuple(child.pref_label for child in social_movements.children) == ("Abolition movement",)


def test_crs_source_concept_releases_project_exact_labels_and_definitions() -> None:
    evidence = (
        Path(__file__).resolve().parents[1]
        / "research/evidence/crs-source-concept-releases-2026-08-04"
    )
    legislative_path = evidence / "legislative-subjects/bundle-manifest.json"
    policy_path = evidence / "policy-areas/bundle-manifest.json"
    legislative = SourceConceptReleaseView.open(
        legislative_path,
        expected_manifest_digest=_file_digest(legislative_path),
    )
    policy = SourceConceptReleaseView.open(
        policy_path,
        expected_manifest_digest=_file_digest(policy_path),
    )

    legislative_concepts = qual.concepts_from_source_release(
        legislative,
        vocabulary="CRS Legislative Subject Terms",
    )
    policy_concepts = qual.concepts_from_source_release(policy, vocabulary="CRS Policy Areas")

    assert len(legislative_concepts) == 565
    assert len(policy_concepts) == 32
    assert {concept.pref_label for concept in legislative_concepts} >= {"Abortion", "Water quality"}
    agriculture = next(concept for concept in policy_concepts if concept.pref_label == "Agriculture and Food")
    assert agriculture.release == policy.release_id
    assert agriculture.definition is not None and "agricultural practices" in agriculture.definition
    assert all(concept.parents == concept.children == () for concept in policy_concepts)


def test_icpsr_qualification_reader_refuses_a_dropped_development_marker(tmp_path: Path) -> None:
    manifest_path = _icpsr_package(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["operationalState"] = "operational"
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")

    with pytest.raises(VocabularyAtlasError, match="development-only|canonicalPayloadDigest"):
        PinnedIcpsrSubjectAtlasRelease.open(
            manifest_path,
            expected_manifest_digest=_file_digest(manifest_path),
        )


def test_icpsr_qualification_reader_refuses_a_forged_release_identifier(tmp_path: Path) -> None:
    manifest_path = _icpsr_package(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["release"] = {
        **manifest["release"],
        "id": ICPSR_RELEASE_IRI_PREFIX + "0" * 64,
    }
    manifest_path.write_text(canonical_json(_reseal(manifest)) + "\n", encoding="utf-8")

    with pytest.raises(VocabularyAtlasError, match="not derived from its own source digests"):
        PinnedIcpsrSubjectAtlasRelease.open(
            manifest_path,
            expected_manifest_digest=_file_digest(manifest_path),
        )


def test_icpsr_qualification_reader_refuses_record_expression_disagreement(tmp_path: Path) -> None:
    manifest_path = _icpsr_package(tmp_path)
    root = manifest_path.parent
    concepts = [json.loads(line) for line in (root / "records/concepts.jsonl").read_bytes().splitlines()]
    concepts[0]["officialLabel"] = "forged label"
    _forge_artifact(
        root,
        "records/concepts.jsonl",
        b"".join(canonical_json(row).encode("utf-8") + b"\n" for row in concepts),
    )
    source = PinnedIcpsrSubjectAtlasRelease.open(
        manifest_path,
        expected_manifest_digest=_file_digest(manifest_path),
    )

    with pytest.raises(VocabularyAtlasError, match="state different text"):
        source.verified_view()


def test_icpsr_qualification_reader_refuses_a_wrong_external_manifest_digest(tmp_path: Path) -> None:
    manifest_path = _icpsr_package(tmp_path)

    with pytest.raises(VocabularyAtlasError, match="manifest digest differs"):
        PinnedIcpsrSubjectAtlasRelease.open(
            manifest_path,
            expected_manifest_digest="sha256:" + "0" * 64,
        )
