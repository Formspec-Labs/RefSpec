"""Lossless reader for the Federal Register's 1995 text thesaurus.

The source format is an alphabetic list with four relationship markers:

``see``
    A non-preferred entry points to one or more preferred entries.
``x``
    A preferred entry names one of its alternate labels.
``xx``
    A preferred entry names one of the broad categories used to group terms
    in the 1995 document. It does not assert a semantic parent concept.
``sa``
    A preferred entry names an associatively related preferred entry.

This adapter preserves authored occurrences instead of flattening them into one
row per concept.  Identifiers use source-local ordinals; no identifier depends
on a label.  Relationship targets resolve only against preferred headings,
because the source describes ``sa`` and ``xx`` as preferred-term references.
An unresolved reference remains an explicit record and makes the default parse
fail closed.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

FEDERAL_REGISTER_THESAURUS_1995_URL = "https://www.archives.gov/files/federal-register/cfr/thesaurus-alpha.txt"

HISTORICAL_GROUPING_PREDICATE_IRI = (
    "urn:ref:predicate:federal-register:historical-document-grouping"
)
# Compatibility import for callers of the 1995 regression adapter. The value
# is intentionally not ``skos:broader``.
BROADER_PREDICATE_IRI = HISTORICAL_GROUPING_PREDICATE_IRI
ASSOCIATIVE_PREDICATE_IRI = "http://www.w3.org/2004/02/skos/core#related"
SCOPE_NOTE_PROPERTY_IRI = "http://www.w3.org/2004/02/skos/core#scopeNote"
CATEGORY_NOTATION_DATATYPE_IRI = "urn:ref:datatype:federal-register-thesaurus-category-codes:1995"

_HEADER_END = "related terms:"
_MARKERS = frozenset({"see", "x", "xx", "sa"})
_CATEGORY_NOTATION = re.compile(r"^(?P<label>.*?)(?:\s+)(?P<notation>\(\s*\d{2}(?:\s*,\s*\d{2})*\s*\))\s*$")
_CATEGORY_CODE = re.compile(r"\d{2}")

EntryKind = Literal["preferred", "nonPreferred"]
LabelRole = Literal["preferred", "alternate"]
LabelSource = Literal["heading", "see", "x"]
ReferenceKind = Literal[
    "see",
    "historicalGrouping",
    "related",
    "alternate",
]
ResolutionStatus = Literal["resolved", "unresolved"]


class ThesaurusParseError(ValueError):
    """The source text cannot be interpreted without guessing."""


class UnresolvedReferenceError(ThesaurusParseError):
    """One or more required references do not name a preferred source entry."""

    def __init__(self, result: FederalRegisterThesaurus):
        self.result = result
        preview = ", ".join(
            f"{item.reference_kind}@{item.locator.start_line}:{item.raw_target_label!r}"
            for item in result.unresolved_references[:5]
        )
        remaining = len(result.unresolved_references) - 5
        suffix = f", and {remaining} more" if remaining > 0 else ""
        super().__init__(
            f"{len(result.unresolved_references)} required Federal Register "
            f"thesaurus reference(s) did not resolve: {preview}{suffix}"
        )


@dataclass(frozen=True, slots=True)
class SourceLocator:
    """Exact source lines plus a source-local semantic occurrence ordinal."""

    start_line: int
    end_line: int
    ordinal: int


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """One unindented thesaurus heading, including non-preferred headings."""

    entry_id: str
    source_ordinal: int
    raw_heading: str
    label: str
    entry_kind: EntryKind
    concept_id: str | None
    locator: SourceLocator


@dataclass(frozen=True, slots=True)
class PreferredConcept:
    """A preferred entry identified by its position in the pinned source."""

    concept_id: str
    source_entry_id: str
    source_ordinal: int
    locator: SourceLocator


@dataclass(frozen=True, slots=True)
class LabelExpression:
    """One authored preferred or alternate label occurrence."""

    label_id: str
    concept_id: str
    role: LabelRole
    literal: str
    language_tag: str
    source: LabelSource
    source_entry_id: str
    source_reference_id: str | None
    locator: SourceLocator


@dataclass(frozen=True, slots=True)
class CategoryNotation:
    """The exact trailing category-code notation from a source heading."""

    notation_id: str
    source_entry_id: str
    concept_id: str | None
    raw_literal: str
    codes: tuple[str, ...]
    datatype_iri: str
    locator: SourceLocator


@dataclass(frozen=True, slots=True)
class ScopeNote:
    """One source scope note, including its original wrapped lines."""

    note_id: str
    source_entry_id: str
    concept_id: str | None
    property_iri: str
    text: str
    language_tag: str
    raw_lines: tuple[str, ...]
    locator: SourceLocator


@dataclass(frozen=True, slots=True)
class CrossReference:
    """One authored ``see`` statement from a non-preferred entry."""

    reference_id: str
    source_entry_id: str
    alternate_label: str
    raw_target_label: str
    target_concept_id: str | None
    resolution_status: ResolutionStatus
    locator: SourceLocator


@dataclass(frozen=True, slots=True)
class ConceptRelation:
    """One authored grouping or associative statement.

    The 1995 ``xx`` statement retains its authored grouping signal but is not
    interpreted as a SKOS hierarchy edge.
    """

    relation_id: str
    source_entry_id: str
    source_concept_id: str | None
    predicate_iri: str
    marker: Literal["xx", "sa"]
    raw_target_label: str
    target_concept_id: str | None
    resolution_status: ResolutionStatus
    locator: SourceLocator


@dataclass(frozen=True, slots=True)
class UnresolvedReference:
    """A required source reference that cannot be resolved without guessing."""

    unresolved_id: str
    reference_kind: ReferenceKind
    source_entry_id: str
    source_concept_id: str | None
    raw_target_label: str
    reason: str
    locator: SourceLocator


@dataclass(frozen=True, slots=True)
class ImportCounts:
    """Feature counts used by import coverage and regression checks."""

    source_lines: int
    source_bytes: int
    entries: int
    preferred_concepts: int
    nonpreferred_entries: int
    preferred_labels: int
    alternate_labels: int
    scope_notes: int
    category_notations: int
    see_references: int
    historical_grouping_relations: int
    associative_relations: int
    resolved_references: int
    unresolved_references: int


@dataclass(frozen=True, slots=True)
class FederalRegisterThesaurus:
    """Lossless parsed view of one exact source text."""

    source_sha256: str
    source_lines: int
    source_bytes: int
    entries: tuple[SourceEntry, ...]
    concepts: tuple[PreferredConcept, ...]
    labels: tuple[LabelExpression, ...]
    category_notations: tuple[CategoryNotation, ...]
    scope_notes: tuple[ScopeNote, ...]
    cross_references: tuple[CrossReference, ...]
    relations: tuple[ConceptRelation, ...]
    unresolved_references: tuple[UnresolvedReference, ...]
    source_artifact_bytes: bytes | None = None

    @property
    def counts(self) -> ImportCounts:
        preferred_labels = sum(item.role == "preferred" for item in self.labels)
        alternate_labels = len(self.labels) - preferred_labels
        historical_grouping_relations = sum(
            item.predicate_iri == HISTORICAL_GROUPING_PREDICATE_IRI
            for item in self.relations
        )
        associative_relations = len(self.relations) - historical_grouping_relations
        resolved_references = sum(item.resolution_status == "resolved" for item in self.cross_references) + sum(
            item.resolution_status == "resolved" for item in self.relations
        )
        return ImportCounts(
            source_lines=self.source_lines,
            source_bytes=self.source_bytes,
            entries=len(self.entries),
            preferred_concepts=len(self.concepts),
            nonpreferred_entries=sum(item.entry_kind == "nonPreferred" for item in self.entries),
            preferred_labels=preferred_labels,
            alternate_labels=alternate_labels,
            scope_notes=len(self.scope_notes),
            category_notations=len(self.category_notations),
            see_references=len(self.cross_references),
            historical_grouping_relations=historical_grouping_relations,
            associative_relations=associative_relations,
            resolved_references=resolved_references,
            unresolved_references=len(self.unresolved_references),
        )


@dataclass(slots=True)
class _Statement:
    marker: str
    raw_target_label: str
    locator: SourceLocator


@dataclass(slots=True)
class _RawScopeNote:
    raw_lines: tuple[str, ...]
    locator: SourceLocator


@dataclass(slots=True)
class _EntryBuilder:
    entry_id: str
    source_ordinal: int
    raw_heading: str
    label: str
    notation: tuple[str, tuple[str, ...], SourceLocator] | None
    locator: SourceLocator
    statements: list[_Statement]
    notes: list[_RawScopeNote]

    @property
    def is_preferred(self) -> bool:
        return not any(item.marker == "see" for item in self.statements)


def _normalize_reference_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _split_heading(raw_heading: str) -> tuple[str, str | None, tuple[str, ...]]:
    stripped = raw_heading.strip()
    match = _CATEGORY_NOTATION.fullmatch(stripped)
    if match is None:
        return stripped, None, ()
    notation = match.group("notation")
    return match.group("label").strip(), notation, tuple(_CATEGORY_CODE.findall(notation))


def _scope_note_text(raw_lines: tuple[str, ...]) -> str:
    joined = " ".join(line.strip() for line in raw_lines)
    if joined.startswith("(") and joined.endswith(")"):
        joined = joined[1:-1]
    return " ".join(joined.split())


def _source_bytes(source: str | bytes) -> tuple[str, bytes]:
    if isinstance(source, bytes):
        try:
            return source.decode("utf-8"), source
        except UnicodeDecodeError as exc:
            raise ThesaurusParseError(f"Federal Register thesaurus is not valid UTF-8 at byte {exc.start}") from exc
    if not isinstance(source, str):
        raise TypeError("source must be str or bytes")
    return source, source.encode("utf-8")


def _scan_entries(text: str) -> list[_EntryBuilder]:
    entries: list[_EntryBuilder] = []
    current: _EntryBuilder | None = None
    current_marker: str | None = None
    pending_note_lines: list[str] | None = None
    pending_note_start = 0
    pending_note_ordinal = 0
    source_ordinal = 0
    started = False

    def locator(start_line: int, end_line: int | None = None) -> SourceLocator:
        nonlocal source_ordinal
        source_ordinal += 1
        return SourceLocator(
            start_line=start_line,
            end_line=end_line if end_line is not None else start_line,
            ordinal=source_ordinal,
        )

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()

        if pending_note_lines is not None:
            pending_note_lines.append(raw_line)
            joined = " ".join(line.strip() for line in pending_note_lines)
            if joined.count("(") <= joined.count(")"):
                assert current is not None
                current.notes.append(
                    _RawScopeNote(
                        raw_lines=tuple(pending_note_lines),
                        locator=SourceLocator(
                            start_line=pending_note_start,
                            end_line=line_number,
                            ordinal=pending_note_ordinal,
                        ),
                    )
                )
                pending_note_lines = None
            continue

        if not started:
            if stripped.casefold().endswith(_HEADER_END):
                started = True
            continue
        if not stripped:
            continue

        indented = bool(raw_line[:1].isspace())
        marker = stripped.casefold()
        if indented and marker in _MARKERS:
            if current is None:
                raise ThesaurusParseError(f"relationship marker {stripped!r} at line {line_number} has no entry")
            current_marker = marker
            continue

        if indented and stripped.startswith("("):
            if current is None:
                raise ThesaurusParseError(f"scope note at line {line_number} has no source entry")
            note_locator = locator(line_number)
            if stripped.count("(") > stripped.count(")"):
                pending_note_lines = [raw_line]
                pending_note_start = line_number
                pending_note_ordinal = note_locator.ordinal
            else:
                current.notes.append(_RawScopeNote(raw_lines=(raw_line,), locator=note_locator))
            continue

        if indented:
            if current is None or current_marker is None:
                raise ThesaurusParseError(f"indented value at line {line_number} has no relationship marker")
            current.statements.append(
                _Statement(
                    marker=current_marker,
                    raw_target_label=stripped,
                    locator=locator(line_number),
                )
            )
            continue

        label, raw_notation, codes = _split_heading(raw_line)
        if not label:
            raise ThesaurusParseError(f"empty source heading at line {line_number}")
        entry_ordinal = len(entries) + 1
        entry_locator = locator(line_number)
        notation = (raw_notation, codes, locator(line_number)) if raw_notation is not None else None
        current = _EntryBuilder(
            entry_id=f"frt95-entry-{entry_ordinal:04d}",
            source_ordinal=entry_ordinal,
            raw_heading=raw_line,
            label=label,
            notation=notation,
            locator=entry_locator,
            statements=[],
            notes=[],
        )
        entries.append(current)
        current_marker = None

    if not started:
        raise ThesaurusParseError(f"Federal Register thesaurus header does not end with {_HEADER_END!r}")
    if pending_note_lines is not None:
        raise ThesaurusParseError(f"unterminated scope note beginning at line {pending_note_start}")
    return entries


def parse_federal_register_thesaurus(
    source: str | bytes,
    *,
    require_resolved: bool = True,
) -> FederalRegisterThesaurus:
    """Parse the pinned text format and optionally expose source defects.

    ``require_resolved`` defaults to ``True``.  Set it to ``False`` only when a
    coverage or reconciliation step needs to inspect the explicit unresolved
    records.  A permissive result is not a releasable vocabulary.
    """

    text, encoded = _source_bytes(source)
    builders = _scan_entries(text)

    preferred_by_label: dict[str, _EntryBuilder] = {}
    for entry in builders:
        if not entry.is_preferred:
            continue
        key = _normalize_reference_label(entry.label)
        if not key:
            raise ThesaurusParseError(f"preferred entry {entry.entry_id} has an empty normalized label")
        previous = preferred_by_label.get(key)
        if previous is not None:
            raise ThesaurusParseError(
                f"preferred entries {previous.entry_id} and {entry.entry_id} "
                f"have the same normalized label {entry.label!r}"
            )
        preferred_by_label[key] = entry

    concept_id_by_entry = {
        entry.entry_id: f"frt95-concept-{entry.source_ordinal:04d}" for entry in builders if entry.is_preferred
    }
    source_entries: list[SourceEntry] = []
    concepts: list[PreferredConcept] = []
    labels: list[LabelExpression] = []
    notations: list[CategoryNotation] = []
    notes: list[ScopeNote] = []
    cross_references: list[CrossReference] = []
    relations: list[ConceptRelation] = []
    unresolved: list[UnresolvedReference] = []

    def add_label(
        *,
        concept_id: str,
        role: LabelRole,
        literal: str,
        source_kind: LabelSource,
        source_entry_id: str,
        source_reference_id: str | None,
        item_locator: SourceLocator,
    ) -> None:
        labels.append(
            LabelExpression(
                label_id=f"frt95-label-{len(labels) + 1:04d}",
                concept_id=concept_id,
                role=role,
                literal=literal,
                language_tag="en",
                source=source_kind,
                source_entry_id=source_entry_id,
                source_reference_id=source_reference_id,
                locator=item_locator,
            )
        )

    def add_unresolved(
        *,
        reference_kind: ReferenceKind,
        source_entry_id: str,
        source_concept_id: str | None,
        raw_target_label: str,
        reason: str,
        item_locator: SourceLocator,
    ) -> None:
        unresolved.append(
            UnresolvedReference(
                unresolved_id=f"frt95-unresolved-{len(unresolved) + 1:04d}",
                reference_kind=reference_kind,
                source_entry_id=source_entry_id,
                source_concept_id=source_concept_id,
                raw_target_label=raw_target_label,
                reason=reason,
                locator=item_locator,
            )
        )

    for entry in builders:
        concept_id = concept_id_by_entry.get(entry.entry_id)
        entry_kind: EntryKind = "preferred" if entry.is_preferred else "nonPreferred"
        source_entries.append(
            SourceEntry(
                entry_id=entry.entry_id,
                source_ordinal=entry.source_ordinal,
                raw_heading=entry.raw_heading,
                label=entry.label,
                entry_kind=entry_kind,
                concept_id=concept_id,
                locator=entry.locator,
            )
        )
        if concept_id is not None:
            concepts.append(
                PreferredConcept(
                    concept_id=concept_id,
                    source_entry_id=entry.entry_id,
                    source_ordinal=entry.source_ordinal,
                    locator=entry.locator,
                )
            )
            add_label(
                concept_id=concept_id,
                role="preferred",
                literal=entry.label,
                source_kind="heading",
                source_entry_id=entry.entry_id,
                source_reference_id=None,
                item_locator=entry.locator,
            )

        if entry.notation is not None:
            raw_literal, codes, notation_locator = entry.notation
            notations.append(
                CategoryNotation(
                    notation_id=f"frt95-notation-{len(notations) + 1:04d}",
                    source_entry_id=entry.entry_id,
                    concept_id=concept_id,
                    raw_literal=raw_literal,
                    codes=codes,
                    datatype_iri=CATEGORY_NOTATION_DATATYPE_IRI,
                    locator=notation_locator,
                )
            )

        for note in entry.notes:
            notes.append(
                ScopeNote(
                    note_id=f"frt95-note-{len(notes) + 1:04d}",
                    source_entry_id=entry.entry_id,
                    concept_id=concept_id,
                    property_iri=SCOPE_NOTE_PROPERTY_IRI,
                    text=_scope_note_text(note.raw_lines),
                    language_tag="en",
                    raw_lines=note.raw_lines,
                    locator=note.locator,
                )
            )

        for statement in entry.statements:
            target_label, _, _ = _split_heading(statement.raw_target_label)
            target_entry = preferred_by_label.get(_normalize_reference_label(target_label))
            target_concept_id = concept_id_by_entry[target_entry.entry_id] if target_entry is not None else None

            if statement.marker == "see":
                reference_id = f"frt95-see-{len(cross_references) + 1:04d}"
                resolution_status: ResolutionStatus = "resolved" if target_concept_id is not None else "unresolved"
                cross_references.append(
                    CrossReference(
                        reference_id=reference_id,
                        source_entry_id=entry.entry_id,
                        alternate_label=entry.label,
                        raw_target_label=statement.raw_target_label,
                        target_concept_id=target_concept_id,
                        resolution_status=resolution_status,
                        locator=statement.locator,
                    )
                )
                if target_concept_id is None:
                    add_unresolved(
                        reference_kind="see",
                        source_entry_id=entry.entry_id,
                        source_concept_id=None,
                        raw_target_label=statement.raw_target_label,
                        reason="see target is not a preferred source heading",
                        item_locator=statement.locator,
                    )
                else:
                    add_label(
                        concept_id=target_concept_id,
                        role="alternate",
                        literal=entry.label,
                        source_kind="see",
                        source_entry_id=entry.entry_id,
                        source_reference_id=reference_id,
                        item_locator=entry.locator,
                    )
                continue

            if statement.marker == "x":
                if concept_id is None:
                    add_unresolved(
                        reference_kind="alternate",
                        source_entry_id=entry.entry_id,
                        source_concept_id=None,
                        raw_target_label=statement.raw_target_label,
                        reason="x alternate label belongs to a non-preferred entry",
                        item_locator=statement.locator,
                    )
                else:
                    add_label(
                        concept_id=concept_id,
                        role="alternate",
                        literal=statement.raw_target_label,
                        source_kind="x",
                        source_entry_id=entry.entry_id,
                        source_reference_id=None,
                        item_locator=statement.locator,
                    )
                continue

            if statement.marker not in {"xx", "sa"}:  # pragma: no cover - scanner invariant
                raise AssertionError(f"unknown marker {statement.marker!r}")
            relation_id = f"frt95-relation-{len(relations) + 1:04d}"
            predicate_iri = (
                HISTORICAL_GROUPING_PREDICATE_IRI
                if statement.marker == "xx"
                else ASSOCIATIVE_PREDICATE_IRI
            )
            resolution_status = "resolved" if concept_id is not None and target_concept_id is not None else "unresolved"
            relations.append(
                ConceptRelation(
                    relation_id=relation_id,
                    source_entry_id=entry.entry_id,
                    source_concept_id=concept_id,
                    predicate_iri=predicate_iri,
                    marker=statement.marker,
                    raw_target_label=statement.raw_target_label,
                    target_concept_id=target_concept_id,
                    resolution_status=resolution_status,
                    locator=statement.locator,
                )
            )
            if concept_id is None:
                add_unresolved(
                    reference_kind=(
                        "historicalGrouping"
                        if statement.marker == "xx"
                        else "related"
                    ),
                    source_entry_id=entry.entry_id,
                    source_concept_id=None,
                    raw_target_label=statement.raw_target_label,
                    reason=f"{statement.marker} source is not a preferred entry",
                    item_locator=statement.locator,
                )
            elif target_concept_id is None:
                add_unresolved(
                    reference_kind=(
                        "historicalGrouping"
                        if statement.marker == "xx"
                        else "related"
                    ),
                    source_entry_id=entry.entry_id,
                    source_concept_id=concept_id,
                    raw_target_label=statement.raw_target_label,
                    reason=f"{statement.marker} target is not a preferred source heading",
                    item_locator=statement.locator,
                )

    result = FederalRegisterThesaurus(
        source_sha256="sha256:" + hashlib.sha256(encoded).hexdigest(),
        source_lines=len(text.splitlines()),
        source_bytes=len(encoded),
        entries=tuple(source_entries),
        concepts=tuple(concepts),
        labels=tuple(labels),
        category_notations=tuple(notations),
        scope_notes=tuple(notes),
        cross_references=tuple(cross_references),
        relations=tuple(relations),
        unresolved_references=tuple(unresolved),
        source_artifact_bytes=encoded,
    )
    if require_resolved and result.unresolved_references:
        raise UnresolvedReferenceError(result)
    return result
