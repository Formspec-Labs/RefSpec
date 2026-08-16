"""Deterministic agency projection from asserted agency-roster releases.

REF-038 projects regulations.gov docket-ID prefixes from the asserted agency
identity mapping release. The release owns every identity decision; this module
adds no mapping and makes no matching decision. It joins asserted mappings and
metadata abstentions to the five pinned roster releases, then selects labels and
parent relations already present in those releases.

The builder performs no file or network I/O, normalizes no identifier, and
never compares names for similarity.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from refspec.atlas.v3_registry_rosters import ATLAS_PARENT_ENTITY
from refspec.atlas.v3_source_data import (
    RegistryMapping,
    RegistryMappingRelease,
    RegistryRelease,
    RegistryResource,
)
from refspec.immutable import deep_freeze_json

ATLAS_SAME_ENTITY_AS = "https://refspec.org/ns/atlas/v3#sameEntityAs"
REF_038_DECISION_RECORD = "docs/decisions.md#ref-038"
REF_038_REVIEWER_IRI = "urn:ref:reviewer:refspec-owner"
REF_038_ADJUDICATED_ON = "2026-08-16"

FR_RELEASE_KEY = "federal-register-agencies-roster-2026-08-15"
FH_RELEASE_KEY = "federal-hierarchy-orgs-complete-2026-08-15"
OPM_RELEASE_KEY = "opm-ehri-agency-subelement-2026-08-04"
ECFR_RELEASE_KEY = "ecfr-agencies-roster-2026-08-15"
REGULATIONS_GOV_RELEASE_KEY = "regulations-gov-agencies-roster-2026-08-16"

AGENCY_ROSTER_ORDER = (
    "federal-register-agencies",
    "federal-hierarchy-organizations",
    "opm-ehri-agency-subelement",
    "ecfr-agencies",
    "regulations-gov-agencies",
)
AGENCY_ROSTER_RELEASE_KEYS = (
    FR_RELEASE_KEY,
    FH_RELEASE_KEY,
    OPM_RELEASE_KEY,
    ECFR_RELEASE_KEY,
    REGULATIONS_GOV_RELEASE_KEY,
)
EXPECTED_AGENCY_ROSTER_COUNTS = {
    "federal-register-agencies": 472,
    "federal-hierarchy-organizations": 907,
    "opm-ehri-agency-subelement": 798,
    "ecfr-agencies": 316,
    "regulations-gov-agencies": 331,
}

IDENTIFIER_KIND_TO_ROSTER = {
    "federalRegisterNumericId": "federal-register-agencies",
    "federalRegisterSlug": "federal-register-agencies",
    "federalRegisterShortName": "federal-register-agencies",
    "federalHierarchyOrganizationId": "federal-hierarchy-organizations",
    "fpdsAgencyCode": "federal-hierarchy-organizations",
    "cgacAgencyIdentifier": "federal-hierarchy-organizations",
    "legacyFpdsOfficeCode": "federal-hierarchy-organizations",
    "opmEhriAgencySubelementCode": "opm-ehri-agency-subelement",
    "ecfrAgencySlug": "ecfr-agencies",
    "ecfrAgencyShortName": "ecfr-agencies",
    "regulationsGovAgencyId": "regulations-gov-agencies",
}
IDENTIFIER_KIND_ORDER = tuple(IDENTIFIER_KIND_TO_ROSTER)
ADMISSIBLE_ACRONYM_PAIRS = frozenset(
    {
        frozenset({"federalRegisterShortName", "ecfrAgencyShortName"}),
        frozenset({"federalRegisterShortName", "regulationsGovAgencyId"}),
        frozenset({"ecfrAgencyShortName", "regulationsGovAgencyId"}),
    }
)

EvidenceTier = Literal["E4"]
ReviewWarrant = Literal["humanReview"]


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen = deep_freeze_json(value)
    if not isinstance(frozen, Mapping):
        raise TypeError("agency projection mapping must remain an object")
    return cast(Mapping[str, Any], frozen)


def _release_by_key(releases: Sequence[RegistryRelease]) -> dict[str, RegistryRelease]:
    by_key: dict[str, RegistryRelease] = {}
    for release in releases:
        if release.key in by_key:
            raise ValueError(f"agency projection input repeats release key {release.key!r}")
        by_key[release.key] = release
    missing = sorted(set(AGENCY_ROSTER_RELEASE_KEYS) - set(by_key))
    if missing:
        raise ValueError(f"agency projection is missing required releases: {missing!r}")
    for roster, release_key in zip(
        AGENCY_ROSTER_ORDER,
        AGENCY_ROSTER_RELEASE_KEYS,
        strict=True,
    ):
        observed = len(by_key[release_key].resources)
        expected = EXPECTED_AGENCY_ROSTER_COUNTS[roster]
        if observed != expected:
            raise ValueError(
                f"agency projection roster count drifted for {release_key}: "
                f"expected {expected}, got {observed}"
            )
    return by_key


def _add_identifier_claim(
    claims: dict[str, dict[str, set[str]]],
    *,
    kind: str,
    value: object,
    resource: RegistryResource,
) -> None:
    if value is None or value == "":
        return
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ValueError(f"{kind} identifier must be text or integer, got {value!r}")
    claims[kind][str(value)].add(resource.iri)


def extract_agency_identifier_claims(
    releases: Sequence[RegistryRelease],
) -> dict[str, dict[str, set[str]]]:
    """Extract the eleven publisher identifier kinds without reading labels."""

    by_key = _release_by_key(releases)
    claims: dict[str, dict[str, set[str]]] = {
        kind: defaultdict(set) for kind in IDENTIFIER_KIND_ORDER
    }
    for resource in by_key[FR_RELEASE_KEY].resources:
        payload = resource.native_payload
        _add_identifier_claim(
            claims,
            kind="federalRegisterNumericId",
            value=payload["id"],
            resource=resource,
        )
        _add_identifier_claim(
            claims,
            kind="federalRegisterSlug",
            value=payload["slug"],
            resource=resource,
        )
        _add_identifier_claim(
            claims,
            kind="federalRegisterShortName",
            value=payload["short_name"],
            resource=resource,
        )
    for resource in by_key[FH_RELEASE_KEY].resources:
        payload = resource.native_payload
        _add_identifier_claim(
            claims,
            kind="federalHierarchyOrganizationId",
            value=payload["fhorgid"],
            resource=resource,
        )
        _add_identifier_claim(
            claims,
            kind="fpdsAgencyCode",
            value=payload["agencycode"],
            resource=resource,
        )
        _add_identifier_claim(
            claims,
            kind="legacyFpdsOfficeCode",
            value=payload.get("oldfpdsofficecode"),
            resource=resource,
        )
        for cgac_row in payload["cgaclist"]:
            _add_identifier_claim(
                claims,
                kind="cgacAgencyIdentifier",
                value=cgac_row["cgac"],
                resource=resource,
            )
    for resource in by_key[OPM_RELEASE_KEY].resources:
        _add_identifier_claim(
            claims,
            kind="opmEhriAgencySubelementCode",
            value=resource.native_payload["code"],
            resource=resource,
        )
    for resource in by_key[ECFR_RELEASE_KEY].resources:
        payload = resource.native_payload
        _add_identifier_claim(
            claims,
            kind="ecfrAgencySlug",
            value=payload["slug"],
            resource=resource,
        )
        _add_identifier_claim(
            claims,
            kind="ecfrAgencyShortName",
            value=payload["short_name"],
            resource=resource,
        )
    for resource in by_key[REGULATIONS_GOV_RELEASE_KEY].resources:
        _add_identifier_claim(
            claims,
            kind="regulationsGovAgencyId",
            value=resource.native_payload["id"],
            resource=resource,
        )
    return claims


@dataclass(frozen=True, slots=True)
class AgencyProjectionSourceRecord:
    """One exact publisher record used by an E4 adjudication."""

    release_key: str
    release_digest: str
    resource: str
    source_locator: str
    source_digest: str
    field: str
    value: str
    publisher_name: str

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True, slots=True)
class AgencyProjectionEvidenceRecord:
    """The complete REF-035 E4 decision for one acronym-equality bridge."""

    record_id: str
    evidence_tier: EvidenceTier
    warrant: ReviewWarrant
    reviewer: str
    adjudicated_on: str
    decision_record: str
    decision: Literal["approved"]
    decision_basis: str
    relation: str
    name_similarity_used: Literal[False]
    reasoning: str
    source_record: AgencyProjectionSourceRecord
    target_record: AgencyProjectionSourceRecord

    def __post_init__(self) -> None:
        if self.evidence_tier != "E4" or self.warrant != "humanReview":
            raise ValueError("agency acronym equality must remain E4 humanReview evidence")
        if not self.decision_basis:
            raise ValueError("agency projection evidence requires a decision basis")
        if not self.reasoning:
            raise ValueError("agency projection evidence requires specific reasoning")
        if self.name_similarity_used is not False:
            raise ValueError("agency projection evidence must not use roster-wide name similarity")
        if self.relation != ATLAS_SAME_ENTITY_AS:
            raise ValueError("agency projection evidence must assert atlas:sameEntityAs")
        content = self.to_dict()
        content.pop("record_id")
        expected_id = "urn:ref:agency-projection-evidence:" + _digest(content).removeprefix(
            "sha256:"
        )
        if self.record_id != expected_id:
            raise ValueError("agency projection evidence record id is not content-derived")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "evidence_tier": self.evidence_tier,
            "warrant": self.warrant,
            "reviewer": self.reviewer,
            "adjudicated_on": self.adjudicated_on,
            "decision_record": self.decision_record,
            "decision": self.decision,
            "decision_basis": self.decision_basis,
            "relation": self.relation,
            "name_similarity_used": self.name_similarity_used,
            "reasoning": self.reasoning,
            "source_record": self.source_record.to_dict(),
            "target_record": self.target_record.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AgencyProjectionRow:
    """One resolved agency source value and its exact mapping basis."""

    source_value_kind: str
    source_value: str
    org: str
    pref_label: str
    abbreviations: tuple[str, ...]
    aliases: tuple[str, ...]
    parent_org: str | None
    relation: str
    evidence_tier: EvidenceTier
    warrant: ReviewWarrant
    basis: str
    evidence_records: tuple[AgencyProjectionEvidenceRecord, ...]

    def __post_init__(self) -> None:
        if not self.basis:
            raise ValueError("agency projection mapping row requires a basis")
        if not self.evidence_records:
            raise ValueError("agency projection mapping row requires evidence records")
        if self.relation != ATLAS_SAME_ENTITY_AS:
            raise ValueError("agency projection mapping row must use atlas:sameEntityAs")
        if self.evidence_tier != "E4" or self.warrant != "humanReview":
            raise ValueError("agency projection mapping row must remain E4 humanReview")
        for evidence in self.evidence_records:
            if evidence.source_record.value != self.source_value:
                raise ValueError("agency projection row evidence cites another source value")
            if evidence.target_record.resource != self.org:
                raise ValueError("agency projection row evidence cites another target org")
            if evidence.evidence_tier != self.evidence_tier or evidence.warrant != self.warrant:
                raise ValueError("agency projection row and evidence tier or warrant differ")
            if evidence.decision_basis != self.basis:
                raise ValueError("agency projection row and evidence basis differ")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_value_kind": self.source_value_kind,
            "source_value": self.source_value,
            "org": self.org,
            "pref_label": self.pref_label,
            "abbreviations": list(self.abbreviations),
            "aliases": list(self.aliases),
            "parent_org": self.parent_org,
            "relation": self.relation,
            "evidence_tier": self.evidence_tier,
            "warrant": self.warrant,
            "basis": self.basis,
            "evidence_records": [record.to_dict() for record in self.evidence_records],
        }


@dataclass(frozen=True, slots=True)
class AgencyProjectionUnresolvedRow:
    """One source value for which REF-038 requires abstention."""

    source_value_kind: str
    source_value: str
    source_org: str
    pref_label: str
    source_parent_org: str | None
    reason: str
    reasoning: str
    candidate_resources: tuple[str, ...]
    closest_non_adopted_candidate: Mapping[str, str] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_value_kind": self.source_value_kind,
            "source_value": self.source_value,
            "source_org": self.source_org,
            "pref_label": self.pref_label,
            "source_parent_org": self.source_parent_org,
            "reason": self.reason,
            "reasoning": self.reasoning,
            "candidate_resources": list(self.candidate_resources),
            "closest_non_adopted_candidate": (
                None
                if self.closest_non_adopted_candidate is None
                else dict(self.closest_non_adopted_candidate)
            ),
        }


@dataclass(frozen=True, slots=True)
class AgencyProjectionCoverage:
    """Counted parity between all source values, mappings, and abstentions."""

    source_value_kind: str
    source_value_count: int
    resolved_value_count: int
    unresolved_value_count: int
    basis_counts: Mapping[str, int]
    unresolved_reason_counts: Mapping[str, int]
    rows_with_parent_org: int
    evidence_record_count: int

    def __post_init__(self) -> None:
        if self.resolved_value_count + self.unresolved_value_count != self.source_value_count:
            raise ValueError("agency projection coverage does not account for every source value")
        if sum(self.basis_counts.values()) != self.resolved_value_count:
            raise ValueError("agency projection basis counts do not equal resolved rows")
        if sum(self.unresolved_reason_counts.values()) != self.unresolved_value_count:
            raise ValueError("agency projection reason counts do not equal unresolved rows")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_value_kind": self.source_value_kind,
            "source_value_count": self.source_value_count,
            "resolved_value_count": self.resolved_value_count,
            "unresolved_value_count": self.unresolved_value_count,
            "basis_counts": dict(self.basis_counts),
            "unresolved_reason_counts": dict(self.unresolved_reason_counts),
            "rows_with_parent_org": self.rows_with_parent_org,
            "evidence_record_count": self.evidence_record_count,
        }


@dataclass(frozen=True, slots=True)
class AgencyProjection:
    """Resolved and unresolved agency projection tables plus counted coverage."""

    rows: tuple[AgencyProjectionRow, ...]
    unresolved: tuple[AgencyProjectionUnresolvedRow, ...]
    coverage: AgencyProjectionCoverage
    digest: str

    def __post_init__(self) -> None:
        source_values = [row.source_value for row in self.rows]
        unresolved_values = [row.source_value for row in self.unresolved]
        if len(source_values) != len(set(source_values)):
            raise ValueError("agency projection repeats a resolved source value")
        if len(unresolved_values) != len(set(unresolved_values)):
            raise ValueError("agency projection repeats an unresolved source value")
        if set(source_values) & set(unresolved_values):
            raise ValueError("agency projection resolves and abstains on the same source value")
        content = self.to_dict()
        content.pop("digest")
        if self.digest != _digest(content):
            raise ValueError("agency projection digest is not content-derived")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": [row.to_dict() for row in self.rows],
            "unresolved": [row.to_dict() for row in self.unresolved],
            "coverage": self.coverage.to_dict(),
            "digest": self.digest,
        }


def _resources_by_iri(release: RegistryRelease) -> dict[str, RegistryResource]:
    resources = {resource.iri: resource for resource in release.resources}
    if len(resources) != len(release.resources):
        raise ValueError(f"agency release {release.key} repeats a resource IRI")
    return resources


def _preferred_label(resource: RegistryResource) -> str:
    labels = [
        label.value
        for label in resource.labels
        if label.role == "preferred" and label.language == "en"
    ]
    if len(labels) != 1:
        raise ValueError(
            f"agency projection resource {resource.iri} must have one English preferred label"
        )
    return labels[0]


def _parent_by_subject(release: RegistryRelease) -> dict[str, str]:
    parents: dict[str, str] = {}
    resource_iris = {resource.iri for resource in release.resources}
    for relation in release.relations:
        if relation.predicate != ATLAS_PARENT_ENTITY:
            continue
        if relation.subject not in resource_iris or relation.object not in resource_iris:
            raise ValueError(f"agency release {release.key} has a parent outside its roster")
        previous = parents.setdefault(relation.subject, relation.object)
        if previous != relation.object:
            raise ValueError(f"agency release {release.key} gives one resource two parents")
    return parents


def _mapping_decision_payload(
    mapping: RegistryMapping,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    """Return one checked shared decision and its two endpoint records."""

    if len(mapping.evidence) != 2:
        raise ValueError("agency identity mapping must carry two publisher evidence rows")
    payloads = [evidence.native_payload for evidence in mapping.evidence]
    if any(evidence.review_warrant != "humanReview" for evidence in mapping.evidence):
        raise ValueError("agency identity mapping evidence must remain humanReview")
    if len({evidence.reviewer_iri for evidence in mapping.evidence}) != 1:
        raise ValueError("agency identity mapping evidence reviewers differ")
    if len({evidence.attested_at for evidence in mapping.evidence}) != 1:
        raise ValueError("agency identity mapping evidence decision times differ")
    by_role: dict[str, Mapping[str, Any]] = {}
    shared: Mapping[str, Any] | None = None
    for payload in payloads:
        role = payload.get("endpointRole")
        endpoint_record = payload.get("endpointRecord")
        if role not in {"subject", "object"} or not isinstance(endpoint_record, Mapping):
            raise ValueError("agency identity evidence lacks a subject or object record")
        if role in by_role:
            raise ValueError("agency identity evidence repeats an endpoint role")
        by_role[str(role)] = endpoint_record
        current_shared = {
            key: value
            for key, value in payload.items()
            if key not in {"endpointRole", "endpointRecord"}
        }
        if shared is None:
            shared = current_shared
        elif current_shared != shared:
            raise ValueError("agency identity endpoint evidence decisions differ")
    if shared is None or set(by_role) != {"subject", "object"}:
        raise ValueError("agency identity mapping evidence is incomplete")
    expected = {
        "subjectIri": mapping.subject,
        "predicateIri": mapping.predicate,
        "objectIri": mapping.object,
    }
    if any(shared.get(key) != value for key, value in expected.items()):
        raise ValueError("agency identity evidence differs from its mapping triple")
    if (
        shared.get("decision") != "adopted"
        or shared.get("evidenceTier") != "E4"
        or shared.get("nameSimilarityUsed") is not False
        or shared.get("decisionRecord") != REF_038_DECISION_RECORD
    ):
        raise ValueError("agency identity evidence decision fields differ")
    for key in ("decisionBasis", "reasoning", "reviewerIri", "decidedAt"):
        if not isinstance(shared.get(key), str) or not shared[key]:
            raise ValueError(f"agency identity evidence lacks {key}")
    return shared, by_role["subject"], by_role["object"]


def _projection_source_record(payload: Mapping[str, Any]) -> AgencyProjectionSourceRecord:
    expected = {
        "field",
        "publisher",
        "publisherName",
        "releaseDigest",
        "releaseKey",
        "resourceIri",
        "sourceDigest",
        "sourceLocator",
        "value",
    }
    if set(payload) != expected:
        raise ValueError("agency identity endpoint record fields differ")
    return AgencyProjectionSourceRecord(
        release_key=str(payload["releaseKey"]),
        release_digest=str(payload["releaseDigest"]),
        resource=str(payload["resourceIri"]),
        source_locator=str(payload["sourceLocator"]),
        source_digest=str(payload["sourceDigest"]),
        field=str(payload["field"]),
        value=str(payload["value"]),
        publisher_name=str(payload["publisherName"]),
    )


def _projection_evidence_record(mapping: RegistryMapping) -> AgencyProjectionEvidenceRecord:
    shared, source_payload, target_payload = _mapping_decision_payload(mapping)
    source_record = _projection_source_record(source_payload)
    target_record = _projection_source_record(target_payload)
    content: dict[str, Any] = {
        "evidence_tier": "E4",
        "warrant": "humanReview",
        "reviewer": str(shared["reviewerIri"]),
        "adjudicated_on": str(shared["decidedAt"]),
        "decision_record": str(shared["decisionRecord"]),
        "decision": "approved",
        "decision_basis": str(shared["decisionBasis"]),
        "relation": mapping.predicate,
        "name_similarity_used": False,
        "reasoning": str(shared["reasoning"]),
        "source_record": source_record,
        "target_record": target_record,
    }
    identity_payload = {
        key: value.to_dict() if isinstance(value, AgencyProjectionSourceRecord) else value
        for key, value in content.items()
    }
    record_id = "urn:ref:agency-projection-evidence:" + _digest(identity_payload).removeprefix(
        "sha256:"
    )
    return AgencyProjectionEvidenceRecord(record_id=record_id, **content)  # type: ignore[arg-type]


def _projection_labels(
    source_resource: RegistryResource,
    target_resource: RegistryResource,
    *,
    source_value: str,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    pref_label = _preferred_label(target_resource)
    abbreviations = (source_value,)
    alias_candidates = {
        _preferred_label(source_resource),
        *(label.value for label in source_resource.labels if label.role == "alternate"),
        *(label.value for label in target_resource.labels if label.role == "alternate"),
    }
    aliases = tuple(sorted(alias_candidates - {pref_label, *abbreviations}))
    return pref_label, abbreviations, aliases


def build_agency_projection(
    releases: Sequence[RegistryRelease],
    identity_release: RegistryMappingRelease,
) -> AgencyProjection:
    """Project asserted mappings and metadata abstentions without adding claims."""

    by_key = _release_by_key(releases)
    if (
        identity_release.key != "regulations-gov-agency-identity-2026-08-16"
        or identity_release.ring != "entity"
    ):
        raise ValueError("agency projection requires the REF-038 entity mapping release")
    resources = {
        key: _resources_by_iri(by_key[key]) for key in AGENCY_ROSTER_RELEASE_KEYS
    }
    parents = {
        key: _parent_by_subject(by_key[key]) for key in AGENCY_ROSTER_RELEASE_KEYS
    }
    releases_by_atlas_iri = {
        release.atlas_release_iri: release for release in by_key.values()
    }
    regs_release = by_key[REGULATIONS_GOV_RELEASE_KEY]
    regs_resources = resources[REGULATIONS_GOV_RELEASE_KEY]
    regs_by_value = {
        str(resource.native_payload["id"]): resource
        for resource in regs_release.resources
    }

    decisions_value = identity_release.metadata.get("candidateDecisions")
    if not isinstance(decisions_value, Sequence) or isinstance(
        decisions_value,
        (str, bytes, bytearray),
    ):
        raise TypeError("agency identity release has no candidate decisions")
    decisions: dict[str, Mapping[str, Any]] = {}
    for value in decisions_value:
        if not isinstance(value, Mapping):
            raise TypeError("agency identity candidate decision must be an object")
        source_value = value.get("sourceValue")
        if not isinstance(source_value, str) or source_value in decisions:
            raise ValueError("agency identity candidate decisions repeat or omit a source value")
        decisions[source_value] = value
    if set(decisions) != set(regs_by_value):
        raise ValueError("agency identity candidate decisions do not account for all 331 ids")

    rows: list[AgencyProjectionRow] = []
    mapped_values: set[str] = set()
    for mapping in sorted(identity_release.mappings, key=lambda row: row.subject):
        if mapping.predicate != ATLAS_SAME_ENTITY_AS:
            raise ValueError("agency identity release uses a predicate outside the entity ring")
        if mapping.subject not in regs_resources:
            raise ValueError("agency identity mapping subject is outside regulations.gov")
        if mapping.subject_atlas_release_iri != regs_release.atlas_release_iri:
            raise ValueError("agency identity mapping subject release differs")
        target_release = releases_by_atlas_iri.get(mapping.object_atlas_release_iri)
        if target_release is None or target_release.key not in {
            FR_RELEASE_KEY,
            FH_RELEASE_KEY,
            ECFR_RELEASE_KEY,
        }:
            raise ValueError("agency identity mapping target release is not FR, FH, or eCFR")
        target_resource = resources[target_release.key].get(mapping.object)
        if target_resource is None:
            raise ValueError("agency identity mapping object is absent from its target roster")
        source_resource = regs_resources[mapping.subject]
        source_value = str(source_resource.native_payload["id"])
        if source_value in mapped_values:
            raise ValueError("agency identity release maps one regulations.gov id twice")
        mapped_values.add(source_value)
        decision = decisions[source_value]
        if (
            decision.get("decision") != "adopted"
            or decision.get("sourceResource") != mapping.subject
            or decision.get("objectResource") != mapping.object
            or decision.get("predicateIri") != mapping.predicate
        ):
            raise ValueError("agency identity mapping differs from candidate accounting")
        evidence = _projection_evidence_record(mapping)
        if (
            evidence.source_record.resource != source_resource.iri
            or evidence.target_record.resource != target_resource.iri
            or evidence.decision_basis != decision.get("basis")
            or evidence.reasoning != decision.get("reasoning")
        ):
            raise ValueError("agency identity projection evidence differs from release metadata")
        pref_label, abbreviations, aliases = _projection_labels(
            source_resource,
            target_resource,
            source_value=source_value,
        )
        rows.append(
            AgencyProjectionRow(
                source_value_kind="regulationsGovAgencyId",
                source_value=source_value,
                org=target_resource.iri,
                pref_label=pref_label,
                abbreviations=abbreviations,
                aliases=aliases,
                parent_org=parents[target_release.key].get(target_resource.iri),
                relation=mapping.predicate,
                evidence_tier="E4",
                warrant="humanReview",
                basis=evidence.decision_basis,
                evidence_records=(evidence,),
            )
        )

    unresolved: list[AgencyProjectionUnresolvedRow] = []
    for source_value, decision in sorted(decisions.items()):
        if decision.get("decision") == "adopted":
            if source_value not in mapped_values:
                raise ValueError("agency identity metadata adopts a value without an assertion")
            continue
        if decision.get("decision") != "abstained" or source_value in mapped_values:
            raise ValueError("agency identity abstention differs from asserted mappings")
        source_resource = regs_by_value[source_value]
        closest = decision.get("closestNonAdoptedCandidate")
        if closest is not None and not isinstance(closest, Mapping):
            raise TypeError("agency identity closest candidate must be an object")
        candidate_resources = (
            () if closest is None else (str(closest["resource"]),)
        )
        unresolved.append(
            AgencyProjectionUnresolvedRow(
                source_value_kind="regulationsGovAgencyId",
                source_value=source_value,
                source_org=source_resource.iri,
                pref_label=_preferred_label(source_resource),
                source_parent_org=parents[REGULATIONS_GOV_RELEASE_KEY].get(
                    source_resource.iri
                ),
                reason=str(decision["reason"]),
                reasoning=str(decision["reasoning"]),
                candidate_resources=candidate_resources,
                closest_non_adopted_candidate=(
                    None
                    if closest is None
                    else _frozen_mapping(
                        {str(key): str(value) for key, value in closest.items()}
                    )
                ),
            )
        )

    basis_counts = Counter(row.basis for row in rows)
    unresolved_reason_counts = Counter(row.reason for row in unresolved)
    coverage = AgencyProjectionCoverage(
        source_value_kind="regulationsGovAgencyId",
        source_value_count=len(regs_by_value),
        resolved_value_count=len(rows),
        unresolved_value_count=len(unresolved),
        basis_counts=_frozen_mapping(dict(sorted(basis_counts.items()))),
        unresolved_reason_counts=_frozen_mapping(
            dict(sorted(unresolved_reason_counts.items()))
        ),
        rows_with_parent_org=sum(row.parent_org is not None for row in rows),
        evidence_record_count=sum(len(row.evidence_records) for row in rows),
    )
    content = {
        "rows": [row.to_dict() for row in rows],
        "unresolved": [row.to_dict() for row in unresolved],
        "coverage": coverage.to_dict(),
    }
    return AgencyProjection(
        rows=tuple(rows),
        unresolved=tuple(unresolved),
        coverage=coverage,
        digest=_digest(content),
    )


__all__ = [
    "ADMISSIBLE_ACRONYM_PAIRS",
    "AGENCY_ROSTER_ORDER",
    "AGENCY_ROSTER_RELEASE_KEYS",
    "ATLAS_SAME_ENTITY_AS",
    "ECFR_RELEASE_KEY",
    "EXPECTED_AGENCY_ROSTER_COUNTS",
    "FH_RELEASE_KEY",
    "FR_RELEASE_KEY",
    "IDENTIFIER_KIND_ORDER",
    "IDENTIFIER_KIND_TO_ROSTER",
    "OPM_RELEASE_KEY",
    "REGULATIONS_GOV_RELEASE_KEY",
    "AgencyProjection",
    "AgencyProjectionCoverage",
    "AgencyProjectionEvidenceRecord",
    "AgencyProjectionRow",
    "AgencyProjectionSourceRecord",
    "AgencyProjectionUnresolvedRow",
    "build_agency_projection",
    "extract_agency_identifier_claims",
]
