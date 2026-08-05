"""One explicit, local spend authority for all six Atlas v1 jobs."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from refspec import binding
from refspec.atlas import qualification as qual
from refspec.atlas import qualification_batch as qbatch
from refspec.atlas import qualification_spend as spend
from refspec.atlas.qualification_jobs import (
    EXPECTED_JOB_PAIRS,
    EXPECTED_SOURCE_KEYS,
    QUALIFICATION_POLICY,
    WORKFLOW,
    VocabularyAtlasV1QualificationJobs,
    read_vocabulary_atlas_v1_qualification_jobs,
    seal_vocabulary_atlas_v1_qualification_jobs,
)
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)

ROOT = Path(__file__).resolve().parents[1]
TRACKED_MANIFEST = (
    ROOT / "portfolio/vocabulary-atlas-v1-production-qualification-jobs.json"
)
APPROVED_BY = "urn:ref:actor:vocabulary-atlas-v1-spend-review"
APPROVED_AT = "2026-08-05T14:00:00Z"
APPROVED_TOTAL = "112.00"


def _write(path: Path, value: object) -> str:
    payload = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256_digest(payload)


def _write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> str:
    payload = b"".join(canonical_json_bytes(row) for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256_digest(payload)


def _concept_record(concept: qual.AtlasConcept) -> dict[str, Any]:
    return {
        "member": concept.member,
        "prefLabel": concept.pref_label,
        "release": concept.release,
        "vocabulary": concept.vocabulary,
    }


def _candidate_row(
    source_release: str,
    target_release: str,
    *,
    index: int,
) -> dict[str, Any]:
    label = f"Policy area {index}"
    pair = qual.CandidatePair(
        source=qual.AtlasConcept(
            member=f"{source_release}:member:{index}",
            release=source_release,
            pref_label=label,
            vocabulary=f"source-{index}",
        ),
        target=qual.AtlasConcept(
            member=f"{target_release}:member:{index}",
            release=target_release,
            pref_label=label,
            vocabulary=f"target-{index}",
        ),
        generation_class="normalizedLabelEquality",
        evidence={
            "method": "normalized-preferred-label-equality",
            "normalizedLabel": label.casefold(),
            "version": "1",
        },
        generation_policy=qual.PRODUCTION_CANDIDATE_GENERATION_POLICY,
    )
    entry = qual.assemble_candidate(
        pair,
        generated_at="2026-08-04T23:00:00Z",
        readings=(),
        protocol=qual.PROTOCOL,
    )
    context = next(
        artifact for artifact in entry.artifacts if artifact.role == "inputContext"
    )
    return {
        "candidateId": entry.candidate.identifier,
        "evidence": dict(pair.evidence),
        "generationClass": pair.generation_class,
        "generationPolicy": pair.generation_policy,
        "inputDigest": context.content_digest,
        "scoringInputDigest": qual.scoring_input_digest(pair),
        "source": _concept_record(pair.source),
        "target": _concept_record(pair.target),
    }


def _fixture_manifest(root: Path) -> VocabularyAtlasV1QualificationJobs:
    releases = {
        key: f"urn:test:release:{key}"
        for key in EXPECTED_SOURCE_KEYS
    }
    sources: list[dict[str, str]] = []
    for key in sorted(EXPECTED_SOURCE_KEYS):
        relative = f"inputs/{key}.json"
        digest = _write(root / relative, {"key": key})
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
                "manifestDigest": digest,
                "releaseId": releases[key],
                "vocabulary": key,
            }
        )
    jobs = [
        {
            "generatedAt": "2026-08-04T23:00:00Z",
            "key": f"{source}--{target}",
            "outputPath": f"output/qualification/{source}--{target}",
            "sourceKey": source,
            "targetKey": target,
        }
        for source, target in sorted(
            EXPECTED_JOB_PAIRS,
            key=lambda pair: f"{pair[0]}--{pair[1]}",
        )
    ]
    record = seal_vocabulary_atlas_v1_qualification_jobs(
        {
            "type": "VocabularyAtlasV1ProductionQualificationJobs",
            "schemaVersion": "1.0",
            "releaseName": "vocabulary-atlas-v1",
            "qualificationPolicy": dict(QUALIFICATION_POLICY),
            "workflow": copy.deepcopy(WORKFLOW),
            "sources": sources,
            "jobs": jobs,
        }
    )
    manifest_path = root / "portfolio/jobs.json"
    _write(manifest_path, record)
    manifest = read_vocabulary_atlas_v1_qualification_jobs(manifest_path)
    sources_by_key = {row["key"]: row for row in manifest.sources}
    for index, job in enumerate(manifest.jobs, start=1):
        source = sources_by_key[job["sourceKey"]]
        target = sources_by_key[job["targetKey"]]
        output = root / job["outputPath"]
        for role, endpoint in (("source", source), ("target", target)):
            _write(
                output / f"concepts-{role}.json",
                {
                    "conceptCount": 1,
                    "concepts": [],
                    "language": "en",
                    "manifestDigest": endpoint["manifestDigest"],
                    "referenceRelease": endpoint["releaseId"],
                    "role": role,
                    "vocabulary": endpoint["vocabulary"],
                },
            )
        candidates = [
            _candidate_row(
                source["releaseId"],
                target["releaseId"],
                index=candidate_index,
            )
            for candidate_index in (index, 100 + index)
        ]
        _write(
            output / "candidates.json",
            {
                "candidates": candidates,
                "coverageMode": qual.PRODUCTION_COVERAGE_MODE,
                "generatedAt": job["generatedAt"],
                "generationPolicy": qual.PRODUCTION_CANDIDATE_GENERATION_POLICY,
                "limits": None,
                "productionFloor": qual.PRODUCTION_FLOOR,
                "proposedRelation": qual.PROPOSED_RELATION,
                "protocol": qual.PROTOCOL,
                "seed": qual.GENERATION_SEED,
                "sourceManifestDigest": source["manifestDigest"],
                "targetManifestDigest": target["manifestDigest"],
                "total": len(candidates),
            },
        )
    return manifest


@pytest.fixture
def local_campaign(
    tmp_path: Path,
) -> tuple[Path, VocabularyAtlasV1QualificationJobs]:
    root = tmp_path / "repository"
    root.mkdir()
    return root, _fixture_manifest(root)


def _seal(
    root: Path,
    manifest: VocabularyAtlasV1QualificationJobs,
) -> dict[str, Any]:
    return spend.seal_vocabulary_atlas_v1_production_spend_authority(
        manifest,
        repository_root=root,
        approved_by=APPROVED_BY,
        approved_at=APPROVED_AT,
        approved_total_spend_cap_usd=APPROVED_TOTAL,
    )


def _sidecar_authority(
    root: Path,
    authority_path: Path,
    authority: spend.VocabularyAtlasV1ProductionSpendAuthority,
    job_key: str,
) -> dict[str, Any]:
    allocation = authority.job(job_key)
    return {
        "approvedTotalSpendCapUsd": authority.record[
            "approvedTotalSpendCapUsd"
        ],
        "authorityFile": authority_path.relative_to(root).as_posix(),
        "authorityFileDigest": authority.file_digest,
        "authorityId": authority.identifier,
        "authorityRecordDigest": authority.record_digest,
        "batchPlanDigest": allocation["batchPlanDigest"],
        "batchPolicyDigest": authority.batch_policy_digest,
        "jobKey": allocation["jobKey"],
        "modelsByFamily": dict(
            authority.record["batchPolicy"]["modelsByFamily"]
        ),
        "runSpendCapUsd": allocation["runSpendCapUsd"],
    }


def test_current_six_job_authority_recomputes_the_exact_25_row_plan_without_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = read_vocabulary_atlas_v1_qualification_jobs(TRACKED_MANIFEST)

    def provider_call_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("spend-authority sealing must remain local")

    monkeypatch.setattr(qbatch, "default_transport", provider_call_forbidden)
    monkeypatch.setattr(qual, "list_models", provider_call_forbidden)

    record = _seal(ROOT, manifest)

    assert record["providerCalls"] is False
    assert record["approvedTotalSpendCapUsd"] == "112.000000"
    assert record["allocatedTotalSpendCapUsd"] == "112.000000"
    assert record["candidateTotal"] == 12_313
    assert record["providerRequestCount"] == 1_488
    assert record["providerJobCount"] == 27
    assert record["projectedTotalSpendUsd"] == "109.903535"
    assert record["batchPolicy"]["modelResolution"] == "exactMatchOnly"
    assert {
        row["jobKey"]: (row["projectedCostUsd"], row["runSpendCapUsd"])
        for row in record["jobs"]
    } == {
        "crs-legislative-subjects--crs-policy-areas": ("1.040396", "1.100000"),
        "crs-legislative-subjects--federal-register-thesaurus-2025": (
            "3.266306",
            "3.500000",
        ),
        "crs-policy-areas--federal-register-thesaurus-2025": (
            "0.979159",
            "1.000000",
        ),
        "elsst-r6--icpsr-subject-thesaurus": ("69.025621", "70.000000"),
        "federal-register-thesaurus-2025--elsst-r6": (
            "20.060778",
            "20.500000",
        ),
        "federal-register-thesaurus-2025--icpsr-subject-thesaurus": (
            "15.531275",
            "15.900000",
        ),
    }


def test_authority_is_canonical_content_addressed_and_reopens(
    local_campaign: tuple[Path, VocabularyAtlasV1QualificationJobs],
) -> None:
    root, manifest = local_campaign
    record = _seal(root, manifest)
    basis = {
        key: value
        for key, value in record.items()
        if key not in {"id", "recordDigest"}
    }
    path = root / "output/control/spend-authority.json"
    payload = canonical_json_bytes(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)

    opened = spend.read_vocabulary_atlas_v1_production_spend_authority(
        path,
        manifest=manifest,
        repository_root=root,
    )

    assert record["recordDigest"] == binding.canonical_sha256(basis)
    assert record["id"] == (
        spend.VOCABULARY_ATLAS_V1_PRODUCTION_SPEND_AUTHORITY_ID_PREFIX
        + record["recordDigest"].removeprefix("sha256:")
    )
    assert opened.artifact_bytes == payload
    assert opened.file_digest == sha256_digest(payload)
    assert opened.approved_total_spend_cap_usd == 112.0
    assert opened.batch_policy_digest == binding.canonical_sha256(
        plain_json(opened.record["batchPolicy"])
    )
    assert opened.job(manifest.jobs[0]["key"])["outputPath"] == manifest.jobs[0][
        "outputPath"
    ]
    assert opened.job_for_output_path(manifest.jobs[0]["outputPath"])[
        "jobKey"
    ] == manifest.jobs[0]["key"]


@pytest.mark.parametrize(
    ("approved_by", "approved_at", "approved_total", "message"),
    [
        ("reviewer", APPROVED_AT, APPROVED_TOTAL, "absolute IRI"),
        (APPROVED_BY, "2026-08-05T14:00:00", APPROVED_TOTAL, "time zone"),
        (APPROVED_BY, APPROVED_AT, "111.99", r"fixed \$112\.00 allocation"),
        (APPROVED_BY, APPROVED_AT, "nan", "positive finite USD"),
        (APPROVED_BY, APPROVED_AT, True, "positive finite USD"),
    ],
)
def test_sealing_requires_an_explicit_valid_approval(
    local_campaign: tuple[Path, VocabularyAtlasV1QualificationJobs],
    approved_by: object,
    approved_at: object,
    approved_total: object,
    message: str,
) -> None:
    root, manifest = local_campaign
    with pytest.raises(
        spend.VocabularyAtlasV1ProductionSpendAuthorityError,
        match=message,
    ):
        spend.seal_vocabulary_atlas_v1_production_spend_authority(
            manifest,
            repository_root=root,
            approved_by=approved_by,  # type: ignore[arg-type]
            approved_at=approved_at,  # type: ignore[arg-type]
            approved_total_spend_cap_usd=approved_total,
        )


def test_exact_plan_must_fit_its_fixed_run_allocation(
    monkeypatch: pytest.MonkeyPatch,
    local_campaign: tuple[Path, VocabularyAtlasV1QualificationJobs],
) -> None:
    root, manifest = local_campaign
    caps = dict(spend.FIXED_RUN_SPEND_CAPS_USD)
    first = manifest.jobs[0]["key"]
    last = manifest.jobs[-1]["key"]
    transferred = caps[first] - Decimal("0.000001")
    caps[first] = Decimal("0.000001")
    caps[last] += transferred
    monkeypatch.setattr(spend, "FIXED_RUN_SPEND_CAPS_USD", caps)

    with pytest.raises(
        spend.VocabularyAtlasV1ProductionSpendAuthorityError,
        match="exact 25-row plan projects",
    ):
        _seal(root, manifest)


def test_reopening_detects_candidate_catalog_drift(
    local_campaign: tuple[Path, VocabularyAtlasV1QualificationJobs],
) -> None:
    root, manifest = local_campaign
    record = _seal(root, manifest)
    authority_path = root / "output/control/spend-authority.json"
    _write(authority_path, record)
    catalog_path = root / manifest.jobs[0]["outputPath"] / "candidates.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["candidates"][0]["source"]["prefLabel"] = "Changed policy area"
    _write(catalog_path, catalog)

    with pytest.raises(
        spend.VocabularyAtlasV1ProductionSpendAuthorityError,
        match="identity differs from its exact current plans",
    ):
        spend.read_vocabulary_atlas_v1_production_spend_authority(
            authority_path,
            manifest=manifest,
            repository_root=root,
        )


def test_reopening_rejects_noncanonical_or_tampered_authority_bytes(
    local_campaign: tuple[Path, VocabularyAtlasV1QualificationJobs],
) -> None:
    root, manifest = local_campaign
    record = _seal(root, manifest)
    path = root / "output/control/spend-authority.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(
        spend.VocabularyAtlasV1ProductionSpendAuthorityError,
        match="bytes are not canonical",
    ):
        spend.read_vocabulary_atlas_v1_production_spend_authority(
            path,
            manifest=manifest,
            repository_root=root,
        )

    forged = copy.deepcopy(record)
    forged["jobs"][0]["runSpendCapUsd"] = "2.000000"
    _write(path, forged)
    with pytest.raises(
        spend.VocabularyAtlasV1ProductionSpendAuthorityError,
        match="identity differs from its exact current plans",
    ):
        spend.read_vocabulary_atlas_v1_production_spend_authority(
            path,
            manifest=manifest,
            repository_root=root,
        )


def test_catalog_and_authority_paths_must_be_local_regular_files(
    tmp_path: Path,
    local_campaign: tuple[Path, VocabularyAtlasV1QualificationJobs],
) -> None:
    root, manifest = local_campaign
    record = _seal(root, manifest)
    outside = tmp_path / "outside-authority.json"
    _write(outside, record)
    with pytest.raises(
        spend.VocabularyAtlasV1ProductionSpendAuthorityError,
        match="stay inside the repository",
    ):
        spend.read_vocabulary_atlas_v1_production_spend_authority(
            outside,
            manifest=manifest,
            repository_root=root,
        )

    catalog = root / manifest.jobs[0]["outputPath"] / "candidates.json"
    retained = catalog.with_name("retained-candidates.json")
    catalog.rename(retained)
    catalog.symlink_to(retained.name)
    with pytest.raises(
        spend.VocabularyAtlasV1ProductionSpendAuthorityError,
        match="must not traverse a symlink",
    ):
        _seal(root, manifest)


def test_scoring_sidecar_must_reproduce_the_authority_model_and_initial_plan(
    local_campaign: tuple[Path, VocabularyAtlasV1QualificationJobs],
) -> None:
    root, manifest = local_campaign
    authority_path = root / "output/control/spend-authority.json"
    _write(authority_path, _seal(root, manifest))
    authority = spend.read_vocabulary_atlas_v1_production_spend_authority(
        authority_path,
        manifest=manifest,
        repository_root=root,
    )
    job = manifest.jobs[0]
    catalog = json.loads(
        (root / job["outputPath"] / "candidates.json").read_text(encoding="utf-8")
    )
    rows = qbatch.candidate_rows_from_catalog(catalog, work_kind="scoring")
    protocol = qual.SCORING_PROTOCOL
    plans: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    for family_name in (spend.SCORER_FAMILY,):
        family = qual.VALIDATOR_FAMILIES[family_name]
        model_id = spend.PRODUCTION_MODELS_BY_FAMILY[family_name]
        requests = qbatch.build_provider_requests(
            family,
            model_id,
            rows,
            protocol=protocol,
            work_kind="scoring",
            group_size=spend.REQUEST_GROUP_SIZE,
        )
        plans.extend(
            qbatch._planned_shard_record(
                family,
                model_id,
                shard,
                protocol=protocol,
                work_kind="scoring",
                group_size=spend.REQUEST_GROUP_SIZE,
            )
            for shard in qbatch.deterministic_request_shards(
                family,
                model_id,
                requests,
                protocol=protocol,
                    work_kind="scoring",
            )
        )
        jobs.append(
            {
                "family": family_name,
                "modelId": model_id,
                "workKind": "scoring",
            }
        )
    sidecar = {
        "jobs": jobs,
        "plannedShards": plans,
        "spendAuthority": _sidecar_authority(
            root,
            authority_path,
            authority,
            job["key"],
        ),
    }

    verified = spend.verify_vocabulary_atlas_v1_production_batch_sidecar(
        authority,
        sidecar,
        job_key=job["key"],
        work_kind="scoring",
        repository_root=root,
    )

    assert verified["initialShardCount"] == 1
    wrong_model = copy.deepcopy(sidecar)
    wrong_model["jobs"][0]["modelId"] += "-2026-08-05"
    with pytest.raises(
        spend.VocabularyAtlasV1ProductionSpendAuthorityError,
        match="model policy",
    ):
        spend.verify_vocabulary_atlas_v1_production_batch_sidecar(
            authority,
            wrong_model,
            job_key=job["key"],
            work_kind="scoring",
            repository_root=root,
        )

    missing_initial_plan = copy.deepcopy(sidecar)
    missing_initial_plan["plannedShards"][0]["maxRequestGroupSize"] = 1
    with pytest.raises(
        spend.VocabularyAtlasV1ProductionSpendAuthorityError,
        match="initial 25-row shards",
    ):
        spend.verify_vocabulary_atlas_v1_production_batch_sidecar(
            authority,
            missing_initial_plan,
            job_key=job["key"],
            work_kind="scoring",
            repository_root=root,
        )

    wrong_cost = copy.deepcopy(sidecar)
    wrong_cost["plannedShards"][0]["projectedCostUsd"] += 0.000001
    with pytest.raises(
        spend.VocabularyAtlasV1ProductionSpendAuthorityError,
        match="cost or coverage differs",
    ):
        spend.verify_vocabulary_atlas_v1_production_batch_sidecar(
            authority,
            wrong_cost,
            job_key=job["key"],
            work_kind="scoring",
            repository_root=root,
        )


def test_judging_sidecar_requires_complete_scoring_evidence(
    local_campaign: tuple[Path, VocabularyAtlasV1QualificationJobs],
) -> None:
    root, manifest = local_campaign
    authority_path = root / "output/control/spend-authority.json"
    _write(authority_path, _seal(root, manifest))
    authority = spend.read_vocabulary_atlas_v1_production_spend_authority(
        authority_path,
        manifest=manifest,
        repository_root=root,
    )
    job = manifest.jobs[0]

    with pytest.raises(
        spend.VocabularyAtlasV1ProductionSpendAuthorityError,
        match="scoring Batch sidecar does not exist",
    ):
        spend.verify_vocabulary_atlas_v1_production_batch_sidecar(
            authority,
            {
                "jobs": [],
                "plannedShards": [],
                "spendAuthority": _sidecar_authority(
                    root,
                    authority_path,
                    authority,
                    job["key"],
                ),
            },
            job_key=job["key"],
            work_kind="validation",
            repository_root=root,
        )


def test_judging_plan_reproduces_score_priority_and_refuses_tampering(
    monkeypatch: pytest.MonkeyPatch,
    local_campaign: tuple[Path, VocabularyAtlasV1QualificationJobs],
) -> None:
    root, manifest = local_campaign
    authority_path = root / "output/control/spend-authority.json"
    _write(authority_path, _seal(root, manifest))
    authority = spend.read_vocabulary_atlas_v1_production_spend_authority(
        authority_path,
        manifest=manifest,
        repository_root=root,
    )
    job = manifest.jobs[0]
    output = root / job["outputPath"]
    catalog_path = output / "candidates.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    scorer = qual.VALIDATOR_FAMILIES[spend.SCORER_FAMILY]
    scorer_model = spend.PRODUCTION_MODELS_BY_FAMILY[spend.SCORER_FAMILY]
    scoring_rows = qbatch.candidate_rows_from_catalog(catalog, work_kind="scoring")
    scoring_requests = qbatch.build_provider_requests(
        scorer,
        scorer_model,
        scoring_rows,
        protocol=qual.SCORING_PROTOCOL,
        work_kind="scoring",
        group_size=spend.REQUEST_GROUP_SIZE,
    )
    scoring_plans: list[dict[str, Any]] = []
    for order, shard in enumerate(
        qbatch.deterministic_request_shards(
            scorer,
            scorer_model,
            scoring_requests,
            protocol=qual.SCORING_PROTOCOL,
            work_kind="scoring",
        ),
        start=1,
    ):
        plan = qbatch._planned_shard_record(
            scorer,
            scorer_model,
            shard,
            protocol=qual.SCORING_PROTOCOL,
            work_kind="scoring",
            group_size=spend.REQUEST_GROUP_SIZE,
        )
        plan["planOrder"] = order
        scoring_plans.append(plan)
    scoring_sidecar = {
        "jobs": [
            {
                "family": spend.SCORER_FAMILY,
                "modelId": scorer_model,
                "workKind": "scoring",
            }
        ],
        "plannedShards": scoring_plans,
        "spendAuthority": _sidecar_authority(
            root,
            authority_path,
            authority,
            job["key"],
        ),
    }
    scoring_sidecar_path = output / "scoring-batch-jobs.json"
    scoring_sidecar_digest = _write(scoring_sidecar_path, scoring_sidecar)

    scoring_receipts: list[dict[str, Any]] = []
    for index, row in enumerate(scoring_rows):
        answer = {
            "task_id": qual.scoring_task_id(row.pair),
            "semantic_plausibility": 90 - (index * 20),
            "evidence_sufficiency": 40 + (index * 10),
            "likely_relation": "same" if index == 0 else "related",
            "reason": "priority only",
        }
        scoring_receipts.append(
            {
                "answer": answer,
                "candidate_id": row.candidate_id,
                "family": spend.SCORER_FAMILY,
                "input_digest": row.input_digest,
                "kind": "crosswalk_scoring",
                "model_id": scorer_model,
                "outcome": "completed",
                "protocol": qual.SCORING_PROTOCOL,
                "request_sha256": "sha256:" + f"{index + 1:x}" * 64,
                "response_sha256": "sha256:" + f"{index + 3:x}" * 64,
                "source_member": row.pair.source.member,
                "target_member": row.pair.target.member,
                "task_id": qual.scoring_task_id(row.pair),
            }
        )
    scoring_receipt_path = output / "scoring-receipts.jsonl"
    scoring_receipt_digest = _write_jsonl(scoring_receipt_path, scoring_receipts)
    provenance, ordered_ids = qual.scorer_priority_provenance(
        catalog,
        scoring_receipts,
        scorer_family=scorer,
        scorer_model_id=scorer_model,
        candidate_catalog_file_digest=sha256_digest(catalog_path.read_bytes()),
        scoring_receipt_log_file_digest=scoring_receipt_digest,
        scoring_sidecar_file_digest=scoring_sidecar_digest,
    )
    rank_by_id = {
        candidate_id: rank for rank, candidate_id in enumerate(ordered_ids)
    }
    judge_rows = [
        qbatch.CandidateRow(
            row.candidate_id,
            row.pair,
            row.input_digest,
            rank_by_id[row.candidate_id],
        )
        for row in qbatch.candidate_rows_from_catalog(
            catalog,
            work_kind="validation",
        )
    ]
    judging_plans: list[dict[str, Any]] = []
    judging_jobs: list[dict[str, Any]] = []
    plan_order = 0
    for family_name in spend.JUDGE_FAMILIES:
        family = qual.VALIDATOR_FAMILIES[family_name]
        model_id = spend.PRODUCTION_MODELS_BY_FAMILY[family_name]
        requests = qbatch.build_provider_requests(
            family,
            model_id,
            judge_rows,
            protocol=qbatch.run_protocol(catalog),
            work_kind="validation",
            group_size=spend.REQUEST_GROUP_SIZE,
        )
        for shard in qbatch.deterministic_request_shards(
            family,
            model_id,
            requests,
            protocol=qbatch.run_protocol(catalog),
            work_kind="validation",
        ):
            plan_order += 1
            plan = qbatch._planned_shard_record(
                family,
                model_id,
                shard,
                protocol=qbatch.run_protocol(catalog),
                work_kind="validation",
                group_size=spend.REQUEST_GROUP_SIZE,
            )
            plan["planOrder"] = plan_order
            judging_plans.append(plan)
        judging_jobs.append(
            {
                "family": family_name,
                "modelId": model_id,
                "workKind": "validation",
            }
        )
    judging_sidecar = {
        "jobs": judging_jobs,
        "plannedShards": judging_plans,
        "priorityProvenance": provenance,
        "spendAuthority": _sidecar_authority(
            root,
            authority_path,
            authority,
            job["key"],
        ),
    }
    monkeypatch.setattr(
        qbatch,
        "verify_provider_batch_evidence",
        lambda **_kwargs: {},
    )

    verified = spend.verify_vocabulary_atlas_v1_production_batch_sidecar(
        authority,
        judging_sidecar,
        job_key=job["key"],
        work_kind="validation",
        repository_root=root,
    )
    assert verified["priorityDigest"] == provenance["priorityDigest"]

    incomplete = scoring_receipts[:1]
    _write_jsonl(scoring_receipt_path, incomplete)
    with pytest.raises(
        spend.VocabularyAtlasV1ProductionSpendAuthorityError,
        match="complete scoring evidence does not reproduce",
    ):
        spend.verify_vocabulary_atlas_v1_production_batch_sidecar(
            authority,
            judging_sidecar,
            job_key=job["key"],
            work_kind="validation",
            repository_root=root,
        )

    changed = copy.deepcopy(scoring_receipts)
    changed[1]["answer"]["semantic_plausibility"] = 99
    _write_jsonl(scoring_receipt_path, changed)
    with pytest.raises(
        spend.VocabularyAtlasV1ProductionSpendAuthorityError,
        match="priority provenance differs",
    ):
        spend.verify_vocabulary_atlas_v1_production_batch_sidecar(
            authority,
            judging_sidecar,
            job_key=job["key"],
            work_kind="validation",
            repository_root=root,
        )

    _write_jsonl(scoring_receipt_path, scoring_receipts)
    changed_order = copy.deepcopy(judging_sidecar)
    changed_order["plannedShards"][0]["providerRequests"][0][
        "candidateIds"
    ].reverse()
    with pytest.raises(
        spend.VocabularyAtlasV1ProductionSpendAuthorityError,
        match="judging order differs from scorer priority",
    ):
        spend.verify_vocabulary_atlas_v1_production_batch_sidecar(
            authority,
            changed_order,
            job_key=job["key"],
            work_kind="validation",
            repository_root=root,
        )
