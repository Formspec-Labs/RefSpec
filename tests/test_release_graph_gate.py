from __future__ import annotations

import hashlib
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from refspec import binding, release_graph
from refspec.release_graph import (
    GRAPH_DIGEST_ALGORITHM,
    ReleaseGraphGateReport,
    RulespecValidatorPin,
    ValidatorCommand,
    issue_release_graph_validation_receipt,
    load_rulespec_dependency_manifest,
    rulespec_graph_digest,
    validate_release_graph_bundle,
)

REAL_BINDING_VALIDATE = binding.validate
VALIDATOR_IDENTITY = (
    "rkaf-validate@test + tools/ci_validate.py + "
    "rkaf-behavior-validate@test"
)
VALIDATOR_REVISION = "a" * 40
EVIDENCE_REVISION = "b" * 40
RULESPEC_IDENTIFIER = "urn:rulespec:concept:example"
RULESPEC_GRAPH_IDENTIFIER = "urn:rulespec:graph:example"
REF_IDENTIFIER = "urn:ref:record:example"


@pytest.fixture(autouse=True)
def accept_ref_records(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binding, "validate", lambda records: [])


def validator_pin(
    tmp_path: Path,
    *,
    exit_code: int = 0,
    dependency_manifest: Path | None = None,
) -> RulespecValidatorPin:
    script = (
        "import json,sys; "
        "document=json.load(open(sys.argv[1], encoding='utf-8')); "
        "print(len(document.get('@graph', []))); "
        f"raise SystemExit({exit_code})"
    )
    behavior_script = """
import json
import pathlib
import sys

lattice = [
    "rkaf:notEligible",
    "rkaf:searchOnly",
    "rkaf:reviewQueueOnly",
    "rkaf:draftGenerationAllowed",
    "rkaf:localOperationalUse",
    "rkaf:publicationAllowed",
    "rkaf:officialUse",
]
path = pathlib.Path(sys.argv[1])
test_case = json.load(path.open(encoding="utf-8"))
nodes = {
    node["@id"]: node
    for node in test_case["rkaf:input"]["@graph"]
    if isinstance(node, dict) and isinstance(node.get("@id"), str)
}
subject = test_case["rkaf:subjectAssertion"]
scope = test_case["rkaf:evaluationScopes"][0]
assertion = nodes[subject]
level = assertion.get("rkaf:usageEligibility", "rkaf:notEligible")
if assertion.get("rkaf:consumerLifecycleState") == "rkaf:staleForCurrentUse":
    level = "rkaf:notEligible"
for node in nodes.values():
    if (
        node.get("@type") == "rkaf:LocalAdoption"
        and node.get("rkaf:targetAssertion") == subject
        and node.get("rkaf:adoptionScope") == scope
        and node.get("rkaf:adoptionStatus") == "rkaf:active"
    ):
        grant = node["rkaf:usageEligibility"]
        level = lattice[max(lattice.index(level), lattice.index(grant))]
actual = {"byScope": {scope: level}}
expected = test_case["rkaf:expectedOutput"]
passed = actual == expected
print(json.dumps({
    "fixtures": [{
        "name": path.stem,
        "result": "pass" if passed else "fail",
        "diagnostic": None if passed else "OutputMismatch",
    }]
}))
raise SystemExit(0 if passed else 1)
"""
    return RulespecValidatorPin(
        identity=VALIDATOR_IDENTITY,
        source_revision=VALIDATOR_REVISION,
        evidence_revision=EVIDENCE_REVISION,
        working_directory=tmp_path,
        commands=(
            ValidatorCommand(
                "test Rulespec validator",
                (sys.executable, "-c", script, "{graph}"),
            ),
        ),
        behavior_command=ValidatorCommand(
            "test Rulespec L4 behavior runtime",
            (sys.executable, "-c", behavior_script, "{behavior}"),
        ),
        behavior_component_digest="sha256:" + "d" * 64,
        dependency_manifest_digest=(
            "sha256:" + hashlib.sha256(dependency_manifest.read_bytes()).hexdigest()
            if dependency_manifest is not None
            else ""
        ),
    )


def release_shape_validator_pin(
    tmp_path: Path,
    *,
    dependency_manifest: Path,
) -> RulespecValidatorPin:
    """Stand in for the pinned Rulespec release-shape gate."""

    script = """
import json
import sys

document = json.load(open(sys.argv[1], encoding="utf-8"))
required = {
    "dcterms:isVersionOf",
    "dcat:version",
    "dcterms:type",
    "rkaf:membershipMode",
    "prov:hadMember",
    "dcat:distribution",
    "rkaf:referenceReleaseDigest",
}
releases = [
    node
    for node in document.get("@graph", [])
    if node.get("@type") == "rkaf:ReferenceResourceRelease"
]
raise SystemExit(
    0 if releases and all(required <= set(node) for node in releases) else 13
)
"""
    return RulespecValidatorPin(
        identity=VALIDATOR_IDENTITY,
        source_revision=VALIDATOR_REVISION,
        evidence_revision=EVIDENCE_REVISION,
        working_directory=tmp_path,
        commands=(
            ValidatorCommand(
                "test Rulespec release-shape validator",
                (sys.executable, "-c", script, "{graph}"),
            ),
        ),
        dependency_manifest_digest=(
            "sha256:"
            + hashlib.sha256(dependency_manifest.read_bytes()).hexdigest()
        ),
    )


def valid_bundle() -> dict:
    graph = {
        "@context": {
            "rkaf": "https://rulespec.org/ns/v1#",
        },
        "@graph": [
            {
                "@id": RULESPEC_IDENTIFIER,
                "@type": "rkaf:Concept",
                "rkaf:prefLabel": {"en": "Example"},
            }
        ],
    }
    digest = rulespec_graph_digest(graph)
    ref_record = {
        "id": REF_IDENTIFIER,
        "type": "urn:ref:type:Example",
        "rulespecReference": RULESPEC_IDENTIFIER,
    }
    ref_record["canonicalPayloadDigest"] = binding.canonical_payload_digest(
        ref_record
    )
    return {
        "bundleVersion": "1.0",
        "refRecords": [ref_record],
        "rulespecGraph": graph,
        "rulespecGraphId": RULESPEC_GRAPH_IDENTIFIER,
        "graphDigestAlgorithm": GRAPH_DIGEST_ALGORITHM,
        "rulespecGraphDigest": digest,
        "validatorReceipt": {
            "id": "urn:receipt:rulespec:example",
            "validatorIdentity": VALIDATOR_IDENTITY,
            "validatorSourceRevision": VALIDATOR_REVISION,
            "graphId": RULESPEC_GRAPH_IDENTIFIER,
            "graphDigest": digest,
            "coveredIdentifiers": [RULESPEC_IDENTIFIER],
            "result": "pass",
        },
        "crossReferences": [
            {
                "refRecordId": REF_IDENTIFIER,
                "rulespecIdentifier": RULESPEC_IDENTIFIER,
            }
        ],
    }


def selected_registry_bundle(*, open_ended_period: bool = False) -> dict:
    decision_id = "urn:ref:registry-deployment:selected"
    scope = "urn:ref:environment:development"
    subject = "urn:rulespec:assertion:registry-selection"
    attestation = "urn:rulespec:attestation:registry-selection"
    adoption = "urn:rulespec:adoption:registry-selection"
    release = "urn:rulespec:release:registry-selection"
    activity = "urn:rulespec:activity:registry-selection"
    period = "urn:rulespec:effective-period:registry-selection"
    graph_nodes = [
        {
            "@id": subject,
            "@type": "rkaf:ValueAssertion",
            "rkaf:assertionOrigin": "rkaf:humanAsserted",
            "rkaf:epistemicBasis": "rkaf:editorialAssertion",
            "rkaf:usageEligibility": "rkaf:notEligible",
        },
        {
            "@id": attestation,
            "@type": "rkaf:Attestation",
            "rkaf:attestor": "urn:rulespec:actor:reviewer",
            "rkaf:attestorKind": "rkaf:humanUser",
            "rkaf:targets": [subject],
            "rkaf:decision": "rkaf:approved",
            "rkaf:attestationScope": scope,
            "rkaf:attestedAt": "2026-07-29T17:00:00Z",
            **(
                {"rkaf:hasEffectivePeriod": period}
                if open_ended_period
                else {}
            ),
        },
        {
            "@id": adoption,
            "@type": "rkaf:LocalAdoption",
            "rkaf:organization": "urn:rulespec:organization:test",
            "rkaf:targetAssertion": subject,
            "rkaf:adoptionStatus": "rkaf:active",
            "rkaf:usageEligibility": "rkaf:localOperationalUse",
            "rkaf:adoptionAuthorityKind": "rkaf:localOperational",
            "rkaf:adoptionScope": scope,
            "rkaf:authorizedBy": "urn:rulespec:actor:reviewer",
            "rkaf:adoptedAt": "2026-07-29T17:00:00Z",
            "rkaf:basedOnAttestation": attestation,
        },
        {
            "@id": release,
            "@type": "rkaf:ReferenceResourceRelease",
        },
        {
            "@id": activity,
            "@type": "prov:Activity",
        },
    ]
    if open_ended_period:
        graph_nodes.append(
            {
                "@id": period,
                "@type": "rkaf:EffectivePeriod",
                "rkaf:effectivePeriodStart": "2026-01-01T00:00:00Z",
            }
        )
    graph = {
        "@context": {
            "rkaf": "https://rulespec.org/ns/v1#",
            "prov": "http://www.w3.org/ns/prov#",
        },
        "@graph": graph_nodes,
    }
    graph_digest = rulespec_graph_digest(graph)
    decision = {
        "id": decision_id,
        "type": "urn:ref:type:RegistryDeploymentDecision",
        "recordedAt": "2026-07-29T18:00:00Z",
        "recordedBy": "urn:ref:agent:test",
        "schemaVersion": "1.0",
        "operationalState": "effective",
        "environment": {"id": scope, "classification": "development"},
        "selectionState": "selected",
        "effectiveAt": "2026-07-29T18:00:00Z",
        "referenceResourceRelease": {
            "id": release,
            "version": "1",
            "digest": "sha256:" + "1" * 64,
        },
        "rulespecAttestationRefs": [attestation],
        "localAdoptionRefs": [adoption],
        "activity": activity,
    }
    decision["canonicalPayloadDigest"] = binding.canonical_payload_digest(
        decision
    )
    covered = sorted(release_graph.defined_rulespec_identifiers(graph))
    cross_references = [
        {"refRecordId": decision_id, "rulespecIdentifier": identifier}
        for identifier in (release, attestation, adoption, activity)
    ]
    return {
        "bundleVersion": "1.0",
        "refRecords": [decision],
        "rulespecGraph": graph,
        "rulespecGraphId": RULESPEC_GRAPH_IDENTIFIER,
        "graphDigestAlgorithm": GRAPH_DIGEST_ALGORITHM,
        "rulespecGraphDigest": graph_digest,
        "validatorReceipt": {
            "id": "urn:receipt:rulespec:selected-registry",
            "validatorIdentity": VALIDATOR_IDENTITY,
            "validatorSourceRevision": VALIDATOR_REVISION,
            "graphId": RULESPEC_GRAPH_IDENTIFIER,
            "graphDigest": graph_digest,
            "coveredIdentifiers": covered,
            "result": "pass",
        },
        "crossReferences": cross_references,
    }


def resolved_reconciliation_bundle() -> dict:
    record_id = "urn:ref:reconciliation:resolved"
    scope = "urn:ref:precedence-policy:v1"
    subject = "urn:rulespec:assertion:reconciliation"
    authority = "urn:rulespec:authority:reconciliation"
    attestation = "urn:rulespec:attestation:reconciliation"
    adoption = "urn:rulespec:adoption:reconciliation"
    activity = "urn:rulespec:activity:reconciliation"
    graph = {
        "@context": {
            "rkaf": "https://rulespec.org/ns/v1#",
            "prov": "http://www.w3.org/ns/prov#",
        },
        "@graph": [
            {
                "@id": subject,
                "@type": "rkaf:ValueAssertion",
                "rkaf:assertionOrigin": "rkaf:humanAsserted",
                "rkaf:epistemicBasis": "rkaf:editorialAssertion",
                "rkaf:usageEligibility": "rkaf:notEligible",
                "rkaf:hasAuthority": authority,
            },
            {
                "@id": authority,
                "@type": "rkaf:Authority",
            },
            {
                "@id": attestation,
                "@type": "rkaf:Attestation",
                "rkaf:attestor": "urn:rulespec:actor:reviewer",
                "rkaf:attestorKind": "rkaf:humanUser",
                "rkaf:targets": [subject],
                "rkaf:decision": "rkaf:approved",
                "rkaf:attestationScope": scope,
                "rkaf:attestedAt": "2026-07-29T17:00:00Z",
            },
            {
                "@id": adoption,
                "@type": "rkaf:LocalAdoption",
                "rkaf:organization": "urn:rulespec:organization:test",
                "rkaf:targetAssertion": subject,
                "rkaf:adoptionStatus": "rkaf:active",
                "rkaf:usageEligibility": "rkaf:localOperationalUse",
                "rkaf:adoptionAuthorityKind": "rkaf:localOperational",
                "rkaf:adoptionScope": scope,
                "rkaf:authorizedBy": "urn:rulespec:actor:reviewer",
                "rkaf:adoptedAt": "2026-07-29T17:00:00Z",
                "rkaf:basedOnAttestation": attestation,
            },
            {"@id": activity, "@type": "prov:Activity"},
        ],
    }
    graph_digest = rulespec_graph_digest(graph)
    record = {
        "id": record_id,
        "type": "urn:ref:type:RegistryReconciliationReport",
        "recordedAt": "2026-07-29T18:00:00Z",
        "recordedBy": "urn:ref:agent:test",
        "schemaVersion": "1.0",
        "operationalState": "complete",
        "precedencePolicy": {
            "id": scope,
            "version": "1",
            "digest": "sha256:" + "1" * 64,
        },
        "rulespecAuthorityRefs": [authority],
        "attestationRefs": [attestation],
        "localAdoptionRefs": [adoption],
        "activity": activity,
        "outcome": "selectedInput",
    }
    record["canonicalPayloadDigest"] = binding.canonical_payload_digest(record)
    covered = sorted(release_graph.defined_rulespec_identifiers(graph))
    return {
        "bundleVersion": "1.0",
        "refRecords": [record],
        "rulespecGraph": graph,
        "rulespecGraphId": RULESPEC_GRAPH_IDENTIFIER,
        "graphDigestAlgorithm": GRAPH_DIGEST_ALGORITHM,
        "rulespecGraphDigest": graph_digest,
        "validatorReceipt": {
            "id": "urn:receipt:rulespec:reconciliation",
            "validatorIdentity": VALIDATOR_IDENTITY,
            "validatorSourceRevision": VALIDATOR_REVISION,
            "graphId": RULESPEC_GRAPH_IDENTIFIER,
            "graphDigest": graph_digest,
            "coveredIdentifiers": covered,
            "result": "pass",
        },
        "crossReferences": [
            {"refRecordId": record_id, "rulespecIdentifier": identifier}
            for identifier in (authority, attestation, adoption, activity)
        ],
    }


def schema_aware_bundle(
    record: dict,
    graph_nodes: list[dict],
    cross_reference_identifiers: list[str],
) -> dict:
    graph = {
        "@context": {
            "rkaf": "https://rulespec.org/ns/v1#",
            "prov": "http://www.w3.org/ns/prov#",
        },
        "@graph": graph_nodes,
    }
    digest = rulespec_graph_digest(graph)
    return {
        "bundleVersion": "1.0",
        "refRecords": [record],
        "rulespecGraph": graph,
        "rulespecGraphId": RULESPEC_GRAPH_IDENTIFIER,
        "graphDigestAlgorithm": GRAPH_DIGEST_ALGORITHM,
        "rulespecGraphDigest": digest,
        "validatorReceipt": {
            "id": "urn:receipt:rulespec:schema-aware",
            "validatorIdentity": VALIDATOR_IDENTITY,
            "validatorSourceRevision": VALIDATOR_REVISION,
            "graphId": RULESPEC_GRAPH_IDENTIFIER,
            "graphDigest": digest,
            "coveredIdentifiers": sorted(
                release_graph.defined_rulespec_identifiers(graph)
            ),
            "result": "pass",
        },
        "crossReferences": [
            {
                "refRecordId": record["id"],
                "rulespecIdentifier": identifier,
            }
            for identifier in cross_reference_identifiers
        ],
    }


def test_combined_release_graph_passes_both_validators_and_boundary(
    tmp_path: Path,
) -> None:
    report = validate_release_graph_bundle(
        valid_bundle(),
        validator=validator_pin(tmp_path),
    )

    assert report == ReleaseGraphGateReport()
    assert report.passed


def test_schema_aware_resolver_finds_missing_target_not_named_by_crossrefs(
    tmp_path: Path,
) -> None:
    release_identifier = "urn:rulespec:release:schema-aware"
    conformance_identifier = "urn:rulespec:validation:schema-aware"
    activity_identifier = "urn:rulespec:activity:schema-aware"
    missing_artifact = "urn:rulespec:artifact:missing"
    record = {
        "id": "urn:ref:import:schema-aware",
        "type": "urn:ref:type:RegistryImportSnapshot",
        "referenceResourceRelease": {"id": release_identifier},
        "distributionArtifacts": [{"id": missing_artifact}],
        "rulespecValidationResult": {"id": conformance_identifier},
        "activity": activity_identifier,
    }
    bundle = schema_aware_bundle(
        record,
        [
            {
                "@id": release_identifier,
                "@type": "rkaf:ReferenceResourceRelease",
            },
            {
                "@id": conformance_identifier,
                "@type": "rkaf:Artifact",
            },
            {
                "@id": activity_identifier,
                "@type": "prov:Activity",
            },
        ],
        [
            release_identifier,
            conformance_identifier,
            activity_identifier,
        ],
    )

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path),
    )

    assert not report.passed
    assert any(
        missing_artifact in failure
        and "validated graph does not define it" in failure
        for failure in report.cross_boundary_failures
    )


def test_schema_aware_resolver_rejects_wrong_rulespec_node_type(
    tmp_path: Path,
) -> None:
    concept_identifier = "urn:rulespec:concept:typed-wrong"
    record = {
        "id": "urn:ref:expression:typed-wrong",
        "type": "urn:ref:type:IndexedVocabularyExpression",
        "member": concept_identifier,
    }
    bundle = schema_aware_bundle(
        record,
        [
            {
                "@id": concept_identifier,
                "@type": "rkaf:Artifact",
            }
        ],
        [concept_identifier],
    )

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path),
    )

    assert not report.passed
    assert any(
        "/member requires" in failure
        and "RegisteredConcept" in failure
        and "Artifact" in failure
        for failure in report.cross_boundary_failures
    )


def test_schema_aware_resolver_accepts_external_native_skos_members(
    tmp_path: Path,
) -> None:
    scheme_identifier = "https://example.test/vocabulary/6/"
    concept_identifier = (
        "https://example.test/vocabulary/6/concept-1"
    )
    record = {
        "id": "urn:ref:expression:native-skos",
        "type": "urn:ref:type:IndexedVocabularyExpression",
        "scheme": scheme_identifier,
        "member": concept_identifier,
    }
    bundle = schema_aware_bundle(
        record,
        [
            {
                "@id": scheme_identifier,
                "@type": "skos:ConceptScheme",
            },
            {
                "@id": concept_identifier,
                "@type": "skos:Concept",
            },
        ],
        [scheme_identifier, concept_identifier],
    )

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path),
    )

    assert report.passed


def test_authorization_kind_must_match_rulespec_node_type(
    tmp_path: Path,
) -> None:
    authorization_identifier = "urn:rulespec:authority:not-attestation"
    record = {
        "id": "urn:ref:deployment:authorization-kind",
        "type": "urn:ref:type:RegistryDeploymentDecision",
        "rulespecAttestationRefs": [authorization_identifier],
    }
    bundle = schema_aware_bundle(
        record,
        [
            {
                "@id": authorization_identifier,
                "@type": "rkaf:Authority",
            }
        ],
        [authorization_identifier],
    )

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path),
    )

    assert not report.passed
    assert any(
        "/rulespecAttestationRefs/0 requires" in failure
        and "Attestation" in failure
        and "Authority" in failure
        for failure in report.cross_boundary_failures
    )


def test_type_resolution_accepts_compact_expanded_and_type_arrays(
    tmp_path: Path,
) -> None:
    release_identifier = "urn:rulespec:release:type-forms"
    artifact_identifier = "urn:rulespec:artifact:type-forms"
    activity_identifier = "urn:rulespec:activity:type-forms"
    record = {
        "id": "urn:ref:coverage:type-forms",
        "type": "urn:ref:type:RegistryImportCoverageReport",
        "referenceResourceRelease": {"id": release_identifier},
        "distributionArtifacts": [{"id": artifact_identifier}],
        "activity": activity_identifier,
        "recordedBy": "urn:external:agent:reference-runtime",
    }
    bundle = schema_aware_bundle(
        record,
        [
            {
                "@id": release_identifier,
                "@type": "rkaf:ReferenceResourceRelease",
            },
            {
                "@id": artifact_identifier,
                "@type": "https://rulespec.org/ns/v1#Artifact",
            },
            {
                "@id": activity_identifier,
                "@type": [
                    "http://www.w3.org/ns/prov#Entity",
                    "https://rulespec.org/ns/v1#ExtractionActivity",
                ],
            },
        ],
        [
            release_identifier,
            artifact_identifier,
            activity_identifier,
        ],
    )

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path),
    )

    assert report == ReleaseGraphGateReport()


def test_bare_jsonld_identifier_is_not_a_defining_graph_node(
    tmp_path: Path,
) -> None:
    release_identifier = "urn:rulespec:release:bare-reference"
    record = {
        "id": "urn:ref:output-profile:bare-reference",
        "type": "urn:ref:type:OutputProfile",
        "releasePermissions": [
            {
                "referenceResourceRelease": {
                    "id": release_identifier,
                }
            }
        ],
    }
    bundle = schema_aware_bundle(
        record,
        [{"@id": release_identifier}],
        [release_identifier],
    )

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path),
    )

    assert not report.passed
    assert any(
        release_identifier in failure
        and "validated graph does not define it" in failure
        for failure in report.cross_boundary_failures
    )


def test_external_actor_and_component_identifiers_do_not_create_crossrefs(
    tmp_path: Path,
) -> None:
    release_identifier = "urn:rulespec:release:external-actors"
    record = {
        "id": "urn:ref:receipt:external-actors",
        "type": "urn:ref:type:RunReceipt",
        "recordedBy": "urn:external:agent:recorder",
        "rulespecReleases": [{"id": release_identifier}],
        "rulespecAgentRefs": ["urn:external:agent:importer"],
        "providerDetailsReference": "urn:external:provider:request",
    }
    bundle = schema_aware_bundle(
        record,
        [
            {
                "@id": release_identifier,
                "@type": "rkaf:ReferenceResourceRelease",
            }
        ],
        [release_identifier],
    )

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path),
    )

    assert report == ReleaseGraphGateReport()


def test_crossrefs_must_exactly_match_schema_derived_references(
    tmp_path: Path,
) -> None:
    release_identifier = "urn:rulespec:release:exact-crossrefs"
    external_identifier = "urn:external:agent:not-a-cross-reference"
    record = {
        "id": "urn:ref:receipt:exact-crossrefs",
        "type": "urn:ref:type:RunReceipt",
        "rulespecReleases": [{"id": release_identifier}],
        "rulespecAgentRefs": [external_identifier],
    }
    bundle = schema_aware_bundle(
        record,
        [
            {
                "@id": release_identifier,
                "@type": "rkaf:ReferenceResourceRelease",
            },
            {
                "@id": external_identifier,
                "@type": "prov:Agent",
            },
        ],
        [release_identifier, external_identifier],
    )

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path),
    )

    assert not report.passed
    assert any(
        "crossReferences do not exactly enumerate" in failure
        and "unexpected=" in failure
        and external_identifier in failure
        for failure in report.cross_boundary_failures
    )


def test_binding_only_fixture_does_not_require_a_release_graph() -> None:
    fixture = binding.load_json(
        binding.REFSPEC_ROOT
        / "bindings"
        / "json"
        / "1.0"
        / "fixtures"
        / "valid"
        / "managed-release-minimal.json"
    )

    assert REAL_BINDING_VALIDATE(fixture["records"]) == []


def test_forged_pass_receipt_cannot_replace_rulespec_execution(
    tmp_path: Path,
) -> None:
    bundle = valid_bundle()
    assert bundle["validatorReceipt"]["result"] == "pass"

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path, exit_code=9),
    )

    assert not report.passed
    assert report.ref_failures == ()
    assert report.cross_boundary_failures == ()
    assert any("rejected graph with exit code 9" in failure for failure in report.rulespec_failures)


def test_stale_receipt_does_not_bind_a_changed_graph(tmp_path: Path) -> None:
    bundle = valid_bundle()
    bundle["rulespecGraph"]["@graph"][0]["rkaf:prefLabel"]["en"] = "Changed"

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path),
    )

    assert not report.passed
    assert report.ref_failures == ()
    assert report.rulespec_failures == ()
    assert any("does not match exact graph digest" in failure for failure in report.cross_boundary_failures)
    assert any("does not bind the exact Rulespec graph" in failure for failure in report.cross_boundary_failures)


def test_receipt_must_cover_exact_rulespec_identifiers(tmp_path: Path) -> None:
    bundle = valid_bundle()
    bundle["validatorReceipt"]["coveredIdentifiers"] = ["urn:rulespec:concept:different"]

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path),
    )

    assert not report.passed
    assert report.ref_failures == ()
    assert report.rulespec_failures == ()
    assert any("does not exactly cover the Rulespec graph" in failure for failure in report.cross_boundary_failures)


def test_receipt_from_a_different_validator_pin_is_rejected(tmp_path: Path) -> None:
    bundle = valid_bundle()
    bundle["validatorReceipt"]["validatorIdentity"] = "rkaf-validate@other"
    bundle["validatorReceipt"]["validatorSourceRevision"] = "c" * 40

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path),
    )

    assert not report.passed
    assert report.ref_failures == ()
    assert report.rulespec_failures == ()
    assert any("validatorIdentity does not match" in failure for failure in report.cross_boundary_failures)
    assert any("validatorSourceRevision does not match" in failure for failure in report.cross_boundary_failures)


def test_cross_reference_list_must_cover_every_graph_id_used_by_ref(
    tmp_path: Path,
) -> None:
    bundle = valid_bundle()
    second_identifier = "urn:rulespec:concept:second"
    bundle["rulespecGraph"]["@graph"].append(
        {
            "@id": second_identifier,
            "@type": "rkaf:Concept",
            "rkaf:prefLabel": {"en": "Second"},
        }
    )
    digest = rulespec_graph_digest(bundle["rulespecGraph"])
    bundle["rulespecGraphDigest"] = digest
    bundle["validatorReceipt"]["graphDigest"] = digest
    bundle["validatorReceipt"]["coveredIdentifiers"].append(second_identifier)
    bundle["refRecords"][0]["secondRulespecReference"] = second_identifier

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path),
    )

    assert not report.passed
    assert any(
        "crossReferences do not exactly enumerate" in failure
        and second_identifier in failure
        for failure in report.cross_boundary_failures
    )


def test_cross_reference_list_cannot_invent_a_link_not_in_ref(
    tmp_path: Path,
) -> None:
    bundle = valid_bundle()
    del bundle["refRecords"][0]["rulespecReference"]

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path),
    )

    assert not report.passed
    assert any(
        "crossReferences do not exactly enumerate" in failure
        and "unexpected=" in failure
        for failure in report.cross_boundary_failures
    )


def test_live_gate_issues_modeled_receipt_only_after_all_channels_pass(
    tmp_path: Path,
) -> None:
    dependency_manifest = tmp_path / "rulespec-dependency.json"
    dependency_manifest.write_text('{"schemaVersion":"1.0"}\n', encoding="utf-8")

    receipt = issue_release_graph_validation_receipt(
        valid_bundle(),
        validator=validator_pin(
            tmp_path,
            dependency_manifest=dependency_manifest,
        ),
        dependency_manifest=dependency_manifest,
        receipt_id="urn:ref:release-graph-validation-receipt:test:v1",
        recorded_at="2026-07-29T18:00:00Z",
        recorded_by="urn:ref:agent:test-gate",
        activity="urn:ref:activity:test-release-graph-gate",
    )

    assert receipt["type"] == "urn:ref:type:ReleaseGraphValidationReceipt"
    assert receipt["verdicts"] == {
        "refBinding": "pass",
        "rulespecConformance": "pass",
        "rulespecBehavior": "pass",
        "crossBoundary": "pass",
    }
    assert receipt["refRecordDigests"] == [
        {
            "id": REF_IDENTIFIER,
            "digest": valid_bundle()["refRecords"][0][
                "canonicalPayloadDigest"
            ],
        }
    ]
    assert (
        receipt["canonicalPayloadDigest"]
        == binding.canonical_payload_digest(receipt)
    )


def test_selected_registry_receipt_binds_gate_owned_l4_authorization(
    tmp_path: Path,
) -> None:
    dependency_manifest = tmp_path / "rulespec-dependency.json"
    dependency_manifest.write_text('{"schemaVersion":"1.0"}\n', encoding="utf-8")
    bundle = selected_registry_bundle()

    receipt = issue_release_graph_validation_receipt(
        bundle,
        validator=validator_pin(
            tmp_path,
            dependency_manifest=dependency_manifest,
        ),
        dependency_manifest=dependency_manifest,
        receipt_id="urn:ref:release-graph-validation-receipt:selected:v1",
        recorded_at="2026-07-29T18:01:00Z",
        recorded_by="urn:ref:agent:test-gate",
        activity="urn:rulespec:activity:registry-selection",
    )

    assert receipt["verdicts"]["rulespecBehavior"] == "pass"
    assert receipt["rulespecBehaviorRuntime"]["id"] == (
        "urn:rulespec:runtime:rkaf-behavior-validate"
    )
    assert len(receipt["authorizationEvaluations"]) == 1
    evaluation = receipt["authorizationEvaluations"][0]
    decision = bundle["refRecords"][0]
    assert evaluation["governanceRecord"] == {
        "id": decision["id"],
        "digest": decision["canonicalPayloadDigest"],
    }
    assert evaluation["inputGraph"] == {
        "id": RULESPEC_GRAPH_IDENTIFIER,
        "digest": bundle["rulespecGraphDigest"],
    }
    assert evaluation["effectiveUsageEligibility"] == (
        "rkaf:localOperationalUse"
    )
    assert evaluation["result"] == "pass"


def test_open_ended_attestation_period_can_authorize_at_l4(
    tmp_path: Path,
) -> None:
    report = validate_release_graph_bundle(
        selected_registry_bundle(open_ended_period=True),
        validator=validator_pin(tmp_path),
    )

    assert report == ReleaseGraphGateReport()


def test_resolved_reconciliation_requires_gate_owned_l4_authorization(
    tmp_path: Path,
) -> None:
    dependency_manifest = tmp_path / "rulespec-dependency.json"
    dependency_manifest.write_text('{"schemaVersion":"1.0"}\n', encoding="utf-8")
    bundle = resolved_reconciliation_bundle()

    receipt = issue_release_graph_validation_receipt(
        bundle,
        validator=validator_pin(
            tmp_path,
            dependency_manifest=dependency_manifest,
        ),
        dependency_manifest=dependency_manifest,
        receipt_id="urn:ref:release-graph-validation-receipt:reconciled:v1",
        recorded_at="2026-07-29T18:01:00Z",
        recorded_by="urn:ref:agent:test-gate",
        activity="urn:rulespec:activity:reconciliation",
    )

    assert receipt["authorizationEvaluations"][0][
        "governanceRecord"
    ] == {
        "id": bundle["refRecords"][0]["id"],
        "digest": bundle["refRecords"][0]["canonicalPayloadDigest"],
    }


def test_caller_effective_boolean_and_behavior_test_cannot_authorize(
    tmp_path: Path,
) -> None:
    bundle = selected_registry_bundle()
    decision = bundle["refRecords"][0]
    decision["authorizationValidations"] = [
        {
            "authorizationRef": decision["rulespecAttestationRefs"][0],
            "kind": "rulespecAttestation",
            "effective": True,
        },
        {
            "authorizationRef": decision["localAdoptionRefs"][0],
            "kind": "localAdoption",
            "effective": True,
        },
    ]
    decision["canonicalPayloadDigest"] = binding.canonical_payload_digest(
        decision
    )
    bundle["rulespecBehaviorTests"] = [
        {
            "@type": "rkaf:BehaviorTestCase",
            "rkaf:expectedOutput": {
                "byScope": {
                    decision["environment"]["id"]: "rkaf:officialUse"
                }
            },
        }
    ]
    adoption_id = decision["localAdoptionRefs"][0]
    for node in bundle["rulespecGraph"]["@graph"]:
        if node.get("@id") == adoption_id:
            node["rkaf:adoptionStatus"] = "rkaf:revoked"
    graph_digest = rulespec_graph_digest(bundle["rulespecGraph"])
    bundle["rulespecGraphDigest"] = graph_digest
    bundle["validatorReceipt"]["graphDigest"] = graph_digest

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path),
    )

    assert not report.passed
    assert any(
        "local adoption" in failure and "is not active" in failure
        for failure in report.cross_boundary_failures
    )


def test_l4_runtime_verdict_must_name_exact_content_bound_test(
    tmp_path: Path,
) -> None:
    script = (
        "import json; "
        "print(json.dumps({'fixtures':[{'name':'unrelated',"
        "'result':'pass','diagnostic':None}]}))"
    )
    validator = replace(
        validator_pin(tmp_path),
        behavior_command=ValidatorCommand(
            "wrong-name runtime",
            (sys.executable, "-c", script, "{behavior}"),
        ),
    )

    report = validate_release_graph_bundle(
        selected_registry_bundle(),
        validator=validator,
    )

    assert not report.passed
    assert any(
        "not the exact gate-owned behavior test" in failure
        for failure in report.cross_boundary_failures
    )


def test_live_gate_refuses_to_issue_receipt_after_rulespec_failure(
    tmp_path: Path,
) -> None:
    dependency_manifest = tmp_path / "rulespec-dependency.json"
    dependency_manifest.write_text('{"schemaVersion":"1.0"}\n', encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="release-graph validation receipt was not issued",
    ):
        issue_release_graph_validation_receipt(
            valid_bundle(),
            validator=validator_pin(
                tmp_path,
                exit_code=7,
                dependency_manifest=dependency_manifest,
            ),
            dependency_manifest=dependency_manifest,
            receipt_id="urn:ref:release-graph-validation-receipt:test:v1",
            recorded_at="2026-07-29T18:00:00Z",
            recorded_by="urn:ref:agent:test-gate",
            activity="urn:ref:activity:test-release-graph-gate",
        )


def test_skeletal_release_graph_cannot_receive_a_validation_receipt(
    tmp_path: Path,
) -> None:
    dependency_manifest = tmp_path / "rulespec-dependency.json"
    dependency_manifest.write_text('{"schemaVersion":"1.0"}\n', encoding="utf-8")
    bundle = valid_bundle()
    bundle["rulespecGraph"]["@graph"][0] = {
        "@id": RULESPEC_IDENTIFIER,
        "@type": "rkaf:ReferenceResourceRelease",
        "rkaf:membershipMode": "rkaf:completeMembership",
        "prov:hadMember": ["urn:rulespec:concept:missing"],
    }
    graph_digest = rulespec_graph_digest(bundle["rulespecGraph"])
    bundle["rulespecGraphDigest"] = graph_digest
    bundle["validatorReceipt"]["graphDigest"] = graph_digest

    with pytest.raises(
        ValueError,
        match="release-graph validation receipt was not issued",
    ):
        issue_release_graph_validation_receipt(
            bundle,
            validator=release_shape_validator_pin(
                tmp_path,
                dependency_manifest=dependency_manifest,
            ),
            dependency_manifest=dependency_manifest,
            receipt_id=(
                "urn:ref:release-graph-validation-receipt:skeletal:v1"
            ),
            recorded_at="2026-07-29T18:00:00Z",
            recorded_by="urn:ref:agent:test-gate",
            activity="urn:ref:activity:test-release-graph-gate",
        )


def test_receipt_cannot_bind_a_different_dependency_manifest(
    tmp_path: Path,
) -> None:
    validator_manifest = tmp_path / "validator-dependency.json"
    validator_manifest.write_text(
        '{"schemaVersion":"1.0","identity":"validator"}\n',
        encoding="utf-8",
    )
    claimed_manifest = tmp_path / "claimed-dependency.json"
    claimed_manifest.write_text(
        '{"schemaVersion":"1.0","identity":"different"}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="does not match the manifest that loaded",
    ):
        issue_release_graph_validation_receipt(
            valid_bundle(),
            validator=validator_pin(
                tmp_path,
                dependency_manifest=validator_manifest,
            ),
            dependency_manifest=claimed_manifest,
            receipt_id="urn:ref:release-graph-validation-receipt:test:v1",
            recorded_at="2026-07-29T18:00:00Z",
            recorded_by="urn:ref:agent:test-gate",
            activity="urn:ref:activity:test-release-graph-gate",
        )


def test_publication_dependency_must_match_the_validator_manifest(
    tmp_path: Path,
) -> None:
    bundle = valid_bundle()
    publication = bundle["refRecords"][0]
    publication["type"] = "urn:ref:type:PublicationReleaseManifest"
    publication["rulespecDependency"] = {
        "version": "wrong",
        "contractRevision": "0" * 40,
        "evidenceRevision": "0" * 40,
        "constraintDigest": "sha256:" + "0" * 64,
        "conformanceCorpusDigest": "sha256:" + "0" * 64,
        "releaseAvailability": "published",
        "validator": {
            "id": "urn:rulespec:validator:wrong",
            "revision": "0" * 40,
            "digest": "sha256:" + "0" * 64,
        },
    }
    publication["canonicalPayloadDigest"] = binding.canonical_payload_digest(
        publication
    )
    dependency = {
        "rulespecVersion": "0.2.0-pre.9",
        "contractRevision": "1" * 40,
        "evidenceRevision": "2" * 40,
        "constraintDigest": "sha256:" + "1" * 64,
        "conformanceCorpusDigest": "sha256:" + "2" * 64,
        "releaseAvailability": "localUnpublished",
    }
    validator = replace(
        validator_pin(tmp_path),
        component_digest="sha256:" + "3" * 64,
        dependency_manifest=dependency,
    )

    report = validate_release_graph_bundle(bundle, validator=validator)

    assert not report.passed
    assert any(
        "rulespecDependency.version does not match" in failure
        for failure in report.cross_boundary_failures
    )
    assert any(
        "rulespecDependency.validator does not match" in failure
        for failure in report.cross_boundary_failures
    )


def test_installed_package_can_load_embedded_dependency_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        release_graph,
        "DEFAULT_DEPENDENCY_MANIFEST",
        tmp_path / "checkout-assets-are-absent.json",
    )

    manifest = load_rulespec_dependency_manifest()

    assert manifest["rulespecVersion"] == "0.2.0-pre.9"
    assert (
        manifest["contractRevision"]
        == "0eb94257b70783688b55220e7a84dcc61bbd7507"
    )


def test_failure_channels_remain_separate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        binding,
        "validate",
        lambda records: [binding.Diagnostic("REF-TEST", "invalid REF record")],
    )
    bundle = valid_bundle()
    bundle["crossReferences"][0]["rulespecIdentifier"] = "urn:rulespec:missing"

    report = validate_release_graph_bundle(
        bundle,
        validator=validator_pin(tmp_path, exit_code=4),
    )

    assert report.ref_failures == ("REF-TEST: invalid REF record",)
    assert any("exit code 4" in failure for failure in report.rulespec_failures)
    assert any("cannot resolve Rulespec identifier" in failure for failure in report.cross_boundary_failures)
