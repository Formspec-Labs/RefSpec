#!/usr/bin/env python3
"""Build and verify one ELSST R6 Atlas 2.0 native-relation bench.

The input is an exact RefSpec managed release that has already passed the
pinned Rulespec gate. This tool does not reinterpret ELSST or call Rulespec.
It selects the exact ELSST release, builds the canonical Atlas, publishes a
bounded offline explorer, and verifies that ELSST's native SKOS assertions are
preserved separately from cross-release mappings.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from refspec import binding
from refspec.atlas.atlas_scope import (
    AtlasScopeRelease,
    PinnedVocabularyAtlasScope,
    VocabularyAtlasScope,
)
from refspec.atlas.concept_release import (
    ManagedReleaseRingAssignment,
    PinnedManagedConceptRelease,
    PinnedManagedReleaseRingAssignment,
)
from refspec.atlas.model import VocabularyAtlasAsset, build_vocabulary_atlas
from refspec.atlas.publication import (
    EXPLORER_DATA,
    PUBLICATION_MANIFEST,
    AtlasPublication,
    publish_vocabulary_atlas,
)
from refspec.atlas.publication_decision import (
    VocabularyAtlasPublicationDecision,
    build_vocabulary_atlas_publication_decision,
    read_vocabulary_atlas_publication_decision,
)
from refspec.atlas.queries import VocabularyAtlasQueries
from refspec.atlas_index import PinnedAtlasIndex, build_atlas_index
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)

ELSST_RELEASE_ID = "https://elsst.cessda.eu/id/6"
SKOS_BROADER = "http://www.w3.org/2004/02/skos/core#broader"
SKOS_NARROWER = "http://www.w3.org/2004/02/skos/core#narrower"
SKOS_RELATED = "http://www.w3.org/2004/02/skos/core#related"

DEFAULT_INPUT = ROOT / "output" / "elsst-r6-atlas2-bench-input-2026-08-04"
DEFAULT_CONTROL = ROOT / "output" / "decisions" / "refspec-atlas-2.0-elsst-r6-native-relations-bench-2026-08-04"
DEFAULT_ATLAS = ROOT / "output" / "atlas-2.0-elsst-r6-native-relations-bench-2026-08-04"
DEFAULT_PUBLICATION = ROOT / "output" / "publications" / "refspec-atlas-2.0-elsst-r6-native-relations-bench-2026-08-04"
DEFAULT_SCOPE_NAME = "urn:ref:scope:elsst-r6-native-relations-bench:2026-08-04"
DEFAULT_TITLE = "RefSpec Atlas 2.0 - ELSST R6 native relationships (bench)"


class ElsstAtlasBenchError(ValueError):
    """The ELSST Atlas bench input, output, or verification is invalid."""


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--managed-release",
        type=Path,
        default=DEFAULT_INPUT / "managed-release" / "managed-release-bundle.json",
    )
    parser.add_argument("--managed-manifest-digest", required=True)
    parser.add_argument(
        "--rebuild-report",
        type=Path,
        default=DEFAULT_INPUT / "rebuild-result.json",
    )
    parser.add_argument(
        "--atlas-index-input",
        type=Path,
        default=ROOT / "portfolio" / "atlas-index-input-v0.json",
    )
    parser.add_argument(
        "--resource-catalog",
        type=Path,
        default=ROOT / "portfolio" / "resource-catalog-v0.json",
    )
    parser.add_argument("--control-output", type=Path, default=DEFAULT_CONTROL)
    parser.add_argument("--atlas-output", type=Path, default=DEFAULT_ATLAS)
    parser.add_argument(
        "--publication-output",
        type=Path,
        default=DEFAULT_PUBLICATION,
    )
    parser.add_argument("--release-id", default=ELSST_RELEASE_ID)
    parser.add_argument("--scope-name", default=DEFAULT_SCOPE_NAME)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--decided-at", required=True)
    parser.add_argument(
        "--decision-actor",
        default="urn:ref:actor:local-workspace-user",
    )
    parser.add_argument("--max-concepts", type=int, default=640)
    parser.add_argument("--max-mapping-assertions", type=int, default=240)
    return parser.parse_args()


def _load_json(path: Path, *, label: str) -> Any:
    try:
        return json.loads(
            path.read_bytes().decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ElsstAtlasBenchError(f"cannot read {label}: {error}") from error


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ElsstAtlasBenchError(f"{label} must be an object")
    return cast(dict[str, Any], plain_json(value))


def _repository_path(path: Path, *, label: str, must_exist: bool = True) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    if candidate.is_symlink():
        raise ElsstAtlasBenchError(f"{label} must not be a symlink")
    try:
        resolved = candidate.resolve(strict=must_exist)
        resolved.relative_to(ROOT.resolve(strict=True))
    except (FileNotFoundError, ValueError) as error:
        raise ElsstAtlasBenchError(f"{label} must be inside the repository") from error
    if must_exist and (resolved.is_symlink() or not resolved.is_file()):
        raise ElsstAtlasBenchError(f"{label} must be a regular file")
    return resolved


def _output_path(path: Path, *, label: str) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    if candidate.is_symlink():
        raise ElsstAtlasBenchError(f"{label} must not be a symlink")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(ROOT.resolve(strict=True))
    except ValueError as error:
        raise ElsstAtlasBenchError(f"{label} must be inside the repository") from error
    return resolved


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve(strict=True)).as_posix()


def _ensure_file(path: Path, payload: bytes, *, label: str) -> Path:
    """Create exact bytes once, or verify an identical resumable artifact."""

    if path.is_symlink():
        raise ElsstAtlasBenchError(f"{label} must not be a symlink")
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise ElsstAtlasBenchError(f"existing {label} differs from this run")
        return path.resolve(strict=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
        if path.exists() or path.is_symlink():
            raise ElsstAtlasBenchError(f"{label} appeared while writing")
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path.resolve(strict=True)


def _policy_pin(role: str, policy: Mapping[str, Any]) -> dict[str, str]:
    return {
        "role": role,
        "id": cast(str, policy["id"]),
        "version": cast(str, policy["version"]),
        "contentDigest": sha256_digest(canonical_json_bytes(policy)),
    }


def _replace_elsst_index_row(
    source: Mapping[str, Any],
    *,
    evidence_path: str,
    manifest_digest: str,
    release_id: str,
    recorded_at: str,
) -> dict[str, Any]:
    result = _mapping(source, label="atlas index input")
    rows = result.get("rows")
    if not isinstance(rows, list):
        raise ElsstAtlasBenchError("atlas index input rows must be an array")
    matches = [row for row in rows if isinstance(row, dict) and row.get("resourceId") == "elsst"]
    if len(matches) != 1:
        raise ElsstAtlasBenchError("atlas index input must contain exactly one ELSST row")
    row = matches[0]
    readiness = row.get("readinessEvidence")
    if not isinstance(readiness, list):
        raise ElsstAtlasBenchError("ELSST readinessEvidence must be an array")
    managed_rows = [
        item for item in readiness if isinstance(item, dict) and item.get("kind") == "managedReleaseValidation"
    ]
    if len(managed_rows) != 1:
        raise ElsstAtlasBenchError("ELSST readinessEvidence must contain one managedReleaseValidation row")
    managed_rows[0]["path"] = evidence_path
    row["release"] = {
        "evidencePath": evidence_path,
        "manifestDigest": manifest_digest,
        "releaseId": release_id,
    }
    result["recordedAt"] = recorded_at
    return result


def _verified_publication(
    path: Path,
    *,
    atlas: VocabularyAtlasAsset,
    title: str,
    max_concepts: int,
    max_mapping_assertions: int,
    decision: VocabularyAtlasPublicationDecision,
) -> AtlasPublication:
    if path.exists() or path.is_symlink():
        manifest_path = path / PUBLICATION_MANIFEST
        manifest_digest = sha256_digest(manifest_path.read_bytes())
        publication = AtlasPublication.open(
            path,
            expected_manifest_digest=manifest_digest,
        )
        explorer = _mapping(
            _load_json(path / EXPLORER_DATA, label="existing atlas explorer"),
            label="existing atlas explorer",
        )
        selection = _mapping(
            explorer.get("selectionPolicy"),
            label="existing atlas explorer selectionPolicy",
        )
        if (
            explorer.get("title") != title
            or selection.get("maxConcepts") != max_concepts
            or selection.get("maxMappingAssertions") != max_mapping_assertions
            or publication.distribution.manifest_digest != atlas.manifest_digest
            or publication.decision.reference != decision.reference
        ):
            raise ElsstAtlasBenchError("existing publication differs from this run")
        return publication
    return publish_vocabulary_atlas(
        atlas,
        path,
        decision=decision,
        title=title,
        release_labels={ELSST_RELEASE_ID: "ELSST R6"},
        max_concepts=max_concepts,
        max_mapping_assertions=max_mapping_assertions,
    )


def build(args: argparse.Namespace) -> dict[str, Any]:
    if args.release_id != ELSST_RELEASE_ID:
        raise ElsstAtlasBenchError(f"this ELSST R6 builder requires release id {ELSST_RELEASE_ID}")
    managed_manifest = _repository_path(
        args.managed_release,
        label="managed release manifest",
    )
    rebuild_report_path = _repository_path(
        args.rebuild_report,
        label="managed release rebuild report",
    )
    expected_manifest_digest = args.managed_manifest_digest
    if sha256_digest(managed_manifest.read_bytes()) != expected_manifest_digest:
        raise ElsstAtlasBenchError("managed release manifest differs from its external pin")
    _progress("verified exact ELSST managed-release input")

    report = _mapping(
        _load_json(rebuild_report_path, label="managed release rebuild report"),
        label="managed release rebuild report",
    )
    output_bundle = _mapping(
        report.get("outputBundleManifest"),
        label="rebuild report outputBundleManifest",
    )
    if output_bundle.get("digest") != expected_manifest_digest:
        raise ElsstAtlasBenchError("rebuild report names another managed release")
    counts = _mapping(report.get("counts"), label="rebuild report counts")
    relation_counts = _mapping(
        counts.get("relationsByPredicate"),
        label="rebuild report relationsByPredicate",
    )

    control = _output_path(args.control_output, label="control output")
    control.mkdir(parents=True, exist_ok=True)
    if control.is_symlink() or not control.is_dir():
        raise ElsstAtlasBenchError("control output must be a regular directory")

    evidence = {
        "type": "ElsstAtlas2BenchEvidence",
        "schemaVersion": "1.0",
        "recordedAt": cast(str, report["recordedAt"]),
        "selectedReleaseId": args.release_id,
        "managedBundle": {
            "manifestDigest": expected_manifest_digest,
            "manifestPath": _relative(managed_manifest),
            "publicationReleaseId": _mapping(
                report.get("publicationRelease"),
                label="rebuild report publicationRelease",
            )["id"],
        },
        "rebuildReport": {
            "path": _relative(rebuild_report_path),
            "sha256": sha256_digest(rebuild_report_path.read_bytes()),
        },
        "counts": counts,
    }
    evidence_path = _ensure_file(
        control / "elsst-r6-atlas2-bench-evidence.json",
        canonical_json_bytes(evidence),
        label="ELSST Atlas bench evidence",
    )

    tracked_index_input = _mapping(
        _load_json(
            _repository_path(args.atlas_index_input, label="atlas index input"),
            label="atlas index input",
        ),
        label="atlas index input",
    )
    index_input = _replace_elsst_index_row(
        tracked_index_input,
        evidence_path=_relative(evidence_path),
        manifest_digest=expected_manifest_digest,
        release_id=args.release_id,
        recorded_at=cast(str, report["recordedAt"]),
    )
    index_input_path = _ensure_file(
        control / "atlas-index-input.json",
        canonical_json_bytes(index_input),
        label="bench atlas index input",
    )
    resource_catalog = _mapping(
        _load_json(
            _repository_path(args.resource_catalog, label="resource catalog"),
            label="resource catalog",
        ),
        label="resource catalog",
    )
    atlas_index = build_atlas_index(
        index_input,
        resource_catalog,
        repository_root=ROOT,
    )
    atlas_index_bytes = canonical_json_bytes(atlas_index)
    atlas_index_path = _ensure_file(
        control / "atlas-index.json",
        atlas_index_bytes,
        label="bench atlas index",
    )
    pinned_index = PinnedAtlasIndex.open(
        atlas_index_path,
        expected_file_digest=sha256_digest(atlas_index_bytes),
        index_input=index_input,
        resource_catalog=resource_catalog,
        repository_root=ROOT,
    )
    _progress("built and reopened the ELSST-bound non-authorizing atlas index")

    assignment = ManagedReleaseRingAssignment(
        managed_manifest_digest=expected_manifest_digest,
        release_id=args.release_id,
        semantic_ring="subject",
        assigned_by=args.decision_actor,
        assigned_at=args.decided_at,
        evidence=("urn:ref:evidence:elsst-r6-atlas2-native-relation-bench-review",),
    )
    assignment_path = _ensure_file(
        control / "managed-release-ring-assignment.json",
        assignment.artifact_bytes(),
        label="managed release ring assignment",
    )
    pinned_assignment = PinnedManagedReleaseRingAssignment.open(
        assignment_path,
        expected_file_digest=sha256_digest(assignment.artifact_bytes()),
    )
    _progress("opening the exact ELSST R6 release through its managed-release gate")
    managed_release = PinnedManagedConceptRelease.open(
        managed_manifest,
        expected_manifest_digest=expected_manifest_digest,
        release_id=args.release_id,
        ring_assignment=pinned_assignment,
    )
    scope_release = AtlasScopeRelease(managed_release)
    scope = VocabularyAtlasScope.create(
        scope_name=args.scope_name,
        scope_kind="bench",
        atlas_index=pinned_index,
        releases=(scope_release,),
    )
    scope_path = _ensure_file(
        control / "atlas-scope.json",
        scope.artifact_bytes(),
        label="Atlas scope",
    )
    pinned_scope = PinnedVocabularyAtlasScope.open(
        scope_path,
        expected_file_digest=sha256_digest(scope.artifact_bytes()),
        atlas_index=pinned_index,
        releases=(scope_release,),
    )
    _progress("built and reopened the ELSST-only bench scope")

    _progress("building and reopening the canonical Atlas 2.0 asset")
    built_atlas = build_vocabulary_atlas(pinned_scope)
    atlas_output = _output_path(args.atlas_output, label="Atlas output")
    if atlas_output.exists() or atlas_output.is_symlink():
        atlas = VocabularyAtlasAsset.reproduce_from_scope(
            atlas_output,
            scope=pinned_scope,
            expected_manifest_digest=built_atlas.manifest_digest,
        )
    else:
        built_atlas.write(atlas_output)
        atlas = VocabularyAtlasAsset.open(
            atlas_output,
            expected_manifest_digest=built_atlas.manifest_digest,
        )
        if (
            atlas.payload != built_atlas.payload
            or atlas.scope_payload != built_atlas.scope_payload
            or atlas.manifest != built_atlas.manifest
        ):
            raise ElsstAtlasBenchError(
                "reopened Atlas output differs from the in-process build"
            )

    qualification_policy = {
        "id": ("https://refspec.org/policies/vocabulary-atlas-qualification/elsst-native-relations-bench/1.0"),
        "type": "ElsstNativeRelationQualificationPolicy",
        "version": "1.0",
        "exactReleaseOnly": True,
        "sourceNativePredicates": [SKOS_BROADER, SKOS_NARROWER, SKOS_RELATED],
        "crossReleaseMappings": "excluded",
    }
    selection_policy = {
        "id": ("https://refspec.org/policies/vocabulary-atlas-selection/elsst-r6-native-relations-bench/1.0"),
        "type": "ExactReleaseSelectionPolicy",
        "version": "1.0",
        "scopeName": args.scope_name,
        "releaseIds": [args.release_id],
        "relationBundleIds": [],
    }
    _ensure_file(
        control / "qualification-policy.json",
        canonical_json_bytes(qualification_policy),
        label="qualification policy",
    )
    _ensure_file(
        control / "selection-policy.json",
        canonical_json_bytes(selection_policy),
        label="selection policy",
    )
    decision = build_vocabulary_atlas_publication_decision(
        pinned_scope,
        artifact_kind="atlas",
        policies=(
            _policy_pin("qualificationPolicy", qualification_policy),
            _policy_pin("selectionPolicy", selection_policy),
        ),
        decision_actor=args.decision_actor,
        decided_at=args.decided_at,
        result={
            "role": "VocabularyAtlas",
            "id": cast(str, atlas.manifest["id"]),
            "manifestDigest": atlas.manifest_digest,
            "distributionDigest": atlas.output_digest,
        },
        exceptions=(
            {
                "kind": "developmentOnly",
                "appliesTo": cast(str, atlas.manifest["id"]),
                "statement": (
                    "Local bench publication for native-relation explorer verification; "
                    "not a product release, deployment, or activation."
                ),
            },
            {
                "kind": "rights",
                "appliesTo": args.release_id,
                "statement": (
                    "ELSST R6 source metadata records CC BY-SA 4.0; downstream "
                    "distribution must preserve attribution and share-alike terms."
                ),
            },
        ),
    )
    decision_path = _ensure_file(
        control / "publication-decision.json",
        decision.artifact_bytes(),
        label="publication decision",
    )
    pinned_decision = read_vocabulary_atlas_publication_decision(
        decision_path,
        expected_file_digest=sha256_digest(decision.artifact_bytes()),
    )
    publication_output = _output_path(
        args.publication_output,
        label="publication output",
    )
    _progress("publishing and reopening the bounded offline explorer")
    publication = _verified_publication(
        publication_output,
        atlas=atlas,
        title=args.title,
        max_concepts=args.max_concepts,
        max_mapping_assertions=args.max_mapping_assertions,
        decision=pinned_decision,
    )

    _progress("checking exact ELSST native-relation and mapping counts")
    queries = VocabularyAtlasQueries(atlas)
    concepts = queries.concepts(release_id=args.release_id)
    native_relations = queries.native_relations(release_id=args.release_id)
    mappings = queries.mapping_assertions(release_id=args.release_id)
    observed_by_predicate = dict(sorted(Counter(value.predicate_iri for value in native_relations).items()))
    expected_by_predicate = {str(key): value for key, value in sorted(relation_counts.items())}
    if len(concepts) != counts.get("members"):
        raise ElsstAtlasBenchError("Atlas concept count differs from the managed release")
    if len(native_relations) != counts.get("relations"):
        raise ElsstAtlasBenchError("Atlas native-relation count differs from the managed release")
    if observed_by_predicate != expected_by_predicate:
        raise ElsstAtlasBenchError("Atlas native-relation predicate counts differ")
    if mappings or atlas.manifest["counts"]["mappingAssertions"] != 0:
        raise ElsstAtlasBenchError("ELSST-only Atlas unexpectedly contains cross-release mappings")

    explorer_path = publication.directory / EXPLORER_DATA
    explorer = _mapping(
        _load_json(explorer_path, label="published Atlas explorer"),
        label="published Atlas explorer",
    )
    summary = _mapping(
        explorer.get("summary"),
        label="published Atlas explorer summary",
    )
    shown_relations = explorer.get("nativeRelations")
    if not isinstance(shown_relations, list) or not shown_relations:
        raise ElsstAtlasBenchError("published explorer contains no native ELSST relationships")
    if (
        summary.get("availableConceptCount") != len(concepts)
        or summary.get("availableNativeRelationCount") != len(native_relations)
        or summary.get("availableMappingAssertionCount") != 0
        or summary.get("shownNativeRelationCount") != len(shown_relations)
    ):
        raise ElsstAtlasBenchError("published explorer summary differs from exact Atlas queries")

    result = {
        "type": "ElsstAtlas2BenchBuildResult",
        "schemaVersion": "1.0",
        "decidedAt": args.decided_at,
        "selectedReleaseId": args.release_id,
        "managedManifestDigest": expected_manifest_digest,
        "atlas": {
            "path": _relative(atlas_output),
            "id": atlas.manifest["id"],
            "manifestDigest": atlas.manifest_digest,
            "distributionDigest": atlas.output_digest,
            "counts": plain_json(atlas.manifest["counts"]),
        },
        "nativeRelations": {
            "count": len(native_relations),
            "byPredicate": observed_by_predicate,
        },
        "crossReleaseMappings": len(mappings),
        "publication": {
            "path": _relative(publication.directory),
            "id": publication.manifest["id"],
            "manifestDigest": publication.manifest_digest,
            "explorerSummary": summary,
        },
        "controlArtifacts": {
            "path": _relative(control),
            "atlasIndexInput": _relative(index_input_path),
            "atlasIndex": pinned_index.pin(),
            "ringAssignment": pinned_assignment.pin(),
            "scope": pinned_scope.pin(),
            "publicationDecision": pinned_decision.reference,
        },
    }
    _ensure_file(
        control / "build-result.json",
        canonical_json_bytes(result),
        label="ELSST Atlas bench build result",
    )
    return result


def main() -> int:
    args = _arguments()
    try:
        result = build(args)
    except (ElsstAtlasBenchError, OSError, ValueError) as error:
        print(f"ELSST Atlas bench error: {error}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(canonical_json_bytes(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
