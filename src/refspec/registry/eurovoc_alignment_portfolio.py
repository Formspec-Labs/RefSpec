"""Digest-pinned reader for the EuroVoc publisher alignment portfolio.

The EU Vocabularies catalogue publishes 18 EuroVoc-to-vocabulary alignments.
The existing ``eurovoc_lcsh_alignment`` reader owns one of them; this module
captures the other 17 versioned Cellar distributions.  Only triples whose
subject is a EuroVoc IRI are portfolio mappings.  Publisher-file anomalies are
counted, not silently promoted into mappings.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, SKOS

EUROVOC_CONCEPT_PREFIX = "http://eurovoc.europa.eu/"
EUROVOC_ALIGNMENT_CATALOGUE_URL = "https://op.europa.eu/en/web/eu-vocabularies/alignments"
EUROVOC_ALIGNMENT_LICENSE_STATEMENT = "publisher states no license"
EUROVOC_ALIGNMENT_GENERAL_REUSE_BASIS_URL = "https://eur-lex.europa.eu/legal-content/en/TXT/?uri=CELEX:32011D0833"
EUROVOC_ALIGNMENT_THIRD_PARTY_RIGHTS_EXCLUSION = (
    "documents for which the Commission is not in a position to allow their reuse in view of "
    "intellectual property rights of third parties"
)

SUPPORTED_MAPPING_PREDICATES = (str(SKOS.exactMatch), str(SKOS.closeMatch))
_REFUSED_MAPPING_PREDICATES = frozenset(
    {
        str(SKOS.broadMatch),
        str(SKOS.narrowMatch),
        str(SKOS.relatedMatch),
        str(OWL.sameAs),
    }
)


class EuroVocAlignmentPortfolioError(ValueError):
    """A pinned portfolio artifact differs or carries an unadmitted claim."""


@dataclass(frozen=True, slots=True)
class EuroVocAlignmentPin:
    """Exact identity and measured shape of one versioned Cellar file."""

    key: str
    title: str
    version: str
    publisher_filename: str
    filename: str
    source_url: str
    expected_sha256: str
    expected_byte_length: int
    retrieved_at: str
    expected_predicate_counts: MappingProxyType[str, int]
    expected_non_eurovoc_mapping_count: int = 0

    @property
    def source_release_iri(self) -> str:
        return f"http://publications.europa.eu/resource/dataset/eurovoc_alignment_{self.key}/{self.version}"

    @property
    def issued(self) -> str:
        return date.fromisoformat(f"{self.version[:4]}-{self.version[4:6]}-{self.version[6:8]}").isoformat()


def _counts(*, exact: int, close: int = 0) -> MappingProxyType[str, int]:
    values = {str(SKOS.exactMatch): exact}
    if close:
        values[str(SKOS.closeMatch)] = close
    return MappingProxyType(values)


def _source_url(key: str, version: str, publisher_filename: str) -> str:
    return (
        "https://op.europa.eu/o/opportal-service/euvoc-download-handler?"
        "cellarURI=http%3A%2F%2Fpublications.europa.eu%2Fresource%2Fdistribution%2F"
        f"eurovoc_alignment_{key}%2F{version}%2Frdf%2Fskos_core_alignment%2F{publisher_filename}"
        f"&fileName={publisher_filename}"
    )


def _pin(
    key: str,
    title: str,
    version: str,
    publisher_filename: str,
    sha256: str,
    byte_length: int,
    retrieved_at: str,
    *,
    exact: int,
    close: int = 0,
    non_eurovoc: int = 0,
) -> EuroVocAlignmentPin:
    return EuroVocAlignmentPin(
        key=key,
        title=title,
        version=version,
        publisher_filename=publisher_filename,
        filename=f"eurovoc-alignment-{key}-{version}.rdf",
        source_url=_source_url(key, version, publisher_filename),
        expected_sha256=sha256,
        expected_byte_length=byte_length,
        retrieved_at=retrieved_at,
        expected_predicate_counts=_counts(exact=exact, close=close),
        expected_non_eurovoc_mapping_count=non_eurovoc,
    )


EUROVOC_ALIGNMENT_PINS = (
    _pin(
        "agrovoc",
        "Agrovoc",
        "20181220-0",
        "align_EuroVoc_Agrovoc.rdf",
        "sha256:c4809e4ebe9951192add8aae7c3428e14b8ad937c739dbdd9b0884be58d9549e",
        290_038,
        "2026-08-15T22:54:12Z",
        exact=1_783,
        close=31,
    ),
    _pin(
        "country",
        "Country",
        "20230915-0",
        "align_EuroVoc_Country.rdf",
        "sha256:61b67881a35260e145cde1401867f0d9f732b97809b5034fad7a53cb4a6e5fbd",
        44_624,
        "2026-08-15T22:54:13Z",
        exact=246,
    ),
    _pin(
        "det",
        "DET",
        "20260617-0",
        "align_EuroVoc_DET.rdf",
        "sha256:0ace99b63ac7b55311210f509e5094965def614b2a138047489a861da107b743",
        221_826,
        "2026-08-15T22:54:14Z",
        exact=1_462,
        close=37,
    ),
    _pin(
        "eclas",
        "Eclas",
        "20210630-0",
        "align_EuroVoc_Eclas.rdf",
        "sha256:44bb596ef912a9d428725d8225b9b70ec6795c26cea23f5e585621bf11cf8282",
        632_464,
        "2026-08-15T22:54:16Z",
        exact=3_618,
        close=381,
        non_eurovoc=3,
    ),
    _pin(
        "eige",
        "Eige",
        "20171215-0",
        "align_EuroVoc_Eige.rdf",
        "sha256:d960ec5f9b5cd9c995c7e5ebb74ac23dbdb4bfb06b547d79bcef81b272e49b2a",
        13_636,
        "2026-08-15T22:54:16Z",
        exact=49,
        close=26,
    ),
    _pin(
        "esco",
        "ESCO",
        "20171215-0",
        "align_EuroVoc_Esco.rdf",
        "sha256:1cc613ae8de54ebbbc6e167c359c967e39d41cbea7fe25ed654b426c792312cb",
        1_705,
        "2026-08-15T22:54:17Z",
        exact=2,
    ),
    _pin(
        "gemet",
        "Gemet",
        "20201218-0",
        "align_EuroVoc_Gemet.rdf",
        "sha256:7d73105ab6e5102f162b8212748acdd3be543ea965d2c3f027bb6282bbfd441d",
        340_681,
        "2026-08-15T22:54:18Z",
        exact=1_920,
        close=116,
    ),
    _pin(
        "gesis",
        "ThesSoz",
        "20171215-0",
        "align_EuroVoc_gesis.rdf",
        "sha256:b5cd1fbe5efea044a4119d0b551cdb079454edbbc9c3f4d3a5bb583e36be6f65",
        1_482,
        "2026-08-15T22:54:20Z",
        exact=2,
    ),
    _pin(
        "gnd",
        "gnd",
        "20181220-0",
        "align_EuroVoc_gnd.rdf",
        "sha256:36fc05d0e4530844d934253225e72e566b0f534eb86d2c497e77310744c5b520",
        34_020,
        "2026-08-15T22:54:21Z",
        exact=196,
        close=19,
    ),
    _pin(
        "inspire",
        "Inspire",
        "20171215-0",
        "align_EuroVoc_Inspire.rdf",
        "sha256:0a938590208ce0706ce18531af9fa56669af35940a086c5f5ad56c329390ac32",
        3_569,
        "2026-08-15T22:54:21Z",
        exact=14,
    ),
    _pin(
        "mesh",
        "mesh",
        "20171215-0",
        "align_EuroVoc_mesh.rdf",
        "sha256:8d1e120994bb9f3381dc01b0a32986564a7bbffeffc64de9dc85377a3ded586c",
        2_976,
        "2026-08-15T22:54:22Z",
        exact=10,
        close=1,
    ),
    _pin(
        "rameau",
        "Rameau",
        "20181220-0",
        "align_EuroVoc_Rameau.rdf",
        "sha256:de61fa7b1df78532575ab757cb1b962b3d4a4dd4a497ad68c4da05def2ff1a3e",
        53_555,
        "2026-08-15T22:54:23Z",
        exact=269,
        close=47,
    ),
    _pin(
        "umt",
        "UMTHES",
        "20181220-0",
        "align_EuroVoc_umt.rdf",
        "sha256:e4b01e12722abab0a2b38aa2c57ec9a7ce5dd57f0a93a873c5f19731ed2fe96c",
        4_933,
        "2026-08-15T22:54:24Z",
        exact=23,
    ),
    _pin(
        "unbis",
        "Unbis",
        "20201218-0",
        "align_EuroVoc_Unbis.rdf",
        "sha256:367d4ea377b51f3bc672099c585937059b3634c6769fdc4a312b595fce6ed860",
        430_379,
        "2026-08-15T22:54:25Z",
        exact=2_379,
        close=411,
    ),
    _pin(
        "unesco",
        "Unesco",
        "20181220-0",
        "align_EuroVoc_Unesco.rdf",
        "sha256:100782a8863e5fe8f679aa9db9f0a4e39f94d64ca3d5ee2dec400c95ebe60a24",
        237_726,
        "2026-08-15T22:54:26Z",
        exact=1_365,
        close=5,
    ),
    _pin(
        "wikidata",
        "WikiData",
        "20260708-0",
        "align_EuroVoc_WikiData.rdf",
        "sha256:bf05aabf4712bb42a46045ddfcdb72bb4ae268b3abb2632d39985d70a9d54978",
        1_494_603,
        "2026-08-15T22:54:28Z",
        exact=5_650,
    ),
    _pin(
        "zbw",
        "ZBW",
        "20181220-0",
        "align_EuroVoc_STW.rdf",
        "sha256:95378374e0324fa57f8c60ee1f5bccf76667ea87384d94dbd1ca1842a0412300",
        416_897,
        "2026-08-15T22:54:29Z",
        exact=2_276,
        close=372,
    ),
)
EUROVOC_ALIGNMENT_PINS_BY_KEY = MappingProxyType({pin.key: pin for pin in EUROVOC_ALIGNMENT_PINS})

EXPECTED_PORTFOLIO_PREDICATE_COUNTS = MappingProxyType(
    {
        str(SKOS.exactMatch): 21_264,
        str(SKOS.closeMatch): 1_446,
    }
)
EXPECTED_PORTFOLIO_ASSERTION_COUNT = sum(EXPECTED_PORTFOLIO_PREDICATE_COUNTS.values())
EXPECTED_COMPLETE_CATALOGUE_ASSERTION_COUNT = EXPECTED_PORTFOLIO_ASSERTION_COUNT + 2_003
EXPECTED_COMPLETE_CATALOGUE_EXACT_PERCENT = 93.75


@dataclass(frozen=True, slots=True)
class EuroVocPortfolioMapping:
    """One direct EuroVoc-to-target mapping from one publisher file."""

    subject_iri: str
    predicate_iri: str
    object_iri: str


@dataclass(frozen=True, slots=True)
class EuroVocAlignmentCapture:
    """One verified alignment distribution and its direct mappings."""

    pin: EuroVocAlignmentPin
    source_sha256: str
    source_byte_length: int
    triple_count: int
    mappings: tuple[EuroVocPortfolioMapping, ...]
    predicate_counts: dict[str, int]
    non_eurovoc_mapping_count: int


@dataclass(frozen=True, slots=True)
class EuroVocAlignmentPortfolio:
    """The complete 17-file complement to the existing LCSH capture."""

    alignments: tuple[EuroVocAlignmentCapture, ...]
    assertion_count: int
    predicate_counts: dict[str, int]
    non_eurovoc_mapping_count: int


def _verified_bytes(path: Path, pin: EuroVocAlignmentPin) -> bytes:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise EuroVocAlignmentPortfolioError(f"EuroVoc {pin.key} alignment is not a regular file: {source}")
    payload = source.read_bytes()
    observed_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    if len(payload) != pin.expected_byte_length or observed_digest != pin.expected_sha256:
        raise EuroVocAlignmentPortfolioError(
            f"EuroVoc {pin.key} alignment input pin differs: "
            f"expected=({pin.expected_byte_length}, {pin.expected_sha256}), "
            f"observed=({len(payload)}, {observed_digest})"
        )
    return payload


def parse_eurovoc_alignment_bytes(source: bytes, *, pin: EuroVocAlignmentPin) -> EuroVocAlignmentCapture:
    """Parse one already-pinned RDF/XML file and enforce publisher direction."""

    if not isinstance(source, bytes):
        raise TypeError("EuroVoc alignment source must be bytes")
    observed_digest = "sha256:" + hashlib.sha256(source).hexdigest()
    if len(source) != pin.expected_byte_length or observed_digest != pin.expected_sha256:
        raise EuroVocAlignmentPortfolioError(
            f"EuroVoc {pin.key} alignment input pin differs: "
            f"expected=({pin.expected_byte_length}, {pin.expected_sha256}), "
            f"observed=({len(source)}, {observed_digest})"
        )
    with closing(Graph()) as graph:
        try:
            graph.parse(data=source, format="xml", publicID=pin.source_url)
        except Exception as error:
            raise EuroVocAlignmentPortfolioError(f"could not parse EuroVoc {pin.key} RDF/XML: {error}") from error

        refused = Counter(
            str(predicate)
            for subject, predicate, obj in graph
            if isinstance(subject, URIRef)
            and str(subject).startswith(EUROVOC_CONCEPT_PREFIX)
            and isinstance(obj, URIRef)
            and str(predicate) in _REFUSED_MAPPING_PREDICATES
        )
        if refused:
            raise EuroVocAlignmentPortfolioError(
                f"EuroVoc {pin.key} contains unsupported mapping predicates: {dict(sorted(refused.items()))}"
            )

        rows: list[EuroVocPortfolioMapping] = []
        anomalies = 0
        counts: Counter[str] = Counter()
        for predicate_iri in SUPPORTED_MAPPING_PREDICATES:
            predicate = URIRef(predicate_iri)
            for subject, obj in graph.subject_objects(predicate):
                if not isinstance(subject, URIRef) or not isinstance(obj, URIRef):
                    raise EuroVocAlignmentPortfolioError(f"EuroVoc {pin.key} mapping endpoints must both be IRIs")
                if not str(subject).startswith(EUROVOC_CONCEPT_PREFIX):
                    anomalies += 1
                    continue
                if str(obj).startswith(EUROVOC_CONCEPT_PREFIX):
                    raise EuroVocAlignmentPortfolioError(
                        f"EuroVoc {pin.key} mapping object unexpectedly belongs to EuroVoc: {obj}"
                    )
                counts[predicate_iri] += 1
                rows.append(
                    EuroVocPortfolioMapping(
                        subject_iri=str(subject),
                        predicate_iri=predicate_iri,
                        object_iri=str(obj),
                    )
                )
        observed_counts = dict(sorted(counts.items()))
        if observed_counts != dict(pin.expected_predicate_counts):
            raise EuroVocAlignmentPortfolioError(
                f"EuroVoc {pin.key} predicate counts differ: "
                f"expected={dict(pin.expected_predicate_counts)!r}, observed={observed_counts!r}"
            )
        if anomalies != pin.expected_non_eurovoc_mapping_count:
            raise EuroVocAlignmentPortfolioError(
                f"EuroVoc {pin.key} non-EuroVoc mapping count differs: "
                f"expected={pin.expected_non_eurovoc_mapping_count}, observed={anomalies}"
            )
        ordered = tuple(sorted(rows, key=lambda row: (row.subject_iri, row.predicate_iri, row.object_iri)))
        if len(ordered) != len(set(ordered)):
            raise EuroVocAlignmentPortfolioError(f"EuroVoc {pin.key} repeats a mapping assertion")
        return EuroVocAlignmentCapture(
            pin=pin,
            source_sha256=observed_digest,
            source_byte_length=len(source),
            triple_count=len(graph),
            mappings=ordered,
            predicate_counts=observed_counts,
            non_eurovoc_mapping_count=anomalies,
        )


def parse_eurovoc_alignment_file(path: Path, *, pin: EuroVocAlignmentPin) -> EuroVocAlignmentCapture:
    """Verify and parse one configured alignment file."""

    return parse_eurovoc_alignment_bytes(_verified_bytes(path, pin), pin=pin)


def load_eurovoc_alignment_portfolio(source_root: Path) -> EuroVocAlignmentPortfolio:
    """Load all 17 versioned files and refuse any portfolio shape drift."""

    alignments = tuple(
        parse_eurovoc_alignment_file(Path(source_root) / pin.filename, pin=pin) for pin in EUROVOC_ALIGNMENT_PINS
    )
    counts = Counter(mapping.predicate_iri for alignment in alignments for mapping in alignment.mappings)
    observed_counts = dict(sorted(counts.items()))
    if observed_counts != dict(EXPECTED_PORTFOLIO_PREDICATE_COUNTS):
        raise EuroVocAlignmentPortfolioError(
            "EuroVoc portfolio predicate counts differ: "
            f"expected={dict(EXPECTED_PORTFOLIO_PREDICATE_COUNTS)!r}, observed={observed_counts!r}"
        )
    return EuroVocAlignmentPortfolio(
        alignments=alignments,
        assertion_count=sum(counts.values()),
        predicate_counts=observed_counts,
        non_eurovoc_mapping_count=sum(item.non_eurovoc_mapping_count for item in alignments),
    )


__all__ = [
    "EUROVOC_ALIGNMENT_CATALOGUE_URL",
    "EUROVOC_ALIGNMENT_GENERAL_REUSE_BASIS_URL",
    "EUROVOC_ALIGNMENT_LICENSE_STATEMENT",
    "EUROVOC_ALIGNMENT_PINS",
    "EUROVOC_ALIGNMENT_PINS_BY_KEY",
    "EUROVOC_ALIGNMENT_THIRD_PARTY_RIGHTS_EXCLUSION",
    "EXPECTED_COMPLETE_CATALOGUE_ASSERTION_COUNT",
    "EXPECTED_COMPLETE_CATALOGUE_EXACT_PERCENT",
    "EXPECTED_PORTFOLIO_ASSERTION_COUNT",
    "EXPECTED_PORTFOLIO_PREDICATE_COUNTS",
    "EuroVocAlignmentCapture",
    "EuroVocAlignmentPin",
    "EuroVocAlignmentPortfolio",
    "EuroVocAlignmentPortfolioError",
    "EuroVocPortfolioMapping",
    "load_eurovoc_alignment_portfolio",
    "parse_eurovoc_alignment_bytes",
    "parse_eurovoc_alignment_file",
]
