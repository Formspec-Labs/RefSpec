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

**Do not extend this to an uncaptured family without an acquired directory.**
A family is answerable only if we hold a directory that answers it; a closed
type vocabulary cannot answer "what is THIS one" (REF-070). Four shapes
shipped initially (act section, CFR part, Regulations.gov docket, RIN). FERC
docket identifiers joined as the fifth once FERC's June 2025 Docket Prefix
List — 95 rows (77 active, 18 discontinued), digest-pinned and visually
attested in :mod:`refspec.registry.ferc_elibrary_codes` — was captured and
packaged for offline lookup; routing states only the authoritative prefix
code, status, eLibrary library, definition, and source provenance from that
directory, never facts about an individual proceeding beyond its prefix. The
remaining top unanswered families from REF-070 (EPA FRL, SEC release, FAA
airworthiness, SEC rule filing, OMB control) stay blocked on acquisition and
unrouted. Coverage is not the claim — this route wins on answer quality, not
on documents found.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

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
from refspec.registry.ferc_elibrary_codes import (
    FERC_DOCKET_PREFIX_PDF_EDITION,
    FERC_PUBLISHER,
    FercPublishedDocketPrefixCapture,
    FercPublishedDocketPrefixRow,
    load_packaged_ferc_docket_prefixes,
)
from refspec.registry.identifier_shapes import (
    _DASHES,
    _FERC_DOCKET_PREFIXES,
    IdentifierKind,
    detect_identifier_shapes,
)

__all__ = [
    "EXPLANATION_KINDS",
    "RIN_CONTAINER_THRESHOLD",
    "UNEXPLAINED_REASONS",
    "DocketDocument",
    "FercDocketPrefixExplanation",
    "RinSubject",
    "TermExplanation",
    "acts_classifying",
    "explain_term",
    "parts_naming",
]

#: The five shapes a non-expert is handed. The first four were already
#: recognised on 2026-09-06; ``ferc_docket`` joined once FERC's 95-row June
#: 2025 Docket Prefix List was captured, visually attested, and packaged for
#: offline lookup (REF-070).
EXPLANATION_KINDS = ("act_section", "cfr_part", "docket", "ferc_docket", "rin")

UNEXPLAINED_REASONS = (
    #: Nothing in the routed grammars read this string at all.
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
    #: A FERC-shaped docket whose prefix is absent from FERC's 95-row directory.
    "ferc_docket_prefix_unknown",
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
class FercDocketPrefixExplanation:
    """Authoritative FERC eLibrary docket-prefix record and source provenance.

    Carries only what FERC's pinned Docket Prefix List publishes: prefix code,
    active/discontinued status, eLibrary library code, exact publisher
    definition, and source provenance. Nothing is inferred about an individual
    proceeding beyond its prefix.
    """

    prefix: str
    status: Literal["active", "discontinued"]
    library: str
    definition: str
    publisher: str
    source_edition: str
    source_url: str
    source_sha256: str


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
    #: For a FERC docket: the authoritative prefix row and provenance from
    #: FERC's pinned June 2025 Docket Prefix List.
    ferc_docket_prefix: FercDocketPrefixExplanation | None = None
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


#: Active Table 1 prefixes that ``identifier_shapes`` already recognises in
#: two-segment form (``EL23-45``) without a three-digit sub-docket. Discontinued
#: prefixes (such as ``DA``/``ST``, which collide with FCC ``DA16-1282`` and
#: USDA ``ST08-01``) and ``PT`` (which also appears in the agency crosswalk)
#: require either a three-digit sub-docket (``-000``) or an explicit ``FERC``
#: qualifier, measured across 1,004,233 Federal Register documents.
_FERC_UNQUALIFIED_TWO_SEGMENT_PREFIXES = frozenset(_FERC_DOCKET_PREFIXES)
_FERC_COUNTER_WORD = r"(?:nos?(?:\.|\b)|numbers?\b|ids?\b)"
_FERC_TERM = re.compile(
    rf"^(?P<ferc>ferc\s+)?"
    rf"(?:(?P<label_noun>dockets?|projects?)\b\.?\s*(?:{_FERC_COUNTER_WORD}\s*)?[:#\-]*\s*)?"
    rf"(?P<body>\S+)$",
    re.IGNORECASE,
)
_FERC_STANDARD_BODY = re.compile(r"^(?P<prefix>[A-Z]{2})(?P<year>\d{2})-(?P<seq>\d+)(?:-(?P<sub>\d{3}))?$")
_FERC_HYDRO_BODY = re.compile(r"^P-(?P<seq>\d+)(?:-(?P<sub>\d{3}))?$")
_FERC_HB_BODY = re.compile(r"^HB\d{2}-\d+(?:-\d+-\d{2}|-\d{3})$")
_FERC_HB_EXPLICIT_BODY = re.compile(r"^HB(?:\d{2}-)?\d+(?:-\d+)*$")
_FERC_ID_BODY = re.compile(r"^ID-\d+(?:-\d{3})?$")
_FERC_HYPHEN_DISCONTINUED_BODY = re.compile(r"^(?P<prefix>[EGR]-)\d+(?:-\d{3})?$")
_FERC_EXPLICIT_HYPHEN_BODY = re.compile(r"^[A-Z]{1,3}-\d+(?:-\d{3})?$")


def _ferc_prefix_answer(
    text: str,
    subject: str,
    row: FercPublishedDocketPrefixRow,
    directory: FercPublishedDocketPrefixCapture,
) -> TermExplanation:
    info = FercDocketPrefixExplanation(
        prefix=row.prefix,
        status=row.status,
        library=row.library,
        definition=row.definition,
        publisher=FERC_PUBLISHER,
        source_edition=FERC_DOCKET_PREFIX_PDF_EDITION,
        source_url=directory.source_url,
        source_sha256=directory.source_sha256,
    )
    statement = (
        f"{subject} is a FERC docket with {row.status} prefix {row.prefix} "
        f"(\u201c{row.definition}\u201d, library {row.library}), "
        f"per the {FERC_PUBLISHER} Docket Prefix List ({FERC_DOCKET_PREFIX_PDF_EDITION})."
    )
    return TermExplanation(
        text=text,
        kind="ferc_docket",
        subject=subject,
        statement=statement,
        ferc_docket_prefix=info,
    )


def _explain_ferc_docket(
    text: str,
    directory: FercPublishedDocketPrefixCapture,
    *,
    require_explicit_ferc: bool,
) -> TermExplanation | None:
    """Route one whole FERC docket identifier against the pinned 95-row directory.

    Whole-string match only: running prose, multi-docket lists, bare prefixes
    (``"CP"``, ``"P"``), and non-FERC agency dockets (Regulations.gov, Federal
    Reserve ``Docket No. R-1835``, FCC ``DA16-1282``, FEMA ``Docket No. P-7915``,
    SEC ``Rel. No. IC-24979``, FAA ``AD 2000-01-01``) are never claimed.
    """

    folded = text.translate(_DASHES).strip()
    match = _FERC_TERM.fullmatch(folded)
    if match is None:
        return None
    explicit_ferc = match.group("ferc") is not None
    if require_explicit_ferc and not explicit_ferc:
        return None
    label_noun = (match.group("label_noun") or "").lower()
    is_project_label = label_noun.startswith("project")
    body = match.group("body").upper()
    by_prefix = directory.by_prefix()

    # Table 2 Hydropower Projects: P-<seq>-<sub> (220/220 FERC in the FR corpus;
    # two-part P-<seq> collides with FEMA/MARAD unless explicitly FERC-labeled).
    hydro = _FERC_HYDRO_BODY.fullmatch(body)
    if hydro is not None:
        if hydro.group("sub") is None and not explicit_ferc:
            return None
        row = by_prefix.get("P")
        if row is None:
            return TermExplanation(
                text=text, kind="ferc_docket", subject=body, unexplained_reason="ferc_docket_prefix_unknown"
            )
        return _ferc_prefix_answer(text, body, row, directory)

    # A "Project No." label only licenses P- hydropower projects, never general dockets.
    if is_project_label:
        return None

    # Table 2 Headwater Benefits: HB<yy>-<seq>-<n>-<nn> or HB<yy>-<seq>-<sub>.
    if _FERC_HB_BODY.fullmatch(body) or (explicit_ferc and _FERC_HB_EXPLICIT_BODY.fullmatch(body)):
        row = by_prefix.get("HB")
        if row is None:
            return TermExplanation(
                text=text, kind="ferc_docket", subject=body, unexplained_reason="ferc_docket_prefix_unknown"
            )
        return _ferc_prefix_answer(text, body, row, directory)

    # Table 2 Interlocking Directorates (ID-<seq>-<sub>) and Table 3 discontinued
    # hyphenated prefixes (E-, G-, R-) collide with EPA Idaho / Regulations.gov /
    # Federal Reserve (1,434 R-nnnn dockets) without an explicit FERC qualifier.
    if explicit_ferc:
        if _FERC_ID_BODY.fullmatch(body):
            row = by_prefix.get("ID")
            if row is None:
                return TermExplanation(
                    text=text, kind="ferc_docket", subject=body, unexplained_reason="ferc_docket_prefix_unknown"
                )
            return _ferc_prefix_answer(text, body, row, directory)
        hyph = _FERC_HYPHEN_DISCONTINUED_BODY.fullmatch(body)
        if hyph is not None:
            row = by_prefix.get(hyph.group("prefix"))
            if row is None:
                return TermExplanation(
                    text=text, kind="ferc_docket", subject=body, unexplained_reason="ferc_docket_prefix_unknown"
                )
            return _ferc_prefix_answer(text, body, row, directory)

    # Standard 2-letter + 2-digit year + sequence + optional 3-digit sub-docket:
    # covers all 73 Table 1 active prefixes, Table 2 IC, and all 15 two-letter
    # Table 3 discontinued prefixes.
    std = _FERC_STANDARD_BODY.fullmatch(body)
    if std is not None:
        prefix = std.group("prefix")
        has_sub = std.group("sub") is not None
        row = by_prefix.get(prefix)
        if row is not None and prefix != "ID":
            if has_sub or explicit_ferc or (row.status == "active" and prefix in _FERC_UNQUALIFIED_TWO_SEGMENT_PREFIXES):
                return _ferc_prefix_answer(text, body, row, directory)
            return None
        if has_sub or explicit_ferc:
            return TermExplanation(
                text=text, kind="ferc_docket", subject=body, unexplained_reason="ferc_docket_prefix_unknown"
            )
        return None

    if explicit_ferc and _FERC_EXPLICIT_HYPHEN_BODY.fullmatch(body):
        return TermExplanation(
            text=text, kind="ferc_docket", subject=body, unexplained_reason="ferc_docket_prefix_unknown"
        )
    return None


def _explain_act_section(
    text: str,
    index: ActIndex | None,
    notes: CfrAuthorityNotes | None,
) -> TermExplanation | None:
    from refspec.registry.act_resolution import resolve_act_relative_citation

    name, section = stated_act_name(text), stated_section(text)
    if not name or not section:
        return None
    if index is None or notes is None:
        raise ValueError("index and notes are required to explain an act-relative citation")
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


def _explain_cfr_part(
    text: str,
    index: ActIndex | None,
    notes: CfrAuthorityNotes | None,
) -> TermExplanation | None:
    citations = find_cfr_citations(text, expand_qualifiers=False)
    if not citations:
        return None
    if (len(citations) != 1 or isinstance(citations[0].citation, CfrCitationRange)
            or citations[0].refusal or citations[0].qualifier_status):
        return TermExplanation(text=text, kind="cfr_part", unexplained_reason="cfr_scope_not_one_part")
    if notes is None:
        raise ValueError("notes is required to explain a CFR part citation")
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
        if index is None:
            raise ValueError("index is required to attribute U.S.C. authorities on a CFR part")
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
    index: ActIndex | None = None,
    notes: CfrAuthorityNotes | None = None,
    docket_documents: Callable[[str], Sequence[DocketDocument]] | None = None,
    rin_subject: Callable[[str], RinSubject | None] | None = None,
    ferc_docket_prefixes: FercPublishedDocketPrefixCapture | None = None,
) -> TermExplanation:
    """Route one handed term to the authority that owns it.

    Order is act-relative, then CFR citation, then explicit ``FERC``-labeled
    docket, then ``identifier_shapes`` (RIN and Regulations.gov docket), then
    unqualified FERC docket. Act-relative and CFR citations are the most
    specific readings, explicit ``FERC`` labels prevent ``FERC Docket No.
    ID-...`` from falling into the Regulations.gov docket grammar, and running
    Regulations.gov before unqualified FERC keeps agency-hyphenated dockets
    (such as ``PT-2026-0001`` or ``EPA-HQ-OAR-2021-0317``) in their own family.

    ``docket_documents`` is a callable rather than a corpus because the subject
    of a Regulations.gov docket is NOT this repository's to answer: recognition
    and the agency name are the atlas's, and the subject comes from the search
    corpus joining its own docket ids to titles it already serves. Passing it in
    keeps that boundary visible instead of importing across it.

    ``ferc_docket_prefixes`` defaults to the packaged, digest-verified 95-row
    June 2025 FERC Docket Prefix List (:func:`load_packaged_ferc_docket_prefixes`),
    so FERC docket routing runs fully offline with zero network calls.
    """

    text = str(text or "").strip()
    if not text:
        return TermExplanation(text=text, unexplained_reason="unrecognised_shape")
    for reader in (_explain_act_section, _explain_cfr_part):
        found = reader(text, index, notes)
        if found is not None:
            return found
    directory = (
        ferc_docket_prefixes
        if ferc_docket_prefixes is not None
        else load_packaged_ferc_docket_prefixes()
    )
    explicit_ferc = _explain_ferc_docket(text, directory, require_explicit_ferc=True)
    if explicit_ferc is not None:
        return explicit_ferc
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
    ferc = _explain_ferc_docket(text, directory, require_explicit_ferc=False)
    if ferc is not None:
        return ferc
    return TermExplanation(text=text, unexplained_reason="unrecognised_shape")
