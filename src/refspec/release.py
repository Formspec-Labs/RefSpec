"""Build and validate fail-closed RefSpec vocabulary releases."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .canonical import (
    CanonicalValueError,
    canonical_digest,
    canonical_json_bytes,
    stable_record,
    validate_stable_record,
    validate_vocabulary_release_identity,
)
from .reference_resource import (
    reference_release_node,
    validate_reference_resource_release,
)
from .rulespec_core import (
    rulespec_core_fixture_pin,
    rulespec_core_release_ref,
)
from .source_fixtures import (
    federal_register_source_fixture_pin,
    load_federal_register_source_fixture,
)


TOP_LEVEL_FIELDS = {
    "schema_version",
    "release_id",
    "release_digest",
    "vocabulary",
    "source_fixture_pin",
    "rulespec_core_fixture",
    "rulespec_core_release",
    "reference_resource_release",
    "concepts",
    "labels",
    "hierarchy",
    "mappings",
    "redirects",
    "source_term_keys",
    "source_term_resolutions",
    "support_records",
    "agent_validation_receipts",
    "baseline_validation_receipts",
    "resolution_policy",
    "coverage",
}
RESOLUTION_STATUSES = {
    "officialTerm",
    "recognizedVariant",
    "sourceLocalOpenTerm",
    "unresolved",
}
TARGETED_STATUSES = {"officialTerm", "recognizedVariant"}
USABLE_BASELINE_RESULTS = {
    "usable_for_search",
    "usable_with_nonblocking_limits",
}
BASELINE_RESULTS = USABLE_BASELINE_RESULTS | {"deferred", "failed"}
REFERENCE_FIELDS = {"id", "digest"}


class ReleaseValidationError(ValueError):
    """A vocabulary release is incomplete, inconsistent, or tampered with."""


def _fail(message: str) -> None:
    raise ReleaseValidationError(message)


def _expect_fields(
    record: Mapping[str, Any],
    expected: set[str],
    *,
    label: str,
) -> None:
    if not isinstance(record, Mapping):
        _fail(f"{label} must be a JSON object")
    actual = set(record)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        _fail(
            f"{label} fields do not match the schema; "
            f"missing={missing}, unexpected={unexpected}"
        )


def _reference_index(
    records: Sequence[Mapping[str, Any]],
    *,
    id_field: str,
    digest_field: str,
    label: str,
) -> dict[str, Mapping[str, Any]]:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        _fail(f"{label} collection must be a JSON array")
    result: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            _fail(f"{label} must be a JSON object")
        identifier = record.get(id_field)
        if not isinstance(identifier, str) or not identifier:
            _fail(f"{label} has no valid {id_field}")
        if identifier in result:
            _fail(f"duplicate {label} identifier: {identifier}")
        if not isinstance(record.get(digest_field), str):
            _fail(f"{label} has no valid {digest_field}")
        result[identifier] = record
    return result


def _resolve_reference(
    reference: Mapping[str, Any],
    index: Mapping[str, Mapping[str, Any]],
    *,
    digest_field: str,
    label: str,
) -> Mapping[str, Any]:
    _expect_fields(reference, REFERENCE_FIELDS, label=f"{label} reference")
    record = index.get(reference.get("id"))
    if record is None:
        _fail(f"{label} reference does not resolve: {reference.get('id')}")
    if record[digest_field] != reference.get("digest"):
        _fail(f"{label} reference has the wrong digest")
    return record


def seal_external_concept(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Seal a publisher-stable concept identifier with its managed content."""

    if "concept_digest" in payload:
        raise ValueError("concept payload must omit concept_digest")
    return {"concept_digest": canonical_digest(payload), **dict(payload)}


def vocabulary_distribution_payload(
    *,
    concepts: Sequence[Mapping[str, Any]],
    labels: Sequence[Mapping[str, Any]],
    hierarchy: Sequence[Mapping[str, Any]],
    mappings: Sequence[Mapping[str, Any]],
    redirects: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the bytes-level content pinned by the Rulespec distribution."""

    return {
        "concepts": list(concepts),
        "labels": list(labels),
        "hierarchy": list(hierarchy),
        "mappings": list(mappings),
        "redirects": list(redirects),
    }


def validate_vocabulary_release(release: Mapping[str, Any]) -> None:
    """Validate nested identities, target cardinality, and reference closure."""

    try:
        validate_vocabulary_release_identity(release)
    except CanonicalValueError as error:
        raise ReleaseValidationError(str(error)) from error
    _expect_fields(release, TOP_LEVEL_FIELDS, label="VocabularyRelease")
    if release["schema_version"] != "refspec-vocabulary-release-v1":
        _fail("unsupported VocabularyRelease schema_version")

    if release["rulespec_core_fixture"] != rulespec_core_fixture_pin():
        _fail("VocabularyRelease uses the wrong Rulespec Core fixture pin")
    _expect_fields(
        release["rulespec_core_release"],
        {"release_id", "release_digest"},
        label="Rulespec Core release reference",
    )
    if release["rulespec_core_release"] != rulespec_core_release_ref():
        _fail("VocabularyRelease uses the wrong Rulespec Core release")
    if release["source_fixture_pin"] != federal_register_source_fixture_pin():
        _fail("VocabularyRelease uses the wrong source fixture pin")
    source_fixture = load_federal_register_source_fixture()
    source_vocabulary = source_fixture["vocabulary"]
    source = source_fixture["source"]
    expected_vocabulary = {
        "scheme_id": source_vocabulary["scheme_id"],
        "title": source_vocabulary["title"],
        "version": source_vocabulary["version"],
        "publisher": source["publisher"],
        "release_scope": source_vocabulary["release_scope"],
        "default_for_source_profiles": source_vocabulary["default_for_source_profiles"],
        "root_ontology": source_vocabulary["root_ontology"],
        "source_distribution": {
            "url": source["url"],
            "issued": source["issued"],
            "digest": source["sha256"],
        },
    }
    if release["vocabulary"] != expected_vocabulary:
        _fail("vocabulary metadata does not match the pinned source fixture")
    reference_release = release["reference_resource_release"]
    try:
        reference_node = reference_release_node(reference_release)
    except CanonicalValueError as error:
        raise ReleaseValidationError(str(error)) from error

    concepts = release["concepts"]
    concept_index = _reference_index(
        concepts,
        id_field="concept_id",
        digest_field="concept_digest",
        label="concept",
    )
    expected_source_concepts = {
        item["concept_id"]: {
            "concept_id": item["concept_id"],
            "scheme_id": source_vocabulary["scheme_id"],
            "preferred_label": item["label"],
            "language": "en",
            "source_locator": item["source_locator"],
        }
        for item in source_fixture["concepts"]
    }
    if set(concept_index) != set(expected_source_concepts):
        _fail("concept set does not match the sealed first-slice fixture")
    for concept in concepts:
        _expect_fields(
            concept,
            {
                "concept_id",
                "concept_digest",
                "scheme_id",
                "preferred_label",
                "language",
                "source_locator",
            },
            label="concept",
        )
        if concept["concept_digest"] != canonical_digest(
            concept, omit_root_fields=("concept_digest",)
        ):
            _fail("concept_digest does not match concept content")
        expected_concept = expected_source_concepts.get(concept["concept_id"])
        if (
            expected_concept is None
            or {key: value for key, value in concept.items() if key != "concept_digest"}
            != expected_concept
        ):
            _fail("concept does not match the pinned source fixture")
    if release["hierarchy"] or release["mappings"]:
        _fail("the sealed first-slice fixture has no hierarchy or mappings")
    expected_labels = [
        stable_record(
            {
                "concept_id": item["concept_id"],
                "label": item["label"],
                "language": "en",
                "label_kind": "preferred",
                "source_locator": item["source_locator"],
            },
            id_field="label_id",
            digest_field="label_digest",
            id_prefix="urn:refspec:label:",
        )
        for item in source_fixture["concepts"]
    ]
    expected_labels.extend(
        stable_record(
            {
                "concept_id": item["target_concept_id"],
                "label": item["label"],
                "language": "en",
                "label_kind": "recognizedVariant",
                "source_locator": item["source_locator"],
            },
            id_field="label_id",
            digest_field="label_digest",
            id_prefix="urn:refspec:label:",
        )
        for item in source_fixture["recognized_variants"]
    )
    expected_redirects = [
        stable_record(
            {
                "source_label": item["label"],
                "language": "en",
                "target_concept_id": item["target_concept_id"],
                "basis": "publisher-authored recognized variant",
                "source_locator": item["source_locator"],
            },
            id_field="redirect_id",
            digest_field="redirect_digest",
            id_prefix="urn:refspec:redirect:",
        )
        for item in source_fixture["recognized_variants"]
    ]
    if release["labels"] != expected_labels:
        _fail("labels do not match the sealed first-slice fixture")
    if release["redirects"] != expected_redirects:
        _fail("redirects do not match the sealed first-slice fixture")
    for record_type, id_field, digest_field, prefix, fields in (
        (
            "labels",
            "label_id",
            "label_digest",
            "urn:refspec:label:",
            {
                "label_id",
                "label_digest",
                "concept_id",
                "label",
                "language",
                "label_kind",
                "source_locator",
            },
        ),
        (
            "redirects",
            "redirect_id",
            "redirect_digest",
            "urn:refspec:redirect:",
            {
                "redirect_id",
                "redirect_digest",
                "source_label",
                "language",
                "target_concept_id",
                "basis",
                "source_locator",
            },
        ),
    ):
        for record in release[record_type]:
            _expect_fields(record, fields, label=record_type)
            try:
                validate_stable_record(
                    record,
                    id_field=id_field,
                    digest_field=digest_field,
                    id_prefix=prefix,
                )
            except CanonicalValueError as error:
                raise ReleaseValidationError(str(error)) from error
            concept_ref = record.get("concept_id") or record.get("target_concept_id")
            if concept_ref is not None and concept_ref not in concept_index:
                _fail(f"{record_type} record refers to a missing concept")

    distribution_payload = vocabulary_distribution_payload(
        concepts=release["concepts"],
        labels=release["labels"],
        hierarchy=release["hierarchy"],
        mappings=release["mappings"],
        redirects=release["redirects"],
    )
    try:
        validate_reference_resource_release(
            reference_release,
            scheme_id=source_vocabulary["scheme_id"],
            release_version=source_vocabulary["version"],
            concept_ids=list(concept_index),
            distribution_payload=distribution_payload,
        )
    except CanonicalValueError as error:
        raise ReleaseValidationError(str(error)) from error

    support_records = release["support_records"]
    support_index = _reference_index(
        support_records,
        id_field="record_id",
        digest_field="record_digest",
        label="support record",
    )
    for record in support_records:
        _expect_fields(
            record,
            {"record_id", "record_digest", "record_type", "payload"},
            label="support record",
        )
        try:
            validate_stable_record(
                record,
                id_field="record_id",
                digest_field="record_digest",
                id_prefix="urn:refspec:support-record:",
            )
        except CanonicalValueError as error:
            raise ReleaseValidationError(str(error)) from error
        if record.get("record_type") in {
            "SourceObservation",
            "SourceObservationCapture",
            "DocumentObservation",
            "SearchRecord",
            "SearchIndex",
        }:
            _fail("document observation capture and search records are outside RefSpec")

    agents = release["agent_validation_receipts"]
    agent_index = _reference_index(
        agents,
        id_field="receipt_id",
        digest_field="receipt_digest",
        label="agent validation receipt",
    )
    reference_release_index = {
        reference_node["@id"]: {
            "record_digest": reference_node["rkaf:referenceReleaseDigest"]
        }
    }
    for agent in agents:
        required_agent_fields = {
            "receipt_id",
            "receipt_digest",
            "attempt_id",
            "owner",
            "target_ref_and_digest",
            "protocol_and_version",
            "input_manifest_ref_and_digest",
            "validator_actor_ref",
            "validator_kind",
            "independence_group",
            "provider_and_model_id",
            "request_contract_ref_and_digest",
            "execution_status",
            "check_outcomes",
            "started_at",
            "completed_at",
        }
        optional_agent_fields = {
            "response_artifact_ref_and_digest",
            "failure_reason",
            "failure_artifact_ref_and_digest",
            "overall_recommendation",
            "advisory_attestation_ref",
        }
        actual_agent_fields = set(agent)
        if not required_agent_fields <= actual_agent_fields or not (
            actual_agent_fields - required_agent_fields <= optional_agent_fields
        ):
            _fail("AgentValidationReceipt fields do not match the schema")
        try:
            validate_stable_record(
                agent,
                id_field="receipt_id",
                digest_field="receipt_digest",
                id_prefix="urn:refspec:agent-validation-receipt:",
            )
        except CanonicalValueError as error:
            raise ReleaseValidationError(str(error)) from error
        _resolve_reference(
            agent["target_ref_and_digest"],
            reference_release_index,
            digest_field="record_digest",
            label="agent target",
        )
        for field in (
            "input_manifest_ref_and_digest",
            "request_contract_ref_and_digest",
        ):
            _resolve_reference(
                agent[field],
                support_index,
                digest_field="record_digest",
                label=field,
            )
        status = agent.get("execution_status")
        if agent.get("validator_kind") not in {"aiModel", "aiAgent"}:
            _fail("agent validation receipt has an unknown validator kind")
        if status == "completed":
            if "response_artifact_ref_and_digest" not in agent:
                _fail("completed agent attempt has no response artifact")
            if agent.get("overall_recommendation") not in {
                "supports",
                "flags",
                "abstains",
            }:
                _fail("completed agent attempt has no valid recommendation")
            if "failure_reason" in agent or "failure_artifact_ref_and_digest" in agent:
                _fail("completed agent attempt contains failure data")
            _resolve_reference(
                agent["response_artifact_ref_and_digest"],
                support_index,
                digest_field="record_digest",
                label="agent response",
            )
        elif status == "failed":
            if not agent.get("failure_reason"):
                _fail("failed agent attempt has no failure reason")
            if "overall_recommendation" in agent:
                _fail("failed agent attempt contains a recommendation")
            if "response_artifact_ref_and_digest" in agent:
                _fail("failed agent attempt contains a response")
            if "failure_artifact_ref_and_digest" in agent:
                _resolve_reference(
                    agent["failure_artifact_ref_and_digest"],
                    support_index,
                    digest_field="record_digest",
                    label="agent failure artifact",
                )
        else:
            _fail("agent validation receipt has an unknown execution status")
        if "advisory_attestation_ref" in agent:
            _resolve_reference(
                agent["advisory_attestation_ref"],
                support_index,
                digest_field="record_digest",
                label="advisory attestation",
            )
        for outcome in agent.get("check_outcomes", []):
            _expect_fields(
                outcome,
                {"check_id", "outcome", "rationale", "evidence_refs"},
                label="agent check outcome",
            )
            if outcome.get("outcome") not in {
                "pass",
                "fail",
                "abstain",
                "not_applicable",
            }:
                _fail("agent check has an unknown outcome")
            for evidence_ref in outcome.get("evidence_refs", []):
                _resolve_reference(
                    evidence_ref,
                    support_index,
                    digest_field="record_digest",
                    label="agent check evidence",
                )

    baselines = release["baseline_validation_receipts"]
    baseline_index = _reference_index(
        baselines,
        id_field="receipt_id",
        digest_field="receipt_digest",
        label="baseline validation receipt",
    )
    for baseline in baselines:
        _expect_fields(
            baseline,
            {
                "receipt_id",
                "receipt_digest",
                "owner",
                "target_profile_and_release_ref",
                "sample_manifest_ref_and_digest",
                "rubric_and_version",
                "aggregation_policy_and_version",
                "deterministic_check_receipt_refs",
                "deterministic_check_outcomes",
                "agent_validation_receipt_refs",
                "aggregate_result",
                "disagreements_and_flags",
                "known_limitations",
                "evaluated_at",
            },
            label="BaselineValidationReceipt",
        )
        try:
            validate_stable_record(
                baseline,
                id_field="receipt_id",
                digest_field="receipt_digest",
                id_prefix="urn:refspec:baseline-validation-receipt:",
            )
        except CanonicalValueError as error:
            raise ReleaseValidationError(str(error)) from error
        _resolve_reference(
            baseline["target_profile_and_release_ref"],
            reference_release_index,
            digest_field="record_digest",
            label="baseline target",
        )
        _resolve_reference(
            baseline["sample_manifest_ref_and_digest"],
            support_index,
            digest_field="record_digest",
            label="baseline sample manifest",
        )
        for reference in baseline["deterministic_check_receipt_refs"]:
            _resolve_reference(
                reference,
                support_index,
                digest_field="record_digest",
                label="deterministic check receipt",
            )
        for outcome in baseline["deterministic_check_outcomes"]:
            _expect_fields(
                outcome,
                {"check_id", "outcome", "receipt_ref"},
                label="deterministic check outcome",
            )
            if outcome["outcome"] not in {
                "pass",
                "fail",
                "abstain",
                "not_applicable",
            }:
                _fail("deterministic check has an unknown outcome")
            _resolve_reference(
                outcome["receipt_ref"],
                support_index,
                digest_field="record_digest",
                label="deterministic check outcome receipt",
            )
        referenced_agents: list[Mapping[str, Any]] = []
        for reference in baseline["agent_validation_receipt_refs"]:
            referenced_agents.append(
                _resolve_reference(
                    reference,
                    agent_index,
                    digest_field="receipt_digest",
                    label="agent validation receipt",
                )
            )
        if baseline["aggregate_result"] not in BASELINE_RESULTS:
            _fail("baseline validation receipt has an unknown aggregate result")
        if baseline["aggregate_result"] in USABLE_BASELINE_RESULTS:
            completed = [
                agent
                for agent in referenced_agents
                if agent["execution_status"] == "completed"
            ]
            groups = {agent["independence_group"] for agent in completed}
            if len(completed) < 2 or len(groups) < 2:
                _fail(
                    "a usable baseline requires two completed independent "
                    "agent attempts"
                )
            if baseline["aggregate_result"] == "usable_for_search" and any(
                agent.get("overall_recommendation") != "supports" for agent in completed
            ):
                _fail(
                    "an unrestricted usable baseline requires supporting "
                    "agent recommendations"
                )

    keys = release["source_term_keys"]
    key_index = _reference_index(
        keys,
        id_field="key_id",
        digest_field="key_digest",
        label="source term key",
    )
    required_key_fields = {
        "key_id",
        "key_digest",
        "source_system_and_profile_version",
        "observation_kind",
        "source_native_path",
        "raw_value",
        "language",
    }
    expected_keys: list[dict[str, Any]] = []
    expected_resolution_by_key_id: dict[str, Mapping[str, Any]] = {}
    for example in source_fixture["resolution_examples"]:
        key_payload = {
            "source_system_and_profile_version": example[
                "source_system_and_profile_version"
            ],
            "observation_kind": example["observation_kind"],
            "source_native_path": example["source_native_path"],
            "raw_value": example["raw_value"],
            "language": example["language"],
        }
        if "source_context_discriminator" in example:
            key_payload["source_context_discriminator"] = example[
                "source_context_discriminator"
            ]
        expected_key = stable_record(
            key_payload,
            id_field="key_id",
            digest_field="key_digest",
            id_prefix="urn:refspec:source-term-key:",
        )
        expected_keys.append(expected_key)
        expected_resolution_by_key_id[expected_key["key_id"]] = example
    if keys != expected_keys:
        _fail("SourceTermKeys do not match the sealed first-slice fixture")
    for key in keys:
        allowed = required_key_fields | {"source_context_discriminator"}
        if set(key) not in (required_key_fields, allowed):
            _fail("SourceTermKey fields do not match the schema")
        try:
            validate_stable_record(
                key,
                id_field="key_id",
                digest_field="key_digest",
                id_prefix="urn:refspec:source-term-key:",
            )
        except CanonicalValueError as error:
            raise ReleaseValidationError(str(error)) from error

    resolutions = release["source_term_resolutions"]
    resolution_index = _reference_index(
        resolutions,
        id_field="resolution_id",
        digest_field="resolution_digest",
        label="source term resolution",
    )
    del resolution_index
    resolution_counts: Counter[str] = Counter()
    resolved_key_ids: list[str] = []
    projection_id = reference_node["@id"]
    projection_digest = reference_node["rkaf:referenceReleaseDigest"]
    for resolution in resolutions:
        required_resolution_fields = {
            "resolution_id",
            "resolution_digest",
            "source_term_key_ref",
            "resolution_status",
            "policy_and_version",
            "reason",
            "evidence_refs",
            "baseline_validation_receipt_ref",
            "optional_review_refs",
        }
        actual_resolution_fields = set(resolution)
        if actual_resolution_fields not in (
            required_resolution_fields,
            required_resolution_fields | {"target_concept_and_release"},
        ):
            _fail("SourceTermResolution fields do not match the schema")
        try:
            validate_stable_record(
                resolution,
                id_field="resolution_id",
                digest_field="resolution_digest",
                id_prefix="urn:refspec:source-term-resolution:",
            )
        except CanonicalValueError as error:
            raise ReleaseValidationError(str(error)) from error
        status = resolution.get("resolution_status")
        if status not in RESOLUTION_STATUSES:
            _fail("SourceTermResolution has an unknown status")
        if not resolution.get("policy_and_version") or not resolution.get("reason"):
            _fail("SourceTermResolution requires policy_and_version and reason")
        key = _resolve_reference(
            resolution["source_term_key_ref"],
            key_index,
            digest_field="key_digest",
            label="source term key",
        )
        resolved_key_ids.append(str(key["key_id"]))
        expected_resolution = expected_resolution_by_key_id[str(key["key_id"])]
        if status != expected_resolution["status"]:
            _fail("resolution status does not match the sealed source example")
        target = resolution.get("target_concept_and_release")
        if status in TARGETED_STATUSES:
            if not isinstance(target, Mapping):
                _fail(f"{status} requires exactly one target")
            _expect_fields(
                target,
                {
                    "concept_id",
                    "reference_resource_release_id",
                    "reference_resource_release_digest",
                },
                label="resolution target",
            )
            if target["concept_id"] not in concept_index:
                _fail("resolution target concept does not resolve")
            if target["concept_id"] != expected_resolution.get("target_concept_id"):
                _fail("resolution target does not match the sealed source example")
            if (
                target["reference_resource_release_id"] != projection_id
                or target["reference_resource_release_digest"] != projection_digest
            ):
                _fail("resolution target uses the wrong reference release")
        elif target is not None:
            _fail(f"{status} forbids a concept target")
        if not resolution.get("evidence_refs"):
            _fail("SourceTermResolution requires evidence")
        for evidence_ref in resolution.get("evidence_refs", []):
            _resolve_reference(
                evidence_ref,
                support_index,
                digest_field="record_digest",
                label="resolution evidence",
            )
        baseline_record = _resolve_reference(
            resolution["baseline_validation_receipt_ref"],
            baseline_index,
            digest_field="receipt_digest",
            label="baseline validation receipt",
        )
        if (
            status in TARGETED_STATUSES
            and baseline_record["aggregate_result"] not in USABLE_BASELINE_RESULTS
        ):
            _fail("a targeted resolution requires a usable baseline")
        for review_ref in resolution.get("optional_review_refs", []):
            _resolve_reference(
                review_ref,
                support_index,
                digest_field="record_digest",
                label="optional review",
            )
        resolution_counts[str(status)] += 1
    if sorted(resolved_key_ids) != sorted(key_index):
        _fail("every SourceTermKey must have exactly one SourceTermResolution")

    coverage = release["coverage"]
    _expect_fields(
        coverage,
        {
            "coverage_id",
            "coverage_digest",
            "source_complete_concept_count",
            "published_concept_count",
            "resolution_key_count",
            "resolution_counts_by_status",
            "included_source_locators",
            "excluded_scope",
        },
        label="VocabularyCoverage",
    )
    try:
        validate_stable_record(
            coverage,
            id_field="coverage_id",
            digest_field="coverage_digest",
            id_prefix="urn:refspec:vocabulary-coverage:",
        )
    except CanonicalValueError as error:
        raise ReleaseValidationError(str(error)) from error
    if coverage["published_concept_count"] != len(concepts):
        _fail("coverage published_concept_count is inconsistent")
    if coverage["resolution_key_count"] != len(keys):
        _fail("coverage resolution_key_count is inconsistent")
    if coverage["resolution_counts_by_status"] != {
        status: resolution_counts.get(status, 0)
        for status in sorted(RESOLUTION_STATUSES)
    }:
        _fail("coverage resolution status counts are inconsistent")
    if (
        coverage["source_complete_concept_count"]
        != source_vocabulary["complete_source_concept_count"]
    ):
        _fail("coverage source concept count is inconsistent")

    vocabulary = release["vocabulary"]
    if vocabulary.get("root_ontology") is not False:
        _fail("the Federal Register thesaurus cannot be the root ontology")
    resolution_policy = release["resolution_policy"]
    _expect_fields(
        resolution_policy,
        {
            "policy_and_version",
            "missing_resolution_behavior",
            "targeted_statuses",
            "untargeted_statuses",
            "human_approval_required",
        },
        label="resolution policy",
    )
    if resolution_policy != {
        "policy_and_version": "federal-register-source-term-resolution-v1",
        "missing_resolution_behavior": "failClosed",
        "targeted_statuses": ["officialTerm", "recognizedVariant"],
        "untargeted_statuses": ["sourceLocalOpenTerm", "unresolved"],
        "human_approval_required": False,
    }:
        _fail("resolution policy does not match the supported first-slice policy")
    rendered = canonical_json_bytes(release).decode("utf-8").lower()
    if "1995" in rendered or "crosswalk" in rendered:
        _fail("the active release must not include the retired vocabulary")
