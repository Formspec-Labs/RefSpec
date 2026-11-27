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
import time
from pathlib import Path

import pytest

from refspec.registry.act_resolution import ActIndex
from refspec.registry.cfr_authority_notes import CFR_AUTHORITY_NOTES_ARTIFACT, CfrAuthorityNotes
from refspec.registry.ferc_elibrary_codes import (
    FERC_DOCKET_PREFIX_PDF_EDITION,
    FERC_DOCKET_PREFIX_PDF_SHA256,
    FERC_DOCKET_PREFIX_PDF_URL,
    FERC_PUBLISHER,
    FercPublishedDocketPrefixCapture,
    load_packaged_ferc_docket_prefixes,
)
from refspec.registry.term_explanation import (
    EXPLANATION_KINDS,
    RIN_CONTAINER_THRESHOLD,
    UNEXPLAINED_REASONS,
    DocketDocument,
    FercDocketPrefixExplanation,
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

    assert set(EXPLANATION_KINDS) == {"act_section", "cfr_part", "docket", "ferc_docket", "rin"}
    assert "ferc_docket_prefix_unknown" in UNEXPLAINED_REASONS
    assert len(set(UNEXPLAINED_REASONS)) == len(UNEXPLAINED_REASONS)


@pytest.mark.parametrize(
    ("term", "expected_subject", "expected_prefix", "expected_library", "expected_definition"),
    [
        (
            "Docket No. CP26-20-000",
            "CP26-20-000",
            "CP",
            "G",
            "Certificates for Interstate Natural Gas Pipeline Companies",
        ),
        (
            "CP26-20-000",
            "CP26-20-000",
            "CP",
            "G",
            "Certificates for Interstate Natural Gas Pipeline Companies",
        ),
        (
            "docket no. cp26\u201320\u2013000",
            "CP26-20-000",
            "CP",
            "G",
            "Certificates for Interstate Natural Gas Pipeline Companies",
        ),
        ("ER24-1234-000", "ER24-1234-000", "ER", "E", "Electric Rate Filings"),
        ("EL23-45", "EL23-45", "EL", "E", "Miscellaneous Formal Filings Related to Electric Power"),
        (
            "Docket No.EL02-65-005",
            "EL02-65-005",
            "EL",
            "E",
            "Miscellaneous Formal Filings Related to Electric Power",
        ),
        ("RM22-10-000", "RM22-10-000", "RM", "Gen, RM", "Rulemaking Proceedings"),
        ("RP24-500-000", "RP24-500-000", "RP", "G", "Rates for Interstate Natural Gas Pipeline Companies"),
        ("AD10-12-017", "AD10-12-017", "AD", "Gen", "Administrative"),
        (
            "ZZ26-20-000",
            "ZZ26-20-000",
            "ZZ",
            "E, G, H, O",
            "Tracking Docket for Certain Non-Docketed Submissions",
        ),
    ],
)
def test_ferc_standard_dockets_route_labeled_and_bare_to_authoritative_directory(
    term: str,
    expected_subject: str,
    expected_prefix: str,
    expected_library: str,
    expected_definition: str,
) -> None:
    """REF-070 unblocked: FERC dockets route offline to the pinned 95-row directory."""

    answer = explain_term(term)
    assert answer.kind == "ferc_docket"
    assert answer.subject == expected_subject
    assert answer.unexplained_reason is None
    assert answer.ferc_docket_prefix == FercDocketPrefixExplanation(
        prefix=expected_prefix,
        status="active",
        library=expected_library,
        definition=expected_definition,
        publisher=FERC_PUBLISHER,
        source_edition=FERC_DOCKET_PREFIX_PDF_EDITION,
        source_url=FERC_DOCKET_PREFIX_PDF_URL,
        source_sha256=FERC_DOCKET_PREFIX_PDF_SHA256,
    )
    assert answer.statement is not None
    assert expected_subject in answer.statement
    assert f"active prefix {expected_prefix}" in answer.statement
    assert expected_definition in answer.statement
    assert f"library {expected_library}" in answer.statement
    assert FERC_DOCKET_PREFIX_PDF_EDITION in answer.statement


@pytest.mark.parametrize(
    ("term", "expected_subject", "expected_prefix", "expected_status", "expected_definition"),
    [
        ("P-1234-000", "P-1234-000", "P", "active", "Hydropower Projects"),
        ("Docket No. P-1234-000", "P-1234-000", "P", "active", "Hydropower Projects"),
        ("Project No. P-2725-076", "P-2725-076", "P", "active", "Hydropower Projects"),
        ("FERC Project No. P-1234", "P-1234", "P", "active", "Hydropower Projects"),
        (
            "Docket No. IC26-25-000",
            "IC26-25-000",
            "IC",
            "active",
            (
                "Information Collections – Public Involvement on the Development of the "
                "Commission's Information Collection Requirements Prior to OMB Approval"
            ),
        ),
        (
            "HB26-01-0-00",
            "HB26-01-0-00",
            "HB",
            "active",
            "Headwater Benefits Related to Hydroelectric Projects",
        ),
        (
            "FERC Docket No. HB26-1-000",
            "HB26-1-000",
            "HB",
            "active",
            "Headwater Benefits Related to Hydroelectric Projects",
        ),
        (
            "FERC Docket No. ID-8705-002",
            "ID-8705-002",
            "ID",
            "active",
            "Interlocking Directorates for Electric Utilities",
        ),
        (
            "PT26-20-000",
            "PT26-20-000",
            "PT",
            "active",
            (
                "Prefilling Activity for a Permit to Site New Electric Transmission Facilities "
                "or Modify Existing Facilities"
            ),
        ),
        (
            "TA90-1-000",
            "TA90-1-000",
            "TA",
            "discontinued",
            "Annual Tracking Filings of Interstate Natural Gas Pipelines",
        ),
        (
            "Docket No. CI80-123-000",
            "CI80-123-000",
            "CI",
            "discontinued",
            "Certificates for Small Independent Natural Gas Producers & Marketers",
        ),
        (
            "FERC Docket No. E-7890",
            "E-7890",
            "E-",
            "discontinued",
            "All Electric Cases (Replaced by ER, ES, EL, etc. prefixes)",
        ),
        (
            "FERC Docket No. G-1234",
            "G-1234",
            "G-",
            "discontinued",
            "Gas Cases – Used Prior to 1960",
        ),
        (
            "FERC Docket No. R-456",
            "R-456",
            "R-",
            "discontinued",
            "Rulemakings (Prior to Formation of RM Prefix – Fiscal Year 1974)",
        ),
    ],
)
def test_ferc_nonstandard_and_discontinued_prefixes_route_cleanly(
    term: str,
    expected_subject: str,
    expected_prefix: str,
    expected_status: str,
    expected_definition: str,
) -> None:
    """Table 2 non-standard and Table 3 discontinued prefixes resolve with exact status."""

    answer = explain_term(term)
    assert answer.kind == "ferc_docket"
    assert answer.subject == expected_subject
    assert answer.ferc_docket_prefix is not None
    assert answer.ferc_docket_prefix.prefix == expected_prefix
    assert answer.ferc_docket_prefix.status == expected_status
    assert answer.ferc_docket_prefix.definition == expected_definition
    assert answer.statement is not None
    assert f"{expected_status} prefix {expected_prefix}" in answer.statement


def test_every_one_of_the_95_ferc_prefixes_routes_verbatim() -> None:
    """All 95 captured prefixes (77 active, 18 discontinued) are routable without omission."""

    directory = load_packaged_ferc_docket_prefixes()
    assert len(directory.rows) == 95
    for row in directory.rows:
        if row.prefix == "P":
            sample = "P-1234-000"
        elif row.prefix == "HB":
            sample = "HB26-01-0-00"
        elif row.prefix == "ID":
            sample = "FERC Docket No. ID-8705-002"
        elif row.prefix.endswith("-"):
            sample = f"FERC Docket No. {row.prefix}1234"
        else:
            sample = f"Docket No. {row.prefix}26-20-000"
        answer = explain_term(sample, ferc_docket_prefixes=directory)
        assert answer.kind == "ferc_docket", row.prefix
        assert answer.ferc_docket_prefix is not None, row.prefix
        assert answer.ferc_docket_prefix.prefix == row.prefix
        assert answer.ferc_docket_prefix.status == row.status
        assert answer.ferc_docket_prefix.library == row.library
        assert answer.ferc_docket_prefix.definition == row.definition
        assert answer.ferc_docket_prefix.source_url == FERC_DOCKET_PREFIX_PDF_URL
        assert answer.ferc_docket_prefix.source_sha256 == FERC_DOCKET_PREFIX_PDF_SHA256


@pytest.mark.parametrize(
    ("term", "expected_subject"),
    [
        ("QQ26-20-000", "QQ26-20-000"),
        ("Docket No. QQ26-20-000", "QQ26-20-000"),
        ("XZ26-20-000", "XZ26-20-000"),
        ("FERC Docket No. QQ26-20", "QQ26-20"),
        ("FERC Docket No. Q-1234-000", "Q-1234-000"),
    ],
)
def test_unknown_ferc_prefixes_refuse_explicitly(term: str, expected_subject: str) -> None:
    """A FERC-shaped docket whose prefix is absent from the 95-row directory refuses."""

    answer = explain_term(term)
    assert answer.kind == "ferc_docket"
    assert answer.subject == expected_subject
    assert answer.statement is None
    assert answer.ferc_docket_prefix is None
    assert answer.unexplained_reason == "ferc_docket_prefix_unknown"


def test_ferc_routing_reads_supplied_directory_rather_than_hardcoded_definitions() -> None:
    """Omitting a prefix from an injected directory refuses it rather than inventing an answer."""

    full = load_packaged_ferc_docket_prefixes()
    without_cp = FercPublishedDocketPrefixCapture(
        source_url=full.source_url,
        source_sha256=full.source_sha256,
        source_byte_length=full.source_byte_length,
        page_count=full.page_count,
        rows=tuple(row for row in full.rows if row.prefix != "CP"),
    )
    answer = explain_term("Docket No. CP26-20-000", ferc_docket_prefixes=without_cp)
    assert answer.kind == "ferc_docket"
    assert answer.unexplained_reason == "ferc_docket_prefix_unknown"


def test_regulations_gov_dockets_stay_in_their_own_family() -> None:
    """Regulations.gov dockets (including PT-, FS-, FERC-, ID-) must never route to FERC."""

    for term, expected_subject in (
        ("EPA-HQ-OAR-2021-0317", "EPA-HQ-OAR-2021-0317"),
        ("Docket No. EPA-HQ-OAR-2021-0317", "EPA-HQ-OAR-2021-0317"),
        ("PT-2026-0001", "PT-2026-0001"),
        ("FS-2024-0001", "FS-2024-0001"),
        ("FERC-2026-0001", "FERC-2026-0001"),
        ("ID-2024-0001", "ID-2024-0001"),
        ("Docket # ID-03-003", "ID-03-003"),
    ):
        answer = explain_term(term)
        assert answer.kind == "docket", term
        assert answer.subject == expected_subject, term
        assert answer.unexplained_reason == "docket_documents_not_supplied", term
        assert answer.ferc_docket_prefix is None


@pytest.mark.parametrize(
    "term",
    [
        # Federal Reserve Board (1,434 R-nnnn dockets in the Federal Register)
        "Docket No. R-1835",
        "R-1835",
        "Docket No. E-7890",
        "Docket No. G-1234",
        # FCC Delegated Authority and media/wireline dockets
        "DA16-1282",
        "MM Docket No. 98-213",
        "WC Docket No. 17-108",
        "FCC 24-100",
        # USDA AMS & EPA Idaho & FEMA/MARAD two-segment collisions
        "ST08-01",
        "ID-03-003",
        "ID23-7003",
        "P-1234",
        "Docket No. P-7915",
        "Docket No. P-009",
        # FAA Airworthiness Directive & SEC releases/filings
        "AD 2000-01-01",
        "Rel. No. IC-24979",
        "Release No. 33-8176",
        "File No. SR-NYSE-2024-01",
        # Wrong agency or label noun
        "EPA Docket No. CP26-20-000",
        "Project No. CP26-20-000",
        # Bare prefixes and incomplete fragments without a docket shape
        "CP",
        "ER",
        "EL",
        "P",
        "CP26",
        "Docket No. CP",
        "Docket No.",
        "FERC",
        "FERC Docket No. HB26",
        "FERC HB1",
        # Known FERC prefixes in wrong format must refuse as unrecognised_shape,
        # never misreporting them as unknown prefixes or Regulations.gov dockets
        "ID23-7003-000",
        "FERC Docket No. ID23-7003",
        "FERC Docket No. CP-1234",
        "FERC Docket No. ER-1234-000",
        "FERC Docket No. HB-123",
        "FERC Docket No. PT-2026-001",
        # Non-ASCII Unicode digits rejected by re.ASCII
        "CP\u0662\u0666-\u0662\u0660-\u0660\u0660\u0660",
        "P-\u0661\u0662\u0663\u0664-\u0660\u0660\u0660",
        # Ambiguous / compound / malformed inputs
        "CP26-20-000 and ER24-1234-000",
        "Docket Nos. CP26-20-000, ER24-1234-000",
        "CP26-20-000 extra",
        "CP26-20-00",
        "CP26-20-0000",
        "CP2-20-000",
        "PT26-20",
        "QQ26-20",
    ],
)
def test_non_ferc_collisions_bare_prefixes_and_ambiguous_inputs_refuse(term: str) -> None:
    """Anti-false-positive fence measured over 1,004,233 Federal Register documents."""

    answer = explain_term(term)
    assert answer.unexplained_reason == "unrecognised_shape", (term, answer)
    assert answer.ferc_docket_prefix is None


@pytest.mark.parametrize(
    ("label", "adversarial"),
    [
        ("docket_10k_spaces", "Docket" + " " * 10_000 + "a b"),
        ("docket_3k_colons", "Docket No." + ":" * 3_000 + "a b"),
        ("ferc_10k_spaces", "FERC" + " " * 10_000 + "a b"),
    ],
    ids=lambda item: item if isinstance(item, str) and len(item) < 30 else "",
)
def test_ferc_label_regex_is_linear_on_adversarial_runs(label: str, adversarial: str) -> None:
    """Possessive quantifiers prevent quadratic ReDoS on long non-matching runs."""

    from refspec.registry import term_explanation as mod

    start = time.perf_counter()
    assert mod._explain_ferc_docket(adversarial, None, require_explicit_ferc=False) is None
    assert mod._explain_ferc_docket(adversarial, None, require_explicit_ferc=True) is None
    elapsed = time.perf_counter() - start
    assert elapsed < 0.05, f"_explain_ferc_docket took {elapsed:.3f}s on {label}"
    assert explain_term("Docket No." + ":" * 3_000 + "a b").unexplained_reason == "unrecognised_shape"


def test_unrelated_inputs_do_not_load_ferc_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-FERC inputs defer directory loading and by_prefix() indexing."""

    from refspec.registry import term_explanation as mod

    def _boom() -> FercPublishedDocketPrefixCapture:
        raise AssertionError("FERC prefix directory must not be loaded for unrelated inputs")

    monkeypatch.setattr(mod, "load_packaged_ferc_docket_prefixes", _boom)
    assert explain_term("haddock").unexplained_reason == "unrecognised_shape"
    assert explain_term("RIN 2060-AV12").unexplained_reason == "rin_subject_not_owned_here"
    assert explain_term("EPA-HQ-OAR-2021-0317").unexplained_reason == "docket_documents_not_supplied"
