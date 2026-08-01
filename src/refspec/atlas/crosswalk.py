"""Build a static cross-vocabulary atlas from RefSpec releases."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, Self

from rdflib import Dataset, Graph, Namespace, URIRef
from rdflib import Literal as RdfLiteral
from rdflib.namespace import DCAT, DCTERMS, PROV, RDF, RDFS, SKOS, XSD

from ..canonical import (
    CanonicalValueError,
    canonical_digest,
    canonical_json_bytes,
    stable_record,
    validate_stable_record,
)
from .model import (
    ATLAS_FORMAT_VERSION,
    ATLAS_GENERATION_POLICY,
    CROSSWALK_SELECTION_POLICY,
    VerifiedCrosswalkBundle,
    VerifiedVocabularyRelease,
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    atlas_implementation_pin,
    build_manifest,
    canonical_nquads,
)

ATLAS = Namespace("https://refspec.org/ns/vocabulary-atlas#")
RKAF = Namespace("https://rulespec.org/ns/v1#")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>]+$")
_MAPPING_RELATIONS = frozenset(
    {
        str(SKOS.exactMatch),
        str(SKOS.closeMatch),
        str(SKOS.broadMatch),
        str(SKOS.narrowMatch),
        str(SKOS.relatedMatch),
    }
)
_USABLE_BASELINE_RESULTS = {
    "usable_for_search",
    "usable_with_nonblocking_limits",
}
_MAPPING_VALIDATION_PROTOCOL = "refspec-crosswalk-agent-validation-v1"
_MAPPING_BASELINE_RUBRIC = "refspec-crosswalk-rubric-v1"
_MAPPING_AGGREGATION_POLICY = "refspec-crosswalk-two-independent-v1"
_LABEL_PREDICATES = {
    "preferred": SKOS.prefLabel,
    "recognizedVariant": SKOS.altLabel,
    "alternate": SKOS.altLabel,
    "hidden": SKOS.hiddenLabel,
}
_DCAT_VERSION = URIRef("http://www.w3.org/ns/dcat#version")


def _absolute_iri(value: object, label: str) -> str:
    text = str(value or "")
    if _ABSOLUTE_IRI.fullmatch(text) is None:
        raise VocabularyAtlasError(f"{label} must be an absolute IRI: {text!r}")
    return text


def _reference(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"id", "digest"}:
        raise VocabularyAtlasError(f"{label} must contain exactly id and digest")
    identifier = _absolute_iri(value.get("id"), f"{label} id")
    digest = str(value.get("digest") or "")
    if _SHA256.fullmatch(digest) is None:
        raise VocabularyAtlasError(f"{label} digest is invalid")
    return {"id": identifier, "digest": digest}


def normalize_label(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(text.split())


@dataclass(frozen=True, slots=True)
class MappingCandidate:
    """One model- or agent-generated cross-vocabulary mapping proposal."""

    _record: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        source_concept_id: str,
        source_release_id: str,
        target_concept_id: str,
        target_release_id: str,
        proposed_relation: str,
        generator_kind: Literal["aiModel", "aiAgent"],
        generator_id: str,
        generation_method: str,
        model_id: str,
        model_version: str,
        prompt_template_ref: str,
        temperature: float,
        input_context_hash: str,
        evidence_refs: Sequence[Mapping[str, str]],
        generated_at: str,
        seed: int | None = None,
    ) -> Self:
        payload = {
            "source_concept_id": _absolute_iri(
                source_concept_id, "candidate source_concept_id"
            ),
            "source_release_id": _absolute_iri(
                source_release_id, "candidate source_release_id"
            ),
            "target_concept_id": _absolute_iri(
                target_concept_id, "candidate target_concept_id"
            ),
            "target_release_id": _absolute_iri(
                target_release_id, "candidate target_release_id"
            ),
            "proposed_relation": _absolute_iri(
                proposed_relation, "candidate proposed_relation"
            ),
            "generator_kind": generator_kind,
            "generator_id": str(generator_id).strip(),
            "generation_method": str(generation_method).strip(),
            "model_id": str(model_id).strip(),
            "model_version": str(model_version).strip(),
            "prompt_template_ref": _absolute_iri(
                prompt_template_ref, "candidate prompt_template_ref"
            ),
            "temperature": temperature,
            "input_context_hash": str(input_context_hash),
            "evidence_refs": [
                _reference(value, "candidate evidence reference")
                for value in evidence_refs
            ],
            "generated_at": str(generated_at).strip(),
        }
        if seed is not None:
            payload["seed"] = seed
        if payload["source_release_id"] == payload["target_release_id"]:
            raise VocabularyAtlasError("a crosswalk candidate must cross releases")
        if payload["source_concept_id"] == payload["target_concept_id"]:
            raise VocabularyAtlasError("a crosswalk candidate needs distinct concepts")
        if payload["proposed_relation"] not in _MAPPING_RELATIONS:
            raise VocabularyAtlasError(
                "candidate uses an unsupported SKOS mapping relation"
            )
        if generator_kind not in {"aiModel", "aiAgent"}:
            raise VocabularyAtlasError("generator_kind must be aiModel or aiAgent")
        if any(
            not payload[field]
            for field in (
                "generator_id",
                "generation_method",
                "model_id",
                "model_version",
            )
        ):
            raise VocabularyAtlasError(
                "candidate generator and model fields are required"
            )
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise VocabularyAtlasError("candidate temperature must be numeric")
        if temperature < 0 or temperature > 2:
            raise VocabularyAtlasError("candidate temperature must be between 0 and 2")
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
            raise VocabularyAtlasError("candidate seed must be an integer")
        if _SHA256.fullmatch(payload["input_context_hash"]) is None:
            raise VocabularyAtlasError("candidate input_context_hash is invalid")
        if not payload["evidence_refs"]:
            raise VocabularyAtlasError("a mapping candidate needs evidence")
        if not payload["generated_at"]:
            raise VocabularyAtlasError("candidate generated_at is required")
        sealed = stable_record(
            payload,
            id_field="candidate_id",
            digest_field="candidate_digest",
            id_prefix="urn:refspec:mapping-candidate:",
        )
        return cls(deepcopy(sealed))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        copied = deepcopy(dict(value))
        try:
            validate_stable_record(
                copied,
                id_field="candidate_id",
                digest_field="candidate_digest",
                id_prefix="urn:refspec:mapping-candidate:",
            )
        except CanonicalValueError as error:
            raise VocabularyAtlasError(str(error)) from error
        rebuilt = cls.create(
            source_concept_id=str(copied.get("source_concept_id") or ""),
            source_release_id=str(copied.get("source_release_id") or ""),
            target_concept_id=str(copied.get("target_concept_id") or ""),
            target_release_id=str(copied.get("target_release_id") or ""),
            proposed_relation=str(copied.get("proposed_relation") or ""),
            generator_kind=copied.get("generator_kind"),  # type: ignore[arg-type]
            generator_id=str(copied.get("generator_id") or ""),
            generation_method=str(copied.get("generation_method") or ""),
            model_id=str(copied.get("model_id") or ""),
            model_version=str(copied.get("model_version") or ""),
            prompt_template_ref=str(copied.get("prompt_template_ref") or ""),
            temperature=copied.get("temperature"),  # type: ignore[arg-type]
            input_context_hash=str(copied.get("input_context_hash") or ""),
            evidence_refs=copied.get("evidence_refs") or (),
            generated_at=str(copied.get("generated_at") or ""),
            seed=copied.get("seed"),  # type: ignore[arg-type]
        )
        if rebuilt.to_dict() != copied:
            raise VocabularyAtlasError("mapping candidate has unsupported fields")
        return rebuilt

    @property
    def candidate_id(self) -> str:
        return str(self._record["candidate_id"])

    @property
    def candidate_digest(self) -> str:
        return str(self._record["candidate_digest"])

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(dict(self._record))

    def reference(self) -> dict[str, str]:
        return {"id": self.candidate_id, "digest": self.candidate_digest}


@dataclass(frozen=True, slots=True)
class MappingFeedback:
    """Optional later feedback that does not set mapping eligibility."""

    _record: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        candidate_ref: Mapping[str, str],
        actor_ref: str,
        disposition: Literal["supports", "challenges", "comment"],
        comment: str,
        recorded_at: str,
    ) -> Self:
        payload = {
            "candidate_ref": _reference(candidate_ref, "feedback candidate reference"),
            "actor_ref": _absolute_iri(actor_ref, "feedback actor_ref"),
            "disposition": disposition,
            "comment": str(comment).strip(),
            "recorded_at": str(recorded_at).strip(),
        }
        if disposition not in {"supports", "challenges", "comment"}:
            raise VocabularyAtlasError("feedback disposition is unsupported")
        if not payload["comment"] or not payload["recorded_at"]:
            raise VocabularyAtlasError("feedback comment and recorded_at are required")
        sealed = stable_record(
            payload,
            id_field="feedback_id",
            digest_field="feedback_digest",
            id_prefix="urn:refspec:mapping-feedback:",
        )
        return cls(deepcopy(sealed))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        copied = deepcopy(dict(value))
        try:
            validate_stable_record(
                copied,
                id_field="feedback_id",
                digest_field="feedback_digest",
                id_prefix="urn:refspec:mapping-feedback:",
            )
        except CanonicalValueError as error:
            raise VocabularyAtlasError(str(error)) from error
        rebuilt = cls.create(
            candidate_ref=copied.get("candidate_ref") or {},
            actor_ref=str(copied.get("actor_ref") or ""),
            disposition=copied.get("disposition"),  # type: ignore[arg-type]
            comment=str(copied.get("comment") or ""),
            recorded_at=str(copied.get("recorded_at") or ""),
        )
        if rebuilt.to_dict() != copied:
            raise VocabularyAtlasError("mapping feedback has unsupported fields")
        return rebuilt

    @property
    def feedback_id(self) -> str:
        return str(self._record["feedback_id"])

    @property
    def feedback_digest(self) -> str:
        return str(self._record["feedback_digest"])

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(dict(self._record))


def _required_text(record: Mapping[str, Any], field: str, label: str) -> str:
    value = str(record.get(field) or "").strip()
    if not value:
        raise VocabularyAtlasError(f"{label} {field} is required")
    return value


def _reference_list(
    value: object, label: str, *, nonempty: bool = False
) -> list[dict[str, str]]:
    if not isinstance(value, list) or (nonempty and not value):
        requirement = "a nonempty JSON array" if nonempty else "a JSON array"
        raise VocabularyAtlasError(f"{label} must be {requirement}")
    references = [_reference(item, label) for item in value]
    if len({(item["id"], item["digest"]) for item in references}) != len(references):
        raise VocabularyAtlasError(f"{label} repeats a reference")
    return references


def _check_outcomes(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not value:
        raise VocabularyAtlasError(f"{label} must be a nonempty JSON array")
    results: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise VocabularyAtlasError(f"{label} entries must be JSON objects")
        required = {"check_id", "outcome", "rationale"}
        allowed = required | {"evidence_refs", "receipt_ref"}
        if not required <= set(item) or not set(item) <= allowed:
            raise VocabularyAtlasError(f"{label} entry fields are unsupported")
        _required_text(item, "check_id", label)
        _required_text(item, "rationale", label)
        if item.get("outcome") not in {"pass", "fail", "abstain", "not_applicable"}:
            raise VocabularyAtlasError(f"{label} outcome is unsupported")
        if "evidence_refs" in item:
            _reference_list(item["evidence_refs"], f"{label} evidence_refs")
        if "receipt_ref" in item:
            _reference(item["receipt_ref"], f"{label} receipt_ref")
        results.append(item)
    return results


def _validated_agent_receipts(
    values: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    receipts: dict[str, Mapping[str, Any]] = {}
    for value in values:
        copied = deepcopy(dict(value))
        required_fields = {
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
        optional_fields = {
            "response_artifact_ref_and_digest",
            "failure_reason",
            "failure_artifact_ref_and_digest",
            "overall_recommendation",
            "advisory_attestation_ref",
        }
        if not required_fields <= set(copied) or not set(copied) <= (
            required_fields | optional_fields
        ):
            raise VocabularyAtlasError("agent receipt fields differ from v1")
        try:
            validate_stable_record(
                copied,
                id_field="receipt_id",
                digest_field="receipt_digest",
                id_prefix="urn:refspec:agent-validation-receipt:",
            )
        except CanonicalValueError as error:
            raise VocabularyAtlasError(str(error)) from error
        identifier = str(copied["receipt_id"])
        if identifier in receipts:
            raise VocabularyAtlasError(f"duplicate agent receipt: {identifier}")
        if copied.get("validator_kind") not in {"aiModel", "aiAgent"}:
            raise VocabularyAtlasError("mapping validator must be an AI model or agent")
        _reference(copied.get("target_ref_and_digest"), "agent target reference")
        _reference(
            copied.get("input_manifest_ref_and_digest"),
            "agent input manifest reference",
        )
        _reference(
            copied.get("request_contract_ref_and_digest"),
            "agent request contract reference",
        )
        for field in (
            "attempt_id",
            "owner",
            "independence_group",
            "provider_and_model_id",
            "started_at",
            "completed_at",
        ):
            _required_text(copied, field, "agent receipt")
        _absolute_iri(copied.get("validator_actor_ref"), "validator_actor_ref")
        if copied.get("protocol_and_version") != _MAPPING_VALIDATION_PROTOCOL:
            raise VocabularyAtlasError("agent receipt uses another protocol")
        checks = _check_outcomes(copied.get("check_outcomes"), "agent checks")
        status = copied.get("execution_status")
        recommendation = copied.get("overall_recommendation")
        if status == "completed":
            if recommendation not in {"supports", "flags", "abstains"}:
                raise VocabularyAtlasError(
                    "completed agent receipt needs a supported recommendation"
                )
            _reference(
                copied.get("response_artifact_ref_and_digest"),
                "agent response artifact reference",
            )
            if recommendation == "supports" and any(
                check.get("outcome") not in {"pass", "not_applicable"}
                for check in checks
            ):
                raise VocabularyAtlasError(
                    "a supporting agent receipt has a non-passing check"
                )
            if (
                "failure_reason" in copied
                or "failure_artifact_ref_and_digest" in copied
            ):
                raise VocabularyAtlasError(
                    "completed agent receipt contains failure data"
                )
        elif status == "failed":
            if (
                recommendation is not None
                or not str(copied.get("failure_reason") or "").strip()
                or "response_artifact_ref_and_digest" in copied
            ):
                raise VocabularyAtlasError(
                    "failed agent receipt needs a reason and no response or recommendation"
                )
            if "failure_artifact_ref_and_digest" in copied:
                _reference(
                    copied["failure_artifact_ref_and_digest"],
                    "agent failure artifact reference",
                )
        else:
            raise VocabularyAtlasError("agent execution_status is unsupported")
        if "advisory_attestation_ref" in copied:
            _reference(copied["advisory_attestation_ref"], "advisory attestation")
        receipts[identifier] = copied
    return receipts


def _validated_baselines(
    values: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    receipts: dict[str, Mapping[str, Any]] = {}
    for value in values:
        copied = deepcopy(dict(value))
        expected_fields = {
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
        }
        if set(copied) != expected_fields:
            raise VocabularyAtlasError("baseline receipt fields differ from v1")
        try:
            validate_stable_record(
                copied,
                id_field="receipt_id",
                digest_field="receipt_digest",
                id_prefix="urn:refspec:baseline-validation-receipt:",
            )
        except CanonicalValueError as error:
            raise VocabularyAtlasError(str(error)) from error
        identifier = str(copied["receipt_id"])
        if identifier in receipts:
            raise VocabularyAtlasError(f"duplicate baseline receipt: {identifier}")
        _reference(
            copied.get("target_profile_and_release_ref"),
            "baseline target reference",
        )
        _reference(
            copied.get("sample_manifest_ref_and_digest"),
            "baseline sample manifest reference",
        )
        _required_text(copied, "owner", "baseline receipt")
        _required_text(copied, "evaluated_at", "baseline receipt")
        if copied.get("rubric_and_version") != _MAPPING_BASELINE_RUBRIC:
            raise VocabularyAtlasError("baseline receipt uses another rubric")
        if copied.get("aggregation_policy_and_version") != _MAPPING_AGGREGATION_POLICY:
            raise VocabularyAtlasError(
                "baseline receipt uses another aggregation policy"
            )
        _reference_list(
            copied.get("deterministic_check_receipt_refs"),
            "baseline deterministic receipt references",
            nonempty=True,
        )
        _check_outcomes(
            copied.get("deterministic_check_outcomes"),
            "baseline deterministic checks",
        )
        _reference_list(
            copied.get("agent_validation_receipt_refs"),
            "baseline agent references",
        )
        for field in ("disagreements_and_flags", "known_limitations"):
            values_list = copied.get(field)
            if not isinstance(values_list, list) or any(
                not isinstance(item, str) for item in values_list
            ):
                raise VocabularyAtlasError(f"baseline {field} must be a string array")
        receipts[identifier] = copied
    return receipts


def _qualify_candidates(
    candidates: Mapping[str, MappingCandidate],
    agents: Mapping[str, Mapping[str, Any]],
    baselines: Mapping[str, Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    qualified: dict[str, Mapping[str, Any]] = {}
    baseline_by_candidate: dict[str, str] = {}
    for baseline_id, baseline in baselines.items():
        target = _reference(
            baseline["target_profile_and_release_ref"],
            "baseline target reference",
        )
        candidate = candidates.get(target["id"])
        if candidate is None or candidate.candidate_digest != target["digest"]:
            raise VocabularyAtlasError(
                f"baseline {baseline_id} does not target an exact mapping candidate"
            )
        if candidate.candidate_id in baseline_by_candidate:
            raise VocabularyAtlasError(
                f"candidate {candidate.candidate_id} has multiple baseline receipts"
            )
        baseline_by_candidate[candidate.candidate_id] = baseline_id

        references = baseline.get("agent_validation_receipt_refs")
        if not isinstance(references, list):
            raise VocabularyAtlasError("baseline agent references must be a JSON array")
        if len({str(value) for value in references}) != len(references):
            raise VocabularyAtlasError("baseline repeats an agent receipt reference")
        selected_agents: list[Mapping[str, Any]] = []
        for reference_value in references:
            reference = _reference(reference_value, "baseline agent reference")
            agent = agents.get(reference["id"])
            if agent is None or agent.get("receipt_digest") != reference["digest"]:
                raise VocabularyAtlasError(
                    f"baseline {baseline_id} has a dangling agent receipt"
                )
            agent_target = _reference(
                agent["target_ref_and_digest"],
                "agent target reference",
            )
            if agent_target != candidate.reference():
                raise VocabularyAtlasError(
                    f"agent receipt {agent['receipt_id']} targets another candidate"
                )
            selected_agents.append(agent)

        aggregate = str(baseline.get("aggregate_result") or "")
        if aggregate not in {
            *_USABLE_BASELINE_RESULTS,
            "deferred",
            "failed",
        }:
            raise VocabularyAtlasError("baseline aggregate_result is unsupported")
        if aggregate not in _USABLE_BASELINE_RESULTS:
            continue
        deterministic = baseline.get("deterministic_check_outcomes")
        if not isinstance(deterministic, list) or not deterministic:
            raise VocabularyAtlasError(
                "a usable mapping baseline needs deterministic checks"
            )
        if any(
            not isinstance(check, Mapping)
            or check.get("outcome") not in {"pass", "not_applicable"}
            for check in deterministic
        ):
            raise VocabularyAtlasError(
                "a usable mapping baseline has a non-passing deterministic check"
            )
        supporting = [
            agent
            for agent in selected_agents
            if agent.get("execution_status") == "completed"
            and agent.get("overall_recommendation") == "supports"
        ]
        groups = {str(agent.get("independence_group") or "") for agent in supporting}
        actors = {str(agent.get("validator_actor_ref") or "") for agent in supporting}
        providers = {
            str(agent.get("provider_and_model_id") or "") for agent in supporting
        }
        input_manifests = {
            tuple(
                sorted(
                    _reference(
                        agent["input_manifest_ref_and_digest"],
                        "agent input manifest reference",
                    ).items()
                )
            )
            for agent in supporting
        }
        request_contracts = {
            tuple(
                sorted(
                    _reference(
                        agent["request_contract_ref_and_digest"],
                        "agent request contract reference",
                    ).items()
                )
            )
            for agent in supporting
        }
        if (
            len(supporting) < 2
            or len(groups - {""}) < 2
            or len(actors - {""}) < 2
            or len(providers - {""}) < 2
        ):
            raise VocabularyAtlasError(
                "a usable mapping baseline needs distinct groups, actors, and providers"
            )
        if len(input_manifests) != 1 or len(request_contracts) != 1:
            raise VocabularyAtlasError(
                "independent validators must use the same sealed input and request"
            )
        qualified[candidate.candidate_id] = baseline
    return qualified


def _stable_iri(kind: str, *values: object) -> URIRef:
    digest = canonical_digest({"kind": kind, "values": list(values)})
    return URIRef(
        f"urn:refspec:vocabulary-atlas:{kind}:{digest.removeprefix('sha256:')}"
    )


def _project_release(
    graph,
    release: VerifiedVocabularyRelease,
    *,
    release_by_concept: dict[str, str],
    reference_release_by_release: dict[str, str],
    scheme_by_concept: dict[str, str],
    preferred_labels: dict[str, list[tuple[str, str, str]]],
) -> None:
    record = release.record()
    vocabulary = record["vocabulary"]
    release_node = URIRef(release.release_id)
    reference_release = URIRef(release.reference_release_id)
    scheme_id = str(vocabulary["scheme_id"])
    scheme = URIRef(scheme_id)
    graph.add((release_node, RDF.type, ATLAS.ManagedVocabularyRelease))
    graph.add((release_node, DCTERMS.isVersionOf, scheme))
    graph.add((release_node, _DCAT_VERSION, RdfLiteral(str(vocabulary["version"]))))
    graph.add((release_node, ATLAS.releaseDigest, RdfLiteral(release.release_digest)))
    graph.add((release_node, ATLAS.membershipMode, RKAF.completeMembership))
    graph.add((release_node, ATLAS.referenceResourceRelease, reference_release))
    reference_graph = Graph()
    reference_graph.parse(
        data=canonical_json_bytes(record["reference_resource_release"]).decode("utf-8"),
        format="json-ld",
    )
    for triple in reference_graph:
        graph.add(triple)
    reference_release_by_release[release.release_id] = release.reference_release_id
    graph.add((scheme, RDF.type, SKOS.ConceptScheme))
    graph.add(
        (scheme, SKOS.prefLabel, RdfLiteral(str(vocabulary.get("title") or scheme_id)))
    )

    for concept in record["concepts"]:
        concept_id = str(concept["concept_id"])
        if concept_id in release_by_concept:
            raise VocabularyAtlasError(
                f"concept appears in multiple atlas releases: {concept_id}"
            )
        release_by_concept[concept_id] = release.release_id
        scheme_by_concept[concept_id] = scheme_id
        node = URIRef(concept_id)
        graph.add((node, RDF.type, SKOS.Concept))
        graph.add((node, SKOS.inScheme, scheme))
        graph.add((node, ATLAS.memberOf, release_node))
        graph.add((release_node, ATLAS.hasMember, node))
        graph.add((reference_release, PROV.hadMember, node))
        graph.add(
            (node, ATLAS.sourceRecordDigest, RdfLiteral(concept["concept_digest"]))
        )

    for label in record["labels"]:
        concept_id = str(label["concept_id"])
        predicate = _LABEL_PREDICATES.get(str(label["label_kind"]))
        if predicate is None:
            raise VocabularyAtlasError(
                f"unsupported label_kind: {label['label_kind']!r}"
            )
        literal = RdfLiteral(str(label["label"]), lang=str(label["language"]))
        graph.add((URIRef(concept_id), predicate, literal))
        label_node = URIRef(str(label["label_id"]))
        graph.add((label_node, RDF.type, ATLAS.VocabularyLabel))
        graph.add((label_node, ATLAS.member, URIRef(concept_id)))
        graph.add((label_node, ATLAS.memberRelease, release_node))
        graph.add((label_node, ATLAS.semanticProperty, predicate))
        graph.add((label_node, RDF.value, literal))
        graph.add(
            (label_node, ATLAS.normalizedLabel, RdfLiteral(normalize_label(literal)))
        )
        graph.add(
            (label_node, ATLAS.sourceRecordDigest, RdfLiteral(label["label_digest"]))
        )
        if label["label_kind"] == "preferred":
            preferred_labels[normalize_label(literal)].append(
                (concept_id, release.release_id, str(label["label_id"]))
            )

    relation_predicates = {
        "broader": SKOS.broader,
        "narrower": SKOS.narrower,
        "related": SKOS.related,
        str(SKOS.broader): SKOS.broader,
        str(SKOS.narrower): SKOS.narrower,
        str(SKOS.related): SKOS.related,
    }
    for relation in record["hierarchy"]:
        if not isinstance(relation, Mapping):
            raise VocabularyAtlasError("hierarchy records must be JSON objects")
        source = str(relation.get("source_concept_id") or "")
        target = str(relation.get("target_concept_id") or "")
        predicate = relation_predicates.get(str(relation.get("relation") or ""))
        if source not in release_by_concept or target not in release_by_concept:
            raise VocabularyAtlasError("hierarchy endpoint is outside its release")
        if scheme_by_concept[source] != scheme_by_concept[target] or predicate is None:
            raise VocabularyAtlasError(
                "hierarchy must be a supported within-scheme relation"
            )
        graph.add((URIRef(source), predicate, URIRef(target)))

    if record["mappings"]:
        raise VocabularyAtlasError(
            "embedded release mappings are not yet normalized; supply mapping candidates and validation receipts"
        )
    for redirect in record["redirects"]:
        node = URIRef(str(redirect["redirect_id"]))
        graph.add((node, RDF.type, ATLAS.VocabularyRedirect))
        graph.add((node, RDFS.label, RdfLiteral(str(redirect["source_label"]))))
        graph.add((node, ATLAS.redirectsTo, URIRef(str(redirect["target_concept_id"]))))
        graph.add(
            (node, ATLAS.sourceRecordDigest, RdfLiteral(redirect["redirect_digest"]))
        )


def build_vocabulary_atlas(
    releases: Sequence[VerifiedVocabularyRelease],
    *,
    mapping_candidates: Sequence[MappingCandidate] = (),
    agent_validation_receipts: Sequence[Mapping[str, Any]] = (),
    baseline_validation_receipts: Sequence[Mapping[str, Any]] = (),
    feedback: Sequence[MappingFeedback] = (),
    crosswalk_bundle: VerifiedCrosswalkBundle | None = None,
) -> VocabularyAtlasAsset:
    """Build a deterministic two-graph vocabulary and crosswalk asset."""

    selected = tuple(releases)
    if not selected:
        raise VocabularyAtlasError("an atlas needs at least one VocabularyRelease")
    if len({release.release_id for release in selected}) != len(selected):
        raise VocabularyAtlasError("atlas releases contain a duplicate release_id")

    candidates: dict[str, MappingCandidate] = {}
    for candidate in mapping_candidates:
        if candidate.candidate_id in candidates:
            raise VocabularyAtlasError(
                f"duplicate mapping candidate: {candidate.candidate_id}"
            )
        candidates[candidate.candidate_id] = candidate
    agents = _validated_agent_receipts(agent_validation_receipts)
    baselines = _validated_baselines(baseline_validation_receipts)
    for receipt_id, receipt in agents.items():
        target = _reference(receipt["target_ref_and_digest"], "agent target reference")
        candidate = candidates.get(target["id"])
        if candidate is None or candidate.candidate_digest != target["digest"]:
            raise VocabularyAtlasError(
                f"agent receipt {receipt_id} does not target an exact mapping candidate"
            )
    qualified = _qualify_candidates(candidates, agents, baselines)

    feedback_by_id: dict[str, MappingFeedback] = {}
    for item in feedback:
        if item.feedback_id in feedback_by_id:
            raise VocabularyAtlasError(
                f"duplicate mapping feedback: {item.feedback_id}"
            )
        candidate_ref = _reference(
            item.to_dict()["candidate_ref"],
            "feedback candidate reference",
        )
        candidate = candidates.get(candidate_ref["id"])
        if candidate is None or candidate.candidate_digest != candidate_ref["digest"]:
            raise VocabularyAtlasError("mapping feedback targets an unknown candidate")
        feedback_by_id[item.feedback_id] = item

    if crosswalk_bundle is not None:
        bundle = crosswalk_bundle.record()
        represented = {
            "schema_version": bundle["schema_version"],
            "mapping_candidates": [item.to_dict() for item in mapping_candidates],
            "agent_validation_receipts": [
                dict(item) for item in agent_validation_receipts
            ],
            "baseline_validation_receipts": [
                dict(item) for item in baseline_validation_receipts
            ],
            "feedback": [item.to_dict() for item in feedback],
        }
        if bundle != represented:
            raise VocabularyAtlasError(
                "crosswalk bundle does not exactly match the supplied records"
            )

    policies = {
        "candidateSelection": CROSSWALK_SELECTION_POLICY,
        "generation": ATLAS_GENERATION_POLICY,
    }
    implementation = atlas_implementation_pin()
    generation_input = {
        "schemaVersion": ATLAS_FORMAT_VERSION,
        "policies": policies,
        "implementation": implementation,
        "releases": [
            release.pin()
            for release in sorted(selected, key=lambda item: item.release_id)
        ],
        "mappingCandidates": [candidates[key].to_dict() for key in sorted(candidates)],
        "agentValidationReceipts": [agents[key] for key in sorted(agents)],
        "baselineValidationReceipts": [baselines[key] for key in sorted(baselines)],
        "feedback": [feedback_by_id[key].to_dict() for key in sorted(feedback_by_id)],
        "sourceInputs": [crosswalk_bundle.pin()] if crosswalk_bundle else [],
    }
    generation_digest = canonical_digest(generation_input)
    suffix = generation_digest.removeprefix("sha256:")
    asserted_graph_iri = f"urn:refspec:vocabulary-atlas:{suffix}"
    analysis_graph_iri = f"urn:refspec:vocabulary-atlas-analysis:{suffix}"
    dataset = Dataset(default_union=False)
    dataset.bind("atlas", ATLAS)
    dataset.bind("dcat", DCAT)
    dataset.bind("dcterms", DCTERMS)
    dataset.bind("prov", PROV)
    dataset.bind("rkaf", RKAF)
    dataset.bind("skos", SKOS)
    asserted = dataset.graph(URIRef(asserted_graph_iri))
    analysis = dataset.graph(URIRef(analysis_graph_iri))
    generation = URIRef(asserted_graph_iri)
    analysis_generation = URIRef(analysis_graph_iri)
    asserted.add((generation, RDF.type, ATLAS.AtlasGeneration))
    asserted.add((generation, ATLAS.analysisGraph, analysis_generation))
    asserted.add((generation, ATLAS.generationDigest, RdfLiteral(generation_digest)))
    analysis.add((analysis_generation, RDF.type, ATLAS.AnalysisGeneration))
    analysis.add((analysis_generation, PROV.wasDerivedFrom, generation))

    release_by_concept: dict[str, str] = {}
    reference_release_by_release: dict[str, str] = {}
    scheme_by_concept: dict[str, str] = {}
    preferred_labels: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for release in sorted(selected, key=lambda item: item.release_id):
        _project_release(
            asserted,
            release,
            release_by_concept=release_by_concept,
            reference_release_by_release=reference_release_by_release,
            scheme_by_concept=scheme_by_concept,
            preferred_labels=preferred_labels,
        )
        pin = release.pin()
        pin_node = _stable_iri(
            "input",
            pin["identifier"],
            pin["releaseDigest"],
            pin["fileDigest"],
        )
        asserted.add((pin_node, RDF.type, ATLAS.InputPin))
        asserted.add((pin_node, ATLAS.inputIdentifier, URIRef(pin["identifier"])))
        asserted.add((pin_node, ATLAS.releaseDigest, RdfLiteral(pin["releaseDigest"])))
        asserted.add((pin_node, ATLAS.fileDigest, RdfLiteral(pin["fileDigest"])))
        asserted.add(
            (
                pin_node,
                ATLAS.referenceResourceRelease,
                URIRef(pin["referenceReleaseId"]),
            )
        )
        asserted.add(
            (
                pin_node,
                RKAF.referenceReleaseDigest,
                RdfLiteral(pin["referenceReleaseDigest"]),
            )
        )
        asserted.add((generation, PROV.used, pin_node))

    cluster_count = 0
    for normalized, values in sorted(preferred_labels.items()):
        schemes = {scheme_by_concept[concept] for concept, _, _ in values}
        if len(schemes) < 2:
            continue
        cluster = _stable_iri("label-cluster", normalized)
        analysis.add((cluster, RDF.type, ATLAS.LabelCluster))
        analysis.add((cluster, ATLAS.normalizedLabel, RdfLiteral(normalized)))
        for concept, release, label_id in sorted(values):
            analysis.add((cluster, ATLAS.member, URIRef(concept)))
            analysis.add((cluster, ATLAS.memberRelease, URIRef(release)))
            analysis.add((cluster, ATLAS.sourceLabel, URIRef(label_id)))
        cluster_count += 1

    for candidate_id, candidate in sorted(candidates.items()):
        record = candidate.to_dict()
        source = str(record["source_concept_id"])
        target = str(record["target_concept_id"])
        if release_by_concept.get(source) != record["source_release_id"]:
            raise VocabularyAtlasError(
                f"candidate {candidate_id} source is outside its exact release"
            )
        if release_by_concept.get(target) != record["target_release_id"]:
            raise VocabularyAtlasError(
                f"candidate {candidate_id} target is outside its exact release"
            )
        node = URIRef(candidate_id)
        analysis.add((node, RDF.type, ATLAS.ConceptMappingCandidate))
        analysis.add(
            (node, ATLAS.candidateDigest, RdfLiteral(candidate.candidate_digest))
        )
        analysis.add((node, ATLAS.sourceConcept, URIRef(source)))
        analysis.add((node, ATLAS.sourceRelease, URIRef(record["source_release_id"])))
        analysis.add((node, ATLAS.targetConcept, URIRef(target)))
        analysis.add((node, ATLAS.targetRelease, URIRef(record["target_release_id"])))
        analysis.add(
            (node, ATLAS.proposedRelation, URIRef(record["proposed_relation"]))
        )
        analysis.add((node, ATLAS.generatorKind, ATLAS[str(record["generator_kind"])]))
        analysis.add((node, ATLAS.generatorId, RdfLiteral(record["generator_id"])))
        analysis.add(
            (node, ATLAS.generationMethod, RdfLiteral(record["generation_method"]))
        )
        analysis.add(
            (
                node,
                PROV.generatedAtTime,
                RdfLiteral(record["generated_at"], datatype=XSD.dateTime),
            )
        )
        analysis.add((node, RKAF.assertionOrigin, RKAF.aiSuggested))
        analysis.add((node, ATLAS.verificationStatus, ATLAS.unverified))
        analysis.add((node, RKAF.usageEligibility, RKAF.notEligible))
        analysis.add((node, ATLAS.selectionDisposition, ATLAS.notSelected))
        analysis.add(
            (
                node,
                ATLAS.selectionPolicy,
                RdfLiteral(CROSSWALK_SELECTION_POLICY),
            )
        )
        for evidence in record["evidence_refs"]:
            analysis.add((node, ATLAS.evidence, URIRef(evidence["id"])))

        baseline = qualified.get(candidate_id)
        if baseline is None:
            continue
        baseline_node = URIRef(str(baseline["receipt_id"]))
        analysis.remove((node, RKAF.usageEligibility, RKAF.notEligible))
        analysis.remove((node, ATLAS.selectionDisposition, ATLAS.notSelected))
        analysis.add((node, RKAF.usageEligibility, RKAF.searchOnly))
        analysis.add((node, ATLAS.selectionDisposition, ATLAS.selectedForSearchOnly))
        analysis.add((node, ATLAS.qualifiedBy, baseline_node))
        mapping = _stable_iri(
            "search-only-mapping",
            candidate_id,
            baseline["receipt_id"],
        )
        lineage = _stable_iri(
            "ai-lineage",
            candidate_id,
        )
        analysis.add((lineage, RDF.type, RKAF.AILineage))
        analysis.add((lineage, RKAF.modelId, RdfLiteral(record["model_id"])))
        analysis.add((lineage, RKAF.modelVersion, RdfLiteral(record["model_version"])))
        analysis.add(
            (lineage, RKAF.promptTemplateRef, URIRef(record["prompt_template_ref"]))
        )
        analysis.add(
            (
                lineage,
                RKAF.temperature,
                RdfLiteral(str(record["temperature"]), datatype=XSD.float),
            )
        )
        analysis.add(
            (lineage, RKAF.inputContextHash, RdfLiteral(record["input_context_hash"]))
        )
        if "seed" in record:
            analysis.add(
                (
                    lineage,
                    RKAF.seed,
                    RdfLiteral(record["seed"], datatype=XSD.integer),
                )
            )
        analysis.add((node, RDF.type, PROV.Entity))
        asserted.add((mapping, RDF.type, RKAF.ConceptMapping))
        asserted.add((mapping, RKAF.assertsSubject, URIRef(source)))
        asserted.add(
            (mapping, RKAF.assertsPredicate, URIRef(record["proposed_relation"]))
        )
        asserted.add((mapping, RKAF.assertsObject, URIRef(target)))
        asserted.add(
            (
                mapping,
                RKAF.sourceConceptRelease,
                URIRef(reference_release_by_release[record["source_release_id"]]),
            )
        )
        asserted.add(
            (
                mapping,
                RKAF.targetConceptRelease,
                URIRef(reference_release_by_release[record["target_release_id"]]),
            )
        )
        asserted.add((mapping, RKAF.usageEligibility, RKAF.searchOnly))
        asserted.add((mapping, RKAF.assertionOrigin, RKAF.aiSuggested))
        asserted.add((mapping, RKAF.epistemicBasis, RKAF.statisticalInference))
        asserted.add((mapping, RKAF.assertionPolarity, RKAF.affirmed))
        asserted.add((mapping, RKAF.hasAILineage, lineage))
        asserted.add((mapping, PROV.wasDerivedFrom, node))
        asserted.add((mapping, ATLAS.verificationStatus, ATLAS.unverified))
        asserted.add(
            (
                mapping,
                ATLAS.selectionPolicy,
                RdfLiteral(CROSSWALK_SELECTION_POLICY),
            )
        )
        asserted.add((mapping, ATLAS.qualifiedFrom, node))
        asserted.add((mapping, ATLAS.qualifiedBy, baseline_node))
        evidence_binding = _stable_iri(
            "evidence-binding",
            mapping,
            candidate_id,
            baseline["receipt_id"],
        )
        asserted.add((evidence_binding, RDF.type, RKAF.EvidenceBinding))
        asserted.add((evidence_binding, RKAF.bindsAssertion, mapping))
        asserted.add(
            (
                evidence_binding,
                RKAF.noEvidenceReason,
                RKAF["declared-hypothesis"],
            )
        )

    for receipt_id, receipt in sorted(agents.items()):
        node = URIRef(receipt_id)
        target = _reference(receipt["target_ref_and_digest"], "agent target reference")
        analysis.add((node, RDF.type, ATLAS.AgentValidationReceipt))
        analysis.add((node, ATLAS.receiptDigest, RdfLiteral(receipt["receipt_digest"])))
        analysis.add((node, ATLAS.validates, URIRef(target["id"])))
        analysis.add((node, ATLAS.validatorKind, ATLAS[str(receipt["validator_kind"])]))
        analysis.add(
            (node, ATLAS.independenceGroup, RdfLiteral(receipt["independence_group"]))
        )
        analysis.add(
            (node, ATLAS.executionStatus, RdfLiteral(receipt["execution_status"]))
        )
        if receipt.get("overall_recommendation") is not None:
            analysis.add(
                (
                    node,
                    ATLAS.recommendation,
                    RdfLiteral(receipt["overall_recommendation"]),
                )
            )

    for receipt_id, receipt in sorted(baselines.items()):
        node = URIRef(receipt_id)
        target = _reference(
            receipt["target_profile_and_release_ref"],
            "baseline target reference",
        )
        analysis.add((node, RDF.type, ATLAS.BaselineValidationReceipt))
        analysis.add((node, ATLAS.receiptDigest, RdfLiteral(receipt["receipt_digest"])))
        analysis.add((node, ATLAS.validates, URIRef(target["id"])))
        analysis.add(
            (node, ATLAS.aggregateResult, RdfLiteral(receipt["aggregate_result"]))
        )
        for reference_value in receipt["agent_validation_receipt_refs"]:
            reference = _reference(reference_value, "baseline agent reference")
            analysis.add((node, ATLAS.usesValidation, URIRef(reference["id"])))

    for feedback_id, item in sorted(feedback_by_id.items()):
        record = item.to_dict()
        node = URIRef(feedback_id)
        analysis.add((node, RDF.type, ATLAS.MappingFeedback))
        analysis.add((node, ATLAS.feedbackDigest, RdfLiteral(item.feedback_digest)))
        analysis.add((node, ATLAS.feedbackOn, URIRef(record["candidate_ref"]["id"])))
        analysis.add((node, ATLAS.feedbackActor, URIRef(record["actor_ref"])))
        analysis.add(
            (node, ATLAS.feedbackDisposition, RdfLiteral(record["disposition"]))
        )
        analysis.add((node, RDFS.comment, RdfLiteral(record["comment"])))
        analysis.add(
            (
                node,
                PROV.generatedAtTime,
                RdfLiteral(record["recorded_at"], datatype=XSD.dateTime),
            )
        )

    payload = canonical_nquads(dataset)
    counts = {
        "managedReleases": len(selected),
        "conceptSchemes": len(set(scheme_by_concept.values())),
        "concepts": len(release_by_concept),
        "labels": sum(len(release.record()["labels"]) for release in selected),
        "labelClusters": cluster_count,
        "mappingCandidates": len(candidates),
        "searchOnlyMappings": len(qualified),
        "agentValidationReceipts": len(agents),
        "baselineValidationReceipts": len(baselines),
        "feedback": len(feedback_by_id),
    }
    inputs: list[dict[str, str]] = [release.pin() for release in selected]
    if crosswalk_bundle is not None:
        inputs.append(crosswalk_bundle.pin())
    inputs.extend(
        {
            "role": "MappingCandidate",
            "identifier": candidate.candidate_id,
            "recordDigest": candidate.candidate_digest,
        }
        for candidate in candidates.values()
    )
    inputs.extend(
        {
            "role": "AgentValidationReceipt",
            "identifier": identifier,
            "recordDigest": str(receipt["receipt_digest"]),
        }
        for identifier, receipt in agents.items()
    )
    inputs.extend(
        {
            "role": "BaselineValidationReceipt",
            "identifier": identifier,
            "recordDigest": str(receipt["receipt_digest"]),
        }
        for identifier, receipt in baselines.items()
    )
    inputs.extend(
        {
            "role": "MappingFeedback",
            "identifier": item.feedback_id,
            "recordDigest": item.feedback_digest,
        }
        for item in feedback_by_id.values()
    )
    manifest = build_manifest(
        payload=payload,
        generation_digest=generation_digest,
        asserted_graph=asserted,
        analysis_graph=analysis,
        counts=counts,
        inputs=inputs,
        asset_id=asserted_graph_iri,
        policies=policies,
        implementation=implementation,
    )
    return VocabularyAtlasAsset(
        _canonical_payload=payload,
        _manifest=manifest,
        asserted_graph_iri=asserted_graph_iri,
        analysis_graph_iri=analysis_graph_iri,
        generation_digest=generation_digest,
    )


__all__ = [
    "ATLAS",
    "RKAF",
    "MappingCandidate",
    "MappingFeedback",
    "build_vocabulary_atlas",
    "normalize_label",
]
