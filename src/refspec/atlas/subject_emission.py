"""Resolve subject eligibility and a product-profile grant without re-minting.

Admission remains a factual editorial record. A SubjectEmissionPolicy pins
the exact subject concept release, admission reviews, and eligible uses. It does
not grant use.  OutputProfile supplies the separate candidate/output-use grant
for that exact policy.  Resolution requires both records.  This module does
not prove the later configuration, evaluation, and deployment chain required
to authorize one accepted assignment.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from refspec import binding
from refspec.atlas.subject_admission import (
    SubjectAdmissionError,
    SubjectAdmissionReview,
    _validate_subject_admission_reviews_with_facts,
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
from refspec.vocabulary import OutputProfile, ReferenceRuntimeError

from .concept_release import (
    ConceptReleaseError,
    SubjectConceptRelease,
    VerifiedConceptReleaseFacts,
    normalize_concept_release_pin,
    verified_concept_release_facts,
)

SUBJECT_EMISSION_POLICY_VERSION = "1.0"
SUBJECT_EMISSION_POLICY_TYPE = "urn:ref:type:SubjectEmissionPolicy"

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_POLICY_BASIS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "version",
        "recordedAt",
        "recordedBy",
        "subjectConceptRelease",
        "eligibility",
    }
)
_POLICY_RECORD_FIELDS = _POLICY_BASIS_FIELDS | {"id", "contentDigest"}
_ELIGIBILITY_FIELDS = frozenset(
    {
        "subjectConcept",
        "subjectAdmissionReview",
        "facet",
        "assignmentRole",
        "intendedProductUse",
    }
)


class SubjectEmissionError(ValueError):
    """The supplied facts do not resolve one exact subject policy chain."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        binding.validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise SubjectEmissionError(str(error)) from error
    return canonical_json_bytes(plain)


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise SubjectEmissionError(f"{label} must be non-empty trimmed text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise SubjectEmissionError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise SubjectEmissionError(f"{label} must not contain credentials")
    return iri


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SubjectEmissionError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_datetime(value: object, label: str) -> str:
    text = _require_text(value, label)
    try:
        return require_aware_datetime_text(text, label=label)
    except SourceIdentityError as error:
        raise SubjectEmissionError(str(error)) from error


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise SubjectEmissionError(
            f"{label} fields differ; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _verified_release_facts(
    release: SubjectConceptRelease,
) -> VerifiedConceptReleaseFacts:
    try:
        facts = verified_concept_release_facts(release)
        facts.require_subject()
    except ConceptReleaseError as error:
        raise SubjectEmissionError(str(error)) from error
    return facts


def _release_pin(facts: VerifiedConceptReleaseFacts) -> dict[str, Any]:
    return cast(dict[str, Any], _plain(facts.pin))


def _normalized_release_pin(value: object) -> dict[str, Any]:
    try:
        pin = normalize_concept_release_pin(value)
    except ConceptReleaseError as error:
        raise SubjectEmissionError(str(error)) from error
    if pin["semanticRing"] != "subject":
        raise SubjectEmissionError(
            "subject emission policy rejects a non-subject release pin"
        )
    return pin


def _normalized_review_reference(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise SubjectEmissionError(f"{label} must be an object")
    row = cast(dict[str, Any], _plain(value))
    _require_exact_fields(row, {"id", "digest"}, label)
    return {
        "id": _require_iri(row.get("id"), f"{label}.id"),
        "digest": _require_digest(row.get("digest"), f"{label}.digest"),
    }


def _normalized_versioned_reference(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise SubjectEmissionError(f"{label} must be an object")
    row = cast(dict[str, Any], _plain(value))
    _require_exact_fields(row, {"id", "version", "digest"}, label)
    return {
        "id": _require_iri(row.get("id"), f"{label}.id"),
        "version": _require_text(row.get("version"), f"{label}.version"),
        "digest": _require_digest(row.get("digest"), f"{label}.digest"),
    }


def _normalized_eligibility(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise SubjectEmissionError("eligibility must be a non-empty array")
    result: list[dict[str, Any]] = []
    selectors: set[tuple[str, str, str, str]] = set()
    for index, item in enumerate(value):
        label = f"eligibility[{index}]"
        if not isinstance(item, Mapping):
            raise SubjectEmissionError(f"{label} must be an object")
        row = cast(dict[str, Any], _plain(item))
        _require_exact_fields(row, set(_ELIGIBILITY_FIELDS), label)
        normalized = {
            "subjectConcept": _require_iri(row.get("subjectConcept"), f"{label}.subjectConcept"),
            "subjectAdmissionReview": _normalized_review_reference(
                row.get("subjectAdmissionReview"),
                f"{label}.subjectAdmissionReview",
            ),
            "facet": _require_iri(row.get("facet"), f"{label}.facet"),
            "assignmentRole": _require_iri(
                row.get("assignmentRole"),
                f"{label}.assignmentRole",
            ),
            "intendedProductUse": _require_iri(
                row.get("intendedProductUse"),
                f"{label}.intendedProductUse",
            ),
        }
        selector = (
            normalized["subjectConcept"],
            normalized["facet"],
            normalized["assignmentRole"],
            normalized["intendedProductUse"],
        )
        if selector in selectors:
            raise SubjectEmissionError(
                "eligibility repeats a concept/facet/role/product-use selector"
            )
        selectors.add(selector)
        result.append(normalized)
    return tuple(
        sorted(
            result,
            key=lambda row: (
                row["subjectConcept"],
                row["facet"],
                row["assignmentRole"],
                row["intendedProductUse"],
                row["subjectAdmissionReview"]["id"],
            ),
        )
    )


def _normalized_policy_basis(value: Mapping[str, Any]) -> dict[str, Any]:
    row = cast(dict[str, Any], _plain(value))
    _require_exact_fields(row, set(_POLICY_BASIS_FIELDS), "subject emission policy basis")
    if row.get("type") != SUBJECT_EMISSION_POLICY_TYPE:
        raise SubjectEmissionError("subject emission policy type is unsupported")
    if row.get("schemaVersion") != SUBJECT_EMISSION_POLICY_VERSION:
        raise SubjectEmissionError("subject emission policy schemaVersion is unsupported")
    return {
        "type": SUBJECT_EMISSION_POLICY_TYPE,
        "schemaVersion": SUBJECT_EMISSION_POLICY_VERSION,
        "version": _require_text(row.get("version"), "version"),
        "recordedAt": _require_datetime(row.get("recordedAt"), "recordedAt"),
        "recordedBy": _require_iri(row.get("recordedBy"), "recordedBy"),
        "subjectConceptRelease": _normalized_release_pin(
            row.get("subjectConceptRelease")
        ),
        "eligibility": list(_normalized_eligibility(row.get("eligibility"))),
    }


def _normalized_policy_record(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SubjectEmissionError("subject emission policy must be an object")
    row = cast(dict[str, Any], _plain(value))
    _require_exact_fields(row, set(_POLICY_RECORD_FIELDS), "subject emission policy")
    basis = _normalized_policy_basis(
        {field: row[field] for field in _POLICY_BASIS_FIELDS}
    )
    content_digest = sha256_digest(_canonical_bytes(basis))
    expected = {
        **basis,
        "id": f"urn:ref:subject-emission-policy:{content_digest.removeprefix('sha256:')}",
        "contentDigest": content_digest,
    }
    if row != expected:
        raise SubjectEmissionError("subject emission policy is stale or not canonical")
    return expected


@dataclass(frozen=True, slots=True)
class SubjectEmissionPolicy:
    """One immutable eligibility policy over exact subject admission reviews."""

    record: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "record",
            cast(Mapping[str, Any], deep_freeze_json(_normalized_policy_record(self.record))),
        )

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> SubjectEmissionPolicy:
        return cls(record=value)

    @property
    def identifier(self) -> str:
        return cast(str, self.record["id"])

    @property
    def version(self) -> str:
        return cast(str, self.record["version"])

    @property
    def content_digest(self) -> str:
        return cast(str, self.record["contentDigest"])

    @property
    def reference(self) -> Mapping[str, str]:
        return {
            "id": self.identifier,
            "version": self.version,
            "digest": self.content_digest,
        }

    @property
    def eligibility(self) -> tuple[Mapping[str, Any], ...]:
        return cast(tuple[Mapping[str, Any], ...], self.record["eligibility"])

    def as_record(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self.record))

    def validate_for_release(
        self,
        release: SubjectConceptRelease,
        reviews: Sequence[SubjectAdmissionReview | Mapping[str, Any]],
    ) -> tuple[SubjectAdmissionReview, ...]:
        """Resolve every policy row to one admitted review on the exact release."""

        return self._validate_for_facts(
            _verified_release_facts(release),
            reviews,
        )

    def _validate_for_facts(
        self,
        facts: VerifiedConceptReleaseFacts,
        reviews: Sequence[SubjectAdmissionReview | Mapping[str, Any]],
    ) -> tuple[SubjectAdmissionReview, ...]:
        """Resolve policy rows from one operation-scoped release view."""

        if _plain(self.record["subjectConceptRelease"]) != _release_pin(facts):
            raise SubjectEmissionError("subject emission policy names another exact release")
        try:
            validated = _validate_subject_admission_reviews_with_facts(
                facts,
                reviews,
            )
        except SubjectAdmissionError as error:
            raise SubjectEmissionError(str(error)) from error
        reviews_by_id = {review.identifier: review for review in validated}
        referenced_ids = {
            cast(str, row["subjectAdmissionReview"]["id"])
            for row in self.eligibility
        }
        if set(reviews_by_id) != referenced_ids:
            raise SubjectEmissionError(
                "subject emission policy requires exactly its pinned admission review set"
            )
        for row in self.eligibility:
            review_reference = cast(Mapping[str, str], row["subjectAdmissionReview"])
            review = reviews_by_id[review_reference["id"]]
            if _plain(review.reference) != _plain(review_reference):
                raise SubjectEmissionError("subject emission policy admission review digest differs")
            if review.decision != "admit":
                raise SubjectEmissionError("subject emission policy cannot select a rejected concept")
            if row["subjectConcept"] != review.subject_concept:
                raise SubjectEmissionError("subject emission policy concept differs from its admission review")
            if row["facet"] != review.facet:
                raise SubjectEmissionError("subject emission policy facet differs from its admission review")
            if row["intendedProductUse"] not in review.intended_product_uses:
                raise SubjectEmissionError(
                    "subject emission policy product use is absent from its admission review"
                )
        return validated


def subject_emission_eligibility(
    review: SubjectAdmissionReview,
    *,
    assignment_role: str,
    intended_product_use: str,
) -> dict[str, Any]:
    """Build one eligibility row from an admitted review without changing identity."""

    if not isinstance(review, SubjectAdmissionReview):
        raise SubjectEmissionError("review must be a SubjectAdmissionReview")
    if review.decision != "admit":
        raise SubjectEmissionError("a rejected review cannot become emission eligibility")
    product_use = _require_iri(intended_product_use, "intended_product_use")
    if product_use not in review.intended_product_uses:
        raise SubjectEmissionError("intended_product_use is absent from the admission review")
    return {
        "subjectConcept": review.subject_concept,
        "subjectAdmissionReview": dict(review.reference),
        "facet": review.facet,
        "assignmentRole": _require_iri(assignment_role, "assignment_role"),
        "intendedProductUse": product_use,
    }


def build_subject_emission_policy(
    release: SubjectConceptRelease,
    reviews: Sequence[SubjectAdmissionReview | Mapping[str, Any]],
    *,
    version: str,
    recorded_at: str,
    recorded_by: str,
    eligibility: Sequence[Mapping[str, Any]],
) -> SubjectEmissionPolicy:
    """Build eligibility that still requires an OutputProfile use grant."""

    facts = _verified_release_facts(release)
    raw_basis = {
        "type": SUBJECT_EMISSION_POLICY_TYPE,
        "schemaVersion": SUBJECT_EMISSION_POLICY_VERSION,
        "version": version,
        "recordedAt": recorded_at,
        "recordedBy": recorded_by,
        "subjectConceptRelease": _release_pin(facts),
        "eligibility": list(eligibility),
    }
    basis = _normalized_policy_basis(raw_basis)
    content_digest = sha256_digest(_canonical_bytes(basis))
    policy = SubjectEmissionPolicy(
        {
            **basis,
            "id": f"urn:ref:subject-emission-policy:{content_digest.removeprefix('sha256:')}",
            "contentDigest": content_digest,
        }
    )
    policy._validate_for_facts(facts, reviews)
    return policy


_RESOLUTION_CONSTRUCTION_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class SubjectEmissionPolicyResolution:
    """Resolver-issued policy/grant result, short of accepted assignment use."""

    subject_concept: str
    facet: str
    assignment_role: str
    intended_product_use: str
    subject_concept_release: Mapping[str, Any]
    admission_review: Mapping[str, str]
    emission_policy: Mapping[str, str]
    output_profile: Mapping[str, str]
    eligibility: Mapping[str, Any]
    output_permission: Mapping[str, Any]
    resolution: str = "productPolicyAuthorized"

    def __init__(
        self,
        *,
        subject_concept: str,
        facet: str,
        assignment_role: str,
        intended_product_use: str,
        subject_concept_release: Mapping[str, Any],
        admission_review: Mapping[str, str],
        emission_policy: Mapping[str, str],
        output_profile: Mapping[str, str],
        eligibility: Mapping[str, Any],
        output_permission: Mapping[str, Any],
        resolution: str = "productPolicyAuthorized",
        _construction_token: object | None = None,
    ) -> None:
        if _construction_token is not _RESOLUTION_CONSTRUCTION_TOKEN:
            raise SubjectEmissionError(
                "SubjectEmissionPolicyResolution can only be created by "
                "resolve_subject_emission_policy()"
            )
        for field, value in (
            ("subject_concept", subject_concept),
            ("facet", facet),
            ("assignment_role", assignment_role),
            ("intended_product_use", intended_product_use),
            ("subject_concept_release", subject_concept_release),
            ("admission_review", admission_review),
            ("emission_policy", emission_policy),
            ("output_profile", output_profile),
            ("eligibility", eligibility),
            ("output_permission", output_permission),
            ("resolution", resolution),
        ):
            object.__setattr__(self, field, value)
        self.__post_init__()

    def __post_init__(self) -> None:
        subject_concept = _require_iri(self.subject_concept, "subject_concept")
        facet = _require_iri(self.facet, "facet")
        assignment_role = _require_iri(self.assignment_role, "assignment_role")
        intended_product_use = _require_iri(
            self.intended_product_use,
            "intended_product_use",
        )
        if self.resolution != "productPolicyAuthorized":
            raise SubjectEmissionError(
                "subject emission policy resolution must be productPolicyAuthorized"
            )
        subject_release = _normalized_release_pin(self.subject_concept_release)
        admission_review = _normalized_review_reference(
            self.admission_review,
            "admission_review",
        )
        emission_policy = _normalized_versioned_reference(
            self.emission_policy,
            "emission_policy",
        )
        output_profile = _normalized_versioned_reference(
            self.output_profile,
            "output_profile",
        )
        eligibility = _normalized_eligibility((self.eligibility,))[0]
        if (
            eligibility["subjectConcept"] != subject_concept
            or eligibility["facet"] != facet
            or eligibility["assignmentRole"] != assignment_role
            or eligibility["intendedProductUse"] != intended_product_use
            or eligibility["subjectAdmissionReview"] != admission_review
        ):
            raise SubjectEmissionError("subject emission policy eligibility is inconsistent")
        output_permission = cast(dict[str, Any], _plain(self.output_permission))
        _require_exact_fields(
            output_permission,
            {
                "facet",
                "assignmentRole",
                "subjectEmissionPolicy",
                "intendedProductUse",
                "candidateUse",
                "acceptedOutputUse",
            },
            "output_permission",
        )
        if (
            output_permission.get("facet") != facet
            or output_permission.get("assignmentRole") != assignment_role
            or output_permission.get("intendedProductUse") != intended_product_use
            or _normalized_versioned_reference(
                output_permission.get("subjectEmissionPolicy"),
                "output_permission.subjectEmissionPolicy",
            )
            != emission_policy
            or output_permission.get("candidateUse") is not True
            or output_permission.get("acceptedOutputUse") is not True
        ):
            raise SubjectEmissionError("subject emission policy output grant is inconsistent")
        for field, value in (
            ("subject_concept_release", subject_release),
            ("admission_review", admission_review),
            ("emission_policy", emission_policy),
            ("output_profile", output_profile),
            ("eligibility", eligibility),
            ("output_permission", output_permission),
        ):
            object.__setattr__(
                self,
                field,
                cast(Mapping[str, Any], deep_freeze_json(value)),
            )


def resolve_subject_emission_policy(
    *,
    output_profile: OutputProfile,
    policy: SubjectEmissionPolicy,
    release: SubjectConceptRelease,
    admission_reviews: Sequence[SubjectAdmissionReview | Mapping[str, Any]],
    subject_concept: str,
    facet: str,
    assignment_role: str,
    intended_product_use: str,
    resource_route: str,
) -> SubjectEmissionPolicyResolution:
    """Resolve eligibility and a grant without claiming accepted assignment use."""

    if not isinstance(output_profile, OutputProfile):
        raise SubjectEmissionError("output_profile must be an OutputProfile")
    if not isinstance(policy, SubjectEmissionPolicy):
        raise SubjectEmissionError("policy must be a SubjectEmissionPolicy")
    try:
        output_profile.payload()
    except ReferenceRuntimeError as error:
        raise SubjectEmissionError(str(error)) from error
    if output_profile.operational_state != "active":
        raise SubjectEmissionError("subject emission requires an active OutputProfile")
    profile = output_profile.enrichment_profile_record
    if profile is None:
        raise SubjectEmissionError("OutputProfile lacks its exact EnrichmentProfile")
    try:
        profile.require_compatible(
            facet=facet,
            assignment_role=assignment_role,
            resource_route=resource_route,
        )
    except ReferenceRuntimeError as error:
        raise SubjectEmissionError(str(error)) from error

    facts = _verified_release_facts(release)
    validated_reviews = policy._validate_for_facts(facts, admission_reviews)
    reviews_by_id = {review.identifier: review for review in validated_reviews}
    selector = {
        "subjectConcept": _require_iri(subject_concept, "subject_concept"),
        "facet": _require_iri(facet, "facet"),
        "assignmentRole": _require_iri(assignment_role, "assignment_role"),
        "intendedProductUse": _require_iri(
            intended_product_use,
            "intended_product_use",
        ),
    }
    matches = [
        row
        for row in policy.eligibility
        if all(row.get(field) == value for field, value in selector.items())
    ]
    if len(matches) != 1:
        raise SubjectEmissionError(
            "subject emission must match exactly one policy eligibility row"
        )
    eligibility = matches[0]
    review_id = cast(str, eligibility["subjectAdmissionReview"]["id"])
    review = reviews_by_id[review_id]
    try:
        output_permission = output_profile.select_subject_admission_grant(
            facet=selector["facet"],
            assignment_role=selector["assignmentRole"],
            resource_route=resource_route,
            subject_emission_policy=policy.reference,
            intended_product_use=selector["intendedProductUse"],
            accepted_output=True,
        )
    except ReferenceRuntimeError as error:
        raise SubjectEmissionError(str(error)) from error
    return SubjectEmissionPolicyResolution(
        subject_concept=review.subject_concept,
        facet=review.facet,
        assignment_role=selector["assignmentRole"],
        intended_product_use=selector["intendedProductUse"],
        subject_concept_release=cast(
            Mapping[str, Any],
            deep_freeze_json(_release_pin(facts)),
        ),
        admission_review=cast(
            Mapping[str, str],
            deep_freeze_json(review.reference),
        ),
        emission_policy=cast(
            Mapping[str, str],
            deep_freeze_json(policy.reference),
        ),
        output_profile=cast(
            Mapping[str, str],
            deep_freeze_json(output_profile.reference),
        ),
        eligibility=cast(
            Mapping[str, Any],
            deep_freeze_json(eligibility),
        ),
        output_permission=cast(
            Mapping[str, Any],
            deep_freeze_json(output_permission),
        ),
        _construction_token=_RESOLUTION_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "SUBJECT_EMISSION_POLICY_TYPE",
    "SUBJECT_EMISSION_POLICY_VERSION",
    "SubjectEmissionError",
    "SubjectEmissionPolicy",
    "SubjectEmissionPolicyResolution",
    "build_subject_emission_policy",
    "resolve_subject_emission_policy",
    "subject_emission_eligibility",
]
