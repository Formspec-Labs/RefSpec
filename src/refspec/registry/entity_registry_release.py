"""Build the standalone entity-registry object for registrant populations.

The Atlas is a sealed reference artifact: identifier authorities and
institutional rosters belong there, but open registrant populations -- SAM
registrants, CAGE facilities, NPI providers, CompTox substances -- are
referents with registry cadence, not reference with vocabulary cadence. This
object carries those records under the same URNs the Atlas exemplars used, so
consumers join by identifier while each object keeps its own release rhythm.
The Atlas producer refuses these authorities outright; see REF-030 in
docs/decisions.md.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from refspec.registry import epa_srs_substances as epa
from refspec.registry import nppes_npi_identifiers as nppes
from refspec.registry import uei_cage_identifiers as sam
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)

ENTITY_REGISTRY_TYPE = "EntityRegistryRelease"
ENTITY_REGISTRY_MANIFEST_TYPE = "EntityRegistryManifest"
ENTITY_REGISTRY_SCHEMA_VERSION = "1.0"
ENTITY_REGISTRY_PAYLOAD_FILE = "entity-registry.json"
ENTITY_REGISTRY_MANIFEST_FILE = "entity-registry-manifest.json"

ATLAS_NS = "https://refspec.org/ns/atlas/v3#"

SAM_ENTITY_PIN_PATH = "output/registry-real-data-sources/sam-entity-3m-public.json"
COMPTOX_SUBSTANCE_PIN_PATH = (
    "output/registry-real-data-sources/comptox-DTXSID7020182.normalized.html"
)
COMPTOX_SUBSTANCE_SHA256 = (
    "sha256:96166f421b896b79f0f0273b26908a5d0dbbcc6ab484e6b15fa41d71ca082803"
)
COMPTOX_SUBSTANCE_BYTE_LENGTH = 334_109
COMPTOX_SUBSTANCE_SOURCE_IRI = (
    "https://comptox.epa.gov/dashboard/chemical/details/DTXSID7020182"
)
COMPTOX_CAPTURED_AT = "2026-08-03T20:00:00Z"
NPPES_FILEHEADER_PIN_PATH = (
    "tests/fixtures/nppes_npi_identifiers/npidata_pfile_fileheader_v2.csv"
)
NPPES_SAMPLE_PIN_PATH = "tests/fixtures/nppes_npi_identifiers/npidata_pfile_sample_v2.csv"


class EntityRegistryError(ValueError):
    """The entity registry cannot be built or verified from these inputs."""


def _verified_bytes(
    repo_root: Path,
    logical_path: str,
    *,
    sha256: str,
    byte_length: int,
) -> bytes:
    path = Path(repo_root) / logical_path
    if not path.is_file():
        raise EntityRegistryError(f"pinned source is missing: {logical_path}")
    data = path.read_bytes()
    if len(data) != byte_length:
        raise EntityRegistryError(
            f"pinned source byte length differs: {logical_path} "
            f"({len(data)} != {byte_length})"
        )
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    expected = sha256 if sha256.startswith("sha256:") else "sha256:" + sha256
    if digest != expected:
        raise EntityRegistryError(f"pinned source digest differs: {logical_path}")
    return data


def _pin_row(
    logical_path: str,
    *,
    sha256: str,
    byte_length: int,
    source_iri: str,
    role: str,
) -> dict[str, Any]:
    return {
        "byteLength": byte_length,
        "logicalPath": logical_path,
        "role": role,
        "sha256": sha256 if sha256.startswith("sha256:") else "sha256:" + sha256,
        "sourceIri": source_iri,
    }


def _record(
    iri: str,
    label: str,
    *,
    identifiers: list[dict[str, str]],
    status: str,
    native_payload: dict[str, Any],
    source_pin: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": iri,
        "identifiers": identifiers,
        "label": label.strip(),
        "nativePayload": native_payload,
        "sourceDigest": source_pin["sha256"],
        "sourceLocator": source_pin["sourceIri"],
        "status": status,
    }


def _release(
    *,
    key: str,
    authority: str,
    issued: str,
    source_pins: list[dict[str, Any]],
    records: list[dict[str, Any]],
    relations: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    if not records:
        raise EntityRegistryError(f"entity registry release {key} carries no records")
    return {
        "authority": authority,
        "issued": issued,
        "key": key,
        "metadata": metadata,
        "records": records,
        "relations": relations or [],
        "ring": "entity",
        "scheme": f"urn:ref:atlas-resource-scheme:{authority}",
        "scope": "captureSubset",
        "sourcePins": source_pins,
    }


def load_sam_registry_releases(repo_root: Path) -> list[dict[str, Any]]:
    pin_spec = sam.SAM_ENTITY_3M_PUBLIC_PIN
    data = _verified_bytes(
        repo_root,
        SAM_ENTITY_PIN_PATH,
        sha256=pin_spec.sha256,
        byte_length=pin_spec.byte_length,
    )
    pin = _pin_row(
        SAM_ENTITY_PIN_PATH,
        sha256=pin_spec.sha256,
        byte_length=pin_spec.byte_length,
        source_iri=pin_spec.url,
        role="boundedPublicEntityResponse",
    )
    sample = sam.parse_sam_entity_public_response(data, pin_spec)
    if len(sample.ueis) != 1 or len(sample.cages) != 1:
        raise EntityRegistryError(
            "bounded SAM sample must contain one UEI and one CAGE record"
        )
    uei = sample.ueis[0]
    cage = sample.cages[0]
    uei_iri = f"urn:ref:sam-entity:uei:{uei.identifier.value}"
    cage_iri = f"urn:ref:dla-cage-facility:{cage.identifier.value}"
    return [
        _release(
            key="sam-uei-bounded-public-entity-2026-08-03",
            authority="uei-authority",
            issued="2026-08-03",
            source_pins=[pin],
            records=[
                _record(
                    uei_iri,
                    uei.legal_business_name,
                    identifiers=[
                        {
                            "scheme": "urn:ref:atlas-resource-scheme:uei-authority",
                            "value": uei.identifier.value,
                        }
                    ],
                    status=uei.registration_status,
                    native_payload=dict(uei.native_payload()),
                    source_pin=pin,
                )
            ],
            metadata={"completeAuthority": False, "publicEntityCount": 1},
        ),
        _release(
            key="sam-cage-bounded-public-facility-2026-08-03",
            authority="cage-authority",
            issued="2026-08-03",
            source_pins=[pin],
            records=[
                _record(
                    cage_iri,
                    cage.facility_name,
                    identifiers=[
                        {
                            "scheme": "urn:ref:atlas-resource-scheme:cage-authority",
                            "value": cage.identifier.value,
                        }
                    ],
                    status=cage.cage_status,
                    native_payload=dict(cage.native_payload()),
                    source_pin=pin,
                )
            ],
            relations=[
                {
                    "object": uei_iri,
                    "predicate": ATLAS_NS + "relatedEntity",
                    "sourcePayload": {
                        "associatedUei": cage.associated_uei,
                        "identityEquivalenceClaimed": False,
                        "relationMeaning": "facility is filed under the SAM registrant",
                    },
                    "subject": cage_iri,
                }
            ],
            metadata={
                "completeAuthority": False,
                "dlaCageStatusObserved": False,
                "publicFacilityCount": 1,
            },
        ),
    ]


def load_nppes_registry_releases(repo_root: Path) -> list[dict[str, Any]]:
    header_bytes = _verified_bytes(
        repo_root,
        NPPES_FILEHEADER_PIN_PATH,
        sha256=nppes.NPPES_FILEHEADER_SHA256,
        byte_length=nppes.NPPES_FILEHEADER_BYTE_LENGTH,
    )
    sample_bytes = _verified_bytes(
        repo_root,
        NPPES_SAMPLE_PIN_PATH,
        sha256=nppes.NPPES_SAMPLE_SHA256,
        byte_length=nppes.NPPES_SAMPLE_BYTE_LENGTH,
    )
    header_pin = _pin_row(
        NPPES_FILEHEADER_PIN_PATH,
        sha256=nppes.NPPES_FILEHEADER_SHA256,
        byte_length=nppes.NPPES_FILEHEADER_BYTE_LENGTH,
        source_iri=nppes.NPPES_FILEHEADER_SOURCE_ID,
        role="publisherFileHeader",
    )
    sample_pin = _pin_row(
        NPPES_SAMPLE_PIN_PATH,
        sha256=nppes.NPPES_SAMPLE_SHA256,
        byte_length=nppes.NPPES_SAMPLE_BYTE_LENGTH,
        source_iri=nppes.NPPES_WEEKLY_CAPTURE_URL + "#bounded-provider-sample",
        role="publisherProviderSample",
    )
    columns = nppes.parse_fileheader_columns(
        header_bytes,
        expected_sha256=nppes.NPPES_FILEHEADER_SHA256,
        expected_byte_length=nppes.NPPES_FILEHEADER_BYTE_LENGTH,
    )
    providers = nppes.parse_npi_provider_sample(
        sample_bytes,
        columns,
        expected_sha256=nppes.NPPES_SAMPLE_SHA256,
        expected_byte_length=nppes.NPPES_SAMPLE_BYTE_LENGTH,
    )
    return [
        _release(
            key="nppes-npi-provider-sample-2026-08-03",
            authority="nppes-npi-authority",
            issued="2026-08-03",
            source_pins=[header_pin, sample_pin],
            records=[
                _record(
                    f"urn:ref:nppes-provider:{record.identifier.value}",
                    record.publisher_label,
                    identifiers=[
                        {
                            "scheme": "urn:ref:atlas-resource-scheme:nppes-npi-authority",
                            "value": record.identifier.value,
                        }
                    ],
                    status="boundedPublicSample",
                    native_payload=dict(record.native_payload()),
                    source_pin=sample_pin,
                )
                for record in providers
            ],
            metadata={
                "completeAuthority": False,
                "providerCount": len(providers),
                "providerFieldsRetained": len(columns),
            },
        )
    ]


def load_comptox_registry_releases(repo_root: Path) -> list[dict[str, Any]]:
    data = _verified_bytes(
        repo_root,
        COMPTOX_SUBSTANCE_PIN_PATH,
        sha256=COMPTOX_SUBSTANCE_SHA256,
        byte_length=COMPTOX_SUBSTANCE_BYTE_LENGTH,
    )
    pin = _pin_row(
        COMPTOX_SUBSTANCE_PIN_PATH,
        sha256=COMPTOX_SUBSTANCE_SHA256,
        byte_length=COMPTOX_SUBSTANCE_BYTE_LENGTH,
        source_iri=COMPTOX_SUBSTANCE_SOURCE_IRI,
        role="boundedPublisherSubstancePage",
    )
    sample = epa.parse_comptox_detail_page(
        data,
        source_uri=COMPTOX_SUBSTANCE_SOURCE_IRI,
        captured_at=COMPTOX_CAPTURED_AT,
    )
    return [
        _release(
            key="epa-comptox-substance-bounded-2026-08-03",
            authority="epa-substance-identifiers",
            issued="2026-08-03",
            source_pins=[pin],
            records=[
                _record(
                    f"urn:ref:epa-substance:{record.dtxsid}",
                    record.preferred_name,
                    identifiers=[
                        {
                            "scheme": (
                                "urn:ref:atlas-resource-scheme:epa-substance-identifiers"
                            ),
                            "value": value,
                        }
                        for value in (record.dtxsid, record.dtxcid, record.casrn)
                        if value is not None
                    ],
                    status="boundedPublicSample",
                    native_payload=dict(record.native_payload()),
                    source_pin=pin,
                )
                for record in sample.records
            ],
            metadata={
                "completePublisherRelease": False,
                "identifierKinds": ["DTXSID", "DTXCID", "CASRN"],
                "substanceCount": len(sample.records),
            },
        )
    ]


def build_entity_registry_payload(repo_root: str | Path) -> dict[str, Any]:
    """Parse every pinned registrant capture into one deterministic payload."""

    root = Path(repo_root)
    releases = [
        *load_comptox_registry_releases(root),
        *load_nppes_registry_releases(root),
        *load_sam_registry_releases(root),
    ]
    releases.sort(key=lambda release: release["key"])
    keys = [release["key"] for release in releases]
    if len(keys) != len(set(keys)):
        raise EntityRegistryError("entity registry releases carry duplicate keys")
    counts = {
        "identifiers": sum(
            len(record["identifiers"])
            for release in releases
            for record in release["records"]
        ),
        "records": sum(len(release["records"]) for release in releases),
        "relations": sum(len(release["relations"]) for release in releases),
        "releases": len(releases),
    }
    return {
        "counts": counts,
        "releases": releases,
        "schemaVersion": ENTITY_REGISTRY_SCHEMA_VERSION,
        "type": ENTITY_REGISTRY_TYPE,
    }


def write_entity_registry(repo_root: str | Path, output: str | Path) -> dict[str, Any]:
    """Write the payload and its manifest; refuse to replace differing output."""

    payload = build_entity_registry_payload(repo_root)
    payload_bytes = canonical_json_bytes(payload)
    manifest = {
        "counts": payload["counts"],
        "payloadPath": ENTITY_REGISTRY_PAYLOAD_FILE,
        "payloadSha256": sha256_digest(payload_bytes),
        "schemaVersion": ENTITY_REGISTRY_SCHEMA_VERSION,
        "type": ENTITY_REGISTRY_MANIFEST_TYPE,
    }
    manifest_bytes = canonical_json_bytes(manifest)
    target = Path(output)
    payload_path = target / ENTITY_REGISTRY_PAYLOAD_FILE
    manifest_path = target / ENTITY_REGISTRY_MANIFEST_FILE
    if target.exists():
        existing = (
            payload_path.read_bytes() if payload_path.is_file() else None,
            manifest_path.read_bytes() if manifest_path.is_file() else None,
        )
        if existing != (payload_bytes, manifest_bytes):
            raise EntityRegistryError(f"refusing to replace differing output: {target}")
        return manifest
    target.mkdir(parents=True)
    payload_path.write_bytes(payload_bytes)
    manifest_path.write_bytes(manifest_bytes)
    return manifest


def verify_entity_registry(output: str | Path) -> dict[str, Any]:
    """Check the written object against its manifest and return the manifest."""

    target = Path(output)
    manifest_path = target / ENTITY_REGISTRY_MANIFEST_FILE
    if not manifest_path.is_file():
        raise EntityRegistryError(f"entity registry manifest is missing: {manifest_path}")
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except ValueError as error:
        raise EntityRegistryError("entity registry manifest is invalid JSON") from error
    if canonical_json_bytes(manifest) != manifest_bytes:
        raise EntityRegistryError("entity registry manifest is not canonical JSON")
    if manifest.get("type") != ENTITY_REGISTRY_MANIFEST_TYPE:
        raise EntityRegistryError("entity registry manifest type is unsupported")
    payload_path = target / manifest["payloadPath"]
    if not payload_path.is_file():
        raise EntityRegistryError(f"entity registry payload is missing: {payload_path}")
    payload_bytes = payload_path.read_bytes()
    if sha256_digest(payload_bytes) != manifest["payloadSha256"]:
        raise EntityRegistryError("entity registry payload digest differs")
    payload = json.loads(payload_bytes)
    if payload.get("counts") != manifest.get("counts"):
        raise EntityRegistryError("entity registry counts differ from the manifest")
    return manifest


__all__ = [
    "ENTITY_REGISTRY_MANIFEST_FILE",
    "ENTITY_REGISTRY_MANIFEST_TYPE",
    "ENTITY_REGISTRY_PAYLOAD_FILE",
    "ENTITY_REGISTRY_SCHEMA_VERSION",
    "ENTITY_REGISTRY_TYPE",
    "EntityRegistryError",
    "build_entity_registry_payload",
    "load_comptox_registry_releases",
    "load_nppes_registry_releases",
    "load_sam_registry_releases",
    "verify_entity_registry",
    "write_entity_registry",
]
