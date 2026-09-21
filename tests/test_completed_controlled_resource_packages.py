"""portfolio/completed-resource-packages-v2.json: closed package-class census, exact evidence, identity claims."""
from __future__ import annotations

import json
from pathlib import Path

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
INVENTORY = REFSPEC_ROOT / "portfolio" / "completed-resource-packages-v2.json"


def test_completed_package_inventory_is_closed_and_honest() -> None:
    """Pins 13 resources / 14 releases / 345,066 records and four package classes summing to the count."""

    inventory = json.loads(INVENTORY.read_bytes())
    resources = inventory["resources"]
    summary = inventory["summary"]

    assert inventory["schemaVersion"] == "2.0"
    # REF-069 adds `usc-act-index` as the first sealedRegistryArtifact: 12 -> 13
    # resources, 13 -> 14 releases, and 22,045 -> 345,066 records, the jump being
    # its 302,156 classification rows plus 20,865 popular-name rows.
    assert len(resources) == summary["resourceCount"] == 13
    assert len({resource["resourceId"] for resource in resources}) == 13
    assert sum(resource["releaseOrSnapshotCount"] for resource in resources) == summary["releaseOrSnapshotCount"] == 14
    assert (
        sum(resource["recordOrObservationCount"] for resource in resources)
        == summary["recordOrObservationCount"]
        == 345_066
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
    assert (
        sum(resource["packageClass"] == "sealedRegistryArtifact" for resource in resources)
        == summary["sealedRegistryArtifactCount"]
        == 1
    )
    # What makes the enumeration above CLOSED rather than merely long. Each class
    # was asserted on its own, so REF-069's fourth class entered the inventory
    # without any assertion noticing -- only the resource count did, which named
    # the symptom and not the cause. Summing them means a fifth class fails here
    # until someone states it, which is what "closed and honest" was claiming.
    assert (
        summary["managedConceptResourceCount"]
        + summary["sourceConceptReleaseCount"]
        + summary["sourceControlledResourceCount"]
        + summary["sealedRegistryArtifactCount"]
        == summary["resourceCount"]
    )
    assert all(resource["intendedUses"] for resource in resources)
    assert all({"candidateUseAuthorized", "acceptedOutputUseAuthorized"}.isdisjoint(resource) for resource in resources)


def test_completed_packages_have_exact_evidence_and_no_placeholder_digests() -> None:
    """Pins each resource to a sha256: digest of 64 hex chars and an evidence path that exists."""

    resources = json.loads(INVENTORY.read_bytes())["resources"]

    for resource in resources:
        digest = resource["packageDigest"]
        assert digest.startswith("sha256:")
        assert len(digest) == len("sha256:") + 64
        assert (REFSPEC_ROOT / resource["evidencePath"]).is_file()
        assert resource["identityStatus"]
        assert resource["intendedUses"]


def test_non_concept_packages_never_claim_concept_identity() -> None:
    """Pins the five source-controlled resources to capture-local or publisher-identifier identity statuses."""

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
    """Pins the three CRS source-concept releases to one evidence file and refspecSourceScopedConceptIdentity."""

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
