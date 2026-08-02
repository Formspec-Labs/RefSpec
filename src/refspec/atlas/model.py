"""Deterministic static vocabulary-atlas assets over managed release views.

The atlas is a publication format, not a second vocabulary release model.
Every release fact comes from a fail-closed verified release source.  The
second named graph contains replaceable analysis, including explicitly bounded
``searchOnly`` mappings.  Consumers need only the canonical manifest and
N-Quads files.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import itertools
import json
import platform
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol, cast

from rdflib import BNode, Dataset, Graph, Namespace, URIRef
from rdflib import Literal as RdfLiteral
from rdflib.compare import to_canonical_graph
from rdflib.namespace import PROV, RDF, RDFS, XSD
from typing_extensions import Self

from refspec import binding
from refspec.managed_release import (
    ManagedReleaseExpression,
    ManagedReleaseMember,
    ManagedReleaseView,
)
from refspec.release_graph import rulespec_graph_digest
from refspec.storage import canonical_json

FORMAT_ID = "refspec-vocabulary-atlas-nquads-1.0"
SCHEMA_VERSION = "1.0"
ATLAS_FILE = "atlas.nq"
MANIFEST_FILE = "atlas-manifest.json"
CROSSWALK_MEDIA_TYPE = "application/vnd.refspec.vocabulary-atlas-crosswalk+json"

ATLAS = Namespace("https://refspec.org/ns/vocabulary-atlas/v1#")
RKAF = Namespace("https://rulespec.org/ns/v1#")

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>]+$")
_DECIMAL = re.compile(r"^(?:0|1|2)(?:\.[0-9]+)?$")
_MAPPING_RELATIONS = frozenset(
    {
        "http://www.w3.org/2004/02/skos/core#exactMatch",
        "http://www.w3.org/2004/02/skos/core#closeMatch",
        "http://www.w3.org/2004/02/skos/core#broadMatch",
        "http://www.w3.org/2004/02/skos/core#narrowMatch",
        "http://www.w3.org/2004/02/skos/core#relatedMatch",
    }
)
_ARTIFACT_ROLES = frozenset(
    {"evidence", "inputContext", "validationRequest", "validationResponse"}
)
_CORE_RELEASE_STATUSES = frozenset({"fixture", "candidate", "published"})
_CORE_ARTIFACT_MANIFESTS = (
    "conformance_fixture_artifacts",
    "schema_artifacts",
    "validator_artifacts",
)
_CORE_ARTIFACT_FIELDS = frozenset({"artifact_digest", "media_type", "name"})
_CORE_RELEASE_FIELDS = frozenset(
    {
        "record_type",
        "release_digest",
        "release_id",
        "release_status",
        "version",
        *_CORE_ARTIFACT_MANIFESTS,
    }
)
_FEEDBACK_DISPOSITIONS = frozenset({"supports", "challenges", "comment"})
_POLICIES = MappingProxyType(
    {
        "releaseFacts": "copiedManagedReleaseFactsOnly",
        "analysis": "replaceableMachineAnalysis",
        "labelEquality": "clusterOnly",
        "mappingEligibility": "twoIndependentMachinesSearchOnly",
        "humanFeedback": "appendOnlyNonAuthorizing",
    }
)
_IMPLEMENTATION_SOURCE_PATHS = (
    "atlas/__init__.py",
    "atlas/federal_register.py",
    "atlas/model.py",
    "atlas/queries.py",
    "binding.py",
    "generated_rulespec_dependency.py",
    "immutable.py",
    "managed_release.py",
    "registry/federal_register_thesaurus.py",
    "registry/federal_register_thesaurus_2025.py",
    "registry/federal_register_thesaurus_2025_managed_release.py",
    "registry/federal_register_vocabulary_policy.py",
    "release_graph.py",
    "storage.py",
    "vocabulary.py",
)


class VocabularyAtlasError(ValueError):
    """The atlas or one of its exact inputs is invalid."""


class AtlasReleaseFactsView(Protocol):
    """Small verified view needed to project one release into an atlas."""

    @property
    def release_id(self) -> str: ...

    @property
    def rulespec_graph_id(self) -> str: ...

    @property
    def rulespec_graph(self) -> Mapping[str, Any]: ...

    def iter_members(self) -> Iterable[ManagedReleaseMember]: ...

    def lookup_member(self, member_iri: str) -> ManagedReleaseMember | None: ...

    def iter_expressions(self) -> Iterable[ManagedReleaseExpression]: ...


class VerifiedManagedReleaseSource(Protocol):
    """Producer-neutral source of exact release facts and its publication pin."""

    def verified_view(self) -> AtlasReleaseFactsView: ...

    def pin(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class _ResolvedManagedRelease:
    """One verified view bound to the exact pin checked for this build."""

    view: AtlasReleaseFactsView
    pin: Mapping[str, Any]


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_plain(child) for child in value]
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(child) for key, child in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(_freeze(child) for child in value)
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        binding.validate_canonical_value(value)
    except (TypeError, ValueError) as error:
        raise VocabularyAtlasError(str(error)) from error
    return (canonical_json(value) + "\n").encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _digest_value(value: object) -> str:
    return _digest_bytes(_canonical_bytes(value).removesuffix(b"\n"))


def _require_digest(value: object, label: str) -> str:
    result = str(value or "")
    if _SHA256.fullmatch(result) is None:
        raise VocabularyAtlasError(f"{label} must be sha256:<64 lowercase hex>")
    return result


def _require_iri(value: object, label: str) -> str:
    result = str(value or "")
    if _ABSOLUTE_IRI.fullmatch(result) is None:
        raise VocabularyAtlasError(f"{label} must be an absolute IRI")
    return result


def _require_text(value: object, label: str) -> str:
    result = str(value).strip() if isinstance(value, str) else ""
    if not result:
        raise VocabularyAtlasError(f"{label} is required")
    return result


def _reference(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"id", "digest"}:
        raise VocabularyAtlasError(f"{label} must contain exactly id and digest")
    return {
        "id": _require_iri(value.get("id"), f"{label} id"),
        "digest": _require_digest(value.get("digest"), f"{label} digest"),
    }


def _seal_record(
    *,
    record_type: str,
    id_prefix: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if set(payload) & {"id", "type", "canonicalPayloadDigest"}:
        raise VocabularyAtlasError("sealed payload contains reserved fields")
    basis = {"type": record_type, **_plain(payload)}
    identity_digest = binding.canonical_payload_digest(basis)
    record = {
        "id": id_prefix + identity_digest.removeprefix("sha256:"),
        **basis,
    }
    record["canonicalPayloadDigest"] = binding.canonical_payload_digest(record)
    return record


def _verify_sealed_record(
    record: Mapping[str, Any],
    *,
    record_type: str,
    id_prefix: str,
) -> None:
    plain = _plain(record)
    if plain.get("type") != record_type:
        raise VocabularyAtlasError(f"record type must be {record_type}")
    actual = plain.get("canonicalPayloadDigest")
    expected = binding.canonical_payload_digest(plain)
    if actual != expected:
        raise VocabularyAtlasError("record canonicalPayloadDigest differs")
    basis = {key: value for key, value in plain.items() if key not in {"id", "canonicalPayloadDigest"}}
    identity_digest = binding.canonical_payload_digest(basis)
    if plain.get("id") != id_prefix + identity_digest.removeprefix("sha256:"):
        raise VocabularyAtlasError("record content-derived id differs")


def _load_json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise VocabularyAtlasError(f"{label} is not strict UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise VocabularyAtlasError(f"{label} root must be a JSON object")
    try:
        binding.validate_canonical_value(value)
    except (TypeError, ValueError) as error:
        raise VocabularyAtlasError(str(error)) from error
    return value


def _read_exact_file(path: Path | str, label: str) -> tuple[Path, bytes]:
    selected = Path(path)
    if selected.is_symlink():
        raise VocabularyAtlasError(f"{label} must not be a symlink")
    try:
        selected = selected.resolve(strict=True)
    except FileNotFoundError as error:
        raise VocabularyAtlasError(f"{label} does not exist") from error
    if not selected.is_file():
        raise VocabularyAtlasError(f"{label} must be a regular file")
    return selected, selected.read_bytes()


def _normalize_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _implementation_pin() -> dict[str, Any]:
    package_root = Path(__file__).parents[1]
    sources = [
        {
            "path": f"refspec/{relative}",
            "digest": _digest_bytes((package_root / relative).read_bytes()),
        }
        for relative in _IMPLEMENTATION_SOURCE_PATHS
    ]
    return {
        "id": "urn:ref:implementation:vocabulary-atlas:1.0",
        "version": "1.0",
        "sourceModules": sources,
        "runtime": {
            "jsonschemaVersion": importlib.metadata.version("jsonschema"),
            "pyarrowVersion": importlib.metadata.version("pyarrow"),
            "pythonRequirement": ">=3.10",
            "pythonVersion": platform.python_version(),
            "rdflibVersion": importlib.metadata.version("rdflib"),
        },
    }


@dataclass(frozen=True, slots=True)
class PinnedManagedRelease:
    """One exact managed-bundle manifest and its verified read view."""

    manifest_path: Path
    manifest_digest: str
    view: ManagedReleaseView

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> Self:
        digest = _require_digest(expected_manifest_digest, "managed release manifest digest")
        view = ManagedReleaseView.open(
            manifest_path,
            expected_manifest_digest=digest,
        )
        return cls(Path(manifest_path).resolve(strict=True), digest, view)

    def verified_view(self) -> ManagedReleaseView:
        """Reopen the manifest so later file changes fail closed."""

        return ManagedReleaseView.open(
            self.manifest_path,
            expected_manifest_digest=self.manifest_digest,
        )

    def pin(self) -> dict[str, Any]:
        view = self.verified_view()
        return {
            "role": "ManagedReleaseView",
            "manifestDigest": self.manifest_digest,
            "publicationReleaseId": view.release_id,
            "rulespecGraph": {
                "id": view.rulespec_graph_id,
                "digest": rulespec_graph_digest(_plain(view.rulespec_graph)),
            },
        }


def _require_core_release_contract(record: Mapping[str, Any]) -> None:
    """Reject a pinned file that is not a complete Rulespec Core release.

    Matching digests prove only that the bytes are the pinned bytes.  This
    check proves the bytes are a Core release: without it a file containing
    just ``{"record_type": "RulespecCoreRelease"}`` pins cleanly and publishes
    an atlas that claims Rulespec Core conformance it cannot support.

    RefSpec reimplements the required-field contract published in Rulespec's
    ``release-records/schemas/rulespec-core-release.schema.json`` rather than
    importing Rulespec, so the atlas keeps its file-only dependency.
    """

    missing = sorted(_CORE_RELEASE_FIELDS - set(record))
    if missing:
        raise VocabularyAtlasError(f"Rulespec Core release omits required fields {missing!r}")
    unsupported = sorted(set(record) - _CORE_RELEASE_FIELDS)
    if unsupported:
        raise VocabularyAtlasError(f"Rulespec Core release contains unsupported fields {unsupported!r}")
    if record["release_status"] not in _CORE_RELEASE_STATUSES:
        raise VocabularyAtlasError("Rulespec Core release_status must be fixture, candidate, or published")
    _require_text(record["version"], "Rulespec Core version")
    for field in _CORE_ARTIFACT_MANIFESTS:
        entries = record[field]
        if not isinstance(entries, list) or not entries:
            raise VocabularyAtlasError(f"Rulespec Core {field} must list at least one artifact")
        for index, entry in enumerate(entries):
            label = f"Rulespec Core {field}[{index}]"
            if not isinstance(entry, Mapping) or set(entry) != _CORE_ARTIFACT_FIELDS:
                raise VocabularyAtlasError(f"{label} must contain exactly name, media_type, and artifact_digest")
            _require_text(entry["name"], f"{label} name")
            _require_text(entry["media_type"], f"{label} media_type")
            _require_digest(entry["artifact_digest"], f"{label} artifact_digest")


@dataclass(frozen=True, slots=True)
class PinnedRulespecCoreRelease:
    """Exact external Rulespec Core release bytes used by the atlas."""

    path: Path
    file_digest: str
    release_id: str
    release_digest: str

    @classmethod
    def open(
        cls,
        path: Path | str,
        *,
        expected_file_digest: str,
        expected_release_id: str,
        expected_release_digest: str,
    ) -> Self:
        expected_file_digest = _require_digest(expected_file_digest, "Rulespec Core file digest")
        expected_release_id = _require_iri(expected_release_id, "Rulespec Core release id")
        expected_release_digest = _require_digest(expected_release_digest, "Rulespec Core release digest")
        resolved, raw = _read_exact_file(path, "Rulespec Core release")
        if _digest_bytes(raw) != expected_file_digest:
            raise VocabularyAtlasError("Rulespec Core file digest differs")
        record = _load_json_object(raw, "Rulespec Core release")
        if record.get("record_type") != "RulespecCoreRelease":
            raise VocabularyAtlasError("Rulespec Core record_type differs")
        _require_core_release_contract(record)
        if record.get("release_id") != expected_release_id:
            raise VocabularyAtlasError("Rulespec Core release id differs")
        if record.get("release_digest") != expected_release_digest:
            raise VocabularyAtlasError("Rulespec Core release digest differs")
        preimage = {key: value for key, value in record.items() if key not in {"release_id", "release_digest"}}
        if _digest_value(preimage) != expected_release_digest:
            raise VocabularyAtlasError("Rulespec Core content-derived release digest differs")
        expected_id = "urn:rulespec:core:" + expected_release_digest.removeprefix("sha256:")
        if expected_release_id != expected_id:
            raise VocabularyAtlasError("Rulespec Core content-derived id differs")
        return cls(
            path=resolved,
            file_digest=expected_file_digest,
            release_id=expected_release_id,
            release_digest=expected_release_digest,
        )

    def verify(self) -> None:
        self.open(
            self.path,
            expected_file_digest=self.file_digest,
            expected_release_id=self.release_id,
            expected_release_digest=self.release_digest,
        )

    def pin(self) -> dict[str, str]:
        self.verify()
        return {
            "role": "RulespecCoreRelease",
            "fileDigest": self.file_digest,
            "releaseId": self.release_id,
            "releaseDigest": self.release_digest,
        }


@dataclass(frozen=True, slots=True)
class CrosswalkArtifact:
    """A sealed evidence, request, or response artifact in a crosswalk bundle."""

    _record: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        role: Literal[
            "evidence",
            "inputContext",
            "validationRequest",
            "validationResponse",
        ],
        media_type: str,
        content: Mapping[str, Any],
    ) -> Self:
        if role not in _ARTIFACT_ROLES:
            raise VocabularyAtlasError("crosswalk artifact role is unsupported")
        payload = {
            "role": role,
            "mediaType": _require_text(media_type, "artifact media type"),
            "content": _plain(content),
        }
        return cls(
            cast(
                Mapping[str, Any],
                _freeze(
                    _seal_record(
                        record_type="urn:ref:type:VocabularyAtlasCrosswalkArtifact",
                        id_prefix="urn:ref:vocabulary-atlas-artifact:",
                        payload=payload,
                    )
                ),
            )
        )

    @property
    def identifier(self) -> str:
        return str(self._record["id"])

    @property
    def digest(self) -> str:
        return str(self._record["canonicalPayloadDigest"])

    @property
    def role(self) -> str:
        return str(self._record["role"])

    @property
    def content_digest(self) -> str:
        """Digest the sealed content alone, which is what a candidate cites.

        ``canonicalPayloadDigest`` also covers the role and media type, so it
        cannot be what ``inputContextDigest`` names.
        """

        return _artifact_content_digest(self._record)

    def reference(self) -> dict[str, str]:
        return {"id": self.identifier, "digest": self.digest}

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self._record))


def _artifact_content_digest(record: Mapping[str, Any]) -> str:
    return binding.canonical_sha256(_plain(record["content"]))


@dataclass(frozen=True, slots=True)
class MappingCandidate:
    """One model- or agent-generated cross-release mapping proposal."""

    _record: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        source_member: str,
        source_release: str,
        target_member: str,
        target_release: str,
        proposed_relation: str,
        generator_kind: Literal["aiModel", "aiAgent"],
        generator_actor: str,
        generator_provider: str,
        model_id: str,
        model_version: str,
        prompt_template: str,
        input_context_digest: str,
        temperature: str,
        evidence: Sequence[Mapping[str, str]],
        generated_at: str,
        seed: int | None = None,
    ) -> Self:
        source_member = _require_iri(source_member, "candidate source member")
        source_release = _require_iri(source_release, "candidate source release")
        target_member = _require_iri(target_member, "candidate target member")
        target_release = _require_iri(target_release, "candidate target release")
        proposed_relation = _require_iri(proposed_relation, "candidate proposed relation")
        if source_release == target_release:
            raise VocabularyAtlasError("a crosswalk candidate must cross releases")
        if source_member == target_member:
            raise VocabularyAtlasError("a crosswalk candidate needs distinct members")
        if proposed_relation not in _MAPPING_RELATIONS:
            raise VocabularyAtlasError("candidate mapping relation is unsupported")
        if generator_kind not in {"aiModel", "aiAgent"}:
            raise VocabularyAtlasError("candidate generator kind is unsupported")
        if not isinstance(temperature, str) or _DECIMAL.fullmatch(temperature) is None:
            raise VocabularyAtlasError("candidate temperature must be a canonical decimal string")
        try:
            parsed_temperature = Decimal(temperature)
        except InvalidOperation as error:
            raise VocabularyAtlasError("candidate temperature is invalid") from error
        if parsed_temperature < 0 or parsed_temperature > 2:
            raise VocabularyAtlasError("candidate temperature must be between 0 and 2")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            raise VocabularyAtlasError("candidate seed must be an integer")
        evidence_refs = [_reference(item, "candidate evidence") for item in evidence]
        if not evidence_refs:
            raise VocabularyAtlasError("candidate evidence must not be empty")
        payload: dict[str, Any] = {
            "sourceMember": source_member,
            "sourceRelease": source_release,
            "targetMember": target_member,
            "targetRelease": target_release,
            "proposedRelation": proposed_relation,
            "generatorKind": generator_kind,
            "generatorActor": _require_iri(generator_actor, "candidate generator actor"),
            "generatorProvider": _require_iri(generator_provider, "candidate generator provider"),
            "modelId": _require_text(model_id, "candidate model id"),
            "modelVersion": _require_text(model_version, "candidate model version"),
            "promptTemplate": _require_iri(prompt_template, "candidate prompt template"),
            "inputContextDigest": _require_digest(input_context_digest, "candidate input context digest"),
            "temperature": temperature,
            "evidence": evidence_refs,
            "generatedAt": _require_text(generated_at, "candidate generated timestamp"),
        }
        if seed is not None:
            payload["seed"] = seed
        return cls(
            cast(
                Mapping[str, Any],
                _freeze(
                    _seal_record(
                        record_type="urn:ref:type:VocabularyAtlasMappingCandidate",
                        id_prefix="urn:ref:vocabulary-atlas-mapping-candidate:",
                        payload=payload,
                    )
                ),
            )
        )

    @property
    def identifier(self) -> str:
        return str(self._record["id"])

    @property
    def digest(self) -> str:
        return str(self._record["canonicalPayloadDigest"])

    def reference(self) -> dict[str, str]:
        return {"id": self.identifier, "digest": self.digest}

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self._record))


@dataclass(frozen=True, slots=True)
class MachineValidation:
    """A sealed machine result; qualification still requires an independent pair."""

    _record: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        candidate: Mapping[str, str],
        validator_kind: Literal["aiModel", "aiAgent"],
        validator_actor: str,
        independence_group: str,
        provider: str,
        provider_model_id: str,
        sealed_input_digest: str,
        request_artifact: Mapping[str, str],
        response_artifact: Mapping[str, str],
        deterministic_checks_passed: bool,
        outcome: Literal["supports", "rejects", "abstains"],
        completed_at: str,
    ) -> Self:
        if validator_kind not in {"aiModel", "aiAgent"}:
            raise VocabularyAtlasError("validator kind is unsupported")
        if outcome not in {"supports", "rejects", "abstains"}:
            raise VocabularyAtlasError("machine validation outcome is unsupported")
        if not isinstance(deterministic_checks_passed, bool):
            raise VocabularyAtlasError("deterministicChecksPassed must be boolean")
        payload = {
            "candidate": _reference(candidate, "machine candidate"),
            "validatorKind": validator_kind,
            "validatorActor": _require_iri(validator_actor, "machine validator actor"),
            "independenceGroup": _require_iri(independence_group, "machine independence group"),
            "provider": _require_iri(provider, "machine provider"),
            "providerModelId": _require_text(provider_model_id, "machine provider model id"),
            "sealedInputDigest": _require_digest(sealed_input_digest, "machine sealed input digest"),
            "requestArtifact": _reference(request_artifact, "machine request artifact"),
            "responseArtifact": _reference(response_artifact, "machine response artifact"),
            "deterministicChecksPassed": deterministic_checks_passed,
            "outcome": outcome,
            "completedAt": _require_text(completed_at, "machine completed timestamp"),
        }
        return cls(
            cast(
                Mapping[str, Any],
                _freeze(
                    _seal_record(
                        record_type="urn:ref:type:VocabularyAtlasMachineValidation",
                        id_prefix="urn:ref:vocabulary-atlas-machine-validation:",
                        payload=payload,
                    )
                ),
            )
        )

    @property
    def identifier(self) -> str:
        return str(self._record["id"])

    @property
    def digest(self) -> str:
        return str(self._record["canonicalPayloadDigest"])

    def reference(self) -> dict[str, str]:
        return {"id": self.identifier, "digest": self.digest}

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self._record))


@dataclass(frozen=True, slots=True)
class MappingFeedback:
    """Optional human feedback that never changes current eligibility."""

    _record: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        candidate: Mapping[str, str],
        actor: str,
        disposition: Literal["supports", "challenges", "comment"],
        comment: str,
        recorded_at: str,
    ) -> Self:
        if disposition not in _FEEDBACK_DISPOSITIONS:
            raise VocabularyAtlasError("mapping feedback disposition is unsupported")
        payload = {
            "candidate": _reference(candidate, "feedback candidate"),
            "actor": _require_iri(actor, "feedback actor"),
            "disposition": disposition,
            "comment": _require_text(comment, "feedback comment"),
            "recordedAt": _require_text(recorded_at, "feedback timestamp"),
        }
        return cls(
            cast(
                Mapping[str, Any],
                _freeze(
                    _seal_record(
                        record_type="urn:ref:type:VocabularyAtlasMappingFeedback",
                        id_prefix="urn:ref:vocabulary-atlas-mapping-feedback:",
                        payload=payload,
                    )
                ),
            )
        )

    @property
    def identifier(self) -> str:
        return str(self._record["id"])

    @property
    def digest(self) -> str:
        return str(self._record["canonicalPayloadDigest"])

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self._record))


@dataclass(frozen=True, slots=True)
class CrosswalkBundle:
    """Closed crosswalk input with machine validation and optional feedback."""

    _record: Mapping[str, Any]

    @classmethod
    def open(
        cls,
        path: Path | str,
        *,
        expected_file_digest: str,
        expected_bundle_digest: str,
    ) -> Self:
        """Open one exact canonical crosswalk bundle file and close every reference."""

        expected_file_digest = _require_digest(expected_file_digest, "crosswalk file digest")
        expected_bundle_digest = _require_digest(expected_bundle_digest, "crosswalk bundle digest")
        _, raw = _read_exact_file(path, "crosswalk bundle")
        if _digest_bytes(raw) != expected_file_digest:
            raise VocabularyAtlasError("crosswalk file digest differs")
        record = _load_json_object(raw, "crosswalk bundle")
        if _canonical_bytes(record) != raw:
            raise VocabularyAtlasError("crosswalk bundle bytes are not canonical")
        bundle = cls(cast(Mapping[str, Any], _freeze(record)))
        bundle.verify()
        if bundle.digest != expected_bundle_digest:
            raise VocabularyAtlasError("crosswalk bundle digest differs")
        return bundle

    @classmethod
    def create(
        cls,
        *,
        artifacts: Sequence[CrosswalkArtifact],
        mapping_candidates: Sequence[MappingCandidate],
        machine_validations: Sequence[MachineValidation] = (),
        feedback: Sequence[MappingFeedback] = (),
    ) -> Self:
        artifact_records = _unique_records(artifacts, "crosswalk artifact")
        candidate_records = _unique_records(mapping_candidates, "mapping candidate")
        validation_records = _unique_records(machine_validations, "machine validation")
        feedback_records = _unique_records(feedback, "mapping feedback")
        _validate_crosswalk_closure(
            artifacts=artifact_records,
            candidates=candidate_records,
            validations=validation_records,
            feedback=feedback_records,
        )
        record = _seal_record(
            record_type="urn:ref:type:VocabularyAtlasCrosswalkBundle",
            id_prefix="urn:ref:vocabulary-atlas-crosswalk-bundle:",
            payload={
                "schemaVersion": SCHEMA_VERSION,
                "artifacts": [artifact_records[key] for key in sorted(artifact_records)],
                "mappingCandidates": [candidate_records[key] for key in sorted(candidate_records)],
                "machineValidations": [validation_records[key] for key in sorted(validation_records)],
                "feedback": [feedback_records[key] for key in sorted(feedback_records)],
            },
        )
        return cls(cast(Mapping[str, Any], _freeze(record)))

    @property
    def identifier(self) -> str:
        return str(self._record["id"])

    @property
    def digest(self) -> str:
        return str(self._record["canonicalPayloadDigest"])

    def pin(self) -> dict[str, str]:
        self.verify()
        return {
            "role": "CrosswalkBundle",
            "id": self.identifier,
            "digest": self.digest,
            "fileDigest": _digest_bytes(self.canonical_bytes()),
            "mediaType": CROSSWALK_MEDIA_TYPE,
        }

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self._record))

    def canonical_bytes(self) -> bytes:
        self.verify()
        return _canonical_bytes(self.to_dict())

    def write(self, path: Path | str) -> Path:
        """Write one immutable canonical bundle file without overwriting bytes."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(self.canonical_bytes())
        except FileExistsError as error:
            raise VocabularyAtlasError("crosswalk bundle destination already exists") from error
        return target

    def verify(self) -> None:
        record = self.to_dict()
        expected_fields = {
            "id",
            "type",
            "schemaVersion",
            "artifacts",
            "mappingCandidates",
            "machineValidations",
            "feedback",
            "canonicalPayloadDigest",
        }
        if set(record) != expected_fields:
            raise VocabularyAtlasError("crosswalk bundle fields differ from v1")
        _verify_sealed_record(
            record,
            record_type="urn:ref:type:VocabularyAtlasCrosswalkBundle",
            id_prefix="urn:ref:vocabulary-atlas-crosswalk-bundle:",
        )
        if record["schemaVersion"] != SCHEMA_VERSION:
            raise VocabularyAtlasError("crosswalk bundle schemaVersion differs")
        artifacts = _index_serialized_records(record["artifacts"], "crosswalk artifact")
        candidates = _index_serialized_records(record["mappingCandidates"], "mapping candidate")
        validations = _index_serialized_records(record["machineValidations"], "machine validation")
        feedback = _index_serialized_records(record["feedback"], "mapping feedback")
        _validate_crosswalk_closure(
            artifacts=artifacts,
            candidates=candidates,
            validations=validations,
            feedback=feedback,
        )

    def with_feedback(self, *items: MappingFeedback) -> Self:
        """Return a new bundle that retains every existing feedback record."""

        self.verify()
        record = self.to_dict()
        existing = {str(item["id"]): item for item in cast(list[dict[str, Any]], record["feedback"])}
        for item in items:
            if item.identifier in existing:
                raise VocabularyAtlasError("mapping feedback is already present")
            existing[item.identifier] = item.to_dict()
        artifacts = [_artifact_from_record(item) for item in record["artifacts"]]
        candidates = [_candidate_from_record(item) for item in record["mappingCandidates"]]
        validations = [_validation_from_record(item) for item in record["machineValidations"]]
        feedback = [_feedback_from_record(item) for item in existing.values()]
        return type(self).create(
            artifacts=artifacts,
            mapping_candidates=candidates,
            machine_validations=validations,
            feedback=feedback,
        )

    def qualified(self) -> dict[str, tuple[dict[str, Any], ...]]:
        self.verify()
        record = self.to_dict()
        candidates = {item["id"]: item for item in record["mappingCandidates"]}
        validations = {item["id"]: item for item in record["machineValidations"]}
        return _qualified_candidates(candidates, validations)


def _unique_records(values: Sequence[Any], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        record = value.to_dict()
        identifier = str(record["id"])
        if identifier in result:
            raise VocabularyAtlasError(f"duplicate {label}: {identifier}")
        result[identifier] = record
    return result


def _index_serialized_records(value: object, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise VocabularyAtlasError(f"{label} collection must be a JSON array")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise VocabularyAtlasError(f"{label} must be a JSON object with an id")
        identifier = item["id"]
        if identifier in result:
            raise VocabularyAtlasError(f"duplicate {label}: {identifier}")
        result[identifier] = item
    return result


def _resolve_reference(
    reference: object,
    records: Mapping[str, Mapping[str, Any]],
    label: str,
) -> Mapping[str, Any]:
    exact = _reference(reference, label)
    record = records.get(exact["id"])
    if record is None or record.get("canonicalPayloadDigest") != exact["digest"]:
        raise VocabularyAtlasError(f"{label} does not close against the bundle")
    return record


def _resolve_input_context(
    input_context_digest: object,
    artifacts: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Return the one bundled artifact whose bytes produce the cited digest.

    Machine validations agreeing on a digest proves nothing about the model
    input unless those bytes are in the closure a consumer receives, so the
    digest MUST name an ``inputContext`` artifact present in this bundle.
    """

    digest = _require_digest(input_context_digest, "candidate input context digest")
    matches = sorted(
        record["id"]
        for record in artifacts.values()
        if record["role"] == "inputContext" and _artifact_content_digest(record) == digest
    )
    if not matches:
        raise VocabularyAtlasError(
            "candidate input context does not close against the bundle"
        )
    if len(matches) > 1:
        raise VocabularyAtlasError("candidate input context resolves to several artifacts")
    return artifacts[matches[0]]


def _validate_crosswalk_closure(
    *,
    artifacts: Mapping[str, Mapping[str, Any]],
    candidates: Mapping[str, Mapping[str, Any]],
    validations: Mapping[str, Mapping[str, Any]],
    feedback: Mapping[str, Mapping[str, Any]],
) -> None:
    for record in artifacts.values():
        _artifact_from_record(record)
    for record in candidates.values():
        _candidate_from_record(record)
        for evidence in record["evidence"]:
            artifact = _resolve_reference(evidence, artifacts, "candidate evidence")
            if artifact["role"] != "evidence":
                raise VocabularyAtlasError("candidate evidence has the wrong role")
        _resolve_input_context(record["inputContextDigest"], artifacts)
    for record in validations.values():
        _validation_from_record(record)
        candidate = _resolve_reference(record["candidate"], candidates, "machine candidate")
        request = _resolve_reference(record["requestArtifact"], artifacts, "machine request artifact")
        response = _resolve_reference(record["responseArtifact"], artifacts, "machine response artifact")
        if request["role"] != "validationRequest":
            raise VocabularyAtlasError("machine request artifact has the wrong role")
        if response["role"] != "validationResponse":
            raise VocabularyAtlasError("machine response artifact has the wrong role")
        if record["sealedInputDigest"] != candidate["inputContextDigest"]:
            raise VocabularyAtlasError("machine validation uses another sealed input")
        request_content = request["content"]
        if (
            not isinstance(request_content, Mapping)
            or request_content.get("inputDigest") != candidate["inputContextDigest"]
            or request_content.get("candidate") != record["candidate"]
        ):
            raise VocabularyAtlasError("machine request does not seal the candidate and input")
        response_content = response["content"]
        if (
            not isinstance(response_content, Mapping)
            or response_content.get("candidate") != record["candidate"]
            or response_content.get("inputDigest") != candidate["inputContextDigest"]
            or response_content.get("requestArtifact") != record["requestArtifact"]
            or response_content.get("validatorActor") != record["validatorActor"]
            or response_content.get("provider") != record["provider"]
            or response_content.get("providerModelId") != record["providerModelId"]
            or response_content.get("outcome") != record["outcome"]
            or response_content.get("deterministicChecksPassed") is not record["deterministicChecksPassed"]
        ):
            raise VocabularyAtlasError("machine response does not seal its validator result")
    for record in feedback.values():
        _feedback_from_record(record)
        _resolve_reference(record["candidate"], candidates, "feedback candidate")


def _qualified_candidates(
    candidates: Mapping[str, Mapping[str, Any]],
    validations: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in validations.values():
        if record["outcome"] == "supports" and record["deterministicChecksPassed"] is True:
            by_candidate[record["candidate"]["id"]].append(dict(record))
    qualified: dict[str, tuple[dict[str, Any], ...]] = {}
    for candidate_id, candidate in candidates.items():
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for validation in by_candidate.get(candidate_id, []):
            if validation["sealedInputDigest"] != candidate["inputContextDigest"]:
                continue
            request = validation["requestArtifact"]
            key = (
                validation["sealedInputDigest"],
                request["id"],
                request["digest"],
            )
            grouped[key].append(validation)
        for key in sorted(grouped):
            values = sorted(grouped[key], key=lambda item: item["id"])
            pair = next(
                (
                    pair
                    for pair in itertools.combinations(values, 2)
                    if pair[0]["validatorActor"] != pair[1]["validatorActor"]
                    and pair[0]["independenceGroup"] != pair[1]["independenceGroup"]
                    and pair[0]["provider"] != pair[1]["provider"]
                    and pair[0]["providerModelId"] != pair[1]["providerModelId"]
                    and pair[0]["responseArtifact"] != pair[1]["responseArtifact"]
                ),
                None,
            )
            if pair is not None:
                qualified[candidate_id] = cast(tuple[dict[str, Any], ...], pair)
                break
    return qualified


def _artifact_from_record(record: Mapping[str, Any]) -> CrosswalkArtifact:
    _verify_sealed_record(
        record,
        record_type="urn:ref:type:VocabularyAtlasCrosswalkArtifact",
        id_prefix="urn:ref:vocabulary-atlas-artifact:",
    )
    if set(record) != {
        "id",
        "type",
        "role",
        "mediaType",
        "content",
        "canonicalPayloadDigest",
    }:
        raise VocabularyAtlasError("crosswalk artifact fields differ from v1")
    rebuilt = CrosswalkArtifact.create(
        role=record["role"],  # type: ignore[arg-type]
        media_type=record["mediaType"],
        content=record["content"],
    )
    if rebuilt.to_dict() != _plain(record):
        raise VocabularyAtlasError("crosswalk artifact content differs")
    return rebuilt


def _candidate_from_record(record: Mapping[str, Any]) -> MappingCandidate:
    _verify_sealed_record(
        record,
        record_type="urn:ref:type:VocabularyAtlasMappingCandidate",
        id_prefix="urn:ref:vocabulary-atlas-mapping-candidate:",
    )
    required = {
        "id",
        "type",
        "sourceMember",
        "sourceRelease",
        "targetMember",
        "targetRelease",
        "proposedRelation",
        "generatorKind",
        "generatorActor",
        "generatorProvider",
        "modelId",
        "modelVersion",
        "promptTemplate",
        "inputContextDigest",
        "temperature",
        "evidence",
        "generatedAt",
        "canonicalPayloadDigest",
    }
    if not required <= set(record) or set(record) - required != ({"seed"} if "seed" in record else set()):
        raise VocabularyAtlasError("mapping candidate fields differ from v1")
    rebuilt = MappingCandidate.create(
        source_member=record["sourceMember"],
        source_release=record["sourceRelease"],
        target_member=record["targetMember"],
        target_release=record["targetRelease"],
        proposed_relation=record["proposedRelation"],
        generator_kind=record["generatorKind"],  # type: ignore[arg-type]
        generator_actor=record["generatorActor"],
        generator_provider=record["generatorProvider"],
        model_id=record["modelId"],
        model_version=record["modelVersion"],
        prompt_template=record["promptTemplate"],
        input_context_digest=record["inputContextDigest"],
        temperature=record["temperature"],
        evidence=record["evidence"],
        generated_at=record["generatedAt"],
        seed=record.get("seed"),
    )
    if rebuilt.to_dict() != _plain(record):
        raise VocabularyAtlasError("mapping candidate content differs")
    return rebuilt


def _validation_from_record(record: Mapping[str, Any]) -> MachineValidation:
    _verify_sealed_record(
        record,
        record_type="urn:ref:type:VocabularyAtlasMachineValidation",
        id_prefix="urn:ref:vocabulary-atlas-machine-validation:",
    )
    if set(record) != {
        "id",
        "type",
        "candidate",
        "validatorKind",
        "validatorActor",
        "independenceGroup",
        "provider",
        "providerModelId",
        "sealedInputDigest",
        "requestArtifact",
        "responseArtifact",
        "deterministicChecksPassed",
        "outcome",
        "completedAt",
        "canonicalPayloadDigest",
    }:
        raise VocabularyAtlasError("machine validation fields differ from v1")
    rebuilt = MachineValidation.create(
        candidate=record["candidate"],
        validator_kind=record["validatorKind"],  # type: ignore[arg-type]
        validator_actor=record["validatorActor"],
        independence_group=record["independenceGroup"],
        provider=record["provider"],
        provider_model_id=record["providerModelId"],
        sealed_input_digest=record["sealedInputDigest"],
        request_artifact=record["requestArtifact"],
        response_artifact=record["responseArtifact"],
        deterministic_checks_passed=record["deterministicChecksPassed"],
        outcome=record["outcome"],  # type: ignore[arg-type]
        completed_at=record["completedAt"],
    )
    if rebuilt.to_dict() != _plain(record):
        raise VocabularyAtlasError("machine validation content differs")
    return rebuilt


def _feedback_from_record(record: Mapping[str, Any]) -> MappingFeedback:
    _verify_sealed_record(
        record,
        record_type="urn:ref:type:VocabularyAtlasMappingFeedback",
        id_prefix="urn:ref:vocabulary-atlas-mapping-feedback:",
    )
    if set(record) != {
        "id",
        "type",
        "candidate",
        "actor",
        "disposition",
        "comment",
        "recordedAt",
        "canonicalPayloadDigest",
    }:
        raise VocabularyAtlasError("mapping feedback fields differ from v1")
    rebuilt = MappingFeedback.create(
        candidate=record["candidate"],
        actor=record["actor"],
        disposition=record["disposition"],  # type: ignore[arg-type]
        comment=record["comment"],
        recorded_at=record["recordedAt"],
    )
    if rebuilt.to_dict() != _plain(record):
        raise VocabularyAtlasError("mapping feedback content differs")
    return rebuilt


def _canonical_nquads(dataset: Dataset) -> bytes:
    if any(isinstance(term, BNode) for context in dataset.graphs() for triple in context for term in triple):
        raise VocabularyAtlasError("atlas must not contain blank nodes")
    serialized = dataset.serialize(format="nquads")
    text = serialized.decode("utf-8") if isinstance(serialized, bytes) else serialized
    lines = sorted(line.strip() for line in text.splitlines() if line.strip())
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _stable_iri(prefix: str, *parts: str) -> URIRef:
    digest = _digest_value({"prefix": prefix, "parts": list(parts)})
    return URIRef(f"urn:ref:vocabulary-atlas-{prefix}:{digest.removeprefix('sha256:')}")


def _build_dataset(
    releases: Sequence[_ResolvedManagedRelease],
    *,
    asset_id: str,
    crosswalk: CrosswalkBundle | None,
) -> tuple[bytes, dict[str, int], str, str]:
    release_graph_id = asset_id + ":release-facts"
    analysis_graph_id = asset_id + ":analysis"
    dataset = Dataset(default_union=False)
    release_graph = dataset.graph(URIRef(release_graph_id))
    analysis = dataset.graph(URIRef(analysis_graph_id))

    source_union = Graph()
    views = [item.view for item in releases]
    for view in views:
        source_union.parse(
            data=canonical_json(_plain(view.rulespec_graph)),
            format="json-ld",
        )
    for triple in to_canonical_graph(source_union):
        release_graph.add(
            cast(
                tuple[Any, Any, Any],
                tuple(URIRef(f"{asset_id}:bnode:{term}") if isinstance(term, BNode) else term for term in triple),
            )
        )
    # Some historical managed graphs use a compact JSON-LD context that leaves
    # ``prov:hadMember`` values as literals when parsed generically.  The
    # verified view has already checked these exact release/member pairs, so the
    # portable RDF distribution writes their required resource-valued form.
    for view in views:
        for member in view.iter_members():
            release = URIRef(member.release_iri)
            member_iri = URIRef(member.member_iri)
            release_graph.remove((release, PROV.hadMember, RdfLiteral(member.member_iri)))
            release_graph.add((release, PROV.hadMember, member_iri))

    analysis_root = URIRef(analysis_graph_id)
    analysis.add((analysis_root, RDF.type, ATLAS.ReplaceableAnalysis))
    for view in views:
        analysis.add((analysis_root, PROV.wasDerivedFrom, URIRef(view.release_id)))

    endpoint_releases: dict[str, set[str]] = defaultdict(set)
    labels: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for view in views:
        for member in view.iter_members():
            endpoint_releases[member.member_iri].add(member.release_iri)
            analysis.add(
                (
                    URIRef(member.member_iri),
                    ATLAS.memberOfRelease,
                    URIRef(member.release_iri),
                )
            )
        for expression in view.iter_expressions():
            member = view.lookup_member(expression.member_iri)
            if member is None:
                raise VocabularyAtlasError("release expression has no exact member")
            normalized = _normalize_label(expression.original_literal)
            if normalized:
                labels[normalized].add((expression.member_iri, member.release_iri))

    cluster_count = 0
    for normalized, members in sorted(labels.items()):
        if len(members) < 2 or len({release for _, release in members}) < 2:
            continue
        cluster = _stable_iri("label-cluster", normalized)
        analysis.add((cluster, RDF.type, ATLAS.LabelCluster))
        analysis.add((cluster, ATLAS.normalizedLabel, RdfLiteral(normalized)))
        for member_iri, release_iri in sorted(members):
            analysis.add((cluster, ATLAS.member, URIRef(member_iri)))
            analysis.add((cluster, ATLAS.memberRelease, URIRef(release_iri)))
        cluster_count += 1

    candidate_count = 0
    validation_count = 0
    feedback_count = 0
    search_mapping_count = 0
    if crosswalk is not None:
        bundle = crosswalk.to_dict()
        candidates = {item["id"]: item for item in bundle["mappingCandidates"]}
        validations = {item["id"]: item for item in bundle["machineValidations"]}
        bundle_artifacts = {item["id"]: item for item in bundle["artifacts"]}
        qualified = _qualified_candidates(candidates, validations)
        for artifact in bundle["artifacts"]:
            node = URIRef(artifact["id"])
            analysis.add((node, RDF.type, ATLAS.CrosswalkArtifact))
            analysis.add(
                (
                    node,
                    ATLAS.artifactDigest,
                    RdfLiteral(artifact["canonicalPayloadDigest"]),
                )
            )
            analysis.add((node, ATLAS.artifactRole, RdfLiteral(artifact["role"])))
            if artifact["role"] == "inputContext":
                # Only this role is cited by digest, so only this role needs the
                # content digest published for a consumer to resolve the citation.
                analysis.add(
                    (
                        node,
                        ATLAS.contentDigest,
                        RdfLiteral(_artifact_content_digest(artifact)),
                    )
                )
        for candidate_id, candidate in sorted(candidates.items()):
            source = candidate["sourceMember"]
            target = candidate["targetMember"]
            if candidate["sourceRelease"] not in endpoint_releases.get(source, set()):
                raise VocabularyAtlasError(f"candidate {candidate_id} source is outside its exact release")
            if candidate["targetRelease"] not in endpoint_releases.get(target, set()):
                raise VocabularyAtlasError(f"candidate {candidate_id} target is outside its exact release")
            for release_iri, endpoint_role in (
                (candidate["sourceRelease"], "source"),
                (candidate["targetRelease"], "target"),
            ):
                release_digests = tuple(
                    release_graph.objects(
                        URIRef(release_iri),
                        RKAF.referenceReleaseDigest,
                    )
                )
                if len(release_digests) != 1 or not isinstance(
                    release_digests[0],
                    RdfLiteral,
                ):
                    raise VocabularyAtlasError(
                        f"candidate {candidate_id} {endpoint_role} release lacks one exact digest"
                    )
                _require_digest(
                    str(release_digests[0]),
                    f"candidate {candidate_id} {endpoint_role} release digest",
                )
            node = URIRef(candidate_id)
            analysis.add((node, RDF.type, ATLAS.MappingCandidate))
            analysis.add(
                (
                    node,
                    ATLAS.candidateDigest,
                    RdfLiteral(candidate["canonicalPayloadDigest"]),
                )
            )
            for predicate, field in (
                (ATLAS.sourceMember, "sourceMember"),
                (ATLAS.sourceRelease, "sourceRelease"),
                (ATLAS.targetMember, "targetMember"),
                (ATLAS.targetRelease, "targetRelease"),
                (ATLAS.proposedRelation, "proposedRelation"),
            ):
                analysis.add((node, predicate, URIRef(candidate[field])))
            analysis.add(
                (
                    node,
                    ATLAS.inputContextDigest,
                    RdfLiteral(candidate["inputContextDigest"]),
                )
            )
            analysis.add(
                (
                    node,
                    ATLAS.inputContextArtifact,
                    URIRef(
                        _resolve_input_context(
                            candidate["inputContextDigest"],
                            bundle_artifacts,
                        )["id"]
                    ),
                )
            )
            for evidence in candidate["evidence"]:
                analysis.add((node, ATLAS.evidence, URIRef(evidence["id"])))
            candidate_count += 1

            selected = qualified.get(candidate_id)
            if selected is None:
                analysis.add((node, RKAF.usageEligibility, RKAF.notEligible))
                continue
            analysis.add((node, RKAF.usageEligibility, RKAF.searchOnly))
            mapping = _stable_iri(
                "search-only-mapping",
                candidate_id,
                *(validation["id"] for validation in selected),
            )
            analysis.add((mapping, RDF.type, RKAF.ConceptMapping))
            analysis.add((mapping, RKAF.assertsSubject, URIRef(source)))
            analysis.add((mapping, RKAF.assertsPredicate, URIRef(candidate["proposedRelation"])))
            analysis.add((mapping, RKAF.assertsObject, URIRef(target)))
            analysis.add(
                (
                    mapping,
                    RKAF.sourceConceptRelease,
                    URIRef(candidate["sourceRelease"]),
                )
            )
            analysis.add(
                (
                    mapping,
                    RKAF.targetConceptRelease,
                    URIRef(candidate["targetRelease"]),
                )
            )
            analysis.add((mapping, RKAF.usageEligibility, RKAF.searchOnly))
            analysis.add((mapping, RKAF.assertionOrigin, RKAF.aiSuggested))
            analysis.add((mapping, RKAF.epistemicBasis, RKAF.statisticalInference))
            analysis.add((mapping, ATLAS.qualifiedFrom, node))
            analysis.add(
                (
                    mapping,
                    ATLAS.selectionPolicy,
                    RdfLiteral(_POLICIES["mappingEligibility"]),
                )
            )
            analysis.add(
                (
                    mapping,
                    ATLAS.verificationStatus,
                    ATLAS.machineQualifiedForSearch,
                )
            )
            for validation in selected:
                analysis.add((mapping, ATLAS.qualifiedBy, URIRef(validation["id"])))
            search_mapping_count += 1

        for validation in sorted(validations.values(), key=lambda item: item["id"]):
            node = URIRef(validation["id"])
            analysis.add((node, RDF.type, ATLAS.MachineValidation))
            analysis.add(
                (
                    node,
                    ATLAS.validationDigest,
                    RdfLiteral(validation["canonicalPayloadDigest"]),
                )
            )
            analysis.add((node, ATLAS.validates, URIRef(validation["candidate"]["id"])))
            for predicate, field in (
                (ATLAS.validatorActor, "validatorActor"),
                (ATLAS.independenceGroup, "independenceGroup"),
                (ATLAS.provider, "provider"),
                (ATLAS.requestArtifact, "requestArtifact"),
                (ATLAS.responseArtifact, "responseArtifact"),
            ):
                value = validation[field]
                analysis.add((node, predicate, URIRef(value["id"] if isinstance(value, dict) else value)))
            analysis.add(
                (
                    node,
                    ATLAS.providerModelId,
                    RdfLiteral(validation["providerModelId"]),
                )
            )
            analysis.add(
                (
                    node,
                    ATLAS.sealedInputDigest,
                    RdfLiteral(validation["sealedInputDigest"]),
                )
            )
            analysis.add((node, ATLAS.outcome, RdfLiteral(validation["outcome"])))
            analysis.add(
                (
                    node,
                    ATLAS.deterministicChecksPassed,
                    RdfLiteral(
                        validation["deterministicChecksPassed"],
                        datatype=XSD.boolean,
                    ),
                )
            )
            validation_count += 1
        for feedback in sorted(bundle["feedback"], key=lambda item: item["id"]):
            node = URIRef(feedback["id"])
            analysis.add((node, RDF.type, ATLAS.MappingFeedback))
            analysis.add(
                (
                    node,
                    ATLAS.feedbackDigest,
                    RdfLiteral(feedback["canonicalPayloadDigest"]),
                )
            )
            analysis.add((node, ATLAS.feedbackOn, URIRef(feedback["candidate"]["id"])))
            analysis.add((node, ATLAS.feedbackActor, URIRef(feedback["actor"])))
            analysis.add(
                (
                    node,
                    ATLAS.feedbackDisposition,
                    RdfLiteral(feedback["disposition"]),
                )
            )
            analysis.add((node, RDFS.comment, RdfLiteral(feedback["comment"])))
            analysis.add((node, PROV.generatedAtTime, RdfLiteral(feedback["recordedAt"])))
            feedback_count += 1

    payload = _canonical_nquads(dataset)
    counts = {
        "managedReleases": len(releases),
        "releaseFacts": len(release_graph),
        "analysisFacts": len(analysis),
        "labelClusters": cluster_count,
        "mappingCandidates": candidate_count,
        "searchOnlyMappings": search_mapping_count,
        "machineValidations": validation_count,
        "feedback": feedback_count,
    }
    return payload, counts, release_graph_id, analysis_graph_id


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    return binding.canonical_payload_digest(_plain(manifest))


def _as_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VocabularyAtlasError(f"{label} must be a JSON object")
    return cast(Mapping[str, Any], value)


def _as_sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise VocabularyAtlasError(f"{label} must be a JSON array")
    return cast(Sequence[Any], value)


def _require_count(value: object, label: str, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        qualifier = "positive" if positive else "nonnegative"
        raise VocabularyAtlasError(f"{label} must be a {qualifier} integer")
    return value


def _one_resource(graph: Graph, subject: URIRef, predicate: URIRef, label: str) -> URIRef:
    values = tuple(graph.objects(subject, predicate))
    if len(values) != 1 or not isinstance(values[0], URIRef):
        raise VocabularyAtlasError(f"{label} must have exactly one IRI")
    return values[0]


def _one_literal(graph: Graph, subject: URIRef, predicate: URIRef, label: str) -> RdfLiteral:
    values = tuple(graph.objects(subject, predicate))
    if len(values) != 1 or not isinstance(values[0], RdfLiteral):
        raise VocabularyAtlasError(f"{label} must have exactly one literal")
    return values[0]


def _search_only_mapping_nodes(analysis: Graph) -> tuple[URIRef, ...]:
    """Return every concept mapping in the analysis graph, in id order.

    An atlas only ever carries ``searchOnly`` mappings, so a mapping with any
    other eligibility is a defect rather than a row to skip.  This is the one
    place that decides which nodes are mappings; :mod:`refspec.atlas.queries`
    reads the same answer instead of re-deriving a laxer one.
    """

    nodes: list[URIRef] = []
    for subject in sorted(set(analysis.subjects(RDF.type, RKAF.ConceptMapping)), key=str):
        if not isinstance(subject, URIRef):
            raise VocabularyAtlasError("searchOnly mapping id must be an IRI")
        if _one_resource(analysis, subject, RKAF.usageEligibility, "mapping eligibility") != RKAF.searchOnly:
            raise VocabularyAtlasError("searchOnly mapping has contradictory eligibility")
        nodes.append(subject)
    return tuple(nodes)


def _search_only_mapping_validations(analysis: Graph, mapping: URIRef) -> tuple[URIRef, URIRef]:
    """Return the exactly two machine validations that qualify one mapping."""

    validations = tuple(sorted(set(analysis.objects(mapping, ATLAS.qualifiedBy)), key=str))
    if len(validations) != 2 or any(not isinstance(value, URIRef) for value in validations):
        raise VocabularyAtlasError("searchOnly mapping needs exactly two machine validations")
    return cast(tuple[URIRef, URIRef], validations)


def _label_cluster_nodes(analysis: Graph) -> tuple[URIRef, ...]:
    """Return every label cluster in the analysis graph, in id order.

    A cluster only means anything if it crosses releases, so the cross-release
    and membership checks belong to reading a cluster, not to one caller.
    """

    clusters: list[URIRef] = []
    for cluster in sorted(set(analysis.subjects(RDF.type, ATLAS.LabelCluster)), key=str):
        if not isinstance(cluster, URIRef):
            raise VocabularyAtlasError("label cluster id must be an IRI")
        _one_literal(analysis, cluster, ATLAS.normalizedLabel, "label cluster normalized label")
        members = tuple(analysis.objects(cluster, ATLAS.member))
        releases = tuple(analysis.objects(cluster, ATLAS.memberRelease))
        if len(members) < 2 or not releases:
            raise VocabularyAtlasError("label cluster must contain members from releases")
        if any(not isinstance(value, URIRef) for value in (*members, *releases)):
            raise VocabularyAtlasError("label cluster members and releases must be IRIs")
        if len(set(releases)) < 2:
            raise VocabularyAtlasError("label cluster must cross releases")
        if any(
            not any((member, ATLAS.memberOfRelease, release) in analysis for release in releases) for member in members
        ):
            raise VocabularyAtlasError("label cluster member is outside its declared releases")
        clusters.append(cluster)
    return tuple(clusters)


def _validate_input_pin(value: object) -> str:
    pin = _as_mapping(value, "atlas input")
    role = pin.get("role")
    if role == "ManagedReleaseView":
        if set(pin) != {
            "role",
            "manifestDigest",
            "publicationReleaseId",
            "rulespecGraph",
        }:
            raise VocabularyAtlasError("managed release input fields differ from v1")
        _require_digest(pin.get("manifestDigest"), "managed release manifest digest")
        _require_iri(pin.get("publicationReleaseId"), "managed publication release id")
        graph = _as_mapping(pin.get("rulespecGraph"), "managed Rulespec graph pin")
        if set(graph) != {"id", "digest"}:
            raise VocabularyAtlasError("managed Rulespec graph pin fields differ from v1")
        _require_iri(graph.get("id"), "managed Rulespec graph id")
        _require_digest(graph.get("digest"), "managed Rulespec graph digest")
        return role
    if role == "RulespecCoreRelease":
        if set(pin) != {"role", "fileDigest", "releaseId", "releaseDigest"}:
            raise VocabularyAtlasError("Rulespec Core input fields differ from v1")
        _require_digest(pin.get("fileDigest"), "Rulespec Core file digest")
        release_id = _require_iri(pin.get("releaseId"), "Rulespec Core release id")
        release_digest = _require_digest(pin.get("releaseDigest"), "Rulespec Core release digest")
        if release_id != "urn:rulespec:core:" + release_digest.removeprefix("sha256:"):
            raise VocabularyAtlasError("Rulespec Core release id differs from its digest")
        return role
    if role == "CrosswalkBundle":
        if set(pin) != {"role", "id", "digest", "fileDigest", "mediaType"}:
            raise VocabularyAtlasError("crosswalk input fields differ from v1")
        _require_iri(pin.get("id"), "crosswalk bundle id")
        _require_digest(pin.get("digest"), "crosswalk bundle digest")
        _require_digest(pin.get("fileDigest"), "crosswalk file digest")
        if pin.get("mediaType") != CROSSWALK_MEDIA_TYPE:
            raise VocabularyAtlasError("crosswalk media type differs")
        return role
    raise VocabularyAtlasError("atlas input role is unsupported")


def _validate_implementation_pin(value: object) -> Mapping[str, Any]:
    implementation = _as_mapping(value, "atlas implementation")
    if set(implementation) != {"id", "version", "sourceModules", "runtime"}:
        raise VocabularyAtlasError("atlas implementation fields differ from v1")
    _require_iri(implementation.get("id"), "atlas implementation id")
    _require_text(implementation.get("version"), "atlas implementation version")
    modules = _as_sequence(implementation.get("sourceModules"), "atlas implementation source modules")
    if not modules:
        raise VocabularyAtlasError("atlas implementation needs at least one source module")
    seen_paths: set[str] = set()
    for item in modules:
        module = _as_mapping(item, "atlas implementation source module")
        if set(module) != {"path", "digest"}:
            raise VocabularyAtlasError("atlas implementation source module fields differ from v1")
        path = _require_text(module.get("path"), "atlas implementation source module path")
        if path in seen_paths:
            raise VocabularyAtlasError("atlas implementation repeats a source module")
        seen_paths.add(path)
        _require_digest(module.get("digest"), f"atlas implementation module {path} digest")
    runtime = _as_mapping(implementation.get("runtime"), "atlas implementation runtime")
    if not runtime:
        raise VocabularyAtlasError("atlas implementation runtime must not be empty")
    for field, runtime_value in runtime.items():
        _require_text(field, "atlas implementation runtime name")
        _require_text(runtime_value, f"atlas implementation runtime {field}")
    return implementation


def _validate_projected_artifact(graph: Graph, artifact: URIRef, *, role: str) -> None:
    if (artifact, RDF.type, ATLAS.CrosswalkArtifact) not in graph:
        raise VocabularyAtlasError("searchOnly mapping references a missing crosswalk artifact")
    observed_role = _one_literal(graph, artifact, ATLAS.artifactRole, "crosswalk artifact role")
    if str(observed_role) != role:
        raise VocabularyAtlasError("searchOnly mapping references a crosswalk artifact with the wrong role")
    _require_digest(
        str(_one_literal(graph, artifact, ATLAS.artifactDigest, "crosswalk artifact digest")),
        "crosswalk artifact digest",
    )


def _reference_release_digest(graph: Graph, release: URIRef) -> str:
    if (release, RDF.type, RKAF.ReferenceResourceRelease) not in graph:
        raise VocabularyAtlasError("searchOnly mapping release is not a ReferenceResourceRelease")
    return _require_digest(
        str(_one_literal(graph, release, RKAF.referenceReleaseDigest, "reference release digest")),
        "reference release digest",
    )


def _validate_query_graph_semantics(
    dataset: Dataset,
    *,
    release_graph_id: str,
    analysis_graph_id: str,
) -> None:
    """Validate the graph facts exposed by :mod:`refspec.atlas.queries`.

    This is intentionally a distribution check.  Producer-only reconstruction
    additionally reopens the crosswalk bundle and recomputes every projected
    fact from its exact inputs.
    """

    release_graph = dataset.graph(URIRef(release_graph_id))
    analysis = dataset.graph(URIRef(analysis_graph_id))

    for member, release in analysis.subject_objects(ATLAS.memberOfRelease):
        if not isinstance(member, URIRef) or not isinstance(release, URIRef):
            raise VocabularyAtlasError("atlas membership must connect two IRIs")
        _reference_release_digest(release_graph, release)
        if (release, PROV.hadMember, member) not in release_graph:
            raise VocabularyAtlasError("atlas analysis membership is absent from authoritative release facts")

    _label_cluster_nodes(analysis)

    for mapping in _search_only_mapping_nodes(analysis):
        validations = _search_only_mapping_validations(analysis, mapping)
        source = _one_resource(analysis, mapping, RKAF.assertsSubject, "mapping source")
        relation = _one_resource(analysis, mapping, RKAF.assertsPredicate, "mapping relation")
        target = _one_resource(analysis, mapping, RKAF.assertsObject, "mapping target")
        source_release = _one_resource(
            analysis,
            mapping,
            RKAF.sourceConceptRelease,
            "mapping source release",
        )
        target_release = _one_resource(
            analysis,
            mapping,
            RKAF.targetConceptRelease,
            "mapping target release",
        )
        if str(relation) not in _MAPPING_RELATIONS:
            raise VocabularyAtlasError("searchOnly mapping relation is unsupported")
        if _one_resource(analysis, mapping, RKAF.assertionOrigin, "mapping origin") != RKAF.aiSuggested:
            raise VocabularyAtlasError("searchOnly mapping origin differs")
        if (
            _one_resource(analysis, mapping, RKAF.epistemicBasis, "mapping epistemic basis")
            != RKAF.statisticalInference
        ):
            raise VocabularyAtlasError("searchOnly mapping epistemic basis differs")
        if (
            str(_one_literal(analysis, mapping, ATLAS.selectionPolicy, "mapping selection policy"))
            != _POLICIES["mappingEligibility"]
        ):
            raise VocabularyAtlasError("searchOnly mapping selection policy differs")
        if (
            _one_resource(analysis, mapping, ATLAS.verificationStatus, "mapping verification status")
            != ATLAS.machineQualifiedForSearch
        ):
            raise VocabularyAtlasError("searchOnly mapping verification status differs")

        candidate = _one_resource(analysis, mapping, ATLAS.qualifiedFrom, "mapping candidate")
        if (candidate, RDF.type, ATLAS.MappingCandidate) not in analysis:
            raise VocabularyAtlasError("searchOnly mapping candidate is missing")
        if _one_resource(analysis, candidate, RKAF.usageEligibility, "candidate eligibility") != RKAF.searchOnly:
            raise VocabularyAtlasError("searchOnly mapping candidate is not searchOnly")
        expected_candidate_values = (
            (ATLAS.sourceMember, source),
            (ATLAS.proposedRelation, relation),
            (ATLAS.targetMember, target),
            (ATLAS.sourceRelease, source_release),
            (ATLAS.targetRelease, target_release),
        )
        if any(
            _one_resource(analysis, candidate, predicate, "mapping candidate endpoint") != expected
            for predicate, expected in expected_candidate_values
        ):
            raise VocabularyAtlasError("searchOnly mapping differs from its candidate")
        _require_digest(
            str(_one_literal(analysis, candidate, ATLAS.candidateDigest, "mapping candidate digest")),
            "mapping candidate digest",
        )
        input_digest = _require_digest(
            str(_one_literal(analysis, candidate, ATLAS.inputContextDigest, "mapping input digest")),
            "mapping input digest",
        )
        input_context = _one_resource(
            analysis,
            candidate,
            ATLAS.inputContextArtifact,
            "mapping input context artifact",
        )
        _validate_projected_artifact(analysis, input_context, role="inputContext")
        if (
            str(
                _one_literal(
                    analysis,
                    input_context,
                    ATLAS.contentDigest,
                    "input context content digest",
                )
            )
            != input_digest
        ):
            raise VocabularyAtlasError(
                "searchOnly mapping input context does not carry the sealed input digest"
            )
        evidence = tuple(analysis.objects(candidate, ATLAS.evidence))
        if not evidence or any(not isinstance(item, URIRef) for item in evidence):
            raise VocabularyAtlasError("searchOnly mapping candidate needs IRI evidence")
        for artifact in cast(tuple[URIRef, ...], evidence):
            _validate_projected_artifact(analysis, artifact, role="evidence")

        independence: list[tuple[URIRef, URIRef, URIRef, str, URIRef]] = []
        for validation in validations:
            if (validation, RDF.type, ATLAS.MachineValidation) not in analysis:
                raise VocabularyAtlasError("searchOnly mapping validation is missing")
            if _one_resource(analysis, validation, ATLAS.validates, "machine validation candidate") != candidate:
                raise VocabularyAtlasError("machine validation applies to another candidate")
            _require_digest(
                str(_one_literal(analysis, validation, ATLAS.validationDigest, "machine validation digest")),
                "machine validation digest",
            )
            if (
                str(_one_literal(analysis, validation, ATLAS.sealedInputDigest, "machine sealed input digest"))
                != input_digest
            ):
                raise VocabularyAtlasError("machine validation uses another sealed input")
            outcome = _one_literal(analysis, validation, ATLAS.outcome, "machine validation outcome")
            deterministic = _one_literal(
                analysis,
                validation,
                ATLAS.deterministicChecksPassed,
                "machine deterministic check",
            )
            if (
                str(outcome) != "supports"
                or deterministic.datatype != XSD.boolean
                or deterministic.toPython() is not True
            ):
                raise VocabularyAtlasError("machine validation does not support deterministic search use")
            actor = _one_resource(analysis, validation, ATLAS.validatorActor, "machine validator actor")
            group = _one_resource(analysis, validation, ATLAS.independenceGroup, "machine independence group")
            provider = _one_resource(analysis, validation, ATLAS.provider, "machine provider")
            provider_model_id = _require_text(
                str(
                    _one_literal(
                        analysis,
                        validation,
                        ATLAS.providerModelId,
                        "machine provider model id",
                    )
                ),
                "machine provider model id",
            )
            request = _one_resource(analysis, validation, ATLAS.requestArtifact, "machine request artifact")
            response = _one_resource(analysis, validation, ATLAS.responseArtifact, "machine response artifact")
            _validate_projected_artifact(analysis, request, role="validationRequest")
            _validate_projected_artifact(analysis, response, role="validationResponse")
            independence.append((actor, group, provider, provider_model_id, response))
        first, second = independence
        if any(left == right for left, right in zip(first, second, strict=True)):
            raise VocabularyAtlasError("searchOnly mapping validations are not independent")
        expected_mapping = _stable_iri(
            "search-only-mapping",
            str(candidate),
            *(str(value) for value in validations),
        )
        if mapping != expected_mapping:
            raise VocabularyAtlasError("searchOnly mapping id differs from its proof")
        if (source, ATLAS.memberOfRelease, source_release) not in analysis or (
            target,
            ATLAS.memberOfRelease,
            target_release,
        ) not in analysis:
            raise VocabularyAtlasError("searchOnly mapping endpoints are outside their releases")
        _reference_release_digest(release_graph, source_release)
        _reference_release_digest(release_graph, target_release)
        if (source_release, PROV.hadMember, source) not in release_graph or (
            target_release,
            PROV.hadMember,
            target,
        ) not in release_graph:
            raise VocabularyAtlasError("searchOnly mapping endpoint is absent from its release facts")


_ASSET_CONSTRUCTION_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class VocabularyAtlasAsset:
    """Canonical atlas bytes and the manifest that verifies them."""

    payload: bytes
    manifest: Mapping[str, Any]
    _verification_token: object

    def __init__(
        self,
        payload: bytes,
        manifest: Mapping[str, Any],
        *,
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _ASSET_CONSTRUCTION_TOKEN:
            raise TypeError(
                "VocabularyAtlasAsset must come from build_vocabulary_atlas() or VocabularyAtlasAsset.open()"
            )
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(self, "_verification_token", _ASSET_CONSTRUCTION_TOKEN)

    @classmethod
    def _verified(cls, *, payload: bytes, manifest: Mapping[str, Any]) -> Self:
        return cls(
            payload,
            manifest,
            _construction_token=_ASSET_CONSTRUCTION_TOKEN,
        )

    def _require_verified(self) -> None:
        """Marker check used by query helpers before parsing public bytes."""

        if (
            getattr(self, "_verification_token", None) is not _ASSET_CONSTRUCTION_TOKEN
            or not isinstance(self.payload, bytes)
            or not isinstance(self.manifest, Mapping)
        ):
            raise VocabularyAtlasError("atlas asset is not a verified distribution")

    def manifest_bytes(self) -> bytes:
        return _canonical_bytes(_plain(self.manifest))

    @property
    def manifest_digest(self) -> str:
        return _digest_bytes(self.manifest_bytes())

    @property
    def output_digest(self) -> str:
        return _digest_bytes(self.payload)

    def rulespec_core_pin(self) -> dict[str, str]:
        """Return the one Core identity selected by this verified distribution."""

        self._require_verified()
        values = [value for value in self.manifest["inputs"] if value.get("role") == "RulespecCoreRelease"]
        if len(values) != 1:
            raise VocabularyAtlasError("atlas must contain exactly one Rulespec Core input")
        return {
            "release_id": str(values[0]["releaseId"]),
            "release_digest": str(values[0]["releaseDigest"]),
        }

    def write(self, directory: Path | str) -> Path:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=False)
        (target / ATLAS_FILE).write_bytes(self.payload)
        (target / MANIFEST_FILE).write_bytes(self.manifest_bytes())
        return target

    @classmethod
    def open(
        cls,
        directory: Path | str,
        *,
        expected_manifest_digest: str,
        expected_output_digest: str,
    ) -> Self:
        """Verify a static distribution using only its two external digests."""

        root = Path(directory)
        if root.is_symlink():
            raise VocabularyAtlasError("atlas directory must not be a symlink")
        try:
            root = root.resolve(strict=True)
        except FileNotFoundError as error:
            raise VocabularyAtlasError("atlas directory does not exist") from error
        if not root.is_dir():
            raise VocabularyAtlasError("atlas path must be a directory")
        manifest_path, manifest_bytes = _read_exact_file(root / MANIFEST_FILE, "atlas manifest")
        del manifest_path
        expected_manifest_digest = _require_digest(expected_manifest_digest, "expected atlas manifest digest")
        if _digest_bytes(manifest_bytes) != expected_manifest_digest:
            raise VocabularyAtlasError("atlas external manifest digest differs")
        manifest = _load_json_object(manifest_bytes, "atlas manifest")
        if _canonical_bytes(manifest) != manifest_bytes:
            raise VocabularyAtlasError("atlas manifest bytes are not canonical")
        required = {
            "id",
            "type",
            "schemaVersion",
            "format",
            "generationDigest",
            "inputs",
            "implementation",
            "policies",
            "graphs",
            "output",
            "counts",
            "canonicalPayloadDigest",
        }
        if set(manifest) != required:
            raise VocabularyAtlasError("atlas manifest fields differ from v1")
        if manifest["type"] != "urn:ref:type:VocabularyAtlasManifest":
            raise VocabularyAtlasError("atlas manifest type differs")
        if manifest["schemaVersion"] != SCHEMA_VERSION:
            raise VocabularyAtlasError("atlas manifest schemaVersion differs")
        if manifest["format"] != FORMAT_ID:
            raise VocabularyAtlasError("atlas format differs")
        _require_iri(manifest["id"], "atlas id")
        _require_digest(manifest["generationDigest"], "atlas generation digest")
        _require_digest(manifest["canonicalPayloadDigest"], "atlas canonical payload digest")
        if manifest["canonicalPayloadDigest"] != _manifest_digest(manifest):
            raise VocabularyAtlasError("atlas manifest digest differs")
        implementation = _validate_implementation_pin(manifest["implementation"])
        actual_inputs = list(_as_sequence(manifest["inputs"], "atlas inputs"))
        roles = [_validate_input_pin(item) for item in actual_inputs]
        managed_inputs = [
            cast(Mapping[str, Any], item)
            for item, role in zip(actual_inputs, roles, strict=True)
            if role == "ManagedReleaseView"
        ]
        if not managed_inputs or roles.count("RulespecCoreRelease") != 1 or roles.count("CrosswalkBundle") > 1:
            raise VocabularyAtlasError(
                "atlas inputs require managed releases, one Rulespec Core, and at most one crosswalk"
            )
        if len(managed_inputs) + roles.count("RulespecCoreRelease") + roles.count("CrosswalkBundle") != len(
            actual_inputs
        ):
            raise VocabularyAtlasError("atlas input roles differ from v1")
        managed_identities = {(item["publicationReleaseId"], item["manifestDigest"]) for item in managed_inputs}
        if len(managed_identities) != len(managed_inputs):
            raise VocabularyAtlasError("atlas repeats a managed release input")
        generation_input = {
            "format": FORMAT_ID,
            "inputs": actual_inputs,
            "implementation": _plain(implementation),
            "policies": _plain(manifest["policies"]),
        }
        generation_digest = _digest_value(generation_input)
        if manifest["generationDigest"] != generation_digest:
            raise VocabularyAtlasError("atlas generation digest differs")
        asset_id = "urn:ref:vocabulary-atlas:" + generation_digest.removeprefix("sha256:")
        if manifest["id"] != asset_id:
            raise VocabularyAtlasError("atlas id differs from generation digest")
        policies = _as_mapping(manifest["policies"], "atlas policies")
        if dict(policies) != dict(_POLICIES):
            raise VocabularyAtlasError("atlas policies differ")
        expected_graphs = {
            "releaseFacts": asset_id + ":release-facts",
            "analysis": asset_id + ":analysis",
        }
        graph_rows = _as_sequence(manifest["graphs"], "atlas graphs")
        if len(graph_rows) != 2:
            raise VocabularyAtlasError("atlas must declare exactly two named graphs")
        graph_by_role: dict[str, Mapping[str, Any]] = {}
        for value in graph_rows:
            row = _as_mapping(value, "atlas graph")
            if set(row) != {"role", "id", "quadCount"}:
                raise VocabularyAtlasError("atlas graph fields differ from v1")
            role = row.get("role")
            if role not in expected_graphs or role in graph_by_role:
                raise VocabularyAtlasError("atlas graph roles differ")
            _require_iri(row.get("id"), f"atlas {role} graph id")
            _require_count(row.get("quadCount"), f"atlas {role} graph count", positive=True)
            graph_by_role[cast(str, role)] = row
        if set(graph_by_role) != set(expected_graphs):
            raise VocabularyAtlasError("atlas graph roles differ")
        for role, graph_id in expected_graphs.items():
            if graph_by_role[role].get("id") != graph_id:
                raise VocabularyAtlasError("atlas graph id differs")

        _, payload = _read_exact_file(root / ATLAS_FILE, "atlas N-Quads")
        expected_output_digest = _require_digest(expected_output_digest, "expected atlas output digest")
        if _digest_bytes(payload) != expected_output_digest:
            raise VocabularyAtlasError("atlas external output digest differs")
        output = _as_mapping(manifest["output"], "atlas output")
        if set(output) != {"path", "mediaType", "digest", "byteLength", "quadCount"}:
            raise VocabularyAtlasError("atlas output fields differ from v1")
        if output.get("path") != ATLAS_FILE or output.get("mediaType") != ("application/n-quads"):
            raise VocabularyAtlasError("atlas output declaration differs")
        _require_digest(output.get("digest"), "atlas output digest")
        _require_count(output.get("byteLength"), "atlas output byte length", positive=True)
        _require_count(output.get("quadCount"), "atlas output quad count", positive=True)
        if output.get("byteLength") != len(payload):
            raise VocabularyAtlasError("atlas output byte length differs")
        if output.get("digest") != _digest_bytes(payload):
            raise VocabularyAtlasError("atlas output digest differs")
        dataset = Dataset(default_union=False)
        try:
            dataset.parse(data=payload.decode("utf-8"), format="nquads")
        except Exception as error:  # rdflib exposes parser-specific subclasses
            raise VocabularyAtlasError("atlas output is not valid N-Quads") from error
        if any(isinstance(term, BNode) for context in dataset.graphs() for triple in context for term in triple):
            raise VocabularyAtlasError("atlas output contains a blank node")
        if _canonical_nquads(dataset) != payload:
            raise VocabularyAtlasError("atlas N-Quads bytes are not canonical")
        named_ids = {str(context.identifier) for context in dataset.graphs() if len(context) > 0}
        if named_ids != set(expected_graphs.values()):
            raise VocabularyAtlasError("atlas N-Quads named graphs differ")
        graph_counts = {role: len(dataset.graph(URIRef(graph_id))) for role, graph_id in expected_graphs.items()}
        if any(graph_by_role[role].get("quadCount") != count for role, count in graph_counts.items()):
            raise VocabularyAtlasError("atlas graph counts differ")
        total = sum(graph_counts.values())
        if output.get("quadCount") != total:
            raise VocabularyAtlasError("atlas output quad count differs")
        counts = _as_mapping(manifest["counts"], "atlas counts")
        expected_count_fields = {
            "managedReleases",
            "releaseFacts",
            "analysisFacts",
            "labelClusters",
            "mappingCandidates",
            "searchOnlyMappings",
            "machineValidations",
            "feedback",
        }
        if set(counts) != expected_count_fields:
            raise VocabularyAtlasError("atlas count fields differ from v1")
        for field, value in counts.items():
            _require_count(value, f"atlas count {field}")
        observed_counts = {
            "managedReleases": len(managed_inputs),
            "releaseFacts": graph_counts["releaseFacts"],
            "analysisFacts": graph_counts["analysis"],
            "labelClusters": len(
                set(dataset.graph(URIRef(expected_graphs["analysis"])).subjects(RDF.type, ATLAS.LabelCluster))
            ),
            "mappingCandidates": len(
                set(dataset.graph(URIRef(expected_graphs["analysis"])).subjects(RDF.type, ATLAS.MappingCandidate))
            ),
            "searchOnlyMappings": len(
                {
                    subject
                    for subject in dataset.graph(URIRef(expected_graphs["analysis"])).subjects(
                        RDF.type, RKAF.ConceptMapping
                    )
                    if (
                        subject,
                        RKAF.usageEligibility,
                        RKAF.searchOnly,
                    )
                    in dataset.graph(URIRef(expected_graphs["analysis"]))
                }
            ),
            "machineValidations": len(
                set(dataset.graph(URIRef(expected_graphs["analysis"])).subjects(RDF.type, ATLAS.MachineValidation))
            ),
            "feedback": len(
                set(dataset.graph(URIRef(expected_graphs["analysis"])).subjects(RDF.type, ATLAS.MappingFeedback))
            ),
        }
        if dict(counts) != observed_counts:
            raise VocabularyAtlasError("atlas declared counts differ")
        _validate_query_graph_semantics(
            dataset,
            release_graph_id=expected_graphs["releaseFacts"],
            analysis_graph_id=expected_graphs["analysis"],
        )
        return cls._verified(
            payload=payload,
            manifest=cast(Mapping[str, Any], _freeze(manifest)),
        )

    @classmethod
    def reproduce_from_inputs(
        cls,
        directory: Path | str,
        *,
        releases: Sequence[VerifiedManagedReleaseSource],
        rulespec_core: PinnedRulespecCoreRelease,
        expected_manifest_digest: str,
        expected_output_digest: str,
        crosswalk: CrosswalkBundle | None = None,
    ) -> Self:
        """Verify the distribution and reproduce it from exact producer inputs."""

        opened = cls.open(
            directory,
            expected_manifest_digest=expected_manifest_digest,
            expected_output_digest=expected_output_digest,
        )
        implementation = _implementation_pin()
        if _plain(opened.manifest["implementation"]) != implementation:
            raise VocabularyAtlasError("atlas implementation pin differs")
        actual_inputs = cast(list[dict[str, Any]], _plain(opened.manifest["inputs"]))
        resolved = _resolve_managed_releases(releases)
        expected_inputs = _input_pins(
            resolved,
            rulespec_core=rulespec_core,
            crosswalk=crosswalk,
        )
        if actual_inputs != expected_inputs:
            raise VocabularyAtlasError("atlas release input pins differ")
        rebuilt = _build_resolved_vocabulary_atlas(
            resolved,
            rulespec_core=rulespec_core,
            crosswalk=crosswalk,
        )
        if rebuilt.manifest != opened.manifest or rebuilt.payload != opened.payload:
            raise VocabularyAtlasError("atlas files do not reproduce from the exact pinned inputs")
        return opened


def _resolve_managed_releases(
    releases: Sequence[VerifiedManagedReleaseSource],
) -> tuple[_ResolvedManagedRelease, ...]:
    """Bind every claimed input pin to the same verified view used to build."""

    if not releases:
        raise VocabularyAtlasError("an atlas needs at least one managed release")
    resolved: list[_ResolvedManagedRelease] = []
    for source in releases:
        view = source.verified_view()
        release_id = _require_iri(view.release_id, "managed publication release id")
        graph_id = _require_iri(view.rulespec_graph_id, "managed Rulespec graph id")
        graph_digest = rulespec_graph_digest(_plain(view.rulespec_graph))
        pin = source.pin()
        if _validate_input_pin(pin) != "ManagedReleaseView":
            raise VocabularyAtlasError("managed release source returned another input role")
        expected_view_pin = {
            "publicationReleaseId": release_id,
            "rulespecGraph": {
                "id": graph_id,
                "digest": graph_digest,
            },
        }
        if (
            pin.get("publicationReleaseId") != expected_view_pin["publicationReleaseId"]
            or pin.get("rulespecGraph") != expected_view_pin["rulespecGraph"]
        ):
            raise VocabularyAtlasError("managed release pin differs from its verified view")
        resolved.append(
            _ResolvedManagedRelease(
                view=view,
                pin=cast(Mapping[str, Any], _freeze(_plain(pin))),
            )
        )
    ordered = tuple(
        sorted(
            resolved,
            key=lambda item: (
                item.pin["publicationReleaseId"],
                item.pin["manifestDigest"],
            ),
        )
    )
    identities = [(item.pin["publicationReleaseId"], item.pin["manifestDigest"]) for item in ordered]
    if len(set(identities)) != len(identities):
        raise VocabularyAtlasError("atlas repeats a managed release input")
    return ordered


def _input_pins(
    releases: Sequence[_ResolvedManagedRelease],
    *,
    rulespec_core: PinnedRulespecCoreRelease,
    crosswalk: CrosswalkBundle | None,
) -> list[dict[str, Any]]:
    release_pins = [cast(dict[str, Any], _plain(item.pin)) for item in releases]
    result: list[dict[str, Any]] = [*release_pins, rulespec_core.pin()]
    if crosswalk is not None:
        result.append(crosswalk.pin())
    return result


def _build_resolved_vocabulary_atlas(
    releases: Sequence[_ResolvedManagedRelease],
    *,
    rulespec_core: PinnedRulespecCoreRelease,
    crosswalk: CrosswalkBundle | None = None,
) -> VocabularyAtlasAsset:
    """Build deterministic release-facts and replaceable-analysis graphs."""

    inputs = _input_pins(
        releases,
        rulespec_core=rulespec_core,
        crosswalk=crosswalk,
    )
    implementation = _implementation_pin()
    generation_input = {
        "format": FORMAT_ID,
        "inputs": inputs,
        "implementation": implementation,
        "policies": dict(_POLICIES),
    }
    generation_digest = _digest_value(generation_input)
    asset_id = "urn:ref:vocabulary-atlas:" + generation_digest.removeprefix("sha256:")
    payload, counts, release_graph_id, analysis_graph_id = _build_dataset(
        releases,
        asset_id=asset_id,
        crosswalk=crosswalk,
    )
    graphs = [
        {
            "role": "releaseFacts",
            "id": release_graph_id,
            "quadCount": counts["releaseFacts"],
        },
        {
            "role": "analysis",
            "id": analysis_graph_id,
            "quadCount": counts["analysisFacts"],
        },
    ]
    manifest: dict[str, Any] = {
        "id": asset_id,
        "type": "urn:ref:type:VocabularyAtlasManifest",
        "schemaVersion": SCHEMA_VERSION,
        "format": FORMAT_ID,
        "generationDigest": generation_digest,
        "inputs": inputs,
        "implementation": implementation,
        "policies": dict(_POLICIES),
        "graphs": graphs,
        "output": {
            "path": ATLAS_FILE,
            "mediaType": "application/n-quads",
            "digest": _digest_bytes(payload),
            "byteLength": len(payload),
            "quadCount": counts["releaseFacts"] + counts["analysisFacts"],
        },
        "counts": counts,
    }
    manifest["canonicalPayloadDigest"] = _manifest_digest(manifest)
    return VocabularyAtlasAsset._verified(
        payload=payload,
        manifest=cast(Mapping[str, Any], _freeze(manifest)),
    )


def build_vocabulary_atlas(
    releases: Sequence[VerifiedManagedReleaseSource],
    *,
    rulespec_core: PinnedRulespecCoreRelease,
    crosswalk: CrosswalkBundle | None = None,
) -> VocabularyAtlasAsset:
    """Build deterministic release-facts and replaceable-analysis graphs."""

    return _build_resolved_vocabulary_atlas(
        _resolve_managed_releases(tuple(releases)),
        rulespec_core=rulespec_core,
        crosswalk=crosswalk,
    )


__all__ = [
    "ATLAS",
    "CROSSWALK_MEDIA_TYPE",
    "FORMAT_ID",
    "RKAF",
    "AtlasReleaseFactsView",
    "CrosswalkArtifact",
    "CrosswalkBundle",
    "MachineValidation",
    "MappingCandidate",
    "MappingFeedback",
    "PinnedManagedRelease",
    "PinnedRulespecCoreRelease",
    "VerifiedManagedReleaseSource",
    "VocabularyAtlasAsset",
    "VocabularyAtlasError",
    "build_vocabulary_atlas",
]
