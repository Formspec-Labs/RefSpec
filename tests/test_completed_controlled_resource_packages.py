from __future__ import annotations

import json
from pathlib import Path

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
INVENTORY = REFSPEC_ROOT / "portfolio" / "completed-controlled-resource-packages-v1.json"


def test_completed_package_inventory_is_closed_and_honest() -> None:
    inventory = json.loads(INVENTORY.read_bytes())
    resources = inventory["resources"]
    summary = inventory["summary"]

    assert inventory["schemaVersion"] == "1.0"
    assert len(resources) == summary["resourceCount"] == 8
    assert len({resource["resourceId"] for resource in resources}) == 8
    assert sum(resource["releaseOrSnapshotCount"] for resource in resources) == summary["releaseOrSnapshotCount"] == 9
    assert (
        sum(resource["recordOrObservationCount"] for resource in resources)
        == summary["recordOrObservationCount"]
        == 20_265
    )
    assert (
        sum(resource["packageClass"] == "managedConceptRelease" for resource in resources)
        == summary["managedConceptResourceCount"]
        == 3
    )
    assert (
        sum(resource["packageClass"] == "sourceControlledResource" for resource in resources)
        == summary["sourceControlledResourceCount"]
        == 5
    )
    assert (
        sum(resource["candidateUseAuthorized"] for resource in resources)
        == summary["candidateLookupResourceCount"]
        == 6
    )
    assert not any(resource["acceptedOutputUseAuthorized"] for resource in resources)
    assert summary["acceptedOutputResourceCount"] == 0


def test_completed_packages_have_exact_evidence_and_no_placeholder_digests() -> None:
    resources = json.loads(INVENTORY.read_bytes())["resources"]

    for resource in resources:
        digest = resource["packageDigest"]
        assert digest.startswith("sha256:")
        assert len(digest) == len("sha256:") + 64
        assert (REFSPEC_ROOT / resource["evidencePath"]).is_file()
        assert resource["identityStatus"]
        assert resource["productUse"]


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
