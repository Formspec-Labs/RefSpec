"""Pinned reader for Northwestern's 2021 MeSH-to-LCSH MARCXML mapping.

The source is a third-party mapping: Northwestern owns neither MeSH nor LCSH.
MARC linking fields are not SKOS predicates, so this reader records an explicit
translation for each admitted field.  It translates only field 750 rows that
identify one MeSH descriptor and one LCSH subject authority.  Subdivision
fields (780), complex search instructions (788), compound MeSH identifiers,
local targets, and non-LCSH target indicators remain counted refusals.
"""

from __future__ import annotations

import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from rdflib.namespace import SKOS

LCSH_MESH_MAPPING_FILENAME = "mesh-lcsh-mapping-20210325.zip"
LCSH_MESH_MAPPING_SOURCE_URL = (
    "https://prism.northwestern.edu/records/abga7-chg83/files/MeSH-LCSH%20mapping%2820210325xmlzip%29.zip?download=1"
)
LCSH_MESH_MAPPING_LANDING_PAGE_URL = "https://prism.northwestern.edu/records/abga7-chg83"
LCSH_MESH_MAPPING_METADATA_URL = "https://prism.northwestern.edu/api/records/abga7-chg83"
LCSH_MESH_MAPPING_DOI = "https://doi.org/10.18131/g3-8qqd-5b04"
LCSH_MESH_MAPPING_RETRIEVED_AT = "2026-08-15T22:50:20Z"
LCSH_MESH_MAPPING_SHA256 = "sha256:0dac4ce471e196c2bf5b86d93e760192a8969ce5f69ce2fe5e55a7d7bfed9f03"
LCSH_MESH_MAPPING_BYTE_LENGTH = 3_851_889
LCSH_MESH_MAPPING_MEMBER = "MeSH-LCSH mapping(20210325xml).xml"
LCSH_MESH_MAPPING_MEMBER_SHA256 = "sha256:02449d5f18dd8815f51358bb3372e48aa7269f4ae41e50d3cdd3ca3ed206fd63"
LCSH_MESH_MAPPING_MEMBER_BYTE_LENGTH = 40_947_976
LCSH_MESH_MAPPING_ISSUED = "2021-03-31"
LCSH_MESH_MAPPING_VERSION = "v1.0.0"

# Verbatim publisher metadata from the DOI release's current record API.
LCSH_MESH_LICENSE_STATEMENT = "Creative Commons Public Domain Mark 1.0"
LCSH_MESH_LICENSE_URL = "http://creativecommons.org/publicdomain/mark/1.0"
LCSH_MESH_WORKING_FILE_RIGHTS_NOTE = (
    "Current working-file rights are unverified; this release uses only the pinned legacy DOI v1.0.0 ZIP."
)

PUBLISHER_DECLARED_RECORD_COUNT = 13_453
EXPECTED_RECORD_COUNT = 13_329
EXPECTED_LINKING_RECORD_COUNT = 13_286
EXPECTED_LINKING_FIELD_COUNT = 14_195
EXPECTED_ACCEPTED_SOURCE_FIELD_COUNT = 13_278
EXPECTED_UNIQUE_MAPPING_COUNT = 13_270
EXPECTED_REFUSAL_COUNT = 917
EXPECTED_PREDICATE_COUNTS = MappingProxyType(
    {
        str(SKOS.exactMatch): 13_069,
        str(SKOS.broadMatch): 135,
        str(SKOS.narrowMatch): 35,
        str(SKOS.relatedMatch): 31,
    }
)
EXPECTED_REFUSAL_COUNTS = MappingProxyType(
    {
        "complex-linking-field": 174,
        "no-single-lcsh-control-number": 299,
        "subject-not-mesh-descriptor": 231,
        "subdivision-linking-field": 134,
        "target-vocabulary-not-lcsh": 79,
    }
)

MESH_DESCRIPTOR_PREFIX = "https://id.nlm.nih.gov/mesh/"
LCSH_SUBJECT_PREFIX = "http://id.loc.gov/authorities/subjects/"
MARC_750_FIELD_IRI = "https://www.loc.gov/marc/authority/ad750.html"
MARC_780_FIELD_IRI = "https://www.loc.gov/marc/authority/ad780.html"
MARC_788_FIELD_IRI = "https://www.loc.gov/marc/authority/ad788.html"

MARC_RELATION_CODE_TO_SKOS = MappingProxyType(
    {
        "BM": str(SKOS.broadMatch),
        "NM": str(SKOS.narrowMatch),
        "RM": str(SKOS.relatedMatch),
    }
)
MARC_RELATION_TEXT_TO_SKOS = MappingProxyType(
    {
        "Broader mapping": str(SKOS.broadMatch),
        "Narrower mapping": str(SKOS.narrowMatch),
        "Related mapping": str(SKOS.relatedMatch),
    }
)

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_MESH_DESCRIPTOR_CONTROL = re.compile(r"^\(DNLM\)(D\d{6,})$")
_LCSH_CONTROL = re.compile(r"^(?:\(DLC\))*\s*sh\s*(\d{8,10})$", re.IGNORECASE)
_LINKING_FIELD_TAGS = frozenset({"750", "780", "788"})
_ENTITY_GUARD_WINDOW_BYTES = 16_384


class LcshMeshMappingError(ValueError):
    """The pinned MARCXML mapping cannot be represented without guessing."""


@dataclass(frozen=True, slots=True)
class MarcSubfield:
    """One ordered MARC subfield exactly as published."""

    code: str
    value: str


@dataclass(frozen=True, slots=True)
class MarcMappingField:
    """One source linking field and its position in a MARC authority record."""

    record_index: int
    mapping_field_index: int
    local_record_number: str
    tag: str
    indicator_1: str
    indicator_2: str
    subfields: tuple[MarcSubfield, ...]

    @property
    def source_predicate_iri(self) -> str:
        return {
            "750": MARC_750_FIELD_IRI,
            "780": MARC_780_FIELD_IRI,
            "788": MARC_788_FIELD_IRI,
        }[self.tag]

    def native_payload(self) -> dict[str, object]:
        return {
            "indicator1": self.indicator_1,
            "indicator2": self.indicator_2,
            "localRecordNumber": self.local_record_number,
            "mappingFieldIndex": self.mapping_field_index,
            "recordIndex": self.record_index,
            "subfields": [{"code": item.code, "value": item.value} for item in self.subfields],
            "tag": self.tag,
        }


@dataclass(frozen=True, slots=True)
class LcshMeshMapping:
    """One unique adopted SKOS claim with every supporting source field."""

    subject_iri: str
    predicate_iri: str
    object_iri: str
    source_predicate_iri: str
    translation_basis: str
    source_fields: tuple[MarcMappingField, ...]


@dataclass(frozen=True, slots=True)
class LcshMeshRefusal:
    """One linking field that cannot be translated without adding meaning."""

    reason: str
    source_field: MarcMappingField


@dataclass(frozen=True, slots=True)
class LcshMeshMappingCapture:
    """The complete field accounting from one exact MARCXML ZIP."""

    source_url: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    member_sha256: str
    member_byte_length: int
    record_count: int
    linking_record_count: int
    linking_field_count: int
    accepted_source_field_count: int
    mappings: tuple[LcshMeshMapping, ...]
    refusals: tuple[LcshMeshRefusal, ...]

    @property
    def predicate_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(row.predicate_iri for row in self.mappings).items()))

    @property
    def refusal_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(item.reason for item in self.refusals).items()))


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _verify_pin(
    payload: bytes,
    *,
    expected_sha256: str,
    expected_byte_length: int,
    label: str,
) -> None:
    if _DIGEST.fullmatch(expected_sha256) is None:
        raise LcshMeshMappingError(f"{label} expected digest is not canonical SHA-256")
    observed_sha256 = _digest(payload)
    if len(payload) != expected_byte_length:
        raise LcshMeshMappingError(f"{label} byte length drift: expected {expected_byte_length}, got {len(payload)}")
    if observed_sha256 != expected_sha256:
        raise LcshMeshMappingError(f"{label} digest drift: expected {expected_sha256}, got {observed_sha256}")


def _record_number(record: ElementTree.Element, *, record_index: int) -> str:
    values = [node.text or "" for node in record.findall("controlfield[@tag='001']")]
    if len(values) != 1 or not values[0]:
        raise LcshMeshMappingError(f"MARCXML record {record_index} must have one non-empty field 001")
    return values[0]


def _mapping_field(
    field: ElementTree.Element,
    *,
    record_index: int,
    mapping_field_index: int,
    local_record_number: str,
) -> MarcMappingField:
    tag = field.attrib.get("tag")
    indicator_1 = field.attrib.get("ind1")
    indicator_2 = field.attrib.get("ind2")
    if tag not in _LINKING_FIELD_TAGS or indicator_1 is None or indicator_2 is None:
        raise LcshMeshMappingError(f"MARCXML record {record_index} linking field has malformed tag or indicators")
    subfields: list[MarcSubfield] = []
    for node in field.findall("subfield"):
        code = node.attrib.get("code")
        if code is None or len(code) != 1:
            raise LcshMeshMappingError(f"MARCXML record {record_index} field {tag} has a malformed subfield code")
        subfields.append(MarcSubfield(code=code, value=node.text or ""))
    return MarcMappingField(
        record_index=record_index,
        mapping_field_index=mapping_field_index,
        local_record_number=local_record_number,
        tag=tag,
        indicator_1=indicator_1,
        indicator_2=indicator_2,
        subfields=tuple(subfields),
    )


def _values(field: MarcMappingField, code: str) -> tuple[str, ...]:
    return tuple(item.value for item in field.subfields if item.code == code)


def _mesh_descriptor_iri(record: ElementTree.Element) -> str | None:
    values = {
        match.group(1)
        for node in record.findall("datafield[@tag='035']/subfield[@code='a']")
        if (match := _MESH_DESCRIPTOR_CONTROL.fullmatch(node.text or "")) is not None
    }
    if len(values) != 1:
        return None
    return MESH_DESCRIPTOR_PREFIX + next(iter(values))


def _translated_predicate(field: MarcMappingField) -> tuple[str, str] | None:
    relation_codes = set(_values(field, "4"))
    if relation_codes:
        if len(relation_codes) != 1:
            return None
        relation_code = next(iter(relation_codes))
        predicate = MARC_RELATION_CODE_TO_SKOS.get(relation_code)
        return (predicate, f"MARC 750 $4 {relation_code}") if predicate is not None else None
    relation_texts = set(_values(field, "i"))
    if not relation_texts:
        return str(SKOS.exactMatch), "MARC 750 corresponding heading"
    if len(relation_texts) != 1:
        return None
    relation_text = next(iter(relation_texts))
    predicate = MARC_RELATION_TEXT_TO_SKOS.get(relation_text)
    return (predicate, f"MARC 750 $i {relation_text}") if predicate is not None else None


def _lcsh_subject_iri(field: MarcMappingField) -> str | None:
    identifiers = {
        LCSH_SUBJECT_PREFIX + "sh" + match.group(1)
        for value in _values(field, "0")
        if (match := _LCSH_CONTROL.fullmatch(value)) is not None
    }
    return next(iter(identifiers)) if len(identifiers) == 1 else None


def parse_lcsh_mesh_marcxml(
    payload: bytes,
    *,
    source_url: str = LCSH_MESH_MAPPING_SOURCE_URL,
    retrieved_at: str = LCSH_MESH_MAPPING_RETRIEVED_AT,
    source_sha256: str | None = None,
    source_byte_length: int | None = None,
) -> LcshMeshMappingCapture:
    """Parse MARCXML and account for every 750, 780, and 788 field."""

    if not isinstance(payload, bytes):
        raise TypeError("LCSH--MeSH MARCXML must be bytes")
    if b"<!ENTITY" in payload[:_ENTITY_GUARD_WINDOW_BYTES].upper():
        raise LcshMeshMappingError("LCSH--MeSH MARCXML must not declare XML entities")

    record_count = 0
    linking_record_count = 0
    linking_field_count = 0
    accepted_source_field_count = 0
    refusals: list[LcshMeshRefusal] = []
    grouped: dict[
        tuple[str, str, str],
        tuple[str, str, list[MarcMappingField]],
    ] = {}
    try:
        parser = ElementTree.iterparse(io.BytesIO(payload), events=("start", "end"))
        _event, root = next(parser)
        if root.tag != "collection":
            raise LcshMeshMappingError(f"MARCXML root must be collection, got {root.tag!r}")
        for event, record in parser:
            if event != "end" or record.tag != "record":
                continue
            record_count += 1
            local_record_number = _record_number(record, record_index=record_count)
            mesh_iri = _mesh_descriptor_iri(record)
            fields = [node for node in record.findall("datafield") if node.attrib.get("tag") in _LINKING_FIELD_TAGS]
            linking_record_count += bool(fields)
            linking_field_count += len(fields)
            for mapping_field_index, field_node in enumerate(fields, start=1):
                field = _mapping_field(
                    field_node,
                    record_index=record_count,
                    mapping_field_index=mapping_field_index,
                    local_record_number=local_record_number,
                )
                reason: str | None = None
                if mesh_iri is None:
                    reason = "subject-not-mesh-descriptor"
                elif field.tag == "780":
                    reason = "subdivision-linking-field"
                elif field.tag == "788":
                    reason = "complex-linking-field"
                elif field.indicator_2 != "0":
                    reason = "target-vocabulary-not-lcsh"
                else:
                    translation = _translated_predicate(field)
                    if translation is None:
                        reason = "unsupported-marc-relationship"
                    else:
                        predicate_iri, translation_basis = translation
                        object_iri = _lcsh_subject_iri(field)
                        if object_iri is None:
                            reason = "no-single-lcsh-control-number"
                if reason is not None:
                    refusals.append(LcshMeshRefusal(reason=reason, source_field=field))
                    continue
                accepted_source_field_count += 1
                triple = (mesh_iri, predicate_iri, object_iri)
                existing = grouped.get(triple)
                if existing is None:
                    grouped[triple] = (field.source_predicate_iri, translation_basis, [field])
                else:
                    source_predicate_iri, previous_basis, source_fields = existing
                    if source_predicate_iri != field.source_predicate_iri or previous_basis != translation_basis:
                        raise LcshMeshMappingError(
                            f"duplicate mapping triple has inconsistent MARC translation: {triple!r}"
                        )
                    source_fields.append(field)
            root.clear()
    except ElementTree.ParseError as error:
        raise LcshMeshMappingError(f"could not parse LCSH--MeSH MARCXML: {error}") from error

    mappings = tuple(
        LcshMeshMapping(
            subject_iri=subject,
            predicate_iri=predicate,
            object_iri=obj,
            source_predicate_iri=source_predicate,
            translation_basis=translation_basis,
            source_fields=tuple(source_fields),
        )
        for (subject, predicate, obj), (source_predicate, translation_basis, source_fields) in sorted(grouped.items())
    )
    return LcshMeshMappingCapture(
        source_url=source_url,
        retrieved_at=retrieved_at,
        source_sha256=source_sha256 or _digest(payload),
        source_byte_length=source_byte_length if source_byte_length is not None else len(payload),
        member_sha256=_digest(payload),
        member_byte_length=len(payload),
        record_count=record_count,
        linking_record_count=linking_record_count,
        linking_field_count=linking_field_count,
        accepted_source_field_count=accepted_source_field_count,
        mappings=mappings,
        refusals=tuple(refusals),
    )


def parse_lcsh_mesh_mapping_zip(
    payload: bytes,
    *,
    source_url: str = LCSH_MESH_MAPPING_SOURCE_URL,
    retrieved_at: str = LCSH_MESH_MAPPING_RETRIEVED_AT,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
    expected_member_sha256: str | None = None,
    expected_member_byte_length: int | None = None,
) -> LcshMeshMappingCapture:
    """Verify the outer ZIP and its one exact MARCXML member before parsing."""

    if not isinstance(payload, bytes):
        raise TypeError("LCSH--MeSH mapping ZIP must be bytes")
    if expected_sha256 is not None and expected_byte_length is not None:
        _verify_pin(
            payload,
            expected_sha256=expected_sha256,
            expected_byte_length=expected_byte_length,
            label="LCSH--MeSH mapping ZIP",
        )
    elif expected_sha256 is not None or expected_byte_length is not None:
        raise LcshMeshMappingError("ZIP digest and byte length pins must be supplied together")
    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != LCSH_MESH_MAPPING_MEMBER or members[0].is_dir():
                raise LcshMeshMappingError(
                    f"LCSH--MeSH ZIP membership drifted: observed {[item.filename for item in members]!r}"
                )
            xml_payload = archive.read(members[0])
    except (BadZipFile, OSError) as error:
        raise LcshMeshMappingError(f"could not read LCSH--MeSH mapping ZIP: {error}") from error
    if expected_member_sha256 is not None and expected_member_byte_length is not None:
        _verify_pin(
            xml_payload,
            expected_sha256=expected_member_sha256,
            expected_byte_length=expected_member_byte_length,
            label="LCSH--MeSH MARCXML member",
        )
    elif expected_member_sha256 is not None or expected_member_byte_length is not None:
        raise LcshMeshMappingError("member digest and byte length pins must be supplied together")
    return parse_lcsh_mesh_marcxml(
        xml_payload,
        source_url=source_url,
        retrieved_at=retrieved_at,
        source_sha256=_digest(payload),
        source_byte_length=len(payload),
    )


def load_lcsh_mesh_mapping(path: Path) -> LcshMeshMappingCapture:
    """Load the exact pinned Northwestern v1.0.0 mapping ZIP."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise LcshMeshMappingError(f"LCSH--MeSH mapping source is not a regular file: {source}")
    capture = parse_lcsh_mesh_mapping_zip(
        source.read_bytes(),
        expected_sha256=LCSH_MESH_MAPPING_SHA256,
        expected_byte_length=LCSH_MESH_MAPPING_BYTE_LENGTH,
        expected_member_sha256=LCSH_MESH_MAPPING_MEMBER_SHA256,
        expected_member_byte_length=LCSH_MESH_MAPPING_MEMBER_BYTE_LENGTH,
    )
    expected_shape = {
        "acceptedSourceFields": EXPECTED_ACCEPTED_SOURCE_FIELD_COUNT,
        "linkingFields": EXPECTED_LINKING_FIELD_COUNT,
        "linkingRecords": EXPECTED_LINKING_RECORD_COUNT,
        "mappings": EXPECTED_UNIQUE_MAPPING_COUNT,
        "predicateCounts": dict(EXPECTED_PREDICATE_COUNTS),
        "records": EXPECTED_RECORD_COUNT,
        "refusalCounts": dict(EXPECTED_REFUSAL_COUNTS),
        "refusals": EXPECTED_REFUSAL_COUNT,
    }
    observed_shape = {
        "acceptedSourceFields": capture.accepted_source_field_count,
        "linkingFields": capture.linking_field_count,
        "linkingRecords": capture.linking_record_count,
        "mappings": len(capture.mappings),
        "predicateCounts": capture.predicate_counts,
        "records": capture.record_count,
        "refusalCounts": capture.refusal_counts,
        "refusals": len(capture.refusals),
    }
    if observed_shape != expected_shape:
        raise LcshMeshMappingError(
            f"LCSH--MeSH mapping inventory drifted: expected={expected_shape!r}, observed={observed_shape!r}"
        )
    return capture


__all__ = [
    "EXPECTED_ACCEPTED_SOURCE_FIELD_COUNT",
    "EXPECTED_LINKING_FIELD_COUNT",
    "EXPECTED_LINKING_RECORD_COUNT",
    "EXPECTED_PREDICATE_COUNTS",
    "EXPECTED_RECORD_COUNT",
    "EXPECTED_REFUSAL_COUNT",
    "EXPECTED_REFUSAL_COUNTS",
    "EXPECTED_UNIQUE_MAPPING_COUNT",
    "LCSH_MESH_LICENSE_STATEMENT",
    "LCSH_MESH_LICENSE_URL",
    "LCSH_MESH_MAPPING_BYTE_LENGTH",
    "LCSH_MESH_MAPPING_DOI",
    "LCSH_MESH_MAPPING_FILENAME",
    "LCSH_MESH_MAPPING_ISSUED",
    "LCSH_MESH_MAPPING_LANDING_PAGE_URL",
    "LCSH_MESH_MAPPING_MEMBER",
    "LCSH_MESH_MAPPING_MEMBER_BYTE_LENGTH",
    "LCSH_MESH_MAPPING_MEMBER_SHA256",
    "LCSH_MESH_MAPPING_METADATA_URL",
    "LCSH_MESH_MAPPING_RETRIEVED_AT",
    "LCSH_MESH_MAPPING_SHA256",
    "LCSH_MESH_MAPPING_SOURCE_URL",
    "LCSH_MESH_MAPPING_VERSION",
    "LCSH_MESH_WORKING_FILE_RIGHTS_NOTE",
    "LCSH_SUBJECT_PREFIX",
    "MARC_750_FIELD_IRI",
    "MARC_RELATION_CODE_TO_SKOS",
    "MARC_RELATION_TEXT_TO_SKOS",
    "MESH_DESCRIPTOR_PREFIX",
    "PUBLISHER_DECLARED_RECORD_COUNT",
    "LcshMeshMapping",
    "LcshMeshMappingCapture",
    "LcshMeshMappingError",
    "LcshMeshRefusal",
    "MarcMappingField",
    "MarcSubfield",
    "load_lcsh_mesh_mapping",
    "parse_lcsh_mesh_mapping_zip",
    "parse_lcsh_mesh_marcxml",
]
