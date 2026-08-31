"""The minting layer: shapes in, one canonical ``urn:rkaf`` identifier out.

:mod:`refspec.registry.identifier_shapes` names the hole this module fills:
*"IRI minting (``urn:rkaf:...``) stays with consumers until the minting layer
is its own port."* No consumer ever did it. Before this module the whole
platform minted exactly one family — ``act_resolution.canonical_usc_iri``,
``urn:rkaf:us:usc:...`` — while the shapes for six others sat validated and
nameless in :mod:`identifier_shapes` and :mod:`citation_grammar`.

A grammar is not a minter. rulespec owns the ``urn:rkaf`` grammar
normatively; what belongs here is the executable step from a validated shape
to the one identifier that shape names, and the refusal of everything else.

The three rules this module is
-----------------------------

- **The shape layer decides, this layer spells.** Every minter below wraps a
  validator that already exists — :func:`~identifier_shapes.normalize_rin`,
  :func:`~identifier_shapes.normalize_docket_reference`,
  :func:`~identifier_shapes.is_federal_register_document_number`,
  :func:`~identifier_shapes.detect_identifier_shapes`,
  :data:`~citation_grammar.CFR_TITLE_COUNT` — and adds no second opinion
  about what a real identifier looks like. Where a minter is narrower than
  the validator it wraps, the narrowing is rulespec's lexical space and is
  named at the site.

- **The candidate is minted and then checked against the contract.** The
  seven lexical spaces in :data:`IDENTIFIER_SPACES` are restated **verbatim**
  from the compiled rulespec profiles this repository vendors, the way
  ``act_resolution._RKAF_USC_IRI`` restates the U.S.C. one, and
  ``test_the_minted_spaces_are_the_contract_verbatim`` holds the copies true
  against the vendored package. So what a minter will emit is exactly what
  rulespec's own validators accept — there is no paraphrase to drift.

- **Refusal is ``None``; a broken invariant raises.** A value that states no
  identifier is a measured population, not an error: 39.2% of the pinned
  Federal Register ``document_number`` column takes a shape rulespec cannot
  spell, and an exception per row is not what that is. So every minter is a
  total function returning ``MintedIdentifier | None``. ``ValueError`` is
  reserved for :class:`MintedIdentifier` itself, which refuses to exist
  outside a declared scheme's space — the convention
  ``usc_section_oracle`` uses for its verdicts. The one existing minter
  raises instead, and both of its call sites
  (``act_resolution.py:749,772``) catch the exception immediately and turn it
  back into a refusal; this module keeps the raise where it means something
  and hands out the refusal.

Two readers, and the one place the column is the license
--------------------------------------------------------
:mod:`identifier_shapes` splits its readers in two — the **prose reader**,
handed running text, whose grammar is deliberately narrow, and the **column
reader**, handed a field whose name already declares what it holds. Minting
inherits that split at exactly one place:
:func:`mint_federal_register_document_iri` takes ``column_licensed``, and only
that flag admits :data:`BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER`. Prose
detection is not loosened by a single character, because nothing here is
asking it to be.

The docket minter inherits the other half of the same doctrine and it is
easier to misread: it wraps a COLUMN reader, so it mints what a
``docket_ids_json`` value states, including a Regulations.gov document id that
fits the docket shape. See :func:`mint_regulations_gov_docket_iri`.

What rkaf cannot spell today, measured
--------------------------------------
Every number below was measured 2026-08-31 against the same two pinned
columns :mod:`identifier_shapes` and its tests read — the Federal Register
corpus's ``document_number`` (1,004,233 distinct, in
``spicy-regs/output/rulespec-stabilization-candidate-final/
federal_register.parquet``) and the Unified Agenda's ``rin`` (46,547
distinct). Mostly they are recorded here because a lexical space that cannot
spell a real thing is **a gap in rkaf, ours to fix**, never a fact about the
thing — the posture ``act_resolution`` takes with statutory notes and section
ranges. The RIN entry is the exception that proves the rule has a direction,
and it is the last one below.

Two of these gaps closed in rulespec ``0.2.0rc16`` (REF-054), which is why
this section reads shorter than it did.

- **CLOSED: the Federal Register document space was five digits wide and the
  series is not.** ``rkaf:us-frdoc`` is now ``[0-9]{4}-[0-9]{3,5}``, and the
  **28,862** modern-form numbers refused for a three- or four-digit tail —
  2,599 with three, 26,263 with four, all of them published 2010-2013 — are
  first-class. 2010-5997, 2011-237 and 2012-00019 are three of them, each
  confirmed against the publisher's own API on 2026-08-22. First-class
  coverage went **451,704 → 480,566** of 1,004,233, 45.0% → **47.9%**.
- **STILL OPEN, and deliberately: 286 modern numbers below the floor.**
  ``2010-99`` and ``2010-100`` are consecutive documents of one unpadded
  series, and the space admits the second and refuses the first. The floor
  holds at three digits because that makes ``rkaf:us-frdoc`` exactly
  co-extensive with ``identifier_shapes.FEDERAL_REGISTER_DOCUMENT_NUMBER``
  (``\\d{4}-\\d{3,5}``), so the space caught up to the shape layer rather than
  overtaking it. That is a **consistency** argument, not an evidential one;
  the count is written down so a future floor decision has it, the way the
  1,370 ``\\d{2}-\\d{1,2}`` values are written down at
  :data:`BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER`.
- **STILL OPEN as a gap in rkaf, CLOSED as an identity gap: 394,128 (39.2%)
  are the bare-legacy form.** No rulespec space reaches them — that has not
  changed — but as of this cycle (REF-052) the shape moved home to
  ``identifier_shapes.BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER`` and
  reads through that module's own ``column_licensed`` flag rather than a
  local copy here. Every one of these documents still identifies, through
  the partner hatch; only ``rkaf:us-frdoc`` itself is the gap.
- **CLOSED: the letter-opening family's identical short-tail hole, and three
  siblings with it.** REF-052/REF-054 named four letter-opening families
  with a verified live example and 10,340 unread values between them;
  ``identifier_shapes``'s column reader now reads **10,231** of them —
  **5,829** three-digit-and-shorter tails (the short-tail hole this bullet
  used to leave open), **4,195** two-digit prefixes, **206** six-digit tails,
  and the single legacy-prefix-over-modern-body hybrid. The remaining 109
  stay refused, deliberately: 99 short-tail corrections (96 of them naming an
  original document the widening above just made first-class), 9
  colophon-fused values, and 1 non-identifier extraction artifact — see
  ``identifier_shapes._FR_COLUMN_LETTER_FORMS`` for the measurement and the
  publisher pages each family was read against. None of this is a gap in
  rkaf: every value here was always outside ``rkaf:us-frdoc``'s space and
  stays outside it, identified through the partner hatch rather than
  first-class.
- **CLOSED for letters, REFUSED for hyphens: the CFR part.** ``rkaf:us-cfr``
  now writes the part as ``[0-9]+([a-z]|-[0-9]+)?``, covering all 272 of the
  8,424 parts in the OFR's published subject index that are not plain digits
  (``citation_grammar.CFR_LETTERED_PART_SHARE``, which stays ``(272, 8424)``
  — only its consequence changed). :func:`mint_cfr_iri` mints the **83**
  single-letter parts and refuses the **189** hyphen-numbered ones, a
  narrowing against the space that :func:`_cfr_part` states and justifies.
  It spells **8,226 of the 8,424** pairs end to end (97.65%) — the 189 plus
  nine index rows whose part is literally ``0``, which there is no part 0 to
  name.
- **The RIN space is narrower than the shape, and here the direction is the
  other way round.** ``rkaf:us-rin`` closes on ``[0-9]{2}`` where
  ``identifier_shapes._RIN`` allows ``[A-Za-z0-9]{2}``, and zero of the
  46,547 RINs take the divergent form. This one is **not a gap in rkaf**:
  the only published RIN format statement anywhere — the Fish and Wildlife
  Service handbook's "two letters followed by two numbers", recorded at
  ``identifier_shapes.py:344-352``, which says in the same breath that its
  own shape is *"a chosen lexical space, not the publisher's
  specification"* — **is** ``[A-Z]{2}[0-9]{2}``. rkaf matches the publisher
  and RefSpec's column shape is the loose one; this module's own prose
  reader (``citation_grammar._RIN_TOKEN``) agrees with rkaf, not with the
  column shape. So the divergence was re-examined in rc16 and rkaf was left
  alone. It stays pinned by a refusal test, which is the alarm for the day a
  roster carries one — not a defect waiting to be fixed.

The whole ``document_number`` column, sorted by what it can carry and pinned
by ``test_the_document_number_column_is_accounted_for_exactly``: **480,566**
first-class, **521,651** under the partner hatch (394,128 bare-legacy +
127,523 letter-opening), **2,016** refused. 99.8% identified, against 47.9%
if only rkaf's own spaces are minted into and 0% before this module existed.
The census had a fifth bucket for the 28,862 modern short tails; the widening
emptied it, so it is gone rather than pinned at zero. This cycle (REF-052)
moved **10,231** values from refused into the letter-opening bucket
(117,292 → 127,523) without moving a single value into or out of first-class
— the four families it admits are column-licensed, not rulespec-widened, so
the split between first-class and partner-hatch is untouched.

Anything the space cannot spell is still identified, never dropped: it takes
rulespec's own ``rkaf:partner-defined`` escape hatch under
:func:`mint_partner_iri`, whose segment layout is copied from rulespec's own
fixtures (``urn:rkaf:partner:fixture:proceeding:EPA-HQ-OAR-2021-0317`` in
``artifact-us-frdoc-positive.jsonld``) with this repository as the partner.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote

from refspec.registry.citation_grammar import CFR_TITLE_COUNT, states_nothing
from refspec.registry.identifier_shapes import (
    _DASHES,  # the shape layer's own table, shared deliberately -- see its docstring
    BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER,
    IdentifierKind,
    detect_identifier_shapes,
    is_federal_register_document_number,
    normalize_docket_reference,
    normalize_rin,
)

__all__ = [
    "BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER",
    "IDENTIFIER_SPACES",
    "PARTNER_NAMESPACE",
    "MintedIdentifier",
    "mint_cfr_iri",
    "mint_executive_order_iri",
    "mint_federal_register_document_iri",
    "mint_partner_iri",
    "mint_public_law_iri",
    "mint_regulations_gov_docket_iri",
    "mint_rin_iri",
]

# --------------------------------------------------------------------------- #
# The contract, restated verbatim.

#: rulespec's lexical spaces, one per scheme this module mints into, restated
#: **verbatim** from the compiled profiles in the vendored
#: ``rulespec-conformance`` wheel. Each is stated identically in all four
#: compiled forms — JSON Schema, SHACL, Rego and TypeScript — and
#: ``test_the_minted_spaces_are_the_contract_verbatim`` sweeps the package to
#: hold these copies true, the way ``act_resolution`` holds its single copy
#: true. Restating rather than reading the package at runtime is deliberate:
#: reading it would make this module agree with whatever shipped rather than
#: with what was reviewed.
#:
#: The one edit to each string is making its groups non-capturing, which the
#: verbatim test undoes before comparing. ``rkaf:partner-defined`` is the
#: exception and says so at :data:`_PARTNER_IRI`: rulespec states no lexical
#: space for it, because the point of the escape hatch is that it has none.
_US_CFR = re.compile(r"^urn:rkaf:us:cfr:[1-9][0-9]*:[0-9]+(?:[a-z]|-[0-9]+)?(?:\.[0-9]+[a-z]{0,3}(?:-[0-9a-z]+)*)?$")
_US_EO = re.compile(r"^urn:rkaf:us:eo:[1-9][0-9]*$")
_US_FRDOC = re.compile(r"^urn:rkaf:us:frdoc:[0-9]{4}-[0-9]{3,5}$")
_US_PL = re.compile(r"^urn:rkaf:us:pl:[1-9][0-9]*-[1-9][0-9]*$")
_US_REGSGOV = re.compile(r"^urn:rkaf:us:regsgov:[A-Z0-9]+(?:[-_][A-Z0-9]+)*$")
_US_RIN = re.compile(r"^urn:rkaf:us:rin:[0-9]{4}-[A-Z]{2}[0-9]{2}$")

#: This repository, as the partner. rulespec's own fixtures write a
#: partner-defined identifier as ``urn:rkaf:partner:<namespace>:<kind>:<value>``
#: — ``urn:rkaf:partner:fixture:proceeding:EPA-HQ-OAR-2021-0317`` — so the
#: layout is the publisher's, not an invention, and only the namespace is
#: ours. The archived spicy-regs minter reached for its own URN prefix
#: (``urn:spicy-regs:frdoc:...``) instead, which named nothing rkaf could
#: resolve; naming the partner INSIDE the rkaf URN keeps the escape hatch
#: inside the vocabulary it escapes from.
PARTNER_NAMESPACE = "refspec"

#: A partner ``kind`` is a plain lowercase family word — no colon, no case
#: variant, no leading digit — so a partner identifier always parses back
#: into its five segments unambiguously ("us:usc" as a kind would spell a
#: string that reads as six). What the fence does NOT do is refuse a real
#: family's word: :func:`mint_federal_register_document_iri` deliberately
#: mints kind ``frdoc`` beside the real ``rkaf:us-frdoc`` space, because an
#: unspellable member of a family is still a member of it. The
#: ``urn:rkaf:partner:refspec:`` prefix, not the kind, is what keeps the
#: partner namespace apart from rulespec's own.
_PARTNER_KIND = re.compile(r"[a-z][a-z0-9-]*")

#: The partner space. Its body is whatever :func:`mint_partner_iri`
#: percent-encodes, so the alphabet is RFC 3986's unreserved set plus the
#: escape character — which is also what makes the result satisfy
#: :data:`_RKAF_IDENTIFIER` for free.
_PARTNER_IRI = re.compile(rf"^urn:rkaf:partner:{PARTNER_NAMESPACE}:[a-z][a-z0-9-]*:[A-Za-z0-9._~%-]+$")

#: Scheme -> the space an identifier in it must live in. The scheme names are
#: rulespec's ``#USRegulatoryIdentifierScheme`` / ``#AgendaItemIdentifierScheme``
#: / ``#ArtifactIdentifierScheme`` enum members; a :class:`MintedIdentifier`
#: outside this table cannot be constructed at all. (The RIN enum is
#: ``#AgendaItemIdentifierScheme``, defined at ``rulemaking.cue:11``. This
#: comment used to say ``#RinIdentifierScheme``, which rulespec has never
#: defined.)
IDENTIFIER_SPACES: Mapping[str, re.Pattern[str]] = {
    "rkaf:us-cfr": _US_CFR,
    "rkaf:us-eo": _US_EO,
    "rkaf:us-frdoc": _US_FRDOC,
    "rkaf:us-pl": _US_PL,
    "rkaf:us-regsgov": _US_REGSGOV,
    "rkaf:us-rin": _US_RIN,
    "rkaf:partner-defined": _PARTNER_IRI,
}

#: What rkaf requires of ANY identifier, whatever its scheme:
#: ``rkaf:hasArtifactIdentifier`` and ``rkaf:hasRegulatoryIdentifier`` are both
#: constrained to this in every compiled profile. It is the floor every space
#: above sits on, checked separately so a future space cannot be added that
#: satisfies itself and not the floor — the structural check the U.S.C.
#: precedent's family would apply to anything claiming to be one of these.
_RKAF_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")


# --------------------------------------------------------------------------- #
# The Federal Register's bare-legacy document number.
#
# MOVED HOME 2026-08-31 (REF-052): the shape, its evidence, and the dash-fold
# table this module used to mirror all now live in
# ``identifier_shapes.BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER`` and
# ``identifier_shapes._DASHES``, imported above rather than restated. That
# module is content-hashed into a build receipt, which is why the shape lived
# here instead until this cycle's rebuild unit. Nothing about what this
# module MINTS changes: ``mint_federal_register_document_iri``'s
# ``column_licensed`` flag reads the identical shape it read before, now
# through :func:`~identifier_shapes.is_federal_register_document_number`
# rather than a local pattern.


# --------------------------------------------------------------------------- #
# The minted value.


@dataclass(frozen=True)
class MintedIdentifier:
    """One identifier, and the rulespec scheme whose space it satisfies.

    Both halves, because rulespec requires both: an artifact carrying
    ``rkaf:hasRegulatoryIdentifier`` is invalid without
    ``rkaf:regulatoryIdentifierScheme`` beside it, and the scheme is precisely
    what differs between a Federal Register number rkaf can spell and one it
    cannot. A minter that returned the IRI alone would make every consumer
    re-derive the half that carries the news.

    Constructing one outside a declared scheme's space raises, and that is the
    module's whole structural guarantee: no minter can emit an identifier
    rulespec's validators would reject, because the type will not hold one.
    """

    scheme: str
    iri: str

    def __post_init__(self) -> None:
        space = IDENTIFIER_SPACES.get(self.scheme)
        if space is None:
            raise ValueError(f"undeclared identifier scheme: {self.scheme!r}")
        if not space.fullmatch(self.iri):
            raise ValueError(f"{self.iri!r} is outside the lexical space of {self.scheme}")
        if not _RKAF_IDENTIFIER.fullmatch(self.iri):
            raise ValueError(f"{self.iri!r} is not a well-formed rkaf identifier")


def _mint(scheme: str, iri: str) -> MintedIdentifier | None:
    """The candidate, or ``None`` when the contract will not hold it.

    The one place the two conventions meet: the type raises because a
    malformed pair is a broken invariant, and a minter refuses because a value
    outside a space is data. Written once so no minter restates the space
    check that :class:`MintedIdentifier` already performs.
    """

    try:
        return MintedIdentifier(scheme=scheme, iri=iri)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Spelling helpers. Selecting and folding only -- never inventing.


def _stated(value: object) -> str:
    """The characters a value states, stripped. Only ``None`` states nothing.

    Mirrors ``identifier_shapes._stated_text``, including its reason: one
    coercion, so two readers cannot disagree about the same value.
    ``str(value or "")`` made the falsy integer 0 state nothing.
    """

    return "" if value is None else str(value).strip()


def _positive_integer(value: object) -> str | None:
    """The canonical decimal a value states, or ``None``.

    A leading zero is spelling, not identity, and stripping it is the
    ``citation_grammar._canonical_part`` rule — "the part is a JOIN KEY, and
    '0718' must meet '718'" — applied wherever rulespec writes an integer
    production. The Unified Agenda's filers pad: 95 of its CFR titles are
    written "07 CFR 1943", and every one is USDA's title 7.

    ``[0-9]`` rather than ``str.isdigit``: that predicate is true of Unicode
    digits, and ``int("٧")`` is 7, which would let a minter emit an identifier
    no publisher wrote.
    """

    text = _stated(value)
    if re.fullmatch(r"[0-9]+", text) is None:
        return None
    return text.lstrip("0") or None


def _cfr_part(value: object) -> str | None:
    """A CFR part: the canonical decimal, optionally one lowercased letter.

    ``rkaf:us-cfr`` writes the part as ``[0-9]+([a-z]|-[0-9]+)?``, and this
    helper is deliberately narrower than that: it mints the numeric and
    single-letter forms and REFUSES the hyphen-number form. The narrowing is
    the same kind :func:`mint_cfr_iri` already makes against the title, and it
    is named here rather than left to be discovered.

    **The letter branch.** ``[a-z]`` was 83 of the OFR index's 272 non-numeric
    parts, and it has a live producer: ``parse_cfr_citations("7 CFR 15a")``
    returns part ``15a`` today. Four parts are published UPPERCASE — 26 CFR
    16A, 29 CFR 4022B, 29 CFR 4041A, 46 CFR 147A — and the prose reader emits
    the uppercase spelling verbatim, so folding here is the only thing that
    makes them mintable. The fold is lossless: no part collides with another
    under it anywhere in the index, and each of those four titles also has the
    bare numeric part (26 CFR 16, 29 CFR 4022, ...), which is why the rule is
    to fold and never to truncate.

    **The hyphen branch, refused.** The other 189 non-numeric parts are
    hyphen-numbered (41 CFR 101-1), and every single one is in title 41. This
    layer cannot produce one and must not pretend to:
    ``citation_grammar._CFR_PART_CAPTURE`` stops at the hyphen, which is the
    RIGHT answer in 48 of the 49 titles, because a hyphen after a part number
    usually means a range (40 CFR 60-63), a section written loosely (28 CFR
    23-4 for §23.4) or a numbered standard (49 CFR 571-108) — none of them a
    part. Title 41 is the sole exception, and separating it from the other
    three readings needs a title-conditional rule that does not exist.

    DEFERRED, not fixed: because the capture stops at the hyphen,
    ``parse_cfr_citations("41 CFR 101-1")`` yields part ``101`` and this
    function mints ``urn:rkaf:us:cfr:41:101`` — a first-class identifier for a
    part that does not exist, since none of title 41's 16 hyphen heads is a
    part in its own right. Minting the hyphen form here would replace that
    named, tested gap with a silent wrong answer, so the space carries the
    form and the minter does not. The fix belongs in ``_CFR_PART_CAPTURE``,
    inside receipt-pinned ``citation_grammar``; see REF-054 for the trigger
    that reopens it.

    Refuses part 0, and leading zeros are spelling: see
    :func:`_positive_integer`, whose join-key rule this reuses unchanged.
    """

    text = _stated(value).lower()
    match = re.fullmatch(r"([0-9]+)([a-z]?)", text)
    if match is None:
        return None
    number = _positive_integer(match[1])
    return None if number is None else f"{number}{match[2]}"


def _cfr_section(value: object) -> str | None:
    """A CFR section suffix, lowercased, with subsection detail dropped.

    A parenthetical is DROPPED rather than refused, so "60.18(a)" resolves to
    the section that contains it — the deliberate narrowing
    ``act_resolution.canonical_usc_iri`` makes and pins one column over. A
    section this cannot spell inside rulespec's production is refused, never
    truncated to the part.
    """

    text = re.sub(r"\([^)]*\)", "", _stated(value).lower())
    return text if re.fullmatch(r"[0-9]+[a-z]{0,3}(?:-[0-9a-z]+)*", text) else None


def _states_a_federal_register_document(text: str) -> bool:
    """Whether the shape layer reads the whole value as one FR document number.

    The prose reader's four recognised forms — modern, correction,
    republication and legacy — asked as one question, so this module admits
    exactly what :mod:`identifier_shapes` admits and never a form of its own.
    "Whole" matters: a value that merely CONTAINS a document number states a
    sentence, not an identifier, and 56,364 "Not Assigned" strings are what a
    containment test buys.
    """

    candidates = detect_identifier_shapes(text)
    return (
        len(candidates) == 1
        and candidates[0].kind is IdentifierKind.FEDERAL_REGISTER_DOCUMENT
        and candidates[0].span == (0, len(text))
    )


# --------------------------------------------------------------------------- #
# The seven minters.


def mint_cfr_iri(title: object, part: object, section: object = None) -> MintedIdentifier | None:
    """Mint ``urn:rkaf:us:cfr:{title}:{part}[.{section}]``.

    The title is fenced to the 50 that exist (:data:`CFR_TITLE_COUNT`),
    reserved title 35 included — it held the Panama Canal until 2000, so a
    1990s citation to it is real. This is the one place a minter is narrower
    than the grammar on purpose: ``parse_cfr_citations`` keeps an impossible
    title with a false ``title_is_possible`` verdict, because a data-quality
    consumer needs the row, while minting an identifier for a title that does
    not exist would publish the claim rather than the doubt.

    Mints a LETTERED part, folding its suffix to lowercase, and refuses a
    hyphen-number part — both decided in :func:`_cfr_part`, which carries the
    measurements and the reason the second is a deliberate narrowing against
    the space rather than an oversight. "7 CFR 15" and "7 CFR 15a" stay
    separate identifiers, as they are separate parts.

    Refuses part 0 as it refuses title 0, which rulespec's own title
    production already refuses — there is no part 0 to name.

    A section that STATES NOTHING is no section, not a bad one: a
    ``cfr_section`` column carrying "", "None" or "N/A"
    (``citation_grammar.states_nothing``, whose sentinel set the Agenda's own
    placeholders bought) mints the part, where refusing the whole citation
    would throw away the half the source did state.
    """

    title_text = _positive_integer(title)
    if title_text is None or not 1 <= int(title_text) <= CFR_TITLE_COUNT:
        return None
    part_text = _cfr_part(part)
    if part_text is None:
        return None
    body = f"{title_text}:{part_text}"
    if not states_nothing(section):
        section_text = _cfr_section(section)
        if section_text is None:
            return None
        body = f"{body}.{section_text}"
    return _mint("rkaf:us-cfr", f"urn:rkaf:us:cfr:{body}")


def mint_executive_order_iri(number: object) -> MintedIdentifier | None:
    """Mint ``urn:rkaf:us:eo:{number}``.

    Deliberately NOT fenced by ``citation_grammar.EO_HIGHEST_KNOWN``. That
    bound is a dated fact for builders judging pinned captures — the module
    that states it says so — and a minter that refused above it would refuse
    the next order the President signs. The series has one real floor, that it
    starts at 1, and rulespec's ``[1-9][0-9]*`` already states it.
    """

    text = _positive_integer(number)
    return None if text is None else _mint("rkaf:us-eo", f"urn:rkaf:us:eo:{text}")


def mint_rin_iri(value: object) -> MintedIdentifier | None:
    """Mint ``urn:rkaf:us:rin:{rin}`` for a Regulation Identifier Number.

    Wraps :func:`~identifier_shapes.normalize_rin`, which answers "is this
    string one" and never "does it contain one" — 56,364 of 64,537 catalog
    ``rin`` values are the literal string "Not Assigned", and a containment
    test made it the corpus's most common identifier by a factor of ten.

    ``rkaf:us-rin`` closes on ``[0-9]{2}`` where the shape allows
    ``[A-Za-z0-9]{2}``, so a RIN whose last two characters are letters
    normalizes and then refuses. Zero of the Unified Agenda's 46,547 RINs take
    that form (measured 2026-08-31), so the divergence costs nothing today;
    ``test_a_rin_the_shape_admits_and_rkaf_cannot_spell_is_refused`` is there
    so it stops costing nothing loudly.

    The narrow one here is the SHAPE's counterpart, not this space. rulespec
    was asked to widen the tail alongside frdoc and CFR in ``0.2.0rc16`` and
    was deliberately left alone: ``[A-Z]{2}[0-9]{2}`` is the only published
    format statement anyone has found, the five known out-of-space RINs
    (0648-XD990, 0648-XC705, 3090-00XX, 1115-09AE, 2070-78AB) are unreachable
    by widening the last two characters anyway — two need a five-character
    tail, three run digit-digit-letter-letter — and widening would have
    deleted the refusal test for a coverage gain of provably zero. See
    REF-054.
    """

    rin = normalize_rin(value)
    return None if rin is None else _mint("rkaf:us-rin", f"urn:rkaf:us:rin:{rin}")


def mint_regulations_gov_docket_iri(reference: object) -> MintedIdentifier | None:
    """Mint ``urn:rkaf:us:regsgov:{docket}`` for a Regulations.gov docket.

    Wraps :func:`~identifier_shapes.normalize_docket_reference` whole, which
    carries three rules this module must not restate: strip-then-validate in
    that order only (so Commerce's own ``DOC-2010-0001`` is not mutilated by
    the label grammar), a stripped remainder that must open on a letter (which
    refuses 5,214 of 5,506 mutilated references and costs no real docket), and
    the FERC exclusion (24,548 references of the "CP26-20-000" form fit the
    shape and belong to another registry).

    It is a COLUMN reader, and inherits that license exactly: the wrapped
    shape absorbs "EPA-HQ-OAR-2021-0317-0001" — a Regulations.gov *document*
    id — and mints it as a docket, because a value arriving from
    ``docket_ids_json`` is a docket by the field's own declaration. The prose
    reader arbitrates the identical characters the other way, and that
    arbitration is where the question belongs; a caller holding a document id
    must not hand it to a docket minter.
    ``test_the_docket_minter_inherits_the_column_readers_license`` pins both
    halves, because either one changing silently is how a document id becomes
    a docket downstream.
    """

    docket = normalize_docket_reference(reference)
    return None if docket is None else _mint("rkaf:us-regsgov", f"urn:rkaf:us:regsgov:{docket}")


def mint_public_law_iri(public_law: object) -> MintedIdentifier | None:
    """Mint ``urn:rkaf:us:pl:{congress}-{number}`` from "119-101".

    Takes the compound the grammar already produces —
    ``AuthorityCitation.public_law`` is written
    ``f"{int(congress)}-{int(number)}"`` — so the label spellings, the doubled
    dash and the dotted separator are read where they are read today and this
    layer never re-parses prose.

    Deliberately NOT fenced by ``PL_FIRST_NUMBERED_CONGRESS`` or
    ``CONGRESS_CURRENT``, for the reason those constants give themselves: they
    are dated series bounds for damage detection, and the next Congress
    outruns them. Minting for the 120th Congress must work the day it sits.
    """

    text = _stated(public_law).translate(_DASHES)
    match = re.fullmatch(r"([0-9]+)-([0-9]+)", text)
    if match is None:
        return None
    congress, number = _positive_integer(match[1]), _positive_integer(match[2])
    if congress is None or number is None:
        return None
    return _mint("rkaf:us-pl", f"urn:rkaf:us:pl:{congress}-{number}")


def mint_federal_register_document_iri(
    document_number: object, *, column_licensed: bool = False
) -> MintedIdentifier | None:
    """Mint an identifier for a Federal Register document number.

    Three outcomes, and which one a value gets is the news:

    - ``rkaf:us-frdoc`` when rulespec's space can spell it —
      ``[0-9]{4}-[0-9]{3,5}``, which is **480,566 of the 1,004,233** distinct
      values in the pinned column (47.9%);
    - ``rkaf:partner-defined`` when the shape layer recognises the value and
      rulespec cannot spell it. Two populations arrive here unconditionally,
      through the prose reader: the correction, republication and legacy
      forms, and — behind ``column_licensed`` — three more REF-052/REF-054
      admit: the **394,128** bare-legacy numbers and, as of this cycle, the
      four letter-opening families
      (:data:`~identifier_shapes._FR_COLUMN_LETTER_FORMS`) totalling **10,231**
      more. A sixth used to arrive here: the 28,862 modern-form numbers with a
      three- or four-digit tail (2010-5997, 2011-237, 2012-00019 among them)
      took the hatch until rulespec 0.2.0rc16 widened the space, and they are
      first-class now;
    - ``None`` otherwise, which is a refusal and never a repair.

    ``column_licensed`` is the whole of the two-readers doctrine in this
    module, delegated whole to
    :func:`~identifier_shapes.is_federal_register_document_number`'s own
    ``column_licensed`` flag — this function adds no second opinion about
    what the column licenses. Unlabeled in running text "94-12345" is
    indistinguishable from a docket or a release number and stays unread;
    arriving from a ``document_number`` field it needs no inference, because
    the field is the license. Nothing about prose detection changes either
    way — the flag admits shapes and admits them nowhere else. See
    :data:`~identifier_shapes.BARE_LEGACY_FEDERAL_REGISTER_DOCUMENT_NUMBER`
    and :data:`~identifier_shapes._FR_COLUMN_LETTER_FORMS`.

    The padding is never normalized, and after the widening that rule is the
    only thing standing between a document and a second identifier. The Office
    of the Federal Register pads some years and not others; across all 480,566
    modern-form values now inside the space, not one padded number has an
    unpadded twin — measured, and the load-bearing safety proof for widening
    the space at all. So 2012-00019 is the identifier and "2012-19" would be a
    spelling no publisher issued.
    """

    text = _stated(document_number).translate(_DASHES)
    if is_federal_register_document_number(
        text, column_licensed=column_licensed
    ) or _states_a_federal_register_document(text):
        minted = _mint("rkaf:us-frdoc", f"urn:rkaf:us:frdoc:{text}")
        return minted if minted is not None else mint_partner_iri("frdoc", text)
    return None


def mint_partner_iri(kind: str, value: object) -> MintedIdentifier | None:
    """Mint ``urn:rkaf:partner:refspec:{kind}:{value}`` under the escape hatch.

    rulespec's ``rkaf:partner-defined`` is how a real thing its own spaces
    cannot spell stays losslessly identifiable, and this is the only minter
    here that adds identity rather than restating rulespec's. So it folds
    nothing: no dash collapse, no case fold. Whatever a caller hands it comes
    back recoverable, because a value that reached this function did so
    precisely because no space would normalize it.

    The value is percent-encoded (RFC 3986 unreserved set kept), which is what
    makes the result satisfy rkaf's ``[^\\s]+`` identifier floor without
    dropping a character. Encode ONCE: handing this function an
    already-encoded value produces a different, wrong identifier, since "%"
    itself encodes.

    Refuses a control character, which is damage rather than identity and
    percent-encoding would otherwise hide as "%0A"; refuses an empty value;
    and refuses a ``kind`` outside ``[a-z][a-z0-9-]*`` so the five-segment
    layout always parses back unambiguously. Reusing a real family's word as
    the kind is deliberate, not a shadow: the FR minter itself hands the
    394,128 bare-legacy and 117,292 letter-opening documents here as kind
    ``frdoc``, and the ``urn:rkaf:partner:refspec:`` prefix is what keeps
    them lexically apart from every ``urn:rkaf:us:...`` identifier.

    The hatch is a WAITING ROOM, not a parallel vocabulary. When rulespec
    widens a space, whatever it now admits leaves through the same door it
    came in: ``urn:rkaf:partner:refspec:frdoc:2011-237`` became
    ``urn:rkaf:us:frdoc:2011-237`` in 0.2.0rc16 with no lookup, because the
    value is percent-encoded here losslessly and is recoverable from the
    partner IRI itself. See REF-054 for what that obliges a future widening
    to check.
    """

    text = _stated(value)
    if not text or _PARTNER_KIND.fullmatch(kind) is None or any(ord(character) < 32 for character in text):
        return None
    return _mint("rkaf:partner-defined", f"urn:rkaf:partner:{PARTNER_NAMESPACE}:{kind}:{quote(text, safe='')}")
