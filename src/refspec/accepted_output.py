"""Authorize one accepted assignment through an exact RefSpec evidence chain.

Candidate lookup deliberately remains separate.  This module is the only
reference-runtime path that turns a managed-release candidate into an
accepted-output authorization.  It does not rank candidates or infer policy:
the caller supplies the exact selected member, permission row, configuration,
evaluation, deployments, and gate receipt.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

from refspec import binding
from refspec.managed_release import ManagedReleaseMember, ManagedReleaseView

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_GATE_IMPLEMENTATION_ID = (
    "https://refspec.org/reference-runtime/release-graph-gate"
)
_RECEIPT_TYPE = "urn:ref:type:ReleaseGraphValidationReceipt"
_OUTPUT_PROFILE_TYPE = "urn:ref:type:OutputProfile"
_REGISTRY_DEPLOYMENT_TYPE = "urn:ref:type:RegistryDeploymentDecision"
_CONFIGURATION_TYPE = "urn:ref:type:EnrichmentConfiguration"
_EVALUATION_TYPE = "urn:ref:type:EnrichmentEvaluationResult"
_ENRICHMENT_DEPLOYMENT_TYPE = "urn:ref:type:EnrichmentDeploymentDecision"
_BEHAVIOR_CONTRACT = "rkaf:UsageEligibilityReducer"


class AcceptedOutputAuthorizationError(ValueError):
    """The supplied evidence does not authorize an accepted assignment."""


@dataclass(frozen=True, slots=True)
class AcceptedOutputAuthorization:
    """The immutable identities resolved for one accepted assignment."""

    member: ManagedReleaseMember
    permission: Mapping[str, Any]
    expression_corpus_snapshot: Mapping[str, str]
    lookup_index_manifest: Mapping[str, str]
    registry_deployment: Mapping[str, str]
    configuration: Mapping[str, str]
    evaluation_result: Mapping[str, str]
    enrichment_deployment: Mapping[str, str]
    validation_receipt: Mapping[str, str]
    usage_eligibility: str = "acceptedOutput"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_plain(item) for item in value]
    return value


def _exact_reference(
    record: Mapping[str, Any],
    *,
    versioned: bool = False,
) -> Mapping[str, str]:
    digest_field = binding.digest_field(dict(record))
    keys = {"id", "digest", *(("version",) if versioned else ())}
    reference: dict[str, str] = {}
    for key in keys:
        source_key = digest_field if key == "digest" else key
        value = record.get(source_key)
        if not isinstance(value, str) or not value:
            raise AcceptedOutputAuthorizationError(
                f"{record.get('id', '<unknown>')} lacks exact {source_key}"
            )
        reference[key] = value
    return MappingProxyType(reference)


def _require_digest_reference(
    value: Mapping[str, Any],
    label: str,
    *,
    versioned: bool = False,
) -> dict[str, str]:
    required = {"id", "digest", *(("version",) if versioned else ())}
    if set(value) != required:
        raise AcceptedOutputAuthorizationError(
            f"{label} must contain exactly {sorted(required)!r}"
        )
    identifier = value.get("id")
    digest = value.get("digest")
    if not isinstance(identifier, str) or not identifier:
        raise AcceptedOutputAuthorizationError(f"{label}.id is required")
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise AcceptedOutputAuthorizationError(
            f"{label}.digest must be sha256:<64 lowercase hex>"
        )
    result = {"id": identifier, "digest": digest}
    if versioned:
        version = value.get("version")
        if not isinstance(version, str) or not version:
            raise AcceptedOutputAuthorizationError(f"{label}.version is required")
        result["version"] = version
    return result


def _records_by_id(
    records: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    copied: list[dict[str, Any]] = []
    indexed: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(records):
        if not isinstance(raw, Mapping):
            raise AcceptedOutputAuthorizationError(
                f"ref_records[{index}] must be an object"
            )
        record = cast(dict[str, Any], copy.deepcopy(dict(raw)))
        identifier = record.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise AcceptedOutputAuthorizationError(
                f"ref_records[{index}].id is required"
            )
        if identifier in indexed:
            raise AcceptedOutputAuthorizationError(
                f"ref_records repeats identifier {identifier!r}"
            )
        copied.append(record)
        indexed[identifier] = record
    return copied, indexed


def _require_record(
    records: Mapping[str, dict[str, Any]],
    identifier: str,
    record_type: str,
    label: str,
) -> dict[str, Any]:
    record = records.get(identifier)
    if record is None:
        raise AcceptedOutputAuthorizationError(
            f"{label} {identifier!r} is absent from the validated REF records"
        )
    if record.get("type") != record_type:
        raise AcceptedOutputAuthorizationError(
            f"{label} {identifier!r} has type {record.get('type')!r}, not {record_type!r}"
        )
    return record


def _require_exact_record_reference(
    reference: object,
    record: Mapping[str, Any],
    label: str,
) -> None:
    if not isinstance(reference, Mapping) or not binding.references_record(
        dict(reference),
        dict(record),
    ):
        raise AcceptedOutputAuthorizationError(
            f"{label} does not resolve to the exact record {record.get('id')!r}"
        )


def _require_selected(record: Mapping[str, Any], label: str) -> None:
    if record.get("selectionState") != "selected":
        raise AcceptedOutputAuthorizationError(f"{label} is not selected")


def _require_receipt_authorization(
    receipt: Mapping[str, Any],
    decision: Mapping[str, Any],
    label: str,
) -> None:
    decision_ref = dict(_exact_reference(decision))
    evaluations = receipt.get("authorizationEvaluations")
    if not isinstance(evaluations, list):
        raise AcceptedOutputAuthorizationError(
            "ReleaseGraphValidationReceipt lacks authorizationEvaluations"
        )
    matches = [
        row
        for row in evaluations
        if isinstance(row, Mapping)
        and row.get("governanceRecord") == decision_ref
    ]
    if len(matches) != 1:
        raise AcceptedOutputAuthorizationError(
            f"ReleaseGraphValidationReceipt must contain exactly one "
            f"authorizationEvaluation for {label}"
        )
    evaluation = matches[0]
    if (
        evaluation.get("behaviorContract") != _BEHAVIOR_CONTRACT
        or evaluation.get("minimumUsageEligibility")
        != "rkaf:localOperationalUse"
        or evaluation.get("result") != "pass"
    ):
        raise AcceptedOutputAuthorizationError(
            f"{label} lacks a passing Rulespec usage-eligibility evaluation"
        )
    if evaluation.get("inputGraph") != receipt.get("rulespecGraph"):
        raise AcceptedOutputAuthorizationError(
            f"{label} authorization was evaluated against a different Rulespec graph"
        )
    if evaluation.get("runtime") != receipt.get("rulespecBehaviorRuntime"):
        raise AcceptedOutputAuthorizationError(
            f"{label} authorization was evaluated by a different Rulespec runtime"
        )


def authorize_accepted_assignment(
    *,
    managed_release: ManagedReleaseView,
    member_iri: str,
    facet: str,
    assignment_role: str,
    accepted_output_permission: Mapping[str, Any],
    expression_corpus_snapshot: Mapping[str, Any],
    lookup_index_manifest: Mapping[str, Any],
    ref_records: Sequence[Mapping[str, Any]],
    output_profile_id: str,
    registry_deployment_id: str,
    configuration_id: str,
    evaluation_result_id: str,
    enrichment_deployment_id: str,
    release_graph_validation_receipt: Mapping[str, Any],
) -> AcceptedOutputAuthorization:
    """Resolve and authorize one exact managed-release member for output.

    The complete linked REF record set is validated before any chain-specific
    checks run.  This keeps structural and shared behavioral policy in the
    existing RefSpec binding validator while this function enforces the
    accepted-output joins that span the managed release, physical lookup
    index, deployments, configuration, evaluation, and Rulespec behavior
    receipt.
    """

    if not isinstance(managed_release, ManagedReleaseView):
        raise AcceptedOutputAuthorizationError(
            "managed_release must be an opened refspec.ManagedReleaseView"
        )
    member = managed_release.lookup_member(member_iri)
    if member is None:
        raise AcceptedOutputAuthorizationError(
            f"{member_iri!r} is not an exact managed-release member"
        )

    actual_expression_corpus = _require_digest_reference(
        expression_corpus_snapshot,
        "expression_corpus_snapshot",
    )
    if actual_expression_corpus != dict(managed_release.expression_corpus_snapshot):
        raise AcceptedOutputAuthorizationError(
            "expression corpus does not match the opened managed release"
        )
    actual_lookup_index = _require_digest_reference(
        lookup_index_manifest,
        "lookup_index_manifest",
    )
    if actual_lookup_index["id"] == actual_expression_corpus["id"]:
        raise AcceptedOutputAuthorizationError(
            "lookup index must not reuse the expression-corpus identity"
        )

    copied_records, records = _records_by_id(ref_records)
    output_profile = _require_record(
        records,
        output_profile_id,
        _OUTPUT_PROFILE_TYPE,
        "OutputProfile",
    )
    registry_deployment = _require_record(
        records,
        registry_deployment_id,
        _REGISTRY_DEPLOYMENT_TYPE,
        "RegistryDeploymentDecision",
    )
    configuration = _require_record(
        records,
        configuration_id,
        _CONFIGURATION_TYPE,
        "EnrichmentConfiguration",
    )
    evaluation = _require_record(
        records,
        evaluation_result_id,
        _EVALUATION_TYPE,
        "EnrichmentEvaluationResult",
    )
    enrichment_deployment = _require_record(
        records,
        enrichment_deployment_id,
        _ENRICHMENT_DEPLOYMENT_TYPE,
        "EnrichmentDeploymentDecision",
    )

    receipt = cast(
        dict[str, Any],
        _plain(release_graph_validation_receipt),
    )
    trusted_receipt = cast(
        dict[str, Any],
        _plain(managed_release.release_graph_validation_receipt),
    )
    if (
        receipt.get("canonicalPayloadDigest")
        != trusted_receipt.get("canonicalPayloadDigest")
        or receipt != trusted_receipt
    ):
        raise AcceptedOutputAuthorizationError(
            "release_graph_validation_receipt is not the exact receipt "
            "verified when the managed release was opened"
        )
    diagnostics = binding.validate([*copied_records, receipt])
    if diagnostics:
        raise AcceptedOutputAuthorizationError(
            "accepted-output evidence fails REF JSON Binding 1.0: "
            + " | ".join(item.render() for item in diagnostics)
        )

    supplied_permission = copy.deepcopy(dict(accepted_output_permission))
    matching_permissions = [
        row
        for row in output_profile.get("releasePermissions", [])
        if row == supplied_permission
    ]
    if len(matching_permissions) != 1:
        raise AcceptedOutputAuthorizationError(
            "accepted_output_permission must match exactly one complete "
            "OutputProfile releasePermissions row"
        )
    if (
        supplied_permission.get("facet") != facet
        or supplied_permission.get("assignmentRole") != assignment_role
        or supplied_permission.get("candidateUse") is not True
        or supplied_permission.get("acceptedOutputUse") is not True
    ):
        raise AcceptedOutputAuthorizationError(
            "permission row does not authorize this facet, role, and accepted output"
        )

    _require_selected(registry_deployment, "RegistryDeploymentDecision")
    _require_selected(enrichment_deployment, "EnrichmentDeploymentDecision")
    _require_exact_record_reference(
        registry_deployment.get("outputProfile"),
        output_profile,
        "registry deployment OutputProfile",
    )
    _require_exact_record_reference(
        configuration.get("outputProfile"),
        output_profile,
        "configuration OutputProfile",
    )
    _require_exact_record_reference(
        enrichment_deployment.get("outputProfile"),
        output_profile,
        "enrichment deployment OutputProfile",
    )

    release_ref = registry_deployment.get("referenceResourceRelease")
    import_ref = registry_deployment.get("registryImportSnapshot")
    if (
        not isinstance(release_ref, Mapping)
        or supplied_permission.get("referenceResourceRelease") != release_ref
        or supplied_permission.get("registryImportSnapshot") != import_ref
    ):
        raise AcceptedOutputAuthorizationError(
            "permission row does not match the selected registry release and import"
        )
    if member.release_iri != release_ref.get("id"):
        raise AcceptedOutputAuthorizationError(
            "accepted member does not belong to the selected registry release"
        )

    vocabulary = configuration.get("vocabulary")
    if not isinstance(vocabulary, Mapping):
        raise AcceptedOutputAuthorizationError(
            "EnrichmentConfiguration lacks vocabulary pins"
        )
    registry_ref = dict(_exact_reference(registry_deployment))
    if registry_ref not in vocabulary.get("registryDeploymentDecisions", []):
        raise AcceptedOutputAuthorizationError(
            "EnrichmentConfiguration does not pin the exact registry deployment"
        )
    if dict(release_ref) not in vocabulary.get("referenceResourceReleases", []):
        raise AcceptedOutputAuthorizationError(
            "EnrichmentConfiguration does not pin the selected release"
        )
    if dict(import_ref) not in vocabulary.get("registryImportSnapshots", []):
        raise AcceptedOutputAuthorizationError(
            "EnrichmentConfiguration does not pin the selected import"
        )

    matching_indexes = [
        row
        for row in configuration.get("indexes", [])
        if isinstance(row, Mapping)
        and row.get("expressionCorpusSnapshot") == actual_expression_corpus
        and row.get("lookupIndexManifest") == actual_lookup_index
    ]
    if len(matching_indexes) != 1:
        raise AcceptedOutputAuthorizationError(
            "EnrichmentConfiguration must contain exactly one index pin for "
            "the actual expression corpus and lookup index"
        )

    _require_exact_record_reference(
        evaluation.get("configuration"),
        configuration,
        "evaluation configuration",
    )
    if evaluation.get("verdict") != "pass":
        raise AcceptedOutputAuthorizationError(
            "accepted output requires a passing EnrichmentEvaluationResult"
        )
    _require_exact_record_reference(
        enrichment_deployment.get("configuration"),
        configuration,
        "enrichment deployment configuration",
    )
    _require_exact_record_reference(
        enrichment_deployment.get("evaluationResult"),
        evaluation,
        "enrichment deployment evaluation",
    )

    registry_environment = registry_deployment.get("environment")
    enrichment_environment = enrichment_deployment.get("environment")
    if (
        not isinstance(registry_environment, Mapping)
        or not isinstance(enrichment_environment, Mapping)
        or registry_environment.get("id") != enrichment_environment.get("id")
    ):
        raise AcceptedOutputAuthorizationError(
            "registry and enrichment deployments select different environments"
        )

    if receipt.get("type") != _RECEIPT_TYPE:
        raise AcceptedOutputAuthorizationError(
            "accepted output requires a ReleaseGraphValidationReceipt"
        )
    if receipt.get("operationalState") != "passed":
        raise AcceptedOutputAuthorizationError(
            "ReleaseGraphValidationReceipt is not passed"
        )
    gate = receipt.get("gateImplementation")
    if not isinstance(gate, Mapping) or gate.get("id") != _GATE_IMPLEMENTATION_ID:
        raise AcceptedOutputAuthorizationError(
            "receipt was not issued by the RefSpec release-graph gate"
        )
    verdicts = receipt.get("verdicts")
    if (
        not isinstance(verdicts, Mapping)
        or verdicts.get("rulespecBehavior") != "pass"
        or any(value != "pass" for value in verdicts.values())
    ):
        raise AcceptedOutputAuthorizationError(
            "ReleaseGraphValidationReceipt does not carry all passing verdicts"
        )
    behavior_runtime = receipt.get("rulespecBehaviorRuntime")
    if not isinstance(behavior_runtime, Mapping):
        raise AcceptedOutputAuthorizationError(
            "ReleaseGraphValidationReceipt lacks the exact Rulespec behavior runtime"
        )

    receipt_record_refs = receipt.get("refRecordDigests")
    if not isinstance(receipt_record_refs, list):
        raise AcceptedOutputAuthorizationError(
            "ReleaseGraphValidationReceipt lacks refRecordDigests"
        )
    for label, decision in (
        ("RegistryDeploymentDecision", registry_deployment),
        ("EnrichmentDeploymentDecision", enrichment_deployment),
    ):
        decision_ref = dict(_exact_reference(decision))
        if decision_ref not in receipt_record_refs:
            raise AcceptedOutputAuthorizationError(
                f"ReleaseGraphValidationReceipt does not digest the exact {label}"
            )
        _require_receipt_authorization(receipt, decision, label)

    return AcceptedOutputAuthorization(
        member=member,
        permission=cast(Mapping[str, Any], _freeze(supplied_permission)),
        expression_corpus_snapshot=cast(
            Mapping[str, str],
            _freeze(actual_expression_corpus),
        ),
        lookup_index_manifest=cast(
            Mapping[str, str],
            _freeze(actual_lookup_index),
        ),
        registry_deployment=_exact_reference(registry_deployment),
        configuration=_exact_reference(configuration),
        evaluation_result=_exact_reference(evaluation),
        enrichment_deployment=_exact_reference(enrichment_deployment),
        validation_receipt=_exact_reference(receipt),
    )
