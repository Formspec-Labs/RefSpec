"""Searchable development packages for captured CRS controlled terms.

Congress.gov publishes useful Legislative Subject Terms and Policy Areas, but
the captured pages do not expose stable publisher term identifiers or a named
vocabulary release.  These packages preserve the exact source rows for
development lookup while keeping every row a capture-local observation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from refspec.registry.crs_legislative_resources import (
    CRS_LEGISLATIVE_GEOGRAPHIC_PAGE,
    CRS_LEGISLATIVE_ORGANIZATIONS_PAGE,
    CRS_LEGISLATIVE_SUBJECT_TERM_PAGES,
    CRS_LEGISLATIVE_SUBJECTS_PAGE,
    CRS_POLICY_AREAS_PAGE,
    AcquiredCRSPage,
    CRSControlledTerm,
    CRSPageSnapshotPin,
    CRSSourceDriftError,
    ParsedCRSResource,
    acquire_crs_page,
    assemble_crs_legislative_subject_terms,
    assemble_crs_policy_areas,
    parse_crs_field_value_page,
    sha256_digest,
)
from refspec.registry.source_controlled_resource import (
    ResourceKind,
    ResourceUse,
    SourceControlledResourceBundle,
    build_source_controlled_resource_bundle,
)
from refspec.storage import canonical_json

CRS_CAPTURE_DATE = "2026-07-30"
CRS_COMPLETE_CAPTURED_AT = "2026-07-30T13:01:22Z"
CRS_PACKAGE_EVIDENCE_VERSION = "1.0"

CRS_LEGISLATIVE_SUBJECT_TERMS_RESOURCE_ID = "crs-legislative-subject-terms-capture-2026-07-30"
CRS_POLICY_AREAS_RESOURCE_ID = "crs-policy-areas-capture-2026-07-30"

CRS_LEGISLATIVE_SUBJECTS_PIN = CRSPageSnapshotPin(
    source=CRS_LEGISLATIVE_SUBJECTS_PAGE,
    retrieved_at="2026-07-30T13:00:42Z",
    expected_sha256=("sha256:8b4964a8cea53d63bce0a029bac38a2bc260059883120bc36e1759a4b5e844d1"),
    expected_byte_length=410_454,
)
CRS_LEGISLATIVE_GEOGRAPHIC_PIN = CRSPageSnapshotPin(
    source=CRS_LEGISLATIVE_GEOGRAPHIC_PAGE,
    retrieved_at="2026-07-30T13:01:19Z",
    expected_sha256=("sha256:7dfefc6e8b17b3a86a9c9009453e792453eef01b099177ef29f4dc172d19d3d0"),
    expected_byte_length=384_627,
)
CRS_LEGISLATIVE_ORGANIZATIONS_PIN = CRSPageSnapshotPin(
    source=CRS_LEGISLATIVE_ORGANIZATIONS_PAGE,
    retrieved_at="2026-07-30T13:01:21Z",
    expected_sha256=("sha256:fa870ff36352c3482a68aad4d9cff69bd8ff98294a7dd21b1e36f0a534b2b880"),
    expected_byte_length=381_186,
)
CRS_POLICY_AREAS_PIN = CRSPageSnapshotPin(
    source=CRS_POLICY_AREAS_PAGE,
    retrieved_at="2026-07-30T13:01:22Z",
    expected_sha256=("sha256:16d806e4a07df391de776d0bd5fade9d0bce89fe33b564036c94e0749df91326"),
    expected_byte_length=383_558,
)
CRS_PAGE_SNAPSHOT_PINS = (
    CRS_LEGISLATIVE_SUBJECTS_PIN,
    CRS_LEGISLATIVE_GEOGRAPHIC_PIN,
    CRS_LEGISLATIVE_ORGANIZATIONS_PIN,
    CRS_POLICY_AREAS_PIN,
)

_EXPECTED_SOURCES = (
    *CRS_LEGISLATIVE_SUBJECT_TERM_PAGES,
    CRS_POLICY_AREAS_PAGE,
)
_EXPECTED_SOURCE_BY_KEY = {(source.resource_name, source.term_category): source for source in _EXPECTED_SOURCES}


@dataclass(frozen=True, slots=True)
class CRSSourcePackages:
    """The separate detailed-term and broad-navigation packages."""

    legislative_subject_terms: SourceControlledResourceBundle
    policy_areas: SourceControlledResourceBundle

    def resources(self) -> tuple[SourceControlledResourceBundle, ...]:
        """Return both packages in their stable product order."""

        return (self.legislative_subject_terms, self.policy_areas)


def _page_key(page: AcquiredCRSPage) -> tuple[str, str]:
    source = page.pin.source
    return source.resource_name, source.term_category


def _ordered_pages(
    pages: Sequence[AcquiredCRSPage],
) -> tuple[AcquiredCRSPage, ...]:
    by_key: dict[tuple[str, str], AcquiredCRSPage] = {}
    for page in pages:
        key = _page_key(page)
        expected = _EXPECTED_SOURCE_BY_KEY.get(key)
        if expected is None or page.pin.source.source_url != expected.source_url:
            raise CRSSourceDriftError(
                "CRS source packages accept only the four reviewed Congress.gov field-value pages"
            )
        if key in by_key:
            raise CRSSourceDriftError(f"CRS source packages received a duplicate {key[0]}/{key[1]} page")
        by_key[key] = page
    missing = [
        f"{source.resource_name}/{source.term_category}"
        for source in _EXPECTED_SOURCES
        if (source.resource_name, source.term_category) not in by_key
    ]
    if missing:
        raise CRSSourceDriftError(f"CRS source packages require all four reviewed pages; missing {missing}")
    return tuple(by_key[(source.resource_name, source.term_category)] for source in _EXPECTED_SOURCES)


def _verified_source_bytes(page: AcquiredCRSPage) -> bytes:
    path = Path(page.path)
    if path.is_symlink() or not path.is_file():
        raise CRSSourceDriftError("CRS source package input must be a regular retained source file")
    payload = path.read_bytes()
    if len(payload) != page.byte_length or len(payload) != page.pin.expected_byte_length:
        raise CRSSourceDriftError("CRS source package input byte length changed after acquisition")
    digest = sha256_digest(payload)
    if digest != page.sha256 or digest != page.pin.expected_sha256:
        raise CRSSourceDriftError("CRS source package input digest changed after acquisition")
    return payload


def _source_artifact_iri(page: AcquiredCRSPage) -> str:
    digest = page.sha256.removeprefix("sha256:")
    return f"urn:ref:crs-source-artifact:{page.pin.source.term_category}:{digest}"


def _observation(
    term: CRSControlledTerm,
    page: AcquiredCRSPage,
    *,
    eligible_uses: tuple[str, ...],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": term.record_iri,
        "sourceArtifact": _source_artifact_iri(page),
        "sourcePath": (f"fieldValues/{term.category}[{term.source_ordinal}]"),
        "sourceOrdinal": term.source_ordinal,
        "labels": [
            {
                "value": term.official_label,
                "language": term.language,
                "role": "preferred",
            }
        ],
        # Congress.gov exposes the label, not a stable term ID or term IRI.
        "identifiers": [],
        "eligibleUses": list(eligible_uses),
        "conceptIdentityClaimed": False,
        "resourceName": term.resource_name,
        "category": term.category,
        "sourceUrl": term.source_url,
        "sourceObservedAt": page.pin.retrieved_at,
        "identityStatus": term.identity_status,
        "publisherReleaseStatus": "namedReleaseAbsent",
    }
    if term.definition is not None:
        row["definition"] = term.definition
    return row


def _resource_gaps(term_count: int) -> tuple[dict[str, Any], ...]:
    return (
        {
            "code": "publisherTermIdentifiersAbsent",
            "affectedObservationCount": term_count,
            "effect": ("Rows remain capture-local observations and cannot be treated as publisher concepts."),
        },
        {
            "code": "publisherNamedReleaseAbsent",
            "affectedObservationCount": term_count,
            "effect": ("The capture can support development lookup but cannot claim a publisher vocabulary release."),
        },
    )


def _build_resource_package(
    resource: ParsedCRSResource,
    acquired_pages: tuple[AcquiredCRSPage, ...],
    *,
    resource_id: str,
    title: str,
    resource_kind: ResourceKind,
    uses: tuple[ResourceUse, ...],
    captured_at: str,
    candidate_use_authorized: bool,
) -> SourceControlledResourceBundle:
    acquired_by_category = {page.pin.source.term_category: page for page in acquired_pages}
    observations = tuple(
        _observation(
            term,
            acquired_by_category[term.category],
            eligible_uses=uses,
        )
        for term in resource.terms
    )
    source_artifacts = {_source_artifact_iri(page): _verified_source_bytes(page) for page in acquired_pages}
    return build_source_controlled_resource_bundle(
        resource_id=resource_id,
        title=title,
        resource_kind=resource_kind,
        identity_status="captureLocalObservationsOnly",
        uses=uses,
        captured_at=captured_at,
        candidate_use_authorized=candidate_use_authorized,
        observations=observations,
        source_artifacts=source_artifacts,
        source_observed_count=len(resource.terms),
        gaps=_resource_gaps(len(resource.terms)),
    )


def build_crs_source_packages(
    pages: Sequence[AcquiredCRSPage],
    *,
    captured_at: str,
) -> CRSSourcePackages:
    """Build separate deterministic packages from the four exact captures."""

    ordered = _ordered_pages(tuple(pages))
    parsed = tuple(parse_crs_field_value_page(page) for page in ordered)
    legislative_resource = assemble_crs_legislative_subject_terms(parsed[:3])
    policy_resource = assemble_crs_policy_areas(parsed[3])

    legislative_package = _build_resource_package(
        legislative_resource,
        ordered[:3],
        resource_id=CRS_LEGISLATIVE_SUBJECT_TERMS_RESOURCE_ID,
        title="CRS Legislative Subject Terms source observations",
        resource_kind="sourceTermSnapshot",
        uses=("sourceAssignedEvidence", "searchExpansion"),
        captured_at=captured_at,
        candidate_use_authorized=True,
    )
    policy_package = _build_resource_package(
        policy_resource,
        ordered[3:],
        resource_id=CRS_POLICY_AREAS_RESOURCE_ID,
        title="CRS Policy Areas source observations",
        resource_kind="navigationList",
        uses=("sourceAssignedEvidence", "navigation"),
        captured_at=captured_at,
        candidate_use_authorized=False,
    )
    return CRSSourcePackages(
        legislative_subject_terms=legislative_package,
        policy_areas=policy_package,
    )


def build_crs_source_packages_from_capture_root(
    capture_root: Path,
    *,
    captured_at: str = CRS_COMPLETE_CAPTURED_AT,
) -> CRSSourcePackages:
    """Strictly reopen the four reviewed 2026-07-30 captures and package them."""

    acquired = tuple(acquire_crs_page(pin, Path(capture_root)) for pin in CRS_PAGE_SNAPSHOT_PINS)
    return build_crs_source_packages(acquired, captured_at=captured_at)


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _source_evidence(
    package: SourceControlledResourceBundle,
) -> list[dict[str, Any]]:
    by_source: dict[str, dict[str, Any]] = {}
    for observation in package.observations:
        source_id = str(observation["sourceArtifact"])
        row = {
            "id": source_id,
            "category": observation["category"],
            "sourceUrl": observation["sourceUrl"],
            "retrievedAt": observation["sourceObservedAt"],
        }
        previous = by_source.setdefault(source_id, row)
        if previous != row:
            raise CRSSourceDriftError(f"source artifact {source_id!r} has inconsistent observation metadata")
    result: list[dict[str, Any]] = []
    for descriptor in package.resource_manifest["sourceArtifacts"]:
        source_id = descriptor["id"]
        result.append(
            {
                **by_source[source_id],
                "sha256": descriptor["sha256"],
                "byteLength": descriptor["byteLength"],
            }
        )
    return result


def _package_evidence(
    package: SourceControlledResourceBundle,
) -> dict[str, Any]:
    artifacts = package.artifact_bytes()
    category_counts: dict[str, int] = {}
    for observation in package.observations:
        category = str(observation["category"])
        category_counts[category] = category_counts.get(category, 0) + 1
    return {
        "resourceId": package.resource_manifest["resourceId"],
        "resourceKind": package.resource_manifest["resourceKind"],
        "logicalDigest": package.logical_digest,
        "observationCount": len(package.observations),
        "observationSetDigest": package.coverage_report["observationSetDigest"],
        "categoryCounts": category_counts,
        "coverageStatus": package.coverage_report["reportStatus"],
        "coverageGaps": [gap["code"] for gap in package.coverage_report["gaps"]],
        "candidateUseAuthorized": package.resource_manifest["candidateUseAuthorized"],
        "acceptedOutputUseAuthorized": package.resource_manifest["acceptedOutputUseAuthorized"],
        "conceptIdentityClaimed": package.resource_manifest["conceptIdentityClaimed"],
        "uses": package.resource_manifest["uses"],
        "sourceArtifacts": _source_evidence(package),
        "packageArtifacts": [
            {
                "path": path,
                "sha256": _sha256(payload),
                "byteLength": len(payload),
            }
            for path, payload in sorted(artifacts.items())
        ],
    }


def crs_source_package_evidence(
    packages: CRSSourcePackages,
) -> dict[str, Any]:
    """Summarize the exact package identities and their source limitations."""

    return {
        "schemaVersion": CRS_PACKAGE_EVIDENCE_VERSION,
        "evidenceKind": "crsSourceControlledResourcePackages",
        "capturedAt": packages.legislative_subject_terms.resource_manifest["capturedAt"],
        "sourceLimitations": [
            "Congress.gov did not expose stable publisher term identifiers or term IRIs.",
            "Congress.gov did not publish the captured pages as a named, versioned vocabulary release.",
            "Package observation IRIs are capture-local records, not publisher concept identities.",
        ],
        "resources": [_package_evidence(package) for package in packages.resources()],
    }


def crs_source_package_evidence_bytes(
    packages: CRSSourcePackages,
) -> bytes:
    """Serialize package evidence deterministically."""

    return canonical_json(crs_source_package_evidence(packages)).encode("utf-8") + b"\n"


__all__ = [
    "CRS_CAPTURE_DATE",
    "CRS_COMPLETE_CAPTURED_AT",
    "CRS_LEGISLATIVE_GEOGRAPHIC_PIN",
    "CRS_LEGISLATIVE_ORGANIZATIONS_PIN",
    "CRS_LEGISLATIVE_SUBJECTS_PIN",
    "CRS_LEGISLATIVE_SUBJECT_TERMS_RESOURCE_ID",
    "CRS_PACKAGE_EVIDENCE_VERSION",
    "CRS_PAGE_SNAPSHOT_PINS",
    "CRS_POLICY_AREAS_PIN",
    "CRS_POLICY_AREAS_RESOURCE_ID",
    "CRSSourcePackages",
    "build_crs_source_packages",
    "build_crs_source_packages_from_capture_root",
    "crs_source_package_evidence",
    "crs_source_package_evidence_bytes",
]
