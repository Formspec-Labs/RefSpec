from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from refspec.atlas.v3_source_data import (
    RegistryInputPin,
    RegistryLabel,
    RegistryRelease,
    RegistryResource,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
generator = importlib.import_module("generate_atlas_v3_full")


def _compiled_test_report(
    graphs: generator.BuildGraphs,
) -> dict[str, object]:
    if isinstance(graphs.asserted, generator._MutationTrackedGraph):
        graphs.sealed_asserted_revision = graphs.asserted.revision
    return {
        "bindingProfile": dict(generator._COMPILED_PRODUCER_BINDING_PINS),
        "checks": ["unit-test compiled producer proof"],
        "constructorProfile": generator._COMPILED_PRODUCER_PROFILE,
        "counts": generator._counts(graphs),
        "mode": "compiledSourceProducerValidation",
        "shaclDataProof": "compiledAgainstPinnedOntologyAndShapes",
        "shaclMetaValidation": "pySHACL",
        "sourceAccountingDigest": generator._canonical_digest(graphs.accounting),
        "sourceReleaseCount": generator._counts(graphs)["releases"],
        "status": "passed",
    }


def _compiled_test_accounting() -> dict[str, object]:
    return {
        "distributionId": generator.DISTRIBUTION_ID,
        "inputs": [
            {
                "declaredMemberCount": 0,
                "dispositions": [],
                "membershipMode": "complete",
                "sourceRelease": "urn:test:source-release",
            }
        ],
        "totals": {
            "excluded": 0,
            "represented": 0,
            "sourceRecords": 0,
            "sourceReleases": 1,
            "unresolved": 0,
        },
        "type": "AtlasSourceAccounting",
        "version": "3.0",
    }


def test_release_pack_paths_are_readable_safe_and_deterministic() -> None:
    release = generator.ReleasePackPlan(
        key="gemet-4.2.3",
        source_release_iri="urn:test:source-release:gemet",
        atlas_release_iri="urn:test:atlas-release:gemet",
        ring="subject",
        resource_count=1,
    )

    assert generator._release_pack_token(release) == "gemet-4-2-3"


def test_release_pack_path_collisions_fail_before_graph_construction() -> None:
    first = SimpleNamespace(
        spec=SimpleNamespace(key="gemet-4.2", ring="subject"),
        source_release_iri="urn:test:source-release:one",
        atlas_release_iri="urn:test:atlas-release:one",
        resources=(object(),),
    )
    second = SimpleNamespace(
        spec=SimpleNamespace(key="gemet-4-2", ring="subject"),
        source_release_iri="urn:test:source-release:two",
        atlas_release_iri="urn:test:atlas-release:two",
        resources=(object(),),
    )

    with pytest.raises(ValueError, match="collide after safe pack-path"):
        generator._release_pack_plans((first, second))


def test_same_release_cross_partition_reference_pins_target_pack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = generator.ReleasePackPlan(
        key="same-release",
        source_release_iri="urn:test:source-release:same",
        atlas_release_iri="urn:test:atlas-release:0",
        ring="subject",
        resource_count=generator._PACK_LARGE_RELEASE_RESOURCE_THRESHOLD,
    )
    source = URIRef("urn:test:resource:1")
    target = URIRef("urn:test:resource:2")
    source_partition = generator._release_pack_partition(release, source)
    target_partition = generator._release_pack_partition(release, target)
    assert source_partition is not None
    assert target_partition is not None
    assert source_partition != target_partition

    asserted = generator._new_build_graph()
    asserted.add(
        (
            URIRef("urn:test:catalog"),
            RDF.type,
            generator.ATLAS.RegistrySource,
        )
    )
    asserted.add(
        (
            URIRef(release.atlas_release_iri),
            RDF.type,
            generator.ATLAS.AtlasRelease,
        )
    )
    for resource in (source, target):
        asserted.add((resource, RDF.type, generator.ATLAS.AtlasResource))
        asserted.add(
            (
                resource,
                generator.ATLAS.inRelease,
                URIRef(release.atlas_release_iri),
            )
        )
    asserted.add((source, URIRef("urn:test:relation"), target))

    original_partition = generator._release_pack_partition
    partition_calls: dict[URIRef, int] = {}

    def counted_partition(
        release_plan: generator.ReleasePackPlan,
        subject: URIRef,
    ) -> str | None:
        partition_calls[subject] = partition_calls.get(subject, 0) + 1
        return original_partition(release_plan, subject)

    monkeypatch.setattr(
        generator,
        "_release_pack_partition",
        counted_partition,
    )
    packs = generator._write_asserted_packs(tmp_path, asserted, (release,))
    release_packs = [pack for pack in packs if pack["kind"] == "sourceRelease"]
    source_pack = next(
        pack
        for pack in packs
        if pack.get("partition", {}).get("prefix") == source_partition
    )
    target_pack = next(
        pack
        for pack in packs
        if pack.get("partition", {}).get("prefix") == target_partition
    )

    assert len(release_packs) == 2
    assert source_pack["sourceReleases"] == [release.source_release_iri]
    assert target_pack["sourceReleases"] == [release.source_release_iri]
    assert target_pack["packId"] in source_pack["dependencies"]
    assert source_pack["packId"] not in source_pack["dependencies"]
    assert all((tmp_path / pack["path"]).is_file() for pack in packs)
    assert partition_calls[source] == 1


def test_candidate_binds_compiled_proof_before_releasing_graphs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    graphs = generator.BuildGraphs(
        asserted=generator._new_build_graph(),
        projection=generator._new_build_graph(),
        derived=generator._new_build_graph(),
        accounting=_compiled_test_accounting(),
    )
    graphs.asserted.add(
        (
            URIRef("urn:test:release"),
            RDF.type,
            generator.ATLAS.AtlasRelease,
        )
    )

    events: list[str] = []

    compiled_validation = _compiled_test_report(graphs)
    original_check = generator._check_compiled_validation_report

    def checked(*args, **kwargs) -> None:
        events.append("compiled")
        original_check(*args, **kwargs)

    monkeypatch.setattr(generator, "_check_compiled_validation_report", checked)
    monkeypatch.setattr(
        generator.ATLAS_VALIDATE,
        "validate_preparsed_distribution",
        lambda *args, **kwargs: pytest.fail(
            "trusted producer must not run resident-graph RDF validation"
        ),
    )

    result, manifest = generator._write_candidate_distribution(
        tmp_path,
        graphs,
        compiled_validation=compiled_validation,
    )

    assert events == ["compiled"]
    assert not graphs.asserted
    assert not graphs.projection
    assert not graphs.derived
    assert graphs.accounting == {}
    assert result["compiledProducerValidation"]["type"] == (
        "AtlasProducerValidation"
    )
    assert result["compiledProducerValidation"]["binding"] == manifest["binding"]
    assert result["compiledProducerValidation"]["implementationDigest"] == (
        generator._COMPILED_PRODUCER_IMPLEMENTATION_DIGEST
    )
    assert result["trustedWriterReceiptChecks"]["mode"] == "trustedWriterReceipts"
    assert result["independentFileConsumerValidation"] == {
        "performedByGenerator": False,
        "requiredForIndependentConsumers": True,
        "validator": "bindings/atlas/3.0/tools/validate.py:validate_distribution",
    }


def test_pack_write_receipt_matches_both_exact_byte_forms(tmp_path: Path) -> None:
    content = (
        b"<urn:test:a> <urn:test:p> <urn:test:o> <urn:test:graph> .\n"
        b"<urn:test:b> <urn:test:p> <urn:test:o> <urn:test:graph> .\n"
    )
    source = tmp_path / "source.nq"
    target = tmp_path / "pack.nq.zst"
    source.write_bytes(content)

    receipt = generator._compress_nquads(source, target)

    with generator.zstd.open(target, "rb") as stream:
        assert stream.read() == content
    stored = target.read_bytes()
    assert receipt == generator.PackWriteReceipt(
        content_byte_length=len(content),
        content_digest="sha256:" + hashlib.sha256(content).hexdigest(),
        content_quad_count=2,
        transport_byte_length=len(stored),
        transport_digest="sha256:" + hashlib.sha256(stored).hexdigest(),
    )


def _write_receipted_test_candidate(tmp_path: Path, monkeypatch) -> dict:
    asserted = generator._new_build_graph()
    asserted.add(
        (
            URIRef("urn:test:subject"),
            URIRef("urn:test:predicate"),
            URIRef("urn:test:object"),
        )
    )
    asserted.add(
        (
            URIRef("urn:test:release"),
            RDF.type,
            generator.ATLAS.AtlasRelease,
        )
    )
    graphs = generator.BuildGraphs(
        asserted=asserted,
        projection=generator._new_build_graph(),
        derived=generator._new_build_graph(),
        accounting=_compiled_test_accounting(),
    )
    _, manifest = generator._write_candidate_distribution(
        tmp_path,
        graphs,
        compiled_validation=_compiled_test_report(graphs),
    )
    return manifest


def test_trusted_writer_receipts_reject_same_size_stored_pack_tampering(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest = _write_receipted_test_candidate(tmp_path, monkeypatch)
    pack_path = tmp_path / manifest["packs"][0]["path"]
    payload = bytearray(pack_path.read_bytes())
    payload[len(payload) // 2] ^= 1
    pack_path.write_bytes(payload)

    with pytest.raises(ValueError, match="stored pack transport differs"):
        generator._trusted_writer_receipt_checks(tmp_path, manifest=manifest)


@pytest.mark.parametrize(
    ("mismatch", "message"),
    (
        ("contentQuadCount", "graph counts differ from content quadCount"),
        ("graphQuadCount", "asserted graph quadCount differs"),
        ("graphPackCount", "asserted graph packCount differs"),
        ("graphInventoryDigest", "asserted graph inventoryDigest differs"),
    ),
)
def test_trusted_writer_receipts_reject_manifest_inventory_mismatches(
    tmp_path: Path,
    monkeypatch,
    mismatch: str,
    message: str,
) -> None:
    manifest = _write_receipted_test_candidate(tmp_path, monkeypatch)
    if mismatch == "contentQuadCount":
        manifest["packs"][0]["content"]["quadCount"] += 1
    elif mismatch == "graphQuadCount":
        manifest["graphs"][0]["quadCount"] += 1
    elif mismatch == "graphPackCount":
        manifest["graphs"][0]["packCount"] += 1
    else:
        manifest["graphs"][0]["inventoryDigest"] = "sha256:" + "0" * 64

    with pytest.raises(ValueError, match=message):
        generator._trusted_writer_receipt_checks(tmp_path, manifest=manifest)


def test_fixed_distribution_inputs_are_externally_pinned_and_logical() -> None:
    inventory = generator.verify_inputs()

    assert set(inventory) == {
        "expectedResources",
        "registryDescriptors",
        "registryDescriptorsPin",
        "sources",
    }
    assert all(not row["path"].startswith("/") for row in inventory["sources"])
    assert all(row["usesPriorAtlasGraph"] is False for row in inventory["sources"])
    assert all(None not in row.values() for row in inventory["sources"])
    assert "mapping-evidence" not in json.dumps(inventory, sort_keys=True)
    assert not hasattr(generator, "PROOF_BUNDLES")
    assert not hasattr(generator, "load_proof_bundles")


def test_v3_fallback_identity_is_readable_deterministic_and_source_preserving() -> None:
    local_record_id = "urn:uuid:019fc9f2-c758-7134-9432-2a0de8fde1dd"
    source_scheme = "http://id.loc.gov/vocabulary/subjectSchemes/lst"
    prior_iri = (
        "urn:ref:source-concept:v1:"
        "6db43bea6ad5f32b25d57b4cd182d1b3b7f5de9a29a727b65fc17954cec97f01:"
        "019fc9f2-c758-7134-9432-2a0de8fde1dd"
    )

    iri, source_identity = generator._v3_fallback_source_identity(
        namespace_token="loc-lst",
        prior_iri=prior_iri,
        identity_kind="refspecSourceScoped",
        local_record_id=local_record_id,
        source_scheme=source_scheme,
    )

    assert iri == (
        "urn:ref:source-concept:v2:loc-lst:"
        "019fc9f2-c758-7134-9432-2a0de8fde1dd"
    )
    assert source_identity == {
        "identityKind": "refspecSourceScoped",
        "localRecordId": local_record_id,
        "namespaceToken": "loc-lst",
        "priorSourceConceptIri": prior_iri,
        "sourceScheme": source_scheme,
    }


@pytest.mark.parametrize(
    "overrides, message",
    (
        ({"namespace_token": None}, "fallback namespace token"),
        ({"namespace_token": "LOC_LST"}, "fallback namespace token"),
        (
            {"identity_kind": "publisherConceptIri"},
            "only refspecSourceScoped",
        ),
        ({"local_record_id": "urn:uuid:not-a-uuid"}, "UUID"),
        ({"source_scheme": "not-an-iri"}, "absolute IRI"),
        (
            {"namespace_token": "loc-cgpa"},
            "does not identify the exact sourceScheme",
        ),
        ({"prior_iri": "urn:test:wrong"}, "prior source concept IRI"),
    ),
)
def test_v3_fallback_identity_fails_closed(
    overrides: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "namespace_token": "loc-lst",
        "prior_iri": (
            "urn:ref:source-concept:v1:"
            "6db43bea6ad5f32b25d57b4cd182d1b3b7f5de9a29a727b65fc17954cec97f01:"
            "019fc9f2-c758-7134-9432-2a0de8fde1dd"
        ),
        "identity_kind": "refspecSourceScoped",
        "local_record_id": (
            "urn:uuid:019fc9f2-c758-7134-9432-2a0de8fde1dd"
        ),
        "source_scheme": "http://id.loc.gov/vocabulary/subjectSchemes/lst",
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        generator._v3_fallback_source_identity(**values)


def test_v3_fallback_identity_rejects_non_string_local_id() -> None:
    with pytest.raises(TypeError, match="localRecordId"):
        generator._v3_fallback_source_identity(
            namespace_token="loc-lst",
            prior_iri="urn:test:prior",
            identity_kind="refspecSourceScoped",
            local_record_id=7,
            source_scheme="http://id.loc.gov/vocabulary/subjectSchemes/lst",
        )


def _source_spec(key: str):
    return next(spec for spec in generator.SOURCE_SPECS if spec.key == key)


@pytest.mark.parametrize(
    ("role", "predicate"),
    (
        ("preferred", generator.SKOSXL.prefLabel),
        ("alternate", generator.SKOSXL.altLabel),
        ("hidden", generator.SKOSXL.hiddenLabel),
    ),
)
def test_source_label_roles_map_to_skosxl(role: str, predicate: URIRef) -> None:
    label = generator.SourceLabel(
        value="Label",
        language="en",
        role=role,
        source_path="source#label",
    )

    assert label.role == role
    assert generator._source_label_predicate(role) == predicate


def test_source_label_roles_fail_closed() -> None:
    with pytest.raises(ValueError, match="unsupported source label role"):
        generator.SourceLabel(
            value="Label",
            language="en",
            role="future-role",
            source_path="source#label",
        )
    with pytest.raises(ValueError, match="unsupported source label role"):
        generator._source_label_predicate("future-role")


@pytest.mark.parametrize(
    ("ring_name", "resource_class", "assignment_predicate"),
    (
        ("subject", generator.ATLAS.SubjectConcept, generator.ATLAS.assignedSubject),
        ("entity", generator.ATLAS.EntityResource, generator.ATLAS.assignedEntity),
        ("value", generator.ATLAS.ValueResource, generator.ATLAS.assignedValue),
        (
            "legalIdentity",
            generator.ATLAS.LegalIdentityResource,
            generator.ATLAS.assignedLegalIdentity,
        ),
    ),
)
def test_ring_dispatch_uses_binding_policy(
    ring_name: str,
    resource_class: URIRef,
    assignment_predicate: URIRef,
) -> None:
    ring, observed_class, observed_predicate = generator._ring_dispatch(ring_name)

    assert ring == generator.ATLAS[ring_name]
    assert observed_class == resource_class
    assert observed_predicate == assignment_predicate


def test_ring_dispatch_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported Atlas semantic ring"):
        generator._ring_dispatch("futureRing")


def _compiled_descriptor_graph() -> Graph:
    graph = generator._new_build_graph()
    scheme = URIRef("urn:test:scheme:subjects")
    graph.add((scheme, RDF.type, generator.ATLAS.ResourceScheme))
    graph.add((scheme, RDF.type, generator.SKOS.ConceptScheme))
    graph.add(
        (scheme, generator.ATLAS.resourceProfile, generator.ATLAS.conceptScheme)
    )
    graph.add((scheme, generator.ATLAS.supportedRing, generator.ATLAS.subject))
    return graph


def _compiled_source_release(
    tmp_path: Path,
    *,
    labels: tuple[generator.SourceLabel, ...] | None = None,
    predicate: str | None = None,
) -> generator.LoadedRelease:
    source = tmp_path / "compiled-source.json"
    source.write_text("{}", encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    first = generator.SourceResource(
        iri="urn:test:resource:first",
        labels=labels
        or (
            generator.SourceLabel(
                value="First",
                language="en",
                role="preferred",
                source_path="source.json#first.label",
            ),
        ),
        native_payload={"id": "first"},
        source_locator="urn:test:source-row:first",
        source_digest=digest,
    )
    second = generator.SourceResource(
        iri="urn:test:resource:second",
        labels=(
            generator.SourceLabel(
                value="Second",
                language="en",
                role="preferred",
                source_path="source.json#second.label",
            ),
        ),
        native_payload={"id": "second"},
        source_locator="urn:test:source-row:second",
        source_digest=digest,
    )
    relations = (
        generator.SourceRelation(
            subject=first.iri,
            predicate=predicate or str(generator.SKOS.related),
            object=second.iri,
            source_payload={"sourcePath": "source.json#first.related"},
        ),
    )
    spec = generator.SourceSpec(
        key="compiled-source",
        kind="test",
        path=source,
        logical_path="compiled-source.json",
        expected_digest=digest,
        expected_resources=2,
        expected_relations=1,
        profile="conceptScheme",
        ring="subject",
    )
    return generator.LoadedRelease(
        spec=spec,
        source_release_iri="urn:test:source-release:compiled",
        source_release_digest=digest,
        atlas_release_iri="urn:test:atlas-release:compiled",
        scheme_iri="urn:test:scheme:subjects",
        issued="2026-08-06",
        resources=(first, second),
        relations=relations,
    )


def test_compiled_source_producer_validates_rows_and_constructor_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    release = _compiled_source_release(tmp_path)

    source_receipt = generator._validate_compiled_source_rows((release,))
    graphs = generator._build_graphs((release,), include_projection=False)
    report = generator._validate_compiled_producer_output(
        (release,),
        graphs,
        source_receipt,
    )

    assert report["mode"] == "compiledSourceProducerValidation"
    assert report["shaclDataProof"] == "compiledAgainstPinnedOntologyAndShapes"
    assert report["counts"] == {
        "crossRingRelationAssertions": 0,
        "derivedRelations": 0,
        "identifiers": 0,
        "labels": 2,
        "mappingAssertions": 0,
        "nativeRelationAssertions": 1,
        "projectedRelations": 0,
        "relationAssertions": 3,
        "releases": 1,
        "resources": 2,
        "sourceAssignments": 2,
        "sourceRecords": 2,
    }


def test_compiled_source_producer_fails_closed_when_shape_profile_drifts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = generator.ATLAS_VALIDATE._binding_digests()
    monkeypatch.setattr(
        generator.ATLAS_VALIDATE,
        "_binding_digests",
        lambda: {**observed, "shapesDigest": "sha256:" + "0" * 64},
    )

    with pytest.raises(ValueError, match="validation profile drifted"):
        generator._validate_compiled_binding_profile()


def test_compiled_source_producer_implementation_pin_is_current() -> None:
    assert generator._compiled_producer_implementation_digest() == (
        generator._COMPILED_PRODUCER_IMPLEMENTATION_DIGEST
    )


def test_compiled_source_producer_rejects_empty_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    monkeypatch.setattr(
        generator,
        "_validate_compiled_binding_profile",
        lambda: dict(generator._COMPILED_PRODUCER_BINDING_PINS),
    )
    release = _compiled_source_release(tmp_path)
    release = dataclasses.replace(
        release,
        spec=dataclasses.replace(
            release.spec,
            expected_resources=0,
            expected_relations=0,
        ),
        resources=(),
        relations=(),
    )

    with pytest.raises(ValueError, match="has no Atlas resources"):
        generator._validate_compiled_source_rows((release,))


def test_compiled_source_producer_rejects_subject_scheme_without_skos_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor = _compiled_descriptor_graph()
    descriptor.remove(
        (
            URIRef("urn:test:scheme:subjects"),
            RDF.type,
            generator.SKOS.ConceptScheme,
        )
    )
    monkeypatch.setattr(generator, "_registry_asserted_graph", lambda: descriptor)
    monkeypatch.setattr(
        generator,
        "_validate_compiled_binding_profile",
        lambda: dict(generator._COMPILED_PRODUCER_BINDING_PINS),
    )

    with pytest.raises(ValueError, match="not a SKOS ConceptScheme"):
        generator._validate_compiled_source_rows(
            (_compiled_source_release(tmp_path),)
        )


def test_asserted_pack_writer_rejects_oversized_nquads_line(
    tmp_path: Path,
) -> None:
    asserted = generator._new_build_graph()
    asserted.add(
        (
            URIRef("urn:test:subject"),
            URIRef("urn:test:predicate"),
            generator.Literal(
                "x" * generator.ATLAS_VALIDATE.NQUADS_MAX_LINE_BYTES
            ),
        )
    )

    with pytest.raises(ValueError, match="exceeds the binding limit"):
        generator._write_asserted_packs(tmp_path, asserted, ())


def test_candidate_rejects_asserted_mutation_after_compiled_validation(
    tmp_path: Path,
) -> None:
    asserted = generator._new_build_graph()
    asserted.add(
        (
            URIRef("urn:test:subject"),
            URIRef("urn:test:predicate"),
            URIRef("urn:test:object"),
        )
    )
    graphs = generator.BuildGraphs(
        asserted,
        generator._new_build_graph(),
        generator._new_build_graph(),
        {},
    )
    report = _compiled_test_report(graphs)
    asserted.add(
        (
            URIRef("urn:test:subject"),
            URIRef("urn:test:extra"),
            URIRef("urn:test:value"),
        )
    )

    with pytest.raises(ValueError, match="changed after compiled"):
        generator._write_candidate_distribution(
            tmp_path,
            graphs,
            compiled_validation=report,
        )


@pytest.mark.parametrize(
    ("labels", "predicate", "message"),
    (
        (
            (
                generator.SourceLabel(
                    "First",
                    "en",
                    "preferred",
                    "source.json#first.label",
                ),
                generator.SourceLabel(
                    "First alternate spelling",
                    "en",
                    "preferred",
                    "source.json#first.label-2",
                ),
            ),
            None,
            "more than one preferred",
        ),
        (
            (
                generator.SourceLabel(
                    "First",
                    "en",
                    "preferred",
                    "source.json#first.label",
                ),
                generator.SourceLabel(
                    "First",
                    "en",
                    "alternate",
                    "source.json#first.alt-label",
                ),
            ),
            None,
            "across SKOS-XL roles",
        ),
        (
            None,
            "urn:test:not-allowed",
            "predicate is not allowed",
        ),
    ),
)
def test_compiled_source_producer_rejects_compact_row_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    labels: tuple[generator.SourceLabel, ...] | None,
    predicate: str | None,
    message: str,
) -> None:
    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    monkeypatch.setattr(
        generator,
        "_validate_compiled_binding_profile",
        lambda: dict(generator._COMPILED_PRODUCER_BINDING_PINS),
    )
    release = _compiled_source_release(
        tmp_path,
        labels=labels,
        predicate=predicate,
    )

    with pytest.raises(ValueError, match=message):
        generator._validate_compiled_source_rows((release,))


def test_compiled_source_producer_rejects_projection_and_accounting_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    monkeypatch.setattr(
        generator,
        "_validate_compiled_binding_profile",
        lambda: dict(generator._COMPILED_PRODUCER_BINDING_PINS),
    )
    release = _compiled_source_release(tmp_path)
    source_receipt = generator._validate_compiled_source_rows((release,))
    graphs = generator._build_graphs((release,), include_projection=False)
    graphs.projection.add(
        (
            URIRef("urn:test:projection"),
            RDF.type,
            generator.ATLAS.ProjectedRelation,
        )
    )
    with pytest.raises(ValueError, match="empty projection"):
        generator._validate_compiled_producer_output(
            (release,),
            graphs,
            source_receipt,
        )

    graphs.projection.remove((None, None, None))
    graphs.accounting["inputs"][0]["dispositions"].pop()
    with pytest.raises(ValueError, match="member count differs"):
        generator._validate_compiled_producer_output(
            (release,),
            graphs,
            source_receipt,
        )


def test_loaded_release_counts_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    spec = generator.SourceSpec(
        key="count-test",
        kind="test",
        path=source,
        logical_path="source.json",
        expected_digest="sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
        expected_resources=1,
        expected_relations=1,
        profile="codeScheme",
        ring="value",
    )
    release = generator.LoadedRelease(
        spec=spec,
        source_release_iri="urn:test:source-release",
        source_release_digest=spec.expected_digest,
        atlas_release_iri="urn:test:atlas-release",
        scheme_iri="urn:ref:atlas-resource-scheme:count-test",
        issued="2026-08-05",
        resources=(),
        relations=(),
    )

    with pytest.raises(ValueError, match="source counts differ"):
        generator._validate_loaded_release(release)


def test_crs_loader_preserves_source_label_roles(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "crs-source.json"
    source.write_text("{}", encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    observation = {
        "id": "urn:test:observation",
        "labels": [
            {"language": "en", "role": "preferred", "value": "Public label"},
            {"language": "en", "role": "hidden", "value": "Search-only form"},
        ],
        "sourcePath": "source.json#concept",
    }
    view = SimpleNamespace(
        concepts=(
            {
                "id": "https://example.test/concept",
                "identityKind": "publisherConceptIri",
                "sourceObservation": observation["id"],
                "sourceObservationDigest": "sha256:" + "1" * 64,
            },
        ),
        release_digest="sha256:" + "2" * 64,
        release_id="urn:test:crs-release",
        source_bundle=SimpleNamespace(observations=(observation,)),
    )
    monkeypatch.setattr(
        generator.SourceConceptReleaseView,
        "open",
        staticmethod(lambda *_args, **_kwargs: view),
    )
    spec = generator.SourceSpec(
        key="crs-test",
        kind="sourceConceptRelease",
        path=source,
        logical_path="test/crs-source.json",
        expected_digest=digest,
        expected_resources=1,
        profile="conceptScheme",
        ring="subject",
    )

    release = generator._load_crs(spec)

    assert {label.value: label.role for label in release.resources[0].labels} == {
        "Public label": "preferred",
        "Search-only form": "hidden",
    }


def test_elsst_loader_includes_english_hidden_labels(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "elsst-source.json"
    source.write_text("{}", encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    member = SimpleNamespace(
        member_iri="https://example.test/elsst/concept",
        record={
            "skos:altLabel": {"en": ["Alternate label"]},
            "skos:hiddenLabel": {
                "en": ["Hidden label"],
                "fr": ["Etiquette cachee"],
            },
            "skos:prefLabel": {"en": "Preferred label"},
        },
    )

    class FakeElsstView:
        def iter_members(self, *, release_iri: str):
            assert release_iri == "https://elsst.cessda.eu/id/6"
            return iter((member,))

    monkeypatch.setattr(
        generator.ManagedReleaseGraphFactsView,
        "open",
        staticmethod(lambda *_args, **_kwargs: FakeElsstView()),
    )
    spec = generator.SourceSpec(
        key="elsst-r6",
        kind="managedRelease",
        path=source,
        logical_path="test/elsst-source.json",
        expected_digest=digest,
        expected_resources=1,
        profile="conceptScheme",
        ring="subject",
    )

    release = generator._load_elsst(spec)

    assert {label.value: label.role for label in release.resources[0].labels} == {
        "Alternate label": "alternate",
        "Hidden label": "hidden",
        "Preferred label": "preferred",
    }
    assert release.dropped_label_count == 1


@pytest.fixture(scope="module")
def crs_releases():
    return tuple(
        generator._load_crs(_source_spec(key))
        for key in (
            "crs-legislative-entities",
            "crs-legislative-subjects",
            "crs-policy-areas",
        )
    )


def test_all_1075_crs_fallback_ids_are_readable_and_reversible(
    crs_releases,
) -> None:
    resources = [
        (release, resource)
        for release in crs_releases
        for resource in release.resources
    ]
    counts_by_namespace = {
        token: sum(
            len(release.resources)
            for release in crs_releases
            if release.spec.fallback_namespace_token == token
        )
        for token in ("loc-lst", "loc-cgpa")
    }

    assert len(resources) == 1_075
    assert counts_by_namespace == {"loc-lst": 1_043, "loc-cgpa": 32}
    assert not any(
        resource.iri.startswith("urn:ref:source-concept:v1:")
        for _, resource in resources
    )
    for release, resource in resources:
        token = release.spec.fallback_namespace_token
        assert resource.iri.startswith(
            f"urn:ref:source-concept:v2:{token}:"
        )
        assert resource.native_payload is not None
        source_identity = resource.native_payload["sourceIdentity"]
        assert source_identity["identityKind"] == "refspecSourceScoped"
        assert source_identity["namespaceToken"] == token
        assert source_identity["priorSourceConceptIri"].startswith(
            "urn:ref:source-concept:v1:"
        )
        assert resource.iri.endswith(
            source_identity["localRecordId"].removeprefix("urn:uuid:")
        )

    entity_release = next(
        release
        for release in crs_releases
        if release.spec.key == "crs-legislative-entities"
    )
    brazil = next(
        resource
        for resource in entity_release.resources
        if any(label.value == "Brazil" for label in resource.labels)
    )
    assert brazil.iri == (
        "urn:ref:source-concept:v2:loc-lst:"
        "019fc9f2-c758-7134-9432-2a0de8fde1dd"
    )
    assert brazil.native_payload is not None
    assert brazil.native_payload["sourceIdentity"] == {
        "identityKind": "refspecSourceScoped",
        "localRecordId": "urn:uuid:019fc9f2-c758-7134-9432-2a0de8fde1dd",
        "namespaceToken": "loc-lst",
        "priorSourceConceptIri": (
            "urn:ref:source-concept:v1:"
            "6db43bea6ad5f32b25d57b4cd182d1b3b7f5de9a29a727b65fc17954cec97f01:"
            "019fc9f2-c758-7134-9432-2a0de8fde1dd"
        ),
        "sourceScheme": "http://id.loc.gov/vocabulary/subjectSchemes/lst",
    }


@pytest.fixture(scope="module")
def icpsr_release():
    return generator._load_icpsr(_source_spec("icpsr-subject-thesaurus"))


@pytest.fixture(scope="module")
def document_releases():
    from refspec.atlas.v3_registry_documents import load_registry_document_releases

    return tuple(
        generator._adapt_registry_release(release)
        for release in load_registry_document_releases(ROOT)
    )


@pytest.fixture(scope="module")
def registry_code_releases():
    from refspec.atlas.v3_registry_codes import load_registry_code_releases

    return tuple(
        generator._adapt_registry_release(release)
        for release in load_registry_code_releases(ROOT)
    )


def test_only_five_icpsr_xml_gaps_receive_readable_fallback_ids(
    icpsr_release,
) -> None:
    fallback_resources = [
        resource
        for resource in icpsr_release.resources
        if resource.native_payload is not None
        and resource.native_payload.get("identityStatus")
        == "publisherIdentifierAbsent"
    ]
    publisher_resources = [
        resource
        for resource in icpsr_release.resources
        if resource.native_payload is not None
        and resource.native_payload.get("identityStatus")
        != "publisherIdentifierAbsent"
    ]
    fallback_ids = {resource.iri for resource in fallback_resources}
    fallback_relation_endpoints = {
        endpoint
        for relation in icpsr_release.relations
        for endpoint in (relation.subject, relation.object)
        if endpoint.startswith(
            "urn:ref:source-concept:v2:icpsr-subject-thesaurus:"
        )
    }

    assert len(fallback_resources) == 5
    assert len(publisher_resources) == 3_805
    assert all(
        resource.iri.startswith(
            "urn:ref:source-concept:v2:icpsr-subject-thesaurus:"
        )
        for resource in fallback_resources
    )
    assert all(
        resource.native_payload is not None
        and resource.native_payload["sourceIdentity"]["priorSourceConceptIri"].startswith(
            "urn:ref:source-concept:v1:"
        )
        for resource in fallback_resources
    )
    assert all(
        resource.iri == resource.source_locator
        for resource in publisher_resources
    )
    assert fallback_relation_endpoints == fallback_ids
    assert not any(
        resource.iri.startswith("urn:ref:source-concept:v1:")
        for resource in icpsr_release.resources
    )
    assert not any(
        endpoint.startswith("urn:ref:source-concept:v1:")
        for relation in icpsr_release.relations
        for endpoint in (relation.subject, relation.object)
    )


def test_compiled_producer_matches_normative_shacl_for_real_assertion_variants(
    icpsr_release,
    document_releases,
) -> None:
    native_relation = icpsr_release.relations[0]
    native_resources = {
        resource.iri: resource for resource in icpsr_release.resources
    }
    sampled_native_resources = tuple(
        native_resources[iri]
        for iri in dict.fromkeys(
            (native_relation.subject, native_relation.object)
        )
    )
    native_spec = dataclasses.replace(
        icpsr_release.spec,
        expected_resources=len(sampled_native_resources),
        expected_relations=1,
    )
    sampled_native = dataclasses.replace(
        icpsr_release,
        spec=native_spec,
        resources=sampled_native_resources,
        relations=(native_relation,),
    )

    cross_owner = next(
        release for release in document_releases if release.cross_ring_relations
    )
    cross_relation = cross_owner.cross_ring_relations[0]
    endpoint_iris = {cross_relation.subject, cross_relation.object}
    sampled_documents: list[generator.LoadedRelease] = []
    for release in document_releases:
        resources = tuple(
            resource for resource in release.resources if resource.iri in endpoint_iris
        )
        if not resources:
            continue
        cross_relations = (cross_relation,) if release is cross_owner else ()
        sampled_documents.append(
            dataclasses.replace(
                release,
                spec=dataclasses.replace(
                    release.spec,
                    expected_resources=len(resources),
                    expected_relations=0,
                    expected_cross_ring_relations=len(cross_relations),
                ),
                resources=resources,
                relations=(),
                cross_ring_relations=cross_relations,
            )
        )
    releases = (sampled_native, *sampled_documents)

    source_receipt = generator._validate_compiled_source_rows(releases)
    graphs = generator._build_graphs(releases, include_projection=False)
    producer_report = generator._validate_compiled_producer_output(
        releases,
        graphs,
        source_receipt,
    )
    ontology, shapes = generator.ATLAS_VALIDATE._parse_binding_graphs()
    try:
        generator.ATLAS_VALIDATE._lint_ontology(ontology)
        generator.ATLAS_VALIDATE._run_shacl(
            {
                "asserted": graphs.asserted,
                "projection": graphs.projection,
                "derived": graphs.derived,
            },
            ontology,
            shapes,
        )
    finally:
        ontology.close()
        shapes.close()
        graphs.release()

    assert producer_report["status"] == "passed"
    assert producer_report["counts"]["sourceAssignments"] >= 1
    assert producer_report["counts"]["nativeRelationAssertions"] == 1
    assert producer_report["counts"]["crossRingRelationAssertions"] == 1


def test_grants_subject_codes_use_a_skos_concept_scheme(
    registry_code_releases,
) -> None:
    releases = tuple(
        release
        for release in registry_code_releases
        if release.spec.key
        in {
            "grants-gov-eligibilities",
            "grants-gov-funding-categories",
        }
    )
    assert {release.spec.key for release in releases} == {
        "grants-gov-eligibilities",
        "grants-gov-funding-categories",
    }

    source_receipt = generator._validate_compiled_source_rows(releases)
    graphs = generator._build_graphs(releases, include_projection=False)
    ontology, shapes = generator.ATLAS_VALIDATE._parse_binding_graphs()
    try:
        scheme = generator.URIRef(
            "urn:ref:atlas-resource-scheme:grants-gov-status-codes"
        )
        assert (
            scheme,
            generator.RDF.type,
            generator.SKOS.ConceptScheme,
        ) in graphs.asserted
        generator._validate_compiled_producer_output(
            releases,
            graphs,
            source_receipt,
        )
        generator.ATLAS_VALIDATE._run_shacl(
            {
                "asserted": graphs.asserted,
                "projection": graphs.projection,
                "derived": graphs.derived,
            },
            ontology,
            shapes,
        )
    finally:
        ontology.close()
        shapes.close()
        graphs.release()


def test_mapping_evidence_archive_preserves_all_exact_proof_bytes() -> None:
    archive_root = (
        ROOT / "research" / "evidence" / "atlas-3-mapping-evidence-2026-08-05"
    )
    manifest_path = archive_root / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    assert "sha256:" + hashlib.sha256(manifest_bytes).hexdigest() == (
        "sha256:287858f602d3073f81584e43f2692c1f35575bc62c767bf1ed90b217ac19f9e8"
    )
    archive = json.loads(manifest_bytes)
    counts = {
        row["id"]: row["mappingAssertionCount"]
        for row in archive["pairs"]
    }

    assert counts == {
        "elsst-icpsr": 191,
        "fr-elsst": 190,
        "fr-icpsr": 201,
    }
    assert sum(counts.values()) == 582
    assert len(archive["artifacts"]) == 9
    expected_paths = {
        f"{pair}/{name}"
        for pair in ("elsst-icpsr", "fr-elsst", "fr-icpsr")
        for name in (
            "crosswalk-bundle.json",
            "relation-assertions-v2/bundle-manifest.json",
            "relation-assertions-v2/relation-assertions.json",
        )
    }
    descriptors = {row["path"]: row for row in archive["artifacts"]}
    assert set(descriptors) == expected_paths
    for relative_path, descriptor in descriptors.items():
        artifact = archive_root / relative_path
        payload = artifact.read_bytes()
        assert descriptor["byteLength"] == len(payload)
        assert descriptor["sha256"] == (
            "sha256:" + hashlib.sha256(payload).hexdigest()
        )


def test_production_relation_scope_rejects_mapping_and_derived_relations() -> None:
    clean = generator.BuildGraphs(Graph(), Graph(), Graph(), {})
    assert generator._production_relation_scope(clean) == {
        "derivedRelations": 0,
        "mappingAssertions": 0,
        "mode": "publisherSourceOnly",
    }

    mapping = generator.BuildGraphs(Graph(), Graph(), Graph(), {})
    mapping.asserted.add(
        (
            URIRef("urn:test:mapping"),
            RDF.type,
            generator.ATLAS.MappingAssertion,
        )
    )
    with pytest.raises(ValueError, match="zero mapping assertions"):
        generator._production_relation_scope(mapping)

    derived = generator.BuildGraphs(Graph(), Graph(), Graph(), {})
    derived.derived.add(
        (
            URIRef("urn:test:derived"),
            RDF.type,
            generator.ATLAS.DerivedRelation,
        )
    )
    with pytest.raises(ValueError, match="zero mapping assertions"):
        generator._production_relation_scope(derived)


def test_recursive_english_normalization_covers_complete_elsst_profile() -> None:
    payload = {
        "nested": {
            "skos:hiddenLabel": {"en": "Hidden", "fr": "Cache"},
            "skos:editorialNote": {"EN": ["Keep"], "de": ["Drop"]},
        },
        "ordinary": {"id": ["urn:test:not-a-language-map"]},
        "tagged": [
            {"language": "EN", "value": "Keep"},
            {"language": "fr", "value": "Drop"},
        ],
    }

    normalized, dropped = generator._normalize_english_language_content(
        payload,
        language_map_fields=generator.ELSST_LANGUAGE_MAP_FIELDS,
    )

    assert normalized["nested"] == {
        "skos:editorialNote": {"en": ["Keep"]},
        "skos:hiddenLabel": {"en": ["Hidden"]},
    }
    assert normalized["ordinary"] == {"id": ["urn:test:not-a-language-map"]}
    assert normalized["tagged"] == [{"language": "en", "value": "Keep"}]
    assert {(row["path"], row["language"]) for row in dropped} == {
        ("nested/skos:editorialNote", "de"),
        ("nested/skos:hiddenLabel", "fr"),
        ("tagged/1", "fr"),
    }
    maps, tags, violations = generator._audit_english_language_content(
        normalized,
        language_map_fields=generator.ELSST_LANGUAGE_MAP_FIELDS,
    )
    assert (maps, tags, violations) == (2, 1, ())


def test_english_normalization_fails_closed_for_unprofiled_language_field() -> None:
    with pytest.raises(ValueError, match="unprofiled language-bearing field"):
        generator._normalize_english_language_content(
            {"skos:futureNote": {"en": "Known", "fr": "Inconnu"}},
            language_map_fields=generator.ELSST_LANGUAGE_MAP_FIELDS,
        )


def test_source_record_rejects_nested_non_english_tagged_content() -> None:
    with pytest.raises(ValueError, match="not English-only"):
        generator._add_source_record(
            Graph(),
            source_release=URIRef("urn:test:release"),
            source_locator=URIRef("urn:test:locator"),
            source_digest="sha256:" + "0" * 64,
            native_payload={"proofDetails": {"language": "fr", "value": "preuve"}},
            represents_resource=None,
        )


def test_source_record_canonicalizes_native_payload_once_and_preserves_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Graph()
    source_release = URIRef("urn:test:release")
    source_locator = URIRef("urn:test:locator")
    source_digest = "sha256:" + "1" * 64
    native_payload = {"nested": {"rows": ["one", {"ordinal": 2}]}}
    plain_payload = generator._plain(native_payload)
    original = generator.ATLAS_VALIDATE.canonical_native_json_bytes
    expected_bytes = original(plain_payload)
    calls = 0

    def counted(value: object) -> bytes:
        nonlocal calls
        calls += 1
        return original(value)

    monkeypatch.setattr(
        generator.ATLAS_VALIDATE,
        "canonical_native_json_bytes",
        counted,
    )
    record = generator._add_source_record(
        graph,
        source_release=source_release,
        source_locator=source_locator,
        source_digest=source_digest,
        native_payload=native_payload,
        represents_resource=None,
    )

    native_digest = "sha256:" + hashlib.sha256(expected_bytes).hexdigest()
    assert calls == 1
    assert record == generator._node_iri(
        "atlas-source-record",
        {
            "nativePayloadDigest": native_digest,
            "sourceDigest": source_digest,
            "sourceLocator": str(source_locator),
            "sourceRelease": str(source_release),
        },
    )
    assert str(graph.value(record, generator.ATLAS.nativePayload)) == expected_bytes.decode(
        "utf-8"
    )
    assert str(graph.value(record, generator.ATLAS.contentDigest)) == (
        generator.ATLAS_VALIDATE.rdf_node_digest(graph, record)
    )


def test_add_assertion_mints_evidence_without_temporary_graph_mutations() -> None:
    class RemoveRejectingGraph(Graph):
        def remove(self, triple: object) -> Graph:
            raise AssertionError(f"evidence construction must not remove {triple}")

    graph = RemoveRejectingGraph()
    policy = URIRef("urn:test:policy")
    evidence_record = URIRef("urn:test:evidence-record")
    graph.add(
        (
            policy,
            generator.ATLAS.contentDigest,
            generator.Literal("sha256:" + "2" * 64),
        )
    )
    graph.add(
        (
            evidence_record,
            generator.ATLAS.contentDigest,
            generator.Literal("sha256:" + "3" * 64),
        )
    )

    generator._add_assertion(
        graph,
        assertion_type=generator.ATLAS.NativeRelationAssertion,
        ring=generator.ATLAS.subject,
        subject=URIRef("urn:test:subject"),
        predicate=generator.SKOS.related,
        obj=URIRef("urn:test:object"),
        source_release=URIRef("urn:test:source-release"),
        target_release=URIRef("urn:test:source-release"),
        policy=policy,
        asserted_at="2026-08-06T00:00:00Z",
        evidence_record=evidence_record,
        reviewer=URIRef("urn:test:reviewer"),
        review_method=generator.ATLAS.publisherAssertion,
        confidence=None,
    )

    bindings = set(
        graph.subjects(RDF.type, generator.ATLAS.EvidenceBinding)
    )
    assert len(bindings) == 1
    binding = next(iter(bindings))
    stored_digest = str(graph.value(binding, generator.ATLAS.contentDigest))
    assert binding == URIRef(
        "urn:ref:atlas-evidence:" + stored_digest.removeprefix("sha256:")
    )
    assert stored_digest == generator.ATLAS_VALIDATE.rdf_node_digest(
        graph,
        binding,
    )
    assert not any(
        str(subject).startswith("urn:ref:atlas-evidence:pending:")
        for subject in graph.subjects()
    )


def test_review_methods_match_assertion_provenance_without_operator_adoption() -> None:
    observed = {
        generator._review_method_for_assertion(generator.ATLAS.SourceAssignment),
        generator._review_method_for_assertion(
            generator.ATLAS.NativeRelationAssertion
        ),
        generator._review_method_for_assertion(
            generator.ATLAS.NativeRelationAssertion,
            deterministic_transformation=True,
        ),
    }

    assert observed == {
        generator.ATLAS.publisherAssertion,
        generator.ATLAS.deterministicTransformation,
    }
    assert generator.ATLAS.operatorAdoption not in observed
    with pytest.raises(ValueError, match="unsupported assertion"):
        generator._review_method_for_assertion(generator.ATLAS.MappingAssertion)


def test_active_editorial_policies_contain_no_serving_permission_language() -> None:
    graph = Graph()
    emitted_payloads = []

    for payload in generator.EDITORIAL_POLICY_PAYLOADS.values():
        policy = generator._add_policy(graph, payload)
        encoded = graph.value(policy, generator.ATLAS.policyPayload)
        assert encoded is not None
        emitted_payload = json.loads(str(encoded))
        emitted_payloads.append(emitted_payload)
        assert emitted_payload == generator._plain(payload)
        assert generator._portable_policy_term_violations(emitted_payload) == ()

    assert len(emitted_payloads) == 1
    with pytest.raises(ValueError, match="serving eligibility or permission"):
        generator._add_policy(
            Graph(),
            {"nested": [{"usage-permission": "searchOnly"}]},
        )


def test_transformed_relation_evidence_is_content_derived_and_preserves_publisher_row() -> None:
    publisher_relation = {
        "relation": "related",
        "sourceLabel": "A",
        "sourceLocalRecordNumber": "1",
        "sourcePath": "subject.xml#record=1",
        "targetLabel": "B",
    }
    relation = generator.SourceRelation(
        subject="urn:test:a",
        predicate=str(generator.ATLAS.thesaurusRelated),
        object="urn:test:b",
        source_payload={
            "editorialTransformation": {
                "fromPredicate": str(generator.SKOS.related),
                "reason": "SKOS-S27-hierarchy-path",
                "rule": "preserveAuthoredAssociationOutsideSkosProjection",
                "toPredicate": str(generator.ATLAS.thesaurusRelated),
            },
            "publisherRelation": publisher_relation,
        },
    )

    locator, source_digest, payload = generator._transformed_relation_evidence(relation)

    assert source_digest == generator._native_digest(publisher_relation)
    assert str(locator).endswith(source_digest.removeprefix("sha256:"))
    assert payload["publisherRelation"] == publisher_relation
    assert payload["publisherRelationDigest"] == source_digest
    assert json.dumps(payload, sort_keys=True) == json.dumps(
        generator._transformed_relation_evidence(relation)[2],
        sort_keys=True,
    )


def test_source_accounting_recounts_all_22_icpsr_remap_evidence_records() -> None:
    represented = [
        {
            "atlasResources": [f"urn:test:icpsr:{index}"],
            "sourceRecord": f"urn:test:source-record:{index:04d}",
            "status": "represented",
        }
        for index in reversed(range(3_810))
    ]
    remap_evidence = [
        {
            "atlasResources": [],
            "reason": "Evidence-only deterministic relation remap.",
            "sourceRecord": f"urn:test:remap-evidence:{index:02d}",
            "status": "excluded",
        }
        for index in reversed(range(22))
    ]
    icpsr = {
        "declaredMemberCount": len(represented),
        "dispositions": [*represented, *remap_evidence],
        "membershipMode": "complete",
        "sourceRelease": "urn:test:release:icpsr",
    }
    other = {
        "declaredMemberCount": 0,
        "dispositions": [],
        "membershipMode": "complete",
        "sourceRelease": "urn:test:release:aaa",
    }
    accounting_inputs = [icpsr, other]

    generator._finalize_source_accounting_inputs(accounting_inputs)

    assert accounting_inputs == [other, icpsr]
    assert icpsr["declaredMemberCount"] == 3_832
    assert len(icpsr["dispositions"]) == 3_832
    assert [row["sourceRecord"] for row in icpsr["dispositions"]] == sorted(
        row["sourceRecord"] for row in icpsr["dispositions"]
    )


def test_generation_report_uses_a_location_independent_distribution_path(
    tmp_path: Path,
) -> None:
    first = tmp_path / "checkout-a" / "distribution"
    second = tmp_path / "checkout-b" / "distribution"

    assert generator._generation_report_distribution_path(first) == "distribution"
    assert generator._generation_report_distribution_path(second) == "distribution"
    assert not Path(generator._generation_report_distribution_path(first)).is_absolute()


def test_external_sort_bounds_open_files_across_multiple_merge_rounds(
    tmp_path: Path,
) -> None:
    output = tmp_path / "sorted.nq"
    rows = [f"row-{index:03d}\n" for index in reversed(range(41))]

    generator._write_sorted_lines(
        output,
        rows,
        chunk_line_count=2,
        merge_fan_in=3,
    )

    assert output.read_text().splitlines() == sorted(row.strip() for row in rows)


def test_lean_build_graph_preserves_validator_projection_semantics() -> None:
    asserted = Graph()
    resource = URIRef("urn:test:resource")
    label = URIRef("urn:test:label")
    asserted.add((resource, generator.SKOSXL.prefLabel, label))
    asserted.add(
        (
            label,
            generator.SKOSXL.literalForm,
            generator.Literal("Public label", lang="en"),
        )
    )

    expected = generator.ATLAS_VALIDATE._expected_projection(asserted)
    actual = generator._expected_projection_graph(asserted)

    assert actual.store.__class__.__name__ == "SimpleMemory"
    assert actual.store.context_aware is False
    assert set(actual) == set(expected)


def test_released_build_graphs_remain_lean_and_empty() -> None:
    graphs = generator.BuildGraphs(
        asserted=generator._new_build_graph(),
        projection=generator._new_build_graph(),
        derived=generator._new_build_graph(),
        accounting={"large": "ledger"},
    )
    graphs.asserted.add(
        (
            URIRef("urn:test:subject"),
            URIRef("urn:test:predicate"),
            URIRef("urn:test:object"),
        )
    )

    graphs.release()

    assert graphs.accounting == {}
    for graph in (graphs.asserted, graphs.projection, graphs.derived):
        assert graph.store.__class__.__name__ == "SimpleMemory"
        assert not graph


@pytest.mark.parametrize(
    ("scope", "membership_mode"),
    (
        ("publisherRelease", "complete"),
        ("completeCapture", "complete"),
        ("captureSubset", "partial"),
    ),
)
def test_source_scope_controls_accounting_membership(
    scope: str,
    membership_mode: str,
) -> None:
    assert generator._accounting_membership_mode(scope) == membership_mode


def test_crs_sources_are_complete_captures_not_claimed_publisher_releases() -> None:
    crs = [spec for spec in generator.SOURCE_SPECS if spec.key.startswith("crs-")]

    assert len(crs) == 3
    assert {spec.scope for spec in crs} == {"completeCapture"}


def test_build_graphs_emits_content_derived_registry_identifiers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resource_scheme = URIRef("urn:test:scheme:codes")
    identifier_scheme = URIRef("urn:test:scheme:identifiers")
    descriptor_graph = generator._new_build_graph()
    for scheme, profile in (
        (resource_scheme, generator.ATLAS.codeScheme),
        (identifier_scheme, generator.ATLAS.identifierScheme),
    ):
        descriptor_graph.add((scheme, RDF.type, generator.ATLAS.ResourceScheme))
        descriptor_graph.add((scheme, generator.ATLAS.resourceProfile, profile))
    descriptor_graph.add(
        (resource_scheme, generator.ATLAS.supportedRing, generator.ATLAS.value)
    )
    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        lambda: descriptor_graph,
    )

    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    source_digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    resource_iri = "urn:test:resource:one"
    source_path = "source.json#row=1.identifier"
    release = generator._adapt_registry_release(
        RegistryRelease(
            key="identifier-emission-test",
            resource_id="identifier-emission-test",
            source_module="refspec.registry.test",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            source_release_iri="urn:test:source-release",
            source_release_digest=source_digest,
            atlas_release_iri="urn:test:atlas-release",
            scheme_iri=str(resource_scheme),
            issued="2026-08-06",
            inputs=(
                RegistryInputPin(
                    path=source,
                    logical_path="source.json",
                    sha256=source_digest,
                    byte_length=source.stat().st_size,
                    source_iri="urn:test:source",
                ),
            ),
            resources=(
                RegistryResource(
                    iri=resource_iri,
                    labels=(
                        RegistryLabel(
                            value="One",
                            role="preferred",
                            source_path="source.json#row=1.label",
                        ),
                    ),
                    native_payload={"identifier": "ONE-001"},
                    source_locator="urn:test:source-row:1",
                    source_digest=source_digest,
                    identifiers=(
                        generator.RegistryIdentifier(
                            value="ONE-001",
                            scheme_iri=str(identifier_scheme),
                            source_path=source_path,
                        ),
                    ),
                ),
            ),
        )
    )

    graphs = generator._build_graphs((release,))
    identifiers = set(
        graphs.asserted.subjects(RDF.type, generator.ATLAS.Identifier)
    )

    assert len(identifiers) == 1
    identifier = next(iter(identifiers))
    resource = URIRef(resource_iri)
    source_record = graphs.asserted.value(resource, generator.ATLAS.sourceRecord)
    assert identifier == generator._node_iri(
        "atlas-identifier",
        {
            "identifierScheme": str(identifier_scheme),
            "identifierValue": "ONE-001",
            "identifies": resource_iri,
            "sourcePath": source_path,
            "sourceRecord": str(source_record),
        },
    )
    assert set(graphs.asserted.predicate_objects(identifier)) == {
        (RDF.type, generator.ATLAS.Identifier),
        (
            generator.ATLAS.identifierValue,
            generator.Literal("ONE-001", datatype=generator.XSD.string),
        ),
        (generator.ATLAS.identifierScheme, identifier_scheme),
        (generator.ATLAS.identifies, resource),
        (generator.ATLAS.sourceRecord, source_record),
        (
            generator.ATLAS.contentDigest,
            generator.Literal(
                generator.ATLAS_VALIDATE.rdf_node_digest(
                    graphs.asserted,
                    identifier,
                )
            ),
        ),
    }
    assert generator._counts(graphs)["identifiers"] == 1


def test_build_graphs_rejects_one_authority_identifier_for_two_resources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resource_scheme = URIRef("urn:test:scheme:codes")
    identifier_scheme = URIRef("urn:test:scheme:identifiers")
    descriptor_graph = generator._new_build_graph()
    for scheme, profile in (
        (resource_scheme, generator.ATLAS.codeScheme),
        (identifier_scheme, generator.ATLAS.identifierScheme),
    ):
        descriptor_graph.add((scheme, RDF.type, generator.ATLAS.ResourceScheme))
        descriptor_graph.add((scheme, generator.ATLAS.resourceProfile, profile))
    descriptor_graph.add(
        (resource_scheme, generator.ATLAS.supportedRing, generator.ATLAS.value)
    )
    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        lambda: descriptor_graph,
    )

    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    source_digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    identifier = generator.RegistryIdentifier(
        value="DUPLICATE-001",
        scheme_iri=str(identifier_scheme),
        source_path="source.json#identifier",
    )
    release = generator._adapt_registry_release(
        RegistryRelease(
            key="identifier-uniqueness-test",
            resource_id="identifier-uniqueness-test",
            source_module="refspec.registry.test",
            profile="codeScheme",
            ring="value",
            scope="completeCapture",
            source_release_iri="urn:test:source-release",
            source_release_digest=source_digest,
            atlas_release_iri="urn:test:atlas-release",
            scheme_iri=str(resource_scheme),
            issued="2026-08-06",
            inputs=(
                RegistryInputPin(
                    path=source,
                    logical_path="source.json",
                    sha256=source_digest,
                    byte_length=source.stat().st_size,
                    source_iri="urn:test:source",
                ),
            ),
            resources=tuple(
                RegistryResource(
                    iri=f"urn:test:resource:{ordinal}",
                    labels=(
                        RegistryLabel(
                            value=f"Resource {ordinal}",
                            role="preferred",
                            source_path=f"source.json#row={ordinal}.label",
                        ),
                    ),
                    native_payload={"ordinal": ordinal},
                    source_locator=f"urn:test:source-row:{ordinal}",
                    source_digest=source_digest,
                    identifiers=(identifier,),
                )
                for ordinal in (1, 2)
            ),
        )
    )

    with pytest.raises(
        ValueError,
        match="authority-scoped identifier resolves to multiple resources",
    ):
        generator._build_graphs((release,))


@pytest.mark.parametrize(
    ("scheme_type", "scheme_profile"),
    (
        (None, generator.ATLAS.identifierScheme),
        (generator.ATLAS.ResourceScheme, generator.ATLAS.codeScheme),
    ),
)
def test_identifier_emission_rejects_non_identifier_schemes(
    scheme_type: URIRef | None,
    scheme_profile: URIRef,
) -> None:
    graph = generator._new_build_graph()
    scheme = URIRef("urn:test:scheme:not-an-identifier-authority")
    if scheme_type is not None:
        graph.add((scheme, RDF.type, scheme_type))
    graph.add((scheme, generator.ATLAS.resourceProfile, scheme_profile))

    with pytest.raises(ValueError, match="atlas:identifierScheme profile"):
        generator._add_identifier(
            graph,
            identifier_row=generator.RegistryIdentifier(
                value="ONE-001",
                scheme_iri=str(scheme),
                source_path="source.json#identifier",
            ),
            resource=URIRef("urn:test:resource"),
            source_record=URIRef("urn:test:source-record"),
        )


def test_real_document_releases_emit_identifiers_and_cross_ring_assignment(
    document_releases,
) -> None:
    releases = document_releases
    assert generator._direct_source_counts(releases, label_count=1_060) == {
        "crossRingRelations": 1,
        "identifiers": 1_059,
        "labels": 1_060,
        "nativeRelations": 0,
        "resources": 1_060,
    }
    assert [generator._release_direct_source_counts(release) for release in releases] == [
        {
            "crossRingRelations": 0,
            "identifiers": 1_058,
            "nativeRelations": 0,
            "resources": 1_058,
        },
        {
            "crossRingRelations": 1,
            "identifiers": 1,
            "nativeRelations": 0,
            "resources": 1,
        },
        {
            "crossRingRelations": 0,
            "identifiers": 0,
            "nativeRelations": 0,
            "resources": 1,
        },
    ]
    graphs = generator._build_graphs(releases)
    report = URIRef("https://www.gao.gov/products/gao-26-108505")
    topic = next(
        resource
        for resource in graphs.asserted.subjects(
            RDF.type,
            generator.ATLAS.SubjectConcept,
        )
    )
    assertions = set(
        graphs.asserted.subjects(
            RDF.type,
            generator.ATLAS.CrossRingRelationAssertion,
        )
    )

    assert generator._counts(graphs)["identifiers"] == 1_059
    assert generator._counts(graphs)["crossRingRelationAssertions"] == 1
    assert len(assertions) == 1
    assertion = next(iter(assertions))
    assert graphs.asserted.value(assertion, RDF.subject) == report
    assert graphs.asserted.value(assertion, RDF.predicate) == (
        generator.ATLAS.hasIndexedSubject
    )
    assert graphs.asserted.value(assertion, RDF.object) == topic
    assert graphs.asserted.value(assertion, generator.ATLAS.sourceRing) == (
        generator.ATLAS.entity
    )
    assert graphs.asserted.value(assertion, generator.ATLAS.targetRing) == (
        generator.ATLAS.subject
    )
    assert (report, generator.ATLAS.hasIndexedSubject, topic) in graphs.projection
