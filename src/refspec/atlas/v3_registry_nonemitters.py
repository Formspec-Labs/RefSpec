"""Finish Atlas 3 adapters for bounded descriptor-only registry sources.

Every adapter consumes exact publisher bytes through its registry parser and
states its capture scope. Partial samples remain partial samples; structural
definitions remain structural definitions; identifiers attach to the entity or
legal resource they identify. No adapter promotes examples into authority
membership or creates an identifier ring.

Registrant populations (SAM registrants, CAGE facilities, NPI providers,
CompTox substances) are not loaded here: they are referents with registry
cadence, carried by ``refspec.registry.entity_registry_release`` instead, and
the producer refuses their authorities outright (REF-030).

Observed inventories are not loaded here either (REF-032). What survives is
publisher-*written* structure: FAC's field dictionary, NPPES's dissemination
layout, the FAST Book's published account symbols, and GSDM's data
dictionary. Set-distincts over sampled records, first-page roster slices,
scraped search widgets, and regexed identifier shapes left the Atlas.
"""

from __future__ import annotations

import dataclasses
import tempfile
from collections import defaultdict
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
    RegistryIdentifier,
    RegistryInputPin,
    RegistryLabel,
    RegistryRelation,
    RegistryRelease,
    RegistryResource,
    canonical_digest,
)
from refspec.immutable import deep_freeze_json
from refspec.registry import fac_dictionary as fac
from refspec.registry import nppes_npi_identifiers as nppes
from refspec.registry import treasury_tas_fast_book as treasury
from refspec.registry import usaspending_gsdm_codes as gsdm


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


def _nppes_releases(root: Path) -> tuple[RegistryRelease, ...]:
    header_pin = _pin(
        root,
        "tests/fixtures/nppes_npi_identifiers/npidata_pfile_fileheader_v2.csv",
        sha256=nppes.NPPES_FILEHEADER_SHA256,
        byte_length=nppes.NPPES_FILEHEADER_BYTE_LENGTH,
        source_iri=nppes.NPPES_FILEHEADER_SOURCE_ID,
        role="publisherFileHeader",
    )
    columns = nppes.parse_fileheader_columns(
        header_pin.path.read_bytes(),
        expected_sha256=header_pin.sha256,
        expected_byte_length=header_pin.byte_length,
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
    return (
        _release(
            key="treasury-fast-book-accounts-parts-ii-iii-2026-07",
            resource_id="treasury-account-symbol-structure",
            source_module="refspec.registry.treasury_tas_fast_book",
            profile="identifierScheme",
            ring="entity",
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


REGISTRY_NONEMITTER_RELEASE_GROUPS = (
    ("fac", frozenset({"fac-api-field-dictionary-2026-08-03"})),
    (
        "nppes",
        frozenset({"nppes-data-dissemination-layout-v2-2026-08-03"}),
    ),
    (
        "treasury",
        frozenset({"treasury-fast-book-accounts-parts-ii-iii-2026-07"}),
    ),
    (
        "gsdm",
        frozenset(
            {
                "gsdm-online-data-dictionary-2026-08-03",
                "gsdm-reviewed-domain-values-2026-08-03",
            }
        ),
    ),
)
REGISTRY_NONEMITTER_RELEASE_KEYS = frozenset(
    key
    for _group_name, group_keys in REGISTRY_NONEMITTER_RELEASE_GROUPS
    for key in group_keys
)


def load_registry_nonemitter_releases(
    repo_root: Path,
    *,
    only_keys: Collection[str] | None = None,
) -> tuple[RegistryRelease, ...]:
    """Load selected records recovered from descriptor-only registry sources."""

    requested = normalize_only_keys(
        only_keys,
        allowed_keys=REGISTRY_NONEMITTER_RELEASE_KEYS,
        loader_name="load_registry_nonemitter_releases",
    )
    root = Path(repo_root)
    loaders = {
        "fac": _fac_releases,
        "nppes": _nppes_releases,
        "treasury": _treasury_releases,
        "gsdm": _gsdm_releases,
    }
    releases: list[RegistryRelease] = []
    for group_name, group_keys in REGISTRY_NONEMITTER_RELEASE_GROUPS:
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
        raise ValueError("registry non-emitter adapters produced duplicate release keys")
    return tuple(releases)


__all__ = [
    "REGISTRY_NONEMITTER_RELEASE_GROUPS",
    "REGISTRY_NONEMITTER_RELEASE_KEYS",
    "load_registry_nonemitter_releases",
]
