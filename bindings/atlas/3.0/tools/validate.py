"""Independent validator for the RefSpec Atlas 3.0 binding.

The validator deliberately imports no RefSpec package code.  A consumer can
copy this binding directory, install ``requirements.txt``, and verify an Atlas
distribution offline.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import re
import sys
import tempfile
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from itertools import zip_longest
from pathlib import Path
from typing import Any, NoReturn

from jsonschema import Draft202012Validator, FormatChecker
from owlrl import DeductiveClosure, OWLRL_Semantics
from pyshacl import validate as shacl_validate
from rdf_canonical import (
    ABSOLUTE_IRI_RE,
    RdfCanonicalError,
)
from rdf_canonical import nquads_line as _canonical_nquads_line
from rdf_canonical import ntriples_term as _canonical_ntriples_term
from rdflib import BNode, Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, PROV, RDF, RDFS, SKOS, XSD
from rdflib.parser import create_input_source
from rdflib.plugins.parsers.nquads import NQuadsParser
from rdflib.plugins.parsers.ntriples import URI, ParseError, r_literal, unquote, uriquote
from referencing import Registry, Resource

BINDING_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BINDING_ROOT.parents[2]
SCHEMA_ROOT = BINDING_ROOT / "schemas"
ONTOLOGY_PATH = BINDING_ROOT / "ontology" / "atlas.ttl"
SHAPES_PATH = BINDING_ROOT / "shapes" / "atlas.shacl.ttl"
FIXTURE_ROOT = BINDING_ROOT / "fixtures"
CORPUS_PATH = FIXTURE_ROOT / "corpus.json"
PROFILE_MAP_PATH = BINDING_ROOT / "registry-resource-profiles.json"
REGISTRY_COVERAGE_PATH = BINDING_ROOT / "tests" / "registry-coverage.json"
REGISTRY_DESCRIPTOR_PROOF_PATH = BINDING_ROOT / "tests" / "registry-descriptors.json"
REGISTRY_DESCRIPTOR_DATASET_PATH = BINDING_ROOT / "tests" / "registry-descriptors.nq"
BINDING_BUNDLE_PATHS = (
    Path("README.md"),
    Path("fixtures/corpus.json"),
    Path("ontology/atlas.ttl"),
    Path("registry-resource-profiles.json"),
    Path("requirements.txt"),
    Path("shapes/atlas.shacl.ttl"),
    Path("tests/registry-coverage.json"),
    Path("tests/registry-descriptors.json"),
    Path("tests/registry-descriptors.nq"),
    Path("tools/build_fixtures.py"),
    Path("tools/rdf_canonical.py"),
    Path("tools/validate.py"),
)

ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")
SKOSXL = Namespace("http://www.w3.org/2008/05/skos-xl#")

VALIDATOR_ID = "refspec-atlas-conformance"
VALIDATOR_VERSION = "3.0"
EXACT_MATCH_TRANSITIVITY_RULE = URIRef("urn:ref:rule:skos-exact-match-closure-path")
DERIVATION_ENGINE = URIRef("https://pypi.org/project/owlrl/7.1.4/")
DERIVATION_ENGINE_VERSION = "7.1.4"

SCHEMAS = {
    "manifest": "atlas-manifest.schema.json",
    "sourceAccounting": "atlas-source-accounting.schema.json",
    "acceptance": "atlas-acceptance.schema.json",
    "corpus": "conformance-corpus.schema.json",
    "registryCoverage": "registry-coverage.schema.json",
    "registryDescriptors": "registry-descriptors.schema.json",
    "registryProfiles": "registry-resource-profiles.schema.json",
}
EXPECTED_FILES = frozenset(
    {
        "atlas-manifest.json",
        "atlas.nq",
        "atlas-source-accounting.json",
        "atlas-acceptance.json",
    }
)
SAFE_INTEGER = 9_007_199_254_740_991
NQUADS_SORT_CHUNK_SIZE = 50_000
NQUADS_SORT_CHUNK_BYTES = 64 * 1024 * 1024
NQUADS_MAX_LINE_BYTES = 16 * 1024 * 1024
NQUADS_MERGE_FAN_IN = 64
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ASSERTION_TYPES = frozenset(
    {ATLAS.MappingAssertion, ATLAS.NativeRelationAssertion, ATLAS.SourceAssignment}
)
RESOURCE_TYPES = frozenset(
    {
        ATLAS.SubjectConcept,
        ATLAS.EntityResource,
        ATLAS.ValueResource,
        ATLAS.LegalIdentityResource,
    }
)
SKOS_MAPPING_PREDICATES = frozenset(
    {SKOS.exactMatch, SKOS.closeMatch, SKOS.broadMatch, SKOS.narrowMatch, SKOS.relatedMatch}
)
SKOS_NATIVE_RELATION_PREDICATES = frozenset({SKOS.broader, SKOS.narrower, SKOS.related})
REVIEW_METHODS = frozenset(
    {
        ATLAS.deterministicTransformation,
        ATLAS.humanReview,
        ATLAS.operatorAdoption,
        ATLAS.publisherAssertion,
        ATLAS.trustedPipelineReview,
        ATLAS.twoMachineAdjudication,
    }
)
EXPECTED_PROFILE_NAMES = frozenset(
    {"codeScheme", "conceptScheme", "identifierScheme", "resourceCollection", "structureScheme"}
)
RING_RESOURCE_CLASSES = {
    ATLAS.entity: ATLAS.EntityResource,
    ATLAS.legalIdentity: ATLAS.LegalIdentityResource,
    ATLAS.subject: ATLAS.SubjectConcept,
    ATLAS.value: ATLAS.ValueResource,
}
RELATION_POLICY_TYPE_NAMES = {
    "MappingAssertion": ATLAS.MappingAssertion,
    "NativeRelationAssertion": ATLAS.NativeRelationAssertion,
    "SourceAssignment": ATLAS.SourceAssignment,
}
ALLOWED_ASSERTED_TYPES = frozenset(
    {
        ATLAS.Release,
        ATLAS.AtlasRelease,
        ATLAS.SourceRelease,
        ATLAS.ResourceScheme,
        ATLAS.AtlasResource,
        *RESOURCE_TYPES,
        ATLAS.Identifier,
        ATLAS.SourceRecord,
        ATLAS.EvidenceBinding,
        ATLAS.EditorialPolicy,
        ATLAS.LifecycleEvent,
        ATLAS.RelationAssertion,
        *ASSERTION_TYPES,
        ATLAS.SkosMappingAssertion,
        SKOS.Concept,
        SKOS.ConceptScheme,
        SKOSXL.Label,
    }
)
ASSERTED_CARRIER_TYPES = frozenset(
    {
        ATLAS.AtlasRelease,
        ATLAS.SourceRelease,
        ATLAS.ResourceScheme,
        *RESOURCE_TYPES,
        ATLAS.Identifier,
        ATLAS.SourceRecord,
        ATLAS.EvidenceBinding,
        ATLAS.EditorialPolicy,
        ATLAS.LifecycleEvent,
        *ASSERTION_TYPES,
        SKOSXL.Label,
    }
)
ALLOWED_ASSERTED_PREDICATES = frozenset(
    {
        RDF.type,
        RDF.subject,
        RDF.predicate,
        RDF.object,
        RDFS.label,
        DCTERMS.identifier,
        DCTERMS.title,
        DCTERMS.issued,
        DCTERMS.description,
        PROV.hadMember,
        PROV.wasDerivedFrom,
        SKOS.inScheme,
        SKOSXL.prefLabel,
        SKOSXL.altLabel,
        SKOSXL.hiddenLabel,
        SKOSXL.literalForm,
        ATLAS.inRelease,
        ATLAS.inSourceRelease,
        ATLAS.inScheme,
        ATLAS.semanticRing,
        ATLAS.supportedRing,
        ATLAS.resourceProfile,
        ATLAS.sourceRecord,
        ATLAS.representsResource,
        ATLAS.collectionMember,
        ATLAS.sourceLocator,
        ATLAS.identifierScheme,
        ATLAS.identifies,
        ATLAS.membershipMode,
        ATLAS.sourceRelease,
        ATLAS.targetRelease,
        ATLAS.governedByPolicy,
        ATLAS.assertionStatus,
        ATLAS.supersedes,
        ATLAS.evidenceSourceRecord,
        ATLAS.evidenceSourceDigest,
        ATLAS.reviewedBy,
        ATLAS.decisionStatus,
        ATLAS.reviewMethod,
        ATLAS.bindsAssertion,
        ATLAS.eventSubject,
        ATLAS.eventType,
        ATLAS.fromRelease,
        ATLAS.toRelease,
        ATLAS.sourceDigest,
        ATLAS.nativePayload,
        ATLAS.descriptorPayload,
        ATLAS.policyPayload,
        ATLAS.notation,
        ATLAS.definition,
        ATLAS.note,
        ATLAS.recordStatus,
        ATLAS.validationRule,
        ATLAS.componentPosition,
        ATLAS.validFrom,
        ATLAS.validUntil,
        ATLAS.identifierValue,
        ATLAS.assertedAt,
        ATLAS.assertionIdentityDigest,
        ATLAS.decidedAt,
        ATLAS.confidence,
        ATLAS.eventAt,
        ATLAS.contentDigest,
    }
)
XL_TO_SKOS = {
    SKOSXL.prefLabel: SKOS.prefLabel,
    SKOSXL.altLabel: SKOS.altLabel,
    SKOSXL.hiddenLabel: SKOS.hiddenLabel,
}
SKOS_TO_XL = {plain: xl for xl, plain in XL_TO_SKOS.items()}
REQUIRED_GATES = frozenset(
    {
        "canonical-json",
        "json-schema",
        "rdf-syntax",
        "ontology-profile",
        "shacl-meta",
        "shacl-data",
        "dataset-closure",
        "source-accounting",
        "projection-parity",
        "reasoning-isolation",
        "profile-conformance",
    }
)
REQUIRED_CORPUS_CASES = frozenset(
    {
        "acceptance-missing-gate",
        "all-resource-profiles",
        "asserted-naked-mapping",
        "asserted-auxiliary-type-only",
        "asserted-untyped-statement",
        "assertion-extra-property",
        "blank-node",
        "cross-role-identity",
        "dataset-digest-mismatch",
        "derived-input-digest",
        "derived-asserted-scheme-collision",
        "derived-is-authoritative",
        "derived-extra-type",
        "derived-extra-branch",
        "derived-naked-mapping",
        "derived-nonresource-endpoint",
        "derived-reflexive-output",
        "derived-withdrawn-input",
        "duplicate-preferred-language",
        "evidence-retargeted",
        "evidence-reviewer-retargeted",
        "identifier-missing-value",
        "label-missing-literal",
        "label-extra-skos-type",
        "manifest-count-mismatch",
        "manifest-unknown-field",
        "mapping-missing-evidence",
        "mapping-wrong-endpoint-release",
        "native-payload-noncanonical",
        "naked-projected-mapping",
        "no-derived",
        "non-english-label",
        "profile-ring-mismatch",
        "policy-payload-changed",
        "rdf-literal-escaping",
        "scheme-assertion-property",
        "source-native-thesaurus",
        "skos-hierarchy-conflict",
        "skos-mapping-conflict",
        "skos-mapping-hierarchy-conflict",
        "skos-mapping-reverse-conflict",
        "skos-mapping-transitive-conflict",
        "skosxl-label-role-overlap",
        "source-accounting-false-inverse",
        "source-accounting-missing-disposition",
        "source-accounting-resource-swap",
        "subject-scheme-disagreement",
        "superseded-policy-revision",
        "supersession-old-still-current",
        "unjustified-thesaurus-related",
        "validator-identity-mismatch",
        "wrong-ring-relation",
    }
)


@dataclass(slots=True)
class AtlasValidationError(ValueError):
    """One deterministic Atlas validation failure."""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True, slots=True)
class ExactMatchIndex:
    """Linear-space index for the pinned symmetric-transitive semantics."""

    component_by_node: Mapping[URIRef, int]
    component_sizes: tuple[int, ...]
    directed_direct_counts: tuple[int, ...]
    direct_triples: frozenset[tuple[URIRef, URIRef, URIRef]]

    def same_component(self, subject: URIRef, obj: URIRef) -> bool:
        component = self.component_by_node.get(subject)
        return component is not None and component == self.component_by_node.get(obj)

    @property
    def inferred_count(self) -> int:
        return sum(
            size**2 - self.directed_direct_counts[index]
            for index, size in enumerate(self.component_sizes)
        )


def _fail(code: str, detail: str) -> NoReturn:
    raise AtlasValidationError(code, detail)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("json.duplicate-key", f"duplicate object key {key!r}")
        result[key] = value
    return result


def _reject_float(value: str) -> NoReturn:
    _fail("json.number", f"floating-point value {value!r} is forbidden")


def _reject_constant(value: str) -> NoReturn:
    _fail("json.number", f"non-finite value {value!r} is forbidden")


def _parse_int(value: str) -> int:
    parsed = int(value)
    if abs(parsed) > SAFE_INTEGER:
        _fail("json.number", f"integer {value!r} exceeds the safe range")
    return parsed


def _reject_nulls_and_numbers(value: Any, location: str = "$") -> None:
    if value is None:
        _fail("json.null", f"{location} contains null")
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > SAFE_INTEGER:
            _fail("json.number", f"{location} exceeds the safe integer range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail("json.number", f"{location} contains a non-finite number")
        _fail("json.number", f"{location} contains a floating-point number")
    if isinstance(value, Mapping):
        for key, child in value.items():
            _reject_nulls_and_numbers(child, f"{location}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _reject_nulls_and_numbers(child, f"{location}[{index}]")


def canonical_json_bytes(value: Any, *, terminal_lf: bool = True) -> bytes:
    """Return REF canonical JSON bytes for an already parsed value."""

    _reject_nulls_and_numbers(value)
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return payload + (b"\n" if terminal_lf else b"")


def canonical_native_json_bytes(value: Any) -> bytes:
    """Return canonical source JSON while preserving publisher null values."""

    def reject_numbers(child: Any, location: str = "$") -> None:
        if child is None or isinstance(child, bool):
            return
        if isinstance(child, int):
            if abs(child) > SAFE_INTEGER:
                _fail("json.number", f"{location} exceeds the safe integer range")
            return
        if isinstance(child, float):
            if not math.isfinite(child):
                _fail("json.number", f"{location} contains a non-finite number")
            _fail("json.number", f"{location} contains a floating-point number")
        if isinstance(child, Mapping):
            for key, grandchild in child.items():
                reject_numbers(grandchild, f"{location}.{key}")
        elif isinstance(child, Sequence) and not isinstance(
            child, (str, bytes, bytearray)
        ):
            for index, grandchild in enumerate(child):
                reject_numbers(grandchild, f"{location}[{index}]")

    reject_numbers(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any, *, terminal_lf: bool = True) -> str:
    return "sha256:" + hashlib.sha256(
        canonical_json_bytes(value, terminal_lf=terminal_lf)
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def ntriples_term(term: Any) -> str:
    """Render one RDF term in one deterministic RDF 1.1 N-Triples form."""

    try:
        return _canonical_ntriples_term(term)
    except RdfCanonicalError as exc:
        code = "rdf.blank-node" if isinstance(term, BNode) else "rdf.term"
        _fail(code, str(exc))


def nquads_line(
    subject: URIRef,
    predicate: URIRef,
    obj: URIRef | Literal,
    graph_id: URIRef,
) -> str:
    """Render one canonical named-graph RDF 1.1 N-Quads statement."""

    try:
        return _canonical_nquads_line(subject, predicate, obj, graph_id)
    except RdfCanonicalError as exc:
        _fail("rdf.term", str(exc))


def _canonical_dataset_lines(
    dataset: Dataset,
    *,
    blank_node_code: str,
    blank_node_detail: str,
) -> list[str]:
    """Render parsed quads canonically while rejecting actual blank-node terms."""

    lines: list[str] = []
    for subject, predicate, obj, graph_id in dataset.quads((None, None, None, None)):
        if any(isinstance(term, BNode) for term in (subject, predicate, obj, graph_id)):
            _fail(blank_node_code, blank_node_detail)
        lines.append(nquads_line(subject, predicate, obj, graph_id))
    return sorted(lines)


class _LexicalNQuadsParser(NQuadsParser):
    """Pinned RDFLib parser variant that never normalizes literal lexemes."""

    def literal(self) -> Literal | bool:
        if not self.peek('"'):
            return False
        lexical, language, datatype = self.eat(r_literal).groups()
        if language and datatype:
            raise ParseError("Can't have both a language and a datatype")
        datatype_node = URI(uriquote(unquote(datatype))) if datatype else None
        return Literal(
            unquote(lexical),
            lang=language or None,
            datatype=datatype_node,
            normalize=False,
        )


def _parse_nquads_preserving_lexical_forms(dataset: Dataset, source: Path) -> None:
    """Parse N-Quads without mutating RDFLib's process-global normalization flag."""

    input_source = create_input_source(source=source, format="nquads")
    try:
        _LexicalNQuadsParser().parse(input_source, dataset)
    finally:
        if input_source.auto_close:
            input_source.close()


def _check_serialized_nquads_profile(path: Path) -> int:
    """Check the line-level canonical profile with bounded memory."""

    previous: bytes | None = None
    line_count = 0
    has_line_ending_error = False
    has_blank_or_padded_line = False
    has_ordering_error = False
    try:
        with path.open("rb") as stream:
            while line := stream.readline(NQUADS_MAX_LINE_BYTES + 1):
                line_count += 1
                if len(line) > NQUADS_MAX_LINE_BYTES:
                    _fail(
                        "rdf.resource-limit",
                        f"atlas.nq line {line_count} exceeds {NQUADS_MAX_LINE_BYTES} bytes",
                    )
                try:
                    line.decode("utf-8")
                except UnicodeDecodeError as exc:
                    _fail("rdf.syntax", f"atlas.nq is not UTF-8: {exc}")
                has_terminal_lf = line.endswith(b"\n")
                has_line_ending_error |= not has_terminal_lf or b"\r" in line
                content = line[:-1] if has_terminal_lf else line
                has_blank_or_padded_line |= not content or content != content.strip()
                if previous is not None and line <= previous:
                    has_ordering_error = True
                previous = line
    except OSError as exc:
        _fail("distribution.file", f"cannot read {path}: {exc}")
    if line_count == 0 or has_line_ending_error:
        _fail("rdf.canonical", "atlas.nq must be nonempty LF text with one terminal LF")
    if has_blank_or_padded_line:
        _fail("rdf.canonical", "atlas.nq contains a blank or padded line")
    if has_ordering_error:
        _fail("rdf.canonical", "atlas.nq lines must be sorted and unique")
    return line_count


def _merge_sorted_nquads_chunks(inputs: Sequence[Path], output: Path) -> None:
    """Merge one bounded group of sorted byte chunks without deduplicating."""

    with ExitStack() as stack:
        streams = [stack.enter_context(path.open("rb")) for path in inputs]
        sink = stack.enter_context(output.open("wb"))
        sink.writelines(heapq.merge(*streams))


def _bound_sorted_nquads_merge(
    chunks: Sequence[Path],
    temporary: Path,
    *,
    fan_in: int,
) -> list[Path]:
    """Reduce sorted chunks until the final merge opens at most ``fan_in`` files."""

    if fan_in < 2:
        raise ValueError("N-Quads merge fan-in must be at least two")
    current = list(chunks)
    pass_index = 0
    while len(current) > fan_in:
        reduced: list[Path] = []
        for group_index, offset in enumerate(range(0, len(current), fan_in)):
            group = current[offset : offset + fan_in]
            if len(group) == 1:
                reduced.append(group[0])
                continue
            output = temporary / f"merge-{pass_index:03d}-{group_index:05d}.nq"
            _merge_sorted_nquads_chunks(group, output)
            reduced.append(output)
            for path in group:
                path.unlink()
        current = reduced
        pass_index += 1
    return current


def _check_canonical_dataset_terms(path: Path, dataset: Dataset, *, line_count: int) -> None:
    """Externally sort canonical parsed quads and compare them to the source bytes."""

    try:
        with tempfile.TemporaryDirectory(prefix="atlas3-canonical-") as raw_temporary:
            temporary = Path(raw_temporary)
            chunks: list[Path] = []
            buffered: list[bytes] = []
            buffered_bytes = 0
            parsed_count = 0

            def flush_chunk() -> None:
                nonlocal buffered_bytes
                if not buffered:
                    return
                buffered.sort()
                chunk = temporary / f"chunk-{len(chunks):05d}.nq"
                with chunk.open("wb") as sink:
                    sink.writelines(buffered)
                chunks.append(chunk)
                buffered.clear()
                buffered_bytes = 0

            for subject, predicate, obj, graph_id in dataset.quads((None, None, None, None)):
                if any(isinstance(term, BNode) for term in (subject, predicate, obj, graph_id)):
                    _fail("rdf.blank-node", "atlas.nq contains a blank node term")
                line = (nquads_line(subject, predicate, obj, graph_id) + "\n").encode("utf-8")
                if len(line) > NQUADS_MAX_LINE_BYTES:
                    _fail(
                        "rdf.resource-limit",
                        f"canonical N-Quads line exceeds {NQUADS_MAX_LINE_BYTES} bytes",
                    )
                if buffered and (
                    len(buffered) >= NQUADS_SORT_CHUNK_SIZE
                    or buffered_bytes + len(line) > NQUADS_SORT_CHUNK_BYTES
                ):
                    flush_chunk()
                buffered.append(line)
                buffered_bytes += len(line)
                parsed_count += 1
            flush_chunk()
            if parsed_count != line_count or not chunks:
                _fail("rdf.canonical", "parsed quad count differs from serialized line count")
            chunks = _bound_sorted_nquads_merge(
                chunks,
                temporary,
                fan_in=NQUADS_MERGE_FAN_IN,
            )
            with ExitStack() as stack:
                streams = [stack.enter_context(chunk.open("rb")) for chunk in chunks]
                source = stack.enter_context(path.open("rb"))
                for actual, expected in zip_longest(source, heapq.merge(*streams)):
                    if actual != expected:
                        _fail("rdf.canonical", "atlas.nq is not in the canonical N-Quads term form")
    except OSError as exc:
        _fail("rdf.resource-limit", f"canonical N-Quads external sort failed: {exc}")


def rdf_node_digest(graph: Graph, node: URIRef) -> str:
    """Digest one node's sorted outgoing RDF facts, excluding the digest itself."""

    facts = [
        (predicate, obj)
        for predicate, obj in graph.predicate_objects(node)
        if predicate != ATLAS.contentDigest
    ]
    if not facts:
        _fail("dataset.node-identity", f"{node} has no digestible RDF facts")
    return _outgoing_facts_digest(facts)


def _load_json(path: Path, *, require_canonical: bool) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _fail("distribution.file", f"cannot read {path}: {exc}")
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_float,
            parse_int=_parse_int,
            parse_constant=_reject_constant,
        )
    except UnicodeDecodeError as exc:
        _fail("json.encoding", f"{path.name} is not UTF-8: {exc}")
    except json.JSONDecodeError as exc:
        _fail("json.syntax", f"{path.name} is not valid JSON: {exc}")
    _reject_nulls_and_numbers(value)
    if require_canonical and raw != canonical_json_bytes(value):
        _fail("json.canonical", f"{path.name} is not canonical REF JSON")
    return value


def _schema_registry() -> tuple[dict[str, Mapping[str, Any]], Registry]:
    schemas: dict[str, Mapping[str, Any]] = {}
    registry = Registry()
    for path in sorted(SCHEMA_ROOT.glob("*.schema.json")):
        value = _load_json(path, require_canonical=False)
        if not isinstance(value, Mapping):
            _fail("schema.meta", f"{path.name} root is not an object")
        try:
            Draft202012Validator.check_schema(value)
            resource = Resource.from_contents(value)
        except Exception as exc:  # noqa: BLE001 - normalize validator-library failures
            _fail("schema.meta", f"{path.name} is not a valid Draft 2020-12 schema: {exc}")
        schema_id = value.get("$id")
        if not isinstance(schema_id, str):
            _fail("schema.meta", f"{path.name} has no string $id")
        if schema_id in schemas:
            _fail("schema.meta", f"duplicate schema $id {schema_id!r}")
        schemas[schema_id] = value
        registry = registry.with_resource(schema_id, resource)
    return schemas, registry


def _schema_by_name(
    name: str, schemas: Mapping[str, Mapping[str, Any]]
) -> Mapping[str, Any]:
    filename = SCHEMAS[name]
    matches = [schema for schema in schemas.values() if str(schema.get("$id", "")).endswith("/" + filename)]
    if len(matches) != 1:
        _fail("schema.meta", f"cannot resolve exactly one {filename}")
    return matches[0]


def _validate_json_schema(
    value: Any,
    schema_name: str,
    *,
    schemas: Mapping[str, Mapping[str, Any]],
    registry: Registry,
    label: str,
) -> None:
    schema = _schema_by_name(schema_name, schemas)
    validator = Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(value), key=lambda error: (list(error.absolute_path), error.message))
    if errors:
        error = errors[0]
        location = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path
        )
        _fail("json.schema", f"{label}{location}: {error.message}")


def _one(graph: Graph, subject: URIRef, predicate: URIRef, *, code: str) -> Any:
    values = list(graph.objects(subject, predicate))
    if len(values) != 1:
        _fail(code, f"{subject} must have exactly one {predicate}; found {len(values)}")
    return values[0]


def _iri(value: Any, *, code: str, label: str) -> URIRef:
    if not isinstance(value, URIRef):
        _fail(code, f"{label} must be an IRI")
    return value


def _literal_text(value: Any, *, code: str, label: str) -> str:
    if not isinstance(value, Literal):
        _fail(code, f"{label} must be a literal")
    return str(value)


def _date_time(value: Any, *, code: str, label: str) -> datetime:
    if not isinstance(value, Literal) or value.datatype != XSD.dateTime:
        _fail(code, f"{label} must be an xsd:dateTime literal")
    lexical = str(value)
    try:
        parsed = datetime.fromisoformat(lexical.replace("Z", "+00:00"))
    except ValueError:
        _fail(code, f"{label} is not a valid dateTime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(code, f"{label} must include an explicit timezone")
    return parsed.astimezone(timezone.utc)


def _binding_digests(
    *,
    content_overrides: Mapping[Path, bytes] | None = None,
) -> dict[str, str]:
    bundle_paths = [
        *BINDING_BUNDLE_PATHS,
        *(path.relative_to(BINDING_ROOT) for path in sorted(SCHEMA_ROOT.glob("*.schema.json"))),
    ]
    overrides = dict(content_overrides or {})
    unknown_overrides = set(overrides) - set(bundle_paths)
    if unknown_overrides:
        _fail("binding.digest", f"binding content override is not bundled: {min(unknown_overrides)}")
    bundle_payloads = {
        relative: overrides.get(relative, (BINDING_ROOT / relative).read_bytes())
        for relative in sorted(set(bundle_paths), key=lambda path: path.as_posix())
    }
    bundle_rows = [
        {
            "byteLength": len(payload),
            "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "path": relative.as_posix(),
        }
        for relative, payload in bundle_payloads.items()
    ]
    return {
        "bindingBundleDigest": canonical_sha256(bundle_rows, terminal_lf=False),
        "ontologyDigest": file_sha256(ONTOLOGY_PATH),
        "shapesDigest": file_sha256(SHAPES_PATH),
        "manifestSchemaDigest": file_sha256(SCHEMA_ROOT / SCHEMAS["manifest"]),
        "sourceAccountingSchemaDigest": file_sha256(SCHEMA_ROOT / SCHEMAS["sourceAccounting"]),
        "acceptanceSchemaDigest": file_sha256(SCHEMA_ROOT / SCHEMAS["acceptance"]),
    }


def _check_binding_pins(manifest: Mapping[str, Any], acceptance: Mapping[str, Any]) -> None:
    expected = _binding_digests()
    manifest_binding = manifest["binding"]
    for field, digest in expected.items():
        if manifest_binding[field] != digest:
            _fail("binding.digest", f"manifest binding.{field} does not match the binding asset")
        if acceptance["inputs"][field] != digest:
            _fail("binding.digest", f"acceptance inputs.{field} does not match the binding asset")
    if manifest_binding["validatorVersion"] != VALIDATOR_VERSION:
        _fail("binding.validator", "manifest validatorVersion does not match this validator")
    if acceptance["validator"] != {"name": VALIDATOR_ID, "version": VALIDATOR_VERSION}:
        _fail("binding.validator", "acceptance validator identity does not match this validator")


def _check_manifest_digest(manifest: Mapping[str, Any]) -> None:
    payload = dict(manifest)
    actual = payload.pop("canonicalPayloadDigest")
    expected = canonical_sha256(payload, terminal_lf=False)
    if actual != expected:
        _fail("manifest.identity", "canonicalPayloadDigest does not match the canonical manifest payload")


def _check_distribution_files(root: Path, manifest: Mapping[str, Any]) -> None:
    if root.is_symlink() or not root.is_dir():
        _fail("distribution.path", f"distribution is not a regular directory: {root}")
    entries = list(root.iterdir())
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            _fail("distribution.path", f"unsafe distribution member: {entry.name}")
    names = {entry.name for entry in entries}
    if names != EXPECTED_FILES:
        _fail(
            "distribution.members",
            f"distribution members differ; missing={sorted(EXPECTED_FILES - names)}, extra={sorted(names - EXPECTED_FILES)}",
        )
    for member in manifest["members"]:
        path = root / member["path"]
        if path.stat().st_size != member["byteLength"]:
            _fail("distribution.length", f"{path.name} byteLength differs")
        if file_sha256(path) != member["digest"]:
            _fail("distribution.digest", f"{path.name} digest differs")


def _parse_dataset(path: Path, manifest: Mapping[str, Any]) -> tuple[Dataset, dict[str, Graph]]:
    line_count = _check_serialized_nquads_profile(path)
    dataset = Dataset()
    try:
        _parse_nquads_preserving_lexical_forms(dataset, path)
    except Exception as exc:  # noqa: BLE001 - normalize RDF parser failures
        _fail("rdf.syntax", f"atlas.nq cannot be parsed as N-Quads: {exc}")
    _check_canonical_dataset_terms(path, dataset, line_count=line_count)

    declared = {row["role"]: URIRef(row["id"]) for row in manifest["graphs"]}
    allowed_ids = set(declared.values())
    counts: Counter[URIRef] = Counter()
    for _, _, _, graph_id in dataset.quads((None, None, None, None)):
        if not isinstance(graph_id, URIRef) or graph_id not in allowed_ids:
            _fail("dataset.graph", f"statement occurs in undeclared graph {graph_id}")
        counts[graph_id] += 1
    for row in manifest["graphs"]:
        graph_id = URIRef(row["id"])
        if counts[graph_id] != row["quadCount"]:
            _fail("dataset.graph-count", f"{row['role']} graph quadCount differs")
    if counts[declared["asserted"]] == 0:
        _fail("dataset.graph", "asserted graph is empty")
    graphs = {role: dataset.graph(graph_id) for role, graph_id in declared.items()}
    return dataset, graphs


def _parse_binding_graphs() -> tuple[Graph, Graph]:
    ontology = Graph()
    shapes = Graph()
    try:
        ontology.parse(ONTOLOGY_PATH, format="turtle")
    except Exception as exc:  # noqa: BLE001 - normalize RDF parser failures
        _fail("ontology.syntax", f"cannot parse atlas.ttl: {exc}")
    try:
        shapes.parse(SHAPES_PATH, format="turtle")
    except Exception as exc:  # noqa: BLE001 - normalize RDF parser failures
        _fail("shacl.syntax", f"cannot parse atlas.shacl.ttl: {exc}")
    return ontology, shapes


def _lint_ontology(ontology: Graph) -> None:
    allowed_predicates = {
        RDF.type,
        RDFS.comment,
        RDFS.domain,
        RDFS.label,
        RDFS.range,
        RDFS.subClassOf,
        OWL.disjointWith,
        OWL.versionInfo,
    }
    allowed_declaration_types = {
        OWL.Ontology,
        OWL.Class,
        OWL.ObjectProperty,
        OWL.DatatypeProperty,
        ATLAS.SemanticRing,
        ATLAS.ResourceProfile,
        ATLAS.AssertionStatus,
        ATLAS.AuthorityStatus,
        ATLAS.MembershipMode,
        ATLAS.EditorialDecisionStatus,
        ATLAS.ReviewMethod,
    }
    allowed_datatype_ranges = {
        RDFS.Literal,
        XSD.dateTime,
        XSD.decimal,
        XSD.integer,
        XSD.string,
    }
    ontology_iri = URIRef("https://refspec.org/ns/atlas/v3")
    for subject, predicate, obj in ontology:
        if isinstance(subject, BNode) or isinstance(obj, BNode):
            _fail("ontology.profile", "Atlas ontology MUST contain no blank nodes")
        if not isinstance(subject, URIRef) or not (
            subject == ontology_iri or str(subject).startswith(str(ATLAS))
        ):
            _fail("ontology.profile", f"Atlas ontology defines an external subject {subject}")
        if predicate not in allowed_predicates:
            _fail("ontology.profile", f"Atlas ontology uses non-allowlisted predicate {predicate}")
        if predicate == RDF.type and obj not in allowed_declaration_types:
            _fail("ontology.profile", f"Atlas ontology uses non-allowlisted rdf:type {obj}")
        if (
            predicate == RDFS.range
            and (subject, RDF.type, OWL.DatatypeProperty) in ontology
            and obj not in allowed_datatype_ranges
        ):
            _fail("ontology.profile", f"Atlas datatype property uses non-RL range {obj}")

    declared_terms = {
        subject
        for subject, _, declaration_type in ontology.triples((None, RDF.type, None))
        if declaration_type in allowed_declaration_types and subject != ontology_iri
    }
    for subject in declared_terms:
        if not list(ontology.objects(subject, RDFS.label)):
            _fail("ontology.term", f"Atlas term has no rdfs:label: {subject}")


def _run_shacl(graphs: Mapping[str, Graph], ontology: Graph, shapes: Graph) -> None:
    """Validate authoritative inputs; exact regeneration validates the projection."""

    first = True
    for role in ("asserted", "derived"):
        try:
            conforms, _, report = shacl_validate(
                graphs[role],
                shacl_graph=shapes,
                ont_graph=ontology,
                inference="none",
                advanced=False,
                abort_on_first=False,
                allow_infos=False,
                allow_warnings=False,
                meta_shacl=first,
            )
        except Exception as exc:  # noqa: BLE001 - normalize SHACL processor failures
            code = "shacl.meta" if first else "shacl.data"
            _fail(code, f"SHACL processor failed for {role}: {exc}")
        first = False
        if not conforms:
            compact = " ".join(str(report).split())
            _fail("shacl.data", f"{role} graph does not conform: {compact[:900]}")


def _check_graph_roles(graphs: Mapping[str, Graph]) -> None:
    asserted = graphs["asserted"]
    projection = graphs["projection"]
    derived = graphs["derived"]
    projection_only_predicates = _projection_only_predicates()

    for subject, predicate, _ in asserted:
        if predicate in projection_only_predicates:
            _fail("dataset.graph-placement", f"bare projected predicate {predicate} occurs in asserted graph")
        if predicate not in ALLOWED_ASSERTED_PREDICATES:
            _fail("dataset.graph-placement", f"unsupported asserted predicate {predicate} on {subject}")
    for subject in set(asserted.subjects()):
        types = set(asserted.objects(subject, RDF.type))
        unsupported_types = types - ALLOWED_ASSERTED_TYPES
        if unsupported_types:
            _fail(
                "dataset.graph-placement",
                f"asserted subject {subject} has unsupported type {min(unsupported_types, key=str)}",
            )
        carrier_types = types & ASSERTED_CARRIER_TYPES
        if len(carrier_types) != 1:
            _fail(
                "dataset.graph-placement",
                f"asserted subject {subject} must have exactly one concrete Atlas carrier type",
            )
        carrier_type = next(iter(carrier_types))
        expected_types = {carrier_type}
        if carrier_type in RESOURCE_TYPES:
            expected_types.add(ATLAS.AtlasResource)
            if carrier_type == ATLAS.SubjectConcept or (
                carrier_type == ATLAS.ValueResource and SKOS.Concept in types
            ):
                expected_types.add(SKOS.Concept)
        elif carrier_type == ATLAS.ResourceScheme:
            if set(asserted.objects(subject, ATLAS.resourceProfile)) == {
                ATLAS.conceptScheme
            } or any(asserted.subjects(SKOS.inScheme, subject)):
                expected_types.add(SKOS.ConceptScheme)
        elif carrier_type in ASSERTION_TYPES:
            expected_types.add(ATLAS.RelationAssertion)
            if (
                carrier_type == ATLAS.MappingAssertion
                and set(asserted.objects(subject, ATLAS.semanticRing)) == {ATLAS.subject}
            ):
                expected_types.add(ATLAS.SkosMappingAssertion)
        if types != expected_types:
            _fail(
                "dataset.graph-placement",
                f"asserted subject {subject} type set differs from its concrete carrier",
            )
        if ATLAS.ProjectedRelation in types or ATLAS.DerivedRelation in types:
            _fail("dataset.graph-placement", f"{subject} has a non-asserted carrier type in the asserted graph")

    derived_nodes = set(derived.subjects(RDF.type, ATLAS.DerivedRelation))
    for subject in derived_nodes:
        if set(derived.objects(subject, RDF.type)) != {ATLAS.DerivedRelation}:
            _fail("dataset.graph-placement", f"derived subject {subject} has an extra carrier type")
    for subject, predicate, _ in derived:
        if subject not in derived_nodes:
            _fail("dataset.graph-placement", f"derived graph has non-DerivedRelation subject {subject}")
        if predicate in projection_only_predicates:
            _fail("dataset.graph-placement", f"bare projected predicate {predicate} occurs in derived graph")

    asserted_carrier_nodes = {
        subject
        for carrier_type in ASSERTED_CARRIER_TYPES
        for subject in asserted.subjects(RDF.type, carrier_type)
    }
    projection_nodes = set(projection.subjects(RDF.type, ATLAS.ProjectedRelation))
    overlaps = {
        "asserted/projection": asserted_carrier_nodes & projection_nodes,
        "asserted/derived": asserted_carrier_nodes & derived_nodes,
        "projection/derived": projection_nodes & derived_nodes,
    }
    for label, nodes in overlaps.items():
        if nodes:
            _fail("dataset.graph-placement", f"record identity crosses {label} roles: {min(nodes, key=str)}")


def _profile_policy_document() -> Mapping[str, Any]:
    profile_map = _load_json(PROFILE_MAP_PATH, require_canonical=True)
    expected_keys = {
        "format",
        "namespace",
        "profileDigest",
        "profiles",
        "relationPolicies",
        "schemaVersion",
    }
    if not isinstance(profile_map, Mapping) or set(profile_map) != expected_keys:
        _fail("profile.policy", "profile policy fields are incomplete or unknown")
    if profile_map.get("format") != "refspec-atlas-registry-resource-profiles/3.0":
        _fail("profile.policy", "profile policy format is not Atlas 3.0")
    if profile_map.get("namespace") != str(ATLAS):
        _fail("profile.policy", "profile policy namespace is not the Atlas 3.0 namespace")
    if profile_map.get("schemaVersion") != "3.0":
        _fail("profile.policy", "profile policy schemaVersion is not 3.0")
    expected_digest = canonical_sha256(
        {key: value for key, value in profile_map.items() if key != "profileDigest"},
        terminal_lf=False,
    )
    if profile_map.get("profileDigest") != expected_digest:
        _fail("profile.policy", "profileDigest does not match the canonical profile policy")
    return profile_map


def _profile_policies() -> dict[URIRef, Mapping[str, Any]]:
    profile_map = _profile_policy_document()
    policies: dict[URIRef, Mapping[str, Any]] = {}
    rows = profile_map.get("profiles")
    if not isinstance(rows, list):
        _fail("profile.policy", "profiles must be a list")
    observed_names: list[str] = []
    for position, row in enumerate(rows):
        location = f"profiles[{position}]"
        if not isinstance(row, Mapping) or set(row) != {
            "applicableEntryClasses",
            "applicableSemanticRings",
            "descriptorBehavior",
            "profile",
            "resourceKinds",
        }:
            _fail("profile.policy", f"{location} fields are incomplete or unknown")
        name = row.get("profile")
        if not isinstance(name, str) or name not in EXPECTED_PROFILE_NAMES:
            _fail("profile.policy", f"{location}.profile is unsupported")
        observed_names.append(name)
        for field, allow_empty in (
            ("applicableEntryClasses", False),
            ("applicableSemanticRings", True),
            ("resourceKinds", False),
        ):
            values = row.get(field)
            if (
                not isinstance(values, list)
                or (not allow_empty and not values)
                or not all(isinstance(value, str) and value for value in values)
                or values != sorted(values)
                or len(values) != len(set(values))
            ):
                _fail("profile.policy", f"{location}.{field} must be a unique sorted string list")
        ring_names = row["applicableSemanticRings"]
        if any(URIRef(str(ATLAS) + value) not in RING_RESOURCE_CLASSES for value in ring_names):
            _fail("profile.policy", f"{location}.applicableSemanticRings contains an unknown ring")
        if any(not ABSOLUTE_IRI_RE.fullmatch(value) for value in row["applicableEntryClasses"]):
            _fail("profile.policy", f"{location}.applicableEntryClasses contains a non-absolute IRI")
        behavior = row.get("descriptorBehavior")
        expected_behavior = (
            "alwaysDescriptorOnly" if name == "resourceCollection" else "descriptorOnlyUntilExactRelease"
        )
        if behavior != expected_behavior or (name == "resourceCollection" and ring_names):
            _fail("profile.policy", f"{location}.descriptorBehavior or rings are inconsistent")
        profile = URIRef(str(ATLAS) + name)
        if profile in policies:
            _fail("profile.policy", f"duplicate profile policy {profile}")
        policies[profile] = row
    if observed_names != sorted(EXPECTED_PROFILE_NAMES):
        _fail("profile.policy", "profiles must contain the five profiles once in sorted order")
    return policies


def _relation_policies() -> dict[URIRef, dict[URIRef, frozenset[URIRef]]]:
    """Load the one canonical ring/type/predicate policy matrix."""

    profile_map = _profile_policy_document()
    rows = profile_map.get("relationPolicies")
    if not isinstance(rows, list) or len(rows) != len(RING_RESOURCE_CLASSES):
        _fail("profile.policy", "relationPolicies must contain exactly four rows")
    expected_ring_names = sorted(str(ring).removeprefix(str(ATLAS)) for ring in RING_RESOURCE_CLASSES)
    observed_ring_names: list[str] = []
    policies: dict[URIRef, dict[URIRef, frozenset[URIRef]]] = {}
    seen_predicates: set[URIRef] = set()
    for position, row in enumerate(rows):
        location = f"relationPolicies[{position}]"
        if not isinstance(row, Mapping) or set(row) != {
            "assertionPredicates",
            "resourceClass",
            "semanticRing",
        }:
            _fail("profile.policy", f"{location} fields are incomplete or unknown")
        ring_name = row.get("semanticRing")
        if not isinstance(ring_name, str):
            _fail("profile.policy", f"{location}.semanticRing must be a string")
        observed_ring_names.append(ring_name)
        ring = URIRef(str(ATLAS) + ring_name)
        expected_resource_class = RING_RESOURCE_CLASSES.get(ring)
        if expected_resource_class is None or row.get("resourceClass") != str(expected_resource_class):
            _fail("profile.policy", f"{location}.resourceClass does not match its ring")
        raw_predicates = row.get("assertionPredicates")
        if not isinstance(raw_predicates, Mapping) or set(raw_predicates) != set(
            RELATION_POLICY_TYPE_NAMES
        ):
            _fail("profile.policy", f"{location}.assertionPredicates has the wrong type cells")
        ring_policy: dict[URIRef, frozenset[URIRef]] = {}
        for type_name, assertion_type in RELATION_POLICY_TYPE_NAMES.items():
            values = raw_predicates[type_name]
            if (
                not isinstance(values, list)
                or not values
                or not all(isinstance(value, str) and ABSOLUTE_IRI_RE.fullmatch(value) for value in values)
                or values != sorted(values)
                or len(values) != len(set(values))
            ):
                _fail("profile.policy", f"{location}.{type_name} predicates must be nonempty, unique, sorted absolute IRIs")
            predicates = frozenset(URIRef(value) for value in values)
            allowed_skos = (
                SKOS_MAPPING_PREDICATES
                if assertion_type == ATLAS.MappingAssertion
                else SKOS_NATIVE_RELATION_PREDICATES
                if assertion_type == ATLAS.NativeRelationAssertion
                else frozenset()
            )
            for predicate in predicates:
                if not str(predicate).startswith(str(ATLAS)) and not (
                    ring == ATLAS.subject and predicate in allowed_skos
                ):
                    _fail("profile.policy", f"{location}.{type_name} contains unsupported predicate {predicate}")
            overlap = seen_predicates & predicates
            if overlap:
                _fail("profile.policy", f"relation predicate occurs in more than one policy cell: {min(overlap, key=str)}")
            seen_predicates.update(predicates)
            ring_policy[assertion_type] = predicates
        policies[ring] = ring_policy
    if observed_ring_names != expected_ring_names or set(policies) != set(RING_RESOURCE_CLASSES):
        _fail("profile.policy", "relationPolicies rings must occur once in sorted order")
    return policies


def _projection_only_predicates() -> frozenset[URIRef]:
    relation_predicates = frozenset().union(
        *(
            predicates
            for ring_policy in _relation_policies().values()
            for predicates in ring_policy.values()
        )
    )
    return relation_predicates | frozenset({SKOS.prefLabel, SKOS.altLabel, SKOS.hiddenLabel})


def _check_profile_conformance(asserted: Graph) -> None:
    policies = _profile_policies()
    for subject_type in (ATLAS.ResourceScheme, ATLAS.AtlasRelease, *RESOURCE_TYPES):
        for subject in set(asserted.subjects(RDF.type, subject_type)):
            profile = _iri(
                _one(asserted, subject, ATLAS.resourceProfile, code="profile.conformance"),
                code="profile.conformance",
                label="resource profile",
            )
            policy = policies.get(profile)
            if policy is None:
                _fail("profile.conformance", f"{subject} uses unknown profile {profile}")
            rings = set(asserted.objects(subject, ATLAS.semanticRing))
            allowed_rings = {URIRef(str(ATLAS) + value) for value in policy["applicableSemanticRings"]}
            if rings - allowed_rings:
                _fail("profile.conformance", f"{subject} ring is not allowed by {profile}")
            if subject_type == ATLAS.ResourceScheme:
                if rings:
                    _fail(
                        "profile.conformance",
                        f"{subject} must declare supportedRing, not one singular semanticRing",
                    )
                supported_rings = set(asserted.objects(subject, ATLAS.supportedRing))
                if supported_rings - allowed_rings:
                    _fail("profile.conformance", f"{subject} supported ring is not allowed by {profile}")
            if subject_type != ATLAS.ResourceScheme and len(rings) != 1:
                _fail("profile.conformance", f"{subject} must have exactly one allowed semantic ring")
            if subject_type in RESOURCE_TYPES:
                allowed_classes = {URIRef(value) for value in policy["applicableEntryClasses"]}
                if subject_type not in allowed_classes:
                    _fail("profile.conformance", f"{subject_type} is not allowed by {profile}")

    for identifier in set(asserted.subjects(RDF.type, ATLAS.Identifier)):
        scheme = _iri(
            _one(asserted, identifier, ATLAS.identifierScheme, code="profile.conformance"),
            code="profile.conformance",
            label="identifier scheme",
        )
        profile = _iri(
            _one(asserted, scheme, ATLAS.resourceProfile, code="profile.conformance"),
            code="profile.conformance",
            label="identifier profile",
        )
        policy = policies.get(profile)
        if policy is None or str(ATLAS.Identifier) not in policy["applicableEntryClasses"]:
            _fail("profile.conformance", f"{identifier} is not allowed by {profile}")


def _assertion_type(graph: Graph, assertion: URIRef) -> URIRef:
    types = ASSERTION_TYPES & set(graph.objects(assertion, RDF.type))
    if len(types) != 1:
        _fail("dataset.assertion", f"{assertion} must have exactly one concrete assertion type")
    assertion_type = next(iter(types))
    expected_types = {ATLAS.RelationAssertion, assertion_type}
    if assertion_type == ATLAS.MappingAssertion:
        ring = set(graph.objects(assertion, ATLAS.semanticRing))
        if ring == {ATLAS.subject}:
            expected_types.add(ATLAS.SkosMappingAssertion)
    actual_types = set(graph.objects(assertion, RDF.type)) & (
        {ATLAS.RelationAssertion, ATLAS.SkosMappingAssertion} | set(ASSERTION_TYPES)
    )
    if actual_types != expected_types:
        _fail("dataset.assertion", f"{assertion} assertion types differ from {sorted(map(str, expected_types))}")
    return assertion_type


def _resource_type(graph: Graph, resource: URIRef) -> URIRef:
    types = RESOURCE_TYPES & set(graph.objects(resource, RDF.type))
    if len(types) != 1:
        _fail("dataset.resource", f"{resource} must have exactly one Atlas resource type")
    return next(iter(types))


def _assertion_basis(graph: Graph, assertion: URIRef) -> tuple[dict[str, Any], tuple[URIRef, URIRef, URIRef]]:
    assertion_type = _assertion_type(graph, assertion)
    subject = _iri(_one(graph, assertion, RDF.subject, code="dataset.assertion"), code="dataset.assertion", label="assertion subject")
    predicate = _iri(_one(graph, assertion, RDF.predicate, code="dataset.assertion"), code="dataset.assertion", label="assertion predicate")
    obj = _iri(_one(graph, assertion, RDF.object, code="dataset.assertion"), code="dataset.assertion", label="assertion object")
    ring = _iri(_one(graph, assertion, ATLAS.semanticRing, code="dataset.assertion"), code="dataset.assertion", label="semantic ring")
    source_release = _iri(_one(graph, assertion, ATLAS.sourceRelease, code="dataset.assertion"), code="dataset.assertion", label="source release")
    target_release = _iri(_one(graph, assertion, ATLAS.targetRelease, code="dataset.assertion"), code="dataset.assertion", label="target release")
    policy = _iri(_one(graph, assertion, ATLAS.governedByPolicy, code="dataset.assertion"), code="dataset.assertion", label="policy")
    if (policy, RDF.type, ATLAS.EditorialPolicy) not in graph:
        _fail("dataset.assertion", f"{assertion} names unknown editorial policy {policy}")
    policy_digest = _literal_text(
        _one(graph, policy, ATLAS.contentDigest, code="dataset.assertion"),
        code="dataset.assertion",
        label="policy contentDigest",
    )
    basis = {
        "object": str(obj),
        "policy": str(policy),
        "policyContentDigest": policy_digest,
        "predicate": str(predicate),
        "semanticRing": str(ring),
        "sourceRelease": str(source_release),
        "subject": str(subject),
        "targetRelease": str(target_release),
        "type": str(assertion_type),
    }
    return basis, (subject, predicate, obj)


def _validate_assertions(
    asserted: Graph,
) -> dict[tuple[URIRef, URIRef, URIRef], frozenset[URIRef]]:
    relation_policies = _relation_policies()
    assertions = {
        subject
        for assertion_type in ASSERTION_TYPES
        for subject in asserted.subjects(RDF.type, assertion_type)
        if isinstance(subject, URIRef)
    }
    states: dict[
        URIRef,
        tuple[dict[str, Any], tuple[URIRef, URIRef, URIRef], URIRef, datetime, URIRef | None],
    ] = {}
    for assertion in sorted(assertions, key=str):
        basis, triple = _assertion_basis(asserted, assertion)
        identity_digest = canonical_sha256(basis)
        stored_identity_digest = _literal_text(
            _one(
                asserted,
                assertion,
                ATLAS.assertionIdentityDigest,
                code="dataset.assertion-identity",
            ),
            code="dataset.assertion-identity",
            label="assertionIdentityDigest",
        )
        if stored_identity_digest != identity_digest:
            _fail("dataset.assertion-identity", f"{assertion} identity digest differs")
        expected_id = URIRef(
            "urn:ref:atlas-assertion:" + identity_digest.removeprefix("sha256:")
        )
        if assertion != expected_id:
            _fail("dataset.assertion-identity", f"{assertion} is not its stable claim IRI")

        stored_content_digest = _literal_text(
            _one(asserted, assertion, ATLAS.contentDigest, code="dataset.assertion-identity"),
            code="dataset.assertion-identity",
            label="contentDigest",
        )
        if stored_content_digest != rdf_node_digest(asserted, assertion):
            _fail("dataset.assertion-identity", f"{assertion} contentDigest differs")

        status = _iri(
            _one(asserted, assertion, ATLAS.assertionStatus, code="dataset.assertion"),
            code="dataset.assertion",
            label="assertionStatus",
        )
        asserted_at = _date_time(
            _one(asserted, assertion, ATLAS.assertedAt, code="dataset.assertion"),
            code="dataset.assertion",
            label="assertedAt",
        )
        predecessors = list(asserted.objects(assertion, ATLAS.supersedes))
        if len(predecessors) > 1 or any(not isinstance(value, URIRef) for value in predecessors):
            _fail("dataset.supersession", f"{assertion} has an invalid supersedes value")
        predecessor = predecessors[0] if predecessors else None
        states[assertion] = (basis, triple, status, asserted_at, predecessor)

        assertion_type = URIRef(basis["type"])
        ring = URIRef(basis["semanticRing"])
        predicate = triple[1]
        allowed = relation_policies.get(ring, {}).get(assertion_type, frozenset())
        if predicate not in allowed:
            _fail("dataset.relation", f"{assertion} predicate {predicate} is not allowed for its ring and type")

        source_release = URIRef(basis["sourceRelease"])
        target_release = URIRef(basis["targetRelease"])
        subject, _, obj = triple
        if assertion_type == ATLAS.SourceAssignment:
            if (subject, RDF.type, ATLAS.SourceRecord) not in asserted:
                _fail("dataset.assignment", f"{assertion} subject is not a SourceRecord")
            if source_release not in asserted.objects(subject, ATLAS.inSourceRelease):
                _fail("dataset.assignment", f"{assertion} source release does not match its SourceRecord")
            if target_release not in asserted.objects(obj, ATLAS.inRelease):
                _fail("dataset.assignment", f"{assertion} target release does not contain its object")
            if set(asserted.objects(obj, ATLAS.semanticRing)) != {ring}:
                _fail("dataset.assignment", f"{assertion} target ring differs from its assertion ring")
        else:
            _resource_type(asserted, subject)
            _resource_type(asserted, obj)
            if source_release not in asserted.objects(subject, ATLAS.inRelease):
                _fail("dataset.release", f"{assertion} source release does not contain its subject")
            if target_release not in asserted.objects(obj, ATLAS.inRelease):
                _fail("dataset.release", f"{assertion} target release does not contain its object")
            if set(asserted.objects(subject, ATLAS.semanticRing)) != {ring} or set(
                asserted.objects(obj, ATLAS.semanticRing)
            ) != {ring}:
                _fail("dataset.release", f"{assertion} endpoint ring differs from its assertion ring")
            if assertion_type == ATLAS.NativeRelationAssertion and source_release != target_release:
                _fail("dataset.release", f"{assertion} native relation crosses releases")
            if assertion_type == ATLAS.MappingAssertion and source_release == target_release:
                _fail("dataset.release", f"{assertion} mapping endpoints use one release")

    successors: dict[URIRef, set[URIRef]] = defaultdict(set)
    for assertion, (basis, _, _, asserted_at, predecessor) in states.items():
        if predecessor is None:
            continue
        if predecessor == assertion or predecessor not in states:
            _fail("dataset.supersession", f"{assertion} supersedes itself or an unknown assertion")
        predecessor_basis, _, _, predecessor_time, _ = states[predecessor]
        for field in ("type", "semanticRing", "subject", "sourceRelease"):
            if basis[field] != predecessor_basis[field]:
                _fail(
                    "dataset.supersession",
                    f"{assertion} and {predecessor} disagree on lineage field {field}",
                )
        if asserted_at <= predecessor_time:
            _fail("dataset.supersession", f"{assertion} is not later than {predecessor}")
        successors[predecessor].add(assertion)

    for predecessor, rows in successors.items():
        if len(rows) != 1:
            _fail("dataset.supersession", f"{predecessor} has more than one direct successor")

    projected: dict[tuple[URIRef, URIRef, URIRef], set[URIRef]] = defaultdict(set)
    for assertion, (_, triple, status, _, _) in states.items():
        has_successor = bool(successors[assertion])
        if has_successor and status != ATLAS.superseded:
            _fail("dataset.supersession", f"non-terminal {assertion} must have superseded status")
        if not has_successor and status == ATLAS.superseded:
            _fail("dataset.supersession", f"terminal {assertion} cannot have superseded status")
        if not has_successor and status == ATLAS.current:
            projected[triple].add(assertion)
    return {triple: frozenset(assertions) for triple, assertions in projected.items()}


def _check_evidence_bindings(asserted: Graph) -> None:
    assertions = {
        subject
        for assertion_type in ASSERTION_TYPES
        for subject in asserted.subjects(RDF.type, assertion_type)
    }
    source_records = set(asserted.subjects(RDF.type, ATLAS.SourceRecord))
    bindings = set(asserted.subjects(RDF.type, ATLAS.EvidenceBinding))
    bound_assertions: set[URIRef] = set()
    for binding in sorted(bindings, key=str):
        assertion = _iri(
            _one(asserted, binding, ATLAS.bindsAssertion, code="dataset.evidence"),
            code="dataset.evidence",
            label="bound assertion",
        )
        source_record = _iri(
            _one(asserted, binding, ATLAS.evidenceSourceRecord, code="dataset.evidence"),
            code="dataset.evidence",
            label="evidence source record",
        )
        if assertion not in assertions:
            _fail("dataset.evidence", f"{binding} binds unknown assertion {assertion}")
        if source_record not in source_records:
            _fail("dataset.evidence", f"{binding} names unknown source record {source_record}")
        _iri(
            _one(asserted, binding, ATLAS.reviewedBy, code="dataset.evidence"),
            code="dataset.evidence",
            label="reviewer",
        )
        if _one(asserted, binding, ATLAS.decisionStatus, code="dataset.evidence") != ATLAS.approved:
            _fail("dataset.evidence", f"{binding} is not an approved editorial decision")
        if _one(asserted, binding, ATLAS.reviewMethod, code="dataset.evidence") not in REVIEW_METHODS:
            _fail("dataset.evidence", f"{binding} uses an unsupported review method")
        _date_time(
            _one(asserted, binding, ATLAS.decidedAt, code="dataset.evidence"),
            code="dataset.evidence",
            label="decidedAt",
        )
        confidence_values = list(asserted.objects(binding, ATLAS.confidence))
        if len(confidence_values) > 1:
            _fail("dataset.evidence", f"{binding} has more than one confidence value")
        if confidence_values:
            confidence = confidence_values[0]
            if not isinstance(confidence, Literal) or confidence.datatype != XSD.decimal:
                _fail("dataset.evidence", f"{binding} confidence is not xsd:decimal")
            try:
                parsed_confidence = Decimal(str(confidence))
            except InvalidOperation:
                _fail("dataset.evidence", f"{binding} confidence is not a decimal")
            if not Decimal(0) <= parsed_confidence <= Decimal(1):
                _fail("dataset.evidence", f"{binding} confidence is outside 0..1")
        pinned_source_digest = _literal_text(
            _one(asserted, binding, ATLAS.evidenceSourceDigest, code="dataset.evidence-identity"),
            code="dataset.evidence-identity",
            label="evidenceSourceDigest",
        )
        actual_source_digest = _literal_text(
            _one(asserted, source_record, ATLAS.contentDigest, code="dataset.evidence-identity"),
            code="dataset.evidence-identity",
            label="evidence SourceRecord contentDigest",
        )
        if pinned_source_digest != actual_source_digest:
            _fail("dataset.evidence-identity", f"{binding} does not pin its exact SourceRecord")
        stored = _literal_text(
            _one(asserted, binding, ATLAS.contentDigest, code="dataset.evidence-identity"),
            code="dataset.evidence-identity",
            label="contentDigest",
        )
        expected = rdf_node_digest(asserted, binding)
        if stored != expected:
            _fail("dataset.evidence-identity", f"{binding} contentDigest differs")
        expected_id = URIRef("urn:ref:atlas-evidence:" + expected.removeprefix("sha256:"))
        if binding != expected_id:
            _fail("dataset.evidence-identity", f"{binding} is not its content-derived IRI")
        bound_assertions.add(assertion)
    missing = assertions - bound_assertions
    if missing:
        _fail("dataset.evidence", f"assertion has no immutable evidence binding: {min(missing, key=str)}")


def _hierarchy_connected_pairs(
    hierarchy: Mapping[URIRef, set[URIRef]],
    pairs: Iterable[frozenset[URIRef]],
) -> set[frozenset[URIRef]]:
    """Find hierarchy-connected pairs with one target-aware traversal per source."""

    targets_by_source: dict[URIRef, dict[URIRef, frozenset[URIRef]]] = defaultdict(dict)
    for pair in pairs:
        members = sorted(pair, key=str)
        source = members[0]
        target = members[-1]
        targets_by_source[source][target] = pair
        targets_by_source[target][source] = pair

    connected: set[frozenset[URIRef]] = set()
    for source in sorted(targets_by_source, key=str):
        pending = dict(targets_by_source[source])
        frontier = deque([source])
        visited: set[URIRef] = set()
        while frontier and pending:
            current_node = frontier.popleft()
            for broader in hierarchy.get(current_node, set()):
                pair = pending.pop(broader, None)
                if pair is not None:
                    connected.add(pair)
                if broader not in visited:
                    visited.add(broader)
                    frontier.append(broader)
    return connected


def _build_exact_match_index(
    current: Mapping[tuple[URIRef, URIRef, URIRef], frozenset[URIRef]],
) -> ExactMatchIndex:
    """Index exactMatch components without retaining their Cartesian closure."""

    direct_triples = frozenset(
        triple for triple in current if triple[1] == SKOS.exactMatch
    )
    adjacency: dict[URIRef, set[URIRef]] = defaultdict(set)
    for subject, _, obj in direct_triples:
        adjacency[subject].add(obj)
        adjacency[obj].add(subject)

    component_by_node: dict[URIRef, int] = {}
    component_sizes: list[int] = []
    for start in sorted(adjacency, key=str):
        if start in component_by_node:
            continue
        frontier = [start]
        visited = {start}
        while frontier:
            current_node = frontier.pop()
            for neighbor in adjacency[current_node] - visited:
                visited.add(neighbor)
                frontier.append(neighbor)
        component = len(component_sizes)
        component_sizes.append(len(visited))
        for node in visited:
            component_by_node[node] = component

    directed_direct_counts = [0] * len(component_sizes)
    for subject, _, _ in direct_triples:
        directed_direct_counts[component_by_node[subject]] += 1
    return ExactMatchIndex(
        component_by_node=component_by_node,
        component_sizes=tuple(component_sizes),
        directed_direct_counts=tuple(directed_direct_counts),
        direct_triples=direct_triples,
    )


def _check_skos_integrity(
    current: Mapping[tuple[URIRef, URIRef, URIRef], frozenset[URIRef]],
    exact_index: ExactMatchIndex | None = None,
) -> None:
    exact_index = exact_index or _build_exact_match_index(current)
    hierarchy: dict[URIRef, set[URIRef]] = defaultdict(set)
    related_pairs: set[frozenset[URIRef]] = set()
    thesaurus_related_pairs: set[frozenset[URIRef]] = set()
    mapping_relations: list[tuple[URIRef, URIRef, URIRef]] = []
    for subject, predicate, obj in current:
        if predicate in {SKOS.broadMatch, SKOS.narrowMatch, SKOS.relatedMatch}:
            mapping_relations.append((subject, predicate, obj))
        if predicate == SKOS.broader:
            hierarchy[subject].add(obj)
        elif predicate == SKOS.narrower or predicate == SKOS.narrowMatch:
            hierarchy[obj].add(subject)
        elif predicate == SKOS.broadMatch:
            hierarchy[subject].add(obj)
        elif predicate == SKOS.related or predicate == SKOS.relatedMatch:
            related_pairs.add(frozenset((subject, obj)))
        elif predicate == ATLAS.thesaurusRelated:
            thesaurus_related_pairs.add(frozenset((subject, obj)))

    for subject, predicate, obj in sorted(
        mapping_relations,
        key=lambda triple: tuple(map(str, triple)),
    ):
        if exact_index.same_component(subject, obj):
            _fail(
                "dataset.skos-integrity",
                f"SKOS S46 exactMatch-component conflict for {(subject, predicate, obj)}",
            )

    hierarchy_connected = _hierarchy_connected_pairs(
        hierarchy,
        related_pairs | thesaurus_related_pairs,
    )
    pair_key = lambda pair: tuple(map(str, sorted(pair, key=str)))
    for pair in sorted(related_pairs, key=pair_key):
        members = sorted(pair, key=str)
        source = members[0]
        target = members[-1]
        if pair in hierarchy_connected:
            _fail("dataset.skos-integrity", f"SKOS S27 transitive hierarchy conflict for {(source, target)}")

    for pair in sorted(thesaurus_related_pairs, key=pair_key):
        members = sorted(pair, key=str)
        source = members[0]
        target = members[-1]
        if pair not in hierarchy_connected:
            _fail(
                "dataset.skos-integrity",
                "atlas:thesaurusRelated is allowed only for an authored associative "
                f"link with a transitive hierarchy conflict: {(source, target)}",
            )


def _outgoing_facts_digest(facts: Iterable[tuple[URIRef, URIRef | Literal]]) -> str:
    rows = sorted(
        f"{ntriples_term(predicate)} {ntriples_term(obj)} ."
        for predicate, obj in facts
        if predicate != ATLAS.contentDigest
    )
    if not rows:
        _fail("dataset.node-identity", "node has no digestible RDF facts")
    return "sha256:" + hashlib.sha256(("\n".join(rows) + "\n").encode("utf-8")).hexdigest()


def _projection_record_iri(triple: tuple[URIRef, URIRef, URIRef]) -> URIRef:
    subject, predicate, obj = triple
    digest = hashlib.sha256(
        canonical_json_bytes(
            {"object": str(obj), "predicate": str(predicate), "subject": str(subject)},
            terminal_lf=False,
        )
    ).hexdigest()
    return URIRef("urn:ref:atlas-projection:" + digest)


def _projection_support_ring(
    asserted: Graph,
    triple: tuple[URIRef, URIRef, URIRef],
    assertions: frozenset[URIRef],
) -> URIRef:
    rings = {
        ring
        for assertion in assertions
        for ring in asserted.objects(assertion, ATLAS.semanticRing)
    }
    if len(rings) != 1:
        _fail("dataset.projection", f"projection support for {triple} disagrees on semantic ring")
    return _iri(next(iter(rings)), code="dataset.projection", label="projection semantic ring")


def _projection_record_facts(
    asserted: Graph,
    triple: tuple[URIRef, URIRef, URIRef],
    assertions: frozenset[URIRef],
) -> tuple[URIRef, list[tuple[URIRef, URIRef | Literal]]]:
    subject, predicate, obj = triple
    projection = _projection_record_iri(triple)
    facts: list[tuple[URIRef, URIRef | Literal]] = [
        (RDF.type, ATLAS.ProjectedRelation),
        (ATLAS.relationSubject, subject),
        (ATLAS.relationPredicate, predicate),
        (ATLAS.relationObject, obj),
        (ATLAS.semanticRing, _projection_support_ring(asserted, triple, assertions)),
    ]
    facts.extend(
        (ATLAS.supportingAssertion, assertion)
        for assertion in sorted(assertions, key=str)
    )
    return projection, facts


def _expected_projection_triples(
    asserted: Graph,
    supported: Mapping[tuple[URIRef, URIRef, URIRef], frozenset[URIRef]],
) -> Iterable[tuple[URIRef, URIRef, URIRef | Literal]]:
    emitted_label_triples: set[tuple[URIRef, URIRef, Literal]] = set()
    for xl_predicate, plain_predicate in XL_TO_SKOS.items():
        for resource, _, label in asserted.triples((None, xl_predicate, None)):
            literal = _one(asserted, _iri(label, code="dataset.label", label="label"), SKOSXL.literalForm, code="dataset.label")
            if not isinstance(literal, Literal):
                _fail("dataset.label", f"{label} literalForm must be a literal")
            triple = (resource, plain_predicate, literal)
            if triple not in emitted_label_triples:
                emitted_label_triples.add(triple)
                yield triple

    for triple, assertions in sorted(supported.items(), key=lambda row: tuple(map(str, row[0]))):
        yield triple
        projection, facts = _projection_record_facts(asserted, triple, assertions)
        for fact_predicate, fact_object in facts:
            yield projection, fact_predicate, fact_object
        yield projection, ATLAS.contentDigest, Literal(_outgoing_facts_digest(facts))


def _expected_projection(
    asserted: Graph,
    supported: Mapping[tuple[URIRef, URIRef, URIRef], frozenset[URIRef]] | None = None,
) -> Graph:
    expected = Graph()
    analysis = supported if supported is not None else _validate_assertions(asserted)
    for triple in _expected_projection_triples(asserted, analysis):
        expected.add(triple)
    return expected


def _check_projection(
    asserted: Graph,
    projection: Graph,
    supported: Mapping[tuple[URIRef, URIRef, URIRef], frozenset[URIRef]],
) -> None:
    projection_records: dict[
        URIRef,
        tuple[tuple[URIRef, URIRef, URIRef], frozenset[URIRef]],
    ] = {}
    for triple, assertions in supported.items():
        record_iri = _projection_record_iri(triple)
        previous = projection_records.get(record_iri)
        if previous is not None and previous[0] != triple:
            _fail("dataset.projection", f"projection record identity collision for {record_iri}")
        projection_records[record_iri] = (triple, assertions)

    def triple_key(triple: tuple[Any, Any, Any]) -> tuple[str, str, str]:
        return tuple(ntriples_term(term) for term in triple)  # type: ignore[return-value]

    def is_expected(triple: tuple[Any, Any, Any]) -> bool:
        subject, predicate, obj = triple
        if triple in supported:
            return True
        xl_predicate = SKOS_TO_XL.get(predicate)
        if xl_predicate is not None and isinstance(obj, Literal):
            return any(
                (label, SKOSXL.literalForm, obj) in asserted
                for label in asserted.objects(subject, xl_predicate)
            )
        record = projection_records.get(subject)
        if record is None:
            return False
        relation, assertions = record
        relation_subject, relation_predicate, relation_object = relation
        if predicate == RDF.type:
            return obj == ATLAS.ProjectedRelation
        if predicate == ATLAS.relationSubject:
            return obj == relation_subject
        if predicate == ATLAS.relationPredicate:
            return obj == relation_predicate
        if predicate == ATLAS.relationObject:
            return obj == relation_object
        if predicate == ATLAS.semanticRing:
            return obj == _projection_support_ring(asserted, relation, assertions)
        if predicate == ATLAS.supportingAssertion:
            return obj in assertions
        if predicate == ATLAS.contentDigest:
            _, facts = _projection_record_facts(asserted, relation, assertions)
            return obj == Literal(_outgoing_facts_digest(facts))
        return False

    missing_count = 0
    first_missing: tuple[URIRef, URIRef, URIRef | Literal] | None = None
    for triple in _expected_projection_triples(asserted, supported):
        if triple not in projection:
            missing_count += 1
            if first_missing is None or triple_key(triple) < triple_key(first_missing):
                first_missing = triple

    extra_count = 0
    first_extra: tuple[Any, Any, Any] | None = None
    for triple in projection:
        if not is_expected(triple):
            extra_count += 1
            if first_extra is None or triple_key(triple) < triple_key(first_extra):
                first_extra = triple

    if missing_count or extra_count:
        detail = f"projection differs; missing={missing_count}, extra={extra_count}"
        if first_missing is not None:
            detail += f", firstMissing={first_missing}"
        if first_extra is not None:
            detail += f", firstExtra={first_extra}"
        _fail("dataset.projection", detail)


def _check_release_membership(asserted: Graph) -> None:
    releases = {subject for subject in asserted.subjects(RDF.type, ATLAS.AtlasRelease)}
    resources = {
        subject
        for resource_type in RESOURCE_TYPES
        for subject in asserted.subjects(RDF.type, resource_type)
    }
    for release in releases:
        release_ring = _one(asserted, release, ATLAS.semanticRing, code="dataset.release")
        release_profile = _one(asserted, release, ATLAS.resourceProfile, code="dataset.release")
        scheme = _iri(
            _one(asserted, release, ATLAS.inScheme, code="dataset.release"),
            code="dataset.release",
            label="release scheme",
        )
        if (scheme, RDF.type, ATLAS.ResourceScheme) not in asserted:
            _fail("dataset.release", f"{release} names an unknown ResourceScheme")
        if release_profile not in asserted.objects(scheme, ATLAS.resourceProfile):
            _fail("dataset.release", f"{release} profile differs from {scheme}")
        if release_ring not in asserted.objects(scheme, ATLAS.supportedRing):
            _fail("dataset.release", f"{release} ring is not supported by {scheme}")
        members = set(asserted.objects(release, PROV.hadMember))
        if not members:
            _fail("dataset.release", f"{release} has no prov:hadMember")
        for member in members:
            if member not in resources:
                _fail("dataset.release", f"{release} contains non-resource {member}")
            if release not in asserted.objects(member, ATLAS.inRelease):
                _fail("dataset.release", f"{member} lacks inverse inRelease for {release}")
    for resource in resources:
        release = _iri(_one(asserted, resource, ATLAS.inRelease, code="dataset.release"), code="dataset.release", label="inRelease")
        if release not in releases or (release, PROV.hadMember, resource) not in asserted:
            _fail("dataset.release", f"{resource} is not a closed member of {release}")
        resource_ring = _one(asserted, resource, ATLAS.semanticRing, code="dataset.release")
        release_ring = _one(asserted, release, ATLAS.semanticRing, code="dataset.release")
        if resource_ring != release_ring:
            _fail("dataset.release", f"{resource} ring differs from {release}")
        resource_scheme = _one(asserted, resource, ATLAS.inScheme, code="dataset.release")
        release_scheme = _one(asserted, release, ATLAS.inScheme, code="dataset.release")
        if resource_scheme != release_scheme:
            _fail("dataset.release", f"{resource} scheme differs from {release}")
        resource_profile = _one(asserted, resource, ATLAS.resourceProfile, code="dataset.release")
        release_profile = _one(asserted, release, ATLAS.resourceProfile, code="dataset.release")
        if resource_profile != release_profile:
            _fail("dataset.release", f"{resource} profile differs from {release}")


def _check_label_integrity(asserted: Graph) -> None:
    """Enforce cross-record SKOS-XL invariants without per-node SPARQL queries."""

    resources = {
        subject
        for resource_type in RESOURCE_TYPES
        for subject in asserted.subjects(RDF.type, resource_type)
        if isinstance(subject, URIRef)
    }
    role_predicates = tuple(XL_TO_SKOS)
    for resource in resources:
        release = _iri(
            _one(asserted, resource, ATLAS.inRelease, code="dataset.label-integrity"),
            code="dataset.label-integrity",
            label="resource release",
        )
        source_records = set(asserted.objects(resource, ATLAS.sourceRecord))
        labels_by_role: dict[URIRef, set[URIRef]] = {}
        literals_by_role: dict[URIRef, set[Literal]] = {}
        for role in role_predicates:
            labels: set[URIRef] = set()
            literals: set[Literal] = set()
            for raw_label in asserted.objects(resource, role):
                label = _iri(
                    raw_label,
                    code="dataset.label-integrity",
                    label="SKOS-XL label",
                )
                labels.add(label)
                if set(asserted.objects(label, ATLAS.inRelease)) != {release}:
                    _fail(
                        "dataset.label-integrity",
                        f"{label} release differs from its resource {resource}",
                    )
                label_records = set(asserted.objects(label, ATLAS.sourceRecord))
                if not source_records.intersection(label_records):
                    _fail(
                        "dataset.label-integrity",
                        f"{label} shares no SourceRecord with its resource {resource}",
                    )
                literal = _one(
                    asserted,
                    label,
                    SKOSXL.literalForm,
                    code="dataset.label-integrity",
                )
                if not isinstance(literal, Literal):
                    _fail("dataset.label-integrity", f"{label} literalForm is not a literal")
                literals.add(literal)
            labels_by_role[role] = labels
            literals_by_role[role] = literals

        preferred_languages = [
            (literal.language or "").lower()
            for literal in literals_by_role[SKOSXL.prefLabel]
        ]
        if len(preferred_languages) != len(set(preferred_languages)):
            _fail(
                "dataset.label-integrity",
                f"{resource} has more than one preferred label in a language",
            )
        for index, first_role in enumerate(role_predicates):
            for second_role in role_predicates[index + 1 :]:
                if labels_by_role[first_role] & labels_by_role[second_role] or (
                    literals_by_role[first_role] & literals_by_role[second_role]
                ):
                    _fail(
                        "dataset.label-integrity",
                        f"{resource} reuses a label node or literal across SKOS-XL roles",
                    )


def _check_node_digests(graphs: Mapping[str, Graph]) -> None:
    """Recompute the general RDF-node digest for every non-assertion carrier."""

    classes_by_role = {
        "asserted": {
            ATLAS.ResourceScheme,
            ATLAS.AtlasRelease,
            ATLAS.SourceRelease,
            ATLAS.AtlasResource,
            ATLAS.SubjectConcept,
            ATLAS.EntityResource,
            ATLAS.ValueResource,
            ATLAS.LegalIdentityResource,
            ATLAS.Identifier,
            ATLAS.SourceRecord,
            ATLAS.EvidenceBinding,
            ATLAS.EditorialPolicy,
            ATLAS.LifecycleEvent,
            SKOSXL.Label,
        },
        "projection": {ATLAS.ProjectedRelation},
        "derived": {ATLAS.DerivedRelation},
    }
    for role, classes in classes_by_role.items():
        graph = graphs[role]
        nodes = {
            node
            for class_iri in classes
            for node in graph.subjects(RDF.type, class_iri)
            if isinstance(node, URIRef)
        }
        for node in sorted(nodes, key=str):
            stored = _literal_text(
                _one(graph, node, ATLAS.contentDigest, code="dataset.node-identity"),
                code="dataset.node-identity",
                label="contentDigest",
            )
            expected = rdf_node_digest(graph, node)
            if stored != expected:
                _fail("dataset.node-identity", f"{node} contentDigest differs")


def _check_rdf_json_payload(
    literal: Any,
    *,
    node: URIRef,
    label: str,
    source_native: bool = False,
) -> None:
    if not isinstance(literal, Literal) or literal.datatype != RDF.JSON:
        _fail("dataset.native-payload", f"{node} {label} is not rdf:JSON")
    try:
        value = json.loads(
            str(literal),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_float,
            parse_int=_parse_int,
            parse_constant=_reject_constant,
        )
        expected = (
            canonical_native_json_bytes(value)
            if source_native
            else canonical_json_bytes(value, terminal_lf=False)
        )
    except (json.JSONDecodeError, AtlasValidationError) as exc:
        _fail("dataset.native-payload", f"{node} {label} is invalid: {exc}")
    if str(literal).encode("utf-8") != expected:
        _fail("dataset.native-payload", f"{node} {label} is not canonical REF JSON")


def _check_native_payloads(asserted: Graph) -> None:
    for record in set(asserted.subjects(RDF.type, ATLAS.SourceRecord)):
        literal = _one(asserted, record, ATLAS.nativePayload, code="dataset.native-payload")
        _check_rdf_json_payload(
            literal,
            node=record,
            label="nativePayload",
            source_native=True,
        )
    for scheme in set(asserted.subjects(RDF.type, ATLAS.ResourceScheme)):
        payloads = list(asserted.objects(scheme, ATLAS.descriptorPayload))
        if len(payloads) > 1:
            _fail("dataset.native-payload", f"{scheme} has more than one descriptorPayload")
        if payloads:
            _check_rdf_json_payload(payloads[0], node=scheme, label="descriptorPayload")
    for policy in set(asserted.subjects(RDF.type, ATLAS.EditorialPolicy)):
        literal = _one(asserted, policy, ATLAS.policyPayload, code="dataset.native-payload")
        _check_rdf_json_payload(literal, node=policy, label="policyPayload")
        expected_digest = rdf_node_digest(asserted, policy)
        expected_id = URIRef(
            "urn:ref:atlas-policy:" + expected_digest.removeprefix("sha256:")
        )
        if policy != expected_id:
            _fail("dataset.policy-identity", f"{policy} is not its content-derived IRI")


def _check_source_accounting(asserted: Graph, accounting: Mapping[str, Any]) -> None:
    graph_records = {str(subject) for subject in asserted.subjects(RDF.type, ATLAS.SourceRecord)}
    graph_releases = {str(subject) for subject in asserted.subjects(RDF.type, ATLAS.SourceRelease)}
    dispositions: dict[str, Mapping[str, Any]] = {}
    input_releases: set[str] = set()
    represented = excluded = unresolved = 0
    for source in accounting["inputs"]:
        source_release = source["sourceRelease"]
        if source_release in input_releases:
            _fail("source.accounting", f"duplicate source release input {source_release}")
        input_releases.add(source_release)
        if source_release not in graph_releases:
            _fail("source.accounting", f"unknown source release input {source_release}")
        for disposition in source["dispositions"]:
            record = disposition["sourceRecord"]
            if record in dispositions:
                _fail("source.accounting", f"duplicate disposition for {record}")
            dispositions[record] = disposition
            record_iri = URIRef(record)
            if (record_iri, RDF.type, ATLAS.SourceRecord) not in asserted:
                _fail("source.accounting", f"disposition names unknown source record {record}")
            if URIRef(source["sourceRelease"]) not in asserted.objects(record_iri, ATLAS.inSourceRelease):
                _fail("source.accounting", f"{record} is assigned to the wrong source release")
            status = disposition["status"]
            represented += status == "represented"
            excluded += status == "excluded"
            unresolved += status == "unresolved"
            ledger_resources = set(disposition["atlasResources"])
            graph_resources = {str(value) for value in asserted.objects(record_iri, ATLAS.representsResource)}
            inverse_resources = {
                str(resource)
                for resource in asserted.subjects(ATLAS.sourceRecord, record_iri)
                if any(
                    (resource, RDF.type, resource_type) in asserted
                    for resource_type in RESOURCE_TYPES
                )
            }
            if not (ledger_resources == graph_resources == inverse_resources):
                _fail(
                    "source.accounting",
                    f"{record} represented resources differ across its ledger and bidirectional RDF links",
                )
            if status != "represented" and graph_resources:
                _fail("source.accounting", f"{record} is {status} but links a represented resource")
            for resource in ledger_resources:
                if not any((URIRef(resource), RDF.type, resource_type) in asserted for resource_type in RESOURCE_TYPES):
                    _fail("source.accounting", f"{record} names unknown Atlas resource {resource}")
        if source["membershipMode"] in {"complete", "partial"} and len(source["dispositions"]) != source["declaredMemberCount"]:
            _fail("source.accounting", f"{source['sourceRelease']} declaredMemberCount differs")
    if set(dispositions) != graph_records:
        _fail(
            "source.accounting",
            f"source-record dispositions differ; missing={sorted(graph_records-set(dispositions))}, extra={sorted(set(dispositions)-graph_records)}",
        )
    if input_releases != graph_releases:
        _fail(
            "source.accounting",
            f"source releases differ; missing={sorted(graph_releases-input_releases)}, extra={sorted(input_releases-graph_releases)}",
        )
    for resource, _, record in asserted.triples((None, ATLAS.sourceRecord, None)):
        if any((resource, RDF.type, resource_type) in asserted for resource_type in RESOURCE_TYPES) and (
            record,
            ATLAS.representsResource,
            resource,
        ) not in asserted:
            _fail("source.accounting", f"{resource} sourceRecord link is not reconciled by {record}")
    expected_totals = {
        "sourceReleases": len(accounting["inputs"]),
        "sourceRecords": len(dispositions),
        "represented": represented,
        "excluded": excluded,
        "unresolved": unresolved,
    }
    if accounting["totals"] != expected_totals:
        _fail("source.accounting", "source-accounting totals do not reconcile")


def _check_counts(manifest: Mapping[str, Any], graphs: Mapping[str, Graph]) -> None:
    asserted = graphs["asserted"]
    expected = {
        "releases": len(set(asserted.subjects(RDF.type, ATLAS.AtlasRelease))),
        "resources": len(
            {
                subject
                for resource_type in RESOURCE_TYPES
                for subject in asserted.subjects(RDF.type, resource_type)
            }
        ),
        "labels": len(set(asserted.subjects(RDF.type, SKOSXL.Label))),
        "sourceRecords": len(set(asserted.subjects(RDF.type, ATLAS.SourceRecord))),
        "relationAssertions": sum(
            len(set(asserted.subjects(RDF.type, assertion_type))) for assertion_type in ASSERTION_TYPES
        ),
        "mappingAssertions": len(set(asserted.subjects(RDF.type, ATLAS.MappingAssertion))),
        "nativeRelationAssertions": len(set(asserted.subjects(RDF.type, ATLAS.NativeRelationAssertion))),
        "sourceAssignments": len(set(asserted.subjects(RDF.type, ATLAS.SourceAssignment))),
        "projectedRelations": len(set(graphs["projection"].subjects(RDF.type, ATLAS.ProjectedRelation))),
        "derivedRelations": len(set(graphs["derived"].subjects(RDF.type, ATLAS.DerivedRelation))),
    }
    if manifest["counts"] != expected:
        _fail("dataset.counts", f"manifest counts differ; expected={expected}, actual={manifest['counts']}")


def derived_input_digest(asserted: Graph, inputs: Iterable[URIRef]) -> str:
    rows = []
    for assertion in sorted(set(inputs), key=str):
        digest = _literal_text(
            _one(asserted, assertion, ATLAS.contentDigest, code="dataset.derived-input"),
            code="dataset.derived-input",
            label="input assertion contentDigest",
        )
        rows.append({"assertion": str(assertion), "contentDigest": digest})
    return canonical_sha256({"assertions": rows}, terminal_lf=False)


def _check_derived(
    asserted: Graph,
    projection: Graph,
    derived: Graph,
    current: Mapping[tuple[URIRef, URIRef, URIRef], frozenset[URIRef]],
) -> None:
    relation_policies = _relation_policies()
    active_assertions = {
        assertion
        for assertions in current.values()
        for assertion in assertions
    }
    derived_nodes = set(derived.subjects(RDF.type, ATLAS.DerivedRelation))
    for node in derived_nodes:
        if (node, RDF.type, ATLAS.RelationAssertion) in derived or any(
            (node, RDF.type, assertion_type) in derived for assertion_type in ASSERTION_TYPES
        ):
            _fail("dataset.derived-authority", f"{node} is both derived and authoritative")
        if _one(derived, node, ATLAS.authorityStatus, code="dataset.derived") != ATLAS.nonAuthoritative:
            _fail("dataset.derived-authority", f"{node} is not explicitly non-authoritative")
        inputs = set(derived.objects(node, ATLAS.derivedFromAssertion))
        if not inputs or not inputs <= active_assertions:
            _fail(
                "dataset.derived",
                f"{node} has missing, unknown, withdrawn, or superseded input assertions",
            )
        stored_input_digest = _literal_text(
            _one(derived, node, ATLAS.inputDigest, code="dataset.derived-input"),
            code="dataset.derived-input",
            label="inputDigest",
        )
        expected_input_digest = derived_input_digest(asserted, inputs)
        if stored_input_digest != expected_input_digest:
            _fail("dataset.derived-input", f"{node} inputDigest differs from its assertion inputs")
        subject = _iri(_one(derived, node, ATLAS.relationSubject, code="dataset.derived"), code="dataset.derived", label="derived subject")
        predicate = _iri(_one(derived, node, ATLAS.relationPredicate, code="dataset.derived"), code="dataset.derived", label="derived predicate")
        obj = _iri(_one(derived, node, ATLAS.relationObject, code="dataset.derived"), code="dataset.derived", label="derived object")
        ring = _iri(
            _one(derived, node, ATLAS.semanticRing, code="dataset.derived"),
            code="dataset.derived",
            label="derived ring",
        )
        if not any((subject, RDF.type, resource_type) in asserted for resource_type in RESOURCE_TYPES):
            _fail("dataset.derived", f"{node} subject is not an asserted Atlas resource")
        if not any((obj, RDF.type, resource_type) in asserted for resource_type in RESOURCE_TYPES):
            _fail("dataset.derived", f"{node} object is not an asserted Atlas resource")
        if ring not in asserted.objects(subject, ATLAS.semanticRing) or ring not in asserted.objects(obj, ATLAS.semanticRing):
            _fail("dataset.derived", f"{node} endpoint ring differs")
        allowed = (
            relation_policies.get(ring, {}).get(ATLAS.MappingAssertion, frozenset())
            | relation_policies.get(ring, {}).get(ATLAS.NativeRelationAssertion, frozenset())
        )
        if predicate not in allowed:
            _fail("dataset.derived", f"{node} predicate is not allowed for its ring")

        rule = _iri(
            _one(derived, node, ATLAS.derivationRule, code="dataset.derived-rule"),
            code="dataset.derived-rule",
            label="derivation rule",
        )
        engine = _iri(
            _one(derived, node, ATLAS.engine, code="dataset.derived-rule"),
            code="dataset.derived-rule",
            label="derivation engine",
        )
        engine_version = _literal_text(
            _one(derived, node, ATLAS.engineVersion, code="dataset.derived-rule"),
            code="dataset.derived-rule",
            label="engineVersion",
        )
        if (rule, engine, engine_version) != (
            EXACT_MATCH_TRANSITIVITY_RULE,
            DERIVATION_ENGINE,
            DERIVATION_ENGINE_VERSION,
        ):
            _fail("dataset.derived-rule", f"{node} uses an unallowlisted rule or engine")
        if (
            ring != ATLAS.subject
            or predicate != SKOS.exactMatch
            or subject == obj
            or len(inputs) < 2
        ):
            _fail("dataset.derived-rule", f"{node} does not match the exactMatch transitivity rule")
        adjacency: dict[URIRef, set[URIRef]] = defaultdict(set)
        edges: set[frozenset[URIRef]] = set()
        for assertion in inputs:
            assertion_type = _assertion_type(asserted, assertion)
            _, triple = _assertion_basis(asserted, assertion)
            if assertion_type != ATLAS.MappingAssertion or triple[1] != SKOS.exactMatch:
                _fail("dataset.derived-rule", f"{node} cites a non-exactMatch input")
            if triple[0] == triple[2]:
                _fail("dataset.derived-rule", f"{node} cites a reflexive exactMatch input")
            edge = frozenset((triple[0], triple[2]))
            if edge in edges:
                _fail("dataset.derived-rule", f"{node} cites a duplicate exactMatch edge")
            edges.add(edge)
            adjacency[triple[0]].add(triple[2])
            adjacency[triple[2]].add(triple[0])
        frontier = [subject]
        visited = {subject}
        while frontier:
            current = frontier.pop()
            for target in adjacency[current] - visited:
                visited.add(target)
                frontier.append(target)
        graph_nodes = set(adjacency)
        if (
            obj not in visited
            or visited != graph_nodes
            or len(edges) != len(graph_nodes) - 1
            or adjacency[subject] == set()
            or len(adjacency[subject]) != 1
            or len(adjacency[obj]) != 1
            or any(
                len(adjacency[path_node]) != 2
                for path_node in graph_nodes - {subject, obj}
            )
        ):
            _fail(
                "dataset.derived-rule",
                f"{node} inputs are not one exact simple path between its endpoints",
            )

        stored_node_digest = _literal_text(
            _one(derived, node, ATLAS.contentDigest, code="dataset.derived-identity"),
            code="dataset.derived-identity",
            label="contentDigest",
        )
        expected_id = URIRef("urn:ref:atlas-derived:" + stored_node_digest.removeprefix("sha256:"))
        if node != expected_id:
            _fail("dataset.derived-identity", f"{node} is not its content-derived IRI")
        if (subject, predicate, obj) in projection or (
            predicate == SKOS.exactMatch
            and (obj, predicate, subject) in projection
        ):
            _fail(
                "dataset.derived-authority",
                f"{node} duplicates a directly asserted projection relation",
            )


def _check_reasoning_isolation(
    derived: Graph,
    current: Mapping[tuple[URIRef, URIRef, URIRef], frozenset[URIRef]],
    exact_index: ExactMatchIndex | None = None,
) -> int:
    exact_index = exact_index or _build_exact_match_index(current)
    direct_mappings = {
        triple
        for triple in current
        if triple[1] in SKOS_MAPPING_PREDICATES
    }
    assertion_triples = {
        assertion: triple
        for triple, assertions in current.items()
        for assertion in assertions
    }
    for node in sorted(set(derived.subjects(RDF.type, ATLAS.DerivedRelation)), key=str):
        output = (
            _iri(
                _one(derived, node, ATLAS.relationSubject, code="reasoning.authority"),
                code="reasoning.authority",
                label="derived subject",
            ),
            _iri(
                _one(derived, node, ATLAS.relationPredicate, code="reasoning.authority"),
                code="reasoning.authority",
                label="derived predicate",
            ),
            _iri(
                _one(derived, node, ATLAS.relationObject, code="reasoning.authority"),
                code="reasoning.authority",
                label="derived object",
            ),
        )
        replay = Graph()
        for assertion in derived.objects(node, ATLAS.derivedFromAssertion):
            input_triple = assertion_triples.get(assertion)
            if input_triple is not None:
                replay.add(input_triple)
        replay.add((SKOS.exactMatch, RDF.type, OWL.TransitiveProperty))
        replay.add((SKOS.exactMatch, RDF.type, OWL.SymmetricProperty))
        DeductiveClosure(
            OWLRL_Semantics,
            axiomatic_triples=False,
            datatype_axioms=False,
        ).expand(replay)
        if output in direct_mappings or output not in replay:
            _fail(
                "reasoning.authority",
                f"{node} is not a newly inferred mapping under the pinned reasoner",
            )
    return exact_index.inferred_count


def acceptance_gate_evidence_digest(
    name: str,
    *,
    inputs: Mapping[str, Any],
    validator: Mapping[str, Any],
) -> str:
    """Bind one passed gate receipt to the validator and exact evaluated inputs."""

    return canonical_sha256(
        {
            "inputs": dict(inputs),
            "name": name,
            "status": "passed",
            "validator": dict(validator),
        },
        terminal_lf=False,
    )


def _check_acceptance(manifest: Mapping[str, Any], accounting: Mapping[str, Any], acceptance: Mapping[str, Any], root: Path) -> None:
    if acceptance["distributionId"] != manifest["distributionId"] or accounting["distributionId"] != manifest["distributionId"]:
        _fail("distribution.identity", "distributionId differs across JSON artifacts")
    if acceptance["inputs"]["atlasDigest"] != file_sha256(root / "atlas.nq"):
        _fail("acceptance.inputs", "acceptance atlasDigest differs")
    if acceptance["inputs"]["sourceAccountingDigest"] != file_sha256(root / "atlas-source-accounting.json"):
        _fail("acceptance.inputs", "acceptance sourceAccountingDigest differs")
    names = [gate["name"] for gate in acceptance["gates"]]
    if len(names) != len(set(names)) or set(names) != REQUIRED_GATES:
        _fail(
            "acceptance.gates",
            f"acceptance gates differ; missing={sorted(REQUIRED_GATES-set(names))}, extra={sorted(set(names)-REQUIRED_GATES)}",
        )
    for gate in acceptance["gates"]:
        expected_digest = acceptance_gate_evidence_digest(
            gate["name"],
            inputs=acceptance["inputs"],
            validator=acceptance["validator"],
        )
        if gate["evidenceDigest"] != expected_digest:
            _fail("acceptance.evidence", f"gate {gate['name']} evidenceDigest differs")


def validate_distribution(root: Path) -> dict[str, Any]:
    """Validate one closed Atlas 3.0 distribution and return proof counts."""

    schemas, registry = _schema_registry()
    manifest_path = root / "atlas-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        _fail("distribution.file", "atlas-manifest.json is missing or unsafe")
    manifest = _load_json(manifest_path, require_canonical=True)
    _validate_json_schema(manifest, "manifest", schemas=schemas, registry=registry, label="manifest")
    _check_manifest_digest(manifest)
    _check_distribution_files(root, manifest)

    accounting = _load_json(root / "atlas-source-accounting.json", require_canonical=True)
    acceptance = _load_json(root / "atlas-acceptance.json", require_canonical=True)
    _validate_json_schema(accounting, "sourceAccounting", schemas=schemas, registry=registry, label="source accounting")
    _validate_json_schema(acceptance, "acceptance", schemas=schemas, registry=registry, label="acceptance")
    _check_binding_pins(manifest, acceptance)

    dataset, graphs = _parse_dataset(root / "atlas.nq", manifest)
    ontology, shapes = _parse_binding_graphs()
    _lint_ontology(ontology)
    _run_shacl(graphs, ontology, shapes)
    _check_graph_roles(graphs)
    _check_profile_conformance(graphs["asserted"])
    _check_release_membership(graphs["asserted"])
    _check_label_integrity(graphs["asserted"])
    _check_evidence_bindings(graphs["asserted"])
    current_assertions = _validate_assertions(graphs["asserted"])
    exact_index = _build_exact_match_index(current_assertions)
    _check_skos_integrity(current_assertions, exact_index)
    _check_projection(graphs["asserted"], graphs["projection"], current_assertions)
    _check_derived(
        graphs["asserted"],
        graphs["projection"],
        graphs["derived"],
        current_assertions,
    )
    _check_native_payloads(graphs["asserted"])
    _check_node_digests(graphs)
    _check_source_accounting(graphs["asserted"], accounting)
    _check_counts(manifest, graphs)
    inferred_mapping_count = _check_reasoning_isolation(
        graphs["derived"], current_assertions, exact_index
    )
    _check_acceptance(manifest, accounting, acceptance, root)
    # Keep the shared Dataset store alive for every graph view through the last check.
    del dataset
    return {
        "counts": manifest["counts"],
        "distributionId": manifest["distributionId"],
        "inferredMappingCount": inferred_mapping_count,
        "quadCount": sum(row["quadCount"] for row in manifest["graphs"]),
    }


def _check_registry_descriptors(
    profile_map: Mapping[str, Any],
    coverage: Mapping[str, Any],
    *,
    schemas: Mapping[str, Mapping[str, Any]],
    registry: Registry,
) -> dict[str, int]:
    """Verify the checked RDF export of every real registry descriptor."""

    for path in (REGISTRY_DESCRIPTOR_PROOF_PATH, REGISTRY_DESCRIPTOR_DATASET_PATH):
        if not path.is_file() or path.is_symlink():
            _fail("registry.descriptors", f"registry descriptor artifact is missing or unsafe: {path.name}")
    proof = _load_json(REGISTRY_DESCRIPTOR_PROOF_PATH, require_canonical=True)
    _validate_json_schema(
        proof,
        "registryDescriptors",
        schemas=schemas,
        registry=registry,
        label="registry descriptor proof",
    )
    expected_proof_keys = {
        "artifact",
        "counts",
        "format",
        "graphIri",
        "inputs",
        "proofDigest",
        "resourceIdSetDigest",
        "schemaVersion",
    }
    if not isinstance(proof, Mapping) or set(proof) != expected_proof_keys:
        _fail("registry.descriptors", "registry descriptor proof fields are incomplete or unknown")
    if (
        proof.get("format") != "refspec-atlas-registry-descriptors/3.0"
        or proof.get("schemaVersion") != "3.0"
    ):
        _fail("registry.descriptors", "registry descriptor proof is not Atlas 3.0")
    expected_proof_digest = canonical_sha256(
        {key: value for key, value in proof.items() if key != "proofDigest"},
        terminal_lf=False,
    )
    if proof.get("proofDigest") != expected_proof_digest:
        _fail("registry.descriptors", "registry descriptor proofDigest differs")
    proof_inputs = proof.get("inputs")
    if not isinstance(proof_inputs, Mapping) or set(proof_inputs) != {
        "atlasIndexDigest",
        "registryResourceProfilesDigest",
        "resourceCatalogDigest",
    }:
        _fail("registry.descriptors", "registry descriptor input receipt is malformed")
    if proof_inputs != coverage.get("inputs"):
        _fail("registry.descriptors", "registry descriptor and coverage inputs differ")
    if proof_inputs.get("registryResourceProfilesDigest") != profile_map.get("profileDigest"):
        _fail("registry.descriptors", "registry descriptor proof does not pin the profile policy")

    artifact = proof.get("artifact")
    if not isinstance(artifact, Mapping) or set(artifact) != {"byteLength", "path", "sha256"}:
        _fail("registry.descriptors", "registry descriptor artifact receipt is malformed")
    if artifact.get("path") != REGISTRY_DESCRIPTOR_DATASET_PATH.name:
        _fail("registry.descriptors", "registry descriptor artifact path differs")
    raw = REGISTRY_DESCRIPTOR_DATASET_PATH.read_bytes()
    if artifact.get("byteLength") != len(raw) or artifact.get("sha256") != file_sha256(
        REGISTRY_DESCRIPTOR_DATASET_PATH
    ):
        _fail("registry.descriptors", "registry descriptor artifact receipt differs")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        _fail("registry.descriptors", f"registry descriptor N-Quads are not UTF-8: {exc}")
    if not text or not text.endswith("\n") or "\r" in text:
        _fail("registry.descriptors", "registry descriptor N-Quads must be LF text")
    lines = text.splitlines()
    if lines != sorted(lines) or len(lines) != len(set(lines)) or any(
        not line or line != line.strip() for line in lines
    ):
        _fail("registry.descriptors", "registry descriptor N-Quads are not sorted and unique")
    dataset = Dataset()
    try:
        _parse_nquads_preserving_lexical_forms(dataset, REGISTRY_DESCRIPTOR_DATASET_PATH)
    except Exception as exc:  # noqa: BLE001 - normalize RDF parser failures
        _fail("registry.descriptors", f"registry descriptor N-Quads cannot be parsed: {exc}")
    canonical_lines = _canonical_dataset_lines(
        dataset,
        blank_node_code="registry.descriptors",
        blank_node_detail="registry descriptor N-Quads contain a blank node term",
    )
    if canonical_lines != lines:
        _fail("registry.descriptors", "registry descriptor N-Quads are not canonical")
    graph_iri = proof.get("graphIri")
    if not isinstance(graph_iri, str) or not ABSOLUTE_IRI_RE.fullmatch(graph_iri):
        _fail("registry.descriptors", "registry descriptor graphIri is not an absolute IRI")
    graph_id = URIRef(graph_iri)
    graph_ids = {
        quad_graph
        for _, _, _, quad_graph in dataset.quads((None, None, None, None))
    }
    if graph_ids != {graph_id}:
        _fail("registry.descriptors", "registry descriptor statements use unexpected graph IRIs")
    graph = Graph(identifier=graph_id)
    for subject, predicate, obj, _ in dataset.quads((None, None, None, graph_id)):
        graph.add((subject, predicate, obj))

    counts = proof.get("counts")
    expected_count_keys = {
        "atlasIndexPlacementCount",
        "conceptSchemeCount",
        "quadCount",
        "resourceSchemeCount",
        "supportedRingStatementCount",
    }
    if (
        not isinstance(counts, Mapping)
        or set(counts) != expected_count_keys
        or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in counts.values())
    ):
        _fail("registry.descriptors", "registry descriptor counts are missing or vacuous")
    if counts["atlasIndexPlacementCount"] != coverage["summary"]["atlasIndexRowCount"]:
        _fail("registry.descriptors", "registry descriptor index count does not reconcile")
    if counts["resourceSchemeCount"] != coverage["summary"]["catalogResourceCount"]:
        _fail("registry.descriptors", "registry descriptor scheme count does not reconcile")

    schemes = set(graph.subjects(RDF.type, ATLAS.ResourceScheme))
    if set(graph.subjects()) != schemes:
        _fail("registry.descriptors", "registry descriptor graph has a non-ResourceScheme subject")
    policies = _profile_policies()
    resource_ids: list[str] = []
    concept_scheme_count = 0
    for scheme in sorted(schemes, key=str):
        if not isinstance(scheme, URIRef):
            _fail("registry.descriptors", "registry descriptor scheme identity is not an IRI")
        profile = _iri(
            _one(graph, scheme, ATLAS.resourceProfile, code="registry.descriptors"),
            code="registry.descriptors",
            label="registry descriptor profile",
        )
        policy = policies.get(profile)
        if policy is None:
            _fail("registry.descriptors", f"registry descriptor uses unknown profile {profile}")
        allowed_rings = {URIRef(str(ATLAS) + value) for value in policy["applicableSemanticRings"]}
        supported_rings = set(graph.objects(scheme, ATLAS.supportedRing))
        if supported_rings - allowed_rings:
            _fail("registry.descriptors", f"registry descriptor {scheme} has an unsupported ring")
        is_concept_scheme = (scheme, RDF.type, SKOS.ConceptScheme) in graph
        if is_concept_scheme != (profile == ATLAS.conceptScheme):
            _fail("registry.descriptors", f"registry descriptor {scheme} has inconsistent SKOS typing")
        concept_scheme_count += int(is_concept_scheme)

        identifier = _literal_text(
            _one(graph, scheme, DCTERMS.identifier, code="registry.descriptors"),
            code="registry.descriptors",
            label="registry descriptor identifier",
        )
        title = _literal_text(
            _one(graph, scheme, DCTERMS.title, code="registry.descriptors"),
            code="registry.descriptors",
            label="registry descriptor title",
        )
        payload_literal = _one(graph, scheme, ATLAS.descriptorPayload, code="registry.descriptors")
        if not isinstance(payload_literal, Literal) or payload_literal.datatype != RDF.JSON:
            _fail("registry.descriptors", f"registry descriptor {scheme} payload is not rdf:JSON")
        try:
            payload = json.loads(
                str(payload_literal),
                object_pairs_hook=_reject_duplicate_keys,
                parse_float=_reject_float,
                parse_constant=_reject_constant,
                parse_int=_parse_int,
            )
        except (AtlasValidationError, json.JSONDecodeError) as exc:
            _fail("registry.descriptors", f"registry descriptor {scheme} payload is invalid: {exc}")
        if (
            not isinstance(payload, Mapping)
            or canonical_json_bytes(payload, terminal_lf=False).decode("utf-8") != str(payload_literal)
            or payload.get("resourceId") != identifier
            or payload.get("title") != title
        ):
            _fail("registry.descriptors", f"registry descriptor {scheme} payload is not a lossless canonical row")
        stored_digest = _literal_text(
            _one(graph, scheme, ATLAS.contentDigest, code="registry.descriptors"),
            code="registry.descriptors",
            label="registry descriptor contentDigest",
        )
        if stored_digest != rdf_node_digest(graph, scheme):
            _fail("registry.descriptors", f"registry descriptor {scheme} contentDigest differs")
        resource_ids.append(identifier)

    actual_counts = {
        "conceptSchemeCount": concept_scheme_count,
        "quadCount": len(graph),
        "resourceSchemeCount": len(schemes),
        "supportedRingStatementCount": len(list(graph.triples((None, ATLAS.supportedRing, None)))),
    }
    for name, value in actual_counts.items():
        if counts[name] != value:
            _fail("registry.descriptors", f"registry descriptor {name} differs")
    if len(resource_ids) != len(set(resource_ids)) or proof.get("resourceIdSetDigest") != canonical_sha256(
        sorted(resource_ids), terminal_lf=False
    ):
        _fail("registry.descriptors", "registry descriptor resource identity set differs")
    return {name: int(value) for name, value in counts.items()}


def validate_binding() -> dict[str, Any]:
    """Validate schemas, ontology, shapes, registry proof, and corpus."""

    schemas, registry = _schema_registry()
    ontology, shapes = _parse_binding_graphs()
    _lint_ontology(ontology)

    # Meta-SHACL runs before any fixture can claim data conformance.
    empty = {role: Graph() for role in ("asserted", "projection", "derived")}
    try:
        meta_conforms, _, meta_report = shacl_validate(
            empty["asserted"],
            shacl_graph=shapes,
            ont_graph=ontology,
            inference="none",
            advanced=False,
            meta_shacl=True,
        )
    except Exception as exc:  # noqa: BLE001 - normalize SHACL processor failures
        _fail("shacl.meta", f"shape graph is not well formed: {exc}")
    if not meta_conforms:
        compact = " ".join(str(meta_report).split())
        _fail("shacl.meta", f"shape graph does not conform to SHACL-SHACL: {compact[:900]}")

    corpus = _load_json(CORPUS_PATH, require_canonical=True)
    _validate_json_schema(corpus, "corpus", schemas=schemas, registry=registry, label="corpus")
    case_ids = {case["id"] for case in corpus["cases"]}
    if case_ids != REQUIRED_CORPUS_CASES:
        _fail(
            "corpus.coverage",
            f"corpus cases differ; missing={sorted(REQUIRED_CORPUS_CASES-case_ids)}, extra={sorted(case_ids-REQUIRED_CORPUS_CASES)}",
        )
    declared_paths = {case["path"] for case in corpus["cases"]}
    fixture_paths = {
        f"{role}/{path.name}"
        for role in ("valid", "invalid")
        for path in (FIXTURE_ROOT / role).iterdir()
        if path.is_dir() and not path.is_symlink()
    }
    if declared_paths != fixture_paths:
        _fail(
            "corpus.coverage",
            f"corpus paths differ from fixture directories; missing={sorted(fixture_paths-declared_paths)}, extra={sorted(declared_paths-fixture_paths)}",
        )
    results: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for case in corpus["cases"]:
        relative = case["path"]
        if relative in seen_paths or relative.startswith("/") or ".." in Path(relative).parts:
            _fail("corpus.path", f"unsafe or duplicate corpus path {relative!r}")
        seen_paths.add(relative)
        case_path = (FIXTURE_ROOT / relative).resolve()
        try:
            case_path.relative_to(FIXTURE_ROOT.resolve())
        except ValueError:
            _fail("corpus.path", f"case escapes fixture root: {relative}")
        try:
            validate_distribution(case_path)
        except AtlasValidationError as exc:
            if case["expected"] == "valid":
                _fail("corpus.verdict", f"valid case {case['id']} failed with {exc}")
            expected_issue = case["firstIssue"]
            if exc.code != expected_issue:
                _fail(
                    "corpus.first-issue",
                    f"case {case['id']} expected {expected_issue}, observed {exc.code}: {exc.detail}",
                )
            results.append({"id": case["id"], "result": "rejected", "issue": exc.code})
        else:
            if case["expected"] == "invalid":
                _fail("corpus.verdict", f"invalid case {case['id']} passed")
            results.append({"id": case["id"], "result": "accepted"})

    if not PROFILE_MAP_PATH.is_file() or not REGISTRY_COVERAGE_PATH.is_file():
        _fail("registry.coverage", "registry profile map or coverage report is missing")
    profile_map = _load_json(PROFILE_MAP_PATH, require_canonical=True)
    coverage = _load_json(REGISTRY_COVERAGE_PATH, require_canonical=True)
    _validate_json_schema(
        profile_map,
        "registryProfiles",
        schemas=schemas,
        registry=registry,
        label="registry profile policy",
    )
    _validate_json_schema(
        coverage,
        "registryCoverage",
        schemas=schemas,
        registry=registry,
        label="registry coverage proof",
    )
    policies = _profile_policies()
    expected_coverage_keys = {
        "coverageDigest",
        "format",
        "inputs",
        "profiles",
        "schemaVersion",
        "setDigests",
        "summary",
        "unsupported",
    }
    if set(coverage) != expected_coverage_keys:
        _fail("registry.coverage", "registry coverage fields are incomplete or unknown")
    if profile_map.get("schemaVersion") != "3.0" or coverage.get("schemaVersion") != "3.0":
        _fail("registry.coverage", "registry proof uses another Atlas version")
    if coverage.get("format") != "refspec-atlas-registry-coverage/3.0":
        _fail("registry.coverage", "registry coverage format is not Atlas 3.0")
    claimed_coverage_digest = coverage["coverageDigest"]
    expected_coverage_digest = canonical_sha256(
        {key: value for key, value in coverage.items() if key != "coverageDigest"},
        terminal_lf=False,
    )
    if claimed_coverage_digest != expected_coverage_digest:
        _fail("registry.coverage", "coverageDigest does not match the canonical report")
    inputs = coverage.get("inputs")
    if not isinstance(inputs, Mapping) or set(inputs) != {
        "atlasIndexDigest",
        "registryResourceProfilesDigest",
        "resourceCatalogDigest",
    }:
        _fail("registry.coverage", "registry report input receipt is malformed")
    set_digests = coverage.get("setDigests")
    if not isinstance(set_digests, Mapping) or set(set_digests) != {
        "catalogOnlyDescriptorIds",
        "catalogResourceIds",
        "implementationModules",
        "indexedPlacementIdentities",
        "indexedResourceIds",
        "indexedSemanticRings",
        "indexedWithoutExactReleaseIds",
        "registryModules",
        "releaseReadyIndexedResourceIds",
        "sourceModules",
    }:
        _fail("registry.coverage", "registry report set-digest receipt is malformed")
    if inputs.get("registryResourceProfilesDigest") != profile_map["profileDigest"]:
        _fail("registry.coverage", "registry report does not pin the profile policy")
    for digest in [*inputs.values(), *set_digests.values()]:
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            _fail("registry.coverage", "registry report contains a malformed digest")
    if coverage.get("unsupported") != {"modules": [], "resourceKinds": [], "resources": []}:
        _fail("registry.coverage", "registry coverage report contains unsupported items")
    expected_profiles = {str(profile).removeprefix(str(ATLAS)) for profile in policies}
    profile_rows = coverage.get("profiles")
    if not isinstance(profile_rows, Mapping) or set(profile_rows) != expected_profiles:
        _fail("registry.coverage", "registry report profile rows differ from profile policy")
    summary = coverage.get("summary")
    expected_summary_keys = {
        "atlasIndexRowCount",
        "catalogOnlyDescriptorCount",
        "catalogResourceCount",
        "implementationModuleCount",
        "indexedResourceCount",
        "indexedWithoutExactReleaseCount",
        "registryModuleCount",
        "releaseReadyIndexedResourceCount",
        "resourceKindCounts",
        "sourceModuleCount",
    }
    if not isinstance(summary, Mapping) or set(summary) != expected_summary_keys:
        _fail("registry.coverage", "registry report summary fields are incomplete or unknown")
    integer_summary = {name: value for name, value in summary.items() if name != "resourceKindCounts"}
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in integer_summary.values()
    ):
        _fail("registry.coverage", "registry report summary counts must be non-negative integers")
    resource_kind_counts = summary.get("resourceKindCounts")
    if (
        not isinstance(resource_kind_counts, Mapping)
        or not resource_kind_counts
        or any(
            not isinstance(name, str)
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
            for name, value in resource_kind_counts.items()
        )
    ):
        _fail("registry.coverage", "registry resource-kind counts are malformed or vacuous")
    expected_profile_row_keys = {
        "catalogOnlyDescriptorCount",
        "catalogResourceCount",
        "indexedResourceCount",
        "indexedRowCount",
        "indexedWithoutExactReleaseCount",
        "releaseReadyIndexedResourceCount",
        "semanticRingCounts",
    }
    for profile_name, row in profile_rows.items():
        if not isinstance(row, Mapping) or set(row) != expected_profile_row_keys:
            _fail("registry.coverage", f"registry profile row {profile_name} is malformed")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for name, value in row.items()
            if name != "semanticRingCounts"
        ):
            _fail("registry.coverage", f"registry profile row {profile_name} has invalid counts")
        ring_counts = row.get("semanticRingCounts")
        if not isinstance(ring_counts, Mapping) or any(
            URIRef(str(ATLAS) + ring) not in RING_RESOURCE_CLASSES
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
            for ring, value in ring_counts.items()
        ):
            _fail("registry.coverage", f"registry profile row {profile_name} has invalid ring counts")
        if row["catalogResourceCount"] != row["indexedResourceCount"] + row["catalogOnlyDescriptorCount"]:
            _fail("registry.coverage", f"registry profile row {profile_name} resource counts do not reconcile")
        if row["indexedResourceCount"] != (
            row["releaseReadyIndexedResourceCount"] + row["indexedWithoutExactReleaseCount"]
        ):
            _fail("registry.coverage", f"registry profile row {profile_name} release counts do not reconcile")
        if sum(ring_counts.values()) != row["indexedRowCount"]:
            _fail("registry.coverage", f"registry profile row {profile_name} ring counts do not reconcile")
    required_positive_counts = {
        "atlasIndexRowCount",
        "catalogResourceCount",
        "indexedResourceCount",
        "registryModuleCount",
        "sourceModuleCount",
    }
    if any(not isinstance(summary.get(name), int) or summary[name] <= 0 for name in required_positive_counts):
        _fail("registry.coverage", "registry report has missing or vacuous summary counts")
    if summary["registryModuleCount"] != summary["sourceModuleCount"] + summary["implementationModuleCount"]:
        _fail("registry.coverage", "registry module counts do not reconcile")
    if summary["catalogResourceCount"] != summary["indexedResourceCount"] + summary["catalogOnlyDescriptorCount"]:
        _fail("registry.coverage", "catalog resource counts do not reconcile")
    if summary["indexedResourceCount"] != (
        summary["releaseReadyIndexedResourceCount"] + summary["indexedWithoutExactReleaseCount"]
    ):
        _fail("registry.coverage", "indexed resource counts do not reconcile")
    if sum(resource_kind_counts.values()) != summary["catalogResourceCount"]:
        _fail("registry.coverage", "registry resource-kind counts do not reconcile")
    if sum(row["catalogResourceCount"] for row in profile_rows.values()) != summary["catalogResourceCount"]:
        _fail("registry.coverage", "profile resource counts do not reconcile")
    if sum(row["indexedRowCount"] for row in profile_rows.values()) != summary["atlasIndexRowCount"]:
        _fail("registry.coverage", "profile index counts do not reconcile")
    descriptor_counts = _check_registry_descriptors(
        profile_map,
        coverage,
        schemas=schemas,
        registry=registry,
    )
    return {
        "caseCount": len(results),
        "invalidCount": sum(row["result"] == "rejected" for row in results),
        "registryDescriptorCount": descriptor_counts["resourceSchemeCount"],
        "registryDescriptorQuadCount": descriptor_counts["quadCount"],
        "schemaCount": len(schemas),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--distribution",
        type=Path,
        help="validate one distribution instead of the complete binding corpus",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        result = validate_distribution(args.distribution) if args.distribution else validate_binding()
    except AtlasValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
