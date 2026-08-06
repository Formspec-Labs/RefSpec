"""Finish Atlas 3 adapters for bounded descriptor-only registry sources.

Every adapter consumes exact publisher bytes through its registry parser and
states its capture scope. Partial samples remain partial samples; structural
definitions remain structural definitions; identifiers attach to the entity or
legal resource they identify. No adapter promotes examples into authority
membership or creates an identifier ring.
"""

from __future__ import annotations

import dataclasses
import hashlib
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from refspec.atlas.v3_source_data import (
    RegistryIdentifier,
    RegistryInputPin,
    RegistryLabel,
    RegistryRelation,
    RegistryRelease,
    RegistryResource,
    canonical_digest,
)
from refspec.immutable import deep_freeze_json
from refspec.registry import agrovoc_thesaurus as agrovoc
from refspec.registry import epa_enterprise_vocabulary as epa_vocabulary
from refspec.registry import epa_srs_substances as epa
from refspec.registry import eurovoc_thesaurus as eurovoc
from refspec.registry import fac_dictionary as fac
from refspec.registry import federal_hierarchy_orgs as fh
from refspec.registry import gao_cra_facets as gao_cra
from refspec.registry import govinfo_collections as govinfo
from refspec.registry import lcsh_topical as lcsh
from refspec.registry import nalt_core
from refspec.registry import nppes_npi_identifiers as nppes
from refspec.registry import nrc_adams_codes as nrc
from refspec.registry import treasury_tas_fast_book as treasury
from refspec.registry import uei_cage_identifiers as sam
from refspec.registry import usaspending_gsdm_codes as gsdm

ATLAS = "https://refspec.org/ns/atlas/v3#"
SKOS = "http://www.w3.org/2004/02/skos/core#"


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


def _agrovoc_releases(root: Path) -> tuple[RegistryRelease, ...]:
    sample = agrovoc.AGROVOC_C330_SAMPLE
    pin = _pin(
        root,
        f"tests/fixtures/agrovoc_thesaurus/{sample.filename}",
        sha256=sample.expected_sha256,
        byte_length=sample.expected_byte_length,
        source_iri=sample.source_url,
        role="boundedPublisherConcept",
    )
    parsed = agrovoc.parse_agrovoc_file(
        pin.path,
        source_url=sample.source_url,
        expected_sha256=sample.expected_sha256,
        expected_byte_length=sample.expected_byte_length,
    )
    concept = next(item for item in parsed.concepts if item.concept_iri == sample.concept_iri)
    source_labels = [item for item in parsed.labels if item.subject_iri == concept.concept_iri]
    english_labels = [item for item in source_labels if item.value.language_tag in {None, "en"}]
    labels = tuple(_label(item.value.lexical_form, pin.logical_path, item.role) for item in english_labels)
    resource = RegistryResource(
        iri=concept.concept_iri,
        labels=labels,
        native_payload=_frozen(
            {
                "concept": concept,
                "notes": [item for item in parsed.notes if item.subject_iri == concept.concept_iri],
                "notations": [item for item in parsed.notations if item.subject_iri == concept.concept_iri],
                "semanticRelations": [
                    item for item in parsed.semantic_relations if item.subject_iri == concept.concept_iri
                ],
                "mappingRelations": [
                    item for item in parsed.mapping_relations if item.subject_iri == concept.concept_iri
                ],
                "captureRole": "mappingReference",
            }
        ),
        source_locator=pin.source_iri,
        source_digest=pin.sha256,
        notations=tuple(
            item.value.lexical_form for item in parsed.notations if item.subject_iri == concept.concept_iri
        ),
        status="boundedMappingReference",
    )
    return (
        _release(
            key="agrovoc-c330-bounded-2026-08-03",
            resource_id="agrovoc",
            source_module="refspec.registry.agrovoc_thesaurus",
            profile="conceptScheme",
            ring="subject",
            scope="captureSubset",
            issued="2026-08-03",
            inputs=(pin,),
            resources=(resource,),
            dropped_label_count=len(source_labels) - len(english_labels),
            metadata={
                "completePublisherRelease": False,
                "mappingReferenceOnly": True,
                "publisherConceptCount": 1,
            },
        ),
    )


def _eurovoc_releases(root: Path) -> tuple[RegistryRelease, ...]:
    sample = eurovoc.EUROVOC_SAMPLE_2026_08_03
    pin = _pin(
        root,
        f"tests/fixtures/eurovoc_thesaurus/{sample.filename}",
        sha256=sample.expected_sha256,
        byte_length=sample.expected_byte_length,
        source_iri=sample.source_url,
        role="boundedPublisherConcepts",
    )
    parsed = eurovoc.parse_eurovoc_file(
        pin.path,
        source_url=sample.source_url,
        accepted_use="mappingReference",
        expected_sha256=sample.expected_sha256,
        expected_byte_length=sample.expected_byte_length,
    )
    concept_iris = {concept.concept_iri for concept in parsed.concepts}
    resources: list[RegistryResource] = []
    dropped_labels = 0
    for concept in parsed.concepts:
        source_labels = [item for item in parsed.labels if item.subject_iri == concept.concept_iri]
        english_labels = [item for item in source_labels if item.value.language_tag in {None, "en"}]
        dropped_labels += len(source_labels) - len(english_labels)
        resources.append(
            RegistryResource(
                iri=concept.concept_iri,
                labels=tuple(_label(item.value.lexical_form, pin.logical_path, item.role) for item in english_labels),
                native_payload=_frozen(
                    {
                        "concept": concept,
                        "schemeMemberships": [
                            item for item in parsed.scheme_memberships if item.subject_iri == concept.concept_iri
                        ],
                        "statusAssertions": [
                            item for item in parsed.status_assertions if item.subject_iri == concept.concept_iri
                        ],
                        "captureRole": parsed.role,
                        "thesaurusVersion": parsed.thesaurus_version,
                    }
                ),
                source_locator=pin.source_iri,
                source_digest=pin.sha256,
                notations=(concept.notation,),
                status="boundedMappingReference",
            )
        )
    relations = tuple(
        RegistryRelation(
            subject=item.subject_iri,
            predicate=item.predicate_iri,
            object=item.object_iri,
            source_payload=_frozen({"publisherRelation": item}),
        )
        for item in parsed.hierarchy_relations
        if item.subject_iri in concept_iris and item.object_iri in concept_iris
    )
    return (
        _release(
            key="eurovoc-bounded-concepts-2026-08-03",
            resource_id="eurovoc",
            source_module="refspec.registry.eurovoc_thesaurus",
            profile="conceptScheme",
            ring="subject",
            scope="captureSubset",
            issued="2026-08-03",
            inputs=(pin,),
            resources=resources,
            relations=relations,
            dropped_label_count=dropped_labels,
            metadata={
                "completePublisherRelease": False,
                "mappingReferenceOnly": True,
                "publisherConceptCount": len(resources),
                "thesaurusVersion": parsed.thesaurus_version,
            },
        ),
    )


def _epa_vocabulary_releases(root: Path) -> tuple[RegistryRelease, ...]:
    """Emit every captured row as structure, without inventing concept IDs."""

    sample = epa_vocabulary.EPA_REGULATORY_ACTIVITIES_TIER_WITH_DEFINITIONS_CAPTURE
    pin = _pin(
        root,
        f"tests/fixtures/epa_enterprise_vocabulary/{sample.filename}",
        sha256=sample.expected_sha256,
        byte_length=sample.expected_byte_length,
        source_iri=sample.source_url,
        role="boundedPublisherLabelTree",
    )
    parsed = epa_vocabulary.parse_epa_enterprise_vocabulary_file(
        pin.path,
        source_url=sample.source_url,
        expected_sha256=sample.expected_sha256,
        expected_byte_length=sample.expected_byte_length,
    )
    walked = [item for root_row in parsed.rows for item in root_row.walk()]
    by_path = {row.source_path: row for _depth, row in walked}
    resources = tuple(
        RegistryResource(
            iri="urn:ref:epa-enterprise-vocabulary-row:" + quote(row.source_path, safe=""),
            labels=(_label(row.label, f"{pin.logical_path}#{row.source_path}"),),
            native_payload=_frozen(
                {
                    "depth": depth,
                    "row": row,
                    "publisherConceptIdentityAvailable": False,
                }
            ),
            source_locator=f"{sample.tier_browse_url}#{row.source_path}",
            source_digest=pin.sha256,
            definition=(row.definitions_text or "").strip() or None,
            notes=tuple(value for value in ((row.scope_note_text or "").strip(),) if value and value != "\xa0"),
            status="sourcePositionObservation",
        )
        for depth, row in walked
    )
    relations: list[RegistryRelation] = []
    for _depth, parent in walked:
        for child in parent.child_terms:
            if child.source_path not in by_path:
                raise ValueError("EPA vocabulary walk omitted a captured child row")
            relations.append(
                RegistryRelation(
                    subject="urn:ref:epa-enterprise-vocabulary-row:" + quote(child.source_path, safe=""),
                    predicate=ATLAS + "broaderValue",
                    object="urn:ref:epa-enterprise-vocabulary-row:" + quote(parent.source_path, safe=""),
                    source_payload=_frozen(
                        {
                            "publisherNesting": True,
                            "parentSourcePath": parent.source_path,
                            "childSourcePath": child.source_path,
                        }
                    ),
                )
            )
    return (
        _release(
            key="epa-enterprise-vocabulary-label-tree-2026-08-03",
            resource_id="epa-enterprise-vocabulary",
            source_module="refspec.registry.epa_enterprise_vocabulary",
            profile="structureScheme",
            ring="value",
            scope="completeCapture",
            issued="2026-08-03",
            inputs=(pin,),
            resources=resources,
            relations=relations,
            scheme_suffix="captured-label-tree",
            metadata={
                "allCapturedRowsEmitted": True,
                "publisherConceptIdentityAvailable": False,
                "rowCount": len(resources),
                "verificationGaps": epa_vocabulary.EPA_ENTERPRISE_VOCABULARY_VERIFICATION_GAPS,
            },
        ),
    )


def _gao_cra_releases(root: Path) -> tuple[RegistryRelease, ...]:
    pin_spec = gao_cra.GAO_CRA_REAL_CAPTURE_2026_08_04
    source_pin = _pin(
        root,
        "tests/fixtures/gao_cra_facets/gao-cra-database-real-capture-2026-08-04.html",
        sha256=pin_spec.expected_sha256,
        byte_length=pin_spec.expected_byte_length,
        source_iri=pin_spec.source_url,
        role="publisherSearchFacets",
    )
    with tempfile.TemporaryDirectory(prefix="refspec-atlas-gao-cra-") as directory:
        acquired = gao_cra.acquire_gao_cra_facets_page(
            pin_spec,
            Path(directory),
            source_path=source_pin.path,
        )
        parsed = gao_cra.parse_gao_cra_facets(acquired)
    resources: list[RegistryResource] = []
    for facet_name, values in sorted(parsed.facets.items()):
        for value in values:
            identifier = value.identifiers[0]
            resources.append(
                RegistryResource(
                    iri=(
                        "urn:ref:gao-cra-facet:" + quote(facet_name, safe="") + ":" + quote(identifier.value, safe="")
                    ),
                    labels=(_label(value.publisher_label, source_pin.logical_path),),
                    native_payload=_frozen(value),
                    source_locator=source_pin.source_iri,
                    source_digest=source_pin.sha256,
                    notations=(identifier.value,),
                    status="default" if value.is_default else "available",
                )
            )
    return (
        _release(
            key="gao-cra-database-facets-2026-08-04",
            resource_id="gao-cra-database-facets",
            source_module="refspec.registry.gao_cra_facets",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            issued="2026-08-04",
            inputs=(source_pin,),
            resources=resources,
            metadata={
                "allVisibleFacetValuesEmitted": True,
                "facetNames": sorted(parsed.facets),
                "facetValueCount": len(resources),
                "publisherReleaseUnavailable": True,
                "sourceGaps": parsed.gaps,
            },
        ),
    )


def _lcsh_releases(root: Path) -> tuple[RegistryRelease, ...]:
    logical_path = "tests/fixtures/lcsh_topical/lcsh-topical-mini.ndjson"
    pin = _pin(
        root,
        logical_path,
        sha256=lcsh.LCSH_TOPICAL_MINI_FIXTURE_SHA256,
        byte_length=lcsh.LCSH_TOPICAL_MINI_FIXTURE_BYTE_LENGTH,
        source_iri=lcsh.LCSH_TOPICAL_MADS_NDJSON_URL + "#bounded-byte-range",
        role="boundedPublisherRecords",
    )
    payload = lcsh.open_pinned_lcsh_topical_mini_fixture(pin.path)
    captured = lcsh.capture_lcsh_topical_subset(
        payload.splitlines(keepends=True),
        source_url=lcsh.LCSH_TOPICAL_MADS_NDJSON_URL,
        max_records=3,
    )
    record_iris = {record.concept_iri for record in captured.records}
    resources = tuple(
        RegistryResource(
            iri=record.concept_iri,
            labels=(
                _label(record.preferred_label.value, f"{logical_path}#line-{record.line_number}"),
                *(
                    _label(
                        label.value,
                        f"{logical_path}#line-{record.line_number}",
                        "alternate",
                    )
                    for label in record.variant_labels
                ),
            ),
            native_payload=_frozen(
                {
                    "lccn": record.lccn,
                    "broaderIris": record.broader_iris,
                    "lineNumber": record.line_number,
                    "recordDigest": record.source_sha256,
                    "recordByteLength": record.source_byte_length,
                    "captureRole": "mappingReference",
                }
            ),
            source_locator=f"{record.source_url}#line-{record.line_number}",
            source_digest=record.source_sha256,
            notations=(record.lccn,),
            status="boundedMappingReference",
        )
        for record in captured.records
    )
    relations = tuple(
        RegistryRelation(
            subject=record.concept_iri,
            predicate=SKOS + "broader",
            object=broader,
            source_payload=_frozen({"lineNumber": record.line_number, "publisherBroader": broader}),
        )
        for record in captured.records
        for broader in record.broader_iris
        if broader in record_iris
    )
    return (
        _release(
            key="lcsh-topical-bounded-2026-08-03",
            resource_id="lcsh-topical",
            source_module="refspec.registry.lcsh_topical",
            profile="conceptScheme",
            ring="subject",
            scope="captureSubset",
            issued="2026-08-03",
            inputs=(pin,),
            resources=resources,
            relations=relations,
            metadata={
                "completePublisherRelease": False,
                "mappingReferenceOnly": True,
                "linesScanned": captured.lines_scanned,
                "excludedNonTopicalRows": captured.excluded_count,
                "topicalRecordCount": len(resources),
            },
        ),
    )


def _fac_releases(root: Path) -> tuple[RegistryRelease, ...]:
    pin_spec = fac.FAC_DICTIONARY_DOC_2026_08_03
    source_pin = _pin(
        root,
        "tests/fixtures/fac_dictionary/fac-api-dictionary-2026-08-03.html",
        sha256=pin_spec.expected_sha256,
        byte_length=pin_spec.expected_byte_length,
        source_iri=pin_spec.source.source_url,
        role="publisherFieldDictionary",
    )
    with tempfile.TemporaryDirectory(prefix="refspec-atlas-fac-") as directory:
        acquired = fac.acquire_fac_dictionary_doc(
            pin_spec,
            Path(directory),
            source_path=source_pin.path,
        )
        portfolio = fac.parse_fac_dictionary(acquired)
    resources = tuple(
        RegistryResource(
            iri=("urn:ref:fac-api-field:" + quote(field.endpoint, safe="") + ":" + quote(field.gsa_field, safe="")),
            labels=(_label(field.gsa_field, source_pin.logical_path),),
            native_payload=_frozen(field),
            source_locator=source_pin.source_iri,
            source_digest=source_pin.sha256,
            definition=(f"FAC {field.data_type} field on the {field.endpoint} endpoint"),
            notations=(field.gsa_field,),
        )
        for field in portfolio.fields
    )
    return (
        _release(
            key="fac-api-field-dictionary-2026-08-03",
            resource_id="fac-api-dictionary",
            source_module="refspec.registry.fac_dictionary",
            profile="structureScheme",
            ring="value",
            scope="completeCapture",
            issued="2026-08-03",
            inputs=(source_pin,),
            resources=resources,
            metadata={
                "endpointCount": len(portfolio.endpoints),
                "distinctFieldCount": len(resources),
                "publisherLastModified": portfolio.publisher_last_modified,
                "sourceGaps": portfolio.gaps,
            },
        ),
    )


def _epa_substance_releases(root: Path) -> tuple[RegistryRelease, ...]:
    source_iri = "https://comptox.epa.gov/dashboard/chemical/details/DTXSID7020182"
    source_pin = _pin(
        root,
        "output/registry-real-data-sources/comptox-DTXSID7020182.normalized.html",
        sha256="sha256:96166f421b896b79f0f0273b26908a5d0dbbcc6ab484e6b15fa41d71ca082803",
        byte_length=334_109,
        source_iri=source_iri,
        role="boundedPublisherSubstancePage",
    )
    sample = epa.parse_comptox_detail_page(
        source_pin.path.read_bytes(),
        source_uri=source_iri,
        captured_at="2026-08-03T20:00:00Z",
    )
    resources = tuple(
        RegistryResource(
            iri=f"urn:ref:epa-substance:{record.dtxsid}",
            labels=(_label(record.preferred_name, source_pin.logical_path),),
            native_payload=_frozen(record.native_payload()),
            source_locator=source_pin.source_iri,
            source_digest=source_pin.sha256,
            identifiers=tuple(
                RegistryIdentifier(
                    value=value,
                    scheme_iri="urn:ref:atlas-resource-scheme:epa-substance-identifiers",
                    source_path=f"{source_pin.logical_path}#{kind}",
                )
                for kind, value in (
                    ("DTXSID", record.dtxsid),
                    ("DTXCID", record.dtxcid),
                    ("CASRN", record.casrn),
                )
                if value is not None
            ),
            status="boundedPublicSample",
        )
        for record in sample.records
    )
    return (
        _release(
            key="epa-comptox-substance-bounded-2026-08-03",
            resource_id="epa-substance-identifiers",
            source_module="refspec.registry.epa_srs_substances",
            profile="identifierScheme",
            ring="entity",
            scope="captureSubset",
            issued="2026-08-03",
            inputs=(source_pin,),
            resources=resources,
            metadata={
                "completePublisherRelease": False,
                "substanceCount": len(resources),
                "identifierKinds": ["DTXSID", "DTXCID", "CASRN"],
            },
        ),
    )


def _federal_hierarchy_releases(root: Path) -> tuple[RegistryRelease, ...]:
    captures = (
        (
            fh.FH_ORGS_DEFAULT_PAGE_2026_08_03,
            "output/registry-real-data-sources/fh-orgs-default-page.json",
        ),
        (
            fh.FH_ORGS_SUB_TIER_PAGE_2026_08_03,
            "output/registry-real-data-sources/fh-orgs-sub-tier-page.json",
        ),
    )
    pins: list[RegistryInputPin] = []
    parsed_samples: list[fh.ParsedFHOrgsSample] = []
    with tempfile.TemporaryDirectory(prefix="refspec-atlas-fh-") as directory:
        for pin_spec, logical_path in captures:
            source_pin = _pin(
                root,
                logical_path,
                sha256=pin_spec.expected_sha256,
                byte_length=pin_spec.expected_byte_length,
                source_iri=pin_spec.source.source_url,
                role="boundedPublisherOrganizationPage",
            )
            pins.append(source_pin)
            acquired = fh.acquire_fh_orgs_sample(
                pin_spec,
                Path(directory),
                source_path=source_pin.path,
            )
            parsed_samples.append(fh.parse_fh_orgs_sample(acquired))
    records: dict[str, tuple[fh.FHOrgRecord, RegistryInputPin]] = {}
    for parsed, source_pin in zip(parsed_samples, pins, strict=True):
        for record in parsed.records:
            if record.fhorgid in records:
                raise ValueError(f"Federal Hierarchy captures repeat organization {record.fhorgid}")
            records[record.fhorgid] = (record, source_pin)
    resources = tuple(
        RegistryResource(
            iri=f"urn:ref:federal-hierarchy-org:{record.fhorgid}",
            labels=(_label(record.fhorgname, source_pin.logical_path),),
            native_payload=_frozen(record),
            source_locator=source_pin.source_iri,
            source_digest=source_pin.sha256,
            identifiers=(
                RegistryIdentifier(
                    value=record.fhorgid,
                    scheme_iri="urn:ref:atlas-resource-scheme:federal-hierarchy:org-identifiers",
                    source_path=f"{source_pin.logical_path}#fhorgid",
                ),
            ),
            status=record.status,
        )
        for record, source_pin in records.values()
    )
    relations = tuple(
        RegistryRelation(
            subject=f"urn:ref:federal-hierarchy-org:{record.fhorgid}",
            predicate=ATLAS + "parentEntity",
            object=f"urn:ref:federal-hierarchy-org:{record.parent_fhorgid}",
            source_payload=_frozen(
                {
                    "parentFhorgid": record.parent_fhorgid,
                    "parentOrgName": record.parent_org_name,
                }
            ),
        )
        for record, _source_pin in records.values()
        if record.parent_fhorgid in records and record.parent_fhorgid != record.fhorgid
    )
    return (
        _release(
            key="federal-hierarchy-orgs-bounded-2026-08-03",
            resource_id="federal-hierarchy",
            source_module="refspec.registry.federal_hierarchy_orgs",
            profile="identifierScheme",
            ring="entity",
            scope="captureSubset",
            issued="2026-08-03",
            inputs=pins,
            resources=resources,
            relations=relations,
            scheme_suffix="org-identifiers",
            metadata={
                "completePublisherRelease": False,
                "organizationCount": len(resources),
                "publisherTotals": [parsed.total_records_reported for parsed in parsed_samples],
                "otherPublisherIdentifiersRetainedInNativePayload": True,
            },
        ),
    )


def _govinfo_package_releases(root: Path) -> tuple[RegistryRelease, ...]:
    summary_spec = govinfo.GOVINFO_CFR_PACKAGE_SUMMARY_2026_08_03
    fixity_spec = govinfo.GOVINFO_CFR_PACKAGE_PREMIS_2026_08_03
    summary_pin = _pin(
        root,
        "tests/fixtures/govinfo_collections/govinfo-package-summary-cfr-2023-title1-vol1-2026-08-03.json",
        sha256=summary_spec.expected_sha256,
        byte_length=summary_spec.expected_byte_length,
        source_iri=summary_spec.source.source_url,
        role="publisherPackageSummary",
    )
    fixity_pin = _pin(
        root,
        "tests/fixtures/govinfo_collections/govinfo-premis-cfr-2023-title1-vol1-mini-2026-08-03.xml",
        sha256=fixity_spec.expected_sha256,
        byte_length=fixity_spec.expected_byte_length,
        source_iri=fixity_spec.source.source_url,
        role="publisherPackageFixity",
    )
    with tempfile.TemporaryDirectory(prefix="refspec-atlas-govinfo-") as directory:
        store = Path(directory)
        summary = govinfo.parse_govinfo_cfr_package_summary(
            govinfo.acquire_govinfo_source(summary_spec, store, source_path=summary_pin.path)
        )
        fixity = govinfo.parse_govinfo_cfr_package_fixity(
            govinfo.acquire_govinfo_source(fixity_spec, store, source_path=fixity_pin.path),
            expected_package_id=summary.package_id,
        )
    resource = RegistryResource(
        iri=f"urn:ref:govinfo-cfr-package:{summary.package_id}",
        labels=(
            _label(
                f"{summary.document_type}: {summary.package_id}",
                summary_pin.logical_path,
            ),
        ),
        native_payload=_frozen({"summary": summary, "fixity": fixity}),
        source_locator=summary.details_link,
        source_digest=summary_pin.sha256,
        identifiers=(
            RegistryIdentifier(
                value=summary.package_id,
                scheme_iri="urn:ref:atlas-resource-scheme:govinfo-cfr-packages",
                source_path=f"{summary_pin.logical_path}#packageId",
            ),
        ),
        status="boundedPublishedPackage",
    )
    return (
        _release(
            key="govinfo-cfr-package-bounded-2026-08-03",
            resource_id="govinfo-cfr-packages",
            source_module="refspec.registry.govinfo_collections",
            profile="identifierScheme",
            ring="legalIdentity",
            scope="captureSubset",
            issued="2026-08-03",
            inputs=(summary_pin, fixity_pin),
            resources=(resource,),
            metadata={
                "completePublisherRelease": False,
                "packageCount": 1,
                "packageDateIssued": summary.date_issued,
                "premisFixityRecordCount": len(fixity.records),
            },
        ),
    )


def _nalt_releases(root: Path) -> tuple[RegistryRelease, ...]:
    fixture_root = "tests/fixtures/nalt_core"
    specs = (
        nalt_core.NALT_CORE_ANIMAL_WELFARE_CAPTURE,
        nalt_core.NALT_CORE_TOP_CONCEPT_CAPTURE,
    )
    pins: list[RegistryInputPin] = []
    captures: list[nalt_core.NaltCoreCapture] = []
    for spec in specs:
        logical_path = f"{fixture_root}/{spec.filename}"
        pin = _pin(
            root,
            logical_path,
            sha256=spec.expected_sha256,
            byte_length=spec.expected_byte_length,
            source_iri=spec.source_url,
        )
        pins.append(pin)
        captures.append(
            nalt_core.parse_nalt_core_file(
                pin.path,
                source_url=spec.source_url,
                concept_iri=spec.concept_iri,
                expected_sha256=spec.expected_sha256,
                expected_byte_length=spec.expected_byte_length,
            )
        )

    requested = {capture.requested_concept_iri for capture in captures}
    resources: list[RegistryResource] = []
    dropped_labels = 0
    for capture, pin in zip(captures, pins, strict=True):
        vocabulary = capture.vocabulary
        source_path = pin.logical_path
        source_labels = [item for item in vocabulary.labels if item.subject_iri == capture.requested_concept_iri]
        english_labels = [item for item in source_labels if item.value.language_tag in {None, "en"}]
        dropped_labels += len(source_labels) - len(english_labels)
        labels = tuple(_label(item.value.lexical_form, source_path, item.role) for item in english_labels)
        if sum(label.role == "preferred" for label in labels) != 1:
            raise ValueError(f"NALT capture has no single English preferred label: {capture.requested_concept_iri}")
        direct_relations = [
            relation
            for relation in vocabulary.semantic_relations
            if relation.subject_iri == capture.requested_concept_iri
        ]
        resources.append(
            RegistryResource(
                iri=capture.requested_concept_iri,
                labels=labels,
                native_payload=_frozen(
                    {
                        "concept": capture.requested_concept,
                        "directSemanticRelations": direct_relations,
                        "sourcePredicateCounts": vocabulary.predicate_counts,
                        "captureScope": "one requested NALT Core concept",
                    }
                ),
                source_locator=pin.source_iri,
                source_digest=pin.sha256,
            )
        )

    relation_rows: dict[tuple[str, str, str], RegistryRelation] = {}
    for capture in captures:
        for relation in capture.vocabulary.semantic_relations:
            if relation.subject_iri not in requested or relation.object_iri not in requested:
                continue
            key = (relation.subject_iri, relation.predicate_iri, relation.object_iri)
            relation_rows[key] = RegistryRelation(
                subject=relation.subject_iri,
                predicate=relation.predicate_iri,
                object=relation.object_iri,
                source_payload=_frozen(
                    {
                        "publisherRelation": dataclasses.asdict(relation),
                        "captureScope": "relation whose two endpoints are both emitted",
                    }
                ),
            )
    return (
        _release(
            key="nalt-core-bounded-concepts-2026-08-03",
            resource_id="nalt-core",
            source_module="refspec.registry.nalt_core",
            profile="conceptScheme",
            ring="subject",
            scope="captureSubset",
            issued="2026-08-03",
            inputs=pins,
            resources=resources,
            relations=tuple(relation_rows[key] for key in sorted(relation_rows)),
            dropped_label_count=dropped_labels,
            metadata={
                "boundedConceptCount": 2,
                "completePublisherRelease": False,
                "licenseEvidenceResolved": False,
            },
        ),
    )


def _nppes_releases(root: Path) -> tuple[RegistryRelease, ...]:
    header_pin = _pin(
        root,
        "tests/fixtures/nppes_npi_identifiers/npidata_pfile_fileheader_v2.csv",
        sha256=nppes.NPPES_FILEHEADER_SHA256,
        byte_length=nppes.NPPES_FILEHEADER_BYTE_LENGTH,
        source_iri=nppes.NPPES_FILEHEADER_SOURCE_ID,
        role="publisherFileHeader",
    )
    sample_pin = _pin(
        root,
        "tests/fixtures/nppes_npi_identifiers/npidata_pfile_sample_v2.csv",
        sha256=nppes.NPPES_SAMPLE_SHA256,
        byte_length=nppes.NPPES_SAMPLE_BYTE_LENGTH,
        source_iri=nppes.NPPES_WEEKLY_CAPTURE_URL + "#bounded-provider-sample",
        role="publisherProviderSample",
    )
    columns = nppes.parse_fileheader_columns(
        header_pin.path.read_bytes(),
        expected_sha256=header_pin.sha256,
        expected_byte_length=header_pin.byte_length,
    )
    providers = nppes.parse_npi_provider_sample(
        sample_pin.path.read_bytes(),
        columns,
        expected_sha256=sample_pin.sha256,
        expected_byte_length=sample_pin.byte_length,
    )
    layout_resources = tuple(
        RegistryResource(
            iri=f"urn:ref:nppes-layout:v2:field-{ordinal:03d}",
            labels=(_label(column, header_pin.logical_path),),
            native_payload=_frozen(
                {
                    "columnName": column,
                    "ordinal": ordinal,
                    "layoutVersion": "2",
                    "licensedTaxonomyValuesIncluded": False,
                }
            ),
            source_locator=header_pin.source_iri,
            source_digest=header_pin.sha256,
            notations=(str(ordinal),),
        )
        for ordinal, column in enumerate(columns)
    )
    provider_resources = tuple(
        RegistryResource(
            iri=f"urn:ref:nppes-provider:{record.identifier.value}",
            labels=(_label(record.publisher_label, sample_pin.logical_path),),
            native_payload=_frozen(record.native_payload()),
            source_locator=sample_pin.source_iri,
            source_digest=sample_pin.sha256,
            identifiers=(
                RegistryIdentifier(
                    value=record.identifier.value,
                    scheme_iri="urn:ref:atlas-resource-scheme:nppes-npi-authority",
                    source_path=f"{sample_pin.logical_path}#NPI",
                ),
            ),
            status="boundedPublicSample",
        )
        for record in providers
    )
    return (
        _release(
            key="nppes-data-dissemination-layout-v2-2026-08-03",
            resource_id="nppes-data-dissemination-layout",
            source_module="refspec.registry.nppes_npi_identifiers",
            profile="structureScheme",
            ring="value",
            scope="completeCapture",
            issued="2026-08-03",
            inputs=(header_pin,),
            resources=layout_resources,
            metadata={"fieldCount": len(columns), "layoutVersion": "2"},
        ),
        _release(
            key="nppes-npi-provider-sample-2026-08-03",
            resource_id="nppes-npi-authority",
            source_module="refspec.registry.nppes_npi_identifiers",
            profile="identifierScheme",
            ring="entity",
            scope="captureSubset",
            issued="2026-08-03",
            inputs=(header_pin, sample_pin),
            resources=provider_resources,
            metadata={
                "providerCount": len(providers),
                "completeAuthority": False,
                "providerFieldsRetained": len(columns),
            },
        ),
    )


def _nrc_releases(root: Path) -> tuple[RegistryRelease, ...]:
    fixture_root = Path("tests/fixtures/nrc_adams_codes")
    rows = (
        (nrc.NRC_ADAMS_LANDING_PAGE_2026_08_03, "nrc-adams-landing-page-2026-08-03.html"),
        (nrc.NRC_ADAMS_HELP_REFERENCE_2026_08_03, "nrc-adams-help-reference-2026-08-03.html"),
        (nrc.NRC_ADAMS_FAQ_2026_08_03, "nrc-adams-faq-2026-08-03.html"),
        (nrc.NRC_ADAMS_SYSTEM_NOTICES_2026_08_03, "nrc-adams-system-notices-2026-08-03.html"),
        (nrc.NRC_APS_RESULT_FIELD_LABELS_2026_08_03, "nrc-aps-result-field-labels-excerpt-2026-08-03.js"),
        (nrc.NRC_APS_LIBRARY_FACET_LABELS_2026_08_03, "nrc-aps-library-facet-labels-excerpt-2026-08-03.js"),
    )
    pins: dict[str, RegistryInputPin] = {}
    acquired: dict[str, nrc.AcquiredAdamsSource] = {}
    import tempfile

    with tempfile.TemporaryDirectory(prefix="refspec-nrc-adams-") as temporary:
        for pin_spec, filename in rows:
            logical_path = (fixture_root / filename).as_posix()
            source_iri = (
                f"urn:ref:nrc-adams-capture:{pin_spec.source.resource_name}:"
                + pin_spec.expected_sha256.removeprefix("sha256:")
            )
            pin = _pin(
                root,
                logical_path,
                sha256=pin_spec.expected_sha256,
                byte_length=pin_spec.expected_byte_length,
                source_iri=source_iri,
                role=pin_spec.capture_kind,
            )
            pins[pin_spec.source.resource_name] = pin
            acquired[pin_spec.source.resource_name] = nrc.acquire_adams_source(
                pin_spec,
                Path(temporary),
                source_path=pin.path,
            )

        controls = (
            *nrc.parse_aps_result_field_labels(acquired["apsResultFieldLabels"]),
            *nrc.parse_aps_library_facet_labels(acquired["apsLibraryFacetLabels"]),
            *nrc.parse_docket_number_category_links(acquired["helpReferencePage"]),
        )
        shapes = (
            nrc.parse_docket_number_shape(acquired["faqPage"]),
            nrc.parse_legacy_library_accession_number_shape(acquired["faqPage"]),
            nrc.parse_current_accession_number_shape(acquired["landingPage"]),
            nrc.parse_accession_number_format_notice(acquired["systemNoticesPage"]),
        )

    control_resources: list[RegistryResource] = []
    for ordinal, control in enumerate(controls):
        pin = pins[control.resource_name]
        identity = control.identifiers[-1].value
        control_resources.append(
            RegistryResource(
                iri=(
                    f"urn:ref:nrc-adams-control:{control.resource_name}:"
                    + hashlib.sha256(identity.encode("utf-8")).hexdigest()
                ),
                labels=(_label(control.publisher_label, pin.logical_path),),
                native_payload=_frozen(
                    {
                        "ordinal": ordinal,
                        "control": control,
                        "completeGovernedList": False,
                    }
                ),
                source_locator=pin.source_iri,
                source_digest=pin.sha256,
            )
        )
    shape_resources: list[RegistryResource] = []
    shape_source_names = (
        "faqPage",
        "faqPage",
        "landingPage",
        "systemNoticesPage",
    )
    for ordinal, (shape, source_name) in enumerate(zip(shapes, shape_source_names, strict=True)):
        pin = pins[source_name]
        basis = f"{shape.identifier_kind}:{shape.shape_basis}:{shape.pattern}"
        shape_resources.append(
            RegistryResource(
                iri=("urn:ref:nrc-adams-identifier-shape:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()),
                labels=(
                    _label(
                        f"{shape.identifier_kind} format ({shape.shape_basis})",
                        pin.logical_path,
                    ),
                ),
                native_payload=_frozen(
                    {
                        "ordinal": ordinal,
                        "shape": shape,
                        "sampleValuesAreAuthorityMembers": False,
                    }
                ),
                source_locator=pin.source_iri,
                source_digest=pin.sha256,
                definition=shape.explanation,
                notations=(shape.pattern,),
            )
        )
    return (
        _release(
            key="nrc-adams-native-controls-bounded-2026-08-03",
            resource_id="nrc-adams-native-controls",
            source_module="refspec.registry.nrc_adams_codes",
            profile="structureScheme",
            ring="value",
            scope="captureSubset",
            issued="2026-08-03",
            inputs=tuple(pins.values()),
            resources=control_resources,
            scheme_suffix="observed-structure",
            metadata={
                "controlCount": len(control_resources),
                "completeGovernedList": False,
            },
        ),
        _release(
            key="nrc-adams-identifier-shapes-2026-08-03",
            resource_id="nrc-adams-identifiers",
            source_module="refspec.registry.nrc_adams_codes",
            profile="structureScheme",
            ring="value",
            scope="completeCapture",
            issued="2026-08-03",
            inputs=tuple(pins.values()),
            resources=shape_resources,
            scheme_suffix="identifier-shapes",
            metadata={
                "shapeCount": len(shape_resources),
                "identifierInstancesEmitted": 0,
            },
        ),
    )


def _treasury_releases(root: Path) -> tuple[RegistryRelease, ...]:
    pin_spec = treasury.FAST_BOOK_PART_II_III_2026_07_31
    workbook_pin = _pin(
        root,
        "tests/fixtures/treasury_tas_fast_book/fast-book-part-ii-iii-2026-07-31.xlsx",
        sha256=pin_spec.expected_sha256,
        byte_length=pin_spec.expected_byte_length,
        source_iri=pin_spec.source_url,
        role="publisherWorkbookPartsIIAndIII",
    )
    workbook = treasury.parse_fast_book_workbook(workbook_pin.path, pin=pin_spec)
    by_tas: dict[str, list[treasury.FASTBookPublishedAccount]] = defaultdict(list)
    for account in workbook.accounts:
        by_tas[account.treasury_account_symbol].append(account)
    account_resources: list[RegistryResource] = []
    for tas in sorted(by_tas):
        rows = by_tas[tas]
        first = rows[0]
        account_resources.append(
            RegistryResource(
                iri=f"urn:ref:treasury-account:{quote(tas, safe='')}",
                labels=(
                    _label(
                        f"{first.agency_name} — {first.account_title}",
                        f"{workbook_pin.logical_path}#{tas}",
                    ),
                ),
                native_payload=_frozen(
                    {
                        "treasuryAccountSymbol": tas,
                        "publishedRows": rows,
                        "duplicatePublisherRowCount": len(rows) - 1,
                    }
                ),
                source_locator=workbook_pin.source_iri,
                source_digest=workbook_pin.sha256,
                identifiers=(
                    RegistryIdentifier(
                        value=tas,
                        scheme_iri="urn:ref:atlas-resource-scheme:treasury-account-symbol-structure",
                        source_path=f"{workbook_pin.logical_path}#TAS",
                    ),
                ),
                status="publishedPartIIOrIII",
            )
        )
    fund_counts = Counter((account.part, account.fund_type) for account in workbook.accounts)
    fund_resources: list[RegistryResource] = []
    for fund_type in sorted({account.fund_type for account in workbook.accounts}):
        parts = sorted(
            part for part in {account.part for account in workbook.accounts} if (part, fund_type) in fund_counts
        )
        fund_resources.append(
            RegistryResource(
                iri=("urn:ref:treasury-fast-book:fund-type:" + hashlib.sha256(fund_type.encode("utf-8")).hexdigest()),
                labels=(_label(fund_type, workbook_pin.logical_path),),
                native_payload=_frozen(
                    {
                        "fundType": fund_type,
                        "parts": parts,
                        "accountCountsByPart": {part: fund_counts[(part, fund_type)] for part in parts},
                    }
                ),
                source_locator=workbook_pin.source_iri,
                source_digest=workbook_pin.sha256,
            )
        )
    return (
        _release(
            key="treasury-fast-book-accounts-parts-ii-iii-2026-07",
            resource_id="treasury-account-symbol-structure",
            source_module="refspec.registry.treasury_tas_fast_book",
            profile="identifierScheme",
            ring="legalIdentity",
            scope="completeCapture",
            issued="2026-07-31",
            inputs=(workbook_pin,),
            resources=account_resources,
            metadata={
                "publisherRows": len(workbook.accounts),
                "identifiedAccounts": len(account_resources),
                "publisherAnomalies": workbook.publisher_anomalies,
                "partsIncluded": ["II", "III"],
                "partIMissing": True,
            },
        ),
        _release(
            key="treasury-fast-book-fund-types-parts-ii-iii-2026-07",
            resource_id="treasury-fast-book",
            source_module="refspec.registry.treasury_tas_fast_book",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            issued="2026-07-31",
            inputs=(workbook_pin,),
            resources=fund_resources,
            metadata={
                "fundTypeCount": len(fund_resources),
                "partsIncluded": ["II", "III"],
                "partIMissing": True,
            },
        ),
    )


def _sam_releases(root: Path) -> tuple[RegistryRelease, ...]:
    pin_spec = sam.SAM_ENTITY_3M_PUBLIC_PIN
    source_pin = _pin(
        root,
        "output/registry-real-data-sources/sam-entity-3m-public.json",
        sha256=pin_spec.sha256,
        byte_length=pin_spec.byte_length,
        source_iri=pin_spec.url,
        role="boundedPublicEntityResponse",
    )
    sample = sam.parse_sam_entity_public_response(source_pin.path.read_bytes(), pin_spec)
    if len(sample.ueis) != 1 or len(sample.cages) != 1:
        raise ValueError("bounded SAM sample must contain one UEI and one CAGE record")
    uei = sample.ueis[0]
    cage = sample.cages[0]
    uei_iri = f"urn:ref:sam-entity:uei:{uei.identifier.value}"
    cage_iri = f"urn:ref:dla-cage-facility:{cage.identifier.value}"
    uei_resource = RegistryResource(
        iri=uei_iri,
        labels=(_label(uei.legal_business_name, source_pin.logical_path),),
        native_payload=_frozen(uei.native_payload()),
        source_locator=source_pin.source_iri,
        source_digest=source_pin.sha256,
        identifiers=(
            RegistryIdentifier(
                value=uei.identifier.value,
                scheme_iri="urn:ref:atlas-resource-scheme:uei-authority",
                source_path=f"{source_pin.logical_path}#entityRegistration.ueiSAM",
            ),
        ),
        status=uei.registration_status,
    )
    cage_resource = RegistryResource(
        iri=cage_iri,
        labels=(_label(cage.facility_name, source_pin.logical_path),),
        native_payload=_frozen(cage.native_payload()),
        source_locator=source_pin.source_iri,
        source_digest=source_pin.sha256,
        identifiers=(
            RegistryIdentifier(
                value=cage.identifier.value,
                scheme_iri="urn:ref:atlas-resource-scheme:cage-authority",
                source_path=f"{source_pin.logical_path}#entityRegistration.cageCode",
            ),
        ),
        status=cage.cage_status,
    )
    return (
        _release(
            key="sam-uei-bounded-public-entity-2026-08-03",
            resource_id="uei-authority",
            source_module="refspec.registry.uei_cage_identifiers",
            profile="identifierScheme",
            ring="entity",
            scope="captureSubset",
            issued="2026-08-03",
            inputs=(source_pin,),
            resources=(uei_resource,),
            metadata={"completeAuthority": False, "publicEntityCount": 1},
        ),
        _release(
            key="sam-cage-bounded-public-facility-2026-08-03",
            resource_id="cage-authority",
            source_module="refspec.registry.uei_cage_identifiers",
            profile="identifierScheme",
            ring="entity",
            scope="captureSubset",
            issued="2026-08-03",
            inputs=(source_pin,),
            resources=(cage_resource,),
            relations=(
                RegistryRelation(
                    subject=cage_iri,
                    predicate=ATLAS + "relatedEntity",
                    object=uei_iri,
                    source_payload=_frozen(
                        {
                            "associatedUei": cage.associated_uei,
                            "relationMeaning": "facility is filed under the SAM registrant",
                            "identityEquivalenceClaimed": False,
                        }
                    ),
                ),
            ),
            metadata={
                "completeAuthority": False,
                "publicFacilityCount": 1,
                "dlaCageStatusObserved": False,
            },
        ),
    )


def _gsdm_releases(root: Path) -> tuple[RegistryRelease, ...]:
    dictionary_pin = _pin(
        root,
        "output/registry-real-data-sources/gsdm-data-dictionary-2026-08-03.json",
        sha256=gsdm.GSDM_DATA_DICTIONARY_SHA256,
        byte_length=gsdm.GSDM_DATA_DICTIONARY_BYTE_LENGTH,
        source_iri=gsdm.GSDM_DATA_DICTIONARY_URL,
        role="completeOnlineDataDictionary",
    )
    document_pin = _pin(
        root,
        "output/registry-real-data-sources/gsdm-architecture-v1.0.1.pdf",
        sha256=gsdm.GSDM_DOCUMENT_SHA256,
        byte_length=gsdm.GSDM_DOCUMENT_BYTE_LENGTH,
        source_iri=gsdm.GSDM_DOCUMENT_URL,
        role="architectureDocument",
    )
    dictionary = gsdm.parse_gsdm_data_dictionary(dictionary_pin.path.read_bytes())
    header_keys = [raw for raw, _ in dictionary.headers]
    structure_resources: list[RegistryResource] = []
    for row in dictionary.rows:
        cells = {key: row.cells[position] for position, key in enumerate(header_keys)}
        cells["R:unlabeled_publisher_cell"] = row.cells[-1]
        definition = row.cells[1] if isinstance(row.cells[1], str) else None
        structure_resources.append(
            RegistryResource(
                iri=f"urn:ref:gsdm:data-element:{quote(row.element, safe='')}",
                labels=(_label(row.element, f"{dictionary_pin.logical_path}#row-{row.ordinal}"),),
                native_payload=_frozen(
                    {
                        "ordinal": row.ordinal,
                        "cells": cells,
                        "publisherHeaderCount": len(dictionary.headers),
                        "publisherRowWidth": len(row.cells),
                    }
                ),
                source_locator=dictionary_pin.source_iri,
                source_digest=dictionary_pin.sha256,
                definition=definition,
            )
        )

    domain_resources: list[RegistryResource] = []
    for element in gsdm.GSDM_SCHEMA_CROSSWALK_ELEMENTS:
        for value in element.domain_values:
            group = value.domain_group or "default"
            identity = f"{element.gsdm_element}:{group}:{value.code}"
            domain_resources.append(
                RegistryResource(
                    iri=(
                        "urn:ref:gsdm:domain-value:"
                        + quote(element.gsdm_element, safe="")
                        + ":"
                        + quote(group, safe="")
                        + ":"
                        + quote(value.code, safe="")
                    ),
                    labels=(
                        _label(
                            value.label,
                            f"{dictionary_pin.logical_path}#{identity}",
                        ),
                    ),
                    native_payload=_frozen(
                        {
                            "gsdmElement": element.gsdm_element,
                            "domainGroup": value.domain_group,
                            "code": value.code,
                            "label": value.label,
                            "codeDescription": value.code_description,
                        }
                    ),
                    source_locator=dictionary_pin.source_iri,
                    source_digest=dictionary_pin.sha256,
                    definition=value.code_description,
                    notations=(value.code,),
                )
            )
    return (
        _release(
            key="gsdm-online-data-dictionary-2026-08-03",
            resource_id="governmentwide-spending-data-model",
            source_module="refspec.registry.usaspending_gsdm_codes",
            profile="structureScheme",
            ring="value",
            scope="completeCapture",
            issued="2026-08-03",
            inputs=(dictionary_pin, document_pin),
            resources=structure_resources,
            metadata={
                "dataElementCount": len(structure_resources),
                "architectureVersion": gsdm.GSDM_VERSION,
                "publisherHeaderCount": len(dictionary.headers),
                "publisherRowWidth": gsdm.GSDM_DATA_DICTIONARY_ROW_WIDTH,
            },
        ),
        _release(
            key="gsdm-reviewed-domain-values-2026-08-03",
            resource_id="governmentwide-spending-data-model",
            source_module="refspec.registry.usaspending_gsdm_codes",
            profile="codeScheme",
            ring="value",
            scope="captureSubset",
            issued="2026-08-03",
            inputs=(dictionary_pin,),
            resources=domain_resources,
            scheme_suffix="reviewed-domain-values",
            metadata={
                "domainValueCount": len(domain_resources),
                "typedElements": [element.gsdm_element for element in gsdm.GSDM_SCHEMA_CROSSWALK_ELEMENTS],
                "allStructuralRowsEmitted": True,
            },
        ),
    )


def load_registry_nonemitter_releases(repo_root: Path) -> tuple[RegistryRelease, ...]:
    """Load every real record recovered from descriptor-only registry sources."""

    root = Path(repo_root)
    releases = (
        *_agrovoc_releases(root),
        *_eurovoc_releases(root),
        *_epa_vocabulary_releases(root),
        *_gao_cra_releases(root),
        *_lcsh_releases(root),
        *_fac_releases(root),
        *_epa_substance_releases(root),
        *_federal_hierarchy_releases(root),
        *_govinfo_package_releases(root),
        *_nalt_releases(root),
        *_nppes_releases(root),
        *_nrc_releases(root),
        *_treasury_releases(root),
        *_sam_releases(root),
        *_gsdm_releases(root),
    )
    keys = [release.key for release in releases]
    if len(keys) != len(set(keys)):
        raise ValueError("registry non-emitter adapters produced duplicate release keys")
    return releases


__all__ = ["load_registry_nonemitter_releases"]
