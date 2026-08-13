"""Pinned Unified Agenda rule-stage, priority, timetable-action, and
legal-authority controls for RIN records published on reginfo.gov.

reginfo.gov ships every RIN's structured fields as an XML export governed by a
shared, publicly linked schema (REGINFO_XML_Ver10262011.xsd). RULE_STAGE,
PRIORITY_CATEGORY, and TTBL_ACTION are typed as unrestricted ``xs:string``
elements, but the schema's own ``xs:documentation`` text names a closed list
of values for each -- "One of the following options: ...". RefSpec treats
that documented list, not an XSD enumeration restriction, as the pinned
controlled value set, and refuses to parse if the documentation no longer
matches the expected shape or count.

LEGAL_AUTHORITY carries no schema documentation or enumeration at all; it is
genuinely free text (for example "5 U.S.C. 301" or "E.O. 13279, 67 FR
77141"). Its citation-type prefixes (U.S.C., Pub. L., E.O.) come from the
RISC Preamble's "Legal Authority --" field definition and abbreviations
glossary instead, are hand-transcribed rather than machine-parsed out of the
PDF, and an unmatched citation is not treated as drift.

None of these values is a general subject concept. The catalog keeps the
Unified Agenda's Federal-Register-Thesaurus-based subject index separate from
this module, and treats RIN, agency sort codes, and NAICS as non-topical
deterministic metadata that this module does not model.

Acquisition accepts a local exact capture or an injected fetcher. Importing
this module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit

from refspec.registry.infrastructure.controlled_identifier import ControlledIdentifier
from refspec.registry.infrastructure.pinned_acquisition import FetcherAcquisitionMode as AcquisitionMode

UA_PUBLISHER = (
    "Regulatory Information Service Center, Office of Information and "
    "Regulatory Affairs, U.S. Office of Management and Budget"
)
UA_IDENTIFIER_AUTHORITY_URI = "https://www.reginfo.gov/"
UA_REGINFO_XSD_URL = "https://www.reginfo.gov/public/xml/REGINFO_XML_Ver10262011.xsd"
UA_RISC_PREAMBLE_URL = "https://www.reginfo.gov/public/jsp/eAgenda/StaticContent/202210/RiscPreamble.pdf"

DocumentKind = Literal["reginfoSchema", "riscPreamble"]
UAControlledFieldName = Literal["ruleStage", "priorityCategory", "timetableAction"]

_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_OPTION_LIST = re.compile(r"^One of the following(?: options)?:\s*(?P<body>.+)$", re.DOTALL)
_QUOTED_OPTION = re.compile(r'"([^"]+)"')
_XS_NS = "{http://www.w3.org/2001/XMLSchema}"

# Deterministic metadata: RULE_STAGE, PRIORITY_CATEGORY, and TTBL_ACTION count
# and shape expectations, pinned from the reviewed 2026-08-03 schema capture.
UA_RULE_STAGE_EXPECTED_DISTINCT_COUNT = 6
UA_RULE_STAGE_EXPECTED_RAW_COUNT = 6
UA_PRIORITY_CATEGORY_EXPECTED_DISTINCT_COUNT = 6
UA_PRIORITY_CATEGORY_EXPECTED_RAW_COUNT = 7
UA_TIMETABLE_ACTION_EXPECTED_DISTINCT_COUNT = 34
UA_TIMETABLE_ACTION_EXPECTED_RAW_COUNT = 35

# Transcribed from the RISC Preamble's "Legal Authority --" definition ("the
# section(s) of the United States Code (U.S.C.) or Public Law (Pub. L.) or the
# Executive order (EO) that authorize(s) the regulatory action") and its
# abbreviations glossary. Not machine-extracted from the PDF.
UA_LEGAL_AUTHORITY_CITATION_TYPES: tuple[str, ...] = ("U.S.C.", "Pub. L.", "E.O.")

# The publisher's own definition of each citation type, transcribed verbatim
# from the same Preamble's Section V abbreviations glossary. These were
# available all along and were simply not carried, so the three records reached
# consumers as bare tokens ("U.S.C.") with no statement of what they mean --
# while the pinned source defined each one. Verbatim, not paraphrased: this is
# publisher wording and a consumer may quote it as such. `_verify_citation_type
# _definitions` re-reads them out of the pinned PDF at parse time, so a source
# revision that rewrites a definition fails loudly instead of leaving Atlas
# publishing text the document no longer contains.
UA_LEGAL_AUTHORITY_CITATION_TYPE_DEFINITIONS: Mapping[str, str] = MappingProxyType(
    {
        "U.S.C.": (
            "The United States Code is a consolidation and codification of all general "
            "and permanent laws of the United States. The USC is divided into 50 titles, "
            "each title covering a broad area of Federal law."
        ),
        "Pub. L.": (
            "A public law is a law passed by Congress and signed by the President or "
            "enacted over his veto. It has general applicability, unlike a private law "
            "that applies only to those persons or entities specifically designated. "
            "Public laws are numbered in sequence throughout the 2-year life of each "
            "Congress; for example, Public Law 112-4 is the fourth public law of the "
            "112th Congress."
        ),
        "E.O.": (
            "An Executive order is a directive from the President to Executive agencies, "
            "issued under constitutional or statutory authority. Executive orders are "
            "published in the Federal Register and in title 3 of the Code of Federal "
            "Regulations."
        ),
    }
)

UA_PORTFOLIO_GAPS: tuple[str, ...] = (
    (
        "The reginfo.gov RIN-data schema types RULE_STAGE, PRIORITY_CATEGORY, and "
        "TTBL_ACTION as unrestricted xs:string elements with no XSD enumeration; "
        "the closed value sets RefSpec packages come from the schema's own "
        "'One of the following' documentation text, not an enforced type."
    ),
    (
        "The schema's PRIORITY_CATEGORY documentation lists 'Not Major' twice and "
        "its TTBL_ACTION documentation lists 'NPRM' twice; RefSpec folds each "
        "literal duplicate into one value rather than inventing a second meaning."
    ),
    (
        "The schema's TTBL_ACTION documentation joins two action names with a "
        "period instead of a comma ('Supplemental NPRM. FInal Action'); RefSpec "
        "preserves the literal joined text rather than guessing the intended split."
    ),
    (
        "The schema documents a 'No Stage' RULE_STAGE value that the RISC "
        "Preamble narrative's five-rulemaking-stage list does not mention."
    ),
    (
        "The LEGAL_AUTHORITY element carries no XSD documentation or enumeration "
        "and remains free text; a citation without a documented U.S.C./Pub. L./E.O. "
        "prefix is not a drift condition."
    ),
)


class UnifiedAgendaResourceError(ValueError):
    """Base class for Unified Agenda controlled-value failures."""


class UnifiedAgendaAcquisitionError(UnifiedAgendaResourceError):
    """Exact official source bytes could not be acquired safely."""


class UnifiedAgendaSourceDriftError(UnifiedAgendaResourceError):
    """A Unified Agenda source no longer matches the reviewed structure or pin."""


class UnifiedAgendaAssignmentError(UnifiedAgendaResourceError):
    """A RIN record carries an unknown or malformed source-controlled value."""


@dataclass(frozen=True, slots=True)
class UASourceDocument:
    """One official reginfo.gov document that documents controlled values."""

    document_kind: DocumentKind
    source_url: str
    filename: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "www.reginfo.gov":
            raise UnifiedAgendaAcquisitionError("source_url must be an official HTTPS www.reginfo.gov URL")
        if parsed.username is not None or parsed.password is not None:
            raise UnifiedAgendaAcquisitionError("source_url must not contain credentials")
        if not self.filename or Path(self.filename).name != self.filename:
            raise UnifiedAgendaAcquisitionError("filename must be one plain path component")


UA_REGINFO_SCHEMA = UASourceDocument(
    document_kind="reginfoSchema",
    source_url=UA_REGINFO_XSD_URL,
    filename="reginfo-rin-data-ver10262011.xsd",
)
UA_RISC_PREAMBLE = UASourceDocument(
    document_kind="riscPreamble",
    source_url=UA_RISC_PREAMBLE_URL,
    filename="risc-preamble-202210.pdf",
)


@dataclass(frozen=True, slots=True)
class UASnapshotPin:
    """Exact identity of one official reginfo.gov document response."""

    document: UASourceDocument
    retrieved_at: str
    expected_sha256: str
    expected_byte_length: int

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.expected_sha256) is None:
            raise UnifiedAgendaAcquisitionError("expected_sha256 must be a lowercase sha256:<64 hex> digest")
        if self.expected_byte_length <= 0:
            raise UnifiedAgendaAcquisitionError("expected_byte_length must be positive")
        if not self.retrieved_at:
            raise UnifiedAgendaAcquisitionError("retrieved_at must not be empty")


# Exact bytes observed on 2026-08-03. RefSpec fetched the live official
# documents rather than a re-hosted copy; see the module docstring for what
# each document does and does not establish.
UA_REGINFO_SCHEMA_2026_08_03 = UASnapshotPin(
    document=UA_REGINFO_SCHEMA,
    retrieved_at="2026-08-03T19:15:15Z",
    expected_sha256="sha256:94fdcf4b382830cc44b9956c00439dc20a9643de402c298cee71293a14153b24",
    expected_byte_length=22_730,
)
UA_RISC_PREAMBLE_2026_08_03 = UASnapshotPin(
    document=UA_RISC_PREAMBLE,
    retrieved_at="2026-08-03T19:13:31Z",
    expected_sha256="sha256:b7372fec456cf0c346bd23528ae227913e37f546bb1c03689da19ee6a44cb2a5",
    expected_byte_length=148_467,
)


@dataclass(frozen=True, slots=True)
class FetchedUADocument:
    """Provider-independent response returned by an injected fetcher."""

    body: bytes
    status_code: int
    content_type: str
    resolved_url: str


class UAFetcher(Protocol):
    """Small transport boundary for official reginfo.gov documents."""

    def fetch(self, source_url: str, *, timeout_seconds: float) -> FetchedUADocument:
        """Fetch one response while preserving its exact body bytes."""


@dataclass(frozen=True, slots=True)
class AcquiredUADocument:
    """One verified source object in the content-addressed store."""

    pin: UASnapshotPin
    path: Path
    sha256: str
    byte_length: int
    source_url: str
    resolved_url: str | None
    content_type: str
    acquisition_mode: AcquisitionMode
    cache_hit: bool
    local_source_path: Path | None


@dataclass(frozen=True, slots=True)
class UAControlledFieldValues:
    """One field's distinct, source-documented controlled value set."""

    field_name: UAControlledFieldName
    values: tuple[str, ...]
    raw_observed_count: int
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False

    def by_value(self) -> dict[str, ControlledIdentifier]:
        """Index each distinct publisher-documented value to its identifier."""

        return {identifier.value: identifier for identifier in self.identifiers}


@dataclass(frozen=True, slots=True)
class ParsedReginfoSchema:
    """A parsed, digest-pinned reginfo.gov RIN-data schema."""

    source_url: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    rule_stage: UAControlledFieldValues
    priority_category: UAControlledFieldValues
    timetable_action: UAControlledFieldValues
    gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UARiscPreambleEvidence:
    """A digest-pinned RISC Preamble used only as evidence, never parsed."""

    source_url: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    legal_authority_citation_types: tuple[str, ...]
    legal_authority_citation_type_identifiers: tuple[ControlledIdentifier, ...]
    gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UAControlPortfolio:
    """The combined controlled values available for RIN field validation."""

    rule_stage: UAControlledFieldValues
    priority_category: UAControlledFieldValues
    timetable_action: UAControlledFieldValues
    legal_authority_citation_types: tuple[str, ...]
    legal_authority_citation_type_identifiers: tuple[ControlledIdentifier, ...]
    gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UAControlledValueAssignment:
    """One RIN field value validated against its exact documented set."""

    source_field: str
    publisher_value: str
    identifiers: tuple[ControlledIdentifier, ...]
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class UALegalAuthorityCitation:
    """One free-text legal authority citation, classified where possible."""

    source_field: str
    publisher_text: str
    citation_type: str | None
    is_general_subject_concept: bool = False


@dataclass(frozen=True, slots=True)
class ValidatedUARinFields:
    """Deterministic control evidence retained from one RIN record."""

    rule_stage: UAControlledValueAssignment | None
    priority_category: UAControlledValueAssignment | None
    timetable_actions: tuple[UAControlledValueAssignment, ...]
    legal_authorities: tuple[UALegalAuthorityCitation, ...]
    gaps: tuple[str, ...]


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec SHA-256 spelling."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_resolved_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "www.reginfo.gov":
        raise UnifiedAgendaAcquisitionError("fetcher resolved_url must remain on official HTTPS www.reginfo.gov")
    if parsed.username is not None or parsed.password is not None:
        raise UnifiedAgendaAcquisitionError("fetcher resolved_url must not contain credentials")


def _verify_payload(payload: bytes, pin: UASnapshotPin, *, location: str) -> tuple[str, int]:
    byte_length = len(payload)
    if byte_length != pin.expected_byte_length:
        raise UnifiedAgendaSourceDriftError(
            f"{location} byte length drift: expected {pin.expected_byte_length}, got {byte_length}"
        )
    actual_sha256 = sha256_digest(payload)
    if actual_sha256 != pin.expected_sha256:
        raise UnifiedAgendaSourceDriftError(
            f"{location} digest drift: expected {pin.expected_sha256}, got {actual_sha256}"
        )
    return actual_sha256, byte_length


def _default_content_type(document_kind: DocumentKind) -> str:
    return "application/pdf" if document_kind == "riscPreamble" else "application/xml"


def _verify_existing(path: Path, pin: UASnapshotPin) -> AcquiredUADocument:
    if path.is_symlink() or not path.is_file():
        raise UnifiedAgendaAcquisitionError(f"content-addressed target is not a regular file: {path}")
    actual_sha256, byte_length = _verify_payload(
        path.read_bytes(),
        pin,
        location="cached Unified Agenda source",
    )
    return AcquiredUADocument(
        pin=pin,
        path=path,
        sha256=actual_sha256,
        byte_length=byte_length,
        source_url=pin.document.source_url,
        resolved_url=None,
        content_type=_default_content_type(pin.document.document_kind),
        acquisition_mode="cache",
        cache_hit=True,
        local_source_path=None,
    )


def _publish_payload(
    payload: bytes,
    pin: UASnapshotPin,
    final_path: Path,
    *,
    content_type: str,
    acquisition_mode: Literal["local", "fetcher"],
    resolved_url: str | None,
    local_source_path: Path | None,
) -> AcquiredUADocument:
    actual_sha256, byte_length = _verify_payload(
        payload,
        pin,
        location=f"{acquisition_mode} Unified Agenda source",
    )
    final_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".acquire-",
        suffix=".tmp",
        dir=final_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary_path, final_path)
        except FileExistsError:
            return _verify_existing(final_path, pin)
        return AcquiredUADocument(
            pin=pin,
            path=final_path,
            sha256=actual_sha256,
            byte_length=byte_length,
            source_url=pin.document.source_url,
            resolved_url=resolved_url,
            content_type=content_type,
            acquisition_mode=acquisition_mode,
            cache_hit=False,
            local_source_path=local_source_path,
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def acquire_unified_agenda_document(
    pin: UASnapshotPin,
    store_dir: Path,
    *,
    source_path: Path | None = None,
    fetcher: UAFetcher | None = None,
    timeout_seconds: float = 30.0,
) -> AcquiredUADocument:
    """Acquire one exact reginfo.gov document through a provider-neutral boundary."""

    if timeout_seconds <= 0:
        raise UnifiedAgendaAcquisitionError("timeout_seconds must be positive")
    if source_path is not None and fetcher is not None:
        raise UnifiedAgendaAcquisitionError("provide source_path or fetcher, not both")
    digest_hex = cast(re.Match[str], _DIGEST.fullmatch(pin.expected_sha256)).group(1)
    final_path = Path(store_dir) / "sha256" / digest_hex / pin.document.filename
    if final_path.exists() or final_path.is_symlink():
        return _verify_existing(final_path, pin)

    if source_path is not None:
        local_path = Path(source_path)
        if local_path.is_symlink() or not local_path.is_file():
            raise UnifiedAgendaAcquisitionError(f"local Unified Agenda source is not a regular file: {local_path}")
        return _publish_payload(
            local_path.read_bytes(),
            pin,
            final_path,
            content_type=_default_content_type(pin.document.document_kind),
            acquisition_mode="local",
            resolved_url=None,
            local_source_path=local_path.resolve(),
        )

    if fetcher is None:
        raise UnifiedAgendaAcquisitionError(
            "Unified Agenda documents are not cached; provide source_path or an injected fetcher"
        )
    fetched = fetcher.fetch(pin.document.source_url, timeout_seconds=timeout_seconds)
    if fetched.status_code != 200:
        raise UnifiedAgendaAcquisitionError(f"could not acquire {pin.document.source_url}: HTTP {fetched.status_code}")
    _validate_resolved_url(fetched.resolved_url)
    # The live reginfo.gov server sends no Content-Type header at all for the
    # static XSD, so an empty string is an accepted, observed shape for it.
    media_type = fetched.content_type.partition(";")[0].strip().lower()
    allowed_media_types = (
        {"application/pdf"} if pin.document.document_kind == "riscPreamble" else {"", "application/xml", "text/xml"}
    )
    if media_type not in allowed_media_types:
        raise UnifiedAgendaSourceDriftError(
            f"Unified Agenda {pin.document.document_kind} content type drifted to {fetched.content_type!r}"
        )
    return _publish_payload(
        fetched.body,
        pin,
        final_path,
        content_type=fetched.content_type,
        acquisition_mode="fetcher",
        resolved_url=fetched.resolved_url,
        local_source_path=None,
    )


def _find_documentation(root: ET.Element, container_type: str, element_name: str) -> str:
    complex_type = root.find(f"./{_XS_NS}complexType[@name='{container_type}']")
    if complex_type is None:
        raise UnifiedAgendaSourceDriftError(f"reginfo schema no longer defines complexType {container_type!r}")
    element = complex_type.find(f".//{_XS_NS}element[@name='{element_name}']")
    if element is None:
        raise UnifiedAgendaSourceDriftError(f"reginfo schema {container_type} no longer defines element {element_name}")
    documentation = element.find(f"./{_XS_NS}annotation/{_XS_NS}documentation")
    if documentation is None or not documentation.text or not documentation.text.strip():
        raise UnifiedAgendaSourceDriftError(f"reginfo schema {element_name} lost its documented option list")
    return documentation.text


def _parse_documented_options(text: str, *, quoted: bool, field_name: str) -> tuple[str, ...]:
    match = _OPTION_LIST.match(text.strip())
    if match is None:
        raise UnifiedAgendaSourceDriftError(
            f"reginfo schema {field_name} documentation no longer starts with 'One of the following'"
        )
    body = match.group("body").strip().rstrip(".").strip()
    raw = _QUOTED_OPTION.findall(body) if quoted else [part.strip() for part in body.split(",") if part.strip()]
    if not raw:
        raise UnifiedAgendaSourceDriftError(f"reginfo schema {field_name} documentation produced no option values")
    return tuple(raw)


def _controlled_field(
    field_name: UAControlledFieldName,
    raw_values: Sequence[str],
    *,
    identifier_kind: str,
    source_url: str,
    retrieved_at: str,
    source_digest: str,
) -> UAControlledFieldValues:
    # Fold literal duplicates (a documented publisher typo, see UA_PORTFOLIO_GAPS)
    # into one value while preserving first-seen order and the raw count.
    distinct = tuple(dict.fromkeys(raw_values))
    identifiers = tuple(
        ControlledIdentifier(
            value=value,
            kind=identifier_kind,
            authority_uri=UA_IDENTIFIER_AUTHORITY_URI,
            source_uri=source_url,
            observed_at=retrieved_at,
            effective_at=None,
            source_digest=source_digest,
        )
        for value in distinct
    )
    return UAControlledFieldValues(
        field_name=field_name,
        values=distinct,
        raw_observed_count=len(raw_values),
        identifiers=identifiers,
    )


_SCHEMA_FIELDS: tuple[tuple[UAControlledFieldName, str, str, bool, str, int, int], ...] = (
    (
        "ruleStage",
        "RIN_INFOType",
        "RULE_STAGE",
        True,
        "ruleStageValue",
        UA_RULE_STAGE_EXPECTED_DISTINCT_COUNT,
        UA_RULE_STAGE_EXPECTED_RAW_COUNT,
    ),
    (
        "priorityCategory",
        "RIN_INFOType",
        "PRIORITY_CATEGORY",
        True,
        "priorityCategoryValue",
        UA_PRIORITY_CATEGORY_EXPECTED_DISTINCT_COUNT,
        UA_PRIORITY_CATEGORY_EXPECTED_RAW_COUNT,
    ),
    (
        "timetableAction",
        "TIMETABLEType",
        "TTBL_ACTION",
        False,
        "timetableActionValue",
        UA_TIMETABLE_ACTION_EXPECTED_DISTINCT_COUNT,
        UA_TIMETABLE_ACTION_EXPECTED_RAW_COUNT,
    ),
)


def parse_reginfo_schema(acquired: AcquiredUADocument) -> ParsedReginfoSchema:
    """Parse the schema's documented option lists without minting new codes."""

    if acquired.pin.document.document_kind != "reginfoSchema":
        raise UnifiedAgendaResourceError("parse_reginfo_schema requires a reginfoSchema acquisition")
    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="parsed reginfo schema")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise UnifiedAgendaSourceDriftError("reginfo schema payload is not valid XML") from error

    fields: dict[UAControlledFieldName, UAControlledFieldValues] = {}
    for (
        field_name,
        container_type,
        element_name,
        quoted,
        identifier_kind,
        expected_distinct,
        expected_raw,
    ) in _SCHEMA_FIELDS:
        documentation = _find_documentation(root, container_type, element_name)
        raw_values = _parse_documented_options(documentation, quoted=quoted, field_name=element_name)
        field_values = _controlled_field(
            field_name,
            raw_values,
            identifier_kind=identifier_kind,
            source_url=acquired.pin.document.source_url,
            retrieved_at=acquired.pin.retrieved_at,
            source_digest=acquired.sha256,
        )
        if len(field_values.values) != expected_distinct or field_values.raw_observed_count != expected_raw:
            raise UnifiedAgendaSourceDriftError(
                f"{element_name} option count drift: expected {expected_distinct} distinct of "
                f"{expected_raw} raw, parsed {len(field_values.values)} distinct of "
                f"{field_values.raw_observed_count} raw"
            )
        fields[field_name] = field_values

    return ParsedReginfoSchema(
        source_url=acquired.pin.document.source_url,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        rule_stage=fields["ruleStage"],
        priority_category=fields["priorityCategory"],
        timetable_action=fields["timetableAction"],
        gaps=UA_PORTFOLIO_GAPS,
    )


def _verify_citation_type_definitions(payload: bytes) -> None:
    """Fail if the pinned Preamble no longer states each definition we publish.

    Transcribed text is only trustworthy while the document still says it. This
    re-reads the PDF and requires every published definition to appear verbatim
    after whitespace normalization, so a revision that rewrites a glossary entry
    breaks the build instead of leaving Atlas serving wording the cited source
    no longer contains.
    """

    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - dependency gate
        raise UnifiedAgendaSourceDriftError(
            "pypdf is required to verify the RISC Preamble citation-type definitions"
        ) from error
    try:
        reader = PdfReader(io.BytesIO(payload))
        text = " ".join(" ".join((page.extract_text() or "").split()) for page in reader.pages)
    except Exception as error:  # pragma: no cover - unreadable pinned source
        raise UnifiedAgendaSourceDriftError("pinned RISC Preamble is unreadable") from error
    for citation_type, definition in UA_LEGAL_AUTHORITY_CITATION_TYPE_DEFINITIONS.items():
        if definition not in text:
            raise UnifiedAgendaSourceDriftError(
                f"RISC Preamble no longer states the published definition for {citation_type!r}"
            )


def pin_risc_preamble_evidence(acquired: AcquiredUADocument) -> UARiscPreambleEvidence:
    """Verify the pinned RISC Preamble bytes and attach the transcribed
    legal-authority citation types. The PDF's prose is never machine-parsed."""

    if acquired.pin.document.document_kind != "riscPreamble":
        raise UnifiedAgendaResourceError("pin_risc_preamble_evidence requires a riscPreamble acquisition")
    payload = acquired.path.read_bytes()
    _verify_payload(payload, acquired.pin, location="pinned RISC Preamble")
    if payload[:5] != b"%PDF-":
        raise UnifiedAgendaSourceDriftError("pinned RISC Preamble no longer starts with a PDF header")

    _verify_citation_type_definitions(payload)
    identifiers = tuple(
        ControlledIdentifier(
            value=citation_type,
            kind="legalAuthorityCitationType",
            authority_uri=UA_IDENTIFIER_AUTHORITY_URI,
            source_uri=acquired.pin.document.source_url,
            observed_at=acquired.pin.retrieved_at,
            effective_at=None,
            source_digest=acquired.sha256,
        )
        for citation_type in UA_LEGAL_AUTHORITY_CITATION_TYPES
    )
    return UARiscPreambleEvidence(
        source_url=acquired.pin.document.source_url,
        retrieved_at=acquired.pin.retrieved_at,
        source_sha256=acquired.sha256,
        source_byte_length=acquired.byte_length,
        legal_authority_citation_types=UA_LEGAL_AUTHORITY_CITATION_TYPES,
        legal_authority_citation_type_identifiers=identifiers,
        gaps=UA_PORTFOLIO_GAPS,
    )


def assemble_unified_agenda_portfolio(
    reginfo_schema: ParsedReginfoSchema,
    risc_preamble: UARiscPreambleEvidence,
) -> UAControlPortfolio:
    """Combine the schema's documented fields and the preamble's citation types."""

    return UAControlPortfolio(
        rule_stage=reginfo_schema.rule_stage,
        priority_category=reginfo_schema.priority_category,
        timetable_action=reginfo_schema.timetable_action,
        legal_authority_citation_types=risc_preamble.legal_authority_citation_types,
        legal_authority_citation_type_identifiers=risc_preamble.legal_authority_citation_type_identifiers,
        gaps=UA_PORTFOLIO_GAPS,
    )


def classify_legal_authority_citation(text: str, portfolio: UAControlPortfolio) -> str | None:
    """Return the documented citation-type prefix found in free-text legal
    authority, or None when it carries none. LEGAL_AUTHORITY is unrestricted
    text, so an unmatched citation is a legitimate, non-drift outcome."""

    for citation_type in portfolio.legal_authority_citation_types:
        if citation_type in text:
            return citation_type
    return None


def _assignment(
    source_field: str,
    value: str,
    identifiers_by_value: Mapping[str, ControlledIdentifier],
) -> UAControlledValueAssignment:
    identifier = identifiers_by_value.get(value)
    if identifier is None:
        raise UnifiedAgendaAssignmentError(f"{source_field} has unknown value {value!r}")
    return UAControlledValueAssignment(
        source_field=source_field,
        publisher_value=value,
        identifiers=(identifier,),
    )


def validate_rin_controlled_fields(
    rin: Mapping[str, object],
    portfolio: UAControlPortfolio,
) -> ValidatedUARinFields:
    """Validate one RIN record's deterministic controls against the exact
    pinned schema and preamble evidence. Never promotes a value to a subject."""

    rule_stage_lookup = portfolio.rule_stage.by_value()
    priority_lookup = portfolio.priority_category.by_value()
    timetable_lookup = portfolio.timetable_action.by_value()

    rule_stage: UAControlledValueAssignment | None = None
    raw_rule_stage = rin.get("RULE_STAGE")
    if raw_rule_stage is not None:
        if not isinstance(raw_rule_stage, str):
            raise UnifiedAgendaAssignmentError("RULE_STAGE must be a string when present")
        rule_stage = _assignment("RULE_STAGE", raw_rule_stage, rule_stage_lookup)

    priority_category: UAControlledValueAssignment | None = None
    raw_priority = rin.get("PRIORITY_CATEGORY")
    if raw_priority is not None:
        if not isinstance(raw_priority, str):
            raise UnifiedAgendaAssignmentError("PRIORITY_CATEGORY must be a string when present")
        priority_category = _assignment("PRIORITY_CATEGORY", raw_priority, priority_lookup)

    raw_timetable = rin.get("TIMETABLE_LIST")
    if raw_timetable is None:
        raw_timetable = []
    if not isinstance(raw_timetable, list):
        raise UnifiedAgendaAssignmentError("TIMETABLE_LIST must be an array")
    timetable_actions: list[UAControlledValueAssignment] = []
    for ordinal, entry in enumerate(raw_timetable, start=1):
        if not isinstance(entry, Mapping):
            raise UnifiedAgendaAssignmentError(f"TIMETABLE_LIST[{ordinal}] must be an object")
        raw_action = entry.get("TTBL_ACTION")
        if raw_action is None:
            continue
        if not isinstance(raw_action, str):
            raise UnifiedAgendaAssignmentError(f"TIMETABLE_LIST[{ordinal}].TTBL_ACTION must be a string")
        timetable_actions.append(
            _assignment(
                f"TIMETABLE_LIST[{ordinal - 1}].TTBL_ACTION",
                raw_action,
                timetable_lookup,
            )
        )

    raw_legal_authorities = rin.get("LEGAL_AUTHORITY_LIST")
    if raw_legal_authorities is None:
        raw_legal_authorities = []
    if not isinstance(raw_legal_authorities, list):
        raise UnifiedAgendaAssignmentError("LEGAL_AUTHORITY_LIST must be an array")
    legal_authorities: list[UALegalAuthorityCitation] = []
    for ordinal, text in enumerate(raw_legal_authorities, start=1):
        if not isinstance(text, str) or not text.strip():
            raise UnifiedAgendaAssignmentError(f"LEGAL_AUTHORITY_LIST[{ordinal}] must be non-empty text")
        legal_authorities.append(
            UALegalAuthorityCitation(
                source_field=f"LEGAL_AUTHORITY_LIST[{ordinal - 1}]",
                publisher_text=text,
                citation_type=classify_legal_authority_citation(text, portfolio),
            )
        )

    return ValidatedUARinFields(
        rule_stage=rule_stage,
        priority_category=priority_category,
        timetable_actions=tuple(timetable_actions),
        legal_authorities=tuple(legal_authorities),
        gaps=UA_PORTFOLIO_GAPS,
    )
