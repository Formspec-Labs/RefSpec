"""Tests for the U.S. Courts JS-044 Nature of Suit code importer.

No test opens a network connection. ``SYNTHETIC_SOURCE`` is a small,
hand-verified example of the ``pdftotext -layout`` convention this module
depends on; it exercises every structural feature the real document uses:
a per-page "(Rev. MM/YY)" line, a single-line category heading, a two-line
compound heading, a title that wraps onto its own column, a title and
description that both wrap on the very same physical line, a description
that a page break interrupts mid-sentence, and a trailing document note.

``tests/fixtures/nature_of_suit_codes/js_044_code_descriptions.layout.txt``
is a real captured sample: the output of

    pdftotext -layout js_044_code_descriptions.pdf js_044_code_descriptions.layout.txt

(Poppler 26.06.0) run against the official PDF fetched from
``NATURE_OF_SUIT_CODE_DESCRIPTIONS_URL`` on 2026-08-03. The original PDF's
own sha256 at that date was
``aeaff2476c8cc926191466ff571e91b0f0896858f4f00deed1117c1aa33daa95``; that
PDF is not itself committed here; PDF-to-text extraction is a separate,
independently pinned step per the module docstring, and this fixture is that
step's pinned output. ``HISTORICAL_SHA256``/``HISTORICAL_COUNTS`` below pin
that extracted text's own digest and shape, so a byte-for-byte drift in a
future re-capture fails the regression test below rather than parsing
silently.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from refspec.registry.nature_of_suit_codes import (
    NATURE_OF_SUIT_CODE_DESCRIPTIONS_URL,
    NATURE_OF_SUIT_CODE_IDENTIFIER_KIND,
    NATURE_OF_SUIT_CODES_RESOURCE_ID,
    ImportCounts,
    NatureOfSuitParseError,
    build_nature_of_suit_code_package,
    parse_nature_of_suit_code_descriptions,
)
from refspec.registry.source_controlled_resource import SourceControlledResourceView

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "nature_of_suit_codes"
REAL_FIXTURE_PATH = FIXTURE_DIR / "js_044_code_descriptions.layout.txt"

HISTORICAL_SHA256 = "sha256:dcb5ac0d1da85ad597d1e7ae07e91b6b8193e6eb19ae6403a050607eebfde1f2"
HISTORICAL_COUNTS = ImportCounts(
    source_lines=377,
    source_bytes=32211,
    pages=8,
    sections=16,
    entries=93,
    document_notes=1,
)


def _row(code: str, title_first: str, desc_first: str, title_col: int, desc_col: int) -> str:
    left = f"  {code}".ljust(title_col)
    mid = title_first.ljust(desc_col - title_col)
    return left + mid + desc_first


def _cont(text: str, col: int) -> str:
    return " " * col + text


def _header(title_col: int, desc_col: int) -> str:
    left = "  Code".ljust(title_col)
    mid = "Title".ljust(desc_col - title_col)
    return left + mid + "Description"


_TITLE_COL_1 = 12
_DESC_COL_1 = 57
_TITLE_COL_2 = 12
_DESC_COL_2 = 53

SYNTHETIC_SOURCE = "\n".join(
    [
        "Civil Nature of Suit Code Descriptions",
        "(Rev. 03/24)",
        "",
        " Contract",
        _header(_TITLE_COL_1, _DESC_COL_1),
        _row("110", "Insurance", "Action alleging breach of insurance", _TITLE_COL_1, _DESC_COL_1),
        _cont("contract, tort claim, or other cause.", _DESC_COL_1),
        _row(
            "150",
            "Recovery of Overpayment & Enforcement",
            "Action to recover debt owed to the",
            _TITLE_COL_1,
            _DESC_COL_1,
        ),
        # A title continuation ("Judgment") and a description continuation
        # ("United States, including enforcement.") on the very same line.
        " " * _TITLE_COL_1 + "Judgment".ljust(_DESC_COL_1 - _TITLE_COL_1) + "United States, including enforcement.",
        "",
        "",
        " " * 70 + "Page 1 of 2",
        "Civil Nature of Suit Code Descriptions",
        "(Rev. 03/24)",
        # Page-crossing continuation of 150's description; no blank line
        # separates it from the revision line above.
        _cont("Excludes overpayments arising from Medicare benefits.", 53),
        "",
        "",
        " Prisoner Petitions",
        " Habeas Corpus",
        _header(_TITLE_COL_2, _DESC_COL_2),
        _row(
            "463",
            "Alien Detainee",
            "Immigration habeas petition under 28",
            _TITLE_COL_2,
            _DESC_COL_2,
        ),
        _cont("U.S.C. Section 2241.", _DESC_COL_2),
        "",
        "Note: The categories above are illustrative, not exhaustive.",
        "     See the published table for the complete list.",
        "",
        "",
        " " * 70 + "Page 2 of 2",
    ]
) + "\n"


def test_parser_preserves_pages_sections_entries_and_document_note() -> None:
    parsed = parse_nature_of_suit_code_descriptions(SYNTHETIC_SOURCE)

    assert parsed.counts == ImportCounts(
        source_lines=len(SYNTHETIC_SOURCE.splitlines()),
        source_bytes=len(SYNTHETIC_SOURCE.encode("utf-8")),
        pages=2,
        sections=2,
        entries=3,
        document_notes=1,
    )
    assert parsed.source_sha256 == "sha256:" + hashlib.sha256(SYNTHETIC_SOURCE.encode("utf-8")).hexdigest()

    assert [page.revision_label for page in parsed.pages] == ["(Rev. 03/24)", "(Rev. 03/24)"]
    assert [page.page_number for page in parsed.pages] == [1, 2]

    contract, prisoner = parsed.sections
    assert contract.heading_lines == ("Contract",)
    assert prisoner.heading_lines == ("Prisoner Petitions", "Habeas Corpus")
    assert contract.page_id == parsed.pages[0].page_id
    assert prisoner.page_id == parsed.pages[1].page_id

    insurance = parsed.entry_by_code("110")
    assert insurance.title_lines == ("Insurance",)
    assert insurance.title == "Insurance"
    assert insurance.description == "Action alleging breach of insurance contract, tort claim, or other cause."
    assert insurance.section_id == contract.section_id

    recovery = parsed.entry_by_code("150")
    assert recovery.title_lines == ("Recovery of Overpayment & Enforcement", "Judgment")
    assert recovery.title == "Recovery of Overpayment & Enforcement Judgment"
    # The description spans the page break: two lines from page 1 plus one
    # line that appears directly after page 2's revision line.
    assert recovery.description_lines == (
        "Action to recover debt owed to the",
        "United States, including enforcement.",
        "Excludes overpayments arising from Medicare benefits.",
    )

    alien_detainee = parsed.entry_by_code("463")
    assert alien_detainee.title == "Alien Detainee"
    assert alien_detainee.description == "Immigration habeas petition under 28 U.S.C. Section 2241."
    assert alien_detainee.section_id == prisoner.section_id

    (note,) = parsed.document_notes
    assert note.text == (
        "Note: The categories above are illustrative, not exhaustive. "
        "See the published table for the complete list."
    )


def test_entry_by_code_raises_key_error_for_an_unknown_code() -> None:
    parsed = parse_nature_of_suit_code_descriptions(SYNTHETIC_SOURCE)
    with pytest.raises(KeyError):
        parsed.entry_by_code("999")


def test_two_line_heading_is_preserved_without_asserting_a_hierarchy() -> None:
    parsed = parse_nature_of_suit_code_descriptions(SYNTHETIC_SOURCE)
    prisoner = parsed.sections[1]
    # Both physical lines are kept verbatim, in order; nothing here promotes
    # the first line to a "parent" or the second to a "child" facet.
    assert prisoner.heading_lines == ("Prisoner Petitions", "Habeas Corpus")


def test_missing_revision_line_after_page_title_fails_closed() -> None:
    source = "Civil Nature of Suit Code Descriptions\nnot a revision line\n"
    with pytest.raises(NatureOfSuitParseError, match="Rev. MM/YY"):
        parse_nature_of_suit_code_descriptions(source)


def test_code_row_before_column_header_fails_closed() -> None:
    source = "\n".join(
        [
            "Civil Nature of Suit Code Descriptions",
            "(Rev. 03/24)",
            "",
            " Contract",
            _row("110", "Insurance", "Action alleging breach.", _TITLE_COL_1, _DESC_COL_1),
        ]
    )
    with pytest.raises(NatureOfSuitParseError, match="before its section's column header"):
        parse_nature_of_suit_code_descriptions(source)


def test_column_header_without_open_section_fails_closed() -> None:
    source = "\n".join(
        [
            "Civil Nature of Suit Code Descriptions",
            "(Rev. 03/24)",
            "",
            _header(_TITLE_COL_1, _DESC_COL_1),
        ]
    )
    with pytest.raises(NatureOfSuitParseError, match="no open category section"):
        parse_nature_of_suit_code_descriptions(source)


def test_duplicate_code_fails_closed() -> None:
    source = "\n".join(
        [
            "Civil Nature of Suit Code Descriptions",
            "(Rev. 03/24)",
            "",
            " Contract",
            _header(_TITLE_COL_1, _DESC_COL_1),
            _row("110", "Insurance", "First occurrence.", _TITLE_COL_1, _DESC_COL_1),
            _row("110", "Insurance Again", "Second occurrence.", _TITLE_COL_1, _DESC_COL_1),
        ]
    )
    with pytest.raises(NatureOfSuitParseError, match="repeats at line"):
        parse_nature_of_suit_code_descriptions(source)


def test_unattributable_continuation_line_fails_closed() -> None:
    # A large-indent line appears right after a page's revision line, but no
    # entry from a previous page is open to continue -- this must refuse
    # rather than silently invent a heading or an entry.
    source = "\n".join(
        [
            "Civil Nature of Suit Code Descriptions",
            "(Rev. 03/24)",
            _cont("stray wrapped text with nothing open above it", 20),
        ]
    )
    with pytest.raises(NatureOfSuitParseError, match="no entry is open"):
        parse_nature_of_suit_code_descriptions(source)


def test_entry_without_a_title_fails_closed() -> None:
    # A code row whose title slice is entirely blank signals a column-offset
    # mismatch, not a legitimately titleless entry.
    source = "\n".join(
        [
            "Civil Nature of Suit Code Descriptions",
            "(Rev. 03/24)",
            "",
            " Contract",
            _header(_TITLE_COL_1, _DESC_COL_1),
            "  110" + " " * (_DESC_COL_1 - 5) + "Action with a blank title column.",
        ]
    )
    with pytest.raises(NatureOfSuitParseError, match="has no title"):
        parse_nature_of_suit_code_descriptions(source)


def test_parser_accepts_bytes_and_rejects_non_utf8_bytes() -> None:
    parsed_from_bytes = parse_nature_of_suit_code_descriptions(SYNTHETIC_SOURCE.encode("utf-8"))
    assert parsed_from_bytes.counts.entries == 3

    with pytest.raises(NatureOfSuitParseError, match="not valid UTF-8"):
        parse_nature_of_suit_code_descriptions(b"\xff\xfe not utf-8")


def test_build_nature_of_suit_code_package_is_a_controlled_code_list_not_a_concept_scheme() -> None:
    parsed = parse_nature_of_suit_code_descriptions(SYNTHETIC_SOURCE)

    bundle = build_nature_of_suit_code_package(parsed, captured_at="2026-08-03T00:00:00Z")

    assert bundle.resource_manifest["resourceKind"] == "controlledCodeList"
    assert bundle.resource_manifest["identityStatus"] == "publisherIdentifiersPreserved"
    assert bundle.resource_manifest["conceptIdentityClaimed"] is False
    assert bundle.resource_manifest["acceptedOutputUseAuthorized"] is False
    assert bundle.resource_manifest["usageCeiling"] == "developmentOnly"
    assert bundle.resource_manifest["observationCount"] == 3
    assert all(observation["conceptIdentityClaimed"] is False for observation in bundle.observations)
    assert all(observation["eligibleUses"] == ["deterministicMetadata"] for observation in bundle.observations)


def test_package_keeps_the_official_code_separate_from_any_minted_identifier() -> None:
    parsed = parse_nature_of_suit_code_descriptions(SYNTHETIC_SOURCE)
    bundle = build_nature_of_suit_code_package(parsed, captured_at="2026-08-03T00:00:00Z")

    insurance = next(item for item in bundle.observations if item["code"] == "110")
    # The observation's own "id" is a capture-local URN, never claimed to be
    # the official code. The official code lives only in the identifiers
    # array (and the convenience "code" field), tagged with its own kind.
    assert insurance["id"] != "110"
    assert insurance["id"].startswith("urn:ref:source-observation:")
    (identifier,) = insurance["identifiers"]
    assert identifier["value"] == "110"
    assert identifier["kind"] == NATURE_OF_SUIT_CODE_IDENTIFIER_KIND
    assert identifier["sourceUri"] == NATURE_OF_SUIT_CODE_DESCRIPTIONS_URL


def test_package_round_trips_through_a_written_directory(tmp_path: Path) -> None:
    parsed = parse_nature_of_suit_code_descriptions(SYNTHETIC_SOURCE)
    bundle = build_nature_of_suit_code_package(parsed, captured_at="2026-08-03T00:00:00Z")

    written = bundle.write_to(tmp_path / "package")
    reopened = SourceControlledResourceView.open(written)

    assert reopened.logical_digest == bundle.logical_digest
    assert len(reopened.observations) == 3
    assert reopened.resource_manifest["resourceKind"] == "controlledCodeList"
    assert reopened.resource_manifest["resourceId"] == NATURE_OF_SUIT_CODES_RESOURCE_ID


@pytest.mark.skipif(not REAL_FIXTURE_PATH.is_file(), reason="real JS-044 fixture is not present")
def test_verified_real_full_source_counts_and_cross_page_stitch() -> None:
    payload = REAL_FIXTURE_PATH.read_bytes()

    parsed = parse_nature_of_suit_code_descriptions(payload)

    assert parsed.source_sha256 == HISTORICAL_SHA256
    assert parsed.counts == HISTORICAL_COUNTS

    # 893's description is split across a page break in the real PDF; the
    # continuation must land back on the same entry, not a stray fragment.
    environmental = parsed.entry_by_code("893")
    assert environmental.title == "Environmental Matters"
    assert "National Environmental Policy Act" in environmental.description
    assert environmental.description.endswith("River & Harbor Act penalty 3:401-437, 1251.")

    # The continuation section on page 8 stays a distinct, verbatim heading;
    # this module never merges it back into "Other Statutes".
    continued = next(s for s in parsed.sections if s.heading_lines == ("Other Statutes (Continued)",))
    codes_in_continued = [e.code for e in parsed.entries if e.section_id == continued.section_id]
    assert codes_in_continued == ["895", "896", "899", "950"]

    (note,) = parsed.document_notes
    assert note.text.startswith("Note: The statutes listed above are not all-inclusive")


@pytest.mark.skipif(not REAL_FIXTURE_PATH.is_file(), reason="real JS-044 fixture is not present")
def test_verified_real_full_source_packages_cleanly() -> None:
    payload = REAL_FIXTURE_PATH.read_bytes()
    parsed = parse_nature_of_suit_code_descriptions(payload)

    bundle = build_nature_of_suit_code_package(parsed, captured_at="2026-08-03T00:00:00Z")

    assert bundle.resource_manifest["observationCount"] == 93
    assert bundle.coverage_report["reportStatus"] == "pass"
    codes = sorted(observation["code"] for observation in bundle.observations)
    assert len(codes) == len(set(codes)) == 93
