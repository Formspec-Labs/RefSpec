"""Exact six-job preparation controls for Vocabulary Atlas v1."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from refspec import binding
from refspec.atlas.qualification_jobs import (
    EXPECTED_JOB_PAIRS,
    EXPECTED_SOURCE_KEYS,
    QUALIFICATION_POLICY,
    WORKFLOW,
    VocabularyAtlasV1QualificationJobs,
    VocabularyAtlasV1QualificationJobsError,
    prepare_vocabulary_atlas_v1_qualification_jobs,
    read_vocabulary_atlas_v1_qualification_jobs,
    seal_vocabulary_atlas_v1_qualification_jobs,
    verify_prepared_vocabulary_atlas_v1_qualification_jobs,
)
from refspec.registry.infrastructure.artifact_serialization import plain_json, sha256_digest
from refspec.storage import canonical_json

ROOT = Path(__file__).resolve().parents[1]
TRACKED_MANIFEST = ROOT / "portfolio/vocabulary-atlas-v1-production-qualification-jobs.json"
PREPARATION_TOOL = ROOT / "tools/prepare_vocabulary_atlas_v1_qualification.py"
GENERATED_AT = "2026-08-04T22:00:00Z"

EXACT_SOURCE_PINS = {
    "crs-legislative-subjects": {
        "kind": "sourceConceptRelease",
        "manifestDigest": "sha256:f20d688f08134a8b6b1c9a6e202e84c5e051e2786c743df66708be27b55b12e7",
        "manifestPath": (
            "research/evidence/crs-source-concept-releases-2026-08-04/legislative-subjects/bundle-manifest.json"
        ),
        "releaseId": (
            "urn:ref:source-concept-release:subject:d137bdbae553a0ca59fb879458703de0a0a9047b49c119cb79a0765de75f3567"
        ),
    },
    "crs-policy-areas": {
        "kind": "sourceConceptRelease",
        "manifestDigest": "sha256:b5966cb93cc1a28cc87ea914538f9c2f3da0b44fb37f66385170b56954dabeb8",
        "manifestPath": "research/evidence/crs-source-concept-releases-2026-08-04/policy-areas/bundle-manifest.json",
        "releaseId": (
            "urn:ref:source-concept-release:subject:3e2d1e3d598d818c4d53e9514c05ad8a5a804a3f138e1325f1605c7eed517d7e"
        ),
    },
    "elsst-r6": {
        "kind": "managedRelease",
        "manifestDigest": "sha256:466a4464cd252bf0b0c0e872927abc430f7532610100cf01e8104eec0ee69f25",
        "manifestPath": (
            "output/elsst-r6-atlas2-bench-input-2026-08-04/managed-release/managed-release-bundle.json"
        ),
        "releaseId": "https://elsst.cessda.eu/id/6",
    },
    "federal-register-thesaurus-2025": {
        "kind": "managedRelease",
        "manifestDigest": "sha256:3491acfdb3c4b51fda6351fcc47c2ca13e63e9df99e30399e05f745c97bf9df6",
        "manifestPath": "output/skip-test-runtime/frt25/managed-release/managed-release.json",
        "releaseId": "urn:ref:federal-register-thesaurus:2025-04-01:reference-resource-release:v1",
    },
    "icpsr-subject-thesaurus": {
        "kind": "managedRelease",
        "manifestDigest": "sha256:f3c9f4efa7fd12b6339db9feabb029b17425672293a8fb615999c881673ac12a",
        "manifestPath": "output/refspec-vocabulary-portfolio/icpsr/2026-07-30/managed-release/managed-release.json",
        "releaseId": (
            "urn:ref:icpsr:release:development:8bf9bf7f6c335e3aaccd29eedd00d41d7bc153e216e7dff6ff215472368aae37"
        ),
    },
}

EXACT_JOB_OUTPUTS = {
    "crs-legislative-subjects--crs-policy-areas": (
        "output/vocabulary-atlas-v1-rc1/qualification-production/crs-subjects-policy"
    ),
    "crs-legislative-subjects--federal-register-thesaurus-2025": (
        "output/vocabulary-atlas-v1-rc1/qualification-production/crs-subjects-fr"
    ),
    "crs-policy-areas--federal-register-thesaurus-2025": (
        "output/vocabulary-atlas-v1-rc1/qualification-production/crs-policy-fr"
    ),
    "elsst-r6--icpsr-subject-thesaurus": (
        "output/vocabulary-atlas-v1-rc1/qualification-production/elsst-icpsr"
    ),
    "federal-register-thesaurus-2025--elsst-r6": (
        "output/vocabulary-atlas-v1-rc1/qualification-production/fr-elsst"
    ),
    "federal-register-thesaurus-2025--icpsr-subject-thesaurus": (
        "output/vocabulary-atlas-v1-rc1/qualification-production/fr-icpsr"
    ),
}


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_basis(root: Path) -> dict[str, Any]:
    sources: list[dict[str, str]] = []
    for key in sorted(EXPECTED_SOURCE_KEYS):
        relative = f"inputs/{key}.json"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json({"key": key}) + "\n", encoding="utf-8")
        sources.append(
            {
                "key": key,
                "kind": (
                    "sourceConceptRelease"
                    if key.startswith("crs-")
                    else "managedRelease"
                ),
                "label": key,
                "language": "en",
                "manifestPath": relative,
                "manifestDigest": _file_digest(path),
                "releaseId": f"urn:test:release:{key}",
                "vocabulary": key,
            }
        )
    jobs = [
        {
            "key": f"{source}--{target}",
            "sourceKey": source,
            "targetKey": target,
            "outputPath": f"output/qualification/{source}--{target}",
            "generatedAt": GENERATED_AT,
        }
        for source, target in sorted(EXPECTED_JOB_PAIRS, key=lambda pair: f"{pair[0]}--{pair[1]}")
    ]
    return {
        "type": "VocabularyAtlasV1ProductionQualificationJobs",
        "schemaVersion": "1.0",
        "releaseName": "vocabulary-atlas-v1",
        "qualificationPolicy": dict(QUALIFICATION_POLICY),
        "workflow": copy.deepcopy(WORKFLOW),
        "sources": sources,
        "jobs": jobs,
    }


def _fixture_manifest(root: Path) -> VocabularyAtlasV1QualificationJobs:
    return VocabularyAtlasV1QualificationJobs(
        seal_vocabulary_atlas_v1_qualification_jobs(_fixture_basis(root))
    )


def _fixture_runner(root: Path) -> None:
    path = root / "tools/run_atlas_qualification.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# fixture runner\n", encoding="utf-8")


def _value(command: Sequence[str], option: str) -> str:
    return str(command[command.index(option) + 1])


def _successful_runner(commands: list[tuple[str, ...]]):
    def run(command: Sequence[str]) -> int:
        row = tuple(command)
        commands.append(row)
        output = Path(_value(row, "--output"))
        output.mkdir(parents=True, exist_ok=True)
        stage = row[4]
        if stage == "extract":
            language = _value(row, "--language")
            for role in ("source", "target"):
                manifest_path = Path(_value(row, f"--{role}-manifest"))
                record = {
                    "conceptCount": 1,
                    "concepts": [],
                    "language": language,
                    "manifestDigest": _file_digest(manifest_path),
                    "referenceRelease": _value(row, f"--{role}-release-iri"),
                    "role": role,
                    "vocabulary": _value(row, f"--{role}-vocabulary"),
                }
                (output / f"concepts-{role}.json").write_text(
                    canonical_json(record) + "\n",
                    encoding="utf-8",
                )
        elif stage == "generate":
            source = json.loads((output / "concepts-source.json").read_text(encoding="utf-8"))
            target = json.loads((output / "concepts-target.json").read_text(encoding="utf-8"))
            record = {
                "candidates": [{"candidateId": "urn:test:candidate:1"}],
                "coverageMode": QUALIFICATION_POLICY["coverageMode"],
                "generatedAt": _value(row, "--generated-at"),
                "generationPolicy": QUALIFICATION_POLICY["generationPolicy"],
                "limits": None,
                "productionFloor": QUALIFICATION_POLICY["productionFloor"],
                "proposedRelation": QUALIFICATION_POLICY["proposedRelation"],
                "protocol": QUALIFICATION_POLICY["protocol"],
                "seed": _value(row, "--seed"),
                "sourceManifestDigest": source["manifestDigest"],
                "targetManifestDigest": target["manifestDigest"],
                "total": 1,
            }
            (output / "candidates.json").write_text(
                canonical_json(record) + "\n",
                encoding="utf-8",
            )
        return 0

    return run


def test_tracked_manifest_pins_the_exact_six_production_jobs() -> None:
    manifest = read_vocabulary_atlas_v1_qualification_jobs(TRACKED_MANIFEST)

    assert len(manifest.sources) == 5
    assert len(manifest.jobs) == 6
    assert {source["key"] for source in manifest.sources} == EXPECTED_SOURCE_KEYS
    assert {
        (job["sourceKey"], job["targetKey"])
        for job in manifest.jobs
    } == EXPECTED_JOB_PAIRS
    assert {
        source["key"]: {
            field: source[field]
            for field in ("kind", "manifestDigest", "manifestPath", "releaseId")
        }
        for source in manifest.sources
    } == EXACT_SOURCE_PINS
    assert {job["key"]: job["outputPath"] for job in manifest.jobs} == EXACT_JOB_OUTPUTS
    assert {job["generatedAt"] for job in manifest.jobs} == {"2026-08-04T23:00:00Z"}
    assert manifest.record_digest == binding.canonical_sha256(
        plain_json(
            {
                key: manifest.record[key]
                for key in manifest.record
                if key not in {"id", "recordDigest"}
            }
        )
    )
    assert manifest.artifact_bytes == TRACKED_MANIFEST.read_bytes()
    assert manifest.file_digest == sha256_digest(TRACKED_MANIFEST.read_bytes())


def test_tracked_manifest_verifies_current_exact_source_bytes() -> None:
    manifest = read_vocabulary_atlas_v1_qualification_jobs(TRACKED_MANIFEST)
    missing = [
        source["manifestPath"]
        for source in manifest.sources
        if not (ROOT / source["manifestPath"]).is_file()
    ]
    if missing:
        pytest.skip(f"local exact release inputs are unavailable: {missing}")

    verified = manifest.verify_source_manifests(ROOT)

    assert set(verified) == EXPECTED_SOURCE_KEYS
    assert all(path.is_file() for path in verified.values())


def test_manifest_names_provider_scoring_and_blind_judging_as_later_stages() -> None:
    manifest = read_vocabulary_atlas_v1_qualification_jobs(TRACKED_MANIFEST)
    workflow = list(manifest.record["workflow"])

    assert workflow[0] == {
        "commands": ("extract", "generate"),
        "name": "localPreparation",
        "providerCalls": False,
        "timing": "preparedByThisTool",
    }
    assert [(stage["name"], stage["providerCalls"], stage["timing"]) for stage in workflow[1:3]] == [
        ("providerScoring", True, "afterLocalPreparation"),
        ("blindProviderJudging", True, "afterProviderScoring"),
    ]
    assert manifest.record["qualificationPolicy"] == QUALIFICATION_POLICY


def test_preparation_invokes_only_extract_and_production_generate(tmp_path: Path) -> None:
    manifest = _fixture_manifest(tmp_path)
    _fixture_runner(tmp_path)
    commands: list[tuple[str, ...]] = []

    result = prepare_vocabulary_atlas_v1_qualification_jobs(
        manifest,
        repository_root=tmp_path,
        command_runner=_successful_runner(commands),
        python_executable="python-fixture",
    )

    assert len(commands) == 12
    assert [command[4] for command in commands] == ["extract", "generate"] * 6
    assert all(command[-1] == "--production" for command in commands[1::2])
    assert all("batch-submit" not in command and "qualify" not in command for command in commands)
    assert result["providerCalls"] is False
    assert len(result["jobs"]) == 6


def test_preparation_can_select_one_exact_job(tmp_path: Path) -> None:
    manifest = _fixture_manifest(tmp_path)
    _fixture_runner(tmp_path)
    commands: list[tuple[str, ...]] = []
    selected = "federal-register-thesaurus-2025--elsst-r6"

    result = prepare_vocabulary_atlas_v1_qualification_jobs(
        manifest,
        repository_root=tmp_path,
        job_keys=[selected],
        command_runner=_successful_runner(commands),
    )

    assert len(commands) == 2
    assert result["jobs"][0]["jobKey"] == selected
    assert result["jobs"][0]["outputPath"] == f"output/qualification/{selected}"
    assert result["jobs"][0]["stages"] == ["extract", "generate"]
    assert result["jobs"][0]["candidateCatalog"]["total"] == 1


def test_read_only_verification_reopens_all_six_prepared_catalogs(tmp_path: Path) -> None:
    manifest = _fixture_manifest(tmp_path)
    _fixture_runner(tmp_path)
    prepare_vocabulary_atlas_v1_qualification_jobs(
        manifest,
        repository_root=tmp_path,
        command_runner=_successful_runner([]),
    )
    output_root = tmp_path / "output"
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in output_root.rglob("*")
        if path.is_file()
    }

    result = verify_prepared_vocabulary_atlas_v1_qualification_jobs(
        manifest,
        repository_root=tmp_path,
    )

    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in output_root.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert result["providerCalls"] is False
    assert result["sourceCount"] == 5
    assert result["jobCount"] == 6
    assert result["aggregateTotal"] == 6
    assert len(result["candidateCatalogs"]) == 6
    assert all(set(row) == {"path", "fileDigest", "total"} for row in result["candidateCatalogs"])
    assert all(row["total"] == 1 for row in result["candidateCatalogs"])


def test_read_only_verification_refuses_a_tampered_candidate_catalog(tmp_path: Path) -> None:
    manifest = _fixture_manifest(tmp_path)
    _fixture_runner(tmp_path)
    prepare_vocabulary_atlas_v1_qualification_jobs(
        manifest,
        repository_root=tmp_path,
        command_runner=_successful_runner([]),
    )
    first = manifest.jobs[0]
    catalog_path = tmp_path / first["outputPath"] / "candidates.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["coverageMode"] = "pilotSlice"
    catalog_path.write_text(canonical_json(catalog) + "\n", encoding="utf-8")

    with pytest.raises(VocabularyAtlasV1QualificationJobsError, match="differs from its production plan"):
        verify_prepared_vocabulary_atlas_v1_qualification_jobs(
            manifest,
            repository_root=tmp_path,
        )


def test_check_and_verify_prepared_cli_modes_are_mutually_exclusive() -> None:
    completed = subprocess.run(
        [sys.executable, str(PREPARATION_TOOL), "--check", "--verify-prepared"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 2
    assert "not allowed with argument" in completed.stderr


def test_preparation_verifies_all_source_pins_before_running_a_command(tmp_path: Path) -> None:
    basis = _fixture_basis(tmp_path)
    manifest = VocabularyAtlasV1QualificationJobs(
        seal_vocabulary_atlas_v1_qualification_jobs(basis)
    )
    _fixture_runner(tmp_path)
    (tmp_path / basis["sources"][-1]["manifestPath"]).write_text("changed\n", encoding="utf-8")
    calls = 0

    def count_calls(_command: Sequence[str]) -> int:
        nonlocal calls
        calls += 1
        return 0

    with pytest.raises(VocabularyAtlasV1QualificationJobsError, match="pinned manifestDigest"):
        prepare_vocabulary_atlas_v1_qualification_jobs(
            manifest,
            repository_root=tmp_path,
            command_runner=count_calls,
        )
    assert calls == 0


def test_preparation_stops_at_the_first_failed_local_stage(tmp_path: Path) -> None:
    manifest = _fixture_manifest(tmp_path)
    _fixture_runner(tmp_path)
    calls: list[tuple[str, ...]] = []

    def fail_extract(command: Sequence[str]) -> int:
        calls.append(tuple(command))
        return 7

    with pytest.raises(VocabularyAtlasV1QualificationJobsError, match="extract failed with status 7"):
        prepare_vocabulary_atlas_v1_qualification_jobs(
            manifest,
            repository_root=tmp_path,
            command_runner=fail_extract,
        )
    assert len(calls) == 1


def test_manifest_refuses_unsafe_or_noncanonical_repository_paths(tmp_path: Path) -> None:
    basis = _fixture_basis(tmp_path)
    basis["sources"][0]["manifestPath"] = "../outside.json"

    with pytest.raises(VocabularyAtlasV1QualificationJobsError, match="normalized repository-relative"):
        seal_vocabulary_atlas_v1_qualification_jobs(basis)


def test_reader_refuses_noncanonical_bytes(tmp_path: Path) -> None:
    record = seal_vocabulary_atlas_v1_qualification_jobs(_fixture_basis(tmp_path))
    path = tmp_path / "pretty.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(VocabularyAtlasV1QualificationJobsError, match="bytes are not canonical"):
        read_vocabulary_atlas_v1_qualification_jobs(path)


def test_content_change_moves_the_manifest_identity(tmp_path: Path) -> None:
    first_basis = _fixture_basis(tmp_path)
    second_basis = copy.deepcopy(first_basis)
    second_basis["jobs"][0]["generatedAt"] = "2026-08-04T22:00:01Z"

    first = seal_vocabulary_atlas_v1_qualification_jobs(first_basis)
    second = seal_vocabulary_atlas_v1_qualification_jobs(second_basis)

    assert first["recordDigest"] != second["recordDigest"]
    assert first["id"] != second["id"]


def test_manifest_object_refuses_a_false_file_digest(tmp_path: Path) -> None:
    record = seal_vocabulary_atlas_v1_qualification_jobs(_fixture_basis(tmp_path))

    with pytest.raises(
        VocabularyAtlasV1QualificationJobsError,
        match="file digest differs from its canonical bytes",
    ):
        VocabularyAtlasV1QualificationJobs(
            record,
            file_digest="sha256:" + "0" * 64,
        )
