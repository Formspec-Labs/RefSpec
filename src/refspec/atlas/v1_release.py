"""Build one immutable six-release Vocabulary Atlas v1 publication.

The release definition is a canonical, content-derived JSON record.  It pins
the planning index, each exact concept release, every relation bundle, and the
qualified Crosswalk proof sources needed to reopen those bundles.  The build
then creates a published scope, canonical Atlas 2.0 distribution, publication
decision, static package, acceptance record, and one summary that pins every
generated file.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from refspec import binding
from refspec.atlas_index import PinnedAtlasIndex
from refspec.immutable import deep_freeze_json
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue
from refspec.registry.infrastructure.semantic_foundation import (
    SUBJECT_BROAD_MATCH,
    SUBJECT_CLOSE_MATCH,
    SUBJECT_EXACT_MATCH,
    SUBJECT_NARROW_MATCH,
    SUBJECT_RELATED_MATCH,
)
from refspec.registry.infrastructure.source_identity import (
    SourceIdentityError,
    require_aware_datetime_text,
)
from refspec.registry.managed_releases.federal_register_thesaurus_2025_managed_release import (
    FederalRegisterThesaurus2025ManagedReleaseError,
    FederalRegisterThesaurus2025ManagedReleaseView,
)
from refspec.storage import canonical_json

from .atlas_scope import (
    AtlasScopeRelease,
    PinnedVocabularyAtlasScope,
    VocabularyAtlasScope,
)
from .concept_release import (
    ConceptReleaseSource,
    ManagedReleaseRingAssignment,
    PinnedManagedConceptRelease,
    PinnedManagedReleaseRingAssignment,
    PinnedSourceConceptRelease,
)
from .explorer_acceptance import (
    VocabularyAtlasExplorerAcceptance,
    build_vocabulary_atlas_explorer_acceptance,
    read_vocabulary_atlas_explorer_acceptance,
)
from .federal_register import PinnedFederalRegisterManagedConceptRelease
from .icpsr import PinnedIcpsrManagedConceptRelease
from .machine_evidence import PinnedCrosswalkMachineProof
from .model import CrosswalkBundle, VocabularyAtlasAsset, build_vocabulary_atlas
from .publication import (
    EXPLORER_DATA,
    EXPLORER_HTML,
    AtlasPublication,
    publish_vocabulary_atlas,
)
from .publication_decision import (
    PublicationDecisionError,
    VocabularyAtlasPublicationDecision,
    build_vocabulary_atlas_publication_decision,
    read_vocabulary_atlas_publication_decision,
)
from .relation_assertion import PinnedRelationAssertionBundle
from .release_acceptance import (
    VocabularyAtlasReleaseAcceptance,
    build_vocabulary_atlas_release_acceptance,
    read_vocabulary_atlas_release_acceptance,
)

VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_TYPE = "VocabularyAtlasV1ReleaseDefinition"
VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_VERSION = "2.0"
VOCABULARY_ATLAS_V1_BUILD_RESULT_TYPE = "VocabularyAtlasV1BuildResult"
VOCABULARY_ATLAS_V1_BUILD_RESULT_VERSION = "2.0"

ReleaseKind = Literal[
    "sourceConceptRelease",
    "managedConceptRelease",
    "federalRegisterManagedConceptRelease",
    "icpsrManagedConceptRelease",
]
ReleaseMode = Literal["publicV1", "baselineEvidenceRc"]
V1ReleaseRole = Literal[
    "federalRegisterThesaurus",
    "crsLegislativeSubjects",
    "crsPolicyAreas",
    "crsEntities",
    "elsst",
    "icpsr",
]

_DEFINITION_ID_PREFIX = "urn:ref:vocabulary-atlas-v1-release-definition:"
_BUILD_RESULT_ID_PREFIX = "urn:ref:vocabulary-atlas-v1-build-result:"
_PUBLIC_V1_EXPLORER_SEARCH_CORPUS_PATH = (
    "research/vocabulary-atlas-v1-explorer-search-corpus-2026-08-05.json"
)
_PUBLIC_V1_EXPLORER_SEARCH_CORPUS_FILE_DIGEST = (
    "sha256:1a3c007ea39ce3bbf2401c34bf2f49fed3d2b2294658e2b04c68a52454588c2d"
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_KEY = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_RINGS = frozenset({"subject", "entity", "value", "legalIdentity"})
_RELEASE_KINDS = frozenset(
    {
        "sourceConceptRelease",
        "managedConceptRelease",
        "federalRegisterManagedConceptRelease",
        "icpsrManagedConceptRelease",
    }
)
_MANAGED_KINDS = _RELEASE_KINDS - {"sourceConceptRelease"}
_POLICY_ROLES = frozenset({"selectionPolicy", "qualificationPolicy"})
_EXCEPTION_KINDS = frozenset({"developmentOnly", "rights"})
_RELEASE_MODES = frozenset({"publicV1", "baselineEvidenceRc"})
_V1_RELEASE_ROLES = frozenset(
    {
        "federalRegisterThesaurus",
        "crsLegislativeSubjects",
        "crsPolicyAreas",
        "crsEntities",
        "elsst",
        "icpsr",
    }
)
_PRODUCTION_JOB_ROLES: Mapping[str, tuple[str, str]] = {
    "federal-register-elsst": ("federalRegisterThesaurus", "elsst"),
    "federal-register-icpsr": ("federalRegisterThesaurus", "icpsr"),
    "elsst-icpsr": ("elsst", "icpsr"),
    "crs-subjects-federal-register": (
        "crsLegislativeSubjects",
        "federalRegisterThesaurus",
    ),
    "crs-policy-federal-register": (
        "crsPolicyAreas",
        "federalRegisterThesaurus",
    ),
    "crs-subjects-crs-policy": (
        "crsLegislativeSubjects",
        "crsPolicyAreas",
    ),
}
_BASELINE_JOB_NAMES = frozenset(
    {
        "federal-register-elsst",
        "federal-register-icpsr",
        "elsst-icpsr",
    }
)
_FEDERAL_REGISTER_RELATED_REFERENCE_COUNTS: Mapping[str, int] = {
    "resolved": 1_451,
    "suggestedOpenTermPattern": 11,
    "unresolved": 1,
}
_FEDERAL_REGISTER_RECONCILIATION_ID_PREFIX = "urn:ref:federal-register-related-reference-reconciliation:"
_PUBLIC_V1_PLANNING_INDEX_DIGESTS: Mapping[str, str] = {
    "fileDigest": "sha256:c84657233253289530aaf43c58ae7d8098a1887630bffa8fe79590d945b4a386",
    "inputFileDigest": "sha256:aeeedc35c99bb8a7ac6185ff323b8d8306f5a359aab46288a2fa102cef9e9d5c",
    "resourceCatalogFileDigest": "sha256:f0f6be90ae4017187242561af837e3642dab80bff9371082bcdcfaf0b03a94d7",
}
_PUBLIC_V1_RELEASE_PINS: Mapping[str, tuple[str, str, int, int]] = {
    "crsEntities": (
        "urn:ref:source-concept-release:entity:79db00f21940827fdf62a0af51e1d0d9161fdc438f345700f50590439b0f5822",
        "sha256:aa80aaf0495a5e74a5194374cac05075fe8bcc0f0046261853293521544959fd",
        478,
        0,
    ),
    "crsLegislativeSubjects": (
        "urn:ref:source-concept-release:subject:d137bdbae553a0ca59fb879458703de0a0a9047b49c119cb79a0765de75f3567",
        "sha256:f20d688f08134a8b6b1c9a6e202e84c5e051e2786c743df66708be27b55b12e7",
        565,
        0,
    ),
    "crsPolicyAreas": (
        "urn:ref:source-concept-release:subject:3e2d1e3d598d818c4d53e9514c05ad8a5a804a3f138e1325f1605c7eed517d7e",
        "sha256:b5966cb93cc1a28cc87ea914538f9c2f3da0b44fb37f66385170b56954dabeb8",
        32,
        0,
    ),
    "elsst": (
        "https://elsst.cessda.eu/id/6",
        "sha256:466a4464cd252bf0b0c0e872927abc430f7532610100cf01e8104eec0ee69f25",
        3_470,
        12_482,
    ),
    "federalRegisterThesaurus": (
        "urn:ref:federal-register-thesaurus:2025-04-01:reference-resource-release:v1",
        "sha256:3491acfdb3c4b51fda6351fcc47c2ca13e63e9df99e30399e05f745c97bf9df6",
        705,
        1_451,
    ),
    "icpsr": (
        "urn:ref:icpsr:release:development:8bf9bf7f6c335e3aaccd29eedd00d41d7bc153e216e7dff6ff215472368aae37",
        "sha256:f3c9f4efa7fd12b6339db9feabb029b17425672293a8fb615999c881673ac12a",
        3_760,
        18_751,
    ),
}
_PUBLIC_V1_BASELINE_MAPPING_COUNTS: Mapping[str, int] = {
    SUBJECT_BROAD_MATCH: 75,
    SUBJECT_CLOSE_MATCH: 232,
    SUBJECT_EXACT_MATCH: 121,
    SUBJECT_NARROW_MATCH: 119,
    SUBJECT_RELATED_MATCH: 35,
}
_PUBLIC_V1_PRODUCTION_CATALOGS: Mapping[str, tuple[int, str]] = {
    "crs-policy-federal-register": (
        110,
        "sha256:5bd6cd992b15d1bba46a5a951081fe55c63d9442687762ccbaf58aa283823366",
    ),
    "crs-subjects-crs-policy": (
        116,
        "sha256:105dee6fb91f68dd33dd4f170fe069ae6cbd6f8985ec04345e0f7105f93e2473",
    ),
    "crs-subjects-federal-register": (
        385,
        "sha256:499c31e5ea6724deb962adad2b5b3d7aab600e8f351d6ab4ddc625afc2cde5b5",
    ),
    "elsst-icpsr": (
        7_626,
        "sha256:9fdb98b75ba02e3393e6af501eb55282b2f184c84fec7576ce721e2b164bf2b7",
    ),
    "federal-register-elsst": (
        2_281,
        "sha256:6d9c3d882ed3ddee732a0e5012a509a599465d18d3f01e333b15007fb348612c",
    ),
    "federal-register-icpsr": (
        1_795,
        "sha256:4d4e1d632b14f3f5239f0a645c273eba6e2462bc614f5686d365c24bbe883c43",
    ),
}
_PUBLIC_V1_BASELINE_RUNS: Mapping[str, tuple[str, str]] = {
    "elsst-icpsr": (
        "sha256:c45a4142a8f9eadbdac2469ba9388b4a2e4cab37f03b5a4861d3c0dbddf480a6",
        "sha256:9427c1f6594a73018774ee740ed6c2be8d5a2fd7075f4342035d557cbf9036c7",
    ),
    "federal-register-elsst": (
        "sha256:7b5dce1a35c40dbac27365a128dd5c2fa9f4ceaab2dd0ab724ce3d4ca76be89a",
        "sha256:7fdac61f4afdbc664e29c40c3c725767779fd166ceb50eebbf46593826abcec2",
    ),
    "federal-register-icpsr": (
        "sha256:83203c9830857e708b34835c124182948ef12e1d07b848490957f99f087efbb0",
        "sha256:de38585b99ec063a729ec23f74874572c72e8b2237644991b346d0ea7daecf20",
    ),
}
_PUBLIC_V1_BASELINE_ENDPOINT_MANIFEST_DIGESTS: Mapping[str, tuple[str, str]] = {
    "elsst-icpsr": (
        "sha256:e20928a6cb68494dfac8b8c16d6aa3db1147f2145d99c31bd01287eeced9761f",
        _PUBLIC_V1_RELEASE_PINS["icpsr"][1],
    ),
    "federal-register-elsst": (
        _PUBLIC_V1_RELEASE_PINS["federalRegisterThesaurus"][1],
        "sha256:8dd408effe1d57109460a01a9c6620107b4662cbb95eed829ef905f3bfe8b71e",
    ),
    "federal-register-icpsr": (
        _PUBLIC_V1_RELEASE_PINS["federalRegisterThesaurus"][1],
        _PUBLIC_V1_RELEASE_PINS["icpsr"][1],
    ),
}

_DEFINITION_BASIS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "releaseMode",
        "releaseName",
        "scopeName",
        "scopeKind",
        "title",
        "planningIndex",
        "reviewedSearchCorpus",
        "releases",
        "relationBundles",
        "productionQualificationRuns",
        "baselineQualificationRuns",
        "publication",
        "expectedCounts",
    }
)
_DEFINITION_RECORD_FIELDS = _DEFINITION_BASIS_FIELDS | {"id", "recordDigest"}
_DEFINITION_V1_BASIS_FIELDS = _DEFINITION_BASIS_FIELDS - {
    "reviewedSearchCorpus"
}
_DEFINITION_BASIS_FIELDS_BY_VERSION = {
    "1.0": _DEFINITION_V1_BASIS_FIELDS,
    "2.0": _DEFINITION_BASIS_FIELDS,
}
_PUBLIC_REVIEWED_SEARCH_CORPUS_FIELDS = frozenset(
    {"status", "path", "fileDigest"}
)
_BASELINE_REVIEWED_SEARCH_CORPUS_FIELDS = frozenset({"status"})
_PLANNING_INDEX_FIELDS = frozenset(
    {
        "path",
        "fileDigest",
        "inputPath",
        "inputFileDigest",
        "resourceCatalogPath",
        "resourceCatalogFileDigest",
        "repositoryRoot",
    }
)
_RELEASE_BASE_FIELDS = frozenset(
    {
        "key",
        "v1Role",
        "kind",
        "label",
        "manifestPath",
        "manifestDigest",
        "releaseId",
        "semanticRing",
    }
)
_RING_ASSIGNMENT_FIELDS = frozenset({"assignedBy", "assignedAt", "evidence"})
_RELATION_FIELDS = frozenset(
    {
        "key",
        "manifestPath",
        "manifestDigest",
        "semanticRing",
        "releaseIds",
        "machineProofs",
    }
)
_PROOF_FIELDS = frozenset(
    {
        "crosswalkPath",
        "crosswalkFileDigest",
        "crosswalkBundleDigest",
        "candidateId",
        "qualificationRun",
    }
)
_QUALIFICATION_RUN_FIELDS = frozenset({"path", "fileDigest", "contentDigest"})
_PAIR_RUN_FIELDS = frozenset(
    {
        "job",
        "sourceReleaseId",
        "targetReleaseId",
        "runReceiptPath",
        "runReceiptFileDigest",
        "runReceiptContentDigest",
    }
)
_PUBLICATION_FIELDS = frozenset(
    {
        "decisionActor",
        "decidedAt",
        "policies",
        "exceptions",
        "supersedes",
        "sourceApprovals",
        "rowDispositions",
    }
)
_POLICY_FIELDS = frozenset({"role", "id", "version", "contentDigest"})
_EXCEPTION_FIELDS = frozenset({"kind", "appliesTo", "statement"})
_SUPERSESSION_FIELDS = frozenset({"id", "recordDigest"})
_SOURCE_APPROVAL_FIELDS = frozenset(
    {
        "releaseId",
        "manifestDigest",
        "semanticRing",
        "disposition",
        "conditions",
    }
)
_APPROVAL_CONDITION_FIELDS = frozenset({"kind", "statement"})
_ROW_DISPOSITION_FIELDS = frozenset({"rowId", "rowDigest", "disposition", "reason"})
_ROW_DISPOSITIONS = frozenset({"included", "planned", "deferred", "unavailable", "deliberatelyExcluded"})
_EXPECTED_COUNT_FIELDS = frozenset(
    {
        "releaseCount",
        "planningRowCount",
        "includedPlanningRowCount",
        "conceptTotal",
        "conceptsByRelease",
        "nativeRelationTotal",
        "nativeRelationsByRelease",
        "mappingMinimumTotal",
        "mappingMinimumByRelation",
    }
)
_BUILD_RESULT_BASIS_FIELDS = frozenset(
    {
        "type",
        "schemaVersion",
        "releaseMode",
        "releaseName",
        "status",
        "releaseDefinition",
        "scope",
        "atlas",
        "publicationDecision",
        "publication",
        "explorerAcceptance",
        "acceptance",
        "counts",
        "reproducibility",
        "qualificationRuns",
        "sourceReconciliations",
        "artifacts",
    }
)
_BUILD_RESULT_RECORD_FIELDS = _BUILD_RESULT_BASIS_FIELDS | {
    "id",
    "recordDigest",
}
_BUILD_RESULT_V1_BASIS_FIELDS = _BUILD_RESULT_BASIS_FIELDS - {
    "explorerAcceptance"
}
_BUILD_RESULT_BASIS_FIELDS_BY_VERSION = {
    "1.0": _BUILD_RESULT_V1_BASIS_FIELDS,
    "2.0": _BUILD_RESULT_BASIS_FIELDS,
}


class VocabularyAtlasV1ReleaseError(ValueError):
    """The v1 definition, an exact input, or a generated release is invalid."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        binding.validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise VocabularyAtlasV1ReleaseError(str(error)) from error
    return canonical_json_bytes(plain)


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VocabularyAtlasV1ReleaseError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _require_array(value: object, label: str, *, nonempty: bool = False) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise VocabularyAtlasV1ReleaseError(f"{label} must be an array")
    if nonempty and not value:
        raise VocabularyAtlasV1ReleaseError(f"{label} must not be empty")
    return cast(Sequence[Any], value)


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise VocabularyAtlasV1ReleaseError(
            f"{label} fields differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise VocabularyAtlasV1ReleaseError(f"{label} must be non-empty trimmed text")
    return value


def _require_iri(value: object, label: str) -> str:
    iri = _require_text(value, label)
    issue = absolute_uri_issue(iri)
    if issue == "missing-scheme":
        raise VocabularyAtlasV1ReleaseError(f"{label} must be an absolute IRI")
    if issue == "credentials":
        raise VocabularyAtlasV1ReleaseError(f"{label} must not contain credentials")
    return iri


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise VocabularyAtlasV1ReleaseError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_datetime(value: object, label: str) -> str:
    text = _require_text(value, label)
    try:
        return require_aware_datetime_text(text, label=label)
    except SourceIdentityError as error:
        raise VocabularyAtlasV1ReleaseError(str(error)) from error


def _require_count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise VocabularyAtlasV1ReleaseError(f"{label} must be a non-negative integer")
    return value


def _require_relative_path(value: object, label: str) -> str:
    text = _require_text(value, label)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != text:
        raise VocabularyAtlasV1ReleaseError(f"{label} must be a normalized artifact-root-relative path")
    return text


def _require_key(value: object, label: str) -> str:
    key = _require_text(value, label)
    if _KEY.fullmatch(key) is None:
        raise VocabularyAtlasV1ReleaseError(f"{label} must contain lowercase letters, digits, and internal hyphens")
    return key


def _normalize_unique_iris(value: object, label: str, *, nonempty: bool = True) -> list[str]:
    rows = _require_array(value, label, nonempty=nonempty)
    result = [_require_iri(item, f"{label}[{index}]") for index, item in enumerate(rows)]
    if len(result) != len(set(result)):
        raise VocabularyAtlasV1ReleaseError(f"{label} must contain unique IRIs")
    return sorted(result)


def _normalize_planning_index(value: object) -> dict[str, str]:
    label = "v1 release definition planningIndex"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _PLANNING_INDEX_FIELDS, label)
    return {
        "path": _require_relative_path(row.get("path"), f"{label}.path"),
        "fileDigest": _require_digest(row.get("fileDigest"), f"{label}.fileDigest"),
        "inputPath": _require_relative_path(row.get("inputPath"), f"{label}.inputPath"),
        "inputFileDigest": _require_digest(row.get("inputFileDigest"), f"{label}.inputFileDigest"),
        "resourceCatalogPath": _require_relative_path(row.get("resourceCatalogPath"), f"{label}.resourceCatalogPath"),
        "resourceCatalogFileDigest": _require_digest(
            row.get("resourceCatalogFileDigest"),
            f"{label}.resourceCatalogFileDigest",
        ),
        "repositoryRoot": _require_relative_path(row.get("repositoryRoot"), f"{label}.repositoryRoot"),
    }


def _normalize_reviewed_search_corpus(
    value: object,
    *,
    release_mode: str,
) -> dict[str, str]:
    label = "v1 release definition reviewedSearchCorpus"
    row = _require_mapping(value, label)
    if release_mode == "publicV1":
        _require_exact_fields(row, _PUBLIC_REVIEWED_SEARCH_CORPUS_FIELDS, label)
        if row.get("status") != "required":
            raise VocabularyAtlasV1ReleaseError(
                f"{label}.status must be required for publicV1"
            )
        return {
            "status": "required",
            "path": _require_relative_path(row.get("path"), f"{label}.path"),
            "fileDigest": _require_digest(
                row.get("fileDigest"),
                f"{label}.fileDigest",
            ),
        }
    _require_exact_fields(row, _BASELINE_REVIEWED_SEARCH_CORPUS_FIELDS, label)
    if row.get("status") != "skippedPublicOnly":
        raise VocabularyAtlasV1ReleaseError(
            f"{label}.status must be skippedPublicOnly for baselineEvidenceRc"
        )
    return {"status": "skippedPublicOnly"}


def _normalize_ring_assignment(value: object, label: str) -> dict[str, Any]:
    row = _require_mapping(value, label)
    _require_exact_fields(row, _RING_ASSIGNMENT_FIELDS, label)
    return {
        "assignedBy": _require_iri(row.get("assignedBy"), f"{label}.assignedBy"),
        "assignedAt": _require_datetime(row.get("assignedAt"), f"{label}.assignedAt"),
        "evidence": _normalize_unique_iris(row.get("evidence"), f"{label}.evidence"),
    }


def _normalize_releases(value: object) -> list[dict[str, Any]]:
    rows = _require_array(value, "v1 release definition releases", nonempty=True)
    if len(rows) != 6:
        raise VocabularyAtlasV1ReleaseError("v1 release definition must name exactly six concept releases")
    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    release_ids: set[str] = set()
    roles: set[str] = set()
    kind_counts = {kind: 0 for kind in _RELEASE_KINDS}
    for index, raw in enumerate(rows):
        label = f"v1 release definition releases[{index}]"
        row = _require_mapping(raw, label)
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in _RELEASE_KINDS:
            raise VocabularyAtlasV1ReleaseError(f"{label}.kind is unsupported")
        expected = _RELEASE_BASE_FIELDS | ({"ringAssignment"} if kind in _MANAGED_KINDS else set())
        _require_exact_fields(row, frozenset(expected), label)
        key = _require_key(row.get("key"), f"{label}.key")
        role = row.get("v1Role")
        if not isinstance(role, str) or role not in _V1_RELEASE_ROLES:
            raise VocabularyAtlasV1ReleaseError(f"{label}.v1Role is unsupported")
        release_id = _require_iri(row.get("releaseId"), f"{label}.releaseId")
        if key in keys or release_id in release_ids or role in roles:
            raise VocabularyAtlasV1ReleaseError("v1 release definition repeats a release key, releaseId, or v1Role")
        keys.add(key)
        release_ids.add(release_id)
        roles.add(role)
        ring = row.get("semanticRing")
        if not isinstance(ring, str) or ring not in _RINGS:
            raise VocabularyAtlasV1ReleaseError(f"{label}.semanticRing is unsupported")
        if (
            kind
            in {
                "federalRegisterManagedConceptRelease",
                "icpsrManagedConceptRelease",
            }
            and ring != "subject"
        ):
            raise VocabularyAtlasV1ReleaseError(f"{label}.semanticRing must be subject for this specialized release")
        normalized: dict[str, Any] = {
            "key": key,
            "v1Role": role,
            "kind": kind,
            "label": _require_text(row.get("label"), f"{label}.label"),
            "manifestPath": _require_relative_path(row.get("manifestPath"), f"{label}.manifestPath"),
            "manifestDigest": _require_digest(row.get("manifestDigest"), f"{label}.manifestDigest"),
            "releaseId": release_id,
            "semanticRing": ring,
        }
        if kind in _MANAGED_KINDS:
            normalized["ringAssignment"] = _normalize_ring_assignment(
                row.get("ringAssignment"), f"{label}.ringAssignment"
            )
        result.append(normalized)
        kind_counts[kind] += 1
    if kind_counts != {
        "sourceConceptRelease": 3,
        "managedConceptRelease": 1,
        "federalRegisterManagedConceptRelease": 1,
        "icpsrManagedConceptRelease": 1,
    }:
        raise VocabularyAtlasV1ReleaseError(
            "v1 requires three source releases plus one generic, one Federal Register, and one ICPSR managed release"
        )
    expected_role_shapes = {
        "federalRegisterThesaurus": (
            "federalRegisterManagedConceptRelease",
            "subject",
        ),
        "crsLegislativeSubjects": ("sourceConceptRelease", "subject"),
        "crsPolicyAreas": ("sourceConceptRelease", "subject"),
        "crsEntities": ("sourceConceptRelease", "entity"),
        "elsst": ("managedConceptRelease", "subject"),
        "icpsr": ("icpsrManagedConceptRelease", "subject"),
    }
    actual_role_shapes = {
        cast(str, row["v1Role"]): (
            cast(str, row["kind"]),
            cast(str, row["semanticRing"]),
        )
        for row in result
    }
    if actual_role_shapes != expected_role_shapes:
        raise VocabularyAtlasV1ReleaseError("v1 release roles must name the exact six source kinds and semantic rings")
    return sorted(result, key=lambda row: row["key"])


def _normalize_qualification_run(value: object, label: str) -> dict[str, str]:
    row = _require_mapping(value, label)
    _require_exact_fields(row, _QUALIFICATION_RUN_FIELDS, label)
    return {
        "path": _require_relative_path(row.get("path"), f"{label}.path"),
        "fileDigest": _require_digest(row.get("fileDigest"), f"{label}.fileDigest"),
        "contentDigest": _require_digest(row.get("contentDigest"), f"{label}.contentDigest"),
    }


def _normalize_machine_proofs(value: object, label: str) -> list[dict[str, Any]]:
    rows = _require_array(value, label)
    result: list[dict[str, Any]] = []
    candidates: set[tuple[str, str]] = set()
    for index, raw in enumerate(rows):
        item_label = f"{label}[{index}]"
        row = _require_mapping(raw, item_label)
        _require_exact_fields(row, _PROOF_FIELDS, item_label)
        normalized = {
            "crosswalkPath": _require_relative_path(row.get("crosswalkPath"), f"{item_label}.crosswalkPath"),
            "crosswalkFileDigest": _require_digest(
                row.get("crosswalkFileDigest"),
                f"{item_label}.crosswalkFileDigest",
            ),
            "crosswalkBundleDigest": _require_digest(
                row.get("crosswalkBundleDigest"),
                f"{item_label}.crosswalkBundleDigest",
            ),
            "candidateId": _require_iri(row.get("candidateId"), f"{item_label}.candidateId"),
            "qualificationRun": _normalize_qualification_run(
                row.get("qualificationRun"), f"{item_label}.qualificationRun"
            ),
        }
        key = (normalized["crosswalkPath"], normalized["candidateId"])
        if key in candidates:
            raise VocabularyAtlasV1ReleaseError(f"{label} repeats a Crosswalk candidate proof")
        candidates.add(key)
        result.append(normalized)
    return sorted(
        result,
        key=lambda row: (row["crosswalkPath"], row["candidateId"]),
    )


def _normalize_relation_bundles(
    value: object,
    *,
    release_ids: frozenset[str],
) -> list[dict[str, Any]]:
    rows = _require_array(value, "v1 release definition relationBundles", nonempty=True)
    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, raw in enumerate(rows):
        label = f"v1 release definition relationBundles[{index}]"
        row = _require_mapping(raw, label)
        _require_exact_fields(row, _RELATION_FIELDS, label)
        key = _require_key(row.get("key"), f"{label}.key")
        if key in keys:
            raise VocabularyAtlasV1ReleaseError("v1 release definition repeats a relation-bundle key")
        keys.add(key)
        ring = row.get("semanticRing")
        if ring != "subject":
            raise VocabularyAtlasV1ReleaseError(f"{label}.semanticRing must be subject for the v1 mapping set")
        endpoints = _normalize_unique_iris(row.get("releaseIds"), f"{label}.releaseIds")
        if len(endpoints) < 2 or not set(endpoints) <= release_ids:
            raise VocabularyAtlasV1ReleaseError(f"{label}.releaseIds must name at least two v1 releases")
        result.append(
            {
                "key": key,
                "manifestPath": _require_relative_path(row.get("manifestPath"), f"{label}.manifestPath"),
                "manifestDigest": _require_digest(row.get("manifestDigest"), f"{label}.manifestDigest"),
                "semanticRing": "subject",
                "releaseIds": endpoints,
                "machineProofs": _normalize_machine_proofs(row.get("machineProofs"), f"{label}.machineProofs"),
            }
        )
    return sorted(result, key=lambda row: row["key"])


def _normalize_policies(value: object, label: str) -> list[dict[str, str]]:
    rows = _require_array(value, label, nonempty=True)
    result: list[dict[str, str]] = []
    roles: set[str] = set()
    for index, raw in enumerate(rows):
        item_label = f"{label}[{index}]"
        row = _require_mapping(raw, item_label)
        _require_exact_fields(row, _POLICY_FIELDS, item_label)
        role = row.get("role")
        if not isinstance(role, str) or role not in _POLICY_ROLES:
            raise VocabularyAtlasV1ReleaseError(f"{item_label}.role must be selectionPolicy or qualificationPolicy")
        if role in roles:
            raise VocabularyAtlasV1ReleaseError(f"{label} must contain one policy for each required role")
        roles.add(role)
        result.append(
            {
                "role": role,
                "id": _require_iri(row.get("id"), f"{item_label}.id"),
                "version": _require_text(row.get("version"), f"{item_label}.version"),
                "contentDigest": _require_digest(row.get("contentDigest"), f"{item_label}.contentDigest"),
            }
        )
    if roles != _POLICY_ROLES:
        raise VocabularyAtlasV1ReleaseError(f"{label} must contain selectionPolicy and qualificationPolicy")
    return sorted(result, key=lambda row: (row["role"], row["id"]))


def _normalize_exceptions(
    value: object,
    label: str,
    *,
    release_ids: frozenset[str],
) -> list[dict[str, str]]:
    rows = _require_array(value, label)
    result: list[dict[str, str]] = []
    for index, raw in enumerate(rows):
        item_label = f"{label}[{index}]"
        row = _require_mapping(raw, item_label)
        _require_exact_fields(row, _EXCEPTION_FIELDS, item_label)
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in _EXCEPTION_KINDS:
            raise VocabularyAtlasV1ReleaseError(f"{item_label}.kind is unsupported")
        applies_to = _require_iri(row.get("appliesTo"), f"{item_label}.appliesTo")
        if applies_to not in release_ids:
            raise VocabularyAtlasV1ReleaseError(f"{item_label}.appliesTo must name an included release")
        result.append(
            {
                "kind": kind,
                "appliesTo": applies_to,
                "statement": _require_text(row.get("statement"), f"{item_label}.statement"),
            }
        )
    canonical_rows = [_canonical_bytes(row) for row in result]
    if len(canonical_rows) != len(set(canonical_rows)):
        raise VocabularyAtlasV1ReleaseError(f"{label} repeats an exception")
    return sorted(
        result,
        key=lambda row: (row["kind"], row["appliesTo"], row["statement"]),
    )


def _normalize_supersedes(value: object, label: str) -> list[dict[str, str]]:
    rows = _require_array(value, label)
    result: list[dict[str, str]] = []
    identifiers: set[str] = set()
    for index, raw in enumerate(rows):
        item_label = f"{label}[{index}]"
        row = _require_mapping(raw, item_label)
        _require_exact_fields(row, _SUPERSESSION_FIELDS, item_label)
        identifier = _require_iri(row.get("id"), f"{item_label}.id")
        if identifier in identifiers:
            raise VocabularyAtlasV1ReleaseError(f"{label} repeats an id")
        identifiers.add(identifier)
        result.append(
            {
                "id": identifier,
                "recordDigest": _require_digest(row.get("recordDigest"), f"{item_label}.recordDigest"),
            }
        )
    return sorted(result, key=lambda row: row["id"])


def _normalize_pair_runs(
    value: object,
    label: str,
    *,
    releases: Sequence[Mapping[str, Any]],
    expected_jobs: frozenset[str],
) -> list[dict[str, str]]:
    rows = _require_array(value, label, nonempty=bool(expected_jobs))
    role_release_ids = {cast(str, row["v1Role"]): cast(str, row["releaseId"]) for row in releases}
    result: list[dict[str, str]] = []
    jobs: set[str] = set()
    for index, raw in enumerate(rows):
        item_label = f"{label}[{index}]"
        row = _require_mapping(raw, item_label)
        _require_exact_fields(row, _PAIR_RUN_FIELDS, item_label)
        job = _require_key(row.get("job"), f"{item_label}.job")
        if job not in expected_jobs or job in jobs:
            raise VocabularyAtlasV1ReleaseError(f"{label} must name every required job exactly once")
        jobs.add(job)
        source_role, target_role = _PRODUCTION_JOB_ROLES[job]
        source_release_id = _require_iri(row.get("sourceReleaseId"), f"{item_label}.sourceReleaseId")
        target_release_id = _require_iri(row.get("targetReleaseId"), f"{item_label}.targetReleaseId")
        if source_release_id != role_release_ids[source_role] or target_release_id != role_release_ids[target_role]:
            raise VocabularyAtlasV1ReleaseError(f"{item_label} endpoints differ from the required v1 pair")
        result.append(
            {
                "job": job,
                "sourceReleaseId": source_release_id,
                "targetReleaseId": target_release_id,
                "runReceiptPath": _require_relative_path(row.get("runReceiptPath"), f"{item_label}.runReceiptPath"),
                "runReceiptFileDigest": _require_digest(
                    row.get("runReceiptFileDigest"),
                    f"{item_label}.runReceiptFileDigest",
                ),
                "runReceiptContentDigest": _require_digest(
                    row.get("runReceiptContentDigest"),
                    f"{item_label}.runReceiptContentDigest",
                ),
            }
        )
    if jobs != expected_jobs:
        raise VocabularyAtlasV1ReleaseError(f"{label} must name every required job exactly once")
    return sorted(result, key=lambda row: row["job"])


def _normalize_approval_conditions(value: object, label: str) -> list[dict[str, str]]:
    rows = _require_array(value, label)
    result: list[dict[str, str]] = []
    for index, raw in enumerate(rows):
        item_label = f"{label}[{index}]"
        row = _require_mapping(raw, item_label)
        _require_exact_fields(row, _APPROVAL_CONDITION_FIELDS, item_label)
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in _EXCEPTION_KINDS:
            raise VocabularyAtlasV1ReleaseError(f"{item_label}.kind is unsupported")
        result.append(
            {
                "kind": kind,
                "statement": _require_text(row.get("statement"), f"{item_label}.statement"),
            }
        )
    canonical = [_canonical_bytes(row) for row in result]
    if len(canonical) != len(set(canonical)):
        raise VocabularyAtlasV1ReleaseError(f"{label} repeats a condition")
    return sorted(result, key=lambda row: (row["kind"], row["statement"]))


def _normalize_source_approvals(
    value: object,
    label: str,
    *,
    releases: Sequence[Mapping[str, Any]],
    exceptions: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    rows = _require_array(value, label, nonempty=True)
    expected = {cast(str, release["releaseId"]): release for release in releases}
    result: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, raw in enumerate(rows):
        item_label = f"{label}[{index}]"
        row = _require_mapping(raw, item_label)
        _require_exact_fields(row, _SOURCE_APPROVAL_FIELDS, item_label)
        release_id = _require_iri(row.get("releaseId"), f"{item_label}.releaseId")
        if release_id in identifiers or release_id not in expected:
            raise VocabularyAtlasV1ReleaseError(f"{label} must approve every and only included release")
        identifiers.add(release_id)
        release = expected[release_id]
        conditions = _normalize_approval_conditions(row.get("conditions"), f"{item_label}.conditions")
        expected_conditions = sorted(
            (
                {"kind": exception["kind"], "statement": exception["statement"]}
                for exception in exceptions
                if exception["appliesTo"] == release_id
            ),
            key=lambda item: (item["kind"], item["statement"]),
        )
        if release["v1Role"] == "icpsr" and not any(
            condition["kind"] == "developmentOnly" for condition in expected_conditions
        ):
            raise VocabularyAtlasV1ReleaseError(f"{item_label} must retain the ICPSR developmentOnly condition")
        if (
            row.get("disposition") != "approved"
            or row.get("manifestDigest") != release["manifestDigest"]
            or row.get("semanticRing") != release["semanticRing"]
            or conditions != expected_conditions
        ):
            raise VocabularyAtlasV1ReleaseError(f"{item_label} differs from its exact release or conditions")
        result.append(
            {
                "releaseId": release_id,
                "manifestDigest": release["manifestDigest"],
                "semanticRing": release["semanticRing"],
                "disposition": "approved",
                "conditions": conditions,
            }
        )
    if identifiers != set(expected):
        raise VocabularyAtlasV1ReleaseError(f"{label} must approve every and only included release")
    return sorted(result, key=lambda row: row["releaseId"])


def _normalize_row_dispositions(value: object, label: str) -> list[dict[str, str]]:
    rows = _require_array(value, label, nonempty=True)
    result: list[dict[str, str]] = []
    identifiers: set[str] = set()
    for index, raw in enumerate(rows):
        item_label = f"{label}[{index}]"
        row = _require_mapping(raw, item_label)
        _require_exact_fields(row, _ROW_DISPOSITION_FIELDS, item_label)
        row_id = _require_iri(row.get("rowId"), f"{item_label}.rowId")
        disposition = row.get("disposition")
        if row_id in identifiers or disposition not in _ROW_DISPOSITIONS:
            raise VocabularyAtlasV1ReleaseError(f"{label} repeats a row or has an unsupported disposition")
        identifiers.add(row_id)
        result.append(
            {
                "rowId": row_id,
                "rowDigest": _require_digest(row.get("rowDigest"), f"{item_label}.rowDigest"),
                "disposition": cast(str, disposition),
                "reason": _require_text(row.get("reason"), f"{item_label}.reason"),
            }
        )
    return sorted(result, key=lambda row: row["rowId"])


def _normalize_publication(
    value: object,
    *,
    releases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    label = "v1 release definition publication"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _PUBLICATION_FIELDS, label)
    release_ids = frozenset(cast(str, release["releaseId"]) for release in releases)
    exceptions = _normalize_exceptions(
        row.get("exceptions"),
        f"{label}.exceptions",
        release_ids=release_ids,
    )
    return {
        "decisionActor": _require_iri(row.get("decisionActor"), f"{label}.decisionActor"),
        "decidedAt": _require_datetime(row.get("decidedAt"), f"{label}.decidedAt"),
        "policies": _normalize_policies(row.get("policies"), f"{label}.policies"),
        "exceptions": exceptions,
        "supersedes": _normalize_supersedes(row.get("supersedes"), f"{label}.supersedes"),
        "sourceApprovals": _normalize_source_approvals(
            row.get("sourceApprovals"),
            f"{label}.sourceApprovals",
            releases=releases,
            exceptions=exceptions,
        ),
        "rowDispositions": _normalize_row_dispositions(row.get("rowDispositions"), f"{label}.rowDispositions"),
    }


def _normalize_count_map(
    value: object,
    label: str,
    *,
    expected_keys: frozenset[str] | None = None,
) -> dict[str, int]:
    row = _require_mapping(value, label)
    result = {_require_iri(key, f"{label} key"): _require_count(item, f"{label}[{key!r}]") for key, item in row.items()}
    if expected_keys is not None and set(result) != expected_keys:
        raise VocabularyAtlasV1ReleaseError(f"{label} must name every and only included release")
    return {key: result[key] for key in sorted(result)}


def _normalize_expected_counts(
    value: object,
    *,
    release_ids: frozenset[str],
) -> dict[str, Any]:
    label = "v1 release definition expectedCounts"
    row = _require_mapping(value, label)
    _require_exact_fields(row, _EXPECTED_COUNT_FIELDS, label)
    release_count = _require_count(row.get("releaseCount"), f"{label}.releaseCount")
    if release_count != 6:
        raise VocabularyAtlasV1ReleaseError(f"{label}.releaseCount must be six")
    concepts = _normalize_count_map(
        row.get("conceptsByRelease"),
        f"{label}.conceptsByRelease",
        expected_keys=release_ids,
    )
    native = _normalize_count_map(
        row.get("nativeRelationsByRelease"),
        f"{label}.nativeRelationsByRelease",
        expected_keys=release_ids,
    )
    concept_total = _require_count(row.get("conceptTotal"), f"{label}.conceptTotal")
    native_total = _require_count(row.get("nativeRelationTotal"), f"{label}.nativeRelationTotal")
    if sum(concepts.values()) != concept_total:
        raise VocabularyAtlasV1ReleaseError(f"{label}.conceptTotal differs from conceptsByRelease")
    if sum(native.values()) != native_total:
        raise VocabularyAtlasV1ReleaseError(f"{label}.nativeRelationTotal differs from nativeRelationsByRelease")
    mapping_minima = _normalize_count_map(
        row.get("mappingMinimumByRelation"),
        f"{label}.mappingMinimumByRelation",
    )
    mapping_minimum_total = _require_count(row.get("mappingMinimumTotal"), f"{label}.mappingMinimumTotal")
    if sum(mapping_minima.values()) > mapping_minimum_total:
        raise VocabularyAtlasV1ReleaseError(f"{label}.mappingMinimumTotal must cover every predicate minimum")
    return {
        "releaseCount": release_count,
        "planningRowCount": _require_count(row.get("planningRowCount"), f"{label}.planningRowCount"),
        "includedPlanningRowCount": _require_count(
            row.get("includedPlanningRowCount"),
            f"{label}.includedPlanningRowCount",
        ),
        "conceptTotal": concept_total,
        "conceptsByRelease": concepts,
        "nativeRelationTotal": native_total,
        "nativeRelationsByRelease": native,
        "mappingMinimumTotal": mapping_minimum_total,
        "mappingMinimumByRelation": mapping_minima,
    }


def _validate_public_v1_profile(
    *,
    planning_index: Mapping[str, str],
    reviewed_search_corpus: Mapping[str, str] | None,
    releases: Sequence[Mapping[str, Any]],
    expected_counts: Mapping[str, Any],
    baseline_runs: Sequence[Mapping[str, Any]],
) -> None:
    """Keep the public v1 label tied to the approved current release profile."""

    if any(planning_index[field] != digest for field, digest in _PUBLIC_V1_PLANNING_INDEX_DIGESTS.items()):
        raise VocabularyAtlasV1ReleaseError("publicV1 requires the exact approved 87-row planning index and inputs")
    if reviewed_search_corpus is not None and _plain(reviewed_search_corpus) != {
        "status": "required",
        "path": _PUBLIC_V1_EXPLORER_SEARCH_CORPUS_PATH,
        "fileDigest": _PUBLIC_V1_EXPLORER_SEARCH_CORPUS_FILE_DIGEST,
    }:
        raise VocabularyAtlasV1ReleaseError(
            "publicV1 requires the exact approved reviewed explorer search corpus"
        )
    observed_pins = {
        cast(str, release["v1Role"]): (
            cast(str, release["releaseId"]),
            cast(str, release["manifestDigest"]),
        )
        for release in releases
    }
    approved_pins = {
        role: (release_id, manifest_digest)
        for role, (release_id, manifest_digest, _concepts, _native) in (_PUBLIC_V1_RELEASE_PINS.items())
    }
    if observed_pins != approved_pins:
        raise VocabularyAtlasV1ReleaseError("publicV1 requires the exact approved six release IDs and manifest digests")
    concepts = {
        release_id: concept_count
        for release_id, _manifest, concept_count, _native in (_PUBLIC_V1_RELEASE_PINS.values())
    }
    native_relations = {
        release_id: native_count
        for release_id, _manifest, _concepts, native_count in (_PUBLIC_V1_RELEASE_PINS.values())
    }
    approved_counts = {
        "releaseCount": 6,
        "planningRowCount": 87,
        "includedPlanningRowCount": 6,
        "conceptTotal": 9_010,
        "conceptsByRelease": {key: concepts[key] for key in sorted(concepts)},
        "nativeRelationTotal": 32_684,
        "nativeRelationsByRelease": {key: native_relations[key] for key in sorted(native_relations)},
        "mappingMinimumTotal": 582,
        "mappingMinimumByRelation": {
            key: _PUBLIC_V1_BASELINE_MAPPING_COUNTS[key] for key in sorted(_PUBLIC_V1_BASELINE_MAPPING_COUNTS)
        },
    }
    if _plain(expected_counts) != approved_counts:
        raise VocabularyAtlasV1ReleaseError(
            "publicV1 requires the approved 9,010 concepts, 32,684 native relations, "
            "87 planning rows, and 582 baseline mappings by predicate"
        )
    observed_baseline_runs = {
        cast(str, run["job"]): (
            cast(str, run["runReceiptFileDigest"]),
            cast(str, run["runReceiptContentDigest"]),
        )
        for run in baseline_runs
    }
    if observed_baseline_runs != _PUBLIC_V1_BASELINE_RUNS:
        raise VocabularyAtlasV1ReleaseError(
            "publicV1 requires the exact three approved 582-admission baseline receipts"
        )


def _normalize_definition_basis(value: object) -> dict[str, Any]:
    label = "v1 release definition"
    row = _require_mapping(value, label)
    schema_version = row.get("schemaVersion")
    expected_fields = _DEFINITION_BASIS_FIELDS_BY_VERSION.get(
        cast(str, schema_version)
    )
    if expected_fields is None:
        raise VocabularyAtlasV1ReleaseError(
            f"{label}.schemaVersion must be one of "
            f"{sorted(_DEFINITION_BASIS_FIELDS_BY_VERSION)}"
        )
    _require_exact_fields(row, expected_fields, label)
    if row.get("type") != VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_TYPE:
        raise VocabularyAtlasV1ReleaseError(f"{label}.type must be {VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_TYPE}")
    releases = _normalize_releases(row.get("releases"))
    release_ids = frozenset(cast(str, release["releaseId"]) for release in releases)
    release_mode = row.get("releaseMode")
    if not isinstance(release_mode, str) or release_mode not in _RELEASE_MODES:
        raise VocabularyAtlasV1ReleaseError(f"{label}.releaseMode must be publicV1 or baselineEvidenceRc")
    if schema_version == "1.0" and release_mode == "publicV1":
        raise VocabularyAtlasV1ReleaseError(f"{label}.schemaVersion 1.0 is supported only for baselineEvidenceRc")
    expected_scope_kind = "published" if release_mode == "publicV1" else "bench"
    if row.get("scopeKind") != expected_scope_kind:
        raise VocabularyAtlasV1ReleaseError(f"{label}.scopeKind must be {expected_scope_kind} for {release_mode}")
    planning_index = _normalize_planning_index(row.get("planningIndex"))
    reviewed_search_corpus = (
        _normalize_reviewed_search_corpus(
            row.get("reviewedSearchCorpus"),
            release_mode=release_mode,
        )
        if schema_version == "2.0"
        else None
    )
    expected_counts = _normalize_expected_counts(row.get("expectedCounts"), release_ids=release_ids)
    production_runs = _normalize_pair_runs(
        row.get("productionQualificationRuns"),
        f"{label}.productionQualificationRuns",
        releases=releases,
        expected_jobs=(frozenset(_PRODUCTION_JOB_ROLES) if release_mode == "publicV1" else frozenset()),
    )
    baseline_runs = _normalize_pair_runs(
        row.get("baselineQualificationRuns"),
        f"{label}.baselineQualificationRuns",
        releases=releases,
        expected_jobs=_BASELINE_JOB_NAMES,
    )
    if release_mode == "publicV1":
        _validate_public_v1_profile(
            planning_index=planning_index,
            reviewed_search_corpus=reviewed_search_corpus,
            releases=releases,
            expected_counts=expected_counts,
            baseline_runs=baseline_runs,
        )
    normalized = {
        "type": VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_TYPE,
        "schemaVersion": schema_version,
        "releaseMode": release_mode,
        "releaseName": _require_iri(row.get("releaseName"), f"{label}.releaseName"),
        "scopeName": _require_iri(row.get("scopeName"), f"{label}.scopeName"),
        "scopeKind": expected_scope_kind,
        "title": _require_text(row.get("title"), f"{label}.title"),
        "planningIndex": planning_index,
        "releases": releases,
        "relationBundles": _normalize_relation_bundles(row.get("relationBundles"), release_ids=release_ids),
        "productionQualificationRuns": production_runs,
        "baselineQualificationRuns": baseline_runs,
        "publication": _normalize_publication(row.get("publication"), releases=releases),
        "expectedCounts": expected_counts,
    }
    if reviewed_search_corpus is not None:
        normalized["reviewedSearchCorpus"] = reviewed_search_corpus
    return normalized


@dataclass(frozen=True, slots=True)
class VocabularyAtlasV1ReleaseDefinition:
    """One canonical, content-derived definition for the six-release build."""

    record: Mapping[str, Any]
    file_digest: str | None = None
    path: Path | None = None

    def __post_init__(self) -> None:
        row = _require_mapping(self.record, "v1 release definition")
        basis_fields = _DEFINITION_BASIS_FIELDS_BY_VERSION.get(
            cast(str, row.get("schemaVersion"))
        )
        if basis_fields is None:
            raise VocabularyAtlasV1ReleaseError(
                "v1 release definition schemaVersion is unsupported"
            )
        _require_exact_fields(
            row,
            basis_fields | {"id", "recordDigest"},
            "v1 release definition",
        )
        basis = _normalize_definition_basis(
            {field: row[field] for field in basis_fields}
        )
        digest = sha256_digest(_canonical_bytes(basis))
        expected = {
            **basis,
            "id": _DEFINITION_ID_PREFIX + digest.removeprefix("sha256:"),
            "recordDigest": digest,
        }
        if _plain(row) != expected:
            raise VocabularyAtlasV1ReleaseError("v1 release definition identity, inputs, or canonical order differs")
        if (self.file_digest is None) is not (self.path is None):
            raise VocabularyAtlasV1ReleaseError("v1 release definition path and file digest must be supplied together")
        if self.file_digest is not None:
            _require_digest(self.file_digest, "v1 release definition file digest")
            if self.path is None:
                raise VocabularyAtlasV1ReleaseError("v1 release definition path is required with its file digest")
            object.__setattr__(
                self,
                "path",
                Path(self.path).resolve(strict=True),
            )
        object.__setattr__(
            self,
            "record",
            cast(Mapping[str, Any], deep_freeze_json(expected)),
        )

    @classmethod
    def seal(cls, basis: Mapping[str, Any]) -> VocabularyAtlasV1ReleaseDefinition:
        """Normalize a definition basis and derive its immutable identity."""

        normalized = _normalize_definition_basis(basis)
        digest = sha256_digest(_canonical_bytes(normalized))
        return cls(
            {
                **normalized,
                "id": _DEFINITION_ID_PREFIX + digest.removeprefix("sha256:"),
                "recordDigest": digest,
            }
        )

    @property
    def identifier(self) -> str:
        return cast(str, self.record["id"])

    @property
    def record_digest(self) -> str:
        return cast(str, self.record["recordDigest"])

    def as_record(self) -> dict[str, Any]:
        return cast(dict[str, Any], _plain(self.record))

    def artifact_bytes(self) -> bytes:
        return _canonical_bytes(self.as_record())

    def write_to(self, path: Path | str) -> Path:
        """Write a newly sealed definition once so it can receive an external pin."""

        return _write_new_file(
            Path(path),
            self.artifact_bytes(),
            label="v1 release definition",
        )


def read_vocabulary_atlas_v1_release_definition(
    path: Path | str,
    *,
    expected_file_digest: str,
) -> VocabularyAtlasV1ReleaseDefinition:
    """Open one canonical tracked definition from an independent file digest."""

    digest = _require_digest(expected_file_digest, "v1 release definition file digest")
    payload = _read_regular_file(Path(path), label="v1 release definition")
    if sha256_digest(payload) != digest:
        raise VocabularyAtlasV1ReleaseError("v1 release definition file digest differs")
    value = _decode_json(payload, "v1 release definition")
    if not isinstance(value, Mapping) or _canonical_bytes(value) != payload:
        raise VocabularyAtlasV1ReleaseError("v1 release definition bytes are not canonical")
    resolved = Path(path).resolve(strict=True)
    definition = VocabularyAtlasV1ReleaseDefinition(
        value,
        file_digest=digest,
        path=resolved,
    )
    if _read_regular_file(Path(path), label="v1 release definition") != payload:
        raise VocabularyAtlasV1ReleaseError("v1 release definition changed while opening")
    return definition


def _verified_definition_bytes(
    definition: VocabularyAtlasV1ReleaseDefinition,
) -> tuple[VocabularyAtlasV1ReleaseDefinition, bytes]:
    """Reopen the independently pinned source file used to authorize a build."""

    if definition.path is None or definition.file_digest is None:
        raise VocabularyAtlasV1ReleaseError(
            "v1 build requires a path-backed definition reopened from an independent file digest"
        )
    reopened = read_vocabulary_atlas_v1_release_definition(
        definition.path,
        expected_file_digest=definition.file_digest,
    )
    if reopened.as_record() != definition.as_record():
        raise VocabularyAtlasV1ReleaseError("reopened v1 definition differs from the supplied definition")
    payload = _read_regular_file(
        reopened.path or definition.path,
        label="v1 release definition",
    )
    if sha256_digest(payload) != definition.file_digest:
        raise VocabularyAtlasV1ReleaseError("v1 release definition changed after reopening")
    return reopened, payload


def _decode_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise VocabularyAtlasV1ReleaseError(f"{label} must be valid UTF-8 JSON") from error


def _open_reviewed_search_corpus(
    definition: VocabularyAtlasV1ReleaseDefinition,
    root: Path,
) -> tuple[Mapping[str, Any] | None, Mapping[str, str]]:
    if definition.record.get("schemaVersion") == "1.0":
        return None, {"status": "legacySchemaAbsent"}
    descriptor = cast(
        Mapping[str, str],
        definition.record["reviewedSearchCorpus"],
    )
    if definition.record["releaseMode"] == "baselineEvidenceRc":
        if _plain(descriptor) != {"status": "skippedPublicOnly"}:
            raise VocabularyAtlasV1ReleaseError(
                "baselineEvidenceRc must explicitly skip the public-only reviewed search corpus"
            )
        return None, descriptor
    path = cast(str, descriptor["path"])
    digest = cast(str, descriptor["fileDigest"])
    corpus = _exact_json(
        root,
        path,
        digest,
        label="public v1 reviewed explorer search corpus",
    )
    return corpus, descriptor


def _read_regular_file(path: Path, *, label: str) -> bytes:
    if path.is_symlink():
        raise VocabularyAtlasV1ReleaseError(f"{label} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise VocabularyAtlasV1ReleaseError(f"{label} does not exist") from error
    if not resolved.is_file():
        raise VocabularyAtlasV1ReleaseError(f"{label} must be a regular file")
    return resolved.read_bytes()


def _artifact_root(path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink():
        raise VocabularyAtlasV1ReleaseError("artifact root must not be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise VocabularyAtlasV1ReleaseError("artifact root does not exist") from error
    if not resolved.is_dir():
        raise VocabularyAtlasV1ReleaseError("artifact root must be a directory")
    return resolved


def _resolve_inside(
    root: Path,
    relative: str,
    *,
    label: str,
    directory: bool = False,
) -> Path:
    path = PurePosixPath(_require_relative_path(relative, label))
    candidate = root.joinpath(*path.parts)
    cursor = root
    for part in path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise VocabularyAtlasV1ReleaseError(f"{label} must not traverse a symlink")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except FileNotFoundError as error:
        raise VocabularyAtlasV1ReleaseError(f"{label} does not exist") from error
    except ValueError as error:
        raise VocabularyAtlasV1ReleaseError(f"{label} must stay inside the artifact root") from error
    if directory and not resolved.is_dir():
        raise VocabularyAtlasV1ReleaseError(f"{label} must be a directory")
    if not directory and not resolved.is_file():
        raise VocabularyAtlasV1ReleaseError(f"{label} must be a regular file")
    return resolved


def _exact_file(
    root: Path,
    relative: str,
    digest: str,
    *,
    label: str,
) -> Path:
    path, _ = _exact_file_bytes(root, relative, digest, label=label)
    return path


def _exact_file_bytes(
    root: Path,
    relative: str,
    digest: str,
    *,
    label: str,
) -> tuple[Path, bytes]:
    path = _resolve_inside(root, relative, label=label)
    payload = path.read_bytes()
    if sha256_digest(payload) != digest:
        raise VocabularyAtlasV1ReleaseError(f"{label} differs from its exact digest")
    if path.read_bytes() != payload:
        raise VocabularyAtlasV1ReleaseError(f"{label} changed while opening")
    return path, payload


def _exact_json(
    root: Path,
    relative: str,
    digest: str,
    *,
    label: str,
) -> Mapping[str, Any]:
    _path, payload = _exact_file_bytes(root, relative, digest, label=label)
    value = _decode_json(payload, label)
    if not isinstance(value, Mapping):
        raise VocabularyAtlasV1ReleaseError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _open_planning_index(
    definition: VocabularyAtlasV1ReleaseDefinition,
    root: Path,
) -> PinnedAtlasIndex:
    descriptor = cast(Mapping[str, Any], definition.record["planningIndex"])
    index_path = _exact_file(
        root,
        cast(str, descriptor["path"]),
        cast(str, descriptor["fileDigest"]),
        label="v1 planning index",
    )
    index_input = _exact_json(
        root,
        cast(str, descriptor["inputPath"]),
        cast(str, descriptor["inputFileDigest"]),
        label="v1 planning index input",
    )
    resource_catalog = _exact_json(
        root,
        cast(str, descriptor["resourceCatalogPath"]),
        cast(str, descriptor["resourceCatalogFileDigest"]),
        label="v1 resource catalog",
    )
    repository_root = _resolve_inside(
        root,
        cast(str, descriptor["repositoryRoot"]),
        label="v1 planning-index repository root",
        directory=True,
    )
    return PinnedAtlasIndex.open(
        index_path,
        expected_file_digest=cast(str, descriptor["fileDigest"]),
        index_input=index_input,
        resource_catalog=resource_catalog,
        repository_root=repository_root,
    )


def _run_support_file(
    run_path: Path,
    descriptor: Mapping[str, Any],
    *,
    label: str,
    required: bool = True,
    require_total: bool = True,
) -> tuple[Path, bytes] | None:
    name = descriptor.get("file")
    digest = descriptor.get("fileDigest")
    total = descriptor.get("total")
    if require_total and (not isinstance(total, int) or isinstance(total, bool) or total < 0):
        raise VocabularyAtlasV1ReleaseError(f"{label}.total is invalid")
    if not isinstance(name, str) or Path(name).name != name:
        raise VocabularyAtlasV1ReleaseError(f"{label}.file is unsafe")
    if digest is None and not required and total == 0:
        return None
    expected = _require_digest(digest, f"{label}.fileDigest")
    candidate = run_path.parent / name
    if candidate.is_symlink() or not candidate.is_file():
        raise VocabularyAtlasV1ReleaseError(f"{label} is missing or unsafe")
    payload = candidate.read_bytes()
    if sha256_digest(payload) != expected or candidate.read_bytes() != payload:
        raise VocabularyAtlasV1ReleaseError(f"{label} differs from its exact pin")
    return candidate.resolve(strict=True), payload


def _verify_receipt_log(
    payload: bytes,
    *,
    expected_total: int,
    label: str,
    receipt_kind: Literal["judge", "scorer"],
    allow_legacy_epoch: bool = False,
) -> dict[tuple[str, str], dict[str, Any]]:
    from .qualification import (
        VALIDATOR_FAMILIES,
        QualificationError,
        endpoint_host,
        reading_from_receipt,
        score_reading_from_receipt,
    )

    rows = payload.splitlines(keepends=True)
    if len(rows) != expected_total:
        raise VocabularyAtlasV1ReleaseError(f"{label} row count differs")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for index, line in enumerate(rows):
        if not line.endswith(b"\n"):
            raise VocabularyAtlasV1ReleaseError(f"{label}[{index}] lacks its canonical line ending")
        value = _decode_json(line, f"{label}[{index}]")
        if not isinstance(value, Mapping) or (canonical_json(value) + "\n").encode("utf-8") != line:
            raise VocabularyAtlasV1ReleaseError(f"{label}[{index}] is not canonical JSON")
        candidate_id = _require_iri(value.get("candidate_id"), f"{label}[{index}].candidate_id")
        family_name = _require_text(value.get("family"), f"{label}[{index}].family")
        family = VALIDATOR_FAMILIES.get(family_name)
        expected_kind = "crosswalk_validation" if receipt_kind == "judge" else "crosswalk_scoring"
        request_url = _require_iri(value.get("request_url"), f"{label}[{index}].request_url")
        model_id = _require_text(value.get("model_id"), f"{label}[{index}].model_id")
        if (
            family is None
            or value.get("kind") != expected_kind
            or value.get("model_requested") != family.requested_model
            or endpoint_host(request_url) != endpoint_host(family.base_url)
        ):
            raise VocabularyAtlasV1ReleaseError(
                f"{label}[{index}] differs from its approved family, model, or endpoint"
            )
        _require_digest(value.get("input_digest"), f"{label}[{index}].input_digest")
        _require_digest(value.get("request_sha256"), f"{label}[{index}].request_sha256")
        _require_datetime(value.get("started_at"), f"{label}[{index}].started_at")
        finished_at = value.get("finished_at")
        if not (
            allow_legacy_epoch
            and isinstance(finished_at, str)
            and finished_at.isascii()
            and finished_at.isdigit()
            and int(finished_at) > 0
        ):
            _require_datetime(finished_at, f"{label}[{index}].finished_at")
        outcome = _require_text(value.get("outcome"), f"{label}[{index}].outcome")
        deterministic = False
        if outcome == "completed":
            if value.get("response_status") != 200:
                raise VocabularyAtlasV1ReleaseError(f"{label}[{index}] completed without a successful response")
            _require_digest(
                value.get("response_sha256"),
                f"{label}[{index}].response_sha256",
            )
            _require_text(
                value.get("response_model"),
                f"{label}[{index}].response_model",
            )
            try:
                reading = (
                    reading_from_receipt(value, family, model_id)
                    if receipt_kind == "judge"
                    else score_reading_from_receipt(value, family, model_id)
                )
            except QualificationError as error:
                raise VocabularyAtlasV1ReleaseError(str(error)) from error
            deterministic = bool(reading is not None and reading.deterministic_checks_passed)
            if not deterministic:
                raise VocabularyAtlasV1ReleaseError(f"{label}[{index}] completed without deterministic response checks")
        key = (candidate_id, family_name)
        if key in result:
            raise VocabularyAtlasV1ReleaseError(f"{label} repeats a candidate and validator family")
        result[key] = {
            "family": family_name,
            "modelId": model_id,
            "endpoint": endpoint_host(request_url),
            "outcome": outcome,
            "requestSha256": value["request_sha256"],
            "responseSha256": str(value.get("response_sha256") or ""),
            "receiptDigest": sha256_digest(line),
            "deterministicChecksPassed": deterministic,
            "independenceGroup": family.independence_group,
        }
    return result


def _verify_accounting_receipt_resolution(
    accounting: Sequence[Any],
    *,
    judge_receipts: Mapping[tuple[str, str], Mapping[str, Any]],
    scorer_receipts: Mapping[tuple[str, str], Mapping[str, Any]],
    label: str,
) -> None:
    judge_fields = frozenset({"family", "outcome", "receiptDigest"})
    scorer_fields = frozenset(
        {
            "family",
            "modelId",
            "endpoint",
            "outcome",
            "deterministicChecksPassed",
            "requestSha256",
            "responseSha256",
            "receiptDigest",
        }
    )
    expected_judges: dict[tuple[str, str], dict[str, Any]] = {}
    expected_scorers: dict[tuple[str, str], dict[str, Any]] = {}
    for index, raw in enumerate(accounting):
        row = _require_mapping(raw, f"{label}[{index}]")
        candidate_id = _require_iri(row.get("candidateId"), f"{label}[{index}].candidateId")
        completed_judge_groups: set[str] = set()
        for position, raw_pin in enumerate(
            _require_array(
                row.get("judgeReceipts"),
                f"{label}[{index}].judgeReceipts",
            )
        ):
            pin_label = f"{label}[{index}].judgeReceipts[{position}]"
            pin = _require_mapping(raw_pin, pin_label)
            _require_exact_fields(pin, judge_fields, pin_label)
            family = _require_text(pin.get("family"), f"{pin_label}.family")
            key = (candidate_id, family)
            if key in expected_judges:
                raise VocabularyAtlasV1ReleaseError(f"{label}[{index}] repeats a judge receipt family")
            expected = {
                "family": family,
                "outcome": _require_text(pin.get("outcome"), f"{pin_label}.outcome"),
                "receiptDigest": _require_digest(pin.get("receiptDigest"), f"{pin_label}.receiptDigest"),
            }
            actual = judge_receipts.get(key)
            if actual is None or {field: actual[field] for field in judge_fields} != expected:
                raise VocabularyAtlasV1ReleaseError(f"{pin_label} does not resolve to its exact judge receipt row")
            if actual["outcome"] == "completed" and actual["deterministicChecksPassed"] is True:
                completed_judge_groups.add(cast(str, actual["independenceGroup"]))
            expected_judges[key] = expected
        reproduced_judged = len(completed_judge_groups) >= 2
        if row.get("judged") is not reproduced_judged:
            raise VocabularyAtlasV1ReleaseError(
                f"{label}[{index}].judged does not reproduce from exact independent receipts"
            )

        reproduced_scored = False
        for position, raw_pin in enumerate(
            _require_array(
                row.get("scorerReceipts"),
                f"{label}[{index}].scorerReceipts",
            )
        ):
            pin_label = f"{label}[{index}].scorerReceipts[{position}]"
            pin = _require_mapping(raw_pin, pin_label)
            _require_exact_fields(pin, scorer_fields, pin_label)
            family = _require_text(pin.get("family"), f"{pin_label}.family")
            key = (candidate_id, family)
            if key in expected_scorers:
                raise VocabularyAtlasV1ReleaseError(f"{label}[{index}] repeats a scorer receipt family")
            expected = {field: _plain(pin[field]) for field in scorer_fields}
            actual = scorer_receipts.get(key)
            if actual is None or {field: actual[field] for field in scorer_fields} != expected:
                raise VocabularyAtlasV1ReleaseError(f"{pin_label} does not resolve to its exact scorer receipt row")
            reproduced_scored = reproduced_scored or (
                actual["outcome"] == "completed" and actual["deterministicChecksPassed"] is True
            )
            expected_scorers[key] = expected
        if row.get("scored") is not reproduced_scored:
            raise VocabularyAtlasV1ReleaseError(
                f"{label}[{index}].scored does not reproduce from exact scorer receipts"
            )
    if set(expected_judges) != set(judge_receipts):
        raise VocabularyAtlasV1ReleaseError(f"{label} judge receipt log has missing or extra rows")
    if set(expected_scorers) != set(scorer_receipts):
        raise VocabularyAtlasV1ReleaseError(f"{label} scorer receipt log has missing or extra rows")


def _verify_pair_qualification_run(
    descriptor: Mapping[str, Any],
    *,
    root: Path,
    releases: Mapping[str, ConceptReleaseSource],
    production: bool,
) -> dict[str, Any]:
    from .qualification import (
        PILOT_COVERAGE_MODE,
        PRODUCTION_COVERAGE_MODE,
        QualificationError,
        validate_qualification_run_receipt,
        verify_candidate_accounting_catalog_lineage,
    )

    job = cast(str, descriptor["job"])
    run_path, payload = _exact_file_bytes(
        root,
        cast(str, descriptor["runReceiptPath"]),
        cast(str, descriptor["runReceiptFileDigest"]),
        label=f"v1 qualification job {job} run receipt",
    )
    record = _decode_json(payload, f"v1 qualification job {job} run receipt")
    if not isinstance(record, Mapping) or (canonical_json(record) + "\n").encode("utf-8") != payload:
        raise VocabularyAtlasV1ReleaseError(f"v1 qualification job {job} run receipt is not canonical")
    try:
        run = validate_qualification_run_receipt(record)
    except QualificationError as error:
        raise VocabularyAtlasV1ReleaseError(str(error)) from error
    if run.get("contentDigest") != descriptor["runReceiptContentDigest"]:
        raise VocabularyAtlasV1ReleaseError(f"v1 qualification job {job} content digest differs")
    expected_coverage = PRODUCTION_COVERAGE_MODE if production else PILOT_COVERAGE_MODE
    if run.get("coverageMode") != expected_coverage:
        raise VocabularyAtlasV1ReleaseError(f"v1 qualification job {job} has the wrong coverage mode")
    if production and run.get("productionReady") is not True:
        raise VocabularyAtlasV1ReleaseError(f"v1 qualification job {job} is not production ready")
    if not production and run.get("productionReady") is not False:
        raise VocabularyAtlasV1ReleaseError(f"baseline qualification job {job} must remain non-production evidence")

    source = releases[cast(str, descriptor["sourceReleaseId"])]
    target = releases[cast(str, descriptor["targetReleaseId"])]
    expected_manifest_digests = (
        cast(str, source.pin()["manifestDigest"]),
        cast(str, target.pin()["manifestDigest"]),
    )
    approved_baseline = _PUBLIC_V1_BASELINE_RUNS.get(job)
    uses_approved_baseline = not production and approved_baseline == (
        descriptor["runReceiptFileDigest"],
        descriptor["runReceiptContentDigest"],
    )
    if uses_approved_baseline:
        expected_manifest_digests = _PUBLIC_V1_BASELINE_ENDPOINT_MANIFEST_DIGESTS[job]
    if (
        run.get("sourceManifestDigest"),
        run.get("targetManifestDigest"),
    ) != expected_manifest_digests:
        raise VocabularyAtlasV1ReleaseError(f"v1 qualification job {job} names unapproved endpoint manifest digests")
    if production and (
        run.get("sourceManifestDigest") != source.pin()["manifestDigest"]
        or run.get("targetManifestDigest") != target.pin()["manifestDigest"]
    ):
        raise VocabularyAtlasV1ReleaseError(f"v1 qualification job {job} names another exact release pair")

    bundle_row = _require_mapping(run.get("bundle"), f"v1 qualification job {job} bundle")
    bundle_file = _run_support_file(
        run_path,
        bundle_row,
        label=f"v1 qualification job {job} CrosswalkBundle",
        require_total=False,
    )
    assert bundle_file is not None
    bundle_path, _bundle_payload = bundle_file
    bundle = CrosswalkBundle.open(
        bundle_path,
        expected_file_digest=_require_digest(
            bundle_row.get("fileDigest"),
            f"v1 qualification job {job} bundle.fileDigest",
        ),
        expected_bundle_digest=_require_digest(
            bundle_row.get("bundleDigest"),
            f"v1 qualification job {job} bundle.bundleDigest",
        ),
    )
    if bundle.identifier != bundle_row.get("id"):
        raise VocabularyAtlasV1ReleaseError(f"v1 qualification job {job} CrosswalkBundle identity differs")
    candidate_rows = _require_array(
        bundle.to_dict().get("mappingCandidates"),
        f"v1 qualification job {job} Crosswalk candidates",
    )
    if any(
        not isinstance(candidate, Mapping)
        or candidate.get("sourceRelease") != descriptor["sourceReleaseId"]
        or candidate.get("targetRelease") != descriptor["targetReleaseId"]
        for candidate in candidate_rows
    ):
        raise VocabularyAtlasV1ReleaseError(
            f"v1 qualification job {job} Crosswalk candidates name another release identity"
        )

    catalog_row = _require_mapping(
        run.get("candidateCatalog"),
        f"v1 qualification job {job} candidate catalog",
    )
    if production:
        expected_catalog_total, expected_catalog_digest = _PUBLIC_V1_PRODUCTION_CATALOGS[job]
        if (
            catalog_row.get("total") != expected_catalog_total
            or catalog_row.get("fileDigest") != expected_catalog_digest
        ):
            raise VocabularyAtlasV1ReleaseError(
                f"publicV1 qualification job {job} must use its exact prepared production catalog"
            )
    catalog_file = _run_support_file(
        run_path,
        catalog_row,
        label=f"v1 qualification job {job} candidate catalog",
    )
    assert catalog_file is not None
    _catalog_path, catalog_payload = catalog_file
    catalog = _decode_json(catalog_payload, f"v1 qualification job {job} candidate catalog")
    if not isinstance(catalog, Mapping) or (canonical_json(catalog) + "\n").encode("utf-8") != catalog_payload:
        raise VocabularyAtlasV1ReleaseError(f"v1 qualification job {job} candidate catalog is not canonical")

    provider_batch_evidence = run.get("providerBatchEvidence")
    if (
        production
        and (
            not isinstance(provider_batch_evidence, Mapping)
            or set(provider_batch_evidence) != {"judging", "scoring"}
        )
    ):
        raise VocabularyAtlasV1ReleaseError(
            f"publicV1 qualification job {job} must pin judging and scoring provider batch evidence"
        )

    receipt_row = _require_mapping(run.get("receiptLog"), f"v1 qualification job {job} judge receipt log")
    receipt_total = _require_count(receipt_row.get("total"), f"v1 qualification job {job} receiptLog.total")
    receipt_file = _run_support_file(
        run_path,
        receipt_row,
        label=f"v1 qualification job {job} judge receipt log",
        required=receipt_total > 0,
    )
    judge_receipts: dict[tuple[str, str], dict[str, Any]] = {}
    if receipt_file is not None:
        _receipt_path, receipt_payload = receipt_file
        judge_receipts = _verify_receipt_log(
            receipt_payload,
            expected_total=receipt_total,
            label=f"v1 qualification job {job} judge receipt log",
            receipt_kind="judge",
            allow_legacy_epoch=uses_approved_baseline,
        )

    scoring = _require_mapping(run.get("scoring"), f"v1 qualification job {job} scoring")
    scoring_row = _require_mapping(
        scoring.get("receiptLog"),
        f"v1 qualification job {job} scorer receipt log",
    )
    scoring_total = _require_count(
        scoring_row.get("total"),
        f"v1 qualification job {job} scoring.receiptLog.total",
    )
    scoring_file = _run_support_file(
        run_path,
        scoring_row,
        label=f"v1 qualification job {job} scorer receipt log",
        required=scoring_total > 0,
    )
    scorer_receipts: dict[tuple[str, str], dict[str, Any]] = {}
    if scoring_file is not None:
        _scoring_path, scoring_payload = scoring_file
        scorer_receipts = _verify_receipt_log(
            scoring_payload,
            expected_total=scoring_total,
            label=f"v1 qualification job {job} scorer receipt log",
            receipt_kind="scorer",
            allow_legacy_epoch=uses_approved_baseline,
        )

    if provider_batch_evidence is not None:
        from .qualification_batch import BatchError, verify_run_provider_batch_evidence

        try:
            verify_run_provider_batch_evidence(run_path, run)
        except BatchError as error:
            raise VocabularyAtlasV1ReleaseError(str(error)) from error

    counts = _require_mapping(run.get("counts"), f"v1 qualification job {job} counts")
    if production and counts.get("generated") != expected_catalog_total:
        raise VocabularyAtlasV1ReleaseError(
            f"publicV1 qualification job {job} generated count differs from its exact catalog"
        )
    accounting = _require_array(
        run.get("candidateAccounting"),
        f"v1 qualification job {job} candidate accounting",
    )
    _verify_accounting_receipt_resolution(
        accounting,
        judge_receipts=judge_receipts,
        scorer_receipts=scorer_receipts,
        label=f"v1 qualification job {job} candidate accounting",
    )
    catalog_candidates = _require_array(
        catalog.get("candidates"),
        f"v1 qualification job {job} candidate catalog.candidates",
    )
    if production:
        try:
            verify_candidate_accounting_catalog_lineage(
                accounting,
                catalog_candidates,
            )
        except QualificationError as error:
            raise VocabularyAtlasV1ReleaseError(
                f"v1 qualification job {job} candidate accounting differs from its exact catalog: {error}"
            ) from error
    catalog_ids = [
        _require_iri(
            _require_mapping(
                row,
                f"v1 qualification job {job} candidate catalog.candidates[{index}]",
            ).get("candidateId"),
            f"v1 qualification job {job} candidate catalog.candidates[{index}].candidateId",
        )
        for index, row in enumerate(catalog_candidates)
    ]
    bundle_ids = [
        _require_iri(
            cast(Mapping[str, Any], row).get("id"),
            f"v1 qualification job {job} Crosswalk candidate id",
        )
        for row in candidate_rows
    ]
    accounting_ids = [
        _require_iri(
            _require_mapping(row, f"v1 qualification job {job} candidate accounting[{index}]").get("candidateId"),
            f"v1 qualification job {job} candidate accounting[{index}].candidateId",
        )
        for index, row in enumerate(accounting)
    ]
    if (
        len(catalog_ids) != len(set(catalog_ids))
        or len(bundle_ids) != len(set(bundle_ids))
        or len(accounting_ids) != len(set(accounting_ids))
        or set(catalog_ids) != set(bundle_ids)
        or set(bundle_ids) != set(accounting_ids)
        or (
            catalog.get("coverageMode") != run.get("coverageMode")
            and not (uses_approved_baseline and catalog.get("coverageMode") is None)
        )
        or catalog.get("generationPolicy") != run.get("candidateGenerationPolicy")
    ):
        raise VocabularyAtlasV1ReleaseError(
            f"v1 qualification job {job} catalog, Crosswalk bundle, and accounting do not close"
        )
    if production:
        accounting_by_id = {
            cast(str, row["candidateId"]): row
            for row in accounting
            if isinstance(row, Mapping)
        }
        accounted_admissions = {
            candidate_id: cast(str, row["relation"])
            for candidate_id, row in accounting_by_id.items()
            if row.get("disposition") == "admitted"
        }
        expected_admissions = {
            candidate_id: relation
            for candidate_id, relation in bundle.adjudicated_relations().items()
            if accounting_by_id[candidate_id].get("control") is False
        }
        if accounted_admissions != expected_admissions:
            raise VocabularyAtlasV1ReleaseError(
                f"v1 qualification job {job} Crosswalk adjudications differ from run admissions"
            )
    admitted_candidates = sorted(
        (
            {
                "candidateId": _require_iri(
                    row.get("candidateId"),
                    f"v1 qualification job {job} admitted candidate id",
                ),
                "relation": _require_iri(
                    row.get("relation"),
                    f"v1 qualification job {job} admitted candidate relation",
                ),
            }
            for row in accounting
            if isinstance(row, Mapping) and row.get("disposition") == "admitted"
        ),
        key=lambda row: (row["candidateId"], row["relation"]),
    )
    return {
        "job": job,
        "runKind": "production" if production else "baselineEvidence",
        "sourceReleaseId": descriptor["sourceReleaseId"],
        "targetReleaseId": descriptor["targetReleaseId"],
        "id": run["id"],
        "runReceiptPath": descriptor["runReceiptPath"],
        "contentDigest": run["contentDigest"],
        "fileDigest": descriptor["runReceiptFileDigest"],
        "counts": _plain(counts),
        "admittedCandidates": admitted_candidates,
    }


def _verify_qualification_runs(
    definition: VocabularyAtlasV1ReleaseDefinition,
    *,
    root: Path,
    releases: Mapping[str, ConceptReleaseSource],
) -> tuple[
    list[dict[str, Any]],
    frozenset[tuple[str, str, str]],
    frozenset[tuple[str, str, str, str, str]],
]:
    pins: list[dict[str, Any]] = []
    authorized_receipts: set[tuple[str, str, str]] = set()
    admitted_candidates: set[tuple[str, str, str, str, str]] = set()
    groups = (
        ("productionQualificationRuns", True),
        ("baselineQualificationRuns", False),
    )
    for field, production in groups:
        for descriptor in cast(Sequence[Mapping[str, Any]], definition.record[field]):
            pin = _verify_pair_qualification_run(
                descriptor,
                root=root,
                releases=releases,
                production=production,
            )
            pins.append(pin)
            receipt_key = (
                cast(str, descriptor["runReceiptPath"]),
                cast(str, descriptor["runReceiptFileDigest"]),
                cast(str, descriptor["runReceiptContentDigest"]),
            )
            authorized_receipts.add(receipt_key)
            for admission in cast(Sequence[Mapping[str, Any]], pin["admittedCandidates"]):
                admission_key = (
                    *receipt_key,
                    cast(str, admission["candidateId"]),
                    cast(str, admission["relation"]),
                )
                if admission_key in admitted_candidates:
                    raise VocabularyAtlasV1ReleaseError("v1 qualification jobs repeat an admitted candidate proof")
                admitted_candidates.add(admission_key)
    ids = [cast(str, pin["id"]) for pin in pins]
    if len(ids) != len(set(ids)):
        raise VocabularyAtlasV1ReleaseError("v1 qualification jobs must pin distinct run receipts")
    return (
        sorted(pins, key=lambda pin: (pin["runKind"], pin["job"])),
        frozenset(authorized_receipts),
        frozenset(admitted_candidates),
    )


def _write_new_file(path: Path, payload: bytes, *, label: str) -> Path:
    if path.exists() or path.is_symlink():
        raise VocabularyAtlasV1ReleaseError(f"{label} already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path


def _federal_register_related_reconciliation(
    definition: VocabularyAtlasV1ReleaseDefinition,
    root: Path,
) -> dict[str, Any]:
    """Derive the complete Related-reference accounting from the exact source."""

    release = next(
        cast(Mapping[str, Any], row)
        for row in cast(Sequence[Mapping[str, Any]], definition.record["releases"])
        if row["v1Role"] == "federalRegisterThesaurus"
    )
    manifest_path = _exact_file(
        root,
        cast(str, release["manifestPath"]),
        cast(str, release["manifestDigest"]),
        label="v1 Federal Register managed-release manifest",
    )
    try:
        view = FederalRegisterThesaurus2025ManagedReleaseView.open(manifest_path)
    except FederalRegisterThesaurus2025ManagedReleaseError as error:
        raise VocabularyAtlasV1ReleaseError(str(error)) from error
    status_counts = Counter(row.get("resolutionStatus") for row in view.relations)
    if status_counts != Counter(_FEDERAL_REGISTER_RELATED_REFERENCE_COUNTS):
        raise VocabularyAtlasV1ReleaseError(
            "v1 Federal Register Related references must reconcile as "
            "1,451 resolved links, 11 suggested open-term patterns, and one "
            "unresolved target"
        )
    _exact_file(
        root,
        cast(str, release["manifestPath"]),
        cast(str, release["manifestDigest"]),
        label="v1 Federal Register managed-release manifest",
    )
    counts = {
        "resolvedConceptLinks": status_counts["resolved"],
        "suggestedOpenTermPatterns": status_counts["suggestedOpenTermPattern"],
        "unresolvedTargets": status_counts["unresolved"],
        "sourceReferenceTotal": sum(status_counts.values()),
    }
    basis = {
        "role": "federalRegisterRelatedReferenceReconciliation",
        "releaseId": release["releaseId"],
        "manifestDigest": release["manifestDigest"],
        "counts": counts,
    }
    digest = sha256_digest(_canonical_bytes(basis))
    return {
        **basis,
        "id": _FEDERAL_REGISTER_RECONCILIATION_ID_PREFIX + digest.removeprefix("sha256:"),
        "contentDigest": digest,
    }


def _open_releases(
    definition: VocabularyAtlasV1ReleaseDefinition,
    root: Path,
    assignment_directory: Path,
    *,
    materialize_assignments: bool = True,
) -> tuple[
    tuple[AtlasScopeRelease, ...],
    Mapping[str, ConceptReleaseSource],
    Mapping[str, str],
]:
    scope_releases: list[AtlasScopeRelease] = []
    sources: dict[str, ConceptReleaseSource] = {}
    labels: dict[str, str] = {}
    for raw in cast(Sequence[Mapping[str, Any]], definition.record["releases"]):
        key = cast(str, raw["key"])
        kind = cast(ReleaseKind, raw["kind"])
        release_id = cast(str, raw["releaseId"])
        manifest_digest = cast(str, raw["manifestDigest"])
        manifest_path = _exact_file(
            root,
            cast(str, raw["manifestPath"]),
            manifest_digest,
            label=f"v1 release {key} manifest",
        )
        if kind == "sourceConceptRelease":
            source: ConceptReleaseSource = PinnedSourceConceptRelease.open(
                manifest_path,
                expected_manifest_digest=manifest_digest,
            )
        else:
            assignment_values = cast(Mapping[str, Any], raw["ringAssignment"])
            assignment = ManagedReleaseRingAssignment(
                managed_manifest_digest=manifest_digest,
                release_id=release_id,
                semantic_ring=cast(Any, raw["semanticRing"]),
                assigned_by=cast(str, assignment_values["assignedBy"]),
                assigned_at=cast(str, assignment_values["assignedAt"]),
                evidence=tuple(cast(Sequence[str], assignment_values["evidence"])),
            )
            assignment_path = assignment_directory / f"{key}.json"
            if materialize_assignments:
                assignment.write_to(assignment_path)
            else:
                payload = _read_regular_file(
                    assignment_path,
                    label=f"v1 release {key} ring assignment",
                )
                if payload != assignment.artifact_bytes():
                    raise VocabularyAtlasV1ReleaseError(f"v1 release {key} ring assignment differs from its definition")
            pinned_assignment = PinnedManagedReleaseRingAssignment.open(
                assignment_path,
                expected_file_digest=sha256_digest(assignment.artifact_bytes()),
            )
            release_class = {
                "managedConceptRelease": PinnedManagedConceptRelease,
                "federalRegisterManagedConceptRelease": PinnedFederalRegisterManagedConceptRelease,
                "icpsrManagedConceptRelease": PinnedIcpsrManagedConceptRelease,
            }[kind]
            source = release_class.open(
                manifest_path,
                expected_manifest_digest=manifest_digest,
                release_id=release_id,
                ring_assignment=pinned_assignment,
            )
        pin = source.pin()
        if (
            pin.get("releaseId") != release_id
            or pin.get("manifestDigest") != manifest_digest
            or pin.get("semanticRing") != raw["semanticRing"]
        ):
            raise VocabularyAtlasV1ReleaseError(f"v1 release {key} differs from its definition")
        scope_releases.append(AtlasScopeRelease(source))
        sources[release_id] = source
        labels[release_id] = cast(str, raw["label"])
    return tuple(scope_releases), sources, labels


def _record_public_mapping_proof(
    mapping: Any,
    *,
    evidence_by_id: Mapping[str, Any],
    approved_proof_ids: set[str],
    used_proof_ids: set[str],
) -> None:
    """Require one distinct approved admission proof for one public mapping."""

    pending = list(mapping.evidence)
    supporting_proofs: set[str] = set()
    visited: set[str] = set()
    while pending:
        evidence_id = pending.pop()
        if evidence_id in visited:
            continue
        visited.add(evidence_id)
        evidence = evidence_by_id[evidence_id]
        if evidence.evidence_class == "operatorAdopted":
            pending.append(cast(str, evidence.adopted_evidence))
        elif evidence.evidence_class in {
            "machineQualified",
            "machineReviewed",
        }:
            supporting_proofs.add(cast(str, evidence.machine_proof))
    if len(supporting_proofs) != 1 or not supporting_proofs <= approved_proof_ids:
        raise VocabularyAtlasV1ReleaseError(
            "publicV1 mappings must each resolve to exactly one approved baseline or production admission"
        )
    proof_id = next(iter(supporting_proofs))
    if proof_id in used_proof_ids:
        raise VocabularyAtlasV1ReleaseError("publicV1 mapping assertions reuse an admitted candidate proof")
    used_proof_ids.add(proof_id)


def _open_relation_bundles(
    definition: VocabularyAtlasV1ReleaseDefinition,
    root: Path,
    release_sources: Mapping[str, ConceptReleaseSource],
    authorized_run_receipts: frozenset[tuple[str, str, str]],
    required_admitted_candidates: frozenset[tuple[str, str, str, str, str]],
) -> tuple[PinnedRelationAssertionBundle, ...]:
    result: list[PinnedRelationAssertionBundle] = []
    represented_admissions: set[tuple[str, str, str, str, str]] = set()
    approved_proof_ids: set[str] = set()
    used_proof_ids: set[str] = set()
    public_v1 = definition.record["releaseMode"] == "publicV1"
    for raw in cast(Sequence[Mapping[str, Any]], definition.record["relationBundles"]):
        key = cast(str, raw["key"])
        proofs: list[PinnedCrosswalkMachineProof] = []
        for proof_row in cast(Sequence[Mapping[str, Any]], raw["machineProofs"]):
            crosswalk_path = _exact_file(
                root,
                cast(str, proof_row["crosswalkPath"]),
                cast(str, proof_row["crosswalkFileDigest"]),
                label=f"v1 relation {key} CrosswalkBundle",
            )
            run = cast(Mapping[str, Any], proof_row["qualificationRun"])
            run_key = (
                cast(str, run["path"]),
                cast(str, run["fileDigest"]),
                cast(str, run["contentDigest"]),
            )
            if run_key not in authorized_run_receipts:
                raise VocabularyAtlasV1ReleaseError(f"v1 relation {key} proof uses an undeclared qualification run")
            run_path = _exact_file(
                root,
                cast(str, run["path"]),
                cast(str, run["fileDigest"]),
                label=f"v1 relation {key} qualification run",
            )
            proof = PinnedCrosswalkMachineProof.qualified(
                crosswalk_path,
                expected_file_digest=cast(str, proof_row["crosswalkFileDigest"]),
                expected_bundle_digest=cast(str, proof_row["crosswalkBundleDigest"]),
                candidate_id=cast(str, proof_row["candidateId"]),
                qualification_run_path=run_path,
                expected_qualification_run_file_digest=cast(str, run["fileDigest"]),
                expected_qualification_run_content_digest=cast(str, run["contentDigest"]),
            )
            facts = proof.verified_facts()
            if not {facts.source_release, facts.target_release} <= set(raw["releaseIds"]):
                raise VocabularyAtlasV1ReleaseError(f"v1 relation {key} proof endpoints are outside its descriptor")
            admission_key = (
                *run_key,
                cast(str, proof_row["candidateId"]),
                facts.relation,
            )
            if admission_key in represented_admissions:
                raise VocabularyAtlasV1ReleaseError("v1 relation bundles repeat an admitted run candidate proof")
            represented_admissions.add(admission_key)
            approved_proof_ids.add(facts.identifier)
            proofs.append(proof)
        manifest_path = _exact_file(
            root,
            cast(str, raw["manifestPath"]),
            cast(str, raw["manifestDigest"]),
            label=f"v1 relation {key} manifest",
        )
        release_ids = cast(Sequence[str], raw["releaseIds"])
        bundle = PinnedRelationAssertionBundle.open(
            manifest_path,
            expected_manifest_digest=cast(str, raw["manifestDigest"]),
            release_sources=tuple(release_sources[release_id] for release_id in release_ids),
            machine_proof_sources=tuple(proofs),
        )
        if bundle.semantic_ring != raw["semanticRing"]:
            raise VocabularyAtlasV1ReleaseError(f"v1 relation {key} semantic ring differs from its descriptor")
        verified = bundle.verified_bundle()
        if any(
            mapping.lifecycle_status != "current" or mapping.supersedes
            for mapping in verified.mapping_assertions
        ):
            raise VocabularyAtlasV1ReleaseError(
                "v1 mapping assertions require lifecycleStatus current and empty supersedes"
            )
        if public_v1:
            evidence_by_id = {evidence.identifier: evidence for evidence in verified.evidence_assertions}
            for mapping in verified.mapping_assertions:
                _record_public_mapping_proof(
                    mapping,
                    evidence_by_id=evidence_by_id,
                    approved_proof_ids=approved_proof_ids,
                    used_proof_ids=used_proof_ids,
                )
        result.append(bundle)
    if represented_admissions != set(required_admitted_candidates):
        missing = len(set(required_admitted_candidates) - represented_admissions)
        extra = len(represented_admissions - set(required_admitted_candidates))
        raise VocabularyAtlasV1ReleaseError(
            "v1 relation-bundle machine proofs must exactly represent every admitted "
            f"qualification candidate; missing={missing}, extra={extra}"
        )
    if public_v1 and used_proof_ids != approved_proof_ids:
        raise VocabularyAtlasV1ReleaseError(
            "publicV1 mapping assertions must preserve every admitted candidate and no unrelated assertion"
        )
    return tuple(result)


def _rows_by_key(
    rows: object,
    *,
    key: str,
    label: str,
) -> dict[str, int]:
    values = _require_array(rows, label)
    result: dict[str, int] = {}
    for index, raw in enumerate(values):
        row = _require_mapping(raw, f"{label}[{index}]")
        name = _require_text(row.get(key), f"{label}[{index}].{key}")
        if name in result:
            raise VocabularyAtlasV1ReleaseError(f"{label} repeats {name!r}")
        result[name] = _require_count(row.get("count"), f"{label}[{index}].count")
    return result


def validate_vocabulary_atlas_v1_acceptance(
    definition: VocabularyAtlasV1ReleaseDefinition,
    acceptance: VocabularyAtlasReleaseAcceptance,
) -> None:
    """Check v1's exact release counts, mapping floors, and reproducibility."""

    expected = cast(Mapping[str, Any], definition.record["expectedCounts"])
    counts = _require_mapping(acceptance.record.get("counts"), "v1 acceptance counts")
    concepts = _require_mapping(counts.get("concepts"), "v1 acceptance concepts")
    native = _require_mapping(counts.get("nativeRelations"), "v1 acceptance nativeRelations")
    mappings = _require_mapping(counts.get("mappingAssertions"), "v1 acceptance mappingAssertions")
    facets = _require_mapping(counts.get("facets"), "v1 acceptance facets")
    concept_by_release = _rows_by_key(
        concepts.get("byRelease"),
        key="releaseId",
        label="v1 acceptance concepts.byRelease",
    )
    native_by_release = _rows_by_key(
        native.get("byRelease"),
        key="releaseId",
        label="v1 acceptance nativeRelations.byRelease",
    )
    mapping_by_relation = _rows_by_key(
        mappings.get("byRelation"),
        key="value",
        label="v1 acceptance mappingAssertions.byRelation",
    )
    exact_pairs = (
        (concepts.get("total"), expected["conceptTotal"], "concept total"),
        (
            native.get("total"),
            expected["nativeRelationTotal"],
            "native-relation total",
        ),
        (
            facets.get("rowCount"),
            expected["planningRowCount"],
            "planning-row total",
        ),
        (
            facets.get("includedReleaseRowCount"),
            expected["includedPlanningRowCount"],
            "included planning-row total",
        ),
    )
    for observed, wanted, label in exact_pairs:
        if observed != wanted:
            raise VocabularyAtlasV1ReleaseError(f"v1 {label} is {observed!r}; expected {wanted!r}")
    if concept_by_release != _plain(expected["conceptsByRelease"]):
        raise VocabularyAtlasV1ReleaseError("v1 concept counts by release differ from the release definition")
    if native_by_release != _plain(expected["nativeRelationsByRelease"]):
        raise VocabularyAtlasV1ReleaseError("v1 native-relation counts by release differ from the release definition")
    if len(concept_by_release) != expected["releaseCount"]:
        raise VocabularyAtlasV1ReleaseError("v1 acceptance does not contain exactly six release snapshots")
    mapping_total = _require_count(mappings.get("total"), "v1 acceptance mappingAssertions.total")
    if mapping_total < expected["mappingMinimumTotal"]:
        raise VocabularyAtlasV1ReleaseError("v1 mapping count is below its declared release floor")
    for relation, minimum in cast(Mapping[str, int], expected["mappingMinimumByRelation"]).items():
        if mapping_by_relation.get(relation, 0) < minimum:
            raise VocabularyAtlasV1ReleaseError(f"v1 mapping count for {relation} is below its declared floor")

    evidence = _require_mapping(counts.get("evidence"), "v1 acceptance evidence")
    machine_proof_total = _require_count(
        evidence.get("machineProofTotal"),
        "v1 acceptance evidence.machineProofTotal",
    )
    reproducibility_rows = _require_array(
        acceptance.record.get("reproducibility"),
        "v1 acceptance reproducibility",
    )
    statuses = {
        cast(str, _require_mapping(row, "v1 acceptance reproducibility row")["layer"]): cast(
            str, _require_mapping(row, "v1 acceptance reproducibility row")["status"]
        )
        for row in reproducibility_rows
    }
    for layer in (
        "planningIndex",
        "sourceConceptReleases",
        "scope",
        "atlas",
        "explorer",
    ):
        if statuses.get(layer) != "reproduced":
            raise VocabularyAtlasV1ReleaseError(f"v1 deterministic layer {layer} was not reproduced")
    expected_machine_status = "pinnedNonReproducible" if machine_proof_total else "notApplicable"
    if statuses.get("machineQualificationEvidence") != expected_machine_status:
        raise VocabularyAtlasV1ReleaseError("v1 machine-evidence reproducibility status differs from its contents")


def _artifact_role(path: str) -> str:
    name = PurePosixPath(path).name
    if path.startswith("control/ring-assignments/"):
        return "managedReleaseRingAssignment"
    return {
        "atlas-scope.json": "vocabularyAtlasScope",
        "atlas-manifest.json": "vocabularyAtlasManifest",
        "atlas.nq": "vocabularyAtlasData",
        "publication-decision.json": "publicationDecision",
        "publication-manifest.json": "publicationManifest",
        "explorer-acceptance.json": "explorerAcceptance",
        "release-acceptance.json": "releaseAcceptance",
    }.get(name, "publicationMember")


def _generated_artifacts(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise VocabularyAtlasV1ReleaseError("generated v1 release must not contain symlinks")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        result.append(
            {
                "path": relative,
                "role": _artifact_role(relative),
                "fileDigest": sha256_digest(payload),
                "byteLength": len(payload),
            }
        )
    return result


def _seal_build_result(basis: Mapping[str, Any]) -> dict[str, Any]:
    schema_version = basis.get("schemaVersion")
    basis_fields = _BUILD_RESULT_BASIS_FIELDS_BY_VERSION.get(
        cast(str, schema_version)
    )
    if basis_fields is None:
        raise VocabularyAtlasV1ReleaseError(
            "v1 build result basis schemaVersion is unsupported"
        )
    _require_exact_fields(
        basis,
        basis_fields,
        "v1 build result basis",
    )
    digest = sha256_digest(_canonical_bytes(basis))
    return {
        **_plain(basis),
        "id": _BUILD_RESULT_ID_PREFIX + digest.removeprefix("sha256:"),
        "recordDigest": digest,
    }


def _validate_build_result(value: object) -> dict[str, Any]:
    row = _require_mapping(value, "v1 build result")
    basis_fields = _BUILD_RESULT_BASIS_FIELDS_BY_VERSION.get(
        cast(str, row.get("schemaVersion"))
    )
    if basis_fields is None:
        raise VocabularyAtlasV1ReleaseError(
            "v1 build result schemaVersion is unsupported"
        )
    _require_exact_fields(
        row,
        basis_fields | {"id", "recordDigest"},
        "v1 build result",
    )
    if row.get("type") != VOCABULARY_ATLAS_V1_BUILD_RESULT_TYPE:
        raise VocabularyAtlasV1ReleaseError("v1 build result type is unsupported")
    mode = row.get("releaseMode")
    if mode not in _RELEASE_MODES:
        raise VocabularyAtlasV1ReleaseError("v1 build result releaseMode is unsupported")
    expected_status = "passed" if mode == "publicV1" else "baselineEvidenceOnly"
    if row.get("status") != expected_status:
        raise VocabularyAtlasV1ReleaseError(f"v1 build result status must be {expected_status} for {mode}")
    basis = {field: _plain(row[field]) for field in basis_fields}
    expected = _seal_build_result(basis)
    if _plain(row) != expected:
        raise VocabularyAtlasV1ReleaseError("v1 build result identity or content digest differs")
    return expected


def _verified_output_directory(path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink():
        raise VocabularyAtlasV1ReleaseError("v1 output directory must not be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise VocabularyAtlasV1ReleaseError("v1 output directory does not exist") from error
    if not resolved.is_dir():
        raise VocabularyAtlasV1ReleaseError("v1 output must be a directory")
    return resolved


def _verify_artifact_inventory(
    output: Path,
    result: Mapping[str, Any],
) -> None:
    expected_rows = _require_array(result.get("artifacts"), "v1 build result artifacts")
    expected: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(expected_rows):
        row = _require_mapping(raw, f"v1 build result artifacts[{index}]")
        _require_exact_fields(
            row,
            frozenset({"path", "role", "fileDigest", "byteLength"}),
            f"v1 build result artifacts[{index}]",
        )
        path = _require_relative_path(row.get("path"), f"v1 build result artifacts[{index}].path")
        if path == "build-result.json" or path in expected:
            raise VocabularyAtlasV1ReleaseError("v1 build result artifact inventory repeats or self-lists a path")
        expected[path] = row

    observed_rows = [row for row in _generated_artifacts(output) if row["path"] != "build-result.json"]
    observed = {cast(str, row["path"]): row for row in observed_rows}
    if set(observed) != set(expected):
        raise VocabularyAtlasV1ReleaseError("v1 output has missing, unlisted, or extra generated files")
    for path, row in expected.items():
        if _plain(row) != observed[path]:
            raise VocabularyAtlasV1ReleaseError(f"v1 output artifact {path} differs from its build-result pin")


@dataclass(frozen=True, slots=True)
class VocabularyAtlasV1Build:
    """The reopened result of one successful atomic v1 build."""

    output_directory: Path
    result: Mapping[str, Any]
    result_file_digest: str

    @property
    def identifier(self) -> str:
        return cast(str, self.result["id"])


def open_vocabulary_atlas_v1_build(
    output_directory: Path | str,
    *,
    artifact_root: Path | str,
    expected_result_file_digest: str,
) -> VocabularyAtlasV1Build:
    """Reopen every generated file and reproduce the complete placed build."""

    output = _verified_output_directory(output_directory)
    expected_digest = _require_digest(expected_result_file_digest, "v1 build-result file digest")
    result_payload = _read_regular_file(output / "build-result.json", label="v1 build result")
    if sha256_digest(result_payload) != expected_digest:
        raise VocabularyAtlasV1ReleaseError("v1 build-result file digest differs")
    value = _decode_json(result_payload, "v1 build result")
    if not isinstance(value, Mapping) or _canonical_bytes(value) != result_payload:
        raise VocabularyAtlasV1ReleaseError("v1 build result bytes are not canonical")
    result = _validate_build_result(value)
    _verify_artifact_inventory(output, result)

    definition_pin = _require_mapping(result.get("releaseDefinition"), "v1 build result releaseDefinition")
    definition_relative = _require_relative_path(definition_pin.get("path"), "v1 build result releaseDefinition.path")
    definition_path = output.joinpath(*PurePosixPath(definition_relative).parts)
    definition = read_vocabulary_atlas_v1_release_definition(
        definition_path,
        expected_file_digest=_require_digest(
            definition_pin.get("fileDigest"),
            "v1 build result releaseDefinition.fileDigest",
        ),
    )
    if (
        definition.identifier != definition_pin.get("id")
        or definition.record_digest != definition_pin.get("recordDigest")
        or definition.record.get("releaseMode") != result.get("releaseMode")
        or definition.record.get("releaseName") != result.get("releaseName")
    ):
        raise VocabularyAtlasV1ReleaseError("v1 copied definition differs from the build result")

    root = _artifact_root(artifact_root)
    reviewed_corpus, reviewed_corpus_descriptor = _open_reviewed_search_corpus(
        definition,
        root,
    )
    source_reconciliations = [_federal_register_related_reconciliation(definition, root)]
    index = _open_planning_index(definition, root)
    scope_releases, release_sources, _release_labels = _open_releases(
        definition,
        root,
        output / "control" / "ring-assignments",
        materialize_assignments=False,
    )
    (
        qualification_runs,
        authorized_run_receipts,
        admitted_candidates,
    ) = _verify_qualification_runs(
        definition,
        root=root,
        releases=release_sources,
    )
    if _plain(result.get("qualificationRuns")) != qualification_runs:
        raise VocabularyAtlasV1ReleaseError("v1 build-result qualification runs differ from their exact receipts")
    if _plain(result.get("sourceReconciliations")) != source_reconciliations:
        raise VocabularyAtlasV1ReleaseError("v1 build-result source reconciliation differs from the exact source")
    relation_bundles = _open_relation_bundles(
        definition,
        root,
        release_sources,
        authorized_run_receipts,
        admitted_candidates,
    )
    scope_pin = _require_mapping(result.get("scope"), "v1 build result scope")
    pinned_scope = PinnedVocabularyAtlasScope.open(
        output / "control" / "atlas-scope.json",
        expected_file_digest=_require_digest(scope_pin.get("fileDigest"), "v1 build result scope.fileDigest"),
        atlas_index=index,
        releases=scope_releases,
        relation_bundles=relation_bundles,
    )
    if pinned_scope.pin() != _plain(scope_pin):
        raise VocabularyAtlasV1ReleaseError("v1 scope differs from its build-result pin")

    atlas_pin = _require_mapping(result.get("atlas"), "v1 build result atlas")
    atlas = VocabularyAtlasAsset.open(
        output / "canonical",
        expected_manifest_digest=_require_digest(
            atlas_pin.get("manifestDigest"),
            "v1 build result atlas.manifestDigest",
        ),
    )
    if {
        "role": "VocabularyAtlas",
        "id": atlas.manifest["id"],
        "manifestDigest": atlas.manifest_digest,
        "distributionDigest": atlas.output_digest,
    } != _plain(atlas_pin):
        raise VocabularyAtlasV1ReleaseError("v1 Atlas differs from its build-result pin")

    decision_pin = _require_mapping(
        result.get("publicationDecision"),
        "v1 build result publicationDecision",
    )
    decision = read_vocabulary_atlas_publication_decision(
        output / "control" / "publication-decision.json",
        expected_file_digest=_require_digest(
            decision_pin.get("fileDigest"),
            "v1 build result publicationDecision.fileDigest",
        ),
    )
    if decision.identifier != decision_pin.get("id") or decision.record_digest != decision_pin.get("recordDigest"):
        raise VocabularyAtlasV1ReleaseError("v1 publication decision differs from its build-result pin")
    decision.validate_for_scope(pinned_scope)
    decision.validate_distribution(atlas)

    publication_pin = _require_mapping(result.get("publication"), "v1 build result publication")
    publication_relative = _require_relative_path(publication_pin.get("path"), "v1 build result publication.path")
    expected_publication = (
        ("publicVocabularyAtlas", "public")
        if result["releaseMode"] == "publicV1"
        else ("baselineEvidencePreview", "baseline-preview")
    )
    if (
        publication_pin.get("role"),
        publication_relative,
    ) != expected_publication:
        raise VocabularyAtlasV1ReleaseError("v1 publication role or path differs from its release mode")
    publication = AtlasPublication.open(
        output.joinpath(*PurePosixPath(publication_relative).parts),
        expected_manifest_digest=_require_digest(
            publication_pin.get("manifestDigest"),
            "v1 build result publication.manifestDigest",
        ),
    )
    if publication.manifest.get("id") != publication_pin.get("id"):
        raise VocabularyAtlasV1ReleaseError("v1 publication differs from its build-result pin")
    explorer_payload = _read_regular_file(
        publication.directory / EXPLORER_DATA,
        label="v1 publication explorer",
    )
    explorer = _decode_json(explorer_payload, "v1 publication explorer")
    if not isinstance(explorer, Mapping) or _canonical_bytes(explorer) != explorer_payload:
        raise VocabularyAtlasV1ReleaseError("v1 publication explorer bytes are not canonical")
    explorer_html = _read_regular_file(
        publication.directory / EXPLORER_HTML,
        label="v1 publication explorer HTML",
    )

    acceptance_pin = _require_mapping(result.get("acceptance"), "v1 build result acceptance")
    acceptance = read_vocabulary_atlas_release_acceptance(
        output / "control" / "release-acceptance.json",
        expected_file_digest=_require_digest(
            acceptance_pin.get("fileDigest"),
            "v1 build result acceptance.fileDigest",
        ),
    )
    if acceptance.identifier != acceptance_pin.get("id") or acceptance.record_digest != acceptance_pin.get(
        "recordDigest"
    ):
        raise VocabularyAtlasV1ReleaseError("v1 acceptance differs from its build-result pin")
    acceptance.validate_inputs(
        atlas,
        scope=pinned_scope,
        planning_index=index,
        publication_decision=decision,
        explorer=explorer,
    )
    explorer_acceptance: VocabularyAtlasExplorerAcceptance | None = None
    if result["schemaVersion"] == "2.0":
        explorer_acceptance_pin = _require_mapping(
            result.get("explorerAcceptance"),
            "v1 build result explorerAcceptance",
        )
        explorer_acceptance = read_vocabulary_atlas_explorer_acceptance(
            output / "control" / "explorer-acceptance.json",
            expected_file_digest=_require_digest(
                explorer_acceptance_pin.get("fileDigest"),
                "v1 build result explorerAcceptance.fileDigest",
            ),
        )
        if (
            explorer_acceptance.identifier != explorer_acceptance_pin.get("id")
            or explorer_acceptance.record_digest
            != explorer_acceptance_pin.get("recordDigest")
        ):
            raise VocabularyAtlasV1ReleaseError(
                "v1 explorer acceptance differs from its build-result pin"
            )
        search_record = _require_mapping(
            explorer_acceptance.record.get("search"),
            "v1 explorer acceptance search",
        )
        expected_explorer_status = (
            "passed"
            if result["releaseMode"] == "publicV1"
            else "measuredBaselineOnly"
        )
        expected_corpus_source = (
            {
                "path": reviewed_corpus_descriptor["path"],
                "fileDigest": reviewed_corpus_descriptor["fileDigest"],
            }
            if result["releaseMode"] == "publicV1"
            else None
        )
        if (
            explorer_acceptance.record.get("status") != expected_explorer_status
            or _plain(explorer_acceptance_pin.get("reviewedCorpus"))
            != _plain(reviewed_corpus_descriptor)
            or _plain(search_record.get("source")) != expected_corpus_source
        ):
            raise VocabularyAtlasV1ReleaseError(
                "v1 explorer acceptance status or reviewed-corpus pin differs from its release mode"
            )
        expected_explorer_acceptance = build_vocabulary_atlas_explorer_acceptance(
            atlas,
            explorer,
            explorer_html=explorer_html,
            release_mode=cast(ReleaseMode, result["releaseMode"]),
            reviewed_corpus=reviewed_corpus,
            reviewed_corpus_path=(
                cast(str, reviewed_corpus_descriptor["path"])
                if result["releaseMode"] == "publicV1"
                else None
            ),
            reviewed_corpus_file_digest=(
                cast(str, reviewed_corpus_descriptor["fileDigest"])
                if result["releaseMode"] == "publicV1"
                else None
            ),
        )
        if (
            explorer_acceptance.as_record()
            != expected_explorer_acceptance.as_record()
        ):
            raise VocabularyAtlasV1ReleaseError(
                "v1 explorer acceptance differs from the externally reopened reviewed corpus"
            )
    expected_checks = _builder_acceptance_checks(
        definition,
        index=index,
        scope=pinned_scope,
        atlas=atlas,
        decision=decision,
        publication=publication,
        explorer_acceptance=explorer_acceptance,
        qualification_runs=qualification_runs,
        federal_register_reconciliation=source_reconciliations[0],
    )
    if _plain(acceptance.record.get("checks")) != expected_checks:
        raise VocabularyAtlasV1ReleaseError("v1 acceptance checks were not derived by the release builder")
    validate_vocabulary_atlas_v1_acceptance(definition, acceptance)
    if _plain(acceptance.record.get("counts")) != _plain(result.get("counts")) or _plain(
        acceptance.record.get("reproducibility")
    ) != _plain(result.get("reproducibility")):
        raise VocabularyAtlasV1ReleaseError("v1 acceptance measurements differ from the build result")
    return VocabularyAtlasV1Build(
        output_directory=output,
        result=cast(Mapping[str, Any], deep_freeze_json(result)),
        result_file_digest=expected_digest,
    )


def _builder_acceptance_checks(
    definition: VocabularyAtlasV1ReleaseDefinition,
    *,
    index: PinnedAtlasIndex,
    scope: PinnedVocabularyAtlasScope,
    atlas: VocabularyAtlasAsset,
    decision: VocabularyAtlasPublicationDecision,
    publication: AtlasPublication,
    explorer_acceptance: VocabularyAtlasExplorerAcceptance | None,
    qualification_runs: Sequence[Mapping[str, Any]],
    federal_register_reconciliation: Mapping[str, Any],
) -> list[dict[str, Any]]:
    mode = cast(str, definition.record["releaseMode"])
    qualification_evidence = sorted(cast(str, run["id"]) for run in qualification_runs)
    publication_statement = (
        "The exact public v1 package reopened from its external manifest digest."
        if mode == "publicV1"
        else "The baseline evidence RC preview reopened from its external manifest digest and remains a bench artifact."
    )
    federal_register_counts = _require_mapping(
        federal_register_reconciliation.get("counts"),
        "v1 Federal Register Related-reference reconciliation counts",
    )
    explorer_check: dict[str, Any] | None = None
    if explorer_acceptance is not None:
        expected_explorer_status = (
            "passed" if mode == "publicV1" else "measuredBaselineOnly"
        )
        if explorer_acceptance.record.get("status") != expected_explorer_status:
            raise VocabularyAtlasV1ReleaseError(
                "v1 explorer acceptance status differs from its release mode"
            )
        explorer_search = _require_mapping(
            explorer_acceptance.record.get("search"),
            "v1 explorer acceptance search",
        )
        expected_search_source = None
        if mode == "publicV1":
            reviewed_corpus = _require_mapping(
                definition.record.get("reviewedSearchCorpus"),
                "v1 release definition reviewedSearchCorpus",
            )
            expected_search_source = {
                "path": reviewed_corpus["path"],
                "fileDigest": reviewed_corpus["fileDigest"],
            }
        expected_search_status = (
            "passed" if mode == "publicV1" else "skippedPublicOnly"
        )
        if (
            explorer_search.get("status") != expected_search_status
            or _plain(explorer_search.get("source")) != expected_search_source
        ):
            raise VocabularyAtlasV1ReleaseError(
                "v1 explorer acceptance does not use the definition-pinned reviewed corpus state"
            )
        explorer_check = {
            "id": "urn:ref:check:vocabulary-atlas-v1:explorer-acceptance",
            "statement": (
                "Every explorer facet and assertion reconciles, and every reviewed ring-specific public search case meets its required rank."
                if mode == "publicV1"
                else "Every explorer facet and assertion reconciles; the public-only reviewed search corpus remains explicitly skipped for this bench preview."
            ),
            "status": "passed",
            "evidence": [explorer_acceptance.identifier],
        }
    checks = [
        {
            "id": "urn:ref:check:vocabulary-atlas-v1:canonical-reproduction",
            "statement": "The canonical Atlas reproduced from its exact six-release scope.",
            "status": "passed",
            "evidence": sorted([scope.scope_id, cast(str, atlas.manifest["id"])]),
        },
        {
            "id": "urn:ref:check:vocabulary-atlas-v1:definition-and-controls",
            "statement": "The independently pinned definition, planning index, source approvals, and every planning-row disposition agree.",
            "status": "passed",
            "evidence": sorted([definition.identifier, index.index_id, decision.identifier]),
        },
        {
            "id": "urn:ref:check:vocabulary-atlas-v1:federal-register-related-reconciliation",
            "statement": (
                "The exact Federal Register source reconciles "
                f"{federal_register_counts['resolvedConceptLinks']:,} resolved concept links, "
                f"{federal_register_counts['suggestedOpenTermPatterns']} suggested open-term patterns, "
                f"and {federal_register_counts['unresolvedTargets']} unresolved target across "
                f"all {federal_register_counts['sourceReferenceTotal']:,} Related references."
            ),
            "status": "passed",
            "evidence": sorted(
                [
                    cast(str, federal_register_reconciliation["id"]),
                    cast(str, federal_register_reconciliation["releaseId"]),
                ]
            ),
        },
        {
            "id": "urn:ref:check:vocabulary-atlas-v1:publication-reopen",
            "statement": publication_statement,
            "status": "passed",
            "evidence": sorted([cast(str, publication.manifest["id"]), decision.identifier]),
        },
        {
            "id": "urn:ref:check:vocabulary-atlas-v1:qualification-accounting",
            "statement": (
                "All six required production jobs and the preserved baseline jobs carry exact candidate accounting."
                if mode == "publicV1"
                else "The three preserved baseline jobs carry exact pilot accounting and do not claim production readiness."
            ),
            "status": "passed",
            "evidence": qualification_evidence,
        },
    ]
    if explorer_check is not None:
        checks.insert(2, explorer_check)
    return checks


def _build_in_staging(
    definition: VocabularyAtlasV1ReleaseDefinition,
    definition_payload: bytes,
    root: Path,
    staging: Path,
) -> dict[str, Any]:
    _write_new_file(
        staging / "control" / "release-definition.json",
        definition_payload,
        label="copied v1 release definition",
    )
    index = _open_planning_index(definition, root)
    source_reconciliations = [_federal_register_related_reconciliation(definition, root)]
    assignment_directory = staging / "control" / "ring-assignments"
    assignment_directory.mkdir(parents=True)
    scope_releases, release_sources, release_labels = _open_releases(
        definition,
        root,
        assignment_directory,
    )
    (
        qualification_runs,
        authorized_run_receipts,
        admitted_candidates,
    ) = _verify_qualification_runs(
        definition,
        root=root,
        releases=release_sources,
    )
    relation_bundles = _open_relation_bundles(
        definition,
        root,
        release_sources,
        authorized_run_receipts,
        admitted_candidates,
    )
    scope = VocabularyAtlasScope.create(
        scope_name=cast(str, definition.record["scopeName"]),
        scope_kind=cast(Any, definition.record["scopeKind"]),
        atlas_index=index,
        releases=scope_releases,
        relation_bundles=relation_bundles,
    )
    scope_path = scope.write_to(staging / "control" / "atlas-scope.json")
    pinned_scope = PinnedVocabularyAtlasScope.open(
        scope_path,
        expected_file_digest=sha256_digest(scope.artifact_bytes()),
        atlas_index=index,
        releases=scope_releases,
        relation_bundles=relation_bundles,
    )

    built_atlas = build_vocabulary_atlas(pinned_scope)
    canonical_directory = built_atlas.write(staging / "canonical")
    atlas = VocabularyAtlasAsset.open(
        canonical_directory,
        expected_manifest_digest=built_atlas.manifest_digest,
    )
    if (
        atlas.payload != built_atlas.payload
        or atlas.scope_payload != built_atlas.scope_payload
        or atlas.manifest_bytes() != built_atlas.manifest_bytes()
    ):
        raise VocabularyAtlasV1ReleaseError("reopened v1 Atlas differs from its deterministic build")

    publication_values = cast(Mapping[str, Any], definition.record["publication"])
    try:
        decision = build_vocabulary_atlas_publication_decision(
            pinned_scope,
            artifact_kind="atlas",
            policies=cast(Sequence[Mapping[str, Any]], publication_values["policies"]),
            decision_actor=cast(str, publication_values["decisionActor"]),
            decided_at=cast(str, publication_values["decidedAt"]),
            result={
                "role": "VocabularyAtlas",
                "id": cast(str, atlas.manifest["id"]),
                "manifestDigest": atlas.manifest_digest,
                "distributionDigest": atlas.output_digest,
            },
            exceptions=cast(Sequence[Mapping[str, Any]], publication_values["exceptions"]),
            supersedes=cast(Sequence[Mapping[str, Any]], publication_values["supersedes"]),
            source_approvals=cast(Sequence[Mapping[str, Any]], publication_values["sourceApprovals"]),
            row_dispositions=cast(Sequence[Mapping[str, Any]], publication_values["rowDispositions"]),
        )
    except PublicationDecisionError as error:
        raise VocabularyAtlasV1ReleaseError(str(error)) from error
    decision_path = decision.write_to(staging / "control" / "publication-decision.json")
    decision_file_digest = sha256_digest(decision.artifact_bytes())
    decision = read_vocabulary_atlas_publication_decision(
        decision_path,
        expected_file_digest=decision_file_digest,
    )

    release_mode = cast(str, definition.record["releaseMode"])
    publication_path = "public" if release_mode == "publicV1" else "baseline-preview"
    publication = publish_vocabulary_atlas(
        atlas,
        staging / publication_path,
        decision=decision,
        planning_index=index,
        title=cast(str, definition.record["title"]),
        release_labels=release_labels,
    )
    publication = AtlasPublication.open(
        publication.directory,
        expected_manifest_digest=publication.manifest_digest,
    )
    if (
        publication.distribution.manifest_digest != atlas.manifest_digest
        or publication.distribution.output_digest != atlas.output_digest
    ):
        raise VocabularyAtlasV1ReleaseError("reopened v1 publication names another canonical Atlas")
    explorer_payload = _read_regular_file(
        publication.directory / EXPLORER_DATA,
        label="v1 publication explorer",
    )
    explorer = _decode_json(explorer_payload, "v1 publication explorer")
    if not isinstance(explorer, Mapping) or _canonical_bytes(explorer) != explorer_payload:
        raise VocabularyAtlasV1ReleaseError("v1 publication explorer bytes are not canonical")
    explorer_html = _read_regular_file(
        publication.directory / EXPLORER_HTML,
        label="v1 publication explorer HTML",
    )

    reviewed_corpus, reviewed_corpus_descriptor = _open_reviewed_search_corpus(
        definition,
        root,
    )
    explorer_acceptance = build_vocabulary_atlas_explorer_acceptance(
        atlas,
        explorer,
        explorer_html=explorer_html,
        release_mode=cast(ReleaseMode, release_mode),
        reviewed_corpus=reviewed_corpus,
        reviewed_corpus_path=(
            cast(str, reviewed_corpus_descriptor["path"])
            if release_mode == "publicV1"
            else None
        ),
        reviewed_corpus_file_digest=(
            cast(str, reviewed_corpus_descriptor["fileDigest"])
            if release_mode == "publicV1"
            else None
        ),
    )
    explorer_acceptance_path = explorer_acceptance.write_to(
        staging / "control" / "explorer-acceptance.json"
    )
    explorer_acceptance_file_digest = sha256_digest(
        explorer_acceptance.artifact_bytes()
    )
    reopened_explorer_acceptance = read_vocabulary_atlas_explorer_acceptance(
        explorer_acceptance_path,
        expected_file_digest=explorer_acceptance_file_digest,
    )
    expected_explorer_acceptance = build_vocabulary_atlas_explorer_acceptance(
        atlas,
        explorer,
        explorer_html=explorer_html,
        release_mode=cast(ReleaseMode, release_mode),
        reviewed_corpus=reviewed_corpus,
        reviewed_corpus_path=(
            cast(str, reviewed_corpus_descriptor["path"])
            if release_mode == "publicV1"
            else None
        ),
        reviewed_corpus_file_digest=(
            cast(str, reviewed_corpus_descriptor["fileDigest"])
            if release_mode == "publicV1"
            else None
        ),
    )
    if (
        reopened_explorer_acceptance.as_record()
        != expected_explorer_acceptance.as_record()
    ):
        raise VocabularyAtlasV1ReleaseError(
            "reopened v1 explorer acceptance differs from the definition-pinned reviewed corpus"
        )

    acceptance = build_vocabulary_atlas_release_acceptance(
        atlas,
        scope=pinned_scope,
        planning_index=index,
        publication_decision=decision,
        explorer=explorer,
        checks=_builder_acceptance_checks(
            definition,
            index=index,
            scope=pinned_scope,
            atlas=atlas,
            decision=decision,
            publication=publication,
            explorer_acceptance=reopened_explorer_acceptance,
            qualification_runs=qualification_runs,
            federal_register_reconciliation=source_reconciliations[0],
        ),
    )
    validate_vocabulary_atlas_v1_acceptance(definition, acceptance)
    acceptance_path = acceptance.write_to(staging / "control" / "release-acceptance.json")
    acceptance_file_digest = sha256_digest(acceptance.artifact_bytes())
    reopened_acceptance = read_vocabulary_atlas_release_acceptance(
        acceptance_path,
        expected_file_digest=acceptance_file_digest,
    )
    if reopened_acceptance.as_record() != acceptance.as_record():
        raise VocabularyAtlasV1ReleaseError(
            "reopened v1 acceptance differs from its deterministic build"
        )

    if definition.file_digest is None:
        raise VocabularyAtlasV1ReleaseError("v1 build lost its independently reopened definition digest")
    basis = {
        "type": VOCABULARY_ATLAS_V1_BUILD_RESULT_TYPE,
        "schemaVersion": VOCABULARY_ATLAS_V1_BUILD_RESULT_VERSION,
        "releaseMode": release_mode,
        "releaseName": definition.record["releaseName"],
        "status": "passed" if release_mode == "publicV1" else "baselineEvidenceOnly",
        "releaseDefinition": {
            "id": definition.identifier,
            "recordDigest": definition.record_digest,
            "fileDigest": definition.file_digest,
            "path": "control/release-definition.json",
        },
        "scope": pinned_scope.pin(),
        "atlas": {
            "role": "VocabularyAtlas",
            "id": atlas.manifest["id"],
            "manifestDigest": atlas.manifest_digest,
            "distributionDigest": atlas.output_digest,
        },
        "publicationDecision": {
            "id": decision.identifier,
            "recordDigest": decision.record_digest,
            "fileDigest": decision_file_digest,
        },
        "publication": {
            "role": ("publicVocabularyAtlas" if release_mode == "publicV1" else "baselineEvidencePreview"),
            "path": publication_path,
            "id": publication.manifest["id"],
            "manifestDigest": publication.manifest_digest,
        },
        "explorerAcceptance": {
            "id": reopened_explorer_acceptance.identifier,
            "recordDigest": reopened_explorer_acceptance.record_digest,
            "fileDigest": explorer_acceptance_file_digest,
            "reviewedCorpus": _plain(reviewed_corpus_descriptor),
        },
        "acceptance": {
            "id": reopened_acceptance.identifier,
            "recordDigest": reopened_acceptance.record_digest,
            "fileDigest": acceptance_file_digest,
        },
        "counts": _plain(reopened_acceptance.record["counts"]),
        "reproducibility": _plain(reopened_acceptance.record["reproducibility"]),
        "qualificationRuns": qualification_runs,
        "sourceReconciliations": source_reconciliations,
        "artifacts": _generated_artifacts(staging),
    }
    result = _seal_build_result(basis)
    _write_new_file(
        staging / "build-result.json",
        _canonical_bytes(result),
        label="v1 build result",
    )
    return result


def build_vocabulary_atlas_v1_release(
    definition: VocabularyAtlasV1ReleaseDefinition,
    *,
    artifact_root: Path | str,
    output_directory: Path | str,
) -> VocabularyAtlasV1Build:
    """Build, verify, and atomically place one six-release Atlas v1."""

    if not isinstance(definition, VocabularyAtlasV1ReleaseDefinition):
        raise VocabularyAtlasV1ReleaseError("v1 build requires an exact VocabularyAtlasV1ReleaseDefinition")
    definition, definition_payload = _verified_definition_bytes(definition)
    root = _artifact_root(artifact_root)
    requested_destination = Path(output_directory)
    if requested_destination.exists() or requested_destination.is_symlink():
        raise VocabularyAtlasV1ReleaseError(f"v1 output destination already exists: {requested_destination}")
    requested_destination.parent.mkdir(parents=True, exist_ok=True)
    if requested_destination.parent.is_symlink():
        raise VocabularyAtlasV1ReleaseError("v1 output parent must not be a symlink")
    parent = requested_destination.parent.resolve(strict=True)
    destination = parent / requested_destination.name
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=parent))
    placed = False
    try:
        result = _build_in_staging(
            definition,
            definition_payload,
            root,
            staging,
        )
        if destination.exists() or destination.is_symlink():
            raise VocabularyAtlasV1ReleaseError(f"v1 output destination appeared during the build: {destination}")
        os.rename(staging, destination)
        placed = True
        result_payload = _canonical_bytes(result)
        reopened = open_vocabulary_atlas_v1_build(
            destination,
            artifact_root=root,
            expected_result_file_digest=sha256_digest(result_payload),
        )
        if _plain(reopened.result) != result:
            raise VocabularyAtlasV1ReleaseError("placed v1 build differs from the verified staging result")
        return reopened
    except BaseException:
        cleanup = destination if placed else staging
        shutil.rmtree(cleanup, ignore_errors=True)
        raise


__all__ = [
    "VOCABULARY_ATLAS_V1_BUILD_RESULT_TYPE",
    "VOCABULARY_ATLAS_V1_BUILD_RESULT_VERSION",
    "VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_TYPE",
    "VOCABULARY_ATLAS_V1_RELEASE_DEFINITION_VERSION",
    "ReleaseKind",
    "ReleaseMode",
    "V1ReleaseRole",
    "VocabularyAtlasV1Build",
    "VocabularyAtlasV1ReleaseDefinition",
    "VocabularyAtlasV1ReleaseError",
    "build_vocabulary_atlas_v1_release",
    "open_vocabulary_atlas_v1_build",
    "read_vocabulary_atlas_v1_release_definition",
    "validate_vocabulary_atlas_v1_acceptance",
]
