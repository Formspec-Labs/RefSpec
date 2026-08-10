"""Normalized source-native inputs for the Atlas 3 registry build.

Registry readers keep their publisher-specific models.  This module is the
small boundary they adapt to before the Atlas writer assigns RDF classes,
profiles, provenance records, and assertion identities.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from refspec.input_pin import verify_file_pin
from refspec.registry.infrastructure.semantic_foundation import SEMANTIC_RINGS
from refspec.registry.infrastructure.source_controlled_resource import (
    LABEL_ROLES,
    LabelRole,
)

MappingReviewMethod = Literal[
    "deterministicTransformation",
    "humanReview",
    "operatorAdoption",
    "publisherAssertion",
    "trustedPipelineReview",
    "twoMachineAdjudication",
]
ReleaseScope = Literal["publisherRelease", "completeCapture", "captureSubset"]

MAPPING_REVIEW_METHODS = frozenset(
    {
        "deterministicTransformation",
        "humanReview",
        "operatorAdoption",
        "publisherAssertion",
        "trustedPipelineReview",
        "twoMachineAdjudication",
    }
)
RELEASE_SCOPES = frozenset(
    {"publisherRelease", "completeCapture", "captureSubset"}
)
RESOURCE_PROFILES = frozenset(
    {"conceptScheme", "codeScheme", "identifierScheme", "structureScheme"}
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:\S+$")


def _canonical_json_bytes(value: Any) -> bytes:
    value = _json_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_json_value(item) for item in value]
    return value


def canonical_digest(value: Any) -> str:
    """Return the stable digest used for normalized release identities."""

    return "sha256:" + hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _canonical_aware_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a canonical ISO 8601 date-time")
    parse_value = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(parse_value)
    except ValueError as error:
        raise ValueError(
            f"{field_name} must be a canonical ISO 8601 date-time"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include an explicit timezone")
    canonical = parsed.isoformat()
    if value.endswith("Z"):
        if parsed.utcoffset().total_seconds() != 0:
            raise ValueError(f"{field_name} uses Z with a non-UTC value")
        canonical = canonical.removesuffix("+00:00") + "Z"
    if canonical != value:
        raise ValueError(f"{field_name} must use canonical ISO 8601 spelling")
    return parsed


def mapping_triple_digest(
    *,
    subject_iri: str,
    predicate_iri: str,
    object_iri: str,
) -> str:
    """Digest one mapping triple with the registry adapter's canonical profile."""

    return canonical_digest(
        {
            "object": object_iri,
            "predicate": predicate_iri,
            "subject": subject_iri,
        }
    )


@dataclass(frozen=True, slots=True)
class RegistryInputPin:
    """One exact source artifact consumed by a registry adapter."""

    path: Path
    logical_path: str
    sha256: str
    byte_length: int
    source_iri: str
    role: str = "publisherSource"

    def verify(self) -> None:
        verify_file_pin(
            self.path,
            expected_sha256=self.sha256,
            expected_byte_length=self.byte_length,
            logical_path=self.logical_path,
        )


@dataclass(frozen=True, slots=True)
class RegistryLabel:
    """One retained English SKOS-XL label with an explicit role."""

    value: str
    role: LabelRole
    source_path: str
    language: str = "en"

    def __post_init__(self) -> None:
        if self.role not in LABEL_ROLES:
            raise ValueError(f"unsupported registry label role: {self.role!r}")
        if self.language != "en":
            raise ValueError("Atlas registry labels must be normalized to English")
        if not self.value or self.value != self.value.strip():
            raise ValueError("Atlas registry labels must be non-empty trimmed text")
        if not self.source_path:
            raise ValueError("Atlas registry labels must retain a source path")


@dataclass(frozen=True, slots=True)
class RegistryIdentifier:
    """One authority-scoped identifier attached to a normalized resource."""

    value: str
    scheme_iri: str
    source_path: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("Atlas registry identifier values must be non-empty")
        if not self.scheme_iri or ":" not in self.scheme_iri:
            raise ValueError("Atlas registry identifier schemes must be absolute IRIs")
        if not self.source_path:
            raise ValueError("Atlas registry identifiers must retain a source path")


@dataclass(frozen=True, slots=True)
class RegistryResource:
    """One normalized Atlas member backed by an exact source record."""

    iri: str
    labels: Sequence[RegistryLabel]
    native_payload: Mapping[str, Any]
    source_locator: str
    source_digest: str
    definition: str | None = None
    notes: Sequence[str] = ()
    notations: Sequence[str] = ()
    status: str | None = None
    identifiers: Sequence[RegistryIdentifier] = ()

    def __post_init__(self) -> None:
        if not self.iri or ":" not in self.iri:
            raise ValueError("registry resource IRI must be absolute")
        if not self.labels:
            raise ValueError(f"registry resource {self.iri} has no English label")
        if sum(label.role == "preferred" for label in self.labels) > 1:
            raise ValueError(
                f"registry resource {self.iri} has more than one preferred label"
            )
        label_roles: dict[str, str] = {}
        label_claims: set[tuple[str, str]] = set()
        for label in self.labels:
            claim = (label.value, label.role)
            if claim in label_claims:
                raise ValueError(
                    f"registry resource {self.iri} repeats label claim {claim!r}"
                )
            label_claims.add(claim)
            previous_role = label_roles.setdefault(label.value, label.role)
            if previous_role != label.role:
                raise ValueError(
                    f"registry resource {self.iri} reuses label value "
                    f"{label.value!r} across roles"
                )
        if not self.source_locator or ":" not in self.source_locator:
            raise ValueError(f"registry resource {self.iri} has no absolute source locator")
        if not self.source_digest.startswith("sha256:"):
            raise ValueError(f"registry resource {self.iri} has no SHA-256 source digest")
        identifier_keys: set[tuple[str, str]] = set()
        for identifier in self.identifiers:
            key = (identifier.scheme_iri, identifier.value)
            if key in identifier_keys:
                raise ValueError(
                    f"registry resource {self.iri} repeats identifier {key!r}"
                )
            identifier_keys.add(key)


@dataclass(frozen=True, slots=True)
class RegistryRelation:
    """One direct publisher relation whose endpoints belong to one release."""

    subject: str
    predicate: str
    object: str
    source_payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RegistrySupplementalSourceRecord:
    """One exact source-evidence record retained beside normalized members."""

    source_record_id: str
    source_locator: str
    source_digest: str
    native_payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_record_id", self.source_record_id),
            ("source_locator", self.source_locator),
        ):
            if _ABSOLUTE_IRI.fullmatch(value) is None:
                raise ValueError(
                    f"supplemental source record {field_name} must be an absolute IRI"
                )
        if _SHA256.fullmatch(self.source_digest) is None:
            raise ValueError(
                "supplemental source record source_digest must be SHA-256"
            )
        if not isinstance(self.native_payload, Mapping):
            raise TypeError("supplemental source record native_payload must be an object")


@dataclass(frozen=True, slots=True)
class RegistryCrossRingRelation:
    """One direct publisher relation between resources in different rings."""

    subject: str
    predicate: str
    object: str
    source_ring: str
    target_ring: str
    source_payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.source_ring not in SEMANTIC_RINGS:
            raise ValueError(f"unsupported source semantic ring: {self.source_ring!r}")
        if self.target_ring not in SEMANTIC_RINGS:
            raise ValueError(f"unsupported target semantic ring: {self.target_ring!r}")
        if self.source_ring == self.target_ring:
            raise ValueError("cross-ring relations must name two different rings")
        for endpoint in (self.subject, self.predicate, self.object):
            if not endpoint or ":" not in endpoint:
                raise ValueError("cross-ring relation terms must be absolute IRIs")


@dataclass(frozen=True, slots=True)
class RegistryMappingEvidence:
    """One immutable approval and its exact source record for a mapping claim."""

    source_locator: str
    source_digest: str
    native_payload: Mapping[str, Any]
    review_method: MappingReviewMethod
    reviewer_iri: str
    decided_at: str

    def __post_init__(self) -> None:
        if (
            self.source_locator != self.source_locator.strip()
            or _ABSOLUTE_IRI.fullmatch(self.source_locator) is None
        ):
            raise ValueError("mapping evidence source locator must be an absolute IRI")
        if _SHA256.fullmatch(self.source_digest) is None:
            raise ValueError("mapping evidence source digest must be SHA-256")
        if not isinstance(self.native_payload, Mapping):
            raise TypeError("mapping evidence native payload must be an object")
        _canonical_json_bytes(self.native_payload)
        if self.review_method not in MAPPING_REVIEW_METHODS:
            raise ValueError(
                f"unsupported mapping evidence review method: {self.review_method!r}"
            )
        if (
            self.reviewer_iri != self.reviewer_iri.strip()
            or _ABSOLUTE_IRI.fullmatch(self.reviewer_iri) is None
        ):
            raise ValueError("mapping evidence reviewer must be an absolute IRI")
        _canonical_aware_datetime(
            self.decided_at,
            field_name="mapping evidence decided_at",
        )


@dataclass(frozen=True, slots=True)
class RegistryMapping:
    """One mapping claim over exact Atlas releases with one or more approvals."""

    subject: str
    predicate: str
    object: str
    subject_atlas_release_iri: str
    object_atlas_release_iri: str
    asserted_at: str
    evidence: Sequence[RegistryMappingEvidence]

    def __post_init__(self) -> None:
        for endpoint in (
            self.subject,
            self.predicate,
            self.object,
            self.subject_atlas_release_iri,
            self.object_atlas_release_iri,
        ):
            if (
                not isinstance(endpoint, str)
                or endpoint != endpoint.strip()
                or _ABSOLUTE_IRI.fullmatch(endpoint) is None
            ):
                raise ValueError("mapping terms and releases must be absolute IRIs")
        if self.subject_atlas_release_iri == self.object_atlas_release_iri:
            raise ValueError("mapping endpoints must use different Atlas releases")
        asserted_at = _canonical_aware_datetime(
            self.asserted_at,
            field_name="mapping asserted_at",
        )
        if not self.evidence:
            raise ValueError("mapping claim must have at least one evidence decision")
        if any(not isinstance(item, RegistryMappingEvidence) for item in self.evidence):
            raise TypeError("mapping evidence rows must be RegistryMappingEvidence")
        evidence_keys = [
            canonical_digest(
                {
                    "decidedAt": _canonical_aware_datetime(
                        item.decided_at,
                        field_name="mapping evidence decided_at",
                    )
                    .astimezone(timezone.utc)
                    .isoformat(),
                    "nativePayload": item.native_payload,
                    "reviewMethod": item.review_method,
                    "reviewedBy": item.reviewer_iri,
                    "sourceDigest": item.source_digest,
                    "sourceLocator": item.source_locator,
                }
            )
            for item in self.evidence
        ]
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("mapping claim repeats an evidence decision")
        if all(
            _canonical_aware_datetime(
                item.decided_at,
                field_name="mapping evidence decided_at",
            )
            > asserted_at
            for item in self.evidence
        ):
            raise ValueError(
                "mapping claim was asserted before every approving decision"
            )


@dataclass(frozen=True, slots=True)
class RegistryMappingRelease:
    """An exact pinned collection whose members are evidence-backed mappings."""

    key: str
    resource_id: str
    source_module: str
    ring: str
    scope: ReleaseScope
    issued: str
    source_release_iri: str
    source_release_digest: str
    inputs: Sequence[RegistryInputPin]
    mappings: Sequence[RegistryMapping]
    editorial_policy: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.resource_id or self.resource_id != self.resource_id.strip():
            raise ValueError(
                f"mapping release {self.key} has no canonical registry resource id"
            )
        if self.ring not in SEMANTIC_RINGS:
            raise ValueError(f"unsupported mapping semantic ring: {self.ring!r}")
        if self.scope not in RELEASE_SCOPES:
            raise ValueError(f"unsupported mapping release scope: {self.scope!r}")
        if not self.inputs:
            raise ValueError(f"mapping release {self.key} has no source inputs")
        if (
            self.source_release_iri != self.source_release_iri.strip()
            or _ABSOLUTE_IRI.fullmatch(self.source_release_iri) is None
        ):
            raise ValueError(
                f"mapping release {self.key} source release is not an absolute IRI"
            )
        if _SHA256.fullmatch(self.source_release_digest) is None:
            raise ValueError(
                f"mapping release {self.key} source release digest is not SHA-256"
            )
        if self.source_release_digest != self.inputs[0].sha256:
            raise ValueError(
                f"mapping release {self.key} source release digest differs from "
                "its primary mapping input"
            )
        if not self.mappings:
            raise ValueError(f"mapping release {self.key} has no mappings")
        if any(not isinstance(mapping, RegistryMapping) for mapping in self.mappings):
            raise TypeError(f"mapping release {self.key} contains a non-mapping row")
        claims = [
            (mapping.subject, mapping.predicate, mapping.object)
            for mapping in self.mappings
        ]
        if len(claims) != len(set(claims)):
            raise ValueError(f"mapping release {self.key} repeats a mapping claim")
        if not isinstance(self.editorial_policy, Mapping) or not self.editorial_policy:
            raise ValueError(
                f"mapping release {self.key} has no editorial policy payload"
            )
        _canonical_json_bytes(self.editorial_policy)
        try:
            parsed_issued = date.fromisoformat(self.issued)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"mapping release {self.key} issued must be an ISO 8601 date"
            ) from error
        if parsed_issued.isoformat() != self.issued:
            raise ValueError(
                f"mapping release {self.key} issued must use canonical YYYY-MM-DD"
            )
        issued_at = datetime(
            parsed_issued.year,
            parsed_issued.month,
            parsed_issued.day,
            tzinfo=timezone.utc,
        )
        for mapping in self.mappings:
            if (
                _canonical_aware_datetime(
                    mapping.asserted_at,
                    field_name=f"mapping release {self.key} asserted_at",
                ).astimezone(timezone.utc)
                < issued_at
            ):
                raise ValueError(
                    f"mapping release {self.key} assertion predates its release"
                )
            if any(
                _canonical_aware_datetime(
                    evidence.decided_at,
                    field_name=f"mapping release {self.key} decided_at",
                ).astimezone(timezone.utc)
                < issued_at
                for evidence in mapping.evidence
            ):
                raise ValueError(
                    f"mapping release {self.key} evidence decision predates its release"
                )

    def verify_inputs(self) -> None:
        for source in self.inputs:
            source.verify()


@dataclass(frozen=True, slots=True)
class RegistryRelease:
    """A complete declared publisher release or exact bounded capture."""

    key: str
    resource_id: str
    source_module: str
    profile: str
    ring: str
    scope: ReleaseScope
    issued: str
    source_release_iri: str
    source_release_digest: str
    atlas_release_iri: str
    scheme_iri: str
    inputs: Sequence[RegistryInputPin]
    resources: Sequence[RegistryResource]
    relations: Sequence[RegistryRelation] = ()
    cross_ring_relations: Sequence[RegistryCrossRingRelation] = ()
    supplemental_source_records: Sequence[RegistrySupplementalSourceRecord] = ()
    dropped_label_count: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.profile not in RESOURCE_PROFILES:
            raise ValueError(f"unsupported registry resource profile: {self.profile!r}")
        if self.ring not in SEMANTIC_RINGS:
            raise ValueError(f"unsupported Atlas semantic ring: {self.ring!r}")
        if self.scope not in RELEASE_SCOPES:
            raise ValueError(f"unsupported registry release scope: {self.scope!r}")
        if not self.inputs:
            raise ValueError(f"registry release {self.key} has no source inputs")
        if not self.resources:
            raise ValueError(f"registry release {self.key} has no members")
        if self.dropped_label_count < 0:
            raise ValueError("dropped label count must be non-negative")
        supplemental_keys = [
            (
                record.source_record_id,
                record.source_locator,
                record.source_digest,
            )
            for record in self.supplemental_source_records
        ]
        if len(set(supplemental_keys)) != len(supplemental_keys):
            raise ValueError(
                f"registry release {self.key} repeats a supplemental source record"
            )
        try:
            parsed_issued = date.fromisoformat(self.issued)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"registry release {self.key} issued must be an ISO 8601 date"
            ) from error
        if parsed_issued.isoformat() != self.issued:
            raise ValueError(
                f"registry release {self.key} issued must use canonical YYYY-MM-DD"
            )

    def verify_inputs(self) -> None:
        for source in self.inputs:
            source.verify()

    @property
    def expected_resources(self) -> int:
        return len(self.resources)

    @property
    def expected_relations(self) -> int:
        return len(self.relations)

    @property
    def expected_cross_ring_relations(self) -> int:
        return len(self.cross_ring_relations)


__all__ = [
    "LABEL_ROLES",
    "MAPPING_REVIEW_METHODS",
    "RELEASE_SCOPES",
    "RESOURCE_PROFILES",
    "SEMANTIC_RINGS",
    "LabelRole",
    "MappingReviewMethod",
    "RegistryCrossRingRelation",
    "RegistryIdentifier",
    "RegistryInputPin",
    "RegistryLabel",
    "RegistryMapping",
    "RegistryMappingEvidence",
    "RegistryMappingRelease",
    "RegistryRelation",
    "RegistryRelease",
    "RegistryResource",
    "RegistrySupplementalSourceRecord",
    "ReleaseScope",
    "canonical_digest",
    "mapping_triple_digest",
]
