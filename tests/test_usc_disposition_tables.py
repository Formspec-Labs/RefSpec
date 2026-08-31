"""The 1994 Title 49 disposition table, and what it says about the pinned corpus.

Four kinds of test, the same four the section-oracle suite uses.

**Pin tests** hold every file of the artifact to the digest its README states —
the volume, the extractor, the derived Parquet and the readable rendering —
because every number below is a statement about those exact bytes, and a
swapped directory must fail loudly rather than answer differently.

**Specimen tests** run the reader on the ten rows the human review of
2026-08-23 read by hand (``research/evidence/sample-review-2026-08-23/review.md``
§ F), *verbatim*: the printed former field and the printed value, not a
paraphrase. Beside them are the rows the reader must NOT collapse — the four
successors of ``1432``, the note row that answers ``1374`` and not ``1374(c)``,
the ``(See § 2 of Pub. L. 97-449.)`` that is not a repeal, and a section the
table never lists.

**Corpus tests** run the whole thing over
``agenda-legal-authorities-as-measured-797170.parquet`` — the 797,170-row build
the section-oracle report measured, read by digest — and count how many of the
2,548 ``title_49_appendix_not_published`` rows the table answers, by verdict.
Ten of the answered rows are printed with the filer's own text and pinned, for
a human to check by eye; so is every section where the table gives more than
one successor, because that is the population a consumer must present as
candidates rather than as an identity.

**Negative tests** construct the verdict dataclasses wrong on purpose. A
verdict that names successors and says ``not-in-table``, a successor carrying
``repealed``, an absence without its caveat: each must raise, because the
invariant is what stops a future edit from publishing a guess.
"""

from __future__ import annotations

import collections
import hashlib
import random
from functools import cache
from pathlib import Path

import pytest

from refspec.registry import citation_grammar, usc_section_oracle
from refspec.registry.usc_disposition_tables import (
    _DASHES,
    NOT_IN_TABLE_CAVEATS,
    RECODIFICATIONS,
    RECODIFICATIONS_NOT_PINNED,
    STATUSES,
    USC_DISPOSITION_TABLES_ARTIFACT,
    VERDICTS,
    Disposition,
    DispositionRow,
    Successor,
    UscDispositionTables,
    normalize_section,
    normalize_subsection,
)
from refspec.registry.usc_section_oracle import (
    USC_SECTION_ORACLE_ARTIFACT,
    UscSectionOracle,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / USC_DISPOSITION_TABLES_ARTIFACT

#: The artifact README's Files table, restated. The volume and the extractor
#: are pinned here although the reader never opens them: they are the chain
#: from a verdict back to a printed page, and a swap anywhere along it makes
#: the derived table unprovable.
ARTIFACT_PINS = {
    "USCODE-1994-title49.pdf": ("sha256:66f004679e27e0d16356e14b79cb3b4f7ebf63d91307435fa8f53c95bcc2848d", 5_165_242),
    "usc-1994-title49-disposition.parquet": (
        "sha256:8403212c0193b3361accf7ff4be238420634beb5aa5740d78b9960fef5b2aedd",
        37_672,
    ),
    "usc-1994-title49-disposition.txt": (
        "sha256:30c7aeaa3693cc343b4b843e201e3ec17a92cd86db837362aeafce95800b87cf",
        61_218,
    ),
    "scripts/extract_disposition_table.py": (
        "sha256:4082ba71c5206b8b95b471d32df816f23141bf145b737098ca62b0ccc5cdb99a",
        27_725,
    ),
}

#: The build every corpus count below was measured over, read by digest from
#: the section oracle's artifact, where it already lives.
SNAPSHOT = ROOT / USC_SECTION_ORACLE_ARTIFACT / "agenda-legal-authorities-as-measured-797170.parquet"
SNAPSHOT_DIGEST = "sha256:c5c4bd1f8b70fd52491f8b22e7bc72c75287cbbf3638692210fd1691731c7424"


@cache
def tables() -> UscDispositionTables:
    return UscDispositionTables.from_repository(ROOT)


@cache
def rows() -> tuple[dict, ...]:
    """Every row of the derived table, as the extractor wrote it."""

    import pyarrow.parquet as pq

    table = pq.read_table(ARTIFACT / "usc-1994-title49-disposition.parquet")
    columns = {name: table.column(name).to_pylist() for name in table.schema.names}
    return tuple(dict(zip(columns, values, strict=True)) for values in zip(*columns.values(), strict=True))


# --------------------------------------------------------------------------- #
# The pins


def test_every_artifact_file_is_the_one_the_readme_states() -> None:
    """Four files, four digests and four byte lengths, from the Files table."""

    for name, (pin, size) in ARTIFACT_PINS.items():
        raw = (ARTIFACT / name).read_bytes()
        assert f"sha256:{hashlib.sha256(raw).hexdigest()}" == pin, name
        assert len(raw) == size, name


def test_the_module_pins_the_table_the_readme_pins() -> None:
    """One recodification, and its digest is the artifact's, restated in code."""

    assert [recodification.former_title for recodification in RECODIFICATIONS] == [49]
    only = RECODIFICATIONS[0]
    assert only.digest == ARTIFACT_PINS[only.table][0]
    assert only.source_digest == ARTIFACT_PINS["USCODE-1994-title49.pdf"][0]
    assert only.source_bytes == ARTIFACT_PINS["USCODE-1994-title49.pdf"][1]
    assert only.deeming_provision == "Pub. L. 103-272, § 6(b)"


def test_a_drifted_table_refuses_loudly_and_names_itself(tmp_path: Path) -> None:
    """A wrong directory must fail, not answer differently."""

    name = RECODIFICATIONS[0].table
    (tmp_path / name).write_bytes((ARTIFACT / name).read_bytes() + b"\0")
    with pytest.raises(ValueError, match=f"pinned disposition table drifted: {name}"):
        UscDispositionTables.from_directory(tmp_path)


def test_the_dash_table_is_the_grammars_verbatim() -> None:
    """Restated, not imported — see the module docstring on the coming cycle."""

    assert _DASHES == citation_grammar._DASHES
    for dash in "‐‑‒–—―−\x96\x97":
        assert normalize_section(f"1601{dash}1") == "1601-1"


def test_a_subsection_query_is_read_the_way_a_citation_writes_one() -> None:
    assert normalize_subsection("d") == ("d",)
    assert normalize_subsection("(d)") == ("d",)
    assert normalize_subsection("(D)") == ("d",)
    assert normalize_subsection("(a)(1)") == ("a", "1")
    assert normalize_subsection(None) == ()
    assert normalize_subsection("") == ()


def test_the_span_order_is_the_oracles_over_every_former_section() -> None:
    """Restated, not imported — the same copy the dash table above is.

    Run over all 909 former sections the pinned table lists, because the only
    thing that makes a restatement safe is a check that reads both.
    """

    from refspec.registry.usc_disposition_tables import _section_order

    for section in sorted(tables().former_sections(49)):
        assert _section_order(section) == usc_section_oracle._section_key(section), section
    # The reason it is not a plain int: a numeric prefix alone orders 1421a
    # before 1421, and a span "1421 to 1431" would then take neither.
    assert _section_order("1421") < _section_order("1421a") < _section_order("1422")


# --------------------------------------------------------------------------- #
# What the derived table is

@pytest.mark.slow
def test_the_table_is_the_size_the_readme_states() -> None:
    """Row, entry, section and status counts, all from the README's Counts."""

    data = rows()
    entries = {(row["page"], row["column"], row["former_text"], row["new_text"]) for row in data}
    assert len(data) == 3_102
    assert len(entries) == 1_852
    assert len({row["former_section"] for row in data}) == 909
    assert len({(row["former_section"], row["former_subsection"]) for row in data}) == 2_428
    assert collections.Counter(row["status"] for row in data) == {
        "restated": 2_560,
        "repealed": 468,
        "eliminated": 47,
        "see-reference": 24,
        "restated-as-note": 3,
    }
    assert set(collections.Counter(row["status"] for row in data)) <= set(STATUSES)
    assert {row["page"] for row in data} == set(range(1, 13))
    assert tables().former_sections(49) == {normalize_section(row["former_section"]) for row in data}


@pytest.mark.slow
def test_every_row_keeps_the_tables_own_text() -> None:
    """The parse drops prose; the record does not. Nothing vanishes."""

    for row in rows():
        assert row["former_text"] and row["new_text"]
        assert row["former_text"][0].isdigit()
    # The prose the parse drops is exactly what tells two rows of one section
    # apart, and it is still there to read.
    prose = {row["former_text"] for row in rows() if row["former_section"] == "1432"}
    assert prose == {
        "1432(a) (related to issuing certificates).",
        "1432(a) (related to standards)",
        "1432(b), (c)",
        "1432(d)",
    }


# --------------------------------------------------------------------------- #
# The ten rows the reviewer read by hand

#: ``(review row, filer's text, section, subsection, verdict, successors,
#: printed former field, printed value)`` — the last two verbatim from the
#: page, so that a re-extraction that changes the print fails here.
REVIEW_F = (
    (1, "49 USC 1432", "1432", None, "exists-as-recodified", ("44702", "44701", "44706", "44914"), None, None),
    (1, "49 USC 1432", "1432", "b", "exists-as-recodified", ("44706",), "1432(b), (c)", "44706"),
    (1, "49 USC 1432", "1432", "d", "exists-as-recodified", ("44914",), "1432(d)", "44914"),
    (2, "49 USC 1652(e)", "1652", "e", "exists-as-recodified", ("106", "104", "103", "108"), None, None),
    (3, "49 USC 1421 to 1431", "1430", None, "exists-as-recodified", ("44711",), "1430", "44711"),
    (3, "49 USC 1421 to 1431", "1431", "a", "exists-as-recodified", ("44715",), "1431(a)-(d)", "44715"),
    (4, "49 USC 1423 to 1426", "1425", None, "exists-as-recodified", ("44713",), "1425", "44713"),
    (4, "49 USC 1423 to 1426", "1424", "b", "exists-as-recodified", ("44705",), "1424(b)", "44705"),
    (5, "49 USC 1502", "1502", "a", "exists-as-recodified", ("40105",), "1502(a)", "40105"),
    (5, "49 USC 1502", "1502", "b", "exists-as-recodified", ("40101",), "1502(b)", "40101"),
    (6, "49 USC 1424", "1424", "b", "exists-as-recodified", ("44705",), "1424(b)", "44705"),
    (7, "49 USC 1421", "1421", "f", "exists-as-recodified", ("44716",), "1421(f)", "44716"),
    (8, "49 USC 1374(c)", "1374", "c", "exists-as-recodified", ("41705",), "1374(c)", "41705"),
    (9, "49 USC 1604(h)", "1604", "h", "repealed-no-successor", (), "1604, 1604a", "Rep."),
    (10, "49 USC 1510", "1510", None, "exists-as-recodified", ("40120",), "1510", "40120"),
)


@pytest.mark.parametrize(
    ("review_row", "filed", "section", "sub", "verdict", "successors", "printed", "value"), REVIEW_F
)
@pytest.mark.slow
def test_the_rows_review_f_read_are_the_rows_the_table_prints(
    review_row: int,
    filed: str,
    section: str,
    sub: str | None,
    verdict: str,
    successors: tuple[str, ...],
    printed: str | None,
    value: str | None,
) -> None:
    """Ten citations a human resolved against the publisher's pages, verbatim.

    ``filed`` is the filer's own text in the pinned build; it is here so the
    row this asserts can be found in the artifact, not because the reader parses
    it.
    """

    answer = tables().disposition(49, section, sub)
    assert answer.verdict == verdict, filed
    assert tuple(s.section for s in answer.successors) == successors, filed
    assert all(s.title == 49 for s in answer.successors), filed
    assert answer.recodification == "title-49-1994"
    if printed is not None:
        assert [(row.former_text, row.new_text) for row in answer.rows] == [(printed, value)] * len(answer.rows)


@pytest.mark.slow
def test_the_one_row_of_review_f_that_is_not_a_recodification() -> None:
    """§ F row 9. ``1604, 1604a … Rep.`` — a verdict, not a coverage gap.

    The section is in the table, printed beside its neighbour, and given no
    successor. That is the fact ``unknown`` could not express and the reason
    this module exists beside the oracle rather than inside it.
    """

    answer = tables().disposition(49, "1604", "h")
    assert (answer.verdict, answer.successors, answer.caveats) == ("repealed-no-successor", (), ())
    assert answer.subsection_resolved is True
    assert [(row.former_text, row.new_text, row.status) for row in answer.rows] == [
        ("1604, 1604a", "Rep.", "repealed")
    ]
    # The section named beside it in the same printed entry answers identically,
    # off the same page and column: one printed row, two former sections.
    beside = tables().disposition(49, "1604a")
    assert beside.verdict == answer.verdict
    assert [(r.former_text, r.new_text, r.page, r.column) for r in beside.rows] == [
        (r.former_text, r.new_text, r.page, r.column) for r in answer.rows
    ]
    assert (beside.rows[0].former_section, answer.rows[0].former_section) == ("1604a", "1604")


@pytest.mark.slow
def test_several_successors_are_all_returned_and_none_is_picked() -> None:
    """§ F row 1. ``1432`` is four sections, and the prose is what tells them apart."""

    answer = tables().disposition(49, "1432")
    # Four successors, and the four printed entries they came from: the two
    # readings of (a) differ only in the prose, which is exactly the point.
    distinct = answer.rows[:2] + answer.rows[3:]
    assert [(s.section, row.former_text) for s, row in zip(answer.successors, distinct, strict=True)] == [
        ("44702", "1432(a) (related to issuing certificates)."),
        ("44701", "1432(a) (related to standards)"),
        ("44706", "1432(b), (c)"),
        ("44914", "1432(d)"),
    ]
    assert answer.subsection_resolved is None
    # Narrowing by subsection is the only thing that reduces it, and it reduces
    # it to what the print says and no further: (a) is still two readings.
    assert tuple(s.section for s in tables().disposition(49, "1432", "a").successors) == ("44702", "44701")


@pytest.mark.slow
def test_a_note_row_answers_the_section_and_not_a_subsection() -> None:
    """``1374 note → 41706`` is about the notes under 1374, not about 1374(c)."""

    whole = tables().disposition(49, "1374")
    assert "41706" in {s.section for s in whole.successors}
    assert any(row.former_note == "note" for row in whole.rows)
    assert tuple(s.section for s in tables().disposition(49, "1374", "c").successors) == ("41705",)
    assert tuple(s.section for s in tables().disposition(49, "1421", "f").successors) == ("44716",)
    assert {s.section for s in tables().disposition(49, "1421").successors} >= {"44717", "44722"}


@pytest.mark.slow
def test_a_pointer_at_another_act_is_not_a_repeal() -> None:
    """``1655(a)(4) → (See § 2 of Pub. L. 97-449.)`` — no successor, not gone."""

    answer = tables().disposition(49, "1655", "(a)(4)")
    assert answer.verdict == "stated-without-successor"
    assert [row.new_text for row in answer.rows] == ["(See § 2 of Pub. L. 97-449.)"]
    assert [row.status for row in answer.rows] == ["see-reference"]
    # A sibling subsection of the same section IS a repeal, and says so.
    assert tables().disposition(49, "1655", "(a)(5)").verdict == "repealed-no-successor"


@pytest.mark.slow
def test_the_reps_are_captured() -> None:
    """The table's ``Rep.`` lines, which are a third of its printed entries."""

    for section in ("1604", "1604a", "1613", "1554", "1555", "1556", "1557"):
        answer = tables().disposition(49, section)
        assert answer.verdict == "repealed-no-successor", section
        assert answer.successors == ()
    assert [row.former_text for row in tables().disposition(49, "1554").rows] == ["1554-1557"]
    only_repealed = {
        section
        for section, group in _by_section().items()
        if {row["status"] for row in group} == {"repealed"}
    }
    assert len(only_repealed) == 308
    assert sum(1 for row in rows() if row["status"] == "repealed") == 468


@pytest.mark.slow
def test_a_section_the_table_never_lists_is_not_in_table_and_says_how_wide_that_is() -> None:
    """And carries the caveat, because the table is not a roster of the title."""

    answer = tables().disposition(49, "9999")
    assert answer.verdict == "not-in-table"
    assert answer.caveats == NOT_IN_TABLE_CAVEATS
    assert (answer.successors, answer.rows) == ((), ())
    assert not answer.answered
    # 1509d is a real specimen from the pinned corpus, not an invented number.
    assert tables().disposition(49, "1509d").verdict == "not-in-table"


@pytest.mark.slow
def test_a_title_with_no_pinned_table_is_not_an_absence() -> None:
    """§ E rows 7 and 10, and § H row 8, are waiting on exactly this."""

    for title, section in ((31, "483a"), (41, "85"), (10, "593"), (5, "552")):
        answer = tables().disposition(title, section)
        assert answer.verdict == "no-table-for-title", (title, section)
        assert answer.recodification is None
        assert answer.caveats == ()
        assert not answer.answered
    assert set(RECODIFICATIONS_NOT_PINNED) == {10, 31, 34, 41, 46, 51, 54}
    assert not set(RECODIFICATIONS_NOT_PINNED) & {r.former_title for r in RECODIFICATIONS}


@pytest.mark.slow
def test_a_subsection_the_table_does_not_resolve_falls_back_to_the_section() -> None:
    """``1905(a)-(c)(2)`` spans levels, so only its first label is matchable.

    A query for ``(b)`` therefore matches no row. Answering ``not-in-table``
    would be the worse error — the table plainly knows 1905 — so the section's
    own rows come back with ``subsection_resolved`` False.
    """

    answer = tables().disposition(49, "1905", "b")
    assert answer.subsection_resolved is False
    assert answer.verdict == "exists-as-recodified"
    assert answer.rows == tables().disposition(49, "1905").rows
    assert tables().disposition(49, "1905", "a").subsection_resolved is True


def test_a_stated_pinpoint_narrows_and_the_bare_sibling_does_not() -> None:
    """``49 USC 1651(b)(2)`` (RIN 2120-AF10, 1995-10) against bare ``1651``.

    The filer's two texts, side by side, from the visual review of 2026-08-23
    (§ J rows 13 and 14). The 1994 volume prints ``1651(a), (b)(1) -> 101``
    and ``1651(b)(2) -> 303`` as two rows, so the pinpointed citation has ONE
    answer and the bare one has two — and before 2026-08-24 the build gave
    both rows the same pair, because no pinpoint reached the table.

    The bare sibling is the paired negative and matters as much: a narrowing
    that also fired without a pinpoint would be picking one of two candidates,
    which is the thing this module exists not to do.
    """

    pinpointed = tables().disposition(49, "1651", "(b)(2)")
    assert pinpointed.subsection_resolved is True
    assert [f"{one.title}:{one.section}" for one in pinpointed.successors] == ["49:303"]
    assert [row.former_text for row in pinpointed.rows] == ["1651(b)(2)"]

    bare = tables().disposition(49, "1651")
    assert bare.subsection_resolved is None
    assert [f"{one.title}:{one.section}" for one in bare.successors] == ["49:101", "49:303"]

    # The pinpoint can move the VERDICT, not only the list: "49 USC 1341(c)"
    # (RIN 2120-AE68, 1995-10) points at the one subsection of 1341 the volume
    # prints as repealed, while (a) and (b) went to 106.
    assert tables().disposition(49, "1341").verdict == "exists-as-recodified"
    repealed = tables().disposition(49, "1341", "(c)")
    assert (repealed.verdict, repealed.successors) == ("repealed-no-successor", ())
    assert [row.new_text for row in repealed.rows] == ["Rep."]


def test_a_stated_span_is_asked_member_by_member_and_the_union_says_so() -> None:
    """``49 USC 1421 to 1431`` (RIN 2120-AE42, 1995-10), the review's § J row 11.

    The parse captured the range end and the build published bare 1421's seven
    successors as the range's answer. Eleven former sections are cited; the
    volume prints all eleven; the answer is their union, and ``members`` keeps
    each one's own so the union is never read as one section's.

    The paired negative is the same section without the range: asking about
    1421 alone must still answer about 1421 alone.
    """

    span = tables().disposition(49, "1421", section_end="1431")
    assert span.covers == tuple(str(number) for number in range(1421, 1432))
    assert span.former_section_end == "1431"

    bare = tables().disposition(49, "1421")
    assert bare.covers == ("1421",)
    assert bare.members == ()
    assert bare.former_section_end is None

    # Every successor of the head section survives, and ELEVEN more arrive
    # that a bare-1421 answer never named.
    def named(answer):
        return [f"{one.title}:{one.section}" for one in answer.successors]

    assert named(bare) == ["49:44701", "49:44702", "49:44712", "49:44714", "49:44716", "49:44717", "49:44722"]
    assert named(span)[: len(bare.successors)] == named(bare)
    assert set(named(span)) - set(named(bare)) == {
        "49:1153", "49:44703", "49:44704", "49:44705", "49:44707", "49:44708",
        "49:44709", "49:44710", "49:44711", "49:44713", "49:44715",
    }
    # Three members the review named, with their own answers intact.
    per_member = {member.former_section: named(member) for member in span.members}
    assert per_member["1423"] == ["49:44702", "49:44704"]
    assert per_member["1429"] == ["49:44709", "49:1153", "49:44710"]
    assert per_member["1430"] == ["49:44711"]
    # And the union is exactly the members' own, in member order.
    assert named(span) == list(dict.fromkeys(one for member in span.members for one in named(member)))


def test_a_spans_members_are_the_volumes_own_keys_and_never_a_count() -> None:
    """``1 to 85`` is 84 former sections, not 85, and four of them are lettered.

    The Interstate Commerce Act span the Agenda writes 143 times. Counting
    from 1 to 85 would claim ``24``, ``28`` … which the 1994 volume does not
    print, and would MISS ``1a``, ``5a``, ``15b``, ``26c`` — real former
    sections that no integer walk reaches. Membership by order key takes the
    printed keys and only those.
    """

    span = tables().disposition(49, "1", section_end="85")
    assert len(span.covers) == 84
    assert {"1a", "5a", "5b", "5c", "15a", "15b", "26a", "26b", "26c", "65a"} <= set(span.covers)
    assert {"24", "28", "29", "30", "40", "68", "69", "70"} & set(span.covers) == set()
    assert span.covers == tuple(
        section for section in span.covers if section in tables().former_sections(49)
    )
    # A backwards range, and a range whose endpoint the grammar never read,
    # are both "no span" rather than a guess at one.
    assert tables().sections_in_span(49, "1431", "1421") == ()
    assert tables().sections_in_span(49, "1421", None) == ()
    assert tables().disposition(49, "1421", section_end=None).members == ()


def test_a_span_the_table_lists_nothing_inside_is_an_absence_as_wide_as_the_table() -> None:
    """And a span answers ``repealed-no-successor`` when every member is gone."""

    empty = tables().disposition(49, "9001", section_end="9009")
    assert (empty.verdict, empty.members, empty.rows) == ("not-in-table", (), ())
    assert empty.caveats == NOT_IN_TABLE_CAVEATS
    assert empty.former_section_end == "9009"

    # "49 USC 401 to 417" (RIN 2105-AE04, 2011-04): three members, all struck.
    gone = tables().disposition(49, "401", section_end="417")
    assert (gone.verdict, gone.covers) == ("repealed-no-successor", ("401", "402", "403"))
    assert gone.successors == ()


def test_a_pinpoint_beside_a_span_narrows_the_member_it_is_written_on() -> None:
    """One citation's ``(a)`` is not ten sections' ``(a)``.

    No row of the pinned corpus states both today, which is why the rule is
    written down here rather than left to be discovered: the pinpoint follows
    the START token in the filer's own text, so it narrows that member and
    every other member answers whole.
    """

    span = tables().disposition(49, "1421", "(a)", section_end="1423")
    by_member = {member.former_section: member for member in span.members}
    assert by_member["1421"].subsection_resolved is True
    assert [f"{one.title}:{one.section}" for one in by_member["1421"].successors] == ["49:44701"]
    assert by_member["1422"].subsection_resolved is None
    assert by_member["1423"].successors == tables().disposition(49, "1423").successors
    assert span.subsection_resolved is True


@cache
def _by_section() -> dict[str, tuple[dict, ...]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows():
        grouped.setdefault(normalize_section(row["former_section"]), []).append(row)
    return {key: tuple(value) for key, value in grouped.items()}


# --------------------------------------------------------------------------- #
# The invariants, broken on purpose


def _row(**overrides: object) -> DispositionRow:
    base = {
        "former_section": "1432",
        "former_subsection": "(d)",
        "former_note": None,
        "successor": Successor(title=49, section="44914", subsection=None, status="restated"),
        "status": "restated",
        "former_text": "1432(d)",
        "new_text": "44914",
        "page": 8,
        "column": "right",
    }
    return DispositionRow(**{**base, **overrides})


def _disposition(**overrides: object) -> Disposition:
    base = {
        "former_title": 49,
        "former_section": "1432",
        "subsection": (),
        "verdict": "exists-as-recodified",
        "recodification": "title-49-1994",
        "successors": (Successor(title=49, section="44914", subsection=None, status="restated"),),
        "rows": (_row(),),
        "subsection_resolved": None,
    }
    return Disposition(**{**base, **overrides})


def test_a_successor_cannot_carry_a_status_that_denies_it() -> None:
    with pytest.raises(ValueError, match="cannot carry the status"):
        Successor(title=49, section="44914", subsection=None, status="repealed")
    with pytest.raises(ValueError, match="undeclared status"):
        Successor(title=49, section="44914", subsection=None, status="moved")


def test_a_row_names_a_successor_exactly_when_its_status_says_so() -> None:
    with pytest.raises(ValueError, match="exactly when its status"):
        _row(successor=None)
    with pytest.raises(ValueError, match="exactly when its status"):
        _row(status="repealed", new_text="Rep.")


def test_a_verdict_cannot_be_undeclared_or_contradict_its_own_fields() -> None:
    with pytest.raises(ValueError, match="undeclared verdict"):
        _disposition(verdict="recodified")
    with pytest.raises(ValueError, match="names its successors"):
        _disposition(verdict="repealed-no-successor")
    with pytest.raises(ValueError, match="only as wide as the table"):
        _disposition(verdict="not-in-table", successors=(), rows=())
    with pytest.raises(ValueError, match="cannot carry rows"):
        _disposition(verdict="not-in-table", successors=(), caveats=NOT_IN_TABLE_CAVEATS)
    with pytest.raises(ValueError, match="only an absence"):
        _disposition(caveats=NOT_IN_TABLE_CAVEATS)
    assert set(VERDICTS) == {
        "exists-as-recodified",
        "repealed-no-successor",
        "stated-without-successor",
        "not-in-table",
        "no-table-for-title",
    }


def test_a_span_cannot_be_published_as_anything_but_its_members_union() -> None:
    """The three ways a span answer could lie, each raising.

    Members without a far end would let a one-section answer wear a union's
    clothes; a member that is itself a span would let a breakdown nest until
    nobody reads it; and successors that are not the members' own would let
    the flattened list drift from the breakdown that is supposed to explain
    it — which is the exact failure this whole change is about.
    """

    member = _disposition()
    with pytest.raises(ValueError, match="only a span has members"):
        _disposition(members=(member,))
    with pytest.raises(ValueError, match="cannot itself be a span"):
        _disposition(
            former_section_end="1440",
            members=(_disposition(former_section_end="1436", members=(member,)),),
        )
    with pytest.raises(ValueError, match="union over its members"):
        _disposition(
            former_section_end="1440",
            members=(_disposition(verdict="repealed-no-successor", successors=()),),
            successors=(Successor(title=49, section="44914", subsection=None, status="restated"),),
        )
    assert _disposition(former_section_end="1440", members=(member,)).covers == ("1432",)


# --------------------------------------------------------------------------- #
# The corpus: the 2,548 rows this table was built for


@cache
def unknown_rows() -> tuple[tuple, ...]:
    """Every row of the pinned build the section oracle cannot see.

    Read by digest from the section oracle's artifact. The filter is the
    oracle's own verdict — ``unknown`` for the reason
    ``title_49_appendix_not_published`` — not a guess about which sections are
    Title 49 Appendix ones, so this measures exactly the population the reason
    code names.
    """

    import pyarrow.parquet as pq

    digest = f"sha256:{hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()}"
    assert digest == SNAPSHOT_DIGEST, "the measured build is not the build on disk"
    table = pq.read_table(
        SNAPSHOT,
        columns=[
            "rin",
            "publication_id",
            "ordinal",
            "citation_ordinal",
            "authority_text",
            "authority_type",
            "usc_title",
            "usc_section",
            "usc_appendix",
        ],
    )
    columns = {name: table.column(name).to_pylist() for name in table.schema.names}
    oracle = UscSectionOracle.from_repository(ROOT)
    verdicts: dict[tuple, object] = {}
    out = []
    for row in zip(*columns.values(), strict=True):
        if row[5] != "usc" or row[6] is None or row[7] is None:
            continue
        key = (row[6], normalize_section(row[7]), bool(row[8]), int(row[1][:4]))
        verdict = verdicts.get(key)
        if verdict is None:
            verdict = verdicts[key] = oracle.section_verdict(key[0], key[1], key[3], appendix=key[2])
        if verdict.verdict == "unknown" and verdict.reason == "title_49_appendix_not_published":
            out.append((row[0], row[1], row[2], row[3], row[4], key[1]))
    return tuple(sorted(out))


@cache
def _answers() -> dict[str, Disposition]:
    return {section: tables().disposition(49, section) for _, _, _, _, _, section in unknown_rows()}


@pytest.mark.slow
def test_the_population_is_the_one_the_review_counted() -> None:
    """2,548 rows over 146 distinct sections — the § F headline, reproduced."""

    assert len(unknown_rows()) == 2_548
    assert len({row[5] for row in unknown_rows()}) == 146


@pytest.mark.slow
def test_how_many_of_the_unknown_rows_the_table_answers() -> None:
    """93.1% of the rows, on the reason code the review said it would close.

    Counted by row and by distinct section, because the two say different
    things: the sections the table misses are more numerous in proportion than
    the rows they carry, which is what a hold-out of malformed one-off tokens
    looks like.
    """

    by_row = collections.Counter(_answers()[row[5]].verdict for row in unknown_rows())
    by_section = collections.Counter(answer.verdict for answer in _answers().values())
    assert by_row == {"exists-as-recodified": 2_237, "not-in-table": 177, "repealed-no-successor": 134}
    assert by_section == {"exists-as-recodified": 100, "not-in-table": 27, "repealed-no-successor": 19}
    assert sum(count for verdict, count in by_row.items() if verdict != "not-in-table") == 2_371
    # Nothing in this population is answered by a title with no table: they are
    # all title 49 by construction.
    assert {answer.recodification for answer in _answers().values()} == {"title-49-1994"}


#: Ten of the 2,371 answered rows, drawn with ``random.Random(20260823)`` from
#: the sorted population, each as ``(RIN, edition, the filer's own text, the
#: verdict, the successors)``. Frozen so a human can read them against the
#: pages once and a later change has to explain itself.
BY_EYE = (
    ("2120-AH88", "200510", "49 USC 100(g)", "100", "exists-as-recodified", ("80113",)),
    ("2105-AA84", "200104", "49 USC 1381", "1381", "exists-as-recodified", ("41712", "41707")),
    ("2120-AC43", "199510", "49 USC 1421", "1421", "exists-as-recodified",
     ("44701", "44702", "44712", "44714", "44716", "44717", "44722")),
    ("1902-AF93", "202210", "49 U.S.C. App. 13, 15 (1988)", "15", "exists-as-recodified",
     ("10704", "10324", "10705", "10748", "10708", "10707", "10709", "10763", "11710", "11910", "10747",
      "10321", "10727", "10728", "10729")),
    ("2120-AD16", "199510", "49 USC 1402", "1402", "exists-as-recodified", ("44104",)),
    ("2120-AJ97", "201110", "49 USC 1726", "1726", "repealed-no-successor", ()),
    ("2120-AB17", "199510", "49 USC 1485", "1485", "exists-as-recodified", ("46105", "46103")),
    ("2120-AD16", "199510", "49 USC 1401", "1401", "exists-as-recodified",
     ("44101", "44102", "44103", "44105", "44106", "44111", "44703", "44713")),
    ("2105-AA88", "200004", "49 USC 1371 to 1374", "1371", "exists-as-recodified",
     ("41101", "41108", "41102", "41503", "41110", "41109", "41105", "41312", "42112", "41903", "41107",
      "41104", "41106", "41111", "41112")),
    ("2120-AE92", "199510", "49 USC 1401", "1401", "exists-as-recodified",
     ("44101", "44102", "44103", "44105", "44106", "44111", "44703", "44713")),
)


@pytest.mark.slow
def test_ten_answered_rows_a_human_can_check_by_eye() -> None:
    """The filer's text beside the disposition, for the ten drawn at seed 20260823.

    Row 6 is the one to read hardest: ``49 USC 1726`` in a **2011** filing, and
    the table prints ``1714-1730 … Rep.`` — the filer was citing a numbering
    that had been gone for seventeen years, which is the same finding § F row 10
    made about ``1510`` and the reason a disposition verdict is worth more here
    than a correction.
    """

    answered = [row for row in unknown_rows() if _answers()[row[5]].answered]
    assert len(answered) == 2_371
    drawn = random.Random(20260823).sample(answered, 10)
    read = tuple(
        (row[0], row[1], row[4], row[5], _answers()[row[5]].verdict,
         tuple(s.section for s in _answers()[row[5]].successors))
        for row in drawn
    )
    assert read == BY_EYE


@pytest.mark.slow
def test_every_section_where_the_table_gives_several_successors() -> None:
    """1,779 of the 2,548 rows. **Candidates, never an identity.**

    This is the number that decides how the next cycle may publish: on 62 of
    the 146 sections the table names more than one successor, so a consumer
    that keyed a tag on "the" successor would be wrong on the majority of the
    rows this table answers. The prose in ``former_text`` is what separates
    them, and it is not machine-decidable from the citation alone.
    """

    several = {section for section, answer in _answers().items() if len(answer.successors) > 1}
    rows_covered = sum(1 for row in unknown_rows() if row[5] in several)
    assert (len(several), rows_covered) == (62, 1_779)
    exactly_one = {section for section, answer in _answers().items() if len(answer.successors) == 1}
    assert (len(exactly_one), sum(1 for row in unknown_rows() if row[5] in exactly_one)) == (38, 458)
    assert len(several) + len(exactly_one) + 19 + 27 == 146


#: The 27 sections of the population the table does not list, with their rows
#: and one of the filer's texts. Not a failure of the extraction: read them and
#: the reason is visible — 14 CFR chapter III part numbers in the U.S.C. slot
#: (401-465, the commercial space licensing parts), a Privacy Act citation
#: under the wrong title (``552a(k)``), two descending ranges (``166 to 117``,
#: ``1491 to 1406``), a Statutes page read as a section (``1763``), and a
#: current section of the new title mis-shaped (``114l`` for 114(l)).
HOLD_OUT = (
    ("417", 39, "49 USC 417"),
    ("411", 37, "49 USC 411"),
    ("413", 23, "49 USC 413"),
    ("374", 12, "49 USC 374(a)"),
    ("322a", 8, "49 USC 322a"),
    ("415", 6, "49 USC 415"),
    ("552a", 6, "49 USC 552a(k)"),
    ("190", 5, "49 USC 190 60101 et seq"),
    ("217", 5, "49 U.S.C. 217(a), 1.51(F), 1.81, 1.85 and 1.90"),
    ("3102", 5, "49 USC app 3102"),
    ("1392", 3, "49 USC 1392"),
    ("1509d", 3, "49 USC 1509d"),
    ("166", 3, "49 U.S.C. 166 to 117"),
    ("29", 3, "49 USC 29"),
    ("10109", 2, "49 USC 10109"),
    ("1085", 2, "49 App. USC 1085 (1988)"),
    ("419", 2, "49 USC 401, 411, 413. 415, 417, 419, 421, 449, 461, 463, 465"),
    ("449", 2, "49 USC 401, 411, 413. 415, 417, 419, 421, 449, 461, 463, 465"),
    ("463", 2, "49 USC 401, 411, 413. 415, 417, 419, 421, 449, 461, 463, 465"),
    ("465", 2, "49 USC 401, 411, 413. 415, 417, 419, 421, 449, 461, 463, 465"),
    ("114l", 1, "49 USC 114l"),
    ("134", 1, "49 USC 134"),
    ("1491", 1, "49 USC 1491 to 1406"),
    ("1763", 1, "49 USC 13908, as amended by sec 4304 of PL 109-159, 119 Stat 1144, 1763"),
    ("40", 1, "49 U.S.C. 40"),
    ("406", 1, "49 USC 406(f)"),
    ("447", 1, "49 USC 106(g), 447 and 451"),
)


@pytest.mark.slow
def test_the_hold_out_is_named_row_by_row() -> None:
    """177 rows the table cannot answer, and why — never a bare shortfall.

    A count of what a source does not cover is only useful with the specimens
    beside it; without them "27 sections" reads as a gap in the table, and
    reading them shows most of it is damage in the citation instead.
    """

    held: dict[str, list] = {}
    for row in unknown_rows():
        if not _answers()[row[5]].answered:
            held.setdefault(row[5], []).append(row[4])
    listed = tuple(
        sorted(
            ((section, len(texts), collections.Counter(texts).most_common(1)[0][0]) for section, texts in held.items()),
            key=lambda item: (-item[1], item[0]),
        )
    )
    assert listed == tuple(sorted(HOLD_OUT, key=lambda item: (-item[1], item[0])))
    assert sum(count for _, count, _ in HOLD_OUT) == 177
    assert all(_answers()[section].verdict == "not-in-table" for section, _, _ in HOLD_OUT)
