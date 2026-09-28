"""Bounded accounting parity, byte guards and sort boundary probes."""

from __future__ import annotations

import copy
import dataclasses
import importlib
import io

import pytest
import test_generate_atlas_v3_full as fixtures

from conftest import missing_pinned_input

generator = fixtures.generator
oracle = importlib.import_module("atlas_builder_accounting_oracle")
ACCOUNTING_MUTATIONS = (
    "none",
    "missing",
    "extra",
    "duplicate",
    "wrong-release",
    "totals",
    "status",
    "source",
    "source-record",
    "link",
)
# Performance repairs permit no semantic accounting divergence: a mutation named
# here must change the frozen oracle's verdict, and every other must keep it.
INTENTIONAL_ACCOUNTING_DIVERGENCES: frozenset[str] = frozenset()


def test_accounting_divergences_name_real_mutations():
    assert INTENTIONAL_ACCOUNTING_DIVERGENCES <= set(ACCOUNTING_MUTATIONS)


@pytest.mark.parametrize("mutation", ACCOUNTING_MUTATIONS)
def test_compact_accounting_matches_frozen_verdict(tmp_path, monkeypatch, mutation):
    monkeypatch.setattr(generator, "_registry_asserted_graph", fixtures._compiled_descriptor_graph)
    releases, mapping = fixtures._compiled_mapping_case(tmp_path)
    evidence = mapping.mappings[0].evidence[0]
    second_evidence = dataclasses.replace(evidence, source_locator=evidence.source_locator + "#second")
    mapping = dataclasses.replace(
        mapping, mappings=(dataclasses.replace(mapping.mappings[0], evidence=(evidence, second_evidence)),)
    )
    graphs = generator._build_graphs(releases, mapping_releases=(mapping,), include_projection=False)
    accounting = copy.deepcopy(graphs.accounting)
    graphs.release()
    row = next(row for row in accounting["inputs"] if row["sourceRelease"] == mapping.source_release_iri)
    if mutation == "missing":
        row["dispositions"].pop()
    elif mutation == "extra":
        row["dispositions"].append(
            {"atlasAssertions": ["urn:test:extra"], "sourceRecord": "urn:test:extra", "status": "represented"}
        )
    elif mutation == "duplicate":
        row["dispositions"].append(copy.deepcopy(row["dispositions"][0]))
    elif mutation == "wrong-release":
        row["sourceRelease"] = "urn:test:wrong-release"
    elif mutation == "totals":
        accounting["totals"]["sourceRecords"] += 1
    elif mutation == "status":
        row["dispositions"][0]["status"] = "excluded"
    elif mutation == "source":
        source = next(r for r in accounting["inputs"] if r["sourceRelease"] == releases[0].source_release_iri)
        source["dispositions"][0]["atlasResources"] = ["urn:test:wrong-resource"]
    elif mutation == "source-record":
        row["dispositions"][0]["sourceRecord"] = "urn:test:wrong-record"
    elif mutation == "link":
        row["dispositions"][0]["atlasAssertions"] = ["urn:test:wrong-assertion"]
    accounting["distributionId"] = generator.distribution_identity(accounting)

    def verdict(call):
        try:
            return ("accepted", call())
        except (ValueError, TypeError) as error:
            return (type(error).__name__, str(error))

    expected = generator._mapping_accounting_expectations((mapping,))
    assert expected == oracle._mapping_accounting_expectations((mapping,))
    old = verdict(lambda: oracle._validate_compiled_source_accounting(releases, accounting, (mapping,)))
    new = verdict(
        lambda: generator._validate_compiled_source_accounting(
            [generator._source_accounting_expectation(r) for r in releases],
            accounting,
            [generator._MappingAccountingExpectation(mapping.key, mapping.scope, mapping.source_release_iri)],
            mapping_expectations=expected,
        )
    )
    # Every mutation is one the frozen oracle refuses, or it proves nothing.
    assert (old[0] == "accepted") == (mutation == "none")
    assert (new != old) == (mutation in INTENTIONAL_ACCOUNTING_DIVERGENCES)


@pytest.mark.parametrize("scale", (1, 2, 4))
def test_expected_graph_bound_and_shared_records(tmp_path, monkeypatch, scale):
    _, mapping = fixtures._compiled_mapping_case(tmp_path)
    mappings = []
    for index in range(scale * 3):
        original_mapping = mapping.mappings[0]
        subject = original_mapping.subject + str(index)
        evidence = original_mapping.evidence[0]
        payload = dict(evidence.native_payload)
        payload["subjectIri"] = subject
        payload["mappingTripleDigest"] = generator.mapping_triple_digest(
            subject_iri=subject, predicate_iri=original_mapping.predicate, object_iri=original_mapping.object
        )
        mappings.append(
            dataclasses.replace(
                original_mapping, subject=subject, evidence=(dataclasses.replace(evidence, native_payload=payload),)
            )
        )
    mapping = dataclasses.replace(mapping, mappings=tuple(mappings))
    monkeypatch.setattr(generator, "_STREAM_CONSTRUCTION_BATCH_SIZE", 2)
    expected = oracle._mapping_accounting_expectations((mapping,))
    original = generator._expected_mapping_asserted_graph
    sizes = []

    def measured(releases):
        sizes.append(sum(len(r.mappings) for r in releases))
        return original(releases)

    monkeypatch.setattr(generator, "_expected_mapping_asserted_graph", measured)
    assert generator._mapping_accounting_expectations((mapping,)) == expected
    assert max(sizes) <= 2
    assert sum(sizes) == scale * 3


def test_real_agency_event_and_empty_mapping_accounting(monkeypatch):
    from refspec.atlas import v3_registry_alignments_entity as entity
    from tools import analyze_agency_roster_identifiers as census

    release = entity.load_agency_registry_mapping_release(census.load_five_agency_rosters(fixtures.ROOT))
    monkeypatch.setattr(generator, "_STREAM_CONSTRUCTION_BATCH_SIZE", 2)
    assert generator._mapping_accounting_expectations((release,)) == oracle._mapping_accounting_expectations((release,))
    assert generator._mapping_accounting_expectations(()) == oracle._mapping_accounting_expectations(()) == {}
    # Existing model refuses zero mappings, even if events were supplied.
    with pytest.raises(ValueError, match="has no mappings"):
        dataclasses.replace(release, mappings=())
    batches = list(generator._mapping_batches(release))
    assert batches[0].change_events == release.change_events
    assert all(not batch.change_events for batch in batches[1:])


def test_sort_byte_bound_utf8_and_oversized_singleton(tmp_path, monkeypatch):
    rows = ["é" * 4 + "\n", "a\n", "b" * 20 + "\n", "z\n", "a\n"]
    original = generator._merge_sorted_chunks
    runs = []

    def inspect(chunks, temp, *, fan_in):
        runs.extend([p.read_bytes() for p in chunks])
        return original(chunks, temp, fan_in=fan_in)

    monkeypatch.setattr(generator, "_merge_sorted_chunks", inspect)
    output = tmp_path / "sort.nq"
    generator._write_sorted_lines(output, rows, chunk_byte_count=10, chunk_line_count=10, merge_fan_in=2)
    assert output.read_text() == "".join(sorted(rows))
    assert all(len(run) <= 10 or run.count(b"\n") == 1 for run in runs)
    assert len(runs) == 4


def test_actual_pack_and_spool_byte_guards(tmp_path, monkeypatch):
    binding = generator.ATLAS_VALIDATE
    monkeypatch.setattr(binding, "NQUADS_MAX_CONTENT_BYTES", 8)
    monkeypatch.setattr(binding, "NQUADS_MAX_TRANSPORT_BYTES", 8)
    monkeypatch.setattr(binding, "NQUADS_DATASET_MAX_CONTENT_BYTES", 12)
    writer = generator._DigestingBinaryWriter(io.BytesIO())
    assert writer.write(b"12345678") == 8
    with pytest.raises(ValueError, match="transport"):
        writer.write(b"9")
    source = tmp_path / "input.nq"
    source.write_bytes(b"123456789")
    with pytest.raises(ValueError, match="content"):
        generator._materialize_nquads_pack(
            source, tmp_path / "output.zst", relative_path="output.zst", incremental=None
        )
    assert not (tmp_path / "output.zst").exists()
    spool = generator._StreamingGraphSpool(tmp_path / "spool", (), resource_owner_tokens={}, catalog=generator.Graph())
    spool._account_spool_bytes(("one", None), 8)
    with pytest.raises(ValueError, match="content"):
        spool._account_spool_bytes(("one", None), 1)
    with pytest.raises(ValueError, match="aggregate"):
        spool._account_spool_bytes(("two", None), 5)
    pack = {"content": {"byteLength": 7}, "transport": {"byteLength": 5}}
    generator._check_pack_byte_bounds([pack])
    with pytest.raises(ValueError, match="aggregate"):
        generator._check_pack_byte_bounds([pack, pack])


def test_bounded_real_lc_fast_accounting(tmp_path, monkeypatch):
    """First archived publisher statements, without loading the corpus models."""
    import zipfile
    from itertools import islice

    from refspec.atlas import v3_registry_alignments_lc as adapter
    from refspec.registry import lc_external_links as external

    pin = adapter._external_pin(adapter.DEFAULT_SOURCE_ROOT, role="publisherAlignment")
    if not pin.path.exists():
        missing_pinned_input(f"pinned LC archive {pin.path} is absent")
    assert pin.path.stat().st_size == pin.byte_length
    assert generator._sha256_file(pin.path) == pin.sha256
    with zipfile.ZipFile(pin.path) as archive, archive.open(external.LC_EXTERNAL_LINKS_MEMBER) as stream:
        raw = list(islice(stream, 1000))
    rows = external._scan_assertions(raw)
    assert rows and any(row.target_vocabulary == "fast" for row in rows)
    _, template = fixtures._compiled_mapping_case(tmp_path)
    mappings = []
    for row in rows:
        predicate = adapter.MADS_TO_SKOS_PREDICATE[row.predicate_iri]
        mappings.append(
            generator.RegistryMapping(
                subject=row.subject_iri,
                predicate=predicate,
                object=row.object_iri,
                subject_atlas_release_iri=adapter.LCSH_CONSOLIDATED_ATLAS_RELEASE_IRI,
                object_atlas_release_iri="urn:test:bounded-lc-target:" + row.target_vocabulary,
                asserted_at=adapter.LC_MAPPING_DECIDED_AT,
                evidence=(adapter._mapping_evidence(row, mapping_predicate=predicate, source_pin=pin),),
            )
        )
    release = dataclasses.replace(
        template,
        mappings=tuple(mappings),
        inputs=(pin,),
        source_release_digest=pin.sha256,
        editorial_policy=adapter.LC_EXTERNAL_LINKS_MAPPING_POLICY,
    )
    monkeypatch.setattr(generator, "_STREAM_CONSTRUCTION_BATCH_SIZE", 7)
    assert generator._mapping_accounting_expectations((release,)) == oracle._mapping_accounting_expectations((release,))


def test_derivation_premises_follow_registered_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "_registry_asserted_graph", fixtures._compiled_descriptor_graph)
    releases, mapping = fixtures._compiled_mapping_case(tmp_path)
    prebuild = fixtures._compiled_stream_prebuild(releases, (mapping,))
    selected = releases[1].spec.key
    monkeypatch.setattr(generator, "_REGISTERED_DERIVATION_RULES", ((selected, None, None, None, None),))
    observed = []

    def capture(_spool, premises, *, generated_at):
        observed.append(premises)
        return generator.Graph(), 0, ()

    monkeypatch.setattr(generator, "_derive_registered_relations", capture)
    result = generator._stream_construct_graphs(
        list(releases), [mapping], prebuild=prebuild, spool_root=tmp_path / "spool"
    )
    assert set(observed[0]) == {selected}
    result.derived.close()
    result.spool.catalog.close()
