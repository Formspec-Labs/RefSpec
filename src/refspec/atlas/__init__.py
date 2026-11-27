"""Static vocabulary atlas publication and verification.

Re-exports the atlas namespace constants, the concept-release and managed-release
contracts, the DuckDB view over published Atlas tables, and the sealed read-only
Vocabulary Pack runtime. Heavy submodules (such as ``duckdb_view`` and
``vocabulary_vectors``) are resolved lazily via PEP 562 ``__getattr__`` so
importing ``AtlasVocabularyPack`` never pulls in ``numpy``, ``duckdb``,
``pyarrow``, or ``rdflib`` and performs zero I/O.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_CONCEPT_RELEASE_EXPORTS = frozenset(
    {
        "MANAGED_RELEASE_RING_ASSIGNMENT_VERSION",
        "ConceptReleaseError",
        "ConceptReleaseSource",
        "ManagedReleaseRingAssignment",
        "PinnedManagedConceptRelease",
        "PinnedManagedReleaseRingAssignment",
        "PinnedSourceConceptRelease",
        "SubjectConceptRelease",
        "VerifiedConceptReleaseFacts",
        "concept_release_member_ids",
        "concept_release_pin",
        "normalize_concept_release_pin",
        "require_admissible_subject_concept",
        "require_subject_concept_release",
        "subject_release_rights_metadata",
        "verified_concept_release_facts",
    }
)
_DUCKDB_VIEW_EXPORTS = frozenset(
    {
        "ATLAS_DUCKDB_TABLES",
        "ATLAS_SEARCH_DOCUMENTS_TABLE",
        "AtlasDuckDBView",
        "AtlasDuckDBViewError",
        "open_atlas_duckdb_view",
    }
)
_EFFECTIVE_PERIOD_EXPORTS = frozenset(
    {
        "EffectiveAsOfDisposition",
        "EffectivePeriodError",
        "effective_as_of_disposition",
        "format_utc_instant",
        "is_effective_as_of",
        "normalize_as_of_utc",
        "parse_as_of",
        "validate_effective_period_bounds",
    }
)
_MODEL_EXPORTS = frozenset(
    {
        "ATLAS",
        "RKAF",
        "VocabularyAtlasError",
    }
)
_VOCABULARY_PACK_EXPORTS = frozenset(
    {
        "PACK_POLICY_VERSION",
        "PACK_RECORD_TYPE",
        "PACK_SCHEMA_VERSION",
        "SUPPORTED_PACK_SCHEMA_VERSIONS",
        "AtlasVocabularyPack",
        "PriorGuidedSemanticIndex",
        "VocabularyPackManifest",
        "build_vocabulary_pack",
    }
)
_VOCABULARY_PROTOCOL_EXPORTS = frozenset(
    {
        "DEFAULT_CALIBRATION_EVT_SIGMA",
        "DEFAULT_CALIBRATION_MIN_ELIGIBLE",
        "DEFAULT_CURATED_SCHEME_WEIGHTS",
        "DEFAULT_EXTRACT_MAX_UNIGRAM_DOC_FREQ",
        "REGULATORY_BENCHMARK_SCHEME_PRESET",
        "AuthorityReranker",
        "CandidateReranker",
        "ExactPinnedRRF",
        "GraphExpander",
        "LookupPolicy",
        "QueryEncoder",
        "RankFusionPolicy",
        "RelationPolicy",
        "SemanticIndex",
        "VocabularyInputError",
        "VocabularyPackError",
        "VocabularyProvider",
        "group_by_identical_label",
        "normalize_text",
    }
)
_VOCABULARY_VECTOR_EXPORTS = frozenset(
    {
        "AtlasSemanticSidecar",
        "SemanticSidecarManifest",
        "build_semantic_sidecar",
        "build_semantic_sidecar_from_arrays",
        "calibrate_semantic_sidecar",
    }
)

_LAZY_MODULE_BY_NAME: dict[str, str] = {}
for _name in _CONCEPT_RELEASE_EXPORTS:
    _LAZY_MODULE_BY_NAME[_name] = "refspec.atlas.concept_release"
for _name in _DUCKDB_VIEW_EXPORTS:
    _LAZY_MODULE_BY_NAME[_name] = "refspec.atlas.duckdb_view"
for _name in _EFFECTIVE_PERIOD_EXPORTS:
    _LAZY_MODULE_BY_NAME[_name] = "refspec.atlas.effective_period"
for _name in _MODEL_EXPORTS:
    _LAZY_MODULE_BY_NAME[_name] = "refspec.atlas.model"
for _name in _VOCABULARY_PACK_EXPORTS:
    _LAZY_MODULE_BY_NAME[_name] = "refspec.atlas.vocabulary_pack"
for _name in _VOCABULARY_PROTOCOL_EXPORTS:
    _LAZY_MODULE_BY_NAME[_name] = "refspec.atlas.vocabulary_protocols"
for _name in _VOCABULARY_VECTOR_EXPORTS:
    _LAZY_MODULE_BY_NAME[_name] = "refspec.atlas.vocabulary_vectors"
del _name

__all__ = [
    "ATLAS",
    "ATLAS_DUCKDB_TABLES",
    "ATLAS_SEARCH_DOCUMENTS_TABLE",
    "DEFAULT_CALIBRATION_EVT_SIGMA",
    "DEFAULT_CALIBRATION_MIN_ELIGIBLE",
    "DEFAULT_CURATED_SCHEME_WEIGHTS",
    "DEFAULT_EXTRACT_MAX_UNIGRAM_DOC_FREQ",
    "MANAGED_RELEASE_RING_ASSIGNMENT_VERSION",
    "PACK_POLICY_VERSION",
    "PACK_RECORD_TYPE",
    "PACK_SCHEMA_VERSION",
    "REGULATORY_BENCHMARK_SCHEME_PRESET",
    "RKAF",
    "SUPPORTED_PACK_SCHEMA_VERSIONS",
    "AtlasDuckDBView",
    "AtlasDuckDBViewError",
    "AtlasSemanticSidecar",
    "AtlasVocabularyPack",
    "AuthorityReranker",
    "CandidateReranker",
    "ConceptReleaseError",
    "ConceptReleaseSource",
    "EffectiveAsOfDisposition",
    "EffectivePeriodError",
    "ExactPinnedRRF",
    "GraphExpander",
    "LookupPolicy",
    "ManagedReleaseRingAssignment",
    "PinnedManagedConceptRelease",
    "PinnedManagedReleaseRingAssignment",
    "PinnedSourceConceptRelease",
    "PriorGuidedSemanticIndex",
    "QueryEncoder",
    "RankFusionPolicy",
    "RelationPolicy",
    "SemanticIndex",
    "SemanticSidecarManifest",
    "SubjectConceptRelease",
    "VerifiedConceptReleaseFacts",
    "VocabularyAtlasError",
    "VocabularyInputError",
    "VocabularyPackError",
    "VocabularyPackManifest",
    "VocabularyProvider",
    "build_semantic_sidecar",
    "build_semantic_sidecar_from_arrays",
    "build_vocabulary_pack",
    "calibrate_semantic_sidecar",
    "concept_release_member_ids",
    "concept_release_pin",
    "effective_as_of_disposition",
    "format_utc_instant",
    "group_by_identical_label",
    "is_effective_as_of",
    "normalize_as_of_utc",
    "normalize_concept_release_pin",
    "normalize_text",
    "open_atlas_duckdb_view",
    "parse_as_of",
    "require_admissible_subject_concept",
    "require_subject_concept_release",
    "subject_release_rights_metadata",
    "validate_effective_period_bounds",
    "verified_concept_release_facts",
]


def __getattr__(name: str) -> Any:
    module_name = _LAZY_MODULE_BY_NAME.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
