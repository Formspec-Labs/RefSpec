"""Real retained readings plus normalized-output mutations, independent of producers."""

import copy
import importlib.util
import json
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest
import rdflib

from refspec.atlas.generation import select_atlas_generation
from tools import atlas_independent_agency as agency
from tools import atlas_independent_pdf as pdf

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "research/atlas-refresh-2026-09-27/independent"
PDF_PATHS = {
    "ferc-document-class-types": ROOT / "output/registry-real-data-sources/ferc-class-types-january-2025.pdf",
    "ferc-docket-prefixes": ROOT / "output/registry-real-data-sources/ferc-docket-prefix-june-2025.pdf",
    "unified-agenda-legal-authority-citation-types": ROOT
    / "tests/fixtures/unified_agenda_codes/risc-preamble-202210.pdf",
}


# The external pins the release job passes (.github/workflows/release.yml), so a
# changed manifest or receipt fails here too instead of being re-hashed into agreement.
AGENCY_EVIDENCE_SHA256 = "sha256:ea238cddc9f5089124d66f4ef1a16d55a05c2ed94099bf3a1dff6687093af996"
AGENCY_REVIEW_SHA256 = "sha256:201b489c479ce7f5339079195310cb45fb6b0bd362ce7f7ac4d76de083c2576d"
AGENCY_VIEW_SHA256 = "sha256:7a806ea060c0c7a0ee37a991f443edc1a1f9ba74a1f5e1007db1e4e28cb23b7d"
OPM_WORKBOOK = ROOT / agency.OPM_WORKBOOK


def oracle(name):
    path = ROOT / "tests/oracles/atlas_refresh" / f"{name}.py.txt"
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(path)))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.mark.slow
@pytest.mark.parametrize(
    "key",
    [
        pytest.param(key, marks=pytest.mark.pinned_input(not path.is_file(), reason="Pinned PDF absent"))
        for key, path in PDF_PATHS.items()
    ],
)
def test_pdf_real_exact_artifact_population_and_fields(key):
    import shutil

    assert PDF_PATHS[key].is_file(), "Pinned PDF absent: fetch the declared source input"
    assert shutil.which("pdftotext"), "Poppler pdftotext is required for the explicit PDF replay tier"
    observed = pdf.read_pdf_rows(key, PDF_PATHS[key].read_bytes())
    expected = json.loads((EVIDENCE / "omitted-vocabularies/receipts/artifact-observed.json").read_text())[key]
    rows = copy.deepcopy(observed["rows"])
    for row in rows:
        row["source_digest"] = row.pop("input_digest")
    assert agency.differences(expected, rows) == []
    for field in rows[0]:
        changed = copy.deepcopy(rows)
        changed[0][field] = "changed"
        assert agency.differences(expected, changed), field
    assert agency.differences(expected, rows[:-1])
    assert agency.differences(expected, [*rows, rows[0]])
    with pytest.raises(ValueError, match="pin mismatch"):
        pdf.read_pdf_rows(key, PDF_PATHS[key].read_bytes() + b"changed")


def test_pdf_frozen_oracle_and_explicit_reading_divergence(tmp_path):
    source = EVIDENCE / "omitted-vocabularies/receipts"
    for name in ("class-bbox.html", "docket-bbox.html", "ua-glossary.txt"):
        (tmp_path / name).write_bytes((source / name).read_bytes())
    subprocess.run(
        [sys.executable, str(ROOT / "tests/oracles/atlas_refresh/pdf_tables.py.txt"), "--output-dir", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    old = json.loads((tmp_path / "independent-extraction.json").read_text())
    for kind, field in [("class", "classes"), ("docket", "dockets")]:
        got = pdf.extract_tables((tmp_path / f"{kind}-bbox.html").read_text(), kind)
        assert [(r["page"], r["native"]) for r in got] == [(r["page"], r["native"]) for r in old[field]]
    exception = pdf.reading_exception(
        pdf.PINS["ferc-document-class-types"][0], 7, 233, "type_description", pdf.VISIBLE + " lines"
    )
    assert exception["reviewed_reading"] == pdf.VISIBLE
    args = [pdf.PINS["ferc-document-class-types"][0], 7, 233, "type_description", pdf.VISIBLE + " lines"]
    for index, value in enumerate(["0" * 64, 6, 234, "library", pdf.VISIBLE + " changed"]):
        changed = args.copy()
        changed[index] = value
        with pytest.raises(ValueError):
            pdf.reading_exception(*changed)


@pytest.fixture
def plans():
    return (
        json.loads((ROOT / "plans/agency-registry-batch-1-candidates.json").read_text()),
        json.loads((ROOT / "plans/agency-registry-batch-1-decisions.json").read_text()),
    )


@pytest.fixture
def alias_plans():
    cp, dp, *_ = agency.BATCHES[-1]
    return json.loads((ROOT / cp).read_text()), json.loads((ROOT / dp).read_text())


def test_agency_digest_and_expected_rows_frozen_oracles(plans):
    c, d = plans
    assert agency.decision_failures(c, d) == []
    old = oracle("agency_digests")
    assert all(r["matches"] for r in old.recompute(c))
    assert old.aggregate(c) == agency.OWNER_AGGREGATE
    expected, details = agency.expected_from_plans(c, d)
    frozen_expected, frozen_details = oracle("agency_artifacts").expected_from_plans(c, d)
    # The deliberate divergences from the frozen oracle: the view now states
    # each event original's roster parent (F6), and an aliases table batch 1
    # leaves empty (REF-075). Everything else still agrees.
    assert expected.pop("aliases") == []
    assert details == frozen_details
    assert {key for row in expected["events"] for key in row} - {
        key for row in frozen_expected["events"] for key in row
    } == {"original_parents"}
    without = [{key: value for key, value in row.items() if key != "original_parents"} for row in expected["events"]]
    assert {**expected, "events": agency.sorted_rows(without)} == frozen_expected
    for field in ("date_basis", "effective_date", "originals", "public_records"):
        changed = copy.deepcopy(c)
        changed["events"][0][field] = None
        assert agency.decision_failures(changed, d)
    changed = copy.deepcopy(c)
    changed["candidates"][0]["effect_note"] = "changed"
    failures = agency.decision_failures(changed, d)
    assert any(f["path"] == "candidates_digest" for f in failures)
    assert not any(f["path"].startswith("decision-digest/") for f in failures)
    for mode in ("missing", "unknown", "stale"):
        changed = copy.deepcopy(d)
        key = next(iter(changed["decisions"]))
        if mode == "missing":
            del changed["decisions"][key]
        elif mode == "unknown":
            changed["decisions"]["unknown"] = changed["decisions"][key]
        else:
            changed["decisions"][key]["content_digest"] = "sha256:wrong"
        assert agency.decision_failures(c, changed)


@pytest.mark.parametrize(
    "table,field",
    [
        ("events", f)
        for f in (
            "effective_date",
            "date_basis",
            "functions_taken",
            "originals",
            "original_parents",
            "result",
            "public_records",
            "decision",
        )
    ]
    + [("bridges", f) for f in ("subject_parent", "object_parent", "reasoning", "relation", "decision")]
    + [("non-emissions", f) for f in ("reason", "subject", "object", "decision")],
)
def test_agency_normalized_output_mutations(plans, table, field):
    expected, _ = agency.expected_from_plans(*plans)
    changed = copy.deepcopy(expected)
    changed[table][0][field] = "changed"
    assert agency.differences(expected, changed)
    changed = copy.deepcopy(expected)
    changed[table].pop()
    assert agency.differences(expected, changed)
    changed = copy.deepcopy(expected)
    changed[table].append(changed[table][0])
    assert agency.differences(expected, changed)


def test_real_agency_rdf_and_semantic_mutations(plans):
    path = ROOT / "tests/fixtures/atlas_independent_adapters/agency-registry.nq.zst"
    c, d = plans
    expected, details = agency.expected_from_plans(c, d)
    graph, _ = agency.read_graph(path)
    _, receipts, _ = agency.check_raw_endpoints(ROOT, c)
    endpoints = agency.independent_endpoint_records(c, receipts)

    decisions_file = ("plans/agency-registry-batch-1-decisions.json", agency.sha(ROOT / "plans/agency-registry-batch-1-decisions.json"))

    def check(g):
        return agency.check_rdf(g, c, d, expected, details, dict.fromkeys(d["decisions"], decisions_file), endpoints)[0]

    assert check(graph) == []
    assert (
        oracle("agency_artifacts").check_rdf(
            graph, c, d, expected, details, agency.sha(ROOT / "plans/agency-registry-batch-1-decisions.json")
        )[0]
        == []
    )
    for kind, field in [
        ("event", "dateBasis"),
        ("event", "results"),
        ("event", "originals"),
        ("event", "effectiveDate"),
        ("endpointRecord", "sourceDigest"),
        ("endpointRecord", "sourceLocator"),
        ("endpointRecord", "releaseDigest"),
        ("endpointRecord", "publisher"),
    ]:
        record, literal = next(
            (s, o) for s, o in graph.subject_objects(agency.A.nativePayload) if kind in json.loads(str(o))
        )
        payload = json.loads(str(literal))
        payload[kind][field] = "changed"
        mutated = rdflib.Literal(agency.canonical(payload), datatype=literal.datatype)
        graph.remove((record, agency.A.nativePayload, literal))
        graph.add((record, agency.A.nativePayload, mutated))
        # Repair the outer payload hash: semantic comparison still must fail.
        old_hash = next(graph.objects(record, agency.A.sourceDigest))
        graph.set((record, agency.A.sourceDigest, rdflib.Literal(agency.digest(payload))))
        assert check(graph), (kind, field)
        graph.set((record, agency.A.nativePayload, literal))
        graph.set((record, agency.A.sourceDigest, old_hash))
    rejected = expected["non-emissions"][0]
    node = rdflib.URIRef("urn:mutation:rejected-bridge")
    for p, v in [
        (rdflib.RDF.subject, rejected["subject"]),
        (rdflib.RDF.predicate, str(agency.A.sameEntityAs)),
        (rdflib.RDF.object, rejected["object"]),
    ]:
        graph.add((node, p, rdflib.URIRef(v)))
    assert check(graph)


def test_missing_agency_evidence_is_unevaluated():
    assert agency.verify_agency_artifacts(source_root=ROOT, distribution=ROOT)["status"] == "unevaluated"


@pytest.mark.slow
@pytest.mark.pinned_input(
    not (ROOT / "output/atlas-refresh-2026-09-27-evidence/agency-primary-sources").is_dir(),
    reason="Retained primary source originals absent",
)
def test_review_manifest_external_pins_and_source_mutation(tmp_path, plans, alias_plans):
    base = EVIDENCE / "agency"
    c, d = plans
    mp = base / "audit-evidence-manifest.json"
    rp = base / "claim-receipt.json"

    def authenticate(manifest=mp, manifest_pin=AGENCY_EVIDENCE_SHA256, receipt=rp, receipt_pin=AGENCY_REVIEW_SHA256):
        return agency.authenticate_agency_evidence(
            ROOT, manifest, manifest_pin, receipt, receipt_pin, c, d, alias_batch=alias_plans
        )

    assert authenticate() == []
    with pytest.raises(ValueError, match="external digest mismatch"):
        authenticate(manifest_pin="sha256:wrong")
    with pytest.raises(ValueError, match="no alias batch"):
        agency.authenticate_agency_evidence(ROOT, mp, AGENCY_EVIDENCE_SHA256, rp, AGENCY_REVIEW_SHA256, c, d)
    manifest = json.loads(mp.read_text())
    member = manifest["members"][0]
    member["sha256"] = "sha256:" + "0" * 64
    changed = tmp_path / "manifest.json"
    changed.write_text(json.dumps(manifest))
    assert authenticate(manifest=changed, manifest_pin="sha256:" + agency.sha(changed))
    # The alias review binds each alias's records: a reworded passage, a dropped alias, or a
    # re-pointed FR record in the receipt fails, even under a fresh external pin.
    for mutate, path in [
        (lambda r: r["aliasReview"]["aliases"][0]["claims"][0]["evidence"][0].update(passage="changed"), "/records"),
        (lambda r: r["aliasReview"]["aliases"].pop(), "review/alias-population"),
        (lambda r: r["aliasReview"]["aliases"][0].update(fr="urn:ref:federal-register-agency:1"), "/fr"),
    ]:
        receipt = json.loads(rp.read_text())
        mutate(receipt)
        changed_receipt = tmp_path / "receipt.json"
        changed_receipt.write_text(json.dumps(receipt))
        failures = authenticate(receipt=changed_receipt, receipt_pin="sha256:" + agency.sha(changed_receipt))
        assert any(path in f["path"] for f in failures), (path, failures)


@pytest.mark.slow
@pytest.mark.reads_built_artifact
@pytest.mark.pinned_input(
    not (ROOT / "output/agency-registry-view/view-manifest.json").is_file(),
    reason="Retained dedicated agency view absent",
)
def test_real_agency_wrapper_checks_exact_dedicated_tables():
    base = EVIDENCE / "agency"
    view = ROOT / "output/agency-registry-view"
    distribution = select_atlas_generation(ROOT / "output/atlas-3.1-agency-2026-09-27/distribution").distribution
    assert (view / "view-manifest.json").is_file(), "Dedicated bounded agency view must be supplied for replay"
    result = agency.verify_agency_artifacts(
        source_root=ROOT,
        distribution=distribution,
        agency_view=view,
        agency_view_manifest_sha256=AGENCY_VIEW_SHA256,
        agency_audit_evidence_manifest=base / "audit-evidence-manifest.json",
        agency_audit_evidence_sha256=AGENCY_EVIDENCE_SHA256,
        agency_review_receipt=base / "claim-receipt.json",
        agency_review_receipt_sha256=AGENCY_REVIEW_SHA256,
    )
    assert result["status"] == "passed", result["failures"]
    assert result["comparedRows"] == {
        "bridges": 13,
        "events": 15,
        "non-emissions": 11,
        "aliases": 63,
        "current-successors": 15,
        "projection": 321,
        "projection-unresolved": 10,
        "organizations": 472,
    }
    assert len(result["aliasRecordsRead"]) == 62 and all(r["match"] for r in result["aliasRecordsRead"])


def _remove(rows, key, value):
    """Drop the one row whose ``key`` is ``value``: a missing row, not a changed one."""
    (index,) = [i for i, row in enumerate(rows) if row[key] == value]
    rows.pop(index)


# One planted error per view table, each a value an honest producer bug could write.
PLANTED_VIEW_ERRORS = {
    "events": ("agency-registry-events", lambda rows: rows[0].update(effective_date="1900-01-01")),
    # An alias resolved to the wrong FR record: the Army to the Navy's department.
    "aliases": (
        "agency-registry-aliases",
        lambda rows: next(r for r in rows if r["alias_id"] == "alias:army").update(
            fr_resource="urn:ref:federal-register-agency:378"
        ),
    ),
    # A rejected alias silently dropped instead of recorded.
    "non-emissions": ("agency-registry-non-emissions", lambda rows: _remove(rows, "item_id", "alias:education")),
    # A missing organization (FR 520, Veterans Affairs Department).
    "organizations": ("agency-registry-organizations", lambda rows: _remove(rows, "fr_id", 520)),
    # A REF-038 code projected onto the wrong organization.
    "projection": (
        "agency-projection",
        lambda rows: next(r for r in rows if r["source_value"] == "ABMC").update(
            org="urn:ref:federal-register-agency:21"
        ),
    ),
    # An abstention whose reason was rewritten.
    "projection-unresolved": (
        "agency-projection-unresolved",
        lambda rows: rows[0].update(reason="genuineCollisionNamesCannotBreak"),
    ),
}


@pytest.mark.slow
@pytest.mark.reads_built_artifact
@pytest.mark.pinned_input(
    not (ROOT / "output/agency-registry-view/view-manifest.json").is_file(),
    reason="Retained dedicated agency view absent",
)
@pytest.mark.parametrize("table", sorted(PLANTED_VIEW_ERRORS))
def test_agency_view_semantic_mutation_with_valid_transport_pins(tmp_path, table):
    """A planted wrong value, re-sealed so every transport pin agrees, still fails on its own table."""
    import hashlib
    import shutil

    import pyarrow as pa
    import pyarrow.parquet as pq

    original = ROOT / "output/agency-registry-view"
    assert original.is_dir(), "Dedicated bounded agency view must be supplied for replay"
    view = tmp_path / "view"
    shutil.copytree(original, view)
    name, plant = PLANTED_VIEW_ERRORS[table]
    path = view / f"tables/{name}.parquet"
    parquet = pq.read_table(path)
    rows = parquet.to_pylist()
    plant(rows)
    pq.write_table(pa.Table.from_pylist(rows, schema=parquet.schema), path)
    manifest_path = view / "view-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    member = next(m for m in manifest["members"] if m["path"] == str(path.relative_to(view)))
    member.update(byteLength=path.stat().st_size, sha256="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest())
    manifest_path.write_text(json.dumps(manifest))
    base = EVIDENCE / "agency"
    result = agency.verify_agency_artifacts(
        source_root=ROOT,
        distribution=select_atlas_generation(ROOT / "output/atlas-3.1-agency-2026-09-27/distribution").distribution,
        agency_view=view,
        agency_view_manifest_sha256="sha256:" + agency.sha(manifest_path),
        agency_audit_evidence_manifest=base / "audit-evidence-manifest.json",
        agency_audit_evidence_sha256=AGENCY_EVIDENCE_SHA256,
        agency_review_receipt=base / "claim-receipt.json",
        agency_review_receipt_sha256=AGENCY_REVIEW_SHA256,
    )
    assert result["status"] == "failed"
    assert result["failures"], table
    assert all(f["path"].startswith(f"agency-view/{table}/") for f in result["failures"]), result["failures"]


def test_agency_reads_resolved_authenticated_capture_paths(tmp_path, plans):
    c, _d = plans
    logical = "tests/fixtures/federal_register_native_controls/fr-agencies-2026-08-15.json"
    path = tmp_path / "caller-resolved-roster.json"
    path.write_bytes((ROOT / logical).read_bytes())
    sources = {logical: path}
    errors, receipts, _ = agency.check_raw_endpoints(ROOT, c, sources)
    assert errors == []
    assert any(row["resolvedSourcePath"] == str(path) for row in receipts)
    rows = json.loads(path.read_text())
    selected_id = c["candidates"][0]["source"]["id"]
    next(row for row in rows if row["id"] == selected_id)["name"] = "Mutated caller-selected source"
    path.write_text(json.dumps(rows))
    assert agency.check_raw_endpoints(ROOT, c, sources)[0]


def test_every_batch_joins_in_the_expected_rows():
    """Pin the merge: all three batches' rows, FNS -> FNA among the current successors, one reviewer, no item twice."""

    batches = [
        (json.loads((ROOT / cp).read_text()), json.loads((ROOT / dp).read_text())) for cp, dp, *_ in agency.BATCHES
    ]
    for (c, d), (_, _, aggregate, covers) in zip(batches, agency.BATCHES, strict=True):
        assert agency.decision_failures(c, d, aggregate, covers) == []
    expected, details = agency.expected_from_batches(batches)
    assert {key: len(rows) for key, rows in expected.items()} == {
        "bridges": 13,
        "events": 15,
        "non-emissions": 11,
        "aliases": 63,
        "current-successors": 15,
    }
    fna = "urn:ref:federal-register-agency:"
    assert {"original": fna + "200", "successor": fna + "625"} in expected["current-successors"]
    assert details["event:fr200"]["effectiveDate"] == "2026-06-24"
    plan, decisions = agency.merged_plans(batches)
    assert len(plan["events"]) == 10 and len(decisions["decisions"]) == 97
    with pytest.raises(ValueError, match="decided in two"):
        agency.merged_plans([*batches, batches[1]])


def test_alias_answers_follow_their_own_effects(alias_plans):
    """Adopted aliases become alias rows with the decided relation; a "no" a non-emission; an unruled answer refuses."""
    c, d = alias_plans
    expected, _ = agency.expected_from_plans(c, d)
    army = next(r for r in expected["aliases"] if r["alias_id"] == "alias:army")
    assert (d["decisions"]["alias:army"]["answer"], army["fr_relation"]) == ("2", "partOf")
    assert {r["item_id"] for r in expected["non-emissions"]} == {
        a for a, x in d["decisions"].items() if x["answer"] == "no"
    }
    changed = copy.deepcopy(d)
    changed["decisions"]["alias:army"]["answer"] = "9"
    with pytest.raises(ValueError, match="no effect"):
        agency.expected_from_plans(c, changed)
    # An undecided alias is held: no row, and the decision population still checks.
    held = copy.deepcopy(d)
    del held["decisions"]["alias:army"]
    assert "alias:army" not in {r["alias_id"] for r in agency.expected_from_plans(c, held)[0]["aliases"]}
    assert agency.decision_failures(c, held, agency.ALIAS_OWNER_AGGREGATE, agency.ALIAS_COVERED) == []
    stale = copy.deepcopy(d)
    stale["decisions"]["alias:army"]["content_digest"] = "sha256:wrong"
    assert agency.decision_failures(c, stale, agency.ALIAS_OWNER_AGGREGATE, agency.ALIAS_COVERED)


def test_alias_records_are_read_and_a_changed_record_is_caught(tmp_path, alias_plans):
    """Every cited record re-hashes and holds its passage; changed bytes or a reworded passage fail."""
    c, d = alias_plans
    errors, reads = agency.check_alias_records(ROOT, (c, d))
    assert errors == [] and len(reads) == 62
    record = c["aliases"][0]["records"][0]
    logical = f"{agency.ALIAS_RECORDS_DIR}/{record['file']}"
    tampered = tmp_path / Path(record["file"]).name
    tampered.write_bytes((ROOT / logical).read_bytes() + b"<!-- one byte more -->")
    errors, _ = agency.check_alias_records(ROOT, (c, d), {logical: tampered})
    assert any(e["path"].endswith("/sha256") for e in errors)
    reworded = copy.deepcopy(c)
    reworded["aliases"][0]["records"][0]["passage"] += " and the Coast Guard"
    errors, _ = agency.check_alias_records(ROOT, (reworded, d))
    assert [e["path"].rsplit("/", 1)[1] for e in errors] == ["passageFound"]


@pytest.mark.pinned_input(not OPM_WORKBOOK.is_file(), reason="Pinned OPM EHRI workbook absent")
def test_alias_rosters_and_projection_from_raw_captures(alias_plans):
    """Alias names re-read from the raw rosters, FR ancestry, mechanical rules, and REF-038 from its adjudication."""
    c, d = alias_plans
    rosters = agency.read_rosters(ROOT)
    releases = c["inputs"]["roster_releases"]
    projection, unresolved = agency.expected_projection(ROOT, rosters, releases)
    assert (len(projection), len(unresolved)) == (321, 10)
    opm = agency.read_opm_names(ROOT)
    assert agency.check_alias_rosters((c, d), rosters, opm, projection) == []
    for alias_id, side, field, value, path in [
        ("alias:veterans-health-administration", "target", "publisher_name", "VETERANS HEALTH", "/target/raw-roster"),
        ("alias:bureau-of-land-management", "fr_record", "id", 253, "/mechanical/"),
    ]:
        changed = copy.deepcopy(c)
        alias = next(a for a in changed["aliases"] if a["alias_id"] == alias_id)
        alias[side][field] = value
        failures = agency.check_alias_rosters((changed, d), rosters, opm, projection)
        assert any(path in f["path"] for f in failures), (alias_id, failures)
    organizations = agency.expected_organizations(rosters, projection, [])
    assert len(organizations) == 472
    abmc = next(r for r in organizations if r["fr_id"] == 20)
    assert abmc["regulations_gov_codes"] == ["ABMC"]
