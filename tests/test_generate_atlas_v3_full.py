from __future__ import annotations

import dataclasses
import hashlib
import importlib
import io
import json
import re
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from refspec.atlas.v3_source_data import (
    RegistryCrossRingRelation,
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

# The instant a build records is a fact of its newest pinned release, never a
# clock, so a test states the release date and derives the instant the same way.
_TEST_CREATED_AT = generator._release_instant("2026-08-06")


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


def test_status_reporter_records_portable_peak_rss_receipts() -> None:
    ticks = iter((10.0, 11.0, 12.0))
    reporter = generator._StatusReporter(
        enabled=False,
        clock=lambda: next(ticks),
    )

    reporter.phase("constructed")
    profile = reporter.memory_profile()

    assert profile["measurement"] == "getrusage-process-high-water-rss"
    assert isinstance(profile["peakRssBytes"], int)
    assert profile["peakRssBytes"] > 0
    assert profile["phaseHighWaterMarks"] == [
        {
            "elapsedMilliseconds": 1000,
            "phase": "constructed",
            "processPeakRssBytes": profile["phaseHighWaterMarks"][0]["processPeakRssBytes"],
        },
        {
            "elapsedMilliseconds": 2000,
            "phase": "generation-report",
            "processPeakRssBytes": profile["phaseHighWaterMarks"][1]["processPeakRssBytes"],
        },
    ]
    generator.ATLAS_VALIDATE.canonical_json_bytes(profile)


def _compiled_test_report(
    graphs: generator.BuildGraphs,
) -> dict[str, object]:
    if isinstance(graphs.asserted, generator._MutationTrackedGraph):
        graphs.sealed_asserted_revision = graphs.asserted.revision
    return {
        "bindingProfile": generator.ATLAS_VALIDATE._binding_digests(),
        "constructorProfile": generator._COMPILED_PRODUCER_PROFILE,
        "counts": generator._counts(graphs),
        "mode": generator._COMPILED_PRODUCER_MODE,
        "sourceAccountingDigest": generator._canonical_digest(graphs.accounting),
        "sourceReleaseCount": generator._counts(graphs)["releases"],
        "status": "passed",
    }


def _compiled_test_accounting() -> dict[str, object]:
    return generator._identified_source_accounting(
        {
            "inputs": [
                {
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
            "version": "3.1",
        }
    )


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
    source_pack = next(pack for pack in packs if pack.get("partition", {}).get("prefix") == source_partition)
    target_pack = next(pack for pack in packs if pack.get("partition", {}).get("prefix") == target_partition)

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
    original_check = generator._check_producer_validation_receipt

    def checked(*args, **kwargs) -> None:
        events.append("compiled")
        original_check(*args, **kwargs)

    monkeypatch.setattr(generator, "_check_producer_validation_receipt", checked)
    monkeypatch.setattr(
        generator.ATLAS_VALIDATE,
        "validate_preparsed_distribution",
        lambda *args, **kwargs: pytest.fail("trusted producer must not run resident-graph RDF validation"),
    )

    result, manifest = generator._write_candidate_distribution(
        tmp_path,
        graphs,
        releases=(_test_release_plan(),),
        compiled_validation=compiled_validation,
        construction_seeds=(_test_construction_seed(),),
        created_at=_TEST_CREATED_AT,
    )

    assert events == ["compiled"]
    assert not graphs.asserted
    assert not graphs.projection
    assert not graphs.derived
    assert graphs.accounting == {}
    assert result["compiledProducerValidation"]["type"] == ("AtlasProducerValidation")
    assert result["compiledProducerValidation"]["binding"] == manifest["binding"]
    assert result["trustedWriterReceiptChecks"]["mode"] == "trustedWriterReceipts"
    assert result["packMaterialization"] == {
        "currentCanonicalPackContent": "fullyRecomputedAndSorted",
        "graphConstruction": "fullRebuild",
        "mode": "coldPackMaterialization",
        "rebuiltPackCount": 2,
        "rebuiltPacks": [
            "packs/catalog.nq.zst",
            "packs/sources/unit-test-release/all.nq.zst",
        ],
    }
    assert result["independentFileConsumerValidation"] == {
        "performedByGenerator": False,
        "requiredForIndependentConsumers": True,
        "validator": "bindings/atlas/3.1/tools/validate.py:validate_distribution",
    }


def test_the_builder_derives_its_binding_block_instead_of_asserting_a_pin(
    tmp_path: Path,
) -> None:
    """The producer records the binding it read; it does not agree with itself.

    Until REF-029 this module carried six compiled digests and refused to build
    when the binding on disk disagreed with them -- the producer checking the
    producer, paid for with a `--repin` edit every time an ontology comment
    moved. The digests are now read off the binding files this build validates
    against and RECORDED on the wire unchanged. The comparison worth making is
    the independent validator's, against the binding on ITS disk; that one is
    untouched (see `_check_binding_pins`).
    """

    graphs = _receipted_test_graphs()

    _, manifest = generator._write_candidate_distribution(
        tmp_path / "distribution",
        graphs,
        releases=(_test_release_plan(),),
        compiled_validation=_compiled_test_report(graphs),
        construction_seeds=(_test_construction_seed(),),
        created_at=_TEST_CREATED_AT,
    )

    assert not hasattr(generator, "_COMPILED_PRODUCER_BINDING_PINS")
    assert manifest["binding"] == {
        "validatorVersion": "3.1",
        "version": "3.1",
        **generator.ATLAS_VALIDATE._binding_digests(),
    }
    # Contract identity is in the manifest; proof identity is in the receipt.
    acceptance = json.loads((tmp_path / "distribution" / "atlas-acceptance.json").read_bytes())
    assert acceptance["corpusDigest"] == generator.ATLAS_VALIDATE.corpus_digest()
    assert "corpusDigest" not in manifest["binding"]
    assert "contractDigest" in manifest["binding"]


def test_a_binding_edited_under_a_running_build_is_refused(tmp_path: Path) -> None:
    """The one comparison the deleted pin table was standing in for.

    A full build runs for ~25 minutes. The binding is hashed once when the
    compiled producer validates its rows and again when the manifest is
    written, so an ontology edited in between is two different readings of the
    same file -- a real disagreement, unlike a constant compiled into this
    program comparing itself against itself.
    """

    graphs = _receipted_test_graphs()
    compiled_validation = _compiled_test_report(graphs)
    compiled_validation["bindingProfile"] = {
        **compiled_validation["bindingProfile"],
        "ontologyDigest": "sha256:" + "0" * 64,
    }

    with pytest.raises(ValueError, match="binding changed on disk"):
        generator._write_candidate_distribution(
            tmp_path / "distribution",
            graphs,
            releases=(_test_release_plan(),),
            compiled_validation=compiled_validation,
            construction_seeds=(_test_construction_seed(),),
            created_at=_TEST_CREATED_AT,
        )


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
    asserted.add((atlas_release, generator.RKAF.membershipMode, generator.RKAF.completeMembership))
    asserted.add((atlas_release, generator.DCTERMS.identifier, Literal("unit-test-release")))
    asserted.add(
        (
            atlas_release,
            generator.DCTERMS.issued,
            Literal("2026-08-06", datatype=generator.XSD.date),
        )
    )
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
        created_at=_TEST_CREATED_AT,
    )
    return manifest


def test_bounded_release_keys_reach_the_loader_that_declares_them() -> None:
    source_keys, mapping_keys = generator.split_construction_unit_keys(
        frozenset({"federal-register-thesaurus-2025", "eurovoc-lcsh-alignment-20240711"})
    )

    assert source_keys == frozenset({"federal-register-thesaurus-2025"})
    assert mapping_keys == frozenset({"eurovoc-lcsh-alignment-20240711"})
    with pytest.raises(ValueError, match="unknown Atlas construction units"):
        generator.split_construction_unit_keys(frozenset({"no-such-release"}))
    with pytest.raises(ValueError, match="names at least one release key"):
        generator.split_construction_unit_keys(frozenset())


def test_bounded_build_loads_only_the_named_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bounded build reaches the loaders with the requested keys only."""

    requested: dict[str, object] = {}

    def load_sources(*, include_keys: object, registry_claim_inputs: object) -> tuple[object, ...]:
        requested["sources"] = include_keys
        return ()

    def load_mappings(*, include_keys: object, source_releases: object) -> None:
        requested["mappings"] = include_keys
        requested["mapping_sources"] = source_releases
        raise RuntimeError("bounded load reached")

    monkeypatch.setattr(generator, "load_releases", load_sources)
    monkeypatch.setattr(generator, "load_mapping_releases", load_mappings)
    with pytest.raises(RuntimeError, match="bounded load reached"):
        generator.build_distribution(
            tmp_path / "distribution",
            include_keys=frozenset({"federal-register-thesaurus-2025"}),
        )

    assert requested["sources"] == frozenset({"federal-register-thesaurus-2025"})
    assert requested["mappings"] == frozenset()
    assert requested["mapping_sources"] == ()


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


def test_distribution_identity_is_the_digest_of_the_content_it_labels() -> None:
    accounting = _compiled_test_accounting()
    identity = accounting["distributionId"]

    bounded_prefix = generator.DISTRIBUTION_ID_PREFIXES[generator.BOUNDED_SELECTION_SCOPE]

    assert identity == generator.distribution_identity(accounting)
    assert identity == generator.distribution_identity(_compiled_test_accounting())
    assert identity.startswith(bounded_prefix)
    assert re.fullmatch(r"[0-9a-f]{64}", identity.removeprefix(bounded_prefix))

    changed = _compiled_test_accounting()
    changed["inputs"][0]["sourceRelease"] = "urn:test:other-source-release"
    assert generator.distribution_identity(changed) != identity

    # No timestamp reaches the identity: the fields it digests are the ledger's
    # own, and adding a recorded instant beside them cannot move it.
    assert set(accounting) == {
        "distributionId",
        "inputs",
        "totals",
        "type",
        "version",
    }
    assert "2026" not in json.dumps(
        {key: value for key, value in accounting.items() if key != "distributionId"},
        sort_keys=True,
    )
    with pytest.raises(ValueError, match="closed source accounting content"):
        generator.distribution_identity({**accounting, "createdAt": _TEST_CREATED_AT})


def test_distribution_identity_names_its_scope_and_cannot_be_relabelled() -> None:
    """The scope segment is read from the content the digest already covers."""

    declared = len(generator._declared_construction_unit_keys())

    assert generator.distribution_scope_profile(declared) == (generator.COMPLETE_TOPOLOGY_SCOPE)
    assert generator.distribution_scope_profile(1) == (generator.BOUNDED_SELECTION_SCOPE)
    for outside in (0, declared + 1):
        with pytest.raises(ValueError, match="code-declared construction units"):
            generator.distribution_scope_profile(outside)

    bounded = _compiled_test_accounting()
    complete = generator._identified_source_accounting(
        {key: value for key, value in bounded.items() if key != "distributionId"}
        | {"totals": {**bounded["totals"], "sourceReleases": declared}}
    )

    assert bounded["distributionId"].startswith(generator.DISTRIBUTION_ID_PREFIXES[generator.BOUNDED_SELECTION_SCOPE])
    assert complete["distributionId"].startswith(generator.DISTRIBUTION_ID_PREFIXES[generator.COMPLETE_TOPOLOGY_SCOPE])
    # Claiming the wider scope moves the digest beside it, because the release
    # count the scope is read from is inside the content the digest covers.
    assert bounded["distributionId"].removeprefix(
        generator.DISTRIBUTION_ID_PREFIXES[generator.BOUNDED_SELECTION_SCOPE]
    ) != complete["distributionId"].removeprefix(generator.DISTRIBUTION_ID_PREFIXES[generator.COMPLETE_TOPOLOGY_SCOPE])
    relabelled = {
        **bounded,
        "distributionId": generator.DISTRIBUTION_ID_PREFIXES[generator.COMPLETE_TOPOLOGY_SCOPE]
        + bounded["distributionId"].split(":")[-1],
    }
    with pytest.raises(ValueError, match="not its own content digest"):
        generator._distribution_id(relabelled)


def test_recorded_instant_comes_from_release_dates_not_a_clock() -> None:
    assert generator._release_instant("2025-04-01") == "2025-04-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="not an ISO 8601 date"):
        generator._release_instant("2025-4-1")
    with pytest.raises(ValueError, match="canonical YYYY-MM-DD"):
        generator._release_instant("20250401")

    older = SimpleNamespace(issued="2025-04-01")
    newer = SimpleNamespace(issued="2026-08-04")

    assert generator._distribution_instant((older, newer)) == ("2026-08-04T00:00:00+00:00")
    assert generator._distribution_instant((newer, older)) == (generator._distribution_instant((older, newer)))


def test_fixed_distribution_inputs_are_externally_pinned_and_logical() -> None:
    # Same split as the ICPSR fixture: an absent capture skips, a moved digest
    # raises `ValueError` and fails, because that is drift rather than absence.
    try:
        inventory = generator.verify_inputs()
    except FileNotFoundError as error:
        pytest.skip(str(error))

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

    assert iri == ("urn:ref:source-concept:v2:loc-lst:019fc9f2-c758-7134-9432-2a0de8fde1dd")
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
        "local_record_id": ("urn:uuid:019fc9f2-c758-7134-9432-2a0de8fde1dd"),
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
    graph.add((scheme, generator.ATLAS.resourceProfile, generator.ATLAS.conceptScheme))
    graph.add((scheme, generator.ATLAS.supportedRing, generator.ATLAS.subject))
    return graph


def test_shared_row_validator_rejects_a_malformed_label_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generator, "_registry_asserted_graph", _compiled_descriptor_graph)
    releases, _ = _compiled_mapping_case(tmp_path)
    dirty, clean = releases
    malformed_label = dataclasses.replace(
        dirty.resources[0].labels[0],
        source_path="",
    )
    dirty = dataclasses.replace(
        dirty,
        resources=(dataclasses.replace(dirty.resources[0], labels=(malformed_label,)),),
    )
    with pytest.raises(ValueError, match="invalid label row"):
        generator._validate_compiled_producer_rows((dirty, clean))


def test_shared_row_validator_rejects_duplicate_cross_ring_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    releases, _ = _compiled_mapping_case(tmp_path)
    dirty, clean = releases
    entity_scheme = URIRef("urn:test:scheme:entities")

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
                review_warrant="operatorAdoption",
                reviewer_iri="urn:ref:actor:atlas-3-test-operator-adoption",
                attested_at="2026-08-06T00:00:00+00:00",
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


def _compiled_stream_prebuild(
    releases: tuple[generator.LoadedRelease, ...],
    mapping_releases: tuple[RegistryMappingRelease, ...],
) -> generator.ProducerPrebuildValidation:
    """Prepare the shared clean receipt used by streamed mutation probes."""

    inventory = generator.verify_inputs(releases, mapping_releases)
    compiled_rows = generator._validate_compiled_producer_rows(
        releases,
        mapping_releases,
    )
    construction_seeds = tuple(
        dataclasses.replace(
            seed,
            adapter_recipe_inputs=_test_construction_seed().adapter_recipe_inputs,
        )
        for seed in generator._release_construction_seeds(
            releases,
            mapping_releases,
        )
    )
    return generator.ProducerPrebuildValidation(
        compiled_rows=compiled_rows,
        construction_seeds=construction_seeds,
        generation_report=generator._producer_generation_report(
            releases,
            mapping_releases,
            input_inventory=inventory,
            producer_validation=compiled_rows,
        ),
        input_inventory=inventory,
        pack_plans=generator._release_pack_plans(releases, mapping_releases),
    )


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

    assert generator.load_mapping_releases(frozenset({mapping_release.key})) == (mapping_release,)
    assert observed == [mapping_release]


def _endpoint_ownership_release(
    tmp_path: Path,
    *,
    key: str,
    iris: tuple[str, ...],
    preference: str,
) -> RegistryRelease:
    source = tmp_path / f"{key}.json"
    source.write_text("{}", encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    pin = RegistryInputPin(
        path=source,
        logical_path=f"tests/{source.name}",
        sha256=digest,
        byte_length=source.stat().st_size,
        source_iri=f"https://example.test/{source.name}",
        role="publisherEndpointSource",
    )
    return RegistryRelease(
        key=key,
        resource_id=key,
        source_module="refspec.registry.test_endpoints",
        profile="conceptScheme",
        ring="subject",
        scope="captureSubset",
        issued="2026-08-15",
        source_release_iri=f"urn:test:source-release:{key}",
        source_release_digest=digest,
        atlas_release_iri=f"urn:test:atlas-release:{key}",
        scheme_iri=f"urn:test:scheme:{key}",
        inputs=(pin,),
        resources=tuple(
            RegistryResource(
                iri=iri,
                labels=(
                    RegistryLabel(
                        value=iri.rsplit("/", 1)[-1],
                        role="preferred",
                        source_path="$.label",
                    ),
                ),
                native_payload={"iri": iri},
                source_locator=f"https://example.test/{key}#{index}",
                source_digest=digest,
            )
            for index, iri in enumerate(iris)
        ),
        metadata={"endpointOwnershipPreference": preference},
    )


def test_endpoint_ownership_reuses_held_resources_and_drops_empty_release(
    tmp_path: Path,
) -> None:
    held = _endpoint_ownership_release(
        tmp_path,
        key="held-vocabulary",
        iris=("https://example.test/vocabulary/held",),
        preference="publisherOwnedVocabulary",
    )
    publisher = _endpoint_ownership_release(
        tmp_path,
        key="publisher-endpoints",
        iris=("https://example.test/vocabulary/shared",),
        preference="publisherOwnedVocabulary",
    )
    duplicate_only = _endpoint_ownership_release(
        tmp_path,
        key="third-party-endpoints",
        iris=(
            "https://example.test/vocabulary/held",
            "https://example.test/vocabulary/shared",
        ),
        preference="publisherVocabularyViaThirdPartySelection",
    )

    reconciled = generator._reconcile_endpoint_release_ownership(
        (held,),
        (duplicate_only, publisher),
    )

    assert [release.key for release in reconciled] == ["publisher-endpoints"]
    assert reconciled[0].metadata["endpointOwnership"] == {
        "candidateResourceCount": 1,
        "candidateRelationCount": 0,
        "emittedResourceCount": 1,
        "emittedRelationCount": 0,
        "excludedResourceCount": 0,
        "excludedRelationCount": 0,
        "excludedResourceCountsByOwningRelease": {},
        "heldIriSpacesBeforeAcquisition": ["https://example.test/vocabulary/"],
        "iriSpaces": ["https://example.test/vocabulary/"],
        "ownershipDecisions": [
            {
                "iriSpace": "https://example.test/vocabulary/",
                "ownerReleaseKey": "publisher-endpoints",
                "resourceCount": 1,
                "selectionBasis": "publisherContentPreference",
            }
        ],
        "preference": "publisherOwnedVocabulary",
        "rule": (
            "reuse an exact resource from an existing held release; otherwise "
            "prefer target-publisher content and break equal-preference ties by release key"
        ),
    }


def test_release_resource_uniqueness_tripwire_rejects_a_duplicate(
    tmp_path: Path,
) -> None:
    first = _endpoint_ownership_release(
        tmp_path,
        key="first",
        iris=("https://example.test/vocabulary/shared",),
        preference="publisherOwnedVocabulary",
    )
    second = _endpoint_ownership_release(
        tmp_path,
        key="second",
        iris=("https://example.test/vocabulary/shared",),
        preference="publisherOwnedVocabulary",
    )

    with pytest.raises(ValueError, match="Atlas releases repeat resource IRI"):
        generator._assert_unique_release_resource_iris((first, second))


def test_mapping_endpoints_are_repinned_without_dropping_assertions(
    tmp_path: Path,
) -> None:
    releases, mapping_release = _compiled_mapping_case(tmp_path)
    stale_mapping = dataclasses.replace(
        mapping_release.mappings[0],
        subject_atlas_release_iri="urn:test:atlas-release:stale-subject",
        object_atlas_release_iri="urn:test:atlas-release:stale-object",
    )
    stale_release = dataclasses.replace(
        mapping_release,
        mappings=(stale_mapping,),
    )

    (repinned,) = generator._pin_mapping_endpoints_to_loaded_releases(
        releases,
        (stale_release,),
    )

    assert len(repinned.mappings) == len(stale_release.mappings) == 1
    assert repinned.mappings[0].subject_atlas_release_iri == releases[0].atlas_release_iri
    assert repinned.mappings[0].object_atlas_release_iri == releases[1].atlas_release_iri
    assert repinned.metadata["endpointOwnership"]["repinnedMappingCount"] == 1


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
    assert len(generator._validated_registry_index_rows(index, proof)) == 112

    changed_index = json.loads(json.dumps(index))
    mapping_row = next(row for row in changed_index["rows"] if row["resourceId"] == "eurovoc-lcsh-alignment")
    mapping_row["sourceModule"] = "refspec.registry.unapproved_alignment"
    with pytest.raises(ValueError, match="index content digest differs"):
        generator._validated_registry_index_rows(changed_index, proof)

    changed_digest = generator._registry_index_content_digest(changed_index)
    changed_index["indexDigest"] = changed_digest
    changed_index["indexId"] = "urn:ref:atlas-index:" + changed_digest.removeprefix("sha256:")
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
    with pytest.raises(ValueError, match="differs from its declared source release inputs"):
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
    descriptors.set((source, generator.ATLAS.memberDisposition, Literal("memberRelease")))
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
    releases, mapping_release = _compiled_mapping_case(tmp_path)
    mapping_releases = (mapping_release,)

    inventory = generator.verify_inputs(releases, mapping_releases)
    assert inventory["expectedResources"] == 2
    assert inventory["registryDescriptors"] == 105
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
        assert len(graphs.derived) == 0
        report = generator._validate_compiled_producer_output(
            releases,
            graphs,
            producer_receipt,
            mapping_releases,
        )
        assert report["counts"] == {
            "crossRingRelationAssertions": 0,
            "derivedRelations": 0,
            "evidenceBindings": 3,
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

        mapping_assertions = set(graphs.asserted.subjects(RDF.type, generator.ATLAS.MappingAssertion))
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
        evidence_bindings = set(graphs.asserted.subjects(generator.RKAF.bindsAssertion, assertion))
        assert len(evidence_bindings) == 1
        evidence = next(iter(evidence_bindings))
        evidence_row = mapping_release.mappings[0].evidence[0]
        assert (
            evidence,
            generator.RKAF.evidenceRole,
            generator.RKAF.formalAdoptionEvent,
        ) in graphs.asserted
        assert (
            evidence,
            generator.RKAF.attestor,
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
            generator.RKAF.assertedAt,
            expected_assertion_time,
        ) in graphs.asserted
        assert (
            evidence,
            generator.RKAF.attestedAt,
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
            row for row in graphs.accounting["inputs"] if row["sourceRelease"] == mapping_release.source_release_iri
        )
        assert len(accounting_row["dispositions"]) == 1
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
        assert mapping_pack["path"] == ("packs/mappings/eurovoc-lcsh-alignment-20240711.nq.zst")
        assert set(mapping_pack["dependencies"]) == {
            catalog_pack["packId"],
            *(pack["packId"] for pack in source_packs),
        }

    finally:
        graphs.release()


def test_streamed_construction_matches_the_whole_graph_oracle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The release spool must preserve every sealed byte and compact row."""

    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    releases, mapping_release = _compiled_mapping_case(tmp_path)
    mapping_releases = (mapping_release,)
    prebuild = _compiled_stream_prebuild(releases, mapping_releases)
    compiled_rows = prebuild.compiled_rows
    pack_plans = prebuild.pack_plans
    construction_seeds = prebuild.construction_seeds

    graphs = generator._build_graphs(
        releases,
        mapping_releases=mapping_releases,
        include_projection=False,
    )
    try:
        legacy_validation = generator._validate_compiled_producer_output(
            releases,
            graphs,
            compiled_rows,
            mapping_releases,
        )
        legacy_accounting = generator._plain(graphs.accounting)
        legacy_root = tmp_path / "whole-graph"
        legacy_result, legacy_manifest = generator._write_candidate_distribution(
            legacy_root / "distribution",
            graphs,
            releases=pack_plans,
            created_at=_TEST_CREATED_AT,
            compiled_validation=legacy_validation,
            construction_seeds=construction_seeds,
            parquet_tables=legacy_root / "parquet-view",
        )
    finally:
        graphs.release()

    comparand_calls = {"idsByRole": 0, "reachability": 0}
    original_ids_by_role = generator.ATLAS_VALIDATE._rdf_record_ids_by_role
    original_reachability = generator.ATLAS_VALIDATE._check_explorer_reachability

    def counted_ids_by_role(graph: Graph) -> dict[str, set[str]]:
        comparand_calls["idsByRole"] += 1
        return original_ids_by_role(graph)

    def counted_reachability(
        served: dict[str, list[str]],
        asserted: dict[str, set[str]],
    ) -> None:
        comparand_calls["reachability"] += 1
        original_reachability(served, asserted)

    monkeypatch.setattr(
        generator.ATLAS_VALIDATE,
        "_rdf_record_ids_by_role",
        counted_ids_by_role,
    )
    monkeypatch.setattr(
        generator.ATLAS_VALIDATE,
        "_check_explorer_reachability",
        counted_reachability,
    )
    streamed = generator._stream_construct_graphs(
        list(releases),
        list(mapping_releases),
        prebuild=prebuild,
        spool_root=tmp_path / "stream-spool",
    )
    streamed_root = tmp_path / "streamed"
    streamed_result, streamed_manifest = generator._write_streamed_candidate_distribution(
        streamed_root / "distribution",
        streamed,
        pack_plans,
        created_at=_TEST_CREATED_AT,
        construction_seeds=construction_seeds,
        parquet_tables=streamed_root / "parquet-view",
    )

    def files(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    assert streamed.accounting == legacy_accounting
    assert streamed.compiled_validation == legacy_validation
    assert streamed_manifest == legacy_manifest
    assert streamed_result == legacy_result
    assert files(streamed_root) == files(legacy_root)
    assert comparand_calls["idsByRole"] > 0
    assert comparand_calls["reachability"] > 0

    role = generator.CompactRecordRole.LABEL
    table_path = streamed_root / "parquet-view" / generator.TABLE_DIRECTORY / generator.TABLE_NAMES[role]
    table = pq.read_table(table_path)
    rows = table.to_pylist()
    rows[0]["id"] = "urn:ref:atlas-label:" + "9" * 64
    table_path.unlink()
    pq.write_table(
        pa.Table.from_pylist(rows, schema=table.schema),
        table_path,
        compression="zstd",
    )
    with pytest.raises(generator.ATLAS_VALIDATE.AtlasValidationError) as streamed_error:
        streamed.spool.check_parquet(streamed_root / "parquet-view")
    assert streamed_error.value.code == "construction.reachability"

    legacy_table_path = legacy_root / "parquet-view" / generator.TABLE_DIRECTORY / generator.TABLE_NAMES[role]
    table_path.replace(legacy_table_path)
    legacy_graphs = generator._build_graphs(
        releases,
        mapping_releases=mapping_releases,
        include_projection=False,
    )
    try:
        with pytest.raises(generator.ATLAS_VALIDATE.AtlasValidationError) as legacy_error:
            generator._check_parquet_view_against_graph(
                legacy_root / "parquet-view",
                legacy_graphs.asserted,
            )
    finally:
        legacy_graphs.release()
    assert legacy_error.value.code == streamed_error.value.code


def _probe_reachability_divergence(
    _tmp_path: Path,
    _monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A duplicate split across two streamed batches keeps the legacy code.

    Both paths report the same detail while the duplicate remains within one
    batch. Across the 2,000-row boundary, the legacy whole-set check still sees
    a duplicate while the streamed check sees a served/asserted mismatch in the
    second slice. That message difference is deliberate; the refusal code is
    the stable verdict.
    """

    role = generator.CompactRecordRole.LABEL
    batch_size = generator._STREAM_CONSTRUCTION_BATCH_SIZE
    asserted = [f"urn:test:label:{index:04d}" for index in range(batch_size + 1)]

    in_batch = list(asserted)
    in_batch[batch_size - 1] = in_batch[batch_size - 2]
    with pytest.raises(generator.ATLAS_VALIDATE.AtlasValidationError) as legacy_in_batch:
        generator.ATLAS_VALIDATE._check_explorer_reachability(
            {role.value: in_batch},
            {role.value: set(asserted)},
        )
    with pytest.raises(generator.ATLAS_VALIDATE.AtlasValidationError) as streamed_in_batch:
        generator._StreamingGraphSpool._check_reachability_batch(
            role,
            in_batch[:batch_size],
            asserted[:batch_size],
        )
    assert streamed_in_batch.value.code == legacy_in_batch.value.code
    assert streamed_in_batch.value.detail == legacy_in_batch.value.detail

    boundary = [*asserted[:batch_size], asserted[batch_size - 1]]
    with pytest.raises(generator.ATLAS_VALIDATE.AtlasValidationError) as legacy_boundary:
        generator.ATLAS_VALIDATE._check_explorer_reachability(
            {role.value: boundary},
            {role.value: set(asserted)},
        )
    generator._StreamingGraphSpool._check_reachability_batch(
        role,
        boundary[:batch_size],
        asserted[:batch_size],
    )
    with pytest.raises(generator.ATLAS_VALIDATE.AtlasValidationError) as streamed_boundary:
        generator._StreamingGraphSpool._check_reachability_batch(
            role,
            boundary[batch_size:],
            asserted[batch_size:],
        )

    assert streamed_boundary.value.code == legacy_boundary.value.code
    assert streamed_boundary.value.code == "construction.reachability"
    assert streamed_boundary.value.detail != legacy_boundary.value.detail
    assert "repeats a record identity" in legacy_boundary.value.detail
    assert "not the asserted" in streamed_boundary.value.detail


def _probe_non_iri_subject(
    tmp_path: Path,
    _monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = generator._new_build_graph()
    catalog = generator._new_build_graph()
    try:
        graph.add(
            (
                Literal("not-an-iri-subject"),
                URIRef("urn:test:predicate"),
                URIRef("urn:test:object"),
            )
        )
        plan = _test_release_plan()
        legacy_root = tmp_path / "legacy"
        legacy_root.mkdir()
        with pytest.raises(TypeError) as legacy_error:
            generator._write_asserted_packs(legacy_root, graph, (plan,))

        spool = generator._StreamingGraphSpool(
            tmp_path / "streamed",
            (plan,),
            resource_owner_tokens={},
            catalog=catalog,
        )
        with pytest.raises(TypeError) as streamed_error:
            spool.append_graph(graph, plan)

        assert str(streamed_error.value) == str(legacy_error.value)
        assert str(streamed_error.value) == "Atlas asserted graph contains a non-IRI subject"
    finally:
        graph.close()
        catalog.close()


def test_streamed_statement_counter_matches_legacy_dual_type_semantics(
    tmp_path: Path,
) -> None:
    assertion = URIRef("urn:test:dual-typed-assertion")
    graph = generator._new_build_graph()
    projection = generator._new_build_graph()
    derived = generator._new_build_graph()
    catalog = generator._new_build_graph()
    try:
        graph.add((assertion, RDF.type, generator.ATLAS.RelationAssertion))
        graph.add((assertion, RDF.type, generator.ATLAS.MappingAssertion))
        graph.add((assertion, RDF.type, generator.ATLAS.NativeRelationAssertion))
        legacy = generator._counts(
            generator.BuildGraphs(
                asserted=graph,
                projection=projection,
                derived=derived,
                accounting={},
            )
        )
        plan = _test_release_plan()
        spool = generator._StreamingGraphSpool(
            tmp_path / "streamed",
            (plan,),
            resource_owner_tokens={},
            catalog=catalog,
        )
        spool._increment_counts(
            graph,
            assertion,
            generator.CompactRecordRole.STATEMENT,
            plan.key,
        )

        for field in (
            "mappingAssertions",
            "nativeRelationAssertions",
            "relationAssertions",
        ):
            assert spool.counts[field] == legacy[field]
        assert spool.counts["relationAssertions"] == 2
    finally:
        graph.close()
        projection.close()
        derived.close()
        catalog.close()


def _probe_source_accounting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reviewer's accepted-corruption probe is a permanent negative."""

    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    releases, mapping_release = _compiled_mapping_case(tmp_path)
    mapping_releases = (mapping_release,)
    prebuild = _compiled_stream_prebuild(releases, mapping_releases)
    nonexistent = "urn:ref:atlas-assertion:" + "0" * 64

    graphs = generator._build_graphs(
        releases,
        mapping_releases=mapping_releases,
        include_projection=False,
    )
    try:
        mapping_row = next(
            row
            for row in graphs.accounting["inputs"]
            if row["sourceRelease"] == mapping_release.source_release_iri
        )
        mapping_row["dispositions"][0]["atlasAssertions"] = [nonexistent]
        graphs.accounting["distributionId"] = generator.distribution_identity(
            graphs.accounting
        )
        with pytest.raises(ValueError) as legacy_error:
            generator._validate_compiled_producer_output(
                releases,
                graphs,
                prebuild.compiled_rows,
                mapping_releases,
            )
    finally:
        graphs.release()

    original = generator._stream_mapping_release

    def corrupt_mapping_accounting(*args, **kwargs):
        row = original(*args, **kwargs)
        row["dispositions"][0]["atlasAssertions"] = [nonexistent]
        return row

    monkeypatch.setattr(
        generator,
        "_stream_mapping_release",
        corrupt_mapping_accounting,
    )
    with pytest.raises(ValueError) as streamed_error:
        generator._stream_construct_graphs(
            list(releases),
            list(mapping_releases),
            prebuild=prebuild,
            spool_root=tmp_path / "stream-spool",
        )

    assert type(streamed_error.value) is type(legacy_error.value)
    assert str(streamed_error.value) == str(legacy_error.value)
    assert "represented mapping assertions differ" in str(streamed_error.value)


def _probe_count_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    releases, mapping_release = _compiled_mapping_case(tmp_path)
    mapping_releases = (mapping_release,)
    prebuild = _compiled_stream_prebuild(releases, mapping_releases)
    wrong_counts = dict(prebuild.compiled_rows.expected_counts)
    wrong_counts["labels"] += 1
    wrong_receipt = dataclasses.replace(
        prebuild.compiled_rows,
        expected_counts=wrong_counts,
    )

    graphs = generator._build_graphs(
        releases,
        mapping_releases=mapping_releases,
        include_projection=False,
    )
    try:
        with pytest.raises(ValueError) as legacy_error:
            generator._validate_compiled_producer_output(
                releases,
                graphs,
                wrong_receipt,
                mapping_releases,
            )
    finally:
        graphs.release()

    with pytest.raises(ValueError) as streamed_error:
        generator._stream_construct_graphs(
            list(releases),
            list(mapping_releases),
            prebuild=dataclasses.replace(prebuild, compiled_rows=wrong_receipt),
            spool_root=tmp_path / "stream-spool",
        )
    assert type(streamed_error.value) is type(legacy_error.value)
    assert "constructor counts differ" in str(legacy_error.value)
    assert "constructor counts differ" in str(streamed_error.value)


def _probe_duplicate_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    releases, mapping_release = _compiled_mapping_case(tmp_path)
    prebuild = _compiled_stream_prebuild(releases, (mapping_release,))
    object.__setattr__(
        mapping_release,
        "mappings",
        (*mapping_release.mappings, *mapping_release.mappings),
    )

    with pytest.raises(ValueError) as legacy_error:
        generator._build_graphs(
            releases,
            mapping_releases=(mapping_release,),
            include_projection=False,
        )
    with pytest.raises(ValueError) as streamed_error:
        generator._stream_construct_graphs(
            list(releases),
            [mapping_release],
            prebuild=prebuild,
            spool_root=tmp_path / "stream-spool",
        )

    assert type(streamed_error.value) is type(legacy_error.value)
    assert "evidence decisions collapse to one binding" in str(legacy_error.value)
    assert "repeats a mapping claim" in str(streamed_error.value)


def _probe_evidence_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    releases, mapping_release = _compiled_mapping_case(tmp_path)
    mapping_releases = (mapping_release,)
    prebuild = _compiled_stream_prebuild(releases, mapping_releases)

    graphs = generator._build_graphs(
        releases,
        mapping_releases=mapping_releases,
        include_projection=False,
    )
    try:
        assertion = next(
            graphs.asserted.subjects(RDF.type, generator.ATLAS.MappingAssertion)
        )
        binding = next(
            graphs.asserted.subjects(generator.RKAF.bindsAssertion, assertion)
        )
        graphs.asserted.remove((binding, None, None))
        with pytest.raises(ValueError) as legacy_error:
            generator._validate_compiled_producer_output(
                releases,
                graphs,
                prebuild.compiled_rows,
                mapping_releases,
            )
    finally:
        graphs.release()

    original = generator._validate_streamed_evidence_batch
    mutated = False

    def remove_mapping_evidence(
        graph: Graph,
        current_mappings: tuple[RegistryMappingRelease, ...] = (),
    ) -> None:
        nonlocal mutated
        if current_mappings and not mutated:
            binding = next(graph.subjects(RDF.type, generator.RKAF.EvidenceBinding))
            graph.remove((binding, None, None))
            mutated = True
        original(graph, current_mappings)

    monkeypatch.setattr(
        generator,
        "_validate_streamed_evidence_batch",
        remove_mapping_evidence,
    )
    with pytest.raises(ValueError) as streamed_error:
        generator._stream_construct_graphs(
            list(releases),
            list(mapping_releases),
            prebuild=prebuild,
            spool_root=tmp_path / "stream-spool",
        )

    assert mutated is True
    assert type(streamed_error.value) is type(legacy_error.value)
    assert str(streamed_error.value) == str(legacy_error.value)
    assert "mapping evidence identities differ" in str(streamed_error.value)


def _probe_pack_partition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = dataclasses.replace(
        _test_release_plan(),
        atlas_release_iri=None,
        kind="mapping",
    )
    graph = generator._new_build_graph()
    catalog = generator._new_build_graph()
    try:
        generator._add_source_release(
            graph,
            identifier=plan.source_release_iri,
            digest="sha256:" + "1" * 64,
            issued="2026-08-06",
            locator=URIRef("urn:test:source"),
        )
        monkeypatch.setattr(
            generator,
            "_release_pack_partition",
            lambda release, subject: "0" if release.kind == "mapping" else None,
        )

        legacy_root = tmp_path / "legacy"
        legacy_root.mkdir()
        with pytest.raises(ValueError) as legacy_error:
            generator._write_asserted_packs(legacy_root, graph, (plan,))

        spool = generator._StreamingGraphSpool(
            tmp_path / "streamed-spool",
            (plan,),
            resource_owner_tokens={},
            catalog=catalog,
        )
        spool.append_graph(graph, plan)
        streamed_root = tmp_path / "streamed"
        streamed_root.mkdir()
        with pytest.raises(ValueError) as streamed_error:
            spool.materialize_packs(
                streamed_root,
                incremental=generator.ColdPackMaterialization(),
            )

        assert type(streamed_error.value) is type(legacy_error.value)
        assert str(streamed_error.value) == str(legacy_error.value)
        assert str(streamed_error.value) == "mapping packs do not support source partitions"
    finally:
        graph.close()
        catalog.close()


def _probe_refused_release_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _compiled_source_release(tmp_path)
    refused = dataclasses.replace(release, resources=())
    with pytest.raises(ValueError) as legacy_error:
        generator._validate_loaded_release(refused)

    monkeypatch.setattr(
        generator,
        "load_releases",
        lambda **kwargs: (refused,),
    )
    monkeypatch.setattr(
        generator,
        "load_mapping_releases",
        lambda **kwargs: (),
    )
    write_calls = 0

    def unexpected_write(*args, **kwargs):
        nonlocal write_calls
        write_calls += 1
        raise AssertionError("refused release reached the streamed writer")

    monkeypatch.setattr(
        generator,
        "_write_streamed_distribution",
        unexpected_write,
    )
    output = tmp_path / "output" / "distribution"
    with pytest.raises(ValueError) as streamed_error:
        generator.build_distribution(output)

    assert type(streamed_error.value) is type(legacy_error.value)
    assert str(streamed_error.value) == str(legacy_error.value)
    assert write_calls == 0
    assert not output.exists()


# AGENTS.md requires replacements to keep the former whole-graph behavior as a
# test-only oracle. Each name is bound to the probe that executes both paths;
# deleting a probe therefore removes a required inventory entry and fails the
# guard below. A non-None reason records an intentional message-level mismatch.
_STREAMED_WHOLE_GRAPH_REFUSAL_PROBES: dict[
    str,
    tuple[Callable[[Path, pytest.MonkeyPatch], None], str | None],
] = {
    "count-mismatch": (_probe_count_mismatch, None),
    "duplicate-claim": (
        _probe_duplicate_claim,
        (
            "same-verdict/different-message: the legacy constructor says "
            "'evidence decisions collapse to one binding'; the streamed "
            "constructor says 'repeats a mapping claim'"
        ),
    ),
    "evidence-resolution": (_probe_evidence_resolution, None),
    "non-iri-subject": (_probe_non_iri_subject, None),
    "pack-partition": (_probe_pack_partition, None),
    "reachability-divergence": (
        _probe_reachability_divergence,
        (
            "same-verdict/different-message: a duplicate split across the 2,000-row "
            "boundary appears as a batch-local served/asserted mismatch"
        ),
    ),
    "refused-release-before-write": (_probe_refused_release_before_write, None),
    "source-accounting": (_probe_source_accounting, None),
}
_STREAMED_WHOLE_GRAPH_DELIBERATE_DIVERGENCES = frozenset(
    (name, reason)
    for name, (_probe, reason) in _STREAMED_WHOLE_GRAPH_REFUSAL_PROBES.items()
    if reason is not None
)


def test_streamed_whole_graph_refusal_battery_has_no_missing_probe() -> None:
    assert set(_STREAMED_WHOLE_GRAPH_REFUSAL_PROBES) == {
        "count-mismatch",
        "duplicate-claim",
        "evidence-resolution",
        "non-iri-subject",
        "pack-partition",
        "reachability-divergence",
        "refused-release-before-write",
        "source-accounting",
    }
    assert _STREAMED_WHOLE_GRAPH_DELIBERATE_DIVERGENCES == frozenset(
        {
            (
                "duplicate-claim",
                (
                    "same-verdict/different-message: the legacy constructor says "
                    "'evidence decisions collapse to one binding'; the streamed "
                    "constructor says 'repeats a mapping claim'"
                ),
            ),
            (
                "reachability-divergence",
                (
                    "same-verdict/different-message: a duplicate split across the 2,000-row "
                    "boundary appears as a batch-local served/asserted mismatch"
                ),
            ),
        }
    )


@pytest.mark.parametrize("probe_name", sorted(_STREAMED_WHOLE_GRAPH_REFUSAL_PROBES))
def test_streamed_whole_graph_refusal_probe(
    probe_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe, _reason = _STREAMED_WHOLE_GRAPH_REFUSAL_PROBES[probe_name]
    probe(tmp_path, monkeypatch)


def test_mapping_additional_evidence_keeps_claim_identity_and_mixes_methods(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
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
        review_warrant="humanReview",
        reviewer_iri="urn:ref:actor:atlas-3-test-human-reviewer",
        attested_at="2026-08-06T02:00:00+00:00",
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
        base_assertions = set(base_graphs.asserted.subjects(RDF.type, generator.ATLAS.MappingAssertion))
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
                generator.RKAF.bindsAssertion,
                assertion,
            )
        )
        assert len(bindings) == 2
        assert set(
            expanded_graphs.asserted.objects(
                None,
                generator.RKAF.evidenceRole,
            )
        ) >= {
            generator.RKAF.textualEvidence,
            generator.RKAF.formalAdoptionEvent,
        }
        assert producer_receipt.expected_counts["evidenceBindings"] == 4
        assert producer_receipt.expected_construction_counts["evidenceBindings"] == 4
        assert producer_receipt.expected_counts["sourceRecords"] == 4
        report = generator._validate_compiled_producer_output(
            releases,
            expanded_graphs,
            producer_receipt,
            (expanded_release,),
        )
        assert report["counts"]["evidenceBindings"] == 4
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
        assert len(accounting_row["dispositions"]) == 2
        assert all(disposition["atlasAssertions"] == [str(assertion)] for disposition in accounting_row["dispositions"])
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
    releases, mapping_release = _compiled_mapping_case(tmp_path)
    mapping = mapping_release.mappings[0]
    second_approval = dataclasses.replace(
        mapping.evidence[0],
        review_warrant="humanReview",
        reviewer_iri="urn:ref:actor:atlas-3-test-human-reviewer",
        attested_at="2026-08-06T02:00:00+00:00",
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
        assertion = next(graphs.asserted.subjects(RDF.type, generator.ATLAS.MappingAssertion))
        bindings = list(graphs.asserted.subjects(generator.RKAF.bindsAssertion, assertion))
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
            row for row in graphs.accounting["inputs"] if row["sourceRelease"] == mapping_release.source_release_iri
        )
        accounting_row["dispositions"][0]["atlasAssertions"] = ["urn:ref:atlas-assertion:" + "0" * 64]

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
    assert report["counts"] == {
        "crossRingRelationAssertions": 0,
        "derivedRelations": 0,
        "evidenceBindings": 3,
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
        if not list(graphs.asserted.objects(subject, generator.ATLAS.representsResource))
    }
    assert len(supplemental_nodes) == 1


def test_compiled_producer_rejects_empty_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
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

    with pytest.raises(ValueError, match="not a SKOS ConceptScheme"):
        generator._validate_compiled_producer_rows((_compiled_source_release(tmp_path),))


def test_asserted_pack_writer_rejects_oversized_nquads_line(
    tmp_path: Path,
) -> None:
    asserted = generator._new_build_graph()
    asserted.add(
        (
            URIRef("urn:test:subject"),
            URIRef("urn:test:predicate"),
            generator.Literal("x" * generator.ATLAS_VALIDATE.NQUADS_MAX_LINE_BYTES),
        )
    )

    with pytest.raises(ValueError, match="exceeds the binding limit"):
        generator._write_asserted_packs(tmp_path, asserted, ())


def test_record_counts_are_keyed_by_unit_key_not_by_pack_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A construction unit and its pack path are two different strings.

    `_release_pack_token` casefolds a unit key and replaces every character a
    pack path may not carry, so `eurovoc-4.24` owns `packs/sources/eurovoc-4-24/`.
    The construction summary is keyed by the unit; `pack_owners` is keyed for
    the filesystem. A tally that published the pack token would disagree with
    the unit enumeration for exactly the units whose key is not already a valid
    path token -- three of the 110 in the full topology, and none of the
    single-unit staging artifacts, whose keys are all path-safe.

    Pinned at fixture scale because the divergence needs only one dotted key,
    not the topology that happens to contain them.
    """

    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    release = _compiled_source_release(tmp_path)
    dotted_key = "unit-test.release.4.24"
    plan = generator.ReleasePackPlan(
        key=dotted_key,
        source_release_iri=release.source_release_iri,
        atlas_release_iri=release.atlas_release_iri,
        ring=release.spec.ring,
        resource_count=len(release.resources),
    )
    assert generator._release_pack_token(plan) == "unit-test-release-4-24"
    assert generator._release_pack_token(plan) != plan.key

    graphs = generator._build_graphs((release,), include_projection=False)
    try:
        pack_root = tmp_path / "packed"
        pack_root.mkdir()
        record_counts: dict[str, dict[str, int]] = {}
        packs = generator._write_asserted_packs(
            pack_root,
            graphs.asserted,
            (plan,),
            record_counts=record_counts,
        )

        # The tally is keyed by the unit, and the pack path by the token.
        assert set(record_counts) == {dotted_key}
        assert any("unit-test-release-4-24" in pack["path"] for pack in packs)
        assert record_counts[dotted_key]["resources"] == len(release.resources)
    finally:
        graphs.release()


def test_builder_emits_parquet_from_the_graph_it_already_walks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One walk, two serializations, and the tables prove against the RDF.

    The Parquet rows come off the graph walk that writes the RDF packs, so the
    tables cost that walk rather than a re-read of everything it just wrote.
    The comparand for the proof is the binding validator's, never the
    builder's own projection.
    """

    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    release = _compiled_source_release(tmp_path)
    graphs = generator._build_graphs((release,), include_projection=False)
    try:
        pack_root = tmp_path / "packed"
        pack_root.mkdir()
        tables = tmp_path / "parquet-tables"
        writer = generator.AtlasParquetTableWriter(tables)
        record_counts: dict[str, dict[str, int]] = {}
        generator._write_asserted_packs(
            pack_root,
            graphs.asserted,
            generator._release_pack_plans((release,), ()),
            parquet=writer,
            record_counts=record_counts,
        )
        members, counts = writer.close()

        # Every logical record reached a Parquet row, role for role, and the
        # per-release counts the construction summary publishes are the same
        # tally.
        expected = Counter()
        for owned in record_counts.values():
            for field, count in owned.items():
                expected[field] += count
        by_field = {generator._COMPACT_ROLE_COUNT_FIELDS[role]: count for role, count in counts.items() if count}
        assert by_field == {field: count for field, count in expected.items() if count}
        assert {member["role"] for member in members} == {role.value for role in generator.CompactRecordRole}

        receipt = generator._check_parquet_view_against_graph(tables, graphs.asserted)
        assert receipt["status"] == "passed"
        assert receipt["sampledRowsAgainstRdf"] > 0
        assert receipt["sourceRecordPayloadRows"] == counts["SourceRecord"]
        assert receipt["reachabilityRows"] == sum(counts.values())
        assert receipt["comparand"].endswith("validate.py:parquet_row_from_rdf")
        assert receipt["reachabilityComparand"].endswith("validate.py:_check_explorer_reachability")
    finally:
        graphs.release()


def test_parquet_parity_refuses_a_table_the_graph_does_not_say(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A check nothing can fail is not a check.

    The tables are rewritten with one warrant axis changed -- exactly the
    column class the 2026-08 defect lived in -- and the parity gate must
    refuse them.
    """

    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    release = _compiled_source_release(tmp_path)
    graphs = generator._build_graphs((release,), include_projection=False)
    try:
        pack_root = tmp_path / "packed"
        pack_root.mkdir()
        tables = tmp_path / "parquet-tables"
        writer = generator.AtlasParquetTableWriter(tables)
        generator._write_asserted_packs(
            pack_root,
            graphs.asserted,
            generator._release_pack_plans((release,), ()),
            parquet=writer,
            record_counts={},
        )
        writer.close()
        generator._check_parquet_view_against_graph(tables, graphs.asserted)

        role = generator.CompactRecordRole.EVIDENCE_BINDING
        table_path = tables / generator.TABLE_DIRECTORY / generator.TABLE_NAMES[role]
        table = pq.read_table(table_path)
        assert table.num_rows > 0
        rows = table.to_pylist()
        rows[0]["epistemic_basis"] = "urn:test:not-what-the-graph-says"
        table_path.unlink()
        pq.write_table(
            pa.Table.from_pylist(rows, schema=table.schema),
            table_path,
            compression="zstd",
        )

        with pytest.raises(generator.ATLAS_VALIDATE.AtlasValidationError) as error:
            generator._check_parquet_view_against_graph(tables, graphs.asserted)
        assert error.value.code == "construction.parquet"
        assert "epistemic_basis" in error.value.detail
    finally:
        graphs.release()


def test_parquet_parity_refuses_a_record_the_served_tables_cannot_reach(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reachability property the compact layer used to carry, negative-tested.

    `explorer-record-unreachable` was a corpus case while the served
    projection was compact JSONL inside the distribution. The projection is
    now the Parquet view beside it, which fixtures do not carry, so the case
    moves here: one label row is retitled to an id the graph never asserts,
    leaving every count equal, and the gate must still refuse it. The
    comparand stays `validate.py:_check_explorer_reachability`.
    """

    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    release = _compiled_source_release(tmp_path)
    graphs = generator._build_graphs((release,), include_projection=False)
    try:
        pack_root = tmp_path / "packed"
        pack_root.mkdir()
        tables = tmp_path / "parquet-tables"
        writer = generator.AtlasParquetTableWriter(tables)
        generator._write_asserted_packs(
            pack_root,
            graphs.asserted,
            generator._release_pack_plans((release,), ()),
            parquet=writer,
            record_counts={},
        )
        writer.close()
        generator._check_parquet_view_against_graph(tables, graphs.asserted)

        role = generator.CompactRecordRole.LABEL
        table_path = tables / generator.TABLE_DIRECTORY / generator.TABLE_NAMES[role]
        table = pq.read_table(table_path)
        assert table.num_rows > 0
        rows = table.to_pylist()
        rows[0]["id"] = "urn:ref:atlas-label:" + "9" * 64
        table_path.unlink()
        pq.write_table(
            pa.Table.from_pylist(rows, schema=table.schema),
            table_path,
            compression="zstd",
        )

        with pytest.raises(generator.ATLAS_VALIDATE.AtlasValidationError) as error:
            generator._check_parquet_view_against_graph(tables, graphs.asserted)
        assert error.value.code == "construction.reachability"
        assert "unreachable=" in error.value.detail
        assert "unasserted=" in error.value.detail
    finally:
        graphs.release()


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
            created_at=_TEST_CREATED_AT,
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
    with pytest.raises(ValueError, match="source accounting identity differs"):
        generator._validate_compiled_producer_output(
            (release,),
            graphs,
            producer_receipt,
        )

    # Reseal the ledger around the mutation. An accounting names the digest of
    # its own content, so tampering is caught by the identity above; resealing
    # is what reaches the membership reconciliation underneath it.
    #
    # What refuses the dropped disposition is that reconciliation -- the
    # represented resources the ledger names against the resources the release
    # actually carries. The `declaredMemberCount` self-count that used to fire
    # first said only that the producer could count its own list.
    graphs.accounting["distributionId"] = generator.distribution_identity(graphs.accounting)
    with pytest.raises(ValueError, match="resource membership differs"):
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
    resources = [(release, resource) for release in crs_releases for resource in release.resources]
    counts_by_namespace = {
        token: sum(len(release.resources) for release in crs_releases if release.spec.fallback_namespace_token == token)
        for token in ("loc-lst", "loc-cgpa")
    }

    assert len(resources) == 1_075
    assert counts_by_namespace == {"loc-lst": 1_043, "loc-cgpa": 32}
    assert not any(resource.iri.startswith("urn:ref:source-concept:v1:") for _, resource in resources)
    for release, resource in resources:
        token = release.spec.fallback_namespace_token
        assert resource.iri.startswith(f"urn:ref:source-concept:v2:{token}:")
        assert resource.native_payload is not None
        source_identity = resource.native_payload["sourceIdentity"]
        assert source_identity["identityKind"] == "refspecSourceScoped"
        assert source_identity["namespaceToken"] == token
        assert source_identity["priorSourceConceptIri"].startswith("urn:ref:source-concept:v1:")
        assert resource.iri.endswith(source_identity["localRecordId"].removeprefix("urn:uuid:"))

    entity_release = next(release for release in crs_releases if release.spec.key == "crs-legislative-entities")
    brazil = next(
        resource for resource in entity_release.resources if any(label.value == "Brazil" for label in resource.labels)
    )
    assert brazil.iri == ("urn:ref:source-concept:v2:loc-lst:019fc9f2-c758-7134-9432-2a0de8fde1dd")
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
    # The pinned capture lives under the gitignored output tree. Absence is
    # `FileNotFoundError` and skips; a digest that moved is `ValueError` and
    # still fails, which is the class this fixture exists to catch.
    try:
        return generator._load_icpsr(_source_spec("icpsr-subject-thesaurus"))
    except FileNotFoundError as error:
        pytest.skip(str(error))


@pytest.fixture(scope="module")
def registry_code_releases():
    from refspec.atlas.v3_registry_codes import load_registry_code_releases

    if not (ROOT / "output" / "registry-real-data-sources").is_dir():
        pytest.skip("pinned registry code sources are not present: output/registry-real-data-sources")
    return tuple(generator._adapt_registry_release(release) for release in load_registry_code_releases(ROOT))


def test_only_five_icpsr_xml_gaps_receive_readable_fallback_ids(
    icpsr_release,
) -> None:
    fallback_resources = [
        resource
        for resource in icpsr_release.resources
        if resource.native_payload is not None
        and resource.native_payload.get("identityStatus") == "publisherIdentifierAbsent"
    ]
    publisher_resources = [
        resource
        for resource in icpsr_release.resources
        if resource.native_payload is not None
        and resource.native_payload.get("identityStatus") != "publisherIdentifierAbsent"
    ]
    fallback_ids = {resource.iri for resource in fallback_resources}
    fallback_relation_endpoints = {
        endpoint
        for relation in icpsr_release.relations
        for endpoint in (relation.subject, relation.object)
        if endpoint.startswith("urn:ref:source-concept:v2:icpsr-subject-thesaurus:")
    }

    assert len(fallback_resources) == 5
    assert len(publisher_resources) == 3_805
    assert all(
        resource.iri.startswith("urn:ref:source-concept:v2:icpsr-subject-thesaurus:") for resource in fallback_resources
    )
    assert all(
        resource.native_payload is not None
        and resource.native_payload["sourceIdentity"]["priorSourceConceptIri"].startswith("urn:ref:source-concept:v1:")
        for resource in fallback_resources
    )
    assert all(resource.iri == resource.source_locator for resource in publisher_resources)
    assert fallback_relation_endpoints == fallback_ids
    assert not any(resource.iri.startswith("urn:ref:source-concept:v1:") for resource in icpsr_release.resources)
    assert not any(
        endpoint.startswith("urn:ref:source-concept:v1:")
        for relation in icpsr_release.relations
        for endpoint in (relation.subject, relation.object)
    )


@pytest.fixture(scope="module")
def entity_ring_release():
    """One small entity-ring release, for cross-ring assertion coverage."""

    from refspec.atlas.v3_registry_large import (
        load_courtlistener_jurisdictions_release,
    )

    return generator._adapt_registry_release(load_courtlistener_jurisdictions_release())


def test_compiled_producer_matches_normative_shacl_for_real_assertion_variants(
    icpsr_release,
    entity_ring_release,
) -> None:
    # This test keeps an isolated entity -> subject variant because the live
    # REF-037 carrier exercises entity -> legalIdentity. Together they cover
    # two distinct admitted cells without making the compiled-SHACL check load
    # the full eCFR and CFR releases.
    native_relation = icpsr_release.relations[0]
    native_resources = {resource.iri: resource for resource in icpsr_release.resources}
    sampled_native_resources = tuple(
        native_resources[iri] for iri in dict.fromkeys((native_relation.subject, native_relation.object))
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

    subject_endpoint = sampled_native_resources[0]
    entity_endpoint = entity_ring_release.resources[0]
    cross_relation = RegistryCrossRingRelation(
        subject=entity_endpoint.iri,
        predicate=str(generator.ATLAS.hasIndexedSubject),
        object=subject_endpoint.iri,
        source_ring="entity",
        target_ring="subject",
        source_payload={"constructedFor": "cross-ring assertion shape coverage"},
    )
    sampled_entity = dataclasses.replace(
        entity_ring_release,
        spec=dataclasses.replace(
            entity_ring_release.spec,
            expected_resources=1,
            expected_relations=0,
            expected_cross_ring_relations=1,
        ),
        resources=(entity_endpoint,),
        relations=(),
        cross_ring_relations=(cross_relation,),
    )
    releases = (sampled_native, sampled_entity)

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
        scheme = generator.URIRef("urn:ref:atlas-resource-scheme:grants-gov-status-codes")
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
    archive_root = ROOT / "research" / "evidence" / "atlas-3-mapping-evidence-2026-08-05"
    manifest_path = archive_root / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    assert "sha256:" + hashlib.sha256(manifest_bytes).hexdigest() == (
        "sha256:287858f602d3073f81584e43f2692c1f35575bc62c767bf1ed90b217ac19f9e8"
    )
    archive = json.loads(manifest_bytes)
    counts = {row["id"]: row["mappingAssertionCount"] for row in archive["pairs"]}

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
        assert descriptor["sha256"] == ("sha256:" + hashlib.sha256(payload).hexdigest())


def test_production_relation_scope_allows_pinned_mappings_and_registered_derived() -> None:
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

    # REF-042: a nonzero derivedRelations count is no longer refused here.
    # The only path that ever populates it is `_derive_registered_relations`,
    # which only ever runs a binding-admitted rule, so this scope records
    # the count instead of gating it a second time.
    derived = generator.BuildGraphs(Graph(), Graph(), Graph(), {})
    derived.derived.add(
        (
            URIRef("urn:test:derived"),
            RDF.type,
            generator.ATLAS.DerivedRelation,
        )
    )
    assert generator._production_relation_scope(derived) == {
        "derivedRelations": 1,
        "mappingAssertions": 0,
        "mode": "sourceClaimsAndEvidenceBackedMappings",
    }


def test_recursive_english_normalization_covers_complete_elsst_profile() -> None:
    payload = {
        "nested": {
            "skos:hiddenLabel": {
                "en": "Hidden",
                "en-US": ["Hidden", "Color"],
                "fr": "Cache",
            },
            "skos:editorialNote": {"EN": ["Keep"], "de": ["Drop"]},
        },
        "ordinary": {"id": ["urn:test:not-a-language-map"]},
        "tagged": [
            {"language": "EN", "role": "preferred", "value": "Keep"},
            {"language": "en-US", "role": "preferred", "value": "Keep"},
            {"language": "en-US", "role": "preferred", "value": "Color"},
            {"language": "fr", "role": "preferred", "value": "Drop"},
        ],
    }

    normalized, dropped = generator._normalize_english_language_content(
        payload,
        language_map_fields=generator.ELSST_LANGUAGE_MAP_FIELDS,
    )

    assert normalized["nested"] == {
        "skos:editorialNote": {"en": ["Keep"]},
        "skos:hiddenLabel": {"en": ["Hidden", "Color"]},
    }
    assert normalized["ordinary"] == {"id": ["urn:test:not-a-language-map"]}
    assert normalized["tagged"] == [
        {"language": "en", "role": "preferred", "value": "Keep"},
        {"language": "en", "role": "alternate", "value": "Color"},
    ]
    assert {(row["path"], row["language"]) for row in dropped} == {
        ("nested/skos:editorialNote", "de"),
        ("nested/skos:hiddenLabel", "fr"),
        ("tagged/3", "fr"),
    }
    maps, tags, violations = generator._audit_english_language_content(
        normalized,
        language_map_fields=generator.ELSST_LANGUAGE_MAP_FIELDS,
    )
    assert (maps, tags, violations) == (2, 2, ())


def test_english_normalization_fails_closed_for_unprofiled_language_field() -> None:
    with pytest.raises(ValueError, match="unprofiled language-bearing field"):
        generator._normalize_english_language_content(
            {"skos:futureNote": {"en": "Known", "fr": "Inconnu"}},
            language_map_fields=generator.ELSST_LANGUAGE_MAP_FIELDS,
        )


def test_source_record_rejects_noncanonical_language_metadata() -> None:
    with pytest.raises(ValueError, match="invalid language metadata"):
        generator._add_source_record(
            Graph(),
            source_release=URIRef("urn:test:release"),
            source_locator=URIRef("urn:test:locator"),
            source_digest="sha256:" + "0" * 64,
            native_payload={"proofDetails": {"language": "FR", "value": "preuve"}},
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
    assert str(graph.value(record, generator.ATLAS.nativePayload)) == expected_bytes.decode("utf-8")
    # The record does not publish its own digest: nothing derives its IRI
    # from one, so the wire carries none and the closed shapes refuse one.
    assert list(graph.objects(record, generator.ATLAS.contentDigest)) == []


def test_add_evidenced_assertion_mints_evidence_without_temporary_mutations() -> None:
    class RemoveRejectingGraph(Graph):
        def remove(self, triple: object) -> Graph:
            raise AssertionError(f"evidence construction must not remove {triple}")

    graph = RemoveRejectingGraph()
    policy = URIRef("urn:test:policy")
    evidence_record = URIRef("urn:test:evidence-record")
    # Both digests are now recomputed from the node's own facts, so each node
    # needs facts to digest rather than a digest triple to read.
    graph.add((policy, RDF.type, generator.ATLAS.EditorialPolicy))
    graph.add((evidence_record, RDF.type, generator.ATLAS.SourceRecord))

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
        review_warrant="publisherAssertion",
        decided_at="2026-08-06T00:00:00Z",
    )

    bindings = set(graph.subjects(RDF.type, generator.RKAF.EvidenceBinding))
    assert len(bindings) == 1
    binding = next(iter(bindings))
    stored_digest = str(graph.value(binding, generator.ATLAS.contentDigest))
    assert binding == URIRef("urn:ref:atlas-evidence:" + stored_digest.removeprefix("sha256:"))
    assert stored_digest == generator.ATLAS_VALIDATE.rdf_node_digest(
        graph,
        binding,
    )
    assert not any(str(subject).startswith("urn:ref:atlas-evidence:pending:") for subject in graph.subjects())


def test_source_and_mapping_review_methods_are_explicit_and_fail_closed() -> None:
    observed = {
        generator._review_method_for_assertion(generator.ATLAS.SourceAssignment),
        generator._review_method_for_assertion(generator.ATLAS.NativeRelationAssertion),
        generator._review_method_for_assertion(
            generator.ATLAS.NativeRelationAssertion,
            deterministic_transformation=True,
        ),
    }

    assert observed == {"publisherAssertion", "deterministicTransformation"}
    assert "operatorAdoption" not in observed
    with pytest.raises(ValueError, match="unsupported assertion"):
        generator._review_method_for_assertion(generator.ATLAS.MappingAssertion)

    for method in generator.MAPPING_REVIEW_METHODS - generator.UNEMITTABLE_MAPPING_REVIEW_METHODS:
        assert generator._mapping_review_method(method) == method
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
        "dispositions": [*represented, *remap_evidence],
        "membershipMode": "complete",
        "sourceRelease": "urn:test:release:icpsr",
    }
    other = {
        "dispositions": [],
        "membershipMode": "complete",
        "sourceRelease": "urn:test:release:aaa",
    }
    accounting_inputs = [icpsr, other]

    generator._finalize_source_accounting_inputs(accounting_inputs)

    assert accounting_inputs == [other, icpsr]
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


def test_streamed_generation_report_records_memory_profile_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The final report exposes the diagnostic RSS receipt in a stable shape."""

    monkeypatch.setattr(
        generator,
        "_registry_asserted_graph",
        _compiled_descriptor_graph,
    )
    releases = (_compiled_source_release(tmp_path),)
    prebuild = _compiled_stream_prebuild(releases, ())
    streamed = generator._stream_construct_graphs(
        list(releases),
        [],
        prebuild=prebuild,
        spool_root=tmp_path / "stream-spool",
    )
    output = tmp_path / "built" / "distribution"
    generator._write_streamed_distribution(
        output,
        streamed,
        releases=prebuild.pack_plans,
        construction_seeds=prebuild.construction_seeds,
        generation_report=prebuild.generation_report,
    )

    report = json.loads((output.parent / "generation-report.json").read_bytes())
    profile = report["memoryProfile"]
    assert set(profile) == {
        "measurement",
        "peakRssBytes",
        "phaseHighWaterMarks",
    }
    assert profile["measurement"] == "getrusage-process-high-water-rss"
    assert isinstance(profile["peakRssBytes"], int)
    assert profile["peakRssBytes"] > 0
    assert profile["phaseHighWaterMarks"]
    assert all(
        set(sample)
        == {
            "elapsedMilliseconds",
            "phase",
            "processPeakRssBytes",
        }
        and isinstance(sample["elapsedMilliseconds"], int)
        and isinstance(sample["phase"], str)
        and isinstance(sample["processPeakRssBytes"], int)
        for sample in profile["phaseHighWaterMarks"]
    )
    assert profile["phaseHighWaterMarks"][-1]["phase"] == "generation-report"


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
    descriptor_graph.add((resource_scheme, generator.ATLAS.supportedRing, generator.ATLAS.value))
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
    identifiers = set(graphs.asserted.subjects(RDF.type, generator.ATLAS.Identifier))

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
    # The simple form, not `^^xsd:string`: RDF 1.1 makes the two the same term,
    # so the wire admits only one spelling and the canonical renderer refuses
    # the other outright. The identifier IRI above is derived from the value as
    # a Python string, so this changes the bytes and nothing else.
    assert set(graphs.asserted.predicate_objects(identifier)) == {
        (RDF.type, generator.ATLAS.Identifier),
        (generator.ATLAS.identifierValue, generator.Literal("ONE-001")),
        (generator.ATLAS.identifierScheme, identifier_scheme),
        (generator.ATLAS.identifies, resource),
        (generator.ATLAS.sourceRecord, source_record),
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
    descriptor_graph.add((resource_scheme, generator.ATLAS.supportedRing, generator.ATLAS.value))
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


def test_the_producer_refuses_a_warrant_whose_records_it_cannot_emit() -> None:
    """Fail at intake, not at the end of a full build.

    The Atlas 3.1 binding admits the twoMachineAdjudication evidence warrant and
    obliges every assertion carrying it to be licensed by a complete
    machine-adjudication record set -- a comparison context, its independent
    proof records, their issuers and model lineages, and the artifacts that
    resolve the sealed request and every sealed response to bundled bytes. This
    producer emits none of them. Until it does, a registry source that declares
    the warrant would build a distribution the binding validator refuses, and
    the refusal would arrive after the whole registry had been constructed
    rather than at the input responsible for it.

    No registry source declares it today; this is the guard that keeps the gap
    honest until the emission is written.
    """

    assert "twoMachineAdjudication" in generator.MAPPING_REVIEW_METHODS, (
        "the binding still admits this warrant, so the producer's refusal is still the thing keeping the two in step"
    )
    with pytest.raises(ValueError) as failure:
        generator._mapping_review_method("twoMachineAdjudication")
    message = str(failure.value)
    assert "twoMachineAdjudication" in message
    assert "rkaf:RelationComparisonContext" in message
    assert "rkaf:ResolverProofRecord" in message


def test_every_other_binding_warrant_still_passes_producer_intake() -> None:
    """The refusal is one named warrant, not a narrowing of the enum."""

    emittable = sorted(generator.MAPPING_REVIEW_METHODS - generator.UNEMITTABLE_MAPPING_REVIEW_METHODS)
    assert emittable == [
        "deterministicTransformation",
        "humanReview",
        "operatorAdoption",
        "publisherAssertion",
        "trustedPipelineReview",
    ]
    for warrant in emittable:
        assert generator._mapping_review_method(warrant) == warrant


def test_every_mapping_ring_passes_producer_intake() -> None:
    """The producer now emits the periods required by dated mapping rings."""

    for ring in sorted(generator.SEMANTIC_RINGS):
        assert generator._mapping_release_ring(ring) == generator.ATLAS[ring]
    with pytest.raises(ValueError, match="unsupported mapping semantic ring"):
        generator._mapping_release_ring("inventedRing")


def test_mapping_assertion_emits_a_content_addressed_effective_period() -> None:
    graph = generator._new_build_graph()
    policy = URIRef("urn:test:mapping-policy")
    graph.add((policy, RDF.type, generator.ATLAS.EditorialPolicy))
    assertion = generator._add_assertion(
        graph,
        assertion_type=generator.ATLAS.MappingAssertion,
        ring=generator.ATLAS.value,
        subject=URIRef("urn:test:value:first"),
        predicate=generator.ATLAS.equivalentValue,
        obj=URIRef("urn:test:value:second"),
        source_release=URIRef("urn:test:release:first"),
        target_release=URIRef("urn:test:release:second"),
        policy=policy,
        asserted_at="2026-08-15T00:00:00+00:00",
        effective_period=("2026-08-15T00:00:00+00:00", None),
    )

    period = graph.value(assertion, generator.RKAF.hasEffectivePeriod)
    assert period is not None
    assert (period, RDF.type, generator.RKAF.EffectivePeriod) in graph
    assert str(graph.value(period, generator.RKAF.effectivePeriodStart)) == ("2026-08-15T00:00:00+00:00")


def test_mapping_periods_are_required_exactly_for_dated_rings(
    tmp_path: Path,
) -> None:
    _, release = _compiled_mapping_case(tmp_path)
    mapping = release.mappings[0]

    assert generator._mapping_effective_period(mapping, ring="subject") is None
    with pytest.raises(ValueError, match="value mapping has no effective period"):
        generator._mapping_effective_period(mapping, ring="value")

    dated = dataclasses.replace(
        mapping,
        effective_from="2026-08-15",
        effective_through="2026-08-31",
    )
    assert generator._mapping_effective_period(dated, ring="value") == (
        "2026-08-15T00:00:00+00:00",
        "2026-08-31T23:59:59+00:00",
    )
    with pytest.raises(ValueError, match="subject mapping must not carry"):
        generator._mapping_effective_period(dated, ring="subject")


def test_registrant_population_releases_are_refused() -> None:
    """REF-030's running check: registrant populations cannot re-enter the Atlas.

    The entity registry (refspec.registry.entity_registry_release) owns SAM
    registrants, CAGE facilities, NPI providers, and CompTox substances. A
    loader that reintroduces one of their authorities -- or a renamed release
    that re-ingests the same records -- must fail the build, not ship.
    """

    by_scheme = SimpleNamespace(
        spec=SimpleNamespace(key="sam-uei-reintroduced"),
        scheme_iri="urn:ref:atlas-resource-scheme:uei-authority",
        resources=(),
    )
    with pytest.raises(ValueError, match="entity registry, not the Atlas"):
        generator._refuse_registrant_population_release(by_scheme)

    by_record = SimpleNamespace(
        spec=SimpleNamespace(key="renamed-entity-release"),
        scheme_iri="urn:ref:atlas-resource-scheme:renamed",
        resources=(SimpleNamespace(iri="urn:ref:sam-entity:uei:YLQMY5SGNE55"),),
    )
    with pytest.raises(ValueError, match="REF-030"):
        generator._refuse_registrant_population_release(by_record)

    institutional = SimpleNamespace(
        spec=SimpleNamespace(key="courtlistener-jurisdictions-2026-08-03"),
        scheme_iri="urn:ref:atlas-resource-scheme:courtlistener-jurisdictions",
        resources=(SimpleNamespace(iri="urn:ref:courtlistener:jurisdiction:scotus"),),
    )
    generator._refuse_registrant_population_release(institutional)


def test_document_population_releases_are_refused() -> None:
    """REF-031's running check: document populations cannot re-enter the Atlas.

    SpicyRegs acquires CBO publications, FCC ECFS proceedings, GovInfo CFR
    packages, and GAO products -- world-generated populations no sealed
    reference artifact can enumerate honestly. A loader that reintroduces one
    of their authorities, or a renamed release that re-ingests the same
    documents, must fail the build. REF-032 amended this: the GAO report page
    that REF-031 kept as a witness left with the topics it witnessed, so GAO
    products are refused here with the rest.
    """

    by_scheme = SimpleNamespace(
        spec=SimpleNamespace(key="cbo-publications-reintroduced"),
        scheme_iri="urn:ref:atlas-resource-scheme:cbo-publication-identifiers",
        resources=(),
    )
    with pytest.raises(ValueError, match="SpicyRegs, not the Atlas"):
        generator._refuse_document_population_release(by_scheme)

    govinfo_by_scheme = SimpleNamespace(
        spec=SimpleNamespace(key="govinfo-cfr-package-reintroduced"),
        scheme_iri="urn:ref:atlas-resource-scheme:govinfo-cfr-packages",
        resources=(),
    )
    with pytest.raises(ValueError, match="REF-031"):
        generator._refuse_document_population_release(govinfo_by_scheme)

    for iri in (
        "https://www.cbo.gov/publication/62634",
        "urn:ref:govinfo-cfr-package:CFR-2023-title1-vol1",
        ("urn:ref:source-concept:v2:fcc-ecfs-proceedings:019fc911-9300-7449-8c7c-4a2e8c3eca11"),
    ):
        by_record = SimpleNamespace(
            spec=SimpleNamespace(key="renamed-document-release"),
            scheme_iri="urn:ref:atlas-resource-scheme:renamed",
            resources=(SimpleNamespace(iri=iri),),
        )
        with pytest.raises(ValueError, match="REF-031"):
            generator._refuse_document_population_release(by_record)

    # REF-032: the witness no longer stays. Both its scheme and its product
    # IRI are refused now.
    witness = SimpleNamespace(
        spec=SimpleNamespace(key="gao-report-gao-26-108505"),
        scheme_iri="urn:ref:atlas-resource-scheme:gao-report-identifiers",
        resources=(SimpleNamespace(iri="https://www.gao.gov/products/gao-26-108505"),),
    )
    with pytest.raises(ValueError, match="REF-031"):
        generator._refuse_document_population_release(witness)

    # The ECFS proceedings' scheme URN stays unguarded here: FCC's *published*
    # bureau roster is a named REF-032 follow-up and lands under it.
    documented_fcc_roster = SimpleNamespace(
        spec=SimpleNamespace(key="fcc-published-bureau-roster"),
        scheme_iri="urn:ref:atlas-resource-scheme:fcc-ecfs-native-controls",
        resources=(SimpleNamespace(iri="urn:ref:source-concept:v2:fcc-bureaus:019fc911-9300-7a37-9efb-3f03b934f065"),),
    )
    generator._refuse_document_population_release(documented_fcc_roster)


def test_observed_inventory_releases_are_refused() -> None:
    """REF-032's running check: observed inventories cannot re-enter the Atlas.

    The Atlas carries what a publisher wrote down. It does not carry the
    distinct values someone scanned out of that publisher's records, one
    alphabetical page of a paginated roster, the radio buttons on a search
    form, or a regex inferred from two examples. The refusal is keyed to the
    observation *substrate* -- the pinned bytes -- plus the minted namespaces
    that name the observation itself, so a documented publisher list for the
    same resource still passes.
    """

    for logical_path in (
        "output/registry-real-data-sources/regulatory-native-current/documents.parquet",
        ("research/evidence/regulatory-native-controls-2026-08-03/source-native-control-capture.json"),
        "output/registry-real-data-sources/OPM-PLUM-all-data-20260804.csv",
        "output/registry-real-data-sources/fh-orgs-default-page.json",
        "output/registry-real-data-sources/ferc-accessibility-tips.html",
        "tests/fixtures/fcc_ecfs_codes/fcc-ecfs-filings-2026-08-03.json",
        "tests/fixtures/gao_topics/gao-product-gao-26-108505-2026-08-04.html",
        "tests/fixtures/gao_cra_facets/gao-cra-database-real-capture-2026-08-04.html",
        "tests/fixtures/agrovoc_thesaurus/agrovoc-c330-sample.ttl",
        "tests/fixtures/nalt_core/nalt-core-9084-animal-welfare.ttl",
        ("tests/fixtures/epa_enterprise_vocabulary/epa-enterprise-vocabulary-tier-1005100-with-definitions.xml"),
        "tests/fixtures/nrc_adams_codes/nrc-adams-faq-2026-08-03.html",
    ):
        by_substrate = SimpleNamespace(
            spec=SimpleNamespace(
                key="renamed-observed-inventory",
                logical_path=logical_path,
                input_pins=(SimpleNamespace(logical_path=logical_path),),
            ),
            scheme_iri="urn:ref:atlas-resource-scheme:renamed",
            resources=(),
        )
        with pytest.raises(ValueError, match="REF-032"):
            generator._refuse_observed_inventory_release(by_substrate)

    for scheme_iri in (
        "urn:ref:atlas-resource-scheme:epa-enterprise-vocabulary:captured-label-tree",
        "urn:ref:atlas-resource-scheme:nrc-adams-identifiers:identifier-shapes",
        "urn:ref:atlas-resource-scheme:nrc-adams-native-controls:observed-structure",
    ):
        by_scheme = SimpleNamespace(
            spec=SimpleNamespace(
                key="reintroduced-observation-scheme",
                logical_path="tests/fixtures/somewhere-else.json",
                input_pins=(),
            ),
            scheme_iri=scheme_iri,
            resources=(),
        )
        with pytest.raises(ValueError, match="REF-032"):
            generator._refuse_observed_inventory_release(by_scheme)

    for iri in (
        "urn:ref:gao-cra-facet:priority:0",
        "urn:ref:nrc-adams-control:apsResultFieldLabels:0f0f",
        "urn:ref:nrc-adams-identifier-shape:0f0f",
        "urn:ref:treasury-fast-book:fund-type:0f0f",
        ("urn:ref:source-concept:v2:federal-register-unresolved-agency-name:019fc911-9300-7449-8c7c-4a2e8c3eca11"),
        ("urn:ref:source-concept:v2:ferc-accession-formats:019fc911-9300-7449-8c7c-4a2e8c3eca11"),
        "urn:ref:source-concept:v2:opm-plum:019fc911-9300-7449-8c7c-4a2e8c3eca11",
        ("urn:ref:source-concept:v2:regulations-gov-docket-agency-code:019fc911-9300-7449-8c7c-4a2e8c3eca11"),
        ("urn:ref:source-concept:v2:regulations-gov-document-agency-code:019fc911-9300-7449-8c7c-4a2e8c3eca11"),
        ("urn:ref:source-concept:v2:unified-agenda-agency-code:019fc911-9300-7449-8c7c-4a2e8c3eca11"),
    ):
        by_record = SimpleNamespace(
            spec=SimpleNamespace(
                key="renamed-observation-release",
                logical_path="tests/fixtures/somewhere-else.json",
                input_pins=(),
            ),
            scheme_iri="urn:ref:atlas-resource-scheme:renamed",
            resources=(SimpleNamespace(iri=iri),),
        )
        with pytest.raises(ValueError, match="REF-032"):
            generator._refuse_observed_inventory_release(by_record)

    # The documented twins that stay. Regulations.gov and the Unified Agenda
    # publish these lists in an OpenAPI document and a documented schema; the
    # observed inventories that shared their scheme *and* their minted-IRI
    # namespace left, which is why neither surface can be guarded and only the
    # substrate refusal above covers them (REF-032 records this).
    for key, iri in (
        (
            "regulations-gov-docket-type",
            ("urn:ref:source-concept:v2:regulations-gov-docket-type:019fc911-9300-7449-8c7c-4a2e8c3eca11"),
        ),
        (
            "regulations-gov-document-type",
            ("urn:ref:source-concept:v2:regulations-gov-document-type:019fc911-9300-7449-8c7c-4a2e8c3eca11"),
        ),
        (
            "unified-agenda-priority-category",
            ("urn:ref:source-concept:v2:unified-agenda-priority-category:019fc911-9300-7449-8c7c-4a2e8c3eca11"),
        ),
        (
            "unified-agenda-rule-stage",
            ("urn:ref:source-concept:v2:unified-agenda-rule-stage:019fc911-9300-7449-8c7c-4a2e8c3eca11"),
        ),
    ):
        documented = SimpleNamespace(
            spec=SimpleNamespace(
                key=key,
                logical_path=("tests/fixtures/regulations_gov_codes/regulations-gov-openapi-v4-2026-08-03.yaml"),
                input_pins=(),
            ),
            scheme_iri="urn:ref:atlas-resource-scheme:regulations-gov-native-controls",
            resources=(SimpleNamespace(iri=iri),),
        )
        generator._refuse_observed_inventory_release(documented)

    # The named follow-ups land under the same resources the observations
    # vacated, and must not trip this guard when they do.
    for key, scheme_iri, logical_path in (
        (
            "federal-register-documented-document-types",
            "urn:ref:atlas-resource-scheme:federal-register-native-controls",
            "tests/fixtures/federal_register/document-types-published.json",
        ),
        (
            "federal-hierarchy-orgs-complete",
            "urn:ref:atlas-resource-scheme:federal-hierarchy:org-identifiers",
            "output/registry-real-data-sources/fh-orgs-complete-roster.json",
        ),
        (
            "gao-published-topics-index",
            "urn:ref:atlas-resource-scheme:gao-topics",
            "tests/fixtures/gao/topics-index.html",
        ),
        (
            "nrc-adams-documented-identifier-shapes",
            "urn:ref:atlas-resource-scheme:nrc-adams-identifiers",
            "tests/fixtures/nrc/adams-identifier-reference.html",
        ),
    ):
        follow_up = SimpleNamespace(
            spec=SimpleNamespace(
                key=key,
                logical_path=logical_path,
                input_pins=(SimpleNamespace(logical_path=logical_path),),
            ),
            scheme_iri=scheme_iri,
            resources=(SimpleNamespace(iri="urn:ref:example:1"),),
        )
        generator._refuse_observed_inventory_release(follow_up)


def test_producer_pins_the_ref037_ecfr_cross_ring_carrier() -> None:
    """The eCFR roster carries the live REF-037 crossing, with 446 rows."""

    releases = generator.load_releases(
        frozenset(
            {
                "ecfr-agencies-roster-2026-08-15",
                "ecfr-cfr-titles",
            }
        )
    )
    carrier_relations = {
        release.spec.key: release.cross_ring_relations
        for release in releases
        if release.cross_ring_relations
    }
    assert {key: len(rows) for key, rows in carrier_relations.items()} == {"ecfr-agencies-roster-2026-08-15": 446}
    relations = carrier_relations["ecfr-agencies-roster-2026-08-15"]
    assert {row.predicate for row in relations} == {str(generator.ATLAS.referencesLegalIdentity)}
    assert {(row.source_ring, row.target_ring) for row in relations} == {("entity", "legalIdentity")}


def test_mapping_releases_are_never_partitioned() -> None:
    """A mapping release packs whole, however many assertions it carries.

    `packs/mappings/<key>.nq.zst` has no partition segment and the packer
    refuses one, but the partitioner used to decide on resource_count alone.
    The FAST-to-LCSH release crossed the large-release threshold and the build
    failed 176 seconds in. Bucketing is a source-release device for large
    member sets; a large mapping release is large in assertions, not members.
    """

    mapping_plan = generator.ReleasePackPlan(
        key="fast-to-lcsh-mapping",
        source_release_iri="urn:test:source-release",
        atlas_release_iri="urn:test:atlas-release",
        ring="subject",
        resource_count=generator._PACK_LARGE_RELEASE_RESOURCE_THRESHOLD * 10,
        kind="mapping",
    )
    source_plan = dataclasses.replace(mapping_plan, kind="sourceRelease")
    subject = URIRef("urn:test:subject")

    assert generator._release_pack_partition(mapping_plan, subject) is None
    assert generator._release_pack_partition(source_plan, subject) is not None
