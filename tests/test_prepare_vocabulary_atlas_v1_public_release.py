from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest

from refspec.atlas import qualification as qual
from refspec.atlas import v1_release as release_contract
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    sha256_digest,
)
from refspec.storage import canonical_json

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools/prepare_vocabulary_atlas_v1_public_release.py"
RUNNER_PATH = ROOT / "tools/run_atlas_qualification.py"


def _load_tool(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


PUBLIC_TOOL = _load_tool("_refspec_public_release_preparer", TOOL_PATH)
RUNNER = _load_tool("_refspec_public_release_runner", RUNNER_PATH)


@pytest.fixture(scope="module")
def baseline_basis() -> dict[str, Any]:
    return PUBLIC_TOOL.build_baseline_release_definition_basis(ROOT, check=False)


def _copy(value: object) -> Any:
    return json.loads(canonical_json(value))


def _reseal_record(record: Mapping[str, Any], *, prefix: str) -> dict[str, Any]:
    basis = {key: _copy(value) for key, value in record.items() if key not in {"id", "contentDigest"}}
    digest = sha256_digest(canonical_json_bytes(basis))
    return {
        **basis,
        "id": prefix + digest.removeprefix("sha256:"),
        "contentDigest": digest,
    }


def _fabricate_resealed_question_digest(
    relation: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep an embedded relation self-consistent while inventing proof facts."""

    result = cast(dict[str, Any], _copy(relation))
    proof = result["machineProofPins"][0]
    old_proof_id = proof["id"]
    proof["proofDetails"]["sealedQuestion"]["inputDigest"] = "sha256:" + "f" * 64
    proof = _reseal_record(
        proof,
        prefix="urn:ref:machine-evidence-proof:subject:",
    )
    result["machineProofPins"][0] = proof
    result["machineProofPins"].sort(key=lambda row: row["id"])

    evidence_ids: dict[str, str] = {}
    for index, evidence in enumerate(result["evidenceAssertions"]):
        if evidence.get("machineProof") != old_proof_id:
            continue
        old_evidence_id = evidence["id"]
        evidence["machineProof"] = proof["id"]
        evidence["evidence"] = [proof["id"] if value == old_proof_id else value for value in evidence["evidence"]]
        resealed = _reseal_record(
            evidence,
            prefix="urn:ref:evidence-assertion:subject:",
        )
        result["evidenceAssertions"][index] = resealed
        evidence_ids[old_evidence_id] = resealed["id"]
    result["evidenceAssertions"].sort(key=lambda row: row["id"])

    for index, mapping in enumerate(result["mappingAssertions"]):
        replaced = [evidence_ids.get(value, value) for value in mapping["evidence"]]
        if replaced == mapping["evidence"]:
            continue
        mapping["evidence"] = replaced
        result["mappingAssertions"][index] = _reseal_record(
            mapping,
            prefix="urn:ref:mapping-assertion:subject:",
        )
    result["mappingAssertions"].sort(key=lambda row: row["id"])
    return _reseal_record(
        result,
        prefix="urn:ref:relation-assertion-bundle:subject:",
    )


def _public_basis(baseline_basis: Mapping[str, Any]) -> dict[str, Any]:
    basis = cast(dict[str, Any], _copy(baseline_basis))
    release_ids = {row["v1Role"]: row["releaseId"] for row in basis["releases"]}
    production_runs = []
    for job, roles in release_contract._PRODUCTION_JOB_ROLES.items():
        digest = hashlib.sha256(job.encode("utf-8")).hexdigest()
        production_runs.append(
            {
                "job": job,
                "sourceReleaseId": release_ids[roles[0]],
                "targetReleaseId": release_ids[roles[1]],
                "runReceiptPath": f"output/test/{job}/qualification-receipt.json",
                "runReceiptFileDigest": f"sha256:{digest}",
                "runReceiptContentDigest": f"sha256:{digest[::-1]}",
            }
        )
    basis.update(
        {
            "releaseMode": "publicV1",
            "releaseName": "urn:ref:vocabulary-atlas:release:v1",
            "scopeName": "urn:ref:vocabulary-atlas:scope:v1",
            "scopeKind": "published",
            "title": "Vocabulary Atlas v1",
            "reviewedSearchCorpus": {
                "status": "required",
                "path": release_contract._PUBLIC_V1_EXPLORER_SEARCH_CORPUS_PATH,
                "fileDigest": release_contract._PUBLIC_V1_EXPLORER_SEARCH_CORPUS_FILE_DIGEST,
            },
            "productionQualificationRuns": production_runs,
        }
    )
    return basis


def test_prepares_and_rechecks_public_definition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    baseline_basis: Mapping[str, Any],
) -> None:
    basis = _public_basis(baseline_basis)
    monkeypatch.setattr(
        PUBLIC_TOOL,
        "build_public_release_definition_basis",
        lambda _root, *, decided_at, check: _copy(basis),
    )
    output = tmp_path / "vocabulary-atlas-v1-public.json"

    prepared = PUBLIC_TOOL.prepare_public_release_definition(
        output,
        root=ROOT,
        decided_at="2026-08-05T12:00:00Z",
    )

    assert prepared.path == output.resolve()
    assert prepared.record["releaseMode"] == "publicV1"
    assert len(prepared.record["productionQualificationRuns"]) == 6
    assert output.read_bytes() == prepared.artifact_bytes()
    checked = PUBLIC_TOOL.prepare_public_release_definition(
        output,
        root=ROOT,
        decided_at="2026-08-05T12:00:00Z",
        check=True,
    )
    assert checked.identifier == prepared.identifier

    output.write_bytes(b"{}\n")
    with pytest.raises(
        PUBLIC_TOOL.PublicReleasePreparationError,
        match="differs from the exact current inputs",
    ):
        PUBLIC_TOOL.prepare_public_release_definition(
            output,
            root=ROOT,
            decided_at="2026-08-05T12:00:00Z",
            check=True,
        )


def test_public_basis_discovers_six_unique_manifest_jobs_and_relation_keys(
    monkeypatch: pytest.MonkeyPatch,
    baseline_basis: Mapping[str, Any],
) -> None:
    monkeypatch.setattr(
        PUBLIC_TOOL,
        "build_baseline_release_definition_basis",
        lambda _root, *, check: _copy(baseline_basis),
    )
    monkeypatch.setattr(
        PUBLIC_TOOL,
        "verify_prepared_vocabulary_atlas_v1_qualification_jobs",
        lambda _manifest, *, repository_root: {"jobCount": 6},
    )

    def production_job(
        _root: Path,
        *,
        public_job: str,
        planned_job: Mapping[str, str],
        source: Mapping[str, str],
        target: Mapping[str, str],
        policy: Mapping[str, str],
    ) -> tuple[dict[str, str], dict[str, Any] | None, int, dict[str, Any]]:
        digest = "sha256:" + hashlib.sha256(public_job.encode()).hexdigest()
        run = {
            "job": public_job,
            "sourceReleaseId": source["releaseId"],
            "targetReleaseId": target["releaseId"],
            "runReceiptPath": f"{planned_job['outputPath']}/qualification-receipt.json",
            "runReceiptFileDigest": digest,
            "runReceiptContentDigest": digest,
        }
        spend = {
            "approvedTotalSpendCapUsd": "112.000000",
            "authorityFileDigest": "sha256:" + "a" * 64,
            "authorityId": "urn:ref:test:production-spend-authority",
            "authorityRecordDigest": "sha256:" + "b" * 64,
            "batchPlanDigest": "sha256:" + "c" * 64,
            "batchPolicyDigest": "sha256:" + "d" * 64,
            "committedSpendUsd": 0.0,
            "jobKey": planned_job["key"],
            "runSpendCapUsd": format(
                PUBLIC_TOOL.qspend.FIXED_RUN_SPEND_CAPS_USD[planned_job["key"]],
                ".6f",
            ),
        }
        if public_job == "crs-subjects-crs-policy":
            return run, None, 0, spend
        relation = {
            "key": f"production-{public_job}",
            "manifestPath": f"{planned_job['outputPath']}/relation-assertions/bundle-manifest.json",
            "manifestDigest": digest,
            "semanticRing": "subject",
            "releaseIds": sorted([source["releaseId"], target["releaseId"]]),
            "machineProofs": [],
        }
        return run, relation, 1, spend

    monkeypatch.setattr(PUBLIC_TOOL, "_production_job", production_job)

    result = PUBLIC_TOOL.build_public_release_definition_basis(
        ROOT,
        decided_at="2026-08-05T12:00:00Z",
    )

    runs = result["productionQualificationRuns"]
    assert len(runs) == 6
    assert {row["job"] for row in runs} == set(release_contract._PRODUCTION_JOB_ROLES)
    production_keys = {row["key"] for row in result["relationBundles"] if row["key"].startswith("production-")}
    assert production_keys == {
        f"production-{job}" for job in release_contract._PRODUCTION_JOB_ROLES if job != "crs-subjects-crs-policy"
    }
    assert len({row["key"] for row in result["relationBundles"]}) == len(result["relationBundles"])


def test_public_campaign_spend_gate_requires_one_exact_global_authority() -> None:
    manifest = PUBLIC_TOOL._qualification_manifest(ROOT)
    rows = [
        {
            "approvedTotalSpendCapUsd": "112.000000",
            "authorityFileDigest": "sha256:" + "a" * 64,
            "authorityId": "urn:ref:test:production-spend-authority",
            "authorityRecordDigest": "sha256:" + "b" * 64,
            "batchPlanDigest": "sha256:" + "c" * 64,
            "batchPolicyDigest": "sha256:" + "d" * 64,
            "committedSpendUsd": 0.0,
            "jobKey": job["key"],
            "runSpendCapUsd": format(
                PUBLIC_TOOL.qspend.FIXED_RUN_SPEND_CAPS_USD[job["key"]],
                ".6f",
            ),
        }
        for job in manifest.jobs
    ]

    PUBLIC_TOOL._verify_campaign_spend_rows(rows, manifest)

    mixed = _copy(rows)
    mixed[0]["authorityId"] = "urn:ref:test:another-authority"
    with pytest.raises(
        PUBLIC_TOOL.PublicReleasePreparationError,
        match="share one exact six-run spend authority",
    ):
        PUBLIC_TOOL._verify_campaign_spend_rows(mixed, manifest)

    overallocated = _copy(rows)
    overallocated[0]["runSpendCapUsd"] = "1.110000"
    with pytest.raises(
        PUBLIC_TOOL.PublicReleasePreparationError,
        match="exceeds its approved total spend cap",
    ):
        PUBLIC_TOOL._verify_campaign_spend_rows(overallocated, manifest)

    overspent = _copy(rows)
    overspent[0]["committedSpendUsd"] = 112.000001
    with pytest.raises(
        PUBLIC_TOOL.PublicReleasePreparationError,
        match="exceeds its approved total spend cap",
    ):
        PUBLIC_TOOL._verify_campaign_spend_rows(overspent, manifest)


def test_public_basis_never_creates_missing_upstream_lifecycle_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = tmp_path / "unexpected-lifecycle-artifact"
    observed_checks: list[bool] = []

    def missing_lifecycle(_root: Path, *, check: bool) -> dict[str, Any]:
        observed_checks.append(check)
        if not check:
            created.write_text("created\n", encoding="utf-8")
        raise ValueError("prepared lifecycle relation bundle is unavailable")

    monkeypatch.setattr(
        PUBLIC_TOOL,
        "build_baseline_release_definition_basis",
        missing_lifecycle,
    )
    with pytest.raises(ValueError, match="lifecycle relation bundle is unavailable"):
        PUBLIC_TOOL.build_public_release_definition_basis(
            ROOT,
            decided_at="2026-08-05T12:00:00Z",
            check=False,
        )
    assert observed_checks == [True]
    assert not created.exists()


def test_public_basis_rejects_a_repeated_manifest_pair(
    monkeypatch: pytest.MonkeyPatch,
    baseline_basis: Mapping[str, Any],
) -> None:
    manifest = PUBLIC_TOOL._qualification_manifest(ROOT)

    class RepeatedManifest:
        sources = manifest.sources
        jobs = (manifest.jobs[0],) * 6
        record = manifest.record

    monkeypatch.setattr(
        PUBLIC_TOOL,
        "build_baseline_release_definition_basis",
        lambda _root, *, check: _copy(baseline_basis),
    )
    monkeypatch.setattr(
        PUBLIC_TOOL,
        "_qualification_manifest",
        lambda _root: RepeatedManifest(),
    )
    monkeypatch.setattr(
        PUBLIC_TOOL,
        "verify_prepared_vocabulary_atlas_v1_qualification_jobs",
        lambda _manifest, *, repository_root: {"jobCount": 6},
    )
    monkeypatch.setattr(
        PUBLIC_TOOL,
        "_production_job",
        lambda _root, **kwargs: (
            {
                "job": kwargs["public_job"],
                "sourceReleaseId": kwargs["source"]["releaseId"],
                "targetReleaseId": kwargs["target"]["releaseId"],
                "runReceiptPath": "output/test/qualification-receipt.json",
                "runReceiptFileDigest": "sha256:" + "1" * 64,
                "runReceiptContentDigest": "sha256:" + "2" * 64,
            },
            None,
            0,
            {
                "approvedTotalSpendCapUsd": "112.000000",
                "authorityFileDigest": "sha256:" + "a" * 64,
                "authorityId": "urn:ref:test:production-spend-authority",
                "authorityRecordDigest": "sha256:" + "b" * 64,
                "batchPlanDigest": "sha256:" + "c" * 64,
                "batchPolicyDigest": "sha256:" + "d" * 64,
                "committedSpendUsd": 0.0,
                "jobKey": kwargs["planned_job"]["key"],
                "runSpendCapUsd": "1.100000",
            },
        ),
    )

    with pytest.raises(
        PUBLIC_TOOL.PublicReleasePreparationError,
        match="do not map uniquely",
    ):
        PUBLIC_TOOL.build_public_release_definition_basis(
            ROOT,
            decided_at="2026-08-05T12:00:00Z",
        )


def test_catalog_verifier_rejects_noncanonical_exact_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_job = "crs-policy-federal-register"
    source_release = "urn:ref:test:source"
    target_release = "urn:ref:test:target"
    catalog = {
        "coverageMode": qual.PRODUCTION_COVERAGE_MODE,
        "generatedAt": "2026-08-05T12:00:00Z",
        "generationPolicy": qual.PRODUCTION_CANDIDATE_GENERATION_POLICY,
        "productionFloor": qual.PRODUCTION_FLOOR,
        "proposedRelation": qual.PROPOSED_RELATION,
        "protocol": qual.PROTOCOL,
        "seed": qual.GENERATION_SEED,
        "sourceManifestDigest": "sha256:" + "1" * 64,
        "targetManifestDigest": "sha256:" + "2" * 64,
        "limits": None,
        "total": 1,
        "candidates": [
            {
                "candidateId": "urn:ref:test:candidate",
                "source": {"release": source_release},
                "target": {"release": target_release},
            }
        ],
    }
    payload = json.dumps(catalog, indent=2).encode("utf-8")
    output = tmp_path / "job"
    output.mkdir()
    (output / "candidates.json").write_bytes(payload)
    digest = sha256_digest(payload)
    monkeypatch.setitem(
        release_contract._PUBLIC_V1_PRODUCTION_CATALOGS,
        public_job,
        (1, digest),
    )

    with pytest.raises(
        PUBLIC_TOOL.PublicReleasePreparationError,
        match="bytes are not canonical",
    ):
        PUBLIC_TOOL._verify_catalog(
            tmp_path,
            public_job=public_job,
            planned_job={
                "outputPath": "job",
                "generatedAt": "2026-08-05T12:00:00Z",
            },
            source={
                "releaseId": source_release,
                "manifestDigest": "sha256:" + "1" * 64,
            },
            target={
                "releaseId": target_release,
                "manifestDigest": "sha256:" + "2" * 64,
            },
            policy={
                "coverageMode": qual.PRODUCTION_COVERAGE_MODE,
                "generationPolicy": qual.PRODUCTION_CANDIDATE_GENERATION_POLICY,
                "productionFloor": qual.PRODUCTION_FLOOR,
                "proposedRelation": qual.PROPOSED_RELATION,
                "protocol": qual.PROTOCOL,
                "seed": qual.GENERATION_SEED,
            },
            run={
                "candidateCatalog": {
                    "file": "candidates.json",
                    "fileDigest": digest,
                    "total": 1,
                }
            },
        )


def test_public_job_rejects_accounting_reclassified_as_a_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "job"
    output.mkdir()
    (output / "qualification-receipt.json").write_bytes(canonical_json_bytes({}))
    candidate_id = "urn:ref:test:candidate"
    policy = {
        "generationPolicy": qual.PRODUCTION_CANDIDATE_GENERATION_POLICY,
        "productionFloor": qual.PRODUCTION_FLOOR,
        "protocol": qual.PROTOCOL,
    }
    run = {
        "coverageMode": qual.PRODUCTION_COVERAGE_MODE,
        "productionReady": True,
        "sourceManifestDigest": "sha256:" + "1" * 64,
        "targetManifestDigest": "sha256:" + "2" * 64,
        "candidateGenerationPolicy": policy["generationPolicy"],
        "productionFloor": policy["productionFloor"],
        "protocol": policy["protocol"],
        "providerBatchEvidence": {"judging": {}, "scoring": {}},
        "counts": {"generated": 1},
        "candidateAccounting": [
            {
                "candidateId": candidate_id,
                "generationClass": "randomNegativeControl",
                "control": True,
                "disposition": "controlled",
            }
        ],
    }
    monkeypatch.setattr(
        PUBLIC_TOOL.qual,
        "validate_qualification_run_receipt",
        lambda _record: run,
    )
    monkeypatch.setattr(
        PUBLIC_TOOL.qbatch,
        "verify_run_provider_batch_evidence",
        lambda _path, _run: {},
    )
    monkeypatch.setattr(
        PUBLIC_TOOL,
        "_verify_catalog",
        lambda *_args, **_kwargs: (
            {
                candidate_id: {
                    "candidateId": candidate_id,
                    "generationClass": "normalizedLabelEquality",
                }
            },
            "job/candidates.json",
            "sha256:" + "3" * 64,
        ),
    )

    with pytest.raises(
        PUBLIC_TOOL.PublicReleasePreparationError,
        match="generation class differs from its exact catalog row",
    ):
        PUBLIC_TOOL._production_job(
            tmp_path,
            public_job="crs-policy-federal-register",
            planned_job={"outputPath": "job"},
            source={
                "releaseId": "urn:ref:test:source",
                "manifestDigest": run["sourceManifestDigest"],
            },
            target={
                "releaseId": "urn:ref:test:target",
                "manifestDigest": run["targetManifestDigest"],
            },
            policy=policy,
        )


def test_relation_verifier_closes_admissions_and_rejects_a_changed_relation(
    tmp_path: Path,
    baseline_basis: Mapping[str, Any],
) -> None:
    del baseline_basis
    baseline = ROOT / "output/vocabulary-atlas-v1-rc1/qualification-baseline/elsst-icpsr"
    destination = tmp_path / "job/relation-assertions"
    destination.mkdir(parents=True)
    for name in ("qualification-receipt.json", "crosswalk-bundle.json"):
        shutil.copy2(baseline / name, destination.parent / name)
    for name in ("bundle-manifest.json", "relation-assertions.json"):
        shutil.copy2(baseline / "relation-assertions-v2" / name, destination / name)
    relation = json.loads((destination / "relation-assertions.json").read_text())
    run_path = destination.parent / "qualification-receipt.json"
    run = json.loads(run_path.read_text())
    crosswalk = json.loads((destination.parent / "crosswalk-bundle.json").read_text())
    crosswalk_candidates = {row["id"]: row for row in crosswalk["mappingCandidates"]}
    admitted = {pin["candidate"]["id"]: pin["relation"] for pin in relation["machineProofPins"]}
    release_pins = {pin["releaseId"]: pin for pin in relation["releasePins"]}
    source_id = "https://elsst.cessda.eu/id/6"
    target_id = next(release_id for release_id in release_pins if release_id != source_id)
    arguments = {
        "public_job": "elsst-icpsr",
        "output_path": "job",
        "source": {
            "releaseId": source_id,
            "manifestDigest": release_pins[source_id]["manifestDigest"],
        },
        "target": {
            "releaseId": target_id,
            "manifestDigest": release_pins[target_id]["manifestDigest"],
        },
        "run_path": "job/qualification-receipt.json",
        "run_file_digest": sha256_digest(run_path.read_bytes()),
        "run": run,
        "crosswalk_path": "job/crosswalk-bundle.json",
        "crosswalk_candidates": crosswalk_candidates,
    }

    descriptor = PUBLIC_TOOL._verify_relation_bundle(
        tmp_path,
        admitted=admitted,
        **arguments,
    )
    assert descriptor is not None
    assert descriptor["key"] == "production-elsst-icpsr"
    assert len(descriptor["machineProofs"]) == len(admitted)

    changed = dict(admitted)
    first = next(iter(changed))
    changed[first] = "http://www.w3.org/2004/02/skos/core#exactMatch"
    with pytest.raises(
        PUBLIC_TOOL.PublicReleasePreparationError,
        match="proofs differ from admitted candidates",
    ):
        PUBLIC_TOOL._verify_relation_bundle(
            tmp_path,
            admitted=changed,
            **arguments,
        )

    fabricated = _fabricate_resealed_question_digest(relation)
    relation_payload = canonical_json_bytes(fabricated)
    (destination / "relation-assertions.json").write_bytes(relation_payload)
    manifest_path = destination / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["bundleId"] = fabricated["id"]
    manifest["contentDigest"] = fabricated["contentDigest"]
    manifest["artifacts"][0]["sha256"] = sha256_digest(relation_payload)
    manifest["artifacts"][0]["byteLength"] = len(relation_payload)
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    with pytest.raises(
        PUBLIC_TOOL.PublicReleasePreparationError,
        match="differs from the exact reproduced machine proof",
    ):
        PUBLIC_TOOL._verify_relation_bundle(
            tmp_path,
            admitted=admitted,
            **arguments,
        )


def test_relation_verifier_represents_zero_admissions_without_a_bundle(
    tmp_path: Path,
) -> None:
    arguments = {
        "public_job": "crs-subjects-crs-policy",
        "output_path": "job",
        "source": {"releaseId": "urn:ref:test:source", "manifestDigest": "sha256:" + "1" * 64},
        "target": {"releaseId": "urn:ref:test:target", "manifestDigest": "sha256:" + "2" * 64},
        "run_path": "job/qualification-receipt.json",
        "run_file_digest": "sha256:" + "3" * 64,
        "run": {},
        "crosswalk_path": "job/crosswalk-bundle.json",
        "crosswalk_candidates": {},
        "admitted": {},
    }
    assert PUBLIC_TOOL._verify_relation_bundle(tmp_path, **arguments) is None

    stale = tmp_path / "job/relation-assertions"
    stale.mkdir(parents=True)
    with pytest.raises(
        PUBLIC_TOOL.PublicReleasePreparationError,
        match="stale relation output",
    ):
        PUBLIC_TOOL._verify_relation_bundle(tmp_path, **arguments)


def test_seal_relations_closes_catalog_lineage_for_zero_admissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "run"
    output.mkdir()
    (output / "qualification-receipt.json").write_bytes(canonical_json_bytes({}))
    candidate_id = "urn:ref:test:candidate"
    run = {
        "coverageMode": qual.PRODUCTION_COVERAGE_MODE,
        "productionReady": True,
        "candidateCatalog": {"file": "candidates.json"},
        "bundle": {
            "file": "crosswalk-bundle.json",
            "id": "urn:ref:test:crosswalk",
            "fileDigest": "sha256:" + "1" * 64,
            "bundleDigest": "sha256:" + "2" * 64,
        },
        "receiptLog": {"file": "receipts.jsonl"},
        "scoring": {"receiptLog": {"file": "scoring-receipts.jsonl"}},
        "providerBatchEvidence": None,
        "candidateAccounting": [
            {
                "candidateId": candidate_id,
                "generationClass": "normalizedLabelEquality",
                "control": False,
                "disposition": "rejected",
            }
        ],
        "counts": {"scorerReceipts": 0},
        "id": "urn:ref:test:qualification-run",
        "contentDigest": "sha256:" + "3" * 64,
    }

    class EmptyBundle:
        identifier = "urn:ref:test:crosswalk"

        @staticmethod
        def to_dict() -> dict[str, Any]:
            return {
                "mappingCandidates": [
                    {
                        "id": candidate_id,
                        "sourceRelease": "urn:ref:test:source",
                        "targetRelease": "urn:ref:test:target",
                    }
                ]
            }

        @staticmethod
        def adjudicated_relations() -> dict[str, str]:
            return {}

    monkeypatch.setattr(RUNNER.qual, "validate_qualification_run_receipt", lambda _row: run)
    monkeypatch.setattr(
        RUNNER,
        "_verify_run_file_pin",
        lambda _root, pin: output / str(pin["file"]),
    )
    monkeypatch.setattr(
        RUNNER,
        "_read_json",
        lambda _path: {
            "candidates": [
                {
                    "candidateId": candidate_id,
                    "generationClass": "normalizedLabelEquality",
                }
            ]
        },
    )
    monkeypatch.setattr(RUNNER.CrosswalkBundle, "open", lambda *_args, **_kwargs: EmptyBundle())
    monkeypatch.setattr(RUNNER, "_verify_candidate_receipt_pins", lambda *_args, **_kwargs: None)
    args = argparse.Namespace(output=output, relation_output="relation-assertions")

    assert RUNNER.command_seal_relations(args) == 0
    assert json.loads(capsys.readouterr().out) == {
        "mappingAssertions": 0,
        "sourceRun": {
            "id": run["id"],
            "contentDigest": run["contentDigest"],
        },
        "status": "noAdmittedMappings",
    }
    assert not (output / "relation-assertions").exists()

    accounting = run["candidateAccounting"][0]
    accounting.update(
        {
            "generationClass": "randomNegativeControl",
            "control": True,
            "disposition": "controlled",
        }
    )
    with pytest.raises(SystemExit, match="generation class differs from its exact catalog row"):
        RUNNER.command_seal_relations(args)
    accounting.update(
        {
            "generationClass": "normalizedLabelEquality",
            "control": False,
            "disposition": "rejected",
        }
    )

    (output / "relation-assertions").mkdir()
    with pytest.raises(SystemExit, match="stale relation output"):
        RUNNER.command_seal_relations(args)
