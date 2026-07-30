"""Deterministic serializer for one RefSpec managed vocabulary release.

This module owns only the physical bundle layout consumed by
``ManagedReleaseView``. Source adapters remain responsible for building and
validating the Rulespec graph, REF records, normalized rows, and indexed
expressions before packaging them.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from refspec import binding
from refspec.storage import canonical_json
from refspec.vocabulary import (
    CONCEPT_EVENT_PARTICIPANT_COLUMNS,
    CONCEPT_LABEL_COLUMNS,
    CONCEPT_RELATION_COLUMNS,
)

_ABSOLUTE_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_PUBLICATION_TYPE = "urn:ref:type:PublicationReleaseManifest"
_COMBINED_RECEIPT_TYPE = "urn:ref:type:ReleaseGraphValidationReceipt"


class ManagedVocabularyBundleError(ValueError):
    """A managed vocabulary bundle cannot be serialized safely."""


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_plain_json(child) for child in value]
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return canonical_json(_plain_json(value)).encode("utf-8") + b"\n"


def _canonical_jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(_canonical_json_bytes(row) for row in rows)


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _artifact_descriptor(path: str, payload: bytes) -> dict[str, str]:
    return {"path": path, "sha256": _sha256_bytes(payload)}


def _source_artifact_path(identifier: str, payload: bytes) -> str:
    identity = canonical_json(
        {
            "id": identifier,
            "sha256": _sha256_bytes(payload),
            "byteLength": len(payload),
        }
    ).encode("utf-8")
    fingerprint = hashlib.sha256(identity).hexdigest()
    return f"sources/source-{fingerprint}.bin"


def _validated_record_identity(
    record: Mapping[str, Any],
    *,
    label: str,
) -> tuple[dict[str, Any], str, str, str]:
    plain = _plain_json(record)
    if not isinstance(plain, dict):
        raise ManagedVocabularyBundleError(f"{label} must be a JSON object")
    record_type = plain.get("type")
    identifier = plain.get("id")
    if not isinstance(record_type, str) or not record_type:
        raise ManagedVocabularyBundleError(f"{label}.type is required")
    if not isinstance(identifier, str) or _ABSOLUTE_IRI.fullmatch(identifier) is None:
        raise ManagedVocabularyBundleError(f"{label}.id must be an absolute IRI")
    digest_field = binding.digest_field(plain)
    digest = plain.get(digest_field)
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ManagedVocabularyBundleError(f"{label}.{digest_field} must be an exact SHA-256 digest")
    expected = binding.canonical_payload_digest(plain)
    if digest != expected:
        raise ManagedVocabularyBundleError(f"{label}.{digest_field} is stale: expected {expected}, got {digest}")
    return plain, record_type, identifier, digest


def _record_artifact_path(
    record_type: str,
    identifier: str,
    digest: str,
) -> str:
    local_name = re.split(r"[:/#]", record_type)[-1]
    slug = re.sub(r"[^a-z0-9]+", "-", local_name.casefold()).strip("-")
    if not slug:
        slug = "record"
    identity = canonical_json(
        {
            "type": record_type,
            "id": identifier,
            "digest": digest,
        }
    ).encode("utf-8")
    fingerprint = hashlib.sha256(identity).hexdigest()
    return f"records/{slug}-{fingerprint}.json"


def _parquet_bytes(
    *,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> bytes:
    schema = pa.schema([(column, pa.string()) for column in columns])
    normalized = [
        {
            column: (
                None
                if row.get(column) is None
                else canonical_json(_plain_json(row[column]))
                if isinstance(row[column], (Mapping, list, tuple))
                else str(row[column])
            )
            for column in columns
        }
        for row in rows
    ]
    table = pa.Table.from_pylist(normalized, schema=schema) if normalized else schema.empty_table()
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="zstd")
    return sink.getvalue().to_pybytes()


@dataclass(frozen=True, slots=True)
class ManagedVocabularyBundle:
    """One source-neutral managed vocabulary bundle ready for publication."""

    rulespec_graph_id: str
    rulespec_graph: Mapping[str, Any]
    ref_records: tuple[Mapping[str, Any], ...]
    normalized_labels: tuple[Mapping[str, Any], ...]
    normalized_relations: tuple[Mapping[str, Any], ...]
    normalized_participants: tuple[Mapping[str, Any], ...]
    indexed_expressions: tuple[Mapping[str, Any], ...]
    publication_release_manifest: Mapping[str, Any]
    combined_validation_receipt: Mapping[str, Any]
    rulespec_dependency_manifest_bytes: bytes
    expression_corpus_snapshot: Mapping[str, str]
    source_artifacts: Mapping[str, bytes]
    _corpus_identity_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if _ABSOLUTE_IRI.fullmatch(self.rulespec_graph_id) is None:
            raise ManagedVocabularyBundleError("rulespec_graph_id must be an absolute IRI")
        if not isinstance(self.rulespec_graph, Mapping):
            raise ManagedVocabularyBundleError("rulespec_graph must be a default-graph JSON-LD document")
        graph_nodes = self.rulespec_graph.get("@graph")
        if (
            "@id" in self.rulespec_graph
            or not isinstance(graph_nodes, Sequence)
            or isinstance(graph_nodes, (str, bytes))
            or not graph_nodes
        ):
            raise ManagedVocabularyBundleError("rulespec_graph must be a default-graph JSON-LD document")
        if not self.ref_records:
            raise ManagedVocabularyBundleError("ref_records must contain at least one operational REF record")
        if (
            not isinstance(self.rulespec_dependency_manifest_bytes, bytes)
            or not self.rulespec_dependency_manifest_bytes
        ):
            raise ManagedVocabularyBundleError("rulespec_dependency_manifest_bytes must be non-empty bytes")
        snapshot = _plain_json(self.expression_corpus_snapshot)
        if (
            not isinstance(snapshot, dict)
            or set(snapshot) != {"id", "digest"}
            or not isinstance(snapshot.get("id"), str)
            or _ABSOLUTE_IRI.fullmatch(snapshot["id"]) is None
            or not isinstance(snapshot.get("digest"), str)
            or _SHA256.fullmatch(snapshot["digest"]) is None
        ):
            raise ManagedVocabularyBundleError("expression_corpus_snapshot must be one exact id and digest")
        if not isinstance(self.source_artifacts, Mapping) or not self.source_artifacts:
            raise ManagedVocabularyBundleError(
                "source_artifacts must map one or more absolute artifact IRIs to exact bytes"
            )
        source_paths: set[str] = set()
        for identifier, payload in self.source_artifacts.items():
            if not isinstance(identifier, str) or _ABSOLUTE_IRI.fullmatch(identifier) is None:
                raise ManagedVocabularyBundleError(
                    "source_artifacts keys must be absolute artifact IRIs"
                )
            if not isinstance(payload, bytes) or not payload:
                raise ManagedVocabularyBundleError(
                    f"source_artifacts[{identifier!r}] must be non-empty exact bytes"
                )
            path = _source_artifact_path(identifier, payload)
            if path in source_paths:
                raise ManagedVocabularyBundleError(
                    "source_artifacts produced a duplicate artifact path"
                )
            source_paths.add(path)
        if not self.indexed_expressions:
            raise ManagedVocabularyBundleError(
                "indexed_expressions must not be empty"
            )
        object.__setattr__(
            self,
            "_corpus_identity_digest",
            snapshot["digest"],
        )
        publication, publication_type, _, _ = _validated_record_identity(
            self.publication_release_manifest,
            label="publication_release_manifest",
        )
        if publication_type != _PUBLICATION_TYPE:
            raise ManagedVocabularyBundleError("publication_release_manifest has the wrong REF record type")
        receipt, receipt_type, _, _ = _validated_record_identity(
            self.combined_validation_receipt,
            label="combined_validation_receipt",
        )
        if receipt_type != _COMBINED_RECEIPT_TYPE:
            raise ManagedVocabularyBundleError("combined_validation_receipt has the wrong REF record type")
        del publication, receipt
        self._record_artifacts()

    def _record_artifacts(self) -> tuple[tuple[str, bytes], ...]:
        records: list[tuple[str, bytes]] = []
        identifiers: set[str] = set()
        paths: dict[str, tuple[str, str, str]] = {}
        for index, record in enumerate(self.ref_records):
            plain, record_type, identifier, digest = _validated_record_identity(
                record,
                label=f"ref_records[{index}]",
            )
            if identifier in identifiers:
                raise ManagedVocabularyBundleError(f"ref_records repeats identifier {identifier!r}")
            identifiers.add(identifier)
            path = _record_artifact_path(
                record_type,
                identifier,
                digest,
            )
            identity = (record_type, identifier, digest)
            if path in paths:
                raise ManagedVocabularyBundleError(
                    f"ref_records produced a duplicate artifact path for {paths[path]!r} and {identity!r}"
                )
            paths[path] = identity
            records.append((path, _canonical_json_bytes(plain)))
        return tuple(sorted(records))

    def _content_artifacts(
        self,
        *,
        include_expression_corpus: bool = True,
    ) -> dict[str, bytes]:
        artifacts = {
            "rulespec/release.jsonld": _canonical_json_bytes(self.rulespec_graph),
            "records/publication-release-manifest.json": (_canonical_json_bytes(self.publication_release_manifest)),
            "validation/combined-receipt.json": _canonical_json_bytes(self.combined_validation_receipt),
            "rulespec/rulespec-dependency.json": (self.rulespec_dependency_manifest_bytes),
            "tables/concept_labels.parquet": _parquet_bytes(
                columns=CONCEPT_LABEL_COLUMNS,
                rows=self.normalized_labels,
            ),
            "tables/concept_relations.parquet": _parquet_bytes(
                columns=CONCEPT_RELATION_COLUMNS,
                rows=self.normalized_relations,
            ),
            "tables/concept_event_participants.parquet": _parquet_bytes(
                columns=CONCEPT_EVENT_PARTICIPANT_COLUMNS,
                rows=self.normalized_participants,
            ),
        }
        if include_expression_corpus:
            artifacts["corpus/indexed-expressions.jsonl"] = (
                _canonical_jsonl_bytes(self.indexed_expressions)
            )
        for identifier, payload in sorted(self.source_artifacts.items()):
            path = _source_artifact_path(identifier, payload)
            if path in artifacts:
                raise ManagedVocabularyBundleError(f"duplicate managed artifact path {path}")
            artifacts[path] = payload
        for path, payload in self._record_artifacts():
            if path in artifacts:
                raise ManagedVocabularyBundleError(f"duplicate managed artifact path {path}")
            artifacts[path] = payload
        return dict(sorted(artifacts.items()))

    def _manifest_for_content(
        self,
        content: Mapping[str, bytes],
        *,
        expression_corpus_artifact: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        record_paths = [path for path, _payload in self._record_artifacts()]
        source_artifacts = {
            identifier: {
                **_artifact_descriptor(
                    _source_artifact_path(identifier, payload),
                    payload,
                ),
                "byteLength": len(payload),
            }
            for identifier, payload in sorted(self.source_artifacts.items())
        }
        if expression_corpus_artifact is None:
            expression_corpus_artifact = _artifact_descriptor(
                "corpus/indexed-expressions.jsonl",
                content["corpus/indexed-expressions.jsonl"],
            )
        return {
            "bundleVersion": "1.0",
            "publicationReleaseManifest": _artifact_descriptor(
                "records/publication-release-manifest.json",
                content["records/publication-release-manifest.json"],
            ),
            "refRecords": [_artifact_descriptor(path, content[path]) for path in record_paths],
            "rulespecGraph": _artifact_descriptor(
                "rulespec/release.jsonld",
                content["rulespec/release.jsonld"],
            ),
            "rulespecGraphId": self.rulespec_graph_id,
            "rulespecDependencyManifest": _artifact_descriptor(
                "rulespec/rulespec-dependency.json",
                content["rulespec/rulespec-dependency.json"],
            ),
            "combinedValidationReceipt": _artifact_descriptor(
                "validation/combined-receipt.json",
                content["validation/combined-receipt.json"],
            ),
            "normalizedTables": [
                {
                    "name": name,
                    **_artifact_descriptor(path, content[path]),
                }
                for name, path in (
                    (
                        "concept_labels",
                        "tables/concept_labels.parquet",
                    ),
                    (
                        "concept_relations",
                        "tables/concept_relations.parquet",
                    ),
                    (
                        "concept_event_participants",
                        "tables/concept_event_participants.parquet",
                    ),
                )
            ],
            "indexedExpressionCorpus": {
                **dict(expression_corpus_artifact),
                "expressionCorpusSnapshot": dict(self.expression_corpus_snapshot),
                "recordCount": len(self.indexed_expressions),
                "schemaVersion": "ref-indexed-expression-corpus-1.0",
                "canonicalIdentityDigest": self._corpus_identity_digest,
            },
            "sourceArtifacts": source_artifacts,
        }

    def manifest(self) -> dict[str, Any]:
        """Return the closed manifest consumed by ``ManagedReleaseView``."""

        return self._manifest_for_content(self._content_artifacts())

    def artifact_bytes(self) -> dict[str, bytes]:
        """Return every content artifact plus its closed bundle manifest."""

        artifacts = self._content_artifacts()
        artifacts["managed-release-bundle.json"] = _canonical_json_bytes(self._manifest_for_content(artifacts))
        return dict(sorted(artifacts.items()))

    def write_to(self, output_dir: Path | str) -> Mapping[str, Path]:
        """Write deterministically without materializing the large corpus."""

        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}
        artifacts = self._content_artifacts(
            include_expression_corpus=False
        )
        for relative, payload in artifacts.items():
            destination = root / relative
            if destination.exists() and destination.read_bytes() != payload:
                raise FileExistsError(f"refusing to overwrite different artifact {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            written[relative] = destination

        corpus_relative = "corpus/indexed-expressions.jsonl"
        corpus_destination = root / corpus_relative
        corpus_destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".indexed-expressions-",
            suffix=".tmp",
            dir=corpus_destination.parent,
        )
        temporary = Path(temporary_name)
        digest = hashlib.sha256()
        try:
            with os.fdopen(descriptor, "wb") as output:
                descriptor = -1
                for record in self.indexed_expressions:
                    line = _canonical_json_bytes(record)
                    digest.update(line)
                    output.write(line)
                output.flush()
                os.fsync(output.fileno())
            corpus_sha256 = "sha256:" + digest.hexdigest()
            if corpus_destination.exists():
                existing_digest = hashlib.sha256()
                with corpus_destination.open("rb") as source:
                    for chunk in iter(
                        lambda: source.read(1024 * 1024),
                        b"",
                    ):
                        existing_digest.update(chunk)
                if (
                    "sha256:" + existing_digest.hexdigest()
                    != corpus_sha256
                ):
                    raise FileExistsError(
                        "refusing to overwrite different artifact "
                        f"{corpus_destination}"
                    )
            else:
                try:
                    os.link(temporary, corpus_destination)
                except FileExistsError:
                    existing_digest = hashlib.sha256(
                        corpus_destination.read_bytes()
                    ).hexdigest()
                    if f"sha256:{existing_digest}" != corpus_sha256:
                        raise FileExistsError(
                            "refusing to overwrite different artifact "
                            f"{corpus_destination}"
                        )
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
        written[corpus_relative] = corpus_destination

        manifest = self._manifest_for_content(
            artifacts,
            expression_corpus_artifact={
                "path": corpus_relative,
                "sha256": corpus_sha256,
            },
        )
        manifest_relative = "managed-release-bundle.json"
        manifest_payload = _canonical_json_bytes(manifest)
        manifest_destination = root / manifest_relative
        if (
            manifest_destination.exists()
            and manifest_destination.read_bytes() != manifest_payload
        ):
            raise FileExistsError(
                "refusing to overwrite different artifact "
                f"{manifest_destination}"
            )
        manifest_destination.write_bytes(manifest_payload)
        written[manifest_relative] = manifest_destination
        return written
