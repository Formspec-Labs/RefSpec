"""Pinned reader for OCLC's FAST Topical external-link assertions.

The OCLC N-Triples archive is a rolling bulk file.  Its digest therefore
identifies the captured release: a later file at the same URL is source drift,
not an implicit update.  The reader admits OCLC's ``schema:sameAs`` and
``skos:relatedMatch`` and topical ``rdfs:seeAlso`` rows as publisher claims.
The two non-topical license-document ``rdfs:seeAlso`` statements are counted
but not treated as FAST links.  ``owl:sameAs`` remains refused because it
asserts identity rather than a navigational association.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

FAST_EXTERNAL_LINKS_FILENAME = "FASTTopical.nt.zip"
FAST_EXTERNAL_LINKS_SOURCE_URL = "https://researchworks.oclc.org/researchdata/fast/FASTTopical.nt.zip"
FAST_EXTERNAL_LINKS_SHA256 = "sha256:217826c90649895bfca71e81e2ed88919b2e061646ec42a185bc12d0bd3c19db"
FAST_EXTERNAL_LINKS_BYTE_LENGTH = 55_099_212
FAST_EXTERNAL_LINKS_RETRIEVED_AT = "2026-07-27"
FAST_EXTERNAL_LINKS_HAS_VERSIONED_URL = False

FAST_EXTERNAL_LINKS_MEMBER = "FASTTopical.nt"
FAST_EXTERNAL_LINKS_MEMBER_SHA256 = "sha256:8c60dec62f659435debca1de5306472ad77dde2ee9b30d15ed7c228ceedc2e0c"
FAST_EXTERNAL_LINKS_MEMBER_BYTE_LENGTH = 634_399_116
FAST_EXTERNAL_LINKS_LICENSE_MEMBER = "License02_15_2012.txt"
FAST_EXTERNAL_LINKS_LICENSE_MEMBER_SHA256 = "sha256:3b19f8a2f6bab43aaee9b5f895f912079099e7e70a1b2c19e55aafbb01f7abdd"
FAST_EXTERNAL_LINKS_LICENSE_MEMBER_BYTE_LENGTH = 25_293
FAST_EXTERNAL_LINKS_LICENSE_URL = "https://www.oclc.org/research/areas/data-science/fast/odcby.html"
FAST_EXTERNAL_LINKS_LICENSE_TITLE = "Open Data Commons Attribution License (ODC-By) v1.0"
FAST_EXTERNAL_LINKS_LICENSE_ARCHIVE_STATEMENT = (
    "This FAST (Faceted Application of Subject Terminology) data files are made available by OCLC "
    "under the Open Data Commons Attribution License (ODC-By): "
    "http://www.oclc.org/research/activities/fast/odcby.htm."
)

FAST_URI_PREFIX = "http://id.worldcat.org/fast/"
SCHEMA_SAME_AS = "http://schema.org/sameAs"
SKOS_RELATED_MATCH = "http://www.w3.org/2004/02/skos/core#relatedMatch"
RDFS_SEE_ALSO = "http://www.w3.org/2000/01/rdf-schema#seeAlso"
OWL_SAME_AS = "http://www.w3.org/2002/07/owl#sameAs"

EXPECTED_PREDICATE_COUNTS = MappingProxyType(
    {
        RDFS_SEE_ALSO: 155_171,
        SCHEMA_SAME_AS: 311_890,
        SKOS_RELATED_MATCH: 468_479,
    }
)
EXPECTED_REFUSED_PREDICATE_COUNTS = MappingProxyType(
    {
        RDFS_SEE_ALSO: 2,
        OWL_SAME_AS: 2,
    }
)
EXPECTED_TARGET_PREDICATE_COUNTS = MappingProxyType(
    {
        "agrovoc": MappingProxyType({SCHEMA_SAME_AS: 1_057, SKOS_RELATED_MATCH: 7}),
        "bnf-rameau": MappingProxyType({SCHEMA_SAME_AS: 51_430}),
        "gnd": MappingProxyType({SKOS_RELATED_MATCH: 33_570}),
        "fast": MappingProxyType({RDFS_SEE_ALSO: 78_981}),
        "lcsh": MappingProxyType({SCHEMA_SAME_AS: 259_397, SKOS_RELATED_MATCH: 356_351}),
        "loc-other": MappingProxyType({SCHEMA_SAME_AS: 4, SKOS_RELATED_MATCH: 5}),
        "nalt": MappingProxyType({SKOS_RELATED_MATCH: 2_650}),
        "viaf": MappingProxyType({SCHEMA_SAME_AS: 2}),
        "wikidata": MappingProxyType({SKOS_RELATED_MATCH: 75_375}),
        "wikipedia": MappingProxyType({RDFS_SEE_ALSO: 76_190, SKOS_RELATED_MATCH: 521}),
    }
)
EXPECTED_ASSERTION_COUNT = sum(EXPECTED_PREDICATE_COUNTS.values())

_MAPPING_TRIPLE = re.compile(rb"^<([^>]+)>\s+<([^>]+)>\s+<([^>]+)>\s+\.\s*$")
_ANY_URI_TRIPLE = re.compile(
    rb'^<([^>]+)>\s+<([^>]+)>\s+"([^"\\]+)"\^\^'
    rb"<http://www.w3.org/2001/XMLSchema#anyURI>\s+\.\s*$"
)
_MAPPING_PREDICATES = frozenset(EXPECTED_PREDICATE_COUNTS)
_COUNTED_PREDICATES = frozenset((*EXPECTED_PREDICATE_COUNTS, *EXPECTED_REFUSED_PREDICATE_COUNTS))


class OclcFastExternalLinksError(ValueError):
    """The captured OCLC archive cannot be represented without guessing."""


@dataclass(frozen=True, slots=True)
class OclcFastExternalLink:
    """One publisher-authored positive mapping statement."""

    subject_iri: str
    predicate_iri: str
    object_iri: str
    target_vocabulary: str
    line_number: int
    native_statement: str
    source_record_digest: str


@dataclass(frozen=True, slots=True)
class OclcFastExternalLinksCapture:
    """Measured shape plus any caller-selected mapping rows from the archive."""

    source_url: str
    source_sha256: str
    source_byte_length: int
    retrieved_at: str
    assertion_count: int
    predicate_counts: dict[str, int]
    refused_predicate_counts: dict[str, int]
    target_predicate_counts: dict[str, dict[str, int]]
    distinct_subject_count: int
    retained_links: tuple[OclcFastExternalLink, ...]
    retained_duplicate_assertion_count: int


@dataclass(frozen=True, slots=True)
class OclcFastEndpointRecord:
    """Publisher content for one FAST endpoint needed by a see-also assertion."""

    iri: str
    label: str
    publisher_language_tag: str | None
    language: str
    language_determined_by: str
    label_line_number: int
    label_native_statement: str
    label_statement_digest: str
    deprecated: bool


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_length = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            byte_length += len(chunk)
    return "sha256:" + digest.hexdigest(), byte_length


def _target_vocabulary(object_iri: str) -> str:
    if object_iri.startswith("http://id.loc.gov/authorities/subjects/"):
        return "lcsh"
    if object_iri.startswith(FAST_URI_PREFIX):
        return "fast"
    if object_iri.startswith("http://data.bnf.fr/ark:/"):
        return "bnf-rameau"
    if object_iri.startswith("https://www.wikidata.org/entity/"):
        return "wikidata"
    if object_iri.startswith("http://d-nb.info/gnd/"):
        return "gnd"
    if object_iri.startswith("http://lod.nal.usda.gov/nalt/"):
        return "nalt"
    if object_iri.startswith("http://aims.fao.org/aos/agrovoc/"):
        return "agrovoc"
    if object_iri.startswith("http://en.wikipedia.org/wiki/"):
        return "wikipedia"
    if object_iri.startswith("https://viaf.org/viaf/"):
        return "viaf"
    if object_iri.startswith("http://id.loc.gov/authorities/"):
        return "loc-other"
    raise OclcFastExternalLinksError(f"FAST external-link target vocabulary is unclassified: {object_iri}")


def parse_oclc_fast_external_link_statement(
    raw_line: bytes,
    *,
    line_number: int,
) -> OclcFastExternalLink | None:
    """Parse one admitted positive mapping; return ``None`` for every other row."""

    predicate_iri = next(
        (predicate for predicate in _COUNTED_PREDICATES if f" <{predicate}> ".encode() in raw_line),
        None,
    )
    if predicate_iri not in _MAPPING_PREDICATES:
        return None
    statement = raw_line.rstrip(b"\r\n")
    match = _MAPPING_TRIPLE.fullmatch(statement)
    if match is None and predicate_iri == RDFS_SEE_ALSO:
        match = _ANY_URI_TRIPLE.fullmatch(statement)
    if match is None:
        raise OclcFastExternalLinksError(f"FAST positive mapping line {line_number} is not an IRI N-Triples statement")
    subject_iri, parsed_predicate, object_iri = (part.decode("utf-8") for part in match.groups())
    if parsed_predicate != predicate_iri:
        raise OclcFastExternalLinksError(f"FAST mapping line {line_number} predicate parsing differs")
    if not subject_iri.startswith(FAST_URI_PREFIX):
        raise OclcFastExternalLinksError(f"FAST mapping line {line_number} subject is outside the Topical authority")
    return OclcFastExternalLink(
        subject_iri=subject_iri,
        predicate_iri=predicate_iri,
        object_iri=object_iri,
        target_vocabulary=_target_vocabulary(object_iri),
        line_number=line_number,
        native_statement=raw_line.decode("utf-8").rstrip("\r\n"),
        source_record_digest=_sha256(raw_line),
    )


def _verify_license(payload: bytes) -> None:
    if len(payload) != FAST_EXTERNAL_LINKS_LICENSE_MEMBER_BYTE_LENGTH:
        raise OclcFastExternalLinksError("FAST license member byte length drifted")
    if _sha256(payload) != FAST_EXTERNAL_LINKS_LICENSE_MEMBER_SHA256:
        raise OclcFastExternalLinksError("FAST license member digest drifted")
    normalized = " ".join(payload.decode("windows-1252").split())
    if FAST_EXTERNAL_LINKS_LICENSE_TITLE not in normalized:
        raise OclcFastExternalLinksError("FAST archive no longer carries the pinned ODC-By 1.0 title")
    if FAST_EXTERNAL_LINKS_LICENSE_ARCHIVE_STATEMENT not in normalized:
        raise OclcFastExternalLinksError("FAST archive no longer carries the pinned OCLC license statement")


def parse_oclc_fast_external_links_file(
    path: Path,
    *,
    retained_subject_iris: Collection[str] | None = None,
    retained_target_iris: Collection[str] | None = None,
    retained_predicate_iris: Collection[str] | None = None,
) -> OclcFastExternalLinksCapture:
    """Verify and scan the rolling archive, retaining only requested rows.

    Passing neither selector retains all 935,540 admitted link assertions.
    Selectors affect memory use only; all publisher rows are still counted and
    checked against the pinned source shape.
    """

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise OclcFastExternalLinksError(f"FAST external-links source is not a regular file: {source}")
    observed_digest, observed_length = _digest_file(source)
    if observed_length != FAST_EXTERNAL_LINKS_BYTE_LENGTH or observed_digest != FAST_EXTERNAL_LINKS_SHA256:
        raise OclcFastExternalLinksError(
            "FAST external-links input pin differs: "
            f"expected=({FAST_EXTERNAL_LINKS_BYTE_LENGTH}, {FAST_EXTERNAL_LINKS_SHA256}), "
            f"observed=({observed_length}, {observed_digest})"
        )

    subject_filter = None if retained_subject_iris is None else frozenset(retained_subject_iris)
    target_filter = None if retained_target_iris is None else frozenset(retained_target_iris)
    predicate_filter = None if retained_predicate_iris is None else frozenset(retained_predicate_iris)
    predicate_counts: Counter[str] = Counter()
    refused_counts: Counter[str] = Counter()
    target_counts: Counter[tuple[str, str]] = Counter()
    subjects: set[str] = set()
    retained: list[OclcFastExternalLink] = []
    retained_claims: set[tuple[str, str, str]] = set()
    retained_duplicate_count = 0
    member_digest = hashlib.sha256()
    member_length = 0

    try:
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            if names != [FAST_EXTERNAL_LINKS_MEMBER, FAST_EXTERNAL_LINKS_LICENSE_MEMBER]:
                raise OclcFastExternalLinksError(f"FAST archive members differ: {names!r}")
            _verify_license(archive.read(FAST_EXTERNAL_LINKS_LICENSE_MEMBER))
            with archive.open(FAST_EXTERNAL_LINKS_MEMBER) as handle:
                for line_number, raw_line in enumerate(handle, start=1):
                    member_digest.update(raw_line)
                    member_length += len(raw_line)
                    predicate_iri = next(
                        (predicate for predicate in _COUNTED_PREDICATES if f" <{predicate}> ".encode() in raw_line),
                        None,
                    )
                    if predicate_iri is None:
                        continue
                    if predicate_iri not in _MAPPING_PREDICATES or (
                        predicate_iri == RDFS_SEE_ALSO
                        and not raw_line.startswith(("<" + FAST_URI_PREFIX).encode("ascii"))
                    ):
                        refused_counts[predicate_iri] += 1
                        continue
                    link = parse_oclc_fast_external_link_statement(
                        raw_line,
                        line_number=line_number,
                    )
                    if link is None:  # pragma: no cover - predicate already admitted above
                        raise AssertionError("admitted FAST mapping statement was not parsed")
                    predicate_counts[predicate_iri] += 1
                    target_counts[(link.target_vocabulary, predicate_iri)] += 1
                    subjects.add(link.subject_iri)
                    if (subject_filter is not None and link.subject_iri not in subject_filter) or (
                        target_filter is not None and link.object_iri not in target_filter
                    ) or (predicate_filter is not None and link.predicate_iri not in predicate_filter):
                        continue
                    claim = (link.subject_iri, predicate_iri, link.object_iri)
                    if claim in retained_claims:
                        retained_duplicate_count += 1
                        continue
                    retained_claims.add(claim)
                    retained.append(link)
    except (OSError, UnicodeError, zipfile.BadZipFile) as error:
        raise OclcFastExternalLinksError(f"could not read FAST external-links archive: {error}") from error

    observed_member_digest = "sha256:" + member_digest.hexdigest()
    if member_length != FAST_EXTERNAL_LINKS_MEMBER_BYTE_LENGTH or observed_member_digest != (
        FAST_EXTERNAL_LINKS_MEMBER_SHA256
    ):
        raise OclcFastExternalLinksError(
            "FAST N-Triples member pin differs: "
            f"expected=({FAST_EXTERNAL_LINKS_MEMBER_BYTE_LENGTH}, {FAST_EXTERNAL_LINKS_MEMBER_SHA256}), "
            f"observed=({member_length}, {observed_member_digest})"
        )
    observed_predicates = dict(sorted(predicate_counts.items()))
    if observed_predicates != dict(EXPECTED_PREDICATE_COUNTS):
        raise OclcFastExternalLinksError(
            "FAST positive predicate counts differ: "
            f"expected={dict(EXPECTED_PREDICATE_COUNTS)!r}, observed={observed_predicates!r}"
        )
    observed_refused = dict(sorted(refused_counts.items()))
    if observed_refused != dict(EXPECTED_REFUSED_PREDICATE_COUNTS):
        raise OclcFastExternalLinksError(
            "FAST refused predicate counts differ: "
            f"expected={dict(EXPECTED_REFUSED_PREDICATE_COUNTS)!r}, observed={observed_refused!r}"
        )
    observed_targets: dict[str, dict[str, int]] = {}
    for target, predicate in sorted(target_counts):
        observed_targets.setdefault(target, {})[predicate] = target_counts[(target, predicate)]
    expected_targets = {target: dict(counts) for target, counts in EXPECTED_TARGET_PREDICATE_COUNTS.items()}
    if observed_targets != expected_targets:
        raise OclcFastExternalLinksError(
            f"FAST target vocabulary counts differ: expected={expected_targets!r}, observed={observed_targets!r}"
        )
    return OclcFastExternalLinksCapture(
        source_url=FAST_EXTERNAL_LINKS_SOURCE_URL,
        source_sha256=observed_digest,
        source_byte_length=observed_length,
        retrieved_at=FAST_EXTERNAL_LINKS_RETRIEVED_AT,
        assertion_count=sum(predicate_counts.values()),
        predicate_counts=observed_predicates,
        refused_predicate_counts=observed_refused,
        target_predicate_counts=observed_targets,
        distinct_subject_count=len(subjects),
        retained_links=tuple(retained),
        retained_duplicate_assertion_count=retained_duplicate_count,
    )


_FAST_PREF_LABEL = re.compile(
    rb'^<([^>]+)>\s+<http://www.w3.org/2004/02/skos/core#prefLabel>\s+'
    rb'"((?:[^"\\]|\\.)*)"(?:@([A-Za-z]+(?:-[A-Za-z0-9]+)*)|\^\^<([^>]*)>)?\s+\.\s*$'
)
_FAST_DEPRECATED = re.compile(
    rb'^<([^>]+)>\s+<http://www.w3.org/2002/07/owl#deprecated>\s+'
    rb'"true"\^\^<http://www.w3.org/2001/XMLSchema#boolean>\s+\.\s*$'
)
_NT_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t"}


def _unescape_literal(value: bytes, *, line_number: int) -> str:
    try:
        escaped = value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise OclcFastExternalLinksError(
            f"FAST label line {line_number} is not UTF-8"
        ) from error
    output: list[str] = []
    index = 0
    while index < len(escaped):
        if escaped[index] != "\\":
            output.append(escaped[index])
            index += 1
            continue
        marker = escaped[index + 1]
        if marker in _NT_ESCAPES:
            output.append(_NT_ESCAPES[marker])
            index += 2
            continue
        if marker in {"u", "U"}:
            width = 4 if marker == "u" else 8
            digits = escaped[index + 2 : index + 2 + width]
            if len(digits) != width:
                raise OclcFastExternalLinksError(f"FAST label line {line_number} has a short Unicode escape")
            output.append(chr(int(digits, 16)))
            index += 2 + width
            continue
        raise OclcFastExternalLinksError(f"FAST label line {line_number} has unsupported escape \\{marker}")
    return "".join(output)


def capture_oclc_fast_endpoint_records(
    path: Path,
    *,
    endpoint_iris: Collection[str],
) -> tuple[Mapping[str, OclcFastEndpointRecord], frozenset[str]]:
    """Load real labels for requested FAST endpoints; return missing IRIs separately."""

    source = Path(path)
    observed_digest, observed_length = _digest_file(source)
    if observed_length != FAST_EXTERNAL_LINKS_BYTE_LENGTH or observed_digest != FAST_EXTERNAL_LINKS_SHA256:
        raise OclcFastExternalLinksError("FAST external-links input pin differs while loading endpoint content")
    requested = frozenset(endpoint_iris)
    labels: dict[str, tuple[str, str | None, str | None, int, str, str]] = {}
    deprecated: set[str] = set()
    with zipfile.ZipFile(source) as archive, archive.open(FAST_EXTERNAL_LINKS_MEMBER) as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.startswith(b"<"):
                continue
            subject_end = raw_line.find(b">")
            if subject_end < 2:
                continue
            try:
                subject_iri = raw_line[1:subject_end].decode("ascii")
            except UnicodeDecodeError as error:
                raise OclcFastExternalLinksError(f"FAST endpoint line {line_number} has a non-ASCII IRI") from error
            if subject_iri not in requested:
                continue
            statement = raw_line.rstrip(b"\r\n")
            deprecated_match = _FAST_DEPRECATED.fullmatch(statement)
            if deprecated_match is not None:
                deprecated.add(subject_iri)
                continue
            label_match = _FAST_PREF_LABEL.fullmatch(statement)
            if label_match is None:
                continue
            if subject_iri in labels:
                raise OclcFastExternalLinksError(f"FAST endpoint repeats prefLabel: {subject_iri}")
            _subject, value_raw, language_raw, datatype_raw = label_match.groups()
            language = None if language_raw is None else language_raw.decode("ascii").lower()
            datatype = None if datatype_raw is None else datatype_raw.decode("ascii")
            if datatype is not None:
                raise OclcFastExternalLinksError(f"FAST endpoint prefLabel is typed: {subject_iri}")
            native_statement = statement.decode("utf-8")
            label_value = _unescape_literal(value_raw, line_number=line_number).strip()
            if not label_value:
                raise OclcFastExternalLinksError(f"FAST endpoint prefLabel is empty: {subject_iri}")
            labels[subject_iri] = (
                label_value,
                language,
                datatype,
                line_number,
                native_statement,
                _sha256(statement),
            )
    records = {
        iri: OclcFastEndpointRecord(
            iri=iri,
            label=value[0],
            publisher_language_tag=value[1],
            language="en" if value[1] is None else value[1],
            language_determined_by=(
                "authorityConvention:fast-topical-labels-are-English"
                if value[1] is None
                else "publisherLanguageTag"
            ),
            label_line_number=value[3],
            label_native_statement=value[4],
            label_statement_digest=value[5],
            deprecated=iri in deprecated,
        )
        for iri, value in sorted(labels.items())
    }
    return MappingProxyType(records), frozenset(requested - records.keys())


__all__ = [
    "EXPECTED_ASSERTION_COUNT",
    "EXPECTED_PREDICATE_COUNTS",
    "EXPECTED_REFUSED_PREDICATE_COUNTS",
    "EXPECTED_TARGET_PREDICATE_COUNTS",
    "FAST_EXTERNAL_LINKS_BYTE_LENGTH",
    "FAST_EXTERNAL_LINKS_FILENAME",
    "FAST_EXTERNAL_LINKS_HAS_VERSIONED_URL",
    "FAST_EXTERNAL_LINKS_LICENSE_ARCHIVE_STATEMENT",
    "FAST_EXTERNAL_LINKS_LICENSE_TITLE",
    "FAST_EXTERNAL_LINKS_LICENSE_URL",
    "FAST_EXTERNAL_LINKS_RETRIEVED_AT",
    "FAST_EXTERNAL_LINKS_SHA256",
    "FAST_EXTERNAL_LINKS_SOURCE_URL",
    "OWL_SAME_AS",
    "RDFS_SEE_ALSO",
    "SCHEMA_SAME_AS",
    "SKOS_RELATED_MATCH",
    "OclcFastEndpointRecord",
    "OclcFastExternalLink",
    "OclcFastExternalLinksCapture",
    "OclcFastExternalLinksError",
    "capture_oclc_fast_endpoint_records",
    "parse_oclc_fast_external_link_statement",
    "parse_oclc_fast_external_links_file",
]
