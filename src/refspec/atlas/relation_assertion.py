"""Closed relation assertions over exact releases in one semantic ring.

The bundle in this module is the shared foundation for subject mappings,
entity links, value crosswalks, and legal-identity relations.  It shares
identity, release pins, evidence, and lifecycle-independent assertion shape;
the semantic foundation still enforces a different relation vocabulary for
each ring.

Every endpoint is checked against a path-backed, digest-verified release.
Labels never establish membership or identity, and contradictory assertions
remain separate facts unless they repeat the same assertion identifier.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from typing_extensions import Self

from refspec import binding
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.semantic_foundation import (
    SEMANTIC_RINGS,
    EvidenceAssertion,
    MappingAssertion,
    SemanticFoundationError,
    SemanticRing,
    _validate_mapping_assertions_with_machine_evidence,
    validate_evidence_assertions,
    validate_machine_evidence_proof_pin,
)
from refspec.registry.infrastructure.source_identity import (
    SourceIdentityError,
    require_aware_datetime_text,
)

from .concept_release import (
    ConceptReleaseError,
    ConceptReleaseSource,
    PinnedManagedConceptRelease,
    PinnedSourceConceptRelease,
)
from .relation_proof import (
    RelationMachineProofSource,
    RelationMachineProofTrustError,
    trusted_relation_machine_proof_adapter_id,
)

RELATION_ASSERTION_BUNDLE_VERSION = "1.0"
RELATION_ASSERTION_BUNDLE_MEDIA_TYPE = "application/vnd.refspec.relation-assertion-bundle+json"

_ASSERTIONS_PATH = "relation-assertions.json"
_BUNDLE_MANIFEST_PATH = "bundle-manifest.json"
_BUNDLE_FILES = frozenset({_ASSERTIONS_PATH, _BUNDLE_MANIFEST_PATH})
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_RECORD_FIELDS = frozenset(
    {
        "id",
        "type",
        "schemaVersion",
        "contentDigest",
        "semanticRing",
        "releasePins",
        "machineProofPins",
        "evidenceAssertions",
        "mappingAssertions",
    }
)


class RelationAssertionError(ValueError):
    """A relation bundle is incomplete, mutable, or outside its exact releases."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        binding.validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise RelationAssertionError(str(error)) from error
    return canonical_json_bytes(plain)


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise RelationAssertionError(f"{label} must be non-empty trimmed text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise RelationAssertionError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise RelationAssertionError(f"{label} must not contain credentials")
    return iri


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RelationAssertionError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_ring(value: object, label: str) -> SemanticRing:
    if not isinstance(value, str) or value not in SEMANTIC_RINGS:
        raise RelationAssertionError(
            f"{label} must be subject, entity, value, or legalIdentity"
        )
    return cast(SemanticRing, value)


def _require_datetime(value: object, label: str) -> str:
    text = _require_text(value, label)
    try:
        return require_aware_datetime_text(text, label=label)
    except SourceIdentityError as error:
        raise RelationAssertionError(str(error)) from error


def _require_unique_iris(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise RelationAssertionError(f"{label} must be a non-empty IRI array")
    result = tuple(_require_iri(item, f"{label}[{index}]") for index, item in enumerate(value))
    if len(set(result)) != len(result):
        raise RelationAssertionError(f"{label} must contain unique IRIs")
    return tuple(sorted(result))


def _require_exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise RelationAssertionError(
            f"{label} fields differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _read_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise RelationAssertionError(f"{label} must be valid canonical UTF-8 JSON") from error


def _bundle_snapshot(root: Path) -> dict[str, bytes]:
    """Read the exact regular-file set and reject shape changes during the read."""

    entries = {item.name: item for item in root.iterdir()}
    if set(entries) != _BUNDLE_FILES:
        raise RelationAssertionError("relation bundle file set differs")
    if any(item.is_symlink() for item in entries.values()):
        raise RelationAssertionError("relation bundle must not contain symlinks")
    if any(not item.is_file() for item in entries.values()):
        raise RelationAssertionError("relation bundle must contain only regular files")
    result = {name: entries[name].read_bytes() for name in _BUNDLE_FILES}
    final_entries = {item.name: item for item in root.iterdir()}
    if (
        set(final_entries) != _BUNDLE_FILES
        or any(item.is_symlink() for item in final_entries.values())
        or any(not item.is_file() for item in final_entries.values())
    ):
        raise RelationAssertionError("relation bundle changed while reading")
    return result


@dataclass(frozen=True, slots=True)
class _ResolvedRelease:
    pin: Mapping[str, Any]
    members: frozenset[str]


def _resolve_releases(
    values: Sequence[ConceptReleaseSource],
    *,
    semantic_ring: SemanticRing,
) -> tuple[tuple[ConceptReleaseSource, ...], tuple[_ResolvedRelease, ...]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
        raise RelationAssertionError("release_sources must be a non-empty array of verified release pins")
    sources: list[ConceptReleaseSource] = []
    resolved: list[_ResolvedRelease] = []
    identifiers: set[str] = set()
    for index, source in enumerate(values):
        if not isinstance(
            source,
            (PinnedSourceConceptRelease, PinnedManagedConceptRelease),
        ):
            raise RelationAssertionError(
                f"release_sources[{index}] must be a path-backed verified concept release"
            )
        try:
            if source.semantic_ring != semantic_ring:
                raise RelationAssertionError(
                    "relation release semanticRing differs from the bundle"
                )
            pin = source.pin()
            members = source.member_ids()
        except ConceptReleaseError as error:
            raise RelationAssertionError(str(error)) from error
        release_id = _require_iri(pin.get("releaseId"), f"release_sources[{index}].releaseId")
        if release_id in identifiers:
            raise RelationAssertionError("release_sources repeats a releaseId")
        if not members:
            raise RelationAssertionError("relation release has no exact members")
        identifiers.add(release_id)
        sources.append(source)
        resolved.append(
            _ResolvedRelease(
                pin=cast(Mapping[str, Any], deep_freeze_json(pin)),
                members=members,
            )
        )
    paired = sorted(
        zip(sources, resolved, strict=True),
        key=lambda pair: str(pair[1].pin["releaseId"]),
    )
    return tuple(pair[0] for pair in paired), tuple(pair[1] for pair in paired)


def _required_evidence_ids(
    mappings: Sequence[MappingAssertion],
    evidence_by_id: Mapping[str, EvidenceAssertion],
) -> frozenset[str]:
    required = {identifier for mapping in mappings for identifier in mapping.evidence}
    for identifier in tuple(required):
        assertion = evidence_by_id[identifier]
        if assertion.evidence_class != "operatorAdopted":
            continue
        adopted = cast(str, assertion.adopted_evidence)
        required.add(adopted)
    return frozenset(required)


def _resolve_machine_proofs(
    values: Sequence[RelationMachineProofSource],
    *,
    semantic_ring: SemanticRing,
) -> tuple[tuple[RelationMachineProofSource, ...], tuple[Mapping[str, Any], ...]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise RelationAssertionError("machine_proof_sources must be an array")
    paired: list[tuple[RelationMachineProofSource, Mapping[str, Any]]] = []
    identifiers: set[str] = set()
    for index, source in enumerate(values):
        if not isinstance(source, RelationMachineProofSource):
            raise RelationAssertionError(
                f"machine_proof_sources[{index}] must implement the path-backed proof adapter interface"
            )
        try:
            adapter_id = trusted_relation_machine_proof_adapter_id(source)
            requested_path = Path(source.path)
            if requested_path.is_symlink():
                raise RelationAssertionError("machine proof source path must not be a symlink")
            proof_path = requested_path.resolve(strict=True)
            if not proof_path.is_file():
                raise RelationAssertionError("machine proof source path must be a regular file")
            proof_bytes = proof_path.read_bytes()
            pin = cast(
                Mapping[str, Any],
                deep_freeze_json(
                    validate_machine_evidence_proof_pin(
                        source.pin(),
                        semantic_ring=semantic_ring,
                    )
                ),
            )
            if proof_path.read_bytes() != proof_bytes or Path(source.path).resolve(strict=True) != proof_path:
                raise RelationAssertionError("machine proof source changed while verifying")
        except (OSError, RelationMachineProofTrustError, SemanticFoundationError, TypeError, ValueError) as error:
            raise RelationAssertionError(str(error)) from error
        proof_source = pin.get("proofSource")
        if not isinstance(proof_source, Mapping) or proof_source.get("fileDigest") != sha256_digest(proof_bytes):
            raise RelationAssertionError("machine proof pin fileDigest differs from its exact source bytes")
        if pin.get("proofAdapter") != adapter_id:
            raise RelationAssertionError("machine proof pin proofAdapter differs from its trusted executable adapter")
        identifier = _require_iri(pin.get("id"), f"machine_proof_sources[{index}].id")
        if identifier in identifiers:
            raise RelationAssertionError("machine_proof_sources repeats a proof id")
        identifiers.add(identifier)
        paired.append((source, pin))
    paired.sort(key=lambda pair: str(pair[1]["id"]))
    return tuple(pair[0] for pair in paired), tuple(pair[1] for pair in paired)


def _validate_machine_evidence_proofs(
    evidence: Sequence[EvidenceAssertion],
    proof_pins: Sequence[Mapping[str, Any]],
    mappings: Sequence[MappingAssertion],
) -> None:
    machine = tuple(value for value in evidence if value.evidence_class in {"machineQualified", "machineReviewed"})
    pins_by_id = {cast(str, value["id"]): value for value in proof_pins}
    required = {cast(str, value.machine_proof) for value in machine}
    if required != set(pins_by_id):
        raise RelationAssertionError("machine evidence and exact proof pins do not close")
    for assertion in machine:
        pin = pins_by_id[cast(str, assertion.machine_proof)]
        expected_class = pin.get("evidenceClass")
        if pin.get("semanticRing") != assertion.semantic_ring:
            raise RelationAssertionError("machine evidence semantic ring differs from its verified proof")
        if assertion.evidence_class != expected_class:
            raise RelationAssertionError("machine evidence class differs from its verified proof kind")
        candidate = pin.get("candidate")
        validations = pin.get("validations")
        if not isinstance(candidate, Mapping) or not isinstance(validations, Sequence):
            raise RelationAssertionError("machine proof pin is incomplete")
        validation_ids = tuple(
            sorted(
                _require_iri(value.get("id"), "machine proof validation id")
                for value in validations
                if isinstance(value, Mapping)
            )
        )
        if len(validation_ids) != len(validations):
            raise RelationAssertionError("machine proof validations must be objects")
        if (
            assertion.candidate != candidate.get("id")
            or assertion.validation_receipts != validation_ids
            or assertion.source_concept != pin.get("sourceConcept")
            or assertion.target_concept != pin.get("targetConcept")
            or assertion.source_release != pin.get("sourceRelease")
            or assertion.target_release != pin.get("targetRelease")
            or assertion.relation != pin.get("relation")
            or cast(str, assertion.machine_proof) not in assertion.evidence
        ):
            raise RelationAssertionError("machine evidence differs from its verified proof facts")
    evidence_by_id = {value.identifier: value for value in evidence}
    for mapping in mappings:
        expected_context = None if mapping.context is None else dict(mapping.context)
        for identifier in _required_evidence_ids((mapping,), evidence_by_id):
            assertion = evidence_by_id[identifier]
            if assertion.evidence_class not in {"machineQualified", "machineReviewed"}:
                continue
            pin = pins_by_id[cast(str, assertion.machine_proof)]
            if pin.get("context") != expected_context:
                raise RelationAssertionError("mapping context differs from its verified machine proof facts")


def _content_record(
    *,
    semantic_ring: SemanticRing,
    release_pins: Sequence[Mapping[str, Any]],
    machine_proof_pins: Sequence[Mapping[str, Any]],
    evidence_assertions: Sequence[EvidenceAssertion],
    mapping_assertions: Sequence[MappingAssertion],
) -> dict[str, Any]:
    basis = {
        "type": "RelationAssertionBundle",
        "schemaVersion": RELATION_ASSERTION_BUNDLE_VERSION,
        "semanticRing": semantic_ring,
        "releasePins": [_plain(value) for value in release_pins],
        "machineProofPins": [_plain(value) for value in machine_proof_pins],
        "evidenceAssertions": [value.as_record() for value in evidence_assertions],
        "mappingAssertions": [value.as_record() for value in mapping_assertions],
    }
    content_digest = sha256_digest(_canonical_bytes(basis))
    return {
        **basis,
        "id": f"urn:ref:relation-assertion-bundle:{semantic_ring}:{content_digest.removeprefix('sha256:')}",
        "contentDigest": content_digest,
    }


@dataclass(frozen=True, slots=True)
class RelationAssertionBundle:
    """One content-derived, release-closed set of typed relation assertions."""

    semantic_ring: SemanticRing
    release_pins: tuple[Mapping[str, Any], ...]
    machine_proof_pins: tuple[Mapping[str, Any], ...]
    evidence_assertions: tuple[EvidenceAssertion, ...]
    mapping_assertions: tuple[MappingAssertion, ...]
    _release_sources: tuple[ConceptReleaseSource, ...] = field(repr=False)
    _machine_proof_sources: tuple[RelationMachineProofSource, ...] = field(repr=False)
    _path: Path | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        ring = _require_ring(self.semantic_ring, "relation bundle semanticRing")
        sources, resolved = _resolve_releases(self._release_sources, semantic_ring=ring)
        expected_pins = tuple(value.pin for value in resolved)
        supplied_pins = tuple(cast(Mapping[str, Any], deep_freeze_json(_plain(value))) for value in self.release_pins)
        if supplied_pins != expected_pins:
            raise RelationAssertionError("relation bundle release pins differ from their verified sources")
        proof_sources, expected_proof_pins = _resolve_machine_proofs(
            self._machine_proof_sources,
            semantic_ring=ring,
        )
        supplied_proof_pins = tuple(
            cast(Mapping[str, Any], deep_freeze_json(_plain(value))) for value in self.machine_proof_pins
        )
        if supplied_proof_pins != expected_proof_pins:
            raise RelationAssertionError("relation bundle machine proof pins differ from their verified sources")
        try:
            evidence = validate_evidence_assertions(self.evidence_assertions, semantic_ring=ring)
            mappings = _validate_mapping_assertions_with_machine_evidence(
                self.mapping_assertions,
                evidence_assertions=evidence,
                semantic_ring=ring,
            )
        except SemanticFoundationError as error:
            raise RelationAssertionError(str(error)) from error
        if not mappings:
            raise RelationAssertionError("relation bundle must contain at least one mapping assertion")
        _validate_machine_evidence_proofs(evidence, expected_proof_pins, mappings)
        evidence_by_id = {value.identifier: value for value in evidence}
        used = _required_evidence_ids(mappings, evidence_by_id)
        unused = sorted(set(evidence_by_id) - used)
        if unused:
            raise RelationAssertionError(f"relation bundle contains unreferenced evidence {unused!r}")
        evidence_ids = set(evidence_by_id)
        mapping_ids = {value.identifier for value in mappings}
        candidate_ids = {
            cast(str, value.candidate)
            for value in evidence
            if value.evidence_class in {"machineQualified", "machineReviewed"}
        }
        if evidence_ids & mapping_ids:
            raise RelationAssertionError("evidence and mapping assertions must have distinct identities")
        if candidate_ids & (evidence_ids | mapping_ids):
            raise RelationAssertionError("candidate identity must remain distinct from evidence and mapping assertions")
        releases = {cast(str, value.pin["releaseId"]): value for value in resolved}
        for mapping in mappings:
            source = releases.get(mapping.source_release)
            target = releases.get(mapping.target_release)
            if source is None or target is None:
                raise RelationAssertionError("mapping assertion names a release outside the exact release pins")
            if mapping.source_concept not in source.members:
                raise RelationAssertionError("mapping sourceConcept is not a member of sourceRelease")
            if mapping.target_concept not in target.members:
                raise RelationAssertionError("mapping targetConcept is not a member of targetRelease")
        required_release_ids = {
            identifier
            for mapping in mappings
            for identifier in (mapping.source_release, mapping.target_release)
        }
        if set(releases) != required_release_ids:
            raise RelationAssertionError("release pins do not equal the exact mapping endpoint release closure")
        object.__setattr__(self, "semantic_ring", ring)
        object.__setattr__(self, "release_pins", expected_pins)
        object.__setattr__(self, "machine_proof_pins", expected_proof_pins)
        object.__setattr__(self, "evidence_assertions", evidence)
        object.__setattr__(self, "mapping_assertions", mappings)
        object.__setattr__(self, "_release_sources", sources)
        object.__setattr__(self, "_machine_proof_sources", proof_sources)
        if self._path is not None:
            object.__setattr__(self, "_path", self._path.resolve(strict=True))

    @classmethod
    def create(
        cls,
        *,
        semantic_ring: SemanticRing,
        release_sources: Sequence[ConceptReleaseSource],
        machine_proof_sources: Sequence[RelationMachineProofSource] = (),
        evidence_assertions: Sequence[EvidenceAssertion | Mapping[str, Any]],
        mapping_assertions: Sequence[MappingAssertion | Mapping[str, Any]],
    ) -> Self:
        ring = _require_ring(semantic_ring, "relation bundle semanticRing")
        sources, resolved = _resolve_releases(release_sources, semantic_ring=ring)
        proof_sources, proof_pins = _resolve_machine_proofs(machine_proof_sources, semantic_ring=ring)
        try:
            evidence = validate_evidence_assertions(evidence_assertions, semantic_ring=ring)
            mappings = _validate_mapping_assertions_with_machine_evidence(
                mapping_assertions,
                evidence_assertions=evidence,
                semantic_ring=ring,
            )
        except SemanticFoundationError as error:
            raise RelationAssertionError(str(error)) from error
        return cls(
            semantic_ring=ring,
            release_pins=tuple(value.pin for value in resolved),
            machine_proof_pins=proof_pins,
            evidence_assertions=evidence,
            mapping_assertions=mappings,
            _release_sources=sources,
            _machine_proof_sources=proof_sources,
        )

    @property
    def identifier(self) -> str:
        return cast(str, self.as_record()["id"])

    @property
    def content_digest(self) -> str:
        return cast(str, self.as_record()["contentDigest"])

    def as_record(self) -> dict[str, Any]:
        return _content_record(
            semantic_ring=self.semantic_ring,
            release_pins=self.release_pins,
            machine_proof_pins=self.machine_proof_pins,
            evidence_assertions=self.evidence_assertions,
            mapping_assertions=self.mapping_assertions,
        )

    def artifact_bytes(self) -> dict[str, bytes]:
        assertions = _canonical_bytes(self.as_record())
        manifest = _canonical_bytes(
            {
                "schemaVersion": RELATION_ASSERTION_BUNDLE_VERSION,
                "packageKind": "relationAssertionBundle",
                "bundleId": self.identifier,
                "contentDigest": self.content_digest,
                "artifacts": [
                    {
                        "path": _ASSERTIONS_PATH,
                        "role": "relationAssertions",
                        "mediaType": RELATION_ASSERTION_BUNDLE_MEDIA_TYPE,
                        "sha256": sha256_digest(assertions),
                        "byteLength": len(assertions),
                    }
                ],
            }
        )
        return {_BUNDLE_MANIFEST_PATH: manifest, _ASSERTIONS_PATH: assertions}

    @property
    def manifest_digest(self) -> str:
        return sha256_digest(self.artifact_bytes()[_BUNDLE_MANIFEST_PATH])

    def verify(self) -> None:
        """Reopen every input release and, when persisted, the bundle itself."""

        rebuilt = RelationAssertionBundle.create(
            semantic_ring=self.semantic_ring,
            release_sources=self._release_sources,
            machine_proof_sources=self._machine_proof_sources,
            evidence_assertions=self.evidence_assertions,
            mapping_assertions=self.mapping_assertions,
        )
        if rebuilt.as_record() != self.as_record():
            raise RelationAssertionError("relation bundle no longer reproduces from its verified inputs")
        if self._path is not None:
            reopened = RelationAssertionBundle.open(
                self._path / _BUNDLE_MANIFEST_PATH,
                expected_manifest_digest=self.manifest_digest,
                release_sources=self._release_sources,
                machine_proof_sources=self._machine_proof_sources,
            )
            if reopened.artifact_bytes() != self.artifact_bytes():
                raise RelationAssertionError("persisted relation bundle bytes differ")

    def write_to(self, path: Path | str) -> Path:
        """Write the closed bundle atomically to a new directory."""

        destination = Path(path)
        if destination.exists() or destination.is_symlink():
            raise RelationAssertionError(f"relation bundle destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}-",
                dir=destination.parent,
            )
        )
        try:
            for relative_path, payload in self.artifact_bytes().items():
                (temporary / relative_path).write_bytes(payload)
            os.replace(temporary, destination)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return destination

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
        release_sources: Sequence[ConceptReleaseSource],
        machine_proof_sources: Sequence[RelationMachineProofSource] = (),
    ) -> Self:
        """Open exact bundle bytes and prove their endpoint releases again."""

        expected = _require_digest(expected_manifest_digest, "relation bundle manifest digest")
        requested = Path(manifest_path)
        if requested.is_symlink():
            raise RelationAssertionError("relation bundle manifest must not be a symlink")
        candidate = requested / _BUNDLE_MANIFEST_PATH if requested.is_dir() else requested
        if candidate.name != _BUNDLE_MANIFEST_PATH or not candidate.is_file():
            raise RelationAssertionError("relation bundle requires bundle-manifest.json")
        root = candidate.parent.resolve(strict=True)
        if root.is_symlink() or not root.is_dir():
            raise RelationAssertionError("relation bundle root must be a regular directory")
        observed = _bundle_snapshot(root)
        manifest_bytes = observed[_BUNDLE_MANIFEST_PATH]
        if sha256_digest(manifest_bytes) != expected:
            raise RelationAssertionError("relation bundle manifest digest differs")
        manifest = _read_json(manifest_bytes, "relation bundle manifest")
        if not isinstance(manifest, Mapping):
            raise RelationAssertionError("relation bundle manifest must be an object")
        if _canonical_bytes(manifest) != manifest_bytes:
            raise RelationAssertionError("relation bundle manifest bytes are not canonical")
        _require_exact_fields(
            manifest,
            {"schemaVersion", "packageKind", "bundleId", "contentDigest", "artifacts"},
            "relation bundle manifest",
        )
        if (
            manifest.get("schemaVersion") != RELATION_ASSERTION_BUNDLE_VERSION
            or manifest.get("packageKind") != "relationAssertionBundle"
        ):
            raise RelationAssertionError("relation bundle manifest version is unsupported")
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)) or len(artifacts) != 1:
            raise RelationAssertionError("relation bundle manifest must name one assertion artifact")
        descriptor = artifacts[0]
        if not isinstance(descriptor, Mapping):
            raise RelationAssertionError("relation bundle artifact descriptor must be an object")
        _require_exact_fields(
            descriptor,
            {"path", "role", "mediaType", "sha256", "byteLength"},
            "relation bundle artifact descriptor",
        )
        if (
            descriptor.get("path") != _ASSERTIONS_PATH
            or descriptor.get("role") != "relationAssertions"
            or descriptor.get("mediaType") != RELATION_ASSERTION_BUNDLE_MEDIA_TYPE
        ):
            raise RelationAssertionError("relation bundle assertion artifact descriptor differs")
        assertions_bytes = observed[_ASSERTIONS_PATH]
        if descriptor.get("sha256") != sha256_digest(assertions_bytes) or descriptor.get("byteLength") != len(
            assertions_bytes
        ):
            raise RelationAssertionError("relation bundle assertion artifact bytes differ")
        record = _read_json(assertions_bytes, "relation assertion record")
        if not isinstance(record, Mapping):
            raise RelationAssertionError("relation assertion record must be an object")
        _require_exact_fields(record, set(_RECORD_FIELDS), "relation assertion record")
        if _canonical_bytes(record) != assertions_bytes:
            raise RelationAssertionError("relation assertion record bytes are not canonical")
        if (
            record.get("type") != "RelationAssertionBundle"
            or record.get("schemaVersion") != RELATION_ASSERTION_BUNDLE_VERSION
        ):
            raise RelationAssertionError("relation assertion record version is unsupported")
        if manifest.get("bundleId") != record.get("id") or manifest.get("contentDigest") != record.get("contentDigest"):
            raise RelationAssertionError("relation bundle manifest differs from its assertion record")
        release_pins = record.get("releasePins")
        proof_pins = record.get("machineProofPins")
        evidence_rows = record.get("evidenceAssertions")
        mapping_rows = record.get("mappingAssertions")
        if not isinstance(release_pins, Sequence) or isinstance(release_pins, (str, bytes)):
            raise RelationAssertionError("relation assertion releasePins must be an array")
        if not isinstance(proof_pins, Sequence) or isinstance(proof_pins, (str, bytes)):
            raise RelationAssertionError("relation assertion machineProofPins must be an array")
        if not isinstance(evidence_rows, Sequence) or isinstance(evidence_rows, (str, bytes)):
            raise RelationAssertionError("relation assertion evidenceAssertions must be an array")
        if not isinstance(mapping_rows, Sequence) or isinstance(mapping_rows, (str, bytes)):
            raise RelationAssertionError("relation assertion mappingAssertions must be an array")
        rebuilt = cls.create(
            semantic_ring=_require_ring(record.get("semanticRing"), "relation assertion semanticRing"),
            release_sources=release_sources,
            machine_proof_sources=machine_proof_sources,
            evidence_assertions=cast(Sequence[Mapping[str, Any]], evidence_rows),
            mapping_assertions=cast(Sequence[Mapping[str, Any]], mapping_rows),
        )
        if tuple(_plain(value) for value in rebuilt.release_pins) != tuple(_plain(value) for value in release_pins):
            raise RelationAssertionError("relation assertion release pins differ from verified sources")
        if tuple(_plain(value) for value in rebuilt.machine_proof_pins) != tuple(_plain(value) for value in proof_pins):
            raise RelationAssertionError("relation assertion machine proof pins differ from verified sources")
        if rebuilt.as_record() != dict(record):
            raise RelationAssertionError("relation assertion content identity is stale or incorrect")
        result = cls(
            semantic_ring=rebuilt.semantic_ring,
            release_pins=rebuilt.release_pins,
            machine_proof_pins=rebuilt.machine_proof_pins,
            evidence_assertions=rebuilt.evidence_assertions,
            mapping_assertions=rebuilt.mapping_assertions,
            _release_sources=rebuilt._release_sources,
            _machine_proof_sources=rebuilt._machine_proof_sources,
            _path=root,
        )
        try:
            final_snapshot = _bundle_snapshot(root)
        except RelationAssertionError as error:
            raise RelationAssertionError("relation bundle changed while opening") from error
        if final_snapshot != observed:
            raise RelationAssertionError("relation bundle changed while opening")
        return result


@dataclass(frozen=True, slots=True)
class PinnedRelationAssertionBundle:
    """One exact path-backed relation bundle prepared as an atlas input."""

    manifest_path: Path
    manifest_digest: str
    bundle_id: str
    semantic_ring: SemanticRing
    content_digest: str
    _release_sources: tuple[ConceptReleaseSource, ...] = field(repr=False)
    _machine_proof_sources: tuple[RelationMachineProofSource, ...] = field(repr=False)

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
        release_sources: Sequence[ConceptReleaseSource],
        machine_proof_sources: Sequence[RelationMachineProofSource] = (),
    ) -> Self:
        """Open exact bundle bytes and retain every source needed to reopen them."""

        digest = _require_digest(
            expected_manifest_digest,
            "relation bundle manifest digest",
        )
        bundle = RelationAssertionBundle.open(
            manifest_path,
            expected_manifest_digest=digest,
            release_sources=release_sources,
            machine_proof_sources=machine_proof_sources,
        )
        if bundle._path is None:
            raise RelationAssertionError("pinned relation bundle must be path-backed")
        return cls(
            manifest_path=(bundle._path / _BUNDLE_MANIFEST_PATH).resolve(strict=True),
            manifest_digest=digest,
            bundle_id=bundle.identifier,
            semantic_ring=bundle.semantic_ring,
            content_digest=bundle.content_digest,
            _release_sources=bundle._release_sources,
            _machine_proof_sources=bundle._machine_proof_sources,
        )

    def verified_bundle(self) -> RelationAssertionBundle:
        """Reopen the bundle and all exact release and proof inputs."""

        bundle = RelationAssertionBundle.open(
            self.manifest_path,
            expected_manifest_digest=self.manifest_digest,
            release_sources=self._release_sources,
            machine_proof_sources=self._machine_proof_sources,
        )
        if (
            bundle.identifier != self.bundle_id
            or bundle.semantic_ring != self.semantic_ring
            or bundle.content_digest != self.content_digest
            or bundle.manifest_digest != self.manifest_digest
        ):
            raise RelationAssertionError("relation bundle identity, semantic ring, or content digest changed")
        return bundle

    def pin(self) -> dict[str, str]:
        """Return the closed content-derived input pin for an atlas scope."""

        bundle = self.verified_bundle()
        return {
            "role": "RelationAssertionBundle",
            "id": bundle.identifier,
            "semanticRing": bundle.semantic_ring,
            "contentDigest": bundle.content_digest,
            "manifestDigest": self.manifest_digest,
        }


__all__ = [
    "RELATION_ASSERTION_BUNDLE_MEDIA_TYPE",
    "RELATION_ASSERTION_BUNDLE_VERSION",
    "PinnedRelationAssertionBundle",
    "RelationAssertionBundle",
    "RelationAssertionError",
    "RelationMachineProofSource",
]
