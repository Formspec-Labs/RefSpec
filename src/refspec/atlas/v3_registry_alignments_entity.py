"""E4 entity-identity mappings for the regulations.gov agency roster.

REF-038 keeps each identity claim in an asserted entity-ring mapping release.
The release uses only ``atlas:sameEntityAs`` and asserts each regulations.gov
resource to one held Federal Register, eCFR, or Federal Hierarchy resource.
Candidate decisions in release metadata account for every regulations.gov id,
including the values for which no held roster contains the same entity.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, cast
from urllib.parse import quote

from refspec.atlas import agency_projection
from refspec.atlas.v3_registry_rosters import ATLAS_PARENT_ENTITY
from refspec.atlas.v3_source_data import (
    RegistryInputPin,
    RegistryMapping,
    RegistryMappingEvidence,
    RegistryMappingRelease,
    RegistryRelease,
    RegistryResource,
    canonical_digest,
    mapping_triple_digest,
)
from refspec.immutable import deep_freeze_json

REGULATIONS_GOV_AGENCY_IDENTITY_RELEASE_KEY = (
    "regulations-gov-agency-identity-2026-08-16"
)
REGULATIONS_GOV_AGENCY_IDENTITY_RESOURCE_ID = (
    "regulations-gov-agency-identity"
)
REGULATIONS_GOV_AGENCY_IDENTITY_ASSERTED_AT = "2026-08-16T00:00:00+00:00"
REGULATIONS_GOV_AGENCY_IDENTITY_REVIEWER_IRI = (
    "urn:ref:reviewer:refspec-owner"
)
REGULATIONS_GOV_AGENCY_IDENTITY_DECISION_RECORD = (
    "docs/decisions.md#ref-038"
)
EXPECTED_IDENTITY_MAPPING_COUNT = 321
EXPECTED_IDENTITY_ABSTENTION_COUNT = 10
EXPECTED_IDENTITY_CANDIDATE_COUNT = 331

ATLAS_SAME_ENTITY_AS = agency_projection.ATLAS_SAME_ENTITY_AS

AgencyDecisionBasis = Literal[
    "federalRegisterShortNameEqualsRegulationsGovAgencyId",
    "ecfrAgencyShortNameEqualsRegulationsGovAgencyId",
    "exactPublisherNameEquality",
    "obviousPublisherNameVariant",
    "publisherNameWithParentContext",
    "acronymExpansionWithNameAndParentContext",
]
AbstentionReason = Literal[
    "genuineCollisionNamesCannotBreak",
    "noCounterpartInHeldRosters",
]

AGENCY_DECISION_BASES = frozenset(
    {
        "federalRegisterShortNameEqualsRegulationsGovAgencyId",
        "ecfrAgencyShortNameEqualsRegulationsGovAgencyId",
        "exactPublisherNameEquality",
        "obviousPublisherNameVariant",
        "publisherNameWithParentContext",
        "acronymExpansionWithNameAndParentContext",
    }
)
AGENCY_ABSTENTION_REASONS = frozenset(
    {
        "genuineCollisionNamesCannotBreak",
        "noCounterpartInHeldRosters",
    }
)


@dataclass(frozen=True, slots=True)
class ResidueAdoption:
    """One owner-adjudicated identity from the original 52-value residue."""

    source_value: str
    source_name: str
    target_release_key: str
    target_resource: str
    target_name: str
    basis: AgencyDecisionBasis
    reasoning: str
    non_emitted_candidates: tuple[Mapping[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ResidueAbstention:
    """One residue value for which no defensible identity target exists."""

    source_value: str
    source_name: str
    reason: AbstentionReason
    reasoning: str
    closest_candidate: Mapping[str, str] | None = None


def _adopt(
    source_value: str,
    source_name: str,
    target_release_key: str,
    target_resource: str,
    target_name: str,
    basis: AgencyDecisionBasis,
    reasoning: str,
    *,
    non_emitted_candidates: tuple[Mapping[str, str], ...] = (),
) -> ResidueAdoption:
    return ResidueAdoption(
        source_value=source_value,
        source_name=source_name,
        target_release_key=target_release_key,
        target_resource=target_resource,
        target_name=target_name,
        basis=basis,
        reasoning=reasoning,
        non_emitted_candidates=non_emitted_candidates,
    )


def _abstain(
    source_value: str,
    source_name: str,
    reasoning: str,
    *,
    closest_candidate: Mapping[str, str] | None = None,
) -> ResidueAbstention:
    return ResidueAbstention(
        source_value=source_value,
        source_name=source_name,
        reason="noCounterpartInHeldRosters",
        reasoning=reasoning,
        closest_candidate=closest_candidate,
    )


FR = agency_projection.FR_RELEASE_KEY
FH = agency_projection.FH_RELEASE_KEY
ECFR = agency_projection.ECFR_RELEASE_KEY


RESIDUE_ADOPTIONS: tuple[ResidueAdoption, ...] = (
    _adopt(
        "ACL",
        "Administration for Community Living",
        FH,
        "urn:ref:federal-hierarchy-org:100525875",
        "ADMINISTRATION FOR COMMUNITY LIVING (ACL)",
        "obviousPublisherNameVariant",
        "Federal Hierarchy adds only the regulations.gov acronym ACL to the same full publisher name.",
    ),
    _adopt(
        "ADF",
        "African Development Foundation",
        ECFR,
        "urn:ref:ecfr-agency:african-development-foundation",
        "African Development Foundation",
        "exactPublisherNameEquality",
        "regulations.gov and eCFR publish the same name, African Development Foundation.",
    ),
    _adopt(
        "AID",
        "U.S. Agency for International Development",
        FR,
        "urn:ref:federal-register-agency:6",
        "Agency for International Development",
        "obviousPublisherNameVariant",
        "The Federal Register name omits only the U.S. qualifier from the regulations.gov name.",
    ),
    _adopt(
        "ASC",
        "Appraisal Subcommittee",
        FR,
        "urn:ref:federal-register-agency:621",
        "Appraisal Subcommittee of the Federal Financial Institutions Examination Council",
        "obviousPublisherNameVariant",
        "The Federal Register expands Appraisal Subcommittee with its parent council and names no competing subcommittee.",
    ),
    _adopt(
        "ATR",
        "Antitrust Division",
        FR,
        "urn:ref:federal-register-agency:23",
        "Antitrust Division",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same name, Antitrust Division.",
    ),
    _adopt(
        "CDFIF",
        "Community Development Financial Institutions Fund Np",
        FR,
        "urn:ref:federal-register-agency:78",
        "Community Development Financial Institutions Fund",
        "obviousPublisherNameVariant",
        "The regulations.gov name adds only the stray suffix Np to the complete Federal Register name.",
    ),
    _adopt(
        "CISA",
        "Cybersecurity and Infrastructure Security Agency",
        FH,
        "urn:ref:federal-hierarchy-org:500044551",
        "Cybersecurity and Infrastructure Security Agency",
        "exactPublisherNameEquality",
        "regulations.gov and Federal Hierarchy publish the same name for CISA.",
    ),
    _adopt(
        "CNCS",
        "Corporation for National and Community Service",
        FR,
        "urn:ref:federal-register-agency:91",
        "Corporation for National and Community Service",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same corporation name.",
    ),
    _adopt(
        "COFA",
        "Commission of Fine Arts",
        FR,
        "urn:ref:federal-register-agency:57",
        "Commission of Fine Arts",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same commission name.",
    ),
    _adopt(
        "CORP",
        "Corporation for National and Community Service",
        FR,
        "urn:ref:federal-register-agency:91",
        "Corporation for National and Community Service",
        "exactPublisherNameEquality",
        "The separate regulations.gov id CORP carries the same full publisher name as the Federal Register corporation record.",
    ),
    _adopt(
        "CROMFS",
        "Commission on Review of Overseas Military Facility Structure of the United States",
        FR,
        "urn:ref:federal-register-agency:67",
        "Commission on Review of Overseas Military Facility Structure of the United States",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same complete commission name.",
    ),
    _adopt(
        "DBCRC",
        "Defense Base Closure and Realignment Commission",
        FR,
        "urn:ref:federal-register-agency:99",
        "Defense Base Closure and Realignment Commission",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same commission name.",
    ),
    _adopt(
        "DEPO",
        "Disability Employment Policy Office",
        FR,
        "urn:ref:federal-register-agency:115",
        "Disability Employment Policy Office",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same office name.",
    ),
    _adopt(
        "EERE",
        "Energy Efficiency and Renewable Energy Office",
        FR,
        "urn:ref:federal-register-agency:137",
        "Energy Efficiency and Renewable Energy Office",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same office name.",
    ),
    _adopt(
        "EIB",
        "Export Import Bank of the United States",
        ECFR,
        "urn:ref:ecfr-agency:export-import-bank",
        "Export-Import Bank of the United States",
        "obviousPublisherNameVariant",
        "The two names differ only by the publisher's hyphenation of Export-Import.",
    ),
    _adopt(
        "ESA",
        "Employment Standards Administration",
        FR,
        "urn:ref:federal-register-agency:134",
        "Employment Standards Administration",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same administration name.",
    ),
    _adopt(
        "FINCEN",
        "Financial Crimes Enforcement Network",
        FR,
        "urn:ref:federal-register-agency:194",
        "Financial Crimes Enforcement Network",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same network name.",
    ),
    _adopt(
        "FIRSTNET",
        "First Responder Network Authority",
        FR,
        "urn:ref:federal-register-agency:584",
        "First Responder Network Authority",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same authority name.",
    ),
    _adopt(
        "FISCAL",
        "Fiscal Service",
        FR,
        "urn:ref:federal-register-agency:585",
        "Fiscal Service",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same service name.",
    ),
    _adopt(
        "FPAC",
        "Farm Production and Conservation Business Center",
        FR,
        "urn:ref:federal-register-agency:619",
        "Farm Production and Conservation Business Center",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same business-center name.",
    ),
    _adopt(
        "FPPO",
        "Federal Procurement Policy Office",
        FR,
        "urn:ref:federal-register-agency:184",
        "Federal Procurement Policy Office",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same office name.",
    ),
    _adopt(
        "FR",
        "Office of Federal Register",
        ECFR,
        "urn:ref:ecfr-agency:federal-register-office",
        "Office of Federal Register",
        "exactPublisherNameEquality",
        "regulations.gov and eCFR publish the same office name.",
    ),
    _adopt(
        "FS",
        "Forest Service",
        FR,
        "urn:ref:federal-register-agency:209",
        "Forest Service",
        "publisherNameWithParentContext",
        "The regulations.gov name Forest Service and Agriculture parent select the Federal Register Forest Service, not Fiscal Service.",
        non_emitted_candidates=(
            {
                "resource": "urn:ref:federal-register-agency:585",
                "publisherName": "Fiscal Service",
                "reason": "same acronym but different publisher name",
            },
            {
                "resource": "urn:ref:ecfr-agency:fiscal-service",
                "publisherName": "Fiscal Service",
                "reason": "same acronym but different publisher name",
            },
            {
                "resource": "urn:ref:ecfr-agency:forest-service",
                "publisherName": "Forest Service",
                "reason": "same entity in another roster; one target is emitted",
            },
        ),
    ),
    _adopt(
        "GCERC",
        "Gulf Coast Ecosystem Restoration Council",
        FR,
        "urn:ref:federal-register-agency:583",
        "Gulf Coast Ecosystem Restoration Council",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same council name.",
    ),
    _adopt(
        "GEO",
        "Government Ethics Office",
        FR,
        "urn:ref:federal-register-agency:215",
        "Government Ethics Office",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same office name.",
    ),
    _adopt(
        "HHSIG",
        "Inspector General Office, Health and Human Services Department",
        FH,
        "urn:ref:federal-hierarchy-org:100004455",
        "OFFICE OF THE INSPECTOR GENERAL",
        "acronymExpansionWithNameAndParentContext",
        "HHSIG expands to the inspector-general office named by regulations.gov, and Federal Hierarchy places that office under Health and Human Services.",
    ),
    _adopt(
        "HPAC",
        "Historic Preservation, Advisory Council",
        FR,
        "urn:ref:federal-register-agency:225",
        "Advisory Council on Historic Preservation",
        "obviousPublisherNameVariant",
        "The Federal Register uses the ordinary word order for the same advisory council named by regulations.gov.",
    ),
    _adopt(
        "ICEB",
        "Immigration and Customs Enforcement Bureau",
        FH,
        "urn:ref:federal-hierarchy-org:100012075",
        "U.S. IMMIGRATION AND CUSTOMS ENFORCEMENT",
        "acronymExpansionWithNameAndParentContext",
        "ICEB expands to Immigration and Customs Enforcement, and both records place the entity under Homeland Security.",
    ),
    _adopt(
        "MCRMC",
        "Military Compensation and Retirement Modernization Commission",
        FR,
        "urn:ref:federal-register-agency:582",
        "Military Compensation and Retirement Modernization Commission",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same commission name.",
    ),
    _adopt(
        "MEXICO",
        "U.S. International Boundary and Water Commission",
        ECFR,
        "urn:ref:ecfr-agency:international-boundary-and-water-commission-united-states-and-mexico",
        "United States Section United States and Mexico International Boundary and Water Commission",
        "obviousPublisherNameVariant",
        "The regulations.gov id MEXICO and U.S. qualifier identify the United States Section that eCFR names in full; the commission's official two-section description only corroborates that publisher-name decision.",
    ),
    _adopt(
        "MKU",
        "Morris K. Udall Scholarship and Excellence in National Environmental Policy Foundation",
        FH,
        "urn:ref:federal-hierarchy-org:300000070",
        "MORRIS K. UDALL SCHOLARSHIP AND EXCELLENCE IN NATIONAL ENVIRONMENTAL POLICY FOUNDATION",
        "obviousPublisherNameVariant",
        "The publishers give the same complete foundation name with only letter case differing.",
        non_emitted_candidates=(
            {
                "resource": "urn:ref:federal-hierarchy-org:300000385",
                "publisherName": "MORRIS K. UDALL SCHOLARSHIP AND EXCELLENCE IN NATIONAL ENVIRONMENTAL POLICY FOUNDATION",
                "reason": "Federal Hierarchy marks this duplicate-name resource as a Sub-Tier under the selected entity",
            },
        ),
    ),
    _adopt(
        "MPAC",
        "Medicare Payment Advisory Commission",
        FR,
        "urn:ref:federal-register-agency:284",
        "Medicare Payment Advisory Commission",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same commission name.",
    ),
    _adopt(
        "NCC",
        "National Counterintelligence Center",
        FR,
        "urn:ref:federal-register-agency:334",
        "National Counterintelligence Center",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same center name.",
    ),
    _adopt(
        "NEO",
        "Nuclear Energy Office",
        FR,
        "urn:ref:federal-register-agency:382",
        "Nuclear Energy Office",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same office name.",
    ),
    _adopt(
        "NRPC",
        "National Railroad Passenger Corporation",
        FR,
        "urn:ref:federal-register-agency:365",
        "National Railroad Passenger Corporation",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same corporation name.",
    ),
    _adopt(
        "NSPC",
        "National Space Council",
        FR,
        "urn:ref:federal-register-agency:612",
        "National Space Council",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same council name.",
    ),
    _adopt(
        "RUF",
        "Reagan Udall Foundation",
        FR,
        "urn:ref:federal-register-agency:445",
        "Reagan-Udall Foundation for the Food and Drug Administration",
        "obviousPublisherNameVariant",
        "The Federal Register supplies the hyphen and the foundation's FDA qualifier; no other Reagan-Udall entity appears in the held rosters.",
    ),
    _adopt(
        "SS",
        "Secret Service",
        FR,
        "urn:ref:federal-register-agency:465",
        "Secret Service",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same service name.",
    ),
    _adopt(
        "TRADE",
        "Trade and Development Agency",
        FR,
        "urn:ref:federal-register-agency:490",
        "Trade and Development Agency",
        "exactPublisherNameEquality",
        "regulations.gov and the Federal Register publish the same agency name.",
    ),
    _adopt(
        "USDAIG",
        "Inspector General Office, Agriculture Department",
        FH,
        "urn:ref:federal-hierarchy-org:100006936",
        "OFFICE OF INSPECTOR GENERAL",
        "acronymExpansionWithNameAndParentContext",
        "USDAIG expands to the inspector-general office named by regulations.gov, and Federal Hierarchy places that office under Agriculture.",
    ),
    _adopt(
        "USEIB",
        "Export-import Bank",
        FR,
        "urn:ref:federal-register-agency:151",
        "Export-Import Bank",
        "obviousPublisherNameVariant",
        "The two publisher names differ only in the capitalization of Import.",
    ),
    _adopt(
        "WCPO",
        "Workers Compensation Programs Office",
        FR,
        "urn:ref:federal-register-agency:530",
        "Workers' Compensation Programs Office",
        "obviousPublisherNameVariant",
        "The Federal Register adds only the possessive apostrophe to the same office name.",
    ),
)


RESIDUE_ABSTENTIONS: tuple[ResidueAbstention, ...] = (
    _abstain(
        "ARCTICGAS",
        "Office of the Federal Coordinator for Alaska Natural Gas Transportation Projects",
        "No held roster contains the Federal Coordinator office; Federal Hierarchy's Federal Inspector office is a different entity.",
        closest_candidate={
            "resource": "urn:ref:federal-hierarchy-org:300000035",
            "publisherName": "OFF OF THE FED INSPECTOR FOR THE AK NATURAL GAS TRANSPORT",
            "reason": "different office and role",
        },
    ),
    _abstain(
        "BSC",
        "Business Standards Council",
        "No Federal Register, Federal Hierarchy, OPM, or eCFR resource names this council.",
    ),
    _abstain(
        "EOA",
        "Energy Office, Agriculture Department",
        "No held roster contains this Agriculture office; the Energy Policy and New Uses Office is a differently named office.",
        closest_candidate={
            "resource": "urn:ref:federal-register-agency:536",
            "publisherName": "Energy Policy and New Uses Office",
            "reason": "same department but different office name",
        },
    ),
    _abstain(
        "GAPFAC",
        "Gsa Acquisition Policy Federal Advisory Committee",
        "No held roster contains this GSA federal advisory committee.",
    ),
    _abstain(
        "MMA",
        "Marine Minerals Administration",
        "The held rosters contain predecessor bureaus but no Marine Minerals Administration resource.",
        closest_candidate={
            "resource": "urn:ref:federal-register-agency:289",
            "publisherName": "Minerals Management Service",
            "reason": "predecessor organization, not the same roster entity",
        },
    ),
    _abstain(
        "NCRIRS",
        "National Commission on Restructuring the Internal Revenue Service",
        "No held roster contains this temporary commission; the Internal Revenue Service is the commission's subject, not the commission.",
        closest_candidate={
            "resource": "urn:ref:federal-register-agency:254",
            "publisherName": "Internal Revenue Service",
            "reason": "reviewed organization, not the reviewing commission",
        },
    ),
    _abstain(
        "OIRA",
        "Office of Information and Regulatory Affairs",
        "No held roster contains an OIRA resource; its Office of Management and Budget parent is not the same entity.",
        closest_candidate={
            "resource": "urn:ref:federal-register-agency:391",
            "publisherName": "Management and Budget Office",
            "reason": "parent office, not the OIRA subunit",
        },
    ),
    _abstain(
        "PCSCOTUS",
        "Presidential Commission on the Supreme Court of the United States",
        "No held roster contains this presidential commission; Supreme Court resources are the commission's subject, not the commission.",
        closest_candidate={
            "resource": "urn:ref:federal-hierarchy-org:300000011",
            "publisherName": "SUPREME COURT OF THE UNITED STATES",
            "reason": "reviewed institution, not the presidential commission",
        },
    ),
    _abstain(
        "PRES",
        "Presidential Documents",
        "Presidential Documents is a special docket grouping, and no held entity roster contains a same-entity resource.",
        closest_candidate={
            "resource": "urn:ref:federal-hierarchy-org:100525435",
            "publisherName": "PRESIDENT OF THE UNITED STATES",
            "reason": "document issuer, not the docket grouping",
        },
    ),
    _abstain(
        "USC",
        "United States Courts",
        "The held rosters separate the Judicial Branch, courts, and their Administrative Office; none is a same-entity counterpart to this umbrella name.",
        closest_candidate={
            "resource": "urn:ref:federal-register-agency:3",
            "publisherName": "Administrative Office of United States Courts",
            "reason": "administrative support agency, not the United States Courts collectively",
        },
    ),
)


def _frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen = deep_freeze_json(value)
    if not isinstance(frozen, Mapping):
        raise TypeError("agency identity metadata row must remain an object")
    return cast(Mapping[str, Any], frozen)


def _releases_by_key(releases: Sequence[RegistryRelease]) -> dict[str, RegistryRelease]:
    by_key: dict[str, RegistryRelease] = {}
    for release in releases:
        if release.key in by_key:
            raise ValueError(f"agency identity input repeats release key {release.key!r}")
        by_key[release.key] = release
    missing = sorted(set(agency_projection.AGENCY_ROSTER_RELEASE_KEYS) - set(by_key))
    if missing:
        raise ValueError(f"agency identity release is missing required rosters: {missing!r}")
    for key, expected in zip(
        agency_projection.AGENCY_ROSTER_RELEASE_KEYS,
        agency_projection.EXPECTED_AGENCY_ROSTER_COUNTS.values(),
        strict=True,
    ):
        if len(by_key[key].resources) != expected:
            raise ValueError(f"agency identity roster count drifted for {key}")
    return by_key


def _resources_by_iri(release: RegistryRelease) -> dict[str, RegistryResource]:
    resources = {resource.iri: resource for resource in release.resources}
    if len(resources) != len(release.resources):
        raise ValueError(f"agency identity release {release.key} repeats a resource IRI")
    return resources


def _publisher_name(release_key: str, resource: RegistryResource) -> tuple[str, str]:
    if release_key == agency_projection.REGULATIONS_GOV_RELEASE_KEY:
        return "name", str(resource.native_payload["name"])
    if release_key == FR:
        return "name", str(resource.native_payload["name"])
    if release_key == FH:
        return "fhorgname", str(resource.native_payload["fhorgname"])
    if release_key == ECFR:
        return "name", str(resource.native_payload["name"])
    if release_key == agency_projection.OPM_RELEASE_KEY:
        return "publisherName", str(resource.native_payload["publisherName"])
    raise ValueError(f"unsupported agency publisher-name release {release_key!r}")


def _publisher_label(release_key: str) -> str:
    return {
        agency_projection.REGULATIONS_GOV_RELEASE_KEY: "regulations.gov",
        FR: "Federal Register",
        FH: "Federal Hierarchy",
        ECFR: "eCFR",
        agency_projection.OPM_RELEASE_KEY: "OPM EHRI",
    }[release_key]


def _parent_by_subject(release: RegistryRelease) -> dict[str, str]:
    return {
        relation.subject: relation.object
        for relation in release.relations
        if relation.predicate == ATLAS_PARENT_ENTITY
    }


def _pin_for_resource(
    release: RegistryRelease,
    resource: RegistryResource,
) -> RegistryInputPin:
    matches = [pin for pin in release.inputs if pin.sha256 == resource.source_digest]
    if len(matches) != 1:
        raise ValueError(
            f"agency identity resource {resource.iri} does not select one input pin"
        )
    return matches[0]


def _source_record_payload(
    *,
    release: RegistryRelease,
    resource: RegistryResource,
    field: str,
    value: str,
    publisher_name: str,
) -> dict[str, Any]:
    return {
        "field": field,
        "publisher": _publisher_label(release.key),
        "publisherName": publisher_name,
        "releaseDigest": release.source_release_digest,
        "releaseKey": release.key,
        "resourceIri": resource.iri,
        "sourceDigest": resource.source_digest,
        "sourceLocator": resource.source_locator,
        "value": value,
    }


def _mapping_evidence(
    *,
    source_release: RegistryRelease,
    source_resource: RegistryResource,
    source_value: str,
    source_name: str,
    target_release: RegistryRelease,
    target_resource: RegistryResource,
    target_field: str,
    target_value: str,
    target_name: str,
    basis: AgencyDecisionBasis,
    reasoning: str,
    mapping_subject: str,
    mapping_object: str,
) -> tuple[RegistryMappingEvidence, RegistryMappingEvidence]:
    triple = {
        "subjectIri": mapping_subject,
        "predicateIri": ATLAS_SAME_ENTITY_AS,
        "objectIri": mapping_object,
    }
    shared_payload: dict[str, Any] = {
        **triple,
        "decidedAt": REGULATIONS_GOV_AGENCY_IDENTITY_ASSERTED_AT,
        "decision": "adopted",
        "decisionBasis": basis,
        "decisionRecord": REGULATIONS_GOV_AGENCY_IDENTITY_DECISION_RECORD,
        "evidenceTier": "E4",
        "mappingTripleDigest": mapping_triple_digest(
            subject_iri=mapping_subject,
            predicate_iri=ATLAS_SAME_ENTITY_AS,
            object_iri=mapping_object,
        ),
        "nameSimilarityUsed": False,
        "publisherNames": {
            "object": target_name,
            "subject": source_name,
        },
        "reasoning": reasoning,
        "reviewerIri": REGULATIONS_GOV_AGENCY_IDENTITY_REVIEWER_IRI,
    }
    endpoints = (
        (
            "subject",
            source_release,
            source_resource,
            _source_record_payload(
                release=source_release,
                resource=source_resource,
                field="attributes.id",
                value=source_value,
                publisher_name=source_name,
            ),
        ),
        (
            "object",
            target_release,
            target_resource,
            _source_record_payload(
                release=target_release,
                resource=target_resource,
                field=target_field,
                value=target_value,
                publisher_name=target_name,
            ),
        ),
    )
    rows: list[RegistryMappingEvidence] = []
    for endpoint_role, release, resource, endpoint_record in endpoints:
        pin = _pin_for_resource(release, resource)
        rows.append(
            RegistryMappingEvidence(
                source_locator=(
                    pin.source_iri
                    + "#agency-identity-resource="
                    + quote(resource.iri, safe="")
                ),
                source_digest=pin.sha256,
                native_payload={
                    **shared_payload,
                    "endpointRecord": endpoint_record,
                    "endpointRole": endpoint_role,
                },
                review_warrant="humanReview",
                reviewer_iri=REGULATIONS_GOV_AGENCY_IDENTITY_REVIEWER_IRI,
                attested_at=REGULATIONS_GOV_AGENCY_IDENTITY_ASSERTED_AT,
            )
        )
    return rows[0], rows[1]


def _mapping_and_decision(
    *,
    source_release: RegistryRelease,
    source_resource: RegistryResource,
    source_value: str,
    source_name: str,
    target_release: RegistryRelease,
    target_resource: RegistryResource,
    target_field: str,
    target_value: str,
    target_name: str,
    basis: AgencyDecisionBasis,
    reasoning: str,
    non_emitted_candidates: Sequence[Mapping[str, str]] = (),
) -> tuple[RegistryMapping, Mapping[str, Any]]:
    if basis not in AGENCY_DECISION_BASES:
        raise ValueError(f"agency identity basis is outside the closed vocabulary: {basis}")
    evidence = _mapping_evidence(
        source_release=source_release,
        source_resource=source_resource,
        source_value=source_value,
        source_name=source_name,
        target_release=target_release,
        target_resource=target_resource,
        target_field=target_field,
        target_value=target_value,
        target_name=target_name,
        basis=basis,
        reasoning=reasoning,
        mapping_subject=source_resource.iri,
        mapping_object=target_resource.iri,
    )
    mapping = RegistryMapping(
        subject=source_resource.iri,
        predicate=ATLAS_SAME_ENTITY_AS,
        object=target_resource.iri,
        subject_atlas_release_iri=source_release.atlas_release_iri,
        object_atlas_release_iri=target_release.atlas_release_iri,
        asserted_at=REGULATIONS_GOV_AGENCY_IDENTITY_ASSERTED_AT,
        evidence=evidence,
    )
    decision: dict[str, Any] = {
        "basis": basis,
        "decidedAt": REGULATIONS_GOV_AGENCY_IDENTITY_ASSERTED_AT,
        "decision": "adopted",
        "objectPublisherName": target_name,
        "objectReleaseKey": target_release.key,
        "objectResource": target_resource.iri,
        "predicateIri": ATLAS_SAME_ENTITY_AS,
        "reasoning": reasoning,
        "reviewerIri": REGULATIONS_GOV_AGENCY_IDENTITY_REVIEWER_IRI,
        "sourceParentResource": _parent_by_subject(source_release).get(
            source_resource.iri
        ),
        "sourcePublisherName": source_name,
        "sourceResource": source_resource.iri,
        "sourceValue": source_value,
    }
    if non_emitted_candidates:
        decision["nonEmittedCandidates"] = [dict(row) for row in non_emitted_candidates]
    return mapping, _frozen_mapping(decision)


def _mapping_inputs(
    by_key: Mapping[str, RegistryRelease],
) -> tuple[RegistryInputPin, ...]:
    inputs: list[RegistryInputPin] = []
    for release_index, release_key in enumerate(
        agency_projection.AGENCY_ROSTER_RELEASE_KEYS,
        start=1,
    ):
        for pin_index, pin in enumerate(by_key[release_key].inputs, start=1):
            inputs.append(
                replace(
                    pin,
                    role=f"agencyRoster{release_index:02d}Input{pin_index:02d}",
                )
            )
    return tuple(inputs)


def _candidate_resources(
    claims: Mapping[str, Mapping[str, set[str]]],
    source_value: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                *claims["federalRegisterShortName"].get(source_value, set()),
                *claims["ecfrAgencyShortName"].get(source_value, set()),
            }
        )
    )


def load_regulations_gov_agency_identity_mapping_release(
    releases: Sequence[RegistryRelease],
) -> RegistryMappingRelease:
    """Build the complete 331-value E4 decision release from pinned rosters."""

    by_key = _releases_by_key(releases)
    resources = {
        key: _resources_by_iri(by_key[key])
        for key in agency_projection.AGENCY_ROSTER_RELEASE_KEYS
    }
    claims = agency_projection.extract_agency_identifier_claims(releases)
    regs_release = by_key[agency_projection.REGULATIONS_GOV_RELEASE_KEY]
    fr_release = by_key[FR]
    ecfr_release = by_key[ECFR]
    residue_adoptions = {row.source_value: row for row in RESIDUE_ADOPTIONS}
    residue_abstentions = {row.source_value: row for row in RESIDUE_ABSTENTIONS}
    if set(residue_adoptions) & set(residue_abstentions):
        raise ValueError("agency identity residue resolves and abstains on one value")

    mappings: list[RegistryMapping] = []
    candidate_decisions: list[Mapping[str, Any]] = []
    regs_claims = claims["regulationsGovAgencyId"]
    fr_claims = claims["federalRegisterShortName"]
    ecfr_claims = claims["ecfrAgencyShortName"]
    original_residue: set[str] = set()

    for source_value in sorted(regs_claims):
        source_iris = sorted(regs_claims[source_value])
        if len(source_iris) != 1:
            raise ValueError(f"regulations.gov agency id {source_value!r} is not unique")
        source_resource = resources[agency_projection.REGULATIONS_GOV_RELEASE_KEY][
            source_iris[0]
        ]
        _, source_name = _publisher_name(regs_release.key, source_resource)
        fr_candidates = sorted(fr_claims.get(source_value, set()))
        ecfr_candidates = sorted(ecfr_claims.get(source_value, set()))
        target_release: RegistryRelease | None = None
        target_resource: RegistryResource | None = None
        target_field = ""
        basis: AgencyDecisionBasis | None = None
        if len(fr_candidates) == 1:
            target_release = fr_release
            target_resource = resources[FR][fr_candidates[0]]
            target_field = "short_name"
            basis = "federalRegisterShortNameEqualsRegulationsGovAgencyId"
        elif len(ecfr_candidates) == 1:
            target_release = ecfr_release
            target_resource = resources[ECFR][ecfr_candidates[0]]
            target_field = "short_name"
            basis = "ecfrAgencyShortNameEqualsRegulationsGovAgencyId"

        if target_release is not None and target_resource is not None and basis is not None:
            _, target_name = _publisher_name(target_release.key, target_resource)
            other_candidates = [
                {
                    "resource": iri,
                    "publisherName": _publisher_name(
                        FR if iri in resources[FR] else ECFR,
                        resources[FR].get(iri, resources[ECFR].get(iri)),  # type: ignore[arg-type]
                    )[1],
                    "reason": "not selected by the deterministic acronym target order",
                }
                for iri in _candidate_resources(claims, source_value)
                if iri != target_resource.iri
            ]
            reasoning = (
                f"regulations.gov id {source_value} equals the publisher acronym "
                f"on the {_publisher_label(target_release.key)} record; "
                f"regulations.gov names {source_name!r} and the target publisher "
                f"names {target_name!r}."
            )
            mapping, decision = _mapping_and_decision(
                source_release=regs_release,
                source_resource=source_resource,
                source_value=source_value,
                source_name=source_name,
                target_release=target_release,
                target_resource=target_resource,
                target_field=target_field,
                target_value=source_value,
                target_name=target_name,
                basis=basis,
                reasoning=reasoning,
                non_emitted_candidates=other_candidates,
            )
            mappings.append(mapping)
            candidate_decisions.append(decision)
            continue

        original_residue.add(source_value)
        adoption = residue_adoptions.get(source_value)
        abstention = residue_abstentions.get(source_value)
        if adoption is not None:
            if adoption.source_name != source_name:
                raise ValueError(
                    f"agency identity source name drifted for {source_value}: {source_name!r}"
                )
            target_release = by_key[adoption.target_release_key]
            target_resource = resources[adoption.target_release_key][
                adoption.target_resource
            ]
            target_field, target_name = _publisher_name(
                target_release.key,
                target_resource,
            )
            if target_name != adoption.target_name:
                raise ValueError(
                    f"agency identity target name drifted for {source_value}: {target_name!r}"
                )
            mapping, decision = _mapping_and_decision(
                source_release=regs_release,
                source_resource=source_resource,
                source_value=source_value,
                source_name=source_name,
                target_release=target_release,
                target_resource=target_resource,
                target_field=target_field,
                target_value=target_name,
                target_name=target_name,
                basis=adoption.basis,
                reasoning=adoption.reasoning,
                non_emitted_candidates=adoption.non_emitted_candidates,
            )
            mappings.append(mapping)
            candidate_decisions.append(decision)
            continue
        if abstention is None:
            raise ValueError(f"agency identity residue lacks a decision for {source_value}")
        if abstention.source_name != source_name:
            raise ValueError(
                f"agency identity abstention name drifted for {source_value}: {source_name!r}"
            )
        decision = {
            "decidedAt": REGULATIONS_GOV_AGENCY_IDENTITY_ASSERTED_AT,
            "decision": "abstained",
            "reason": abstention.reason,
            "reasoning": abstention.reasoning,
            "reviewerIri": REGULATIONS_GOV_AGENCY_IDENTITY_REVIEWER_IRI,
            "sourceParentResource": _parent_by_subject(regs_release).get(
                source_resource.iri
            ),
            "sourcePublisherName": source_name,
            "sourceResource": source_resource.iri,
            "sourceValue": source_value,
        }
        if abstention.closest_candidate is not None:
            decision["closestNonAdoptedCandidate"] = dict(
                abstention.closest_candidate
            )
        candidate_decisions.append(_frozen_mapping(decision))

    expected_residue = set(residue_adoptions) | set(residue_abstentions)
    if original_residue != expected_residue:
        raise ValueError(
            "agency identity 52-value residue drifted: "
            f"expected={sorted(expected_residue)!r}, observed={sorted(original_residue)!r}"
        )
    if len(mappings) != EXPECTED_IDENTITY_MAPPING_COUNT:
        raise ValueError(
            f"agency identity expected {EXPECTED_IDENTITY_MAPPING_COUNT} mappings; "
            f"built {len(mappings)}"
        )
    abstention_count = sum(
        decision["decision"] == "abstained" for decision in candidate_decisions
    )
    if abstention_count != EXPECTED_IDENTITY_ABSTENTION_COUNT:
        raise ValueError("agency identity abstention count drifted")
    if len(candidate_decisions) != EXPECTED_IDENTITY_CANDIDATE_COUNT:
        raise ValueError("agency identity candidate accounting is incomplete")

    inputs = _mapping_inputs(by_key)
    input_roles = tuple(pin.role for pin in inputs)
    source_release_digest = canonical_digest(
        [
            {
                "byteLength": pin.byte_length,
                "role": pin.role,
                "sha256": pin.sha256,
                "sourceIri": pin.source_iri,
            }
            for pin in inputs
        ]
    )
    basis_counts: dict[str, int] = defaultdict(int)
    for decision in candidate_decisions:
        if decision["decision"] == "adopted":
            basis_counts[str(decision["basis"])] += 1
    return RegistryMappingRelease(
        key=REGULATIONS_GOV_AGENCY_IDENTITY_RELEASE_KEY,
        resource_id=REGULATIONS_GOV_AGENCY_IDENTITY_RESOURCE_ID,
        source_module="refspec.atlas.v3_registry_alignments_entity",
        ring="entity",
        scope="captureSubset",
        issued="2026-08-16",
        source_release_iri=(
            "urn:ref:registry-mapping-release:regulations-gov-agency-identity:"
            + source_release_digest.removeprefix("sha256:")
        ),
        source_release_digest=source_release_digest,
        source_release_input_roles=input_roles,
        inputs=inputs,
        mappings=tuple(mappings),
        editorial_policy={
            "admission": (
                "assert one regulations.gov-to-held-roster atlas:sameEntityAs "
                "claim when exact acronym evidence or per-value publisher-name "
                "adjudication gives a defensible identity"
            ),
            "abstention": (
                "abstain only for an unbroken collision or when no held roster "
                "contains the same entity"
            ),
            "candidateAccounting": "record all 331 decisions and every non-emitted candidate",
            "direction": "regulations.gov subject to one FR, eCFR, or Federal Hierarchy object",
            "evidence": "E4 humanReview with both publisher records and a specific reasoning sentence",
            "predicate": ATLAS_SAME_ENTITY_AS,
            "version": "ref-038-agency-identity-adjudication-v2",
        },
        metadata={
            "adoptedAssertionCount": len(mappings),
            "abstentionCount": abstention_count,
            "basisCounts": dict(sorted(basis_counts.items())),
            "candidateDecisions": candidate_decisions,
            "candidateDecisionCount": len(candidate_decisions),
            "decisionRecord": REGULATIONS_GOV_AGENCY_IDENTITY_DECISION_RECORD,
            "evidenceRecordCount": sum(len(mapping.evidence) for mapping in mappings),
            "inverseAssertionCount": 0,
            "reviewedRosterReleaseKeys": list(
                agency_projection.AGENCY_ROSTER_RELEASE_KEYS
            ),
            "subunitPredicateEmitted": False,
        },
    )


__all__ = [
    "AGENCY_ABSTENTION_REASONS",
    "AGENCY_DECISION_BASES",
    "ATLAS_SAME_ENTITY_AS",
    "EXPECTED_IDENTITY_ABSTENTION_COUNT",
    "EXPECTED_IDENTITY_CANDIDATE_COUNT",
    "EXPECTED_IDENTITY_MAPPING_COUNT",
    "REGULATIONS_GOV_AGENCY_IDENTITY_ASSERTED_AT",
    "REGULATIONS_GOV_AGENCY_IDENTITY_DECISION_RECORD",
    "REGULATIONS_GOV_AGENCY_IDENTITY_RELEASE_KEY",
    "REGULATIONS_GOV_AGENCY_IDENTITY_RESOURCE_ID",
    "REGULATIONS_GOV_AGENCY_IDENTITY_REVIEWER_IRI",
    "RESIDUE_ABSTENTIONS",
    "RESIDUE_ADOPTIONS",
    "AgencyDecisionBasis",
    "ResidueAbstention",
    "ResidueAdoption",
    "load_regulations_gov_agency_identity_mapping_release",
]
