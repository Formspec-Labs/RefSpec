"""Deterministic agency projection from asserted agency-roster releases.

REF-038 projects regulations.gov docket-ID prefixes from the asserted agency
identity mapping release. The release owns every identity decision; this module
adds no mapping and makes no matching decision. It joins asserted mappings and
metadata abstentions to the five pinned roster releases, then selects labels and
parent relations already present in those releases. The reverse lookup reads
the projection backwards for consumers and asserts nothing.

REF-072's agency-registry release has its own view beside it, never folded into
the REF-038 projection: its bridges, one row per (change event, result), and its
recorded non-emissions, plus the forward successor lookup, which is derived and
never asserted.

Neither performs file or network I/O, normalizes an identifier, or compares
names for similarity.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast, get_args

from refspec.atlas.v3_registry_rosters import ATLAS_PARENT_ENTITY
from refspec.atlas.v3_source_data import (
    RegistryMapping,
    RegistryMappingEvidence,
    RegistryMappingRelease,
    RegistryRelease,
    RegistryResource,
)
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import plain_json

ATLAS_SAME_ENTITY_AS = "https://refspec.org/ns/atlas/v3#sameEntityAs"
REF_038_DECISION_RECORD = "docs/decisions.md#ref-038"
REF_038_ADJUDICATED_ON = "2026-08-16"
# REF-072's release sits beside REF-038's and never feeds its projection.
AGENCY_REGISTRY_RELEASE_KEY = "agency-registry-2026-09-26"
# Why a decided item emits nothing -- closed, so the release and every reader
# of its view refuse a reason nobody defined. The owner's own words ride beside
# each code as its reasoning.
AgencyRegistryNonEmissionReason = Literal[
    "heldForStatutoryRenameBasis",
    "noCounterpartInHeldFRRoster",
    "sameOrganizationReverseLookupCostRejected",
    "withdrawn",
]
AGENCY_REGISTRY_NON_EMISSION_REASONS = frozenset(get_args(AgencyRegistryNonEmissionReason))

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


def parent_by_subject(release: RegistryRelease) -> dict[str, str]:
    """Each resource's one publisher-stated parent in its own roster; raises on a second parent or an outside one."""

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
        key: parent_by_subject(by_key[key]) for key in AGENCY_ROSTER_RELEASE_KEYS
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


@dataclass(frozen=True, slots=True)
class AgencyReverseProjection:
    """Target organizations read back to regulations.gov codes, ordered by organization IRI.

    ``resolved`` maps an organization exactly one projection row selects to that
    row's code; ``ambiguous`` maps an organization several rows select to all of
    their codes, sorted, and such an organization is absent from ``resolved``.
    """

    resolved: Mapping[str, str]
    ambiguous: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        if not self.resolved.keys().isdisjoint(self.ambiguous):
            raise ValueError("agency reverse projection resolves an ambiguous organization")
        if any(len(codes) < 2 for codes in self.ambiguous.values()):
            raise ValueError("agency reverse projection lists an organization one code selects as ambiguous")


def reverse_agency_projection(projection: AgencyProjection) -> AgencyReverseProjection:
    """Read the projection backwards: an organization resolves only where one code selects it.

    This is a consumer's interpretation, not an assertion. REF-038's release
    asserts ``atlas:sameEntityAs`` one way, from each regulations.gov resource to
    its counterpart, and deliberately mints no inverse; nothing here mints one,
    and the output must never be emitted as an identity claim. An organization
    is the IRI a row's ``org`` carries: ``urn:ref:federal-register-agency:<id>``,
    ``urn:ref:ecfr-agency:<slug>`` or ``urn:ref:federal-hierarchy-org:<id>``.
    Where several codes select one organization (``FR`` and ``OFR`` both select
    the Office of the Federal Register) no code is the organization's own, so it
    resolves to nothing and is listed as ambiguous. Unresolved rows select no
    organization and contribute nothing, closest candidates included.
    """

    codes_by_org: dict[str, list[str]] = defaultdict(list)
    for row in projection.rows:
        codes_by_org[row.org].append(row.source_value)
    by_org = sorted(codes_by_org.items())
    return AgencyReverseProjection(
        resolved=_frozen_mapping({org: codes[0] for org, codes in by_org if len(codes) == 1}),
        ambiguous=_frozen_mapping(
            {org: tuple(sorted(codes)) for org, codes in by_org if len(codes) > 1}
        ),
    )


# ---------------------------------------------------------------------------
# REF-072: the agency registry's own view and its forward successor lookup.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgencyRegistryView:
    """The agency-registry release as consumer rows: bridges, event results, and non-emissions.

    Each row is a plain dict whose shape is its Parquet table's, so the digest a
    reader recomputes from the tables is this one. One event row per (event,
    result) carries the event's date, its public records, and the functions that
    result took; a rename has one row, a split one per result.
    """

    bridges: tuple[Mapping[str, Any], ...]
    events: tuple[Mapping[str, Any], ...]
    non_emissions: tuple[Mapping[str, Any], ...]
    coverage: Mapping[str, int]
    release: Mapping[str, str]
    digest: str

    def __post_init__(self) -> None:
        if self.digest != agency_registry_view_digest(self.bridges, self.events, self.non_emissions, self.coverage):
            raise ValueError("agency registry view digest is not content-derived")


def agency_registry_view_digest(
    bridges: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    non_emissions: Sequence[Mapping[str, Any]],
    coverage: Mapping[str, int],
) -> str:
    """The logical-content digest of the view, the same whether computed from the release or the tables."""

    return _digest(
        plain_json(
            {
                "bridges": bridges,
                "coverage": coverage,
                "events": events,
                "nonEmissions": non_emissions,
            }
        )
    )


def _owner_decision_row(decision: Mapping[str, Any], reviewer: str) -> dict[str, Any]:
    return {
        "answer": str(decision["answer"]),
        "channel": str(decision["channel"]),
        "content_digest": str(decision["contentDigest"]),
        "decided_on": str(decision["decidedOn"]),
        "note": decision.get("note"),
        "reviewer": reviewer,
    }


def _stated_review(evidence: Sequence[RegistryMappingEvidence], claim: str) -> tuple[str, str, str]:
    """The evidence tier, warrant and reviewer every approval of one claim states; refused unless they agree.

    A view row states one of each, so approvals that disagree are refused
    rather than one of them chosen.
    """

    reviews = {
        (item.native_payload.get("evidenceTier"), item.review_warrant, item.reviewer_iri) for item in evidence
    }
    if len(reviews) != 1:
        raise ValueError(f"agency registry {claim} approvals differ in evidence tier, warrant or reviewer")
    ((tier, warrant, reviewer),) = reviews
    if not isinstance(tier, str) or not tier:
        raise ValueError(f"agency registry {claim} approvals state no evidence tier")
    return tier, warrant, reviewer


def _release_reviews(
    release: RegistryMappingRelease,
) -> tuple[dict[tuple[str, str, str], tuple[str, str, str]], dict[str, tuple[str, str, str]], str]:
    """What the release's evidence states for each bridge and each event, and the one reviewer it names.

    Bridges are keyed by their triple and events by the event id their
    evidence carries. A non-emission has no evidence of its own; it is the
    decision of the reviewer every approval in the release names, so a release
    naming more than one is refused rather than guessed at.
    """

    bridges = {
        (mapping.subject, mapping.predicate, mapping.object): _stated_review(mapping.evidence, mapping.subject)
        for mapping in release.mappings
    }
    events: dict[str, tuple[str, str, str]] = {}
    for event in release.change_events:
        event_ids = {item.native_payload.get("event", {}).get("eventId") for item in event.evidence}
        event_id = event_ids.pop() if len(event_ids) == 1 else None
        if not isinstance(event_id, str):
            raise ValueError("agency registry change event evidence does not name one event")
        events[event_id] = _stated_review(event.evidence, event_id)
    reviewers = {reviewer for _tier, _warrant, reviewer in (*bridges.values(), *events.values())}
    if len(reviewers) != 1:
        named = "no reviewer" if not reviewers else f"{len(reviewers)} reviewers"
        raise ValueError(f"agency registry approvals name {named}; a non-emission's reviewer is unknown")
    (reviewer,) = reviewers
    return bridges, events, reviewer


def build_agency_registry_view(release: RegistryMappingRelease) -> AgencyRegistryView:
    """Project the agency-registry release into its view rows; add nothing, match nothing.

    Rows equal the release's assertions and records exactly: every bridge row
    is one of its ``atlas:sameEntityAs`` mappings, every event row one result
    of one of its change events, and every decided item appears once. Each
    row's evidence tier, warrant and reviewer are what the release's evidence
    states, never constants, so a release whose evidence falls short shows it.
    """

    if release.key != AGENCY_REGISTRY_RELEASE_KEY or release.ring != "entity":
        raise ValueError("the agency registry view reads the agency-registry release only")
    bridge_reviews, event_reviews, release_reviewer = _release_reviews(release)
    bridges: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    non_emissions: list[dict[str, Any]] = []
    for decision in release.metadata["decisions"]:
        if decision["decision"] == "adopted":
            triple = (str(decision["sourceResource"]), str(decision["predicateIri"]), str(decision["objectResource"]))
            if triple not in bridge_reviews:
                raise ValueError("agency registry bridge rows are not exactly the release's mappings")
            tier, warrant, reviewer = bridge_reviews[triple]
            parents = decision.get("parents", {})
            bridges.append(
                {
                    "candidate_id": str(decision["candidateId"]),
                    "subject": str(decision["sourceResource"]),
                    "subject_publisher_name": str(decision["sourcePublisherName"]),
                    "subject_parent": parents["subject"]["resourceIri"] if "subject" in parents else None,
                    "object": str(decision["objectResource"]),
                    "object_release_key": str(decision["objectReleaseKey"]),
                    "object_publisher_name": str(decision["objectPublisherName"]),
                    "object_parent": parents["object"]["resourceIri"] if "object" in parents else None,
                    "relation": str(decision["predicateIri"]),
                    "basis": str(decision["basis"]),
                    "reasoning": str(decision["reasoning"]),
                    "evidence_tier": tier,
                    "warrant": warrant,
                    "decision": _owner_decision_row(decision["ownerDecision"], reviewer),
                }
            )
        elif decision["decision"] == "event":
            if str(decision["eventId"]) not in event_reviews:
                raise ValueError("agency registry event rows are not exactly the release's change events")
            tier, warrant, reviewer = event_reviews[str(decision["eventId"])]
            records = [
                {key: str(record[key]) for key in ("citation", "kind", "note", "url")}
                for record in decision["publicRecords"]
            ]
            originals = [str(row["resourceIri"]) for row in decision["originals"]]
            for result in decision["results"]:
                events.append(
                    {
                        "event_id": str(decision["eventId"]),
                        "effective_date": str(decision["effectiveDate"]),
                        "date_basis": str(decision["dateBasis"]),
                        "originals": originals,
                        "result": str(result["resourceIri"]),
                        "result_publisher_name": str(result["publisherName"]),
                        "functions_taken": result.get("functionsTaken"),
                        "reasoning": str(result["reasoning"]),
                        "public_records": records,
                        "evidence_tier": tier,
                        "warrant": warrant,
                        "decision": _owner_decision_row(decision["ownerDecision"], reviewer),
                    }
                )
        elif decision["decision"] == "nonEmission":
            closest = decision.get("closestAlternative")
            non_emissions.append(
                {
                    "item_id": str(decision["candidateId"]),
                    "reason": str(decision["reason"]),
                    "reasoning": str(decision["reasoning"]),
                    "subject": decision.get("sourceResource"),
                    "subject_value": decision.get("sourceValue"),
                    "object": decision.get("objectResource"),
                    "closest_alternative": (
                        None
                        if closest is None
                        else {key: str(closest[key]) for key in ("description", "relation", "why_not_proposed")}
                    ),
                    "decision": _owner_decision_row(decision["ownerDecision"], release_reviewer),
                }
            )
        else:
            raise ValueError(f"agency registry decision has an unknown kind: {decision['decision']!r}")

    bridges.sort(key=lambda row: row["candidate_id"])
    events.sort(key=lambda row: (row["event_id"], row["result"]))
    non_emissions.sort(key=lambda row: row["item_id"])
    claims = {(mapping.subject, mapping.predicate, mapping.object) for mapping in release.mappings}
    if {(row["subject"], row["relation"], row["object"]) for row in bridges} != claims or len(bridges) != len(claims):
        raise ValueError("agency registry bridge rows are not exactly the release's mappings")
    event_links = {
        (original, result) for event in release.change_events for original in event.originals for result in event.results
    }
    if {(original, row["result"]) for row in events for original in row["originals"]} != event_links:
        raise ValueError("agency registry event rows are not exactly the release's change events")
    coverage = {
        "bridgeCount": len(bridges),
        "decidedItemCount": len(bridges) + len({row["event_id"] for row in events}) + len(non_emissions),
        "eventCount": len({row["event_id"] for row in events}),
        "eventResultRowCount": len(events),
        "nonEmissionCount": len(non_emissions),
    }
    if coverage["decidedItemCount"] != release.metadata["decidedItemCount"]:
        raise ValueError("agency registry view does not account for every decided item")
    return AgencyRegistryView(
        bridges=tuple(_frozen_mapping(row) for row in bridges),
        events=tuple(_frozen_mapping(row) for row in events),
        non_emissions=tuple(_frozen_mapping(row) for row in non_emissions),
        coverage=_frozen_mapping(coverage),
        release=_frozen_mapping(
            {
                "candidatesDigest": str(release.metadata["candidatesDigest"]),
                "decisionRecord": str(release.metadata["decisionRecord"]),
                "key": release.key,
                "sourceReleaseDigest": release.source_release_digest,
            }
        ),
        digest=agency_registry_view_digest(bridges, events, non_emissions, coverage),
    )


@dataclass(frozen=True, slots=True)
class AgencySuccessors:
    """Each defunct organization read forward to the organizations that hold its functions now.

    ``current`` maps an event's original to the results no later event
    replaced, walking every chain to its end; a split keeps every result. An
    organization no event names as an original has no successors.
    """

    current: Mapping[str, frozenset[str]]

    def of(self, organization: str) -> frozenset[str]:
        return self.current.get(organization, frozenset())


def current_agency_successors(events: Sequence[Mapping[str, Any]]) -> AgencySuccessors:
    """Walk the change events forward; derived for consumers, never asserted.

    The same standing as ``reverse_agency_projection()``: a reading of
    adjudicated events, not a claim, and never emitted as ``atlas:sameEntityAs``
    or as a succession. A consumer that needs one code applies its own
    exactly-one rule, so a split yields no single successor by design. Takes the
    view's event rows (``AgencyRegistryView.events`` or the Parquet table's), one
    per (event, result). An iterative depth-first walk, so a long chain cannot
    exhaust the stack: each organization's answer is settled once, after all its
    results, and reused along every chain through it. A cycle, which the binding
    refuses on the wire, is refused here too.
    """

    results_of: dict[str, set[str]] = defaultdict(set)
    for row in events:
        for original in row["originals"]:
            results_of[str(original)].add(str(row["result"]))
    settled: dict[str, frozenset[str]] = {}
    for root in sorted(results_of):
        if root in settled:
            continue
        path = {root}
        stack = [(root, iter(sorted(results_of[root])))]
        while stack:
            organization, pending = stack[-1]
            for result in pending:
                if result in settled or result not in results_of:
                    continue
                if result in path:
                    raise ValueError(f"agency change events form a cycle through {result}")
                path.add(result)
                stack.append((result, iter(sorted(results_of[result]))))
                break
            else:
                stack.pop()
                path.discard(organization)
                current: set[str] = set()
                for result in results_of[organization]:
                    current |= settled[result] if result in results_of else {result}
                settled[organization] = frozenset(current)
    return AgencySuccessors(current=_frozen_mapping(dict(sorted(settled.items()))))

__all__ = [
    "ADMISSIBLE_ACRONYM_PAIRS",
    "AGENCY_REGISTRY_NON_EMISSION_REASONS",
    "AGENCY_REGISTRY_RELEASE_KEY",
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
    "AgencyRegistryNonEmissionReason",
    "AgencyRegistryView",
    "AgencyReverseProjection",
    "AgencySuccessors",
    "agency_registry_view_digest",
    "build_agency_projection",
    "build_agency_registry_view",
    "current_agency_successors",
    "extract_agency_identifier_claims",
    "parent_by_subject",
    "reverse_agency_projection",
]
