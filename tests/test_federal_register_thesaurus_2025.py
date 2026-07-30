from __future__ import annotations

import os
from pathlib import Path

import pytest

from refspec.registry.federal_register_thesaurus_2025 import (
    FEDERAL_REGISTER_THESAURUS_2025_SHA256,
    load_packaged_federal_register_thesaurus_2025,
    parse_federal_register_thesaurus_2025_pdf,
)
from refspec.registry.federal_register_thesaurus_2025_managed_release import (
    FederalRegisterThesaurus2025ManagedReleaseView,
)
from refspec.registry.federal_register_vocabulary_policy import (
    load_federal_register_thesaurus_crosswalk,
    resolve_list_of_subjects_term,
)

RESOURCE_ROOT = (
    Path(__file__).parents[1]
    / "src"
    / "refspec"
    / "resources"
    / "federal_register_thesaurus"
    / "2025-04-01"
)


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


def test_crosswalk_covers_every_historical_and_current_term() -> None:
    crosswalk = load_federal_register_thesaurus_crosswalk(
        (
            RESOURCE_ROOT / "crosswalk-1995-to-2025.json"
        ).read_bytes()
    )

    assert crosswalk["counts"] == {
        "historicalRows": 629,
        "currentOfficialTerms": 705,
        "unchanged": 587,
        "renamed": 18,
        "redirected": 3,
        "ambiguous": 7,
        "removed": 14,
        "added": 111,
    }
    examples = {
        row["historicalPreferredLabel"]: row["category"]
        for row in crosswalk["historicalTerms"]
    }
    assert examples["Accountants"] == "unchanged"
    assert examples["Blood diseases"] == "renamed"
    assert examples["Conflict of interests"] == "redirected"
    assert examples["Bakery products"] == "ambiguous"
    assert examples["Acid rain"] == "removed"
    assert (
        crosswalk["authority"]["candidateSelectionAuthorized"] is False
    )
    assert (
        crosswalk["authority"]["conceptIdentityAssertions"] is False
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


def test_written_managed_release_verifies_when_available() -> None:
    manifest_path = os.environ.get("REFSPEC_FR_THESAURUS_2025_MANIFEST")
    if not manifest_path:
        pytest.skip(
            "set REFSPEC_FR_THESAURUS_2025_MANIFEST for the package gate"
        )
    view = FederalRegisterThesaurus2025ManagedReleaseView.open(
        Path(manifest_path)
    )
    assert len(view.concepts) == 705
    assert (
        view.manifest["candidatePolicy"]["defaultForProfiles"]
        == ["federal-register-document-v1"]
    )
    assert view.manifest["candidatePolicy"]["rootOntology"] is False
    assert all(
        row["predicateIri"]
        != "http://www.w3.org/2004/02/skos/core#broader"
        for row in view.relations
    )
