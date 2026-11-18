"""Library of Congress pre-1951 Statutes at Large (Vols. 1-64) catalog resolver and dual-OCR reader.

GovInfo's ``STATUTE`` collection begins at Volume 65 (1951). For Volumes 1-64
(1789-1950) -- 2,097 rows of ``usc-popular-names.parquet`` and 33,485 rows of
``usc-act-sections.parquet`` in :mod:`refspec.registry.act_resolution` -- the
primary federal digital repository is the Library of Congress
``united-states-statutes-at-large`` collection.

Two structural properties established from the primary catalogue and 10
SHA-256-pinned PDFs (19,555 pages across Vols. 1-62) govern every function here:

1. **Catalogue lookup is required for PDF URLs, and multi-part volumes cannot
   be disambiguated from ``(volume, page)`` alone.** Volume item URLs
   (``llsl-v1`` .. ``llsl-v64``) are arithmetic across all 64 volumes, and
   ``llsalvol`` page-turner resources (``llsal_001`` .. ``llsal_064``, 69
   objects total) are single-object arithmetic for 62 of 64 volumes (Volume 18
   splits into ``018a`` .. ``018e``; Volume 44 splits into ``044`` and
   ``044a`` for the 1925 U.S. Code). By contrast, ``tile.loc.gov`` PDF slugs
   are keyed by Congress/session or subject (``llsl-c38.pdf``,
   ``llsl-c75s2.pdf``, ``llsl-vol-6-private.pdf``), and 12 volumes (Vols. 1-5,
   9-12, 18, 20, 44) publish 2 to 7 Congress- or part-level PDFs (97 PDFs
   total; never per-chapter PDFs) without page-range bounds in the catalogue
   metadata. When a multi-PDF volume is queried without narrowing metadata (or
   when a Congress-transition calendar year such as ``1807`` overlaps adjacent
   Congress PDFs, or a bare year without a ``YYYY:chapter`` session-law key
   also matches supplementary parts in Vols. 18, 20, or 44),
   :func:`resolve_statutes_volume` returns all matching candidate PDFs with
   ``pdf_resolution_status="ambiguous_multi_part_volume"`` rather than guessing.
2. **Every sampled ``llsl`` PDF carries two overlaid invisible OCR layers.**
   Each page paints a 2007 Type 1 font pass (``Times-Roman``/``Bold``/``Italic``,
   ``WinAnsiEncoding``, ``3 Tr``) followed by a July 2021 ``Foxit FXPDFA 1.2`` /
   ``PDF Compressor 8.2.12.20`` Type 0 CID pass (``/InvisibleOCR``,
   ``Identity-H``, ``3 Tr``). Spatial PDF text extractors (``pdftotext`` default,
   ``-layout``, ``-bbox``) interleave both layers on every line. Separating by
   ``/BaseFont`` via :func:`extract_llsl_pdf_ocr_layers` isolates each pass
   cleanly.

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
from typing import Any, Literal

from pypdf import PdfReader

EVIDENCE_RELATIVE_DIR = "research/evidence/loc-statutes-and-authorities-2026-11-18"

LLSL_CATALOG_FILENAME = "llsl-volumes-1-64-catalog.json"
LLSL_CATALOG_SHA256 = "sha256:712b2b572eddaf0b95329576366a37e523717042090957096ccf602553fba351"
LLSL_CATALOG_BYTE_LENGTH = 92_517

LLSL_OCR_MANIFEST_FILENAME = "llsl-ocr-verification-manifest.json"
LLSL_OCR_MANIFEST_SHA256 = "sha256:2e4984c5c0790ae707786c06c6de821717e06aadcd1d338e68423aa4483f29fc"
LLSL_OCR_MANIFEST_BYTE_LENGTH = 50_833

MIN_PRE1951_VOLUME = 1
MAX_PRE1951_VOLUME = 64

PdfResolutionStatus = Literal[
    "single_volume_pdf",
    "narrowed_by_year",
    "ambiguous_multi_part_volume",
]
PageStemKind = Literal["arabic", "roman", "unnumbered"]

_ARABIC_STEM_RE = re.compile(r"^(\d{4})(\d{4})$")
_ROMAN_STEM_RE = re.compile(r"^(\d{4})r(\d{3})$")
_SESSION_LAW_KEY_RE = re.compile(r"^((?:1[789]|20)\d{2}):([1-9]\d*)$")
_SPLIT_SMALLCAPS_SEC_RE = re.compile(r"\bS\s+EC(TION)?\b")
_SPLIT_SMALLCAPS_CH_RE = re.compile(r"\bC\s+(HAP(?:TER)?|HS?)\b")


class LocStatutesError(ValueError):
    """Raised when a pinned Statutes at Large manifest drifts or an input is invalid."""


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


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
    """Parsed 8-character METS/ALTO page stem from ``llsalvol`` (e.g. ``06940570`` or ``0041r045``)."""

    stem: str
    scan_frame: int
    kind: PageStemKind
    page_number: int | None


@dataclass(frozen=True, slots=True)
class LlslPageOcrLayers:
    """Font-separated OCR text layers extracted from one page of an LoC ``llsl`` PDF."""

    page_number: int
    layer1_type1_text: str
    layer2_invisible_ocr_text: str
    has_legacy_type1_layer: bool
    has_invisible_ocr_layer: bool
    font_names: tuple[str, ...]

    @property
    def has_dual_ocr_collision(self) -> bool:
        """True when both the 2007 Type 1 pass and the 2021 ``/InvisibleOCR`` pass carry text."""
        return bool(self.layer1_type1_text.strip() and self.layer2_invisible_ocr_text.strip())


@cache
def load_llsl_catalog(repo_root: Path | None = None) -> Mapping[int, LlslVolumeEntry]:
    """Load and SHA-256-verify the complete 64-volume LoC Statutes at Large catalogue."""

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
                    year_start=p["year_start"],
                    year_end=p["year_end"],
                )
                for p in row["pdf_resources"]
            ),
        )
    return by_vol


@cache
def load_llsl_ocr_verification_manifest(repo_root: Path | None = None) -> dict[str, Any]:
    """Load and SHA-256-verify the 10-PDF / 16-specimen multi-era OCR verification manifest."""

    root = _default_repo_root() if repo_root is None else Path(repo_root)
    path = root / EVIDENCE_RELATIVE_DIR / LLSL_OCR_MANIFEST_FILENAME
    raw = _verify_pinned_bytes(
        path,
        expected_sha256=LLSL_OCR_MANIFEST_SHA256,
        expected_bytes=LLSL_OCR_MANIFEST_BYTE_LENGTH,
        label=LLSL_OCR_MANIFEST_FILENAME,
    )
    return json.loads(raw.decode("utf-8"))


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

    Never guesses across multiple Congress/part PDFs:
    - Single-PDF volumes (52/64) return ``"single_volume_pdf"``.
    - Multi-PDF volumes (12/64) narrow by ``congress`` (when supplied), by
      ``YYYY:chapter`` session-law flag (``table3_key`` excludes Revised
      Statutes / U.S. Code supplement parts whose ``part_tag`` is non-null),
      and by ``effective_year``. When narrowing leaves a single candidate PDF,
      ``pdf_resolution_status`` is ``"narrowed_by_year"``; otherwise it is
      ``"ambiguous_multi_part_volume"`` and all matching candidate PDFs are
      returned.
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
    if congress is not None and (isinstance(congress, bool) or not isinstance(congress, int) or congress <= 0):
        raise LocStatutesError(f"congress must be a positive integer when provided, got {congress!r}")

    key_year = parse_enactment_year_from_table3_key(table3_key)
    is_session_law = key_year is not None
    effective_year = enactment_year if enactment_year is not None else key_year
    cat = load_llsl_catalog() if catalog is None else catalog
    entry = cat[volume]
    pdfs = entry.pdf_resources

    if len(pdfs) == 1:
        status: PdfResolutionStatus = "single_volume_pdf"
        selected = pdfs
    else:
        candidates = pdfs
        if is_session_law:
            session_only = tuple(p for p in candidates if p.part_tag is None)
            if session_only:
                candidates = session_only
        if congress is not None:
            cong_matches = tuple(p for p in candidates if p.congress == congress)
            if cong_matches:
                candidates = cong_matches
        if effective_year is not None:
            year_matches = tuple(
                p
                for p in candidates
                if p.year_start is not None
                and p.year_end is not None
                and p.year_start <= effective_year <= p.year_end
            )
            if year_matches:
                candidates = year_matches
        selected = candidates
        status = (
            "narrowed_by_year"
            if (len(selected) == 1 and (effective_year is not None or congress is not None))
            else "ambiguous_multi_part_volume"
        )

    return LocStatutesResolution(
        volume=volume,
        statutes_at_large_page=statutes_at_large_page,
        enactment_year=effective_year,
        item_url=entry.item_url,
        llsalvol_urls=tuple(r.url for r in entry.llsalvol_resources),
        llsalvol_is_single_object=(len(entry.llsalvol_resources) == 1),
        pdf_resolution_status=status,
        candidate_pdfs=selected,
    )


def parse_llsalvol_page_stem(stem_or_filename: str) -> LlsalvolPageStem:
    """Parse an 8-character ``llsalvol`` METS/ALTO page stem into ``(scan_frame, kind, page_number)``.

    Examples from ``item/llsl-v1/?fo=json`` and ``item/llsl-v52/?fo=json``:
    - ``"06940570.alto.xml"`` -> frame 694, ``kind="arabic"``, printed page 570 (``1 Stat. 570``)
    - ``"0041r045"`` -> frame 41, ``kind="roman"``, Roman page 45 (``xlv``)
    - ``"00010000.jp2"`` -> frame 1, ``kind="unnumbered"``, ``page_number=None``
    """

    stem = stem_or_filename.rsplit("/", 1)[-1].split(".", 1)[0]
    m_roman = _ROMAN_STEM_RE.fullmatch(stem)
    if m_roman is not None:
        frame = int(m_roman.group(1))
        rpage = int(m_roman.group(2))
        if frame <= 0 or rpage <= 0:
            raise LocStatutesError(f"invalid non-positive Roman llsalvol stem: {stem_or_filename!r}")
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


def extract_llsl_pdf_ocr_layers(pdf_source: bytes | Path, page_number: int) -> LlslPageOcrLayers:
    """Extract and separate the 2007 Type 1 and 2021 ``/InvisibleOCR`` layers on a 1-based PDF page."""

    if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number <= 0:
        raise LocStatutesError(f"page_number must be a 1-based positive integer, got {page_number!r}")

    reader = PdfReader(io.BytesIO(pdf_source) if isinstance(pdf_source, bytes) else str(pdf_source))
    if page_number > len(reader.pages):
        raise LocStatutesError(f"page_number {page_number} exceeds PDF page count {len(reader.pages)}")

    page = reader.pages[page_number - 1]
    fonts_seen: set[str] = set()
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

    layer1_parts: list[str] = []
    layer2_parts: list[str] = []

    def _visitor(text: str, _cm: Any, _tm: Any, font_dict: Any, _font_size: float) -> None:
        if not text:
            return
        base = str((font_dict or {}).get("/BaseFont") or "")
        if "InvisibleOCR" in base:
            layer2_parts.append(text)
        else:
            layer1_parts.append(text)

    page.extract_text(visitor_text=_visitor)
    l1 = " ".join("".join(layer1_parts).split())
    l2 = " ".join("".join(layer2_parts).split())
    has_inv_font = any("InvisibleOCR" in f for f in fonts_seen) or bool(l2)
    has_t1_font = any("InvisibleOCR" not in f for f in fonts_seen) or bool(l1)

    return LlslPageOcrLayers(
        page_number=page_number,
        layer1_type1_text=l1,
        layer2_invisible_ocr_text=l2,
        has_legacy_type1_layer=has_t1_font and bool(l1),
        has_invisible_ocr_layer=has_inv_font and bool(l2),
        font_names=tuple(sorted(fonts_seen)),
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
    "LlslPageOcrLayers",
    "LlslPdfResource",
    "LlslVolumeEntry",
    "LocStatutesError",
    "LocStatutesResolution",
    "PageStemKind",
    "PdfResolutionStatus",
    "extract_llsl_pdf_ocr_layers",
    "llsalvol_segment_urls",
    "load_llsl_catalog",
    "load_llsl_ocr_verification_manifest",
    "normalize_split_smallcaps_designators",
    "parse_enactment_year_from_table3_key",
    "parse_llsalvol_page_stem",
    "resolve_statutes_volume",
]
