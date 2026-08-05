"""Lazy public exports for RefSpec source adapters.

Importing one registry submodule must not initialize every publisher adapter.
The compatibility re-exports remain available and load only when requested.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AcquiredElsstSource": ("refspec.registry.adapters.elsst_acquisition", "AcquiredElsstSource"),
    "AcquiredFederalRegisterTopics": ("refspec.registry.federal_register_topics_api", "AcquiredFederalRegisterTopics"),
    "CRSResourceReconciliation": (
        "refspec.registry.packages.crs_source_packages",
        "CRSResourceReconciliation",
    ),
    "CRSIdentityLink": ("refspec.registry.packages.crs_source_packages", "CRSIdentityLink"),
    "CRSIdentityReview": ("refspec.registry.packages.crs_source_packages", "CRSIdentityReview"),
    "CRSSourcePackages": ("refspec.registry.packages.crs_source_packages", "CRSSourcePackages"),
    "CRSSourceConceptReleases": (
        "refspec.registry.packages.crs_source_concept_releases",
        "CRSSourceConceptReleases",
    ),
    "CRS_REGISTRATION_EVENT": (
        "refspec.registry.packages.crs_source_packages",
        "CRS_REGISTRATION_EVENT",
    ),
    "CRSSourceScheme": ("refspec.registry.crs_legislative_resources", "CRSSourceScheme"),
    "CRS_LEGISLATIVE_SUBJECT_TERMS_SCHEME": (
        "refspec.registry.crs_legislative_resources",
        "CRS_LEGISLATIVE_SUBJECT_TERMS_SCHEME",
    ),
    "CRS_LEGISLATIVE_SUBJECT_TERMS_RESOURCE_ID": (
        "refspec.registry.packages.crs_source_packages",
        "CRS_LEGISLATIVE_SUBJECT_TERMS_RESOURCE_ID",
    ),
    "CRS_POLICY_AREAS_RESOURCE_ID": ("refspec.registry.packages.crs_source_packages", "CRS_POLICY_AREAS_RESOURCE_ID"),
    "CRS_POLICY_AREAS_SCHEME": (
        "refspec.registry.crs_legislative_resources",
        "CRS_POLICY_AREAS_SCHEME",
    ),
    "ConceptDomainBridge": ("refspec.registry.adapters.concept_domain_bridge", "ConceptDomainBridge"),
    "ConceptDomainBridgeError": ("refspec.registry.adapters.concept_domain_bridge", "ConceptDomainBridgeError"),
    "ConceptDomainSourceConcept": ("refspec.registry.adapters.concept_domain_bridge", "ConceptDomainSourceConcept"),
    "ConceptDomainSourceSnapshot": ("refspec.registry.adapters.concept_domain_bridge", "ConceptDomainSourceSnapshot"),
    "ELSST_ATTRIBUTION": ("refspec.registry.adapters.elsst_acquisition", "ELSST_ATTRIBUTION"),
    "ELSST_COVERAGE_FEATURES": ("refspec.registry.adapters.elsst_import_coverage", "ELSST_COVERAGE_FEATURES"),
    "ELSST_LICENSE_IRI": ("refspec.registry.adapters.elsst_acquisition", "ELSST_LICENSE_IRI"),
    "ELSST_LICENSE_LABEL": ("refspec.registry.adapters.elsst_acquisition", "ELSST_LICENSE_LABEL"),
    "ELSST_METADATA_LITERAL_PREDICATE_IRIS": ("refspec.registry.elsst", "ELSST_METADATA_LITERAL_PREDICATE_IRIS"),
    "ELSST_NOTE_PREDICATE_IRIS": ("refspec.registry.elsst", "ELSST_NOTE_PREDICATE_IRIS"),
    "ELSST_PUBLISHER": ("refspec.registry.adapters.elsst_acquisition", "ELSST_PUBLISHER"),
    "ELSST_R6": ("refspec.registry.adapters.elsst_acquisition", "ELSST_R6"),
    "ELSST_RELEASES": ("refspec.registry.adapters.elsst_acquisition", "ELSST_RELEASES"),
    "EVIDENCE_USE_CEILINGS": (
        "refspec.registry.infrastructure.semantic_foundation",
        "EVIDENCE_USE_CEILINGS",
    ),
    "EvidenceAssertion": (
        "refspec.registry.infrastructure.semantic_foundation",
        "EvidenceAssertion",
    ),
    "EvidenceUseCeiling": (
        "refspec.registry.infrastructure.semantic_foundation",
        "EvidenceUseCeiling",
    ),
    "ElsstAcquisitionError": ("refspec.registry.adapters.elsst_acquisition", "ElsstAcquisitionError"),
    "ElsstConcept": ("refspec.registry.elsst", "ElsstConcept"),
    "ElsstConceptScheme": ("refspec.registry.elsst", "ElsstConceptScheme"),
    "ElsstCoverageDifference": ("refspec.registry.adapters.elsst_import_coverage", "ElsstCoverageDifference"),
    "ElsstDeprecation": ("refspec.registry.elsst", "ElsstDeprecation"),
    "ElsstFeatureCensus": ("refspec.registry.adapters.elsst_import_coverage", "ElsstFeatureCensus"),
    "ElsstImportCensus": ("refspec.registry.adapters.elsst_import_coverage", "ElsstImportCensus"),
    "ElsstImportCounts": ("refspec.registry.elsst", "ElsstImportCounts"),
    "ElsstImportCoverageError": ("refspec.registry.adapters.elsst_import_coverage", "ElsstImportCoverageError"),
    "ElsstImportCoverageValidation": (
        "refspec.registry.adapters.elsst_import_coverage",
        "ElsstImportCoverageValidation",
    ),
    "ElsstIriRelation": ("refspec.registry.elsst", "ElsstIriRelation"),
    "ElsstLabelExpression": ("refspec.registry.elsst", "ElsstLabelExpression"),
    "ElsstLiteral": ("refspec.registry.elsst", "ElsstLiteral"),
    "ElsstMetadataLiteral": ("refspec.registry.elsst", "ElsstMetadataLiteral"),
    "ElsstNotation": ("refspec.registry.elsst", "ElsstNotation"),
    "ElsstNote": ("refspec.registry.elsst", "ElsstNote"),
    "ElsstParseError": ("refspec.registry.elsst", "ElsstParseError"),
    "ElsstPredicateCount": ("refspec.registry.elsst", "ElsstPredicateCount"),
    "ElsstReleaseComparison": ("refspec.registry.elsst", "ElsstReleaseComparison"),
    "ElsstReleaseSource": ("refspec.registry.adapters.elsst_acquisition", "ElsstReleaseSource"),
    "ElsstStableIdentityMatch": ("refspec.registry.elsst", "ElsstStableIdentityMatch"),
    "ElsstVocabulary": ("refspec.registry.elsst", "ElsstVocabulary"),
    "FEDERAL_REGISTER_THESAURUS_2025_ISSUED": (
        "refspec.registry.federal_register_thesaurus_2025",
        "FEDERAL_REGISTER_THESAURUS_2025_ISSUED",
    ),
    "FEDERAL_REGISTER_THESAURUS_2025_RESOURCE_ID": (
        "refspec.registry.managed_releases.federal_register_thesaurus_2025_managed_release",
        "FEDERAL_REGISTER_THESAURUS_2025_RESOURCE_ID",
    ),
    "FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI": (
        "refspec.registry.federal_register_thesaurus_2025",
        "FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI",
    ),
    "FEDERAL_REGISTER_THESAURUS_2025_SHA256": (
        "refspec.registry.federal_register_thesaurus_2025",
        "FEDERAL_REGISTER_THESAURUS_2025_SHA256",
    ),
    "FEDERAL_REGISTER_THESAURUS_2025_URL": (
        "refspec.registry.federal_register_thesaurus_2025",
        "FEDERAL_REGISTER_THESAURUS_2025_URL",
    ),
    "FEDERAL_REGISTER_TOPICS_API_URL": (
        "refspec.registry.federal_register_topics_api",
        "FEDERAL_REGISTER_TOPICS_API_URL",
    ),
    "FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT": (
        "refspec.registry.packages.federal_register_topics_package",
        "FEDERAL_REGISTER_TOPICS_CAPTURE_EVENT",
    ),
    "FEDERAL_REGISTER_TOPICS_CAPTURED_AT": (
        "refspec.registry.packages.federal_register_topics_package",
        "FEDERAL_REGISTER_TOPICS_CAPTURED_AT",
    ),
    "FEDERAL_REGISTER_TOPICS_PARSER_VERSION": (
        "refspec.registry.federal_register_topics_api",
        "FEDERAL_REGISTER_TOPICS_PARSER_VERSION",
    ),
    "FEDERAL_REGISTER_TOPICS_REGISTRATION_EVENT": (
        "refspec.registry.packages.federal_register_topics_package",
        "FEDERAL_REGISTER_TOPICS_REGISTRATION_EVENT",
    ),
    "FEDERAL_REGISTER_TOPICS_RESOURCE_ID": (
        "refspec.registry.packages.federal_register_topics_package",
        "FEDERAL_REGISTER_TOPICS_RESOURCE_ID",
    ),
    "FederalRegisterThesaurus2025": (
        "refspec.registry.federal_register_thesaurus_2025",
        "FederalRegisterThesaurus2025",
    ),
    "FederalRegisterThesaurus2025Error": (
        "refspec.registry.federal_register_thesaurus_2025",
        "FederalRegisterThesaurus2025Error",
    ),
    "FederalRegisterThesaurus2025ManagedRelease": (
        "refspec.registry.managed_releases.federal_register_thesaurus_2025_managed_release",
        "FederalRegisterThesaurus2025ManagedRelease",
    ),
    "FederalRegisterThesaurus2025ManagedReleaseError": (
        "refspec.registry.managed_releases.federal_register_thesaurus_2025_managed_release",
        "FederalRegisterThesaurus2025ManagedReleaseError",
    ),
    "FederalRegisterThesaurus2025ManagedReleaseView": (
        "refspec.registry.managed_releases.federal_register_thesaurus_2025_managed_release",
        "FederalRegisterThesaurus2025ManagedReleaseView",
    ),
    "FederalRegisterTopicLink": ("refspec.registry.federal_register_topics_api", "FederalRegisterTopicLink"),
    "FederalRegisterTopicRecord": ("refspec.registry.federal_register_topics_api", "FederalRegisterTopicRecord"),
    "FederalRegisterTopicsError": ("refspec.registry.federal_register_topics_api", "FederalRegisterTopicsError"),
    "FederalRegisterTopicsSnapshot": ("refspec.registry.federal_register_topics_api", "FederalRegisterTopicsSnapshot"),
    "ICPSR_FEDERAL_REGISTER_BRIDGE_V1_SHA256": (
        "refspec.registry.adapters.concept_domain_bridge",
        "ICPSR_FEDERAL_REGISTER_BRIDGE_V1_SHA256",
    ),
    "ICPSR_FEDERAL_REGISTER_BRIDGE_V2_SHA256": (
        "refspec.registry.adapters.concept_domain_bridge",
        "ICPSR_FEDERAL_REGISTER_BRIDGE_V2_SHA256",
    ),
    "IcpsrLookupHit": ("refspec.registry.managed_releases.icpsr_managed_release", "IcpsrLookupHit"),
    "IcpsrManagedRelease": ("refspec.registry.managed_releases.icpsr_managed_release", "IcpsrManagedRelease"),
    "IcpsrManagedReleaseError": ("refspec.registry.managed_releases.icpsr_managed_release", "IcpsrManagedReleaseError"),
    "IcpsrManagedReleaseSources": (
        "refspec.registry.managed_releases.icpsr_managed_release",
        "IcpsrManagedReleaseSources",
    ),
    "IcpsrManagedReleaseView": ("refspec.registry.managed_releases.icpsr_managed_release", "IcpsrManagedReleaseView"),
    "LDAControlledListPackageError": (
        "refspec.registry.packages.lda_controlled_list_resources",
        "LDAControlledListPackageError",
    ),
    "LDAControlledListView": ("refspec.registry.packages.lda_controlled_list_resources", "LDAControlledListView"),
    "LISTS_OF_SUBJECTS_RESOLUTION_POLICY_VERSION": (
        "refspec.policies.federal_register_lists_of_subjects",
        "LISTS_OF_SUBJECTS_RESOLUTION_POLICY_VERSION",
    ),
    "ListsOfSubjectsResolution": ("refspec.policies.federal_register_lists_of_subjects", "ListsOfSubjectsResolution"),
    "ManagedReleaseViewLike": ("refspec.registry.adapters.concept_domain_bridge", "ManagedReleaseViewLike"),
    "MACHINE_EVIDENCE_PROOF_VERSION": (
        "refspec.registry.infrastructure.semantic_foundation",
        "MACHINE_EVIDENCE_PROOF_VERSION",
    ),
    "MAPPING_LIFECYCLE_STATUSES": (
        "refspec.registry.infrastructure.semantic_foundation",
        "MAPPING_LIFECYCLE_STATUSES",
    ),
    "MappingAssertion": (
        "refspec.registry.infrastructure.semantic_foundation",
        "MappingAssertion",
    ),
    "MappingLifecycleStatus": (
        "refspec.registry.infrastructure.semantic_foundation",
        "MappingLifecycleStatus",
    ),
    "ManagedVocabularyBundle": ("refspec.registry.infrastructure.managed_vocabulary_bundle", "ManagedVocabularyBundle"),
    "ManagedVocabularyBundleError": (
        "refspec.registry.infrastructure.managed_vocabulary_bundle",
        "ManagedVocabularyBundleError",
    ),
    "NOTE_PREDICATE_IRIS": ("refspec.registry.elsst", "NOTE_PREDICATE_IRIS"),
    "RING_RELATIONS": (
        "refspec.registry.infrastructure.semantic_foundation",
        "RING_RELATIONS",
    ),
    "RightsMetadata": (
        "refspec.registry.infrastructure.semantic_foundation",
        "RightsMetadata",
    ),
    "SEMANTIC_RINGS": (
        "refspec.registry.infrastructure.semantic_foundation",
        "SEMANTIC_RINGS",
    ),
    "SemanticFoundationError": (
        "refspec.registry.infrastructure.semantic_foundation",
        "SemanticFoundationError",
    ),
    "SourceControlledResourceBundle": (
        "refspec.registry.infrastructure.source_controlled_resource",
        "SourceControlledResourceBundle",
    ),
    "SourceControlledResourceError": (
        "refspec.registry.infrastructure.source_controlled_resource",
        "SourceControlledResourceError",
    ),
    "SourceControlledResourceView": (
        "refspec.registry.infrastructure.source_controlled_resource",
        "SourceControlledResourceView",
    ),
    "SourceConceptReleaseBundle": (
        "refspec.registry.infrastructure.source_concept_release",
        "SourceConceptReleaseBundle",
    ),
    "SourceConceptReleaseError": (
        "refspec.registry.infrastructure.source_concept_release",
        "SourceConceptReleaseError",
    ),
    "SourceConceptReleaseView": (
        "refspec.registry.infrastructure.source_concept_release",
        "SourceConceptReleaseView",
    ),
    "SourceCaptureEvent": ("refspec.registry.infrastructure.source_identity", "SourceCaptureEvent"),
    "SourceIdentityError": ("refspec.registry.infrastructure.source_identity", "SourceIdentityError"),
    "SourceRegistrationEvent": (
        "refspec.registry.infrastructure.source_identity",
        "SourceRegistrationEvent",
    ),
    "TopicCollection": ("refspec.registry.federal_register_topics_api", "TopicCollection"),
    "acquire_elsst_release": ("refspec.registry.adapters.elsst_acquisition", "acquire_elsst_release"),
    "build_crs_source_packages": ("refspec.registry.packages.crs_source_packages", "build_crs_source_packages"),
    "build_crs_source_concept_releases": (
        "refspec.registry.packages.crs_source_concept_releases",
        "build_crs_source_concept_releases",
    ),
    "build_crs_source_packages_from_capture_root": (
        "refspec.registry.packages.crs_source_packages",
        "build_crs_source_packages_from_capture_root",
    ),
    "build_federal_register_thesaurus_2025_managed_release": (
        "refspec.registry.managed_releases.federal_register_thesaurus_2025_managed_release",
        "build_federal_register_thesaurus_2025_managed_release",
    ),
    "build_federal_register_topics_source_package": (
        "refspec.registry.packages.federal_register_topics_package",
        "build_federal_register_topics_source_package",
    ),
    "build_icpsr_managed_release": (
        "refspec.registry.managed_releases.icpsr_managed_release",
        "build_icpsr_managed_release",
    ),
    "build_lda_filing_type_package": (
        "refspec.registry.packages.lda_controlled_list_resources",
        "build_lda_filing_type_package",
    ),
    "build_lda_general_issue_code_package": (
        "refspec.registry.packages.lda_controlled_list_resources",
        "build_lda_general_issue_code_package",
    ),
    "build_source_controlled_resource_bundle": (
        "refspec.registry.infrastructure.source_controlled_resource",
        "build_source_controlled_resource_bundle",
    ),
    "build_source_concept_release_bundle": (
        "refspec.registry.infrastructure.source_concept_release",
        "build_source_concept_release_bundle",
    ),
    "capture_federal_register_topics": (
        "refspec.registry.federal_register_topics_api",
        "capture_federal_register_topics",
    ),
    "census_indexed_elsst": ("refspec.registry.adapters.elsst_import_coverage", "census_indexed_elsst"),
    "census_parsed_elsst": ("refspec.registry.adapters.elsst_import_coverage", "census_parsed_elsst"),
    "census_raw_elsst_turtle": ("refspec.registry.adapters.elsst_import_coverage", "census_raw_elsst_turtle"),
    "compare_elsst_releases": ("refspec.registry.elsst", "compare_elsst_releases"),
    "crs_source_scheme": ("refspec.registry.crs_legislative_resources", "crs_source_scheme"),
    "load_concept_domain_bridge": ("refspec.registry.adapters.concept_domain_bridge", "load_concept_domain_bridge"),
    "load_packaged_crs_scheme_authorities": (
        "refspec.registry.packages.crs_source_packages",
        "load_packaged_crs_scheme_authorities",
    ),
    "load_federal_register_thesaurus_2025_extract": (
        "refspec.registry.federal_register_thesaurus_2025",
        "load_federal_register_thesaurus_2025_extract",
    ),
    "load_packaged_federal_register_thesaurus_2025": (
        "refspec.registry.federal_register_thesaurus_2025",
        "load_packaged_federal_register_thesaurus_2025",
    ),
    "open_federal_register_topics_capture": (
        "refspec.registry.federal_register_topics_api",
        "open_federal_register_topics_capture",
    ),
    "open_icpsr_managed_release_sources": (
        "refspec.registry.managed_releases.icpsr_managed_release",
        "open_icpsr_managed_release_sources",
    ),
    "parse_acquired_elsst_source": ("refspec.registry.elsst", "parse_acquired_elsst_source"),
    "parse_elsst_file": ("refspec.registry.elsst", "parse_elsst_file"),
    "parse_elsst_turtle": ("refspec.registry.elsst", "parse_elsst_turtle"),
    "parse_federal_register_thesaurus_2025_pdf": (
        "refspec.registry.federal_register_thesaurus_2025",
        "parse_federal_register_thesaurus_2025_pdf",
    ),
    "parse_federal_register_topics_api": (
        "refspec.registry.federal_register_topics_api",
        "parse_federal_register_topics_api",
    ),
    "require_complete_elsst_import_coverage": (
        "refspec.registry.adapters.elsst_import_coverage",
        "require_complete_elsst_import_coverage",
    ),
    "resolve_list_of_subjects_term": (
        "refspec.policies.federal_register_lists_of_subjects",
        "resolve_list_of_subjects_term",
    ),
    "source_scoped_concept_iri": (
        "refspec.registry.infrastructure.source_concept_release",
        "source_scoped_concept_iri",
    ),
    "validate_elsst_import_coverage": (
        "refspec.registry.adapters.elsst_import_coverage",
        "validate_elsst_import_coverage",
    ),
    "validate_evidence_assertions": (
        "refspec.registry.infrastructure.semantic_foundation",
        "validate_evidence_assertions",
    ),
    "validate_machine_evidence_proof_pin": (
        "refspec.registry.infrastructure.semantic_foundation",
        "validate_machine_evidence_proof_pin",
    ),
    "validate_mapping_assertions": (
        "refspec.registry.infrastructure.semantic_foundation",
        "validate_mapping_assertions",
    ),
    "validate_mapping_supersession": (
        "refspec.registry.infrastructure.semantic_foundation",
        "validate_mapping_supersession",
    ),
    "validate_rights_metadata": (
        "refspec.registry.infrastructure.semantic_foundation",
        "validate_rights_metadata",
    ),
    "validate_rights_metadata_records": (
        "refspec.registry.infrastructure.semantic_foundation",
        "validate_rights_metadata_records",
    ),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Load a compatibility export only when a caller requests it."""

    try:
        module_name, attribute_name = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(name) from None
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy names to interactive callers and documentation tools."""

    return sorted(set(globals()) | set(_LAZY_EXPORTS))
