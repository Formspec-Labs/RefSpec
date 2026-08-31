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
    two-digit tail and stay outside -- and they are not a separate form:
    2010-99 and 2010-100 are consecutive documents of one unpadded series, so
    the floor cuts a continuous series and is held for consistency with the
    layer that reads it, not because the evidence puts a boundary there.
    The count is recorded so a future floor decision has it.

    The ceiling is measured rather than chosen: zero modern values reach a
    six-digit tail, and the largest sequence ever issued is 33,861 (2011), so
    refusing six leaves 3x headroom.
    """

    for below in ("2010-99", "2024-36", "2011-7"):
        assert mint_federal_register_document_iri(below) is None, below
        assert mint_federal_register_document_iri(below, column_licensed=True) is None, below
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
    already proved for two of them; licensed, all four mint through the
    partner hatch, the same escape hatch the pre-existing correction,
    republication and legacy forms already use.
    """

    for value in ("E9-654", "Z9-9", "X10-11220", "X09-101207", "E3-2013-2261"):
        assert mint_federal_register_document_iri(value) is None, value
        licensed = mint_federal_register_document_iri(value, column_licensed=True)
        assert licensed is not None, value
        assert licensed.scheme == "rkaf:partner-defined", value
        assert licensed.iri == f"urn:rkaf:partner:{PARTNER_NAMESPACE}:frdoc:{value}", value

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
    # in the pinned column are 1994-01-03 and 2009-08-19.
    for value in ("94-1", "94-120124", "95-170007", "97-339151", "08-1234"):
        licensed = mint_federal_register_document_iri(value, column_licensed=True)
        assert (licensed is not None) == (re.fullmatch(BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER, value) is not None)
        assert mint_federal_register_document_iri(value) is None, value


def test_the_bare_legacy_shape_stops_where_the_measurement_stops() -> None:
    """The tail runs three to six digits, and the floor is a named refusal.

    Three to five is the modern shape's own range and covers 394,121 values;
    the six-digit tail adds exactly 7, every one a real published document
    with its own publisher URL in the pinned corpus. 1,370 further values run
    ``\\d{2}-\\d{1,2}`` -- "00-10" is a real airworthiness directive of
    2000-01-04 -- and stay unminted, because widening a floor is a recall
    decision with its own budget rather than a side effect of this one.
    """

    shape = re.compile(BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER)
    assert shape.fullmatch("09-19806") and shape.fullmatch("94-120124")
    assert not shape.fullmatch("00-10") and not shape.fullmatch("00-1")
    assert not shape.fullmatch("94-1234567")
    assert mint_federal_register_document_iri("00-10", column_licensed=True) is None
    # Damage the column really carries, admitted by neither shape.
    for damaged in ("94-22818Filed", "94-S16142", "00-2999Doc", "95-95-744"):
        assert mint_federal_register_document_iri(damaged, column_licensed=True) is None, damaged


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
    a number to move. Re-measured 2026-08-31 (REF-052) over the same pinned
    file ``test_identifier_shapes`` reads, after ``identifier_shapes`` took
    the bare-legacy shape and the four letter-opening families home as
    column-licensed reads.

    The headline is still the 39.2%: without the column license, 394,128
    real documents have no identity of any kind, and the ingest lane that
    reads their bodies has nothing to join them on. What moved this cycle is
    the letter-opening bucket: 10,231 values that used to land in ``refused``
    now land here, because a shape being column-licensed (this cycle) is not
    the same event as a lexical space being widened (rc16) -- neither
    ``first-class`` nor ``bare-legacy`` moved by one value.

    The bucket a value falls into is now read from its own shape rather than
    inferred from whether the prose reader agreed: before this cycle
    "the prose reader refused it" and "it is bare-legacy" were the same fact,
    because nothing else reached the partner hatch through the column alone.
    They are not the same fact any more -- the four new families are also
    prose-refused and also column-only -- so the letter-opening bucket is
    now everything the bare-legacy shape does not fullmatch, whether the
    prose reader agrees (117,292 of it, unchanged) or not (10,231 more).

    There used to be a fifth bucket here, ``modern-short-tail``, counting the
    28,862 modern numbers the five-digit-wide ``rkaf:us-frdoc`` space refused.
    rulespec 0.2.0rc16 widened the space to ``[0-9]{4}-[0-9]{3,5}`` and that
    population is now first-class, so the bucket names nobody and is gone
    rather than pinned at zero. The loop below still proves it emptied: a
    partner-hatch value the prose reader reads can no longer be a modern-form
    document number, and the assertion says so where the branch used to be.
    """

    import pyarrow.parquet as pq

    bare_legacy_shape = re.compile(BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER)

    values: set[str] = set()
    for batch in pq.ParquetFile(FEDERAL_REGISTER_PARQUET).iter_batches(
        columns=["document_number"], batch_size=100_000
    ):
        values.update(value for value in batch.column(0).to_pylist() if value is not None)
    assert len(values) == 1_004_233

    census = dict.fromkeys(("first-class", "bare-legacy", "letter-opening", "refused"), 0)
    for value in values:
        prose = mint_federal_register_document_iri(value)
        column = mint_federal_register_document_iri(value, column_licensed=True)
        assert prose is None or prose == column, value  # the license only ever adds
        if column is None:
            census["refused"] += 1
        elif column.scheme == "rkaf:us-frdoc":
            census["first-class"] += 1
        elif bare_legacy_shape.fullmatch(value.strip().translate(identifier_shapes._DASHES)):
            census["bare-legacy"] += 1
        else:
            # The dead bucket, as an assertion. Every modern-form number the
            # shape layer reads is now inside the space, so nothing that
            # reaches the partner hatch -- through the prose reader or through
            # the four new column-only families alike -- can be one.
            assert not identifier_shapes.is_federal_register_document_number(value), value
            census["letter-opening"] += 1

    assert census == {
        # What rulespec can spell: 47.9% of the column, up from 45.0% before
        # the rc16 widening moved 28,862 documents in from the partner hatch.
        # Untouched by this cycle -- column licensing moves values between
        # the partner hatch and refused, never into or out of first-class.
        "first-class": 480_566,
        # §1.2: identity-less today, and the whole reason for the column
        # license. Unchanged: this cycle only moved the shape's HOME, not its
        # membership.
        "bare-legacy": 394_128,
        # Corrections, republications and legacy prefixes the prose reader
        # reads (117,292, unchanged) plus the four families REF-052/REF-054
        # admit this cycle (10,231 more): 5,829 three-digit-and-shorter
        # tails, 4,195 two-digit prefixes, 206 six-digit tails, and the
        # single legacy-prefix-over-modern-body hybrid. See
        # `identifier_shapes._FR_COLUMN_LETTER_FORMS`.
        "letter-opening": 127_523,
        # Damage and the shapes nobody has decided about: 0.2% of the column,
        # down from 1.2% before this cycle moved 10,231 letter-opening values
        # out. All 2,016 are named: 1,370 bare-legacy values with a one- to
        # three-digit tail (REF-052 licensed the short-tail widening for the
        # letter-opening family only; bare-legacy's own tail is a separate,
        # unmade ruling); 286 modern numbers with a one- or two-digit tail,
        # deliberately left below the widened floor; 228 `-2`-suffixed
        # collision values; 99 short-tail corrections REF-054 keeps refused;
        # 32 colophon-fused values (9 letter-opening + 23 bare-legacy); and
        # `granule293`, the one non-identifier extraction artifact. None is
        # an oversight: 1,370 + 286 + 228 + 99 + 32 + 1 = 2,016.
        "refused": 2_016,
    }
    assert sum(census.values()) == len(values)
    # The partner hatch, derived rather than pinned separately.
    assert census["bare-legacy"] + census["letter-opening"] == 521_651


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
