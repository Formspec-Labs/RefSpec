"""CRS source-concept releases preserve identity and separate semantic rings."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from refspec.registry import crs_legislative_resources as crs
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseBundle,
    build_source_concept_release_bundle,
    source_scoped_concept_iri,
)
from refspec.registry.infrastructure.source_identity import (
    SourceRegistrationEvent,
    derive_uuid7,
)
from refspec.registry.packages.crs_source_concept_releases import (
    CRS_LEGISLATIVE_SUBJECT_SELECTION_POLICY,
    CRS_POLICY_AREA_SELECTION_POLICY,
    build_crs_source_concept_releases,
)
from refspec.registry.packages.crs_source_packages import (
    CRS_COMPLETE_CAPTURED_AT,
    CRSSourcePackages,
    build_crs_source_packages,
    build_crs_source_packages_from_capture_root,
)

PROJECT_ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
FULL_CAPTURE_ROOT = PROJECT_ROOT / "output" / "refspec-vocabulary-portfolio" / "crs" / "2026-07-30"

_FIXTURE_PAGES = (
    (
        crs.CRS_LEGISLATIVE_SUBJECTS_PAGE,
        "crs-legislative-subjects-mini.html",
        3,
    ),
    (
        crs.CRS_LEGISLATIVE_GEOGRAPHIC_PAGE,
        "crs-legislative-geographic-mini.html",
        2,
    ),
    (
        crs.CRS_LEGISLATIVE_ORGANIZATIONS_PAGE,
        "crs-legislative-organizations-mini.html",
        2,
    ),
    (
        crs.CRS_POLICY_AREAS_PAGE,
        "crs-policy-areas-mini.html",
        2,
    ),
)

_FORBIDDEN_PERMISSION_FIELDS = frozenset(
    {
        "acceptedOutputUseAuthorized",
        "admission",
        "candidateUseAuthorized",
        "eligibleUses",
        "emissionAuthorized",
        "usageCeiling",
    }
)


def _fixture_acquisitions(
    tmp_path: Path,
    *,
    retrieved_at: str = "2026-07-30T12:33:34Z",
) -> tuple[crs.AcquiredCRSPage, ...]:
    result: list[crs.AcquiredCRSPage] = []
    for original_source, fixture_name, count in _FIXTURE_PAGES:
        source = replace(original_source, expected_term_count=count)
        fixture = FIXTURES / fixture_name
        payload = fixture.read_bytes()
        pin = crs.CRSPageSnapshotPin(
            source=source,
            retrieved_at=retrieved_at,
            fetch_id=derive_uuid7(
                retrieved_at,
                seed=f"source-release-fixture:{source.term_category}".encode(),
            ),
            expected_sha256=crs.sha256_digest(payload),
            expected_byte_length=len(payload),
        )
        result.append(
            crs.acquire_crs_page(
                pin,
                tmp_path / "capture",
                source_path=fixture,
            )
        )
    return tuple(result)


def _registration_event(registered_at: str, seed: bytes) -> SourceRegistrationEvent:
    return SourceRegistrationEvent(
        registration_id=derive_uuid7(registered_at, seed=seed),
        registered_at=registered_at,
    )


def _packages(
    tmp_path: Path,
    *,
    captured_at: str = CRS_COMPLETE_CAPTURED_AT,
    registration_event: SourceRegistrationEvent | None = None,
    predecessor: CRSSourcePackages | None = None,
) -> CRSSourcePackages:
    kwargs: dict[str, Any] = {
        "captured_at": captured_at,
        "predecessor": predecessor,
    }
    if registration_event is not None:
        kwargs["registration_event"] = registration_event
    return build_crs_source_packages(
        _fixture_acquisitions(tmp_path, retrieved_at=captured_at),
        **kwargs,
    )


def _concepts_by_observation(
    release: SourceConceptReleaseBundle,
) -> dict[str, dict[str, Any]]:
    return {str(concept["sourceObservation"]): dict(concept) for concept in release.concepts}


def _all_mapping_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return set(value) | {key for child in value.values() for key in _all_mapping_keys(child)}
    if isinstance(value, (list, tuple)):
        return {key for child in value for key in _all_mapping_keys(child)}
    return set()


def _not_stated_rights(source: Any, selected_observation_ids: tuple[str, ...]) -> tuple[dict[str, str], ...]:
    selected = frozenset(selected_observation_ids)
    source_artifacts = {
        str(observation["sourceArtifact"]) for observation in source.observations if observation["id"] in selected
    }
    return tuple(
        {
            "type": "RightsMetadata",
            "rightsStatus": "notStated",
            "sourceArtifact": identifier,
            "sourceDigest": crs.sha256_digest(source.source_artifacts[identifier]),
        }
        for identifier in sorted(source_artifacts)
    )


def _assert_identity_preserved(
    release: SourceConceptReleaseBundle,
    *,
    categories: frozenset[str],
    semantic_ring: str,
) -> None:
    source = release.source_bundle
    source_scheme = str(source.resource_manifest["sourceScheme"]["id"])
    expected_rows = {
        str(observation["id"]): observation
        for observation in source.observations
        if observation["category"] in categories
    }
    concepts = _concepts_by_observation(release)
    assert concepts.keys() == expected_rows.keys()
    for observation_id, observation in expected_rows.items():
        concept = concepts[observation_id]
        assert concept["id"] == source_scoped_concept_iri(
            source_scheme,
            str(observation["localRecordId"]),
        )
        assert concept["identityKind"] == "refspecSourceScoped"
        assert concept["semanticRing"] == semantic_ring
        assert concept["sourceScheme"] == source_scheme


def test_builds_exact_reconciled_releases_with_separate_candidate_pools(
    tmp_path: Path,
) -> None:
    packages = _packages(tmp_path)
    releases = build_crs_source_concept_releases(packages)

    assert [release.release_manifest["semanticRing"] for release in releases.releases()] == [
        "subject",
        "entity",
        "subject",
    ]
    _assert_identity_preserved(
        releases.legislative_subjects,
        categories=frozenset({"subject"}),
        semantic_ring="subject",
    )
    _assert_identity_preserved(
        releases.legislative_entities,
        categories=frozenset({"geographicEntity", "organizationName"}),
        semantic_ring="entity",
    )
    _assert_identity_preserved(
        releases.policy_areas,
        categories=frozenset({"policyArea"}),
        semantic_ring="subject",
    )
    assert [len(release.concepts) for release in releases.releases()] == [3, 4, 2]
    assert releases.legislative_subjects.release_id != (releases.legislative_entities.release_id)

    legislative_reconciliation = packages.reconciliations[0].as_dict()
    policy_reconciliation = packages.reconciliations[1].as_dict()
    for release, expected in (
        (releases.legislative_subjects, legislative_reconciliation),
        (releases.legislative_entities, legislative_reconciliation),
        (releases.policy_areas, policy_reconciliation),
    ):
        assert release.release_manifest["sourceCapture"]["reconciliationDigest"].startswith("sha256:")
        assert json.loads(release.artifact_bytes()["reconciliation.json"].decode("utf-8")) == expected
        assert (
            not (
                _all_mapping_keys(release.release_manifest)
                | _all_mapping_keys(release.concepts)
                | _all_mapping_keys(release.lifecycle_records)
            )
            & _FORBIDDEN_PERMISSION_FIELDS
        )


def test_exact_publisher_captures_build_all_three_ring_scoped_releases() -> None:
    if not FULL_CAPTURE_ROOT.is_dir():
        pytest.skip("exact 2026-07-30 CRS captures are not present")

    packages = build_crs_source_packages_from_capture_root(FULL_CAPTURE_ROOT)
    releases = build_crs_source_concept_releases(packages)

    assert [len(release.concepts) for release in releases.releases()] == [
        565,
        478,
        32,
    ]
    assert {
        str(artifact["sha256"])
        for release in releases.releases()
        for artifact in release.source_bundle.resource_manifest["sourceArtifacts"]
    } >= {
        "sha256:8b4964a8cea53d63bce0a029bac38a2bc260059883120bc36e1759a4b5e844d1",
        "sha256:7dfefc6e8b17b3a86a9c9009453e792453eef01b099177ef29f4dc172d19d3d0",
        "sha256:fa870ff36352c3482a68aad4d9cff69bd8ff98294a7dd21b1e36f0a534b2b880",
        "sha256:16d806e4a07df391de776d0bd5fade9d0bce89fe33b564036c94e0749df91326",
    }
    subject_ids = tuple(
        str(observation["id"])
        for observation in packages.legislative_subject_terms.observations
        if observation["category"] == "subject"
    )
    direct_subject_release = build_source_concept_release_bundle(
        packages.legislative_subject_terms,
        semantic_ring="subject",
        selected_observation_ids=subject_ids,
        selection_policy=CRS_LEGISLATIVE_SUBJECT_SELECTION_POLICY,
        rights_metadata=_not_stated_rights(packages.legislative_subject_terms, subject_ids),
        reconciliation_record=packages.reconciliations[0].as_dict(),
    )
    assert direct_subject_release.release_id == releases.legislative_subjects.release_id
    policy_ids = tuple(
        str(observation["id"])
        for observation in packages.policy_areas.observations
        if observation["category"] == "policyArea"
    )
    direct_policy_release = build_source_concept_release_bundle(
        packages.policy_areas,
        semantic_ring="subject",
        selected_observation_ids=policy_ids,
        selection_policy=CRS_POLICY_AREA_SELECTION_POLICY,
        rights_metadata=_not_stated_rights(packages.policy_areas, policy_ids),
        reconciliation_record=packages.reconciliations[1].as_dict(),
    )
    assert direct_policy_release.release_id == releases.policy_areas.release_id


def test_refuses_a_source_package_with_pending_identity_review(tmp_path: Path) -> None:
    packages = _packages(tmp_path)
    pending = replace(
        packages.reconciliations[0],
        status="reviewRequired",
        requires_human_review=True,
    )
    packages = replace(
        packages,
        reconciliations=(pending, packages.reconciliations[1]),
    )

    with pytest.raises(crs.CRSIdentityError, match="human identity review"):
        build_crs_source_concept_releases(packages)


def test_refuses_a_stale_reconciliation_digest_binding(tmp_path: Path) -> None:
    packages = _packages(tmp_path)
    stale = replace(
        packages.reconciliations[0],
        current_local_record_content_set_digest="sha256:" + "0" * 64,
    )
    packages = replace(
        packages,
        reconciliations=(stale, packages.reconciliations[1]),
    )

    with pytest.raises(crs.CRSIdentityError, match="content digest drifted"):
        build_crs_source_concept_releases(packages)


def test_unchanged_refetch_preserves_every_source_scoped_concept_identity(
    tmp_path: Path,
) -> None:
    first_packages = _packages(tmp_path / "first")
    first = build_crs_source_concept_releases(first_packages)
    next_time = "2026-08-04T12:00:00Z"
    second_packages = _packages(
        tmp_path / "second",
        captured_at=next_time,
        registration_event=_registration_event(next_time, b"source-release-refetch"),
        predecessor=first_packages,
    )
    second = build_crs_source_concept_releases(second_packages)

    for previous, current in zip(first.releases(), second.releases(), strict=True):
        assert {concept["id"] for concept in current.concepts} == {concept["id"] for concept in previous.concepts}
        assert current.release_id != previous.release_id
        assert (
            current.release_manifest["sourceCapture"]["reconciliationDigest"]
            != previous.release_manifest["sourceCapture"]["reconciliationDigest"]
        )
