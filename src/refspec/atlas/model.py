"""Verified vocabulary-release inputs and immutable atlas artifacts."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from rdflib import BNode, Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import PROV, RDF, SKOS

from ..canonical import (
    CanonicalValueError,
    canonical_digest,
    canonical_json_bytes,
    validate_stable_record,
    validate_vocabulary_release_identity,
)
from ..reference_resource import (
    reference_release_node,
    validate_reference_resource_release,
)

ATLAS_FORMAT_VERSION = "refspec-vocabulary-atlas/v1"
CROSSWALK_INPUT_VERSION = "refspec-crosswalk-input-v1"
ATLAS_GENERATION_POLICY = "refspec-vocabulary-atlas-generation-v1"
CROSSWALK_SELECTION_POLICY = "refspec-crosswalk-search-only-selection-v1"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>]+$")
_ATLAS = Namespace("https://refspec.org/ns/vocabulary-atlas#")
_RKAF = Namespace("https://rulespec.org/ns/v1#")
_REQUIRED_RELEASE_FIELDS = {
    "schema_version",
    "release_id",
    "release_digest",
    "vocabulary",
    "reference_resource_release",
    "concepts",
    "labels",
    "hierarchy",
    "mappings",
    "redirects",
}


class VocabularyAtlasError(ValueError):
    """An input or projection cannot form a safe vocabulary atlas."""


def sha256_bytes(payload: bytes) -> str:
    """Return the lowercase prefixed SHA-256 digest of exact bytes."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def atlas_implementation_pin() -> dict[str, Any]:
    """Identify the exact implementation and runtime that determine atlas bytes."""

    package_root = Path(__file__).resolve().parents[1]
    source_modules = (
        ("refspec/atlas/model.py", package_root / "atlas" / "model.py"),
        ("refspec/atlas/crosswalk.py", package_root / "atlas" / "crosswalk.py"),
        ("refspec/canonical.py", package_root / "canonical.py"),
        ("refspec/reference_resource.py", package_root / "reference_resource.py"),
        ("refspec/rulespec_core.py", package_root / "rulespec_core.py"),
    )
    validation_artifacts = (
        (
            "refspec/fixtures/rulespec-core-release-m2.json",
            package_root / "fixtures" / "rulespec-core-release-m2.json",
        ),
        (
            "refspec/fixtures/rulespec-reference-resource-release.schema.json",
            package_root
            / "fixtures"
            / "rulespec-reference-resource-release.schema.json",
        ),
        (
            "refspec/fixtures/rulespec-reference-resource-release-digest-positive.jsonld",
            package_root
            / "fixtures"
            / "rulespec-reference-resource-release-digest-positive.jsonld",
        ),
    )
    pinned_sources: list[dict[str, str]] = []
    for relative_path, path in source_modules:
        if path.is_symlink() or not path.is_file():
            raise VocabularyAtlasError(
                f"atlas implementation source is unavailable: {relative_path}"
            )
        pinned_sources.append(
            {"path": relative_path, "sha256": sha256_bytes(path.read_bytes())}
        )
    pinned_artifacts: list[dict[str, str]] = []
    for relative_path, path in validation_artifacts:
        if path.is_symlink() or not path.is_file():
            raise VocabularyAtlasError(
                f"atlas validation artifact is unavailable: {relative_path}"
            )
        pinned_artifacts.append(
            {"path": relative_path, "sha256": sha256_bytes(path.read_bytes())}
        )
    return {
        "sourceModules": pinned_sources,
        "validationArtifacts": pinned_artifacts,
        "runtime": {
            "pythonRequirement": ">=3.11",
            "rdflibVersion": importlib.metadata.version("rdflib"),
        },
    }


def _absolute_iri(value: object, label: str) -> str:
    text = str(value or "")
    if _ABSOLUTE_IRI.fullmatch(text) is None:
        raise VocabularyAtlasError(f"{label} must be an absolute IRI: {text!r}")
    return text


def _json_object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VocabularyAtlasError(f"{label} must be a JSON object")
    return value


def _json_array(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise VocabularyAtlasError(f"{label} must be a JSON array")
    return value


def _strict_json(payload: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise VocabularyAtlasError(f"{label} repeats JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise VocabularyAtlasError(f"{label} contains non-finite number {value}")

    try:
        return json.loads(
            payload,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VocabularyAtlasError(f"{label} is not valid UTF-8 JSON") from error


def validate_vocabulary_release_input(record: Mapping[str, Any]) -> None:
    """Validate the generic release fields used by the static atlas.

    The active RefSpec release validator currently contains additional checks
    specific to its Federal Register conformance slice. The atlas needs a
    source-neutral reader, so this function validates the canonical release
    identity, exact reference membership, and every nested vocabulary record it
    consumes without weakening the release's own validator.
    """

    missing = _REQUIRED_RELEASE_FIELDS - set(record)
    if missing:
        raise VocabularyAtlasError(
            f"VocabularyRelease lacks atlas fields: {sorted(missing)!r}"
        )
    if record.get("schema_version") != "refspec-vocabulary-release-v1":
        raise VocabularyAtlasError("unsupported VocabularyRelease schema_version")
    try:
        validate_vocabulary_release_identity(record)
    except CanonicalValueError as error:
        raise VocabularyAtlasError(str(error)) from error

    vocabulary = _json_object(record["vocabulary"], "vocabulary")
    scheme_id = _absolute_iri(vocabulary.get("scheme_id"), "vocabulary scheme_id")
    version = str(vocabulary.get("version") or "").strip()
    if not version:
        raise VocabularyAtlasError("vocabulary version is required")

    concepts = _json_array(record["concepts"], "concepts")
    if not concepts:
        raise VocabularyAtlasError("VocabularyRelease must contain concepts")
    concept_ids: set[str] = set()
    for value in concepts:
        concept = _json_object(value, "concept")
        concept_id = _absolute_iri(concept.get("concept_id"), "concept_id")
        if concept_id in concept_ids:
            raise VocabularyAtlasError(f"duplicate concept_id: {concept_id}")
        concept_ids.add(concept_id)
        if concept.get("scheme_id") != scheme_id:
            raise VocabularyAtlasError(
                f"concept {concept_id} does not belong to release scheme {scheme_id}"
            )
        actual_digest = concept.get("concept_digest")
        expected_digest = canonical_digest(
            concept,
            omit_root_fields=("concept_digest",),
        )
        if actual_digest != expected_digest:
            raise VocabularyAtlasError(
                f"concept_digest does not match concept {concept_id}"
            )

    labels = _json_array(record["labels"], "labels")
    label_ids: set[str] = set()
    preferred_by_concept: dict[str, int] = {identifier: 0 for identifier in concept_ids}
    for value in labels:
        label = _json_object(value, "label")
        try:
            validate_stable_record(
                label,
                id_field="label_id",
                digest_field="label_digest",
                id_prefix="urn:refspec:label:",
            )
        except CanonicalValueError as error:
            raise VocabularyAtlasError(str(error)) from error
        label_id = str(label["label_id"])
        if label_id in label_ids:
            raise VocabularyAtlasError(f"duplicate label_id: {label_id}")
        label_ids.add(label_id)
        concept_id = str(label.get("concept_id") or "")
        if concept_id not in concept_ids:
            raise VocabularyAtlasError(
                f"label {label_id} names a concept outside its release"
            )
        text = str(label.get("label") or "").strip()
        language = str(label.get("language") or "").strip()
        if not text or not language:
            raise VocabularyAtlasError(f"label {label_id} needs text and language")
        if label.get("label_kind") == "preferred":
            preferred_by_concept[concept_id] += 1
    if any(count != 1 for count in preferred_by_concept.values()):
        raise VocabularyAtlasError(
            "every released concept must have exactly one preferred label record"
        )

    for collection in ("hierarchy", "mappings", "redirects"):
        _json_array(record[collection], collection)
    for value in record["redirects"]:
        redirect = _json_object(value, "redirect")
        try:
            validate_stable_record(
                redirect,
                id_field="redirect_id",
                digest_field="redirect_digest",
                id_prefix="urn:refspec:redirect:",
            )
        except CanonicalValueError as error:
            raise VocabularyAtlasError(str(error)) from error
        if redirect.get("target_concept_id") not in concept_ids:
            raise VocabularyAtlasError("redirect target is outside its release")

    reference_document = _json_object(
        record["reference_resource_release"],
        "reference_resource_release",
    )
    distribution_payload = {
        "concepts": list(concepts),
        "labels": list(labels),
        "hierarchy": list(record["hierarchy"]),
        "mappings": list(record["mappings"]),
        "redirects": list(record["redirects"]),
    }
    try:
        reference_release = reference_release_node(reference_document)
        validate_reference_resource_release(
            reference_document,
            scheme_id=scheme_id,
            release_version=version,
            concept_ids=sorted(concept_ids),
            distribution_payload=distribution_payload,
        )
    except CanonicalValueError as error:
        raise VocabularyAtlasError(str(error)) from error
    members = reference_release.get("prov:hadMember")
    if not isinstance(members, list) or sorted(members) != sorted(concept_ids):
        raise VocabularyAtlasError(
            "ReferenceResourceRelease membership differs from released concepts"
        )
    if reference_release.get("dcterms:isVersionOf") != scheme_id:
        raise VocabularyAtlasError(
            "ReferenceResourceRelease names the wrong concept scheme"
        )
    if str(reference_release.get("dcat:version") or "") != version:
        raise VocabularyAtlasError("ReferenceResourceRelease version differs")


@dataclass(frozen=True, slots=True)
class VerifiedVocabularyRelease:
    """One canonical, immutable vocabulary release selected for an atlas."""

    _canonical_payload: bytes
    release_id: str
    release_digest: str
    file_digest: str
    reference_release_id: str
    reference_release_digest: str

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        file_digest: str | None = None,
    ) -> Self:
        copied = deepcopy(dict(record))
        validate_vocabulary_release_input(copied)
        payload = canonical_json_bytes(copied)
        canonical_file_digest = sha256_bytes(payload)
        if file_digest is not None and file_digest != canonical_file_digest:
            raise VocabularyAtlasError(
                "file_digest does not match the canonical VocabularyRelease bytes"
            )
        exact_file_digest = canonical_file_digest
        if _SHA256.fullmatch(exact_file_digest) is None:
            raise VocabularyAtlasError("file_digest must be sha256:<64 lowercase hex>")
        reference_release = reference_release_node(copied["reference_resource_release"])
        return cls(
            _canonical_payload=payload,
            release_id=str(copied["release_id"]),
            release_digest=str(copied["release_digest"]),
            file_digest=exact_file_digest,
            reference_release_id=str(reference_release["@id"]),
            reference_release_digest=str(
                reference_release["rkaf:referenceReleaseDigest"]
            ),
        )

    @classmethod
    def open(cls, path: Path | str, *, expected_file_digest: str) -> Self:
        if _SHA256.fullmatch(expected_file_digest) is None:
            raise VocabularyAtlasError(
                "expected_file_digest must be sha256:<64 lowercase hex>"
            )
        source = Path(path)
        if source.is_symlink() or not source.is_file():
            raise VocabularyAtlasError(
                f"VocabularyRelease must be a regular file: {source}"
            )
        payload = source.read_bytes()
        if sha256_bytes(payload) != expected_file_digest:
            raise VocabularyAtlasError(
                "VocabularyRelease bytes differ from the external digest pin"
            )
        record = _strict_json(payload, "VocabularyRelease")
        if not isinstance(record, Mapping):
            raise VocabularyAtlasError("VocabularyRelease root must be a JSON object")
        verified = cls.from_record(record)
        return cls(
            _canonical_payload=verified._canonical_payload,
            release_id=verified.release_id,
            release_digest=verified.release_digest,
            file_digest=expected_file_digest,
            reference_release_id=verified.reference_release_id,
            reference_release_digest=verified.reference_release_digest,
        )

    def record(self) -> dict[str, Any]:
        """Return a disposable copy of the verified release record."""

        return json.loads(self._canonical_payload)

    def pin(self) -> dict[str, str]:
        return {
            "role": "VocabularyRelease",
            "identifier": self.release_id,
            "releaseDigest": self.release_digest,
            "fileDigest": self.file_digest,
            "referenceReleaseId": self.reference_release_id,
            "referenceReleaseDigest": self.reference_release_digest,
        }


@dataclass(frozen=True, slots=True)
class VerifiedCrosswalkBundle:
    """One externally pinned bundle of candidates and validation records."""

    _canonical_payload: bytes
    file_digest: str

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        file_digest: str | None = None,
    ) -> Self:
        copied = deepcopy(dict(record))
        expected_fields = {
            "schema_version",
            "mapping_candidates",
            "agent_validation_receipts",
            "baseline_validation_receipts",
            "feedback",
        }
        if set(copied) != expected_fields:
            raise VocabularyAtlasError(
                "crosswalk bundle fields differ from the supported schema"
            )
        if copied.get("schema_version") != CROSSWALK_INPUT_VERSION:
            raise VocabularyAtlasError("unsupported crosswalk bundle schema_version")
        for field in expected_fields - {"schema_version"}:
            _json_array(copied[field], f"crosswalk bundle {field}")
        payload = canonical_json_bytes(copied)
        canonical_file_digest = sha256_bytes(payload)
        if file_digest is not None and file_digest != canonical_file_digest:
            raise VocabularyAtlasError(
                "file_digest does not match the canonical crosswalk bundle bytes"
            )
        exact_file_digest = canonical_file_digest
        if _SHA256.fullmatch(exact_file_digest) is None:
            raise VocabularyAtlasError("file_digest must be sha256:<64 lowercase hex>")
        return cls(_canonical_payload=payload, file_digest=exact_file_digest)

    @classmethod
    def open(cls, path: Path | str, *, expected_file_digest: str) -> Self:
        if _SHA256.fullmatch(expected_file_digest) is None:
            raise VocabularyAtlasError(
                "expected_file_digest must be sha256:<64 lowercase hex>"
            )
        source = Path(path)
        if source.is_symlink() or not source.is_file():
            raise VocabularyAtlasError(
                f"crosswalk bundle must be a regular file: {source}"
            )
        payload = source.read_bytes()
        if sha256_bytes(payload) != expected_file_digest:
            raise VocabularyAtlasError(
                "crosswalk bundle bytes differ from the external digest pin"
            )
        record = _strict_json(payload, "crosswalk bundle")
        if not isinstance(record, Mapping):
            raise VocabularyAtlasError("crosswalk bundle root must be a JSON object")
        verified = cls.from_record(record)
        return cls(
            _canonical_payload=verified._canonical_payload,
            file_digest=expected_file_digest,
        )

    def record(self) -> dict[str, Any]:
        return json.loads(self._canonical_payload)

    def pin(self) -> dict[str, str]:
        return {
            "role": "CrosswalkInputBundle",
            "identifier": (
                "urn:refspec:crosswalk-input:"
                + self.file_digest.removeprefix("sha256:")
            ),
            "fileDigest": self.file_digest,
        }


def canonical_nquads(dataset: Dataset) -> bytes:
    """Serialize one blank-node-free dataset as deterministically sorted N-Quads."""

    for subject, predicate, object_, graph in dataset.quads((None, None, None, None)):
        if any(
            isinstance(value, BNode) for value in (subject, predicate, object_, graph)
        ):
            raise VocabularyAtlasError("the atlas must not contain blank nodes")
    serialized = dataset.serialize(format="nquads")
    text = serialized.decode("utf-8") if isinstance(serialized, bytes) else serialized
    lines = sorted(line for line in text.splitlines() if line.strip())
    return ("\n".join(lines) + "\n").encode("utf-8")


@dataclass(frozen=True, slots=True)
class VocabularyAtlasAsset:
    """A sealed static vocabulary atlas and its deterministic manifest."""

    _canonical_payload: bytes
    _manifest: Mapping[str, Any]
    asserted_graph_iri: str
    analysis_graph_iri: str
    generation_digest: str

    @classmethod
    def from_bytes(
        cls,
        payload: bytes,
        manifest: Mapping[str, Any],
    ) -> Self:
        """Verify canonical static bytes before exposing a queryable asset."""

        copied = deepcopy(dict(manifest))
        expected_fields = {
            "schemaVersion",
            "assetId",
            "generationDigest",
            "policies",
            "implementation",
            "graphs",
            "counts",
            "inputs",
            "output",
            "reasoning",
        }
        if set(copied) != expected_fields:
            raise VocabularyAtlasError("atlas manifest fields differ from v1")
        if copied.get("schemaVersion") != ATLAS_FORMAT_VERSION:
            raise VocabularyAtlasError("unsupported atlas manifest schemaVersion")
        generation_digest = str(copied.get("generationDigest") or "")
        if _SHA256.fullmatch(generation_digest) is None:
            raise VocabularyAtlasError("atlas generationDigest is invalid")
        suffix = generation_digest.removeprefix("sha256:")
        asset_id = str(copied.get("assetId") or "")
        expected_asset_id = f"urn:refspec:vocabulary-atlas:{suffix}"
        if asset_id != expected_asset_id:
            raise VocabularyAtlasError("atlas assetId differs from generationDigest")

        policies = _json_object(copied["policies"], "atlas policies")
        if policies != {
            "candidateSelection": CROSSWALK_SELECTION_POLICY,
            "generation": ATLAS_GENERATION_POLICY,
        }:
            raise VocabularyAtlasError("atlas policies differ from supported v1")
        implementation = _json_object(copied["implementation"], "atlas implementation")
        if set(implementation) != {
            "sourceModules",
            "validationArtifacts",
            "runtime",
        }:
            raise VocabularyAtlasError("atlas implementation fields are invalid")
        source_modules = _json_array(
            implementation.get("sourceModules"),
            "atlas implementation sourceModules",
        )
        if not source_modules:
            raise VocabularyAtlasError("atlas implementation pin is empty")
        for value in source_modules:
            source = _json_object(value, "atlas implementation source")
            if (
                set(source) != {"path", "sha256"}
                or _SHA256.fullmatch(str(source.get("sha256") or "")) is None
            ):
                raise VocabularyAtlasError("atlas implementation source pin is invalid")
        validation_artifacts = _json_array(
            implementation.get("validationArtifacts"),
            "atlas implementation validationArtifacts",
        )
        if not validation_artifacts:
            raise VocabularyAtlasError("atlas validation-artifact pin is empty")
        for value in validation_artifacts:
            artifact = _json_object(value, "atlas validation artifact")
            if (
                set(artifact) != {"path", "sha256"}
                or _SHA256.fullmatch(str(artifact.get("sha256") or "")) is None
            ):
                raise VocabularyAtlasError(
                    "atlas implementation validation-artifact pin is invalid"
                )
        runtime = _json_object(
            implementation.get("runtime"), "atlas implementation runtime"
        )
        if set(runtime) != {
            "pythonRequirement",
            "rdflibVersion",
        } or any(not str(value).strip() for value in runtime.values()):
            raise VocabularyAtlasError("atlas implementation runtime pin is invalid")

        graphs = _json_object(copied["graphs"], "atlas graphs")
        if set(graphs) != {"asserted", "analysis"}:
            raise VocabularyAtlasError("atlas must declare exactly two named graphs")
        asserted = _json_object(graphs["asserted"], "asserted graph")
        analysis = _json_object(graphs["analysis"], "analysis graph")
        expected_analysis_id = f"urn:refspec:vocabulary-atlas-analysis:{suffix}"
        if asserted.get("id") != asset_id or analysis.get("id") != expected_analysis_id:
            raise VocabularyAtlasError(
                "atlas graph identity differs from asset identity"
            )
        for name, graph in (("asserted", asserted), ("analysis", analysis)):
            if (
                set(graph) != {"id", "tripleCount"}
                or not isinstance(graph.get("tripleCount"), int)
                or graph["tripleCount"] < 1
            ):
                raise VocabularyAtlasError(f"{name} graph declaration is invalid")

        output = _json_object(copied["output"], "atlas output")
        if set(output) != {"path", "mediaType", "byteLength", "sha256"}:
            raise VocabularyAtlasError("atlas output declaration is invalid")
        if (
            output.get("path") != "atlas.nq"
            or output.get("mediaType") != "application/n-quads"
        ):
            raise VocabularyAtlasError("atlas output format is unsupported")
        if not isinstance(output.get("byteLength"), int) or output["byteLength"] != len(
            payload
        ):
            raise VocabularyAtlasError("atlas output byte length differs")
        if output.get("sha256") != sha256_bytes(payload):
            raise VocabularyAtlasError("atlas output digest differs")

        try:
            dataset = Dataset(default_union=False)
            dataset.parse(data=payload, format="nquads")
        except Exception as error:
            raise VocabularyAtlasError("atlas.nq is not valid N-Quads") from error
        canonical = canonical_nquads(dataset)
        if canonical != payload:
            raise VocabularyAtlasError("atlas.nq bytes are not canonical")
        graph_ids = {str(graph.identifier) for graph in dataset.graphs() if len(graph)}
        if graph_ids != {asset_id, expected_analysis_id}:
            raise VocabularyAtlasError(
                "atlas.nq does not contain exactly two named graphs"
            )
        asserted_graph = dataset.graph(URIRef(asset_id))
        analysis_graph = dataset.graph(URIRef(expected_analysis_id))
        if len(asserted_graph) != asserted["tripleCount"]:
            raise VocabularyAtlasError("asserted graph triple count differs")
        if len(analysis_graph) != analysis["tripleCount"]:
            raise VocabularyAtlasError("analysis graph triple count differs")

        generation_node = URIRef(asset_id)
        analysis_node = URIRef(expected_analysis_id)
        if (
            (generation_node, RDF.type, _ATLAS.AtlasGeneration) not in asserted_graph
            or (
                generation_node,
                _ATLAS.generationDigest,
                Literal(generation_digest),
            )
            not in asserted_graph
            or (generation_node, _ATLAS.analysisGraph, analysis_node)
            not in asserted_graph
            or (analysis_node, RDF.type, _ATLAS.AnalysisGeneration)
            not in analysis_graph
            or (analysis_node, PROV.wasDerivedFrom, generation_node)
            not in analysis_graph
        ):
            raise VocabularyAtlasError("atlas graph identity chain differs")

        counts = _json_object(copied["counts"], "atlas counts")
        actual_counts = {
            "managedReleases": len(
                set(asserted_graph.subjects(RDF.type, _ATLAS.ManagedVocabularyRelease))
            ),
            "conceptSchemes": len(
                set(asserted_graph.subjects(RDF.type, SKOS.ConceptScheme))
            ),
            "concepts": len(set(asserted_graph.subjects(RDF.type, SKOS.Concept))),
            "labels": len(
                set(asserted_graph.subjects(RDF.type, _ATLAS.VocabularyLabel))
            ),
            "labelClusters": len(
                set(analysis_graph.subjects(RDF.type, _ATLAS.LabelCluster))
            ),
            "mappingCandidates": len(
                set(analysis_graph.subjects(RDF.type, _ATLAS.ConceptMappingCandidate))
            ),
            "searchOnlyMappings": len(
                set(asserted_graph.subjects(RDF.type, _RKAF.ConceptMapping))
            ),
            "agentValidationReceipts": len(
                set(analysis_graph.subjects(RDF.type, _ATLAS.AgentValidationReceipt))
            ),
            "baselineValidationReceipts": len(
                set(analysis_graph.subjects(RDF.type, _ATLAS.BaselineValidationReceipt))
            ),
            "feedback": len(
                set(analysis_graph.subjects(RDF.type, _ATLAS.MappingFeedback))
            ),
        }
        if counts != actual_counts:
            raise VocabularyAtlasError(
                "atlas declared counts differ from graph contents"
            )

        inputs = _json_array(copied["inputs"], "atlas inputs")
        seen_inputs: set[tuple[str, str]] = set()
        release_inputs: list[Mapping[str, Any]] = []
        record_shapes = {
            "MappingCandidate": (
                _ATLAS.ConceptMappingCandidate,
                _ATLAS.candidateDigest,
            ),
            "AgentValidationReceipt": (
                _ATLAS.AgentValidationReceipt,
                _ATLAS.receiptDigest,
            ),
            "BaselineValidationReceipt": (
                _ATLAS.BaselineValidationReceipt,
                _ATLAS.receiptDigest,
            ),
            "MappingFeedback": (_ATLAS.MappingFeedback, _ATLAS.feedbackDigest),
        }
        for value in inputs:
            item = _json_object(value, "atlas input")
            role = str(item.get("role") or "")
            identifier = _absolute_iri(item.get("identifier"), "atlas input identifier")
            key = (role, identifier)
            if key in seen_inputs:
                raise VocabularyAtlasError("atlas manifest repeats an input")
            seen_inputs.add(key)
            if role == "VocabularyRelease":
                expected = {
                    "role",
                    "identifier",
                    "releaseDigest",
                    "fileDigest",
                    "referenceReleaseId",
                    "referenceReleaseDigest",
                }
                if set(item) != expected:
                    raise VocabularyAtlasError("VocabularyRelease input pin is invalid")
                _absolute_iri(
                    item["referenceReleaseId"], "reference release identifier"
                )
                for field in (
                    "releaseDigest",
                    "fileDigest",
                    "referenceReleaseDigest",
                ):
                    if _SHA256.fullmatch(str(item[field])) is None:
                        raise VocabularyAtlasError(
                            f"VocabularyRelease input {field} is invalid"
                        )
                release_inputs.append(item)
            elif role == "CrosswalkInputBundle":
                if (
                    set(item)
                    != {
                        "role",
                        "identifier",
                        "fileDigest",
                    }
                    or _SHA256.fullmatch(str(item.get("fileDigest") or "")) is None
                ):
                    raise VocabularyAtlasError("crosswalk bundle input pin is invalid")
            elif role in record_shapes:
                if (
                    set(item)
                    != {
                        "role",
                        "identifier",
                        "recordDigest",
                    }
                    or _SHA256.fullmatch(str(item.get("recordDigest") or "")) is None
                ):
                    raise VocabularyAtlasError(f"{role} input pin is invalid")
                record_type, digest_predicate = record_shapes[role]
                node = URIRef(identifier)
                if (node, RDF.type, record_type) not in analysis_graph or (
                    node,
                    digest_predicate,
                    Literal(str(item["recordDigest"])),
                ) not in analysis_graph:
                    raise VocabularyAtlasError(f"{role} input pin differs from graph")
            else:
                raise VocabularyAtlasError(f"atlas input role is unsupported: {role}")

        pin_nodes = set(asserted_graph.subjects(RDF.type, _ATLAS.InputPin))
        if len(pin_nodes) != len(release_inputs):
            raise VocabularyAtlasError("atlas release input-pin count differs")
        for item in release_inputs:
            matches = {
                node
                for node in pin_nodes
                if (
                    node,
                    _ATLAS.inputIdentifier,
                    URIRef(str(item["identifier"])),
                )
                in asserted_graph
            }
            if len(matches) != 1:
                raise VocabularyAtlasError("atlas release input pin does not resolve")
            pin_node = next(iter(matches))
            expected_triples = (
                (_ATLAS.releaseDigest, Literal(str(item["releaseDigest"]))),
                (_ATLAS.fileDigest, Literal(str(item["fileDigest"]))),
                (
                    _ATLAS.referenceResourceRelease,
                    URIRef(str(item["referenceReleaseId"])),
                ),
                (
                    _RKAF.referenceReleaseDigest,
                    Literal(str(item["referenceReleaseDigest"])),
                ),
            )
            if any(
                (pin_node, predicate, object_) not in asserted_graph
                for predicate, object_ in expected_triples
            ):
                raise VocabularyAtlasError("atlas release input pin differs from graph")
        reasoning = _json_object(copied["reasoning"], "atlas reasoning")
        if reasoning != {
            "enabled": False,
            "sameAsEnabled": False,
            "storedInferenceGraph": False,
        }:
            raise VocabularyAtlasError("atlas reasoning declaration is unsafe")
        return cls(
            _canonical_payload=payload,
            _manifest=copied,
            asserted_graph_iri=asset_id,
            analysis_graph_iri=expected_analysis_id,
            generation_digest=generation_digest,
        )

    @classmethod
    def open(
        cls,
        directory: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> Self:
        """Open a copied static asset only when its manifest is externally pinned."""

        if _SHA256.fullmatch(expected_manifest_digest) is None:
            raise VocabularyAtlasError("expected manifest digest is invalid")
        root = Path(directory)
        manifest_path = root / "atlas-manifest.json"
        payload_path = root / "atlas.nq"
        for path in (manifest_path, payload_path):
            if path.is_symlink() or not path.is_file():
                raise VocabularyAtlasError(f"atlas file must be regular: {path}")
        manifest_payload = manifest_path.read_bytes()
        if sha256_bytes(manifest_payload) != expected_manifest_digest:
            raise VocabularyAtlasError("atlas manifest differs from its external pin")
        manifest = _strict_json(manifest_payload, "atlas manifest")
        if not isinstance(manifest, Mapping):
            raise VocabularyAtlasError("atlas manifest root must be a JSON object")
        if canonical_json_bytes(manifest) + b"\n" != manifest_payload:
            raise VocabularyAtlasError("atlas manifest bytes are not canonical")
        return cls.from_bytes(payload_path.read_bytes(), manifest)

    @property
    def dataset(self) -> Dataset:
        dataset = Dataset(default_union=False)
        dataset.parse(data=self._canonical_payload, format="nquads")
        return dataset

    def canonical_nquads(self) -> bytes:
        return self._canonical_payload

    def manifest(self) -> dict[str, Any]:
        return deepcopy(dict(self._manifest))

    def write_to(self, output_directory: Path | str) -> dict[str, Path]:
        root = Path(output_directory)
        root.mkdir(parents=True, exist_ok=True)
        payloads = {
            "atlas.nq": self._canonical_payload,
            "atlas-manifest.json": canonical_json_bytes(self._manifest) + b"\n",
        }
        written: dict[str, Path] = {}
        for name, payload in payloads.items():
            path = root / name
            if path.exists() and path.read_bytes() != payload:
                raise FileExistsError(
                    f"refusing to overwrite a different atlas artifact: {path}"
                )
            path.write_bytes(payload)
            written[name] = path
        return written


def build_manifest(
    *,
    payload: bytes,
    generation_digest: str,
    asserted_graph: Graph,
    analysis_graph: Graph,
    counts: Mapping[str, int],
    inputs: Sequence[Mapping[str, str]],
    asset_id: str,
    policies: Mapping[str, str],
    implementation: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schemaVersion": ATLAS_FORMAT_VERSION,
        "assetId": asset_id,
        "generationDigest": generation_digest,
        "policies": dict(sorted(policies.items())),
        "implementation": deepcopy(dict(implementation)),
        "graphs": {
            "asserted": {
                "id": str(asserted_graph.identifier),
                "tripleCount": len(asserted_graph),
            },
            "analysis": {
                "id": str(analysis_graph.identifier),
                "tripleCount": len(analysis_graph),
            },
        },
        "counts": dict(sorted(counts.items())),
        "inputs": sorted(
            (dict(value) for value in inputs),
            key=lambda value: (
                value.get("role", ""),
                value.get("identifier", ""),
            ),
        ),
        "output": {
            "path": "atlas.nq",
            "mediaType": "application/n-quads",
            "byteLength": len(payload),
            "sha256": sha256_bytes(payload),
        },
        "reasoning": {
            "enabled": False,
            "sameAsEnabled": False,
            "storedInferenceGraph": False,
        },
    }


__all__ = [
    "ATLAS_FORMAT_VERSION",
    "ATLAS_GENERATION_POLICY",
    "CROSSWALK_INPUT_VERSION",
    "CROSSWALK_SELECTION_POLICY",
    "VerifiedCrosswalkBundle",
    "VerifiedVocabularyRelease",
    "VocabularyAtlasAsset",
    "VocabularyAtlasError",
    "atlas_implementation_pin",
    "build_manifest",
    "canonical_nquads",
    "sha256_bytes",
    "validate_vocabulary_release_input",
]
