"""Canonical operational records published in a RefSpec vocabulary release."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Self

from .canonical import seal_vocabulary_release, stable_record


ResolutionStatus = Literal[
    "officialTerm",
    "recognizedVariant",
    "sourceLocalOpenTerm",
    "unresolved",
]
ExecutionStatus = Literal["completed", "failed"]
CheckOutcome = Literal["pass", "fail", "abstain", "not_applicable"]
Recommendation = Literal["supports", "flags", "abstains"]
AggregateResult = Literal[
    "usable_for_search",
    "usable_with_nonblocking_limits",
    "deferred",
    "failed",
]


@dataclass(frozen=True, slots=True)
class RecordReference:
    """An exact identifier-and-digest reference to an immutable record."""

    record_id: str
    record_digest: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.record_id, "digest": self.record_digest}

    @classmethod
    def from_record(
        cls,
        record: Mapping[str, Any],
        *,
        id_field: str,
        digest_field: str,
    ) -> Self:
        return cls(
            record_id=str(record[id_field]),
            record_digest=str(record[digest_field]),
        )


@dataclass(frozen=True, slots=True)
class TargetConceptRelease:
    """One concept in one exact complete Rulespec reference release."""

    concept_id: str
    reference_resource_release_id: str
    reference_resource_release_digest: str

    def to_dict(self) -> dict[str, str]:
        return {
            "concept_id": self.concept_id,
            "reference_resource_release_id": self.reference_resource_release_id,
            "reference_resource_release_digest": (
                self.reference_resource_release_digest
            ),
        }


@dataclass(frozen=True, slots=True)
class SourceTermKey:
    """The complete source-field identity used for a term resolution."""

    key_id: str
    key_digest: str
    source_system_and_profile_version: str
    observation_kind: str
    source_native_path: str
    raw_value: str
    language: str
    source_context_discriminator: str | None = None

    @classmethod
    def create(
        cls,
        *,
        source_system_and_profile_version: str,
        observation_kind: str,
        source_native_path: str,
        raw_value: str,
        language: str,
        source_context_discriminator: str | None = None,
    ) -> Self:
        payload: dict[str, Any] = {
            "source_system_and_profile_version": (source_system_and_profile_version),
            "observation_kind": observation_kind,
            "source_native_path": source_native_path,
            "raw_value": raw_value,
            "language": language,
        }
        if source_context_discriminator is not None:
            payload["source_context_discriminator"] = source_context_discriminator
        sealed = stable_record(
            payload,
            id_field="key_id",
            digest_field="key_digest",
            id_prefix="urn:refspec:source-term-key:",
        )
        return cls(**sealed)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "key_id": self.key_id,
            "key_digest": self.key_digest,
            "source_system_and_profile_version": (
                self.source_system_and_profile_version
            ),
            "observation_kind": self.observation_kind,
            "source_native_path": self.source_native_path,
            "raw_value": self.raw_value,
            "language": self.language,
        }
        if self.source_context_discriminator is not None:
            result["source_context_discriminator"] = self.source_context_discriminator
        return result

    def reference(self) -> RecordReference:
        return RecordReference(self.key_id, self.key_digest)


@dataclass(frozen=True, slots=True)
class SourceTermResolution:
    """One explicit resolution decision for one exact source-term key."""

    resolution_id: str
    resolution_digest: str
    source_term_key_ref: RecordReference
    resolution_status: ResolutionStatus
    policy_and_version: str
    reason: str
    target_concept_and_release: TargetConceptRelease | None
    evidence_refs: tuple[RecordReference, ...]
    baseline_validation_receipt_ref: RecordReference
    optional_review_refs: tuple[RecordReference, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        source_term_key_ref: RecordReference,
        resolution_status: ResolutionStatus,
        policy_and_version: str,
        reason: str,
        target_concept_and_release: TargetConceptRelease | None,
        evidence_refs: tuple[RecordReference, ...],
        baseline_validation_receipt_ref: RecordReference,
        optional_review_refs: tuple[RecordReference, ...] = (),
    ) -> Self:
        targeted = resolution_status in {"officialTerm", "recognizedVariant"}
        if targeted != (target_concept_and_release is not None):
            raise ValueError(f"{resolution_status} has invalid target cardinality")
        if not policy_and_version or not reason:
            raise ValueError("resolution policy and reason are required")
        payload: dict[str, Any] = {
            "source_term_key_ref": source_term_key_ref.to_dict(),
            "resolution_status": resolution_status,
            "policy_and_version": policy_and_version,
            "reason": reason,
            "evidence_refs": [item.to_dict() for item in evidence_refs],
            "baseline_validation_receipt_ref": (
                baseline_validation_receipt_ref.to_dict()
            ),
            "optional_review_refs": [item.to_dict() for item in optional_review_refs],
        }
        if target_concept_and_release is not None:
            payload["target_concept_and_release"] = target_concept_and_release.to_dict()
        sealed = stable_record(
            payload,
            id_field="resolution_id",
            digest_field="resolution_digest",
            id_prefix="urn:refspec:source-term-resolution:",
        )
        return cls(
            resolution_id=sealed["resolution_id"],
            resolution_digest=sealed["resolution_digest"],
            source_term_key_ref=source_term_key_ref,
            resolution_status=resolution_status,
            policy_and_version=policy_and_version,
            reason=reason,
            target_concept_and_release=target_concept_and_release,
            evidence_refs=evidence_refs,
            baseline_validation_receipt_ref=baseline_validation_receipt_ref,
            optional_review_refs=optional_review_refs,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "resolution_id": self.resolution_id,
            "resolution_digest": self.resolution_digest,
            "source_term_key_ref": self.source_term_key_ref.to_dict(),
            "resolution_status": self.resolution_status,
            "policy_and_version": self.policy_and_version,
            "reason": self.reason,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "baseline_validation_receipt_ref": (
                self.baseline_validation_receipt_ref.to_dict()
            ),
            "optional_review_refs": [
                item.to_dict() for item in self.optional_review_refs
            ],
        }
        if self.target_concept_and_release is not None:
            payload["target_concept_and_release"] = (
                self.target_concept_and_release.to_dict()
            )
        return payload


def create_support_record(
    record_type: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a typed immutable record referenced by validation receipts."""

    if not record_type:
        raise ValueError("record_type is required")
    return stable_record(
        {"record_type": record_type, "payload": deepcopy(dict(payload))},
        id_field="record_id",
        digest_field="record_digest",
        id_prefix="urn:refspec:support-record:",
    )


@dataclass(frozen=True, slots=True)
class AgentValidationReceipt:
    """One immutable independent validator attempt."""

    _record: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        attempt_id: str,
        owner: str,
        target_ref_and_digest: RecordReference,
        protocol_and_version: str,
        input_manifest_ref_and_digest: RecordReference,
        validator_actor_ref: str,
        validator_kind: Literal["aiModel", "aiAgent"],
        independence_group: str,
        provider_and_model_id: str,
        request_contract_ref_and_digest: RecordReference,
        execution_status: ExecutionStatus,
        check_outcomes: tuple[Mapping[str, Any], ...],
        started_at: str,
        completed_at: str,
        response_artifact_ref_and_digest: RecordReference | None = None,
        failure_reason: str | None = None,
        failure_artifact_ref_and_digest: RecordReference | None = None,
        overall_recommendation: Recommendation | None = None,
        advisory_attestation_ref: RecordReference | None = None,
    ) -> Self:
        if execution_status == "completed":
            if response_artifact_ref_and_digest is None:
                raise ValueError("a completed attempt requires a response")
            if overall_recommendation is None:
                raise ValueError(
                    "a completed attempt requires an overall recommendation"
                )
            if failure_reason is not None or failure_artifact_ref_and_digest:
                raise ValueError("a completed attempt cannot contain failure data")
        elif execution_status == "failed":
            if not failure_reason:
                raise ValueError("a failed attempt requires a failure reason")
            if overall_recommendation is not None:
                raise ValueError("a failed attempt forbids a recommendation")
            if response_artifact_ref_and_digest is not None:
                raise ValueError("a failed attempt cannot contain a response")
        else:
            raise ValueError("unknown execution status")
        payload: dict[str, Any] = {
            "attempt_id": attempt_id,
            "owner": owner,
            "target_ref_and_digest": target_ref_and_digest.to_dict(),
            "protocol_and_version": protocol_and_version,
            "input_manifest_ref_and_digest": (input_manifest_ref_and_digest.to_dict()),
            "validator_actor_ref": validator_actor_ref,
            "validator_kind": validator_kind,
            "independence_group": independence_group,
            "provider_and_model_id": provider_and_model_id,
            "request_contract_ref_and_digest": (
                request_contract_ref_and_digest.to_dict()
            ),
            "execution_status": execution_status,
            "check_outcomes": deepcopy(list(check_outcomes)),
            "started_at": started_at,
            "completed_at": completed_at,
        }
        optional: dict[str, Any] = {
            "response_artifact_ref_and_digest": (
                response_artifact_ref_and_digest.to_dict()
                if response_artifact_ref_and_digest
                else None
            ),
            "failure_reason": failure_reason,
            "failure_artifact_ref_and_digest": (
                failure_artifact_ref_and_digest.to_dict()
                if failure_artifact_ref_and_digest
                else None
            ),
            "overall_recommendation": overall_recommendation,
            "advisory_attestation_ref": (
                advisory_attestation_ref.to_dict() if advisory_attestation_ref else None
            ),
        }
        payload.update(
            {key: value for key, value in optional.items() if value is not None}
        )
        sealed = stable_record(
            payload,
            id_field="receipt_id",
            digest_field="receipt_digest",
            id_prefix="urn:refspec:agent-validation-receipt:",
        )
        return cls(deepcopy(sealed))

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(dict(self._record))

    def reference(self) -> RecordReference:
        return RecordReference(
            str(self._record["receipt_id"]),
            str(self._record["receipt_digest"]),
        )


@dataclass(frozen=True, slots=True)
class BaselineValidationReceipt:
    """Deterministic reduction of checks and independent agent attempts."""

    _record: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        owner: str,
        target_profile_and_release_ref: RecordReference,
        sample_manifest_ref_and_digest: RecordReference,
        rubric_and_version: str,
        aggregation_policy_and_version: str,
        deterministic_check_receipt_refs: tuple[RecordReference, ...],
        deterministic_check_outcomes: tuple[Mapping[str, Any], ...],
        agent_validation_receipt_refs: tuple[RecordReference, ...],
        aggregate_result: AggregateResult,
        disagreements_and_flags: tuple[str, ...],
        known_limitations: tuple[str, ...],
        evaluated_at: str,
    ) -> Self:
        payload = {
            "owner": owner,
            "target_profile_and_release_ref": (
                target_profile_and_release_ref.to_dict()
            ),
            "sample_manifest_ref_and_digest": (
                sample_manifest_ref_and_digest.to_dict()
            ),
            "rubric_and_version": rubric_and_version,
            "aggregation_policy_and_version": (aggregation_policy_and_version),
            "deterministic_check_receipt_refs": [
                item.to_dict() for item in deterministic_check_receipt_refs
            ],
            "deterministic_check_outcomes": deepcopy(
                list(deterministic_check_outcomes)
            ),
            "agent_validation_receipt_refs": [
                item.to_dict() for item in agent_validation_receipt_refs
            ],
            "aggregate_result": aggregate_result,
            "disagreements_and_flags": list(disagreements_and_flags),
            "known_limitations": list(known_limitations),
            "evaluated_at": evaluated_at,
        }
        sealed = stable_record(
            payload,
            id_field="receipt_id",
            digest_field="receipt_digest",
            id_prefix="urn:refspec:baseline-validation-receipt:",
        )
        return cls(deepcopy(sealed))

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(dict(self._record))

    def reference(self) -> RecordReference:
        return RecordReference(
            str(self._record["receipt_id"]),
            str(self._record["receipt_digest"]),
        )


@dataclass(frozen=True, slots=True)
class VocabularyCoverage:
    """The declared source and managed-release coverage for a vocabulary."""

    _record: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        source_complete_concept_count: int,
        published_concept_count: int,
        resolution_key_count: int,
        resolution_counts_by_status: Mapping[str, int],
        included_source_locators: tuple[Mapping[str, Any], ...],
        excluded_scope: tuple[str, ...],
    ) -> Self:
        payload = {
            "source_complete_concept_count": source_complete_concept_count,
            "published_concept_count": published_concept_count,
            "resolution_key_count": resolution_key_count,
            "resolution_counts_by_status": dict(resolution_counts_by_status),
            "included_source_locators": deepcopy(list(included_source_locators)),
            "excluded_scope": list(excluded_scope),
        }
        sealed = stable_record(
            payload,
            id_field="coverage_id",
            digest_field="coverage_digest",
            id_prefix="urn:refspec:vocabulary-coverage:",
        )
        return cls(deepcopy(sealed))

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(dict(self._record))


@dataclass(frozen=True, slots=True)
class VocabularyRelease:
    """A canonical RefSpec vocabulary release manifest."""

    _record: Mapping[str, Any]

    @classmethod
    def create(cls, payload: Mapping[str, Any]) -> Self:
        return cls(deepcopy(seal_vocabulary_release(payload)))

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(dict(self._record))
