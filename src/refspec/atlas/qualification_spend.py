"""One explicit spend authority for all six Atlas v1 qualification jobs.

The provider runner enforces a hard cap inside one qualification directory.
This module turns one user-approved campaign ceiling into six immutable run
caps whose sum is the same ceiling.  Because the allocations do not overlap,
the global bound holds even when jobs run concurrently or a process restarts;
no mutable shared spend ledger is required.

Sealing is local and deterministic.  It reopens the approved six-job manifest,
verifies every prepared catalog, and rebuilds the exact 25-row scoring plan
plus a score-independent judging budget baseline.  Complete scorer evidence
later determines the exact judge order under the sealed priority policy.  This
module never creates a provider transport or reads a key.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, cast

from refspec import binding
from refspec.atlas import qualification as qual
from refspec.atlas import qualification_batch as qbatch
from refspec.atlas.qualification_jobs import (
    VocabularyAtlasV1QualificationJobs,
    VocabularyAtlasV1QualificationJobsError,
    verify_prepared_vocabulary_atlas_v1_qualification_jobs,
)
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

VOCABULARY_ATLAS_V1_PRODUCTION_SPEND_AUTHORITY_TYPE = (
    "VocabularyAtlasV1ProductionSpendAuthority"
)
VOCABULARY_ATLAS_V1_PRODUCTION_SPEND_AUTHORITY_VERSION = "1.0"
VOCABULARY_ATLAS_V1_PRODUCTION_SPEND_AUTHORITY_ID_PREFIX = (
    "urn:ref:vocabulary-atlas-v1-production-spend-authority:"
)

REQUEST_GROUP_SIZE = 25
SCORER_FAMILY = "openai"
JUDGE_FAMILIES = ("gemini", "openai")
MODEL_RESOLUTION_POLICY = "exactMatchOnly"
PRODUCTION_MODELS_BY_FAMILY: Mapping[str, str] = MappingProxyType(
    {
        "gemini": "models/gemini-3.6-flash",
        "openai": "gpt-5.6-terra",
    }
)

# One approved campaign ceiling, partitioned into non-overlapping run limits.
# The cents above each exact current projection leave bounded recovery room.
FIXED_RUN_SPEND_CAPS_USD: Mapping[str, Decimal] = MappingProxyType(
    {
        "crs-legislative-subjects--crs-policy-areas": Decimal("1.10"),
        "crs-legislative-subjects--federal-register-thesaurus-2025": Decimal(
            "3.50"
        ),
        "crs-policy-areas--federal-register-thesaurus-2025": Decimal("1.00"),
        "elsst-r6--icpsr-subject-thesaurus": Decimal("70.00"),
        "federal-register-thesaurus-2025--elsst-r6": Decimal("20.50"),
        "federal-register-thesaurus-2025--icpsr-subject-thesaurus": Decimal(
            "15.90"
        ),
    }
)
FIXED_TOTAL_SPEND_CAP_USD = sum(
    FIXED_RUN_SPEND_CAPS_USD.values(),
    start=Decimal(0),
)

_MONEY_QUANTUM = Decimal("0.000001")
_SHA256_PREFIX = "sha256:"
_BASIS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "approvedAt",
        "approvedBy",
        "approvedTotalSpendCapUsd",
        "allocatedTotalSpendCapUsd",
        "batchPolicy",
        "candidateTotal",
        "qualificationJobs",
        "jobs",
        "projectedTotalSpendUsd",
        "providerCalls",
        "providerJobCount",
        "providerRequestCount",
    }
)
_RECORD_FIELDS = _BASIS_FIELDS | {"id", "recordDigest"}
_BATCH_POLICY_FIELDS = frozenset(
    {
        "batchPricingFactor",
        "judgeFamilies",
        "judgingPlanResolution",
        "judgingPriorityPolicy",
        "modelResolution",
        "modelsByFamily",
        "requestGroupSize",
        "scorerFamily",
    }
)
_QUALIFICATION_JOBS_PIN_FIELDS = frozenset(
    {"fileDigest", "id", "recordDigest"}
)
_JOB_FIELDS = frozenset(
    {
        "batchPlanDigest",
        "candidateCatalog",
        "jobKey",
        "outputPath",
        "projectedCostUsd",
        "providerJobCount",
        "providerRequestCount",
        "runSpendCapUsd",
    }
)
_CATALOG_FIELDS = frozenset({"fileDigest", "path", "total"})


class VocabularyAtlasV1ProductionSpendAuthorityError(ValueError):
    """The campaign approval, fixed allocation, or local plan is invalid."""


def _plain(value: object) -> Any:
    return plain_json(value)


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} fields differ; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must be an object"
        )
    return cast(Mapping[str, Any], value)


def _require_sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must be an array"
        )
    return cast(Sequence[Any], value)


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must be non-empty trimmed text"
        )
    return value


def _require_digest(value: object, label: str) -> str:
    text = _require_text(value, label)
    if (
        not text.startswith(_SHA256_PREFIX)
        or len(text) != len(_SHA256_PREFIX) + 64
        or any(character not in "0123456789abcdef" for character in text[7:])
    ):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must be sha256:<64 lowercase hex>"
        )
    return text


def _require_actor(value: object) -> str:
    actor = _require_text(value, "spend authority approvedBy")
    issue = absolute_uri_issue(actor)
    if issue is not None:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "spend authority approvedBy must be an absolute IRI without credentials"
        )
    return actor


def _require_approved_at(value: object) -> str:
    text = _require_text(value, "spend authority approvedAt")
    try:
        return require_aware_datetime_text(
            text,
            label="spend authority approvedAt",
        )
    except SourceIdentityError as error:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(str(error)) from error


def _money(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must be positive finite USD"
        )
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must be positive finite USD"
        ) from error
    if not amount.is_finite() or amount <= 0:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must be positive finite USD"
        )
    if amount.quantize(_MONEY_QUANTUM) != amount:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must use at most six decimal places"
        )
    return amount


def _money_text(value: Decimal) -> str:
    return format(value.quantize(_MONEY_QUANTUM), ".6f")


def _canonical_plan_value(value: Any) -> Any:
    """Make the transient Batch plan safe for a canonical content digest."""

    if isinstance(value, float):
        if not math.isfinite(value):
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                "exact Batch plan contains a non-finite number"
            )
        return format(Decimal(str(value)), "f")
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_plan_value(child)
            for key, child in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_canonical_plan_value(child) for child in value]
    return value


def _resolve_root(path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink():
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "repository root must not be a symlink"
        )
    try:
        root = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "repository root does not exist"
        ) from error
    if not root.is_dir():
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "repository root must be a directory"
        )
    return root


def _safe_existing_file(root: Path, relative: str, *, label: str) -> Path:
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != relative
    ):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must be a normalized repository-relative path"
        )
    candidate = root.joinpath(*path.parts)
    cursor = root
    for part in path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                f"{label} must not traverse a symlink"
            )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except FileNotFoundError as error:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} does not exist"
        ) from error
    except ValueError as error:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must stay inside the repository"
        ) from error
    if not resolved.is_file():
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must be a regular file"
        )
    return resolved


def _decode_canonical_object(payload: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must be valid UTF-8 JSON"
        ) from error
    if not isinstance(value, Mapping):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must be an object"
        )
    if canonical_json_bytes(value) != payload:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} bytes are not canonical"
        )
    return cast(Mapping[str, Any], value)


def _read_catalog(
    root: Path,
    pin: Mapping[str, Any],
    *,
    job_key: str,
) -> Mapping[str, Any]:
    _require_exact_fields(pin, _CATALOG_FIELDS, f"{job_key} candidate catalog pin")
    relative = _require_text(pin.get("path"), f"{job_key} candidate catalog path")
    path = _safe_existing_file(
        root,
        relative,
        label=f"{job_key} candidate catalog",
    )
    payload = path.read_bytes()
    if sha256_digest(payload) != _require_digest(
        pin.get("fileDigest"),
        f"{job_key} candidate catalog fileDigest",
    ):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{job_key} candidate catalog differs from prepared verification"
        )
    catalog = _decode_canonical_object(
        payload,
        f"{job_key} candidate catalog",
    )
    total = pin.get("total")
    if (
        isinstance(total, bool)
        or not isinstance(total, int)
        or total <= 0
        or catalog.get("total") != total
    ):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{job_key} candidate catalog total differs"
        )
    if path.read_bytes() != payload:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{job_key} candidate catalog changed while planning"
        )
    return catalog


def _read_canonical_jsonl(
    root: Path,
    relative: str,
    *,
    label: str,
) -> tuple[Path, list[dict[str, Any]], str]:
    path = _safe_existing_file(root, relative, label=label)
    payload = path.read_bytes()
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must be UTF-8"
        ) from error
    rows: list[dict[str, Any]] = []
    reproduced = ""
    for index, line in enumerate(text.splitlines()):
        if not line:
            continue
        try:
            value = json.loads(
                line,
                object_pairs_hook=binding.reject_duplicate_keys,
                parse_constant=binding.reject_nonfinite_constant,
            )
        except (json.JSONDecodeError, ValueError) as error:
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                f"{label} row {index + 1} is invalid"
            ) from error
        if not isinstance(value, Mapping) or canonical_json_bytes(value) != (
            line + "\n"
        ).encode("utf-8"):
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                f"{label} row {index + 1} is not canonical"
            )
        rows.append(dict(value))
        reproduced += line + "\n"
    if not rows or reproduced.encode("utf-8") != payload:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} must contain canonical nonempty rows"
        )
    if path.read_bytes() != payload:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{label} changed while opening"
        )
    return path, rows, sha256_digest(payload)


def _batch_plan(catalog: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if set(PRODUCTION_MODELS_BY_FAMILY) != set(qual.VALIDATOR_FAMILIES) or any(
        model_id.removeprefix("models/")
        != qual.VALIDATOR_FAMILIES[family_name].requested_model
        for family_name, model_id in PRODUCTION_MODELS_BY_FAMILY.items()
    ):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "production model policy differs from the qualification families"
        )
    protocol = qbatch.run_protocol(catalog)
    judging_rows = qbatch.candidate_rows_from_catalog(
        catalog,
        work_kind="validation",
    )
    scoring_rows = qbatch.candidate_rows_from_catalog(
        catalog,
        work_kind="scoring",
    )
    plans = [
        qbatch.request_plan_summary(
            qual.VALIDATOR_FAMILIES[SCORER_FAMILY],
            PRODUCTION_MODELS_BY_FAMILY[SCORER_FAMILY],
            scoring_rows,
            protocol=qual.SCORING_PROTOCOL,
            work_kind="scoring",
            group_size=REQUEST_GROUP_SIZE,
        ),
        *[
            qbatch.request_plan_summary(
                qual.VALIDATOR_FAMILIES[family_name],
                PRODUCTION_MODELS_BY_FAMILY[family_name],
                judging_rows,
                protocol=protocol,
                work_kind="validation",
                group_size=REQUEST_GROUP_SIZE,
            )
            for family_name in JUDGE_FAMILIES
        ],
    ]
    plan = {
        "candidateCount": len(judging_rows),
        "jobs": plans,
        "judgingPlanResolution": "derivedFromCompleteScoringEvidence",
        "modelResolution": "notPerformed",
        "planningMode": "complete",
        "protocol": protocol,
        "providerCalls": False,
        "providerJobCount": sum(int(row["providerJobCount"]) for row in plans),
        "providerRequestCount": sum(
            int(row["providerRequestCount"]) for row in plans
        ),
        "requestGroupSizeLimit": REQUEST_GROUP_SIZE,
        "totalProjectedCostUsd": round(
            sum(float(row["projectedCostUsd"]) for row in plans),
            6,
        ),
    }
    canonical_plan = _canonical_plan_value(plan)
    binding.validate_canonical_value(canonical_plan)
    summary = {
        "batchPlanDigest": binding.canonical_sha256(canonical_plan),
        "projectedCostUsd": plan["totalProjectedCostUsd"],
        "providerJobCount": plan["providerJobCount"],
        "providerRequestCount": plan["providerRequestCount"],
    }
    return plan, summary


def _approval(
    *,
    approved_by: object,
    approved_at: object,
    approved_total_spend_cap_usd: object,
) -> tuple[str, str, Decimal]:
    actor = _require_actor(approved_by)
    timestamp = _require_approved_at(approved_at)
    approved_total = _money(
        approved_total_spend_cap_usd,
        "spend authority approvedTotalSpendCapUsd",
    )
    if approved_total != FIXED_TOTAL_SPEND_CAP_USD:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "approved total spend cap must equal the fixed $112.00 allocation"
        )
    return actor, timestamp, approved_total


def seal_vocabulary_atlas_v1_production_spend_authority(
    manifest: VocabularyAtlasV1QualificationJobs,
    *,
    repository_root: Path | str,
    approved_by: str,
    approved_at: str,
    approved_total_spend_cap_usd: object,
) -> dict[str, Any]:
    """Recompute and seal the exact six-job plan under one explicit approval."""

    actor, timestamp, approved_total = _approval(
        approved_by=approved_by,
        approved_at=approved_at,
        approved_total_spend_cap_usd=approved_total_spend_cap_usd,
    )
    if not isinstance(manifest, VocabularyAtlasV1QualificationJobs):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "spend authority requires a verified six-job manifest"
        )
    if not manifest.file_digest:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "spend authority requires the six-job manifest's exact file digest"
        )
    root = _resolve_root(repository_root)
    try:
        prepared = verify_prepared_vocabulary_atlas_v1_qualification_jobs(
            manifest,
            repository_root=root,
        )
    except VocabularyAtlasV1QualificationJobsError as error:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"production catalogs do not reopen: {error}"
        ) from error
    raw_catalogs = _require_sequence(
        prepared.get("candidateCatalogs"),
        "prepared candidate catalogs",
    )
    catalog_pins = {
        str(_require_mapping(row, "prepared candidate catalog").get("path")): _require_mapping(
            row,
            "prepared candidate catalog",
        )
        for row in raw_catalogs
    }
    expected_job_keys = set(FIXED_RUN_SPEND_CAPS_USD)
    manifest_job_keys = {str(job["key"]) for job in manifest.jobs}
    if (
        len(manifest.jobs) != 6
        or manifest_job_keys != expected_job_keys
        or len(catalog_pins) != 6
    ):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "spend authority requires the six exact production jobs and catalogs"
        )

    jobs: list[dict[str, Any]] = []
    for job in manifest.jobs:
        job_key = str(job["key"])
        output_path = str(job["outputPath"])
        catalog_relative = f"{output_path}/candidates.json"
        raw_pin = catalog_pins.get(catalog_relative)
        if raw_pin is None:
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                f"{job_key} has no exact prepared candidate catalog"
            )
        pin = {
            "fileDigest": _require_digest(
                raw_pin.get("fileDigest"),
                f"{job_key} candidate catalog fileDigest",
            ),
            "path": catalog_relative,
            "total": raw_pin.get("total"),
        }
        catalog = _read_catalog(root, pin, job_key=job_key)
        _plan, summary = _batch_plan(catalog)
        projected = _money(
            summary["projectedCostUsd"],
            f"{job_key} projected cost",
        )
        run_cap = FIXED_RUN_SPEND_CAPS_USD[job_key]
        if projected > run_cap:
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                f"{job_key} exact 25-row plan projects ${projected} above its "
                f"${run_cap} fixed run cap"
            )
        jobs.append(
            {
                "batchPlanDigest": summary["batchPlanDigest"],
                "candidateCatalog": pin,
                "jobKey": job_key,
                "outputPath": output_path,
                "projectedCostUsd": _money_text(projected),
                "providerJobCount": summary["providerJobCount"],
                "providerRequestCount": summary["providerRequestCount"],
                "runSpendCapUsd": _money_text(run_cap),
            }
        )

    allocated_total = sum(
        (_money(row["runSpendCapUsd"], "run spend cap") for row in jobs),
        start=Decimal(0),
    )
    if allocated_total != approved_total:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "fixed run allocations do not equal the approved total spend cap"
        )
    projected_total = sum(
        (_money(row["projectedCostUsd"], "projected job cost") for row in jobs),
        start=Decimal(0),
    )
    basis = {
        "type": VOCABULARY_ATLAS_V1_PRODUCTION_SPEND_AUTHORITY_TYPE,
        "schemaVersion": VOCABULARY_ATLAS_V1_PRODUCTION_SPEND_AUTHORITY_VERSION,
        "approvedAt": timestamp,
        "approvedBy": actor,
        "approvedTotalSpendCapUsd": _money_text(approved_total),
        "allocatedTotalSpendCapUsd": _money_text(allocated_total),
        "batchPolicy": {
            "batchPricingFactor": format(
                Decimal(str(qbatch.BATCH_PRICE_FACTOR)),
                "f",
            ),
            "judgeFamilies": list(JUDGE_FAMILIES),
            "judgingPlanResolution": "derivedFromCompleteScoringEvidence",
            "judgingPriorityPolicy": qual.SCORER_PRIORITY_POLICY,
            "modelResolution": MODEL_RESOLUTION_POLICY,
            "modelsByFamily": {
                name: PRODUCTION_MODELS_BY_FAMILY[name]
                for name in sorted(PRODUCTION_MODELS_BY_FAMILY)
            },
            "requestGroupSize": REQUEST_GROUP_SIZE,
            "scorerFamily": SCORER_FAMILY,
        },
        "candidateTotal": sum(
            cast(int, row["candidateCatalog"]["total"])
            for row in jobs
        ),
        "qualificationJobs": {
            "fileDigest": manifest.file_digest,
            "id": manifest.identifier,
            "recordDigest": manifest.record_digest,
        },
        "jobs": jobs,
        "projectedTotalSpendUsd": _money_text(projected_total),
        "providerCalls": False,
        "providerJobCount": sum(cast(int, row["providerJobCount"]) for row in jobs),
        "providerRequestCount": sum(
            cast(int, row["providerRequestCount"])
            for row in jobs
        ),
    }
    binding.validate_canonical_value(basis)
    digest = binding.canonical_sha256(basis)
    return {
        **basis,
        "id": (
            VOCABULARY_ATLAS_V1_PRODUCTION_SPEND_AUTHORITY_ID_PREFIX
            + digest.removeprefix(_SHA256_PREFIX)
        ),
        "recordDigest": digest,
    }


@dataclass(frozen=True, slots=True)
class VocabularyAtlasV1ProductionSpendAuthority:
    """A verified approval and its six non-overlapping run allocations."""

    record: Mapping[str, Any]
    file_digest: str

    def __init__(
        self,
        record: Mapping[str, Any],
        *,
        manifest: VocabularyAtlasV1QualificationJobs,
        repository_root: Path | str,
        file_digest: str = "",
    ) -> None:
        row = _require_mapping(record, "production spend authority record")
        _require_exact_fields(
            row,
            _RECORD_FIELDS,
            "production spend authority record",
        )
        expected = seal_vocabulary_atlas_v1_production_spend_authority(
            manifest,
            repository_root=repository_root,
            approved_by=_require_text(row.get("approvedBy"), "spend authority approvedBy"),
            approved_at=_require_text(row.get("approvedAt"), "spend authority approvedAt"),
            approved_total_spend_cap_usd=row.get("approvedTotalSpendCapUsd"),
        )
        if _plain(row) != expected:
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                "production spend authority identity differs from its exact current plans"
            )
        normalized_file_digest = ""
        if file_digest:
            normalized_file_digest = _require_digest(
                file_digest,
                "production spend authority file digest",
            )
            expected_file_digest = sha256_digest(canonical_json_bytes(expected))
            if normalized_file_digest != expected_file_digest:
                raise VocabularyAtlasV1ProductionSpendAuthorityError(
                    "production spend authority file digest differs from its canonical bytes"
                )
        object.__setattr__(
            self,
            "record",
            cast(Mapping[str, Any], deep_freeze_json(expected)),
        )
        object.__setattr__(self, "file_digest", normalized_file_digest)

    @property
    def identifier(self) -> str:
        return cast(str, self.record["id"])

    @property
    def record_digest(self) -> str:
        return cast(str, self.record["recordDigest"])

    @property
    def approved_total_spend_cap_usd(self) -> float:
        return float(self.record["approvedTotalSpendCapUsd"])

    @property
    def batch_policy_digest(self) -> str:
        return binding.canonical_sha256(_plain(self.record["batchPolicy"]))

    @property
    def jobs(self) -> tuple[Mapping[str, Any], ...]:
        return cast(tuple[Mapping[str, Any], ...], self.record["jobs"])

    @property
    def artifact_bytes(self) -> bytes:
        return canonical_json_bytes(self.record)

    def job(self, job_key: str) -> Mapping[str, Any]:
        matches = [row for row in self.jobs if row["jobKey"] == job_key]
        if len(matches) != 1:
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                f"production spend authority does not name job {job_key!r} exactly once"
            )
        return matches[0]

    def job_for_output_path(self, output_path: str) -> Mapping[str, Any]:
        """Return the one allocation governing an exact manifest output path."""

        matches = [row for row in self.jobs if row["outputPath"] == output_path]
        if len(matches) != 1:
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                "production spend authority does not govern output path "
                f"{output_path!r} exactly once"
            )
        return matches[0]


def _score_prioritized_judging_plan(
    authority: VocabularyAtlasV1ProductionSpendAuthority,
    allocation: Mapping[str, Any],
    catalog: Mapping[str, Any],
    *,
    root: Path,
    job_key: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], tuple[str, ...]]:
    output_path = _require_text(
        allocation.get("outputPath"),
        f"{job_key} output path",
    )
    scoring_sidecar_relative = f"{output_path}/scoring-batch-jobs.json"
    scoring_sidecar_path = _safe_existing_file(
        root,
        scoring_sidecar_relative,
        label=f"{job_key} scoring Batch sidecar",
    )
    scoring_sidecar_payload = scoring_sidecar_path.read_bytes()
    scoring_sidecar = _decode_canonical_object(
        scoring_sidecar_payload,
        f"{job_key} scoring Batch sidecar",
    )
    scoring_receipt_path, scoring_receipts, scoring_receipt_digest = (
        _read_canonical_jsonl(
            root,
            f"{output_path}/scoring-receipts.jsonl",
            label=f"{job_key} scoring receipt log",
        )
    )
    scoring_rows = qbatch.candidate_rows_from_catalog(
        catalog,
        work_kind="scoring",
    )
    try:
        qbatch.verify_provider_batch_evidence(
            sidecar_path=scoring_sidecar_path,
            families=qual.VALIDATOR_FAMILIES,
            rows=scoring_rows,
            receipts=scoring_receipts,
            work_kind="scoring",
        )
        verify_vocabulary_atlas_v1_production_batch_sidecar(
            authority,
            scoring_sidecar,
            job_key=job_key,
            work_kind="scoring",
            repository_root=root,
        )
        provenance, ordered_ids = qual.scorer_priority_provenance(
            catalog,
            scoring_receipts,
            scorer_family=qual.VALIDATOR_FAMILIES[SCORER_FAMILY],
            scorer_model_id=PRODUCTION_MODELS_BY_FAMILY[SCORER_FAMILY],
            candidate_catalog_file_digest=str(
                _require_mapping(
                    allocation.get("candidateCatalog"),
                    f"{job_key} candidate catalog pin",
                )["fileDigest"]
            ),
            scoring_receipt_log_file_digest=scoring_receipt_digest,
            scoring_sidecar_file_digest=sha256_digest(scoring_sidecar_payload),
        )
    except (qbatch.BatchError, qual.QualificationError) as error:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{job_key} complete scoring evidence does not reproduce: {error}"
        ) from error
    if scoring_receipt_path.read_bytes() == b"":
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{job_key} scoring receipt log is empty"
        )
    rank_by_id = {
        candidate_id: rank for rank, candidate_id in enumerate(ordered_ids)
    }
    judge_rows = [
        qbatch.CandidateRow(
            candidate_id=row.candidate_id,
            pair=row.pair,
            input_digest=row.input_digest,
            priority_rank=rank_by_id[row.candidate_id],
        )
        for row in qbatch.candidate_rows_from_catalog(
            catalog,
            work_kind="validation",
        )
    ]
    protocol = qbatch.run_protocol(catalog)
    plans = [
        qbatch.request_plan_summary(
            qual.VALIDATOR_FAMILIES[family_name],
            PRODUCTION_MODELS_BY_FAMILY[family_name],
            judge_rows,
            protocol=protocol,
            work_kind="validation",
            group_size=REQUEST_GROUP_SIZE,
        )
        for family_name in JUDGE_FAMILIES
    ]
    return plans, provenance, ordered_ids


def verify_vocabulary_atlas_v1_production_batch_sidecar(
    authority: VocabularyAtlasV1ProductionSpendAuthority,
    sidecar: Mapping[str, Any],
    *,
    job_key: str,
    work_kind: qbatch.WorkKind,
    repository_root: Path | str,
) -> dict[str, Any]:
    """Match one runtime sidecar to the authority's exact initial Batch plan."""

    if not isinstance(authority, VocabularyAtlasV1ProductionSpendAuthority):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "production Batch verification requires a reopened spend authority"
        )
    allocation = authority.job(job_key)
    root = _resolve_root(repository_root)
    sidecar_authority = _require_mapping(
        sidecar.get("spendAuthority"),
        f"{job_key} {work_kind} spend authority",
    )
    authority_relative = _require_text(
        sidecar_authority.get("authorityFile"),
        f"{job_key} {work_kind} spend authority path",
    )
    authority_path = _safe_existing_file(
        root,
        authority_relative,
        label=f"{job_key} {work_kind} spend authority",
    )
    expected_sidecar_authority = {
        "approvedTotalSpendCapUsd": authority.record[
            "approvedTotalSpendCapUsd"
        ],
        "authorityFile": authority_relative,
        "authorityFileDigest": authority.file_digest,
        "authorityId": authority.identifier,
        "authorityRecordDigest": authority.record_digest,
        "batchPlanDigest": allocation["batchPlanDigest"],
        "batchPolicyDigest": authority.batch_policy_digest,
        "jobKey": allocation["jobKey"],
        "modelsByFamily": dict(authority.record["batchPolicy"]["modelsByFamily"]),
        "runSpendCapUsd": allocation["runSpendCapUsd"],
    }
    if (
        _plain(sidecar_authority) != expected_sidecar_authority
        or sha256_digest(authority_path.read_bytes()) != authority.file_digest
    ):
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{job_key} {work_kind} sidecar names another spend authority"
        )
    catalog = _read_catalog(
        root,
        _require_mapping(
            allocation.get("candidateCatalog"),
            f"{job_key} candidate catalog pin",
        ),
        job_key=job_key,
    )
    plan, _summary = _batch_plan(catalog)
    expected_families = (
        {SCORER_FAMILY}
        if work_kind == "scoring"
        else set(JUDGE_FAMILIES)
    )
    authority_jobs = [
        _require_mapping(row, f"{job_key} authority Batch plan")
        for row in _require_sequence(plan.get("jobs"), "authority Batch plans")
        if _require_mapping(row, f"{job_key} authority Batch plan").get(
            "workKind"
        )
        == work_kind
    ]
    priority_provenance: Mapping[str, Any] | None = None
    ordered_ids: tuple[str, ...] = ()
    if work_kind == "validation":
        planned_jobs, priority_provenance, ordered_ids = (
            _score_prioritized_judging_plan(
                authority,
                allocation,
                catalog,
                root=root,
                job_key=job_key,
            )
        )
        if _plain(sidecar.get("priorityProvenance")) != priority_provenance:
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                f"{job_key} judging priority provenance differs from complete scoring evidence"
            )
        scoring_cost = sum(
            Decimal(str(row["projectedCostUsd"]))
            for row in _require_sequence(plan.get("jobs"), "authority Batch plans")
            if isinstance(row, Mapping) and row.get("workKind") == "scoring"
        )
        judging_cost = sum(
            Decimal(str(row["projectedCostUsd"])) for row in planned_jobs
        )
        if scoring_cost + judging_cost > _money(
            allocation.get("runSpendCapUsd"),
            f"{job_key} run spend cap",
        ):
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                f"{job_key} score-prioritized 25-row plan exceeds its authority"
            )
    else:
        planned_jobs = authority_jobs
        if sidecar.get("priorityProvenance") is not None:
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                f"{job_key} scoring sidecar must not carry judging priority provenance"
            )
    if {str(row.get("family")) for row in planned_jobs} != expected_families:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{job_key} authority has the wrong {work_kind} families"
        )
    expected_initial_plans = {
        (str(row["family"]), str(shard["shardId"])): _require_mapping(
            shard,
            f"{job_key} {row['family']} authority shard",
        )
        for row in planned_jobs
        for shard in _require_sequence(
            row.get("shards"),
            f"{job_key} {row['family']} authority shards",
        )
        if isinstance(shard, Mapping)
    }
    expected_initial_shards = set(expected_initial_plans)
    raw_plans = _require_sequence(
        sidecar.get("plannedShards"),
        f"{job_key} {work_kind} planned shards",
    )
    actual_initial_shards: set[tuple[str, str]] = set()
    observed_plan_keys: set[tuple[str, str]] = set()
    for raw_plan in raw_plans:
        runtime_plan = _require_mapping(
            raw_plan,
            f"{job_key} {work_kind} planned shard",
        )
        family_name = str(runtime_plan.get("family") or "")
        shard_id = str(runtime_plan.get("shardId") or "")
        key = (family_name, shard_id)
        max_group_size = runtime_plan.get("maxRequestGroupSize")
        if (
            key in observed_plan_keys
            or family_name not in expected_families
            or runtime_plan.get("workKind") != work_kind
            or runtime_plan.get("modelId")
            != PRODUCTION_MODELS_BY_FAMILY[family_name]
            or max_group_size not in {REQUEST_GROUP_SIZE, 1}
        ):
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                f"{job_key} {work_kind} runtime plan differs from its authority"
            )
        observed_plan_keys.add(key)
        if max_group_size == REQUEST_GROUP_SIZE:
            expected_plan = expected_initial_plans.get(key)
            if expected_plan is None or any(
                runtime_plan.get(field) != expected_plan.get(field)
                for field in (
                    "candidateCount",
                    "inputFileBytes",
                    "projectedCostUsd",
                    "projectedInputTokens",
                    "projectedOutputTokenAllowance",
                    "providerRequestCount",
                    "shardId",
                )
            ):
                raise VocabularyAtlasV1ProductionSpendAuthorityError(
                    f"{job_key} {work_kind} initial shard cost or coverage differs from its authority"
                )
            actual_initial_shards.add(key)
    if actual_initial_shards != expected_initial_shards:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{job_key} {work_kind} initial 25-row shards differ from its authority"
        )
    if work_kind == "validation":
        for family_name in JUDGE_FAMILIES:
            family_plans = sorted(
                (
                    _require_mapping(raw, f"{job_key} judging planned shard")
                    for raw in raw_plans
                    if isinstance(raw, Mapping)
                    and raw.get("family") == family_name
                    and raw.get("maxRequestGroupSize") == REQUEST_GROUP_SIZE
                ),
                key=lambda row: int(row.get("planOrder") or 0),
            )
            actual_order = tuple(
                str(candidate_id)
                for runtime_plan in family_plans
                for provider_request in _require_sequence(
                    runtime_plan.get("providerRequests"),
                    f"{job_key} {family_name} provider requests",
                )
                for candidate_id in _require_sequence(
                    _require_mapping(
                        provider_request,
                        f"{job_key} {family_name} provider request",
                    ).get("candidateIds"),
                    f"{job_key} {family_name} provider request candidates",
                )
            )
            if actual_order != ordered_ids:
                raise VocabularyAtlasV1ProductionSpendAuthorityError(
                    f"{job_key} {family_name} judging order differs from scorer priority"
                )

    raw_jobs = _require_sequence(
        sidecar.get("jobs"),
        f"{job_key} {work_kind} provider jobs",
    )
    runtime_families: set[str] = set()
    for raw_job in raw_jobs:
        runtime_job = _require_mapping(
            raw_job,
            f"{job_key} {work_kind} provider job",
        )
        family_name = str(runtime_job.get("family") or "")
        if (
            family_name not in expected_families
            or runtime_job.get("workKind") != work_kind
            or runtime_job.get("modelId")
            != PRODUCTION_MODELS_BY_FAMILY[family_name]
        ):
            raise VocabularyAtlasV1ProductionSpendAuthorityError(
                f"{job_key} {work_kind} provider job differs from its model policy"
            )
        runtime_families.add(family_name)
    if runtime_families != expected_families:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            f"{job_key} {work_kind} provider jobs do not cover every approved family"
        )
    return {
        "initialShardCount": len(expected_initial_shards),
        "modelPolicyDigest": authority.batch_policy_digest,
        "providerJobCount": len(raw_jobs),
        "runtimePlanCount": len(raw_plans),
        **(
            {"priorityDigest": priority_provenance["priorityDigest"]}
            if priority_provenance is not None
            else {}
        ),
        "workKind": work_kind,
    }


def read_vocabulary_atlas_v1_production_spend_authority(
    path: Path | str,
    *,
    manifest: VocabularyAtlasV1QualificationJobs,
    repository_root: Path | str,
) -> VocabularyAtlasV1ProductionSpendAuthority:
    """Open canonical authority bytes and reproduce them from current catalogs."""

    root = _resolve_root(repository_root)
    candidate = Path(path)
    lexical = (candidate if candidate.is_absolute() else root / candidate).absolute()
    try:
        relative = lexical.relative_to(root)
        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise VocabularyAtlasV1ProductionSpendAuthorityError(
                    "production spend authority must not traverse a symlink"
                )
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root)
    except FileNotFoundError as error:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "production spend authority does not exist"
        ) from error
    except ValueError as error:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "production spend authority must stay inside the repository"
        ) from error
    if not resolved.is_file():
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "production spend authority must be a regular file"
        )
    payload = resolved.read_bytes()
    record = _decode_canonical_object(payload, "production spend authority")
    authority = VocabularyAtlasV1ProductionSpendAuthority(
        record,
        manifest=manifest,
        repository_root=root,
        file_digest=sha256_digest(payload),
    )
    if resolved.read_bytes() != payload:
        raise VocabularyAtlasV1ProductionSpendAuthorityError(
            "production spend authority changed while opening"
        )
    return authority


__all__ = [
    "FIXED_RUN_SPEND_CAPS_USD",
    "FIXED_TOTAL_SPEND_CAP_USD",
    "JUDGE_FAMILIES",
    "MODEL_RESOLUTION_POLICY",
    "PRODUCTION_MODELS_BY_FAMILY",
    "REQUEST_GROUP_SIZE",
    "SCORER_FAMILY",
    "VOCABULARY_ATLAS_V1_PRODUCTION_SPEND_AUTHORITY_ID_PREFIX",
    "VOCABULARY_ATLAS_V1_PRODUCTION_SPEND_AUTHORITY_TYPE",
    "VOCABULARY_ATLAS_V1_PRODUCTION_SPEND_AUTHORITY_VERSION",
    "VocabularyAtlasV1ProductionSpendAuthority",
    "VocabularyAtlasV1ProductionSpendAuthorityError",
    "read_vocabulary_atlas_v1_production_spend_authority",
    "seal_vocabulary_atlas_v1_production_spend_authority",
    "verify_vocabulary_atlas_v1_production_batch_sidecar",
]
