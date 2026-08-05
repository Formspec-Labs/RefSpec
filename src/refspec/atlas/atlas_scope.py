"""One index-bound, non-authorizing scope for the four-ring atlas.

The scope selects exact concept releases and relation bundles. The pinned
atlas index remains the only source of ring participation, source module, and
resource classification. A scope records every matching index row so no
classification can be dropped or supplied by a caller.
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
from refspec.atlas_index import AtlasIndexError, PinnedAtlasIndex
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.semantic_foundation import (
    SEMANTIC_RINGS,
    SemanticRing,
)

from .concept_release import (
    ConceptReleaseError,
    ConceptReleaseSource,
    PinnedManagedConceptRelease,
    PinnedSourceConceptRelease,
    normalize_concept_release_pin,
)
from .relation_assertion import (
    PinnedRelationAssertionBundle,
    RelationAssertionError,
)

ATLAS_SCOPE_VERSION = "1.0"
ATLAS_SCOPE_TYPE = "VocabularyAtlasScope"

ScopeKind = Literal["bench", "published", "product"]
SubjectParticipation = Literal["core", "specialist", "bridge"]

_SCOPE_KINDS = frozenset({"bench", "published", "product"})
_PARTICIPATION = frozenset({"core", "specialist", "bridge"})
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_INDEX_ROW_REF_FIELDS = {"rowId", "rowDigest"}
_ATLAS_INDEX_PIN_FIELDS = frozenset(
    {"role", "id", "indexDigest", "fileDigest"}
)
_SCOPE_BASIS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "scopeName",
        "scopeKind",
        "atlasIndex",
        "releases",
        "relationBundles",
    }
)
_SCOPE_RECORD_FIELDS = _SCOPE_BASIS_FIELDS | {"id", "contentDigest"}
_RELATION_BUNDLE_PIN_FIELDS = frozenset(
    {
        "role",
        "id",
        "semanticRing",
        "contentDigest",
        "manifestDigest",
    }
)


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


def _require_scope_kind(value: object, label: str) -> ScopeKind:
    if not isinstance(value, str) or value not in _SCOPE_KINDS:
        raise AtlasScopeError(f"{label} must be bench, published, or product")
    return cast(ScopeKind, value)


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise AtlasScopeError(
            f"{label} fields differ; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _read_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise AtlasScopeError(
            f"{label} must be valid canonical UTF-8 JSON"
        ) from error


def _verified_index_snapshot(
    atlas_index: PinnedAtlasIndex,
) -> tuple[Mapping[str, str], tuple[Mapping[str, Any], ...]]:
    if not isinstance(atlas_index, PinnedAtlasIndex):
        raise AtlasScopeError("atlas scope requires a path-backed exact atlas index")
    try:
        index = atlas_index.verified_index()
    except AtlasIndexError as error:
        raise AtlasScopeError(str(error)) from error
    raw_rows = index.get("rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise AtlasScopeError("atlas index rows must be an array")
    rows: list[Mapping[str, Any]] = []
    for position, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise AtlasScopeError(f"atlas index rows[{position}] must be an object")
        rows.append(raw)
    pin: Mapping[str, str] = {
        "role": "AtlasIndex",
        "id": _require_iri(atlas_index.index_id, "atlas index id"),
        "indexDigest": _require_digest(
            atlas_index.index_digest,
            "atlas index content digest",
        ),
        "fileDigest": _require_digest(
            atlas_index.file_digest,
            "atlas index file digest",
        ),
    }
    return pin, tuple(rows)


@dataclass(frozen=True, slots=True)
class AtlasScopeRelease:
    """One exact release; its classifications come from the pinned index."""

    source: ConceptReleaseSource

    def __post_init__(self) -> None:
        if not isinstance(
            self.source,
            (PinnedSourceConceptRelease, PinnedManagedConceptRelease),
        ):
            raise AtlasScopeError(
                "atlas scope release must be a path-backed exact concept release"
            )
        try:
            self.source.pin()
        except ConceptReleaseError as error:
            raise AtlasScopeError(str(error)) from error

    @property
    def release_id(self) -> str:
        return cast(str, self.pin()["releaseId"])

    @property
    def semantic_ring(self) -> SemanticRing:
        return cast(SemanticRing, self.pin()["semanticRing"])

    def pin(self) -> dict[str, Any]:
        try:
            return self.source.pin()
        except ConceptReleaseError as error:
            raise AtlasScopeError(str(error)) from error


def _release_index_refs(
    release_pin: Mapping[str, Any],
    index_rows: Sequence[Mapping[str, Any]],
    *,
    location: str,
) -> list[dict[str, str]]:
    release_id = _require_iri(release_pin.get("releaseId"), f"{location}.releaseId")
    manifest_digest = _require_digest(
        release_pin.get("manifestDigest"),
        f"{location}.manifestDigest",
    )
    semantic_ring = _require_text(
        release_pin.get("semanticRing"),
        f"{location}.semanticRing",
    )
    matches: list[Mapping[str, Any]] = []
    for row in index_rows:
        indexed_release = row.get("release")
        if not isinstance(indexed_release, Mapping):
            continue
        if indexed_release.get("releaseId") == release_id:
            matches.append(row)
    if not matches:
        raise AtlasScopeError(
            f"{location} releaseId is absent from the exact atlas index"
        )

    classifications: set[tuple[str, str | None, str, str]] = set()
    references: list[dict[str, str]] = []
    for position, row in enumerate(matches):
        row_location = f"{location} matching atlas index rows[{position}]"
        indexed_release = cast(Mapping[str, Any], row["release"])
        if indexed_release.get("manifestDigest") != manifest_digest:
            raise AtlasScopeError(
                f"{row_location} manifestDigest differs from the exact release"
            )
        row_ring = row.get("semanticRing")
        if row_ring != semantic_ring:
            raise AtlasScopeError(
                f"{row_location} semanticRing differs from the exact release"
            )
        participation = row.get("atlasParticipation")
        if participation is not None and (
            not isinstance(participation, str)
            or participation not in _PARTICIPATION
        ):
            raise AtlasScopeError(
                f"{row_location} atlasParticipation is unsupported"
            )
        source_module = _require_text(
            row.get("sourceModule"),
            f"{row_location}.sourceModule",
        )
        resource_id = _require_text(
            row.get("resourceId"),
            f"{row_location}.resourceId",
        )
        classifications.add(
            (semantic_ring, cast(str | None, participation), source_module, resource_id)
        )
        references.append(
            {
                "rowId": _require_iri(
                    row.get("rowId"),
                    f"{row_location}.rowId",
                ),
                "rowDigest": _require_digest(
                    row.get("rowDigest"),
                    f"{row_location}.rowDigest",
                ),
            }
        )
    if len(classifications) != 1:
        raise AtlasScopeError(
            f"{location} atlas index rows conflict on ring, participation, "
            "sourceModule, or resourceId"
        )
    return sorted(references, key=lambda value: value["rowId"])


def _normalized_release_rows(
    releases: Sequence[AtlasScopeRelease],
    index_rows: Sequence[Mapping[str, Any]],
) -> tuple[tuple[AtlasScopeRelease, ...], tuple[Mapping[str, Any], ...]]:
    if (
        not isinstance(releases, Sequence)
        or isinstance(releases, (str, bytes))
        or not releases
    ):
        raise AtlasScopeError("atlas scope releases must be a non-empty array")
    values: list[tuple[AtlasScopeRelease, Mapping[str, Any]]] = []
    identifiers: set[str] = set()
    for position, release in enumerate(releases):
        if not isinstance(release, AtlasScopeRelease):
            raise AtlasScopeError(
                f"atlas scope releases[{position}] must be an AtlasScopeRelease"
            )
        pin = release.pin()
        release_id = _require_iri(
            pin.get("releaseId"),
            f"atlas scope releases[{position}].releaseId",
        )
        if release_id in identifiers:
            raise AtlasScopeError("atlas scope repeats a releaseId")
        identifiers.add(release_id)
        row = {
            **pin,
            "atlasIndexRows": _release_index_refs(
                pin,
                index_rows,
                location=f"atlas scope releases[{position}]",
            ),
        }
        values.append(
            (
                release,
                cast(Mapping[str, Any], deep_freeze_json(row)),
            )
        )
    values.sort(
        key=lambda pair: (
            str(pair[1]["semanticRing"]),
            str(pair[1]["releaseId"]),
        )
    )
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
    for position, relation in enumerate(relations):
        if not isinstance(relation, PinnedRelationAssertionBundle):
            raise AtlasScopeError(
                f"atlas scope relation_bundles[{position}] must be a pinned "
                "relation bundle"
            )
        try:
            pin = relation.pin()
        except RelationAssertionError as error:
            raise AtlasScopeError(str(error)) from error
        identifier = _require_iri(
            pin.get("id"),
            f"atlas scope relation_bundles[{position}].id",
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


def _release_pin_without_index_rows(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _plain(item)
        for key, item in value.items()
        if key != "atlasIndexRows"
    }


def _require_relation_release_closure(
    release_rows: Sequence[Mapping[str, Any]],
    relations: Sequence[PinnedRelationAssertionBundle],
) -> None:
    scope_releases = {
        cast(str, row["releaseId"]): _release_pin_without_index_rows(row)
        for row in release_rows
    }
    for relation in relations:
        try:
            bundle = relation.verified_bundle()
        except RelationAssertionError as error:
            raise AtlasScopeError(str(error)) from error
        for release_pin in bundle.release_pins:
            release_id = cast(str, release_pin["releaseId"])
            scoped = scope_releases.get(release_id)
            if scoped is None:
                raise AtlasScopeError(
                    "relation bundle release closure is outside the atlas scope"
                )
            if scoped != _plain(release_pin):
                raise AtlasScopeError(
                    "relation bundle release pin differs from the exact atlas "
                    "scope release"
                )


def _scope_basis(
    *,
    scope_name: str,
    scope_kind: ScopeKind,
    atlas_index_pin: Mapping[str, str],
    release_rows: Sequence[Mapping[str, Any]],
    relation_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "type": ATLAS_SCOPE_TYPE,
        "schemaVersion": ATLAS_SCOPE_VERSION,
        "scopeName": scope_name,
        "scopeKind": scope_kind,
        "atlasIndex": _plain(atlas_index_pin),
        "releases": [_plain(value) for value in release_rows],
        "relationBundles": [_plain(value) for value in relation_rows],
    }


def _normalize_atlas_index_pin(value: object) -> dict[str, str]:
    label = "atlas scope atlasIndex"
    if not isinstance(value, Mapping):
        raise AtlasScopeError(f"{label} must be an object")
    row = cast(dict[str, Any], _plain(value))
    _require_exact_fields(row, set(_ATLAS_INDEX_PIN_FIELDS), label)
    if row.get("role") != "AtlasIndex":
        raise AtlasScopeError(f"{label}.role must be AtlasIndex")
    return {
        "role": "AtlasIndex",
        "id": _require_iri(row.get("id"), f"{label}.id"),
        "indexDigest": _require_digest(
            row.get("indexDigest"),
            f"{label}.indexDigest",
        ),
        "fileDigest": _require_digest(
            row.get("fileDigest"),
            f"{label}.fileDigest",
        ),
    }


def _normalize_index_row_refs(value: object, *, label: str) -> list[dict[str, str]]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
    ):
        raise AtlasScopeError(f"{label} must be a non-empty array")
    result: list[dict[str, str]] = []
    for position, item in enumerate(value):
        item_label = f"{label}[{position}]"
        if not isinstance(item, Mapping):
            raise AtlasScopeError(f"{item_label} must be an object")
        row = cast(dict[str, Any], _plain(item))
        _require_exact_fields(row, set(_INDEX_ROW_REF_FIELDS), item_label)
        result.append(
            {
                "rowId": _require_iri(row.get("rowId"), f"{item_label}.rowId"),
                "rowDigest": _require_digest(
                    row.get("rowDigest"),
                    f"{item_label}.rowDigest",
                ),
            }
        )
    row_ids = [item["rowId"] for item in result]
    if len(set(row_ids)) != len(row_ids):
        raise AtlasScopeError(f"{label} repeat a rowId")
    if row_ids != sorted(row_ids):
        raise AtlasScopeError(f"{label} must be ordered by rowId")
    return result


def _normalize_scope_release_pin(value: object, *, index: int) -> dict[str, Any]:
    label = f"atlas scope releases[{index}]"
    if not isinstance(value, Mapping):
        raise AtlasScopeError(f"{label} must be an object")
    row = cast(dict[str, Any], _plain(value))
    index_rows = row.pop("atlasIndexRows", None)
    try:
        pin = normalize_concept_release_pin(row)
    except ConceptReleaseError as error:
        raise AtlasScopeError(f"{label}: {error}") from error
    pin["atlasIndexRows"] = _normalize_index_row_refs(
        index_rows,
        label=f"{label}.atlasIndexRows",
    )
    return pin


def _normalize_scope_relation_pin(value: object, *, index: int) -> dict[str, str]:
    label = f"atlas scope relationBundles[{index}]"
    if not isinstance(value, Mapping):
        raise AtlasScopeError(f"{label} must be an object")
    row = cast(dict[str, Any], _plain(value))
    _require_exact_fields(row, set(_RELATION_BUNDLE_PIN_FIELDS), label)
    if row.get("role") != "RelationAssertionBundle":
        raise AtlasScopeError(f"{label}.role must be RelationAssertionBundle")
    semantic_ring = row.get("semanticRing")
    if not isinstance(semantic_ring, str) or semantic_ring not in SEMANTIC_RINGS:
        raise AtlasScopeError(
            f"{label}.semanticRing must be subject, entity, value, or legalIdentity"
        )
    return {
        "role": "RelationAssertionBundle",
        "id": _require_iri(row.get("id"), f"{label}.id"),
        "semanticRing": semantic_ring,
        "contentDigest": _require_digest(
            row.get("contentDigest"),
            f"{label}.contentDigest",
        ),
        "manifestDigest": _require_digest(
            row.get("manifestDigest"),
            f"{label}.manifestDigest",
        ),
    }


def validate_atlas_scope_record(value: object) -> dict[str, Any]:
    """Validate one closed scope record without opening any pinned inputs."""

    if not isinstance(value, Mapping):
        raise AtlasScopeError("atlas scope must be an object")
    row = cast(dict[str, Any], _plain(value))
    _require_exact_fields(row, set(_SCOPE_RECORD_FIELDS), "atlas scope")
    if row.get("type") != ATLAS_SCOPE_TYPE:
        raise AtlasScopeError(f"atlas scope type must be {ATLAS_SCOPE_TYPE}")
    if row.get("schemaVersion") != ATLAS_SCOPE_VERSION:
        raise AtlasScopeError(
            f"atlas scope schemaVersion must be {ATLAS_SCOPE_VERSION}"
        )

    release_values = row.get("releases")
    if (
        not isinstance(release_values, Sequence)
        or isinstance(release_values, (str, bytes))
        or not release_values
    ):
        raise AtlasScopeError("atlas scope releases must be a non-empty array")
    releases = [
        _normalize_scope_release_pin(release, index=index)
        for index, release in enumerate(release_values)
    ]
    release_ids = [cast(str, release["releaseId"]) for release in releases]
    if len(set(release_ids)) != len(release_ids):
        raise AtlasScopeError("atlas scope releases repeat a releaseId")
    release_order = [
        (
            cast(str, release["semanticRing"]),
            cast(str, release["releaseId"]),
        )
        for release in releases
    ]
    if release_order != sorted(release_order):
        raise AtlasScopeError(
            "atlas scope releases must be ordered by semanticRing and releaseId"
        )
    index_row_ids = [
        cast(str, reference["rowId"])
        for release in releases
        for reference in cast(Sequence[Mapping[str, Any]], release["atlasIndexRows"])
    ]
    if len(set(index_row_ids)) != len(index_row_ids):
        raise AtlasScopeError("atlas scope releases reuse an atlasIndex rowId")

    relation_values = row.get("relationBundles")
    if not isinstance(relation_values, Sequence) or isinstance(
        relation_values,
        (str, bytes),
    ):
        raise AtlasScopeError("atlas scope relationBundles must be an array")
    relations = [
        _normalize_scope_relation_pin(relation, index=index)
        for index, relation in enumerate(relation_values)
    ]
    relation_ids = [relation["id"] for relation in relations]
    if len(set(relation_ids)) != len(relation_ids):
        raise AtlasScopeError("atlas scope relationBundles repeat an id")
    if relation_ids != sorted(relation_ids):
        raise AtlasScopeError("atlas scope relationBundles must be ordered by id")

    basis = _scope_basis(
        scope_name=_require_iri(row.get("scopeName"), "atlas scope scopeName"),
        scope_kind=_require_scope_kind(
            row.get("scopeKind"),
            "atlas scope scopeKind",
        ),
        atlas_index_pin=_normalize_atlas_index_pin(row.get("atlasIndex")),
        release_rows=releases,
        relation_rows=relations,
    )
    content_digest = sha256_digest(_canonical_bytes(basis))
    if _require_digest(
        row.get("contentDigest"),
        "atlas scope contentDigest",
    ) != content_digest:
        raise AtlasScopeError("atlas scope contentDigest differs from its content")
    identifier = "urn:ref:vocabulary-atlas-scope:" + content_digest.removeprefix(
        "sha256:"
    )
    if _require_iri(row.get("id"), "atlas scope id") != identifier:
        raise AtlasScopeError("atlas scope id differs from its contentDigest")
    return {
        **basis,
        "id": identifier,
        "contentDigest": content_digest,
    }


@dataclass(frozen=True, slots=True)
class VocabularyAtlasScope:
    """A content-derived exact scope; never publication or use permission."""

    record: Mapping[str, Any]
    _atlas_index: PinnedAtlasIndex
    _releases: tuple[AtlasScopeRelease, ...]
    _relation_bundles: tuple[PinnedRelationAssertionBundle, ...]

    def __post_init__(self) -> None:
        atlas_index_pin, index_rows = _verified_index_snapshot(self._atlas_index)
        releases, release_rows = _normalized_release_rows(
            self._releases,
            index_rows,
        )
        relations, relation_rows = _normalized_relation_rows(
            self._relation_bundles
        )
        _require_relation_release_closure(release_rows, relations)
        if not isinstance(self.record, Mapping):
            raise AtlasScopeError("atlas scope must be an object")
        row = cast(dict[str, Any], _plain(self.record))
        _require_exact_fields(row, set(_SCOPE_RECORD_FIELDS), "atlas scope")
        if (
            row.get("type") != ATLAS_SCOPE_TYPE
            or row.get("schemaVersion") != ATLAS_SCOPE_VERSION
        ):
            raise AtlasScopeError("atlas scope version is unsupported")
        basis = _scope_basis(
            scope_name=_require_iri(
                row.get("scopeName"),
                "atlas scope scopeName",
            ),
            scope_kind=_require_scope_kind(
                row.get("scopeKind"),
                "atlas scope scopeKind",
            ),
            atlas_index_pin=atlas_index_pin,
            release_rows=release_rows,
            relation_rows=relation_rows,
        )
        content_digest = sha256_digest(_canonical_bytes(basis))
        expected = {
            **basis,
            "id": (
                "urn:ref:vocabulary-atlas-scope:"
                + content_digest.removeprefix("sha256:")
            ),
            "contentDigest": content_digest,
        }
        if row != expected:
            raise AtlasScopeError(
                "atlas scope content identity, index bindings, inputs, or "
                "canonical order differs"
            )
        object.__setattr__(
            self,
            "record",
            cast(Mapping[str, Any], deep_freeze_json(expected)),
        )
        object.__setattr__(self, "_releases", releases)
        object.__setattr__(self, "_relation_bundles", relations)

    @classmethod
    def _from_verified_components(
        cls,
        *,
        record: Mapping[str, Any],
        atlas_index: PinnedAtlasIndex,
        releases: tuple[AtlasScopeRelease, ...],
        relation_bundles: tuple[PinnedRelationAssertionBundle, ...],
    ) -> Self:
        """Construct from components verified together in one create call."""

        instance = object.__new__(cls)
        object.__setattr__(
            instance,
            "record",
            cast(Mapping[str, Any], deep_freeze_json(record)),
        )
        object.__setattr__(instance, "_atlas_index", atlas_index)
        object.__setattr__(instance, "_releases", releases)
        object.__setattr__(instance, "_relation_bundles", relation_bundles)
        return instance

    @classmethod
    def create(
        cls,
        *,
        scope_name: str,
        scope_kind: ScopeKind,
        atlas_index: PinnedAtlasIndex,
        releases: Sequence[AtlasScopeRelease],
        relation_bundles: Sequence[PinnedRelationAssertionBundle] = (),
    ) -> Self:
        name = _require_iri(scope_name, "scope_name")
        kind = _require_scope_kind(scope_kind, "scope_kind")
        atlas_index_pin, index_rows = _verified_index_snapshot(atlas_index)
        normalized_releases, release_rows = _normalized_release_rows(
            releases,
            index_rows,
        )
        normalized_relations, relation_rows = _normalized_relation_rows(
            relation_bundles
        )
        _require_relation_release_closure(
            release_rows,
            normalized_relations,
        )
        basis = _scope_basis(
            scope_name=name,
            scope_kind=kind,
            atlas_index_pin=atlas_index_pin,
            release_rows=release_rows,
            relation_rows=relation_rows,
        )
        content_digest = sha256_digest(_canonical_bytes(basis))
        return cls._from_verified_components(
            record={
                **basis,
                "id": (
                    "urn:ref:vocabulary-atlas-scope:"
                    + content_digest.removeprefix("sha256:")
                ),
                "contentDigest": content_digest,
            },
            atlas_index=atlas_index,
            releases=normalized_releases,
            relation_bundles=normalized_relations,
        )

    @classmethod
    def from_record(
        cls,
        value: Mapping[str, Any],
        *,
        atlas_index: PinnedAtlasIndex,
        releases: Sequence[AtlasScopeRelease],
        relation_bundles: Sequence[PinnedRelationAssertionBundle] = (),
    ) -> Self:
        return cls(
            record=value,
            _atlas_index=atlas_index,
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
    def scope_kind(self) -> ScopeKind:
        return cast(ScopeKind, self.record["scopeKind"])

    @property
    def atlas_index(self) -> PinnedAtlasIndex:
        return self._atlas_index

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
            atlas_index=self._atlas_index,
            releases=self._releases,
            relation_bundles=self._relation_bundles,
        )

    def write_to(self, path: Path | str) -> Path:
        destination = Path(path)
        if destination.exists() or destination.is_symlink():
            raise AtlasScopeError(
                f"atlas scope destination already exists: {destination}"
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
class PinnedVocabularyAtlasScope:
    """One exact scope artifact plus every source needed to reopen it."""

    path: Path
    file_digest: str
    scope_id: str
    content_digest: str
    _atlas_index: PinnedAtlasIndex
    _releases: tuple[AtlasScopeRelease, ...]
    _relation_bundles: tuple[PinnedRelationAssertionBundle, ...]
    _scope: VocabularyAtlasScope

    @classmethod
    def open(
        cls,
        path: Path | str,
        *,
        expected_file_digest: str,
        atlas_index: PinnedAtlasIndex,
        releases: Sequence[AtlasScopeRelease],
        relation_bundles: Sequence[PinnedRelationAssertionBundle] = (),
    ) -> Self:
        digest = _require_digest(
            expected_file_digest,
            "atlas scope file digest",
        )
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
            atlas_index=atlas_index,
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
            _atlas_index=atlas_index,
            _releases=scope.releases,
            _relation_bundles=scope.relation_bundles,
            _scope=scope,
        )

    def verified_scope(self) -> VocabularyAtlasScope:
        reopened = self.open(
            self.path,
            expected_file_digest=self.file_digest,
            atlas_index=self._atlas_index,
            releases=self._releases,
            relation_bundles=self._relation_bundles,
        )
        if (
            reopened.scope_id != self.scope_id
            or reopened.content_digest != self.content_digest
        ):
            raise AtlasScopeError(
                "atlas scope identity or content digest changed"
            )
        return reopened._scope

    def pin(self) -> dict[str, str]:
        scope = self.verified_scope()
        return {
            "role": "VocabularyAtlasScope",
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
    "ScopeKind",
    "SubjectParticipation",
    "VocabularyAtlasScope",
    "validate_atlas_scope_record",
]
