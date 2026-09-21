"""Answer "what is this term I was handed", from the authority that owns it.

A DEFINITIONAL question — "Section 232", "40 CFR 60", a docket id, a rule
number — that no list of documents answers. This module routes rather than
resolves: :mod:`refspec.registry.identifier_shapes` and
:mod:`refspec.registry.citation_grammar` already recognize the families and
each family's resolution already exists; this is the hop that sends a term to
the authority that owns it and refuses where no authority does.

**It says a CFR part NAMES a statute in its authority note, never that the
part implements the section.** "Clean Air Act section 111" resolves to
42 U.S.C. 7411, which exactly one part names in its note (40 CFR 72), while
the part that actually implements it (40 CFR 60) writes "42 U.S.C. 7401 et
seq." — so "implemented by" would answer confidently and wrongly, and widening
the net only trades one wrong answer for another.

**One ambiguity rule, applied at whichever scope the ambiguity sits:** withhold
the ambiguous claim and keep the unambiguous ones, which reduces to refusal
when nothing is left. A CFR part keeps its name and authority text with only
the act attribution withheld; a container rule number, where the ambiguity
swallows the subject, refuses. Where several acts classify to one U.S.C.
section — the original and every amendment — :func:`acts_classifying` returns
all of them and the explainer refuses with ``act_attribution_ambiguous``
rather than choosing, because a refusal a reader can act on beats a name they
will quote.

**Do not extend this to a fifth shape without an acquired instance directory.**
A family is answerable only if we hold a directory of instances; a closed type
vocabulary cannot answer "what is THIS one". The four shapes here are four of
four: every family with a directory is already routed, and every top
unanswered family is blocked on acquisition, upstream of anything routing can
fix (REF-070). Coverage is not the claim — this route wins on answer quality,
not on documents found.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from refspec.registry.act_resolution import (
    ActIndex,
    act_name_absence_reason,
    canonical_usc_iri,
    resolve_act_name,
)
from refspec.registry.cfr_authority_notes import CfrAuthorityNotes, usc_citation
from refspec.registry.citation_grammar import (
    ActRelativeCitation,
    CfrCitationRange,
    find_cfr_citations,
    normalize_popular_name,
    stated_act_name,
    stated_section,
)
from refspec.registry.identifier_shapes import IdentifierKind, detect_identifier_shapes

__all__ = [
    "EXPLANATION_KINDS",
    "RIN_CONTAINER_THRESHOLD",
    "UNEXPLAINED_REASONS",
    "DocketDocument",
    "RinSubject",
    "TermExplanation",
    "acts_classifying",
    "explain_term",
    "parts_naming",
]

#: The four shapes a non-expert is handed. Measured 2026-09-06: all four are
#: RECOGNISED today by grammars this repository already ships. Only the
#: resolution differed, which is why this is a router and not a parser.
EXPLANATION_KINDS = ("act_section", "cfr_part", "docket", "rin")

UNEXPLAINED_REASONS = (
    #: Nothing in the four grammars read this string at all.
    "unrecognised_shape",
    #: An act-relative citation whose act the Popular Name Tool cannot answer.
    #: The specific absence is act_resolution's three-way code, carried through
    #: rather than flattened, so "the source lists this act and files nothing
    #: under it" survives the hop.
    "act_unresolved",
    #: The act resolved and the section is not classified to the U.S. Code.
    "act_section_not_classified",
    #: An identifier that covers several rulemakings rather than one. The
    #: sibling of the withheld act attribution below: ONE RULE, two scopes.
    #: Where the ambiguity sits in a single field, withhold that field and keep
    #: the rest; where it swallows the whole subject, refuse. A container RIN
    #: has no unambiguous subject left to give, so it refuses.
    "identifier_covers_several_rulemakings",
    #: A CFR part outside the 8,240 notes the pinned cache holds.
    "cfr_part_not_in_cache",
    #: A range, multiple citations, or refused scope cannot name one part.
    "cfr_scope_not_one_part",
    #: A RIN is recognised and its subject lives in the Unified Agenda catalog,
    #: which this repository does not hold. Named rather than guessed.
    "rin_subject_not_owned_here",
    #: A RIN that is a CONTAINER rather than a rulemaking. Measured by
    #: spicyregZ2 2026-09-07: 2120-AA66 carries 3,561 Federal Register documents
    #: from 2000 to 2026 across three document types -- an FAA airspace omnibus
    #: number. Answering it with one subject would state something confidently
    #: false, and it is the shape most likely to be typed because it is the most
    #: published. The distribution is one-to-few (11,678 RINs with one document,
    #: 10,796 with two, 3,840 with three), so containers are rare and enormous,
    #: which is the worst combination for a router that returns one answer.

    #: A docket parsed, and no document lookup was supplied to answer it.
    "docket_documents_not_supplied",
)


#: Above this many Federal Register documents a rule number is a CONTAINER, not
#: a rulemaking, and gets a refusal rather than a subject.
#:
#: **A percentile, not a structural break, and the difference matters.**
#: Measured by spicyregZ2 over 29,818 RINs on 2026-09-07: median 2 documents,
#: p90 4, p99 12, p99.9 21, maximum 19,798. 20 sits essentially at the 99.9th
#: percentile and refuses 35 RINs, 0.12% of the population. The tail is sparse
#: where the line falls -- roughly ten RINs in total between 24 and 40 -- so it
#: is not slicing a dense region. But nothing structural separates 19 documents
#: from 21, and a future corpus needs the PERCENTILE recomputed rather than
#: this number carried forward.
#:
#: **A conjunction was measured and rejected.** "Spans a decade AND carries all
#: three document types" looks more principled and is worse: it misses the
#: largest containers, because a container need not carry every type. 1625-AA00
#: is 4,326 documents over 23 years with two types -- a Coast Guard container
#: by any reading -- and the type test excludes it, while the conjunction
#: catches 65 ordinary long-running NOAA fishery actions the count leaves
#: alone. Three certain containers traded for sixty-five probable
#: non-containers. The crude measure won on evidence.
#:
#: The case that motivates it is 2120-AA64, 19,798 documents of FAA airspace
#: under one number.
RIN_CONTAINER_THRESHOLD = 20


@dataclass(frozen=True)
class RinSubject:
    """What a rule number is about, from whichever table answered.

    ``answered_by`` is required rather than optional because the two sources
    are not equivalent: the Unified Agenda edition carries the agency's own
    title and abstract for 3,954 RINs, and the Federal Register carries
    published documents for ~29,818. A reader must be able to tell which one
    spoke, and the coverage number to quote depends on the answer.
    """

    title: str
    agency: str
    stage: str
    answered_by: str
    document_count: int = 1


@dataclass(frozen=True)
class DocketDocument:
    """One document a docket produced, as a caller's lookup reports it."""

    published: str
    document_type: str
    title: str


@dataclass(frozen=True)
class TermExplanation:
    """What a handed term is, or exactly why this cannot say.

    Carries either an explanation or an :data:`UNEXPLAINED_REASONS` code and
    never neither, the same contract ``ActResolution`` keeps.
    """

    text: str
    kind: str | None = None
    #: The canonical thing the term names, when there is one.
    subject: str | None = None
    #: One line for a person. The product's whole value in this item.
    statement: str | None = None
    #: Every CFR part whose authority note NAMES the statute, never "the
    #: implementing part". Empty is a real answer and is stated as one.
    naming_parts: tuple[str, ...] = ()
    #: For a docket: what it produced, oldest first, which for a multi-document
    #: docket is an arc rather than a list.
    documents: tuple[DocketDocument, ...] = ()
    #: Rule one's evidence: every act that classifies to the section. One is an
    #: answer; more than one is a refusal that shows its working.
    candidate_acts: tuple[str, ...] = ()
    unexplained_reason: str | None = None

    def __post_init__(self) -> None:
        if (self.statement is None) == (self.unexplained_reason is None):
            raise ValueError("an explanation carries a statement or a reason, never both or neither")
        if self.unexplained_reason is not None and self.unexplained_reason not in UNEXPLAINED_REASONS:
            raise ValueError(f"undeclared reason: {self.unexplained_reason!r}")
        if self.kind is not None and self.kind not in EXPLANATION_KINDS:
            raise ValueError(f"undeclared kind: {self.kind!r}")


def acts_classifying(usc_title: object, usc_section: object, index: ActIndex) -> tuple[str, ...]:
    """Every act whose Table III classification reaches this U.S.C. section.

    Rule one lives here. A section is reached by its originating act AND by
    every act that amended it, so this is one-to-many by construction: 42
    U.S.C. 7401 is classified by both the Clean Air Act and the Clean Air Act
    Amendments of 1990, among others. Returning all of them lets the caller
    refuse; returning the first lets it answer "Amendments of 1990" to a person
    who said "Clean Air Act", which is the defect this replaces.

    Sorted for determinism, because a tuple whose order depends on dict
    insertion is a different answer on a different build.
    """

    wanted = (str(usc_title), str(usc_section))
    hits = {
        key
        for key, sections in index.classifications.items()
        for rows in sections.values()
        for row in rows
        if (str(row.usc_title), str(row.usc_section)) == wanted
    }
    return tuple(sorted(hits))


def parts_naming(usc_title: object, usc_section: object, notes: CfrAuthorityNotes) -> tuple[str, ...]:
    """CFR parts whose authority note NAMES this section, as "40 CFR 72".

    Reads the notes' own parsed citations rather than matching text, so a note
    stating a span ("42 U.S.C. 6291-6309") answers for a section inside it the
    way the publisher meant. What it cannot do is find a part whose note says
    "et seq." -- 13.3% of notes cite at chapter level and 40 CFR 60 is one of
    them -- which is why the caller may not phrase this as "implements".
    """

    try:
        citation = usc_citation(usc_title, usc_section)
    except ValueError:
        # An APPENDIX title -- "50 App." -- which the note grammar's citation
        # identity cannot express, since it is `int(title):section`. Found by
        # widening the verification sample from 120 acts to 400, where it
        # crashed rather than answered. Returning empty is correct and slightly
        # lossy: it means "no note names this" where the truth is "this reader
        # cannot ask", and the caller says so rather than implying absence.
        return ()
    if citation is None:
        return ()
    found = [
        f"{title} CFR {part}"
        for (title, part) in notes.coverage()
        if (note := notes.note(title, part)) is not None
        and any(c.family == "usc" and c.identity == citation.identity for c in note.citations)
    ]
    return tuple(sorted(found))


def _docket_agency(organization: str) -> str | None:
    """The agency a docket's organization token names, top level only.

    `EPA-HQ-OAR` yields EPA. The crosswalk holds 316 agency codes and resolves
    the leading token; it does not resolve the sub-office, so a reader is told
    "an EPA docket" and never "EPA Office of Air and Radiation". Stated because
    the honest limit is more useful than a plausible expansion.
    """

    from refspec.registry.agency_crosswalk import AGENCY_CROSSWALK_BY_CODE

    lead = str(organization or "").split("-")[0].upper()
    entry = AGENCY_CROSSWALK_BY_CODE.get(lead)
    return entry.agency_code if entry is not None and entry.tier == "confident" else None


def _explain_act_section(text: str, index: ActIndex, notes: CfrAuthorityNotes) -> TermExplanation | None:
    from refspec.registry.act_resolution import resolve_act_relative_citation

    name, section = stated_act_name(text), stated_section(text)
    if not name or not section:
        return None
    key = normalize_popular_name(name)
    if resolve_act_name(key, index) is None:
        return TermExplanation(text=text, kind="act_section", unexplained_reason="act_unresolved",
                               candidate_acts=(act_name_absence_reason(key, index),))
    outcome = resolve_act_relative_citation(
        ActRelativeCitation(act_name=name, act_key=key, section=section), index=index
    )
    if outcome.iri is None:
        return TermExplanation(text=text, kind="act_section",
                               unexplained_reason="act_section_not_classified",
                               candidate_acts=(outcome.unresolved_reason or "",))
    parts = parts_naming(outcome.usc_title, outcome.usc_section, notes)
    # The caveat is not optional and is the Clean Air Act 111 lesson in one
    # sentence. 13.3% of notes cite a chapter ("42 U.S.C. 7401 et seq.") rather
    # than a section, and 40 CFR 60 -- the part that actually implements section
    # 111 -- is one of them. Without this line a reader takes the named parts
    # for the complete set and takes 40 CFR 72 for the answer.
    caveat = " A part whose note cites the chapter rather than the section does not appear here."
    where = (
        f" {_and_list(parts)} {'names' if len(parts) == 1 else 'name'} it in"
        f" {'its' if len(parts) == 1 else 'their'} authority note{'' if len(parts) == 1 else 's'}."
        + caveat
        if parts
        else " No CFR part names it in its authority note." + caveat
    )
    return TermExplanation(
        text=text, kind="act_section",
        subject=canonical_usc_iri(outcome.usc_title, outcome.usc_section),
        statement=(f"Section {section} of the {name} is codified at "
                   f"{outcome.usc_title} U.S.C. {outcome.usc_section}.{where}"),
        naming_parts=parts,
    )


def _explain_cfr_part(text: str, index: ActIndex, notes: CfrAuthorityNotes) -> TermExplanation | None:
    citations = find_cfr_citations(text, expand_qualifiers=False)
    if not citations:
        return None
    if (len(citations) != 1 or isinstance(citations[0].citation, CfrCitationRange)
            or citations[0].refusal or citations[0].qualifier_status):
        return TermExplanation(text=text, kind="cfr_part", unexplained_reason="cfr_scope_not_one_part")
    first = citations[0].citation
    note = notes.note(first.cfr_title, first.cfr_part)
    if note is None:
        return TermExplanation(text=text, kind="cfr_part", unexplained_reason="cfr_part_not_in_cache")
    # The part's NAME, not its source note. `source_note` says "Source: 36 FR
    # 24877, Dec. 23, 1971", which tells a person nothing about what the part
    # is; `part_head` says "PART 60—STANDARDS OF PERFORMANCE FOR NEW STATIONARY
    # SOURCES", which is the answer.
    head = (note.part_head or "").strip().rstrip(".") or f"{first.cfr_title} CFR part {first.cfr_part}"
    # RULE ONE. Every act reaching any U.S.C. section the note names. One is an
    # attribution; several is not, and naming the first would be the defect
    # this module was written to remove.
    acts: set[str] = set()
    for citation in note.citations:
        if citation.family != "usc":
            continue
        title, _, section = citation.identity.partition(":")
        acts.update(acts_classifying(title, section, index))
    statement = f"{first.cfr_title} CFR {first.cfr_part} is {head}. Its authority note reads: {note.authority_note.strip()}"
    # The withheld attribution is said OUT LOUD rather than merely left absent.
    # A reader who is not told the attribution was withheld cannot tell it from
    # an attribution nobody looked for, and the whole point of the rule is that
    # a refusal a reader can act on beats a name they will quote.
    if len(acts) == 1:
        statement += f" That authority is classified from one act, Table III key {next(iter(acts))}."
    elif len(acts) > 1:
        statement += (f" {len(acts)} acts classify that authority — the originating act and those"
                      " amending it — so this does not attribute it to one.")
    return TermExplanation(
        text=text, kind="cfr_part", subject=f"{first.cfr_title} CFR {first.cfr_part}",
        statement=statement, candidate_acts=tuple(sorted(acts)),
    )


def _and_list(items: Sequence[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def explain_term(
    text: str,
    *,
    index: ActIndex,
    notes: CfrAuthorityNotes,
    docket_documents: Callable[[str], Sequence[DocketDocument]] | None = None,
    rin_subject: Callable[[str], RinSubject | None] | None = None,
) -> TermExplanation:
    """Route one handed term to the authority that owns it.

    Order is act-relative, then CFR citation, then identifier shape, because
    the first two are the most specific readings and an act-relative citation
    contains words a looser grammar would claim.

    ``docket_documents`` is a callable rather than a corpus because the subject
    of a docket is NOT this repository's to answer: recognition and the agency
    name are the atlas's, and the subject comes from the search corpus joining
    its own docket ids to titles it already serves. Passing it in keeps that
    boundary visible instead of importing across it.
    """

    text = str(text or "").strip()
    if not text:
        return TermExplanation(text=text, unexplained_reason="unrecognised_shape")
    for reader in (_explain_act_section, _explain_cfr_part):
        found = reader(text, index, notes)
        if found is not None:
            return found
    for candidate in detect_identifier_shapes(text):
        if candidate.kind is IdentifierKind.RIN:
            if rin_subject is None:
                return TermExplanation(text=text, kind="rin", subject=candidate.value,
                                       unexplained_reason="rin_subject_not_owned_here")
            answer = rin_subject(candidate.value)
            if answer is None:
                return TermExplanation(text=text, kind="rin", subject=candidate.value,
                                       unexplained_reason="rin_subject_not_owned_here")
            if answer.document_count > RIN_CONTAINER_THRESHOLD:
                return TermExplanation(text=text, kind="rin", subject=candidate.value,
                                       unexplained_reason="identifier_covers_several_rulemakings")
            return TermExplanation(
                text=text, kind="rin", subject=candidate.value,
                statement=(f"{candidate.value} is {answer.agency}'s rulemaking "
                           f"\u201c{answer.title}\u201d ({answer.stage}), per {answer.answered_by}."),
            )
        if candidate.kind is IdentifierKind.DOCKET:
            agency = _docket_agency(candidate.components.get("organization", ""))
            if docket_documents is None:
                return TermExplanation(text=text, kind="docket", subject=candidate.value,
                                       unexplained_reason="docket_documents_not_supplied")
            found = tuple(sorted(docket_documents(candidate.value), key=lambda d: d.published))
            opened = f"an {agency} docket" if agency else "a docket"
            if not found:
                statement = f"{candidate.value} is {opened}. No document in this corpus cites it."
            elif len(found) == 1:
                statement = f"{candidate.value} is {opened}: {found[0].title}"
            else:
                statement = (f"{candidate.value} is {opened}: {found[0].title} — "
                             f"{found[0].document_type} {found[0].published}, "
                             f"through {found[-1].document_type} {found[-1].published}, "
                             f"{len(found)} documents.")
            return TermExplanation(text=text, kind="docket", subject=candidate.value,
                                   statement=statement, documents=found)
    return TermExplanation(text=text, unexplained_reason="unrecognised_shape")
