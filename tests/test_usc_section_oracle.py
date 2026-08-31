"""The U.S.C. section-existence oracle, and what it says about the pinned corpus.

Four kinds of test, deliberately.

**Pin tests** hold the six oracle tables and the agenda snapshot to the digests
their artifact README states, because every number below is a statement about
those exact bytes and a swapped directory must fail loudly rather than answer
differently.

**Specimen tests** run each predicate and each correction on the citations the
two reports name — *including the ones the reports say must NOT fire*, which
are the load-bearing half: ``5 USC 552(a)`` and ``5 USC 552a`` are both real,
``42 USC 2139(a)`` is an honest unknown, ``26 USC 6165`` is a real section
OLRC's Table III does not enumerate, and ``21 USC 134a to 134d`` were real
until 2002 with every citing row predating the repeal.

**Corpus tests** run the whole thing over
``agenda-legal-authorities-as-measured-797170.parquet`` — 797,170 rows, the
build the oracle report measured — and compare every count to the report's own
table. Where they differ the difference is asserted with its cause, because an
unexplained difference is the finding this suite exists to surface.

**Before/after tests** run the correction reader as it stood at ``da46f0de``
beside the one that replaced it on 2026-08-23, over all 38,218 triples of the
same build. The old reader is COPIED here (:func:`_head_correction_candidates`)
and never imported, per this repository's rule for replacing a running check.
A4 and B1 must not move by a single reading; every outcome that moved must be
the B8 population exactly; and the readings that did move are a frozen,
classified list (:data:`DELIBERATE_DIVERGENCES`), so an unlisted one fails here
instead of becoming a diff nobody reads.
"""

from __future__ import annotations

import collections
import hashlib
import inspect
import random
import re
import time
from functools import cache
from pathlib import Path

import pytest

from refspec.registry import citation_grammar
from refspec.registry.usc_section_oracle import (
    _DASHES,
    _ORACLE_PINS,
    ABSENT_CAVEATS,
    ACT_ASSOCIATIONS,
    APPENDIX_TITLES_PUBLISHED,
    CANDIDATE_ONLY_RULES,
    CORRECTION_RULES,
    MISS_CLASSES,
    ORACLE_ANNUAL_YEARS,
    ORACLE_WINDOW,
    UNKNOWN_REASONS,
    USC_SECTION_ORACLE_ARTIFACT,
    ActSectionClaim,
    Candidate,
    Correction,
    UscSectionOracle,
    _read_pinned_parquet,
    _section_key,
    _SpanIndex,
    normalize_section,
)

ROOT = Path(__file__).resolve().parents[1]
ORACLE_DIR = ROOT / USC_SECTION_ORACLE_ARTIFACT
#: The build every corpus count below was measured over. Its digest is stated
#: three times — here, in the artifact README's Files table, and in the build's
#: own ``receipt.json`` — and the report's numbers are only about these bytes.
SNAPSHOT = "agenda-legal-authorities-as-measured-797170.parquet"
SNAPSHOT_DIGEST = "sha256:c5c4bd1f8b70fd52491f8b22e7bc72c75287cbbf3638692210fd1691731c7424"


@cache
def oracle() -> UscSectionOracle:
    return UscSectionOracle.from_repository(ROOT)


@cache
def corpus() -> dict[str, object]:
    """The 685,431 parsed U.S.C. rows of the pinned build, aggregated once."""

    import pyarrow.parquet as pq

    path = ORACLE_DIR / SNAPSHOT
    digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    assert digest == SNAPSHOT_DIGEST, "the measured build is not the build on disk"
    table = pq.read_table(
        path,
        columns=[
            "rin",
            "publication_id",
            "authority_text",
            "authority_type",
            "parse_status",
            "usc_title",
            "usc_section",
            "usc_appendix",
            "usc_title_is_possible",
        ],
    )
    columns = {name: table.column(name).to_pylist() for name in table.schema.names}
    rows = [
        row
        for row in zip(*columns.values(), strict=True)
        if row[3] == "usc" and row[5] is not None and row[6] is not None
    ]
    keys = [(row[5], normalize_section(row[6]), bool(row[7])) for row in rows]

    pair_rows: collections.Counter = collections.Counter(keys)
    pair_ok: collections.Counter = collections.Counter()
    pair_texts: dict[tuple, set[str]] = collections.defaultdict(set)
    pair_rins: dict[tuple, set[str]] = collections.defaultdict(set)
    pair_text_rows: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    stated_impossible: set[tuple[int, str]] = set()
    for key, row in zip(keys, rows, strict=True):
        pair_texts[key].add(row[2])
        pair_rins[key].add(row[0])
        pair_text_rows[key][row[2]] += 1
        if row[4] == "ok":
            pair_ok[key] += 1
        if row[8] is False:
            stated_impossible.add((row[5], normalize_section(row[6])))
    return {
        "rows": rows,
        "keys": keys,
        "pair_rows": pair_rows,
        "pair_ok": pair_ok,
        "pair_texts": pair_texts,
        "pair_rins": pair_rins,
        "pair_text_rows": pair_text_rows,
        "stated_impossible": stated_impossible,
        "rin_states": {(row[0], row[5], normalize_section(row[6])) for row in rows},
        "triples": collections.Counter((row[5], normalize_section(row[6]), row[2]) for row in rows),
    }


@cache
def act_claims() -> dict[tuple[int, str, str], tuple[ActSectionClaim, ...]]:
    """What the builder's own association puts in front of each corpus triple.

    :class:`~refspec.registry.unified_agenda_parquet._ActNumbering` is
    IMPORTED, not copied. The association is a production decision -- which
    acts a row may be read against -- and a test-local copy would prove a
    different one; the thing this file copies instead is the correction reader
    under replacement, which is the opposite case.

    The rosters are rebuilt from the snapshot the way the builder builds them:
    every act key a row resolved BEFORE corroboration ran, at the RIN and at
    the agency. ``corroboration_rule is null`` is exactly the base pass, which
    is the builder's own rule for what fed those two dicts.

    What is kept is what the FENCE can use --
    :meth:`UscSectionOracle.act_numbering_fence`'s own answer, not the roster's
    raw one. That is not a shortcut: the roster answers 26,818 rows and the
    fence keeps 8, because on all the rest the token is a section the Code
    prints itself (``42 USC 216``, ``7 USC 6c``) and the fence is silent by
    construction. Keying by TRIPLE is sound only over the kept population,
    where no triple is filed by two agencies with different rosters -- asserted
    here, over the whole snapshot, rather than assumed. Over the raw roster it
    is NOT sound (``42 USC 216`` is filed by two agencies with two answers),
    which is why the builder keys its memo per row and this fixture says so.
    """

    import pyarrow.parquet as pq

    from refspec.registry.act_resolution import USC_ACT_INDEX_ARTIFACT, ActIndex
    from refspec.registry.unified_agenda_parquet import _ActNumbering

    table = pq.read_table(
        ORACLE_DIR / SNAPSHOT,
        columns=[
            "rin",
            "authority_text",
            "authority_type",
            "usc_title",
            "usc_section",
            "act_key",
            "corroboration_rule",
        ],
    )
    rows = table.to_pylist()
    keys_by_rin: dict[str, set[str]] = {}
    keys_by_agency: dict[str, set[str]] = {}
    for row in rows:
        if row["act_key"] and row["corroboration_rule"] is None:
            keys_by_rin.setdefault(row["rin"], set()).add(row["act_key"])
            keys_by_agency.setdefault(row["rin"][:4], set()).add(row["act_key"])
    numbering = _ActNumbering.build(ActIndex.from_artifact(ROOT / USC_ACT_INDEX_ARTIFACT), keys_by_rin, keys_by_agency)
    known = oracle()
    out: dict[tuple[int, str, str], tuple[ActSectionClaim, ...]] = {}
    for row in rows:
        if row["authority_type"] != "usc" or row["usc_title"] is None or row["usc_section"] is None:
            continue
        title, section = row["usc_title"], normalize_section(row["usc_section"])
        claims = known.act_numbering_fence(title, section, numbering.claims(row["rin"], title, section))
        if not claims:
            continue
        key = (title, section, row["authority_text"])
        assert out.setdefault(key, claims) == claims, f"two rosters answer one triple: {key}"
    return out


@cache
def misses() -> tuple[tuple, ...]:
    known = oracle()
    return tuple(key for key in corpus()["pair_rows"] if not known.section_exists(key[0], key[1], appendix=key[2]))


@cache
def triage() -> dict[tuple, object]:
    """Every miss, classified with the corpus context the report's script used."""

    known, data = oracle(), corpus()
    out = {}
    for key in misses():
        title, section, appendix = key
        joined = " || ".join(text for text, _n in data["pair_text_rows"][key].most_common())
        statements = {}
        for near in known.near_misses(title, section):
            hits = sum(1 for rin in data["pair_rins"][key] if (rin, near.title, near.section) in data["rin_states"])
            if hits:
                statements[(near.title, near.section)] = hits
        out[key] = known.classify_section_miss(
            title,
            section,
            appendix=appendix,
            authority_text=joined,
            same_rin_statements=statements,
            stated_title_possible=False if (title, section) in data["stated_impossible"] else None,
        )
    return out


# --------------------------------------------------------------------------- #
# The pins


def test_every_oracle_table_is_the_one_the_artifact_readme_states() -> None:
    """Six tables, six digests, restated from the README's Files table."""

    for name, pin in _ORACLE_PINS.items():
        digest = f"sha256:{hashlib.sha256((ORACLE_DIR / name).read_bytes()).hexdigest()}"
        assert digest == pin, name
    snapshot = f"sha256:{hashlib.sha256((ORACLE_DIR / SNAPSHOT).read_bytes()).hexdigest()}"
    assert snapshot == SNAPSHOT_DIGEST


def test_a_drifted_table_refuses_loudly_and_names_itself(tmp_path: Path) -> None:
    """A wrong directory must fail, not answer differently."""

    name = "usc-oracle-chapters.parquet"
    (tmp_path / name).write_bytes((ORACLE_DIR / name).read_bytes() + b"\0")
    with pytest.raises(ValueError, match=r"pinned U\.S\.C\. oracle drifted: usc-oracle-chapters\.parquet"):
        _read_pinned_parquet(tmp_path, name)
    # And the drift is not merely reported: nothing loads through it either.
    with pytest.raises(ValueError, match="drifted"):
        _ = UscSectionOracle(directory=tmp_path).chapters


def test_a_swapped_table_nobody_reads_still_refuses(tmp_path: Path) -> None:
    """All six are hashed at bind time, not the one the caller happens to want.

    The tables load lazily, one cached_property each, so a consumer asking only
    ``c7_chapter_as_section`` authenticated ``usc-oracle-chapters`` (11,713
    bytes) and answered from five tables nothing had looked at. Here the
    ANNUAL RANGES are swapped and the chapters are pristine, and the question
    asked is the one that reads chapters alone.
    """

    for name in _ORACLE_PINS:
        (tmp_path / name).write_bytes((ORACLE_DIR / name).read_bytes())
    untouched = "usc-oracle-annual-ranges.parquet"
    (tmp_path / untouched).write_bytes((ORACLE_DIR / untouched).read_bytes() + b"\0")

    with pytest.raises(ValueError, match=rf"drifted: {re.escape(untouched)}"):
        UscSectionOracle.from_directory(tmp_path)
    # The bare dataclass still answers from a table it never authenticated,
    # which is exactly the hole `verify` closes at the door.
    assert UscSectionOracle(directory=tmp_path).c7_chapter_as_section(10, "55")
    with pytest.raises(ValueError, match="drifted"):
        UscSectionOracle(directory=tmp_path).verify()
    # And the sealed copy this repository carries passes the whole six.
    UscSectionOracle.from_repository(ROOT).verify()


@pytest.mark.slow
def test_the_dash_table_is_the_grammars_verbatim() -> None:
    """The lesson that made this load-bearing is in the module docstring.

    OLRC spells the dash in ``/us/usc/t42/s1395w–4`` as U+2013 and the corpus
    uses ASCII hyphen; without this table the whole Medicare/ACA/SDWA
    compound-name family reads as nonexistent.
    """

    assert _DASHES == citation_grammar._DASHES
    for dash in "‐‑‒–—―−\x96\x97":
        assert normalize_section(f"1395W{dash}4") == "1395w-4"
    for title, section in ((42, "1395w-4"), (42, "300gg-11"), (42, "300j-9"), (21, "360bbb-3"), (42, "7671q")):
        assert oracle().section_verdict(title, section).exists, f"{title} U.S.C. {section}"


@pytest.mark.slow
def test_the_oracle_is_the_size_its_report_states() -> None:
    """A table that changed shape changes every count in this file."""

    known = oracle()
    assert len(known.release_point_sections) == 59_362
    statuses: collections.Counter = collections.Counter()
    for words in known.release_point_sections.values():
        statuses.update(words)
    assert statuses["current"] == 50_957
    assert sum(1 for words in known.release_point_sections.values() if "current" not in words) == 8_405
    assert sum(len(spans) for spans in known.release_point_ranges.values()) == 1_751
    assert len(known.annual_sections) == 67_022
    assert sum(1 for key in known.annual_sections if not key[1]) == 66_007
    assert sum(1 for key in known.annual_sections if key[1]) == 1_015
    assert sum(len(spans) for spans in known.annual_ranges.values()) == 49_823
    assert sum(len(subs) for subs in known.subsections.values()) == 160_209
    assert len(known.subsections) == 35_133, "sections with at least one subsection"
    assert len(known.chapters) == 2_905
    assert len({title for title, _chapter in known.chapters}) == 53
    assert len(known.enumerated) == 66_780, "the union that is the existence test"


# --------------------------------------------------------------------------- #
# Verdicts


@pytest.mark.slow
def test_the_verification_run_the_report_records() -> None:
    """The five probes and the one negative the oracle leg used to trust itself."""

    known = oracle()
    for title, section in ((15, "77aaaa"), (42, "7401"), (10, "128"), (54, "100101")):
        assert known.section_verdict(title, section).exists
    assert not any(title == 53 for title, _section in known.enumerated), "title 53 was never enacted"
    assert known.section_verdict(53, "1").verdict == "absent"


@pytest.mark.slow
def test_the_appendix_controls_and_the_one_year_that_moved() -> None:
    """Four appendix probes from the report, and a difference worth naming."""

    known = oracle()
    for title, section, span in (
        (50, "2401", (1994, 2014)),
        (50, "2410", (1994, 2014)),
        (46, "466c", (1994, 2005)),
        (46, "688", (1994, 2005)),
    ):
        verdict = known.section_verdict(title, section, appendix=True)
        assert verdict.exists, f"{title} App {section}"
        assert (verdict.attested_years[0], verdict.attested_years[-1]) == span

    # The report writes 5 App 3 and 5 App 8g as 1994-2020. The pinned annual
    # set carries them through 2021 — the Inspector General Act appendix
    # survived one more archive year than the report's prose says. One year,
    # both sections, and it changes no verdict.
    for section in ("3", "8g"):
        verdict = known.section_verdict(5, section, appendix=True)
        assert (verdict.attested_years[0], verdict.attested_years[-1]) == (1994, 2021)


@pytest.mark.slow
def test_where_the_oracle_cannot_speak_the_verdict_is_unknown_and_names_the_gap() -> None:
    """label never guess: a coverage hole is never published as an absence."""

    known = oracle()
    # C9: the pre-1996 Title 49 numbering. No usc49a.htm exists in any year.
    for section in ("1421", "1354", "1371", "1381", "1386", "1502"):
        verdict = known.section_verdict(49, section, 1996)
        assert verdict.verdict == "unknown"
        assert verdict.reason == "title_49_appendix_not_published"
        assert verdict.caveats == ()
    # C5: an appendix in a title no archive year publishes.
    assert known.section_verdict(49, "1804", 1999, appendix=True).reason == "title_49_appendix_not_published"
    for title, section in ((48, "1"), (42, "5195"), (15, "2401")):
        assert known.section_verdict(title, section, 2000, appendix=True).reason == "appendix_title_not_published"
    # C6: an appendix in a title the archives DO publish is a real absence.
    assert known.section_verdict(50, "24091", 2000, appendix=True).verdict == "absent"
    # Outside the window there is nothing to consult.
    for year in (1993, 2027):
        assert known.section_verdict(42, "7401", year).reason == "edition_outside_oracle_window"
    assert set(UNKNOWN_REASONS) >= {
        "title_49_appendix_not_published",
        "appendix_title_not_published",
        "edition_outside_oracle_window",
        "subsection_structure_not_published",
    }


# --------------------------------------------------------------------------- #
# The disposition table, beside the unknown it answers

#: The ten rows the human review of 2026-08-23 read against the publisher's own
#: pages (``research/evidence/sample-review-2026-08-23/review.md`` § F), as the
#: SECTION SLOT carries them — the filer's text, the section token the grammar
#: parsed out of it, the table's verdict and **every** successor in print
#: order. A pinpoint is not in this slot (row 2's ``(e)``, row 8's ``(c)``,
#: row 9's ``(h)``), so a whole-section query is what the oracle can ask, and
#: rows 3 and 4 open a range whose start is what ``usc_section`` holds.
REVIEW_F_THROUGH_THE_SECTION_SLOT = (
    (1, "49 USC 1432", "1432", "exists-as-recodified", ("44702", "44701", "44706", "44914")),
    (2, "49 USC 1652(e)", "1652", "exists-as-recodified", ("102", "106", "104", "103", "108")),
    (3, "49 USC 1421 to 1431", "1421", "exists-as-recodified",
     ("44701", "44702", "44712", "44714", "44716", "44717", "44722")),
    (4, "49 USC 1423 to 1426", "1423", "exists-as-recodified", ("44702", "44704")),
    (5, "49 USC 1502", "1502", "exists-as-recodified", ("40105", "40101")),
    (6, "49 USC 1424", "1424", "exists-as-recodified", ("44702", "44701", "44705")),
    (7, "49 USC 1421", "1421", "exists-as-recodified",
     ("44701", "44702", "44712", "44714", "44716", "44717", "44722")),
    (8, "49 USC 1374(c)", "1374", "exists-as-recodified",
     ("41702", "41501", "41310", "41705", "41706", "46301")),
    (9, "49 USC 1604(h)", "1604", "repealed-no-successor", ()),
    (10, "49 USC 1510", "1510", "exists-as-recodified", ("40120",)),
)


@pytest.mark.parametrize(("review_row", "filed", "section", "verdict", "successors"), REVIEW_F_THROUGH_THE_SECTION_SLOT)
@pytest.mark.slow
def test_the_disposition_stands_beside_the_verdict_and_never_instead_of_it(
    review_row: int, filed: str, section: str, verdict: str, successors: tuple[str, ...]
) -> None:
    """Ten rows the reviewer settled by hand, answered — and still ``unknown``.

    The verdict does not move and the reason does not move, because both are
    still true: no OLRC archive year publishes a Title 49 Appendix, and no
    rebuild of THIS oracle changes that. What moves is that the row now carries
    a second, different fact beside the first — what Pub. L. 103-272 did with
    the section in 1994 — from a source this oracle does not read.
    """

    answer = oracle().section_verdict(49, section, 2000)
    assert (answer.verdict, answer.reason) == ("unknown", "title_49_appendix_not_published"), filed
    assert answer.caveats == (), "an unknown is not an absence and carries no window caveat"
    assert answer.disposition is not None, filed
    assert answer.disposition.verdict == verdict, filed
    assert tuple(one.section for one in answer.disposition.successors) == successors, filed
    assert answer.disposition.recodification == "title-49-1994"
    # The disposition is the disposition OF THIS SECTION, and the dataclass
    # will not hold one of any other.
    assert (answer.disposition.former_title, answer.disposition.former_section) == (49, section)


@pytest.mark.slow
def test_the_disposition_names_every_successor_and_picks_none() -> None:
    """§ F row 1. ``1432`` is four sections, and the print is all that parts them.

    ``1432(a)`` alone is TWO — 44701 for the words about standards and 44702
    for the words about issuing certificates — printed in two rows whose only
    difference is the prose. A section slot cannot carry the pinpoint that
    would narrow even that far, so what the oracle attaches is every successor
    the table names, as candidates. Picking one would be the B8 mistake with a
    statute's authority behind it.
    """

    known = oracle()
    whole = known.section_verdict(49, "1432", 1996).disposition
    assert [(one.title, one.section) for one in whole.successors] == [
        (49, "44702"), (49, "44701"), (49, "44706"), (49, "44914")
    ]
    # The prose that separates them is kept verbatim beside them, and it is not
    # an address: nothing here parses it and nothing here should.
    printed = {(row.former_text, row.new_text) for row in whole.rows}
    assert ("1432(a) (related to standards)", "44701") in printed
    assert ("1432(a) (related to issuing certificates).", "44702") in printed
    # Narrowed to the subsection, the table still answers with BOTH, which is
    # the point: the pinpoint is not what tells them apart.
    narrowed = known.dispositions.disposition(49, "1432", "a")
    assert narrowed.subsection_resolved is True
    assert [(one.title, one.section) for one in narrowed.successors] == [(49, "44702"), (49, "44701")]
    # And where the print DOES decide, it decides: (d) is one section.
    assert [one.section for one in known.dispositions.disposition(49, "1432", "d").successors] == ["44914"]


@pytest.mark.slow
def test_a_repealed_former_section_is_a_verdict_and_never_an_absence() -> None:
    """§ F row 9. ``49 U.S.C. 1604(h)``, printed ``1604, 1604a … Rep.``

    Two facts that must not be confused. The oracle's own answer stays
    ``unknown``: the appendix is unpublished and 1604 is not confirmable from
    anything this oracle reads. The table's answer is ``repealed-no-successor``
    — the section is IN the table, printed beside its neighbour, and given no
    successor — which is a fact the oracle could not express in any of its
    three verdicts, and is why the disposition rides beside them rather than
    inside them. Nowhere in either is ``absent``.
    """

    known = oracle()
    answer = known.section_verdict(49, "1604", 2005)
    assert answer.verdict == "unknown" and answer.verdict != "absent"
    assert answer.reason == "title_49_appendix_not_published"
    assert answer.disposition.verdict == "repealed-no-successor"
    assert answer.disposition.successors == ()
    assert [(row.former_text, row.new_text) for row in answer.disposition.rows] == [("1604, 1604a", "Rep.")]
    # The subsection the filer wrote changes nothing: the printed row names no
    # subsection, so it speaks for the whole section and for (h) with it.
    assert known.dispositions.disposition(49, "1604", "h").verdict == "repealed-no-successor"


@pytest.mark.slow
def test_the_disposition_is_asked_of_the_table_and_of_nothing_else() -> None:
    """Bound without the tables, every verdict is the one it always was.

    The attachment is additive by construction, and this is what says so: the
    same oracle with ``dispositions=None`` answers identically on the verdict,
    the reason and the caveats, and attaches nothing.
    """

    from refspec.registry.usc_section_oracle import DISPOSITION_REASON

    bare = UscSectionOracle.from_directory(ORACLE_DIR)
    known = oracle()
    assert bare.dispositions is None and known.dispositions is not None
    for title, section, appendix in ((49, "1432", False), (49, "1804", True), (42, "7401", False), (21, "371a", False)):
        one = bare.section_verdict(title, section, 2000, appendix=appendix)
        two = known.section_verdict(title, section, 2000, appendix=appendix)
        assert one.disposition is None
        assert two.__dict__ | {"disposition": None} == one.__dict__, (title, section)
    assert DISPOSITION_REASON == "title_49_appendix_not_published"
    # And the memo is keyed by the section, not by the edition that cited it:
    # what Pub. L. 103-272 did in 1994 is not a fact about a 2011 filing.
    assert known.disposition(49, "1432") is known.section_verdict(49, "1432", 2011).disposition
    assert known.disposition(49, "1432") is known.section_verdict(49, "1432", 1995).disposition
    assert known.disposition(49, "1432", appendix=True) is known.section_verdict(49, "1432", 1995, appendix=True).disposition


@pytest.mark.slow
def test_a_disposition_cannot_be_attached_to_a_verdict_that_did_not_earn_one() -> None:
    """The invariant, tried three ways. Each must raise, not be published."""

    known = oracle()
    answer = known.section_verdict(49, "1432", 2000)
    other = known.disposition(49, "1510")
    kind = type(answer)
    # Beside a verdict that named a different hole.
    with pytest.raises(ValueError, match="a disposition stands only beside"):
        kind(**{**answer.__dict__, "reason": "appendix_title_not_published"})
    # Beside a verdict that named no hole at all -- the same guard, and the
    # one that matters most, because "exists" plus a successor is the shape a
    # consumer would read as a relocation of a live section.
    with pytest.raises(ValueError, match="not beside None"):
        kind(**{**answer.__dict__, "verdict": "exists", "reason": None})
    # And the disposition of some other section.
    with pytest.raises(ValueError, match="the disposition of that section"):
        kind(**{**answer.__dict__, "disposition": other})


@pytest.mark.slow
def test_c9_gains_the_dispositions_outcome_as_its_classification() -> None:
    """The one class that detected a family and could say nothing about a member.

    "no OLRC archive year carries a Title 49 Appendix" is a fact about the
    SOURCES, and a triage reader got the identical sentence for a section
    restated at 49 U.S.C. 40120 and one repealed outright. The class code does
    not move — the coverage hole has not — and the classification now names
    what became of the section.
    """

    known = oracle()
    one = known.classify_section_miss(49, "1510")
    assert one.name == "C9 title-49-pre-1996"
    assert one.proposal == "49 USC 40120", "one successor, so the class may name it"
    assert "restates it as 49 U.S.C. 40120 (Pub. L. 103-272, § 6(b))" in one.why
    assert one.disposition.verdict == "exists-as-recodified"

    several = known.classify_section_miss(49, "1432")
    assert several.proposal is None, "four successors: candidates, never an identity"
    assert "names 4 successors separated only by printed prose" in several.why
    assert len(several.disposition.successors) == 4
    # The successors are NOT folded into `candidates`, which holds sections a
    # named EDIT away in the current Code. A typo and a statute are not one
    # kind of thing, and a consumer must not be able to rank them together.
    assert several.candidates == ()

    gone = known.classify_section_miss(49, "1726")
    assert gone.proposal is None and "repeals it and names no successor" in gone.why

    missing = known.classify_section_miss(49, "1509d")
    assert missing.proposal is None
    assert "does not list it (repealed_before_the_recodification_not_listed)" in missing.why
    assert missing.disposition.verdict == "not-in-table"
    # An oracle with no tables bound classifies exactly as C9 always did.
    assert UscSectionOracle.from_directory(ORACLE_DIR).classify_section_miss(49, "1510") == type(one)(
        "C9", "title-49-pre-1996", None, "no OLRC archive year carries a Title 49 Appendix"
    )


@pytest.mark.slow
def test_the_disposition_over_the_corpus_and_the_hold_out_that_stays_unknown() -> None:
    """2,548 rows asked, 2,371 answered, 177 held out — and all 2,548 unknown.

    The hold-out is the load-bearing half. Those 177 rows are damage in the
    citation and not a gap in the table (14 CFR chapter III part numbers in the
    U.S.C. slot, a Privacy Act citation under the wrong title, two descending
    ranges, a Statutes page), and every one of them keeps the verdict and the
    reason it had before this table existed: ``not-in-table`` is the TABLE's
    answer and never the oracle's.
    """

    known, data = oracle(), corpus()
    rows: collections.Counter = collections.Counter()
    pairs: dict[str, set[tuple]] = collections.defaultdict(set)
    for key in misses():
        verdict = known.section_verdict(key[0], key[1], appendix=key[2])
        if verdict.reason != "title_49_appendix_not_published":
            continue
        assert verdict.verdict == "unknown" and verdict.caveats == ()
        rows[verdict.disposition.verdict] += data["pair_rows"][key]
        pairs[verdict.disposition.verdict].add(key)
    assert dict(rows) == {"exists-as-recodified": 2_237, "not-in-table": 177, "repealed-no-successor": 134}
    assert {name: len(group) for name, group in pairs.items()} == {
        "exists-as-recodified": 115, "not-in-table": 27, "repealed-no-successor": 19
    }
    # The census closes against the reason code exactly: every row the oracle
    # refuses for this one hole is a row the table was asked about, and the
    # answered count is the review's own 93.1%.
    assert sum(rows.values()) == 2_548
    assert sum(count for name, count in rows.items() if name != "not-in-table") == 2_371
    assert sum(len(group) for group in pairs.values()) == 161
    assert len({key[1] for group in pairs.values() for key in group}) == 146
    # A held-out section carries the table's own statement of how wide its
    # absence is, so nobody reads "not in the table" as "never existed": the
    # table lists what existed to be restated in 1994, and a section repealed
    # before that was never in it.
    held = known.section_verdict(49, "1509d").disposition
    assert held.verdict == "not-in-table"
    assert held.caveats == ("repealed_before_the_recodification_not_listed",)
    assert held.successors == () and held.rows == ()


@pytest.mark.slow
def test_an_absence_always_carries_the_window_it_speaks_for() -> None:
    """``absent`` means "in no edition 1994-2026", never "never existed"."""

    known = oracle()
    absent = known.section_verdict(21, "371a", 2010)
    assert absent.verdict == "absent"
    assert absent.caveats == ABSENT_CAVEATS == ("repealed_before_1994_not_stubbed",)
    assert ORACLE_WINDOW == (1994, 2026)

    # 18 U.S.C. 3568 is the specimen the gap is named for: a real section
    # repealed effective 1987-11-01, still cited deliberately for pre-1987
    # conduct, and invisible to an oracle whose window opens in 1994.
    stale = known.section_verdict(18, "3568", 2025)
    assert stale.verdict == "absent"
    assert stale.attested_years == ()
    assert stale.caveats == ABSENT_CAVEATS
    data = corpus()
    key = (18, "3568", False)
    assert data["pair_rows"][key] == 182
    assert len(data["pair_rins"][key]) == 14

    # And the dataclass will not let a caller drop it.
    with pytest.raises(ValueError, match="only as wide as the oracle's window"):
        type(absent)(**{**absent.__dict__, "caveats": ()})


@pytest.mark.slow
def test_the_edition_year_narrows_but_never_accuses() -> None:
    """A citation is judged against the Code of its own edition, one way only."""

    known = oracle()
    # The report's own must-not-fire: real animal-quarantine sections until
    # their 2002 repeal, and every citing row predates it.
    for section in ("134a", "134b", "134c", "134d"):
        for year in (1996, 2001):
            verdict = known.section_verdict(21, section, year)
            assert verdict.exists and verdict.attested_at_edition is True, f"{section}@{year}"
    assert ORACLE_ANNUAL_YEARS == (1994, 2024)
    # 2025 and 2026 have no annual archive, so the release point answers.
    modern = known.section_verdict(42, "7401", 2025)
    assert modern.exists and modern.attested_at_edition is True
    assert "release-point" in modern.evidence


@pytest.mark.slow
def test_a_section_table_iii_does_not_enumerate_is_still_real() -> None:
    """Two claims the campaign had to withdraw, now settled by the oracle."""

    known = oracle()
    # The campaign's own rejected candidates: a real section Table III does not
    # enumerate, and sections real until a 2002 repeal.
    assert known.section_verdict(26, "6165").exists
    assert known.section_verdict(54, "100101").exists
    # The lost-hyphen trap: citation_grammar refuses to adjudicate against an
    # ACT INDEX, which is a roster of what named acts contributed and says
    # nothing about the rest of the Code. The whole-Code oracle holds both.
    assert known.section_verdict(15, "80b-11").exists
    assert known.section_verdict(15, "80b-1").exists


@pytest.mark.slow
def test_the_prose_about_the_act_index_is_about_the_act_index_in_force() -> None:
    """The argument is about what an act index IS; the worked example expired.

    Until ``e8b4c2c1`` the default act index was the 24-act per-page build, and
    this module's evidence line said the recovered section was one "the 24-act
    index lacks". The default is now the bulk build, which holds 15 U.S.C.
    80b-11, 80b-1 AND 7 U.S.C. 6b-1 — so the comparison is gone from the
    evidence and the prose, and the conclusion (a roster of acts is not a
    roster of the Code, at any size) is what remains. This test fails when the
    default moves again, so the prose is re-read rather than silently outlived.
    """

    import pyarrow.parquet as pq

    from refspec.registry import act_resolution

    assert act_resolution.USC_ACT_INDEX_ARTIFACT == "output/usc-act-index-2026-08-22"
    index = pq.read_table(
        ROOT / act_resolution.USC_ACT_INDEX_ARTIFACT / "usc-act-sections.parquet",
        columns=["usc_title", "usc_section"],
    )
    pairs = set(zip(index.column("usc_title").to_pylist(), index.column("usc_section").to_pylist(), strict=True))
    assert index.num_rows == 302_156
    for title, section in (("15", "80b-11"), ("15", "80b-1"), ("7", "6b-1")):
        assert (title, section) in pairs, f"{title} U.S.C. {section}"
    # So no evidence line may claim the index lacks what the oracle prints.
    recovered = oracle().recovered_lost_hyphen_sections(15, "15 USC 80b-4, 80bll(a)")
    assert "index" not in recovered[0].evidence
    assert "which the pinned OLRC oracle enumerates" in recovered[0].evidence


@pytest.mark.slow
def test_the_subsection_oracle_says_when_it_cannot_see() -> None:
    """Gap three: release point, non-appendix, and never a stub."""

    known = oracle()
    # 16 U.S.C. 462 is stubbed (its provisions moved to title 54 in 2014), so
    # whether it ever had a subsection (k) is unknown here -- and 49 rows cite
    # "16 USC 462k".
    unseen = known.subsection_verdict(16, "462", "k")
    assert unseen.verdict == "unknown"
    assert unseen.reason == "subsection_structure_not_published"
    assert all("current" not in words for words in [known.release_point_sections[(16, "462")]])
    # No stub anywhere carries subsection rows, which is why the stub rule is a
    # rule and not a guess.
    stubs = {key for key, words in known.release_point_sections.items() if "current" not in words}
    assert len(stubs) == 8_405
    assert not any(key in known.subsections for key in stubs)
    # A live section with no lettered subsection at all: class B8's whole case.
    silent = known.subsection_verdict(42, "1395", "hh")
    assert silent.verdict == "absent" and silent.lettered == ()
    assert known.subsection_verdict(42, "629", "b").lettered == (), "only unlettered paragraphs (1)-(4)"
    assert len(known.subsections[(42, "629")]) == 4
    # And a live section that really does carry the letter.
    assert known.subsection_verdict(5, "552", "a").verdict == "exists"
    assert known.subsection_verdict(42, "2139", "a").verdict == "exists"


# --------------------------------------------------------------------------- #
# The predicates, on the reports' own specimens


@pytest.mark.slow
def test_c0_title_impossible_and_the_edition_dated_column_that_outranks_it() -> None:
    known = oracle()
    for title in (61, 410, 347, 166, 72, 53):
        assert known.c0_title_impossible(title), title
    for title in (1, 42, 52, 54):
        assert not known.c0_title_impossible(title), title
    # The builder's column is EDITION-DATED ("had this title been created
    # yet?"); this function is not. Measured over the pinned build the two
    # disagree on exactly two pairs, both titles enacted in 2014.
    assert known.c0_title_impossible(52, stated_possible=False)
    assert known.c0_title_impossible(54, stated_possible=False)
    stated = corpus()["stated_impossible"]
    assert {pair for pair in stated if citation_grammar.usc_title_is_possible(pair[0])} == {
        (52, "7602"),
        (54, "4118"),
    }


@pytest.mark.slow
def test_c1_zero_padded() -> None:
    known = oracle()
    for section in ("0956", "0367", "0864", "0901", "0904"):
        assert known.c1_zero_padded(26, section), section
    assert not known.c1_zero_padded(26, "956"), "an unpadded section is not the class"


@pytest.mark.slow
def test_c2_subsection_as_section_and_the_two_it_must_not_touch() -> None:
    known = oracle()
    for title, section in ((21, "321p"), (21, "371a"), (21, "361a"), (12, "1828o"), (42, "7414a")):
        assert known.c2_subsection_as_section(title, section), f"{title} {section}"
    # 21 U.S.C. 360b is real and 321p is not, and nothing in the characters
    # separates them -- the oracle is what makes it decidable.
    assert not known.c2_subsection_as_section(21, "360b")
    # And the Privacy Act: a real stem, a real subsection (a), AND a real
    # lettered section. Without the "not itself a section" clause this class
    # would swallow it.
    assert not known.c2_subsection_as_section(5, "552a")
    assert not known.c2_subsection_as_section(42, "2139a")


@pytest.mark.slow
def test_c3_paren_suffix_eaten() -> None:
    """One parenthesised suffix, one section named, one proposal."""

    known = oracle()
    for title, section, text, target in (
        (15, "78", "15 USC 78(a)", "78a"),
        (42, "2000", "42 U.S.C. 2000(d)", "2000d"),
        (19, "81", "19 U.S.C. 81(c)", "81c"),
    ):
        assert [one.section for one in known.c3_proposals(title, section, text)] == [target]
        miss = known.classify_section_miss(title, section, authority_text=text)
        assert (miss.code, miss.proposal) == ("C3", f"{title} USC {target}")
    assert known.c3_proposals(21, "321", "21 USC 321(p)") == (), "321 is a real section"

    # 15 U.S.C. 80a is not a section and 80a-1 … 80a-64 are. The text states
    # WHICH one, and that outranks the family: reading 80a-1 out of "80(a)-23"
    # was the family fallback answering a question the text had already
    # answered.
    assert [one.section for one in known.c3_proposals(15, "80", "15 U.S.C. 80(a)-23")] == ["80a-23"]
    assert known.section_verdict(15, "80a-23").exists
    # Drop the stated tail and the family has 65 members, so the class detects
    # and proposes nothing rather than picking the lowest-numbered one.
    family = known.c3_proposals(15, "80", "15 U.S.C. 80(a) et seq")
    assert len(family) == 65 == len(known.hyphen_children[(15, "80a")])
    assert {kind for one in family for kind in one.kinds} == {"compound-name-family"}
    assert known.classify_section_miss(15, "80", authority_text="15 U.S.C. 80(a) et seq").proposal is None


@pytest.mark.slow
def test_c3_refuses_by_count_where_the_text_parenthesises_several_suffixes() -> None:
    """303 of C3's 343 rows name more than one section, and no order picks.

    The parenthesis is gone from the parse, so the text is the only witness to
    which suffix it held — and three of the four pairs witness several. Walking
    ``_SUFFIXES`` alphabetically published "15 USC 78a" for all 245 rows of a
    pair whose texts name eighteen sections.
    """

    known, data, classified = oracle(), corpus(), triage()
    measured = {
        key: (miss.proposal, len(miss.candidates), data["pair_rows"][key])
        for key, miss in classified.items()
        if miss.code == "C3"
    }
    assert measured == {
        (15, "78", False): (None, 18, 245),
        (42, "2000", False): (None, 2, 49),
        (19, "81", False): (None, 3, 9),
        (15, "80", False): ("15 USC 80a-23", 1, 40),
    }
    assert sum(rows for proposal, _n, rows in measured.values() if proposal is None) == 303
    assert sum(rows for _p, _n, rows in measured.values()) == 343

    # The eighteen, named. Every one is a real section of title 15 and every
    # one is parenthesised somewhere in the pair's 57 authority texts.
    joined = " || ".join(
        text for text, _n in data["pair_text_rows"][(15, "78", False)].most_common()
    )
    assert len(data["pair_text_rows"][(15, "78", False)]) == 57
    assert [one.section for one in known.c3_proposals(15, "78", joined)] == [
        "78a", "78b", "78c", "78g", "78h", "78i", "78j", "78l", "78m",
        "78n", "78o", "78p", "78q", "78s", "78w", "78x", "78ll", "78mm",
    ]
    assert [one.section for one in classified[(42, "2000", False)].candidates] == ["2000d", "2000e"]
    assert [one.section for one in classified[(19, "81", False)].candidates] == ["81a", "81c", "81u"]
    # The count is what the refusal publishes, in the same shape C8 uses.
    assert "18 sections are named 78 plus a suffix" in classified[(15, "78", False)].why


@pytest.mark.slow
def test_c4_fires_on_nothing_here_and_would_fire_on_the_defect_it_names() -> None:
    """The date-year phantom, fixed at ``f05791de`` and gone from this build."""

    known = oracle()
    phantom = (
        "18 USC 3621, 3622, 3624, 4001, 4042, 4081, 4082 "
        "(Repealed in part as to offenses committed on or after November 1, 1987)"
    )
    assert known.c4_date_year_as_section("1987", phantom)
    assert not known.c4_date_year_as_section("1987", "18 USC 1987")
    assert not any(miss.code == "C4" for miss in triage().values()), "the class is gone from the artifact"


@pytest.mark.slow
def test_c5_and_c6_split_the_appendix_by_what_was_published() -> None:
    known = oracle()
    assert APPENDIX_TITLES_PUBLISHED == frozenset({5, 10, 11, 18, 26, 28, 38, 40, 46, 50})
    assert known.c5_appendix_out_of_oracle(49, appendix=True)
    assert known.c5_appendix_out_of_oracle(48, appendix=True)
    assert known.c6_appendix_miss(50, appendix=True)
    assert not known.c5_appendix_out_of_oracle(50, appendix=True)
    assert not known.c6_appendix_miss(50, appendix=False), "a non-appendix citation is neither"


@pytest.mark.slow
def test_c7_chapter_as_section() -> None:
    known = oracle()
    for title, section in ((10, "55"), (46, "701"), (5, "89"), (41, "85"), (49, "401"), (49, "1")):
        assert known.c7_chapter_as_section(title, section), f"{title} {section}"
    assert not known.c7_chapter_as_section(42, "7401"), "a real section is not a chapter reading"


@pytest.mark.slow
def test_c8_and_c8b() -> None:
    known = oracle()
    assert known.hyphen_children[(15, "80a")][0] == "80a-1", "the Investment Company Act opens at 80a-1"
    assert known.hyphen_children[(42, "300aa")][0] == "300aa-1", "the Vaccine Act opens at 300aa-1"
    assert known.c8_hyphen_part_dropped(15, "80b")
    assert known.c8b_proposal(15, "780-10") == "78o-10"
    assert known.c8b_proposal(15, "780-5") == "78o-5"
    assert known.c8b_proposal(16, "8240") == "824o"
    assert known.c8b_proposal(15, "16930") == "1693o"


@pytest.mark.slow
def test_c8c_and_c8d_wear_one_shape_and_two_mechanisms() -> None:
    """A kept-whole pair is an inversion or an abbreviation, and never both.

    Both reach the section-identity column through the same fail-closed
    branch — the second number sorts below the first, so the ordering rule
    declines and the token stays one NAME. Underneath they are different
    defects: "2032-1" is a 26 CFR reg number and no reading as a span exists,
    while "2671-80" is §§2671-2680 with its repeated leading digits dropped.
    HEAD's grammar reads the second kind as a range, so undivided the class
    would fall from 113 pairs to 49 on the next rebuild and keep its name.
    """

    known = oracle()
    for section in ("2032-1", "460-6", "472-8", "436-1", "472-1"):
        assert known.c8c_inverted_range_kept_whole(26, section), section
        assert not known.c8d_abbreviated_span_kept_whole(26, section), section
    assert known.c8c_inverted_range_kept_whole(50, "4801-4582"), "a pair that repeats nothing abbreviates nothing"
    assert not known.c8c_inverted_range_kept_whole(42, "1395w-4"), "a compound NAME is not an inverted range"

    for title, section, span in (
        (28, "2671-80", ("2671", "2680")),
        (31, "3801-12", ("3801", "3812")),
        (12, "1784-86", ("1784", "1786")),
        (5, "571-83", ("571", "583")),
        (7, "1373-74", ("1373", "1374")),
        (12, "1781-90", ("1781", "1790")),
    ):
        assert known.c8d_abbreviated_span_kept_whole(title, section), section
        assert not known.c8c_inverted_range_kept_whole(title, section), section
        # The class defers to the grammar rather than restating it, so it means
        # exactly what the grammar reads -- and says so in the proposal.
        assert citation_grammar._abbreviated_span(section) == span
        miss = known.classify_section_miss(title, section)
        assert (miss.code, miss.proposal) == ("C8d", f"{title} USC {span[0]} to {span[1]}")

    # Over the pinned snapshot: one shape, partitioned with nothing left over.
    data = corpus()
    shape = [key for key in misses() if known._kept_whole_pair(key[0], key[1])]
    inverted = [key for key in shape if known.c8c_inverted_range_kept_whole(key[0], key[1])]
    abbreviated = [key for key in shape if known.c8d_abbreviated_span_kept_whole(key[0], key[1])]
    assert (len(shape), sum(data["pair_rows"][key] for key in shape)) == (113, 682)
    assert (len(inverted), sum(data["pair_rows"][key] for key in inverted)) == (49, 426)
    assert (len(abbreviated), sum(data["pair_rows"][key] for key in abbreviated)) == (64, 256)
    assert set(inverted) & set(abbreviated) == set()
    assert set(inverted) | set(abbreviated) == set(shape)


@pytest.mark.slow
def test_c9_is_a_shape_and_the_verdict_still_answers_first() -> None:
    known = oracle()
    for section in ("1421", "1354", "1371", "1381", "1386", "1502"):
        assert known.c9_title_49_pre_1996(49, section), section
    assert not known.c9_title_49_pre_1996(49, "40113"), "the recodified numbering is outside the shape"
    assert not known.c9_title_49_pre_1996(42, "1354"), "only title 49"
    # The shape fires on 49 U.S.C. 106 too -- and it does not matter, because
    # every predicate here presumes a MISS and 106 is a real section.
    assert known.c9_title_49_pre_1996(49, "106")
    assert known.section_verdict(49, "106", 2020).exists


@pytest.mark.slow
def test_c10_is_a_lead_and_the_report_says_why() -> None:
    """``21 USC 360gg`` has exactly one neighbour, and it is the wrong answer."""

    known = oracle()
    near = known.near_misses(21, "360gg")
    assert len(near) == 1 and near[0].section == "360"
    assert known.classify_section_miss(21, "360gg").proposal == "21 USC 360"
    # Verified at the publisher: the radiation-control subchapter opens at
    # 360hh, which the generator's single edit cannot reach.
    assert not known.section_verdict(21, "360gg").exists
    assert known.section_verdict(21, "360hh").exists


def test_every_triage_predicate_is_reachable_from_the_classifier() -> None:
    """A predicate the classifier does not call is a second opinion nobody asks for.

    ``c3_paren_suffix_eaten``, ``c8b_letter_o_as_zero`` and ``c12_unresolved``
    each had no caller anywhere in ``src`` or ``tests`` while
    :meth:`classify_section_miss` restated their conditions inline, so an edit
    to one of them changed no count and nothing said so. Both directions are
    held here: every ``cN_`` predicate the module defines is called by the
    classifier, and every class the table declares is one the classifier can
    return.
    """

    source = inspect.getsource(UscSectionOracle.classify_section_miss)
    # A class whose CONSTRUCTION the classifier delegates is still the
    # classifier's -- C9 builds its MissClass in ``_c9_class`` so the
    # disposition table's four outcomes do not swell the precedence chain.
    # The helpers are gathered from the source rather than listed, or this
    # check goes blind the next time a branch moves out of the chain.
    called = sorted(
        name
        for name in set(re.findall(r"self\.(\w+)\(", source))
        if inspect.isfunction(getattr(UscSectionOracle, name, None))
    )
    assert "_c9_class" in called
    source += "".join(inspect.getsource(getattr(UscSectionOracle, name)) for name in called)
    predicates = {name for name in dir(UscSectionOracle) if re.fullmatch(r"c\d+[a-z]?_\w+", name)}
    assert len(predicates) >= 12, "the cN_ naming convention moved and this check went blind"
    assert {name for name in predicates if f"self.{name}(" not in source} == set()

    declared = {name.split(" ", 1)[0] for name in MISS_CLASSES}
    returned = set(re.findall(r'MissClass\(\s*\n?\s*"([^"]+)"', source))
    assert returned == declared, "the table and the classifier name the same classes"
    # C12 is the only class with no predicate of its own, because "detected,
    # unexplained" IS the fallthrough past C10 and C11.
    assert not any(name.startswith("c12_") for name in predicates)


@pytest.mark.slow
def test_the_precedence_is_the_reports_order() -> None:
    known = oracle()
    assert [name.split(" ", 1)[0] for name in MISS_CLASSES] == [
        "C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C8b", "C8c", "C8d", "C9", "C10", "C11", "C12",
    ]
    seen = {miss.name for miss in triage().values()}
    assert seen <= set(MISS_CLASSES)
    # A pair that satisfies two predicates takes the earlier one: 49 U.S.C. 401
    # is both a chapter number (C7) and pre-1996 title 49 shape (C9).
    assert known.c7_chapter_as_section(49, "401") and known.c9_title_49_pre_1996(49, "401")
    assert known.classify_section_miss(49, "401").code == "C7"


# --------------------------------------------------------------------------- #
# Corrections: exactly one survivor, or nothing


@pytest.mark.slow
def test_a4_a_subsection_rendered_as_a_lettered_section() -> None:
    known = oracle()
    fix = known.corrected_section(21, "371a", "21 USC 371a", 2010)
    assert fix is not None
    assert (fix.rule, fix.section, fix.subsection) == ("A4-subsection-rendered-as-a-lettered-section", "371", "a")
    assert fix.original_section == "371a", "a correction keeps what it replaces"
    assert "371" in fix.evidence and "(a)" in fix.evidence
    assert known.corrected_section(21, "321p", "21 USC 321p", 2010).section == "321"


@pytest.mark.slow
def test_a4_refuses_by_name_where_two_readings_survive() -> None:
    """``5 USC 552a`` is the Privacy Act AND 5 U.S.C. 552 has a subsection (a)."""

    known = oracle()
    for title, section, text in ((5, "552a", "5 USC 552a"), (42, "2139a", "42 USC 2139a")):
        candidates = known.correction_candidates(title, section, text)
        assert {candidate.rule for candidate in candidates} == {
            "parse-as-filed",
            "A4-subsection-rendered-as-a-lettered-section",
        }
        assert len({candidate.target for candidate in candidates}) == 2, "two survivors"
        assert known.corrected_section(title, section, text) is None


#: The Commodity Exchange Act's own section numbering, as OLRC's pinned act
#: index classifies it, spelled here the way the builder's ``_ActNumbering``
#: hands it to the oracle. ``1922:369`` IS the credit's "Sept. 21, 1922,
#: ch. 369"; ``association`` is the level of the CFTC's own roster that held
#: the act (agency: RIN 3038-AD31's own boxes name no act at all).
_CEA_8A = ActSectionClaim(
    act="commodity exchange act",
    act_key="1922:369",
    act_section="8a",
    title=7,
    section="12a",
    association="agency",
)
#: The second act that numbers a §8a into title 7, and the whole reason the
#: association is fenced to the filing agency. Real, and in the same pinned
#: index: A.A.A. Farm Relief and Inflation Act §8a is 7 U.S.C. 608a.
_AAA_8A = ActSectionClaim(
    act="a.a.a. farm relief and inflation act",
    act_key="1933:25",
    act_section="8a",
    title=7,
    section="608a",
    association="agency",
)
#: 7 U.S.C. 12a's printed source credit, verbatim from uscode.house.gov
#: (fetched 2026-08-24, granuleid USC-prelim-title7-section12a). This one
#: string is the whole witness: the Act's §8a and the Code's §12a are the same
#: text, so a filer writing "8a" under a "7 USC" label is writing the Act's
#: number.
_USC_7_12A_SOURCE_CREDIT = (
    "(Sept. 21, 1922, ch. 369, §8a, as added June 15, 1936, ch. 545, §10, 49 Stat. 1500 ; "
    "amended Aug. 5, 1955, ch. 574, 69 Stat. 535 ; ...)"
)


@pytest.mark.slow
def test_a4_is_fenced_where_the_act_numbers_the_token_itself() -> None:
    """``7 USC 8a(5)`` is Commodity Exchange Act §8a(5) — 7 U.S.C. 12a(5).

    The exact two filer texts of the eight rows visual review #2 found wrong
    (``research/evidence/review2-2026-08-23/notes/H.json``, row 18): RIN
    3038-AD31 wrote "7 USC 8a(5)" in five editions and RIN 3038-AB50 wrote
    "7 USC 8a" in three, and every one of them was published as 7 U.S.C. 8(a).

    A4's structural test is TRUE on all eight — 7 U.S.C. 8 is a real section
    and does carry a subsection (a) — which is why no existence check could
    see it happen. What separates them is the Code's own source credit for
    §12a, quoted here verbatim.
    """

    known = oracle()
    assert "§8a" in _USC_7_12A_SOURCE_CREDIT and "ch. 369" in _USC_7_12A_SOURCE_CREDIT
    assert known.section_exists(7, "8") and known.subsection_verdict(7, "8", "a").verdict == "exists", (
        "A4 was structurally right and referentially wrong: that is the whole finding"
    )
    assert not known.section_exists(7, "8a"), "and the token the filer wrote is no section of the Code"

    for text, pinpoint, spelled in (("7 USC 8a(5)", "5", "12a(5)"), ("7 USC 8a", None, "12a")):
        fix = known.corrected_section(7, "8a", text, 2011, (_CEA_8A,))
        assert fix is not None, text
        assert (fix.rule, fix.section, fix.subsection) == ("act-section-under-a-usc-label", "12a", pinpoint)
        assert fix.original_section == "8a", "a correction keeps what it replaces"
        assert fix.section + (f"({fix.subsection})" if fix.subsection else "") == spelled
        assert "1922:369" in fix.evidence and "commodity exchange act" in fix.evidence
        assert "agency roster" in fix.evidence

        # A4's reading is not deleted. It is named, and struck, and says by
        # what -- the B8 posture, reached inside A4's own rule.
        candidates = known.correction_candidates(7, "8a", text, 2011, (_CEA_8A,))
        struck = [one for one in candidates if one.fenced_by is not None]
        assert [one.rule for one in struck] == ["A4-subsection-rendered-as-a-lettered-section"]
        assert (struck[0].section, struck[0].subsection) == ("8", "a")
        assert struck[0].corrects is False, "a struck reading never publishes, whatever its rule"
        assert "1922:369" in struck[0].fenced_by and "7 U.S.C. 12a" in struck[0].fenced_by

    # And with no roster in front of it the module is unchanged: the fence is
    # the caller's association, and an empty one is a silence, not a licence.
    unfenced = known.corrected_section(7, "8a", "7 USC 8a(5)", 2011)
    assert (unfenced.rule, unfenced.section, unfenced.subsection) == (
        "A4-subsection-rendered-as-a-lettered-section",
        "8",
        "a",
    )


@pytest.mark.slow
def test_the_act_numbering_fence_refuses_where_two_acts_claim_the_token() -> None:
    """Two credits, no identity — and the measured cost of a corpus-wide roster.

    Both claims are real and both are in the pinned index. A CFTC row sees only
    the first because :data:`ACT_ASSOCIATIONS` fences the roster to the filing
    agency; a reader that skipped the fence would see both, and this is what
    that reader gets: candidates, named, and nothing published.
    """

    known = oracle()
    candidates = known.correction_candidates(7, "8a", "7 USC 8a(5)", 2011, (_CEA_8A, _AAA_8A))
    readings = {(one.rule, one.section, one.subsection) for one in candidates if one.fenced_by is None}
    assert readings == {
        ("act-section-under-a-usc-label", "12a", "5"),
        ("act-section-under-a-usc-label", "608a", "5"),
    }
    assert known.corrected_section(7, "8a", "7 USC 8a(5)", 2011, (_CEA_8A, _AAA_8A)) is None
    # A4 stays struck either way: two act readings do not restore the lost
    # parenthesis, they only mean the module cannot say which act.
    assert all(
        one.fenced_by is not None
        for one in candidates
        if one.rule == "A4-subsection-rendered-as-a-lettered-section"
    )
    assert known.section_is_enumerated(7, "608a"), "the rival is a real section, which is why it refuses"


@pytest.mark.slow
def test_the_act_numbering_fence_is_silent_on_the_families_it_must_not_touch() -> None:
    """The FDA family, ``7 USC 12g``, and a token the Code prints itself.

    Three different silences, three different reasons, and each is a row that
    must NOT move:

    * **21 USC 321p / 371a (3,349 rows).** No claim reaches them at all. No act
      in the 15,189-key index numbers a §321p, and the one that numbers a §371a
      classifies it into title 42, not 21 — so the fence never fires and A4
      publishes 321(p) and 371(a) exactly as the review verified them.
    * **7 USC 12g (3 rows, RIN 3038-AB17).** The one class-H row the review
      called plausible-unproven. Re-checked under this fence: the Commodity
      Exchange Act's own §12 is 7 U.S.C. 16 and its §8a..§8e family covers
      12a..12e; NO act in the whole index numbers a §12g. No second numbering
      system claims the token, so there is nothing to fence and A4's 12(g)
      stands, unchanged and still unproven-by-abstract.
    * **7 USC 6c (162 rows).** Both numbering systems really do claim it — the
      Code's own §6c and the Act's §6c (→ 13a-1) — and the fence stays silent
      because the parse as filed HAS a witness. Same doctrine, same words, as
      the lost-space rule's "where the stem exists the rule stays SILENT".
    """

    known = oracle()
    off_title = ActSectionClaim(
        act="donald j. cohen national child traumatic stress initiative",
        act_key="2000:310",
        act_section="371a",
        title=42,
        section="280g-2",
        association="agency",
    )
    for section, text, spelled in (("321p", "21 USC 321p", ("321", "p")), ("371a", "21 USC 371a", ("371", "a"))):
        fix = known.corrected_section(21, section, text, 2004, (off_title,))
        assert (fix.rule, fix.section, fix.subsection) == (
            "A4-subsection-rendered-as-a-lettered-section",
            *spelled,
        ), "the FDA family is verified correct and must not move"
        assert known.act_numbering_fence(21, section, (off_title,)) == (), "a claim in another title is no claim"

    twelve_g = known.corrected_section(7, "12g", "7 USC 12g", 1997)
    assert (twelve_g.rule, twelve_g.section, twelve_g.subsection) == (
        "A4-subsection-rendered-as-a-lettered-section",
        "12",
        "g",
    )
    assert known.subsection_verdict(7, "12", "g").verdict == "exists"
    assert not known.section_exists(7, "12g"), "no rival section, and now: no rival numbering"

    cea_6c = ActSectionClaim(
        act="commodity exchange act",
        act_key="1922:369",
        act_section="6c",
        title=7,
        section="13a-1",
        association="agency",
    )
    assert known.section_exists(7, "6c"), "the Code prints a §6c of its own"
    assert known.act_numbering_fence(7, "6c", (cea_6c,)) == ()
    before = known.correction_candidates(7, "6c", "7 U.S.C. 6a, 6c, 6d")
    after = known.correction_candidates(7, "6c", "7 U.S.C. 6a, 6c, 6d", act_sections=(cea_6c,))
    assert before == after, "a fence that fires where two real numbering systems agree decides nothing"


@pytest.mark.slow
def test_b8_a_subsection_on_a_section_that_has_none_is_named_and_never_published() -> None:
    """``42 USC 1395(hh)`` names 42 U.S.C. 1395hh — as a candidate, alone, forever.

    B8 was a correction until 2026-08-23. It is a candidate now because its
    truth rests on evidence outside its own inputs, so it may name a reading
    and may not pick one, however alone that reading stands. The builder's
    ``usc_section_corrected_section`` / ``usc_section_corrected_pinpoint``
    columns follow this module at the next rebuild; nothing here rewrites an
    artifact already on disk.
    """

    known = oracle()
    candidates = known.correction_candidates(42, "1395", "42 USC 1395(hh)", 2015)
    assert [(one.rule, one.section) for one in candidates] == [
        ("B8-lettered-section-rather-than-a-pinpoint", "1395hh")
    ]
    assert candidates[0].corrects is False, "the flag that tells B8 from A4 and B1"
    assert candidates[0].evidence == (
        "lettered section exists: 42 U.S.C. 1395hh is a section the oracle prints; the bare 42 U.S.C. 1395 has "
        "no such lettered subsection ((hh): absent, 0 lettered subsections printed)"
    )
    assert known.corrected_section(42, "1395", "42 USC 1395(hh)", 2015) is None, "one survivor is not enough"
    for letter, target in (("fff", "1395fff"), ("cc", "1395cc"), ("m", "1395m")):
        named = known.correction_candidates(42, "1395", f"42 USC 1395({letter})")
        assert [one.section for one in named] == [target]
        assert known.corrected_section(42, "1395", f"42 USC 1395({letter})") is None


#: The hyphenated lettered sections B8's generator could not reach, with the
#: bare lettered section the truncation reached instead. Every one of the five
#: was published as a correction to the bare section by the build the review
#: read; the human reviewer resolved the first against the publisher (24 CFR
#: part 30's authority note: 12 U.S.C. 1735f-14, National Housing Act § 536,
#: civil money penalties against mortgagees -- while 12 U.S.C. 1735f is "Water
#: and sewerage facilities", a different section on a different subject).
#: ``research/evidence/sample-review-2026-08-23/review.md`` § G, row 7.
HYPHENATED_LETTERED_SPECIMENS = (
    (12, "1735", "f", "14", "1735f-14", "1735f", "12 USC 1735(f)-14"),
    (42, "7385", "s", "10", "7385s-10", "7385s", "42 U.S.C. 7385(s)-10(e)"),
    (12, "1831", "o", "1", "1831o-1", "1831o", "12 U.S.C. 1831(o)-1"),
    (16, "460", "l", "6", "460l-6", "460l", "16 U.S.C. 460(l)-6(d)"),
    (47, "615", "a", "1", "615a-1", "615a", "47 U.S.C. 615(a)-1"),
)


@pytest.mark.slow
def test_b8_reads_the_hyphenated_lettered_section_the_text_states() -> None:
    """``12 USC 1735(f)-14`` is 1735f-14, and 1735f is a different section.

    B8's generator built one reading, ``NNN`` + the letter, and dropped
    whatever followed. That put the whole hyphenated lettered family out of its
    structural reach -- 1735f-14, 1735f-15, 1735z-11a, 1701q-1 -- which is
    exactly the family where a filer's parentheses go astray, and it
    MANUFACTURED the single survivor: with the tail truncated, only the bare
    lettered section was ever offered, so the survivor count could not be
    anything but one.

    All ten sections named here are in the EXACT enumerated set, never reached
    through a range stub, per this module's rule that ranges judge and never
    propose.
    """

    known = oracle()
    for title, section, letter, tail, hyphenated, bare, text in HYPHENATED_LETTERED_SPECIMENS:
        assert known.section_is_enumerated(title, hyphenated), f"{title} U.S.C. {hyphenated}"
        # And the bare lettered section is real too. That is the whole defect:
        # the truncation swapped one printed section for another printed
        # section, so nothing downstream could see it happen.
        assert known.section_is_enumerated(title, bare), f"{title} U.S.C. {bare}"
        assert known.subsection_verdict(title, section, letter).verdict == "absent"
        assert known.lettered_subsections(title, section) == frozenset(), "the pinpoint is impossible as written"
        candidates = known.correction_candidates(title, section, text)
        b8 = [one for one in candidates if one.rule.startswith("B8")]
        assert [one.section for one in b8] == [hyphenated], text
        assert bare not in {one.section for one in candidates}, "the truncated reading is never offered beside it"
        assert f"the text states the tail '-{tail}'" in b8[0].evidence
    # Exactness, stated section by section: the enumerated set, not a range.
    for title, hyphenated, status, first_year in (
        (12, "1735f-14", ("current",), 1994),
        (42, "7385s-10", ("current",), 2004),
        (12, "1831o-1", ("current",), 2011),
        (16, "460l-6", ("repealed",), 1994),
        (47, "615a-1", ("current",), 2008),
    ):
        verdict = known.section_verdict(title, hyphenated)
        assert verdict.exists and verdict.status == status
        assert known.attested_years(title, hyphenated)[0] == first_year


@pytest.mark.slow
def test_a_stated_tail_outranks_the_bare_lettered_reading_and_only_then() -> None:
    """The preference, and the fallback that keeps every untailed reading intact."""

    known = oracle()
    # A tail the Code does not print falls back to the bare lettered section,
    # which is B8's whole original reading and is untouched by this rule.
    assert not known.section_is_enumerated(12, "1735f-99")
    fallback = known.correction_candidates(12, "1735", "12 USC 1735(f)-99")
    assert [one.section for one in fallback if one.rule.startswith("B8")] == ["1735f"]
    assert "states the tail" not in fallback[0].evidence
    # No tail at all: unchanged.
    assert [one.section for one in known.correction_candidates(42, "1395", "42 USC 1395(hh)")] == ["1395hh"]
    # A text stating TWO tails names two readings, and two readings are two
    # survivors: the Voting Rights Act range "1973(aa)-1(a) to 1973(aa)-2".
    both = known.correction_candidates(42, "1973", "42 USC 1973(aa)-1(a) to 1973(aa)-2")
    assert sorted(one.section for one in both if one.rule.startswith("B8")) == ["1973aa-1", "1973aa-2"]
    assert known.corrected_section(42, "1973", "42 USC 1973(aa)-1(a) to 1973(aa)-2") is None
    # And the rule reaches a reading the truncation could not offer AT ALL:
    # 42 U.S.C. 300c is not a section, so B8 was silent on "300(c)-22".
    assert not known.section_is_enumerated(42, "300c")
    assert known.section_is_enumerated(42, "300c-22")
    reached = known.correction_candidates(42, "300", "42 U.S.C. 300(c)-22 (note)")
    assert [one.section for one in reached if one.rule.startswith("B8")] == ["300c-22"]


@pytest.mark.slow
def test_the_stated_tail_is_a_question_a_caller_outside_b8_can_ask() -> None:
    """One enumeration, two readers.

    B8 asks it with the pinpoint letter it has already chosen; the Agenda
    builder's scheme-label repair asks it with no letter at all, because it has
    not chosen one -- it is asking whether the value it just repaired can mean
    the truncated stem, and "12 UDC 1735(f)-14" must never come out as 1735.
    Two callers, one enumeration, so a fence widened for one cannot silently
    widen for the other.
    """

    known = oracle()
    assert known.tail_stated_sections(12, "1735", "12 U.S.C. 1735(f)-14") == ("1735f-14",)
    # The damaged spelling asks the same question and gets the same answer:
    # what is enumerated is a fact about the Code, not about the label.
    assert known.tail_stated_sections(12, "1735", "12 UDC 1735(f)-14") == ("1735f-14",)
    # A tail nothing prints returns nothing rather than a plausible neighbour.
    assert known.tail_stated_sections(12, "1735", "12 U.S.C. 1735(f)-99") == ()
    # No tail stated is not a tail refused: the caller falls back to its own
    # reading, which is what keeps "16 U.S.C. 715(i)" reading 715 as filed.
    assert known.tail_stated_sections(16, "715", "16 U.S.C. 715(i)") == ()
    # TWO stated tails is an ambiguity the caller must refuse, so both come
    # back rather than one being chosen here.
    assert known.tail_stated_sections(42, "1973", "42 USC 1973(aa)-1(a) to 1973(aa)-2") == (
        "1973aa-1", "1973aa-2"
    )
    # And the letter narrows to exactly the pinpoint B8 is reasoning about.
    assert known.tail_stated_sections(
        42, "1973", "42 USC 1973(aa)-1(a) to 1973(aa)-2", letter="bb"
    ) == ()
    assert known.tail_stated_sections(12, "", "12 U.S.C. 1735(f)-14") == ()


@pytest.mark.slow
def test_b8_refuses_the_honest_unknowns_the_campaign_recorded() -> None:
    """The 387-row case a row-count argument would have called wrong."""

    known = oracle()
    for title, section, text, lettered in (
        (5, "552", "5 USC 552(a)", "552a"),
        (42, "2139", "42 USC 2139(a)", "2139a"),
    ):
        candidates = known.correction_candidates(title, section, text)
        assert {candidate.rule for candidate in candidates} == {
            "parse-as-filed",
            "B8-lettered-section-rather-than-a-pinpoint",
        }
        assert known.corrected_section(title, section, text) is None
        assert known.section_verdict(title, lettered).exists
        assert known.subsection_verdict(title, section, "a").verdict == "exists"
    assert corpus()["triples"][(42, "2139", "42 USC 2139(a)")] == 387, "the campaign's 387 rows"
    assert corpus()["triples"][(5, "552", "5 USC 552(a)")] == 413


@pytest.mark.slow
def test_b1_et_seq_follows_a_section_never_a_subsection() -> None:
    known = oracle()
    for title, section, letter, target in (
        (21, "346", "a", "346a"),
        (42, "300", "f", "300f"),
        (16, "460", "k", "460k"),
        (16, "742", "a", "742a"),
        (16, "791", "a", "791a"),
        (42, "2000", "d", "2000d"),
        (7, "136", "a", "136a"),
        (25, "396", "A", "396a"),
        (16, "590", "a", "590a"),
    ):
        text = f"{title} USC {section}({letter}) et seq"
        fix = known.corrected_section(title, section, text)
        assert fix is not None, text
        assert (fix.rule, fix.section) == ("B1-et-seq-follows-a-section", target)
    # 42 U.S.C. 2000 does not exist, which is why B1 does not wait for the bare
    # section: the "et seq." tell is the whole discriminator.
    assert not known.section_verdict(42, "2000").exists
    # Drop the tell and the rule changes hands, and with it the STANDING: B1
    # publishes "346a" because "subsection (a) and following" is not a citation
    # form anyone writes, which is a fact about the text in front of it. B8
    # reaches the same section by a different argument and may only name it,
    # because what settles the same shape elsewhere (15 U.S.C. 18 vs 18a) is
    # not in front of it. Same target, one correction and one candidate.
    with_tell = known.corrected_section(21, "346", "21 USC 346(a) et seq")
    without_tell = known.correction_candidates(21, "346", "21 USC 346(a)")
    assert (with_tell.rule, with_tell.section, with_tell.section) == (
        "B1-et-seq-follows-a-section",
        "346a",
        without_tell[0].section,
    )
    assert (without_tell[0].rule, without_tell[0].corrects) == ("B8-lettered-section-rather-than-a-pinpoint", False)
    assert known.corrected_section(21, "346", "21 USC 346(a)") is None
    # And where the bare section really does carry the letter, nothing is
    # corrected at all: 21 U.S.C. 321 has subsections (a)-(ss) and no 321p.
    assert known.corrected_section(21, "321", "21 USC 321(p)") is None
    assert [candidate.rule for candidate in known.correction_candidates(21, "321", "21 USC 321(p)")] == [
        "parse-as-filed"
    ]


@pytest.mark.slow
def test_the_lost_hyphen_family_the_grammar_refused() -> None:
    """The test citation_grammar said should fail when someone brings an oracle.

    ``LOST_HYPHEN_SPECIMENS`` there lists 14 tokens over 75 source rows and
    refuses all of them, because the only roster that module reaches is an act
    index and non-membership there proves nothing about the Code.
    Against the whole-Code oracle, exactly two reach a single surviving target
    under the named operator; the other twelve reach none, which is a refusal
    with a reason rather than a refusal for want of a roster.
    """

    known = oracle()
    advisers = "15 USC 80b-4, 80b-6(4), 80bll(a), 80b-3(c)(1)"
    recovered = known.recovered_lost_hyphen_sections(15, advisers)
    assert [(one.original_section, one.section) for one in recovered] == [("80bll", "80b-11")]
    assert "80b-11" in recovered[0].evidence
    assert [
        (one.original_section, one.section) for one in known.recovered_lost_hyphen_sections(7, "7 U.S.C. 6b to 6bi")
    ] == [("6bi", "6b-1")]

    refused = {
        (42, "42 USC 300ea-14(e)(2)"),
        (17, "17 U.S.C. 78cl"),
        (42, "42 USC 1437cA"),
        (15, "15 USC 717io"),
        (15, "15 U.S.C. 78cn"),
        (15, "15 USC 78jA"),
        (16, "16 USC 742aj"),
        (15, "15 U.S.C. 77fc"),
        (15, "15 U.S.C. 77fs"),
        (15, "15 USC 78dll(D)"),
        (16, "16 U.S.C. 668ddU.S.C."),
        (7, "7 USC 136fFIFRA Sec 8"),
    }
    for title, text in refused:
        assert known.recovered_lost_hyphen_sections(title, text) == (), text
    # Two of those are refused although a real section sits one UNNAMED
    # operator away -- 42 U.S.C. 1437c-1 and 15 U.S.C. 78j-1 both exist, and
    # reaching them would need "A typed for 1", which is not a typography fact.
    assert known.section_verdict(42, "1437c-1").exists
    assert known.section_verdict(15, "78j-1").exists
    # And the damaged token is never read out of a longer compound name.
    assert known.section_verdict(42, "300aa-14").exists


@pytest.mark.slow
def test_a_space_before_a_lettered_suffix_needs_the_oracle_as_witness() -> None:
    """"15 USC 78 o-10" published section 78, and title 15 has no section 78.

    A section's name never contains a space, so a space between a section's
    digits and its letter suffix is a named damage operator with exactly one
    repair: delete it. The grammar cannot make that repair --
    ``_USC_SECTION_TOKEN`` reads the digits and leaves the letters as uncovered
    text, which is what keeps the row partial and the letters visible -- and
    this module is the one it may not import.

    TWO witnesses, both required. The stem the grammar published must be ABSENT
    from the oracle (no archive year, no printed range stub), so the parse as
    filed has no witness at all; and the fused token must be enumerated
    EXACTLY. Then exactly one reading survives.

    Measured over all 38,182 (title, section, text) keys the pinned artifact
    files: 83 write a spaced suffix at all, and exactly 3 pass both witnesses
    -- 15 U.S.C. 78 -> 78j-1 (SEC RIN 3235-AI75, Spring 2003), 78k-1
    (3235-AK22, Fall 2008), 78o-10 (Federal Reserve RIN 7100-AD74, Fall 2011
    and Fall 2012): 4 rows. The oracle's title 15 runs 71...77, then 77a, 77aa,
    77aaa, 77aaaa, 77b ... and has no section 78; the Exchange Act's sections
    are 78a onward.

    "15 USC 77 eee" is the REFUSAL, and it is why the witnesses are two rather
    than one. 15 U.S.C. 77eee is enumerated -- and so is 15 U.S.C. 77, a
    current section of title 15 in the pinned release point, attested in all 31
    archive years. Two real sections, one string, and nothing this module can
    consult separates them, so the rule offers nothing and the row keeps the
    section its own text supports. The specimen is SEC RINs 3235-AG65 and
    3235-AG68, Spring 1996, whose continuation writes it.
    """

    known = oracle()
    for text, target in (
        ("15 USC 78 o-10", "78o-10"),
        ("15 USC 78 j-1", "78j-1"),
        ("15 USC 78 k-1", "78k-1"),
    ):
        fix = known.corrected_section(15, "78", text)
        assert fix is not None, text
        assert (fix.rule, fix.section, fix.subsection) == (
            "space-lost-before-a-lettered-suffix",
            target,
            None,
        ), text
        assert fix.original_section == "78"
        assert "never contains a space" in fix.evidence

    # The TAIL is part of the target, never dropped. 15 U.S.C. 78o is real --
    # "78 o-10" read as 78o would mint a different real section, which is the
    # exact failure that demoted B8 to candidate-only.
    assert known.section_is_enumerated(15, "78o")
    assert known.corrected_section(15, "78", "15 USC 78 o-10").section == "78o-10"

    # The refusal, with both halves of its reason stated.
    assert known.section_verdict(15, "77", 1996).verdict == "exists"
    assert known.section_is_enumerated(15, "77eee")
    assert known.correction_candidates(15, "77", "15 USC 77 eee") == ()
    assert known.corrected_section(15, "77", "15 USC 77 eee") is None
    # Same shape, same refusal, wherever the stem is real: 16 U.S.C. 668 and
    # 668dd both exist, 42 U.S.C. 1395 and 1395hh both exist.
    for title, stem, text in ((16, "668", "16 USC 668 dd to ee"), (42, "1395", "42 USC 1395 hh")):
        assert known.section_exists(title, stem), text
        assert known.corrected_section(title, stem, text) is None, text

    # The suffix SHAPE is the whole fence against reading an English word as a
    # suffix -- one letter repeated is the only suffix the Code has -- so there
    # is no second list of connectives to drift from it.
    for word in ("et", "to", "and", "or", "sec", "ch", "note", "app", "seq", "through", "of", "as"):
        assert known.correction_candidates(15, "78", f"15 USC 78 {word}") == (), word
    # And a stem that is absent with a target that is not enumerated reaches
    # nothing rather than guessing: 42 U.S.C. 1359 and 1359hh are both absent.
    assert not known.section_exists(42, "1359") and not known.section_is_enumerated(42, "1359hh")
    assert known.corrected_section(42, "1359", "42 USC 1359 hh") is None


@pytest.mark.slow
def test_a_correction_outside_the_oracles_window_is_not_made() -> None:
    known = oracle()
    assert known.correction_candidates(21, "371a", "21 USC 371a", 1990) == ()
    assert known.corrected_section(21, "371a", "21 USC 371a", 2027) is None
    # And an unstated section corrects nothing, though it is a prefix of every
    # damaged token in the value. The recovery keyed on the text alone still
    # finds it, which is where a dropped citation belongs.
    for absent_section in (None, "", "   "):
        assert known.corrected_section(15, absent_section, "15 USC 80bll(a)") is None
    assert known.corrected_section(15, "80", "15 USC 80bll(a)").section == "80b-11"
    assert len(known.recovered_lost_hyphen_sections(15, "15 USC 80bll(a)")) == 1
    # The window gate is BEFORE every rule, the act fence included: an edition
    # outside 1994-2026 asks nothing of the oracle, however good the witness.
    assert known.correction_candidates(7, "8a", "7 USC 8a(5)", 1990, (_CEA_8A,)) == ()
    assert known.corrected_section(7, "8a", "7 USC 8a(5)", 2027, (_CEA_8A,)) is None
    assert set(CORRECTION_RULES) == {
        "parse-as-filed",
        "B1-et-seq-follows-a-section",
        "B8-lettered-section-rather-than-a-pinpoint",
        "A4-subsection-rendered-as-a-lettered-section",
        "act-section-under-a-usc-label",
        "lost-hyphen-with-one-typed-as-a-letter",
        "space-lost-before-a-lettered-suffix",
    }
    # Both censuses that count rules -- this module's refusal key and the
    # builder's ``uscSectionCorrectedRowsByRule`` short name -- take a rule's
    # FIRST dash-token. Two rules sharing one would be counted as one reading,
    # silently, which is why "space-lost" is not spelled "lost-space".
    heads = [rule.split("-")[0] for rule in CORRECTION_RULES]
    assert len(set(heads)) == len(heads), f"two correction rules share a census key: {heads}"


def test_a_rule_publishes_only_where_its_own_inputs_can_decide() -> None:
    """The doctrine, held by construction rather than by care.

    A4 and B1 publish; B8 and parse-as-filed name. What separates them is not a
    string comparison a caller has to remember but
    :data:`CANDIDATE_ONLY_RULES`, read by :attr:`Candidate.corrects` and by
    :class:`Correction`'s own constructor, so a B8 correction cannot be built
    at all -- not by this module, and not by a consumer that wanted one.

    A rule that publishes IN GENERAL can still be struck on one citation, and
    that is a second, per-reading flag rather than a second rule list: A4
    publishes 3,651 rows of the pinned build and is struck on 8.
    """

    assert set(CANDIDATE_ONLY_RULES) == {"parse-as-filed", "B8-lettered-section-rather-than-a-pinpoint"}
    assert set(CANDIDATE_ONLY_RULES) < set(CORRECTION_RULES), "a candidate-only rule is still a declared rule"
    publishing = set(CORRECTION_RULES) - set(CANDIDATE_ONLY_RULES)
    assert publishing == {
        "B1-et-seq-follows-a-section",
        "A4-subsection-rendered-as-a-lettered-section",
        "act-section-under-a-usc-label",
        "lost-hyphen-with-one-typed-as-a-letter",
        "space-lost-before-a-lettered-suffix",
    }
    for rule in CORRECTION_RULES:
        one = Candidate(rule=rule, title=42, section="1395hh", subsection=None, evidence="fixture")
        assert one.corrects is (rule in publishing)
        struck = Candidate(
            rule=rule, title=42, section="1395hh", subsection=None, evidence="fixture", fenced_by="a reason"
        )
        assert struck.corrects is False, "nothing struck publishes, whatever list its rule is on"
        if one.corrects:
            continue
        with pytest.raises(ValueError, match="not a correction rule"):
            Correction(
                rule=rule,
                title=42,
                original_section="1395",
                section="1395hh",
                subsection=None,
                evidence="fixture",
            )
    # And the two new refusals, each with the negative fixture that proves it.
    with pytest.raises(ValueError, match="says what struck it"):
        Candidate(rule="parse-as-filed", title=7, section="8", subsection="a", evidence="fixture", fenced_by="  ")
    assert ACT_ASSOCIATIONS == ("rin", "agency"), "narrowest first, and no corpus-wide level"
    with pytest.raises(ValueError, match="undeclared act association"):
        ActSectionClaim(
            act="commodity exchange act",
            act_key="1922:369",
            act_section="8a",
            title=7,
            section="12a",
            association="corpus",
        )
    with pytest.raises(ValueError, match="names an act, its key"):
        ActSectionClaim(
            act="commodity exchange act", act_key="", act_section="8a", title=7, section="12a", association="rin"
        )


# --------------------------------------------------------------------------- #
# The corpus: 797,170 rows, against the report's own tables


@pytest.mark.slow
def test_the_pinned_corpus_reproduces_the_reports_headline() -> None:
    data, keys = corpus(), misses()
    assert len(data["pair_rows"]) == 11_124, "distinct parsed (title, section, appendix)"
    assert sum(data["pair_rows"].values()) == 685_431
    assert len(keys) == 1_728
    assert sum(data["pair_rows"][key] for key in keys) == 18_117
    assert len({text for key in keys for text in data["pair_texts"][key]}) == 2_372
    assert len({rin for key in keys for rin in data["pair_rins"][key]}) == 2_622
    assert sum(data["pair_ok"][key] for key in keys) == 13_612


@pytest.mark.slow
def test_the_pinned_corpus_reproduces_the_reports_class_table() -> None:
    """Every cell of the report's per-class table, from this module's predicates."""

    data, classified = corpus(), triage()
    pairs: collections.Counter = collections.Counter()
    rows: collections.Counter = collections.Counter()
    ok_rows: collections.Counter = collections.Counter()
    texts: dict[str, set[str]] = collections.defaultdict(set)
    per_pair_texts: collections.Counter = collections.Counter()
    for key, miss in classified.items():
        pairs[miss.name] += 1
        rows[miss.name] += data["pair_rows"][key]
        ok_rows[miss.name] += data["pair_ok"][key]
        texts[miss.name] |= data["pair_texts"][key]
        per_pair_texts[miss.name] += len(data["pair_texts"][key])

    expected = {
        # class: (pairs, texts, rows, `ok` rows) -- the report's table verbatim.
        "C0 title-impossible": (31, 35, 134, 74),
        "C1 zero-padded": (48, 101, 943, 569),
        "C2 subsection-as-section": (75, 91, 3_659, 3_614),
        "C3 paren-suffix-eaten": (4, 84, 343, 50),
        "C5 appendix-out-of-oracle": (33, 55, 269, 80),
        "C6 appendix-miss": (11, 15, 42, 25),
        "C7 chapter-as-section": (94, 144, 1_253, 1_031),
        "C8 hyphen-part-dropped": (3, 26, 158, 98),
        "C8b letter-o-as-zero": (9, 15, 61, 51),
        # The report's single "C8c 109 / 137 / 649 / 431" row, split by
        # mechanism and summing back to it exactly. C8d is the half HEAD's
        # `citation_grammar._abbreviated_span` now reads as a range, so it
        # empties on the next rebuild while C8c does not.
        "C8c inverted-range-kept-whole": (45, 62, 393, 271),
        "C8d abbreviated-span-kept-whole": (64, 75, 256, 160),
        "C9 title-49-pre-1996": (111, 189, 1_969, 1_674),
        "C10 unique-near-miss": (146, 167, 833, 573),
        "C11 corroborated-near-miss": (237, 358, 2_321, 1_686),
        "C12 unresolved": (817, 973, 5_483, 3_656),
    }
    measured = {name: (pairs[name], len(texts[name]), rows[name], ok_rows[name]) for name in pairs}
    assert measured == expected
    assert "C4 date-year-as-section" not in measured, "fixed at f05791de, gone from this build"
    # The C8c/C8d split moved no pair out of the report's row and invented none.
    split = ("C8c inverted-range-kept-whole", "C8d abbreviated-span-kept-whole")
    assert tuple(sum(measured[name][index] for name in split) for index in range(4)) == (109, 137, 649, 431)
    # The report's prose says the class texts "sum to 2,526 against a union of
    # 2,372". That 2,526 is the PER-PAIR sum, not the per-class one: a text
    # citing two nonexistent sections of the same class is counted once in the
    # table column and twice in the prose. Both are reproduced here.
    assert sum(per_pair_texts.values()) == 2_526
    assert sum(len(group) for group in texts.values()) == 2_390


@pytest.mark.slow
def test_the_misses_by_parse_status() -> None:
    """13,612 rows declared themselves clean and pointed at nothing."""

    data = corpus()
    keys = set(misses())
    rows: collections.Counter = collections.Counter()
    texts: dict[str, set[str]] = collections.defaultdict(set)
    for key, row in zip(data["keys"], data["rows"], strict=True):
        if key in keys:
            rows[row[4]] += 1
            texts[row[4]].add(row[2])
    assert {status: (count, len(texts[status])) for status, count in rows.items()} == {
        "ok": (13_612, 1_508),
        "partial": (4_485, 860),
        "corroborated": (20, 4),
    }


@pytest.mark.slow
def test_what_the_oracle_refuses_to_call_absent_over_the_corpus() -> None:
    """161 of the 1,728 misses are coverage holes, not findings."""

    known, data = oracle(), corpus()
    verdicts: collections.Counter = collections.Counter()
    rows: collections.Counter = collections.Counter()
    for key in misses():
        verdict = known.section_verdict(key[0], key[1], appendix=key[2])
        verdicts[(verdict.verdict, verdict.reason)] += 1
        rows[(verdict.verdict, verdict.reason)] += data["pair_rows"][key]
    assert dict(verdicts) == {
        ("absent", None): 1_564,
        ("unknown", "title_49_appendix_not_published"): 161,
        ("unknown", "appendix_title_not_published"): 3,
    }
    assert rows[("absent", None)] == 15_566
    assert rows[("unknown", "title_49_appendix_not_published")] == 2_548
    # 161 is larger than class C9's 111 pairs plus the 30 title-49 appendix
    # pairs of C5, and the 20 extra are the classes that take PRECEDENCE over
    # C9 while the oracle still cannot confirm the section: 49 U.S.C. 401 is
    # classified C7 and its existence stays unknown.
    classified = triage()
    assert sum(1 for key, miss in classified.items() if miss.code == "C9") == 111
    assert sum(1 for key, miss in classified.items() if miss.code == "C5" and key[0] == 49) == 30
    assert classified[(49, "401", False)].code == "C7"
    assert known.section_verdict(49, "401").reason == "title_49_appendix_not_published"


@pytest.mark.slow
def test_the_edition_year_would_have_accused_eight_thousand_rows() -> None:
    """Why an edition-scoped absence is published as a field, not a verdict."""

    known, data = oracle(), corpus()
    filed: collections.Counter = collections.Counter(
        (key, int(row[1][:4])) for key, row in zip(data["keys"], data["rows"], strict=True)
    )
    mismatch_rows = 0
    mismatch_pairs = set()
    before_first = 0
    for (key, year), count in filed.items():
        verdict = known.section_verdict(key[0], key[1], year, appendix=key[2])
        if verdict.exists and verdict.attested_at_edition is False:
            mismatch_rows += count
            mismatch_pairs.add(key)
            if verdict.attested_years and min(verdict.attested_years) > year:
                before_first += count
    assert (mismatch_rows, len(mismatch_pairs), before_first) == (8_227, 706, 822)
    # Every one of those 8,227 rows would have been called absent by an
    # edition-scoped verdict, and 822 of them only because the archive of the
    # citing year predates the enactment it cites.


@pytest.mark.slow
def test_the_corrections_this_module_will_make_over_the_corpus() -> None:
    """Counted per distinct (title, section, authority_text), and per row.

    Corrections are what :meth:`corrected_section` PUBLISHES: A4, B1, "space"
    (3 texts / 4 rows where the stem the grammar published is absent from the
    oracle and the fused token is enumerated) and, since 2026-08-24, "act" --
    the two texts where an act on the filer's own roster numbers the token
    itself. The B8 population is counted beside them, because a rule that names
    a reading without publishing it still has a size and a consumer still has
    to be able to see it. The builder's columns follow at the next rebuild.
    """

    known, data, claims = oracle(), corpus(), act_claims()
    corrected: collections.Counter = collections.Counter()
    corrected_rows: collections.Counter = collections.Counter()
    candidates_only: collections.Counter = collections.Counter()
    candidate_rows: collections.Counter = collections.Counter()
    refused: collections.Counter = collections.Counter()
    refused_rows: collections.Counter = collections.Counter()
    for key, count in data["triples"].items():
        title, section, text = key
        act_sections = claims.get(key, ())
        candidates = known.correction_candidates(title, section, text, None, act_sections)
        if len(candidates) > 1:
            named = "+".join(sorted({candidate.rule.split("-")[0] for candidate in candidates}))
            refused[named] += 1
            refused_rows[named] += count
        elif len(candidates) == 1 and candidates[0].rule != "parse-as-filed":
            named = candidates[0].rule.split("-")[0]
            candidates_only[named] += 1
            candidate_rows[named] += count
        fix = known.corrected_section(title, section, text, None, act_sections)
        if fix is not None:
            corrected[fix.rule.split("-")[0]] += 1
            corrected_rows[fix.rule.split("-")[0]] += count

    assert len(data["triples"]) == 38_218
    assert len(claims) == 76, "76 texts carry a claim the fence can use; two of them are read by A4"
    # B8 IS ABSENT FROM BOTH LINES BELOW, and that is the fix of 2026-08-23.
    # "space" is the lost-space rule, and its 3 texts / 4 rows are exactly the
    # three 15 U.S.C. 78 citations in
    # ``test_a_space_before_a_lettered_suffix_needs_the_oracle_as_witness``.
    # A4 91 -> 89 and "act" 2 on 2026-08-24: the eight 7 U.S.C. 8a rows.
    assert dict(corrected) == {"A4": 89, "B1": 21, "act": 2, "space": 3}
    assert dict(corrected_rows) == {"A4": 3_651, "B1": 155, "act": 8, "space": 4}
    # It is not absent from the corpus. 213 texts / 1,441 rows are a lone B8
    # survivor -- every one of them a correction the build the review read
    # published, and a named candidate now.
    assert dict(candidates_only) == {"A4": 89, "B8": 213, "B1": 21, "space": 3}
    assert dict(candidate_rows) == {"A4": 3_651, "B8": 1_441, "B1": 155, "space": 4}
    assert candidate_rows["B8"] == 1_441 and "B8" not in corrected_rows
    # A4's rows plus the act fence's are exactly class C2 -- the same defect
    # read from the other end, which is the check that the two agree. The
    # triage classifier reads the token's SHAPE and is right that all 3,659 are
    # "a subsection written as a section"; which of two numbering systems the
    # subsection belongs to is a question only the fence asks.
    assert corrected_rows["A4"] + corrected_rows["act"] == 3_659 == sum(
        corpus()["pair_rows"][key] for key, miss in triage().items() if miss.code == "C2"
    )

    # "A4+act" is the first key that is counted HERE and does not reach the
    # builder's receipt: this line counts texts with more than one reading
    # NAMED, and the builder counts a refusal only where nothing published. A
    # struck reading is named and is not a survivor, so those 2 texts / 8 rows
    # publish (above) and the artifact's uscSectionRefusalRowsBySurvivors is
    # unchanged by this fence -- measured on the scratch build of 2026-08-24.
    assert dict(refused) == {"A4+parse": 1_708, "B8+parse": 1_159, "A4+B8+parse": 5, "parse": 689, "A4+act": 2}
    assert refused_rows["A4+act"] == 8
    assert refused_rows["A4+parse"] == 26_190
    # 1,158 texts / 12,589 rows before B8 learned to read a stated tail. The
    # one text / 5 rows it gained is "42 U.S.C. 300(c)-22 (note)": 42 U.S.C.
    # 300c is not a section, so the truncated generator offered NOTHING there
    # and the row carried a lone parse-as-filed candidate, counted nowhere.
    assert refused_rows["B8+parse"] == 12_594
    assert refused_rows["A4+B8+parse"] == 11
    # "parse" alone is not a refusal: one survivor, and it is the reading the
    # grammar already published, so there is nothing to correct.
    assert refused_rows["parse"] == 6_498


@pytest.mark.slow
def test_the_hyphenated_lettered_readings_over_the_corpus() -> None:
    """Every text whose stated tail B8's truncation ate, sized and named.

    The build the review read published the bare lettered section for all of
    them. The builder's ``usc_section_corrected_section`` /
    ``usc_section_correction_evidence`` columns still carry those readings and
    follow this module at the next rebuild; nothing here rewrites an artifact.
    """

    known, data = oracle(), corpus()
    marker = "; the text states the tail"
    texts, rows = 0, 0
    by_reading: collections.Counter = collections.Counter()
    two_real_sections: collections.Counter = collections.Counter()
    published_as_a_correction: collections.Counter = collections.Counter()
    for (title, section, text), count in data["triples"].items():
        candidates = known.correction_candidates(title, section, text)
        stated = [one for one in candidates if one.rule.startswith("B8") and marker in one.evidence]
        if not stated:
            continue
        texts += 1
        rows += count
        for one in stated:
            by_reading[(title, one.section)] += count
            bare = one.section.split("-", 1)[0]
            if known.section_is_enumerated(title, bare):
                two_real_sections[(title, one.section, bare)] += count
                if len(candidates) == 1:
                    published_as_a_correction[(title, one.section, bare)] += count

    assert (texts, rows, len(by_reading)) == (12, 43, 10)
    assert dict(by_reading) == {
        (12, "1735f-14"): 17,
        (42, "7385s-10"): 6,
        (42, "300c-22"): 5,
        (42, "300g-2"): 5,
        (42, "300v-1"): 4,
        (12, "1831o-1"): 2,
        (42, "1973aa-1"): 2,
        (42, "1973aa-2"): 2,
        (16, "460l-6"): 1,
        (47, "615a-1"): 1,
    }
    # The review sized this at 26 rows over 6 texts by reading the raw strings.
    # The 27th row and 7th text are "12 USC 1708(c), 1708(d), 1709(s), 1715b
    # and 1735(f)\x9614", where the dash is U+0096 and only
    # :func:`normalize_section` makes it a hyphen -- the same dash table that
    # kept the whole 1395w-4 / 300gg-11 family from being called nonexistent.
    assert sum(count for (title, name), count in by_reading.items() if name.endswith(("-14", "-10", "-1", "-6"))) >= 27
    assert data["triples"][(12, "1735", "12 USC 1708(c), 1708(d), 1709(s), 1715b and 1735(f)\x9614")] == 1

    # Where BOTH the stated reading and the bare lettered section are printed,
    # the truncation swapped one real section for another real section and no
    # existence check downstream could notice. Nine readings / 40 rows wear
    # that shape; 42 U.S.C. 300c-22 is the tenth and the only one whose bare
    # sibling the Code never printed.
    assert sum(two_real_sections.values()) == 40
    assert len(two_real_sections) == 9
    assert not known.section_is_enumerated(42, "300c")
    # Five of the nine were PUBLISHED as a correction, because the truncation
    # left them one survivor. Those are the five the review caught by hand, and
    # the whole of the wrong-but-real surface the build carried.
    assert dict(published_as_a_correction) == {
        (12, "1735f-14", "1735f"): 17,
        (42, "7385s-10", "7385s"): 6,
        (12, "1831o-1", "1831o"): 2,
        (16, "460l-6", "460l"): 1,
        (47, "615a-1", "615a"): 1,
    }
    assert sum(published_as_a_correction.values()) == 27


@pytest.mark.slow
def test_where_this_modules_correction_counts_differ_from_the_campaigns() -> None:
    """Three differences, each with its cause. An unexplained one is a defect."""

    known, data = oracle(), corpus()

    # B1. The campaign reported 18 texts / 146 rows / 9 (title, section) pairs.
    # This module finds 20 texts / 155 rows / 11 pairs, for two reasons, both
    # widenings and both checked against the oracle:
    #   (a) whitespace between the section and its parenthesis, which the
    #       campaign's SQL predicate did not allow;
    #   (b) two targets the campaign's hand-listed table does not carry.
    b1_texts, b1_rows, b1_targets = set(), 0, collections.Counter()
    for (title, section, text), count in data["triples"].items():
        candidates = known.correction_candidates(title, section, text)
        if len(candidates) == 1 and candidates[0].rule.startswith("B1"):
            b1_texts.add(text)
            b1_rows += count
            b1_targets[(title, candidates[0].section)] += count
    assert (len(b1_texts), b1_rows, len(b1_targets)) == (20, 155, 11)
    assert {(33, "1375a"), (20, "1087a")} <= set(b1_targets), "the two the campaign's table lacks"
    assert "16 USC 460 (k) et seq" in b1_texts, "a space the campaign's regex refused"
    # Both extra targets are real sections, and both were already printed in
    # the edition that cited them -- the widening did not invent an anachronism.
    for title, section, first_edition in ((33, "1375a", 2001), (20, "1087a", 1999)):
        verdict = known.section_verdict(title, section, first_edition)
        assert verdict.exists and verdict.attested_at_edition is True

    # B8. The campaign counted 30 texts / 205 rows / 45 RINs for 42 U.S.C. 1395
    # by enumerating the variants by hand. The mechanical predicate over the
    # same build finds more of the same family.
    family = [
        (key, row) for key, row in zip(data["keys"], data["rows"], strict=True) if key == (42, "1395", False)
    ]
    hit_texts = {
        text
        for text in {row[2] for _key, row in family}
        if (lambda found: len(found) == 1 and found[0].rule.startswith("B8"))(
            known.correction_candidates(42, "1395", text)
        )
    }
    assert len(hit_texts) == 36
    assert sum(1 for _key, row in family if row[2] in hit_texts) == 226
    assert len({row[0] for _key, row in family if row[2] in hit_texts}) == 50

    # The unresolved NNN(x) surface. The campaign sized it at ~1,469 texts /
    # ~29,557 rows by asking whether the CORPUS attests NNNx anywhere. This
    # module asks whether the CODE prints it, which is a different and smaller
    # question: 1,158 texts / 12,589 rows, all refused for two survivors.
    #
    # A4's two largest specimens also read differently in the two reports, and
    # the difference is the denominator, not the finding: the campaign counted
    # the exact string (1,713 and 1,494 + 51 for "21USC 371a") over the
    # 798,114-row build, while the pair carries every spelling.
    assert data["triples"][(21, "321p", "21 USC 321p")] == 1_713
    assert data["pair_rows"][(21, "321p", False)] == 1_764
    assert data["triples"][(21, "371a", "21 USC 371a")] == 1_494
    assert data["pair_rows"][(21, "371a", False)] == 1_551


@pytest.mark.slow
def test_the_lost_hyphen_specimens_over_the_corpus() -> None:
    """14 tokens, 75 source rows in the grammar's list; 2 closed, 12 refused."""

    known, data = oracle(), corpus()
    specimens = (
        ("300ea", 42), ("80bll", 15), ("78cl", 17), ("1437cA", 42), ("717io", 15), ("78cn", 15),
        ("78jA", 15), ("6bi", 7), ("742aj", 16), ("77fc", 15), ("77fs", 15), ("78dll", 15),
        ("668ddU", 16), ("136fFIFRA", 7),
    )
    texts: collections.Counter = collections.Counter()
    for row in data["rows"]:
        texts[row[2]] += 1
    closed, total_rows = {}, 0
    for token, title in specimens:
        pattern = re.compile(rf"(^|[^0-9A-Za-z]){token}([^0-9A-Za-z]|$)")
        hits = [(text, count) for text, count in texts.items() if pattern.search(text)]
        total_rows += sum(count for _text, count in hits)
        found = {one.section for text, _count in hits for one in known.recovered_lost_hyphen_sections(title, text)}
        if found:
            closed[token] = sorted(found)
    assert closed == {"80bll": ["80b-11"], "6bi": ["6b-1"]}
    # The row counts here are over the U.S.C.-parsed rows of this build, not
    # the 75 "source rows" the grammar's list counts over all 42,642 distinct
    # authority values, so they are not the same denominator.
    assert total_rows == 109


# --------------------------------------------------------------------------- #
# The 2026-08-23 change, judged against the reader it replaced
#
# This repository's rule for replacing a running check: keep the old
# implementation as a test-only oracle, COPIED here rather than imported --
# importing the thing under replacement makes the comparison circular -- and
# record the deliberate divergences as a frozen list, so an unlisted one fails
# the suite instead of becoming a diff nobody reads. The pattern is
# ``_old_attested_years`` below. Unlike that one, this replacement is MEANT to
# diverge, so the frozen list is the finding and the agreement is the guard:
# A4, B1 and the lost-hyphen recovery must not move by a single reading.


def _head_correction_candidates(
    known: UscSectionOracle, title: int, section: str, authority_text: str, edition_year: int | None = None
) -> tuple[tuple[str, str, str | None], ...]:
    """``correction_candidates`` as it stood at ``da46f0de``, verbatim in logic.

    Returns ``(rule, section, subsection)`` rather than :class:`Candidate`
    objects: the comparison is about the reading, and HEAD's
    :meth:`corrected_section` would build a B8 :class:`Correction`, which the
    replacement's own constructor now refuses to make.
    """

    section = normalize_section(section)
    text = normalize_section(authority_text)
    window_start, window_end = ORACLE_WINDOW
    if edition_year is not None and not window_start <= edition_year <= window_end:
        return ()
    found: dict[tuple[int, str, str | None], tuple[str, str, str | None]] = {}

    def offer(rule: str, name: str, sub: str | None) -> None:
        found.setdefault((title, name, sub), (rule, name, sub))

    pinpoint = re.search(rf"(?<![0-9a-z]){re.escape(section)}\s*\(\s*([a-z]{{1,4}})\s*\)", text) if section else None
    if pinpoint is not None:
        letter = pinpoint.group(1)
        lettered = section + letter
        structure = known.subsection_verdict(title, section, letter)
        follows_et_seq = re.search(
            rf"(?<![0-9a-z]){re.escape(section)}\s*\(\s*{letter}\s*\)\s*,?\s*et\.?\s*seq", text
        )
        if follows_et_seq and known.section_is_enumerated(title, lettered):
            offer("B1-et-seq-follows-a-section", lettered, None)
        elif known.section_exists(title, section):
            if not (structure.verdict == "absent" and not structure.lettered):
                offer("parse-as-filed", section, letter)
            # The defect: one reading, NNN + the letter, and whatever the text
            # said after it was gone.
            if known.section_is_enumerated(title, lettered):
                offer("B8-lettered-section-rather-than-a-pinpoint", lettered, None)

    split = re.fullmatch(r"(\d+)([a-z]+)", section)
    if split is not None:
        stem, tail = split.group(1), split.group(2)
        if known.section_exists(title, section):
            offer("parse-as-filed", section, None)
        if known.section_is_enumerated(title, stem) and known.subsection_verdict(title, stem, tail).verdict == "exists":
            offer("A4-subsection-rendered-as-a-lettered-section", stem, tail)

    if section and not known.section_exists(title, section):
        for recovered in known.recovered_lost_hyphen_sections(title, authority_text):
            if recovered.original_section.startswith(section):
                offer(recovered.rule, recovered.section, None)
    return tuple(found.values())


def _head_corrected_section(
    known: UscSectionOracle, title: int, section: str, authority_text: str, edition_year: int | None = None
) -> tuple[str, str, str | None] | None:
    """``corrected_section`` at ``da46f0de``: one survivor that is not the parse."""

    candidates = _head_correction_candidates(known, title, section, authority_text, edition_year)
    if len(candidates) != 1 or candidates[0][0] == "parse-as-filed":
        return None
    return candidates[0]


#: Every deliberate divergence, frozen. ``kind`` is the classification the
#: change forces on each: nothing here is a regression, and each says why.
#:
#: * ``published-a-different-real-section`` — the build the review read
#:   PUBLISHED a correction to a section the filer did not cite, and the
#:   section it published is real, so no existence check could see it happen.
#:   The 27 rows the review sized by hand, plus the U+0096 dash spelling only
#:   :func:`normalize_section` reaches.
#: * ``already-refused-reading-relocated`` — two survivors before and after, so
#:   nothing was ever published; what moves is the name in the candidate list.
#: * ``candidate-reached-where-truncation-had-none`` — 42 U.S.C. 300c is not a
#:   section, so the truncated generator was silent and the text carried a lone
#:   parse-as-filed candidate, counted nowhere. It is now two survivors, named
#:   and refused. No correction before, none after.
#: * ``reading-arrived-from-a-new-rule`` — the reader HEAD offered nothing at
#:   all on these, and ``space-lost-before-a-lettered-suffix`` offers one
#:   reading. Nothing HEAD offered moves; a reading ARRIVES beside it, on a
#:   text that carried none. ``old`` is None and ``new`` is what arrived.
#: * ``published-reading-struck-by-a-second-numbering-system`` — the only kind
#:   where a PUBLISHED value changes to a different published value rather than
#:   to nothing. HEAD published A4's 7 U.S.C. 8(a); the act-numbering fence
#:   strikes that reading (it is still offered, and still says 8/(a) here,
#:   because this comparison reads the reading and not the flag that struck it)
#:   and ``act-section-under-a-usc-label`` arrives with 12a. ``old`` is the A4
#:   identity HEAD published and ``new`` is what arrived. Visual review #2,
#:   class H, row 18; 8 rows over two CFTC RINs.
DELIBERATE_DIVERGENCES = (
    (12, "1735", "12 USC 1735(f)-14", 14, "1735f", ("1735f-14",), "published-a-different-real-section"),
    (42, "7385", "42 U.S.C. 7385(s)-10(e)", 6, "7385s", ("7385s-10",), "published-a-different-real-section"),
    (12, "1735", "12 USC 1708(c), 1708(d), 1709(s), 1735(f)-14", 2, "1735f", ("1735f-14",),
     "published-a-different-real-section"),
    (12, "1831", "12 U.S.C. 1831(o)-1", 2, "1831o", ("1831o-1",), "published-a-different-real-section"),
    (12, "1735", "12 USC 1708(c), 1708(d), 1709(s), 1715b and 1735(f)\x9614", 1, "1735f", ("1735f-14",),
     "published-a-different-real-section"),
    (16, "460", "16 U.S.C. 460(l)-6(d)", 1, "460l", ("460l-6",), "published-a-different-real-section"),
    (47, "615", "47 U.S.C. 615(a)-1", 1, "615a", ("615a-1",), "published-a-different-real-section"),
    (42, "300", "42 USC 300(v)-1(b)", 4, "300v", ("300v-1",), "already-refused-reading-relocated"),
    (42, "300", "42 U.S.C. 300g-3(h)(6), 42 U.S.C. 300(g)-2(a)(6), and 42 U.S.C. 300j-9(a)(1)", 4, "300g",
     ("300g-2",), "already-refused-reading-relocated"),
    (42, "1973", "42 USC 1973(aa)-1(a) to 1973(aa)-2", 2, "1973aa", ("1973aa-1", "1973aa-2"),
     "already-refused-reading-relocated"),
    (42, "300", "42 U.S.C. 300g-3(h)(6), 42 U.S.C. 300(g)-2(a)(6), and 42 USC 300j-9(a)(1)", 1, "300g", ("300g-2",),
     "already-refused-reading-relocated"),
    (42, "300", "42 U.S.C. 300(c)-22 (note)", 5, None, ("300c-22",), "candidate-reached-where-truncation-had-none"),
    (15, "78", "15 USC 78 o-10", 2, None, ("78o-10",), "reading-arrived-from-a-new-rule"),
    (15, "78", "15 USC 78 j-1", 1, None, ("78j-1",), "reading-arrived-from-a-new-rule"),
    (15, "78", "15 USC 78 k-1", 1, None, ("78k-1",), "reading-arrived-from-a-new-rule"),
    (7, "8a", "7 USC 8a(5)", 5, "8", ("12a",), "published-reading-struck-by-a-second-numbering-system"),
    (7, "8a", "7 USC 8a", 3, "8", ("12a",), "published-reading-struck-by-a-second-numbering-system"),
)


@cache
def movement() -> dict[str, object]:
    """HEAD's reader and this one, over all 38,218 triples of the pinned build."""

    known, data, claims = oracle(), corpus(), act_claims()
    outcome_changed: dict[tuple, tuple] = {}
    readings_changed: dict[tuple, tuple] = {}
    old_corrections: dict[tuple, tuple] = {}
    new_corrections: dict[tuple, tuple] = {}
    for key, count in data["triples"].items():
        title, section, text = key
        # The corpus's own association, exactly as the builder computes it --
        # HEAD had no such input, which is the whole point of asking twice.
        act_sections = claims.get(key, ())
        old = _head_corrected_section(known, title, section, text)
        fix = known.corrected_section(title, section, text, None, act_sections)
        new = None if fix is None else (fix.rule, fix.section, fix.subsection)
        if old is not None:
            old_corrections[key] = old
        if new is not None:
            new_corrections[key] = new
        if old != new:
            outcome_changed[key] = (count, old, new)
        before = set(_head_correction_candidates(known, title, section, text))
        after = {
            (one.rule, one.section, one.subsection)
            for one in known.correction_candidates(title, section, text, None, act_sections)
        }
        if before != after:
            readings_changed[key] = (count, before, after)
    return {
        "outcome_changed": outcome_changed,
        "readings_changed": readings_changed,
        "old_corrections": old_corrections,
        "new_corrections": new_corrections,
    }


#: The two texts the act-numbering fence struck A4 on, and the identity each
#: now publishes. Named once, so the three harnesses below check the same two
#: keys rather than three descriptions of them.
ACT_FENCED_TEXTS = {
    (7, "8a", "7 USC 8a(5)"): ("act-section-under-a-usc-label", "12a", "5"),
    (7, "8a", "7 USC 8a"): ("act-section-under-a-usc-label", "12a", None),
}


@pytest.mark.slow
def test_no_a4_or_b1_correction_moved_but_the_two_the_fence_struck() -> None:
    """The guard half, with one named exception: A4 lost 2 texts / 8 rows.

    B1 does not move at all. A4 moves on exactly the two texts visual review #2
    found wrong (``research/evidence/review2-2026-08-23/review.md`` § H) and on
    no others -- 91 texts / 3,659 rows before, 89 / 3,651 after, the difference
    being ``7 USC 8a`` and ``7 USC 8a(5)`` at 3 and 5 rows. Nothing about A4's
    RULE changed; what changed is that a Commodity Exchange Act on the CFTC's
    own roster numbers §8a itself, so A4's licence is void there.
    """

    moved, data = movement(), corpus()
    kept = {"A4-subsection-rendered-as-a-lettered-section", "B1-et-seq-follows-a-section"}
    before = {key: value for key, value in moved["old_corrections"].items() if value[0] in kept}
    after = {key: value for key, value in moved["new_corrections"].items() if value[0] in kept}
    assert set(before) - set(after) == set(ACT_FENCED_TEXTS), "an unnamed A4 or B1 correction moved"
    assert {key: before[key] for key in after} == after, "and every one that stayed publishes the identical thing"
    assert len(before) == 112, "112 (title, section, text) published an A4 or B1 correction"
    assert sum(data["triples"][key] for key in before) == 3_814
    assert collections.Counter(value[0].split("-")[0] for value in before.values()) == {"A4": 91, "B1": 21}
    assert len(after) == 110
    assert sum(data["triples"][key] for key in after) == 3_806
    assert collections.Counter(value[0].split("-")[0] for value in after.values()) == {"A4": 89, "B1": 21}
    assert sum(data["triples"][key] for key in ACT_FENCED_TEXTS) == 8
    # B1 alone is untouched on both sides, which is the narrower guard the
    # count above cannot make on its own.
    b1 = {key for key, value in before.items() if value[0] == "B1-et-seq-follows-a-section"}
    assert b1 == {key for key, value in after.items() if value[0] == "B1-et-seq-follows-a-section"}

    # And the new reader publishes nothing else but those 110, the two fenced
    # texts, and the three lost-space readings the rule that landed after this
    # comparison adds -- each on a text HEAD's reader offered NO candidate for
    # at all, so none of them is a reading this comparison moved.
    space = {
        key
        for key, value in moved["new_corrections"].items()
        if value[0] == "space-lost-before-a-lettered-suffix"
    }
    assert len(space) == 3 and sum(data["triples"][key] for key in space) == 4
    fenced = {key: value for key, value in moved["new_corrections"].items() if key in ACT_FENCED_TEXTS}
    assert fenced == ACT_FENCED_TEXTS
    assert set(moved["new_corrections"]) == set(after) | space | set(ACT_FENCED_TEXTS)


@pytest.mark.slow
def test_every_outcome_that_moved_is_b8_the_lost_space_or_the_act_fence() -> None:
    """218 texts / 1,453 rows, in three populations that cannot hide in each other.

    213 / 1,441 are the B8 demotions (a correction stopped being published),
    3 / 4 are the lost-space arrivals (one started), and 2 / 8 are the
    act-numbering fence -- the only population where a published value became a
    DIFFERENT published value. Split on which side is None, and, where neither
    is, on the key, so no fourth population can arrive unnamed.
    """

    moved, data = movement(), corpus()
    withdrawn = {
        key: value
        for key, value in moved["outcome_changed"].items()
        if value[1] is not None and value[2] is None
    }
    arrived = {key: value for key, value in moved["outcome_changed"].items() if value[1] is None}
    relocated = {
        key: value
        for key, value in moved["outcome_changed"].items()
        if value[1] is not None and value[2] is not None
    }
    assert len(moved["outcome_changed"]) == len(withdrawn) + len(arrived) + len(relocated) == 218
    assert sum(count for count, _old, _new in moved["outcome_changed"].values()) == 1_453
    changed = withdrawn
    assert len(changed) == 213
    assert sum(count for count, _old, _new in changed.values()) == 1_441
    assert {(old[0].split("-")[0], new) for _count, old, new in changed.values()} == {("B8", None)}
    assert len(arrived) == 3 and sum(count for count, _old, _new in arrived.values()) == 4
    assert {new[0] for _count, _old, new in arrived.values()} == {"space-lost-before-a-lettered-suffix"}
    # The act fence: A4 out, act-section-under-a-usc-label in, on those two
    # texts and nothing else in the corpus.
    assert set(relocated) == set(ACT_FENCED_TEXTS)
    assert sum(count for count, _old, _new in relocated.values()) == 8
    assert {old[0].split("-")[0] for _count, old, _new in relocated.values()} == {"A4"}
    assert {key: new for key, (_count, _old, new) in relocated.items()} == ACT_FENCED_TEXTS
    # The B8 population, counted independently from the candidate side, is the
    # same 213 / 1,441 -- so nothing changed that was not B8, and no B8
    # correction survived.
    b8_before = {
        key
        for key, value in moved["old_corrections"].items()
        if value[0] == "B8-lettered-section-rather-than-a-pinpoint"
    }
    assert b8_before == set(changed)
    assert sum(data["triples"][key] for key in b8_before) == 1_441


@pytest.mark.slow
def test_the_deliberate_divergences_are_a_frozen_list() -> None:
    """Seventeen texts / 55 rows read to a different section. Each is classified.

    An unlisted divergence fails here rather than becoming a diff nobody reads.
    """

    moved, data = movement(), corpus()
    listed = {(title, section, text): (rows, old, new, kind) for title, section, text, rows, old, new, kind in
              DELIBERATE_DIVERGENCES}
    assert set(moved["readings_changed"]) == set(listed), "an unlisted reading moved"
    for key, (count, before, after) in moved["readings_changed"].items():
        rows, old, new, kind = listed[key]
        assert count == rows == data["triples"][key], key
        if kind == "published-reading-struck-by-a-second-numbering-system":
            # HEAD's whole candidate list survives -- A4's reading is STRUCK,
            # not removed, and this comparison reads readings and not the flag
            # -- and the act's reading joins it. What moved is which of them
            # may publish, which the outcome harness above checks by name.
            assert before < after, key
            assert {rule for rule, _name, _sub in before} == {
                "A4-subsection-rendered-as-a-lettered-section"
            }, key
            assert {name for _rule, name, _sub in before} == {old}, key
            fenced = {rule for rule, _name, _sub in after - before}
            assert fenced == {"act-section-under-a-usc-label"}, key
            assert tuple(sorted(name for _rule, name, _sub in after - before)) == new, key
            struck = [
                one
                for one in oracle().correction_candidates(*key, None, act_claims()[key])
                if one.fenced_by is not None
            ]
            assert [one.rule for one in struck] == ["A4-subsection-rendered-as-a-lettered-section"], key
            continue
        if kind == "reading-arrived-from-a-new-rule":
            # Nothing HEAD offered moved. A reading ARRIVED, on a text HEAD's
            # reader had no candidate for at all, and it is the named one.
            assert old is None and before == set() and before < after, key
            assert {rule for rule, _name, _sub in after} == {"space-lost-before-a-lettered-suffix"}, key
            assert tuple(sorted(name for _rule, name, _sub in after)) == new, key
            continue
        b8_before = sorted(name for rule, name, _sub in before if rule.startswith("B8"))
        b8_after = sorted(name for rule, name, _sub in after if rule.startswith("B8"))
        assert b8_before == ([old] if old is not None else []), key
        assert tuple(b8_after) == new, key
        # Only the B8 reading moved. Every other candidate on every one of
        # these texts is the one HEAD offered.
        assert {one for one in before if not one[0].startswith("B8")} == {
            one for one in after if not one[0].startswith("B8")
        }, key
    assert sum(rows for _t, _s, _x, rows, _o, _n, _k in DELIBERATE_DIVERGENCES) == 55
    by_kind: collections.Counter = collections.Counter()
    rows_by_kind: collections.Counter = collections.Counter()
    for _title, _section, _text, rows, _old, _new, kind in DELIBERATE_DIVERGENCES:
        by_kind[kind] += 1
        rows_by_kind[kind] += rows
    assert dict(by_kind) == {
        "published-a-different-real-section": 7,
        "already-refused-reading-relocated": 4,
        "candidate-reached-where-truncation-had-none": 1,
        "reading-arrived-from-a-new-rule": 3,
        "published-reading-struck-by-a-second-numbering-system": 2,
    }
    assert dict(rows_by_kind) == {
        "published-a-different-real-section": 27,
        "already-refused-reading-relocated": 11,
        "candidate-reached-where-truncation-had-none": 5,
        "reading-arrived-from-a-new-rule": 4,
        "published-reading-struck-by-a-second-numbering-system": 8,
    }
    # The classification is not a label: the 7 that PUBLISHED a wrong reading
    # and the 2 the act fence struck are exactly the ones HEAD's reader
    # corrected, and the other 8 are exactly the ones it never published
    # anything for.
    published = {
        (title, section, text)
        for title, section, text, _rows, _old, _new, kind in DELIBERATE_DIVERGENCES
        if kind in ("published-a-different-real-section", "published-reading-struck-by-a-second-numbering-system")
    }
    assert {key for key in listed if key in moved["old_corrections"]} == published
    # And of those 9, the 2 are the only ones that still publish something --
    # a different section, from a different rule, with the same original kept.
    assert {key for key in published if key in moved["new_corrections"]} == set(ACT_FENCED_TEXTS)
    for title, _section, old, new in (
        (12, "1735", "1735f", "1735f-14"),
        (42, "7385", "7385s", "7385s-10"),
        (12, "1831", "1831o", "1831o-1"),
        (16, "460", "460l", "460l-6"),
        (47, "615", "615a", "615a-1"),
    ):
        assert oracle().section_is_enumerated(title, old), "wrong, and real: that is why nothing downstream saw it"
        assert oracle().section_is_enumerated(title, new)


#: How the hold-out was drawn, restated so a reader can redo it: every corpus
#: ROW whose old reader published a B8 correction (1,441 of them), keyed
#: ``(rin, publication_id, title, section, text)``, sorted, then
#: ``random.Random(20260823).sample(population, 10)``.
B8_HOLD_OUT_SEED = 20260823


@pytest.mark.slow
def test_a_ten_row_b8_hold_out_a_human_can_check_by_eye() -> None:
    """Ten of the 1,441, drawn by seed, with what they were and what they are.

    Nothing here asserts the readings are RIGHT -- that is the judgement this
    module has just disclaimed. It fixes a sample a reviewer can carry to
    reginfo.gov and the CFR authority notes before any rebuild keys on it.
    """

    known, data, moved = oracle(), corpus(), movement()
    # The B8 half of outcome_changed: a correction that STOPPED being
    # published -- old is a reading and new is nothing. The lost-space arrivals
    # (old None) and the two act-fence relocations (new not None) are the other
    # two halves, and neither is what this hold-out samples. The second clause
    # arrived with the act fence on 2026-08-24; without it the population would
    # be 1,449 and this draw would silently be a different ten.
    b8_texts = {
        key
        for key, (_count, old, new) in moved["outcome_changed"].items()
        if old is not None and new is None
    }
    population = sorted(
        (row[0], row[1], row[5], normalize_section(row[6]), row[2])
        for row in data["rows"]
        if (row[5], normalize_section(row[6]), row[2]) in b8_texts
    )
    assert len(population) == 1_441
    draw = random.Random(B8_HOLD_OUT_SEED).sample(population, 10)
    assert [(rin, edition, title, section) for rin, edition, title, section, _text in draw] == [
        ("3084-AA82", "200304", 15, "57"),
        ("2060-AT43", "201710", 42, "7671"),
        ("0938-AJ10", "200204", 42, "1395"),
        ("1018-AW49", "200904", 16, "715"),
        ("0596-AB61", "199710", 16, "559"),
        ("1024-AC30", "199704", 16, "460"),
        ("3064-AF28", "202104", 12, "1831"),
        ("3064-AE94", "202104", 12, "1831"),
        ("2070-AD61", "200310", 21, "346"),
        ("1018-AU89", "200810", 16, "690"),
    ]
    seen = []
    for _rin, _edition, title, section, text in draw:
        old = _head_corrected_section(known, title, section, text)
        candidates = known.correction_candidates(title, section, text)
        assert known.corrected_section(title, section, text) is None, text
        assert [one.section for one in candidates] == [old[1]], "the reading itself did not move on any of the ten"
        seen.append((text, old[1]))
    assert seen == [
        ("15 USC 57(a)", "57a"),
        ("42 U.S.C. 7671 to 7671(q)", "7671q"),
        ("42 USC 1395(hh)", "1395hh"),
        ("16 USC 664, 668dd to 668ee, 715(i)", "715i"),
        ("16 USC 559(a) to 559(g)", "559a"),
        ("16 USC 460(g)", "460g"),
        ("12 U.S.C. 1831(o)", "1831o"),
        ("12 U.S.C. 1831(f)", "1831f"),
        ("21 USC 346(a) FFDCA", "346a"),
        ("16 USC 664, 16 USC 668(dd), 16 USC 685, 16 USC 690(d), 16 USC 715(i), 16 USC 725", "690d"),
    ]
    # Two of the ten are range endpoints read as a pinpoint -- "7671 to
    # 7671(q)", "559(a) to 559(g)" -- and three sit inside a list of other
    # citations. Neither shape is anything B8 consults, which is the argument
    # for naming rather than publishing, restated as ten rows.


@pytest.mark.slow
def test_every_row_the_act_fence_moves_a_human_can_check_by_eye() -> None:
    """All eight, drawn the B8 hold-out's way, with what each was and now is.

    Drawn identically to :data:`B8_HOLD_OUT_SEED`'s sample -- every corpus ROW
    whose published correction changed to a DIFFERENT correction, keyed
    ``(rin, publication_id, title, section, text)``, sorted, then
    ``random.Random(20260823).sample(population, k)``. Here ``k`` is the whole
    population: eight rows is smaller than the ten that sample takes, so the
    hold-out IS the population and a reviewer checks every one rather than a
    tenth of them. The seed is kept anyway, because a population that grows
    past ten must be sampled the same way and not re-invented.

    Nothing here asserts a judgement this module cannot make. What it fixes is
    the eight rows a reviewer carries to uscode.house.gov and reginfo.gov: two
    RINs, eight editions, one filer text per RIN, one witness.
    """

    known, data, moved = oracle(), corpus(), movement()
    relocated = {
        key
        for key, (_count, old, new) in moved["outcome_changed"].items()
        if old is not None and new is not None
    }
    assert relocated == set(ACT_FENCED_TEXTS)
    population = sorted(
        (row[0], row[1], row[5], normalize_section(row[6]), row[2])
        for row in data["rows"]
        if (row[5], normalize_section(row[6]), row[2]) in relocated
    )
    assert len(population) == 8
    draw = random.Random(B8_HOLD_OUT_SEED).sample(population, len(population))
    seen = []
    for rin, edition, title, section, text in sorted(draw):
        old = _head_corrected_section(known, title, section, text)
        fix = known.corrected_section(title, section, text, None, act_claims()[(title, section, text)])
        seen.append(
            (
                rin,
                edition,
                text,
                f"{old[1]}({old[2]})",
                fix.section + (f"({fix.subsection})" if fix.subsection else ""),
            )
        )
    assert seen == [
        ("3038-AB50", "200004", "7 USC 8a", "8(a)", "12a"),
        ("3038-AB50", "200010", "7 USC 8a", "8(a)", "12a"),
        ("3038-AB50", "200104", "7 USC 8a", "8(a)", "12a"),
        ("3038-AD31", "201110", "7 USC 8a(5)", "8(a)", "12a(5)"),
        ("3038-AD31", "201210", "7 USC 8a(5)", "8(a)", "12a(5)"),
        ("3038-AD31", "201304", "7 USC 8a(5)", "8(a)", "12a(5)"),
        ("3038-AD31", "201310", "7 USC 8a(5)", "8(a)", "12a(5)"),
        ("3038-AD31", "201404", "7 USC 8a(5)", "8(a)", "12a(5)"),
    ]
    # The witness, one string, for all eight: 7 U.S.C. 12a's printed source
    # credit. Every RIN here is a CFTC RIN (agency 3038) and every claim came
    # from the same act on the same roster, which is what makes eight rows one
    # judgement rather than eight.
    assert {rin[:4] for rin, _edition, _text, _old, _new in seen} == {"3038"}
    assert {claim.act for key in relocated for claim in act_claims()[key]} == {"commodity exchange act"}
    assert {claim.act_key for key in relocated for claim in act_claims()[key]} == {"1922:369"}
    assert "ch. 369, §8a" in _USC_7_12A_SOURCE_CREDIT


@pytest.mark.slow
def test_the_review_specimens_read_the_way_the_publisher_does() -> None:
    """The three § G rows the 2026-08-23 review turned on, pinned side by side."""

    known = oracle()
    # Row 7, the defect. RIN 2501-AC95, HUD mortgagee civil penalties: NHA
    # § 536 = 12 U.S.C. 1735f-14 (24 CFR part 30's authority note), never
    # 12 U.S.C. 1735f, which is water and sewerage facilities.
    hud = known.correction_candidates(12, "1735", "12 USC 1735(f)-14", 2004)
    assert [(one.rule, one.section, one.corrects) for one in hud] == [
        ("B8-lettered-section-rather-than-a-pinpoint", "1735f-14", False)
    ]
    assert "1735f" not in {one.section for one in hud}, "and never the bare section again"
    assert known.corrected_section(12, "1735", "12 USC 1735(f)-14", 2004) is None
    # Row 10, the one B8 got right -- and got right on the abstract and 16 CFR
    # 801/803, neither of which is an input to this module. Both sections are
    # real, so it names 18a and picks nothing.
    ftc = known.correction_candidates(15, "18", "15 U.S.C. 18(a), Clayton Act", 2019)
    assert [(one.rule, one.section, one.corrects) for one in ftc] == [
        ("B8-lettered-section-rather-than-a-pinpoint", "18a", False)
    ]
    assert known.corrected_section(15, "18", "15 U.S.C. 18(a), Clayton Act", 2019) is None
    assert known.section_verdict(15, "18").exists and known.section_verdict(15, "18a").exists
    # Rows 1-6, 8, 9: A4, measured 8/8 true, and still a correction. It never
    # relocates a citation -- 371a -> 371(a) keeps the identity 371.
    for title, section, text, stem, letter in (
        (33, "1361a", "33 USC 1361a", "1361", "a"),
        (21, "321p", "21 USC 321p", "321", "p"),
        (21, "371a", "21 USC 371a", "371", "a"),
    ):
        fix = known.corrected_section(title, section, text)
        assert (fix.rule, fix.section, fix.subsection) == (
            "A4-subsection-rendered-as-a-lettered-section",
            stem,
            letter,
        )
        assert fix.original_section == section


# --------------------------------------------------------------------------- #
# The sorted-span index: a replaced check keeps the old one as an oracle


def _old_attested_years(known: UscSectionOracle, title: int, section: str, appendix: bool = False) -> tuple[int, ...]:
    """``attested_years`` before :class:`_SpanIndex`, copied verbatim as the test-only reference.

    AGENTS.md: a replacement keeps the old implementation as a test-only
    oracle, copied rather than imported -- importing the thing under
    replacement would make the comparison circular. This is
    ``UscSectionOracle.attested_years``'s linear scan exactly as it read
    before the sorted index; the module itself no longer contains this body.
    """

    section = normalize_section(section)
    years = set(known.annual_sections.get((title, appendix, section), ()))
    key = _section_key(section)
    if key is not None:
        years |= {year for low, high, year in known.annual_ranges.get((title, appendix), ()) if low <= key <= high}
    return tuple(sorted(years))


@cache
def _filed_keys() -> tuple[tuple[int, str, bool, int], ...]:
    """Every distinct ``(title, section, appendix, year)`` the pinned corpus files.

    ``year`` is the citing edition -- ``publication_id``'s head, exactly as
    :func:`test_the_edition_year_would_have_accused_eight_thousand_rows`
    derives it, just flattened into the key instead of used as a Counter's
    second field. 95,492 keys over the pinned build, which is not a
    reconstruction: ``unified_agenda_parquet._judge_usc_sections`` states
    this exact figure as the key count "over the 685,431 U.S.C. rows the
    oracle report measured" -- this snapshot -- against 95,107 "over the
    685,268" rows of the builder's own, separately evolving working copy,
    163 U.S.C. rows fewer. Different build, not a missed dedup.
    """

    data = corpus()
    return tuple(
        sorted(
            {(key[0], key[1], key[2], int(row[1][:4])) for key, row in zip(data["keys"], data["rows"], strict=True)}
        )
    )


@pytest.mark.slow
def test_attested_years_index_matches_the_old_linear_scan_on_every_corpus_key() -> None:
    """The sorted-index optimization, proven against the scan it replaced -- and timed.

    Measured on this machine, one run each, same process, back to back: the
    old linear scan took 8.8s over the 95,492 keys below; the indexed
    ``attested_years`` took 0.26s over the same keys -- about 34x. The module
    docstring and :class:`_SpanIndex`'s restate these two figures. Absolute
    seconds will drift with the machine; the equality check is what actually
    guards behaviour, and the loose timing assertion below is a tripwire
    against the index silently regressing back to a scan, not a benchmark.
    """

    known = oracle()
    keys = _filed_keys()
    assert len(keys) > 90_000, "the corpus shrank; the before/after figures no longer describe this build"

    start = time.perf_counter()
    old_results = [_old_attested_years(known, title, section, appendix) for title, section, appendix, _year in keys]
    old_elapsed = time.perf_counter() - start

    start = time.perf_counter()
    new_results = [known.attested_years(title, section, appendix=appendix) for title, section, appendix, _year in keys]
    new_elapsed = time.perf_counter() - start

    assert new_results == old_results
    assert new_elapsed < old_elapsed, (old_elapsed, new_elapsed)


def test_span_index_matches_brute_force_on_adversarial_interval_sets() -> None:
    """:class:`_SpanIndex` against a naive scan, on shapes the real corpus may not exercise.

    The corpus test above proves the index against every span OLRC actually
    printed; it does not prove the shapes OLRC never printed -- unsorted
    input (the raw table arrives in row order, not low order), a key exactly
    on a ``low`` or ``high`` boundary, several spans from different years all
    covering the same key, a key strictly between two spans neither of which
    reaches it, an empty bucket, and a degenerate ``low > high`` stub (which
    the old linear scan also never matched, since no key can be both ``>=
    low`` and ``<= high`` when ``low > high``). Each is constructed here,
    deterministically seeded, and checked one key at a time against a
    brute-force scan -- the mutation battery AGENTS.md asks of a replaced
    check, adapted to an algorithmic replacement rather than a judgment rule.
    """

    rng = random.Random(20260822)
    universe = [(n, letter) for n in range(25) for letter in ("", "a", "b", "bb")]

    def brute_contains(spans: list[tuple[tuple[int, str], tuple[int, str], int]], key: tuple[int, str]) -> bool:
        return any(low <= key <= high for low, high, _payload in spans)

    def brute_payloads(spans: list[tuple[tuple[int, str], tuple[int, str], int]], key: tuple[int, str]) -> list[int]:
        return sorted(payload for low, high, payload in spans if low <= key <= high)

    cases: list[list[tuple[tuple[int, str], tuple[int, str], int]]] = [
        [],  # no spans at all
        [(universe[5], universe[5], 2001)],  # a single-point span
        [(universe[0], universe[-1], 1999)],  # one span covering the whole universe
        [(universe[10], universe[3], 2000)],  # low > high: a degenerate stub, never matches
        [(universe[5], universe[9], 1994), (universe[5], universe[9], 1994)],  # exact duplicate rows
    ]
    for _ in range(30):
        spans = []
        for _ in range(rng.randint(0, 40)):
            a, b = rng.choice(universe), rng.choice(universe)
            low, high = (a, b) if a <= b else (b, a)
            spans.append((low, high, rng.randint(1994, 2024)))
        rng.shuffle(spans)  # the real table arrives in row order, never pre-sorted by low
        cases.append(spans)

    for spans in cases:
        index = _SpanIndex.build(spans)
        for key in universe:
            assert index.contains(key) == brute_contains(spans, key), (spans, key)
            assert sorted(index.payloads_containing(key)) == brute_payloads(spans, key), (spans, key)
