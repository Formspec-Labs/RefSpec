"""Fold the typographic artefacts a PDF text layer carries into plain text.

A PDF encodes *typography*, not data. Its text layer stores what the renderer
drew, so a word set with an "fi" ligature arrives as U+FB01 and a hyphen drawn
from a text font arrives as U+2010 rather than ASCII hyphen-minus. Both render
identically to their plain forms -- that is the entire point of a ligature --
so the difference is invisible on the page and invisible in review, and it
survives every byte-level gate we have: these are valid Unicode, so canonical
N-Quads, the strict-parser sweep and SHACL all pass. It only shows up where it
hurts, which is lookup: a consumer searching "Staff Adjustments" does not match
"Staﬀ Adjustments", and "Certificates" does not match "Certiﬁcates".

Measured on the 2026-08-13d distribution before this module existed: 54
presentation-form ligatures and 143 U+2010 hyphens, all of them inherited
verbatim from publisher PDFs.

WHAT THIS DELIBERATELY DOES NOT TOUCH, because the same scan showed the wire is
mostly legitimate non-ASCII and a broad sweep would corrupt it:

* Diacritics and letters -- macrons (10,775 of them: ā ī ō ū), accented Latin,
  the Hawaiian ʻokina U+02BB, U+02BC. These are the spelling of the term.
* Em and en dashes (4,074 and 261). Publishers use them meaningfully, and one
  FERC definition's en-dash was verified against the printed page.
* Curly quotation marks. Same reasoning.
* U+FE20/U+FE21 combining ligature halves (1,745 pairs), which carry meaning in
  the MARC-derived bibliographic sources.
* U+FFFD REPLACEMENT CHARACTER. 213 reach the wire, and they are the
  PUBLISHER'S: the pinned Federal Register Parquet capture holds 71 values
  containing one, such as a title reading "Notice of Preliminary Permit
  �09�09Applications". Repairing those would mean inventing text the
  source does not contain, which is worse than carrying its damage honestly.

So this is not "normalize unicode". It is a closed, enumerated fold of the
artefacts a PDF text layer adds on top of the characters an author chose.
NFKC is not used: it would leave U+2010 alone while folding unrelated things
like superscripts.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

# Presentation forms and typographic hyphens, mapped to what the author wrote.
# Enumerated rather than derived from a Unicode category so that adding a
# character to this fold is a visible, reviewable decision.
PDF_TEXT_FOLDS: Mapping[str, str] = MappingProxyType(
    {
        "ﬀ": "ff",
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬅ": "st",
        "ﬆ": "st",
        "‐": "-",  # HYPHEN, semantically ASCII hyphen-minus
        "‑": "-",  # NON-BREAKING HYPHEN, ditto
    }
)

PDF_TEXT_FOLD_RULE = "refspec-pdf-text-fold-v1"

_TABLE = str.maketrans(dict(PDF_TEXT_FOLDS))


def fold_pdf_text(value: str) -> str:
    """Return ``value`` with PDF presentation forms folded to plain characters."""

    return value.translate(_TABLE)


def pdf_text_fold_counts(value: str) -> Mapping[str, int]:
    """Report which folds ``value`` would trigger, for evidence and tests."""

    return {source: value.count(source) for source in PDF_TEXT_FOLDS if source in value}
