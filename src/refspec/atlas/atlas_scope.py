"""One non-authorizing exact scope for the four-ring vocabulary atlas.

The scope names the exact concept releases and relation bundles a canonical
atlas build may publish. Subject participation is planning metadata on a
release row; it is never admission or use permission. Relation bundles must
close over release pins already present in the same scope.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from typing_extensions import Self

from refspec import binding
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.semantic_foundation import SemanticRing

from .concept_release import (
    ConceptReleaseError,
    ConceptReleaseSource,
    PinnedManagedConceptRelease,
    PinnedSourceConceptRelease,
)
from .relation_assertion import (
    PinnedRelationAssertionBundle,
    RelationAssertionError,
)

ATLAS_SCOPE_VERSION = "1.0"
ATLAS_SCOPE_TYPE = "VocabularyAtlasScope"

SubjectParticipation = Literal["core", "specialist", "bridge"]

_PARTICIPATION = frozenset({"core", "specialist", "bridge"})
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCOPE_BASIS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "scopeName",
        "releases",
        "relationBundles",
    }
)
_SCOPE_RECORD_FIELDS = _SCOPE_BASIS_FIELDS | {"id", "contentDigest"}


class AtlasScopeError(ValueError):
    """An atlas scope is incomplete, mutable, or internally inconsistent."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        binding.validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise AtlasScopeError(str(error)) from error
    return canonical_json_bytes(plain)


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise AtlasScopeError(f"{label} must be non-empty trimmed text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise AtlasScopeError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise AtlasScopeError(f"{label} must not contain credentials")
    return iri


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AtlasScopeError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise AtlasScopeError(
            f"{label} fields differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _read_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise AtlasScopeError(f"{label} must be valid canonical UTF-8 JSON") from error


@dataclass(frozen=True, slots=True)
class AtlasScopeRelease:
    """One exact release plus optional subject participation metadata."""

    source: ConceptReleaseSource
    subject_participation: SubjectParticipation | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.source,
            (PinnedSourceConceptRelease, PinnedManagedConceptRelease),
        ):
            raise AtlasScopeError("atlas scope release must be a path-backed exact concept release")
        try:
            pin = self.source.pin()
        except ConceptReleaseError as error:
            raise AtlasScopeError(str(error)) from error
        participation = self.subject_participation
        if participation is not None and (not isinstance(participation, str) or participation not in _PARTICIPATION):
            raise AtlasScopeError("subject participation must be core, specialist, bridge, or absent")
        if participation is not None and pin["semanticRing"] != "subject":
            raise AtlasScopeError("only a subject release may have a participation class")

    @property
    def release_id(self) -> str:
        try:
            return cast(str, self.source.pin()["releaseId"])
        except ConceptReleaseError as error:
            raise AtlasScopeError(str(error)) from error

    @property
    def semantic_ring(self) -> SemanticRing:
        try:
            return cast(SemanticRing, self.source.pin()["semanticRing"])
        except ConceptReleaseError as error:
            raise AtlasScopeError(str(error)) from error

    def pin(self) -> dict[str, Any]:
        try:
            result = self.source.pin()
        except ConceptReleaseError as error:
            raise AtlasScopeError(str(error)) from error
        if self.subject_participation is not None:
            result["subjectParticipation"] = self.subject_participation
        return result


def _release_pin_without_participation(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _plain(item) for key, item in value.items() if key != "subjectParticipation"}


def _normalized_release_rows(
    releases: Sequence[AtlasScopeRelease],
) -> tuple[tuple[AtlasScopeRelease, ...], tuple[Mapping[str, Any], ...]]:
    if not isinstance(releases, Sequence) or isinstance(releases, (str, bytes)) or not releases:
        raise AtlasScopeError("atlas scope releases must be a non-empty array")
    values: list[tuple[AtlasScopeRelease, Mapping[str, Any]]] = []
    identifiers: set[str] = set()
    for index, release in enumerate(releases):
        if not isinstance(release, AtlasScopeRelease):
            raise AtlasScopeError(f"atlas scope releases[{index}] must be an AtlasScopeRelease")
        pin = release.pin()
        release_id = _require_iri(
            pin.get("releaseId"),
            f"atlas scope releases[{index}].releaseId",
        )
        if release_id in identifiers:
            raise AtlasScopeError("atlas scope repeats a releaseId")
        identifiers.add(release_id)
        values.append(
            (
                release,
                cast(Mapping[str, Any], deep_freeze_json(pin)),
            )
        )
    values.sort(key=lambda pair: str(pair[1]["releaseId"]))
    return (
        tuple(pair[0] for pair in values),
        tuple(pair[1] for pair in values),
    )


def _normalized_relation_rows(
    relations: Sequence[PinnedRelationAssertionBundle],
) -> tuple[
    tuple[PinnedRelationAssertionBundle, ...],
    tuple[Mapping[str, Any], ...],
]:
    if not isinstance(relations, Sequence) or isinstance(relations, (str, bytes)):
        raise AtlasScopeError("atlas scope relation_bundles must be an array")
    values: list[tuple[PinnedRelationAssertionBundle, Mapping[str, Any]]] = []
    identifiers: set[str] = set()
    for index, relation in enumerate(relations):
        if not isinstance(relation, PinnedRelationAssertionBundle):
            raise AtlasScopeError(f"atlas scope relation_bundles[{index}] must be a pinned relation bundle")
        try:
            pin = relation.pin()
        except RelationAssertionError as error:
            raise AtlasScopeError(str(error)) from error
        identifier = _require_iri(
            pin.get("id"),
            f"atlas scope relation_bundles[{index}].id",
        )
        if identifier in identifiers:
            raise AtlasScopeError("atlas scope repeats a relation bundle id")
        identifiers.add(identifier)
        values.append(
            (
                relation,
                cast(Mapping[str, Any], deep_freeze_json(pin)),
            )
        )
    values.sort(key=lambda pair: str(pair[1]["id"]))
    return (
        tuple(pair[0] for pair in values),
        tuple(pair[1] for pair in values),
    )


def _require_relation_release_closure(
    release_rows: Sequence[Mapping[str, Any]],
    relations: Sequence[PinnedRelationAssertionBundle],
) -> None:
    scope_releases = {cast(str, row["releaseId"]): _release_pin_without_participation(row) for row in release_rows}
    for relation in relations:
        try:
            bundle = relation.verified_bundle()
        except RelationAssertionError as error:
            raise AtlasScopeError(str(error)) from error
        for release_pin in bundle.release_pins:
            release_id = cast(str, release_pin["releaseId"])
            scoped = scope_releases.get(release_id)
            if scoped is None:
                raise AtlasScopeError("relation bundle release closure is outside the atlas scope")
            if scoped != _plain(release_pin):
                raise AtlasScopeError("relation bundle release pin differs from the exact atlas scope release")


def _scope_basis(
    *,
    scope_name: str,
    release_rows: Sequence[Mapping[str, Any]],
    relation_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "type": ATLAS_SCOPE_TYPE,
        "schemaVersion": ATLAS_SCOPE_VERSION,
        "scopeName": scope_name,
        "releases": [_plain(value) for value in release_rows],
        "relationBundles": [_plain(value) for value in relation_rows],
    }


@dataclass(frozen=True, slots=True)
class VocabularyAtlasScope:
    """A content-derived exact scope; never publication or use permission."""

    record: Mapping[str, Any]
    _releases: tuple[AtlasScopeRelease, ...]
    _relation_bundles: tuple[PinnedRelationAssertionBundle, ...]

    def __post_init__(self) -> None:
        releases, release_rows = _normalized_release_rows(self._releases)
        relations, relation_rows = _normalized_relation_rows(self._relation_bundles)
        _require_relation_release_closure(release_rows, relations)
        if not isinstance(self.record, Mapping):
            raise AtlasScopeError("atlas scope must be an object")
        row = cast(dict[str, Any], _plain(self.record))
        _require_exact_fields(
            row,
            set(_SCOPE_RECORD_FIELDS),
            "atlas scope",
        )
        if row.get("type") != ATLAS_SCOPE_TYPE or row.get("schemaVersion") != ATLAS_SCOPE_VERSION:
            raise AtlasScopeError("atlas scope version is unsupported")
        basis = _scope_basis(
            scope_name=_require_iri(row.get("scopeName"), "atlas scope scopeName"),
            release_rows=release_rows,
            relation_rows=relation_rows,
        )
        content_digest = sha256_digest(_canonical_bytes(basis))
        expected = {
            **basis,
            "id": ("urn:ref:vocabulary-atlas-scope:" + content_digest.removeprefix("sha256:")),
            "contentDigest": content_digest,
        }
        if row != expected:
            raise AtlasScopeError("atlas scope content identity, inputs, or canonical order differs")
        object.__setattr__(
            self,
            "record",
            cast(Mapping[str, Any], deep_freeze_json(expected)),
        )
        object.__setattr__(self, "_releases", releases)
        object.__setattr__(self, "_relation_bundles", relations)

    @classmethod
    def create(
        cls,
        *,
        scope_name: str,
        releases: Sequence[AtlasScopeRelease],
        relation_bundles: Sequence[PinnedRelationAssertionBundle] = (),
    ) -> Self:
        name = _require_iri(scope_name, "scope_name")
        normalized_releases, release_rows = _normalized_release_rows(releases)
        normalized_relations, relation_rows = _normalized_relation_rows(relation_bundles)
        _require_relation_release_closure(
            release_rows,
            normalized_relations,
        )
        basis = _scope_basis(
            scope_name=name,
            release_rows=release_rows,
            relation_rows=relation_rows,
        )
        content_digest = sha256_digest(_canonical_bytes(basis))
        return cls(
            record={
                **basis,
                "id": ("urn:ref:vocabulary-atlas-scope:" + content_digest.removeprefix("sha256:")),
                "contentDigest": content_digest,
            },
            _releases=normalized_releases,
            _relation_bundles=normalized_relations,
        )

    @classmethod
    def from_record(
        cls,
        value: Mapping[str, Any],
        *,
        releases: Sequence[AtlasScopeRelease],
        relation_bundles: Sequence[PinnedRelationAssertionBundle] = (),
    ) -> Self:
        return cls(
            record=value,
            _releases=tuple(releases),
            _relation_bundles=tuple(relation_bundles),
        )

    @property
    def identifier(self) -> str:
        return cast(str, self.record["id"])

    @property
    def content_digest(self) -> str:
        return cast(str, self.record["contentDigest"])

    @property
    def scope_name(self) -> str:
        return cast(str, self.record["scopeName"])

    @property
    def releases(self) -> tuple[AtlasScopeRelease, ...]:
        return self._releases

    @property
    def relation_bundles(self) -> tuple[PinnedRelationAssertionBundle, ...]:
        return self._relation_bundles

    def as_record(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self.record))

    def artifact_bytes(self) -> bytes:
        return _canonical_bytes(self.as_record())

    def verify(self) -> None:
        VocabularyAtlasScope.from_record(
            self.as_record(),
            releases=self._releases,
            relation_bundles=self._relation_bundles,
        )

    def write_to(self, path: Path | str) -> Path:
        destination = Path(path)
        if destination.exists() or destination.is_symlink():
            raise AtlasScopeError(f"atlas scope destination already exists: {destination}")
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
class PinnedVocabularyAtlasScope:
    """One exact scope artifact plus every source needed to reopen it."""

    path: Path
    file_digest: str
    scope_id: str
    content_digest: str
    _releases: tuple[AtlasScopeRelease, ...]
    _relation_bundles: tuple[PinnedRelationAssertionBundle, ...]

    @classmethod
    def open(
        cls,
        path: Path | str,
        *,
        expected_file_digest: str,
        releases: Sequence[AtlasScopeRelease],
        relation_bundles: Sequence[PinnedRelationAssertionBundle] = (),
    ) -> Self:
        digest = _require_digest(expected_file_digest, "atlas scope file digest")
        candidate = Path(path)
        if candidate.is_symlink():
            raise AtlasScopeError("atlas scope must not be a symlink")
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            raise AtlasScopeError("atlas scope does not exist") from error
        if not resolved.is_file():
            raise AtlasScopeError("atlas scope must be a regular file")
        payload = resolved.read_bytes()
        if sha256_digest(payload) != digest:
            raise AtlasScopeError("atlas scope file digest differs")
        record = _read_json(payload, "atlas scope")
        if not isinstance(record, Mapping) or _canonical_bytes(record) != payload:
            raise AtlasScopeError("atlas scope bytes are not canonical")
        scope = VocabularyAtlasScope.from_record(
            record,
            releases=releases,
            relation_bundles=relation_bundles,
        )
        if resolved.read_bytes() != payload:
            raise AtlasScopeError("atlas scope changed while opening")
        return cls(
            path=resolved,
            file_digest=digest,
            scope_id=scope.identifier,
            content_digest=scope.content_digest,
            _releases=scope.releases,
            _relation_bundles=scope.relation_bundles,
        )

    def verified_scope(self) -> VocabularyAtlasScope:
        reopened = self.open(
            self.path,
            expected_file_digest=self.file_digest,
            releases=self._releases,
            relation_bundles=self._relation_bundles,
        )
        if reopened.scope_id != self.scope_id or reopened.content_digest != self.content_digest:
            raise AtlasScopeError("atlas scope identity or content digest changed")
        payload = _read_json(self.path.read_bytes(), "atlas scope")
        if not isinstance(payload, Mapping):
            raise AtlasScopeError("atlas scope must be an object")
        return VocabularyAtlasScope.from_record(
            payload,
            releases=self._releases,
            relation_bundles=self._relation_bundles,
        )

    def pin(self) -> dict[str, str]:
        scope = self.verified_scope()
        return {
            "role": "vocabularyAtlasScope",
            "id": scope.identifier,
            "contentDigest": scope.content_digest,
            "fileDigest": self.file_digest,
        }


__all__ = [
    "ATLAS_SCOPE_TYPE",
    "ATLAS_SCOPE_VERSION",
    "AtlasScopeError",
    "AtlasScopeRelease",
    "PinnedVocabularyAtlasScope",
    "SubjectParticipation",
    "VocabularyAtlasScope",
]
