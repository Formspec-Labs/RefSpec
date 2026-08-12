"""Exact concept releases shared by all semantic-ring products.

Source releases state their semantic ring directly. Managed Rulespec releases
need a separate reviewed ring assignment because their older publication shape
does not carry the four-ring classification. Both paths reopen exact bytes and
produce one discriminated pin. Admission, relation assertions, and later atlas
scope records consume this module instead of inventing product-specific release
identity.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self, TypeAlias, cast

from refspec.immutable import deep_freeze_json
from refspec.managed_release import ManagedReleaseGraphFactsView
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.semantic_foundation import (
    SEMANTIC_RINGS,
    RightsMetadata,
    SemanticFoundationError,
    SemanticRing,
    validate_rights_metadata_records,
)
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseBundle,
    SourceConceptReleaseError,
    SourceConceptReleaseView,
)
from refspec.registry.infrastructure.source_identity import (
    SourceIdentityError,
    require_aware_datetime_text,
)
from refspec.release_model import (
    ManagedReleaseError,
    reject_duplicate_keys,
    reject_nonfinite_constant,
    rulespec_graph_digest,
    validate_canonical_value,
)

MANAGED_RELEASE_RING_ASSIGNMENT_VERSION = "1.0"

_BUNDLE_MANIFEST_PATH = "bundle-manifest.json"
_LOCAL_CONCEPT_TYPES = frozenset(
    {
        "rkaf:LocalConcept",
        "https://rulespec.org/ns/v1#LocalConcept",
    }
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class ConceptReleaseError(ValueError):
    """An exact concept release or its planning classification is invalid."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise ConceptReleaseError(str(error)) from error
    return canonical_json_bytes(plain)


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ConceptReleaseError(f"{label} must be non-empty trimmed text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise ConceptReleaseError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise ConceptReleaseError(f"{label} must not contain credentials")
    return iri


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ConceptReleaseError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_ring(value: object, label: str) -> SemanticRing:
    if not isinstance(value, str) or value not in SEMANTIC_RINGS:
        raise ConceptReleaseError(
            f"{label} must be subject, entity, value, or legalIdentity"
        )
    return cast(SemanticRing, value)


def _require_datetime(value: object, label: str) -> str:
    text = _require_text(value, label)
    try:
        return require_aware_datetime_text(text, label=label)
    except SourceIdentityError as error:
        raise ConceptReleaseError(str(error)) from error


def _require_unique_iris(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise ConceptReleaseError(f"{label} must be a non-empty IRI array")
    result = tuple(
        _require_iri(item, f"{label}[{index}]") for index, item in enumerate(value)
    )
    if len(set(result)) != len(result):
        raise ConceptReleaseError(f"{label} must contain unique IRIs")
    return tuple(sorted(result))


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise ConceptReleaseError(
            f"{label} fields differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _read_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ConceptReleaseError(
            f"{label} must be valid canonical UTF-8 JSON"
        ) from error


def _managed_declared_release_digest(
    view: ManagedReleaseGraphFactsView,
    release_id: str,
) -> str:
    """Read the selected vocabulary identity from the verified Rulespec graph.

    The managed bundle manifest separately pins the exact distribution bytes.
    Operational serialization metadata can therefore change the distribution
    pin without changing the publisher-declared vocabulary release identity.
    """

    nodes = view.rulespec_graph.get("@graph")
    if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes)):
        raise ConceptReleaseError("managed Rulespec graph has no @graph array")
    releases = [
        value
        for value in nodes
        if isinstance(value, Mapping) and value.get("@id") == release_id
    ]
    if len(releases) != 1:
        raise ConceptReleaseError(
            "managed Rulespec graph does not name the selected release exactly once"
        )
    return _require_digest(
        releases[0].get("rkaf:referenceReleaseDigest"),
        "managed reference release digest",
    )


def _record_types(record: Mapping[str, Any]) -> frozenset[str]:
    value = record.get("@type")
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return frozenset(item for item in value if isinstance(item, str))
    return frozenset()


@dataclass(frozen=True, slots=True)
class ManagedReleaseRingAssignment:
    """A reviewed four-ring classification for one exact managed release."""

    managed_manifest_digest: str
    release_id: str
    semantic_ring: SemanticRing
    assigned_by: str
    assigned_at: str
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "managed_manifest_digest",
            _require_digest(
                self.managed_manifest_digest,
                "ring assignment managedManifestDigest",
            ),
        )
        object.__setattr__(
            self,
            "release_id",
            _require_iri(self.release_id, "ring assignment releaseId"),
        )
        object.__setattr__(
            self,
            "semantic_ring",
            _require_ring(self.semantic_ring, "ring assignment semanticRing"),
        )
        object.__setattr__(
            self,
            "assigned_by",
            _require_iri(self.assigned_by, "ring assignment assignedBy"),
        )
        object.__setattr__(
            self,
            "assigned_at",
            _require_datetime(self.assigned_at, "ring assignment assignedAt"),
        )
        object.__setattr__(
            self,
            "evidence",
            _require_unique_iris(self.evidence, "ring assignment evidence"),
        )

    def _basis(self) -> dict[str, Any]:
        return {
            "type": "ManagedReleaseRingAssignment",
            "schemaVersion": MANAGED_RELEASE_RING_ASSIGNMENT_VERSION,
            "managedManifestDigest": self.managed_manifest_digest,
            "releaseId": self.release_id,
            "semanticRing": self.semantic_ring,
            "assignedBy": self.assigned_by,
            "assignedAt": self.assigned_at,
            "evidence": list(self.evidence),
        }

    @property
    def content_digest(self) -> str:
        return sha256_digest(_canonical_bytes(self._basis()))

    @property
    def identifier(self) -> str:
        return (
            "urn:ref:managed-release-ring-assignment:"
            + self.content_digest.removeprefix("sha256:")
        )

    def as_record(self) -> dict[str, Any]:
        return {
            **self._basis(),
            "id": self.identifier,
            "contentDigest": self.content_digest,
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> Self:
        if not isinstance(value, Mapping):
            raise ConceptReleaseError(
                "managed release ring assignment must be an object"
            )
        _require_exact_fields(
            value,
            {
                "id",
                "type",
                "schemaVersion",
                "contentDigest",
                "managedManifestDigest",
                "releaseId",
                "semanticRing",
                "assignedBy",
                "assignedAt",
                "evidence",
            },
            "managed release ring assignment",
        )
        if (
            value.get("type") != "ManagedReleaseRingAssignment"
            or value.get("schemaVersion") != MANAGED_RELEASE_RING_ASSIGNMENT_VERSION
        ):
            raise ConceptReleaseError(
                "managed release ring assignment version is unsupported"
            )
        assignment = cls(
            managed_manifest_digest=cast(
                str,
                value.get("managedManifestDigest"),
            ),
            release_id=cast(str, value.get("releaseId")),
            semantic_ring=_require_ring(
                value.get("semanticRing"),
                "ring assignment semanticRing",
            ),
            assigned_by=cast(str, value.get("assignedBy")),
            assigned_at=cast(str, value.get("assignedAt")),
            evidence=cast(tuple[str, ...], value.get("evidence")),
        )
        if (
            value.get("id") != assignment.identifier
            or value.get("contentDigest") != assignment.content_digest
        ):
            raise ConceptReleaseError(
                "managed release ring assignment content identity is stale"
            )
        if assignment.as_record() != dict(value):
            raise ConceptReleaseError(
                "managed release ring assignment does not reproduce canonically"
            )
        return assignment

    def artifact_bytes(self) -> bytes:
        return _canonical_bytes(self.as_record())

    def write_to(self, path: Path | str) -> Path:
        destination = Path(path)
        if destination.exists() or destination.is_symlink():
            raise ConceptReleaseError(
                f"ring assignment destination already exists: {destination}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}-",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(self.artifact_bytes())
            os.replace(temporary, destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return destination


@dataclass(frozen=True, slots=True)
class PinnedManagedReleaseRingAssignment:
    """One exact, reopened managed-release ring classification."""

    path: Path
    file_digest: str
    assignment: ManagedReleaseRingAssignment

    @classmethod
    def open(
        cls,
        path: Path | str,
        *,
        expected_file_digest: str,
    ) -> Self:
        digest = _require_digest(
            expected_file_digest,
            "ring assignment file digest",
        )
        candidate = Path(path)
        if candidate.is_symlink():
            raise ConceptReleaseError("ring assignment must not be a symlink")
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            raise ConceptReleaseError("ring assignment does not exist") from error
        if not resolved.is_file():
            raise ConceptReleaseError("ring assignment must be a regular file")
        payload = resolved.read_bytes()
        if sha256_digest(payload) != digest:
            raise ConceptReleaseError("ring assignment file digest differs")
        record = _read_json(payload, "managed release ring assignment")
        if not isinstance(record, Mapping) or _canonical_bytes(record) != payload:
            raise ConceptReleaseError(
                "managed release ring assignment bytes are not canonical"
            )
        assignment = ManagedReleaseRingAssignment.from_record(record)
        if resolved.read_bytes() != payload:
            raise ConceptReleaseError(
                "managed release ring assignment changed while opening"
            )
        return cls(path=resolved, file_digest=digest, assignment=assignment)

    def verified_assignment(self) -> ManagedReleaseRingAssignment:
        return self.open(
            self.path,
            expected_file_digest=self.file_digest,
        ).assignment

    def pin(self) -> dict[str, str]:
        assignment = self.verified_assignment()
        return {
            "id": assignment.identifier,
            "contentDigest": assignment.content_digest,
            "fileDigest": self.file_digest,
        }


@dataclass(frozen=True, slots=True)
class PinnedSourceConceptRelease:
    """One exact path-backed source-concept release."""

    manifest_path: Path
    manifest_digest: str
    release_id: str
    semantic_ring: SemanticRing

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> Self:
        digest = _require_digest(
            expected_manifest_digest,
            "source-concept manifest digest",
        )
        try:
            view = SourceConceptReleaseView.open(
                manifest_path,
                expected_manifest_digest=digest,
            )
        except SourceConceptReleaseError as error:
            raise ConceptReleaseError(str(error)) from error
        return cls(
            manifest_path=(view.path / _BUNDLE_MANIFEST_PATH).resolve(strict=True),
            manifest_digest=digest,
            release_id=view.release_id,
            semantic_ring=view.semantic_ring,
        )

    def verified_view(self) -> SourceConceptReleaseView:
        """Reopen the package so changes after selection fail closed."""

        try:
            view = SourceConceptReleaseView.open(
                self.manifest_path,
                expected_manifest_digest=self.manifest_digest,
            )
        except SourceConceptReleaseError as error:
            raise ConceptReleaseError(str(error)) from error
        if (
            view.release_id != self.release_id
            or view.semantic_ring != self.semantic_ring
        ):
            raise ConceptReleaseError(
                "source-concept release identity or semantic ring changed"
            )
        return view

    def pin(self) -> dict[str, str]:
        return _source_release_pin(self.verified_view())

    def member_ids(self) -> frozenset[str]:
        return _source_member_ids(self.verified_view())


@dataclass(frozen=True, slots=True)
class PinnedManagedConceptRelease:
    """One exact complete-membership release inside a managed bundle."""

    manifest_path: Path
    manifest_digest: str
    release_id: str
    ring_assignment: PinnedManagedReleaseRingAssignment

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
        release_id: str,
        ring_assignment: PinnedManagedReleaseRingAssignment,
    ) -> Self:
        digest = _require_digest(
            expected_manifest_digest,
            "managed release manifest digest",
        )
        selected_release = _require_iri(
            release_id,
            "managed concept release id",
        )
        if not isinstance(ring_assignment, PinnedManagedReleaseRingAssignment):
            raise ConceptReleaseError(
                "managed concept release requires a pinned ring assignment"
            )
        assignment = ring_assignment.verified_assignment()
        if (
            assignment.managed_manifest_digest != digest
            or assignment.release_id != selected_release
        ):
            raise ConceptReleaseError(
                "managed release ring assignment names another exact release"
            )
        try:
            view = ManagedReleaseGraphFactsView.open(
                manifest_path,
                expected_manifest_digest=digest,
            )
        except ManagedReleaseError as error:
            raise ConceptReleaseError(str(error)) from error
        if not tuple(view.iter_members(release_iri=selected_release)):
            raise ConceptReleaseError(
                "managed concept release is not an exact complete-membership release in the bundle"
            )
        requested = Path(manifest_path)
        candidate = (
            requested / _BUNDLE_MANIFEST_PATH if requested.is_dir() else requested
        )
        return cls(
            manifest_path=candidate.resolve(strict=True),
            manifest_digest=digest,
            release_id=selected_release,
            ring_assignment=ring_assignment,
        )

    @property
    def semantic_ring(self) -> SemanticRing:
        return self.ring_assignment.verified_assignment().semantic_ring

    def verified_view(self) -> ManagedReleaseGraphFactsView:
        """Reopen the package and reselect the same complete release."""

        view, _ = self._open_verified_view_and_assignment()
        return view

    def verified_view_and_pin(
        self,
    ) -> tuple[ManagedReleaseGraphFactsView, dict[str, Any]]:
        """Reopen once and derive the exact pin from that same verified view."""

        view, assignment = self._open_verified_view_and_assignment()
        return view, self._pin_from_verified_view(view, assignment)

    def _open_verified_view_and_assignment(
        self,
    ) -> tuple[ManagedReleaseGraphFactsView, ManagedReleaseRingAssignment]:
        """Open and validate one release without deriving unused pin fields."""

        try:
            view = ManagedReleaseGraphFactsView.open(
                self.manifest_path,
                expected_manifest_digest=self.manifest_digest,
            )
        except ManagedReleaseError as error:
            raise ConceptReleaseError(str(error)) from error
        assignment = self.ring_assignment.verified_assignment()
        if (
            assignment.managed_manifest_digest != self.manifest_digest
            or assignment.release_id != self.release_id
        ):
            raise ConceptReleaseError(
                "managed release ring assignment names another exact release"
            )
        if not tuple(view.iter_members(release_iri=self.release_id)):
            raise ConceptReleaseError(
                "managed concept release is no longer present or complete"
            )
        return view, assignment

    def _pin_from_verified_view(
        self,
        view: ManagedReleaseGraphFactsView,
        assignment: ManagedReleaseRingAssignment,
    ) -> dict[str, Any]:
        """Pin exact distribution bytes and declared vocabulary identity separately."""

        return {
            "releaseKind": "managedReferenceRelease",
            "semanticRing": assignment.semantic_ring,
            "releaseId": self.release_id,
            "manifestDigest": self.manifest_digest,
            "managedBundleReleaseId": view.release_id,
            "ringAssignment": {
                "id": assignment.identifier,
                "contentDigest": assignment.content_digest,
                "fileDigest": self.ring_assignment.file_digest,
            },
            "rulespecGraph": {
                "id": view.rulespec_graph_id,
                "digest": rulespec_graph_digest(_plain(view.rulespec_graph)),
            },
            "declaredReleaseDigest": _managed_declared_release_digest(
                view,
                self.release_id,
            ),
        }

    def pin(self) -> dict[str, Any]:
        _, pin = self.verified_view_and_pin()
        return pin

    def member_ids(self) -> frozenset[str]:
        view = self.verified_view()
        return frozenset(
            member.member_iri
            for member in view.iter_members(release_iri=self.release_id)
        )

    def require_local_concept(self, concept_iri: str) -> None:
        """Require one selected member to be an actual rkaf:LocalConcept."""

        concept = _require_iri(concept_iri, "managed subject concept")
        view = self.verified_view()
        member = view.lookup_member(concept)
        if member is None or member.release_iri != self.release_id:
            raise ConceptReleaseError(
                "managed subject concept is outside the exact release"
            )
        if not (_record_types(member.record) & _LOCAL_CONCEPT_TYPES):
            raise ConceptReleaseError(
                "managed subject admission requires an rkaf:LocalConcept member"
            )


ConceptReleaseSource: TypeAlias = (
    PinnedSourceConceptRelease | PinnedManagedConceptRelease
)
SubjectConceptRelease: TypeAlias = (
    SourceConceptReleaseBundle
    | PinnedSourceConceptRelease
    | PinnedManagedConceptRelease
)


def _source_release_pin(
    release: SourceConceptReleaseBundle | SourceConceptReleaseView,
) -> dict[str, str]:
    return {
        "releaseKind": "sourceConceptRelease",
        "semanticRing": release.semantic_ring,
        "releaseId": _require_iri(release.release_id, "source release id"),
        "manifestDigest": _require_digest(
            release.manifest_digest,
            "source release manifest digest",
        ),
        "releaseDigest": _require_digest(
            release.release_digest,
            "source release digest",
        ),
        "logicalDigest": _require_digest(
            release.logical_digest,
            "source release logical digest",
        ),
    }


def _source_member_ids(
    release: SourceConceptReleaseBundle | SourceConceptReleaseView,
) -> frozenset[str]:
    return frozenset(
        _require_iri(concept.get("id"), f"source release concept[{index}].id")
        for index, concept in enumerate(release.concepts)
    )


@dataclass(frozen=True, slots=True)
class VerifiedConceptReleaseFacts:
    """One operation-scoped release verification shared by its consumers.

    Composed Atlas workflows use this value so pin, membership, graph, and
    subject-admission checks all derive from the same freshly opened bytes.
    Holding this value does not cache verification across operations; callers
    create a new value at every explicit trust boundary.
    """

    release: SubjectConceptRelease
    view: SourceConceptReleaseBundle | SourceConceptReleaseView | ManagedReleaseGraphFactsView
    pin: Mapping[str, Any]
    member_ids: frozenset[str]

    @property
    def semantic_ring(self) -> SemanticRing:
        return _require_ring(self.pin.get("semanticRing"), "concept release semanticRing")

    def require_subject(self) -> None:
        if self.semantic_ring != "subject":
            raise ConceptReleaseError("subject use rejects non-subject releases")

    def require_admissible_subject_concept(self, concept_iri: str) -> str:
        """Check subject membership and managed-local authorship without reopening."""

        self.require_subject()
        concept = _require_iri(concept_iri, "subject concept")
        if concept not in self.member_ids:
            raise ConceptReleaseError("subject concept is outside the exact release")
        if isinstance(self.release, PinnedManagedConceptRelease):
            if not isinstance(self.view, ManagedReleaseGraphFactsView):
                raise ConceptReleaseError("managed release verification returned the wrong view kind")
            member = self.view.lookup_member(concept)
            if member is None or member.release_iri != self.release.release_id:
                raise ConceptReleaseError(
                    "managed subject concept is outside the exact release"
                )
            if not (_record_types(member.record) & _LOCAL_CONCEPT_TYPES):
                raise ConceptReleaseError(
                    "managed subject admission requires an rkaf:LocalConcept member"
                )
        return concept

    def rights_metadata(
        self,
        supplied: Sequence[RightsMetadata | Mapping[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Resolve exact rights facts from this same verification boundary."""

        self.require_subject()
        graph: Mapping[str, str] | None
        if isinstance(self.release, PinnedManagedConceptRelease):
            if supplied is None:
                raise ConceptReleaseError(
                    "managed subject admission requires explicit release-bound rights metadata"
                )
            values = supplied
            graph = cast(Mapping[str, str], self.pin["rulespecGraph"])
        else:
            if not isinstance(
                self.view,
                (SourceConceptReleaseBundle, SourceConceptReleaseView),
            ):
                raise ConceptReleaseError("source release verification returned the wrong view kind")
            values = cast(
                Sequence[RightsMetadata | Mapping[str, Any]],
                self.view.rights_metadata,
            )
            graph = None
        try:
            normalized = tuple(
                item.as_record()
                for item in validate_rights_metadata_records(values)
            )
        except SemanticFoundationError as error:
            raise ConceptReleaseError(str(error)) from error
        if not normalized:
            raise ConceptReleaseError(
                "subject release rights metadata must not be empty"
            )
        if graph is not None and any(
            row["sourceArtifact"] != graph["id"]
            or row["sourceDigest"] != graph["digest"]
            for row in normalized
        ):
            raise ConceptReleaseError(
                "managed subject rights metadata must name the exact Rulespec graph and digest"
            )
        if graph is None and supplied is not None:
            try:
                supplied_normalized = tuple(
                    item.as_record()
                    for item in validate_rights_metadata_records(supplied)
                )
            except SemanticFoundationError as error:
                raise ConceptReleaseError(str(error)) from error
            if supplied_normalized != normalized:
                raise ConceptReleaseError(
                    "source subject rights metadata differs from the exact release"
                )
        return normalized


def verified_concept_release_facts(
    release: SubjectConceptRelease,
) -> VerifiedConceptReleaseFacts:
    """Freshly verify one release once for a composed consumer operation."""

    if isinstance(release, SourceConceptReleaseBundle):
        view: SourceConceptReleaseBundle | SourceConceptReleaseView | ManagedReleaseGraphFactsView = release
        pin: dict[str, Any] = _source_release_pin(release)
        members = _source_member_ids(release)
    elif isinstance(release, PinnedSourceConceptRelease):
        view = release.verified_view()
        pin = _source_release_pin(view)
        members = _source_member_ids(view)
    elif isinstance(release, PinnedManagedConceptRelease):
        view, assignment = release._open_verified_view_and_assignment()
        pin = release._pin_from_verified_view(view, assignment)
        members = frozenset(
            member.member_iri
            for member in view.iter_members(release_iri=release.release_id)
        )
    else:
        raise ConceptReleaseError("concept release must be an exact supported release")
    return VerifiedConceptReleaseFacts(
        release=release,
        view=view,
        pin=cast(Mapping[str, Any], deep_freeze_json(pin)),
        member_ids=members,
    )


def concept_release_pin(release: SubjectConceptRelease) -> dict[str, Any]:
    """Return one discriminated exact-release pin for any supported release."""

    return cast(dict[str, Any], _plain(verified_concept_release_facts(release).pin))


def concept_release_member_ids(
    release: SubjectConceptRelease,
) -> frozenset[str]:
    """Return the exact identifiers selected by one release."""

    return verified_concept_release_facts(release).member_ids


def require_subject_concept_release(release: SubjectConceptRelease) -> None:
    """Require a supported exact release classified in the subject ring."""

    verified_concept_release_facts(release).require_subject()


def require_admissible_subject_concept(
    release: SubjectConceptRelease,
    concept_iri: str,
) -> str:
    """Require exact membership and managed-local authorship when applicable."""

    return verified_concept_release_facts(
        release
    ).require_admissible_subject_concept(concept_iri)


def _normalized_reference(
    value: object,
    *,
    label: str,
    fields: set[str],
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ConceptReleaseError(f"{label} must be an object")
    row = cast(dict[str, Any], _plain(value))
    _require_exact_fields(row, fields, label)
    result: dict[str, str] = {}
    for field in fields:
        result[field] = (
            _require_iri(row.get(field), f"{label}.{field}")
            if field == "id"
            else _require_digest(row.get(field), f"{label}.{field}")
        )
    return result


def normalize_concept_release_pin(value: object) -> dict[str, Any]:
    """Validate the closed, discriminated exact-release pin shape."""

    if not isinstance(value, Mapping):
        raise ConceptReleaseError("subjectConceptRelease must be an object")
    row = cast(dict[str, Any], _plain(value))
    release_kind = row.get("releaseKind")
    if release_kind == "sourceConceptRelease":
        _require_exact_fields(
            row,
            {
                "releaseKind",
                "semanticRing",
                "releaseId",
                "manifestDigest",
                "releaseDigest",
                "logicalDigest",
            },
            "subjectConceptRelease",
        )
        return {
            "releaseKind": "sourceConceptRelease",
            "semanticRing": _require_ring(
                row.get("semanticRing"),
                "subjectConceptRelease.semanticRing",
            ),
            "releaseId": _require_iri(
                row.get("releaseId"),
                "subjectConceptRelease.releaseId",
            ),
            "manifestDigest": _require_digest(
                row.get("manifestDigest"),
                "subjectConceptRelease.manifestDigest",
            ),
            "releaseDigest": _require_digest(
                row.get("releaseDigest"),
                "subjectConceptRelease.releaseDigest",
            ),
            "logicalDigest": _require_digest(
                row.get("logicalDigest"),
                "subjectConceptRelease.logicalDigest",
            ),
        }
    if release_kind == "managedReferenceRelease":
        _require_exact_fields(
            row,
            {
                "releaseKind",
                "semanticRing",
                "releaseId",
                "manifestDigest",
                "managedBundleReleaseId",
                "ringAssignment",
                "rulespecGraph",
                "declaredReleaseDigest",
            },
            "subjectConceptRelease",
        )
        return {
            "releaseKind": "managedReferenceRelease",
            "semanticRing": _require_ring(
                row.get("semanticRing"),
                "subjectConceptRelease.semanticRing",
            ),
            "releaseId": _require_iri(
                row.get("releaseId"),
                "subjectConceptRelease.releaseId",
            ),
            "manifestDigest": _require_digest(
                row.get("manifestDigest"),
                "subjectConceptRelease.manifestDigest",
            ),
            "managedBundleReleaseId": _require_iri(
                row.get("managedBundleReleaseId"),
                "subjectConceptRelease.managedBundleReleaseId",
            ),
            "ringAssignment": _normalized_reference(
                row.get("ringAssignment"),
                label="subjectConceptRelease.ringAssignment",
                fields={"id", "contentDigest", "fileDigest"},
            ),
            "rulespecGraph": _normalized_reference(
                row.get("rulespecGraph"),
                label="subjectConceptRelease.rulespecGraph",
                fields={"id", "digest"},
            ),
            "declaredReleaseDigest": _require_digest(
                row.get("declaredReleaseDigest"),
                "subjectConceptRelease.declaredReleaseDigest",
            ),
        }
    raise ConceptReleaseError(
        "subjectConceptRelease.releaseKind must be sourceConceptRelease or managedReferenceRelease"
    )


def subject_release_rights_metadata(
    release: SubjectConceptRelease,
    supplied: Sequence[RightsMetadata | Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Resolve exact rights facts without treating them as use permission.

    Source releases already publish their rights rows. Managed releases do not
    expose release-scoped rights in their publication shape, so the admission
    review must supply a row bound to the exact Rulespec graph identifier and
    digest in the managed release pin.
    """

    return verified_concept_release_facts(release).rights_metadata(supplied)


__all__ = [
    "MANAGED_RELEASE_RING_ASSIGNMENT_VERSION",
    "ConceptReleaseError",
    "ConceptReleaseSource",
    "ManagedReleaseRingAssignment",
    "PinnedManagedConceptRelease",
    "PinnedManagedReleaseRingAssignment",
    "PinnedSourceConceptRelease",
    "SubjectConceptRelease",
    "VerifiedConceptReleaseFacts",
    "concept_release_member_ids",
    "concept_release_pin",
    "normalize_concept_release_pin",
    "require_admissible_subject_concept",
    "require_subject_concept_release",
    "subject_release_rights_metadata",
    "verified_concept_release_facts",
]
