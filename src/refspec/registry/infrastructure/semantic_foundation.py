"""Shared semantic records for the four vocabulary-atlas rings.

The records in this module describe facts, not permission.  They give source
concept releases and later relation artifacts one closed representation for
rights, evidence origin, and mapping assertions while leaving each semantic
ring in control of its relation vocabulary.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any, Literal, cast

from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.source_identity import (
    SourceIdentityError,
    require_aware_datetime_text,
)

SemanticRing = Literal["subject", "entity", "value", "legalIdentity"]
EvidenceClass = Literal[
    "machineQualified",
    "publisherAsserted",
    "operatorAdopted",
    "humanReviewed",
    "ruleGenerated",
]
EvidenceBasis = Literal[
    "statisticalInference",
    "sourceExplicit",
    "publisherCrosswalk",
    "operatorDirection",
    "editorialReview",
    "identifierAgreement",
    "deterministicDerivation",
    "nameEquality",
]
RightsStatus = Literal["stated", "notStated"]

SEMANTIC_RINGS = frozenset({"subject", "entity", "value", "legalIdentity"})
EVIDENCE_CLASSES = frozenset(
    {
        "machineQualified",
        "publisherAsserted",
        "operatorAdopted",
        "humanReviewed",
        "ruleGenerated",
    }
)

SUBJECT_EXACT_MATCH = "http://www.w3.org/2004/02/skos/core#exactMatch"
SUBJECT_CLOSE_MATCH = "http://www.w3.org/2004/02/skos/core#closeMatch"
SUBJECT_BROAD_MATCH = "http://www.w3.org/2004/02/skos/core#broadMatch"
SUBJECT_NARROW_MATCH = "http://www.w3.org/2004/02/skos/core#narrowMatch"
SUBJECT_RELATED_MATCH = "http://www.w3.org/2004/02/skos/core#relatedMatch"

ENTITY_SAME_IDENTITY = "urn:ref:relation:entity:sameIdentityAs"
ENTITY_SUCCESSOR = "urn:ref:relation:entity:successorOf"
ENTITY_RELATED = "urn:ref:relation:entity:relatedEntity"

VALUE_EXACT_CROSSWALK = "urn:ref:relation:value:exactCrosswalk"
VALUE_BROAD_CROSSWALK = "urn:ref:relation:value:broadCrosswalk"
VALUE_NARROW_CROSSWALK = "urn:ref:relation:value:narrowCrosswalk"
VALUE_REPLACED_BY = "urn:ref:relation:value:replacedBy"

LEGAL_CITES = "urn:ref:relation:legal-identity:cites"
LEGAL_AMENDS = "urn:ref:relation:legal-identity:amends"
LEGAL_AUTHORIZES = "urn:ref:relation:legal-identity:authorizes"
LEGAL_IMPLEMENTS = "urn:ref:relation:legal-identity:implements"

RING_RELATIONS: Mapping[SemanticRing, frozenset[str]] = MappingProxyType(
    {
        "subject": frozenset(
            {
                SUBJECT_EXACT_MATCH,
                SUBJECT_CLOSE_MATCH,
                SUBJECT_BROAD_MATCH,
                SUBJECT_NARROW_MATCH,
                SUBJECT_RELATED_MATCH,
            }
        ),
        "entity": frozenset(
            {
                ENTITY_SAME_IDENTITY,
                ENTITY_SUCCESSOR,
                ENTITY_RELATED,
            }
        ),
        "value": frozenset(
            {
                VALUE_EXACT_CROSSWALK,
                VALUE_BROAD_CROSSWALK,
                VALUE_NARROW_CROSSWALK,
                VALUE_REPLACED_BY,
            }
        ),
        "legalIdentity": frozenset(
            {
                LEGAL_CITES,
                LEGAL_AMENDS,
                LEGAL_AUTHORIZES,
                LEGAL_IMPLEMENTS,
            }
        ),
    }
)

_EVIDENCE_BASES_BY_CLASS: Mapping[EvidenceClass, frozenset[str]] = MappingProxyType(
    {
        "machineQualified": frozenset({"statisticalInference"}),
        "publisherAsserted": frozenset({"sourceExplicit", "publisherCrosswalk"}),
        "operatorAdopted": frozenset({"operatorDirection"}),
        "humanReviewed": frozenset({"editorialReview", "identifierAgreement"}),
        "ruleGenerated": frozenset({"deterministicDerivation", "nameEquality"}),
    }
)
_ENTITY_IDENTITY_BASES = frozenset(
    {
        "sourceExplicit",
        "publisherCrosswalk",
        "editorialReview",
        "identifierAgreement",
    }
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_POLICY_FIELDS = frozenset(
    {
        "acceptedOutputAllowed",
        "acceptedOutputUseAuthorized",
        "admission",
        "admissionReview",
        "admitted",
        "authorization",
        "authorized",
        "candidateLookupAllowed",
        "candidateUseAuthorized",
        "emissionAuthorized",
        "outputProfile",
        "permission",
        "productPolicy",
        "usageCeiling",
    }
)


class SemanticFoundationError(ValueError):
    """A shared semantic record is incomplete or changes its meaning."""


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SemanticFoundationError(f"{label} must be non-empty text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise SemanticFoundationError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise SemanticFoundationError(f"{label} must not contain credentials")
    return iri


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SemanticFoundationError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_datetime(value: object, label: str) -> str:
    text = _require_text(value, label)
    try:
        return require_aware_datetime_text(text, label=label)
    except SourceIdentityError as error:
        raise SemanticFoundationError(str(error)) from error


def _require_date(value: object, label: str) -> str:
    text = _require_text(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise SemanticFoundationError(f"{label} must be an ISO 8601 calendar date") from error
    if parsed.isoformat() != text:
        raise SemanticFoundationError(f"{label} must be an ISO 8601 calendar date")
    return text


def _require_ring(value: object, label: str) -> SemanticRing:
    if value not in SEMANTIC_RINGS:
        raise SemanticFoundationError(f"{label} must be subject, entity, value, or legalIdentity")
    return cast(SemanticRing, value)


def _require_unique_iris(
    value: object,
    label: str,
    *,
    minimum: int = 1,
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SemanticFoundationError(f"{label} must be an array")
    result = tuple(_require_iri(item, f"{label}[{index}]") for index, item in enumerate(value))
    if len(result) < minimum or len(set(result)) != len(result):
        raise SemanticFoundationError(f"{label} must contain at least {minimum} unique IRIs")
    return result


def _require_unique_texts(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SemanticFoundationError(f"{label} must be an array")
    result = tuple(_require_text(item, f"{label}[{index}]") for index, item in enumerate(value))
    if len(set(result)) != len(result):
        raise SemanticFoundationError(f"{label} must contain unique text values")
    return result


def _forbid_policy_fields(value: Any, *, label: str) -> None:
    if isinstance(value, Mapping):
        forbidden = sorted(set(value) & _FORBIDDEN_POLICY_FIELDS)
        if forbidden:
            raise SemanticFoundationError(f"{label} contains admission or permission fields {forbidden!r}")
        for key, child in value.items():
            _forbid_policy_fields(child, label=f"{label}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            _forbid_policy_fields(child, label=f"{label}[{index}]")


def _require_closed_fields(
    value: Mapping[str, Any],
    *,
    label: str,
    required: set[str],
    optional: set[str] = frozenset(),
) -> None:
    fields = set(value)
    missing = sorted(required - fields)
    unknown = sorted(fields - required - set(optional))
    if missing or unknown:
        raise SemanticFoundationError(f"{label} has missing fields {missing!r} and unknown fields {unknown!r}")


@dataclass(frozen=True, slots=True)
class RightsMetadata:
    """Pinned rights facts for one source release, never a use permission."""

    rights_status: RightsStatus
    source_artifact: str
    source_digest: str
    rights_statement: str | None = None
    license: str | None = None
    rights_holders: tuple[str, ...] = ()
    attribution: str | None = None

    def __post_init__(self) -> None:
        if self.rights_status not in {"stated", "notStated"}:
            raise SemanticFoundationError("rights_metadata.rightsStatus must be stated or notStated")
        object.__setattr__(
            self,
            "source_artifact",
            _require_iri(self.source_artifact, "rights_metadata.sourceArtifact"),
        )
        object.__setattr__(
            self,
            "source_digest",
            _require_digest(self.source_digest, "rights_metadata.sourceDigest"),
        )
        if self.rights_status == "stated":
            if self.rights_statement is None:
                raise SemanticFoundationError("stated rights metadata requires rightsStatement")
            object.__setattr__(
                self,
                "rights_statement",
                _require_iri(self.rights_statement, "rights_metadata.rightsStatement"),
            )
            if self.license is not None:
                object.__setattr__(self, "license", _require_iri(self.license, "rights_metadata.license"))
            object.__setattr__(
                self,
                "rights_holders",
                _require_unique_texts(self.rights_holders, "rights_metadata.rightsHolders"),
            )
            if self.attribution is not None:
                object.__setattr__(
                    self,
                    "attribution",
                    _require_text(self.attribution, "rights_metadata.attribution"),
                )
        elif any(
            value is not None and value != ()
            for value in (
                self.rights_statement,
                self.license,
                self.rights_holders,
                self.attribution,
            )
        ):
            raise SemanticFoundationError("notStated rights metadata cannot imply unstated rights facts")

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> RightsMetadata:
        if not isinstance(value, Mapping):
            raise SemanticFoundationError("rights_metadata must be an object")
        _forbid_policy_fields(value, label="rights_metadata")
        _require_closed_fields(
            value,
            label="rights_metadata",
            required={"type", "rightsStatus", "sourceArtifact", "sourceDigest"},
            optional={"rightsStatement", "license", "rightsHolders", "attribution"},
        )
        if value.get("type") != "RightsMetadata":
            raise SemanticFoundationError("rights_metadata.type must be RightsMetadata")
        holders = value.get("rightsHolders", ())
        return cls(
            rights_status=cast(RightsStatus, value.get("rightsStatus")),
            source_artifact=cast(str, value.get("sourceArtifact")),
            source_digest=cast(str, value.get("sourceDigest")),
            rights_statement=cast(str | None, value.get("rightsStatement")),
            license=cast(str | None, value.get("license")),
            rights_holders=cast(tuple[str, ...], holders),
            attribution=cast(str | None, value.get("attribution")),
        )

    def as_record(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": "RightsMetadata",
            "rightsStatus": self.rights_status,
            "sourceArtifact": self.source_artifact,
            "sourceDigest": self.source_digest,
        }
        if self.rights_statement is not None:
            result["rightsStatement"] = self.rights_statement
        if self.license is not None:
            result["license"] = self.license
        if self.rights_holders:
            result["rightsHolders"] = list(self.rights_holders)
        if self.attribution is not None:
            result["attribution"] = self.attribution
        return result


@dataclass(frozen=True, slots=True)
class EvidenceAssertion:
    """One typed statement about how evidence was produced or reviewed."""

    identifier: str
    semantic_ring: SemanticRing
    evidence_class: EvidenceClass
    basis: EvidenceBasis
    asserted_by: str
    asserted_at: str
    evidence: tuple[str, ...]
    qualification_policy: str | None = None
    validation_receipts: tuple[str, ...] = ()
    source_artifact: str | None = None
    source_digest: str | None = None
    adopted_evidence: str | None = None
    review_decision: str | None = None
    generator: str | None = None
    generator_inputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _require_iri(self.identifier, "evidence_assertion.id"))
        object.__setattr__(
            self,
            "semantic_ring",
            _require_ring(self.semantic_ring, "evidence_assertion.semanticRing"),
        )
        if self.evidence_class not in EVIDENCE_CLASSES:
            raise SemanticFoundationError("evidence_assertion.evidenceClass is unsupported")
        allowed_bases = _EVIDENCE_BASES_BY_CLASS[cast(EvidenceClass, self.evidence_class)]
        if self.basis not in allowed_bases:
            raise SemanticFoundationError(
                f"evidence_assertion basis {self.basis!r} does not match {self.evidence_class}"
            )
        object.__setattr__(self, "asserted_by", _require_iri(self.asserted_by, "evidence_assertion.assertedBy"))
        object.__setattr__(
            self,
            "asserted_at",
            _require_datetime(self.asserted_at, "evidence_assertion.assertedAt"),
        )
        object.__setattr__(
            self,
            "evidence",
            _require_unique_iris(self.evidence, "evidence_assertion.evidence"),
        )

        if self.evidence_class == "machineQualified":
            if self.qualification_policy is None:
                raise SemanticFoundationError("machineQualified evidence requires qualificationPolicy")
            object.__setattr__(
                self,
                "qualification_policy",
                _require_iri(self.qualification_policy, "evidence_assertion.qualificationPolicy"),
            )
            object.__setattr__(
                self,
                "validation_receipts",
                _require_unique_iris(
                    self.validation_receipts,
                    "evidence_assertion.validationReceipts",
                    minimum=2,
                ),
            )
        elif self.evidence_class == "publisherAsserted":
            if self.source_artifact is None or self.source_digest is None:
                raise SemanticFoundationError("publisherAsserted evidence requires a pinned sourceArtifact")
            object.__setattr__(
                self,
                "source_artifact",
                _require_iri(self.source_artifact, "evidence_assertion.sourceArtifact"),
            )
            object.__setattr__(
                self,
                "source_digest",
                _require_digest(self.source_digest, "evidence_assertion.sourceDigest"),
            )
        elif self.evidence_class == "operatorAdopted":
            if self.adopted_evidence is None:
                raise SemanticFoundationError("operatorAdopted evidence requires adoptedEvidence")
            object.__setattr__(
                self,
                "adopted_evidence",
                _require_iri(self.adopted_evidence, "evidence_assertion.adoptedEvidence"),
            )
        elif self.evidence_class == "humanReviewed":
            if self.review_decision is None:
                raise SemanticFoundationError("humanReviewed evidence requires reviewDecision")
            object.__setattr__(
                self,
                "review_decision",
                _require_iri(self.review_decision, "evidence_assertion.reviewDecision"),
            )
        elif self.evidence_class == "ruleGenerated":
            if self.generator is None:
                raise SemanticFoundationError("ruleGenerated evidence requires generator")
            object.__setattr__(self, "generator", _require_iri(self.generator, "evidence_assertion.generator"))
            object.__setattr__(
                self,
                "generator_inputs",
                _require_unique_iris(self.generator_inputs, "evidence_assertion.generatorInputs"),
            )

        forbidden_specializations = {
            "machineQualified": (
                self.source_artifact,
                self.source_digest,
                self.adopted_evidence,
                self.review_decision,
                self.generator,
                self.generator_inputs,
            ),
            "publisherAsserted": (
                self.qualification_policy,
                self.validation_receipts,
                self.adopted_evidence,
                self.review_decision,
                self.generator,
                self.generator_inputs,
            ),
            "operatorAdopted": (
                self.qualification_policy,
                self.validation_receipts,
                self.source_artifact,
                self.source_digest,
                self.review_decision,
                self.generator,
                self.generator_inputs,
            ),
            "humanReviewed": (
                self.qualification_policy,
                self.validation_receipts,
                self.source_artifact,
                self.source_digest,
                self.adopted_evidence,
                self.generator,
                self.generator_inputs,
            ),
            "ruleGenerated": (
                self.qualification_policy,
                self.validation_receipts,
                self.source_artifact,
                self.source_digest,
                self.adopted_evidence,
                self.review_decision,
            ),
        }
        extras = forbidden_specializations[self.evidence_class]
        if any(value is not None and value != () for value in extras):
            raise SemanticFoundationError(f"evidence_assertion contains fields outside the {self.evidence_class} shape")

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> EvidenceAssertion:
        if not isinstance(value, Mapping):
            raise SemanticFoundationError("evidence_assertion must be an object")
        _forbid_policy_fields(value, label="evidence_assertion")
        evidence_class = value.get("evidenceClass")
        if evidence_class not in EVIDENCE_CLASSES:
            raise SemanticFoundationError("evidence_assertion.evidenceClass is unsupported")
        specialized_fields = {
            "machineQualified": {"qualificationPolicy", "validationReceipts"},
            "publisherAsserted": {"sourceArtifact", "sourceDigest"},
            "operatorAdopted": {"adoptedEvidence"},
            "humanReviewed": {"reviewDecision"},
            "ruleGenerated": {"generator", "generatorInputs"},
        }[cast(EvidenceClass, evidence_class)]
        _require_closed_fields(
            value,
            label="evidence_assertion",
            required={
                "id",
                "type",
                "semanticRing",
                "evidenceClass",
                "basis",
                "assertedBy",
                "assertedAt",
                "evidence",
                *specialized_fields,
            },
        )
        if value.get("type") != "EvidenceAssertion":
            raise SemanticFoundationError("evidence_assertion.type must be EvidenceAssertion")
        return cls(
            identifier=cast(str, value.get("id")),
            semantic_ring=cast(SemanticRing, value.get("semanticRing")),
            evidence_class=cast(EvidenceClass, evidence_class),
            basis=cast(EvidenceBasis, value.get("basis")),
            asserted_by=cast(str, value.get("assertedBy")),
            asserted_at=cast(str, value.get("assertedAt")),
            evidence=cast(tuple[str, ...], value.get("evidence")),
            qualification_policy=cast(str | None, value.get("qualificationPolicy")),
            validation_receipts=cast(tuple[str, ...], value.get("validationReceipts", ())),
            source_artifact=cast(str | None, value.get("sourceArtifact")),
            source_digest=cast(str | None, value.get("sourceDigest")),
            adopted_evidence=cast(str | None, value.get("adoptedEvidence")),
            review_decision=cast(str | None, value.get("reviewDecision")),
            generator=cast(str | None, value.get("generator")),
            generator_inputs=cast(tuple[str, ...], value.get("generatorInputs", ())),
        )

    def as_record(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.identifier,
            "type": "EvidenceAssertion",
            "semanticRing": self.semantic_ring,
            "evidenceClass": self.evidence_class,
            "basis": self.basis,
            "assertedBy": self.asserted_by,
            "assertedAt": self.asserted_at,
            "evidence": list(self.evidence),
        }
        if self.evidence_class == "machineQualified":
            result["qualificationPolicy"] = self.qualification_policy
            result["validationReceipts"] = list(self.validation_receipts)
        elif self.evidence_class == "publisherAsserted":
            result["sourceArtifact"] = self.source_artifact
            result["sourceDigest"] = self.source_digest
        elif self.evidence_class == "operatorAdopted":
            result["adoptedEvidence"] = self.adopted_evidence
        elif self.evidence_class == "humanReviewed":
            result["reviewDecision"] = self.review_decision
        else:
            result["generator"] = self.generator
            result["generatorInputs"] = list(self.generator_inputs)
        return result


@dataclass(frozen=True, slots=True)
class MappingAssertion:
    """One ring-scoped relation assertion supported by typed evidence."""

    identifier: str
    semantic_ring: SemanticRing
    source_concept: str
    target_concept: str
    source_release: str
    target_release: str
    relation: str
    evidence: tuple[str, ...]
    asserted_at: str
    context: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _require_iri(self.identifier, "mapping_assertion.id"))
        ring = _require_ring(self.semantic_ring, "mapping_assertion.semanticRing")
        object.__setattr__(self, "semantic_ring", ring)
        object.__setattr__(
            self,
            "source_concept",
            _require_iri(self.source_concept, "mapping_assertion.sourceConcept"),
        )
        object.__setattr__(
            self,
            "target_concept",
            _require_iri(self.target_concept, "mapping_assertion.targetConcept"),
        )
        if self.source_concept == self.target_concept:
            raise SemanticFoundationError("mapping_assertion endpoints must be distinct concepts")
        object.__setattr__(
            self,
            "source_release",
            _require_iri(self.source_release, "mapping_assertion.sourceRelease"),
        )
        object.__setattr__(
            self,
            "target_release",
            _require_iri(self.target_release, "mapping_assertion.targetRelease"),
        )
        relation = _require_iri(self.relation, "mapping_assertion.relation")
        if relation not in RING_RELATIONS[ring]:
            raise SemanticFoundationError(f"mapping_assertion relation is not valid for the {ring} ring")
        object.__setattr__(self, "relation", relation)
        object.__setattr__(
            self,
            "evidence",
            _require_unique_iris(self.evidence, "mapping_assertion.evidence"),
        )
        object.__setattr__(
            self,
            "asserted_at",
            _require_datetime(self.asserted_at, "mapping_assertion.assertedAt"),
        )
        object.__setattr__(self, "context", self._validated_context(self.context))

    def _validated_context(self, value: Mapping[str, str] | None) -> Mapping[str, str] | None:
        if self.semantic_ring in {"subject", "entity"}:
            if value is not None:
                raise SemanticFoundationError(f"{self.semantic_ring} mapping assertions do not accept context")
            return None
        if not isinstance(value, Mapping):
            raise SemanticFoundationError(f"{self.semantic_ring} mapping assertions require context")
        context = dict(value)
        if self.semantic_ring == "value":
            _require_closed_fields(
                context,
                label="mapping_assertion.context",
                required={"sourceEdition", "targetEdition", "effectiveFrom"},
                optional={"effectiveThrough"},
            )
            context["sourceEdition"] = _require_text(
                context.get("sourceEdition"),
                "mapping_assertion.context.sourceEdition",
            )
            context["targetEdition"] = _require_text(
                context.get("targetEdition"),
                "mapping_assertion.context.targetEdition",
            )
            context["effectiveFrom"] = _require_date(
                context.get("effectiveFrom"),
                "mapping_assertion.context.effectiveFrom",
            )
            if "effectiveThrough" in context:
                context["effectiveThrough"] = _require_date(
                    context.get("effectiveThrough"),
                    "mapping_assertion.context.effectiveThrough",
                )
                if context["effectiveThrough"] < context["effectiveFrom"]:
                    raise SemanticFoundationError("mapping_assertion effectiveThrough precedes effectiveFrom")
        else:
            _require_closed_fields(
                context,
                label="mapping_assertion.context",
                required={"effectiveAt"},
            )
            context["effectiveAt"] = _require_date(
                context.get("effectiveAt"),
                "mapping_assertion.context.effectiveAt",
            )
        return MappingProxyType(context)

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> MappingAssertion:
        if not isinstance(value, Mapping):
            raise SemanticFoundationError("mapping_assertion must be an object")
        _forbid_policy_fields(value, label="mapping_assertion")
        ring = _require_ring(value.get("semanticRing"), "mapping_assertion.semanticRing")
        required = {
            "id",
            "type",
            "semanticRing",
            "sourceConcept",
            "targetConcept",
            "sourceRelease",
            "targetRelease",
            "relation",
            "evidence",
            "assertedAt",
        }
        if ring in {"value", "legalIdentity"}:
            required.add("context")
        _require_closed_fields(value, label="mapping_assertion", required=required)
        if value.get("type") != "MappingAssertion":
            raise SemanticFoundationError("mapping_assertion.type must be MappingAssertion")
        context = value.get("context")
        return cls(
            identifier=cast(str, value.get("id")),
            semantic_ring=ring,
            source_concept=cast(str, value.get("sourceConcept")),
            target_concept=cast(str, value.get("targetConcept")),
            source_release=cast(str, value.get("sourceRelease")),
            target_release=cast(str, value.get("targetRelease")),
            relation=cast(str, value.get("relation")),
            evidence=cast(tuple[str, ...], value.get("evidence")),
            asserted_at=cast(str, value.get("assertedAt")),
            context=(cast(Mapping[str, str], context) if isinstance(context, Mapping) else None),
        )

    def validate_evidence(self, evidence_by_id: Mapping[str, EvidenceAssertion]) -> None:
        missing = sorted(set(self.evidence) - set(evidence_by_id))
        if missing:
            raise SemanticFoundationError(f"mapping_assertion cites unknown evidence {missing!r}")
        supporting = tuple(evidence_by_id[identifier] for identifier in self.evidence)
        if any(value.semantic_ring != self.semantic_ring for value in supporting):
            raise SemanticFoundationError("mapping_assertion evidence crosses semantic rings")
        if self.semantic_ring == "entity" and self.relation == ENTITY_SAME_IDENTITY:
            if any(value.basis == "nameEquality" for value in supporting):
                raise SemanticFoundationError("entity identity cannot be supported by name equality")
            if not any(value.basis in _ENTITY_IDENTITY_BASES for value in supporting):
                raise SemanticFoundationError(
                    "entity identity requires identifiers, publisher crosswalk, source assertion, or human review"
                )
        if any(value.evidence_class == "ruleGenerated" for value in supporting):
            raise SemanticFoundationError("ruleGenerated evidence is candidate provenance, not mapping support")

    def as_record(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.identifier,
            "type": "MappingAssertion",
            "semanticRing": self.semantic_ring,
            "sourceConcept": self.source_concept,
            "targetConcept": self.target_concept,
            "sourceRelease": self.source_release,
            "targetRelease": self.target_release,
            "relation": self.relation,
            "evidence": list(self.evidence),
            "assertedAt": self.asserted_at,
        }
        if self.context is not None:
            result["context"] = dict(self.context)
        return result


def validate_rights_metadata(value: RightsMetadata | Mapping[str, Any]) -> RightsMetadata:
    """Return one validated rights record."""

    if isinstance(value, RightsMetadata):
        return RightsMetadata.from_record(value.as_record())
    return RightsMetadata.from_record(value)


def validate_rights_metadata_records(
    values: Sequence[RightsMetadata | Mapping[str, Any]],
) -> tuple[RightsMetadata, ...]:
    """Validate one rights fact per distinct source artifact."""

    result: list[RightsMetadata] = []
    source_artifacts: set[str] = set()
    for value in values:
        rights = validate_rights_metadata(value)
        if rights.source_artifact in source_artifacts:
            raise SemanticFoundationError("rights_metadata repeats a sourceArtifact")
        source_artifacts.add(rights.source_artifact)
        result.append(rights)
    return tuple(sorted(result, key=lambda value: value.source_artifact))


def validate_evidence_assertions(
    values: Sequence[EvidenceAssertion | Mapping[str, Any]],
    *,
    semantic_ring: SemanticRing | None = None,
) -> tuple[EvidenceAssertion, ...]:
    """Validate, deduplicate, and deterministically order evidence records."""

    expected_ring = None if semantic_ring is None else _require_ring(semantic_ring, "semantic_ring")
    result: list[EvidenceAssertion] = []
    identifiers: set[str] = set()
    for value in values:
        assertion = value if isinstance(value, EvidenceAssertion) else EvidenceAssertion.from_record(value)
        if assertion.identifier in identifiers:
            raise SemanticFoundationError("evidence_assertions repeats an id")
        if expected_ring is not None and assertion.semantic_ring != expected_ring:
            raise SemanticFoundationError("evidence_assertion semanticRing differs from the requested ring")
        identifiers.add(assertion.identifier)
        result.append(assertion)
    by_id = {value.identifier: value for value in result}
    for assertion in result:
        if assertion.evidence_class != "operatorAdopted":
            continue
        adopted = by_id.get(cast(str, assertion.adopted_evidence))
        if adopted is None or adopted.identifier == assertion.identifier:
            raise SemanticFoundationError("operatorAdopted evidence must cite another evidence assertion")
        if adopted.semantic_ring != assertion.semantic_ring:
            raise SemanticFoundationError("operatorAdopted evidence crosses semantic rings")
    return tuple(sorted(result, key=lambda value: value.identifier))


def validate_mapping_assertions(
    values: Sequence[MappingAssertion | Mapping[str, Any]],
    *,
    evidence_assertions: Sequence[EvidenceAssertion | Mapping[str, Any]],
    semantic_ring: SemanticRing | None = None,
) -> tuple[MappingAssertion, ...]:
    """Validate mappings against their ring vocabulary and exact evidence set."""

    expected_ring = None if semantic_ring is None else _require_ring(semantic_ring, "semantic_ring")
    evidence = validate_evidence_assertions(evidence_assertions)
    evidence_by_id = {value.identifier: value for value in evidence}
    result: list[MappingAssertion] = []
    identifiers: set[str] = set()
    for value in values:
        assertion = value if isinstance(value, MappingAssertion) else MappingAssertion.from_record(value)
        if assertion.identifier in identifiers:
            raise SemanticFoundationError("mapping_assertions repeats an id")
        if expected_ring is not None and assertion.semantic_ring != expected_ring:
            raise SemanticFoundationError("mapping_assertion semanticRing differs from the requested ring")
        assertion.validate_evidence(evidence_by_id)
        identifiers.add(assertion.identifier)
        result.append(assertion)
    return tuple(sorted(result, key=lambda value: value.identifier))


__all__ = [
    "ENTITY_RELATED",
    "ENTITY_SAME_IDENTITY",
    "ENTITY_SUCCESSOR",
    "EVIDENCE_CLASSES",
    "LEGAL_AMENDS",
    "LEGAL_AUTHORIZES",
    "LEGAL_CITES",
    "LEGAL_IMPLEMENTS",
    "RING_RELATIONS",
    "SEMANTIC_RINGS",
    "SUBJECT_BROAD_MATCH",
    "SUBJECT_CLOSE_MATCH",
    "SUBJECT_EXACT_MATCH",
    "SUBJECT_NARROW_MATCH",
    "SUBJECT_RELATED_MATCH",
    "VALUE_BROAD_CROSSWALK",
    "VALUE_EXACT_CROSSWALK",
    "VALUE_NARROW_CROSSWALK",
    "VALUE_REPLACED_BY",
    "EvidenceAssertion",
    "EvidenceBasis",
    "EvidenceClass",
    "MappingAssertion",
    "RightsMetadata",
    "RightsStatus",
    "SemanticFoundationError",
    "SemanticRing",
    "validate_evidence_assertions",
    "validate_mapping_assertions",
    "validate_rights_metadata",
    "validate_rights_metadata_records",
]
