"""Development-only managed release for the URI-verified ICPSR subset.

The public ICPSR index supplies stable term URIs and numeric codes.  The
separately published ``subject.xml`` supplies notes and thesaurus relations.
This module joins only labels observed in both sources, records every source
version gap, and packages the exact source bytes with deterministic concept,
expression, coverage, and release records.

The result is candidate-lookup material for the Spicy Regs experiment.  It is
not a claim that the XML snapshot and current public index are one complete,
publisher-versioned release.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from refspec.immutable import deep_freeze_json
from refspec.registry.icpsr_subject import (
    ICPSR_INDEX_LETTERS,
    ICPSR_INDEX_PARSER_VERSION,
    ICPSR_SUBJECT_SCHEME_IRI,
    ICPSR_SUBJECT_XML_BYTE_LENGTH,
    ICPSR_SUBJECT_XML_SHA256,
    IcpsrIndexTerm,
    IcpsrSubjectIndex,
    IcpsrXmlSnapshot,
    build_icpsr_subject_index,
    compare_icpsr_xml_to_official_index,
    parse_icpsr_subject_xml,
)
from refspec.registry.infrastructure.controlled_identifier import validate_identifier_date
from refspec.release_model import canonical_text_digest, normalize_unicode_text
from refspec.storage import canonical_json

MANAGED_RELEASE_VERSION = "icpsr-uri-verified-development-v1"
PARSER_VERSION = "refspec-icpsr-managed-release-v1"
DEVELOPMENT_ENVIRONMENT_IRI = "urn:ref:environment:spicy-regs-experimental-playground"
PREFERRED_LABEL_IRI = "http://www.w3.org/2004/02/skos/core#prefLabel"
ALTERNATE_LABEL_IRI = "http://www.w3.org/2004/02/skos/core#altLabel"
SCOPE_NOTE_IRI = "http://www.w3.org/2004/02/skos/core#scopeNote"

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
_RELATION_FIELDS = (
    ("broader", "broader_labels"),
    ("narrower", "narrower_labels"),
    ("related", "related_labels"),
    ("use", "use_labels"),
    ("usedFor", "used_for_labels"),
)


class IcpsrManagedReleaseError(ValueError):
    """The exact ICPSR sources cannot form the bounded development release."""


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _digest_json(value: object) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _json_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8") + b"\n"


def _jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(_json_bytes(dict(row)) for row in rows)


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    if "canonicalPayloadDigest" in result:
        raise IcpsrManagedReleaseError("record already contains canonicalPayloadDigest")
    result["canonicalPayloadDigest"] = _digest_json(result)
    return result


def _verify_seal(value: Mapping[str, Any], *, label: str) -> None:
    digest = value.get("canonicalPayloadDigest")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise IcpsrManagedReleaseError(f"{label}.canonicalPayloadDigest is required")
    unsigned = dict(value)
    del unsigned["canonicalPayloadDigest"]
    expected = _digest_json(unsigned)
    if digest != expected:
        raise IcpsrManagedReleaseError(f"{label}.canonicalPayloadDigest is stale")


def _safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise IcpsrManagedReleaseError(f"artifact path {value!r} must be a safe relative path")
    return path.as_posix()


def _read_regular(root: Path, relative_path: str) -> bytes:
    relative = _safe_relative_path(relative_path)
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise IcpsrManagedReleaseError(f"required ICPSR source is not a regular file: {relative}")
    return path.read_bytes()


def _verify_descriptor(
    descriptor: Mapping[str, Any],
    payload: bytes,
    *,
    label: str,
) -> None:
    if descriptor.get("byteLength") != len(payload):
        raise IcpsrManagedReleaseError(f"{label} byte length drifted")
    if descriptor.get("sha256") != _sha256_bytes(payload):
        raise IcpsrManagedReleaseError(f"{label} digest drifted")


def _legacy_capture_digest(manifest: Mapping[str, Any]) -> str:
    """Reproduce the manifest digest emitted before structured identifiers."""

    robots = manifest.get("robots")
    pages = manifest.get("pages")
    terms = manifest.get("terms")
    if not isinstance(robots, Mapping) or not isinstance(pages, list) or not isinstance(terms, list):
        raise IcpsrManagedReleaseError("ICPSR index manifest lacks robots, pages, or terms")
    identity = {
        "parserVersion": manifest.get("parserVersion"),
        "schemeIri": manifest.get("schemeIri"),
        "robots": {key: robots.get(key) for key in ("url", "sha256", "byteLength")},
        "pages": [
            {
                key: page.get(key)
                for key in (
                    "letter",
                    "url",
                    "resolvedUrl",
                    "sha256",
                    "byteLength",
                )
            }
            for page in pages
            if isinstance(page, Mapping)
        ],
        "terms": [
            {
                key: term.get(key)
                for key in (
                    "code",
                    "conceptIri",
                    "label",
                    "preferred",
                    "sourceLetter",
                )
            }
            for term in terms
            if isinstance(term, Mapping)
        ],
        "complete": manifest.get("complete"),
    }
    return _digest_json(identity)


def _manifest_term(term: IcpsrIndexTerm) -> dict[str, Any]:
    return {
        "code": term.code,
        "conceptIri": term.concept_iri,
        "label": term.label,
        "preferred": term.preferred,
        "sourceLetter": term.source_letter,
    }


@dataclass(frozen=True, slots=True)
class IcpsrManagedReleaseSources:
    """Verified source objects and exact bytes needed to reproduce a release."""

    index: IcpsrSubjectIndex
    xml: IcpsrXmlSnapshot
    source_capture_digest: str
    source_manifest_digest: str
    source_artifacts: Mapping[str, bytes]


def open_icpsr_managed_release_sources(
    capture_root: Path,
    *,
    expected_xml_sha256: str = ICPSR_SUBJECT_XML_SHA256,
    expected_xml_byte_length: int = ICPSR_SUBJECT_XML_BYTE_LENGTH,
    require_complete_index: bool = True,
) -> IcpsrManagedReleaseSources:
    """Verify an on-disk ICPSR index capture and its pinned XML snapshot."""

    root = Path(capture_root)
    manifest_payload = _read_regular(root, "index/manifest.json")
    try:
        manifest = json.loads(manifest_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IcpsrManagedReleaseError("ICPSR index manifest is not valid JSON") from error
    if not isinstance(manifest, Mapping):
        raise IcpsrManagedReleaseError("ICPSR index manifest must be a JSON object")
    if manifest.get("parserVersion") != ICPSR_INDEX_PARSER_VERSION:
        raise IcpsrManagedReleaseError("ICPSR index parser version drifted")
    if manifest.get("schemeIri") != ICPSR_SUBJECT_SCHEME_IRI:
        raise IcpsrManagedReleaseError("ICPSR scheme IRI drifted")
    if require_complete_index and manifest.get("complete") is not True:
        raise IcpsrManagedReleaseError("managed release requires a complete ICPSR index capture")

    robots_descriptor = manifest.get("robots")
    if not isinstance(robots_descriptor, Mapping):
        raise IcpsrManagedReleaseError("ICPSR index manifest robots descriptor is required")
    robots_path = robots_descriptor.get("path")
    if not isinstance(robots_path, str):
        raise IcpsrManagedReleaseError("ICPSR robots descriptor path is required")
    robots_payload = _read_regular(root / "index", robots_path)
    _verify_descriptor(
        robots_descriptor,
        robots_payload,
        label="ICPSR robots source",
    )

    raw_pages = manifest.get("pages")
    if not isinstance(raw_pages, list):
        raise IcpsrManagedReleaseError("ICPSR index manifest pages must be a list")
    pages: dict[str, bytes] = {}
    source_artifacts: dict[str, bytes] = {
        "index/manifest.json": manifest_payload,
        f"index/{_safe_relative_path(robots_path)}": robots_payload,
    }
    page_letters: list[str] = []
    for ordinal, descriptor in enumerate(raw_pages, start=1):
        if not isinstance(descriptor, Mapping):
            raise IcpsrManagedReleaseError(f"ICPSR page descriptor {ordinal} must be an object")
        letter = descriptor.get("letter")
        relative_path = descriptor.get("path")
        if not isinstance(letter, str) or not isinstance(
            relative_path,
            str,
        ):
            raise IcpsrManagedReleaseError(f"ICPSR page descriptor {ordinal} lacks letter or path")
        if letter in pages:
            raise IcpsrManagedReleaseError(f"ICPSR index manifest repeats letter {letter!r}")
        payload = _read_regular(root / "index", relative_path)
        _verify_descriptor(
            descriptor,
            payload,
            label=f"ICPSR index page {letter!r}",
        )
        pages[letter] = payload
        page_letters.append(letter)
        source_artifacts[f"index/{_safe_relative_path(relative_path)}"] = payload

    if require_complete_index and tuple(page_letters) != ICPSR_INDEX_LETTERS:
        raise IcpsrManagedReleaseError("ICPSR index page order or membership drifted")
    observed_at = manifest.get("observedAt")
    if observed_at is not None and not isinstance(observed_at, str):
        raise IcpsrManagedReleaseError("ICPSR observedAt must be a string or null")
    index = build_icpsr_subject_index(
        pages,
        robots_body=robots_payload,
        require_complete=require_complete_index,
        observed_at=observed_at,
    )
    raw_terms = manifest.get("terms")
    if not isinstance(raw_terms, list):
        raise IcpsrManagedReleaseError("ICPSR index manifest terms must be a list")
    manifest_terms = [
        {
            key: term.get(key)
            for key in (
                "code",
                "conceptIri",
                "label",
                "preferred",
                "sourceLetter",
            )
        }
        for term in raw_terms
        if isinstance(term, Mapping)
    ]
    if manifest_terms != [_manifest_term(term) for term in index.terms]:
        raise IcpsrManagedReleaseError("ICPSR parsed term identities do not match the capture manifest")
    capture_digest = manifest.get("captureDigest")
    if not isinstance(capture_digest, str):
        raise IcpsrManagedReleaseError("ICPSR captureDigest is required")
    current_manifest = (
        bool(raw_terms)
        and isinstance(
            raw_terms[0],
            Mapping,
        )
        and "identifiers" in raw_terms[0]
    )
    expected_capture_digest = index.capture_digest if current_manifest else _legacy_capture_digest(manifest)
    if capture_digest != expected_capture_digest:
        raise IcpsrManagedReleaseError("ICPSR captureDigest does not match exact manifest content")

    xml_payload = _read_regular(root, "subject.xml")
    if len(xml_payload) != expected_xml_byte_length or _sha256_bytes(xml_payload) != expected_xml_sha256:
        raise IcpsrManagedReleaseError("ICPSR subject.xml does not match its exact expected revision")
    xml = parse_icpsr_subject_xml(xml_payload)
    source_artifacts["subject.xml"] = xml_payload
    return IcpsrManagedReleaseSources(
        index=index,
        xml=xml,
        source_capture_digest=capture_digest,
        source_manifest_digest=_sha256_bytes(manifest_payload),
        source_artifacts=source_artifacts,
    )


def _relation_rows(
    *,
    source_concept_iri: str,
    xml_term: object,
    identities: Mapping[str, IcpsrIndexTerm],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = []
    for relation, field in _RELATION_FIELDS:
        labels = getattr(xml_term, field)
        for target_label in labels:
            target = identities.get(target_label)
            row: dict[str, Any] = {
                "relation": relation,
                "targetLabel": target_label,
            }
            if target is None:
                row["resolutionStatus"] = "unresolvedSourceSkew"
                gaps.append(
                    {
                        "sourceConceptIri": source_concept_iri,
                        "relation": relation,
                        "targetLabel": target_label,
                    }
                )
            else:
                row["resolutionStatus"] = "uriVerified"
                row["targetConceptIri"] = target.concept_iri
            rows.append(row)
    return rows, gaps


def _expression(
    *,
    release_iri: str,
    member_iri: str,
    semantic_property_iri: str,
    original_literal: str,
    role: str,
    source_path: str,
) -> dict[str, Any]:
    indexed_text = normalize_unicode_text(original_literal)
    identity = {
        "release": release_iri,
        "member": member_iri,
        "semanticProperty": semantic_property_iri,
        "literal": original_literal,
        "language": "en",
        "sourcePath": source_path,
    }
    return {
        "id": (
            "urn:ref:icpsr:indexed-expression:" + hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
        ),
        "memberIri": member_iri,
        "semanticPropertyIri": semantic_property_iri,
        "role": role,
        "originalLiteral": original_literal,
        "language": "en",
        "sourcePath": source_path,
        "indexedText": indexed_text,
        "indexedTextDigest": canonical_text_digest(indexed_text),
    }


@dataclass(frozen=True, slots=True)
class IcpsrManagedRelease:
    """Deterministic development bundle ready to write or inspect."""

    manifest: Mapping[str, Any]
    coverage: Mapping[str, Any]
    concepts: tuple[Mapping[str, Any], ...]
    indexed_expressions: tuple[Mapping[str, Any], ...]
    source_artifacts: Mapping[str, bytes]

    def artifact_bytes(self) -> dict[str, bytes]:
        artifacts = {
            "records/coverage.json": _json_bytes(self.coverage),
            "records/concepts.jsonl": _jsonl_bytes(self.concepts),
            "records/indexed-expressions.jsonl": _jsonl_bytes(self.indexed_expressions),
        }
        artifacts.update(
            {f"sources/{_safe_relative_path(path)}": payload for path, payload in self.source_artifacts.items()}
        )
        return artifacts

    def write_to(self, output_dir: Path) -> Path:
        """Publish exact artifacts idempotently, with the manifest last."""

        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        for relative_path, payload in sorted(self.artifact_bytes().items()):
            _publish_exact(root / relative_path, payload)
        manifest_path = root / "managed-release.json"
        _publish_exact(manifest_path, _json_bytes(self.manifest))
        return manifest_path


def _publish_exact(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise IcpsrManagedReleaseError(f"managed-release target differs: {path}")
        return
    with tempfile.NamedTemporaryFile(
        prefix=".icpsr-release-",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as output:
        temporary = Path(output.name)
        output.write(payload)
        output.flush()
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def build_icpsr_managed_release(
    sources: IcpsrManagedReleaseSources,
    *,
    recorded_at: str,
    recorded_by: str,
    require_complete_index: bool = True,
    expected_gap_counts: tuple[int, int] | None = None,
) -> IcpsrManagedRelease:
    """Build the exact URI-verified subset and record every excluded gap."""

    validate_identifier_date(recorded_at, "recorded_at")
    if _ABSOLUTE_IRI.fullmatch(recorded_by) is None:
        raise IcpsrManagedReleaseError("recorded_by must be an absolute IRI")
    if (
        _SHA256.fullmatch(sources.source_capture_digest) is None
        or _SHA256.fullmatch(sources.source_manifest_digest) is None
    ):
        raise IcpsrManagedReleaseError("source capture and manifest digests must be exact SHA-256 values")
    if require_complete_index and not sources.index.complete:
        raise IcpsrManagedReleaseError("managed release requires a complete index capture")
    report = compare_icpsr_xml_to_official_index(
        sources.xml,
        sources.index,
        require_complete_index=require_complete_index,
    )
    actual_gaps = (
        len(report.xml_only_labels),
        len(report.index_only_terms),
    )
    if expected_gap_counts is not None and actual_gaps != expected_gap_counts:
        raise IcpsrManagedReleaseError(
            f"ICPSR source-version gap counts drifted: expected {expected_gap_counts}, got {actual_gaps}"
        )

    scope = hashlib.sha256(
        canonical_json(
            {
                "indexCapture": sources.source_capture_digest,
                "xml": report.xml_sha256,
                "policy": MANAGED_RELEASE_VERSION,
            }
        ).encode("utf-8")
    ).hexdigest()
    release_iri = f"urn:ref:icpsr:release:development:{scope}"
    coverage_iri = f"urn:ref:icpsr:coverage:uri-verified-subset:{scope}"
    identities = sources.index.term_by_label()
    xml_by_label = {term.label: term for term in sources.xml.terms}
    shared = sorted(
        set(identities) & set(xml_by_label),
        key=lambda label: (
            identities[label].concept_iri,
            label,
        ),
    )
    release_identities = {label: identities[label] for label in shared}

    concepts: list[dict[str, Any]] = []
    expressions: list[dict[str, Any]] = []
    unresolved_relations: list[dict[str, str]] = []
    resolved_relation_count = 0
    relation_count = 0
    for label in shared:
        identity = identities[label]
        xml_term = xml_by_label[label]
        relations, relation_gaps = _relation_rows(
            source_concept_iri=identity.concept_iri,
            xml_term=xml_term,
            identities=release_identities,
        )
        unresolved_relations.extend(relation_gaps)
        relation_count += len(relations)
        resolved_relation_count += sum(row["resolutionStatus"] == "uriVerified" for row in relations)
        concepts.append(
            {
                "conceptIri": identity.concept_iri,
                "publisherCode": identity.code,
                "officialLabel": identity.label,
                "officialLabelRole": ("preferred" if identity.preferred else "alternate"),
                "xmlLabelRole": ("preferred" if xml_term.preferred else "alternate"),
                "sourceLetter": identity.source_letter,
                "sourceLocalRecordNumber": (xml_term.source_local_record_number),
                "scopeNotes": list(xml_term.scope_notes),
                "relations": relations,
                "inputTimestamp": xml_term.input_timestamp,
                "updateTimestamp": xml_term.update_timestamp,
                "identifiers": [identifier.as_dict() for identifier in identity.identifiers],
            }
        )
        label_property = PREFERRED_LABEL_IRI if identity.preferred else ALTERNATE_LABEL_IRI
        expressions.append(
            _expression(
                release_iri=release_iri,
                member_iri=identity.concept_iri,
                semantic_property_iri=label_property,
                original_literal=identity.label,
                role=("preferredLabel" if identity.preferred else "alternateLabel"),
                source_path=(f"index/pages/{identity.source_letter}#term={identity.code}"),
            )
        )
        for ordinal, note in enumerate(xml_term.scope_notes, start=1):
            expressions.append(
                _expression(
                    release_iri=release_iri,
                    member_iri=identity.concept_iri,
                    semantic_property_iri=SCOPE_NOTE_IRI,
                    original_literal=note,
                    role="scopeNote",
                    source_path=(f"subject.xml#record={xml_term.source_local_record_number};scopeNote={ordinal}"),
                )
            )

    index_only = [
        {
            "label": term.label,
            "code": term.code,
            "conceptIri": term.concept_iri,
            "preferred": term.preferred,
        }
        for term in report.index_only_terms
    ]
    role_conflicts = [
        {
            "label": conflict.label,
            "xmlPreferred": conflict.xml_preferred,
            "indexPreferred": conflict.index_preferred,
        }
        for conflict in report.role_conflicts
    ]
    coverage = _seal(
        {
            "type": "urn:ref:type:RegistryImportCoverageReport",
            "id": coverage_iri,
            "version": MANAGED_RELEASE_VERSION,
            "recordedAt": recorded_at,
            "recordedBy": recorded_by,
            "operationalState": "developmentOnly",
            "reportStatus": "developmentOnly",
            "identityPolicy": ("public-index URI verified shared labels only"),
            "sourceCounts": {
                "xmlTerms": report.xml_term_count,
                "publicIndexTerms": report.index_term_count,
                "uriVerifiedJoins": report.matched_term_count,
            },
            "gaps": {
                "xmlOnlyCount": len(report.xml_only_labels),
                "xmlOnlyLabels": list(report.xml_only_labels),
                "indexOnlyCount": len(report.index_only_terms),
                "indexOnlyTerms": index_only,
                "roleConflictCount": len(report.role_conflicts),
                "roleConflicts": role_conflicts,
                "unresolvedRelationCount": len(unresolved_relations),
                "unresolvedRelations": unresolved_relations,
            },
            "relationCoverage": {
                "sourceObservedCount": relation_count,
                "uriResolvedCount": resolved_relation_count,
                "explicitlyExcludedCount": len(unresolved_relations),
                "failedCount": 0,
            },
            "membershipCompleteForVerifiedSubset": True,
            "sourceVocabularyComplete": False,
            "candidateLookupAllowed": True,
            "acceptedOutputAllowed": False,
        }
    )

    concept_rows = tuple(concepts)
    expression_rows = tuple(sorted(expressions, key=lambda item: item["id"]))
    core_artifacts = {
        "records/coverage.json": _json_bytes(coverage),
        "records/concepts.jsonl": _jsonl_bytes(concept_rows),
        "records/indexed-expressions.jsonl": _jsonl_bytes(expression_rows),
    }
    source_artifacts = {
        f"sources/{_safe_relative_path(path)}": payload for path, payload in sources.source_artifacts.items()
    }
    artifact_descriptors = [
        {
            "path": path,
            "sha256": _sha256_bytes(payload),
            "byteLength": len(payload),
        }
        for path, payload in sorted({**core_artifacts, **source_artifacts}.items())
    ]
    manifest = _seal(
        {
            "type": "urn:ref:type:IcpsrManagedReleaseManifest",
            "id": f"urn:ref:icpsr:managed-release:{scope}",
            "version": MANAGED_RELEASE_VERSION,
            "parserVersion": PARSER_VERSION,
            "recordedAt": recorded_at,
            "recordedBy": recorded_by,
            "operationalState": "developmentOnly",
            "environment": DEVELOPMENT_ENVIRONMENT_IRI,
            "release": {
                "id": release_iri,
                "schemeIri": ICPSR_SUBJECT_SCHEME_IRI,
                "membershipPolicy": ("exact complete membership of URI-verified subset"),
            },
            "sources": {
                "indexCaptureDigest": sources.source_capture_digest,
                "indexManifestDigest": (sources.source_manifest_digest),
                "xmlDigest": report.xml_sha256,
                "xmlByteLength": sources.xml.source_byte_length,
            },
            "coverage": {
                "id": coverage["id"],
                "digest": coverage["canonicalPayloadDigest"],
            },
            "counts": {
                "concepts": len(concept_rows),
                "indexedExpressions": len(expression_rows),
                "xmlOnlyGaps": len(report.xml_only_labels),
                "indexOnlyGaps": len(report.index_only_terms),
                "roleConflicts": len(report.role_conflicts),
                "unresolvedRelations": len(unresolved_relations),
            },
            "rightsNote": (
                "Rights information is recorded for later review and does not restrict this development experiment."
            ),
            "candidateLookupAllowed": True,
            "acceptedOutputAllowed": False,
            "artifacts": artifact_descriptors,
        }
    )
    return IcpsrManagedRelease(
        manifest=manifest,
        coverage=coverage,
        concepts=concept_rows,
        indexed_expressions=expression_rows,
        source_artifacts=dict(sources.source_artifacts),
    )


@dataclass(frozen=True, slots=True)
class IcpsrLookupHit:
    """One deterministic lookup match in the development-only release."""

    concept_iri: str
    official_label: str
    matched_text: str
    role: str
    score: int


@dataclass(frozen=True, slots=True)
class IcpsrManagedReleaseView:
    """Verified public reader for an immutable ICPSR managed-release bundle."""

    manifest: Mapping[str, Any]
    coverage: Mapping[str, Any]
    concepts: tuple[Mapping[str, Any], ...]
    indexed_expressions: tuple[Mapping[str, Any], ...]

    @classmethod
    def open(
        cls,
        manifest_path: Path,
    ) -> IcpsrManagedReleaseView:
        path = Path(manifest_path)
        if path.is_symlink() or not path.is_file():
            raise IcpsrManagedReleaseError("managed-release manifest must be a regular file")
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IcpsrManagedReleaseError("managed-release manifest is not valid JSON") from error
        if not isinstance(manifest, Mapping):
            raise IcpsrManagedReleaseError("managed-release manifest must be an object")
        _verify_seal(manifest, label="managed-release manifest")
        if manifest.get("operationalState") != "developmentOnly" or manifest.get("acceptedOutputAllowed") is not False:
            raise IcpsrManagedReleaseError("ICPSR bundle must remain development-only")
        descriptors = manifest.get("artifacts")
        if not isinstance(descriptors, list) or not descriptors:
            raise IcpsrManagedReleaseError("managed-release artifacts are required")
        artifact_bytes: dict[str, bytes] = {}
        for descriptor in descriptors:
            if not isinstance(descriptor, Mapping):
                raise IcpsrManagedReleaseError("managed-release artifact descriptor must be an object")
            relative = descriptor.get("path")
            if not isinstance(relative, str):
                raise IcpsrManagedReleaseError("managed-release artifact path is required")
            payload = _read_regular(path.parent, relative)
            _verify_descriptor(
                descriptor,
                payload,
                label=f"managed-release artifact {relative!r}",
            )
            artifact_bytes[relative] = payload
        required = {
            "records/coverage.json",
            "records/concepts.jsonl",
            "records/indexed-expressions.jsonl",
        }
        if not required <= set(artifact_bytes):
            raise IcpsrManagedReleaseError("managed-release lacks coverage, concepts, or expressions")
        try:
            coverage = json.loads(artifact_bytes["records/coverage.json"])
            concepts = tuple(json.loads(line) for line in artifact_bytes["records/concepts.jsonl"].splitlines())
            expressions = tuple(
                json.loads(line) for line in artifact_bytes["records/indexed-expressions.jsonl"].splitlines()
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IcpsrManagedReleaseError("managed-release record artifact is malformed") from error
        if not isinstance(coverage, Mapping):
            raise IcpsrManagedReleaseError("managed-release coverage must be an object")
        _verify_seal(coverage, label="managed-release coverage")
        coverage_reference = manifest.get("coverage")
        if (
            not isinstance(coverage_reference, Mapping)
            or coverage_reference.get("id") != coverage.get("id")
            or coverage_reference.get("digest") != coverage.get("canonicalPayloadDigest")
        ):
            raise IcpsrManagedReleaseError("managed-release coverage reference drifted")
        counts = manifest.get("counts")
        if (
            not isinstance(counts, Mapping)
            or counts.get("concepts") != len(concepts)
            or counts.get("indexedExpressions") != len(expressions)
        ):
            raise IcpsrManagedReleaseError("managed-release record counts drifted")
        concept_iris = {concept.get("conceptIri") for concept in concepts if isinstance(concept, Mapping)}
        if len(concept_iris) != len(concepts) or any(
            not isinstance(value, str) or _ABSOLUTE_IRI.fullmatch(value) is None for value in concept_iris
        ):
            raise IcpsrManagedReleaseError("managed-release concept membership is invalid")
        for concept in concepts:
            relations = concept.get("relations")
            if not isinstance(relations, list):
                raise IcpsrManagedReleaseError("managed-release concept relations must be a list")
            for relation in relations:
                if not isinstance(relation, Mapping):
                    raise IcpsrManagedReleaseError("managed-release relation must be an object")
                status = relation.get("resolutionStatus")
                target = relation.get("targetConceptIri")
                if (status == "uriVerified" and target not in concept_iris) or (
                    status == "unresolvedSourceSkew" and target is not None
                ):
                    raise IcpsrManagedReleaseError("managed-release relation target membership drifted")
        expression_ids: set[str] = set()
        for expression in expressions:
            if not isinstance(expression, Mapping):
                raise IcpsrManagedReleaseError("indexed expression must be an object")
            identifier = expression.get("id")
            member = expression.get("memberIri")
            indexed_text = expression.get("indexedText")
            if (
                not isinstance(identifier, str)
                or identifier in expression_ids
                or member not in concept_iris
                or not isinstance(indexed_text, str)
                or expression.get("indexedTextDigest") != canonical_text_digest(indexed_text)
            ):
                raise IcpsrManagedReleaseError("indexed expression identity or text digest drifted")
            expression_ids.add(identifier)
        return cls(
            manifest=cast(
                Mapping[str, Any],
                deep_freeze_json(manifest),
            ),
            coverage=cast(
                Mapping[str, Any],
                deep_freeze_json(coverage),
            ),
            concepts=cast(
                tuple[Mapping[str, Any], ...],
                deep_freeze_json(concepts),
            ),
            indexed_expressions=cast(
                tuple[Mapping[str, Any], ...],
                deep_freeze_json(expressions),
            ),
        )

    def concept(
        self,
        concept_iri: str,
    ) -> Mapping[str, Any] | None:
        """Return one exact concept record by public ICPSR term URI."""

        return next(
            (concept for concept in self.concepts if concept.get("conceptIri") == concept_iri),
            None,
        )

    def lookup(
        self,
        text: str,
        *,
        limit: int = 20,
    ) -> tuple[IcpsrLookupHit, ...]:
        """Search exact, prefix, then contained normalized expressions."""

        query = normalize_unicode_text(text)
        if not query or limit <= 0:
            return ()
        concepts = {concept["conceptIri"]: concept for concept in self.concepts}
        role_weight = {
            "preferredLabel": 30,
            "alternateLabel": 20,
            "scopeNote": 10,
        }
        hits: list[IcpsrLookupHit] = []
        for expression in self.indexed_expressions:
            indexed = expression["indexedText"]
            if indexed == query:
                match_weight = 300
            elif indexed.startswith(query):
                match_weight = 200
            elif query in indexed:
                match_weight = 100
            else:
                continue
            member = expression["memberIri"]
            concept = concepts[member]
            role = expression["role"]
            hits.append(
                IcpsrLookupHit(
                    concept_iri=member,
                    official_label=concept["officialLabel"],
                    matched_text=expression["originalLiteral"],
                    role=role,
                    score=match_weight + role_weight.get(role, 0),
                )
            )
        hits.sort(
            key=lambda hit: (
                -hit.score,
                hit.official_label.casefold(),
                hit.concept_iri,
                hit.matched_text,
            )
        )
        return tuple(hits[:limit])


__all__ = [
    "DEVELOPMENT_ENVIRONMENT_IRI",
    "MANAGED_RELEASE_VERSION",
    "PARSER_VERSION",
    "IcpsrLookupHit",
    "IcpsrManagedRelease",
    "IcpsrManagedReleaseError",
    "IcpsrManagedReleaseSources",
    "IcpsrManagedReleaseView",
    "build_icpsr_managed_release",
    "open_icpsr_managed_release_sources",
]
