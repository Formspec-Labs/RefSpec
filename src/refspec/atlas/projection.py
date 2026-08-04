"""Exact ring and subject-module views of one verified Atlas 2.0 asset.

A projection is a derived distribution, not a second canonical atlas.  Its
identity pins one verified parent and one declarative selector.  The selector
names a semantic ring or one subject specialist source module; it never copies
the release identifiers resolved from that selector.

The projection carries complete canonical records.  It does not slice JSON or
copy one endpoint of a mapping.  A ring view retains every release in that
ring and every closed relation bundle for those releases.  A module view
retains the named specialist module, every subject-core release, and only
relation bundles whose complete endpoint-release set remains in the view.
Evidence and machine-proof records follow their retained relation bundle as a
closed set.
"""

from __future__ import annotations

import importlib.metadata
import platform
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from rdflib import Dataset, URIRef
from typing_extensions import Self

from refspec import binding
from refspec.atlas.model import (
    _COUNT_FIELDS_V2,
    _ROLE_COUNT_FIELD,
    ATLAS_FILE,
    MANIFEST_FILE,
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    _atlas_record_identifier,
    _canonical_bytes,
    _CanonicalAtlasRecord,
    _CanonicalRecordSet,
    _decode_record_dataset,
    _digest_bytes,
    _digest_value,
    _freeze,
    _load_json_object,
    _manifest_digest,
    _plain,
    _read_exact_file,
    _record_dataset,
    _ring_summaries,
    _snapshot_release_records,
    _validate_implementation_v2,
)
from refspec.atlas.relation_assertion import (
    EmbeddedRelationAssertionBundle,
    RelationAssertionError,
)
from refspec.atlas.release_snapshot import (
    AtlasReleaseSnapshot,
    AtlasReleaseSnapshotError,
)

FORMAT_ID = "refspec-vocabulary-atlas-projection-nquads-2.0"
SCHEMA_VERSION = "2.0"
MANIFEST_TYPE = "urn:ref:type:VocabularyAtlasProjectionManifest"
ASSET_ID_PREFIX = "urn:ref:vocabulary-atlas-projection:"
POLICY_VERSION = "1"
_POLICY_PREFIX = "urn:ref:policy:vocabulary-atlas-projection:"

SemanticRing = Literal["subject", "entity", "value", "legalIdentity"]
_RINGS = frozenset({"subject", "entity", "value", "legalIdentity"})
_SOURCE_MODULE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>]+$")

_IMPLEMENTATION_SOURCE_PATHS = tuple(
    sorted(
        {
            "atlas/model.py",
            "atlas/projection.py",
            "atlas/relation_assertion.py",
            "atlas/release_snapshot.py",
            "binding.py",
            "storage.py",
        }
    )
)
_MANIFEST_FIELDS = frozenset(
    {
        "id",
        "type",
        "schemaVersion",
        "format",
        "projectionDigest",
        "derivedFrom",
        "projectionPolicy",
        "implementation",
        "graphs",
        "output",
        "counts",
        "rings",
        "canonicalPayloadDigest",
    }
)

_PROJECTION_CONSTRUCTION_TOKEN = object()


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise VocabularyAtlasError(f"{label} must be non-empty trimmed text")
    return value


def _require_digest(value: object, label: str) -> str:
    result = _require_text(value, label)
    if _SHA256.fullmatch(result) is None:
        raise VocabularyAtlasError(f"{label} must be sha256:<64 lowercase hex>")
    return result


def _require_iri(value: object, label: str) -> str:
    result = _require_text(value, label)
    if _ABSOLUTE_IRI.fullmatch(result) is None:
        raise VocabularyAtlasError(f"{label} must be an absolute IRI")
    return result


def _require_count(value: object, label: str, *, positive: bool = False) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < (1 if positive else 0)
        or value > binding.SAFE_INTEGER
    ):
        qualifier = "positive" if positive else "non-negative"
        raise VocabularyAtlasError(f"{label} must be a {qualifier} safe integer")
    return value


def ring_projection_policy(semantic_ring: SemanticRing) -> dict[str, Any]:
    """Return the complete registered selector for one semantic ring."""

    if semantic_ring not in _RINGS:
        raise VocabularyAtlasError("ring projection semanticRing is unsupported")
    return {
        "id": f"{_POLICY_PREFIX}ring:{semantic_ring}",
        "version": POLICY_VERSION,
        "selectors": {"semanticRing": semantic_ring},
    }


def module_projection_policy(source_module: str) -> dict[str, Any]:
    """Return the complete selector for one subject specialist module."""

    source_module = _require_text(source_module, "module projection sourceModule")
    if _SOURCE_MODULE.fullmatch(source_module) is None:
        raise VocabularyAtlasError("module projection sourceModule must be a dotted Python module")
    return {
        "id": f"{_POLICY_PREFIX}module:{source_module}",
        "version": POLICY_VERSION,
        "selectors": {"sourceModule": source_module},
    }


def _registered_policy(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "id",
        "version",
        "selectors",
    }:
        raise VocabularyAtlasError("atlas projection policy fields differ from 2.0")
    identifier = _require_text(value.get("id"), "atlas projection policy id")
    if value.get("version") != POLICY_VERSION:
        raise VocabularyAtlasError("atlas projection policy version is unsupported")
    selectors = value.get("selectors")
    if not isinstance(selectors, Mapping):
        raise VocabularyAtlasError("atlas projection policy selectors must be an object")

    if identifier.startswith(f"{_POLICY_PREFIX}ring:"):
        ring = identifier.removeprefix(f"{_POLICY_PREFIX}ring:")
        expected = ring_projection_policy(cast(SemanticRing, ring))
    elif identifier.startswith(f"{_POLICY_PREFIX}module:"):
        source_module = identifier.removeprefix(f"{_POLICY_PREFIX}module:")
        expected = module_projection_policy(source_module)
    else:
        raise VocabularyAtlasError("atlas projection policy is unregistered")
    if _plain(value) != expected:
        raise VocabularyAtlasError("atlas projection policy selectors differ from the named policy")
    return cast(Mapping[str, Any], _freeze(expected))


def _implementation_pin() -> dict[str, Any]:
    package_root = Path(__file__).parents[1]
    return {
        "id": "urn:ref:implementation:vocabulary-atlas-projection:2.0",
        "version": "2.0",
        "sourceModules": [
            {
                "path": f"refspec/{relative}",
                "digest": _digest_bytes((package_root / relative).read_bytes()),
            }
            for relative in _IMPLEMENTATION_SOURCE_PATHS
        ],
        "runtime": {
            "jsonschemaVersion": importlib.metadata.version("jsonschema"),
            "pythonRequirement": ">=3.10",
            "pythonVersion": platform.python_version(),
            "rdflibVersion": importlib.metadata.version("rdflib"),
        },
    }


def _parent_pin(parent: VocabularyAtlasAsset) -> dict[str, str]:
    parent._require_verified()
    return {
        "assetId": _require_iri(parent.manifest.get("id"), "atlas parent id"),
        "manifestDigest": parent.manifest_digest,
        "distributionDigest": parent.output_digest,
    }


def _validate_parent_pin(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {
        "assetId",
        "manifestDigest",
        "distributionDigest",
    }:
        raise VocabularyAtlasError("atlas projection derivedFrom fields differ from 2.0")
    return {
        "assetId": _require_iri(value.get("assetId"), "atlas projection parent id"),
        "manifestDigest": _require_digest(value.get("manifestDigest"), "atlas projection parent manifest digest"),
        "distributionDigest": _require_digest(
            value.get("distributionDigest"),
            "atlas projection parent distribution digest",
        ),
    }


@dataclass(frozen=True, slots=True)
class _ReleaseClassification:
    semantic_ring: SemanticRing
    participation: str | None
    source_module: str
    resource_id: str


@dataclass(frozen=True, slots=True)
class _ProjectionRecordView:
    snapshots: tuple[AtlasReleaseSnapshot, ...]
    relations: tuple[EmbeddedRelationAssertionBundle, ...]
    classifications: Mapping[str, _ReleaseClassification]


def _index_row_classification(
    row: Mapping[str, Any],
    *,
    snapshot: AtlasReleaseSnapshot,
) -> _ReleaseClassification:
    required = {
        "assignmentRole",
        "facet",
        "intendedUses",
        "planningStatus",
        "readinessEvidence",
        "release",
        "resourceId",
        "rowDigest",
        "rowId",
        "semanticRing",
        "sourceModule",
    }
    if set(row) not in (required, required | {"atlasParticipation"}):
        raise VocabularyAtlasError("atlas projection index-row fields differ")
    row_id = _require_iri(row.get("rowId"), "atlas projection index-row id")
    row_digest = _require_digest(row.get("rowDigest"), "atlas projection index-row digest")
    basis = {key: _plain(item) for key, item in row.items() if key not in {"rowId", "rowDigest"}}
    basis.setdefault("atlasParticipation", None)
    if binding.canonical_sha256(basis) != row_digest or row_id != "urn:ref:atlas-index-row:" + row_digest.removeprefix(
        "sha256:"
    ):
        raise VocabularyAtlasError("atlas projection index-row identity is stale")

    release = row.get("release")
    if not isinstance(release, Mapping):
        raise VocabularyAtlasError("atlas projection index row lacks an exact release")
    if (
        release.get("releaseId") != snapshot.release_id
        or release.get("manifestDigest") != snapshot.release_pin.get("manifestDigest")
        or row.get("semanticRing") != snapshot.semantic_ring
    ):
        raise VocabularyAtlasError("atlas projection index row differs from its contained release")
    participation = row.get("atlasParticipation")
    if participation not in {None, "core", "specialist", "bridge"}:
        raise VocabularyAtlasError("atlas projection index-row participation is unsupported")
    source_module = _require_text(row.get("sourceModule"), "atlas projection index-row sourceModule")
    if _SOURCE_MODULE.fullmatch(source_module) is None:
        raise VocabularyAtlasError("atlas projection index-row sourceModule is malformed")
    return _ReleaseClassification(
        semantic_ring=cast(SemanticRing, snapshot.semantic_ring),
        participation=cast(str | None, participation),
        source_module=source_module,
        resource_id=_require_text(row.get("resourceId"), "atlas projection index-row resourceId"),
    )


def _projection_record_view(
    records: Sequence[_CanonicalAtlasRecord],
) -> _ProjectionRecordView:
    """Verify the selected-record and relation closure without the parent."""

    try:
        snapshots = tuple(
            AtlasReleaseSnapshot.from_record(record.record) for record in records if record.role == "conceptRelease"
        )
    except AtlasReleaseSnapshotError as error:
        raise VocabularyAtlasError(str(error)) from error
    if not snapshots:
        raise VocabularyAtlasError("atlas projection contains no concept release")
    snapshots_by_release = {snapshot.release_id: snapshot for snapshot in snapshots}
    if len(snapshots_by_release) != len(snapshots):
        raise VocabularyAtlasError("atlas projection repeats a concept release")

    classifications: dict[str, _ReleaseClassification] = {}
    memberships: dict[str, frozenset[str]] = {}
    for release_id, snapshot in snapshots_by_release.items():
        memberships[release_id] = snapshot.member_ids
        expected_concepts = {_atlas_record_identifier(value) for value in snapshot.concept_records}
        actual_concepts = {
            record.identifier
            for record in records
            if record.role == "concept" and release_id in record.release_containers
        }
        if actual_concepts != expected_concepts:
            raise VocabularyAtlasError("atlas projection concepts differ from their release snapshot")

        native_release_records = {_atlas_record_identifier(value) for value in _snapshot_release_records(snapshot)}
        contained_release_records = tuple(
            record for record in records if record.role == "releaseRecord" and release_id in record.release_containers
        )
        index_records = tuple(record for record in contained_release_records if "rowId" in record.record)
        if not index_records:
            raise VocabularyAtlasError("atlas projection release lacks its resolved index-row facts")
        release_classifications = {
            _index_row_classification(record.record, snapshot=snapshot) for record in index_records
        }
        if len(release_classifications) != 1:
            raise VocabularyAtlasError("atlas projection index rows conflict on release classification")
        classifications[release_id] = release_classifications.pop()
        expected_release_records = native_release_records | {record.identifier for record in index_records}
        if {record.identifier for record in contained_release_records} != expected_release_records:
            raise VocabularyAtlasError("atlas projection release-record closure differs")

    relation_records = tuple(record for record in records if record.role == "relationBundle")
    relations: list[EmbeddedRelationAssertionBundle] = []
    for record in relation_records:
        raw_pins = record.record.get("releasePins")
        if not isinstance(raw_pins, Sequence) or isinstance(raw_pins, (str, bytes)):
            raise VocabularyAtlasError("atlas projection relation releasePins are invalid")
        release_ids = tuple(cast(str, pin.get("releaseId")) for pin in raw_pins if isinstance(pin, Mapping))
        if len(release_ids) != len(raw_pins) or any(release_id not in memberships for release_id in release_ids):
            raise VocabularyAtlasError("atlas projection relation has an endpoint release outside the projection")
        try:
            relation = EmbeddedRelationAssertionBundle.from_record(
                record.record,
                release_memberships={release_id: memberships[release_id] for release_id in release_ids},
            )
        except RelationAssertionError as error:
            raise VocabularyAtlasError(str(error)) from error
        relations.append(relation)
        expected_by_role = {
            "evidenceAssertion": {
                _atlas_record_identifier(value.as_record()) for value in relation.evidence_assertions
            },
            "mappingAssertion": {_atlas_record_identifier(value.as_record()) for value in relation.mapping_assertions},
            "machineProof": {_atlas_record_identifier(value) for value in relation.machine_proof_pins},
        }
        for role, expected in expected_by_role.items():
            actual = {
                child.identifier
                for child in records
                if child.role == role and relation.identifier in child.relation_containers
            }
            if actual != expected:
                raise VocabularyAtlasError(f"atlas projection {role} closure differs from its relation bundle")

    relation_ids = {relation.identifier for relation in relations}
    if len(relation_ids) != len(relations):
        raise VocabularyAtlasError("atlas projection repeats a relation bundle")
    for record in records:
        if (
            record.role in {"evidenceAssertion", "mappingAssertion", "machineProof"}
            and not record.relation_containers <= relation_ids
        ):
            raise VocabularyAtlasError("atlas projection relation child names an absent relation bundle")
    return _ProjectionRecordView(
        snapshots=snapshots,
        relations=tuple(relations),
        classifications=cast(Mapping[str, _ReleaseClassification], _freeze(classifications)),
    )


def _selected_release_ids(
    view: _ProjectionRecordView,
    policy: Mapping[str, Any],
) -> frozenset[str]:
    identifier = cast(str, policy["id"])
    if identifier.startswith(f"{_POLICY_PREFIX}ring:"):
        ring = identifier.removeprefix(f"{_POLICY_PREFIX}ring:")
        selected = {snapshot.release_id for snapshot in view.snapshots if snapshot.semantic_ring == ring}
        if not selected:
            raise VocabularyAtlasError(f"atlas projection policy {identifier} selects no release")
        return frozenset(selected)

    source_module = cast(str, policy["selectors"]["sourceModule"])
    specialist = {
        release_id
        for release_id, row in view.classifications.items()
        if row.semantic_ring == "subject" and row.participation == "specialist" and row.source_module == source_module
    }
    if not specialist:
        raise VocabularyAtlasError("module projection must name a subject specialist module in its parent")
    core = {
        release_id
        for release_id, row in view.classifications.items()
        if row.semantic_ring == "subject" and row.participation == "core"
    }
    return frozenset(core | specialist)


def _selected_relation_ids(
    view: _ProjectionRecordView,
    *,
    release_ids: frozenset[str],
) -> frozenset[str]:
    return frozenset(
        relation.identifier
        for relation in view.relations
        if {cast(str, pin["releaseId"]) for pin in relation.release_pins} <= release_ids
    )


def _project_records(
    records: Sequence[_CanonicalAtlasRecord],
    *,
    view: _ProjectionRecordView,
    policy: Mapping[str, Any],
) -> tuple[_CanonicalAtlasRecord, ...]:
    release_ids = _selected_release_ids(view, policy)
    relation_ids = _selected_relation_ids(view, release_ids=release_ids)
    snapshot_release = {
        _atlas_record_identifier(snapshot.as_record()): snapshot.release_id for snapshot in view.snapshots
    }
    relation_bundle = {_atlas_record_identifier(relation.record): relation.identifier for relation in view.relations}

    selected = _CanonicalRecordSet()
    for record in records:
        if record.role == "conceptRelease":
            if snapshot_release[record.identifier] in release_ids:
                selected.add(record.record, role=record.role)
        elif record.role in {"concept", "releaseRecord"}:
            for release_id in sorted(record.release_containers & release_ids):
                selected.add(
                    record.record,
                    role=record.role,
                    in_release=release_id,
                )
        elif record.role == "relationBundle":
            if relation_bundle[record.identifier] in relation_ids:
                selected.add(record.record, role=record.role)
        else:
            for relation_id in sorted(record.relation_containers & relation_ids):
                selected.add(
                    record.record,
                    role=record.role,
                    in_relation_bundle=relation_id,
                )
    result = selected.values()
    selected_view = _projection_record_view(result)
    if {snapshot.release_id for snapshot in selected_view.snapshots} != release_ids:
        raise VocabularyAtlasError("atlas projection release selection is incomplete")
    if {relation.identifier for relation in selected_view.relations} != relation_ids:
        raise VocabularyAtlasError("atlas projection relation selection is incomplete")
    return result


def _graph_ids(asset_id: str) -> dict[str, str]:
    return {
        "releaseFacts": asset_id + ":release-facts",
        "crossRelease": asset_id + ":cross-release",
    }


def _read_projection_distribution(
    directory: Path | str,
) -> tuple[Path, dict[str, bytes]]:
    root = Path(directory)
    if root.is_symlink():
        raise VocabularyAtlasError("atlas projection directory must not be a symlink")
    try:
        root = root.resolve(strict=True)
    except FileNotFoundError as error:
        raise VocabularyAtlasError("atlas projection directory does not exist") from error
    if not root.is_dir():
        raise VocabularyAtlasError("atlas projection path must be a directory")
    expected = {ATLAS_FILE, MANIFEST_FILE}
    entries = {item.name: item for item in root.iterdir()}
    if set(entries) != expected:
        raise VocabularyAtlasError("atlas projection file set differs from 2.0")
    if any(item.is_symlink() or not item.is_file() for item in entries.values()):
        raise VocabularyAtlasError("atlas projection must contain two regular files and no symlinks")
    payloads = {name: entries[name].read_bytes() for name in expected}
    final_entries = {item.name: item for item in root.iterdir()}
    if (
        set(final_entries) != expected
        or any(item.is_symlink() or not item.is_file() for item in final_entries.values())
        or any(final_entries[name].read_bytes() != payloads[name] for name in expected)
    ):
        raise VocabularyAtlasError("atlas projection changed while opening")
    return root, payloads


@dataclass(frozen=True, slots=True, init=False)
class VocabularyAtlasProjection:
    """A verified derived view of one canonical Atlas 2.0 distribution."""

    payload: bytes
    manifest: Mapping[str, Any]
    _verification_token: object

    def __init__(
        self,
        payload: bytes,
        manifest: Mapping[str, Any],
        *,
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _PROJECTION_CONSTRUCTION_TOKEN:
            raise TypeError(
                "VocabularyAtlasProjection must come from build_atlas_projection() or VocabularyAtlasProjection.open()"
            )
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(self, "_verification_token", _PROJECTION_CONSTRUCTION_TOKEN)

    @classmethod
    def _verified(cls, *, payload: bytes, manifest: Mapping[str, Any]) -> Self:
        return cls(
            payload,
            manifest,
            _construction_token=_PROJECTION_CONSTRUCTION_TOKEN,
        )

    def _require_verified(self) -> None:
        if (
            getattr(self, "_verification_token", None) is not _PROJECTION_CONSTRUCTION_TOKEN
            or not isinstance(self.payload, bytes)
            or not isinstance(self.manifest, Mapping)
        ):
            raise VocabularyAtlasError("atlas projection is not verified")

    def manifest_bytes(self) -> bytes:
        self._require_verified()
        return _canonical_bytes(_plain(self.manifest))

    @property
    def manifest_digest(self) -> str:
        return _digest_bytes(self.manifest_bytes())

    @property
    def output_digest(self) -> str:
        self._require_verified()
        return _digest_bytes(self.payload)

    @property
    def parent_pin(self) -> dict[str, str]:
        self._require_verified()
        return cast(dict[str, str], _plain(self.manifest["derivedFrom"]))

    def write(self, directory: Path | str) -> Path:
        self._require_verified()
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=False)
        (target / ATLAS_FILE).write_bytes(self.payload)
        (target / MANIFEST_FILE).write_bytes(self.manifest_bytes())
        return target

    @classmethod
    def open(
        cls,
        directory: Path | str,
        *,
        expected_manifest_digest: str,
    ) -> Self:
        """Verify the two-file projection from one trusted manifest digest."""

        _, payloads = _read_projection_distribution(directory)
        expected_digest = _require_digest(
            expected_manifest_digest,
            "expected atlas projection manifest digest",
        )
        manifest_payload = payloads[MANIFEST_FILE]
        if _digest_bytes(manifest_payload) != expected_digest:
            raise VocabularyAtlasError("atlas projection external manifest digest differs")
        manifest = _load_json_object(manifest_payload, "atlas projection manifest")
        if _canonical_bytes(manifest) != manifest_payload:
            raise VocabularyAtlasError("atlas projection manifest bytes are not canonical")
        if set(manifest) != _MANIFEST_FIELDS:
            raise VocabularyAtlasError("atlas projection manifest fields differ from 2.0")
        if (
            manifest.get("type") != MANIFEST_TYPE
            or manifest.get("schemaVersion") != SCHEMA_VERSION
            or manifest.get("format") != FORMAT_ID
        ):
            raise VocabularyAtlasError("atlas projection version or format differs")
        projection_digest = _require_digest(manifest.get("projectionDigest"), "atlas projection projectionDigest")
        asset_id = _require_iri(manifest.get("id"), "atlas projection id")
        if asset_id != ASSET_ID_PREFIX + projection_digest.removeprefix("sha256:"):
            raise VocabularyAtlasError("atlas projection id differs from projectionDigest")
        if manifest.get("canonicalPayloadDigest") != _manifest_digest(manifest):
            raise VocabularyAtlasError("atlas projection canonicalPayloadDigest differs")
        parent_pin = _validate_parent_pin(manifest.get("derivedFrom"))
        policy = _registered_policy(manifest.get("projectionPolicy"))
        implementation = _validate_implementation_v2(manifest.get("implementation"))
        basis = {
            "format": FORMAT_ID,
            "derivedFrom": parent_pin,
            "projectionPolicy": _plain(policy),
            "implementation": _plain(implementation),
        }
        if _digest_value(basis) != projection_digest:
            raise VocabularyAtlasError("atlas projection projectionDigest differs")
        if asset_id == parent_pin["assetId"]:
            raise VocabularyAtlasError("atlas projection id collides with its parent")

        graph_ids = _graph_ids(asset_id)
        graph_rows = manifest.get("graphs")
        if not isinstance(graph_rows, Sequence) or isinstance(graph_rows, (str, bytes)) or len(graph_rows) != 2:
            raise VocabularyAtlasError("atlas projection must declare exactly two named graphs")
        expected_graphs = (
            ("releaseFacts", graph_ids["releaseFacts"], True),
            ("crossRelease", graph_ids["crossRelease"], False),
        )
        for position, (role, graph_id, positive) in enumerate(expected_graphs):
            row = graph_rows[position]
            if not isinstance(row, Mapping) or set(row) != {
                "role",
                "id",
                "quadCount",
            }:
                raise VocabularyAtlasError("atlas projection graph fields differ")
            if row.get("role") != role or row.get("id") != graph_id:
                raise VocabularyAtlasError("atlas projection graph role or id differs")
            _require_count(
                row.get("quadCount"),
                f"atlas projection {role} quadCount",
                positive=positive,
            )

        payload = payloads[ATLAS_FILE]
        output = manifest.get("output")
        if not isinstance(output, Mapping) or set(output) != {
            "path",
            "mediaType",
            "digest",
            "byteLength",
            "quadCount",
        }:
            raise VocabularyAtlasError("atlas projection output fields differ")
        if output.get("path") != ATLAS_FILE or output.get("mediaType") != "application/n-quads":
            raise VocabularyAtlasError("atlas projection output descriptor differs")
        if output.get("digest") != _digest_bytes(payload):
            raise VocabularyAtlasError("atlas projection output digest differs")
        if output.get("byteLength") != len(payload):
            raise VocabularyAtlasError("atlas projection output byteLength differs")
        _require_count(
            output.get("quadCount"),
            "atlas projection output quadCount",
            positive=True,
        )

        records = _decode_record_dataset(payload, asset_id=asset_id)
        view = _projection_record_view(records)
        actual_release_ids = frozenset(snapshot.release_id for snapshot in view.snapshots)
        if _selected_release_ids(view, policy) != actual_release_ids:
            raise VocabularyAtlasError("atlas projection records differ from its policy selector")
        for relation in view.relations:
            if not {cast(str, pin["releaseId"]) for pin in relation.release_pins} <= actual_release_ids:
                raise VocabularyAtlasError("atlas projection contains a one-ended relation")

        observed_counts = {
            count_field: sum(record.role == role for record in records)
            for role, count_field in _ROLE_COUNT_FIELD.items()
        }
        counts = manifest.get("counts")
        if not isinstance(counts, Mapping) or set(counts) != _COUNT_FIELDS_V2:
            raise VocabularyAtlasError("atlas projection count fields differ")
        for field in _COUNT_FIELDS_V2:
            _require_count(
                counts.get(field),
                f"atlas projection counts.{field}",
                positive=field in {"conceptReleases", "concepts", "releaseRecords"},
            )
        if dict(counts) != observed_counts:
            raise VocabularyAtlasError("atlas projection record counts differ")

        dataset = Dataset(default_union=False)
        dataset.parse(data=payload.decode("utf-8"), format="nquads")
        graph_counts = {role: len(dataset.graph(URIRef(graph_id))) for role, graph_id, _ in expected_graphs}
        for position, (role, _, _) in enumerate(expected_graphs):
            if cast(Mapping[str, Any], graph_rows[position]).get("quadCount") != graph_counts[role]:
                raise VocabularyAtlasError("atlas projection graph quadCount differs")
        if output.get("quadCount") != sum(graph_counts.values()):
            raise VocabularyAtlasError("atlas projection output quadCount differs")
        if manifest.get("rings") != _ring_summaries(
            records,
            snapshots=view.snapshots,
            relations=view.relations,
        ):
            raise VocabularyAtlasError("atlas projection ring summaries differ")
        return cls._verified(
            payload=payload,
            manifest=cast(Mapping[str, Any], _freeze(manifest)),
        )

    @classmethod
    def reproduce_from_parent(
        cls,
        directory: Path | str,
        *,
        parent: VocabularyAtlasAsset,
        expected_manifest_digest: str,
    ) -> Self:
        """Rebuild the projection from the verified parent named in it."""

        parent._require_verified()
        opened = cls.open(
            directory,
            expected_manifest_digest=expected_manifest_digest,
        )
        if opened.parent_pin != _parent_pin(parent):
            raise VocabularyAtlasError("atlas projection names another verified parent distribution")
        rebuilt = build_atlas_projection(
            parent,
            policy=_registered_policy(opened.manifest["projectionPolicy"]),
        )
        if rebuilt.manifest != opened.manifest or rebuilt.payload != opened.payload:
            raise VocabularyAtlasError("atlas projection does not reproduce from its verified parent")
        return opened


def build_atlas_projection(
    parent: VocabularyAtlasAsset,
    *,
    policy: Mapping[str, Any],
) -> VocabularyAtlasProjection:
    """Build one exact record projection from a verified canonical parent."""

    if not isinstance(parent, VocabularyAtlasAsset):
        raise VocabularyAtlasError("atlas projection requires one verified VocabularyAtlasAsset parent")
    parent._require_verified()
    registered = _registered_policy(policy)
    parent_id = _require_iri(parent.manifest.get("id"), "atlas parent id")
    records = _decode_record_dataset(parent.payload, asset_id=parent_id)
    parent_view = _projection_record_view(records)
    projected_records = _project_records(
        records,
        view=parent_view,
        policy=registered,
    )
    projected_view = _projection_record_view(projected_records)

    derived_from = _parent_pin(parent)
    implementation = _implementation_pin()
    projection_basis = {
        "format": FORMAT_ID,
        "derivedFrom": derived_from,
        "projectionPolicy": _plain(registered),
        "implementation": implementation,
    }
    projection_digest = _digest_value(projection_basis)
    asset_id = ASSET_ID_PREFIX + projection_digest.removeprefix("sha256:")
    payload, observed = _record_dataset(projected_records, asset_id=asset_id)
    counts = {field: observed[field] for field in _COUNT_FIELDS_V2}
    graph_ids = _graph_ids(asset_id)
    graphs = [
        {
            "role": "releaseFacts",
            "id": graph_ids["releaseFacts"],
            "quadCount": observed["releaseFacts"],
        },
        {
            "role": "crossRelease",
            "id": graph_ids["crossRelease"],
            "quadCount": observed["crossRelease"],
        },
    ]
    manifest: dict[str, Any] = {
        "id": asset_id,
        "type": MANIFEST_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "format": FORMAT_ID,
        "projectionDigest": projection_digest,
        "derivedFrom": derived_from,
        "projectionPolicy": _plain(registered),
        "implementation": implementation,
        "graphs": graphs,
        "output": {
            "path": ATLAS_FILE,
            "mediaType": "application/n-quads",
            "digest": _digest_bytes(payload),
            "byteLength": len(payload),
            "quadCount": observed["releaseFacts"] + observed["crossRelease"],
        },
        "counts": counts,
        "rings": _ring_summaries(
            projected_records,
            snapshots=projected_view.snapshots,
            relations=projected_view.relations,
        ),
    }
    manifest["canonicalPayloadDigest"] = _manifest_digest(manifest)
    return VocabularyAtlasProjection._verified(
        payload=payload,
        manifest=cast(Mapping[str, Any], _freeze(manifest)),
    )


def distribution_kind(directory: Path | str) -> str:
    """Name a canonical atlas or projection without treating one as the other."""

    _, manifest_bytes = _read_exact_file(
        Path(directory) / MANIFEST_FILE,
        "atlas distribution manifest",
    )
    manifest = _load_json_object(manifest_bytes, "atlas distribution manifest")
    if manifest.get("type") == MANIFEST_TYPE:
        return "vocabularyAtlasProjection"
    if manifest.get("type") == "urn:ref:type:VocabularyAtlasManifest":
        return "vocabularyAtlas"
    raise VocabularyAtlasError("distribution is neither an atlas nor a projection")


__all__ = [
    "ASSET_ID_PREFIX",
    "FORMAT_ID",
    "MANIFEST_TYPE",
    "POLICY_VERSION",
    "SCHEMA_VERSION",
    "SemanticRing",
    "VocabularyAtlasProjection",
    "build_atlas_projection",
    "distribution_kind",
    "module_projection_policy",
    "ring_projection_policy",
]
