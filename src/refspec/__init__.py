"""Executable interfaces for the Regulatory Evidence Framework."""

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from refspec.generated_rulespec_dependency import load_rulespec_dependency

try:
    __version__ = version("refspec")
except PackageNotFoundError:  # pragma: no cover - direct source-tree import
    __version__ = "0.1.0.dev0"


__all__ = [
    "CANDIDATE_EXCLUDED_SOURCE_STATUSES",
    "CANONICAL_JSON_POLICY",
    "CONCEPT_EVENT_PARTICIPANT_COLUMNS",
    "CONCEPT_LABEL_COLUMNS",
    "CONCEPT_RELATION_COLUMNS",
    "MAPPING_IMPORT_REQUIRED_FEATURES",
    "REQUIRED_IMPORT_FEATURES",
    "AcceptedOutputAuthorization",
    "AcceptedOutputAuthorizationError",
    "ConceptEventParticipant",
    "ConceptLabel",
    "ConceptRelation",
    "CoverageException",
    "EnrichmentConfiguration",
    "EnrichmentDeploymentDecision",
    "EnrichmentEvaluationResult",
    "EnrichmentProfile",
    "ImportFeatureCoverage",
    "IndexedVocabularyExpression",
    "LegacyMigrationBatch",
    "ManagedReleaseAuthorizationError",
    "ManagedReleaseCandidatePermission",
    "ManagedReleaseConceptMapping",
    "ManagedReleaseError",
    "ManagedReleaseExpression",
    "ManagedReleaseGraphFactsView",
    "ManagedReleaseIdentityLink",
    "ManagedReleaseLifecycleParticipant",
    "ManagedReleaseMember",
    "ManagedReleaseRelation",
    "ManagedReleaseView",
    "OutputProfile",
    "ReferenceRuntimeError",
    "ReferenceRuntimeStore",
    "RegistryDeploymentDecision",
    "RegistryImportCoverageReport",
    "RegistryReconciliationReport",
    "VocabularyUniverseFreeze",
    "__version__",
    "adapt_source_terms_for_migration",
    "assert_managed_vocabulary_row_integrity",
    "authorize_accepted_assignment",
    "bind_ranked_candidates",
    "canonical_payload_digest",
    "canonical_text_digest",
    "indexed_expression_corpus_digest",
    "indexed_expression_id",
    "indexed_expression_id_set_digest",
    "indexed_expression_identity",
    "indexed_expression_identity_from_record",
    "indexed_expression_identity_set_digest",
    "load_rulespec_dependency",
    "materialize_open_label_value_assertion",
    "migrate_legacy_concepts",
    "normalize_unicode_text",
    "reject_legacy_conforming_payload",
    "require_language_tag",
    "require_payload_digest",
    "require_vocabulary_universe_freeze",
    "seal_payload",
]

# Governance workflow modules (accepted_output, managed_release, vocabulary --
# and, transitively, binding and release_graph) are heavy and unexercised by
# the build path; importing them eagerly here would defeat the point of
# splitting refspec.release_model out from underneath them. Every name below
# is resolved lazily, on first attribute access, per PEP 562. Object identity
# is preserved: `refspec.X` is exactly `refspec.<owning module>.X`, the same
# object, not a copy -- this module only defers *when* the owning module
# loads, never *what* the attribute is.
_ACCEPTED_OUTPUT_EXPORTS = frozenset(
    {
        "AcceptedOutputAuthorization",
        "AcceptedOutputAuthorizationError",
        "authorize_accepted_assignment",
    }
)
_MANAGED_RELEASE_EXPORTS = frozenset(
    {
        "CANDIDATE_EXCLUDED_SOURCE_STATUSES",
        "ManagedReleaseAuthorizationError",
        "ManagedReleaseCandidatePermission",
        "ManagedReleaseConceptMapping",
        "ManagedReleaseError",
        "ManagedReleaseExpression",
        "ManagedReleaseGraphFactsView",
        "ManagedReleaseIdentityLink",
        "ManagedReleaseLifecycleParticipant",
        "ManagedReleaseMember",
        "ManagedReleaseRelation",
        "ManagedReleaseView",
    }
)
_VOCABULARY_EXPORTS = frozenset(
    {
        "CANONICAL_JSON_POLICY",
        "CONCEPT_EVENT_PARTICIPANT_COLUMNS",
        "CONCEPT_LABEL_COLUMNS",
        "CONCEPT_RELATION_COLUMNS",
        "MAPPING_IMPORT_REQUIRED_FEATURES",
        "REQUIRED_IMPORT_FEATURES",
        "ConceptEventParticipant",
        "ConceptLabel",
        "ConceptRelation",
        "CoverageException",
        "EnrichmentConfiguration",
        "EnrichmentDeploymentDecision",
        "EnrichmentEvaluationResult",
        "EnrichmentProfile",
        "ImportFeatureCoverage",
        "IndexedVocabularyExpression",
        "LegacyMigrationBatch",
        "OutputProfile",
        "ReferenceRuntimeError",
        "ReferenceRuntimeStore",
        "RegistryDeploymentDecision",
        "RegistryImportCoverageReport",
        "RegistryReconciliationReport",
        "VocabularyUniverseFreeze",
        "adapt_source_terms_for_migration",
        "assert_managed_vocabulary_row_integrity",
        "bind_ranked_candidates",
        "canonical_payload_digest",
        "canonical_text_digest",
        "indexed_expression_corpus_digest",
        "indexed_expression_id",
        "indexed_expression_id_set_digest",
        "indexed_expression_identity",
        "indexed_expression_identity_from_record",
        "indexed_expression_identity_set_digest",
        "materialize_open_label_value_assertion",
        "migrate_legacy_concepts",
        "normalize_unicode_text",
        "reject_legacy_conforming_payload",
        "require_language_tag",
        "require_payload_digest",
        "require_vocabulary_universe_freeze",
        "seal_payload",
    }
)

_LAZY_MODULE_BY_NAME: dict[str, str] = {}
for _name in _ACCEPTED_OUTPUT_EXPORTS:
    _LAZY_MODULE_BY_NAME[_name] = "refspec.accepted_output"
for _name in _MANAGED_RELEASE_EXPORTS:
    _LAZY_MODULE_BY_NAME[_name] = "refspec.managed_release"
for _name in _VOCABULARY_EXPORTS:
    _LAZY_MODULE_BY_NAME[_name] = "refspec.vocabulary"
del _name


def __getattr__(name: str) -> Any:
    module_name = _LAZY_MODULE_BY_NAME.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
