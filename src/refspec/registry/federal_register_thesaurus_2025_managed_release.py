"""Closed managed release for the April 1, 2025 Federal Register thesaurus."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from refspec import binding
from refspec.registry.federal_register_thesaurus_2025 import (
    ALTERNATE_LABEL_PROPERTY_IRI,
    FEDERAL_REGISTER_THESAURUS_2025_ISSUED,
    FEDERAL_REGISTER_THESAURUS_2025_PARSER_VERSION,
    FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI,
    FEDERAL_REGISTER_THESAURUS_2025_SHA256,
    FEDERAL_REGISTER_THESAURUS_2025_URL,
    RELATED_PROPERTY_IRI,
    FederalRegisterThesaurus2025,
    federal_register_thesaurus_2025_concept_iri,
    federal_register_thesaurus_2025_extract_bytes,
)
from refspec.registry.federal_register_vocabulary_policy import (
    FEDERAL_REGISTER_CROSSWALK_VERSION,
    LISTS_OF_SUBJECTS_RESOLUTION_POLICY_VERSION,
    validate_federal_register_thesaurus_crosswalk,
)
from refspec.storage import canonical_json

FEDERAL_REGISTER_THESAURUS_2025_RESOURCE_ID = (
    "federal-register-thesaurus-2025"
)
FEDERAL_REGISTER_THESAURUS_2025_MANAGED_RELEASE_VERSION = (
    "federal-register-thesaurus-2025-managed-release-v1"
)

_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
_SOURCE_PDF_PATH = "sources/thesaurus-4-1-2025.pdf"
_SOURCE_EXTRACT_PATH = "sources/source-extract.json"
_CONCEPTS_PATH = "records/concepts.jsonl"
_VARIANTS_PATH = "records/variants.jsonl"
_RELATIONS_PATH = "records/relations.jsonl"
_OPEN_PATTERNS_PATH = "records/suggested-open-term-patterns.jsonl"
_CROSSWALK_PATH = "records/crosswalk-1995-to-2025.json"
_LISTS_POLICY_PATH = "records/lists-of-subjects-policy.json"
_COVERAGE_PATH = "records/coverage.json"
_MANIFEST_PATH = "managed-release.json"


class FederalRegisterThesaurus2025ManagedReleaseError(ValueError):
    """The current Federal Register vocabulary package is incomplete."""


def _json_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8") + b"\n"


def _jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(_json_bytes(row) for row in rows)


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _seal(record: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(record)
    result["canonicalPayloadDigest"] = binding.canonical_payload_digest(result)
    return result


def _verify_seal(record: Mapping[str, Any], *, label: str) -> None:
    expected = binding.canonical_payload_digest(dict(record))
    if record.get("canonicalPayloadDigest") != expected:
        raise FederalRegisterThesaurus2025ManagedReleaseError(
            f"{label} digest drifted"
        )


def _descriptor(path: str, payload: bytes) -> dict[str, Any]:
    return {
        "path": path,
        "sha256": _sha256_bytes(payload),
        "byteLength": len(payload),
    }


def _read_regular(root: Path, relative: str) -> bytes:
    if relative.startswith("/") or ".." in Path(relative).parts:
        raise FederalRegisterThesaurus2025ManagedReleaseError(
            f"unsafe package path {relative!r}"
        )
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise FederalRegisterThesaurus2025ManagedReleaseError(
            f"package artifact is not a regular file: {relative}"
        )
    return path.read_bytes()


def _recognized_variants_by_target(
    thesaurus: FederalRegisterThesaurus2025,
) -> dict[str, tuple[str, ...]]:
    values: dict[str, set[str]] = defaultdict(set)
    for variant in thesaurus.variants:
        if (
            variant.resolution_status == "recognizedVariant"
            and len(variant.target_concept_ids) == 1
        ):
            values[variant.target_concept_ids[0]].add(variant.label)
    return {
        key: tuple(sorted(labels, key=lambda value: (value.casefold(), value)))
        for key, labels in values.items()
    }


def _concept_rows(
    thesaurus: FederalRegisterThesaurus2025,
) -> tuple[dict[str, Any], ...]:
    variants = _recognized_variants_by_target(thesaurus)
    return tuple(
        {
            "conceptId": term.concept_id,
            "conceptIri": federal_register_thesaurus_2025_concept_iri(
                term.concept_id
            ),
            "schemeIri": FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI,
            "preferredLabel": term.label,
            "alternateLabels": list(variants.get(term.concept_id, ())),
            "status": "active",
            "sourceLocator": asdict(term.locator),
            "hierarchyRelations": [],
        }
        for term in thesaurus.official_terms
    )


def _variant_rows(
    thesaurus: FederalRegisterThesaurus2025,
) -> tuple[dict[str, Any], ...]:
    redirects = {
        item.redirect_id: item for item in thesaurus.variant_redirects
    }
    return tuple(
        {
            "variantId": item.variant_id,
            "label": item.label,
            "propertyIri": ALTERNATE_LABEL_PROPERTY_IRI,
            "resolutionStatus": item.resolution_status,
            "targetConceptIds": list(item.target_concept_ids),
            "targetConceptIris": [
                federal_register_thesaurus_2025_concept_iri(target)
                for target in item.target_concept_ids
            ],
            "redirects": [
                {
                    "redirectId": redirect.redirect_id,
                    "rawTargetLabel": redirect.raw_target_label,
                    "targetConceptId": redirect.target_concept_id,
                    "resolutionStatus": redirect.resolution_status,
                    "sourceLocator": asdict(redirect.locator),
                }
                for redirect_id in item.redirect_ids
                for redirect in (redirects[redirect_id],)
            ],
            "sourceLocator": asdict(item.locator),
        }
        for item in thesaurus.variants
    )


def _relation_rows(
    thesaurus: FederalRegisterThesaurus2025,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "relationId": item.relation_id,
            "sourceConceptId": item.source_concept_id,
            "sourceConceptIri": federal_register_thesaurus_2025_concept_iri(
                item.source_concept_id
            ),
            "predicateIri": (
                RELATED_PROPERTY_IRI
                if item.resolution_status == "resolved"
                else None
            ),
            "rawTargetLabel": item.raw_target_label,
            "targetConceptId": item.target_concept_id,
            "targetConceptIri": (
                federal_register_thesaurus_2025_concept_iri(
                    item.target_concept_id
                )
                if item.target_concept_id is not None
                else None
            ),
            "resolutionStatus": item.resolution_status,
            "sourceLocator": asdict(item.locator),
        }
        for item in thesaurus.related_references
    )


def _lists_policy() -> dict[str, Any]:
    return {
        "policyVersion": LISTS_OF_SUBJECTS_RESOLUTION_POLICY_VERSION,
        "input": (
            "a List of Subjects literal plus its Federal Register source "
            "record and field location"
        ),
        "classifications": {
            "officialTerm": (
                "exact April 1, 2025 official-term match"
            ),
            "recognizedVariant": (
                "exact variant match with one resolved official See target"
            ),
            "sourceLocalOpenTerm": (
                "source-assigned non-thesaurus text retained with its source "
                "record and path; no concept identity"
            ),
            "unresolved": (
                "unknown, ambiguous, or defective text that requires review"
            ),
        },
        "conceptMintingAllowed": False,
        "silentFallbackAllowed": False,
        "sourceLocalOpenTermRequires": [
            "explicit caller authorization",
            "sourceRecordId",
            "sourcePath",
        ],
    }


@dataclass(frozen=True, slots=True)
class FederalRegisterThesaurus2025ManagedRelease:
    """One deterministic, source-complete managed concept release."""

    manifest: Mapping[str, Any]
    coverage: Mapping[str, Any]
    concepts: tuple[Mapping[str, Any], ...]
    variants: tuple[Mapping[str, Any], ...]
    relations: tuple[Mapping[str, Any], ...]
    suggested_open_term_patterns: tuple[Mapping[str, Any], ...]
    lists_of_subjects_policy: Mapping[str, Any]
    crosswalk: Mapping[str, Any]
    source_pdf: bytes
    source_extract: bytes

    def content_artifacts(self) -> dict[str, bytes]:
        return {
            _CONCEPTS_PATH: _jsonl_bytes(self.concepts),
            _VARIANTS_PATH: _jsonl_bytes(self.variants),
            _RELATIONS_PATH: _jsonl_bytes(self.relations),
            _OPEN_PATTERNS_PATH: _jsonl_bytes(
                self.suggested_open_term_patterns
            ),
            _CROSSWALK_PATH: _json_bytes(self.crosswalk),
            _LISTS_POLICY_PATH: _json_bytes(self.lists_of_subjects_policy),
            _COVERAGE_PATH: _json_bytes(self.coverage),
            _SOURCE_PDF_PATH: self.source_pdf,
            _SOURCE_EXTRACT_PATH: self.source_extract,
        }

    def artifact_bytes(self) -> dict[str, bytes]:
        artifacts = self.content_artifacts()
        artifacts[_MANIFEST_PATH] = _json_bytes(self.manifest)
        return dict(sorted(artifacts.items()))

    def write_to(self, output_dir: Path | str) -> Mapping[str, Path]:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}
        for relative, payload in self.artifact_bytes().items():
            path = root / relative
            if path.exists() and path.read_bytes() != payload:
                raise FileExistsError(
                    f"refusing to overwrite different artifact {path}"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            written[relative] = path
        return written


def build_federal_register_thesaurus_2025_managed_release(
    thesaurus: FederalRegisterThesaurus2025,
    crosswalk: Mapping[str, Any],
    *,
    recorded_at: str,
    recorded_by: str,
) -> FederalRegisterThesaurus2025ManagedRelease:
    """Package the exact current publication and its analysis-only crosswalk."""

    if (
        thesaurus.source_sha256 != FEDERAL_REGISTER_THESAURUS_2025_SHA256
        or thesaurus.source_artifact_bytes is None
    ):
        raise FederalRegisterThesaurus2025ManagedReleaseError(
            "managed release requires the exact pinned PDF bytes"
        )
    if _ABSOLUTE_IRI.fullmatch(recorded_by) is None:
        raise FederalRegisterThesaurus2025ManagedReleaseError(
            "recorded_by must be an absolute IRI"
        )
    validate_federal_register_thesaurus_crosswalk(
        crosswalk,
        current=thesaurus,
    )
    concepts = _concept_rows(thesaurus)
    variants = _variant_rows(thesaurus)
    relations = _relation_rows(thesaurus)
    open_patterns = tuple(
        {
            "patternId": item.pattern_id,
            "sourceEntryId": item.source_entry_id,
            "referenceKind": item.reference_kind,
            "rawLiteral": item.raw_literal,
            "sourceLocator": asdict(item.locator),
            "conceptMinted": False,
        }
        for item in thesaurus.suggested_open_term_patterns
    )
    lists_policy = _lists_policy()
    coverage = _seal(
        {
            "type": (
                "urn:ref:type:"
                "FederalRegisterThesaurus2025ImportCoverageReport"
            ),
            "id": (
                "urn:ref:federal-register-thesaurus:2025-04-01:"
                "coverage:v1"
            ),
            "version": (
                FEDERAL_REGISTER_THESAURUS_2025_MANAGED_RELEASE_VERSION
            ),
            "recordedAt": recorded_at,
            "recordedBy": recorded_by,
            "sourceCounts": asdict(thesaurus.counts),
            "managedConceptCount": len(concepts),
            "recognizedVariantOccurrenceCount": sum(
                row["resolutionStatus"] == "recognizedVariant"
                for row in variants
            ),
            "ambiguousVariantOccurrenceCount": sum(
                row["resolutionStatus"] == "ambiguous" for row in variants
            ),
            "unresolvedVariantOccurrenceCount": sum(
                row["resolutionStatus"] == "unresolved" for row in variants
            ),
            "resolvedAssociativeRelationCount": sum(
                row["resolutionStatus"] == "resolved" for row in relations
            ),
            "openTermPatternCount": len(open_patterns),
            "unresolvedReferences": [
                asdict(item) for item in thesaurus.unresolved_references
            ],
            "indexAnomalies": [
                asdict(item) for item in thesaurus.index_anomalies
            ],
            "hierarchyRelationCount": 0,
            "candidateLookupAllowed": True,
            "acceptedOutputAllowed": False,
        }
    )
    source_extract = federal_register_thesaurus_2025_extract_bytes(thesaurus)
    partial = FederalRegisterThesaurus2025ManagedRelease(
        manifest={},
        coverage=coverage,
        concepts=concepts,
        variants=variants,
        relations=relations,
        suggested_open_term_patterns=open_patterns,
        lists_of_subjects_policy=lists_policy,
        crosswalk=dict(crosswalk),
        source_pdf=thesaurus.source_artifact_bytes,
        source_extract=source_extract,
    )
    artifacts = partial.content_artifacts()
    manifest = _seal(
        {
            "type": (
                "urn:ref:type:"
                "FederalRegisterThesaurus2025ManagedReleaseManifest"
            ),
            "id": (
                "urn:ref:federal-register-thesaurus:2025-04-01:"
                "managed-release:v1"
            ),
            "resourceId": FEDERAL_REGISTER_THESAURUS_2025_RESOURCE_ID,
            "version": (
                FEDERAL_REGISTER_THESAURUS_2025_MANAGED_RELEASE_VERSION
            ),
            "recordedAt": recorded_at,
            "recordedBy": recorded_by,
            "release": {
                "issued": FEDERAL_REGISTER_THESAURUS_2025_ISSUED,
                "schemeIri": FEDERAL_REGISTER_THESAURUS_2025_SCHEME_IRI,
                "source": FEDERAL_REGISTER_THESAURUS_2025_URL,
                "sourceSha256": FEDERAL_REGISTER_THESAURUS_2025_SHA256,
                "parserVersion": (
                    FEDERAL_REGISTER_THESAURUS_2025_PARSER_VERSION
                ),
            },
            "counts": {
                "concepts": len(concepts),
                "variants": len(variants),
                "relations": len(relations),
                "suggestedOpenTermPatterns": len(open_patterns),
            },
            "coverage": {
                "id": coverage["id"],
                "digest": coverage["canonicalPayloadDigest"],
            },
            "crosswalkVersion": FEDERAL_REGISTER_CROSSWALK_VERSION,
            "candidatePolicy": {
                "candidateLookupAllowed": True,
                "defaultForProfiles": ["federal-register-document-v1"],
                "priority": "strongSourceNative",
                "rootOntology": False,
                "acceptedOutputAllowed": False,
            },
            "vocabularyBoundaries": {
                "currentFederalRegisterTopicsMerged": False,
                "currentFederalRegisterTopicsRole": (
                    "mutableSourceAssignedMetadata"
                ),
                "historical1995CandidateLookupAllowed": False,
                "historical1995Roles": [
                    "historicalLookup",
                    "regressionTesting",
                    "vocabularyChangeAnalysis",
                ],
                "historicalBroadCategoriesAsSkosHierarchy": False,
                "listsOfSubjectsSilentConceptMintingAllowed": False,
            },
            "artifacts": [
                _descriptor(path, payload)
                for path, payload in sorted(artifacts.items())
            ],
        }
    )
    return FederalRegisterThesaurus2025ManagedRelease(
        manifest=manifest,
        coverage=coverage,
        concepts=concepts,
        variants=variants,
        relations=relations,
        suggested_open_term_patterns=open_patterns,
        lists_of_subjects_policy=lists_policy,
        crosswalk=dict(crosswalk),
        source_pdf=thesaurus.source_artifact_bytes,
        source_extract=source_extract,
    )


@dataclass(frozen=True, slots=True)
class FederalRegisterThesaurus2025ManagedReleaseView:
    """Digest-verified reader for the packaged current vocabulary."""

    manifest: Mapping[str, Any]
    coverage: Mapping[str, Any]
    concepts: tuple[Mapping[str, Any], ...]
    variants: tuple[Mapping[str, Any], ...]
    relations: tuple[Mapping[str, Any], ...]
    lists_of_subjects_policy: Mapping[str, Any]
    crosswalk: Mapping[str, Any]

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
    ) -> FederalRegisterThesaurus2025ManagedReleaseView:
        path = Path(manifest_path)
        if path.is_symlink() or not path.is_file():
            raise FederalRegisterThesaurus2025ManagedReleaseError(
                "managed-release manifest must be a regular file"
            )
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FederalRegisterThesaurus2025ManagedReleaseError(
                "managed-release manifest is not valid JSON"
            ) from error
        if not isinstance(manifest, Mapping):
            raise FederalRegisterThesaurus2025ManagedReleaseError(
                "managed-release manifest must be an object"
            )
        _verify_seal(manifest, label="managed-release manifest")
        descriptors = manifest.get("artifacts")
        if not isinstance(descriptors, list):
            raise FederalRegisterThesaurus2025ManagedReleaseError(
                "managed-release artifact descriptors are required"
            )
        artifacts: dict[str, bytes] = {}
        for descriptor in descriptors:
            if not isinstance(descriptor, Mapping):
                raise FederalRegisterThesaurus2025ManagedReleaseError(
                    "artifact descriptor must be an object"
                )
            relative = descriptor.get("path")
            if not isinstance(relative, str):
                raise FederalRegisterThesaurus2025ManagedReleaseError(
                    "artifact path is required"
                )
            payload = _read_regular(path.parent, relative)
            if (
                descriptor.get("sha256") != _sha256_bytes(payload)
                or descriptor.get("byteLength") != len(payload)
            ):
                raise FederalRegisterThesaurus2025ManagedReleaseError(
                    f"artifact digest drifted: {relative}"
                )
            artifacts[relative] = payload
        required = {
            _CONCEPTS_PATH,
            _VARIANTS_PATH,
            _RELATIONS_PATH,
            _CROSSWALK_PATH,
            _LISTS_POLICY_PATH,
            _COVERAGE_PATH,
            _SOURCE_PDF_PATH,
            _SOURCE_EXTRACT_PATH,
        }
        if not required <= set(artifacts):
            raise FederalRegisterThesaurus2025ManagedReleaseError(
                "managed release lacks required records or source evidence"
            )
        if _sha256_bytes(artifacts[_SOURCE_PDF_PATH]) != (
            FEDERAL_REGISTER_THESAURUS_2025_SHA256
        ):
            raise FederalRegisterThesaurus2025ManagedReleaseError(
                "packaged PDF is not the pinned April 1, 2025 source"
            )
        try:
            coverage = json.loads(artifacts[_COVERAGE_PATH])
            crosswalk = json.loads(artifacts[_CROSSWALK_PATH])
            lists_policy = json.loads(artifacts[_LISTS_POLICY_PATH])
            concepts = tuple(
                json.loads(line)
                for line in artifacts[_CONCEPTS_PATH].splitlines()
            )
            variants = tuple(
                json.loads(line)
                for line in artifacts[_VARIANTS_PATH].splitlines()
            )
            relations = tuple(
                json.loads(line)
                for line in artifacts[_RELATIONS_PATH].splitlines()
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FederalRegisterThesaurus2025ManagedReleaseError(
                "managed-release record artifact is malformed"
            ) from error
        if not isinstance(coverage, Mapping):
            raise FederalRegisterThesaurus2025ManagedReleaseError(
                "coverage must be an object"
            )
        _verify_seal(coverage, label="coverage")
        validate_federal_register_thesaurus_crosswalk(crosswalk)
        counts = manifest.get("counts")
        if not isinstance(counts, Mapping) or (
            counts.get("concepts") != len(concepts)
            or counts.get("variants") != len(variants)
            or counts.get("relations") != len(relations)
        ):
            raise FederalRegisterThesaurus2025ManagedReleaseError(
                "managed-release counts drifted"
            )
        if any(
            row.get("predicateIri")
            == "http://www.w3.org/2004/02/skos/core#broader"
            for row in relations
        ):
            raise FederalRegisterThesaurus2025ManagedReleaseError(
                "Federal Register package must not contain SKOS broader"
            )
        return cls(
            manifest=manifest,
            coverage=coverage,
            concepts=concepts,
            variants=variants,
            relations=relations,
            lists_of_subjects_policy=lists_policy,
            crosswalk=crosswalk,
        )


__all__ = [
    "FEDERAL_REGISTER_THESAURUS_2025_MANAGED_RELEASE_VERSION",
    "FEDERAL_REGISTER_THESAURUS_2025_RESOURCE_ID",
    "FederalRegisterThesaurus2025ManagedRelease",
    "FederalRegisterThesaurus2025ManagedReleaseError",
    "FederalRegisterThesaurus2025ManagedReleaseView",
    "build_federal_register_thesaurus_2025_managed_release",
]
