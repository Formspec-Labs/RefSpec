"""Federal Register List of Subjects evidence linked to CFR references.

The eCFR structure and full-text APIs publish CFR structure and regulatory
text.  They do not publish a current ``List of Subjects`` for each CFR part.
FederalRegister.gov document JSON is the machine-readable source that carries
both a document's ``topics`` (the published List of Subjects terms) and its
``cfr_references``.

This module preserves that document-level shape.  It does not assign every
topic independently to every cited CFR part when a document cites more than
one part, and it does not turn topic labels into concept identifiers.  The
result is source-assigned filing evidence for candidate ranking and
evaluation, not a governed vocabulary or accepted-output authority.

Importing this module performs no network access.  Callers provide exact
publisher bytes, normally captured through the shared Zyte transport.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

from refspec.storage import canonical_json

ECFR_API_DOCUMENTATION_URL = "https://www.ecfr.gov/developers/documentation/api/v1"
ECFR_API_OPENAPI_URL = "https://www.ecfr.gov/developers/documentation/api/v1.json"
ECFR_AGENCIES_URL = "https://www.ecfr.gov/api/admin/v1/agencies.json"
ECFR_TITLES_URL = "https://www.ecfr.gov/api/versioner/v1/titles.json"
ECFR_STRUCTURE_TITLE_1_2026_07_31_URL = "https://www.ecfr.gov/api/versioner/v1/structure/2026-07-31/title-1.json"
ECFR_FULL_TITLE_1_PART_18_2026_07_31_URL = "https://www.ecfr.gov/api/versioner/v1/full/2026-07-31/title-1.xml?part=18"
FEDERAL_REGISTER_DOCUMENT_2026_15493_URL = "https://www.federalregister.gov/api/v1/documents/2026-15493.json"
FEDERAL_REGISTER_DOCUMENT_96_32865_URL = "https://www.federalregister.gov/api/v1/documents/96-32865.json"
ASSIGNMENT_EVIDENCE_VERSION = "2.0"
CFR_LANGUAGE = "en"

AssignmentRole = Literal["sourceAssignedFilingEvidence"]
IdentityStatus = Literal["publisherIdentifierAbsent"]

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DOCUMENT_NUMBER = re.compile(r"^[A-Za-z0-9-]+$")


class CFRListOfSubjectsError(ValueError):
    """Publisher bytes cannot be represented without guessing."""


class CFRSourceDriftError(CFRListOfSubjectsError):
    """A publisher response no longer matches the reviewed source shape."""


class CFRPromotionError(CFRListOfSubjectsError):
    """Document evidence was requested as a governed concept release."""


def sha256_digest(payload: bytes) -> str:
    """Return the canonical RefSpec spelling for a SHA-256 digest."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _json_object(payload: bytes, label: str) -> Mapping[str, Any]:
    if not isinstance(payload, bytes) or not payload:
        raise CFRSourceDriftError(f"{label} must be non-empty bytes")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CFRSourceDriftError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, Mapping):
        raise CFRSourceDriftError(f"{label} root must be an object")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CFRSourceDriftError(f"{label} must be non-empty text")
    return value


def _official_url(value: object, label: str, hosts: frozenset[str]) -> str:
    text = _required_text(value, label)
    parsed = urlsplit(text)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise CFRSourceDriftError(f"{label} must remain on its official HTTPS host")
    return text


def _find_structure_part(value: object, *, part: str) -> tuple[Mapping[str, Any], ...]:
    matches: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        if value.get("type") == "part" and str(value.get("identifier")) == part:
            matches.append(value)
        for child in value.values():
            matches.extend(_find_structure_part(child, part=part))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            matches.extend(_find_structure_part(child, part=part))
    return tuple(matches)


def _find_structure_paths(
    value: object,
    *,
    part: str,
    ancestors: tuple[Mapping[str, Any], ...] = (),
) -> tuple[tuple[Mapping[str, Any], ...], ...]:
    paths: list[tuple[Mapping[str, Any], ...]] = []
    if isinstance(value, Mapping):
        current = (*ancestors, value)
        if value.get("type") == "part" and str(value.get("identifier")) == part:
            paths.append(current)
        for child in value.values():
            paths.extend(_find_structure_paths(child, part=part, ancestors=current))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            paths.extend(_find_structure_paths(child, part=part, ancestors=ancestors))
    return tuple(paths)


def _flatten_agencies(value: Sequence[object]) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for ordinal, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise CFRSourceDriftError(f"agencies[{ordinal}] must be an object")
        _required_text(item.get("name"), f"agencies[{ordinal}].name")
        _required_text(item.get("slug"), f"agencies[{ordinal}].slug")
        children = item.get("children", [])
        references = item.get("cfr_references")
        if not isinstance(children, list) or not isinstance(references, list):
            raise CFRSourceDriftError(f"agencies[{ordinal}] children and cfr_references must be arrays")
        rows.append(item)
        rows.extend(_flatten_agencies(children))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class EcfrPartSourceInspection:
    """What the two official eCFR APIs do and do not expose for one part."""

    cfr_title: int
    cfr_part: str
    part_label: str
    section_count: int
    chapter: str
    catalog_date: str
    title_name: str
    title_latest_issue_date: str
    title_up_to_date_as_of: str
    title_count: int
    top_level_agency_count: int
    total_agency_count: int
    responsible_agencies: tuple[str, ...]
    titles_source_sha256: str
    titles_source_byte_length: int
    agencies_source_sha256: str
    agencies_source_byte_length: int
    structure_source_sha256: str
    structure_source_byte_length: int
    full_text_source_sha256: str
    full_text_source_byte_length: int
    list_requirement_present: bool
    published_subject_assignment_count: int
    assignment_source: Literal["federalRegisterDocumentJson"] = "federalRegisterDocumentJson"


def inspect_ecfr_part_sources(
    structure_payload: bytes,
    full_text_payload: bytes,
    titles_payload: bytes,
    agencies_payload: bytes,
    *,
    cfr_title: int,
    cfr_part: str,
) -> EcfrPartSourceInspection:
    """Inspect exact eCFR API bytes without treating rule text as assignments."""

    structure = _json_object(structure_payload, "eCFR structure response")
    if structure.get("type") != "title" or structure.get("identifier") != str(cfr_title):
        raise CFRSourceDriftError("eCFR structure response identifies a different title")
    paths = _find_structure_paths(structure, part=cfr_part)
    if len(paths) != 1:
        raise CFRSourceDriftError(f"eCFR structure must contain exactly one Part {cfr_part}; found {len(paths)}")
    path = paths[0]
    part = path[-1]
    chapters = tuple(item for item in path if item.get("type") == "chapter")
    if len(chapters) != 1:
        raise CFRSourceDriftError("eCFR part must have exactly one chapter ancestor")
    chapter = _required_text(chapters[0].get("identifier"), "eCFR chapter identifier")
    children = part.get("children")
    if not isinstance(children, list):
        raise CFRSourceDriftError("eCFR part children must be an array")
    sections = tuple(child for child in children if isinstance(child, Mapping) and child.get("type") == "section")
    if not sections:
        raise CFRSourceDriftError("eCFR part contains no section rows")

    try:
        root = ElementTree.fromstring(full_text_payload)
    except (ElementTree.ParseError, TypeError) as error:
        raise CFRSourceDriftError("eCFR full-text response is not valid XML") from error
    if root.tag != "DIV5" or root.attrib.get("TYPE") != "PART" or root.attrib.get("N") != cfr_part:
        raise CFRSourceDriftError("eCFR full-text XML identifies a different part")
    normalized_text = " ".join("".join(root.itertext()).split())
    requirement_present = "Federal Register Thesaurus" in normalized_text and "list of index terms" in normalized_text
    if not requirement_present:
        raise CFRSourceDriftError("eCFR full text no longer contains the List of Subjects requirement")

    # The reviewed API has no subject-assignment element.  If one appears,
    # fail so the parser can be updated instead of silently reporting zero.
    subject_elements = [
        element for element in root.iter() if element.tag.casefold() in {"subject", "subjects", "list-of-subjects"}
    ]
    if subject_elements:
        raise CFRSourceDriftError("eCFR full text now exposes subject elements; review the source model")

    titles_response = _json_object(titles_payload, "eCFR titles response")
    titles = titles_response.get("titles")
    meta = titles_response.get("meta")
    if not isinstance(titles, list) or not isinstance(meta, Mapping):
        raise CFRSourceDriftError("eCFR titles response must contain titles and meta")
    title_rows = [item for item in titles if isinstance(item, Mapping) and item.get("number") == cfr_title]
    if len(title_rows) != 1:
        raise CFRSourceDriftError(f"eCFR titles response must contain Title {cfr_title} exactly once")
    title_row = title_rows[0]
    catalog_date = _required_text(meta.get("date"), "eCFR titles meta.date")
    title_up_to_date = _required_text(
        title_row.get("up_to_date_as_of"),
        "eCFR title up_to_date_as_of",
    )
    if catalog_date != title_up_to_date:
        raise CFRSourceDriftError("eCFR Title 1 is not current for the catalog date")
    if meta.get("import_in_progress") is not False:
        raise CFRSourceDriftError("eCFR title import is in progress")

    agencies_response = _json_object(agencies_payload, "eCFR agencies response")
    top_level_agencies = agencies_response.get("agencies")
    if not isinstance(top_level_agencies, list):
        raise CFRSourceDriftError("eCFR agencies response must contain an agencies array")
    all_agencies = _flatten_agencies(top_level_agencies)
    responsible: list[str] = []
    for agency in all_agencies:
        references = agency["cfr_references"]
        matches_part_or_chapter = any(
            isinstance(reference, Mapping)
            and reference.get("title") == cfr_title
            and (
                str(reference.get("part")) == cfr_part
                if reference.get("part") is not None
                else reference.get("chapter") == chapter
            )
            for reference in references
        )
        if matches_part_or_chapter:
            responsible.append(_required_text(agency.get("name"), "agency.name"))
    if not responsible:
        raise CFRSourceDriftError("eCFR agencies response identifies no responsible agency")

    return EcfrPartSourceInspection(
        cfr_title=cfr_title,
        cfr_part=cfr_part,
        part_label=_required_text(part.get("label"), "eCFR part label"),
        section_count=len(sections),
        chapter=chapter,
        catalog_date=catalog_date,
        title_name=_required_text(title_row.get("name"), "eCFR title name"),
        title_latest_issue_date=_required_text(
            title_row.get("latest_issue_date"),
            "eCFR title latest_issue_date",
        ),
        title_up_to_date_as_of=title_up_to_date,
        title_count=len(titles),
        top_level_agency_count=len(top_level_agencies),
        total_agency_count=len(all_agencies),
        responsible_agencies=tuple(responsible),
        titles_source_sha256=sha256_digest(titles_payload),
        titles_source_byte_length=len(titles_payload),
        agencies_source_sha256=sha256_digest(agencies_payload),
        agencies_source_byte_length=len(agencies_payload),
        structure_source_sha256=sha256_digest(structure_payload),
        structure_source_byte_length=len(structure_payload),
        full_text_source_sha256=sha256_digest(full_text_payload),
        full_text_source_byte_length=len(full_text_payload),
        list_requirement_present=True,
        published_subject_assignment_count=0,
    )


@dataclass(frozen=True, slots=True)
class CFRReference:
    """One publisher-authored CFR reference on a Federal Register document."""

    title: int
    part: str
    chapter: str | None
    citation_url: str | None

    @property
    def citation(self) -> str:
        return f"{self.title} CFR Part {self.part}"


@dataclass(frozen=True, slots=True)
class CFRSubjectTermEvidence:
    """One document-level List of Subjects label, without invented identity."""

    official_label: str
    language: str
    source_ordinal: int
    record_iri: str
    identity_status: IdentityStatus = "publisherIdentifierAbsent"


@dataclass(frozen=True, slots=True)
class CFRAssignmentReadiness:
    """Why source-assigned filing evidence cannot become a concept release."""

    document_number: str
    source_term_count: int
    source_sha256: str
    ready: bool = False
    blockers: tuple[str, ...] = (
        "Federal Register document topics are filing evidence, not a separately governed concept scheme",
        "topic labels have no publisher term identifiers in the document response",
    )

    def require_ready(self) -> None:
        if not self.ready:
            raise CFRPromotionError("; ".join(self.blockers))


@dataclass(frozen=True, slots=True)
class FederalRegisterDocumentAssignments:
    """Topics and CFR references preserved at their publisher-authored scope."""

    document_number: str
    publication_date: str
    document_type: str
    title: str
    json_url: str
    html_url: str
    source_sha256: str
    source_byte_length: int
    cfr_references: tuple[CFRReference, ...]
    terms: tuple[CFRSubjectTermEvidence, ...]
    readiness: CFRAssignmentReadiness
    role: AssignmentRole = "sourceAssignedFilingEvidence"

    @property
    def assignment_count(self) -> int:
        return len(self.terms)


def _parse_cfr_reference(value: object, ordinal: int) -> CFRReference:
    label = f"cfr_references[{ordinal}]"
    if not isinstance(value, Mapping):
        raise CFRSourceDriftError(f"{label} must be an object")
    if set(value) != {"chapter", "citation_url", "part", "title"}:
        raise CFRSourceDriftError(f"{label} fields changed")
    title = value["title"]
    if not isinstance(title, int) or isinstance(title, bool) or title <= 0:
        raise CFRSourceDriftError(f"{label}.title must be a positive integer")
    raw_part = value["part"]
    if isinstance(raw_part, bool) or not isinstance(raw_part, (int, str)):
        raise CFRSourceDriftError(f"{label}.part must be an integer or string")
    part = str(raw_part).strip()
    if not part:
        raise CFRSourceDriftError(f"{label}.part must not be empty")
    chapter = value["chapter"]
    if chapter is not None and not isinstance(chapter, str):
        raise CFRSourceDriftError(f"{label}.chapter must be text or null")
    citation_url = value["citation_url"]
    if citation_url is not None:
        citation_url = _official_url(
            citation_url,
            f"{label}.citation_url",
            frozenset({"ecfr.gov", "www.ecfr.gov"}),
        )
    return CFRReference(title=title, part=part, chapter=chapter, citation_url=citation_url)


def _record_iri(document_number: str, source_sha256: str, ordinal: int) -> str:
    digest = source_sha256.removeprefix("sha256:")
    return f"urn:ref:federal-register-list-of-subjects-record:{digest}:{quote(document_number, safe='')}:{ordinal}"


def parse_federal_register_document_assignments(
    payload: bytes,
    *,
    expected_document_number: str | None = None,
) -> FederalRegisterDocumentAssignments:
    """Parse one exact Federal Register document JSON response."""

    value = _json_object(payload, "Federal Register document response")
    required = {
        "document_number",
        "publication_date",
        "type",
        "title",
        "json_url",
        "html_url",
        "topics",
        "cfr_references",
    }
    missing = sorted(required - set(value))
    if missing:
        raise CFRSourceDriftError(f"Federal Register document fields are missing: {missing}")
    document_number = _required_text(value["document_number"], "document_number")
    if _DOCUMENT_NUMBER.fullmatch(document_number) is None:
        raise CFRSourceDriftError("document_number has an unsupported shape")
    if expected_document_number is not None and document_number != expected_document_number:
        raise CFRSourceDriftError(f"expected document {expected_document_number!r}, got {document_number!r}")
    publication_date = _required_text(value["publication_date"], "publication_date")
    if _ISO_DATE.fullmatch(publication_date) is None:
        raise CFRSourceDriftError("publication_date must be YYYY-MM-DD")
    json_url = _official_url(
        value["json_url"],
        "json_url",
        frozenset({"federalregister.gov", "www.federalregister.gov"}),
    )
    html_url = _official_url(
        value["html_url"],
        "html_url",
        frozenset({"federalregister.gov", "www.federalregister.gov"}),
    )

    raw_references = value["cfr_references"]
    if not isinstance(raw_references, list) or not raw_references:
        raise CFRSourceDriftError("cfr_references must be a non-empty array")
    references = tuple(_parse_cfr_reference(item, ordinal) for ordinal, item in enumerate(raw_references))
    if len({(item.title, item.part, item.chapter) for item in references}) != len(references):
        raise CFRSourceDriftError("cfr_references contains a duplicate")

    raw_topics = value["topics"]
    if not isinstance(raw_topics, list):
        raise CFRSourceDriftError("topics must be an array")
    labels = tuple(_required_text(item, f"topics[{ordinal}]") for ordinal, item in enumerate(raw_topics))
    if len(set(labels)) != len(labels):
        raise CFRSourceDriftError("topics contains a duplicate label")
    source_sha256 = sha256_digest(payload)
    terms = tuple(
        CFRSubjectTermEvidence(
            official_label=label,
            language=CFR_LANGUAGE,
            source_ordinal=ordinal,
            record_iri=_record_iri(document_number, source_sha256, ordinal),
        )
        for ordinal, label in enumerate(labels, start=1)
    )
    return FederalRegisterDocumentAssignments(
        document_number=document_number,
        publication_date=publication_date,
        document_type=_required_text(value["type"], "type"),
        title=_required_text(value["title"], "title"),
        json_url=json_url,
        html_url=html_url,
        source_sha256=source_sha256,
        source_byte_length=len(payload),
        cfr_references=references,
        terms=terms,
        readiness=CFRAssignmentReadiness(
            document_number=document_number,
            source_term_count=len(terms),
            source_sha256=source_sha256,
        ),
    )


def cfr_list_of_subjects_assignment_evidence(
    parsed: FederalRegisterDocumentAssignments,
) -> dict[str, Any]:
    """Return deterministic document-level evidence without concept claims."""

    return {
        "schemaVersion": ASSIGNMENT_EVIDENCE_VERSION,
        "evidenceKind": "federalRegisterDocumentListOfSubjects",
        "role": parsed.role,
        "documentNumber": parsed.document_number,
        "publicationDate": parsed.publication_date,
        "documentType": parsed.document_type,
        "documentTitle": parsed.title,
        "sourceUrl": parsed.json_url,
        "sourceSha256": parsed.source_sha256,
        "sourceByteLength": parsed.source_byte_length,
        "cfrReferences": [
            {
                "title": item.title,
                "part": item.part,
                "chapter": item.chapter,
                "citationUrl": item.citation_url,
            }
            for item in parsed.cfr_references
        ],
        "termCount": len(parsed.terms),
        "terms": [
            {
                "id": item.record_iri,
                "label": item.official_label,
                "language": item.language,
                "sourceOrdinal": item.source_ordinal,
                "identityStatus": item.identity_status,
            }
            for item in parsed.terms
        ],
        "scopeNote": (
            "Topics and CFR references are document-level arrays; this evidence does not "
            "assert a topic-to-part pairing when the document cites multiple CFR parts."
        ),
        "conceptIdentityClaimed": False,
    }


def cfr_list_of_subjects_assignment_evidence_bytes(
    parsed: FederalRegisterDocumentAssignments,
) -> bytes:
    """Serialize the source evidence deterministically."""

    return canonical_json(cfr_list_of_subjects_assignment_evidence(parsed)).encode("utf-8") + b"\n"


__all__ = [
    "ASSIGNMENT_EVIDENCE_VERSION",
    "CFR_LANGUAGE",
    "ECFR_AGENCIES_URL",
    "ECFR_API_DOCUMENTATION_URL",
    "ECFR_API_OPENAPI_URL",
    "ECFR_FULL_TITLE_1_PART_18_2026_07_31_URL",
    "ECFR_STRUCTURE_TITLE_1_2026_07_31_URL",
    "ECFR_TITLES_URL",
    "FEDERAL_REGISTER_DOCUMENT_96_32865_URL",
    "FEDERAL_REGISTER_DOCUMENT_2026_15493_URL",
    "AssignmentRole",
    "CFRAssignmentReadiness",
    "CFRListOfSubjectsError",
    "CFRPromotionError",
    "CFRReference",
    "CFRSourceDriftError",
    "CFRSubjectTermEvidence",
    "EcfrPartSourceInspection",
    "FederalRegisterDocumentAssignments",
    "IdentityStatus",
    "cfr_list_of_subjects_assignment_evidence",
    "cfr_list_of_subjects_assignment_evidence_bytes",
    "inspect_ecfr_part_sources",
    "parse_federal_register_document_assignments",
    "sha256_digest",
]
