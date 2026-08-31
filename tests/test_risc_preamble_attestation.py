"""Facts checked by reading pages 18-19 of the RISC Preamble as rendered pages.

`research/evidence/risc-preamble-attestation-2026-08-21/attestation.md` records
the reading. These tests pin what it established.
"""

from __future__ import annotations

from refspec.registry.unified_agenda_codes import (
    UA_LEGAL_AUTHORITY_CITATION_TYPE_DEFINITIONS as DEFINITIONS,
)
from refspec.registry.unified_agenda_codes import (
    UA_LEGAL_AUTHORITY_CITATION_TYPES as CITATION_TYPES,
)

# Transcribed from the rendered pages, not from the producer.
AS_READ = {
    "U.S.C.": (
        "The United States Code is a consolidation and codification of all general "
        "and permanent laws of the United States. The USC is divided into 50 titles, "
        "each title covering a broad area of Federal law."
    ),
    "Pub. L.": (
        "A public law is a law passed by Congress and signed by the President or "
        "enacted over his veto. It has general applicability, unlike a private law "
        "that applies only to those persons or entities specifically designated. "
        "Public laws are numbered in sequence throughout the 2-year life of each "
        "Congress; for example, Public Law 112-4 is the fourth public law of the "
        "112th Congress."
    ),
    "E.O.": (
        "An Executive order is a directive from the President to Executive agencies, "
        "issued under constitutional or statutory authority. Executive orders are "
        "published in the Federal Register and in title 3 of the Code of Federal "
        "Regulations."
    ),
}

# The CFR entry sits four above E.O. in the same glossary.
CFR_AS_READ = (
    "The Code of Federal Regulations is an annual codification of the general and "
    "permanent regulations published in the Federal Register by the agencies of the "
    "Federal Government. The Code is divided into 50 titles, each title covering a "
    "broad area subject to Federal regulation."
)


def test_the_three_definitions_are_the_publishers_words() -> None:
    assert set(CITATION_TYPES) == set(AS_READ)
    for citation_type, text in AS_READ.items():
        assert DEFINITIONS[citation_type] == text


def test_the_cfr_entry_was_not_transcribed_into_the_usc_record() -> None:
    """The failure that would not look like a failure.

    Both entries say "divided into 50 titles, each title covering a broad area";
    they diverge only in the last three words. Swapping them would read
    plausibly and no consumer could detect it.
    """

    shared = "divided into 50 titles, each title covering a broad area"
    assert shared in CFR_AS_READ and shared in AS_READ["U.S.C."]
    assert DEFINITIONS["U.S.C."].endswith("of Federal law.")
    assert "subject to Federal regulation" not in DEFINITIONS["U.S.C."]
    assert "CFR" not in DEFINITIONS


def test_the_release_claims_only_a_subset_of_the_glossary() -> None:
    """Section V defines twelve terms; three are carried, and the scope says so."""

    assert len(CITATION_TYPES) == 3
    for not_a_citation_type in ("ANPRM", "NPRM", "FR", "FY", "RIN", "RFA", "Seq. No.", "CFR"):
        assert not_a_citation_type not in DEFINITIONS
