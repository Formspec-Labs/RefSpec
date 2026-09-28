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
AGENCY_EVIDENCE_SHA256 = "sha256:fde4401ea78b2e0e5c1c758b90d32def2d81d40693098a5f3ca904e33344ef3b"
AGENCY_REVIEW_SHA256 = "sha256:4b6a8e01b2d589ad1a2fcad17406070da15c9d31c725f127450efc70ae2ba9ed"
AGENCY_VIEW_SHA256 = "sha256:c7dc9310f9c11cd346245d7cf882f9eaf69b70b25f59841ae6004dca4944866e"


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


def test_agency_digest_and_expected_rows_frozen_oracles(plans):
    c, d = plans
    assert agency.decision_failures(c, d) == []
    old = oracle("agency_digests")
    assert all(r["matches"] for r in old.recompute(c))
    assert old.aggregate(c) == agency.OWNER_AGGREGATE
    expected, details = agency.expected_from_plans(c, d)
    frozen_expected, frozen_details = oracle("agency_artifacts").expected_from_plans(c, d)
    # The one deliberate divergence from the frozen oracle: the view now states
    # each event original's roster parent (F6). Everything else still agrees.
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

    def check(g):
        return agency.check_rdf(
            g, c, d, expected, details, agency.sha(ROOT / "plans/agency-registry-batch-1-decisions.json"), endpoints
        )[0]

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
def test_review_manifest_external_pins_and_source_mutation(tmp_path, plans):
    base = EVIDENCE / "agency"
    c, d = plans
    mp = base / "audit-evidence-manifest.json"
    rp = base / "claim-receipt.json"
    assert agency.authenticate_agency_evidence(ROOT, mp, AGENCY_EVIDENCE_SHA256, rp, AGENCY_REVIEW_SHA256, c, d) == []
    with pytest.raises(ValueError, match="external digest mismatch"):
        agency.authenticate_agency_evidence(ROOT, mp, "sha256:wrong", rp, AGENCY_REVIEW_SHA256, c, d)
    manifest = json.loads(mp.read_text())
    member = manifest["members"][0]
    member["sha256"] = "sha256:" + "0" * 64
    changed = tmp_path / "manifest.json"
    changed.write_text(json.dumps(manifest))
    assert agency.authenticate_agency_evidence(
        ROOT, changed, "sha256:" + agency.sha(changed), rp, AGENCY_REVIEW_SHA256, c, d
    )


@pytest.mark.slow
@pytest.mark.reads_built_artifact
@pytest.mark.pinned_input(
    not (ROOT / "output/agency-registry-view/view-manifest.json").is_file(),
    reason="Retained dedicated agency view absent",
)
def test_real_agency_wrapper_checks_exact_dedicated_tables():
    base = EVIDENCE / "agency"
    view = ROOT / "output/agency-registry-view"
    distribution = ROOT / "output/atlas-3.1-agency-2026-09-27/distribution"
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
    assert result["comparedRows"] == {"bridges": 13, "events": 14, "non-emissions": 4}


@pytest.mark.slow
@pytest.mark.reads_built_artifact
@pytest.mark.pinned_input(
    not (ROOT / "output/agency-registry-view/view-manifest.json").is_file(),
    reason="Retained dedicated agency view absent",
)
def test_agency_view_semantic_mutation_with_valid_transport_pins(tmp_path):
    import hashlib
    import shutil

    import pyarrow as pa
    import pyarrow.parquet as pq

    original = ROOT / "output/agency-registry-view"
    assert original.is_dir(), "Dedicated bounded agency view must be supplied for replay"
    view = tmp_path / "view"
    shutil.copytree(original, view)
    path = view / "tables/agency-registry-events.parquet"
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows[0]["effective_date"] = "1900-01-01"
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    manifest_path = view / "view-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    member = next(m for m in manifest["members"] if m["path"] == str(path.relative_to(view)))
    member.update(byteLength=path.stat().st_size, sha256="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest())
    manifest_path.write_text(json.dumps(manifest))
    base = EVIDENCE / "agency"
    result = agency.verify_agency_artifacts(
        source_root=ROOT,
        distribution=ROOT / "output/atlas-3.1-agency-2026-09-27/distribution",
        agency_view=view,
        agency_view_manifest_sha256="sha256:" + agency.sha(manifest_path),
        agency_audit_evidence_manifest=base / "audit-evidence-manifest.json",
        agency_audit_evidence_sha256=AGENCY_EVIDENCE_SHA256,
        agency_review_receipt=base / "claim-receipt.json",
        agency_review_receipt_sha256=AGENCY_REVIEW_SHA256,
    )
    assert result["status"] == "failed"
    assert any(
        f["path"].startswith("agency-view/events/") and f["path"].endswith("/effective_date")
        for f in result["failures"]
    )
    assert all(not f["path"].startswith("view/member-") for f in result["failures"])


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
