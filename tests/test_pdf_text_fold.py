"""The PDF text fold must repair lookup without touching real content."""

from __future__ import annotations

import pytest

from refspec.pdf_text import (
    PDF_TEXT_FOLDS,
    fold_pdf_text,
    pdf_text_fold_counts,
)


@pytest.mark.parametrize(
    ("published", "expected"),
    [
        # The exact strings measured on the wire before the fold existed.
        ("Staﬀ Adjustments under Section 502 of NGPA", "Staff Adjustments under Section 502 of NGPA"),
        ("Certiﬁcates for Interstate Natural Gas Pipeline Companies", "Certificates for Interstate Natural Gas Pipeline Companies"),
        ("Audits other than ﬁnancial audits by the Chief Accountant", "Audits other than financial audits by the Chief Accountant"),
        ("Exemption Notiﬁcation", "Exemption Notification"),
        ("Form 6 ‐ Annual Report of Oil Pipeline Companies", "Form 6 - Annual Report of Oil Pipeline Companies"),
    ],
)
def test_fold_makes_published_text_searchable(published: str, expected: str) -> None:
    assert fold_pdf_text(published) == expected


@pytest.mark.parametrize(
    "preserved",
    [
        # Diacritics are the spelling of the term, not typography.
        "Hawaiʻi Volcanoes National Park",
        "Kīlauea",
        "Société Générale",
        "Español",
        # Em and en dashes are the publisher's punctuation; one of these was
        # verified against the printed FERC page.
        "Information Collections – Public Involvement",
        "Regulatory Planning and Review — an executive order",
        # Curly quotation marks likewise.
        "Executive Order (“EO”) 12866",
        # The publisher's own damage: repairing it would invent text.
        "Notice of Preliminary Permit �09�09Applications",
    ],
)
def test_fold_leaves_real_content_alone(preserved: str) -> None:
    assert fold_pdf_text(preserved) == preserved


def test_every_declared_fold_is_exercised_and_reported() -> None:
    """A fold nobody can demonstrate is a fold nobody should trust."""

    for source, target in PDF_TEXT_FOLDS.items():
        sample = f"before {source} after"
        assert fold_pdf_text(sample) == f"before {target} after"
        assert pdf_text_fold_counts(sample) == {source: 1}


def test_fold_is_idempotent() -> None:
    once = fold_pdf_text("Staﬀ ﬁles a Certiﬁcate ‐ today")
    assert fold_pdf_text(once) == once
