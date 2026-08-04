"""Path-backed machine evidence for shared relation assertions.

The existing crosswalk bundle closes candidates, sealed request/response
artifacts, and machine validations.  This adapter selects either one verified
review or the complete supporting validation set that passed the v2 gate.
Relation assertions pin the resulting proof record and never accept receipt
IRIs alone.

This adapter is intentionally subject-ring specific because CrosswalkBundle v2
only defines SKOS mapping relations.  Other rings can use the same relation
foundation after they supply proof adapters for their own relation semantics.

Signed proof is intentionally absent.  A future signed adapter must verify an
independently pinned authority policy before it may emit a signed proof kind.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from typing_extensions import Self

from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes, sha256_digest
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.semantic_foundation import (
    MACHINE_EVIDENCE_PROOF_VERSION,
    SUBJECT_BROAD_MATCH,
    SUBJECT_CLOSE_MATCH,
    SUBJECT_EXACT_MATCH,
    SUBJECT_NARROW_MATCH,
    SUBJECT_RELATED_MATCH,
    EvidenceAssertion,
    validate_machine_evidence_proof_pin,
)

from .model import CrosswalkBundle, VocabularyAtlasError

CROSSWALK_MACHINE_PROOF_VERSION = MACHINE_EVIDENCE_PROOF_VERSION
CROSSWALK_V2_QUALIFICATION_POLICY = (
    "https://refspec.org/policies/two-independent-machines-relation-agreement-v2"
)

MachineProofKind = Literal[
    "crosswalkV2IndependentValidations",
    "crosswalkV2SingleMachineReview",
]
MachineEvidenceClass = Literal["machineQualified", "machineReviewed"]

_VERDICT_RELATIONS = {
    "same": SUBJECT_EXACT_MATCH,
    "near_same": SUBJECT_CLOSE_MATCH,
    "target_is_broader": SUBJECT_BROAD_MATCH,
    "target_is_narrower": SUBJECT_NARROW_MATCH,
    "related": SUBJECT_RELATED_MATCH,
}


class CrosswalkMachineProofError(ValueError):
    """A selected machine proof is absent, stale, or not closed."""


def machine_evidence_class_for_proof_kind(value: object) -> MachineEvidenceClass:
    """Derive the evidence class from one verified Crosswalk v2 proof kind."""

    if value == "crosswalkV2IndependentValidations":
        return "machineQualified"
    if value == "crosswalkV2SingleMachineReview":
        return "machineReviewed"
    raise CrosswalkMachineProofError("crosswalk machine proof kind is unsupported")


def _require_iri(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CrosswalkMachineProofError(f"{label} must be non-empty trimmed text")
    issue = absolute_uri_issue(value)
    if issue == "missing-scheme":
        raise CrosswalkMachineProofError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise CrosswalkMachineProofError(f"{label} must not contain credentials")
    return value


def _require_digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise CrosswalkMachineProofError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _record_by_id(rows: object, identifier: str, label: str) -> Mapping[str, Any]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise CrosswalkMachineProofError(f"crosswalk {label} must be an array")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("id") == identifier]
    if len(matches) != 1:
        raise CrosswalkMachineProofError(f"crosswalk must contain the selected {label} exactly once")
    return matches[0]


@dataclass(frozen=True, slots=True)
class CrosswalkMachineProofFacts:
    """Facts reproduced from one exact crosswalk bundle."""

    proof_kind: MachineProofKind
    crosswalk_bundle_id: str
    crosswalk_bundle_digest: str
    crosswalk_file_digest: str
    candidate_id: str
    candidate_digest: str
    validation_ids: tuple[str, ...]
    validation_digests: tuple[str, ...]
    sealed_input_digest: str
    request_id: str
    request_digest: str
    source_concept: str
    target_concept: str
    source_release: str
    target_release: str
    relation: str

    def _basis(self) -> dict[str, Any]:
        result = {
            "type": "MachineEvidenceProof",
            "schemaVersion": CROSSWALK_MACHINE_PROOF_VERSION,
            "semanticRing": "subject",
            "evidenceClass": machine_evidence_class_for_proof_kind(self.proof_kind),
            "proofKind": self.proof_kind,
            "proofSource": {
                "type": "CrosswalkBundle",
                "id": self.crosswalk_bundle_id,
                "contentDigest": self.crosswalk_bundle_digest,
                "fileDigest": self.crosswalk_file_digest,
            },
            "candidate": {"id": self.candidate_id, "contentDigest": self.candidate_digest},
            "validations": [
                {"id": identifier, "contentDigest": digest}
                for identifier, digest in zip(self.validation_ids, self.validation_digests, strict=True)
            ],
            "proofDetails": {
                "adapter": "RefSpecCrosswalkV2",
                "sealedQuestion": {
                    "inputDigest": self.sealed_input_digest,
                    "request": {"id": self.request_id, "contentDigest": self.request_digest},
                },
            },
            "sourceConcept": self.source_concept,
            "targetConcept": self.target_concept,
            "sourceRelease": self.source_release,
            "targetRelease": self.target_release,
            "relation": self.relation,
        }
        if self.proof_kind == "crosswalkV2IndependentValidations":
            result["qualificationPolicy"] = CROSSWALK_V2_QUALIFICATION_POLICY
        return result

    @property
    def content_digest(self) -> str:
        return sha256_digest(canonical_json_bytes(self._basis()))

    @property
    def identifier(self) -> str:
        return "urn:ref:machine-evidence-proof:subject:" + self.content_digest.removeprefix("sha256:")

    def as_record(self) -> dict[str, Any]:
        return validate_machine_evidence_proof_pin(
            {**self._basis(), "id": self.identifier, "contentDigest": self.content_digest},
            semantic_ring="subject",
        )


@dataclass(frozen=True, slots=True)
class PinnedCrosswalkMachineProof:
    """One proof selection that is reproduced from exact path-backed bytes."""

    path: Path
    file_digest: str
    bundle_digest: str
    proof_kind: MachineProofKind
    candidate_id: str
    validation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        machine_evidence_class_for_proof_kind(self.proof_kind)
        object.__setattr__(self, "file_digest", _require_digest(self.file_digest, "crosswalk file digest"))
        object.__setattr__(self, "bundle_digest", _require_digest(self.bundle_digest, "crosswalk bundle digest"))
        object.__setattr__(self, "candidate_id", _require_iri(self.candidate_id, "crosswalk candidate id"))
        validations = tuple(sorted(_require_iri(value, "crosswalk validation id") for value in self.validation_ids))
        if len(validations) != len(set(validations)):
            raise CrosswalkMachineProofError("crosswalk validation ids must be unique")
        if self.proof_kind == "crosswalkV2IndependentValidations" and len(validations) < 2:
            raise CrosswalkMachineProofError(
                "crosswalkV2IndependentValidations requires at least two selected validations"
            )
        if self.proof_kind == "crosswalkV2SingleMachineReview" and len(validations) != 1:
            raise CrosswalkMachineProofError(
                "crosswalkV2SingleMachineReview requires exactly one selected validation"
            )
        object.__setattr__(self, "validation_ids", validations)
        candidate = Path(self.path)
        if candidate.is_symlink():
            raise CrosswalkMachineProofError("crosswalk proof path must not be a symlink")
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            raise CrosswalkMachineProofError("crosswalk proof path does not exist") from error
        if not resolved.is_file():
            raise CrosswalkMachineProofError("crosswalk proof path must be a regular file")
        object.__setattr__(self, "path", resolved)

    @classmethod
    def qualified(
        cls,
        path: Path | str,
        *,
        expected_file_digest: str,
        expected_bundle_digest: str,
        candidate_id: str,
    ) -> Self:
        """Select the complete support set that qualified one v2 candidate."""

        selected_candidate = _require_iri(candidate_id, "crosswalk candidate id")
        bundle = cls._open_bundle(path, expected_file_digest, expected_bundle_digest)
        qualified = bundle.qualified().get(selected_candidate)
        if qualified is None:
            raise CrosswalkMachineProofError("crosswalk candidate did not pass independent qualification")
        selected = cls(
            path=Path(path),
            file_digest=expected_file_digest,
            bundle_digest=expected_bundle_digest,
            proof_kind="crosswalkV2IndependentValidations",
            candidate_id=selected_candidate,
            validation_ids=tuple(str(row["id"]) for row in qualified),
        )
        selected.verified_facts()
        return selected

    @classmethod
    def reviewed(
        cls,
        path: Path | str,
        *,
        expected_file_digest: str,
        expected_bundle_digest: str,
        candidate_id: str,
        validation_id: str,
    ) -> Self:
        """Select one deterministic supporting v2 review for operator adoption."""

        selected = cls(
            path=Path(path),
            file_digest=expected_file_digest,
            bundle_digest=expected_bundle_digest,
            proof_kind="crosswalkV2SingleMachineReview",
            candidate_id=candidate_id,
            validation_ids=(validation_id,),
        )
        selected.verified_facts()
        return selected

    @staticmethod
    def _open_bundle(path: Path | str, file_digest: str, bundle_digest: str) -> CrosswalkBundle:
        try:
            return CrosswalkBundle.open(
                path,
                expected_file_digest=_require_digest(file_digest, "crosswalk file digest"),
                expected_bundle_digest=_require_digest(bundle_digest, "crosswalk bundle digest"),
            )
        except VocabularyAtlasError as error:
            raise CrosswalkMachineProofError(str(error)) from error

    def verified_facts(self) -> CrosswalkMachineProofFacts:
        """Reopen the bytes and reproduce the same candidate, receipts, and relation."""

        bundle = self._open_bundle(self.path, self.file_digest, self.bundle_digest)
        record = bundle.to_dict()
        if record.get("schemaVersion") != "2.0":
            raise CrosswalkMachineProofError("shared machine proof requires a relation-adjudicating v2 bundle")
        candidate = _record_by_id(record.get("mappingCandidates"), self.candidate_id, "candidate")
        validations = tuple(
            _record_by_id(record.get("machineValidations"), identifier, "validation")
            for identifier in self.validation_ids
        )
        if self.proof_kind == "crosswalkV2IndependentValidations":
            qualified = bundle.qualified().get(self.candidate_id)
            if qualified is None or tuple(sorted(str(row["id"]) for row in qualified)) != self.validation_ids:
                raise CrosswalkMachineProofError(
                    "selected validations are not the candidate's complete qualifying support set"
                )
            relation = bundle.adjudicated_relations().get(self.candidate_id)
            if relation is None or relation == SUBJECT_RELATED_MATCH:
                raise CrosswalkMachineProofError("qualified crosswalk proof has no emitted relation")
        else:
            validation = validations[0]
            candidate_reference = validation.get("candidate")
            if (
                not isinstance(candidate_reference, Mapping)
                or candidate_reference.get("id") != self.candidate_id
                or candidate_reference.get("digest") != candidate.get("canonicalPayloadDigest")
                or validation.get("outcome") != "supports"
                or validation.get("deterministicChecksPassed") is not True
            ):
                raise CrosswalkMachineProofError("selected validation is not a deterministic supporting review")
            verdict = validation.get("verdictRelation")
            relation = _VERDICT_RELATIONS.get(verdict)
            if relation is None:
                raise CrosswalkMachineProofError("selected validation has no supported relation verdict")
        question_keys: set[tuple[str, str, str]] = set()
        for validation in validations:
            request = validation.get("requestArtifact")
            if not isinstance(request, Mapping):
                raise CrosswalkMachineProofError("selected validation has no sealed request")
            question_keys.add(
                (
                    _require_digest(validation.get("sealedInputDigest"), "crosswalk sealed input digest"),
                    _require_iri(request.get("id"), "crosswalk request id"),
                    _require_digest(request.get("digest"), "crosswalk request digest"),
                )
            )
        if len(question_keys) != 1:
            raise CrosswalkMachineProofError("selected validations do not answer one sealed question")
        sealed_input_digest, request_id, request_digest = question_keys.pop()
        facts = CrosswalkMachineProofFacts(
            proof_kind=self.proof_kind,
            crosswalk_bundle_id=_require_iri(bundle.identifier, "crosswalk bundle id"),
            crosswalk_bundle_digest=_require_digest(bundle.digest, "crosswalk bundle digest"),
            crosswalk_file_digest=self.file_digest,
            candidate_id=self.candidate_id,
            candidate_digest=_require_digest(candidate.get("canonicalPayloadDigest"), "crosswalk candidate digest"),
            validation_ids=self.validation_ids,
            validation_digests=tuple(
                _require_digest(row.get("canonicalPayloadDigest"), "crosswalk validation digest") for row in validations
            ),
            sealed_input_digest=sealed_input_digest,
            request_id=request_id,
            request_digest=request_digest,
            source_concept=_require_iri(candidate.get("sourceMember"), "crosswalk source member"),
            target_concept=_require_iri(candidate.get("targetMember"), "crosswalk target member"),
            source_release=_require_iri(candidate.get("sourceRelease"), "crosswalk source release"),
            target_release=_require_iri(candidate.get("targetRelease"), "crosswalk target release"),
            relation=_require_iri(relation, "crosswalk adjudicated relation"),
        )
        if sha256_digest(self.path.read_bytes()) != self.file_digest:
            raise CrosswalkMachineProofError("crosswalk proof changed while verifying")
        return facts

    @property
    def identifier(self) -> str:
        return self.verified_facts().identifier

    def pin(self) -> dict[str, Any]:
        return self.verified_facts().as_record()


def build_machine_evidence_from_crosswalk_proof(
    proof: PinnedCrosswalkMachineProof,
    *,
    asserted_by: str,
    asserted_at: str,
    evidence: Sequence[str] = (),
) -> EvidenceAssertion:
    """Build an evidence assertion whose complete machine scope is reproduced."""

    if not isinstance(proof, PinnedCrosswalkMachineProof):
        raise CrosswalkMachineProofError("machine evidence requires a pinned crosswalk proof")
    facts = proof.verified_facts()
    supporting = tuple(sorted({facts.identifier, *evidence}))
    common: dict[str, Any] = {
        "semantic_ring": "subject",
        "basis": "statisticalInference",
        "asserted_by": asserted_by,
        "asserted_at": asserted_at,
        "evidence": supporting,
        "candidate": facts.candidate_id,
        "machine_proof": facts.identifier,
        "source_concept": facts.source_concept,
        "target_concept": facts.target_concept,
        "source_release": facts.source_release,
        "target_release": facts.target_release,
        "relation": facts.relation,
        "validation_receipts": facts.validation_ids,
    }
    return EvidenceAssertion(
        evidence_class=machine_evidence_class_for_proof_kind(facts.proof_kind),
        **common,
    )


__all__ = [
    "CROSSWALK_MACHINE_PROOF_VERSION",
    "CROSSWALK_V2_QUALIFICATION_POLICY",
    "CrosswalkMachineProofError",
    "CrosswalkMachineProofFacts",
    "MachineEvidenceClass",
    "PinnedCrosswalkMachineProof",
    "build_machine_evidence_from_crosswalk_proof",
    "machine_evidence_class_for_proof_kind",
]
