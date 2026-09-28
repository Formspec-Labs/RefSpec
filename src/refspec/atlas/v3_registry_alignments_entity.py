"""E4 entity-identity mappings for the regulations.gov agency roster.

REF-038 keeps each identity claim in an asserted entity-ring mapping release.
The release uses only ``atlas:sameEntityAs`` and asserts each regulations.gov
resource to one held Federal Register, eCFR, or Federal Hierarchy resource.
Candidate decisions in release metadata account for every regulations.gov id,
including the values for which no held roster contains the same entity.

REF-072's agency registry release sits beside it, never revising it: the
owner's batch-1 decisions become Federal Register identity bridges in REF-038's
shape, dated organization change events, and recorded non-emissions, read by
digest from the committed candidates and decisions and refused whole if any
decision is missing or stale.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, NamedTuple, cast
from urllib.parse import quote

from refspec.atlas import agency_projection
from refspec.atlas.v3_source_data import (
    RegistryChangeEvent,
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
from refspec.input_pin import read_verified_file_pin

REGULATIONS_GOV_AGENCY_IDENTITY_RELEASE_KEY = (
    "regulations-gov-agency-identity-2026-08-16"
)
REGULATIONS_GOV_AGENCY_IDENTITY_RESOURCE_ID = (
    "regulations-gov-agency-identity"
)
AGENCY_REGISTRY_RELEASE_KEY = agency_projection.AGENCY_REGISTRY_RELEASE_KEY
ENTITY_REGISTRY_MAPPING_RELEASE_KEYS = frozenset(
    {REGULATIONS_GOV_AGENCY_IDENTITY_RELEASE_KEY, AGENCY_REGISTRY_RELEASE_KEY}
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

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ADJUDICATION_LOGICAL_PATH = (
    "research/evidence/agency-identifier-census-2026-08-16/census.json"
)
_ADJUDICATION_SHA256 = (
    "sha256:11c58cf263496e9c0a320ab4fb1985ff7e17214d6a43996b6722336164143339"
)
_ADJUDICATION_BYTE_LENGTH = 370_256
_ADJUDICATION_SOURCE_IRI = (
    "urn:ref:source-artifact:11c58cf263496e9c0a320ab4fb1985ff7e17214d6a43996b6722336164143339"
)

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


def publisher_name(release_key: str, resource: RegistryResource) -> tuple[str, str]:
    """The sealed publisher-name field and its value for one agency roster resource."""

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
    source_field: str = "attributes.id",
    decided_at: str = REGULATIONS_GOV_AGENCY_IDENTITY_ASSERTED_AT,
    decision_record: str = REGULATIONS_GOV_AGENCY_IDENTITY_DECISION_RECORD,
    shared_extra: Mapping[str, Any] | None = None,
) -> tuple[RegistryMappingEvidence, RegistryMappingEvidence]:
    """Two E4 human-review records, one per publisher record, sharing one decision.

    The defaults are REF-038's; the agency registry passes its own decision
    record, day, subject name field and the owner's decision fields.
    """

    triple = {
        "subjectIri": mapping_subject,
        "predicateIri": ATLAS_SAME_ENTITY_AS,
        "objectIri": mapping_object,
    }
    shared_payload: dict[str, Any] = {
        **triple,
        **(shared_extra or {}),
        "decidedAt": decided_at,
        "decision": "adopted",
        "decisionBasis": basis,
        "decisionRecord": decision_record,
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
                field=source_field,
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
                attested_at=decided_at,
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
    source_parents: Mapping[str, str],
    non_emitted_candidates: Sequence[Mapping[str, str]] = (),
    source_field: str = "attributes.id",
    decided_at: str = REGULATIONS_GOV_AGENCY_IDENTITY_ASSERTED_AT,
    decision_record: str = REGULATIONS_GOV_AGENCY_IDENTITY_DECISION_RECORD,
    shared_extra: Mapping[str, Any] | None = None,
    decision_extra: Mapping[str, Any] | None = None,
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
        source_field=source_field,
        decided_at=decided_at,
        decision_record=decision_record,
        shared_extra=shared_extra,
    )
    mapping = RegistryMapping(
        subject=source_resource.iri,
        predicate=ATLAS_SAME_ENTITY_AS,
        object=target_resource.iri,
        subject_atlas_release_iri=source_release.atlas_release_iri,
        object_atlas_release_iri=target_release.atlas_release_iri,
        asserted_at=decided_at,
        evidence=evidence,
    )
    decision: dict[str, Any] = {
        **(decision_extra or {}),
        "basis": basis,
        "decidedAt": decided_at,
        "decision": "adopted",
        "objectPublisherName": target_name,
        "objectReleaseKey": target_release.key,
        "objectResource": target_resource.iri,
        "predicateIri": ATLAS_SAME_ENTITY_AS,
        "reasoning": reasoning,
        "reviewerIri": REGULATIONS_GOV_AGENCY_IDENTITY_REVIEWER_IRI,
        "sourcePublisherName": source_name,
        "sourceResource": source_resource.iri,
        "sourceValue": source_value,
    }
    # The caller derives the source roster's parent map once and passes it in:
    # rebuilding it here walked the whole roster once per mapping.
    source_parent_resource = source_parents.get(source_resource.iri)
    if source_parent_resource is not None:
        decision["sourceParentResource"] = source_parent_resource
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
    inputs.append(
        RegistryInputPin(
            path=_REPOSITORY_ROOT / _ADJUDICATION_LOGICAL_PATH,
            logical_path=_ADJUDICATION_LOGICAL_PATH,
            sha256=_ADJUDICATION_SHA256,
            byte_length=_ADJUDICATION_BYTE_LENGTH,
            source_iri=_ADJUDICATION_SOURCE_IRI,
            role="ownerAdjudication",
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
    regs_parents = agency_projection.parent_by_subject(regs_release)
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
        _, source_name = publisher_name(regs_release.key, source_resource)
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
            _, target_name = publisher_name(target_release.key, target_resource)
            other_candidates = [
                {
                    "resource": iri,
                    "publisherName": publisher_name(
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
                source_parents=regs_parents,
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
            target_field, target_name = publisher_name(
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
                source_parents=regs_parents,
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
            "sourcePublisherName": source_name,
            "sourceResource": source_resource.iri,
            "sourceValue": source_value,
        }
        source_parent_resource = regs_parents.get(source_resource.iri)
        if source_parent_resource is not None:
            decision["sourceParentResource"] = source_parent_resource
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
    mapping_triples = {
        (mapping.subject, mapping.predicate, mapping.object)
        for mapping in mappings
    }
    inverse_assertion_count = sum(
        (object_iri, predicate, subject_iri) in mapping_triples
        for subject_iri, predicate, object_iri in mapping_triples
    )
    return RegistryMappingRelease(
        key=REGULATIONS_GOV_AGENCY_IDENTITY_RELEASE_KEY,
        resource_id=REGULATIONS_GOV_AGENCY_IDENTITY_RESOURCE_ID,
        source_module="refspec.registry.regulations_gov_agencies",
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
            "inverseAssertionCount": inverse_assertion_count,
            "reviewedRosterReleaseKeys": list(
                agency_projection.AGENCY_ROSTER_RELEASE_KEYS
            ),
            "subunitPredicateEmitted": False,
        },
    )


# ---------------------------------------------------------------------------
# REF-072: the agency registry, batch 1 -- the owner's decisions become
# assertions. The contract below is the one tools/assemble_agency_registry_batch_1.py
# renders the adjudication sheet from, so the sheet and the release read one
# file the same way.
# ---------------------------------------------------------------------------

AGENCY_REGISTRY_RESOURCE_ID = "agency-registry"
# The release's subject roster is the Federal Register's, as REF-038's is the
# regulations.gov roster's.
AGENCY_REGISTRY_SOURCE_MODULE = "refspec.registry.federal_register_native_controls"
AGENCY_REGISTRY_REVIEWER_IRI = REGULATIONS_GOV_AGENCY_IDENTITY_REVIEWER_IRI
AGENCY_REGISTRY_DECISION_RECORD = "docs/decisions.md#ref-072"
# What the owner decided on: plans/agency-registry-batch-1-candidates.json's
# candidates_digest, recomputed here, never read off the file.
AGENCY_REGISTRY_CANDIDATES_DIGEST = "sha256:7fe88a9167a9363f5c2bfdcd3911953b7323abe1564d40586991c9612f95f4bc"
AGENCY_REGISTRY_CANDIDATES_PATH = "plans/agency-registry-batch-1-candidates.json"
AGENCY_REGISTRY_DECISIONS_PATH = "plans/agency-registry-batch-1-decisions.json"
_AGENCY_REGISTRY_CANDIDATES_SHA256 = "sha256:6bb7c2d4dc818b24cb92b1e220704b9d9acb9afc6be6fc400c0daccde14b71d2"
_AGENCY_REGISTRY_CANDIDATES_BYTE_LENGTH = 191_706
_AGENCY_REGISTRY_DECISIONS_SHA256 = "sha256:a454ea277d533ce25a331a996a676d58f0bd2573700a43893a1f52b6c8938098"
_AGENCY_REGISTRY_DECISIONS_BYTE_LENGTH = 6_744
# The adjudicable content; replay-derived counts sit outside it on purpose.
CANDIDATES_DIGEST_COVERS = ("candidates", "events", "non_emissions", "no_fr_bridge")
EXPECTED_AGENCY_REGISTRY_BRIDGE_COUNT = 13
EXPECTED_AGENCY_REGISTRY_EVENT_COUNT = 9
EXPECTED_AGENCY_REGISTRY_NON_EMISSION_COUNT = 4
EXPECTED_AGENCY_REGISTRY_DECISION_COUNT = 26
DECISIONS_SCHEMA_VERSION = "refspec-agency-registry-batch-1-decisions/2"
DECISION_CHANNELS = ("questionTool", "decisionsFile")
# A public record states its own date by enactment or publication; a roster
# description does not. An event rests on at least one dated record.
DATED_PUBLIC_RECORD_KINDS = frozenset({"statute", "reorganizationPlan", "frNotice", "frDocument"})

# What each answer the owner gave does. The generic answers mean the same on
# every item; a numbered option means what its text says, and that text is
# inside the item's content_digest, so a reworded option stales the decision
# before this table can misread it. An answer with no row here -- no, wrong-date,
# not-a-succession, overrule, another option -- refuses the release: it needs a
# release change, never a guess.
_ANSWER_OUTCOMES = {"yes": "bridge", "accept": "event", "accept-every-row": "event", "confirm": "nonEmission"}
_OPTION_OUTCOMES: Mapping[tuple[str, str], tuple[str, agency_projection.AgencyRegistryNonEmissionReason | None]] = {
    ("same:fr151:ecfr:export-import-bank", "2"): ("nonEmission", "sameOrganizationReverseLookupCostRejected"),
    ("same:fr296:fh:300000070", "1"): ("nonEmission", "heldForStatutoryRenameBasis"),
    ("event:fr564", "1"): ("event", None),
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


class Decisions(NamedTuple):
    """The owner's recorded answers: bound to the current candidates, or stale (kept, never dropped)."""

    current: Mapping[str, Mapping[str, Any]]
    stale: Mapping[str, Mapping[str, Any]]


NO_DECISIONS = Decisions({}, {})
_DECISION_REQUIRED = {"answer", "decided_on", "content_digest", "channel"}
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NEEDS_NOTE = frozenset({"wrong-date", "wrong-functions"})


def decision_digests(report: Mapping[str, Any]) -> dict[str, str]:
    """Every decidable id and the content digest its decisions bind to."""

    entries = [row for row in report["candidates"] if row["relation"] == "sameEntityAs"]
    entries += [*report["non_emissions"], *report["events"]]
    digests = {entry.get("candidate_id") or entry["event_id"]: entry["content_digest"] for entry in entries}
    digests.update({row["value_id"]: row["content_digest"] for row in report["no_fr_bridge"]})
    return digests


def decision_answers(report: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """Every decidable id and the answers the sheet offers for it; event rows are never decided alone."""

    answers: dict[str, tuple[str, ...]] = {}
    for row in report["candidates"]:
        if row["relation"] != "sameEntityAs":
            continue
        question = row.get("owner_question")
        answers[row["candidate_id"]] = (
            ("yes", "no") if question is None else tuple(str(n) for n in range(1, len(question["options"]) + 1))
        )
    for row in report["non_emissions"]:
        answers[row["candidate_id"]] = ("confirm", "overrule")
    for row in report["no_fr_bridge"]:
        answers[row["value_id"]] = ("confirm", "overrule")
    for event in report["events"]:
        question = event.get("owner_question")
        if question is not None:
            answers[event["event_id"]] = tuple(str(n) for n in range(1, len(question["options"]) + 1))
        elif event["group"] == "C":
            answers[event["event_id"]] = ("accept", "wrong-date", "not-a-succession")
        else:
            answers[event["event_id"]] = ("accept-every-row", "wrong-date", "wrong-functions", "not-a-succession")
    return answers


def load_decisions(path: Path, report: Mapping[str, Any]) -> Decisions:
    """Read the owner's decisions file; an absent file is no decisions.

    Each decision names a decidable id and is bound to the ``content_digest`` of
    that row or event as it stood when decided. When its own row or event changes,
    the decision is stale: returned and rendered as stale, never dropped. A change
    to any other row leaves it current. An id that names no decidable row or
    event is refused, so a removed or re-keyed row is reconciled by hand. A
    current decision must give one of the answers the sheet offers.
    """

    if not path.is_file():
        return NO_DECISIONS
    return decisions_from_json(json.loads(path.read_text()), report, label=str(path))


def decisions_from_json(data: Any, report: Mapping[str, Any], *, label: str) -> Decisions:
    """Bind one parsed decisions document to the candidates it decides; ``load_decisions`` without the read."""

    _require(isinstance(data, dict) and set(data) == {"schema_version", "reviewer_iri", "decisions"}, "decisions file fields differ")
    _require(data["schema_version"] == DECISIONS_SCHEMA_VERSION, f"decisions file is not {DECISIONS_SCHEMA_VERSION}")
    _require(data["reviewer_iri"] == AGENCY_REGISTRY_REVIEWER_IRI, "decisions come only from the owner's reviewer IRI")
    _require(isinstance(data["decisions"], dict), "decisions must be an object keyed by candidate or event id")
    answers = decision_answers(report)
    digests = decision_digests(report)
    unknown = sorted(set(data["decisions"]) - set(answers))
    if unknown:
        event_of = {row["candidate_id"]: row["event_id"] for row in report["candidates"] if "event_id" in row}
        named = [f"{key} (a row of {event_of[key]}; decide the event)" if key in event_of else key for key in unknown]
        raise ValueError(
            f"{label}: decisions for unknown ids {', '.join(named)}; a removed or re-keyed row is reconciled by hand"
        )
    current: dict[str, Mapping[str, Any]] = {}
    stale: dict[str, Mapping[str, Any]] = {}
    for key, decision in sorted(data["decisions"].items()):
        _require(isinstance(decision, dict), f"decision {key!r} must be an object")
        fields = set(decision)
        _require(_DECISION_REQUIRED <= fields <= _DECISION_REQUIRED | {"note"}, f"decision {key!r} fields differ")
        _require(bool(_DIGEST_RE.fullmatch(str(decision["content_digest"]))), f"decision {key!r} digest malformed")
        _require(bool(_DATE_RE.fullmatch(str(decision["decided_on"]))), f"decision {key!r} date is not YYYY-MM-DD")
        _require(decision["channel"] in DECISION_CHANNELS, f"decision {key!r} channel is not one of {DECISION_CHANNELS}")
        _require("note" not in decision or (isinstance(decision["note"], str) and decision["note"]), f"decision {key!r} note is empty")
        if decision["content_digest"] != digests[key]:
            stale[key] = decision
            continue
        _require(decision["answer"] in answers[key], f"decision {key!r} answers {decision['answer']!r}, not one of {answers[key]}")
        _require(decision["answer"] not in _NEEDS_NOTE or "note" in decision, f"decision {key!r} needs a note saying what is wrong")
        current[key] = decision
    return Decisions(current, stale)


class AgencyRegistryOutcome(NamedTuple):
    """What one owner-decided item became: a bridge, an event, or a recorded non-emission."""

    item_id: str
    outcome: Literal["bridge", "event", "nonEmission"]
    reason: str | None
    decision: Mapping[str, Any]


def _plan_pin(logical_path: str, sha256: str, byte_length: int, role: str) -> RegistryInputPin:
    return RegistryInputPin(
        path=_REPOSITORY_ROOT / logical_path,
        logical_path=logical_path,
        sha256=sha256,
        byte_length=byte_length,
        source_iri="urn:ref:source-artifact:" + sha256.removeprefix("sha256:"),
        role=role,
    )


_AGENCY_REGISTRY_CANDIDATES_PIN = _plan_pin(
    AGENCY_REGISTRY_CANDIDATES_PATH,
    _AGENCY_REGISTRY_CANDIDATES_SHA256,
    _AGENCY_REGISTRY_CANDIDATES_BYTE_LENGTH,
    "ownerCandidates",
)
_AGENCY_REGISTRY_DECISIONS_PIN = _plan_pin(
    AGENCY_REGISTRY_DECISIONS_PATH,
    _AGENCY_REGISTRY_DECISIONS_SHA256,
    _AGENCY_REGISTRY_DECISIONS_BYTE_LENGTH,
    "ownerDecisions",
)


def _read_plan(pin: RegistryInputPin) -> Any:
    return json.loads(
        read_verified_file_pin(
            pin.path,
            expected_sha256=pin.sha256,
            expected_byte_length=pin.byte_length,
            logical_path=pin.logical_path,
        )
    )


def agency_registry_outcomes(
    candidates: Mapping[str, Any],
    decisions_document: Any,
) -> tuple[AgencyRegistryOutcome, ...]:
    """Every owner-decided item and what it becomes, or a refusal; decides nothing itself.

    Refuses candidates whose recomputed digest is not the one the owner decided
    on, any decision that is stale or missing, and any answer the release has
    no rule for. The parity is exact: every decidable item has one outcome.
    """

    covered = {key: candidates[key] for key in CANDIDATES_DIGEST_COVERS}
    observed = canonical_digest(covered)
    _require(
        observed == AGENCY_REGISTRY_CANDIDATES_DIGEST == candidates.get("candidates_digest"),
        f"agency registry candidates digest {observed} is not the decided {AGENCY_REGISTRY_CANDIDATES_DIGEST}",
    )
    decisions = decisions_from_json(decisions_document, candidates, label=AGENCY_REGISTRY_DECISIONS_PATH)
    _require(not decisions.stale, f"stale decisions refuse the release: {', '.join(sorted(decisions.stale))}")
    missing = sorted(set(decision_digests(candidates)) - set(decisions.current))
    _require(not missing, f"undecided items refuse the release: {', '.join(missing)}")
    outcomes = []
    for item_id, decision in sorted(decisions.current.items()):
        answer = str(decision["answer"])
        outcome, reason = _OPTION_OUTCOMES.get((item_id, answer), (_ANSWER_OUTCOMES.get(answer), None))
        _require(outcome is not None, f"{item_id} answer {answer!r} has no rule in this release; change the release")
        outcomes.append(AgencyRegistryOutcome(item_id, outcome, reason, _frozen_mapping(dict(decision))))
    return tuple(outcomes)


def _owner_decision(
    item_id: str,
    decision: Mapping[str, Any],
    content_digest: str,
    decisions_pin: RegistryInputPin,
) -> dict[str, Any]:
    """The owner's decision as the evidence cites it: the answer, when, how, and the file it lives in."""

    return {
        "answer": decision["answer"],
        "channel": decision["channel"],
        "contentDigest": content_digest,
        "decidedOn": decision["decided_on"],
        "decisionsFile": decisions_pin.logical_path,
        "decisionsFileSha256": decisions_pin.sha256,
        "itemId": item_id,
        **({"note": decision["note"]} if "note" in decision else {}),
    }


def _decided_at(decision: Mapping[str, Any]) -> str:
    """The instant an item's evidence attests: the first instant, UTC, of the day the owner decided it."""

    return f"{decision['decided_on']}T00:00:00+00:00"


def _roster_record(
    by_key: Mapping[str, RegistryRelease],
    resources: Mapping[str, Mapping[str, RegistryResource]],
    parents: Mapping[str, Mapping[str, str]],
    record: Mapping[str, Any],
) -> tuple[RegistryRelease, RegistryResource, str, str]:
    """Re-derive one candidate endpoint from its pinned roster; refuse a drifted name or parent."""

    release_key = str(record["release_key"])
    resource = resources[release_key].get(str(record["resource_iri"]))
    _require(resource is not None, f"{record['resource_iri']} is absent from {release_key}")
    assert resource is not None
    field, name = publisher_name(release_key, resource)
    _require(
        (field, name) == (record["name_field"], record["publisher_name"]),
        f"{resource.iri} sealed publisher name drifted from the decided {record['publisher_name']!r}",
    )
    decided_parent = record["parent"]["resource_iri"] if record.get("parent") else None
    _require(
        parents[release_key].get(resource.iri) == decided_parent,
        f"{resource.iri} publisher parent drifted from the decided {decided_parent!r}",
    )
    return by_key[release_key], resource, field, name


def _bridge_endpoints(
    item: Mapping[str, Any],
    by_key: Mapping[str, RegistryRelease],
    resources: Mapping[str, Mapping[str, RegistryResource]],
    parents: Mapping[str, Mapping[str, str]],
) -> tuple[tuple[RegistryRelease, RegistryResource, str, str], tuple[RegistryRelease, RegistryResource, str, str]]:
    """Both re-derived endpoints of one bridge, refused unless it runs Federal Register to eCFR or Federal Hierarchy."""

    source = _roster_record(by_key, resources, parents, item["source"])
    target = _roster_record(by_key, resources, parents, item["target"])
    _require(
        source[0].key == FR and target[0].key in {ECFR, FH},
        f"{item['candidate_id']} is not a Federal Register-to-eCFR or Federal Hierarchy bridge",
    )
    return source, target


def _parent_record(record: Mapping[str, Any]) -> dict[str, str] | None:
    parent = record.get("parent")
    return None if not parent else {"publisherName": parent["publisher_name"], "resourceIri": parent["resource_iri"]}


def _change_event(
    event: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    decision: Mapping[str, Any],
    *,
    by_key: Mapping[str, RegistryRelease],
    resources: Mapping[str, Mapping[str, RegistryResource]],
    parents: Mapping[str, Mapping[str, str]],
    decisions_pin: RegistryInputPin,
) -> tuple[RegistryChangeEvent, dict[str, Any]]:
    """One accepted event: its originals, every result with the functions it took, and one E4 record per public record.

    Every organization an event names must be a Federal Register roster record:
    the rename rule (design note section 3) makes a succession link two records
    one roster holds, and batch 1's are all the Register's. Anything else is
    refused, never silently pinned to the Register's release.
    """

    for record in (*event["originals"], *(row[side] for row in rows for side in ("source", "target"))):
        _require(
            record["release_key"] == FR,
            f"{event['event_id']} names {record['resource_iri']}, which is not a Federal Register roster record",
        )
        _roster_record(by_key, resources, parents, record)
    originals = [str(record["resource_iri"]) for record in event["originals"]]
    results = [str(row["target"]["resource_iri"]) for row in rows]
    records = list(event["public_records"])
    _require(
        any(record["kind"] in DATED_PUBLIC_RECORD_KINDS for record in records),
        f"{event['event_id']} rests on no dated public record",
    )
    _require(all(str(record["url"]).startswith("https://") for record in records), f"{event['event_id']} cites a non-https record")
    event_payload = {
        "dateBasis": event["date_basis"],
        "effectiveDate": event["effective_date"],
        "eventId": event["event_id"],
        "originals": [
            {"publisherName": record["publisher_name"], "resourceIri": record["resource_iri"]} for record in event["originals"]
        ],
        # A rename names no functions: the key is absent rather than null, so
        # the payload and the release metadata carry no null anywhere.
        "results": [
            {
                **({"functionsTaken": row["functions_taken"]} if row["functions_taken"] is not None else {}),
                "publisherName": row["target"]["publisher_name"],
                "reasoning": row["reasoning"],
                "resourceIri": row["target"]["resource_iri"],
                "rowId": row["candidate_id"],
            }
            for row in rows
        ],
    }
    owner_decision = _owner_decision(str(event["event_id"]), decision, str(event["content_digest"]), decisions_pin)
    decided_at = _decided_at(decision)
    evidence = tuple(
        RegistryMappingEvidence(
            source_locator=str(record["url"]),
            source_digest=_AGENCY_REGISTRY_CANDIDATES_SHA256,
            native_payload={
                "decidedAt": decided_at,
                "decision": "adopted",
                "decisionRecord": AGENCY_REGISTRY_DECISION_RECORD,
                "event": event_payload,
                "evidenceTier": "E4",
                "ownerDecision": owner_decision,
                "publicRecord": dict(record),
                "reviewerIri": AGENCY_REGISTRY_REVIEWER_IRI,
            },
            review_warrant="humanReview",
            reviewer_iri=AGENCY_REGISTRY_REVIEWER_IRI,
            attested_at=decided_at,
        )
        for record in records
    )
    fr_release = by_key[FR]
    change = RegistryChangeEvent(
        originals=tuple(originals),
        results=tuple(results),
        release_iris=dict.fromkeys((*originals, *results), fr_release.atlas_release_iri),
        effective_date=str(event["effective_date"]),
        asserted_at=decided_at,
        evidence=evidence,
    )
    metadata = {
        **event_payload,
        "decision": "event",
        # Each original's roster parent, as a bridge's decision carries its
        # subject's: sealed in the candidates and re-derived from the roster
        # above, which refuses drift. Metadata only, so the evidence the owner
        # reviewed is unchanged; a top-level original has no key, never a null.
        "originalParents": {
            str(record["resource_iri"]): parent
            for record in event["originals"]
            if (parent := _parent_record(record)) is not None
        },
        "ownerDecision": owner_decision,
        "publicRecords": records,
    }
    return change, metadata


def _non_emission(
    outcome: AgencyRegistryOutcome,
    item: Mapping[str, Any],
    owner_decision: Mapping[str, Any],
) -> Mapping[str, Any]:
    """One decided item that emits nothing, with the reason in the owner's own terms.

    A numbered option's text is its reasoning; a confirmed withdrawal keeps the
    reason it was proposed with and its closest alternative, and a confirmed
    no-bridge value its reason code and reasoning.
    """

    if outcome.reason is not None:
        reason = outcome.reason
        reasoning = item["owner_question"]["options"][int(outcome.decision["answer"]) - 1]
    elif "value_id" in item:
        reason, reasoning = item["reason"], item["reasoning"]
    else:
        reason, reasoning = "withdrawn", item["reason"]
    _require(
        reason in agency_projection.AGENCY_REGISTRY_NON_EMISSION_REASONS,
        f"{outcome.item_id} non-emission reason {reason!r} is outside the closed vocabulary",
    )
    row: dict[str, Any] = {
        "candidateId": outcome.item_id,
        "decision": "nonEmission",
        "ownerDecision": dict(owner_decision),
        "reason": reason,
        "reasoning": reasoning,
    }
    if "source" in item:
        row["sourceResource"] = item["source"]["resource_iri"]
        row["objectResource"] = item["target"]["resource_iri"]
    else:
        row["sourceValue"] = item["value"]
    if "closest_alternative" in item:
        row["closestAlternative"] = dict(item["closest_alternative"])
    return _frozen_mapping(row)


def load_agency_registry_mapping_release(
    releases: Sequence[RegistryRelease],
) -> RegistryMappingRelease:
    """Emit exactly the owner's batch-1 decisions: 13 bridges, 9 events, 4 recorded non-emissions.

    Candidates never enter the release: it reads the owner's decisions and the
    candidate content they are bound to, both by digest, and re-derives every
    publisher name and parent from the pinned rosters. Bridges keep REF-038's
    shape -- one way, Federal Register subject, a typed basis, both sealed
    names, both parents, two E4 records -- and cite the decisions file. Nothing
    here revises REF-038's release or feeds its projection.
    """

    by_key = _releases_by_key(releases)
    resources = {key: _resources_by_iri(by_key[key]) for key in agency_projection.AGENCY_ROSTER_RELEASE_KEYS}
    parents = {key: agency_projection.parent_by_subject(by_key[key]) for key in agency_projection.AGENCY_ROSTER_RELEASE_KEYS}
    decisions_pin = _AGENCY_REGISTRY_DECISIONS_PIN
    candidates = _read_plan(_AGENCY_REGISTRY_CANDIDATES_PIN)
    outcomes = agency_registry_outcomes(candidates, _read_plan(decisions_pin))
    items: dict[str, Mapping[str, Any]] = {
        **{row["candidate_id"]: row for row in candidates["candidates"] if row["relation"] == "sameEntityAs"},
        **{row["candidate_id"]: row for row in candidates["non_emissions"]},
        **{row["value_id"]: row for row in candidates["no_fr_bridge"]},
        **{row["event_id"]: row for row in candidates["events"]},
    }
    rows_by_event: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in candidates["candidates"]:
        if "event_id" in row:
            rows_by_event[row["event_id"]].append(row)

    mappings: list[RegistryMapping] = []
    events: list[RegistryChangeEvent] = []
    item_decisions: list[Mapping[str, Any]] = []
    for outcome in outcomes:
        item = items[outcome.item_id]
        owner_decision = _owner_decision(outcome.item_id, outcome.decision, str(item["content_digest"]), decisions_pin)
        if outcome.outcome == "bridge":
            (
                (source_release, source_resource, source_field, source_name),
                (target_release, target_resource, target_field, target_name),
            ) = _bridge_endpoints(item, by_key, resources, parents)
            # A top-level organization has no parent key, never a null one.
            both_parents = {
                side: parent
                for side, parent in (("object", _parent_record(item["target"])), ("subject", _parent_record(item["source"])))
                if parent is not None
            }
            mapping, decision = _mapping_and_decision(
                source_release=source_release,
                source_resource=source_resource,
                source_value=source_name,
                source_name=source_name,
                target_release=target_release,
                target_resource=target_resource,
                target_field=target_field,
                target_value=target_name,
                target_name=target_name,
                basis=item["proposed_basis"],
                reasoning=str(item["reasoning"]),
                source_parents=parents[source_release.key],
                source_field=source_field,
                decided_at=_decided_at(outcome.decision),
                decision_record=AGENCY_REGISTRY_DECISION_RECORD,
                shared_extra={"ownerDecision": owner_decision, "parents": both_parents},
                decision_extra={
                    "candidateId": outcome.item_id,
                    "ownerDecision": owner_decision,
                    "parents": both_parents,
                },
            )
            mappings.append(mapping)
            item_decisions.append(decision)
        elif outcome.outcome == "event":
            _require(outcome.item_id in rows_by_event, f"{outcome.item_id} is not an event")
            change, metadata = _change_event(
                item,
                sorted(rows_by_event[outcome.item_id], key=lambda row: row["candidate_id"]),
                outcome.decision,
                by_key=by_key,
                resources=resources,
                parents=parents,
                decisions_pin=decisions_pin,
            )
            events.append(change)
            item_decisions.append(_frozen_mapping(metadata))
        else:
            item_decisions.append(_non_emission(outcome, item, owner_decision))

    counts = {
        "bridge": len(mappings),
        "event": len(events),
        "nonEmission": sum(row["decision"] == "nonEmission" for row in item_decisions),
    }
    _require(
        (counts["bridge"], counts["event"], counts["nonEmission"], len(item_decisions))
        == (
            EXPECTED_AGENCY_REGISTRY_BRIDGE_COUNT,
            EXPECTED_AGENCY_REGISTRY_EVENT_COUNT,
            EXPECTED_AGENCY_REGISTRY_NON_EMISSION_COUNT,
            EXPECTED_AGENCY_REGISTRY_DECISION_COUNT,
        )
        and sum(counts.values()) == len(item_decisions) == len(outcomes),
        f"agency registry parity differs: {counts} over {len(item_decisions)} decided items",
    )

    claims = {(mapping.subject, mapping.predicate, mapping.object) for mapping in mappings}
    # The five roster pins REF-038 reads, then the two owner artifacts in place
    # of its census adjudication.
    inputs = (*_mapping_inputs(by_key)[:-1], _AGENCY_REGISTRY_CANDIDATES_PIN, decisions_pin)
    source_release_digest = canonical_digest(
        [
            {"byteLength": pin.byte_length, "role": pin.role, "sha256": pin.sha256, "sourceIri": pin.source_iri}
            for pin in inputs
        ]
    )
    return RegistryMappingRelease(
        key=AGENCY_REGISTRY_RELEASE_KEY,
        resource_id=AGENCY_REGISTRY_RESOURCE_ID,
        source_module=AGENCY_REGISTRY_SOURCE_MODULE,
        ring="entity",
        scope="captureSubset",
        # Each item attests the day the owner decided it, and a mapping release
        # refuses evidence older than its issue day, so the release is issued
        # on its earliest decision day (2026-09-26 for all of batch 1).
        issued=min(str(outcome.decision["decided_on"]) for outcome in outcomes),
        source_release_iri=(
            "urn:ref:registry-mapping-release:agency-registry:" + source_release_digest.removeprefix("sha256:")
        ),
        source_release_digest=source_release_digest,
        source_release_input_roles=tuple(pin.role for pin in inputs),
        inputs=inputs,
        mappings=tuple(mappings),
        change_events=tuple(events),
        editorial_policy={
            "admission": (
                "emit exactly the owner's current decisions on the batch-1 candidates, bound to each item's "
                "content digest; refuse the release while any decision is missing or stale"
            ),
            "direction": "Federal Register subject to one eCFR or Federal Hierarchy object; no inverse",
            "events": (
                "one dated atlas:OrganizationChangeEvent per accepted succession, never folded into identity, "
                "with one E4 human-review record per public record"
            ),
            "evidence": "E4 humanReview by the owner, citing the decisions file and the channel",
            "nonEmission": "record every decided item that emits nothing, with the owner's reason",
            "predicate": ATLAS_SAME_ENTITY_AS,
            "version": "ref-072-agency-registry-batch-1-v1",
        },
        metadata={
            "bridgeCount": counts["bridge"],
            "candidatesDigest": AGENCY_REGISTRY_CANDIDATES_DIGEST,
            "decisionRecord": AGENCY_REGISTRY_DECISION_RECORD,
            "decisions": sorted(item_decisions, key=lambda row: str(row.get("candidateId") or row.get("eventId"))),
            "decidedItemCount": len(item_decisions),
            "eventCount": counts["event"],
            "evidenceRecordCount": sum(len(row.evidence) for row in (*mappings, *events)),
            "inverseAssertionCount": sum(
                (mapping.object, mapping.predicate, mapping.subject) in claims for mapping in mappings
            ),
            "nonEmissionCount": counts["nonEmission"],
            "reviewedRosterReleaseKeys": list(agency_projection.AGENCY_ROSTER_RELEASE_KEYS),
        },
    )


__all__ = [
    "AGENCY_ABSTENTION_REASONS",
    "AGENCY_DECISION_BASES",
    "AGENCY_REGISTRY_CANDIDATES_DIGEST",
    "AGENCY_REGISTRY_CANDIDATES_PATH",
    "AGENCY_REGISTRY_DECISIONS_PATH",
    "AGENCY_REGISTRY_DECISION_RECORD",
    "AGENCY_REGISTRY_RELEASE_KEY",
    "AGENCY_REGISTRY_RESOURCE_ID",
    "AGENCY_REGISTRY_REVIEWER_IRI",
    "ATLAS_SAME_ENTITY_AS",
    "CANDIDATES_DIGEST_COVERS",
    "DATED_PUBLIC_RECORD_KINDS",
    "DECISIONS_SCHEMA_VERSION",
    "DECISION_CHANNELS",
    "ENTITY_REGISTRY_MAPPING_RELEASE_KEYS",
    "EXPECTED_AGENCY_REGISTRY_BRIDGE_COUNT",
    "EXPECTED_AGENCY_REGISTRY_DECISION_COUNT",
    "EXPECTED_AGENCY_REGISTRY_EVENT_COUNT",
    "EXPECTED_AGENCY_REGISTRY_NON_EMISSION_COUNT",
    "EXPECTED_IDENTITY_ABSTENTION_COUNT",
    "EXPECTED_IDENTITY_CANDIDATE_COUNT",
    "EXPECTED_IDENTITY_MAPPING_COUNT",
    "NO_DECISIONS",
    "REGULATIONS_GOV_AGENCY_IDENTITY_ASSERTED_AT",
    "REGULATIONS_GOV_AGENCY_IDENTITY_DECISION_RECORD",
    "REGULATIONS_GOV_AGENCY_IDENTITY_RELEASE_KEY",
    "REGULATIONS_GOV_AGENCY_IDENTITY_RESOURCE_ID",
    "REGULATIONS_GOV_AGENCY_IDENTITY_REVIEWER_IRI",
    "RESIDUE_ABSTENTIONS",
    "RESIDUE_ADOPTIONS",
    "AgencyDecisionBasis",
    "AgencyRegistryOutcome",
    "Decisions",
    "ResidueAbstention",
    "ResidueAdoption",
    "agency_registry_outcomes",
    "decision_answers",
    "decision_digests",
    "decisions_from_json",
    "load_agency_registry_mapping_release",
    "load_decisions",
    "load_regulations_gov_agency_identity_mapping_release",
    "publisher_name",
]
