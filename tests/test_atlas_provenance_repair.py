"""Independent payload and exact hierarchy regressions for Atlas repair F2-F4."""

from __future__ import annotations

import copy
import json
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import verify_atlas_source_fidelity as v


def old_ancestors(graph, start):
    # Copied from the former ICPSR reader, not imported from its replacement.
    found = set()
    pending = list(graph.get(start, ()))
    while pending:
        target = pending.pop()
        if target in found:
            continue
        found.add(target)
        pending.extend(graph.get(target, ()))
    return frozenset(found)


def test_requested_paths_match_old_oracle_for_cycles_direction_and_long_paths():
    graph = defaultdict(set)
    for number in range(500):
        graph[str(number)].add(str(number + 1))
    graph["350"].add("200")
    pairs = {(a, b) for a in ("0", "200", "350", "500", "missing") for b in ("0", "200", "350", "500", "missing")}
    assert v._requested_reachability(graph, pairs) == {(a, b) for a, b in pairs if b in old_ancestors(graph, a)}


@pytest.fixture(scope="module")
def umthes():
    root = Path(__file__).parents[1]
    distribution = root / "output/atlas-3.1-umthes-2026-09-27/distribution"
    assert distribution.is_dir(), "required retained UMTHES distribution is unavailable"
    selected, scoped = v.select_scope(["umthes-gemet-endpoints-2026-08-15"])
    context = v.build_context(distribution, v.DEFAULT_SOURCE_ROOT, specs=selected, scoped_out_specs=scoped)
    assert not context.load_failures
    assert not context.pin_failures
    return context


def _old_failures(pair):
    namespace = dict(vars(v))
    exec((Path(__file__).parent / "oracles/atlas_provenance_before_repair.txt").read_text(), namespace)
    publisher = SimpleNamespace(
        **vars(pair.publisher), resource_input_digest_values={}, source_digest_is_native_payload_digest=False
    )
    policy = SimpleNamespace(
        **vars(pair.spec.rdf_source), record_digest_is_native_payload_digest=False, record_input_path_by_resource=()
    )
    spec = replace(pair.spec, rdf_source=policy)
    return namespace["_rdf_provenance_failures"](replace(pair, publisher=publisher, spec=spec))


@pytest.mark.reads_built_artifact
def test_real_payloads_and_old_verdict_divergence(umthes):
    pair = umthes.pairs[0]
    assert len(pair.publisher.expected_relation_payloads) == 50
    assert v._rdf_provenance_failures(pair) == []
    old = _old_failures(pair)
    # Frozen intentional difference: old code confused upstream and outer hashes.
    assert old
    assert all(
        "digest differs -- expected" in row or "sourceDigest differs from its exact publisherRelation payload" in row
        for row in old
    )


@pytest.mark.parametrize("field", ["responseDigest", "reason", "object", "direction", "extra", "missing"])
@pytest.mark.reads_built_artifact
def test_self_rehashed_relation_mutations_fail_exact_comparison(umthes, field):
    pair = umthes.pairs[0]
    record = next(key for key, payload in pair.atlas.native_payloads.items() if "publisherRelation" in payload)
    payload = copy.deepcopy(pair.atlas.native_payloads[record])
    relation = payload["publisherRelation"]
    if field == "responseDigest":
        relation["responseDigest"] = "sha256:" + "0" * 64
    elif field == "reason":
        payload["editorialTransformation"]["reason"] = "invented"
    elif field == "object":
        relation["objectIri"] += "-invented"
    elif field == "direction":
        relation["subjectIri"], relation["objectIri"] = relation["objectIri"], relation["subjectIri"]
    elif field == "extra":
        payload["editorialTransformation"]["extra"] = True
    else:
        del payload["editorialTransformation"]["reason"]
    digest = v._canonical_json_digest(relation)
    payload["publisherRelationDigest"] = digest
    atlas = replace(
        pair.atlas,
        native_payloads={**pair.atlas.native_payloads, record: payload},
        record_source_digests={**pair.atlas.record_source_digests, record: v._canonical_json_digest(payload)},
        record_source_locators={
            **pair.atlas.record_source_locators,
            record: "urn:ref:publisher-relation:" + digest[7:],
        },
    )
    failures = v._rdf_provenance_failures(replace(pair, atlas=atlas))
    assert failures
    assert any("independent reconstruction" in row or "independent source reconstruction" in row for row in failures)


@pytest.mark.reads_built_artifact
def test_relation_population_multiplicity(umthes):
    pair = umthes.pairs[0]
    record = next(key for key, payload in pair.atlas.native_payloads.items() if "publisherRelation" in payload)
    for duplicate in (False, True):
        new = record + "-duplicate"
        payloads = dict(pair.atlas.native_payloads)
        digests = dict(pair.atlas.record_source_digests)
        locators = dict(pair.atlas.record_source_locators)
        records = set(pair.atlas.source_records)
        if duplicate:
            payloads[new] = payloads[record]
            digests[new] = digests[record]
            locators[new] = locators[record]
            records.add(new)
        else:
            del payloads[record]
            del digests[record]
            del locators[record]
            records.remove(record)
        atlas = replace(
            pair.atlas,
            native_payloads=payloads,
            record_source_digests=digests,
            record_source_locators=locators,
            source_records=frozenset(records),
        )
        assert any(
            "source records; expected 1" in row for row in v._rdf_provenance_failures(replace(pair, atlas=atlas))
        )


@pytest.mark.reads_built_artifact
def test_one_comparison_per_invocation_and_no_stale_reuse(umthes, monkeypatch):
    calls = []
    original = v._rdf_provenance_failures

    def counted(pair):
        calls.append(pair)
        return original(pair)

    monkeypatch.setattr(v, "_rdf_provenance_failures", counted)
    checks = (v.check_rdf_provenance_fidelity, v.check_claim_scope)
    v.run_checks(umthes, checks)
    assert len(calls) == 1
    v.run_checks(umthes, checks)
    assert len(calls) == 2


def _old_lc_reader():
    namespace = dict(vars(v))
    stock = v._stock_vocabulary_view

    def old_stock(*args, **kwargs):
        kwargs.pop("source_digest_is_native_payload_digest", None)
        return stock(*args, **kwargs)

    namespace["_stock_vocabulary_view"] = old_stock
    exec((Path(__file__).parent / "oracles/atlas_lc_endpoints_before_repair.txt").read_text(), namespace)
    return namespace["_read_lc_external_target_endpoints"]


def test_lc_partition_matches_copied_grouped_oracle_and_parses_once(monkeypatch):
    import io
    import zipfile
    from collections import Counter

    resources = {
        name: prefixes[0] + "repair-fixture"
        for name, prefixes in v._LC_TARGET_PREFIXES.items()
        if name in {"agrovoc", "getty-aat"}
    }
    subject = v._LCSH_SUBJECT_BASE + "sh-fixture"
    predicate = next(iter(v._LC_MADS_TO_SKOS))
    lines = []
    for name, resource in resources.items():
        lines += [f"<{subject}> <{predicate}> <{resource}> .", f'<{resource}> <{v._LC_AUTHORITATIVE_LABEL}> "{name}" .']
    detached = v._LC_TARGET_PREFIXES["agrovoc"][0] + "detached"
    lines += [
        f'<{detached}> <{v._LC_AUTHORITATIVE_LABEL}> "Detached" .',
        f"<http://id.loc.gov/authorities/names/n-fixture> <{predicate}> <{detached}> .",
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("external_links.nt", "\n".join(lines) + "\n")
    raw = buffer.getvalue()
    pin = v.SourcePin(
        path="fixture.zip",
        sha256="sha256:" + v.hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
        fmt="zip-ntriples",
        role="publisherEndpointSource",
        source_iri="https://example.test/lc.zip",
    )
    specs = [
        replace(
            next(spec for spec in v.SOURCES if spec.name == f"lc-external-{name}-endpoints-2026-08-15"), inputs=(pin,)
        )
        for name in resources
    ]
    monkeypatch.setattr(v, "_LC_TARGET_ENDPOINT_COUNTS", dict.fromkeys(resources, 1))
    opens = Counter()
    original_open = zipfile.ZipFile.open

    def counted(archive, name, *args, **kwargs):
        opens[name] += 1
        return original_open(archive, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", counted)
    parsed = v._parse_lc_endpoint_capture(pin, raw)
    separate = [v._read_lc_external_target_endpoints(spec, {pin: raw}, parsed_capture=parsed) for spec in specs]
    reverse = [
        v._read_lc_external_target_endpoints(spec, {pin: raw}, parsed_capture=parsed) for spec in reversed(specs)
    ]
    assert opens["external_links.nt"] == 2
    assert separate == list(reversed(reverse))
    grouped = _old_lc_reader()(
        replace(specs[0], release_keys=tuple(key for spec in specs for key in spec.release_keys)), {pin: raw}
    )
    assert grouped.concepts == frozenset(resources.values())
    assert set().union(*(view.concepts for view in separate)) == grouped.concepts
    assert {
        key: value for view in separate for key, value in view.expected_native_payloads.items()
    } == grouped.expected_native_payloads
    assert detached not in grouped.concepts


def test_declaration_topology_has_exact_executable_owners():
    from collections import Counter

    from tools.generate_atlas_v3_full import _declared_construction_unit_keys

    owners = Counter(key for spec in v.SOURCES for key in spec.release_keys)
    assert set(owners) == _declared_construction_unit_keys()
    assert set(owners.values()) == {1}
    assert all(
        spec.reader in v._PUBLISHER_READERS
        or spec.reader in {"rdf", "independent-agency"}
        or spec.kind in {"native-control", "source-extract"}
        for spec in v.SOURCES
    )


@pytest.mark.reads_built_artifact
def test_partial_expected_digest_map_cannot_prove_custom_fields(umthes):
    pair = umthes.pairs[0]
    resource = next(iter(pair.publisher.concepts))
    digests = dict(pair.publisher.expected_native_payload_digests)
    payloads = dict(pair.publisher.expected_native_payloads)
    del digests[resource]
    del payloads[resource]
    altered = replace(
        pair,
        publisher=replace(pair.publisher, expected_native_payload_digests=digests, expected_native_payloads=payloads),
    )
    assert any("lacks independent payload proof" in row for row in v._rdf_provenance_failures(altered))


def test_resealed_artifact_tamper_passes_binding_but_fails_publisher(tmp_path, monkeypatch):
    """Keep valid RDF identities, binding digests, accounting and transport pins."""
    import hashlib
    import json
    import sys

    from rdflib import RDF, Literal, URIRef

    root = Path(__file__).parents[1]
    sys.path.insert(0, str(root / "bindings/atlas/3.1/tools"))
    import build_fixtures as fixture_builder
    import validate as standalone

    specimen = json.loads(
        (root / "research/atlas-refresh-2026-09-27/independent/provenance/relation-specimen.json").read_text()
    )
    expected = specimen["native_payload"]
    inner = expected["publisherRelationDigest"]
    publisher = v._stock_vocabulary_view([], (), (), (), expected_relation_payloads={inner: expected})
    source_spec = v.SourceSpec(
        name="resealed-publisher-relation",
        kind="vocabulary",
        release_keys=("fixture",),
        inputs=(),
        rdf_source=v.RdfSourcePolicy(evaluated_native_payload_fields=frozenset()),
    )
    records = []
    verdicts = []
    for changed in (False, True):
        fixture = fixture_builder._base_fixture()
        fixture.rdf_zstd_all = True
        graph = fixture.asserted
        baseline = copy.deepcopy(graph)
        evidence = next(graph.subjects(RDF.type, fixture_builder.RKAF.EvidenceBinding))
        original = graph.value(evidence, fixture_builder.ATLAS.evidenceSourceRecord)
        release = graph.value(original, fixture_builder.ATLAS.inSourceRelease)
        payload = copy.deepcopy(expected)
        if changed:
            payload["editorialTransformation"]["reason"] = "invented"
        payload_digest = v._canonical_json_digest(payload)
        locator = "urn:ref:publisher-relation:" + inner[7:]
        basis = {
            "nativePayloadDigest": payload_digest,
            "sourceDigest": inner,
            "sourceLocator": locator,
            "sourceRelease": str(release),
        }
        record = URIRef(
            "urn:ref:atlas-source-record:" + hashlib.sha256(v._canonical_json_bytes(basis) + b"\n").hexdigest()
        )
        records.append(record)
        for predicate, obj in (
            (RDF.type, fixture_builder.ATLAS.SourceRecord),
            (fixture_builder.ATLAS.inSourceRelease, release),
            (fixture_builder.ATLAS.sourceLocator, URIRef(locator)),
            (fixture_builder.ATLAS.sourceDigest, Literal(payload_digest)),
            (
                fixture_builder.ATLAS.nativePayload,
                Literal(v._canonical_json_bytes(payload).decode(), datatype=RDF.JSON, normalize=False),
            ),
        ):
            graph.add((record, predicate, obj))
        graph.remove((evidence, fixture_builder.ATLAS.evidenceSourceRecord, original))
        graph.add((evidence, fixture_builder.ATLAS.evidenceSourceRecord, record))
        fixture_builder._refresh_evidence_for_source(graph, record)
        fixture_builder._reseal_adjudication(graph)
        for item in fixture.accounting["inputs"]:
            if item["sourceRelease"] == str(release):
                item["dispositions"].append(
                    {"sourceRecord": str(record), "status": "represented", "atlasResources": []}
                )
                item["dispositions"].sort(key=lambda row: row["sourceRecord"])
        fixture.accounting["totals"]["sourceRecords"] += 1
        fixture.accounting["totals"]["represented"] += 1
        fixture_builder._account_assertions(fixture)
        distribution = tmp_path / ("mutated" if changed else "baseline")
        fixture_builder._write_case(
            distribution,
            fixture,
            baseline_asserted=baseline,
            binding_digests=standalone._binding_digests(),
            corpus_digest=standalone.corpus_digest(),
            distribution_id="urn:ref:atlas-fixture:distribution:all-resource-profiles",
        )
        assert standalone.validate_distribution(distribution)["counts"]["sourceRecords"] == 28
        manifest = json.loads((distribution / "atlas-manifest.json").read_text())
        monkeypatch.setattr(
            v, "ASSERTED_GRAPH", next(row["id"] for row in manifest["graphs"] if row["role"] == "asserted")
        )
        atlas = v.read_atlas_source(
            distribution, tuple(row["path"].removeprefix("packs/") for row in manifest["packs"])
        )
        # Isolate this source's record after parsing the actual authenticated artifact.
        rid = str(record)
        atlas = replace(
            atlas,
            source_records=frozenset({rid}),
            record_targets={},
            native_payloads={rid: atlas.native_payloads[rid]},
            compact_native_payload_records=frozenset(),
        )
        verdicts.append(v._rdf_provenance_failures(v.SourcePair(source_spec, publisher, atlas)))
    assert records[0] != records[1]
    assert verdicts[0] == []
    assert any("payload differs from the independent source reconstruction" in row for row in verdicts[1])


def test_real_lc_sample_context_reuses_capture_and_isolates_pin_and_selection(tmp_path, monkeypatch):
    import io
    import zipfile

    raw_rows = (Path(__file__).parent / "fixtures/lc_external_endpoints_repair/external_links.nt").read_bytes()
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w") as archive:
        archive.writestr("external_links.nt", raw_rows)
    raw = packed.getvalue()
    (tmp_path / "sample.zip").write_bytes(raw)
    pin = v.SourcePin(
        path="sample.zip",
        sha256="sha256:" + v.hashlib.sha256(raw).hexdigest(),
        byte_length=len(raw),
        fmt="zip-ntriples",
        role="publisherEndpointSource",
        source_iri="https://id.loc.gov/download/externallinks.nt.zip",
    )
    names = ("agrovoc", "getty-aat")
    specs = tuple(
        replace(
            next(spec for spec in v.SOURCES if spec.name == f"lc-external-{name}-endpoints-2026-08-15"), inputs=(pin,)
        )
        for name in names
    )
    monkeypatch.setattr(v, "_LC_TARGET_ENDPOINT_COUNTS", dict.fromkeys(names, 1))
    original = v._parse_lc_endpoint_capture
    calls = []

    def counted(source_pin, payload):
        calls.append(source_pin)
        return original(source_pin, payload)

    monkeypatch.setattr(v, "_parse_lc_endpoint_capture", counted)
    first = v.build_context(tmp_path / "no-artifact", tmp_path, specs=specs)
    assert len(calls) == 1
    second = v.build_context(tmp_path / "no-artifact", tmp_path, specs=tuple(reversed(specs)))
    assert len(calls) == 2
    assert {pair.spec.name: pair.publisher for pair in first.pairs} == {
        pair.spec.name: pair.publisher for pair in second.pairs
    }
    assert [len(pair.publisher.concepts) for pair in first.pairs] == [1, 1]
    assert not first.pairs[0].publisher.concepts & first.pairs[1].publisher.concepts
    for spec in specs:
        separate = v._read_lc_external_target_endpoints(spec, {pin: raw})
        assert separate == next(pair.publisher for pair in first.pairs if pair.spec == spec)
    grouped = _old_lc_reader()(
        replace(specs[0], release_keys=tuple(key for spec in specs for key in spec.release_keys)), {pin: raw}
    )
    assert {
        resource: payload
        for pair in first.pairs
        for resource, payload in pair.publisher.expected_native_payloads.items()
    } == grouped.expected_native_payloads
    wrong = replace(pin, sha256="sha256:" + "0" * 64)
    bad = v.build_context(tmp_path / "no-artifact", tmp_path, specs=(specs[0], replace(specs[1], inputs=(wrong,))))
    assert bad.pin_failures
    assert {pair.spec.name for pair in bad.pairs} == {specs[0].name}


def test_docket_status_is_exact_publisher_evidence(tmp_path):
    payload = {"status": "discontinued"}
    record = v._StockVocabularyRecord(
        resource="urn:term",
        preferred_labels=(v._literal_value("Term", "en", None),),
        alternate_labels=(),
        notations=(),
        annotations=(),
        source_locator="urn:publisher",
        source_digest="sha256:" + "1" * 64,
        native_payload=payload,
    )
    publisher = v._stock_vocabulary_view([record], (), (), ())
    spec = v.SourceSpec(
        name="ferc-docket-prefixes",
        kind="vocabulary",
        release_keys=("ferc-docket-prefixes",),
        inputs=(),
        rdf_source=v.RdfSourcePolicy(evaluated_native_payload_fields=frozenset({"status"})),
    )
    atlas = replace(
        v.read_atlas_source(tmp_path, ()),
        source_records=frozenset({"urn:record"}),
        record_targets={"urn:record": "urn:term"},
        record_source_locators={"urn:record": "urn:publisher"},
        record_source_digests={"urn:record": v._canonical_json_digest(payload)},
        native_payloads={"urn:record": payload},
        record_statuses=frozenset({("urn:term", v._literal_value("discontinued", None, None))}),
    )
    assert v._rdf_provenance_failures(v.SourcePair(spec, publisher, atlas)) == []
    changed = replace(atlas, record_statuses=frozenset({("urn:term", v._literal_value("active", None, None))}))
    assert v._rdf_provenance_failures(v.SourcePair(spec, publisher, changed)) == [
        "ferc-docket-prefixes: recordStatus differs from exact publisher docket status"
    ]


def test_agency_placeholder_cannot_claim_another_unit(tmp_path):
    spec = v.SourceSpec(
        name="placeholder", kind="agency", release_keys=("another-mapping",), inputs=(), reader="placeholder"
    )
    context = v.build_context(tmp_path, tmp_path, specs=())
    context = replace(context, specs=(spec,), agency_result={})
    assert not context.loaded_specs()
    assert not v.check_agency_fidelity(context).passed
    assert any(
        "no exact executable agency comparison" in failure for failure in v.check_configuration(context).failures
    )


# One real S27 relation record from a bounded NASA thesaurus build. Raw context
# (thesaurus-SKOS.xml): "meteorological satellites" (#47375) skos:related
# "GOES 4" (#61980), and GOES 4 is skos:broader "GOES satellites" (#61976),
# itself skos:broader #47375 -- one hierarchy path, which is what S27 forbids.
S27_SPECIMEN = json.loads(
    (Path(__file__).parent / "fixtures/atlas_s27_relation_provenance/nasa-relation-record.json").read_text()
)


def _s27_failures(tmp_path, *, relations=None, payload=None):
    """Run relation provenance for the specimen against a stock (non-reconstructing) publisher view."""
    record = S27_SPECIMEN["sourceRecord"]
    payload = S27_SPECIMEN["nativePayload"] if payload is None else payload
    if relations is None:
        relations = {tuple(S27_SPECIMEN["publisherRelation"]), *map(tuple, S27_SPECIMEN["publisherHierarchy"])}
    publisher = replace(v._stock_vocabulary_view([], (), (), ()), relations=frozenset(relations))
    spec = v.SourceSpec(
        name="nasa-thesaurus-skos",
        kind="vocabulary",
        release_keys=("nasa-thesaurus-skos",),
        inputs=(),
        rdf_source=v.RdfSourcePolicy(evaluated_native_payload_fields=frozenset()),
    )
    atlas = replace(
        v.read_atlas_source(tmp_path, ()),
        source_records=frozenset({record}),
        native_payloads={record: payload},
        record_source_locators={record: S27_SPECIMEN["sourceLocator"]},
        record_source_digests={record: v._canonical_json_digest(payload)},
    )
    return v._rdf_provenance_failures(v.SourcePair(spec, publisher, atlas))


def test_s27_relation_present_in_publisher_bytes_passes(tmp_path):
    assert v._canonical_json_digest(S27_SPECIMEN["nativePayload"]) == S27_SPECIMEN["sourceDigest"]
    assert _s27_failures(tmp_path) == []


def test_s27_relation_absent_from_publisher_bytes_fails(tmp_path):
    relations = set(map(tuple, S27_SPECIMEN["publisherHierarchy"]))
    failures = _s27_failures(tmp_path, relations=relations)
    assert len(failures) == 1 and "is absent from publisher bytes" in failures[0]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("reason", "differs from the exact S27 transformation"),
        ("extra-field", "differs from the exact S27 transformation"),
        ("relation-object", "is absent from publisher bytes"),
        ("relation-digest", "publisherRelationDigest differs"),
        ("normalized-predicate", "is not an S27 relation"),
        ("no-hierarchy-path", "share no publisher hierarchy path"),
    ],
)
def test_s27_relation_mutations_fail_even_when_self_rehashed(tmp_path, mutation, expected):
    payload = copy.deepcopy(S27_SPECIMEN["nativePayload"])
    relations = None
    relation = payload["publisherRelation"]
    if mutation == "reason":
        payload["editorialTransformation"]["reason"] = "invented"
    elif mutation == "extra-field":
        payload["responseDigest"] = "sha256:" + "0" * 64
    elif mutation == "relation-object":
        relation["objectIri"] = relation["objectIri"] + "0"
        payload["publisherRelationDigest"] = v._canonical_json_digest(relation)
    elif mutation == "relation-digest":
        payload["publisherRelationDigest"] = "sha256:" + "0" * 64
    elif mutation == "normalized-predicate":
        relation["normalizedPredicateIri"] = v.SKOS + "broader"
    elif mutation == "no-hierarchy-path":
        relations = {tuple(S27_SPECIMEN["publisherRelation"])}
    # sourceDigest follows the mutated payload, so only the field comparison can catch it.
    assert any(expected in row for row in _s27_failures(tmp_path, relations=relations, payload=payload))
