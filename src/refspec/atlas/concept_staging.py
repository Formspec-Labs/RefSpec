"""Sealed governance receipts for genuinely new RefSpec subject concepts.

Concept staging does not mint a concept or publish a managed release.  It
checks that vocabulary governance already produced both of those Rulespec
facts, then binds them to one exact, accepted ``ConceptProposal`` and the full
promotion checklist from REF-GOV-002.  The authorizing decision remains an
``rkaf:Attestation`` by a concept-minting authority in the exact managed
release graph; this receipt is operational evidence, not a second approval.

Existing source identities take the separate subject-admission path.  When a
new local concept consolidates or refines source meanings, every cited source
identity stays pinned to its own exact release and the authored identifier
must differ from all of them.
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
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue

from .concept_release import (
    ConceptReleaseError,
    PinnedManagedConceptRelease,
    SubjectConceptRelease,
    concept_release_pin,
    normalize_concept_release_pin,
    require_admissible_subject_concept,
    require_subject_concept_release,
)

CONCEPT_AUTHORING_TRANSITION_TYPE = "ConceptAuthoringTransition"
CONCEPT_AUTHORING_TRANSITION_VERSION = "1.0"

AuthoringKind = Literal["newMeaning", "consolidation", "splitRefinement"]

_AUTHORING_KINDS = frozenset({"newMeaning", "consolidation", "splitRefinement"})
_PLACEMENT_RELATIONS = frozenset({"narrowerThan", "broaderThan", "relatedTo"})
_GRAPH_PLACEMENT_PROPERTIES: Mapping[str, str] = {
    "narrowerThan": "skos:broader",
    "broaderThan": "skos:narrower",
    "relatedTo": "skos:related",
}
_LOCAL_CONCEPT_TYPES = frozenset(
    {"rkaf:LocalConcept", "https://rulespec.org/ns/v1#LocalConcept"}
)
_ATTESTATION_TYPES = frozenset(
    {"rkaf:Attestation", "https://rulespec.org/ns/v1#Attestation"}
)
_CONCEPT_MINTING_AUTHORITY_KINDS = frozenset(
    {
        "rkaf:conceptMintingAuthority",
        "https://rulespec.org/ns/v1#conceptMintingAuthority",
    }
)
_APPROVING_DECISIONS = frozenset(
    {
        "rkaf:approved",
        "rkaf:approvedWithConditions",
        "https://rulespec.org/ns/v1#approved",
        "https://rulespec.org/ns/v1#approvedWithConditions",
    }
)
_CONDITIONAL_DECISIONS = frozenset(
    {
        "rkaf:approvedWithConditions",
        "https://rulespec.org/ns/v1#approvedWithConditions",
    }
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")

_REFERENCE_FIELDS = frozenset({"id", "digest"})
_POLICY_FIELDS = frozenset({"id", "version", "contentDigest"})
_SOURCE_FIELDS = frozenset({"conceptId", "conceptRelease"})
_ATTESTATION_FIELDS = frozenset({"id"})
_CHECKLIST_FIELDS = frozenset(
    {
        "definition",
        "inclusionCues",
        "exclusionCues",
        "preferredLabels",
        "alternateLabels",
        "placement",
        "duplicateAndMappingAnalysis",
        "representativeEvidence",
        "evidencePolicy",
        "expectedAssignmentEffect",
        "rightsAssessment",
        "governancePolicy",
    }
)
_BASIS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "proposal",
        "authoringKind",
        "sourceConcepts",
        "checklist",
        "authoredConcept",
        "authoredConceptRelease",
        "authoringAttestation",
    }
)
_RECORD_FIELDS = _BASIS_FIELDS | {"id", "recordDigest"}


class ConceptStagingError(ValueError):
    """A local-concept authoring transition is incomplete or stale."""


@dataclass(frozen=True, slots=True)
class ConceptAuthoringSource:
    """One existing concept cited from its exact subject release."""

    release: SubjectConceptRelease
    concept_id: str


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        binding.validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise ConceptStagingError(str(error)) from error
    return canonical_json_bytes(plain)


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConceptStagingError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _require_array(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ConceptStagingError(f"{label} must be an array")
    return cast(Sequence[Any], value)


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise ConceptStagingError(
            f"{label} fields differ; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ConceptStagingError(f"{label} must be non-empty trimmed text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise ConceptStagingError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise ConceptStagingError(f"{label} must not contain credentials")
    return iri


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ConceptStagingError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _normalize_reference(value: object, label: str) -> dict[str, str]:
    row = _require_mapping(value, label)
    _require_exact_fields(row, _REFERENCE_FIELDS, label)
    return {
        "id": _require_iri(row.get("id"), f"{label}.id"),
        "digest": _require_digest(row.get("digest"), f"{label}.digest"),
    }


def _normalize_policy(value: object, label: str) -> dict[str, str]:
    row = _require_mapping(value, label)
    _require_exact_fields(row, _POLICY_FIELDS, label)
    return {
        "id": _require_iri(row.get("id"), f"{label}.id"),
        "version": _require_text(row.get("version"), f"{label}.version"),
        "contentDigest": _require_digest(
            row.get("contentDigest"),
            f"{label}.contentDigest",
        ),
    }


def _normalize_text_set(value: object, label: str) -> list[str]:
    rows = _require_array(value, label)
    if not rows:
        raise ConceptStagingError(f"{label} must not be empty")
    result = sorted(
        _require_text(item, f"{label}[{index}]")
        for index, item in enumerate(rows)
    )
    if len(result) != len(set(result)):
        raise ConceptStagingError(f"{label} must contain unique values")
    return result


def _normalize_iri_set(value: object, label: str) -> list[str]:
    rows = _require_array(value, label)
    if not rows:
        raise ConceptStagingError(f"{label} must not be empty")
    result = sorted(
        _require_iri(item, f"{label}[{index}]")
        for index, item in enumerate(rows)
    )
    if len(result) != len(set(result)):
        raise ConceptStagingError(f"{label} must contain unique IRIs")
    return result


def _normalize_language_map(
    value: object,
    label: str,
    *,
    multiple: bool,
) -> dict[str, str | list[str]]:
    row = _require_mapping(value, label)
    if not row:
        raise ConceptStagingError(f"{label} must not be empty")
    normalized: dict[str, str | list[str]] = {}
    for language, raw in sorted(row.items()):
        tag = _require_text(language, f"{label} language")
        if isinstance(raw, str):
            values = [_require_text(raw, f"{label}.{tag}")]
        else:
            values = _normalize_text_set(raw, f"{label}.{tag}")
        if not multiple and len(values) != 1:
            raise ConceptStagingError(
                f"{label}.{tag} must contain exactly one value"
            )
        normalized[tag] = values if multiple else values[0]
    return normalized


def _normalize_placement(value: object) -> dict[str, str]:
    label = "concept authoring checklist placement"
    row = _require_mapping(value, label)
    status = row.get("status")
    if status == "placed":
        _require_exact_fields(
            row,
            frozenset({"status", "relation", "targetConcept"}),
            label,
        )
        relation = _require_text(row.get("relation"), f"{label}.relation")
        if relation not in _PLACEMENT_RELATIONS:
            raise ConceptStagingError(f"{label}.relation is unsupported")
        return {
            "status": "placed",
            "relation": relation,
            "targetConcept": _require_iri(
                row.get("targetConcept"),
                f"{label}.targetConcept",
            ),
        }
    if status == "topConcept":
        _require_exact_fields(row, frozenset({"status"}), label)
        return {"status": "topConcept"}
    if status in {"nonhierarchical", "notApplicable"}:
        _require_exact_fields(row, frozenset({"status", "reason"}), label)
        return {
            "status": cast(str, status),
            "reason": _require_text(row.get("reason"), f"{label}.reason"),
        }
    raise ConceptStagingError(
        f"{label}.status must be placed, topConcept, nonhierarchical, or "
        "notApplicable"
    )


def _normalize_source(value: object, index: int) -> dict[str, Any]:
    label = f"concept authoring sourceConcepts[{index}]"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _SOURCE_FIELDS, label)
    try:
        release = normalize_concept_release_pin(row.get("conceptRelease"))
    except ConceptReleaseError as error:
        raise ConceptStagingError(str(error)) from error
    if release["semanticRing"] != "subject":
        raise ConceptStagingError("concept authoring sources must be subject concepts")
    return {
        "conceptId": _require_iri(row.get("conceptId"), f"{label}.conceptId"),
        "conceptRelease": release,
    }


def _normalize_sources(value: object, *, authoring_kind: AuthoringKind) -> list[dict[str, Any]]:
    rows = _require_array(value, "concept authoring sourceConcepts")
    result = [_normalize_source(item, index) for index, item in enumerate(rows)]
    result.sort(
        key=lambda item: (
            item["conceptId"],
            item["conceptRelease"]["releaseId"],
        )
    )
    concept_ids = [cast(str, item["conceptId"]) for item in result]
    if len(concept_ids) != len(set(concept_ids)):
        raise ConceptStagingError(
            "concept authoring sourceConcepts repeat a concept identity"
        )
    if authoring_kind == "consolidation" and len(result) < 2:
        raise ConceptStagingError("a consolidation requires at least two source concepts")
    if authoring_kind == "splitRefinement" and not result:
        raise ConceptStagingError("a split refinement requires at least one source concept")
    return result


def _normalize_checklist(value: object) -> dict[str, Any]:
    label = "concept authoring checklist"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _CHECKLIST_FIELDS, label)
    return {
        "definition": _normalize_language_map(
            row.get("definition"),
            f"{label}.definition",
            multiple=True,
        ),
        "inclusionCues": _normalize_text_set(
            row.get("inclusionCues"),
            f"{label}.inclusionCues",
        ),
        "exclusionCues": _normalize_text_set(
            row.get("exclusionCues"),
            f"{label}.exclusionCues",
        ),
        "preferredLabels": _normalize_language_map(
            row.get("preferredLabels"),
            f"{label}.preferredLabels",
            multiple=False,
        ),
        "alternateLabels": _normalize_language_map(
            row.get("alternateLabels"),
            f"{label}.alternateLabels",
            multiple=True,
        ),
        "placement": _normalize_placement(row.get("placement")),
        "duplicateAndMappingAnalysis": _require_text(
            row.get("duplicateAndMappingAnalysis"),
            f"{label}.duplicateAndMappingAnalysis",
        ),
        "representativeEvidence": _normalize_iri_set(
            row.get("representativeEvidence"),
            f"{label}.representativeEvidence",
        ),
        "evidencePolicy": _normalize_policy(
            row.get("evidencePolicy"),
            f"{label}.evidencePolicy",
        ),
        "expectedAssignmentEffect": _require_text(
            row.get("expectedAssignmentEffect"),
            f"{label}.expectedAssignmentEffect",
        ),
        "rightsAssessment": _normalize_reference(
            row.get("rightsAssessment"),
            f"{label}.rightsAssessment",
        ),
        "governancePolicy": _normalize_policy(
            row.get("governancePolicy"),
            f"{label}.governancePolicy",
        ),
    }


def _normalize_basis(value: Mapping[str, Any]) -> dict[str, Any]:
    row = cast(dict[str, Any], _plain(value))
    _require_exact_fields(row, _BASIS_FIELDS, "concept authoring transition basis")
    if row.get("type") != CONCEPT_AUTHORING_TRANSITION_TYPE:
        raise ConceptStagingError("concept authoring transition type is unsupported")
    if row.get("schemaVersion") != CONCEPT_AUTHORING_TRANSITION_VERSION:
        raise ConceptStagingError(
            "concept authoring transition schemaVersion is unsupported"
        )
    raw_kind = row.get("authoringKind")
    if not isinstance(raw_kind, str) or raw_kind not in _AUTHORING_KINDS:
        raise ConceptStagingError(
            "concept authoring authoringKind must be newMeaning, consolidation, "
            "or splitRefinement"
        )
    authoring_kind = cast(AuthoringKind, raw_kind)
    sources = _normalize_sources(
        row.get("sourceConcepts"),
        authoring_kind=authoring_kind,
    )
    authored_concept = _require_iri(
        row.get("authoredConcept"),
        "concept authoring authoredConcept",
    )
    if authored_concept in {source["conceptId"] for source in sources}:
        raise ConceptStagingError(
            "a RefSpec-authored concept must not reuse a cited source identity"
        )
    proposal = _normalize_reference(row.get("proposal"), "concept authoring proposal")
    if authored_concept == proposal["id"]:
        raise ConceptStagingError(
            "a RefSpec-authored concept must not reuse its proposal identifier"
        )
    try:
        authored_release = normalize_concept_release_pin(
            row.get("authoredConceptRelease")
        )
    except ConceptReleaseError as error:
        raise ConceptStagingError(str(error)) from error
    if (
        authored_release["releaseKind"] != "managedReferenceRelease"
        or authored_release["semanticRing"] != "subject"
    ):
        raise ConceptStagingError(
            "an authored subject concept requires an exact managed subject release"
        )
    attestation = _require_mapping(
        row.get("authoringAttestation"),
        "concept authoring authoringAttestation",
    )
    _require_exact_fields(
        attestation,
        _ATTESTATION_FIELDS,
        "concept authoring authoringAttestation",
    )
    return {
        "type": CONCEPT_AUTHORING_TRANSITION_TYPE,
        "schemaVersion": CONCEPT_AUTHORING_TRANSITION_VERSION,
        "proposal": proposal,
        "authoringKind": authoring_kind,
        "sourceConcepts": sources,
        "checklist": _normalize_checklist(row.get("checklist")),
        "authoredConcept": authored_concept,
        "authoredConceptRelease": authored_release,
        "authoringAttestation": {
            "id": _require_iri(
                attestation.get("id"),
                "concept authoring authoringAttestation.id",
            )
        },
    }


def _normalize_record(value: object) -> dict[str, Any]:
    row = _require_mapping(value, "concept authoring transition")
    _require_exact_fields(row, _RECORD_FIELDS, "concept authoring transition")
    basis = _normalize_basis({field: row[field] for field in _BASIS_FIELDS})
    record_digest = sha256_digest(_canonical_bytes(basis))
    expected = {
        **basis,
        "id": "urn:ref:concept-authoring-transition:"
        + record_digest.removeprefix("sha256:"),
        "recordDigest": record_digest,
    }
    if _plain(row) != expected:
        raise ConceptStagingError(
            "concept authoring transition is stale or not canonically ordered"
        )
    return expected


def _validated_ref_record(
    value: Mapping[str, Any],
    *,
    expected_type: str,
    label: str,
) -> dict[str, Any]:
    row = _plain(value)
    if not isinstance(row, dict) or row.get("type") != expected_type:
        raise ConceptStagingError(f"{label} has the wrong REF record type")
    diagnostics = binding.validate([row])
    if diagnostics:
        detail = "; ".join(diagnostic.render() for diagnostic in diagnostics)
        raise ConceptStagingError(f"{label} is invalid: {detail}")
    return row


def _proposal_context(value: Mapping[str, Any]) -> tuple[dict[str, str], list[str]]:
    proposal = _validated_ref_record(
        value,
        expected_type="urn:ref:type:ConceptProposal",
        label="concept proposal",
    )
    if proposal.get("workflowState") != "acceptedForPromotion":
        raise ConceptStagingError(
            "concept proposal must be acceptedForPromotion, but that state alone "
            "does not authorize authoring"
        )
    reference = {
        "id": _require_iri(proposal.get("id"), "concept proposal id"),
        "digest": _require_digest(
            proposal.get("canonicalPayloadDigest"),
            "concept proposal canonicalPayloadDigest",
        ),
    }
    evidence = _normalize_iri_set(
        proposal.get("evidenceAddresses"),
        "concept proposal evidenceAddresses",
    )
    return reference, evidence


def _rights_context(value: Mapping[str, Any]) -> dict[str, str]:
    rights = _validated_ref_record(
        value,
        expected_type="urn:ref:type:RightsAssessment",
        label="rights assessment",
    )
    return {
        "id": _require_iri(rights.get("id"), "rights assessment id"),
        "digest": _require_digest(
            rights.get("canonicalPayloadDigest"),
            "rights assessment canonicalPayloadDigest",
        ),
    }


def _node_types(node: Mapping[str, Any]) -> frozenset[str]:
    raw = node.get("@type")
    values = raw if isinstance(raw, Sequence) and not isinstance(raw, str) else (raw,)
    return frozenset(item for item in values if isinstance(item, str))


def _iri_values(value: object) -> tuple[str, ...]:
    values = (
        value
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        else (value,)
    )
    result: list[str] = []
    for item in values:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, Mapping) and isinstance(item.get("@id"), str):
            result.append(cast(str, item["@id"]))
    return tuple(result)


def _graph_nodes(graph: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = graph.get("@graph")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ConceptStagingError("managed Rulespec graph has no @graph array")
    result: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping) or not isinstance(item.get("@id"), str):
            raise ConceptStagingError(
                f"managed Rulespec graph @graph[{index}] is not a named node"
            )
        identifier = cast(str, item["@id"])
        if identifier in result:
            raise ConceptStagingError(
                f"managed Rulespec graph repeats identifier {identifier!r}"
            )
        result[identifier] = item
    return result


def _validate_placement_in_graph(
    placement: Mapping[str, str],
    *,
    concept_id: str,
    concept: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
) -> None:
    status = placement["status"]
    if status == "placed":
        relation = placement["relation"]
        target = placement["targetConcept"]
        property_name = _GRAPH_PLACEMENT_PROPERTIES[relation]
        if target not in _iri_values(concept.get(property_name)):
            raise ConceptStagingError(
                "the authored LocalConcept does not carry its reviewed placement"
            )
        if target == concept_id:
            raise ConceptStagingError("an authored concept cannot be placed against itself")
        return
    schemes = _iri_values(concept.get("skos:inScheme"))
    if len(schemes) != 1:
        raise ConceptStagingError(
            "the authored LocalConcept must identify exactly one concept scheme"
        )
    if status == "topConcept":
        scheme = nodes.get(schemes[0])
        if scheme is None or concept_id not in _iri_values(
            scheme.get("skos:hasTopConcept")
        ):
            raise ConceptStagingError(
                "the authored LocalConcept is not a top concept of its exact scheme"
            )
        return
    if _iri_values(concept.get("skos:broader")) or _iri_values(
        concept.get("skos:narrower")
    ):
        raise ConceptStagingError(
            "a nonhierarchical or not-applicable placement conflicts with exact "
            "LocalConcept hierarchy edges"
        )


def _output_context(
    release: PinnedManagedConceptRelease,
    *,
    authored_concept: str,
    authoring_attestation: str,
    placement: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(release, PinnedManagedConceptRelease):
        raise ConceptStagingError(
            "concept authoring requires an exact managed concept release"
        )
    try:
        require_subject_concept_release(release)
        concept_id = require_admissible_subject_concept(release, authored_concept)
        release_pin = concept_release_pin(release)
        view = release.verified_view()
    except ConceptReleaseError as error:
        raise ConceptStagingError(str(error)) from error
    graph = cast(Mapping[str, Any], view.rulespec_graph)
    nodes = _graph_nodes(graph)
    concept = nodes.get(concept_id)
    if concept is None or not (_node_types(concept) & _LOCAL_CONCEPT_TYPES):
        raise ConceptStagingError(
            "authoredConcept must be an actual rkaf:LocalConcept in the exact release"
        )
    attestation = nodes.get(authoring_attestation)
    if attestation is None or not (_node_types(attestation) & _ATTESTATION_TYPES):
        raise ConceptStagingError(
            "authoringAttestation must resolve to an rkaf:Attestation in the exact graph"
        )
    if attestation.get("rkaf:attestorKind") not in _CONCEPT_MINTING_AUTHORITY_KINDS:
        raise ConceptStagingError(
            "authoringAttestation must be made by a concept-minting authority"
        )
    decision = attestation.get("rkaf:decision")
    if decision not in _APPROVING_DECISIONS:
        raise ConceptStagingError("authoringAttestation must approve the authored concept")
    if concept_id not in _iri_values(attestation.get("rkaf:targets")):
        raise ConceptStagingError(
            "authoringAttestation must target the authored LocalConcept"
        )
    _require_iri(attestation.get("rkaf:attestor"), "authoring attestation attestor")
    _require_text(
        attestation.get("rkaf:attestedAt"),
        "authoring attestation attestedAt",
    )
    if "rkaf:revokedAt" in attestation:
        raise ConceptStagingError("a revoked authoringAttestation cannot author a concept")
    if decision in _CONDITIONAL_DECISIONS:
        _require_text(
            attestation.get("rkaf:rationale"),
            "conditional authoring attestation rationale",
        )
    preferred = _normalize_language_map(
        concept.get("skos:prefLabel"),
        "authored LocalConcept skos:prefLabel",
        multiple=False,
    )
    alternate = _normalize_language_map(
        concept.get("skos:altLabel"),
        "authored LocalConcept skos:altLabel",
        multiple=True,
    )
    definition = _normalize_language_map(
        concept.get("skos:definition"),
        "authored LocalConcept skos:definition",
        multiple=True,
    )
    _validate_placement_in_graph(
        placement,
        concept_id=concept_id,
        concept=concept,
        nodes=nodes,
    )
    return release_pin, {
        "preferredLabels": preferred,
        "alternateLabels": alternate,
        "definition": definition,
    }


def _source_context(
    values: Sequence[ConceptAuthoringSource],
    *,
    authored_concept: str,
    authoring_kind: AuthoringKind,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, source in enumerate(values):
        if not isinstance(source, ConceptAuthoringSource):
            raise ConceptStagingError(
                f"concept authoring source[{index}] must be ConceptAuthoringSource"
            )
        try:
            concept_id = require_admissible_subject_concept(
                source.release,
                source.concept_id,
            )
            release_pin = concept_release_pin(source.release)
        except ConceptReleaseError as error:
            raise ConceptStagingError(str(error)) from error
        if concept_id == authored_concept:
            raise ConceptStagingError(
                "a RefSpec-authored concept must not reuse a cited source identity"
            )
        records.append(
            {
                "conceptId": concept_id,
                "conceptRelease": release_pin,
            }
        )
    return _normalize_sources(records, authoring_kind=authoring_kind)


@dataclass(frozen=True, slots=True)
class ConceptAuthoringTransition:
    """One immutable receipt over a completed, governed authoring transition."""

    record: Mapping[str, Any]

    def __post_init__(self) -> None:
        normalized = _normalize_record(self.record)
        object.__setattr__(
            self,
            "record",
            cast(Mapping[str, Any], deep_freeze_json(normalized)),
        )

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> Self:
        return cls(record=value)

    @property
    def identifier(self) -> str:
        return cast(str, self.record["id"])

    @property
    def record_digest(self) -> str:
        return cast(str, self.record["recordDigest"])

    @property
    def authored_concept(self) -> str:
        return cast(str, self.record["authoredConcept"])

    def as_record(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self.record))

    def artifact_bytes(self) -> bytes:
        return _canonical_bytes(self.as_record())

    def write_to(self, path: Path | str) -> Path:
        destination = Path(path)
        if destination.exists() or destination.is_symlink():
            raise ConceptStagingError(
                f"concept authoring transition destination already exists: {destination}"
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

    def validate_context(
        self,
        *,
        proposal: Mapping[str, Any],
        authored_release: PinnedManagedConceptRelease,
        source_concepts: Sequence[ConceptAuthoringSource],
        rights_assessment: Mapping[str, Any],
    ) -> None:
        """Reopen every exact input and require the same completed transition."""

        record = self.as_record()
        proposal_ref, evidence = _proposal_context(proposal)
        rights_ref = _rights_context(rights_assessment)
        authoring_kind = cast(AuthoringKind, record["authoringKind"])
        sources = _source_context(
            source_concepts,
            authored_concept=self.authored_concept,
            authoring_kind=authoring_kind,
        )
        checklist = cast(dict[str, Any], record["checklist"])
        output_pin, authored_text = _output_context(
            authored_release,
            authored_concept=self.authored_concept,
            authoring_attestation=cast(
                str,
                record["authoringAttestation"]["id"],
            ),
            placement=cast(Mapping[str, str], checklist["placement"]),
        )
        if record["proposal"] != proposal_ref:
            raise ConceptStagingError("concept authoring transition names another proposal")
        if checklist["representativeEvidence"] != evidence:
            raise ConceptStagingError(
                "concept authoring transition evidence differs from the exact proposal"
            )
        if checklist["rightsAssessment"] != rights_ref:
            raise ConceptStagingError(
                "concept authoring transition names another rights assessment"
            )
        if record["sourceConcepts"] != sources:
            raise ConceptStagingError(
                "concept authoring transition names other source concepts or releases"
            )
        if record["authoredConceptRelease"] != output_pin:
            raise ConceptStagingError(
                "concept authoring transition names another authored release"
            )
        for field, value in authored_text.items():
            if checklist[field] != value:
                raise ConceptStagingError(
                    f"concept authoring checklist {field} differs from the exact LocalConcept"
                )


def build_concept_authoring_transition(
    proposal: Mapping[str, Any],
    authored_release: PinnedManagedConceptRelease,
    *,
    authored_concept: str,
    authoring_attestation: str,
    authoring_kind: AuthoringKind,
    source_concepts: Sequence[ConceptAuthoringSource] = (),
    inclusion_cues: Sequence[str],
    exclusion_cues: Sequence[str],
    placement: Mapping[str, str],
    duplicate_and_mapping_analysis: str,
    evidence_policy: Mapping[str, str],
    expected_assignment_effect: str,
    rights_assessment: Mapping[str, Any],
    governance_policy: Mapping[str, str],
) -> ConceptAuthoringTransition:
    """Seal a completed authoring transition without minting or publishing it."""

    if authoring_kind not in _AUTHORING_KINDS:
        raise ConceptStagingError("authoring_kind is unsupported")
    concept_id = _require_iri(authored_concept, "authored_concept")
    proposal_ref, evidence = _proposal_context(proposal)
    rights_ref = _rights_context(rights_assessment)
    normalized_placement = _normalize_placement(placement)
    sources = _source_context(
        source_concepts,
        authored_concept=concept_id,
        authoring_kind=authoring_kind,
    )
    output_pin, authored_text = _output_context(
        authored_release,
        authored_concept=concept_id,
        authoring_attestation=_require_iri(
            authoring_attestation,
            "authoring_attestation",
        ),
        placement=normalized_placement,
    )
    basis = _normalize_basis(
        {
            "type": CONCEPT_AUTHORING_TRANSITION_TYPE,
            "schemaVersion": CONCEPT_AUTHORING_TRANSITION_VERSION,
            "proposal": proposal_ref,
            "authoringKind": authoring_kind,
            "sourceConcepts": sources,
            "checklist": {
                **authored_text,
                "inclusionCues": list(inclusion_cues),
                "exclusionCues": list(exclusion_cues),
                "placement": normalized_placement,
                "duplicateAndMappingAnalysis": duplicate_and_mapping_analysis,
                "representativeEvidence": evidence,
                "evidencePolicy": dict(evidence_policy),
                "expectedAssignmentEffect": expected_assignment_effect,
                "rightsAssessment": rights_ref,
                "governancePolicy": dict(governance_policy),
            },
            "authoredConcept": concept_id,
            "authoredConceptRelease": output_pin,
            "authoringAttestation": {"id": authoring_attestation},
        }
    )
    record_digest = sha256_digest(_canonical_bytes(basis))
    transition = ConceptAuthoringTransition(
        {
            **basis,
            "id": "urn:ref:concept-authoring-transition:"
            + record_digest.removeprefix("sha256:"),
            "recordDigest": record_digest,
        }
    )
    transition.validate_context(
        proposal=proposal,
        authored_release=authored_release,
        source_concepts=source_concepts,
        rights_assessment=rights_assessment,
    )
    return transition


def read_concept_authoring_transition(path: Path | str) -> ConceptAuthoringTransition:
    """Read one canonical transition receipt from a regular, non-symlink file."""

    candidate = Path(path)
    if candidate.is_symlink():
        raise ConceptStagingError("concept authoring transition must not be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise ConceptStagingError("concept authoring transition does not exist") from error
    if not resolved.is_file():
        raise ConceptStagingError("concept authoring transition must be a regular file")
    payload = resolved.read_bytes()
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ConceptStagingError(
            "concept authoring transition must be canonical UTF-8 JSON"
        ) from error
    if not isinstance(value, Mapping) or _canonical_bytes(value) != payload:
        raise ConceptStagingError(
            "concept authoring transition bytes are not canonical"
        )
    transition = ConceptAuthoringTransition.from_record(value)
    if resolved.read_bytes() != payload:
        raise ConceptStagingError("concept authoring transition changed while reading")
    return transition


__all__ = [
    "CONCEPT_AUTHORING_TRANSITION_TYPE",
    "CONCEPT_AUTHORING_TRANSITION_VERSION",
    "AuthoringKind",
    "ConceptAuthoringSource",
    "ConceptAuthoringTransition",
    "ConceptStagingError",
    "build_concept_authoring_transition",
    "read_concept_authoring_transition",
]
