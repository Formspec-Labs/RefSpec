"""Named admission reviews for existing subject concept identities.

A source or managed release supplies identity and the wide subject mapping
tier. This module records the separate editorial decision that places one
existing identity in the curated emit tier. Managed admission accepts only an
actual ``rkaf:LocalConcept`` in an exact complete release. The review pins the
release and its rights facts; it never creates a second concept or grants use.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from refspec import binding
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.semantic_foundation import (
    EvidenceAssertion,
    RightsMetadata,
    SemanticFoundationError,
    validate_evidence_assertions,
    validate_rights_metadata_records,
)
from refspec.registry.infrastructure.source_identity import (
    SourceIdentityError,
    require_aware_datetime_text,
)

from .concept_release import (
    ConceptReleaseError,
    SubjectConceptRelease,
    VerifiedConceptReleaseFacts,
    normalize_concept_release_pin,
    verified_concept_release_facts,
)

SUBJECT_ADMISSION_REVIEW_VERSION = "1.0"
SUBJECT_ADMISSION_ADMIT = "urn:ref:decision:subject-admission:admit"
SUBJECT_ADMISSION_REJECT = "urn:ref:decision:subject-admission:reject"

AdmissionDecision = Literal["admit", "reject"]

_DECISION_IRIS: Mapping[AdmissionDecision, str] = {
    "admit": SUBJECT_ADMISSION_ADMIT,
    "reject": SUBJECT_ADMISSION_REJECT,
}
_HIERARCHY_RELATIONS = frozenset({"broaderThan", "narrowerThan", "topConceptOf"})
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVIEW_BASIS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "decision",
        "subjectConcept",
        "subjectConceptRelease",
        "definitionOrScopeNote",
        "hierarchyPlacement",
        "facet",
        "evidenceAssertions",
        "rightsMetadata",
        "reviewer",
        "reviewedAt",
        "intendedProductUses",
    }
)
_REVIEW_RECORD_FIELDS = _REVIEW_BASIS_FIELDS | {"id", "recordDigest"}


class SubjectAdmissionError(ValueError):
    """A subject admission review is incomplete or bound to other facts."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        binding.validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise SubjectAdmissionError(str(error)) from error
    return canonical_json_bytes(plain)


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise SubjectAdmissionError(f"{label} must be non-empty trimmed text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise SubjectAdmissionError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise SubjectAdmissionError(f"{label} must not contain credentials")
    return iri


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SubjectAdmissionError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_datetime(value: object, label: str) -> str:
    text = _require_text(value, label)
    try:
        return require_aware_datetime_text(text, label=label)
    except SourceIdentityError as error:
        raise SubjectAdmissionError(str(error)) from error


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise SubjectAdmissionError(
            f"{label} fields differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _require_unique_iris(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise SubjectAdmissionError(f"{label} must be a non-empty IRI array")
    result = tuple(_require_iri(item, f"{label}[{index}]") for index, item in enumerate(value))
    if len(set(result)) != len(result):
        raise SubjectAdmissionError(f"{label} must contain unique IRIs")
    return tuple(sorted(result))


def _verified_release_facts(
    release: SubjectConceptRelease,
) -> VerifiedConceptReleaseFacts:
    try:
        facts = verified_concept_release_facts(release)
        facts.require_subject()
    except ConceptReleaseError as error:
        raise SubjectAdmissionError(str(error)) from error
    return facts


def _release_pin(facts: VerifiedConceptReleaseFacts) -> dict[str, Any]:
    return cast(dict[str, Any], _plain(facts.pin))


def _require_admissible_concept(
    facts: VerifiedConceptReleaseFacts,
    concept_iri: str,
) -> str:
    try:
        return facts.require_admissible_subject_concept(concept_iri)
    except ConceptReleaseError as error:
        raise SubjectAdmissionError(str(error)) from error


def _release_rights(
    facts: VerifiedConceptReleaseFacts,
    supplied: Sequence[RightsMetadata | Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], ...]:
    try:
        return facts.rights_metadata(supplied)
    except ConceptReleaseError as error:
        raise SubjectAdmissionError(str(error)) from error


def _hierarchy_placement(value: object, *, subject_concept: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise SubjectAdmissionError("hierarchyPlacement must be an object")
    row = cast(dict[str, Any], _plain(value))
    status = row.get("status")
    if status == "anchored":
        _require_exact_fields(row, {"status", "relation", "anchor"}, "hierarchyPlacement")
        relation = _require_text(row.get("relation"), "hierarchyPlacement.relation")
        if relation not in _HIERARCHY_RELATIONS:
            raise SubjectAdmissionError("hierarchyPlacement.relation is unsupported")
        anchor = _require_iri(row.get("anchor"), "hierarchyPlacement.anchor")
        if anchor == subject_concept:
            raise SubjectAdmissionError("hierarchyPlacement cannot anchor a concept to itself")
        return {"status": "anchored", "relation": relation, "anchor": anchor}
    if status == "unresolved":
        _require_exact_fields(row, {"status", "reason"}, "hierarchyPlacement")
        return {
            "status": "unresolved",
            "reason": _require_text(row.get("reason"), "hierarchyPlacement.reason"),
        }
    raise SubjectAdmissionError("hierarchyPlacement.status must be anchored or unresolved")


def _evidence_records(
    values: object,
    *,
    decision: AdmissionDecision,
    reviewer: str,
    reviewed_at: str,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
        raise SubjectAdmissionError("evidenceAssertions must be a non-empty array")
    try:
        assertions = validate_evidence_assertions(
            cast(Sequence[EvidenceAssertion | Mapping[str, Any]], values),
            semantic_ring="subject",
        )
    except SemanticFoundationError as error:
        raise SubjectAdmissionError(str(error)) from error
    decision_iri = _DECISION_IRIS[decision]
    matching_reviews = [
        assertion
        for assertion in assertions
        if assertion.evidence_class == "humanReviewed"
        and assertion.asserted_by == reviewer
        and assertion.asserted_at == reviewed_at
        and assertion.review_decision == decision_iri
    ]
    if not matching_reviews:
        raise SubjectAdmissionError(
            "admission decision requires matching humanReviewed evidence from the named reviewer"
        )
    return tuple(assertion.as_record() for assertion in assertions)


def _rights_records(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise SubjectAdmissionError("rightsMetadata must be a non-empty array")
    try:
        rights = validate_rights_metadata_records(
            cast(Sequence[RightsMetadata | Mapping[str, Any]], value)
        )
    except SemanticFoundationError as error:
        raise SubjectAdmissionError(str(error)) from error
    return tuple(item.as_record() for item in rights)


def _normalized_review_basis(value: Mapping[str, Any]) -> dict[str, Any]:
    row = cast(dict[str, Any], _plain(value))
    _require_exact_fields(row, set(_REVIEW_BASIS_FIELDS), "subject admission review basis")
    if row.get("type") != "SubjectAdmissionReview":
        raise SubjectAdmissionError("subject admission review type is unsupported")
    if row.get("schemaVersion") != SUBJECT_ADMISSION_REVIEW_VERSION:
        raise SubjectAdmissionError("subject admission review schemaVersion is unsupported")
    decision = row.get("decision")
    if decision not in _DECISION_IRIS:
        raise SubjectAdmissionError("subject admission review decision must be admit or reject")
    decision = cast(AdmissionDecision, decision)
    subject_concept = _require_iri(row.get("subjectConcept"), "subjectConcept")
    try:
        normalized_pin = normalize_concept_release_pin(
            row.get("subjectConceptRelease")
        )
    except ConceptReleaseError as error:
        raise SubjectAdmissionError(str(error)) from error
    if normalized_pin["semanticRing"] != "subject":
        raise SubjectAdmissionError(
            "subject admission review rejects a non-subject release pin"
        )
    reviewer = _require_iri(row.get("reviewer"), "reviewer")
    reviewed_at = _require_datetime(row.get("reviewedAt"), "reviewedAt")
    return {
        "type": "SubjectAdmissionReview",
        "schemaVersion": SUBJECT_ADMISSION_REVIEW_VERSION,
        "decision": decision,
        "subjectConcept": subject_concept,
        "subjectConceptRelease": normalized_pin,
        "definitionOrScopeNote": _require_text(
            row.get("definitionOrScopeNote"),
            "definitionOrScopeNote",
        ),
        "hierarchyPlacement": _hierarchy_placement(
            row.get("hierarchyPlacement"),
            subject_concept=subject_concept,
        ),
        "facet": _require_iri(row.get("facet"), "facet"),
        "evidenceAssertions": list(
            _evidence_records(
                row.get("evidenceAssertions"),
                decision=decision,
                reviewer=reviewer,
                reviewed_at=reviewed_at,
            )
        ),
        "rightsMetadata": list(_rights_records(row.get("rightsMetadata"))),
        "reviewer": reviewer,
        "reviewedAt": reviewed_at,
        "intendedProductUses": list(
            _require_unique_iris(row.get("intendedProductUses"), "intendedProductUses")
        ),
    }


def _normalized_review_record(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SubjectAdmissionError("subject admission review must be an object")
    row = cast(dict[str, Any], _plain(value))
    _require_exact_fields(row, set(_REVIEW_RECORD_FIELDS), "subject admission review")
    basis = _normalized_review_basis(
        {field: row[field] for field in _REVIEW_BASIS_FIELDS}
    )
    record_digest = sha256_digest(_canonical_bytes(basis))
    expected = {
        **basis,
        "id": f"urn:ref:subject-admission-review:{record_digest.removeprefix('sha256:')}",
        "recordDigest": record_digest,
    }
    if row != expected:
        raise SubjectAdmissionError("subject admission review is stale or not canonically ordered")
    return expected


@dataclass(frozen=True, slots=True)
class SubjectAdmissionReview:
    """One immutable review of one existing concept in one exact release."""

    record: Mapping[str, Any]

    def __post_init__(self) -> None:
        normalized = _normalized_review_record(self.record)
        object.__setattr__(
            self,
            "record",
            cast(Mapping[str, Any], deep_freeze_json(normalized)),
        )

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> SubjectAdmissionReview:
        return cls(record=value)

    @property
    def identifier(self) -> str:
        return cast(str, self.record["id"])

    @property
    def record_digest(self) -> str:
        return cast(str, self.record["recordDigest"])

    @property
    def reference(self) -> Mapping[str, str]:
        return {
            "id": self.identifier,
            "digest": self.record_digest,
        }

    @property
    def decision(self) -> AdmissionDecision:
        return cast(AdmissionDecision, self.record["decision"])

    @property
    def subject_concept(self) -> str:
        return cast(str, self.record["subjectConcept"])

    @property
    def facet(self) -> str:
        return cast(str, self.record["facet"])

    @property
    def intended_product_uses(self) -> tuple[str, ...]:
        return cast(tuple[str, ...], self.record["intendedProductUses"])

    def as_record(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self.record))

    def validate_for_release(self, release: SubjectConceptRelease) -> None:
        """Require the exact release, existing identity, and sealed rights facts."""

        self._validate_for_facts(_verified_release_facts(release))

    def _validate_for_facts(
        self,
        facts: VerifiedConceptReleaseFacts,
    ) -> None:
        """Validate against facts already opened for this operation."""

        if _plain(self.record["subjectConceptRelease"]) != _release_pin(facts):
            raise SubjectAdmissionError("subject admission review names another exact release")
        _require_admissible_concept(facts, self.subject_concept)
        release_rights = _release_rights(
            facts,
            cast(Sequence[Mapping[str, Any]], self.record["rightsMetadata"]),
        )
        if _plain(self.record["rightsMetadata"]) != list(release_rights):
            raise SubjectAdmissionError("subject admission review rights differ from the exact release")


def build_subject_admission_review(
    release: SubjectConceptRelease,
    *,
    subject_concept: str,
    decision: AdmissionDecision,
    definition_or_scope_note: str,
    hierarchy_placement: Mapping[str, str],
    facet: str,
    evidence_assertions: Sequence[EvidenceAssertion | Mapping[str, Any]],
    reviewer: str,
    reviewed_at: str,
    intended_product_uses: Sequence[str],
    rights_metadata: Sequence[RightsMetadata | Mapping[str, Any]] | None = None,
) -> SubjectAdmissionReview:
    """Review an existing identity without re-minting it or granting use."""

    facts = _verified_release_facts(release)
    if decision not in _DECISION_IRIS:
        raise SubjectAdmissionError("decision must be admit or reject")
    concept = _require_admissible_concept(facts, subject_concept)
    reviewer_iri = _require_iri(reviewer, "reviewer")
    review_time = _require_datetime(reviewed_at, "reviewed_at")
    raw_basis = {
        "type": "SubjectAdmissionReview",
        "schemaVersion": SUBJECT_ADMISSION_REVIEW_VERSION,
        "decision": decision,
        "subjectConcept": concept,
        "subjectConceptRelease": _release_pin(facts),
        "definitionOrScopeNote": definition_or_scope_note,
        "hierarchyPlacement": dict(hierarchy_placement),
        "facet": facet,
        "evidenceAssertions": [
            value.as_record() if isinstance(value, EvidenceAssertion) else dict(value)
            for value in evidence_assertions
        ],
        "rightsMetadata": list(_release_rights(facts, rights_metadata)),
        "reviewer": reviewer_iri,
        "reviewedAt": review_time,
        "intendedProductUses": list(intended_product_uses),
    }
    basis = _normalized_review_basis(raw_basis)
    record_digest = sha256_digest(_canonical_bytes(basis))
    return SubjectAdmissionReview(
        {
            **basis,
            "id": f"urn:ref:subject-admission-review:{record_digest.removeprefix('sha256:')}",
            "recordDigest": record_digest,
        }
    )


def validate_subject_admission_reviews(
    release: SubjectConceptRelease,
    values: Sequence[SubjectAdmissionReview | Mapping[str, Any]],
) -> tuple[SubjectAdmissionReview, ...]:
    """Validate one final review per release member; product use stays separate."""

    return _validate_subject_admission_reviews_with_facts(
        _verified_release_facts(release),
        values,
    )


def _validate_subject_admission_reviews_with_facts(
    facts: VerifiedConceptReleaseFacts,
    values: Sequence[SubjectAdmissionReview | Mapping[str, Any]],
) -> tuple[SubjectAdmissionReview, ...]:
    """Validate several reviews from one operation-scoped release view."""

    result: list[SubjectAdmissionReview] = []
    concepts: set[str] = set()
    identifiers: set[str] = set()
    for value in values:
        review = (
            value
            if isinstance(value, SubjectAdmissionReview)
            else SubjectAdmissionReview.from_record(value)
        )
        review._validate_for_facts(facts)
        if review.identifier in identifiers:
            raise SubjectAdmissionError("subject admission reviews repeat an id")
        if review.subject_concept in concepts:
            raise SubjectAdmissionError(
                "subject admission reviews contain multiple final decisions for one concept"
            )
        identifiers.add(review.identifier)
        concepts.add(review.subject_concept)
        result.append(review)
    return tuple(sorted(result, key=lambda value: value.identifier))


def admitted_subject_concept_ids(
    release: SubjectConceptRelease,
    reviews: Sequence[SubjectAdmissionReview | Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return the curated-tier identities; this result grants no product use."""

    validated = validate_subject_admission_reviews(release, reviews)
    return tuple(sorted(review.subject_concept for review in validated if review.decision == "admit"))


__all__ = [
    "SUBJECT_ADMISSION_ADMIT",
    "SUBJECT_ADMISSION_REJECT",
    "SUBJECT_ADMISSION_REVIEW_VERSION",
    "AdmissionDecision",
    "SubjectAdmissionError",
    "SubjectAdmissionReview",
    "admitted_subject_concept_ids",
    "build_subject_admission_review",
    "validate_subject_admission_reviews",
]
