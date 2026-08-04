from __future__ import annotations

import json
from pathlib import Path

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
INVENTORY = REFSPEC_ROOT / "portfolio" / "completed-resource-packages-v2.json"


def test_completed_package_inventory_is_closed_and_honest() -> None:
    inventory = json.loads(INVENTORY.read_bytes())
    resources = inventory["resources"]
    summary = inventory["summary"]

    assert inventory["schemaVersion"] == "2.0"
    assert len(resources) == summary["resourceCount"] == 12
    assert len({resource["resourceId"] for resource in resources}) == 12
    assert sum(resource["releaseOrSnapshotCount"] for resource in resources) == summary["releaseOrSnapshotCount"] == 13
    assert (
        sum(resource["recordOrObservationCount"] for resource in resources)
        == summary["recordOrObservationCount"]
        == 22_045
    )
    assert (
        sum(resource["packageClass"] == "managedConceptRelease" for resource in resources)
        == summary["managedConceptResourceCount"]
        == 4
    )
    assert (
        sum(resource["packageClass"] == "sourceConceptRelease" for resource in resources)
        == summary["sourceConceptReleaseCount"]
        == 3
    )
    assert (
        sum(resource["packageClass"] == "sourceControlledResource" for resource in resources)
        == summary["sourceControlledResourceCount"]
        == 5
    )
    assert all(resource["intendedUses"] for resource in resources)
    assert all({"candidateUseAuthorized", "acceptedOutputUseAuthorized"}.isdisjoint(resource) for resource in resources)


def test_completed_packages_have_exact_evidence_and_no_placeholder_digests() -> None:
    resources = json.loads(INVENTORY.read_bytes())["resources"]

    for resource in resources:
        digest = resource["packageDigest"]
        assert digest.startswith("sha256:")
        assert len(digest) == len("sha256:") + 64
        assert (REFSPEC_ROOT / resource["evidencePath"]).is_file()
        assert resource["identityStatus"]
        assert resource["intendedUses"]


def test_non_concept_packages_never_claim_concept_identity() -> None:
    resources = json.loads(INVENTORY.read_bytes())["resources"]
    source_resources = [resource for resource in resources if resource["packageClass"] == "sourceControlledResource"]

    assert {resource["resourceId"] for resource in source_resources} == {
        "federal-register-api-topics",
        "crs-legislative-subject-terms",
        "crs-policy-areas",
        "lda-general-issue-codes",
        "lda-filing-types",
    }
    assert all(
        resource["identityStatus"]
        in {
            "captureLocalObservationsOnly",
            "publisherIdentifiersPreserved",
        }
        for resource in source_resources
    )


def test_source_concept_releases_are_distinct_crs_packages() -> None:
    resources = json.loads(INVENTORY.read_bytes())["resources"]
    source_concept_releases = [resource for resource in resources if resource["packageClass"] == "sourceConceptRelease"]

    assert {resource["resourceId"] for resource in source_concept_releases} == {
        "crs-legislative-subject-source-concepts",
        "crs-legislative-entity-source-concepts",
        "crs-policy-area-source-concepts",
    }
    assert {resource["evidencePath"] for resource in source_concept_releases} == {
        "research/evidence/crs-source-concept-releases-2026-08-04/release-evidence.json"
    }
    assert all(
        resource["identityStatus"] == "refspecSourceScopedConceptIdentity" for resource in source_concept_releases
    )
