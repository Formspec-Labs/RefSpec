from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
verifier = importlib.import_module("verify_federal_register_thesaurus_distribution")

REAL_SOURCE_ROOT = ROOT / "output" / "registry-real-data-sources"


@pytest.fixture(scope="module")
def source_root() -> Path:
    path = REAL_SOURCE_ROOT / verifier.SOURCE_FILENAME
    if not path.is_file():
        pytest.skip(
            "pinned thesaurus source is not present: "
            "output/registry-real-data-sources/federal-register-thesaurus-2025.pdf"
        )
    return REAL_SOURCE_ROOT


def test_pinned_source_refuses_absent_wrong_and_truncated_bytes(tmp_path: Path) -> None:
    with pytest.raises(verifier.BoundedReleaseVerificationError, match="is absent"):
        verifier.verify_pinned_source(tmp_path)

    forged = tmp_path / verifier.SOURCE_FILENAME
    forged.write_bytes(b"%PDF-1.7\n" * 8)
    with pytest.raises(verifier.BoundedReleaseVerificationError, match="digest differs"):
        verifier.verify_pinned_source(tmp_path)


def test_source_ledger_accounts_for_every_related_reference_occurrence(
    source_root: Path,
) -> None:
    """The occurrence ledger is the count a distribution cannot state itself."""

    ledger = verifier.source_occurrence_ledger(source_root)
    statuses = ledger["relatedReferenceStatuses"]

    assert ledger["officialTerms"] == 705
    assert ledger["relatedReferenceOccurrences"] == 1_463
    assert sum(statuses.values()) == 1_463
    assert statuses["resolved"] == 1_451
    assert ledger["unrepresentedOccurrences"] == 12


def test_verification_fails_on_the_right_count_of_wrong_rows(
    source_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counting alone would pass this; comparing identities is what refuses it."""

    release = verifier.load_federal_register_2025_release(source_root)
    resources = {resource.iri for resource in release.resources}
    labels = {
        (resource.iri, label.role, label.value)
        for resource in release.resources
        for label in resource.labels
    }
    statements = {
        (relation.subject, relation.predicate, relation.object)
        for relation in release.relations
    }
    substituted = min(statements)
    swapped = (substituted[0], substituted[1], "urn:ref:source-concept:v2:invented")

    def measured(_distribution: Path, _digest: str) -> dict[str, object]:
        return {
            "distributionId": "urn:ref:atlas:distribution:test:0",
            "labelRoleCounts": {"alternate": 433, "preferred": 705},
            "labels": labels,
            "manifestSha256": "sha256:" + "0" * 64,
            "releases": {verifier.ATLAS_RELEASE_IRI},
            "resources": resources,
            "sourceRecords": resources,
            "statements": (statements - {substituted}) | {swapped},
        }

    monkeypatch.setattr(verifier, "_measure_distribution", measured)
    receipt = verifier.verify_distribution(
        Path("unused"),
        expected_manifest_digest="sha256:" + "0" * 64,
        source_root=source_root,
    )

    assert receipt["measuredCounts"]["relationRows"] == 1_451
    assert receipt["status"] == "failed"
    assert receipt["failures"] == [
        (
            "relation rows differ: 1 absent from the distribution, "
            "1 unexpected in the distribution"
        )
    ]
