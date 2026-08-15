"""Atlas 3 adapters for documented rosters and controls (REF-032 follow-ups).

REF-032 removed observed inventories: distinct-value scans, first-page roster
slices, and set-distincts over sampled API responses. Its named follow-ups
land here, each captured from the publisher's own documented list:

* the Federal Register's documented document types and presidential-document
  subtypes, from the publisher's machine-readable OpenAPI description, with
  display names from the publisher's own type-facet endpoint;
* the Federal Register's complete agencies roster, with publisher-asserted
  ``parent_id`` relations carried as native entity relations;
* FCC's published Offices & Bureaus roster from fcc.gov — the documented
  successor of the removed observed five-bureau ECFS inventory, which had
  carried the abolished Common Carrier Bureau;
* the complete SAM.gov Federal Hierarchy organization roster — all 907
  records the public API reports, verified against the API's own per-level
  totals, with sub-tier -> department relations carried as native entity
  relations. REF-032's cross-ring tripwire names this roster as the intended
  carrier of a future entity -> subject crossing; no such publisher
  assignment exists yet, so no cross-ring relation is emitted;
* GAO's published /topics browse index — the complete 30-term topic
  vocabulary the publisher itself serves, each term carrying the publisher's
  own /topics/<slug> path and numeric Drupal taxonomy term id. The documented
  successor of the removed observed unit, which was one label observed on one
  report page under RefSpec-minted identity. This lands on the subject ring:
  the terms are general subject concepts with publisher-authored scope
  descriptions, and the identity is publisher-claimed, which is exactly what
  the deleted unit lacked.

Every adapter consumes exact publisher bytes through its registry parser,
verifies them against pinned digests, and states its capture scope. Publisher
anomalies are recorded verbatim in release metadata, never repaired.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from refspec.atlas.v3_registry_selection import (
    normalize_only_keys,
    select_declared_group,
    wants_group,
)
from refspec.atlas.v3_source_data import (
    RegistryInputPin,
    RegistryLabel,
    RegistryRelation,
    RegistryRelease,
    RegistryResource,
    canonical_digest,
)
from refspec.immutable import deep_freeze_json
from refspec.registry import fcc_bureaus_offices as fcc
from refspec.registry import federal_hierarchy_complete as fh
from refspec.registry import federal_register_native_controls as fr
from refspec.registry import gao_published_topics as gao

ATLAS_PARENT_ENTITY = "https://refspec.org/ns/atlas/v3#parentEntity"

_FR_FIXTURES = "tests/fixtures/federal_register_native_controls"
_FCC_FIXTURES = "tests/fixtures/fcc_bureaus_offices"
_FH_FIXTURES = "tests/fixtures/federal_hierarchy_complete"
_GAO_FIXTURES = "tests/fixtures/gao_published_topics"


def _json_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _json_value(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(child) for child in value]
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _frozen(value: Any) -> Mapping[str, Any]:
    frozen = deep_freeze_json(_json_value(value))
    if not isinstance(frozen, Mapping):
        raise TypeError("registry native payload must normalize to an object")
    return cast(Mapping[str, Any], frozen)


def _pin(
    root: Path,
    logical_path: str,
    *,
    sha256: str,
    byte_length: int,
    source_iri: str,
    role: str = "publisherSource",
) -> RegistryInputPin:
    pin = RegistryInputPin(
        path=root / logical_path,
        logical_path=logical_path,
        sha256=sha256,
        byte_length=byte_length,
        source_iri=source_iri,
        role=role,
    )
    pin.verify()
    return pin


def _release(
    *,
    key: str,
    resource_id: str,
    source_module: str,
    profile: str,
    ring: str,
    scope: str,
    issued: str,
    inputs: Sequence[RegistryInputPin],
    resources: Sequence[RegistryResource],
    relations: Sequence[RegistryRelation] = (),
    scheme_suffix: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    dropped_label_count: int = 0,
) -> RegistryRelease:
    if not resources:
        raise ValueError(f"registry adapter {key} emitted no members")
    for pin in inputs:
        pin.verify()
    digest = canonical_digest(
        {
            "inputs": [
                {
                    "logicalPath": pin.logical_path,
                    "sha256": pin.sha256,
                    "sourceIri": pin.source_iri,
                }
                for pin in inputs
            ],
            "key": key,
            "members": [resource.iri for resource in resources],
            "relations": [
                {
                    "subject": relation.subject,
                    "predicate": relation.predicate,
                    "object": relation.object,
                }
                for relation in relations
            ],
        }
    )
    token = digest.removeprefix("sha256:")
    scheme = f"urn:ref:atlas-resource-scheme:{resource_id}"
    if scheme_suffix is not None:
        scheme += ":" + scheme_suffix
    return RegistryRelease(
        key=key,
        resource_id=resource_id,
        source_module=source_module,
        profile=profile,
        ring=ring,
        scope=scope,  # type: ignore[arg-type]
        issued=issued,
        source_release_iri=f"urn:ref:registry-release:{resource_id}:{token}",
        source_release_digest=digest,
        atlas_release_iri=f"urn:ref:atlas-release:v3:{resource_id}:{token}",
        scheme_iri=scheme,
        inputs=tuple(inputs),
        resources=tuple(resources),
        relations=tuple(relations),
        dropped_label_count=dropped_label_count,
        metadata=_frozen(metadata or {}),
    )


def _label(value: str, source_path: str, role: str = "preferred") -> RegistryLabel:
    return RegistryLabel(
        value=value.strip(),
        role=role,  # type: ignore[arg-type]
        source_path=source_path,
    )


def _federal_register_releases(root: Path) -> tuple[RegistryRelease, ...]:
    documentation_pin = _pin(
        root,
        f"{_FR_FIXTURES}/fr-api-documentation-2026-08-15.json",
        sha256=fr.FR_API_DOCUMENTATION_2026_08_15.expected_sha256,
        byte_length=fr.FR_API_DOCUMENTATION_2026_08_15.expected_byte_length,
        source_iri=fr.FR_API_DOCUMENTATION_URL,
        role="publisherApiDescription",
    )
    facets_pin = _pin(
        root,
        f"{_FR_FIXTURES}/fr-documents-facets-type-2026-08-15.json",
        sha256=fr.FR_DOCUMENT_TYPE_FACETS_2026_08_15.expected_sha256,
        byte_length=fr.FR_DOCUMENT_TYPE_FACETS_2026_08_15.expected_byte_length,
        source_iri=fr.FR_DOCUMENT_TYPE_FACETS_URL,
        role="publisherDisplayNames",
    )
    agencies_pin = _pin(
        root,
        f"{_FR_FIXTURES}/fr-agencies-2026-08-15.json",
        sha256=fr.FR_AGENCIES_2026_08_15.expected_sha256,
        byte_length=fr.FR_AGENCIES_2026_08_15.expected_byte_length,
        source_iri=fr.FR_AGENCIES_URL,
        role="publisherRoster",
    )
    documentation_payload = documentation_pin.path.read_bytes()
    documented = fr.parse_documented_document_types(documentation_payload, facets_pin.path.read_bytes())
    subtypes = fr.parse_documented_presidential_document_types(documentation_payload)
    roster = fr.parse_agencies_roster(agencies_pin.path.read_bytes())
    documented_agency_slug_count = fr.crosscheck_documented_agency_slugs(documentation_payload, roster)

    enum_path = "components.schemas.DocumentType.items.enum"
    type_resources = tuple(
        RegistryResource(
            iri=f"urn:ref:federal-register-document-type:{quote(item.code, safe='')}",
            labels=(_label(item.display_name, f"{facets_pin.logical_path}#{item.code}"),),
            native_payload=_frozen(
                {
                    "code": item.code,
                    "displayName": item.display_name,
                    "enumPath": enum_path,
                }
            ),
            source_locator=documentation_pin.source_iri,
            source_digest=documentation_pin.sha256,
            notations=(item.code,),
        )
        for item in documented.types
    )
    subtype_enum_path = "components.schemas.PresidentialDocumentType.items.enum"
    subtype_resources = tuple(
        RegistryResource(
            iri=f"urn:ref:federal-register-presidential-document-type:{quote(code, safe='')}",
            labels=(_label(code, f"{documentation_pin.logical_path}#{subtype_enum_path}[{ordinal}]"),),
            native_payload=_frozen(
                {
                    "code": code,
                    "enumPath": subtype_enum_path,
                    "parentDocumentType": "PRESDOCU",
                }
            ),
            source_locator=documentation_pin.source_iri,
            source_digest=documentation_pin.sha256,
            notations=(code,),
        )
        for ordinal, code in enumerate(subtypes)
    )

    # Authority-scoped identifier rows are minted only under schemes the
    # registry descriptors declare as identifier authorities (an
    # ``identifierAuthority`` catalog resource, e.g.
    # treasury-account-symbol-structure); the build refuses any other scheme.
    # This resource is a code-scheme roster, not a declared identifier
    # authority, so the publisher's ``id`` and ``slug`` travel as notations
    # and verbatim payload fields instead of identifier rows.
    agency_resources: list[RegistryResource] = []
    for record in roster.records:
        source_path = f"{agencies_pin.logical_path}#agencies[{record.source_ordinal - 1}]"
        labels = [_label(record.name, source_path)]
        if record.short_name is not None and record.short_name.strip() and record.short_name.strip() != record.name.strip():
            labels.append(_label(record.short_name, source_path, role="alternate"))
        agency_resources.append(
            RegistryResource(
                iri=f"urn:ref:federal-register-agency:{record.agency_id}",
                labels=tuple(labels),
                native_payload=_frozen(record.raw),
                source_locator=agencies_pin.source_iri,
                source_digest=agencies_pin.sha256,
                definition=record.description,
                notations=(record.slug, str(record.agency_id)),
            )
        )
    agency_relations = tuple(
        RegistryRelation(
            subject=f"urn:ref:federal-register-agency:{record.agency_id}",
            predicate=ATLAS_PARENT_ENTITY,
            object=f"urn:ref:federal-register-agency:{record.parent_id}",
            source_payload={
                "sourceProperty": "parent_id",
                "childAgencyId": record.agency_id,
                "parentAgencyId": record.parent_id,
            },
        )
        for record in roster.records
        if record.parent_id is not None
    )

    return (
        _release(
            key="federal-register-documented-document-types-2026-08-15",
            resource_id="federal-register-native-controls",
            source_module="refspec.registry.federal_register_native_controls",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            issued="2026-08-15",
            inputs=(documentation_pin, facets_pin),
            resources=type_resources,
            scheme_suffix="documented-document-types",
            metadata={
                "documentedTypeCount": len(type_resources),
                "openapiVersion": documented.openapi_version,
                "publisherInfoVersion": documented.publisher_info_version,
                "enumPath": enum_path,
                "displayNameSource": facets_pin.source_iri,
                "facetDocumentCountsAtCapture": {
                    item.code: item.facet_document_count_at_capture for item in documented.types
                },
                "documentationPageUrl": fr.FR_DEVELOPER_DOCUMENTATION_PAGE_URL,
            },
        ),
        _release(
            key="federal-register-documented-presidential-document-types-2026-08-15",
            resource_id="federal-register-native-controls",
            source_module="refspec.registry.federal_register_native_controls",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            issued="2026-08-15",
            inputs=(documentation_pin,),
            resources=subtype_resources,
            scheme_suffix="documented-presidential-document-types",
            metadata={
                "documentedSubtypeCount": len(subtype_resources),
                "parentDocumentType": "PRESDOCU",
                "enumPath": subtype_enum_path,
                "openapiVersion": documented.openapi_version,
            },
        ),
        _release(
            key="federal-register-agencies-roster-2026-08-15",
            resource_id="federal-register-native-controls",
            source_module="refspec.registry.federal_register_native_controls",
            profile="codeScheme",
            ring="entity",
            scope="completeCapture",
            issued="2026-08-15",
            inputs=(agencies_pin, documentation_pin),
            resources=tuple(agency_resources),
            relations=agency_relations,
            scheme_suffix="agencies",
            metadata={
                "agencyCount": len(agency_resources),
                "parentRelationCount": len(agency_relations),
                "documentedAgencyEnumCount": documented_agency_slug_count,
                "publisherAnomalies": roster.anomalies,
            },
        ),
    )


def _fcc_releases(root: Path) -> tuple[RegistryRelease, ...]:
    page_pin = _pin(
        root,
        f"{_FCC_FIXTURES}/fcc-offices-bureaus-2026-08-15.html",
        sha256=fcc.FCC_OFFICES_BUREAUS_2026_08_15.expected_sha256,
        byte_length=fcc.FCC_OFFICES_BUREAUS_2026_08_15.expected_byte_length,
        source_iri=fcc.FCC_OFFICES_BUREAUS_URL,
        role="publisherRosterPage",
    )
    roster = fcc.parse_fcc_bureaus_offices(page_pin.path.read_bytes())
    resources = tuple(
        RegistryResource(
            iri=f"urn:ref:fcc-organizational-unit:{quote(unit.slug, safe='')}",
            labels=(_label(unit.name, f"{page_pin.logical_path}#{unit.slug}"),),
            native_payload=_frozen(unit),
            source_locator=page_pin.source_iri,
            source_digest=page_pin.sha256,
            definition=unit.description,
            notations=(unit.slug,),
        )
        for unit in roster.units
    )
    return (
        _release(
            key="fcc-bureaus-offices-roster-2026-08-15",
            resource_id="fcc-ecfs-native-controls",
            source_module="refspec.registry.fcc_bureaus_offices",
            profile="codeScheme",
            ring="entity",
            scope="completeCapture",
            issued="2026-08-15",
            inputs=(page_pin,),
            resources=resources,
            scheme_suffix="published-bureaus-offices",
            metadata={
                "officeCount": roster.office_count,
                "bureauCount": roster.bureau_count,
                "publisherSections": [title for title, _count in fcc.FCC_EXPECTED_SECTIONS],
                "replacesObservedInventoryNote": (
                    "The removed observed ECFS bureau inventory carried the abolished "
                    "Common Carrier Bureau; this published roster does not list it."
                ),
            },
        ),
    )


def _federal_hierarchy_releases(root: Path) -> tuple[RegistryRelease, ...]:
    page_pins = tuple(
        _pin(
            root,
            f"{_FH_FIXTURES}/fh-orgs-all-page-{index}.json",
            sha256=pin.expected_sha256,
            byte_length=pin.expected_byte_length,
            source_iri=pin.source_url,
            role="publisherRosterPage",
        )
        for index, pin in enumerate(fh.FH_COMPLETE_PAGES_2026_08_15)
    )
    dept_witness_pin = _pin(
        root,
        f"{_FH_FIXTURES}/fh-orgs-total-dept.json",
        sha256=fh.FH_TOTAL_DEPT_WITNESS_2026_08_15.expected_sha256,
        byte_length=fh.FH_TOTAL_DEPT_WITNESS_2026_08_15.expected_byte_length,
        source_iri=fh.FH_TOTAL_DEPT_WITNESS_2026_08_15.source_url,
        role="publisherTotalsWitness",
    )
    sub_tier_witness_pin = _pin(
        root,
        f"{_FH_FIXTURES}/fh-orgs-total-subtier.json",
        sha256=fh.FH_TOTAL_SUBTIER_WITNESS_2026_08_15.expected_sha256,
        byte_length=fh.FH_TOTAL_SUBTIER_WITNESS_2026_08_15.expected_byte_length,
        source_iri=fh.FH_TOTAL_SUBTIER_WITNESS_2026_08_15.source_url,
        role="publisherTotalsWitness",
    )
    roster = fh.parse_complete_roster(
        [pin.path.read_bytes() for pin in page_pins],
        dept_witness_pin.path.read_bytes(),
        sub_tier_witness_pin.path.read_bytes(),
    )

    # Authority-scoped identifier rows are minted only under schemes the
    # registry descriptors declare as identifier authorities; this resource
    # is a code-scheme roster, and the agencycode/cgac/oldfpdsofficecode
    # values it republishes belong to authorities (FPDS, Treasury CGAC) the
    # catalog does not carry -- claiming them under a federal-hierarchy
    # scheme would misattribute them. They travel verbatim in the native
    # payload, with the publisher's own fhorgid as the notation; the
    # provenance is stated in the release's identifierAuthorityNote.
    resources: list[RegistryResource] = []
    for record in roster.records:
        page_pin = page_pins[record.page_index]
        source_path = f"{page_pin.logical_path}#orglist[{record.source_ordinal}]"
        resources.append(
            RegistryResource(
                iri=f"urn:ref:federal-hierarchy-org:{record.fhorgid}",
                labels=(_label(record.name, source_path),),
                native_payload=_frozen(record.raw),
                source_locator=page_pin.source_iri,
                source_digest=page_pin.sha256,
                notations=(record.fhorgid,),
                status=record.status,
            )
        )
    relations = tuple(
        RegistryRelation(
            subject=f"urn:ref:federal-hierarchy-org:{record.fhorgid}",
            predicate=ATLAS_PARENT_ENTITY,
            object=f"urn:ref:federal-hierarchy-org:{record.parent_fhorgid}",
            source_payload={
                "sourceProperty": "fhdeptindagencyorgid",
                "childFhorgid": record.fhorgid,
                "parentFhorgid": record.parent_fhorgid,
                "parentName": record.parent_name,
            },
        )
        for record in roster.records
        if record.org_type == "Sub-Tier"
    )
    return (
        _release(
            key="federal-hierarchy-orgs-complete-2026-08-15",
            resource_id="federal-hierarchy",
            source_module="refspec.registry.federal_hierarchy_complete",
            profile="codeScheme",
            ring="entity",
            scope="completeCapture",
            issued="2026-08-15",
            inputs=(*page_pins, dept_witness_pin, sub_tier_witness_pin),
            resources=resources,
            relations=relations,
            metadata={
                "totalRecordsReported": roster.total_records_reported,
                "departmentOrIndependentAgencyCount": roster.department_count,
                "subTierCount": roster.sub_tier_count,
                "publisherTypeTotalsWitness": {
                    "Department/Ind. Agency": roster.dept_witness_total,
                    "Sub-Tier": roster.sub_tier_witness_total,
                },
                "parentRelationCount": len(relations),
                "identifierAuthorityNote": (
                    "agencycode and oldfpdsofficecode originate in FPDS and cgac in "
                    "Treasury's CGAC classification; the Federal Hierarchy API "
                    "publishes all three alongside its own fhorgid."
                ),
                "publisherAnomalies": roster.anomalies,
                "ref032TotalsNote": (
                    "The API's own totals partition 907 total records into 169 "
                    "Department/Ind. Agency and 738 Sub-Tier; the REF-032 ledger's "
                    "1,645 double-counted the sub-tiers beside the total."
                ),
            },
        ),
    )


def _gao_releases(root: Path) -> tuple[RegistryRelease, ...]:
    page_pin = _pin(
        root,
        f"{_GAO_FIXTURES}/gao-topics-2026-08-15.html",
        sha256=gao.GAO_TOPICS_2026_08_15.expected_sha256,
        byte_length=gao.GAO_TOPICS_2026_08_15.expected_byte_length,
        source_iri=gao.GAO_TOPICS_URL,
        role="publisherIndexPage",
    )
    index = gao.parse_gao_published_topics(page_pin.path.read_bytes())
    # Identity here is publisher-claimed twice over: the /topics/<slug> path
    # is the publisher's operative URL identity and the numeric Drupal
    # taxonomy term id is the publisher's own vocabulary identity, both
    # rendered in the publisher's markup. The REF-032-deleted gao-topics unit
    # failed for minted identity over one observed label, not because slugs
    # are insufficient; the slug is the IRI basis and both publisher ids ride
    # as notations, never as identifier rows (gao-topics is not a declared
    # identifier authority).
    resources = tuple(
        RegistryResource(
            iri=f"urn:ref:gao-topic:{quote(topic.slug, safe='')}",
            labels=(_label(topic.name, f"{page_pin.logical_path}#taxonomy-term-{topic.term_id}"),),
            native_payload=_frozen(topic),
            source_locator=page_pin.source_iri,
            source_digest=page_pin.sha256,
            definition=topic.description,
            notations=(topic.slug, topic.term_id),
        )
        for topic in index.topics
    )
    return (
        _release(
            key="gao-published-topics-index-2026-08-15",
            resource_id="gao-topics",
            source_module="refspec.registry.gao_published_topics",
            profile="conceptScheme",
            ring="subject",
            scope="completeCapture",
            issued="2026-08-15",
            inputs=(page_pin,),
            resources=resources,
            metadata={
                "topicCount": len(resources),
                "listingTitle": index.listing_title,
                "publisherIdentityNote": (
                    "Each topic carries two publisher-minted identifiers rendered in "
                    "the publisher's own markup: its /topics/<slug> path and its "
                    "numeric Drupal taxonomy term id (div id taxonomy-term-<id>, "
                    "class vocabulary-topic). The REF-032-removed gao-topics unit "
                    "was one label observed on one report page under RefSpec-minted "
                    "UUIDv7 identity; this release is the publisher's complete "
                    "published index under the publisher's own identity."
                ),
                "excludedFeaturedEntryHrefs": list(index.featured_entry_hrefs),
                "excludedFeaturedEntryCount": len(index.featured_entry_hrefs),
                "excludedFeaturedEntryNote": (
                    "The page's featured block renders four content nodes "
                    "(node--type-featured-topic), not taxonomy terms; they are "
                    "recorded here and never emitted as topics."
                ),
                "transportNote": (
                    "gao.gov returns HTTP 403 to plain clients behind an Akamai "
                    "challenge; REF-033 recorded GAO's published /topics index as "
                    "sitting behind that challenge with no pinned capture cleared. "
                    "This capture was fetched through the shared Zyte transport "
                    "(refspec.registry.infrastructure.zyte_transport), which "
                    "returned the publisher's 200 response on 2026-08-15T13:56:14Z."
                ),
                "identityStabilityNote": (
                    "The Internet Archive's 2022-12-31 snapshot of this page "
                    "(https://web.archive.org/web/20221231190002/https://www.gao.gov/topics) "
                    "carries the identical 30 slugs and the identical 30 taxonomy "
                    "term ids as this capture; both publisher identifier sets are "
                    "stable 2022 -> 2026. Verified against the snapshot at capture "
                    "review time; the snapshot is not a pinned input."
                ),
                "publisherMarkupAnomalies": {
                    "misspelledDescriptionClass": "taxonomy-term-descripiton"
                },
            },
        ),
    )


REGISTRY_ROSTER_RELEASE_GROUPS = (
    (
        "federal-register",
        frozenset(
            {
                "federal-register-documented-document-types-2026-08-15",
                "federal-register-documented-presidential-document-types-2026-08-15",
                "federal-register-agencies-roster-2026-08-15",
            }
        ),
    ),
    ("fcc", frozenset({"fcc-bureaus-offices-roster-2026-08-15"})),
    (
        "federal-hierarchy",
        frozenset({"federal-hierarchy-orgs-complete-2026-08-15"}),
    ),
    ("gao", frozenset({"gao-published-topics-index-2026-08-15"})),
)
REGISTRY_ROSTER_RELEASE_KEYS = frozenset(
    key
    for _group_name, group_keys in REGISTRY_ROSTER_RELEASE_GROUPS
    for key in group_keys
)


def load_registry_roster_releases(
    repo_root: Path,
    *,
    only_keys: Collection[str] | None = None,
) -> tuple[RegistryRelease, ...]:
    """Load selected documented-roster releases from pinned publisher bytes."""

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=REGISTRY_ROSTER_RELEASE_KEYS,
        loader_name="load_registry_roster_releases",
    )
    root = Path(repo_root)
    loaders = {
        "federal-register": _federal_register_releases,
        "fcc": _fcc_releases,
        "federal-hierarchy": _federal_hierarchy_releases,
        "gao": _gao_releases,
    }
    releases: list[RegistryRelease] = []
    for group_name, group_keys in REGISTRY_ROSTER_RELEASE_GROUPS:
        if not wants_group(requested, group_keys):
            continue
        releases.extend(
            select_declared_group(
                loaders[group_name](root),
                declared_keys=group_keys,
                requested_keys=requested,
                loader_name=loaders[group_name].__name__,
            )
        )
    keys = [release.key for release in releases]
    if len(keys) != len(set(keys)):
        raise ValueError("registry roster adapters produced duplicate release keys")
    return tuple(releases)


__all__ = [
    "ATLAS_PARENT_ENTITY",
    "REGISTRY_ROSTER_RELEASE_GROUPS",
    "REGISTRY_ROSTER_RELEASE_KEYS",
    "load_registry_roster_releases",
]
