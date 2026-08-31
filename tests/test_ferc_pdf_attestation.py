"""Facts checked by reading the two FERC PDFs as rendered pages.

`research/evidence/ferc-pdf-attestation-2026-08-21/attestation.md` records a
page-by-page reading of both documents, done without consulting the producer's
parser. These tests pin what that reading established, so a change to the
producer breaks a check rather than silently diverging from the source.

They are not a substitute for a `SourceSpec`: they do not re-read the PDF, and
a new publisher revision would need the reading done again. What they prevent
is the extraction drifting away from a source that has been looked at.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKET_PDF = ROOT / "output" / "registry-real-data-sources" / "ferc-docket-prefix-june-2025.pdf"
CLASS_PDF = ROOT / "output" / "registry-real-data-sources" / "ferc-class-types-january-2025.pdf"

pytestmark = pytest.mark.skipif(
    not (DOCKET_PDF.is_file() and CLASS_PDF.is_file()),
    reason="pinned FERC captures are not present",
)


@pytest.fixture(scope="module")
def docket_rows():
    from refspec.registry import ferc_elibrary_codes as source

    return source.parse_ferc_docket_prefix_pdf(DOCKET_PDF.read_bytes()).rows


@pytest.fixture(scope="module")
def class_rows():
    from refspec.registry import ferc_elibrary_codes as source

    return source.parse_ferc_class_type_pdf(CLASS_PDF.read_bytes()).rows


def test_the_docket_pdf_splits_into_the_three_tables_the_pages_show(docket_rows) -> None:
    """Table 1 (73) + Table 2 (4) active, Table 3 (18) discontinued."""

    active = [row.prefix for row in docket_rows if row.status == "active"]
    discontinued = [row.prefix for row in docket_rows if row.status == "discontinued"]
    assert len(docket_rows) == 95
    assert len(active) == 77, "Table 1 has 73 prefixes and Table 2 has 4"
    assert len(discontinued) == 18
    # The three hyphen-suffixed codes are all in Table 3 and keep their hyphen.
    assert {"E-", "G-", "R-"} <= set(discontinued)
    # Page 1 begins at AC and page 4 ends at ZZ; Table 2 contributes the last four.
    assert active[0] == "AC"
    assert active[-4:] == ["HB", "IC", "ID", "P"]


def test_the_docket_pdf_keeps_the_publishers_own_punctuation(docket_rows) -> None:
    by_prefix = {row.prefix: row for row in docket_rows}
    # A bare '<' that survives unescaped.
    assert by_prefix["CD"].definition == "Conduit Determination (< than 5 MW Facility)"
    # The publisher's stray space inside "FERC- 65B", not tidied to "FERC-65B".
    assert "FERC- 65B [Waiver Notification]" in by_prefix["PH"].definition
    # En dash, not a hyphen.
    assert by_prefix["RT"].definition == "Electric Rate Filings – Rate Transmission"
    # Apostrophe survives, and the multi-line cell is joined without losing words.
    assert by_prefix["IC"].definition.startswith(
        "Information Collections – Public Involvement on the Development of the Commission's"
    )
    # The one observed normalisation: the page shows "Gen,  RM" with two spaces.
    assert by_prefix["PL"].library == "Gen, RM"


def test_the_class_pdf_excludes_repeated_print_headers_and_spacer_rows(class_rows) -> None:
    """The header band repeats mid-page on pages 4-7; blank spacer rows appear too.

    A reader that took every table row would ingest both as data. This is the
    defect the document most invites, so it is checked directly.
    """

    header_labels = {"Category", "Library", "Classification", "Type Description"}
    contaminated = [
        row
        for row in class_rows
        if {row.category, row.library, row.classification, row.type_description} & header_labels
    ]
    assert contaminated == []
    assert [row for row in class_rows if not row.type_description.strip()] == []


def test_the_class_pdf_row_split_matches_the_pages(class_rows) -> None:
    issuance = [row for row in class_rows if row.category == "Issuance"]
    assert len(class_rows) == 235
    # 51 Issuance rows on page 1 and 3 on page 2, counted off the rendered pages.
    assert len(issuance) == 54
    assert len([row for row in class_rows if row.category == "Submittal"]) == 181
    assert class_rows[0].type_description == (
        "ALJ Initial Decision/Certification of Initial Decision and Record"
    )
    assert class_rows[-1].type_description == "Form 552 - Annual Report of Natural Gas Transactions"


def test_the_class_pdf_preserves_publisher_defects(class_rows) -> None:
    libraries = {row.library for row in class_rows}
    # A trailing comma the publisher wrote, kept rather than stripped.
    assert "H, O, G," in libraries
    # Prose "and" rather than a comma, kept rather than normalised.
    assert "H, E and RM" in libraries
    # The publisher's own text stops mid-word; almost certainly "Pipelines".
    truncated = [row for row in class_rows if row.type_description.endswith("Hinshaw Pipe")]
    assert len(truncated) == 1
    assert truncated[0].type_description.startswith("Form 549D-Quarterly Transportation & Storage")
