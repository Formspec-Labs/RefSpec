from __future__ import annotations

import dataclasses
import hashlib
import importlib
import io
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from refspec.atlas.v3_source_data import (
    RegistryInputPin,
    RegistryLabel,
    RegistryMapping,
    RegistryMappingEvidence,
    RegistryMappingRelease,
    RegistryRelease,
    RegistryResource,
    RegistrySupplementalSourceRecord,
    mapping_triple_digest,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
generator = importlib.import_module("generate_atlas_v3_full")


def test_status_reporter_rate_limits_progress_and_keeps_phase_boundaries() -> None:
    ticks = iter((100.0, 100.0, 101.0, 116.0, 117.0))
    stream = io.StringIO()
    reporter = generator._StatusReporter(
        enabled=True,
        stream=stream,
        interval_seconds=15.0,
        clock=lambda: next(ticks),
    )

    reporter.phase("load")
    reporter.progress("construct", 1, 3, current="release-one")
    reporter.progress("construct", 2, 3, current="release-two")
    reporter.progress("construct", 3, 3, current="release-three")

    lines = stream.getvalue().splitlines()
    assert len(lines) == 3
    assert lines[0] == 'atlas-build elapsed=0.0s phase="load"'
    assert "progress=1/3" not in stream.getvalue()
    assert 'progress=2/3 current="release-two"' in lines[1]
    assert 'progress=3/3 current="release-three"' in lines[2]


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
        "mode": generator._COMPILED_PRODUCER_MODE,
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


def _test_release_plan() -> generator.ReleasePackPlan:
    return generator.ReleasePackPlan(
        key="unit-test-release",
        source_release_iri="urn:test:source-release",
        atlas_release_iri="urn:test:atlas-release",
        ring="subject",
        resource_count=0,
    )


def _test_construction_seed() -> generator.ReleaseConstructionSeed:
    adapter_path = ROOT / "src" / "refspec" / "atlas" / "v3_source_data.py"
    return generator.ReleaseConstructionSeed(
        key="unit-test-release",
        source_release_iri="urn:test:source-release",
        atlas_release_iri="urn:test:atlas-release",
        ring="subject",
        input_pins=(
            {
                "byteLength": 1,
                "path": "tests/unit-test-source.txt",
                "role": "registrySource",
                "sha256": "sha256:" + "1" * 64,
                "sourceIri": "urn:test:source-artifact",
            },
        ),
        adapter_recipe_inputs=(
            {
                "byteLength": adapter_path.stat().st_size,
                "path": adapter_path.relative_to(ROOT).as_posix(),
                "sha256": generator._sha256_file(adapter_path),
            },
        ),
        resource_profile="conceptScheme",
        scheme_iri="urn:test:scheme",
    )


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
    graphs = _receipted_test_graphs()

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
        releases=(_test_release_plan(),),
        compiled_validation=compiled_validation,
        construction_seeds=(_test_construction_seed(),),
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
    assert result["packMaterialization"] == {
        "currentCanonicalPackContent": "fullyRecomputedAndSorted",
        "graphConstruction": "fullRebuildRequiredByCompiledProducerProof",
        "mode": "incrementalPackMaterialization",
        "priorDistribution": "notProvided",
        "rebuiltPackCount": 2,
        "rebuiltPacks": [
            "packs/catalog.nq.zst",
            "packs/sources/unit-test-release/all.nq.zst",
        ],
        "reuseCriterion": "contentDigestByteLengthAndQuadCount",
        "reusedPackCount": 0,
        "reusedPacks": [],
    }
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


def _receipted_test_graphs() -> generator.BuildGraphs:
    asserted = generator._new_build_graph()
    asserted.add(
        (
            URIRef("urn:test:subject"),
            URIRef("urn:test:predicate"),
            URIRef("urn:test:object"),
        )
    )
    generator._add_source_release(
        asserted,
        identifier="urn:test:source-release",
        digest="sha256:" + "2" * 64,
        issued="2026-08-06",
        locator=URIRef("urn:test:source-artifact"),
    )
    atlas_release = URIRef("urn:test:atlas-release")
    asserted.add((atlas_release, RDF.type, generator.ATLAS.AtlasRelease))
    asserted.add((atlas_release, generator.ATLAS.resourceProfile, generator.ATLAS.conceptScheme))
    asserted.add((atlas_release, generator.ATLAS.semanticRing, generator.ATLAS.subject))
    asserted.add((atlas_release, generator.ATLAS.inScheme, URIRef("urn:test:scheme")))
    asserted.add(
        (atlas_release, generator.ATLAS.membershipMode, generator.ATLAS.completeMembership)
    )
    asserted.add((atlas_release, generator.DCTERMS.identifier, Literal("unit-test-release")))
    asserted.add(
        (
            atlas_release,
            generator.DCTERMS.issued,
            Literal("2026-08-06", datatype=generator.XSD.date),
        )
    )
    generator._add_content_digest(asserted, atlas_release)
    return generator.BuildGraphs(
        asserted=asserted,
        projection=generator._new_build_graph(),
        derived=generator._new_build_graph(),
        accounting=_compiled_test_accounting(),
    )


def _write_receipted_test_candidate(tmp_path: Path, monkeypatch) -> dict:
    graphs = _receipted_test_graphs()
    _, manifest = generator._write_candidate_distribution(
        tmp_path,
        graphs,
        releases=(_test_release_plan(),),
        compiled_validation=_compiled_test_report(graphs),
        construction_seeds=(_test_construction_seed(),),
    )
    return manifest


def _write_exact_reuse_test_distribution(
    tmp_path: Path,
) -> tuple[Path, dict[str, Path]]:
    input_paths = {
        generator.REGISTRY_DESCRIPTORS_PROOF_LOGICAL_PATH: (
            generator.REGISTRY_DESCRIPTORS_PROOF
        ),
        generator.REGISTRY_DESCRIPTORS_LOGICAL_PATH: generator.REGISTRY_DESCRIPTORS,
        "tests/exact-reuse/source.txt": tmp_path / "source.txt",
        "src/refspec/atlas/v3_source_data.py": (
            ROOT / "src" / "refspec" / "atlas" / "v3_source_data.py"
        ),
    }
    input_paths["tests/exact-reuse/source.txt"].write_text(
        "tests/exact-reuse/source.txt\n",
        encoding="utf-8",
    )

    def pin(logical_path: str) -> dict[str, object]:
        path = input_paths[logical_path]
        return {
            "byteLength": path.stat().st_size,
            "path": logical_path,
            "sha256": generator._sha256_file(path),
        }

    descriptor_pin = pin(generator.REGISTRY_DESCRIPTORS_LOGICAL_PATH)
    descriptor_proof_pin = pin(generator.REGISTRY_DESCRIPTORS_PROOF_LOGICAL_PATH)
    source_pin = pin("tests/exact-reuse/source.txt")
    inventory = {
        "expectedResources": 1,
        "mappingSources": [],
        "registryDescriptors": 1,
        "registryDescriptorsPin": {
            "byteLength": descriptor_pin["byteLength"],
            "digest": descriptor_pin["sha256"],
            "path": descriptor_pin["path"],
        },
        "registryDescriptorsProofPin": {
            "byteLength": descriptor_proof_pin["byteLength"],
            "digest": descriptor_proof_pin["sha256"],
            "path": descriptor_proof_pin["path"],
        },
        "sources": [
            {
                "inputs": [source_pin],
                "key": "exact-reuse-source",
            }
        ],
    }
    semantic_construction = generator._semantic_construction_receipt(
        inventory,
        (
            dataclasses.replace(
                _test_construction_seed(),
                input_pins=(
                    {
                        **source_pin,
                        "role": "registrySource",
                        "sourceIri": "urn:test:source-artifact",
                    },
                ),
            ),
        ),
    )
    construction_seed = dataclasses.replace(
        _test_construction_seed(),
        input_pins=(
            {
                **source_pin,
                "role": "registrySource",
                "sourceIri": "urn:test:source-artifact",
            },
        ),
    )
    graphs = _receipted_test_graphs()
    output = tmp_path / "distribution"
    generator._write_distribution(
        output,
        graphs,
        releases=(_test_release_plan(),),
        construction_seeds=(construction_seed,),
        generation_report={
            "inputInventory": inventory,
            "semanticConstruction": semantic_construction,
            "type": "AtlasGenerationReport",
            "version": "test",
        },
        compiled_validation=_compiled_test_report(graphs),
    )
    return output, input_paths


def test_exact_distribution_reuse_skips_all_semantic_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, input_paths = _write_exact_reuse_test_distribution(tmp_path)
    monkeypatch.setattr(
        generator,
        "_resolve_semantic_input_path",
        lambda logical_path: input_paths[logical_path],
    )

    def forbidden(*args, **kwargs):
        pytest.fail("exact distribution reuse entered semantic construction")

    for name in (
        "load_releases",
        "load_mapping_releases",
        "_build_graphs",
        "_write_sorted_lines",
        "_compress_nquads",
    ):
        monkeypatch.setattr(generator, name, forbidden)

    generator.build_distribution(output)

    report = json.loads((output.parent / "generation-report.json").read_bytes())
    reuse = report["exactDistributionReuse"]
    assert reuse["mode"] == "exactDistributionReuse"
    assert reuse["reuseScope"] == "wholeDistributionExactInputsOnly"
    assert reuse["semanticWorkSkipped"] == [
        "sourceParsing",
        "normalizedRowValidationAndGlobalJoins",
        "rdfGraphConstruction",
        "compactRecordConstruction",
        "canonicalSorting",
        "packCompression",
    ]


def test_exact_distribution_reuse_copies_a_verified_prior_distribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior, input_paths = _write_exact_reuse_test_distribution(tmp_path)
    output = tmp_path / "copied" / "distribution"
    monkeypatch.setattr(
        generator,
        "_resolve_semantic_input_path",
        lambda logical_path: input_paths[logical_path],
    )

    result = generator._try_exact_distribution_reuse(
        output,
        reuse_from=prior,
    )

    assert result is not None
    assert result["mode"] == "exactDistributionReuse"
    assert (output / "atlas-manifest.json").read_bytes() == (
        prior / "atlas-manifest.json"
    ).read_bytes()
    assert json.loads(
        (output.parent / "generation-report.json").read_bytes()
    )["distribution"]["path"] == "distribution"


def test_exact_distribution_reuse_fails_closed_on_changed_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, input_paths = _write_exact_reuse_test_distribution(tmp_path)
    monkeypatch.setattr(
        generator,
        "_resolve_semantic_input_path",
        lambda logical_path: input_paths[logical_path],
    )
    input_paths["tests/exact-reuse/source.txt"].write_text(
        "changed exact source\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        generator,
        "load_releases",
        lambda: pytest.fail("changed input must fail before source parsing"),
    )

    with pytest.raises(ValueError, match="pinned Atlas input drifted"):
        generator.build_distribution(output)


@pytest.mark.parametrize("incompatibility", ("recipe", "binding"))
def test_exact_distribution_reuse_incompatibility_enters_full_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    incompatibility: str,
) -> None:
    output, input_paths = _write_exact_reuse_test_distribution(tmp_path)
    monkeypatch.setattr(
        generator,
        "_resolve_semantic_input_path",
        lambda logical_path: input_paths[logical_path],
    )
    if incompatibility == "recipe":
        monkeypatch.setattr(
            generator,
            "_shared_semantic_recipe_digest",
            lambda: "sha256:" + "0" * 64,
        )
    else:
        changed_binding = dict(generator._COMPILED_PRODUCER_BINDING_PINS)
        changed_binding["bindingBundleDigest"] = "sha256:" + "0" * 64
        monkeypatch.setattr(
            generator,
            "_validate_compiled_binding_profile",
            lambda: changed_binding,
        )

    def full_build_entered(**_kwargs: object) -> None:
        raise RuntimeError("full semantic rebuild entered")

    monkeypatch.setattr(generator, "load_releases", full_build_entered)
    with pytest.raises(RuntimeError, match="full semantic rebuild entered"):
        generator.build_distribution(output)


def test_incremental_planner_receipts_shared_paths_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_calls: list[str] = []
    adapter_calls: list[str] = []

    def source_receipt(pin: Mapping[str, object]) -> dict[str, object]:
        source_calls.append(str(pin["path"]))
        return {
            "byteLength": 7,
            "path": pin["path"],
            "role": pin["role"],
            "sha256": "sha256:" + "1" * 64,
            "sourceIri": pin["sourceIri"],
        }

    def adapter_receipt(pin: Mapping[str, object]) -> dict[str, object]:
        adapter_calls.append(str(pin["path"]))
        return {
            "byteLength": 11,
            "path": pin["path"],
            "sha256": "sha256:" + "2" * 64,
        }

    monkeypatch.setattr(generator, "_current_preparse_input_pin", source_receipt)
    monkeypatch.setattr(
        generator,
        "_current_adapter_recipe_input",
        adapter_receipt,
    )
    raw_pin = {
        "byteLength": 7,
        "path": "research/evidence/shared-source.bin",
        "role": "registrySource",
        "sha256": "sha256:" + "0" * 64,
        "sourceIri": "urn:test:shared-source",
    }
    adapter_pin = {
        "byteLength": 11,
        "path": "src/refspec/registry/shared_parser.py",
        "sha256": "sha256:" + "0" * 64,
    }

    def release_row(key: str) -> dict[str, object]:
        return {
            "adapterRecipeInputs": [adapter_pin],
            "atlasRelease": f"urn:test:atlas-release:{key}",
            "endpointDependencies": [],
            "inputs": [raw_pin],
            "key": key,
            "kind": "sourceRelease",
            "resourceProfile": "conceptScheme",
            "scheme": "urn:test:scheme",
            "semanticRing": "subject",
            "sourceRelease": f"urn:test:source-release:{key}",
        }

    seeds = generator._current_construction_seeds_from_summary(
        {"releases": [release_row("first"), release_row("second")]}
    )

    assert [seed.key for seed in seeds] == ["first", "second"]
    assert source_calls == [raw_pin["path"]]
    assert adapter_calls == [adapter_pin["path"]]


def test_incremental_pack_materialization_reuses_only_exact_current_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = tmp_path / "prior"
    candidate = tmp_path / "candidate"
    prior_manifest = _write_receipted_test_candidate(prior, monkeypatch)
    prior_transports = {
        pack["path"]: (prior / pack["path"]).read_bytes()
        for pack in prior_manifest["packs"]
    }
    compression_calls: list[Path] = []
    original_compress = generator._compress_nquads

    def counted_compress(source: Path, target: Path) -> generator.PackWriteReceipt:
        compression_calls.append(target)
        return original_compress(source, target)

    monkeypatch.setattr(generator, "_compress_nquads", counted_compress)
    graphs = _receipted_test_graphs()
    result, manifest = generator._write_candidate_distribution(
        candidate,
        graphs,
        releases=(_test_release_plan(),),
        compiled_validation=_compiled_test_report(graphs),
        construction_seeds=(_test_construction_seed(),),
        reuse_from=prior,
    )

    pack_report = result["packMaterialization"]
    assert compression_calls == []
    assert pack_report == {
        "currentCanonicalPackContent": "fullyRecomputedAndSorted",
        "graphConstruction": "fullRebuildRequiredByCompiledProducerProof",
        "mode": "incrementalPackMaterialization",
        "priorDistribution": "closedManifestAndMembersVerified",
        "priorDistributionId": prior_manifest["distributionId"],
        "priorManifestDigest": generator._sha256_file(
            prior / "atlas-manifest.json"
        ),
        "rebuiltPackCount": 0,
        "rebuiltPacks": [],
        "reuseCriterion": "contentDigestByteLengthAndQuadCount",
        "reusedPackCount": 2,
        "reusedPacks": [
            "packs/catalog.nq.zst",
            "packs/sources/unit-test-release/all.nq.zst",
        ],
    }
    assert all(
        (candidate / pack["path"]).read_bytes() == prior_transports[pack["path"]]
        for pack in manifest["packs"]
    )
    assert manifest == prior_manifest


def test_release_local_incremental_construction_skips_clean_parser_and_matches_cold_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One dirty source rebuilds while clean sources and mapping stay packed."""

    monkeypatch.setattr(generator, "_registry_asserted_graph", _compiled_descriptor_graph)
    observed_binding = generator.ATLAS_VALIDATE._binding_digests()
    monkeypatch.setattr(
        generator.ATLAS_VALIDATE,
        "_binding_digests",
        lambda: dict(observed_binding),
    )
    monkeypatch.setattr(
        generator,
        "_COMPILED_PRODUCER_BINDING_PINS",
        generator.MappingProxyType(
            {
                field: observed_binding[field]
                for field in generator._COMPILED_PRODUCER_BINDING_PINS
            }
        ),
    )
    monkeypatch.setattr(
        generator,
        "_validate_compiled_binding_profile",
        lambda: dict(generator._COMPILED_PRODUCER_BINDING_PINS),
    )
    mapped_releases, mapping_release = _compiled_mapping_case(tmp_path)
    third_resource = dataclasses.replace(
        mapped_releases[0].resources[0],
        iri="urn:test:resource:third",
        labels=(
            generator.SourceLabel(
                value="Third",
                language="en",
                role="preferred",
                source_path="source-third.json#label",
            ),
        ),
        native_payload={"id": "third"},
        source_locator="urn:test:source-row:third",
    )
    cross_release_relation = generator.SourceRelation(
        subject=third_resource.iri,
        predicate=str(generator.SKOS.related),
        object=mapped_releases[0].resources[0].iri,
        source_payload={"sourcePath": "source-third.json#related"},
    )
    base_releases = (
        *mapped_releases,
        dataclasses.replace(
            mapped_releases[0],
            spec=dataclasses.replace(
                mapped_releases[0].spec,
                key="compiled-source-third",
                expected_relations=1,
            ),
            resources=(third_resource,),
            relations=(cross_release_relation,),
        ),
    )
    source_paths = {
        "compiled-source-first": tmp_path / "source-first.json",
        "compiled-source-second": tmp_path / "source-second.json",
        "compiled-source-third": tmp_path / "source-third.json",
    }
    for key, path in source_paths.items():
        path.write_text('{"key":"' + key + '","revision":1}\n', encoding="utf-8")

    def release_for_source(
        release: generator.LoadedRelease,
    ) -> generator.LoadedRelease:
        path = source_paths[release.spec.key]
        digest = generator._sha256_file(path)
        token = digest.removeprefix("sha256:")
        return dataclasses.replace(
            release,
            spec=dataclasses.replace(
                release.spec,
                path=path,
                logical_path=f"tests/incremental/{path.name}",
                expected_digest=digest,
                source_module="refspec.atlas.v3_source_data",
            ),
            source_release_iri=f"urn:test:source-release:{release.spec.key}:{token}",
            source_release_digest=digest,
            atlas_release_iri=f"urn:test:atlas-release:{release.spec.key}:{token}",
            resources=tuple(
                dataclasses.replace(resource, source_digest=digest)
                for resource in release.resources
            ),
        )

    initial_releases = tuple(release_for_source(release) for release in base_releases)
    mapping_release = dataclasses.replace(
        mapping_release,
        mappings=(
            dataclasses.replace(
                mapping_release.mappings[0],
                subject_atlas_release_iri=initial_releases[0].atlas_release_iri,
                object_atlas_release_iri=initial_releases[1].atlas_release_iri,
            ),
        ),
    )
    all_keys = frozenset(
        {
            *(release.spec.key for release in initial_releases),
            mapping_release.key,
        }
    )
    monkeypatch.setattr(generator, "_declared_construction_unit_keys", lambda: all_keys)
    original_resolver = generator._resolve_semantic_input_path
    logical_inputs = {
        **{
            release.spec.logical_path: release.spec.path
            for release in initial_releases
        },
        **{
            pin.logical_path: pin.path for pin in mapping_release.inputs
        },
    }

    def resolve(logical_path: str) -> Path:
        return logical_inputs.get(logical_path, original_resolver(logical_path))

    monkeypatch.setattr(generator, "_resolve_semantic_input_path", resolve)

    def write_cold(
        output: Path,
        releases: tuple[generator.LoadedRelease, ...],
    ) -> None:
        mappings = (mapping_release,)
        inventory = generator.verify_inputs(releases, mappings)
        row_receipt = generator._validate_compiled_producer_rows(releases, mappings)
        plans = generator._release_pack_plans(releases, mappings)
        seeds = generator._release_construction_seeds(releases, mappings)
        semantic = generator._semantic_construction_receipt(inventory, seeds)
        graphs = generator._build_graphs(
            releases,
            mapping_releases=mappings,
            include_projection=False,
        )
        compiled = generator._validate_compiled_producer_output(
            releases,
            graphs,
            row_receipt,
            mappings,
        )
        generator._write_distribution(
            output,
            graphs,
            releases=plans,
            construction_seeds=seeds,
            generation_report={
                "inputInventory": inventory,
                "semanticConstruction": semantic,
                "type": "AtlasGenerationReport",
                "version": "test",
            },
            compiled_validation=compiled,
        )

    prior = tmp_path / "prior" / "distribution"
    write_cold(prior, initial_releases)

    dirty_key = "compiled-source-third"
    source_paths[dirty_key].write_text(
        '{"key":"compiled-source-third","revision":2}\n',
        encoding="utf-8",
    )
    current_releases = tuple(release_for_source(release) for release in base_releases)
    current_by_key = {release.spec.key: release for release in current_releases}
    source_loader_calls: list[frozenset[str] | None] = []
    mapping_loader_calls: list[frozenset[str] | None] = []

    def load_sources(
        include_keys: frozenset[str] | None = None,
    ) -> tuple[generator.LoadedRelease, ...]:
        source_loader_calls.append(include_keys)
        assert include_keys is not None
        return tuple(current_by_key[key] for key in sorted(include_keys))

    def load_mappings(
        include_keys: frozenset[str] | None = None,
    ) -> tuple[RegistryMappingRelease, ...]:
        mapping_loader_calls.append(include_keys)
        assert include_keys == frozenset()
        return ()

    monkeypatch.setattr(generator, "load_releases", load_sources)
    monkeypatch.setattr(generator, "load_mapping_releases", load_mappings)
    compact_roles_read: list[str] = []
    original_compact_reader = generator.read_compact_record_pack

    def counted_compact_reader(
        root: Path,
        descriptor: Mapping[str, object],
    ):
        compact_roles_read.append(str(descriptor["role"]))
        return original_compact_reader(root, descriptor)

    monkeypatch.setattr(
        generator,
        "read_compact_record_pack",
        counted_compact_reader,
    )
    incremental = tmp_path / "incremental" / "distribution"
    generator.build_distribution(incremental, reuse_from=prior)

    assert source_loader_calls == [frozenset({dirty_key})]
    assert mapping_loader_calls == [frozenset()]
    assert "compiled-source-second" not in source_loader_calls[0]
    assert set(compact_roles_read) <= {
        "Identifier",
        "Release",
        "Resource",
        "Statement",
    }
    assert {"Release", "Resource", "Statement"} <= set(compact_roles_read)

    incremental_manifest = json.loads(
        (incremental / "atlas-manifest.json").read_bytes()
    )
    clean_release = current_by_key["compiled-source-first"]
    dirty_release = current_by_key[dirty_key]
    clean_rdf_pack = next(
        pack
        for pack in incremental_manifest["packs"]
        if pack["sourceReleases"] == [clean_release.source_release_iri]
    )
    dirty_rdf_pack = next(
        pack
        for pack in incremental_manifest["packs"]
        if pack["sourceReleases"] == [dirty_release.source_release_iri]
    )
    assert clean_rdf_pack["packId"] in dirty_rdf_pack["dependencies"]
    incremental_summary = json.loads(
        (incremental / "atlas-construction-summary.json").read_bytes()
    )
    compact_by_path = {
        pack["path"]: pack for pack in incremental_summary["compactPacks"]
    }
    rows_by_key = {row["key"]: row for row in incremental_summary["releases"]}
    dirty_statement_pack = next(
        compact_by_path[path]
        for path in rows_by_key[dirty_key]["compactPackPaths"]
        if compact_by_path[path]["role"] == "Statement"
    )
    clean_resource_pack = next(
        compact_by_path[path]
        for path in rows_by_key["compiled-source-first"]["compactPackPaths"]
        if compact_by_path[path]["role"] == "Resource"
    )
    assert clean_resource_pack["packId"] in dirty_statement_pack["dependencies"]

    cold = tmp_path / "cold" / "distribution"
    write_cold(cold, current_releases)
    declared_paths = {
        "atlas-manifest.json",
        *(member["path"] for member in incremental_manifest["members"]),
        *(pack["path"] for pack in incremental_manifest["packs"]),
        *(
            pack["path"]
            for pack in json.loads(
                (incremental / "atlas-construction-summary.json").read_bytes()
            )["compactPacks"]
        ),
    }
    assert all(
        (incremental / path).read_bytes() == (cold / path).read_bytes()
        for path in declared_paths
    )
    assert {
        path.relative_to(incremental).as_posix()
        for path in incremental.rglob("*")
        if path.is_file()
    } == declared_paths


def test_incremental_generation_report_accounts_for_mapping_releases() -> None:
    source_plan = generator.ReleasePackPlan(
        key="source-release",
        source_release_iri="urn:test:source-release:source",
        atlas_release_iri="urn:test:atlas-release:source",
        ring="subject",
        resource_count=3,
    )
    mapping_plan = generator.ReleasePackPlan(
        key="mapping-release",
        source_release_iri="urn:test:source-release:mapping",
        atlas_release_iri=None,
        ring="subject",
        resource_count=2,
        kind="mapping",
    )
    report = generator._incremental_generation_report(
        counts={
            "crossRingRelationAssertions": 0,
            "identifiers": 0,
            "labels": 3,
            "mappingAssertions": 2,
            "nativeRelationAssertions": 0,
            "resources": 3,
        },
        english_only_scan={},
        inventory={"mappingSources": [], "sources": []},
        plans=(source_plan, mapping_plan),
        reuse=SimpleNamespace(
            prior_summary={
                "releases": [
                    {
                        "key": "mapping-release",
                        "recordCounts": {
                            "evidenceBindings": 3,
                            "statements": 2,
                        },
                    }
                ]
            },
            report=lambda: {"status": "passed"},
        ),
        semantic_construction={},
    )

    assert len(report["mappingReleases"]) == 1
    assert report["mappingReleases"][0] == {
        "evidenceBindingCount": 3,
        "key": "mapping-release",
        "mappingCount": 2,
        "sourceRelease": "urn:test:source-release:mapping",
    }
    assert [row["key"] for row in report["sourceReleases"]] == ["source-release"]


def test_incremental_pack_materialization_rebuilds_changed_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = tmp_path / "prior"
    candidate = tmp_path / "candidate"
    _write_receipted_test_candidate(prior, monkeypatch)
    compression_calls: list[Path] = []
    original_compress = generator._compress_nquads

    def counted_compress(source: Path, target: Path) -> generator.PackWriteReceipt:
        compression_calls.append(target)
        return original_compress(source, target)

    monkeypatch.setattr(generator, "_compress_nquads", counted_compress)
    graphs = _receipted_test_graphs()
    graphs.asserted.add(
        (
            URIRef("urn:test:changed"),
            URIRef("urn:test:predicate"),
            URIRef("urn:test:object"),
        )
    )
    result, _ = generator._write_candidate_distribution(
        candidate,
        graphs,
        releases=(_test_release_plan(),),
        compiled_validation=_compiled_test_report(graphs),
        construction_seeds=(_test_construction_seed(),),
        reuse_from=prior,
    )

    assert len(compression_calls) == 1
    assert result["packMaterialization"]["reusedPackCount"] == 1
    assert result["packMaterialization"]["rebuiltPackCount"] == 1
    assert result["packMaterialization"]["rebuiltPacks"] == [
        "packs/catalog.nq.zst"
    ]


def test_incremental_pack_materialization_rejects_tampered_prior_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = tmp_path / "prior"
    candidate = tmp_path / "candidate"
    manifest = _write_receipted_test_candidate(prior, monkeypatch)
    prior_pack = prior / manifest["packs"][0]["path"]
    payload = bytearray(prior_pack.read_bytes())
    payload[len(payload) // 2] ^= 1
    prior_pack.write_bytes(payload)
    graphs = _receipted_test_graphs()

    with pytest.raises(ValueError, match="prior stored pack transport differs"):
        generator._write_candidate_distribution(
            candidate,
            graphs,
            releases=(_test_release_plan(),),
            compiled_validation=_compiled_test_report(graphs),
            construction_seeds=(_test_construction_seed(),),
            reuse_from=prior,
        )


def test_incremental_pack_materialization_rejects_unsafe_prior_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = tmp_path / "prior"
    candidate = tmp_path / "candidate"
    manifest = _write_receipted_test_candidate(prior, monkeypatch)
    prior_pack = prior / manifest["packs"][0]["path"]
    outside = tmp_path / "outside-pack.nq.zst"
    prior_pack.rename(outside)
    prior_pack.symlink_to(outside)
    graphs = _receipted_test_graphs()

    with pytest.raises(Exception, match="unsafe symlink"):
        generator._write_candidate_distribution(
            candidate,
            graphs,
            releases=(_test_release_plan(),),
            compiled_validation=_compiled_test_report(graphs),
            construction_seeds=(_test_construction_seed(),),
            reuse_from=prior,
        )


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
        "mappingSources",
        "registryDescriptors",
        "registryDescriptorsPin",
        "registryDescriptorsProofPin",
        "sources",
    }
    assert inventory["mappingSources"] == []
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


def _clean_validation_state(
    release: generator.LoadedRelease,
) -> generator.CleanConstructionState:
    return generator.CleanConstructionState(
        resources={
            resource.iri: (
                release.spec.key,
                URIRef(release.atlas_release_iri),
                generator.ATLAS[release.spec.ring],
            )
            for resource in release.resources
        },
        identifier_targets={},
        compact_subject_pack_ids={},
        rdf_subject_owners={},
        statement_type_counts={},
        mapping_policy_iris=frozenset(),
        relation_triples={},
    )


def test_shared_row_validator_rejects_malformed_dirty_label_in_cold_and_incremental(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generator, "_registry_asserted_graph", _compiled_descriptor_graph)
    monkeypatch.setattr(
        generator,
        "_validate_compiled_binding_profile",
        lambda: dict(generator._COMPILED_PRODUCER_BINDING_PINS),
    )
    releases, _ = _compiled_mapping_case(tmp_path)
    dirty, clean = releases
    malformed_label = dataclasses.replace(
        dirty.resources[0].labels[0],
        source_path="",
    )
    dirty = dataclasses.replace(
        dirty,
        resources=(
            dataclasses.replace(dirty.resources[0], labels=(malformed_label,)),
        ),
    )
    with pytest.raises(ValueError, match="invalid English label row"):
        generator._validate_compiled_producer_rows((dirty, clean))
    with pytest.raises(ValueError, match="invalid English label row"):
        generator._validate_compiled_producer_rows(
            (dirty,),
            clean_state=_clean_validation_state(clean),
            clean_seeds=generator._release_construction_seeds((clean,)),
        )


def test_shared_row_validator_rejects_duplicate_cross_ring_claims_across_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    releases, _ = _compiled_mapping_case(tmp_path)
    dirty, clean = releases
    entity_scheme = URIRef("urn:test:scheme:entities")
    monkeypatch.setattr(
        generator,
        "_validate_compiled_binding_profile",
        lambda: dict(generator._COMPILED_PRODUCER_BINDING_PINS),
    )

    def descriptor_graph() -> Graph:
        graph = _compiled_descriptor_graph()
        graph.add((entity_scheme, RDF.type, generator.ATLAS.ResourceScheme))
        graph.add(
            (
                entity_scheme,
                generator.ATLAS.resourceProfile,
                generator.ATLAS.conceptScheme,
            )
        )
        graph.add(
            (
                entity_scheme,
                generator.ATLAS.supportedRing,
                generator.ATLAS.entity,
            )
        )
        return graph

    monkeypatch.setattr(generator, "_registry_asserted_graph", descriptor_graph)
    relation = generator.RegistryCrossRingRelation(
        subject=dirty.resources[0].iri,
        predicate=str(generator.ATLAS.hasIndexedSubject),
        object=clean.resources[0].iri,
        source_ring="entity",
        target_ring="subject",
        source_payload={"sourcePath": "dirty#subject"},
    )
    dirty_with_duplicate_rows = dataclasses.replace(
        dirty,
        spec=dataclasses.replace(
            dirty.spec,
            ring="entity",
            expected_cross_ring_relations=2,
        ),
        scheme_iri=str(entity_scheme),
        cross_ring_relations=(relation, relation),
    )
    message = "cross-ring relation duplicates another relation"
    with pytest.raises(ValueError, match=message):
        generator._validate_compiled_producer_rows((dirty_with_duplicate_rows, clean))

    dirty = dataclasses.replace(
        dirty,
        spec=dataclasses.replace(
            dirty.spec,
            ring="entity",
            expected_cross_ring_relations=1,
        ),
        scheme_iri=str(entity_scheme),
        cross_ring_relations=(relation,),
    )
    triple = (
        URIRef(relation.subject),
        URIRef(relation.predicate),
        URIRef(relation.object),
    )
    clean_state = dataclasses.replace(
        _clean_validation_state(clean),
        relation_triples={triple: ()},
    )
    with pytest.raises(ValueError, match=message):
        generator._validate_compiled_producer_rows(
            (dirty,),
            clean_state=clean_state,
            clean_seeds=generator._release_construction_seeds((clean,)),
        )


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


def _compiled_mapping_case(
    tmp_path: Path,
) -> tuple[tuple[generator.LoadedRelease, ...], RegistryMappingRelease]:
    base = _compiled_source_release(tmp_path)
    releases = (
        dataclasses.replace(
            base,
            spec=dataclasses.replace(
                base.spec,
                key="compiled-source-first",
                expected_resources=1,
                expected_relations=0,
            ),
            source_release_iri="urn:test:source-release:first",
            atlas_release_iri="urn:test:atlas-release:first",
            resources=(base.resources[0],),
            relations=(),
        ),
        dataclasses.replace(
            base,
            spec=dataclasses.replace(
                base.spec,
                key="compiled-source-second",
                expected_resources=1,
                expected_relations=0,
            ),
            source_release_iri="urn:test:source-release:second",
            atlas_release_iri="urn:test:atlas-release:second",
            resources=(base.resources[1],),
            relations=(),
        ),
    )
    alignment = tmp_path / "publisher-alignment.rdf"
    metadata = tmp_path / "current-eurovoc-metadata.ttl"
    alignment.write_text("publisher alignment", encoding="utf-8")
    metadata.write_text("current EuroVoc metadata", encoding="utf-8")
    alignment_digest = "sha256:" + hashlib.sha256(alignment.read_bytes()).hexdigest()
    metadata_digest = "sha256:" + hashlib.sha256(metadata.read_bytes()).hexdigest()
    mapping_source_release = "urn:test:source-release:publisher-alignment"
    pins = (
        RegistryInputPin(
            path=alignment,
            logical_path="publisher-alignment.rdf",
            sha256=alignment_digest,
            byte_length=alignment.stat().st_size,
            source_iri="https://example.test/publisher-alignment.rdf",
            role="publisherAlignment",
        ),
        RegistryInputPin(
            path=metadata,
            logical_path="current-eurovoc-metadata.ttl",
            sha256=metadata_digest,
            byte_length=metadata.stat().st_size,
            source_iri="https://example.test/current-eurovoc-metadata.ttl",
            role="currentPublisherLinksetMetadata",
        ),
    )
    triple_digest = mapping_triple_digest(
        subject_iri=base.resources[0].iri,
        predicate_iri=str(generator.SKOS.exactMatch),
        object_iri=base.resources[1].iri,
    )
    mapping = RegistryMapping(
        subject=base.resources[0].iri,
        predicate=str(generator.SKOS.exactMatch),
        object=base.resources[1].iri,
        subject_atlas_release_iri=releases[0].atlas_release_iri,
        object_atlas_release_iri=releases[1].atlas_release_iri,
        asserted_at="2026-08-06T01:00:00+00:00",
        evidence=(
            RegistryMappingEvidence(
                source_locator=pins[0].source_iri,
                source_digest=alignment_digest,
                native_payload={
                    "mappingTripleDigest": triple_digest,
                    "objectIri": base.resources[1].iri,
                    "predicateIri": str(generator.SKOS.exactMatch),
                    "subjectIri": base.resources[0].iri,
                },
                review_method="operatorAdoption",
                reviewer_iri="urn:ref:actor:atlas-3-test-operator-adoption",
                decided_at="2026-08-06T00:00:00+00:00",
            ),
        ),
    )
    mapping_release = RegistryMappingRelease(
        key="eurovoc-lcsh-alignment-20240711",
        resource_id="synthetic-publisher-alignment",
        source_module="refspec.registry.synthetic_alignment",
        ring="subject",
        scope="publisherRelease",
        issued="2024-07-11",
        source_release_iri=mapping_source_release,
        source_release_digest=alignment_digest,
        inputs=pins,
        mappings=(mapping,),
        editorial_policy={
            "admission": "exact evidence-backed test mapping",
            "profile": "test-mapping-policy-v1",
        },
        metadata={"adoptionDecision": "atlasOperatorAdoption"},
    )
    return releases, mapping_release


def _mapping_policy_graph(resource_id: str) -> Graph:
    graph = generator._new_build_graph()
    source = generator._registry_source_descriptor_iri(resource_id)
    graph.add((source, RDF.type, generator.ATLAS.RegistrySource))
    graph.add(
        (
            source,
            generator.ATLAS.memberDisposition,
            Literal("mappingAssertionsOnly"),
        )
    )
    graph.add(
        (
            source,
            generator.ATLAS.descriptorPayload,
            Literal(
                json.dumps(
                    {
                        "resourceId": resource_id,
                        "resourceKind": "mappingReference",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                datatype=RDF.JSON,
            ),
        )
    )
    return graph


def _mapping_policy_index_row(
    release: RegistryMappingRelease,
) -> dict[str, object]:
    return {
        "intendedUses": ["mappingReference"],
        "resourceId": release.resource_id,
        "semanticRing": release.ring,
        "sourceModule": release.source_module,
    }


def test_load_mapping_releases_applies_registry_policy_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import refspec.atlas.v3_registry_alignments as registry_alignments

    _, mapping_release = _compiled_mapping_case(tmp_path)
    observed: list[RegistryMappingRelease] = []
    monkeypatch.setattr(
        registry_alignments,
        "load_all_registry_mapping_releases",
        lambda only_keys=None: (mapping_release,),
    )
    monkeypatch.setattr(
        generator,
        "_validate_registry_mapping_release_descriptors",
        lambda releases: observed.extend(releases),
    )

    assert generator.load_mapping_releases() == (mapping_release,)
    assert observed == [mapping_release]


def test_mapping_release_matches_mapping_only_registry_policy(tmp_path: Path) -> None:
    _, mapping_release = _compiled_mapping_case(tmp_path)

    generator._validate_registry_mapping_release_policy(
        mapping_release,
        descriptors=_mapping_policy_graph(mapping_release.resource_id),
        index_rows=(_mapping_policy_index_row(mapping_release),),
    )


def test_mapping_evidence_uses_shared_registry_triple_digest(tmp_path: Path) -> None:
    _, mapping_release = _compiled_mapping_case(tmp_path)
    mapping = mapping_release.mappings[0]
    evidence = mapping.evidence[0]
    expected_digest = mapping_triple_digest(
        subject_iri=mapping.subject,
        predicate_iri=mapping.predicate,
        object_iri=mapping.object,
    )

    locator, source_digest, payload = generator._mapping_evidence(
        mapping_release,
        mapping,
        evidence,
    )

    assert locator == URIRef(evidence.source_locator)
    assert source_digest == evidence.source_digest
    assert payload["mappingTripleDigest"] == expected_digest

    tampered = dataclasses.replace(
        evidence,
        native_payload={
            **evidence.native_payload,
            "mappingTripleDigest": "sha256:" + "0" * 64,
        },
    )
    with pytest.raises(ValueError, match="wrong triple digest"):
        generator._mapping_evidence(mapping_release, mapping, tampered)

    secondary_pin = mapping_release.inputs[1]
    secondary = dataclasses.replace(
        evidence,
        source_locator=secondary_pin.source_iri,
        source_digest=secondary_pin.sha256,
    )
    locator, source_digest, _ = generator._mapping_evidence(
        mapping_release,
        mapping,
        secondary,
    )
    assert locator == URIRef(secondary_pin.source_iri)
    assert source_digest == secondary_pin.sha256


def test_mapping_policy_accepts_multiple_versioned_releases_for_one_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, first = _compiled_mapping_case(tmp_path)
    next_digest = "sha256:" + "a" * 64
    next_primary = dataclasses.replace(first.inputs[0], sha256=next_digest)
    second = dataclasses.replace(
        first,
        key="eurovoc-lcsh-alignment-next",
        source_release_iri="urn:test:source-release:publisher-alignment:next",
        source_release_digest=next_digest,
        inputs=(next_primary, *first.inputs[1:]),
        mappings=(
            dataclasses.replace(
                first.mappings[0],
                evidence=(
                    dataclasses.replace(
                        first.mappings[0].evidence[0],
                        source_digest=next_digest,
                    ),
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        lambda: _mapping_policy_graph(first.resource_id),
    )
    monkeypatch.setattr(
        generator,
        "_registry_index_rows",
        lambda: (_mapping_policy_index_row(first),),
    )

    generator._validate_registry_mapping_release_descriptors((first, second))


def test_registry_mapping_policy_pins_index_content_and_descriptor_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = generator._read_json(generator.ROOT / "portfolio/atlas-index-v0.json")
    proof = generator._read_json(generator.REGISTRY_DESCRIPTORS_PROOF)
    assert len(generator._validated_registry_index_rows(index, proof)) == 89

    changed_index = json.loads(json.dumps(index))
    mapping_row = next(
        row
        for row in changed_index["rows"]
        if row["resourceId"] == "eurovoc-lcsh-alignment"
    )
    mapping_row["sourceModule"] = "refspec.registry.unapproved_alignment"
    with pytest.raises(ValueError, match="index content digest differs"):
        generator._validated_registry_index_rows(changed_index, proof)

    changed_digest = generator._registry_index_content_digest(changed_index)
    changed_index["indexDigest"] = changed_digest
    changed_index["indexId"] = (
        "urn:ref:atlas-index:" + changed_digest.removeprefix("sha256:")
    )
    with pytest.raises(ValueError, match="differs from the descriptor proof"):
        generator._validated_registry_index_rows(changed_index, proof)

    tampered_proof = tmp_path / "registry-descriptors.json"
    tampered_proof.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(generator, "REGISTRY_DESCRIPTORS_PROOF", tampered_proof)
    with pytest.raises(ValueError, match="pinned Atlas input drifted"):
        generator._registry_index_rows()


def test_mapping_release_pins_its_primary_source_artifact(tmp_path: Path) -> None:
    _, mapping_release = _compiled_mapping_case(tmp_path)

    with pytest.raises(ValueError, match="not an absolute IRI"):
        dataclasses.replace(mapping_release, source_release_iri="relative-release")
    with pytest.raises(ValueError, match="digest is not SHA-256"):
        dataclasses.replace(mapping_release, source_release_digest="sha256:not-a-digest")
    with pytest.raises(ValueError, match="differs from its primary mapping input"):
        dataclasses.replace(
            mapping_release,
            source_release_digest="sha256:" + "0" * 64,
        )
    with pytest.raises(ValueError, match="unsupported mapping release scope"):
        dataclasses.replace(mapping_release, scope="unknown")


def test_mapping_release_rejects_unknown_or_member_registry_source(
    tmp_path: Path,
) -> None:
    _, mapping_release = _compiled_mapping_case(tmp_path)
    index_rows = (_mapping_policy_index_row(mapping_release),)

    with pytest.raises(ValueError, match="unknown registry source"):
        generator._validate_registry_mapping_release_policy(
            mapping_release,
            descriptors=generator._new_build_graph(),
            index_rows=index_rows,
        )

    descriptors = _mapping_policy_graph(mapping_release.resource_id)
    source = generator._registry_source_descriptor_iri(mapping_release.resource_id)
    descriptors.set(
        (source, generator.ATLAS.memberDisposition, Literal("memberRelease"))
    )
    with pytest.raises(ValueError, match="not mappingAssertionsOnly"):
        generator._validate_registry_mapping_release_policy(
            mapping_release,
            descriptors=descriptors,
            index_rows=index_rows,
        )


def test_mapping_release_rejects_resource_scheme_and_wrong_descriptor_kind(
    tmp_path: Path,
) -> None:
    _, mapping_release = _compiled_mapping_case(tmp_path)
    index_rows = (_mapping_policy_index_row(mapping_release),)
    descriptors = _mapping_policy_graph(mapping_release.resource_id)
    descriptors.add(
        (
            generator._registry_primary_scheme_iri(mapping_release.resource_id),
            RDF.type,
            generator.ATLAS.ResourceScheme,
        )
    )
    with pytest.raises(ValueError, match="unexpectedly has a ResourceScheme"):
        generator._validate_registry_mapping_release_policy(
            mapping_release,
            descriptors=descriptors,
            index_rows=index_rows,
        )

    descriptors = _mapping_policy_graph(mapping_release.resource_id)
    source = generator._registry_source_descriptor_iri(mapping_release.resource_id)
    descriptors.set(
        (
            source,
            generator.ATLAS.descriptorPayload,
            Literal(
                json.dumps(
                    {
                        "resourceId": mapping_release.resource_id,
                        "resourceKind": "subjectVocabulary",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                datatype=RDF.JSON,
            ),
        )
    )
    with pytest.raises(ValueError, match="not a mappingReference"):
        generator._validate_registry_mapping_release_policy(
            mapping_release,
            descriptors=descriptors,
            index_rows=index_rows,
        )


def test_mapping_release_rejects_index_module_ring_or_intended_use_drift(
    tmp_path: Path,
) -> None:
    _, mapping_release = _compiled_mapping_case(tmp_path)
    descriptors = _mapping_policy_graph(mapping_release.resource_id)
    index_row = _mapping_policy_index_row(mapping_release)

    for field, value in (
        ("sourceModule", "refspec.registry.other_alignment"),
        ("semanticRing", "entity"),
    ):
        changed = {**index_row, field: value}
        with pytest.raises(ValueError, match="module/ring differs"):
            generator._validate_registry_mapping_release_policy(
                mapping_release,
                descriptors=descriptors,
                index_rows=(changed,),
            )

    changed = {**index_row, "intendedUses": ["searchExpansion"]}
    with pytest.raises(ValueError, match="not a mappingReference"):
        generator._validate_registry_mapping_release_policy(
            mapping_release,
            descriptors=descriptors,
            index_rows=(changed,),
        )


def test_mapping_emits_evidence_accounting_and_dedicated_pack(
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
    releases, mapping_release = _compiled_mapping_case(tmp_path)
    mapping_releases = (mapping_release,)

    inventory = generator.verify_inputs(releases, mapping_releases)
    assert inventory["expectedResources"] == 2
    assert inventory["registryDescriptors"] == 88
    mapping_source = inventory["mappingSources"][0]
    assert [row["role"] for row in mapping_source["inputs"]] == [
        "publisherAlignment",
        "currentPublisherLinksetMetadata",
    ]
    assert mapping_source["mappingCount"] == 1
    assert mapping_source["evidenceBindingCount"] == 1
    assert mapping_source["reviewMethods"] == ["operatorAdoption"]
    assert mapping_source["scope"] == "publisherRelease"

    producer_receipt = generator._validate_compiled_producer_rows(
        releases,
        mapping_releases,
    )
    graphs = generator._build_graphs(
        releases,
        mapping_releases=mapping_releases,
        include_projection=False,
    )
    try:
        report = generator._validate_compiled_producer_output(
            releases,
            graphs,
            producer_receipt,
            mapping_releases,
        )
        assert report["counts"] == {
            "crossRingRelationAssertions": 0,
            "derivedRelations": 0,
            "identifiers": 0,
            "labels": 2,
            "mappingAssertions": 1,
            "nativeRelationAssertions": 0,
            "projectedRelations": 0,
            "relationAssertions": 3,
            "releases": 2,
            "resources": 2,
            "sourceAssignments": 2,
            "sourceRecords": 3,
        }
        assert report["sourceReleaseCount"] == 3

        mapping_assertions = set(
            graphs.asserted.subjects(RDF.type, generator.ATLAS.MappingAssertion)
        )
        assert len(mapping_assertions) == 1
        assertion = next(iter(mapping_assertions))
        assert (
            assertion,
            RDF.type,
            generator.ATLAS.SkosMappingAssertion,
        ) in graphs.asserted
        mapping_row = mapping_release.mappings[0]
        assert graphs.asserted.value(
            assertion,
            generator.ATLAS.sourceRelease,
        ) == URIRef(mapping_row.subject_atlas_release_iri)
        assert graphs.asserted.value(
            assertion,
            generator.ATLAS.targetRelease,
        ) == URIRef(mapping_row.object_atlas_release_iri)
        evidence_bindings = set(
            graphs.asserted.subjects(generator.ATLAS.bindsAssertion, assertion)
        )
        assert len(evidence_bindings) == 1
        evidence = next(iter(evidence_bindings))
        evidence_row = mapping_release.mappings[0].evidence[0]
        assert (
            evidence,
            generator.ATLAS.reviewMethod,
            generator.ATLAS.operatorAdoption,
        ) in graphs.asserted
        assert (
            evidence,
            generator.ATLAS.reviewedBy,
            URIRef(evidence_row.reviewer_iri),
        ) in graphs.asserted
        expected_assertion_time = Literal(
            "2026-08-06T01:00:00+00:00",
            datatype=generator.XSD.dateTime,
            normalize=False,
        )
        expected_decision_time = Literal(
            "2026-08-06T00:00:00+00:00",
            datatype=generator.XSD.dateTime,
            normalize=False,
        )
        assert (
            assertion,
            generator.ATLAS.assertedAt,
            expected_assertion_time,
        ) in graphs.asserted
        assert (
            evidence,
            generator.ATLAS.decidedAt,
            expected_decision_time,
        ) in graphs.asserted
        evidence_source_record = graphs.asserted.value(
            evidence,
            generator.ATLAS.evidenceSourceRecord,
        )
        assert isinstance(evidence_source_record, URIRef)
        assert graphs.asserted.value(
            evidence_source_record,
            generator.ATLAS.sourceLocator,
        ) == URIRef(evidence_row.source_locator)

        accounting_row = next(
            row
            for row in graphs.accounting["inputs"]
            if row["sourceRelease"] == mapping_release.source_release_iri
        )
        assert accounting_row["declaredMemberCount"] == 1
        assert accounting_row["membershipMode"] == "complete"
        assert accounting_row["dispositions"] == [
            {
                "atlasAssertions": [str(assertion)],
                "sourceRecord": str(evidence_source_record),
                "status": "represented",
            }
        ]

        pack_root = tmp_path / "packed"
        pack_root.mkdir()
        packs = generator._write_asserted_packs(
            pack_root,
            graphs.asserted,
            generator._release_pack_plans(releases, mapping_releases),
        )
        mapping_pack = next(pack for pack in packs if pack["kind"] == "mapping")
        catalog_pack = next(pack for pack in packs if pack["kind"] == "catalog")
        source_packs = [pack for pack in packs if pack["kind"] == "sourceRelease"]
        assert len(packs) == 4
        assert mapping_pack["path"] == (
            "packs/mappings/eurovoc-lcsh-alignment-20240711.nq.zst"
        )
        assert set(mapping_pack["dependencies"]) == {
            catalog_pack["packId"],
            *(pack["packId"] for pack in source_packs),
        }

        compression_calls: list[Path] = []
        original_compress = generator._compress_nquads

        def counted_compress(
            source: Path,
            target: Path,
        ) -> generator.PackWriteReceipt:
            compression_calls.append(target)
            return original_compress(source, target)

        monkeypatch.setattr(generator, "_compress_nquads", counted_compress)
        incremental = generator.IncrementalPackMaterialization(
            prior_root=pack_root,
            prior_packs_by_path={pack["path"]: pack for pack in packs},
        )
        rebuilt_root = tmp_path / "incremental-packed"
        rebuilt_root.mkdir()
        rebuilt_packs = generator._write_asserted_packs(
            rebuilt_root,
            graphs.asserted,
            generator._release_pack_plans(releases, mapping_releases),
            incremental=incremental,
        )
        assert compression_calls == []
        assert rebuilt_packs == packs
        assert sorted(incremental.reused_paths) == sorted(
            pack["path"] for pack in packs
        )
        assert any(path.startswith("packs/mappings/") for path in incremental.reused_paths)
        assert all(
            (rebuilt_root / pack["path"]).read_bytes()
            == (pack_root / pack["path"]).read_bytes()
            for pack in packs
        )
    finally:
        graphs.release()


def test_mapping_additional_evidence_keeps_claim_identity_and_mixes_methods(
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
    releases, mapping_release = _compiled_mapping_case(tmp_path)
    mapping = mapping_release.mappings[0]
    secondary_pin = mapping_release.inputs[1]
    secondary_evidence = RegistryMappingEvidence(
        source_locator=secondary_pin.source_iri,
        source_digest=secondary_pin.sha256,
        native_payload={
            **mapping.evidence[0].native_payload,
            "reviewRecord": "independent-human-review",
        },
        review_method="humanReview",
        reviewer_iri="urn:ref:actor:atlas-3-test-human-reviewer",
        decided_at="2026-08-06T02:00:00+00:00",
    )
    expanded_release = dataclasses.replace(
        mapping_release,
        mappings=(
            dataclasses.replace(
                mapping,
                evidence=(*mapping.evidence, secondary_evidence),
            ),
        ),
    )

    producer_receipt = generator._validate_compiled_producer_rows(
        releases,
        (expanded_release,),
    )
    base_graphs = generator._build_graphs(
        releases,
        mapping_releases=(mapping_release,),
        include_projection=False,
    )
    expanded_graphs = generator._build_graphs(
        releases,
        mapping_releases=(expanded_release,),
        include_projection=False,
    )
    try:
        base_assertions = set(
            base_graphs.asserted.subjects(RDF.type, generator.ATLAS.MappingAssertion)
        )
        expanded_assertions = set(
            expanded_graphs.asserted.subjects(
                RDF.type,
                generator.ATLAS.MappingAssertion,
            )
        )
        assert expanded_assertions == base_assertions
        assertion = next(iter(expanded_assertions))
        bindings = set(
            expanded_graphs.asserted.subjects(
                generator.ATLAS.bindsAssertion,
                assertion,
            )
        )
        assert len(bindings) == 2
        assert set(
            expanded_graphs.asserted.objects(
                None,
                generator.ATLAS.reviewMethod,
            )
        ) >= {
            generator.ATLAS.humanReview,
            generator.ATLAS.operatorAdoption,
        }
        assert producer_receipt.expected_counts["sourceRecords"] == 4
        report = generator._validate_compiled_producer_output(
            releases,
            expanded_graphs,
            producer_receipt,
            (expanded_release,),
        )
        assert report["counts"]["sourceRecords"] == 4
        summary = generator._mapping_release_summary(expanded_release)
        assert summary["mappingCount"] == 1
        assert summary["evidenceBindingCount"] == 2
        assert summary["reviewMethods"] == ["humanReview", "operatorAdoption"]
        accounting_row = next(
            row
            for row in expanded_graphs.accounting["inputs"]
            if row["sourceRelease"] == expanded_release.source_release_iri
        )
        assert accounting_row["declaredMemberCount"] == 2
        assert all(
            disposition["atlasAssertions"] == [str(assertion)]
            for disposition in accounting_row["dispositions"]
        )
    finally:
        base_graphs.release()
        expanded_graphs.release()


def test_compiled_output_rejects_a_missing_mapping_evidence_binding(
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
    releases, mapping_release = _compiled_mapping_case(tmp_path)
    mapping = mapping_release.mappings[0]
    second_approval = dataclasses.replace(
        mapping.evidence[0],
        review_method="humanReview",
        reviewer_iri="urn:ref:actor:atlas-3-test-human-reviewer",
        decided_at="2026-08-06T02:00:00+00:00",
    )
    expanded_release = dataclasses.replace(
        mapping_release,
        mappings=(
            dataclasses.replace(
                mapping,
                evidence=(*mapping.evidence, second_approval),
            ),
        ),
    )
    producer_receipt = generator._validate_compiled_producer_rows(
        releases,
        (expanded_release,),
    )
    graphs = generator._build_graphs(
        releases,
        mapping_releases=(expanded_release,),
        include_projection=False,
    )
    try:
        assertion = next(
            graphs.asserted.subjects(RDF.type, generator.ATLAS.MappingAssertion)
        )
        bindings = list(
            graphs.asserted.subjects(generator.ATLAS.bindsAssertion, assertion)
        )
        assert len(bindings) == 2
        graphs.asserted.remove((bindings[-1], None, None))

        with pytest.raises(ValueError):
            generator._validate_compiled_producer_output(
                releases,
                graphs,
                producer_receipt,
                (expanded_release,),
            )
    finally:
        graphs.release()


def test_compiled_output_rejects_wrong_mapping_assertion_in_source_accounting(
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
    releases, mapping_release = _compiled_mapping_case(tmp_path)
    mapping_releases = (mapping_release,)
    producer_receipt = generator._validate_compiled_producer_rows(
        releases,
        mapping_releases,
    )
    graphs = generator._build_graphs(
        releases,
        mapping_releases=mapping_releases,
        include_projection=False,
    )
    try:
        accounting_row = next(
            row
            for row in graphs.accounting["inputs"]
            if row["sourceRelease"] == mapping_release.source_release_iri
        )
        accounting_row["dispositions"][0]["atlasAssertions"] = [
            "urn:ref:atlas-assertion:" + "0" * 64
        ]

        with pytest.raises(ValueError):
            generator._validate_compiled_producer_output(
                releases,
                graphs,
                producer_receipt,
                mapping_releases,
            )
    finally:
        graphs.release()


@pytest.mark.parametrize(
    ("release_field", "message"),
    (
        (
            "subject_atlas_release_iri",
            "subject endpoint release differs from its exact pin",
        ),
        (
            "object_atlas_release_iri",
            "object endpoint release differs from its exact pin",
        ),
    ),
)
def test_mapping_rejects_endpoint_release_version_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    release_field: str,
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
    releases, mapping_release = _compiled_mapping_case(tmp_path)
    drifted_mapping = dataclasses.replace(
        mapping_release.mappings[0],
        **{release_field: f"urn:test:atlas-release:stale-{release_field}"},
    )
    drifted_release = dataclasses.replace(
        mapping_release,
        mappings=(drifted_mapping,),
    )

    with pytest.raises(ValueError, match=message):
        generator._validate_compiled_producer_rows(
            releases,
            (drifted_release,),
        )


def test_compiled_producer_validates_rows_and_constructor_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    release = _compiled_source_release(tmp_path)

    producer_receipt = generator._validate_compiled_producer_rows((release,))
    graphs = generator._build_graphs((release,), include_projection=False)
    report = generator._validate_compiled_producer_output(
        (release,),
        graphs,
        producer_receipt,
    )

    assert report["mode"] == generator._COMPILED_PRODUCER_MODE
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


def test_compiled_producer_retains_supplemental_source_claim_records(
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
    supplemental = RegistrySupplementalSourceRecord(
        source_record_id="urn:test:source-record:claim-one",
        source_locator="https://example.test/source.ttl",
        source_digest=release.source_release_digest,
        native_payload={
            "claimRelease": "urn:test:registry-claim-release",
            "claimReleaseManifestDigest": "sha256:" + "1" * 64,
            "claims": [
                {
                    "language": "en",
                    "lexical_value": "First",
                    "source_record_id": "urn:test:source-record:claim-one",
                }
            ],
            "schemaVersion": "1.0",
            "type": "RegistryClaimRecord",
        },
    )
    release = dataclasses.replace(
        release,
        supplemental_source_records=(supplemental,),
    )

    producer_receipt = generator._validate_compiled_producer_rows((release,))
    graphs = generator._build_graphs((release,), include_projection=False)
    report = generator._validate_compiled_producer_output(
        (release,),
        graphs,
        producer_receipt,
    )

    assert report["counts"]["sourceRecords"] == 3
    assert graphs.accounting["totals"]["excluded"] == 1
    supplemental_nodes = {
        subject
        for subject in graphs.asserted.subjects(
            RDF.type,
            generator.ATLAS.SourceRecord,
        )
        if not list(
            graphs.asserted.objects(subject, generator.ATLAS.representsResource)
        )
    }
    assert len(supplemental_nodes) == 1


def test_compiled_producer_fails_closed_when_shape_profile_drifts(
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


def test_compiled_producer_implementation_pin_is_current() -> None:
    assert generator._compiled_producer_implementation_digest() == (
        generator._COMPILED_PRODUCER_IMPLEMENTATION_DIGEST
    )


def test_semantic_recipe_changes_with_parser_library_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = generator._shared_semantic_recipe_digest()
    current_version = generator.package_version

    def changed_version(distribution: str) -> str:
        version = current_version(distribution)
        return version + "+changed" if distribution == "openpyxl" else version

    monkeypatch.setattr(generator, "package_version", changed_version)

    assert generator._shared_semantic_recipe_digest() != baseline


def test_compiled_producer_rejects_empty_release(
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
        generator._validate_compiled_producer_rows((release,))


def test_compiled_producer_rejects_subject_scheme_without_skos_type(
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
        generator._validate_compiled_producer_rows(
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
            releases=(_test_release_plan(),),
            compiled_validation=report,
            construction_seeds=(_test_construction_seed(),),
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
def test_compiled_producer_rejects_compact_row_mutations(
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
        generator._validate_compiled_producer_rows((release,))


def test_compiled_producer_rejects_projection_and_accounting_mutations(
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
    producer_receipt = generator._validate_compiled_producer_rows((release,))
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
            producer_receipt,
        )

    graphs.projection.remove((None, None, None))
    graphs.accounting["inputs"][0]["dispositions"].pop()
    with pytest.raises(ValueError, match="member count differs"):
        generator._validate_compiled_producer_output(
            (release,),
            graphs,
            producer_receipt,
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

    producer_receipt = generator._validate_compiled_producer_rows(releases)
    graphs = generator._build_graphs(releases, include_projection=False)
    producer_report = generator._validate_compiled_producer_output(
        releases,
        graphs,
        producer_receipt,
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


def test_grants_filter_codes_use_the_value_ring(
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

    producer_receipt = generator._validate_compiled_producer_rows(releases)
    graphs = generator._build_graphs(releases, include_projection=False)
    ontology, shapes = generator.ATLAS_VALIDATE._parse_binding_graphs()
    try:
        scheme = generator.URIRef(
            "urn:ref:atlas-resource-scheme:grants-gov-status-codes"
        )
        assert all(release.spec.ring == "value" for release in releases)
        assert (
            scheme,
            generator.RDF.type,
            generator.SKOS.ConceptScheme,
        ) not in graphs.asserted
        generator._validate_compiled_producer_output(
            releases,
            graphs,
            producer_receipt,
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


def test_production_relation_scope_allows_pinned_mappings_and_rejects_derived() -> None:
    clean = generator.BuildGraphs(Graph(), Graph(), Graph(), {})
    assert generator._production_relation_scope(clean) == {
        "derivedRelations": 0,
        "mappingAssertions": 0,
        "mode": "sourceClaimsAndEvidenceBackedMappings",
    }

    mapping = generator.BuildGraphs(Graph(), Graph(), Graph(), {})
    mapping.asserted.add(
        (
            URIRef("urn:test:mapping"),
            RDF.type,
            generator.ATLAS.MappingAssertion,
        )
    )
    assert generator._production_relation_scope(mapping) == {
        "derivedRelations": 0,
        "mappingAssertions": 1,
        "mode": "sourceClaimsAndEvidenceBackedMappings",
    }

    derived = generator.BuildGraphs(Graph(), Graph(), Graph(), {})
    derived.derived.add(
        (
            URIRef("urn:test:derived"),
            RDF.type,
            generator.ATLAS.DerivedRelation,
        )
    )
    with pytest.raises(ValueError, match="zero derived relations"):
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


def test_add_evidenced_assertion_mints_evidence_without_temporary_mutations() -> None:
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

    generator._add_evidenced_assertion(
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
        decided_at="2026-08-06T00:00:00Z",
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


def test_source_and_mapping_review_methods_are_explicit_and_fail_closed() -> None:
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

    for method in generator.MAPPING_REVIEW_METHODS:
        assert generator._mapping_review_method(method) == generator.ATLAS[method]
    with pytest.raises(ValueError, match="unsupported mapping review method"):
        generator._mapping_review_method("inventedReview")


def test_active_editorial_policies_contain_no_serving_permission_language(
    tmp_path: Path,
) -> None:
    graph = Graph()
    emitted_payloads = []
    _, mapping_release = _compiled_mapping_case(tmp_path)

    for payload in (
        *generator.EDITORIAL_POLICY_PAYLOADS.values(),
        mapping_release.editorial_policy,
    ):
        policy = generator._add_policy(graph, payload)
        encoded = graph.value(policy, generator.ATLAS.policyPayload)
        assert encoded is not None
        emitted_payload = json.loads(str(encoded))
        emitted_payloads.append(emitted_payload)
        assert emitted_payload == generator._plain(payload)
        assert generator._portable_policy_term_violations(emitted_payload) == ()

    assert len(emitted_payloads) == 2
    assert len(set(graph.subjects(RDF.type, generator.ATLAS.EditorialPolicy))) == 2
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
