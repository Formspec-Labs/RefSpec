"""Sealed crosswalk evidence: mapping candidates and machine validation.

A ``CrosswalkBundle`` closes one release-crossing set of proposed concept
mappings (``MappingCandidate``), the sealed evidence and request/response
artifacts they cite (``CrosswalkArtifact``), and the independent machine
verdicts that qualify them (``MachineValidation``).  Qualification requires
two independent machines to agree on the same relation for the same sealed
question; ``CrosswalkBundle`` computes that agreement itself so no consumer
can drift from the gate that emitted it.

``PinnedManagedRelease`` and ``closed_reference_release_digest`` supply the
release-side primitives a crosswalk pipeline pins against: an exact managed
release manifest and read view, and a checkout-free digest of one closed
Rulespec ``ReferenceResourceRelease``.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol, cast

from rdflib import BNode, Graph, Namespace, URIRef
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
    _verified: bool = dataclass_field(default=False, init=False, repr=False, compare=False)
    _qualified_cache: Mapping[str, tuple[Mapping[str, Any], ...]] | None = dataclass_field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )
    _adjudicated_cache: Mapping[str, str] | None = dataclass_field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

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
        if self._verified:
            return
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
        object.__setattr__(self, "_verified", True)

    def qualified(self) -> dict[str, tuple[dict[str, Any], ...]]:
        """Return every supporting validation in each qualifying question.

        The returned validation set is the complete same-question set whose
        unanimous relation determined qualification, not only the first pair
        that demonstrated machine independence.
        """

        self.verify()
        if self._qualified_cache is None:
            record = self.to_dict()
            candidates = {item["id"]: item for item in record["mappingCandidates"]}
            validations = {item["id"]: item for item in record["machineValidations"]}
            cached = _qualified_candidates(candidates, validations)
            object.__setattr__(
                self,
                "_qualified_cache",
                cast(Mapping[str, tuple[Mapping[str, Any], ...]], _freeze(cached)),
            )
        return {
            candidate_id: tuple(cast(dict[str, Any], _plain(row)) for row in rows)
            for candidate_id, rows in cast(
                Mapping[str, tuple[Mapping[str, Any], ...]],
                self._qualified_cache,
            ).items()
        }

    def adjudicated_relations(self) -> dict[str, str]:
        """Every candidate's agreed relation IRI, adjudicated-``related`` included.

        Read through the same lattice the atlas builder uses, so a report that
        counts relations can never drift from the gate that emitted them.
        """

        self.verify()
        if self._adjudicated_cache is None:
            record = self.to_dict()
            candidates = {item["id"]: item for item in record["mappingCandidates"]}
            validations = {item["id"]: item for item in record["machineValidations"]}
            cached = {
                candidate_id: relation
                for candidate_id, (_, relation) in _independent_agreements(
                    candidates,
                    validations,
                ).items()
            }
            object.__setattr__(
                self,
                "_adjudicated_cache",
                MappingProxyType(cached),
            )
        return dict(cast(Mapping[str, str], self._adjudicated_cache))


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


__all__ = [
    "ATLAS",
    "CROSSWALK_MEDIA_TYPE",
    "RKAF",
    "AtlasReleaseFactsView",
    "CrosswalkArtifact",
    "CrosswalkBundle",
    "MachineValidation",
    "MappingCandidate",
    "PinnedManagedRelease",
    "VerifiedManagedReleaseSource",
    "VocabularyAtlasError",
    "closed_reference_release_digest",
]
