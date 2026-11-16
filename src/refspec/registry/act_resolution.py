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
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from functools import cached_property
from pathlib import Path
from typing import NamedTuple

from refspec.registry.citation_grammar import (
    ActRelativeCitation,
    act_name_with_trailing_year,
    normalize_popular_name,
)

__all__ = [
    "ALIAS_PRECEDENCE_RULE",
    "ALIAS_YEAR_RULE",
    "ANSWERING_SOURCES",
    "DIVISION_RULE",
    "GENERIC_ACT_STEM_STOPLIST",
    "SOURCE_COMPOSITION_RULE",
    "SOURCE_CREDIT_STATUSES",
    "UNRESOLVED_REASONS",
    "USC_ACT_INDEX_ARTIFACT",
    "USC_SOURCE_CREDIT_ARTIFACT",
    "ActIndex",
    "ActResolution",
    "Classification",
    "PopularNameRecord",
    "SourceCreditAnswer",
    "SourceCreditIndex",
    "SourceCreditTarget",
    "StatutoryShortTitleMatch",
    "act_name_absence_reason",
    "canonical_usc_iri",
    "find_statutory_short_titles",
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
#: classifications and quarantine tables distinguish them and must agree on the
#: admitted artifact; the shared popular-name file fits either one.
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
        "quarantine.parquet": "sha256:c2d956c67dd05203a5733dff3fd1b74cb2e3da3f6f57e61b8d078d0954f71ee9",
    },
    "usc-act-index-2026-08-22": {
        "usc-popular-names.parquet": "sha256:603d5b072133d8fe6802736aeaa70b9fb9832e4fb996158a083fae3ce1026a9a",
        "usc-act-sections.parquet": "sha256:9040d4460e90704aef911b4d4f704e9f432cebd7b58717f31f090a3008ca6159",
        "quarantine.parquet": "sha256:a89305172a27e682488e05e8fc82d8b0521d20a8fcee7d97a00331e8527acfac",
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

#: Exclude only when every complete page is outside the conservative division
#: range, regardless of row count. Unknown or narrowed pages cannot prove it;
#: an in-range page does not establish membership. The next start bounds the end.
DIVISION_RULE = "act-division-complete-pages-exclusion-v2"

#: Both sources are consulted, always. Either may answer alone; the same
#: identifier from both says ``both``; different identifiers REFUSE. The
#: measured cause of disagreement is an act section that classified to more
#: than one place, where each source retains a different one — (114-94,
#: div. C, §32101): Table III says 22 U.S.C. 2714a, the credits say
#: 26 U.S.C. 7345, and both are true. Naming one would be arbitrary.
#: Multiple credit targets likewise prevent selecting a lone Table III candidate.
SOURCE_COMPOSITION_RULE = "table3-and-source-credits-plurality-and-disagreement-refuse-v2"

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
    "act_name_ambiguous",
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
    #: Also covers multiple credit targets when Table III supplies one candidate.
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
class PopularNameRecord:
    """One popular name and one source statement; shared by builder and lookup."""

    name: str
    content_type: str
    table3_key: str | None = None
    usc_title: str | None = None
    usc_section: str | None = None
    see_also: str | None = None
    release_point: str | None = None
    division: str | None = None
    statutes_at_large_volume: str | None = None
    statutes_at_large_page: str | None = None
    #: Builder evidence, absent from the sealed table.
    statutes_at_large_witness: str | None = None
    refused_usc_anchor: str | None = None


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

    #: Populated only where the source credits name several possible targets.
    source_credit_targets: tuple[SourceCreditTarget, ...] = ()
    #: Retain each source's identifier when they disagree; select neither.
    conflicting_targets: Mapping[str, str] = field(default_factory=dict)
    #: Table III's candidate when multiple credit targets prevent a unique answer.
    table3_candidate_iri: str | None = None
    #: Division established by the name source or explicitly stated citation.
    act_division: str | None = None
    #: Competing name records, including records ruled out by a stated division.
    name_sources: tuple[PopularNameRecord, ...] = ()
    #: Each compatible identity's lookup; none is selected by their parent result.
    candidate_resolutions: tuple[ActResolution, ...] = ()

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
        if self.conflicting_targets and (
            self.unresolved_reason != "sources_disagree"
            or set(self.conflicting_targets) != {"table3", "source_credits"}
            or len(set(self.conflicting_targets.values())) != 2
        ):
            raise ValueError("conflicting targets require two distinct source answers and a disagreement refusal")
        if self.table3_candidate_iri is not None and (
            self.unresolved_reason != "act_section_ambiguous" or self.source_credit_status != "multi_target"
        ):
            raise ValueError("a Table III candidate requires a multiple-target refusal")
        if self.candidate_resolutions and (
            self.unresolved_reason != "act_name_ambiguous"
            or len(self.candidate_resolutions) < 2
            or any(c.candidate_resolutions or c.citation != self.citation for c in self.candidate_resolutions)
        ):
            raise ValueError("name candidates require an ambiguity refusal and unnested lookups of the same citation")


@dataclass(frozen=True)
class ActIndex:
    """The two joins, loaded from the pinned artifact or built for a test."""

    #: None means the listed name has multiple law keys; never a first-row winner.
    table3_key_by_name: Mapping[str, str | None] = field(default_factory=dict)
    #: Only names with multiple law/division identities need these source records.
    name_candidates: Mapping[str, tuple[PopularNameRecord, ...]] = field(default_factory=dict)
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
    division_by_name: Mapping[str, tuple[str, int | None]] = field(default_factory=dict)
    #: Table III key -> every division of that law and where it begins, page
    #: ascending. Read every qualifying source row, including ambiguous names.
    division_starts: Mapping[str, tuple[tuple[str, int], ...]] = field(default_factory=dict)
    #: The producer retained non-single-page spellings separately from first pages.
    narrowed_page_sections: frozenset[tuple[str, str]] = frozenset()

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

        if act_key in self.name_candidates:
            return None
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

    def find_statutory_short_titles(
        self, text: str, *, deduplicate: bool = True
    ) -> tuple[StatutoryShortTitleMatch, ...]:
        """Extract enacted statutory short titles from unstructured prose via maximal-NP scanning."""

        return find_statutory_short_titles(text, self, deduplicate=deduplicate)

    def scan_text(self, text: str, *, deduplicate: bool = True) -> tuple[StatutoryShortTitleMatch, ...]:
        """Alias for :meth:`find_statutory_short_titles` over unstructured prose."""

        return find_statutory_short_titles(text, self, deduplicate=deduplicate)

    @classmethod
    def from_artifact(cls, artifact_dir: Path) -> ActIndex:
        """Load from a sealed ``usc-act-index-artifact-v1`` directory, verifying pins."""

        directory = Path(artifact_dir)
        receipt = json.loads((directory / "receipt.json").read_text(encoding="utf-8"))
        if not (_artifacts_stating(directory / "usc-act-sections.parquet")
                & _artifacts_stating(directory / "quarantine.parquet")):
            raise ValueError("classifications and quarantine must belong to the same act artifact")
        narrowed = frozenset(
            (row["table3_key"], row["raw_value"].partition(" -> ")[0])
            for row in _read_pinned_parquet(directory, "quarantine.parquet")
            if row["reason"] == "statutes_at_large_page_span_narrowed"
        )
        records_by_name: dict[str, set[PopularNameRecord]] = {}
        alias_by_name: dict[str, str] = {}
        cited_names: set[str] = set()
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
                record = PopularNameRecord(**{k: v for k, v in row.items() if k not in {"name_key", "see_also_key"}})
                records_by_name.setdefault(name, set()).add(record)
            if not (row["division"] and row["statutes_at_large_page"]):
                continue
            page = int(row["statutes_at_large_page"])
            if row["table3_key"]:
                # Every qualifying row, not just a name's first: a division
                # begins where its EARLIEST act does, and the acts that state
                # it are spread across the table.
                by_division = starts.setdefault(row["table3_key"], {})
                by_division[row["division"]] = min(by_division.get(row["division"], page), page)
        table3_key_by_name = {}
        division_by_name = {}
        name_candidates = {}
        for name, records in records_by_name.items():
            laws = {r.table3_key for r in records}
            table3_key_by_name[name] = next(iter(laws)) if len(laws) == 1 else None
            identities = {(r.table3_key, r.division) for r in records}
            if len(identities) > 1:
                name_candidates[name] = tuple(sorted(records, key=lambda r: tuple(str(v or "") for v in asdict(r).values())))
            else:
                division = next(iter(identities))[1]
                if division:
                    page = min((int(r.statutes_at_large_page) for r in records if r.statutes_at_large_page), default=None)
                    division_by_name[name] = (division, page)
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
            name_candidates=name_candidates,
            alias_by_name=alias_by_name,
            classifications=classifications,
            incomplete_sources=frozenset(hole["table3_key"] for hole in receipt.get("source_incomplete", ())),
            cited_names=frozenset(cited_names),
            division_by_name=division_by_name,
            division_starts={
                key: tuple(sorted(by_division.items(), key=lambda item: (item[1], item[0])))
                for key, by_division in starts.items()
            },
            narrowed_page_sections=narrowed,
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
    targets: tuple[SourceCreditTarget, ...] = ()

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
            return SourceCreditAnswer(status="multi_target", targets=found)
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
    page_range = index.act_page_range(act_key)
    if page_range is not None and (table3_key, citation.section) not in index.narrowed_page_sections:
        low, high = page_range
        # Exclusion only: unknown pages cannot prove it, and narrowing to one
        # in-range row cannot identify that row as belonging to the named act.
        if all(page is not None and not low <= page <= high for *_, page in rows):
            return _Verdict(reason="act_section_outside_act")
    if len(rows) > 1:
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
    sources = index.name_candidates.get(act_key, ())
    if sources:
        groups = {}
        for source in sources:
            if citation.division and source.division and citation.division != source.division:
                continue
            identity = (source.table3_key, source.division or citation.division)
            groups.setdefault(identity, []).append(source)
        candidates = []
        for (law, division), records in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1] or "")):
            page = min((int(r.statutes_at_large_page) for r in records if r.statutes_at_large_page), default=None)
            narrowed = replace(index, table3_key_by_name={act_key: law}, name_candidates={},
                               division_by_name={act_key: (division, page)} if division else {})
            candidates.append(resolve_act_relative_citation(citation, index=narrowed, source_credits=source_credits))
        if len(candidates) == 1:
            return replace(candidates[0], name_sources=sources)
        return ActResolution(citation, act_key=act_key, table3_key=index.table3_key_by_name[act_key],
                             unresolved_reason="act_name_ambiguous" if candidates else "act_division_conflict",
                             name_sources=sources, candidate_resolutions=tuple(candidates))
    table3_key = index.table3_key_by_name[act_key]
    stated = index.division_by_name.get(act_key)
    common = {"act_key": act_key, "table3_key": table3_key,
              "act_division": stated[0] if stated else citation.division}

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

    shared = {**common, "table3_reason": table3.reason, "source_credit_status": credit.status,
              "source_credit_targets": credit.targets}

    if table3.iri is not None and credit.status == "multi_target":
        return ActResolution(citation, **shared, unresolved_reason="act_section_ambiguous",
                             table3_candidate_iri=table3.iri)
    if table3.iri is not None and credits.iri is not None:
        if table3.iri != credits.iri:
            return ActResolution(citation, **shared, unresolved_reason="sources_disagree",
                                 conflicting_targets={"table3": table3.iri, "source_credits": credits.iri})
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


# --------------------------------------------------------------------------- #
# Maximal-NP statutory short-title scanning over unstructured prose
# --------------------------------------------------------------------------- #

#: Generic demonstratives and articles that appear before ``Act`` in legislative
#: and regulatory prose ("This Act", "Such Act", "That Act", "The Act") and
#: never identify a statutory short title on their own, even on a synthetic index.
GENERIC_ACT_STEM_STOPLIST: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "any",
        "each",
        "other",
        "present",
        "prior",
        "said",
        "same",
        "such",
        "that",
        "the",
        "this",
    }
)

_PROSE_CHAR_MAP = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‛": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "‟": '"',
        "″": '"',
        "\u00a0": " ",
        **dict.fromkeys("‐‑‒–—―−\x96\x97", "-"),
    }
)
_PROSE_PARAGRAPH_BREAK_RE = re.compile(r"\r?\n[ \t]*\r?\n")
_PROSE_ACT_CONNECTORS = frozenset(
    {
        "of",
        "for",
        "and",
        "or",
        "the",
        "to",
        "on",
        "in",
        "with",
        "&",
        "by",
        "against",
        "from",
    }
)
_PROSE_ACT_STOP_TOKENS = frozenset(
    {
        "ACTS",
        "USC",
        "USCA",
        "USCS",
        "CFR",
        "STAT",
        "FR",
        "PL",
        "EO",
        "PUB",
        "AMEND",
        "AMENDS",
        "AMENDED",
        "AMENDING",
        "UNDER",
        "PURSUANT",
        "ENACTED",
        "TITLED",
        "ENTITLED",
    }
)
_PROSE_SENTENCE_INITIAL_OPENERS = frozenset(
    {
        "all",
        "although",
        "anything",
        "because",
        "both",
        "but",
        "cf",
        "compare",
        "despite",
        "during",
        "each",
        "either",
        "even",
        "every",
        "everything",
        "except",
        "few",
        "following",
        "given",
        "hence",
        "however",
        "if",
        "including",
        "instead",
        "irrespective",
        "many",
        "meanwhile",
        "moreover",
        "most",
        "neither",
        "nevertheless",
        "no",
        "none",
        "nonetheless",
        "nor",
        "note",
        "nothing",
        "notwithstanding",
        "once",
        "only",
        "otherwise",
        "pending",
        "regarding",
        "regardless",
        "respecting",
        "save",
        "see",
        "several",
        "since",
        "so",
        "some",
        "something",
        "then",
        "therefore",
        "though",
        "throughout",
        "thus",
        "unless",
        "unlike",
        "until",
        "when",
        "whenever",
        "where",
        "whereas",
        "whether",
        "while",
        "within",
        "yet",
    }
)
_PROSE_ABBREV_DOTTED_RE = re.compile(
    r"(?:(?:[A-Za-z]\.){1,6}(?:-[A-Za-z0-9']+)?|\d+\.\d+|(?i:"
    r"Adm|Admin|App|Art|Assn|Brig|Bros|Capt|Cf|Ch|Cmdr|Co|Col|Coop|Corp|Cpl"
    r"|Dept|Dev|Div|Dr|Envt|Fed|Ft|Gen|Gov|Govt|Hon|Inc|Intl|Jr|Lt|Ltd|Maj"
    r"|Mgmt|Mr|Mrs|Ms|Mt|Natl|No|Nos|Para|Prev|Prof|Pt|Pub|Pvt|Rehab|Rep"
    r"|Rev|Ry|Sec|Secs|Sen|Sgt|Sr|St|Ste|Subch|Subpt|Subsec|Supp|Tech|Tit|Vet"
    r")\.)"
)
_PROSE_CAP_TOKEN_RE = re.compile(
    r"(?:(?:[A-Z]\.){1,6}(?:-[\w']+)?|\d+\.\d+|[A-Z0-9][\w'\-&]*(?:\([A-Za-z0-9.\-&]{1,12}\))*\.?)"
)
_PROSE_FWD_LEX_RE = re.compile(
    r"(?P<para>\r?\n[ \t]*\r?\n)"
    r"|(?P<ws>\s+)"
    r"|(?P<comma>,)"
    r"|(?P<quoted>\"[^\"\r\n]{1,32}\"|''[^'\r\n]{1,32}'')"
    r"|(?P<paren>\([^()\r\n]{1,40}\))"
    r"|(?P<word>"
    r"(?:[A-Za-z]\.){2,6}(?:-[\w']+)?"
    r"|\d+\.\d+"
    r"|[A-Za-z0-9][\w'\-&]*(?:\([A-Za-z0-9.\-&]{1,12}\))+"
    r"|[A-Za-z0-9][\w'\-&]*\.?"
    r"|§+"
    r"|&"
    r")"
    r"|(?P<other>.)"
)
_PROSE_LIST_MARKER_PAREN_RE = re.compile(r"^\([A-Za-z0-9]{1,4}\)$")
_PROSE_DESIGNATOR_RE = re.compile(
    r"^(?:"
    r"[A-Z]{1,3}"
    r"|[IVXLCDM]{1,8}"
    r"|\d{1,5}[A-Za-z0-9.\-]*(?:\([A-Za-z0-9.\-]{1,6}\))*"
    r"|\([A-Za-z0-9]{1,4}\)(?:\([A-Za-z0-9]{1,4}\))*"
    r")$"
)
_PROSE_DESIGNATOR_CONJ = frozenset({"and", "&", "or", "through", "to"})
_PROSE_STRUCTURAL_CONTAINERS = frozenset(
    {
        "article",
        "articles",
        "art",
        "ch",
        "chapter",
        "chapters",
        "clause",
        "clauses",
        "div",
        "division",
        "divisions",
        "item",
        "items",
        "para",
        "paragraph",
        "paragraphs",
        "part",
        "parts",
        "pt",
        "schedule",
        "sec",
        "secs",
        "section",
        "sections",
        "subch",
        "subchapter",
        "subchapters",
        "subparagraph",
        "subparagraphs",
        "subpart",
        "subparts",
        "subpt",
        "subsec",
        "subsection",
        "subsections",
        "subtitle",
        "subtitles",
        "tit",
        "title",
        "titles",
        "§",
        "§§",
    }
)
_PROSE_AMENDMENTS_TAIL_RE = re.compile(r"\s+Amendments?\b")
_PROSE_OF_YEAR_TAIL_RE = re.compile(r"\s*(?:,\s*)?of\s+(?P<year>(?:1[789]|20)\d{2})\b")
_PROSE_COMMA_YEAR_TAIL_RE = re.compile(r"\s*,\s*(?P<year>(?:1[789]|20)\d{2})\b")
_PROSE_FOUR_DIGIT_YEAR_RE = re.compile(r"^(?:1[789]|20)\d{2}$")
_PROSE_QUOTED_ACT_END_RE = re.compile(r"\bAct\s*[\"']+$")


class _ProseToken(NamedTuple):
    kind: str
    raw: str
    bare: str
    start: int
    has_comma: bool


@dataclass(frozen=True, slots=True)
class StatutoryShortTitleMatch:
    """One enacted statutory short title resolved from unstructured prose."""

    surface: str
    act_key: str
    table3_key: str | None
    start: int
    end: int

    @property
    def normalized_surface(self) -> str:
        """Single-line whitespace-collapsed rendering of :attr:`surface`."""

        return re.sub(r"\s+", " ", self.surface).strip()

    @property
    def resolved_act_key(self) -> str:
        """Alias preserving compatibility with callers reading ``resolved_act_key``."""

        return self.act_key


def _is_sentence_initial(norm: str, pos: int) -> bool:
    """Whether ``pos`` sits at the opening word of a sentence, line heading, or quoted/bulleted clause."""

    idx = pos
    while idx > 0 and norm[idx - 1] in " \t\"'([{-*•":
        idx -= 1
    return idx == 0 or norm[idx - 1] in ".!?;:\n\r"


def _tokenize_window_backward(norm: str, window_start: int, act_start: int) -> list[_ProseToken]:
    """Tokenize ``norm[window_start:act_start]`` in one forward ``O(W)`` pass and walk right-to-left."""

    lex_items: list[tuple[str, str, int, bool]] = []
    for m in _PROSE_FWD_LEX_RE.finditer(norm, window_start, act_start):
        lkind = m.lastgroup
        if lkind == "ws" or lkind is None:
            continue
        raw = m.group()
        if lkind == "comma":
            if lex_items and lex_items[-1][0] != "barrier" and not lex_items[-1][3]:
                prev_k, prev_r, prev_s, _ = lex_items[-1]
                lex_items[-1] = (prev_k, prev_r, prev_s, True)
            else:
                lex_items.append(("barrier", ",", m.start(), False))
            continue
        if lkind == "para" or lkind == "other":
            lex_items.append(("barrier", raw, m.start(), False))
            continue
        if lkind == "quoted":
            if _PROSE_QUOTED_ACT_END_RE.search(raw) or not any(ch.isalnum() for ch in raw):
                # An earlier quoted Act title ("Clean Air Act") wraps a complete title rather than an inner nickname.
                lex_items.append(("barrier", raw, m.start(), False))
            else:
                lex_items.append(("quoted", raw, m.start(), False))
            continue
        lex_items.append((lkind, raw, m.start(), False))

    if not lex_items or lex_items[-1][0] == "barrier" or lex_items[-1][3]:
        # A barrier or comma immediately preceding "Act" cannot belong to this Act's noun phrase.
        return []

    tokens: list[_ProseToken] = []
    for k in range(len(lex_items) - 1, -1, -1):
        kind, raw_word, tok_start, has_comma = lex_items[k]
        if kind == "barrier":
            break
        if kind == "quoted":
            tokens.append(_ProseToken("quoted", raw_word, raw_word, tok_start, has_comma))
            continue
        if kind == "paren":
            has_left_np_neighbor = (
                k > 0
                and lex_items[k - 1][0] in {"word", "quoted", "paren"}
                and not lex_items[k - 1][1].endswith(".")
                and (
                    lex_items[k - 1][1][:1].isupper()
                    or lex_items[k - 1][1].lower() in {"the", "a", "an"}
                )
            )
            if (
                any(ch.isupper() or ch.isdigit() for ch in raw_word)
                or _PROSE_LIST_MARKER_PAREN_RE.fullmatch(raw_word)
                or has_left_np_neighbor
            ):
                tokens.append(_ProseToken("paren", raw_word, raw_word, tok_start, has_comma))
                continue
            break

        bare_word = raw_word.rstrip(".")
        upper_word = bare_word.upper()
        lower_word = bare_word.lower()

        if raw_word.endswith("."):
            if _PROSE_ABBREV_DOTTED_RE.fullmatch(raw_word):
                prev_bare_upper = (
                    lex_items[k - 1][1].replace(".", "").upper()
                    if k > 0 and lex_items[k - 1][0] == "word"
                    else ""
                )
                if upper_word == "L" and prev_bare_upper in {"PUB", "P"}:
                    break
                if upper_word == "APP" and prev_bare_upper in {"USC", "USCA", "USCS", "C"}:
                    break
            else:
                # Only treat an unknown capitalized dotted word as part of the NP when immediately preceded
                # by an article ("the Brig. Smith Act"), otherwise "." ends the preceding sentence.
                preceded_by_article = (
                    raw_word[:1].isupper()
                    and k > 0
                    and lex_items[k - 1][0] == "word"
                    and not lex_items[k - 1][1].endswith(".")
                    and not lex_items[k - 1][3]
                    and lex_items[k - 1][1].lower() in {"the", "a", "an"}
                )
                if not preceded_by_article:
                    break

        if upper_word in _PROSE_ACT_STOP_TOKENS:
            break

        if (
            _PROSE_CAP_TOKEN_RE.fullmatch(raw_word)
            or lower_word in _PROSE_ACT_CONNECTORS
            or lower_word in _PROSE_STRUCTURAL_CONTAINERS
        ):
            tokens.append(_ProseToken("word", raw_word, bare_word, tok_start, has_comma))
            continue
        break

    return tokens


def _resolve_prose_act_candidate(
    norm: str,
    span_start: int,
    act_end: int,
    index: ActIndex,
    *,
    leading_the_start: int | None = None,
) -> tuple[int, int, str] | None:
    """Resolve one candidate NP start through forward ``Amendments`` and year tails, longest span first."""

    base_end = act_end
    amend_match = _PROSE_AMENDMENTS_TAIL_RE.match(norm, base_end)
    if amend_match is not None and not _PROSE_PARAGRAPH_BREAK_RE.search(norm, base_end, amend_match.end()):
        base_end = amend_match.end()

    def _try_surface(c_start: int, c_end: int, probe_text: str) -> tuple[int, int, str] | None:
        resolved = resolve_act_name(probe_text, index)
        if resolved is None:
            reordered = act_name_with_trailing_year(normalize_popular_name(probe_text))
            if reordered is not None:
                resolved = resolve_act_name(reordered, index)
        if resolved is not None:
            return c_start, c_end, resolved
        if leading_the_start is not None and c_start == span_start:
            with_the = f"the {probe_text}"
            resolved_the = resolve_act_name(with_the, index)
            if resolved_the is not None:
                return leading_the_start, c_end, resolved_the
        return None

    stem_surface = re.sub(r"\s+", " ", norm[span_start:base_end]).strip()
    of_year = _PROSE_OF_YEAR_TAIL_RE.match(norm, base_end)
    if of_year is not None and not _PROSE_PARAGRAPH_BREAK_RE.search(norm, base_end, of_year.end()):
        yr = of_year.group("year")
        yr_end = of_year.end()
        # Try "of YYYY" first, then ", YYYY" for pre-modern statutes titled with a comma year.
        for candidate_str in (f"{stem_surface} of {yr}", f"{stem_surface}, {yr}"):
            hit = _try_surface(span_start, yr_end, candidate_str)
            if hit is not None:
                return hit
        # An explicit "of YYYY" belongs to the stated title; never drop it to match a different year's act.
        return None

    comma_year = _PROSE_COMMA_YEAR_TAIL_RE.match(norm, base_end)
    if comma_year is not None and not _PROSE_PARAGRAPH_BREAK_RE.search(norm, base_end, comma_year.end()):
        yr = comma_year.group("year")
        yr_end = comma_year.end()
        for candidate_str in (f"{stem_surface}, {yr}", f"{stem_surface} of {yr}"):
            hit = _try_surface(span_start, yr_end, candidate_str)
            if hit is not None:
                return hit
        # Unlike "of YYYY", ", YYYY" in prose may open the next clause ("Under the Clean Air Act, 2023 emissions..."),
        # so fall through to the pre-comma span when neither year-qualified spelling is indexed.

    return _try_surface(span_start, base_end, stem_surface)


def _match_structural_prefix_before_of(trimmed: list[_ProseToken]) -> int | None:
    """If ``trimmed`` opens with ``[Container] <Designator> [(and|or|through) <Designator>]* of <NP>``, return the ``of`` index."""

    idx = len(trimmed) - 1
    if idx < 1:
        return None
    if trimmed[idx].kind == "word" and trimmed[idx].bare.lower() in _PROSE_STRUCTURAL_CONTAINERS:
        idx -= 1
    if idx < 1 or not _PROSE_DESIGNATOR_RE.fullmatch(trimmed[idx].bare):
        return None
    idx -= 1
    while idx >= 2 and trimmed[idx].bare.lower() in _PROSE_DESIGNATOR_CONJ:
        if not _PROSE_DESIGNATOR_RE.fullmatch(trimmed[idx - 1].bare):
            break
        idx -= 2
    if idx >= 1 and trimmed[idx].bare.lower() == "of":
        return idx
    return None


def _trim_and_resolve_token_slice(
    raw_slice: list[_ProseToken],
    norm: str,
    act_start: int,
    act_end: int,
    index: ActIndex,
) -> tuple[int, int, str] | None:
    """Trim leading connectors/designators on one uninterrupted NP slice and resolve it without inner sub-slicing."""

    toks = list(raw_slice)
    leading_the_start: int | None = None
    while toks and toks[-1].kind == "word" and toks[-1].bare.lower() in _PROSE_ACT_CONNECTORS:
        leading_the_start = toks[-1].start if toks[-1].bare.lower() == "the" else None
        toks.pop()
    if not toks:
        return None

    def _attempt(active: list[_ProseToken], the_start: int | None) -> tuple[int, int, str] | None:
        if not active or not any(
            t.raw[:1].isupper() or t.kind == "quoted" for t in active
        ):
            return None
        c_start = active[-1].start
        stem_raw = re.sub(r"\s+", " ", norm[c_start:act_start]).strip()
        stem_norm = _LEADING_ARTICLE.sub("", normalize_popular_name(stem_raw)).strip()
        if not stem_norm or stem_norm in GENERIC_ACT_STEM_STOPLIST:
            return None
        return _resolve_prose_act_candidate(norm, c_start, act_end, index, leading_the_start=the_start)

    # First try the full maximal slice (preserving e.g. "Title I of the Elementary and Secondary Education Act of 1965").
    direct = _attempt(toks, leading_the_start)
    if direct is not None:
        return direct

    trimmed = list(toks)
    sub_the = leading_the_start
    changed = False
    while trimmed:
        if (trimmed[-1].kind == "paren" and _PROSE_LIST_MARKER_PAREN_RE.fullmatch(trimmed[-1].raw)) or (
            len(trimmed) >= 2
            and trimmed[-1].kind == "word"
            and not trimmed[-1].has_comma
            and _is_sentence_initial(norm, trimmed[-1].start)
            and (
                (trimmed[-2].kind == "word" and trimmed[-2].bare.lower() == "the")
                or (
                    trimmed[-1].bare.lower() in _PROSE_SENTENCE_INITIAL_OPENERS
                    and trimmed[-2].kind == "word"
                    and trimmed[-2].bare.lower() in _PROSE_ACT_CONNECTORS
                )
            )
        ):
            trimmed.pop()
            changed = True
        else:
            of_idx = _match_structural_prefix_before_of(trimmed)
            if of_idx is not None:
                trimmed = trimmed[:of_idx]
                changed = True
            else:
                break

        sub_the = None
        while trimmed and trimmed[-1].kind == "word" and trimmed[-1].bare.lower() in _PROSE_ACT_CONNECTORS:
            sub_the = trimmed[-1].start if trimmed[-1].bare.lower() == "the" else None
            trimmed.pop()

    if changed and trimmed:
        return _attempt(trimmed, sub_the)
    return None


def _build_candidate_slices(tokens: list[_ProseToken]) -> list[list[_ProseToken]]:
    """Order candidate slices longest-first, splitting only at coordinated inner ``Act`` boundaries or clause commas."""

    slices: list[list[_ProseToken]] = [tokens]
    seen_lengths: set[int] = {len(tokens)}

    def _push(sub: list[_ProseToken]) -> None:
        if sub and len(sub) not in seen_lengths:
            seen_lengths.add(len(sub))
            slices.append(sub)

    for idx_tok in range(len(tokens) - 1, 0, -1):
        tok = tokens[idx_tok]
        # 1. Coordinated multi-Act fallback ("Clean Air Act and the Safe Drinking Water Act"):
        #    only split after an earlier "Act [Amendments] [of/, YYYY]" when followed by explicit
        #    coordination (comma or and/&/or), never inside an uncoordinated compound NP
        #    ("Violence Against Women Act Reauthorization Act" or "Kelsey Smith Act Technical Amendments Act").
        if tok.kind == "word" and tok.raw == "Act":
            cur = idx_tok - 1
            if cur >= 0 and tokens[cur].kind == "word" and tokens[cur].bare in {"Amendment", "Amendments"}:
                cur -= 1
            tail_had_comma = tokens[cur + 1].has_comma
            if (
                cur >= 1
                and tokens[cur].kind == "word"
                and tokens[cur].bare.lower() == "of"
                and _PROSE_FOUR_DIGIT_YEAR_RE.fullmatch(tokens[cur - 1].bare)
            ):
                tail_had_comma = tokens[cur - 1].has_comma
                cur -= 2
            elif (
                tail_had_comma
                and cur >= 0
                and _PROSE_FOUR_DIGIT_YEAR_RE.fullmatch(tokens[cur].bare)
            ):
                tail_had_comma = tokens[cur].has_comma
                cur -= 1
            if cur >= 0 and tail_had_comma:
                if tokens[cur].bare.lower() in {"and", "&", "or"}:
                    cur -= 1
                if cur >= 0:
                    _push(tokens[: cur + 1])
            elif cur >= 1 and tokens[cur].bare.lower() in {"and", "&", "or"}:
                _push(tokens[:cur])

        # 2. Non-conjunction clause comma ("According to Congress, Clean Air Act rules apply"),
        #    skipping serial-title commas ("Prevention, Detection, and Smith Act") and comma-years (", 2023").
        if tok.has_comma:
            right_neighbor_bare = tokens[idx_tok - 1].bare.lower()
            if right_neighbor_bare not in {"and", "&", "or"} and not _PROSE_FOUR_DIGIT_YEAR_RE.fullmatch(
                right_neighbor_bare
            ):
                _push(tokens[:idx_tok])

    return slices


def find_statutory_short_titles(
    text: str,
    index: ActIndex,
    *,
    deduplicate: bool = True,
) -> tuple[StatutoryShortTitleMatch, ...]:
    """Deterministically extract enacted statutory short titles from unstructured prose.

    Tokenizes each 450-character pre-``Act`` window in one forward ``O(W)`` pass and
    arbitrates overlapping matches longest-span first via ``O(M log M)`` binary search,
    enforcing two precision invariants:

    1. **Generic-stem stoplisting** (:data:`GENERIC_ACT_STEM_STOPLIST`): anaphoric and
       determiner phrases (``This Act``, ``Such Act``, ``That Act``, ``The Act``, ``An Act``,
       ``Said Act``) are refused outright before consulting ``index``.
    2. **Maximal-NP longest-span resolution**: an uninterrupted noun phrase (including
       middle initials, honorifics, inner nicknames/parentheticals, and multi-``Act``
       compounds) is queried whole and never sub-sliced into shorter inner suffixes, so
       unenacted bill titles such as ``Kelsey Smith Act``, ``John L. Smith Act``, or
       ``SEC Small Business Act`` never false-positive onto inner suffixes.
    """

    if not text:
        return ()
    raw_text = str(text)
    norm = raw_text.translate(_PROSE_CHAR_MAP)
    raw_hits: list[StatutoryShortTitleMatch] = []

    for match in re.finditer(r"\bAct\b", norm):
        act_start, act_end = match.start(), match.end()
        window_start = max(0, act_start - 450)
        tokens = _tokenize_window_backward(norm, window_start, act_start)
        if not tokens:
            continue

        for cand_slice in _build_candidate_slices(tokens):
            resolved_hit = _trim_and_resolve_token_slice(cand_slice, norm, act_start, act_end, index)
            if resolved_hit is not None:
                hit_start, hit_end, resolved_key = resolved_hit
                raw_hits.append(
                    StatutoryShortTitleMatch(
                        surface=raw_text[hit_start:hit_end],
                        act_key=resolved_key,
                        table3_key=index.table3_key_by_name.get(resolved_key),
                        start=hit_start,
                        end=hit_end,
                    )
                )
                break

    if not raw_hits:
        return ()

    # Arbitrate overlapping matches longest-span first in O(M log M) via sorted disjoint intervals.
    by_length = sorted(raw_hits, key=lambda item: (-(item.end - item.start), item.start))
    kept_starts: list[int] = []
    kept_ends: list[int] = []
    kept: list[StatutoryShortTitleMatch] = []
    for candidate in by_length:
        idx = bisect_right(kept_starts, candidate.start)
        if (idx > 0 and kept_ends[idx - 1] > candidate.start) or (
            idx < len(kept_starts) and kept_starts[idx] < candidate.end
        ):
            continue
        kept_starts.insert(idx, candidate.start)
        kept_ends.insert(idx, candidate.end)
        kept.append(candidate)
    kept.sort(key=lambda item: (item.start, item.end))

    if not deduplicate:
        return tuple(kept)
    seen_keys: set[str] = set()
    unique: list[StatutoryShortTitleMatch] = []
    for item in kept:
        if item.act_key not in seen_keys:
            seen_keys.add(item.act_key)
            unique.append(item)
    return tuple(unique)

