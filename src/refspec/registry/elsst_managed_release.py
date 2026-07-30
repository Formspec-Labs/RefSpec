"""Build one RefSpec-managed ELSST history with R6 selected for lookup.

The exact publisher Turtle files remain canonical.  RefSpec packages their
source-native Rulespec graph, lossless normalized rows, indexed vocabulary
expressions, import coverage, and one project-local R6 lookup decision.
Spicy Regs consumes the resulting immutable bundle; it does not own registry
history, import policy, or deployment selection.
"""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from refspec import binding
from refspec.registry.elsst import (
    ALT_LABEL_PREDICATE_IRI,
    HIDDEN_LABEL_PREDICATE_IRI,
    IDENTIFIER_PREDICATE_IRI,
    PREF_LABEL_PREDICATE_IRI,
    ElsstLabelExpression,
    ElsstLiteral,
    ElsstVocabulary,
    parse_acquired_elsst_source,
)
from refspec.registry.elsst_acquisition import (
    ELSST_LICENSE_IRI,
    ELSST_R5,
    ELSST_R6,
    AcquiredElsstSource,
    ElsstReleaseSource,
)
from refspec.registry.elsst_import_coverage import (
    ELSST_COVERAGE_FEATURES,
    ElsstImportCensus,
    ElsstImportCoverageError,
    census_indexed_elsst,
    census_parsed_elsst,
    census_raw_elsst_turtle,
    require_complete_elsst_import_coverage,
)
from refspec.registry.elsst_rulespec_projection import (
    ElsstRulespecProjection,
    build_elsst_rulespec_projection,
    require_valid_elsst_rulespec_projection,
    seal_elsst_rulespec_projection,
)
from refspec.registry.federal_register_vertical_slice import (
    _CORE_FACET_ROWS,
)
from refspec.registry.managed_vocabulary_bundle import (
    ManagedVocabularyBundle,
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
    REQUIRED_IMPORT_FEATURES,
    ConceptEventParticipant,
    ConceptLabel,
    ConceptRelation,
    EnrichmentProfile,
    ImportFeatureCoverage,
    IndexedVocabularyExpression,
    OutputProfile,
    RegistryDeploymentDecision,
    RegistryImportCoverageReport,
    assert_managed_vocabulary_row_integrity,
    canonical_text_digest,
    indexed_expression_id,
    indexed_expression_identity,
    indexed_expression_identity_set_digest,
    normalize_unicode_text,
    seal_payload,
)

PARSER_VERSION = "elsst-rdf-skos-lossless-v1"
BUNDLE_VERSION = "elsst-r5-r6-managed-release-v1"

NORMALIZATION_POLICY_IRI = (
    "urn:ref:normalization:unicode-nfkc-casefold-whitespace:v1"
)
IMPORT_POLICY_IRI = "urn:ref:policy:elsst-native-skos-lossless:v1"
LICENSE_RECORDING_POLICY_IRI = (
    "urn:ref:policy:record-license-without-runtime-use-gate:v1"
)
DEVELOPMENT_ENVIRONMENT_IRI = (
    "urn:ref:environment:spicy-regs-experimental-playground"
)
GENERAL_SUBJECT_FACET_IRI = "urn:ref:facet:general-subject"
ASSIGNMENT_PRIMARY_IRI = (
    "https://rulespec.org/ns/v1#assignmentPrimary"
)
SKOS_CONCEPT_IRI = "http://www.w3.org/2004/02/skos/core#Concept"
XSD_STRING_IRI = "http://www.w3.org/2001/XMLSchema#string"

_FEATURE_ORDER = ELSST_COVERAGE_FEATURES
if frozenset(_FEATURE_ORDER) != REQUIRED_IMPORT_FEATURES:  # pragma: no cover
    raise RuntimeError("ELSST feature order does not match RefSpec")

_LABEL_PREDICATE_IRIS = frozenset(
    {
        PREF_LABEL_PREDICATE_IRI,
        ALT_LABEL_PREDICATE_IRI,
        HIDDEN_LABEL_PREDICATE_IRI,
    }
)
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")


class ElsstManagedReleaseError(ValueError):
    """The exact ELSST inputs cannot form one closed managed release."""


@dataclass(frozen=True, slots=True)
class ElsstCandidateGovernance:
    """One project-local authorization for experimental R6 candidate lookup."""

    actor_iri: str
    organization_iri: str
    effective_at: str

    def __post_init__(self) -> None:
        for label, value in (
            ("actor_iri", self.actor_iri),
            ("organization_iri", self.organization_iri),
        ):
            if _ABSOLUTE_IRI.fullmatch(value) is None:
                raise ElsstManagedReleaseError(
                    f"{label} must be an absolute IRI"
                )
        if "T" not in self.effective_at or not self.effective_at.endswith("Z"):
            raise ElsstManagedReleaseError(
                "effective_at must be an RFC 3339 UTC timestamp"
            )


@dataclass(frozen=True, slots=True)
class _ElsstBuildIdentifiers:
    scope: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", self.scope) is None:
            raise ElsstManagedReleaseError(
                "ELSST build identifier scope must be 64 lowercase "
                "hexadecimal characters"
            )

    def id(self, kind: str) -> str:
        if not kind or any(character.isspace() for character in kind):
            raise ElsstManagedReleaseError(
                "generated ELSST identifier kind must be non-empty and "
                "contain no whitespace"
            )
        return f"urn:ref:elsst:{kind}:{self.scope}"

    @property
    def expression_corpus(self) -> str:
        return self.id("expression-corpus")

    @property
    def rights_assessment(self) -> str:
        return self.id("rights-assessment")

    @property
    def run_receipt(self) -> str:
        return self.id("receipt:managed-release")

    @property
    def publication(self) -> str:
        return self.id("publication:development")

    @property
    def conformance_result(self) -> str:
        return self.id("rulespec-validation-result")

    @property
    def validation_receipt(self) -> str:
        return self.id("release-graph-validation-receipt")

    @property
    def enrichment_profile(self) -> str:
        return self.id("enrichment-profile")

    @property
    def output_profile(self) -> str:
        return self.id("output-profile:development")

    @property
    def access_scope(self) -> str:
        return self.id("access-scope:local-development-only")

    @property
    def retention_policy(self) -> str:
        return self.id("retention-policy:content-addressed-source")

    @property
    def selection_assertion(self) -> str:
        return self.id("assertion:r6-local-candidate-use")

    @property
    def selection_evidence(self) -> str:
        return self.id("evidence:r6-local-candidate-use")

    @property
    def selection_attestation(self) -> str:
        return self.id("attestation:r6-local-candidate-use")

    @property
    def selection_adoption(self) -> str:
        return self.id("local-adoption:r6-local-candidate-use")

    @property
    def selected_deployment(self) -> str:
        return self.id("registry-deployment:r6-development-selected")


@dataclass(frozen=True, slots=True)
class _ReleaseInput:
    vocabulary: ElsstVocabulary
    acquired: AcquiredElsstSource
    source: ElsstReleaseSource
    release_reference: Mapping[str, str]
    distribution_reference: Mapping[str, str]
    capture_record: Mapping[str, Any] | None = None
    import_record: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class _ExpressionSeed:
    release_iri: str
    scheme_iri: str
    member_iri: str
    property_iri: str
    original_literal: str
    language_tag: str | None
    datatype_iri: str | None

    def identity(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "release": self.release_iri,
            "scheme": self.scheme_iri,
            "member": self.member_iri,
            "property": self.property_iri,
            "literal": self.original_literal,
        }
        if self.language_tag is not None:
            result["language"] = self.language_tag
        if self.datatype_iri is not None:
            result["datatype"] = self.datatype_iri
        return result


@dataclass(frozen=True, slots=True)
class ElsstManagedRelease:
    """Built records plus their reusable managed-bundle serialization."""

    bundle: ManagedVocabularyBundle
    projection: ElsstRulespecProjection
    release_references: tuple[Mapping[str, str], Mapping[str, str]]
    import_records: tuple[Mapping[str, Any], Mapping[str, Any]]
    coverage_records: tuple[Mapping[str, Any], Mapping[str, Any]]
    selected_deployment: Mapping[str, Any]
    expression_count: int
    label_count: int
    relation_count: int
    participant_count: int


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _digest_json(value: object) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _canonical_release_descriptor(
    release: ElsstReleaseSource,
) -> None:
    canonical_by_iri = {
        ELSST_R5.release_iri: ELSST_R5,
        ELSST_R6.release_iri: ELSST_R6,
    }
    canonical = canonical_by_iri.get(release.release_iri)
    if canonical is not None and release != canonical:
        raise ElsstManagedReleaseError(
            f"canonical ELSST release IRI {release.release_iri!r} requires "
            "the exact canonical release descriptor"
        )


def _verified_acquired_source(
    acquired: AcquiredElsstSource,
    *,
    label: str,
) -> tuple[ElsstVocabulary, bytes]:
    acquired_type = type(acquired)
    is_acquired_source = isinstance(
        acquired,
        AcquiredElsstSource,
    ) or (
        acquired_type.__module__
        == AcquiredElsstSource.__module__
        and acquired_type.__qualname__
        == AcquiredElsstSource.__qualname__
    )
    if not is_acquired_source:
        raise ElsstManagedReleaseError(
            f"{label} must be an AcquiredElsstSource"
        )
    _canonical_release_descriptor(acquired.release)
    if (
        acquired.source_url != acquired.release.source_url
        or acquired.sha256 != acquired.release.expected_sha256
        or acquired.byte_length
        != acquired.release.expected_byte_length
    ):
        raise ElsstManagedReleaseError(
            f"{label} acquisition metadata does not match its exact release "
            "descriptor"
        )
    try:
        vocabulary = parse_acquired_elsst_source(acquired)
        payload = acquired.path.read_bytes()
    except (OSError, TypeError, ValueError) as error:
        raise ElsstManagedReleaseError(
            f"{label} is not an intact verified acquired source: {error}"
        ) from error
    if (
        vocabulary.source_sha256 != acquired.sha256
        or vocabulary.source_bytes != acquired.byte_length
    ):
        raise ElsstManagedReleaseError(
            f"{label} parsed source identity differs from its acquisition"
        )
    return vocabulary, payload


def _build_identifiers(
    *,
    previous: AcquiredElsstSource,
    current: AcquiredElsstSource,
    validator: RulespecValidatorPin,
    recorded_at: str,
    recorded_by: str,
    governance: ElsstCandidateGovernance,
) -> _ElsstBuildIdentifiers:
    scope_digest = _digest_json(
        {
            "identityVersion": "elsst-managed-release-v2",
            "bundleVersion": BUNDLE_VERSION,
            "parserVersion": PARSER_VERSION,
            "previousSource": {
                "descriptor": asdict(previous.release),
                "verifiedDigest": previous.sha256,
                "verifiedByteLength": previous.byte_length,
            },
            "currentSource": {
                "descriptor": asdict(current.release),
                "verifiedDigest": current.sha256,
                "verifiedByteLength": current.byte_length,
            },
            "validator": {
                "identity": validator.identity,
                "sourceRevision": validator.source_revision,
                "evidenceRevision": validator.evidence_revision,
                "componentId": validator.component_id,
                "componentDigest": validator.component_digest,
                "dependencyManifestId": (
                    validator.dependency_manifest_id
                ),
                "dependencyManifestDigest": (
                    validator.dependency_manifest_digest
                ),
            },
            "recordedAt": recorded_at,
            "recordedBy": recorded_by,
            "governance": asdict(governance),
            "policies": {
                "normalization": _NORMALIZATION_POLICY,
                "import": _IMPORT_PROFILE,
                "licenseRecording": _LICENSE_RECORDING_POLICY,
                "adoptedImportPolicy": IMPORT_POLICY_IRI,
                "adoptedLicensePolicy": (
                    LICENSE_RECORDING_POLICY_IRI
                ),
            },
            "profiles": {
                "coreFacets": _CORE_FACET_ROWS,
                "candidatePermission": {
                    "facet": GENERAL_SUBJECT_FACET_IRI,
                    "assignmentRole": ASSIGNMENT_PRIMARY_IRI,
                    "requiredImportFeatures": _FEATURE_ORDER,
                    "candidateUse": True,
                    "acceptedOutputUse": False,
                },
                "environment": DEVELOPMENT_ENVIRONMENT_IRI,
            },
        }
    )
    return _ElsstBuildIdentifiers(
        scope=scope_digest.removeprefix("sha256:")
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


def _digest_reference(
    record: Mapping[str, Any],
) -> dict[str, str]:
    digest_field = binding.digest_field(dict(record))
    identifier = record.get("id")
    digest = record.get(digest_field)
    if not isinstance(identifier, str) or not isinstance(digest, str):
        raise ElsstManagedReleaseError(
            "REF record lacks an exact digest reference"
        )
    return {"id": identifier, "digest": digest}


def _versioned_reference(
    record: Mapping[str, Any],
) -> dict[str, str]:
    reference = _digest_reference(record)
    version = record.get("version")
    if not isinstance(version, str):
        raise ElsstManagedReleaseError(
            "REF record lacks a versioned digest reference"
        )
    return {**reference, "version": version}


def _policy_reference(
    identifier: str,
    version: str,
    description: object,
) -> dict[str, str]:
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
_IMPORT_PROFILE = _policy_reference(
    "urn:ref:import-profile:elsst-native-skos:v1",
    "1.0",
    {
        "parserVersion": PARSER_VERSION,
        "nativeDistribution": "canonical",
        "identityJoin": ["dcterms:isVersionOf", "owl:priorVersion"],
        "labelLanguages": "preserve",
    },
)
_LICENSE_RECORDING_POLICY = _policy_reference(
    LICENSE_RECORDING_POLICY_IRI,
    "1.0",
    {
        "rule": "Record source licensing and attribution as evidence.",
        "runtimeUseGate": False,
    },
)


def _literal_seed(
    *,
    release_iri: str,
    scheme_iri: str,
    member_iri: str,
    property_iri: str,
    value: ElsstLiteral,
) -> _ExpressionSeed:
    language = value.language_tag
    datatype = value.datatype_iri
    if (language is None) == (datatype is None):
        raise ElsstManagedReleaseError(
            f"{member_iri} {property_iri} must carry exactly one language "
            "or datatype"
        )
    return _ExpressionSeed(
        release_iri=release_iri,
        scheme_iri=scheme_iri,
        member_iri=member_iri,
        property_iri=property_iri,
        original_literal=value.lexical_form,
        language_tag=language,
        datatype_iri=datatype,
    )


def _expression_seeds(
    item: _ReleaseInput,
) -> tuple[_ExpressionSeed, ...]:
    member_iris = {
        concept.concept_iri for concept in item.vocabulary.concepts
    }
    seeds: list[_ExpressionSeed] = []
    for label in item.vocabulary.labels:
        if label.subject_iri not in member_iris:
            continue
        seeds.append(
            _literal_seed(
                release_iri=item.source.release_iri,
                scheme_iri=item.source.concept_scheme_iri,
                member_iri=label.subject_iri,
                property_iri=label.property_iri,
                value=label.value,
            )
        )
    for note in item.vocabulary.notes:
        if note.subject_iri not in member_iris:
            continue
        seeds.append(
            _literal_seed(
                release_iri=item.source.release_iri,
                scheme_iri=item.source.concept_scheme_iri,
                member_iri=note.subject_iri,
                property_iri=note.property_iri,
                value=note.value,
            )
        )
    for notation in item.vocabulary.notations:
        if notation.subject_iri not in member_iris:
            continue
        seeds.append(
            _literal_seed(
                release_iri=item.source.release_iri,
                scheme_iri=item.source.concept_scheme_iri,
                member_iri=notation.subject_iri,
                property_iri=notation.property_iri,
                value=notation.value,
            )
        )
    for metadata in item.vocabulary.metadata_literals:
        if (
            metadata.subject_iri not in member_iris
            or metadata.property_iri != IDENTIFIER_PREDICATE_IRI
        ):
            continue
        seeds.append(
            _literal_seed(
                release_iri=item.source.release_iri,
                scheme_iri=item.source.concept_scheme_iri,
                member_iri=metadata.subject_iri,
                property_iri=metadata.property_iri,
                value=metadata.value,
            )
        )
    identities = [canonical_json(seed.identity()) for seed in seeds]
    if len(identities) != len(set(identities)):
        raise ElsstManagedReleaseError(
            f"release {item.source.version} repeats an expression identity"
        )
    return tuple(
        sorted(
            seeds,
            key=lambda seed: (
                seed.member_iri,
                seed.property_iri,
                seed.language_tag or "",
                seed.datatype_iri or "",
                seed.original_literal,
            ),
        )
    )


def _graph_support_nodes(
    *,
    projection: ElsstRulespecProjection,
    validator: RulespecValidatorPin,
    governance: ElsstCandidateGovernance,
    identifiers: _ElsstBuildIdentifiers,
) -> tuple[dict[str, Any], ...]:
    conformance_digest = _digest_json(
        {
            "graph": projection.rulespec_graph_iri,
            "releaseDigests": list(projection.release_digests),
            "validator": validator.identity,
            "validatorRevision": validator.source_revision,
            "expectedResult": "pass",
        }
    )
    return (
        {
            "@id": identifiers.conformance_result,
            "@type": "rkaf:Artifact",
            "rkaf:hasArtifactIdentifier": [
                identifiers.conformance_result
            ],
            "rkaf:artifactIdentifierScheme": ["rkaf:partner-defined"],
            "dcterms:format": "application/json",
            "rkaf:hasContentDigest": conformance_digest,
        },
        {
            "@id": identifiers.id("activity:acquire:r5"),
            "@type": "prov:Activity",
        },
        {
            "@id": identifiers.id("activity:acquire:r6"),
            "@type": "prov:Activity",
        },
        {
            "@id": identifiers.access_scope,
            "@type": "rkaf:AccessScope",
            "rkaf:accessScopeKind": "rkaf:organizationVisible",
        },
        {
            "@id": identifiers.retention_policy,
            "@type": "rkaf:RetentionPolicy",
            "rkaf:retentionDurationDays": 36500,
            "rkaf:retentionTrigger": "rkaf:creation",
            "rkaf:retentionPostExpiry": "rkaf:archive",
        },
        {
            "@id": identifiers.id("rights-artifact:license"),
            "@type": "rkaf:Artifact",
            "rkaf:hasArtifactIdentifier": [ELSST_LICENSE_IRI],
            "rkaf:artifactIdentifierScheme": ["rkaf:partner-defined"],
            "dcterms:format": "text/html",
        },
        {
            "@id": identifiers.id("rights-fragment:license"),
            "@type": "rkaf:SourceFragment",
            "oa:hasSource": identifiers.id("rights-artifact:license"),
            "oa:hasSelector": [
                {
                    "@type": "oa:TextQuoteSelector",
                    "oa:exact": [
                        (
                            "Creative Commons Attribution-ShareAlike 4.0 "
                            "International"
                        )
                    ],
                }
            ],
            "rkaf:selectorKind": ["oa:TextQuoteSelector"],
            "rkaf:fragmentContentDigest": _sha256_bytes(
                b"Creative Commons Attribution-ShareAlike 4.0 "
                b"International"
            ),
        },
        {
            "@id": identifiers.selection_assertion,
            "@type": "rkaf:ValueAssertion",
            "rkaf:assertionOrigin": "rkaf:humanAsserted",
            "rkaf:epistemicBasis": "rkaf:editorialAssertion",
            "rkaf:assertsSubject": projection.release_iris[1],
            "rkaf:assertsPredicate": (
                "urn:ref:predicate:eligible-for-local-candidate-lookup"
            ),
            "rkaf:assertsValue": {
                "@value": "true",
                "@type": "xsd:boolean",
            },
            "rkaf:assertionPolarity": "rkaf:affirmed",
            "rkaf:usageEligibility": "rkaf:notEligible",
            "rkaf:assertedAt": governance.effective_at,
            "rkaf:hasAccessScope": identifiers.access_scope,
        },
        {
            "@id": identifiers.selection_evidence,
            "@type": "rkaf:EvidenceBinding",
            "rkaf:bindsAssertion": identifiers.selection_assertion,
            "rkaf:noEvidenceReason": "rkaf:consensus-without-citation",
        },
        {
            "@id": identifiers.selection_attestation,
            "@type": "rkaf:Attestation",
            "rkaf:attestor": governance.actor_iri,
            "rkaf:attestorKind": "rkaf:formalReviewer",
            "rkaf:targets": [identifiers.selection_assertion],
            "rkaf:decision": "rkaf:approved",
            "rkaf:attestationScope": DEVELOPMENT_ENVIRONMENT_IRI,
            "rkaf:attestedAt": governance.effective_at,
        },
        {
            "@id": identifiers.selection_adoption,
            "@type": "rkaf:LocalAdoption",
            "rkaf:organization": governance.organization_iri,
            "rkaf:targetAssertion": identifiers.selection_assertion,
            "rkaf:adoptionStatus": "rkaf:active",
            "rkaf:usageEligibility": "rkaf:localOperationalUse",
            "rkaf:adoptionAuthorityKind": "rkaf:localOperational",
            "rkaf:adoptionScope": DEVELOPMENT_ENVIRONMENT_IRI,
            "rkaf:authorizedBy": governance.actor_iri,
            "rkaf:adoptedAt": governance.effective_at,
            "rkaf:basedOnAttestation": (
                identifiers.selection_attestation
            ),
        },
    )


def _managed_graph(
    *,
    projection: ElsstRulespecProjection,
    validator: RulespecValidatorPin,
    governance: ElsstCandidateGovernance,
    identifiers: _ElsstBuildIdentifiers,
) -> dict[str, Any]:
    graph = copy.deepcopy(projection.graph)
    raw_nodes = graph.get("@graph")
    if not isinstance(raw_nodes, list):
        raise ElsstManagedReleaseError(
            "ELSST projection has no graph nodes"
        )
    raw_nodes.extend(
        _graph_support_nodes(
            projection=projection,
            validator=validator,
            governance=governance,
            identifiers=identifiers,
        )
    )
    identifiers = [
        node.get("@id")
        for node in raw_nodes
        if isinstance(node, Mapping)
    ]
    if len(identifiers) != len(set(identifiers)):
        raise ElsstManagedReleaseError(
            "managed ELSST graph repeats a named node"
    )
    return graph


def _build_rights_assessment(
    *,
    previous: ElsstReleaseSource,
    current: ElsstReleaseSource,
    recorded_at: str,
    recorded_by: str,
    identifiers: _ElsstBuildIdentifiers,
) -> Mapping[str, Any]:
    combined_digest = _digest_json(
        [
            {
                "source": previous.source_url,
                "digest": previous.expected_sha256,
            },
            {
                "source": current.source_url,
                "digest": current.expected_sha256,
            },
        ]
    )
    return seal_payload(
        {
            **_record_base(
                record_id=identifiers.rights_assessment,
                record_type="urn:ref:type:RightsAssessment",
                recorded_at=recorded_at,
                recorded_by=recorded_by,
                operational_state="projectDetermination",
            ),
            "target": {
                "kind": "source",
                "reference": {
                    "id": "https://elsst.cessda.eu/id/",
                    "version": (
                        f"{previous.version}-{current.version}"
                    ),
                    "digest": combined_digest,
                },
            },
            "observedTerms": [
                {
                    "sourceFragment": identifiers.id(
                        "rights-fragment:license"
                    ),
                    "summary": (
                        f"The publisher records {current.license_label} for "
                        "the ELSST distribution."
                    ),
                }
            ],
            "supportingSourceFragments": [
                identifiers.id("rights-fragment:license")
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
                "Record publisher licensing and attribution for provenance. "
                "The project does not use this record as a runtime gate for "
                "the local experiment, candidate lookup, or evaluation."
            ),
            "attribution": current.attribution,
            "audience": "RefSpec and Spicy Regs development users",
            "effectiveAt": recorded_at,
            "rulespecPolicyRefs": [],
            "attestationRefs": [],
            "localAdoptionRefs": [],
        }
    )


def _capture_id(
    source: ElsstReleaseSource,
    identifiers: _ElsstBuildIdentifiers,
) -> str:
    return identifiers.id(f"capture:r{source.version}:pinned-source")


def _import_id(
    source: ElsstReleaseSource,
    identifiers: _ElsstBuildIdentifiers,
) -> str:
    return identifiers.id(
        f"registry-import:r{source.version}:native-skos-v1"
    )


def _coverage_id(
    source: ElsstReleaseSource,
    identifiers: _ElsstBuildIdentifiers,
) -> str:
    return identifiers.id(
        f"registry-import-coverage:r{source.version}:v1"
    )


def _build_capture(
    *,
    item: _ReleaseInput,
    rights_record: Mapping[str, Any],
    recorded_at: str,
    recorded_by: str,
    identifiers: _ElsstBuildIdentifiers,
) -> Mapping[str, Any]:
    return seal_payload(
        {
            **_record_base(
                record_id=_capture_id(item.source, identifiers),
                record_type="urn:ref:type:Capture",
                recorded_at=recorded_at,
                recorded_by=recorded_by,
                operational_state="capturedDevelopmentInput",
            ),
            "source": {
                "id": item.source.source_url,
                "version": item.source.version,
                "digest": item.source.expected_sha256,
            },
            "sourceLocator": item.source.source_url,
            "requestMethod": (
                "explicitContentAddressedLocalResolver"
            ),
            "safeRequestParameters": {
                "expectedDigest": item.source.expected_sha256,
                "expectedByteLength": (
                    str(item.source.expected_byte_length)
                ),
                "networkFetchDuringBuild": "false",
            },
            "retrievalStartedAt": recorded_at,
            "retrievalEndedAt": recorded_at,
            "responseStatus": (
                "verified-local-content-addressed-input"
            ),
            "requestHeaders": {},
            "responseHeaders": {
                "content-type": "text/turtle",
            },
            "mediaType": "text/turtle",
            "acquisitionStatus": "success",
            "byteDigest": item.source.expected_sha256,
            "byteLength": item.source.expected_byte_length,
            "storageReference": item.distribution_reference["id"],
            "contentPreservation": "exactBytes",
            "completeness": {
                "complete": True,
                "pagination": {},
                "retries": [],
                "exclusions": [],
            },
            "acquisitionActivity": (
                identifiers.id(
                    f"activity:acquire:r{item.source.version}"
                )
            ),
            "runReceipt": identifiers.run_receipt,
            "accessScopeRefs": [identifiers.access_scope],
            "retentionPolicyRefs": [identifiers.retention_policy],
            "rightsExpressionRefs": [str(rights_record["id"])],
        }
    )


def _build_import_snapshot(
    *,
    item: _ReleaseInput,
    capture_record: Mapping[str, Any],
    rights_record: Mapping[str, Any],
    conformance_result_digest: str,
    recorded_at: str,
    recorded_by: str,
    projection: ElsstRulespecProjection,
    identifiers: _ElsstBuildIdentifiers,
) -> Mapping[str, Any]:
    projection_digest = _digest_json(
        {
            "source": item.source.expected_sha256,
            "parserVersion": PARSER_VERSION,
            "release": dict(item.release_reference),
            "counts": asdict(item.vocabulary.counts),
        }
    )
    return seal_payload(
        {
            **_record_base(
                record_id=_import_id(item.source, identifiers),
                record_type="urn:ref:type:RegistryImportSnapshot",
                recorded_at=recorded_at,
                recorded_by=recorded_by,
            ),
            "inventoryCoverageComponent": (
                identifiers.id(
                    f"inventory-component:r{item.source.version}"
                )
            ),
            "importProfile": dict(_IMPORT_PROFILE),
            "captures": [_digest_reference(capture_record)],
            "externalReferences": [],
            "referenceResourceRelease": dict(
                item.release_reference
            ),
            "distributionArtifacts": [
                dict(item.distribution_reference)
            ],
            "rightsAssessment": _digest_reference(rights_record),
            "adoptedPolicyRefs": [
                IMPORT_POLICY_IRI,
                LICENSE_RECORDING_POLICY_IRI,
            ],
            "transformation": {
                "id": (
                    "urn:ref:implementation:elsst-rdf-skos-parser"
                ),
                "revision": PARSER_VERSION,
                "digest": projection_digest,
            },
            "exclusions": [],
            "failures": [],
            "rulespecValidationResult": {
                "id": identifiers.conformance_result,
                "digest": conformance_result_digest,
            },
            "refValidationResult": {
                "id": (
                    identifiers.id(
                        f"validation-result:r{item.source.version}:v1"
                    )
                ),
                "digest": _digest_json(
                    {
                        "gate": "REF JSON Binding 1.0",
                        "expected": "pass",
                        "bundleVersion": BUNDLE_VERSION,
                        "source": item.source.expected_sha256,
                    }
                ),
            },
            "expectedRefreshCadence": "publisher-release",
            "activity": projection.projection_activity_iri,
            "receipt": identifiers.run_receipt,
        }
    )


def _build_profiles(
    *,
    release_inputs: Sequence[_ReleaseInput],
    recorded_at: str,
    recorded_by: str,
    identifiers: _ElsstBuildIdentifiers,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    enrichment_profile = EnrichmentProfile(
        profile_id=identifiers.enrichment_profile,
        version="1.0.0",
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        operational_state="developmentOnly",
        facets=_CORE_FACET_ROWS,
    )
    enrichment_record = enrichment_profile.sealed_payload()
    permissions = []
    for item in release_inputs:
        if item.import_record is None:
            raise ElsstManagedReleaseError(
                "profiles require exact import records"
            )
        permissions.append(
            {
                "facet": GENERAL_SUBJECT_FACET_IRI,
                "assignmentRole": ASSIGNMENT_PRIMARY_IRI,
                "referenceResourceRelease": dict(
                    item.release_reference
                ),
                "registryImportSnapshot": _digest_reference(
                    item.import_record
                ),
                "requiredImportFeatures": list(_FEATURE_ORDER),
                "candidateUse": True,
                "acceptedOutputUse": False,
            }
        )
    output_profile = OutputProfile(
        profile_id=identifiers.output_profile,
        version="1.0-development",
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        operational_state="developmentOnly",
        enrichment_profile=enrichment_profile.reference,
        acceptance_policies=(
            _policy_reference(
                "urn:ref:acceptance-policy:"
                "candidate-only-development:v1",
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
                "urn:ref:publication-view:"
                "local-experimental-playground:v1",
                "1.0",
                {
                    "audience": "localDevelopment",
                    "authorityClaim": "none",
                },
            ),
        ),
        release_permissions=tuple(permissions),
        mapping_permissions=(),
        open_label_permissions=(),
        enrichment_profile_record=enrichment_profile,
    )
    return enrichment_record, output_profile.sealed_payload()


def _build_expressions(
    *,
    release_inputs: Sequence[_ReleaseInput],
    seeds: Sequence[_ExpressionSeed],
    expression_corpus_digest: str,
    recorded_at: str,
    recorded_by: str,
    projection: ElsstRulespecProjection,
    identifiers: _ElsstBuildIdentifiers,
) -> tuple[
    tuple[Mapping[str, Any], ...],
    Mapping[str, str],
]:
    by_release = {
        item.source.release_iri: item for item in release_inputs
    }
    corpus_reference = {
        "id": identifiers.expression_corpus,
        "digest": expression_corpus_digest,
    }
    records: list[Mapping[str, Any]] = []
    # Normalized rows join back only to label expressions. Keeping note,
    # notation, and identifier seed keys would retain a second large in-memory
    # index that no later build step reads.
    expression_id_by_seed: dict[str, str] = {}
    for seed in seeds:
        item = by_release[seed.release_iri]
        if item.import_record is None:
            raise ElsstManagedReleaseError(
                "expressions require exact import records"
            )
        import_reference = _digest_reference(item.import_record)
        expression_id = indexed_expression_id(
            reference_resource_release=item.release_reference,
            registry_import_snapshot=import_reference,
            distribution_artifact=item.distribution_reference,
            scheme_iri=seed.scheme_iri,
            member_iri=seed.member_iri,
            semantic_property_iri=seed.property_iri,
            source_property_or_path=seed.property_iri,
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
            reference_resource_release=item.release_reference,
            registry_import_snapshot=import_reference,
            distribution_artifact=item.distribution_reference,
            scheme_iri=seed.scheme_iri,
            member_iri=seed.member_iri,
            semantic_property_iri=seed.property_iri,
            source_property_or_path=seed.property_iri,
            original_literal=seed.original_literal,
            language_tag=seed.language_tag,
            datatype_iri=seed.datatype_iri,
            normalization_policy=_NORMALIZATION_POLICY,
            indexed_text=indexed_text,
            indexed_text_digest=canonical_text_digest(
                indexed_text
            ),
            indexed_representation_version=(
                "unicode-nfkc-casefold-whitespace-v1"
            ),
            expression_corpus_snapshot=corpus_reference,
            activity=projection.projection_activity_iri,
            receipt=identifiers.run_receipt,
        ).sealed_payload()
        if seed.property_iri in _LABEL_PREDICATE_IRIS:
            key = canonical_json(seed.identity())
            if key in expression_id_by_seed:
                raise ElsstManagedReleaseError(
                    "expression seed identity is repeated"
                )
            expression_id_by_seed[key] = expression_id
        records.append(record)
    return tuple(records), expression_id_by_seed


def _label_seed(
    item: _ReleaseInput,
    label: ElsstLabelExpression,
) -> _ExpressionSeed:
    return _literal_seed(
        release_iri=item.source.release_iri,
        scheme_iri=item.source.concept_scheme_iri,
        member_iri=label.subject_iri,
        property_iri=label.property_iri,
        value=label.value,
    )


def _validated_graph_member_type(
    projection: ElsstRulespecProjection,
    concept_iri: str,
) -> str:
    node = next(
        (
            value
            for value in projection.graph.get("@graph", ())
            if isinstance(value, Mapping)
            and value.get("@id") == concept_iri
        ),
        None,
    )
    if not isinstance(node, Mapping):
        raise ElsstManagedReleaseError(
            f"lifecycle participant {concept_iri} is absent from the "
            "validated graph"
        )
    raw_types = node.get("@type")
    values = (
        (raw_types,)
        if isinstance(raw_types, str)
        else tuple(raw_types)
        if isinstance(raw_types, Sequence)
        and not isinstance(raw_types, (str, bytes))
        else ()
    )
    expanded = {
        (
            SKOS_CONCEPT_IRI
            if value == "skos:Concept"
            else "https://rulespec.org/ns/v1#"
            + value.removeprefix("rkaf:")
            if isinstance(value, str) and value.startswith("rkaf:")
            else value
        )
        for value in values
        if isinstance(value, str)
    }
    if len(expanded) != 1:
        raise ElsstManagedReleaseError(
            f"lifecycle participant {concept_iri} must have exactly one "
            "absolute graph type"
        )
    concept_type = next(iter(expanded))
    if _ABSOLUTE_IRI.fullmatch(concept_type) is None:
        raise ElsstManagedReleaseError(
            f"lifecycle participant {concept_iri} graph type is not an "
            "absolute IRI"
        )
    return concept_type


def _build_normalized_rows(
    *,
    release_inputs: Sequence[_ReleaseInput],
    projection: ElsstRulespecProjection,
    expression_id_by_seed: Mapping[str, str],
    identifiers: _ElsstBuildIdentifiers,
) -> tuple[
    tuple[Mapping[str, Any], ...],
    tuple[Mapping[str, Any], ...],
    tuple[Mapping[str, Any], ...],
]:
    labels: list[ConceptLabel] = []
    relations: list[ConceptRelation] = []
    participants: list[ConceptEventParticipant] = []
    membership: dict[str, Mapping[str, Any]] = {}
    for item in release_inputs:
        if item.import_record is None:
            raise ElsstManagedReleaseError(
                "normalized rows require exact import records"
            )
        import_reference = _digest_reference(item.import_record)
        member_iris = {
            concept.concept_iri
            for concept in item.vocabulary.concepts
        }
        membership[item.source.release_iri] = {
            "completeMembership": True,
            "members": member_iris,
        }
        for label in item.vocabulary.labels:
            if label.subject_iri not in member_iris:
                continue
            seed = _label_seed(item, label)
            seed_key = canonical_json(seed.identity())
            try:
                expression_id = expression_id_by_seed[seed_key]
            except KeyError as error:  # pragma: no cover - builder invariant
                raise ElsstManagedReleaseError(
                    "label has no indexed expression"
                ) from error
            identity = {
                "release": item.source.release_iri,
                "member": label.subject_iri,
                "property": label.property_iri,
                "literal": label.value.lexical_form,
                "language": label.value.language_tag,
            }
            labels.append(
                ConceptLabel(
                    label_id=(
                        identifiers.id(
                            "label:"
                            f"{_digest_json(identity).removeprefix('sha256:')}"
                        )
                    ),
                    concept_iri=label.subject_iri,
                    scheme_iri=item.source.concept_scheme_iri,
                    release_iri=item.source.release_iri,
                    import_snapshot_id=str(
                        import_reference["id"]
                    ),
                    distribution_artifact_id=str(
                        item.distribution_reference["id"]
                    ),
                    source_property_iri=label.property_iri,
                    label_role=label.role,
                    original_literal=label.value.lexical_form,
                    language_tag=str(label.value.language_tag),
                    status="notDeclared",
                    expression_id=expression_id,
                )
            )
        for relation in item.vocabulary.semantic_relations:
            identity = {
                "release": item.source.release_iri,
                "subject": relation.subject_iri,
                "predicate": relation.predicate_iri,
                "object": relation.object_iri,
            }
            relations.append(
                ConceptRelation(
                    relation_id=(
                        identifiers.id(
                            "relation:"
                            f"{_digest_json(identity).removeprefix('sha256:')}"
                        )
                    ),
                    release_iri=item.source.release_iri,
                    import_snapshot_id=str(
                        import_reference["id"]
                    ),
                    distribution_artifact_id=str(
                        item.distribution_reference["id"]
                    ),
                    subject_concept_iri=relation.subject_iri,
                    subject_scheme_iri=(
                        item.source.concept_scheme_iri
                    ),
                    predicate_iri=relation.predicate_iri,
                    object_concept_iri=relation.object_iri,
                    object_scheme_iri=(
                        item.source.concept_scheme_iri
                    ),
                    source_property_or_path=relation.predicate_iri,
                )
            )

    for transition in projection.lifecycle_transitions:
        for ordinal, concept_iri in enumerate(
            transition.predecessor_concept_iris
        ):
            participants.append(
                ConceptEventParticipant(
                    event_id=transition.event_iri,
                    operation=transition.operation,
                    participant_role="predecessor",
                    concept_iri=concept_iri,
                    concept_type_iri=_validated_graph_member_type(
                        projection,
                        concept_iri,
                    ),
                    release_iri=transition.predecessor_release_iri,
                    complete_membership=True,
                    ordinal=ordinal,
                )
            )
        for ordinal, concept_iri in enumerate(
            transition.successor_concept_iris
        ):
            successor_release = transition.successor_release_iri
            if successor_release is None:
                raise ElsstManagedReleaseError(
                    "lifecycle successor has no exact release"
                )
            participants.append(
                ConceptEventParticipant(
                    event_id=transition.event_iri,
                    operation=transition.operation,
                    participant_role="successor",
                    concept_iri=concept_iri,
                    concept_type_iri=_validated_graph_member_type(
                        projection,
                        concept_iri,
                    ),
                    release_iri=successor_release,
                    complete_membership=True,
                    ordinal=ordinal,
                )
            )
    assert_managed_vocabulary_row_integrity(
        labels,
        relations,
        participants,
        release_membership=membership,
    )
    return (
        tuple(item.to_row() for item in labels),
        tuple(item.to_row() for item in relations),
        tuple(item.to_row() for item in participants),
    )


def _build_coverage_report(
    *,
    item: _ReleaseInput,
    raw_census: ElsstImportCensus,
    parsed_census: ElsstImportCensus,
    expressions: Sequence[Mapping[str, Any]],
    graph: Mapping[str, Any],
    normalized_labels: Sequence[Mapping[str, Any]],
    normalized_relations: Sequence[Mapping[str, Any]],
    output_profile_record: Mapping[str, Any],
    expression_corpus_digest: str,
    recorded_at: str,
    recorded_by: str,
    projection: ElsstRulespecProjection,
    identifiers: _ElsstBuildIdentifiers,
) -> Mapping[str, Any]:
    if item.import_record is None:
        raise ElsstManagedReleaseError(
            "coverage requires an exact import record"
        )
    try:
        coverage = require_complete_elsst_import_coverage(
            raw_census,
            parsed_census,
            census_indexed_elsst(
                source_sha256=item.source.expected_sha256,
                release_iri=item.source.release_iri,
                concept_scheme_iri=item.source.concept_scheme_iri,
                expressions=expressions,
                rulespec_graph=graph,
                normalized_labels=normalized_labels,
                normalized_relations=normalized_relations,
            ),
        )
    except (ElsstImportCoverageError, TypeError) as error:
        raise ElsstManagedReleaseError(
            f"release {item.source.version} import coverage failed: {error}"
        ) from error
    feature_rows = tuple(
        ImportFeatureCoverage(
            feature=feature,
            source_observed_count=coverage.raw.feature(feature).count,
            parsed_count=coverage.parsed.feature(feature).count,
            indexed_count=coverage.indexed.feature(feature).count,
            explicitly_excluded_count=0,
            failed_count=0,
            source_observed_digest=coverage.raw.feature(feature).digest,
            parsed_digest=coverage.parsed.feature(feature).digest,
            indexed_digest=coverage.indexed.feature(feature).digest,
            exclusions=(),
            failures=(),
            required_for_candidate_or_output=True,
        )
        for feature in _FEATURE_ORDER
    )
    report = RegistryImportCoverageReport(
        report_id=_coverage_id(item.source, identifiers),
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        operational_state="developmentOnly",
        output_profile=_versioned_reference(
            output_profile_record
        ),
        import_snapshot=_digest_reference(item.import_record),
        reference_resource_release=item.release_reference,
        distribution_artifacts=(item.distribution_reference,),
        import_profile=_IMPORT_PROFILE,
        parser_version=PARSER_VERSION,
        expression_corpus_snapshot={
            "id": identifiers.expression_corpus,
            "digest": expression_corpus_digest,
        },
        activity=projection.projection_activity_iri,
        receipt=identifiers.run_receipt,
        feature_rows=feature_rows,
        report_status="pass",
    )
    return report.sealed_payload()


def _build_selected_deployment(
    *,
    current: _ReleaseInput,
    coverage_record: Mapping[str, Any],
    output_profile_record: Mapping[str, Any],
    governance: ElsstCandidateGovernance,
    recorded_by: str,
    projection: ElsstRulespecProjection,
    identifiers: _ElsstBuildIdentifiers,
) -> Mapping[str, Any]:
    if current.import_record is None:
        raise ElsstManagedReleaseError(
            "deployment requires the current import record"
        )
    decision = RegistryDeploymentDecision(
        decision_id=identifiers.selected_deployment,
        recorded_at=governance.effective_at,
        recorded_by=recorded_by,
        operational_state="developmentOnly",
        environment={
            "id": DEVELOPMENT_ENVIRONMENT_IRI,
            "classification": "development",
        },
        registry_import_snapshot=_digest_reference(
            current.import_record
        ),
        reference_resource_release=current.release_reference,
        coverage_report=_digest_reference(coverage_record),
        output_profile=_versioned_reference(
            output_profile_record
        ),
        rights_assessment=dict(
            current.import_record["rightsAssessment"]
        ),
        adopted_policy_refs=tuple(
            current.import_record["adoptedPolicyRefs"]
        ),
        selection_state="selected",
        effective_at=governance.effective_at,
        reason=(
            "Select exact ELSST R6 only for candidate lookup in the "
            "Spicy Regs development playground after complete R5/R6 "
            "source, import, release, and coverage validation. R5 remains "
            "historical evidence. This grants no accepted-output, "
            "publisher, or production authority."
        ),
        activity=projection.projection_activity_iri,
        rulespec_attestation_refs=(
            identifiers.selection_attestation,
        ),
        local_adoption_refs=(identifiers.selection_adoption,),
    )
    return decision.sealed_payload(
        import_snapshot_record=current.import_record,
        coverage_report_record=coverage_record,
        output_profile_record=output_profile_record,
    )


def _build_run_receipt(
    *,
    release_inputs: Sequence[_ReleaseInput],
    coverage_records: Sequence[Mapping[str, Any]],
    selected_deployment: Mapping[str, Any],
    graph_digest: str,
    expression_corpus_digest: str,
    expression_count: int,
    label_count: int,
    relation_count: int,
    participant_count: int,
    recorded_at: str,
    recorded_by: str,
    projection: ElsstRulespecProjection,
    identifiers: _ElsstBuildIdentifiers,
) -> Mapping[str, Any]:
    captures = [
        item.capture_record
        for item in release_inputs
        if item.capture_record is not None
    ]
    imports = [
        item.import_record
        for item in release_inputs
        if item.import_record is not None
    ]
    if len(captures) != len(release_inputs) or len(imports) != len(
        release_inputs
    ):
        raise ElsstManagedReleaseError(
            "run receipt requires both captures and imports"
        )
    outputs = [
        *(_digest_reference(record) for record in imports),
        *(
            _digest_reference(record)
            for record in coverage_records
        ),
        _digest_reference(selected_deployment),
        {
            "id": projection.rulespec_graph_iri,
            "digest": graph_digest,
        },
        {
            "id": identifiers.expression_corpus,
            "digest": expression_corpus_digest,
        },
    ]
    return seal_payload(
        {
            **_record_base(
                record_id=identifiers.run_receipt,
                record_type="urn:ref:type:RunReceipt",
                recorded_at=recorded_at,
                recorded_by=recorded_by,
                operational_state="completeDevelopmentRun",
            ),
            "inputCaptures": [
                _digest_reference(record) for record in captures
            ],
            "inputSnapshots": [
                _digest_reference(record) for record in imports
            ],
            "rulespecReleases": [
                dict(item.release_reference)
                for item in release_inputs
            ],
            "coverageWindow": {
                "startedAt": recorded_at,
                "endedAt": recorded_at,
            },
            "rulespecActivityRefs": [
                projection.projection_activity_iri
            ],
            "rulespecAgentRefs": [recorded_by],
            "rulespecOutputRefs": [
                *(item.source.release_iri for item in release_inputs),
                projection.rulespec_graph_iri,
            ],
            "environmentLock": {
                "id": identifiers.id("environment-lock"),
                "digest": _digest_json(
                    {
                        "parserVersion": PARSER_VERSION,
                        "bundleVersion": BUNDLE_VERSION,
                        "sources": [
                            item.source.expected_sha256
                            for item in release_inputs
                        ],
                    }
                ),
            },
            "outputs": outputs,
            "counts": {
                "releases": len(release_inputs),
                "concepts": sum(
                    len(item.vocabulary.concepts)
                    for item in release_inputs
                ),
                "indexedExpressions": expression_count,
                "normalizedLabels": label_count,
                "normalizedRelations": relation_count,
                "lifecycleParticipants": participant_count,
                "registryImports": len(imports),
                "coverageReports": len(coverage_records),
                "deploymentSelections": 1,
            },
            "exclusions": [],
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
        for path in sorted(
            binding.SCHEMA_ROOT.glob("*.schema.json")
        )
    ]
    if not artifacts:
        raise ElsstManagedReleaseError(
            "REF JSON Binding schema set is empty"
        )
    return _digest_json(artifacts)


def _rulespec_dependency(
    *,
    validator: RulespecValidatorPin,
    conformance_result_digest: str,
    identifiers: _ElsstBuildIdentifiers,
) -> Mapping[str, Any]:
    manifest_path = (
        binding.REFSPEC_ROOT
        / "profiles"
        / "rulespec-dependency.json"
    )
    manifest = binding.load_json(manifest_path)
    if not isinstance(manifest, Mapping):
        raise ElsstManagedReleaseError(
            "Rulespec dependency manifest is not an object"
        )
    return {
        "version": str(manifest["rulespecVersion"]),
        "contractRevision": str(manifest["contractRevision"]),
        "evidenceRevision": str(manifest["evidenceRevision"]),
        "constraintDigest": str(manifest["constraintDigest"]),
        "conformanceCorpusDigest": str(
            manifest["conformanceCorpusDigest"]
        ),
        "adoptedProfiles": ["urn:rulespec:profile:refspec"],
        "validator": {
            "id": validator.component_id,
            "revision": validator.source_revision,
            "digest": validator.component_digest,
        },
        "conformanceResult": {
            "id": identifiers.conformance_result,
            "digest": conformance_result_digest,
        },
        "releaseAvailability": str(
            manifest["releaseAvailability"]
        ),
    }


def _build_publication_manifest(
    *,
    operational_records: Sequence[Mapping[str, Any]],
    run_receipt: Mapping[str, Any],
    coverage_records: Sequence[Mapping[str, Any]],
    graph_digest: str,
    expression_corpus_digest: str,
    validator: RulespecValidatorPin,
    conformance_result_digest: str,
    recorded_at: str,
    recorded_by: str,
    projection: ElsstRulespecProjection,
    identifiers: _ElsstBuildIdentifiers,
) -> Mapping[str, Any]:
    return seal_payload(
        {
            **_record_base(
                record_id=identifiers.publication,
                record_type=(
                    "urn:ref:type:PublicationReleaseManifest"
                ),
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
                conformance_result_digest=(
                    conformance_result_digest
                ),
                identifiers=identifiers,
            ),
            "claimedConformanceLevels": [
                "REF JSON Binding 1.0",
                "Rulespec pinned local validation",
                (
                    "Development candidate bundle with "
                    "gate-evaluated local selection"
                ),
            ],
            "inventoryCoveragePins": [
                _digest_reference(record)
                for record in coverage_records
            ],
            "rulespecReleaseGraph": {
                "id": projection.rulespec_graph_iri,
                "digest": graph_digest,
            },
            "refOperationalRecords": [
                _digest_reference(record)
                for record in operational_records
            ],
            "expressionCorpusSnapshot": {
                "id": identifiers.expression_corpus,
                "digest": expression_corpus_digest,
            },
            "runReceipt": _digest_reference(run_receipt),
            "releaseState": "complete",
            "deploymentClass": "developmentOnly",
            "consumerEligible": True,
            "publishedAt": recorded_at,
            "activity": projection.projection_activity_iri,
        }
    )


def _release_graph_gate_bundle(
    *,
    graph: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    validator: RulespecValidatorPin,
    projection: ElsstRulespecProjection,
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
        key=lambda item: (
            item["refRecordId"],
            item["rulespecIdentifier"],
        ),
    )
    return {
        "bundleVersion": "1.0",
        "refRecords": [dict(record) for record in records],
        "rulespecGraph": dict(graph),
        "rulespecGraphId": projection.rulespec_graph_iri,
        "rulespecGraphDigest": graph_digest,
        "graphDigestAlgorithm": GRAPH_DIGEST_ALGORITHM,
        "validatorReceipt": {
            "result": "pass",
            "validatorIdentity": validator.identity,
            "validatorSourceRevision": validator.source_revision,
            "graphId": projection.rulespec_graph_iri,
            "graphDigest": graph_digest,
            "coveredIdentifiers": sorted(graph_identifiers),
        },
        "crossReferences": cross_references,
    }


def build_elsst_managed_release(
    previous_source: AcquiredElsstSource,
    current_source: AcquiredElsstSource,
    *,
    rulespec_root: Path,
    recorded_at: str,
    recorded_by: str,
    governance: ElsstCandidateGovernance,
) -> ElsstManagedRelease:
    """Build from two reverified acquired sources and gate one history."""

    previous, previous_payload = _verified_acquired_source(
        previous_source,
        label="previous_source",
    )
    current, current_payload = _verified_acquired_source(
        current_source,
        label="current_source",
    )
    try:
        source_censuses = tuple(
            (
                census_raw_elsst_turtle(
                    source_payload,
                    source_url=source.release.source_url,
                    release_iri=source.release.release_iri,
                    expected_sha256=source.release.expected_sha256,
                    expected_byte_length=(
                        source.release.expected_byte_length
                    ),
                ),
                census_parsed_elsst(
                    vocabulary,
                    release_iri=source.release.release_iri,
                ),
            )
            for vocabulary, source, source_payload in zip(
                (previous, current),
                (previous_source, current_source),
                (previous_payload, current_payload),
                strict=True,
            )
        )
    except (ElsstImportCoverageError, TypeError) as error:
        raise ElsstManagedReleaseError(
            f"ELSST source or parser coverage failed: {error}"
        ) from error
    try:
        validator = load_pinned_rulespec_validator(rulespec_root)
    except (OSError, TypeError, ValueError) as error:
        raise ElsstManagedReleaseError(
            f"cannot load the pinned Rulespec validator: {error}"
        ) from error
    identifiers = _build_identifiers(
        previous=previous_source,
        current=current_source,
        validator=validator,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        governance=governance,
    )
    projection = build_elsst_rulespec_projection(
        previous,
        current,
        validator=validator,
        previous_release=previous_source.release,
        current_release=current_source.release,
        identifier_scope=identifiers.scope,
    )
    projection = seal_elsst_rulespec_projection(
        projection,
        validator=validator,
    )
    require_valid_elsst_rulespec_projection(
        projection,
        validator=validator,
    )
    graph = _managed_graph(
        projection=projection,
        validator=validator,
        governance=governance,
        identifiers=identifiers,
    )
    nodes = {
        str(node["@id"]): node
        for node in graph["@graph"]
        if isinstance(node, Mapping)
        and isinstance(node.get("@id"), str)
    }
    conformance_result = nodes.get(identifiers.conformance_result)
    if not isinstance(conformance_result, Mapping):
        raise ElsstManagedReleaseError(
            "managed graph lacks its validation-result artifact"
        )
    conformance_result_digest = conformance_result.get(
        "rkaf:hasContentDigest"
    )
    if not isinstance(conformance_result_digest, str):
        raise ElsstManagedReleaseError(
            "managed graph validation-result digest is absent"
        )

    release_inputs: tuple[_ReleaseInput, _ReleaseInput] = tuple(
        _ReleaseInput(
            vocabulary=vocabulary,
            acquired=acquired,
            source=source,
            release_reference={
                "id": source.release_iri,
                "version": str(
                    nodes[source.release_iri]["dcat:version"]
                ),
                "digest": str(
                    nodes[source.release_iri][
                        "rkaf:referenceReleaseDigest"
                    ]
                ),
            },
            distribution_reference={
                "id": distribution_iri,
                "digest": source.expected_sha256,
            },
        )
        for vocabulary, acquired, source, distribution_iri in zip(
            (previous, current),
            (previous_source, current_source),
            (previous_source.release, current_source.release),
            projection.distribution_iris,
            strict=True,
        )
    )  # type: ignore[assignment]
    seeds = tuple(
        seed
        for item in release_inputs
        for seed in _expression_seeds(item)
    )
    rights_record = _build_rights_assessment(
        previous=previous_source.release,
        current=current_source.release,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        identifiers=identifiers,
    )
    release_inputs = tuple(
        replace(
            item,
            capture_record=_build_capture(
                item=item,
                rights_record=rights_record,
                recorded_at=recorded_at,
                recorded_by=recorded_by,
                identifiers=identifiers,
            ),
        )
        for item in release_inputs
    )  # type: ignore[assignment]
    release_inputs = tuple(
        replace(
            item,
            import_record=_build_import_snapshot(
                item=item,
                capture_record=(
                    item.capture_record
                    if item.capture_record is not None
                    else {}
                ),
                rights_record=rights_record,
                conformance_result_digest=(
                    conformance_result_digest
                ),
                recorded_at=recorded_at,
                recorded_by=recorded_by,
                projection=projection,
                identifiers=identifiers,
            ),
        )
        for item in release_inputs
    )  # type: ignore[assignment]
    release_input_by_iri = {
        item.source.release_iri: item for item in release_inputs
    }
    expression_corpus_digest = (
        indexed_expression_identity_set_digest(
            indexed_expression_identity(
                reference_resource_release=(
                    release_input_by_iri[
                        seed.release_iri
                    ].release_reference
                ),
                registry_import_snapshot=_digest_reference(
                    release_input_by_iri[
                        seed.release_iri
                    ].import_record
                    or {}
                ),
                distribution_artifact=(
                    release_input_by_iri[
                        seed.release_iri
                    ].distribution_reference
                ),
                scheme_iri=seed.scheme_iri,
                member_iri=seed.member_iri,
                semantic_property_iri=seed.property_iri,
                source_property_or_path=seed.property_iri,
                original_literal=seed.original_literal,
                language_tag=seed.language_tag,
                datatype_iri=seed.datatype_iri,
            )
            for seed in seeds
        )
    )
    enrichment_record, output_profile_record = _build_profiles(
        release_inputs=release_inputs,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        identifiers=identifiers,
    )
    expressions, expression_id_by_seed = _build_expressions(
        release_inputs=release_inputs,
        seeds=seeds,
        expression_corpus_digest=expression_corpus_digest,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        projection=projection,
        identifiers=identifiers,
    )
    del seeds
    (
        normalized_labels,
        normalized_relations,
        normalized_participants,
    ) = _build_normalized_rows(
        release_inputs=release_inputs,
        projection=projection,
        expression_id_by_seed=expression_id_by_seed,
        identifiers=identifiers,
    )
    del expression_id_by_seed
    coverage_records = tuple(
        _build_coverage_report(
            item=item,
            raw_census=raw_census,
            parsed_census=parsed_census,
            expressions=expressions,
            graph=graph,
            normalized_labels=normalized_labels,
            normalized_relations=normalized_relations,
            output_profile_record=output_profile_record,
            expression_corpus_digest=expression_corpus_digest,
            recorded_at=recorded_at,
            recorded_by=recorded_by,
            projection=projection,
            identifiers=identifiers,
        )
        for item, (raw_census, parsed_census) in zip(
            release_inputs,
            source_censuses,
            strict=True,
        )
    )
    selected_deployment = _build_selected_deployment(
        current=release_inputs[1],
        coverage_record=coverage_records[1],
        output_profile_record=output_profile_record,
        governance=governance,
        recorded_by=recorded_by,
        projection=projection,
        identifiers=identifiers,
    )
    graph_digest = rulespec_graph_digest(graph)
    run_receipt = _build_run_receipt(
        release_inputs=release_inputs,
        coverage_records=coverage_records,
        selected_deployment=selected_deployment,
        graph_digest=graph_digest,
        expression_corpus_digest=expression_corpus_digest,
        expression_count=len(expressions),
        label_count=len(normalized_labels),
        relation_count=len(normalized_relations),
        participant_count=len(normalized_participants),
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        projection=projection,
        identifiers=identifiers,
    )
    captures = tuple(
        item.capture_record
        for item in release_inputs
        if item.capture_record is not None
    )
    imports = tuple(
        item.import_record
        for item in release_inputs
        if item.import_record is not None
    )
    operational_records = (
        enrichment_record,
        output_profile_record,
        rights_record,
        *captures,
        *imports,
        *coverage_records,
        selected_deployment,
        run_receipt,
    )
    publication_record = _build_publication_manifest(
        operational_records=operational_records,
        run_receipt=run_receipt,
        coverage_records=coverage_records,
        graph_digest=graph_digest,
        expression_corpus_digest=expression_corpus_digest,
        validator=validator,
        conformance_result_digest=conformance_result_digest,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        projection=projection,
        identifiers=identifiers,
    )
    gate_bundle = _release_graph_gate_bundle(
        graph=graph,
        records=(
            publication_record,
            *operational_records,
        ),
        validator=validator,
        projection=projection,
    )
    try:
        combined_receipt = (
            issue_release_graph_validation_receipt(
                gate_bundle,
                validator=validator,
                receipt_id=identifiers.validation_receipt,
                recorded_at=recorded_at,
                recorded_by=recorded_by,
                activity=projection.projection_activity_iri,
            )
        )
    except (OSError, TypeError, ValueError) as error:
        raise ElsstManagedReleaseError(
            "combined RefSpec/Rulespec gate rejected the managed ELSST "
            f"release: {error}"
        ) from error

    expression_corpus_reference = {
        "id": identifiers.expression_corpus,
        "digest": expression_corpus_digest,
    }
    bundle = ManagedVocabularyBundle(
        rulespec_graph_id=projection.rulespec_graph_iri,
        rulespec_graph=graph,
        ref_records=tuple(operational_records),
        normalized_labels=normalized_labels,
        normalized_relations=normalized_relations,
        normalized_participants=normalized_participants,
        indexed_expressions=expressions,
        publication_release_manifest=publication_record,
        combined_validation_receipt=combined_receipt,
        rulespec_dependency_manifest_bytes=(
            rulespec_dependency_bytes()
        ),
        expression_corpus_snapshot=expression_corpus_reference,
        source_artifacts={
            projection.distribution_iris[0]: previous_payload,
            projection.distribution_iris[1]: current_payload,
        },
    )
    return ElsstManagedRelease(
        bundle=bundle,
        projection=projection,
        release_references=(
            release_inputs[0].release_reference,
            release_inputs[1].release_reference,
        ),
        import_records=(
            imports[0],
            imports[1],
        ),
        coverage_records=(
            coverage_records[0],
            coverage_records[1],
        ),
        selected_deployment=selected_deployment,
        expression_count=len(expressions),
        label_count=len(normalized_labels),
        relation_count=len(normalized_relations),
        participant_count=len(normalized_participants),
    )


__all__ = [
    "BUNDLE_VERSION",
    "ElsstCandidateGovernance",
    "ElsstManagedRelease",
    "ElsstManagedReleaseError",
    "build_elsst_managed_release",
]
