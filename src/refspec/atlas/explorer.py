"""Open and render sealed RefSpec Atlas 3.0 distributions."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import stat
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, BinaryIO, TypeVar, cast

from rdflib import BNode, Dataset, Graph, Literal, Namespace, URIRef
from rdflib.exceptions import ParserError
from rdflib.namespace import DCTERMS, PROV, RDF, SKOS

from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)

ATLAS_V3_EXPLORER_TYPE = "urn:ref:type:Atlas3ExplorerView"
ATLAS_V3_EXPLORER_SCHEMA_VERSION = "3.0"

# These familiar names now identify Atlas 3.0. They are aliases, not a legacy
# Atlas 2 reader or wire-format compatibility layer.
EXPLORER_TYPE = ATLAS_V3_EXPLORER_TYPE
EXPLORER_SCHEMA_VERSION = ATLAS_V3_EXPLORER_SCHEMA_VERSION

ATLAS = Namespace("https://refspec.org/ns/atlas/v3#")
SKOSXL = Namespace("http://www.w3.org/2008/05/skos-xl#")

EXPECTED_FILES = frozenset(
    {
        "atlas-manifest.json",
        "atlas.nq",
        "atlas-source-accounting.json",
        "atlas-acceptance.json",
    }
)
REQUIRED_ACCEPTANCE_GATES = frozenset(
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
RESOURCE_TYPES = frozenset(
    {
        ATLAS.SubjectConcept,
        ATLAS.EntityResource,
        ATLAS.ValueResource,
        ATLAS.LegalIdentityResource,
    }
)
RELATION_TYPES = (
    (ATLAS.MappingAssertion, "mapping"),
    (ATLAS.NativeRelationAssertion, "native"),
    (ATLAS.SourceAssignment, "sourceAssignment"),
)
LABEL_ROLES = (
    (SKOSXL.prefLabel, "preferred"),
    (SKOSXL.altLabel, "alternate"),
    (SKOSXL.hiddenLabel, "hidden"),
)
PREDICATE_MEANINGS = {
    str(SKOS.broader): "The subject is narrower than the object in the publisher's hierarchy.",
    str(SKOS.narrower): "The subject is broader than the object in the publisher's hierarchy.",
    str(SKOS.related): "The publisher asserted a direct associative SKOS relationship.",
    str(SKOS.exactMatch): "The concepts have an exact match across two exact releases.",
    str(SKOS.closeMatch): "The concepts are similar enough for some cross-vocabulary retrieval uses.",
    str(SKOS.broadMatch): "The subject maps to a broader concept in another exact release.",
    str(SKOS.narrowMatch): "The subject maps to a narrower concept in another exact release.",
    str(SKOS.relatedMatch): "The subject maps associatively to a concept in another exact release.",
    str(ATLAS.thesaurusUse): (
        "Use the object as the publisher's preferred term for the non-preferred subject term."
    ),
    str(ATLAS.thesaurusUsedFor): (
        "The preferred subject term is used for the non-preferred object term."
    ),
    str(ATLAS.thesaurusRelated): (
        "The publisher asserted this direct associative link. Atlas preserves it outside skos:related "
        "when a hierarchy path makes that SKOS projection unsafe; the link remains directly relevant."
    ),
}

# Atlas 3 filtering starts from authority role. The reader does not consume the
# Atlas 2 planning-index facets that the retired explorer used.
EXPLORER_FILTER_SEMANTICS: tuple[Mapping[str, object], ...] = (
    {
        "recordKind": "resource",
        "authorityRole": "asserted",
        "filterFields": ("semanticRing", "resourceProfile", "labels"),
    },
    {
        "recordKind": "assertedRelation",
        "authorityRole": "asserted",
        "filterFields": ("kind", "semanticRing", "predicate", "status"),
    },
    {
        "recordKind": "projectedRelation",
        "authorityRole": "projection",
        "filterFields": ("semanticRing", "predicate"),
    },
    {
        "recordKind": "derivedRelation",
        "authorityRole": "derived",
        "filterFields": ("semanticRing", "predicate", "rule", "engine"),
    },
)
PLANNING_FILTER_SEMANTICS: tuple[Mapping[str, str], ...] = ()

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_INTEGER = 9_007_199_254_740_991
_NQUADS_MAX_LINE_BYTES = 16 * 1024 * 1024
_MANIFEST_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "format",
        "distributionId",
        "createdAt",
        "binding",
        "graphs",
        "members",
        "counts",
        "canonicalPayloadDigest",
    }
)
_BINDING_FIELDS = frozenset(
    {
        "version",
        "bindingBundleDigest",
        "ontologyDigest",
        "shapesDigest",
        "manifestSchemaDigest",
        "sourceAccountingSchemaDigest",
        "acceptanceSchemaDigest",
        "validatorVersion",
    }
)
_COUNT_FIELDS = frozenset(
    {
        "releases",
        "resources",
        "labels",
        "sourceRecords",
        "relationAssertions",
        "mappingAssertions",
        "nativeRelationAssertions",
        "sourceAssignments",
        "projectedRelations",
        "derivedRelations",
    }
)
_BINDING_ROOT = Path(__file__).resolve().parents[3] / "bindings" / "atlas" / "3.0"
_BINDING_BUNDLE_PATHS = (
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


class Atlas3ExplorerError(ValueError):
    """An Atlas 3.0 distribution or explorer model is unsafe to consume."""


AtlasExplorerError = Atlas3ExplorerError

_LimitedRow = TypeVar("_LimitedRow")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Atlas3ExplorerError(f"Atlas 3.0 JSON repeats key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise Atlas3ExplorerError(f"Atlas 3.0 JSON contains non-finite number {token}")


def _validate_json_value(value: object, label: str) -> None:
    if value is None or isinstance(value, float):
        raise Atlas3ExplorerError(f"{label} uses a forbidden null or floating-point value")
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > _SAFE_INTEGER:
        raise Atlas3ExplorerError(f"{label} contains an unsafe integer")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise Atlas3ExplorerError(f"{label} contains a non-text object key")
            _validate_json_value(child, f"{label}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            _validate_json_value(child, f"{label}[{index}]")


def _read_canonical_json(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Atlas3ExplorerError(f"{label} must be valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise Atlas3ExplorerError(f"{label} must be a JSON object")
    _validate_json_value(value, label)
    if canonical_json_bytes(value) != payload:
        raise Atlas3ExplorerError(f"{label} is not canonical JSON")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Atlas3ExplorerError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise Atlas3ExplorerError(f"{label} must be an array")
    return cast(Sequence[Any], value)


def _exact_fields(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    if set(value) != expected:
        raise Atlas3ExplorerError(
            f"{label} fields differ; missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise Atlas3ExplorerError(f"{label} must be non-empty trimmed text")
    return value


def _digest(value: object, label: str) -> str:
    text_value = _text(value, label)
    if _DIGEST.fullmatch(text_value) is None:
        raise Atlas3ExplorerError(f"{label} must be sha256:<64 lowercase hex>")
    return text_value


def _count(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise Atlas3ExplorerError(f"{label} must be a non-negative integer")
    return value


def _iri_name(value: object) -> str:
    text_value = str(value)
    if "#" in text_value:
        return text_value.rsplit("#", 1)[-1]
    return text_value.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _one(
    graph: Graph,
    subject: URIRef,
    predicate: URIRef,
    *,
    label: str,
    required: bool = True,
) -> object | None:
    values = tuple(graph.objects(subject, predicate))
    if len(values) > 1 or (required and not values):
        qualifier = "exactly one" if required else "at most one"
        raise Atlas3ExplorerError(f"{label} must have {qualifier} {predicate}")
    return values[0] if values else None


def _json_literal(value: object | None, label: str) -> object | None:
    if value is None:
        return None
    if not isinstance(value, Literal):
        raise Atlas3ExplorerError(f"{label} must be an RDF JSON literal")
    try:
        return json.loads(str(value), object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise Atlas3ExplorerError(f"{label} must contain valid JSON") from error


def _literal_view(value: Literal) -> dict[str, str]:
    result = {"value": str(value)}
    if value.language:
        result["language"] = value.language
    if value.datatype:
        result["datatype"] = str(value.datatype)
    return result


def atlas_v3_predicate_meaning(predicate_iri: str) -> str:
    """Explain a relation without weakening or changing its source semantics."""

    return PREDICATE_MEANINGS.get(
        predicate_iri,
        "A relation preserved with its exact publisher or editorial predicate.",
    )


def _canonical_digest_without_lf(value: object) -> str:
    payload = canonical_json_bytes(value)
    if not payload.endswith(b"\n"):
        raise Atlas3ExplorerError("canonical JSON encoder omitted its expected terminal LF")
    return sha256_digest(payload[:-1])


def _binding_digests() -> dict[str, str]:
    try:
        root_status = _BINDING_ROOT.lstat()
    except OSError as error:
        raise Atlas3ExplorerError("the authoritative Atlas 3.0 binding is unavailable") from error
    if stat.S_ISLNK(root_status.st_mode) or not stat.S_ISDIR(root_status.st_mode):
        raise Atlas3ExplorerError("the authoritative Atlas 3.0 binding root is unsafe")
    relative_paths = {
        *_BINDING_BUNDLE_PATHS,
        *(path.relative_to(_BINDING_ROOT) for path in (_BINDING_ROOT / "schemas").glob("*.schema.json")),
    }
    payloads: dict[Path, bytes] = {}
    for relative in sorted(relative_paths, key=lambda path: path.as_posix()):
        path = _BINDING_ROOT / relative
        try:
            file_status = path.lstat()
            payload = path.read_bytes()
        except OSError as error:
            raise Atlas3ExplorerError(f"cannot read Atlas 3.0 binding asset {relative}") from error
        if stat.S_ISLNK(file_status.st_mode) or not stat.S_ISREG(file_status.st_mode):
            raise Atlas3ExplorerError(f"Atlas 3.0 binding asset {relative} is unsafe")
        payloads[relative] = payload
    bundle_rows = [
        {
            "byteLength": len(payload),
            "digest": sha256_digest(payload),
            "path": relative.as_posix(),
        }
        for relative, payload in payloads.items()
    ]
    return {
        "bindingBundleDigest": _canonical_digest_without_lf(bundle_rows),
        "ontologyDigest": sha256_digest(payloads[Path("ontology/atlas.ttl")]),
        "shapesDigest": sha256_digest(payloads[Path("shapes/atlas.shacl.ttl")]),
        "manifestSchemaDigest": sha256_digest(
            payloads[Path("schemas/atlas-manifest.schema.json")]
        ),
        "sourceAccountingSchemaDigest": sha256_digest(
            payloads[Path("schemas/atlas-source-accounting.schema.json")]
        ),
        "acceptanceSchemaDigest": sha256_digest(
            payloads[Path("schemas/atlas-acceptance.schema.json")]
        ),
    }


def _verify_binding_evidence(
    manifest: Mapping[str, Any],
    acceptance: Mapping[str, Any],
) -> None:
    binding = _mapping(manifest.get("binding"), "Atlas 3.0 manifest binding")
    inputs = _mapping(acceptance.get("inputs"), "Atlas 3.0 acceptance inputs")
    for field, expected in _binding_digests().items():
        if binding.get(field) != expected or inputs.get(field) != expected:
            raise Atlas3ExplorerError(
                f"Atlas 3.0 {field} does not match the authoritative v3 binding"
            )


def _scan_dataset_member(stream: BinaryIO) -> tuple[int, str]:
    digest = hashlib.sha256()
    byte_length = 0
    previous: bytes | None = None
    line_count = 0
    while line := stream.readline(_NQUADS_MAX_LINE_BYTES + 1):
        line_count += 1
        if len(line) > _NQUADS_MAX_LINE_BYTES:
            raise Atlas3ExplorerError(
                f"Atlas 3.0 dataset line {line_count} exceeds {_NQUADS_MAX_LINE_BYTES} bytes"
            )
        digest.update(line)
        byte_length += len(line)
        if not line.endswith(b"\n") or b"\r" in line:
            raise Atlas3ExplorerError("Atlas 3.0 dataset must use canonical LF lines")
        content = line[:-1]
        if not content or content != content.strip() or (
            previous is not None and line <= previous
        ):
            raise Atlas3ExplorerError(
                "Atlas 3.0 dataset lines must be non-empty, unique, and sorted"
            )
        previous = line
    if line_count == 0:
        raise Atlas3ExplorerError("Atlas 3.0 dataset must not be empty")
    return byte_length, "sha256:" + digest.hexdigest()


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _verify_manifest(
    manifest: Mapping[str, Any],
    manifest_payload: bytes,
    member_evidence: Mapping[str, tuple[int, str]],
    trusted_manifest_digest: str | None,
) -> tuple[str, dict[str, URIRef]]:
    _exact_fields(manifest, _MANIFEST_FIELDS, "Atlas 3.0 manifest")
    if (
        manifest.get("type") != "AtlasManifest"
        or manifest.get("schemaVersion") != "3.0"
        or manifest.get("format") != "refspec-atlas-nquads-3.0"
    ):
        raise Atlas3ExplorerError("Atlas 3.0 manifest type, schemaVersion, or format is unsupported")
    _text(manifest.get("distributionId"), "Atlas 3.0 manifest distributionId")
    _text(manifest.get("createdAt"), "Atlas 3.0 manifest createdAt")

    manifest_digest = sha256_digest(manifest_payload)
    if trusted_manifest_digest is not None and (
        _digest(trusted_manifest_digest, "trusted Atlas 3.0 manifest digest") != manifest_digest
    ):
        raise Atlas3ExplorerError("Atlas 3.0 manifest differs from the trusted digest")
    basis = dict(manifest)
    expected_payload_digest = _digest(
        basis.pop("canonicalPayloadDigest"),
        "Atlas 3.0 manifest canonicalPayloadDigest",
    )
    if _canonical_digest_without_lf(basis) != expected_payload_digest:
        raise Atlas3ExplorerError("Atlas 3.0 manifest canonicalPayloadDigest is stale")

    binding = _mapping(manifest.get("binding"), "Atlas 3.0 manifest binding")
    _exact_fields(binding, _BINDING_FIELDS, "Atlas 3.0 manifest binding")
    if binding.get("version") != "3.0" or binding.get("validatorVersion") != "3.0":
        raise Atlas3ExplorerError("Atlas 3.0 manifest binding version is unsupported")
    for key in _BINDING_FIELDS - {"version", "validatorVersion"}:
        _digest(binding.get(key), f"Atlas 3.0 manifest binding.{key}")

    graph_rows = _sequence(manifest.get("graphs"), "Atlas 3.0 manifest graphs")
    if len(graph_rows) != 3:
        raise Atlas3ExplorerError("Atlas 3.0 manifest must declare exactly three graph roles")
    graph_ids: dict[str, URIRef] = {}
    for position, role in enumerate(("asserted", "projection", "derived")):
        row = _mapping(graph_rows[position], f"Atlas 3.0 {role} graph")
        _exact_fields(row, frozenset({"role", "id", "quadCount"}), f"Atlas 3.0 {role} graph")
        if row.get("role") != role:
            raise Atlas3ExplorerError("Atlas 3.0 manifest graph roles are out of order")
        graph_ids[role] = URIRef(_text(row.get("id"), f"Atlas 3.0 {role} graph id"))
        _count(row.get("quadCount"), f"Atlas 3.0 {role} graph quadCount")
    if len(set(graph_ids.values())) != 3:
        raise Atlas3ExplorerError("Atlas 3.0 graph role IRIs must be distinct")

    expected_members = (
        ("atlasDataset", "atlas.nq", "application/n-quads"),
        ("sourceAccounting", "atlas-source-accounting.json", "application/json"),
        ("acceptance", "atlas-acceptance.json", "application/json"),
    )
    members = _sequence(manifest.get("members"), "Atlas 3.0 manifest members")
    if len(members) != len(expected_members):
        raise Atlas3ExplorerError("Atlas 3.0 manifest must pin exactly three non-manifest members")
    for position, (role, path, media_type) in enumerate(expected_members):
        row = _mapping(members[position], f"Atlas 3.0 member {path}")
        _exact_fields(
            row,
            frozenset({"role", "path", "mediaType", "digest", "byteLength"}),
            f"Atlas 3.0 member {path}",
        )
        if row.get("role") != role or row.get("path") != path or row.get("mediaType") != media_type:
            raise Atlas3ExplorerError(f"Atlas 3.0 member {path} role, path, or media type differs")
        byte_length, digest = member_evidence[path]
        if _digest(row.get("digest"), f"Atlas 3.0 member {path} digest") != digest:
            raise Atlas3ExplorerError(f"Atlas 3.0 member {path} digest differs")
        if _count(row.get("byteLength"), f"Atlas 3.0 member {path} byteLength") != byte_length:
            raise Atlas3ExplorerError(f"Atlas 3.0 member {path} byte length differs")

    counts = _mapping(manifest.get("counts"), "Atlas 3.0 manifest counts")
    _exact_fields(counts, _COUNT_FIELDS, "Atlas 3.0 manifest counts")
    for key, value in counts.items():
        _count(value, f"Atlas 3.0 manifest counts.{key}")
    return manifest_digest, graph_ids


def _verify_acceptance(
    manifest: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    member_digests: Mapping[str, str],
) -> None:
    if (
        acceptance.get("type") != "AtlasAcceptance"
        or acceptance.get("version") != "3.0"
        or acceptance.get("distributionId") != manifest.get("distributionId")
        or acceptance.get("verdict") != "passed"
    ):
        raise Atlas3ExplorerError("Atlas 3.0 acceptance does not certify this distribution")
    validator = _mapping(acceptance.get("validator"), "Atlas 3.0 acceptance validator")
    if dict(validator) != {"name": "refspec-atlas-conformance", "version": "3.0"}:
        raise Atlas3ExplorerError("Atlas 3.0 acceptance validator identity is unsupported")
    gate_names: list[str] = []
    for raw in _sequence(acceptance.get("gates"), "Atlas 3.0 acceptance gates"):
        row = _mapping(raw, "Atlas 3.0 acceptance gate")
        if row.get("status") != "passed":
            raise Atlas3ExplorerError("Every Atlas 3.0 acceptance gate must have passed")
        gate_names.append(_text(row.get("name"), "Atlas 3.0 acceptance gate name"))
        _digest(row.get("evidenceDigest"), "Atlas 3.0 acceptance gate evidenceDigest")
    if frozenset(gate_names) != REQUIRED_ACCEPTANCE_GATES or len(gate_names) != len(set(gate_names)):
        raise Atlas3ExplorerError("Atlas 3.0 acceptance gate set is incomplete or duplicated")

    inputs = _mapping(acceptance.get("inputs"), "Atlas 3.0 acceptance inputs")
    binding = _mapping(manifest.get("binding"), "Atlas 3.0 manifest binding")
    expected = {
        "atlasDigest": member_digests["atlas.nq"],
        "sourceAccountingDigest": member_digests["atlas-source-accounting.json"],
        "bindingBundleDigest": binding["bindingBundleDigest"],
        "ontologyDigest": binding["ontologyDigest"],
        "shapesDigest": binding["shapesDigest"],
        "manifestSchemaDigest": binding["manifestSchemaDigest"],
        "sourceAccountingSchemaDigest": binding["sourceAccountingSchemaDigest"],
        "acceptanceSchemaDigest": binding["acceptanceSchemaDigest"],
    }
    if dict(inputs) != expected:
        raise Atlas3ExplorerError("Atlas 3.0 acceptance inputs differ from the sealed distribution")
    for raw in cast(Sequence[Mapping[str, Any]], acceptance["gates"]):
        expected_gate_digest = _canonical_digest_without_lf(
            {
                "inputs": dict(inputs),
                "name": raw["name"],
                "status": "passed",
                "validator": dict(validator),
            }
        )
        if raw["evidenceDigest"] != expected_gate_digest:
            raise Atlas3ExplorerError(f"Atlas 3.0 gate {raw['name']} evidenceDigest differs")


def _verify_dataset(
    manifest: Mapping[str, Any],
    atlas_stream: BinaryIO,
    graph_ids: Mapping[str, URIRef],
) -> Dataset:
    dataset = Dataset(default_union=False)
    try:
        atlas_stream.seek(0)
        dataset.parse(source=atlas_stream, format="nquads")
    except (ParserError, UnicodeDecodeError) as error:
        raise Atlas3ExplorerError("Atlas 3.0 dataset is not valid N-Quads") from error
    observed_graph_counts: Counter[str] = Counter()
    allowed_graph_ids = set(graph_ids.values())
    for subject, predicate, object_value, graph_id in dataset.quads((None, None, None, None)):
        if graph_id not in allowed_graph_ids:
            raise Atlas3ExplorerError(f"Atlas 3.0 dataset uses undeclared graph {graph_id}")
        if any(isinstance(term, BNode) for term in (subject, predicate, object_value, graph_id)):
            raise Atlas3ExplorerError("Atlas 3.0 dataset must not contain blank nodes")
        observed_graph_counts[str(graph_id)] += 1
    expected_graph_counts = {
        str(row["id"]): row["quadCount"]
        for row in cast(Sequence[Mapping[str, Any]], manifest["graphs"])
    }
    if {graph_id: observed_graph_counts[graph_id] for graph_id in expected_graph_counts} != expected_graph_counts:
        raise Atlas3ExplorerError("Atlas 3.0 graph quad counts differ from the manifest")

    asserted = dataset.graph(graph_ids["asserted"])
    projection = dataset.graph(graph_ids["projection"])
    derived = dataset.graph(graph_ids["derived"])
    observed_counts = {
        "releases": len(set(asserted.subjects(RDF.type, ATLAS.AtlasRelease))),
        "resources": len(set(asserted.subjects(RDF.type, ATLAS.AtlasResource))),
        "labels": len(set(asserted.subjects(RDF.type, SKOSXL.Label))),
        "sourceRecords": len(set(asserted.subjects(RDF.type, ATLAS.SourceRecord))),
        "relationAssertions": len(set(asserted.subjects(RDF.type, ATLAS.RelationAssertion))),
        "mappingAssertions": len(set(asserted.subjects(RDF.type, ATLAS.MappingAssertion))),
        "nativeRelationAssertions": len(set(asserted.subjects(RDF.type, ATLAS.NativeRelationAssertion))),
        "sourceAssignments": len(set(asserted.subjects(RDF.type, ATLAS.SourceAssignment))),
        "projectedRelations": len(set(projection.subjects(RDF.type, ATLAS.ProjectedRelation))),
        "derivedRelations": len(set(derived.subjects(RDF.type, ATLAS.DerivedRelation))),
    }
    if observed_counts != dict(cast(Mapping[str, Any], manifest["counts"])):
        raise Atlas3ExplorerError("Atlas 3.0 RDF record counts differ from the manifest")
    return dataset


def _verify_source_accounting(
    manifest: Mapping[str, Any],
    accounting: Mapping[str, Any],
    asserted: Graph,
) -> None:
    if (
        accounting.get("type") != "AtlasSourceAccounting"
        or accounting.get("version") != "3.0"
        or accounting.get("distributionId") != manifest.get("distributionId")
    ):
        raise Atlas3ExplorerError("Atlas 3.0 source accounting belongs to another distribution")
    graph_records = {str(value) for value in asserted.subjects(RDF.type, ATLAS.SourceRecord)}
    graph_releases = {str(value) for value in asserted.subjects(RDF.type, ATLAS.SourceRelease)}
    input_releases: set[str] = set()
    dispositions: dict[str, Mapping[str, Any]] = {}
    status_counts = {"represented": 0, "excluded": 0, "unresolved": 0}
    inputs = _sequence(accounting.get("inputs"), "Atlas 3.0 source accounting inputs")
    for raw_input in inputs:
        source = _mapping(raw_input, "Atlas 3.0 source accounting input")
        source_release = _text(source.get("sourceRelease"), "Atlas 3.0 source release")
        if source_release in input_releases or source_release not in graph_releases:
            raise Atlas3ExplorerError("Atlas 3.0 source accounting repeats or invents a source release")
        input_releases.add(source_release)
        rows = _sequence(source.get("dispositions"), "Atlas 3.0 source dispositions")
        if source.get("membershipMode") in {"complete", "partial"} and source.get("declaredMemberCount") != len(rows):
            raise Atlas3ExplorerError("Atlas 3.0 source declaredMemberCount differs from its dispositions")
        for raw_disposition in rows:
            disposition = _mapping(raw_disposition, "Atlas 3.0 source disposition")
            record = _text(disposition.get("sourceRecord"), "Atlas 3.0 disposition sourceRecord")
            status_value = disposition.get("status")
            if record in dispositions or record not in graph_records or status_value not in status_counts:
                raise Atlas3ExplorerError("Atlas 3.0 source accounting repeats or invents a source record")
            if URIRef(source_release) not in asserted.objects(URIRef(record), ATLAS.inSourceRelease):
                raise Atlas3ExplorerError("Atlas 3.0 source record is assigned to the wrong source release")
            atlas_resources = _sequence(
                disposition.get("atlasResources"),
                f"Atlas 3.0 disposition {record} atlasResources",
            )
            ledger_resources = {str(value) for value in atlas_resources}
            if len(ledger_resources) != len(atlas_resources):
                raise Atlas3ExplorerError(f"Atlas 3.0 disposition {record} repeats an Atlas resource")
            graph_resources = {
                str(value)
                for value in asserted.objects(URIRef(record), ATLAS.representsResource)
            }
            inverse_resources = {
                str(resource)
                for resource in asserted.subjects(ATLAS.sourceRecord, URIRef(record))
                if any((resource, RDF.type, resource_type) in asserted for resource_type in RESOURCE_TYPES)
            }
            if not (ledger_resources == graph_resources == inverse_resources):
                raise Atlas3ExplorerError(
                    f"Atlas 3.0 disposition {record} differs from its bidirectional RDF resource links"
                )
            if status_value == "represented":
                if not ledger_resources or "reason" in disposition:
                    raise Atlas3ExplorerError(
                        f"represented Atlas 3.0 disposition {record} needs resources and no reason"
                    )
            else:
                if ledger_resources or "reason" not in disposition:
                    raise Atlas3ExplorerError(
                        f"{status_value} Atlas 3.0 disposition {record} needs a reason and no resources"
                    )
                _text(disposition["reason"], f"Atlas 3.0 disposition {record} reason")
            for resource in ledger_resources:
                resource_iri = URIRef(resource)
                if not any((resource_iri, RDF.type, resource_type) in asserted for resource_type in RESOURCE_TYPES):
                    raise Atlas3ExplorerError(f"Atlas 3.0 disposition {record} names an unknown resource")
            dispositions[record] = disposition
            status_counts[cast(str, status_value)] += 1
    if set(dispositions) != graph_records or input_releases != graph_releases:
        raise Atlas3ExplorerError("Atlas 3.0 source accounting is not complete for the asserted graph")
    expected_totals = {
        "sourceReleases": len(input_releases),
        "sourceRecords": len(dispositions),
        **status_counts,
    }
    if accounting.get("totals") != expected_totals:
        raise Atlas3ExplorerError("Atlas 3.0 source-accounting totals do not reconcile")


@dataclass(frozen=True, slots=True)
class Atlas3ExplorerDistribution:
    """A verified, read-only view of one sealed Atlas 3.0 distribution."""

    root: Path
    manifest_digest: str
    manifest: Mapping[str, Any]
    source_accounting: Mapping[str, Any]
    acceptance: Mapping[str, Any]
    trusted_manifest: bool
    binding_verified: bool
    _dataset: Dataset
    _graph_ids: Mapping[str, URIRef]

    @classmethod
    def open(
        cls,
        root: str | Path,
        *,
        trusted_manifest_digest: str,
    ) -> Atlas3ExplorerDistribution:
        """Open four exact files, verify their pins, and retain graph roles."""

        requested_root = Path(root)
        try:
            root_status = requested_root.lstat()
        except OSError as error:
            raise Atlas3ExplorerError(f"cannot open Atlas 3.0 distribution {requested_root}") from error
        if stat.S_ISLNK(root_status.st_mode) or not stat.S_ISDIR(root_status.st_mode):
            raise Atlas3ExplorerError("Atlas 3.0 distribution root must be a real directory")
        resolved_root = requested_root.resolve(strict=True)
        children = {child.name: child for child in resolved_root.iterdir()}
        if set(children) != EXPECTED_FILES:
            raise Atlas3ExplorerError(
                "Atlas 3.0 distribution files differ; "
                f"missing={sorted(EXPECTED_FILES - set(children))}, "
                f"extra={sorted(set(children) - EXPECTED_FILES)}"
            )
        member_statuses: dict[str, os.stat_result] = {}
        for name, path in children.items():
            file_status = path.lstat()
            if stat.S_ISLNK(file_status.st_mode) or not stat.S_ISREG(file_status.st_mode):
                raise Atlas3ExplorerError(f"Atlas 3.0 member {name} must be a regular non-symlink file")
            member_statuses[name] = file_status

        json_payloads = {
            name: children[name].read_bytes()
            for name in (
                "atlas-manifest.json",
                "atlas-source-accounting.json",
                "atlas-acceptance.json",
            )
        }
        member_evidence = {
            name: (len(payload), sha256_digest(payload))
            for name, payload in json_payloads.items()
            if name != "atlas-manifest.json"
        }
        atlas_path = children["atlas.nq"]
        with atlas_path.open("rb") as atlas_stream:
            opened_status = os.fstat(atlas_stream.fileno())
            if (
                not stat.S_ISREG(opened_status.st_mode)
                or (opened_status.st_dev, opened_status.st_ino)
                != (
                    member_statuses["atlas.nq"].st_dev,
                    member_statuses["atlas.nq"].st_ino,
                )
            ):
                raise Atlas3ExplorerError("Atlas 3.0 dataset changed while it was being opened")
            opened_identity = _file_identity(opened_status)
            member_evidence["atlas.nq"] = _scan_dataset_member(atlas_stream)

            manifest_payload = json_payloads["atlas-manifest.json"]
            manifest = _read_canonical_json(manifest_payload, "Atlas 3.0 manifest")
            source_accounting = _read_canonical_json(
                json_payloads["atlas-source-accounting.json"],
                "Atlas 3.0 source accounting",
            )
            acceptance = _read_canonical_json(
                json_payloads["atlas-acceptance.json"],
                "Atlas 3.0 acceptance",
            )
            manifest_digest, graph_ids = _verify_manifest(
                manifest,
                manifest_payload,
                member_evidence,
                trusted_manifest_digest,
            )
            _verify_acceptance(
                manifest,
                acceptance,
                {name: digest for name, (_size, digest) in member_evidence.items()},
            )
            _verify_binding_evidence(manifest, acceptance)
            dataset = _verify_dataset(manifest, atlas_stream, graph_ids)
            try:
                current_path_status = atlas_path.lstat()
                final_status = os.fstat(atlas_stream.fileno())
            except OSError as error:
                raise Atlas3ExplorerError("Atlas 3.0 dataset changed while it was being read") from error
            if (
                _file_identity(final_status) != opened_identity
                or stat.S_ISLNK(current_path_status.st_mode)
                or _file_identity(current_path_status) != opened_identity
            ):
                raise Atlas3ExplorerError("Atlas 3.0 dataset changed while it was being read")
            _verify_source_accounting(
                manifest,
                source_accounting,
                dataset.graph(graph_ids["asserted"]),
            )
        return cls(
            root=resolved_root,
            manifest_digest=manifest_digest,
            manifest=cast(Mapping[str, Any], deep_freeze_json(manifest)),
            source_accounting=cast(Mapping[str, Any], deep_freeze_json(source_accounting)),
            acceptance=cast(Mapping[str, Any], deep_freeze_json(acceptance)),
            trusted_manifest=True,
            binding_verified=True,
            _dataset=dataset,
            _graph_ids=cast(Mapping[str, URIRef], deep_freeze_json(graph_ids)),
        )

    def graph(self, role: str) -> Graph:
        """Return exactly one manifest-assigned graph role."""

        graph_id = self._graph_ids.get(role)
        if graph_id is None:
            raise Atlas3ExplorerError(f"unknown Atlas 3.0 graph role {role!r}")
        return self._dataset.graph(graph_id)

    @property
    def asserted_graph(self) -> Graph:
        return self.graph("asserted")

    @property
    def projection_graph(self) -> Graph:
        return self.graph("projection")

    @property
    def derived_graph(self) -> Graph:
        return self.graph("derived")


def open_atlas_v3_explorer_distribution(
    root: str | Path,
    *,
    trusted_manifest_digest: str,
) -> Atlas3ExplorerDistribution:
    """Open one Atlas 3.0 distribution for evidence-aware exploration."""

    return Atlas3ExplorerDistribution.open(root, trusted_manifest_digest=trusted_manifest_digest)


def _source_record_view(graph: Graph, record: URIRef) -> dict[str, Any]:
    return {
        "id": str(record),
        "sourceRelease": str(_one(graph, record, ATLAS.inSourceRelease, label=f"source record {record}")),
        "sourceLocator": str(_one(graph, record, ATLAS.sourceLocator, label=f"source record {record}")),
        "sourceDigest": str(_one(graph, record, ATLAS.sourceDigest, label=f"source record {record}")),
        "contentDigest": str(_one(graph, record, ATLAS.contentDigest, label=f"source record {record}")),
        "nativePayload": _json_literal(
            _one(graph, record, ATLAS.nativePayload, label=f"source record {record}"),
            f"source record {record} nativePayload",
        ),
        "representsResources": sorted(str(value) for value in graph.objects(record, ATLAS.representsResource)),
    }


def _label_view(graph: Graph, label: URIRef, role: str) -> dict[str, Any]:
    literal = _one(graph, label, SKOSXL.literalForm, label=f"label {label}")
    if not isinstance(literal, Literal):
        raise Atlas3ExplorerError(f"label {label} literalForm must be a literal")
    return {
        "id": str(label),
        "role": role,
        **_literal_view(literal),
        "sourceRecord": str(_one(graph, label, ATLAS.sourceRecord, label=f"label {label}")),
        "contentDigest": str(_one(graph, label, ATLAS.contentDigest, label=f"label {label}")),
    }


def _resource_display_label(graph: Graph, resource: URIRef) -> str:
    candidates: list[tuple[int, str, str, str, str]] = []
    for role_order, (predicate, _role) in enumerate(LABEL_ROLES):
        for label in graph.objects(resource, predicate):
            if not isinstance(label, URIRef):
                continue
            literal = _one(graph, label, SKOSXL.literalForm, label=f"label {label}")
            if not isinstance(literal, Literal):
                raise Atlas3ExplorerError(f"label {label} literalForm must be a literal")
            literal_view = _literal_view(literal)
            value = literal_view["value"]
            candidates.append(
                (
                    role_order,
                    literal_view.get("language", ""),
                    value.casefold(),
                    value,
                    str(label),
                )
            )
    if not candidates:
        raise Atlas3ExplorerError(f"resource {resource} has no asserted SKOS-XL label")
    return min(candidates)[3]


def _resource_view(graph: Graph, resource: URIRef) -> dict[str, Any]:
    labels: list[dict[str, Any]] = []
    for predicate, role in LABEL_ROLES:
        labels.extend(
            _label_view(graph, value, role)
            for value in graph.objects(resource, predicate)
            if isinstance(value, URIRef)
        )
    role_order = {role: position for position, (_predicate, role) in enumerate(LABEL_ROLES)}
    labels.sort(
        key=lambda row: (
            role_order[row["role"]],
            row.get("language", ""),
            cast(str, row["value"]).casefold(),
            row["value"],
            row["id"],
        )
    )
    if not labels:
        raise Atlas3ExplorerError(f"resource {resource} has no asserted SKOS-XL label")
    resource_types = [value for value in RESOURCE_TYPES if (resource, RDF.type, value) in graph]
    if len(resource_types) != 1:
        raise Atlas3ExplorerError(f"resource {resource} must have one Atlas 3.0 resource type")
    return {
        "id": str(resource),
        "resourceType": _iri_name(resource_types[0]),
        "release": str(_one(graph, resource, ATLAS.inRelease, label=f"resource {resource}")),
        "scheme": str(_one(graph, resource, ATLAS.inScheme, label=f"resource {resource}")),
        "semanticRing": _iri_name(_one(graph, resource, ATLAS.semanticRing, label=f"resource {resource}")),
        "resourceProfile": _iri_name(_one(graph, resource, ATLAS.resourceProfile, label=f"resource {resource}")),
        "displayLabel": labels[0]["value"],
        "displayLabelRole": labels[0]["role"],
        "labels": labels,
        "sourceRecords": sorted(str(value) for value in graph.objects(resource, ATLAS.sourceRecord)),
        "contentDigest": str(_one(graph, resource, ATLAS.contentDigest, label=f"resource {resource}")),
        "notations": sorted(str(value) for value in graph.objects(resource, ATLAS.notation)),
        "definitions": [
            _literal_view(value)
            for value in graph.objects(resource, ATLAS.definition)
            if isinstance(value, Literal)
        ],
        "notes": [
            _literal_view(value)
            for value in graph.objects(resource, ATLAS.note)
            if isinstance(value, Literal)
        ],
    }


def _resource_index_view(
    graph: Graph,
    resource: URIRef,
    display_label: str,
) -> dict[str, str]:
    """Return the small, complete resource row used by search and filtering."""

    return {
        "id": str(resource),
        "displayLabel": display_label,
        "release": str(_one(graph, resource, ATLAS.inRelease, label=f"resource {resource}")),
        "semanticRing": _iri_name(
            _one(graph, resource, ATLAS.semanticRing, label=f"resource {resource}")
        ),
    }


def _policy_view(graph: Graph, policy: URIRef) -> dict[str, Any]:
    return {
        "id": str(policy),
        "contentDigest": str(_one(graph, policy, ATLAS.contentDigest, label=f"policy {policy}")),
        "payload": _json_literal(
            _one(graph, policy, ATLAS.policyPayload, label=f"policy {policy}"),
            f"policy {policy} payload",
        ),
    }


def _evidence_view(
    graph: Graph,
    binding: URIRef,
    source_record_content_digests: Mapping[str, str],
) -> dict[str, Any]:
    record = _one(graph, binding, ATLAS.evidenceSourceRecord, label=f"evidence {binding}")
    record_id = str(record)
    if not isinstance(record, URIRef) or record_id not in source_record_content_digests:
        raise Atlas3ExplorerError(f"evidence {binding} names an unavailable source record")
    result: dict[str, Any] = {
        "id": str(binding),
        "sourceRecord": record_id,
        "sourceRecordContentDigest": source_record_content_digests[record_id],
        "sourceDigest": str(_one(graph, binding, ATLAS.evidenceSourceDigest, label=f"evidence {binding}")),
        "decisionStatus": _iri_name(_one(graph, binding, ATLAS.decisionStatus, label=f"evidence {binding}")),
        "reviewMethod": _iri_name(_one(graph, binding, ATLAS.reviewMethod, label=f"evidence {binding}")),
        "decidedAt": str(_one(graph, binding, ATLAS.decidedAt, label=f"evidence {binding}")),
        "contentDigest": str(_one(graph, binding, ATLAS.contentDigest, label=f"evidence {binding}")),
    }
    for predicate, field in ((ATLAS.reviewedBy, "reviewedBy"), (ATLAS.confidence, "confidence")):
        value = _one(graph, binding, predicate, label=f"evidence {binding}", required=False)
        if value is not None:
            result[field] = str(value)
    return result


def _assertion_view(
    graph: Graph,
    assertion: URIRef,
    source_record_content_digests: Mapping[str, str],
    labels: Mapping[str, str],
) -> dict[str, Any]:
    kinds = [label for relation_type, label in RELATION_TYPES if (assertion, RDF.type, relation_type) in graph]
    if len(kinds) != 1:
        raise Atlas3ExplorerError(f"assertion {assertion} must have one Atlas 3.0 specialization")
    subject = _one(graph, assertion, RDF.subject, label=f"assertion {assertion}")
    predicate = _one(graph, assertion, RDF.predicate, label=f"assertion {assertion}")
    object_value = _one(graph, assertion, RDF.object, label=f"assertion {assertion}")
    policy = _one(graph, assertion, ATLAS.governedByPolicy, label=f"assertion {assertion}")
    if not all(isinstance(value, URIRef) for value in (subject, predicate, object_value, policy)):
        raise Atlas3ExplorerError(f"assertion {assertion} endpoints, predicate, and policy must be IRIs")
    evidence = sorted(
        (
            _evidence_view(graph, binding, source_record_content_digests)
            for binding in graph.subjects(ATLAS.bindsAssertion, assertion)
            if isinstance(binding, URIRef)
        ),
        key=lambda row: row["id"],
    )
    if not evidence:
        raise Atlas3ExplorerError(f"assertion {assertion} has no evidence binding")
    status = _iri_name(_one(graph, assertion, ATLAS.assertionStatus, label=f"assertion {assertion}"))
    result: dict[str, Any] = {
        "id": str(assertion),
        "kind": kinds[0],
        "authority": "authoritative" if status == "current" else "historicalEditorialRecord",
        "authoritative": status == "current",
        "subject": str(subject),
        "subjectLabel": labels.get(str(subject), _iri_name(subject)),
        "predicate": str(predicate),
        "predicateLabel": _iri_name(predicate),
        "predicateMeaning": atlas_v3_predicate_meaning(str(predicate)),
        "object": str(object_value),
        "objectLabel": labels.get(str(object_value), _iri_name(object_value)),
        "semanticRing": _iri_name(_one(graph, assertion, ATLAS.semanticRing, label=f"assertion {assertion}")),
        "sourceRelease": str(_one(graph, assertion, ATLAS.sourceRelease, label=f"assertion {assertion}")),
        "targetRelease": str(_one(graph, assertion, ATLAS.targetRelease, label=f"assertion {assertion}")),
        "assertedAt": str(_one(graph, assertion, ATLAS.assertedAt, label=f"assertion {assertion}")),
        "status": status,
        "identityDigest": str(
            _one(graph, assertion, ATLAS.assertionIdentityDigest, label=f"assertion {assertion}")
        ),
        "contentDigest": str(_one(graph, assertion, ATLAS.contentDigest, label=f"assertion {assertion}")),
        "policy": _policy_view(graph, cast(URIRef, policy)),
        "evidence": evidence,
    }
    supersedes = _one(graph, assertion, ATLAS.supersedes, label=f"assertion {assertion}", required=False)
    if supersedes is not None:
        result["supersedes"] = str(supersedes)
    return result


def _projected_view(graph: Graph, relation: URIRef, labels: Mapping[str, str]) -> dict[str, Any]:
    subject = _one(graph, relation, ATLAS.relationSubject, label=f"projection {relation}")
    predicate = _one(graph, relation, ATLAS.relationPredicate, label=f"projection {relation}")
    object_value = _one(graph, relation, ATLAS.relationObject, label=f"projection {relation}")
    supporting_assertions = sorted(str(value) for value in graph.objects(relation, ATLAS.supportingAssertion))
    if not supporting_assertions:
        raise Atlas3ExplorerError(f"projection {relation} has no supporting assertion")
    return {
        "id": str(relation),
        "authority": "reproducibleProjection",
        "authoritative": False,
        "subject": str(subject),
        "subjectLabel": labels.get(str(subject), _iri_name(subject)),
        "predicate": str(predicate),
        "predicateLabel": _iri_name(predicate),
        "predicateMeaning": atlas_v3_predicate_meaning(str(predicate)),
        "object": str(object_value),
        "objectLabel": labels.get(str(object_value), _iri_name(object_value)),
        "semanticRing": _iri_name(_one(graph, relation, ATLAS.semanticRing, label=f"projection {relation}")),
        "supportingAssertions": supporting_assertions,
        "contentDigest": str(_one(graph, relation, ATLAS.contentDigest, label=f"projection {relation}")),
    }


def _derived_view(graph: Graph, relation: URIRef, labels: Mapping[str, str]) -> dict[str, Any]:
    subject = _one(graph, relation, ATLAS.relationSubject, label=f"derived relation {relation}")
    predicate = _one(graph, relation, ATLAS.relationPredicate, label=f"derived relation {relation}")
    object_value = _one(graph, relation, ATLAS.relationObject, label=f"derived relation {relation}")
    authority_status = _one(graph, relation, ATLAS.authorityStatus, label=f"derived relation {relation}")
    if authority_status != ATLAS.nonAuthoritative:
        raise Atlas3ExplorerError(f"derived relation {relation} is not explicitly non-authoritative")
    return {
        "id": str(relation),
        "authority": "nonAuthoritative",
        "authorityStatus": _iri_name(authority_status),
        "authoritative": False,
        "subject": str(subject),
        "subjectLabel": labels.get(str(subject), _iri_name(subject)),
        "predicate": str(predicate),
        "predicateLabel": _iri_name(predicate),
        "predicateMeaning": atlas_v3_predicate_meaning(str(predicate)),
        "object": str(object_value),
        "objectLabel": labels.get(str(object_value), _iri_name(object_value)),
        "semanticRing": _iri_name(
            _one(graph, relation, ATLAS.semanticRing, label=f"derived relation {relation}")
        ),
        "derivedFromAssertions": sorted(str(value) for value in graph.objects(relation, ATLAS.derivedFromAssertion)),
        "rule": str(_one(graph, relation, ATLAS.derivationRule, label=f"derived relation {relation}")),
        "engine": str(_one(graph, relation, ATLAS.engine, label=f"derived relation {relation}")),
        "engineVersion": str(_one(graph, relation, ATLAS.engineVersion, label=f"derived relation {relation}")),
        "inputDigest": str(_one(graph, relation, ATLAS.inputDigest, label=f"derived relation {relation}")),
        "generatedAt": str(_one(graph, relation, ATLAS.generatedAt, label=f"derived relation {relation}")),
        "contentDigest": str(_one(graph, relation, ATLAS.contentDigest, label=f"derived relation {relation}")),
    }


def _release_view(graph: Graph, release: URIRef, *, source: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": str(release),
        "kind": "source" if source else "atlas",
        "contentDigest": str(_one(graph, release, ATLAS.contentDigest, label=f"release {release}")),
    }
    optional_fields = (
        (DCTERMS.title, "title", False),
        (DCTERMS.identifier, "identifier", False),
        (DCTERMS.issued, "issued", False),
        (ATLAS.sourceLocator, "sourceLocator", False),
        (ATLAS.sourceDigest, "sourceDigest", False),
        (ATLAS.inScheme, "scheme", False),
        (ATLAS.sourceRelease, "sourceRelease", False),
        (ATLAS.resourceProfile, "resourceProfile", True),
        (ATLAS.semanticRing, "semanticRing", True),
    )
    for predicate, field, short_iri in optional_fields:
        value = _one(graph, release, predicate, label=f"release {release}", required=False)
        if value is not None:
            result[field] = _iri_name(value) if short_iri else str(value)
    if not source:
        result["memberCount"] = len(set(graph.objects(release, PROV.hadMember)))
    return result


def _limit(rows: list[_LimitedRow], limit: int | None, label: str) -> list[_LimitedRow]:
    if limit is None:
        return rows
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise Atlas3ExplorerError(f"{label} must be a non-negative integer or None")
    return rows[:limit]


def build_atlas_v3_explorer_model(
    distribution: Atlas3ExplorerDistribution,
    *,
    title: str = "RefSpec Atlas 3.0 explorer",
    max_resources: int | None = None,
    max_assertions: int | None = None,
    max_projected_relations: int | None = None,
    max_derived_relations: int | None = None,
) -> dict[str, Any]:
    """Build a JSON view whose relation collections retain their authority roles."""

    if not isinstance(distribution, Atlas3ExplorerDistribution):
        raise Atlas3ExplorerError("Atlas 3.0 explorer requires an opened distribution")
    _text(title, "Atlas 3.0 explorer title")
    for limit, label in (
        (max_resources, "max_resources"),
        (max_assertions, "max_assertions"),
        (max_projected_relations, "max_projected_relations"),
        (max_derived_relations, "max_derived_relations"),
    ):
        _limit([], limit, label)
    asserted = distribution.asserted_graph
    projection = distribution.projection_graph
    derived = distribution.derived_graph

    source_record_ids = sorted(
        (
            record
            for record in set(asserted.subjects(RDF.type, ATLAS.SourceRecord))
            if isinstance(record, URIRef)
        ),
        key=str,
    )
    source_record_by_id = {str(record): record for record in source_record_ids}
    source_record_content_digests = {
        str(record): str(_one(asserted, record, ATLAS.contentDigest, label=f"source record {record}"))
        for record in source_record_ids
    }
    resource_ids = [
        resource
        for resource in set(asserted.subjects(RDF.type, ATLAS.AtlasResource))
        if isinstance(resource, URIRef)
    ]
    labels = {
        str(resource): _resource_display_label(asserted, resource)
        for resource in resource_ids
    }
    resource_ids.sort(
        key=lambda resource: (
            labels[str(resource)].casefold(),
            labels[str(resource)],
            str(resource),
        )
    )
    resource_index = [
        _resource_index_view(asserted, resource, labels[str(resource)])
        for resource in resource_ids
    ]
    shown_resource_ids = _limit(resource_ids, max_resources, "max_resources")
    resources = [
        _resource_view(asserted, resource)
        for resource in shown_resource_ids
    ]
    assertion_ids = sorted(
        (
            assertion
            for assertion in set(asserted.subjects(RDF.type, ATLAS.RelationAssertion))
            if isinstance(assertion, URIRef)
        ),
        key=str,
    )
    primary_assertion_ids = _limit(assertion_ids, max_assertions, "max_assertions")
    projected_ids = sorted(
        (
            relation
            for relation in set(projection.subjects(RDF.type, ATLAS.ProjectedRelation))
            if isinstance(relation, URIRef)
        ),
        key=str,
    )
    shown_projected_ids = _limit(
        projected_ids,
        max_projected_relations,
        "max_projected_relations",
    )
    projected = [
        _projected_view(projection, relation, labels)
        for relation in shown_projected_ids
    ]
    derived_ids = sorted(
        (
            relation
            for relation in set(derived.subjects(RDF.type, ATLAS.DerivedRelation))
            if isinstance(relation, URIRef)
        ),
        key=str,
    )
    shown_derived_ids = _limit(
        derived_ids,
        max_derived_relations,
        "max_derived_relations",
    )
    derived_rows = [
        _derived_view(derived, relation, labels)
        for relation in shown_derived_ids
    ]
    referenced_assertion_ids = {
        assertion_id
        for relation in (*projected, *derived_rows)
        for field in ("supportingAssertions", "derivedFromAssertions")
        for assertion_id in cast(Sequence[str], relation.get(field, ()))
    }
    assertion_by_id = {str(assertion): assertion for assertion in assertion_ids}
    unavailable_assertions = referenced_assertion_ids - set(assertion_by_id)
    if unavailable_assertions:
        raise Atlas3ExplorerError(
            "bounded Atlas 3.0 relations cite unavailable assertions: "
            f"{sorted(unavailable_assertions)}"
        )
    selected_assertion_ids = {str(assertion) for assertion in primary_assertion_ids}
    selected_assertion_ids.update(referenced_assertion_ids)
    shown_assertion_ids = [
        assertion_by_id[assertion_id]
        for assertion_id in sorted(selected_assertion_ids)
    ]
    assertions = [
        _assertion_view(
            asserted,
            assertion,
            source_record_content_digests,
            labels,
        )
        for assertion in shown_assertion_ids
    ]
    current_authoritative_relations = sum(
        _iri_name(
            _one(
                asserted,
                assertion,
                ATLAS.assertionStatus,
                label=f"assertion {assertion}",
            )
        )
        == "current"
        for assertion in assertion_ids
    )
    shown_source_record_ids = {
        cast(str, record)
        for resource in resources
        for record in cast(Sequence[str], resource["sourceRecords"])
    } | {
        cast(str, evidence["sourceRecord"])
        for assertion in assertions
        for evidence in cast(Sequence[Mapping[str, Any]], assertion["evidence"])
    }
    shown_source_records = [
        _source_record_view(asserted, source_record_by_id[record_id])
        for record_id in sorted(shown_source_record_ids)
    ]
    graph_by_role = {
        cast(str, row["role"]): cast(str, row["id"])
        for row in cast(Sequence[Mapping[str, Any]], distribution.manifest["graphs"])
    }
    return {
        "type": ATLAS_V3_EXPLORER_TYPE,
        "schemaVersion": ATLAS_V3_EXPLORER_SCHEMA_VERSION,
        "title": title,
        "distribution": {
            "id": distribution.manifest["distributionId"],
            "manifestDigest": distribution.manifest_digest,
            "trustedManifestDigestChecked": distribution.trusted_manifest,
            "createdAt": distribution.manifest["createdAt"],
            "counts": dict(cast(Mapping[str, Any], distribution.manifest["counts"])),
        },
        "acceptance": {
            "verdict": distribution.acceptance["verdict"],
            "receiptVerified": True,
            "bindingDigestChecked": distribution.binding_verified,
            "gatesReexecutedByExplorer": False,
            "evaluatedAt": distribution.acceptance["evaluatedAt"],
            "validator": dict(cast(Mapping[str, Any], distribution.acceptance["validator"])),
            "gates": [dict(cast(Mapping[str, Any], row)) for row in distribution.acceptance["gates"]],
        },
        "authority": {
            "asserted": {
                "graph": graph_by_role["asserted"],
                "status": "authoritative",
                "meaning": (
                    "Evidence-bearing current assertion records are editorial authority. "
                    "Every displayed assertion links to its policy and source-record evidence."
                ),
            },
            "projection": {
                "graph": graph_by_role["projection"],
                "status": "reproducibleConvenienceView",
                "meaning": (
                    "Bare relation triples and plain SKOS labels are generated from asserted records; "
                    "they are not independent editorial facts."
                ),
            },
            "derived": {
                "graph": graph_by_role["derived"],
                "status": "nonAuthoritative",
                "meaning": (
                    "Reasoner output is useful for search and analysis but is never an editorial assertion."
                ),
            },
        },
        "summary": {
            "availableResources": len(resource_ids),
            "indexedResources": len(resource_index),
            "shownResources": len(resources),
            "availableSourceRecords": len(source_record_ids),
            "shownSourceRecords": len(shown_source_records),
            "availableAssertedRelations": len(assertion_ids),
            "shownAssertedRelations": len(assertions),
            "provenanceClosureAssertedRelations": (
                len(assertions) - len(primary_assertion_ids)
            ),
            "currentAuthoritativeRelations": current_authoritative_relations,
            "availableProjectedRelations": len(projected_ids),
            "shownProjectedRelations": len(projected),
            "availableDerivedRelations": len(derived_ids),
            "shownDerivedRelations": len(derived_rows),
            "truncated": any(
                (
                    len(resources) < len(resource_ids),
                    len(assertions) < len(assertion_ids),
                    len(projected) < len(projected_ids),
                    len(derived_rows) < len(derived_ids),
                )
            ),
        },
        "atlasReleases": sorted(
            (
                _release_view(asserted, release, source=False)
                for release in set(asserted.subjects(RDF.type, ATLAS.AtlasRelease))
                if isinstance(release, URIRef)
            ),
            key=lambda row: row["id"],
        ),
        "sourceReleases": sorted(
            (
                _release_view(asserted, release, source=True)
                for release in set(asserted.subjects(RDF.type, ATLAS.SourceRelease))
                if isinstance(release, URIRef)
            ),
            key=lambda row: row["id"],
        ),
        "sourceRecords": shown_source_records,
        "resourceIndex": resource_index,
        "resources": resources,
        "assertedRelations": assertions,
        "projectedRelations": projected,
        "derivedRelations": derived_rows,
    }


def _validate_model(model: Mapping[str, Any]) -> None:
    if model.get("type") != ATLAS_V3_EXPLORER_TYPE or model.get("schemaVersion") != ATLAS_V3_EXPLORER_SCHEMA_VERSION:
        raise Atlas3ExplorerError("Atlas 3.0 explorer type or schemaVersion is unsupported")
    _text(model.get("title"), "Atlas 3.0 explorer title")
    authority = _mapping(model.get("authority"), "Atlas 3.0 explorer authority")
    if set(authority) != {"asserted", "projection", "derived"}:
        raise Atlas3ExplorerError("Atlas 3.0 explorer must keep all three graph roles distinct")
    expected_status = {
        "asserted": "authoritative",
        "projection": "reproducibleConvenienceView",
        "derived": "nonAuthoritative",
    }
    graph_ids: set[str] = set()
    for role, status_value in expected_status.items():
        row = _mapping(authority.get(role), f"Atlas 3.0 explorer {role}")
        if row.get("status") != status_value:
            raise Atlas3ExplorerError(f"Atlas 3.0 explorer {role} authority status differs")
        graph_ids.add(_text(row.get("graph"), f"Atlas 3.0 explorer {role} graph"))
    if len(graph_ids) != 3:
        raise Atlas3ExplorerError("Atlas 3.0 explorer graph role IRIs must be distinct")
    for field in (
        "resourceIndex",
        "resources",
        "sourceRecords",
        "assertedRelations",
        "projectedRelations",
        "derivedRelations",
    ):
        _sequence(model.get(field), f"Atlas 3.0 explorer {field}")
    resource_index_ids = [
        _text(_mapping(row, "Atlas 3.0 resource index row").get("id"), "resource index id")
        for row in model["resourceIndex"]
    ]
    if len(resource_index_ids) != len(set(resource_index_ids)):
        raise Atlas3ExplorerError("Atlas 3.0 resource index repeats an id")
    summary = _mapping(model.get("summary"), "Atlas 3.0 explorer summary")
    if summary.get("availableResources") != len(resource_index_ids):
        raise Atlas3ExplorerError("Atlas 3.0 resource index is incomplete")
    detailed_resource_ids = {
        _text(_mapping(row, "Atlas 3.0 resource").get("id"), "resource id")
        for row in model["resources"]
    }
    if not detailed_resource_ids.issubset(resource_index_ids):
        raise Atlas3ExplorerError("Atlas 3.0 detailed resources are absent from its index")
    for row in model["assertedRelations"]:
        expected_authority = row.get("status") == "current"
        if row.get("authoritative") is not expected_authority or row.get("authority") != (
            "authoritative" if expected_authority else "historicalEditorialRecord"
        ):
            raise Atlas3ExplorerError("Atlas 3.0 asserted relation authority differs from its lifecycle status")
    if any(row.get("authoritative") is not False for row in model["projectedRelations"]):
        raise Atlas3ExplorerError("Atlas 3.0 projections contain an authoritative row")
    if any(row.get("authority") != "nonAuthoritative" for row in model["derivedRelations"]):
        raise Atlas3ExplorerError("Atlas 3.0 derivations contain an authoritative row")
    assertion_ids = {
        _text(_mapping(row, "Atlas 3.0 asserted relation").get("id"), "asserted relation id")
        for row in model["assertedRelations"]
    }
    for field, rows in (
        ("supportingAssertions", model["projectedRelations"]),
        ("derivedFromAssertions", model["derivedRelations"]),
    ):
        for raw_row in rows:
            row = _mapping(raw_row, f"Atlas 3.0 relation with {field}")
            references = {
                _text(value, f"Atlas 3.0 relation {field}[]")
                for value in _sequence(row.get(field), f"Atlas 3.0 relation {field}")
            }
            if not references.issubset(assertion_ids):
                raise Atlas3ExplorerError(
                    f"Atlas 3.0 relation {field} is not provenance-closed"
                )


def _safe_json(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


class _Atlas3Template(Template):
    delimiter = "@@"


_GRAPH_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <link rel="icon" href="data:,">
  <title>@@title · RefSpec Atlas 3 explorer</title>
  <style>
    :root {
      --ink: #edf4f0; --muted: #9caaa4; --faint: #66756f; --paper: #09100e;
      --raised: #101a17; --rule: #263530; --rule-strong: #3b4f48; --focus: #99ddd0;
      --asserted: #70d29b; --projection: #68a9ff; --derived: #e7ad55;
      --serif: ui-serif, Georgia, Cambria, "Times New Roman", serif;
      --sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --mono: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
    }
    * { box-sizing: border-box; }
    html, body { width: 100%; height: 100%; }
    body { margin: 0; overflow: hidden; color: var(--ink); background: var(--paper); font: 14px/1.45 var(--sans); }
    button, input, select { font: inherit; }
    button:focus-visible, input:focus-visible, select:focus-visible, canvas:focus-visible {
      outline: 2px solid var(--focus); outline-offset: 2px;
    }
    .shell { display: grid; grid-template-rows: 68px minmax(0, 1fr) 34px; height: 100%; }
    .appbar {
      display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 1rem; align-items: center;
      padding: .75rem 1.1rem; border-bottom: 1px solid var(--rule); background: rgba(9, 16, 14, .96);
    }
    .eyebrow { color: var(--asserted); font: 600 10px/1.2 var(--mono); letter-spacing: .14em; text-transform: uppercase; }
    h1 { margin: .2rem 0 0; overflow: hidden; font: 500 1.35rem/1.1 var(--serif); text-overflow: ellipsis; white-space: nowrap; }
    .metrics { display: flex; gap: 1.2rem; }
    .metric { text-align: right; } .metric b { display: block; font: 600 .95rem/1 var(--mono); }
    .metric span { color: var(--faint); font-size: .65rem; letter-spacing: .08em; text-transform: uppercase; }
    .workspace { display: grid; grid-template-columns: 272px minmax(0, 1fr) 330px; min-height: 0; }
    .panel { min-height: 0; overflow: auto; background: rgba(14, 23, 20, .94); scrollbar-color: var(--rule-strong) transparent; }
    .controls { padding: 1rem; border-right: 1px solid var(--rule); }
    .inspector { padding: 1rem 1.05rem 1.5rem; border-left: 1px solid var(--rule); }
    .panel h2, .panel h3 { margin: 0; font-size: .7rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
    .panel h3 { color: var(--faint); }
    .control-section { padding: .9rem 0; border-bottom: 1px solid var(--rule); }
    .control-section:last-child { border-bottom: 0; }
    .search-wrap { position: relative; margin-top: .65rem; }
    #search, #ring-filter, #predicate-filter, #render-limit-number {
      width: 100%; min-height: 38px; padding: .55rem .65rem; color: var(--ink);
      border: 1px solid var(--rule-strong); border-radius: 4px; background: #080e0c;
    }
    #search { padding-right: 2rem; } .key { position: absolute; top: 50%; right: .65rem; color: var(--faint); transform: translateY(-50%); }
    .results { display: grid; margin-top: .35rem; }
    .result { padding: .42rem .3rem; overflow: hidden; color: var(--muted); border: 0; border-bottom: 1px solid var(--rule); background: transparent; text-align: left; cursor: pointer; }
    .result:hover { color: var(--ink); background: rgba(112, 210, 155, .08); }
    .result b, .result small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .result small { color: var(--faint); font-size: .68rem; }
    .filter-list { display: grid; gap: .48rem; margin-top: .65rem; }
    .filter { display: grid; grid-template-columns: 14px 10px minmax(0, 1fr) auto; gap: .5rem; align-items: center; color: var(--muted); cursor: pointer; }
    .filter input { width: 14px; height: 14px; margin: 0; accent-color: var(--asserted); }
    .filter .swatch { width: 9px; height: 9px; border-radius: 50%; background: var(--swatch); }
    .filter .label { overflow: hidden; color: var(--ink); text-overflow: ellipsis; white-space: nowrap; }
    .filter small { color: var(--faint); font: 10px/1 var(--mono); }
    .authority-filter { grid-template-columns: 14px 20px minmax(0, 1fr); }
    .edge-key { width: 20px; height: 0; border-top: 2px solid var(--edge); }
    .edge-key.projection { border-top-style: dashed; } .edge-key.derived { border-top-style: dotted; }
    .hint { margin: .55rem 0 0; color: var(--faint); font-size: .72rem; }
    .render-limit { display: grid; grid-template-columns: 1fr 66px; gap: .5rem; align-items: center; margin-top: .65rem; }
    #render-limit-range { grid-column: 1 / -1; width: 100%; accent-color: var(--asserted); }
    #render-limit-number { min-height: 30px; text-align: right; font: 11px/1 var(--mono); }
    .actions { display: flex; gap: .5rem; margin-top: .75rem; }
    .action { padding: .45rem .6rem; color: var(--muted); border: 1px solid var(--rule-strong); border-radius: 4px; background: transparent; cursor: pointer; }
    .action:hover { color: var(--ink); border-color: var(--asserted); }
    .stage { position: relative; min-width: 0; min-height: 0; overflow: hidden; background: radial-gradient(circle at 50% 42%, rgba(66, 112, 95, .12), transparent 34rem); }
    #graph { display: block; width: 100%; height: 100%; cursor: grab; touch-action: none; }
    #graph.panning { cursor: grabbing; }
    .graph-tools { position: absolute; top: .7rem; right: .7rem; display: flex; overflow: hidden; border: 1px solid var(--rule-strong); border-radius: 4px; background: rgba(9, 16, 14, .92); }
    .graph-tools button { width: 38px; height: 38px; padding: 0; color: var(--muted); border: 0; border-right: 1px solid var(--rule); background: transparent; cursor: pointer; }
    .graph-tools button:last-child { border-right: 0; } .graph-tools button:hover { color: var(--ink); background: rgba(112, 210, 155, .09); }
    .legend { position: absolute; bottom: .75rem; left: .75rem; display: flex; flex-wrap: wrap; gap: .7rem; padding: .42rem .55rem; color: var(--muted); border: 1px solid var(--rule); border-radius: 4px; background: rgba(9, 16, 14, .9); font-size: .68rem; }
    .legend span { display: flex; gap: .35rem; align-items: center; } .legend i { width: 18px; border-top: 2px solid var(--edge); }
    .legend .projection i { border-top-style: dashed; } .legend .derived i { border-top-style: dotted; }
    .graph-status { position: absolute; top: .75rem; left: .75rem; padding: .38rem .5rem; color: var(--muted); border: 1px solid var(--rule); border-radius: 4px; background: rgba(9, 16, 14, .9); font: 10px/1.3 var(--mono); pointer-events: none; }
    .tooltip { position: absolute; z-index: 5; max-width: 250px; padding: .42rem .55rem; color: var(--ink); border: 1px solid var(--rule-strong); background: rgba(7, 12, 10, .97); box-shadow: 0 10px 28px rgba(0,0,0,.36); pointer-events: none; transform: translate(12px, 12px); }
    .tooltip small { display: block; color: var(--faint); } .tooltip[hidden] { display: none; }
    .empty { margin-top: 1.3rem; color: var(--muted); } .empty b { display: block; margin-bottom: .4rem; color: var(--ink); font: 500 1.15rem/1.2 var(--serif); }
    .inspector-view[hidden], .empty[hidden] { display: none; }
    .kicker { margin: 1rem 0 .25rem; color: var(--asserted); font: 10px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; }
    .inspector-title { margin: 0 0 .8rem; font: 500 1.25rem/1.2 var(--serif); overflow-wrap: anywhere; }
    .badge { display: inline-block; margin: 0 .3rem .3rem 0; padding: .2rem .42rem; color: var(--muted); border: 1px solid var(--rule-strong); border-radius: 999px; font-size: .66rem; }
    .badge.asserted { color: var(--asserted); } .badge.projection { color: var(--projection); } .badge.derived { color: var(--derived); }
    .facts { display: grid; grid-template-columns: 5.2rem minmax(0, 1fr); gap: .42rem .65rem; margin: .8rem 0; }
    .facts dt { color: var(--faint); font-size: .7rem; } .facts dd { margin: 0; overflow-wrap: anywhere; color: var(--muted); }
    .iri, pre { color: var(--muted); font: 10px/1.45 var(--mono); overflow-wrap: anywhere; white-space: pre-wrap; }
    details { margin-top: .6rem; border-top: 1px solid var(--rule); padding-top: .55rem; } details summary { color: var(--muted); cursor: pointer; }
    .relation-brief { margin-top: .75rem; border-top: 1px solid var(--rule-strong); }
    .brief-block { padding: .68rem 0; border-bottom: 1px solid var(--rule); }
    .brief-block h4, .supporting h4 { margin: 0 0 .32rem; color: var(--faint); font-size: .65rem; letter-spacing: .1em; text-transform: uppercase; }
    .brief-block p { margin: 0; color: var(--muted); line-height: 1.5; }
    .brief-block .brief-lead { color: var(--ink); font: 500 1rem/1.42 var(--serif); }
    .supporting { padding: .78rem 0 .15rem; border-bottom: 1px solid var(--rule); }
    .supporting-intro { margin: 0 0 .55rem; color: var(--muted); font-size: .75rem; line-height: 1.45; }
    .support-list { display: grid; }
    .support-link { width: 100%; padding: .62rem 0; color: var(--muted); border: 0; border-top: 1px solid var(--rule); background: transparent; text-align: left; cursor: pointer; }
    .support-link:hover { color: var(--ink); }
    .support-link b, .support-link span, .support-link small { display: block; }
    .support-link b { color: var(--ink); font-weight: 600; line-height: 1.35; }
    .support-link span { margin-top: .2rem; line-height: 1.42; }
    .support-link small { margin-top: .28rem; color: var(--faint); font: 10px/1.4 var(--mono); }
    .evidence-list { display: grid; }
    .evidence-row { padding: .62rem 0; border-top: 1px solid var(--rule); }
    .evidence-row:first-child { border-top: 0; }
    .evidence-row b { display: block; color: var(--ink); font-size: .78rem; }
    .evidence-row p { margin: .22rem 0 0; color: var(--muted); font-size: .74rem; line-height: 1.45; }
    .inspector-back { margin: .65rem 0 .2rem; padding: .3rem 0; color: var(--asserted); border: 0; background: transparent; cursor: pointer; }
    .inspector-back:hover { color: var(--ink); }
    details.technical { margin-top: .75rem; }
    details.technical summary { color: var(--faint); font-size: .7rem; }
    .connections { display: grid; gap: .35rem; margin-top: .6rem; }
    .connection { width: 100%; padding: .45rem .5rem; color: var(--muted); border: 0; border-left: 2px solid var(--edge); background: rgba(255,255,255,.025); text-align: left; cursor: pointer; }
    .connection:hover { color: var(--ink); background: rgba(255,255,255,.055); }
    .connection small { display: block; margin-top: .2rem; color: var(--faint); font: 10px/1.35 var(--mono); }
    .footer { display: flex; justify-content: space-between; gap: 1rem; align-items: center; padding: 0 1rem; overflow: hidden; color: var(--faint); border-top: 1px solid var(--rule); background: #080e0c; font: 10px/1 var(--mono); }
    .footer span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    @media (max-width: 1000px) { .workspace { grid-template-columns: 238px minmax(0,1fr); } .inspector { position: absolute; z-index: 8; top: 68px; right: 0; bottom: 34px; width: min(340px, 86vw); box-shadow: -12px 0 38px rgba(0,0,0,.4); } }
    @media (max-width: 680px) { .workspace { grid-template-columns: 1fr; } .controls { position: absolute; z-index: 7; top: 68px; bottom: 34px; left: 0; width: min(272px, 88vw); } .metrics .metric:not(:last-child) { display: none; } }
    @media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
  </style>
</head>
<body>
<div class="shell">
  <header class="appbar">
    <div><span class="eyebrow">RefSpec Atlas 3 · graph authority explorer</span><h1>@@title</h1></div>
    <div class="metrics" aria-label="Atlas totals">
      <div class="metric"><b id="metric-resources">—</b><span>resources</span></div>
      <div class="metric"><b id="metric-asserted">—</b><span>asserted</span></div>
      <div class="metric"><b id="metric-derived">—</b><span>derived</span></div>
    </div>
  </header>
  <main class="workspace">
    <aside class="panel controls" id="controls" aria-label="Graph controls">
      <h2>Explore the graph</h2>
      <section class="control-section">
        <h3>Search</h3><div class="search-wrap"><input id="search" type="search" autocomplete="off" placeholder="English label, notation, or IRI" aria-label="Search Atlas resources"><span class="key">/</span></div>
        <div class="results" id="search-results" aria-live="polite"></div>
      </section>
      <section class="control-section"><h3>Authority layers</h3><div class="filter-list">
        <label class="filter authority-filter"><input id="authority-asserted" type="checkbox" checked><span class="edge-key" style="--edge:var(--asserted)"></span><span class="label">Asserted</span></label>
        <label class="filter authority-filter"><input id="authority-projection" type="checkbox"><span class="edge-key projection" style="--edge:var(--projection)"></span><span class="label">Projection</span></label>
        <label class="filter authority-filter"><input id="authority-derived" type="checkbox" checked><span class="edge-key derived" style="--edge:var(--derived)"></span><span class="label">Derived</span></label>
        <label class="filter authority-filter"><input id="show-source-assignments" type="checkbox"><span class="edge-key" style="--edge:#8b9792"></span><span class="label">Source assignments</span></label>
      </div><p class="hint">Projection duplicates and source assignments stay hidden until requested.</p></section>
      <section class="control-section"><h3>Semantic ring</h3><select id="ring-filter" aria-label="Filter semantic ring"><option value="">All rings</option></select></section>
      <section class="control-section"><h3>Atlas releases</h3><div class="filter-list" id="release-filters"></div></section>
      <section class="control-section"><h3>Relation predicate</h3><select id="predicate-filter" aria-label="Filter relation predicate"><option value="">All predicates</option></select></section>
      <section class="control-section"><h3>Rendered resources</h3><div class="render-limit"><span id="render-limit-label">—</span><input id="render-limit-number" type="number" min="1"><input id="render-limit-range" type="range" min="1"></div>
        <p class="hint">Search matches and high-degree resources enter the graph first.</p><div class="actions"><button class="action" id="reset-view" type="button">Reset</button><button class="action" id="fit-view" type="button">Fit graph</button></div></section>
    </aside>
    <section class="stage" id="stage" aria-label="Atlas relation graph">
      <canvas id="graph" tabindex="0" aria-label="Interactive Atlas 3 relation graph"></canvas>
      <div class="graph-status" id="graph-status">Preparing graph…</div>
      <div class="graph-tools"><button id="zoom-in" type="button" aria-label="Zoom in">+</button><button id="zoom-out" type="button" aria-label="Zoom out">−</button><button id="fit-canvas" type="button" aria-label="Fit graph to view">⌂</button></div>
      <div class="legend" aria-label="Relation authority legend"><span style="--edge:var(--asserted)"><i></i>Asserted</span><span class="projection" style="--edge:var(--projection)"><i></i>Projection</span><span class="derived" style="--edge:var(--derived)"><i></i>Derived</span></div>
      <div class="tooltip" id="tooltip" hidden></div>
    </section>
    <aside class="panel inspector" id="inspector" aria-label="Provenance inspector"><h2>Provenance inspector</h2><div class="empty" id="empty-inspector"><b>Select a resource or relation</b>Click a node or relation.</div><div class="inspector-view" id="inspector-view" hidden></div></aside>
  </main>
  <footer class="footer"><span id="distribution-id"></span><span id="manifest-digest"></span></footer>
</div>
<script id="atlas-data" type="application/json">@@atlas_data</script>
<script>
(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("atlas-data").textContent);
  const canvas = document.getElementById("graph");
  const stage = document.getElementById("stage");
  const ctx = canvas.getContext("2d", {alpha:true});
  const tooltip = document.getElementById("tooltip");
  const search = document.getElementById("search");
  const searchResults = document.getElementById("search-results");
  const ringFilter = document.getElementById("ring-filter");
  const predicateFilter = document.getElementById("predicate-filter");
  const releaseColors = ["#78c7b6","#d8ad62","#83aee1","#d38fae","#9fca72","#c596e5","#e28b6f","#72c5d8"];
  const layerColors = {asserted:"#70d29b", projection:"#68a9ff", derived:"#e7ad55"};
  const sourceById = new Map(data.sourceRecords.map(row => [row.id, row]));
  const sourceReleaseById = new Map(data.sourceReleases.map(row => [row.id, row]));
  const releaseById = new Map(data.atlasReleases.map((row,index) => [row.id, {...row, color:releaseColors[index%releaseColors.length]}]));
  const nodeById = new Map();
  const assertedById = new Map(data.assertedRelations.map(row => [row.id,row]));
  const allEdges = [];
  const state = {width:1,height:1,dpr:1,view:{x:0,y:0,k:1},activeReleases:new Set(releaseById.keys()),layers:{asserted:true,projection:false,derived:true},showAssignments:false,ring:"",predicate:"",renderLimit:1,renderedNodes:[],renderedEdges:[],matches:new Set(),query:"",selected:null,inspectorReturn:null,hover:null,panning:false,drag:null,animation:null};
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const short = value => { const text=String(value); const hash=text.lastIndexOf("#"); return hash>=0?text.slice(hash+1):text.replace(/\/$/,"").split(/[/:]/).pop(); };
  const format = value => new Intl.NumberFormat("en-US").format(value);
  const hash = value => { let result=2166136261; for(const char of String(value)){result^=char.codePointAt(0);result=Math.imul(result,16777619);} return result>>>0; };
  const searchText = node => [node.label,node.id,node.release,...node.rings,...(node.detail?.labels||[]).map(row=>row.value),...(node.detail?.notations||[])].join(" ").toLocaleLowerCase("en-US");
  function ensureNode(id,label,release="",ring="",detail=null,isSource=false){let node=nodeById.get(id);if(!node){node={id,label:label||short(id),release,ring,rings:new Set(ring?[ring]:[]),detail,isSource,x:0,y:0,tx:0,ty:0,degree:0};nodeById.set(id,node);}else{if(!node.release&&release)node.release=release;if(ring){node.rings.add(ring);if(!node.ring)node.ring=ring;}if(detail)node.detail=detail;}return node;}
  data.resourceIndex.forEach(row=>ensureNode(row.id,row.displayLabel,row.release,row.semanticRing,null,false));
  data.resources.forEach(row=>ensureNode(row.id,row.displayLabel,row.release,row.semanticRing,row,false));
  function edgeFrom(row,layer){const sourceRelease=row.sourceRelease||"";const targetRelease=row.targetRelease||"";ensureNode(row.subject,row.subjectLabel,sourceRelease,row.semanticRing,null,row.kind==="sourceAssignment");ensureNode(row.object,row.objectLabel,targetRelease,row.semanticRing);return {...row,layer,color:layerColors[layer]};}
  data.assertedRelations.forEach(row=>allEdges.push(edgeFrom(row,"asserted")));
  data.projectedRelations.forEach(row=>allEdges.push(edgeFrom(row,"projection")));
  data.derivedRelations.forEach(row=>allEdges.push(edgeFrom(row,"derived")));
  const nodes=[...nodeById.values()];
  const ringLabels={subject:"Subject",entity:"Entity",value:"Value",legalIdentity:"Legal identity"};
  const rings=[...new Set(nodes.flatMap(node=>[...node.rings]))].sort((a,b)=>(ringLabels[a]||a).localeCompare(ringLabels[b]||b,"en"));
  rings.forEach(value=>{const option=document.createElement("option");option.value=value;option.textContent=ringLabels[value]||value;ringFilter.append(option);});
  const predicates=[...new Map(allEdges.map(edge=>[edge.predicate,edge.predicateLabel])).entries()].sort((a,b)=>a[1].localeCompare(b[1],"en"));
  predicates.forEach(([value,label])=>{const option=document.createElement("option");option.value=value;option.textContent=label;predicateFilter.append(option);});
  const maxLimit=Math.max(1,nodes.filter(node=>!node.isSource).length);state.renderLimit=Math.min(900,maxLimit);
  const range=document.getElementById("render-limit-range"), number=document.getElementById("render-limit-number");range.max=number.max=String(maxLimit);range.value=number.value=String(state.renderLimit);
  function releaseLabel(row){return row.title||row.identifier||short(row.id);}
  function renderReleaseFilters(){const root=document.getElementById("release-filters");root.replaceChildren();releaseById.forEach(row=>{const label=document.createElement("label");label.className="filter";label.innerHTML=`<input type="checkbox" checked data-release="${esc(row.id)}"><span class="swatch" style="--swatch:${row.color}"></span><span class="label">${esc(releaseLabel(row))}</span><small>${format(row.memberCount||0)}</small>`;root.append(label);});root.querySelectorAll("input").forEach(input=>input.addEventListener("change",()=>{input.checked?state.activeReleases.add(input.dataset.release):state.activeReleases.delete(input.dataset.release);refresh(true);}));}
  function layerEnabled(edge){if(edge.layer==="asserted"&&!state.layers.asserted)return false;if(edge.layer==="projection"&&!state.layers.projection)return false;if(edge.layer==="derived"&&!state.layers.derived)return false;if(edge.kind==="sourceAssignment"&&!state.showAssignments)return false;if(state.ring&&edge.semanticRing!==state.ring)return false;return !state.predicate||edge.predicate===state.predicate;}
  function releaseEnabled(node){return !node.release||!releaseById.has(node.release)||state.activeReleases.has(node.release);}
  function computeGraph(){nodes.forEach(node=>{node.degree=0;});const eligibleEdges=allEdges.filter(edge=>{if(!layerEnabled(edge))return false;const source=nodeById.get(edge.subject),target=nodeById.get(edge.object);if(!source||!target||!releaseEnabled(source)||!releaseEnabled(target))return false;source.degree++;target.degree++;return true;});const selectedNeighbors=selectedNodeNeighborIds(state.selected,eligibleEdges);const candidates=nodes.filter(node=>(!state.ring||node.rings.has(state.ring))&&releaseEnabled(node)&&(!node.isSource||state.showAssignments));candidates.sort((a,b)=>(state.matches.has(b.id)?1:0)-(state.matches.has(a.id)?1:0)||(state.selected?.kind==="node"&&state.selected.id===b.id?1:0)-(state.selected?.kind==="node"&&state.selected.id===a.id?1:0)||(selectedNeighbors.has(b.id)?1:0)-(selectedNeighbors.has(a.id)?1:0)||b.degree-a.degree||a.label.localeCompare(b.label,"en")||a.id.localeCompare(b.id));state.renderedNodes=candidates.slice(0,state.renderLimit);const ids=new Set(state.renderedNodes.map(node=>node.id));state.renderedEdges=eligibleEdges.filter(edge=>ids.has(edge.subject)&&ids.has(edge.object));}
  function layout(animate=true){const groups=new Map();state.renderedNodes.forEach(node=>{const key=node.release||"unreleased";if(!groups.has(key))groups.set(key,[]);groups.get(key).push(node);});const ordered=[...groups.entries()].sort((a,b)=>a[0].localeCompare(b[0]));const orbit=Math.max(220,Math.sqrt(state.renderedNodes.length)*28);const golden=2.399963229728653;ordered.forEach(([key,group],groupIndex)=>{group.sort((a,b)=>b.degree-a.degree||a.id.localeCompare(b.id));const angle=(Math.PI*2*groupIndex/Math.max(1,ordered.length))+((hash(key)%1000)/1000)*.3;const cx=ordered.length===1?0:Math.cos(angle)*orbit,cy=ordered.length===1?0:Math.sin(angle)*orbit;group.forEach((node,index)=>{const theta=index*golden+(hash(node.id)%628)/100;const radius=18*Math.sqrt(index);node.sx=Number.isFinite(node.x)?node.x:cx;node.sy=Number.isFinite(node.y)?node.y:cy;node.tx=cx+Math.cos(theta)*radius;node.ty=cy+Math.sin(theta)*radius;});});if(!animate||matchMedia("(prefers-reduced-motion: reduce)").matches){state.renderedNodes.forEach(node=>{node.x=node.tx;node.y=node.ty;});draw();return;}const started=performance.now();if(state.animation)cancelAnimationFrame(state.animation);const tick=now=>{const t=Math.min(1,(now-started)/360),ease=1-Math.pow(1-t,3);state.renderedNodes.forEach(node=>{node.x=node.sx+(node.tx-node.sx)*ease;node.y=node.sy+(node.ty-node.sy)*ease;});draw();if(t<1)state.animation=requestAnimationFrame(tick);};state.animation=requestAnimationFrame(tick);}
  function bounds(){if(!state.renderedNodes.length)return{minX:-1,maxX:1,minY:-1,maxY:1};return{minX:Math.min(...state.renderedNodes.map(n=>n.x)),maxX:Math.max(...state.renderedNodes.map(n=>n.x)),minY:Math.min(...state.renderedNodes.map(n=>n.y)),maxY:Math.max(...state.renderedNodes.map(n=>n.y))};}
  function fitView(){const box=bounds(),padding=80,width=Math.max(1,box.maxX-box.minX),height=Math.max(1,box.maxY-box.minY);state.view.k=Math.max(.08,Math.min(2.8,Math.min((state.width-padding*2)/width,(state.height-padding*2)/height)));state.view.x=state.width/2-(box.minX+box.maxX)/2*state.view.k;state.view.y=state.height/2-(box.minY+box.maxY)/2*state.view.k;draw();}
  function refresh(fit=false,animate=true){computeGraph();layout(animate);renderInspector();document.getElementById("graph-status").textContent=`${format(state.renderedNodes.length)} nodes · ${format(state.renderedEdges.length)} relations`;document.getElementById("render-limit-label").textContent=`${format(state.renderLimit)} of ${format(maxLimit)}`;if(fit)setTimeout(fitView,380);}
  function relationSelected(edge){return state.selected?.kind==="edge"&&state.selected.id===edge.id&&state.selected.layer===edge.layer;}
  function nodeConnected(node,edge){return edge.subject===node.id||edge.object===node.id;}
  /* atlas-selected-node-neighbors:start */
  function selectedNodeNeighborIds(selection,edges){const neighbors=new Set();if(selection?.kind!=="node")return neighbors;neighbors.add(selection.id);edges.forEach(edge=>{if(edge.subject===selection.id)neighbors.add(edge.object);else if(edge.object===selection.id)neighbors.add(edge.subject);});return neighbors;}
  /* atlas-selected-node-neighbors:end */
  function drawArrow(source,target,color,alpha,lineWidth){const angle=Math.atan2(target.y-source.y,target.x-source.x),radius=8/state.view.k,tipX=target.x-Math.cos(angle)*radius,tipY=target.y-Math.sin(angle)*radius,len=7/state.view.k,w=3.5/state.view.k;ctx.beginPath();ctx.moveTo(tipX,tipY);ctx.lineTo(tipX-Math.cos(angle)*len+Math.sin(angle)*w,tipY-Math.sin(angle)*len-Math.cos(angle)*w);ctx.lineTo(tipX-Math.cos(angle)*len-Math.sin(angle)*w,tipY-Math.sin(angle)*len+Math.cos(angle)*w);ctx.closePath();ctx.globalAlpha=alpha;ctx.fillStyle=color;ctx.fill();ctx.globalAlpha=1;}
  function drawEdge(edge){const source=nodeById.get(edge.subject),target=nodeById.get(edge.object);if(!source||!target)return;const selected=relationSelected(edge),near=state.selected?.kind==="node"&&(nodeConnected(nodeById.get(state.selected.id),edge)),dim=state.selected&&!selected&&!near;const alpha=selected?.98:near?.82:dim?.08:edge.layer==="projection"?.3:.42;const offset=edge.layer==="projection"?3/state.view.k:0,dx=target.x-source.x,dy=target.y-source.y,length=Math.max(1,Math.hypot(dx,dy)),ox=-dy/length*offset,oy=dx/length*offset;ctx.beginPath();ctx.moveTo(source.x+ox,source.y+oy);ctx.lineTo(target.x+ox,target.y+oy);ctx.strokeStyle=edge.kind==="sourceAssignment"?"#8b9792":edge.color;ctx.globalAlpha=alpha;ctx.lineWidth=(selected?2.8:edge.layer==="asserted"?1.35:1.6)/state.view.k;ctx.setLineDash(edge.layer==="projection"?[7/state.view.k,5/state.view.k]:edge.layer==="derived"?[2/state.view.k,4/state.view.k]:[]);ctx.stroke();ctx.setLineDash([]);ctx.globalAlpha=1;drawArrow({x:source.x+ox,y:source.y+oy},{x:target.x+ox,y:target.y+oy},edge.kind==="sourceAssignment"?"#8b9792":edge.color,alpha,ctx.lineWidth);}
  function nodeColor(node){return releaseById.get(node.release)?.color||"#a8b8b1";}
  function drawNode(node,selectedNeighbors){const selected=state.selected?.kind==="node"&&state.selected.id===node.id,hovered=state.hover===node.id,connected=state.selected?.kind==="edge"&&(state.selected.edge.subject===node.id||state.selected.edge.object===node.id),dim=state.selected&&!selected&&!connected&&!selectedNeighbors.has(node.id);ctx.globalAlpha=dim?.18:1;const radius=(selected?8:node.degree>8?6.5:5)/state.view.k;if(selected||hovered){ctx.beginPath();ctx.arc(node.x,node.y,radius+5/state.view.k,0,Math.PI*2);ctx.fillStyle=selected?"rgba(112,210,155,.2)":"rgba(153,221,208,.14)";ctx.fill();}ctx.beginPath();if(node.isSource){ctx.rect(node.x-radius,node.y-radius,radius*2,radius*2);}else{ctx.arc(node.x,node.y,radius,0,Math.PI*2);}ctx.fillStyle=nodeColor(node);ctx.fill();ctx.strokeStyle=selected?"#fff":"rgba(4,8,7,.85)";ctx.lineWidth=(selected?2:1)/state.view.k;ctx.stroke();ctx.globalAlpha=1;if(selected||hovered||state.matches.has(node.id)||(state.view.k>1.15&&state.renderedNodes.length<260)){ctx.font=`${11/state.view.k}px ui-sans-serif,system-ui`;ctx.textBaseline="middle";const x=node.x+radius+5/state.view.k,width=ctx.measureText(node.label).width;ctx.fillStyle="rgba(5,10,8,.88)";ctx.fillRect(x-2/state.view.k,node.y-8/state.view.k,width+4/state.view.k,16/state.view.k);ctx.fillStyle=nodeColor(node);ctx.fillText(node.label,x,node.y);}}
  function draw(){const selectedNeighbors=selectedNodeNeighborIds(state.selected,state.renderedEdges);ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,canvas.width,canvas.height);ctx.setTransform(state.dpr*state.view.k,0,0,state.dpr*state.view.k,state.dpr*state.view.x,state.dpr*state.view.y);state.renderedEdges.filter(edge=>!relationSelected(edge)).forEach(drawEdge);state.renderedEdges.filter(relationSelected).forEach(drawEdge);state.renderedNodes.filter(node=>state.selected?.id!==node.id).forEach(node=>drawNode(node,selectedNeighbors));const selected=state.selected?.kind==="node"?nodeById.get(state.selected.id):null;if(selected)drawNode(selected,selectedNeighbors);}
  function screenToWorld(x,y){return{x:(x-state.view.x)/state.view.k,y:(y-state.view.y)/state.view.k};}
  function hitNode(clientX,clientY){const rect=canvas.getBoundingClientRect(),point=screenToWorld(clientX-rect.left,clientY-rect.top);let best=null,distance=Infinity;state.renderedNodes.forEach(node=>{const d=Math.hypot(node.x-point.x,node.y-point.y);if(d<12/state.view.k&&d<distance){best=node;distance=d;}});return best;}
  function segmentDistance(point,a,b){const dx=b.x-a.x,dy=b.y-a.y,l2=dx*dx+dy*dy;if(!l2)return Math.hypot(point.x-a.x,point.y-a.y);const t=Math.max(0,Math.min(1,((point.x-a.x)*dx+(point.y-a.y)*dy)/l2));return Math.hypot(point.x-(a.x+t*dx),point.y-(a.y+t*dy));}
  function hitEdge(clientX,clientY){const rect=canvas.getBoundingClientRect(),point=screenToWorld(clientX-rect.left,clientY-rect.top);let best=null,distance=Infinity;state.renderedEdges.forEach(edge=>{const a=nodeById.get(edge.subject),b=nodeById.get(edge.object),d=segmentDistance(point,a,b);if(d<7/state.view.k&&d<distance){best=edge;distance=d;}});return best;}
  function zoomAt(factor,x=state.width/2,y=state.height/2){const before=screenToWorld(x,y);state.view.k=Math.max(.06,Math.min(8,state.view.k*factor));state.view.x=x-before.x*state.view.k;state.view.y=y-before.y*state.view.k;draw();}
  function sourceDetails(ids){return ids.map(id=>sourceById.get(id)).filter(Boolean);}
  function friendlySource(record){
    if(!record)return "Pinned source record";
    const token=record.nativePayload?.sourceIdentity?.namespaceToken;
    const tokenNames={"loc-lst":"Library of Congress Legislative Subject Terms","loc-cgpa":"Library of Congress Policy Areas","icpsr-subject-thesaurus":"ICPSR Subject Thesaurus"};
    if(tokenNames[token])return tokenNames[token];
    const locator=String(record.sourceLocator||"").toLocaleLowerCase("en-US");
    if(locator.includes("elsst"))return "ELSST";
    if(locator.includes("icpsr"))return "ICPSR Subject Thesaurus";
    if(locator.includes("federal-register")||locator.includes("federalregister"))return "Federal Register Thesaurus";
    if(locator.includes("congress.gov"))return "Congress.gov / CRS";
    const release=sourceReleaseById.get(record.sourceRelease);
    return release?.title||release?.identifier||short(record.sourceRelease||record.sourceLocator||"source record");
  }
  function reviewMethod(method){
    return ({
      publisherAssertion:{title:"Publisher supplied",reason:"Supplied directly by the publisher."},
      deterministicTransformation:{title:"Fixed-rule transformation",reason:"Atlas applied a fixed rule to publisher data."},
      twoMachineAdjudication:{title:"Two-model agreement",reason:"Two independent models agreed."},
      operatorAdoption:{title:"Operator adopted",reason:"An operator accepted it."},
      humanReview:{title:"Human approved",reason:"A human reviewer approved it."},
      trustedPipelineReview:{title:"Pipeline approved",reason:"A trusted pipeline approved it."}
    })[method]||{title:String(method||"Reviewed"),reason:"The review method is recorded."};
  }
  function relationMeaning(edge){
    const subject=edge.subjectLabel, object=edge.objectLabel;
    if(edge.kind==="sourceAssignment")return `This source record contributed ${object}. It is provenance, not a topic relation.`;
    return ({
      broader:`${subject} is narrower than ${object}.`,
      narrower:`${object} is narrower than ${subject}.`,
      related:`${subject} ↔ ${object}: directly associated by the publisher.`,
      exactMatch:`${subject} and ${object} are exact matches across vocabularies.`,
      closeMatch:`${subject} and ${object} are similar enough for some cross-vocabulary uses.`,
      broadMatch:`${subject} maps to the broader concept ${object}.`,
      narrowMatch:`${subject} maps to the narrower concept ${object}.`,
      relatedMatch:`${subject} and ${object} are associated across vocabularies.`,
      thesaurusUse:`Use ${object}, the preferred term, instead of ${subject}.`,
      thesaurusUsedFor:`${object} is a non-preferred term for ${subject}.`,
      thesaurusRelated:`${subject} and ${object} are publisher-related despite also sharing a hierarchy.`
    })[edge.predicateLabel]||`${subject} has relation “${edge.predicateLabel}” to ${object}.`;
  }
  function relationWhy(edge){
    if(edge.layer==="projection")return `Query-friendly copy of ${format(edge.supportingAssertions.length)} assertion${edge.supportingAssertions.length===1?"":"s"}; no new claim.`;
    if(edge.layer==="derived")return `Inferred from ${format(edge.derivedFromAssertions.length)} cited assertion${edge.derivedFromAssertions.length===1?"":"s"}; not editor-approved.`;
    const evidence=edge.evidence||[];
    const sources=[...new Set(evidence.map(item=>friendlySource(sourceById.get(item.sourceRecord))))];
    const reasons=[...new Set(evidence.map(item=>reviewMethod(item.reviewMethod).reason))];
    if(edge.kind==="sourceAssignment")return `Links ${sources.join(" and ")||"a pinned source"} to its Atlas resource.`;
    return `${sources.join(" and ")||"Pinned evidence"}: ${reasons.join(" ")||"Approved source fact."}`;
  }
  function relationGuidance(edge){
    if(edge.layer==="projection")return "Use for queries; audit the supporting assertion.";
    if(edge.layer==="derived")return "Discovery only; review before publishing.";
    if(edge.status&&edge.status!=="current")return "Historical; do not use as current.";
    if(edge.kind==="sourceAssignment")return "Use for provenance only.";
    if(edge.kind==="mapping")return "Apply your local mapping policy.";
    return "";
  }
  function evidenceBrief(edge){
    if(edge.layer!=="asserted"||!edge.evidence?.length)return "";
    const rows=edge.evidence.map(item=>{const method=reviewMethod(item.reviewMethod),source=sourceById.get(item.sourceRecord),confidence=item.confidence?` · confidence ${item.confidence}`:"";return `<div class="evidence-row"><b>${esc(friendlySource(source))} · ${esc(method.title)}</b><p>${esc(item.decisionStatus)}${esc(confidence)} · digest pinned</p></div>`;}).join("");
    return `<section class="supporting"><h4>Evidence</h4><div class="evidence-list">${rows}</div></section>`;
  }
  function supportingBrief(edge){
    const ids=edge.layer==="projection"?edge.supportingAssertions:edge.layer==="derived"?edge.derivedFromAssertions:[];
    if(!ids?.length)return "";
    const rows=ids.map(id=>{const assertion=assertedById.get(id);if(!assertion)return `<div class="evidence-row"><b>Supporting assertion</b><p>${esc(id)}</p></div>`;const readable={...assertion,layer:"asserted"};const method=reviewMethod(assertion.evidence?.[0]?.reviewMethod).title;const meaning=edge.layer==="derived"?`<span>${esc(relationMeaning(readable))}</span>`:"";return `<button class="support-link" data-edge="asserted|${esc(id)}"><b>${esc(assertion.subjectLabel)} → ${esc(assertion.objectLabel)}</b>${meaning}<small>${esc(method)} · open</small></button>`;}).join("");
    return `<section class="supporting"><h4>Supporting assertions</h4><div class="support-list">${rows}</div></section>`;
  }
  function technicalRecord(edge){const record={...edge};delete record.color;delete record.layer;return record;}
  function renderInspector(){
    const empty=document.getElementById("empty-inspector"),view=document.getElementById("inspector-view");
    if(!state.selected){empty.hidden=false;view.hidden=true;return;}
    empty.hidden=true;view.hidden=false;
    if(state.selected.kind==="node"){
      const node=nodeById.get(state.selected.id),detail=node.detail,connections=state.renderedEdges.filter(edge=>nodeConnected(node,edge)).slice(0,20);
      view.innerHTML=`<p class="kicker">${node.isSource?"Source record":"Atlas resource"}</p><h3 class="inspector-title">${esc(node.label)}</h3><span class="badge">${esc(detail?.displayLabelRole||node.ring||"endpoint")}</span><h3 style="margin-top:1rem">Relations</h3><div class="connections">${connections.map(edge=>`<button class="connection" data-edge="${esc(edge.layer+"|"+edge.id)}" style="--edge:${edge.color}">${esc(relationMeaning(edge))}<small>${esc(edge.layer)} · ${esc(edge.predicateLabel)}</small></button>`).join("")||"<span class=\"hint\">No visible relations under current filters.</span>"}</div><details class="technical"><summary>About this resource</summary><dl class="facts"><dt>IRI</dt><dd class="iri">${esc(node.id)}</dd><dt>Release</dt><dd class="iri">${esc(node.release||"Not available in bounded view")}</dd>${detail?`<dt>Profile</dt><dd>${esc(detail.resourceProfile)}</dd><dt>Type</dt><dd>${esc(detail.resourceType)}</dd>`:""}</dl>${detail?`<details><summary>English labels</summary><pre>${esc(JSON.stringify(detail.labels,null,2))}</pre></details><details><summary>Source records</summary><pre>${esc(JSON.stringify(sourceDetails(detail.sourceRecords),null,2))}</pre></details>`:"<p class=\"hint\">Increase the resource limit for full details.</p>"}</details>`;
    }else{
      const edge=state.selected.edge;
      const guidance=relationGuidance(edge),back=state.inspectorReturn?`<button class="inspector-back" id="inspector-back" type="button">← ${state.inspectorReturn.selection.kind==="node"?"Back to relations":"Back"}</button>`:"";
      view.innerHTML=`${back}<p class="kicker">${esc(edge.layer)} relation</p><h3 class="inspector-title">${esc(edge.subjectLabel)} → ${esc(edge.objectLabel)}</h3><span class="badge ${esc(edge.layer)}">${esc(edge.layer)}</span><span class="badge">${esc(edge.predicateLabel)}</span><div class="relation-brief"><section class="brief-block"><h4>Meaning</h4><p class="brief-lead">${esc(relationMeaning(edge))}</p></section><section class="brief-block"><h4>Why it is here</h4><p>${esc(relationWhy(edge))}</p></section>${guidance?`<section class="brief-block"><h4>Use</h4><p>${esc(guidance)}</p></section>`:""}</div>${evidenceBrief(edge)}${supportingBrief(edge)}<details class="technical"><summary>Technical details</summary><pre>${esc(JSON.stringify(technicalRecord(edge),null,2))}</pre></details>`;
    }
    document.getElementById("inspector-back")?.addEventListener("click",()=>{const target=state.inspectorReturn;state.inspectorReturn=null;state.selected=target.selection;renderInspector();document.getElementById("inspector").scrollTop=target.scrollTop;draw();});
    view.querySelectorAll("[data-edge]").forEach(button=>button.addEventListener("click",()=>{const [layer,...rest]=button.dataset.edge.split("|");const id=rest.join("|");const edge=allEdges.find(row=>row.layer===layer&&row.id===id);if(edge){if(!state.inspectorReturn)state.inspectorReturn={selection:state.selected,scrollTop:document.getElementById("inspector").scrollTop};state.selected={kind:"edge",id:edge.id,layer:edge.layer,edge};renderInspector();document.getElementById("inspector").scrollTop=0;draw();}}));
  }
  function selectNode(node,center=false){state.inspectorReturn=null;state.selected={kind:"node",id:node.id};refresh(false,false);if(center){state.view.x=state.width/2-node.x*state.view.k;state.view.y=state.height/2-node.y*state.view.k;draw();}}
  function renderSearch(){state.query=search.value.trim().toLocaleLowerCase("en-US");state.matches=new Set(state.query?nodes.filter(node=>searchText(node).includes(state.query)).map(node=>node.id):[]);searchResults.replaceChildren();if(state.query){[...state.matches].slice(0,8).map(id=>nodeById.get(id)).forEach(node=>{const button=document.createElement("button");button.className="result";button.innerHTML=`<b>${esc(node.label)}</b><small>${esc(node.release||node.id)}</small>`;button.addEventListener("click",()=>{selectNode(node,true);searchResults.replaceChildren();});searchResults.append(button);});}refresh(false);}
  function resize(){const rect=stage.getBoundingClientRect();state.width=Math.max(1,rect.width);state.height=Math.max(1,rect.height);state.dpr=Math.min(2,devicePixelRatio||1);canvas.width=Math.round(state.width*state.dpr);canvas.height=Math.round(state.height*state.dpr);canvas.style.width=`${state.width}px`;canvas.style.height=`${state.height}px`;fitView();}
  canvas.addEventListener("pointerdown",event=>{canvas.setPointerCapture(event.pointerId);const node=hitNode(event.clientX,event.clientY);if(node){selectNode(node);return;}const edge=hitEdge(event.clientX,event.clientY);if(edge){state.inspectorReturn=null;state.selected={kind:"edge",id:edge.id,layer:edge.layer,edge};renderInspector();draw();return;}state.panning=true;state.drag={x:event.clientX,y:event.clientY,viewX:state.view.x,viewY:state.view.y};canvas.classList.add("panning");});
  canvas.addEventListener("pointermove",event=>{if(state.panning){state.view.x=state.drag.viewX+event.clientX-state.drag.x;state.view.y=state.drag.viewY+event.clientY-state.drag.y;draw();return;}const node=hitNode(event.clientX,event.clientY);state.hover=node?.id||null;if(node){const rect=stage.getBoundingClientRect();tooltip.innerHTML=`${esc(node.label)}<small>${esc(node.release||node.id)}</small>`;tooltip.style.left=`${event.clientX-rect.left}px`;tooltip.style.top=`${event.clientY-rect.top}px`;tooltip.hidden=false;}else tooltip.hidden=true;draw();});
  canvas.addEventListener("pointerup",event=>{if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);state.panning=false;state.drag=null;canvas.classList.remove("panning");});canvas.addEventListener("pointerleave",()=>{state.hover=null;tooltip.hidden=true;draw();});
  canvas.addEventListener("wheel",event=>{event.preventDefault();const rect=canvas.getBoundingClientRect();zoomAt(event.deltaY<0?1.12:.89,event.clientX-rect.left,event.clientY-rect.top);},{passive:false});
  canvas.addEventListener("keydown",event=>{if(event.key==="+"||event.key==="=")zoomAt(1.2);else if(event.key==="-")zoomAt(.83);else if(event.key==="ArrowLeft")state.view.x+=32;else if(event.key==="ArrowRight")state.view.x-=32;else if(event.key==="ArrowUp")state.view.y+=32;else if(event.key==="ArrowDown")state.view.y-=32;else return;event.preventDefault();draw();});
  document.getElementById("authority-asserted").addEventListener("change",event=>{state.layers.asserted=event.currentTarget.checked;refresh(false);});document.getElementById("authority-projection").addEventListener("change",event=>{state.layers.projection=event.currentTarget.checked;refresh(false);});document.getElementById("authority-derived").addEventListener("change",event=>{state.layers.derived=event.currentTarget.checked;refresh(false);});document.getElementById("show-source-assignments").addEventListener("change",event=>{state.showAssignments=event.currentTarget.checked;refresh(false);});
  ringFilter.addEventListener("change",event=>{state.ring=event.currentTarget.value;state.selected=null;state.inspectorReturn=null;refresh(true);});predicateFilter.addEventListener("change",event=>{state.predicate=event.currentTarget.value;refresh(true);});search.addEventListener("input",renderSearch);window.addEventListener("keydown",event=>{if(event.key==="/"&&document.activeElement!==search){event.preventDefault();search.focus();}if(event.key==="Escape"){state.inspectorReturn=null;state.selected=null;search.value="";renderSearch();}});
  function setLimit(value){state.renderLimit=Math.max(1,Math.min(maxLimit,Number(value)||1));range.value=number.value=String(state.renderLimit);refresh(true);}range.addEventListener("input",event=>setLimit(event.currentTarget.value));number.addEventListener("change",event=>setLimit(event.currentTarget.value));
  function reset(){state.activeReleases=new Set(releaseById.keys());state.layers={asserted:true,projection:false,derived:true};state.showAssignments=false;state.ring="";state.predicate="";state.selected=null;state.inspectorReturn=null;state.query="";state.matches.clear();search.value="";ringFilter.value="";predicateFilter.value="";document.getElementById("authority-asserted").checked=true;document.getElementById("authority-projection").checked=false;document.getElementById("authority-derived").checked=true;document.getElementById("show-source-assignments").checked=false;document.querySelectorAll("[data-release]").forEach(input=>{input.checked=true;});refresh(true);}
  document.getElementById("reset-view").addEventListener("click",reset);document.getElementById("fit-view").addEventListener("click",fitView);document.getElementById("fit-canvas").addEventListener("click",fitView);document.getElementById("zoom-in").addEventListener("click",()=>zoomAt(1.25));document.getElementById("zoom-out").addEventListener("click",()=>zoomAt(.8));new ResizeObserver(resize).observe(stage);
  document.getElementById("metric-resources").textContent=format(data.summary.availableResources);document.getElementById("metric-asserted").textContent=format(data.summary.availableAssertedRelations);document.getElementById("metric-derived").textContent=format(data.summary.availableDerivedRelations);document.getElementById("distribution-id").textContent=data.distribution.id;document.getElementById("manifest-digest").textContent=data.distribution.manifestDigest;
  renderReleaseFilters();refresh(false);resize();
})();
</script>
</body>
</html>
"""


def render_atlas_v3_explorer(model: Mapping[str, Any]) -> str:
    """Render one self-contained Atlas 3.0 explorer."""

    if not isinstance(model, Mapping):
        raise Atlas3ExplorerError("Atlas 3.0 explorer must be an object")
    _validate_model(model)
    return _Atlas3Template(_GRAPH_HTML).substitute(
        title=html.escape(cast(str, model["title"]), quote=True),
        atlas_data=_safe_json(model),
    )


def render_atlas_explorer(model: Mapping[str, Any]) -> str:
    """Render Atlas 3.0; the unversioned name no longer accepts Atlas 2 models."""

    return render_atlas_v3_explorer(model)


__all__ = [
    "ATLAS_V3_EXPLORER_SCHEMA_VERSION",
    "ATLAS_V3_EXPLORER_TYPE",
    "EXPLORER_FILTER_SEMANTICS",
    "EXPLORER_SCHEMA_VERSION",
    "EXPLORER_TYPE",
    "PLANNING_FILTER_SEMANTICS",
    "Atlas3ExplorerDistribution",
    "Atlas3ExplorerError",
    "AtlasExplorerError",
    "atlas_v3_predicate_meaning",
    "build_atlas_v3_explorer_model",
    "open_atlas_v3_explorer_distribution",
    "render_atlas_explorer",
    "render_atlas_v3_explorer",
]
