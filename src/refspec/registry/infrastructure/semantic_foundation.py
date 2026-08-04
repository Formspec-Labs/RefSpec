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

from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes, sha256_digest
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.source_identity import (
    SourceIdentityError,
    require_aware_datetime_text,
)

SemanticRing = Literal["subject", "entity", "value", "legalIdentity"]
EvidenceClass = Literal[
    "machineQualified",
    "machineReviewed",
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
EvidenceUseCeiling = Literal[
    "searchOnly",
    "localOperationalUse",
    "productPolicyRequired",
    "notApplicable",
]
RightsStatus = Literal["stated", "notStated"]

MACHINE_EVIDENCE_PROOF_VERSION = "1.0"
SEMANTIC_RINGS = frozenset({"subject", "entity", "value", "legalIdentity"})
EVIDENCE_CLASSES = frozenset(
    {
        "machineQualified",
        "machineReviewed",
        "publisherAsserted",
        "operatorAdopted",
        "humanReviewed",
        "ruleGenerated",
    }
)
EVIDENCE_USE_CEILINGS: Mapping[EvidenceClass, EvidenceUseCeiling] = MappingProxyType(
    {
        "machineQualified": "searchOnly",
        "machineReviewed": "notApplicable",
        "publisherAsserted": "searchOnly",
        "operatorAdopted": "localOperationalUse",
        "humanReviewed": "productPolicyRequired",
        "ruleGenerated": "notApplicable",
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
        "machineReviewed": frozenset({"statisticalInference"}),
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
    return tuple(sorted(result))


def _require_unique_texts(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SemanticFoundationError(f"{label} must be an array")
    result = tuple(_require_text(item, f"{label}[{index}]") for index, item in enumerate(value))
    if len(set(result)) != len(result):
        raise SemanticFoundationError(f"{label} must contain unique text values")
    return tuple(sorted(result))


def _content_digest(value: Mapping[str, Any]) -> str:
    return sha256_digest(canonical_json_bytes(value))


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


def _validated_relation_context(
    semantic_ring: SemanticRing,
    value: Mapping[str, str] | None,
    *,
    label: str,
) -> Mapping[str, str] | None:
    if semantic_ring in {"subject", "entity"}:
        if value is not None:
            raise SemanticFoundationError(f"{semantic_ring} relation records do not accept context")
        return None
    if not isinstance(value, Mapping):
        raise SemanticFoundationError(f"{semantic_ring} relation records require context")
    context = dict(value)
    if semantic_ring == "value":
        _require_closed_fields(
            context,
            label=label,
            required={"sourceEdition", "targetEdition", "effectiveFrom"},
            optional={"effectiveThrough"},
        )
        context["sourceEdition"] = _require_text(
            context.get("sourceEdition"),
            f"{label}.sourceEdition",
        )
        context["targetEdition"] = _require_text(
            context.get("targetEdition"),
            f"{label}.targetEdition",
        )
        context["effectiveFrom"] = _require_date(
            context.get("effectiveFrom"),
            f"{label}.effectiveFrom",
        )
        if "effectiveThrough" in context:
            context["effectiveThrough"] = _require_date(
                context.get("effectiveThrough"),
                f"{label}.effectiveThrough",
            )
            if context["effectiveThrough"] < context["effectiveFrom"]:
                raise SemanticFoundationError(f"{label}.effectiveThrough precedes effectiveFrom")
    else:
        _require_closed_fields(
            context,
            label=label,
            required={"effectiveAt"},
        )
        context["effectiveAt"] = _require_date(
            context.get("effectiveAt"),
            f"{label}.effectiveAt",
        )
    return MappingProxyType(context)


def validate_machine_evidence_proof_pin(
    value: Mapping[str, Any],
    *,
    semantic_ring: SemanticRing | None = None,
) -> dict[str, Any]:
    """Validate one adapter-produced, content-derived machine proof record.

    The shared shape closes proof identity, exact source bytes, candidate and
    validation identities, endpoints, releases, and relation.  ``proofKind``
    and ``proofDetails`` remain adapter-defined so each semantic ring can use
    its own proof semantics without changing the relation-bundle foundation.
    """

    if not isinstance(value, Mapping):
        raise SemanticFoundationError("machine_evidence_proof must be an object")
    _forbid_policy_fields(value, label="machine_evidence_proof")
    _require_closed_fields(
        value,
        label="machine_evidence_proof",
        required={
            "id",
            "type",
            "schemaVersion",
            "contentDigest",
            "proofAdapter",
            "semanticRing",
            "evidenceClass",
            "proofKind",
            "proofSource",
            "candidate",
            "validations",
            "proofDetails",
            "sourceConcept",
            "targetConcept",
            "sourceRelease",
            "targetRelease",
            "relation",
        },
        optional={"context", "qualificationPolicy"},
    )
    if value.get("type") != "MachineEvidenceProof":
        raise SemanticFoundationError("machine_evidence_proof.type must be MachineEvidenceProof")
    if value.get("schemaVersion") != MACHINE_EVIDENCE_PROOF_VERSION:
        raise SemanticFoundationError("machine_evidence_proof schemaVersion is unsupported")
    proof_adapter = _require_iri(value.get("proofAdapter"), "machine_evidence_proof.proofAdapter")

    ring = _require_ring(value.get("semanticRing"), "machine_evidence_proof.semanticRing")
    if semantic_ring is not None and ring != _require_ring(semantic_ring, "semantic_ring"):
        raise SemanticFoundationError("machine_evidence_proof semanticRing differs from the requested ring")
    evidence_class = value.get("evidenceClass")
    if evidence_class not in {"machineQualified", "machineReviewed"}:
        raise SemanticFoundationError(
            "machine_evidence_proof.evidenceClass must be machineQualified or machineReviewed"
        )
    proof_kind = _require_text(value.get("proofKind"), "machine_evidence_proof.proofKind")
    if proof_kind != proof_kind.strip():
        raise SemanticFoundationError("machine_evidence_proof.proofKind must be trimmed text")

    proof_source_value = value.get("proofSource")
    if not isinstance(proof_source_value, Mapping):
        raise SemanticFoundationError("machine_evidence_proof.proofSource must be an object")
    _require_closed_fields(
        proof_source_value,
        label="machine_evidence_proof.proofSource",
        required={"type", "id", "contentDigest", "fileDigest"},
    )
    proof_source = {
        "type": _require_text(proof_source_value.get("type"), "machine_evidence_proof.proofSource.type"),
        "id": _require_iri(proof_source_value.get("id"), "machine_evidence_proof.proofSource.id"),
        "contentDigest": _require_digest(
            proof_source_value.get("contentDigest"),
            "machine_evidence_proof.proofSource.contentDigest",
        ),
        "fileDigest": _require_digest(
            proof_source_value.get("fileDigest"),
            "machine_evidence_proof.proofSource.fileDigest",
        ),
    }

    candidate_value = value.get("candidate")
    if not isinstance(candidate_value, Mapping):
        raise SemanticFoundationError("machine_evidence_proof.candidate must be an object")
    _require_closed_fields(
        candidate_value,
        label="machine_evidence_proof.candidate",
        required={"id", "contentDigest"},
    )
    candidate = {
        "id": _require_iri(candidate_value.get("id"), "machine_evidence_proof.candidate.id"),
        "contentDigest": _require_digest(
            candidate_value.get("contentDigest"),
            "machine_evidence_proof.candidate.contentDigest",
        ),
    }

    validations_value = value.get("validations")
    if not isinstance(validations_value, Sequence) or isinstance(validations_value, (str, bytes)):
        raise SemanticFoundationError("machine_evidence_proof.validations must be an array")
    validations: list[dict[str, str]] = []
    for index, row in enumerate(validations_value):
        if not isinstance(row, Mapping):
            raise SemanticFoundationError(f"machine_evidence_proof.validations[{index}] must be an object")
        _require_closed_fields(
            row,
            label=f"machine_evidence_proof.validations[{index}]",
            required={"id", "contentDigest"},
        )
        validations.append(
            {
                "id": _require_iri(row.get("id"), f"machine_evidence_proof.validations[{index}].id"),
                "contentDigest": _require_digest(
                    row.get("contentDigest"),
                    f"machine_evidence_proof.validations[{index}].contentDigest",
                ),
            }
        )
    validation_ids = [row["id"] for row in validations]
    required_count = 2 if evidence_class == "machineQualified" else 1
    if len(validations) < required_count or len(validation_ids) != len(set(validation_ids)):
        raise SemanticFoundationError(
            f"machine_evidence_proof.validations must contain at least {required_count} unique records"
        )
    if evidence_class == "machineReviewed" and len(validations) != 1:
        raise SemanticFoundationError("machineReviewed proof requires exactly one validation record")
    validations.sort(key=lambda row: row["id"])

    proof_details_value = value.get("proofDetails")
    if not isinstance(proof_details_value, Mapping):
        raise SemanticFoundationError("machine_evidence_proof.proofDetails must be an object")
    proof_details = dict(proof_details_value)
    try:
        canonical_json_bytes(proof_details)
    except (TypeError, ValueError) as error:
        raise SemanticFoundationError("machine_evidence_proof.proofDetails must be canonical JSON data") from error

    source_concept = _require_iri(value.get("sourceConcept"), "machine_evidence_proof.sourceConcept")
    target_concept = _require_iri(value.get("targetConcept"), "machine_evidence_proof.targetConcept")
    source_release = _require_iri(value.get("sourceRelease"), "machine_evidence_proof.sourceRelease")
    target_release = _require_iri(value.get("targetRelease"), "machine_evidence_proof.targetRelease")
    relation = _require_iri(value.get("relation"), "machine_evidence_proof.relation")
    if relation not in RING_RELATIONS[ring]:
        raise SemanticFoundationError(f"machine_evidence_proof relation is not valid for the {ring} ring")
    context_value = value.get("context")
    context = _validated_relation_context(
        ring,
        cast(Mapping[str, str], context_value) if isinstance(context_value, Mapping) else None,
        label="machine_evidence_proof.context",
    )

    basis: dict[str, Any] = {
        "type": "MachineEvidenceProof",
        "schemaVersion": MACHINE_EVIDENCE_PROOF_VERSION,
        "proofAdapter": proof_adapter,
        "semanticRing": ring,
        "evidenceClass": evidence_class,
        "proofKind": proof_kind,
        "proofSource": proof_source,
        "candidate": candidate,
        "validations": validations,
        "proofDetails": proof_details,
        "sourceConcept": source_concept,
        "targetConcept": target_concept,
        "sourceRelease": source_release,
        "targetRelease": target_release,
        "relation": relation,
    }
    if context is not None:
        basis["context"] = dict(context)
    if evidence_class == "machineQualified":
        basis["qualificationPolicy"] = _require_iri(
            value.get("qualificationPolicy"),
            "machine_evidence_proof.qualificationPolicy",
        )
    elif "qualificationPolicy" in value:
        raise SemanticFoundationError("machineReviewed proof must not contain qualificationPolicy")

    content_digest = _content_digest(basis)
    normalized = {
        **basis,
        "id": f"urn:ref:machine-evidence-proof:{ring}:{content_digest.removeprefix('sha256:')}",
        "contentDigest": content_digest,
    }
    if normalized != dict(value):
        raise SemanticFoundationError("machine_evidence_proof content identity or canonical order differs")
    return normalized


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
    """One immutable statement about how relation evidence was produced."""

    semantic_ring: SemanticRing
    evidence_class: EvidenceClass
    basis: EvidenceBasis
    asserted_by: str
    asserted_at: str
    evidence: tuple[str, ...]
    candidate: str | None = None
    machine_proof: str | None = None
    source_concept: str | None = None
    target_concept: str | None = None
    source_release: str | None = None
    target_release: str | None = None
    relation: str | None = None
    validation_receipts: tuple[str, ...] = ()
    source_artifact: str | None = None
    source_digest: str | None = None
    adopted_evidence: str | None = None
    review_decision: str | None = None
    generator: str | None = None
    generator_inputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ring = _require_ring(self.semantic_ring, "evidence_assertion.semanticRing")
        object.__setattr__(self, "semantic_ring", ring)
        if self.evidence_class not in EVIDENCE_CLASSES:
            raise SemanticFoundationError("evidence_assertion.evidenceClass is unsupported")
        allowed_bases = _EVIDENCE_BASES_BY_CLASS[cast(EvidenceClass, self.evidence_class)]
        if self.basis not in allowed_bases:
            raise SemanticFoundationError(
                f"evidence_assertion basis {self.basis!r} does not match {self.evidence_class}"
            )
        object.__setattr__(self, "asserted_by", _require_iri(self.asserted_by, "evidence_assertion.assertedBy"))
        object.__setattr__(self, "asserted_at", _require_datetime(self.asserted_at, "evidence_assertion.assertedAt"))
        object.__setattr__(self, "evidence", _require_unique_iris(self.evidence, "evidence_assertion.evidence"))

        if self.evidence_class in {"machineQualified", "machineReviewed"}:
            for field_name, value in (
                ("candidate", self.candidate),
                ("machineProof", self.machine_proof),
                ("sourceConcept", self.source_concept),
                ("targetConcept", self.target_concept),
                ("sourceRelease", self.source_release),
                ("targetRelease", self.target_release),
                ("relation", self.relation),
            ):
                if value is None:
                    raise SemanticFoundationError(f"{self.evidence_class} evidence requires {field_name}")
            object.__setattr__(self, "candidate", _require_iri(self.candidate, "evidence_assertion.candidate"))
            object.__setattr__(
                self,
                "machine_proof",
                _require_iri(self.machine_proof, "evidence_assertion.machineProof"),
            )
            object.__setattr__(
                self,
                "source_concept",
                _require_iri(self.source_concept, "evidence_assertion.sourceConcept"),
            )
            object.__setattr__(
                self,
                "target_concept",
                _require_iri(self.target_concept, "evidence_assertion.targetConcept"),
            )
            object.__setattr__(
                self,
                "source_release",
                _require_iri(self.source_release, "evidence_assertion.sourceRelease"),
            )
            object.__setattr__(
                self,
                "target_release",
                _require_iri(self.target_release, "evidence_assertion.targetRelease"),
            )
            relation = _require_iri(self.relation, "evidence_assertion.relation")
            if relation not in RING_RELATIONS[ring]:
                raise SemanticFoundationError(f"evidence_assertion relation is not valid for the {ring} ring")
            object.__setattr__(self, "relation", relation)

        if self.evidence_class == "machineQualified":
            object.__setattr__(
                self,
                "validation_receipts",
                _require_unique_iris(
                    self.validation_receipts,
                    "evidence_assertion.validationReceipts",
                    minimum=2,
                ),
            )
        elif self.evidence_class == "machineReviewed":
            object.__setattr__(
                self,
                "validation_receipts",
                _require_unique_iris(
                    self.validation_receipts,
                    "evidence_assertion.validationReceipts",
                ),
            )
            if len(self.validation_receipts) != 1:
                raise SemanticFoundationError("machineReviewed evidence requires exactly one validation receipt")
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

        machine_fields = {
            "candidate",
            "machine_proof",
            "source_concept",
            "target_concept",
            "source_release",
            "target_release",
            "relation",
            "validation_receipts",
        }
        allowed_specializations = {
            "machineQualified": machine_fields,
            "machineReviewed": machine_fields,
            "publisherAsserted": {"source_artifact", "source_digest"},
            "operatorAdopted": {"adopted_evidence"},
            "humanReviewed": {"review_decision"},
            "ruleGenerated": {"generator", "generator_inputs"},
        }[self.evidence_class]
        specialization_values = {
            "candidate": self.candidate,
            "machine_proof": self.machine_proof,
            "source_concept": self.source_concept,
            "target_concept": self.target_concept,
            "source_release": self.source_release,
            "target_release": self.target_release,
            "relation": self.relation,
            "validation_receipts": self.validation_receipts,
            "source_artifact": self.source_artifact,
            "source_digest": self.source_digest,
            "adopted_evidence": self.adopted_evidence,
            "review_decision": self.review_decision,
            "generator": self.generator,
            "generator_inputs": self.generator_inputs,
        }
        extras = [
            name
            for name, value in specialization_values.items()
            if name not in allowed_specializations and value is not None and value != ()
        ]
        if extras:
            raise SemanticFoundationError(
                f"evidence_assertion contains fields outside the {self.evidence_class} shape: {sorted(extras)!r}"
            )

    def _basis(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": "EvidenceAssertion",
            "semanticRing": self.semantic_ring,
            "evidenceClass": self.evidence_class,
            "basis": self.basis,
            "assertedBy": self.asserted_by,
            "assertedAt": self.asserted_at,
            "evidence": list(self.evidence),
            "useCeiling": self.use_ceiling,
        }
        if self.evidence_class in {"machineQualified", "machineReviewed"}:
            result.update(
                {
                    "candidate": self.candidate,
                    "machineProof": self.machine_proof,
                    "sourceConcept": self.source_concept,
                    "targetConcept": self.target_concept,
                    "sourceRelease": self.source_release,
                    "targetRelease": self.target_release,
                    "relation": self.relation,
                    "validationReceipts": list(self.validation_receipts),
                }
            )
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

    @property
    def content_digest(self) -> str:
        return _content_digest(self._basis())

    @property
    def identifier(self) -> str:
        return f"urn:ref:evidence-assertion:{self.semantic_ring}:{self.content_digest.removeprefix('sha256:')}"

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> EvidenceAssertion:
        if not isinstance(value, Mapping):
            raise SemanticFoundationError("evidence_assertion must be an object")
        _forbid_policy_fields(value, label="evidence_assertion")
        evidence_class = value.get("evidenceClass")
        if evidence_class not in EVIDENCE_CLASSES:
            raise SemanticFoundationError("evidence_assertion.evidenceClass is unsupported")
        expected_ceiling = EVIDENCE_USE_CEILINGS[cast(EvidenceClass, evidence_class)]
        if value.get("useCeiling") != expected_ceiling:
            raise SemanticFoundationError("evidence_assertion.useCeiling must be derived from evidenceClass")
        machine_fields = {
            "candidate",
            "machineProof",
            "sourceConcept",
            "targetConcept",
            "sourceRelease",
            "targetRelease",
            "relation",
            "validationReceipts",
        }
        specialized_fields = {
            "machineQualified": machine_fields,
            "machineReviewed": machine_fields,
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
                "contentDigest",
                "semanticRing",
                "evidenceClass",
                "basis",
                "assertedBy",
                "assertedAt",
                "evidence",
                "useCeiling",
                *specialized_fields,
            },
        )
        if value.get("type") != "EvidenceAssertion":
            raise SemanticFoundationError("evidence_assertion.type must be EvidenceAssertion")
        assertion = cls(
            semantic_ring=cast(SemanticRing, value.get("semanticRing")),
            evidence_class=cast(EvidenceClass, evidence_class),
            basis=cast(EvidenceBasis, value.get("basis")),
            asserted_by=cast(str, value.get("assertedBy")),
            asserted_at=cast(str, value.get("assertedAt")),
            evidence=cast(tuple[str, ...], value.get("evidence")),
            candidate=cast(str | None, value.get("candidate")),
            machine_proof=cast(str | None, value.get("machineProof")),
            source_concept=cast(str | None, value.get("sourceConcept")),
            target_concept=cast(str | None, value.get("targetConcept")),
            source_release=cast(str | None, value.get("sourceRelease")),
            target_release=cast(str | None, value.get("targetRelease")),
            relation=cast(str | None, value.get("relation")),
            validation_receipts=cast(tuple[str, ...], value.get("validationReceipts", ())),
            source_artifact=cast(str | None, value.get("sourceArtifact")),
            source_digest=cast(str | None, value.get("sourceDigest")),
            adopted_evidence=cast(str | None, value.get("adoptedEvidence")),
            review_decision=cast(str | None, value.get("reviewDecision")),
            generator=cast(str | None, value.get("generator")),
            generator_inputs=cast(tuple[str, ...], value.get("generatorInputs", ())),
        )
        if assertion.as_record() != dict(value):
            raise SemanticFoundationError("evidence_assertion content identity or canonical order differs")
        return assertion

    def as_record(self) -> dict[str, Any]:
        return {
            **self._basis(),
            "id": self.identifier,
            "contentDigest": self.content_digest,
        }

    @property
    def use_ceiling(self) -> EvidenceUseCeiling:
        """Return the evidence-class ceiling; it never grants product use."""

        return EVIDENCE_USE_CEILINGS[self.evidence_class]


@dataclass(frozen=True, slots=True)
class MappingAssertion:
    """One ring-scoped relation assertion supported by typed evidence."""

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
        object.__setattr__(
            self,
            "context",
            _validated_relation_context(
                ring,
                self.context,
                label="mapping_assertion.context",
            ),
        )

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> MappingAssertion:
        if not isinstance(value, Mapping):
            raise SemanticFoundationError("mapping_assertion must be an object")
        _forbid_policy_fields(value, label="mapping_assertion")
        ring = _require_ring(value.get("semanticRing"), "mapping_assertion.semanticRing")
        required = {
            "id",
            "type",
            "contentDigest",
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
        assertion = cls(
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
        if assertion.as_record() != dict(value):
            raise SemanticFoundationError("mapping_assertion content identity or canonical order differs")
        return assertion

    def _validate_evidence(
        self,
        evidence_by_id: Mapping[str, EvidenceAssertion],
        *,
        allow_machine_evidence: bool,
    ) -> None:
        if any(identifier != assertion.identifier for identifier, assertion in evidence_by_id.items()):
            raise SemanticFoundationError("evidence lookup keys must equal content-derived assertion ids")
        missing = sorted(set(self.evidence) - set(evidence_by_id))
        if missing:
            raise SemanticFoundationError(f"mapping_assertion cites unknown evidence {missing!r}")
        supporting_by_id: dict[str, EvidenceAssertion] = {}
        pending = [(identifier, frozenset()) for identifier in self.evidence]
        while pending:
            identifier, ancestors = pending.pop()
            if identifier in ancestors:
                raise SemanticFoundationError("operatorAdopted evidence chain contains a cycle")
            if identifier in supporting_by_id:
                continue
            assertion = evidence_by_id[identifier]
            supporting_by_id[identifier] = assertion
            if assertion.evidence_class == "operatorAdopted":
                adopted = cast(str, assertion.adopted_evidence)
                if adopted not in evidence_by_id:
                    raise SemanticFoundationError("operatorAdopted evidence must cite another evidence assertion")
                pending.append((adopted, ancestors | {identifier}))
        supporting = tuple(supporting_by_id.values())
        direct = tuple(evidence_by_id[identifier] for identifier in self.evidence)
        if any(value.semantic_ring != self.semantic_ring for value in supporting):
            raise SemanticFoundationError("mapping_assertion evidence crosses semantic rings")
        if (
            self.semantic_ring == "entity"
            and self.relation == ENTITY_SAME_IDENTITY
            and any(value.basis == "nameEquality" for value in supporting)
        ):
            raise SemanticFoundationError("entity identity cannot be supported by name equality")
        if any(value.evidence_class in {"machineReviewed", "ruleGenerated"} for value in direct):
            raise SemanticFoundationError("candidate-only evidence cannot directly support a mapping assertion")
        scoped_machine_evidence = tuple(
            value for value in supporting if value.evidence_class in {"machineQualified", "machineReviewed"}
        )
        if scoped_machine_evidence and not allow_machine_evidence:
            raise SemanticFoundationError(
                "machine-backed mapping assertions require a path-backed RelationAssertionBundle"
            )
        for value in scoped_machine_evidence:
            if (
                value.source_concept != self.source_concept
                or value.target_concept != self.target_concept
                or value.source_release != self.source_release
                or value.target_release != self.target_release
                or value.relation != self.relation
            ):
                raise SemanticFoundationError("machine evidence does not prove this mapping relation and endpoints")
        if (
            self.semantic_ring == "entity"
            and self.relation == ENTITY_SAME_IDENTITY
            and not any(value.basis in _ENTITY_IDENTITY_BASES for value in supporting)
        ):
            raise SemanticFoundationError(
                "entity identity requires identifiers, publisher crosswalk, source assertion, or human review"
            )
        if any(value.evidence_class == "ruleGenerated" for value in supporting):
            raise SemanticFoundationError("ruleGenerated evidence is candidate provenance, not mapping support")

    def validate_evidence(self, evidence_by_id: Mapping[str, EvidenceAssertion]) -> None:
        """Validate direct use; machine-backed mappings require a relation bundle."""

        self._validate_evidence(evidence_by_id, allow_machine_evidence=False)

    def _basis(self) -> dict[str, Any]:
        result: dict[str, Any] = {
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

    @property
    def content_digest(self) -> str:
        return _content_digest(self._basis())

    @property
    def identifier(self) -> str:
        return f"urn:ref:mapping-assertion:{self.semantic_ring}:{self.content_digest.removeprefix('sha256:')}"

    def as_record(self) -> dict[str, Any]:
        return {
            **self._basis(),
            "id": self.identifier,
            "contentDigest": self.content_digest,
        }


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
        assertion = (
            EvidenceAssertion.from_record(value.as_record())
            if isinstance(value, EvidenceAssertion)
            else EvidenceAssertion.from_record(value)
        )
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
        if adopted.evidence_class != "machineReviewed":
            raise SemanticFoundationError("operatorAdopted evidence must cite one machineReviewed assertion directly")
    return tuple(sorted(result, key=lambda value: value.identifier))


def _validate_mapping_assertions(
    values: Sequence[MappingAssertion | Mapping[str, Any]],
    *,
    evidence_assertions: Sequence[EvidenceAssertion | Mapping[str, Any]],
    semantic_ring: SemanticRing | None = None,
    allow_machine_evidence: bool,
) -> tuple[MappingAssertion, ...]:
    expected_ring = None if semantic_ring is None else _require_ring(semantic_ring, "semantic_ring")
    evidence = validate_evidence_assertions(evidence_assertions)
    evidence_by_id = {value.identifier: value for value in evidence}
    result: list[MappingAssertion] = []
    identifiers: set[str] = set()
    for value in values:
        assertion = (
            MappingAssertion.from_record(value.as_record())
            if isinstance(value, MappingAssertion)
            else MappingAssertion.from_record(value)
        )
        if assertion.identifier in identifiers:
            raise SemanticFoundationError("mapping_assertions repeats an id")
        if expected_ring is not None and assertion.semantic_ring != expected_ring:
            raise SemanticFoundationError("mapping_assertion semanticRing differs from the requested ring")
        assertion._validate_evidence(
            evidence_by_id,
            allow_machine_evidence=allow_machine_evidence,
        )
        identifiers.add(assertion.identifier)
        result.append(assertion)
    return tuple(sorted(result, key=lambda value: value.identifier))


def validate_mapping_assertions(
    values: Sequence[MappingAssertion | Mapping[str, Any]],
    *,
    evidence_assertions: Sequence[EvidenceAssertion | Mapping[str, Any]],
    semantic_ring: SemanticRing | None = None,
) -> tuple[MappingAssertion, ...]:
    """Validate non-machine mappings against their ring and exact evidence set.

    Machine-derived evidence becomes mapping support only inside a
    :class:`RelationAssertionBundle`, which reopens the proof adapter and pins
    the exact proof facts.  This public validator therefore fails closed for
    both direct machine evidence and operator adoption of a machine review.
    """

    return _validate_mapping_assertions(
        values,
        evidence_assertions=evidence_assertions,
        semantic_ring=semantic_ring,
        allow_machine_evidence=False,
    )


def _validate_mapping_assertions_with_machine_evidence(
    values: Sequence[MappingAssertion | Mapping[str, Any]],
    *,
    evidence_assertions: Sequence[EvidenceAssertion | Mapping[str, Any]],
    semantic_ring: SemanticRing,
) -> tuple[MappingAssertion, ...]:
    """Validate bundle-contained mappings before exact proof-pin closure."""

    return _validate_mapping_assertions(
        values,
        evidence_assertions=evidence_assertions,
        semantic_ring=semantic_ring,
        allow_machine_evidence=True,
    )


__all__ = [
    "ENTITY_RELATED",
    "ENTITY_SAME_IDENTITY",
    "ENTITY_SUCCESSOR",
    "EVIDENCE_CLASSES",
    "EVIDENCE_USE_CEILINGS",
    "LEGAL_AMENDS",
    "LEGAL_AUTHORIZES",
    "LEGAL_CITES",
    "LEGAL_IMPLEMENTS",
    "MACHINE_EVIDENCE_PROOF_VERSION",
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
    "EvidenceUseCeiling",
    "MappingAssertion",
    "RightsMetadata",
    "RightsStatus",
    "SemanticFoundationError",
    "SemanticRing",
    "validate_evidence_assertions",
    "validate_machine_evidence_proof_pin",
    "validate_mapping_assertions",
    "validate_rights_metadata",
    "validate_rights_metadata_records",
]
