"""The router answers what a handed term is, or says exactly why it cannot.

A wrong result list wastes an afternoon, but a wrong definition gets quoted
into a supplier letter or a filing, so a definitional answer is a claim about
the world and the verification bar here is stricter than the other readers'.
``test_every_named_part_says_so_in_the_publishers_own_words`` checks the
router's output against the publisher's RAW note text rather than the citation
parse that produced it, because verifying a parse against itself is circular
and would pass on the day the parse breaks.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

from refspec.registry.act_resolution import ActIndex
from refspec.registry.cfr_authority_notes import CFR_AUTHORITY_NOTES_ARTIFACT, CfrAuthorityNotes
from refspec.registry.term_explanation import (
    EXPLANATION_KINDS,
    RIN_CONTAINER_THRESHOLD,
    UNEXPLAINED_REASONS,
    DocketDocument,
    RinSubject,
    TermExplanation,
    acts_classifying,
    explain_term,
    parts_naming,
)

ROOT = Path(__file__).resolve().parents[1]
ACT_INDEX = ROOT / "output" / "usc-act-index-2026-08-22"
artifact = pytest.mark.pinned_input(not ACT_INDEX.is_dir(), reason="the sealed act index is not present")


@pytest.fixture(scope="module")
def index() -> ActIndex:
    """The sealed USC act index, loaded from the pinned artifact directory."""

    return ActIndex.from_artifact(ACT_INDEX)


@pytest.fixture(scope="module")
def notes() -> CfrAuthorityNotes:
    """The pinned eCFR authority-note cache, loaded from the repository root."""

    return CfrAuthorityNotes.from_repository(ROOT)


@pytest.fixture(scope="module")
def raw_notes() -> dict[tuple[str, str], str]:
    """The publisher's note text, read straight from the pinned file.

    The oracle for the check below. Deliberately NOT `CfrAuthorityNotes`: the
    router reaches its answer through that reader's citation parse, so asking
    the same object to confirm the answer would be one implementation agreeing
    with itself.
    """

    out: dict[tuple[str, str], str] = {}
    for line in (ROOT / CFR_AUTHORITY_NOTES_ARTIFACT).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        out[(str(record["cfr_title"]), str(record["cfr_part"]))] = record.get("authority_note") or ""
    return out


def test_an_explanation_carries_a_statement_or_a_reason_and_never_both() -> None:
    """The contract `ActResolution` keeps, kept here for the same reason."""

    with pytest.raises(ValueError, match="never both or neither"):
        TermExplanation(text="x")
    with pytest.raises(ValueError, match="never both or neither"):
        TermExplanation(text="x", statement="a", unexplained_reason="unrecognised_shape")
    with pytest.raises(ValueError, match="undeclared reason"):
        TermExplanation(text="x", unexplained_reason="invented")
    with pytest.raises(ValueError, match="undeclared kind"):
        TermExplanation(text="x", kind="invented", unexplained_reason="unrecognised_shape")


@artifact
def test_the_manufacturers_term_answers(index, notes) -> None:
    """The worst session in the 2026-09-06 persona run, in one line.

    A supplier's letter said "Section 232". The product returned nothing all
    night. This is the answer it should have given, and the value of the whole
    item is that this sentence is right rather than that it is long.
    """

    answer = explain_term("Section 232 of the Trade Expansion Act of 1962", index=index, notes=notes)
    assert answer.kind == "act_section"
    assert answer.subject == "urn:rkaf:us:usc:19:1862"
    assert "19 U.S.C. 1862" in answer.statement
    assert "15 CFR 705" in answer.statement


@artifact
def test_the_router_does_not_say_a_part_implements_a_section(index, notes) -> None:
    """Unsolved rule two, and the failure this module exists to prevent.

    Asked about Clean Air Act section 111, a router that said "implemented by"
    would answer 40 CFR 72, "Permits Regulation" -- because exactly one note
    names 42 U.S.C. 7411 and it is not the new-source performance standards
    part. 40 CFR 60 IS that part and its note reads "42 U.S.C. 7401 et seq.",
    naming the chapter and never the section. So the sentence may only say what
    the note SAYS, and must carry the caveat that a chapter-level note does not
    appear.
    """

    answer = explain_term("Clean Air Act section 111", index=index, notes=notes)
    assert "42 U.S.C. 7411" in answer.statement
    assert "40 CFR 72" in answer.statement
    assert "implement" not in answer.statement.lower()
    assert "cites the chapter rather than the section" in answer.statement
    # The specimen that makes the caveat necessary rather than decorative.
    assert "40 CFR 60" not in answer.naming_parts
    assert "et seq" in (notes.note(40, "60").authority_note or "")


@artifact
def test_a_withheld_attribution_says_so_in_the_sentence(index, notes) -> None:
    """Unsolved rule one. Several acts classify one authority; none is named.

    Withholding silently is not enough: a reader cannot tell an attribution
    that was withheld from one nobody looked for, so the count is stated.
    """

    answer = explain_term("40 CFR 60", index=index, notes=notes)
    assert answer.kind == "cfr_part"
    assert "STANDARDS OF PERFORMANCE" in answer.statement
    assert len(answer.candidate_acts) > 1
    assert "does not attribute it to one" in answer.statement
    assert all(key not in answer.statement for key in answer.candidate_acts)


@artifact
def test_a_single_classifying_act_is_named(index, notes) -> None:
    """The positive fixture for rule one: withholding must not be unconditional.

    A guard that refuses every attribution is not a guard, it is a silence, so
    this asserts that an unambiguous authority IS attributed.
    """

    singles = [
        part
        for part in notes.coverage()[:400]
        if (note := notes.note(*part)) is not None
        and len({
            act
            for citation in note.citations
            if citation.family == "usc"
            for act in acts_classifying(*citation.identity.split(":", 1), index)
        }) == 1
    ]
    assert singles, "no single-act part in the scanned window; the fixture has gone vacuous"
    answer = explain_term(f"{singles[0][0]} CFR {singles[0][1]}", index=index, notes=notes)
    assert "classified from one act" in answer.statement


@artifact
def test_every_named_part_says_so_in_the_publishers_own_words(index, notes, raw_notes) -> None:
    """THE VERIFICATION BAR. Checked against raw note text, not against the parse.

    A definition asserts a fact about the world. So every part the router names
    for a drawn sample of act sections must contain that section number in the
    publisher's own note, read from the pinned bytes rather than from the
    reader that produced the answer. A sample rather than a census because the
    act index holds 15,189 keys; seeded so a failure is reproducible.
    """

    rng = random.Random(20260907)
    keys = rng.sample(sorted(index.classifications), 400)
    checked = 0
    for key in keys:
        for section, rows in list(index.classifications[key].items())[:3]:
            for row in rows[:2]:
                named = parts_naming(row.usc_title, row.usc_section, notes)
                for part in named:
                    title, _, number = part.partition(" CFR ")
                    text = raw_notes[(title.strip(), number.strip())]
                    assert re.search(rf"\b{re.escape(str(row.usc_section))}\b", text), (
                        f"{part} was named for {row.usc_title} U.S.C. {row.usc_section}, "
                        f"and the publisher's note does not contain it: {text[:160]!r}"
                    )
                    checked += 1
            _ = section
    # 645 at the sample this pins. The floor is what stops a future narrowing
    # of the draw from turning the bar into a formality that still passes.
    assert checked >= 400, f"only {checked} named parts drawn; the bar is not exercising the claim"


@artifact
def test_a_container_rule_number_refuses_and_an_ordinary_one_answers(index, notes) -> None:
    """One ambiguity rule at the scope where it swallows the subject.

    2120-AA66 carries 3,561 Federal Register documents across three types and
    twenty-six years: an FAA airspace container, not a rulemaking. Returning
    its first or latest document would be a real document and confidently not
    the answer. Rare and enormous is the worst combination, so this is a
    declared guard rather than something a sample would have found.
    """

    def subject(rin: str) -> RinSubject | None:
        if rin == "2120-AA66":
            return RinSubject("Airspace", "FAA", "Final Rule", "federal_register", 3_561)
        return RinSubject("Oil and Natural Gas Sector Climate Review", "EPA", "Final Rule", "unified_agenda", 5)

    container = explain_term("RIN 2120-AA66", index=index, notes=notes, rin_subject=subject)
    assert container.unexplained_reason == "identifier_covers_several_rulemakings"
    ordinary = explain_term("RIN 2060-AV12", index=index, notes=notes, rin_subject=subject)
    assert "Oil and Natural Gas" in ordinary.statement
    assert "unified_agenda" in ordinary.statement, "the answering table must be named, since coverage differs"
    assert RIN_CONTAINER_THRESHOLD < 3_561


@artifact
def test_a_rin_with_no_resolver_names_the_lane_that_owns_it(index, notes) -> None:
    """Ownership stated rather than guessed: the subject is not this repo's."""

    answer = explain_term("RIN 2060-AV12", index=index, notes=notes)
    assert answer.kind == "rin"
    assert answer.unexplained_reason == "rin_subject_not_owned_here"


@artifact
def test_a_docket_gets_its_arc_and_an_unknown_one_says_so(index, notes) -> None:
    """For 109,442 dockets the answer is an arc rather than a definition."""

    def documents(docket: str) -> list[DocketDocument]:
        if not docket.startswith("EPA"):
            return []
        return [
            DocketDocument("2024-08-01", "Rule", "Standards of Performance"),
            DocketDocument("2021-11-15", "Proposed Rule", "Standards of Performance"),
        ]

    arc = explain_term("EPA-HQ-OAR-2021-0317", index=index, notes=notes, docket_documents=documents)
    assert arc.kind == "docket"
    assert "an EPA docket" in arc.statement
    assert arc.documents[0].published == "2021-11-15", "the arc must run oldest first"
    assert "2 documents" in arc.statement
    empty = explain_term("FDA-2011-V-0020", index=index, notes=notes, docket_documents=documents)
    assert "No document in this corpus cites it" in empty.statement
    assert explain_term("EPA-HQ-OAR-2021-0317", index=index, notes=notes).unexplained_reason == (
        "docket_documents_not_supplied"
    )


@artifact
def test_what_the_router_refuses(index, notes) -> None:
    """The negative fixtures. A router that reads everything reads nothing."""

    assert explain_term("haddock", index=index, notes=notes).unexplained_reason == "unrecognised_shape"
    assert explain_term("", index=index, notes=notes).unexplained_reason == "unrecognised_shape"
    assert explain_term("40 CFR 99999", index=index, notes=notes).unexplained_reason == "cfr_part_not_in_cache"
    unknown = explain_term("Section 4 of the Fictional Widgets Act of 1902", index=index, notes=notes)
    assert unknown.unexplained_reason == "act_unresolved"
    assert unknown.candidate_acts[0] in {
        "act_not_in_index",
        "act_listed_without_classification",
        "act_alias_target_not_listed",
    }, "the three-way absence code must survive the hop rather than being flattened"


def test_the_declared_vocabularies_are_closed() -> None:
    """Every declared reason and kind is reachable, or it is decoration."""

    assert set(EXPLANATION_KINDS) == {"act_section", "cfr_part", "docket", "rin"}
    assert len(set(UNEXPLAINED_REASONS)) == len(UNEXPLAINED_REASONS)
