"""Lossless reader for the U.S. Courts JS-044 Nature of Suit code table.

The Administrative Office of the U.S. Courts publishes "Civil Nature of Suit
Code Descriptions" only as a paginated PDF (the JS-044 form's code table).
This module does not open, render, or extract text from that PDF itself --
following the same division of labor as the Federal Register 1995 thesaurus
adapter, PDF-to-text extraction is a separate, independently pinned step.
This module parses only the resulting pre-extracted text, and it is strict
about the exact convention that text must follow:

The extraction step is expected to run Poppler's ``pdftotext -layout`` against
the official PDF, which preserves the document's column layout using spaces.
That layout is what this parser depends on -- not any content-based
guessing. Concretely, the source has three physical columns (Code, Title,
Description). Each page states its own "Code ... Title ... Description"
header once per printed table; this parser reads the character offsets of
"Title" and "Description" on that exact header line and uses them, for the
remainder of that page, as fixed column boundaries. A data row's own first
line is sliced at those offsets. A later physical line whose leading
whitespace lands exactly on the title offset, the description offset, or
both (the source wraps a heading and a description independently) continues
that entry's title, description, or both.

A source page break resets the known column offsets, because
``pdftotext -layout`` recomputes column widths per page and offsets are not
comparable across a page boundary. Two structural consequences follow, both
observed in the true JS-044 document and both required to parse it:

* The line(s) immediately following a page's "(Rev. MM/YY)" line, before any
  blank line, continue the last open entry from the previous page if one
  exists (e.g. a description that a mid-paragraph page break interrupted).
  Since no column offsets exist yet on the new page, this window is closed
  the moment the first blank line appears, not by a further offset match.
* Category headings occupy one or two short, un-indented physical lines
  (this source visually centers and sometimes wraps a heading; the two-line
  form also appears for compound headings, for example "Prisoner Petitions"
  above "Habeas Corpus", or "Other" above "Prisoner Petitions" for a
  differently wrapped compound heading). This parser preserves both lines
  verbatim as one heading tuple and never asserts a parent/child
  relationship between them, because the plain-text layout supplies no
  reliable signal (font size, weight) to distinguish a two-line wrap from a
  true parent/subsection pair.

A wrapped Title-column continuation is preserved verbatim alongside the
heading line rather than split into a "real title" and a "note": nothing in
the extracted layout marks a boundary between a wrapped title (for example
"Recovery of Overpayment & Enforcement" / "Judgment") and a bracketed
cross-reference note attached under the same column (for example "Airplane"
/ "(Excludes airplane product liability claims)"). Splitting them would
require guessing from content, which this module refuses to do.

The Nature of Suit code itself (a stable three-digit number, e.g. "110") is
a publisher-assigned identifier, unlike the Federal Register 1995 thesaurus,
which supplied no stable identifier and required source-local ordinals.
``build_nature_of_suit_code_package`` therefore records each code as a
``publisherIdentifiersPreserved`` identifier and never mints a replacement.
The capture-local observation id it does mint (via
``refspec.registry.infrastructure.source_controlled_resource``) never claims concept
identity: ``conceptIdentityClaimed`` is always False, matching this source's
catalog role of deterministic case-classification metadata, not a governed
subject vocabulary. Downstream consumers must keep this official code
separate from any platform-normalized value (e.g. a docket platform's own
category label), which is why this module records nothing but the official
JS-044 text.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.source_controlled_resource import (
    ResourceUse,
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

NATURE_OF_SUIT_CODE_DESCRIPTIONS_URL = "https://www.uscourts.gov/sites/default/files/js_044_code_descriptions.pdf"
NATURE_OF_SUIT_CODE_AUTHORITY_URI = "https://www.uscourts.gov/"
NATURE_OF_SUIT_CODE_IDENTIFIER_KIND = "uscourtsNatureOfSuitCode"
NATURE_OF_SUIT_CODES_RESOURCE_ID = "uscourts-nature-of-suit-codes-js-044"
NATURE_OF_SUIT_CODE_LANGUAGE = "en"

_PAGE_TITLE = "Civil Nature of Suit Code Descriptions"
_REVISION_RE = re.compile(r"^\(Rev\. \d{2}/\d{2}\)$")
_FOOTER_RE = re.compile(r"^Page \d+ of \d+$")
_FOOTER_MIN_INDENT = 20
_COLUMN_HEADER_RE = re.compile(r"^Code\s+Title\s+Description\s*$")
_CODE_ROW_RE = re.compile(r"^(\d{3})\s{2,}\S")
_CODE_ROW_MAX_INDENT = 4
_CONTINUATION_MIN_INDENT = 5


class NatureOfSuitParseError(ValueError):
    """The source text cannot be interpreted without guessing."""


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _source_bytes(source: str | bytes) -> tuple[str, bytes]:
    if isinstance(source, bytes):
        try:
            return source.decode("utf-8"), source
        except UnicodeDecodeError as exc:
            raise NatureOfSuitParseError(f"nature of suit code source is not valid UTF-8 at byte {exc.start}") from exc
    if not isinstance(source, str):
        raise TypeError("source must be str or bytes")
    return source, source.encode("utf-8")


@dataclass(frozen=True, slots=True)
class SourceLocator:
    """Exact source line range for one parsed record."""

    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class PageHeader:
    """One page's title, revision label, and page-number footer."""

    page_id: str
    page_number: int
    revision_label: str
    locator: SourceLocator


@dataclass(frozen=True, slots=True)
class CategorySection:
    """One authored category heading, exactly as printed (one or two lines).

    ``heading_lines`` never asserts a parent/subsection relationship between
    a two-line heading's lines; see the module docstring.
    """

    section_id: str
    section_ordinal: int
    heading_lines: tuple[str, ...]
    page_id: str
    locator: SourceLocator


@dataclass(frozen=True, slots=True)
class NatureOfSuitEntry:
    """One Code/Title/Description row, including every wrapped line.

    ``title_lines`` and ``description_lines`` preserve the source's own
    physical line breaks; ``title`` and ``description`` are single-space
    joins of those lines, offered for convenience only.
    """

    entry_id: str
    source_ordinal: int
    code: str
    section_id: str
    title_lines: tuple[str, ...]
    title: str
    description_lines: tuple[str, ...]
    description: str
    locator: SourceLocator


@dataclass(frozen=True, slots=True)
class DocumentNote:
    """One document-level note printed outside any Code/Title/Description row."""

    note_id: str
    text: str
    raw_lines: tuple[str, ...]
    locator: SourceLocator


@dataclass(frozen=True, slots=True)
class ImportCounts:
    """Feature counts used by import coverage and regression checks."""

    source_lines: int
    source_bytes: int
    pages: int
    sections: int
    entries: int
    document_notes: int


@dataclass(frozen=True, slots=True)
class NatureOfSuitCodeDescriptions:
    """Lossless parsed view of one exact pre-extracted source text."""

    source_sha256: str
    source_lines: int
    source_bytes: int
    pages: tuple[PageHeader, ...]
    sections: tuple[CategorySection, ...]
    entries: tuple[NatureOfSuitEntry, ...]
    document_notes: tuple[DocumentNote, ...]
    source_artifact_bytes: bytes | None = None

    @property
    def counts(self) -> ImportCounts:
        return ImportCounts(
            source_lines=self.source_lines,
            source_bytes=self.source_bytes,
            pages=len(self.pages),
            sections=len(self.sections),
            entries=len(self.entries),
            document_notes=len(self.document_notes),
        )

    def entry_by_code(self, code: str) -> NatureOfSuitEntry:
        """Look up one entry by its official three-digit code."""

        for entry in self.entries:
            if entry.code == code:
                return entry
        raise KeyError(code)


@dataclass(slots=True)
class _OpenEntry:
    code: str
    section_id: str
    title_lines: list[str]
    description_lines: list[str]
    active_field: str
    start_line: int
    end_line: int


@dataclass(slots=True)
class _OpenSection:
    heading_lines: list[str]
    page_id: str
    start_line: int
    end_line: int
    header_done: bool


@dataclass(slots=True)
class _OpenNote:
    lines: list[str]
    start_line: int
    end_line: int


def parse_nature_of_suit_code_descriptions(source: str | bytes) -> NatureOfSuitCodeDescriptions:
    """Parse the pinned ``pdftotext -layout`` convention described above.

    Any line this parser cannot attribute to a page, a category heading, a
    Code/Title/Description row, or a trailing document note raises
    ``NatureOfSuitParseError`` rather than guessing. A duplicate three-digit
    code across the whole document raises for the same reason: the source
    never repeats a code, so a repeat signals a parse defect, not a real
    duplicate to reconcile.
    """

    text, encoded = _source_bytes(source)
    lines = text.splitlines()
    line_count = len(lines)

    pages: list[PageHeader] = []
    sections: list[CategorySection] = []
    entries: list[NatureOfSuitEntry] = []
    notes: list[DocumentNote] = []

    open_section: _OpenSection | None = None
    open_entry: _OpenEntry | None = None
    open_note: _OpenNote | None = None
    title_col: int | None = None
    desc_col: int | None = None
    seen_codes: set[str] = set()

    def flush_entry() -> None:
        nonlocal open_entry
        if open_entry is None:
            return
        title = " ".join(open_entry.title_lines)
        description = " ".join(open_entry.description_lines)
        if not title:
            raise NatureOfSuitParseError(
                f"entry {open_entry.code!r} starting at line {open_entry.start_line} has no title"
            )
        entries.append(
            NatureOfSuitEntry(
                entry_id=f"nos-entry-{len(entries) + 1:04d}",
                source_ordinal=len(entries) + 1,
                code=open_entry.code,
                section_id=open_entry.section_id,
                title_lines=tuple(open_entry.title_lines),
                title=title,
                description_lines=tuple(open_entry.description_lines),
                description=description,
                locator=SourceLocator(open_entry.start_line, open_entry.end_line),
            )
        )
        open_entry = None

    def flush_note() -> None:
        nonlocal open_note
        if open_note is None:
            return
        notes.append(
            DocumentNote(
                note_id=f"nos-note-{len(notes) + 1:04d}",
                text=" ".join(open_note.lines),
                raw_lines=tuple(open_note.lines),
                locator=SourceLocator(open_note.start_line, open_note.end_line),
            )
        )
        open_note = None

    def open_new_section(heading: str, line_number: int, page_id: str) -> None:
        nonlocal open_section
        open_section = _OpenSection(
            heading_lines=[heading],
            page_id=page_id,
            start_line=line_number,
            end_line=line_number,
            header_done=False,
        )
        sections.append(
            CategorySection(
                section_id=f"nos-section-{len(sections) + 1:04d}",
                section_ordinal=len(sections) + 1,
                heading_lines=(),  # replaced on close; placeholder keeps ordinal stable
                page_id=page_id,
                locator=SourceLocator(line_number, line_number),
            )
        )

    def close_section_record() -> None:
        # Rewrite the just-appended placeholder with the section's final
        # heading lines, using the page the section actually opened on (not
        # whatever page parsing has since reached).
        assert open_section is not None
        sections[-1] = CategorySection(
            section_id=sections[-1].section_id,
            section_ordinal=sections[-1].section_ordinal,
            heading_lines=tuple(open_section.heading_lines),
            page_id=open_section.page_id,
            locator=SourceLocator(open_section.start_line, open_section.end_line),
        )

    current_page_id = ""
    i = 0
    while i < line_count:
        raw = lines[i]
        stripped = raw.strip()
        indent = _indent(raw)
        line_number = i + 1

        if not stripped:
            i += 1
            continue

        if stripped == _PAGE_TITLE and indent == 0:
            # A section's heading/column-header block is always fully
            # contained within one page in the observed source, so the open
            # section (if any) is left open across the page boundary rather
            # than finalized here; only its entries may continue on the new
            # page (the page-crossing continuation window below).
            i += 1
            if i >= line_count:
                raise NatureOfSuitParseError(f"unexpected end of source after page title at line {line_number}")
            revision_line = lines[i].strip()
            if not _REVISION_RE.match(revision_line):
                raise NatureOfSuitParseError(
                    f"expected a '(Rev. MM/YY)' line after the page title at line {i + 1}, found {revision_line!r}"
                )
            page_number = len(pages) + 1
            current_page_id = f"nos-page-{page_number:04d}"
            pages.append(
                PageHeader(
                    page_id=current_page_id,
                    page_number=page_number,
                    revision_label=revision_line,
                    locator=SourceLocator(line_number, i + 1),
                )
            )
            title_col = None
            desc_col = None
            i += 1
            continue

        if _FOOTER_RE.match(stripped) and indent >= _FOOTER_MIN_INDENT:
            i += 1
            continue

        if _COLUMN_HEADER_RE.match(stripped) and indent <= _CODE_ROW_MAX_INDENT:
            if open_section is None:
                raise NatureOfSuitParseError(f"column header at line {line_number} has no open category section")
            flush_entry()
            title_col = raw.find("Title")
            desc_col = raw.find("Description")
            open_section.header_done = True
            open_section.end_line = line_number
            i += 1
            continue

        code_match = _CODE_ROW_RE.match(stripped) if indent <= _CODE_ROW_MAX_INDENT else None
        if code_match:
            if title_col is None or desc_col is None:
                raise NatureOfSuitParseError(
                    f"code row at line {line_number} appears before its section's column header"
                )
            if open_section is None:  # pragma: no cover - title_col implies a section
                raise NatureOfSuitParseError(f"code row at line {line_number} has no open category section")
            code = code_match.group(1)
            if code in seen_codes:
                raise NatureOfSuitParseError(f"nature of suit code {code!r} repeats at line {line_number}")
            seen_codes.add(code)
            flush_entry()
            flush_note()
            title_text = raw[title_col:desc_col].strip()
            desc_text = raw[desc_col:].strip()
            open_entry = _OpenEntry(
                code=code,
                section_id=sections[-1].section_id,
                title_lines=[title_text] if title_text else [],
                description_lines=[desc_text] if desc_text else [],
                active_field="description",
                start_line=line_number,
                end_line=line_number,
            )
            i += 1
            continue

        if (
            title_col is not None
            and desc_col is not None
            and indent in (title_col, desc_col)
            and open_entry is not None
        ):
            title_part = raw[title_col:desc_col].strip()
            desc_part = raw[desc_col:].strip()
            if not title_part and not desc_part:
                raise NatureOfSuitParseError(f"continuation line at {line_number} carries no title or description text")
            if title_part:
                open_entry.title_lines.append(title_part)
                open_entry.active_field = "title"
            if desc_part:
                open_entry.description_lines.append(desc_part)
                open_entry.active_field = "description"
            open_entry.end_line = line_number
            i += 1
            continue

        if title_col is None and indent >= _CONTINUATION_MIN_INDENT:
            # Page-crossing continuation window: the first non-blank line(s)
            # right after a "(Rev. MM/YY)" line, before this page has any
            # column header of its own. See the module docstring.
            if open_entry is None:
                raise NatureOfSuitParseError(
                    f"line {line_number} looks like a wrapped continuation but no entry is open: {raw!r}"
                )
            getattr(open_entry, f"{open_entry.active_field}_lines").append(stripped)
            open_entry.end_line = line_number
            i += 1
            continue

        if indent == 0:
            flush_entry()
            if open_note is None:
                open_note = _OpenNote(lines=[stripped], start_line=line_number, end_line=line_number)
            else:
                open_note.lines.append(stripped)
                open_note.end_line = line_number
            i += 1
            continue

        if open_note is not None:
            open_note.lines.append(stripped)
            open_note.end_line = line_number
            i += 1
            continue

        # Otherwise this is a category heading line (one physical line of a
        # one- or two-line heading block; see the module docstring).
        flush_entry()
        if open_section is None or open_section.header_done:
            if open_section is not None:
                close_section_record()
            open_new_section(stripped, line_number, current_page_id)
        else:
            open_section.heading_lines.append(stripped)
            open_section.end_line = line_number
        i += 1

    flush_entry()
    flush_note()
    if open_section is not None:
        close_section_record()

    return NatureOfSuitCodeDescriptions(
        source_sha256="sha256:" + hashlib.sha256(encoded).hexdigest(),
        source_lines=line_count,
        source_bytes=len(encoded),
        pages=tuple(pages),
        sections=tuple(sections),
        entries=tuple(entries),
        document_notes=tuple(notes),
        source_artifact_bytes=encoded,
    )


# ---------------------------------------------------------------------------
# Deterministic closed packaging: one controlledCodeList SourceControlledResourceBundle.
# Every observation preserves the official code as a publisher-supplied
# identifier and never claims concept identity (conceptIdentityClaimed is
# always False). Nothing here reconciles the official code against any
# platform-normalized value from a different source.
# ---------------------------------------------------------------------------


def _identifier_payload(identifier: ControlledIdentifier, *, source_path: str) -> dict[str, Any]:
    return {
        "value": identifier.value,
        "kind": identifier.kind,
        "authorityUri": identifier.authority_uri,
        "sourceUri": identifier.source_uri,
        "sourcePath": source_path,
        "observedAt": identifier.observed_at,
        "sourceDigest": identifier.source_digest,
    }


def _observation_id(*, source_path: str, identifiers: Sequence[Mapping[str, Any]]) -> str:
    identity = {
        "resourceId": NATURE_OF_SUIT_CODES_RESOURCE_ID,
        "sourceArtifact": NATURE_OF_SUIT_CODE_DESCRIPTIONS_URL,
        "sourcePath": source_path,
        "identifiers": [
            {"value": item["value"], "kind": item["kind"], "authorityUri": item["authorityUri"]} for item in identifiers
        ],
    }
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return f"urn:ref:source-observation:{NATURE_OF_SUIT_CODES_RESOURCE_ID}:{digest}"


def _observation(
    entry: NatureOfSuitEntry,
    parsed: NatureOfSuitCodeDescriptions,
    *,
    source_uri: str,
    captured_at: str,
) -> dict[str, Any]:
    source_path = f"entries[{entry.source_ordinal}]"
    identifier = ControlledIdentifier(
        value=entry.code,
        kind=NATURE_OF_SUIT_CODE_IDENTIFIER_KIND,
        authority_uri=NATURE_OF_SUIT_CODE_AUTHORITY_URI,
        source_uri=source_uri,
        observed_at=captured_at,
        effective_at=None,
        source_digest=parsed.source_sha256,
    )
    identifiers = [_identifier_payload(identifier, source_path=source_path)]
    return {
        "id": _observation_id(source_path=source_path, identifiers=identifiers),
        "sourceArtifact": source_uri,
        "sourcePath": source_path,
        "sourceOrdinal": entry.source_ordinal,
        "labels": [
            {
                "value": entry.title,
                "language": NATURE_OF_SUIT_CODE_LANGUAGE,
                "role": "preferred",
            }
        ],
        "identifiers": identifiers,
        "uses": ["deterministicMetadata"],
        "conceptIdentityClaimed": False,
        # Official JS-044 text only; never a platform-normalized value from a
        # different source (for example a docket platform's own category).
        "code": entry.code,
        "description": entry.description,
        "sectionId": entry.section_id,
    }


def build_nature_of_suit_code_package(
    parsed: NatureOfSuitCodeDescriptions,
    *,
    captured_at: str,
    source_uri: str = NATURE_OF_SUIT_CODE_DESCRIPTIONS_URL,
    uses: Sequence[ResourceUse] = ("deterministicMetadata",),
) -> SourceControlledResourceBundle:
    """Package one parsed result as a deterministic ``controlledCodeList``.

    This never promotes the result into a concept scheme: ``resource_kind``
    stays ``controlledCodeList``, ``identity_status`` stays
    ``publisherIdentifiersPreserved`` because the code itself is
    publisher-assigned, and ``conceptIdentityClaimed`` stays false (enforced
    by ``source_controlled_resource``). Exact product policy governs use.
    """

    if parsed.source_artifact_bytes is None:
        raise NatureOfSuitParseError("parsed result has no retained source bytes to package")
    observations = tuple(
        _observation(entry, parsed, source_uri=source_uri, captured_at=captured_at) for entry in parsed.entries
    )
    return build_source_controlled_resource_bundle(
        resource_id=NATURE_OF_SUIT_CODES_RESOURCE_ID,
        title="U.S. Courts Civil Nature of Suit Code Descriptions (JS-044)",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=uses,
        captured_at=captured_at,
        observations=observations,
        source_artifacts={source_uri: parsed.source_artifact_bytes},
        source_observed_count=len(parsed.entries),
    )


__all__ = [
    "NATURE_OF_SUIT_CODES_RESOURCE_ID",
    "NATURE_OF_SUIT_CODE_AUTHORITY_URI",
    "NATURE_OF_SUIT_CODE_DESCRIPTIONS_URL",
    "NATURE_OF_SUIT_CODE_IDENTIFIER_KIND",
    "NATURE_OF_SUIT_CODE_LANGUAGE",
    "CategorySection",
    "DocumentNote",
    "ImportCounts",
    "NatureOfSuitCodeDescriptions",
    "NatureOfSuitEntry",
    "NatureOfSuitParseError",
    "PageHeader",
    "SourceLocator",
    "build_nature_of_suit_code_package",
    "parse_nature_of_suit_code_descriptions",
]
