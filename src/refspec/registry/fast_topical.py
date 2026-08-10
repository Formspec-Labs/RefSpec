"""OCLC FAST Topical bulk data and current change records for mapping-only use.

OCLC publishes a periodic RDF N-Triples snapshot plus chronological MARC
authority change files.  RefSpec reads those native formats directly.  The
October 2024 snapshot is preserved as exact publisher bytes through an exact
Wayback replay, and the four later change files are exact live OCLC bytes.
The legacy CSV reader remains for compatibility with earlier callers, but it
is not evidence for the real-data gate.

The catalog assigns FAST a mapping-only role: search expansion and reviewed
cross-vocabulary mappings, never a reserved classifier output slot and never
a promoted concept scheme. FAST does publish stable per-heading identifiers
(the "fst" id and its id.worldcat.org URI), so this module preserves them
exactly as observed instead of minting new identity. Every package built here
inherits the ``source_controlled_resource`` development-only usage ceiling,
which structurally forbids concept-scheme promotion and accepted-output use.

FAST (Faceted Application of Subject Terminology) Data is made available by
OCLC Online Computer Library Center, Inc. under the Open Data Commons
Attribution License (ODC-BY), which requires attribution.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import tempfile
import zipfile
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pymarc import Field, MARCReader

from refspec.registry.infrastructure.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)

FAST_PUBLISHER = "OCLC Online Computer Library Center, Inc."
FAST_LANDING_PAGE_URL = "https://www.oclc.org/research/areas/data-science/fast/download.html"
FAST_LICENSE_URL = "https://www.oclc.org/research/activities/fast/odcby.html"
# The official download landing page, captured 2026-08-04 through the
# project's Zyte transport after direct fetches were Cloudflare-blocked.
# Reference-only provenance for the artifact catalog the page publishes
# (fixture ``fast-download-landing-2026-08-04.html``); never parsed at runtime.
FAST_LANDING_PAGE_CAPTURE_SHA256 = "sha256:d9a49e0ddbaffde84ac6eae124b388b6748fc261bd7281a7e386aba54df1cd79"
FAST_LANDING_PAGE_CAPTURE_BYTE_LENGTH = 56_875
FAST_LANDING_PAGE_CAPTURE_RETRIEVED_AT = "2026-08-04T00:12:00Z"
# The official Topical bulk file WAS acquired once: the sibling spicy-regs
# fused-concept-registry run ingested ``FASTTopical.nt.zip`` and recorded this
# exact pin in ``output/fused-concept-registry-v1/manifest.json`` (retrieved
# 2026-07-27; raw bytes since deleted with that session's scratchpad). A
# future re-acquisition must match it or explain the publisher's change.
# Re-fetch attempts on 2026-08-04 failed: direct curl received a Cloudflare
# 403 and the Zyte raw-HTTP transport received HTTP 520 three times.
FAST_TOPICAL_BULK_NT_ZIP_URL = "https://researchworks.oclc.org/researchdata/fast/FASTTopical.nt.zip"
FAST_TOPICAL_BULK_NT_ZIP_SHA256 = "sha256:217826c90649895bfca71e81e2ed88919b2e061646ec42a185bc12d0bd3c19db"
FAST_TOPICAL_BULK_NT_ZIP_BYTE_LENGTH = 55_099_212
FAST_TOPICAL_BULK_NT_ZIP_RETRIEVED_AT = "2026-07-27"
FAST_TOPICAL_BULK_NT_ZIP_ARCHIVE_URL = (
    "https://web.archive.org/web/20250223102341id_/https://researchworks.oclc.org/researchdata/fast/FASTTopical.nt.zip"
)
FAST_CHANGES_URL = "https://fast.oclc.org/fastChanges/"
# NEW VERIFIED FINDING (2026-08-04): unlike the bulk-data host, OCLC's own
# Linked Data and searchFAST suggest API tier carries no bot wall and needs
# no key. Two channels were checked live and pinned below.
#
# (1) Per-term Linked Data: id.worldcat.org answers a numeric FAST id with
#     RDF/XML at the ``.rdf.xml`` path suffix and stable rdf:about URIs.
#     Only that suffix answered; ``.json``, ``.ttl``, and ``.jsonld`` all came
#     back HTTP 404 on the same live check.
FAST_TERM_RDF_URL_PATTERN = "https://id.worldcat.org/fast/{numeric_id}.rdf.xml"
FAST_TERM_RDF_CAPTURE_SHA256 = "sha256:88940a98a42dca5605f06aef661c07f3591dcc82be32dcd1fbcae2d782318553"
FAST_TERM_RDF_CAPTURE_BYTE_LENGTH = 3_806
FAST_TERM_RDF_CAPTURE_RETRIEVED_AT = "2026-08-04T00:50:00Z"

# (2) The searchFAST suggest API answers term-prefix lookups as CORS-open
#     JSON, also with no key.
FAST_SUGGEST_API_URL_PATTERN = (
    "https://fast.oclc.org/searchfast/fastsuggest?query={query}&queryIndex=suggestall&rows={rows}"
)
FAST_SUGGEST_CAPTURE_SHA256 = "sha256:309c71da16146beabb187199ce03716e7f2e5aec7a9585bc2dbcee1a5df661cd"
FAST_SUGGEST_CAPTURE_BYTE_LENGTH = 352
FAST_SUGGEST_CAPTURE_RETRIEVED_AT = "2026-08-04T00:50:00Z"

# The suggest API's response on 2026-08-04 carried an x-ratelimit-limit-day
# header value of 10,000. This was observed on that one response header, not
# published anywhere as OCLC's documented policy, so it may change without
# notice. At this ceiling a full-vocabulary crawl through the per-term
# channel would take weeks of continuous daily-capped calls rather than a
# single acquisition run.
FAST_SUGGEST_API_OBSERVED_DAILY_RATE_LIMIT = 10_000
FAST_URI_BASE = "http://id.worldcat.org/fast/"
FAST_IDENTIFIER_AUTHORITY_URI = FAST_URI_BASE
FAST_ATTRIBUTION_NOTICE = (
    "This work contains information from FAST (Faceted Application of Subject "
    "Terminology) Data which is made available by OCLC Online Computer Library "
    "Center, Inc. under the ODC Attribution License."
)

# Observed on the official download page on 2026-08-03; no CSV format is offered.
FAST_TOPICAL_OFFICIAL_BULK_FORMATS = ("marc", "marcxml", "ntriples")
# The project's documented full topical extract; individual captures pinned
# through this module are development-scale samples and will not match it.
FAST_TOPICAL_DOCUMENTED_ROW_COUNT = 440_599
FAST_TOPICAL_BASE_ACTIVE_COUNT = 440_612
FAST_TOPICAL_CURRENT_ACTIVE_COUNT = 441_127
FAST_TOPICAL_RESOURCE_ID = "fast-topical-facet"

ResourceUse = Literal["searchExpansion", "mappingReference"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_HEADER = ("fast_id", "uri", "heading")
_FAST_ID = re.compile(r"^fst(\d{6,10})$")
_CHUNK_BYTES = 1 << 20


class FASTTopicalError(ValueError):
    """Base class for FAST topical extract failures."""


class FASTTopicalAcquisitionError(FASTTopicalError):
    """The local FAST topical CSV extract could not be acquired safely."""


class FASTTopicalSourceDriftError(FASTTopicalError):
    """A FAST topical CSV extract no longer matches its pin or documented shape."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _digest_hex(value: str, *, label: str) -> str:
    match = _DIGEST.fullmatch(value)
    if match is None:
        raise FASTTopicalAcquisitionError(f"{label} must be a lowercase sha256:<64 hex> digest")
    return match.group(1)


def _digest_and_length(path: Path) -> tuple[str, int]:
    """Hash and measure a file by streaming it, never holding it fully in memory."""

    hasher = hashlib.sha256()
    length = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            hasher.update(chunk)
            length += len(chunk)
    return "sha256:" + hasher.hexdigest(), length


@dataclass(frozen=True, slots=True)
class FASTTopicalExtractPin:
    """Exact identity of one locally captured FAST topical CSV extract."""

    filename: str
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int
    expected_row_count: int

    def __post_init__(self) -> None:
        _digest_hex(self.expected_sha256, label="expected_sha256")
        if not self.filename or Path(self.filename).name != self.filename:
            raise FASTTopicalAcquisitionError("filename must be one plain path component")
        if not self.retrieved_at:
            raise FASTTopicalAcquisitionError("retrieved_at must not be empty")
        if self.expected_byte_length <= 0:
            raise FASTTopicalAcquisitionError("expected_byte_length must be positive")
        if self.expected_row_count <= 0:
            raise FASTTopicalAcquisitionError("expected_row_count must be positive")


# Deliberately narrower than refspec.registry.infrastructure.pinned_acquisition
# .AcquisitionMode / .FetcherAcquisitionMode: OCLC publishes no live endpoint
# (network or fetcher-reachable) for this facet's CSV extract, so
# acquire_fast_topical_extract() below only ever content-addresses bytes the
# caller already retrieved out of band. There is no third mode to widen to.
AcquisitionMode = Literal["cache", "local"]


@dataclass(frozen=True, slots=True)
class AcquiredFASTTopicalExtract:
    """One verified FAST topical CSV extract in the content-addressed store."""

    pin: FASTTopicalExtractPin
    path: Path
    sha256: str
    byte_length: int
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


def _verify_existing(
    path: Path,
    pin: FASTTopicalExtractPin,
) -> AcquiredFASTTopicalExtract:
    if path.is_symlink() or not path.is_file():
        raise FASTTopicalAcquisitionError(f"content-addressed target is not a regular file: {path}")
    digest, length = _digest_and_length(path)
    if length != pin.expected_byte_length:
        raise FASTTopicalSourceDriftError(
            f"cached FAST topical extract byte length drift: expected {pin.expected_byte_length}, got {length}"
        )
    if digest != pin.expected_sha256:
        raise FASTTopicalSourceDriftError(
            f"cached FAST topical extract digest drift: expected {pin.expected_sha256}, got {digest}"
        )
    return AcquiredFASTTopicalExtract(
        pin=pin,
        path=path,
        sha256=digest,
        byte_length=length,
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def acquire_fast_topical_extract(
    pin: FASTTopicalExtractPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
) -> AcquiredFASTTopicalExtract:
    """Acquire one locally supplied FAST topical CSV extract by content address.

    OCLC publishes no CSV endpoint for this facet, so acquisition never opens
    a network connection: it only content-addresses and re-verifies bytes the
    caller already retrieved.
    """

    digest_hex = _digest_hex(pin.expected_sha256, label="pin.expected_sha256")
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is None:
        raise FASTTopicalAcquisitionError(
            "FAST topical extract is not cached; provide source_path to a local CSV capture"
        )
    local_path = Path(source_path)
    if local_path.is_symlink() or not local_path.is_file():
        raise FASTTopicalAcquisitionError(f"local FAST topical source is not a regular file: {local_path}")

    final_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".acquire-",
        suffix=".tmp",
        dir=final_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        hasher = hashlib.sha256()
        length = 0
        with local_path.open("rb") as source, os.fdopen(descriptor, "wb") as destination:
            descriptor = -1
            for chunk in iter(lambda: source.read(_CHUNK_BYTES), b""):
                hasher.update(chunk)
                length += len(chunk)
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        digest = "sha256:" + hasher.hexdigest()
        if length != pin.expected_byte_length:
            raise FASTTopicalSourceDriftError(
                f"local FAST topical extract byte length drift: expected {pin.expected_byte_length}, got {length}"
            )
        if digest != pin.expected_sha256:
            raise FASTTopicalSourceDriftError(
                f"local FAST topical extract digest drift: expected {pin.expected_sha256}, got {digest}"
            )
        try:
            os.link(temporary_path, final_path)
        except FileExistsError:
            return _verify_existing(final_path, pin)
        return AcquiredFASTTopicalExtract(
            pin=pin,
            path=final_path,
            sha256=digest,
            byte_length=length,
            acquisition_mode="local",
            cache_hit=False,
            local_source_path=local_path.resolve(),
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class FASTTopicalRow:
    """One parsed, digest-provenanced FAST topical CSV row."""

    source_ordinal: int
    fast_id: str
    uri: str
    heading: str


def _parse_row(raw_row: Sequence[str], ordinal: int) -> FASTTopicalRow:
    if len(raw_row) != len(_HEADER):
        raise FASTTopicalSourceDriftError(
            f"FAST topical extract row {ordinal} has {len(raw_row)} fields, expected {len(_HEADER)}"
        )
    fast_id, uri, heading = raw_row
    match = _FAST_ID.fullmatch(fast_id)
    if match is None:
        raise FASTTopicalSourceDriftError(f"FAST topical extract row {ordinal} has malformed fast_id {fast_id!r}")
    expected_uri = f"{FAST_URI_BASE}{int(match.group(1))}"
    if uri != expected_uri:
        raise FASTTopicalSourceDriftError(
            f"FAST topical extract row {ordinal} uri {uri!r} does not match fast_id {fast_id!r}"
        )
    if not heading or heading != heading.strip():
        raise FASTTopicalSourceDriftError(f"FAST topical extract row {ordinal} has malformed heading")
    return FASTTopicalRow(source_ordinal=ordinal, fast_id=fast_id, uri=uri, heading=heading)


def iter_fast_topical_rows(path: Path) -> Iterator[FASTTopicalRow]:
    """Stream one topical row at a time; never materializes the whole file."""

    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = tuple(next(reader))
        except StopIteration as error:
            raise FASTTopicalSourceDriftError("FAST topical extract is empty; expected a header row") from error
        if header != _HEADER:
            raise FASTTopicalSourceDriftError(f"FAST topical extract header drifted: {header!r}")
        for ordinal, raw_row in enumerate(reader, start=1):
            yield _parse_row(raw_row, ordinal)


@dataclass(frozen=True, slots=True)
class ParsedFASTTopicalExtract:
    """A parsed, digest-pinned FAST topical CSV extract."""

    pin: FASTTopicalExtractPin
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    rows: tuple[FASTTopicalRow, ...]
    documented_total_row_count: int
    gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FASTNativeSourcePin:
    """Exact identity and advertised record count of one OCLC source file."""

    filename: str
    publisher_url: str
    expected_sha256: str
    expected_byte_length: int
    expected_record_count: int | None


FAST_TOPICAL_NATIVE_BASE_PIN = FASTNativeSourcePin(
    filename="FASTTopical.nt.zip",
    publisher_url=FAST_TOPICAL_BULK_NT_ZIP_URL,
    expected_sha256=FAST_TOPICAL_BULK_NT_ZIP_SHA256,
    expected_byte_length=FAST_TOPICAL_BULK_NT_ZIP_BYTE_LENGTH,
    expected_record_count=FAST_TOPICAL_BASE_ACTIVE_COUNT,
)

FAST_TOPICAL_CHANGE_PINS = (
    FASTNativeSourcePin(
        filename="FASTChanges2024-10-27.mrc",
        publisher_url=f"{FAST_CHANGES_URL}FASTChanges2024-10-27.mrc",
        expected_sha256="sha256:f53c640767cb1c4c0bce85b85a69e382780a65772d4deae30ab3a1a8fa96419a",
        expected_byte_length=2_726_812,
        expected_record_count=3_276,
    ),
    FASTNativeSourcePin(
        filename="FASTChanges2024-12-04.mrc",
        publisher_url=f"{FAST_CHANGES_URL}FASTChanges2024-12-04.mrc",
        expected_sha256="sha256:06ae6714240ac1d8126cfeff5392feb8004f6a1d16e2bb392c854ecf47a6a011",
        expected_byte_length=1_797_706,
        expected_record_count=2_153,
    ),
    FASTNativeSourcePin(
        filename="FASTChanges2025-05-01.mrc",
        publisher_url=f"{FAST_CHANGES_URL}FASTChanges2025-05-01.mrc",
        expected_sha256="sha256:0d505664fe5de155d58bd1c178e65112ee4b42067044b6a4cb14f516ef03f116",
        expected_byte_length=3_827_847,
        expected_record_count=4_350,
    ),
    FASTNativeSourcePin(
        filename="FASTChanges2026-02-13.mrc",
        publisher_url=f"{FAST_CHANGES_URL}FASTChanges2026-02-13.mrc",
        expected_sha256="sha256:98c965420836f0f21aed18599f0216cc61b2f3c2b7ca06cc10f6b9cc1ad374e3",
        expected_byte_length=10_220_096,
        expected_record_count=12_633,
    ),
)


@dataclass(frozen=True, slots=True)
class FASTTopicalNativeRow:
    """One current active Topical authority record from OCLC's native files."""

    numeric_id: str
    legacy_fst_id: str
    uri: str
    heading: str
    alt_labels: tuple[str, ...]
    broader_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FASTTopicalTombstone:
    """One latest inactive Topical record and its publisher-declared replacements."""

    numeric_id: str
    status: str
    replacement_ids: tuple[str, ...]
    automatically_linked: bool


@dataclass(frozen=True, slots=True)
class FASTTopicalChangeSummary:
    """Measured all-facet and Topical counts for one OCLC MARC change file."""

    filename: str
    source_sha256: str
    source_byte_length: int
    all_facet_record_count: int
    topical_status_counts: Mapping[str, int]
    topical_event_count: int


@dataclass(frozen=True, slots=True)
class ParsedFASTTopicalNativeSnapshot:
    """Current Topical state rebuilt from exact OCLC base and change bytes."""

    base_sha256: str
    base_byte_length: int
    base_active_count: int
    change_summaries: tuple[FASTTopicalChangeSummary, ...]
    topical_event_count: int
    unique_changed_id_count: int
    latest_change_status_counts: Mapping[str, int]
    facet_migration_count: int
    rows: tuple[FASTTopicalNativeRow, ...]
    tombstones: tuple[FASTTopicalTombstone, ...]

    def by_numeric_id(self) -> dict[str, FASTTopicalNativeRow]:
        return {row.numeric_id: row for row in self.rows}


_NT_TRIPLE = re.compile(r'^<([^>]+)>\s+<([^>]+)>\s+(?:<([^>]+)>|"((?:[^"\\]|\\.)*)")')
_NT_BLANK_NODE_OBJECT = re.compile(r"^<[^>]+>\s+<[^>]+>\s+_:[^\s]+\s+\.$")
_SKOS_PREF = "http://www.w3.org/2004/02/skos/core#prefLabel"
_SKOS_ALT = "http://www.w3.org/2004/02/skos/core#altLabel"
_SKOS_BROADER = "http://www.w3.org/2004/02/skos/core#broader"
_OWL_DEPRECATED = "http://www.w3.org/2002/07/owl#deprecated"
_DCTERMS_IDENTIFIER = "http://purl.org/dc/terms/identifier"
_NT_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t"}
_FAST_MARC_ID = re.compile(r"^fst0*(\d+)$")
_FAST_MARC_LINK = re.compile(r"\(OCoLC\)fst0*(\d+)")
_MARC_HEADING_TAGS = frozenset({"100", "110", "111", "130", "147", "148", "150", "151", "155"})
_MARC_ALT_TAGS = frozenset({"400", "410", "411", "430", "447", "448", "450", "451", "455"})
_MARC_LINK_TAGS = frozenset({"500", "510", "511", "530", "547", "548", "550", "551", "555"})
_MARC_REPLACEMENT_TAGS = frozenset({"700", "710", "711", "730", "747", "748", "750", "751", "755"})
_MARC_CONTENT_CODES = frozenset("abcdefghjklmnopqrstu")
_MARC_SUBDIVISION_CODES = frozenset("vxyz")


def _unescape_ntriples_literal(value: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character != "\\" or index + 1 >= len(value):
            output.append(character)
            index += 1
            continue
        marker = value[index + 1]
        if marker in _NT_ESCAPES:
            output.append(_NT_ESCAPES[marker])
            index += 2
            continue
        if marker in {"u", "U"}:
            width = 4 if marker == "u" else 8
            digits = value[index + 2 : index + 2 + width]
            if len(digits) != width or not all(character in "0123456789abcdefABCDEF" for character in digits):
                raise FASTTopicalSourceDriftError("FAST N-Triples contains a malformed Unicode escape")
            output.append(chr(int(digits, 16)))
            index += 2 + width
            continue
        raise FASTTopicalSourceDriftError(f"FAST N-Triples contains unsupported escape \\{marker}")
    return "".join(output)


def _verify_native_source(path: Path, pin: FASTNativeSourcePin) -> tuple[str, int]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise FASTTopicalAcquisitionError(f"FAST native source is not a regular file: {path}")
    digest, length = _digest_and_length(path)
    if length != pin.expected_byte_length:
        raise FASTTopicalSourceDriftError(
            f"{pin.filename} byte length drift: expected {pin.expected_byte_length}, got {length}"
        )
    if digest != pin.expected_sha256:
        raise FASTTopicalSourceDriftError(f"{pin.filename} digest drift: expected {pin.expected_sha256}, got {digest}")
    return digest, length


def _legacy_fst_id(numeric_id: str) -> str:
    return f"fst{int(numeric_id):08d}"


def _parse_native_base(path: Path) -> dict[str, FASTTopicalNativeRow]:
    labels: dict[str, str] = {}
    identifiers: dict[str, str] = {}
    alt_labels: dict[str, list[str]] = {}
    broader_ids: dict[str, list[str]] = {}
    deprecated: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".nt")]
        if members != ["FASTTopical.nt"]:
            raise FASTTopicalSourceDriftError(f"FAST bulk ZIP member shape drifted: {members!r}")
        with archive.open(members[0]) as raw, io.TextIOWrapper(raw, encoding="utf-8", errors="strict") as source:
            for line_number, line in enumerate(source, start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if not stripped.startswith(f"<{FAST_URI_BASE}"):
                    continue
                match = _NT_TRIPLE.match(stripped)
                if match is None:
                    if _NT_BLANK_NODE_OBJECT.fullmatch(stripped):
                        continue
                    raise FASTTopicalSourceDriftError(f"FAST N-Triples line {line_number} is malformed")
                subject, predicate, iri_object, literal = match.groups()
                if not subject.startswith(FAST_URI_BASE):
                    continue
                numeric_id = subject.removeprefix(FAST_URI_BASE)
                if not numeric_id.isdigit():
                    continue
                if predicate == _SKOS_PREF and literal is not None:
                    labels.setdefault(numeric_id, _unescape_ntriples_literal(literal))
                elif predicate == _SKOS_ALT and literal is not None:
                    alt_labels.setdefault(numeric_id, []).append(_unescape_ntriples_literal(literal))
                elif predicate == _SKOS_BROADER and iri_object is not None and iri_object.startswith(FAST_URI_BASE):
                    broader_ids.setdefault(numeric_id, []).append(str(int(iri_object.removeprefix(FAST_URI_BASE))))
                elif predicate == _DCTERMS_IDENTIFIER and literal is not None:
                    identifiers.setdefault(numeric_id, _unescape_ntriples_literal(literal))
                elif predicate == _OWL_DEPRECATED:
                    deprecated.add(numeric_id)

    rows: dict[str, FASTTopicalNativeRow] = {}
    for numeric_id, heading in labels.items():
        if numeric_id in deprecated:
            continue
        if identifiers.get(numeric_id) != numeric_id:
            raise FASTTopicalSourceDriftError(f"FAST identifier does not match its URI for {numeric_id}")
        rows[numeric_id] = FASTTopicalNativeRow(
            numeric_id=numeric_id,
            legacy_fst_id=_legacy_fst_id(numeric_id),
            uri=f"{FAST_URI_BASE}{numeric_id}",
            heading=heading,
            alt_labels=tuple(dict.fromkeys(alt_labels.get(numeric_id, ()))),
            broader_ids=tuple(dict.fromkeys(broader_ids.get(numeric_id, ()))),
        )
    if len(rows) != FAST_TOPICAL_BASE_ACTIVE_COUNT:
        raise FASTTopicalSourceDriftError(
            f"FAST native base active count drift: expected {FAST_TOPICAL_BASE_ACTIVE_COUNT}, got {len(rows)}"
        )
    return rows


def _marc_numeric_id(record: Any) -> str:
    fields = record.get_fields("001")
    if len(fields) != 1:
        raise FASTTopicalSourceDriftError("FAST MARC record must contain exactly one 001 field")
    match = _FAST_MARC_ID.fullmatch(fields[0].value())
    if match is None:
        raise FASTTopicalSourceDriftError(f"FAST MARC 001 drifted: {fields[0].value()!r}")
    return str(int(match.group(1)))


def _render_marc_heading(field: Field) -> str:
    rendered = ""
    for subfield in field.subfields:
        value = " ".join(subfield.value.split())
        if not value:
            continue
        if subfield.code in _MARC_SUBDIVISION_CODES:
            rendered += f"--{value}"
        elif subfield.code in _MARC_CONTENT_CODES:
            if rendered and not rendered.endswith((" ", "--")):
                rendered += " "
            rendered += value
    if not rendered:
        raise FASTTopicalSourceDriftError(f"FAST MARC {field.tag} heading contains no content subfields")
    return rendered


def _marc_link_ids(field: Field) -> tuple[str, ...]:
    result: list[str] = []
    for value in field.get_subfields("0"):
        for match in _FAST_MARC_LINK.finditer(value):
            numeric_id = str(int(match.group(1)))
            if numeric_id not in result:
                result.append(numeric_id)
    return tuple(result)


def _validate_marc_identity(record: Any, numeric_id: str) -> None:
    if record.leader[6] != "z":
        raise FASTTopicalSourceDriftError(f"FAST MARC {numeric_id} is not an authority record")
    if not any(value == "fast" for field in record.get_fields("040") for value in field.get_subfields("f")):
        raise FASTTopicalSourceDriftError(f"FAST MARC {numeric_id} lacks 040 $f fast")
    heading_fields = [field for field in record.fields if field.tag in _MARC_HEADING_TAGS]
    if len(heading_fields) > 1:
        raise FASTTopicalSourceDriftError(f"FAST MARC {numeric_id} contains multiple 1XX headings")
    uri_values = [value for field in record.get_fields("024") for value in field.get_subfields("a")]
    if uri_values != [f"{FAST_URI_BASE}{numeric_id}"]:
        raise FASTTopicalSourceDriftError(f"FAST MARC {numeric_id} 024 URI does not match 001")


def _native_row_from_marc(record: Any, numeric_id: str) -> FASTTopicalNativeRow:
    topical = record.get_fields("150")
    if len(topical) != 1:
        raise FASTTopicalSourceDriftError(f"FAST MARC topical record {numeric_id} must contain one 150")
    alternatives = tuple(
        dict.fromkeys(_render_marc_heading(field) for field in record.fields if field.tag in _MARC_ALT_TAGS)
    )
    parents: list[str] = []
    for field in record.fields:
        if field.tag not in _MARC_LINK_TAGS or not any(value.startswith("g") for value in field.get_subfields("w")):
            continue
        for parent in _marc_link_ids(field):
            if parent not in parents:
                parents.append(parent)
    return FASTTopicalNativeRow(
        numeric_id=numeric_id,
        legacy_fst_id=_legacy_fst_id(numeric_id),
        uri=f"{FAST_URI_BASE}{numeric_id}",
        heading=_render_marc_heading(topical[0]),
        alt_labels=alternatives,
        broader_ids=tuple(parents),
    )


def _replacement_tombstone(record: Any, numeric_id: str, status: str) -> FASTTopicalTombstone:
    replacement_fields = [
        field
        for field in record.fields
        if field.tag in _MARC_REPLACEMENT_TAGS
        and field.indicators is not None
        and field.indicators[1] == "7"
        and "fast" in field.get_subfields("2")
    ]
    replacement_ids = tuple(dict.fromkeys(link for field in replacement_fields for link in _marc_link_ids(field)))
    note_ids = tuple(dict.fromkeys(link for field in record.get_fields("682") for link in _marc_link_ids(field)))
    if status == "x" and (not replacement_ids or set(replacement_ids) != set(note_ids)):
        raise FASTTopicalSourceDriftError(
            f"FAST MARC replacement links disagree with 682 for {numeric_id}: {replacement_ids!r} vs {note_ids!r}"
        )
    if status == "d" and (replacement_ids or note_ids):
        raise FASTTopicalSourceDriftError(f"obsolete FAST MARC record {numeric_id} unexpectedly names replacements")
    automatic = bool(replacement_fields) and all(
        any(len(value) >= 2 and value[1] == "a" for value in field.get_subfields("w")) for field in replacement_fields
    )
    return FASTTopicalTombstone(
        numeric_id=numeric_id,
        status=status,
        replacement_ids=replacement_ids,
        automatically_linked=automatic,
    )


def parse_fast_topical_native_snapshot(
    base_archive_path: Path,
    change_paths: Sequence[Path],
) -> ParsedFASTTopicalNativeSnapshot:
    """Rebuild current FAST Topical state from OCLC's native base and deltas."""

    if len(change_paths) != len(FAST_TOPICAL_CHANGE_PINS):
        raise FASTTopicalAcquisitionError(f"expected {len(FAST_TOPICAL_CHANGE_PINS)} chronological FAST change files")
    base_digest, base_length = _verify_native_source(base_archive_path, FAST_TOPICAL_NATIVE_BASE_PIN)
    rows = _parse_native_base(Path(base_archive_path))
    base_active_count = len(rows)
    latest_status: dict[str, str] = {}
    tombstones: dict[str, FASTTopicalTombstone] = {}
    changed_ids: set[str] = set()
    change_summaries: list[FASTTopicalChangeSummary] = []
    topical_event_count = 0
    facet_migrations = 0

    for raw_path, pin in zip(change_paths, FAST_TOPICAL_CHANGE_PINS, strict=True):
        path = Path(raw_path)
        digest, length = _verify_native_source(path, pin)
        status_counts: Counter[str] = Counter()
        record_count = 0
        with path.open("rb") as source:
            reader = MARCReader(
                source,
                to_unicode=True,
                force_utf8=False,
                utf8_handling="strict",
                permissive=False,
            )
            for record in reader:
                record_count += 1
                if record is None:
                    raise FASTTopicalSourceDriftError(f"{pin.filename} contains an unreadable MARC record")
                numeric_id = _marc_numeric_id(record)
                _validate_marc_identity(record, numeric_id)
                status = record.leader[5]
                if status not in {"c", "n", "x", "d"}:
                    raise FASTTopicalSourceDriftError(
                        f"FAST MARC {numeric_id} has unsupported leader status {status!r}"
                    )
                topical = bool(record.get_fields("150"))
                if topical:
                    status_counts[status] += 1
                    topical_event_count += 1
                    changed_ids.add(numeric_id)
                    latest_status[numeric_id] = status
                if status in {"x", "d"}:
                    if topical or numeric_id in rows:
                        rows.pop(numeric_id, None)
                        tombstones[numeric_id] = _replacement_tombstone(record, numeric_id, status)
                    continue
                if topical:
                    rows[numeric_id] = _native_row_from_marc(record, numeric_id)
                    tombstones.pop(numeric_id, None)
                elif numeric_id in rows:
                    # OCLC changed the record's authority facet. It no longer
                    # belongs in the Topical output even though it remains FAST.
                    rows.pop(numeric_id)
                    tombstones.pop(numeric_id, None)
                    facet_migrations += 1
        if record_count != pin.expected_record_count:
            raise FASTTopicalSourceDriftError(
                f"{pin.filename} record count drift: expected {pin.expected_record_count}, got {record_count}"
            )
        change_summaries.append(
            FASTTopicalChangeSummary(
                filename=pin.filename,
                source_sha256=digest,
                source_byte_length=length,
                all_facet_record_count=record_count,
                topical_status_counts=dict(sorted(status_counts.items())),
                topical_event_count=sum(status_counts.values()),
            )
        )

    current_rows = tuple(sorted(rows.values(), key=lambda row: int(row.numeric_id)))
    current_tombstones = tuple(sorted(tombstones.values(), key=lambda row: int(row.numeric_id)))
    if len(current_rows) != FAST_TOPICAL_CURRENT_ACTIVE_COUNT:
        raise FASTTopicalSourceDriftError(
            f"FAST current active count drift: expected {FAST_TOPICAL_CURRENT_ACTIVE_COUNT}, got {len(current_rows)}"
        )
    return ParsedFASTTopicalNativeSnapshot(
        base_sha256=base_digest,
        base_byte_length=base_length,
        base_active_count=base_active_count,
        change_summaries=tuple(change_summaries),
        topical_event_count=topical_event_count,
        unique_changed_id_count=len(changed_ids),
        latest_change_status_counts=dict(sorted(Counter(latest_status.values()).items())),
        facet_migration_count=facet_migrations,
        rows=current_rows,
        tombstones=current_tombstones,
    )


FAST_TOPICAL_GAPS = (
    (
        "OCLC publishes the Topical facet as MARC, MARCXML, and RDF N-Triples, "
        "not CSV. parse_fast_topical_native_snapshot reads the exact N-Triples "
        "base and chronological MARC changes; the CSV reader is compatibility-only."
    ),
    (
        "The live bulk-data host returned a Cloudflare block to automated "
        "fetches. The exact publisher ZIP was recovered through an exact "
        "Wayback replay and matches the digest recorded by the earlier "
        "SpicyRegs ingestion."
    ),
    (
        f"The native October 2024 base has {FAST_TOPICAL_BASE_ACTIVE_COUNT:,} "
        f"active publisher IDs. Applying OCLC changes through 2026-02-13 yields "
        f"{FAST_TOPICAL_CURRENT_ACTIVE_COUNT:,}; the older "
        f"{FAST_TOPICAL_DOCUMENTED_ROW_COUNT:,} figure came from merging labels "
        "and is not a publisher-record count."
    ),
    (
        "A verified bot-wall-free channel exists alongside the blocked bulk "
        "host: OCLC's per-term Linked Data at id.worldcat.org answers a "
        "numeric FAST id with RDF/XML at the .rdf.xml path suffix only "
        "(FAST_TERM_RDF_URL_PATTERN), confirmed live on 2026-08-04 with no "
        "bot wall and no key. Its one observed response header put the "
        "daily cap at "
        f"{FAST_SUGGEST_API_OBSERVED_DAILY_RATE_LIMIT:,} "
        "(FAST_SUGGEST_API_OBSERVED_DAILY_RATE_LIMIT, not published policy); "
        "at that ceiling a full "
        f"{FAST_TOPICAL_DOCUMENTED_ROW_COUNT:,}-term Topical crawl through "
        "this channel is a multi-week job, not a single acquisition run."
    ),
    (
        "OCLC's official FAST Changes channel publishes current MARC change "
        "records between periodic bulk releases; the latest captured change "
        "file is dated 2026-02-13."
    ),
)


def parse_fast_topical_extract(
    acquired: AcquiredFASTTopicalExtract,
) -> ParsedFASTTopicalExtract:
    """Stream-parse an acquired CSV extract and re-verify it before returning."""

    digest, length = _digest_and_length(acquired.path)
    if length != acquired.pin.expected_byte_length or digest != acquired.pin.expected_sha256:
        raise FASTTopicalSourceDriftError("FAST topical extract drifted between acquisition and parsing")

    rows: list[FASTTopicalRow] = []
    seen_ids: set[str] = set()
    for row in iter_fast_topical_rows(acquired.path):
        if row.fast_id in seen_ids:
            raise FASTTopicalSourceDriftError(f"FAST topical extract contains duplicate fast_id {row.fast_id!r}")
        seen_ids.add(row.fast_id)
        rows.append(row)

    if len(rows) != acquired.pin.expected_row_count:
        raise FASTTopicalSourceDriftError(
            f"FAST topical extract row count drift: expected {acquired.pin.expected_row_count}, parsed {len(rows)}"
        )

    return ParsedFASTTopicalExtract(
        pin=acquired.pin,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=digest,
        source_byte_length=length,
        rows=tuple(rows),
        documented_total_row_count=FAST_TOPICAL_DOCUMENTED_ROW_COUNT,
        gaps=FAST_TOPICAL_GAPS,
    )


def _source_artifact_iri(source_sha256: str) -> str:
    return f"urn:ref:fast-topical-source-artifact:{_digest_hex(source_sha256, label='source_sha256')}"


def _observation_id(source_sha256: str, fast_id: str) -> str:
    digest_hex = _digest_hex(source_sha256, label="source_sha256")
    return f"urn:ref:source-record:fast-topical:{digest_hex}:{fast_id}"


def _identifier(
    value: str,
    kind: str,
    *,
    source_path: str,
    observed_at: str,
    source_digest: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "kind": kind,
        "authorityUri": FAST_IDENTIFIER_AUTHORITY_URI,
        "sourceUri": FAST_LANDING_PAGE_URL,
        "sourcePath": source_path,
        "observedAt": observed_at,
        "sourceDigest": source_digest,
    }


def _observation(
    row: FASTTopicalRow,
    *,
    source_sha256: str,
    observed_at: str,
) -> dict[str, Any]:
    return {
        "id": _observation_id(source_sha256, row.fast_id),
        "sourceArtifact": _source_artifact_iri(source_sha256),
        "sourcePath": f"row[{row.source_ordinal}]",
        "sourceOrdinal": row.source_ordinal,
        "labels": [{"value": row.heading, "language": "en", "role": "preferred"}],
        "identifiers": [
            _identifier(
                row.fast_id,
                "fastId",
                source_path=f"row[{row.source_ordinal}].fast_id",
                observed_at=observed_at,
                source_digest=source_sha256,
            ),
            _identifier(
                row.uri,
                "fastUri",
                source_path=f"row[{row.source_ordinal}].uri",
                observed_at=observed_at,
                source_digest=source_sha256,
            ),
        ],
        # Search expansion and mapping only: FAST never occupies a reserved
        # classifier output slot.
        "uses": ["searchExpansion", "mappingReference"],
        "conceptIdentityClaimed": False,
    }


def _package_gaps(row_count: int) -> tuple[dict[str, Any], ...]:
    return (
        {
            "code": "fastNoOfficialCsvFormat",
            "affectedObservationCount": row_count,
            "effect": (
                "OCLC's official FAST download page publishes the Topical facet "
                "as MARC, MARCXML, and RDF N-Triples bulk files only; no official "
                "CSV byte source exists to pin."
            ),
        },
        {
            "code": "fastLegacyCsvCompatibilityView",
            "affectedObservationCount": row_count,
            "effect": (
                "This package was built from the legacy CSV compatibility view. "
                "Use parse_fast_topical_native_snapshot for source validation."
            ),
        },
        {
            "code": "fastDevelopmentSampleNotFullExtract",
            "affectedObservationCount": row_count,
            "effect": (
                "The current native topical snapshot has "
                f"{FAST_TOPICAL_CURRENT_ACTIVE_COUNT:,} rows; this package's row "
                "count reflects only what was captured for its pin."
            ),
        },
    )


def build_fast_topical_source_package(
    parsed: ParsedFASTTopicalExtract,
    *,
    captured_at: str,
    source_bytes: bytes,
) -> SourceControlledResourceBundle:
    """Package every parsed row as mapping-only source evidence.

    Every observation is restricted to ``searchExpansion`` and
    ``mappingReference``: it is never eligible as ``sourceAssignedEvidence``
    and can never fill a classifier output slot. The shared development-only
    usage ceiling forbids promoting this package into a concept scheme or
    accepted output.
    """

    if len(source_bytes) != parsed.source_byte_length or sha256_digest(source_bytes) != parsed.source_sha256:
        raise FASTTopicalSourceDriftError("supplied source_bytes do not match the parsed extract's pinned digest")

    observations = tuple(
        _observation(row, source_sha256=parsed.source_sha256, observed_at=parsed.retrieved_at) for row in parsed.rows
    )
    return build_source_controlled_resource_bundle(
        resource_id=FAST_TOPICAL_RESOURCE_ID,
        title="OCLC FAST Topical facet source observations",
        resource_kind="sourceTermSnapshot",
        identity_status="publisherIdentifiersPreserved",
        uses=("searchExpansion", "mappingReference"),
        captured_at=captured_at,
        observations=observations,
        source_artifacts={_source_artifact_iri(parsed.source_sha256): source_bytes},
        source_observed_count=len(parsed.rows),
        gaps=_package_gaps(len(parsed.rows)),
    )


__all__ = [
    "FAST_ATTRIBUTION_NOTICE",
    "FAST_IDENTIFIER_AUTHORITY_URI",
    "FAST_LANDING_PAGE_URL",
    "FAST_LICENSE_URL",
    "FAST_PUBLISHER",
    "FAST_TOPICAL_BASE_ACTIVE_COUNT",
    "FAST_TOPICAL_BULK_NT_ZIP_ARCHIVE_URL",
    "FAST_TOPICAL_CHANGE_PINS",
    "FAST_TOPICAL_CURRENT_ACTIVE_COUNT",
    "FAST_TOPICAL_DOCUMENTED_ROW_COUNT",
    "FAST_TOPICAL_GAPS",
    "FAST_TOPICAL_NATIVE_BASE_PIN",
    "FAST_TOPICAL_OFFICIAL_BULK_FORMATS",
    "FAST_TOPICAL_RESOURCE_ID",
    "FAST_URI_BASE",
    "AcquiredFASTTopicalExtract",
    "FASTTopicalAcquisitionError",
    "FASTTopicalChangeSummary",
    "FASTTopicalError",
    "FASTTopicalExtractPin",
    "FASTTopicalNativeRow",
    "FASTTopicalRow",
    "FASTTopicalSourceDriftError",
    "FASTTopicalTombstone",
    "ParsedFASTTopicalExtract",
    "ParsedFASTTopicalNativeSnapshot",
    "acquire_fast_topical_extract",
    "build_fast_topical_source_package",
    "iter_fast_topical_rows",
    "parse_fast_topical_extract",
    "parse_fast_topical_native_snapshot",
    "sha256_digest",
]
