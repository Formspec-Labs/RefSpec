"""NPPES National Provider Identifier structure and CMS Certification Number shape.

Scope is identifier-shape and code-value capture only: the ten-digit NPI
structure with its Luhn check digit, the NPPES Data Dissemination file's
published column layout at fixture scale, and the CMS Certification Number
(CCN) shape. It never ingests bulk NPPES rows -- the live monthly file is
multi-gigabyte and the weekly file is tens of megabytes; this module accepts
only caller-supplied bytes for a small pinned excerpt.

The National Uniform Claim Committee (NUCC) Provider Taxonomy is deliberately
excluded. NPPES file rows carry taxonomy code *fields*, and this module
captures those field *names* as part of the public-domain file layout, but it
never parses, stores, or validates a NUCC taxonomy code *value*: NUCC requires
a commercial license for that code set.

Importing this module never opens a network connection. Every function takes
caller-supplied bytes; nothing here fetches from download.cms.gov.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections.abc import Sequence

from refspec.registry.controlled_identifier import ControlledIdentifier
from refspec.registry.source_controlled_resource import (
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)

# Source: https://download.cms.gov/nppes/NPI_Files.html
NPPES_NPI_FILES_PAGE_URL = "https://download.cms.gov/nppes/NPI_Files.html"
NPPES_AUTHORITY_URL = "https://nppes.cms.hhs.gov/"

# NUCC Provider Taxonomy is referenced by URL only; its codes are never
# captured here because reuse of the code set requires a commercial license.
NUCC_PROVIDER_TAXONOMY_REFERENCE_URL = (
    "https://nucc.org/index.php/code-sets-mainmenu-41/provider-taxonomy-mainmenu-40/csv-mainmenu-57"
)

# Exact real bytes captured 2026-08-03 from the "Weekly Incremental NPI Files
# Version 2 (V.2)" listed on NPPES_NPI_FILES_PAGE_URL, ZIP entry
# "NPPES_Data_Dissemination_072726_080226_Weekly_V2.zip". This one weekly ZIP
# is itself far smaller than the multi-gigabyte monthly file; the fixtures
# below retain only its file-header row and a three-row excerpt.
NPPES_WEEKLY_CAPTURE_URL = "https://download.cms.gov/nppes/NPPES_Data_Dissemination_072726_080226_Weekly_V2.zip"
NPPES_FILEHEADER_SOURCE_PATH = "npidata_pfile_20260727-20260802_fileheader.csv"
NPPES_SAMPLE_SOURCE_PATH = "npidata_pfile_20260727-20260802.csv"
NPPES_CAPTURED_AT = "2026-08-03T19:22:12Z"

NPPES_FILEHEADER_SHA256 = "sha256:1f781040d7dae44496be1729250e79114b6dd03f17c10d7d8965486052177679"
NPPES_FILEHEADER_BYTE_LENGTH = 12267
NPPES_SAMPLE_SHA256 = "sha256:3735061e873e5db7cfb422aeaa7eea5514d0a5e8089765c94b82f0d43450a87d"
NPPES_SAMPLE_BYTE_LENGTH = 15866
NPPES_EXPECTED_FIELD_COUNT = 330

NPPES_FILE_LAYOUT_RESOURCE_ID = "nppes-npi-file-layout-v2"
NPPES_FILEHEADER_SOURCE_ID = "urn:ref:nppes:source:npi-file-header-v2:2026-07-27-2026-08-02"

# Entity Type Code is a native NPPES field, not a licensed code set: 1 marks
# an Individual (NPI-1) record and 2 marks an Organization (NPI-2) record.
NPPES_ENTITY_TYPE_CODES = frozenset({"1", "2"})

_NPI_SHAPE = re.compile(r"^\d{10}$")
_NPI_BASE_SHAPE = re.compile(r"^\d{9}$")
# 45 CFR 162.406 fixes the NPI's card-issuer prefix at 80840 (80 = health
# applications, 840 = United States) for the Luhn check-digit calculation.
_NPI_ISSUER_PREFIX = "80840"

# CMS Manual System Pub 100-07 Transmittal 29 (Oct. 12, 2007) and Survey &
# Certification Letter 16-39 (Sep. 8, 2016) both document the CCN shape used
# here: Part A providers use six characters (2-digit numeric state code plus
# a 4-character facility-type/sequence suffix); Part B suppliers, home health
# agency branches, and outpatient physical therapy extensions use ten
# characters (the same 2-digit state code plus an 8-character suffix). The
# suffix carries an alpha facility-type marker in some provider types (for
# example "P" for organ procurement organizations, "Q" for HHA branches) but
# every observed state code remains two ASCII digits.
_CCN_SHAPE = re.compile(r"^\d{2}[0-9A-Z]{4}$|^\d{2}[0-9A-Z]{8}$")


class NppesIdentifierError(ValueError):
    """An NPI, CCN, or NPPES file-layout capture fails its published shape."""


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _require_bytes(payload: object, label: str) -> bytes:
    if not isinstance(payload, bytes) or not payload:
        raise NppesIdentifierError(f"{label} must be non-empty bytes")
    return payload


def _check_pin(
    payload: bytes,
    *,
    label: str,
    expected_sha256: str | None,
    expected_byte_length: int | None,
) -> None:
    if expected_byte_length is not None and len(payload) != expected_byte_length:
        raise NppesIdentifierError(f"{label} byte length differs from its pin")
    if expected_sha256 is not None and _sha256(payload) != expected_sha256:
        raise NppesIdentifierError(f"{label} digest differs from its pin")


def npi_check_digit(base9: str) -> str:
    """Compute the tenth NPI digit under the 45 CFR 162.406 Luhn rule.

    The check digit is the Luhn (modulus 10, double-add-double) digit over
    the fixed five-digit "80840" card-issuer prefix followed by the first
    nine NPI digits.
    """

    if not isinstance(base9, str) or not _NPI_BASE_SHAPE.fullmatch(base9):
        raise NppesIdentifierError("NPI base digits must be exactly 9 ASCII digits")
    digits = [int(char) for char in (_NPI_ISSUER_PREFIX + base9)]
    total = 0
    for position, digit in enumerate(reversed(digits)):
        if position % 2 == 0:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return str((10 - (total % 10)) % 10)


def validate_npi(value: str) -> str:
    """Validate one National Provider Identifier's ten-digit Luhn structure."""

    if not isinstance(value, str) or not value.strip():
        raise NppesIdentifierError("NPI must not be empty")
    text = value.strip()
    if not _NPI_SHAPE.fullmatch(text):
        raise NppesIdentifierError("NPI must be exactly 10 ASCII digits")
    if text[9] != npi_check_digit(text[:9]):
        raise NppesIdentifierError("NPI check digit fails the 45 CFR 162.406 Luhn rule")
    return text


def validate_ccn(value: str) -> str:
    """Validate one CMS Certification Number's six- or ten-character shape."""

    if not isinstance(value, str) or not value.strip():
        raise NppesIdentifierError("CCN must not be empty")
    text = value.strip()
    if not _CCN_SHAPE.fullmatch(text):
        raise NppesIdentifierError(
            "CCN must be a 2-digit state code followed by a 4- or 8-character "
            "uppercase alphanumeric facility-type/sequence suffix"
        )
    return text


def parse_fileheader_columns(
    payload: bytes,
    *,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> tuple[str, ...]:
    """Parse one NPPES file-header CSV row into its exact ordered column names.

    The parser is strict on purpose: a header capture from a future NPPES
    layout revision that adds, removes, reorders, or repeats a column fails
    loudly here rather than silently drifting from the pinned layout.
    """

    _require_bytes(payload, "fileheader capture")
    _check_pin(
        payload,
        label="fileheader capture",
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
    )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise NppesIdentifierError("fileheader capture must be valid UTF-8") from error
    lines = [line for line in text.splitlines() if line != ""]
    if len(lines) != 1:
        raise NppesIdentifierError("fileheader capture must contain exactly one CSV header line")
    try:
        columns = tuple(next(csv.reader([lines[0]])))
    except (csv.Error, StopIteration) as error:
        raise NppesIdentifierError("fileheader capture is not valid CSV") from error
    if not columns or any(not column.strip() for column in columns):
        raise NppesIdentifierError("fileheader columns must all be non-empty")
    if len(columns) != len(set(columns)):
        raise NppesIdentifierError("fileheader columns must be unique")
    return columns


def build_nppes_file_layout_bundle(
    fileheader_payload: bytes,
    *,
    source_uri: str = NPPES_WEEKLY_CAPTURE_URL,
    source_path: str = NPPES_FILEHEADER_SOURCE_PATH,
    observed_at: str = NPPES_CAPTURED_AT,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> SourceControlledResourceBundle:
    """Package one NPPES file-header capture as a deterministic column list.

    Each observation is one field-name position, not one provider row: this
    is file-layout metadata, never a bulk entity capture. No taxonomy code
    *value* is ever an observation here, only field *names* such as
    "Healthcare Provider Taxonomy Code_1".
    """

    columns = parse_fileheader_columns(
        fileheader_payload,
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
    )
    digest = _sha256(fileheader_payload)
    observations = [
        {
            "id": f"urn:ref:source-controlled-resource:{NPPES_FILE_LAYOUT_RESOURCE_ID}:field-{ordinal:03d}",
            "sourceArtifact": NPPES_FILEHEADER_SOURCE_ID,
            "sourcePath": source_path,
            "sourceOrdinal": ordinal,
            "labels": [{"value": column, "language": "en", "role": "preferred"}],
            "identifiers": [
                {
                    "value": column,
                    "kind": "nppesNpiFileHeaderFieldNameV2",
                    "authorityUri": NPPES_NPI_FILES_PAGE_URL,
                    "sourceUri": source_uri,
                    "sourcePath": source_path,
                    "observedAt": observed_at,
                    "sourceDigest": digest,
                }
            ],
            "eligibleUses": ["deterministicMetadata"],
            "conceptIdentityClaimed": False,
        }
        for ordinal, column in enumerate(columns)
    ]
    return build_source_controlled_resource_bundle(
        resource_id=NPPES_FILE_LAYOUT_RESOURCE_ID,
        title="NPPES NPI Data Dissemination file layout (Version 2 field names)",
        resource_kind="controlledCodeList",
        identity_status="publisherIdentifiersPreserved",
        uses=("deterministicMetadata",),
        captured_at=observed_at,
        candidate_use_authorized=False,
        observations=observations,
        source_artifacts={NPPES_FILEHEADER_SOURCE_ID: fileheader_payload},
    )


def parse_npi_sample(
    payload: bytes,
    fileheader_columns: Sequence[str],
    *,
    source_uri: str = NPPES_WEEKLY_CAPTURE_URL,
    observed_at: str = NPPES_CAPTURED_AT,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> tuple[ControlledIdentifier, ...]:
    """Validate a small NPPES row excerpt against a pinned file layout.

    Returns one ``ControlledIdentifier`` per distinct NPI found. This is a
    small pinned sample for shape validation, never a bulk entity capture:
    callers are responsible for keeping the excerpt small.
    """

    _require_bytes(payload, "NPI sample capture")
    _check_pin(
        payload,
        label="NPI sample capture",
        expected_sha256=expected_sha256,
        expected_byte_length=expected_byte_length,
    )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise NppesIdentifierError("NPI sample capture must be valid UTF-8") from error
    rows = [row for row in csv.reader(text.splitlines()) if row]
    if not rows:
        raise NppesIdentifierError("NPI sample capture must contain a header row")
    header, *data_rows = rows
    if tuple(header) != tuple(fileheader_columns):
        raise NppesIdentifierError("NPI sample header does not match the pinned file layout")
    if not data_rows:
        raise NppesIdentifierError("NPI sample capture must contain at least one data row")
    npi_index = header.index("NPI")
    entity_type_index = header.index("Entity Type Code")
    digest = _sha256(payload)
    seen: set[str] = set()
    identifiers: list[ControlledIdentifier] = []
    for ordinal, row in enumerate(data_rows):
        if len(row) != len(header):
            raise NppesIdentifierError(f"NPI sample row {ordinal} has {len(row)} fields, expected {len(header)}")
        entity_type = row[entity_type_index]
        if entity_type not in NPPES_ENTITY_TYPE_CODES:
            raise NppesIdentifierError(f"NPI sample row {ordinal} has an unrecognized Entity Type Code {entity_type!r}")
        npi = validate_npi(row[npi_index])
        if npi in seen:
            raise NppesIdentifierError(f"NPI sample repeats NPI {npi!r}")
        seen.add(npi)
        identifiers.append(
            ControlledIdentifier(
                value=npi,
                kind="nationalProviderIdentifier",
                authority_uri=NPPES_AUTHORITY_URL,
                source_uri=source_uri,
                observed_at=observed_at,
                effective_at=None,
                source_digest=digest,
            )
        )
    return tuple(identifiers)


__all__ = [
    "NPPES_AUTHORITY_URL",
    "NPPES_CAPTURED_AT",
    "NPPES_ENTITY_TYPE_CODES",
    "NPPES_EXPECTED_FIELD_COUNT",
    "NPPES_FILEHEADER_BYTE_LENGTH",
    "NPPES_FILEHEADER_SHA256",
    "NPPES_FILEHEADER_SOURCE_ID",
    "NPPES_FILEHEADER_SOURCE_PATH",
    "NPPES_FILE_LAYOUT_RESOURCE_ID",
    "NPPES_NPI_FILES_PAGE_URL",
    "NPPES_SAMPLE_BYTE_LENGTH",
    "NPPES_SAMPLE_SHA256",
    "NPPES_SAMPLE_SOURCE_PATH",
    "NPPES_WEEKLY_CAPTURE_URL",
    "NUCC_PROVIDER_TAXONOMY_REFERENCE_URL",
    "NppesIdentifierError",
    "build_nppes_file_layout_bundle",
    "npi_check_digit",
    "parse_fileheader_columns",
    "parse_npi_sample",
    "validate_ccn",
    "validate_npi",
]
