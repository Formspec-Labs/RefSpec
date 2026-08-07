"""Pinned reader for the official EuroVoc--LCSH SKOS alignment.

The Publications Office publishes this alignment independently from the
EuroVoc concept distribution.  This reader therefore keeps the alignment as
its own source release and retains each authored mapping triple exactly.  It
does not infer inverse or transitive mappings.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF, SKOS

ALIGN = Namespace("http://knowledgeweb.semanticweb.org/heterogeneity/alignment#")
CDM = Namespace("http://publications.europa.eu/ontology/cdm#")
VOID = Namespace("http://rdfs.org/ns/void#")

EUROVOC_LCSH_ALIGNMENT_URL = (
    "https://op.europa.eu/o/opportal-service/euvoc-download-handler?"
    "cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2F"
    "eurovoc_alignment_lcsh%2F20240711-0%2Frdf%2Fskos_core_alignment%2F"
    "align_EuroVoc_LCSH.rdf&fileName=align_EuroVoc_LCSH.rdf"
)
EUROVOC_LCSH_ALIGNMENT_FILENAME = "eurovoc-lcsh-alignment-20240711.rdf"
EUROVOC_LCSH_ALIGNMENT_SHA256 = (
    "sha256:dbd6e610ff497c4a39a79924cf50dcf92d5f3e9ab316d58d83c460dba6fb4853"
)
EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH = 332_124
EUROVOC_LCSH_ALIGNMENT_ISSUED = "2024-07-11"
EUROVOC_LCSH_ALIGNMENT_RELEASE_IRI = (
    "http://publications.europa.eu/resource/dataset/"
    "eurovoc_alignment_lcsh/20240711-0"
)
EUROVOC_LCSH_ALIGNMENT_METADATA_URL = EUROVOC_LCSH_ALIGNMENT_RELEASE_IRI
EUROVOC_LCSH_ALIGNMENT_METADATA_FILENAME = (
    "eurovoc-lcsh-alignment-20240711-metadata.rdf"
)
EUROVOC_LCSH_ALIGNMENT_METADATA_SHA256 = (
    "sha256:3792ef3e3ebb18a01c97aa9d7a34f177ed947dd68496b7497a5693f06257faa6"
)
EUROVOC_LCSH_ALIGNMENT_METADATA_BYTE_LENGTH = 8_157
EUROVOC_4_20_RELEASE_IRI = (
    "http://publications.europa.eu/resource/dataset/eurovoc/20240711-0"
)
EUROVOC_4_20_METADATA_URL = EUROVOC_4_20_RELEASE_IRI
EUROVOC_4_20_METADATA_FILENAME = "eurovoc-4.20-20240711-metadata.rdf"
EUROVOC_4_20_METADATA_SHA256 = (
    "sha256:ee86254e0635b9e3ea51ae365153eecd81f0040cb4580d28401986639b0b895d"
)
EUROVOC_4_20_METADATA_BYTE_LENGTH = 14_093
EUROVOC_4_24_METADATA_URL = (
    "https://op.europa.eu/o/opportal-service/euvoc-download-handler?"
    "cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2F"
    "eurovoc%2F20260708-0%2Fttl%2Fmetadata%2Feurovoc_metadata.ttl&"
    "fileName=eurovoc_metadata.ttl"
)
EUROVOC_4_24_METADATA_FILENAME = "eurovoc-4.24-metadata.ttl"
EUROVOC_4_24_METADATA_SHA256 = (
    "sha256:2c58402422f8588aada476f3516051e7fc980182130557a0d8c67497ffd8731d"
)
EUROVOC_4_24_METADATA_BYTE_LENGTH = 36_011

EUROVOC_SCHEME_IRI = "http://eurovoc.europa.eu"
LCSH_SCHEME_IRI = "http://id.loc.gov/authorities/subjects"
EUROVOC_CONCEPT_PREFIX = EUROVOC_SCHEME_IRI + "/"
LCSH_CONCEPT_PREFIX = LCSH_SCHEME_IRI + "/"
SUPPORTED_MAPPING_PREDICATES = frozenset({str(SKOS.exactMatch), str(SKOS.closeMatch)})
EXPECTED_PREDICATE_COUNTS = {
    str(SKOS.exactMatch): 1_904,
    str(SKOS.closeMatch): 99,
}


class EuroVocLcshAlignmentError(ValueError):
    """The pinned alignment cannot be represented without guessing."""


@dataclass(frozen=True, slots=True)
class EuroVocLcshMapping:
    """One publisher-authored SKOS mapping triple."""

    subject_iri: str
    predicate_iri: str
    object_iri: str


@dataclass(frozen=True, slots=True)
class EuroVocLcshAlignment:
    """One verified official alignment artifact."""

    source_url: str
    source_sha256: str
    source_bytes: int
    triple_count: int
    mappings: tuple[EuroVocLcshMapping, ...]

    @property
    def eurovoc_concept_iris(self) -> frozenset[str]:
        return frozenset(row.subject_iri for row in self.mappings)

    @property
    def lcsh_concept_iris(self) -> frozenset[str]:
        return frozenset(row.object_iri for row in self.mappings)


def _verified_bytes(
    path: Path,
    *,
    expected_sha256: str,
    expected_byte_length: int,
    label: str,
) -> bytes:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise EuroVocLcshAlignmentError(f"{label} is not a regular file: {source}")
    payload = source.read_bytes()
    observed = "sha256:" + hashlib.sha256(payload).hexdigest()
    if len(payload) != expected_byte_length or observed != expected_sha256:
        raise EuroVocLcshAlignmentError(
            f"{label} pin differs: expected=({expected_byte_length}, {expected_sha256}), "
            f"observed=({len(payload)}, {observed})"
        )
    return payload


def parse_eurovoc_lcsh_alignment(
    source: bytes,
    *,
    source_url: str = EUROVOC_LCSH_ALIGNMENT_URL,
    expected_sha256: str | None = None,
    expected_byte_length: int | None = None,
) -> EuroVocLcshAlignment:
    """Parse one RDF/XML alignment and retain only its explicit SKOS mappings."""

    if not isinstance(source, bytes):
        raise TypeError("EuroVoc--LCSH alignment source must be bytes")
    digest = "sha256:" + hashlib.sha256(source).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise EuroVocLcshAlignmentError(
            f"alignment digest mismatch: expected {expected_sha256}, got {digest}"
        )
    if expected_byte_length is not None and len(source) != expected_byte_length:
        raise EuroVocLcshAlignmentError(
            "alignment byte length mismatch: "
            f"expected {expected_byte_length}, got {len(source)}"
        )

    with closing(Graph()) as graph:
        try:
            graph.parse(data=source, format="xml", publicID=source_url)
        except Exception as error:
            raise EuroVocLcshAlignmentError(
                f"could not parse EuroVoc--LCSH RDF/XML: {error}"
            ) from error

        alignments = set(graph.subjects(RDF.type, ALIGN.Alignment))
        if len(alignments) != 1:
            raise EuroVocLcshAlignmentError(
                "alignment RDF must identify exactly one align:Alignment, "
                f"found {len(alignments)}"
            )
        alignment = next(iter(alignments))
        if set(graph.objects(alignment, ALIGN.onto1)) != {
            URIRef(EUROVOC_SCHEME_IRI)
        }:
            raise EuroVocLcshAlignmentError("alignment onto1 is not EuroVoc")
        if set(graph.objects(alignment, ALIGN.onto2)) != {URIRef(LCSH_SCHEME_IRI)}:
            raise EuroVocLcshAlignmentError("alignment onto2 is not LCSH")

        unsupported = Counter(
            str(predicate)
            for subject, predicate, obj in graph
            if isinstance(subject, URIRef)
            and str(subject).startswith(EUROVOC_CONCEPT_PREFIX)
            and isinstance(obj, URIRef)
            and str(obj).startswith(LCSH_CONCEPT_PREFIX)
            and str(predicate) not in SUPPORTED_MAPPING_PREDICATES
        )
        if unsupported:
            raise EuroVocLcshAlignmentError(
                "alignment contains unsupported EuroVoc-to-LCSH predicates: "
                f"{dict(sorted(unsupported.items()))}"
            )

        rows: list[EuroVocLcshMapping] = []
        counts: dict[str, int] = {}
        for predicate_iri in sorted(SUPPORTED_MAPPING_PREDICATES):
            predicate = URIRef(predicate_iri)
            triples = sorted(
                graph.subject_objects(predicate),
                key=lambda row: (str(row[0]), str(row[1])),
            )
            counts[predicate_iri] = len(triples)
            for subject, obj in triples:
                if not isinstance(subject, URIRef) or not str(subject).startswith(
                    EUROVOC_CONCEPT_PREFIX
                ):
                    raise EuroVocLcshAlignmentError(
                        f"mapping subject is not a EuroVoc concept IRI: {subject}"
                    )
                if not isinstance(obj, URIRef) or not str(obj).startswith(
                    LCSH_CONCEPT_PREFIX
                ):
                    raise EuroVocLcshAlignmentError(
                        f"mapping object is not an LCSH subject IRI: {obj}"
                    )
                rows.append(
                    EuroVocLcshMapping(
                        subject_iri=str(subject),
                        predicate_iri=predicate_iri,
                        object_iri=str(obj),
                    )
                )
        if counts != EXPECTED_PREDICATE_COUNTS:
            raise EuroVocLcshAlignmentError(
                "alignment mapping counts differ: "
                f"expected={EXPECTED_PREDICATE_COUNTS}, observed={counts}"
            )
        if len(rows) != len(set(rows)):
            raise EuroVocLcshAlignmentError("alignment repeats a mapping triple")
        return EuroVocLcshAlignment(
            source_url=source_url,
            source_sha256=digest,
            source_bytes=len(source),
            triple_count=len(graph),
            mappings=tuple(
                sorted(
                    rows,
                    key=lambda row: (
                        row.subject_iri,
                        row.predicate_iri,
                        row.object_iri,
                    ),
                )
            ),
        )


def parse_eurovoc_lcsh_alignment_file(path: Path) -> EuroVocLcshAlignment:
    """Verify and parse the pinned official alignment file."""

    payload = _verified_bytes(
        path,
        expected_sha256=EUROVOC_LCSH_ALIGNMENT_SHA256,
        expected_byte_length=EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH,
        label="EuroVoc--LCSH alignment",
    )
    return parse_eurovoc_lcsh_alignment(
        payload,
        expected_sha256=EUROVOC_LCSH_ALIGNMENT_SHA256,
        expected_byte_length=EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH,
    )


def verify_eurovoc_4_24_metadata(path: Path) -> None:
    """Verify that current EuroVoc metadata carries both alignment linksets."""

    payload = _verified_bytes(
        path,
        expected_sha256=EUROVOC_4_24_METADATA_SHA256,
        expected_byte_length=EUROVOC_4_24_METADATA_BYTE_LENGTH,
        label="EuroVoc 4.24 metadata",
    )
    with closing(Graph()) as graph:
        try:
            graph.parse(
                data=payload,
                format="turtle",
                publicID=EUROVOC_4_24_METADATA_URL,
            )
        except Exception as error:
            raise EuroVocLcshAlignmentError(
                f"could not parse EuroVoc 4.24 metadata: {error}"
            ) from error
        expected_subject = URIRef("http://eurovoc.europa.eu/void.ttl#EuroVoc_4.24")
        for suffix, predicate, count in (
            ("closeMatch", SKOS.closeMatch, 99),
            ("exactMatch", SKOS.exactMatch, 1_904),
        ):
            linkset = URIRef(
                "http://eurovoc.europa.eu/void.ttl#EuroVoc_LCSH_"
                f"{suffix}_Linkset"
            )
            observed = (
                set(graph.objects(linkset, VOID.subjectsTarget)),
                set(graph.objects(linkset, VOID.objectsTarget)),
                set(graph.objects(linkset, VOID.linkPredicate)),
                {int(value) for value in graph.objects(linkset, VOID.triples)},
            )
            expected = (
                {expected_subject},
                {URIRef("http://eurovoc.europa.eu/void.ttl#LCSH")},
                {predicate},
                {count},
            )
            if observed != expected:
                raise EuroVocLcshAlignmentError(
                    f"EuroVoc 4.24 metadata {suffix} linkset differs: {observed}"
                )


def verify_eurovoc_lcsh_release_metadata(
    alignment_metadata_path: Path,
    eurovoc_metadata_path: Path,
) -> None:
    """Verify the publisher's exact version relationship for the alignment."""

    alignment_payload = _verified_bytes(
        alignment_metadata_path,
        expected_sha256=EUROVOC_LCSH_ALIGNMENT_METADATA_SHA256,
        expected_byte_length=EUROVOC_LCSH_ALIGNMENT_METADATA_BYTE_LENGTH,
        label="EuroVoc--LCSH 20240711-0 release metadata",
    )
    eurovoc_payload = _verified_bytes(
        eurovoc_metadata_path,
        expected_sha256=EUROVOC_4_20_METADATA_SHA256,
        expected_byte_length=EUROVOC_4_20_METADATA_BYTE_LENGTH,
        label="EuroVoc 4.20 release metadata",
    )
    expected = (
        (
            alignment_payload,
            EUROVOC_LCSH_ALIGNMENT_METADATA_URL,
            URIRef(EUROVOC_LCSH_ALIGNMENT_RELEASE_IRI),
            "20240711-0",
            "2024-07-11",
            URIRef(EUROVOC_4_20_RELEASE_IRI),
        ),
        (
            eurovoc_payload,
            EUROVOC_4_20_METADATA_URL,
            URIRef(EUROVOC_4_20_RELEASE_IRI),
            "4.20",
            "2024-07-11",
            URIRef(EUROVOC_LCSH_ALIGNMENT_RELEASE_IRI),
        ),
    )
    for payload, source_url, subject, version, issued, related_release in expected:
        graph = Graph()
        try:
            graph.parse(data=payload, format="xml", publicID=source_url)
            observed_versions = {
                str(value) for value in graph.objects(subject, CDM.version)
            }
            observed_dates = {str(value) for value in graph.objects(subject, CDM.date)}
            observed_related = set(graph.objects(subject, CDM.related_to))
            if (
                observed_versions != {version}
                or observed_dates != {issued}
                or related_release not in observed_related
            ):
                raise EuroVocLcshAlignmentError(
                    f"publisher release metadata differs for {subject}: "
                    f"versions={observed_versions}, dates={observed_dates}, "
                    f"related={observed_related}"
                )
        except EuroVocLcshAlignmentError:
            raise
        except Exception as error:
            raise EuroVocLcshAlignmentError(
                f"could not parse publisher release metadata for {subject}: {error}"
            ) from error
        finally:
            graph.close()


__all__ = [
    "EUROVOC_4_20_METADATA_BYTE_LENGTH",
    "EUROVOC_4_20_METADATA_FILENAME",
    "EUROVOC_4_20_METADATA_SHA256",
    "EUROVOC_4_20_METADATA_URL",
    "EUROVOC_4_20_RELEASE_IRI",
    "EUROVOC_4_24_METADATA_BYTE_LENGTH",
    "EUROVOC_4_24_METADATA_FILENAME",
    "EUROVOC_4_24_METADATA_SHA256",
    "EUROVOC_4_24_METADATA_URL",
    "EUROVOC_LCSH_ALIGNMENT_BYTE_LENGTH",
    "EUROVOC_LCSH_ALIGNMENT_FILENAME",
    "EUROVOC_LCSH_ALIGNMENT_ISSUED",
    "EUROVOC_LCSH_ALIGNMENT_METADATA_BYTE_LENGTH",
    "EUROVOC_LCSH_ALIGNMENT_METADATA_FILENAME",
    "EUROVOC_LCSH_ALIGNMENT_METADATA_SHA256",
    "EUROVOC_LCSH_ALIGNMENT_METADATA_URL",
    "EUROVOC_LCSH_ALIGNMENT_RELEASE_IRI",
    "EUROVOC_LCSH_ALIGNMENT_SHA256",
    "EUROVOC_LCSH_ALIGNMENT_URL",
    "EXPECTED_PREDICATE_COUNTS",
    "EuroVocLcshAlignment",
    "EuroVocLcshAlignmentError",
    "EuroVocLcshMapping",
    "parse_eurovoc_lcsh_alignment",
    "parse_eurovoc_lcsh_alignment_file",
    "verify_eurovoc_4_24_metadata",
    "verify_eurovoc_lcsh_release_metadata",
]
