from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from refspec.accepted_output import (
    AcceptedOutputAuthorizationError,
    authorize_accepted_assignment,
)
from refspec.managed_release import (
    ManagedReleaseMember,
    ManagedReleaseView,
)
from refspec.vocabulary import seal_payload

FIXTURE = (
    Path(__file__).parents[1]
    / "bindings"
    / "json"
    / "1.0"
    / "fixtures"
    / "valid"
    / "vocabulary-closure.json"
)
DIGEST = "sha256:" + "8" * 64


def _records() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["records"]


def _record(
    records: list[dict[str, Any]],
    record_type: str,
) -> dict[str, Any]:
    return next(record for record in records if record["type"] == record_type)


def _view(
    records: list[dict[str, Any]],
    *,
    receipt: dict[str, Any],
) -> ManagedReleaseView:
    configuration = _record(
        records,
        "urn:ref:type:EnrichmentConfiguration",
    )
    expression_corpus = configuration["indexes"][0][
        "expressionCorpusSnapshot"
    ]
    release = configuration["vocabulary"]["referenceResourceReleases"][0][
        "id"
    ]
    member = ManagedReleaseMember(
        member_iri="urn:example:concept:air-quality",
        release_iri=release,
        scheme_iri="urn:example:scheme:subjects-a",
        record={
            "@id": "urn:example:concept:air-quality",
            "@type": "rkaf:RegisteredConcept",
        },
    )
    return ManagedReleaseView(
        _release_id="urn:example:publication:subjects-a",
        _expression_corpus_snapshot=expression_corpus,
        _members={member.member_iri: member},
        _expressions=(),
        _relations=(),
        _lifecycle_participants=(),
        _concept_mappings=(),
        _release_graph_validation_receipt=receipt,
    )


def _receipt(records: list[dict[str, Any]]) -> dict[str, Any]:
    registry = _record(
        records,
        "urn:ref:type:RegistryDeploymentDecision",
    )
    enrichment = _record(
        records,
        "urn:ref:type:EnrichmentDeploymentDecision",
    )

    def reference(record: dict[str, Any]) -> dict[str, str]:
        return {
            "id": record["id"],
            "digest": record["canonicalPayloadDigest"],
        }

    evaluations = []
    for suffix, decision in (
        ("registry", registry),
        ("enrichment", enrichment),
    ):
        evaluations.append(
            {
                "governanceRecord": reference(decision),
                "behaviorTest": {
                    "id": f"urn:example:behavior-test:{suffix}",
                    "digest": "sha256:" + "1" * 64,
                },
                "inputGraph": {
                    "id": "urn:rulespec:release-graph:accepted-output",
                    "digest": "sha256:" + "6" * 64,
                },
                "behaviorContract": "rkaf:UsageEligibilityReducer",
                "subjectAssertion": f"urn:example:assertion:{suffix}",
                "evaluationScope": "urn:example:scope:accepted-output",
                "evaluationTime": "2026-07-29T19:00:00Z",
                "minimumUsageEligibility": "rkaf:localOperationalUse",
                "effectiveUsageEligibility": "rkaf:publicationAllowed",
                "outputDigest": "sha256:" + "3" * 64,
                "runtime": {
                    "id": "urn:rulespec:runtime:rkaf-behavior-validate",
                    "revision": "0eb94257b70783688b55220e7a84dcc61bbd7507",
                    "digest": "sha256:" + "4" * 64,
                },
                "result": "pass",
            }
        )
    return seal_payload(
        {
            "id": "urn:example:release-graph-receipt:accepted-output",
            "type": "urn:ref:type:ReleaseGraphValidationReceipt",
            "recordedAt": "2026-07-29T19:00:00Z",
            "recordedBy": "urn:ref:agent:release-graph-gate",
            "schemaVersion": "1.0",
            "operationalState": "passed",
            "receiptVersion": "1.0",
            "rulespecDependencyManifest": {
                "id": "urn:ref:rulespec-dependency:0.2.0-pre.9",
                "digest": "sha256:" + "5" * 64,
            },
            "rulespecGraph": {
                "id": "urn:rulespec:release-graph:accepted-output",
                "digest": "sha256:" + "6" * 64,
            },
            "refRecordDigests": [
                reference(registry),
                reference(enrichment),
            ],
            "rulespecValidator": {
                "id": "urn:rulespec:validator:rkaf-validate",
                "revision": "0eb94257b70783688b55220e7a84dcc61bbd7507",
                "digest": "sha256:" + "7" * 64,
            },
            "rulespecBehaviorRuntime": {
                "id": "urn:rulespec:runtime:rkaf-behavior-validate",
                "revision": "0eb94257b70783688b55220e7a84dcc61bbd7507",
                "digest": "sha256:" + "4" * 64,
            },
            "gateImplementation": {
                "id": (
                    "https://refspec.org/reference-runtime/"
                    "release-graph-gate"
                ),
                "revision": "0.1.0.dev0",
                "digest": "sha256:" + "9" * 64,
            },
            "verdicts": {
                "refBinding": "pass",
                "rulespecConformance": "pass",
                "rulespecBehavior": "pass",
                "crossBoundary": "pass",
            },
            "authorizationEvaluations": evaluations,
            "coveredRulespecIdentifiers": [
                "urn:example:concept:air-quality",
                "urn:rulespec:release-graph:accepted-output",
            ],
            "crossReferencesDigest": "sha256:" + "a" * 64,
            "validatedAt": "2026-07-29T19:00:00Z",
            "activity": "urn:example:activity:validate-accepted-output",
        }
    )


def _call(
    records: list[dict[str, Any]],
    *,
    view: ManagedReleaseView | None = None,
    permission: dict[str, Any] | None = None,
    lookup_index: dict[str, str] | None = None,
    receipt: dict[str, Any] | None = None,
):
    output = _record(records, "urn:ref:type:OutputProfile")
    registry = _record(
        records,
        "urn:ref:type:RegistryDeploymentDecision",
    )
    configuration = _record(
        records,
        "urn:ref:type:EnrichmentConfiguration",
    )
    evaluation = _record(
        records,
        "urn:ref:type:EnrichmentEvaluationResult",
    )
    deployment = _record(
        records,
        "urn:ref:type:EnrichmentDeploymentDecision",
    )
    selected_permission = copy.deepcopy(
        permission or output["releasePermissions"][0]
    )
    selected_receipt = receipt if receipt is not None else _receipt(records)
    selected_view = view or _view(records, receipt=selected_receipt)
    return authorize_accepted_assignment(
        managed_release=selected_view,
        member_iri="urn:example:concept:air-quality",
        facet="urn:ref:facet:general-subject",
        assignment_role="https://rulespec.org/ns/v1#assignmentPrimary",
        accepted_output_permission=selected_permission,
        expression_corpus_snapshot=selected_view.expression_corpus_snapshot,
        lookup_index_manifest=(
            lookup_index
            or copy.deepcopy(
                configuration["indexes"][0]["lookupIndexManifest"]
            )
        ),
        ref_records=records,
        output_profile_id=output["id"],
        registry_deployment_id=registry["id"],
        configuration_id=configuration["id"],
        evaluation_result_id=evaluation["id"],
        enrichment_deployment_id=deployment["id"],
        release_graph_validation_receipt=(
            selected_receipt
        ),
    )


def test_accepted_assignment_resolves_exact_authorization_chain() -> None:
    records = _records()

    result = _call(records)

    assert result.member.member_iri == "urn:example:concept:air-quality"
    assert result.member.release_iri == result.permission[
        "referenceResourceRelease"
    ]["id"]
    assert result.registry_deployment["id"] == (
        "urn:example:registry-deployment:prod-a"
    )
    assert result.configuration["id"] == "urn:example:configuration:c1"
    assert result.evaluation_result["id"] == "urn:example:evaluation:e1"
    assert result.enrichment_deployment["id"] == (
        "urn:example:deployment:prod-1"
    )
    assert result.usage_eligibility == "acceptedOutput"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record["models"][0].update(
            {"revision": "changed-model"}
        ),
        lambda record: record["models"][0]["providerConfiguration"].update(
            {"revision": "changed-provider"}
        ),
        lambda record: record["prompts"][0].update(
            {"revision": "changed-prompt"}
        ),
        lambda record: record["toolPolicies"][0].update(
            {"revision": "changed-policy"}
        ),
        lambda record: record["budgets"][0].update({"tokens": 9999}),
        lambda record: record["vocabulary"][
            "referenceResourceReleases"
        ][0].update({"version": "changed-release"}),
    ],
    ids=[
        "model",
        "provider",
        "prompt",
        "policy",
        "budget",
        "release",
    ],
)
def test_changed_configuration_requires_a_new_passing_chain(
    mutate,
) -> None:
    records = _records()
    configuration = _record(
        records,
        "urn:ref:type:EnrichmentConfiguration",
    )
    mutate(configuration)
    configuration.update(seal_payload(configuration))

    with pytest.raises(AcceptedOutputAuthorizationError):
        _call(records)


def test_changed_lookup_index_requires_a_new_configuration() -> None:
    records = _records()

    with pytest.raises(
        AcceptedOutputAuthorizationError,
        match="exactly one index pin",
    ):
        _call(
            records,
            lookup_index={
                "id": "urn:example:lookup-index-manifest:changed",
                "digest": DIGEST,
            },
        )


def test_permission_values_cannot_be_assembled_from_another_row() -> None:
    records = _records()
    output = _record(records, "urn:ref:type:OutputProfile")
    permission = copy.deepcopy(output["releasePermissions"][0])
    permission["assignmentRole"] = output["releasePermissions"][1][
        "assignmentRole"
    ]

    with pytest.raises(
        AcceptedOutputAuthorizationError,
        match="match exactly one complete",
    ):
        _call(records, permission=permission)


def test_fake_gate_receipt_cannot_authorize_output() -> None:
    records = _records()
    receipt = _receipt(records)
    receipt["gateImplementation"]["id"] = "urn:example:fake-gate"
    receipt.update(seal_payload(receipt))

    with pytest.raises(
        AcceptedOutputAuthorizationError,
        match="not issued by the RefSpec release-graph gate",
    ):
        _call(records, receipt=receipt)


def test_missing_behavior_evaluation_cannot_authorize_output() -> None:
    records = _records()
    receipt = _receipt(records)
    receipt["authorizationEvaluations"] = receipt[
        "authorizationEvaluations"
    ][1:]
    receipt.update(seal_payload(receipt))

    with pytest.raises(
        AcceptedOutputAuthorizationError,
        match="RegistryDeploymentDecision",
    ):
        _call(records, receipt=receipt)


def test_missing_receipt_cannot_authorize_output() -> None:
    records = _records()

    with pytest.raises(AcceptedOutputAuthorizationError):
        _call(records, receipt={})


def test_supplied_receipt_must_be_the_one_opened_with_the_release() -> None:
    records = _records()
    trusted = _receipt(records)
    substituted = copy.deepcopy(trusted)
    substituted["activity"] = "urn:example:activity:substituted-receipt"
    substituted.update(seal_payload(substituted))
    view = _view(records, receipt=trusted)

    with pytest.raises(
        AcceptedOutputAuthorizationError,
        match="exact receipt verified",
    ):
        _call(records, view=view, receipt=substituted)
