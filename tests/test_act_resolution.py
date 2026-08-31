"""Act-name resolution over the two pinned OLRC sources.

Two kinds of test, deliberately. **Fixture cases** state a rule on the
smallest index that can express it, so the rule is readable and a change to it
fails here first. **Artifact cases** run a property over the real pinned
tables — every name, every classification — because a rule that holds on four
hand-written rows and fails on 10,976 real ones is not a rule.

Where a test pins a count, that count was measured against
``output/usc-act-index-2026-08-02`` and ``output/usc-source-credit-index-2026-08-02``
at release point 119-102. A pinned count that moves is a finding, not a
nuisance: it means the artifact changed shape.
"""

from __future__ import annotations

import collections
import json
import re
import shutil
import tempfile
from pathlib import Path

import pytest
import rulespec_conformance

from refspec.registry.act_resolution import (
    _ARTIFACT_PINS,
    _RKAF_USC_IRI,
    ALIAS_MAX_DEPTH,
    ANSWERING_SOURCES,
    SOURCE_CREDIT_STATUSES,
    UNRESOLVED_REASONS,
    ActIndex,
    ActResolution,
    Classification,
    SourceCreditAnswer,
    SourceCreditIndex,
    SourceCreditTarget,
    _read_pinned_parquet,
    _resolve_through_table3,
    _Verdict,
    canonical_usc_iri,
    resolve_act_name,
    resolve_act_relative_citation,
    stated_name_chain,
)
from refspec.registry.citation_grammar import ActRelativeCitation, normalize_popular_name

ROOT = Path(__file__).resolve().parents[1]
ACT_DIR = ROOT / "output" / "usc-act-index-2026-08-02"
BULK_ACT_DIR = ROOT / "output" / "usc-act-index-2026-08-22"
CREDIT_DIR = ROOT / "output" / "usc-source-credit-index-2026-08-02"

artifact = pytest.mark.skipif(
    not (ACT_DIR.is_dir() and BULK_ACT_DIR.is_dir() and CREDIT_DIR.is_dir()),
    reason="pinned OLRC artifacts are not present",
)


def _citation(act: str, section: str, division: str | None = None) -> ActRelativeCitation:
    return ActRelativeCitation(
        act_name=act, act_key=normalize_popular_name(act), section=section, division=division
    )


@pytest.fixture(scope="module")
def index() -> ActIndex:
    return ActIndex.from_artifact(ACT_DIR)


@pytest.fixture(scope="module")
def credits() -> SourceCreditIndex:
    return SourceCreditIndex.from_artifact(CREDIT_DIR)


@pytest.fixture(scope="module")
def every_name() -> tuple[str, ...]:
    """Every name the tool writes anywhere — as an entry or as a target."""

    rows = _read_pinned_parquet(ACT_DIR, "usc-popular-names.parquet")
    names = {row["name_key"] for row in rows if row["name_key"]}
    names |= {row["see_also_key"] for row in rows if row["see_also_key"]}
    return tuple(sorted(names))


# --------------------------------------------------------------------------- #
# Fixture cases — the ancestor's measured examples, no artifacts needed.

FIXTURE_INDEX = ActIndex(
    table3_key_by_name={
        "employee retirement income security act of 1974": "93-406",
        "taxpayer certainty and disaster tax relief act of 2020": "116-260",
    },
    alias_by_name={"erisa": "employee retirement income security act"},
    classifications={
        "93-406": {
            "101": (Classification("29", "1021", None, 832),),
            "2": (Classification("29", "1001", None, 830),),
        },
        "116-260": {
            # Three classifications for one (law, section): the real shape of
            # a public law carrying many acts.
            "107": (
                Classification("15", "9061", None, 2221),
                Classification("26", "6428a", None, 2276),
                Classification("49", "60122", None, 2623),
            ),
        },
    },
    division_by_name={"taxpayer certainty and disaster tax relief act of 2020": ("EE", 3038)},
    division_starts={"116-260": (("N", 2221), ("T", 2276), ("EE", 3038))},
)


def test_the_alias_year_rule_resolves_erisa_and_refuses_ambiguity() -> None:
    """"ERISA" -> "... Act" -> supply "of 1974" because exactly one act does."""

    assert resolve_act_name("ERISA", FIXTURE_INDEX) == (
        "employee retirement income security act of 1974"
    )
    assert resolve_act_name("Affordable Care Act", FIXTURE_INDEX) is None


def test_the_year_is_supplied_only_when_exactly_one_act_supplies_it() -> None:
    """The rule's whole point. Two candidates is not a candidate.

    "Clean Air Act Amendments" would be 1966, 1970 and 1977 — the tool
    distinguishes them by the year and nothing else, so choosing among them
    would invent a citation the source never made.
    """

    one = ActIndex(table3_key_by_name={"clean air act amendments of 1970": "91-604"})
    assert resolve_act_name("Clean Air Act Amendments", one) == "clean air act amendments of 1970"

    several = ActIndex(
        table3_key_by_name={
            "clean air act amendments of 1966": "89-675",
            "clean air act amendments of 1970": "91-604",
            "clean air act amendments of 1977": "95-95",
        }
    )
    assert resolve_act_name("Clean Air Act Amendments", several) is None


def test_a_name_the_tool_lists_outright_beats_a_year_this_module_would_supply() -> None:
    """A listed name is read; a supplied year is inferred. Reading wins.

    59 stems in the pinned index are themselves listed acts — "Agricultural
    Adjustment Act" is listed, and so is "Agricultural Adjustment Act of
    1938". The bare name must answer itself.
    """

    both = ActIndex(
        table3_key_by_name={
            "agricultural adjustment act": "1933:25",
            "agricultural adjustment act of 1938": "75-430",
        }
    )
    assert resolve_act_name("Agricultural Adjustment Act", both) == "agricultural adjustment act"


def test_what_the_tool_states_outranks_what_this_module_derives() -> None:
    """:data:`ALIAS_PRECEDENCE_RULE`. A cross-reference is evidence; a year is not.

    The whole stated chain is searched for a listed act before any year is
    supplied. Here the tool says "X Act — see Y Act" and also lists an "X Act
    of 1999". Supplying the year first answers the amending act; reading the
    cross-reference first answers the act.
    """

    index = ActIndex(
        table3_key_by_name={"y act": "1948:758", "x act of 1999": "106-1"},
        alias_by_name={"x act": "y act"},
    )
    assert resolve_act_name("X Act", index) == "y act"

    # And where the stated chain leads nowhere, the year is still supplied —
    # the rule is a precedence, not a removal.
    dangling = ActIndex(
        table3_key_by_name={"x act of 1999": "106-1"},
        alias_by_name={"x act": "title 10, chapter 13 (sec. 251 et seq"},
    )
    assert resolve_act_name("X Act", dangling) == "x act of 1999"


def test_the_stated_chain_is_the_query_then_what_the_tool_points_at() -> None:
    """The chain is a value, so what the precedence reads can be inspected."""

    index = ActIndex(alias_by_name={"a": "b", "b": "c"})
    assert stated_name_chain("A", index) == ("a", "b", "c")
    assert stated_name_chain("nothing points anywhere", index) == ("nothing points anywhere",)
    # A cycle appears once and stops; it never repeats a name.
    assert stated_name_chain("a", ActIndex(alias_by_name={"a": "b", "b": "a"})) == ("a", "b")
    assert len(stated_name_chain("n0", ActIndex(alias_by_name={
        f"n{i}": f"n{i + 1}" for i in range(ALIAS_MAX_DEPTH + 4)
    }))) == ALIAS_MAX_DEPTH


def test_an_alias_chain_terminates() -> None:
    """Every cycle shape refuses instead of spinning, and none of them hangs."""

    for edges in (
        {"a": "a"},  # self-loop
        {"a": "b", "b": "a"},  # two-cycle
        {"a": "b", "b": "c", "c": "a"},  # three-cycle
        {"a": "b", "b": "c", "c": "b"},  # lasso: the cycle is not at the head
    ):
        cyclic = ActIndex(table3_key_by_name={}, alias_by_name=edges)
        assert resolve_act_name("a", cyclic) is None, edges

    # A cycle that passes THROUGH a listed act still answers it.
    reachable = ActIndex(table3_key_by_name={"b": "1-1"}, alias_by_name={"a": "b", "b": "a"})
    assert resolve_act_name("a", reachable) == "b"


def test_a_chain_longer_than_the_declared_bound_is_abandoned() -> None:
    """:data:`ALIAS_MAX_DEPTH` is a real fence, not decoration.

    Termination never depended on it — the walk stops at the first name it has
    already seen — so this pins what the bound itself does, which is to give
    up on a chain no OLRC page has ever produced. The pinned index's longest
    chain is two hops, so the fence has measured headroom and never fires
    there; abandoning is recorded upstream as ``act_not_in_index``, which is a
    mislabel this suite records rather than hides (see
    ``test_the_refusals_are_mostly_names_the_tool_does_list``).
    """

    ladder = {f"n{i}": f"n{i + 1}" for i in range(ALIAS_MAX_DEPTH + 4)}

    inside = ActIndex(table3_key_by_name={f"n{ALIAS_MAX_DEPTH - 1}": "1-1"}, alias_by_name=ladder)
    assert resolve_act_name("n0", inside) == f"n{ALIAS_MAX_DEPTH - 1}"

    beyond = ActIndex(table3_key_by_name={f"n{ALIAS_MAX_DEPTH}": "1-1"}, alias_by_name=ladder)
    assert resolve_act_name("n0", beyond) is None


def test_a_section_wholly_outside_the_citing_acts_division_refuses() -> None:
    """The ancestor's own worked example: (116-260, 107) has three rows at
    134 Stat. 2221/2276/2623, and the Taxpayer act is div. EE from 3038 —
    every classification belongs to a sibling act."""

    resolution = resolve_act_relative_citation(
        _citation("Taxpayer Certainty and Disaster Tax Relief Act of 2020", "107"),
        index=FIXTURE_INDEX,
    )
    assert resolution.iri is None
    assert resolution.unresolved_reason == "act_section_outside_act"


def test_a_range_that_narrows_to_exactly_one_row_still_refuses() -> None:
    """**The sound half only.** Exclusion is safe; selection is not.

    A page outside a range that is too WIDE is outside the true one, so
    "every row is outside" refuses soundly. The converse does not hold: the
    range is derived from popular-name start pages, and 6.6% of the pages such
    a range accepts (2,240 of 34,113 measured) belong to a different division.
    Here the range admits exactly one of three rows — and the answer is still
    a refusal, because "the only row I did not exclude" is not evidence that
    it is the right one.
    """

    index = ActIndex(
        table3_key_by_name={"an act": "116-260"},
        classifications={
            "116-260": {
                "107": (
                    Classification("15", "9061", None, 2221),
                    Classification("26", "6428a", None, 3100),  # inside div. EE
                    Classification("49", "60122", None, 4000),
                )
            }
        },
        division_by_name={"an act": ("EE", 3038)},
        division_starts={"116-260": (("N", 2221), ("EE", 3038), ("FF", 3500))},
    )
    assert index.act_page_range("an act") == (3038, 3500)
    resolution = resolve_act_relative_citation(_citation("An Act", "107"), index=index)
    assert resolution.iri is None
    assert resolution.unresolved_reason == "act_section_ambiguous", (
        "narrowing to one row is not the same as identifying it"
    )


def test_the_page_range_is_the_divisions_not_the_acts() -> None:
    """An act states where IT starts; the range must be its DIVISION's.

    Many popular names are a title inside a division, so ending the range at
    the next act truncates the division: 936 of 1,350 testable acts had USLM
    pages outside the act-derived range, and none outside this one.
    """

    index = ActIndex(
        table3_key_by_name={"first": "116-260", "later": "116-260", "undivided": "116-260"},
        division_by_name={"first": ("N", 2400), "later": ("EE", 3038)},
        division_starts={"116-260": (("N", 2221), ("EE", 3038))},
    )
    # "first" starts at 2400 but its division N starts at 2221 and runs to EE.
    assert index.act_page_range("first") == (2221, 3038)
    # The last division has no successor, so it is open-ended.
    assert index.act_page_range("later")[0] == 3038
    assert index.act_page_range("later")[1] > 1_000_000
    # An act that states no division bounds nothing, rather than asserting the
    # whole public law.
    assert index.act_page_range("undivided") is None


def test_two_divisions_that_begin_on_one_page_do_not_truncate_each_other() -> None:
    """The end is the next start STRICTLY later. Five laws need this.

    If a co-starting division ended the range, the range would be empty and
    every row would be excluded — the sound direction turned into a machine
    for refusing everything.
    """

    index = ActIndex(
        table3_key_by_name={"an act": "117-1"},
        division_by_name={"an act": ("A", 100)},
        division_starts={"117-1": (("A", 100), ("B", 100), ("C", 500))},
    )
    assert index.act_page_range("an act") == (100, 500)


def test_a_quarantined_source_refuses_before_it_is_read() -> None:
    """A hole in the build is not an absence of classification.

    The artifact's receipt records one Table III page that could not be read;
    a citation into it must say ``source_incomplete``, never
    ``act_section_not_classified``, which would assert a fact the build never
    established.
    """

    index = ActIndex(
        table3_key_by_name={"an act": "119-21"},
        classifications={"119-21": {"70204": (Classification("26", "1", None, 1),)}},
        incomplete_sources=frozenset({"119-21"}),
    )
    resolution = resolve_act_relative_citation(_citation("An Act", "70204"), index=index)
    assert resolution.unresolved_reason == "source_incomplete"


def test_any_status_at_all_means_the_classification_is_not_current() -> None:
    """The status column is a flag, not a vocabulary this module interprets.

    Measured values in the pinned table: "Rep." (600 rows), "Elim." (183) and
    "Rev. T." (6). Reading them would be reading OLRC's editorial shorthand;
    refusing on any of them reads only that the row is not live.
    """

    for status in ("Rep.", "Elim.", "Rev. T.", "something OLRC has not written yet"):
        index = ActIndex(
            table3_key_by_name={"an act": "1-1"},
            classifications={"1-1": {"2": (Classification("29", "1001", status, 830),)}},
        )
        resolution = resolve_act_relative_citation(_citation("An Act", "2"), index=index)
        assert resolution.unresolved_reason == "classification_not_current", status


def test_a_row_naming_a_title_but_no_section_is_not_an_answer() -> None:
    """Table III can name a place with no section number. "5 App." is one.

    The Appendix to Title 5 held the Inspector General Act, the Federal
    Advisory Committee Act and the Ethics in Government Act until the 2022
    recodification moved them into Title 5 proper — so a row reading
    ``5 App.`` with no section is a real classification, not damage. Five such
    rows sit in the pinned table (see
    ``test_the_appendix_to_title_five_is_a_real_place``), and every one of
    them is shielded by an earlier branch, so only this fixture reaches the
    guard. It is kept for the rebuild where one is not shielded.
    """

    index = ActIndex(
        table3_key_by_name={"an act": "117-328"},
        classifications={"117-328": {"604": (Classification("5 App.", None, None, 5566),)}},
    )
    resolution = resolve_act_relative_citation(_citation("An Act", "604"), index=index)
    assert resolution.iri is None
    assert resolution.unresolved_reason == "act_section_not_classified"


def test_a_division_named_twice_starts_at_its_earliest_page() -> None:
    """A division begins where its EARLIEST act does, not where the last says.

    ``from_artifact`` already mins per division, so no loaded index can carry
    a division twice. This states what the minimum means for one built by hand
    or by a future loader: two rows for one division are two acts inside it,
    and the division starts at the lower page. Only the START is asserted —
    where a repeated division should END is not a question the source has
    ever posed, and inventing an answer here would be inventing a rule.
    """

    index = ActIndex(
        table3_key_by_name={"an act": "117-1"},
        division_by_name={"an act": ("A", 400)},
        division_starts={"117-1": (("A", 200), ("A", 400), ("B", 900))},
    )
    assert index.act_page_range("an act")[0] == 200


def test_ambiguity_is_decided_before_currency_and_that_is_load_bearing() -> None:
    """A repealed row still counts as a competing classification.

    96 (key, section) pairs in the pinned index mix live and dead rows, and 69
    of them have exactly one live row. Dropping the dead rows first would
    answer those 69 — and would be this module choosing which of OLRC's rows
    to believe. It refuses instead, and this pins that order so the cheaper
    rule cannot creep in unnoticed.
    """

    index = ActIndex(
        table3_key_by_name={"an act": "109-58"},
        classifications={
            "109-58": {
                "301(a)": (
                    Classification("42", "15801", "Rep.", 594),
                    Classification("42", "16011", None, 594),
                )
            }
        },
    )
    resolution = resolve_act_relative_citation(_citation("An Act", "301(a)"), index=index)
    assert resolution.unresolved_reason == "act_section_ambiguous"


def test_two_sources_agreeing_says_both_and_disagreeing_refuses() -> None:
    citation = _citation("ERISA", "101")
    agreeing = SourceCreditIndex.from_rows([("93-406", "A", "101", "29", "1021", "88", "840")])
    # ERISA states no division in the fixture, so the credit key falls back to
    # the citation's stated division.
    resolved = resolve_act_relative_citation(
        _citation("ERISA", "101", division="A"), index=FIXTURE_INDEX, source_credits=agreeing
    )
    assert resolved.iri == "urn:rkaf:us:usc:29:1021"
    assert resolved.answered_by == "both"
    # An agreed answer publishes the credits' volume AND page; Table III alone
    # publishes a page with no volume, because its loader drops the column.
    assert (resolved.statutes_at_large_volume, resolved.statutes_at_large_page) == ("88", "840")

    disagreeing = SourceCreditIndex.from_rows([("93-406", "A", "101", "26", "7345", "88", "840")])
    refused = resolve_act_relative_citation(
        _citation("ERISA", "101", division="A"), index=FIXTURE_INDEX, source_credits=disagreeing
    )
    assert refused.iri is None, "two answers is not an answer"
    assert refused.unresolved_reason == "sources_disagree"
    # The refusal still records what each source said.
    assert refused.table3_reason is None and refused.source_credit_status == "resolved"

    solo = resolve_act_relative_citation(citation, index=FIXTURE_INDEX)
    assert solo.answered_by == "table3"
    assert solo.source_credit_status == "not_consulted"
    assert solo.statutes_at_large_page == "832" and solo.statutes_at_large_volume is None


def test_disagreement_always_refuses_whatever_the_two_sources_say() -> None:
    """The property behind :data:`SOURCE_COMPOSITION_RULE`, not one specimen.

    Over every pairing of a Table III target with a credit target, the answer
    is published only where the two mint the same identifier. There is no
    input for which this module names a winner.
    """

    seen: collections.Counter[str] = collections.Counter()
    for t3_title, t3_section in (("29", "1021"), ("26", "7345"), ("42", "7411")):
        for cr_title, cr_section in (("29", "1021"), ("26", "7345"), ("22", "2714a")):
            index = ActIndex(
                table3_key_by_name={"an act": "93-406"},
                classifications={
                    "93-406": {"101": (Classification(t3_title, t3_section, None, 832),)}
                },
            )
            credits = SourceCreditIndex.from_rows(
                [("93-406", "A", "101", cr_title, cr_section, "88", "840")]
            )
            resolution = resolve_act_relative_citation(
                _citation("An Act", "101", division="A"), index=index, source_credits=credits
            )
            agree = (t3_title, t3_section) == (cr_title, cr_section)
            if agree:
                assert resolution.answered_by == "both"
                seen["both"] += 1
            else:
                assert resolution.iri is None
                assert resolution.unresolved_reason == "sources_disagree"
                seen["refused"] += 1
    # Nine pairings; the two sets of targets coincide on exactly two of them.
    assert seen == {"refused": 7, "both": 2}
    assert sum(seen.values()) == 9


def test_the_credits_answer_where_table_iii_has_no_row_at_all() -> None:
    """Complementary, not a tiebreaker. This is the coverage claim, in one case.

    Of the 222 unambiguous credit triples whose public law Table III was also
    fetched for, 176 have no in-division Table III row at all.
    """

    index = ActIndex(table3_key_by_name={"an act": "99-514"}, division_by_name={"an act": ("A", 2085)})
    credits = SourceCreditIndex.from_rows([("99-514", "A", "1234", "26", "6038e", "100", "2085")])
    resolution = resolve_act_relative_citation(_citation("An Act", "1234"), index=index, source_credits=credits)
    assert resolution.iri == "urn:rkaf:us:usc:26:6038e"
    assert resolution.answered_by == "source_credits"
    # And Table III's silence is kept, because it is the coverage fact.
    assert resolution.table3_reason == "act_section_not_classified"


def test_a_credit_target_the_space_cannot_spell_unseats_only_a_bare_absence() -> None:
    """``act_section_not_classified`` claims an absence; a credit falsifies it.

    Table III saying "I have no row" is a claim about the world. If the other
    source holds a target — even one this module cannot mint — the claim is
    false, and publishing it would publish an absence of knowledge as
    knowledge. Any OTHER Table III reason is a fact about a row that exists,
    and stands.
    """

    # A statutory note: real, citable, and outside rkaf:us-usc, which has no
    # production for one. (Not a multi-letter section — those mint now.)
    unspellable = SourceCreditIndex.from_rows([("93-406", "A", "9", "42", "1 nt", "88", "840")])

    bare_absence = ActIndex(table3_key_by_name={"an act": "93-406"}, division_by_name={"an act": ("A", 1)})
    resolution = resolve_act_relative_citation(
        _citation("An Act", "9"), index=bare_absence, source_credits=unspellable
    )
    assert resolution.unresolved_reason == "usc_section_not_expressible"
    assert resolution.table3_reason == "act_section_not_classified"
    assert (resolution.usc_title, resolution.usc_section) == ("42", "1 nt"), "nothing vanishes"

    # The converse: a reason about a row that exists is not unseated.
    stale = ActIndex(
        table3_key_by_name={"an act": "93-406"},
        classifications={"93-406": {"9": (Classification("29", "1001", "Rep.", 830),)}},
        division_by_name={"an act": ("A", 1)},
    )
    kept = resolve_act_relative_citation(_citation("An Act", "9"), index=stale, source_credits=unspellable)
    assert kept.unresolved_reason == "classification_not_current"


def test_a_division_conflict_refuses_without_consulting_the_credits() -> None:
    """The two halves disagree about which act is meant; there is no key.

    Consulting the credits under either division would be answering a question
    neither half asked. The resolution records ``not_consulted`` rather than
    implying the credits were silent.
    """

    index = ActIndex(
        table3_key_by_name={"an act": "116-260"},
        classifications={"116-260": {"107": (Classification("26", "6428a", None, 3050),)}},
        division_by_name={"an act": ("EE", 3038)},
    )
    credits = SourceCreditIndex.from_rows([("116-260", "N", "107", "15", "9061", "134", "2221")])
    resolution = resolve_act_relative_citation(
        _citation("An Act", "107", division="N"), index=index, source_credits=credits
    )
    assert resolution.unresolved_reason == "act_division_conflict"
    assert resolution.source_credit_status == "not_consulted"
    assert resolution.act_key == "an act" and resolution.table3_key == "116-260"


def test_multi_target_is_recorded_and_never_resolved() -> None:
    """"The source said two things" stays distinct from "the source said nothing"."""

    credits = SourceCreditIndex.from_rows(
        [
            ("114-94", "C", "32101", "22", "2714a", "129", "1740"),
            ("114-94", "C", "32101", "26", "7345", "129", "1740"),
        ]
    )
    assert credits.lookup("114-94", "C", "32101").status == "multi_target"
    assert credits.lookup("114-94", "C", "99999").status == "absent"
    assert credits.lookup(None, "C", "32101").status == "no_key"
    assert credits.lookup("114-94", None, "32101").status == "no_key"


def test_a_resolution_states_an_identifier_or_a_reason_never_both() -> None:
    with pytest.raises(ValueError, match="never both or neither"):
        ActResolution(_citation("ERISA", "2"))
    with pytest.raises(ValueError, match="undeclared unresolved reason"):
        ActResolution(_citation("ERISA", "2"), unresolved_reason="because")
    with pytest.raises(ValueError, match="undeclared answering source"):
        ActResolution(_citation("ERISA", "2"), iri="urn:rkaf:us:usc:29:1001", answered_by="vibes")
    with pytest.raises(ValueError, match="undeclared source-credit status"):
        ActResolution(_citation("ERISA", "2"), unresolved_reason="act_not_in_index", source_credit_status="?")
    # A refusal reported by Table III must also come from the declared list:
    # the reason travels to consumers beside the published one.
    with pytest.raises(ValueError, match="undeclared Table III reason"):
        ActResolution(_citation("ERISA", "2"), unresolved_reason="act_not_in_index", table3_reason="huh")


def test_the_credit_vocabulary_is_closed_and_a_target_keeps_its_provenance() -> None:
    """Every status a consumer may see is declared, and none may be invented.

    A status outside :data:`SOURCE_CREDIT_STATUSES` would be a value no
    consumer can count, which is how "found several" quietly becomes "found
    nothing" downstream.
    """

    for status in SOURCE_CREDIT_STATUSES:
        assert SourceCreditAnswer(status=status).status == status
    with pytest.raises(ValueError, match="undeclared source-credit status"):
        SourceCreditAnswer(status="probably")

    target = SourceCreditTarget("29", "1021", "88", "840")
    assert (target.statutes_at_large_volume, target.statutes_at_large_page) == ("88", "840")
    # A target with no stated volume is representable; a missing one is not
    # invented as a default.
    assert SourceCreditTarget("29", "1021").statutes_at_large_volume is None


def test_a_source_verdict_never_states_both_an_answer_and_a_reason() -> None:
    """The invariant that lets the composer drop two unreachable branches."""

    with pytest.raises(ValueError, match="never both"):
        _Verdict(iri="urn:rkaf:us:usc:29:1001", reason="act_section_not_classified")
    assert _Verdict().iri is None and _Verdict().reason is None


def test_the_iri_space_is_the_contract_and_multi_letter_sections_are_in_it() -> None:
    """Real sections with long letter runs and several hyphen groups mint.

    Until 2026-08-22 the module allowed one trailing letter and one hyphen
    group, and so refused 616 real U.S. Code sections. All four below are
    live, currently-codified sections, and rkaf:us-usc has always permitted
    them — the narrowing was this module's, not the space's.
    """

    assert canonical_usc_iri("42", "7411") == "urn:rkaf:us:usc:42:7411"
    assert canonical_usc_iri("42", "300j-9") == "urn:rkaf:us:usc:42:300j-9"
    assert canonical_usc_iri("42", "2000bb") == "urn:rkaf:us:usc:42:2000bb"
    assert canonical_usc_iri("42", "300aa-11") == "urn:rkaf:us:usc:42:300aa-11"
    assert canonical_usc_iri("12", "2279aa-11") == "urn:rkaf:us:usc:12:2279aa-11"
    assert canonical_usc_iri("12", "1749bbb-10c") == "urn:rkaf:us:usc:12:1749bbb-10c"

    with pytest.raises(ValueError):
        canonical_usc_iri("5A", "101")  # an appendix title is not a number
    with pytest.raises(ValueError):
        canonical_usc_iri("42", "")
    with pytest.raises(ValueError):
        canonical_usc_iri("42", "1 nt")  # a note is not a section
    with pytest.raises(ValueError):
        canonical_usc_iri("15", "79 to 79z-6")  # a range is not a section


def test_a_leading_zero_on_a_section_refuses_rather_than_being_read_away() -> None:
    """The contract requires ``[1-9]``, and the old pattern minted outside it.

    A leading zero on the TITLE is spelling ("042 U.S.C." is Title 42). On the
    section it is not: the U.S. Code writes no section 0123, so reading it as
    123 would be inventing a citation. Both used to mint an identifier no
    Rulespec validator accepts.
    """

    assert canonical_usc_iri("042", "7411") == "urn:rkaf:us:usc:42:7411"
    with pytest.raises(ValueError):
        canonical_usc_iri("42", "0123")
    with pytest.raises(ValueError):
        canonical_usc_iri("0", "1")


def test_spelling_is_normalized_but_identity_is_not() -> None:
    """Case, padding and a leading zero are spelling; the section is not."""

    same = {
        canonical_usc_iri("42", "7411"),
        canonical_usc_iri("042", "7411"),
        canonical_usc_iri(" 42 ", " 7411 "),
        canonical_usc_iri("42", "7411"),
        canonical_usc_iri(42, "7411"),
    }
    assert same == {"urn:rkaf:us:usc:42:7411"}
    assert canonical_usc_iri("42", "300J-9") == "urn:rkaf:us:usc:42:300j-9"


def test_a_parenthetical_is_dropped_not_refused() -> None:
    """Pinned because it is a silent narrowing, not because it is obviously right.

    A caller who asks for "7411(a)" is handed the whole section. No row of
    either pinned table carries a parenthetical, so nothing depends on it
    today; if that changes, a subsection would quietly resolve to its parent
    and this test is where it shows up.
    """

    assert canonical_usc_iri("42", "7411(a)") == canonical_usc_iri("42", "7411")
    assert canonical_usc_iri("42", "7411(a)(2)(B)") == "urn:rkaf:us:usc:42:7411"


# --------------------------------------------------------------------------- #
# Real-artifact cases.


@artifact
def test_the_pinned_artifacts_load_and_carry_their_receipted_coverage(index, credits) -> None:
    assert len(index.table3_key_by_name) > 10_000
    assert len(credits.targets) > 0
    # The receipt's one quarantine row is a Table III page that could not be
    # read at build time, and it is distinguishable from "classifies nothing".
    assert len(index.incomplete_sources) == 1


@artifact
def test_the_pins_restate_the_receipts_they_are_meant_to_outrank() -> None:
    """Two copies of one digest, deliberately, held together by this test.

    Reading the pin FROM the receipt beside the tables would authenticate a
    swapped directory against its own paperwork, so the digests are restated
    in the module. That duplication only earns its keep if it is kept true.
    """

    receipted = {}
    for directory in (ACT_DIR, BULK_ACT_DIR, CREDIT_DIR):
        recorded = json.loads((directory / "receipt.json").read_text(encoding="utf-8"))
        receipted[directory.name] = {
            path.rsplit("/", 1)[-1]: meta["digest"] for path, meta in recorded["outputs"].items()
        }
    assert set(_ARTIFACT_PINS) == set(receipted)
    for artifact_name, pins in _ARTIFACT_PINS.items():
        for table, pin in pins.items():
            assert receipted[artifact_name][table] == pin, f"{artifact_name}/{table}"
        # Only the tables a loader reads are pinned; the quarantine files are not.
        assert set(pins) < set(receipted[artifact_name]), artifact_name


@artifact
def test_only_a_pinned_table_can_be_read_through_this_door() -> None:
    """The pin is the authentication, so an unpinned table has no way in."""

    assert (ACT_DIR / "quarantine.parquet").is_file()
    with pytest.raises(KeyError):
        _read_pinned_parquet(ACT_DIR, "quarantine.parquet")


@artifact
def test_a_drifted_artifact_refuses_to_load() -> None:
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "artifact"
        shutil.copytree(ACT_DIR, copy)
        target = copy / "usc-popular-names.parquet"
        target.write_bytes(target.read_bytes() + b" ")
        with pytest.raises(ValueError, match="pinned act artifact drifted"):
            ActIndex.from_artifact(copy)


@artifact
def test_the_two_act_indexes_differ_only_in_their_classifications() -> None:
    """What the artifact-keyed pins can and cannot tell apart, stated.

    The 2026-08-22 rebuild reads only Table III; its popular-name table is the
    08-02 one carried over byte for byte, and one digest is therefore pinned
    under both artifacts. So no digest check can distinguish the two builds by
    that table — there is nothing to distinguish — and the classifications
    table is the whole difference between them. This is why the loader does not
    pretend to catch a "mixed" directory: between these two artifacts, every
    mixture is byte-identical to one of them.
    """

    assert (ACT_DIR / "usc-popular-names.parquet").read_bytes() == (
        BULK_ACT_DIR / "usc-popular-names.parquet"
    ).read_bytes()
    assert (ACT_DIR / "usc-act-sections.parquet").read_bytes() != (
        BULK_ACT_DIR / "usc-act-sections.parquet"
    ).read_bytes()
    names = _ARTIFACT_PINS["usc-act-index-2026-08-02"]["usc-popular-names.parquet"]
    assert _ARTIFACT_PINS["usc-act-index-2026-08-22"]["usc-popular-names.parquet"] == names
    assert (
        _ARTIFACT_PINS["usc-act-index-2026-08-22"]["usc-act-sections.parquet"]
        != _ARTIFACT_PINS["usc-act-index-2026-08-02"]["usc-act-sections.parquet"]
    )


@artifact
def test_the_bulk_built_index_loads_through_the_same_door_and_carries_more(index) -> None:
    """The 2026-08-22 rebuild is read by this module unchanged.

    Same schema, same loader, same pins — and 15,189 Table III keys where the
    per-page build reached 24. Its receipt records no ``source_incomplete``,
    because Pub. L. 119-21 — the one page that build could not fetch — is in
    the bulk release.
    """

    bulk = ActIndex.from_artifact(BULK_ACT_DIR)
    assert bulk.table3_key_by_name == index.table3_key_by_name
    assert bulk.alias_by_name == index.alias_by_name
    assert len(bulk.classifications) == 15_189
    assert len(index.classifications) == 24
    assert bulk.incomplete_sources == frozenset()
    assert index.incomplete_sources == frozenset({"119-21"})
    assert "119-21" in bulk.classifications


@artifact
def test_a_directory_that_is_not_the_artifact_fails_loudly() -> None:
    """Both loaders read the receipt first, so a wrong directory raises rather
    than yielding an empty index that would look like a source with no
    coverage."""

    with tempfile.TemporaryDirectory() as scratch:
        empty = Path(scratch)
        with pytest.raises(FileNotFoundError):
            ActIndex.from_artifact(empty)
        with pytest.raises(FileNotFoundError):
            SourceCreditIndex.from_artifact(empty)


@artifact
def test_clean_air_act_section_111_resolves_from_the_real_tables(index, credits) -> None:
    resolution = resolve_act_relative_citation(
        _citation("Clean Air Act", "111"), index=index, source_credits=credits
    )
    assert resolution.iri == "urn:rkaf:us:usc:42:7411"
    # The Clean Air Act's Table III key is the 1955 session-law chapter, which
    # is not a public law key, so the credits had nothing to look under —
    # recorded, not silent.
    assert index.table3_key_by_name["clean air act"] == "1955:360"
    assert resolution.source_credit_status == "no_key"
    assert resolution.answered_by == "table3"


@artifact
def test_a_session_law_chapter_is_never_offered_to_the_credits(index) -> None:
    """1,921 of the index's 8,391 Table III keys pre-date public-law numbering.

    Public laws were numbered from the 85th Congress (1957); before that an
    act is identified by year and chapter, which the source credits — keyed by
    public law — cannot be looked up under. Handing them one would not find
    nothing, it would ask a question in the wrong language.
    """

    keys = set(index.table3_key_by_name.values())
    chapters = {k for k in keys if ":" in k}
    assert len(keys) == 8_391
    assert len(chapters) == 1_921
    assert "1955:360" in chapters  # Clean Air Act
    assert all(re.fullmatch(r"\d{4}:\d+", k) for k in chapters)


@artifact
def test_table_iii_always_states_an_identifier_or_a_reason(index) -> None:
    """The invariant that made two branches in the composer unreachable.

    Checked over EVERY (Table III key, act section) pair the artifact holds,
    not a sample: if any lookup could return silence, the composer would
    publish ``act_section_not_classified`` over a hole it never looked into.
    """

    act_by_key: dict[str, str] = {}
    for act_key, table3_key in index.table3_key_by_name.items():
        act_by_key.setdefault(table3_key, act_key)

    checked = 0
    reasons: collections.Counter[str] = collections.Counter()
    for table3_key, sections in index.classifications.items():
        act_key = act_by_key.get(table3_key, "")
        for section in sections:
            verdict = _resolve_through_table3(
                _citation(act_key, section), index, act_key, table3_key
            )
            checked += 1
            assert (verdict.iri is None) != (verdict.reason is None), (table3_key, section)
            if verdict.reason:
                assert verdict.reason in UNRESOLVED_REASONS
                reasons[verdict.reason] += 1
    assert checked == 9_916
    assert set(reasons) <= set(UNRESOLVED_REASONS)


@artifact
def test_every_answer_is_a_name_the_index_actually_keys(index, every_name) -> None:
    """An alias chain ends inside the index or nowhere. It never invents a key."""

    for name in every_name:
        answer = resolve_act_name(name, index)
        assert answer is None or answer in index.table3_key_by_name, name


@artifact
def test_resolution_is_deterministic_and_independent_of_call_order(index, every_name) -> None:
    """The derived stem map is a cache, so a wrong one would show as history.

    Resolving a miss first (which is what populates it) and a hit first must
    give the same answers, and repeating a call must not change one.
    """

    probe = ("Clean Air Act", "ERISA", "no such act at all", "Clean Water Act", "Insurrection Act")
    forward = [resolve_act_name(name, index) for name in probe]
    backward = [resolve_act_name(name, index) for name in reversed(probe)]
    assert forward == list(reversed(backward))
    assert forward == [resolve_act_name(name, index) for name in probe]

    fresh = ActIndex.from_artifact(ACT_DIR)
    assert [resolve_act_name(name, fresh) for name in probe] == forward
    assert {name: resolve_act_name(name, index) for name in every_name[:2_000]} == {
        name: resolve_act_name(name, fresh) for name in every_name[:2_000]
    }


@artifact
def test_the_longest_stated_chain_in_the_pinned_index_is_two_hops(index) -> None:
    """Measured headroom for :data:`ALIAS_MAX_DEPTH`.

    The bound is declared in the artifact's own receipt. This is what says the
    declared value is generous rather than lucky — and it breaks if a rebuild
    ever grows a chain that the bound would silently abandon.
    """

    def hops(name: str) -> int:
        seen: set[str] = set()
        current, walked = name, 0
        while current not in seen:
            seen.add(current)
            following = index.alias_by_name.get(current)
            if following is None:
                return walked
            current, walked = following, walked + 1
        return walked

    longest = max(hops(name) for name in index.alias_by_name)
    assert longest == 2
    assert longest < ALIAS_MAX_DEPTH


@artifact
def test_the_refusals_are_mostly_names_the_tool_does_list(index, every_name) -> None:
    """``act_not_in_index`` is true of 19 of the 107 names it is published for.

    This is the module's live mislabel, pinned here rather than left to be
    rediscovered. The tool CITES 63 of the refused names and simply publishes
    no Table III key for them — the Congressional Review Act, the
    Anti-Deficiency Act, the Paperwork Reduction Act among them. Separating
    these needs a new reason code, and the sealed receipt enumerates the
    vocabulary, so the split is a decision for a rebuild, not for this module
    alone.

    Was 115 until 2026-08-22, when two bounded fixes took eight of them: the
    four TeX-quoted names the tool stored behind a spelling no query could
    reach, and the four reachable through a leading article the tool wrote into
    its own cross-reference. The remaining 107 are source-side absences, and no
    amount of spelling closure moves them — see
    ``research/evidence/table3-coverage-2026-08-22.md`` §4.
    """

    rows = _read_pinned_parquet(ACT_DIR, "usc-popular-names.parquet")
    cited = {row["name_key"] for row in rows if row["content_type"] == "cite"}
    refused = {name for name in every_name if resolve_act_name(name, index) is None}
    assert len(refused) == 107

    census: collections.Counter[str] = collections.Counter()
    for name in refused:
        if normalize_popular_name(name) != name:
            census["cited-but-stored-unreachably"] += 1
        elif name in cited:
            census["cited-without-a-table3-key"] += 1
        elif name in index.alias_by_name:
            census["see-also-dead-ends"] += 1
        else:
            census["named-only-as-a-see-also-target"] += 1
    assert census == {
        "cited-without-a-table3-key": 63,
        "see-also-dead-ends": 25,
        "named-only-as-a-see-also-target": 19,
    }
    for listed in ("congressional review act", "anti-deficiency act", "paperwork reduction act"):
        assert listed in cited and listed in refused


@artifact
def test_every_name_the_index_keys_is_a_name_a_query_can_spell(index) -> None:
    """A join key must be a fixed point of the function that builds queries.

    Until 2026-08-22 four were not. ``normalize_popular_name`` stripped edge
    punctuation *before* straightening quotes, and OLRC writes four names with
    TeX quotes — ```` ``SPARS'' Act ```` — whose opening pair is two backticks
    that the edge-strip does not recognize. Straightening ran second and turned
    them into a leading ``''`` the same function would have stripped, so the
    key was ``''spars'' act`` and every query spelled ``spars'' act``. Three of
    the four carried a Table III key: acts the index could classify and no
    caller could ask for.

    Both halves of the repair are pinned here, because either alone is inert.
    The grammar now straightens first, and ``from_artifact`` normalizes the
    stored key on the way in rather than trusting the builder's copy of the
    normalizer.
    """

    assert [name for name in index.table3_key_by_name if normalize_popular_name(name) != name] == []
    assert [name for name in index.alias_by_name if normalize_popular_name(name) != name] == []

    for written, key in (
        ("``SPARS'' Act", "1941:8"),
        ("``Seeing-Eye'' Dogs on Railroads Act", "1937:432"),
        ("``Six Triple Eight'' Congressional Gold Medal Act of 2021", "117-97"),
    ):
        answered = resolve_act_name(written, index)
        assert answered == normalize_popular_name(written), written
        assert index.table3_key_by_name[answered] == key, written
    # The fourth carries no key of its own and reaches one through its stated
    # cross-reference, which is the tool speaking and not a spelling guess.
    assert resolve_act_name("``Kick-Back'' Racket Act", index) == "copeland anti-kickback act"


@artifact
def test_an_article_the_tool_wrote_into_its_own_cross_reference_is_spelling(index) -> None:
    """Four names, named — and the precedence that lets them through.

    OLRC writes "see The Vocational Rehabilitation Act" while its entry for
    that act carries no article, so the chain walk reached a name the tool
    lists and failed to recognize it. Stripping the article is tried only after
    every stated name has been checked verbatim, and still before a year is
    supplied: dropping a word the act's own entry does not use is reading the
    source, and supplying a year is inferring past it.
    """

    for name, act, key in (
        ("the vocational rehabilitation act", "vocational rehabilitation act", "1920:219"),
        ("the 911 modernization act", "911 modernization act", "110-53"),
        # Two more arrive through a stated chain that dead-ends at one of those.
        ("fess-kenyon act", "vocational rehabilitation act", "1920:219"),
        ("improving emergency communications act of 2007", "911 modernization act", "110-53"),
    ):
        assert resolve_act_name(name, index) == act, name
        assert index.table3_key_by_name[act] == key, name

    # The strip never outranks a name the tool lists outright. "The Clean Air
    # Act" and "Clean Air Act" are both spellings of one act, and the verbatim
    # pass is what answers when the tool lists the article-bearing form.
    listed_with_article = [name for name in index.table3_key_by_name if name.startswith("the ")]
    assert listed_with_article
    for name in listed_with_article:
        assert resolve_act_name(name, index) == name, name


@artifact
def test_the_article_strip_moves_exactly_four_names_and_nothing_else(index, every_name) -> None:
    """The blast radius, measured over every name the tool writes.

    A repair that quietly re-answered a name the tool already answered would be
    a regression wearing a fix. The pre-fix resolver is re-implemented here as
    an oracle rather than imported, since importing the thing under replacement
    would compare it with itself.
    """

    def resolve_before(name: str) -> str | None:
        chain = stated_name_chain(name, index)
        for step in chain:
            if step in index.table3_key_by_name:
                return step
        for step in chain:
            supplied = index.acts_supplying_year.get(step, ())
            if len(supplied) == 1:
                return supplied[0]
        return None

    moved = {name: (resolve_before(name), resolve_act_name(name, index)) for name in every_name}
    changed = {name: pair for name, pair in moved.items() if pair[0] != pair[1]}
    assert all(before is None for before, _ in changed.values()), "no name that answered before answers differently"
    assert sorted(changed) == [
        "fess-kenyon act",
        "improving emergency communications act of 2007",
        "the 911 modernization act",
        "the vocational rehabilitation act",
    ]


@artifact
def test_the_minted_space_is_the_contract_verbatim() -> None:
    """:data:`_RKAF_USC_IRI` restates rkaf. This holds the copy true.

    Reading the pattern out of the package at runtime would make the module
    agree with whatever shipped rather than with what was reviewed, so it is
    restated — and, like the artifact digests, restating only earns its keep
    if something breaks when the two drift. The contract is compiled into four
    forms and all four must carry the same pattern.
    """

    root = Path(rulespec_conformance.__file__).parent / "_data" / "compiled"
    stated = set()
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in {".json", ".ttl", ".ts", ".rego"}:
            continue
        stated.update(
            re.findall(r"\^urn:rkaf:us:usc:[^\"$\s]*\$", path.read_text(encoding="utf-8", errors="ignore"))
        )
    assert stated == {r"^urn:rkaf:us:usc:[1-9][0-9]*:[1-9][0-9]*[a-z]*(-[0-9a-z]+)*$"}, stated

    # The module's copy differs only by making the group non-capturing.
    assert _RKAF_USC_IRI.pattern.replace("(?:", "(") == next(iter(stated))


@artifact
def test_every_identifier_this_module_mints_satisfies_the_contract(index) -> None:
    """The property, over every classification in the artifact.

    6,236 of 7,522 distinct targets mint, and not one of them is an identifier
    Rulespec's own validators would reject.
    """

    contract = re.compile(next(iter({r"^urn:rkaf:us:usc:[1-9][0-9]*:[1-9][0-9]*[a-z]*(-[0-9a-z]+)*$"})))
    targets = {
        (row.usc_title, row.usc_section)
        for sections in index.classifications.values()
        for rows in sections.values()
        for row in rows
        if row.usc_title and row.usc_section
    }
    minted = refused = 0
    for title, section in targets:
        try:
            iri = canonical_usc_iri(title, section)
        except ValueError:
            refused += 1
        else:
            assert contract.fullmatch(iri), iri
            minted += 1
    assert (minted, refused, len(targets)) == (6_236, 1_286, 7_522)


@artifact
def test_what_the_space_still_cannot_express_is_a_gap_in_rkaf(index) -> None:
    """1,286 targets still refuse. None is a section; two kinds are citable.

    rkaf is ours, so this splits the leftovers by what would have to change:

    * **1,123 statutory notes** ("42 U.S.C. 1 nt", and five written "1401
      nts"). OLRC defines a statutory note as a provision set out following a
      section — a real, citable legal object that ``rkaf:us-usc`` has no
      production for. The largest gap.
    * **14 ranges** ("79 to 79z-6"). Also real; also unexpressible.
    * **127 positions** ("prec. 2161"), a chapter heading's location rather
      than an identifier — arguably nothing to fix.
    * **22 comma-separated lists** ("2151w, 2221, 2222, …"). Not a space
      defect at all: the artifact builder stored several sections in a scalar
      column. That one belongs to the builder.

    Nothing falls outside these four, which is the point of asserting the
    census rather than a total: a leftover with no name is a leftover nobody
    has looked at.

    Refusing all four is right — none names one section. What is coarse is
    that they share one reason code, so a consumer cannot tell an rkaf gap
    from a builder defect.
    """

    targets = {
        (row.usc_title, row.usc_section)
        for sections in index.classifications.values()
        for rows in sections.values()
        for row in rows
        if row.usc_title and row.usc_section
    }
    census: collections.Counter[str] = collections.Counter()
    for title, section in targets:
        try:
            canonical_usc_iri(title, section)
        except ValueError:
            body = section.strip().lower()
            tokens = re.split(r"[\s.]+", body)
            if "nt" in tokens or "nts" in tokens:
                census["a-statutory-note"] += 1
            elif body.startswith("prec"):
                census["a-position"] += 1
            elif " to " in body:
                census["a-range"] += 1
            elif "," in body:
                census["several-sections-in-one-column"] += 1
            else:
                census["uncategorised"] += 1
    assert census == {
        "a-statutory-note": 1_123,
        "a-position": 127,
        "several-sections-in-one-column": 22,
        "a-range": 14,
    }
    assert sum(census.values()) == 1_286


@artifact
def test_act_section_not_classified_is_mostly_never_fetched(index) -> None:
    """The module's commonest refusal is a false absence, and here is its size.

    The act-sections table holds Table III's classifications for **24 laws**.
    The popular-name index names 8,391. So for 12,695 of its 12,963 cited
    acts, "the section is not classified" is not something OLRC said — it is
    the shape of a build that requested 27 pages and reached 24. That is the
    single largest mislabel in this module: 534 of the 752 pairs the Unified
    Agenda corpus produces refuse under this code, and almost all of them
    refuse because nobody asked.

    Nothing needs to be inferred to tell the two apart: a key absent from
    ``classifications`` was never fetched, and the receipt's ``acts_reached``
    agrees exactly with how many keys are present. Separating them needs a
    reason code the sealed receipt does not enumerate, so it is a decision for
    a rebuild — but the number belongs on the record either way.
    """

    receipt = json.loads((ACT_DIR / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["coverage"]["acts_reached"] == 24
    assert receipt["coverage"]["acts_requested"] == 27
    assert len(index.classifications) == 24, "the fetched set IS the classified set"

    keys = set(index.table3_key_by_name.values())
    assert len(keys) == 8_391
    assert len(keys & set(index.classifications)) == 24

    fetched = sum(1 for key in index.table3_key_by_name.values() if key in index.classifications)
    assert (fetched, len(index.table3_key_by_name) - fetched) == (268, 12_695)

    # The Clean Water Act's own law is among the unfetched, so every section of
    # it refuses as "not classified" — an absence this build never tested.
    fwpca = index.table3_key_by_name["federal water pollution control act"]
    assert fwpca == "1948:758" and fwpca not in index.classifications
    resolution = resolve_act_relative_citation(
        _citation("Federal Water Pollution Control Act", "301"), index=index
    )
    assert resolution.unresolved_reason == "act_section_not_classified"


@artifact
def test_the_appendix_to_title_five_is_a_real_place(index) -> None:
    """Five rows classify to "5 App." with no section. Real, and mislabelled.

    The Appendix to Title 5 is where the Inspector General Act, the Federal
    Advisory Committee Act and the Ethics in Government Act lived until the
    2022 recodification (which is what the "Rev. T." status on four of them
    records). So the module is right to publish no identifier — ``5 App.`` is
    not a number and ``rkaf:us-usc`` cannot spell it — but the reason it would
    give, ``act_section_not_classified``, asserts an absence that is false.
    Every one of the five reaches a different branch first, so nothing is
    mislabelled today; this pins the shape so a rebuild that changes which
    branch wins is visible.
    """

    appendix = [
        (key, section, row)
        for key, sections in index.classifications.items()
        for section, rows in sections.items()
        for row in rows
        if row.usc_title and not row.usc_section
    ]
    assert len(appendix) == 5
    assert {row.usc_title for _, _, row in appendix} == {"5 App."}
    assert sum(1 for _, _, row in appendix if row.status == "Rev. T.") == 4
    with pytest.raises(ValueError):
        canonical_usc_iri("5 App.", "8G")

    for act_key, table3_key in index.table3_key_by_name.items():
        for key, section, _ in appendix:
            if table3_key != key:
                continue
            verdict = _resolve_through_table3(_citation(act_key, section), index, act_key, key)
            assert verdict.reason in {
                "classification_not_current",
                "act_section_ambiguous",
                "act_section_outside_act",
            }, (key, section, verdict.reason)


@artifact
def test_one_credit_target_never_hides_two_pages(credits) -> None:
    """``lookup`` reads ``found[0]``'s provenance. That must not be a choice.

    Where several rows agree on the section, they must also agree on where in
    the Statutes at Large it was enacted — otherwise taking the first would be
    picking, which is the one thing this module does not do.
    """

    picked = 0
    for targets in credits.targets.values():
        if len({(t.usc_title, t.usc_section) for t in targets}) > 1:
            continue  # refused as multi_target before provenance is read
        if len({(t.statutes_at_large_volume, t.statutes_at_large_page) for t in targets}) > 1:
            picked += 1
    assert picked == 0
    assert len(credits.targets) == 2_202
    assert sum(
        1
        for targets in credits.targets.values()
        if len({(t.usc_title, t.usc_section) for t in targets}) > 1
    ) == 325


@artifact
def test_the_credits_key_needs_a_division_and_lose_nothing_by_it(credits) -> None:
    """The asymmetry between the two sources, measured rather than assumed.

    A citation with no division has no key here at all. That would be a
    coverage hole if any credit row lacked a division, or if any law they
    cover were absent from Table III. Neither is true, so ``no_key`` is a
    statement about the question, never about the source.
    """

    rows = _read_pinned_parquet(CREDIT_DIR, "usc-source-credits.parquet")
    assert len(rows) == 3_721
    assert all(row["division"] and row["public_law"] for row in rows)
    assert len({row["public_law"] for row in rows}) == 109


@artifact
def test_every_resolution_over_the_real_tables_keeps_its_contract(index, credits, every_name) -> None:
    """The whole pipeline, over a wide real slice: every published field legal.

    ``ActResolution`` enforces its own invariants, so this is really a test
    that the resolver can be driven over real data without ever constructing
    an illegal one — and a census of what the two sources actually do.
    """

    census: collections.Counter[str] = collections.Counter()
    for name in every_name[:400]:
        act_key = resolve_act_name(name, index)
        sections = ("1", "101", "2", "999999")
        if act_key is not None:
            sections = sections + tuple(
                sorted(index.classifications.get(index.table3_key_by_name[act_key], {}))[:6]
            )
        for section in sections:
            resolution = resolve_act_relative_citation(
                _citation(name, section), index=index, source_credits=credits
            )
            assert (resolution.iri is None) != (resolution.unresolved_reason is None)
            assert resolution.unresolved_reason in (None, *UNRESOLVED_REASONS)
            assert resolution.answered_by in (None, *ANSWERING_SOURCES)
            assert resolution.source_credit_status in SOURCE_CREDIT_STATUSES
            assert resolution.citation.section == section
            census[resolution.answered_by or f"refused:{resolution.unresolved_reason}"] += 1
    assert census["table3"] > 0
    assert census["refused:act_not_in_index"] > 0
    assert sum(census.values()) > 1_500


#: Real ``(act_key, act_section)`` pairs lifted from the Unified Agenda build's
#: legal-authority table — the only real-world corpus this module's answers can
#: be measured against, since nothing in the tree calls it yet. The heaviest
#: pair of every outcome the corpus produces, with the number of authority rows
#: that carried it. They are pinned as SPECIMENS rather than as a census of the
#: live artifact: that artifact belongs to the agenda builder, is rebuilt
#: independently, and its ``act_section`` column still carries fragments of the
#: act's own name ("social security act" section "urity"). What must not drift
#: is the answer this module gives a fixed question, which the digest-pinned
#: OLRC tables fully determine.
DOWNSTREAM_SPECIMENS = (
    (655, "clean air act", "112", "urn:rkaf:us:usc:42:7412", "table3"),
    (238, "erisa", "505", "urn:rkaf:us:usc:29:1135", "table3"),
    (196, "clean air act", "111", "urn:rkaf:us:usc:42:7411", "table3"),
    (169, "social security act", "1102", "urn:rkaf:us:usc:42:1302", "table3"),
    (7, "pipes act of 2020", "103", "urn:rkaf:us:usc:49:60303", "source_credits"),
    (6, "secure 2.0 act of 2022", "303", "urn:rkaf:us:usc:29:1153", "source_credits"),
    (444, "clean air act", "", None, "act_section_not_classified"),
    (101, "social security act", "1886", "urn:rkaf:us:usc:42:1395ww", "table3"),
    (13, "faa reauthorization act of 2018", "427", None, "usc_section_not_expressible"),
    (6, "secure 2.0 act of 2022", "120", None, "act_section_outside_act"),
    (2, "one big beautiful bill act", "70204", None, "source_incomplete"),
    (2, "obra", "13622", None, "act_not_in_index"),
)


@artifact
@pytest.mark.parametrize(("weight", "act_key", "section", "iri", "outcome"), DOWNSTREAM_SPECIMENS)
def test_a_real_downstream_citation_resolves_the_way_it_did(
    index, credits, weight, act_key, section, iri, outcome
) -> None:
    """One pinned answer per outcome the real corpus produces.

    ``weight`` is how many Unified Agenda authority rows carried that pair, so
    a broken specimen states its own blast radius.
    """

    assert weight > 0
    resolution = resolve_act_relative_citation(
        ActRelativeCitation(act_name=act_key, act_key=act_key, section=section),
        index=index,
        source_credits=credits,
    )
    assert resolution.iri == iri
    assert (resolution.answered_by or resolution.unresolved_reason) == outcome


@artifact
def test_every_pair_the_agenda_produced_keeps_its_contract(index, credits) -> None:
    """The whole live corpus, checked for contract rather than for a count.

    The corpus itself is another module's output and moves when that module is
    rebuilt, so nothing here pins its size. What is pinned is that this module
    can be driven over all of it without producing a resolution that states
    both an identifier and a reason, or neither, or a code no consumer
    declares — and that the answers still come overwhelmingly from Table III.
    """

    import pyarrow.parquet as pq

    agenda = (
        ROOT
        / "output/registry-real-data-sources/unified-agenda-parquet"
        / "unified_agenda_legal_authorities.parquet"
    )
    if not agenda.is_file():
        pytest.skip("the unified agenda artifact is not present")

    table = pq.read_table(agenda, columns=["act_key", "act_section"])
    pairs = sorted(
        {
            (key, section or "")
            for key, section in zip(
                table.column("act_key").to_pylist(),
                table.column("act_section").to_pylist(),
                strict=True,
            )
            if key
        }
    )
    assert len(pairs) > 500

    census: collections.Counter[str] = collections.Counter()
    for act_key, section in pairs:
        resolution = resolve_act_relative_citation(
            ActRelativeCitation(act_name=act_key, act_key=act_key, section=section),
            index=index,
            source_credits=credits,
        )
        assert (resolution.iri is None) != (resolution.unresolved_reason is None)
        assert resolution.unresolved_reason in (None, *UNRESOLVED_REASONS)
        assert resolution.answered_by in (None, *ANSWERING_SOURCES)
        census[resolution.answered_by or f"refused:{resolution.unresolved_reason}"] += 1

    answered = census["table3"] + census["source_credits"] + census["both"]
    assert census["table3"] > 100
    assert census["table3"] > census["source_credits"], "Table III carries this corpus"
    assert answered > 150


@artifact
def test_the_four_names_where_a_stated_reference_and_a_year_both_offer_an_answer(index) -> None:
    """Every real case of the precedence, read off the pinned popularnames.htm.

    Four names in the whole index have both a cross-reference and a supplyable
    year. The tool's own words (``content_type`` "see"/"renamed", with the
    target in ``see_also``) settle three of them; the fourth points at a place
    rather than an act, and the year answers it.
    """

    assert index.alias_by_name["clean water act"] == "federal water pollution control act"
    assert index.acts_supplying_year["clean water act"] == ("clean water act of 1977",)
    assert resolve_act_name("Clean Water Act", index) == "federal water pollution control act"

    assert index.alias_by_name["anti-kickback act"] == "copeland anti-kickback act"
    assert index.acts_supplying_year["anti-kickback act"] == ("anti-kickback act of 1986",)
    assert resolve_act_name("Anti-Kickback Act", index) == "copeland anti-kickback act"

    # Right answer, and now for the stated reason rather than by falling
    # through an ambiguous year.
    assert index.alias_by_name["internal revenue code"] == "internal revenue code of 1939"
    assert len(index.acts_supplying_year["internal revenue code"]) == 2
    assert resolve_act_name("Internal Revenue Code", index) == "internal revenue code of 1939"

    # The cross-reference names a location in the Code, not an act, so it
    # leads nowhere and the year is supplied.
    assert index.alias_by_name["insurrection act"] == "title 10, chapter 13 (sec. 251 et seq"
    assert resolve_act_name("Insurrection Act", index) == "insurrection act of 1807"

    both = [
        name
        for name in index.alias_by_name
        if name not in index.table3_key_by_name and name in index.acts_supplying_year
    ]
    assert sorted(both) == [
        "anti-kickback act",
        "clean water act",
        "insurrection act",
        "internal revenue code",
    ]


@artifact
def test_a_typo_in_the_tools_own_cross_reference_refuses(index) -> None:
    """"Canal Zone Code — see Panana Canal Code". The Code is real; the
    spelling is not, and this module does not repair it.

    A near-miss is the most tempting place to guess: one edit away sits an
    entry that resolves. Refusing keeps the fence where doctrine puts it.
    """

    assert index.alias_by_name["canal zone code"] == "panana canal code"
    assert resolve_act_name("panama canal code", index) == "panama canal code"
    assert resolve_act_name("Canal Zone Code", index) is None


@artifact
def test_a_cross_reference_naming_two_acts_is_not_one_act(index) -> None:
    """"Lea-Wagner Act — see Investment Advisers Act of 1940; Investment
    Company Act of 1940" names TWO acts, and refuses.

    Splitting the target on the semicolon looks like recovery — both halves
    resolve, and both carry Table III key 1940:686. But one public law
    enacting two acts is exactly the situation the division rule exists for:
    same key, different acts. Taking the first would be picking one, and this
    records that the recovery was measured and rejected.
    """

    target = index.alias_by_name["lea-wagner act"]
    assert target == "investment advisers act of 1940; investment company act of 1940"
    halves = [half.strip() for half in target.split(";")]
    assert [resolve_act_name(half, index) for half in halves] == halves
    assert len({index.table3_key_by_name[half] for half in halves}) == 1, "one law"
    assert len(set(halves)) == 2, "two acts"
    assert resolve_act_name("Lea-Wagner Act", index) is None
