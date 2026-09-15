"""Shared source observations preserve the existing table policies and bounded build."""

from __future__ import annotations

import json
import zipfile
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import usc_structure_oracle as oracle

from tools import build_usc_structure as builder

FIXTURES = Path(__file__).parent / "fixtures"
ANNUAL = FIXTURES / "usc-structure/annual-2012-title40-322-323.htm"
XML = FIXTURES / "uslm-source-links/title-05-s423.xml"


def release_rows(body, *, appendix=False):
    rows = defaultdict(set)
    builder.read_release_title(body, appendix=appendix, emit=lambda name, row: rows[name].add(row))
    return {name: rows[name] for name in oracle.release(body, appendix=appendix)}


def annual_rows(body, *, year=2012, title=40, appendix=False):
    rows = defaultdict(set)
    builder.read_annual_title(body, year=year, title=title, appendix=appendix,
                              emit=lambda name, row: rows[name].add(row))
    return {name: rows[name] for name in ("annual_sections", "annual_ranges")}


@pytest.mark.parametrize("name", ["title-05-s423.xml", "title-42-s242c.xml"])
@pytest.mark.parametrize("appendix", [False, True])
def test_real_xml_and_policy_mutations_match_frozen_kernels(name, appendix):
    original = (FIXTURES / "uslm-source-links" / name).read_bytes()
    variants = {
        "original": original,
        "missing-status": original.replace(b'<section ', b'<section status="" ', 1),
        "range": original.replace(b'/s423"', b'/s6...15a"'),
        "unicode-dash": original.replace(b'/s423"', '/s824s–1"'.encode()),
        "appendix-identifier": original.replace(b'/us/usc/t5/', b'/us/usc/t5a/'),
        "chapter": original.replace(b'<section ', b'<chapter identifier="/us/usc/t10/stA/ptI/ch1"/><section ', 1),
    }
    for mutation, body in variants.items():
        assert release_rows(body, appendix=appendix) == oracle.release(body, appendix=appendix), mutation


def test_annual_source_context_and_policy_mutations_match_frozen_kernel():
    original = ANNUAL.read_bytes()
    variants = {
        "original": original,
        "range-and-list": original.replace(b'/Sec. 323 -->', b'/Secs. 6 to 15a, 19, 25A -->'),
        "unbracketed-stub": original.replace(b'/[Sec. 322 -->', b'/Sec. 322 -->'),
        "unicode-dash": original.replace(b'/Sec. 323 -->', '/Sec. 824s–1 -->'.encode()),
        "unknown-text": original.replace(b'/Sec. 323 -->', b'/Secs. reserved text, 12 -->'),
        "no-usckey": original.replace(b'usckey:', b'unknown:'),
        "invalid-utf8": original.replace(b'/Sec. 323 -->', b'/Sec. 323\xff -->'),
    }
    for mutation, body in variants.items():
        assert annual_rows(body) == oracle.annual(body, year=2012, title=40), mutation
    assert annual_rows(original)["annual_sections"] == {(2012, 40, False, "323")}


# Frozen intentional differences from byte-regex scanning. These changes read
# actual markup; none changes the oracle's normalization or attestation policy.
PARSER_DIFFERENCES = ("single-quoted-attribute", "comment-is-not-element", "malformed-xml", "longer-structural-prefixes")


def test_only_named_parser_differences_are_intentional():
    bodies = {
        "single-quoted-attribute": b"<uscDoc><section identifier='/us/usc/t5/s1'/></uscDoc>",
        "comment-is-not-element": b'<uscDoc><!-- <section identifier="/us/usc/t5/s1"/> --></uscDoc>',
        "malformed-xml": b'<uscDoc><section identifier="/us/usc/t5/s1">',
        "longer-structural-prefixes": (FIXTURES / "usc-structure/structural-prefixes.xml").read_bytes(),
    }
    assert tuple(bodies) == PARSER_DIFFERENCES
    assert release_rows(bodies["single-quoted-attribute"])["sections"] == {(5, "1", "current")}
    assert oracle.release(bodies["single-quoted-attribute"])["sections"] == set()
    assert release_rows(bodies["comment-is-not-element"])["sections"] == set()
    assert oracle.release(bodies["comment-is-not-element"])["sections"] == {(5, "1", "current")}
    with pytest.raises(ValueError, match="malformed"):
        release_rows(bodies["malformed-xml"])
    assert oracle.release(bodies["malformed-xml"])["sections"] == {(5, "1", "current")}
    before = oracle.release(bodies["longer-structural-prefixes"])
    after = release_rows(bodies["longer-structural-prefixes"])
    assert before["subsections"] == {(10, "ta", "pti"), (14, "ti", "ch1"), (41, "ti", "da")}
    assert after["subsections"] == set()
    assert before["chapters"] == after["chapters"] == {(14, "1")}


def test_longer_prefix_fix_preserves_alphabetic_sections_and_ch1_section_parts():
    body = b'<uscDoc><section identifier="/us/usc/t5/sA"/><subsection identifier="/us/usc/t5/sA/a"/><paragraph identifier="/us/usc/t5/s1/ch1"/></uscDoc>'
    assert release_rows(body) == oracle.release(body)
    assert release_rows(body)["subsections"] == {(5, "a", "a"), (5, "1", "ch1")}


def test_frozen_source_attributed_correction_set_names_only_longer_prefixes():
    correction = json.loads((FIXTURES / "usc-structure/structural-prefix-corrections.json").read_text())
    expected = {tuple(entry["row"]) for entry in correction["rows"]}
    assert len(expected) == 364
    for entry in correction["rows"]:
        parts = entry["identifier"].split("/")
        assert parts[4].startswith(("st", "sch", "spt"))
        assert entry["row"] == [int(parts[3][1:]), parts[4][1:].lower(), parts[5].lower()]
        assert entry["element"] in ("chapter", "part", "division")
    frozen_path = Path(__file__).parents[1] / "research/evidence/usc-section-oracle-2026-08-24/usc-oracle-subsections.parquet"
    frozen = {tuple(row.values()) for row in pq.read_table(frozen_path).to_pylist()}
    assert expected <= frozen
    assert len(frozen - expected) == 159845


def archive(path, entries):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, body in entries:
            bundle.writestr(name, body)
    return path


def test_candidate_has_six_existing_schemas_and_receipt_without_changing_pins(tmp_path):
    corpus = archive(tmp_path / "corpus.zip", [("usc05.xml", XML.read_bytes())])
    annual = archive(tmp_path / "2012.zip", [("2012/2012USC40.htm", ANNUAL.read_bytes()), ("2012/usc.css", b"body {}")])
    output = tmp_path / "candidate"
    receipt = builder.build(corpus=corpus, annual=[(2012, annual)], output=output)
    assert receipt["adopted"] is False
    assert set(receipt["files"]) == {filename for filename, _ in builder.TABLES.values()}
    assert json.loads((output / "receipt.json").read_text()) == receipt
    assert receipt["inputs"][1]["members"][0]["selected"]
    assert not receipt["inputs"][1]["members"][1]["selected"]
    expected = {**oracle.release(XML.read_bytes()), **oracle.annual(ANNUAL.read_bytes(), year=2012, title=40)}
    for name, (filename, _) in builder.TABLES.items():
        table = pq.read_table(output / filename)
        assert {tuple(row.values()) for row in table.to_pylist()} == expected[name]
        assert all(field.type in (pa.int32(), pa.string(), pa.bool_()) for field in table.schema)
        assert table.schema.field("title").type == pa.int32()
    assert not list(tmp_path.glob(".usc-structure-*"))
    with pytest.raises(ValueError, match="already exists"):
        builder.build(corpus=corpus, annual=[], output=output)


def test_more_than_one_insert_batch_preserves_rows_and_deduplicates(tmp_path):
    sections = b"".join(f'<section identifier="/us/usc/t5/s{number}"/>'.encode() for number in range(1100))
    corpus = archive(tmp_path / "corpus.zip", [("usc05.xml", b"<uscDoc>" + sections + sections + b"</uscDoc>")])
    output = tmp_path / "candidate"
    receipt = builder.build(corpus=corpus, annual=[], output=output)
    assert receipt["files"]["usc-oracle-sections.parquet"]["rows"] == 1100
    table = pq.read_table(output / "usc-oracle-sections.parquet")
    assert set(table.column("section").to_pylist()) == {str(number) for number in range(1100)}


@pytest.mark.parametrize("failure", ["bad-member", "malformed-tail", "wrong-year", "repeated-year", "no-titles"])
def test_refused_build_never_leaves_candidate_or_staging_directory(tmp_path, failure):
    xml = XML.read_bytes()[:-10] if failure == "malformed-tail" else XML.read_bytes()
    corpus = archive(tmp_path / "corpus.zip", [("usc05.xml", xml)])
    annual_entries = [("2012/2012USC40.htm", ANNUAL.read_bytes())]
    if failure == "bad-member":
        annual_entries.append(("2012/unclassified.htm", b"unexpected"))
    if failure == "no-titles":
        annual_entries = [("2012/usc.css", b"body {}")]
    annual = archive(tmp_path / "2012.zip", annual_entries)
    selected = [(2013 if failure == "wrong-year" else 2012, annual)]
    if failure == "repeated-year":
        selected *= 2
    with pytest.raises(ValueError):
        builder.build(corpus=corpus, annual=selected, output=tmp_path / "candidate")
    assert not (tmp_path / "candidate").exists()
    assert not list(tmp_path.glob(".usc-structure-*"))


def test_cli_requires_explicit_annual_year_and_reports_refusal(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        builder.main(["--corpus", "missing", "--annual", "2012.zip", "--output", str(tmp_path / "new")])
    assert error.value.code == 2
    assert "YEAR=PATH" in capsys.readouterr().err
    with pytest.raises(SystemExit) as error:
        builder.main(["--corpus", "missing", "--output", str(tmp_path / "new")])
    assert error.value.code == 1
    assert "build failed" in capsys.readouterr().err
