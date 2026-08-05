"""Deterministic, lossless vocabulary-atlas distributions.

The canonical Atlas 2.0 publisher accepts one exact
``PinnedVocabularyAtlasScope``.  It preserves source and RefSpec concept
identity, release-scoped records, typed evidence, and ring-specific mapping
assertions as canonical JSON records.  RDF supplies only the exact record
index and containment needed to read those records; labels never mint identity
or relations.
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
from rdflib.namespace import DCAT, DCTERMS, PROV, RDF, XSD
from typing_extensions import Self

from refspec import binding
from refspec.managed_release import (
    ManagedReleaseExpression,
    ManagedReleaseMember,
    ManagedReleaseRelation,
    ManagedReleaseView,
)
from refspec.release_graph import rulespec_graph_digest
from refspec.storage import canonical_json

FORMAT_ID = "refspec-vocabulary-atlas-nquads-2.0"
_MANAGED_SNAPSHOT_REFERENCE_TYPE = "ManagedAtlasReleaseSnapshotReference"
_MANAGED_SNAPSHOT_REFERENCE_VERSION = "1.0"
SCHEMA_VERSION = "2.0"
ATLAS_FILE = "atlas.nq"
MANIFEST_FILE = "atlas-manifest.json"
SCOPE_FILE = "atlas-scope.json"
CROSSWALK_MEDIA_TYPE = "application/vnd.refspec.vocabulary-atlas-crosswalk+json"

ATLAS = Namespace("https://refspec.org/ns/vocabulary-atlas/v2#")
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

#: Protocol v2 verdict strings a sealed validation may carry, with the outcome
#: each one derives.  Mirrors ``qualification.VERDICTS_V2`` without importing
#: it: the format is the authority on what a sealed record admits.
_V2_VERDICT_OUTCOMES: Mapping[str, str] = MappingProxyType(
    {
        "same": "supports",
        "near_same": "supports",
        "target_is_broader": "supports",
        "target_is_narrower": "supports",
        "related": "supports",
        "unrelated": "rejects",
        "insufficient_evidence": "abstains",
    }
)
_V2_VERDICTS = frozenset(_V2_VERDICT_OUTCOMES)
_CROSSWALK_SCHEMA_V2 = "2.0"
#: Adjudicated-``related`` is a relation like any other — it is recorded on the
#: candidate as ``skos:relatedMatch`` — but it is the one agreed relation that
#: emits no ``ConceptMapping``.  Promoting associative links to consumable
#: mappings is a separate decision for a consumer that actually wants them.
_RELATED_MATCH = "http://www.w3.org/2004/02/skos/core#relatedMatch"


def _agreed_relation_for(verdicts: frozenset[str]) -> str | None:
    """The v2 agreement lattice, folded over *every* supporting verdict.

    The rule is universal, not existential: every supporting validation on one
    question must be relation-compatible with every other, and the mapping is
    emitted at the weakest claim any of them made.  ``same``+``near_same`` agree
    that substitution is symmetric and disagree only about identity, so that set
    qualifies at ``closeMatch``.  Every other mixture is a real disagreement
    about the claim itself — emitting either relation would overrule a machine
    on the precise thing that relation asserts — and yields nothing.
    """

    if not verdicts:
        return None
    if verdicts == {"same"}:
        return "http://www.w3.org/2004/02/skos/core#exactMatch"
    if verdicts <= {"same", "near_same"}:
        return "http://www.w3.org/2004/02/skos/core#closeMatch"
    if verdicts == {"target_is_broader"}:
        return "http://www.w3.org/2004/02/skos/core#broadMatch"
    if verdicts == {"target_is_narrower"}:
        return "http://www.w3.org/2004/02/skos/core#narrowMatch"
    if verdicts == {"related"}:
        return _RELATED_MATCH
    return None


_ARTIFACT_ROLES = frozenset({"evidence", "inputContext", "validationRequest", "validationResponse"})
_POLICIES = MappingProxyType(
    {
        "graphPartition": "releaseFactsAndCrossReleaseRecords",
        "recordEncoding": "canonicalRefJsonV1",
        "recordIndexing": "derivedExactEqualityV1",
        "labelEquality": "discoveryOnly",
        "permission": "externalProductPolicyOnly",
    }
)
# This is the import-closed Atlas 2.0 build path: scope resolution, exact
# release snapshots, relation records, and the codecs that determine output
# bytes. It deliberately excludes source-specific producers, queries,
# projections, product policy, publication UI, and package facades.
_IMPLEMENTATION_SOURCE_PATHS = (
    "atlas/atlas_scope.py",
    "atlas/concept_release.py",
    "atlas/model.py",
    "atlas/relation_assertion.py",
    "atlas/relation_proof.py",
    "atlas/release_snapshot.py",
    "atlas_index.py",
    "binding.py",
    "generated_rulespec_dependency.py",
    "immutable.py",
    "managed_release.py",
    "registry/infrastructure/artifact_serialization.py",
    "registry/infrastructure/identifier_validation.py",
    "registry/infrastructure/semantic_foundation.py",
    "registry/infrastructure/source_concept_release.py",
    "registry/infrastructure/source_controlled_resource.py",
    "registry/infrastructure/source_identity.py",
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

    def iter_relations(self) -> Iterable[ManagedReleaseRelation]: ...


class VerifiedManagedReleaseSource(Protocol):
    """Producer-neutral source of exact release facts and its publication pin."""

    def verified_view(self) -> AtlasReleaseFactsView: ...

    def pin(self) -> dict[str, Any]: ...


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


#: ``dcat:version`` is absent from rdflib's closed DCAT namespace, so it is
#: spelled out rather than fetched as an attribute that warns.
_DCAT_VERSION = URIRef("http://www.w3.org/ns/dcat#version")
_CLOSED_RELEASE_PREDICATES = frozenset(
    {
        RDF.type,
        DCTERMS.isVersionOf,
        _DCAT_VERSION,
        DCTERMS.type,
        RKAF.membershipMode,
        PROV.hadMember,
        DCAT.distribution,
        RKAF.versionBasis,
        DCTERMS.issued,
        RKAF.hasEffectivePeriod,
    }
)
_CLOSED_DISTRIBUTION_PREDICATES = frozenset(
    {
        RKAF.hasArtifactIdentifier,
        DCTERMS.format,
        RKAF.hasContentDigest,
    }
)


def _rdfc_term(term: Any) -> Any:
    """Use the RDFC-1.0 spelling for an explicit ``xsd:string`` literal."""

    if isinstance(term, RdfLiteral) and term.datatype == XSD.string:
        return RdfLiteral(str(term))
    return term


def closed_reference_release_digest(
    graph_value: Mapping[str, Any],
    *,
    release_iri: str,
    label: str,
) -> str:
    """Compute the Rulespec Core closed-manifest digest without a source checkout.

    The closed ``ReferenceResourceRelease`` preimage contains named nodes only.
    With no blank nodes to relabel, RDFC-1.0 is the lexicographically sorted
    canonical N-Quads serialization.  RefSpec owns this small implementation,
    pins its source and rdflib runtime in the atlas manifest, and fails closed
    if a future Core shape introduces a blank node.

    Every specialized producer that packages a vocabulary Rulespec never sealed
    calls exactly this function, so two adapters cannot drift into two
    different answers for the same closed shape.
    """

    release = URIRef(_require_iri(release_iri, f"{label} reference release IRI"))
    parsed = Graph()
    try:
        parsed.parse(data=canonical_json(_plain(graph_value)), format="json-ld")
    except Exception as error:  # rdflib exposes parser-specific exception types
        raise VocabularyAtlasError(f"{label} release graph is not valid JSON-LD") from error
    if (release, RDF.type, RKAF.ReferenceResourceRelease) not in parsed:
        raise VocabularyAtlasError(f"{label} release is not a ReferenceResourceRelease")

    triples: list[tuple[URIRef, URIRef, Any]] = []
    for predicate in _CLOSED_RELEASE_PREDICATES:
        triples.extend((release, predicate, _rdfc_term(value)) for value in parsed.objects(release, predicate))
    distributions = tuple(parsed.objects(release, DCAT.distribution))
    if not distributions:
        raise VocabularyAtlasError(f"{label} release has no distribution")
    for distribution in distributions:
        if not isinstance(distribution, URIRef):
            raise VocabularyAtlasError(f"{label} release distribution must be an IRI")
        for predicate in _CLOSED_DISTRIBUTION_PREDICATES:
            values = tuple(parsed.objects(distribution, predicate))
            if not values:
                raise VocabularyAtlasError(f"{label} distribution lacks digest input {predicate}")
            triples.extend((distribution, predicate, _rdfc_term(value)) for value in values)

    if any(isinstance(term, BNode) for triple in triples for term in triple):
        raise VocabularyAtlasError(f"{label} release digest preimage must not contain blank nodes")
    lines = sorted(f"{subject.n3()} {predicate.n3()} {object_.n3()} ." for subject, predicate, object_ in triples)
    preimage = ("\n".join(lines) + "\n").encode("utf-8")
    return "sha256:" + hashlib.sha256(preimage).hexdigest()


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
        verdict_relation: str,
    ) -> Self:
        if validator_kind not in {"aiModel", "aiAgent"}:
            raise VocabularyAtlasError("validator kind is unsupported")
        if outcome not in {"supports", "rejects", "abstains"}:
            raise VocabularyAtlasError("machine validation outcome is unsupported")
        if not isinstance(deterministic_checks_passed, bool):
            raise VocabularyAtlasError("deterministicChecksPassed must be boolean")
        if verdict_relation not in _V2_VERDICTS:
            raise VocabularyAtlasError("machine validation verdictRelation is unsupported")
        if _V2_VERDICT_OUTCOMES[verdict_relation] != outcome:
            raise VocabularyAtlasError("machine validation outcome disagrees with its verdictRelation")
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
            "verdictRelation": verdict_relation,
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
class CrosswalkBundle:
    """Closed protocol-v2 crosswalk input with machine validation."""

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
    ) -> Self:
        artifact_records = _unique_records(artifacts, "crosswalk artifact")
        candidate_records = _unique_records(mapping_candidates, "mapping candidate")
        validation_records = _unique_records(machine_validations, "machine validation")
        _validate_crosswalk_closure(
            artifacts=artifact_records,
            candidates=candidate_records,
            validations=validation_records,
        )
        record = _seal_record(
            record_type="urn:ref:type:VocabularyAtlasCrosswalkBundle",
            id_prefix="urn:ref:vocabulary-atlas-crosswalk-bundle:",
            payload={
                "schemaVersion": _CROSSWALK_SCHEMA_V2,
                "artifacts": [artifact_records[key] for key in sorted(artifact_records)],
                "mappingCandidates": [candidate_records[key] for key in sorted(candidate_records)],
                "machineValidations": [validation_records[key] for key in sorted(validation_records)],
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
            "canonicalPayloadDigest",
        }
        if set(record) != expected_fields:
            raise VocabularyAtlasError("crosswalk bundle fields differ from v2")
        _verify_sealed_record(
            record,
            record_type="urn:ref:type:VocabularyAtlasCrosswalkBundle",
            id_prefix="urn:ref:vocabulary-atlas-crosswalk-bundle:",
        )
        if record["schemaVersion"] != _CROSSWALK_SCHEMA_V2:
            raise VocabularyAtlasError("crosswalk bundle schemaVersion differs")
        artifacts = _index_serialized_records(record["artifacts"], "crosswalk artifact")
        candidates = _index_serialized_records(record["mappingCandidates"], "mapping candidate")
        validations = _index_serialized_records(record["machineValidations"], "machine validation")
        _validate_crosswalk_closure(
            artifacts=artifacts,
            candidates=candidates,
            validations=validations,
        )

    def qualified(self) -> dict[str, tuple[dict[str, Any], ...]]:
        """Return every supporting validation in each qualifying question.

        The returned validation set is the complete same-question set whose
        unanimous relation determined qualification, not only the first pair
        that demonstrated machine independence.
        """

        self.verify()
        record = self.to_dict()
        candidates = {item["id"]: item for item in record["mappingCandidates"]}
        validations = {item["id"]: item for item in record["machineValidations"]}
        return _qualified_candidates(candidates, validations)

    def adjudicated_relations(self) -> dict[str, str]:
        """Every candidate's agreed relation IRI, adjudicated-``related`` included.

        Read through the same lattice the atlas builder uses, so a report that
        counts relations can never drift from the gate that emitted them.
        """

        self.verify()
        record = self.to_dict()
        candidates = {item["id"]: item for item in record["mappingCandidates"]}
        validations = {item["id"]: item for item in record["machineValidations"]}
        return {
            candidate_id: relation
            for candidate_id, (_, relation) in _independent_agreements(candidates, validations).items()
        }


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
        raise VocabularyAtlasError("candidate input context does not close against the bundle")
    if len(matches) > 1:
        raise VocabularyAtlasError("candidate input context resolves to several artifacts")
    return artifacts[matches[0]]


def _validate_crosswalk_closure(
    *,
    artifacts: Mapping[str, Mapping[str, Any]],
    candidates: Mapping[str, Mapping[str, Any]],
    validations: Mapping[str, Mapping[str, Any]],
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
            or response_content.get("verdict") != record["verdictRelation"]
            or response_content.get("deterministicChecksPassed") is not record["deterministicChecksPassed"]
        ):
            raise VocabularyAtlasError("machine response does not seal its validator result")


def _agreement_relation_tag(values: Sequence[Mapping[str, Any]]) -> str | None:
    """The v2 relation every supporting validation on one question agrees on."""

    return _agreed_relation_for(frozenset(str(value["verdictRelation"]) for value in values))


def _independent_agreements(
    candidates: Mapping[str, Mapping[str, Any]],
    validations: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[tuple[dict[str, Any], ...], str]]:
    """Every candidate whose supporting validations agree on one relation.

    Two gates, in order.  The relation gate is universal — *every* supporting
    validation asked the same question must be compatible with every other, so a
    third machine can never outvote a direction disagreement.  The independence
    gate then requires two of them to be genuinely different machines.
    """

    by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in validations.values():
        if record["outcome"] == "supports" and record["deterministicChecksPassed"] is True:
            by_candidate[record["candidate"]["id"]].append(dict(record))
    agreements: dict[str, tuple[tuple[dict[str, Any], ...], str]] = {}
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
            relation = _agreement_relation_tag(values)
            if relation is None:
                # These machines did not answer one question with one relation.
                # A different sealed question may still have agreement.
                continue
            independent_witness = next(
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
            if independent_witness is not None:
                # Every value above affected the unanimous relation gate.  Keep
                # the full set in the proof; the witness pair establishes only
                # that the set contains two independent machines.
                agreements[candidate_id] = (tuple(values), relation)
                break
    return agreements


def _qualified_candidates(
    candidates: Mapping[str, Mapping[str, Any]],
    validations: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Candidates that earn a typed mapping through independent agreement."""

    return {
        candidate_id: supporting
        for candidate_id, (supporting, _relation) in _independent_agreements(candidates, validations).items()
    }


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
        raise VocabularyAtlasError("crosswalk artifact fields differ from v2")
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
        raise VocabularyAtlasError("mapping candidate fields differ from v2")
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
    base_fields = {
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
    }
    if set(record) != base_fields | {"verdictRelation"}:
        raise VocabularyAtlasError("machine validation fields differ from v2")
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
        verdict_relation=record["verdictRelation"],
    )
    if rebuilt.to_dict() != _plain(record):
        raise VocabularyAtlasError("machine validation content differs")
    return rebuilt


def _canonical_nquads(dataset: Dataset) -> bytes:
    if any(isinstance(term, BNode) for context in dataset.graphs() for triple in context for term in triple):
        raise VocabularyAtlasError("atlas must not contain blank nodes")
    serialized = dataset.serialize(format="nquads")
    text = serialized.decode("utf-8") if isinstance(serialized, bytes) else serialized
    lines = sorted(line.strip() for line in text.splitlines() if line.strip())
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


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


# Canonical Atlas 2.0 distribution
# ---------------------------------------------------------------------------
#
# The classes above remain useful to the evidence and source adapters while
# they move onto the shared semantic foundation.  The publication boundary
# below intentionally does not accept those adapter-specific objects.  One
# pinned scope is the complete and only public build input.

from refspec.atlas_index import AtlasIndexError
from refspec.registry.infrastructure.semantic_foundation import SemanticRing

from .atlas_scope import (
    AtlasScopeError,
    PinnedVocabularyAtlasScope,
    validate_atlas_scope_record,
)
from .relation_assertion import (
    EmbeddedRelationAssertionBundle,
    RelationAssertionError,
)
from .release_snapshot import (
    ATLAS_RELEASE_SNAPSHOT_TYPE,
    AtlasReleaseSnapshot,
    AtlasReleaseSnapshotError,
)

_RING_ORDER: tuple[SemanticRing, ...] = (
    "subject",
    "entity",
    "value",
    "legalIdentity",
)
_RELEASE_GRAPH_ROLES = frozenset({"conceptRelease", "concept", "releaseRecord"})
_CROSS_RELEASE_GRAPH_ROLES = frozenset(
    {
        "relationBundle",
        "evidenceAssertion",
        "mappingAssertion",
        "machineProof",
    }
)
_CHILD_ROLE_CONTAINMENT = MappingProxyType(
    {
        "concept": "release",
        "releaseRecord": "release",
        "evidenceAssertion": "relationBundle",
        "mappingAssertion": "relationBundle",
        "machineProof": "relationBundle",
    }
)
_MANIFEST_FIELDS_V2 = frozenset(
    {
        "id",
        "type",
        "schemaVersion",
        "format",
        "generationDigest",
        "scope",
        "implementation",
        "policies",
        "graphs",
        "output",
        "counts",
        "rings",
        "canonicalPayloadDigest",
    }
)
_COUNT_FIELDS_V2 = frozenset(
    {
        "conceptReleases",
        "concepts",
        "releaseRecords",
        "relationBundles",
        "evidenceAssertions",
        "mappingAssertions",
        "machineProofs",
    }
)
_ROLE_COUNT_FIELD = MappingProxyType(
    {
        "conceptRelease": "conceptReleases",
        "concept": "concepts",
        "releaseRecord": "releaseRecords",
        "relationBundle": "relationBundles",
        "evidenceAssertion": "evidenceAssertions",
        "mappingAssertion": "mappingAssertions",
        "machineProof": "machineProofs",
    }
)
_SCOPE_MEDIA_TYPE = "application/vnd.refspec.vocabulary-atlas-scope+json"
_RECORD_PREDICATES = frozenset(
    {
        RDF.type,
        ATLAS.recordRole,
        ATLAS.recordDigest,
        ATLAS.canonicalJson,
        ATLAS.recordId,
        ATLAS.inRelease,
        ATLAS.inRelationBundle,
    }
)
_IRI_OBJECT_PREDICATES = _RECORD_PREDICATES - {
    ATLAS.canonicalJson,
    ATLAS.recordDigest,
}
_MAX_ATLAS_NQUADS_BYTES = 512 * 1024 * 1024
_MAX_ATLAS_NQUAD_LINE_BYTES = 64 * 1024 * 1024
_NQUADS_IRI_FORBIDDEN = frozenset('<>"{}|^`\\')
_RDF_JSON_DATATYPE_TOKEN = f"^^<{RDF.JSON}>".encode("ascii")


@dataclass(frozen=True, slots=True)
class _CanonicalAtlasRecord:
    record: Mapping[str, Any]
    role: str
    release_containers: frozenset[str] = frozenset()
    relation_containers: frozenset[str] = frozenset()

    @property
    def record_bytes(self) -> bytes:
        return _atlas_record_bytes(self.record)

    @property
    def digest(self) -> str:
        return _digest_bytes(self.record_bytes)

    @property
    def identifier(self) -> str:
        return "urn:ref:vocabulary-atlas-record:" + self.digest.removeprefix("sha256:")


@dataclass(frozen=True, slots=True)
class _VerifiedDecodedRecord:
    """One canonical JSON record normalized, hashed, and frozen by the decoder."""

    record: Mapping[str, Any]
    digest: str

    @property
    def identifier(self) -> str:
        return "urn:ref:vocabulary-atlas-record:" + self.digest.removeprefix("sha256:")


@dataclass(frozen=True, slots=True)
class _DecodedAtlasDataset:
    """One immutable, operation-local decode of canonical Atlas N-Quads.

    The closed line parser never creates or caches a mutable rdflib ``Dataset``.
    Consumers reuse these frozen records and counts for their current
    operation only.
    """

    records: tuple[_CanonicalAtlasRecord, ...]
    graph_quad_counts: tuple[tuple[str, int], ...]

    def graph_quad_count(self, graph_id: str) -> int:
        for candidate, count in self.graph_quad_counts:
            if candidate == graph_id:
                return count
        raise VocabularyAtlasError("decoded atlas has no such named graph")

    @property
    def quad_count(self) -> int:
        return sum(count for _, count in self.graph_quad_counts)


class _CanonicalRecordSet:
    """Deduplicate only byte-identical records and merge exact containment."""

    def __init__(self) -> None:
        self._records: dict[str, _CanonicalAtlasRecord] = {}

    def add(
        self,
        value: Mapping[str, Any],
        *,
        role: str,
        in_release: str | None = None,
        in_relation_bundle: str | None = None,
    ) -> None:
        release_containers, relation_containers = self._validated_containment(
            role=role,
            releases=(() if in_release is None else (in_release,)),
            relation_bundles=(
                ()
                if in_relation_bundle is None
                else (in_relation_bundle,)
            ),
        )
        plain = cast(Mapping[str, Any], _plain(value))
        record = _CanonicalAtlasRecord(
            record=cast(Mapping[str, Any], _freeze(plain)),
            role=role,
            release_containers=release_containers,
            relation_containers=relation_containers,
        )
        self._merge(record, identifier=record.identifier)

    def add_decoded(
        self,
        value: _VerifiedDecodedRecord,
        *,
        role: str,
        releases: Sequence[str] = (),
        relation_bundles: Sequence[str] = (),
    ) -> None:
        """Merge one already-verified record with all of its containment.

        The canonical JSON parser has already normalized, hashed, and frozen
        ``value``.  Keeping containment bulk here prevents one size-S record
        referenced by C containers from repeating that O(S) work C times.
        """

        release_containers, relation_containers = self._validated_containment(
            role=role,
            releases=releases,
            relation_bundles=relation_bundles,
        )
        self._merge(
            _CanonicalAtlasRecord(
                record=value.record,
                role=role,
                release_containers=release_containers,
                relation_containers=relation_containers,
            ),
            identifier=value.identifier,
        )

    @staticmethod
    def _validated_containment(
        *,
        role: str,
        releases: Sequence[str],
        relation_bundles: Sequence[str],
    ) -> tuple[frozenset[str], frozenset[str]]:
        if role not in _ROLE_COUNT_FIELD:
            raise VocabularyAtlasError(f"unsupported canonical record role {role!r}")
        if releases and relation_bundles:
            raise VocabularyAtlasError("one atlas record cannot cross container kinds")
        expected_container = _CHILD_ROLE_CONTAINMENT.get(role)
        actual_container = (
            "release" if releases else "relationBundle" if relation_bundles else None
        )
        if expected_container != actual_container:
            raise VocabularyAtlasError(f"atlas {role} record containment differs from its role")
        return (
            frozenset(
                _require_iri(value, "atlas release container")
                for value in releases
            ),
            frozenset(
                _require_iri(value, "atlas relation-bundle container")
                for value in relation_bundles
            ),
        )

    def _merge(
        self,
        record: _CanonicalAtlasRecord,
        *,
        identifier: str,
    ) -> None:
        current = self._records.get(identifier)
        if current is None:
            self._records[identifier] = record
            return
        if current.record != record.record or current.role != record.role:
            raise VocabularyAtlasError("one canonical atlas record digest has conflicting content or roles")
        self._records[identifier] = _CanonicalAtlasRecord(
            record=current.record,
            role=current.role,
            release_containers=(current.release_containers | record.release_containers),
            relation_containers=(current.relation_containers | record.relation_containers),
        )

    def values(self) -> tuple[_CanonicalAtlasRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))


@dataclass(frozen=True, slots=True)
class _ResolvedAtlasScope:
    record: Mapping[str, Any]
    payload: bytes
    snapshots: tuple[AtlasReleaseSnapshot, ...]
    index_rows: Mapping[str, tuple[Mapping[str, Any], ...]]
    relations: tuple[EmbeddedRelationAssertionBundle, ...]


def _atlas_record_bytes(value: Mapping[str, Any]) -> bytes:
    plain = _plain(value)
    _validate_atlas_record_value(plain, path="$")
    return canonical_json(plain).encode("utf-8")


def _validate_atlas_record_value(value: Any, *, path: str) -> None:
    """Validate native record JSON, retaining captured null values exactly."""

    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        if abs(value) > binding.SAFE_INTEGER:
            raise VocabularyAtlasError(f"{path}: integer exceeds the interoperable JSON range")
        return
    if isinstance(value, float):
        raise VocabularyAtlasError(f"{path}: floating-point numbers are not canonical REF JSON")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise VocabularyAtlasError(f"{path}: object keys must be strings")
            _validate_atlas_record_value(child, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            _validate_atlas_record_value(child, path=f"{path}[{index}]")
        return
    raise VocabularyAtlasError(f"{path}: unsupported canonical record value {type(value).__name__}")


def _atlas_record_identifier(value: Mapping[str, Any]) -> str:
    digest = _digest_bytes(_atlas_record_bytes(value))
    return "urn:ref:vocabulary-atlas-record:" + digest.removeprefix("sha256:")


def _native_record_id(value: Mapping[str, Any]) -> str | None:
    native_id = value.get("id")
    jsonld_id = value.get("@id")
    if isinstance(native_id, str) and isinstance(jsonld_id, str) and native_id != jsonld_id:
        raise VocabularyAtlasError("atlas native record carries conflicting id and @id identities")
    if "id" in value:
        if isinstance(native_id, str) and _ABSOLUTE_IRI.fullmatch(native_id):
            return native_id
        return None
    if isinstance(jsonld_id, str) and _ABSOLUTE_IRI.fullmatch(jsonld_id):
        return jsonld_id
    return None


def _snapshot_release_records(
    snapshot: AtlasReleaseSnapshot,
) -> tuple[Mapping[str, Any], ...]:
    """Return non-concept native records carried by one release snapshot."""

    if snapshot.release_pin["releaseKind"] == "managedReferenceRelease":
        graph = _as_mapping(
            snapshot.record.get("selectedReleaseGraph"),
            "managed atlas release snapshot selectedReleaseGraph",
        )
        raw_nodes = graph.get("@graph")
        if not isinstance(raw_nodes, Sequence) or isinstance(
            raw_nodes,
            (str, bytes),
        ):
            raise VocabularyAtlasError("managed atlas release snapshot selectedReleaseGraph.@graph must be an array")
        rows = [
            _as_mapping(
                snapshot.record.get("ringAssignment"),
                "managed atlas release snapshot ringAssignment",
            )
        ]
        for value in raw_nodes:
            if not isinstance(value, Mapping):
                raise VocabularyAtlasError("managed atlas release snapshot graph contains a non-record value")
            if value.get("@id") not in snapshot.member_ids:
                rows.append(value)
        return tuple(rows)

    excluded = {
        "type",
        "schemaVersion",
        "id",
        "contentDigest",
        "releasePin",
        "concepts",
        "members",
        "memberIds",
    }
    rows: list[Mapping[str, Any]] = []
    for key, value in snapshot.record.items():
        if key in excluded:
            continue
        if isinstance(value, Mapping):
            rows.append(value)
            continue
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            if not all(isinstance(item, Mapping) for item in value):
                raise VocabularyAtlasError(f"atlas release snapshot {key} must contain native records")
            rows.extend(cast(Sequence[Mapping[str, Any]], value))
            continue
        raise VocabularyAtlasError(f"atlas release snapshot {key} is not a native record or record array")
    return tuple(rows)


def _managed_snapshot_reference(
    snapshot: AtlasReleaseSnapshot,
) -> dict[str, Any]:
    """Replace one embedded managed graph copy with exact record references."""

    if snapshot.release_pin["releaseKind"] != "managedReferenceRelease":
        raise VocabularyAtlasError("managed snapshot reference requires a managed release")
    selected_graph = _as_mapping(
        snapshot.record.get("selectedReleaseGraph"),
        "managed atlas release snapshot selectedReleaseGraph",
    )
    graph_rows = _as_sequence(
        selected_graph.get("@graph"),
        "managed atlas release snapshot selectedReleaseGraph.@graph",
    )
    member_ids = snapshot.member_ids
    record_refs: list[dict[str, str]] = []
    for index, value in enumerate(graph_rows):
        row = _as_mapping(
            value,
            f"managed atlas release snapshot selectedReleaseGraph.@graph[{index}]",
        )
        native_id = _native_record_id(row)
        if native_id is None:
            raise VocabularyAtlasError("managed selected graph record lacks one native identity")
        record_refs.append(
            {
                "nativeId": native_id,
                "recordId": _atlas_record_identifier(row),
                "role": "concept" if native_id in member_ids else "releaseRecord",
            }
        )
    record_refs.sort(key=lambda value: value["nativeId"])
    ring_assignment = _as_mapping(
        snapshot.record.get("ringAssignment"),
        "managed atlas release snapshot ringAssignment",
    )
    return {
        "type": _MANAGED_SNAPSHOT_REFERENCE_TYPE,
        "schemaVersion": _MANAGED_SNAPSHOT_REFERENCE_VERSION,
        "snapshot": {
            "id": snapshot.identifier,
            "contentDigest": snapshot.content_digest,
            "schemaVersion": cast(str, snapshot.record["schemaVersion"]),
        },
        "releasePin": _plain(snapshot.release_pin),
        "ringAssignmentRecord": _atlas_record_identifier(ring_assignment),
        "selectedGraphContext": _plain(selected_graph.get("@context")),
        "memberIds": sorted(member_ids),
        "selectedGraphRecords": record_refs,
    }


def _embedded_snapshot_record(snapshot: AtlasReleaseSnapshot) -> Mapping[str, Any]:
    if snapshot.release_pin["releaseKind"] == "managedReferenceRelease":
        return _managed_snapshot_reference(snapshot)
    return snapshot.as_record()


def _managed_snapshot_from_reference(
    reference: Mapping[str, Any],
    *,
    records_by_id: Mapping[str, _CanonicalAtlasRecord],
) -> AtlasReleaseSnapshot:
    expected_fields = {
        "type",
        "schemaVersion",
        "snapshot",
        "releasePin",
        "ringAssignmentRecord",
        "selectedGraphContext",
        "memberIds",
        "selectedGraphRecords",
    }
    if set(reference) != expected_fields:
        raise VocabularyAtlasError("managed atlas snapshot reference fields differ")
    if (
        reference.get("type") != _MANAGED_SNAPSHOT_REFERENCE_TYPE
        or reference.get("schemaVersion") != _MANAGED_SNAPSHOT_REFERENCE_VERSION
    ):
        raise VocabularyAtlasError("managed atlas snapshot reference version is unsupported")
    snapshot_pin = _as_mapping(
        reference.get("snapshot"),
        "managed atlas snapshot reference snapshot",
    )
    if set(snapshot_pin) != {"id", "contentDigest", "schemaVersion"}:
        raise VocabularyAtlasError("managed atlas snapshot reference snapshot fields differ")
    snapshot_id = _require_iri(
        snapshot_pin.get("id"),
        "managed atlas snapshot reference snapshot id",
    )
    snapshot_digest = _require_digest(
        snapshot_pin.get("contentDigest"),
        "managed atlas snapshot reference snapshot digest",
    )
    snapshot_schema = _require_text(
        snapshot_pin.get("schemaVersion"),
        "managed atlas snapshot reference snapshot schemaVersion",
    )
    if snapshot_schema != "1.1":
        raise VocabularyAtlasError("managed atlas snapshot references require snapshot schema 1.1")
    release_pin = _as_mapping(
        reference.get("releasePin"),
        "managed atlas snapshot reference releasePin",
    )
    release_id = _require_iri(
        release_pin.get("releaseId"),
        "managed atlas snapshot reference releasePin.releaseId",
    )
    if release_pin.get("releaseKind") != "managedReferenceRelease":
        raise VocabularyAtlasError("managed atlas snapshot reference release kind differs")
    member_values = _as_sequence(
        reference.get("memberIds"),
        "managed atlas snapshot reference memberIds",
    )
    member_ids = tuple(
        _require_iri(
            value,
            f"managed atlas snapshot reference memberIds[{index}]",
        )
        for index, value in enumerate(member_values)
    )
    if not member_ids or member_ids != tuple(sorted(set(member_ids))):
        raise VocabularyAtlasError("managed atlas snapshot reference memberIds are not canonical")
    graph_ref_values = _as_sequence(
        reference.get("selectedGraphRecords"),
        "managed atlas snapshot reference selectedGraphRecords",
    )
    graph_nodes: list[Mapping[str, Any]] = []
    graph_ref_rows: list[dict[str, str]] = []
    for index, raw in enumerate(graph_ref_values):
        row = _as_mapping(
            raw,
            f"managed atlas snapshot reference selectedGraphRecords[{index}]",
        )
        if set(row) != {"nativeId", "recordId", "role"}:
            raise VocabularyAtlasError("managed atlas snapshot graph reference fields differ")
        native_id = _require_iri(
            row.get("nativeId"),
            "managed atlas snapshot graph nativeId",
        )
        record_id = _require_iri(
            row.get("recordId"),
            "managed atlas snapshot graph recordId",
        )
        role = row.get("role")
        expected_role = "concept" if native_id in member_ids else "releaseRecord"
        record = records_by_id.get(record_id)
        if (
            role != expected_role
            or record is None
            or record.role != expected_role
            or release_id not in record.release_containers
            or record.identifier != record_id
            or _native_record_id(record.record) != native_id
        ):
            raise VocabularyAtlasError("managed atlas snapshot graph reference does not resolve exactly")
        graph_nodes.append(record.record)
        graph_ref_rows.append(
            {
                "nativeId": native_id,
                "recordId": record_id,
                "role": cast(str, role),
            }
        )
    if graph_ref_rows != sorted(
        graph_ref_rows,
        key=lambda value: value["nativeId"],
    ) or len({row["nativeId"] for row in graph_ref_rows}) != len(graph_ref_rows):
        raise VocabularyAtlasError("managed atlas snapshot graph references are not canonical")
    ring_record_id = _require_iri(
        reference.get("ringAssignmentRecord"),
        "managed atlas snapshot reference ringAssignmentRecord",
    )
    ring_record = records_by_id.get(ring_record_id)
    if (
        ring_record is None
        or ring_record.role != "releaseRecord"
        or release_id not in ring_record.release_containers
        or ring_record.identifier != ring_record_id
    ):
        raise VocabularyAtlasError("managed atlas snapshot ring assignment reference does not resolve exactly")
    reconstructed = {
        "type": ATLAS_RELEASE_SNAPSHOT_TYPE,
        "schemaVersion": snapshot_schema,
        "releasePin": _plain(release_pin),
        "ringAssignment": _plain(ring_record.record),
        "selectedReleaseGraph": {
            "@context": _plain(reference.get("selectedGraphContext")),
            "@graph": sorted(
                (_plain(value) for value in graph_nodes),
                key=lambda value: cast(str, value["@id"]),
            ),
        },
        "memberIds": list(member_ids),
        "id": snapshot_id,
        "contentDigest": snapshot_digest,
    }
    try:
        snapshot = AtlasReleaseSnapshot.from_record(reconstructed)
    except AtlasReleaseSnapshotError as error:
        raise VocabularyAtlasError(str(error)) from error
    if _managed_snapshot_reference(snapshot) != _plain(reference):
        raise VocabularyAtlasError("managed atlas snapshot reference does not reproduce exactly")
    return snapshot


def _snapshots_from_records(
    records: Sequence[_CanonicalAtlasRecord],
) -> tuple[AtlasReleaseSnapshot, ...]:
    records_by_id = {record.identifier: record for record in records}
    snapshots: list[AtlasReleaseSnapshot] = []
    for record in records:
        if record.role != "conceptRelease":
            continue
        if record.record.get("type") == _MANAGED_SNAPSHOT_REFERENCE_TYPE:
            snapshots.append(
                _managed_snapshot_from_reference(
                    record.record,
                    records_by_id=records_by_id,
                )
            )
        else:
            try:
                snapshots.append(AtlasReleaseSnapshot.from_record(record.record))
            except AtlasReleaseSnapshotError as error:
                raise VocabularyAtlasError(str(error)) from error
    return tuple(snapshots)


def _resolved_index_rows(
    *,
    scope_record: Mapping[str, Any],
    index: Mapping[str, Any],
) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    raw_rows = index.get("rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise VocabularyAtlasError("pinned atlas index rows must be an array")
    rows: dict[str, Mapping[str, Any]] = {}
    for position, value in enumerate(raw_rows):
        if not isinstance(value, Mapping):
            raise VocabularyAtlasError(f"pinned atlas index rows[{position}] must be an object")
        row_id = _require_iri(value.get("rowId"), f"pinned atlas index rows[{position}].rowId")
        if row_id in rows:
            raise VocabularyAtlasError("pinned atlas index repeats a rowId")
        row_digest = _require_digest(
            value.get("rowDigest"),
            f"pinned atlas index rows[{position}].rowDigest",
        )
        basis = {key: _plain(item) for key, item in value.items() if key not in {"rowId", "rowDigest"}}
        if binding.canonical_sha256(basis) != row_digest:
            raise VocabularyAtlasError("pinned atlas index rowDigest is stale")
        if row_id != "urn:ref:atlas-index-row:" + row_digest.removeprefix("sha256:"):
            raise VocabularyAtlasError("pinned atlas index rowId is stale")
        rows[row_id] = cast(Mapping[str, Any], _freeze(_plain(value)))

    resolved: dict[str, tuple[Mapping[str, Any], ...]] = {}
    used: set[str] = set()
    for position, release in enumerate(cast(Sequence[Mapping[str, Any]], scope_record["releases"])):
        release_id = cast(str, release["releaseId"])
        values: list[Mapping[str, Any]] = []
        for reference in cast(Sequence[Mapping[str, Any]], release["atlasIndexRows"]):
            row_id = cast(str, reference["rowId"])
            row = rows.get(row_id)
            if row is None:
                raise VocabularyAtlasError("atlas scope index-row reference is absent from the pinned index")
            if row.get("rowDigest") != reference.get("rowDigest"):
                raise VocabularyAtlasError("atlas scope index-row digest differs from the pinned index")
            release_pin = row.get("release")
            if (
                not isinstance(release_pin, Mapping)
                or release_pin.get("releaseId") != release_id
                or release_pin.get("manifestDigest") != release.get("manifestDigest")
                or row.get("semanticRing") != release.get("semanticRing")
            ):
                raise VocabularyAtlasError("resolved atlas index row differs from its exact scope release")
            if row_id in used:
                raise VocabularyAtlasError("one atlas index row cannot classify two scoped releases")
            used.add(row_id)
            values.append(row)
        if not values:
            raise VocabularyAtlasError(f"atlas scope releases[{position}] has no resolved index row")
        resolved[release_id] = tuple(values)
    return cast(Mapping[str, tuple[Mapping[str, Any], ...]], _freeze(resolved))


def _resolve_atlas_scope(scope: PinnedVocabularyAtlasScope) -> _ResolvedAtlasScope:
    if not isinstance(scope, PinnedVocabularyAtlasScope):
        raise VocabularyAtlasError("build_vocabulary_atlas requires one PinnedVocabularyAtlasScope")
    try:
        verified = scope.verified_scope()
        scope_record = verified.as_record()
        scope_payload = verified.artifact_bytes()
        if _digest_bytes(scope_payload) != scope.file_digest:
            raise VocabularyAtlasError("atlas scope canonical bytes differ from the pinned file")
        index = verified.atlas_index.verified_index()
        index_rows = _resolved_index_rows(
            scope_record=scope_record,
            index=index,
        )
        snapshots = tuple(AtlasReleaseSnapshot.create(release) for release in verified.releases)
        memberships = {snapshot.release_id: snapshot.member_ids for snapshot in snapshots}
        relations: list[EmbeddedRelationAssertionBundle] = []
        for pinned in verified.relation_bundles:
            bundle = pinned.verified_bundle()
            relations.append(
                EmbeddedRelationAssertionBundle.from_record(
                    bundle.as_record(),
                    release_memberships={
                        cast(str, release_pin["releaseId"]): memberships[cast(str, release_pin["releaseId"])]
                        for release_pin in bundle.release_pins
                    },
                )
            )
    except (
        AtlasIndexError,
        AtlasReleaseSnapshotError,
        AtlasScopeError,
        KeyError,
        RelationAssertionError,
    ) as error:
        if isinstance(error, VocabularyAtlasError):
            raise
        raise VocabularyAtlasError(str(error)) from error
    return _ResolvedAtlasScope(
        record=cast(Mapping[str, Any], _freeze(scope_record)),
        payload=scope_payload,
        snapshots=snapshots,
        index_rows=index_rows,
        relations=tuple(relations),
    )


def _concept_identity(value: Mapping[str, Any]) -> str:
    identifier = value.get("id", value.get("@id"))
    return _require_iri(identifier, "atlas concept identity")


def _scope_record_set(resolved: _ResolvedAtlasScope) -> _CanonicalRecordSet:
    records = _CanonicalRecordSet()
    concept_rings: dict[str, SemanticRing] = {}
    for snapshot in resolved.snapshots:
        records.add(_embedded_snapshot_record(snapshot), role="conceptRelease")
        for concept in snapshot.concept_records:
            identity = _concept_identity(concept)
            previous = concept_rings.setdefault(identity, snapshot.semantic_ring)
            if previous != snapshot.semantic_ring:
                raise VocabularyAtlasError("one concept identity cannot belong to two semantic rings")
            records.add(
                concept,
                role="concept",
                in_release=snapshot.release_id,
            )
        for row in _snapshot_release_records(snapshot):
            records.add(
                row,
                role="releaseRecord",
                in_release=snapshot.release_id,
            )
        for row in resolved.index_rows[snapshot.release_id]:
            records.add(
                row,
                role="releaseRecord",
                in_release=snapshot.release_id,
            )

    for bundle in resolved.relations:
        records.add(bundle.as_record(), role="relationBundle")
        for evidence in bundle.evidence_assertions:
            records.add(
                evidence.as_record(),
                role="evidenceAssertion",
                in_relation_bundle=bundle.identifier,
            )
        for mapping in bundle.mapping_assertions:
            records.add(
                mapping.as_record(),
                role="mappingAssertion",
                in_relation_bundle=bundle.identifier,
            )
        for proof in bundle.machine_proof_pins:
            records.add(
                proof,
                role="machineProof",
                in_relation_bundle=bundle.identifier,
            )
    return records


def _record_dataset(
    records: Sequence[_CanonicalAtlasRecord],
    *,
    asset_id: str,
) -> tuple[bytes, Mapping[str, int]]:
    release_graph_id = asset_id + ":release-facts"
    cross_graph_id = asset_id + ":cross-release"
    dataset = Dataset(default_union=False)
    release_graph = dataset.graph(URIRef(release_graph_id))
    cross_graph = dataset.graph(URIRef(cross_graph_id))
    counts = {field: 0 for field in _COUNT_FIELDS_V2}
    for record in records:
        graph = release_graph if record.role in _RELEASE_GRAPH_ROLES else cross_graph
        node = URIRef(record.identifier)
        graph.add((node, RDF.type, ATLAS.CanonicalRecord))
        graph.add((node, ATLAS.recordRole, ATLAS[record.role]))
        graph.add((node, ATLAS.recordDigest, RdfLiteral(record.digest)))
        graph.add(
            (
                node,
                ATLAS.canonicalJson,
                RdfLiteral(
                    record.record_bytes.decode("utf-8"),
                    datatype=RDF.JSON,
                ),
            )
        )
        native_id = _native_record_id(record.record)
        if native_id is not None:
            graph.add((node, ATLAS.recordId, URIRef(native_id)))
        for release in sorted(record.release_containers):
            graph.add((node, ATLAS.inRelease, URIRef(release)))
        for bundle in sorted(record.relation_containers):
            graph.add((node, ATLAS.inRelationBundle, URIRef(bundle)))
        counts[_ROLE_COUNT_FIELD[record.role]] += 1
    payload = _canonical_nquads(dataset)
    # Keep the producer inside the same explicit size and line-shape limits as
    # the file-only verifier so it cannot emit an asset that cannot be opened.
    for _ in _iter_bounded_canonical_nquad_lines(payload):
        pass
    graph_counts = {
        "releaseFacts": len(release_graph),
        "crossRelease": len(cross_graph),
    }
    return payload, cast(Mapping[str, int], {**counts, **graph_counts})


def _implementation_pin_v2() -> dict[str, Any]:
    package_root = Path(__file__).parents[1]
    sources = [
        {
            "path": f"refspec/{relative}",
            "digest": _digest_bytes((package_root / relative).read_bytes()),
        }
        for relative in _IMPLEMENTATION_SOURCE_PATHS
    ]
    return {
        "id": "urn:ref:implementation:vocabulary-atlas:2.0",
        "version": "2.0",
        "sourceModules": sources,
        "runtime": {
            "jsonschemaVersion": importlib.metadata.version("jsonschema"),
            "pyarrowVersion": importlib.metadata.version("pyarrow"),
            "pythonRequirement": ">=3.10",
            "pythonVersion": platform.python_version(),
            "rdflibVersion": importlib.metadata.version("rdflib"),
        },
    }


def _scope_descriptor(resolved: _ResolvedAtlasScope) -> dict[str, Any]:
    return {
        "role": "VocabularyAtlasScope",
        "path": SCOPE_FILE,
        "mediaType": _SCOPE_MEDIA_TYPE,
        "id": cast(str, resolved.record["id"]),
        "contentDigest": cast(str, resolved.record["contentDigest"]),
        "fileDigest": _digest_bytes(resolved.payload),
        "byteLength": len(resolved.payload),
    }


def _ring_summaries(
    records: Sequence[_CanonicalAtlasRecord],
    *,
    snapshots: Sequence[AtlasReleaseSnapshot],
    relations: Sequence[EmbeddedRelationAssertionBundle],
) -> list[dict[str, Any]]:
    release_rings = {snapshot.release_id: snapshot.semantic_ring for snapshot in snapshots}
    snapshot_rings = {
        _atlas_record_identifier(_embedded_snapshot_record(snapshot)): snapshot.semantic_ring for snapshot in snapshots
    }
    bundle_rings = {bundle.identifier: bundle.semantic_ring for bundle in relations}
    values: dict[SemanticRing, dict[str, set[str]]] = {
        ring: {
            "release": set(),
            "concept": set(),
            "bundle": set(),
            "mapping": set(),
        }
        for ring in _RING_ORDER
    }
    for record in records:
        if record.role == "conceptRelease":
            try:
                ring = snapshot_rings[record.identifier]
            except KeyError as error:
                raise VocabularyAtlasError("atlas concept release does not resolve to a verified snapshot") from error
            values[ring]["release"].add(record.identifier)
        elif record.role == "concept":
            rings = {release_rings[value] for value in record.release_containers}
            if len(rings) != 1:
                raise VocabularyAtlasError("one canonical concept record cannot cross semantic rings")
            values[rings.pop()]["concept"].add(record.identifier)
        elif record.role == "relationBundle":
            bundle = EmbeddedRelationAssertionBundle.from_record(record.record)
            values[bundle.semantic_ring]["bundle"].add(record.identifier)
        elif record.role == "mappingAssertion":
            rings = {bundle_rings[value] for value in record.relation_containers}
            if len(rings) != 1:
                raise VocabularyAtlasError("one mapping assertion record cannot cross semantic rings")
            values[rings.pop()]["mapping"].add(record.identifier)
    return [
        {
            "semanticRing": ring,
            "releaseCount": len(values[ring]["release"]),
            "conceptCount": len(values[ring]["concept"]),
            "relationBundleCount": len(values[ring]["bundle"]),
            "mappingAssertionCount": len(values[ring]["mapping"]),
        }
        for ring in _RING_ORDER
    ]


def _build_resolved_atlas_v2(resolved: _ResolvedAtlasScope) -> VocabularyAtlasAsset:
    implementation = _implementation_pin_v2()
    scope_descriptor = _scope_descriptor(resolved)
    generation_basis = {
        "format": FORMAT_ID,
        "scope": scope_descriptor,
        "implementation": implementation,
        "policies": dict(_POLICIES),
    }
    generation_digest = _digest_value(generation_basis)
    asset_id = "urn:ref:vocabulary-atlas:" + generation_digest.removeprefix("sha256:")
    record_set = _scope_record_set(resolved)
    records = record_set.values()
    payload, observed = _record_dataset(records, asset_id=asset_id)
    counts = {field: observed[field] for field in _COUNT_FIELDS_V2}
    graphs = [
        {
            "role": "releaseFacts",
            "id": asset_id + ":release-facts",
            "quadCount": observed["releaseFacts"],
        },
        {
            "role": "crossRelease",
            "id": asset_id + ":cross-release",
            "quadCount": observed["crossRelease"],
        },
    ]
    manifest: dict[str, Any] = {
        "id": asset_id,
        "type": "urn:ref:type:VocabularyAtlasManifest",
        "schemaVersion": SCHEMA_VERSION,
        "format": FORMAT_ID,
        "generationDigest": generation_digest,
        "scope": scope_descriptor,
        "implementation": implementation,
        "policies": dict(_POLICIES),
        "graphs": graphs,
        "output": {
            "path": ATLAS_FILE,
            "mediaType": "application/n-quads",
            "digest": _digest_bytes(payload),
            "byteLength": len(payload),
            "quadCount": observed["releaseFacts"] + observed["crossRelease"],
        },
        "counts": counts,
        "rings": _ring_summaries(
            records,
            snapshots=resolved.snapshots,
            relations=resolved.relations,
        ),
    }
    manifest["canonicalPayloadDigest"] = _manifest_digest(manifest)
    return VocabularyAtlasAsset._verified(
        payload=payload,
        scope_payload=resolved.payload,
        manifest=cast(Mapping[str, Any], _freeze(manifest)),
    )


def _read_distribution(directory: Path | str) -> tuple[Path, dict[str, bytes]]:
    root = Path(directory)
    if root.is_symlink():
        raise VocabularyAtlasError("atlas directory must not be a symlink")
    try:
        root = root.resolve(strict=True)
    except FileNotFoundError as error:
        raise VocabularyAtlasError("atlas directory does not exist") from error
    if not root.is_dir():
        raise VocabularyAtlasError("atlas path must be a directory")
    expected = {ATLAS_FILE, MANIFEST_FILE, SCOPE_FILE}
    entries = {item.name: item for item in root.iterdir()}
    if set(entries) != expected:
        raise VocabularyAtlasError("atlas distribution file set differs from 2.0")
    if any(item.is_symlink() or not item.is_file() for item in entries.values()):
        raise VocabularyAtlasError("atlas distribution must contain three regular files and no symlinks")
    payloads = {name: entries[name].read_bytes() for name in expected}
    final_entries = {item.name: item for item in root.iterdir()}
    if (
        set(final_entries) != expected
        or any(item.is_symlink() or not item.is_file() for item in final_entries.values())
        or any(final_entries[name].read_bytes() != payloads[name] for name in expected)
    ):
        raise VocabularyAtlasError("atlas distribution changed while opening")
    return root, payloads


def _require_v2_count(value: object, label: str, *, positive: bool = False) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < (1 if positive else 0)
        or value > binding.SAFE_INTEGER
    ):
        qualifier = "positive" if positive else "non-negative"
        raise VocabularyAtlasError(f"{label} must be a {qualifier} safe integer")
    return value


def _validate_implementation_v2(candidate: object) -> Mapping[str, Any]:
    row = _as_mapping(candidate, "atlas implementation")
    if set(row) != {"id", "version", "sourceModules", "runtime"}:
        raise VocabularyAtlasError("atlas implementation fields differ from 2.0")
    _require_iri(row.get("id"), "atlas implementation id")
    _require_text(row.get("version"), "atlas implementation version")
    sources = _as_sequence(row.get("sourceModules"), "atlas implementation sourceModules")
    if not sources:
        raise VocabularyAtlasError("atlas implementation sourceModules must not be empty")
    paths: list[str] = []
    for position, value in enumerate(sources):
        source = _as_mapping(value, f"atlas implementation sourceModules[{position}]")
        if set(source) != {"path", "digest"}:
            raise VocabularyAtlasError("atlas implementation source-module fields differ")
        path = _require_text(source.get("path"), "atlas implementation source-module path")
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise VocabularyAtlasError("atlas implementation source-module path is unsafe")
        _require_digest(source.get("digest"), "atlas implementation source-module digest")
        paths.append(path)
    if paths != sorted(paths) or len(set(paths)) != len(paths):
        raise VocabularyAtlasError("atlas implementation sourceModules are not unique and ordered")
    runtime = _as_mapping(row.get("runtime"), "atlas implementation runtime")
    if not runtime or any(
        not isinstance(key, str) or not key or not isinstance(item, str) or not item for key, item in runtime.items()
    ):
        raise VocabularyAtlasError("atlas implementation runtime is invalid")
    return row


def _parse_canonical_record(
    value: str,
    *,
    expected_digest: str,
) -> _VerifiedDecodedRecord:
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise VocabularyAtlasError("atlas canonicalJson is not valid canonical REF JSON") from error
    if not isinstance(decoded, Mapping):
        raise VocabularyAtlasError("atlas canonicalJson record must be an object")
    canonical_bytes = value.encode("utf-8")
    if _atlas_record_bytes(decoded) != canonical_bytes:
        raise VocabularyAtlasError("atlas canonicalJson bytes are not canonical")
    digest = _digest_bytes(canonical_bytes)
    if digest != expected_digest:
        raise VocabularyAtlasError("atlas recordDigest differs from canonicalJson")
    return _VerifiedDecodedRecord(
        record=cast(Mapping[str, Any], _freeze(decoded)),
        digest=digest,
    )


def _one_object(values: Mapping[URIRef, Sequence[Any]], predicate: URIRef, label: str) -> Any:
    found = tuple(values.get(predicate, ()))
    if len(found) != 1:
        raise VocabularyAtlasError(f"atlas record must have exactly one {label}")
    return found[0]


def _canonical_nquad_literal(value: str) -> bytes:
    """Serialize the literal form used by rdflib's N-Quads writer."""

    escaped = value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"').replace("\r", "\\r")
    return f'"{escaped}"'.encode()


def _parse_canonical_nquad_literal(token: bytes, *, label: str) -> str:
    try:
        value = json.loads(
            token.decode("utf-8"),
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise VocabularyAtlasError(f"atlas {label} literal is invalid") from error
    if not isinstance(value, str):
        raise VocabularyAtlasError(f"atlas {label} must be a string literal")
    try:
        canonical = _canonical_nquad_literal(value)
    except UnicodeEncodeError as error:
        raise VocabularyAtlasError(f"atlas {label} literal is not valid UTF-8") from error
    if canonical != token:
        raise VocabularyAtlasError(f"atlas {label} literal is not canonical")
    return value


def _parse_canonical_nquad_iri(token: bytes, *, label: str) -> str:
    if len(token) < 3 or not token.startswith(b"<") or not token.endswith(b">"):
        raise VocabularyAtlasError(f"atlas {label} must be an N-Quads IRI")
    try:
        value = token[1:-1].decode("utf-8")
    except UnicodeDecodeError as error:
        raise VocabularyAtlasError(f"atlas {label} is not valid UTF-8") from error
    if any(ord(character) <= 0x20 or character in _NQUADS_IRI_FORBIDDEN for character in value):
        raise VocabularyAtlasError(f"atlas {label} contains an invalid N-Quads IRI character")
    return _require_iri(value, f"atlas {label}")


def _take_canonical_nquad_iri(
    line: bytes,
    start: int,
    *,
    label: str,
) -> tuple[str, int]:
    if start >= len(line) or line[start] != ord("<"):
        raise VocabularyAtlasError(f"atlas {label} must start with an N-Quads IRI")
    end = line.find(b">", start + 1)
    if end < 0:
        raise VocabularyAtlasError(f"atlas {label} N-Quads IRI is unterminated")
    return (
        _parse_canonical_nquad_iri(
            line[start : end + 1],
            label=label,
        ),
        end + 1,
    )


def _parse_canonical_atlas_nquad(
    line: bytes,
) -> tuple[URIRef, URIRef, URIRef | RdfLiteral, URIRef]:
    subject, position = _take_canonical_nquad_iri(
        line,
        0,
        label="N-Quads subject",
    )
    if line[position : position + 1] != b" ":
        raise VocabularyAtlasError("atlas N-Quads subject separator differs")
    predicate_value, position = _take_canonical_nquad_iri(
        line,
        position + 1,
        label="N-Quads predicate",
    )
    predicate = URIRef(predicate_value)
    if predicate not in _RECORD_PREDICATES:
        raise VocabularyAtlasError("atlas exact record index has an extra predicate")
    if line[position : position + 1] != b" ":
        raise VocabularyAtlasError("atlas N-Quads predicate separator differs")
    object_start = position + 1

    if not line.endswith(b" ."):
        raise VocabularyAtlasError("atlas N-Quads line terminator differs")
    graph_separator = line.rfind(b" <", object_start, len(line) - 2)
    if graph_separator < object_start:
        raise VocabularyAtlasError("atlas N-Quads named graph is missing")
    graph = _parse_canonical_nquad_iri(
        line[graph_separator + 1 : -2],
        label="N-Quads named graph",
    )
    object_token = line[object_start:graph_separator]

    if predicate in _IRI_OBJECT_PREDICATES:
        object_value = _parse_canonical_nquad_iri(
            object_token,
            label="N-Quads object",
        )
        object_: URIRef | RdfLiteral = URIRef(object_value)
        canonical_object = f"<{object_value}>".encode()
    elif predicate == ATLAS.recordDigest:
        literal = _parse_canonical_nquad_literal(
            object_token,
            label="recordDigest",
        )
        object_ = RdfLiteral(literal)
        canonical_object = _canonical_nquad_literal(literal)
    else:
        if not object_token.endswith(_RDF_JSON_DATATYPE_TOKEN):
            raise VocabularyAtlasError("atlas canonicalJson datatype differs")
        literal_token = object_token[: -len(_RDF_JSON_DATATYPE_TOKEN)]
        literal = _parse_canonical_nquad_literal(
            literal_token,
            label="canonicalJson",
        )
        object_ = RdfLiteral(literal, datatype=RDF.JSON)
        canonical_object = _canonical_nquad_literal(literal) + _RDF_JSON_DATATYPE_TOKEN

    canonical_line = b" ".join(
        (
            f"<{subject}>".encode(),
            f"<{predicate_value}>".encode(),
            canonical_object,
            f"<{graph}>".encode(),
            b".",
        )
    )
    if canonical_line != line:
        raise VocabularyAtlasError("atlas N-Quads line is not canonical")
    return URIRef(subject), predicate, object_, URIRef(graph)


def _iter_bounded_canonical_nquad_lines(payload: bytes) -> Iterable[bytes]:
    if len(payload) > _MAX_ATLAS_NQUADS_BYTES:
        raise VocabularyAtlasError("atlas N-Quads exceeds the verifier byte limit")
    if payload and not payload.endswith(b"\n"):
        raise VocabularyAtlasError("atlas canonical N-Quads must end with one newline")

    previous: bytes | None = None
    start = 0
    while start < len(payload):
        end = payload.find(b"\n", start)
        if end < 0:  # guarded by the final-newline check
            raise VocabularyAtlasError("atlas canonical N-Quads line is unterminated")
        line_length = end - start
        if line_length == 0:
            raise VocabularyAtlasError("atlas canonical N-Quads contains an empty line")
        if line_length > _MAX_ATLAS_NQUAD_LINE_BYTES:
            raise VocabularyAtlasError("atlas N-Quads line exceeds the verifier byte limit")
        line = payload[start:end]
        if previous is not None and previous >= line:
            raise VocabularyAtlasError("atlas canonical N-Quads lines are not unique and ordered")
        yield line
        previous = line
        start = end + 1


def _iter_canonical_atlas_nquads(
    payload: bytes,
) -> Iterable[tuple[URIRef, URIRef, URIRef | RdfLiteral, URIRef]]:
    for line in _iter_bounded_canonical_nquad_lines(payload):
        yield _parse_canonical_atlas_nquad(line)


def _decode_atlas_dataset(
    payload: bytes,
    *,
    asset_id: str,
) -> _DecodedAtlasDataset:
    """Decode the bounded closed Atlas format without container-amplified work.

    Line scanning, grouping, and containment attachment are linear in encoded
    quads and bytes. Canonical REF JSON verification still sorts each object's
    keys, and final records retain deterministic identifier sorting; the exact
    bound is therefore O(P + sum(K_i log K_i) + R log R), not a claim of pure
    O(P), where P is payload size, K_i an object key count, and R the number of
    records.
    """

    graph_roles = {
        asset_id + ":release-facts": _RELEASE_GRAPH_ROLES,
        asset_id + ":cross-release": _CROSS_RELEASE_GRAPH_ROLES,
    }
    graph_quad_counts = dict.fromkeys(graph_roles, 0)
    grouped: dict[tuple[str, URIRef], dict[URIRef, list[Any]]] = defaultdict(lambda: defaultdict(list))
    for subject, predicate, object_, context in _iter_canonical_atlas_nquads(payload):
        graph_id = str(context)
        if graph_id not in graph_roles:
            raise VocabularyAtlasError("atlas N-Quads named graphs differ")
        graph_quad_counts[graph_id] += 1
        grouped[(graph_id, subject)][predicate].append(object_)

    records = _CanonicalRecordSet()
    for (graph_id, node), values in grouped.items():
        if not set(values) <= _RECORD_PREDICATES:
            raise VocabularyAtlasError("atlas exact record index has an extra predicate")
        type_value = _one_object(values, RDF.type, "rdf:type")
        if type_value != ATLAS.CanonicalRecord:
            raise VocabularyAtlasError("atlas record rdf:type differs")
        role_value = _one_object(values, ATLAS.recordRole, "recordRole")
        if not isinstance(role_value, URIRef) or not str(role_value).startswith(str(ATLAS)):
            raise VocabularyAtlasError("atlas recordRole is invalid")
        role = str(role_value).removeprefix(str(ATLAS))
        if role not in graph_roles[graph_id]:
            raise VocabularyAtlasError("atlas record role is in the wrong named graph")
        digest_value = _one_object(values, ATLAS.recordDigest, "recordDigest")
        if (
            not isinstance(digest_value, RdfLiteral)
            or digest_value.datatype is not None
            or digest_value.language is not None
        ):
            raise VocabularyAtlasError("atlas recordDigest must be a plain literal")
        digest = _require_digest(str(digest_value), "atlas recordDigest")
        json_value = _one_object(values, ATLAS.canonicalJson, "canonicalJson")
        if not isinstance(json_value, RdfLiteral) or json_value.datatype != RDF.JSON:
            raise VocabularyAtlasError("atlas canonicalJson must be an rdf:JSON literal")
        record = _parse_canonical_record(
            str(json_value),
            expected_digest=digest,
        )
        if str(node) != record.identifier:
            raise VocabularyAtlasError("atlas record IRI differs from recordDigest")

        record_ids = tuple(values.get(ATLAS.recordId, ()))
        expected_record_id = _native_record_id(record.record)
        if expected_record_id is None:
            if record_ids:
                raise VocabularyAtlasError("atlas recordId is not derived from native id")
        elif record_ids != (URIRef(expected_record_id),):
            raise VocabularyAtlasError("atlas recordId differs from native id")

        release_containers = tuple(values.get(ATLAS.inRelease, ()))
        relation_containers = tuple(values.get(ATLAS.inRelationBundle, ()))
        if any(not isinstance(value, URIRef) for value in (*release_containers, *relation_containers)):
            raise VocabularyAtlasError("atlas record containment must use IRIs")
        expected = _CHILD_ROLE_CONTAINMENT.get(role)
        if expected == "release" and (not release_containers or relation_containers):
            raise VocabularyAtlasError("atlas release child containment differs")
        if expected == "relationBundle" and (not relation_containers or release_containers):
            raise VocabularyAtlasError("atlas relation child containment differs")
        if expected is None and (release_containers or relation_containers):
            raise VocabularyAtlasError("atlas top-level record points to itself or a container")
        records.add_decoded(
            record,
            role=role,
            releases=tuple(str(value) for value in release_containers),
            relation_bundles=tuple(str(value) for value in relation_containers),
        )

    # Canonical byte equality above covers order, duplicates, and RDF lexical
    # form.  The closed predicate and record checks consume every parsed quad,
    # so rebuilding the same dataset would add a second O(n log n)
    # canonicalization without strengthening the trust-boundary validation.
    return _DecodedAtlasDataset(
        records=records.values(),
        graph_quad_counts=tuple(graph_quad_counts.items()),
    )


def _decode_record_dataset(
    payload: bytes,
    *,
    asset_id: str,
) -> tuple[_CanonicalAtlasRecord, ...]:
    """Decode records for internal callers that do not need dataset counts."""

    return _decode_atlas_dataset(payload, asset_id=asset_id).records


def _record_ids_for_container(
    records: Sequence[_CanonicalAtlasRecord],
    *,
    role: str,
    release: str | None = None,
    relation_bundle: str | None = None,
) -> frozenset[str]:
    return frozenset(
        record.identifier
        for record in records
        if record.role == role
        and (release is None or release in record.release_containers)
        and (relation_bundle is None or relation_bundle in record.relation_containers)
    )


def _validate_embedded_scope_records(
    records: Sequence[_CanonicalAtlasRecord],
    *,
    scope_record: Mapping[str, Any],
) -> tuple[
    tuple[AtlasReleaseSnapshot, ...],
    tuple[EmbeddedRelationAssertionBundle, ...],
]:
    snapshots = _snapshots_from_records(records)
    snapshots_by_release = {snapshot.release_id: snapshot for snapshot in snapshots}
    if len(snapshots_by_release) != len(snapshots):
        raise VocabularyAtlasError("atlas repeats a concept release")
    scope_releases = {
        cast(str, row["releaseId"]): row for row in cast(Sequence[Mapping[str, Any]], scope_record["releases"])
    }
    if set(snapshots_by_release) != set(scope_releases):
        raise VocabularyAtlasError("atlas concept releases differ from its exact scope")

    memberships: dict[str, frozenset[str]] = {}
    for release_id, snapshot in snapshots_by_release.items():
        scope_pin = {key: _plain(value) for key, value in scope_releases[release_id].items() if key != "atlasIndexRows"}
        if _plain(snapshot.release_pin) != scope_pin:
            raise VocabularyAtlasError("atlas concept release pin differs from its exact scope")
        memberships[release_id] = snapshot.member_ids
        expected_concepts = {_atlas_record_identifier(value) for value in snapshot.concept_records}
        if _record_ids_for_container(records, role="concept", release=release_id) != expected_concepts:
            raise VocabularyAtlasError("atlas release-scoped concept records differ from its snapshot")

        refs = {
            cast(str, value["rowId"]): cast(str, value["rowDigest"])
            for value in cast(
                Sequence[Mapping[str, Any]],
                scope_releases[release_id]["atlasIndexRows"],
            )
        }
        resolved_index_rows: list[Mapping[str, Any]] = []
        for record in records:
            if record.role != "releaseRecord" or release_id not in record.release_containers:
                continue
            row_id = record.record.get("rowId")
            if not isinstance(row_id, str) or row_id not in refs:
                continue
            row_digest = refs[row_id]
            if record.record.get("rowDigest") != row_digest:
                raise VocabularyAtlasError("atlas resolved index row differs from the scope reference")
            basis = {key: _plain(value) for key, value in record.record.items() if key not in {"rowId", "rowDigest"}}
            if binding.canonical_sha256(
                basis
            ) != row_digest or row_id != "urn:ref:atlas-index-row:" + row_digest.removeprefix("sha256:"):
                raise VocabularyAtlasError("atlas resolved index-row identity is stale")
            indexed_release = record.record.get("release")
            if (
                not isinstance(indexed_release, Mapping)
                or indexed_release.get("releaseId") != release_id
                or indexed_release.get("manifestDigest") != scope_pin.get("manifestDigest")
                or record.record.get("semanticRing") != scope_pin.get("semanticRing")
            ):
                raise VocabularyAtlasError("atlas resolved index row differs from its scope release")
            resolved_index_rows.append(record.record)
        if {cast(str, value["rowId"]) for value in resolved_index_rows} != set(refs):
            raise VocabularyAtlasError("atlas does not resolve every selected index-row fact")
        classifications = {
            (
                value.get("semanticRing"),
                value.get("atlasParticipation"),
                value.get("sourceModule"),
                value.get("resourceId"),
            )
            for value in resolved_index_rows
        }
        if len(classifications) != 1:
            raise VocabularyAtlasError("atlas selected index rows conflict on release classification")
        expected_release_records = {
            _atlas_record_identifier(value)
            for value in (
                *_snapshot_release_records(snapshot),
                *resolved_index_rows,
            )
        }
        if _record_ids_for_container(records, role="releaseRecord", release=release_id) != expected_release_records:
            raise VocabularyAtlasError("atlas release records differ from its snapshot and selected index rows")

    relation_records = [record for record in records if record.role == "relationBundle"]
    relations = tuple(
        EmbeddedRelationAssertionBundle.from_record(
            record.record,
            release_memberships={
                cast(str, pin["releaseId"]): memberships[cast(str, pin["releaseId"])]
                for pin in cast(Sequence[Mapping[str, Any]], record.record["releasePins"])
            },
        )
        for record in relation_records
    )
    relations_by_id = {relation.identifier: relation for relation in relations}
    if len(relations_by_id) != len(relations):
        raise VocabularyAtlasError("atlas repeats a relation bundle")
    scope_relations = {
        cast(str, row["id"]): row for row in cast(Sequence[Mapping[str, Any]], scope_record["relationBundles"])
    }
    if set(relations_by_id) != set(scope_relations):
        raise VocabularyAtlasError("atlas relation bundles differ from its exact scope")
    for bundle_id, relation in relations_by_id.items():
        pin = scope_relations[bundle_id]
        if pin.get("semanticRing") != relation.semantic_ring or pin.get("contentDigest") != relation.content_digest:
            raise VocabularyAtlasError("atlas relation bundle differs from its exact scope pin")
        expected_by_role = {
            "evidenceAssertion": {
                _atlas_record_identifier(value.as_record()) for value in relation.evidence_assertions
            },
            "mappingAssertion": {_atlas_record_identifier(value.as_record()) for value in relation.mapping_assertions},
            "machineProof": {_atlas_record_identifier(value) for value in relation.machine_proof_pins},
        }
        for role, expected in expected_by_role.items():
            if _record_ids_for_container(records, role=role, relation_bundle=bundle_id) != expected:
                raise VocabularyAtlasError(f"atlas {role} records differ from their relation bundle")
    return snapshots, relations


def _validate_manifest_v2(
    manifest: Mapping[str, Any],
    *,
    scope_payload: bytes,
    payload: bytes,
) -> tuple[tuple[AtlasReleaseSnapshot, ...], tuple[EmbeddedRelationAssertionBundle, ...]]:
    if set(manifest) != _MANIFEST_FIELDS_V2:
        raise VocabularyAtlasError("atlas manifest fields differ from 2.0")
    if (
        manifest.get("type") != "urn:ref:type:VocabularyAtlasManifest"
        or manifest.get("schemaVersion") != SCHEMA_VERSION
        or manifest.get("format") != FORMAT_ID
    ):
        raise VocabularyAtlasError("atlas manifest version or format differs")
    generation_digest = _require_digest(manifest.get("generationDigest"), "atlas generationDigest")
    asset_id = _require_iri(manifest.get("id"), "atlas id")
    if asset_id != "urn:ref:vocabulary-atlas:" + generation_digest.removeprefix("sha256:"):
        raise VocabularyAtlasError("atlas id differs from generationDigest")
    if manifest.get("canonicalPayloadDigest") != _manifest_digest(manifest):
        raise VocabularyAtlasError("atlas manifest canonicalPayloadDigest differs")
    if manifest.get("policies") != dict(_POLICIES):
        raise VocabularyAtlasError("atlas policies differ from 2.0")
    implementation = _validate_implementation_v2(manifest.get("implementation"))

    scope = _as_mapping(manifest.get("scope"), "atlas scope descriptor")
    if set(scope) != {
        "role",
        "path",
        "mediaType",
        "id",
        "contentDigest",
        "fileDigest",
        "byteLength",
    }:
        raise VocabularyAtlasError("atlas scope descriptor fields differ")
    if (
        scope.get("role") != "VocabularyAtlasScope"
        or scope.get("path") != SCOPE_FILE
        or scope.get("mediaType") != _SCOPE_MEDIA_TYPE
    ):
        raise VocabularyAtlasError("atlas scope descriptor differs")
    _require_iri(scope.get("id"), "atlas scope id")
    _require_digest(scope.get("contentDigest"), "atlas scope contentDigest")
    if scope.get("fileDigest") != _digest_bytes(scope_payload):
        raise VocabularyAtlasError("atlas scope file digest differs")
    if scope.get("byteLength") != len(scope_payload):
        raise VocabularyAtlasError("atlas scope byteLength differs")
    try:
        scope_record = _load_json_object(scope_payload, "atlas scope")
        if _canonical_bytes(scope_record) != scope_payload:
            raise VocabularyAtlasError("atlas scope bytes are not canonical")
        scope_record = validate_atlas_scope_record(scope_record)
    except AtlasScopeError as error:
        raise VocabularyAtlasError(str(error)) from error
    if scope.get("id") != scope_record.get("id") or scope.get("contentDigest") != scope_record.get("contentDigest"):
        raise VocabularyAtlasError("atlas scope identity differs from its file")

    generation_basis = {
        "format": FORMAT_ID,
        "scope": _plain(scope),
        "implementation": _plain(implementation),
        "policies": dict(_POLICIES),
    }
    if _digest_value(generation_basis) != generation_digest:
        raise VocabularyAtlasError("atlas generationDigest differs")

    graph_rows = _as_sequence(manifest.get("graphs"), "atlas graphs")
    expected_graphs = (
        ("releaseFacts", asset_id + ":release-facts", True),
        ("crossRelease", asset_id + ":cross-release", False),
    )
    if len(graph_rows) != len(expected_graphs):
        raise VocabularyAtlasError("atlas must declare exactly two named graphs")
    for position, (role, identifier, positive) in enumerate(expected_graphs):
        row = _as_mapping(graph_rows[position], f"atlas graphs[{position}]")
        if set(row) != {"role", "id", "quadCount"}:
            raise VocabularyAtlasError("atlas graph fields differ from 2.0")
        if row.get("role") != role or row.get("id") != identifier:
            raise VocabularyAtlasError("atlas graph role or id differs")
        _require_v2_count(row.get("quadCount"), f"atlas {role} quadCount", positive=positive)

    output = _as_mapping(manifest.get("output"), "atlas output")
    if set(output) != {"path", "mediaType", "digest", "byteLength", "quadCount"}:
        raise VocabularyAtlasError("atlas output fields differ from 2.0")
    if output.get("path") != ATLAS_FILE or output.get("mediaType") != "application/n-quads":
        raise VocabularyAtlasError("atlas output descriptor differs")
    if output.get("digest") != _digest_bytes(payload):
        raise VocabularyAtlasError("atlas output digest differs")
    if output.get("byteLength") != len(payload):
        raise VocabularyAtlasError("atlas output byteLength differs")
    _require_v2_count(output.get("quadCount"), "atlas output quadCount", positive=True)

    decoded = _decode_atlas_dataset(payload, asset_id=asset_id)
    records = decoded.records
    observed_role_counts = {
        count_field: sum(record.role == role for record in records) for role, count_field in _ROLE_COUNT_FIELD.items()
    }
    counts = _as_mapping(manifest.get("counts"), "atlas counts")
    if set(counts) != _COUNT_FIELDS_V2:
        raise VocabularyAtlasError("atlas count fields differ from 2.0")
    for field in _COUNT_FIELDS_V2:
        _require_v2_count(
            counts.get(field),
            f"atlas counts.{field}",
            positive=field in {"conceptReleases", "concepts", "releaseRecords"},
        )
    if dict(counts) != observed_role_counts:
        raise VocabularyAtlasError("atlas record counts differ")

    for position, (_, graph_id, _) in enumerate(expected_graphs):
        if cast(Mapping[str, Any], graph_rows[position]).get("quadCount") != decoded.graph_quad_count(graph_id):
            raise VocabularyAtlasError("atlas graph quadCount differs")
    if output.get("quadCount") != decoded.quad_count:
        raise VocabularyAtlasError("atlas output quadCount differs")

    snapshots, relations = _validate_embedded_scope_records(
        records,
        scope_record=scope_record,
    )
    expected_rings = _ring_summaries(
        records,
        snapshots=snapshots,
        relations=relations,
    )
    if manifest.get("rings") != expected_rings:
        raise VocabularyAtlasError("atlas ring summaries differ")
    return snapshots, relations


_ASSET_CONSTRUCTION_TOKEN_V2 = object()


@dataclass(frozen=True, slots=True, init=False)
class VocabularyAtlasAsset:
    """A file-only verified canonical Atlas 2.0 distribution."""

    payload: bytes
    scope_payload: bytes
    manifest: Mapping[str, Any]
    _verification_token: object

    def __init__(
        self,
        payload: bytes,
        scope_payload: bytes,
        manifest: Mapping[str, Any],
        *,
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _ASSET_CONSTRUCTION_TOKEN_V2:
            raise TypeError(
                "VocabularyAtlasAsset must come from build_vocabulary_atlas() or VocabularyAtlasAsset.open()"
            )
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "scope_payload", scope_payload)
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(self, "_verification_token", _ASSET_CONSTRUCTION_TOKEN_V2)

    @classmethod
    def _verified(
        cls,
        *,
        payload: bytes,
        scope_payload: bytes,
        manifest: Mapping[str, Any],
    ) -> Self:
        return cls(
            payload,
            scope_payload,
            manifest,
            _construction_token=_ASSET_CONSTRUCTION_TOKEN_V2,
        )

    def _require_verified(self) -> None:
        if (
            getattr(self, "_verification_token", None) is not _ASSET_CONSTRUCTION_TOKEN_V2
            or not isinstance(self.payload, bytes)
            or not isinstance(self.scope_payload, bytes)
            or not isinstance(self.manifest, Mapping)
        ):
            raise VocabularyAtlasError("atlas asset is not a verified 2.0 distribution")

    def manifest_bytes(self) -> bytes:
        self._require_verified()
        return _canonical_bytes(_plain(self.manifest))

    @property
    def manifest_digest(self) -> str:
        return _digest_bytes(self.manifest_bytes())

    @property
    def output_digest(self) -> str:
        self._require_verified()
        return _digest_bytes(self.payload)

    @property
    def scope_digest(self) -> str:
        self._require_verified()
        return _digest_bytes(self.scope_payload)

    def write(self, directory: Path | str) -> Path:
        self._require_verified()
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=False)
        (target / ATLAS_FILE).write_bytes(self.payload)
        (target / SCOPE_FILE).write_bytes(self.scope_payload)
        (target / MANIFEST_FILE).write_bytes(self.manifest_bytes())
        return target

    @classmethod
    def open(
        cls,
        directory: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> Self:
        """Verify all three files from one independently trusted manifest pin."""

        _, payloads = _read_distribution(directory)
        digest = _require_digest(expected_manifest_digest, "expected atlas manifest digest")
        manifest_payload = payloads[MANIFEST_FILE]
        if _digest_bytes(manifest_payload) != digest:
            raise VocabularyAtlasError("atlas external manifest digest differs")
        manifest = _load_json_object(manifest_payload, "atlas manifest")
        if _canonical_bytes(manifest) != manifest_payload:
            raise VocabularyAtlasError("atlas manifest bytes are not canonical")
        _validate_manifest_v2(
            manifest,
            scope_payload=payloads[SCOPE_FILE],
            payload=payloads[ATLAS_FILE],
        )
        return cls._verified(
            payload=payloads[ATLAS_FILE],
            scope_payload=payloads[SCOPE_FILE],
            manifest=cast(Mapping[str, Any], _freeze(manifest)),
        )

    @classmethod
    def reproduce_from_scope(
        cls,
        directory: Path | str,
        *,
        scope: PinnedVocabularyAtlasScope,
        expected_manifest_digest: str,
    ) -> Self:
        """Reopen the exact producer scope and rebuild all three files."""

        opened = cls.open(
            directory,
            expected_manifest_digest=expected_manifest_digest,
        )
        resolved = _resolve_atlas_scope(scope)
        if opened.scope_payload != resolved.payload:
            raise VocabularyAtlasError("atlas distribution scope differs from the exact producer scope")
        rebuilt = _build_resolved_atlas_v2(resolved)
        if (
            rebuilt.payload != opened.payload
            or rebuilt.scope_payload != opened.scope_payload
            or rebuilt.manifest != opened.manifest
        ):
            raise VocabularyAtlasError("atlas files do not reproduce from the exact pinned scope")
        return opened


def build_vocabulary_atlas(
    scope: PinnedVocabularyAtlasScope,
) -> VocabularyAtlasAsset:
    """Build Atlas 2.0 from one exact, index-bound, non-authorizing scope."""

    return _build_resolved_atlas_v2(_resolve_atlas_scope(scope))


__all__ = [
    "ATLAS",
    "ATLAS_FILE",
    "FORMAT_ID",
    "MANIFEST_FILE",
    "RKAF",
    "SCHEMA_VERSION",
    "SCOPE_FILE",
    "VocabularyAtlasAsset",
    "VocabularyAtlasError",
    "build_vocabulary_atlas",
    "closed_reference_release_digest",
]
