"""Library of Congress pre-1951 Statutes at Large (Vols. 1-64) catalog resolver and dual-OCR reader.

GovInfo's ``STATUTE`` collection begins at Volume 65 (1951). For Volumes 1-64
(1789-1950) -- 2,097 rows of ``usc-popular-names.parquet`` and 33,485 rows of
``usc-act-sections.parquet`` in :mod:`refspec.registry.act_resolution` -- the
primary federal digital repository is the Library of Congress
``united-states-statutes-at-large`` collection.

Two structural properties established from the primary catalogue and 10
SHA-256-pinned PDFs (19,555 pages across Vols. 1-62) govern every function here:

1. **Catalogue lookup is required for PDF URLs, LoC caption years are
   non-exhaustive, and multi-part volumes cannot be disambiguated from
   ``(volume, page)`` alone.** Volume item URLs (``llsl-v1`` .. ``llsl-v64``)
   are arithmetic across all 64 volumes, and ``llsalvol`` page-turner resources
   (``llsal_001`` .. ``llsal_064``, 69 objects total) are single-object
   arithmetic for 62 of 64 volumes (Volume 18 splits into ``018a`` .. ``018e``;
   Volume 44 splits into ``044`` and ``044a`` for the 1925 U.S. Code). By
   contrast, ``tile.loc.gov`` PDF slugs are keyed by Congress/session or
   subject (``llsl-c38.pdf``, ``llsl-c75s2.pdf``, ``llsl-vol-6-private.pdf``),
   and 12 volumes (Vols. 1-5, 9-12, 18, 20, 44) publish 2 to 7 Congress- or
   part-level PDFs (97 PDFs total; never per-chapter PDFs). LoC's PDF captions
   frequently omit the opening calendar year of an autumn session (for example,
   ``llsl-c5.pdf`` is captioned ``"5th Congress (1798/1799)"`` even though its
   first page is ``1 Stat. 536``, enacted December 15, 1797). Each
   :class:`LlslPdfResource` therefore records both ``caption_year_start`` /
   ``caption_year_end`` verbatim and conservative ``year_start`` / ``year_end``
   spanning the full constitutional Congress term. Contradictory filters return
   ``pdf_resolution_status="unresolved_contradictory_filters"`` rather than
   silently dropping a constraint.
2. **All 10 sampled ``llsl`` PDFs carry two overlaid ``3 Tr`` invisible OCR
   layers across text-bearing statutory pages (with occasional blank or
   single-layer scan frames).** Text-bearing statutory pages paint a legacy
   Type 1 font pass (``Times-Roman``/``Bold``/``Italic``, ``Helvetica``,
   ``Courier``, ``WinAnsiEncoding``, ``3 Tr``) followed by a July 2021 ``Foxit
   FXPDFA 1.2`` / ``PDF Compressor 8.2.12.20`` Type 0 CID pass
   (``/InvisibleOCR``, ``Identity-H``, ``3 Tr``), while blank scan frames
   (e.g. ``llsl-c48.pdf`` p. 552) or un-reprocessed frames (e.g. ``llsl-c48.pdf``
   p. 292) carry zero or one text stream. Spatial PDF text extractors
   (``pdftotext`` default, ``-layout``, ``-bbox``) interleave both passes on
   every dual-OCR line. :func:`extract_llsl_pdf_ocr_layers` separates them by
   font and extracts physical running-header/footer bands, while
   :func:`score_llsl_layer_citation` binds folio, chapter, and section checks
   to the printed header and target act block.

Importing this module performs no network access and reads no files until a
pinned manifest loader is called.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pypdf import PdfReader
from pypdf.generic import ContentStream

EVIDENCE_RELATIVE_DIR = "research/evidence/loc-statutes-and-authorities-2026-11-18"

LLSL_CATALOG_FILENAME = "llsl-volumes-1-64-catalog.json"
LLSL_CATALOG_SHA256 = "sha256:160b009b925adaa29fb93a2dfe8d43de56cf28727ddc5ec2ae143da171bb3268"
LLSL_CATALOG_BYTE_LENGTH = 104_453

LLSL_OCR_MANIFEST_FILENAME = "llsl-ocr-verification-manifest.json"
LLSL_OCR_MANIFEST_SHA256 = "sha256:5f34b6f415997d926c5c71ba6456610cc73df981c1dcd2eb51b15f24295337c7"
LLSL_OCR_MANIFEST_BYTE_LENGTH = 65_671

MIN_PRE1951_VOLUME = 1
MAX_PRE1951_VOLUME = 64

PdfResolutionStatus = Literal[
    "single_volume_pdf",
    "narrowed_by_year",
    "ambiguous_multi_part_volume",
    "unresolved_contradictory_filters",
]
PageStemKind = Literal["arabic", "roman", "unnumbered"]

_ARABIC_STEM_RE = re.compile(r"^(\d{4})(\d{4})$")
_ROMAN_STEM_RE = re.compile(r"^(\d{4})r(\d{3})$")
_SESSION_LAW_KEY_RE = re.compile(r"^((?:1[789]|20)\d{2}):([1-9]\d*)$")
_SPLIT_SMALLCAPS_SEC_RE = re.compile(r"\bS\s+EC(TION)?\b")
_SPLIT_SMALLCAPS_CH_RE = re.compile(r"\bC\s+(HAP(?:TER)?|HS?)\b")

_LEGACY_TYPE1_BASEFONT_PREFIXES = (
    "/Times-",
    "/Helvetica",
    "/Courier",
)
_ROMAN_NUMERAL_TABLE: tuple[tuple[int, str], ...] = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)
_ANY_ACT_HEADING_RE = re.compile(
    r"(?:\[\s*C\s*HAPTER\s+[0-9IVXLCDM]+\.?[\]\d]\s*(?=AN\s+ACT|A\s+N\s+A\s+C\s+T|JOINT\s+RESOLUTION|J\s*OINT)"
    r"|\[\s*C\s*HAPTER\s+[0-9IVXLCDM]+\.?\s*\]"
    r"|\bC\s*(?:[\]\[]\s*)?(?:HAP|HAPTER|AP|RAP)\.\s*[0-9IVXLCDM]+(?:\s+[IVXLCDM]+)*\b)",
    re.IGNORECASE,
)


class LocStatutesError(ValueError):
    """Raised when a pinned Statutes at Large manifest drifts or an input is invalid."""


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze_json(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _verify_pinned_bytes(path: Path, *, expected_sha256: str, expected_bytes: int, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise LocStatutesError(f"pinned {label} is missing or not a regular file: {path}")
    payload = path.read_bytes()
    observed_sha = "sha256:" + hashlib.sha256(payload).hexdigest()
    if len(payload) != expected_bytes or observed_sha != expected_sha256:
        raise LocStatutesError(
            f"pinned {label} drifted: expected=({expected_bytes}, {expected_sha256}), "
            f"observed=({len(payload)}, {observed_sha})"
        )
    return payload


def int_to_roman(value: int) -> str:
    """Convert a positive integer (`1..3999`) to its exact uppercase Roman numeral."""

    if isinstance(value, bool) or not isinstance(value, int) or not (1 <= value <= 3999):
        raise LocStatutesError(f"Roman numeral conversion requires integer in 1..3999, got {value!r}")
    remaining = value
    parts: list[str] = []
    for arabic, roman in _ROMAN_NUMERAL_TABLE:
        while remaining >= arabic:
            parts.append(roman)
            remaining -= arabic
    return "".join(parts)


@dataclass(frozen=True, slots=True)
class LlslPdfResource:
    """One Congress-, session-, or part-level PDF published under an ``llsl-v*`` volume."""

    caption: str
    filename: str
    published_pdf_url: str
    normalized_pdf_url: str
    congress: int | None
    session_start: int | None
    session_end: int | None
    part_tag: str | None
    caption_year_start: int | None
    caption_year_end: int | None
    year_start: int | None
    year_end: int | None


@dataclass(frozen=True, slots=True)
class LlsalvolResource:
    """One page-segmented ``llsalvol`` digital object backing IIIF images and ALTO XML."""

    url: str
    segments: int
    caption: str


@dataclass(frozen=True, slots=True)
class LlslVolumeEntry:
    """Complete catalogue entry for one pre-1951 Statutes at Large volume (1..64)."""

    volume: int
    shelf_id: str
    item_url: str
    title: str
    date: str | None
    pdf_granularity: Literal["single_volume_pdf", "multi_congress_or_part_pdfs"]
    llsalvol_resources: tuple[LlsalvolResource, ...]
    pdf_resources: tuple[LlslPdfResource, ...]


@dataclass(frozen=True, slots=True)
class LocStatutesResolution:
    """Deterministic LoC resource resolution for a pre-1951 Statutes at Large citation."""

    volume: int
    statutes_at_large_page: int | None
    enactment_year: int | None
    item_url: str
    llsalvol_urls: tuple[str, ...]
    llsalvol_is_single_object: bool
    pdf_resolution_status: PdfResolutionStatus
    candidate_pdfs: tuple[LlslPdfResource, ...]

    @property
    def unique_pdf(self) -> LlslPdfResource | None:
        """Return the single resolved PDF when unambiguous, else ``None``."""
        return self.candidate_pdfs[0] if len(self.candidate_pdfs) == 1 else None


@dataclass(frozen=True, slots=True)
class LlsalvolPageStem:
    """Parsed 8-character METS/ALTO page stem from ``llsalvol`` (e.g. ``06940570``, ``0041r045``, ``0043r000``)."""

    stem: str
    scan_frame: int
    kind: PageStemKind
    page_number: int | None


@dataclass(frozen=True, slots=True)
class LlslPageOcrLayers:
    """Font-separated OCR text layers and running-header bands from one page of an ``llsl`` PDF."""

    page_number: int
    layer1_type1_text: str
    layer2_invisible_ocr_text: str
    other_font_text: str
    layer1_header_text: str
    layer1_footer_text: str
    layer2_header_text: str
    layer2_footer_text: str
    has_legacy_type1_layer: bool
    has_invisible_ocr_layer: bool
    uses_invisible_render_mode_3tr: bool
    font_names: tuple[str, ...]
    other_font_names: tuple[str, ...]

    @property
    def has_dual_ocr_collision(self) -> bool:
        """True when both the legacy Type 1 pass and the 2021 ``/InvisibleOCR`` pass carry text."""
        return bool(self.layer1_type1_text.strip() and self.layer2_invisible_ocr_text.strip())


@dataclass(frozen=True, slots=True)
class LlslLayerCitationScore:
    """Folio-, chapter-, and act-scoped citation verification result for one OCR layer."""

    folio_in_running_header: bool
    chapter_in_running_header: bool
    chapter_heading_strict: bool
    chapter_heading_tolerant: bool
    chapter_bound: bool
    section_in_act_strict: bool | None
    section_in_act_split_tolerant: bool | None
    full_citation_bound_strict: bool
    full_citation_bound_normalized: bool


@cache
def load_llsl_catalog(repo_root: Path | None = None) -> Mapping[int, LlslVolumeEntry]:
    """Load and SHA-256-verify the immutable 64-volume LoC Statutes at Large catalogue."""

    root = _default_repo_root() if repo_root is None else Path(repo_root)
    path = root / EVIDENCE_RELATIVE_DIR / LLSL_CATALOG_FILENAME
    raw = _verify_pinned_bytes(
        path,
        expected_sha256=LLSL_CATALOG_SHA256,
        expected_bytes=LLSL_CATALOG_BYTE_LENGTH,
        label=LLSL_CATALOG_FILENAME,
    )
    doc = json.loads(raw.decode("utf-8"))
    by_vol: dict[int, LlslVolumeEntry] = {}
    for row in doc["volumes"]:
        vnum = int(row["volume"])
        by_vol[vnum] = LlslVolumeEntry(
            volume=vnum,
            shelf_id=row["shelf_id"],
            item_url=row["item_url"],
            title=row["title"],
            date=row.get("date"),
            pdf_granularity=row["pdf_granularity"],
            llsalvol_resources=tuple(
                LlsalvolResource(url=s["url"], segments=int(s["segments"]), caption=s.get("caption") or "")
                for s in row["llsalvol_resources"]
            ),
            pdf_resources=tuple(
                LlslPdfResource(
                    caption=p["caption"],
                    filename=p["filename"],
                    published_pdf_url=p["published_pdf_url"],
                    normalized_pdf_url=p["normalized_pdf_url"],
                    congress=p["congress"],
                    session_start=p["session_start"],
                    session_end=p["session_end"],
                    part_tag=p["part_tag"],
                    caption_year_start=p["caption_year_start"],
                    caption_year_end=p["caption_year_end"],
                    year_start=p["year_start"],
                    year_end=p["year_end"],
                )
                for p in row["pdf_resources"]
            ),
        )
    return MappingProxyType(by_vol)


@cache
def load_llsl_ocr_verification_manifest(repo_root: Path | None = None) -> Mapping[str, Any]:
    """Load and SHA-256-verify the immutable 10-PDF / 16-specimen OCR verification manifest."""

    root = _default_repo_root() if repo_root is None else Path(repo_root)
    path = root / EVIDENCE_RELATIVE_DIR / LLSL_OCR_MANIFEST_FILENAME
    raw = _verify_pinned_bytes(
        path,
        expected_sha256=LLSL_OCR_MANIFEST_SHA256,
        expected_bytes=LLSL_OCR_MANIFEST_BYTE_LENGTH,
        label=LLSL_OCR_MANIFEST_FILENAME,
    )
    return _freeze_json(json.loads(raw.decode("utf-8")))


def parse_enactment_year_from_table3_key(table3_key: str | None) -> int | None:
    """Extract the 4-digit enactment year from a pre-1957 ``YYYY:chapter`` Table III key."""

    if not table3_key:
        return None
    m = _SESSION_LAW_KEY_RE.fullmatch(table3_key.strip())
    return int(m.group(1)) if m is not None else None


def resolve_statutes_volume(
    volume: int,
    *,
    statutes_at_large_page: int | None = None,
    enactment_year: int | None = None,
    table3_key: str | None = None,
    congress: int | None = None,
    catalog: Mapping[int, LlslVolumeEntry] | None = None,
) -> LocStatutesResolution:
    """Resolve a pre-1951 ``(volume[, page, year, table3_key, congress])`` citation to LoC resources.

    Never guesses across multiple Congress/part PDFs and never silently drops a
    contradictory filter:
    - Each PDF's ``year_start..year_end`` covers its full constitutional
      Congress term in addition to LoC's (often incomplete) caption years, so
      autumn-session acts such as ``1797:1`` on ``1 Stat. 536`` retain both
      ``llsl-c4.pdf`` and ``llsl-c5.pdf`` unless ``congress=5`` is supplied.
    - When ``congress``, ``enactment_year``, and/or ``table3_key`` contradict
      each other or the volume's PDFs, ``candidate_pdfs`` is ``()`` and
      ``pdf_resolution_status`` is ``"unresolved_contradictory_filters"``.
    """

    if isinstance(volume, bool) or not isinstance(volume, int) or not (MIN_PRE1951_VOLUME <= volume <= MAX_PRE1951_VOLUME):
        raise LocStatutesError(
            f"pre-1951 LoC Statutes at Large resolver covers Volumes {MIN_PRE1951_VOLUME}..{MAX_PRE1951_VOLUME}, "
            f"got {volume!r}"
        )
    if statutes_at_large_page is not None and (
        isinstance(statutes_at_large_page, bool)
        or not isinstance(statutes_at_large_page, int)
        or statutes_at_large_page <= 0
    ):
        raise LocStatutesError(f"statutes_at_large_page must be a positive integer when provided, got {statutes_at_large_page!r}")
    if enactment_year is not None and (isinstance(enactment_year, bool) or not isinstance(enactment_year, int)):
        raise LocStatutesError(f"enactment_year must be an integer when provided, got {enactment_year!r}")
    if congress is not None and (isinstance(congress, bool) or not isinstance(congress, int) or congress <= 0):
        raise LocStatutesError(f"congress must be a positive integer when provided, got {congress!r}")

    cat = load_llsl_catalog() if catalog is None else catalog
    entry = cat[volume]
    llsalvol_urls = tuple(r.url for r in entry.llsalvol_resources)
    llsalvol_single = len(entry.llsalvol_resources) == 1

    key_year = parse_enactment_year_from_table3_key(table3_key)
    if table3_key is not None and key_year is None:
        raise LocStatutesError(f"invalid pre-1951 YYYY:chapter table3_key: {table3_key!r}")
    if enactment_year is not None and key_year is not None and enactment_year != key_year:
        return LocStatutesResolution(
            volume=volume,
            statutes_at_large_page=statutes_at_large_page,
            enactment_year=enactment_year,
            item_url=entry.item_url,
            llsalvol_urls=llsalvol_urls,
            llsalvol_is_single_object=llsalvol_single,
            pdf_resolution_status="unresolved_contradictory_filters",
            candidate_pdfs=(),
        )

    is_session_law = key_year is not None
    effective_year = enactment_year if enactment_year is not None else key_year
    candidates = entry.pdf_resources

    if is_session_law:
        # Vol. 6 (Private Laws) has part_tag="vol-6-private" as its sole session-law PDF;
        # only filter out supplementary codification/treaty parts when primary session-law PDFs exist.
        primary = tuple(p for p in candidates if p.part_tag is None)
        if primary:
            candidates = primary
    if congress is not None:
        candidates = tuple(p for p in candidates if p.congress == congress)
    if effective_year is not None:
        candidates = tuple(
            p
            for p in candidates
            if p.year_start is not None
            and p.year_end is not None
            and p.year_start <= effective_year <= p.year_end
        )

    if not candidates:
        status: PdfResolutionStatus = "unresolved_contradictory_filters"
    elif len(candidates) == 1:
        status = "single_volume_pdf" if len(entry.pdf_resources) == 1 else "narrowed_by_year"
    else:
        status = "ambiguous_multi_part_volume"

    return LocStatutesResolution(
        volume=volume,
        statutes_at_large_page=statutes_at_large_page,
        enactment_year=effective_year,
        item_url=entry.item_url,
        llsalvol_urls=llsalvol_urls,
        llsalvol_is_single_object=llsalvol_single,
        pdf_resolution_status=status,
        candidate_pdfs=candidates,
    )


def parse_llsalvol_page_stem(stem_or_filename: str) -> LlsalvolPageStem:
    """Parse an 8-character ``llsalvol`` METS/ALTO page stem into ``(scan_frame, kind, page_number)``.

    Examples from ``item/llsl-v1/?fo=json`` and ``item/llsl-v52/?fo=json``:
    - ``"06940570.alto.xml"`` -> frame 694, ``kind="arabic"``, printed page 570 (``1 Stat. 570``)
    - ``"0041r045"`` -> frame 41, ``kind="roman"``, Roman page 45 (``xlv``)
    - ``"0043r000.alto.xml"`` -> frame 43, ``kind="unnumbered"``, ``page_number=None`` (Vol. 52 seq 43 separator)
    - ``"00010000.jp2"`` -> frame 1, ``kind="unnumbered"``, ``page_number=None``
    """

    stem = stem_or_filename.rsplit("/", 1)[-1].split(".", 1)[0]
    m_roman = _ROMAN_STEM_RE.fullmatch(stem)
    if m_roman is not None:
        frame = int(m_roman.group(1))
        rpage = int(m_roman.group(2))
        if frame <= 0:
            raise LocStatutesError(f"invalid non-positive scan_frame in Roman llsalvol stem: {stem_or_filename!r}")
        if rpage == 0:
            return LlsalvolPageStem(stem=stem, scan_frame=frame, kind="unnumbered", page_number=None)
        return LlsalvolPageStem(stem=stem, scan_frame=frame, kind="roman", page_number=rpage)

    m_arabic = _ARABIC_STEM_RE.fullmatch(stem)
    if m_arabic is not None:
        frame = int(m_arabic.group(1))
        apage = int(m_arabic.group(2))
        if frame <= 0:
            raise LocStatutesError(f"invalid zero scan_frame in llsalvol stem: {stem_or_filename!r}")
        if apage == 0:
            return LlsalvolPageStem(stem=stem, scan_frame=frame, kind="unnumbered", page_number=None)
        return LlsalvolPageStem(stem=stem, scan_frame=frame, kind="arabic", page_number=apage)

    raise LocStatutesError(f"unrecognized llsalvol 8-character page stem: {stem_or_filename!r}")


def llsalvol_segment_urls(
    volume: int,
    *,
    stem: str,
    sequence_index_1based: int,
    part_suffix: str = "",
) -> dict[str, str]:
    """Construct deterministic viewer, IIIF JPEG, JP2, and ALTO XML URLs for one ``llsalvol`` page."""

    if isinstance(volume, bool) or not isinstance(volume, int) or not (MIN_PRE1951_VOLUME <= volume <= MAX_PRE1951_VOLUME):
        raise LocStatutesError(f"volume out of range 1..64: {volume!r}")
    if volume == 18 and part_suffix not in {"a", "b", "c", "d", "e"}:
        raise LocStatutesError("Volume 18 requires part_suffix in {'a', 'b', 'c', 'd', 'e'}")
    if volume == 44 and part_suffix not in {"", "a"}:
        raise LocStatutesError("Volume 44 accepts only part_suffix in {'', 'a'}")
    if volume not in {18, 44} and part_suffix:
        raise LocStatutesError(f"only Volumes 18 and 44 use part_suffix, got {part_suffix!r} for Volume {volume}")
    if isinstance(sequence_index_1based, bool) or not isinstance(sequence_index_1based, int) or sequence_index_1based <= 0:
        raise LocStatutesError(f"sequence_index_1based must be >= 1, got {sequence_index_1based!r}")

    parsed = parse_llsalvol_page_stem(stem)
    obj_id = f"llsal_{volume:03d}{part_suffix}"
    return {
        "viewer_url": f"https://www.loc.gov/resource/llsalvol.{obj_id}/?sp={sequence_index_1based}",
        "alto_xml_url": f"https://tile.loc.gov/storage-services/service/ll/llsalvol/{obj_id}/{parsed.stem}.alto.xml",
        "jp2_url": f"https://tile.loc.gov/storage-services/service/ll/llsalvol/{obj_id}/{parsed.stem}.jp2",
        "iiif_full_jpg_url": f"https://tile.loc.gov/image-services/iiif/service:ll:llsalvol:{obj_id}:{parsed.stem}/full/pct:100/0/default.jpg",
    }


def normalize_split_smallcaps_designators(text: str) -> str:
    """Rejoin initial capitals split by Foxit's 2021 small-caps OCR (``'S EC.'`` -> ``'SEC.'``)."""

    out = _SPLIT_SMALLCAPS_SEC_RE.sub(lambda m: "SEC" + (m.group(1) or ""), text)
    return _SPLIT_SMALLCAPS_CH_RE.sub(lambda m: "C" + m.group(1), out)


def _is_legacy_type1_font(font_dict: Mapping[str, Any] | None) -> bool:
    if not font_dict:
        return False
    subtype = str(font_dict.get("/Subtype") or "")
    base = str(font_dict.get("/BaseFont") or "")
    if "InvisibleOCR" in base:
        return False
    return subtype == "/Type1" or base.startswith(_LEGACY_TYPE1_BASEFONT_PREFIXES)


def _extract_header_footer_bands(positioned: list[tuple[float, float, str]]) -> tuple[str, str]:
    if not positioned:
        return "", ""
    max_ry = max(ry for ry, _, _ in positioned)
    min_ry = min(ry for ry, _, _ in positioned)
    header = " ".join(
        tok
        for _, _, tok in sorted(
            (x, idx, tok) for idx, (ry, x, tok) in enumerate(positioned) if ry >= max_ry - 0.025
        )
    )
    footer = " ".join(
        tok
        for _, _, tok in sorted(
            (x, idx, tok)
            for idx, (ry, x, tok) in enumerate(positioned)
            if ry <= min_ry + 0.015 and ry <= 0.12
        )
    )
    return header, footer


def extract_llsl_pdf_ocr_layers(pdf_source: bytes | Path | PdfReader, page_number: int) -> LlslPageOcrLayers:
    """Extract and separate the legacy Type 1 and 2021 ``/InvisibleOCR`` layers on a 1-based PDF page.

    Accepts an existing :class:`pypdf.PdfReader` so multi-page callers reuse a
    single parsed xref table per PDF file.
    """

    if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number <= 0:
        raise LocStatutesError(f"page_number must be a 1-based positive integer, got {page_number!r}")

    if isinstance(pdf_source, PdfReader):
        reader = pdf_source
    elif isinstance(pdf_source, bytes):
        reader = PdfReader(io.BytesIO(pdf_source))
    else:
        reader = PdfReader(str(pdf_source))

    if page_number > len(reader.pages):
        raise LocStatutesError(f"page_number {page_number} exceeds PDF page count {len(reader.pages)}")

    page = reader.pages[page_number - 1]
    mediabox = page.mediabox
    y0 = float(mediabox.bottom)
    page_height = float(mediabox.top) - y0

    fonts_seen: set[str] = set()
    other_fonts: set[str] = set()
    resources = page.get("/Resources")
    if resources:
        res_obj = resources.get_object()
        font_map = res_obj.get("/Font")
        if font_map:
            for fv in font_map.get_object().values():
                fobj = fv.get_object()
                base = str(fobj.get("/BaseFont") or "")
                if base:
                    fonts_seen.add(base)
                    if "InvisibleOCR" not in base and not _is_legacy_type1_font(fobj):
                        other_fonts.add(base)

    uses_3tr = False
    contents = page.get_contents()
    if contents is not None:
        stream = ContentStream(contents, reader)
        uses_3tr = any(op == b"Tr" and bool(operands) and int(operands[0]) == 3 for operands, op in stream.operations)

    layer1_parts: list[str] = []
    layer2_parts: list[str] = []
    other_parts: list[str] = []
    layer1_pos: list[tuple[float, float, str]] = []
    layer2_pos: list[tuple[float, float, str]] = []

    def _visitor(text: str, cm: Any, tm: Any, font_dict: Any, _font_size: float) -> None:
        if not text:
            return
        fdict = font_dict or {}
        base = str(fdict.get("/BaseFont") or "")
        is_inv = "InvisibleOCR" in base
        is_t1 = _is_legacy_type1_font(fdict)
        if is_inv:
            layer2_parts.append(text)
        elif is_t1:
            layer1_parts.append(text)
        else:
            other_parts.append(text)
            if base:
                other_fonts.add(base)

        stripped = text.strip()
        if stripped and page_height > 0 and (is_inv or is_t1):
            x = float(cm[0] * tm[4] + cm[2] * tm[5] + cm[4])
            y = float(cm[1] * tm[4] + cm[3] * tm[5] + cm[5])
            rel_y = (y - y0) / page_height
            (layer2_pos if is_inv else layer1_pos).append((rel_y, x, stripped))

    page.extract_text(visitor_text=_visitor)
    l1 = " ".join("".join(layer1_parts).split())
    l2 = " ".join("".join(layer2_parts).split())
    other_txt = " ".join("".join(other_parts).split())
    h1, f1 = _extract_header_footer_bands(layer1_pos)
    h2, f2 = _extract_header_footer_bands(layer2_pos)

    return LlslPageOcrLayers(
        page_number=page_number,
        layer1_type1_text=l1,
        layer2_invisible_ocr_text=l2,
        other_font_text=other_txt,
        layer1_header_text=h1,
        layer1_footer_text=f1,
        layer2_header_text=h2,
        layer2_footer_text=f2,
        has_legacy_type1_layer=bool(l1),
        has_invisible_ocr_layer=bool(l2),
        uses_invisible_render_mode_3tr=uses_3tr,
        font_names=tuple(sorted(fonts_seen)),
        other_font_names=tuple(sorted(other_fonts)),
    )


def score_llsl_layer_citation(
    *,
    body_text: str,
    header_text: str,
    footer_text: str,
    statutes_at_large_page: int,
    expected_chapter: int,
    expected_section: str | None = None,
    is_continuation_page: bool = False,
) -> LlslLayerCitationScore:
    """Score one OCR layer with folio, chapter, and section checks bound to the printed header and act slice.

    - ``folio_in_running_header`` checks only the physical top running-header band
      (excluding ``{vol} STAT.]`` and ``{n}TH CONG.`` tokens), falling back to the
      bottom folio band solely on session-opening title pages whose top band has
      no running ``CONG``/``STAT``/``SESS`` header. Body numbers (e.g. ``"$4 per
      day"`` on ``51 Stat. 3``) never satisfy a folio check.
    - ``chapter_heading_strict`` / ``chapter_heading_tolerant`` check only the
      exact Arabic ``expected_chapter`` or ``int_to_roman(expected_chapter)``
      (never arbitrary ``[IVXLCDM]+`` Roman numerals).
    - ``section_in_act_*`` slices ``body_text`` from the target act's heading up
      to the next act heading on the same page, preventing ``Sec. 2`` in an
      adjacent chapter (such as ``ch. 162`` on ``23 Stat. 332``) from satisfying
      a query for ``ch. 163`` or ``ch. 164``.
    """

    if statutes_at_large_page <= 0 or expected_chapter <= 0:
        raise LocStatutesError("statutes_at_large_page and expected_chapter must be positive integers")

    folio_re = re.compile(
        rf"(?<![$0-9.-])\b{statutes_at_large_page}\b(?!\s*S\s*TAT|\s*C\s*O\s*N\s*G)",
        re.IGNORECASE,
    )
    has_running_hdr = bool(re.search(r"C\s*O\s*N\s*G|S\s*TAT|S\s*ESS", header_text, re.IGNORECASE))
    if has_running_hdr:
        folio_ok = bool(folio_re.search(header_text))
    else:
        folio_ok = bool(folio_re.search(header_text) or folio_re.search(footer_text))

    ch_str = str(expected_chapter)
    roman = int_to_roman(expected_chapter)
    roman_split = r"\s*".join(list(roman))

    hdr_chapter_ok = False
    for m in re.finditer(r"\b[CO]\s*[A-Z]{0,3}[.\s]+([0-9,\s–—-]+)", header_text, re.IGNORECASE):
        seg = m.group(1)
        if re.search(rf"\b{ch_str}\b", seg):
            hdr_chapter_ok = True
        for rm in re.finditer(r"(\d+)\s*[-–—]\s*(\d+)", seg):
            if int(rm.group(1)) <= expected_chapter <= int(rm.group(2)):
                hdr_chapter_ok = True

    strict_head_re = re.compile(
        rf"(?:\[\s*CHAPTER\s+{ch_str}\.?\s*\]|\b(?:CHAP|CHAPTER|CAP)\.\s*(?:{ch_str}|{roman})\b)",
        re.IGNORECASE,
    )
    # Tolerant heading allows spaced small-caps ('C HAP.', 'C ] HAP.', 'C RAP.') or closing-bracket ']' OCR'd as '1'/'4' before AN ACT.
    tolerant_head_re = re.compile(
        rf"(?:\[\s*C\s*HAPTER\s+{ch_str}\.?\s*\]"
        rf"|\[\s*C\s*HAPTER\s+{ch_str}[14]\s*(?=AN\s+ACT|A\s+N\s+A\s+C\s+T|JOINT\s+RESOLUTION)"
        rf"|\bC\s*(?:[\]\[]\s*)?(?:HAP|HAPTER|AP|RAP)\.\s*(?:{ch_str}|{roman_split})\b)",
        re.IGNORECASE,
    )

    m_strict_head = strict_head_re.search(body_text)
    m_tol_head = tolerant_head_re.search(body_text)

    chap_strict = bool(m_strict_head) or (is_continuation_page and hdr_chapter_ok)
    chap_tol = bool(m_tol_head) or (is_continuation_page and hdr_chapter_ok)
    chap_bound = chap_tol or hdr_chapter_ok

    if expected_section is None:
        sec_strict: bool | None = None
        sec_tol: bool | None = None
        full_strict = folio_ok and chap_strict
        full_norm = folio_ok and chap_tol
    else:
        if m_tol_head is not None:
            start = m_tol_head.end()
            m_next = _ANY_ACT_HEADING_RE.search(body_text, start)
            act_slice = body_text[start : m_next.start() if m_next else len(body_text)]
        elif is_continuation_page and hdr_chapter_ok:
            m_next = _ANY_ACT_HEADING_RE.search(body_text)
            act_slice = body_text[: m_next.start() if m_next else len(body_text)]
        else:
            act_slice = ""

        sec_strict = bool(
            re.search(rf"\b(?:SEC|SECTION)\.?\s*{re.escape(expected_section)}\b", act_slice, re.IGNORECASE)
        )
        sec_tol = bool(
            re.search(rf"\bS\s*EC(?:TION)?\.?\s*{re.escape(expected_section)}\b", act_slice, re.IGNORECASE)
        )
        full_strict = folio_ok and chap_strict and sec_strict
        full_norm = folio_ok and chap_tol and sec_tol

    return LlslLayerCitationScore(
        folio_in_running_header=folio_ok,
        chapter_in_running_header=hdr_chapter_ok,
        chapter_heading_strict=chap_strict,
        chapter_heading_tolerant=chap_tol,
        chapter_bound=chap_bound,
        section_in_act_strict=sec_strict,
        section_in_act_split_tolerant=sec_tol,
        full_citation_bound_strict=full_strict,
        full_citation_bound_normalized=full_norm,
    )


__all__ = [
    "EVIDENCE_RELATIVE_DIR",
    "LLSL_CATALOG_BYTE_LENGTH",
    "LLSL_CATALOG_FILENAME",
    "LLSL_CATALOG_SHA256",
    "LLSL_OCR_MANIFEST_BYTE_LENGTH",
    "LLSL_OCR_MANIFEST_FILENAME",
    "LLSL_OCR_MANIFEST_SHA256",
    "MAX_PRE1951_VOLUME",
    "MIN_PRE1951_VOLUME",
    "LlsalvolPageStem",
    "LlsalvolResource",
    "LlslLayerCitationScore",
    "LlslPageOcrLayers",
    "LlslPdfResource",
    "LlslVolumeEntry",
    "LocStatutesError",
    "LocStatutesResolution",
    "PageStemKind",
    "PdfResolutionStatus",
    "extract_llsl_pdf_ocr_layers",
    "int_to_roman",
    "llsalvol_segment_urls",
    "load_llsl_catalog",
    "load_llsl_ocr_verification_manifest",
    "normalize_split_smallcaps_designators",
    "parse_enactment_year_from_table3_key",
    "parse_llsalvol_page_stem",
    "resolve_statutes_volume",
    "score_llsl_layer_citation",
]
