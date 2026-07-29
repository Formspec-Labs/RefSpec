"""Deterministic development artifacts for the 1995 Federal Register thesaurus.

This module is deliberately bounded.  It turns the lossless source-adapter
result into:

* one Rulespec JSON-LD concept scheme, concept graph, exact complete-membership
  release, and source-distribution artifact;
* normalized label and resolved relation rows;
* one ``IndexedVocabularyExpression`` for every member-bound preferred label,
  alternate label, scope note, and typed category notation; and
* a feature coverage report whose source defects are explicit parsing
  exclusions under a no-invented-identity policy.

The bundle is always ``developmentOnly`` and never production eligible.  It
references the native source by URL and digest and never writes the source
bytes into the output directory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from refspec import binding
from refspec.registry.federal_register_thesaurus import (
    ASSOCIATIVE_PREDICATE_IRI,
    BROADER_PREDICATE_IRI,
    FEDERAL_REGISTER_THESAURUS_1995_URL,
    SCOPE_NOTE_PROPERTY_IRI,
    FederalRegisterThesaurus,
    SourceLocator,
    parse_federal_register_thesaurus,
)
from refspec.release_graph import (
    GRAPH_DIGEST_ALGORITHM,
    RulespecValidatorPin,
    defined_rulespec_identifiers,
    issue_release_graph_validation_receipt,
    load_pinned_rulespec_validator,
    referenced_rulespec_identifiers,
    rulespec_dependency_bytes,
    rulespec_graph_digest,
)
from refspec.storage import canonical_json
from refspec.vocabulary import (
    CONCEPT_EVENT_PARTICIPANT_COLUMNS,
    CONCEPT_LABEL_COLUMNS,
    CONCEPT_RELATION_COLUMNS,
    CoverageException,
    EnrichmentProfile,
    ImportFeatureCoverage,
    IndexedVocabularyExpression,
    OutputProfile,
    RegistryDeploymentDecision,
    RegistryImportCoverageReport,
    canonical_text_digest,
    indexed_expression_id,
    normalize_unicode_text,
    seal_payload,
)

PARSER_VERSION = "federal-register-thesaurus-1995-lossless-v1"
SLICE_VERSION = "federal-register-thesaurus-1995-vertical-slice-v1"
HISTORICAL_SOURCE_SHA256 = "sha256:d5e013336d4179790e8d6574d4dc9d8cfcb10ce76af202ff4db068617eb8fd30"

GRAPH_IRI = "urn:ref:fr-thesaurus-1995:rulespec-graph:v1"
SCHEME_IRI = "urn:ref:fr-thesaurus-1995:scheme"
REGISTRY_IRI = "urn:ref:external-registry:nara-federal-register-thesaurus"
IMPORT_SCOPE_IRI = "urn:ref:fr-thesaurus-1995:import-scope:lossless-development-v1"
RELEASE_IRI = "urn:ref:fr-thesaurus-1995:release:1995-11-16-preview"
RELEASE_VERSION = "1995-11-16-content-derived-preview"
DISTRIBUTION_IRI = "urn:ref:fr-thesaurus-1995:distribution:native-text"
IMPORT_SNAPSHOT_IRI = "urn:ref:fr-thesaurus-1995:import-snapshot:lossless-v1"
EXPRESSION_CORPUS_IRI = "urn:ref:fr-thesaurus-1995:expression-corpus:v1"
ACTIVITY_IRI = "urn:ref:fr-thesaurus-1995:activity:vertical-slice-v1"
ACQUISITION_ACTIVITY_IRI = "urn:ref:fr-thesaurus-1995:activity:verify-local-source:v1"
RECEIPT_IRI = "urn:ref:fr-thesaurus-1995:receipt:vertical-slice-v1"
CAPTURE_IRI = "urn:ref:fr-thesaurus-1995:capture:pinned-source"
RIGHTS_ASSESSMENT_IRI = "urn:ref:fr-thesaurus-1995:rights-assessment:v1"
PUBLICATION_IRI = "urn:ref:fr-thesaurus-1995:publication:development-v1"
CONFORMANCE_RESULT_IRI = "urn:ref:fr-thesaurus-1995:rulespec-validation-result:v1"
DEVELOPMENT_ENVIRONMENT_IRI = "urn:ref:environment:spicy-regs-experimental-playground"
SELECTION_ASSERTION_IRI = "urn:ref:fr-thesaurus-1995:assertion:local-candidate-use:v1"
SELECTION_ATTESTATION_IRI = "urn:ref:fr-thesaurus-1995:attestation:local-candidate-use:v1"
SELECTION_EVIDENCE_IRI = "urn:ref:fr-thesaurus-1995:evidence:local-candidate-use:v1"
SELECTION_ADOPTION_IRI = "urn:ref:fr-thesaurus-1995:local-adoption:local-candidate-use:v1"
SELECTED_DEPLOYMENT_IRI = "urn:ref:fr-thesaurus-1995:registry-deployment:development-selected:v1"
ROLLBACK_DEPLOYMENT_IRI = "urn:ref:fr-thesaurus-1995:registry-deployment:development-rollback:v1"
ROLLBACK_RECEIPT_IRI = "urn:ref:fr-thesaurus-1995:receipt:development-rollback:v1"
ROLLBACK_VALIDATION_RECEIPT_IRI = (
    "urn:ref:fr-thesaurus-1995:release-graph-validation-receipt:rollback:v1"
)
ROLLBACK_FINAL_STATE_IRI = (
    "urn:ref:fr-thesaurus-1995:selection-state:development-empty"
)
REGISTRY_SELECTION_REDUCER_VERSION = "refspec-registry-selection-reducer-v1"
ENRICHMENT_PROFILE_IRI = "urn:ref:enrichment-profile:core:v1"
OUTPUT_PROFILE_IRI = "urn:ref:output-profile:fr-thesaurus-development:v1"
IMPORT_PROFILE_IRI = "urn:ref:import-profile:fr-thesaurus-1995:v1"
NORMALIZATION_POLICY_IRI = "urn:ref:normalization:unicode-nfkc-casefold-whitespace:v1"
EXCLUSION_POLICY_IRI = "urn:ref:policy:no-invented-source-identity:v1"

GENERAL_SUBJECT_FACET_IRI = "urn:ref:facet:general-subject"
CONCEPT_SCOPE_IRI = "urn:ref:scope:general-subject"
ACCESS_SCOPE_IRI = "urn:ref:access-scope:local-development-only"
RETENTION_POLICY_IRI = "urn:ref:retention-policy:content-addressed-local-source:v1"
SOURCE_ISSUED_AT = "1995-11-16T00:00:00Z"
OFR_AUTHORSHIP_EVIDENCE_IRI = "https://www.govinfo.gov/content/pkg/FR-1977-03-07/pdf/FR-1977-03-07.pdf"
OFR_CURRENT_USE_EVIDENCE_IRI = "https://www.archives.gov/federal-register/cfr/thesaurus.html"
US_GOVERNMENT_WORKS_LAW_IRI = (
    "https://uscode.house.gov/view.xhtml?edition=2023&num=0&req=granuleid%3AUSC-2023-title17-section105"
)
OFR_AUTHORSHIP_ARTIFACT_IRI = "urn:ref:fr-thesaurus-1995:rights-artifact:ofr-1977-notice"
OFR_AUTHORSHIP_FRAGMENT_IRI = "urn:ref:fr-thesaurus-1995:rights-fragment:ofr-authorship"
OFR_CURRENT_USE_ARTIFACT_IRI = "urn:ref:fr-thesaurus-1995:rights-artifact:nara-current-use"
OFR_CURRENT_USE_FRAGMENT_IRI = "urn:ref:fr-thesaurus-1995:rights-fragment:nara-current-use"
US_GOVERNMENT_WORKS_LAW_ARTIFACT_IRI = "urn:ref:fr-thesaurus-1995:rights-artifact:17-usc-105"
US_GOVERNMENT_WORKS_LAW_FRAGMENT_IRI = "urn:ref:fr-thesaurus-1995:rights-fragment:17-usc-105"

PREFERRED_LABEL_PROPERTY_IRI = "http://www.w3.org/2004/02/skos/core#prefLabel"
ALTERNATE_LABEL_PROPERTY_IRI = "http://www.w3.org/2004/02/skos/core#altLabel"
NOTATION_PROPERTY_IRI = "http://www.w3.org/2004/02/skos/core#notation"

_CONCEPT_ID = re.compile(r"^frt95-concept-(\d{4,})$")
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")

_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_DCTERMS_IS_VERSION_OF = "http://purl.org/dc/terms/isVersionOf"
_DCTERMS_TYPE = "http://purl.org/dc/terms/type"
_DCTERMS_FORMAT = "http://purl.org/dc/terms/format"
_DCAT_VERSION = "http://www.w3.org/ns/dcat#version"
_DCAT_DISTRIBUTION = "http://www.w3.org/ns/dcat#distribution"
ASSIGNMENT_PRIMARY_IRI = "https://rulespec.org/ns/v1#assignmentPrimary"

_FEATURE_ORDER = (
    "labels",
    "languages",
    "notation",
    "notes",
    "hierarchy",
    "associativeRelations",
    "mappings",
    "status",
    "replacements",
    "identifiers",
    "membership",
)


class VerticalSliceError(ValueError):
    """The parsed source cannot produce the bounded development artifacts."""


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _digest_json(value: object) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _canonical_json_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8") + b"\n"


def _canonical_jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        return b""
    return b"".join(_canonical_json_bytes(row) for row in rows)


def _locator_payload(locator: SourceLocator) -> dict[str, int]:
    return {
        "startLine": locator.start_line,
        "endLine": locator.end_line,
        "sourceOrdinal": locator.ordinal,
    }


def _source_path(
    *,
    locator: SourceLocator,
    property_iri: str,
    source_record_id: str,
    source_entry_id: str | None = None,
) -> str:
    result = (
        "thesaurus-alpha.txt"
        f"#line={locator.start_line}"
        f";endLine={locator.end_line}"
        f";ordinal={locator.ordinal}"
        f";record={source_record_id}"
    )
    if source_entry_id is not None:
        result += f";entry={source_entry_id}"
    return result + f";property={property_iri}"


def _concept_iri(source_concept_id: str) -> str:
    match = _CONCEPT_ID.fullmatch(source_concept_id)
    if match is None:
        raise VerticalSliceError(f"concept id {source_concept_id!r} is not a source-local ordinal id")
    return f"urn:ref:fr-thesaurus-1995:concept:{match.group(1)}"


@dataclass(frozen=True, slots=True)
class _ExpressionSeed:
    member_iri: str
    source_path: str
    original_literal: str
    language_tag: str | None
    datatype_iri: str | None
    source_kind: str
    source_record_id: str
    locator: SourceLocator

    def corpus_identity(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "member": self.member_iri,
            "sourcePath": self.source_path,
            "originalLiteral": self.original_literal,
            "sourceKind": self.source_kind,
            "sourceRecordId": self.source_record_id,
            "sourceLocator": _locator_payload(self.locator),
        }
        if self.language_tag is not None:
            result["language"] = self.language_tag
        if self.datatype_iri is not None:
            result["datatype"] = self.datatype_iri
        return result


@dataclass(frozen=True, slots=True)
class LocalCandidateGovernance:
    """One explicit project-local approval for development candidate lookup."""

    actor_iri: str
    organization_iri: str
    effective_at: str

    def __post_init__(self) -> None:
        for label, value in (
            ("actor_iri", self.actor_iri),
            ("organization_iri", self.organization_iri),
        ):
            if _ABSOLUTE_IRI.fullmatch(value) is None:
                raise VerticalSliceError(f"{label} must be an absolute IRI")
        if not self.effective_at.endswith("Z") or "T" not in self.effective_at:
            raise VerticalSliceError("effective_at must be an RFC 3339 UTC timestamp")


@dataclass(frozen=True, slots=True)
class RegistrySelectionState:
    """Exact selected decision and release for one development environment."""

    environment_iri: str
    selected_decision: Mapping[str, str] | None
    selected_release: Mapping[str, str] | None

    def digest(self) -> str:
        return _digest_json(
            {
                "environment": self.environment_iri,
                "selectedDecision": (dict(self.selected_decision) if self.selected_decision is not None else None),
                "selectedRelease": (dict(self.selected_release) if self.selected_release is not None else None),
            }
        )


@dataclass(frozen=True, slots=True)
class RegistrySelectionReduction:
    """Append-only reduction trace for deployment and rollback decisions."""

    initial_state: RegistrySelectionState
    final_state: RegistrySelectionState
    state_digests: tuple[str, ...]
    decision_references: tuple[Mapping[str, str], ...]


def _deployment_decision_reference(
    decision: Mapping[str, Any],
) -> dict[str, str]:
    if decision.get("type") != "urn:ref:type:RegistryDeploymentDecision":
        raise VerticalSliceError("selection history accepts only RegistryDeploymentDecision records")
    expected = binding.canonical_payload_digest(dict(decision))
    if decision.get("canonicalPayloadDigest") != expected:
        raise VerticalSliceError(f"deployment decision {decision.get('id')!r} has a stale digest")
    identifier = decision.get("id")
    if not isinstance(identifier, str) or _ABSOLUTE_IRI.fullmatch(identifier) is None:
        raise VerticalSliceError("deployment decision id must be an absolute IRI")
    return {"id": identifier, "digest": expected}


def _decision_time(value: object) -> dt.datetime:
    if not isinstance(value, str):
        raise VerticalSliceError("deployment decision effectiveAt is required")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise VerticalSliceError("deployment decision effectiveAt is not RFC 3339") from error
    if parsed.tzinfo is None:
        raise VerticalSliceError("deployment decision effectiveAt must include a timezone")
    return parsed


def reduce_registry_selection_history(
    decisions: Sequence[Mapping[str, Any]],
    *,
    environment_iri: str = DEVELOPMENT_ENVIRONMENT_IRI,
) -> RegistrySelectionReduction:
    """Reduce append-only decisions, restoring the saved state on rollback."""

    initial = RegistrySelectionState(
        environment_iri=environment_iri,
        selected_decision=None,
        selected_release=None,
    )
    current = initial
    saved_states: list[RegistrySelectionState] = []
    state_digests = [initial.digest()]
    references: list[Mapping[str, str]] = []
    previous_time: dt.datetime | None = None
    for index, decision in enumerate(decisions):
        reference = _deployment_decision_reference(decision)
        environment = decision.get("environment")
        if not isinstance(environment, Mapping) or environment.get("id") != environment_iri:
            raise VerticalSliceError(f"deployment decision {index} targets another environment")
        effective_at = _decision_time(decision.get("effectiveAt"))
        if previous_time is not None and effective_at <= previous_time:
            raise VerticalSliceError("deployment decisions must be strictly ordered by effectiveAt")
        previous_time = effective_at
        selection_state = decision.get("selectionState")
        if selection_state == "selected":
            predecessor = decision.get("predecessor")
            if current.selected_decision is None:
                if predecessor is not None:
                    raise VerticalSliceError("initial selection cannot invent a predecessor")
            elif predecessor != current.selected_decision:
                raise VerticalSliceError("selected decision predecessor does not match current state")
            release = decision.get("referenceResourceRelease")
            if not isinstance(release, Mapping):
                raise VerticalSliceError("selected decision lacks its exact release")
            saved_states.append(current)
            current = RegistrySelectionState(
                environment_iri=environment_iri,
                selected_decision=reference,
                selected_release=dict(release),
            )
        elif selection_state == "deselected":
            if (
                current.selected_decision is None
                or decision.get("predecessor") != current.selected_decision
                or not saved_states
            ):
                raise VerticalSliceError("rollback predecessor does not match the selected state")
            current = saved_states.pop()
        elif selection_state in {"failed", "quarantined", "staged"}:
            predecessor = decision.get("predecessor")
            if predecessor is not None and predecessor != current.selected_decision:
                raise VerticalSliceError(f"{selection_state} decision predecessor does not match current state")
        else:
            raise VerticalSliceError(f"unsupported deployment selectionState {selection_state!r}")
        references.append(reference)
        state_digests.append(current.digest())
    return RegistrySelectionReduction(
        initial_state=initial,
        final_state=current,
        state_digests=tuple(state_digests),
        decision_references=tuple(references),
    )


def _parquet_bytes(
    *,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> bytes:
    """Return deterministic all-string Parquet bytes for a managed table."""

    schema = pa.schema([(column, pa.string()) for column in columns])
    normalized: list[dict[str, str | None]] = []
    for row in rows:
        normalized.append(
            {
                column: (
                    None
                    if row.get(column) is None
                    else canonical_json(row[column])
                    if isinstance(row[column], (dict, list, tuple))
                    else str(row[column])
                )
                for column in columns
            }
        )
    table = pa.Table.from_pylist(normalized, schema=schema) if normalized else schema.empty_table()
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="zstd")
    return sink.getvalue().to_pybytes()


def _artifact_descriptor(path: str, payload: bytes) -> dict[str, str]:
    return {"path": path, "sha256": _sha256_bytes(payload)}


def _record_artifact_path(record: Mapping[str, Any]) -> str:
    record_type = str(record.get("type", ""))
    names = {
        "urn:ref:type:EnrichmentProfile": "enrichment-profile.json",
        "urn:ref:type:OutputProfile": "output-profile.json",
        "urn:ref:type:RightsAssessment": "rights-assessment.json",
        "urn:ref:type:Capture": "capture.json",
        "urn:ref:type:RegistryImportSnapshot": "registry-import-snapshot.json",
        "urn:ref:type:RegistryImportCoverageReport": "registry-import-coverage-report.json",
        "urn:ref:type:RunReceipt": "run-receipt.json",
    }
    if record_type == "urn:ref:type:RegistryDeploymentDecision":
        if record.get("id") != SELECTED_DEPLOYMENT_IRI:
            raise VerticalSliceError(
                "the active managed release may package only its selected "
                "deployment decision"
            )
        return "records/registry-deployment-selected.json"
    name = names.get(record_type)
    if name is None:
        raise VerticalSliceError(f"managed release has no artifact name for {record_type!r}")
    return f"records/{name}"


@dataclass(frozen=True, slots=True)
class VerticalSliceBundle:
    """One validated, candidate-only RefSpec managed-release bundle."""

    rulespec_graph: Mapping[str, Any]
    normalized_labels: tuple[Mapping[str, Any], ...]
    normalized_relations: tuple[Mapping[str, Any], ...]
    indexed_expressions: tuple[Mapping[str, Any], ...]
    coverage_report: Mapping[str, Any]
    operational_records: tuple[Mapping[str, Any], ...]
    publication_release_manifest: Mapping[str, Any]
    combined_validation_receipt: Mapping[str, Any]
    rulespec_dependency_manifest_bytes: bytes
    recorded_at: str
    recorded_by: str
    source_sha256: str
    source_lines: int
    source_bytes: int
    expression_corpus_digest: str

    def _content_artifacts(self) -> dict[str, bytes]:
        artifacts = {
            "rulespec/release.jsonld": _canonical_json_bytes(self.rulespec_graph),
            "records/publication-release-manifest.json": (_canonical_json_bytes(self.publication_release_manifest)),
            "validation/combined-receipt.json": _canonical_json_bytes(self.combined_validation_receipt),
            "rulespec/rulespec-dependency.json": (self.rulespec_dependency_manifest_bytes),
            "tables/concept_labels.parquet": _parquet_bytes(
                columns=CONCEPT_LABEL_COLUMNS,
                rows=self.normalized_labels,
            ),
            "tables/concept_relations.parquet": _parquet_bytes(
                columns=CONCEPT_RELATION_COLUMNS,
                rows=self.normalized_relations,
            ),
            "tables/concept_event_participants.parquet": _parquet_bytes(
                columns=CONCEPT_EVENT_PARTICIPANT_COLUMNS,
                rows=(),
            ),
            "corpus/indexed-expressions.jsonl": _canonical_jsonl_bytes(self.indexed_expressions),
        }
        for record in self.operational_records:
            path = _record_artifact_path(record)
            if path in artifacts:
                raise VerticalSliceError(f"duplicate managed artifact path {path}")
            artifacts[path] = _canonical_json_bytes(record)
        return dict(sorted(artifacts.items()))

    def manifest(self) -> dict[str, Any]:
        """Return the closed manifest consumed by ``ManagedReleaseView``."""

        content = self._content_artifacts()
        operational_paths = [_record_artifact_path(record) for record in self.operational_records]
        return {
            "bundleVersion": "1.0",
            "publicationReleaseManifest": _artifact_descriptor(
                "records/publication-release-manifest.json",
                content["records/publication-release-manifest.json"],
            ),
            "refRecords": [_artifact_descriptor(path, content[path]) for path in operational_paths],
            "rulespecGraph": _artifact_descriptor(
                "rulespec/release.jsonld",
                content["rulespec/release.jsonld"],
            ),
            "rulespecGraphId": GRAPH_IRI,
            "rulespecDependencyManifest": _artifact_descriptor(
                "rulespec/rulespec-dependency.json",
                content["rulespec/rulespec-dependency.json"],
            ),
            "combinedValidationReceipt": _artifact_descriptor(
                "validation/combined-receipt.json",
                content["validation/combined-receipt.json"],
            ),
            "normalizedTables": [
                {
                    "name": name,
                    **_artifact_descriptor(path, content[path]),
                }
                for name, path in (
                    ("concept_labels", "tables/concept_labels.parquet"),
                    ("concept_relations", "tables/concept_relations.parquet"),
                    (
                        "concept_event_participants",
                        "tables/concept_event_participants.parquet",
                    ),
                )
            ],
            "indexedExpressionCorpus": {
                **_artifact_descriptor(
                    "corpus/indexed-expressions.jsonl",
                    content["corpus/indexed-expressions.jsonl"],
                ),
                "expressionCorpusSnapshot": {
                    "id": EXPRESSION_CORPUS_IRI,
                    "digest": self.expression_corpus_digest,
                },
            },
        }

    def artifact_bytes(self) -> dict[str, bytes]:
        artifacts = self._content_artifacts()
        artifacts["managed-release-bundle.json"] = _canonical_json_bytes(self.manifest())
        return dict(sorted(artifacts.items()))

    def write_to(self, output_dir: Path) -> Mapping[str, Path]:
        """Write only small derived artifacts; never write native source bytes."""

        output_dir.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}
        for relative, payload in self.artifact_bytes().items():
            destination = output_dir / relative
            if destination.exists() and destination.read_bytes() != payload:
                raise FileExistsError(f"refusing to overwrite different artifact {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            written[relative] = destination
        return written


@dataclass(frozen=True, slots=True)
class RollbackProofBundle:
    """Separate append-only evidence that rollback restores the prior state."""

    selected_decision: Mapping[str, Any]
    rollback_decision: Mapping[str, Any]
    reduction_receipt: Mapping[str, Any]
    combined_validation_receipt: Mapping[str, Any]
    reduction: RegistrySelectionReduction
    active_publication: Mapping[str, str]

    def manifest(self) -> dict[str, Any]:
        artifacts = self._content_artifacts()
        return {
            "bundleVersion": "1.0",
            "historyKind": "appendOnlyRegistrySelectionRollback",
            "activePublication": dict(self.active_publication),
            "initialSelectionStateDigest": (
                self.reduction.initial_state.digest()
            ),
            "finalSelectionStateDigest": self.reduction.final_state.digest(),
            "history": [
                _artifact_descriptor(
                    "history/registry-deployment-selected.json",
                    artifacts[
                        "history/registry-deployment-selected.json"
                    ],
                ),
                _artifact_descriptor(
                    "history/registry-deployment-rollback.json",
                    artifacts[
                        "history/registry-deployment-rollback.json"
                    ],
                ),
            ],
            "reductionReceipt": _artifact_descriptor(
                "history/selection-reduction-receipt.json",
                artifacts["history/selection-reduction-receipt.json"],
            ),
            "combinedValidationReceipt": _artifact_descriptor(
                "validation/rollback-combined-receipt.json",
                artifacts["validation/rollback-combined-receipt.json"],
            ),
        }

    def _content_artifacts(self) -> dict[str, bytes]:
        return {
            "history/registry-deployment-rollback.json": (
                _canonical_json_bytes(self.rollback_decision)
            ),
            "history/registry-deployment-selected.json": (
                _canonical_json_bytes(self.selected_decision)
            ),
            "history/selection-reduction-receipt.json": (
                _canonical_json_bytes(self.reduction_receipt)
            ),
            "validation/rollback-combined-receipt.json": (
                _canonical_json_bytes(self.combined_validation_receipt)
            ),
        }

    def artifact_bytes(self) -> dict[str, bytes]:
        artifacts = self._content_artifacts()
        artifacts["rollback-history-bundle.json"] = (
            _canonical_json_bytes(self.manifest())
        )
        return dict(sorted(artifacts.items()))

    def write_to(self, output_dir: Path) -> Mapping[str, Path]:
        """Write rollback evidence outside the active managed release."""

        output_dir.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}
        for relative, payload in self.artifact_bytes().items():
            destination = output_dir / relative
            if (
                destination.exists()
                and destination.read_bytes() != payload
            ):
                raise FileExistsError(
                    f"refusing to overwrite different artifact {destination}"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            written[relative] = destination
        return written


def _policy_reference(identifier: str, version: str, description: object) -> dict[str, str]:
    return {
        "id": identifier,
        "version": version,
        "digest": _digest_json(description),
    }


_NORMALIZATION_POLICY = _policy_reference(
    NORMALIZATION_POLICY_IRI,
    "1.0",
    {
        "unicodeNormalization": "NFKC",
        "case": "Unicode casefold",
        "whitespace": "collapse",
        "transliteration": False,
    },
)
_EXCLUSION_POLICY = _policy_reference(
    EXCLUSION_POLICY_IRI,
    "1.0",
    {
        "rule": "Do not invent a preferred concept identity or relationship target.",
        "disposition": "itemizedParsingExclusion",
        "productionEligible": False,
    },
)
_IMPORT_PROFILE = _policy_reference(
    IMPORT_PROFILE_IRI,
    "1.0",
    {
        "parserVersion": PARSER_VERSION,
        "language": "en",
        "unresolvedReferencePolicy": _EXCLUSION_POLICY,
    },
)


def _rulespec_context(validator: RulespecValidatorPin) -> Mapping[str, Any]:
    context_path = validator.working_directory / "context" / "rkaf-context.jsonld"
    try:
        document = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VerticalSliceError(f"cannot read pinned Rulespec JSON-LD context: {error}") from error
    context = document.get("@context") if isinstance(document, dict) else None
    if not isinstance(context, dict):
        raise VerticalSliceError("pinned Rulespec context has no @context object")
    return context


def _compute_rulespec_release_digest(
    graph: Mapping[str, Any],
    validator: RulespecValidatorPin,
) -> str:
    """Ask the pinned Rulespec RDFC-1.0 tool for the release digest."""

    with tempfile.TemporaryDirectory(prefix="refspec-fr-thesaurus-release-digest-") as temporary:
        graph_path = Path(temporary) / "release-without-digest.jsonld"
        graph_path.write_bytes(_canonical_json_bytes(graph))
        command = [
            "uv",
            "run",
            "--python",
            "3.12",
            "--with-requirements",
            "requirements.txt",
            "python",
            "tools/reference_release_digest.py",
            str(graph_path),
            "--release",
            RELEASE_IRI,
            "--json",
        ]
        try:
            result = subprocess.run(
                command,
                cwd=validator.working_directory,
                check=False,
                text=True,
                capture_output=True,
            )
        except OSError as error:
            raise VerticalSliceError(f"cannot execute pinned Rulespec release-digest tool: {error}") from error
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        detail = (result.stderr or result.stdout).strip()
        raise VerticalSliceError(f"pinned Rulespec release-digest tool returned unreadable output: {detail}") from error
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or rows[0].get("release") != RELEASE_IRI
        or rows[0].get("declared") is not None
    ):
        raise VerticalSliceError("pinned Rulespec release-digest tool did not report the one undeclared release")
    computed = rows[0].get("computed")
    if not isinstance(computed, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", computed) is None:
        raise VerticalSliceError("pinned Rulespec release-digest tool returned an invalid digest")
    # Exit 1 is expected because this first pass intentionally has no declared
    # digest. Any setup/error exit remains a hard failure.
    if result.returncode not in {0, 1}:
        detail = (result.stderr or result.stdout).strip()
        raise VerticalSliceError("pinned Rulespec release-digest tool failed: " + detail)
    return computed


_CORE_FACET_ROWS: tuple[Mapping[str, Any], ...] = (
    {
        "iri": "urn:ref:facet:general-subject",
        "label": "General subject",
        "definition": "A cross-domain matter that describes what the target is substantively about.",
        "inclusionCues": ["Central policy issue"],
        "exclusionCues": ["Named referent"],
        "compatibleResourceRoutes": [
            "document",
            "participation",
            "container",
            "externalReference",
        ],
        "compatibleAssignmentPredicates": [
            "https://rulespec.org/ns/v1#assignmentPrimary",
            "https://rulespec.org/ns/v1#assignmentSubstantive",
            "https://rulespec.org/ns/v1#assignmentContextual",
            "https://rulespec.org/ns/v1#assignmentMention",
        ],
    },
    {
        "iri": "urn:ref:facet:specialist-subject",
        "label": "Specialist subject",
        "definition": "A domain-specific matter that depends on a specialist vocabulary.",
        "inclusionCues": ["Specialist technical topic"],
        "exclusionCues": ["Named entity"],
        "compatibleResourceRoutes": ["document", "externalReference"],
        "compatibleAssignmentPredicates": [
            "https://rulespec.org/ns/v1#assignmentPrimary",
            "https://rulespec.org/ns/v1#assignmentMention",
        ],
    },
    {
        "iri": "urn:ref:facet:entity",
        "label": "Entity",
        "definition": "A particular or resolvable referent.",
        "inclusionCues": ["Stable identifier"],
        "exclusionCues": ["Subject class"],
        "compatibleResourceRoutes": ["document", "entity"],
        "compatibleAssignmentPredicates": ["https://rulespec.org/ns/v1#assignmentMention"],
    },
    {
        "iri": "urn:ref:facet:legal-location",
        "label": "Legal location",
        "definition": "A governed location or citation in a legal authority.",
        "inclusionCues": ["Resolvable legal citation"],
        "exclusionCues": ["General legal topic"],
        "compatibleResourceRoutes": ["document", "event"],
        "compatibleAssignmentPredicates": ["https://rulespec.org/ns/v1#assignmentMention"],
    },
    {
        "iri": "urn:ref:facet:industry-classification",
        "label": "Industry classification",
        "definition": "Membership in a governed economic-activity classification.",
        "inclusionCues": ["Exact classification release"],
        "exclusionCues": ["Named company"],
        "compatibleResourceRoutes": ["document", "entity"],
        "compatibleAssignmentPredicates": ["https://rulespec.org/ns/v1#assignmentSubstantive"],
    },
    {
        "iri": "urn:ref:facet:affected-population",
        "label": "Affected population",
        "definition": "A class materially regulated, protected, eligible, or burdened.",
        "inclusionCues": ["Scope language"],
        "exclusionCues": ["Named entity"],
        "compatibleResourceRoutes": ["document", "observation"],
        "compatibleAssignmentPredicates": ["https://rulespec.org/ns/v1#assignmentSubstantive"],
    },
    {
        "iri": "urn:ref:facet:genre",
        "label": "Genre",
        "definition": "The communicative form or source kind of the target.",
        "inclusionCues": ["Governed document form"],
        "exclusionCues": ["Substantive topic"],
        "compatibleResourceRoutes": ["document", "participation"],
        "compatibleAssignmentPredicates": ["https://rulespec.org/ns/v1#assignmentContextual"],
    },
    {
        "iri": "urn:ref:facet:regulatory-action",
        "label": "Regulatory action",
        "definition": "An action proposed, performed, or decided by a regulatory actor.",
        "inclusionCues": ["Supported action relation"],
        "exclusionCues": ["Document genre"],
        "compatibleResourceRoutes": ["document", "event"],
        "compatibleAssignmentPredicates": ["https://rulespec.org/ns/v1#assignmentSubstantive"],
    },
    {
        "iri": "urn:ref:facet:administrative-process-stage",
        "label": "Administrative process stage",
        "definition": "A governed phase or status in an administrative workflow.",
        "inclusionCues": ["Named workflow stage"],
        "exclusionCues": ["Action"],
        "compatibleResourceRoutes": ["document", "event"],
        "compatibleAssignmentPredicates": ["https://rulespec.org/ns/v1#assignmentContextual"],
    },
    {
        "iri": "urn:ref:facet:code-list-value",
        "label": "Code-list value",
        "definition": "A member of a governed operational value set.",
        "inclusionCues": ["Exact code-list release"],
        "exclusionCues": ["Free text"],
        "compatibleResourceRoutes": ["document", "container"],
        "compatibleAssignmentPredicates": ["https://rulespec.org/ns/v1#assignmentContextual"],
    },
    {
        "iri": "urn:ref:facet:ontology-class",
        "label": "Ontology class",
        "definition": "Class membership in an identified ontology.",
        "inclusionCues": ["Exact ontology class IRI"],
        "exclusionCues": ["More specific core facet"],
        "compatibleResourceRoutes": ["document", "entity"],
        "compatibleAssignmentPredicates": ["https://rulespec.org/ns/v1#assignmentContextual"],
    },
    {
        "iri": "urn:ref:facet:observation-measure",
        "label": "Observation and measure",
        "definition": "A measured, counted, estimated, modeled, or observed value.",
        "inclusionCues": ["Unit-bearing quantity"],
        "exclusionCues": ["Topic about measurement"],
        "compatibleResourceRoutes": ["observation", "event"],
        "compatibleAssignmentPredicates": ["https://rulespec.org/ns/v1#assignmentSubstantive"],
    },
)


def _build_profiles(
    *,
    recorded_at: str,
    recorded_by: str,
    release_reference: Mapping[str, str],
    import_reference: Mapping[str, str],
) -> tuple[
    EnrichmentProfile,
    Mapping[str, Any],
    OutputProfile,
    Mapping[str, Any],
]:
    enrichment_profile = EnrichmentProfile(
        profile_id=ENRICHMENT_PROFILE_IRI,
        version="1.0.0",
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        operational_state="developmentOnly",
        facets=_CORE_FACET_ROWS,
    )
    enrichment_record = enrichment_profile.sealed_payload()
    output_profile = OutputProfile(
        profile_id=OUTPUT_PROFILE_IRI,
        version="1.0-development",
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        operational_state="developmentOnly",
        enrichment_profile=enrichment_profile.reference,
        acceptance_policies=(
            _policy_reference(
                "urn:ref:acceptance-policy:candidate-only-development:v1",
                "1.0",
                {
                    "candidateUse": True,
                    "acceptedOutputUse": False,
                    "productionEligible": False,
                },
            ),
        ),
        publication_views=(
            _policy_reference(
                "urn:ref:publication-view:local-experimental-playground:v1",
                "1.0",
                {
                    "audience": "localDevelopment",
                    "authorityClaim": "none",
                },
            ),
        ),
        release_permissions=(
            {
                "facet": GENERAL_SUBJECT_FACET_IRI,
                "assignmentRole": ASSIGNMENT_PRIMARY_IRI,
                "referenceResourceRelease": dict(release_reference),
                "registryImportSnapshot": dict(import_reference),
                "requiredImportFeatures": list(_FEATURE_ORDER),
                "candidateUse": True,
                "acceptedOutputUse": False,
            },
        ),
        mapping_permissions=(),
        open_label_permissions=(),
        enrichment_profile_record=enrichment_profile,
    )
    return (
        enrichment_profile,
        enrichment_record,
        output_profile,
        output_profile.sealed_payload(),
    )


def _rights_evidence_nodes() -> tuple[dict[str, Any], ...]:
    """Return typed Rulespec fragments behind the project rights decision."""

    evidence = (
        (
            OFR_AUTHORSHIP_ARTIFACT_IRI,
            OFR_AUTHORSHIP_FRAGMENT_IRI,
            OFR_AUTHORSHIP_EVIDENCE_IRI,
            "application/pdf",
            ("The compilation of a thesaurus at the Office of the Federal Register"),
        ),
        (
            OFR_CURRENT_USE_ARTIFACT_IRI,
            OFR_CURRENT_USE_FRAGMENT_IRI,
            OFR_CURRENT_USE_EVIDENCE_IRI,
            "text/html",
            (
                "The Office of the Federal Register uses the Thesaurus as "
                "the basis for the subject entries in the CFR Index"
            ),
        ),
        (
            US_GOVERNMENT_WORKS_LAW_ARTIFACT_IRI,
            US_GOVERNMENT_WORKS_LAW_FRAGMENT_IRI,
            US_GOVERNMENT_WORKS_LAW_IRI,
            "text/html",
            ("Copyright protection under this title is not available for any work of the United States Government"),
        ),
    )
    nodes: list[dict[str, Any]] = []
    for artifact_iri, fragment_iri, source_url, media_type, exact in evidence:
        nodes.extend(
            (
                {
                    "@id": artifact_iri,
                    "@type": "rkaf:Artifact",
                    "rkaf:hasArtifactIdentifier": [source_url],
                    "rkaf:artifactIdentifierScheme": ["rkaf:partner-defined"],
                    "dcterms:format": media_type,
                },
                {
                    "@id": fragment_iri,
                    "@type": "rkaf:SourceFragment",
                    "oa:hasSource": artifact_iri,
                    "oa:hasSelector": [
                        {
                            "@type": "oa:TextQuoteSelector",
                            "oa:exact": exact,
                        }
                    ],
                    "rkaf:selectorKind": ["oa:TextQuoteSelector"],
                    "rkaf:fragmentContentDigest": _sha256_bytes(exact.encode("utf-8")),
                },
            )
        )
    return tuple(nodes)


def _local_candidate_governance_nodes(
    governance: LocalCandidateGovernance,
) -> tuple[dict[str, Any], ...]:
    """Materialize only project-local review and use authorization."""

    return (
        {
            "@id": SELECTION_ASSERTION_IRI,
            "@type": "rkaf:ValueAssertion",
            "rkaf:assertionOrigin": "rkaf:humanAsserted",
            "rkaf:epistemicBasis": "rkaf:editorialAssertion",
            "rkaf:assertsSubject": RELEASE_IRI,
            "rkaf:assertsPredicate": ("urn:ref:predicate:eligible-for-local-candidate-lookup"),
            "rkaf:assertsValue": {
                "@value": "true",
                "@type": "xsd:boolean",
            },
            "rkaf:assertionPolarity": "rkaf:affirmed",
            "rkaf:usageEligibility": "rkaf:notEligible",
            "rkaf:assertedAt": governance.effective_at,
            "rkaf:hasAccessScope": ACCESS_SCOPE_IRI,
        },
        {
            "@id": SELECTION_EVIDENCE_IRI,
            "@type": "rkaf:EvidenceBinding",
            "rkaf:bindsAssertion": SELECTION_ASSERTION_IRI,
            "rkaf:noEvidenceReason": "rkaf:consensus-without-citation",
        },
        {
            "@id": SELECTION_ATTESTATION_IRI,
            "@type": "rkaf:Attestation",
            "rkaf:attestor": governance.actor_iri,
            "rkaf:attestorKind": "rkaf:formalReviewer",
            "rkaf:targets": [SELECTION_ASSERTION_IRI],
            "rkaf:decision": "rkaf:approved",
            "rkaf:attestationScope": DEVELOPMENT_ENVIRONMENT_IRI,
            "rkaf:attestedAt": governance.effective_at,
        },
        {
            "@id": SELECTION_ADOPTION_IRI,
            "@type": "rkaf:LocalAdoption",
            "rkaf:organization": governance.organization_iri,
            "rkaf:targetAssertion": SELECTION_ASSERTION_IRI,
            "rkaf:adoptionStatus": "rkaf:active",
            "rkaf:usageEligibility": "rkaf:localOperationalUse",
            "rkaf:adoptionAuthorityKind": "rkaf:localOperational",
            "rkaf:adoptionScope": DEVELOPMENT_ENVIRONMENT_IRI,
            "rkaf:authorizedBy": governance.actor_iri,
            "rkaf:adoptedAt": governance.effective_at,
            "rkaf:basedOnAttestation": SELECTION_ATTESTATION_IRI,
        },
    )


def _build_rulespec_graph(
    parsed: FederalRegisterThesaurus,
    concept_iris: Mapping[str, str],
    validator: RulespecValidatorPin,
    governance: LocalCandidateGovernance | None,
) -> tuple[dict[str, Any], str]:
    labels_by_concept: dict[str, list[Any]] = {}
    for label in parsed.labels:
        labels_by_concept.setdefault(label.concept_id, []).append(label)
    notes_by_concept: dict[str, list[Any]] = {}
    for note in parsed.scope_notes:
        if note.concept_id is not None:
            notes_by_concept.setdefault(note.concept_id, []).append(note)
    notation_by_concept: dict[str, list[Any]] = {}
    for notation in parsed.category_notations:
        if notation.concept_id is not None:
            notation_by_concept.setdefault(notation.concept_id, []).append(notation)
    relations_by_concept: dict[str, list[Any]] = {}
    for relation in parsed.relations:
        if (
            relation.resolution_status == "resolved"
            and relation.source_concept_id is not None
            and relation.target_concept_id is not None
        ):
            relations_by_concept.setdefault(relation.source_concept_id, []).append(relation)

    scheme: dict[str, Any] = {
        "@id": SCHEME_IRI,
        "@type": "rkaf:ConceptScheme",
        "skos:prefLabel": {"en": "Federal Register Thesaurus of Indexing Terms, 1995"},
        "skos:definition": {
            "en": (
                "Content-derived development representation of the Federal "
                "Register's November 16, 1995 alphabetic thesaurus text."
            )
        },
        "rkaf:schemeFacet": GENERAL_SUBJECT_FACET_IRI,
        "rkaf:definedInScope": IMPORT_SCOPE_IRI,
    }

    concept_nodes: list[dict[str, Any]] = []
    for concept in parsed.concepts:
        concept_iri = concept_iris[concept.concept_id]
        labels = labels_by_concept.get(concept.concept_id, [])
        preferred = [item.literal for item in labels if item.role == "preferred"]
        if len(preferred) != 1:
            raise VerticalSliceError(f"{concept.concept_id} has {len(preferred)} preferred labels")
        alternates = [item.literal for item in labels if item.role == "alternate"]
        node: dict[str, Any] = {
            "@id": concept_iri,
            "@type": "rkaf:LocalConcept",
            "skos:prefLabel": {"en": preferred[0]},
            "skos:inScheme": SCHEME_IRI,
            "rkaf:definedInScope": IMPORT_SCOPE_IRI,
            "rkaf:conceptScope": IMPORT_SCOPE_IRI,
        }
        if alternates:
            node["skos:altLabel"] = {"en": alternates}
        concept_notes = notes_by_concept.get(concept.concept_id, [])
        if concept_notes:
            node["skos:scopeNote"] = {"en": [item.text for item in concept_notes]}
        concept_notations = notation_by_concept.get(concept.concept_id, [])
        if concept_notations:
            node["skos:notation"] = [
                {
                    "@value": item.raw_literal,
                    "@type": item.datatype_iri,
                }
                for item in concept_notations
            ]
        broader: list[str] = []
        related: list[str] = []
        for relation in relations_by_concept.get(concept.concept_id, []):
            assert relation.target_concept_id is not None
            target = concept_iris[relation.target_concept_id]
            if relation.predicate_iri == BROADER_PREDICATE_IRI:
                broader.append(target)
            elif relation.predicate_iri == ASSOCIATIVE_PREDICATE_IRI:
                related.append(target)
            else:  # pragma: no cover - parser invariant
                raise VerticalSliceError(f"unknown relation predicate {relation.predicate_iri!r}")
        if broader:
            node["skos:broader"] = broader
        if related:
            node["skos:related"] = related
        concept_nodes.append(node)

    distribution = {
        "@id": DISTRIBUTION_IRI,
        "@type": "rkaf:Artifact",
        "rkaf:hasArtifactIdentifier": [DISTRIBUTION_IRI],
        "rkaf:artifactIdentifierScheme": ["rkaf:partner-defined"],
        "dcterms:format": "text/plain",
        "rkaf:hasContentDigest": parsed.source_sha256,
    }
    release: dict[str, Any] = {
        "@id": RELEASE_IRI,
        "@type": "rkaf:ReferenceResourceRelease",
        "dcterms:isVersionOf": SCHEME_IRI,
        "dcat:version": RELEASE_VERSION,
        "dcterms:type": "skos:ConceptScheme",
        "dcterms:issued": SOURCE_ISSUED_AT,
        "rkaf:membershipMode": "rkaf:completeMembership",
        "prov:hadMember": [concept_iris[concept.concept_id] for concept in parsed.concepts],
        "dcat:distribution": [DISTRIBUTION_IRI],
        "rkaf:versionBasis": "rkaf:contentDerived",
    }
    graph = {
        "@context": _rulespec_context(validator),
        "@graph": [
            {
                "@id": GRAPH_IRI,
                "@type": "rkaf:Artifact",
                "rkaf:hasArtifactIdentifier": [GRAPH_IRI],
                "rkaf:artifactIdentifierScheme": ["rkaf:partner-defined"],
                "dcterms:format": "application/ld+json",
                "rkaf:hasContentDigest": _digest_json(
                    {
                        "sliceVersion": SLICE_VERSION,
                        "sourceDigest": parsed.source_sha256,
                        "role": "rulespecReleaseGraph",
                    }
                ),
            },
            {
                "@id": ACTIVITY_IRI,
                "@type": "prov:Activity",
            },
            {
                "@id": ACQUISITION_ACTIVITY_IRI,
                "@type": "prov:Activity",
            },
            {
                "@id": ACCESS_SCOPE_IRI,
                "@type": "rkaf:AccessScope",
                "rkaf:accessScopeKind": "rkaf:organizationVisible",
            },
            {
                "@id": RETENTION_POLICY_IRI,
                "@type": "rkaf:RetentionPolicy",
                "rkaf:retentionDurationDays": 36500,
                "rkaf:retentionTrigger": "rkaf:creation",
                "rkaf:retentionPostExpiry": "rkaf:archive",
            },
            *_rights_evidence_nodes(),
            *(_local_candidate_governance_nodes(governance) if governance is not None else ()),
            scheme,
            *concept_nodes,
            release,
            distribution,
        ],
    }
    release_digest = _compute_rulespec_release_digest(graph, validator)
    release["rkaf:referenceReleaseDigest"] = release_digest
    validation_result_digest = _digest_json(
        {
            "graph": GRAPH_IRI,
            "release": RELEASE_IRI,
            "referenceReleaseDigest": release_digest,
            "validatorIdentity": validator.identity,
            "validatorSourceRevision": validator.source_revision,
            "validatorEvidenceRevision": validator.evidence_revision,
            "expectedResult": "pass",
            "operationalState": "developmentOnly",
        }
    )
    graph["@graph"].append(
        {
            "@id": CONFORMANCE_RESULT_IRI,
            "@type": "rkaf:Artifact",
            "rkaf:hasArtifactIdentifier": [CONFORMANCE_RESULT_IRI],
            "rkaf:artifactIdentifierScheme": ["rkaf:partner-defined"],
            "dcterms:format": "application/json",
            "rkaf:hasContentDigest": validation_result_digest,
        }
    )
    return graph, release_digest


def _build_expression_seeds(
    parsed: FederalRegisterThesaurus,
    concept_iris: Mapping[str, str],
) -> tuple[_ExpressionSeed, ...]:
    seeds: list[_ExpressionSeed] = []
    for label in parsed.labels:
        property_iri = PREFERRED_LABEL_PROPERTY_IRI if label.role == "preferred" else ALTERNATE_LABEL_PROPERTY_IRI
        seeds.append(
            _ExpressionSeed(
                member_iri=concept_iris[label.concept_id],
                source_path=_source_path(
                    locator=label.locator,
                    property_iri=property_iri,
                    source_record_id=label.label_id,
                    source_entry_id=label.source_entry_id,
                ),
                original_literal=label.literal,
                language_tag=label.language_tag,
                datatype_iri=None,
                source_kind=label.source,
                source_record_id=label.label_id,
                locator=label.locator,
            )
        )
    for note in parsed.scope_notes:
        if note.concept_id is None:
            continue
        seeds.append(
            _ExpressionSeed(
                member_iri=concept_iris[note.concept_id],
                source_path=_source_path(
                    locator=note.locator,
                    property_iri=SCOPE_NOTE_PROPERTY_IRI,
                    source_record_id=note.note_id,
                    source_entry_id=note.source_entry_id,
                ),
                original_literal=note.text,
                language_tag=note.language_tag,
                datatype_iri=None,
                source_kind="scopeNote",
                source_record_id=note.note_id,
                locator=note.locator,
            )
        )
    for notation in parsed.category_notations:
        if notation.concept_id is None:
            continue
        seeds.append(
            _ExpressionSeed(
                member_iri=concept_iris[notation.concept_id],
                source_path=_source_path(
                    locator=notation.locator,
                    property_iri=NOTATION_PROPERTY_IRI,
                    source_record_id=notation.notation_id,
                    source_entry_id=notation.source_entry_id,
                ),
                original_literal=notation.raw_literal,
                language_tag=None,
                datatype_iri=notation.datatype_iri,
                source_kind="notation",
                source_record_id=notation.notation_id,
                locator=notation.locator,
            )
        )
    return tuple(seeds)


def _import_snapshot_digest(
    parsed: FederalRegisterThesaurus,
    expression_seeds: Sequence[_ExpressionSeed],
) -> str:
    return _digest_json(
        {
            "sourceDigest": parsed.source_sha256,
            "parserVersion": PARSER_VERSION,
            "entries": [asdict(item) for item in parsed.entries],
            "concepts": [asdict(item) for item in parsed.concepts],
            "labels": [asdict(item) for item in parsed.labels],
            "notations": [asdict(item) for item in parsed.category_notations],
            "notes": [asdict(item) for item in parsed.scope_notes],
            "crossReferences": [asdict(item) for item in parsed.cross_references],
            "relations": [asdict(item) for item in parsed.relations],
            "expressionCorpus": [item.corpus_identity() for item in expression_seeds],
        }
    )


def _record_base(
    *,
    record_id: str,
    record_type: str,
    recorded_at: str,
    recorded_by: str,
    operational_state: str = "developmentOnly",
) -> dict[str, Any]:
    return {
        "id": record_id,
        "type": record_type,
        "recordedAt": recorded_at,
        "recordedBy": recorded_by,
        "schemaVersion": "1.0",
        "operationalState": operational_state,
    }


def _digest_reference(record: Mapping[str, Any]) -> dict[str, str]:
    digest_field = binding.digest_field(dict(record))
    identifier = record.get("id")
    digest = record.get(digest_field)
    if not isinstance(identifier, str) or not isinstance(digest, str):
        raise VerticalSliceError("REF record lacks an exact digest reference")
    return {"id": identifier, "digest": digest}


def _versioned_reference(record: Mapping[str, Any]) -> dict[str, str]:
    reference = _digest_reference(record)
    version = record.get("version")
    if not isinstance(version, str):
        raise VerticalSliceError("REF record lacks a versioned digest reference")
    return {**reference, "version": version}


def _source_exclusions(
    parsed: FederalRegisterThesaurus,
) -> tuple[Mapping[str, Any], ...]:
    unbound_notes_by_entry: dict[str, list[Any]] = {}
    for note in parsed.scope_notes:
        if note.concept_id is None:
            unbound_notes_by_entry.setdefault(note.source_entry_id, []).append(note)

    exclusions: list[Mapping[str, Any]] = []
    for unresolved in parsed.unresolved_references:
        item: dict[str, Any] = {
            "id": (f"urn:ref:fr-thesaurus-1995:source-exclusion:{unresolved.unresolved_id}"),
            "kind": "unresolvedSourceReference",
            "stage": "parsing",
            "sourceEntryId": unresolved.source_entry_id,
            "referenceKind": unresolved.reference_kind,
            "rawTargetLabel": unresolved.raw_target_label,
            "sourceLocator": _locator_payload(unresolved.locator),
            "policy": dict(_EXCLUSION_POLICY),
            "rationale": unresolved.reason,
        }
        impacted_notes = unbound_notes_by_entry.get(unresolved.source_entry_id, [])
        if unresolved.reference_kind == "see" and impacted_notes:
            item["alsoExcludesScopeNotes"] = [
                {
                    "sourceRecordId": note.note_id,
                    "sourceLocator": _locator_payload(note.locator),
                }
                for note in impacted_notes
            ]
        exclusions.append(item)
    return tuple(exclusions)


def _build_rights_assessment(
    *,
    parsed: FederalRegisterThesaurus,
    recorded_at: str,
    recorded_by: str,
) -> Mapping[str, Any]:
    return seal_payload(
        {
            **_record_base(
                record_id=RIGHTS_ASSESSMENT_IRI,
                record_type="urn:ref:type:RightsAssessment",
                recorded_at=recorded_at,
                recorded_by=recorded_by,
                operational_state="projectDetermination",
            ),
            "target": {
                "kind": "source",
                "reference": {
                    "id": FEDERAL_REGISTER_THESAURUS_1995_URL,
                    "version": "1995-11-16",
                    "digest": parsed.source_sha256,
                },
            },
            "observedTerms": [
                {
                    "sourceFragment": OFR_AUTHORSHIP_FRAGMENT_IRI,
                    "summary": (
                        "The Office of the Federal Register published the "
                        "thesaurus and described compiling it at that Office "
                        "for Federal Register and Code of Federal Regulations "
                        "indexing."
                    ),
                },
                {
                    "sourceFragment": OFR_CURRENT_USE_FRAGMENT_IRI,
                    "summary": (
                        "The National Archives identifies the thesaurus as "
                        "the Office of the Federal Register vocabulary used "
                        "for Federal Register and Code of Federal Regulations "
                        "subject indexing."
                    ),
                },
                {
                    "sourceFragment": US_GOVERNMENT_WORKS_LAW_FRAGMENT_IRI,
                    "summary": (
                        "17 U.S.C. 105 states that United States copyright "
                        "protection is unavailable for a work of the United "
                        "States Government."
                    ),
                },
            ],
            "supportingSourceFragments": [
                OFR_AUTHORSHIP_FRAGMENT_IRI,
                OFR_CURRENT_USE_FRAGMENT_IRI,
                US_GOVERNMENT_WORKS_LAW_FRAGMENT_IRI,
            ],
            "permissions": {
                "acquisition": "permitted",
                "storage": "permitted",
                "indexing": "permitted",
                "modelUse": "permitted",
                "display": "permitted",
                "redistribution": "permitted",
                "retention": "permitted",
            },
            "purpose": (
                "Project determination for loss-detection, indexing, and "
                "candidate lookup in a local development experiment. This "
                "project assumes the 1995 revision remains an Office of the "
                "Federal Register United States Government work; the cited "
                "sources do not independently establish the contributor "
                "history of every revision. The project accepts that "
                "uncertainty for experimental use and redistribution. This "
                "record is not legal clearance and does not authorize "
                "production deployment. Native source bytes remain outside "
                "Git."
            ),
            "attribution": (
                "Office of the Federal Register, Federal Register Thesaurus of Indexing Terms, 16 November 1995."
            ),
            "audience": "Local RefSpec and Spicy Regs development users",
            "effectiveAt": recorded_at,
            "rulespecPolicyRefs": [],
            "attestationRefs": [],
            "localAdoptionRefs": [],
        }
    )


def _build_capture(
    *,
    parsed: FederalRegisterThesaurus,
    rights_record: Mapping[str, Any],
    recorded_at: str,
    recorded_by: str,
) -> Mapping[str, Any]:
    digest_hex = parsed.source_sha256.removeprefix("sha256:")
    return seal_payload(
        {
            **_record_base(
                record_id=CAPTURE_IRI,
                record_type="urn:ref:type:Capture",
                recorded_at=recorded_at,
                recorded_by=recorded_by,
                operational_state="capturedDevelopmentInput",
            ),
            "source": {
                "id": FEDERAL_REGISTER_THESAURUS_1995_URL,
                "version": "1995-11-16",
                "digest": parsed.source_sha256,
            },
            "sourceLocator": FEDERAL_REGISTER_THESAURUS_1995_URL,
            "requestMethod": "explicitContentAddressedLocalResolver",
            "safeRequestParameters": {
                "expectedDigest": parsed.source_sha256,
                "networkFetchDuringBuild": "false",
            },
            "retrievalStartedAt": recorded_at,
            "retrievalEndedAt": recorded_at,
            "responseStatus": "verified-local-content-addressed-input",
            "requestHeaders": {},
            "responseHeaders": {"content-type": "text/plain"},
            "mediaType": "text/plain",
            "acquisitionStatus": "success",
            "byteDigest": parsed.source_sha256,
            "byteLength": parsed.source_bytes,
            "storageReference": ("urn:ref:content-addressed-local-source:sha256:" + digest_hex),
            "contentPreservation": "exactBytes",
            "completeness": {
                "complete": True,
                "pagination": {},
                "retries": [],
                "exclusions": [],
            },
            "acquisitionActivity": ACQUISITION_ACTIVITY_IRI,
            "runReceipt": RECEIPT_IRI,
            "accessScopeRefs": [ACCESS_SCOPE_IRI],
            "retentionPolicyRefs": [RETENTION_POLICY_IRI],
            "rightsExpressionRefs": [str(rights_record["id"])],
        }
    )


def _build_import_snapshot(
    *,
    parsed: FederalRegisterThesaurus,
    capture_record: Mapping[str, Any],
    rights_record: Mapping[str, Any],
    release_reference: Mapping[str, str],
    projection_digest: str,
    conformance_result_digest: str,
    exclusions: Sequence[Mapping[str, Any]],
    recorded_at: str,
    recorded_by: str,
) -> Mapping[str, Any]:
    return seal_payload(
        {
            **_record_base(
                record_id=IMPORT_SNAPSHOT_IRI,
                record_type="urn:ref:type:RegistryImportSnapshot",
                recorded_at=recorded_at,
                recorded_by=recorded_by,
            ),
            "inventoryCoverageComponent": ("urn:ref:inventory-component:federal-register-thesaurus-1995"),
            "importProfile": dict(_IMPORT_PROFILE),
            "captures": [_digest_reference(capture_record)],
            "externalReferences": [],
            "referenceResourceRelease": dict(release_reference),
            "distributionArtifacts": [{"id": DISTRIBUTION_IRI, "digest": parsed.source_sha256}],
            "rightsAssessment": _digest_reference(rights_record),
            "adoptedPolicyRefs": [str(_EXCLUSION_POLICY["id"])],
            "transformation": {
                "id": "urn:ref:implementation:fr-thesaurus-1995-lossless-parser",
                "revision": PARSER_VERSION,
                "digest": projection_digest,
            },
            "exclusions": [dict(item) for item in exclusions],
            "failures": [],
            "rulespecValidationResult": {
                "id": CONFORMANCE_RESULT_IRI,
                "digest": conformance_result_digest,
            },
            "refValidationResult": {
                "id": "urn:ref:validation-result:fr-thesaurus-bundle:v1",
                "digest": _digest_json(
                    {
                        "gate": "REF JSON Binding 1.0",
                        "expected": "pass",
                        "sliceVersion": SLICE_VERSION,
                    }
                ),
            },
            "expectedRefreshCadence": "historical-frozen",
            "activity": ACTIVITY_IRI,
            "receipt": RECEIPT_IRI,
        }
    )


def _build_expressions(
    *,
    seeds: Sequence[_ExpressionSeed],
    recorded_at: str,
    recorded_by: str,
    release_digest: str,
    import_snapshot_digest: str,
    expression_corpus_digest: str,
    source_digest: str,
) -> tuple[Mapping[str, Any], ...]:
    release_reference = {
        "id": RELEASE_IRI,
        "version": RELEASE_VERSION,
        "digest": release_digest,
    }
    import_reference = {
        "id": IMPORT_SNAPSHOT_IRI,
        "digest": import_snapshot_digest,
    }
    distribution_reference = {
        "id": DISTRIBUTION_IRI,
        "digest": source_digest,
    }
    corpus_reference = {
        "id": EXPRESSION_CORPUS_IRI,
        "digest": expression_corpus_digest,
    }
    records: list[Mapping[str, Any]] = []
    for seed in seeds:
        expression_id = indexed_expression_id(
            reference_resource_release=release_reference,
            registry_import_snapshot=import_reference,
            distribution_artifact=distribution_reference,
            scheme_iri=SCHEME_IRI,
            member_iri=seed.member_iri,
            source_property_or_path=seed.source_path,
            original_literal=seed.original_literal,
            language_tag=seed.language_tag,
            datatype_iri=seed.datatype_iri,
        )
        indexed_text = normalize_unicode_text(seed.original_literal)
        record = IndexedVocabularyExpression(
            expression_id=expression_id,
            recorded_at=recorded_at,
            recorded_by=recorded_by,
            operational_state="developmentOnly",
            reference_resource_release=release_reference,
            registry_import_snapshot=import_reference,
            distribution_artifact=distribution_reference,
            scheme_iri=SCHEME_IRI,
            member_iri=seed.member_iri,
            source_property_or_path=seed.source_path,
            original_literal=seed.original_literal,
            language_tag=seed.language_tag,
            datatype_iri=seed.datatype_iri,
            normalization_policy=_NORMALIZATION_POLICY,
            indexed_text=indexed_text,
            indexed_text_digest=canonical_text_digest(indexed_text),
            indexed_representation_version="unicode-nfkc-casefold-whitespace-v1",
            expression_corpus_snapshot=corpus_reference,
            activity=ACTIVITY_IRI,
            receipt=RECEIPT_IRI,
        )
        records.append(record.sealed_payload())
    return tuple(records)


def _build_normalized_rows(
    *,
    parsed: FederalRegisterThesaurus,
    concept_iris: Mapping[str, str],
    expressions: Sequence[Mapping[str, Any]],
    import_snapshot_digest: str,
) -> tuple[tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    expression_by_source_path = {str(item["sourcePath"]): str(item["id"]) for item in expressions}
    label_rows: list[Mapping[str, Any]] = []
    for label in parsed.labels:
        property_iri = PREFERRED_LABEL_PROPERTY_IRI if label.role == "preferred" else ALTERNATE_LABEL_PROPERTY_IRI
        source_path = _source_path(
            locator=label.locator,
            property_iri=property_iri,
            source_record_id=label.label_id,
            source_entry_id=label.source_entry_id,
        )
        label_rows.append(
            {
                "label_id": label.label_id,
                "concept_iri": concept_iris[label.concept_id],
                "scheme_iri": SCHEME_IRI,
                "release_iri": RELEASE_IRI,
                "import_snapshot_id": IMPORT_SNAPSHOT_IRI,
                "import_snapshot_digest": import_snapshot_digest,
                "distribution_artifact_id": DISTRIBUTION_IRI,
                "source_property_iri": property_iri,
                "source_path": source_path,
                "label_role": label.role,
                "original_literal": label.literal,
                "language_tag": label.language_tag,
                "status": "current",
                "expression_id": expression_by_source_path[source_path],
                "source_locator": _locator_payload(label.locator),
                "migration_only": False,
            }
        )

    relation_rows: list[Mapping[str, Any]] = []
    for relation in parsed.relations:
        if (
            relation.resolution_status != "resolved"
            or relation.source_concept_id is None
            or relation.target_concept_id is None
        ):
            continue
        relation_rows.append(
            {
                "relation_id": relation.relation_id,
                "release_iri": RELEASE_IRI,
                "import_snapshot_id": IMPORT_SNAPSHOT_IRI,
                "import_snapshot_digest": import_snapshot_digest,
                "distribution_artifact_id": DISTRIBUTION_IRI,
                "subject_concept_iri": concept_iris[relation.source_concept_id],
                "subject_scheme_iri": SCHEME_IRI,
                "predicate_iri": relation.predicate_iri,
                "object_concept_iri": concept_iris[relation.target_concept_id],
                "object_scheme_iri": SCHEME_IRI,
                "source_property_or_path": _source_path(
                    locator=relation.locator,
                    property_iri=relation.predicate_iri,
                    source_record_id=relation.relation_id,
                    source_entry_id=relation.source_entry_id,
                ),
                "source_locator": _locator_payload(relation.locator),
                "migration_only": False,
            }
        )
    return tuple(label_rows), tuple(relation_rows)


def _coverage_exception(
    item_id: str,
    *,
    reference_kind: str,
    raw_target_label: str,
    reason: str,
    locator: SourceLocator,
) -> CoverageException:
    return CoverageException(
        item_id=item_id,
        stage="parsing",
        count=1,
        policy=_EXCLUSION_POLICY,
        rationale=(
            f"Excluded unresolved {reference_kind} target "
            f"{raw_target_label!r} at source line {locator.start_line}, "
            f"end line {locator.end_line}, ordinal {locator.ordinal}: {reason}"
        ),
    )


def _feature_row(
    *,
    feature: str,
    source_items: Sequence[object],
    parsed_items: Sequence[object],
    indexed_items: Sequence[object],
    exclusions: Sequence[CoverageException] = (),
    required: bool,
) -> ImportFeatureCoverage:
    source_digest = _digest_json(source_items)
    parsed_digest = _digest_json(parsed_items)
    indexed_digest = _digest_json(indexed_items)
    parse_differs = len(source_items) != len(parsed_items) or source_digest != parsed_digest
    index_differs = len(parsed_items) != len(indexed_items) or parsed_digest != indexed_digest
    return ImportFeatureCoverage(
        feature=feature,
        source_observed_count=len(source_items),
        parsed_count=len(parsed_items),
        indexed_count=len(indexed_items),
        explicitly_excluded_count=sum(item.count for item in exclusions),
        failed_count=0,
        source_observed_digest=source_digest,
        parsed_digest=parsed_digest,
        indexed_digest=indexed_digest,
        exclusions=tuple(exclusions),
        failures=(),
        required_for_candidate_or_output=required,
        parse_difference_explanation=(
            "Source items with unresolved preferred identities or relation targets are itemized parsing exclusions."
            if parse_differs
            else None
        ),
        index_difference_explanation=(
            "Only member-bound parsed expressions enter the logical expression corpus." if index_differs else None
        ),
    )


def _build_coverage_report(
    *,
    parsed: FederalRegisterThesaurus,
    normalized_labels: Sequence[Mapping[str, Any]],
    normalized_relations: Sequence[Mapping[str, Any]],
    expression_seeds: Sequence[_ExpressionSeed],
    recorded_at: str,
    recorded_by: str,
    release_digest: str,
    import_snapshot_digest: str,
    expression_corpus_digest: str,
    output_profile_reference: Mapping[str, str],
) -> Mapping[str, Any]:
    exclusion_by_unresolved_id: dict[str, CoverageException] = {}
    label_exclusions: list[CoverageException] = []
    hierarchy_exclusions: list[CoverageException] = []
    associative_exclusions: list[CoverageException] = []
    for unresolved in parsed.unresolved_references:
        item_id = f"urn:ref:fr-thesaurus-1995:coverage:{unresolved.unresolved_id}"
        item = _coverage_exception(
            item_id,
            reference_kind=unresolved.reference_kind,
            raw_target_label=unresolved.raw_target_label,
            reason=unresolved.reason,
            locator=unresolved.locator,
        )
        exclusion_by_unresolved_id[unresolved.unresolved_id] = item
        if unresolved.reference_kind == "see":
            label_exclusions.append(item)
        elif unresolved.reference_kind == "broader":
            hierarchy_exclusions.append(item)
        elif unresolved.reference_kind == "related":
            associative_exclusions.append(item)
        else:
            raise VerticalSliceError(f"unsupported unresolved reference kind {unresolved.reference_kind!r}")

    unbound_notes = [item for item in parsed.scope_notes if item.concept_id is None]
    note_exclusions: list[CoverageException] = []
    for note in unbound_notes:
        candidates = [
            unresolved
            for unresolved in parsed.unresolved_references
            if unresolved.source_entry_id == note.source_entry_id and unresolved.reference_kind == "see"
        ]
        if len(candidates) != 1:
            raise VerticalSliceError(f"unbound note {note.note_id} does not have one unresolved see exclusion")
        reused = exclusion_by_unresolved_id[candidates[0].unresolved_id]
        note_exclusions.append(
            CoverageException(
                item_id=reused.item_id,
                stage=reused.stage,
                count=reused.count,
                policy=reused.policy,
                rationale=(
                    f"{reused.rationale}; the scope note at source line "
                    f"{note.locator.start_line}, end line {note.locator.end_line}, "
                    f"ordinal {note.locator.ordinal} remains unbound rather than "
                    "being attached to a guessed concept."
                ),
            )
        )

    label_source_items = [
        {
            "sourceRecordId": item.label_id,
            "literal": item.literal,
            "role": item.role,
            "locator": _locator_payload(item.locator),
        }
        for item in parsed.labels
    ] + [
        {
            "sourceRecordId": item.unresolved_id,
            "literal": next(entry.label for entry in parsed.entries if entry.entry_id == item.source_entry_id),
            "role": "alternate",
            "unresolvedTarget": item.raw_target_label,
            "locator": _locator_payload(item.locator),
        }
        for item in parsed.unresolved_references
        if item.reference_kind == "see"
    ]
    label_parsed_items = [
        {
            "sourceRecordId": item["label_id"],
            "concept": item["concept_iri"],
            "literal": item["original_literal"],
            "role": item["label_role"],
            "locator": item["source_locator"],
        }
        for item in normalized_labels
    ]

    bound_notes = [item for item in parsed.scope_notes if item.concept_id is not None]
    note_source_items = [
        {
            "sourceRecordId": item.note_id,
            "text": item.text,
            "locator": _locator_payload(item.locator),
        }
        for item in parsed.scope_notes
    ]
    note_parsed_items = [
        {
            "sourceRecordId": item.note_id,
            "text": item.text,
            "locator": _locator_payload(item.locator),
        }
        for item in bound_notes
    ]

    notation_items = [
        {
            "sourceRecordId": item.notation_id,
            "literal": item.raw_literal,
            "datatype": item.datatype_iri,
            "locator": _locator_payload(item.locator),
        }
        for item in parsed.category_notations
        if item.concept_id is not None
    ]
    broader_source_items = [
        {
            "sourceRecordId": item.relation_id,
            "predicate": item.predicate_iri,
            "target": item.raw_target_label,
            "locator": _locator_payload(item.locator),
        }
        for item in parsed.relations
        if item.predicate_iri == BROADER_PREDICATE_IRI
    ]
    broader_parsed_items = [
        {
            "sourceRecordId": item["relation_id"],
            "predicate": item["predicate_iri"],
            "subject": item["subject_concept_iri"],
            "object": item["object_concept_iri"],
            "locator": item["source_locator"],
        }
        for item in normalized_relations
        if item["predicate_iri"] == BROADER_PREDICATE_IRI
    ]
    associative_source_items = [
        {
            "sourceRecordId": item.relation_id,
            "predicate": item.predicate_iri,
            "target": item.raw_target_label,
            "locator": _locator_payload(item.locator),
        }
        for item in parsed.relations
        if item.predicate_iri == ASSOCIATIVE_PREDICATE_IRI
    ]
    associative_parsed_items = [
        {
            "sourceRecordId": item["relation_id"],
            "predicate": item["predicate_iri"],
            "subject": item["subject_concept_iri"],
            "object": item["object_concept_iri"],
            "locator": item["source_locator"],
        }
        for item in normalized_relations
        if item["predicate_iri"] == ASSOCIATIVE_PREDICATE_IRI
    ]
    language_items = [item.corpus_identity() for item in expression_seeds if item.language_tag is not None]
    identifier_items = [
        {
            "sourceConceptId": item.concept_id,
            "member": _concept_iri(item.concept_id),
        }
        for item in parsed.concepts
    ]
    empty: list[object] = []

    rows_by_name = {
        "labels": _feature_row(
            feature="labels",
            source_items=label_source_items,
            parsed_items=label_parsed_items,
            indexed_items=label_parsed_items,
            exclusions=label_exclusions,
            required=True,
        ),
        "languages": _feature_row(
            feature="languages",
            source_items=language_items,
            parsed_items=language_items,
            indexed_items=language_items,
            required=True,
        ),
        "notation": _feature_row(
            feature="notation",
            source_items=notation_items,
            parsed_items=notation_items,
            indexed_items=notation_items,
            required=True,
        ),
        "notes": _feature_row(
            feature="notes",
            source_items=note_source_items,
            parsed_items=note_parsed_items,
            indexed_items=note_parsed_items,
            exclusions=note_exclusions,
            required=True,
        ),
        "hierarchy": _feature_row(
            feature="hierarchy",
            source_items=broader_source_items,
            parsed_items=broader_parsed_items,
            indexed_items=broader_parsed_items,
            exclusions=hierarchy_exclusions,
            required=True,
        ),
        "associativeRelations": _feature_row(
            feature="associativeRelations",
            source_items=associative_source_items,
            parsed_items=associative_parsed_items,
            indexed_items=associative_parsed_items,
            exclusions=associative_exclusions,
            required=True,
        ),
        "mappings": _feature_row(
            feature="mappings",
            source_items=empty,
            parsed_items=empty,
            indexed_items=empty,
            required=True,
        ),
        "status": _feature_row(
            feature="status",
            source_items=empty,
            parsed_items=empty,
            indexed_items=empty,
            required=True,
        ),
        "replacements": _feature_row(
            feature="replacements",
            source_items=empty,
            parsed_items=empty,
            indexed_items=empty,
            required=True,
        ),
        "identifiers": _feature_row(
            feature="identifiers",
            source_items=identifier_items,
            parsed_items=identifier_items,
            indexed_items=identifier_items,
            required=True,
        ),
        "membership": _feature_row(
            feature="membership",
            source_items=identifier_items,
            parsed_items=identifier_items,
            indexed_items=identifier_items,
            required=True,
        ),
    }
    report = RegistryImportCoverageReport(
        report_id="urn:ref:fr-thesaurus-1995:coverage-report:v1",
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        operational_state="developmentOnly",
        output_profile=output_profile_reference,
        import_snapshot={
            "id": IMPORT_SNAPSHOT_IRI,
            "digest": import_snapshot_digest,
        },
        reference_resource_release={
            "id": RELEASE_IRI,
            "version": RELEASE_VERSION,
            "digest": release_digest,
        },
        distribution_artifacts=(
            {
                "id": DISTRIBUTION_IRI,
                "digest": parsed.source_sha256,
            },
        ),
        import_profile=_IMPORT_PROFILE,
        parser_version=PARSER_VERSION,
        expression_corpus_snapshot={
            "id": EXPRESSION_CORPUS_IRI,
            "digest": expression_corpus_digest,
        },
        activity=ACTIVITY_IRI,
        receipt=RECEIPT_IRI,
        feature_rows=tuple(rows_by_name[name] for name in _FEATURE_ORDER),
        report_status="pass",
    )
    return report.sealed_payload()


def _build_registry_deployment_decision(
    *,
    decision_id: str,
    selection_state: str,
    effective_at: str,
    recorded_by: str,
    import_record: Mapping[str, Any],
    release_reference: Mapping[str, str],
    coverage_record: Mapping[str, Any],
    output_profile_record: Mapping[str, Any],
    reason: str,
    predecessor: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    """Build one exact local decision without caller-authored gate verdicts."""

    decision = RegistryDeploymentDecision(
        decision_id=decision_id,
        recorded_at=effective_at,
        recorded_by=recorded_by,
        operational_state="developmentOnly",
        environment={
            "id": DEVELOPMENT_ENVIRONMENT_IRI,
            "classification": "development",
        },
        registry_import_snapshot=_digest_reference(import_record),
        reference_resource_release=release_reference,
        coverage_report=_digest_reference(coverage_record),
        output_profile=_versioned_reference(output_profile_record),
        selection_state=selection_state,
        effective_at=effective_at,
        reason=reason,
        activity=ACTIVITY_IRI,
        rulespec_attestation_refs=(SELECTION_ATTESTATION_IRI,),
        local_adoption_refs=(SELECTION_ADOPTION_IRI,),
        predecessor=predecessor,
    )
    return decision.sealed_payload(
        coverage_report_record=coverage_record,
        output_profile_record=output_profile_record,
    )


def _build_run_receipt(
    *,
    parsed: FederalRegisterThesaurus,
    capture_record: Mapping[str, Any],
    import_record: Mapping[str, Any],
    coverage_record: Mapping[str, Any],
    release_reference: Mapping[str, str],
    graph_digest: str,
    expression_corpus_digest: str,
    expression_count: int,
    exclusions: Sequence[Mapping[str, Any]],
    recorded_at: str,
    recorded_by: str,
    selected_deployment: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    broader_source = sum(relation.predicate_iri == BROADER_PREDICATE_IRI for relation in parsed.relations)
    broader_resolved = sum(
        relation.predicate_iri == BROADER_PREDICATE_IRI and relation.resolution_status == "resolved"
        for relation in parsed.relations
    )
    associative_source = sum(relation.predicate_iri == ASSOCIATIVE_PREDICATE_IRI for relation in parsed.relations)
    associative_resolved = sum(
        relation.predicate_iri == ASSOCIATIVE_PREDICATE_IRI and relation.resolution_status == "resolved"
        for relation in parsed.relations
    )
    counts = asdict(parsed.counts)
    counts.update(
        {
            "indexedExpressions": expression_count,
            "broaderRelationsSource": broader_source,
            "broaderRelationsParsed": broader_resolved,
            "broaderRelationsExcluded": broader_source - broader_resolved,
            "associativeRelationsSource": associative_source,
            "associativeRelationsParsed": associative_resolved,
            "associativeRelationsExcluded": (associative_source - associative_resolved),
            "officialSourceInputs": 1,
            "reconciliationReports": 0,
            "deploymentSelections": (
                1 if selected_deployment is not None else 0
            ),
        }
    )
    outputs = [
        _digest_reference(import_record),
        _digest_reference(coverage_record),
        {"id": GRAPH_IRI, "digest": graph_digest},
        {
            "id": EXPRESSION_CORPUS_IRI,
            "digest": expression_corpus_digest,
        },
    ]
    if selected_deployment is not None:
        outputs.append(_digest_reference(selected_deployment))
    return seal_payload(
        {
            **_record_base(
                record_id=RECEIPT_IRI,
                record_type="urn:ref:type:RunReceipt",
                recorded_at=recorded_at,
                recorded_by=recorded_by,
                operational_state="completeDevelopmentRun",
            ),
            "inputCaptures": [_digest_reference(capture_record)],
            "inputSnapshots": [],
            "rulespecReleases": [dict(release_reference)],
            "coverageWindow": {
                "startedAt": recorded_at,
                "endedAt": recorded_at,
            },
            "rulespecActivityRefs": [ACTIVITY_IRI],
            "rulespecAgentRefs": [recorded_by],
            "rulespecOutputRefs": [RELEASE_IRI, GRAPH_IRI],
            "environmentLock": {
                "id": "urn:ref:environment-lock:fr-thesaurus-vertical-slice:v1",
                "digest": _digest_json(
                    {
                        "parserVersion": PARSER_VERSION,
                        "sliceVersion": SLICE_VERSION,
                        "sourceDigest": parsed.source_sha256,
                    }
                ),
            },
            "outputs": outputs,
            "counts": counts,
            "exclusions": [dict(item) for item in exclusions],
            "failures": [],
            "quarantinedItems": [],
            "startedAt": recorded_at,
            "endedAt": recorded_at,
            "nondeterministicStages": [],
            "reproducibility": "byteIdentical",
        }
    )


def _binding_profile_digest() -> str:
    artifacts = [
        {
            "path": path.name,
            "sha256": _sha256_bytes(path.read_bytes()),
        }
        for path in sorted(binding.SCHEMA_ROOT.glob("*.schema.json"))
    ]
    if not artifacts:
        raise VerticalSliceError("REF JSON Binding schema set is empty")
    return _digest_json(artifacts)


def _rulespec_dependency(
    *,
    validator: RulespecValidatorPin,
    conformance_result_digest: str,
) -> Mapping[str, Any]:
    manifest_path = binding.REFSPEC_ROOT / "profiles" / "rulespec-dependency.json"
    manifest = binding.load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise VerticalSliceError("Rulespec dependency manifest is not an object")
    return {
        "version": str(manifest["rulespecVersion"]),
        "contractRevision": str(manifest["contractRevision"]),
        "evidenceRevision": str(manifest["evidenceRevision"]),
        "constraintDigest": str(manifest["constraintDigest"]),
        "conformanceCorpusDigest": str(manifest["conformanceCorpusDigest"]),
        "adoptedProfiles": ["urn:rulespec:profile:refspec"],
        "validator": {
            "id": validator.component_id,
            "revision": validator.source_revision,
            "digest": validator.component_digest,
        },
        "conformanceResult": {
            "id": CONFORMANCE_RESULT_IRI,
            "digest": conformance_result_digest,
        },
        "releaseAvailability": str(manifest["releaseAvailability"]),
    }


def _build_publication_manifest(
    *,
    operational_records: Sequence[Mapping[str, Any]],
    run_receipt: Mapping[str, Any],
    coverage_record: Mapping[str, Any],
    graph_digest: str,
    expression_corpus_digest: str,
    validator: RulespecValidatorPin,
    conformance_result_digest: str,
    recorded_at: str,
    recorded_by: str,
    selected_deployment: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    selected = selected_deployment is not None
    conformance_levels = [
        "REF JSON Binding 1.0",
        "Rulespec pinned local validation",
    ]
    conformance_levels.append(
        "Development candidate bundle with gate-evaluated local selection"
        if selected
        else "Pre-selection candidate bundle"
    )
    return seal_payload(
        {
            **_record_base(
                record_id=PUBLICATION_IRI,
                record_type="urn:ref:type:PublicationReleaseManifest",
                recorded_at=recorded_at,
                recorded_by=recorded_by,
            ),
            "version": "1.0.0-development",
            "refspecVersion": "0.1.0.dev0",
            "operationalSerializationProfile": {
                "id": "https://refspec.org/bindings/json/1.0",
                "version": "1.0",
                "digest": _binding_profile_digest(),
            },
            "rulespecDependency": _rulespec_dependency(
                validator=validator,
                conformance_result_digest=conformance_result_digest,
            ),
            "claimedConformanceLevels": conformance_levels,
            "inventoryCoveragePins": [_digest_reference(coverage_record)],
            "rulespecReleaseGraph": {
                "id": GRAPH_IRI,
                "digest": graph_digest,
            },
            "refOperationalRecords": [_digest_reference(record) for record in operational_records],
            "expressionCorpusSnapshot": {
                "id": EXPRESSION_CORPUS_IRI,
                "digest": expression_corpus_digest,
            },
            "runReceipt": _digest_reference(run_receipt),
            "releaseState": "complete" if selected else "incomplete",
            "deploymentClass": "developmentOnly",
            "consumerEligible": selected,
            "publishedAt": recorded_at,
            "activity": ACTIVITY_IRI,
        }
    )


def _release_graph_gate_bundle(
    *,
    graph: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    validator: RulespecValidatorPin,
) -> Mapping[str, Any]:
    graph_digest = rulespec_graph_digest(graph)
    graph_identifiers = defined_rulespec_identifiers(graph)
    cross_references = sorted(
        (
            {
                "refRecordId": str(record["id"]),
                "rulespecIdentifier": rulespec_identifier,
            }
            for record in records
            for rulespec_identifier in referenced_rulespec_identifiers(
                record,
                graph_identifiers,
            )
        ),
        key=lambda item: (item["refRecordId"], item["rulespecIdentifier"]),
    )
    return {
        "bundleVersion": "1.0",
        "refRecords": [dict(record) for record in records],
        "rulespecGraph": dict(graph),
        "rulespecGraphId": GRAPH_IRI,
        "rulespecGraphDigest": graph_digest,
        "graphDigestAlgorithm": GRAPH_DIGEST_ALGORITHM,
        "validatorReceipt": {
            "result": "pass",
            "validatorIdentity": validator.identity,
            "validatorSourceRevision": validator.source_revision,
            "graphId": GRAPH_IRI,
            "graphDigest": graph_digest,
            "coveredIdentifiers": sorted(graph_identifiers),
        },
        "crossReferences": cross_references,
    }


def build_federal_register_vertical_slice(
    parsed: FederalRegisterThesaurus,
    *,
    rulespec_root: Path,
    recorded_at: str,
    recorded_by: str,
    governance: LocalCandidateGovernance | None = None,
) -> VerticalSliceBundle:
    """Build and validate one deterministic candidate-only managed release."""

    try:
        validator = load_pinned_rulespec_validator(rulespec_root)
    except (OSError, TypeError, ValueError) as error:
        raise VerticalSliceError(f"cannot load the pinned Rulespec validator: {error}") from error
    concept_iris = {concept.concept_id: _concept_iri(concept.concept_id) for concept in parsed.concepts}
    rulespec_graph, release_digest = _build_rulespec_graph(
        parsed,
        concept_iris,
        validator,
        governance,
    )
    graph_digest = rulespec_graph_digest(rulespec_graph)
    conformance_result = next(
        (node for node in rulespec_graph["@graph"] if node.get("@id") == CONFORMANCE_RESULT_IRI),
        None,
    )
    if not isinstance(conformance_result, dict) or not isinstance(
        conformance_result.get("rkaf:hasContentDigest"),
        str,
    ):
        raise VerticalSliceError("Rulespec graph lacks its validation-result artifact")
    conformance_result_digest = str(conformance_result["rkaf:hasContentDigest"])
    release_reference = {
        "id": RELEASE_IRI,
        "version": RELEASE_VERSION,
        "digest": release_digest,
    }
    expression_seeds = _build_expression_seeds(parsed, concept_iris)
    expression_corpus_digest = _digest_json([item.corpus_identity() for item in expression_seeds])
    projection_digest = _import_snapshot_digest(parsed, expression_seeds)
    source_exclusions = _source_exclusions(parsed)
    rights_record = _build_rights_assessment(
        parsed=parsed,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
    )
    capture_record = _build_capture(
        parsed=parsed,
        rights_record=rights_record,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
    )
    import_record = _build_import_snapshot(
        parsed=parsed,
        capture_record=capture_record,
        rights_record=rights_record,
        release_reference=release_reference,
        projection_digest=projection_digest,
        conformance_result_digest=conformance_result_digest,
        exclusions=source_exclusions,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
    )
    import_reference = _digest_reference(import_record)
    import_snapshot_digest = str(import_reference["digest"])
    (
        _enrichment_profile,
        enrichment_profile_record,
        _output_profile,
        output_profile_record,
    ) = _build_profiles(
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        release_reference=release_reference,
        import_reference=import_reference,
    )
    expressions = _build_expressions(
        seeds=expression_seeds,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        release_digest=release_digest,
        import_snapshot_digest=import_snapshot_digest,
        expression_corpus_digest=expression_corpus_digest,
        source_digest=parsed.source_sha256,
    )
    normalized_labels, normalized_relations = _build_normalized_rows(
        parsed=parsed,
        concept_iris=concept_iris,
        expressions=expressions,
        import_snapshot_digest=import_snapshot_digest,
    )
    coverage_record = _build_coverage_report(
        parsed=parsed,
        normalized_labels=normalized_labels,
        normalized_relations=normalized_relations,
        expression_seeds=expression_seeds,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        release_digest=release_digest,
        import_snapshot_digest=import_snapshot_digest,
        expression_corpus_digest=expression_corpus_digest,
        output_profile_reference=_versioned_reference(output_profile_record),
    )
    selected_deployment: Mapping[str, Any] | None = None
    if governance is not None:
        selected_deployment = _build_registry_deployment_decision(
            decision_id=SELECTED_DEPLOYMENT_IRI,
            selection_state="selected",
            effective_at=governance.effective_at,
            recorded_by=recorded_by,
            import_record=import_record,
            release_reference=release_reference,
            coverage_record=coverage_record,
            output_profile_record=output_profile_record,
            reason=(
                "Selected only for candidate lookup in the Spicy Regs "
                "experimental development environment after passing lossless "
                "import coverage and project-local Rulespec review. This "
                "decision grants no accepted-output, publisher, legal-"
                "clearance, or production authority."
            ),
        )
    run_receipt = _build_run_receipt(
        parsed=parsed,
        capture_record=capture_record,
        import_record=import_record,
        coverage_record=coverage_record,
        release_reference=release_reference,
        graph_digest=graph_digest,
        expression_corpus_digest=expression_corpus_digest,
        expression_count=len(expressions),
        exclusions=source_exclusions,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        selected_deployment=selected_deployment,
    )
    operational_records = (
        enrichment_profile_record,
        output_profile_record,
        rights_record,
        capture_record,
        import_record,
        coverage_record,
        *((selected_deployment,) if selected_deployment is not None else ()),
        run_receipt,
    )
    publication_record = _build_publication_manifest(
        operational_records=operational_records,
        run_receipt=run_receipt,
        coverage_record=coverage_record,
        graph_digest=graph_digest,
        expression_corpus_digest=expression_corpus_digest,
        validator=validator,
        conformance_result_digest=conformance_result_digest,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        selected_deployment=selected_deployment,
    )
    gate_bundle = _release_graph_gate_bundle(
        graph=rulespec_graph,
        records=(publication_record, *operational_records, *expressions),
        validator=validator,
    )
    try:
        combined_receipt = issue_release_graph_validation_receipt(
            gate_bundle,
            validator=validator,
            receipt_id=("urn:ref:fr-thesaurus-1995:release-graph-validation-receipt:v1"),
            recorded_at=recorded_at,
            recorded_by=recorded_by,
            activity=ACTIVITY_IRI,
        )
    except (OSError, TypeError, ValueError) as error:
        stage = (
            "selected development candidate bundle"
            if selected_deployment is not None
            else "pre-selection candidate bundle"
        )
        raise VerticalSliceError(
            f"combined RefSpec/Rulespec gate rejected the {stage}: {error}"
        ) from error
    dependency_manifest_bytes = rulespec_dependency_bytes()
    return VerticalSliceBundle(
        rulespec_graph=rulespec_graph,
        normalized_labels=normalized_labels,
        normalized_relations=normalized_relations,
        indexed_expressions=expressions,
        coverage_report=coverage_record,
        operational_records=operational_records,
        publication_release_manifest=publication_record,
        combined_validation_receipt=combined_receipt,
        rulespec_dependency_manifest_bytes=dependency_manifest_bytes,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        source_sha256=parsed.source_sha256,
        source_lines=parsed.source_lines,
        source_bytes=parsed.source_bytes,
        expression_corpus_digest=expression_corpus_digest,
    )


def _later_timestamp(value: str) -> str:
    parsed = _decision_time(value)
    return (
        (parsed + dt.timedelta(seconds=1))
        .astimezone(dt.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def build_registry_selection_rollback_proof(
    bundle: VerticalSliceBundle,
    *,
    rulespec_root: Path,
    rollback_at: str | None = None,
) -> RollbackProofBundle:
    """Prove that an append-only rollback restores the explicit empty state.

    The returned artifacts are intentionally separate from ``bundle``.  They
    can document a later rollback without rewriting or weakening the active
    managed-release manifest that originally selected the source.
    """

    records_by_type = {
        str(record.get("type")): record
        for record in bundle.operational_records
    }
    selected = next(
        (
            record
            for record in bundle.operational_records
            if record.get("type")
            == "urn:ref:type:RegistryDeploymentDecision"
            and record.get("id") == SELECTED_DEPLOYMENT_IRI
            and record.get("selectionState") == "selected"
        ),
        None,
    )
    if selected is None:
        raise VerticalSliceError(
            "rollback proof requires an active bundle with one selected "
            "development deployment"
        )
    coverage = records_by_type.get(
        "urn:ref:type:RegistryImportCoverageReport"
    )
    output_profile = records_by_type.get("urn:ref:type:OutputProfile")
    enrichment_profile = records_by_type.get(
        "urn:ref:type:EnrichmentProfile"
    )
    import_record = records_by_type.get(
        "urn:ref:type:RegistryImportSnapshot"
    )
    if any(
        record is None
        for record in (
            coverage,
            output_profile,
            enrichment_profile,
            import_record,
        )
    ):
        raise VerticalSliceError(
            "selected bundle lacks records required for rollback proof"
        )
    assert coverage is not None
    assert output_profile is not None
    assert enrichment_profile is not None
    assert import_record is not None

    effective_at = rollback_at or _later_timestamp(
        str(selected["effectiveAt"])
    )
    if _decision_time(effective_at) <= _decision_time(
        selected.get("effectiveAt")
    ):
        raise VerticalSliceError(
            "rollback_at must be later than the selected decision"
        )
    rollback = _build_registry_deployment_decision(
        decision_id=ROLLBACK_DEPLOYMENT_IRI,
        selection_state="deselected",
        effective_at=effective_at,
        recorded_by=bundle.recorded_by,
        import_record=import_record,
        release_reference=dict(selected["referenceResourceRelease"]),
        coverage_record=coverage,
        output_profile_record=output_profile,
        reason=(
            "Rolled back the project-local candidate-use selection to the "
            "explicit prior empty state. No replacement release is inferred "
            "or invented."
        ),
        predecessor=_digest_reference(selected),
    )
    reduction = reduce_registry_selection_history([selected, rollback])
    if (
        reduction.final_state != reduction.initial_state
        or reduction.state_digests[0] != reduction.state_digests[-1]
    ):
        raise VerticalSliceError(
            "registry selection reducer did not restore the prior empty state"
        )
    reduction_receipt = seal_payload(
        {
            **_record_base(
                record_id=ROLLBACK_RECEIPT_IRI,
                record_type="urn:ref:type:RunReceipt",
                recorded_at=effective_at,
                recorded_by=bundle.recorded_by,
                operational_state="completeDevelopmentRun",
            ),
            "inputCaptures": [],
            "inputSnapshots": [
                _digest_reference(selected),
                _digest_reference(rollback),
            ],
            "rulespecReleases": [
                dict(selected["referenceResourceRelease"])
            ],
            "coverageWindow": {
                "startedAt": str(selected["effectiveAt"]),
                "endedAt": effective_at,
            },
            "rulespecActivityRefs": [ACTIVITY_IRI],
            "rulespecAgentRefs": [bundle.recorded_by],
            "rulespecOutputRefs": [RELEASE_IRI],
            "environmentLock": {
                "id": (
                    "urn:ref:environment-lock:"
                    "fr-thesaurus-selection-reducer:v1"
                ),
                "digest": _digest_json(
                    {
                        "reducerVersion": (
                            REGISTRY_SELECTION_REDUCER_VERSION
                        ),
                        "environment": DEVELOPMENT_ENVIRONMENT_IRI,
                        "initialSelectionStateDigest": (
                            reduction.initial_state.digest()
                        ),
                    }
                ),
            },
            "outputs": [
                {
                    "id": ROLLBACK_FINAL_STATE_IRI,
                    "digest": reduction.final_state.digest(),
                }
            ],
            "counts": {
                "historyEvents": 2,
                "selectionEvents": 1,
                "rollbackEvents": 1,
                "restoredEmptyStates": 1,
                "failedEvents": 0,
            },
            "exclusions": [],
            "failures": [],
            "quarantinedItems": [],
            "startedAt": str(selected["effectiveAt"]),
            "endedAt": effective_at,
            "nondeterministicStages": [],
            "reproducibility": "byteIdentical",
        }
    )

    try:
        validator = load_pinned_rulespec_validator(rulespec_root)
        gate_bundle = _release_graph_gate_bundle(
            graph=bundle.rulespec_graph,
            records=(
                enrichment_profile,
                output_profile,
                coverage,
                selected,
                rollback,
                reduction_receipt,
            ),
            validator=validator,
        )
        combined_receipt = issue_release_graph_validation_receipt(
            gate_bundle,
            validator=validator,
            receipt_id=ROLLBACK_VALIDATION_RECEIPT_IRI,
            recorded_at=effective_at,
            recorded_by=bundle.recorded_by,
            activity=ACTIVITY_IRI,
        )
    except (OSError, TypeError, ValueError) as error:
        raise VerticalSliceError(
            "combined RefSpec/Rulespec gate rejected the append-only "
            f"rollback proof: {error}"
        ) from error

    return RollbackProofBundle(
        selected_decision=selected,
        rollback_decision=rollback,
        reduction_receipt=reduction_receipt,
        combined_validation_receipt=combined_receipt,
        reduction=reduction,
        active_publication=_digest_reference(
            bundle.publication_release_manifest
        ),
    )


def build_from_verified_source(
    source_path: Path,
    output_dir: Path,
    *,
    rulespec_root: Path,
    recorded_at: str,
    recorded_by: str,
    governance: LocalCandidateGovernance | None = None,
) -> VerticalSliceBundle:
    """Verify one exact local source, build the bundle, then write artifacts.

    This function never fetches network bytes. Use the separate explicit
    acquisition command when the pinned native source is not already present.
    """

    try:
        source = source_path.read_bytes()
    except OSError as error:
        raise VerticalSliceError(f"cannot read source file {source_path}: {error}") from error
    actual_digest = _sha256_bytes(source)
    if actual_digest != HISTORICAL_SOURCE_SHA256:
        raise VerticalSliceError(
            f"Federal Register thesaurus digest mismatch: expected {HISTORICAL_SOURCE_SHA256}, got {actual_digest}"
        )
    parsed = parse_federal_register_thesaurus(
        source,
        require_resolved=False,
    )
    bundle = build_federal_register_vertical_slice(
        parsed,
        rulespec_root=rulespec_root,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        governance=governance,
    )
    bundle.write_to(output_dir)
    return bundle


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Build the candidate-only Federal Register 1995 managed release from one exact local source file.")
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--rulespec-root", type=Path, required=True)
    parser.add_argument("--recorded-at", required=True)
    parser.add_argument("--recorded-by", required=True)
    parser.add_argument(
        "--select-for-candidate-use",
        action="store_true",
        help=("request an explicitly governed, development-only candidate selection"),
    )
    parser.add_argument("--governance-actor")
    parser.add_argument("--governance-organization")
    parser.add_argument(
        "--rollback-proof-output",
        type=Path,
        help=(
            "write a separate append-only rollback proof after a governed "
            "candidate selection"
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    governance: LocalCandidateGovernance | None = None
    if args.select_for_candidate_use:
        if not args.governance_actor or not args.governance_organization:
            parser.error("--select-for-candidate-use requires --governance-actor and --governance-organization")
        governance = LocalCandidateGovernance(
            actor_iri=args.governance_actor,
            organization_iri=args.governance_organization,
            effective_at=args.recorded_at,
        )
    elif args.governance_actor or args.governance_organization:
        parser.error("governance identifiers require --select-for-candidate-use")
    if (
        args.rollback_proof_output is not None
        and governance is None
    ):
        parser.error(
            "--rollback-proof-output requires "
            "--select-for-candidate-use"
        )
    if args.rollback_proof_output is not None:
        active_output = args.output.resolve()
        rollback_output = args.rollback_proof_output.resolve()
        if (
            active_output == rollback_output
            or active_output.is_relative_to(rollback_output)
            or rollback_output.is_relative_to(active_output)
        ):
            parser.error(
                "active output and rollback-proof output must be separate "
                "non-nested directories"
            )
    try:
        bundle = build_from_verified_source(
            args.source,
            args.output,
            rulespec_root=args.rulespec_root,
            recorded_at=args.recorded_at,
            recorded_by=args.recorded_by,
            governance=governance,
        )
        if args.rollback_proof_output is not None:
            build_registry_selection_rollback_proof(
                bundle,
                rulespec_root=args.rulespec_root,
            ).write_to(args.rollback_proof_output)
    except VerticalSliceError as error:
        parser.error(str(error))
    print(args.output / "managed-release-bundle.json")
    if args.rollback_proof_output is not None:
        print(
            args.rollback_proof_output
            / "rollback-history-bundle.json"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
