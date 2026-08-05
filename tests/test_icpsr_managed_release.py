"""Development-only ICPSR managed-release and reader tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from refspec.atlas.atlas_scope import AtlasScopeRelease
from refspec.atlas.concept_release import (
    ManagedReleaseRingAssignment,
    PinnedManagedReleaseRingAssignment,
)
from refspec.atlas.icpsr import (
    ICPSR_USE_PROPERTY_IRI,
    ICPSR_USED_FOR_PROPERTY_IRI,
    PinnedIcpsrManagedConceptRelease,
)
from refspec.atlas.release_snapshot import AtlasReleaseSnapshot
from refspec.registry.icpsr_subject import (
    build_icpsr_subject_index,
    parse_icpsr_subject_xml,
    write_icpsr_subject_index_capture,
)
from refspec.registry.managed_releases.icpsr_managed_release import (
    IcpsrManagedRelease,
    IcpsrManagedReleaseError,
    IcpsrManagedReleaseSources,
    IcpsrManagedReleaseView,
    build_icpsr_managed_release,
    open_icpsr_managed_release_sources,
)

FIXTURES = Path(__file__).parent / "fixtures"
REAL_CAPTURE = Path(__file__).resolve().parents[1] / "output" / "refspec-vocabulary-portfolio" / "icpsr" / "2026-07-30"
EVIDENCE = (
    Path(__file__).resolve().parents[1] / "research" / "evidence" / "icpsr-managed-release-2026-07-30" / "evidence.json"
)
ROBOTS = b"User-agent: *\nDisallow: /cgi-bin/\n"
RECORDED_AT = "2026-07-30T16:00:00Z"
RECORDED_BY = "urn:test:agent:icpsr-managed-release"
REAL_RECORDED_BY = "urn:ref:actor:codex-local-development"


def _fixture_pages() -> dict[str, bytes]:
    return {letter: (FIXTURES / f"icpsr-subject-index-{letter}-mini.html").read_bytes() for letter in ("a", "s", "t")}


def _fixture_sources() -> IcpsrManagedReleaseSources:
    pages = _fixture_pages()
    xml_payload = (FIXTURES / "icpsr-subject-mini.xml").read_bytes()
    index = build_icpsr_subject_index(
        pages,
        robots_body=ROBOTS,
        require_complete=False,
        observed_at=RECORDED_AT,
    )
    xml = parse_icpsr_subject_xml(xml_payload)
    source_artifacts = {
        "index/robots.txt": ROBOTS,
        **{f"index/pages/{letter}.html": payload for letter, payload in pages.items()},
        "subject.xml": xml_payload,
    }
    return IcpsrManagedReleaseSources(
        index=index,
        xml=xml,
        source_capture_digest=index.capture_digest,
        source_manifest_digest=("sha256:" + hashlib.sha256(b"fixture manifest").hexdigest()),
        source_artifacts=source_artifacts,
    )


def _build_fixture():
    return build_icpsr_managed_release(
        _fixture_sources(),
        recorded_at=RECORDED_AT,
        recorded_by=RECORDED_BY,
        require_complete_index=False,
        expected_gap_counts=(0, 0),
    )


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _atlas_snapshot(
    release: IcpsrManagedRelease,
    root: Path,
) -> AtlasReleaseSnapshot:
    manifest_path = release.write_to(root / "managed-release")
    manifest_digest = _file_digest(manifest_path)
    release_id = cast(str, release.manifest["release"]["id"])
    assignment = ManagedReleaseRingAssignment(
        managed_manifest_digest=manifest_digest,
        release_id=release_id,
        semantic_ring="subject",
        assigned_by="urn:test:actor:icpsr-atlas-reviewer",
        assigned_at=RECORDED_AT,
        evidence=("urn:test:evidence:icpsr-complete-verified-subset",),
    )
    assignment_path = assignment.write_to(root / "managed-release-ring-assignment.json")
    pinned_assignment = PinnedManagedReleaseRingAssignment.open(
        assignment_path,
        expected_file_digest=_file_digest(assignment_path),
    )
    selected = PinnedIcpsrManagedConceptRelease.open(
        manifest_path,
        expected_manifest_digest=manifest_digest,
        release_id=release_id,
        ring_assignment=pinned_assignment,
    )
    return AtlasReleaseSnapshot.create(AtlasScopeRelease(selected))


def _relation_count(snapshot: AtlasReleaseSnapshot) -> int:
    predicates = {
        "http://www.w3.org/2004/02/skos/core#broader",
        "http://www.w3.org/2004/02/skos/core#narrower",
        "http://www.w3.org/2004/02/skos/core#related",
        ICPSR_USE_PROPERTY_IRI,
        ICPSR_USED_FOR_PROPERTY_IRI,
    }

    def count(value: Any) -> int:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return len(value)
        return 1

    return sum(
        count(value)
        for concept in snapshot.concept_records
        for predicate, value in concept.items()
        if predicate in predicates
    )


def test_fixture_release_is_deterministic_and_development_only() -> None:
    first = _build_fixture()
    second = _build_fixture()

    assert first.manifest == second.manifest
    assert first.coverage == second.coverage
    assert first.concepts == second.concepts
    assert first.indexed_expressions == second.indexed_expressions
    assert first.manifest["operationalState"] == "developmentOnly"
    assert first.manifest["candidateLookupAllowed"] is True
    assert first.manifest["acceptedOutputAllowed"] is False
    assert first.manifest["counts"]["concepts"] == 5
    assert first.coverage["membershipCompleteForVerifiedSubset"] is True
    assert first.coverage["sourceVocabularyComplete"] is False


def test_fixture_projects_as_one_complete_verified_subset_snapshot(
    tmp_path: Path,
) -> None:
    snapshot = _atlas_snapshot(_build_fixture(), tmp_path)
    release_node = next(
        record
        for record in snapshot.record["selectedReleaseGraph"]["@graph"]
        if record["@id"] == snapshot.release_id
    )

    assert len(snapshot.member_ids) == 5
    assert snapshot.release_pin["releaseKind"] == "managedReferenceRelease"
    assert release_node["rkaf:membershipMode"] == "rkaf:completeMembership"
    assert release_node["rkaf:referenceReleaseDigest"] == snapshot.release_pin[
        "declaredReleaseDigest"
    ]
    assert release_node["atlas:operationalState"] == "developmentOnly"
    assert "atlas:candidateLookupAllowed" not in release_node
    assert "atlas:acceptedOutputAllowed" not in release_node


def test_reader_verifies_bundle_and_searches_labels_aliases_and_notes(
    tmp_path: Path,
) -> None:
    managed = _build_fixture()
    manifest_path = managed.write_to(tmp_path)

    view = IcpsrManagedReleaseView.open(manifest_path)

    ability = view.lookup("ability")
    talent = view.lookup("talent")
    note = view.lookup("United States Abolition")
    assert ability[0].official_label == "ability"
    assert ability[0].role == "preferredLabel"
    assert talent[0].official_label == "talent"
    assert talent[0].role == "alternateLabel"
    assert note[0].official_label == "Abolition movement"
    assert note[0].role == "scopeNote"
    assert view.concept(ability[0].concept_iri)["publisherCode"] == "24042"


def test_reader_deep_freezes_verified_records_after_open(
    tmp_path: Path,
) -> None:
    manifest_path = _build_fixture().write_to(tmp_path)
    view = IcpsrManagedReleaseView.open(manifest_path)

    assert isinstance(view.manifest["artifacts"], tuple)
    assert isinstance(view.coverage["gaps"], Mapping)
    assert isinstance(
        view.coverage["gaps"]["indexOnlyTerms"],
        tuple,
    )
    assert isinstance(view.concepts[0]["relations"], tuple)
    assert isinstance(view.concepts[0]["relations"][0], Mapping)
    assert isinstance(view.indexed_expressions, tuple)
    assert view.concepts[0]["officialLabel"] == "ability"
    assert view.indexed_expressions[0]["indexedText"]

    with pytest.raises(TypeError):
        view.manifest["artifacts"][0]["path"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        view.concepts[0]["relations"][0]["targetLabel"] = "Changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        view.indexed_expressions[0]["indexedText"] = "changed"  # type: ignore[index]

    assert view.lookup("ability")[0].official_label == "ability"
    assert view.concepts[0]["relations"][0]["targetLabel"] == "talent"


def test_reader_fails_closed_when_an_artifact_changes(
    tmp_path: Path,
) -> None:
    manifest_path = _build_fixture().write_to(tmp_path)
    expressions = tmp_path / "records" / "indexed-expressions.jsonl"
    expressions.write_bytes(expressions.read_bytes() + b" ")

    with pytest.raises(
        IcpsrManagedReleaseError,
        match="digest drifted|byte length drifted",
    ):
        IcpsrManagedReleaseView.open(manifest_path)


def test_expected_source_gap_counts_fail_closed() -> None:
    with pytest.raises(
        IcpsrManagedReleaseError,
        match="gap counts drifted",
    ):
        build_icpsr_managed_release(
            _fixture_sources(),
            recorded_at=RECORDED_AT,
            recorded_by=RECORDED_BY,
            require_complete_index=False,
            expected_gap_counts=(5, 45),
        )


def test_capture_loader_verifies_manifest_page_and_xml_bytes(
    tmp_path: Path,
) -> None:
    fixture = _fixture_sources()
    write_icpsr_subject_index_capture(
        fixture.index,
        tmp_path / "index",
    )
    xml_payload = fixture.source_artifacts["subject.xml"]
    (tmp_path / "subject.xml").write_bytes(xml_payload)
    expected_xml_digest = "sha256:" + hashlib.sha256(xml_payload).hexdigest()

    loaded = open_icpsr_managed_release_sources(
        tmp_path,
        expected_xml_sha256=expected_xml_digest,
        expected_xml_byte_length=len(xml_payload),
        require_complete_index=False,
    )
    assert len(loaded.index.terms) == 5

    page = tmp_path / "index" / "pages" / "a.html"
    page.write_bytes(page.read_bytes() + b" ")
    with pytest.raises(
        IcpsrManagedReleaseError,
        match="byte length drifted|digest drifted",
    ):
        open_icpsr_managed_release_sources(
            tmp_path,
            expected_xml_sha256=expected_xml_digest,
            expected_xml_byte_length=len(xml_payload),
            require_complete_index=False,
        )


def test_exact_2026_07_30_capture_preserves_verified_subset_and_gaps() -> None:
    if not REAL_CAPTURE.is_dir():
        pytest.skip("ignored exact ICPSR capture is unavailable")

    sources = open_icpsr_managed_release_sources(REAL_CAPTURE)
    managed = build_icpsr_managed_release(
        sources,
        recorded_at=RECORDED_AT,
        recorded_by=REAL_RECORDED_BY,
        expected_gap_counts=(5, 45),
    )

    assert managed.manifest["counts"] == {
        "concepts": 3_760,
        "indexedExpressions": len(managed.indexed_expressions),
        "xmlOnlyGaps": 5,
        "indexOnlyGaps": 45,
        "roleConflicts": 4,
        "unresolvedRelations": (managed.coverage["gaps"]["unresolvedRelationCount"]),
    }
    assert managed.coverage["sourceCounts"] == {
        "xmlTerms": 3_765,
        "publicIndexTerms": 3_805,
        "uriVerifiedJoins": 3_760,
    }
    assert managed.coverage["gaps"]["xmlOnlyLabels"] == [
        "Alaskan Natives",
        "Obama Administration (2009-  )",
        "runaway slaves",
        "special  elections",
        "treatment outcomes",
    ]
    assert managed.coverage["gaps"]["indexOnlyCount"] == 45
    assert managed.coverage["gaps"]["roleConflictCount"] == 4
    assert (
        managed.manifest["sources"]["indexCaptureDigest"]
        == "sha256:b155705626d53cce42a746ca582c4c8ca7e546db9b704a2223cad52fac45c6c6"
    )
    assert (
        managed.manifest["sources"]["xmlDigest"]
        == "sha256:1875e0331a8403c00fa47a3ededca98c902f55d0b84d70884543ed1d2db629ff"
    )
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    exact_manifest = REAL_CAPTURE / "managed-release" / "managed-release.json"
    assert evidence["managedRelease"]["manifestDigest"] == _file_digest(
        exact_manifest
    )
    assert evidence["managedRelease"]["canonicalPayloadDigest"] == (
        managed.manifest["canonicalPayloadDigest"]
    )
    assert evidence["managedRelease"]["coverageDigest"] == (managed.coverage["canonicalPayloadDigest"])
    assert evidence["counts"]["uriVerifiedConcepts"] == len(managed.concepts)
    assert evidence["counts"]["indexedExpressions"] == len(managed.indexed_expressions)


def test_exact_2026_07_30_capture_builds_a_complete_atlas_snapshot(
    tmp_path: Path,
) -> None:
    if not REAL_CAPTURE.is_dir():
        pytest.skip("ignored exact ICPSR capture is unavailable")

    sources = open_icpsr_managed_release_sources(REAL_CAPTURE)
    managed = build_icpsr_managed_release(
        sources,
        recorded_at=RECORDED_AT,
        recorded_by=REAL_RECORDED_BY,
        expected_gap_counts=(5, 45),
    )
    snapshot = _atlas_snapshot(managed, tmp_path)

    assert len(snapshot.member_ids) == 3_760
    assert _relation_count(snapshot) == 18_751


def test_written_manifest_is_canonical_json(tmp_path: Path) -> None:
    manifest_path = _build_fixture().write_to(tmp_path)

    parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert parsed["type"] == ("urn:ref:type:IcpsrManagedReleaseManifest")
    assert manifest_path.read_bytes().endswith(b"\n")
