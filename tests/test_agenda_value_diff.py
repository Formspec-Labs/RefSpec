"""Regression coverage for tools/agenda_value_diff.py's column blindness.

Review finding (2026-08-31): the tool's per-table value-column lists were
hand-maintained tuples that had drifted from the producer's own schemas. The
arithmetic, recomputed from ``git show HEAD:tools/agenda_value_diff.py``
against ``LEGAL_AUTHORITIES_SCHEMA``
(``refspec.registry.unified_agenda_parquet``):

    94 schema columns (91 at the review; +3 on 2026-08-31 -- usc_slot_reading
       and the two placeholder-candidate columns -- which the schema-derived
       list picked up without a hand edit, the point of the rework)
     - 4 key columns (rin, publication_id, ordinal, authority_text)
     - 1 deliberate exclusion (citation_ordinal)
    ------------------------------------------------------------------
    = 89 value columns the diff owes a comparison (86 at the review)

    the hand list named 41 of the 86 (all 41 real columns, none stale)
    ------------------------------------------------------------------
    = 45 value columns the diff was blind to

So a rebuild that moved a value only in one of those 45 -- the whole join/carry
family (``authority_source``, ``authority_box_run_start``,
``authority_join_rule``, ``usc_title_carried_from_ordinal``,
``superseded_by_join``, ...) included -- diffed as "no change". Confirmed by
running the pre-fix tool (git HEAD) against a real-artifact pair that differs
in exactly one ``superseded_by_join`` cell: it printed "VANISHED values: 0 /
ARRIVED values: 0". The fixed tool, on the identical pair, reports the one
VANISHED and one ARRIVED value. (An earlier revision of this docstring said
the hand list "carried only 45 of the 86" -- 45 was the BLIND count, not the
covered one, and 45 + 45 does not make 86. The numbers above are the measured
ones; ``test_the_recorded_arithmetic_is_the_measured_arithmetic`` pins them.)

The timetables hand list was, by contrast, complete: 16 schema columns, less
the 4-column key and ``citation_ordinal``, is 11, and it named all 11.

The fix makes each table's value columns a DERIVATION from the producer's own
schema -- imported read-only from ``refspec.registry.unified_agenda_parquet``,
never re-declared here -- rather than a hand list: every schema column is
either the key, a named-and-justified exclusion (``ignore``), or a value that
gets diffed. There is no fourth bucket. The tests below are the structural
tripwire this buys: they fail the day a schema gains a column that lands in
none of those three, which is exactly the failure mode a hand list cannot
detect until someone is bitten by it in production.

Review finding 11 (2026-08-31): each side intersected the expected columns
with the physical schema and only ever reported the NEW-only ones, so a column
DELETED from the new artifact printed "columns only in new: []" and zero
differences -- total silence about every value that left with it. The tool now
reports the old-only columns and their departed values symmetrically, and says
out loud when a column the schema declares is in neither file.
``test_a_column_removed_from_the_new_artifact_is_reported`` and
``test_a_column_absent_from_both_sides_is_reported`` are the tripwires.

Review finding 5 (2026-08-31): the diff core loaded both tables fully into
Python objects and measured 14.428 GiB resident on the real self-diff, enough
to OOM an 8-16 GiB host once `make test`'s `pytest -n auto` overlapped it with
the rest of the slow tier. It is now a streaming, digest-keyed multiset diff.
``test_the_streaming_diff_agrees_with_the_pre_rework_oracle`` is the
verdict-agreement proof AGENTS.md requires of a replaced check, with the
pre-rework core copied in below rather than imported.
"""

from __future__ import annotations

import collections
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from refspec.registry.unified_agenda_parquet import LEGAL_AUTHORITIES_SCHEMA, TIMETABLES_SCHEMA
from tools import agenda_value_diff
from tools.agenda_value_diff import TABLES, main

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = REPOSITORY_ROOT / "output" / "registry-real-data-sources" / "unified-agenda-parquet"
LEGAL_AUTHORITIES_FILE = "unified_agenda_legal_authorities.parquet"

#: The producer schema for each table this tool covers, imported the same way
#: the tool itself does -- read-only, never copied -- so this file's notion of
#: "every column" can never drift from the tool's.
_SCHEMAS = {
    "legal-authorities": LEGAL_AUTHORITIES_SCHEMA,
    "timetables": TIMETABLES_SCHEMA,
}

#: Declared here rather than read off ``TABLES``, so the oracle at the bottom
#: of this file -- which has to be independent of the module it is checking --
#: can derive the same value columns without importing the derivation under
#: test. That independence is also what makes these two dicts a cross-check on
#: ``TABLES`` itself: ``test_every_schema_column_is_diffed_or_named_ignored``
#: and ``test_ignored_columns_are_exactly_the_documented_set`` fail if the tool
#: ever disagrees with them.
_KEYS = {
    "legal-authorities": ("rin", "publication_id", "ordinal", "authority_text"),
    "timetables": ("rin", "publication_id", "ordinal", "fr_citation_text"),
}
_SHAPES = {
    "legal-authorities": ("authority_type", "parse_status"),
    "timetables": ("parse_status", "fr_correction_evidence"),
}
_IGNORED = frozenset({"citation_ordinal"})

#: The 45 legal-authorities columns the review measured as blind, independent
#: of ``TABLES`` -- named here so a future refactor that keeps the derivation
#: mechanism but narrows what it covers still fails a test that says exactly
#: what regressed, rather than only "some column somewhere". Measured
#: 2026-08-31 as (LEGAL_AUTHORITIES_SCHEMA.names) minus (the pre-fix hand list)
#: minus (the key) minus the one deliberate exclusion, citation_ordinal.
_PREVIOUSLY_BLIND_LEGAL_AUTHORITIES_COLUMNS = frozenset(
    {
        "unstated_kind",
        "usc_chapter",
        "usc_chapter_end",
        "cfr_part_is_plausible",
        "reorganization_plan",
        "usc_title_is_possible",
        "usc_section_correction_evidence",
        "usc_section_magnitude_is_plausible",
        "eo_in_known_series",
        "pl_congress_in_series",
        "stat_volume_in_series",
        "statute_volume_matches_public_law",
        "case_reporter",
        "case_volume",
        "case_page",
        "presidential_doc_kind",
        "proclamation",
        "admin_order_kind",
        "admin_order_number",
        "treaty_volume",
        "treaty_number",
        "treaty_page",
        "constitution_article",
        "constitution_section",
        "usc_note",
        "executive_order",
        "statute_page",
        "statute_volume_text",
        "fr_volume",
        "fr_page",
        "fr_volume_in_series",
        "fr_page_in_series",
        "revised_statute_section",
        "dc_code_section",
        "authority_label_corrected",
        "label_correction_evidence",
        # The join/carry family: which publisher field a citation was written
        # in, whether a continuation row repeats a box, the box run a joined
        # citation list was cut across and the rule and text that produced it,
        # which box carried a U.S.C. title into a fragment, and which rows a
        # join superseded.
        "authority_source",
        "restates_box_citation",
        "authority_box_run_start",
        "authority_box_run_length",
        "authority_join_rule",
        "authority_join_text",
        "usc_title_carried_from_ordinal",
        "authority_carry_text",
        "superseded_by_join",
    }
)


def test_the_measured_blind_set_is_exactly_45_columns() -> None:
    """Pins the review's headline number against the schema this file reads
    independently, so a schema edit that changes the count is visible here
    rather than only in the tool it is meant to describe."""

    assert len(_PREVIOUSLY_BLIND_LEGAL_AUTHORITIES_COLUMNS) == 45
    assert _PREVIOUSLY_BLIND_LEGAL_AUTHORITIES_COLUMNS <= set(LEGAL_AUTHORITIES_SCHEMA.names)


def test_the_recorded_arithmetic_is_the_measured_arithmetic() -> None:
    """94 - 4 key - 1 ignored = 89 owed, 45 blind, therefore 44 covered
    (91 / 86 / 41 at the review; the three loud-tier columns of 2026-08-31
    arrived through the schema, not the hand list).

    The docstring at the top of this file used to say the hand list "carried
    only 45 of the 86 non-key ones" while also naming 45 as the blind count --
    an impossible pair, since 45 covered plus 45 blind is 90, not 86 (review
    finding 13). The three numbers are now tied together here, so no future
    edit can restate two of them in a way the third contradicts.
    """

    owed = len(LEGAL_AUTHORITIES_SCHEMA.names) - len(_KEYS["legal-authorities"]) - len(_IGNORED)
    assert (len(LEGAL_AUTHORITIES_SCHEMA.names), len(_KEYS["legal-authorities"]), len(_IGNORED)) == (
        94,
        4,
        1,
    )
    assert owed == 89
    assert owed - len(_PREVIOUSLY_BLIND_LEGAL_AUTHORITIES_COLUMNS) == 44

    # And timetables, where the hand list happened to be complete: 16 - 4 - 1
    # is 11, and none of the 11 were blind.
    assert len(TIMETABLES_SCHEMA.names) - len(_KEYS["timetables"]) - len(_IGNORED) == 11


@pytest.mark.parametrize("table", sorted(TABLES))
def test_the_tool_agrees_with_this_file_about_key_ignore_and_shape(table: str) -> None:
    """``_KEYS``/``_SHAPES``/``_IGNORED`` are declared independently above so
    the oracle can stay out of the module it checks; if the tool ever moves
    away from them the oracle would be checking a different question, so pin
    the agreement rather than let it drift."""

    assert TABLES[table]["key"] == _KEYS[table]
    assert TABLES[table]["shape"] == _SHAPES[table]
    assert TABLES[table]["ignore"] == _IGNORED


@pytest.mark.parametrize("table", sorted(TABLES))
def test_every_schema_column_is_diffed_or_named_ignored(table: str) -> None:
    """The tripwire. Every column the producer's schema declares is either the
    key, a named-and-commented exclusion, or a diffed value -- never silently
    absent from all three. This is computed against ``_SCHEMAS``, imported
    independently in this file rather than read off ``TABLES`` itself, so it
    would still catch a regression to a hand-maintained ``values`` tuple even
    if that regression also removed the ``schema`` key from ``TABLES``."""

    spec = TABLES[table]
    schema_columns = set(_SCHEMAS[table].names)
    accounted = set(spec["key"]) | set(spec["ignore"]) | set(spec["values"])
    missing = schema_columns - accounted
    assert not missing, f"{table}: schema column(s) neither keyed, ignored, nor diffed: {sorted(missing)}"

    # And the inverse: nothing claimed as a value that the schema does not
    # have, and no column double-booked as both a key and a value.
    assert set(spec["values"]) <= schema_columns
    assert not (set(spec["key"]) & set(spec["values"]))
    assert not (set(spec["ignore"]) & set(spec["values"]))


def test_ignored_columns_are_exactly_the_documented_set() -> None:
    """``ignore`` widening silently would re-open exactly the hole this file
    exists to close, so it is pinned to the one column that is deliberately
    excluded on BOTH tables, and reasoned about in the module docstring:
    ``citation_ordinal`` is the renumbering the diff exists to see through,
    not a value a consumer reads."""

    assert TABLES["legal-authorities"]["ignore"] == frozenset({"citation_ordinal"})
    assert TABLES["timetables"]["ignore"] == frozenset({"citation_ordinal"})


def test_previously_blind_columns_are_now_diffed() -> None:
    values = set(TABLES["legal-authorities"]["values"])
    still_blind = _PREVIOUSLY_BLIND_LEGAL_AUTHORITIES_COLUMNS - values
    assert not still_blind, f"still blind after the fix: {sorted(still_blind)}"


def test_legal_authorities_value_column_count() -> None:
    """94 schema columns, less the 4-column key and the one deliberate
    exclusion, is 89 -- pinned as a number so a column quietly added to
    ``ignore`` (rather than to ``values``, where the schema puts it) changes
    a count here even if it passes the set-membership tripwire above by
    accident of some other column moving the other way."""

    assert len(LEGAL_AUTHORITIES_SCHEMA.names) == 94
    assert len(TABLES["legal-authorities"]["values"]) == 89


def test_timetables_value_column_count() -> None:
    assert len(TIMETABLES_SCHEMA.names) == 16
    assert len(TABLES["timetables"]["values"]) == 11


# ---------------------------------------------------------------------------
# Verification against the real artifact. Real data alone only proves the
# tool accepts what is unchanged; the mutation test below proves it rejects
# what changed, per AGENTS.md.
# ---------------------------------------------------------------------------

pytestmark_real_artifact = pytest.mark.skipif(
    not ARTIFACT.is_dir(), reason="derived Unified Agenda Parquet artifact is not built"
)


@pytestmark_real_artifact
@pytest.mark.slow
@pytest.mark.parametrize("table", sorted(TABLES))
def test_self_diff_against_the_real_artifact_reports_zero_differences(table: str, capsys) -> None:
    """The tool run against one build twice must see nothing move, across
    every column the schema declares -- not just the ones a hand list used to
    cover. A tool that reported spurious differences on a self-diff would be
    just as useless as one blind to real ones.

    Cost, measured on the real artifact with ``resource.getrusage`` around
    ``main()`` (2026-08-31, review finding 5):

        legal-authorities  800,573 rows x 91 columns   14.428 GiB / 105.6 s
                           after the streaming rework   0.414 GiB /  46.6 s
        timetables         671,959 rows x 16 columns    2.573 GiB /  20.5 s
                           after the streaming rework   0.284 GiB /  10.5 s

    The 14.428 GiB figure is why the rework happened: this test is slow-marked
    and `make test` runs the slow tier under `pytest -n auto`, so it overlapped
    the rest of that tier and could take an 8-16 GiB host out. The peak is now
    a ``BATCH_ROWS``-wide decode plus one 16-byte digest per row per side; keep
    it there, and keep this note honest if the artifact grows.
    """

    main(str(ARTIFACT), str(ARTIFACT), table)
    out = capsys.readouterr().out
    assert "columns only in new: []" in out
    assert "columns only in old: []" in out
    assert "columns in NEITHER file that the schema declares: []" in out
    assert "VANISHED values: 0" in out
    assert "ARRIVED values: 0" in out


@pytestmark_real_artifact
def test_mutation_in_a_previously_blind_column_is_detected(tmp_path: Path, capsys) -> None:
    """Change one value in ``superseded_by_join`` -- a join/carry column that
    was entirely absent from the pre-fix hand list -- on an otherwise-identical
    copy of a slice of the real artifact, and confirm the tool reports it.

    Reads from the real pinned artifact (not a synthetic table) so the schema,
    dtypes, and null patterns are the ones a real rebuild would produce; sliced
    to the rows up to and including the first ``True`` so the run stays fast
    without inventing data.
    """

    real = pq.read_table(ARTIFACT / "unified_agenda_legal_authorities.parquet")
    column_values = real.column("superseded_by_join").to_pylist()
    mutate_index = next(i for i, v in enumerate(column_values) if v is True)

    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()

    sliced = real.slice(0, mutate_index + 1)
    pq.write_table(sliced, old_dir / "unified_agenda_legal_authorities.parquet")

    mutated_column = sliced.column("superseded_by_join").to_pylist()
    assert mutated_column[mutate_index] is True
    mutated_column[mutate_index] = False
    mutated = sliced.set_column(
        sliced.schema.get_field_index("superseded_by_join"),
        "superseded_by_join",
        pa.array(mutated_column, type=pa.bool_()),
    )
    pq.write_table(mutated, new_dir / "unified_agenda_legal_authorities.parquet")

    main(str(old_dir), str(new_dir), "legal-authorities")
    out = capsys.readouterr().out

    assert "VANISHED values: 1" in out
    assert "ARRIVED values: 1" in out
    assert "'superseded_by_join': True" in out
    assert "'superseded_by_join': False" in out


@pytestmark_real_artifact
def test_mutation_in_a_never_blind_column_is_still_detected(tmp_path: Path, capsys) -> None:
    """Sanity check on the harness itself: a mutation in a column the tool
    already covered before this fix (``parse_status``) must still be caught,
    so the tests above are exercising sensitivity generally and not something
    specific to the newly-covered columns."""

    real = pq.read_table(ARTIFACT / "unified_agenda_legal_authorities.parquet")
    sliced = real.slice(0, 200)

    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    pq.write_table(sliced, old_dir / "unified_agenda_legal_authorities.parquet")

    parse_status = sliced.column("parse_status").to_pylist()
    mutate_index = next(i for i, v in enumerate(parse_status) if v != "mutated-status")
    parse_status[mutate_index] = "mutated-status"
    mutated = sliced.set_column(
        sliced.schema.get_field_index("parse_status"),
        "parse_status",
        pa.array(parse_status, type=pa.string()),
    )
    pq.write_table(mutated, new_dir / "unified_agenda_legal_authorities.parquet")

    main(str(old_dir), str(new_dir), "legal-authorities")
    out = capsys.readouterr().out

    assert "VANISHED values: 1" in out
    assert "ARRIVED values: 1" in out


# ---------------------------------------------------------------------------
# Review finding 11: a column that LEFT the new artifact.
# ---------------------------------------------------------------------------


def _real_slice(rows: int) -> pa.Table:
    """The first ``rows`` rows of the real legal-authorities artifact.

    One Parquet batch rather than the whole file: a test that needs a few
    hundred rows should not pay ~440 MiB of Arrow buffers to get them.
    """

    handle = pq.ParquetFile(ARTIFACT / LEGAL_AUTHORITIES_FILE)
    return pa.Table.from_batches([next(handle.iter_batches(batch_size=rows))])


def _pair(tmp_path: Path, old: pa.Table, new: pa.Table) -> tuple[Path, Path]:
    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    pq.write_table(old, old_dir / LEGAL_AUTHORITIES_FILE)
    pq.write_table(new, new_dir / LEGAL_AUTHORITIES_FILE)
    return old_dir, new_dir


@pytestmark_real_artifact
def test_a_column_removed_from_the_new_artifact_is_reported(tmp_path: Path, capsys) -> None:
    """Drop ``stated_act_name`` from the new side and the tool must say so.

    The reviewer's synthetic for finding 11. Both sides used to intersect the
    expected columns with their own physical schema and only the NEW-only
    residue was ever printed, so this pair produced "columns only in new: []",
    "VANISHED values: 0", "ARRIVED values: 0" -- a build that lost a whole
    column, and every value in it, read exactly like a build that changed
    nothing. Verified against the pre-fix tool (git HEAD) on this same pair:
    it printed those three lines and nothing else.

    Nothing VANISHES here on purpose: the comparison is still on shared
    columns, so the rows themselves are unchanged. What the column took with
    it is reported as its own departure line, which is the point -- silence
    was the bug, not the zero.
    """

    sliced = _real_slice(2000)
    departed = sum(1 for v in sliced.column("stated_act_name").to_pylist() if v is not None)
    assert departed >= 10, "pick a slice where the dropped column actually carried values"

    old_dir, new_dir = _pair(tmp_path, sliced, sliced.drop_columns(["stated_act_name"]))
    main(str(old_dir), str(new_dir), "legal-authorities")
    out = capsys.readouterr().out

    assert "columns only in old: ['stated_act_name']" in out
    assert f"DEPARTED from old column stated_act_name: {departed}" in out
    assert "columns only in new: []" in out
    assert "VANISHED values: 0" in out
    assert "ARRIVED values: 0" in out


@pytestmark_real_artifact
def test_a_column_added_to_the_new_artifact_is_still_reported(tmp_path: Path, capsys) -> None:
    """The mirror of the test above, so the symmetry is a checked claim and
    not just a shape in the code: the arrival direction, which already worked,
    keeps working and keeps its own wording."""

    sliced = _real_slice(2000)
    arrived = sum(1 for v in sliced.column("stated_act_name").to_pylist() if v is not None)

    old_dir, new_dir = _pair(tmp_path, sliced.drop_columns(["stated_act_name"]), sliced)
    main(str(old_dir), str(new_dir), "legal-authorities")
    out = capsys.readouterr().out

    assert "columns only in new: ['stated_act_name']" in out
    assert f"ARRIVED in new column stated_act_name: {arrived}" in out
    assert "columns only in old: []" in out


@pytestmark_real_artifact
def test_a_column_absent_from_both_sides_is_reported(tmp_path: Path, capsys) -> None:
    """A schema column missing from BOTH files gets its own loud line.

    This is the case neither "only in new" nor "only in old" can ever name --
    each side intersects it away, and the set difference of two sets that both
    lack it is empty -- so before finding 11 it was pure silence: 86 columns
    owed a comparison and 85 getting one looked exactly like 86 getting one.
    """

    without = _real_slice(400).drop_columns(["stated_act_name"])
    old_dir, new_dir = _pair(tmp_path, without, without)
    main(str(old_dir), str(new_dir), "legal-authorities")
    out = capsys.readouterr().out

    assert "columns only in new: []" in out
    assert "columns only in old: []" in out
    assert "columns in NEITHER file that the schema declares: ['stated_act_name']" in out


# ---------------------------------------------------------------------------
# Review residual 3: a column retired from BOTH the artifact and the current
# producer schema.
#
# The four "columns ..." lines above are all computed from ``spec["values"]``,
# i.e. from the CURRENT schema, so both physical schemas are filtered through
# it before any of them is derived. A column the old file carries that the
# schema no longer declares is therefore dropped before the reporting starts:
# not "only in old" (that set is intersected with the expected columns), not
# "in NEITHER file" (the schema does not declare it, so it is not owed a
# comparison), and not compared. The build that retired it read as silent.
#
# The fix is one visibility line per side, deliberately reporting-only: what
# is compared is the schema's business, and these two tests pin BOTH halves --
# that the column is named, and that naming it moves no values.
# ---------------------------------------------------------------------------

_RETIRED = "retired_column_the_schema_no_longer_declares"


def _with_retired_column(table: pa.Table) -> pa.Table:
    """``table`` plus one column no schema in this repo declares."""

    assert _RETIRED not in LEGAL_AUTHORITIES_SCHEMA.names
    return table.append_column(
        _RETIRED, pa.array([f"v{i % 3}" for i in range(table.num_rows)], pa.string())
    )


@pytestmark_real_artifact
def test_a_column_only_the_old_file_carries_and_the_schema_lacks_is_named(
    tmp_path: Path, capsys
) -> None:
    """The retirement case: the producer dropped the column AND the schema
    stopped declaring it, so the new build legitimately has neither. Before
    this line the whole event was invisible -- every existing list is derived
    from the current schema, which no longer mentions it."""

    sliced = _real_slice(400)
    old_dir, new_dir = _pair(tmp_path, _with_retired_column(sliced), sliced)
    main(str(old_dir), str(new_dir), "legal-authorities")
    out = capsys.readouterr().out

    assert f"columns in old the schema does not declare (named, never compared): ['{_RETIRED}']" in out
    assert "columns in new the schema does not declare (named, never compared): []" in out
    # The lines that could not see it, still not seeing it -- which is why the
    # new line had to exist rather than one of these being widened.
    assert "columns only in old: []" in out
    assert "columns only in new: []" in out
    assert "columns in NEITHER file that the schema declares: []" in out
    # Reporting only: an undeclared column is named, never diffed.
    assert "VANISHED values: 0" in out
    assert "ARRIVED values: 0" in out


@pytestmark_real_artifact
def test_a_column_both_files_carry_and_the_schema_lacks_is_named_for_both(
    tmp_path: Path, capsys
) -> None:
    """The schema-retired-it-first case: both artifacts still carry the column
    because both were built before the schema dropped it. It is named on both
    sides -- and still not compared, so the differing values in it move
    nothing, which is the reporting-only promise stated in the report line."""

    sliced = _real_slice(400)
    old = _with_retired_column(sliced)
    new = sliced.append_column(
        _RETIRED, pa.array(["different"] * sliced.num_rows, pa.string())
    )
    old_dir, new_dir = _pair(tmp_path, old, new)
    main(str(old_dir), str(new_dir), "legal-authorities")
    out = capsys.readouterr().out

    for side in ("old", "new"):
        assert f"columns in {side} the schema does not declare (named, never compared): ['{_RETIRED}']" in out
    assert "VANISHED values: 0" in out
    assert "ARRIVED values: 0" in out


# ---------------------------------------------------------------------------
# Review finding 5: the streaming rework, against the core it replaced.
#
# AGENTS.md: a replacement of a running check keeps the old implementation as
# a test-only oracle -- copied in, not imported, since importing the thing
# under replacement makes the comparison circular -- and proves verdict
# agreement over real data AND a mutation battery. ``_oracle_report`` below is
# the pre-rework diff core from ``git show HEAD:tools/agenda_value_diff.py``
# (2026-08-31), reading the whole table into Python objects exactly as it did
# in production. That cost -- 14.428 GiB on the full artifact -- is why it is
# only ever pointed at slices here.
# ---------------------------------------------------------------------------

#: The ONLY differences allowed between the rework and the oracle. Both come
#: from the same root: the pre-rework core walked ``set(o) | set(n)``, a set of
#: key tuples of Python strings, so which row it happened to keep as a shape's
#: example and how it ordered shapes that tie on count were PYTHONHASHSEED
#: dependent -- it disagreed with ITSELF between processes. Measured
#: 2026-08-31 on a 40,000-row / 400-mutation battery: the pre-rework tool
#: produced a different report under each of PYTHONHASHSEED 0, 1, 2, 7 and
#: 12345, while the rework (which keeps the first row in FILE order) produced
#: one report every time. Every reported NUMBER and every shape agreed under
#: all five. Anything outside this list is a real divergence and fails below.
_FROZEN_DIVERGENCES = (
    "the example row printed after `e.g.` for each shape",
    "the relative order of shapes that tie on count",
)


#: Cell-tuple pairs that a sloppier encoding than the tool's would hash to the
#: same bytes. Each pair is a real forgery against a specific shortcut: drop
#: the null tag and the first pair collides; drop the string length prefix and
#: the second does (both spell ``sassb``); drop the type tags and the rest do.
#: These are cheaper and sharper than trying to make a data battery produce
#: the pattern -- the mutation run on 2026-08-31 confirmed a 6,000-row battery
#: with null-boundary mutations still let all three shortcuts through.
_FORGERY_PAIRS = (
    ((None, "x"), ("x", None)),
    (("a", "sb"), ("as", "b")),
    ((None,), ("",)),
    ((None,), ("None",)),
    ((True,), (1,)),
    ((False,), (0,)),
    (("1",), (1,)),
    ((["a", "b"],), (["ab"],)),
    # Drop the LIST length prefix and a list's tail becomes the next column.
    ((["a"], "b"), (["a", "b"],)),
    ((), ("",)),
)


@pytest.mark.parametrize(("left", "right"), _FORGERY_PAIRS)
def test_the_digest_separates_cell_tuples_that_could_forge_each_other(left, right) -> None:
    """The streaming diff compares 16-byte digests, not the rows themselves,
    so two different rows hashing alike would be a silent "no change" of
    exactly the kind this whole file exists to prevent. The encoding is
    length-prefixed and type-tagged for that reason; these pairs are the
    shortcuts it refuses."""

    assert agenda_value_diff._digest(left) != agenda_value_diff._digest(right)


def test_the_digest_is_stable_for_equal_rows() -> None:
    """The other half: rows that ARE equal must digest alike, including the
    list-valued columns the report normalises to tuples."""

    assert agenda_value_diff._digest(("a", None, 3, True, ["x", "y"])) == agenda_value_diff._digest(
        ("a", None, 3, True, ("x", "y"))
    )


def _oracle_report(old_dir: Path, new_dir: Path, table: str) -> list[str]:
    """The pre-rework diff core, rendering the report lines it used to print."""

    file_name = {
        "legal-authorities": LEGAL_AUTHORITIES_FILE,
        "timetables": "unified_agenda_timetables.parquet",
    }[table]
    key = _KEYS[table]
    values = tuple(n for n in _SCHEMAS[table].names if n not in set(key) | _IGNORED)
    shape_columns = _SHAPES[table]

    def groups(d):
        t = pq.read_table(f"{d}/{file_name}")
        use = [c for c in values if c in t.column_names]
        g = collections.defaultdict(collections.Counter)
        for r in t.select(list(key) + use).to_pylist():
            row = tuple((c, tuple(r[c]) if isinstance(r[c], list) else r[c]) for c in use)
            g[tuple(r[c] for c in key)][row] += 1
        return g, use

    o, use_o = groups(old_dir)
    n, use_n = groups(new_dir)
    shared = {c for c in use_o if c in use_n}

    def project(counter):
        out, source = collections.Counter(), {}
        for v, c in counter.items():
            p = tuple((k, val) for k, val in v if k in shared)
            out[p] += c
            source.setdefault(p, v)
        return out, source

    def shape(v):
        d = dict(v)
        return tuple(d.get(c) for c in shape_columns)

    def stated(v):
        return {k: val for k, val in v if val is not None}

    van, arr = collections.Counter(), collections.Counter()
    vs, as_ = {}, {}
    for k in set(o) | set(n):
        po, from_o = project(o.get(k, collections.Counter()))
        pn, from_n = project(n.get(k, collections.Counter()))
        for v, c in (po - pn).items():
            van[shape(from_o[v])] += c
            vs.setdefault(shape(from_o[v]), (str(k[3])[:90], stated(from_o[v])))
        for v, c in (pn - po).items():
            arr[shape(from_n[v])] += c
            as_.setdefault(shape(from_n[v]), (str(k[3])[:90], stated(from_n[v])))

    rows_old = sum(sum(c.values()) for c in o.values())
    rows_new = sum(sum(c.values()) for c in n.values())
    lines = [
        f"rows old {rows_old:,} new {rows_new:,}",
        f"VANISHED values: {sum(van.values())}",
    ]
    lines += [f"   {c:6d} {s}   e.g. {vs[s][0]!r} {vs[s][1]}" for s, c in van.most_common()]
    lines.append(f"ARRIVED values: {sum(arr.values())}")
    lines += [f"   {c:6d} {s}   e.g. {as_[s][0]!r} {as_[s][1]}" for s, c in arr.most_common()]
    return lines


def _comparable(lines: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """Report lines with the frozen divergences -- and only those -- removed.

    The example is cut off after ``e.g.`` and each block's detail lines are
    sorted, which is exactly what ``_FROZEN_DIVERGENCES`` names. Counts,
    shapes, headline totals and the rows line all survive verbatim, so any
    other difference reaches the assertion. Lines the oracle never produced
    (the column-inventory lines finding 11 added) are dropped rather than
    compared against nothing.
    """

    header = [line for line in lines if line.startswith("rows old ")]
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        if line.startswith(("VANISHED values:", "ARRIVED values:")):
            current = line
            blocks[current] = []
        elif current is not None and line.startswith("   "):
            blocks[current].append(line.split("   e.g. ", 1)[0])
    return header, {name: sorted(rows) for name, rows in blocks.items()}


def _battery(tmp_path: Path, rows: int = 6000, per_column: int = 12) -> tuple[Path, Path]:
    """An old/new pair off the real artifact with scattered, typed mutations.

    One mutation family per Arrow type the schema uses -- string, int32, bool,
    list<string> -- so the digest encoding the rework leans on is exercised on
    each of them, and enough of them to produce many distinct report shapes
    with ties between some of their counts. Three of the families exist
    because a battery without them let a deliberately broken tool through:

    * ``None`` -> ``""`` and a value -> ``None``, because a digest encoding
      that dropped the null tag (conflating ``None`` with the empty string)
      passed every other case here;
    * a group whose rows are TRIPLED on the old side and single on the new,
      because the report charges a shape the whole outstanding multiplicity
      of a repeated value at once, and a battery where every difference has
      multiplicity 1 cannot tell that apart from charging 1.
    """

    import random

    rng = random.Random(20260831)
    sliced = _real_slice(rows)
    mutated = sliced
    for column, arrow_type, mutate in (
        ("stated_act_name", pa.string(), lambda v: (v or "") + " [moved]"),
        ("authority_type", pa.string(), lambda v: "mutated-type"),
        ("parse_status", pa.string(), lambda v: "mutated-status"),
        ("authority_source", pa.string(), lambda v: "mutated-source"),
        ("usc_title", pa.int32(), lambda v: (v or 0) + 7),
        ("cfr_title", pa.int32(), lambda v: (v or 0) + 3),
        ("superseded_by_join", pa.bool_(), lambda v: not v),
        ("usc_disposition_successors", pa.list_(pa.string()), lambda v: [*list(v or []), "mut"]),
        # Null boundaries, both directions.
        ("cfr_note_part", pa.string(), lambda v: "" if v is None else None),
        ("act_key", pa.string(), lambda v: None if v is None else ""),
    ):
        cells = mutated.column(column).to_pylist()
        for _ in range(per_column):
            index = rng.randrange(len(cells))
            cells[index] = mutate(cells[index])
        mutated = mutated.set_column(
            mutated.schema.get_field_index(column), column, pa.array(cells, type=arrow_type)
        )

    # Multiplicity: the same 30 rows three times on the old side, once on the
    # new, so those digests owe a charge of 2 rather than 1.
    repeated = sliced.slice(0, 30)
    return _pair(tmp_path, pa.concat_tables([sliced, repeated, repeated]), mutated)


@pytestmark_real_artifact
@pytest.mark.slow
def test_the_streaming_diff_agrees_with_the_pre_rework_oracle(tmp_path: Path, capsys) -> None:
    """Verdict agreement between the streaming rework and the core it replaced.

    Real data first (a slice diffed against itself: both must see nothing),
    then the mutation battery, because real data alone only proves the new
    core accepts what is unchanged -- what it REJECTS is unproven until
    something moves on purpose. The battery moves 120 cells across ten
    columns and four Arrow types, crosses the null boundary in both
    directions, and repeats a group so some differences carry a multiplicity
    above one.
    """

    quiet = _real_slice(4000)
    old_dir, new_dir = _pair(tmp_path / "quiet", quiet, quiet)
    main(str(old_dir), str(new_dir), "legal-authorities")
    assert _comparable(capsys.readouterr().out.splitlines()) == _comparable(
        _oracle_report(old_dir, new_dir, "legal-authorities")
    )

    old_dir, new_dir = _battery(tmp_path / "battery")
    main(str(old_dir), str(new_dir), "legal-authorities")
    tool = capsys.readouterr().out.splitlines()
    oracle = _oracle_report(old_dir, new_dir, "legal-authorities")
    assert _comparable(tool) == _comparable(oracle)

    # The battery has to have actually moved something, or the agreement above
    # is agreement about nothing -- and it has to have produced several shapes,
    # or the sorting in ``_comparable`` would be hiding an ordering bug rather
    # than the frozen tie-order divergence.
    _, blocks = _comparable(tool)
    assert len(blocks) == 2 and all(len(rows) >= 4 for rows in blocks.values())
    assert len(_FROZEN_DIVERGENCES) == 2

    # Pinned totals, so an undercount is a failure here and not just a
    # matching undercount in both implementations. 60 of the 168 vanished are
    # the tripled group: 30 digests the old side holds three times and the new
    # side once, each owing a charge of 2. A core that charged 1 per distinct
    # value instead of the outstanding multiplicity would report 138.
    assert "rows old 6,060 new 6,000" in tool
    assert "VANISHED values: 168" in tool
    assert "ARRIVED values: 108" in tool


@pytestmark_real_artifact
def test_the_report_does_not_depend_on_the_batch_size(tmp_path: Path, capsys, monkeypatch) -> None:
    """The streaming core reads in ``BATCH_ROWS``-row steps but compares whole
    rows against whole rows, so the step size must not be able to reach the
    answer. Run the same battery at a batch size that lands mid-group and at
    one larger than the whole fixture, and require the identical report --
    the check that would have caught a difference accumulated per batch
    rather than per row."""

    old_dir, new_dir = _battery(tmp_path / "battery", rows=1200, per_column=6)

    reports = []
    for batch in (7, 101, 100_000):
        monkeypatch.setattr(agenda_value_diff, "BATCH_ROWS", batch)
        main(str(old_dir), str(new_dir), "legal-authorities")
        reports.append(capsys.readouterr().out)

    assert reports[0] == reports[1] == reports[2]
    assert "VANISHED values: 0" not in reports[0]
