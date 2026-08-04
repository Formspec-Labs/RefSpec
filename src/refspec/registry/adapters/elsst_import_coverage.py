"""Independent assertion-level import coverage for exact ELSST releases.

The raw census parses the acquired Turtle bytes directly.  It does not reuse
``ElsstVocabulary`` or any emitted managed-release record.  The parsed census
is reconstructed from the typed parser result, and the indexed census is
reconstructed from the logical managed-release outputs that consumers receive.
The three collections therefore cannot pass merely by sharing one counter.
"""

from __future__ import annotations

import hashlib
import io
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from rdflib import Graph, Namespace, URIRef
from rdflib import Literal as RdfLiteral
from rdflib.exceptions import ParserError
from rdflib.namespace import RDF, SKOS
from rdflib.parser import create_input_source
from rdflib.plugins.parsers.notation3 import BadSyntax, RDFSink, SinkParser
from rdflib.term import Identifier

from refspec.registry.elsst import (
    ADDITIONAL_CONTENT_NOTE_PREDICATE_IRI,
    ALT_LABEL_PREDICATE_IRI,
    BROADER_PREDICATE_IRI,
    DEPRECATED_PREDICATE_IRI,
    HIDDEN_LABEL_PREDICATE_IRI,
    IDENTIFIER_PREDICATE_IRI,
    IS_REPLACED_BY_PREDICATE_IRI,
    IS_VERSION_OF_PREDICATE_IRI,
    NARROWER_PREDICATE_IRI,
    NOTATION_PREDICATE_IRI,
    NOTE_PREDICATE_IRIS,
    PREF_LABEL_PREDICATE_IRI,
    PRIOR_VERSION_PREDICATE_IRI,
    RELATED_PREDICATE_IRI,
    REPLACES_PREDICATE_IRI,
    SKOS_MAPPING_PREDICATE_IRIS,
    ElsstLiteral,
    ElsstVocabulary,
)
from refspec.storage import canonical_json

ELSST_COVERAGE_FEATURES = (
    "labels",
    "languages",
    "notation",
    "notes",
    "hierarchy",
    "associativeRelations",
    "mappings",
    "status",
    "replacements",
    "identifiers",
    "membership",
)

_LABEL_PREDICATES = frozenset(
    {
        PREF_LABEL_PREDICATE_IRI,
        ALT_LABEL_PREDICATE_IRI,
        HIDDEN_LABEL_PREDICATE_IRI,
    }
)
_NOTE_PREDICATES = frozenset(
    {
        *NOTE_PREDICATE_IRIS,
        ADDITIONAL_CONTENT_NOTE_PREDICATE_IRI,
    }
)
_HIERARCHY_PREDICATES = frozenset({BROADER_PREDICATE_IRI, NARROWER_PREDICATE_IRI})
_MAPPING_PREDICATES = frozenset(SKOS_MAPPING_PREDICATE_IRIS)
_REPLACEMENT_PREDICATES = frozenset({IS_REPLACED_BY_PREDICATE_IRI, REPLACES_PREDICATE_IRI})
_IDENTITY_PREDICATES = frozenset(
    {
        IDENTIFIER_PREDICATE_IRI,
        IS_VERSION_OF_PREDICATE_IRI,
        PRIOR_VERSION_PREDICATE_IRI,
    }
)
_MEMBERSHIP_PREDICATES = frozenset(
    {
        str(SKOS.inScheme),
        str(SKOS.topConceptOf),
        str(SKOS.hasTopConcept),
    }
)
_LANGUAGE_FEATURES = frozenset({"labels", "notes", "identifiers"})
_PROV = Namespace("http://www.w3.org/ns/prov#")
_XSD_BOOLEAN_IRI = "http://www.w3.org/2001/XMLSchema#boolean"
_PREFIXES = {
    "dcterms": "http://purl.org/dc/terms/",
    "owl": "http://www.w3.org/2002/07/owl#",
    "prov": "http://www.w3.org/ns/prov#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

CoverageStage = Literal["raw", "parsed", "indexed"]
_ASSERTION_SET_DIGEST_DOMAIN = (
    b"RefSpec ELSST import coverage assertion-set digest v1\0"
)
_MAX_CANONICAL_EXAMPLES = 3


class ElsstImportCoverageError(ValueError):
    """An ELSST assertion was lost, invented, or could not be censused."""


class _CoverageLexicalRDFSink(RDFSink):
    """Stream exact source assertions without retaining an RDF graph."""

    def __init__(
        self,
        graph: Graph,
        collections: dict[str, _AssertionCollector],
    ) -> None:
        super().__init__(graph)
        self.collections = collections

    def newLiteral(
        self,
        s: str,
        dt: URIRef | None,
        lang: str | None,
    ) -> RdfLiteral:
        return RdfLiteral(
            s,
            datatype=dt,
            lang=None if dt is not None else lang,
            normalize=False,
        )

    def makeStatement(
        self,
        quadruple: tuple[object, Identifier, Identifier, Identifier],
        why: object | None = None,
    ) -> None:
        del why
        formula, predicate, subject, object_value = quadruple
        subject = self.normalise(formula, subject)  # type: ignore[arg-type]
        predicate = self.normalise(formula, predicate)  # type: ignore[arg-type]
        object_value = self.normalise(  # type: ignore[arg-type]
            formula,
            object_value,
        )
        if formula != self.rootFormula:
            raise ElsstImportCoverageError(
                "raw ELSST coverage only accepts a Turtle default graph"
            )
        feature = _feature_for_rdf_assertion(
            str(predicate),
            object_value,
        )
        if feature is None:
            return
        identity, assertion, language_tag = _rdf_assertion(
            subject,
            predicate,
            object_value,
        )
        _add_assertion(
            self.collections,
            feature,
            identity,
            assertion=assertion,
            language_tag=language_tag,
        )


def _parse_raw_turtle(
    payload: bytes,
    *,
    source_url: str,
) -> dict[str, _AssertionCollector]:
    collections = _empty_collections()
    graph = Graph()
    source = create_input_source(
        source=io.BytesIO(payload),
        publicID=source_url,
        format="turtle",
    )
    sink = _CoverageLexicalRDFSink(graph, collections)
    base_uri = graph.absolutize(source.getPublicId() or source.getSystemId() or "")
    parser = SinkParser(sink, baseURI=base_uri, turtle=True)
    stream = source.getCharacterStream() or source.getByteStream()
    parser.loadStream(stream)
    return collections


@dataclass(slots=True)
class _AssertionCollector:
    """Compact exact identities plus bounded human-readable diagnostics."""

    hashes: set[bytes]
    examples: dict[bytes, str]

    @classmethod
    def empty(cls) -> _AssertionCollector:
        return cls(hashes=set(), examples={})

    def add(self, canonical_identity: str) -> None:
        assertion_hash = hashlib.sha256(
            canonical_identity.encode("utf-8")
        ).digest()
        self.hashes.add(assertion_hash)
        self._add_example(assertion_hash, canonical_identity)

    def update(self, other: _AssertionCollector) -> None:
        self.hashes.update(other.hashes)
        for assertion_hash, identity in other.examples.items():
            self._add_example(assertion_hash, identity)

    def intersection(
        self,
        other: _AssertionCollector,
    ) -> _AssertionCollector:
        result = _AssertionCollector.empty()
        result.hashes = self.hashes & other.hashes
        for source in (self, other):
            for assertion_hash, identity in source.examples.items():
                if assertion_hash in result.hashes:
                    result._add_example(assertion_hash, identity)
        return result

    def _add_example(
        self,
        assertion_hash: bytes,
        identity: str,
    ) -> None:
        if assertion_hash in self.examples:
            if self.examples[assertion_hash] != identity:
                raise ElsstImportCoverageError(
                    "SHA-256 collision between ELSST assertion identities"
                )
            return
        if len(self.examples) < _MAX_CANONICAL_EXAMPLES:
            self.examples[assertion_hash] = identity
            return
        largest = max(self.examples)
        if assertion_hash < largest:
            del self.examples[largest]
            self.examples[assertion_hash] = identity

    def freeze(self, feature: str) -> ElsstFeatureCensus:
        assertion_hashes = frozenset(self.hashes)
        digest = hashlib.sha256()
        digest.update(_ASSERTION_SET_DIGEST_DOMAIN)
        digest.update(feature.encode("utf-8"))
        digest.update(b"\0")
        for assertion_hash in sorted(assertion_hashes):
            digest.update(b"sha256:")
            digest.update(assertion_hash.hex().encode("ascii"))
            digest.update(b"\n")
        return ElsstFeatureCensus(
            feature=feature,
            assertion_hashes=assertion_hashes,
            canonical_examples=tuple(
                sorted(self.examples.items())
            ),
            digest="sha256:" + digest.hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class ElsstFeatureCensus:
    """Compact assertion hashes for one feature at one stage.

    Each 32-byte value is SHA-256 over one canonical assertion identity.
    ``digest`` hashes the sorted ``sha256:<hex>`` values under the
    versioned ``RefSpec ELSST import coverage assertion-set digest v1``
    domain. At most three canonical identities remain for diagnostics.
    """

    feature: str
    assertion_hashes: frozenset[bytes]
    canonical_examples: tuple[tuple[bytes, str], ...]
    digest: str

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, bytes) or len(value) != 32
            for value in self.assertion_hashes
        ):
            raise ElsstImportCoverageError(
                f"{self.feature} contains a malformed assertion hash"
            )
        if len(self.canonical_examples) > _MAX_CANONICAL_EXAMPLES:
            raise ElsstImportCoverageError(
                f"{self.feature} retains too many canonical examples"
            )
        if any(
            assertion_hash not in self.assertion_hashes
            for assertion_hash, _identity in self.canonical_examples
        ):
            raise ElsstImportCoverageError(
                f"{self.feature} has an example outside its assertion set"
            )
        _require_digest(self.digest, f"{self.feature}.digest")

    @property
    def count(self) -> int:
        return len(self.assertion_hashes)

    def diagnostic_for(self, assertion_hash: bytes) -> str:
        examples = dict(self.canonical_examples)
        return examples.get(
            assertion_hash,
            "sha256:" + assertion_hash.hex(),
        )


@dataclass(frozen=True, slots=True)
class ElsstImportCensus:
    """One independently collected ELSST coverage stage."""

    stage: CoverageStage
    source_sha256: str
    release_iri: str
    features: tuple[ElsstFeatureCensus, ...]

    def feature(self, name: str) -> ElsstFeatureCensus:
        matches = [item for item in self.features if item.feature == name]
        if len(matches) != 1:
            raise ElsstImportCoverageError(f"{self.stage} census does not contain exactly one {name!r} feature")
        return matches[0]


@dataclass(frozen=True, slots=True)
class ElsstCoverageDifference:
    """One exact-set difference between adjacent import stages."""

    feature: str
    transition: Literal["rawToParsed", "parsedToIndexed"]
    expected_count: int
    actual_count: int
    expected_digest: str
    actual_digest: str
    missing_count: int
    unexpected_count: int
    missing_examples: tuple[str, ...]
    unexpected_examples: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ElsstImportCoverageValidation:
    """Complete three-stage coverage result for one exact release."""

    raw: ElsstImportCensus
    parsed: ElsstImportCensus
    indexed: ElsstImportCensus
    differences: tuple[ElsstCoverageDifference, ...]

    @property
    def passed(self) -> bool:
        return not self.differences

    def feature_rows(
        self,
        *,
        required_features: Sequence[str] = ELSST_COVERAGE_FEATURES,
    ) -> tuple[dict[str, Any], ...]:
        required = frozenset(required_features)
        unknown = required - frozenset(ELSST_COVERAGE_FEATURES)
        if unknown:
            raise ElsstImportCoverageError(f"unknown required coverage features: {sorted(unknown)!r}")
        difference_by_feature: dict[str, int] = {}
        for difference in self.differences:
            difference_by_feature[difference.feature] = (
                difference_by_feature.get(difference.feature, 0)
                + difference.missing_count
                + difference.unexpected_count
            )
        rows: list[dict[str, Any]] = []
        for feature in ELSST_COVERAGE_FEATURES:
            raw = self.raw.feature(feature)
            parsed = self.parsed.feature(feature)
            indexed = self.indexed.feature(feature)
            rows.append(
                {
                    "feature": feature,
                    "requiredForCandidateOrOutput": (feature in required),
                    "sourceObservedCount": raw.count,
                    "parsedCount": parsed.count,
                    "indexedCount": indexed.count,
                    "excludedCount": 0,
                    "failedCount": difference_by_feature.get(
                        feature,
                        0,
                    ),
                    "sourceObservedDigest": raw.digest,
                    "parsedDigest": parsed.digest,
                    "indexedDigest": indexed.digest,
                    "exclusions": [],
                    "failures": [],
                }
            )
        return tuple(rows)


def _require_digest(value: str, label: str) -> str:
    if _DIGEST.fullmatch(value) is None:
        raise ElsstImportCoverageError(f"{label} must be a lowercase sha256:<64 hex> digest")
    return value


def _require_iri(value: object, label: str) -> str:
    if not isinstance(value, str) or ":" not in value:
        raise ElsstImportCoverageError(f"{label} must be an absolute IRI")
    return value


def _literal_object(
    *,
    lexical_form: str,
    language_tag: str | None,
    datatype_iri: str | None,
) -> dict[str, str]:
    result = {
        "kind": "literal",
        "lexicalForm": lexical_form,
    }
    if language_tag is not None:
        result["language"] = language_tag
    if datatype_iri is not None:
        result["datatype"] = datatype_iri
    return result


def _literal_assertion(
    *,
    subject_iri: str,
    predicate_iri: str,
    lexical_form: str,
    language_tag: str | None,
    datatype_iri: str | None,
) -> dict[str, Any]:
    return {
        "subject": subject_iri,
        "predicate": predicate_iri,
        "object": _literal_object(
            lexical_form=lexical_form,
            language_tag=language_tag,
            datatype_iri=datatype_iri,
        ),
    }


def _literal_identity(
    *,
    subject_iri: str,
    predicate_iri: str,
    lexical_form: str,
    language_tag: str | None,
    datatype_iri: str | None,
) -> str:
    return canonical_json(
        _literal_assertion(
            subject_iri=subject_iri,
            predicate_iri=predicate_iri,
            lexical_form=lexical_form,
            language_tag=language_tag,
            datatype_iri=datatype_iri,
        )
    )


def _iri_identity(
    *,
    subject_iri: str,
    predicate_iri: str,
    object_iri: str,
) -> str:
    return canonical_json(
        {
            "subject": subject_iri,
            "predicate": predicate_iri,
            "object": {
                "kind": "iri",
                "iri": object_iri,
            },
        }
    )


def _language_identity(
    assertion: Mapping[str, Any],
    language_tag: str,
) -> str:
    return canonical_json(
        {
            "assertion": assertion,
            "language": language_tag,
        }
    )


def _feature_for_predicate(
    predicate_iri: str,
    *,
    object_value: Identifier | None = None,
) -> str | None:
    if predicate_iri in _LABEL_PREDICATES:
        return "labels"
    if predicate_iri == NOTATION_PREDICATE_IRI:
        return "notation"
    if predicate_iri in _NOTE_PREDICATES:
        return "notes"
    if predicate_iri in _HIERARCHY_PREDICATES:
        return "hierarchy"
    if predicate_iri == RELATED_PREDICATE_IRI:
        return "associativeRelations"
    if predicate_iri in _MAPPING_PREDICATES:
        return "mappings"
    if predicate_iri == DEPRECATED_PREDICATE_IRI:
        return "status"
    if predicate_iri in _REPLACEMENT_PREDICATES:
        return "replacements"
    if predicate_iri in _IDENTITY_PREDICATES:
        return "identifiers"
    if predicate_iri in _MEMBERSHIP_PREDICATES:
        return "membership"
    if (
        object_value is not None
        and predicate_iri == str(RDF.type)
        and object_value in {SKOS.Concept, SKOS.ConceptScheme}
    ):
        return "membership"
    return None


def _feature_for_rdf_assertion(
    predicate_iri: str,
    object_value: Identifier,
) -> str | None:
    return _feature_for_predicate(predicate_iri, object_value=object_value)


def _empty_collections() -> dict[str, _AssertionCollector]:
    return {
        feature: _AssertionCollector.empty()
        for feature in ELSST_COVERAGE_FEATURES
    }


def _add_assertion(
    collections: dict[str, _AssertionCollector],
    feature: str,
    identity: str,
    *,
    assertion: Mapping[str, Any] | None = None,
    language_tag: str | None = None,
) -> None:
    collections[feature].add(identity)
    if feature not in _LANGUAGE_FEATURES or language_tag is None:
        return
    if assertion is None:
        raise ElsstImportCoverageError(
            "language feature identity requires the assertion structure"
        )
    collections["languages"].add(_language_identity(assertion, language_tag))


def _add_literal_assertion(
    collections: dict[str, _AssertionCollector],
    feature: str,
    *,
    subject_iri: str,
    predicate_iri: str,
    lexical_form: str,
    language_tag: str | None,
    datatype_iri: str | None,
) -> None:
    assertion = _literal_assertion(
        subject_iri=subject_iri,
        predicate_iri=predicate_iri,
        lexical_form=lexical_form,
        language_tag=language_tag,
        datatype_iri=datatype_iri,
    )
    _add_assertion(
        collections,
        feature,
        canonical_json(assertion),
        assertion=assertion,
        language_tag=language_tag,
    )


def _add_iri_assertion(
    collections: dict[str, _AssertionCollector],
    feature: str,
    *,
    subject_iri: str,
    predicate_iri: str,
    object_iri: str,
) -> None:
    _add_assertion(
        collections,
        feature,
        _iri_identity(
            subject_iri=subject_iri,
            predicate_iri=predicate_iri,
            object_iri=object_iri,
        ),
    )


def _rdf_assertion(
    subject: Identifier,
    predicate: Identifier,
    object_value: Identifier,
) -> tuple[str, Mapping[str, Any] | None, str | None]:
    if not isinstance(subject, URIRef):
        raise ElsstImportCoverageError("covered RDF assertion subject must be an IRI")
    if not isinstance(predicate, URIRef):
        raise ElsstImportCoverageError("covered RDF assertion predicate must be an IRI")
    if isinstance(object_value, URIRef):
        return (
            _iri_identity(
                subject_iri=str(subject),
                predicate_iri=str(predicate),
                object_iri=str(object_value),
            ),
            None,
            None,
        )
    if isinstance(object_value, RdfLiteral):
        language_tag = (
            str(object_value.language) if object_value.language is not None else None
        )
        assertion = _literal_assertion(
            subject_iri=str(subject),
            predicate_iri=str(predicate),
            lexical_form=str(object_value),
            language_tag=language_tag,
            datatype_iri=(
                str(object_value.datatype)
                if object_value.datatype is not None
                else None
            ),
        )
        return canonical_json(assertion), assertion, language_tag
    raise ElsstImportCoverageError("covered RDF assertion object must be an IRI or literal")


def _expand_term(value: str) -> str:
    if value.startswith(("http:", "https:", "urn:")):
        return value
    prefix, separator, suffix = value.partition(":")
    if separator and prefix in _PREFIXES:
        return _PREFIXES[prefix] + suffix
    return value


def _emitted_nodes(
    document: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    raw_nodes = document.get("@graph")
    if (
        not isinstance(raw_nodes, Sequence)
        or isinstance(raw_nodes, (str, bytes))
        or any(not isinstance(node, Mapping) for node in raw_nodes)
    ):
        raise ElsstImportCoverageError("emitted Rulespec graph must contain an @graph array")
    return cast(tuple[Mapping[str, Any], ...], tuple(raw_nodes))


def _node_identifier(node: Mapping[str, Any]) -> str | None:
    value = node.get("@id")
    return value if isinstance(value, str) else None


def _as_values(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(value)
    return (value,)


def _iri_values(value: object) -> tuple[str, ...]:
    values: list[str] = []
    for item in _as_values(value):
        if isinstance(item, str):
            values.append(_expand_term(item))
        elif isinstance(item, Mapping):
            identifier = item.get("@id")
            if isinstance(identifier, str):
                values.append(_expand_term(identifier))
    return tuple(values)


def _literal_values(
    value: object,
    *,
    default_datatype: str | None = None,
) -> tuple[tuple[str, str | None, str | None], ...]:
    values: list[tuple[str, str | None, str | None]] = []
    for item in _as_values(value):
        if isinstance(item, str):
            values.append((item, None, default_datatype))
            continue
        if not isinstance(item, Mapping):
            continue
        if "@value" in item:
            lexical = item.get("@value")
            if isinstance(lexical, bool):
                lexical = "true" if lexical else "false"
            elif not isinstance(lexical, str):
                lexical = str(lexical)
            language = item.get("@language")
            datatype = item.get("@type")
            values.append(
                (
                    lexical,
                    language if isinstance(language, str) else None,
                    (_expand_term(datatype) if isinstance(datatype, str) else default_datatype),
                )
            )
            continue
        for language, literals in item.items():
            if language.startswith("@"):
                continue
            for literal in _as_values(literals):
                if isinstance(literal, str):
                    values.append((literal, language, None))
    return tuple(values)


def _feature_for_emitted_predicate(
    predicate_iri: str,
) -> str | None:
    return _feature_for_predicate(predicate_iri)


def _collect_emitted_graph_assertions(
    document: Mapping[str, Any],
    *,
    allowed_subjects: frozenset[str],
    literal_identifier_subjects: frozenset[str] = frozenset(),
    subset_subjects: frozenset[str] | None = None,
) -> tuple[dict[str, _AssertionCollector], dict[str, _AssertionCollector] | None]:
    collections = _empty_collections()
    subset_collections = (
        _empty_collections() if subset_subjects is not None else None
    )
    targets: list[dict[str, _AssertionCollector]] = [collections]
    for node in _emitted_nodes(document):
        subject = _node_identifier(node)
        if subject is None or subject not in allowed_subjects:
            continue
        active = targets
        if (
            subset_collections is not None
            and subset_subjects is not None
            and subject in subset_subjects
        ):
            active = [collections, subset_collections]
        raw_types = node.get("@type")
        for object_iri in _iri_values(raw_types):
            if object_iri not in {
                str(SKOS.Concept),
                str(SKOS.ConceptScheme),
            }:
                continue
            for target in active:
                _add_iri_assertion(
                    target,
                    "membership",
                    subject_iri=subject,
                    predicate_iri=str(RDF.type),
                    object_iri=object_iri,
                )
        for raw_predicate, raw_value in node.items():
            if raw_predicate.startswith("@"):
                continue
            predicate = _expand_term(raw_predicate)
            feature = _feature_for_emitted_predicate(predicate)
            if feature is None:
                continue
            if (
                feature == "identifiers"
                and predicate == IDENTIFIER_PREDICATE_IRI
                and subject not in literal_identifier_subjects
            ):
                continue
            if feature in {
                "hierarchy",
                "associativeRelations",
                "mappings",
                "replacements",
                "membership",
            } or (feature == "identifiers" and predicate != IDENTIFIER_PREDICATE_IRI):
                for object_iri in _iri_values(raw_value):
                    for target in active:
                        _add_iri_assertion(
                            target,
                            feature,
                            subject_iri=subject,
                            predicate_iri=predicate,
                            object_iri=object_iri,
                        )
                continue
            default_datatype = _XSD_BOOLEAN_IRI if feature == "status" else None
            for lexical, language, datatype in _literal_values(
                raw_value,
                default_datatype=default_datatype,
            ):
                for target in active:
                    _add_literal_assertion(
                        target,
                        feature,
                        subject_iri=subject,
                        predicate_iri=predicate,
                        lexical_form=lexical,
                        language_tag=language,
                        datatype_iri=datatype,
                    )
    return collections, subset_collections


def _emitted_release_members(
    document: Mapping[str, Any],
    *,
    release_iri: str,
) -> frozenset[str]:
    matches = [node for node in _emitted_nodes(document) if _node_identifier(node) == release_iri]
    if len(matches) != 1:
        raise ElsstImportCoverageError(f"emitted release {release_iri} is not defined exactly once")
    values: list[str] = []
    for raw_predicate, raw_value in matches[0].items():
        if _expand_term(raw_predicate) == str(_PROV.hadMember):
            values.extend(_iri_values(raw_value))
    members = frozenset(values)
    if not members:
        raise ElsstImportCoverageError(f"emitted release {release_iri} has no exact prov:hadMember set")
    return members


def _census(
    *,
    stage: CoverageStage,
    source_sha256: str,
    release_iri: str,
    collections: Mapping[str, _AssertionCollector],
) -> ElsstImportCensus:
    _require_digest(source_sha256, "source_sha256")
    _require_iri(release_iri, "release_iri")
    if set(collections) != set(ELSST_COVERAGE_FEATURES):
        raise ElsstImportCoverageError(f"{stage} census feature set is incomplete")
    features = tuple(
        collections[feature].freeze(feature)
        for feature in ELSST_COVERAGE_FEATURES
    )
    return ElsstImportCensus(
        stage=stage,
        source_sha256=source_sha256,
        release_iri=release_iri,
        features=features,
    )


def census_raw_elsst_turtle(
    source: bytes,
    *,
    source_url: str,
    release_iri: str,
    expected_sha256: str,
    expected_byte_length: int,
) -> ElsstImportCensus:
    """Collect feature assertions directly from exact acquired Turtle bytes."""

    if not isinstance(source, bytes):
        raise TypeError("raw ELSST coverage requires exact Turtle bytes")
    _require_iri(source_url, "source_url")
    _require_iri(release_iri, "release_iri")
    expected = _require_digest(expected_sha256, "expected_sha256")
    if expected_byte_length <= 0:
        raise ElsstImportCoverageError("expected_byte_length must be positive")
    actual = "sha256:" + hashlib.sha256(source).hexdigest()
    if actual != expected:
        raise ElsstImportCoverageError(f"raw source digest mismatch: expected {expected}, got {actual}")
    if len(source) != expected_byte_length:
        raise ElsstImportCoverageError(
            f"raw source byte length mismatch: expected {expected_byte_length}, got {len(source)}"
        )
    try:
        collections = _parse_raw_turtle(
            source,
            source_url=source_url,
        )
    except ElsstImportCoverageError:
        raise
    except (BadSyntax, ParserError) as error:
        raise ElsstImportCoverageError(
            f"could not parse raw ELSST Turtle for census: {error}"
        ) from error
    return _census(
        stage="raw",
        source_sha256=actual,
        release_iri=release_iri,
        collections=collections,
    )


def _add_parsed_literal_assertion(
    collections: dict[str, _AssertionCollector],
    feature: str,
    *,
    subject_iri: str,
    predicate_iri: str,
    value: ElsstLiteral,
) -> None:
    _add_literal_assertion(
        collections,
        feature,
        subject_iri=subject_iri,
        predicate_iri=predicate_iri,
        lexical_form=value.lexical_form,
        language_tag=value.language_tag,
        datatype_iri=value.datatype_iri,
    )


def census_parsed_elsst(
    vocabulary: ElsstVocabulary,
    *,
    release_iri: str,
) -> ElsstImportCensus:
    """Collect feature assertions only from the typed parser output."""

    if not isinstance(vocabulary, ElsstVocabulary):
        raise TypeError("parsed ELSST coverage requires ElsstVocabulary")
    collections = _empty_collections()
    for item in vocabulary.labels:
        _add_parsed_literal_assertion(
            collections,
            "labels",
            subject_iri=item.subject_iri,
            predicate_iri=item.property_iri,
            value=item.value,
        )
    for item in vocabulary.notes:
        _add_parsed_literal_assertion(
            collections,
            "notes",
            subject_iri=item.subject_iri,
            predicate_iri=item.property_iri,
            value=item.value,
        )
    for item in vocabulary.notations:
        _add_parsed_literal_assertion(
            collections,
            "notation",
            subject_iri=item.subject_iri,
            predicate_iri=item.property_iri,
            value=item.value,
        )
    for item in vocabulary.semantic_relations:
        feature = "associativeRelations" if item.predicate_iri == RELATED_PREDICATE_IRI else "hierarchy"
        _add_iri_assertion(
            collections,
            feature,
            subject_iri=item.subject_iri,
            predicate_iri=item.predicate_iri,
            object_iri=item.object_iri,
        )
    for item in vocabulary.mapping_relations:
        _add_iri_assertion(
            collections,
            "mappings",
            subject_iri=item.subject_iri,
            predicate_iri=item.predicate_iri,
            object_iri=item.object_iri,
        )
    for item in vocabulary.deprecated_assertions:
        _add_parsed_literal_assertion(
            collections,
            "status",
            subject_iri=item.subject_iri,
            predicate_iri=item.predicate_iri,
            value=item.value,
        )
    for item in vocabulary.replacement_relations:
        _add_iri_assertion(
            collections,
            "replacements",
            subject_iri=item.subject_iri,
            predicate_iri=item.predicate_iri,
            object_iri=item.object_iri,
        )
    for item in vocabulary.metadata_literals:
        if item.property_iri != IDENTIFIER_PREDICATE_IRI:
            continue
        _add_parsed_literal_assertion(
            collections,
            "identifiers",
            subject_iri=item.subject_iri,
            predicate_iri=item.property_iri,
            value=item.value,
        )
    for item in vocabulary.version_relations:
        _add_iri_assertion(
            collections,
            "identifiers",
            subject_iri=item.subject_iri,
            predicate_iri=item.predicate_iri,
            object_iri=item.object_iri,
        )
    for concept in vocabulary.concepts:
        _add_iri_assertion(
            collections,
            "membership",
            subject_iri=concept.concept_iri,
            predicate_iri=str(RDF.type),
            object_iri=str(SKOS.Concept),
        )
        for scheme_iri in concept.scheme_iris:
            _add_iri_assertion(
                collections,
                "membership",
                subject_iri=concept.concept_iri,
                predicate_iri=str(SKOS.inScheme),
                object_iri=scheme_iri,
            )
        for scheme_iri in concept.top_concept_of_iris:
            _add_iri_assertion(
                collections,
                "membership",
                subject_iri=concept.concept_iri,
                predicate_iri=str(SKOS.topConceptOf),
                object_iri=scheme_iri,
            )
    for scheme in vocabulary.concept_schemes:
        _add_iri_assertion(
            collections,
            "membership",
            subject_iri=scheme.scheme_iri,
            predicate_iri=str(RDF.type),
            object_iri=str(SKOS.ConceptScheme),
        )
        for concept_iri in scheme.top_concept_iris:
            _add_iri_assertion(
                collections,
                "membership",
                subject_iri=scheme.scheme_iri,
                predicate_iri=str(SKOS.hasTopConcept),
                object_iri=concept_iri,
            )
    return _census(
        stage="parsed",
        source_sha256=vocabulary.source_sha256,
        release_iri=release_iri,
        collections=collections,
    )


def _record_release_iri(record: Mapping[str, Any]) -> str | None:
    release = record.get("referenceResourceRelease")
    return cast(str, release.get("id")) if isinstance(release, Mapping) and isinstance(release.get("id"), str) else None


def _expression_collections(
    expressions: Sequence[Mapping[str, Any]],
    *,
    release_iri: str,
    member_iris: frozenset[str],
) -> dict[str, _AssertionCollector]:
    collections = _empty_collections()
    for record in expressions:
        if _record_release_iri(record) != release_iri:
            continue
        member = record.get("member")
        predicate = record.get("semanticProperty")
        literal = record.get("originalLiteral")
        if (
            not isinstance(member, str)
            or member not in member_iris
            or not isinstance(predicate, str)
            or not isinstance(literal, str)
        ):
            continue
        feature = _feature_for_rdf_assertion(
            predicate,
            RdfLiteral(literal),
        )
        if feature not in {
            "labels",
            "notation",
            "notes",
            "identifiers",
        }:
            continue
        language = record.get("language")
        datatype = record.get("datatype")
        _add_literal_assertion(
            collections,
            feature,
            subject_iri=member,
            predicate_iri=predicate,
            lexical_form=literal,
            language_tag=(language if isinstance(language, str) else None),
            datatype_iri=(datatype if isinstance(datatype, str) else None),
        )
    return collections


def _normalized_label_identities(
    rows: Sequence[Mapping[str, Any]],
    *,
    release_iri: str,
    member_iris: frozenset[str],
) -> _AssertionCollector:
    identities = _AssertionCollector.empty()
    for row in rows:
        if (
            row.get("release_iri") != release_iri
            or row.get("concept_iri") not in member_iris
            or row.get("migration_only") is True
        ):
            continue
        predicate = row.get("source_property_iri")
        literal = row.get("original_literal")
        language = row.get("language_tag")
        if (
            not isinstance(predicate, str)
            or predicate not in _LABEL_PREDICATES
            or not isinstance(literal, str)
            or not isinstance(language, str)
        ):
            continue
        identities.add(
            _literal_identity(
                subject_iri=cast(str, row["concept_iri"]),
                predicate_iri=predicate,
                lexical_form=literal,
                language_tag=language,
                datatype_iri=None,
            )
        )
    return identities


def _normalized_relation_collections(
    rows: Sequence[Mapping[str, Any]],
    *,
    release_iri: str,
    member_iris: frozenset[str],
) -> dict[str, _AssertionCollector]:
    result = {
        "hierarchy": _AssertionCollector.empty(),
        "associativeRelations": _AssertionCollector.empty(),
    }
    for row in rows:
        subject = row.get("subject_concept_iri")
        predicate = row.get("predicate_iri")
        object_iri = row.get("object_concept_iri")
        if (
            row.get("release_iri") != release_iri
            or row.get("migration_only") is True
            or subject not in member_iris
            or object_iri not in member_iris
            or not isinstance(predicate, str)
        ):
            continue
        if predicate in _HIERARCHY_PREDICATES:
            feature = "hierarchy"
        elif predicate == RELATED_PREDICATE_IRI:
            feature = "associativeRelations"
        else:
            continue
        result[feature].add(
            _iri_identity(
                subject_iri=cast(str, subject),
                predicate_iri=predicate,
                object_iri=cast(str, object_iri),
            )
        )
    return result


def census_indexed_elsst(
    *,
    source_sha256: str,
    release_iri: str,
    concept_scheme_iri: str,
    expressions: Sequence[Mapping[str, Any]],
    rulespec_graph: Mapping[str, Any],
    normalized_labels: Sequence[Mapping[str, Any]],
    normalized_relations: Sequence[Mapping[str, Any]],
) -> ElsstImportCensus:
    """Collect assertions from exact logical managed-release outputs."""

    _require_digest(source_sha256, "source_sha256")
    _require_iri(release_iri, "release_iri")
    _require_iri(concept_scheme_iri, "concept_scheme_iri")
    members = _emitted_release_members(
        rulespec_graph,
        release_iri=release_iri,
    )
    allowed_subjects = frozenset({*members, concept_scheme_iri})
    scheme_subjects = frozenset({concept_scheme_iri})
    graph_collections, scheme_graph = _collect_emitted_graph_assertions(
        rulespec_graph,
        allowed_subjects=allowed_subjects,
        literal_identifier_subjects=scheme_subjects,
        subset_subjects=scheme_subjects,
    )
    if scheme_graph is None:
        raise ElsstImportCoverageError(
            "indexed census requires scheme-scoped graph assertions"
        )
    expression_collections = _expression_collections(
        expressions,
        release_iri=release_iri,
        member_iris=members,
    )
    normalized_label_identities = _normalized_label_identities(
        normalized_labels,
        release_iri=release_iri,
        member_iris=members,
    )
    normalized_relation_collections = _normalized_relation_collections(
        normalized_relations,
        release_iri=release_iri,
        member_iris=members,
    )

    collections = _empty_collections()
    collections["labels"] = expression_collections[
        "labels"
    ].intersection(normalized_label_identities)
    collections["labels"].update(scheme_graph["labels"])
    collections["notation"].update(
        expression_collections["notation"]
    )
    collections["notation"].update(scheme_graph["notation"])
    collections["notes"].update(expression_collections["notes"])
    collections["notes"].update(scheme_graph["notes"])
    collections["hierarchy"] = normalized_relation_collections["hierarchy"]
    collections["associativeRelations"] = normalized_relation_collections["associativeRelations"]
    collections["mappings"] = graph_collections["mappings"]
    collections["status"] = graph_collections["status"]
    collections["replacements"] = graph_collections["replacements"]
    collections["identifiers"].update(
        expression_collections["identifiers"]
    )
    collections["identifiers"].update(
        graph_collections["identifiers"]
    )
    collections["membership"] = graph_collections["membership"]
    collections["languages"].update(
        expression_collections["languages"]
    )
    collections["languages"].update(scheme_graph["languages"])
    return _census(
        stage="indexed",
        source_sha256=source_sha256,
        release_iri=release_iri,
        collections=collections,
    )


def _difference(
    *,
    feature: str,
    transition: Literal["rawToParsed", "parsedToIndexed"],
    expected: ElsstFeatureCensus,
    actual: ElsstFeatureCensus,
) -> ElsstCoverageDifference | None:
    expected_set = expected.assertion_hashes
    actual_set = actual.assertion_hashes
    if expected_set == actual_set:
        return None
    missing = sorted(expected_set - actual_set)
    unexpected = sorted(actual_set - expected_set)
    return ElsstCoverageDifference(
        feature=feature,
        transition=transition,
        expected_count=expected.count,
        actual_count=actual.count,
        expected_digest=expected.digest,
        actual_digest=actual.digest,
        missing_count=len(missing),
        unexpected_count=len(unexpected),
        missing_examples=tuple(
            expected.diagnostic_for(assertion_hash)
            for assertion_hash in missing[:3]
        ),
        unexpected_examples=tuple(
            actual.diagnostic_for(assertion_hash)
            for assertion_hash in unexpected[:3]
        ),
    )


def validate_elsst_import_coverage(
    raw: ElsstImportCensus,
    parsed: ElsstImportCensus,
    indexed: ElsstImportCensus,
) -> ElsstImportCoverageValidation:
    """Compare every canonical assertion across independent collections."""

    if (raw.stage, parsed.stage, indexed.stage) != (
        "raw",
        "parsed",
        "indexed",
    ):
        raise ElsstImportCoverageError("coverage stages must be raw, parsed, and indexed")
    if (
        len(
            {
                raw.source_sha256,
                parsed.source_sha256,
                indexed.source_sha256,
            }
        )
        != 1
    ):
        raise ElsstImportCoverageError("coverage stages do not bind the same exact source digest")
    if len({raw.release_iri, parsed.release_iri, indexed.release_iri}) != 1:
        raise ElsstImportCoverageError("coverage stages do not bind the same exact release")
    differences: list[ElsstCoverageDifference] = []
    for feature in ELSST_COVERAGE_FEATURES:
        raw_feature = raw.feature(feature)
        parsed_feature = parsed.feature(feature)
        indexed_feature = indexed.feature(feature)
        raw_difference = _difference(
            feature=feature,
            transition="rawToParsed",
            expected=raw_feature,
            actual=parsed_feature,
        )
        if raw_difference is not None:
            differences.append(raw_difference)
        indexed_difference = _difference(
            feature=feature,
            transition="parsedToIndexed",
            expected=parsed_feature,
            actual=indexed_feature,
        )
        if indexed_difference is not None:
            differences.append(indexed_difference)
    return ElsstImportCoverageValidation(
        raw=raw,
        parsed=parsed,
        indexed=indexed,
        differences=tuple(differences),
    )


def require_complete_elsst_import_coverage(
    raw: ElsstImportCensus,
    parsed: ElsstImportCensus,
    indexed: ElsstImportCensus,
) -> ElsstImportCoverageValidation:
    """Return a complete result or fail with the dropped feature names."""

    validation = validate_elsst_import_coverage(
        raw,
        parsed,
        indexed,
    )
    if validation.passed:
        return validation
    summaries = [
        (f"{item.feature} {item.transition} missing={item.missing_count} unexpected={item.unexpected_count}")
        for item in validation.differences
    ]
    raise ElsstImportCoverageError("ELSST import coverage failed: " + "; ".join(summaries))


__all__ = [
    "ELSST_COVERAGE_FEATURES",
    "ElsstCoverageDifference",
    "ElsstFeatureCensus",
    "ElsstImportCensus",
    "ElsstImportCoverageError",
    "ElsstImportCoverageValidation",
    "census_indexed_elsst",
    "census_parsed_elsst",
    "census_raw_elsst_turtle",
    "require_complete_elsst_import_coverage",
    "validate_elsst_import_coverage",
]
