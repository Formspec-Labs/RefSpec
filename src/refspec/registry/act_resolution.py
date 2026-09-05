"""Resolve an act-relative citation through the two pinned OLRC sources.

"Clean Air Act section 111" names no code, title or section number. Resolving
it is two joins over a sealed ``usc-act-index-artifact-v1``:

1. **popular name → act.** The Popular Name Tool's names, aliases, and each
   act's Table III key.
2. **act section → U.S.C. section.** Table III's classification of every
   section of that act.

**And a second, independent source with its own coverage.** The U.S. Code's
own source credits state, per section, the act section that added it *and the
division of the enacting public law* — the discriminator Table III lacks,
since Table III is keyed by the public law alone.

The two are **complementary, not a tiebreaker over one another**, and they are
not symmetric. Table III is keyed by ``(law, act section)`` and answers with
*every* row, so its ambiguity must be attacked after the lookup, by a page
range that is sound in one direction only. The credits are keyed by
``(law, division, act section)`` — the discriminator is *in* the key — so
their ambiguity is decided at lookup time and refuses as ``multi_target``.
Their coverage differs by two orders of magnitude: 8,391 Table III keys
against 109 laws in the credits, which is why the credits read as a spot check
rather than a peer. Measured on release point 119-102: of the 222 unambiguous
credit triples whose public law Table III was also fetched for, **176 have no
in-division Table III row at all** — ``26 U.S.C. 6038E`` among them. So
:func:`resolve_act_relative_citation` consults both, records which one
answered, and **refuses when they answer differently**
(:data:`SOURCE_COMPOSITION_RULE`).

Every answer is *derived* from the tables at call time; there is no checked-in
lookup of answers. A refusal is a first-class result: :class:`ActResolution`
always carries either an identifier or an :data:`UNRESOLVED_REASONS` code —
never neither, and never a guess in place of one.

**Read the refusals with the build in mind.** Which build is now a choice.
:data:`USC_ACT_INDEX_PER_PAGE_ARTIFACT` was fetched one HTTP request per act
and holds Table III's classifications for **24** laws against the 8,391 the
popular-name index names, so ``act_section_not_classified`` — much the
commonest code this module publishes — was for 12,695 of its 12,963 cited acts
a statement about a build that requested 27 pages and reached 24, not a
statement OLRC ever made. :data:`USC_ACT_INDEX_BULK_ARTIFACT` — the default,
:data:`USC_ACT_INDEX_ARTIFACT`, since 2026-08-23 — is the same artifact rebuilt from OLRC's
whole-of-Table-III release by :mod:`refspec.registry.usc_act_index`: **15,189**
laws, 302,156 rows, no ``source_incomplete`` at all. Measured over the Unified
Agenda corpus it moves act-relative resolution from 205 (act, section) pairs /
3,621 rows to 354 / 5,590, losing nothing and changing no answer, and turns a
large part of the remaining refusals into codes that are about the source
rather than about coverage — see
``research/evidence/act-index-bulk-table3-2026-08-22.md``. It is one release
point behind (119-73 against 119-102) for the 24 laws both cover, in 29
enumerated rows, which is why switching was taken as a decision rather than
allowed as a consequence -- taken on 2026-08-23, once those 29 rows were
enumerated and none was a resolution this corpus asks for.
``test_act_section_not_classified_is_mostly_never_fetched`` keeps the per-page
number on the record.

Provenance: ported from ``spicy_regs/ontology/act_index.py`` — itself the
evolved successor of the DocSpec-archive original — at its newest state
(division-range discrimination, the two-source composition, and the
sound-half-only range rule all included). The sealed artifacts it reads moved
to this repository's canonical output tree on 2026-08-21 and are digest-pinned
below; the loaders here verify those pins, which the ancestor did not.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import NamedTuple

from refspec.registry.citation_grammar import ActRelativeCitation, normalize_popular_name

__all__ = [
    "ALIAS_PRECEDENCE_RULE",
    "ALIAS_YEAR_RULE",
    "ANSWERING_SOURCES",
    "DIVISION_RULE",
    "SOURCE_COMPOSITION_RULE",
    "SOURCE_CREDIT_STATUSES",
    "UNRESOLVED_REASONS",
    "USC_ACT_INDEX_ARTIFACT",
    "USC_SOURCE_CREDIT_ARTIFACT",
    "ActIndex",
    "ActResolution",
    "Classification",
    "SourceCreditAnswer",
    "SourceCreditIndex",
    "SourceCreditTarget",
    "act_name_absence_reason",
    "canonical_usc_iri",
    "resolve_act_name",
    "resolve_act_relative_citation",
    "stated_name_chain",
]

#: The sealed artifacts, relative to the repository's output tree, with the
#: digest of every table a loader reads. The receipts inside each directory
#: carry the acquisition provenance (popularnames.htm digest, coverage
#: counts); these pins are what make a wrong directory fail loudly instead of
#: loading as a source with no coverage. They deliberately restate a number
#: the receipts also carry: reading the pin *from* the receipt beside the
#: tables would authenticate a swapped directory against its own paperwork.
#: ``test_the_pins_restate_the_receipts`` holds the two copies together.
#:
#: Keyed by ARTIFACT, not by table, since 2026-08-22: two act-index artifacts
#: now state the same table names, and a flat table -> digest map cannot hold
#: two digests for one name. It is deliberately not keyed by DIRECTORY PATH —
#: a sealed directory may be copied anywhere and stay itself — so the digest
#: remains the whole authentication. What that costs is stated rather than
#: papered over: because the two act-index artifacts share one popular-name
#: table byte for byte, no check here can tell a directory holding 08-02's
#: classifications from one holding 08-22's *by that table*, and the
#: classifications table is what distinguishes them
#: (``test_the_two_act_indexes_differ_only_in_their_classifications``).
#: The per-page build: one HTTP request per act, 27 requested, 24 reached.
#: Still pinned and readable; no longer the default.
USC_ACT_INDEX_PER_PAGE_ARTIFACT = "output/usc-act-index-2026-08-02"
#: The same artifact rebuilt from OLRC's whole-of-Table-III bulk release by
#: :mod:`refspec.registry.usc_act_index`: 302,156 classification rows over
#: 15,189 Table III keys against the per-page build's 10,976 over 24. Its
#: popular-name table is the 08-02 one, carried over byte-identically, which is
#: why one digest appears under both artifacts.
USC_ACT_INDEX_BULK_ARTIFACT = "output/usc-act-index-2026-08-22"
#: The default since 2026-08-23. Switching changed no byte of the Unified
#: Agenda artifact (its builder reads only the popular-name table, which the
#: two share) and raised live act-relative resolution from 3,621 to 5,590
#: rows, losing nothing and changing no answer; the one cost is that the 24
#: laws both builds hold sit one release point back (119-73 against 119-102),
#: 29 enumerated rows, none a resolution this corpus asks for
#: (``research/evidence/act-index-bulk-table3-2026-08-22.md``).
USC_ACT_INDEX_ARTIFACT = USC_ACT_INDEX_BULK_ARTIFACT
USC_SOURCE_CREDIT_ARTIFACT = "output/usc-source-credit-index-2026-08-02"
_ARTIFACT_PINS: Mapping[str, Mapping[str, str]] = {
    "usc-act-index-2026-08-02": {
        "usc-popular-names.parquet": "sha256:603d5b072133d8fe6802736aeaa70b9fb9832e4fb996158a083fae3ce1026a9a",
        "usc-act-sections.parquet": "sha256:93c4981ec437f08ce4b1826e8dfdd0519ded05e8143541a21b901488f8baf1f8",
    },
    "usc-act-index-2026-08-22": {
        "usc-popular-names.parquet": "sha256:603d5b072133d8fe6802736aeaa70b9fb9832e4fb996158a083fae3ce1026a9a",
        "usc-act-sections.parquet": "sha256:9040d4460e90704aef911b4d4f704e9f432cebd7b58717f31f090a3008ca6159",
    },
    "usc-source-credit-index-2026-08-02": {
        "usc-source-credits.parquet": "sha256:d377545fe60d592a120bda30dffba665380cf82f826ae06cb327a581f0af9d8a",
    },
}

#: An alias may point at a name the Popular Name Tool does not itself list:
#: "ERISA" points at "Employee Retirement Income Security Act" and the only
#: entry by that name is "… Act of 1974". The year is how the tool
#: distinguishes acts, so it can only be *supplied*, and only when exactly one
#: act supplies it — "Clean Air Act Amendments" would be 1966, 1970 and 1977,
#: and choosing among them would invent a citation the source never made.
ALIAS_YEAR_RULE = "supply-trailing-year-when-exactly-one-act-supplies-it"

#: **What the tool states outranks what this module derives.** Supplying a
#: year is an inference; a cross-reference is the source speaking, so the whole
#: chain of stated ones is read before any year is supplied. The receipt's own
#: derivation of :data:`ALIAS_YEAR_RULE` scopes it that way — "an ALIAS TARGET
#: missing one may have it supplied" — but the code applied it to the query
#: first, and so contradicted the Popular Name Tool twice in the pinned index:
#:
#: * "Clean Water Act" — the tool says *see Federal Water Pollution Control
#:   Act*; the module answered the *Clean Water Act of 1977*, which is the
#:   amending act, not the act. 943 Unified Agenda authority rows cite it.
#: * "Anti-Kickback Act" — the tool says *see Copeland Anti-Kickback Act*; the
#:   module answered the *Anti-Kickback Act of 1986*.
#:
#: Reading the chain first also stops answering the right act for the wrong
#: reason: "Internal Revenue Code" resolved to the 1939 code only because its
#: year was ambiguous enough to fall through to the tool's stated rename.
#: Where the stated chain leads nowhere the year is still supplied, so the
#: Insurrection Act — whose cross-reference is "Title 10, chapter 13 (Sec. 251
#: et seq.)", a place and not an act name — still answers 1807. Measured over
#: all 13,648 names: those two are the only answers this precedence changes.
ALIAS_PRECEDENCE_RULE = "stated-cross-reference-before-derived-year-v1"

#: How many names one walk may visit before it is abandoned. Termination does
#: not rest on this: the walk stops at the first name it has already visited,
#: and the alias map is finite. It is a declared bound with measured headroom
#: — the longest chain in the pinned index is two hops
#: (``test_the_longest_stated_chain_in_the_pinned_index_is_two_hops``), and the
#: artifact's own receipt records the bound as a rule of the build.
ALIAS_MAX_DEPTH = 8

#: How an act is told apart from the others its public law enacted: both
#: halves stated by OLRC, neither inferred. A Table III row belongs to the act
#: whose division's Statutes at Large range contains its page; only the
#: division *end* is derived, from the next division's start, and divisions
#: partition the volume.
DIVISION_RULE = "act-division-statutes-at-large-range-v1"

#: Both sources are consulted, always. Either may answer alone; the same
#: identifier from both says ``both``; different identifiers REFUSE. The
#: measured cause of disagreement is an act section that classified to more
#: than one place, where each source retains a different one — (114-94,
#: div. C, §32101): Table III says 22 U.S.C. 2714a, the credits say
#: 26 U.S.C. 7345, and both are true. Naming one would be arbitrary.
SOURCE_COMPOSITION_RULE = "table3-and-source-credits-consulted-disagreement-refuses-v1"

#: What the source-credit index had to say, whether or not it decided
#: anything. A consumer must be able to tell "no key to look under" from
#: "looked and found nothing" from "found several".
SOURCE_CREDIT_STATUSES = ("not_consulted", "no_key", "absent", "multi_target", "resolved")

#: Which source produced a published identifier.
ANSWERING_SOURCES = ("table3", "source_credits", "both")

_YEAR_SUFFIX = re.compile(r"\s+of\s+(?:1[789]|20)\d{2}$")

#: A leading article the Popular Name Tool wrote into its own cross-reference
#: text — "see The Vocational Rehabilitation Act" — where its entry for the act
#: carries no article. It is spelling, not identity, and the same expression
#: already exists in ``unified_agenda_parquet._act_prose_recoveries``, applied
#: there to corpus text and never to the tool's own names. Stripping it is
#: tried only after every stated name has been checked verbatim, so the tool's
#: own spelling still wins (:data:`ALIAS_PRECEDENCE_RULE`), and still before a
#: year is supplied, because dropping a word the act's own entry does not use
#: is reading the source and supplying a year is inferring past it. Measured
#: over every name the tool writes: it rescues exactly four —
#: "the vocational rehabilitation act" and "the 911 modernization act", and the
#: two names whose stated chains dead-end at them, "fess-kenyon act" and
#: "improving emergency communications act of 2007".
_LEADING_ARTICLE = re.compile(r"^the\s+")

#: A Table III key that is also a public law number, which is what the source
#: credits are keyed by. ``1955:360`` is a session-law chapter and is not one;
#: 1,921 of the index's 8,391 keys have that shape, and for those the credits
#: have nothing to be looked up under.
_PUBLIC_LAW_KEY = re.compile(r"^[1-9]\d{0,2}-[1-9]\d*$")

#: The ``rkaf:us-usc`` lexical space, restated **verbatim** from the contract
#: this repository pins. ``rulespec-conformance==0.2.0rc9`` states it
#: identically in all four compiled forms — JSON Schema, SHACL, Rego and
#: TypeScript — as::
#:
#:     ^urn:rkaf:us:usc:[1-9][0-9]*:[1-9][0-9]*[a-z]*(-[0-9a-z]+)*$
#:
#: This module neither widens nor narrows the space on its own: it mints a
#: candidate and checks it, and a target the space cannot spell refuses as
#: ``usc_section_not_expressible``. Restating rather than importing keeps the
#: check readable at the point of use;
#: ``test_the_minted_space_is_the_contract_verbatim`` holds the copy true
#: against the vendored package, the way :data:`_ARTIFACT_PINS` is held true
#: against its receipts. Agreeing with the contract is this module's job;
#: **the contract itself is fallible and ours to fix**, so where it cannot
#: spell something the U.S. Code really has, that is recorded as a gap in rkaf
#: rather than treated as a fact about the section — see
#: ``test_what_the_space_still_cannot_express_is_a_gap_in_rkaf``.
#:
#: Until 2026-08-22 this was a hand-written ``\d+[a-z]?(?:-\d+[a-z]?)?``, which
#: diverged from the contract in BOTH directions. It refused 616 real sections
#: the space permits — 12 U.S.C. 1831aa, 12 U.S.C. 2279aa-11, 42 U.S.C.
#: 2000bb, 42 U.S.C. 300aa-11 — because it allowed one trailing letter and one
#: hyphen group where the contract allows any number of both. And it minted
#: ``urn:rkaf:us:usc:42:0123`` and ``urn:rkaf:us:usc:0:1``, which the contract
#: forbids, because it allowed a leading zero where the contract requires
#: ``[1-9]``. Both are gone.
#:
#: What still refuses on the pinned tables is 1,286 targets that are not a
#: single section: 1,118 statutory NOTES ("42 U.S.C. 1 nt"), 127 POSITIONS
#: ("prec. 2161", a chapter heading's location), 14 RANGES ("79 to 79z-6"),
#: and 27 comma-separated LISTS ("2151w, 2221, 2222, …") that the artifact
#: builder stored in a scalar column. A note and a range are real, citable
#: things rkaf has no production for; the list is a builder defect, not a
#: space defect. None of the four is a section, so refusing each is right —
#: what is wrong is calling all four "not expressible" without saying which.
_RKAF_USC_IRI = re.compile(r"^urn:rkaf:us:usc:[1-9][0-9]*:[1-9][0-9]*[a-z]*(?:-[0-9a-z]+)*$")

#: Stands in for "this division runs to the end of the volume". Larger than
#: any page that can occur: the highest Statutes at Large page across the
#: 8,451 paged rows of the pinned act-sections table is 6,106.
_PAGE_RANGE_OPEN_END = 1 << 30

#: Every way this module declines to publish an identifier. Codes are data: a
#: consumer counts them, and an artifact records them per citation.
UNRESOLVED_REASONS = (
    #: The source does not LIST this name at all. On the pinned index this is
    #: true of 19 of the 107 unanswerable names -- each reachable only as some
    #: other entry's ``see also`` target, never as an entry of its own.
    "act_not_in_index",
    #: The source lists the name and publishes no Table III key under it: 63 of
    #: the 107, the Congressional Review Act, the Anti-Deficiency Act and the
    #: Paperwork Reduction Act among them. Reporting these as
    #: ``act_not_in_index`` told a reader the act was absent from a source that
    #: names it, which is a different and wronger statement than "nothing is
    #: classified here".
    "act_listed_without_classification",
    #: The source lists the name only as a cross-reference and the reference
    #: dead-ends: 25 of the 107. The name is present, the trail is not.
    "act_alias_target_not_listed",
    "source_incomplete",
    "act_section_not_classified",
    "classification_not_current",
    "usc_section_not_expressible",
    #: Table III is keyed by the enacting Public Law, and one law may carry
    #: many acts (116-260 carries 94 popular names). 471 of the artifact's
    #: 9,916 (key, section) pairs name several classifications; choosing among
    #: them is how "sec. 107 of the Taxpayer Certainty and Disaster Tax Relief
    #: Act of 2020" once became pipeline-safety civil penalties.
    "act_section_ambiguous",
    #: Every classification of the act section sits outside the citing act's
    #: own division — the section belongs to a sibling act.
    "act_section_outside_act",
    #: The citation names a division and the act it names sits in a different
    #: one: the source disagrees with itself about which act is meant.
    "act_division_conflict",
    #: Both sources answered, and they named different U.S. Code sections.
    "sources_disagree",
)


def canonical_usc_iri(title: object, section: object) -> str:
    """Mint ``urn:rkaf:us:usc:{title}:{section}`` inside the lexical space.

    The candidate is minted and then checked against :data:`_RKAF_USC_IRI`,
    so what this function will emit is exactly what Rulespec's own validators
    accept — there is no second, paraphrased opinion about the space to drift
    from it.

    Spelling is normalized — a leading zero on the title, surrounding space,
    upper case — because those are spelling, not identity. A leading zero on
    the SECTION is not normalized away: the U.S. Code writes no such section,
    so "0123" is refused rather than quietly read as 123. A parenthetical is
    *dropped*, so a subsection resolves to its section; no row of either
    pinned table carries one, and
    ``test_a_parenthetical_is_dropped_not_refused`` pins that behaviour so it
    stays a deliberate narrowing rather than a surprise.
    """

    title_text = str(title or "").strip().lstrip("0")
    section_text = re.sub(r"\([^)]*\)", "", str(section or "").strip().lower())
    iri = f"urn:rkaf:us:usc:{title_text}:{section_text}"
    if not _RKAF_USC_IRI.fullmatch(iri):
        raise ValueError(f"invalid U.S.C. identifier components: title={title!r}, section={section!r}")
    return iri


def _pinned_digests(name: str) -> Mapping[str, str]:
    """Artifact -> the digest it pins for this table. ``KeyError`` if none does."""

    stated = {artifact: tables[name] for artifact, tables in _ARTIFACT_PINS.items() if name in tables}
    if not stated:
        raise KeyError(name)
    return stated


def _artifacts_stating(path: Path) -> frozenset[str]:
    """Which sealed artifacts state this file, by digest. Empty means drifted."""

    digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    return frozenset(a for a, pin in _pinned_digests(path.name).items() if pin == digest)


def _read_pinned_parquet(directory: Path, name: str):
    import pyarrow.parquet as pq

    path = directory / name
    if not _artifacts_stating(path):
        expected = sorted(set(_pinned_digests(name).values()))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        raise ValueError(f"pinned act artifact drifted: {name}; expected={expected}, observed=sha256:{digest}")
    return pq.read_table(path).to_pylist()


class Classification(NamedTuple):
    """One Table III row: where an act section landed in the U.S. Code.

    Named because the page used to be read as ``row[3]`` in the one expression
    that decides whether a classification belongs to the citing act.
    """

    usc_title: str | None
    usc_section: str | None
    #: Empty for a live classification; "Rep.", "Elim." or "Rev. T." for one
    #: the Code has since moved or removed. Any value at all refuses.
    status: str | None
    statutes_at_large_page: int | None


@dataclass(frozen=True)
class ActResolution:
    """What an act-relative citation resolved to, or why it did not."""

    citation: ActRelativeCitation
    act_key: str | None = None
    table3_key: str | None = None
    usc_title: str | None = None
    usc_section: str | None = None
    iri: str | None = None
    unresolved_reason: str | None = None
    #: Which source produced the identifier; ``None`` whenever there is none.
    answered_by: str | None = None
    #: What Table III said, resolved or not — kept even when the other source
    #: answered, because "Table III lacks this classification" is the coverage
    #: fact the complementarity claim rests on.
    table3_reason: str | None = None
    source_credit_status: str = "not_consulted"
    #: Stated only by the source credits. Table III states a volume for all
    #: 10,976 of its rows and the loader does not carry it, so a ``table3``
    #: answer publishes a page with no volume; see the module's review notes.
    statutes_at_large_volume: str | None = None
    statutes_at_large_page: str | None = None

    def __post_init__(self) -> None:
        if (self.iri is None) == (self.unresolved_reason is None):
            raise ValueError("a resolution states an identifier or a reason, never both or neither")
        if self.unresolved_reason is not None and self.unresolved_reason not in UNRESOLVED_REASONS:
            raise ValueError(f"undeclared unresolved reason: {self.unresolved_reason!r}")
        if (self.answered_by is None) != (self.iri is None):
            raise ValueError("an identifier names the source that produced it, and a refusal names none")
        if self.answered_by is not None and self.answered_by not in ANSWERING_SOURCES:
            raise ValueError(f"undeclared answering source: {self.answered_by!r}")
        if self.source_credit_status not in SOURCE_CREDIT_STATUSES:
            raise ValueError(f"undeclared source-credit status: {self.source_credit_status!r}")
        if self.table3_reason is not None and self.table3_reason not in UNRESOLVED_REASONS:
            raise ValueError(f"undeclared Table III reason: {self.table3_reason!r}")


@dataclass(frozen=True)
class ActIndex:
    """The two joins, loaded from the pinned artifact or built for a test."""

    table3_key_by_name: Mapping[str, str] = field(default_factory=dict)
    alias_by_name: Mapping[str, str] = field(default_factory=dict)
    #: Table III key -> act section -> **every** classification row. A tuple,
    #: not a single row: a single-valued mapping silently discarded 1,060 of
    #: the artifact's 10,976 rows and let the survivor be chosen by row sort —
    #: which is not a citation rule.
    classifications: Mapping[str, Mapping[str, tuple[Classification, ...]]] = field(default_factory=dict)
    incomplete_sources: frozenset[str] = frozenset()
    #: Every name the Popular Name Tool LISTS -- its ``cite`` rows -- whether
    #: or not it publishes a Table III key for one. Without it the three ways
    #: a name can fail are indistinguishable at resolution time, and all three
    #: were reported as ``act_not_in_index``: see
    #: :func:`act_name_absence_reason`. Empty on a hand-built index, which
    #: makes that index's refusals fall back to ``act_not_in_index`` exactly as
    #: before.
    cited_names: frozenset[str] = frozenset()
    #: Absent for an act that states no division, which is how "spans the
    #: whole public law" is represented rather than asserted. The page beside
    #: the division is the act's own start; the range arithmetic never reads
    #: it, because a division's start is the *earliest* of its acts' and lives
    #: in :attr:`division_starts`.
    division_by_name: Mapping[str, tuple[str, int]] = field(default_factory=dict)
    #: Table III key -> every division of that law and where it begins, page
    #: ascending. Populated from EVERY qualifying row, where
    #: :attr:`division_by_name` keeps only a name's first, so the two can in
    #: principle diverge — one name ("Detainee Treatment Act of 2005") is
    #: already cited under two laws. On the pinned index they do not: deriving
    #: these starts from ``division_by_name`` instead reproduces all 660 of
    #: them exactly. Kept separate anyway, because "they agree today" is a
    #: measurement of one artifact, not a property of the source.
    division_starts: Mapping[str, tuple[tuple[str, int], ...]] = field(default_factory=dict)

    @cached_property
    def acts_supplying_year(self) -> Mapping[str, tuple[str, ...]]:
        """Stem -> the listed acts that complete it with a trailing year.

        :data:`ALIAS_YEAR_RULE` reads this. It is a property of the index, not
        of a query, so it is derived once: rebuilding it per call cost 7.1 ms
        against 4 µs for a name the index lists directly.
        """

        by_stem: dict[str, list[str]] = {}
        for known in self.table3_key_by_name:
            stem = _YEAR_SUFFIX.sub("", known)
            if stem != known:
                by_stem.setdefault(stem, []).append(known)
        return {stem: tuple(acts) for stem, acts in by_stem.items()}

    def act_page_range(self, act_key: str) -> tuple[int, int] | None:
        """The Statutes at Large pages an act occupies, or ``None`` if unbounded.

        The range is the DIVISION's, not the act's: many popular names are a
        title inside a division, and ending the range at the next *act*
        truncates the division. Validated against the Code's own source
        credits: 936 of 1,350 testable acts had USLM pages outside the
        act-derived range, and none outside the division-derived one.

        The end is the next division's start, *strictly* later, so two
        divisions that begin on one page (5 laws in the pinned index) do not
        truncate each other — the wider range is the sound one.
        """

        stated = self.division_by_name.get(act_key)
        if stated is None:
            return None
        division = stated[0]
        starts = self.division_starts.get(self.table3_key_by_name.get(act_key), ())
        # One entry per division when loaded from the artifact; the min is
        # what a hand-built index with repeats would mean.
        start = min((page for name, page in starts if name == division), default=None)
        if start is None:
            return None
        return (start, min((page for _, page in starts if page > start), default=_PAGE_RANGE_OPEN_END))

    @classmethod
    def from_artifact(cls, artifact_dir: Path) -> ActIndex:
        """Load from a sealed ``usc-act-index-artifact-v1`` directory, verifying pins."""

        directory = Path(artifact_dir)
        receipt = json.loads((directory / "receipt.json").read_text(encoding="utf-8"))
        table3_key_by_name: dict[str, str] = {}
        alias_by_name: dict[str, str] = {}
        cited_names: set[str] = set()
        division_by_name: dict[str, tuple[str, int]] = {}
        starts: dict[str, dict[str, int]] = {}
        for row in _read_pinned_parquet(directory, "usc-popular-names.parquet"):
            # Normalized on the way in, not trusted as stored. The builder ran
            # its own copy of this normalizer, and where the two disagree the
            # stored key is one no query can spell: OLRC's four TeX-quoted
            # names ("``SPARS'' Act") were sealed as ``''spars'' act``, which
            # is not a fixed point of `normalize_popular_name`, so the index
            # could classify three acts that no caller could ask for. This
            # makes every key a fixed point by construction — a no-op for
            # 20,861 of the pinned table's 20,865 rows.
            name = normalize_popular_name(row["name_key"])
            if row["see_also_key"]:
                alias_by_name.setdefault(name, normalize_popular_name(row["see_also_key"]))
            if row["content_type"] != "cite":
                continue
            cited_names.add(name)
            if row["table3_key"]:
                table3_key_by_name.setdefault(name, row["table3_key"])
            if not (row["division"] and row["statutes_at_large_page"]):
                continue
            page = int(row["statutes_at_large_page"])
            division_by_name.setdefault(name, (row["division"], page))
            if row["table3_key"]:
                # Every qualifying row, not just a name's first: a division
                # begins where its EARLIEST act does, and the acts that state
                # it are spread across the table.
                by_division = starts.setdefault(row["table3_key"], {})
                by_division[row["division"]] = min(by_division.get(row["division"], page), page)
        classifications: dict[str, dict[str, tuple[Classification, ...]]] = {}
        for row in _read_pinned_parquet(directory, "usc-act-sections.parquet"):
            by_section = classifications.setdefault(row["table3_key"], {})
            page = row["statutes_at_large_page"]
            by_section[row["act_section"]] = (
                *by_section.get(row["act_section"], ()),
                Classification(row["usc_title"], row["usc_section"], row["status"], int(page) if page else None),
            )
        return cls(
            table3_key_by_name=table3_key_by_name,
            alias_by_name=alias_by_name,
            classifications=classifications,
            incomplete_sources=frozenset(hole["table3_key"] for hole in receipt.get("source_incomplete", ())),
            cited_names=frozenset(cited_names),
            division_by_name=division_by_name,
            division_starts={
                key: tuple(sorted(by_division.items(), key=lambda item: item[1]))
                for key, by_division in starts.items()
            },
        )


@dataclass(frozen=True)
class SourceCreditTarget:
    """One U.S. Code section a source credit says an act section added."""

    usc_title: str
    usc_section: str
    statutes_at_large_volume: str | None = None
    statutes_at_large_page: str | None = None


@dataclass(frozen=True)
class SourceCreditAnswer:
    """What the second source had to say about one (law, division, section)."""

    status: str
    usc_title: str | None = None
    usc_section: str | None = None
    statutes_at_large_volume: str | None = None
    statutes_at_large_page: str | None = None

    def __post_init__(self) -> None:
        if self.status not in SOURCE_CREDIT_STATUSES:
            raise ValueError(f"undeclared source-credit status: {self.status!r}")


@dataclass(frozen=True)
class SourceCreditIndex:
    """The U.S. Code's own source credits, keyed the way a citation asks.

    A key naming several sections answers ``multi_target`` and never picks
    one — "the source said two things" stays distinguishable from "the source
    said nothing".
    """

    targets: Mapping[tuple[str, str, str], tuple[SourceCreditTarget, ...]] = field(default_factory=dict)

    @classmethod
    def from_rows(cls, rows) -> SourceCreditIndex:
        collected: dict[tuple[str, str, str], list[SourceCreditTarget]] = {}
        for law, division, act_section, usc_title, usc_section, volume, page in rows:
            target = SourceCreditTarget(usc_title, usc_section, volume, page)
            bucket = collected.setdefault((law, division, act_section), [])
            if target not in bucket:
                bucket.append(target)
        return cls(targets={k: tuple(v) for k, v in collected.items()})

    @classmethod
    def from_artifact(cls, artifact_dir: Path) -> SourceCreditIndex:
        directory = Path(artifact_dir)
        # Reading the receipt is not decoration: it fails loudly when the
        # directory is not this artifact, rather than yielding an empty index
        # that would look like a source with no coverage.
        json.loads((directory / "receipt.json").read_text(encoding="utf-8"))
        return cls.from_rows(
            (
                row["public_law"],
                row["division"],
                row["act_section"],
                row["usc_title"],
                row["usc_section"],
                row["statutes_at_large_volume"],
                row["statutes_at_large_page"],
            )
            for row in _read_pinned_parquet(directory, "usc-source-credits.parquet")
        )

    def targets_for(self, public_law: str, division: str, act_section: str) -> tuple[SourceCreditTarget, ...]:
        return self.targets.get((public_law, division, act_section), ())

    def lookup(self, public_law: str | None, division: str | None, act_section: str) -> SourceCreditAnswer:
        """This source's answer, with "nothing to look under" kept distinct.

        The division is part of the key, not a filter applied afterwards, so a
        citation with no division has no key here at all. That costs nothing:
        every one of the 3,721 credit rows names a division, and every one of
        the 109 laws they cover is also a Table III key.
        """

        if not public_law or not division:
            return SourceCreditAnswer(status="no_key")
        found = self.targets_for(public_law, division, act_section)
        if not found:
            return SourceCreditAnswer(status="absent")
        if len({(t.usc_title, t.usc_section) for t in found}) > 1:
            return SourceCreditAnswer(status="multi_target")
        # Every surviving target names one section; no triple in the pinned
        # index states it at two different pages, so this reads a fact rather
        # than picking one (``test_one_target_never_hides_two_pages``).
        target = found[0]
        return SourceCreditAnswer(
            status="resolved",
            usc_title=target.usc_title,
            usc_section=target.usc_section,
            statutes_at_large_volume=target.statutes_at_large_volume,
            statutes_at_large_page=target.statutes_at_large_page,
        )


def stated_name_chain(name: str, index: ActIndex) -> tuple[str, ...]:
    """The names the tool's own cross-references reach, the query first.

    Terminates on its own: it stops at the first name it has already visited,
    and the alias map is finite. :data:`ALIAS_MAX_DEPTH` is a second, declared
    bound that the pinned index never reaches.
    """

    chain: list[str] = []
    seen: set[str] = set()
    current = normalize_popular_name(name)
    while current not in seen and len(chain) < ALIAS_MAX_DEPTH:
        chain.append(current)
        seen.add(current)
        stated = index.alias_by_name.get(current)
        if stated is None:
            break
        current = stated
    return tuple(chain)


def resolve_act_name(name: str, index: ActIndex) -> str | None:
    """The act a popular name refers to, following aliases. ``None`` when none.

    Three passes over the chain, in the order :data:`ALIAS_PRECEDENCE_RULE`
    fixes: every name the tool's own cross-references reach is checked against
    the tool's listing first; then each is retried with a leading article
    stripped (:data:`_LEADING_ARTICLE`), because an article the tool wrote into
    its own cross-reference is spelling; and only when none of that is listed
    does :data:`ALIAS_YEAR_RULE` supply a trailing year — for the earliest name
    in the chain that exactly one act completes.

    ``None`` covers three situations the caller reports alike as
    ``act_not_in_index``, which is true of only one of them. Of the pinned
    index's 107 unanswerable names: **63 the tool cites but gives no Table III
    key** (the Congressional Review Act, the Anti-Deficiency Act, the
    Paperwork Reduction Act), 25 state a ``see also`` that dead-ends, and 19
    are named only as somebody's ``see also`` target. See the review notes on
    the mislabel. Was 115 until 2026-08-22: four more were reachable through a
    stripped article, and four the tool stores behind a TeX quote pair that
    ``normalize_popular_name`` could not spell until it began straightening
    before it strips.
    """

    chain = stated_name_chain(name, index)
    for step in chain:
        if step in index.table3_key_by_name:
            return step
    for step in chain:
        stripped = _LEADING_ARTICLE.sub("", step)
        if stripped != step and stripped in index.table3_key_by_name:
            return stripped
    for step in chain:
        supplied = index.acts_supplying_year.get(step, ())
        if len(supplied) == 1:
            return supplied[0]
    return None


@dataclass(frozen=True)
class _Verdict:
    """What one source said about one act section.

    An identifier or a reason, never both; ``neither`` is how the credits say
    they had nothing to contribute, which Table III never does.
    """

    iri: str | None = None
    usc_title: str | None = None
    usc_section: str | None = None
    reason: str | None = None
    statutes_at_large_volume: str | None = None
    statutes_at_large_page: str | None = None

    def __post_init__(self) -> None:
        if self.iri is not None and self.reason is not None:
            raise ValueError("a source states an identifier or a reason, never both")


_SILENT = _Verdict()


def _resolve_through_table3(
    citation: ActRelativeCitation, index: ActIndex, act_key: str, table3_key: str
) -> _Verdict:
    """Table III's verdict. Always an identifier or a reason, never silence."""

    if table3_key in index.incomplete_sources:
        return _Verdict(reason="source_incomplete")
    rows = index.classifications.get(table3_key, {}).get(citation.section, ())
    if not rows:
        return _Verdict(reason="act_section_not_classified")
    if len(rows) > 1:
        page_range = index.act_page_range(act_key)
        if page_range is not None:
            low, high = page_range
            # Sound even though the range is only an upper bound: a page
            # outside a range that is too WIDE is outside the true one. The
            # converse is deliberately NOT taken — the surviving rows are
            # never bound to a name here, so they cannot be used by accident.
            # The range is derived from popular-name start pages, and 6.6% of
            # the pages such a range accepts (2,240 of 34,113 measured) belong
            # to a different division; narrowing on that basis would mint
            # exactly the wrong identifier this line of work exists to
            # prevent. It would decide 2,426 of the pinned index's 3,170
            # in-range multi-row lookups, and refusing them is the price.
            if not any(low <= page <= high for *_, page in rows if page is not None):
                return _Verdict(reason="act_section_outside_act")
        return _Verdict(reason="act_section_ambiguous")
    usc_title, usc_section, status, page = rows[0]
    if status:
        return _Verdict(reason="classification_not_current")
    if not (usc_title and usc_section):
        return _Verdict(reason="act_section_not_classified")
    try:
        iri = canonical_usc_iri(usc_title, usc_section)
    except ValueError:
        return _Verdict(usc_title=usc_title, usc_section=usc_section, reason="usc_section_not_expressible")
    return _Verdict(
        iri=iri,
        usc_title=usc_title,
        usc_section=usc_section,
        statutes_at_large_page=str(page) if page is not None else None,
    )


def _verdict_from_credits(credit: SourceCreditAnswer) -> _Verdict:
    """The credits' verdict. Silence unless the lookup actually resolved."""

    if credit.status != "resolved":
        return _SILENT
    provenance = {
        "usc_title": credit.usc_title,
        "usc_section": credit.usc_section,
        "statutes_at_large_volume": credit.statutes_at_large_volume,
        "statutes_at_large_page": credit.statutes_at_large_page,
    }
    try:
        return _Verdict(iri=canonical_usc_iri(credit.usc_title, credit.usc_section), **provenance)
    except ValueError:
        return _Verdict(reason="usc_section_not_expressible", **provenance)


def act_name_absence_reason(name: str, index: ActIndex) -> str:
    """Which of the three absences :func:`resolve_act_name` met, in the source's terms.

    All three were reported as ``act_not_in_index``, which is true of one of
    them. Asked for the Congressional Review Act, a reader was told the act is
    absent from an index that lists it by name and simply classifies nothing
    under it -- a statement about the source that the source contradicts.

    The split is derivable rather than descriptive, which is why it is here and
    not in a comment. Measured against the pinned index over the 13,648 names
    it reaches -- its 13,626 ``name_key`` values plus the ``see also`` targets
    that appear as nothing else -- these three predicates partition the 107
    unanswerable names **67 / 21 / 19**.

    That is NOT the 63 / 25 / 19 :func:`resolve_act_name` notes, and the four
    names between them are the reason this walks the chain instead of testing
    the asked name alone. ``articles of war`` is a ``see`` row pointing at
    ``uniform code of military justice``, which the source LISTS as a ``cite``
    row and publishes no Table III key for; the reference does not dead-end,
    it lands on a listed act with nothing filed under it. Saying "the trail
    stops" there would be false, and the raw rows say so:
    ``articles for the government of the navy``,
    ``admiralty jurisdiction act (extension`` and
    ``interstate commerce commission dangerous article act`` are the same
    shape. The older counts describe the name SETS; these describe what a
    caller is told, which is what a reason code is for.

    Order matters: a name the source cites is answered by the first branch even
    when it also carries a ``see also``, because "listed here, nothing filed
    under it" is the more specific statement.
    """

    chain = stated_name_chain(name, index)
    if any(step in index.cited_names for step in chain):
        return "act_listed_without_classification"
    if len(chain) > 1:
        return "act_alias_target_not_listed"
    return "act_not_in_index"


def resolve_act_relative_citation(
    citation: ActRelativeCitation,
    *,
    index: ActIndex,
    source_credits: SourceCreditIndex | None = None,
) -> ActResolution:
    """Resolve one act-relative citation to a U.S.C. identifier, or say why not."""

    act_key = resolve_act_name(citation.act_key, index)
    if act_key is None:
        return ActResolution(citation, unresolved_reason=act_name_absence_reason(citation.act_key, index))
    table3_key = index.table3_key_by_name[act_key]
    stated = index.division_by_name.get(act_key)
    common = {"act_key": act_key, "table3_key": table3_key}

    # A division the citation itself names is the strongest discriminator
    # there is; if it contradicts the resolved act's division, the two halves
    # disagree about which act is meant and nothing here picks a winner. The
    # credits are not consulted afterwards — there is no agreed key to consult
    # them under — and the resolution records that as ``not_consulted``.
    if citation.division and stated and citation.division != stated[0]:
        return ActResolution(citation, **common, unresolved_reason="act_division_conflict")

    table3 = _resolve_through_table3(citation, index, act_key, table3_key)

    # The second source is consulted even when Table III answered, because a
    # disagreement is a finding; and even when Table III's page could not be
    # read, because a hole in one source is exactly what a second is for.
    if source_credits is None:
        credit = SourceCreditAnswer(status="not_consulted")
    else:
        credit = source_credits.lookup(
            table3_key if _PUBLIC_LAW_KEY.fullmatch(table3_key or "") else None,
            # Equal whenever both are stated: the conflict above already
            # returned. This reads "whichever half named a division".
            stated[0] if stated else citation.division,
            citation.section,
        )
    credits = _verdict_from_credits(credit)

    shared = {**common, "table3_reason": table3.reason, "source_credit_status": credit.status}

    if table3.iri is not None and credits.iri is not None:
        if table3.iri != credits.iri:
            return ActResolution(citation, **shared, unresolved_reason="sources_disagree")
        # Agreed. The identifier and its components are Table III's; the
        # Statutes at Large volume and page are the credits', which state a
        # volume the Table III loader does not carry.
        answer, answered_by = (
            _Verdict(
                iri=table3.iri,
                usc_title=table3.usc_title,
                usc_section=table3.usc_section,
                statutes_at_large_volume=credits.statutes_at_large_volume,
                statutes_at_large_page=credits.statutes_at_large_page,
            ),
            "both",
        )
    elif credits.iri is not None:
        answer, answered_by = credits, "source_credits"
    elif table3.iri is not None:
        answer, answered_by = table3, "table3"
    else:
        # Neither published an identifier, so a reason is published instead.
        # Table III's stands — it always states one, and it is the source with
        # the coverage — with a single truthfulness exception:
        # `act_section_not_classified` asserts a plain absence, and a credit
        # target the lexical space cannot spell falsifies it. Publishing "not
        # classified" then would publish an absence of knowledge as knowledge.
        unseated = credits.reason is not None and table3.reason == "act_section_not_classified"
        refusal = credits if unseated else table3
        return ActResolution(
            citation,
            **shared,
            usc_title=refusal.usc_title,
            usc_section=refusal.usc_section,
            unresolved_reason=refusal.reason,
        )

    return ActResolution(
        citation,
        **shared,
        usc_title=answer.usc_title,
        usc_section=answer.usc_section,
        iri=answer.iri,
        answered_by=answered_by,
        statutes_at_large_volume=answer.statutes_at_large_volume,
        statutes_at_large_page=answer.statutes_at_large_page,
    )
