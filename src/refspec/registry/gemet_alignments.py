"""Pinned reader for every mapping assertion in GEMET 4.2.3.

GEMET publishes its mappings inside the complete SKOS RDF/XML export.  This
reader verifies the exact versioned gzip bytes, verifies the decompressed
payload independently, and retains only the five SKOS mapping predicates.
It preserves the publisher's direction and predicate; it never emits an
inverse or computes closure.
"""

from __future__ import annotations

import gzip
import hashlib
import re
import urllib.parse
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from xml.etree import ElementTree

from rdflib.namespace import SKOS

GEMET_ALIGNMENT_FILENAME = "gemet-4.2.3.rdf.gz"
GEMET_ALIGNMENT_SOURCE_URL = "https://www.eionet.europa.eu/gemet/4.2.3/gemet.rdf.gz"
GEMET_ALIGNMENT_LANDING_PAGE_URL = "https://www.eionet.europa.eu/gemet/en-US/exports/rdf/4.2.3"
GEMET_ALIGNMENT_RETRIEVED_AT = "2026-08-15T22:50:20Z"
GEMET_ALIGNMENT_SHA256 = "sha256:96002bb7cd1f89bccb05ee174fb834a04dd7342bdd1428f32105cd47fd6b73b6"
GEMET_ALIGNMENT_BYTE_LENGTH = 7_423_725
GEMET_ALIGNMENT_RDF_SHA256 = "sha256:1b784b1a6387b8ec6c0d75ea5f0543970933172fcb0428a52de2c8ca536d20f1"
GEMET_ALIGNMENT_RDF_BYTE_LENGTH = 33_332_557
GEMET_ALIGNMENT_VERSION = "4.2.3"
GEMET_ALIGNMENT_ISSUED = "2021-12-06"

# Verbatim visible wording on the versioned publisher landing page.
GEMET_LICENSE_STATEMENT = "Attribution 4.0 International (CC BY 4.0)"
GEMET_LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
GEMET_PUBLISHER_LICENSE_IRI = "http://creativecommons.org/licenses/by/4.0/"

# The mapping export supplies only legacy UMTHES URIs.  RefSpec captures the
# corresponding publisher records separately and records, rather than gates on,
# the UMTHES content license.
UMTHES_CONTENT_RIGHTS_NOTE = (
    "UMTHES publisher content is imported from exact SNS responses under the recorded CC BY-NC 4.0 terms."
)

GEMET_CONCEPT_PREFIX = "http://www.eionet.europa.eu/gemet/concept/"
GEMET_SCHEME_IRI = "http://www.eionet.europa.eu/gemet/gemetThesaurus"

SKOS_MAPPING_PREDICATES = frozenset(
    {
        str(SKOS.exactMatch),
        str(SKOS.closeMatch),
        str(SKOS.broadMatch),
        str(SKOS.narrowMatch),
        str(SKOS.relatedMatch),
    }
)

TARGET_PREFIXES = MappingProxyType(
    {
        "agrovoc": "http://aims.fao.org/aos/agrovoc/",
        "dbpedia": "http://dbpedia.org/",
        "eionet-determinations": "http://rdfdata.eionet.europa.eu/",
        "eurovoc": "http://eurovoc.europa.eu/",
        "umthes": "http://data.uba.de/umt/",
    }
)
HELD_TARGET_SYSTEMS = frozenset({"eurovoc"})

EXPECTED_PAIR_PREDICATE_COUNTS: Mapping[str, Mapping[str, int]] = MappingProxyType(
    {
        "agrovoc": MappingProxyType(
            {
                str(SKOS.exactMatch): 1_188,
                str(SKOS.closeMatch): 5,
                str(SKOS.broadMatch): 4,
                str(SKOS.narrowMatch): 2,
            }
        ),
        "dbpedia": MappingProxyType(
            {
                str(SKOS.closeMatch): 2_035,
                str(SKOS.relatedMatch): 971,
            }
        ),
        "eionet-determinations": MappingProxyType(
            {
                str(SKOS.exactMatch): 31,
                str(SKOS.relatedMatch): 1,
            }
        ),
        "eurovoc": MappingProxyType(
            {
                str(SKOS.exactMatch): 1_683,
                str(SKOS.broadMatch): 217,
                str(SKOS.narrowMatch): 38,
            }
        ),
        "umthes": MappingProxyType(
            {
                str(SKOS.exactMatch): 1,
                str(SKOS.closeMatch): 3_482,
            }
        ),
    }
)
EXPECTED_MAPPING_COUNT = 9_658

_RDF_NAMESPACE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
_RDF_ABOUT = f"{{{_RDF_NAMESPACE}}}about"
_RDF_RESOURCE = f"{{{_RDF_NAMESPACE}}}resource"
_XML_BASE = f"{{{_XML_NAMESPACE}}}base"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ENTITY_GUARD_WINDOW_BYTES = 16_384


class GemetAlignmentError(ValueError):
    """The GEMET mapping export cannot be preserved without guessing."""


@dataclass(frozen=True, slots=True)
class GemetAlignment:
    """One publisher-authored SKOS mapping triple."""

    subject_iri: str
    predicate_iri: str
    object_iri: str
    target_system: str
    target_is_held: bool


@dataclass(frozen=True, slots=True)
class GemetAlignmentCapture:
    """All mappings from one verified GEMET distribution."""

    source_url: str
    retrieved_at: str
    source_sha256: str
    source_byte_length: int
    rdf_sha256: str
    rdf_byte_length: int
    license_statement: str
    license_url: str
    mappings: tuple[GemetAlignment, ...]

    @property
    def pair_predicate_counts(self) -> dict[str, dict[str, int]]:
        counts: dict[str, Counter[str]] = {}
        for row in self.mappings:
            counts.setdefault(row.target_system, Counter())[row.predicate_iri] += 1
        return {pair: dict(sorted(predicate_counts.items())) for pair, predicate_counts in sorted(counts.items())}


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
        raise GemetAlignmentError(f"{label} expected digest is not canonical SHA-256")
    observed_sha256 = _digest(payload)
    if len(payload) != expected_byte_length:
        raise GemetAlignmentError(f"{label} byte length drift: expected {expected_byte_length}, got {len(payload)}")
    if observed_sha256 != expected_sha256:
        raise GemetAlignmentError(f"{label} digest drift: expected {expected_sha256}, got {observed_sha256}")


def _target_system(object_iri: str) -> str:
    matches = [name for name, prefix in TARGET_PREFIXES.items() if object_iri.startswith(prefix)]
    if len(matches) != 1:
        raise GemetAlignmentError(f"GEMET mapping target has no declared endpoint system: {object_iri}")
    return matches[0]


def parse_gemet_alignment_rdf(
    payload: bytes,
    *,
    source_url: str = GEMET_ALIGNMENT_SOURCE_URL,
) -> tuple[GemetAlignment, ...]:
    """Extract explicit SKOS mappings from decompressed GEMET RDF/XML bytes."""

    if not isinstance(payload, bytes):
        raise TypeError("GEMET alignment RDF must be bytes")
    if b"<!ENTITY" in payload[:_ENTITY_GUARD_WINDOW_BYTES].upper():
        raise GemetAlignmentError("GEMET alignment RDF must not declare XML entities")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise GemetAlignmentError(f"could not parse GEMET alignment RDF/XML: {error}") from error

    base = root.attrib.get(_XML_BASE)
    if base != "http://www.eionet.europa.eu/gemet/":
        raise GemetAlignmentError(f"GEMET RDF has an unexpected xml:base: {base!r}")

    scheme_nodes = [
        node
        for node in root
        if node.tag == f"{{{SKOS!s}}}ConceptScheme"
        and urllib.parse.urljoin(base, node.attrib.get(_RDF_ABOUT, "")) == GEMET_SCHEME_IRI
    ]
    if len(scheme_nodes) != 1:
        raise GemetAlignmentError("GEMET RDF must contain its one declared concept scheme")
    license_values = {
        urllib.parse.urljoin(base, child.attrib[_RDF_RESOURCE])
        for child in scheme_nodes[0]
        if child.tag == "{http://purl.org/dc/terms/}licence" and _RDF_RESOURCE in child.attrib
    }
    if license_values != {GEMET_PUBLISHER_LICENSE_IRI}:
        raise GemetAlignmentError(f"GEMET RDF license assertion drifted: observed {sorted(license_values)!r}")

    rows: list[GemetAlignment] = []
    seen: set[tuple[str, str, str]] = set()
    for node in root:
        about = node.attrib.get(_RDF_ABOUT)
        if about is None:
            continue
        subject_iri = urllib.parse.urljoin(base, about)
        for assertion in node:
            predicate_iri = assertion.tag[1:].replace("}", "", 1) if assertion.tag.startswith("{") else assertion.tag
            if predicate_iri not in SKOS_MAPPING_PREDICATES:
                continue
            if not subject_iri.startswith(GEMET_CONCEPT_PREFIX):
                raise GemetAlignmentError(f"GEMET mapping subject is not a GEMET concept: {subject_iri}")
            resource = assertion.attrib.get(_RDF_RESOURCE)
            if resource is None:
                raise GemetAlignmentError(f"GEMET mapping {subject_iri} {predicate_iri} has no rdf:resource target")
            object_iri = urllib.parse.urljoin(base, resource)
            target_system = _target_system(object_iri)
            triple = (subject_iri, predicate_iri, object_iri)
            if triple in seen:
                raise GemetAlignmentError(f"GEMET repeats mapping triple {triple!r}")
            seen.add(triple)
            rows.append(
                GemetAlignment(
                    subject_iri=subject_iri,
                    predicate_iri=predicate_iri,
                    object_iri=object_iri,
                    target_system=target_system,
                    target_is_held=target_system in HELD_TARGET_SYSTEMS,
                )
            )
    return tuple(sorted(rows, key=lambda row: (row.target_system, row.subject_iri, row.predicate_iri, row.object_iri)))


def parse_gemet_alignment_gzip(
    payload: bytes,
    *,
    source_url: str = GEMET_ALIGNMENT_SOURCE_URL,
    retrieved_at: str = GEMET_ALIGNMENT_RETRIEVED_AT,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
    expected_rdf_sha256: str | None = None,
    expected_rdf_byte_length: int | None = None,
) -> GemetAlignmentCapture:
    """Verify and parse one gzip-compressed GEMET mapping distribution."""

    if not isinstance(payload, bytes):
        raise TypeError("GEMET alignment distribution must be bytes")
    if expected_sha256 is not None and expected_byte_length is not None:
        _verify_pin(
            payload,
            expected_sha256=expected_sha256,
            expected_byte_length=expected_byte_length,
            label="GEMET alignment gzip",
        )
    elif expected_sha256 is not None or expected_byte_length is not None:
        raise GemetAlignmentError("GEMET gzip digest and byte length pins must be supplied together")
    try:
        rdf_payload = gzip.decompress(payload)
    except OSError as error:
        raise GemetAlignmentError(f"could not decompress GEMET alignment gzip: {error}") from error
    if expected_rdf_sha256 is not None and expected_rdf_byte_length is not None:
        _verify_pin(
            rdf_payload,
            expected_sha256=expected_rdf_sha256,
            expected_byte_length=expected_rdf_byte_length,
            label="GEMET alignment RDF",
        )
    elif expected_rdf_sha256 is not None or expected_rdf_byte_length is not None:
        raise GemetAlignmentError("GEMET RDF digest and byte length pins must be supplied together")

    mappings = parse_gemet_alignment_rdf(rdf_payload, source_url=source_url)
    return GemetAlignmentCapture(
        source_url=source_url,
        retrieved_at=retrieved_at,
        source_sha256=_digest(payload),
        source_byte_length=len(payload),
        rdf_sha256=_digest(rdf_payload),
        rdf_byte_length=len(rdf_payload),
        license_statement=GEMET_LICENSE_STATEMENT,
        license_url=GEMET_LICENSE_URL,
        mappings=mappings,
    )


def load_gemet_alignments(path: Path) -> GemetAlignmentCapture:
    """Load the exact pinned GEMET 4.2.3 mapping distribution."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise GemetAlignmentError(f"GEMET alignment source is not a regular file: {source}")
    capture = parse_gemet_alignment_gzip(
        source.read_bytes(),
        expected_sha256=GEMET_ALIGNMENT_SHA256,
        expected_byte_length=GEMET_ALIGNMENT_BYTE_LENGTH,
        expected_rdf_sha256=GEMET_ALIGNMENT_RDF_SHA256,
        expected_rdf_byte_length=GEMET_ALIGNMENT_RDF_BYTE_LENGTH,
    )
    observed_counts = capture.pair_predicate_counts
    expected_counts = {pair: dict(sorted(counts.items())) for pair, counts in EXPECTED_PAIR_PREDICATE_COUNTS.items()}
    if len(capture.mappings) != EXPECTED_MAPPING_COUNT or observed_counts != expected_counts:
        raise GemetAlignmentError(
            "GEMET alignment inventory drifted: "
            f"expected=({EXPECTED_MAPPING_COUNT}, {expected_counts!r}), "
            f"observed=({len(capture.mappings)}, {observed_counts!r})"
        )
    return capture


__all__ = [
    "EXPECTED_MAPPING_COUNT",
    "EXPECTED_PAIR_PREDICATE_COUNTS",
    "GEMET_ALIGNMENT_BYTE_LENGTH",
    "GEMET_ALIGNMENT_FILENAME",
    "GEMET_ALIGNMENT_ISSUED",
    "GEMET_ALIGNMENT_LANDING_PAGE_URL",
    "GEMET_ALIGNMENT_RDF_BYTE_LENGTH",
    "GEMET_ALIGNMENT_RDF_SHA256",
    "GEMET_ALIGNMENT_RETRIEVED_AT",
    "GEMET_ALIGNMENT_SHA256",
    "GEMET_ALIGNMENT_SOURCE_URL",
    "GEMET_ALIGNMENT_VERSION",
    "GEMET_LICENSE_STATEMENT",
    "GEMET_LICENSE_URL",
    "HELD_TARGET_SYSTEMS",
    "SKOS_MAPPING_PREDICATES",
    "TARGET_PREFIXES",
    "UMTHES_CONTENT_RIGHTS_NOTE",
    "GemetAlignment",
    "GemetAlignmentCapture",
    "GemetAlignmentError",
    "load_gemet_alignments",
    "parse_gemet_alignment_gzip",
    "parse_gemet_alignment_rdf",
]
