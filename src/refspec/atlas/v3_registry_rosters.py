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
  relations and every Federal Hierarchy organization/Treasury FAST Book
  account pair sharing a publisher-reported CGAC Agency Identifier carried as
  the weakest admitted same-ring entity relation;
* the complete eCFR administrative agency roster — 316 publisher-authored
  agency records, 487 CFR structure references preserved in 446 unique
  agency-to-title assertions, and publisher nesting carried as parent entity
  relations. This is the first current entity -> legalIdentity cross-ring
  carrier after REF-032; it uses only eCFR's own references and performs no
  agency-name reconciliation;
* the complete regulations.gov agency roster — 331 publisher-authored agency
  records whose acronyms are docket-ID prefixes, with 160 publisher ``parent``
  relations. The rolling endpoint requires a project-owned API key and is not
  documented in the public OpenAPI file, so the release carries both caveats
  and an explicit recapture-and-diff obligation;
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
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from refspec.atlas import v3_registry_codes as registry_codes
from refspec.atlas.v3_registry_selection import (
    normalize_only_keys,
    select_declared_group,
    wants_group,
)
from refspec.atlas.v3_source_data import (
    RegistryCrossRingRelation,
    RegistryInputPin,
    RegistryLabel,
    RegistryRelation,
    RegistryRelease,
    RegistryResource,
    canonical_digest,
)
from refspec.immutable import deep_freeze_json
from refspec.registry import cfr_list_of_subjects as cfr
from refspec.registry import fcc_bureaus_offices as fcc
from refspec.registry import federal_hierarchy_complete as fh
from refspec.registry import federal_register_native_controls as fr
from refspec.registry import gao_published_topics as gao
from refspec.registry import govinfo_collections as govinfo
from refspec.registry import regulations_gov_agencies as regulations_gov
from refspec.registry import treasury_tas_fast_book as treasury

ATLAS_PARENT_ENTITY = "https://refspec.org/ns/atlas/v3#parentEntity"
ATLAS_RELATED_ENTITY = "https://refspec.org/ns/atlas/v3#relatedEntity"
ATLAS_REFERENCES_LEGAL_IDENTITY = "https://refspec.org/ns/atlas/v3#referencesLegalIdentity"

FH_TREASURY_EXPECTED_SHARED_CGAC_CODES = 130
FH_TREASURY_EXPECTED_ACCOUNT_ROWS = 3_544
FH_TREASURY_EXPECTED_DISTINCT_TAS = 3_543
FH_TREASURY_EXPECTED_RELATED_ENTITY_RELATIONS = 85_462

_FR_FIXTURES = "tests/fixtures/federal_register_native_controls"
_FCC_FIXTURES = "tests/fixtures/fcc_bureaus_offices"
_FH_FIXTURES = "tests/fixtures/federal_hierarchy_complete"
_GAO_FIXTURES = "tests/fixtures/gao_published_topics"
_CFR_FIXTURES = "tests/fixtures/cfr_list_of_subjects"
_REGULATIONS_GOV_AGENCIES_FIXTURES = "tests/fixtures/regulations_gov_agencies"
_TREASURY_FIXTURES = "tests/fixtures/treasury_tas_fast_book"
_GOVINFO_FIXTURES = "tests/fixtures/govinfo_collections"


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
    cross_ring_relations: Sequence[RegistryCrossRingRelation] = (),
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
            "crossRingRelations": [
                {
                    "subject": relation.subject,
                    "predicate": relation.predicate,
                    "object": relation.object,
                    "sourceRing": relation.source_ring,
                    "targetRing": relation.target_ring,
                }
                for relation in cross_ring_relations
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
        cross_ring_relations=tuple(cross_ring_relations),
        dropped_label_count=dropped_label_count,
        metadata=_frozen(metadata or {}),
    )


def _label(value: str, source_path: str, role: str = "preferred") -> RegistryLabel:
    return RegistryLabel(
        value=value.strip(),
        role=role,  # type: ignore[arg-type]
        source_path=source_path,
    )


def _source_capture_metadata(
    pin: RegistryInputPin,
    *,
    retrieved_at: str,
    source_version_note: str,
) -> dict[str, Any]:
    """Keep the capture facts the 3.1 RegistryInputPin cannot yet carry."""

    return {
        "sourceUrl": pin.source_iri,
        "retrievedAt": retrieved_at,
        "sha256": pin.sha256,
        "byteLength": pin.byte_length,
        "sourceVersionNote": source_version_note,
    }


def _ecfr_title_resource_iri(
    title: govinfo.ECFRCFRTitle,
    *,
    ordinal: int,
) -> str:
    """Derive the exact identity used by the held ``ecfr-cfr-titles`` release."""

    pin = govinfo.ECFR_CFR_TITLES_2026_08_03
    return registry_codes._mint_resource_iri(
        source_token="ecfr-cfr-titles",
        issued=pin.retrieved_at,
        source_locator=pin.source.source_url,
        source_path=f"$.titles[{ordinal}]",
        notations=(str(title.title_number),),
        identity_hint=title.name,
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
    fast_book_pin_spec = treasury.FAST_BOOK_PART_II_III_2026_07_31
    fast_book_pin = _pin(
        root,
        f"{_TREASURY_FIXTURES}/{fast_book_pin_spec.filename}",
        sha256=fast_book_pin_spec.expected_sha256,
        byte_length=fast_book_pin_spec.expected_byte_length,
        source_iri=fast_book_pin_spec.source_url,
        role="publisherCgacJoinSource",
    )
    roster = fh.parse_complete_roster(
        [pin.path.read_bytes() for pin in page_pins],
        dept_witness_pin.path.read_bytes(),
        sub_tier_witness_pin.path.read_bytes(),
    )
    fast_book = treasury.parse_fast_book_workbook(
        fast_book_pin.path,
        pin=fast_book_pin_spec,
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
    parent_relations = tuple(
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

    accounts_by_cgac: dict[str, dict[str, list[treasury.FASTBookPublishedAccount]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for account in fast_book.accounts:
        accounts_by_cgac[account.agency_identifier][account.treasury_account_symbol].append(account)
    hierarchy_cgac_codes = {cgac_code for record in roster.records for cgac_code in record.cgac_codes}
    shared_cgac_codes = hierarchy_cgac_codes & set(accounts_by_cgac)
    shared_account_rows = sum(
        len(rows) for cgac_code in shared_cgac_codes for rows in accounts_by_cgac[cgac_code].values()
    )
    shared_distinct_tas = sum(len(accounts_by_cgac[cgac_code]) for cgac_code in shared_cgac_codes)
    observed_join_counts = (
        len(shared_cgac_codes),
        shared_account_rows,
        shared_distinct_tas,
    )
    expected_join_counts = (
        FH_TREASURY_EXPECTED_SHARED_CGAC_CODES,
        FH_TREASURY_EXPECTED_ACCOUNT_ROWS,
        FH_TREASURY_EXPECTED_DISTINCT_TAS,
    )
    if observed_join_counts != expected_join_counts:
        raise ValueError(
            "Federal Hierarchy/Treasury CGAC join counts drifted: "
            f"expected {expected_join_counts}, got {observed_join_counts}"
        )

    cgac_relations = tuple(
        RegistryRelation(
            subject=f"urn:ref:federal-hierarchy-org:{record.fhorgid}",
            predicate=ATLAS_RELATED_ENTITY,
            object=f"urn:ref:treasury-account:{quote(tas, safe='')}",
            source_payload=_frozen(
                {
                    "sourceProperty": "cgaclist[].cgac",
                    "targetProperty": "TAS Agency Identifier",
                    "cgacAgencyIdentifier": cgac_code,
                    "treasuryAccountSymbol": tas,
                    "matchingPublisherRowCount": len(rows),
                    "identityEquivalenceClaimed": False,
                    "administrationClaimed": False,
                    "relationMeaning": (
                        "the Federal Hierarchy organization and Treasury account "
                        "share the publishers' CGAC Agency Identifier"
                    ),
                }
            ),
        )
        for record in roster.records
        for cgac_code in record.cgac_codes
        if cgac_code in shared_cgac_codes
        for tas, rows in sorted(accounts_by_cgac[cgac_code].items())
    )
    if len(cgac_relations) != FH_TREASURY_EXPECTED_RELATED_ENTITY_RELATIONS:
        raise ValueError(
            "Federal Hierarchy/Treasury related-entity count drifted: "
            f"expected {FH_TREASURY_EXPECTED_RELATED_ENTITY_RELATIONS}, "
            f"got {len(cgac_relations)}"
        )
    relations = (*parent_relations, *cgac_relations)
    source_captures = [
        _source_capture_metadata(
            pin,
            retrieved_at=pin_spec.retrieved_at,
            source_version_note=fh.FH_COMPLETE_SOURCE_VERSION_NOTE,
        )
        for pin, pin_spec in zip(
            page_pins,
            fh.FH_COMPLETE_PAGES_2026_08_15,
            strict=True,
        )
    ]
    source_captures.extend(
        (
            _source_capture_metadata(
                dept_witness_pin,
                retrieved_at=fh.FH_TOTAL_DEPT_WITNESS_2026_08_15.retrieved_at,
                source_version_note=fh.FH_COMPLETE_SOURCE_VERSION_NOTE,
            ),
            _source_capture_metadata(
                sub_tier_witness_pin,
                retrieved_at=fh.FH_TOTAL_SUBTIER_WITNESS_2026_08_15.retrieved_at,
                source_version_note=fh.FH_COMPLETE_SOURCE_VERSION_NOTE,
            ),
            _source_capture_metadata(
                fast_book_pin,
                retrieved_at=fast_book_pin_spec.retrieved_at,
                source_version_note=treasury.FAST_BOOK_SOURCE_VERSION_NOTE,
            ),
        )
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
            inputs=(*page_pins, dept_witness_pin, sub_tier_witness_pin, fast_book_pin),
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
                "parentRelationCount": len(parent_relations),
                "cgacRelatedEntityRelationCount": len(cgac_relations),
                "cgacJoin": {
                    "sharedCgacAgencyIdentifierCount": len(shared_cgac_codes),
                    "treasuryAccountRowCount": shared_account_rows,
                    "distinctTreasuryAccountSymbolCount": shared_distinct_tas,
                    "federalHierarchyOrganizationCount": len(
                        {record.fhorgid for record in roster.records if set(record.cgac_codes) & shared_cgac_codes}
                    ),
                    "predicate": ATLAS_RELATED_ENTITY,
                    "identityEquivalenceClaimed": False,
                    "administrationClaimed": False,
                    "relationMeaning": (
                        "Each assertion states only that its endpoints share a "
                        "publisher-reported CGAC Agency Identifier."
                    ),
                },
                "licenseRightsStatements": {
                    "federalHierarchy": fh.FH_COMPLETE_LICENSE_RIGHTS_STATEMENT,
                    "treasuryFastBook": treasury.FAST_BOOK_LICENSE_RIGHTS_STATEMENT,
                },
                "sourceCaptures": source_captures,
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


def _ecfr_agency_releases(root: Path) -> tuple[RegistryRelease, ...]:
    agencies_pin_spec = cfr.ECFR_AGENCIES_2026_08_15
    agencies_pin = _pin(
        root,
        f"{_CFR_FIXTURES}/ecfr-agencies-2026-08-15.json",
        sha256=agencies_pin_spec.expected_sha256,
        byte_length=agencies_pin_spec.expected_byte_length,
        source_iri=agencies_pin_spec.source_url,
        role="publisherAgencyRoster",
    )
    title_pin_spec = govinfo.ECFR_CFR_TITLES_2026_08_03
    title_pin = _pin(
        root,
        f"{_GOVINFO_FIXTURES}/ecfr-cfr-titles-2026-08-03.json",
        sha256=title_pin_spec.expected_sha256,
        byte_length=title_pin_spec.expected_byte_length,
        source_iri=title_pin_spec.source.source_url,
        role="targetRosterWitness",
    )
    roster = cfr.parse_ecfr_agency_roster(
        agencies_pin.path.read_bytes(),
        pin=agencies_pin_spec,
    )
    titles = govinfo.parse_ecfr_cfr_titles(
        govinfo.AcquiredGovInfoSource(
            pin=title_pin_spec,
            path=title_pin.path,
            sha256=title_pin.sha256,
            byte_length=title_pin.byte_length,
            source_url=title_pin.source_iri,
            resolved_url=None,
            content_type="application/json",
            acquisition_mode="local",
            cache_hit=False,
            local_source_path=title_pin.path,
        )
    )
    title_iris = {
        title.title_number: _ecfr_title_resource_iri(title, ordinal=ordinal)
        for ordinal, title in enumerate(titles.titles)
    }

    resources: list[RegistryResource] = []
    parent_relations: list[RegistryRelation] = []
    cross_ring_relations: list[RegistryCrossRingRelation] = []
    for record in roster.records:
        labels = [_label(record.display_name, record.source_path)]
        for candidate in (record.name, record.short_name):
            if candidate and candidate not in {label.value for label in labels}:
                labels.append(_label(candidate, record.source_path, role="alternate"))
        native_payload = {key: value for key, value in record.raw.items() if key != "children"}
        native_payload.update(
            {
                "childAgencySlugs": list(record.child_slugs),
                "parentAgencySlug": record.parent_slug,
            }
        )
        resources.append(
            RegistryResource(
                iri=f"urn:ref:ecfr-agency:{quote(record.slug, safe='')}",
                labels=tuple(labels),
                native_payload=_frozen(native_payload),
                source_locator=agencies_pin.source_iri,
                source_digest=agencies_pin.sha256,
                notations=(record.slug,),
            )
        )
        if record.parent_slug is not None:
            parent_relations.append(
                RegistryRelation(
                    subject=f"urn:ref:ecfr-agency:{quote(record.slug, safe='')}",
                    predicate=ATLAS_PARENT_ENTITY,
                    object=f"urn:ref:ecfr-agency:{quote(record.parent_slug, safe='')}",
                    source_payload=_frozen(
                        {
                            "sourceProperty": "children",
                            "childAgencySlug": record.slug,
                            "parentAgencySlug": record.parent_slug,
                        }
                    ),
                )
            )

        references_by_title: dict[int, list[cfr.EcfrAgencyCfrReference]] = defaultdict(list)
        for reference in record.references:
            references_by_title[reference.title].append(reference)
        for title_number, references in sorted(references_by_title.items()):
            cross_ring_relations.append(
                RegistryCrossRingRelation(
                    subject=f"urn:ref:ecfr-agency:{quote(record.slug, safe='')}",
                    predicate=ATLAS_REFERENCES_LEGAL_IDENTITY,
                    object=title_iris[title_number],
                    source_ring="entity",
                    target_ring="legalIdentity",
                    source_payload=_frozen(
                        {
                            "sourceProperty": "cfr_references",
                            "agencySlug": record.slug,
                            "cfrTitle": title_number,
                            "publisherReferences": [
                                {
                                    "sourceOrdinal": reference.source_ordinal,
                                    **dict(reference.raw),
                                }
                                for reference in references
                            ],
                            "relationMeaning": (
                                "the eCFR agency record references this CFR title; "
                                "chapter, subtitle, subchapter, and part qualifiers "
                                "remain in publisherReferences"
                            ),
                        }
                    ),
                )
            )

    if len(parent_relations) != 163:
        raise ValueError(f"eCFR agency parent relation count drifted: expected 163, got {len(parent_relations)}")
    if len(cross_ring_relations) != 446:
        raise ValueError(f"eCFR agency/title assertion count drifted: expected 446, got {len(cross_ring_relations)}")
    return (
        _release(
            key="ecfr-agencies-roster-2026-08-15",
            resource_id="ecfr-agencies",
            source_module="refspec.registry.cfr_list_of_subjects",
            profile="codeScheme",
            ring="entity",
            scope="completeCapture",
            issued=agencies_pin_spec.retrieved_at[:10],
            inputs=(agencies_pin, title_pin),
            resources=resources,
            relations=parent_relations,
            cross_ring_relations=cross_ring_relations,
            metadata={
                "topLevelAgencyCount": roster.top_level_agency_count,
                "agencyCount": len(roster.records),
                "parentRelationCount": len(parent_relations),
                "publisherCfrReferenceCount": roster.reference_count,
                "referencedAgencyCount": roster.referenced_agency_count,
                "referencedTitleCount": roster.referenced_title_count,
                "crossRingRelationCount": len(cross_ring_relations),
                "crossRingDirection": "entity agency -> legalIdentity CFR title",
                "crossRingPredicate": ATLAS_REFERENCES_LEGAL_IDENTITY,
                "chapterQualifierNote": (
                    "The held legal-identity release names CFR titles. Multiple "
                    "publisher chapter/subtitle/subchapter/part rows for one agency "
                    "and title are retained together in one assertion payload."
                ),
                "nameMatchingRefused": (
                    "No eCFR agency was matched by name to Federal Register, Federal Hierarchy, or OPM rosters."
                ),
                "licenseRightsStatement": agencies_pin_spec.license_rights_statement,
                "sourceCaptures": [
                    _source_capture_metadata(
                        agencies_pin,
                        retrieved_at=agencies_pin_spec.retrieved_at,
                        source_version_note=agencies_pin_spec.source_version_note,
                    ),
                    _source_capture_metadata(
                        title_pin,
                        retrieved_at=title_pin_spec.retrieved_at,
                        source_version_note=(
                            "The publisher exposes the title roster as a rolling, "
                            "unversioned endpoint; the pinned digest detects drift."
                        ),
                    ),
                ],
                "ref032CrossRingTripwireRetirement": (
                    "This publisher-authored agency-to-CFR-title release is a current "
                    "cross-ring carrier. The REF-032 zero-cross-ring tripwire must be "
                    "retired when the integrator admits this release to the full build."
                ),
            },
        ),
    )


def _regulations_gov_agency_releases(root: Path) -> tuple[RegistryRelease, ...]:
    pin_spec = regulations_gov.REGULATIONS_GOV_AGENCIES_2026_08_16
    roster_pin = _pin(
        root,
        (
            f"{_REGULATIONS_GOV_AGENCIES_FIXTURES}/"
            "regulations-gov-agencies-2026-08-16.json"
        ),
        sha256=pin_spec.expected_sha256,
        byte_length=pin_spec.expected_byte_length,
        source_iri=pin_spec.source_url,
        role="publisherAgencyRoster",
    )
    roster = regulations_gov.parse_regulations_gov_agencies(
        roster_pin.path.read_bytes(),
        pin=pin_spec,
    )
    resources = tuple(
        RegistryResource(
            iri=f"urn:ref:regulations-gov-agency:{quote(record.agency_id, safe='')}",
            labels=(
                _label(
                    record.name,
                    (
                        f"{roster_pin.logical_path}#data[{record.source_ordinal}]"
                        ".attributes.name"
                    ),
                ),
            ),
            native_payload=_frozen(
                {
                    "id": record.agency_id,
                    "type": "agencies",
                    "parent": record.parent,
                    "participate": record.participate,
                    "partner": record.partner,
                    "postingGuidelines": record.posting_guidelines,
                    "name": record.name,
                    "agencyType": record.agency_type,
                    "links": record.raw["links"],
                }
            ),
            source_locator=record.self_link,
            source_digest=roster_pin.sha256,
            notations=(record.agency_id,),
        )
        for record in roster.records
    )
    parent_relations = tuple(
        RegistryRelation(
            subject=f"urn:ref:regulations-gov-agency:{quote(record.agency_id, safe='')}",
            predicate=ATLAS_PARENT_ENTITY,
            object=f"urn:ref:regulations-gov-agency:{quote(record.parent, safe='')}",
            source_payload=_frozen(
                {
                    "sourceProperty": "attributes.parent",
                    "childAgencyId": record.agency_id,
                    "parentAgencyId": record.parent,
                }
            ),
        )
        for record in roster.records
        if record.parent is not None
    )
    if len(parent_relations) != regulations_gov.REGULATIONS_GOV_EXPECTED_PARENT_RELATION_COUNT:
        raise ValueError(
            "regulations.gov parent-relation count drifted during adaptation: "
            f"expected {regulations_gov.REGULATIONS_GOV_EXPECTED_PARENT_RELATION_COUNT}, "
            f"got {len(parent_relations)}"
        )
    return (
        _release(
            key="regulations-gov-agencies-roster-2026-08-16",
            resource_id="regulations-gov-native-controls",
            source_module="refspec.registry.regulations_gov_agencies",
            profile="codeScheme",
            ring="entity",
            scope="completeCapture",
            issued=pin_spec.retrieved_at[:10],
            inputs=(roster_pin,),
            resources=resources,
            relations=parent_relations,
            scheme_suffix="agencies",
            metadata={
                "agencyCount": len(resources),
                "parentRelationCount": len(parent_relations),
                "distinctParentAgencyCount": roster.distinct_parent_count,
                "docketIdPrefixCount": len(resources),
                "docketIdPrefixNote": (
                    "The publisher's agency id is the docket-ID prefix used by "
                    "regulations.gov dockets and documents."
                ),
                "undocumentedEndpoint": True,
                "endpointDocumentationNote": (
                    "The v4 agencies endpoint is publisher-operated but absent "
                    "from the public regulations.gov OpenAPI description."
                ),
                "recaptureObligation": regulations_gov.REGULATIONS_GOV_RECAPTURE_OBLIGATION,
                "apiKeyRequirement": {
                    "environmentVariable": regulations_gov.REGULATIONS_GOV_API_KEY_ENV_VAR,
                    "requestHeader": regulations_gov.REGULATIONS_GOV_API_KEY_HEADER,
                    "keyValueIncluded": False,
                },
                "identifierAuthorityNote": (
                    "The publisher's id travels as the resource notation, not an "
                    "authority-scoped identifier row; regulations-gov-native-controls "
                    "is not an Atlas identifier authority."
                ),
                "licenseRightsStatement": (
                    regulations_gov.REGULATIONS_GOV_LICENSE_RIGHTS_STATEMENT
                ),
                "sourceCaptures": [
                    _source_capture_metadata(
                        roster_pin,
                        retrieved_at=pin_spec.retrieved_at,
                        source_version_note=regulations_gov.REGULATIONS_GOV_SOURCE_VERSION_NOTE,
                    )
                ],
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
    ("ecfr-agencies", frozenset({"ecfr-agencies-roster-2026-08-15"})),
    (
        "regulations-gov-agencies",
        frozenset({"regulations-gov-agencies-roster-2026-08-16"}),
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
        "ecfr-agencies": _ecfr_agency_releases,
        "regulations-gov-agencies": _regulations_gov_agency_releases,
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
    "ATLAS_REFERENCES_LEGAL_IDENTITY",
    "ATLAS_RELATED_ENTITY",
    "FH_TREASURY_EXPECTED_ACCOUNT_ROWS",
    "FH_TREASURY_EXPECTED_DISTINCT_TAS",
    "FH_TREASURY_EXPECTED_RELATED_ENTITY_RELATIONS",
    "FH_TREASURY_EXPECTED_SHARED_CGAC_CODES",
    "REGISTRY_ROSTER_RELEASE_GROUPS",
    "REGISTRY_ROSTER_RELEASE_KEYS",
    "load_registry_roster_releases",
]
