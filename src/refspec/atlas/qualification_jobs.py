"""Exact local preparation plan for the six Vocabulary Atlas v1 mapping jobs.

The manifest in this module pins the source bytes and candidate-generation
identity before any provider work starts.  Preparation verifies every source
digest, then invokes only the qualification runner's ``extract`` and
production ``generate`` commands.  Scoring and blind judging are explicit
later stages and remain outside this module.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from refspec import binding
from refspec.atlas import qualification
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.source_identity import (
    SourceIdentityError,
    require_aware_datetime_text,
)
from refspec.storage import canonical_json

VOCABULARY_ATLAS_V1_QUALIFICATION_JOBS_TYPE = "VocabularyAtlasV1ProductionQualificationJobs"
VOCABULARY_ATLAS_V1_QUALIFICATION_JOBS_VERSION = "1.0"
VOCABULARY_ATLAS_V1_QUALIFICATION_JOBS_ID_PREFIX = (
    "urn:ref:vocabulary-atlas-v1-production-qualification-jobs:"
)

SOURCE_CONCEPT_RELEASE_KIND = "sourceConceptRelease"
MANAGED_RELEASE_KIND = "managedRelease"
SOURCE_KINDS = frozenset({SOURCE_CONCEPT_RELEASE_KIND, MANAGED_RELEASE_KIND})

EXPECTED_SOURCE_KEYS = frozenset(
    {
        "crs-legislative-subjects",
        "crs-policy-areas",
        "elsst-r6",
        "federal-register-thesaurus-2025",
        "icpsr-subject-thesaurus",
    }
)
EXPECTED_JOB_PAIRS = frozenset(
    {
        ("federal-register-thesaurus-2025", "elsst-r6"),
        ("federal-register-thesaurus-2025", "icpsr-subject-thesaurus"),
        ("elsst-r6", "icpsr-subject-thesaurus"),
        ("crs-legislative-subjects", "federal-register-thesaurus-2025"),
        ("crs-policy-areas", "federal-register-thesaurus-2025"),
        ("crs-legislative-subjects", "crs-policy-areas"),
    }
)

WORKFLOW = (
    {
        "commands": ["extract", "generate"],
        "name": "localPreparation",
        "providerCalls": False,
        "timing": "preparedByThisTool",
    },
    {
        "commands": ["score-batch-submit", "score-batch-status", "score-batch-collect"],
        "name": "providerScoring",
        "providerCalls": True,
        "timing": "afterLocalPreparation",
    },
    {
        "commands": ["batch-submit", "batch-status", "batch-collect"],
        "name": "blindProviderJudging",
        "providerCalls": True,
        "timing": "afterProviderScoring",
    },
    {
        "commands": ["bundle", "seal-relations"],
        "name": "evidenceSealing",
        "providerCalls": False,
        "timing": "afterProviderEvidence",
    },
)

QUALIFICATION_POLICY = {
    "coverageMode": qualification.PRODUCTION_COVERAGE_MODE,
    "generationPolicy": qualification.PRODUCTION_CANDIDATE_GENERATION_POLICY,
    "protocol": qualification.PROTOCOL,
    "productionFloor": qualification.PRODUCTION_FLOOR,
    "proposedRelation": qualification.PROPOSED_RELATION,
    "seed": qualification.GENERATION_SEED,
}

CONCEPTS_SOURCE = "concepts-source.json"
CONCEPTS_TARGET = "concepts-target.json"
CANDIDATES = "candidates.json"

_BASIS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "releaseName",
        "qualificationPolicy",
        "workflow",
        "sources",
        "jobs",
    }
)
_RECORD_FIELDS = _BASIS_FIELDS | {"id", "recordDigest"}
_SOURCE_FIELDS = frozenset(
    {
        "key",
        "kind",
        "label",
        "language",
        "manifestPath",
        "manifestDigest",
        "releaseId",
        "vocabulary",
    }
)
_JOB_FIELDS = frozenset(
    {
        "key",
        "sourceKey",
        "targetKey",
        "outputPath",
        "generatedAt",
    }
)
_KEY = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")

CommandRunner = Callable[[Sequence[str]], int]


class VocabularyAtlasV1QualificationJobsError(ValueError):
    """A production-job manifest, source pin, or preparation run is invalid."""


def _plain(value: object) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        binding.validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise VocabularyAtlasV1QualificationJobsError(str(error)) from error
    return canonical_json_bytes(plain)


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VocabularyAtlasV1QualificationJobsError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _require_array(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise VocabularyAtlasV1QualificationJobsError(f"{label} must be an array")
    return cast(Sequence[Any], value)


def _require_exact_fields(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise VocabularyAtlasV1QualificationJobsError(
            f"{label} fields differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise VocabularyAtlasV1QualificationJobsError(f"{label} must be non-empty trimmed text")
    return value


def _require_key(value: object, label: str) -> str:
    key = _require_text(value, label)
    if _KEY.fullmatch(key) is None:
        raise VocabularyAtlasV1QualificationJobsError(
            f"{label} must contain lowercase letters, digits, and internal hyphens"
        )
    return key


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise VocabularyAtlasV1QualificationJobsError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise VocabularyAtlasV1QualificationJobsError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise VocabularyAtlasV1QualificationJobsError(f"{label} must not contain credentials")
    return iri


def _require_datetime(value: object, label: str) -> str:
    text = _require_text(value, label)
    try:
        return require_aware_datetime_text(text, label=label)
    except SourceIdentityError as error:
        raise VocabularyAtlasV1QualificationJobsError(str(error)) from error


def _require_relative_path(value: object, label: str) -> str:
    text = _require_text(value, label)
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != text
    ):
        raise VocabularyAtlasV1QualificationJobsError(
            f"{label} must be a normalized repository-relative path"
        )
    return text


def _normalize_sources(value: object) -> list[dict[str, str]]:
    rows = _require_array(value, "qualification jobs sources")
    result: list[dict[str, str]] = []
    keys: set[str] = set()
    release_ids: set[str] = set()
    for index, raw in enumerate(rows):
        label = f"qualification jobs sources[{index}]"
        row = _require_mapping(raw, label)
        _require_exact_fields(row, _SOURCE_FIELDS, label)
        key = _require_key(row.get("key"), f"{label}.key")
        release_id = _require_iri(row.get("releaseId"), f"{label}.releaseId")
        if key in keys or release_id in release_ids:
            raise VocabularyAtlasV1QualificationJobsError(
                "qualification jobs sources repeat a key or releaseId"
            )
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in SOURCE_KINDS:
            raise VocabularyAtlasV1QualificationJobsError(f"{label}.kind is unsupported")
        language = _require_text(row.get("language"), f"{label}.language")
        if language != "en":
            raise VocabularyAtlasV1QualificationJobsError(f"{label}.language must be en for v1")
        keys.add(key)
        release_ids.add(release_id)
        result.append(
            {
                "key": key,
                "kind": kind,
                "label": _require_text(row.get("label"), f"{label}.label"),
                "language": language,
                "manifestPath": _require_relative_path(row.get("manifestPath"), f"{label}.manifestPath"),
                "manifestDigest": _require_digest(
                    row.get("manifestDigest"),
                    f"{label}.manifestDigest",
                ),
                "releaseId": release_id,
                "vocabulary": _require_text(row.get("vocabulary"), f"{label}.vocabulary"),
            }
        )
    if keys != EXPECTED_SOURCE_KEYS:
        raise VocabularyAtlasV1QualificationJobsError(
            "qualification jobs sources must name the five exact v1 mapping endpoints"
        )
    ordered = sorted(result, key=lambda row: row["key"])
    if result != ordered:
        raise VocabularyAtlasV1QualificationJobsError("qualification jobs sources are not in canonical key order")
    return result


def _normalize_jobs(value: object, *, source_keys: frozenset[str]) -> list[dict[str, str]]:
    rows = _require_array(value, "qualification jobs")
    result: list[dict[str, str]] = []
    keys: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    output_paths: set[str] = set()
    for index, raw in enumerate(rows):
        label = f"qualification jobs[{index}]"
        row = _require_mapping(raw, label)
        _require_exact_fields(row, _JOB_FIELDS, label)
        source_key = _require_key(row.get("sourceKey"), f"{label}.sourceKey")
        target_key = _require_key(row.get("targetKey"), f"{label}.targetKey")
        if source_key not in source_keys or target_key not in source_keys or source_key == target_key:
            raise VocabularyAtlasV1QualificationJobsError(f"{label} must name two distinct declared sources")
        pair = (source_key, target_key)
        key = _require_key(row.get("key"), f"{label}.key")
        expected_key = f"{source_key}--{target_key}"
        if key != expected_key:
            raise VocabularyAtlasV1QualificationJobsError(f"{label}.key must be {expected_key}")
        output_path = _require_relative_path(row.get("outputPath"), f"{label}.outputPath")
        if not output_path.startswith("output/"):
            raise VocabularyAtlasV1QualificationJobsError(f"{label}.outputPath must be below output/")
        if key in keys or pair in pairs or output_path in output_paths:
            raise VocabularyAtlasV1QualificationJobsError(
                "qualification jobs repeat a key, directed pair, or output path"
            )
        keys.add(key)
        pairs.add(pair)
        output_paths.add(output_path)
        result.append(
            {
                "key": key,
                "sourceKey": source_key,
                "targetKey": target_key,
                "outputPath": output_path,
                "generatedAt": _require_datetime(row.get("generatedAt"), f"{label}.generatedAt"),
            }
        )
    if pairs != EXPECTED_JOB_PAIRS:
        raise VocabularyAtlasV1QualificationJobsError(
            "qualification jobs must name the six directed v1 production pairs"
        )
    ordered = sorted(result, key=lambda row: row["key"])
    if result != ordered:
        raise VocabularyAtlasV1QualificationJobsError("qualification jobs are not in canonical key order")
    return result


def _normalize_workflow(value: object) -> list[dict[str, Any]]:
    rows = _require_array(value, "qualification jobs workflow")
    normalized = _plain(rows)
    expected = _plain(WORKFLOW)
    if normalized != expected:
        raise VocabularyAtlasV1QualificationJobsError(
            "qualification jobs workflow must preserve local preparation and later provider stages"
        )
    return cast(list[dict[str, Any]], normalized)


def _normalize_basis(value: Mapping[str, Any]) -> dict[str, Any]:
    _require_exact_fields(value, _BASIS_FIELDS, "qualification jobs basis")
    if (
        value.get("type") != VOCABULARY_ATLAS_V1_QUALIFICATION_JOBS_TYPE
        or value.get("schemaVersion") != VOCABULARY_ATLAS_V1_QUALIFICATION_JOBS_VERSION
    ):
        raise VocabularyAtlasV1QualificationJobsError("qualification jobs type or schemaVersion differs")
    if value.get("releaseName") != "vocabulary-atlas-v1":
        raise VocabularyAtlasV1QualificationJobsError("qualification jobs releaseName must be vocabulary-atlas-v1")
    policy = _require_mapping(value.get("qualificationPolicy"), "qualification jobs qualificationPolicy")
    if _plain(policy) != QUALIFICATION_POLICY:
        raise VocabularyAtlasV1QualificationJobsError(
            "qualification jobs must use the complete production candidate policy"
        )
    sources = _normalize_sources(value.get("sources"))
    jobs = _normalize_jobs(value.get("jobs"), source_keys=frozenset(row["key"] for row in sources))
    return {
        "type": VOCABULARY_ATLAS_V1_QUALIFICATION_JOBS_TYPE,
        "schemaVersion": VOCABULARY_ATLAS_V1_QUALIFICATION_JOBS_VERSION,
        "releaseName": "vocabulary-atlas-v1",
        "qualificationPolicy": dict(QUALIFICATION_POLICY),
        "workflow": _normalize_workflow(value.get("workflow")),
        "sources": sources,
        "jobs": jobs,
    }


def seal_vocabulary_atlas_v1_qualification_jobs(
    basis: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one normalized record whose identifier comes from its exact plan."""

    normalized = _normalize_basis(basis)
    digest = binding.canonical_sha256(normalized)
    return {
        **normalized,
        "id": VOCABULARY_ATLAS_V1_QUALIFICATION_JOBS_ID_PREFIX + digest.removeprefix("sha256:"),
        "recordDigest": digest,
    }


def _decode_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise VocabularyAtlasV1QualificationJobsError(f"{label} must be valid UTF-8 JSON") from error


def _resolve_root(path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink():
        raise VocabularyAtlasV1QualificationJobsError("repository root must not be a symlink")
    try:
        root = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise VocabularyAtlasV1QualificationJobsError("repository root does not exist") from error
    if not root.is_dir():
        raise VocabularyAtlasV1QualificationJobsError("repository root must be a directory")
    return root


def _existing_file(root: Path, relative: str, *, label: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise VocabularyAtlasV1QualificationJobsError(f"{label} must not traverse a symlink")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except FileNotFoundError as error:
        raise VocabularyAtlasV1QualificationJobsError(f"{label} does not exist") from error
    except ValueError as error:
        raise VocabularyAtlasV1QualificationJobsError(f"{label} must stay inside the repository") from error
    if not resolved.is_file():
        raise VocabularyAtlasV1QualificationJobsError(f"{label} must be a regular file")
    return resolved


def _output_path(root: Path, relative: str, *, label: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise VocabularyAtlasV1QualificationJobsError(f"{label} must not traverse a symlink")
    try:
        candidate.parent.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise VocabularyAtlasV1QualificationJobsError(f"{label} must stay inside the repository") from error
    return candidate


def _read_preparation_output(
    root: Path,
    relative: str,
    *,
    label: str,
) -> tuple[Path, bytes, Mapping[str, Any]]:
    path = _existing_file(root, relative, label=label)
    payload = path.read_bytes()
    value = _decode_json(payload, label)
    if not isinstance(value, Mapping):
        raise VocabularyAtlasV1QualificationJobsError(f"{label} must be an object")
    if (canonical_json(value) + "\n").encode("utf-8") != payload:
        raise VocabularyAtlasV1QualificationJobsError(
            f"{label} must use canonical JSON bytes"
        )
    if path.read_bytes() != payload:
        raise VocabularyAtlasV1QualificationJobsError(f"{label} changed while verifying")
    return path, payload, value


def _verify_extracted_release(
    root: Path,
    *,
    output_relative: str,
    role: str,
    source: Mapping[str, str],
) -> None:
    filename = CONCEPTS_SOURCE if role == "source" else CONCEPTS_TARGET
    _path, _payload, record = _read_preparation_output(
        root,
        f"{output_relative}/{filename}",
        label=f"qualification job extracted {role}",
    )
    if (
        record.get("role") != role
        or record.get("manifestDigest") != source["manifestDigest"]
        or record.get("referenceRelease") != source["releaseId"]
        or record.get("language") != source["language"]
        or record.get("vocabulary") != source["vocabulary"]
    ):
        raise VocabularyAtlasV1QualificationJobsError(
            f"qualification job extracted {role} differs from its exact manifest endpoint"
        )
    count = record.get("conceptCount")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise VocabularyAtlasV1QualificationJobsError(
            f"qualification job extracted {role} must contain at least one concept"
        )


def _verify_candidate_catalog(
    root: Path,
    *,
    manifest: VocabularyAtlasV1QualificationJobs,
    job: Mapping[str, str],
    source: Mapping[str, str],
    target: Mapping[str, str],
) -> Mapping[str, Any]:
    _path, payload, record = _read_preparation_output(
        root,
        f"{job['outputPath']}/{CANDIDATES}",
        label=f"qualification job {job['key']} candidate catalog",
    )
    policy = cast(Mapping[str, str], manifest.record["qualificationPolicy"])
    expected = {
        "coverageMode": policy["coverageMode"],
        "generatedAt": job["generatedAt"],
        "generationPolicy": policy["generationPolicy"],
        "productionFloor": policy["productionFloor"],
        "proposedRelation": policy["proposedRelation"],
        "protocol": policy["protocol"],
        "seed": policy["seed"],
        "sourceManifestDigest": source["manifestDigest"],
        "targetManifestDigest": target["manifestDigest"],
    }
    if any(record.get(field) != value for field, value in expected.items()) or record.get("limits") is not None:
        raise VocabularyAtlasV1QualificationJobsError(
            f"qualification job {job['key']} candidate catalog differs from its production plan"
        )
    total = record.get("total")
    candidates = record.get("candidates")
    if (
        isinstance(total, bool)
        or not isinstance(total, int)
        or total <= 0
        or not isinstance(candidates, Sequence)
        or isinstance(candidates, (str, bytes))
        or len(candidates) != total
    ):
        raise VocabularyAtlasV1QualificationJobsError(
            f"qualification job {job['key']} candidate total is incomplete"
        )
    return {
        "path": f"{job['outputPath']}/{CANDIDATES}",
        "fileDigest": sha256_digest(payload),
        "total": total,
    }


@dataclass(frozen=True, slots=True)
class VocabularyAtlasV1QualificationJobs:
    """One canonical six-job plan with exact input bytes and workflow stages."""

    record: Mapping[str, Any]
    file_digest: str

    def __init__(self, record: Mapping[str, Any], *, file_digest: str = "") -> None:
        row = _require_mapping(record, "qualification jobs record")
        _require_exact_fields(row, _RECORD_FIELDS, "qualification jobs record")
        basis = {key: row[key] for key in _BASIS_FIELDS}
        expected = seal_vocabulary_atlas_v1_qualification_jobs(basis)
        if _plain(row) != expected:
            raise VocabularyAtlasV1QualificationJobsError(
                "qualification jobs record identity differs from its canonical content"
            )
        if file_digest:
            normalized_file_digest = _require_digest(
                file_digest,
                "qualification jobs file digest",
            )
            if normalized_file_digest != sha256_digest(_canonical_bytes(expected)):
                raise VocabularyAtlasV1QualificationJobsError(
                    "qualification jobs file digest differs from its canonical bytes"
                )
        object.__setattr__(self, "record", cast(Mapping[str, Any], deep_freeze_json(expected)))
        object.__setattr__(self, "file_digest", file_digest)

    @property
    def identifier(self) -> str:
        return cast(str, self.record["id"])

    @property
    def record_digest(self) -> str:
        return cast(str, self.record["recordDigest"])

    @property
    def sources(self) -> tuple[Mapping[str, str], ...]:
        return cast(tuple[Mapping[str, str], ...], self.record["sources"])

    @property
    def jobs(self) -> tuple[Mapping[str, str], ...]:
        return cast(tuple[Mapping[str, str], ...], self.record["jobs"])

    @property
    def artifact_bytes(self) -> bytes:
        return _canonical_bytes(self.record)

    def verify_source_manifests(self, repository_root: Path | str) -> Mapping[str, Path]:
        """Verify all five input manifests before any output is written."""

        root = _resolve_root(repository_root)
        verified: dict[str, Path] = {}
        for source in self.sources:
            key = source["key"]
            path = _existing_file(
                root,
                source["manifestPath"],
                label=f"qualification source {key}",
            )
            payload = path.read_bytes()
            if sha256_digest(payload) != source["manifestDigest"]:
                raise VocabularyAtlasV1QualificationJobsError(
                    f"qualification source {key} differs from its pinned manifestDigest"
                )
            if path.read_bytes() != payload:
                raise VocabularyAtlasV1QualificationJobsError(
                    f"qualification source {key} changed while verifying"
                )
            verified[key] = path
        return verified


def read_vocabulary_atlas_v1_qualification_jobs(
    path: Path | str,
) -> VocabularyAtlasV1QualificationJobs:
    """Open one canonical job manifest and verify its content-derived identity."""

    manifest_path = Path(path)
    if manifest_path.is_symlink():
        raise VocabularyAtlasV1QualificationJobsError("qualification jobs manifest must not be a symlink")
    try:
        resolved = manifest_path.resolve(strict=True)
    except FileNotFoundError as error:
        raise VocabularyAtlasV1QualificationJobsError("qualification jobs manifest does not exist") from error
    if not resolved.is_file():
        raise VocabularyAtlasV1QualificationJobsError("qualification jobs manifest must be a regular file")
    payload = resolved.read_bytes()
    value = _decode_json(payload, "qualification jobs manifest")
    if not isinstance(value, Mapping) or _canonical_bytes(value) != payload:
        raise VocabularyAtlasV1QualificationJobsError("qualification jobs manifest bytes are not canonical")
    manifest = VocabularyAtlasV1QualificationJobs(
        value,
        file_digest="sha256:" + hashlib.sha256(payload).hexdigest(),
    )
    if resolved.read_bytes() != payload:
        raise VocabularyAtlasV1QualificationJobsError("qualification jobs manifest changed while opening")
    return manifest


def _default_runner(command: Sequence[str]) -> int:
    return subprocess.run(tuple(command), check=False).returncode


def _selected_jobs(
    manifest: VocabularyAtlasV1QualificationJobs,
    job_keys: Sequence[str] | None,
) -> tuple[Mapping[str, str], ...]:
    if not job_keys:
        return manifest.jobs
    requested = tuple(job_keys)
    if len(requested) != len(set(requested)):
        raise VocabularyAtlasV1QualificationJobsError("selected job keys must be unique")
    by_key = {job["key"]: job for job in manifest.jobs}
    missing = sorted(set(requested) - set(by_key))
    if missing:
        raise VocabularyAtlasV1QualificationJobsError(f"unknown qualification job keys: {missing}")
    return tuple(by_key[key] for key in requested)


def verify_prepared_vocabulary_atlas_v1_qualification_jobs(
    manifest: VocabularyAtlasV1QualificationJobs,
    *,
    repository_root: Path | str,
) -> Mapping[str, Any]:
    """Reopen all six prepared catalogs without writing or calling a provider."""

    if not isinstance(manifest, VocabularyAtlasV1QualificationJobs):
        raise VocabularyAtlasV1QualificationJobsError(
            "prepared-catalog verification requires a verified job manifest"
        )
    root = _resolve_root(repository_root)
    source_paths = manifest.verify_source_manifests(root)
    sources = {source["key"]: source for source in manifest.sources}
    catalogs: list[Mapping[str, Any]] = []
    for job in manifest.jobs:
        source = sources[job["sourceKey"]]
        target = sources[job["targetKey"]]
        _verify_extracted_release(
            root,
            output_relative=job["outputPath"],
            role="source",
            source=source,
        )
        _verify_extracted_release(
            root,
            output_relative=job["outputPath"],
            role="target",
            source=target,
        )
        catalogs.append(
            _verify_candidate_catalog(
                root,
                manifest=manifest,
                job=job,
                source=source,
                target=target,
            )
        )
    return {
        "type": "VocabularyAtlasV1PreparedQualificationVerification",
        "schemaVersion": "1.0",
        "qualificationJobs": {
            "id": manifest.identifier,
            "recordDigest": manifest.record_digest,
            "fileDigest": manifest.file_digest,
        },
        "providerCalls": False,
        "sourceCount": len(source_paths),
        "jobCount": len(catalogs),
        "candidateCatalogs": catalogs,
        "aggregateTotal": sum(cast(int, catalog["total"]) for catalog in catalogs),
    }


def prepare_vocabulary_atlas_v1_qualification_jobs(
    manifest: VocabularyAtlasV1QualificationJobs,
    *,
    repository_root: Path | str,
    job_keys: Sequence[str] | None = None,
    command_runner: CommandRunner = _default_runner,
    python_executable: str = sys.executable,
    qualification_runner_path: str = "tools/run_atlas_qualification.py",
) -> Mapping[str, Any]:
    """Verify every pin, then run only extraction and production generation."""

    if not isinstance(manifest, VocabularyAtlasV1QualificationJobs):
        raise VocabularyAtlasV1QualificationJobsError("preparation requires a verified job manifest")
    root = _resolve_root(repository_root)
    source_paths = manifest.verify_source_manifests(root)
    runner_relative = _require_relative_path(
        qualification_runner_path,
        "qualification runner path",
    )
    runner_path = _existing_file(root, runner_relative, label="qualification runner")
    selected = _selected_jobs(manifest, job_keys)
    sources = {source["key"]: source for source in manifest.sources}
    executed: list[dict[str, Any]] = []
    for job in selected:
        source = sources[job["sourceKey"]]
        target = sources[job["targetKey"]]
        output_path = _output_path(root, job["outputPath"], label=f"qualification job {job['key']} output")
        extract_command = (
            python_executable,
            str(runner_path),
            "--output",
            str(output_path),
            "extract",
            "--source-manifest",
            str(source_paths[source["key"]]),
            "--source-release-iri",
            source["releaseId"],
            "--source-vocabulary",
            source["vocabulary"],
            "--target-manifest",
            str(source_paths[target["key"]]),
            "--target-release-iri",
            target["releaseId"],
            "--target-vocabulary",
            target["vocabulary"],
            "--language",
            source["language"],
        )
        status = command_runner(extract_command)
        if status != 0:
            raise VocabularyAtlasV1QualificationJobsError(
                f"qualification job {job['key']} extract failed with status {status}"
            )
        _verify_extracted_release(
            root,
            output_relative=job["outputPath"],
            role="source",
            source=source,
        )
        _verify_extracted_release(
            root,
            output_relative=job["outputPath"],
            role="target",
            source=target,
        )
        generate_command = (
            python_executable,
            str(runner_path),
            "--output",
            str(output_path),
            "generate",
            "--generated-at",
            job["generatedAt"],
            "--seed",
            cast(Mapping[str, str], manifest.record["qualificationPolicy"])["seed"],
            "--production",
        )
        status = command_runner(generate_command)
        if status != 0:
            raise VocabularyAtlasV1QualificationJobsError(
                f"qualification job {job['key']} generate failed with status {status}"
            )
        catalog = _verify_candidate_catalog(
            root,
            manifest=manifest,
            job=job,
            source=source,
            target=target,
        )
        executed.append(
            {
                "candidateCatalog": catalog,
                "jobKey": job["key"],
                "outputPath": job["outputPath"],
                "stages": ["extract", "generate"],
            }
        )
    return {
        "type": "VocabularyAtlasV1QualificationPreparationResult",
        "schemaVersion": "1.0",
        "qualificationJobs": {
            "id": manifest.identifier,
            "recordDigest": manifest.record_digest,
            "fileDigest": manifest.file_digest,
        },
        "providerCalls": False,
        "coverageMode": qualification.PRODUCTION_COVERAGE_MODE,
        "jobs": executed,
    }


__all__ = [
    "EXPECTED_JOB_PAIRS",
    "EXPECTED_SOURCE_KEYS",
    "QUALIFICATION_POLICY",
    "VOCABULARY_ATLAS_V1_QUALIFICATION_JOBS_TYPE",
    "VOCABULARY_ATLAS_V1_QUALIFICATION_JOBS_VERSION",
    "VocabularyAtlasV1QualificationJobs",
    "VocabularyAtlasV1QualificationJobsError",
    "prepare_vocabulary_atlas_v1_qualification_jobs",
    "read_vocabulary_atlas_v1_qualification_jobs",
    "seal_vocabulary_atlas_v1_qualification_jobs",
    "verify_prepared_vocabulary_atlas_v1_qualification_jobs",
]
