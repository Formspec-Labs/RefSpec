"""Canonical Atlas 2.0 construction from one exact four-ring scope."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from rdflib import Dataset, Literal, URIRef

import refspec.atlas.model as atlas_model
from refspec.atlas.atlas_scope import (
    AtlasScopeRelease,
    PinnedVocabularyAtlasScope,
    VocabularyAtlasScope,
)
from refspec.atlas.model import (
    ATLAS,
    VocabularyAtlasAsset,
    VocabularyAtlasError,
    build_vocabulary_atlas,
)
from refspec.atlas.relation_assertion import (
    PinnedRelationAssertionBundle,
    RelationAssertionBundle,
)
from refspec.registry.infrastructure.artifact_serialization import sha256_digest
from refspec.registry.infrastructure.semantic_foundation import (
    VALUE_EXACT_CROSSWALK,
    EvidenceAssertion,
    MappingAssertion,
)
from refspec.registry.infrastructure.source_concept_release import (
    SourceConceptReleaseBundle,
    build_source_concept_release_bundle,
)
from refspec.registry.infrastructure.source_controlled_resource import (
    build_source_controlled_resource_bundle,
)
from refspec.registry.infrastructure.source_identity import derive_uuid7

_REPO_ROOT = Path(__file__).parents[1]
_SCOPE_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "refspec_test_vocabulary_atlas_model_scope_fixture",
    Path(__file__).with_name("test_atlas_scope.py"),
)
assert _SCOPE_FIXTURE_SPEC is not None and _SCOPE_FIXTURE_SPEC.loader is not None
_SCOPE_FIXTURE = importlib.util.module_from_spec(_SCOPE_FIXTURE_SPEC)
sys.modules[_SCOPE_FIXTURE_SPEC.name] = _SCOPE_FIXTURE
_SCOPE_FIXTURE_SPEC.loader.exec_module(_SCOPE_FIXTURE)

ASSERTED_AT = "2026-08-04T16:00:00Z"


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _pinned_scope(
    tmp_path: Path,
    *,
    name: str,
    releases: tuple[AtlasScopeRelease, ...],
    specs: tuple[Any, ...],
    relations: tuple[PinnedRelationAssertionBundle, ...] = (),
) -> tuple[PinnedVocabularyAtlasScope, dict[str, Any]]:
    index, raw_index, _ = _SCOPE_FIXTURE._pinned_index(tmp_path, name, specs)
    scope = VocabularyAtlasScope.create(
        scope_name=f"urn:ref:test:vocabulary-atlas-model:{name}",
        scope_kind="bench",
        atlas_index=index,
        releases=releases,
        relation_bundles=relations,
    )
    path = scope.write_to(tmp_path / f"{name}-atlas-scope.json")
    return (
        PinnedVocabularyAtlasScope.open(
            path,
            expected_file_digest=_file_digest(path),
            atlas_index=index,
            releases=releases,
            relation_bundles=relations,
        ),
        raw_index,
    )


def _records(
    asset: VocabularyAtlasAsset,
    *,
    role: str,
) -> tuple[tuple[URIRef, dict[str, Any], tuple[str, ...]], ...]:
    dataset = Dataset(default_union=False)
    dataset.parse(data=asset.payload.decode("utf-8"), format="nquads")
    graph_row = next(
        row
        for row in asset.manifest["graphs"]
        if row["role"] == ("releaseFacts" if role in {"conceptRelease", "concept", "releaseRecord"} else "crossRelease")
    )
    graph = dataset.graph(URIRef(cast(str, graph_row["id"])))
    result: list[tuple[URIRef, dict[str, Any], tuple[str, ...]]] = []
    for node in graph.subjects(ATLAS.recordRole, ATLAS[role]):
        literal = graph.value(node, ATLAS.canonicalJson)
        assert isinstance(node, URIRef)
        assert isinstance(literal, Literal)
        containers = tuple(
            sorted(
                str(value)
                for predicate in (ATLAS.inRelease, ATLAS.inRelationBundle)
                for value in graph.objects(node, predicate)
            )
        )
        result.append((node, json.loads(str(literal)), containers))
    return tuple(sorted(result, key=lambda value: str(value[0])))


def test_four_ring_scope_build_is_input_order_independent_and_resolves_index_facts(
    tmp_path: Path,
) -> None:
    values: list[AtlasScopeRelease] = []
    specs: list[Any] = []
    for ring in ("subject", "entity", "value", "legalIdentity"):
        _, source, _ = _SCOPE_FIXTURE._source_release(
            tmp_path,
            ring,
            ring=ring,
        )
        release = AtlasScopeRelease(source)
        values.append(release)
        specs.append(
            _SCOPE_FIXTURE._IndexSpec(
                release,
                ring,
                participation=("core" if ring == "subject" else None),
            )
        )
    releases = tuple(values)
    reverse_root = tmp_path / "reverse"
    forward_root = tmp_path / "forward"
    reverse_root.mkdir()
    forward_root.mkdir()
    pinned, raw_index = _pinned_scope(
        reverse_root,
        name="four-rings",
        releases=tuple(reversed(releases)),
        specs=tuple(specs),
    )
    forward_scope, _ = _pinned_scope(
        forward_root,
        name="four-rings",
        releases=releases,
        specs=tuple(specs),
    )

    reverse = build_vocabulary_atlas(pinned)
    forward = build_vocabulary_atlas(forward_scope)

    assert reverse.scope_payload == forward.scope_payload
    assert reverse.payload == forward.payload
    assert reverse.manifest == forward.manifest
    assert [row["semanticRing"] for row in reverse.manifest["rings"]] == [
        "subject",
        "entity",
        "value",
        "legalIdentity",
    ]
    assert [row["releaseCount"] for row in reverse.manifest["rings"]] == [1, 1, 1, 1]
    assert [row["conceptCount"] for row in reverse.manifest["rings"]] == [1, 1, 1, 1]
    assert reverse.manifest["counts"]["conceptReleases"] == 4
    assert reverse.manifest["counts"]["concepts"] == 4
    assert reverse.manifest["implementation"] == forward.manifest["implementation"]

    published_rows = {
        row["rowId"]: (row, containers)
        for _, row, containers in _records(reverse, role="releaseRecord")
        if "rowId" in row
    }
    expected_rows = {row["rowId"]: row for row in raw_index["rows"]}
    assert {identifier: row for identifier, (row, _) in published_rows.items()} == expected_rows
    assert all(len(containers) == 1 for _, containers in published_rows.values())


def _source_release_version(
    tmp_path: Path,
    *,
    version: str,
    label: str,
) -> SourceConceptReleaseBundle:
    source_id = "https://publisher.example/shared-concept.json"
    scheme_id = "https://publisher.example/schemes/shared"
    local_record_id = "urn:uuid:" + derive_uuid7(
        ASSERTED_AT,
        seed=b"atlas-model-shared-concept",
    )
    observation = {
        "id": f"urn:ref:test:atlas-model:observation:{version}",
        "sourceArtifact": source_id,
        "sourcePath": "terms/shared",
        "sourceOrdinal": 0,
        "labels": [{"value": label, "language": "en", "role": "preferred"}],
        "identifiers": [],
        "uses": ["mappingReference"],
        "conceptIdentityClaimed": False,
        "localRecordId": local_record_id,
    }
    payload = f'{{"label":"{label}","version":"{version}"}}\n'.encode()
    capture = build_source_controlled_resource_bundle(
        resource_id=f"atlas-model-shared-{version}",
        title=f"Shared concept {version}",
        resource_kind="sourceTermSnapshot",
        identity_status="captureLocalObservationsOnly",
        uses=("mappingReference",),
        captured_at=ASSERTED_AT,
        observations=(observation,),
        source_artifacts={source_id: payload},
        source_scheme={
            "id": scheme_id,
            "code": "shared",
            "label": "Shared scheme",
            "sourceArtifact": source_id,
            "sourceFetchId": derive_uuid7(
                ASSERTED_AT,
                seed=f"atlas-model-shared-fetch:{version}".encode(),
            ),
            "sourceObservedAt": ASSERTED_AT,
        },
    )
    return build_source_concept_release_bundle(
        capture,
        semantic_ring="subject",
        selected_observation_ids=(observation["id"],),
        selection_policy={
            "id": f"urn:ref:test:atlas-model:selection:{version}",
            "type": "explicitObservationSet",
        },
        rights_metadata=(
            {
                "type": "RightsMetadata",
                "rightsStatus": "notStated",
                "sourceArtifact": source_id,
                "sourceDigest": sha256_digest(payload),
            },
        ),
    )


def test_stable_concept_identity_keeps_distinct_release_scoped_records(
    tmp_path: Path,
) -> None:
    releases: list[AtlasScopeRelease] = []
    concept_ids: list[str] = []
    for version, label in (("v1", "Shared label"), ("v2", "Renamed label")):
        bundle = _source_release_version(tmp_path, version=version, label=label)
        root = bundle.write_to(tmp_path / f"shared-{version}")
        source = _SCOPE_FIXTURE.PinnedSourceConceptRelease.open(
            root,
            expected_manifest_digest=bundle.manifest_digest,
        )
        releases.append(AtlasScopeRelease(source))
        concept_ids.append(cast(str, bundle.concepts[0]["id"]))
    assert concept_ids[0] == concept_ids[1]
    pinned, _ = _pinned_scope(
        tmp_path,
        name="shared-identity",
        releases=tuple(releases),
        specs=tuple(_SCOPE_FIXTURE._IndexSpec(release, f"shared-{index}") for index, release in enumerate(releases)),
    )

    asset = build_vocabulary_atlas(pinned)
    records = _records(asset, role="concept")

    assert len(records) == 2
    assert len({str(node) for node, _, _ in records}) == 2
    assert {row["id"] for _, row, _ in records} == {concept_ids[0]}
    assert {row["sourceObservation"] for _, row, _ in records} == {
        "urn:ref:test:atlas-model:observation:v1",
        "urn:ref:test:atlas-model:observation:v2",
    }
    assert all(len(containers) == 1 for _, _, containers in records)


def test_managed_jsonld_member_identity_is_indexed_from_at_id(
    tmp_path: Path,
) -> None:
    source, _ = _SCOPE_FIXTURE._managed_release(tmp_path)
    release = AtlasScopeRelease(source)
    pinned, _ = _pinned_scope(
        tmp_path,
        name="managed-at-id",
        releases=(release,),
        specs=(
            _SCOPE_FIXTURE._IndexSpec(
                release,
                "managed-at-id",
                participation="specialist",
            ),
        ),
    )

    asset = build_vocabulary_atlas(pinned)
    members = _records(asset, role="concept")
    release_rows = _records(asset, role="releaseRecord")
    snapshot_reference = _records(asset, role="conceptRelease")[0][1]
    decoded = atlas_model._decode_record_dataset(
        asset.payload,
        asset_id=cast(str, asset.manifest["id"]),
    )
    snapshot = atlas_model._snapshots_from_records(decoded)[0].as_record()
    text = asset.payload.decode("utf-8")

    assert members
    assert snapshot_reference["type"] == (
        "ManagedAtlasReleaseSnapshotReference"
    )
    assert "selectedReleaseGraph" not in snapshot_reference
    assert '"selectedReleaseGraph"' not in text
    assert "members" not in snapshot
    assert snapshot["memberIds"] == sorted(snapshot["memberIds"])
    assert all("@graph" not in row for _, row, _ in release_rows)
    native_ids = {row["@id"] for row in snapshot["selectedReleaseGraph"]["@graph"]}
    stored_native_ids = [row["@id"] for _, row, _ in (*members, *release_rows) if "@id" in row]
    assert set(stored_native_ids) == native_ids
    assert len(stored_native_ids) == len(set(stored_native_ids))
    assert {
        row["recordId"] for row in snapshot_reference["selectedGraphRecords"]
    } == {
        str(node) for node, row, _ in (*members, *release_rows) if "@id" in row
    }
    for _, member, _ in members:
        member_id = member["@id"]
        assert f"{ATLAS.recordId.n3()} <{member_id}>" in text

    output = asset.write(tmp_path / "managed-reference-atlas")
    reopened = VocabularyAtlasAsset.open(
        output,
        expected_manifest_digest=asset.manifest_digest,
    )
    assert reopened.payload == asset.payload


def test_value_relation_context_round_trips_and_distribution_reproduces(
    tmp_path: Path,
) -> None:
    _, source, source_concept = _SCOPE_FIXTURE._source_release(
        tmp_path,
        "value-source",
        ring="value",
    )
    _, target, target_concept = _SCOPE_FIXTURE._source_release(
        tmp_path,
        "value-target",
        ring="value",
    )
    source_release = AtlasScopeRelease(source)
    target_release = AtlasScopeRelease(target)
    evidence = EvidenceAssertion(
        semantic_ring="value",
        evidence_class="humanReviewed",
        basis="editorialReview",
        asserted_by="https://refspec.org/actors/value-reviewer",
        asserted_at=ASSERTED_AT,
        evidence=("urn:ref:test:atlas-model:value-evidence",),
        review_decision="urn:ref:test:atlas-model:value-review",
    )
    context = {
        "sourceEdition": "2025",
        "targetEdition": "2026",
        "effectiveFrom": "2026-01-01",
        "effectiveThrough": "2026-12-31",
    }
    mapping = MappingAssertion(
        semantic_ring="value",
        source_concept=source_concept,
        target_concept=target_concept,
        source_release=source.release_id,
        target_release=target.release_id,
        relation=VALUE_EXACT_CROSSWALK,
        evidence=(evidence.identifier,),
        asserted_at=ASSERTED_AT,
        context=context,
    )
    bundle = RelationAssertionBundle.create(
        semantic_ring="value",
        release_sources=(source, target),
        evidence_assertions=(evidence,),
        mapping_assertions=(mapping,),
    )
    relation_root = bundle.write_to(tmp_path / "value-relation")
    relation = PinnedRelationAssertionBundle.open(
        relation_root,
        expected_manifest_digest=bundle.manifest_digest,
        release_sources=(source, target),
    )
    pinned, _ = _pinned_scope(
        tmp_path,
        name="value-relation",
        releases=(source_release, target_release),
        specs=(
            _SCOPE_FIXTURE._IndexSpec(source_release, "value-source"),
            _SCOPE_FIXTURE._IndexSpec(target_release, "value-target"),
        ),
        relations=(relation,),
    )

    asset = build_vocabulary_atlas(pinned)
    assert [row for _, row, _ in _records(asset, role="mappingAssertion")] == [mapping.as_record()]
    assert asset.manifest["counts"]["relationBundles"] == 1
    assert asset.manifest["counts"]["evidenceAssertions"] == 1
    assert asset.manifest["counts"]["mappingAssertions"] == 1

    schema = json.loads(
        (_REPO_ROOT / "bindings/atlas/2.0/schemas/vocabulary-atlas-manifest.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(cast(dict[str, Any], json.loads(asset.manifest_bytes())))
    directory = asset.write(tmp_path / "value-atlas")
    reopened = VocabularyAtlasAsset.open(
        directory,
        expected_manifest_digest=asset.manifest_digest,
    )
    reproduced = VocabularyAtlasAsset.reproduce_from_scope(
        directory,
        scope=pinned,
        expected_manifest_digest=asset.manifest_digest,
    )
    assert reopened.payload == reproduced.payload == asset.payload
    assert reopened.scope_payload == reproduced.scope_payload == asset.scope_payload


def test_three_file_distribution_fails_closed_on_output_scope_and_file_set_tampering(
    tmp_path: Path,
) -> None:
    _, source, _ = _SCOPE_FIXTURE._source_release(tmp_path, "tamper")
    release = AtlasScopeRelease(source)
    pinned, _ = _pinned_scope(
        tmp_path,
        name="tamper",
        releases=(release,),
        specs=(_SCOPE_FIXTURE._IndexSpec(release, "tamper"),),
    )
    asset = build_vocabulary_atlas(pinned)
    directory = asset.write(tmp_path / "tamper-atlas")
    assert {path.name for path in directory.iterdir()} == {
        "atlas-manifest.json",
        "atlas-scope.json",
        "atlas.nq",
    }

    atlas_path = directory / "atlas.nq"
    atlas_path.write_bytes(asset.payload + b"\n")
    with pytest.raises(VocabularyAtlasError, match="output digest differs"):
        VocabularyAtlasAsset.open(
            directory,
            expected_manifest_digest=asset.manifest_digest,
        )
    atlas_path.write_bytes(asset.payload)

    scope_path = directory / "atlas-scope.json"
    scope_path.write_bytes(asset.scope_payload + b" ")
    with pytest.raises(VocabularyAtlasError, match="scope file digest differs"):
        VocabularyAtlasAsset.open(
            directory,
            expected_manifest_digest=asset.manifest_digest,
        )
    scope_path.write_bytes(asset.scope_payload)

    (directory / "extra.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(VocabularyAtlasError, match="file set differs"):
        VocabularyAtlasAsset.open(
            directory,
            expected_manifest_digest=asset.manifest_digest,
        )


def test_asset_open_uses_one_closed_decode_without_rdflib_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, source, _ = _SCOPE_FIXTURE._source_release(tmp_path, "decode-once")
    release = AtlasScopeRelease(source)
    pinned, _ = _pinned_scope(
        tmp_path,
        name="decode-once",
        releases=(release,),
        specs=(_SCOPE_FIXTURE._IndexSpec(release, "decode-once"),),
    )
    asset = build_vocabulary_atlas(pinned)
    directory = asset.write(tmp_path / "decode-once-atlas")

    calls = {"decode": 0}
    original_decode = atlas_model._decode_atlas_dataset

    def counted_decode(payload: bytes, *, asset_id: str):
        calls["decode"] += 1
        return original_decode(payload, asset_id=asset_id)

    def unexpected_rdflib_path(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("closed Atlas decode must not invoke rdflib parsing or canonicalization")

    monkeypatch.setattr(atlas_model, "_decode_atlas_dataset", counted_decode)
    monkeypatch.setattr(Dataset, "parse", unexpected_rdflib_path)
    monkeypatch.setattr(atlas_model, "_canonical_nquads", unexpected_rdflib_path)

    VocabularyAtlasAsset.open(
        directory,
        expected_manifest_digest=asset.manifest_digest,
    )

    assert calls == {"decode": 1}


def test_closed_nquads_decode_matches_rdflib_for_generated_unicode() -> None:
    records = atlas_model._CanonicalRecordSet()
    release_id = "https://example.test/releases/référence"
    concept_id = "https://example.test/concepts/社会"
    release_record = {
        "id": release_id,
        "title": 'Référence "sociale" \\ ligne\nsuivante',
    }
    concept_record = {
        "id": concept_id,
        "skos:prefLabel": {"@language": "fr", "@value": "Société ☃"},
    }
    records.add(release_record, role="conceptRelease")
    records.add(concept_record, role="concept", in_release=release_id)
    asset_id = "urn:ref:test:closed-nquads-unicode"
    payload, expected_counts = atlas_model._record_dataset(
        records.values(),
        asset_id=asset_id,
    )

    decoded = atlas_model._decode_atlas_dataset(payload, asset_id=asset_id)
    reference = Dataset(default_union=False)
    reference.parse(data=payload.decode("utf-8"), format="nquads")

    assert decoded.quad_count == sum(1 for _ in reference.quads((None, None, None, None)))
    assert decoded.graph_quad_count(asset_id + ":release-facts") == expected_counts["releaseFacts"]
    assert decoded.graph_quad_count(asset_id + ":cross-release") == expected_counts["crossRelease"]
    assert [record.record for record in decoded.records] == [record.record for record in records.values()]


def test_closed_nquads_decode_normalizes_one_shared_record_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record_id = "urn:ref:test:shared-large-record"
    release_ids = tuple(
        f"urn:ref:test:shared-large-record:release:{index:03d}"
        for index in range(128)
    )
    record_value = {
        "id": record_id,
        "label": "shared across many release containers",
        "payload": "x" * 256_000,
    }
    source_record = atlas_model._CanonicalAtlasRecord(
        record=cast(
            Any,
            atlas_model._freeze(atlas_model._plain(record_value)),
        ),
        role="concept",
        release_containers=frozenset(release_ids),
    )
    asset_id = "urn:ref:test:shared-large-record-atlas"
    payload, _ = atlas_model._record_dataset(
        (source_record,),
        asset_id=asset_id,
    )

    calls = {"normalize": 0, "hash": 0, "freeze": 0}
    original_plain = atlas_model._plain
    original_digest = atlas_model._digest_bytes
    original_freeze = atlas_model._freeze

    def counted_plain(value: Any) -> Any:
        if isinstance(value, dict) and value.get("id") == record_id:
            calls["normalize"] += 1
        return original_plain(value)

    def counted_digest(value: bytes) -> str:
        calls["hash"] += 1
        return original_digest(value)

    def counted_freeze(value: Any) -> Any:
        if isinstance(value, dict) and value.get("id") == record_id:
            calls["freeze"] += 1
        return original_freeze(value)

    monkeypatch.setattr(atlas_model, "_plain", counted_plain)
    monkeypatch.setattr(atlas_model, "_digest_bytes", counted_digest)
    monkeypatch.setattr(atlas_model, "_freeze", counted_freeze)

    decoded = atlas_model._decode_atlas_dataset(payload, asset_id=asset_id)

    assert len(decoded.records) == 1
    assert decoded.records[0].record == source_record.record
    assert decoded.records[0].release_containers == frozenset(release_ids)
    assert decoded.records[0].relation_containers == frozenset()
    assert calls == {"normalize": 1, "hash": 1, "freeze": 1}


def test_decoded_record_bulk_insertion_preserves_exact_merge_rules() -> None:
    record_value = {
        "id": "urn:ref:test:decoded-bulk-merge",
        "label": "one canonical record",
    }
    record_bytes = atlas_model._atlas_record_bytes(record_value)
    verified = atlas_model._parse_canonical_record(
        record_bytes.decode("utf-8"),
        expected_digest=atlas_model._digest_bytes(record_bytes),
    )
    release_ids = tuple(
        f"urn:ref:test:decoded-bulk-merge:release:{index}"
        for index in range(3)
    )
    records = atlas_model._CanonicalRecordSet()

    records.add_decoded(
        verified,
        role="concept",
        releases=release_ids[:2],
    )
    records.add_decoded(
        verified,
        role="concept",
        releases=release_ids[1:],
    )

    assert len(records.values()) == 1
    assert records.values()[0].release_containers == frozenset(release_ids)
    with pytest.raises(VocabularyAtlasError, match="conflicting content or roles"):
        records.add_decoded(
            verified,
            role="releaseRecord",
            releases=release_ids[:1],
        )
    with pytest.raises(VocabularyAtlasError, match="cannot cross container kinds"):
        records.add_decoded(
            verified,
            role="concept",
            releases=release_ids[:1],
            relation_bundles=("urn:ref:test:decoded-bulk-merge:bundle",),
        )


def test_closed_nquads_decode_rejects_non_generated_shapes_without_rdflib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = atlas_model._CanonicalRecordSet()
    records.add(
        {"id": "urn:ref:test:closed-parser", "label": "Canonical"},
        role="conceptRelease",
    )
    asset_id = "urn:ref:test:closed-parser-atlas"
    payload, _ = atlas_model._record_dataset(records.values(), asset_id=asset_id)
    lines = payload.splitlines()

    def line_index(predicate: bytes) -> int:
        return next(index for index, line in enumerate(lines) if predicate in line)

    digest_index = line_index(b"#recordDigest>")
    digest_line = lines[digest_index]
    canonical_index = line_index(b"#canonicalJson>")
    canonical_line = lines[canonical_index]
    first_line = lines[0]
    subject_end = first_line.index(b"> ")

    language_lines = list(lines)
    language_lines[digest_index] = digest_line.replace(b'" <', b'"@en <', 1)
    datatype_lines = list(lines)
    datatype_lines[digest_index] = digest_line.replace(b'" <', b'"^^<urn:test:type> <', 1)
    graph_lines = [
        line.replace(b"<urn:ref:test:closed-parser-atlas:release-facts> .", b"<urn:test:other> .") for line in lines
    ]
    blank_node_lines = list(lines)
    blank_node_lines[0] = b"_:record" + first_line[subject_end + 1 :]
    extra_predicate_lines = list(lines)
    predicate_start = first_line.index(b" <") + 1
    predicate_end = first_line.index(b"> ", predicate_start) + 1
    extra_predicate_lines[0] = first_line[:predicate_start] + b"<urn:test:extraPredicate>" + first_line[predicate_end:]
    literal_start = canonical_line.index(b'> "') + 3
    noncanonical_literal_lines = list(lines)
    noncanonical_literal_lines[canonical_index] = (
        canonical_line[:literal_start] + b"\\u007b" + canonical_line[literal_start + 1 :]
    )

    def canonical_payload(values: list[bytes]) -> bytes:
        return b"\n".join(sorted(values)) + b"\n"

    corruptions = (
        (canonical_payload(language_lines), "recordDigest literal"),
        (canonical_payload(datatype_lines), "recordDigest literal"),
        (canonical_payload(graph_lines), "named graphs differ"),
        (canonical_payload(blank_node_lines), "subject"),
        (canonical_payload(extra_predicate_lines), "extra predicate"),
        (canonical_payload(noncanonical_literal_lines), "literal is not canonical"),
        (b"\n".join((*lines, lines[-1])) + b"\n", "not unique and ordered"),
        (b"\n".join((lines[1], lines[0], *lines[2:])) + b"\n", "not unique and ordered"),
    )

    def unexpected_rdflib_path(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("closed Atlas decode must reject corruption without rdflib")

    monkeypatch.setattr(Dataset, "parse", unexpected_rdflib_path)
    monkeypatch.setattr(atlas_model, "_canonical_nquads", unexpected_rdflib_path)

    for corrupted, message in corruptions:
        with pytest.raises(VocabularyAtlasError, match=message):
            atlas_model._decode_atlas_dataset(corrupted, asset_id=asset_id)


def test_closed_nquads_long_line_has_bounded_linear_failure_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = atlas_model._CanonicalRecordSet()
    records.add(
        {"id": "urn:ref:test:long-record", "value": "λ" * 1_000_000},
        role="conceptRelease",
    )
    asset_id = "urn:ref:test:long-record-atlas"
    payload, _ = atlas_model._record_dataset(records.values(), asset_id=asset_id)
    datatype_marker = atlas_model._RDF_JSON_DATATYPE_TOKEN
    marker_position = payload.index(datatype_marker)
    malformed = payload[: marker_position - 1] + b"\\" + payload[marker_position - 1 :]
    original_canonical_nquads = atlas_model._canonical_nquads

    def unexpected_rdflib_path(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("long-line validation must not fall back to rdflib")

    monkeypatch.setattr(Dataset, "parse", unexpected_rdflib_path)
    monkeypatch.setattr(atlas_model, "_canonical_nquads", unexpected_rdflib_path)

    with pytest.raises(VocabularyAtlasError, match="canonicalJson literal is invalid"):
        atlas_model._decode_atlas_dataset(malformed, asset_id=asset_id)

    original_max_bytes = atlas_model._MAX_ATLAS_NQUADS_BYTES
    monkeypatch.setattr(atlas_model, "_MAX_ATLAS_NQUADS_BYTES", len(payload) - 1)
    with pytest.raises(VocabularyAtlasError, match="exceeds the verifier byte limit"):
        atlas_model._decode_atlas_dataset(payload, asset_id=asset_id)
    monkeypatch.setattr(atlas_model, "_MAX_ATLAS_NQUADS_BYTES", original_max_bytes)

    longest_line = max(len(line) for line in payload.splitlines())
    monkeypatch.setattr(atlas_model, "_MAX_ATLAS_NQUAD_LINE_BYTES", longest_line - 1)
    with pytest.raises(VocabularyAtlasError, match="line exceeds the verifier byte limit"):
        atlas_model._decode_atlas_dataset(payload, asset_id=asset_id)
    monkeypatch.setattr(atlas_model, "_canonical_nquads", original_canonical_nquads)
    with pytest.raises(VocabularyAtlasError, match="line exceeds the verifier byte limit"):
        atlas_model._record_dataset(records.values(), asset_id=asset_id)


def test_public_builder_rejects_loose_release_inputs(tmp_path: Path) -> None:
    _, source, _ = _SCOPE_FIXTURE._source_release(tmp_path, "loose")

    with pytest.raises(VocabularyAtlasError, match="PinnedVocabularyAtlasScope"):
        build_vocabulary_atlas(cast(Any, (source,)))
    with pytest.raises(TypeError):
        build_vocabulary_atlas(  # type: ignore[call-arg]
            cast(Any, (source,)),
            rulespec_core=object(),
        )
