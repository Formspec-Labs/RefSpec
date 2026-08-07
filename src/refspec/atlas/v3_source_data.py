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
from datetime import date
from pathlib import Path
from typing import Any, Literal

LabelRole = Literal["preferred", "alternate", "hidden"]
MappingReviewMethod = Literal["operatorAdoption", "publisherAssertion"]
ReleaseScope = Literal["publisherRelease", "completeCapture", "captureSubset"]

LABEL_ROLES = frozenset({"preferred", "alternate", "hidden"})
MAPPING_REVIEW_METHODS = frozenset({"operatorAdoption", "publisherAssertion"})
RELEASE_SCOPES = frozenset(
    {"publisherRelease", "completeCapture", "captureSubset"}
)
SEMANTIC_RINGS = frozenset({"subject", "entity", "value", "legalIdentity"})
RESOURCE_PROFILES = frozenset(
    {"conceptScheme", "codeScheme", "identifierScheme", "structureScheme"}
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:\S+$")


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    """Return the stable digest used for normalized release identities."""

    return "sha256:" + hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


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
        if not self.path.is_file() or self.path.is_symlink():
            raise ValueError(f"registry input is missing or unsafe: {self.logical_path}")
        observed_size = self.path.stat().st_size
        digest = hashlib.sha256()
        with self.path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        observed = "sha256:" + digest.hexdigest()
        if observed_size != self.byte_length or observed != self.sha256:
            raise ValueError(
                f"registry input pin differs for {self.logical_path}: "
                f"expected=({self.byte_length}, {self.sha256}), "
                f"observed=({observed_size}, {observed})"
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
class RegistryPublisherMapping:
    """One direct publisher-authored mapping between loaded Atlas resources."""

    subject: str
    predicate: str
    object: str
    source_locator: str
    source_digest: str
    source_payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        for endpoint in (self.subject, self.predicate, self.object):
            if not endpoint or ":" not in endpoint:
                raise ValueError("publisher mapping terms must be absolute IRIs")
        if not self.source_locator or ":" not in self.source_locator:
            raise ValueError("publisher mapping source locator must be an absolute IRI")
        if not self.source_digest.startswith("sha256:"):
            raise ValueError("publisher mapping source digest must be SHA-256")


@dataclass(frozen=True, slots=True)
class RegistryMappingRelease:
    """A separately pinned publisher release whose members are mapping claims."""

    key: str
    resource_id: str
    source_module: str
    ring: str
    issued: str
    source_release_iri: str
    source_release_digest: str
    inputs: Sequence[RegistryInputPin]
    mappings: Sequence[RegistryPublisherMapping]
    decision_date: str
    review_method: MappingReviewMethod
    reviewer_iri: str
    confidence: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.resource_id or self.resource_id != self.resource_id.strip():
            raise ValueError(
                f"mapping release {self.key} has no canonical registry resource id"
            )
        if self.ring not in SEMANTIC_RINGS:
            raise ValueError(f"unsupported mapping semantic ring: {self.ring!r}")
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
        if self.review_method not in MAPPING_REVIEW_METHODS:
            raise ValueError(
                f"mapping release {self.key} has unsupported review method "
                f"{self.review_method!r}"
            )
        if not self.reviewer_iri or ":" not in self.reviewer_iri:
            raise ValueError(f"mapping release {self.key} reviewer is not an IRI")
        parsed_dates: dict[str, date] = {}
        for field_name, value in (
            ("issued", self.issued),
            ("decision_date", self.decision_date),
        ):
            try:
                parsed = date.fromisoformat(value)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"mapping release {self.key} {field_name} must be an ISO 8601 date"
                ) from error
            if parsed.isoformat() != value:
                raise ValueError(
                    f"mapping release {self.key} {field_name} must use canonical "
                    "YYYY-MM-DD"
                )
            parsed_dates[field_name] = parsed
        if parsed_dates["decision_date"] < parsed_dates["issued"]:
            raise ValueError(
                f"mapping release {self.key} decision date predates its release"
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
    "RELEASE_SCOPES",
    "RESOURCE_PROFILES",
    "SEMANTIC_RINGS",
    "LabelRole",
    "RegistryCrossRingRelation",
    "RegistryIdentifier",
    "RegistryInputPin",
    "RegistryLabel",
    "RegistryMappingRelease",
    "RegistryPublisherMapping",
    "RegistryRelation",
    "RegistryRelease",
    "RegistryResource",
    "ReleaseScope",
    "canonical_digest",
    "mapping_triple_digest",
]
