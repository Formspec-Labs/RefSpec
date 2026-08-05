from __future__ import annotations

import hashlib
import os
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import refspec.registry.managed_releases.federal_register_thesaurus_2025_managed_release as managed_release_module
from refspec.atlas.atlas_scope import AtlasScopeRelease
from refspec.atlas.concept_release import (
    ManagedReleaseRingAssignment,
    PinnedManagedReleaseRingAssignment,
)
from refspec.atlas.federal_register import (
    FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI,
    PinnedFederalRegisterManagedConceptRelease,
)
from refspec.atlas.release_snapshot import AtlasReleaseSnapshot
from refspec.policies.federal_register_lists_of_subjects import (
    resolve_list_of_subjects_term,
)
from refspec.registry.federal_register_thesaurus_2025 import (
    FEDERAL_REGISTER_THESAURUS_2025_SHA256,
    load_packaged_federal_register_thesaurus_2025,
    parse_federal_register_thesaurus_2025_pdf,
)
from refspec.registry.managed_releases.federal_register_thesaurus_2025_managed_release import (
    FederalRegisterThesaurus2025ManagedReleaseView,
    build_federal_register_thesaurus_2025_managed_release,
)


def _write_managed_release_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    source_pdf = b"%PDF-1.7\nverified-view-fixture\n"
    real_sha256_bytes = managed_release_module._sha256_bytes

    def fixture_sha256_bytes(payload: bytes) -> str:
        if payload == source_pdf:
            return FEDERAL_REGISTER_THESAURUS_2025_SHA256
        return real_sha256_bytes(payload)

    monkeypatch.setattr(
        managed_release_module,
        "_sha256_bytes",
        fixture_sha256_bytes,
    )
    coverage = managed_release_module._seal(
        {
            "id": "urn:test:fr-thesaurus-2025:coverage",
            "unresolvedReferences": [
                {
                    "rawLiteral": "Fixture unresolved term",
                    "sourceLocator": {"page": 1},
                }
            ],
        }
    )
    concepts = (
        {
            "conceptId": "frt25-fixture",
            "conceptIri": "https://example.test/fr-thesaurus/fixture",
            "preferredLabel": "Fixture",
            "alternateLabels": ["Fixture term"],
            "sourceLocator": {"page": 1, "lines": [2, 3]},
        },
    )
    variants = (
        {
            "variantId": "frt25-fixture-variant",
            "label": "Fixture term",
            "targetConceptIds": ["frt25-fixture"],
        },
    )
    relations = (
        {
            "sourceConceptId": "frt25-fixture",
            "predicateIri": "http://www.w3.org/2004/02/skos/core#related",
            "targetConceptIds": ["frt25-fixture"],
        },
    )
    open_patterns = (
        {
            "patternId": "frt25-open-fixture",
            "sourceEntryId": "fixture",
            "rawLiteral": "Fixture-specific subject",
            "sourceLocator": {"page": 1, "lines": [4]},
            "conceptMinted": False,
        },
    )
    lists_policy = {
        "classifications": {
            "officialTerm": "exact official-term match",
            "unresolved": "requires review",
        },
        "sourceLocalOpenTermRequires": [
            "explicit caller authorization",
            "sourceRecordId",
            "sourcePath",
        ],
        "conceptMintingAllowed": False,
    }
    partial = managed_release_module.FederalRegisterThesaurus2025ManagedRelease(
        manifest={},
        coverage=coverage,
        concepts=concepts,
        variants=variants,
        relations=relations,
        suggested_open_term_patterns=open_patterns,
        lists_of_subjects_policy=lists_policy,
        source_pdf=source_pdf,
        source_extract=b'{"fixture":true}\n',
    )
    artifacts = partial.content_artifacts()
    manifest = managed_release_module._seal(
        {
            "id": "urn:test:fr-thesaurus-2025:managed-release",
            "counts": {
                "concepts": len(concepts),
                "variants": len(variants),
                "relations": len(relations),
                "suggestedOpenTermPatterns": len(open_patterns),
            },
            "candidatePolicy": {
                "defaultForProfiles": [
                    "federal-register-document-v1",
                ],
                "rootOntology": False,
            },
            "artifacts": [
                managed_release_module._descriptor(relative, payload)
                for relative, payload in sorted(artifacts.items())
            ],
        }
    )
    release = managed_release_module.FederalRegisterThesaurus2025ManagedRelease(
        manifest=manifest,
        coverage=coverage,
        concepts=concepts,
        variants=variants,
        relations=relations,
        suggested_open_term_patterns=open_patterns,
        lists_of_subjects_policy=lists_policy,
        source_pdf=source_pdf,
        source_extract=b'{"fixture":true}\n',
    )
    return release.write_to(tmp_path)["managed-release.json"]


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_complete_managed_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    source_pdf = b"%PDF-1.7\ncomplete-705-concept-atlas-fixture\n"
    actual_sha256 = managed_release_module._sha256_bytes

    def fixture_sha256(payload: bytes) -> str:
        if payload == source_pdf:
            return FEDERAL_REGISTER_THESAURUS_2025_SHA256
        return actual_sha256(payload)

    monkeypatch.setattr(managed_release_module, "_sha256_bytes", fixture_sha256)
    checked = load_packaged_federal_register_thesaurus_2025()
    parsed = replace(checked, source_artifact_bytes=source_pdf)
    release = build_federal_register_thesaurus_2025_managed_release(
        parsed,
        recorded_at="2026-07-31T00:00:00Z",
        recorded_by="urn:test:actor:federal-register-atlas-release",
    )
    return release.write_to(tmp_path / "complete-managed-release")[
        "managed-release.json"
    ]


def _atlas_snapshot(manifest_path: Path, root: Path) -> AtlasReleaseSnapshot:
    manifest_digest = _file_digest(manifest_path)
    assignment = ManagedReleaseRingAssignment(
        managed_manifest_digest=manifest_digest,
        release_id=FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI,
        semantic_ring="subject",
        assigned_by="urn:test:actor:federal-register-atlas-reviewer",
        assigned_at="2026-08-04T20:00:00Z",
        evidence=("urn:test:evidence:federal-register-complete-release",),
    )
    assignment_path = assignment.write_to(root / "managed-release-ring-assignment.json")
    pinned_assignment = PinnedManagedReleaseRingAssignment.open(
        assignment_path,
        expected_file_digest=_file_digest(assignment_path),
    )
    selected = PinnedFederalRegisterManagedConceptRelease.open(
        manifest_path,
        expected_manifest_digest=manifest_digest,
        release_id=FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI,
        ring_assignment=pinned_assignment,
    )
    return AtlasReleaseSnapshot.create(AtlasScopeRelease(selected))


def test_packaged_extract_pins_complete_current_source_interpretation() -> None:
    thesaurus = load_packaged_federal_register_thesaurus_2025()

    assert thesaurus.source_sha256 == FEDERAL_REGISTER_THESAURUS_2025_SHA256
    assert thesaurus.counts.official_terms == 705
    assert thesaurus.counts.variant_occurrences == 526
    assert thesaurus.counts.recognized_variant_occurrences == 433
    assert thesaurus.counts.ambiguous_variant_occurrences == 90
    assert thesaurus.counts.unresolved_variant_occurrences == 3
    assert thesaurus.counts.related_references == 1_463
    assert thesaurus.counts.suggested_open_term_patterns == 14
    assert thesaurus.counts.unresolved_references == 2
    assert thesaurus.counts.index_anomalies == 2


def test_complete_2025_release_builds_an_atlas_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _write_complete_managed_release(tmp_path, monkeypatch)
    snapshot = _atlas_snapshot(manifest_path, tmp_path)
    release_node = next(
        record
        for record in snapshot.record["selectedReleaseGraph"]["@graph"]
        if record["@id"] == snapshot.release_id
    )
    related = sum(
        len(cast(tuple[object, ...], concept["http://www.w3.org/2004/02/skos/core#related"]))
        for concept in snapshot.concept_records
        if "http://www.w3.org/2004/02/skos/core#related" in concept
    )
    relation_statuses = Counter(
        row["resolutionStatus"]
        for row in FederalRegisterThesaurus2025ManagedReleaseView.open(
            manifest_path
        ).relations
    )

    assert snapshot.release_id == FEDERAL_REGISTER_THESAURUS_2025_REFERENCE_RELEASE_IRI
    assert len(snapshot.member_ids) == 705
    assert relation_statuses == {
        "resolved": 1_451,
        "suggestedOpenTermPattern": 11,
        "unresolved": 1,
    }
    assert sum(relation_statuses.values()) == 1_463
    assert related == relation_statuses["resolved"]
    assert release_node["rkaf:membershipMode"] == "rkaf:completeMembership"
    assert release_node["rkaf:referenceReleaseDigest"] == snapshot.release_pin[
        "declaredReleaseDigest"
    ]


def test_lists_of_subjects_resolution_never_silently_mints() -> None:
    thesaurus = load_packaged_federal_register_thesaurus_2025()

    official = resolve_list_of_subjects_term(
        "Air pollution control",
        thesaurus,
    )
    recognized = resolve_list_of_subjects_term("Accidents", thesaurus)
    ambiguous = resolve_list_of_subjects_term("Discrimination", thesaurus)
    unresolved = resolve_list_of_subjects_term(
        "Project-specific novel subject",
        thesaurus,
    )
    source_local = resolve_list_of_subjects_term(
        "Project-specific novel subject",
        thesaurus,
        source_record_id="FR-2026-00001",
        source_path="listsOfSubjects[0]",
        allow_source_local_open_term=True,
    )

    assert official.classification == "officialTerm"
    assert recognized.classification == "recognizedVariant"
    assert len(recognized.concept_iris) == 1
    assert ambiguous.classification == "unresolved"
    assert len(ambiguous.concept_iris) > 1
    assert unresolved.classification == "unresolved"
    assert source_local.classification == "sourceLocalOpenTerm"
    assert source_local.source_record_id == "FR-2026-00001"
    assert source_local.source_path == "listsOfSubjects[0]"
    assert not any(
        resolution.concept_minted
        for resolution in (
            official,
            recognized,
            ambiguous,
            unresolved,
            source_local,
        )
    )


def test_exact_pdf_regenerates_checked_extract_when_available() -> None:
    source_path = os.environ.get("REFSPEC_FR_THESAURUS_2025_PATH")
    if not source_path:
        pytest.skip("set REFSPEC_FR_THESAURUS_2025_PATH for the exact PDF gate")
    parsed = parse_federal_register_thesaurus_2025_pdf(
        Path(source_path).read_bytes()
    )
    checked = load_packaged_federal_register_thesaurus_2025()
    assert parsed.counts == checked.counts
    assert parsed.official_terms == checked.official_terms
    assert parsed.variants == checked.variants


def test_managed_release_view_deep_freezes_verified_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _write_managed_release_fixture(
        tmp_path,
        monkeypatch,
    )
    view = FederalRegisterThesaurus2025ManagedReleaseView.open(
        manifest_path
    )

    assert (
        view.manifest["candidatePolicy"]["defaultForProfiles"]
        == ("federal-register-document-v1",)
    )
    assert isinstance(view.concepts[0]["alternateLabels"], tuple)
    assert isinstance(view.concepts[0]["sourceLocator"]["lines"], tuple)
    assert isinstance(
        view.lists_of_subjects_policy["sourceLocalOpenTermRequires"],
        tuple,
    )
    assert view.concepts[0]["preferredLabel"] == "Fixture"

    with pytest.raises(TypeError):
        view.manifest["candidatePolicy"]["rootOntology"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        view.concepts[0]["sourceLocator"]["page"] = 2  # type: ignore[index]
    assert view.manifest["candidatePolicy"]["rootOntology"] is False
    assert view.concepts[0]["sourceLocator"]["page"] == 1


def test_exact_pdf_builds_and_verifies_written_managed_release(
    tmp_path: Path,
) -> None:
    source_path = os.environ.get("REFSPEC_FR_THESAURUS_2025_PATH")
    if not source_path:
        pytest.skip(
            "set REFSPEC_FR_THESAURUS_2025_PATH for the package gate"
        )
    thesaurus = parse_federal_register_thesaurus_2025_pdf(
        Path(source_path).read_bytes()
    )
    release = build_federal_register_thesaurus_2025_managed_release(
        thesaurus,
        recorded_at="2026-08-03T00:00:00Z",
        recorded_by="urn:ref:actor:registry-real-data-audit",
    )
    release.write_to(tmp_path)
    manifest_path = tmp_path / "managed-release.json"
    view = FederalRegisterThesaurus2025ManagedReleaseView.open(
        manifest_path
    )
    assert len(view.concepts) == 705
    assert (
        view.manifest["candidatePolicy"]["defaultForProfiles"]
        == ("federal-register-document-v1",)
    )
    assert view.manifest["candidatePolicy"]["rootOntology"] is False
    assert all(
        row["predicateIri"]
        != "http://www.w3.org/2004/02/skos/core#broader"
        for row in view.relations
    )
