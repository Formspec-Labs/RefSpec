"""Closed-layout, determinism and digest-resealing tests for ManagedVocabularyBundle.

The bundle's manifest key set is pinned exactly, artifact paths must be stable
under record reordering, the expression corpus must stream, and resealing must
propagate input digests in dependency order while refusing cycles.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import refspec.registry.infrastructure.managed_vocabulary_bundle as bundle_module
from refspec import binding
from refspec.registry import (
    ManagedVocabularyBundle,
    ManagedVocabularyBundleError,
)
from refspec.registry.infrastructure.managed_vocabulary_bundle import (
    managed_ref_record_artifact_path,
    reseal_linked_ref_records,
)
from refspec.storage import canonical_json
from refspec.vocabulary import (
    CONCEPT_EVENT_PARTICIPANT_COLUMNS,
    CONCEPT_LABEL_COLUMNS,
    CONCEPT_RELATION_COLUMNS,
    seal_payload,
)


def _digest(value: str) -> str:
    """Return the ``sha256:`` digest of a UTF-8 string."""
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record(record_type: str, identifier: str, marker: str) -> dict[str, object]:
    """Seal a minimal ref record of the given type carrying a marker."""
    return seal_payload(
        {
            "type": record_type,
            "id": identifier,
            "version": "1.0",
            "marker": marker,
        }
    )


def _bundle() -> ManagedVocabularyBundle:
    """Build the fixture bundle: two sealed receipts, one expression and one source artifact."""
    first_receipt = _record(
        "urn:ref:type:RunReceipt",
        "urn:test:run-receipt:first",
        "first",
    )
    second_receipt = _record(
        "urn:ref:type:RunReceipt",
        "urn:test:run-receipt:second",
        "second",
    )
    publication = seal_payload(
        {
            "type": "urn:ref:type:PublicationReleaseManifest",
            "id": "urn:test:publication:v1",
            "version": "1.0",
        }
    )
    combined_receipt = seal_payload(
        {
            "type": "urn:ref:type:ReleaseGraphValidationReceipt",
            "id": "urn:test:validation-receipt:v1",
            "version": "1.0",
        }
    )
    expression = seal_payload(
        {
            "type": "urn:ref:type:IndexedVocabularyExpression",
            "id": "urn:test:expression:one",
            "version": "1.0",
            "indexedText": "worker safety",
        }
    )
    return ManagedVocabularyBundle(
        rulespec_graph_id="urn:test:rulespec-graph:v1",
        rulespec_graph={
            "@context": {"rkaf": "https://rulespec.org/ns/v1#"},
            "@graph": [{"@id": "urn:test:release:v1"}],
        },
        ref_records=(first_receipt, second_receipt),
        normalized_labels=({column: f"label-{column}" for column in CONCEPT_LABEL_COLUMNS},),
        normalized_relations=({column: f"relation-{column}" for column in CONCEPT_RELATION_COLUMNS},),
        normalized_participants=({column: f"participant-{column}" for column in CONCEPT_EVENT_PARTICIPANT_COLUMNS},),
        indexed_expressions=(expression,),
        publication_release_manifest=publication,
        combined_validation_receipt=combined_receipt,
        rulespec_dependency_manifest_bytes=b'{"rulespecVersion":"test"}\n',
        expression_corpus_snapshot={
            "id": "urn:test:expression-corpus:v1",
            "digest": _digest("expression-corpus"),
        },
        source_artifacts={
            "urn:test:distribution:source": b"@prefix test: <urn:test:> .\n",
        },
    )


def _descriptor_digest(payload: bytes) -> str:
    """Return the ``sha256:`` digest of raw bytes."""
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def test_bundle_serializer_emits_the_closed_managed_release_layout() -> None:
    """Pins the exact manifest key set, unique runreceipt paths and the three normalized tables' columns."""
    bundle = _bundle()
    artifacts = bundle.artifact_bytes()
    manifest = bundle.manifest()

    assert set(manifest) == {
        "bundleVersion",
        "publicationReleaseManifest",
        "refRecords",
        "rulespecGraph",
        "rulespecGraphId",
        "rulespecDependencyManifest",
        "combinedValidationReceipt",
        "normalizedTables",
        "indexedExpressionCorpus",
        "sourceArtifacts",
    }
    assert manifest["bundleVersion"] == "1.0"
    assert manifest["rulespecGraphId"] == "urn:test:rulespec-graph:v1"
    ref_paths = [descriptor["path"] for descriptor in manifest["refRecords"]]
    assert len(ref_paths) == 2
    assert len(set(ref_paths)) == 2
    assert all(path.startswith("records/runreceipt-") for path in ref_paths)
    assert all(path in artifacts for path in ref_paths)
    assert all(
        descriptor["sha256"] == _descriptor_digest(artifacts[descriptor["path"]])
        for descriptor in manifest["refRecords"]
    )

    manifest_bytes = artifacts["managed-release-bundle.json"]
    assert json.loads(manifest_bytes) == manifest
    assert manifest_bytes == canonical_json(manifest).encode("utf-8") + b"\n"
    assert artifacts["corpus/indexed-expressions.jsonl"].count(b"\n") == 1
    source_descriptor = manifest["sourceArtifacts"][
        "urn:test:distribution:source"
    ]
    assert source_descriptor["byteLength"] == len(
        b"@prefix test: <urn:test:> .\n"
    )
    assert (
        artifacts[source_descriptor["path"]]
        == b"@prefix test: <urn:test:> .\n"
    )

    tables = {
        descriptor["name"]: pq.read_table(pa.BufferReader(artifacts[descriptor["path"]]))
        for descriptor in manifest["normalizedTables"]
    }
    assert tuple(tables["concept_labels"].column_names) == (CONCEPT_LABEL_COLUMNS)
    assert tuple(tables["concept_relations"].column_names) == (CONCEPT_RELATION_COLUMNS)
    assert tuple(tables["concept_event_participants"].column_names) == CONCEPT_EVENT_PARTICIPANT_COLUMNS
    assert all(table.num_rows == 1 for table in tables.values())


def test_repeated_record_types_have_stable_order_independent_paths(
    tmp_path,
) -> None:
    """Pins that reversing the records leaves artifact bytes identical and that two writes agree."""
    bundle = _bundle()
    reordered = replace(
        bundle,
        ref_records=tuple(reversed(bundle.ref_records)),
    )

    assert bundle.artifact_bytes() == reordered.artifact_bytes()
    first_write = bundle.write_to(tmp_path)
    second_write = bundle.write_to(tmp_path)
    assert first_write == second_write


def test_write_streams_expression_corpus_without_building_one_bytes_object(
    tmp_path,
    monkeypatch,
) -> None:
    """Pins that write_to streams the expression corpus rather than calling the materializing jsonl helper."""
    bundle = _bundle()

    def reject_materialization(_rows):
        raise AssertionError("write_to must stream the expression corpus")

    monkeypatch.setattr(
        bundle_module,
        "_canonical_jsonl_bytes",
        reject_materialization,
    )

    written = bundle.write_to(tmp_path)

    assert written["corpus/indexed-expressions.jsonl"].read_bytes()
    assert written["managed-release-bundle.json"].is_file()


def test_bundle_rejects_duplicate_records_and_stale_record_digests() -> None:
    """Pins refusal for a repeated record identifier and for a payload edited without resealing."""
    bundle = _bundle()

    with pytest.raises(
        ManagedVocabularyBundleError,
        match="repeats identifier",
    ):
        replace(
            bundle,
            ref_records=(bundle.ref_records[0], bundle.ref_records[0]),
        )

    stale = dict(bundle.ref_records[0])
    stale["marker"] = "changed without resealing"
    with pytest.raises(
        ManagedVocabularyBundleError,
        match="is stale",
    ):
        replace(bundle, ref_records=(stale,))


def test_managed_ref_record_artifact_path_matches_bundle_layout() -> None:
    """Pins that the helper's path is the one the bundle's artifact bytes use."""
    bundle = _bundle()

    assert managed_ref_record_artifact_path(
        bundle.ref_records[0]
    ) in bundle.artifact_bytes()


def test_reseal_linked_ref_records_propagates_digest_changes_in_dependency_order() -> None:
    """Pins that resealing updates dependent input digests in dependency order regardless of input order."""
    source = _record(
        "urn:ref:type:RunReceipt",
        "urn:test:record:source",
        "before",
    )
    middle = seal_payload(
        {
            "type": "urn:ref:type:RunReceipt",
            "id": "urn:test:record:middle",
            "version": "1.0",
            "input": {
                "id": source["id"],
                "digest": source["canonicalPayloadDigest"],
            },
        }
    )
    terminal = seal_payload(
        {
            "type": "urn:ref:type:RunReceipt",
            "id": "urn:test:record:terminal",
            "version": "1.0",
            "input": {
                "id": middle["id"],
                "digest": middle["canonicalPayloadDigest"],
            },
        }
    )
    source["marker"] = "after"

    resealed = reseal_linked_ref_records((terminal, source, middle))
    by_id = {record["id"]: record for record in resealed}

    assert by_id[middle["id"]]["input"]["digest"] == (
        by_id[source["id"]]["canonicalPayloadDigest"]
    )
    assert by_id[terminal["id"]]["input"]["digest"] == (
        by_id[middle["id"]]["canonicalPayloadDigest"]
    )
    assert all(
        record["canonicalPayloadDigest"]
        == binding.canonical_payload_digest(record)
        for record in resealed
    )


def test_reseal_linked_ref_records_rejects_digest_cycles() -> None:
    """Pins refusal when two records' input digests form a cycle."""
    first = _record(
        "urn:ref:type:RunReceipt",
        "urn:test:record:first",
        "first",
    )
    second = _record(
        "urn:ref:type:RunReceipt",
        "urn:test:record:second",
        "second",
    )
    first["input"] = {
        "id": second["id"],
        "digest": second["canonicalPayloadDigest"],
    }
    second["input"] = {
        "id": first["id"],
        "digest": first["canonicalPayloadDigest"],
    }

    with pytest.raises(
        ManagedVocabularyBundleError,
        match="digest cycle",
    ):
        reseal_linked_ref_records((first, second))
