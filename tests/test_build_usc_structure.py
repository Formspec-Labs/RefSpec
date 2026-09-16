"""Shared source observations preserve the existing table policies and bounded build."""

from __future__ import annotations

import json
import zipfile
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import usc_structure_archive_oracle as archive_oracle
import usc_structure_oracle as oracle
from spicy_docs.sources.uscode import ReleasePoint

from tools import build_usc_structure as builder

FIXTURES = Path(__file__).parent / "fixtures"
ANNUAL = FIXTURES / "usc-structure/annual-2012-title40-322-323.htm"
XML = FIXTURES / "uslm-source-links/title-05-s423.xml"
RELEASE = ReleasePoint(119, 102)


def release_rows(body, *, appendix=False):
    rows = defaultdict(set)
    builder.read_release_title(body, appendix=appendix, emit=lambda name, row: rows[name].add(row))
    return {name: rows[name] for name in oracle.release(body, appendix=appendix)}


def annual_rows(body, *, year=2012, title=40, appendix=False):
    rows = defaultdict(set)
    builder.read_annual_title(
        body, year=year, title=title, appendix=appendix, emit=lambda name, row: rows[name].add(row)
    )
    return {name: rows[name] for name in ("annual_sections", "annual_ranges")}


@pytest.mark.parametrize("name", ["title-05-s423.xml", "title-42-s242c.xml"])
@pytest.mark.parametrize("appendix", [False, True])
def test_real_xml_and_policy_mutations_match_frozen_kernels(name, appendix):
    original = (FIXTURES / "uslm-source-links" / name).read_bytes()
    variants = {
        "original": original,
        "missing-status": original.replace(b"<section ", b'<section status="" ', 1),
        "range": original.replace(b'/s423"', b'/s6...15a"'),
        "unicode-dash": original.replace(b'/s423"', '/s824s–1"'.encode()),
        "appendix-identifier": original.replace(b"/us/usc/t5/", b"/us/usc/t5a/"),
        "chapter": original.replace(b"<section ", b'<chapter identifier="/us/usc/t10/stA/ptI/ch1"/><section ', 1),
    }
    for mutation, body in variants.items():
        assert release_rows(body, appendix=appendix) == oracle.release(body, appendix=appendix), mutation


def test_annual_source_context_and_policy_mutations_match_frozen_kernel():
    original = ANNUAL.read_bytes()
    variants = {
        "original": original,
        "range-and-list": original.replace(b"/Sec. 323 -->", b"/Secs. 6 to 15a, 19, 25A -->"),
        "unbracketed-stub": original.replace(b"/[Sec. 322 -->", b"/Sec. 322 -->"),
        "unicode-dash": original.replace(b"/Sec. 323 -->", "/Sec. 824s–1 -->".encode()),
        "unknown-text": original.replace(b"/Sec. 323 -->", b"/Secs. reserved text, 12 -->"),
        "no-usckey": original.replace(b"usckey:", b"unknown:"),
        "invalid-utf8": original.replace(b"/Sec. 323 -->", b"/Sec. 323\xff -->"),
    }
    for mutation, body in variants.items():
        assert annual_rows(body) == oracle.annual(body, year=2012, title=40), mutation
    assert annual_rows(original)["annual_sections"] == {(2012, 40, False, "323")}


# Frozen intentional differences from byte-regex scanning. These changes read
# actual markup; none changes the oracle's normalization or attestation policy.
PARSER_DIFFERENCES = (
    "single-quoted-attribute",
    "comment-is-not-element",
    "malformed-xml",
    "longer-structural-prefixes",
)


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
    frozen_path = (
        Path(__file__).parents[1] / "research/evidence/usc-section-oracle-2026-08-24/usc-oracle-subsections.parquet"
    )
    frozen = {tuple(row.values()) for row in pq.read_table(frozen_path).to_pylist()}
    assert expected <= frozen
    assert len(frozen - expected) == 159845


def native_xml(body: bytes | None = None) -> bytes:
    # Exact retained header plus the existing section excerpt, not a claim that
    # the assembled unit fixture is a complete publisher title.
    prefix = (FIXTURES / "usc-structure/release-119-102-title05-header.xml.part").read_bytes()
    excerpt = XML.read_bytes() if body is None else body
    return prefix + excerpt.partition(b">")[2].removesuffix(b"</uscDoc>") + b"</main></uscDoc>"


def native_annual(body: bytes | None = None) -> bytes:
    prefix = (FIXTURES / "usc-structure/annual-2012-title40-header.html.part").read_bytes()
    return prefix + b"<body>" + (ANNUAL.read_bytes() if body is None else body) + b"</body></html>"


def archive(path, entries):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, body in entries:
            bundle.writestr(name, body)
    return path


def test_candidate_has_six_existing_schemas_and_receipt_without_changing_pins(tmp_path):
    corpus = archive(tmp_path / "corpus.zip", [("usc05.xml", native_xml())])
    annual = archive(tmp_path / "2012.zip", [("2012/2012USC40.htm", native_annual()), ("2012/usc.css", b"body {}")])
    output = tmp_path / "candidate"
    receipt = builder.build(corpus=corpus, release_point=RELEASE, annual=[(2012, annual)], output=output)
    assert receipt["adopted"] is False
    assert receipt["format"] == "refspec-usc-structure-candidate-v2"
    assert receipt["releasePoint"] == "119-102"
    assert receipt["bounds"]["totalExpandedBytes"] == 1024**3
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
        builder.build(corpus=corpus, release_point=RELEASE, annual=[], output=output)


def test_more_than_one_insert_batch_preserves_rows_and_deduplicates(tmp_path):
    sections = b"".join(
        f'<section identifier="/us/usc/t5/s{number}"><num>{number}</num></section>'.encode() for number in range(1100)
    )
    corpus = archive(
        tmp_path / "corpus.zip", [("usc05.xml", native_xml(b"<uscDoc>" + sections + sections + b"</uscDoc>"))]
    )
    output = tmp_path / "candidate"
    receipt = builder.build(corpus=corpus, release_point=RELEASE, annual=[], output=output)
    assert receipt["files"]["usc-oracle-sections.parquet"]["rows"] == 1100
    table = pq.read_table(output / "usc-oracle-sections.parquet")
    assert set(table.column("section").to_pylist()) == {str(number) for number in range(1100)}


@pytest.mark.parametrize("failure", ["bad-member", "malformed-tail", "wrong-year", "repeated-year", "no-titles"])
def test_refused_build_never_leaves_candidate_or_staging_directory(tmp_path, failure):
    xml = native_xml()[:-10] if failure == "malformed-tail" else native_xml()
    corpus = archive(tmp_path / "corpus.zip", [("usc05.xml", xml)])
    annual_entries = [("2012/2012USC40.htm", native_annual())]
    if failure == "bad-member":
        annual_entries.append(("2012/unclassified.htm", b"unexpected"))
    if failure == "no-titles":
        annual_entries = [("2012/usc.css", b"body {}")]
    annual = archive(tmp_path / "2012.zip", annual_entries)
    selected = [(2013 if failure == "wrong-year" else 2012, annual)]
    if failure == "repeated-year":
        selected *= 2
    with pytest.raises(ValueError):
        builder.build(corpus=corpus, release_point=RELEASE, annual=selected, output=tmp_path / "candidate")
    assert not (tmp_path / "candidate").exists()
    assert not list(tmp_path.glob(".usc-structure-*"))


def test_cli_requires_explicit_annual_year_and_reports_refusal(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        builder.main(
            [
                "--corpus",
                "missing",
                "--release-point",
                "119-102",
                "--annual",
                "2012.zip",
                "--output",
                str(tmp_path / "new"),
            ]
        )
    assert error.value.code == 2
    assert "YEAR=PATH" in capsys.readouterr().err
    with pytest.raises(SystemExit) as error:
        builder.main(["--corpus", "missing", "--release-point", "119-102", "--output", str(tmp_path / "new")])
    assert error.value.code == 1
    assert "build failed" in capsys.readouterr().err


def archive_rows(path, *, year=None, old=False):
    rows = []

    def emit(name, row):
        rows.append((name, row))

    if old:
        receipt = archive_oracle._archive(path, year=year, emit=emit)
    else:
        receipt = builder._archive(path, year=year, release_point=RELEASE, emit=emit)
    return receipt, rows


def test_archive_handoff_preserves_ordered_receipts_and_table_rows(tmp_path):
    corpus = archive(tmp_path / "corpus.zip", [("nested/usc05.xml", native_xml())])
    annual = archive(
        tmp_path / "annual.zip",
        [
            ("2012/index.htm", b"listing"),
            ("2012/2012UsC40.HTM", native_annual()),
            ("2012/usc.css", b"body {}"),
            ("2012/2012uscPopularNames.htm", b"names"),
        ],
    )
    for path, year in ((corpus, None), (annual, 2012)):
        assert archive_rows(path, year=year) == archive_rows(path, year=year, old=True)
    receipt, _ = archive_rows(annual, year=2012)
    assert [member["selected"] for member in receipt["members"]] == [False, True, False, False]
    assert [member["name"] for member in receipt["members"]] == [
        "2012/index.htm",
        "2012/2012UsC40.HTM",
        "2012/usc.css",
        "2012/2012uscPopularNames.htm",
    ]


ARCHIVE_DIFFERENCES = (
    "native-release",
    "native-title",
    "native-document-type",
    "native-identifier",
    "missing-native-meta",
    "native-body-content",
    "title-name-width",
    "annual-missing-header",
    "annual-native-title",
    "annual-all-carried",
    "hidden-title-sidecar",
    "aggregate-expansion-bound",
)


def test_only_named_archive_admission_changes_refuse_before_output(tmp_path, monkeypatch):
    xml = native_xml()
    annual = native_annual()
    cases = {
        "native-release": (None, [("usc05.xml", xml.replace(b"Online@119-102", b"Online@119-103"))]),
        "native-title": (None, [("usc05.xml", xml.replace(b"<docNumber>5", b"<docNumber>6"))]),
        "native-document-type": (None, [("usc05.xml", xml.replace(b">USCTitle<", b">USCTitleAppendix<"))]),
        "native-identifier": (
            None,
            [("usc05.xml", xml.replace(b'identifier="/us/usc/t5"', b'identifier="/us/usc/t6"', 1))],
        ),
        "missing-native-meta": (None, [("usc05.xml", XML.read_bytes())]),
        "native-body-content": (
            None,
            [("usc05.xml", native_xml(b'<uscDoc><section identifier="/us/usc/t5/s1"/></uscDoc>'))],
        ),
        "title-name-width": (None, [("usc5.xml", xml)]),
        "annual-missing-header": (2012, [("2012usc40.htm", ANNUAL.read_bytes())]),
        "annual-native-title": (
            2012,
            [("2012usc40.htm", annual.replace(b"AUTHORITIES-USC-TITLE-ENUM:40", b"AUTHORITIES-USC-TITLE-ENUM:41"))],
        ),
        "annual-all-carried": (
            2012,
            [
                (
                    "2012usc40.htm",
                    annual.replace(b"AUTHORITIES-PUBLICATION-YEAR:2012", b"AUTHORITIES-PUBLICATION-YEAR:2011"),
                )
            ],
        ),
        "hidden-title-sidecar": (2012, [("index.htm", annual), ("2012usc40.htm", annual)]),
        "aggregate-expansion-bound": (None, [("usc05.xml", xml)]),
    }
    assert tuple(cases) == ARCHIVE_DIFFERENCES
    valid = archive(tmp_path / "valid.zip", [("usc05.xml", xml)])
    for name, (year, entries) in cases.items():
        source = archive(tmp_path / f"{name}.zip", entries)
        archive_rows(source, year=year, old=True)
        with monkeypatch.context() as patch:
            if name == "aggregate-expansion-bound":
                patch.setattr(builder, "MAX_TOTAL_BYTES", len(xml) - 1)
            with pytest.raises(ValueError):
                builder.build(
                    corpus=source if year is None else valid,
                    release_point=RELEASE,
                    annual=[] if year is None else [(year, source)],
                    output=tmp_path / name,
                )
        assert not (tmp_path / name).exists()
        assert not list(tmp_path.glob(".usc-structure-*"))


def test_late_owner_refusal_discards_earlier_callback_rows(tmp_path):
    sections = b"".join(
        f'<section identifier="/us/usc/t5/s{number}"><num>{number}</num></section>'.encode() for number in range(1100)
    )
    # The first member flushes an insert batch before the second is refused.
    corpus = archive(
        tmp_path / "corpus.zip",
        [
            ("usc05.xml", native_xml(b"<uscDoc>" + sections + b"</uscDoc>")),
            (
                "usc06.xml",
                native_xml()
                .replace(b"<docNumber>5", b"<docNumber>6")
                .replace(b"/us/usc/t5", b"/us/usc/t6")
                .replace(b"Online@119-102", b"Online@119-103"),
            ),
        ],
    )
    with pytest.raises(ValueError, match="native release point"):
        builder.build(corpus=corpus, release_point=RELEASE, annual=[], output=tmp_path / "candidate")
    assert not (tmp_path / "candidate").exists()
    assert not list(tmp_path.glob(".usc-structure-*"))


def test_callback_exception_keeps_identity_and_discards_candidate(tmp_path, monkeypatch):
    error = RuntimeError("receiving table insertion failed")
    corpus = archive(tmp_path / "corpus.zip", [("usc05.xml", native_xml())])

    def fail(_tables, _name, _row):
        raise error

    monkeypatch.setattr(builder._Tables, "emit", fail)
    with pytest.raises(RuntimeError) as caught:
        builder.build(corpus=corpus, release_point=RELEASE, annual=[], output=tmp_path / "candidate")
    assert caught.value is error
    assert not (tmp_path / "candidate").exists()
    assert not list(tmp_path.glob(".usc-structure-*"))


def test_cli_requires_release_point_and_rejects_malformed_selection(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        builder.main(["--corpus", "missing", "--output", str(tmp_path / "new")])
    assert error.value.code == 2
    assert "--release-point" in capsys.readouterr().err
    with pytest.raises(SystemExit) as error:
        builder.main(["--corpus", "missing", "--release-point", "wrong", "--output", str(tmp_path / "new")])
    assert error.value.code == 2
    assert "release-point" in capsys.readouterr().err


def test_carried_forward_appendix_keeps_requested_year_policy_and_member_order(tmp_path):
    carried = (FIXTURES / "usc-structure/annual-2016-title50a.htm").read_bytes()
    header = (FIXTURES / "usc-structure/annual-2016-title40-header.html.part").read_bytes()
    current = header + b"<body>" + ANNUAL.read_bytes() + b"</body></html>"
    annual = archive(
        tmp_path / "2016.zip",
        [
            ("2016/2016usc50a.htm", carried),
            ("2016/usc.css", b"css"),
            ("2016/2016usc40.htm", current),
        ],
    )
    assert b"AUTHORITIES-PUBLICATION-YEAR:2015" in carried
    result, rows = archive_rows(annual, year=2016)
    assert (result, rows) == archive_rows(annual, year=2016, old=True)
    assert [item["selected"] for item in result["members"]] == [True, False, True]
    assert ("annual_sections", (2016, 40, False, "323")) in rows
    assert not any(row[1][0] == 2012 for row in rows)


def test_wrong_filename_year_still_refuses_when_native_year_matches(tmp_path):
    annual = archive(tmp_path / "2012.zip", [("2013usc40.htm", native_annual())])
    for previous in (True, False):
        with pytest.raises(ValueError, match="year differs from member name"):
            archive_rows(annual, year=2012, old=previous)
