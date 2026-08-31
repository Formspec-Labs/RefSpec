"""The act index built from OLRC's Table III bulk release.

Two kinds of test, the same split :mod:`tests.test_act_resolution` uses.
**Fixture cases** state a rule on the smallest excerpt that can express it —
including the excerpts that must be REFUSED, since a reader that only proves
what it accepts has proved half a reader. **Artifact cases** run over the real
126 MB member and the real sealed tables, because a split rule that holds on
two hand-written acts and fails on 48,973 real ones is not a rule.

Every pinned count here was measured on 2026-08-22 against
``olrc-table3-xml-bulk-119-73.zip`` at the digest the module pins. A count that
moves is a finding: it means the source, the reader, or the artifact changed
shape.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from refspec.registry.usc_act_index import (
    _FIRST_PAGE,
    _TABLE3_KEY_SHAPE,
    ACT_SECTION_COLUMNS,
    ARTIFACT_SCHEMA_VERSION,
    BULK_MEMBER,
    BULK_MEMBER_BYTES,
    BULK_SOURCE,
    BULK_SOURCE_BYTES,
    BULK_SOURCE_DIGEST,
    BULK_WELL_FORMEDNESS_DEFECT,
    POPULAR_NAME_COLUMNS,
    QUARANTINE_COLUMNS,
    BulkFormatError,
    BulkRecord,
    build,
    iter_act_fragments,
    parse_act,
    table3_key_from_search_key,
    verify_artifact,
    verify_source,
)

ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = ROOT / BULK_SOURCE
OLD_DIR = ROOT / "output" / "usc-act-index-2026-08-02"
NEW_DIR = ROOT / "output" / "usc-act-index-2026-08-22"

source = pytest.mark.skipif(not ZIP_PATH.is_file(), reason="the OLRC Table III bulk release is not present")
artifact = pytest.mark.skipif(
    not (OLD_DIR.is_dir() and NEW_DIR.is_dir()), reason="the pinned act-index artifacts are not present"
)

#: Two acts in the file's own shape: no declaration, no root, the second
#: opening on the same line the first closes.
EXCERPT = (
    b"\n<act id='a' congress='1' statutes-at-large-volume='1' date='1789-06-01' sequence='2'"
    b" insertion='AAAA' format='1' search-key='1789-06-01:1' print-in-supplement='false'"
    b" include-in-online-release-point='true'>\n"
    b" <num>1</num>\n"
    b" <record id='r0' sequence='0' usckey='0'>\n"
    b"  <act-section>2</act-section>\n"
    b"  <statutes-at-large-page>23</statutes-at-large-page>\n"
    b"  <united-states-code-status>R.S. Sec 28</united-states-code-status>\n"
    b" </record>\n"
    b"</act><act id='b' congress='103' statutes-at-large-volume='108' date='1994-10-25' sequence='3'"
    b" insertion='AAAA' format='3' search-key='103-414' print-in-supplement='false'"
    b" include-in-online-release-point='true'>\n"
    b" <num>103-414</num>\n"
    b" <record id='r1' sequence='0' usckey='47'>\n"
    b"  <act-section>101</act-section>\n"
    b"  <statutes-at-large-page>4279, 4280</statutes-at-large-page>\n"
    b"  <united-states-code-title>47</united-states-code-title>\n"
    b"  <united-states-code-section>1001 nt</united-states-code-section>\n"
    b"  </record>\n"
    b" <record id='r2' sequence='1' usckey='0'>\n"
    b"  <statutes-at-large-page>4281</statutes-at-large-page>\n"
    b"  <united-states-code-title>47</united-states-code-title>\n"
    b" </record>\n"
    b"</act>\n"
)


# --------------------------------------------------------------------------- #
# Fixture cases — the reader, on excerpts, including what it must refuse.


def test_the_reader_splits_a_rootless_excerpt_into_its_acts() -> None:
    fragments = list(iter_act_fragments(__import__("io").BytesIO(EXCERPT)))
    assert len(fragments) == 2
    assert all(fragment.startswith(b"<act ") and fragment.endswith(b"</act>") for fragment in fragments)

    first, second = (parse_act(fragment) for fragment in fragments)
    assert first.table3_key == "1789:1"
    assert first.search_key == "1789-06-01:1"
    assert first.congress == "1"
    assert first.statutes_at_large_volume == "1"
    assert first.records == (BulkRecord("2", "23", None, None, "R.S. Sec 28"),)

    assert second.table3_key == "103-414"
    assert second.num == "103-414"
    # Read as the file states it: the span is NOT narrowed by the reader, only
    # by the build, so the reader stays a statement about the bytes.
    assert second.records == (
        BulkRecord("101", "4279, 4280", "47", "1001 nt", None),
        BulkRecord(None, "4281", "47", None, None),
    )


def test_the_reader_refuses_a_shape_it_has_not_proved() -> None:
    """A split that skips bytes is a reader inventing a document."""

    import io

    with pytest.raises(BulkFormatError, match="bytes between two <act> elements"):
        list(iter_act_fragments(io.BytesIO(EXCERPT.replace(b"</act><act ", b"</act>JUNK<act "))))
    with pytest.raises(BulkFormatError, match="bytes after the last </act>"):
        list(iter_act_fragments(io.BytesIO(EXCERPT + b"<trailing/>")))
    with pytest.raises(BulkFormatError, match="a </act> with no <act> opening it"):
        list(iter_act_fragments(io.BytesIO(b"</act>")))
    with pytest.raises(BulkFormatError, match="not an <act>"):
        parse_act(b"<record id='r'/>")


def test_the_junk_refusals_name_a_specimen() -> None:
    """A refusal that only counts bytes has proved half a refusal.

    ``BulkFormatError`` used to say "N bytes between two <act> elements" and
    stop — a count with nowhere to go look. It now appends the junk itself,
    bounded to 60 bytes, so the message is a specimen and not just a number.
    """

    import io

    junk = b"THIS PROSE SITS BETWEEN TWO <act> ELEMENTS AND IS SEVENTY BYTES LONG"
    assert len(junk) > 60, "the fixture must exceed the specimen bound to prove truncation"

    with pytest.raises(BulkFormatError, match=r"bytes between two <act> elements") as between:
        list(iter_act_fragments(io.BytesIO(EXCERPT.replace(b"</act><act ", b"</act>" + junk + b"<act "))))
    assert repr(junk[:60]) in str(between.value)

    with pytest.raises(BulkFormatError, match=r"bytes after the last </act>") as after:
        list(iter_act_fragments(io.BytesIO(EXCERPT + junk)))
    assert repr(junk[:60]) in str(after.value)


def test_parse_act_refuses_a_missing_attribute_by_name() -> None:
    """A bare ``KeyError`` says nothing about WHICH act or WHICH attribute.

    Each of the four attributes ``parse_act`` reads directly is checked: the
    refusal names the attribute AND the head of the fragment it was missing
    from, the way every other refusal in this reader does.
    """

    first_act = EXCERPT.split(b"</act>", 1)[0] + b"</act>"
    for stated, attribute in (
        (b" search-key='1789-06-01:1'", "search-key"),
        (b" congress='1'", "congress"),
        (b" date='1789-06-01'", "date"),
        (b" statutes-at-large-volume='1'", "statutes-at-large-volume"),
    ):
        assert stated in first_act, attribute
        broken = first_act.replace(stated, b"")
        with pytest.raises(BulkFormatError, match=rf"no {attribute!r} attribute") as excinfo:
            parse_act(broken)
        assert repr(broken.decode("utf-8")[:60]) in str(excinfo.value)


def test_the_reader_is_indifferent_to_where_a_block_boundary_falls() -> None:
    """The split is over a stream, so a fragment straddling two reads is one act."""

    import io

    for block_size in (1, 7, 64, 4096):
        acts = [parse_act(f) for f in iter_act_fragments(io.BytesIO(EXCERPT), block_size=block_size)]
        assert [act.table3_key for act in acts] == ["1789:1", "103-414"], block_size


def test_a_table3_key_is_the_stated_search_key_with_the_date_narrowed() -> None:
    """The key is READ, not re-derived, and the difference is a real act.

    ``<num>`` alone reads the 1956 session-law chapter 78-80 as Public Law
    78-80. OLRC's own ``search-key`` says which it is, so that is what is read.
    """

    assert table3_key_from_search_key("103-414") == "103-414"
    assert table3_key_from_search_key("1948-06-30:758") == "1948:758"
    assert table3_key_from_search_key("1955-07-14:360") == "1955:360"
    assert table3_key_from_search_key("1956-03-02:78-80") == "1956:78-80"
    with pytest.raises(BulkFormatError, match="not date-prefixed"):
        table3_key_from_search_key("chapter:758")


# --------------------------------------------------------------------------- #
# Artifact cases — the real 126 MB member and the real sealed tables.


@source
@pytest.mark.slow
def test_the_bulk_source_is_the_pinned_bytes() -> None:
    assert ZIP_PATH.stat().st_size == BULK_SOURCE_BYTES
    assert f"sha256:{hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()}" == BULK_SOURCE_DIGEST
    with zipfile.ZipFile(ZIP_PATH) as archive:
        members = {info.filename: info.file_size for info in archive.infolist()}
    assert members == {BULK_MEMBER: BULK_MEMBER_BYTES}
    assert verify_source(ZIP_PATH) == []


@source
@pytest.mark.slow
def test_the_member_is_not_a_well_formed_xml_document() -> None:
    """The defect, named exactly, because the reader's whole shape rests on it.

    48,973 sibling ``<act>`` elements and no root: the second one is junk after
    the document element. ``iterparse`` fails identically — the defect is the
    document, not the API — so a synthetic root or a streaming split is the
    only way in, and this is what says so.
    """

    with zipfile.ZipFile(ZIP_PATH) as archive:
        with archive.open(BULK_MEMBER) as handle, pytest.raises(ET.ParseError) as parsed:
            ET.parse(handle)
        with archive.open(BULK_MEMBER) as handle, pytest.raises(ET.ParseError) as streamed:
            for _ in ET.iterparse(handle, events=("end",)):
                pass

    assert str(parsed.value) == BULK_WELL_FORMEDNESS_DEFECT
    assert str(streamed.value) == BULK_WELL_FORMEDNESS_DEFECT
    assert parsed.value.position == streamed.value.position == (29, 6)

    # Line 29, column 6 is exactly where the second <act> opens, on the line
    # the first one closes. Read it back so the coordinate is a fact, not a
    # transcription.
    with zipfile.ZipFile(ZIP_PATH) as archive, archive.open(BULK_MEMBER) as handle:
        lines = [handle.readline() for _ in range(29)]
    assert lines[28].startswith(b"</act><act ")
    assert lines[28][6:11] == b"<act "


@source
@pytest.mark.slow
def test_the_reader_reads_the_files_own_first_act() -> None:
    """The excerpt above is hand-written; this is the real bytes it copies."""

    with zipfile.ZipFile(ZIP_PATH) as archive, archive.open(BULK_MEMBER) as handle:
        first = parse_act(next(iter(iter_act_fragments(handle))))
    assert first.table3_key == "1789:1"
    assert (first.congress, first.date, first.num, first.statutes_at_large_volume) == ("1", "1789-06-01", "1", "1")
    assert len(first.records) == 5
    assert first.records[0] == BulkRecord("2", "23", None, None, "R.S. Sec 28")
    assert first.records[-1] == BulkRecord("3", "23", None, None, "R.S. Sec 1837")


@source
@pytest.mark.slow
def test_deriving_the_key_from_num_disagrees_with_search_key_on_one_act() -> None:
    """The one real collision the module's docstring names, not just describes.

    Restricted to acts whose ``<num>`` alone already has the shape of a
    complete modern key (:data:`_TABLE3_KEY_SHAPE`) — anything else is
    obviously incomplete (a pre-1957 act's ``<num>`` carries no year), not a
    plausible wrong answer. Of the 35,243 such acts, exactly one disagrees
    with the key ``search-key`` states: the 1956 session-law chapter 78-80,
    whose ``<num>`` alone reads as Public Law 78-80.
    """

    shape_matches = 0
    disagreements = []
    with zipfile.ZipFile(ZIP_PATH) as archive, archive.open(BULK_MEMBER) as handle:
        for fragment in iter_act_fragments(handle):
            act = parse_act(fragment)
            if _TABLE3_KEY_SHAPE.fullmatch(act.num):
                shape_matches += 1
                if act.num != act.table3_key:
                    disagreements.append(act)

    assert shape_matches == 35_243
    assert len(disagreements) == 1
    (only,) = disagreements
    assert (only.num, only.table3_key, only.search_key, only.congress, only.date) == (
        "78-80",
        "1956:78-80",
        "1956-03-02:78-80",
        "84",
        "1956-03-02",
    )


@artifact
@pytest.mark.slow
def test_the_sealed_tables_have_the_08_02_artifacts_schema() -> None:
    """Same columns, same types, same order — so the consumer needs no change."""

    for table, columns in (
        ("usc-popular-names.parquet", POPULAR_NAME_COLUMNS),
        ("usc-act-sections.parquet", ACT_SECTION_COLUMNS),
        ("quarantine.parquet", QUARANTINE_COLUMNS),
    ):
        old, new = pq.read_schema(OLD_DIR / table), pq.read_schema(NEW_DIR / table)
        assert tuple(new.names) == columns, table
        assert new.names == old.names, table
        assert [str(new.field(name).type) for name in new.names] == ["string"] * len(columns), table
        assert new.types == old.types, table


@artifact
@pytest.mark.slow
def test_the_popular_name_table_is_carried_over_byte_identically() -> None:
    """Only Table III is rebuilt; the names come from a document this file lacks."""

    assert (NEW_DIR / "usc-popular-names.parquet").read_bytes() == (
        OLD_DIR / "usc-popular-names.parquet"
    ).read_bytes()
    receipt = json.loads((NEW_DIR / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["inputs"]["popular_names_carried_from"] == "output/usc-act-index-2026-08-02"
    assert receipt["inputs"]["popular_names_release_point"] == ["119-102"]
    # And the bulk file is an EARLIER release point than those names, which is
    # the whole explanation for the divergences the next test freezes.
    assert receipt["inputs"]["bulk_release_point"] == "119-73"


@artifact
@pytest.mark.slow
def test_the_24_fetched_acts_come_back_out_of_the_bulk_file() -> None:
    """Reproduction, measured — and every difference named rather than allowed.

    The per-page build reached 24 laws. All 24 are in the bulk file, and
    10,963 of its 10,976 rows come back byte-for-byte identical. The 13 + 16
    that do not are frozen below, so an unlisted one fails this test instead of
    becoming a diff nobody reads. Every one of them is the same fact: the bulk
    release is release point 119-73 and the per-page fetch was 119-102, and
    OLRC re-classified these provisions in between.
    """

    import collections

    old = pq.read_table(OLD_DIR / "usc-act-sections.parquet").to_pylist()
    keys = {row["table3_key"] for row in old}
    new = [row for row in pq.read_table(NEW_DIR / "usc-act-sections.parquet").to_pylist() if row["table3_key"] in keys]
    assert len(keys) == 24
    assert {row["table3_key"] for row in new} == keys
    assert (len(old), len(new)) == (10_976, 10_979)

    def multiset(rows):
        return collections.Counter(tuple(row[column] for column in ACT_SECTION_COLUMNS) for row in rows)

    theirs, ours = multiset(old), multiset(new)
    assert sum((theirs & ours).values()) == 10_963

    assert sorted((theirs - ours).elements()) == [
        ("116-260", "104", "2", "6154 nt", None, "134", "1631"),
        ("116-260", "305(a)", "50", "3227b", None, "134", "2366"),
        ("116-260", "305(b)", "50", "3227b nt", None, "134", "2367"),
        ("116-260", "622", "50", "3024 nt", None, "134", "2404"),
        ("117-328", "103(a)", "2", "6154 nt", None, "136", "4917"),
        ("117-328", "103(b)", "2", "6154 nt", None, "136", "4918"),
        ("117-328", "547", "6", "124n nt", None, "136", "4758"),
        ("1944:373", "581", "42", "290kk", None, "58", None),
        ("1944:373", "582", "42", "290kk-1", None, "58", None),
        ("1944:373", "583", "42", "290kk-2", None, "58", None),
        ("1944:373", "584", "42", "290kk-3", None, "58", None),
        ("1955:360", "134", "42", "7434", None, "69", None),
        ("93-406", "2002(a)(1)", "26", "224", None, "88", "958"),
    ]
    assert sorted((ours - theirs).elements()) == [
        ("116-260", "104", "2", "6161", None, "134", "1631"),
        ("116-260", "305(a)", "50", "3227b", "Rep.", "134", "2366"),
        ("116-260", "305(b)", "50", "3227b nt", "Elim.", "134", "2367"),
        ("116-260", "306A", "22", "1741d-1", None, "134", None),
        ("116-260", "315", "22", "3301 nt", None, "134", "3100"),
        ("116-260", "622", "50", "3024 nt", "Rep.", "134", "2404"),
        ("117-328", "103(a)", "2", "6161", None, "136", "4917"),
        ("117-328", "103(b)", "2", "6161 nt", None, "136", "4918"),
        ("117-328", "547", "6", "124n nt", "Elim.", "136", "4758"),
        ("1935:531", "1899C", "42", "1395mmm", None, "49", None),
        ("1944:373", "596", "42", "290kk", None, "58", None),
        ("1944:373", "596A", "42", "290kk-1", None, "58", None),
        ("1944:373", "596B", "42", "290kk-2", None, "58", None),
        ("1944:373", "596C", "42", "290kk-3", None, "58", None),
        ("1955:360", "134", "42", "7434", "Rep.", "69", None),
        ("93-406", "2002(a)(1)", "26", "226", None, "88", "958"),
    ]
    # And the receipt says the same thing, so a rebuild that quietly diverged
    # would contradict its own paperwork before it reached this list.
    reproduction = json.loads((NEW_DIR / "receipt.json").read_text(encoding="utf-8"))["reproduction"]
    assert reproduction["rows_reproduced_identically"] == 10_963
    assert (reproduction["rows_only_in_reference"], reproduction["rows_only_here"]) == (13, 16)
    assert reproduction["table3_keys_present_here"] == 24


@artifact
@pytest.mark.slow
def test_the_receipt_accounts_for_every_record_the_file_states() -> None:
    """Nothing vanishes: every record is a sealed row or a counted refusal."""

    receipt = json.loads((NEW_DIR / "receipt.json").read_text(encoding="utf-8"))
    measured, coverage = receipt["measured"], receipt["coverage"]
    assert (measured["bulk_act_elements"], measured["bulk_record_elements"]) == (48_973, 317_590)
    assert coverage["act_section_rows"] + measured["records_without_act_section"] == measured["bulk_record_elements"]
    assert coverage["act_section_rows"] == 302_156
    assert measured["records_without_act_section"] == 15_434
    assert coverage["quarantine_reasons"] == {
        "record_without_act_section": 15_434,
        "statutes_at_large_page_span_narrowed": 20_371,
    }
    assert measured["pages_unreadable"] == 0
    # Read but uncarryable, named with its count rather than dropped in silence.
    assert measured["stated_but_not_carried"]["act/@congress"] == 48_973
    assert measured["stated_but_not_carried"]["record/@usckey"] == 317_590


@artifact
@pytest.mark.slow
def test_a_narrowed_page_keeps_its_whole_text_in_quarantine() -> None:
    """The column takes one integer, so the span is narrowed AND preserved."""

    quarantined = [
        row
        for row in pq.read_table(NEW_DIR / "quarantine.parquet").to_pylist()
        if row["reason"] == "statutes_at_large_page_span_narrowed"
    ]
    assert len(quarantined) == 20_371
    assert {row["source"] for row in quarantined} == {"table3_bulk_xml"}
    spans = {(row["table3_key"], row["raw_value"]) for row in quarantined}
    assert ("115-254", "1207(c), (d) -> 3440, 3441") in spans
    assert ("109-58", "1310(a)-(e) -> 1007-1009") in spans

    sections = pq.read_table(NEW_DIR / "usc-act-sections.parquet").to_pylist()
    kept = {row["statutes_at_large_page"] for row in sections if row["statutes_at_large_page"]}
    # Every sealed page is one integer — the column the consumer reads with
    # int() can hold nothing else.
    assert all(page.isdigit() for page in kept)


@artifact
@pytest.mark.slow
def test_the_page_span_population_is_counted_whole_and_split() -> None:
    """20,809 records state a page span; 20,371 keep a row, 438 do not.

    The narrower, previously-pinned count is the subset with an
    ``<act-section>``: the span is narrowed to its first page and the row is
    kept. The other 438 have no ``<act-section>`` at all, so they are already
    in ``quarantine.parquet`` under ``record_without_act_section`` before the
    page column is ever read — their span text is sitting in that row's
    ``raw_value``, unexamined until this test reads it back out.
    """

    quarantine = pq.read_table(NEW_DIR / "quarantine.parquet").to_pylist()
    narrowed = [row for row in quarantine if row["reason"] == "statutes_at_large_page_span_narrowed"]
    assert len(narrowed) == 20_371

    orphaned_spans = 0
    for row in quarantine:
        if row["reason"] != "record_without_act_section":
            continue
        page = json.loads(row["raw_value"])["statutes_at_large_page"]
        if page is None:
            continue
        first = _FIRST_PAGE.match(page)
        if first is not None and first.group(1) != page.strip():
            orphaned_spans += 1
    assert orphaned_spans == 438
    assert len(narrowed) + orphaned_spans == 20_809

    # The receipt field is new — the sealed 08-22 receipt predates it — so it
    # is proved by building fresh from the same pinned zip into a scratch
    # directory, never by writing over the sealed artifact.
    with tempfile.TemporaryDirectory() as scratch:
        receipt = build(
            Path(scratch) / "artifact",
            zip_path=ZIP_PATH,
            popular_names_from=OLD_DIR,
            compare_with=None,
        )
    measured = receipt["measured"]
    assert measured["page_spans_stated"] == 20_809
    assert measured["page_spans_narrowed_to_first_page"] == 20_371
    derivation = receipt["rules"]["page_span_rule_derivation"]
    for number in ("20,809", "20,371", "438"):
        assert number in derivation


@artifact
@pytest.mark.slow
def test_the_bulk_release_covers_what_the_popular_name_tool_names() -> None:
    """The coverage claim, measured against the tool's own keys.

    Against the ORDER-FREE set of every table3_key any "cite" row states —
    not a per-name resolution, which is ActIndex's job and not this
    receipt's; see ``test_the_popular_name_cite_coverage_is_order_free``.
    """

    measured = json.loads((NEW_DIR / "receipt.json").read_text(encoding="utf-8"))["measured"]
    assert measured["popular_name_cite_table3_keys"] == 8_399
    assert measured["popular_name_cite_table3_keys_covered"] == 7_553
    assert measured["bulk_distinct_table3_keys"] == 23_147
    # 210 Public Resolution keys the Table III URL grammar cannot spell. They
    # are carried, not refused — and no popular name reaches them, which is
    # why carrying them costs nothing.
    assert measured["table3_keys_outside_the_url_grammar"] == 210
    assert measured["acts_outside_the_url_grammar"] == 213
    # A year:chapter key is not unique across sessions. The popular-name table
    # spells keys the same way, so this is the source's ambiguity, not ours.
    assert measured["table3_keys_spanning_two_statutes_at_large_volumes"] == 49
    # A SEPARATE 49 over a SEPARATE condition, not the same 49 keys restated —
    # the two sets differ by six each way; see
    # test_the_two_and_two_populations_are_not_the_same_49_keys.
    assert measured["table3_keys_spanning_two_congresses"] == 49


@source
@pytest.mark.slow
def test_the_two_and_two_populations_are_not_the_same_49_keys() -> None:
    """49 keys span two volumes; 49 span two Congresses; six differ each way.

    Read from the receipt alone, both counts land on 49 and a reader could
    mistake that for one population under two names — the earlier evidence
    note did. Measured directly over the real member, the two sets differ by
    six in each direction. The four public-law-shaped keys that span two
    volumes but one Congress are not a year:chapter collision: OLRC states
    two ``<act>`` elements for that one law, and the elements disagree with
    each other about which Statutes at Large volume it is in.
    """

    volumes_by_key: dict[str, set[str]] = {}
    congresses_by_key: dict[str, set[str]] = {}
    with zipfile.ZipFile(ZIP_PATH) as archive, archive.open(BULK_MEMBER) as handle:
        for fragment in iter_act_fragments(handle):
            act = parse_act(fragment)
            volumes_by_key.setdefault(act.table3_key, set()).add(act.statutes_at_large_volume)
            congresses_by_key.setdefault(act.table3_key, set()).add(act.congress)

    spans_volumes = {key for key, volumes in volumes_by_key.items() if len(volumes) > 1}
    spans_congresses = {key for key, congresses in congresses_by_key.items() if len(congresses) > 1}
    assert len(spans_volumes) == len(spans_congresses) == 49
    assert spans_volumes - spans_congresses == {"1939:2", "1954:736", "87-845", "93-107", "98-47", "98-53"}
    assert spans_congresses - spans_volumes == {"1797:7", "1837:1", "1861:20", "1861:49", "1861:59", "1861:60"}
    assert len(spans_volumes & spans_congresses) == 43

    # The four modern, public-law-shaped keys really do carry two <act>
    # elements that disagree about the volume — not a year:chapter collision,
    # which those keys' shape rules out entirely — and one Congress each.
    disagreeing_volumes = {
        "87-845": {"76", "76A"},
        "93-107": {"87", "88"},
        "98-47": {"97", "98"},
        "98-53": {"97", "98"},
    }
    for key, volumes in disagreeing_volumes.items():
        assert volumes_by_key[key] == volumes
        assert len(congresses_by_key[key]) == 1


@artifact
@pytest.mark.slow
def test_the_popular_name_cite_coverage_is_order_free() -> None:
    """846 of 8,399 keys are absent — a count nothing can make move.

    Until 2026-08-23 this was 845 of 8,391, computed by a private
    ``keyed_names.setdefault(name_key, table3_key)`` that picked one
    table3_key per name_key in parquet FILE ORDER. 34 name_keys name two
    different table3_keys each ('detainee treatment act of 2005' names both
    109-148 and 109-163), so that pick — and the resulting set's size — moved
    with row order: 8,391 by file order, 8,392 by a sorted tie-break. The
    replacement never picks a winner per name, so row order has nothing left
    to change; the two removed fields are asserted gone rather than merely
    unused, so a reintroduction under the old name fails this test.

    The field is new — the sealed 08-22 receipt predates it — so it is proved
    by building fresh from the same pinned zip into a scratch directory,
    never by writing over the sealed artifact.
    """

    with tempfile.TemporaryDirectory() as scratch:
        receipt = build(
            Path(scratch) / "artifact",
            zip_path=ZIP_PATH,
            popular_names_from=OLD_DIR,
            compare_with=None,
        )
    measured = receipt["measured"]
    assert measured["popular_name_cite_table3_keys"] == 8_399
    assert measured["popular_name_cite_table3_keys_covered"] == 7_553
    assert measured["popular_name_cite_table3_keys_absent"] == 846
    assert (
        measured["popular_name_cite_table3_keys_covered"] + measured["popular_name_cite_table3_keys_absent"]
        == measured["popular_name_cite_table3_keys"]
    )
    assert "popular_name_index_table3_keys" not in measured
    assert "popular_name_index_table3_keys_covered" not in measured
    assert "popular_name_index_table3_keys_absent" not in measured


@artifact
@pytest.mark.slow
def test_verify_passes_the_sealed_artifact_and_names_every_drift() -> None:
    assert verify_artifact(NEW_DIR, zip_path=ZIP_PATH) == []
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "artifact"
        shutil.copytree(NEW_DIR, copy)
        assert verify_artifact(copy) == []

        target = copy / "usc-act-sections.parquet"
        target.write_bytes(target.read_bytes() + b" ")
        problems = verify_artifact(copy)
        assert any("usc-act-sections.parquet drifted" in problem for problem in problems)

        (copy / "receipt.json").unlink()
        assert verify_artifact(copy) == [f"no receipt at {copy / 'receipt.json'}"]

    receipt = json.loads((NEW_DIR / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert receipt["parser_version"] == "uscode-olrc-table3-bulk-xml-v1"
