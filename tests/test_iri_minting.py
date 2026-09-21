"""The minting layer, each rule pinned by the evidence that bought it.

Every specimen is a real identifier: Federal Register document numbers and
bare-legacy witnesses from the pinned ``document_number`` column (1,004,233
distinct, read 2026-08-31), RINs/dockets/CFR parts from :mod:`identifier_shapes`
and :mod:`citation_grammar`. The lexical spaces are rulespec's, restated here
and held true against the vendored ``rulespec-conformance`` wheel by the first
test in this file.
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
    # which is a population the hatch still holds (127,523 of them; 117,292
    # is the PROSE reader's share of it, not the hatch's).
    ("frdoc-short-tail", mint_federal_register_document_iri("2011-237")),
    ("frdoc-partner", mint_federal_register_document_iri("E8-24348")),
    ("frdoc-bare-legacy", mint_federal_register_document_iri("09-19806", column_licensed=True)),
    ("partner", mint_partner_iri("proceeding", "EPA-HQ-OAR-2021-0317")),
)


# --------------------------------------------------------------------------- #
# The contract this module restates.


def test_the_minted_spaces_are_the_contract_verbatim() -> None:
    """Pin that IDENTIFIER_SPACES restates the vendored rkaf contract verbatim, in all four compiled forms.

    Reading patterns out of the package at runtime would make the module agree
    with whatever shipped rather than what was reviewed, so they are restated
    with only two transcription normalizations: non-capturing groups and the
    escaped literal dot.
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
    """Pin that every minted scheme is one the vendored rulespec enum declares, so a rename upstream breaks here rather
    than reaching a consumer.
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
    """Pin every family against its declared space and rkaf's generic identifier floor, the same floor canonical_usc_iri
    is checked against.
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
    """Pin that MintedIdentifier raises for an undeclared scheme and for an IRI outside its scheme's space.

    The minters refuse with ``None``; the raise exists for a consumer
    assembling the pair by hand, the only way an unchecked identifier could
    reach rkaf.
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
    """Pin that equivalent spellings converge to one identifier across RIN case, docket labels, zero-padded CFR titles,
    and unicode dashes.
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
    """Pin title/part/section minting (7 CFR 273.9, 49 CFR 1.95) and the part-only form."""

    assert mint_cfr_iri(7, "273", "9").iri == "urn:rkaf:us:cfr:7:273.9"
    assert mint_cfr_iri(49, "1", "95").iri == "urn:rkaf:us:cfr:49:1.95"
    assert mint_cfr_iri(40, "60").iri == "urn:rkaf:us:cfr:40:60"
    assert mint_cfr_iri(7, "273", "9").scheme == "rkaf:us-cfr"


def test_a_cfr_subsection_resolves_to_its_section() -> None:
    """Pin that a subsection parenthetical is dropped to its section rather than refusing the whole citation."""

    assert mint_cfr_iri(40, "60", "18(a)") == mint_cfr_iri(40, "60", "18")


def test_a_lettered_cfr_part_mints_and_its_case_is_folded() -> None:
    """Pin that lettered parts (7 CFR 15a) stay distinct from their numeric sibling, with the uppercase fold lossless.

    83 of the OFR's 272 non-numeric parts carry a single letter; every ancestor
    of the grammar merged "15" and "15a", and the fold is the only path that
    makes the publisher's uppercase spellings (26 CFR 16A and three others)
    mintable without truncating them.
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
    """Pin that the space accepts a hyphen-numbered part while the minter refuses it, and that "41 CFR 101-1" reads as
    phantom part 101 today.

    The prose reader stops at the hyphen, so minting the hyphen form would swap
    a named, tested gap for a silent wrong answer; the fix belongs upstream in
    ``citation_grammar._CFR_PART_CAPTURE`` and REF-054 records the trigger.
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
    """Pin that the grammar keeps an impossible title for inspection while the minter refuses it, reserving only title
    35.
    """

    assert mint_cfr_iri(CFR_TITLE_COUNT, "1") is not None
    assert mint_cfr_iri(CFR_TITLE_COUNT + 1, "1") is None
    assert mint_cfr_iri(35, "1") is not None  # Reserved today; the Panama Canal until 2000
    assert mint_cfr_iri(0, "1") is None
    assert mint_cfr_iri(16, "0").iri == "urn:rkaf:us:cfr:16:0"  # Published Organization part.


def test_a_section_that_states_nothing_is_no_section_rather_than_a_bad_one() -> None:
    """Pin that blank-section sentinels from ``states_nothing`` fall back to the part while a stated unspellable section
    refuses the citation.
    """

    for blank in (None, "", "  ", "None", "N/A", "Not Yet Determined"):
        assert mint_cfr_iri(40, "60", blank) == mint_cfr_iri(40, "60"), blank
    for unspellable in ("60 to 65", "Appendix A", "18.5"):
        assert mint_cfr_iri(40, "60", unspellable) is None, unspellable


def test_the_part_canonicalization_agrees_with_the_grammar() -> None:
    """Pin that minting from raw components and from a parsed citation land on one identifier for padded and subsection
    forms.
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
    """Pin EO minting from the number (12866, 13990, 14008)."""

    assert mint_executive_order_iri(12_866).iri == "urn:rkaf:us:eo:12866"
    assert mint_executive_order_iri("13990").iri == "urn:rkaf:us:eo:13990"
    assert mint_executive_order_iri(14_008).scheme == "rkaf:us-eo"


def test_an_order_beyond_the_dated_bound_still_mints() -> None:
    """Pin that EO_HIGHEST_KNOWN is a dated capture bound, not a minting fence: the next order still mints."""

    assert mint_executive_order_iri(EO_HIGHEST_KNOWN) is not None
    assert mint_executive_order_iri(EO_HIGHEST_KNOWN + 1_000) is not None


def test_what_is_not_an_order_number_mints_nothing() -> None:
    """Pin that the series starts at 1: zero, empty, malformed, and page-locator forms mint nothing."""

    for stated in (0, "0", "", None, "12866.0", "EO 12866", "12,866", "٣"):
        assert mint_executive_order_iri(stated) is None, stated


# --------------------------------------------------------------------------- #
# RINs.


def test_a_rin_mints_and_a_sentinel_does_not() -> None:
    """Pin RIN minting and refusal of the literal "Not Assigned" sentinel (56,364 of 64,537 catalog values).

    The minter wraps a validator that answers "is this string one", never "does
    it contain one"; admitted by containment the sentinel became the corpus's
    most common identifier tenfold.
    """

    assert mint_rin_iri("2060-AV16").iri == "urn:rkaf:us:rin:2060-AV16"
    assert mint_rin_iri("0301-AA00").iri == "urn:rkaf:us:rin:0301-AA00"
    assert mint_rin_iri("2060-AV16 ").iri == "urn:rkaf:us:rin:2060-AV16"  # surrounding space is not identity
    for stated in ("Not Assigned", "", None, "RIN 2060-AV16", "3235-0695", "2060-AV1"):
        assert mint_rin_iri(stated) is None, stated


def test_a_rin_the_shape_admits_and_rkaf_cannot_spell_is_refused() -> None:
    """Pin the syntax distinction: the shape admits ``[A-Za-z0-9]{2}`` but rkaf's space closes on ``[0-9]{2}``."""

    assert identifier_shapes.is_regulation_identifier_number("0648-ABCD")
    assert mint_rin_iri("0648-ABCD") is None


def test_a_real_rin_outside_the_shape_is_refused_not_repaired() -> None:
    """Pin that five real-but-out-of-shape RINs are refused rather than repaired; refusal contradicts no historical
    publisher attestation.
    """

    for real_but_unminted in ("0648-XD990", "0648-XC705", "3090-00XX", "1115-09AE", "2070-78AB"):
        assert mint_rin_iri(real_but_unminted) is None, real_but_unminted


# --------------------------------------------------------------------------- #
# Regulations.gov dockets.


def test_a_docket_mints_through_the_label_and_not_around_it() -> None:
    """Pin strip-then-validate: labels are stripped (DOC-2010-0001 survives), a digit-opening remainder is not an
    identifier, and a FERC-shaped docket refuses.
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
    """Pin that the docket minter is exactly as wide as the column reader it wraps, so a document id must not be handed
    to it.

    The column reader absorbs "EPA-HQ-OAR-2021-0317-0001" whole; the prose
    reader arbitrates the same characters as a document, and that arbitration
    belongs upstream.
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
    """Pin Public Law minting from the compound the grammar produces (119-101, 116-260)."""

    assert mint_public_law_iri("119-101").iri == "urn:rkaf:us:pl:119-101"
    assert mint_public_law_iri("116-260").iri == "urn:rkaf:us:pl:116-260"
    assert mint_public_law_iri("119-101").scheme == "rkaf:us-pl"


def test_a_law_of_a_congress_that_has_not_sat_still_mints() -> None:
    """Pin that CONGRESS_CURRENT is a dated fact, not a minting fence: the next Congress's first law mints."""

    assert mint_public_law_iri(f"{CONGRESS_CURRENT + 1}-1") is not None


def test_what_is_not_a_public_law_number_mints_nothing() -> None:
    """Pin that a session-law chapter ("1955:360") and malformed forms mint nothing."""

    for stated in ("1955:360", "Pub. L. 119-101", "119", "119-", "0-1", "119-0", "", None):
        assert mint_public_law_iri(stated) is None, stated


# --------------------------------------------------------------------------- #
# Federal Register documents: the three outcomes.


def test_a_modern_document_number_rkaf_can_spell_mints_first_class() -> None:
    """Pin modern-form document numbers as first-class rkaf:us-frdoc identifiers (480,566 of 1,004,233 distinct values).
    """

    for value in ("2024-00366", "2026-13078", "2012-00019"):
        minted = mint_federal_register_document_iri(value)
        assert minted == MintedIdentifier(scheme="rkaf:us-frdoc", iri=f"urn:rkaf:us:frdoc:{value}"), value


def test_a_short_tail_is_real_and_is_now_first_class() -> None:
    """Pin that three- and four-digit tails are first-class since rc16 widened the space to ``[0-9]{4}-[0-9]{3,5}``.

    The widening splits no identity: across all 480,566 admitted values no
    document has both a padded and an unpadded spelling, so no value gained a
    second first-class identifier.
    """

    assert IDENTIFIER_SPACES["rkaf:us-frdoc"].fullmatch("urn:rkaf:us:frdoc:2011-237")
    for value in ("2010-5997", "2011-237", "2012-999", "2013-1234"):
        minted = mint_federal_register_document_iri(value)
        assert minted is not None, value
        assert minted.scheme == "rkaf:us-frdoc", value
        assert minted.iri == f"urn:rkaf:us:frdoc:{value}", value


def test_the_floor_under_the_widened_tail_is_where_the_shape_layer_puts_it() -> None:
    """Pin the three-digit floor as co-extensive with ``identifier_shapes``: below it values mint only through the
    partner hatch, and six-digit tails refuse.

    The floor cuts a continuous series and is held for consistency with the
    layer that reads it, not because evidence puts a boundary there; the
    ceiling is measured (zero six-digit tails, largest sequence ever 33,861).
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
    """Pin that E/C/R letter-opening forms mint through the partner hatch using only shapes the shape layer already
    reads whole.
    """

    for value in ("E7-21559", "C1-2026-13078", "R1-2010-13257", "R1-10679"):
        minted = mint_federal_register_document_iri(value)
        assert minted is not None, value
        assert minted.scheme == "rkaf:partner-defined", value

    for real_but_unread in ("Z9-802", "E9-23", "X10-11220", "E3-2013-2261"):
        assert mint_federal_register_document_iri(real_but_unread) is None, real_but_unread
    assert mint_federal_register_document_iri("FR Doc. 2026-13078") is None


def test_the_four_letter_opening_families_need_the_column_license_too() -> None:
    """Pin REF-052/REF-054's four letter-opening families at the mint layer: unlicensed they are unread, licensed E/Z/E3
    still use the hatch while X moved to its own rkaf:us-frdoc-x space in rc18 (REF-065).
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
    """Pin §1.2: a bare legacy number is unread in prose and mints only under ``column_licensed``, through the partner
    hatch.
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
    """Pin the bare-legacy tail at three to six digits: short tails go through REF-056's sibling production, seven-plus
    refuse, and four named unadmitted column values stay refused.
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
    """Pin REF-056's one- and two-digit bare-legacy tails (1,370 values) as column-licensed-only partner-hatch mints,
    with the six-digit ceiling untouched.
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
    """Pin REF-056's one- and two-digit modern tails (286 values) as column-licensed-only partner-hatch mints, leaving
    rulespec's own space untouched.
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
    """Pin that padding is identity: padded and unpadded spellings stay different identifiers, including the three real
    near-collision pairs.

    The pad is preserved because it is the spelling the publisher issued;
    nothing is folded away, and the letter of a letter-opening value is kept
    for the same reason.
    """

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
    """Pin the partner hatch's lossless percent-encoded layout, its kind and value fences, and that reusing a real
    family's word as the kind is deliberate, not a shadow.
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
    """Pin the full ``document_number`` census (1,004,233 distinct) and its exact eight-class refusal partition (365
    values).

    The headline is unchanged: without the column license 394,128 real
    documents shaped exactly ``BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER``
    have no identity at all. REF-056's two new productions hold 1,370
    bare-legacy and 286 modern short tails -- counted separately because those
    are the strata the evidence argues -- and REF-066's five modern-form
    collisions refuse outright rather than being laundered into another bucket.
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
    """Pin that all 46,547 Agenda RINs mint, with no gap on this roster between the shape's ``[A-Za-z0-9]{2}`` and
    rkaf's ``[0-9]{2}``.
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
    """Pin the property the mint layer adds over the real ``docket_ids_json`` column: whatever the validator accepts,
    the scheme can spell.
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
    """Pin rc17's qualified legacy space: with a publication date a bare number mints as
    ``urn:rkaf:us:frdoc-legacy:<value>:<day>``.
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
    """Pin the negative fixture that justifies dating: "00-111" names two different documents, so undated it would merge
    them.
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
    """Pin that without a date a legacy number keeps the partner hatch rather than an identity whose date was guessed
    from the number.
    """

    undated = mint_federal_register_document_iri("09-19806", column_licensed=True)
    assert undated is not None
    assert undated.scheme == "rkaf:partner-defined"
    assert undated.iri == "urn:rkaf:partner:refspec:frdoc:09-19806"

    # The column license still governs: a date does not admit a value the
    # prose reader refuses, because the date is not a license.
    assert mint_federal_register_document_iri("09-19806", publication_date="2009-08-19") is None


def test_a_year_prefix_that_disagrees_with_its_date_still_mints() -> None:
    """Pin that the year prefix is a spelling, not a fence: 07-6308 published 2008-01-15 mints, one of 1,661
    year-boundary spills.
    """

    spilled = mint_federal_register_document_iri(
        "07-6308", column_licensed=True, publication_date="2008-01-15"
    )
    assert spilled is not None
    assert spilled.iri == "urn:rkaf:us:frdoc-legacy:07-6308:2008-01-15"


def test_a_publication_date_that_is_not_a_day_is_loud() -> None:
    """Pin that a non-day publication_date raises rather than downgrading to the hatch, while the compact ISO spelling
    mints the same identity.
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
    """Pin that rkaf:us-frdoc answers first, so a date never qualifies a modern identity."""

    assert mint_federal_register_document_iri(
        "2024-00366", publication_date="2024-03-08"
    ) == mint_federal_register_document_iri("2024-00366")


# --------------------------------------------------------------------------- #
# The self-dating X space (rulespec 0.2.0rc18, REF-065).


def test_an_x_number_mints_without_a_date_because_it_carries_one() -> None:
    """Pin the self-dating X space: the number's last four digits are month and day, agreeing with publication_date on
    4,400 of 4,400 rows.
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
    """Pin that the X prefix is identity: 2,382 of 4,400 X numbers have a bare twin that is a different document."""

    x = mint_federal_register_document_iri("X94-10503", column_licensed=True)
    bare = mint_federal_register_document_iri(
        "94-10503", column_licensed=True, publication_date="1994-05-03"
    )
    assert x is not None and bare is not None
    assert x.iri != bare.iri
    assert x.scheme == "rkaf:us-frdoc-x"
    assert bare.scheme == "rkaf:us-frdoc-legacy"


def test_an_x_number_whose_own_day_contradicts_the_caller_is_loud() -> None:
    """Pin the self-dating property as load-bearing: a stated date that contradicts the number raises rather than
    minting quietly.
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
    """Pin the deliberate seven-digit-tail gap: rulespec's space is bounded by capacity, this shape layer by
    measurement, so a seven-digit X is spellable but not auto-detected.
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
    """Pin REF-066's negative fixture: the five genuine collisions refuse, the two one-matter-published-twice values
    still mint.
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
    """Pin the refusal mechanism: a collision refuses before every branch, including the partner hatch, monkeypatched so
    it holds without the census.
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
    """Pin that an ordinary mint is repository-independent: the collision witness, census, git root, and git are never
    reached.

    An audit on 2026-09-02 found the earlier census-first order raising for
    ``2024-00366`` from an installed layout (REF-066).
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
