"""Path-backed machine evidence for shared relation assertions.

The existing crosswalk bundle closes candidates, sealed request/response
artifacts, and machine validations.  This adapter selects either one verified
review or the complete supporting validation set that passed the v2 gate.
Relation assertions pin the resulting proof record and never accept receipt
IRIs alone.

This adapter is intentionally subject-ring specific because CrosswalkBundle v2
only defines SKOS mapping relations.  Other rings can use the same relation
foundation after they supply proof adapters for their own relation semantics.

Signed proof is intentionally absent.  A future signed adapter must verify an
independently pinned authority policy before it may emit a signed proof kind.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

from typing_extensions import Self

from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes, sha256_digest
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.semantic_foundation import (
    MACHINE_EVIDENCE_PROOF_VERSION,
    SUBJECT_BROAD_MATCH,
    SUBJECT_CLOSE_MATCH,
    SUBJECT_EXACT_MATCH,
    SUBJECT_NARROW_MATCH,
    SUBJECT_RELATED_MATCH,
    EvidenceAssertion,
    validate_machine_evidence_proof_pin,
)

from .model import CrosswalkBundle, VocabularyAtlasError
from .relation_proof import register_trusted_relation_machine_proof_adapter

CROSSWALK_MACHINE_PROOF_VERSION = MACHINE_EVIDENCE_PROOF_VERSION
CROSSWALK_MACHINE_PROOF_ADAPTER = "https://refspec.org/adapters/crosswalk-machine-proof/v1"
CROSSWALK_V2_QUALIFICATION_POLICY = (
    "https://refspec.org/policies/two-independent-machines-relation-agreement-v2"
)

MachineProofKind = Literal[
    "crosswalkV2IndependentValidations",
    "crosswalkV2SingleMachineReview",
]
MachineEvidenceClass = Literal["machineQualified", "machineReviewed"]

_VERDICT_RELATIONS = {
    "same": SUBJECT_EXACT_MATCH,
    "near_same": SUBJECT_CLOSE_MATCH,
    "target_is_broader": SUBJECT_BROAD_MATCH,
    "target_is_narrower": SUBJECT_NARROW_MATCH,
    "related": SUBJECT_RELATED_MATCH,
}
_CONTROL_GENERATION_CLASSES = frozenset({"siblingDistractor", "randomNegativeControl"})


class CrosswalkMachineProofError(ValueError):
    """A selected machine proof is absent, stale, or not closed."""


@lru_cache(maxsize=16)
def _open_verified_crosswalk_bundle(
    path: str,
    file_digest: str,
    bundle_digest: str,
) -> CrosswalkBundle:
    """Reuse one immutable, already-closed bundle within this process."""

    return CrosswalkBundle.open(
        Path(path),
        expected_file_digest=file_digest,
        expected_bundle_digest=bundle_digest,
    )


@lru_cache(maxsize=16)
def _verify_provider_batch_run(path: str, file_digest: str) -> None:
    """Recompute one immutable run's provider evidence once per process."""

    run_path = Path(path)
    payload = run_path.read_bytes()
    if sha256_digest(payload) != file_digest:
        raise CrosswalkMachineProofError("qualification run changed before provider evidence verification")
    try:
        record = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CrosswalkMachineProofError("qualification run is not UTF-8 JSON") from error
    if not isinstance(record, Mapping):
        raise CrosswalkMachineProofError("qualification run is not an object")
    from .qualification_batch import BatchError, verify_run_provider_batch_evidence

    try:
        verify_run_provider_batch_evidence(run_path, record)
    except BatchError as error:
        raise CrosswalkMachineProofError(str(error)) from error


def machine_evidence_class_for_proof_kind(value: object) -> MachineEvidenceClass:
    """Derive the evidence class from one verified Crosswalk v2 proof kind."""

    if value == "crosswalkV2IndependentValidations":
        return "machineQualified"
    if value == "crosswalkV2SingleMachineReview":
        return "machineReviewed"
    raise CrosswalkMachineProofError("crosswalk machine proof kind is unsupported")


def _require_iri(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CrosswalkMachineProofError(f"{label} must be non-empty trimmed text")
    issue = absolute_uri_issue(value)
    if issue == "missing-scheme":
        raise CrosswalkMachineProofError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise CrosswalkMachineProofError(f"{label} must not contain credentials")
    return value


def _require_digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise CrosswalkMachineProofError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _record_by_id(rows: object, identifier: str, label: str) -> Mapping[str, Any]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise CrosswalkMachineProofError(f"crosswalk {label} must be an array")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("id") == identifier]
    if len(matches) != 1:
        raise CrosswalkMachineProofError(f"crosswalk must contain the selected {label} exactly once")
    return matches[0]


def _candidate_generation_metadata(
    bundle_record: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    """Resolve generator class and policy from the candidate's sealed evidence."""

    artifacts = bundle_record.get("artifacts")
    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
        raise CrosswalkMachineProofError("crosswalk artifacts must be an array")
    by_id = {
        str(row["id"]): row
        for row in artifacts
        if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }
    evidence = candidate.get("evidence")
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        raise CrosswalkMachineProofError("crosswalk candidate evidence must be an array")
    metadata: list[tuple[str, str | None]] = []
    for reference in evidence:
        if not isinstance(reference, Mapping):
            raise CrosswalkMachineProofError("crosswalk candidate evidence reference is invalid")
        artifact = by_id.get(str(reference.get("id")))
        if artifact is None or artifact.get("canonicalPayloadDigest") != reference.get("digest"):
            raise CrosswalkMachineProofError("crosswalk candidate evidence does not resolve exactly")
        if artifact.get("role") != "evidence":
            continue
        content = artifact.get("content")
        if not isinstance(content, Mapping) or "generationClass" not in content:
            continue
        generation_class = content.get("generationClass")
        generation_policy = content.get("generationPolicy")
        if not isinstance(generation_class, str) or not generation_class:
            raise CrosswalkMachineProofError("crosswalk candidate generation class is invalid")
        if generation_policy is not None and not isinstance(generation_policy, str):
            raise CrosswalkMachineProofError("crosswalk candidate generation policy is invalid")
        metadata.append((generation_class, generation_policy))
    if len(set(metadata)) > 1:
        raise CrosswalkMachineProofError("crosswalk candidate evidence disagrees about generation metadata")
    return metadata[0] if metadata else (None, None)


@dataclass(frozen=True, slots=True)
class CrosswalkMachineProofFacts:
    """Facts reproduced from one exact crosswalk bundle."""

    proof_kind: MachineProofKind
    crosswalk_bundle_id: str
    crosswalk_bundle_digest: str
    crosswalk_file_digest: str
    candidate_id: str
    candidate_digest: str
    validation_ids: tuple[str, ...]
    validation_digests: tuple[str, ...]
    sealed_input_digest: str
    request_id: str
    request_digest: str
    source_concept: str
    target_concept: str
    source_release: str
    target_release: str
    relation: str
    generation_class: str | None
    generation_policy: str | None
    qualification_run: Mapping[str, Any] | None

    def _basis(self) -> dict[str, Any]:
        proof_details: dict[str, Any] = {
            "adapter": "RefSpecCrosswalkV2",
            "sealedQuestion": {
                "inputDigest": self.sealed_input_digest,
                "request": {"id": self.request_id, "contentDigest": self.request_digest},
            },
        }
        if self.generation_class is not None or self.generation_policy is not None:
            proof_details["candidateGeneration"] = {
                "class": self.generation_class,
                "policy": self.generation_policy,
            }
        if self.qualification_run is not None:
            proof_details["qualificationRun"] = dict(self.qualification_run)
        result = {
            "type": "MachineEvidenceProof",
            "schemaVersion": CROSSWALK_MACHINE_PROOF_VERSION,
            "proofAdapter": CROSSWALK_MACHINE_PROOF_ADAPTER,
            "semanticRing": "subject",
            "evidenceClass": machine_evidence_class_for_proof_kind(self.proof_kind),
            "proofKind": self.proof_kind,
            "proofSource": {
                "type": "CrosswalkBundle",
                "id": self.crosswalk_bundle_id,
                "contentDigest": self.crosswalk_bundle_digest,
                "fileDigest": self.crosswalk_file_digest,
            },
            "candidate": {"id": self.candidate_id, "contentDigest": self.candidate_digest},
            "validations": [
                {"id": identifier, "contentDigest": digest}
                for identifier, digest in zip(self.validation_ids, self.validation_digests, strict=True)
            ],
            "proofDetails": proof_details,
            "sourceConcept": self.source_concept,
            "targetConcept": self.target_concept,
            "sourceRelease": self.source_release,
            "targetRelease": self.target_release,
            "relation": self.relation,
        }
        if self.proof_kind == "crosswalkV2IndependentValidations":
            result["qualificationPolicy"] = CROSSWALK_V2_QUALIFICATION_POLICY
        return result

    @property
    def content_digest(self) -> str:
        return sha256_digest(canonical_json_bytes(self._basis()))

    @property
    def identifier(self) -> str:
        return "urn:ref:machine-evidence-proof:subject:" + self.content_digest.removeprefix("sha256:")

    def as_record(self) -> dict[str, Any]:
        return validate_machine_evidence_proof_pin(
            {**self._basis(), "id": self.identifier, "contentDigest": self.content_digest},
            semantic_ring="subject",
        )


@register_trusted_relation_machine_proof_adapter(CROSSWALK_MACHINE_PROOF_ADAPTER)
@dataclass(frozen=True, slots=True)
class PinnedCrosswalkMachineProof:
    """One proof selection that is reproduced from exact path-backed bytes."""

    path: Path
    file_digest: str
    bundle_digest: str
    proof_kind: MachineProofKind
    candidate_id: str
    validation_ids: tuple[str, ...]
    qualification_run_path: Path | None = None
    qualification_run_file_digest: str | None = None
    qualification_run_content_digest: str | None = None

    def __post_init__(self) -> None:
        machine_evidence_class_for_proof_kind(self.proof_kind)
        object.__setattr__(self, "file_digest", _require_digest(self.file_digest, "crosswalk file digest"))
        object.__setattr__(self, "bundle_digest", _require_digest(self.bundle_digest, "crosswalk bundle digest"))
        object.__setattr__(self, "candidate_id", _require_iri(self.candidate_id, "crosswalk candidate id"))
        validations = tuple(sorted(_require_iri(value, "crosswalk validation id") for value in self.validation_ids))
        if len(validations) != len(set(validations)):
            raise CrosswalkMachineProofError("crosswalk validation ids must be unique")
        if self.proof_kind == "crosswalkV2IndependentValidations" and len(validations) < 2:
            raise CrosswalkMachineProofError(
                "crosswalkV2IndependentValidations requires at least two selected validations"
            )
        if self.proof_kind == "crosswalkV2SingleMachineReview" and len(validations) != 1:
            raise CrosswalkMachineProofError(
                "crosswalkV2SingleMachineReview requires exactly one selected validation"
            )
        object.__setattr__(self, "validation_ids", validations)
        candidate = Path(self.path)
        if candidate.is_symlink():
            raise CrosswalkMachineProofError("crosswalk proof path must not be a symlink")
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            raise CrosswalkMachineProofError("crosswalk proof path does not exist") from error
        if not resolved.is_file():
            raise CrosswalkMachineProofError("crosswalk proof path must be a regular file")
        object.__setattr__(self, "path", resolved)
        run_values = (
            self.qualification_run_path,
            self.qualification_run_file_digest,
            self.qualification_run_content_digest,
        )
        if any(value is not None for value in run_values) and not all(value is not None for value in run_values):
            raise CrosswalkMachineProofError("qualification run path and both digests must be supplied together")
        if self.qualification_run_path is not None:
            run_path = Path(self.qualification_run_path)
            if run_path.is_symlink():
                raise CrosswalkMachineProofError("qualification run receipt path must not be a symlink")
            try:
                resolved_run = run_path.resolve(strict=True)
            except FileNotFoundError as error:
                raise CrosswalkMachineProofError("qualification run receipt path does not exist") from error
            if not resolved_run.is_file():
                raise CrosswalkMachineProofError("qualification run receipt path must be a regular file")
            object.__setattr__(self, "qualification_run_path", resolved_run)
            object.__setattr__(
                self,
                "qualification_run_file_digest",
                _require_digest(self.qualification_run_file_digest, "qualification run file digest"),
            )
            object.__setattr__(
                self,
                "qualification_run_content_digest",
                _require_digest(self.qualification_run_content_digest, "qualification run content digest"),
            )

    @classmethod
    def qualified(
        cls,
        path: Path | str,
        *,
        expected_file_digest: str,
        expected_bundle_digest: str,
        candidate_id: str,
        qualification_run_path: Path | str | None = None,
        expected_qualification_run_file_digest: str | None = None,
        expected_qualification_run_content_digest: str | None = None,
    ) -> Self:
        """Select the complete support set that qualified one v2 candidate."""

        selected_candidate = _require_iri(candidate_id, "crosswalk candidate id")
        bundle = cls._open_bundle(path, expected_file_digest, expected_bundle_digest)
        qualified = bundle.qualified().get(selected_candidate)
        if qualified is None:
            raise CrosswalkMachineProofError("crosswalk candidate did not pass independent qualification")
        selected = cls(
            path=Path(path),
            file_digest=expected_file_digest,
            bundle_digest=expected_bundle_digest,
            proof_kind="crosswalkV2IndependentValidations",
            candidate_id=selected_candidate,
            validation_ids=tuple(str(row["id"]) for row in qualified),
            qualification_run_path=None if qualification_run_path is None else Path(qualification_run_path),
            qualification_run_file_digest=expected_qualification_run_file_digest,
            qualification_run_content_digest=expected_qualification_run_content_digest,
        )
        selected.verified_facts()
        return selected

    @classmethod
    def reviewed(
        cls,
        path: Path | str,
        *,
        expected_file_digest: str,
        expected_bundle_digest: str,
        candidate_id: str,
        validation_id: str,
    ) -> Self:
        """Select one deterministic supporting v2 review for operator adoption."""

        selected = cls(
            path=Path(path),
            file_digest=expected_file_digest,
            bundle_digest=expected_bundle_digest,
            proof_kind="crosswalkV2SingleMachineReview",
            candidate_id=candidate_id,
            validation_ids=(validation_id,),
        )
        selected.verified_facts()
        return selected

    @staticmethod
    def _open_bundle(path: Path | str, file_digest: str, bundle_digest: str) -> CrosswalkBundle:
        expected_file_digest = _require_digest(file_digest, "crosswalk file digest")
        expected_bundle_digest = _require_digest(bundle_digest, "crosswalk bundle digest")
        candidate = Path(path)
        if candidate.is_symlink():
            raise CrosswalkMachineProofError("crosswalk proof path must not be a symlink")
        try:
            resolved = candidate.resolve(strict=True)
            if not resolved.is_file():
                raise CrosswalkMachineProofError(
                    "crosswalk proof path must be a regular file"
                )
            if sha256_digest(resolved.read_bytes()) != expected_file_digest:
                raise CrosswalkMachineProofError("crosswalk file digest differs")
            bundle = _open_verified_crosswalk_bundle(
                str(resolved),
                expected_file_digest,
                expected_bundle_digest,
            )
            if sha256_digest(resolved.read_bytes()) != expected_file_digest:
                raise CrosswalkMachineProofError(
                    "crosswalk proof changed while opening"
                )
            return bundle
        except FileNotFoundError as error:
            raise CrosswalkMachineProofError(
                "crosswalk proof path does not exist"
            ) from error
        except VocabularyAtlasError as error:
            raise CrosswalkMachineProofError(str(error)) from error

    def _qualification_run_facts(
        self,
        *,
        candidate_id: str,
        generation_class: str | None,
        generation_policy: str | None,
        relation: str,
    ) -> Mapping[str, Any] | None:
        if self.qualification_run_path is None:
            if generation_class is not None and self.proof_kind == "crosswalkV2IndependentValidations":
                raise CrosswalkMachineProofError(
                    "generated crosswalk qualification requires its canonical run receipt"
                )
            return None
        payload = self.qualification_run_path.read_bytes()
        if sha256_digest(payload) != self.qualification_run_file_digest:
            raise CrosswalkMachineProofError("qualification run receipt file digest differs")
        try:
            record = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CrosswalkMachineProofError("qualification run receipt is not UTF-8 JSON") from error
        if not isinstance(record, Mapping) or canonical_json_bytes(record) != payload:
            raise CrosswalkMachineProofError("qualification run receipt bytes are not canonical")
        from .qualification import (  # local import avoids package-initialization cycles
            PRODUCTION_COVERAGE_MODE,
            VALIDATOR_FAMILIES,
            endpoint_host,
            score_reading_from_receipt,
            validate_qualification_run_receipt,
        )

        try:
            run = validate_qualification_run_receipt(record)
        except VocabularyAtlasError as error:
            raise CrosswalkMachineProofError(str(error)) from error
        if run.get("contentDigest") != self.qualification_run_content_digest:
            raise CrosswalkMachineProofError("qualification run content digest differs")
        provider_batch_evidence = run.get("providerBatchEvidence")
        if provider_batch_evidence is not None:
            _verify_provider_batch_run(
                str(self.qualification_run_path),
                str(self.qualification_run_file_digest),
            )
        source = run.get("bundle")
        if (
            not isinstance(source, Mapping)
            or source.get("id") != self._open_bundle(self.path, self.file_digest, self.bundle_digest).identifier
            or source.get("fileDigest") != self.file_digest
            or source.get("bundleDigest") != self.bundle_digest
        ):
            raise CrosswalkMachineProofError("qualification run pins another CrosswalkBundle")
        candidates = run.get("candidateAccounting")
        if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
            raise CrosswalkMachineProofError("qualification run has no candidate accounting")
        matches = [row for row in candidates if isinstance(row, Mapping) and row.get("candidateId") == candidate_id]
        if len(matches) != 1:
            raise CrosswalkMachineProofError("qualification run must account for the proof candidate exactly once")
        row = matches[0]
        if row.get("control") is not False or row.get("disposition") != "admitted" or row.get("relation") != relation:
            raise CrosswalkMachineProofError("qualification run did not admit this non-control relation")
        if row.get("generationClass") != generation_class:
            raise CrosswalkMachineProofError("qualification run generation class differs from candidate evidence")
        if run.get("candidateGenerationPolicy") != generation_policy:
            raise CrosswalkMachineProofError("qualification run generation policy differs from candidate evidence")
        scorer_receipts = row.get("scorerReceipts")
        if not isinstance(scorer_receipts, Sequence) or isinstance(scorer_receipts, (str, bytes)):
            raise CrosswalkMachineProofError("qualification run has no scorer lineage")
        if run.get("coverageMode") == PRODUCTION_COVERAGE_MODE and (
            run.get("productionReady") is not True or row.get("scored") is not True or not scorer_receipts
        ):
            raise CrosswalkMachineProofError("production proof lacks complete scorer and judge lineage")
        scoring = run.get("scoring")
        scoring_log = scoring.get("receiptLog") if isinstance(scoring, Mapping) else None
        if scorer_receipts:
            if not isinstance(scoring_log, Mapping):
                raise CrosswalkMachineProofError("qualification run has no scorer receipt-log pin")
            name = scoring_log.get("file")
            if not isinstance(name, str) or Path(name).name != name:
                raise CrosswalkMachineProofError("qualification run scorer receipt path is unsafe")
            scoring_path = self.qualification_run_path.parent / name
            if scoring_path.is_symlink() or not scoring_path.is_file():
                raise CrosswalkMachineProofError("qualification run scorer receipt log is missing or unsafe")
            scoring_bytes = scoring_path.read_bytes()
            if sha256_digest(scoring_bytes) != scoring_log.get("fileDigest"):
                raise CrosswalkMachineProofError("qualification run scorer receipt log differs from its pin")
            actual: dict[tuple[str, str], tuple[Mapping[str, Any], str]] = {}
            for line in scoring_bytes.decode("utf-8").splitlines():
                if not line.strip():
                    continue
                scorer = json.loads(line)
                if not isinstance(scorer, Mapping) or canonical_json_bytes(scorer) != (line + "\n").encode("utf-8"):
                    raise CrosswalkMachineProofError("scorer receipt row is not canonical JSON")
                key = (str(scorer.get("candidate_id")), str(scorer.get("family")))
                if key in actual:
                    raise CrosswalkMachineProofError("scorer receipt log repeats a candidate/family")
                actual[key] = (scorer, sha256_digest((line + "\n").encode("utf-8")))
            for pin in scorer_receipts:
                if not isinstance(pin, Mapping):
                    raise CrosswalkMachineProofError("qualification run scorer receipt pin is invalid")
                family_name = str(pin.get("family"))
                value = actual.get((candidate_id, family_name))
                if value is None or value[1] != pin.get("receiptDigest"):
                    raise CrosswalkMachineProofError("qualification run scorer receipt does not resolve exactly")
                scorer, _receipt_digest = value
                family = VALIDATOR_FAMILIES.get(family_name)
                if family is None:
                    raise CrosswalkMachineProofError("qualification run scorer family is unsupported")
                try:
                    reading = score_reading_from_receipt(scorer, family, str(scorer.get("model_id")))
                except VocabularyAtlasError as error:
                    raise CrosswalkMachineProofError(str(error)) from error
                deterministic = bool(reading is not None and reading.deterministic_checks_passed)
                if (
                    pin.get("outcome") != scorer.get("outcome")
                    or pin.get("modelId") != scorer.get("model_id")
                    or pin.get("endpoint") != endpoint_host(str(scorer.get("request_url") or ""))
                    or pin.get("requestSha256") != scorer.get("request_sha256")
                    or pin.get("responseSha256") != scorer.get("response_sha256")
                    or pin.get("deterministicChecksPassed") is not deterministic
                ):
                    raise CrosswalkMachineProofError("qualification run scorer lineage differs from its receipt")
        return {
            "id": run["id"],
            "contentDigest": run["contentDigest"],
            "fileDigest": self.qualification_run_file_digest,
            "protocol": run["protocol"],
            "scoringProtocol": cast(Mapping[str, Any], run["scoring"])["protocol"],
            "candidateGenerationPolicy": generation_policy,
            "candidateDisposition": row["disposition"],
            "scorerReceipts": list(scorer_receipts),
        }

    def verified_facts(self) -> CrosswalkMachineProofFacts:
        """Reopen the bytes and reproduce the same candidate, receipts, and relation."""

        bundle = self._open_bundle(self.path, self.file_digest, self.bundle_digest)
        record = bundle.to_dict()
        if record.get("schemaVersion") != "2.0":
            raise CrosswalkMachineProofError("shared machine proof requires a relation-adjudicating v2 bundle")
        candidate = _record_by_id(record.get("mappingCandidates"), self.candidate_id, "candidate")
        generation_class, _generation_policy = _candidate_generation_metadata(record, candidate)
        if generation_class in _CONTROL_GENERATION_CLASSES:
            raise CrosswalkMachineProofError(
                f"control-arm candidate {generation_class!r} remains qualification evidence and cannot become a mapping proof"
            )
        validations = tuple(
            _record_by_id(record.get("machineValidations"), identifier, "validation")
            for identifier in self.validation_ids
        )
        if self.proof_kind == "crosswalkV2IndependentValidations":
            qualified = bundle.qualified().get(self.candidate_id)
            if qualified is None or tuple(sorted(str(row["id"]) for row in qualified)) != self.validation_ids:
                raise CrosswalkMachineProofError(
                    "selected validations are not the candidate's complete qualifying support set"
                )
            relation = bundle.adjudicated_relations().get(self.candidate_id)
            if relation is None:
                raise CrosswalkMachineProofError("qualified crosswalk proof has no emitted relation")
        else:
            validation = validations[0]
            candidate_reference = validation.get("candidate")
            if (
                not isinstance(candidate_reference, Mapping)
                or candidate_reference.get("id") != self.candidate_id
                or candidate_reference.get("digest") != candidate.get("canonicalPayloadDigest")
                or validation.get("outcome") != "supports"
                or validation.get("deterministicChecksPassed") is not True
            ):
                raise CrosswalkMachineProofError("selected validation is not a deterministic supporting review")
            verdict = validation.get("verdictRelation")
            relation = _VERDICT_RELATIONS.get(verdict)
            if relation is None:
                raise CrosswalkMachineProofError("selected validation has no supported relation verdict")
        question_keys: set[tuple[str, str, str]] = set()
        for validation in validations:
            request = validation.get("requestArtifact")
            if not isinstance(request, Mapping):
                raise CrosswalkMachineProofError("selected validation has no sealed request")
            question_keys.add(
                (
                    _require_digest(validation.get("sealedInputDigest"), "crosswalk sealed input digest"),
                    _require_iri(request.get("id"), "crosswalk request id"),
                    _require_digest(request.get("digest"), "crosswalk request digest"),
                )
            )
        if len(question_keys) != 1:
            raise CrosswalkMachineProofError("selected validations do not answer one sealed question")
        sealed_input_digest, request_id, request_digest = question_keys.pop()
        qualification_run = self._qualification_run_facts(
            candidate_id=self.candidate_id,
            generation_class=generation_class,
            generation_policy=_generation_policy,
            relation=relation,
        )
        facts = CrosswalkMachineProofFacts(
            proof_kind=self.proof_kind,
            crosswalk_bundle_id=_require_iri(bundle.identifier, "crosswalk bundle id"),
            crosswalk_bundle_digest=_require_digest(bundle.digest, "crosswalk bundle digest"),
            crosswalk_file_digest=self.file_digest,
            candidate_id=self.candidate_id,
            candidate_digest=_require_digest(candidate.get("canonicalPayloadDigest"), "crosswalk candidate digest"),
            validation_ids=self.validation_ids,
            validation_digests=tuple(
                _require_digest(row.get("canonicalPayloadDigest"), "crosswalk validation digest") for row in validations
            ),
            sealed_input_digest=sealed_input_digest,
            request_id=request_id,
            request_digest=request_digest,
            source_concept=_require_iri(candidate.get("sourceMember"), "crosswalk source member"),
            target_concept=_require_iri(candidate.get("targetMember"), "crosswalk target member"),
            source_release=_require_iri(candidate.get("sourceRelease"), "crosswalk source release"),
            target_release=_require_iri(candidate.get("targetRelease"), "crosswalk target release"),
            relation=_require_iri(relation, "crosswalk adjudicated relation"),
            generation_class=generation_class,
            generation_policy=_generation_policy,
            qualification_run=qualification_run,
        )
        if sha256_digest(self.path.read_bytes()) != self.file_digest:
            raise CrosswalkMachineProofError("crosswalk proof changed while verifying")
        if self.qualification_run_path is not None and sha256_digest(
            self.qualification_run_path.read_bytes()
        ) != self.qualification_run_file_digest:
            raise CrosswalkMachineProofError("qualification run receipt changed while verifying")
        return facts

    @property
    def identifier(self) -> str:
        return self.verified_facts().identifier

    def pin(self) -> dict[str, Any]:
        return self.verified_facts().as_record()


def build_machine_evidence_from_crosswalk_proof(
    proof: PinnedCrosswalkMachineProof,
    *,
    asserted_by: str,
    asserted_at: str,
    evidence: Sequence[str] = (),
) -> EvidenceAssertion:
    """Build an evidence assertion whose complete machine scope is reproduced."""

    if not isinstance(proof, PinnedCrosswalkMachineProof):
        raise CrosswalkMachineProofError("machine evidence requires a pinned crosswalk proof")
    facts = proof.verified_facts()
    supporting = tuple(sorted({facts.identifier, *evidence}))
    common: dict[str, Any] = {
        "semantic_ring": "subject",
        "basis": "statisticalInference",
        "asserted_by": asserted_by,
        "asserted_at": asserted_at,
        "evidence": supporting,
        "candidate": facts.candidate_id,
        "machine_proof": facts.identifier,
        "source_concept": facts.source_concept,
        "target_concept": facts.target_concept,
        "source_release": facts.source_release,
        "target_release": facts.target_release,
        "relation": facts.relation,
        "validation_receipts": facts.validation_ids,
    }
    return EvidenceAssertion(
        evidence_class=machine_evidence_class_for_proof_kind(facts.proof_kind),
        **common,
    )


__all__ = [
    "CROSSWALK_MACHINE_PROOF_VERSION",
    "CROSSWALK_V2_QUALIFICATION_POLICY",
    "CrosswalkMachineProofError",
    "CrosswalkMachineProofFacts",
    "MachineEvidenceClass",
    "PinnedCrosswalkMachineProof",
    "build_machine_evidence_from_crosswalk_proof",
    "machine_evidence_class_for_proof_kind",
]
