"""The minting layer, each rule pinned by the evidence that bought it.

Every specimen below is a real identifier. The Federal Register document
numbers and the bare-legacy witnesses were read out of the pinned
``document_number`` column (1,004,233 distinct) on 2026-08-31; the RINs,
dockets and CFR parts are the specimens :mod:`identifier_shapes` and
:mod:`citation_grammar` already carry, re-used rather than re-invented so a
positive here is a positive there.

The lexical spaces are rulespec's, restated in the module and held true
against the vendored ``rulespec-conformance`` wheel by the first test in this
file. Nothing here asserts what an IRI "should" look like from memory.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import rulespec_conformance
from rulespec_conformance.contract import enums

from refspec.registry import identifier_shapes
from refspec.registry.act_resolution import canonical_usc_iri
from refspec.registry.citation_grammar import (
    CFR_LETTERED_PART_SHARE,
    CFR_TITLE_COUNT,
    CONGRESS_CURRENT,
    EO_HIGHEST_KNOWN,
    parse_cfr_citations,
)
from refspec.registry.iri_minting import (
    BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER,
    IDENTIFIER_SPACES,
    PARTNER_NAMESPACE,
    MintedIdentifier,
    mint_cfr_iri,
    mint_executive_order_iri,
    mint_federal_register_document_iri,
    mint_partner_iri,
    mint_public_law_iri,
    mint_regulations_gov_docket_iri,
    mint_rin_iri,
)

# --------------------------------------------------------------------------- #
# The pinned columns, resolved the way ``test_identifier_shapes`` resolves them.
# The Federal Register corpus came home to RefSpec's own ``output/`` on
# 2026-08-31; this reads it directly rather than through the ``../spicy-regs``
# fallback the two repos' 2026-08-21 split had left behind.

_ROOT = Path(__file__).resolve().parents[1]
FEDERAL_REGISTER_PARQUET = (
    _ROOT
    / "output"
    / "registry-real-data-sources"
    / "rulespec-stabilization-candidate-final"
    / "federal_register.parquet"
)
AGENDA_RIN_PARQUET = (
    _ROOT
    / "output"
    / "registry-real-data-sources"
    / "unified-agenda-parquet"
    / "unified_agenda_legal_authorities.parquet"
)


#: One real, minting call per family, so a property test sweeps the whole
#: surface rather than one minter's habits. Each specimen is cited at the test
#: that states its rule.
EVERY_FAMILY: tuple[tuple[str, MintedIdentifier | None], ...] = (
    ("cfr", mint_cfr_iri(7, "273", "9")),
    ("cfr-part-only", mint_cfr_iri(40, "60")),
    ("cfr-lettered-part", mint_cfr_iri(7, "15a")),
    ("eo", mint_executive_order_iri(12_866)),
    ("rin", mint_rin_iri("2060-AV16")),
    ("regsgov", mint_regulations_gov_docket_iri("EPA-HQ-OAR-2021-0317")),
    ("pl", mint_public_law_iri("119-101")),
    ("frdoc", mint_federal_register_document_iri("2024-00366")),
    # 2011-237 was the "frdoc-partner" specimen until rulespec 0.2.0rc16
    # widened the space; it is first-class now, which is the whole delivery of
    # that widening. The partner specimen moved to a letter-opening value,
    # which is a population the hatch still holds (117,292 of them).
    ("frdoc-short-tail", mint_federal_register_document_iri("2011-237")),
    ("frdoc-partner", mint_federal_register_document_iri("E8-24348")),
    ("frdoc-bare-legacy", mint_federal_register_document_iri("09-19806", column_licensed=True)),
    ("partner", mint_partner_iri("proceeding", "EPA-HQ-OAR-2021-0317")),
)


# --------------------------------------------------------------------------- #
# The contract this module restates.


def test_the_minted_spaces_are_the_contract_verbatim() -> None:
    """:data:`IDENTIFIER_SPACES` restates rkaf. This holds the copies true.

    Reading the patterns out of the package at runtime would make the module
    agree with whatever shipped rather than with what was reviewed, so they
    are restated -- and, like ``act_resolution._RKAF_USC_IRI``, restating only
    earns its keep if something breaks when the two drift. The contract is
    compiled into four forms and all four must carry the same pattern for
    every family.

    Two normalizations, both of the transcription and neither of the rule:
    the module makes each group non-capturing, and all four compiled forms
    escape the CFR pattern's literal dot for their own string syntax
    (``\\\\.`` in the file bytes, ``\\.`` in the pattern).
    """

    root = Path(rulespec_conformance.__file__).parent / "_data" / "compiled"
    compiled = [
        path.read_text(encoding="utf-8", errors="ignore")
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".json", ".ttl", ".ts", ".rego"}
    ]
    for scheme, space in IDENTIFIER_SPACES.items():
        if scheme == "rkaf:partner-defined":
            continue  # the escape hatch: rkaf states no space, and that is the point
        # partition, not removeprefix over the joined literal: spelling the
        # scheme prefix whole here would state a bare "us-" term claim that
        # test_rkaf_term_currency's sweep rightly refuses.
        family = scheme.partition(":us-")[2]
        stated = set()
        for text in compiled:
            stated.update(re.findall(rf"\^urn:rkaf:us:{family}:[^\"$\s]*\$", text))
        assert len(stated) == 1, (family, stated)
        assert space.pattern.replace("(?:", "(") == next(iter(stated)).replace(r"\\", "\\"), family


def test_every_scheme_minted_is_one_rulespec_declares() -> None:
    """A scheme name is data rulespec owns; inventing one publishes nothing.

    The enum members come from the vendored contract, so a scheme renamed
    upstream breaks here rather than reaching a consumer as an unknown string.
    """

    declared = {
        member
        for name in dir(enums)
        if name.isupper() and isinstance(getattr(enums, name), tuple)
        for member in getattr(enums, name)
    }
    assert set(IDENTIFIER_SPACES) <= declared
    assert set(enums.US_REGULATORY_IDENTIFIER_SCHEME) - {"rkaf:us-usc"} <= set(IDENTIFIER_SPACES)


# --------------------------------------------------------------------------- #
# The structural guarantee.


def test_no_minter_emits_an_identifier_the_contract_would_reject() -> None:
    """Every family, checked against the space it declares and the floor below it.

    The floor is rkaf's own ``rkaf:hasArtifactIdentifier`` production, which
    every compiled profile applies to every identifier whatever its scheme.
    The U.S.C. precedent is checked against the same floor in the same
    assertion, so this is the family's rule rather than one invented for the
    new module: if ``canonical_usc_iri`` would fail it, the check is wrong.
    """

    floor = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
    minted = [identifier for _, identifier in EVERY_FAMILY]
    assert all(identifier is not None for identifier in minted)
    for name, identifier in EVERY_FAMILY:
        assert identifier is not None, name
        assert IDENTIFIER_SPACES[identifier.scheme].fullmatch(identifier.iri), name
        assert floor.fullmatch(identifier.iri), name

    for iri in (*(i.iri for i in minted if i), canonical_usc_iri("42", "7411")):
        assert floor.fullmatch(iri), iri
        assert iri.startswith("urn:rkaf:"), iri
        assert iri == iri.strip() and iri.isascii(), iri
        assert "" not in iri.split(":"), iri


def test_the_type_refuses_to_hold_an_identifier_outside_its_space() -> None:
    """Data refuses with ``None``; a broken invariant raises. Both, here.

    The minters never construct a bad pair -- ``_mint`` catches this and hands
    back a refusal -- so the raise exists for a consumer assembling one by
    hand, which is the only way an unchecked identifier could reach rkaf.
    """

    # The scheme below is one substitution from a real one and deliberately
    # undeclared; it is spelled in two halves because writing it whole would
    # claim a term the rkaf term-currency sweep must keep refusing.
    with pytest.raises(ValueError, match="undeclared identifier scheme"):
        MintedIdentifier(scheme="rkaf:" + "us-uscode", iri="urn:rkaf:us:usc:42:7411")
    with pytest.raises(ValueError, match="outside the lexical space"):
        MintedIdentifier(scheme="rkaf:us-eo", iri="urn:rkaf:us:eo:012866")
    with pytest.raises(ValueError, match="outside the lexical space"):
        MintedIdentifier(scheme="rkaf:us-frdoc", iri="urn:rkaf:us:frdoc:09-19806")
    # And the pair a well-formed IRI under the wrong scheme would make.
    with pytest.raises(ValueError, match="outside the lexical space"):
        MintedIdentifier(scheme="rkaf:us-pl", iri="urn:rkaf:us:eo:12866")


def test_minting_is_a_function_of_the_identifier_and_nothing_else() -> None:
    """Same input, same identifier; equivalent spellings, one identifier.

    Where the shape layer normalizes -- case in a RIN, a docket label, a zero
    pad on a CFR title, a Unicode dash in a Public Law -- the spellings must
    converge, or a join key depends on how a publisher typed it.
    """

    assert mint_cfr_iri(7, "273", "9") == mint_cfr_iri(7, "273", "9")
    assert mint_federal_register_document_iri(
        "09-19806", column_licensed=True
    ) == mint_federal_register_document_iri("09-19806", column_licensed=True)

    assert mint_rin_iri("2060-av16") == mint_rin_iri("2060-AV16")
    assert mint_rin_iri("2060–AV16") == mint_rin_iri("2060-AV16")
    assert mint_regulations_gov_docket_iri("Docket No. FDA-2011-N-0002") == mint_regulations_gov_docket_iri(
        "fda-2011-n-0002"
    )
    assert mint_cfr_iri("07", "1943") == mint_cfr_iri(7, 1943)
    assert mint_public_law_iri("119–101") == mint_public_law_iri("119-101")
    assert mint_executive_order_iri("012866") == mint_executive_order_iri(12_866)
    assert mint_federal_register_document_iri("2024-00366") == mint_federal_register_document_iri(" 2024-00366 ")


# --------------------------------------------------------------------------- #
# CFR.


def test_a_cfr_citation_mints_title_part_and_section() -> None:
    """7 CFR 273.9 is SNAP's income rule; 49 CFR 1.95 is one of 22 DOT
    delegation sections under part 1, which is why the section belongs in the
    identifier and not in a comment beside it."""

    assert mint_cfr_iri(7, "273", "9").iri == "urn:rkaf:us:cfr:7:273.9"
    assert mint_cfr_iri(49, "1", "95").iri == "urn:rkaf:us:cfr:49:1.95"
    assert mint_cfr_iri(40, "60").iri == "urn:rkaf:us:cfr:40:60"
    assert mint_cfr_iri(7, "273", "9").scheme == "rkaf:us-cfr"


def test_a_cfr_subsection_resolves_to_its_section() -> None:
    """A parenthetical is dropped, not refused -- the narrowing
    ``canonical_usc_iri`` makes one column over. "40 CFR 60.18(a)" names a
    subsection of a section rkaf can spell, and refusing the whole citation
    over the part it cannot would lose the part it can."""

    assert mint_cfr_iri(40, "60", "18(a)") == mint_cfr_iri(40, "60", "18")


def test_a_lettered_cfr_part_mints_and_its_case_is_folded() -> None:
    """The gap this test used to pin, closed. 83 of the OFR's 272 non-numeric
    parts carry a single letter, and ``rkaf:us-cfr`` writes the part as
    ``[0-9]+([a-z]|-[0-9]+)?`` from rulespec 0.2.0rc16.

    "7 CFR 15" and "7 CFR 15a" are separate parts; every ancestor of the
    grammar merged them, and minting them as one identifier would put that
    defect back on the wire. So the check did not disappear when the gap
    closed -- it changed sign, and the two parts must still be two
    identifiers.

    The fold is the half that could not be tested before. ``parse_cfr_citations``
    emits the publisher's own uppercase spelling for the four parts published
    that way (26 CFR 16A, 29 CFR 4022B, 29 CFR 4041A, 46 CFR 147A), so
    lowercasing here is the only thing that makes them mintable -- and it is
    lossless, because no part collides with another under the fold anywhere in
    the index, and each of those four titles also has the bare numeric part.
    """

    lettered, total = CFR_LETTERED_PART_SHARE
    assert 0 < lettered < total  # the population the widening reaches

    assert parse_cfr_citations("7 CFR 15a")[0].cfr_part == "15a"
    assert mint_cfr_iri(7, "15a").iri == "urn:rkaf:us:cfr:7:15a"
    assert mint_cfr_iri(7, "15").iri == "urn:rkaf:us:cfr:7:15"
    assert mint_cfr_iri(7, "15a") != mint_cfr_iri(7, "15")

    # The uppercase fold, on the only path that produces uppercase.
    assert parse_cfr_citations("26 CFR 16A")[0].cfr_part == "16A"
    assert mint_cfr_iri(26, "16A").iri == "urn:rkaf:us:cfr:26:16a"
    assert mint_cfr_iri(26, "16A") == mint_cfr_iri(26, "16a")
    assert mint_cfr_iri(26, "16").iri == "urn:rkaf:us:cfr:26:16"  # folding, never truncating

    # Still refused: no multi-letter part suffix exists anywhere in the index.
    assert mint_cfr_iri(7, "15ab") is None


def test_a_hyphen_numbered_cfr_part_is_in_the_space_and_out_of_the_minter() -> None:
    """The contract spells ``41 CFR 101-1``; this minter deliberately will not.

    189 of the 272 non-numeric parts are hyphen-numbered and every one is in
    title 41, so rulespec's vocabulary describes the real CFR and the space
    accepts the form. RefSpec is narrower on purpose, the way
    :func:`mint_cfr_iri` is already narrower than the grammar on the title:
    nothing here can PRODUCE a hyphen part. No pinned column carries one (852
    distinct ``cfr_part`` values, all numeric), and the prose reader stops at
    the hyphen -- which is the right answer in 48 of the 49 titles, because a
    hyphen after a part number usually means a range (40 CFR 60-63), a section
    written loosely (28 CFR 23-4) or a numbered standard (49 CFR 571-108).

    DEFERRED, and this is the point of the test: because the capture stops at
    the hyphen, ``41 CFR 101-1`` reads as part ``101`` and mints
    ``urn:rkaf:us:cfr:41:101`` -- a first-class identifier for a part that
    does not exist. Minting the hyphen form here would swap a named, tested
    gap for a silent wrong answer, so the space carries the form and the
    minter refuses it. The fix belongs in
    ``citation_grammar._CFR_PART_CAPTURE``, which is receipt-pinned; REF-054
    records the trigger that reopens it. This test asserts the phantom as
    CURRENT BEHAVIOUR so that fixing it upstream turns this red on purpose.
    """

    # The contract accepts it: the space is rulespec's, and it is right.
    assert IDENTIFIER_SPACES["rkaf:us-cfr"].fullmatch("urn:rkaf:us:cfr:41:101-1")
    # The minter does not.
    assert mint_cfr_iri(41, "101-1") is None
    assert mint_cfr_iri(41, "101-1", "20") is None

    # The deferred phantom, pinned as it behaves today rather than as it should.
    assert parse_cfr_citations("41 CFR 101-1")[0].cfr_part == "101"
    assert mint_cfr_iri(41, "101").iri == "urn:rkaf:us:cfr:41:101"


def test_an_impossible_cfr_title_mints_nothing() -> None:
    """The grammar keeps the row with a false verdict; the minter refuses.

    A data-quality consumer needs "87 CFR 1" inspectable, which is why
    ``parse_cfr_citations`` returns it at all. An identifier is a claim rather
    than a row, so the two layers answer differently on purpose.
    """

    assert mint_cfr_iri(CFR_TITLE_COUNT, "1") is not None
    assert mint_cfr_iri(CFR_TITLE_COUNT + 1, "1") is None
    assert mint_cfr_iri(35, "1") is not None  # Reserved today; the Panama Canal until 2000
    assert mint_cfr_iri(0, "1") is None
    assert mint_cfr_iri(40, "0") is None  # there is no part 0, as there is no title 0


def test_a_section_that_states_nothing_is_no_section_rather_than_a_bad_one() -> None:
    """A placeholder in a ``cfr_section`` column must not sink the part.

    ``states_nothing`` owns that vocabulary -- the Agenda's own placeholders
    bought its sentinel set, quotation marks included -- so this module reads
    it rather than inventing a second list. A section that states SOMETHING
    the space cannot spell still refuses the whole citation, because that is a
    section rkaf cannot name rather than a field left blank.
    """

    for blank in (None, "", "  ", "None", "N/A", "Not Yet Determined"):
        assert mint_cfr_iri(40, "60", blank) == mint_cfr_iri(40, "60"), blank
    for unspellable in ("60 to 65", "Appendix A", "18.5"):
        assert mint_cfr_iri(40, "60", unspellable) is None, unspellable


def test_the_part_canonicalization_agrees_with_the_grammar() -> None:
    """The zero pad is stripped here and there, and the two must not drift.

    The Agenda's filers pad ("07 CFR 1943" is USDA's title 7), the grammar
    strips it because a part is a join key, and this module strips it again
    because the identifier is that key. Minting from the raw components and
    minting from the parsed citation have to land on one identifier.
    """

    for text, components in (
        ("40 CFR 0060", ("40", "0060", None)),
        ("07 CFR 1943", ("07", "1943", None)),
        ("40 CFR 60.18(a)", ("40", "60", "18(a)")),
        ("49 CFR 1.95", ("49", "1", "95")),
    ):
        (citation,) = parse_cfr_citations(text)
        from_grammar = mint_cfr_iri(citation.cfr_title, citation.cfr_part, citation.cfr_section)
        assert from_grammar == mint_cfr_iri(*components), text
        assert from_grammar is not None, text


# --------------------------------------------------------------------------- #
# Executive orders.


def test_an_executive_order_mints_from_its_number() -> None:
    """12866 is the review order every OIRA row cites; 13990 and 14008 are the
    pair ``citation_grammar``'s list rule was bought with."""

    assert mint_executive_order_iri(12_866).iri == "urn:rkaf:us:eo:12866"
    assert mint_executive_order_iri("13990").iri == "urn:rkaf:us:eo:13990"
    assert mint_executive_order_iri(14_008).scheme == "rkaf:us-eo"


def test_an_order_beyond_the_dated_bound_still_mints() -> None:
    """``EO_HIGHEST_KNOWN`` is a dated fact for judging captures, and the module
    that states it says so. A minter fenced by it would refuse the next order
    the President signs, which is a bug with a calendar."""

    assert mint_executive_order_iri(EO_HIGHEST_KNOWN) is not None
    assert mint_executive_order_iri(EO_HIGHEST_KNOWN + 1_000) is not None


def test_what_is_not_an_order_number_mints_nothing() -> None:
    """The series starts at 1, and everything else is a refusal.

    "3 CFR, 1977 Comp., p. 123" locates an order's printed page and states no
    order number at all; ``EoCompilationLocator`` deliberately carries none,
    and nothing here invents one from a page.
    """

    for stated in (0, "0", "", None, "12866.0", "EO 12866", "12,866", "٣"):
        assert mint_executive_order_iri(stated) is None, stated


# --------------------------------------------------------------------------- #
# RINs.


def test_a_rin_mints_and_a_sentinel_does_not() -> None:
    """56,364 of 64,537 catalog ``rin`` values are the literal "Not Assigned".

    Admitted by a containment test it became the corpus's most common
    identifier by a factor of ten, which is why the minter wraps a validator
    that answers "is this string one" and never "does it contain one".
    """

    assert mint_rin_iri("2060-AV16").iri == "urn:rkaf:us:rin:2060-AV16"
    assert mint_rin_iri("0301-AA00").iri == "urn:rkaf:us:rin:0301-AA00"
    assert mint_rin_iri("2060-AV16 ").iri == "urn:rkaf:us:rin:2060-AV16"  # surrounding space is not identity
    for stated in ("Not Assigned", "", None, "RIN 2060-AV16", "3235-0695", "2060-AV1"):
        assert mint_rin_iri(stated) is None, stated


def test_a_rin_the_shape_admits_and_rkaf_cannot_spell_is_refused() -> None:
    """``rkaf:us-rin`` closes on ``[0-9]{2}``; the shape allows
    ``[A-Za-z0-9]{2}``.

    Zero of the Unified Agenda's 46,547 RINs take the divergent form
    (measured 2026-08-31), so the gap costs nothing today. It is pinned here
    so that the day a roster carries one, the refusal is a failing test rather
    than a silently missing identifier.
    """

    assert identifier_shapes.is_regulation_identifier_number("0648-ABCD")
    assert mint_rin_iri("0648-ABCD") is None


def test_a_real_rin_outside_the_shape_is_refused_not_repaired() -> None:
    """Five real RINs fall outside the shape, each confirmed against the
    Federal Register API on 2026-08-22. The minter refuses them for the same
    reason the shape does: no roster entry corroborates them, and a minter
    that guessed would publish an identity nothing issued."""

    for real_but_unminted in ("0648-XD990", "0648-XC705", "3090-00XX", "1115-09AE", "2070-78AB"):
        assert mint_rin_iri(real_but_unminted) is None, real_but_unminted


# --------------------------------------------------------------------------- #
# Regulations.gov dockets.


def test_a_docket_mints_through_the_label_and_not_around_it() -> None:
    """The three rules the wrapped validator carries, each with its witness.

    Strip-then-validate: Commerce's own ``DOC-2010-0001`` survives the label
    grammar that would otherwise eat its "DOC". A stripped remainder opening
    on a digit is what the label was numbering, not an identifier hiding
    behind it -- refusing that shape refuses 5,214 of 5,506 mutilated
    references and costs no real docket. And a FERC docket fits the shape
    without being one of these dockets: 24,548 references of the "CP26-20-000"
    form belong to another registry.
    """

    assert mint_regulations_gov_docket_iri("EPA-HQ-OAR-2021-0317").iri == "urn:rkaf:us:regsgov:EPA-HQ-OAR-2021-0317"
    assert mint_regulations_gov_docket_iri("Docket No. FDA-2011-N-0002").iri == "urn:rkaf:us:regsgov:FDA-2011-N-0002"
    assert mint_regulations_gov_docket_iri("DHS Docket No. USCIS-2025-0004") is not None
    assert mint_regulations_gov_docket_iri("DOC-2010-0001").iri == "urn:rkaf:us:regsgov:DOC-2010-0001"
    assert mint_regulations_gov_docket_iri("ACF_FRDOC_0001").iri == "urn:rkaf:us:regsgov:ACF_FRDOC_0001"

    assert mint_regulations_gov_docket_iri("MM Docket No. 98-213") is None
    assert mint_regulations_gov_docket_iri("CP26-20-000") is None
    for states_nothing in ("Docket No.", "", None, "None", "nan", "null"):
        assert mint_regulations_gov_docket_iri(states_nothing) is None, states_nothing


def test_the_docket_minter_inherits_the_column_readers_license() -> None:
    """A Regulations.gov DOCUMENT id fits the docket shape, and mints.

    This is the two-readers doctrine landing where it is easy to misread.
    ``normalize_docket_reference`` is the COLUMN reader: a value out of
    ``docket_ids_json`` is a docket because the field says so, and its shape
    absorbs "EPA-HQ-OAR-2021-0317-0001" whole. The PROSE reader arbitrates the
    same characters the other way -- the document claim wins, the contest
    ``identifier_shapes`` measures on 56 references of the pinned column --
    and that arbitration is where the question belongs.

    So the minter is exactly as wide as the validator it wraps and not one
    character wider, and a caller holding a document id must not hand it to a
    docket minter. Both halves are pinned here because either one changing
    silently is how a document id becomes a docket downstream.
    """

    assert IDENTIFIER_SPACES["rkaf:us-regsgov"].fullmatch("urn:rkaf:us:regsgov:EPA-HQ-OAR-2021-0317-0001")

    document = "EPA-HQ-OAR-2021-0317-0001"
    assert identifier_shapes.normalize_docket_reference(document) == document
    assert mint_regulations_gov_docket_iri(document).iri == f"urn:rkaf:us:regsgov:{document}"

    (prose,) = identifier_shapes.detect_identifier_shapes(document)
    assert prose.kind is identifier_shapes.IdentifierKind.REGULATIONS_GOV_DOCUMENT
    (docket,) = identifier_shapes.detect_identifier_shapes("EPA-HQ-OAR-2021-0317")
    assert docket.kind is identifier_shapes.IdentifierKind.DOCKET


# --------------------------------------------------------------------------- #
# Public laws.


def test_a_public_law_mints_from_the_compound_the_grammar_produces() -> None:
    """Pub. L. 119-101 is the 21st Century ROAD to Housing Act, approved
    2026-07-11 at 140 Stat. 846; 116-260 is the consolidated act that carries
    94 popular names."""

    assert mint_public_law_iri("119-101").iri == "urn:rkaf:us:pl:119-101"
    assert mint_public_law_iri("116-260").iri == "urn:rkaf:us:pl:116-260"
    assert mint_public_law_iri("119-101").scheme == "rkaf:us-pl"


def test_a_law_of_a_congress_that_has_not_sat_still_mints() -> None:
    """``CONGRESS_CURRENT`` is dated and says so. The next Congress outruns it,
    and a minter fenced by it would refuse that Congress's first law."""

    assert mint_public_law_iri(f"{CONGRESS_CURRENT + 1}-1") is not None


def test_what_is_not_a_public_law_number_mints_nothing() -> None:
    """A session-law chapter is not a Public Law number and never was.

    ``1955:360`` is one of the 1,921 Table III keys with that shape, and the
    source credits have nothing to look them up under. Nothing here converts
    one into the other.
    """

    for stated in ("1955:360", "Pub. L. 119-101", "119", "119-", "0-1", "119-0", "", None):
        assert mint_public_law_iri(stated) is None, stated


# --------------------------------------------------------------------------- #
# Federal Register documents: the three outcomes.


def test_a_modern_document_number_rkaf_can_spell_mints_first_class() -> None:
    """480,566 of the 1,004,233 distinct values, measured 2026-08-31.

    2024-00366 is rulespec's own positive fixture for the scheme
    (``artifact-us-frdoc-positive.jsonld``); 2026-13078 is the specimen
    ``identifier_shapes`` carries for the modern form.
    """

    for value in ("2024-00366", "2026-13078", "2012-00019"):
        minted = mint_federal_register_document_iri(value)
        assert minted == MintedIdentifier(scheme="rkaf:us-frdoc", iri=f"urn:rkaf:us:frdoc:{value}"), value


def test_a_short_tail_is_real_and_is_now_first_class() -> None:
    """The inverse of what this test used to assert, and the point of rc16.

    2010-5997 (published 2010-03-19) and 2011-237 (2011-01-11) are real,
    confirmed against the publisher's own API on 2026-08-22, and 28,862
    modern-form numbers in the pinned column carry a three- or four-digit
    tail. ``rkaf:us-frdoc`` was five digits wide and the series is not; from
    rulespec 0.2.0rc16 the space is ``[0-9]{4}-[0-9]{3,5}`` and all 28,862 are
    first-class. rulespec replaced its own negative fixture accordingly --
    ``urn:rkaf:us:frdoc:2024-366`` was the negative and is now valid, so the
    fixture moved to 2024-36, below the new floor.

    The widening is safe because it splits no identity: across all 480,566
    admitted values, no document has both a padded and an unpadded spelling,
    so nothing here gained a second first-class identifier.
    """

    assert IDENTIFIER_SPACES["rkaf:us-frdoc"].fullmatch("urn:rkaf:us:frdoc:2011-237")
    for value in ("2010-5997", "2011-237", "2012-999", "2013-1234"):
        minted = mint_federal_register_document_iri(value)
        assert minted is not None, value
        assert minted.scheme == "rkaf:us-frdoc", value
        assert minted.iri == f"urn:rkaf:us:frdoc:{value}", value


def test_the_floor_under_the_widened_tail_is_where_the_shape_layer_puts_it() -> None:
    """Three digits, so ``rkaf:us-frdoc`` is exactly co-extensive with the shape.

    ``identifier_shapes.FEDERAL_REGISTER_DOCUMENT_NUMBER`` is
    ``\\d{4}-\\d{3,5}``, and rc16 moved the space to meet it rather than to
    overtake it. 286 modern values in the pinned column have a one- or
    two-digit tail and stay outside RULESPEC'S space -- and they are not a
    separate form: 2010-99 and 2010-100 are consecutive documents of one
    unpadded series, so the floor cuts a continuous series and is held for
    consistency with the layer that reads it, not because the evidence puts
    a boundary there. This test is about that space, which REF-056 leaves
    exactly as wide as rc16 left it -- the same 286 values are now
    column-licensed into the partner hatch, tested in
    ``test_the_modern_short_tail_family_needs_the_column_license_too`` below,
    which is a different event from widening ``rkaf:us-frdoc`` itself.

    The ceiling is measured rather than chosen: zero modern values reach a
    six-digit tail, and the largest sequence ever issued is 33,861 (2011), so
    refusing six leaves 3x headroom.
    """

    for below in ("2010-99", "2024-36", "2011-7"):
        assert mint_federal_register_document_iri(below) is None, below
        licensed = mint_federal_register_document_iri(below, column_licensed=True)
        assert licensed is not None, below
        assert licensed.scheme == "rkaf:partner-defined", below
    for above in ("2024-003661", "2010-1234567"):
        assert mint_federal_register_document_iri(above) is None, above

    assert mint_federal_register_document_iri("2010-100").iri == "urn:rkaf:us:frdoc:2010-100"


def test_the_letter_opening_forms_keep_the_identity_the_shape_layer_reads() -> None:
    """Correction, republication and legacy numbers are official identifiers.

    The shape layer already reads all three whole; only the mintable space
    refuses them. Minting them under the hatch adds no shape of this module's
    own -- ``detect_identifier_shapes`` is the whole test -- and a value that
    layer does not read whole is still refused.
    """

    for value in ("E7-21559", "C1-2026-13078", "R1-2010-13257", "R1-10679"):
        minted = mint_federal_register_document_iri(value)
        assert minted is not None, value
        assert minted.scheme == "rkaf:partner-defined", value

    for real_but_unread in ("Z9-802", "E9-23", "X10-11220", "E3-2013-2261"):
        assert mint_federal_register_document_iri(real_but_unread) is None, real_but_unread
    assert mint_federal_register_document_iri("FR Doc. 2026-13078") is None


def test_the_four_letter_opening_families_need_the_column_license_too() -> None:
    """REF-052/REF-054's four families, at the mint layer rather than the
    shape layer's own unit tests (``test_identifier_shapes.py`` pins the
    positive and negative fixture per family).

    Unlicensed, every specimen below is exactly as unread as
    ``test_the_letter_opening_forms_keep_the_identity_the_shape_layer_reads``
    already proved for two of them. Licensed, THREE of the four still mint
    through the partner hatch; the X family left it at rulespec 0.2.0rc18,
    which gave it a space of its own (REF-065), and that departure is the
    whole delivery of that bump rather than a change in this fence. The column
    license is what the four still share, and it is what this test pins.
    """

    for value in ("E9-654", "Z9-9", "E3-2013-2261"):
        assert mint_federal_register_document_iri(value) is None, value
        licensed = mint_federal_register_document_iri(value, column_licensed=True)
        assert licensed is not None, value
        assert licensed.scheme == "rkaf:partner-defined", value
        assert licensed.iri == f"urn:rkaf:partner:{PARTNER_NAMESPACE}:frdoc:{value}", value

    # X still needs the license -- a date-free letter form is no more readable
    # in prose than a bare legacy number -- but it now lands in its own space.
    for value in ("X10-11220", "X09-101207"):
        assert mint_federal_register_document_iri(value) is None, value
        licensed = mint_federal_register_document_iri(value, column_licensed=True)
        assert licensed is not None and licensed.scheme == "rkaf:us-frdoc-x", value

    # The 99 short-tail corrections and the fused-colophon values REF-054
    # keeps refused stay refused, licensed or not -- the four families do not
    # reach for a second unmeasured population.
    for still_refused in ("C1-2012-19", "C1-2012-2091"):
        assert mint_federal_register_document_iri(still_refused, column_licensed=True) is None, still_refused


def test_the_bare_legacy_form_needs_the_column_license_and_only_that() -> None:
    """§1.2 in one assertion: refused as prose, minted as a column.

    "09-19806" is a real document of 2009-08-19 in the pinned column, and
    today it has no identity at all -- ``detect_identifier_shapes`` returns
    ``[]``. Unlabeled in running text it is indistinguishable from
    "MM Docket No. 98-213" and from a release number, so prose detection stays
    exactly as narrow as it is and the flag carries the whole difference.
    """

    assert identifier_shapes.detect_identifier_shapes("09-19806") == []
    assert not identifier_shapes.is_federal_register_document_number("09-19806")

    assert mint_federal_register_document_iri("09-19806") is None
    minted = mint_federal_register_document_iri("09-19806", column_licensed=True)
    assert minted == MintedIdentifier(
        scheme="rkaf:partner-defined", iri=f"urn:rkaf:partner:{PARTNER_NAMESPACE}:frdoc:09-19806"
    )

    # The whole era, not one witness: the first and last bare-legacy documents
    # in the pinned column are 1994-01-03 and 2009-08-19. (REF-056 widens a
    # further, disjoint production for the one- and two-digit tail this
    # constant's own docstring names and defers -- see
    # test_the_bare_legacy_short_tail_family_needs_the_column_license_too --
    # so the equivalence below stays exactly this constant's own shape.)
    for value in ("94-120124", "95-170007", "97-339151", "08-1234"):
        licensed = mint_federal_register_document_iri(value, column_licensed=True)
        assert (licensed is not None) == (re.fullmatch(BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER, value) is not None)
        assert mint_federal_register_document_iri(value) is None, value


def test_the_bare_legacy_shape_stops_where_the_measurement_stops() -> None:
    """This constant's own tail runs three to six digits; the ceiling is a
    measurement and stays a measurement.

    Three to five is the modern shape's own range and covers 394,121 values;
    the six-digit tail adds exactly 7, every one a real published document
    with its own publisher URL in the pinned corpus. 1,370 further values run
    ``\\d{2}-\\d{1,2}`` -- "00-10" is a real airworthiness directive of
    2000-01-04 -- and REF-056 admits them through a sibling production
    (:data:`~refspec.registry.identifier_shapes._FR_BARE_LEGACY_SHORT_TAIL`)
    rather than by widening THIS constant, so its own 394,128-value count
    stays exactly what REF-052 published it as. Nothing above a six-digit
    tail is a shape the pinned column carries either way.
    """

    shape = re.compile(BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER)
    assert shape.fullmatch("09-19806") and shape.fullmatch("94-120124")
    assert not shape.fullmatch("00-10") and not shape.fullmatch("00-1")
    assert not shape.fullmatch("94-1234567")
    # Refused by THIS shape, but not by the mint layer any more -- REF-056's
    # sibling production reads it; see
    # test_the_bare_legacy_short_tail_family_needs_the_column_license_too.
    assert mint_federal_register_document_iri("00-10", column_licensed=True) is not None
    assert mint_federal_register_document_iri("94-1234567", column_licensed=True) is None
    # Four values the column really carries and no production admits. They
    # are NOT all damage, and the difference is worth stating rather than
    # flattening: "94-22818Filed" and "00-2999Doc" are the colophon fusion
    # the module's research notes attest (the printed page welded the next
    # word on); "95-95-744" is the publisher's own number, printed
    # "[FR Doc. 95-95-744 Filed 1-11-95; 8:45 am]" on 60 FR 2992, with an
    # extra hyphenated segment no shape reads; and "94-S16142" is a spelling
    # whose document the publisher numbers "94-00000" instead. Refusal is
    # what they share; damage is not. See the partition in
    # `test_the_document_number_column_is_accounted_for_exactly`.
    for refused in ("94-22818Filed", "94-S16142", "00-2999Doc", "95-95-744"):
        assert mint_federal_register_document_iri(refused, column_licensed=True) is None, refused


def test_the_bare_legacy_short_tail_family_needs_the_column_license_too() -> None:
    """REF-056's widening of the bare-legacy floor: one or two digits rather
    than three to six, at the mint layer rather than the shape layer's own
    unit tests (``test_identifier_shapes.py`` pins the positive and negative
    fixtures).

    "00-1" and "00-10" are real -- EPA's Amino/Phenolic Resins NESHAP (65 FR
    3276, 2000-01-20) and an FAA airworthiness directive (65 FR 207,
    2000-01-04), each read end to end against the publisher's PDF with its
    own printed colophon in the ordinary place. "93-54" witnesses the
    year-boundary sub-cluster: filed 1994-01-03 for the next day's issue, it
    still carries the outgoing year's two-digit token. 1,370 values in the
    pinned column take this shape: 112 one-digit tails, 1,258 two-digit.
    Unlicensed, all three stay exactly as unread as the wider bare-legacy
    shape already is; licensed, all three mint through the same partner
    hatch. research/evidence/fr-short-tails-2026-08-31/ carries the full
    24-specimen sample this ruling and the next test share.
    """

    for value in ("00-1", "00-10", "93-54"):
        assert mint_federal_register_document_iri(value) is None, value
        licensed = mint_federal_register_document_iri(value, column_licensed=True)
        assert licensed is not None, value
        assert licensed.scheme == "rkaf:partner-defined", value
        assert licensed.iri == f"urn:rkaf:partner:{PARTNER_NAMESPACE}:frdoc:{value}", value

    # The ceiling REF-052 already measured (six digits) is untouched --
    # only the floor moved.
    assert mint_federal_register_document_iri("94-1234567", column_licensed=True) is None


def test_the_modern_short_tail_family_needs_the_column_license_too() -> None:
    """REF-056's second widening: the modern form's own shape with a one- or
    two-digit tail, admitted to the partner hatch only -- rulespec's own
    mintable space (``FEDERAL_REGISTER_DOCUMENT_NUMBER``, three to five
    digits) is untouched by this ruling; see
    ``test_the_floor_under_the_widened_tail_is_where_the_shape_layer_puts_it``
    above for the space that stays exactly as wide as rc16 left it.

    "2010-1" and "2010-10" are real -- an SEC notice of application (75 FR
    1007, 2010-01-07) and a DOE notice on the same page (75 FR 983,
    2010-01-07), each with its own printed colophon in the ordinary place.
    "2013-58" is the sole specimen outside the 2010-2012 cluster: filed
    2013-01-02 at 4:15 pm, printed on 78 FR 908, one page after a
    2012-tokened document ("2012-31431", filed 1-4-13) in the same issue of
    2013-01-07. That pair shows only that the year token follows neither
    date the page prints -- not publication, since one issue carries both
    tokens, and not filing, since the 2012-tokened one was filed two days
    LATER. What decides the token is not established: no source this lane
    retained records a submission timestamp, and a "rolls over per
    submission" reading of these pages would be an inference. The column
    doctrine needs only the shape. 286 values in the pinned column take this
    shape: 27 one-digit tails, 259 two-digit.
    """

    for value in ("2010-1", "2010-10", "2013-58"):
        assert mint_federal_register_document_iri(value) is None, value
        licensed = mint_federal_register_document_iri(value, column_licensed=True)
        assert licensed is not None, value
        assert licensed.scheme == "rkaf:partner-defined", value
        assert licensed.iri == f"urn:rkaf:partner:{PARTNER_NAMESPACE}:frdoc:{value}", value

    # Three digits and up is rulespec's own space, unmoved by this ruling.
    assert mint_federal_register_document_iri("2010-100").iri == "urn:rkaf:us:frdoc:2010-100"


def test_document_number_padding_is_never_normalized_away() -> None:
    """The publisher pads some years and not others, and across the 480,566
    modern-form values not one padded number has an unpadded twin. Stripping
    the pad would invent a spelling no publisher issued, so the two are
    different identifiers and stay different.

    This carried no weight while the space was five digits wide -- "2012-19"
    was outside it for its length. After rc16 widened the tail to three, the
    FLOOR is the only thing still refusing it, so the sentence below is now
    load-bearing rather than incidental: a two-digit tail states nothing the
    shape reads, and the padded spelling is the identifier because it is the
    one the publisher issued. Were the floor ever lowered, this test is where
    the identity question surfaces first."""

    padded = mint_federal_register_document_iri("2012-00019")
    unpadded = mint_federal_register_document_iri("2012-19")
    assert padded is not None and padded.iri == "urn:rkaf:us:frdoc:2012-00019"
    assert unpadded is None  # a two-digit tail states nothing the shape reads
    # Three digits and up, the pad is preserved rather than stripped: both of
    # these are inside the widened space, and they are not the same identifier.
    assert mint_federal_register_document_iri("2012-019").iri == "urn:rkaf:us:frdoc:2012-019"
    assert mint_federal_register_document_iri("2012-019") != mint_federal_register_document_iri("2012-19")

    # REF-056 is the floor lowering this docstring anticipated -- but only
    # for the column license, not for rulespec's own space: "2012-19" now
    # mints under ``column_licensed=True``, through the partner hatch, with
    # the literal two-digit spelling the value stated. It is still not the
    # same identifier as "2012-019": different scheme, different URN.
    licensed_unpadded = mint_federal_register_document_iri("2012-19", column_licensed=True)
    assert licensed_unpadded is not None
    assert licensed_unpadded.scheme == "rkaf:partner-defined"
    assert licensed_unpadded.iri == f"urn:rkaf:partner:{PARTNER_NAMESPACE}:frdoc:2012-19"
    assert licensed_unpadded != mint_federal_register_document_iri("2012-019")

    # "2012-19"/"2012-019" is a HYPOTHETICAL pair: the column carries the
    # padded value and not the unpadded one, so it states the rule without
    # exercising it. REF-056 admitted 1,656 short-tail values, and three of
    # them turn the question real -- these are the only bare-short values in
    # the pinned column whose zero-padded twin is also there, found by
    # padding all 1,370 of them to every width from two digits to six and
    # looking each candidate up:
    for short, padded in (("96-30", "96-00030"), ("97-29", "97-00029"), ("97-63", "97-00063")):
        minted_short = mint_federal_register_document_iri(short, column_licensed=True)
        minted_padded = mint_federal_register_document_iri(padded, column_licensed=True)
        assert minted_short is not None and minted_padded is not None
        assert minted_short != minted_padded, (short, padded)
        assert minted_short.iri.endswith(f":frdoc:{short}"), short
        assert minted_padded.iri.endswith(f":frdoc:{padded}"), padded

    # The larger near-collision the widening opened is not padding at all: a
    # bare short tail and a letter-opening short tail can share their second
    # digit and their whole tail. 967 such pairs exist in the pinned column;
    # "00-1"/"C0-1" is the first alphabetically. The letter is a character
    # the value states, so the two stay distinct for the same reason the
    # padding does -- nothing is folded away.
    bare_short = mint_federal_register_document_iri("00-1", column_licensed=True)
    letter_short = mint_federal_register_document_iri("C0-1", column_licensed=True)
    assert bare_short is not None and letter_short is not None
    assert bare_short != letter_short
    assert bare_short.iri.endswith(":frdoc:00-1") and letter_short.iri.endswith(":frdoc:C0-1")


# --------------------------------------------------------------------------- #
# The partner-defined escape hatch.


def test_the_partner_hatch_is_lossless_and_fenced() -> None:
    """rulespec's own layout, this repository as the namespace.

    ``urn:rkaf:partner:fixture:proceeding:EPA-HQ-OAR-2021-0317`` is how
    rulespec's ``artifact-us-frdoc-positive.jsonld`` writes one, so the
    segment order is the publisher's. The value is percent-encoded rather than
    folded, because a value reaches this hatch precisely when no space would
    normalize it.
    """

    minted = mint_partner_iri("proceeding", "EPA-HQ-OAR-2021-0317")
    assert minted == MintedIdentifier(
        scheme="rkaf:partner-defined",
        iri=f"urn:rkaf:partner:{PARTNER_NAMESPACE}:proceeding:EPA-HQ-OAR-2021-0317",
    )
    assert mint_partner_iri("frdoc", "Docket No. 7").iri.endswith("Docket%20No.%207")
    assert mint_partner_iri("frdoc", "E7-21559") != mint_partner_iri("frdoc", "e7-21559")

    # The kind fence keeps the five-segment layout parseable — no URN
    # machinery, no case variants — and damage is not identity.
    for kind in ("USC", "us:usc", "", "9frdoc", "frdoc/x"):
        assert mint_partner_iri(kind, "x") is None, kind
    for value in ("", None, "  ", "a\nb", "a\tb"):
        assert mint_partner_iri("frdoc", value) is None, value

    # Reusing a real family's word as the kind is DELIBERATE, not a shadow:
    # the FR minter itself mints kind "frdoc" beside rkaf:us-frdoc, and the
    # partner prefix is what keeps the namespaces apart. Pinned positively so
    # a future blocklist cannot land without noticing the module relies on it.
    #
    # The hatch is a waiting room, and rc16 emptied part of it: the 28,862
    # short-tail documents that used to be minted here as kind "frdoc" are
    # first-class now. That migration needed no lookup precisely because the
    # encoding below is lossless -- the partner IRI carries the source value,
    # so `partner:refspec:frdoc:2011-237` maps to `us:frdoc:2011-237` by
    # inspection. See REF-054.
    assert mint_partner_iri("usc", "note-only-citation").iri == (
        f"urn:rkaf:partner:{PARTNER_NAMESPACE}:usc:note-only-citation"
    )


# --------------------------------------------------------------------------- #
# The populations, over the pinned columns.


@pytest.mark.skipif(not FEDERAL_REGISTER_PARQUET.is_file(), reason="the Federal Register corpus is not present")
@pytest.mark.slow
def test_the_document_number_column_is_accounted_for_exactly() -> None:
    """Every distinct ``document_number``, sorted into what it can carry.

    The specimens above state the rules; this states what the rules are worth
    on the population they were written for, so widening or narrowing one has
    a number to move. Re-measured 2026-08-31 (REF-056) over the same pinned
    file ``test_identifier_shapes`` reads, after ``identifier_shapes`` took
    two further column-licensed-only productions home: the bare-legacy
    shape's own one- and two-digit tail, and the modern shape's own one- and
    two-digit tail.

    The headline is still the 39.2%: without the column license, 394,128
    real documents shaped exactly ``BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER``
    have no identity of any kind, and the ingest lane that reads their bodies
    has nothing to join them on. That count is untouched by this cycle,
    because REF-056 widens through two NEW named productions rather than by
    rewriting that constant -- the same posture REF-052 took with the four
    letter-opening families, and for the identical reason: this constant's
    own count is cited from outside this module (``iri_minting.py``), so
    widening it in place would move a number this cycle does not touch.

    What moved this cycle is two new buckets, one per production: 1,656
    values that used to land in ``refused`` now land in them -- 1,370
    bare-legacy-shaped (112 one-digit tails, 1,258 two-digit) and 286
    modern-shaped (27 one-digit, 259 two-digit). They are counted apart
    rather than added together because those four numbers are what the
    evidence stratified on, and an aggregate would let one of them move
    while the total stood still.
    Neither is the same event as a lexical space being widened (rc16) --
    ``first-class`` did not move by one value, because the modern-shaped 286
    mint through the partner hatch, never through ``rkaf:us-frdoc``. Neither
    is the same event as REF-052's own widening -- ``bare-legacy`` and
    ``letter-opening`` did not move by one value either, because both new
    productions are checked (and bucketed) before the ``letter-opening``
    catch-all, the way ``bare-legacy`` itself already was.

    There used to be a bucket here named ``modern-short-tail``, counting the
    28,862 modern numbers the five-digit-wide ``rkaf:us-frdoc`` space refused.
    rulespec 0.2.0rc16 widened the space to ``[0-9]{4}-[0-9]{3,5}`` and that
    population is now first-class, so the bucket named nobody and was retired
    rather than pinned at zero. The 286 modern-shaped values in ``short-tail``
    this cycle are NOT that population reappearing: they are the further
    one- and two-digit tail rc16 stopped short of, admitted to the partner
    hatch only -- rulespec's own space is exactly as wide as rc16 left it,
    proven immediately below by ``test_the_floor_under_the_widened_tail_is_where_the_shape_layer_puts_it``.
    """

    import pyarrow.parquet as pq

    bare_legacy_shape = re.compile(BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER)
    #: REF-056's two productions, bucketed SEPARATELY rather than as one
    #: "short-tail" total. They were read together in the first draft of this
    #: cycle, and the aggregate hid which of the two moved: a mutation that
    #: took a value from one production to the other left the census
    #: untouched. Each is now pinned on its own, with its own tail-length
    #: histogram, because those are the numbers the ruling actually argues.
    bare_short_shape = identifier_shapes._FR_BARE_LEGACY_SHORT_TAIL
    modern_short_shape = identifier_shapes._FR_MODERN_SHORT_TAIL

    from refspec.registry import hand_validated_interpretations

    #: The seven shapes the leftover refusals really take, measured
    #: 2026-08-31 by ``research/evidence/fr-short-tails-2026-08-31/scratch/
    #: classify_refused.py``, plus the eighth REF-066 opened: the five
    #: modern-form collision numbers, membership-matched against the
    #: hand-validated table rather than a shape (there is no shape -- they
    #: are ordinary-looking modern numbers, refused for what they NAME, not
    #: how they are spelled). Every value is classified by exactly one of
    #: them -- asserted below rather than arranged by ordering, so the list
    #: is a partition instead of a priority chain.
    refusal_classes: tuple[tuple[str, re.Pattern[str] | frozenset[str]], ...] = (
        ("collision -2 suffix", re.compile(r"\d{2}-\d{3,5}-2")),
        ("short-tail correction", re.compile(r"[Cc]\d-\d{4}-\d{2,4}")),
        ("colophon-fused", re.compile(r".*(?:Filed|Doc)")),
        ("extra-hyphen", re.compile(r"\d{2}-\d{2}-\d{2,5}")),
        ("trailing letter", re.compile(r"(?:[A-Za-z]\d|\d{2}|\d{4})-\d+[A-Za-z]")),
        ("not the publisher's number", re.compile(r"\d{2}-S\d+")),
        ("granule293", re.compile(r"granule293")),
        ("modern-form collision (REF-066)", hand_validated_interpretations.refused_federal_register_document_numbers()),
    )

    def _refusal_class_matches(matcher: re.Pattern[str] | frozenset[str], text: str) -> bool:
        return matcher.fullmatch(text) is not None if isinstance(matcher, re.Pattern) else text in matcher

    values: set[str] = set()
    for batch in pq.ParquetFile(FEDERAL_REGISTER_PARQUET).iter_batches(
        columns=["document_number"], batch_size=100_000
    ):
        values.update(value for value in batch.column(0).to_pylist() if value is not None)
    assert len(values) == 1_004_233

    census = dict.fromkeys(
        (
            "first-class",
            "bare-legacy",
            "letter-opening",
            "short-tail bare-legacy",
            "short-tail modern",
            "refused",
        ),
        0,
    )
    #: (bucket, tail length) -> count, for the two new buckets only.
    short_tail_lengths: dict[tuple[str, int], int] = {}
    refused_values: list[str] = []
    minted_iris: list[str] = []
    for value in values:
        prose = mint_federal_register_document_iri(value)
        column = mint_federal_register_document_iri(value, column_licensed=True)
        assert prose is None or prose == column, value  # the license only ever adds
        folded = value.strip().translate(identifier_shapes._DASHES)
        if column is None:
            census["refused"] += 1
            refused_values.append(value)
            continue
        minted_iris.append(column.iri)
        if column.scheme == "rkaf:us-frdoc":
            census["first-class"] += 1
        elif bare_legacy_shape.fullmatch(folded):
            census["bare-legacy"] += 1
        elif bare_short_shape.fullmatch(folded) or modern_short_shape.fullmatch(folded):
            # Column-only by construction: neither short-tail production is
            # read by the prose reader, so a value landing here through the
            # column license alone is never one the prose reader also reads.
            assert not identifier_shapes.is_federal_register_document_number(value), value
            # And disjoint by construction: a two-digit year cannot also be a
            # four-digit one under ``fullmatch``, which is the whole argument
            # `identifier_shapes` makes in prose beside both constants.
            assert not (
                bare_short_shape.fullmatch(folded) and modern_short_shape.fullmatch(folded)
            ), value
            bucket = (
                "short-tail bare-legacy"
                if bare_short_shape.fullmatch(folded)
                else "short-tail modern"
            )
            census[bucket] += 1
            key = (bucket, len(folded.split("-")[-1]))
            short_tail_lengths[key] = short_tail_lengths.get(key, 0) + 1
        else:
            # The dead bucket, as an assertion. Every modern-form number the
            # shape layer reads is now inside the space, so nothing that
            # reaches the partner hatch -- through the prose reader, through
            # the four letter-opening families, or through either short-tail
            # production -- can be one.
            assert not identifier_shapes.is_federal_register_document_number(value), value
            census["letter-opening"] += 1

    assert census == {
        # What rulespec can spell: 47.8% of the column. Down 5 from the
        # 480,566 REF-054 widening left this at: REF-066's collision census
        # names five of those five hundred-and-eighty-thousand-odd numbers
        # as each naming TWO different documents, and mints NONE of them --
        # not even through the partner hatch, since minting anything for a
        # collision would still be one identifier standing for two
        # documents. Column licensing otherwise still moves values between
        # the partner hatch and refused, never into or out of first-class.
        "first-class": 480_561,
        # §1.2: identity-less today, and the whole reason for the column
        # license. Unchanged since REF-052: this cycle widens through two new
        # sibling productions, never by rewriting this constant's own shape.
        "bare-legacy": 394_128,
        # Corrections, republications and legacy prefixes the prose reader
        # reads (117,292, unchanged) plus the four families REF-052/REF-054
        # admit: 5,829 three-digit-and-shorter tails, 4,195 two-digit
        # prefixes, 206 six-digit tails, and the single
        # legacy-prefix-over-modern-body hybrid. Unchanged this cycle -- see
        # `identifier_shapes._FR_COLUMN_LETTER_FORMS`.
        "letter-opening": 127_523,
        # REF-056: the widening cycle after REF-052/REF-054, over the exact
        # two populations both named as deferred refusals in this module's
        # own prior comments. Both productions are column-licensed only --
        # the prose reader and rulespec's own mintable space are untouched,
        # proven by the assertion inside the loop above and by
        # `test_the_floor_under_the_widened_tail_is_where_the_shape_layer_puts_it`.
        # research/evidence/fr-short-tails-2026-08-31/ carries the
        # 24-specimen sample this ruling rests on.
        "short-tail bare-legacy": 1_370,
        "short-tail modern": 286,
        # Damage, real spellings nobody has ruled on, one non-identifier, and
        # (new, REF-066) five modern-form collisions -- 0.036% of the
        # column. All 365 are partitioned below.
        "refused": 365,
    }
    assert sum(census.values()) == len(values)
    # The partner hatch, derived rather than pinned separately.
    assert (
        census["bare-legacy"]
        + census["letter-opening"]
        + census["short-tail bare-legacy"]
        + census["short-tail modern"]
    ) == 523_307

    # The tail-length strata the sample was drawn against. The evidence
    # stratified by tail length, so the census pins tail length: a widening
    # that admitted, say, only the two-digit tails would leave every total
    # above intact and fail here.
    assert short_tail_lengths == {
        ("short-tail bare-legacy", 1): 112,
        ("short-tail bare-legacy", 2): 1_258,
        ("short-tail modern", 1): 27,
        ("short-tail modern", 2): 259,
    }

    # GLOBAL MINT SAFETY. Widening a floor is exactly the move that can give
    # two different documents one identifier, and the padding rule
    # (`test_document_number_padding_is_never_normalized_away`) is the only
    # thing preventing it. That test states the rule on four hand-picked
    # pairs; this states it on the whole column at once. The column already
    # walked above, so this costs a set() and no second pass.
    assert len(minted_iris) == 1_003_868
    assert len(set(minted_iris)) == len(minted_iris)

    # THE REMAINING 360, PARTITIONED EXACTLY -- not summarised. Each class is
    # a shape, each shape is disjoint from the others over this population,
    # and every value falls in exactly one. Re-measured 2026-08-31, and the
    # first three lines correct what REF-052's own comment here said:
    #
    # - 224, not 228, carry a literal `-2` collision suffix; every one of the
    #   224 has its un-suffixed twin present in this same column, which is
    #   what makes "collision" a reading rather than a guess.
    # - the four values the old count swept in with them are a different
    #   shape entirely: an extra hyphenated segment (94-94-30552, 95-26-82,
    #   95-95-22339, 95-95-744), and they are NOT damage -- 95-95-744's own
    #   printed colophon reads "[FR Doc. 95-95-744 Filed 1-11-95; 8:45 am]"
    #   on 60 FR 2992, one page after a properly formed "[FR Doc. 95-745
    #   Filed 1-11-95; 8:45 am]" on 60 FR 2991 of the same issue.
    # - the old "32 colophon-fused" was a catch-all holding 27 genuinely
    #   fused values (a literal "Filed"/"Doc" welded on by the printed page's
    #   own composition defect) plus 5 that are not fused at all. Four of
    #   those five are a real micro-family the publisher prints with ONE
    #   trailing letter -- C0-6263A ("[FR Doc. C0-6263A Filed 4-5-00; 8:45
    #   am]", 65 FR 18151, beside a properly formed "[FR Doc. C0-6216 ...]"
    #   on the same page), C9-20022A, 94-2050F and 2014-04654s (79 FR 11733,
    #   the trailing "s" printed with ordinary spacing before "Filed"). The
    #   module's own research notes already named C0-6263A "not damage"; it
    #   is broken out here rather than laundered into "fused".
    # - the fifth, 94-S16142, is the one value whose document the publisher
    #   numbers something else: federalregister.gov answers for it but
    #   returns document_number "94-00000", and the page's own colophon reads
    #   "[FR Doc. 94-00000 Filed 00-00-94; 8:45 am]". Both spellings are in
    #   this column; "94-00000" mints, this one does not.
    #
    # None of those seven is ruled on here. REF-054 keeps the 99 short-tail
    # corrections refused by name, and the trailing-letter and extra-hyphen
    # families are real-but-unread shapes with their own budget, recorded so
    # the decision can be made with a number. The eighth class IS ruled on,
    # by REF-066: five modern-form numbers a hand-validated collision census
    # names as naming two genuinely different documents each, refused
    # outright rather than laundered into any other bucket.
    refusal_partition = dict.fromkeys((name for name, _ in refusal_classes), 0)
    for value in refused_values:
        text = value.strip()
        matched = [name for name, matcher in refusal_classes if _refusal_class_matches(matcher, text)]
        assert len(matched) == 1, (value, matched)  # a partition, not a chain
        refusal_partition[matched[0]] += 1
    assert refusal_partition == {
        "collision -2 suffix": 224,
        "short-tail correction": 99,
        "colophon-fused": 27,
        "extra-hyphen": 4,
        "trailing letter": 4,
        "not the publisher's number": 1,
        "granule293": 1,
        "modern-form collision (REF-066)": 5,
    }
    assert sum(refusal_partition.values()) == census["refused"] == 365


@pytest.mark.skipif(not AGENDA_RIN_PARQUET.is_file(), reason="the Unified Agenda RIN roster is not built")
@pytest.mark.slow
def test_every_rin_the_agenda_states_mints() -> None:
    """All 46,547, with no gap between the shape and the space.

    The two productions differ -- ``[A-Za-z0-9]{2}`` against ``[0-9]{2}`` --
    and on this roster the difference is empty. That is the measurement the
    refusal test above is the counterpart of.
    """

    import pyarrow.parquet as pq

    rins = {value for value in pq.read_table(AGENDA_RIN_PARQUET, columns=["rin"]).column("rin").to_pylist() if value}
    assert len(rins) == 46_547
    minted = {rin: mint_rin_iri(rin) for rin in rins}
    assert all(identifier is not None for identifier in minted.values())
    assert len({identifier.iri for identifier in minted.values() if identifier}) == len(rins)


@pytest.mark.skipif(not FEDERAL_REGISTER_PARQUET.is_file(), reason="the Federal Register corpus is not present")
@pytest.mark.slow
def test_every_docket_the_column_states_mints_or_refuses_cleanly() -> None:
    """The docket minter over the real ``docket_ids_json`` column.

    Nothing here asserts a rate -- ``normalize_docket_reference`` owns that
    measurement and is tested where it lives. What this asserts is the
    property the minting layer adds: whatever the validator accepts, the
    scheme can spell, so a docket never normalizes and then fails to mint.
    """

    import pyarrow.parquet as pq

    references: set[str] = set()
    for batch in pq.ParquetFile(FEDERAL_REGISTER_PARQUET).iter_batches(
        columns=["docket_ids_json"], batch_size=100_000
    ):
        for cell in batch.column(0).to_pylist():
            if cell is not None:
                references.update(value for value in json.loads(cell) if value and value.strip())

    for reference in references:
        docket = identifier_shapes.normalize_docket_reference(reference)
        minted = mint_regulations_gov_docket_iri(reference)
        assert (docket is None) == (minted is None), reference
        assert docket is None or minted.iri == f"urn:rkaf:us:regsgov:{docket}", reference


# --------------------------------------------------------------------------- #
# The date-qualified legacy space (rulespec 0.2.0rc17, REF-064).


def test_a_dated_legacy_number_mints_the_qualified_space() -> None:
    """The whole delivery of rc17: 394,128 values stop taking the hatch.

    The identity carries the publication date because rulespec's space does,
    and it does because the bare number does not identify a document -- see
    the collision fixture below. The spelling is rulespec's own fixture form
    (``artifact-us-frdoc-legacy-tail-1-positive.jsonld`` states
    ``urn:rkaf:us:frdoc-legacy:00-1:2000-01-20`` for the pinned corpus row
    document_number=00-1, publication_date=2000-01-20).
    """

    minted = mint_federal_register_document_iri(
        "00-1", column_licensed=True, publication_date="2000-01-20"
    )
    assert minted is not None
    assert minted.scheme == "rkaf:us-frdoc-legacy"
    assert minted.iri == "urn:rkaf:us:frdoc-legacy:00-1:2000-01-20"

    # A date object and the date32 a PyArrow column yields spell the same day.
    assert mint_federal_register_document_iri(
        "00-1", column_licensed=True, publication_date=date(2000, 1, 20)
    ) == minted

    # Every tail width rulespec's space admits, one to six digits.
    for value, day in (("09-19806", "2009-08-19"), ("94-10503", "1994-05-03")):
        one = mint_federal_register_document_iri(
            value, column_licensed=True, publication_date=day
        )
        assert one is not None and one.scheme == "rkaf:us-frdoc-legacy", value
        assert one.iri == f"urn:rkaf:us:frdoc-legacy:{value}:{day}", value


def test_the_same_legacy_number_on_two_days_is_two_identities() -> None:
    """NEGATIVE FIXTURE, and the reason the space is qualified at all.

    ``00-111`` names two different documents; the Federal Register API and the
    pinned corpus each kept a different one, which is why a within-corpus
    collision count could report zero while the world held two. Undated, both
    would mint the same partner identity and one document would silently
    become the other. Dated, they are two identities, which is the fix.
    """

    first = mint_federal_register_document_iri(
        "00-111", column_licensed=True, publication_date="2000-01-03"
    )
    second = mint_federal_register_document_iri(
        "00-111", column_licensed=True, publication_date="2000-06-15"
    )
    assert first is not None and second is not None
    assert first.iri != second.iri
    assert first.scheme == second.scheme == "rkaf:us-frdoc-legacy"


def test_an_undated_legacy_number_keeps_the_hatch_and_never_half_qualifies() -> None:
    """NEGATIVE FIXTURE: no date, no qualified identity -- and no invention.

    A caller who cannot state the day gets exactly what it got before rc17,
    the partner hatch, rather than an identity whose date slot was guessed
    from the number's own year prefix. That guess is measurably wrong 1,661
    times; see the minter's docstring.
    """

    undated = mint_federal_register_document_iri("09-19806", column_licensed=True)
    assert undated is not None
    assert undated.scheme == "rkaf:partner-defined"
    assert undated.iri == "urn:rkaf:partner:refspec:frdoc:09-19806"

    # The column license still governs: a date does not admit a value the
    # prose reader refuses, because the date is not a license.
    assert mint_federal_register_document_iri("09-19806", publication_date="2009-08-19") is None


def test_a_year_prefix_that_disagrees_with_its_date_still_mints() -> None:
    """The measured refusal to fence: 1,661 real documents disagree.

    A legacy number's leading two digits usually restate its publication year,
    and fencing on the disagreement is the obvious next thought. 07-6308 was
    published 2008-01-15 -- a December number printed in January -- and it is
    one of 1,661 (0.42% of 395,498) that spill across the year boundary. The
    prefix is a spelling; the date is the caller's fact.
    """

    spilled = mint_federal_register_document_iri(
        "07-6308", column_licensed=True, publication_date="2008-01-15"
    )
    assert spilled is not None
    assert spilled.iri == "urn:rkaf:us:frdoc-legacy:07-6308:2008-01-15"


def test_a_publication_date_that_is_not_a_day_is_loud() -> None:
    """NEGATIVE FIXTURE: a caller's broken assertion raises, never downgrades.

    Data gets a refusal (``None``); a caller who passes a non-date has stated
    a fact that is not one, and silently falling back to the hatch would
    publish an identity missing the qualifier the caller believed it supplied.
    A datetime is refused too rather than truncated to its day.
    """

    for bad in ("not a date", "2009-13-45", "2009-08", "August 19, 2009", ""):
        with pytest.raises(ValueError, match="does not state a day"):
            mint_federal_register_document_iri("09-19806", column_licensed=True, publication_date=bad)

    # But a real day in ISO's compact spelling is a real day, and it mints the
    # SAME identity as the extended one. Deliberate, and the same doctrine as
    # the padding rule above: a spelling variant of one fact must not become a
    # second identifier.
    assert mint_federal_register_document_iri(
        "09-19806", column_licensed=True, publication_date="20090819"
    ) == mint_federal_register_document_iri(
        "09-19806", column_licensed=True, publication_date="2009-08-19"
    )

    with pytest.raises(ValueError, match="not an instant"):
        mint_federal_register_document_iri(
            "09-19806", column_licensed=True, publication_date=datetime(2009, 8, 19, 13, 45, tzinfo=UTC)
        )


def test_the_modern_space_is_untouched_by_a_date() -> None:
    """A date changes nothing for a value rulespec can already spell.

    ``rkaf:us-frdoc`` is tried first and answers whole, so a caller passing a
    date for a modern number gets the same identity it always got -- the
    legacy branch is unreachable for it, and no modern identity gains a
    qualifier it never had.
    """

    assert mint_federal_register_document_iri(
        "2024-00366", publication_date="2024-03-08"
    ) == mint_federal_register_document_iri("2024-00366")


# --------------------------------------------------------------------------- #
# The self-dating X space (rulespec 0.2.0rc18, REF-065).


def test_an_x_number_mints_without_a_date_because_it_carries_one() -> None:
    """The X family needs no qualifier: the number states its own day.

    Read right-anchored -- last four digits are the month and day, everything
    before them is the sequence -- the encoding agrees with publication_date on
    4,400 of 4,400 corpus rows. So unlike the legacy form, the bare number
    identifies the document, and no date is asked for.
    """

    five = mint_federal_register_document_iri("X94-10503", column_licensed=True)
    assert five is not None
    assert five.scheme == "rkaf:us-frdoc-x"
    assert five.iri == "urn:rkaf:us:frdoc-x:X94-10503"

    # The six-digit tail a fixed-width space would have stranded: 206 real
    # documents, of which this is one (74 FR 64213, 2009-12-07, the DHS
    # Statement of Regulatory Priorities). Sequence 10, not sequence 1.
    six = mint_federal_register_document_iri("X09-101207", column_licensed=True)
    assert six is not None and six.scheme == "rkaf:us-frdoc-x"
    assert six.iri == "urn:rkaf:us:frdoc-x:X09-101207"


def test_an_x_number_and_its_bare_twin_are_different_identities() -> None:
    """The prefix is part of the identity, and 54.1% of X numbers need it.

    2,382 of the 4,400 X numbers have a bare twin in the corpus, and the pair
    are different documents: X94-10503 is a 44,932-byte Semiannual Regulatory
    Agenda correction (Part VIII, Department of Agriculture), while 94-10503 is
    the 14,678-byte GE CF6 airworthiness NPRM, Docket 94-ANE-11 -- same
    publication date, read from their own bodies. Stripping the prefix would
    merge two publications into one identity.
    """

    x = mint_federal_register_document_iri("X94-10503", column_licensed=True)
    bare = mint_federal_register_document_iri(
        "94-10503", column_licensed=True, publication_date="1994-05-03"
    )
    assert x is not None and bare is not None
    assert x.iri != bare.iri
    assert x.scheme == "rkaf:us-frdoc-x"
    assert bare.scheme == "rkaf:us-frdoc-legacy"


def test_an_x_number_whose_own_day_contradicts_the_caller_is_loud() -> None:
    """NEGATIVE FIXTURE: the self-dating property, made load-bearing.

    A date is never part of an X identity, so stating one is optional -- but
    stating a WRONG one is a detectable defect rather than an ambiguity,
    because the number carries the answer. Across the corpus the two never
    disagree, so a disagreement means either a caller pairing the wrong date
    with the number or a publisher row whose own two statements diverge.
    Minting quietly would hide both.
    """

    assert (
        mint_federal_register_document_iri(
            "X94-10503", column_licensed=True, publication_date="1994-05-03"
        )
        == mint_federal_register_document_iri("X94-10503", column_licensed=True)
    )

    for wrong in ("1994-05-04", "1994-06-03", "1995-05-03"):
        with pytest.raises(ValueError, match="carries its own publication date"):
            mint_federal_register_document_iri(
                "X94-10503", column_licensed=True, publication_date=wrong
            )


def test_the_x_shape_layer_stops_where_the_corpus_does_and_the_space_does_not() -> None:
    """A DELIBERATE gap between two bounds, and closing it either way is wrong.

    rulespec's space admits a seven-digit tail as CAPACITY (its own fixture
    ``X26-9991231`` exercises it). This repository's shape layer stops at six,
    which is what the corpus contains. That is not a mismatch to reconcile:
    **the two layers have opposite failure costs**, so they are bounded by
    different things on purpose (ruled 2026-09-02, rulespec side).

    A LEXICAL SPACE answers "is this string a well-formed identifier?" Its
    failure mode is refusing a real identifier the publisher issued -- silent
    data loss, discovered only when someone cannot cite a document, and
    unrecoverable without a contract change. So it is bounded by CAPACITY and
    never fitted to observed data: hence ``{5,7}``, and hence the capacity
    fixture that exercises headroom no document has reached.

    A SHAPE LAYER answers "does this string, found in data, look like an X
    number?" Its failure mode is a FALSE POSITIVE -- a wrong identity, which is
    worse than a refusal because it is silent and propagates into joins. So it
    is bounded by MEASUREMENT: ``_FR_TWO_DIGIT_PREFIX`` and
    ``_FR_SIX_DIGIT_TAIL`` are measured lines serving every letter family (E,
    C, R and Z as well as X), and widening them on speculation would admit
    unseen shapes for all of them to buy a shape none has.

    The consequence lands in the safe direction, which is what settles it: a
    seven-digit X, if ever published, is SPELLABLE BUT NOT AUTO-DETECTED. A
    caller that knows what it holds can mint it under the column license; a
    detector that does not know refuses, and the refusal is counted. A refusal
    that appears in a census beats a wrong mint that does not. It is REF-052's
    prose-reader/column-reader split -- "the column is the license" -- applied
    one layer up.
    """

    assert mint_federal_register_document_iri("X26-9991231", column_licensed=True) is None
    assert mint_federal_register_document_iri("X09-101207", column_licensed=True) is not None


# --------------------------------------------------------------------------- #
# The modern-form collision refusal set (REF-066).


#: The seven modern-form document numbers a 2026-09-02 full crawl found
#: naming two documents each -- see
#: research/evidence/fr-collision-census-2026-09-02/README.md. Five are
#: genuinely different documents (refused); two are one matter published
#: twice (mint normally). Both halves are asserted below: a refusal test
#: alone would let a future reader "helpfully" refuse all seven.
_FR_COLLISION_REFUSALS = ("2010-31094", "2010-31384", "2010-31396", "2010-31415", "2010-517")
_FR_COLLISION_MINTS_NORMALLY = ("2015-17759", "2015-25354")


def test_the_five_collision_numbers_refuse_and_the_two_still_mint() -> None:
    """The negative fixture REF-066 demands: not all seven refuse.

    Real values, real hand-validated table, no mocking -- this is the test
    that would catch a future reader who "simplifies" the check into
    refusing every number the census names, rather than only the five the
    census AND the documents themselves say collide.
    """

    for value in _FR_COLLISION_REFUSALS:
        assert mint_federal_register_document_iri(value) is None, value
        assert mint_federal_register_document_iri(value, column_licensed=True) is None, value

    for value in _FR_COLLISION_MINTS_NORMALLY:
        minted = mint_federal_register_document_iri(value)
        assert minted is not None, value
        assert minted.scheme == "rkaf:us-frdoc"
        assert minted.iri == f"urn:rkaf:us:frdoc:{value}"


def test_a_refused_collision_number_never_falls_through_to_the_partner_hatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check is unconditional, not merely a guard on ``rkaf:us-frdoc``.

    Minting ANYTHING for a genuine collision -- even the lossless
    ``rkaf:partner-defined`` escape hatch -- would still be one identifier
    standing for two documents, so the refusal has to come before every
    other branch, not just before the first one. Monkeypatched rather than
    using a real collision number, so this holds regardless of whether the
    census evidence is committed: it pins the MECHANISM (refuse before
    shape, refuse before the hatch), not today's seven-member population.
    """

    from refspec.registry import iri_minting as module

    fake_refused = "1994-99999"  # an otherwise-mintable modern-form number
    assert mint_federal_register_document_iri(fake_refused, column_licensed=True) is not None
    monkeypatch.setattr(module, "is_a_refused_federal_register_collision", lambda value: value == fake_refused)
    assert mint_federal_register_document_iri(fake_refused) is None
    assert mint_federal_register_document_iri(fake_refused, column_licensed=True) is None
    # An unrelated value is untouched by the monkeypatched predicate.
    assert mint_federal_register_document_iri("2024-00366") is not None


def test_minting_an_ordinary_number_touches_no_witness_no_census_and_no_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ordinary mint is a pure function of the value, in every deployment.

    ``is_a_refused_federal_register_collision`` is O(1) for the overwhelming
    majority of values precisely because it never has to look at a witness,
    a census receipt or a git index for anything that is not one of the
    seven adjudicated numbers. This proves that from the minter's own side,
    by making all three explode if they are ever reached: an audit on
    2026-09-02 found the earlier census-first order raising for
    ``2024-00366`` from an installed layout, because minting had quietly
    become repository-dependent (REF-066, and
    ``hand_validated_interpretations._repository_root_if_present``).

    What this cannot see: whether the collision numbers themselves still
    refuse -- ``test_the_five_collision_numbers_refuse_and_the_two_still_mint``
    above is that half, and it is the half that would otherwise be
    satisfiable by deleting the check.
    """

    from refspec.registry import hand_validated_interpretations as hvi

    def _explode(*_arguments: object, **_keywords: object) -> object:
        raise AssertionError("an ordinary document number must reach neither witness, census nor git")

    monkeypatch.setattr(hvi, "_federal_register_collision_row", _explode)
    monkeypatch.setattr(hvi, "_federal_register_collision_population", _explode)
    monkeypatch.setattr(hvi, "_repository_root_if_present", _explode)
    monkeypatch.setattr(hvi, "_git", _explode)
    assert mint_federal_register_document_iri("2024-00366") is not None
    assert mint_federal_register_document_iri("E8-24348") is not None
    assert mint_federal_register_document_iri("93-54", column_licensed=True) is not None
