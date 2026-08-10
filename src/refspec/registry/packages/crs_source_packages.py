"""Searchable development packages for captured CRS controlled terms.

The Library of Congress identifies the two source schemes as ``lst`` and
``cgpa``.  Congress.gov publishes their useful term labels, but the captured
pages do not expose stable publisher term identifiers or a named, versioned
release.  These packages fuse each LoC scheme authority record with its
Congress.gov rows.  Each acquisition has a persisted UUIDv7, each observation
gets a RefSpec local record UUIDv7, and later captures carry that local ID
forward only through conservative reconciliation.  Neither ID claims that CRS
or the Library of Congress issued a term identifier.
"""

from __future__ import annotations

import base64
import binascii
import difflib
import hashlib
import importlib.resources
import json
import os
import shutil
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from refspec.registry.crs_legislative_resources import (
    CRS_LEGISLATIVE_GEOGRAPHIC_PAGE,
    CRS_LEGISLATIVE_ORGANIZATIONS_PAGE,
    CRS_LEGISLATIVE_SUBJECT_TERM_PAGES,
    CRS_LEGISLATIVE_SUBJECT_TERMS_SCHEME,
    CRS_LEGISLATIVE_SUBJECTS_PAGE,
    CRS_POLICY_AREAS_PAGE,
    CRS_POLICY_AREAS_SCHEME,
    AcquiredCRSPage,
    CRSControlledTerm,
    CRSIdentityError,
    CRSPageSnapshotPin,
    CRSSourceDriftError,
    CRSSourceScheme,
    ParsedCRSResource,
    acquire_crs_page,
    assemble_crs_legislative_subject_terms,
    assemble_crs_policy_areas,
    parse_crs_field_value_page,
    sha256_digest,
)
from refspec.registry.infrastructure.artifact_serialization import plain_json
from refspec.registry.infrastructure.source_controlled_resource import (
    ResourceKind,
    ResourceUse,
    SourceControlledResourceBundle,
    SourceControlledResourceView,
    build_source_controlled_resource_bundle,
    capture_independent_observation,
)
from refspec.registry.infrastructure.source_identity import (
    SourceCaptureEvent,
    SourceIdentityError,
    SourceRegistrationEvent,
    validate_uuid7_urn,
)
from refspec.storage import canonical_json

CRS_CAPTURE_DATE = "2026-07-30"
CRS_PACKAGE_DATE = "2026-08-03"
CRS_SCHEME_AUTHORITY_CAPTURED_AT = "2026-08-03T23:25:59Z"
CRS_COMPLETE_CAPTURED_AT = CRS_SCHEME_AUTHORITY_CAPTURED_AT
CRS_REGISTRATION_ID = "019fc9f2-c758-7b5c-9c19-f7fe5e2bf611"
CRS_REGISTRATION_EVENT = SourceRegistrationEvent(
    registration_id=CRS_REGISTRATION_ID,
    registered_at=CRS_COMPLETE_CAPTURED_AT,
)
CRS_PACKAGE_EVIDENCE_VERSION = "2.0"

CRS_LEGISLATIVE_SUBJECT_TERMS_RESOURCE_ID = f"crs-legislative-subject-terms-capture-{CRS_PACKAGE_DATE}"
CRS_POLICY_AREAS_RESOURCE_ID = f"crs-policy-areas-capture-{CRS_PACKAGE_DATE}"

CRSReconciliationStatus = Literal[
    "initial",
    "unchanged",
    "sourceOnlyChange",
    "reviewRequired",
    "reviewed",
]


@dataclass(frozen=True, slots=True)
class CRSIdentityLink:
    """A human decision that two capture rows continue one local record."""

    current_observation_id: str
    previous_local_record_id: str
    reason: str

    def __post_init__(self) -> None:
        if not self.current_observation_id.strip() or not self.reason.strip():
            raise CRSIdentityError("CRS identity link observation and reason must not be empty")
        try:
            validate_uuid7_urn(
                self.previous_local_record_id,
                label="previous_local_record_id",
            )
        except SourceIdentityError as error:
            raise CRSIdentityError(str(error)) from error

    def as_dict(self) -> dict[str, str]:
        return {
            "currentObservationId": self.current_observation_id,
            "previousLocalRecordId": self.previous_local_record_id,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class CRSIdentityReview:
    """A named human decision over one exact proposed capture change."""

    review_id: str
    resource_name: str
    proposal_change_digest: str
    reviewed_at: str
    attestor: str
    identity_links: tuple[CRSIdentityLink, ...]
    reason: str

    def __post_init__(self) -> None:
        try:
            review_uuid = validate_uuid7_urn(self.review_id, label="review_id")
            SourceCaptureEvent(
                fetch_id=review_uuid.removeprefix("urn:uuid:"),
                fetched_at=self.reviewed_at,
            )
        except SourceIdentityError as error:
            raise CRSIdentityError(f"CRS identity review is invalid: {error}") from error
        reviewer = urlsplit(self.attestor)
        if not reviewer.scheme or reviewer.username is not None or reviewer.password is not None:
            raise CRSIdentityError("CRS identity review attestor must be an absolute IRI")
        if not self.resource_name.strip() or not self.reason.strip():
            raise CRSIdentityError("CRS identity review resource and reason must not be empty")
        digest_hex = self.proposal_change_digest.removeprefix("sha256:")
        if (
            not self.proposal_change_digest.startswith("sha256:")
            or len(digest_hex) != 64
            or any(character not in "0123456789abcdef" for character in digest_hex)
        ):
            raise CRSIdentityError("CRS identity review must name a SHA-256 proposal digest")
        current_ids = [link.current_observation_id for link in self.identity_links]
        previous_ids = [link.previous_local_record_id for link in self.identity_links]
        if len(current_ids) != len(set(current_ids)) or len(previous_ids) != len(set(previous_ids)):
            raise CRSIdentityError("CRS identity review links must be one-to-one")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.review_id,
            "resourceName": self.resource_name,
            "proposalChangeDigest": self.proposal_change_digest,
            "reviewedAt": self.reviewed_at,
            "attestor": self.attestor,
            "identityLinks": [link.as_dict() for link in self.identity_links],
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class CRSResourceReconciliation:
    """Identity and content changes between two local CRS captures."""

    resource_name: str
    status: CRSReconciliationStatus
    previous_manifest_id: str | None
    current_manifest_id: str
    previous_local_record_id_set_digest: str | None
    current_local_record_id_set_digest: str
    previous_local_record_content_set_digest: str | None
    current_local_record_content_set_digest: str
    auto_matched_count: int
    added_records: tuple[Mapping[str, Any], ...]
    removed_records: tuple[Mapping[str, Any], ...]
    changed_records: tuple[Mapping[str, Any], ...]
    match_suggestions: tuple[Mapping[str, Any], ...]
    requires_human_review: bool
    change_digest: str
    review: Mapping[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CRSResourceReconciliation:
        """Reopen one persisted reconciliation row without weakening its shape."""

        expected = {
            "resourceName",
            "status",
            "previousManifestId",
            "currentManifestId",
            "previousLocalRecordIdSetDigest",
            "currentLocalRecordIdSetDigest",
            "previousLocalRecordContentSetDigest",
            "currentLocalRecordContentSetDigest",
            "autoMatchedCount",
            "addedRecords",
            "removedRecords",
            "changedRecords",
            "matchSuggestions",
            "requiresHumanReview",
            "changeDigest",
            "review",
        }
        if set(value) != expected:
            raise CRSIdentityError("persisted CRS reconciliation fields are unsupported")
        status = value["status"]
        if status not in {"initial", "unchanged", "sourceOnlyChange", "reviewRequired", "reviewed"}:
            raise CRSIdentityError("persisted CRS reconciliation status is unsupported")

        def rows(name: str) -> tuple[Mapping[str, Any], ...]:
            items = value[name]
            if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
                raise CRSIdentityError(f"persisted CRS reconciliation {name} must be an array")
            if not all(isinstance(item, Mapping) for item in items):
                raise CRSIdentityError(f"persisted CRS reconciliation {name} contains a non-object")
            return tuple(dict(item) for item in items)

        auto_matched_count = value["autoMatchedCount"]
        requires_review = value["requiresHumanReview"]
        review = value["review"]
        if not isinstance(auto_matched_count, int) or isinstance(auto_matched_count, bool) or auto_matched_count < 0:
            raise CRSIdentityError("persisted CRS reconciliation autoMatchedCount is invalid")
        if not isinstance(requires_review, bool):
            raise CRSIdentityError("persisted CRS reconciliation requiresHumanReview is invalid")
        if review is not None and not isinstance(review, Mapping):
            raise CRSIdentityError("persisted CRS reconciliation review must be an object or null")
        text_fields = (
            "resourceName",
            "currentManifestId",
            "currentLocalRecordIdSetDigest",
            "currentLocalRecordContentSetDigest",
            "changeDigest",
        )
        if any(not isinstance(value[field], str) or not value[field] for field in text_fields):
            raise CRSIdentityError("persisted CRS reconciliation is missing required text")
        optional_text_fields = (
            "previousManifestId",
            "previousLocalRecordIdSetDigest",
            "previousLocalRecordContentSetDigest",
        )
        if any(value[field] is not None and not isinstance(value[field], str) for field in optional_text_fields):
            raise CRSIdentityError("persisted CRS reconciliation has invalid previous-capture identity")
        result = cls(
            resource_name=value["resourceName"],
            status=status,
            previous_manifest_id=value["previousManifestId"],
            current_manifest_id=value["currentManifestId"],
            previous_local_record_id_set_digest=value["previousLocalRecordIdSetDigest"],
            current_local_record_id_set_digest=value["currentLocalRecordIdSetDigest"],
            previous_local_record_content_set_digest=value["previousLocalRecordContentSetDigest"],
            current_local_record_content_set_digest=value["currentLocalRecordContentSetDigest"],
            auto_matched_count=auto_matched_count,
            added_records=rows("addedRecords"),
            removed_records=rows("removedRecords"),
            changed_records=rows("changedRecords"),
            match_suggestions=rows("matchSuggestions"),
            requires_human_review=requires_review,
            change_digest=value["changeDigest"],
            review=None if review is None else dict(review),
        )
        if result.as_dict() != dict(value):
            raise CRSIdentityError("persisted CRS reconciliation is not canonical")
        return result

    def as_dict(self) -> dict[str, Any]:
        """Return the canonical review-queue representation."""

        return {
            "resourceName": self.resource_name,
            "status": self.status,
            "previousManifestId": self.previous_manifest_id,
            "currentManifestId": self.current_manifest_id,
            "previousLocalRecordIdSetDigest": self.previous_local_record_id_set_digest,
            "currentLocalRecordIdSetDigest": self.current_local_record_id_set_digest,
            "previousLocalRecordContentSetDigest": self.previous_local_record_content_set_digest,
            "currentLocalRecordContentSetDigest": self.current_local_record_content_set_digest,
            "autoMatchedCount": self.auto_matched_count,
            "addedRecords": [dict(value) for value in self.added_records],
            "removedRecords": [dict(value) for value in self.removed_records],
            "changedRecords": [dict(value) for value in self.changed_records],
            "matchSuggestions": [dict(value) for value in self.match_suggestions],
            "requiresHumanReview": self.requires_human_review,
            "changeDigest": self.change_digest,
            "review": None if self.review is None else dict(self.review),
        }


@dataclass(frozen=True, slots=True)
class CRSSchemeAuthorityPin:
    """Pinned packaged bytes for one LoC subject-scheme authority record."""

    scheme: CRSSourceScheme
    retrieved_at: str
    fetch_id: str
    expected_sha256: str
    expected_byte_length: int
    packaged_filename: str

    def __post_init__(self) -> None:
        if not self.expected_sha256.startswith("sha256:") or len(self.expected_sha256) != 71:
            raise CRSSourceDriftError("LoC scheme authority pin must contain a SHA-256 digest")
        if self.expected_byte_length <= 0:
            raise CRSSourceDriftError("LoC scheme authority pin byte length must be positive")
        try:
            SourceCaptureEvent(fetch_id=self.fetch_id, fetched_at=self.retrieved_at)
        except SourceIdentityError as error:
            raise CRSSourceDriftError(f"LoC scheme authority fetch event is invalid: {error}") from error
        if Path(self.packaged_filename).name != self.packaged_filename:
            raise CRSSourceDriftError("LoC scheme authority packaged filename must be one path component")


@dataclass(frozen=True, slots=True)
class CRSSchemeAuthorityCapture:
    """One verified LoC scheme record and its exact response bytes."""

    pin: CRSSchemeAuthorityPin
    payload: bytes

    @property
    def source_artifact(self) -> str:
        """Return the official authority-record URL used as the artifact ID."""

        return self.pin.scheme.authority_record_url

    def manifest_descriptor(self) -> dict[str, str]:
        """Describe the scheme identity without promoting its terms."""

        return {
            "id": self.pin.scheme.scheme_iri,
            "code": self.pin.scheme.code,
            "label": self.pin.scheme.label,
            "sourceArtifact": self.source_artifact,
            "sourceFetchId": self.pin.fetch_id,
            "sourceObservedAt": self.pin.retrieved_at,
        }


CRS_LEGISLATIVE_SUBJECT_TERMS_SCHEME_AUTHORITY_PIN = CRSSchemeAuthorityPin(
    scheme=CRS_LEGISLATIVE_SUBJECT_TERMS_SCHEME,
    retrieved_at=CRS_SCHEME_AUTHORITY_CAPTURED_AT,
    fetch_id="019fc9f2-c758-728f-8dbb-232379d1c9a3",
    expected_sha256="sha256:f4765c3cf7ab685e1cc05ba0f0b71ae288a5433bda29a801be3ca62a25be36f3",
    expected_byte_length=3_153,
    packaged_filename="lst.json.base64",
)
CRS_POLICY_AREAS_SCHEME_AUTHORITY_PIN = CRSSchemeAuthorityPin(
    scheme=CRS_POLICY_AREAS_SCHEME,
    retrieved_at=CRS_SCHEME_AUTHORITY_CAPTURED_AT,
    fetch_id="019fc9f2-c758-7bc2-903d-3b5365220f26",
    expected_sha256="sha256:3b91e326475799c99ed24b6bf7eb692efb0196812b9c9af99606f0b41ac03286",
    expected_byte_length=3_127,
    packaged_filename="cgpa.json.base64",
)
CRS_SCHEME_AUTHORITY_PINS = (
    CRS_LEGISLATIVE_SUBJECT_TERMS_SCHEME_AUTHORITY_PIN,
    CRS_POLICY_AREAS_SCHEME_AUTHORITY_PIN,
)

CRS_LEGISLATIVE_SUBJECTS_PIN = CRSPageSnapshotPin(
    source=CRS_LEGISLATIVE_SUBJECTS_PAGE,
    retrieved_at="2026-07-30T13:00:42Z",
    fetch_id="019fb31c-e090-7efa-9b11-86ab9b9dca0f",
    expected_sha256=("sha256:8b4964a8cea53d63bce0a029bac38a2bc260059883120bc36e1759a4b5e844d1"),
    expected_byte_length=410_454,
)
CRS_LEGISLATIVE_GEOGRAPHIC_PIN = CRSPageSnapshotPin(
    source=CRS_LEGISLATIVE_GEOGRAPHIC_PAGE,
    retrieved_at="2026-07-30T13:01:19Z",
    fetch_id="019fb31d-7118-7813-a9c6-36e67075b615",
    expected_sha256=("sha256:7dfefc6e8b17b3a86a9c9009453e792453eef01b099177ef29f4dc172d19d3d0"),
    expected_byte_length=384_627,
)
CRS_LEGISLATIVE_ORGANIZATIONS_PIN = CRSPageSnapshotPin(
    source=CRS_LEGISLATIVE_ORGANIZATIONS_PAGE,
    retrieved_at="2026-07-30T13:01:21Z",
    fetch_id="019fb31d-78e8-77b7-94d4-70bc21b6fe12",
    expected_sha256=("sha256:fa870ff36352c3482a68aad4d9cff69bd8ff98294a7dd21b1e36f0a534b2b880"),
    expected_byte_length=381_186,
)
CRS_POLICY_AREAS_PIN = CRSPageSnapshotPin(
    source=CRS_POLICY_AREAS_PAGE,
    retrieved_at="2026-07-30T13:01:22Z",
    fetch_id="019fb31d-7cd0-71a4-a23c-d3a206d345f7",
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

_MADS_AUTHORITY = "http://www.loc.gov/mads/rdf/v1#Authority"
_SKOS_CONCEPT = "http://www.w3.org/2004/02/skos/core#Concept"
_MADS_CODE = "http://www.loc.gov/mads/rdf/v1#code"
_MADS_LABEL = "http://www.loc.gov/mads/rdf/v1#authoritativeLabel"
_MADS_EDITORIAL_NOTE = "http://www.loc.gov/mads/rdf/v1#editorialNote"


def _json_ld_values(
    record: Mapping[str, Any],
    predicate: str,
    value_key: str,
) -> tuple[str, ...]:
    raw = record.get(predicate)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    return tuple(
        value[value_key] for value in raw if isinstance(value, Mapping) and isinstance(value.get(value_key), str)
    )


def _parse_scheme_authority_capture(
    pin: CRSSchemeAuthorityPin,
    payload: bytes,
) -> CRSSchemeAuthorityCapture:
    if len(payload) != pin.expected_byte_length or sha256_digest(payload) != pin.expected_sha256:
        raise CRSSourceDriftError(f"LoC {pin.scheme.code} scheme authority record failed its exact byte pin")
    try:
        root = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CRSSourceDriftError(f"LoC {pin.scheme.code} scheme authority record is not valid JSON") from error
    if not isinstance(root, list):
        raise CRSSourceDriftError(f"LoC {pin.scheme.code} scheme authority record must be a JSON-LD array")
    records = [value for value in root if isinstance(value, Mapping) and value.get("@id") == pin.scheme.scheme_iri]
    if len(records) != 1:
        raise CRSSourceDriftError(f"LoC {pin.scheme.code} scheme authority record lacks one canonical identity")
    record = records[0]
    record_types = record.get("@type")
    if (
        not isinstance(record_types, Sequence)
        or isinstance(record_types, (str, bytes))
        or not {_MADS_AUTHORITY, _SKOS_CONCEPT}.issubset(record_types)
    ):
        raise CRSSourceDriftError(f"LoC {pin.scheme.code} scheme authority record has unexpected types")
    if pin.scheme.code not in _json_ld_values(record, _MADS_CODE, "@value"):
        raise CRSSourceDriftError(f"LoC {pin.scheme.code} scheme authority record lacks its code")
    if pin.scheme.label not in _json_ld_values(record, _MADS_LABEL, "@value"):
        raise CRSSourceDriftError(f"LoC {pin.scheme.code} scheme authority record lacks its label")
    if pin.scheme.publisher_page_url not in _json_ld_values(record, _MADS_EDITORIAL_NOTE, "@id"):
        raise CRSSourceDriftError(f"LoC {pin.scheme.code} scheme authority record lacks its Congress.gov link")
    return CRSSchemeAuthorityCapture(pin=pin, payload=payload)


def load_packaged_crs_scheme_authorities() -> tuple[CRSSchemeAuthorityCapture, ...]:
    """Load and verify the two checked-in LoC authority records."""

    resource_root = (
        importlib.resources.files("refspec").joinpath("resources").joinpath("crs_source_schemes").joinpath("2026-08-03")
    )
    captures: list[CRSSchemeAuthorityCapture] = []
    for pin in CRS_SCHEME_AUTHORITY_PINS:
        try:
            encoded = resource_root.joinpath(pin.packaged_filename).read_text(encoding="ascii").strip()
            payload = base64.b64decode(encoded, validate=True)
        except (OSError, UnicodeDecodeError, UnicodeEncodeError, binascii.Error) as error:
            raise CRSSourceDriftError(
                f"packaged LoC {pin.scheme.code} scheme authority capture is unreadable"
            ) from error
        captures.append(_parse_scheme_authority_capture(pin, payload))
    return tuple(captures)


@dataclass(frozen=True, slots=True)
class CRSSourcePackages:
    """The separate detailed-term and broad-navigation packages."""

    legislative_subject_terms: SourceControlledResourceBundle
    policy_areas: SourceControlledResourceBundle
    reconciliations: tuple[CRSResourceReconciliation, ...]

    def resources(self) -> tuple[SourceControlledResourceBundle, ...]:
        """Return both packages in their stable product order."""

        return (self.legislative_subject_terms, self.policy_areas)

    def require_reconciled(self) -> None:
        """Stop promotion when a changed capture still needs human review."""

        pending = [report.resource_name for report in self.reconciliations if report.requires_human_review]
        if pending:
            raise CRSIdentityError(
                "human identity review is required for changed CRS capture(s): " + ", ".join(pending)
            )

    def _ledger_payload(self) -> dict[str, Any]:
        resources = {
            "legislativeSubjectTerms": {
                "path": "legislative-subject-terms",
                "manifestId": self.legislative_subject_terms.resource_manifest["id"],
                "logicalDigest": self.legislative_subject_terms.logical_digest,
            },
            "policyAreas": {
                "path": "policy-areas",
                "manifestId": self.policy_areas.resource_manifest["id"],
                "logicalDigest": self.policy_areas.logical_digest,
            },
        }
        payload = plain_json(
            {
                "format": "refspec-crs-source-ledger/v1",
                "registrationEvent": self.legislative_subject_terms.resource_manifest["registrationEvent"],
                "resources": resources,
                "reconciliations": [report.as_dict() for report in self.reconciliations],
            }
        )
        return {
            **payload,
            "logicalDigest": "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(),
        }

    def write_to(self, path: Path) -> Path:
        """Write one immutable capture ledger containing both packages and review state."""

        destination = Path(path)
        if destination.exists() or destination.is_symlink():
            raise CRSIdentityError(f"CRS ledger destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
        try:
            self.legislative_subject_terms.write_to(temporary / "legislative-subject-terms")
            self.policy_areas.write_to(temporary / "policy-areas")
            (temporary / "ledger.json").write_text(
                canonical_json(self._ledger_payload()) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, destination)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return destination

    @classmethod
    def open(cls, path: Path) -> CRSSourcePackages:
        """Reopen a complete ledger after verifying both packages and the review record."""

        root = Path(path)
        if root.is_symlink() or not root.is_dir():
            raise CRSIdentityError(f"CRS ledger path is not a regular directory: {root}")
        expected_entries = {"ledger.json", "legislative-subject-terms", "policy-areas"}
        entries = {item.name for item in root.iterdir()}
        if entries != expected_entries or any(item.is_symlink() for item in root.iterdir()):
            raise CRSIdentityError("CRS ledger file set is incomplete or contains an unsafe entry")
        ledger_path = root / "ledger.json"
        try:
            payload = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CRSIdentityError("CRS ledger.json is not valid UTF-8 JSON") from error
        if not isinstance(payload, Mapping) or set(payload) != {
            "format",
            "registrationEvent",
            "resources",
            "reconciliations",
            "logicalDigest",
        }:
            raise CRSIdentityError("CRS ledger shape is unsupported")
        if payload["format"] != "refspec-crs-source-ledger/v1":
            raise CRSIdentityError("CRS ledger format is unsupported")
        basis = {key: value for key, value in payload.items() if key != "logicalDigest"}
        expected_digest = "sha256:" + hashlib.sha256(canonical_json(basis).encode("utf-8")).hexdigest()
        if payload["logicalDigest"] != expected_digest:
            raise CRSIdentityError("CRS ledger logicalDigest is stale")
        if ledger_path.read_text(encoding="utf-8") != canonical_json(dict(payload)) + "\n":
            raise CRSIdentityError("CRS ledger.json is not canonical")

        resources = payload["resources"]
        if not isinstance(resources, Mapping) or set(resources) != {"legislativeSubjectTerms", "policyAreas"}:
            raise CRSIdentityError("CRS ledger must contain the two separate resources")
        opened: dict[str, SourceControlledResourceBundle] = {}
        expected_paths = {
            "legislativeSubjectTerms": "legislative-subject-terms",
            "policyAreas": "policy-areas",
        }
        for resource_name, relative_path in expected_paths.items():
            descriptor = resources[resource_name]
            if not isinstance(descriptor, Mapping) or set(descriptor) != {"path", "manifestId", "logicalDigest"}:
                raise CRSIdentityError(f"CRS ledger {resource_name} descriptor is unsupported")
            if descriptor["path"] != relative_path:
                raise CRSIdentityError(f"CRS ledger {resource_name} path is unsupported")
            view = SourceControlledResourceView.open(root / relative_path)
            if (
                descriptor["manifestId"] != view.resource_manifest["id"]
                or descriptor["logicalDigest"] != view.logical_digest
            ):
                raise CRSIdentityError(f"CRS ledger {resource_name} package identity drifted")
            opened[resource_name] = SourceControlledResourceBundle(
                resource_manifest=view.resource_manifest,
                coverage_report=view.coverage_report,
                observations=view.observations,
                source_artifacts=view.source_artifacts,
            )

        reconciliation_rows = payload["reconciliations"]
        if not isinstance(reconciliation_rows, Sequence) or isinstance(reconciliation_rows, (str, bytes)):
            raise CRSIdentityError("CRS ledger reconciliations must be an array")
        if not all(isinstance(row, Mapping) for row in reconciliation_rows):
            raise CRSIdentityError("CRS ledger reconciliation contains a non-object")
        reconciliations = tuple(CRSResourceReconciliation.from_dict(row) for row in reconciliation_rows)
        by_resource = {report.resource_name: report for report in reconciliations}
        if set(by_resource) != {"legislativeSubjectTerms", "policyAreas"} or len(reconciliations) != 2:
            raise CRSIdentityError("CRS ledger must contain one reconciliation per resource")
        for resource_name, package in opened.items():
            if by_resource[resource_name].current_manifest_id != package.resource_manifest["id"]:
                raise CRSIdentityError(f"CRS ledger {resource_name} reconciliation names the wrong package")
        registration_event = payload["registrationEvent"]
        if any(package.resource_manifest["registrationEvent"] != registration_event for package in opened.values()):
            raise CRSIdentityError("CRS ledger package registration events disagree")
        return cls(
            legislative_subject_terms=opened["legislativeSubjectTerms"],
            policy_areas=opened["policyAreas"],
            reconciliations=reconciliations,
        )


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


def _preferred_label(observation: Mapping[str, Any]) -> str:
    labels = observation.get("labels")
    if not isinstance(labels, Sequence) or isinstance(labels, (str, bytes)):
        raise CRSSourceDriftError("CRS predecessor observation lacks labels")
    preferred = [
        value.get("value") for value in labels if isinstance(value, Mapping) and value.get("role") == "preferred"
    ]
    if len(preferred) != 1 or not isinstance(preferred[0], str):
        raise CRSSourceDriftError("CRS predecessor observation lacks one preferred label")
    return preferred[0]


def _local_record_id(
    term: CRSControlledTerm,
    registration_event: SourceRegistrationEvent,
) -> str:
    source_key = canonical_json(
        {
            "resourceName": term.resource_name,
            "category": term.category,
            "captureObservation": term.record_iri,
        }
    )
    return registration_event.derived_record_urn(
        purpose="crs-local-record",
        source_key=source_key,
    )


def _term_identifier_keys(term: CRSControlledTerm) -> frozenset[tuple[str, str, str]]:
    return frozenset((identifier.kind, identifier.authority_uri, identifier.value) for identifier in term.identifiers)


def _observation_identifier_keys(observation: Mapping[str, Any]) -> frozenset[tuple[str, str, str]]:
    identifiers = observation.get("identifiers")
    if not isinstance(identifiers, Sequence) or isinstance(identifiers, (str, bytes)):
        raise CRSSourceDriftError("CRS predecessor observation lacks an identifier array")
    result: set[tuple[str, str, str]] = set()
    for identifier in identifiers:
        if not isinstance(identifier, Mapping):
            raise CRSSourceDriftError("CRS predecessor observation has a malformed identifier")
        kind = identifier.get("kind")
        authority_uri = identifier.get("authorityUri")
        value = identifier.get("value")
        if not all(isinstance(part, str) and part for part in (kind, authority_uri, value)):
            raise CRSSourceDriftError("CRS predecessor observation has an incomplete identifier")
        result.add((str(kind), str(authority_uri), str(value)))
    return frozenset(result)


def _assign_local_record_ids(
    resource: ParsedCRSResource,
    registration_event: SourceRegistrationEvent,
    predecessor: SourceControlledResourceBundle | None,
) -> tuple[dict[str, str], int]:
    """Reuse unique publisher IDs first, then unique exact category/label matches."""

    assigned = {term.record_iri: _local_record_id(term, registration_event) for term in resource.terms}
    if predecessor is None:
        return assigned, 0
    if predecessor.resource_manifest.get("sourceScheme", {}).get("id") != resource.source_scheme.scheme_iri:
        raise CRSSourceDriftError("CRS predecessor source scheme does not match the current resource")
    if "localRecordIdSetDigest" not in predecessor.coverage_report:
        raise CRSSourceDriftError("CRS predecessor predates the local identity ledger")

    previous_rows: list[Mapping[str, Any]] = []
    for row in predecessor.observations:
        category = row.get("category")
        local_record_id = row.get("localRecordId")
        if not isinstance(category, str) or not isinstance(local_record_id, str):
            raise CRSSourceDriftError("CRS predecessor has an incomplete local identity row")
        previous_rows.append(row)

    current_by_identifier: dict[tuple[str, str, str], list[CRSControlledTerm]] = {}
    for term in resource.terms:
        for key in _term_identifier_keys(term):
            current_by_identifier.setdefault(key, []).append(term)
    previous_by_identifier: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in previous_rows:
        for key in _observation_identifier_keys(row):
            previous_by_identifier.setdefault(key, []).append(row)

    candidate_previous_by_current: dict[str, set[str]] = {}
    for key in current_by_identifier.keys() & previous_by_identifier.keys():
        current_matches = current_by_identifier[key]
        previous_matches = previous_by_identifier[key]
        if len(current_matches) == 1 and len(previous_matches) == 1:
            candidate_previous_by_current.setdefault(current_matches[0].record_iri, set()).add(
                str(previous_matches[0]["localRecordId"])
            )
    nominated_by_previous: dict[str, list[str]] = {}
    for current_id, previous_ids in candidate_previous_by_current.items():
        if len(previous_ids) == 1:
            nominated_by_previous.setdefault(next(iter(previous_ids)), []).append(current_id)

    matched_current: set[str] = set()
    matched_previous: set[str] = set()
    auto_matched = 0
    for previous_id, current_ids in nominated_by_previous.items():
        if len(current_ids) != 1:
            continue
        current_id = current_ids[0]
        assigned[current_id] = previous_id
        matched_current.add(current_id)
        matched_previous.add(previous_id)
        auto_matched += 1

    current_by_key: dict[tuple[str, str], list[CRSControlledTerm]] = {}
    for term in resource.terms:
        if term.record_iri not in matched_current:
            current_by_key.setdefault((term.category, term.official_label), []).append(term)
    previous_by_key: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in previous_rows:
        if str(row["localRecordId"]) not in matched_previous:
            previous_by_key.setdefault((str(row["category"]), _preferred_label(row)), []).append(row)
    for key in current_by_key.keys() & previous_by_key.keys():
        current_matches = current_by_key[key]
        previous_matches = previous_by_key[key]
        if len(current_matches) != 1 or len(previous_matches) != 1:
            continue
        assigned[current_matches[0].record_iri] = str(previous_matches[0]["localRecordId"])
        auto_matched += 1
    return assigned, auto_matched


def _observation(
    term: CRSControlledTerm,
    page: AcquiredCRSPage,
    *,
    local_record_id: str,
    eligible_uses: tuple[str, ...],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": term.record_iri,
        "localRecordId": local_record_id,
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
        "identifiers": [
            {
                "value": identifier.value,
                "kind": identifier.kind,
                "authorityUri": identifier.authority_uri,
                "sourceUri": identifier.source_uri,
                "sourcePath": f"fieldValues/{term.category}[{term.source_ordinal}]/identifiers[{index}]",
                "observedAt": identifier.observed_at or page.pin.retrieved_at,
                "sourceDigest": identifier.source_digest or page.sha256,
                **({"effectiveFrom": identifier.effective_at} if identifier.effective_at is not None else {}),
            }
            for index, identifier in enumerate(term.identifiers)
        ],
        "uses": list(eligible_uses),
        "conceptIdentityClaimed": False,
        "resourceName": term.resource_name,
        "category": term.category,
        "sourceUrl": term.source_url,
        "sourceFetchId": page.pin.fetch_id,
        "sourceObservedAt": page.pin.retrieved_at,
        "identityStatus": term.identity_status,
        "publisherReleaseStatus": "namedReleaseAbsent",
    }
    if term.definition is not None:
        row["definition"] = term.definition
    return row


def _identity_fact(observation: Mapping[str, Any]) -> dict[str, Any]:
    return capture_independent_observation(observation)


def _change_summary(observation: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "localRecordId": observation["localRecordId"],
        "observationId": observation["id"],
        "category": observation["category"],
        "label": _preferred_label(observation),
    }
    if "definition" in observation:
        result["definition"] = observation["definition"]
    return result


def _normalized_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join("".join(character if character.isalnum() else " " for character in normalized).split())


def _match_suggestions(
    added: Sequence[Mapping[str, Any]],
    removed: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    suggestions: list[dict[str, Any]] = []
    for current in added:
        current_label = str(current["label"])
        current_definition = current.get("definition")
        candidates: list[tuple[float, str, Mapping[str, Any]]] = []
        for previous in removed:
            if current["category"] != previous["category"]:
                continue
            previous_label = str(previous["label"])
            normalized_equal = _normalized_label(current_label) == _normalized_label(previous_label)
            definition_equal = bool(current_definition and current_definition == previous.get("definition"))
            similarity = difflib.SequenceMatcher(
                None,
                _normalized_label(current_label),
                _normalized_label(previous_label),
            ).ratio()
            if normalized_equal:
                candidates.append((1.0, "normalizedLabel", previous))
            elif definition_equal:
                candidates.append((0.99, "unchangedDefinition", previous))
            elif similarity >= 0.80:
                candidates.append((similarity, "labelSimilarity", previous))
        if not candidates:
            continue
        score, basis, previous = max(
            candidates,
            key=lambda candidate: (candidate[0], str(candidate[2]["localRecordId"])),
        )
        suggestions.append(
            {
                "currentObservationId": current["observationId"],
                "currentLocalRecordId": current["localRecordId"],
                "currentLabel": current_label,
                "previousLocalRecordId": previous["localRecordId"],
                "previousLabel": previous["label"],
                "basis": basis,
                "score": round(score, 6),
                "decision": "humanReviewRequired",
            }
        )
    return tuple(sorted(suggestions, key=lambda value: str(value["currentObservationId"])))


def _reconciliation_report(
    *,
    resource_name: str,
    predecessor: SourceControlledResourceBundle | None,
    current: SourceControlledResourceBundle,
    auto_matched_count: int,
) -> CRSResourceReconciliation:
    current_by_id = {str(row["localRecordId"]): row for row in current.observations}
    previous_by_id = {} if predecessor is None else {str(row["localRecordId"]): row for row in predecessor.observations}
    added = (
        ()
        if predecessor is None
        else tuple(
            _change_summary(current_by_id[local_id])
            for local_id in sorted(current_by_id.keys() - previous_by_id.keys())
        )
    )
    removed = tuple(
        _change_summary(previous_by_id[local_id]) for local_id in sorted(previous_by_id.keys() - current_by_id.keys())
    )
    changed: list[dict[str, Any]] = []
    for local_id in sorted(current_by_id.keys() & previous_by_id.keys()):
        before = _identity_fact(previous_by_id[local_id])
        after = _identity_fact(current_by_id[local_id])
        if before == after:
            continue
        changed_fields = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
        changed.append(
            {
                "localRecordId": local_id,
                "before": before,
                "after": after,
                "changedFields": changed_fields,
            }
        )
    suggestions = _match_suggestions(added, removed)
    content_digest_changed = (
        predecessor is not None
        and predecessor.coverage_report["localRecordContentSetDigest"]
        != current.coverage_report["localRecordContentSetDigest"]
    )
    described_change = bool(added or removed or changed)
    if content_digest_changed != described_change:
        raise CRSSourceDriftError("CRS content digest and reconciliation details disagree")
    requires_review = content_digest_changed
    if predecessor is None:
        status: CRSReconciliationStatus = "initial"
    elif requires_review:
        status = "reviewRequired"
    elif predecessor.resource_manifest["sourceArtifacts"] == current.resource_manifest["sourceArtifacts"]:
        status = "unchanged"
    else:
        status = "sourceOnlyChange"
    change_basis = {
        "resourceName": resource_name,
        "previousManifestId": (None if predecessor is None else predecessor.resource_manifest["id"]),
        "currentManifestId": current.resource_manifest["id"],
        "previousLocalRecordIdSetDigest": (
            None if predecessor is None else predecessor.coverage_report["localRecordIdSetDigest"]
        ),
        "currentLocalRecordIdSetDigest": current.coverage_report["localRecordIdSetDigest"],
        "previousLocalRecordContentSetDigest": (
            None if predecessor is None else predecessor.coverage_report["localRecordContentSetDigest"]
        ),
        "currentLocalRecordContentSetDigest": current.coverage_report["localRecordContentSetDigest"],
        "addedRecords": list(added),
        "removedRecords": list(removed),
        "changedRecords": changed,
        "matchSuggestions": list(suggestions),
    }
    change_digest = "sha256:" + hashlib.sha256(canonical_json(change_basis).encode("utf-8")).hexdigest()
    return CRSResourceReconciliation(
        resource_name=resource_name,
        status=status,
        previous_manifest_id=(None if predecessor is None else str(predecessor.resource_manifest["id"])),
        current_manifest_id=str(current.resource_manifest["id"]),
        previous_local_record_id_set_digest=(
            None if predecessor is None else str(predecessor.coverage_report["localRecordIdSetDigest"])
        ),
        current_local_record_id_set_digest=str(current.coverage_report["localRecordIdSetDigest"]),
        previous_local_record_content_set_digest=(
            None if predecessor is None else str(predecessor.coverage_report["localRecordContentSetDigest"])
        ),
        current_local_record_content_set_digest=str(current.coverage_report["localRecordContentSetDigest"]),
        auto_matched_count=auto_matched_count,
        added_records=added,
        removed_records=removed,
        changed_records=tuple(changed),
        match_suggestions=suggestions,
        requires_human_review=requires_review,
        change_digest=change_digest,
    )


def _apply_identity_review(
    *,
    predecessor: SourceControlledResourceBundle,
    current: SourceControlledResourceBundle,
    pending: CRSResourceReconciliation,
    review: CRSIdentityReview,
) -> tuple[SourceControlledResourceBundle, CRSResourceReconciliation]:
    if review.resource_name != pending.resource_name:
        raise CRSIdentityError("CRS identity review names the wrong resource")
    if review.proposal_change_digest != pending.change_digest:
        raise CRSIdentityError("CRS identity review does not match the proposed change digest")
    if not pending.requires_human_review:
        raise CRSIdentityError("CRS identity review was supplied for a change that needs no review")

    added_by_observation = {str(value["observationId"]): value for value in pending.added_records}
    removed_by_local_id = {str(value["localRecordId"]): value for value in pending.removed_records}
    replacements: dict[str, str] = {}
    for link in review.identity_links:
        current_row = added_by_observation.get(link.current_observation_id)
        previous_row = removed_by_local_id.get(link.previous_local_record_id)
        if current_row is None or previous_row is None:
            raise CRSIdentityError("CRS identity review links must connect a proposed addition to a proposed removal")
        if current_row["category"] != previous_row["category"]:
            raise CRSIdentityError("CRS identity review cannot link records from different categories")
        replacements[link.current_observation_id] = link.previous_local_record_id

    reviewed_observations = tuple(
        {
            **dict(observation),
            "localRecordId": replacements.get(
                str(observation["id"]),
                observation["localRecordId"],
            ),
        }
        for observation in current.observations
    )
    manifest = current.resource_manifest
    coverage = current.coverage_report
    rebuilt = build_source_controlled_resource_bundle(
        resource_id=str(manifest["resourceId"]),
        title=str(manifest["title"]),
        resource_kind=manifest["resourceKind"],
        identity_status=manifest["identityStatus"],
        uses=manifest["uses"],
        captured_at=str(manifest["capturedAt"]),
        observations=reviewed_observations,
        source_artifacts=current.source_artifacts,
        registration_event=manifest["registrationEvent"],
        source_scheme=manifest["sourceScheme"],
        source_observed_count=int(coverage["sourceObservedCount"]),
        excluded_count=int(coverage["excludedCount"]),
        failed_count=int(coverage["failedCount"]),
        gaps=coverage["gaps"],
    )
    final = _reconciliation_report(
        resource_name=pending.resource_name,
        predecessor=predecessor,
        current=rebuilt,
        auto_matched_count=pending.auto_matched_count,
    )
    return rebuilt, replace(
        final,
        status="reviewed",
        requires_human_review=False,
        change_digest=pending.change_digest,
        review=review.as_dict(),
    )


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
    scheme_capture: CRSSchemeAuthorityCapture,
    *,
    registration_event: SourceRegistrationEvent,
    predecessor: SourceControlledResourceBundle | None,
    resource_id: str,
    title: str,
    resource_kind: ResourceKind,
    uses: tuple[ResourceUse, ...],
    captured_at: str,
) -> tuple[SourceControlledResourceBundle, int]:
    if scheme_capture.pin.scheme != resource.source_scheme:
        raise CRSSourceDriftError("CRS package scheme authority does not match its parsed resource")
    acquired_by_category = {page.pin.source.term_category: page for page in acquired_pages}
    local_record_ids, auto_matched_count = _assign_local_record_ids(
        resource,
        registration_event,
        predecessor,
    )
    observations = tuple(
        _observation(
            term,
            acquired_by_category[term.category],
            local_record_id=local_record_ids[term.record_iri],
            eligible_uses=uses,
        )
        for term in resource.terms
    )
    source_artifacts = {_source_artifact_iri(page): _verified_source_bytes(page) for page in acquired_pages}
    source_artifacts[scheme_capture.source_artifact] = scheme_capture.payload
    return (
        build_source_controlled_resource_bundle(
            resource_id=resource_id,
            title=title,
            resource_kind=resource_kind,
            identity_status="captureLocalObservationsOnly",
            uses=uses,
            captured_at=captured_at,
            observations=observations,
            source_artifacts=source_artifacts,
            registration_event=registration_event.as_dict(),
            source_scheme=scheme_capture.manifest_descriptor(),
            source_observed_count=len(resource.terms),
            gaps=_resource_gaps(len(resource.terms)),
        ),
        auto_matched_count,
    )


def build_crs_source_packages(
    pages: Sequence[AcquiredCRSPage],
    *,
    captured_at: str,
    registration_event: SourceRegistrationEvent = CRS_REGISTRATION_EVENT,
    predecessor: CRSSourcePackages | None = None,
    identity_reviews: Sequence[CRSIdentityReview] = (),
) -> CRSSourcePackages:
    """Build two packages and reconcile local term identity with a predecessor."""

    if registration_event.registered_at != captured_at:
        raise CRSSourceDriftError("CRS registration event time must equal captured_at")

    ordered = _ordered_pages(tuple(pages))
    parsed = tuple(parse_crs_field_value_page(page) for page in ordered)
    legislative_resource = assemble_crs_legislative_subject_terms(parsed[:3])
    policy_resource = assemble_crs_policy_areas(parsed[3])
    scheme_captures = {capture.pin.scheme.resource_name: capture for capture in load_packaged_crs_scheme_authorities()}

    capture_date = captured_at[:10]
    legislative_predecessor = None if predecessor is None else predecessor.legislative_subject_terms
    policy_predecessor = None if predecessor is None else predecessor.policy_areas
    legislative_package, legislative_auto_matches = _build_resource_package(
        legislative_resource,
        ordered[:3],
        scheme_captures[legislative_resource.resource_name],
        registration_event=registration_event,
        predecessor=legislative_predecessor,
        resource_id=f"crs-legislative-subject-terms-capture-{capture_date}",
        title="CRS Legislative Subject Terms source observations",
        resource_kind="sourceTermSnapshot",
        uses=("sourceAssignedEvidence", "searchExpansion"),
        captured_at=captured_at,
    )
    policy_package, policy_auto_matches = _build_resource_package(
        policy_resource,
        ordered[3:],
        scheme_captures[policy_resource.resource_name],
        registration_event=registration_event,
        predecessor=policy_predecessor,
        resource_id=f"crs-policy-areas-capture-{capture_date}",
        title="CRS Policy Areas source observations",
        resource_kind="navigationList",
        uses=("sourceAssignedEvidence", "navigation"),
        captured_at=captured_at,
    )
    legislative_report = _reconciliation_report(
        resource_name="legislativeSubjectTerms",
        predecessor=legislative_predecessor,
        current=legislative_package,
        auto_matched_count=legislative_auto_matches,
    )
    policy_report = _reconciliation_report(
        resource_name="policyAreas",
        predecessor=policy_predecessor,
        current=policy_package,
        auto_matched_count=policy_auto_matches,
    )
    reviews_by_resource: dict[str, CRSIdentityReview] = {}
    for review in identity_reviews:
        if review.resource_name in reviews_by_resource:
            raise CRSIdentityError("only one CRS identity review may be applied per resource")
        reviews_by_resource[review.resource_name] = review
    if set(reviews_by_resource) - {"legislativeSubjectTerms", "policyAreas"}:
        raise CRSIdentityError("CRS identity review names an unsupported resource")
    if reviews_by_resource and predecessor is None:
        raise CRSIdentityError("CRS identity review requires a predecessor capture")
    if "legislativeSubjectTerms" in reviews_by_resource:
        assert legislative_predecessor is not None
        legislative_package, legislative_report = _apply_identity_review(
            predecessor=legislative_predecessor,
            current=legislative_package,
            pending=legislative_report,
            review=reviews_by_resource["legislativeSubjectTerms"],
        )
    if "policyAreas" in reviews_by_resource:
        assert policy_predecessor is not None
        policy_package, policy_report = _apply_identity_review(
            predecessor=policy_predecessor,
            current=policy_package,
            pending=policy_report,
            review=reviews_by_resource["policyAreas"],
        )
    return CRSSourcePackages(
        legislative_subject_terms=legislative_package,
        policy_areas=policy_package,
        reconciliations=(legislative_report, policy_report),
    )


def build_crs_source_packages_from_capture_root(
    capture_root: Path,
    *,
    captured_at: str = CRS_COMPLETE_CAPTURED_AT,
    registration_event: SourceRegistrationEvent = CRS_REGISTRATION_EVENT,
    predecessor: CRSSourcePackages | None = None,
    identity_reviews: Sequence[CRSIdentityReview] = (),
) -> CRSSourcePackages:
    """Reopen the four 2026-07-30 pages and add the pinned LoC scheme records."""

    acquired = tuple(acquire_crs_page(pin, Path(capture_root)) for pin in CRS_PAGE_SNAPSHOT_PINS)
    return build_crs_source_packages(
        acquired,
        captured_at=captured_at,
        registration_event=registration_event,
        predecessor=predecessor,
        identity_reviews=identity_reviews,
    )


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
            "fetchId": observation["sourceFetchId"],
            "retrievedAt": observation["sourceObservedAt"],
        }
        previous = by_source.setdefault(source_id, row)
        if previous != row:
            raise CRSSourceDriftError(f"source artifact {source_id!r} has inconsistent observation metadata")
    result: list[dict[str, Any]] = []
    scheme = package.resource_manifest["sourceScheme"]
    for descriptor in package.resource_manifest["sourceArtifacts"]:
        source_id = descriptor["id"]
        if source_id == scheme["sourceArtifact"]:
            metadata = {
                "id": source_id,
                "kind": "schemeAuthorityRecord",
                "sourceUrl": source_id,
                "fetchId": scheme["sourceFetchId"],
                "retrievedAt": scheme["sourceObservedAt"],
            }
        else:
            metadata = {
                **by_source[source_id],
                "kind": "termPage",
            }
        result.append(
            {
                **metadata,
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
    return plain_json(
        {
            "resourceId": package.resource_manifest["resourceId"],
            "resourceKind": package.resource_manifest["resourceKind"],
            "logicalDigest": package.logical_digest,
            "observationCount": len(package.observations),
            "observationSetDigest": package.coverage_report["observationSetDigest"],
            "localRecordIdSetDigest": package.coverage_report["localRecordIdSetDigest"],
            "localRecordContentSetDigest": package.coverage_report["localRecordContentSetDigest"],
            "categoryCounts": category_counts,
            "coverageStatus": package.coverage_report["reportStatus"],
            "coverageGaps": [gap["code"] for gap in package.coverage_report["gaps"]],
            "conceptIdentityClaimed": package.resource_manifest["conceptIdentityClaimed"],
            "uses": package.resource_manifest["uses"],
            "registrationEvent": package.resource_manifest["registrationEvent"],
            "sourceScheme": package.resource_manifest["sourceScheme"],
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
    )


def crs_source_package_evidence(
    packages: CRSSourcePackages,
) -> dict[str, Any]:
    """Summarize the exact package identities and their source limitations."""

    return plain_json(
        {
            "schemaVersion": CRS_PACKAGE_EVIDENCE_VERSION,
            "evidenceKind": "crsSourceControlledResourcePackages",
            "capturedAt": packages.legislative_subject_terms.resource_manifest["capturedAt"],
            "registrationEvent": packages.legislative_subject_terms.resource_manifest["registrationEvent"],
            "sourceLimitations": [
                "The LoC lst and cgpa identifiers name the two source schemes, not individual terms.",
                "Congress.gov did not expose stable publisher term identifiers or term IRIs.",
                "Congress.gov did not publish the captured pages as a named, versioned vocabulary release.",
                "RefSpec local record UUIDs identify registry records, not publisher concepts.",
            ],
            "resources": [_package_evidence(package) for package in packages.resources()],
            "reconciliations": [report.as_dict() for report in packages.reconciliations],
        }
    )


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
    "CRS_LEGISLATIVE_SUBJECT_TERMS_SCHEME_AUTHORITY_PIN",
    "CRS_PACKAGE_DATE",
    "CRS_PACKAGE_EVIDENCE_VERSION",
    "CRS_PAGE_SNAPSHOT_PINS",
    "CRS_POLICY_AREAS_PIN",
    "CRS_POLICY_AREAS_RESOURCE_ID",
    "CRS_POLICY_AREAS_SCHEME_AUTHORITY_PIN",
    "CRS_REGISTRATION_EVENT",
    "CRS_REGISTRATION_ID",
    "CRS_SCHEME_AUTHORITY_CAPTURED_AT",
    "CRS_SCHEME_AUTHORITY_PINS",
    "CRSIdentityLink",
    "CRSIdentityReview",
    "CRSResourceReconciliation",
    "CRSSchemeAuthorityCapture",
    "CRSSchemeAuthorityPin",
    "CRSSourcePackages",
    "build_crs_source_packages",
    "build_crs_source_packages_from_capture_root",
    "crs_source_package_evidence",
    "crs_source_package_evidence_bytes",
    "load_packaged_crs_scheme_authorities",
]
