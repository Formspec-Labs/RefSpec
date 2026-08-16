"""Pinned publisher content for GEMET's UMTHES mapping targets.

The SNS site exposes one RDF/N-Triples representation per UMTHES concept but
does not expose a bulk dump.  The acquisition archive therefore stores the
exact response bytes for every distinct GEMET target plus a canonical manifest
that pins each request URL, response digest, byte length, and retrieval time.
The archive also stores the publisher's license page verbatim.  Importing this
module never opens a network connection.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from rdflib import RDF, Graph, Literal, URIRef
from rdflib.namespace import OWL, SKOS

UMTHES_CAPTURE_FILENAME = "umthes-gemet-endpoints-2026-08-15.zip"
UMTHES_CAPTURE_SOURCE_ROOT = "https://sns.uba.de/umthes/"
UMTHES_RECORD_URL_TEMPLATE = "https://sns.uba.de/umthes/de/concepts/{concept_id}.nt"
UMTHES_LICENSE_SOURCE_URL = "https://sns.uba.de/de/api"
UMTHES_LICENSE_URL = "https://creativecommons.org/licenses/by-nc/4.0/deed.de"
UMTHES_RETRIEVED_AT = "2026-08-16T00:21:03Z"

# Filled from the deterministic acquisition archive.  The individual publisher
# response pins remain inside its manifest and are verified again by the reader.
UMTHES_CAPTURE_SHA256 = "sha256:978b10cd1e3f2f8729372a86f2afa1b62d2790e4810c6d57af5343835259d25f"
UMTHES_CAPTURE_BYTE_LENGTH = 11_935_413
UMTHES_EXPECTED_REQUESTED_RECORD_COUNT = 3_378
UMTHES_EXPECTED_RECORD_COUNT = 3_365
UMTHES_UNAVAILABLE_CONCEPT_IDS = frozenset(
    {
        "_00004353",
        "_00024866",
        "_00047428",
        "_00050113",
        "_00051593",
        "_00651218",
        "_00651220",
        "_00651221",
        "_00651222",
        "_00651223",
        "_00651224",
        "_00651225",
        "_00651226",
    }
)

UMTHES_LEGACY_PREFIX = "http://data.uba.de/umt/"
UMTHES_CURRENT_PREFIX = "https://sns.uba.de/umthes/"
UMTHES_SCHEME_IRI = UMTHES_CURRENT_PREFIX + "scheme"
UMTHES_LICENSE_STATEMENT = (
    "Die auf https://sns.uba.de veröffentlichten Inhalte stehen unter der Lizenz "
    "CC BY-NC 4.0 (Namensnennung – Nicht-kommerziell) und dürfen unter Angabe "
    "der Quelle frei verwendet, geteilt und angepasst werden. Eine kommerzielle "
    "Nutzung ist nicht gestattet."
)
UMTHES_ATTRIBUTION_STATEMENT = (
    "Bitte nennen Sie bei der Nutzung stets die Quelle „Semantischer Netzwerkdienst "
    "(SNS), Umweltbundesamt“ und verlinken Sie nach Möglichkeit auf die entsprechende Seite."
)

_MANIFEST_MEMBER = "manifest.json"
_LICENSE_MEMBER = "license.html"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONCEPT_ID = re.compile(r"^_[0-9a-f]{8}$")
_HTML_TAG = re.compile(r"<[^>]+>")


class UmthesContentError(ValueError):
    """The captured UMTHES content differs from its exact source record."""


@dataclass(frozen=True, slots=True)
class UmthesLabel:
    value: str
    language: str
    role: str
    predicate_iri: str


@dataclass(frozen=True, slots=True)
class UmthesDefinition:
    value: str
    language: str
    predicate_iri: str


@dataclass(frozen=True, slots=True)
class UmthesRelation:
    predicate_iri: str
    object_iri: str


@dataclass(frozen=True, slots=True)
class UmthesRecord:
    legacy_iri: str
    concept_iri: str
    source_url: str
    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    labels: Sequence[UmthesLabel]
    definitions: Sequence[UmthesDefinition]
    relations: Sequence[UmthesRelation]
    deprecated: bool


@dataclass(frozen=True, slots=True)
class UmthesContentCapture:
    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    license_source_sha256: str
    license_source_byte_length: int
    records: Sequence[UmthesRecord]
    unavailable_records: Sequence[Mapping[str, object]]

    @property
    def label_counts_by_language(self) -> dict[str, int]:
        return dict(sorted(Counter(label.language for record in self.records for label in record.labels).items()))

    @property
    def definition_counts_by_language(self) -> dict[str, int]:
        return dict(
            sorted(Counter(value.language for record in self.records for value in record.definitions).items())
        )


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def current_iri_for_legacy(legacy_iri: str) -> str:
    if not legacy_iri.startswith(UMTHES_LEGACY_PREFIX):
        raise UmthesContentError(f"UMTHES legacy IRI has an unexpected namespace: {legacy_iri}")
    concept_id = legacy_iri.removeprefix(UMTHES_LEGACY_PREFIX)
    if _CONCEPT_ID.fullmatch(concept_id) is None:
        raise UmthesContentError(f"UMTHES legacy IRI has an invalid concept id: {legacy_iri}")
    return UMTHES_CURRENT_PREFIX + concept_id


def _literal_values(graph: Graph, subject: URIRef, predicate: URIRef, *, role: str) -> tuple[UmthesLabel, ...]:
    values: list[UmthesLabel] = []
    for value in graph.objects(subject, predicate):
        if not isinstance(value, Literal) or not str(value).strip() or value.language is None:
            raise UmthesContentError(f"UMTHES {predicate} on {subject} is not a language-tagged non-empty literal")
        values.append(
            UmthesLabel(
                value=str(value).strip(),
                language=value.language.lower(),
                role=role,
                predicate_iri=str(predicate),
            )
        )
    return tuple(sorted(values, key=lambda item: (item.language, item.value)))


def parse_umthes_record_nt(
    payload: bytes,
    *,
    legacy_iri: str,
    source_url: str,
    retrieved_at: str,
) -> UmthesRecord:
    """Parse the selected concept only; neighboring context remains source evidence."""

    concept_iri = current_iri_for_legacy(legacy_iri)
    try:
        graph = Graph().parse(data=payload, format="nt")
    except Exception as error:  # rdflib exposes parser-specific exception classes
        raise UmthesContentError(f"UMTHES response for {concept_iri} is not N-Triples: {error}") from error
    subject = URIRef(concept_iri)
    if (subject, RDF.type, SKOS.Concept) not in graph:
        raise UmthesContentError(f"UMTHES response does not describe the requested concept: {concept_iri}")
    if (subject, SKOS.inScheme, URIRef(UMTHES_SCHEME_IRI)) not in graph:
        raise UmthesContentError(f"UMTHES concept has an unexpected scheme: {concept_iri}")
    labels = (
        *_literal_values(graph, subject, SKOS.prefLabel, role="preferred"),
        *_literal_values(graph, subject, SKOS.altLabel, role="alternate"),
        *_literal_values(graph, subject, SKOS.hiddenLabel, role="hidden"),
    )
    if not labels or not any(label.role == "preferred" for label in labels):
        raise UmthesContentError(f"UMTHES concept has no publisher preferred label: {concept_iri}")
    definitions: list[UmthesDefinition] = []
    for predicate in (SKOS.definition, SKOS.scopeNote, SKOS.note):
        for value in graph.objects(subject, predicate):
            if not isinstance(value, Literal) or not str(value).strip() or value.language is None:
                raise UmthesContentError(f"UMTHES definition on {concept_iri} is not language tagged")
            definitions.append(
                UmthesDefinition(
                    value=str(value).strip(),
                    language=value.language.lower(),
                    predicate_iri=str(predicate),
                )
            )
    relations = tuple(
        sorted(
            (
                UmthesRelation(predicate_iri=str(predicate), object_iri=str(value))
                for predicate in (SKOS.broader, SKOS.narrower, SKOS.related)
                for value in graph.objects(subject, predicate)
                if isinstance(value, URIRef) and str(value).startswith(UMTHES_CURRENT_PREFIX)
            ),
            key=lambda item: (item.predicate_iri, item.object_iri),
        )
    )
    deprecated_values = tuple(graph.objects(subject, OWL.deprecated))
    if any(not isinstance(value, Literal) for value in deprecated_values):
        raise UmthesContentError(f"UMTHES deprecated marker is malformed: {concept_iri}")
    return UmthesRecord(
        legacy_iri=legacy_iri,
        concept_iri=concept_iri,
        source_url=source_url,
        source_sha256=_sha256(payload),
        source_byte_length=len(payload),
        retrieved_at=retrieved_at,
        labels=labels,
        definitions=tuple(sorted(definitions, key=lambda item: (item.language, item.predicate_iri, item.value))),
        relations=relations,
        deprecated=any(str(value).lower() == "true" for value in deprecated_values),
    )


def _verify_license(payload: bytes) -> None:
    text = html.unescape(_HTML_TAG.sub("", payload.decode("utf-8")))
    normalized = " ".join(text.split())
    for statement in (UMTHES_LICENSE_STATEMENT, UMTHES_ATTRIBUTION_STATEMENT):
        if statement not in normalized:
            raise UmthesContentError("UMTHES license page no longer contains the pinned publisher wording")


def _require_manifest_record(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise UmthesContentError("UMTHES capture manifest contains a non-object record")
    return value


def load_umthes_content_capture(path: Path) -> UmthesContentCapture:
    """Verify the deterministic archive and every embedded publisher response."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise UmthesContentError(f"UMTHES capture is not a regular file: {source}")
    payload = source.read_bytes()
    if len(payload) != UMTHES_CAPTURE_BYTE_LENGTH or _sha256(payload) != UMTHES_CAPTURE_SHA256:
        raise UmthesContentError("UMTHES capture archive pin differs")
    try:
        with zipfile.ZipFile(source) as archive:
            manifest_payload = archive.read(_MANIFEST_MEMBER)
            manifest = json.loads(manifest_payload)
            if not isinstance(manifest, Mapping) or manifest_payload != _canonical_json_bytes(manifest):
                raise UmthesContentError("UMTHES capture manifest is not canonical JSON")
            if manifest.get("format") != "refspec-umthes-http-capture/1":
                raise UmthesContentError("UMTHES capture manifest format differs")
            retrieved_at = manifest.get("retrievedAt")
            records_value = manifest.get("records")
            license_value = manifest.get("license")
            if not isinstance(retrieved_at, str) or not isinstance(records_value, list):
                raise UmthesContentError("UMTHES capture manifest fields are malformed")
            if (
                retrieved_at != UMTHES_RETRIEVED_AT
                or manifest.get("sourceUrlRoot") != UMTHES_CAPTURE_SOURCE_ROOT
                or manifest.get("sourceUrlTemplate") != UMTHES_RECORD_URL_TEMPLATE
            ):
                raise UmthesContentError("UMTHES capture source identity differs")
            if not isinstance(license_value, Mapping):
                raise UmthesContentError("UMTHES capture license descriptor is malformed")
            if len(records_value) != UMTHES_EXPECTED_RECORD_COUNT:
                raise UmthesContentError("UMTHES capture record count differs")
            unavailable_value = manifest.get("unavailableRecords")
            if not isinstance(unavailable_value, list):
                raise UmthesContentError("UMTHES unavailable-record accounting is malformed")
            unavailable_records = tuple(_require_manifest_record(item) for item in unavailable_value)
            unavailable_ids = {
                str(item.get("legacyIri", "")).removeprefix(UMTHES_LEGACY_PREFIX)
                for item in unavailable_records
            }
            unavailable_urls = {
                UMTHES_RECORD_URL_TEMPLATE.format(concept_id=concept_id)
                for concept_id in unavailable_ids
            }
            if (
                manifest.get("requestedRecordCount") != UMTHES_EXPECTED_REQUESTED_RECORD_COUNT
                or manifest.get("recordCount") != UMTHES_EXPECTED_RECORD_COUNT
                or unavailable_ids != UMTHES_UNAVAILABLE_CONCEPT_IDS
                or any(item.get("httpStatus") != 404 for item in unavailable_records)
                or {item.get("url") for item in unavailable_records} != unavailable_urls
            ):
                raise UmthesContentError("UMTHES unavailable-record set differs")
            expected_members = {_MANIFEST_MEMBER, _LICENSE_MEMBER}
            license_payload = archive.read(_LICENSE_MEMBER)
            if (
                license_value.get("member") != _LICENSE_MEMBER
                or license_value.get("url") != UMTHES_LICENSE_SOURCE_URL
                or license_value.get("byteLength") != len(license_payload)
                or license_value.get("sha256") != _sha256(license_payload)
            ):
                raise UmthesContentError("UMTHES license response pin differs")
            _verify_license(license_payload)
            records: list[UmthesRecord] = []
            seen_legacy: set[str] = set()
            for raw_record in records_value:
                descriptor = _require_manifest_record(raw_record)
                legacy_iri = descriptor.get("legacyIri")
                member = descriptor.get("member")
                url = descriptor.get("url")
                if not isinstance(legacy_iri, str) or not isinstance(member, str) or not isinstance(url, str):
                    raise UmthesContentError("UMTHES record descriptor fields are malformed")
                if legacy_iri in seen_legacy:
                    raise UmthesContentError(f"UMTHES capture repeats {legacy_iri}")
                seen_legacy.add(legacy_iri)
                concept_id = legacy_iri.removeprefix(UMTHES_LEGACY_PREFIX)
                expected_member = f"records/{concept_id}.nt"
                expected_url = UMTHES_RECORD_URL_TEMPLATE.format(concept_id=concept_id)
                if member != expected_member or url != expected_url:
                    raise UmthesContentError(f"UMTHES record location differs for {legacy_iri}")
                expected_members.add(member)
                record_payload = archive.read(member)
                if (
                    descriptor.get("byteLength") != len(record_payload)
                    or descriptor.get("sha256") != _sha256(record_payload)
                    or _DIGEST.fullmatch(str(descriptor.get("sha256"))) is None
                ):
                    raise UmthesContentError(f"UMTHES response pin differs for {legacy_iri}")
                records.append(
                    parse_umthes_record_nt(
                        record_payload,
                        legacy_iri=legacy_iri,
                        source_url=url,
                        retrieved_at=retrieved_at,
                    )
                )
            if set(archive.namelist()) != expected_members:
                raise UmthesContentError("UMTHES capture archive member set differs")
    except (KeyError, OSError, UnicodeError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise UmthesContentError(f"could not read UMTHES capture archive: {error}") from error
    return UmthesContentCapture(
        source_sha256=UMTHES_CAPTURE_SHA256,
        source_byte_length=UMTHES_CAPTURE_BYTE_LENGTH,
        retrieved_at=retrieved_at,
        license_source_sha256=_sha256(license_payload),
        license_source_byte_length=len(license_payload),
        records=tuple(sorted(records, key=lambda item: item.legacy_iri)),
        unavailable_records=unavailable_records,
    )


__all__ = [
    "UMTHES_ATTRIBUTION_STATEMENT",
    "UMTHES_CAPTURE_BYTE_LENGTH",
    "UMTHES_CAPTURE_FILENAME",
    "UMTHES_CAPTURE_SHA256",
    "UMTHES_CAPTURE_SOURCE_ROOT",
    "UMTHES_CURRENT_PREFIX",
    "UMTHES_EXPECTED_RECORD_COUNT",
    "UMTHES_EXPECTED_REQUESTED_RECORD_COUNT",
    "UMTHES_LEGACY_PREFIX",
    "UMTHES_LICENSE_SOURCE_URL",
    "UMTHES_LICENSE_STATEMENT",
    "UMTHES_LICENSE_URL",
    "UMTHES_RECORD_URL_TEMPLATE",
    "UMTHES_RETRIEVED_AT",
    "UMTHES_SCHEME_IRI",
    "UMTHES_UNAVAILABLE_CONCEPT_IDS",
    "UmthesContentCapture",
    "UmthesContentError",
    "UmthesDefinition",
    "UmthesLabel",
    "UmthesRecord",
    "UmthesRelation",
    "current_iri_for_legacy",
    "load_umthes_content_capture",
    "parse_umthes_record_nt",
]
