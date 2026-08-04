"""Lossless SSSOM distribution for a closed subject or value relation bundle.

The TSV is the interoperable mapping table.  The JSON Lines sidecar preserves
the facts SSSOM 1.0 cannot carry without changing their meaning: the mapping
assertion identity, exact release pins, typed evidence, and ring-specific
context.  The manifest seals both files to one verified
``RelationAssertionBundle``.

This module does not convert crosswalk candidates.  It accepts only relation
assertions that already close over exact releases and validated evidence.
Entity identity and legal-identity edges require their own interchange
profiles before they can be represented without weakening their semantics.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from typing_extensions import Self

from refspec import binding
from refspec.registry.infrastructure.artifact_serialization import (
    canonical_json_bytes,
    canonical_jsonl_bytes,
    plain_json,
    sha256_digest,
)
from refspec.registry.infrastructure.semantic_foundation import EvidenceAssertion, MappingAssertion

from .relation_assertion import RelationAssertionBundle, RelationAssertionError

RELATION_SSSOM_VERSION = "1.0"
RELATION_SSSOM_PACKAGE_KIND = "relationAssertionSssomDistribution"
RELATION_SSSOM_MAPPING_SET_NAMESPACE = "https://refspec.org/id/relation-assertion-sssom/"

# SSSOM uses standard Semantic Mapping Vocabulary terms for justification.
# Evidence classes remain in the lossless sidecar rather than minting custom
# SSSOM values that downstream mapping tools would not understand.
_SEMAPV = "https://w3id.org/semapv/vocab/"
REVIEWED_JUSTIFICATION = _SEMAPV + "MappingReview"
UNREVIEWED_JUSTIFICATION = _SEMAPV + "UnspecifiedMatching"
UNSPECIFIED_LICENSE = "https://w3id.org/sssom/license/unspecified"

# Edition-specific names prevent a consumer from silently expanding a concept
# through another edition of the same vocabulary. Unknown namespaces receive
# deterministic ns1, ns2, ... names below.
WELL_KNOWN_PREFIXES: Mapping[str, str] = {
    "http://www.w3.org/2004/02/skos/core#": "skos",
    "https://elsst.cessda.eu/id/": "elsstedition",
    "https://elsst.cessda.eu/id/6/": "elsst6",
    "https://w3id.org/semapv/vocab/": "semapv",
    "urn:ref:federal-register-thesaurus:2025-04-01:concept:": "frt25",
    "urn:ref:federal-register-thesaurus:2025-04-01:reference-resource-release:": ("frt25release"),
}

# Confidence is absent by design: MappingAssertion carries evidence, not a
# numeric confidence score, so the exporter must not invent one.
COLUMNS = (
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "mapping_justification",
    "mapping_source",
    "subject_source",
    "object_source",
    "mapping_tool",
    "mapping_tool_version",
    "see_also",
    "comment",
)

MAPPINGS_PATH = "mappings.sssom.tsv"
EVIDENCE_PATH = "mapping-evidence.jsonl"
MANIFEST_PATH = "distribution-manifest.json"
_DISTRIBUTION_FILES = frozenset({MAPPINGS_PATH, EVIDENCE_PATH, MANIFEST_PATH})
_SUPPORTED_RINGS = frozenset({"subject", "value"})

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_CELL_CHARACTERS = ("\t", "\n", "\r")
_ENTITY_COLUMNS = frozenset(
    {
        "subject_id",
        "predicate_id",
        "object_id",
        "mapping_justification",
        "subject_source",
        "object_source",
    }
)
_RECORD_COLUMNS = frozenset({"mapping_source", "see_also"})
_REVIEW_EVIDENCE_CLASSES = frozenset({"machineQualified", "humanReviewed"})
_MANIFEST_FIELDS = {
    "schemaVersion",
    "packageKind",
    "distributionId",
    "contentDigest",
    "semanticRing",
    "relationAssertionBundle",
    "mappingCount",
    "evidenceAssertionCount",
    "machineProofCount",
    "directEvidenceLinkCount",
    "semantics",
    "artifacts",
}
_ARTIFACT_FIELDS = {"path", "role", "mediaType", "sha256", "byteLength", "rowCount"}
_BUNDLE_PIN_FIELDS = {"id", "contentDigest", "manifestDigest"}
_SEMANTICS_FIELDS = {"sssomRows", "machineProofFacts", "productUse"}


class RelationSssomError(RelationAssertionError):
    """A relation SSSOM distribution is incomplete, stale, or mutable."""


def _plain(value: Any) -> Any:
    return plain_json(value)


def _canonical_bytes(value: object) -> bytes:
    plain = _plain(value)
    try:
        binding.validate_canonical_value(plain)
    except (TypeError, ValueError) as error:
        raise RelationSssomError(str(error)) from error
    return canonical_json_bytes(plain)


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RelationSssomError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _require_supported_ring(bundle: RelationAssertionBundle) -> None:
    if bundle.semantic_ring not in _SUPPORTED_RINGS:
        raise RelationSssomError(f"relation SSSOM supports only subject and value rings; got {bundle.semantic_ring}")


def _require_exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise RelationSssomError(
            f"{label} fields differ; missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _read_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise RelationSssomError(f"{label} must be valid canonical UTF-8 JSON") from error


def _read_jsonl(payload: bytes, label: str) -> tuple[Mapping[str, Any], ...]:
    if not payload or not payload.endswith(b"\n"):
        raise RelationSssomError(f"{label} must be non-empty newline-terminated JSON Lines")
    result: list[Mapping[str, Any]] = []
    for index, line in enumerate(payload.splitlines()):
        value = _read_json(line + b"\n", f"{label}[{index}]")
        if not isinstance(value, Mapping):
            raise RelationSssomError(f"{label}[{index}] must be an object")
        result.append(value)
    if canonical_jsonl_bytes(result) != payload:
        raise RelationSssomError(f"{label} bytes are not canonical JSON Lines")
    return tuple(result)


def _distribution_snapshot(root: Path) -> dict[str, bytes]:
    """Read the exact regular-file set and reject shape changes during the read."""

    entries = {item.name: item for item in root.iterdir()}
    if set(entries) != _DISTRIBUTION_FILES:
        raise RelationSssomError("relation SSSOM file set differs")
    if any(item.is_symlink() for item in entries.values()):
        raise RelationSssomError("relation SSSOM distribution must not contain symlinks")
    if any(not item.is_file() for item in entries.values()):
        raise RelationSssomError("relation SSSOM distribution must contain only regular files")
    result = {name: entries[name].read_bytes() for name in _DISTRIBUTION_FILES}
    final_entries = {item.name: item for item in root.iterdir()}
    if (
        set(final_entries) != _DISTRIBUTION_FILES
        or any(item.is_symlink() for item in final_entries.values())
        or any(not item.is_file() for item in final_entries.values())
    ):
        raise RelationSssomError("relation SSSOM distribution changed while reading")
    return result


def _split_iri(iri: str) -> tuple[str, str]:
    """Split one absolute IRI into a namespace and CURIE-safe local name."""

    if "#" in iri:
        namespace, _, local = iri.rpartition("#")
        namespace += "#"
    elif iri.startswith("urn:"):
        namespace, _, local = iri.rpartition(":")
        namespace += ":"
    else:
        namespace, _, local = iri.rpartition("/")
        namespace += "/"
    if not local or namespace in {"#", ":", "/"}:
        raise RelationSssomError(f"{iri!r} has no local name to compact")
    if ":" in local:
        raise RelationSssomError(f"{iri!r} would compact to a multi-colon CURIE")
    return namespace, local


def _scheme(iri: str) -> tuple[str, str]:
    prefix, separator, _ = iri.partition(":")
    if not prefix or not separator:
        raise RelationSssomError(f"{iri!r} has no URI scheme to declare")
    return prefix, prefix + ":"


@dataclass(frozen=True, slots=True)
class _Compactor:
    """A deterministic prefix map that resolves every identifier in the TSV."""

    prefixes: Mapping[str, str]

    @classmethod
    def over(cls, compacted: Iterable[str], verbatim: Iterable[str]) -> Self:
        namespaces = {_split_iri(iri)[0] for iri in compacted}
        named = {
            namespace: WELL_KNOWN_PREFIXES[namespace] for namespace in namespaces if namespace in WELL_KNOWN_PREFIXES
        }
        unnamed = sorted(namespace for namespace in namespaces if namespace not in named)
        generated = {namespace: f"ns{index}" for index, namespace in enumerate(unnamed, start=1)}
        schemes = {expansion: prefix for prefix, expansion in map(_scheme, verbatim)}
        prefixes = {**named, **generated, **schemes}
        if len(set(prefixes.values())) != len(prefixes):
            raise RelationSssomError("two namespaces claim one SSSOM prefix")
        return cls(prefixes=prefixes)

    def curie(self, iri: str) -> str:
        namespace, local = _split_iri(iri)
        return f"{self.prefixes[namespace]}:{local}"

    def curie_map(self) -> dict[str, str]:
        return {prefix: namespace for namespace, prefix in self.prefixes.items()}


def _cell(value: str, column: str) -> str:
    if any(character in value for character in _FORBIDDEN_CELL_CHARACTERS):
        raise RelationSssomError(f"{column} value contains a tab, newline, or carriage return")
    return value


def _metadata_lines(metadata: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in sorted(metadata):
        value = metadata[key]
        if isinstance(value, Mapping):
            lines.append(f"# {key}:")
            lines.extend(f"#   {name}: {json.dumps(value[name])}" for name in sorted(value))
        else:
            lines.append(f"# {key}: {json.dumps(value)}")
    return lines


def _direct_evidence(
    mapping: MappingAssertion,
    evidence_by_id: Mapping[str, EvidenceAssertion],
) -> tuple[EvidenceAssertion, ...]:
    return tuple(
        sorted((evidence_by_id[identifier] for identifier in mapping.evidence), key=lambda row: row.identifier)
    )


def _evidence_closure(
    direct: Sequence[EvidenceAssertion],
    evidence_by_id: Mapping[str, EvidenceAssertion],
) -> tuple[EvidenceAssertion, ...]:
    identifiers = {row.identifier for row in direct}
    pending = list(direct)
    while pending:
        row = pending.pop()
        if row.evidence_class != "operatorAdopted":
            continue
        adopted = cast(str, row.adopted_evidence)
        if adopted not in identifiers:
            identifiers.add(adopted)
            pending.append(evidence_by_id[adopted])
    return tuple(evidence_by_id[identifier] for identifier in sorted(identifiers))


def _justification(direct: Sequence[EvidenceAssertion]) -> str:
    if any(row.evidence_class in _REVIEW_EVIDENCE_CLASSES for row in direct):
        return REVIEWED_JUSTIFICATION
    return UNREVIEWED_JUSTIFICATION


def _sssom_rows(bundle: RelationAssertionBundle) -> list[dict[str, str]]:
    evidence_by_id = {row.identifier: row for row in bundle.evidence_assertions}
    rows: list[dict[str, str]] = []
    for mapping in bundle.mapping_assertions:
        direct = _direct_evidence(mapping, evidence_by_id)
        rows.append(
            {
                "subject_id": mapping.source_concept,
                "subject_label": "",
                "predicate_id": mapping.relation,
                "object_id": mapping.target_concept,
                "object_label": "",
                "mapping_justification": _justification(direct),
                "mapping_source": bundle.identifier,
                "subject_source": mapping.source_release,
                "object_source": mapping.target_release,
                "mapping_tool": "",
                "mapping_tool_version": "",
                "see_also": mapping.identifier,
                "comment": "; ".join(sorted({row.evidence_class for row in direct})),
            }
        )
    return rows


def relation_sssom_text(bundle: RelationAssertionBundle) -> str:
    """Render every mapping assertion as deterministic SSSOM 1.0 TSV."""

    if not isinstance(bundle, RelationAssertionBundle):
        raise RelationSssomError("relation SSSOM requires a RelationAssertionBundle")
    _require_supported_ring(bundle)
    bundle.verify()
    rows = _sssom_rows(bundle)
    compactor = _Compactor.over(
        (value for row in rows for column, value in row.items() if column in _ENTITY_COLUMNS),
        (value for row in rows for column, value in row.items() if column in _RECORD_COLUMNS),
    )
    rendered = sorted(
        (
            {
                column: _cell(compactor.curie(value) if column in _ENTITY_COLUMNS else value, column)
                for column, value in row.items()
            }
            for row in rows
        ),
        key=lambda row: (row["subject_id"], row["object_id"], row["predicate_id"], row["see_also"]),
    )
    mapping_set_id = RELATION_SSSOM_MAPPING_SET_NAMESPACE + bundle.content_digest.removeprefix("sha256:")
    metadata = {
        "comment": (
            f"Exported from RefSpec relation-assertion bundle {bundle.identifier}, "
            f"sealed at {bundle.content_digest}. Exact evidence is in {EVIDENCE_PATH}."
        ),
        "curie_map": compactor.curie_map(),
        "license": UNSPECIFIED_LICENSE,
        "mapping_set_id": mapping_set_id,
        "mapping_set_title": f"RefSpec {bundle.semantic_ring} relation assertions",
    }
    lines = [
        *_metadata_lines(metadata),
        "\t".join(COLUMNS),
        *("\t".join(row[column] for column in COLUMNS) for row in rendered),
    ]
    return "\n".join(lines) + "\n"


def _sidecar_rows(bundle: RelationAssertionBundle) -> list[dict[str, Any]]:
    evidence_by_id = {row.identifier: row for row in bundle.evidence_assertions}
    release_by_id = {cast(str, row["releaseId"]): row for row in bundle.release_pins}
    proof_by_id = {cast(str, row["id"]): row for row in bundle.machine_proof_pins}
    result: list[dict[str, Any]] = []
    for mapping in bundle.mapping_assertions:
        direct = _direct_evidence(mapping, evidence_by_id)
        closure = _evidence_closure(direct, evidence_by_id)
        mapping_record = mapping.as_record()
        endpoint_release_ids = {mapping.source_release, mapping.target_release}
        row: dict[str, Any] = {
            "mappingAssertionId": mapping.identifier,
            "assertionDigest": sha256_digest(_canonical_bytes(mapping_record)),
            "semanticRing": mapping.semantic_ring,
            "sourceConcept": mapping.source_concept,
            "targetConcept": mapping.target_concept,
            "sourceRelease": mapping.source_release,
            "targetRelease": mapping.target_release,
            "relation": mapping.relation,
            "assertedAt": mapping.asserted_at,
            "directEvidence": [item.as_record() for item in direct],
            "evidenceClosure": [item.as_record() for item in closure],
            "releasePins": [_plain(release_by_id[identifier]) for identifier in sorted(endpoint_release_ids)],
        }
        if mapping.context is not None:
            row["context"] = dict(mapping.context)
        machine = [item for item in closure if item.evidence_class == "machineQualified"]
        if machine:
            row["machineQualificationEvidence"] = [
                {
                    "evidenceAssertionId": item.identifier,
                    "candidate": item.candidate,
                    "machineProof": _plain(proof_by_id[cast(str, item.machine_proof)]),
                    "validationReceipts": list(item.validation_receipts),
                    "useCeiling": item.use_ceiling,
                }
                for item in machine
            ]
        reviews = [item for item in closure if item.evidence_class == "machineReviewed"]
        if reviews:
            row["machineReviewEvidence"] = [
                {
                    "evidenceAssertionId": item.identifier,
                    "candidate": item.candidate,
                    "machineProof": _plain(proof_by_id[cast(str, item.machine_proof)]),
                    "validationReceipts": list(item.validation_receipts),
                    "useCeiling": item.use_ceiling,
                }
                for item in reviews
            ]
        result.append(row)
    return sorted(result, key=lambda row: cast(str, row["mappingAssertionId"]))


def _data_artifacts(bundle: RelationAssertionBundle) -> dict[str, bytes]:
    return {
        MAPPINGS_PATH: relation_sssom_text(bundle).encode("utf-8"),
        EVIDENCE_PATH: canonical_jsonl_bytes(_sidecar_rows(bundle)),
    }


def _artifact_descriptors(bundle: RelationAssertionBundle, artifacts: Mapping[str, bytes]) -> list[dict[str, Any]]:
    mapping_count = len(bundle.mapping_assertions)
    return [
        {
            "path": MAPPINGS_PATH,
            "role": "sssomMappings",
            "mediaType": "text/tab-separated-values; charset=utf-8",
            "sha256": sha256_digest(artifacts[MAPPINGS_PATH]),
            "byteLength": len(artifacts[MAPPINGS_PATH]),
            "rowCount": mapping_count,
        },
        {
            "path": EVIDENCE_PATH,
            "role": "mappingEvidence",
            "mediaType": "application/jsonl",
            "sha256": sha256_digest(artifacts[EVIDENCE_PATH]),
            "byteLength": len(artifacts[EVIDENCE_PATH]),
            "rowCount": mapping_count,
        },
    ]


def _manifest_record(bundle: RelationAssertionBundle, artifacts: Mapping[str, bytes]) -> dict[str, Any]:
    basis = {
        "schemaVersion": RELATION_SSSOM_VERSION,
        "packageKind": RELATION_SSSOM_PACKAGE_KIND,
        "semanticRing": bundle.semantic_ring,
        "relationAssertionBundle": {
            "id": bundle.identifier,
            "contentDigest": bundle.content_digest,
            "manifestDigest": bundle.manifest_digest,
        },
        "mappingCount": len(bundle.mapping_assertions),
        "evidenceAssertionCount": len(bundle.evidence_assertions),
        "machineProofCount": len(bundle.machine_proof_pins),
        "directEvidenceLinkCount": sum(len(row.evidence) for row in bundle.mapping_assertions),
        "semantics": {
            "sssomRows": "interoperabilityProjection",
            "machineProofFacts": "derivedFromPinnedMachineProof",
            "productUse": "requiresEvidenceSidecarAndExactProductPolicy",
        },
        "artifacts": _artifact_descriptors(bundle, artifacts),
    }
    content_digest = sha256_digest(_canonical_bytes(basis))
    return {
        **basis,
        "distributionId": (
            f"urn:ref:relation-sssom-distribution:{bundle.semantic_ring}:{content_digest.removeprefix('sha256:')}"
        ),
        "contentDigest": content_digest,
    }


@dataclass(frozen=True, slots=True)
class RelationSssomDistribution:
    """A deterministic subject/value SSSOM table and evidence sidecar."""

    relation_bundle: RelationAssertionBundle
    _path: Path | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.relation_bundle, RelationAssertionBundle):
            raise RelationSssomError("relation SSSOM requires a RelationAssertionBundle")
        _require_supported_ring(self.relation_bundle)
        self.relation_bundle.verify()
        if self._path is not None:
            object.__setattr__(self, "_path", self._path.resolve(strict=True))

    @classmethod
    def create(cls, relation_bundle: RelationAssertionBundle) -> Self:
        """Build a distribution from already validated relation assertions."""

        return cls(relation_bundle=relation_bundle)

    @property
    def distribution_id(self) -> str:
        return cast(str, self.manifest_record()["distributionId"])

    @property
    def content_digest(self) -> str:
        return cast(str, self.manifest_record()["contentDigest"])

    def manifest_record(self) -> dict[str, Any]:
        artifacts = _data_artifacts(self.relation_bundle)
        return _manifest_record(self.relation_bundle, artifacts)

    def artifact_bytes(self) -> dict[str, bytes]:
        artifacts = _data_artifacts(self.relation_bundle)
        return {
            **artifacts,
            MANIFEST_PATH: _canonical_bytes(_manifest_record(self.relation_bundle, artifacts)),
        }

    @property
    def manifest_digest(self) -> str:
        return sha256_digest(self.artifact_bytes()[MANIFEST_PATH])

    def verify(self) -> None:
        """Reverify the relation bundle and any persisted distribution bytes."""

        rebuilt = RelationSssomDistribution.create(self.relation_bundle)
        if rebuilt.artifact_bytes() != self.artifact_bytes():
            raise RelationSssomError("relation SSSOM distribution no longer reproduces")
        if self._path is not None:
            reopened = RelationSssomDistribution.open(
                self._path / MANIFEST_PATH,
                expected_manifest_digest=self.manifest_digest,
                relation_bundle=self.relation_bundle,
            )
            if reopened.artifact_bytes() != self.artifact_bytes():
                raise RelationSssomError("persisted relation SSSOM bytes differ")

    def write_to(self, path: Path | str) -> Path:
        """Write all three artifacts atomically to a new directory."""

        destination = Path(path)
        if destination.exists() or destination.is_symlink():
            raise RelationSssomError(f"relation SSSOM destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
        try:
            for relative_path, payload in self.artifact_bytes().items():
                (temporary / relative_path).write_bytes(payload)
            os.replace(temporary, destination)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return destination

    @classmethod
    def open(
        cls,
        manifest_path: Path | str,
        *,
        expected_manifest_digest: str,
        relation_bundle: RelationAssertionBundle,
    ) -> Self:
        """Open exact bytes and reproduce them from the pinned relation bundle."""

        expected = _require_digest(expected_manifest_digest, "relation SSSOM manifest digest")
        if not isinstance(relation_bundle, RelationAssertionBundle):
            raise RelationSssomError("relation SSSOM requires a RelationAssertionBundle")
        _require_supported_ring(relation_bundle)
        relation_bundle.verify()
        requested = Path(manifest_path)
        if requested.is_symlink():
            raise RelationSssomError("relation SSSOM manifest must not be a symlink")
        candidate = requested / MANIFEST_PATH if requested.is_dir() else requested
        if candidate.name != MANIFEST_PATH or not candidate.is_file():
            raise RelationSssomError(f"relation SSSOM requires {MANIFEST_PATH}")
        root = candidate.parent.resolve(strict=True)
        if root.is_symlink() or not root.is_dir():
            raise RelationSssomError("relation SSSOM root must be a regular directory")
        observed = _distribution_snapshot(root)
        manifest_bytes = observed[MANIFEST_PATH]
        if sha256_digest(manifest_bytes) != expected:
            raise RelationSssomError("relation SSSOM manifest digest differs")
        manifest = _read_json(manifest_bytes, "relation SSSOM manifest")
        if not isinstance(manifest, Mapping):
            raise RelationSssomError("relation SSSOM manifest must be an object")
        _require_exact_fields(manifest, _MANIFEST_FIELDS, "relation SSSOM manifest")
        if (
            manifest.get("schemaVersion") != RELATION_SSSOM_VERSION
            or manifest.get("packageKind") != RELATION_SSSOM_PACKAGE_KIND
        ):
            raise RelationSssomError("relation SSSOM manifest version is unsupported")
        semantics = manifest.get("semantics")
        if not isinstance(semantics, Mapping):
            raise RelationSssomError("relation SSSOM manifest semantics must be an object")
        _require_exact_fields(semantics, _SEMANTICS_FIELDS, "relation SSSOM manifest semantics")
        if semantics != {
            "sssomRows": "interoperabilityProjection",
            "machineProofFacts": "derivedFromPinnedMachineProof",
            "productUse": "requiresEvidenceSidecarAndExactProductPolicy",
        }:
            raise RelationSssomError("relation SSSOM manifest semantics differ")
        bundle_pin = manifest.get("relationAssertionBundle")
        if not isinstance(bundle_pin, Mapping):
            raise RelationSssomError("relation SSSOM manifest bundle pin must be an object")
        _require_exact_fields(bundle_pin, _BUNDLE_PIN_FIELDS, "relation SSSOM bundle pin")
        descriptors = manifest.get("artifacts")
        if not isinstance(descriptors, Sequence) or isinstance(descriptors, (str, bytes)) or len(descriptors) != 2:
            raise RelationSssomError("relation SSSOM manifest must name two data artifacts")
        for index, descriptor in enumerate(descriptors):
            if not isinstance(descriptor, Mapping):
                raise RelationSssomError(f"relation SSSOM artifact[{index}] must be an object")
            _require_exact_fields(descriptor, _ARTIFACT_FIELDS, f"relation SSSOM artifact[{index}]")

        try:
            observed[MAPPINGS_PATH].decode("utf-8")
        except UnicodeDecodeError as error:
            raise RelationSssomError("relation SSSOM TSV must be UTF-8") from error
        _read_jsonl(observed[EVIDENCE_PATH], "relation SSSOM evidence sidecar")
        rebuilt = cls.create(relation_bundle)
        if observed != rebuilt.artifact_bytes():
            raise RelationSssomError("relation SSSOM artifacts differ from the pinned relation bundle")
        result = cls(relation_bundle=relation_bundle, _path=root)
        try:
            final_snapshot = _distribution_snapshot(root)
        except RelationSssomError as error:
            raise RelationSssomError("relation SSSOM distribution changed while opening") from error
        if final_snapshot != observed:
            raise RelationSssomError("relation SSSOM distribution changed while opening")
        return result


__all__ = [
    "EVIDENCE_PATH",
    "MANIFEST_PATH",
    "MAPPINGS_PATH",
    "RELATION_SSSOM_MAPPING_SET_NAMESPACE",
    "RELATION_SSSOM_PACKAGE_KIND",
    "RELATION_SSSOM_VERSION",
    "RelationSssomDistribution",
    "RelationSssomError",
    "relation_sssom_text",
]
