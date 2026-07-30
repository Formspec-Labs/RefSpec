"""Lossless reader for the April 1, 2025 Federal Register thesaurus PDF.

The Office of the Federal Register publishes this revision as a styled PDF.
Bold entries are official indexing terms. Red bold-italic entries are
variants. ``See`` redirects a variant, and ``See also`` records an associative
reference. Bracketed targets such as ``[Specific chemicals]`` are publisher
suggestions for source-local specificity, not managed concepts.

The parser reads the PDF's authored font roles and validates the combined list
against the separate official-term and variant indexes. It never treats the
1995 broad document categories as hierarchy. The 2025 source expressly says
that those categories were removed.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Any, Literal

from refspec.storage import canonical_json

FEDERAL_REGISTER_THESAURUS_2025_URL = (
    "https://www.archives.gov/files/federal-register/cfr/"
    "thesaurus-4-1-2025.pdf"
)
FEDERAL_REGISTER_THESAURUS_2025_SHA256 = (
    "sha256:66dd28fff5defedfb151d04dc4ef255181085cce76618cb10c9372db6540810f"
)
FEDERAL_REGISTER_THESAURUS_2025_BYTE_LENGTH = 1_051_423
FEDERAL_REGISTER_THESAURUS_2025_PAGE_COUNT = 180
FEDERAL_REGISTER_THESAURUS_2025_ISSUED = "2025-04-01"
FEDERAL_REGISTER_THESAURUS_2025_PARSER_VERSION = (
    "federal-register-thesaurus-2025-styled-pdf-v1"
)

FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI = (
    "urn:ref:federal-register-thesaurus:2025-04-01:scheme"
)
PREFERRED_LABEL_PROPERTY_IRI = "http://www.w3.org/2004/02/skos/core#prefLabel"
ALTERNATE_LABEL_PROPERTY_IRI = "http://www.w3.org/2004/02/skos/core#altLabel"
RELATED_PROPERTY_IRI = "http://www.w3.org/2004/02/skos/core#related"

_MAIN_PAGE_RANGE = range(4, 140)
_OFFICIAL_INDEX_PAGE_RANGE = range(140, 163)
_VARIANT_INDEX_PAGE_RANGE = range(163, 180)
_PAGE_FOOTER = re.compile(r"^\d+\s*\|\s*Page$")
_INDEX_ROW = re.compile(r"^(?P<label>\*?.*?)\s*\.{3,}\s*(?P<page>\d+)$")
_SEE_ALSO = re.compile(r"^See also(?:\s|$)")
_SEE = re.compile(r"^See(?:\s|$)")
_OPEN_PATTERN = re.compile(r"^\[[^\[\]]+\]$")

ReferenceKind = Literal["see", "related"]
VariantResolutionStatus = Literal[
    "recognizedVariant",
    "ambiguous",
    "unresolved",
]
ReferenceResolutionStatus = Literal[
    "resolved",
    "suggestedOpenTermPattern",
    "unresolved",
]


class FederalRegisterThesaurus2025Error(ValueError):
    """The exact PDF cannot be interpreted without inventing source meaning."""


@dataclass(frozen=True, slots=True)
class PdfSourceLocator:
    """One semantic occurrence in the PDF."""

    pdf_page: int
    printed_page: int
    source_ordinal: int


@dataclass(frozen=True, slots=True)
class OfficialTerm:
    """One official indexing term and its project-managed local identity."""

    entry_id: str
    concept_id: str
    label: str
    locator: PdfSourceLocator


@dataclass(frozen=True, slots=True)
class VariantRedirect:
    """One authored ``See`` target under a variant occurrence."""

    redirect_id: str
    variant_id: str
    raw_target_label: str
    target_concept_id: str | None
    resolution_status: ReferenceResolutionStatus
    locator: PdfSourceLocator


@dataclass(frozen=True, slots=True)
class VariantTerm:
    """One authored variant occurrence.

    A literal may occur more than once with different redirects. The status is
    computed across all occurrences of the same normalized literal, so callers
    cannot mistake a locally simple occurrence for a globally ambiguous
    variant.
    """

    variant_id: str
    label: str
    resolution_status: VariantResolutionStatus
    target_concept_ids: tuple[str, ...]
    redirect_ids: tuple[str, ...]
    locator: PdfSourceLocator


@dataclass(frozen=True, slots=True)
class RelatedReference:
    """One authored ``See also`` reference or open-term suggestion."""

    relation_id: str
    source_concept_id: str
    raw_target_label: str
    target_concept_id: str | None
    resolution_status: ReferenceResolutionStatus
    locator: PdfSourceLocator


@dataclass(frozen=True, slots=True)
class SuggestedOpenTermPattern:
    """A bracketed publisher suggestion, never a managed concept."""

    pattern_id: str
    source_entry_id: str
    reference_kind: ReferenceKind
    raw_literal: str
    locator: PdfSourceLocator


@dataclass(frozen=True, slots=True)
class UnresolvedReference2025:
    """A non-bracketed source reference with no official target."""

    unresolved_id: str
    source_entry_id: str
    reference_kind: ReferenceKind
    raw_target_label: str
    reason: str
    locator: PdfSourceLocator


@dataclass(frozen=True, slots=True)
class IndexAnomaly:
    """A summary-index row that is not an authored term occurrence."""

    anomaly_id: str
    index_kind: Literal["official", "variant"]
    raw_label: str
    pdf_page: int
    reason: str


@dataclass(frozen=True, slots=True)
class FederalRegisterThesaurus2025Counts:
    """Locked source and parsed counts for coverage checks."""

    source_pages: int
    source_bytes: int
    official_terms: int
    variant_occurrences: int
    unique_variant_literals: int
    recognized_variant_occurrences: int
    ambiguous_variant_occurrences: int
    unresolved_variant_occurrences: int
    see_references: int
    related_references: int
    resolved_see_references: int
    resolved_related_references: int
    suggested_open_term_patterns: int
    unresolved_references: int
    official_index_rows: int
    variant_index_rows: int
    index_anomalies: int


@dataclass(frozen=True, slots=True)
class FederalRegisterThesaurus2025:
    """Lossless parsed view of the exact April 1, 2025 publication."""

    source_sha256: str
    source_bytes: int
    source_pages: int
    official_terms: tuple[OfficialTerm, ...]
    variants: tuple[VariantTerm, ...]
    variant_redirects: tuple[VariantRedirect, ...]
    related_references: tuple[RelatedReference, ...]
    suggested_open_term_patterns: tuple[SuggestedOpenTermPattern, ...]
    unresolved_references: tuple[UnresolvedReference2025, ...]
    index_anomalies: tuple[IndexAnomaly, ...]
    official_index_rows: int
    variant_index_rows: int
    source_artifact_bytes: bytes | None = None

    @property
    def counts(self) -> FederalRegisterThesaurus2025Counts:
        return FederalRegisterThesaurus2025Counts(
            source_pages=self.source_pages,
            source_bytes=self.source_bytes,
            official_terms=len(self.official_terms),
            variant_occurrences=len(self.variants),
            unique_variant_literals=len(
                {_normalize_exact(item.label) for item in self.variants}
            ),
            recognized_variant_occurrences=sum(
                item.resolution_status == "recognizedVariant"
                for item in self.variants
            ),
            ambiguous_variant_occurrences=sum(
                item.resolution_status == "ambiguous" for item in self.variants
            ),
            unresolved_variant_occurrences=sum(
                item.resolution_status == "unresolved" for item in self.variants
            ),
            see_references=len(self.variant_redirects),
            related_references=len(self.related_references),
            resolved_see_references=sum(
                item.resolution_status == "resolved"
                for item in self.variant_redirects
            ),
            resolved_related_references=sum(
                item.resolution_status == "resolved"
                for item in self.related_references
            ),
            suggested_open_term_patterns=len(self.suggested_open_term_patterns),
            unresolved_references=len(self.unresolved_references),
            official_index_rows=self.official_index_rows,
            variant_index_rows=self.variant_index_rows,
            index_anomalies=len(self.index_anomalies),
        )

    def official_by_normalized_label(self) -> dict[str, OfficialTerm]:
        return {
            _normalize_exact(item.label): item for item in self.official_terms
        }

    def variants_by_normalized_label(self) -> dict[str, tuple[VariantTerm, ...]]:
        grouped: dict[str, list[VariantTerm]] = defaultdict(list)
        for item in self.variants:
            grouped[_normalize_exact(item.label)].append(item)
        return {key: tuple(value) for key, value in grouped.items()}


@dataclass(frozen=True, slots=True)
class _PdfLine:
    pdf_page: int
    printed_page: int
    source_ordinal: int
    x: float
    fonts: tuple[str, ...]
    text: str


@dataclass(frozen=True, slots=True)
class _EntrySeed:
    entry_id: str
    label: str
    kind: Literal["official", "variant"]
    locator: PdfSourceLocator


@dataclass(frozen=True, slots=True)
class _ReferenceSeed:
    source_entry_id: str
    kind: ReferenceKind
    raw_target_label: str
    locator: PdfSourceLocator


def _normalize_exact(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )


def _clean_joined_line(value: str) -> str:
    value = re.sub(r"\[\s+", "[", value)
    value = re.sub(r"\s+\]", "]", value)
    return " ".join(value.split())


def _font_local_name(value: str) -> str:
    return value.split("+", 1)[-1]


def _is_official_font(fonts: Sequence[str]) -> bool:
    return any(
        _font_local_name(font) == "Calibri-Bold" for font in fonts
    )


def _is_variant_font(fonts: Sequence[str]) -> bool:
    return any(
        _font_local_name(font) == "Calibri-BoldItalic" for font in fonts
    )


def _is_heading_font(fonts: Sequence[str]) -> bool:
    return bool(fonts) and all(
        _font_local_name(font) == "Cambria" for font in fonts
    )


def _extract_lines(reader: Any, page_indexes: Sequence[int]) -> tuple[_PdfLine, ...]:
    lines: list[_PdfLine] = []
    source_ordinal = 0
    for page_index in page_indexes:
        spans: list[tuple[int, float, float, str, str]] = []

        def visitor(
            text: str,
            _cm: Sequence[float],
            tm: Sequence[float],
            font: Mapping[str, Any] | None,
            _font_size: float,
            _spans: list[tuple[int, float, float, str, str]] = spans,
        ) -> None:
            stripped = text.strip()
            if not stripped:
                return
            base_font = str(font.get("/BaseFont", "")) if font else ""
            _spans.append(
                (
                    len(_spans),
                    round(float(tm[4]), 1),
                    round(float(tm[5]), 1),
                    base_font,
                    stripped,
                )
            )

        reader.pages[page_index].extract_text(visitor_text=visitor)
        groups: list[tuple[float, list[tuple[int, float, str, str]]]] = []
        for span_order, x, y, font, text in spans:
            if groups and abs(groups[-1][0] - y) < 0.2:
                groups[-1][1].append((span_order, x, font, text))
            else:
                groups.append((y, [(span_order, x, font, text)]))
        for _y, group in groups:
            group.sort(key=lambda item: (item[1], item[0]))
            joined = _clean_joined_line(" ".join(item[3] for item in group))
            if not joined:
                continue
            source_ordinal += 1
            lines.append(
                _PdfLine(
                    pdf_page=page_index + 1,
                    printed_page=page_index - 2,
                    source_ordinal=source_ordinal,
                    x=min(item[1] for item in group),
                    fonts=tuple(item[2] for item in group),
                    text=joined,
                )
            )
    return tuple(lines)


def _parse_index(
    lines: Sequence[_PdfLine],
    *,
    index_kind: Literal["official", "variant"],
) -> tuple[tuple[tuple[str, int, int], ...], tuple[IndexAnomaly, ...]]:
    rows: list[tuple[str, int, int]] = []
    anomalies: list[IndexAnomaly] = []
    for line in lines:
        if _PAGE_FOOTER.fullmatch(line.text):
            continue
        if line.text.startswith("ALPHABETICAL LIST"):
            continue
        if _is_heading_font(line.fonts):
            continue
        match = _INDEX_ROW.fullmatch(line.text)
        if match is None:
            raise FederalRegisterThesaurus2025Error(
                f"{index_kind} index row on PDF page {line.pdf_page} "
                f"does not carry a term and page number: {line.text!r}"
            )
        label = match.group("label").removeprefix("*").strip()
        printed_page = int(match.group("page"))
        if index_kind == "variant" and (
            _SEE.fullmatch(label)
            or _SEE_ALSO.fullmatch(label)
            or _SEE.match(label)
            or _SEE_ALSO.match(label)
        ):
            anomalies.append(
                IndexAnomaly(
                    anomaly_id=(
                        f"frt25-index-anomaly-{len(anomalies) + 1:04d}"
                    ),
                    index_kind=index_kind,
                    raw_label=label,
                    pdf_page=line.pdf_page,
                    reason=(
                        "styled See marker leaked into the generated variant "
                        "index; it is not a variant heading"
                    ),
                )
            )
            continue
        rows.append((label, printed_page, line.pdf_page))
    return tuple(rows), tuple(anomalies)


def _parse_main(
    lines: Sequence[_PdfLine],
) -> tuple[tuple[_EntrySeed, ...], tuple[_ReferenceSeed, ...]]:
    entries: list[_EntrySeed] = []
    references: list[_ReferenceSeed] = []
    current: _EntrySeed | None = None
    current_marker: ReferenceKind | None = None
    semantic_ordinal = 0

    for line in lines:
        if _PAGE_FOOTER.fullmatch(line.text) or _is_heading_font(line.fonts):
            continue
        semantic_ordinal += 1
        locator = PdfSourceLocator(
            pdf_page=line.pdf_page,
            printed_page=line.printed_page,
            source_ordinal=semantic_ordinal,
        )
        if _SEE_ALSO.match(line.text):
            if current is None:
                raise FederalRegisterThesaurus2025Error(
                    f"See also on PDF page {line.pdf_page} has no source entry"
                )
            current_marker = "related"
            target = _SEE_ALSO.sub("", line.text, count=1).strip()
            if target:
                references.append(
                    _ReferenceSeed(
                        source_entry_id=current.entry_id,
                        kind=current_marker,
                        raw_target_label=target,
                        locator=locator,
                    )
                )
            continue
        if _SEE.match(line.text):
            if current is None:
                raise FederalRegisterThesaurus2025Error(
                    f"See on PDF page {line.pdf_page} has no source entry"
                )
            current_marker = "see"
            target = _SEE.sub("", line.text, count=1).strip()
            if target:
                references.append(
                    _ReferenceSeed(
                        source_entry_id=current.entry_id,
                        kind=current_marker,
                        raw_target_label=target,
                        locator=locator,
                    )
                )
            continue
        if line.x < 90 and (
            _is_official_font(line.fonts) or _is_variant_font(line.fonts)
        ):
            kind: Literal["official", "variant"] = (
                "variant" if _is_variant_font(line.fonts) else "official"
            )
            entry_id = (
                f"frt25-entry-{len(entries) + 1:04d}"
                if kind == "official"
                else f"frt25-variant-{sum(item.kind == 'variant' for item in entries) + 1:04d}"
            )
            current = _EntrySeed(
                entry_id=entry_id,
                label=line.text.removeprefix("*").strip(),
                kind=kind,
                locator=locator,
            )
            entries.append(current)
            current_marker = None
            continue
        if current is not None and current_marker is not None:
            references.append(
                _ReferenceSeed(
                    source_entry_id=current.entry_id,
                    kind=current_marker,
                    raw_target_label=line.text,
                    locator=locator,
                )
            )
            continue
        raise FederalRegisterThesaurus2025Error(
            f"unclassified PDF content on page {line.pdf_page}: {line.text!r}"
        )
    return tuple(entries), tuple(references)


def _require_same_multiset(
    *,
    combined: Sequence[str],
    indexed: Sequence[str],
    label: str,
) -> None:
    left = Counter(_normalize_exact(item) for item in combined)
    right = Counter(_normalize_exact(item) for item in indexed)
    if left != right:
        missing = sorted((right - left).elements())
        extra = sorted((left - right).elements())
        raise FederalRegisterThesaurus2025Error(
            f"{label} combined list and index differ; "
            f"missing={missing[:10]}, extra={extra[:10]}"
        )


def parse_federal_register_thesaurus_2025_pdf(
    source: bytes,
    *,
    require_pinned_source: bool = True,
) -> FederalRegisterThesaurus2025:
    """Parse the exact styled PDF and fail closed on source or layout drift."""

    if not isinstance(source, bytes) or not source:
        raise TypeError("source must be non-empty PDF bytes")
    source_sha256 = "sha256:" + hashlib.sha256(source).hexdigest()
    if require_pinned_source and (
        source_sha256 != FEDERAL_REGISTER_THESAURUS_2025_SHA256
        or len(source) != FEDERAL_REGISTER_THESAURUS_2025_BYTE_LENGTH
    ):
        raise FederalRegisterThesaurus2025Error(
            "Federal Register 2025 thesaurus PDF does not match the pinned "
            "April 1, 2025 source"
        )
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - dependency gate
        raise FederalRegisterThesaurus2025Error(
            "pypdf is required to parse the styled 2025 thesaurus PDF"
        ) from error
    try:
        reader = PdfReader(BytesIO(source))
    except Exception as error:
        raise FederalRegisterThesaurus2025Error(
            f"Federal Register 2025 source is not a readable PDF: {error}"
        ) from error
    if require_pinned_source and len(reader.pages) != FEDERAL_REGISTER_THESAURUS_2025_PAGE_COUNT:
        raise FederalRegisterThesaurus2025Error(
            "Federal Register 2025 thesaurus page count drifted"
        )

    main_lines = _extract_lines(reader, tuple(_MAIN_PAGE_RANGE))
    official_index_lines = _extract_lines(
        reader, tuple(_OFFICIAL_INDEX_PAGE_RANGE)
    )
    variant_index_lines = _extract_lines(
        reader, tuple(_VARIANT_INDEX_PAGE_RANGE)
    )
    entries, reference_seeds = _parse_main(main_lines)
    official_index, official_anomalies = _parse_index(
        official_index_lines,
        index_kind="official",
    )
    variant_index, variant_anomalies = _parse_index(
        variant_index_lines,
        index_kind="variant",
    )
    anomalies = (*official_anomalies, *variant_anomalies)

    official_seeds = [item for item in entries if item.kind == "official"]
    variant_seeds = [item for item in entries if item.kind == "variant"]
    _require_same_multiset(
        combined=[item.label for item in official_seeds],
        indexed=[item[0] for item in official_index],
        label="official-term",
    )
    _require_same_multiset(
        combined=[item.label for item in variant_seeds],
        indexed=[item[0] for item in variant_index],
        label="variant",
    )

    official_terms = tuple(
        OfficialTerm(
            entry_id=seed.entry_id,
            concept_id=f"frt25-concept-{ordinal:04d}",
            label=seed.label,
            locator=seed.locator,
        )
        for ordinal, seed in enumerate(official_seeds, start=1)
    )
    official_by_entry = {
        item.entry_id: item for item in official_terms
    }
    official_by_label: dict[str, OfficialTerm] = {}
    for item in official_terms:
        key = _normalize_exact(item.label)
        if key in official_by_label:
            raise FederalRegisterThesaurus2025Error(
                f"official term label repeats after normalization: {item.label!r}"
            )
        official_by_label[key] = item
    seed_by_entry = {item.entry_id: item for item in entries}

    redirects: list[VariantRedirect] = []
    related: list[RelatedReference] = []
    open_patterns: list[SuggestedOpenTermPattern] = []
    unresolved: list[UnresolvedReference2025] = []
    redirects_by_variant: dict[str, list[VariantRedirect]] = defaultdict(list)
    for seed in reference_seeds:
        source_entry = seed_by_entry[seed.source_entry_id]
        target = official_by_label.get(
            _normalize_exact(seed.raw_target_label)
        )
        is_open = _OPEN_PATTERN.fullmatch(seed.raw_target_label) is not None
        if is_open:
            status: ReferenceResolutionStatus = "suggestedOpenTermPattern"
            open_patterns.append(
                SuggestedOpenTermPattern(
                    pattern_id=(
                        f"frt25-open-pattern-{len(open_patterns) + 1:04d}"
                    ),
                    source_entry_id=source_entry.entry_id,
                    reference_kind=seed.kind,
                    raw_literal=seed.raw_target_label,
                    locator=seed.locator,
                )
            )
        else:
            status = "resolved" if target is not None else "unresolved"
        if seed.kind == "see":
            if source_entry.kind != "variant":
                raise FederalRegisterThesaurus2025Error(
                    f"official term {source_entry.label!r} carries a See redirect"
                )
            redirect = VariantRedirect(
                redirect_id=f"frt25-see-{len(redirects) + 1:04d}",
                variant_id=source_entry.entry_id,
                raw_target_label=seed.raw_target_label,
                target_concept_id=(
                    target.concept_id if target is not None else None
                ),
                resolution_status=status,
                locator=seed.locator,
            )
            redirects.append(redirect)
            redirects_by_variant[source_entry.entry_id].append(redirect)
        else:
            if source_entry.kind != "official":
                raise FederalRegisterThesaurus2025Error(
                    f"variant {source_entry.label!r} carries See also"
                )
            source_term = official_by_entry[source_entry.entry_id]
            related.append(
                RelatedReference(
                    relation_id=f"frt25-related-{len(related) + 1:04d}",
                    source_concept_id=source_term.concept_id,
                    raw_target_label=seed.raw_target_label,
                    target_concept_id=(
                        target.concept_id if target is not None else None
                    ),
                    resolution_status=status,
                    locator=seed.locator,
                )
            )
        if status == "unresolved":
            unresolved.append(
                UnresolvedReference2025(
                    unresolved_id=(
                        f"frt25-unresolved-{len(unresolved) + 1:04d}"
                    ),
                    source_entry_id=source_entry.entry_id,
                    reference_kind=seed.kind,
                    raw_target_label=seed.raw_target_label,
                    reason="target is not an official 2025 term",
                    locator=seed.locator,
                )
            )

    variant_targets_by_label: dict[str, set[str]] = defaultdict(set)
    variant_has_nonconcept_target: dict[str, bool] = defaultdict(bool)
    for seed in variant_seeds:
        key = _normalize_exact(seed.label)
        item_redirects = redirects_by_variant.get(seed.entry_id, [])
        if not item_redirects:
            variant_has_nonconcept_target[key] = True
        for redirect in item_redirects:
            if redirect.target_concept_id is None:
                variant_has_nonconcept_target[key] = True
            else:
                variant_targets_by_label[key].add(redirect.target_concept_id)

    variants: list[VariantTerm] = []
    for seed in variant_seeds:
        key = _normalize_exact(seed.label)
        targets = tuple(sorted(variant_targets_by_label[key]))
        if len(targets) == 1 and not variant_has_nonconcept_target[key]:
            resolution: VariantResolutionStatus = "recognizedVariant"
        elif targets:
            resolution = "ambiguous"
        else:
            resolution = "unresolved"
        variants.append(
            VariantTerm(
                variant_id=seed.entry_id,
                label=seed.label,
                resolution_status=resolution,
                target_concept_ids=targets,
                redirect_ids=tuple(
                    item.redirect_id
                    for item in redirects_by_variant.get(seed.entry_id, [])
                ),
                locator=seed.locator,
            )
        )

    return FederalRegisterThesaurus2025(
        source_sha256=source_sha256,
        source_bytes=len(source),
        source_pages=len(reader.pages),
        official_terms=official_terms,
        variants=tuple(variants),
        variant_redirects=tuple(redirects),
        related_references=tuple(related),
        suggested_open_term_patterns=tuple(open_patterns),
        unresolved_references=tuple(unresolved),
        index_anomalies=tuple(anomalies),
        official_index_rows=len(official_index),
        variant_index_rows=len(variant_index) + len(anomalies),
        source_artifact_bytes=source,
    )


def federal_register_thesaurus_2025_extract(
    parsed: FederalRegisterThesaurus2025,
) -> dict[str, Any]:
    """Return the deterministic checked-in source extract."""

    return {
        "schemaVersion": "1.0",
        "parserVersion": FEDERAL_REGISTER_THESAURUS_2025_PARSER_VERSION,
        "source": {
            "id": FEDERAL_REGISTER_THESAURUS_2025_URL,
            "issued": FEDERAL_REGISTER_THESAURUS_2025_ISSUED,
            "sha256": parsed.source_sha256,
            "byteLength": parsed.source_bytes,
            "pageCount": parsed.source_pages,
        },
        "counts": asdict(parsed.counts),
        "officialTerms": [asdict(item) for item in parsed.official_terms],
        "variants": [asdict(item) for item in parsed.variants],
        "variantRedirects": [
            asdict(item) for item in parsed.variant_redirects
        ],
        "relatedReferences": [
            asdict(item) for item in parsed.related_references
        ],
        "suggestedOpenTermPatterns": [
            asdict(item) for item in parsed.suggested_open_term_patterns
        ],
        "unresolvedReferences": [
            asdict(item) for item in parsed.unresolved_references
        ],
        "indexAnomalies": [asdict(item) for item in parsed.index_anomalies],
    }


def federal_register_thesaurus_2025_extract_bytes(
    parsed: FederalRegisterThesaurus2025,
) -> bytes:
    """Serialize the source extract in the repository's canonical JSON form."""

    return (
        canonical_json(federal_register_thesaurus_2025_extract(parsed)).encode(
            "utf-8"
        )
        + b"\n"
    )


def _locator_from_dict(value: Mapping[str, Any]) -> PdfSourceLocator:
    return PdfSourceLocator(
        pdf_page=int(value["pdf_page"]),
        printed_page=int(value["printed_page"]),
        source_ordinal=int(value["source_ordinal"]),
    )


def load_federal_register_thesaurus_2025_extract(
    source: bytes | str,
) -> FederalRegisterThesaurus2025:
    """Load and validate a canonical source extract without opening the PDF."""

    try:
        data = json.loads(source)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FederalRegisterThesaurus2025Error(
            f"2025 thesaurus source extract is not valid JSON: {error}"
        ) from error
    if not isinstance(data, Mapping):
        raise FederalRegisterThesaurus2025Error(
            "2025 thesaurus source extract must be an object"
        )
    if (
        data.get("schemaVersion") != "1.0"
        or data.get("parserVersion")
        != FEDERAL_REGISTER_THESAURUS_2025_PARSER_VERSION
    ):
        raise FederalRegisterThesaurus2025Error(
            "2025 thesaurus source extract version drifted"
        )
    source_record = data.get("source")
    if not isinstance(source_record, Mapping) or (
        source_record.get("id") != FEDERAL_REGISTER_THESAURUS_2025_URL
        or source_record.get("issued")
        != FEDERAL_REGISTER_THESAURUS_2025_ISSUED
        or source_record.get("sha256")
        != FEDERAL_REGISTER_THESAURUS_2025_SHA256
        or source_record.get("byteLength")
        != FEDERAL_REGISTER_THESAURUS_2025_BYTE_LENGTH
        or source_record.get("pageCount")
        != FEDERAL_REGISTER_THESAURUS_2025_PAGE_COUNT
    ):
        raise FederalRegisterThesaurus2025Error(
            "2025 thesaurus source extract does not bind the pinned PDF"
        )

    def rows(name: str) -> list[Mapping[str, Any]]:
        value = data.get(name)
        if not isinstance(value, list) or any(
            not isinstance(item, Mapping) for item in value
        ):
            raise FederalRegisterThesaurus2025Error(
                f"source extract {name} must be an object array"
            )
        return list(value)

    parsed = FederalRegisterThesaurus2025(
        source_sha256=str(source_record["sha256"]),
        source_bytes=int(source_record["byteLength"]),
        source_pages=int(source_record["pageCount"]),
        official_terms=tuple(
            OfficialTerm(
                entry_id=str(item["entry_id"]),
                concept_id=str(item["concept_id"]),
                label=str(item["label"]),
                locator=_locator_from_dict(item["locator"]),
            )
            for item in rows("officialTerms")
        ),
        variants=tuple(
            VariantTerm(
                variant_id=str(item["variant_id"]),
                label=str(item["label"]),
                resolution_status=str(item["resolution_status"]),  # type: ignore[arg-type]
                target_concept_ids=tuple(item["target_concept_ids"]),
                redirect_ids=tuple(item["redirect_ids"]),
                locator=_locator_from_dict(item["locator"]),
            )
            for item in rows("variants")
        ),
        variant_redirects=tuple(
            VariantRedirect(
                redirect_id=str(item["redirect_id"]),
                variant_id=str(item["variant_id"]),
                raw_target_label=str(item["raw_target_label"]),
                target_concept_id=(
                    str(item["target_concept_id"])
                    if item.get("target_concept_id") is not None
                    else None
                ),
                resolution_status=str(item["resolution_status"]),  # type: ignore[arg-type]
                locator=_locator_from_dict(item["locator"]),
            )
            for item in rows("variantRedirects")
        ),
        related_references=tuple(
            RelatedReference(
                relation_id=str(item["relation_id"]),
                source_concept_id=str(item["source_concept_id"]),
                raw_target_label=str(item["raw_target_label"]),
                target_concept_id=(
                    str(item["target_concept_id"])
                    if item.get("target_concept_id") is not None
                    else None
                ),
                resolution_status=str(item["resolution_status"]),  # type: ignore[arg-type]
                locator=_locator_from_dict(item["locator"]),
            )
            for item in rows("relatedReferences")
        ),
        suggested_open_term_patterns=tuple(
            SuggestedOpenTermPattern(
                pattern_id=str(item["pattern_id"]),
                source_entry_id=str(item["source_entry_id"]),
                reference_kind=str(item["reference_kind"]),  # type: ignore[arg-type]
                raw_literal=str(item["raw_literal"]),
                locator=_locator_from_dict(item["locator"]),
            )
            for item in rows("suggestedOpenTermPatterns")
        ),
        unresolved_references=tuple(
            UnresolvedReference2025(
                unresolved_id=str(item["unresolved_id"]),
                source_entry_id=str(item["source_entry_id"]),
                reference_kind=str(item["reference_kind"]),  # type: ignore[arg-type]
                raw_target_label=str(item["raw_target_label"]),
                reason=str(item["reason"]),
                locator=_locator_from_dict(item["locator"]),
            )
            for item in rows("unresolvedReferences")
        ),
        index_anomalies=tuple(
            IndexAnomaly(
                anomaly_id=str(item["anomaly_id"]),
                index_kind=str(item["index_kind"]),  # type: ignore[arg-type]
                raw_label=str(item["raw_label"]),
                pdf_page=int(item["pdf_page"]),
                reason=str(item["reason"]),
            )
            for item in rows("indexAnomalies")
        ),
        official_index_rows=int(data["counts"]["official_index_rows"]),
        variant_index_rows=int(data["counts"]["variant_index_rows"]),
        source_artifact_bytes=None,
    )
    expected_counts = data.get("counts")
    if not isinstance(expected_counts, Mapping) or asdict(parsed.counts) != dict(
        expected_counts
    ):
        raise FederalRegisterThesaurus2025Error(
            "2025 thesaurus source extract counts drifted"
        )
    official_ids = {item.concept_id for item in parsed.official_terms}
    if len(official_ids) != len(parsed.official_terms):
        raise FederalRegisterThesaurus2025Error(
            "2025 thesaurus source extract repeats a concept identity"
        )
    if any(
        target not in official_ids
        for item in parsed.variants
        for target in item.target_concept_ids
    ) or any(
        item.target_concept_id is not None
        and item.target_concept_id not in official_ids
        for item in (
            *parsed.variant_redirects,
            *parsed.related_references,
        )
    ):
        raise FederalRegisterThesaurus2025Error(
            "2025 thesaurus source extract references a nonmember concept"
        )
    return parsed


def load_packaged_federal_register_thesaurus_2025(
) -> FederalRegisterThesaurus2025:
    """Load the checked-in current release extract used by normal pipelines."""

    resource = (
        importlib.resources.files("refspec")
        .joinpath("resources")
        .joinpath("federal_register_thesaurus")
        .joinpath("2025-04-01")
        .joinpath("source-extract.json")
    )
    return load_federal_register_thesaurus_2025_extract(resource.read_bytes())


def federal_register_thesaurus_2025_concept_iri(
    concept_id: str,
) -> str:
    """Convert one source-local ordinal identity to its managed IRI."""

    match = re.fullmatch(r"frt25-concept-(\d{4,})", concept_id)
    if match is None:
        raise FederalRegisterThesaurus2025Error(
            f"unknown 2025 source-local concept id {concept_id!r}"
        )
    return (
        "urn:ref:federal-register-thesaurus:2025-04-01:concept:"
        + match.group(1)
    )


__all__ = [
    "ALTERNATE_LABEL_PROPERTY_IRI",
    "FEDERAL_REGISTER_THESAURUS_2025_BYTE_LENGTH",
    "FEDERAL_REGISTER_THESAURUS_2025_ISSUED",
    "FEDERAL_REGISTER_THESAURUS_2025_PAGE_COUNT",
    "FEDERAL_REGISTER_THESAURUS_2025_PARSER_VERSION",
    "FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI",
    "FEDERAL_REGISTER_THESAURUS_2025_SHA256",
    "FEDERAL_REGISTER_THESAURUS_2025_URL",
    "PREFERRED_LABEL_PROPERTY_IRI",
    "RELATED_PROPERTY_IRI",
    "FederalRegisterThesaurus2025",
    "FederalRegisterThesaurus2025Counts",
    "FederalRegisterThesaurus2025Error",
    "IndexAnomaly",
    "OfficialTerm",
    "PdfSourceLocator",
    "RelatedReference",
    "SuggestedOpenTermPattern",
    "UnresolvedReference2025",
    "VariantRedirect",
    "VariantTerm",
    "federal_register_thesaurus_2025_concept_iri",
    "federal_register_thesaurus_2025_extract",
    "federal_register_thesaurus_2025_extract_bytes",
    "load_federal_register_thesaurus_2025_extract",
    "load_packaged_federal_register_thesaurus_2025",
    "parse_federal_register_thesaurus_2025_pdf",
]
