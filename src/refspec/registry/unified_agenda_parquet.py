"""Typed Parquet tables derived from the pinned Unified Agenda editions.

Pinning 981 MB of XML and a reader is not enough. Without a derived artifact
every consumer re-parses the same sixty files, and each one independently
rediscovers the same two things: that Spring and Fall 2004 are not well-formed
XML, and that the publisher's structured ``CFR_LIST`` needs a citation parse
before it joins to anything. That already happened once -- a downstream session
hit both and had to solve both again -- which is the argument for this module.

The repair happens here, once. The citation parse happens here, once. What a
consumer reads is four flat tables with typed columns.

    unified_agenda_actions           one row per (rin, publication_id)
    unified_agenda_cfr_references    one row per cited CFR reference
    unified_agenda_legal_authorities one row per cited legal authority
    unified_agenda_timetables        one row per timetable action, FR citation
                                     parsed into (fr_volume, fr_page)

**Nothing is filtered.** The publisher's damage is carried into the columns and
labelled, not dropped: ``cfr_title`` is whatever the reference actually says,
including the 115 references to Reserved title 35 and the 36 to title 0, and
``cfr_title_is_possible`` states the verdict without acting on it. A consumer
that wants only real citations filters on that column and can see exactly what
it discarded; a consumer studying publisher data quality reads the same rows
from the other side. Neither has to trust this module's opinion.

``reference_text`` and ``authority_text`` always carry the publisher's original
string beside the parsed fields, so a parse this module got wrong is visible
rather than lost.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from refspec.atlas.parquet_artifact import arrow_schema_sha256, file_sha256
from refspec.registry.act_resolution import (
    UNRESOLVED_REASONS,
    USC_SOURCE_CREDIT_ARTIFACT,
    ActIndex,
    SourceCreditIndex,
    resolve_act_name,
    resolve_act_relative_citation,
)
from refspec.registry.cfr_authority_notes import (
    CFR_AUTHORITY_NOTES_ARTIFACT,
    CfrAuthorityNotes,
    act_citation,
    cfr_citation,
    normalize_part,
    public_law_citation,
    usc_citation,
)

# Aliased on its own line: two modules here declare a closed vocabulary called
# VERDICTS -- the section oracle's exists/absent/unknown and the note reader's
# present/near-miss/absent -- and a bare second import would shadow the first.
from refspec.registry.cfr_authority_notes import VERDICTS as CFR_NOTE_VERDICTS
from refspec.registry.citation_grammar import (
    CONGRESS_CURRENT,
    EO_HIGHEST_KNOWN,
    FR_PAGE_HIGHEST_KNOWN,
    FR_VOLUME_HIGHEST_KNOWN,
    PL_FIRST_NUMBERED_CONGRESS,
    STAT_VOLUME_HIGHEST_KNOWN,
    USC_SPAN_ABBREVIATED,
    USC_SPAN_STATED,
    ActRelativeCitation,
    _normalize_dashes,
    find_act_relative_citations,
    names_citation_structure,
    normalize_popular_name,
    parse_agenda_timetable_citation,
    parse_authority_citation,
    parse_cfr_citations,
    parse_federal_register_citations,
    stated_act_name,
    stated_section,
    states_nothing,
    usc_section_ceilings,
    usc_section_magnitude_is_plausible,
    usc_section_pinpoint,
    usc_title_is_possible,
    usc_token_is_chapter_qualified,
)
from refspec.registry.unified_agenda_editions import (
    CONTINUATION_LABEL_FAMILIES,
    UNIFIED_AGENDA_EDITION_PINS,
    UnifiedAgendaEditionPin,
    legal_authority_continuations,
    parse_unified_agenda_edition,
)
from refspec.registry.usc_disposition_tables import (
    USC_DISPOSITION_TABLES_ARTIFACT,
    UscDispositionTables,
)

# The third closed vocabulary called VERDICTS, aliased for the same reason the
# second one is: the recodification tables answer exists-as-recodified /
# repealed-no-successor / stated-without-successor / not-in-table /
# no-table-for-title, which is neither of the other two.
from refspec.registry.usc_disposition_tables import VERDICTS as DISPOSITION_VERDICTS
from refspec.registry.usc_section_oracle import (
    CORRECTION_RULES,
    UNKNOWN_REASONS,
    USC_SECTION_ORACLE_ARTIFACT,
    VERDICTS,
    ActSectionClaim,
    SectionVerdict,
    UscSectionOracle,
    normalize_section,
)

__all__ = [
    "ACTIONS_SCHEMA",
    "ACT_ENACTMENT_YEAR_RULE",
    "ACT_RESOLUTION_EVIDENCE",
    "ACT_RESOLUTION_REASONS",
    "AUTHORITY_JOIN_REFUSALS",
    "AUTHORITY_JOIN_RULES",
    "CFR_REFERENCES_SCHEMA",
    "CORROBORATION_RULES",
    "LEGAL_AUTHORITIES_SCHEMA",
    "SCHEME_LABELS",
    "SCHEME_LABEL_RULE",
    "SCHEME_LABEL_WITNESSES",
    "SIBLING_ACT_RULE",
    "STATED_ACT_REFUSALS",
    "TIMETABLES_SCHEMA",
    "TITLE_CARRY_MAX_DISTANCE",
    "TITLE_CARRY_REFUSALS",
    "TITLE_CARRY_RULE",
    "UnifiedAgendaParquetReceipt",
    "build_unified_agenda_parquet",
    "main",
    "receipt_payload",
    "resolvable_act_names",
    "verify_unified_agenda_parquet",
]


def _banded_levenshtein(a: str, b: str, cutoff: int) -> int:
    """Edit distance with early exit; cutoff+1 means 'more than cutoff'."""

    if abs(len(a) - len(b)) > cutoff:
        return cutoff + 1
    previous = list(range(len(b) + 1))
    for i, _char in enumerate(a, 1):
        current = [i] + [0] * len(b)
        low, high = max(1, i - cutoff), min(len(b), i + cutoff)
        if low > 1:
            current[low - 1] = cutoff + 1
        for j in range(low, high + 1):
            current[j] = min(
                previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a[i - 1] != b[j - 1])
            )
        for j in range(high + 1, len(b) + 1):
            current[j] = cutoff + 1
        previous = current
        if min(previous) > cutoff:
            return cutoff + 1
    return previous[-1]


_YEAR_TOKEN = re.compile(r"\b(1[89]|20)\d{2}\b")


def _year_tokens(text: str) -> frozenset[str]:
    """Every four-digit year a string states."""

    return frozenset(match.group(0) for match in _YEAR_TOKEN.finditer(text))


class _ActNameMatcher:
    """Similarity matching for act names, licensed by measurement.

    Measured 2026-08-21 on the failed authority pool: cutoff 2 with a strict
    margin (second-best strictly worse) recovered 13 distinct typo'd names —
    "Affordable Housng", "Childrens's", "American Invents" — with 3
    ambiguous refusals and 0 false positives on a 300-text control. Names
    are sparse where numbers are dense, which is why this exists for acts
    and was refused for titles and public laws.

    The year guard is identity, not spelling: a single edit can turn
    "Act of 1990" into "act of 1996", and the year is how the Popular Name
    Tool tells acts apart (ALIAS_YEAR_RULE), so every year token in the
    query must appear verbatim in the match.
    """

    def __init__(self, names) -> None:
        self._by_length: dict[int, list[str]] = {}
        for name in names:
            self._by_length.setdefault(len(name), []).append(name)

    def match(self, query: str, *, cutoff: int = 2) -> str | None:
        hits: list[tuple[int, str]] = []
        for length in range(len(query) - cutoff, len(query) + cutoff + 1):
            for candidate in self._by_length.get(length, ()):
                distance = _banded_levenshtein(query, candidate, cutoff)
                if distance <= cutoff:
                    hits.append((distance, candidate))
        hits.sort()
        if not hits:
            return None
        if len(hits) > 1 and hits[1][0] == hits[0][0]:
            return None  # ambiguity refuses, same as everywhere else
        best = hits[0][1]
        # ``findall`` on this pattern would return the CAPTURED PREFIX ("19"),
        # not the year, so every year token is read through ``group(0)``.
        if not _year_tokens(query) <= _year_tokens(best):
            return None
        return best


ACTIONS_SCHEMA = pa.schema(
    [
        pa.field("rin", pa.string(), nullable=False),
        pa.field("publication_id", pa.string(), nullable=False),
        pa.field("cfr_reference_count", pa.int32(), nullable=False),
        pa.field("legal_authority_count", pa.int32(), nullable=False),
        #: The agency ticked "there are additional citations not listed" on
        #: the RID form, which the Agenda prints as a trailing ellipsis. The
        #: list is then complete as PUBLISHED and incomplete as a FACT, and a
        #: consumer joining on it needs to know which it is holding. The
        #: omitted citations were never entered anywhere, so nothing here can
        #: recover them; the flag is the whole of what the publisher states.
        pa.field("legal_authorities_declared_incomplete", pa.bool_(), nullable=False),
        pa.field("cfr_references_declared_incomplete", pa.bool_(), nullable=False),
    ]
)

CFR_REFERENCES_SCHEMA = pa.schema(
    [
        pa.field("rin", pa.string(), nullable=False),
        pa.field("publication_id", pa.string(), nullable=False),
        pa.field("ordinal", pa.int32(), nullable=False),
        pa.field("reference_text", pa.string(), nullable=False),
        pa.field("cfr_title", pa.int32(), nullable=True),
        pa.field("cfr_part", pa.string(), nullable=True),
        pa.field("cfr_title_is_possible", pa.bool_(), nullable=True),
        pa.field("cfr_section", pa.string(), nullable=True),
        pa.field("cfr_part_is_plausible", pa.bool_(), nullable=True),
        #: Whether (title, part) appears in the OFR's own 2025 subject index —
        #: an evidence-grade signal, not a verdict: a 1995 Panama Canal part
        #: is real and absent; a fused "60758" is fake and absent; 5 CFR 10001
        #: is real and present. NULL when there is no part to look up.
        pa.field("cfr_part_in_current_ofr_index", pa.bool_(), nullable=True),
        pa.field("citation_ordinal", pa.int32(), nullable=False),
    ]
)

TIMETABLES_SCHEMA = pa.schema(
    [
        pa.field("rin", pa.string(), nullable=False),
        pa.field("publication_id", pa.string(), nullable=False),
        pa.field("ordinal", pa.int32(), nullable=False),
        pa.field("action", pa.string(), nullable=False),
        # The publisher's MM/DD/YYYY verbatim: projected months carry a zero
        # day ("11/00/2026"), and normalizing that would invent a date.
        pa.field("date_text", pa.string(), nullable=False),
        pa.field("fr_citation_text", pa.string(), nullable=True),
        pa.field("citation_ordinal", pa.int32(), nullable=False),
        pa.field("fr_volume", pa.int32(), nullable=True),
        pa.field("fr_page", pa.int32(), nullable=True),
        #: "ok" when the citation text parsed on its own terms; "absent" when
        #: the row carries no citation (projected actions); "failed" when text
        #: is present and nothing could read it -- present rather than silent,
        #: per the house rule. Two readings rest on THIS COLUMN's semantics
        #: rather than on the text, and say so instead of claiming "ok":
        #: "relabeled" (a CFR citation whose own numbers refute that scheme)
        #: and "positional" (two plausible numbers, the FR label damaged or
        #: absent). A consumer wanting only text-grounded readings filters to
        #: "ok"; one wanting the join surface takes all three. "partial" is the
        #: fourth: the value states a VOLUME and no page, which is a different
        #: fact from a value nothing could read. "corroborated" is the fifth and
        #: the only one no reading of the TEXT produces: the text is damage, and
        #: the pinned Federal Register roster named the document it meant. The
        #: reading lives in the fr_corrected_* columns below, never here.
        pa.field("parse_status", pa.string(), nullable=False),
        #: Which non-Federal-Register grammar read this value, where one did.
        #: NULL on every row the FR grammar or the two column-semantic repairs
        #: above handled -- set exactly where ``parse_agenda_timetable_citation``
        #: spoke, so the schemes it names stay countable and a rule that stops
        #: firing breaks a pin. See that reader for what each scheme means.
        pa.field("fr_citation_scheme", pa.string(), nullable=True),
        #: "2025-21215" -- the value names a Federal Register DOCUMENT number
        #: where a page belongs. Volume-to-year is a bijection and that is all
        #: the text yields; which page the document opens on is the Register's
        #: to say, so the page column stays NULL rather than being invented.
        pa.field("fr_document_number", pa.string(), nullable=True),
        #: BESIDE the original, never instead of it: the Federal Register
        #: document a citation NOTHING could read turns out to have meant, from
        #: the pinned roster of publisher metadata (research/evidence/
        #: unified-agenda-fr-document-roster-2026-08-23). fr_citation_text keeps
        #: the filer's damage and fr_volume / fr_page stay NULL, because the
        #: grammar read nothing and these are what the ROSTER said. Non-NULL
        #: exactly where parse_status is "corroborated".
        pa.field("fr_corrected_document_number", pa.string(), nullable=True),
        pa.field("fr_corrected_volume", pa.int32(), nullable=True),
        pa.field("fr_corrected_page", pa.int32(), nullable=True),
        #: "<damage operator>-witnessed-by-<witnesses>": which named single-
        #: character edit produced the reading, and which witnesses closed it.
        #: See FR_CITATION_DAMAGE_OPERATORS and FR_CITATION_WITNESSES.
        pa.field("fr_correction_evidence", pa.string(), nullable=True),
    ]
)

LEGAL_AUTHORITIES_SCHEMA = pa.schema(
    [
        pa.field("rin", pa.string(), nullable=False),
        pa.field("publication_id", pa.string(), nullable=False),
        pa.field("ordinal", pa.int32(), nullable=False),
        #: Which citation within one publisher reference this row is. A
        #: reference naming several citations yields several rows sharing
        #: (rin, publication_id, ordinal); without this they cannot be told
        #: apart, and 42,395 rows could not be. The receipt's rowSemantics
        #: has promised this column all along.
        pa.field("citation_ordinal", pa.int32(), nullable=False),
        pa.field("authority_text", pa.string(), nullable=False),
        # Every row is typed: "other" marks a string nothing could read, with
        # parse_status "failed" — the grammar's nothing-vanishes rule carried
        # into the schema, replacing the earlier all-null convention.
        pa.field("authority_type", pa.string(), nullable=False),
        pa.field("parse_status", pa.string(), nullable=False),
        #: WHICH placeholder an "unstated" row carries, because the bucket is
        #: three different facts and only one of them is a placeholder.
        #: NULL on every row that is not "unstated"; see UNSTATED_KINDS.
        pa.field("unstated_kind", pa.string(), nullable=True),
        #: Candidate authorities for an "unstated" row's RECORD -- the
        #: (rin, publication_id) the placeholder belongs to -- from
        #: ``inv-placeholders``'s two-witness design: the publishable tier is
        #: the INTERSECTION of the record's own held CFR parts' authority
        #: notes and a sibling edition of the same rule that states more than
        #: this one does, "family:identity" joined by "; ", sorted. NULL where
        #: the intersection is empty (most placeholders) or the row is not
        #: "unstated". Never a citation this table treats as stated: nothing
        #: else reads this column, and a consumer that wants to use one of its
        #: candidates re-derives it through the ordinary reading for that
        #: family. See :func:`_write_placeholder_candidates`.
        pa.field("placeholder_candidate_authorities", pa.string(), nullable=True),
        #: WHY a candidate was withheld though a witness offered it, on the
        #: rows :func:`_write_placeholder_candidates` looked at and published
        #: nothing for. NULL beside a non-NULL
        #: ``placeholder_candidate_authorities`` and on every row neither
        #: witness reached at all -- "nothing to say" and "said no" are
        #: different facts.
        pa.field("placeholder_candidate_refusal", pa.string(), nullable=True),
        pa.field("usc_title", pa.int32(), nullable=True),
        pa.field("usc_section", pa.string(), nullable=True),
        pa.field("usc_section_end", pa.string(), nullable=True),
        #: How usc_section_end was arrived at: "stated" when the publisher
        #: wrote both ends, "abbreviated" when the grammar expanded a GPO
        #: span ("2671-80" is §§2671–2680). An expanded span is never typed
        #: ok — six of 66 expand into ranges that are mostly not law
        #: ("16 USC 4601-31" is 460l-31: 8 of 31 members real), and a
        #: consumer expanding ranges must be able to tell (review 2026-08-23,
        #: finding 7).
        pa.field("usc_section_span_rule", pa.string(), nullable=True),
        pa.field("usc_chapter", pa.string(), nullable=True),
        pa.field("usc_chapter_end", pa.string(), nullable=True),
        pa.field("usc_appendix", pa.bool_(), nullable=False),
        pa.field("cfr_title", pa.int32(), nullable=True),
        pa.field("cfr_part", pa.string(), nullable=True),
        #: The section under the part. The grammar has always read it and this
        #: table had no column, so 309 distinct values / 4,126 rows arrived one
        #: unit coarser than they were written and nothing said so: 22 distinct
        #: DOT delegation sections — 49 CFR 1.45, 1.46, 1.47 … — all landed as
        #: the single citation "49 CFR part 1". The CFR reference table beside
        #: this one has carried the column all along.
        pa.field("cfr_section", pa.string(), nullable=True),
        #: The CFR reader's own verdict on the part, carried rather than
        #: dropped. The sibling reference table has judged it since it existed,
        #: so the IDENTICAL string was flagged there and minted here with
        #: nothing said -- "42 CFR 412106" reads implausible in one pinned
        #: table and unjudged in the other. A digit-count verdict and nothing
        #: more: real parts reach five digits, so "49 CFR 30166" passes it and
        #: is still a U.S.C. section wearing a CFR label.
        pa.field("cfr_part_is_plausible", pa.bool_(), nullable=True),
        pa.field("reorganization_plan", pa.string(), nullable=True),
        pa.field("act_key", pa.string(), nullable=True),
        pa.field("act_section", pa.string(), nullable=True),
        #: WHICH OLRC source classified this act section, on the rows where
        #: ``usc_title``/``usc_section`` were filled by the act resolver rather
        #: than read out of the filer's own text. NULL everywhere else, so a
        #: consumer can tell a resolved act citation from a citation the filer
        #: wrote as U.S.C. -- the two are equally true and not equally direct.
        #: The vocabulary is ACT_RESOLUTION_EVIDENCE, one value per answering
        #: source ``refspec.registry.act_resolution`` names.
        pa.field("act_resolution_evidence", pa.string(), nullable=True),
        #: Why an act-relative row carries no section, from
        #: ACT_RESOLUTION_REASONS. Set on exactly the act-relative rows
        #: ``act_resolution_evidence`` is NULL on, and NULL on every other row:
        #: "the resolver refused, here is its reason" is a different fact from
        #: "nothing asked it". Before this column every one of these rows said
        #: parse_status "failed", which a consumer read as "could not
        #: resolve" when the parse had in fact succeeded and only the
        #: resolution had not been attempted.
        pa.field("act_resolution_reason", pa.string(), nullable=True),
        #: WHICH box supplied the act, on the rows the ``SIBLING_ACT_RULE``
        #: carried it into. The rule's name says the donor is one box away and
        #: not which of the two, and "which of the two" is the whole appeal a
        #: consumer has against a carry it does not believe -- so the ordinal
        #: is stated rather than left to be guessed from a name. NULL on every
        #: row the rule did not produce.
        pa.field("act_resolution_sibling_ordinal", pa.int32(), nullable=True),
        #: WHICH row of the pinned initialism roster spoke about this citation,
        #: and on whose word: "BBRA@0938 pinned-quote",
        #: "NDAA@0720/2021 candidate-index-match", "FSH@0596
        #: not-an-act:directive". The token and the agency identify the roster
        #: row; the tier says what kind of evidence stands behind it, and the
        #: quote itself lives in the digest-pinned
        #: ``research/evidence/initialism-roster-2026-08-24/roster.csv`` that
        #: every receipt names.
        #:
        #: Written on three KINDS of row, which is the point of having one
        #: column rather than three: the rows the roster RESOLVED (beside a
        #: ``corroboration_rule``), the rows it TYPED as naming no act at all
        #: (no corroboration_rule -- typing is the answer, and the row keeps
        #: its "failed" honesty), and the rows where its weakest tier offers a
        #: name the agency's own filings do not corroborate, which stay
        #: refused with the CANDIDATE recorded rather than spent. NULL on every
        #: row the roster had nothing to say about.
        pa.field("act_initialism_roster", pa.string(), nullable=True),
        #: Series-bound verdicts against web-verified facts (see the grammar's
        #: named constants). Evidence for a capture pinned through Fall 2025;
        #: NULL wherever there is nothing to judge.
        pa.field("usc_title_is_possible", pa.bool_(), nullable=True),
        #: The SECTION fence, beside the title one. ``usc_title_is_possible``
        #: answers for the title and says nothing about the section, so a
        #: citation to a section that was never printed arrived typed ``ok``
        #: and no count surfaced it -- about 7% of rows that produced a
        #: citation produced the wrong one, section non-existence the single
        #: dominant mechanism (research/evidence/silent-misreads-2026-08-22.md).
        #: The decider is refspec.registry.usc_section_oracle, read from the
        #: pinned OLRC oracle; NULL wherever there is no section to judge.
        pa.field("usc_section_verdict", pa.string(), nullable=True),
        #: Which coverage hole an "unknown" names, from the oracle's closed
        #: list. NULL on every other verdict: an unknown that cannot say why is
        #: a guess wearing a label.
        pa.field("usc_section_verdict_reason", pa.string(), nullable=True),
        #: Whether the edition doing the citing printed the section. FALSE
        #: beside ``exists`` is an ERA MISMATCH and never a misread -- the
        #: archives lag enactment, so the edition year narrows and never
        #: accuses. Its own fact, in its own column, for exactly that reason.
        pa.field("usc_section_attested_at_edition", pa.bool_(), nullable=True),
        #: The one reading that survived the oracle, in the Code's own spelling
        #: (``371(a)`` for a pinpoint, ``1395hh`` for a lettered section), and
        #: the rule that produced it. Published only where exactly one reading
        #: survives; the original stays in usc_section, as public_law keeps its
        #: original beside public_law_corrected.
        pa.field("usc_section_corrected", pa.string(), nullable=True),
        pa.field("usc_section_correction_evidence", pa.string(), nullable=True),
        #: The same correction, SPLIT into the two facts a consumer keys on.
        #: Derivation, from the one ``Correction`` the oracle returned and
        #: nothing else: ``usc_section_corrected_section`` is its ``section``
        #: -- the section IDENTITY the reading names -- and
        #: ``usc_section_corrected_pinpoint`` is its ``subsection`` in
        #: parentheses, or NULL where the reading names no pinpoint. The two
        #: concatenated ARE ``usc_section_corrected``, which is written from
        #: them here, so the split cannot drift from the Code's spelling.
        #: Both NULL wherever ``usc_section_corrected`` is.
        #:
        #: Why a consumer needs the split. ``usc_section_corrected`` carries
        #: the Code's own spelling, where ``371(a)`` is a pinpoint into §371
        #: and ``1395hh`` is a lettered section, so keying on that string moves
        #: the key off the section the citation names. Measured on the far
        #: side: of 91 keys that depart under a corrected-then-base reading,
        #: all four with any document exposure are CORRECT citations -- 15
        #: U.S.C. 18 (27 opinions + 1 presidential body), 12 U.S.C. 1715 (5),
        #: 47 U.S.C. 399 (3), 25 U.S.C. 161 (1) -- which lose every tag
        #: because a B8 proposal moved them to 18a / 1715b / 399b / 161a
        #: (research/evidence/ledger-2026-08-22/verification-notes.md,
        #: "Exposure figures decide the corrected-key shape"). Identity as the
        #: key and pinpoint as data is the reading that loses nothing; the B8
        #: proposal stays a named candidate and is never the identity a
        #: consumer keys on.
        pa.field("usc_section_corrected_section", pa.string(), nullable=True),
        pa.field("usc_section_corrected_pinpoint", pa.string(), nullable=True),
        #: What a positive-law recodification did with a former section the
        #: oracle above cannot see, from
        #: refspec.registry.usc_disposition_tables over the printed "TABLE
        #: SHOWING DISPOSITION OF FORMER SECTIONS OF TITLE 49" in the 1994
        #: volume. Written ONLY beside a usc_section_verdict of "unknown"
        #: whose reason is title_49_appendix_not_published -- the one coverage
        #: hole a pinned table speaks into -- and NULL on every other row,
        #: including every row the fence could answer for itself.
        #:
        #: **The verdict beside it does not move, and neither does its
        #: reason.** They answer a different question: whether the oracle can
        #: see the section (it cannot -- no OLRC archive year publishes a
        #: Title 49 Appendix) against what Pub. L. 103-272 § 6(b) deems a
        #: citation to it to mean. Five values, the table's own
        #: (usc_disposition_tables.VERDICTS): exists-as-recodified,
        #: repealed-no-successor, stated-without-successor, not-in-table,
        #: no-table-for-title. "not-in-table" is an ANSWER -- the pinned table
        #: was read and lists no such former section -- and only as wide as
        #: the table: a section repealed before 1994 was never in it.
        pa.field("usc_disposition_verdict", pa.string(), nullable=True),
        #: **EVERY** successor the table names, as "title:section", in print
        #: order, de-duplicated. A LIST because a former section is not a unit
        #: the recodification preserved: 1432 becomes four sections and
        #: 1432(a) alone becomes two, separated only by the printed prose
        #: ("(related to standards)" -> 44701 against "(related to issuing
        #: certificates)." -> 44702), which is not an address and is not in
        #: this column. **Candidates, never an identity** -- on 62 of the 146
        #: sections in this corpus the table names more than one, carrying
        #: 1,779 of the 2,548 rows, so a consumer that keyed a tag on "the"
        #: successor would be wrong on the majority. Non-NULL exactly where
        #: usc_disposition_verdict is exists-as-recodified.
        pa.field("usc_disposition_successors", pa.list_(pa.string()), nullable=True),
        #: WHICH former sections the verdict beside it speaks for. NULL where
        #: the citation names one section, and the members of a STATED span
        #: where it names a range: "49 USC 1421 to 1431" names eleven former
        #: sections and the table answers for each, so the successors above are
        #: the UNION over these and not one section's answer. Only the
        #: sections the 1994 volume itself prints are listed -- never a count
        #: from one endpoint to the other, which for "1 to 85" would claim 85
        #: former sections where the volume prints 84 (including lettered ones
        #: -- 1a, 5a, 15b -- a count could not reach at all).
        pa.field("usc_disposition_span_members", pa.list_(pa.string()), nullable=True),
        #: The subsection the CITATION stated, where the pinned table RESOLVED
        #: it: the answer beside it is the printed rows that speak for that
        #: subsection and no others. "49 USC 1651(b)(2)" answers 303 alone
        #: where bare "1651" answers 101 and 303, because the table prints
        #: "1651(b)(2) -> 303" as its own row. Resolved does not always mean
        #: NARROWER -- a printed row naming no subsection speaks for every
        #: subsection of its section, so "49 USC 486(c)" resolves to the same
        #: "481-496 -> Rep." the bare section gets. NULL where the citation
        #: states no pinpoint, and NULL where it states one the table cannot
        #: resolve: there the section's own rows come back whole, which is the
        #: module's rule that a subsection narrows and never accuses.
        pa.field("usc_disposition_pinpoint", pa.string(), nullable=True),
        #: Why no table was read for a row the fence sent here. NULL on every
        #: row that got an answer. The one refusal today is
        #: "chapter_qualifier_governs_the_token": the citation writes "ch" once
        #: over a list ("49 USC 106(g), ch 447 and 451"), the parse hands the
        #: second member on as a bare section, and the number is a CURRENT
        #: chapter of the title -- so reading it against the pre-1994 table
        #: would answer about a repealed 1930s block the filer never cited.
        pa.field("usc_disposition_refusal", pa.string(), nullable=True),
        #: WHICH pinned table answered, by its own name in
        #: usc_disposition_tables.RECODIFICATIONS ("title-49-1994", reading
        #: usc-1994-title49-disposition.parquet). One table is pinned today
        #: and six more recodifications are not, so a consumer must be able to
        #: tell a verdict from one table from a verdict from another rather
        #: than infer the source from the title. NULL exactly where
        #: usc_disposition_verdict is.
        pa.field("usc_disposition_table", pa.string(), nullable=True),
        #: WHICH non-U.S.C. numbering universe occupies the U.S.C. slot, on a
        #: row ``authority_type`` already reads as ``usc``. Additive only and
        #: never a verdict: this column NAMES a shape, it does not move
        #: ``usc_section_verdict``, and it says nothing about which verdict a
        #: named row carries. The two names differ on which verdicts they
        #: reach, because their evidence differs: "reg-suffix" rests on the
        #: rule's own CFR_LIST and is written whatever the section fence said,
        #: while "chapter-in-slot" is FENCED OFF ``exists`` in
        #: :func:`_write_usc_slot_reading` -- a number that is both a chapter
        #: and a real section is answering the section question correctly, and
        #: naming it here would suggest otherwise. NULL on every row neither
        #: shape reads, which is most
        #: of them. Placed after the recodification block rather than beside
        #: ``usc_section_verdict`` so it never breaks the fence's own
        #: contiguous five, the corrected-key split's two, or the
        #: recodification's six -- three blocks a reader already relies on
        #: meeting unbroken, in that order, right after
        #: ``usc_title_is_possible``. See :func:`_write_usc_slot_reading`.
        pa.field("usc_slot_reading", pa.string(), nullable=True),
        #: The CHEAP section fence beside the real one: the corpus judging
        #: itself, at the 99th percentile of the section stems a title attests
        #: times ten, computed over this build's own rows. A heuristic and
        #: named one -- the oracle above finds these and 18,000 rows more --
        #: kept because it costs one pass over an artifact a consumer already
        #: holds and needs no sealed directory to run. A LABEL, never a repair.
        pa.field("usc_section_magnitude_is_plausible", pa.bool_(), nullable=True),
        pa.field("eo_in_known_series", pa.bool_(), nullable=True),
        pa.field("pl_congress_in_series", pa.bool_(), nullable=True),
        #: A corroborated correction of an out-of-series Public Law: derived
        #: from named damage operators + the pinned congress.gov roster +
        #: any date the string itself states, exactly-one-survivor. The
        #: original stays in public_law; the evidence rule is named.
        pa.field("public_law_corrected", pa.string(), nullable=True),
        pa.field("pl_correction_evidence", pa.string(), nullable=True),
        pa.field("stat_volume_in_series", pa.bool_(), nullable=True),
        #: Whether the volume can carry the Public Law printed BESIDE it --
        #: "PL 92-500 76 Stat. 816" is 86 Stat., and the series bound alone
        #: calls 76 fine because 76 Stat. is a real volume. A verdict and never
        #: a correction: the relation cannot say which of the two numbers is
        #: the damaged one. NULL where the value states no adjacent Public Law,
        #: and NULL where the congress is out of series (pl_congress_in_series
        #: reports that one).
        pa.field("statute_volume_matches_public_law", pa.bool_(), nullable=True),
        pa.field("case_reporter", pa.string(), nullable=True),
        pa.field("case_volume", pa.int32(), nullable=True),
        pa.field("case_page", pa.int32(), nullable=True),
        # The six families from the failed-pool residue (research/
        # authority-families-2026-08-21.md), each web-verified.
        pa.field("presidential_doc_kind", pa.string(), nullable=True),
        pa.field("proclamation", pa.string(), nullable=True),
        pa.field("admin_order_kind", pa.string(), nullable=True),
        pa.field("admin_order_number", pa.string(), nullable=True),
        pa.field("treaty_series", pa.string(), nullable=True),
        pa.field("treaty_volume", pa.int32(), nullable=True),
        pa.field("treaty_number", pa.string(), nullable=True),
        pa.field("treaty_page", pa.int32(), nullable=True),
        pa.field("constitution_article", pa.string(), nullable=True),
        pa.field("constitution_section", pa.string(), nullable=True),
        pa.field("eo_compilation_start", pa.string(), nullable=True),
        pa.field("eo_compilation_page", pa.string(), nullable=True),
        pa.field("usc_note", pa.bool_(), nullable=False),
        pa.field("public_law", pa.string(), nullable=True),
        pa.field("executive_order", pa.string(), nullable=True),
        pa.field("statute_volume", pa.int32(), nullable=True),
        pa.field("statute_page", pa.int32(), nullable=True),
        #: An appendix-paginated Statutes page ("2763A-326"): the page's
        #: identity is the lettered compound, which the int32 column cannot
        #: state without truncating or minting — the int stays NULL and the
        #: identity lives here. Exactly one of the two page columns is set.
        pa.field("statute_page_text", pa.string(), nullable=True),
        pa.field("statute_volume_text", pa.string(), nullable=True),
        pa.field("stated_act_name", pa.string(), nullable=True),
        pa.field("stated_section", pa.string(), nullable=True),
        #: A Federal Register citation in the authority column — a document
        #: locator in the wrong field, typed like the CFR family.
        pa.field("fr_volume", pa.int32(), nullable=True),
        pa.field("fr_page", pa.int32(), nullable=True),
        #: The Register's own bound: volume 1 is 1936, so an edition of year
        #: Y cannot cite a volume above Y-1935, and no annual volume reaches
        #: page 100,000. Four series carried such a column and were loud;
        #: this one carried none (silent-misreads-2026-08-22, class A3).
        pa.field("fr_volume_in_series", pa.bool_(), nullable=True),
        pa.field("fr_page_in_series", pa.bool_(), nullable=True),
        #: Revised Statutes of 1874 — its own namespace, never a U.S.C. title.
        pa.field("revised_statute_section", pa.string(), nullable=True),
        #: D.C. Code title-section compound ("24-131").
        pa.field("dc_code_section", pa.string(), nullable=True),
        #: The scheme label a damaged token was read as, and the token it
        #: replaced: "USE -> U.S.C.", "113tat. -> Stat.". The filer's own
        #: spelling never leaves ``authority_text``; this column is what says
        #: which single edit the reading beside it rests on, so a consumer can
        #: re-derive the repair rather than take it on trust. Non-NULL exactly
        #: on the rows ``one-edit-on-a-scheme-label`` wrote.
        pa.field("authority_label_corrected", pa.string(), nullable=True),
        #: WHICH pinned oracle affirmed that repair, from
        #: :data:`SCHEME_LABEL_WITNESSES`. The operator alone is never the
        #: corroboration: "42 USE 1382" and "42 USO 299b-12" are the same one
        #: edit, and what separates a published row from a refused one is that
        #: a pinned oracle prints the place the repaired value names.
        pa.field("label_correction_evidence", pa.string(), nullable=True),
        #: Which corroboration rule produced this row's reading. Set on every
        #: ``parse_status == "corroborated"`` row and NULL everywhere else: a
        #: consumer that trusts one rule and not another can tell them apart,
        #: and the receipt counts rows per rule so a rule that stops firing
        #: breaks a pin instead of quietly vanishing.
        pa.field("corroboration_rule", pa.string(), nullable=True),
        #: The PUBLISHER's own answer key, beside the filer's text: does the
        #: authority note printed at the head of one of this rule's own CFR
        #: parts name what this row cites? present / near-miss / absent, from
        #: refspec.registry.cfr_authority_notes over the 8,240 notes fetched
        #: 2026-08-24 from the eCFR versioner API -- every authority note the
        #: register publishes, not the 287 the set-cover reached. The review of
        #: 2026-08-23 asked for this join in two of its nine classes and named
        #: it the highest-yield lever in both: the note settled 7 of 10
        #: "unreadable" rows and resolved or bounded 5 of 10 "absent" ones.
        #:
        #: A VERDICT AND NEVER A REPAIR, and each value is narrower than it
        #: sounds. "present" means the note names the citation, by identity,
        #: with a note range covering the sections between its endpoints.
        #: "near-miss" means the note names a citation of the same family one
        #: edit away (Damerau-Levenshtein 1 on the identity, title included),
        #: which the campaign adjudicated at 12.9% precision by text and 5.6%
        #: by rows -- a lead, not an accusation. "absent" means neither, IN THE
        #: NOTE AS FETCHED 2026-08-24, which is a live document a corpus
        #: starting in 1995 predates: 49 CFR 192's note enumerated
        #: 60102-60137 when RIN 2137-AE60 cited them in 2010 and reads "60101
        #: et. seq." today. NULL where the rule names no part the cache holds,
        #: and NULL on the families this join does not judge -- the four it
        #: does are usc, public_law, cfr and act_relative, and the receipt
        #: counts the rest by type.
        pa.field("authority_in_own_cfr_note", pa.string(), nullable=True),
        #: WHICH part's note gave the verdict, as a citation ("40 CFR 136").
        #: For present and near-miss it is the note that named the citation;
        #: for absent every held part failed and this is the first of them in
        #: citation order, so a consumer chasing an absence reads the rule's
        #: whole held set out of the CFR reference table beside this one.
        #: NULL exactly where authority_in_own_cfr_note is.
        pa.field("cfr_note_part", pa.string(), nullable=True),
        #: WHICH of the publisher's fields this citation was written in.
        #: "box" is the ``LEGAL_AUTHORITY_LIST`` element, which is where every
        #: row in this table came from until 2026-08-23. The other two are
        #: ``ADDITIONAL_INFO`` continuations, named by the label family the
        #: filer used (``AUTHORITY_SOURCES``): the Agenda's form gives a filer
        #: a fixed number of authority boxes, and 98 records over 25 RINs typed
        #: the rest of the list into the free-text field under a label. Those
        #: 1,325 citations were in the publisher's own bytes and in no column
        #: here, which is the one thing a "nothing vanishes" table may not do.
        #:
        #: ORDINAL, ON A CONTINUATION ROW, IS THE RECORD'S BOX COUNT PLUS K for
        #: the k-th continuation, counting from zero -- so it continues the box
        #: numbering and cannot collide with it, and (rin, publication_id,
        #: ordinal, citation_ordinal) stays unique by construction rather than
        #: by luck. A consumer that wants only what the structured field
        #: carried filters authority_source = 'box'.
        pa.field("authority_source", pa.string(), nullable=False),
        #: Whether this continuation row states a citation one of the SAME
        #: record's boxes already states. Filers continuing a list often repeat
        #: its head, and 91 of the 1,325 continuation rows do. They are emitted
        #: rather than dropped -- the filer wrote them, and a consumer counting
        #: distinct authorities must be able to tell a repeat from a new
        #: citation without re-deriving identity for itself.
        #:
        #: NULL on every ``authority_source = 'box'`` row: the question is not
        #: asked of a box, and False there would read as "this box is not a
        #: repeat", which this column has not checked. NULL also where the row
        #: states no identity at all (an ``other``/``failed`` row), because
        #: every such row would otherwise "equal" every other. Identity is
        #: :data:`_CITATION_IDENTITY_COLUMNS` -- what is cited, and nothing
        #: about the text it was read from.
        pa.field("restates_box_citation", pa.bool_(), nullable=True),
        #: THE RUN OF BOXES ONE CITATION LIST WAS CUT ACROSS. No fixed-width
        #: chop exists to undo -- the box lengths mode at 10-11 characters and
        #: decay to 212 -- so a join is justified box by box and recorded here
        #: rather than performed on the text: ``authority_text`` is never
        #: rewritten and ``ordinal`` is never renumbered, because a consumer
        #: keyed on either would silently move.
        #:
        #: The run's first box's ordinal and how many boxes it spans, written
        #: on every row of the run -- the donor's, the absorbed boxes', and the
        #: rows the joined string yielded. NULL everywhere else.
        pa.field("authority_box_run_start", pa.int32(), nullable=True),
        pa.field("authority_box_run_length", pa.int32(), nullable=True),
        #: WHICH shape made the run, from :data:`AUTHORITY_JOIN_RULES`: the
        #: signal of the run's first fragment box, or "list-continuation" for a
        #: run of bare comma lists that yields no citation at all. One value per
        #: run, on every row of it.
        pa.field("authority_join_rule", pa.string(), nullable=True),
        #: The EXACT string handed to the grammar, so a consumer can re-derive
        #: the reading rather than take it on trust. It is the run's boxes
        #: joined by ", " and nothing else -- no normalisation, no repair.
        pa.field("authority_join_text", pa.string(), nullable=True),
        #: WHICH earlier box supplied the U.S.C. title, on the rows the title
        #: carry wrote. The donor ordinal rather than a bare flag, for the
        #: reason ``act_resolution_sibling_ordinal`` carries one: the rule's
        #: own name cannot say which box spoke, and a consumer checking the
        #: carry has to be able to read the box it came from.
        pa.field("usc_title_carried_from_ordinal", pa.int32(), nullable=True),
        #: The exact string handed to the grammar once the title was carried --
        #: "46 U.S.C. 40503". Non-NULL exactly where
        #: usc_title_carried_from_ordinal is.
        pa.field("authority_carry_text", pa.string(), nullable=True),
        #: True on the rows of a box the join ABSORBED -- their text is read as
        #: part of the citation the joined rows carry. The rows are kept, never
        #: dropped: the filer wrote that box, and "42 U.S.C. 3535(d)" + "5318a"
        #: is two boxes whichever way it is read. NULL on every row the
        #: question is not asked of, which is every row outside a published
        #: Tier-A run, the donor's rows included.
        pa.field("superseded_by_join", pa.bool_(), nullable=True),
    ]
)

#: Which of the publisher's fields a row's citation was written in. "box" is
#: the structured ``LEGAL_AUTHORITY_LIST`` element; the other two are the
#: ``ADDITIONAL_INFO`` continuation label families, prefixed with the field
#: they were read from so no consumer has to know that "legal-authority-cont"
#: is a free-text label rather than a structured one.
AUTHORITY_SOURCE_BOX = "box"
AUTHORITY_SOURCES: tuple[str, ...] = (
    AUTHORITY_SOURCE_BOX,
    *(f"additional-info:{family}" for family in CONTINUATION_LABEL_FAMILIES),
)

#: What "the same citation" means for ``restates_box_citation``: the columns
#: that say WHAT is cited, and nothing else. Verdicts, corrections, statements
#: and the text itself are all about the STRING, and a continuation that
#: repeats a box in a different spelling is still a repeat. ``authority_type``
#: leads because two rows of different types are never the same citation.
_CITATION_IDENTITY_COLUMNS: tuple[str, ...] = (
    "authority_type",
    "usc_title", "usc_section", "usc_section_end", "usc_appendix", "usc_note",
    "usc_chapter", "usc_chapter_end",
    "cfr_title", "cfr_part", "cfr_section",
    "public_law", "executive_order",
    "statute_volume", "statute_page", "statute_page_text", "statute_volume_text",
    "reorganization_plan", "act_key", "act_section",
    "case_reporter", "case_volume", "case_page",
    "presidential_doc_kind", "proclamation", "admin_order_kind", "admin_order_number",
    "treaty_series", "treaty_volume", "treaty_number", "treaty_page",
    "constitution_article", "constitution_section",
    "eo_compilation_start", "eo_compilation_page",
    "fr_volume", "fr_page",
    "revised_statute_section", "dc_code_section",
)


#: The identity columns "does this row state an identity at all?" is asked of,
#: derived from the schema rather than restated: ``usc_appendix`` and
#: ``usc_note`` are non-nullable flags that read False on a row stating
#: nothing, so a test that included them would call every row a statement and
#: the question would be inert.
_STATED_IDENTITY_COLUMNS: tuple[str, ...] = tuple(
    column
    for column in _CITATION_IDENTITY_COLUMNS[1:]
    if LEGAL_AUTHORITIES_SCHEMA.field(column).nullable
)


def _citation_identity(row: Mapping[str, object]) -> tuple[object, ...]:
    """What a row cites, as the tuple two rows are the same citation by."""

    return tuple(row[column] for column in _CITATION_IDENTITY_COLUMNS)


def _states_a_citation(row: Mapping[str, object]) -> bool:
    """Whether the row names a place at all, rather than only a type."""

    return any(row[column] is not None for column in _STATED_IDENTITY_COLUMNS)


def _judge_restatements(authorities: list[dict[str, object]]) -> int:
    """Write ``restates_box_citation``, and the ONE place that writes it.

    After every row that will ever exist does, for the same reason
    :func:`_number_citations` runs there: corroboration explodes one row into
    several readings, the sibling carry and the act resolver fill identity
    columns, and a flag written at emission would describe a citation the
    published row no longer states. What a consumer reads is the PUBLISHED
    identity, so that is what is compared.

    A BOX row is left NULL: the question is not asked of a box, and False there
    would read as "this box is not a repeat", which nothing has checked. A row
    that states no identity at all -- ``other``/``failed``, every identity
    column NULL -- is left NULL too, because every such row would otherwise
    equal every other one and the flag would mean "unreadable", not "repeated".
    """

    boxes: dict[tuple[object, object], set[tuple[object, ...]]] = {}
    for row in authorities:
        if row["authority_source"] == AUTHORITY_SOURCE_BOX:
            boxes.setdefault((row["rin"], row["publication_id"]), set()).add(_citation_identity(row))
    restating = 0
    for row in authorities:
        row["restates_box_citation"] = None
        if row["authority_source"] == AUTHORITY_SOURCE_BOX:
            continue
        if not _states_a_citation(row):
            continue
        identity = _citation_identity(row)
        row["restates_box_citation"] = identity in boxes.get((row["rin"], row["publication_id"]), set())
        restating += bool(row["restates_box_citation"])
    return restating

#: What an "unstated" value actually says, as three closed kinds. The RID form
#: instructions ("Instructions for Reporting Regulatory Actions in the Unified
#: Agenda", RISC) and EO 12866 §4(b) are what separate them, and the separation
#: matters to a consumer:
#:
#: - "more-citations-follow" is NOT a placeholder. The instructions say: "If
#:   you choose to list only some of the applicable citations, you may check
#:   the box that indicates there are more citations. In this case, the printed
#:   Agenda will contain an ellipsis (...) at the end of the list." So the list
#:   is truthful and INCOMPLETE, and a consumer joining on legal authorities
#:   believes it has the whole list for rules whose agencies said otherwise.
#:   Verified as stored content rather than display truncation three ways: the
#:   eAgenda HTML carries it, the Federal Register print edition renders it as
#:   ". . ." (HHS agenda, FR doc 2025-18328), and it appears on lists of length
#:   2 through 58.
#: - "not-yet-determined" is a controlled value the form offers. 163
#:   occurrences in edition 202510 with zero casing variants, which typing does
#:   not produce; Title-case from 199810 onward, lowercase before.
#: - "none-off-form" is a PUBLISHER DEFECT, not an answer. The form offers a
#:   "None" box for CFR Citation and for Relevant Executive Order and NOT for
#:   Legal Authority, which gets only "Not Yet Determined" and "additional
#:   citations" — and EO 12866 §4(b) requires "the legal authority for the
#:   action" for every entry. Typing it as a placeholder is what hid it; naming
#:   it is what lets a consumer report it. Cross-join the timetable table to
#:   see the ones that carry a published document anyway (NHTSA RIN 2127-AL99
#:   carries "None" beside a published ANPRM at 83 FR 50872).
UNSTATED_KINDS: tuple[str, ...] = (
    "more-citations-follow",
    "not-yet-determined",
    "none-off-form",
)

#: The spellings behind each kind, measured over the built table 2026-08-22:
#: 6,876 / 5,461 / 130. Every ``UNSTATED_SENTINELS`` member the corpus actually
#: writes is here; a spelling this table does not know leaves ``unstated_kind``
#: NULL, which a test turns into a loud failure rather than a silent bucket.
_UNSTATED_KIND_BY_SPELLING: Mapping[str, str] = {
    "...": "more-citations-follow",
    ". . .": "more-citations-follow",
    "not yet determined": "not-yet-determined",
    "undetermined": "not-yet-determined",
    "not determined": "not-yet-determined",
    "nyd": "not-yet-determined",
    "tbd": "not-yet-determined",
    "to be determined": "not-yet-determined",
    "none": "none-off-form",
    "n/a": "none-off-form",
    "na": "none-off-form",
    "not applicable": "none-off-form",
    "null": "none-off-form",
    "nan": "none-off-form",
    "": "none-off-form",
}


#: The publisher's form glues a ZERO title and its scheme label in front of a
#: placeholder -- "00 USC 00" here, "00 CFR NYD" and "00 CFR None" in the CFR
#: column. That is the same non-answer wearing a label, and the grammar already
#: reads through it (``states_nothing``); reading through it the same way here
#: is what stops the prefix from costing the row its kind.
_UNSTATED_ZERO_TITLE = re.compile(r"^0+\s*(?:u\.?s\.?c\.?|c\.?f\.?r\.?|f\.?r\.?)\s*")
_UNSTATED_ALL_ZEROS = re.compile(r"^0+$")


def _unstated_kind(text: str) -> str | None:
    """Which of the three facts an "unstated" value states, or None."""

    value = _WRAPPING_QUOTES.sub("", str(text or "")).strip().casefold()
    kind = _UNSTATED_KIND_BY_SPELLING.get(value)
    if kind is not None:
        return kind
    remainder = _UNSTATED_ZERO_TITLE.sub("", value, count=1).strip()
    if remainder == value:
        return None
    # A zero where a citation belongs is the same off-form non-answer "None"
    # is: the form offered no box for it and the agency wrote one anyway.
    if _UNSTATED_ALL_ZEROS.match(remainder):
        return "none-off-form"
    return _UNSTATED_KIND_BY_SPELLING.get(remainder)


#: The evidence tiers ``research/evidence/initialism-roster-2026-08-24`` keeps
#: apart, and the only ones this module knows how to spend. Three of them are a
#: publisher's or the filer's own word and RESOLVE a row; the fourth is a name
#: that merely resolves in the pinned act index, which is the operator wave 5
#: measured inventing a wrong survivor 15.25% of the time even date-bounded, so
#: it resolves only behind the agency fence and otherwise leaves a candidate.
#: The tiers not named here -- ``not-an-act:*``, ``ambiguous``, ``belief-only``
#: -- never resolve anything, and two of them never even type.
INITIALISM_ROSTER_RESOLVING_TIERS: tuple[str, ...] = (
    "pinned-quote",
    "reverse-pl-verified",
    "self-glossing",
)
INITIALISM_ROSTER_FENCED_TIER = "candidate-index-match"

#: The corroboration rules, each a named damage operator over a pinned oracle
#: with exactly-one-survivor. Declared here so the receipt, the tests and a
#: consumer read the same closed set. This is NOT the vocabulary of
#: ``pl_correction_evidence``, which also labels corrections carried on rows
#: the grammar DID read ("date-matched", "unique-roster-existence"): those
#: rows keep their own parse_status and so carry no corroboration rule.
CORROBORATION_RULES: tuple[str, ...] = (
    #: The OLRC index holds the name a value states; what failed was the
    #: prose around it, not the name.
    "index-holds-the-stated-name",
    "agency-roster-initialism",
    "agency-gloss-narrowed-initialism",
    "agency-roster-word-prefix",
    "rin-history-section-list",
    "rin-history-titleless-usc",
    "rin-history-labelless-pair",
    "rin-history-volumeless-stat",
    "roster-existent-public-law-pair",
    #: The publisher's own list order: one citation cut at commas across
    #: several <LEGAL_AUTHORITY> slots, put back together.
    "list-run-bounding-public-law",
    "unique-dash-insertion",
    "space-separator-roster-existence",
    "to-separator-roster-existence",
    #: The pair with the LABEL between its halves: "94 Pub. L. 588".
    "reordered-public-law-roster-existence",
    #: A box holding nothing but a section number, taking its act from the box
    #: beside it. The publisher's own list order again -- the same defect
    #: ``list-run-bounding-public-law`` reads for Public Laws, read here for
    #: acts. Fenced four ways, and named ``SIBLING_ACT_RULE``.
    "sibling-act-at-ordinal±1",
    #: A box holding nothing but section numbers, taking the U.S.C. title from
    #: the nearest earlier box that states exactly one. Named
    #: ``TITLE_CARRY_RULE``.
    "sibling-usc-title-within-six-boxes",
    #: The same box, taking the ACT from the last earlier box that named one --
    #: which may be four boxes back, and may have named it with three letters
    #: nothing but the RIN's own roster can read. Named ``ACT_CARRY_RULE``.
    "sibling-act-from-an-earlier-box",
    #: A scheme LABEL one edit from its spelling -- "16 USE 715(i)",
    #: "113tat. 1754". Fenced six ways and named ``SCHEME_LABEL_RULE``.
    "one-edit-on-a-scheme-label",
    #: A SECOND authority the filer wrote behind a slash, which the whole-value
    #: fallback could never reach because the first half had already read. One
    #: name per reader that can BIND the piece, for the reason the pinned
    #: roster's tiers are spelled out below: what a second authority stands on
    #: -- the same RIN's own resolved acts, its agency's, a pinned file, or the
    #: OLRC index answering a spelled name -- is the first thing a consumer
    #: filtering on trust needs to see. Named ``SLASH_RULES``.
    *(f"second-authority-behind-a-slash:{bound}"
      for bound in (
          "agency-roster-initialism",
          "agency-gloss-narrowed-initialism",
          "agency-roster-word-prefix",
          "index-holds-the-stated-name",
          "index-holds-a-bare-name-and-section",
          *(f"pinned-roster-initialism:{tier}"
            for tier in (*INITIALISM_ROSTER_RESOLVING_TIERS, INITIALISM_ROSTER_FENCED_TIER)),
      )),
    #: An initialism NO RECORD IN THIS CORPUS DEFINES, named by the pinned
    #: roster instead. One rule name per evidence tier, because what these
    #: rows stand on differs by an order of magnitude between the first and
    #: the last and a consumer filtering on trust needs to see which.
    *(f"pinned-roster-initialism:{tier}"
      for tier in (*INITIALISM_ROSTER_RESOLVING_TIERS, INITIALISM_ROSTER_FENCED_TIER)),
)

#: The rule name spelled once, because the applicator, the fence and the
#: receipt all have to mean the same string.
SIBLING_ACT_RULE = "sibling-act-at-ordinal±1"
SCHEME_LABEL_RULE = "one-edit-on-a-scheme-label"
#: The second authority a slash hid. The published rule name is this stem, a
#: colon, and the name of the reader that BOUND the piece -- so the row says
#: both what found it and what it rests on.
SLASH_RULE = "second-authority-behind-a-slash"

#: The shapes that make a box a FRAGMENT of its neighbour's citation, and the
#: closed vocabulary ``authority_join_rule`` is written from. Left-hand signals
#: describe a box the NEXT one completes; right-hand signals a box the PREVIOUS
#: one governs. "list-continuation" is the other tier: a run of bare comma
#: lists that continues one list and yields no citation at all.
#:
#: R2 -- "opens lowercase and names no scheme" -- is NOT here, and its absence
#: is measured rather than stylistic: it fires on 165 runs of this corpus and
#: every one of them is English prose cut by a field boundary or two unrelated
#: authorities side by side. One run reached a citation no other signal
#: reached. A predicate that describes prose is not a citation fence.
AUTHORITY_JOIN_RULES: tuple[str, ...] = (
    "fragment-left:L1-dangling-label-or-connective",
    "fragment-left:L2-open-punctuation",
    "fragment-left:L3-unbalanced-paren",
    "fragment-left:L4-whole-box-is-a-bare-section",
    "fragment-right:R1-opens-with-close-or-comma",
    "fragment-right:R3-opens-with-connective",
    "fragment-right:R4-whole-box-is-a-bare-section",
    "fragment-right:R5-opens-with-digit-no-scheme",
    "list-continuation",
)

#: Why a proposed run published nothing. Counted by the fence that spoke, for
#: the reason every refusal in this module is: a rule is only as trustworthy as
#: what it declines to answer.
AUTHORITY_JOIN_REFUSALS: tuple[str, ...] = (
    #: The joined string reads a citation the donor box already read -- and
    #: nothing else. Nothing to publish, so nothing is claimed.
    "the-join-adds-no-citation",
    #: The join would weld a STATED SECTION onto a citation that carries its
    #: own: "42 USC 1302" + "sec 1861" is a U.S.C. section and a Social
    #: Security Act one, not one citation, and "MIPPA sec 153 (b" +
    #: "PL 111-148 sec 3401(h)" is two Public Law sections from two acts. Only
    #: a Public Law or a Statutes page takes a stated section, and only from a
    #: box that is nothing but that section.
    "a-statement-welded-to-a-citation-that-has-its-own-section",
    #: The oracle does not print a section the joined reading mints at the
    #: EDITION's year. "12 U.S.C. 4568" + "1437a ... 1437z-7" would mint seven
    #: title-12 rows for title-42 sections.
    "the-oracle-does-not-print-a-section-the-join-mints",
    #: The joined reading no longer carries something the donor box read alone.
    #: A join may only ADD.
    "the-join-loses-what-the-donor-already-read",
)

#: The scheme labels a damaged token may be read as, in the spellings this
#: corpus writes them. A test probes every one of them through the grammar, so
#: a label the grammar stops accepting breaks a pin rather than silently
#: becoming a repair target nothing can read.
SCHEME_LABELS: tuple[str, ...] = (
    "Stat.", "U.S.C.", "USC", "Pub. L.", "PL", "sec.", "CFR", "FR",
)

#: WHICH pinned oracle affirmed a scheme-label repair. A closed vocabulary for
#: the same reason ``pl_correction_evidence`` has one: a consumer that trusts
#: the section oracle and not the Register's series bound can tell them apart,
#: and the receipt counts rows per witness.
SCHEME_LABEL_WITNESSES: tuple[str, ...] = (
    "section-oracle",
    "section-oracle-on-the-stated-tail",
    "statutes-volume-series",
    "public-law-roster",
    "federal-register-volume-series",
)

#: The named refusals, so "the rule found nothing here" and "the rule found
#: something and would not publish it" never read the same in the receipt.
SCHEME_LABEL_REFUSALS: tuple[str, ...] = (
    #: F4. Another repair of the same token types the value IN FULL, using
    #: prose the label reading leaves unexplained: "Reorganization Plan No. 4
    #: or 1978" is a reorganization plan under 'or' -> 'of', and never
    #: "4 FR 1978" under 'or' -> 'FR', however real Register volume 4 is.
    "another-repair-types-the-value-in-full",
    #: F5, first half. A residue run IS a scheme label the grammar already
    #: accepts: "29 USC UC 794" already says USC, so reading "UC" as a second
    #: one invents a label rather than repairing the damaged one. Right answer
    #: by the wrong token is still a guess.
    "the-label-already-stands-in-the-residue",
    #: F5, second half. A residue run is neither spelled out of the label's own
    #: letters (the filer split it: "Pu." + "Bl.") nor citation structure the
    #: grammar names ("et seq.", "note", "to").
    "residue-the-operator-does-not-explain",
    #: The row states something else. Every other column NULL is what makes
    #: this rule additive by construction: it fills, and never overwrites.
    "the-row-already-states-something",
    #: No pinned oracle affirms exactly one reading -- none did, or more than
    #: one did.
    "no-single-corroborated-reading",
)

#: One edit, and the edit is a substitution, an insertion or a deletion.
#: TRANSPOSITION IS OUTSIDE THE FENCE, unlike the Register-label rule's
#: ``FR_LABEL_MAX_EDITS``, and the difference is measured rather than
#: stylistic: over this corpus a transposed reading is never the repair that
#: explains the damage ("49 SUC 45102" and "26 USCU.S.C. 5061" are the family),
#: and admitting it buys rows whose operator names nothing.
SCHEME_LABEL_MAX_EDITS = 1

#: Two letters, because a single letter is not damage -- "f" and "p" sit beside
#: numbers all over this corpus as ordinary pinpoints.
SCHEME_LABEL_MIN_LETTERS = 2


#: ``ActResolution.answered_by`` in the artifact's own spelling. The resolver
#: names its sources for a reader holding its module; this column is read by
#: one who is not, so "table3" becomes what a Table III row IS -- a
#: classification -- and the source credits keep their name.
_ACT_RESOLUTION_EVIDENCE_BY_SOURCE: Mapping[str, str] = {
    "table3": "table3-classification",
    "source_credits": "source-credit",
    "both": "both-sources",
}

#: The closed vocabulary of ``act_resolution_evidence``.
ACT_RESOLUTION_EVIDENCE: tuple[str, ...] = tuple(_ACT_RESOLUTION_EVIDENCE_BY_SOURCE.values())

#: Every reason an act-relative row publishes no section. The first block is
#: :data:`refspec.registry.act_resolution.UNRESOLVED_REASONS` verbatim -- the
#: resolver's own codes, passed through and never paraphrased -- and the rest
#: are this builder's, each with a measured population and a specimen:
#:
#: - ``no_section_stated``: the citation names an act and no section. 1,999
#:   rows; "Nuclear Waste Policy Act of 1982" is the shape. It is the commonest
#:   reason and it is not a resolution failure at all.
#: - ``act_key_refused_by_edition_calendar``: the grammar proposed an act key
#:   whose year is later than the edition citing it, so ``act_key`` is NULL and
#:   there is nothing to look up. 3 rows, all "The Emergency Supplemental
#:   Appropriations Act for Defense" in 2006-2007 editions; the same refusal
#:   ``actKeyAnachronismRefusals`` counts, said per row.
#: - ``act_section_inside_a_range_key`` narrows ``act_section_not_classified``:
#:   Table III files the section under a RANGE key that contains it, so the
#:   classification exists and the section-keyed lookup cannot reach it (review
#:   B, H5). 37 rows / 9 (act, section) pairs; "Section 4(b) of the Steel Trade
#:   Liberalization Program Implementation Act" is filed under key "2-6".
#: - ``resolves_to_note`` narrows ``usc_section_not_expressible``: the target is
#:   a statutory NOTE ("47 U.S.C. 303 nt"), a real and citable thing that is
#:   not a section, which is why rkaf has no production for it (review B, H6).
#:   All 126 of the corpus's inexpressible targets are notes; anything else
#:   keeps the resolver's wider code, which is how a new shape stays visible.
#: - ``revised_statutes_only`` narrows ``no_section_stated``: every one of the
#:   act's Table III rows terminates in the Revised Statutes ("R.S. Sec 2319")
#:   and states no U.S.C. title at all, so no section of it can resolve without
#:   an R.S. -> U.S.C. hop this tree does not have (review B, H7). 4 rows, all
#:   "General Mining Act of 1872, as amended".
ACT_RESOLUTION_REASONS: tuple[str, ...] = (
    *UNRESOLVED_REASONS,
    "no_section_stated",
    "act_key_refused_by_edition_calendar",
    "act_section_inside_a_range_key",
    "resolves_to_note",
    "revised_statutes_only",
)

#: The reasons that say THE ACT is unknown, which is the only thing that leaves
#: an act-relative row's parse_status "failed". Every other reason keeps a right
#: reading of the act and its section, so the row is "partial".
_ACT_UNKNOWN_REASONS = frozenset({"act_not_in_index", "act_key_refused_by_edition_calendar"})


@dataclass(frozen=True)
class UnifiedAgendaParquetReceipt:
    """What was built, from which pinned bytes."""

    editions: int
    actions: int
    cfr_references: int
    legal_authorities: int
    timetable_rows: int
    source_sha256_by_edition: dict[str, str]
    outputs: dict[str, str]
    schema_digests: dict[str, str]
    contract: dict[str, object]
    producer: dict[str, object]


def _edition_payload(pin: UnifiedAgendaEditionPin, source_root: Path) -> bytes:
    return (source_root / f"REGINFO_RIN_DATA_{pin.file_stem}.xml").read_bytes()


#: The pinned oracles this builder consults, all located RELATIVE TO THIS
#: FILE. That is worth stating plainly because it has a sharp edge: a copy of
#: this module run from anywhere else resolves ``parents[3]`` somewhere else,
#: finds none of them, and builds a QUIETLY DIFFERENT artifact -- no Public Law
#: corrections at all, every ``cfr_part_in_current_ofr_index`` NULL and every
#: section verdict NULL. Every loader returns None rather than raising,
#: which is right for a caller that has no oracle, and wrong for one that
#: thinks it has. The test that the files exist is what turns a silent absence
#: into a loud one, and ``main`` refuses to build without them.
_PL_ROSTER_CSV = (
    Path(__file__).resolve().parents[3]
    / "output/registry-real-data-sources/public-law-roster/public-law-roster.csv"
)
#: The U.S.C. section oracle's sealed directory: six tables, each digest-pinned
#: inside :mod:`refspec.registry.usc_section_oracle` and re-checked on every
#: load, so a swapped directory refuses there rather than answering differently
#: here.
_USC_SECTION_ORACLE_DIR = Path(__file__).resolve().parents[3] / USC_SECTION_ORACLE_ARTIFACT
#: The pinned recodification tables the section oracle consults for the ONE
#: coverage hole it cannot answer from its own sources. Digest-pinned inside
#: :mod:`refspec.registry.usc_disposition_tables` and re-checked on every load,
#: so a swapped directory refuses there rather than answering differently here.
_USC_DISPOSITION_TABLES_DIR = Path(__file__).resolve().parents[3] / USC_DISPOSITION_TABLES_ARTIFACT
#: The Code's own source credits -- the second, independent act-section source
#: :func:`refspec.registry.act_resolution.resolve_act_relative_citation`
#: consults beside Table III. Digest-pinned in that module, so a swapped
#: directory refuses there rather than answering differently here.
_USC_SOURCE_CREDIT_DIR = Path(__file__).resolve().parents[3] / USC_SOURCE_CREDIT_ARTIFACT
#: The publisher's own authority notes for 8,240 CFR parts, digest-pinned in
#: :mod:`refspec.registry.cfr_authority_notes` and re-checked on every load.
#: The fourth oracle found relative to this file, and it has the same sharp
#: edge as the other three: absent, the note verdict is NULL on every row and
#: nothing says so, which is what ``main``'s refusal is for.
_CFR_AUTHORITY_NOTES_JSONL = Path(__file__).resolve().parents[3] / CFR_AUTHORITY_NOTES_ARTIFACT
#: What a filer's shorthand names, and on whose word -- 297 rows over 119
#: tokens, each keyed to the agency whose filings the evidence came from and
#: each carrying the TIER of that evidence. The fifth file oracle, with the
#: same sharp edge as the other four: absent, 610 rows stay unread and nothing
#: says so, which is what ``main``'s refusal is for. Its README carries the
#: measurement that forbids using its weakest tier unfenced.
_INITIALISM_ROSTER_CSV = (
    Path(__file__).resolve().parents[3]
    / "research/evidence/initialism-roster-2026-08-24/roster.csv"
)
#: The roster's columns, in the file's own order. Named here because
#: :func:`_initialism_roster` checks the width of every row against it rather
#: than letting ``csv.DictReader`` absorb the difference; see that function.
_INITIALISM_ROSTER_FIELDS: tuple[str, ...] = (
    "token", "agency_prefix", "year_key", "status", "act_name", "table3_key",
    "evidence_path", "evidence_sha256", "evidence_quote", "rows_observed", "notes",
)


def _usc_disposition_tables() -> UscDispositionTables | None:
    """The pinned recodification tables, or None where this tree lacks them."""

    if not _USC_DISPOSITION_TABLES_DIR.is_dir():
        return None
    return UscDispositionTables.from_directory(_USC_DISPOSITION_TABLES_DIR)


def _usc_section_oracle() -> UscSectionOracle | None:
    """The pinned section oracle, or None where this tree does not carry it.

    The recodification tables ride ON the oracle rather than beside it, because
    what they answer is one of the oracle's own coverage holes and the gate is
    the oracle's verdict: a disposition published without that gate would be a
    statement about a live section of the current title.
    """

    if not _USC_SECTION_ORACLE_DIR.is_dir():
        return None
    return UscSectionOracle.from_directory(_USC_SECTION_ORACLE_DIR, dispositions=_usc_disposition_tables())


def _cfr_authority_notes() -> CfrAuthorityNotes | None:
    """The pinned CFR authority notes, or None where this tree does not carry them."""

    return CfrAuthorityNotes.from_file(_CFR_AUTHORITY_NOTES_JSONL) if _CFR_AUTHORITY_NOTES_JSONL.is_file() else None


def _usc_source_credits() -> SourceCreditIndex | None:
    """The pinned source-credit index, or None where this tree does not carry it."""

    return (
        SourceCreditIndex.from_artifact(_USC_SOURCE_CREDIT_DIR)
        if _USC_SOURCE_CREDIT_DIR.is_dir()
        else None
    )


def _pl_roster() -> tuple[dict[tuple[int, int], str], dict[tuple[int, int], int | None]] | None:
    """(congress, law) -> approval date MM/DD/YYYY, and -> Stat volume."""

    import csv

    if not _PL_ROSTER_CSV.is_file():
        return None
    dates: dict[tuple[int, int], str] = {}
    volumes: dict[tuple[int, int], int | None] = {}
    with _PL_ROSTER_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (int(row["congress"]), int(row["law"]))
            dates[key] = row["date"]
            volumes[key] = int(row["stat_volume"]) if row["stat_volume"] else None
    return dates, volumes


#: The code and the oracles that wrote an artifact, as content digests, so a
#: receipt resolves to code by hashing blobs rather than by guessing at
#: commits. Twenty commits landed between two builds on 2026-08-22 and a
#: consumer's receipt digest could be matched to none of them. Deterministic
#: on purpose: no clock, no git state, only bytes.
_PRODUCER_MODULES: tuple[str, ...] = (
    "unified_agenda_parquet",
    "unified_agenda_editions",
    "citation_grammar",
    "identifier_shapes",
    "act_resolution",
    #: The section oracle's own module, which is also how its six tables are
    #: named here: their digests are literal strings in it and its loader
    #: refuses on drift, so hashing the module pins the tables too.
    "usc_section_oracle",
    #: The CFR authority-note reader. Its cache's digest is a literal string in
    #: it as well, so the same argument applies -- and the file is listed under
    #: "oracles" below too, because that one IS the publisher's bytes.
    "cfr_authority_notes",
    #: The recodification tables the section oracle consults. Same argument a
    #: third time: the derived table's sha256 and the printed volume's sha256
    #: and byte length are all literals in RECODIFICATIONS, and the loader
    #: refuses on drift, so hashing the module pins the table and the page it
    #: was cut from.
    "usc_disposition_tables",
)


def _producer_block() -> dict[str, object]:
    """Content digests of the modules and oracles a build reads."""

    import hashlib

    here = Path(__file__).resolve().parent

    def digest(path: Path) -> str | None:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

    return {
        "modules": {name: digest(here / f"{name}.py") for name in _PRODUCER_MODULES},
        "oracles": {
            "public-law-roster.csv": digest(_PL_ROSTER_CSV),
            "part-subjects.csv": digest(_OFR_INDEX_CSV),
            "ecfr-authority-notes-2026-08-24/notes.jsonl": digest(_CFR_AUTHORITY_NOTES_JSONL),
            "unified-agenda-fr-document-roster/documents.csv": digest(_FR_DOCUMENT_ROSTER_CSV),
            "initialism-roster-2026-08-24/roster.csv": digest(_INITIALISM_ROSTER_CSV),
        },
    }


def describe_producer_drift(output_root: Path) -> str | None:
    """Say when the artifact's receipt names other code or oracles than these.

    Not a verification failure: the tables still match their receipt. It is
    the answer to the other question a consumer asks, "is this what the code
    does now?", which --verify alone cannot answer.
    """

    import json

    receipt_path = Path(output_root) / "receipt.json"
    if not receipt_path.is_file():
        return None
    recorded = json.loads(receipt_path.read_text(encoding="utf-8")).get("producer")
    if not isinstance(recorded, dict):
        return "the receipt names no producer; it predates producer blocks"
    current = _producer_block()
    moved = [
        f"{group}/{name}"
        for group in ("modules", "oracles")
        for name, value in current[group].items()
        if recorded.get(group, {}).get(name) != value
    ]
    if not moved:
        return None
    return "the artifact was written by other code or oracles than these: " + ", ".join(moved)


#: A U.S.C. title exists from the day its enacting law was approved, and two of
#: the fifty-four were enacted INSIDE the span these editions cover — so the
#: present-day roster answers "possible" about editions that could not have
#: cited them. The dates are NOT typed here: they come out of the pinned
#: congress.gov roster, which is the same oracle every Public Law rule uses.
_USC_TITLE_ENACTED_BY_LAW: Mapping[int, tuple[int, int]] = {
    51: (111, 314),  # National and Commercial Space Programs
    54: (113, 287),  # National Park Service and Related Programs
}
#: Title 52 has no enacting law: the OLRC created it in 2014 by EDITORIAL
#: reclassification out of titles 2 and 42, so no public law dates it and the
#: year is stated here with its source
#: (https://uscode.house.gov/editorialreclassification/t52/index.html).
_USC_TITLE_RECLASSIFIED_IN: Mapping[int, int] = {52: 2014}


@dataclass(frozen=True)
class _SeriesCalendar:
    """The series bounds, indexed by the year of the edition doing the citing.

    Every series verdict in this table used to be judged against a present-day
    constant, so "54 USC 4118" in a Spring 2004 edition read as possible —
    title 54 exists NOW, and was enacted ten years after that filing. Validity
    carries a calendar, and the builder already had one rule that knew it
    (``_act_key_within_calendar``); this is the same rule for the other flags.

    The calendar is the pinned congress.gov roster read by approval date, not a
    formula: the highest congress and the highest Statutes volume that had
    published anything by the end of a given year. Where the roster cannot
    speak — a year before it starts, or a series with no pinned dates at all —
    the verdict falls back to the undated series bound rather than inventing a
    refusal. A calendar that guesses is worse than no calendar.

    Executive orders have NO pinned date oracle in this tree, so their flag
    stays undated. Measured 2026-08-22 before leaving it so: across all 18,997
    in-series EO rows, the highest number any edition cites is inside that
    edition's own year in every one of the 31 years captured (1995 cites at
    most EO 12958, signed that April; 2025 at most 14308). The cost of the
    missing calendar is zero rows, which is why no oracle was invented for it.
    """

    #: year -> the highest congress that had enacted a law by the end of it.
    congress_by_year: Mapping[int, int]
    #: year -> the highest Statutes at Large volume published by the end of it.
    volume_by_year: Mapping[int, int]
    #: U.S.C. title -> the first year it existed.
    usc_title_from_year: Mapping[int, int]
    #: "congress-law" -> the (year, month) the President approved it, off the
    #: SAME pinned roster the two bounds above are cumulated from. The bounds
    #: answer at YEAR resolution because that is all a cumulative maximum can
    #: say; this answers at the resolution the roster actually carries, for
    #: the one caller that needs it. See :meth:`pl_approved_by_edition`.
    pl_approved_in: Mapping[str, tuple[int, int]] = field(default_factory=dict)

    @classmethod
    def build(cls, roster) -> _SeriesCalendar:
        if roster is None:
            return cls({}, {}, {})
        dates, volumes = roster
        congress_by_year: dict[int, int] = {}
        volume_by_year: dict[int, int] = {}
        approved: dict[str, tuple[int, int]] = {}
        for (congress, law), date in dates.items():
            parts = date.split("/")
            year = int(parts[-1])
            congress_by_year[year] = max(congress_by_year.get(year, 0), congress)
            volume = volumes.get((congress, law))
            if volume is not None:
                volume_by_year[year] = max(volume_by_year.get(year, 0), volume)
            # MM/DD/YYYY on all 21,039 rows of the pinned roster; a row spelled
            # any other way keeps its year for the two bounds above and simply
            # offers no month, which is the fallback pl_approved_by_edition
            # documents rather than a guess about which part is the month.
            if len(parts) == 3:
                approved[f"{congress}-{law}"] = (year, int(parts[0]))
        titles = dict(_USC_TITLE_RECLASSIFIED_IN)
        for title, pair in _USC_TITLE_ENACTED_BY_LAW.items():
            if pair in dates:
                titles[title] = int(dates[pair].split("/")[-1])
        return cls(
            cls._cumulative(congress_by_year), cls._cumulative(volume_by_year), titles, approved
        )

    @staticmethod
    def _cumulative(by_year: Mapping[int, int]) -> Mapping[int, int]:
        """The running maximum, so a year with no laws still has a bound."""

        if not by_year:
            return {}
        running = 0
        out: dict[int, int] = {}
        for year in range(min(by_year), max(by_year) + 1):
            running = max(running, by_year.get(year, 0))
            out[year] = running
        return out

    @staticmethod
    def _edition_year(publication_id: object) -> int | None:
        edition = str(publication_id or "")[:4]
        return int(edition) if edition.isdigit() else None

    def _bound(self, by_year: Mapping[int, int], publication_id: object) -> int | None:
        """The bound for this edition's year, or None where none is pinned."""

        year = self._edition_year(publication_id)
        if year is None or not by_year:
            return None
        if year < min(by_year):
            return None
        return by_year[min(year, max(by_year))]

    def usc_title_is_possible(self, title: int | None, publication_id: object) -> bool | None:
        """The undated verdict, and then: had this title been created yet?"""

        verdict = usc_title_is_possible(title)
        if verdict is not True:
            return verdict
        year = self._edition_year(publication_id)
        created = self.usc_title_from_year.get(title)
        return not (year is not None and created is not None and year < created)

    def pl_congress_in_series(self, public_law: str | None, publication_id: object) -> bool | None:
        if public_law is None:
            return None
        congress = int(public_law.split("-")[0])
        if not PL_FIRST_NUMBERED_CONGRESS <= congress <= CONGRESS_CURRENT:
            return False
        bound = self._bound(self.congress_by_year, publication_id)
        return bound is None or congress <= bound

    def pl_approved_by_edition(self, public_law: str | None, publication_id: object) -> bool | None:
        """Had this law been APPROVED by the edition that would cite it?

        The congress bound above is a year-resolution answer, and a year is
        not fine enough for the question a candidate authority asks. Pub. L.
        110-20 was approved 05/02/2007; the 110th Congress had enacted laws by
        the end of 2007, so :meth:`pl_congress_in_series` calls it in series
        for the SPRING 2007 edition (``200704``) -- an edition published a
        month before the law existed. The pinned roster carries the approval
        date itself, so the finer question is answerable without a new oracle:
        the (year, month) the law was approved against the (year, month) the
        edition names.

        Falls back to the congress bound, never to silence, wherever the finer
        question cannot be asked: a law the pinned roster does not carry, and
        a publication id that states no month (``"2012"``, the one edition
        whose id breaks the YYYYMM spelling -- see
        ``unified_agenda_editions``). That residue is the documented cost:
        such a row is judged exactly as well as it was before this method
        existed, and no better.

        Deliberately NOT wired into ``pl_congress_in_series``'s published
        column. That column is a SERIES verdict a consumer already keys on
        across the whole table, and moving it is a corpus-wide change with its
        own census; this is one gate for one new column, and it says so.
        """

        if public_law is None:
            return None
        approved = self.pl_approved_in.get(str(public_law).strip().lower())
        edition = str(publication_id or "")
        if approved is None or not re.fullmatch(r"\d{6}", edition):
            return self.pl_congress_in_series(public_law, publication_id)
        return approved <= (int(edition[:4]), int(edition[4:6]))

    def stat_volume_in_series(self, volume: int | None, publication_id: object) -> bool | None:
        if volume is None:
            return None
        if not 1 <= volume <= STAT_VOLUME_HIGHEST_KNOWN:
            return False
        bound = self._bound(self.volume_by_year, publication_id)
        return bound is None or volume <= bound

    def fr_volume_in_series(self, volume: int | None, publication_id: object) -> bool | None:
        """Volume 1 is 1936, so an edition of year Y cannot cite above Y-1935.

        No roster needed: the Register's volume IS its year. Four series
        carried a bound column and were loud; this one carried none and
        "643FR 44121" sat typed federal_register, flagged by nothing
        (silent-misreads-2026-08-22, class A3).
        """

        if volume is None:
            return None
        if not 1 <= volume <= FR_VOLUME_HIGHEST_KNOWN:
            return False
        year = self._edition_year(publication_id)
        return year is None or volume <= year - 1935

    @staticmethod
    def fr_page_in_series(page: int | None) -> bool | None:
        if page is None:
            return None
        return 1 <= page <= FR_PAGE_HIGHEST_KNOWN

    @staticmethod
    def eo_in_known_series(executive_order: str | None) -> bool | None:
        """Undated on purpose — see the class docstring's measured zero."""

        if executive_order is None:
            return None
        return 1 <= int(executive_order) <= EO_HIGHEST_KNOWN


_TRAILING_YEAR_STYLE = re.compile(r"(,| of)? ((?:18|19|20)\d{2})")
_TRAILING_YEAR_DESIGNATOR = re.compile(r"(,| of)? (?:18|19|20)\d{2}$")
#: A designator tail after an act's name: "Clean Air Act title I" cites the
#: act (103 failed rows did); the title designation stays visible in the
#: original text, the same convention as presidential memoranda dates.
_ACT_DESIGNATOR_TAIL = re.compile(
    r",?\s*(?:title|div(?:ision)?\.?|subtitle|part)\s+(?:[IVXLC]+[A-D]?|\d+[A-Z]?)\s*$",
    re.IGNORECASE,
)
_LEADING_ARTICLE = re.compile(r"^the\s+")
_TRAILING_PARENTHETICAL = re.compile(r"\s*\([^)]{1,12}\)\s*$")


def _act_name_resolver(index: ActIndex | None) -> Callable[[str], str | None] | None:
    """name -> the act it refers to, memoised. ``None`` without an index.

    :func:`resolve_act_name` walks the Popular Name Tool's own cross-references,
    so this answers "which ACT is this name" where the closure below otherwise
    only knows "which NAME is this". The memo matters: the closure asks about
    every colliding variant it derives, and the walk is not free.
    """

    if index is None:
        return None
    answers: dict[str, str | None] = {}

    def resolves(name: str) -> str | None:
        if name not in answers:
            answers[name] = resolve_act_name(name, index)
        return answers[name]

    return resolves


def _yearless_stems(names: Collection[str]) -> dict[str, tuple[str, ...]]:
    """Year-less stem -> every listed act that completes it with a year.

    The closure below derives one such stem per canonical name and drops it
    where two acts claim it. This states the same population as a table, so the
    receipt can count what was admitted and what was refused, and a test can
    hold the two readings together instead of trusting one.
    """

    by_stem: dict[str, set[str]] = {}
    for canonical in names:
        stem = _TRAILING_YEAR_DESIGNATOR.sub("", canonical)
        if stem != canonical and stem not in names:
            by_stem.setdefault(stem, set()).add(canonical)
    return {stem: tuple(sorted(acts)) for stem, acts in by_stem.items()}


#: A Table III key that is a SESSION law states its own year: ``1955:360`` is
#: chapter 360 of 1955. The public-law keys (``102-579``) state a congress, and
#: the pinned public-law roster dates those.
_SESSION_LAW_YEAR = re.compile(r"^(1[789]\d\d|20\d\d):")

#: The mirror of :data:`~refspec.registry.act_resolution.ALIAS_YEAR_RULE`, and
#: the asymmetry review #2 measured: the year rule SUPPLIES a trailing year the
#: Popular Name Tool's own entry carries and the citation omits, but nothing
#: ever STRIPS one the citation carries and the entry does not. So "Waste
#: Isolation Pilot Plant Land Withdrawal Act of 1992" failed while the tool's
#: entry for Pub. L. 102-579 — approved 10/30/1992 — is the same name without
#: the year (2060-AJ07 200310, review notes G).
#:
#: The year is admitted only where a SOURCE states it of that very act, never
#: because it looks like one: the Table III key when it is a session law
#: (:data:`_SESSION_LAW_YEAR`), the pinned public-law roster's approval date
#: otherwise. That fence is the whole rule, and it is what refuses the four
#: shapes the same corpus offers beside the three it admits — "Clean Air Act of
#: 1990" (the act is 1955:360; 1990 names the AMENDMENTS, which the index lists
#: separately), "Soil Conservation and Domestic Allotment Act of 1936"
#: (1935:85), "Social Security Act of 1886" (1935:531), and "Fair Labor
#: Standards Act of 1939", whose entry carries 1938 and so is not a year-less
#: name at all. "Space Act of 1958" is refused by the same construction: no
#: act is LISTED as "Space Act", and the stem reaches the SPACE Act of 2015.
#:
#: Only names the tool lists WITHOUT a year take a year, so no entry that
#: already distinguishes its family by year can be reached under a second one.
ACT_ENACTMENT_YEAR_RULE = "supply-the-acts-own-enactment-year-to-a-yearless-listed-name-v1"


def _act_enactment_years(
    index: ActIndex | None, pl_roster: tuple[Mapping, Mapping] | None
) -> dict[str, str]:
    """Year-less listed act name -> the year its own enacting law was approved.

    Both halves are read, never derived: a session-law Table III key states the
    year in the key itself, and a public-law key is dated by the pinned roster.
    An act whose key is neither — or whose law predates the roster's earliest
    congress — contributes nothing, which is why this is a mapping and not a
    computation over every name.
    """

    if index is None:
        return {}
    dates = pl_roster[0] if pl_roster else {}
    years: dict[str, str] = {}
    for name, table3_key in index.table3_key_by_name.items():
        if _TRAILING_YEAR_DESIGNATOR.search(name):
            continue
        session = _SESSION_LAW_YEAR.match(table3_key or "")
        if session is not None:
            years[name] = session.group(1)
            continue
        public_law = re.fullmatch(r"(\d+)-(\d+)", table3_key or "")
        if public_law is None:
            continue
        approved = dates.get((int(public_law.group(1)), int(public_law.group(2))))
        if approved:
            years[name] = approved[-4:]
    return years


def _act_name_spelling_closure(
    names,
    resolves: Callable[[str], str | None] | None = None,
    enactment_years: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """variant key -> canonical OLRC key, by declared spelling conventions.

    The OLRC itself alternates year styles ("Motor Carrier Act, 1935" but
    "Clean Air Act Amendments of 1990"), and prose writes "&" where a name
    says "and" — so each canonical name also answers to its ", 1935" /
    " of 1935" / " 1935" and ampersand spellings. No new information enters:
    every variant is derived from the pinned index, the key published is
    always canonical, and a variant reachable from two canonicals is dropped
    (ambiguity refuses, same as everywhere else — 3 of 39,801 dropped,
    measured 2026-08-21).

    ``enactment_years`` closes the year direction the other way
    (:data:`ACT_ENACTMENT_YEAR_RULE`): a listed name carrying NO year also
    answers to its own enacting law's year, in the same three punctuation
    styles, because a filer who writes "Buy Indian Act 1910" is spelling the
    act the tool lists as "Buy Indian Act" and dates to 1910. It is the same
    closure with the same collision rule, which is why it lives here rather
    than beside the year rule it mirrors.
    """

    lookup: dict[str, str] = {}
    ambiguous: set[str] = set()
    for canonical in names:
        variants = {canonical}
        for match in _TRAILING_YEAR_STYLE.finditer(canonical):
            year = match.group(2)
            start, end = match.span()
            variants |= {
                canonical[:start] + style + canonical[end:]
                for style in (f", {year}", f" of {year}", f" {year}")
            }
        # The year-less spelling: prose cites "Fair Labor Standards Act" for
        # the act of 1938. Only a TRAILING year designator drops, and the
        # collision rule below is what makes this safe — "Clean Air Act
        # Amendments" reaches three canonicals and refuses (638 year-less
        # variants dropped as ambiguous, measured 2026-08-21).
        yearless = _TRAILING_YEAR_DESIGNATOR.sub("", canonical)
        if yearless != canonical and yearless not in names:
            variants.add(yearless)
        for variant in tuple(variants):
            if " and " in variant:
                variants.add(variant.replace(" and ", " & "))
            if " & " in variant:
                variants.add(variant.replace(" & ", " and "))
        # The "and"-dropped spelling: the corpus writes "Resource
        # Conservation Recovery Act" for the Resource Conservation and
        # Recovery Act (79 rows, measured 2026-08-22). Derived over every
        # variant so the year-less and ampersand closures compose; zero
        # collisions across 9,160 derived variants, and a collision would
        # refuse like every other.
        for variant in tuple(variants):
            if " and " in variant:
                dropped = variant.replace(" and ", " ")
                if dropped not in names:
                    variants.add(dropped)
        for variant in variants:
            held = lookup.get(variant, canonical)
            if held == canonical:
                lookup[variant] = canonical
                continue
            # Two NAMES are not two acts. The Popular Name Tool says so itself:
            # "Atomic Energy Act of 1946" is stored as RENAMED to "... of
            # 1954", so both complete the stem "atomic energy act" and both
            # mean one act, filed under one Table III key. Four stems are like
            # that -- the other two are the Food Stamp Act of 1964 and of 1977,
            # both renamed to the Food and Nutrition Act of 2008, and the
            # Federal Coal Leasing Amendments Act of 1975/1976 and the Newborn
            # Screening Saves Lives Act of 2007/2008. Where the tool's own
            # cross-references make the two one, the ACT is published (never
            # whichever name this loop reached first, which would make the key
            # depend on iteration order); where they do not, the variant is
            # dropped exactly as before -- 634 of the 638 colliding stems,
            # "clean air act amendments" (1966, 1970, 1977) among them.
            agreed = resolves(canonical) if resolves is not None else None
            if agreed is not None and agreed == resolves(held):
                lookup[variant] = agreed
            else:
                ambiguous.add(variant)
    for variant in ambiguous:
        del lookup[variant]
    # The act's own enacting year, LAST and never over anything already
    # spelled (:data:`ACT_ENACTMENT_YEAR_RULE`). A year read off a public law's
    # approval date is weaker evidence than a year the tool itself wrote into a
    # name, so it yields to every spelling above rather than competing with
    # them: adding these inside the loop re-pointed 33 keys the tool's own
    # names had already answered ("adult education act of 1966" is a listed
    # name AND the year of the listed "adult education act") and dropped 18
    # more as newly ambiguous. Two acts enacted in one year still refuse each
    # other, the same rule as everywhere else.
    claimed: dict[str, set[str]] = {}
    for canonical, own_year in (enactment_years or {}).items():
        if canonical not in names:
            continue
        for style in (f", {own_year}", f" of {own_year}", f" {own_year}"):
            claimed.setdefault(f"{canonical}{style}", set()).add(canonical)
    for variant, owners in claimed.items():
        if len(owners) == 1 and variant not in lookup:
            lookup[variant] = next(iter(owners))
    return lookup


_ACT_INITIALISM_STOPWORDS = frozenset(
    {"of", "the", "and", "for", "a", "an", "to", "in", "on", "with", "by"}
)


def _act_initialism(key: str) -> str:
    """The initials of a popular name's significant words: "clean air act"
    -> "CAA". Function words and year tokens contribute nothing, matching how
    the corpus itself abbreviates ("CAAA" for the Clean Air Act Amendments
    of 1990)."""

    letters = []
    for word in re.split(r"[\s,:\-]+", key):
        if not word or word in _ACT_INITIALISM_STOPWORDS:
            continue
        if re.fullmatch(r"(?:18|19|20)\d{2}", word) or not word[0].isalpha():
            continue
        letters.append(word[0])
    return "".join(letters).upper()


#: A whole value that is an act's name followed by a bare section number:
#: "Clean Air Act 211(o)", "Social Security Act 204(b)" — the marker-less
#: spelling (118 failed rows, measured 2026-08-21). The section is the LAST
#: digit token, so the split point is structurally unique; a bare year-shaped
#: number without a subsection stays refused ("Trade Act 1974" could name a
#: year or a section, and refusing to choose is the rule).
_ACT_NAME_BARE_SECTION = re.compile(
    r"^(?P<name>.+?)[,\s]+(?P<section>\d{1,5}[A-Za-z]?)(?P<subsections>(?:\([^()]{1,8}\))*)\s*$"
)

def _bare_name_section_reading(text: object, act_lookup) -> tuple[str, str] | None:
    """(act_key, act_section) for a name the index holds with a bare section.

    "Clean Air Act 211(o)", "Social Security Act 204(b)" — and "CERCLA 102",
    which is the shape that made this a function rather than a block inside
    the parse loop. The OLRC's Popular Name Tool lists CERCLA as a name in its
    own right, so the index answers it directly where the INITIALISM machinery
    cannot: that machinery compares an abbreviation to the initials of a
    multi-word key, and "cercla" is one word whose initial is "C".

    Two independent refusals, parenthesised so the reader sees the precedence:
    a bare year-shaped number with no subsection ("Trade Act 1974" could name
    a year or a section, and refusing to choose is the rule), or a name the
    index cannot answer. Wrapping quotation marks are presentation, the same
    rule the placeholder detector applies.

    Written once because two callers need the identical answer: the parse
    loop, where the whole value is the name, and the slash rule, where a piece
    of the value is. A second implementation would be a second opinion about
    what an act name is.
    """

    if act_lookup is None:
        return None
    match = _ACT_NAME_BARE_SECTION.match(_WRAPPING_QUOTES.sub("", str(text or "").strip()))
    if match is None:
        return None
    if re.fullmatch(r"(?:18|19|20)\d{2}", match.group("section")) and not match.group("subsections"):
        return None
    name = normalize_popular_name(match.group("name"))
    if name not in act_lookup:
        return None
    return act_lookup[name], match.group("section").lower()


#: The abbreviation-plus-section shapes the corroboration pass reads, each
#: whole-value-anchored so prose can never donate one, and each measured on
#: the failed pool 2026-08-22. A section slot may carry a LIST ("CWA 301,
#: 304, 306") — every listed member is a citation, and reading one is
#: dropping the rest — or a designator tail ("CAA title I"), the same
#: presentation convention act names carry.
_ABBREV_SECTION_TOKEN = r"\d{1,5}[A-Za-z]{0,2}(?:-\d{1,4}[A-Za-z]?)?(?:\([^()]{1,8}\))*"
#: A COMPOUND TAIL: a further paragraph of the section before it, written as a
#: list member. "CAA 112(d)(2) & (3)" is one section, 112, with two paragraphs;
#: "CWA 501(a) and (e)" and "CAA 112(g) or (q)" are the same shape. It may only
#: appear AFTER a real section token, which is what keeps it from letting a
#: value that is nothing but parentheses read as a citation.
_ABBREV_SECTION_TAIL = r"\([^()]{1,8}\)(?:\s*\([^()]{1,8}\))*"
_ABBREV_SECTION_MEMBER = rf"(?:{_ABBREV_SECTION_TOKEN}|{_ABBREV_SECTION_TAIL})"
#: "&" is "and", and the corpus writes both. 2060-AP70's "CAA 112(d)(2) & (3)"
#: sits one box away from "CAA 112(d)(6)", which the roster already reads.
_ABBREV_SECTION_LIST = (
    rf"{_ABBREV_SECTION_TOKEN}"
    rf"(?:(?:\s*(?:,|and|or|&|/)\s*|\s+(?:to|through)\s+)+{_ABBREV_SECTION_MEMBER})*"
)
#: A scheme LABEL in front of the initialism, which the filer wrote and which
#: names no part of the citation the initialism makes: "42 USC BBA 4106"
#: (0938-AI89), "42 USC /RCRA 3004(a)(q)" (2050-AE01), "/TSCA 4" and
#: "/CAA 112 & 103" (2070-AC76). The title is dropped rather than read, because
#: BBA section 4106 and RCRA section 3004 are ACT sections whatever title they
#: end up in, and the filer's own separator -- a slash -- says the two spellings
#: are alternatives rather than one citation. Only ever a PREFIX: "PHSA 42,
#: USC 247d-6d" puts the label AFTER the initialism and stays refused, because
#: there the 42 is the title of a U.S.C. citation and not a section of the act.
#: One of the two must actually be written -- an all-optional prefix would make
#: this shape a duplicate of the plain one and count its rows twice.
_ABBREV_SCHEME_PREFIX = r"(?:\d{1,2}\s+U\.?\s?S\.?\s?C\.?A?\.?\s*/?|/)\s*"
#: The initialism itself, and the numeric suffix four of this corpus's acts
#: carry in their own short titles: TEA-21, MAP-21, NDAA-17. Without it the
#: whole-value shapes see "TEA" followed by an unreadable "-21".
_ABBREV_TOKEN = r"[A-Z]{2,8}(?:-\d{1,2})?"
_ABBREV_IGNORABLE = r"(?:\s*,?\s*as\s+amended)?[\s,;:.]*"
_ABBREVIATED_ACT_SHAPES: tuple[re.Pattern[str], ...] = (
    # "CWA 301", "CAA sec 112(f)(2)", "MMA, sec 811", "CWA 301, 304", "SDWA"
    re.compile(
        rf"^(?P<ab>{_ABBREV_TOKEN})\s*,?\s*(?:as\s+amended\s*,?\s*)?"
        rf"(?:[Ss]ec(?:tion)?s?\.?|§{{1,2}})?\s*"
        rf"(?P<sections>{_ABBREV_SECTION_LIST})?{_ABBREV_IGNORABLE}$"
    ),
    # The same, behind a scheme label the filer wrote in front of it:
    # "42 USC BBA 4106", "42 USC /RCRA 3004(a)(q)", "/TSCA 4". THREE letters at
    # least, because a two-letter token after a U.S.C. label is the damaged
    # label itself far more often than an act -- "29 USC UC 794" is 29 U.S.C.
    # 794, and reading it as an act named UC would take the row out from under
    # the scheme-label repair that exists for exactly this family.
    re.compile(
        rf"^{_ABBREV_SCHEME_PREFIX}(?P<ab>[A-Z]{{3,8}}(?:-\d{{1,2}})?)\s*,?\s*"
        rf"(?:as\s+amended\s*,?\s*)?(?:[Ss]ec(?:tion)?s?\.?|§{{1,2}})?\s*"
        rf"(?P<sections>{_ABBREV_SECTION_LIST})?{_ABBREV_IGNORABLE}$"
    ),
    # The first shape in LOWER CASE, and only with an explicit section marker:
    # "mma, sec 811" (0938-AQ16, Fall 2010). The marker is what separates a
    # lower-case initialism from an ordinary word, and the connectives are
    # named as well, because "and sec 941" is a list continuation and an act
    # named AND is not a thing this corpus has.
    re.compile(
        rf"^(?!(?:and|or|to|through|see|per|the|sub|note)\b)(?P<ab>[a-z]{{3,8}})\s*,?\s*"
        rf"(?:[Ss]ec(?:tion)?s?\.?|§{{1,2}})\s*"
        rf"(?P<sections>{_ABBREV_SECTION_LIST}){_ABBREV_IGNORABLE}$"
    ),
    # the inverted spelling: "212(a)(10) INA", "Sec. 1102 of the SSA"
    re.compile(
        rf"^(?:[Ss]ec(?:tion)?s?\.?|§{{1,2}})?\s*(?P<sections>{_ABBREV_SECTION_LIST})"
        rf"\s*,?\s*(?:of\s+the\s+)?(?P<ab>{_ABBREV_TOKEN}){_ABBREV_IGNORABLE}$"
    ),
    # "sec 4312(a) of BBA of 1997" — the year, when stated, must appear in
    # the resolved act's name or the whole reading refuses
    # The section slot takes a LIST like every other shape ("Sec. 408 and 946
    # of the MMA of 2003"), and the year's "of" is optional the way it
    # already is in "MMA 2003" below ("Sec 303(c) of the MMA 2003").
    re.compile(
        rf"^(?:[Ss]ec(?:tion)?s?\.?|§{{1,2}})\s*(?P<sections>{_ABBREV_SECTION_LIST})\s+of\s+(?:the\s+)?"
        rf"(?P<ab>{_ABBREV_TOKEN})(?:(?:\s+of)?\s+(?P<year>(?:18|19|20)\d{{2}}))?{_ABBREV_IGNORABLE}$"
    ),
    # "DRA of 2005", "MCA of 1935", "MCSA 1984" — the year names the act
    re.compile(
        rf"^(?P<ab>{_ABBREV_TOKEN})(?:\s+of)?\s+(?P<year>(?:18|19|20)\d{{2}})\s*,?\s*"
        rf"(?:(?:[Ss]ec(?:tion)?s?\.?|§{{1,2}})\s*(?P<sections>{_ABBREV_SECTION_LIST}))?{_ABBREV_IGNORABLE}$"
    ),
    # "CAA title I", "CAA title I parts C and D and sec 111(a)(4)"
    re.compile(
        rf"^(?P<ab>{_ABBREV_TOKEN})(?:\s*,?\s*as\s+amended)?\s*,?\s*"
        r"(?:title|division|div\.?|subtitle)\s+[IVXLC0-9]+[A-Za-z]?"
        r"(?:\s+parts?\s+[A-Z](?:\s+and\s+[A-Z])?)?"
        rf"(?:\s+and\s+(?:[Ss]ec(?:tion)?s?\.?|§{{1,2}})\s*(?P<sections>{_ABBREV_SECTION_LIST}))?"
        rf"{_ABBREV_IGNORABLE}$"
    ),
)
#: Citation labels are never act abbreviations: "PL 425" is a Public Law
#: missing its congress, not an act named "PL", whatever any oracle holds. The
#: numeric suffix ``_ABBREV_TOKEN`` now admits is stripped before the check, so
#: "PL-104-193" is refused here as the Public Law it is rather than reaching an
#: oracle as an act named "PL-10".
_ABBREV_LABEL_TOKENS = frozenset(
    {"PL", "USC", "USCA", "EO", "FR", "CFR", "RS", "DM", "STAT", "FSM",
     "OMB", "HR", "US", "DC", "IRC", "UST", "TIAS", "UNTS", "FAR", "DODD"}
)

#: An initialism ANYWHERE inside a value, rather than as the whole of it. The
#: whole-value shapes above are what ``_read_abbreviated_act`` reads; this is
#: what the act carry looks for in a DONOR box that reads as nothing at all --
#: "1007: SSA subsection 1902 (a) (61)" names the Social Security Act and no
#: whole-value shape will ever match it.
_ABBREV_INITIALISM = re.compile(r"\b[A-Z]{2,8}\b")

_WRAPPING_QUOTES = re.compile(r"""^["'“”\s]+|["'“”\s]+$""")
#: A space opened between a section number and its own subsection — "1919
#: (b)(1)(A)", "sec 932 (c) (2)", "Sec. 1101 (b)" — is damage to the
#: punctuation of a citation whose numbers are intact, the whole-value label
#: repairs one slot down. Anchored on a DIGIT or a closing parenthesis to the
#: left, which is what keeps it off "and (3)", "to (f)" and "or (q)", where
#: the space belongs to a connective and the parenthetical is a list member;
#: bounded to three characters, which keeps it off "(2000)" in a case
#: citation's year.
_SUBSECTION_GAP = re.compile(r"(?<=[\d)])\s+(?=\([a-zA-Z0-9]{1,3}\))")
_YEAR_SHAPED = re.compile(r"(?:18|19|20)\d{2}")
_ABBREV_SECTION_SPLIT = re.compile(r"\s*(?:,|\band\b|\bor\b|&|/)\s*")
#: "1421 to 1425" names a RANGE, not two sections: the pair collapses to
#: its stated compound before the list splits, the sections-of-name rule.
_ABBREV_SECTION_RANGE = re.compile(r"(\d{1,5}[A-Za-z]{0,2})\s+(?:to|through)\s+(\d{1,5}[A-Za-z]{0,2})")


#: An explicit section marker in front of the section slot. The publisher
#: saying "sec" is the publisher declaring the token a section, which is what
#: separates "SSA, sec 1834" (Medicare Part B durable medical equipment) from
#: "NEPA 1969" (the act's year). Both are digit strings the year regex
#: matches; only one of them is labelled.
_ABBREV_SECTION_MARKER = re.compile(r"(?:[Ss]ec(?:tion)?s?\.?|§{1,2})")

#: A year written with an apostrophe standing in for the century: "BBA '97",
#: "BBRA'99", "BIPA '00", "BBRA' 99" -- a straight or curly apostrophe, with
#: or without surrounding whitespace. Measured 2026-08-31 over the pinned
#: build's own authority values: 40 rows across 13 distinct texts carry the
#: shape, every one of them a year and not one a section (the 13 are the BBA
#: / BBRA / BIPA / OBRA family, one "(OBRA '87)" gloss inside a spelled-out
#: name, and one "Appropriations for FY '97").
#:
#: Three spellings are folded and a fourth is deliberately refused:
#:
#: * U+0027 and U+2019 are the two the corpus writes (839 and 59 rows carry
#:   the character at all; the publisher's own mangled U+2019 is repaired to
#:   U+2019 before this module ever sees it, see
#:   ``UNIFIED_AGENDA_MANGLED_APOSTROPHE_EDITIONS``).
#: * U+2018, the LEFT single quote, is folded too and is **unattested** in the
#:   pinned corpus -- zero rows. A shape that reads one curly quote and not
#:   its mirror is a defect waiting for the first row that writes it, and
#:   folding costs one character.
#: * "sec '97" -- an apostrophe-year immediately behind a SECTION MARKER -- is
#:   NOT expanded, and that refusal is the point. The marker is the publisher
#:   declaring the token a section, and ``marked`` deliberately defeats the
#:   year suppression in :func:`_corroborated_act_sections`, so an expansion
#:   there would mint ``act_section`` "1997" out of a year -- the exact defect
#:   this shape exists to prevent, one slot over. Left unexpanded, no shape
#:   reads it and the row stays loud-failed, which is what it did before this
#:   wave. Zero rows in the pinned corpus write it; the guard is insurance,
#:   and :func:`test_a_section_marked_apostrophe_year_is_refused_not_expanded`
#:   is what breaks if it is ever removed.
#:
#: The repair is lexical and runs BEFORE any shape is tried: spell the year
#: out in full and let the shapes -- and the year checks
#: :func:`_corroborated_act_sections` already runs for a stated FOUR-digit
#: year, both in the dedicated ``year`` slot ("BBA of 1997") and for a bare
#: one landing in the section slot ("NEPA 1969") -- read it exactly as they
#: read "BBA 1997".
#:
#: **An expanded token is a YEAR CLAIM and can never become a section.** With
#: the marked slot refused above, every expansion lands unmarked, where the
#: four-digit rule decides it: the year is dropped where the resolved act's
#: own published name carries it, and the whole reading REFUSES where it does
#: not. So "FOO '25" against an act of 2025 emits no section, and against an
#: act of any other year emits nothing at all rather than falling back to a
#: section 25 -- which is exactly what such a row did before this wave (no
#: shape read an apostrophe, so ``_abbrev_act_reading`` returned None), so
#: the refusal regresses nothing and mints nothing.
#:
#: The century is the ordinary two-digit pivot (00-68 is 20XX, 69-99 is
#: 19XX), which is right for every token this wave measured (BBA '97, BBRA
#: '99, BIPA '00 -> 1997/1999/2000) and costs nothing when it is wrong: the
#: year check rejects any year that is not a substring of the resolved act's
#: own published name, so a mis-guessed century refuses instead of
#: publishing. This is also the guard for the named defect: "BIPA' 00"
#: (apostrophe, then a space, then the digits) once reached this reader by an
#: unrelated route with no year check at all and published ``act_section``
#: "00" -- see the note in :func:`_corroborated_act_sections` below. Expanded
#: here, "BIPA' 00" reads as the bare year 2000 like every other
#: apostrophe-year token, and the existing four-digit-year-in-the-section-slot
#: rule empties its own section rather than minting one.
_APOSTROPHE_YEAR = re.compile(r"(?<=[A-Za-z])\s*['‘’]\s*(?P<yy>\d{2})(?!\d)")
#: The section marker as the LAST thing a head says, which is what the
#: apostrophe-year expansion refuses to follow. Spelled off the same marker
#: alternation every shape above uses; the "sec." spelling cannot reach here
#: at all, because :data:`_APOSTROPHE_YEAR` needs a letter immediately in
#: front of the apostrophe and a period is not one.
_SECTION_MARKER_BEFORE_A_YEAR = re.compile(r"(?:^|[^A-Za-z])[Ss]ec(?:tion)?s?$")


def _expand_apostrophe_years(text: str) -> str:
    """Spell "'97"/"'99"/"'00" out as "1997"/"1999"/"2000" -- see
    :data:`_APOSTROPHE_YEAR`, including the section-marked spelling it
    refuses."""

    def expand(match: re.Match[str]) -> str:
        if _SECTION_MARKER_BEFORE_A_YEAR.search(text[: match.start()]):
            return match.group(0)
        yy = match.group("yy")
        century = "20" if int(yy) <= 68 else "19"
        return f" {century}{yy}"

    return _APOSTROPHE_YEAR.sub(expand, text)


def _abbrev_act_reading(
    text: str,
) -> tuple[str, str | None, tuple[str, ...], bool] | None:
    """(abbreviation, stated year, section tokens, marked) for a whole value.

    ``marked`` says whether an explicit ``sec``/``section``/``§`` introduces
    the section slot. Purely lexical: whether the abbreviation resolves is the
    oracle's question, not this function's.

    The abbreviation comes back UPPER CASE, because one shape reads a
    lower-case spelling ("mma, sec 811") and every oracle that meets it --
    ``_act_initialism``, the pinned roster's key, ``_ABBREV_LABEL_TOKENS`` --
    is upper case. A reading that returned the filer's own case would answer
    differently for the same three letters.
    """

    stripped = _expand_apostrophe_years(
        _SUBSECTION_GAP.sub("", _WRAPPING_QUOTES.sub("", text.strip()))
    )
    for shape in _ABBREVIATED_ACT_SHAPES:
        match = shape.match(stripped)
        if match is None:
            continue
        groups = match.groupdict()
        raw = groups.get("sections") or ""
        marked = bool(raw) and bool(
            _ABBREV_SECTION_MARKER.search(stripped[: match.start("sections")])
        )
        ranged = _ABBREV_SECTION_RANGE.sub(r"\1-\2", raw)
        sections = tuple(
            token for token in _ABBREV_SECTION_SPLIT.split(ranged) if token
        )
        return match.group("ab").upper(), groups.get("year"), sections, marked
    return None


def _corroborated_act_sections(
    act_key: str, year: str | None, sections: tuple[str, ...], *, marked: bool = False
) -> tuple[str, ...] | None:
    """The act_section values a corroborated reading emits, or None to refuse.

    The year guard is identity: a stated year ("BBA of 1997") must appear in
    the resolved act's name. A year-SHAPED bare section token ("MCSA 1984")
    is the same statement in the section slot — if the year is in the name it
    contributes no section; if it is not ("CAA 1990" against "clean air
    act"), the reading refuses rather than minting section 1990.

    ``marked`` defeats that refusal, because an explicit section marker is the
    publisher stating which slot the token fills. Measured 2026-08-22 on the
    failed pool: 59 rows carry a year-shaped token in the section slot; the 8
    marked ones are all real sections ("SSA, sec 1834", "Sec 1833(h)(8) of the
    MMA", "Sec 1817(i) and 1871 of the SSA" — Medicare and Medicaid sections
    in the 1800s and 1900s), and the 51 unmarked ones are all the act's year
    ("NEPA 1969", "ARRA 2009", "MMA 2003", "EPA 1992", "BIPA 2000", "BBRA
    1999"). Two unmarked rows ("SSA 1819", "SSA 1919") are real sections
    wearing the ambiguous shape and stay refused: the text does not say which
    slot they fill, and refusing to choose is the rule.

    **A year is also written with two digits.** "BBRA 99" is the Balanced
    Budget Refinement Act of 1999, not its section 99, and the four-digit rule
    cannot see it — the pinned roster published exactly that wrong section
    before this clause existed. It is deliberately narrower than the rule above
    it: a two-digit token is suppressed only where the act's own published name
    carries the year it completes, so "Section 3(a)(2)(B) of the USHA of 1937"
    keeps its section 3. And it refuses nothing, because a refusal here would
    cost every short real section in the corpus to catch one year.

    **The apostrophe spelling of a two-digit year** ("BBA '97", "BIPA '00")
    never reaches this function AS an apostrophe at all:
    :func:`_expand_apostrophe_years` spells it out to four digits before any
    shape is tried, so this function sees "BBA 1997" and reads it under the
    FOUR-digit rule two paragraphs up. That is also the fix for the named
    defect review D found: "BIPA' 00" (apostrophe, then a space) used to
    reach an unrelated reading with no year check at all and publish
    act_section "00" under act_key "bipa" -- a row this function never saw.
    Expanded first, it is "BIPA 2000" like every sibling token, and the rule
    above empties its own section instead of minting one; see
    ``test_the_apostrophe_year_shape_never_publishes_the_named_defect``.
    """

    if year is not None and year not in act_key:
        return None
    emitted: list[str] = []
    for token in sections:
        bare = re.sub(r"\([^)]*\)", "", token).strip().lower()
        if not bare:
            continue
        if not marked and "(" not in token:
            if _YEAR_SHAPED.fullmatch(bare):
                if bare in act_key:
                    continue
                return None
            if len(bare) == 2 and bare.isdigit() and any(
                f"{century}{bare}" in act_key for century in ("18", "19", "20")
            ):
                continue
        emitted.append(bare)
    return tuple(emitted)


def _anchored_subsequence(abbreviation: str, initialism: str) -> bool:
    """Whether an abbreviation drops interior words but keeps head and tail.

    "MMA" for the Medicare Prescription Drug, Improvement, and Modernization
    Act of 2003 (initialism MPDIMA) is how the corpus shortens a long name:
    the first and last significant words always survive, the middle ones may
    not. Anchoring both ends is what keeps this from being a free subsequence
    match — unanchored, "MMA" would also reach the Federal MINE Safety act
    (FMSHA) through its interior letters, which is not how anyone abbreviates.

    Held out 2026-08-22 over the 137 abbreviation citations whose act the
    grammar already resolved: with the true act removed from the roster the
    operator answered 86 times, every answer the SAME act under a different
    published name (Table III key identical), and never a different act.
    """

    if len(abbreviation) < 2 or not initialism or len(abbreviation) > len(initialism):
        return False
    if abbreviation[0] != initialism[0] or abbreviation[-1] != initialism[-1]:
        return False
    index = 0
    for letter in initialism:
        if index < len(abbreviation) and abbreviation[index] == letter:
            index += 1
    return index == len(abbreviation)


def _abbrev_survivors(abbreviation: str, year: str | None, keys) -> list[str]:
    """The acts in one roster an abbreviation can name, year filtering first.

    The year is identity, not spelling: "MMA of 2003" at CMS reaches three
    Medicare acts by initials alone (the Modernization Act of 2003, the
    Balanced Budget Refinement Act of 1999, the Benefits Improvement and
    Protection Act of 2000) and exactly one of them once the stated year
    filters the roster. Filtering candidates BEFORE counting survivors is
    what turns that ambiguity into an answer; filtering after would refuse.
    """

    pool = [key for key in keys if year is None or year in key]
    exact = [key for key in pool if _act_initialism(key) == abbreviation]
    if exact:
        return exact
    return [key for key in pool if _anchored_subsequence(abbreviation, _act_initialism(key))]


#: The corpus glossing its own abbreviation: "Medicare Modernization Act
#: (MMA)", "Immigration & Nationality Act (INA)". This is the publisher
#: declaring what its shorthand expands to, in its own authority column —
#: testimony, not inference.
_ACT_GLOSS = re.compile(
    r"([A-Z][A-Za-z0-9&.,'\- ]{6,90}?\bAct\b(?:\s+of\s+(?:18|19|20)\d{2})?)\s*\(([A-Z]{2,8})\)"
)
#: Words that carry no identity in an act's name. "amendments" is here because
#: a gloss and the OLRC's published name routinely differ on it.
_GLOSS_STOPWORDS = frozenset(
    {"of", "the", "and", "for", "a", "an", "to", "in", "on", "with", "by", "act", "amendments"}
)


def _gloss_words(name: str) -> frozenset[str]:
    """The identity-bearing words of a glossed name, years excluded."""

    return frozenset(
        word
        for word in re.split(r"[^a-z0-9]+", name)
        if word and word not in _GLOSS_STOPWORDS and not re.fullmatch(r"(?:18|19|20)\d{2}", word)
    )


def _harvest_act_glosses(authorities) -> dict[str, dict[str, set[str]]]:
    """agency code -> abbreviation -> every expansion that agency wrote."""

    glosses: dict[str, dict[str, set[str]]] = {}
    for row in authorities:
        for name, abbreviation in _ACT_GLOSS.findall(row["authority_text"]):
            table = glosses.setdefault(row["rin"][:4], {})
            table.setdefault(abbreviation, set()).add(normalize_popular_name(name))
    return glosses


@dataclass(frozen=True)
class _InitialismRosterEntry:
    """One (token, agency, year) the pinned roster has something to say about."""

    token: str
    agency_prefix: str
    year_key: str
    status: str
    act_name: str
    evidence_path: str

    @property
    def not_an_act_type(self) -> str | None:
        """"directive", "agency", "treaty" … for a token that names no act."""

        return self.status.split(":", 1)[1] if self.status.startswith("not-an-act:") else None


def _initialism_roster() -> dict[tuple[str, str], tuple[_InitialismRosterEntry, ...]] | None:
    """(TOKEN, agency prefix) -> its rows, or None where this tree lacks the file.

    Keyed on the agency because the roster IS keyed on the agency: "EPA 1992"
    at the Forest Service is the Energy Policy Act of 1992 and "EPA Acquisition
    Regulation" at 2030 is the agency naming itself, and a roster that answered
    both from one row would be inventing the thing this file exists to refuse.
    A token that is keyed by year has several rows at one such pair; which of
    them a citation reaches is the caller's question, because only the caller
    has read the year out of the text.

    **A row of the wrong width is refused, not read.** ``csv.DictReader``
    parks surplus fields under the ``None`` key and pads short rows with
    ``None``, so a note whose comma was never quoted loads as a row that reads
    correctly in every column this function names and is silently a different
    row from the one the file's author wrote. That is exactly what happened:
    the file carried a 12-field row against an 11-field header for a day, and
    nothing said so, because none of the six columns below is the one that
    moved. The width is checked instead of trusted, and a mismatch raises --
    the file is a pinned receipt, and half of one is not a smaller receipt.
    ``rows_observed``, deliberately not read here, is documented in the
    generator that writes it (``build_roster.py``): it is a census of unread
    rows taken when the roster was built, first-recognized-token-wins, and it
    goes DOWN as this roster does its job.
    """

    import csv

    if not _INITIALISM_ROSTER_CSV.is_file():
        return None
    roster: dict[tuple[str, str], list[_InitialismRosterEntry]] = {}
    with _INITIALISM_ROSTER_CSV.open(encoding="utf-8", newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle), start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(
                    f"the initialism roster's row {number} does not have "
                    f"{len(_INITIALISM_ROSTER_FIELDS)} fields: {row!r}"
                )
            if tuple(row) != _INITIALISM_ROSTER_FIELDS:
                raise ValueError(
                    f"the initialism roster's columns are {tuple(row)}, "
                    f"not {_INITIALISM_ROSTER_FIELDS}"
                )
            entry = _InitialismRosterEntry(
                token=row["token"].upper(),
                agency_prefix=row["agency_prefix"],
                year_key=row["year_key"],
                status=row["status"],
                act_name=row["act_name"],
                evidence_path=row["evidence_path"],
            )
            roster.setdefault((entry.token, entry.agency_prefix), []).append(entry)
    for key, entries in roster.items():
        years = [entry.year_key for entry in entries]
        if len(years) != len(set(years)):
            raise ValueError(
                f"the initialism roster holds two rows for {key[0]} at {key[1]} under the same year"
            )
    return {key: tuple(entries) for key, entries in roster.items()}


def _gloss_narrowed(glosses, survivors: list[str]) -> list[str] | None:
    """Survivors whose published name carries every word the gloss states.

    Wave 3 named "MMA" the census's largest single refusal: the corpus
    abbreviates the Medicare Prescription Drug, Improvement, and Modernization
    Act of 2003 as MMA, the initials operator derives MPDIMA, and the OLRC
    publishes no "Medicare Modernization Act" alias — so no oracle testified.
    One does: the corpus itself writes "Medicare Modernization Act (MMA)" in
    its own authority column, 35 times at CMS. The gloss cannot name the act
    (it is not an index name), but its words {medicare, modernization} pick
    exactly one of the three Medicare acts CMS's roster holds — the other two
    are the Balanced Budget Refinement Act of 1999 and the Benefits
    Improvement and Protection Act of 2000, neither of which modernizes
    anything.

    Fenced by agency, like every other roster here. Measured 2026-08-22: over
    the 99 rows where the roster oracle already answers uniquely AND a gloss
    exists, the gloss agrees 99 times and disagrees 0; where the gloss's words
    reach no survivor it returns an empty list and the row stays refused
    (36 such rows) rather than contradicting the roster.
    """

    if not glosses:
        return None
    words: set[str] = set()
    for expansion in glosses:
        words |= _gloss_words(expansion)
    if not words:
        return None
    return [key for key in survivors if words <= _gloss_words(key)]


def _one_word_prefix_survivors(query: str, pool) -> set[str]:
    """Acts in a roster one word-lengthening away from a queried name.

    The corpus writes "Railroad Safety Improvement Act of 2008"; the act's own
    short title (Pub. L. 110-432, Div. A) is the "Rail Safety Improvement Act
    of 2008", which is what the OLRC publishes. One word differs, and the
    shorter is a prefix of the longer — the damage operator is a writer
    completing an abbreviation the statute did not make.

    Wave 3 measured this operator against the WHOLE index (13,560 names),
    found it recovered 15 rows over one distinct value, and refused it on
    yield because a one-specimen operator has an unmeasured false-positive
    surface. Wave 4 fences it with the citing agency's own resolved-act
    roster and MEASURES that surface: held out 2026-08-22 over the 1,964
    distinct (text, RIN) act citations the grammar resolved, with the true act
    removed from the roster, the operator invented a survivor **0 times**. It
    is inert where the index already answers and silent where it is wrong.
    """

    words = query.split()
    survivors: set[str] = set()
    for candidate in pool:
        other = candidate.split()
        if len(other) != len(words):
            continue
        differing = [i for i, (a, b) in enumerate(zip(words, other, strict=True)) if a != b]
        if len(differing) != 1:
            continue
        left = words[differing[0]].rstrip(".")
        right = other[differing[0]].rstrip(".")
        if left == right or len(left) < 4 or len(right) < 4:
            continue
        if left.startswith(right) or right.startswith(left):
            survivors.add(candidate)
    return survivors


def _act_prose_key(text: str) -> tuple[str, str | None]:
    """(normalised act name, stated section) after the presentation tails come
    off — the same peeling the index-side operators already do."""

    work = _AS_AMENDED_TAIL.sub("", _WRAPPING_QUOTES.sub("", text.strip()))
    section = None
    match = _TRAILING_SECTION.search(work)
    if match is not None:
        section = match.group("section").lower()
        work = work[: match.start()]
    work = _LEADING_DESIGNATOR.sub("", work)
    while True:
        peeled = _ACT_DESIGNATOR_TAIL.sub("", _AS_AMENDED_TAIL.sub("", work))
        if peeled == work:
            break
        work = peeled
    return normalize_popular_name(work), section


#: One token of a bare section list: digits, an optional letter suffix, an
#: optional hyphenated compound ("1437z-5"), any number of parenthesised
#: subsections, and the "note"/"et seq." tails the corpus writes.
_HISTORY_TOKEN = r"\d{1,5}[a-z]{0,3}(?:-\d{1,4}[a-z]?)?(?:\([^()]{1,10}\))*(?:\s+note)?(?:\s+et\s+seq\.?)?"
#: A member that is nothing but a parenthesised subsection continues the
#: member before it: "41102(2), (4) and (8)" is one section with three
#: subsections, and "4502(6) and (12)" is one section with two. English lists
#: subsections this way and the corpus does too (22 rows, 8 spellings) — so
#: the member is not a section number and must not be read as one.
_HISTORY_SUBSECTION_MEMBER = r"\([^()]{1,10}\)"
#: The separator between two members. ", and" is ONE separator the corpus
#: writes with both glyphs (the Oxford comma), not two: "12838, and 12905(h)"
#: is a two-member list, and reading it as three refuses a real citation.
_HISTORY_SEPARATOR = r"(?:,\s*and|,|and|or|through|to)"
#: A whole value that is nothing but a section list: "31136(a)", "41708 and
#: 41709", "sec 172(a)", "2601 to 2645". Whole-value anchored, so prose can
#: never donate one. A trailing ", as amended" is ignorable here for the same
#: reason it is in every act shape: it says the law changed, not which law.
_HISTORY_SECTION_LIST = re.compile(
    rf"^(?:[Ss]ecs?\.?\s+|[Ss]ections?\s+)?{_HISTORY_TOKEN}"
    rf"(?:\s*{_HISTORY_SEPARATOR}\s*(?:{_HISTORY_TOKEN}|{_HISTORY_SUBSECTION_MEMBER}))*"
    r"(?:\s*,?\s*as\s+amended)?[\s.,;]*$",
    re.IGNORECASE,
)
_HISTORY_LIST_SPLIT = re.compile(r"\s*(?:,\s*and\b|,|\band\b|\bor\b)\s*", re.IGNORECASE)
_HISTORY_AS_AMENDED = re.compile(r"\s*,?\s*as\s+amended\s*$", re.IGNORECASE)
_HISTORY_SUBSECTION_ONLY = re.compile(rf"^{_HISTORY_SUBSECTION_MEMBER}$")
#: "USC 44101", "U.S.C. 31311(a)", "USC 7401 et seq" — the code label with no
#: title in front. The "et seq." tail is ignorable here for the same reason it
#: is everywhere else: it says the citation continues, not where it starts.
_HISTORY_TITLELESS_USC = re.compile(
    r"^U\.?\s?S\.?\s?C\.?(?:\s?A\.?)?\s+(?P<section>\d{1,5}[A-Za-z]{0,3}(?:-\d{1,4}[A-Za-z]?)?)"
    r"(?:\([^()]{1,10}\))*(?:\s+note)?(?:\s+et\s+seq\.?)?[\s.,;]*$",
    re.IGNORECASE,
)
#: "49 46105", "8 1252 note" — a container and a member with the label between
#: them lost. Which container it is (a U.S.C. title or a Statutes volume) is
#: the oracle's question.
_HISTORY_LABELLESS_PAIR = re.compile(
    r"^(?P<title>\d{1,2})\s+(?P<section>\d{2,5}[A-Za-z]{0,3})(?:\([^()]{1,10}\))*"
    r"(?:\s+note)?(?:\s+et\s+seq\.?)?[\s.,;]*$"
)
#: "Stat. 2936" — the Statutes label kept, the volume lost.
_HISTORY_VOLUMELESS_STAT = re.compile(r"^Stat\.?\s+(?P<page>\d{2,5})[\s.,;]*$", re.IGNORECASE)
#: "89-670 and 91-605" — a Public Law pair with the label lost. The competing
#: reading is a section range, which the oracle settles.
#: "89-670 and 91-605", and "111-5, sec. 13111 to 13112" — the pair may carry
#: its own section tail, the tolerance the fused spelling already has
#: ("Pub. L. 10811, sec 1503").
_HISTORY_PL_PAIRS = re.compile(
    r"^\d{2,3}-\d{1,4}(?:\s*(?:,|and)\s*\d{2,3}-\d{1,4})*"
    r"(?:\s*,?\s*(?:secs?\.?|sections?|§{1,2})\s*\d{1,5}[A-Za-z]?(?:\([^()]{1,10}\))*"
    r"(?:\s*(?:,|and|to|through)\s*\d{1,5}[A-Za-z]?(?:\([^()]{1,10}\))*)*)?[\s.,;]*$",
    re.IGNORECASE,
)
_HISTORY_PL_PAIR_TOKEN = re.compile(r"^\d{2,3}-\d{1,4}|(?<=[\s,])\d{2,3}-\d{1,4}")

def _history_normalize(text: str) -> str:
    """The declared punctuation tolerances, applied to one authority value.

    Whitespace inside a subsection chain ("1814(i) (2)" for 1814(i)(2)) and an
    unmatched closing parenthesis ("2277a-10)") are damage to the PUNCTUATION
    of a value whose numbers are intact — the whole-value label repairs one
    slot down. The gap operator is the one the act shapes use, so a value the
    corroboration pass normalizes one way is never normalized another; the
    paren is dropped only where the value's own parentheses do not balance.
    """

    stripped = _WRAPPING_QUOTES.sub("", _normalize_dashes(text.strip()))
    stripped = _SUBSECTION_GAP.sub("", stripped)
    if stripped.count(")") == stripped.count("(") + 1 and stripped.endswith(")"):
        stripped = stripped[:-1].rstrip()
    return stripped


def _history_section_tokens(text: str) -> list[str] | None:
    """The member tokens of a whole-value section list, or None if not one."""

    stripped = _history_normalize(text)
    if not _HISTORY_SECTION_LIST.match(stripped):
        return None
    body = _HISTORY_AS_AMENDED.sub("", stripped)
    body = re.sub(r"^(?:[Ss]ecs?\.?|[Ss]ections?)\s+", "", body).rstrip(" .,;")
    # A stated range is one citation, not two: it collapses to its start,
    # the same rule the abbreviation shapes use.
    body = re.sub(rf"({_HISTORY_TOKEN})\s+(?:to|through)\s+({_HISTORY_TOKEN})", r"\1|\2", body)
    tokens: list[str] = []
    for token in _HISTORY_LIST_SPLIT.split(body):
        if not token:
            continue
        if _HISTORY_SUBSECTION_ONLY.match(token):
            # "(4)" after "41102(2)" is another subsection of 41102, not a
            # section 4. It carries no new place, so it emits no new citation
            # — and with no earlier member to attach to it is not a list at all.
            if not tokens:
                return None
            continue
        tokens.append(token)
    return tokens or None


def _history_bare(token: str) -> str:
    """The join key of a section token: subsections, tails and range end off.

    This is the corpus's own convention, not a new one: the grammar already
    stores "49 U.S.C. 31136(a)" as section "31136" with parse_status
    "partial", leaving the subsection visible in authority_text.
    """

    value = token.strip().lower().replace(" et seq.", "").replace(" et seq", "").replace(" note", "")
    value = re.sub(r"\([^()]*\)", "", value).strip()
    return value.split("|")[0].strip()


_HISTORY_IGNORABLE_TAIL = re.compile(r"\s*(?:et\s+seq\.?|note)\s*$", re.IGNORECASE)


def _history_stated(token: str) -> str:
    """What a section token STATES, as ``stated_section`` spells it.

    The join key (``_history_bare``) drops subsections because that is what the
    U.S.C. and act columns hold; the STATEMENT keeps them, because that is what
    the 16,615 joined "PL X-Y, sec N(a)" references hold. Only the range end
    and the ignorable tails come off -- a stated range is one citation, which
    is the rule ``_history_section_tokens`` already applied when it made the
    token.
    """

    return _HISTORY_IGNORABLE_TAIL.sub("", token.split("|")[0].strip()).strip(" .,;")


def _history_distinctive(section: str) -> bool:
    """Whether a section token is discriminating enough to carry a title.

    Short bare ordinals are the numbers every title reuses: 42, 301, 504, 509.
    Measured 2026-08-22 by holding out each grammar-read U.S.C. citation's own
    text and asking the corpus to name the title from the section alone,
    accuracy rose from 0.9574 to 0.9963 once these were excluded. A letter
    suffix ("6662a"), a hyphenated compound ("1437z-5") or four or more digits
    ("31136") is what makes a section number an identifier rather than an
    ordinal.
    """

    return bool(
        re.search(r"[a-z]", section) or "-" in section or len(re.sub(r"\D", "", section)) >= 4
    )


def _oracle_levels(rin: str) -> tuple[str, str]:
    """The two altitudes every roster here is fenced by, in order.

    A RIN persists across editions, so the same rule's other appearances speak
    first; the next altitude up is the RIN's leading four digits, which are the
    OMB-assigned agency code (reginfo.gov's own definition).
    """

    return rin, rin[:4]


def _first_level_answer(levels: Iterable[str], survivors_of: Callable[[str], Collection]):
    """The escalation rule, stated ONCE for every oracle in this module.

    A level naming exactly one survivor answers. A level naming several
    REFUSES OUTRIGHT rather than escalating -- borrowing a wider roster to
    break a tie is how a fence stops being a fence, and wave 5 measured what
    the wider rosters do when allowed to (the corpus-wide abbreviation roster
    invents a wrong survivor 15.25% of the time even date-bounded). A level
    naming none is silent, and the next one may speak.

    Six sites spelled this policy six ways before it was written down here.
    What differs between them is ``survivors_of`` -- the fence -- which is the
    load-bearing part and stays per-rule.
    """

    for level in levels:
        survivors = survivors_of(level)
        if len(survivors) == 1:
            return next(iter(survivors))
        if survivors:
            return None
    return None


@dataclass(frozen=True)
class _CitationHistory:
    """What a rule's own editions, and its agency's rules, have cited.

    A RIN persists across editions, so the same rule's other appearances are
    testimony about what its authority strings mean; the agency's roster is
    the next altitude up, keyed by the RIN's OMB-assigned four-digit agency
    code. Only rows the GRAMMAR read enter — never a corroborated row — so
    corroboration never bootstraps on corroboration.
    """

    usc: dict[str, set[tuple[int, str]]]
    act: dict[str, set[tuple[str, str]]]
    stat: dict[str, set[tuple[int, int]]]
    public_law: dict[str, set[tuple[int, int]]]
    #: (public_law, section) -- the third identity space a bare section can
    #: land in, and the one that was missing. The pool held U.S.C. and act
    #: sections only, so "sec. 939(e)" at SEC RIN 3235-AL33 could not survive:
    #: agency 3235's act pool holds no section 939, while the SAME RIN's
    #: earlier editions spell the whole citation "PL 111-203 sec 939(e)" in one
    #: string -- in a space the pool did not read. Measured: 89 rows over 36
    #: RINs answer here, 5 refuse as ambiguous.
    public_law_sections: dict[str, set[tuple[str, str]]]
    #: section -> every U.S.C. title the corpus ever files it under. A section
    #: several titles claim cannot name one from its digits alone.
    usc_titles_by_section: dict[str, set[int]]
    #: Every section string the pool cites, for the competing-reading checks.
    sections: dict[str, set[str]]

    @classmethod
    def build(cls, authorities) -> _CitationHistory:
        usc: dict[str, set[tuple[int, str]]] = {}
        act: dict[str, set[tuple[str, str]]] = {}
        stat: dict[str, set[tuple[int, int]]] = {}
        laws: dict[str, set[tuple[int, int]]] = {}
        law_sections: dict[str, set[tuple[str, str]]] = {}
        titles: dict[str, set[int]] = {}
        sections: dict[str, set[str]] = {}
        for row in authorities:
            if row["parse_status"] == "corroborated":
                continue
            keys = (row["rin"], row["rin"][:4])
            if (
                row["authority_type"] == "usc"
                and row["usc_title"] is not None
                and row["usc_section"]
                and not row["usc_appendix"]
                # A damaged title must not pollute the oracle: "347 USC 307(e)"
                # is out of series and says nothing about where 307 lives.
                and row["usc_title_is_possible"]
            ):
                section = row["usc_section"].lower()
                titles.setdefault(section, set()).add(row["usc_title"])
                for key in keys:
                    usc.setdefault(key, set()).add((row["usc_title"], section))
                    sections.setdefault(key, set()).add(section)
            if row["act_key"] and row["act_section"]:
                section = row["act_section"].lower()
                for key in keys:
                    act.setdefault(key, set()).add((row["act_key"], section))
                    sections.setdefault(key, set()).add(section)
            if row["statute_volume"] is not None and row["statute_page"] is not None:
                for key in keys:
                    stat.setdefault(key, set()).add((row["statute_volume"], row["statute_page"]))
            if row["public_law"] and row["pl_congress_in_series"]:
                # A joined spelling -- "PL 111-203 sec 939(e)" -- is the
                # publisher's own binding of a law to a section, and it is what
                # the split halves elsewhere in the corpus are halves OF.
                if row["stated_section"]:
                    section = _history_bare(row["stated_section"])
                    if section:
                        for key in keys:
                            law_sections.setdefault(key, set()).add((row["public_law"], section))
                congress, number = row["public_law"].split("-", 1)
                try:
                    pair = (int(congress), int(number))
                except ValueError:
                    continue
                for key in keys:
                    laws.setdefault(key, set()).add(pair)
        return cls(usc, act, stat, laws, law_sections, titles, sections)

    def section_survivors(self, key: str, token: str) -> set[tuple[str, object]]:
        """Every body of law the pool files this section token under.

        Two survivors is an ambiguity and refuses. Only U.S.C. titles, act
        sections and Public Law sections can survive: a bare number in the
        authority column reads as a section of a code, an act or an enactment,
        never as a CFR part, a Statutes page or a Public Law NUMBER, because
        each of those forms requires a label the value does not carry.

        A Public Law survivor carries no extra fence beyond the pool's own
        altitude, for the reason the act survivor carries none: the pool is one
        rule's citations, and then its agency's, so an exact section match
        inside it is already narrow. Where it is not -- where the RIN's history
        binds one section to two laws -- ``_first_level_answer`` refuses.
        """

        value = _history_bare(token)
        survivors: set[tuple[str, object]] = set()
        if _history_distinctive(value) and len(self.usc_titles_by_section.get(value, ())) == 1:
            survivors |= {("usc", t) for (t, s) in self.usc.get(key, ()) if s == value}
        survivors |= {("act", k) for (k, s) in self.act.get(key, ()) if s == value}
        survivors |= {
            ("public_law", law) for (law, s) in self.public_law_sections.get(key, ()) if s == value
        }
        return survivors


def _usc_emission(title: int, section: str, *, note: bool = False) -> dict[str, object]:
    """One U.S.C. reading, spelled the one way every rule here spells it.

    It names a PLACE and carries no series verdict, because a series verdict
    carries a calendar and an emission cannot see the edition it lands in.
    ``_apply_corroboration`` dates every verdict on the row it writes.
    """

    return {
        "authority_type": "usc",
        "usc_title": title,
        "usc_section": section,
        "usc_note": note,
    }


def _stat_emission(volume: int, page: int) -> dict[str, object]:
    """One Statutes at Large reading. Its verdict is dated by the applicator."""

    return {
        "authority_type": "statute_at_large",
        "statute_volume": volume,
        "statute_page": page,
    }


def _act_emission(act_key: str, act_section: str | None) -> dict[str, object]:
    """One act-relative reading, spelled the one way every act rule spells it.

    The statements go out because the resolution now holds what they stated: a
    stated name is what a row has INSTEAD of an act key, and a stated section
    is what it has instead of that act's section. This is the rule the main
    emit path has always followed for grammar-read rows; writing it once here
    is what stops a corroboration rule from quietly disagreeing with it.
    """

    return {
        "authority_type": "act_relative",
        "act_key": act_key,
        "act_section": act_section,
        "stated_act_name": None,
        "stated_section": None,
    }


def _public_law_section_emission(public_law: str, section: str, evidence: str) -> dict[str, object]:
    """One "section N of Pub. L. X-Y" reading, spelled the corpus's own way.

    The 16,615 references that write both halves in ONE string store the law in
    ``public_law`` and the section in ``stated_section``, subsections intact
    ("PL 111-203 sec 939(e)" -> 111-203 / "939(e)"). A recovered reading joins
    the same way, with one deliberate difference: the law goes to
    ``public_law_corrected``, never to ``public_law``, because the grammar read
    nothing on this row -- the roster or the publisher's list order did. That
    is the posture ``roster-existent-public-law-pair`` already takes, and
    ``pl_correction_evidence`` names which of the two spoke.
    """

    return {
        "authority_type": "public_law",
        "public_law_corrected": public_law,
        "pl_correction_evidence": evidence,
        "stated_section": section,
    }


def _history_read_section_list(row, history: _CitationHistory):
    """"31136(a)" at an FMCSA RIN is 49 U.S.C. 31136 — because that RIN's own
    editions say so, not because a column's semantics were assumed.

    Every member of the list must resolve, and all members must land in the
    SAME body of law: one authority string names one place. A token the pool
    files two ways, or members that disagree, is an ambiguity this level
    speaks — and ``_first_level_answer`` refuses it rather than escalating.
    """

    tokens = _history_section_tokens(row["authority_text"])
    if tokens is None:
        return None

    def survivors_of(key: str) -> frozenset:
        per_token = [history.section_survivors(key, token) for token in tokens]
        if any(len(found) > 1 for found in per_token):
            # A token the pool files two ways makes the LIST two readings, so
            # the level speaks ambiguously and the escalation rule refuses.
            return frozenset().union(*per_token)
        if any(not found for found in per_token):
            return frozenset()  # a silent member: this level has not read it
        # One reading per member; members that disagree are again several.
        return frozenset(next(iter(found)) for found in per_token)

    answer = _first_level_answer(_oracle_levels(row["rin"]), survivors_of)
    if answer is None:
        return None
    scheme, value = answer
    if scheme == "usc":
        return "rin-history-section-list", [
            _usc_emission(value, _history_bare(token), note=" note" in token.lower())
            for token in tokens
        ]
    if scheme == "public_law":
        # The section keeps the spelling the row states -- subsections and all
        # -- because that is what the joined references this reading came from
        # store, and a resolution that re-spelled it would not join to them.
        return "rin-history-section-list", [
            _public_law_section_emission(value, _history_stated(token), "rin-history-section-list")
            for token in tokens
        ]
    # Through the same emission every other act rule uses, which is what
    # clears the statement this resolution supersedes: these rows used to keep
    # a stated_section beside their act_section, and on an exploded list the
    # two disagreed -- "sec 3568 and 3569" put stated_section "3568" on the
    # row resolving 3569.
    return "rin-history-section-list", [
        _act_emission(value, _history_bare(token)) for token in tokens
    ]


def _history_read_titleless_usc(row, history: _CitationHistory):
    """"USC 44101" keeps the code label and loses the title the label needs.

    Two fences the volume-less Statutes shape does NOT carry, and they are why
    these two look-alike rules stayed apart: the section must be an identifier
    rather than a reused ordinal, and the corpus as a whole must file it under
    one title only. A Statutes PAGE needs neither, because a page number is
    already an identifier within its volume.
    """

    match = _HISTORY_TITLELESS_USC.match(_history_normalize(row["authority_text"]))
    if match is None:
        return None
    section = match.group("section").lower()
    if not _history_distinctive(section) or len(history.usc_titles_by_section.get(section, ())) != 1:
        return None
    title = _first_level_answer(
        _oracle_levels(row["rin"]),
        lambda key: {t for (t, s) in history.usc.get(key, ()) if s == section},
    )
    if title is None:
        return None
    return "rin-history-titleless-usc", [_usc_emission(title, section)]


def _history_read_labelless_pair(row, history: _CitationHistory):
    """"49 46105" and "8 1252 note" state a container and a member with the
    label between them lost.

    Wave 2 refused this shape because "8 1252 note" could be U.S.C. or
    Statutes at Large and the column holds both. It still could — so the pair
    must exist in the pool under exactly ONE of the two, and a pair both
    schemes hold is two survivors at that level, which the escalation rule
    already refuses.
    """

    match = _HISTORY_LABELLESS_PAIR.match(_history_normalize(row["authority_text"]))
    if match is None:
        return None
    title, section = int(match.group("title")), match.group("section").lower()

    def survivors_of(key: str) -> frozenset[str]:
        found = set()
        if (title, section) in history.usc.get(key, ()):
            found.add("usc")
        if section.isdigit() and (title, int(section)) in history.stat.get(key, ()):
            found.add("statute_at_large")
        return frozenset(found)

    scheme = _first_level_answer(_oracle_levels(row["rin"]), survivors_of)
    if scheme == "usc":
        return "rin-history-labelless-pair", [
            _usc_emission(title, section, note="note" in row["authority_text"].lower())
        ]
    if scheme == "statute_at_large":
        return "rin-history-labelless-pair", [_stat_emission(title, int(section))]
    return None


def _history_read_volumeless_stat(row, history: _CitationHistory):
    """"Stat. 2936" keeps the Statutes label and loses its volume."""

    match = _HISTORY_VOLUMELESS_STAT.match(_history_normalize(row["authority_text"]))
    if match is None:
        return None
    page = int(match.group("page"))
    volume = _first_level_answer(
        _oracle_levels(row["rin"]),
        lambda key: {v for (v, p) in history.stat.get(key, ()) if p == page},
    )
    if volume is None:
        return None
    return "rin-history-volumeless-stat", [_stat_emission(volume, page)]


def _history_read_public_law_pairs(row, history: _CitationHistory, roster_pairs):
    """"89-670 and 91-605" state both halves of a Public Law and no label.

    Three fences, because the shape has a real competing reading — "89-670"
    could be a section range. The pair must (1) exist in the pinned
    congress.gov roster, (2) be cited BY THIS RULE or its agency elsewhere,
    and (3) meet no competing section reading in the same pool. The reading
    lives in ``public_law_corrected``, never in ``public_law``: the grammar
    read nothing here, the roster did.
    """

    if roster_pairs is None:
        return None
    stripped = _history_normalize(row["authority_text"])
    if not _HISTORY_PL_PAIRS.match(stripped):
        return None
    tokens = _HISTORY_PL_PAIR_TOKEN.findall(stripped)
    # Deliberately NOT routed through ``_first_level_answer``: the fence here
    # is not a survivor count but a conjunction evaluated per member (roster
    # existence AND cited-here AND no competing section reading), and the
    # competing reading refuses outright at the member that meets it. Forcing
    # it into a survivor set would have to invent a survivor for a reading
    # this rule never emits.
    for key in _oracle_levels(row["rin"]):
        competing = history.sections.get(key, set())
        emitted: list[dict[str, object]] = []
        for token in tokens:
            congress, number = token.split("-")
            pair = (int(congress), int(number))
            if congress.lower() in competing or token.lower() in competing:
                return None
            if not (pair in roster_pairs and pair in history.public_law.get(key, ())):
                emitted = []
                break
            emitted.append(
                {
                    "authority_type": "public_law",
                    "public_law_corrected": f"{pair[0]}-{pair[1]}",
                    "pl_correction_evidence": "roster-existent-public-law-pair",
                }
            )
        if emitted:
            return "roster-existent-public-law-pair", emitted
    return None


@dataclass(frozen=True)
class _SplitCitations:
    """One citation the publisher cut at commas across several list slots.

    ``<LEGAL_AUTHORITY_LIST>`` is sometimes a set of independent citations and
    sometimes ONE authority-note sentence line-wrapped into slots, and the
    parser reads one slot at a time — so it never sees that "sec. 939(e)" is
    the tail of "Pub. L. 111-203" one ordinal up. Two independent ledger
    investigations found this shape in six of ten sampled unreadable rows.
    ``ordinal`` has preserved the order all along; nothing read it.

    **The declared convention** is the CFR/FR authority-note grammar
    ``Sec. N, Pub. L. X-Y, V Stat. P``, which the publisher breaks across list
    items in BOTH directions — measured, 112 donors sit before their section
    slot and 49 after — so the rule is stated as *nearest and unique*, never as
    *preceding*. HUD RIN 2501-AD75 is the counter-example that kills the
    preceding form: it states the correct label after the fragment.

    **Three fences, each measured, none decorative.**

    1. *The donor states no section of its own.* A slot that already writes
       "sec 101(g), PL 104-191, 110 Stat 1936" is a WHOLE authority-note
       sentence, not the head of one that got split. Dropping this fence adds
       11 slots / 45 rows, of which at least 9 slots / 43 rows are provably
       wrong — they are code continuations, not enactment sections: 12 U.S.C.
       1831n at FRB 7100-AF03, 29 U.S.C. 1185b at EBSA 1210-AB55, 22 U.S.C.
       287c at State 1400-AD41, 8 U.S.C. 1357(a)(1) at ETA 1205-AC18. Each was
       read off the row, not off a rate.
    2. *The donor's congress is inside the numbered series, dated to the
       edition.* Wave 5 measured what an undated roster does; ``_SeriesCalendar``
       is what dates it.
    3. *The run's own value has no competing public-law-pair reading.* "PL
       89-564 / 89-670 / 91-605 / 93-87" at FMCSA 0702-AA43 is a LIST OF LAWS,
       and every member tokenises as a hyphenated section. ``_HISTORY_PL_PAIRS``
       is the same shape ``roster-existent-public-law-pair`` reads, so the
       competing reading is named rather than raced.

    Scored against the publisher's own joined spellings — the 16,615 references
    that write a law AND a section in one string, which this rule never sees —
    the answers agree 60/60 at the same RIN and 118/126 at the same agency. All
    eight disagreements are one damaged donor: RIN 0938-AR04 writes "PL 111-48"
    where the Affordable Care Act's sections 1413/2001/2002/2201 need 111-148,
    and the rule faithfully propagates its neighbour's typo. That is the shape
    of this rule's residual risk, and no fence in this tree reaches it: 111-48
    is itself a real law, so the roster cannot refuse it.
    """

    #: (rin, publication_id, ordinal) -> (public law, the sections it states).
    answers: Mapping[tuple[str, str, int], tuple[str, tuple[str, ...]]]
    #: The same key, for runs two different laws bound. Refusing is the answer;
    #: the refusal is counted so it is reported rather than merely absent.
    ambiguities: Mapping[tuple[str, str, int], tuple[str, ...]]

    @classmethod
    def build(cls, authorities) -> _SplitCitations:
        slots: dict[tuple[str, str], dict[int, dict]] = {}
        for row in authorities:
            key = (row["rin"], row["publication_id"])
            slot = slots.setdefault(key, {}).setdefault(
                row["ordinal"],
                {"text": row["authority_text"], "unread": True, "laws": set(),
                 "dated": True, "states_section": False},
            )
            slot["unread"] &= row["authority_type"] == "other"
            if row["public_law"] is not None:
                slot["laws"].add(row["public_law"])
                slot["dated"] &= bool(row["pl_congress_in_series"])
            slot["states_section"] |= bool(row["stated_section"])

        answers: dict[tuple[str, str, int], tuple[str, tuple[str, ...]]] = {}
        ambiguities: dict[tuple[str, str, int], tuple[str, ...]] = {}
        for (rin, publication_id), by_ordinal in slots.items():
            ordinals = sorted(by_ordinal)
            sections = {
                ordinal: cls._section_run(by_ordinal[ordinal]) for ordinal in ordinals
            }
            start = 0
            while start < len(ordinals):
                if sections[ordinals[start]] is None:
                    start += 1
                    continue
                end = start
                while end + 1 < len(ordinals) and sections[ordinals[end + 1]] is not None:
                    end += 1
                donors: set[str] = set()
                for bound in (start - 1, end + 1):
                    if 0 <= bound < len(ordinals):
                        donors |= cls._donor_laws(by_ordinal[ordinals[bound]])
                for ordinal in ordinals[start:end + 1]:
                    tokens = tuple(sections[ordinal])
                    if len(donors) == 1:
                        answers[(rin, publication_id, ordinal)] = (next(iter(donors)), tokens)
                    elif len(donors) > 1:
                        ambiguities[(rin, publication_id, ordinal)] = tokens
                start = end + 1
        return cls(answers, ambiguities)

    @staticmethod
    def _section_run(slot: Mapping[str, object]) -> list[str] | None:
        """The slot's section tokens, if it is nothing but a bare section list."""

        if not slot["unread"]:
            return None
        text = str(slot["text"])
        if _HISTORY_PL_PAIRS.match(_history_normalize(text)):
            return None  # fence 3: the competing public-law-pair reading
        return _history_section_tokens(text)

    @staticmethod
    def _donor_laws(slot: Mapping[str, object]) -> set[str]:
        """The public law this slot can donate to a run it bounds, if any."""

        if not slot["laws"] or not slot["dated"]:
            return set()  # fence 2: nothing, and nothing out of its own calendar
        if slot["states_section"]:
            return set()  # fence 1: a whole authority-note sentence donates nothing
        return set(slot["laws"])


def _read_split_public_law(row, splits: _SplitCitations, history: _CitationHistory, tally: _Tally):
    """The bare section a neighbouring slot's Public Law completes.

    The fourth fence lives here rather than in the index, because it needs the
    other oracle: where the publisher's OWN resolved citations already bind one
    of the run's sections to a DIFFERENT Public Law, the donor is not the only
    reading available and this rule does not get to choose. It is the same
    competing-reading fence ``roster-existent-public-law-pair`` carries, and it
    was adopted on a measurement rather than on principle -- scored against the
    joined spellings before it existed, the rule wrote 109 rows and disagreed
    on 10 of the 15 the key could judge, in exactly two families:

    - CMS RIN 0938-AR04 states "PL 111-48" where the Affordable Care Act's
      sections 1413/2001/2002/2201 need 111-148, and the rule propagated its
      neighbour's typo. The roster cannot refuse this -- 111-48 is a real law.
    - CMS RIN 0938-AR64 reads "1814(i) (2)" as a section of the PL 111-148 two
      slots down, when its own sibling slot says "1814(i) (1) OF THE ACT": it
      is a Social Security Act section, and the public law beside it is a
      separate authority.

    This fence refuses both, costs 18 rows, and costs nothing else -- every
    dropped row is inside those two families. Note what that does to the score
    that licensed it: the pool it consults is built from the same joined
    spellings the hold-out is scored against, so a post-fence disagreement is
    no longer POSSIBLE at the rows the pool covers. The number worth reading is
    the pre-fence one above; the invariant worth testing is that no row this
    rule writes contradicts the publisher's own joined spelling.
    """

    key = (row["rin"], row["publication_id"], row["ordinal"])
    if key in splits.ambiguities:
        tally.split_run_ambiguities += 1
        return None
    answer = splits.answers.get(key)
    if answer is None:
        return None
    public_law, tokens = answer
    sections = {_history_bare(token) for token in tokens}
    for level in _oracle_levels(row["rin"]):
        bound = {
            law
            for (law, section) in history.public_law_sections.get(level, ())
            if section in sections
        }
        if bound and bound != {public_law}:
            tally.split_run_pool_conflicts += 1
            return None
    return "list-run-bounding-public-law", [
        _public_law_section_emission(
            public_law, _history_stated(token), "list-run-bounding-public-law"
        )
        for token in tokens
    ]


@dataclass
class _Tally:
    """The counts the receipt declares.

    Carried as fields on one object rather than as four single-element lists
    threaded through call sites, which is what they were.
    """

    fuzzy_act_rows: int = 0
    prefix_act_rows: int = 0
    corroborated_rows: int = 0
    #: Resolutions the calendar refused: an act named with a year later than
    #: the edition citing it.
    anachronisms: int = 0
    #: Rows the split-citation rule refused because the run of bare sections
    #: was bounded by two different Public Laws. A refusal is an answer and is
    #: counted like one, so "the rule found nothing here" and "the rule found
    #: two things and would not choose" never read the same in the receipt.
    split_run_ambiguities: int = 0
    #: Rows it refused for the other reason: the publisher's own resolved
    #: citations bind one of the run's sections to a different Public Law. Two
    #: refusal reasons, two counters, because they say different things about
    #: the data -- the first is a list this rule cannot read, the second is a
    #: neighbour this rule should not believe.
    split_run_pool_conflicts: int = 0
    #: The scheme-label rule's refusals, by the fence that spoke. Five reasons
    #: rather than one number, because "no oracle affirmed anything" and "the
    #: label already stands in the residue" are different facts about the
    #: corpus, and a fence that stops firing has to break a pin instead of
    #: quietly widening the rule.
    scheme_label_refusals: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(SCHEME_LABEL_REFUSALS, 0)
    )
    #: The pinned initialism roster's refusals, by the fence that spoke. Eight
    #: reasons and not one number, because "this agency has no row" and "the
    #: corpus's own roster is already ambiguous" are opposite facts: the first
    #: is a gap the roster could close and the second is a refusal it must not.
    initialism_roster_refusals: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(INITIALISM_ROSTER_REFUSALS, 0)
    )
    #: Why a slash was not read as a separator between two authorities. Counted
    #: per BOX offered, so the four reasons sum to the boxes this rule looked
    #: at and did not answer.
    slash_refusals: dict[str, int] = field(default_factory=lambda: dict.fromkeys(SLASH_REFUSALS, 0))
    #: Why a span's far end was refused, by the shape that was asked. See
    #: :data:`SPAN_ENDPOINT_REFUSALS`.
    span_endpoint_refusals: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(SPAN_ENDPOINT_REFUSALS, 0)
    )


def _apply_corroboration(
    row, rule: str, emissions, tally: _Tally, calendar: _SeriesCalendar
) -> list[dict[str, object]]:
    """Write one corroborated reading onto a row -- the ONE place that does.

    Every rule in ``CORROBORATION_RULES`` lands here, which is what makes two
    column invariants structural instead of coincidental: ``parse_status`` is
    "corroborated" exactly where ``corroboration_rule`` is set, and a reading
    that names several places explodes into one row per place, the copies
    sitting beside the row they explode (the executive-order-plural rule).

    Four passes each re-implemented this before it was written down once, and
    they did not agree: three cleared the statement their resolution replaced
    and the fourth did not, which is how 147 rows came to carry both an
    ``act_key`` and a ``stated_section``.
    """

    extras: list[dict[str, object]] = []
    for index, emission in enumerate(emissions):
        target = row if index == 0 else dict(row)
        target["parse_status"] = "corroborated"
        target["corroboration_rule"] = rule
        target.update(emission)
        # The third invariant, and the reason the calendar is threaded here: a
        # corroborated reading is judged against the same dated series as a
        # grammar-read one. The emission names a place; only this call site
        # knows which edition is doing the citing.
        target["usc_title_is_possible"] = calendar.usc_title_is_possible(
            target["usc_title"], target["publication_id"]
        )
        target["stat_volume_in_series"] = calendar.stat_volume_in_series(
            target["statute_volume"], target["publication_id"]
        )
        if index:
            extras.append(target)
        tally.corroborated_rows += 1
    return extras


def _corroborate(
    authorities, readers, tally: _Tally, calendar: _SeriesCalendar
) -> list[dict[str, object]]:
    """One sweep over the failed pool, one applicator, one declared order.

    A reader answers ``(rule, emissions)`` or refuses with None, and the first
    that answers claims the row -- so the order of ``readers`` IS the priority
    of the rules, declared as an object rather than left implicit in the
    statement order of four separate sweeps. The shapes are disjoint in the
    measured corpus; the order is what makes that a stated fact rather than a
    hope.

    Only a row that read NOTHING is offered, and that fence is the most
    expensive one here. A row that already read a citation states BOTH -- "7
    USC 1621 to 1627 Agricultural Marketing Act" is a USC citation that also
    names its act -- and relabelling it act_relative would throw the citation
    away. Without this filter the index-holds rule fired on partial rows and
    relabelled 7,069 real U.S.C. and CFR citations; a rule returning eighty
    times its measured population is a defect signal, not a success.
    """

    rebuilt: list[dict[str, object]] = []
    for row in authorities:
        rebuilt.append(row)
        if row["authority_type"] != "other" or row["parse_status"] != "failed":
            continue
        for reader in readers:
            reading = reader(row)
            if reading is None:
                continue
            rebuilt.extend(_apply_corroboration(row, reading[0], reading[1], tally, calendar))
            break
    return rebuilt


def _number_citations(authorities: list[dict[str, object]]) -> list[dict[str, object]]:
    """Number every row within its publisher reference, in emission order.

    The receipt has always said rows sharing (rin, publication_id, ordinal) are
    "distinguished by citation_ordinal", and that is only true if ONE place
    writes the column. Two did: the parse loop numbered the citations a
    reference names, and then ``_apply_corroboration`` exploded a single failed
    row into several readings that every one of them kept the base row's
    number. 632 rows over 194 keys were indistinguishable that way, and every
    single one was a corroboration explosion -- EPA RIN 2060-AF87's "CAA
    section 202,203,247, 301(a)" came out as four rows all numbered 0.

    Numbering here, after every row exists and in the order they were emitted,
    is what makes the declared key unique BY CONSTRUCTION rather than by luck.
    A row's number is its position among the citations its reference yielded,
    which is what the contract says it is.
    """

    counts: dict[tuple[object, object, object], int] = {}
    for row in authorities:
        key = (row["rin"], row["publication_id"], row["ordinal"])
        row["citation_ordinal"] = counts.get(key, 0)
        counts[key] = row["citation_ordinal"] + 1
    return authorities


#: The seven columns the section fence writes. Listed so the emission below can
#: null them on every row in one statement: a column set on some rows and
#: absent from others is the missing key
#: ``dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)`` exists to prevent.
#:
#: The first three are written by TWO passes over two disjoint populations --
#: :func:`_judge_usc_sections` on ``authority_type = 'usc'`` rows and
#: :func:`_judge_act_derived_sections` on the act-relative rows the resolver
#: filled -- through one writer, :func:`_write_section_verdict`. The four
#: correction columns have one pass and one population: a correction repairs
#: what a filer typed, and an act-derived section was not typed.
_USC_SECTION_COLUMNS: tuple[str, ...] = (
    "usc_section_verdict",
    "usc_section_verdict_reason",
    "usc_section_attested_at_edition",
    "usc_section_corrected",
    "usc_section_correction_evidence",
    "usc_section_corrected_section",
    "usc_section_corrected_pinpoint",
)

#: The six columns the recodification tables write, kept apart from the seven
#: above because they are a different source answering a different question:
#: the fence says whether the oracle can see the section, and these say what an
#: Act did with it. Nulled in the same statement, for the same reason.
_USC_DISPOSITION_COLUMNS: tuple[str, ...] = (
    "usc_disposition_verdict",
    "usc_disposition_successors",
    "usc_disposition_table",
    "usc_disposition_span_members",
    "usc_disposition_pinpoint",
    "usc_disposition_refusal",
)

#: The one refusal the disposition block publishes, named once so the writer,
#: the census and the contract cannot drift apart. See
#: :func:`~refspec.registry.citation_grammar.usc_token_is_chapter_qualified`
#: and the guard in :func:`_judge_usc_sections`.
CHAPTER_QUALIFIED_REFUSAL = "chapter_qualifier_governs_the_token"


def _judge_usc_section_magnitudes(authorities: list[dict[str, object]]) -> int:
    """Write the corpus's own magnitude verdict on every row, and count the Falses.

    The ceiling has to be derived HERE rather than pinned: it is the 99th
    percentile of the section stems each title attests **in this build**, times
    ten, so a build with different rows gets a ceiling from those rows. Pinning
    a number computed over one artifact and applying it to the next is the
    stale-oracle failure this module refuses everywhere else.

    Weighted by ROWS, which is the heuristic's own weakness on display: over
    distinct citations, 33 U.S.C. 70116 and 70034 sit inside title 33's top one
    percent and help set the ceiling meant to catch them.
    """

    counted: dict[tuple[int, str], int] = {}
    for row in authorities:
        title, section = row["usc_title"], row["usc_section"]
        if title is not None and section:
            counted[(title, section)] = counted.get((title, section), 0) + 1
    ceilings = usc_section_ceilings((title, section, rows) for (title, section), rows in counted.items())
    # Judged once per distinct citation and then read off, the same shape the
    # section oracle's memos take: the verdict is a fact about the pair.
    verdicts = {
        pair: usc_section_magnitude_is_plausible(pair[0], pair[1], ceilings) for pair in counted
    }
    implausible = 0
    for row in authorities:
        title, section = row["usc_title"], row["usc_section"]
        verdict = verdicts.get((title, section)) if title is not None and section else None
        row["usc_section_magnitude_is_plausible"] = verdict
        implausible += verdict is False
    return implausible


@dataclass(frozen=True)
class _UscSectionCensus:
    """What the section fence said over the whole table, for the receipt.

    Rows, distinct texts, distinct ``(title, section, appendix)`` pairs and
    distinct RINs, because the oracle report counts all four and a defect that
    is one row across 2,000 RINs is a different animal from 2,000 rows in one.
    A text can carry citations of more than one verdict, so the per-verdict
    text counts do not sum to the corpus's distinct texts.
    """

    rows_by_verdict: Mapping[str, int]
    texts_by_verdict: Mapping[str, int]
    pairs_by_verdict: Mapping[str, int]
    rins_by_verdict: Mapping[str, int]
    unknown_rows_by_reason: Mapping[str, int]
    #: ``exists`` and the citing edition did not print it. Era mismatch, not a
    #: misread -- counted beside the verdict rather than folded into it.
    exists_not_at_edition_rows: int
    #: C0: the edition could not have cited the title at all, so no section
    #: question is asked. Counted, or the rows would leave the census silently.
    title_impossible_rows: int
    #: Typed ``usc`` and naming no section: nothing to judge.
    not_stated_rows: int
    corrected_rows_by_rule: Mapping[str, int]
    #: Of those, the rows whose corrected IDENTITY is not the parsed
    #: ``usc_section`` -- the keys a consumer keying on the correction would
    #: move off the section the citation names. The exposure measurement that
    #: asked for the split asked for this number by rule, because the rules do
    #: not carry the same risk: A4 moves an identity the Code does not print
    #: (``371a``), where B8 moves one it does (``18`` -> ``18a``).
    identity_moved_rows_by_rule: Mapping[str, int]
    #: Where more than one reading survived, keyed by the surviving rules'
    #: family codes joined with "+" ("A4+parse"), the oracle report's own
    #: spelling. A refusal is an answer and is counted like one. "parse" alone
    #: is the fourth shape and not a refusal of anything: both survivors are
    #: the parse as filed, at two pinpoint depths of one citation, so there is
    #: nothing to correct.
    refusal_rows_by_survivors: Mapping[str, int]
    #: The recodification tables' own census, over the rows the fence refuses
    #: for :data:`~refspec.registry.usc_section_oracle.DISPOSITION_REASON` and
    #: over no others. Rows and distinct ``(title, section, appendix)`` pairs
    #: per verdict, because "the table misses 27 of 146 sections" and "the
    #: table misses 177 of 2,548 rows" are different sentences and only the
    #: pair count says which sections are one-off damage. Every declared
    #: verdict is listed at zero: a verdict that stops being reached is the
    #: thing a census exists to keep visible.
    disposition_rows_by_verdict: Mapping[str, int]
    disposition_pairs_by_verdict: Mapping[str, int]
    #: Rows by HOW MANY successors the table named, keyed by the count as a
    #: string. This is the number that decides how a consumer may publish the
    #: column: everything above "1" is a set of candidates the printed prose
    #: separates and no machine here does.
    disposition_rows_by_successor_count: Mapping[str, int]
    #: Rows whose citation stated a SPAN the table was asked over, and the
    #: distinct spans behind them. Counted apart from the verdicts because a
    #: span row's successors are a union over members and a section row's are
    #: one section's -- a consumer that cannot tell them apart would read the
    #: union as one section's answer.
    disposition_span_rows: int
    disposition_spans: int
    #: Span rows the ABBREVIATED span rule produced, which are asked about the
    #: start section alone and never expanded. Zero in the pinned build, and
    #: kept at zero visibly: an abbreviated span is this module's reading of
    #: "1421-31", not the filer's statement of a range, and 5 of the 68
    #: abbreviated tokens in the corpus expand to spans whose members are
    #: mostly not law (see AuthorityCitation.usc_section_span_rule).
    disposition_abbreviated_span_rows: int
    #: Rows whose citation stated a pinpoint, and the subset where the table
    #: RESOLVED it and the answer is therefore narrower than the bare
    #: section's. The gap between them is the rows where the table knows the
    #: section and not that subsection, which come back unnarrowed on purpose.
    disposition_pinpoint_rows: int
    disposition_pinpoint_resolved_rows: int
    #: Rows the guard refused to read a table for, by refusal code, and the
    #: distinct ``(title, section, appendix)`` pairs behind them.
    disposition_refusal_rows: Mapping[str, int]
    disposition_refusal_pairs: Mapping[str, int]


@dataclass(frozen=True)
class _ActNumbering:
    """Which acts' OWN section numbers a row may be read against.

    The section fence's one corpus-side input. An act's numbering is not the
    Code's -- Commodity Exchange Act §8a is 7 U.S.C. 12a -- so a filer writing
    the Act's number under a "7 USC" label produces a token that A4 reads as a
    lost parenthesis and publishes at the wrong section. The oracle owns what
    to do with a claim; this owns WHICH claims a row may see, which is a fact
    about the corpus and not about the Code.

    The two altitudes are :class:`_ActOracles`'s, verbatim and for the same
    measured reason: the RIN's own resolved acts, then the filing agency's,
    never the corpus's. Corpus-wide, two acts number a §8a into title 7 (the
    Commodity Exchange Act -> 12a and the A.A.A. Farm Relief and Inflation Act
    -> 608a) and only the CFTC's own roster picks one.

    **Both sides of the join are normalised, and that is not tidiness.**
    ``ActIndex.classifications`` is keyed by the act section as Table III
    PRINTS it, and 12,549 of its 75,596 distinct spellings are not what
    :func:`normalize_section` produces -- ``745A``, ``10B``. A row's token
    arrives folded, so looking the raw key up with a folded token finds nothing
    and the fence would under-fire silently on every act that capitalises. The
    normalised join is built once, here, into :attr:`targets`.

    685k U.S.C. rows ask :meth:`claims` this question; a row's whole cost is
    one dict miss per act on its own roster, and the rosters hold single digits
    of acts (the CFTC's holds three). Measured 0.6 s over rebuild #9's 687,283
    U.S.C. rows, against a 97 s build.
    """

    keys_by_rin: Mapping[str, set[str]]
    keys_by_agency: Mapping[str, set[str]]
    #: ``(Table III key, folded act section)`` -> the Code sections it names,
    #: already restricted to a numeric title and a section that is NOT the act
    #: section itself. Where an act's number and the Code's agree there is no
    #: second numbering system to be confused by, so such a row is not a claim
    #: and never enters this map.
    targets: Mapping[tuple[str, str], tuple[tuple[int, str], ...]]
    #: Popular name -> Table III key, resolved through the index's own alias
    #: chain once per name rather than once per row.
    key_by_name: Mapping[str, str | None]

    @classmethod
    def build(
        cls,
        index: ActIndex | None,
        keys_by_rin: Mapping[str, set[str]],
        keys_by_agency: Mapping[str, set[str]],
    ) -> _ActNumbering | None:
        if index is None:
            return None
        targets: dict[tuple[str, str], set[tuple[int, str]]] = {}
        for act_key, sections in index.classifications.items():
            for act_section, rows in sections.items():
                token = normalize_section(act_section)
                if not token:
                    continue
                for one in rows:
                    section = normalize_section(one.usc_section)
                    if not section or section == token or not str(one.usc_title or "").isdigit():
                        continue
                    targets.setdefault((act_key, token), set()).add((int(one.usc_title), section))
        names = {name for keys in (*keys_by_rin.values(), *keys_by_agency.values()) for name in keys}
        return cls(
            keys_by_rin=keys_by_rin,
            keys_by_agency=keys_by_agency,
            targets={key: tuple(sorted(named)) for key, named in targets.items()},
            key_by_name={
                name: index.table3_key_by_name.get(resolve_act_name(name, index) or "") for name in names
            },
        )

    def claims(self, rin: str, title: int, section: str) -> tuple[ActSectionClaim, ...]:
        """Every associated act that numbers ``section`` itself, narrowest first.

        Both levels are returned, not just the first that answers: the oracle's
        fence refuses on two readings and must see both, and the RIN's roster
        is a subset of its agency's, so a claim reachable at both is one claim
        named at the narrower level.
        """

        token = normalize_section(section)
        if not token:
            return ()
        out: dict[tuple[str, str], ActSectionClaim] = {}
        for association, keys in (
            ("rin", self.keys_by_rin.get(rin, ())),
            ("agency", self.keys_by_agency.get(rin[:4], ())),
        ):
            for name in sorted(keys):
                key = self.key_by_name.get(name)
                if key is None:
                    continue
                for named_title, named_section in self.targets.get((key, token), ()):
                    if named_title != title:
                        continue
                    out.setdefault(
                        (key, named_section),
                        ActSectionClaim(
                            act=name,
                            act_key=key,
                            act_section=token,
                            title=title,
                            section=named_section,
                            association=association,
                        ),
                    )
        return tuple(out[key] for key in sorted(out))


def _write_section_verdict(
    row: dict[str, object],
    oracle: UscSectionOracle,
    memo: dict[tuple[int, str, bool, int | None], SectionVerdict],
) -> tuple[tuple[int, str, bool], SectionVerdict]:
    """Ask the oracle about this row's section AT ITS EDITION, and write the three.

    ONE writer for ``usc_section_verdict`` / ``_reason`` /
    ``_attested_at_edition``, called from both fences: the one that judges what
    a filer wrote under a U.S.C. label (:func:`_judge_usc_sections`) and the one
    that judges the section an act resolution filled
    (:func:`_judge_act_derived_sections`). Extracted rather than copied, because
    two spellings of "the edition's year" or two memo keys would be two dated
    verdicts wearing one column's name.

    The memo is the caller's: the two fences ask about different populations
    (95k distinct keys against 1.7k) and a shared dict would make either one's
    cost unreadable.
    """

    # The same spelling of "the edition's year" every dated verdict in this
    # module uses, rather than a second one that could drift from it.
    year = _SeriesCalendar._edition_year(row["publication_id"])
    pair = (row["usc_title"], normalize_section(row["usc_section"]), bool(row["usc_appendix"]))
    key = (*pair, year)
    verdict = memo.get(key)
    if verdict is None:
        verdict = oracle.section_verdict(pair[0], pair[1], year, appendix=pair[2])
        memo[key] = verdict
    row["usc_section_verdict"] = verdict.verdict
    row["usc_section_verdict_reason"] = verdict.reason
    row["usc_section_attested_at_edition"] = verdict.attested_at_edition
    return pair, verdict


#: Why a span's far end was refused. Two shapes, and both are shapes the
#: GRAMMAR cannot judge because the section oracle imports it -- which is the
#: arrangement ``_abbreviated_span``'s own docstring names when it says "a
#: reader that HOLDS an oracle should re-type these there". This is that
#: reader.
SPAN_ENDPOINT_REFUSALS: tuple[str, ...] = (
    #: An end this module INFERRED out of an abbreviation, where the Code
    #: prints no such section. "7 USC 77701 to 7772" expands to §§77701-77772
    #: of title 7 -- 72 sections, none of them law, out of a filer's stutter on
    #: "7701" -- and "49 USC 440113 to 40114" the same. The six spans the
    #: grammar's docstring already named as phantoms are refused here too:
    #: 16 U.S.C. 4601-4631 (8 of 31 real), 4602-4631 (7 of 30), 42 U.S.C.
    #: 105-133 (6 of 29), 26 U.S.C. 1502-1513 (4 of 12), 42 U.S.C. 3007-3011
    #: (1 of 5) and 8 U.S.C. 81611-81613 (0 of 3).
    "an-inferred-end-the-code-does-not-print",
    #: A COMPOUND end the filer stated, where the Code prints no such section.
    #: "16 U.S.C. 460k to 460k-4" is the Refuge Recreation Act entire and its
    #: end is law; "16 USC 406k to 406k-4" is the same citation with a
    #: transposed stem and neither end is law. A compound token is the one
    #: endpoint shape the grammar cannot tell from a section's NAME, which is
    #: why this one is asked and a plain stated end is not.
    "a-compound-end-the-code-does-not-print",
)


def _refuse_unprintable_span_ends(authorities, oracle, tally: _Tally):
    """Null a span's far end where the Code prints no such section.

    **A PLAIN STATED END IS NEVER ASKED**, and that is measured rather than
    cautious: 3,048 rows over 321 distinct spans state an end the oracle does
    not enumerate, and they are overwhelmingly REPEALED law the filer cited on
    purpose -- 18 U.S.C. 5006 to 5024 (the Youth Corrections Act, repealed in
    1984, and several of those values say so in their own text), 18 U.S.C.
    4161 to 4166, 18 U.S.C. 4201 to 4218. The oracle's coverage begins long
    after those sections left the Code, so "not enumerated" there means "before
    our evidence", not "never law". Asking of every end would delete 3,048 real
    citations to catch two phantoms.

    What IS asked is the two shapes where the module itself supplied or
    disambiguated the end. Both are named in :data:`SPAN_ENDPOINT_REFUSALS`.
    """

    if oracle is None:
        return
    for row in authorities:
        end = row.get("usc_section_end")
        if not end or row.get("usc_title") is None:
            continue
        inferred = row.get("usc_section_span_rule") == USC_SPAN_ABBREVIATED
        if not inferred and "-" not in str(end):
            continue
        appendix = bool(row.get("usc_appendix"))
        if all(
            oracle.section_is_enumerated(row["usc_title"], section, appendix=appendix)
            for section in (row["usc_section"], end)
        ):
            continue
        tally.span_endpoint_refusals[
            "an-inferred-end-the-code-does-not-print"
            if inferred
            else "a-compound-end-the-code-does-not-print"
        ] += 1
        row["usc_section_end"] = None
        row["usc_section_span_rule"] = None
        # AND THE STATUS COMES DOWN WITH IT. "ok" means the module accounts for
        # the whole string, and a row whose endpoint has just been refused does
        # not: "43 USC 270-1 to 270-3" read "ok" while carrying no end, so a
        # consumer filtering on status would have walked past the refusal
        # without seeing it. This is the same sentence
        # ``parse_authority_citation`` writes for an expanded span, applied
        # where the refusal happens rather than where the reading did.
        if row.get("parse_status") == "ok":
            row["parse_status"] = "partial"


def _judge_usc_sections(
    authorities: list[dict[str, object]],
    oracle: UscSectionOracle | None,
    act_numbering: _ActNumbering | None = None,
) -> _UscSectionCensus:
    """Write the section verdict and its correction on every U.S.C. row.

    One decider: every verdict, every reason and every correction here is the
    oracle's, asked through its public API and never re-derived. What this
    function adds is the corpus context the oracle cannot have -- which edition
    made the citation, and what the builder's own dated title verdict says.

    **C0 outranks the section question.** ``usc_title_is_possible`` is the
    builder's, and it is EDITION-DATED where the oracle's own
    ``c0_title_impossible`` is not: "54 USC 4118" filed in 2004 names a title
    enacted in 2014. The oracle's predicate takes the builder's verdict as
    ``stated_possible`` and lets it win, which is the whole gap between the
    module's 29 pairs and the report's 31 (52 USC 7602 and 54 USC 4118, 2 pairs
    / 5 rows). A row whose title the edition could not cite is left UNJUDGED --
    ``usc_title_is_possible`` already states the fault, and an absence verdict
    on top of it would say the section is missing from a title that is not
    there to miss it.

    **Two memos, and why those keys.** A verdict depends on
    ``(title, section, appendix, edition_year)`` and a correction on
    ``(title, section, authority_text, act-section claims)`` -- 95,492 and
    38,218 distinct keys over the 685,431 U.S.C. rows the oracle report
    measured, 95,107 and 38,182 over the 685,268 of that build. The claims join
    the correction key on 2026-08-24 and cost 118 keys: over rebuild #9's
    687,283 U.S.C. rows the correction memo is 38,892 keys without them and
    39,010 with, because 26,818 rows carry a claim tuple and the same
    ``(title, section, text)`` can reach two agencies with two rosters. They
    are IN the key rather than filtered after it for exactly that reason -- a
    memo keyed without them would publish whichever agency asked first (see
    :class:`_ActNumbering`).  That is the difference between asking the
    oracle seven times per answer and once: measured A/B on the same machine,
    the whole fence costs 13.6-16.9 s on a 97 s build, and about 8 s of that is
    the oracle's own range scan for the years an edition attests. The
    edition year is not a correction key because every Agenda edition
    (1995-10 … 2025-10) lies inside the oracle's 1994-2026 window, which is the
    only thing it could change there -- and the receipt's
    ``edition_outside_oracle_window`` count staying zero is what holds that
    true.

    **A THIRD memo, keyed one narrower.** The recodification tables are asked
    per ``(title, section, subsection, section_end, appendix)`` and never per
    edition -- what Pub. L. 103-272 did in 1994 is not a fact about the year a
    filer cited it -- so the memo lives on the oracle
    (``UscSectionOracle.disposition``) where that key is the whole key. The
    same 146 sections are cited across thirty editions in this corpus; a year
    in the key would ask the same table thirty times.

    Only ``usc_section`` is judged. A range row carries its far end in
    ``usc_section_end`` and no verdict speaks for it; the oracle report
    measured the corpus the same way. **The recodification table beside the
    verdict is asked differently**, and 2026-08-24 is when it started to be:
    a citation that states a span states it about every section in the range,
    and a citation that states a pinpoint states it about one subsection, so
    the table is asked over ``usc_section_end`` and under the pinpoint the
    grammar reads back out of ``authority_text``. Both are the CITATION's own
    words -- nothing is expanded, inferred or carried from a sibling -- and
    both leave the section verdict exactly where it was.
    """

    verdicts: dict[tuple[int, str, bool, int | None], SectionVerdict] = {}
    corrections: dict[tuple[int, str, str, tuple[ActSectionClaim, ...]], tuple[object, str | None]] = {}
    rows_by_verdict: dict[str, int] = dict.fromkeys(VERDICTS, 0)
    texts_by_verdict: dict[str, set[str]] = {verdict: set() for verdict in VERDICTS}
    pairs_by_verdict: dict[str, set[tuple[int, str, bool]]] = {verdict: set() for verdict in VERDICTS}
    rins_by_verdict: dict[str, set[str]] = {verdict: set() for verdict in VERDICTS}
    unknown_rows: dict[str, int] = dict.fromkeys(UNKNOWN_REASONS, 0)
    corrected_rows: dict[str, int] = {rule: 0 for rule in CORRECTION_RULES if rule != "parse-as-filed"}
    identity_moved_rows: dict[str, int] = dict.fromkeys(corrected_rows, 0)
    refusal_rows: dict[str, int] = {}
    disposition_rows: dict[str, int] = dict.fromkeys(DISPOSITION_VERDICTS, 0)
    disposition_pairs: dict[str, set[tuple[int, str, bool]]] = {name: set() for name in DISPOSITION_VERDICTS}
    disposition_by_count: dict[int, int] = {}
    disposition_spans: set[tuple[int, str, str]] = set()
    disposition_refusal_rows: dict[str, int] = {CHAPTER_QUALIFIED_REFUSAL: 0}
    disposition_refusal_pairs: dict[str, set[tuple[int, str, bool]]] = {CHAPTER_QUALIFIED_REFUSAL: set()}
    #: The rows the guard's row-local half accepted, held back until the loop
    #: has written every sibling's verdict -- the record-wide half reads them.
    guard_candidates: list[tuple[dict[str, object], tuple[int, str, bool], object]] = []
    span_rows = abbreviated_span_rows = pinpoint_rows = pinpoint_resolved_rows = 0
    exists_not_at_edition = title_impossible = not_stated = 0

    def publish(row: dict[str, object], pair: tuple[int, str, bool], moved: object) -> None:
        """Write one table answer onto a row, and count it. ONE writer."""

        # De-duplicated on the ADDRESS, so two printed rows that differ only by
        # a pinpoint into the same successor ("308(e)" beside "308") are one
        # entry: this column is addresses, and the pinpoint lives in the
        # table's own printed text where it can be read.
        successors = list(dict.fromkeys(f"{one.title}:{one.section}" for one in moved.successors))
        row["usc_disposition_verdict"] = moved.verdict
        row["usc_disposition_successors"] = successors or None
        row["usc_disposition_table"] = moved.recodification
        # The members are written only where the answer is a UNION over them.
        # A one-section answer says so by leaving this NULL rather than by
        # restating the section a consumer already has in usc_section.
        row["usc_disposition_span_members"] = list(moved.covers) if moved.members else None
        row["usc_disposition_pinpoint"] = (
            "".join(f"({label})" for label in moved.subsection) if moved.subsection_resolved else None
        )
        disposition_rows[moved.verdict] += 1
        disposition_pairs[moved.verdict].add(pair)
        disposition_by_count[len(successors)] = disposition_by_count.get(len(successors), 0) + 1

    for row in authorities:
        for column in (*_USC_SECTION_COLUMNS, *_USC_DISPOSITION_COLUMNS):
            row[column] = None
        title, section = row["usc_title"], row["usc_section"]
        if oracle is None or row["authority_type"] != "usc" or title is None:
            continue
        if section is None:
            not_stated += 1
            continue
        if oracle.c0_title_impossible(title, stated_possible=row["usc_title_is_possible"]):
            title_impossible += 1
            continue

        pair, verdict = _write_section_verdict(row, oracle, verdicts)
        rows_by_verdict[verdict.verdict] += 1
        texts_by_verdict[verdict.verdict].add(row["authority_text"])
        pairs_by_verdict[verdict.verdict].add(pair)
        rins_by_verdict[verdict.verdict].add(row["rin"])
        if verdict.reason is not None:
            unknown_rows[verdict.reason] += 1
        if verdict.exists and verdict.attested_at_edition is False:
            exists_not_at_edition += 1

        # The recodification tables, gated by the verdict above: the oracle
        # attaches a disposition only beside the one unknown a pinned table
        # speaks into, so nothing here decides which rows are ASKED -- the
        # fence already did, and its reason code is what the census below
        # closes against. What this block decides is what to ask, and no
        # single-valued correction is minted either way: usc_section_corrected
        # is written further down from the oracle's own Correction and never
        # from this. The section verdict and its reason do not move; the only
        # values that do are these six columns' own.
        if verdict.disposition is not None:
            # What ELSE the citation stated about the same token. A span is
            # taken only where the publisher WROTE the range ("stated"): the
            # abbreviated rule is this module's reading of "1421-31", and
            # AuthorityCitation.usc_section_span_rule carries the measurement
            # that says an expanded span can claim sections that are not law.
            stated_span = row["usc_section_end"] if row["usc_section_span_rule"] == USC_SPAN_STATED else None
            if row["usc_section_end"] is not None and stated_span is None:
                abbreviated_span_rows += 1
            stated_pinpoint = usc_section_pinpoint(row["authority_text"], section)
            moved = verdict.disposition
            if stated_span is not None or stated_pinpoint is not None:
                # The bare answer above is the memoised one the verdict
                # carries; this asks the same table the citation's own fuller
                # question. Same oracle, same memo, one key wider.
                moved = oracle.disposition(
                    pair[0], pair[1], appendix=pair[2], subsection=stated_pinpoint, section_end=stated_span
                )
            if stated_span is not None:
                span_rows += 1
                disposition_spans.add((pair[0], pair[1], normalize_section(stated_span)))
            if stated_pinpoint is not None:
                pinpoint_rows += 1
                pinpoint_resolved_rows += bool(moved.subsection_resolved)
            # The guard's row-local half: the citation writes "ch" over a list
            # and the token is a CURRENT chapter of the title, while the row's
            # own usc_appendix says the parser never read it as an appendix
            # citation. Held back -- the record-wide half needs verdicts this
            # loop has not written yet.
            if (
                not pair[2]
                and (pair[0], pair[1]) in oracle.chapters
                and usc_token_is_chapter_qualified(row["authority_text"], section)
            ):
                guard_candidates.append((row, pair, moved))
            else:
                publish(row, pair, moved)

        text = row["authority_text"]
        # The claims are part of the KEY, not a filter after it: which acts a
        # row may be read against is the filing agency's fact, so two agencies
        # writing one string can get two answers and a memo keyed without them
        # would publish whichever asked first. In the pinned build all but 8
        # rows resolve to the empty tuple, so the memo is the size it was.
        claims = () if act_numbering is None else act_numbering.claims(row["rin"], pair[0], pair[1])
        answer = corrections.get((pair[0], pair[1], text, claims))
        if answer is None:
            # Both questions, because they are two different answers: which
            # single reading survives (the column), and which readings survived
            # where none may be published (the refusal census). The oracle
            # decides both; asking it twice is what keeps this function from
            # re-deriving the exactly-one-survivor rule for itself.
            candidates = oracle.correction_candidates(pair[0], pair[1], text, act_sections=claims)
            survivors = (
                "+".join(sorted({candidate.rule.split("-")[0] for candidate in candidates}))
                if len(candidates) > 1
                else None
            )
            answer = (oracle.corrected_section(pair[0], pair[1], text, act_sections=claims), survivors)
            corrections[(pair[0], pair[1], text, claims)] = answer
        correction, survivors = answer
        if correction is not None:
            # ONE decider, split two ways: the identity the reading names and
            # the pinpoint the Code's spelling carries. usc_section_corrected
            # is written FROM the pair rather than beside it, so the split
            # cannot drift from the spelling a consumer already reads.
            identity = correction.section
            pinpoint = None if correction.subsection is None else f"({correction.subsection})"
            row["usc_section_corrected_section"] = identity
            row["usc_section_corrected_pinpoint"] = pinpoint
            row["usc_section_corrected"] = identity + (pinpoint or "")
            row["usc_section_correction_evidence"] = correction.rule
            corrected_rows[correction.rule] += 1
            if normalize_section(identity) != pair[1]:
                identity_moved_rows[correction.rule] += 1
        elif survivors is not None:
            refusal_rows[survivors] = refusal_rows.get(survivors, 0) + 1

    # The guard's RECORD-WIDE half, and the reason it runs here: a chapter
    # number and a former section number are the same characters, so the
    # question "did this filer mean the Code as it stands" cannot be answered
    # from the token. The record answers it. A record that cites a section the
    # oracle prints TODAY, or a chapter the register holds today, is citing
    # current law, and a bare number under a "ch" in such a record is a chapter
    # the parse handed on without its qualifier -- not a former section the
    # 1994 table can speak about. Where the record gives no such witness the
    # table is read as before: the guard refuses an answer, it never invents
    # one, and it never touches the section verdict beside it.
    #
    # Subtitle VII is what RIN 2105-AD66's own abstract says its authority runs
    # off, and it is deliberately NOT the predicate here: no pinned artifact in
    # this repository maps a title 49 chapter to a subtitle, so a subtitle test
    # would be a range typed from memory. The chapter register is pinned, and
    # a chapter that exists today is current law whichever subtitle holds it.
    if guard_candidates:
        wanted = {(row["rin"], row["publication_id"], pair[0]) for row, pair, _ in guard_candidates}
        cites_current_law: set[tuple[str, str, int]] = set()
        for other in authorities:
            key = (other["rin"], other["publication_id"], other["usc_title"])
            if key not in wanted:
                continue
            if other["usc_section_verdict"] == "exists" or (
                other["authority_type"] == "usc_chapter"
                and (key[2], normalize_section(other["usc_chapter"])) in oracle.chapters
            ):
                cites_current_law.add(key)
        for row, pair, moved in guard_candidates:
            if (row["rin"], row["publication_id"], pair[0]) not in cites_current_law:
                publish(row, pair, moved)
                continue
            row["usc_disposition_refusal"] = CHAPTER_QUALIFIED_REFUSAL
            disposition_refusal_rows[CHAPTER_QUALIFIED_REFUSAL] += 1
            disposition_refusal_pairs[CHAPTER_QUALIFIED_REFUSAL].add(pair)

    return _UscSectionCensus(
        rows_by_verdict=rows_by_verdict,
        texts_by_verdict={verdict: len(texts) for verdict, texts in texts_by_verdict.items()},
        pairs_by_verdict={verdict: len(pairs) for verdict, pairs in pairs_by_verdict.items()},
        rins_by_verdict={verdict: len(rins) for verdict, rins in rins_by_verdict.items()},
        unknown_rows_by_reason=unknown_rows,
        exists_not_at_edition_rows=exists_not_at_edition,
        title_impossible_rows=title_impossible,
        not_stated_rows=not_stated,
        corrected_rows_by_rule=corrected_rows,
        identity_moved_rows_by_rule=identity_moved_rows,
        refusal_rows_by_survivors=dict(sorted(refusal_rows.items())),
        disposition_rows_by_verdict=disposition_rows,
        disposition_pairs_by_verdict={name: len(group) for name, group in disposition_pairs.items()},
        disposition_rows_by_successor_count={
            str(count): rows for count, rows in sorted(disposition_by_count.items())
        },
        disposition_span_rows=span_rows,
        disposition_spans=len(disposition_spans),
        disposition_abbreviated_span_rows=abbreviated_span_rows,
        disposition_pinpoint_rows=pinpoint_rows,
        disposition_pinpoint_resolved_rows=pinpoint_resolved_rows,
        disposition_refusal_rows=disposition_refusal_rows,
        disposition_refusal_pairs={
            name: len(group) for name, group in disposition_refusal_pairs.items()
        },
    )


@dataclass(frozen=True)
class _ActSectionCensus:
    """What the section fence said about the sections an ACT resolution filled.

    Parallel to :class:`_UscSectionCensus` and deliberately not folded into it:
    that census is a statement about what filers wrote under a U.S.C. label,
    and this one is a statement about what OLRC's Table III answered for an act
    section. The two populations are disjoint by construction (a row is one
    ``authority_type`` or the other), they are asked at different points in the
    build, and a consumer gating on one must be able to read its number without
    the other's rows inside it.

    Rows, distinct texts, distinct pairs and distinct RINs, the four the U.S.C.
    census keeps and for its reason -- plus the distinct (act, act section)
    keys, which is the unit OLRC answered and closes against
    ``actRelativeResolvedPairs``.
    """

    rows_by_verdict: Mapping[str, int]
    texts_by_verdict: Mapping[str, int]
    pairs_by_verdict: Mapping[str, int]
    rins_by_verdict: Mapping[str, int]
    #: Distinct ``(act_key, act_section)`` per verdict: the citation OLRC was
    #: asked about, where the pairs above are the Code address it answered.
    act_sections_by_verdict: Mapping[str, int]
    unknown_rows_by_reason: Mapping[str, int]
    #: ``exists`` and the citing edition did not print it. The same era
    #: mismatch the U.S.C. census counts, on the same terms: Table III states a
    #: CURRENT classification, so a filing that predates the Code home its act
    #: section now has lands here and is narrowed, never accused.
    exists_not_at_edition_rows: int
    #: C0, applied for parity with the U.S.C. fence. Zero in the pinned build:
    #: Table III classifies into titles that exist, and the dated half of the
    #: builder's own title verdict has nothing to say here because the filer
    #: stated no title (``usc_title_is_possible`` is NULL on every act row).
    title_impossible_rows: int
    #: Rows by (which source classified it, verdict) and by (the status the row
    #: already carried, verdict). Both nested, the shape
    #: :class:`_CfrAuthorityNoteCensus` uses and for the same reason: the
    #: consumer's named reading is gated on "resolved or corroborated, with a
    #: section and evidence", and a total hides which half moved.
    rows_by_evidence_and_verdict: Mapping[str, Mapping[str, int]]
    rows_by_status_and_verdict: Mapping[str, Mapping[str, int]]


def _judge_act_derived_sections(
    authorities: list[dict[str, object]],
    oracle: UscSectionOracle | None,
) -> _ActSectionCensus:
    """Judge the section an ACT resolution filled, at the edition that cited it.

    5,657 rows resolve an act section to a U.S.C. section through Table III
    (5,644 rows) or the Code's own source credits (13), and until 2026-08-24
    not one of them carried a verdict: the fence above judges
    ``authority_type = 'usc'`` rows only, so an act-derived section's existence
    rested on Table III's CURRENT classification and nothing dated it. A
    consumer keying on those identities asked for the dated answer, and this is
    it -- the same oracle, the same three columns, the same reasons, the same
    attested-at-edition logic, through the same writer
    (:func:`_write_section_verdict`).

    **A verdict beside the identity, never a rewrite.** ``usc_title`` and
    ``usc_section`` are the resolver's and stay exactly as it wrote them,
    ``act_key`` and ``act_section`` stay the filer's, and no correction is
    asked for or published here: a correction repairs what a filer TYPED, and
    nothing on these rows was typed as a U.S.C. citation. The recodification
    tables are not asked either -- they answer beside one ``unknown`` reason,
    and no act-derived section reaches it (measured: zero unknowns).

    **What the measurement found.** Re-measured 2026-08-31 against the
    in-tree oracle of that date, over the 6,768 act-derived rows that reach a
    verdict: all 6,768 read ``exists`` -- no absent, no unknown, 358 distinct
    ``(title, section)`` pairs over 372 distinct act sections -- and **3** of
    them are not attested at their citing edition. **Every number in this
    paragraph rides the pinned section oracle's artifact**, and the artifact
    moved under it once already: the 2026-08-24 wave read 5,657 rows, 348
    pairs, 360 act sections and 19 unattested, and 16 of those 19 stopped
    being unattested when the annual extractor was fixed. Re-measure here
    after any rebuild that re-cuts the oracle.

    - The 16 that moved (RINs 2040-AE69/AE95, "CWA 101" … "CWA 510", edition
      201210) named title 33 sections the oracle printed in all 30 annual
      editions EXCEPT 2012, and that was never the Code's fact: the publisher
      names twelve of its own volume files with an UPPERCASE code name --
      `2010USC12.htm`, `2010USC13.htm`, `2010USC14.htm`, `2010USC51.htm`,
      and `2012USC33.htm`, `2012USC35.htm` … `2012USC41.htm`, verified in the
      pinned `output/usc-annual-2026-08-24/{2010,2012}.zip` members -- while
      every other volume in every other year spells it lowercase, and
      `extract_annual.py` matched only the lowercase spelling. Twelve
      already-downloaded volumes were silently never read. Fixed in this same
      wave (`re.IGNORECASE`, re-extract, re-pin), and the 2012 archive now
      carries 50 titles, title 33 among them. The 133 title-33 U.S.C. rows
      beside these 16, at the same edition, carried the identical hole and
      re-verdict as attested against the same in-tree oracle -- they are still
      flagged in the artifact on disk, which predates the re-cut, and the
      integrator's rebuild is what moves them.
    - Titles 52 and 54 were never that bug and no extractor fix will ever
      print a 2012 volume for them: both are GENUINE title-creation gaps
      (Title 52, Voting and Elections, and Title 54, National Park Service and
      Related Programs, were not enacted as positive-law titles until 2014).
      2012 has no 52 or 54 today and should not.
    - The 3 that remain are the era mismatch proper: 42 U.S.C. 805 and 806
      (Social Security Act §§ 605, 606, RIN 0938-AK71, edition 200310) attest
      1994-2002/2021-2024 and 2022-2024, and 20 U.S.C. 10005 (ARRA 2009
      §14005, RIN 1810-AB17, edition 201310) is first printed in 2014 -- the
      Code home Table III names today post-dates the filing that cited the act
      section.

    No reason code is minted for either. The oracle's own invariant forbids one
    (:class:`~refspec.registry.usc_section_oracle.SectionVerdict` accepts a
    reason only beside ``unknown``), the pair ``exists`` +
    ``attested_at_edition = false`` already says exactly this, and the U.S.C.
    rows carry the same two mechanisms in the same two columns without one.
    """

    verdicts: dict[tuple[int, str, bool, int | None], SectionVerdict] = {}
    rows_by_verdict: dict[str, int] = dict.fromkeys(VERDICTS, 0)
    texts_by_verdict: dict[str, set[str]] = {verdict: set() for verdict in VERDICTS}
    pairs_by_verdict: dict[str, set[tuple[int, str, bool]]] = {verdict: set() for verdict in VERDICTS}
    rins_by_verdict: dict[str, set[str]] = {verdict: set() for verdict in VERDICTS}
    acts_by_verdict: dict[str, set[tuple[object, object]]] = {verdict: set() for verdict in VERDICTS}
    unknown_rows: dict[str, int] = dict.fromkeys(UNKNOWN_REASONS, 0)
    by_evidence: dict[str, dict[str, int]] = {
        evidence: dict.fromkeys(VERDICTS, 0) for evidence in ACT_RESOLUTION_EVIDENCE
    }
    by_status: dict[str, dict[str, int]] = {}
    exists_not_at_edition = title_impossible = 0

    for row in authorities:
        if oracle is None or row["authority_type"] != "act_relative":
            continue
        # Evidence AND a section: a row whose act resolved and whose section
        # did not has no Code address to judge, and the resolver's own
        # act_resolution_reason already names why.
        if row["act_resolution_evidence"] is None or row["usc_section"] is None:
            continue
        title = row["usc_title"]
        if title is None or oracle.c0_title_impossible(title, stated_possible=row["usc_title_is_possible"]):
            title_impossible += 1
            continue
        pair, verdict = _write_section_verdict(row, oracle, verdicts)
        rows_by_verdict[verdict.verdict] += 1
        texts_by_verdict[verdict.verdict].add(row["authority_text"])
        pairs_by_verdict[verdict.verdict].add(pair)
        rins_by_verdict[verdict.verdict].add(row["rin"])
        acts_by_verdict[verdict.verdict].add((row["act_key"], row["act_section"]))
        by_evidence[row["act_resolution_evidence"]][verdict.verdict] += 1
        by_status.setdefault(row["parse_status"], dict.fromkeys(VERDICTS, 0))[verdict.verdict] += 1
        if verdict.reason is not None:
            unknown_rows[verdict.reason] += 1
        if verdict.exists and verdict.attested_at_edition is False:
            exists_not_at_edition += 1

    return _ActSectionCensus(
        rows_by_verdict=rows_by_verdict,
        texts_by_verdict={verdict: len(texts) for verdict, texts in texts_by_verdict.items()},
        pairs_by_verdict={verdict: len(group) for verdict, group in pairs_by_verdict.items()},
        rins_by_verdict={verdict: len(group) for verdict, group in rins_by_verdict.items()},
        act_sections_by_verdict={verdict: len(group) for verdict, group in acts_by_verdict.items()},
        unknown_rows_by_reason=unknown_rows,
        exists_not_at_edition_rows=exists_not_at_edition,
        title_impossible_rows=title_impossible,
        rows_by_evidence_and_verdict=by_evidence,
        rows_by_status_and_verdict=dict(sorted(by_status.items())),
    )


#: The two columns the CFR authority-note join writes, named once so the
#: writer and the "nothing to judge" path cannot drift apart.
_CFR_NOTE_COLUMNS = ("authority_in_own_cfr_note", "cfr_note_part")

#: Which parsed field IS the citation, per authority type. Four families, the
#: four the human review's evidence rests on; every other type is left unjudged
#: and counted (see :class:`_CfrAuthorityNoteCensus`). An executive order is
#: deliberately not here: every in-range EO number names a real order, so
#: "the note names a different one" is not evidence, and the campaign says so.
_CFR_NOTE_CITATION_BY_TYPE: Mapping[str, Callable[[Mapping[str, object]], object]] = {
    "usc": lambda row: usc_citation(row["usc_title"], row["usc_section"]),
    "public_law": lambda row: public_law_citation(row["public_law"]),
    "cfr": lambda row: cfr_citation(row["cfr_title"], row["cfr_part"]),
    #: Resolved key first, the name as stated where nothing resolved it --
    #: exactly the pair the emission keeps (``stated_act_name`` is NULL once
    #: ``act_key`` is set). The RESOLVED U.S.C. section is deliberately not
    #: judged here: it is OLRC's answer, not the filer's citation, and the
    #: fences beside this one hold the same line.
    "act_relative": lambda row: act_citation(row["act_key"] or row["stated_act_name"]),
}


@dataclass(frozen=True)
class _CfrAuthorityNoteCensus:
    """What the publisher's own notes said over the whole table, for the receipt."""

    rows_by_verdict: Mapping[str, int]
    texts_by_verdict: Mapping[str, int]
    #: Rows by (authority_type, verdict). A verdict that means one thing for a
    #: U.S.C. section means another for an act name, and a total hides that.
    rows_by_type_and_verdict: Mapping[str, Mapping[str, int]]
    #: The join's own reach: rows whose rule names at least one held part, the
    #: RINs and rules behind them, and how many of the 8,240 held parts any
    #: rule names. Widening the cache from the 287-part set-cover to the whole
    #: register moves these four and only these four in the way a coverage
    #: change moves them; a move in the verdicts that is not matched here is a
    #: data-quality finding instead, which is why both are printed.
    covered_rows: int
    covered_rins: int
    covered_rules: int
    parts_held: int
    parts_named_by_a_rule: int
    #: Rows that HAVE a held part and are still NULL, by type: the families
    #: this join does not judge, plus the rows whose own citation states no
    #: identity ("21 U.S.C." with no section). Counted so the census closes
    #: against the covered-row count instead of leaking into a silence.
    unjudged_rows_by_type: Mapping[str, int]


def _judge_against_cfr_notes(
    authorities: list[dict[str, object]],
    references: list[dict[str, object]],
    notes: CfrAuthorityNotes | None,
) -> _CfrAuthorityNoteCensus:
    """Write the publisher's verdict on every row whose rule names a held part.

    The join is the rule's own CFR Citation field -- the reference table beside
    this one -- because that is the agenda-to-CFR mapping the campaign's
    set-cover was computed over, and because it is the filer's own statement of
    which parts the rule amends. A CFR part named in the LEGAL AUTHORITY column
    is not read as a join key here: "49 CFR 1.53" is a delegation the rule
    cites as authority, not a part the rule amends, and using it would let a
    rule be judged against a note it has no relation to.

    Additive and nothing else: no existing value moves, and the verdict is
    written last, after corroboration, the sibling carry, both fences and the
    act resolver, so it judges what a consumer will actually read in the row.
    """

    for row in authorities:
        for column in _CFR_NOTE_COLUMNS:
            row[column] = None
    rows_by_verdict: dict[str, int] = dict.fromkeys(CFR_NOTE_VERDICTS, 0)
    texts_by_verdict: dict[str, set[str]] = {verdict: set() for verdict in CFR_NOTE_VERDICTS}
    rows_by_type: dict[str, dict[str, int]] = {}
    unjudged: dict[str, int] = {}
    if notes is None:
        return _CfrAuthorityNoteCensus(
            rows_by_verdict=rows_by_verdict,
            texts_by_verdict=dict.fromkeys(CFR_NOTE_VERDICTS, 0),
            rows_by_type_and_verdict={},
            covered_rows=0,
            covered_rins=0,
            covered_rules=0,
            parts_held=0,
            parts_named_by_a_rule=0,
            unjudged_rows_by_type={},
        )

    held_by_rule: dict[tuple[str, str], set[tuple[int, str]]] = {}
    named_parts: set[tuple[int, str]] = set()
    for reference in references:
        title, part = reference["cfr_title"], normalize_part(reference["cfr_part"])
        if title is None or part is None or not notes.holds(title, part):
            continue
        key = (int(title), part)
        named_parts.add(key)
        held_by_rule.setdefault((reference["rin"], reference["publication_id"]), set()).add(key)

    covered_rows = 0
    covered_rins: set[str] = set()
    for row in authorities:
        parts = held_by_rule.get((row["rin"], row["publication_id"]))
        if not parts:
            continue
        covered_rows += 1
        covered_rins.add(row["rin"])
        kind = str(row["authority_type"])
        reader = _CFR_NOTE_CITATION_BY_TYPE.get(kind)
        citation = reader(row) if reader is not None else None
        verdict = notes.judge(citation, parts) if citation is not None else None
        if verdict is None:
            unjudged[kind] = unjudged.get(kind, 0) + 1
            continue
        row["authority_in_own_cfr_note"] = verdict.verdict
        row["cfr_note_part"] = verdict.cited_as
        rows_by_verdict[verdict.verdict] += 1
        texts_by_verdict[verdict.verdict].add(str(row["authority_text"]))
        by_verdict = rows_by_type.setdefault(kind, dict.fromkeys(CFR_NOTE_VERDICTS, 0))
        by_verdict[verdict.verdict] += 1

    return _CfrAuthorityNoteCensus(
        rows_by_verdict=rows_by_verdict,
        texts_by_verdict={verdict: len(texts) for verdict, texts in texts_by_verdict.items()},
        rows_by_type_and_verdict={kind: dict(counts) for kind, counts in sorted(rows_by_type.items())},
        covered_rows=covered_rows,
        covered_rins=len(covered_rins),
        covered_rules=len(held_by_rule),
        parts_held=len(notes.coverage()),
        parts_named_by_a_rule=len(named_parts),
        unjudged_rows_by_type=dict(sorted(unjudged.items())),
    )


#: A bare digit-hyphen-digit ``usc_section`` ("472-8", "6708-1") -- no letter
#: anywhere, which is what separates it from a real compound section
#: ("1715z-2"). ``inv-universe`` shape (b): Treasury writes its own
#: regulation-numbering suffix under a U.S.C. label, and the grammar reads
#: "472-8" as if it were section 472 hyphen-compound 8, a shape the real Code
#: also uses -- so this is lexical only, never a verdict.
_USC_SLOT_BARE_HYPHEN_SECTION = re.compile(r"\A\d+-\d+\Z")
#: The two names :func:`_write_usc_slot_reading` writes. A THIRD shape,
#: ``inv-universe``'s shape (d) (bare OSHA-style citations with no title or
#: scheme marker nearby), was measured at 0 misreads and gets no name; a
#: FOURTH, shape (a)'s reg-shaped dot-truncation ("26 USC 1.104-1(c)" read as
#: title 26 section 1), is a case where naming without also fixing the
#: verdict would be more confusing than silence, and the fix is explicitly
#: out of scope this wave (see the investigation's own finding 3) -- so this
#: column says nothing about it either, rather than half-saying something.
USC_SLOT_READINGS: tuple[str, ...] = ("reg-suffix", "chapter-in-slot")


def _write_usc_slot_reading(
    authorities: list[dict[str, object]],
    references: list[dict[str, object]],
    oracle: UscSectionOracle | None,
) -> dict[str, int]:
    """Name the non-U.S.C. numbering universe a U.S.C.-labelled slot holds.

    Two shapes, both measured 2026-08-24 (``inv-universe``), neither ever
    moving ``usc_section_verdict`` or any other published column --
    ``usc_slot_reading`` is the only column this function touches, and it is
    NULL on every row until this function decides otherwise.

    **reg-suffix.** A bare digit-hyphen-digit section is Treasury's own
    regulation-numbering convention (26 CFR 1.472-8 written as "26 USC
    472-8"), not a compound U.S.C. section. The witness is structural, and
    the SAME rule's own words: the rule's ``unified_agenda_cfr_references``
    rows, across every edition it filed under, already carry an entry whose
    (cfr_title, cfr_section) is this exact pair -- "witnessed exactly by
    CFR_LIST" is that join and nothing looser. Measured 190 rows, all title
    26, all ``usc_section_verdict`` "absent" today, over a candidate pool of
    820 bare-hyphen U.S.C. sections; unwitnessed candidates get no name,
    because a compound section a real RIN never confirms is not this
    function's to call.

    **chapter-in-slot.** The U.S.C. label's own bare integer names a real
    CHAPTER of that title, not a section --
    :meth:`UscSectionOracle.c7_chapter_as_section`, the same pinned chapters
    table the oracle's own C7 miss-class reads. Fenced to rows the oracle
    does NOT also verdict ``exists``: a number that is both a chapter and a
    real section is answering the section question correctly, and naming it
    "chapter-in-slot" here would suggest otherwise. Measured ~1,685 rows
    (absent + unknown) of the ~15,769 total (title, section) pairs C7
    recognises, the other ~14,084 being exactly that overlap.
    """

    cfr_witness: set[tuple[str, int, str]] = set()
    for reference in references:
        title, section = reference.get("cfr_title"), reference.get("cfr_section")
        if title is not None and section is not None:
            cfr_witness.add((reference["rin"], int(title), section))

    counts: dict[str, int] = dict.fromkeys(USC_SLOT_READINGS, 0)
    for row in authorities:
        row["usc_slot_reading"] = None
        if row["authority_type"] != "usc":
            continue
        title, section = row["usc_title"], row["usc_section"]
        if title is None or section is None:
            continue
        if _USC_SLOT_BARE_HYPHEN_SECTION.match(section) and (row["rin"], int(title), section) in cfr_witness:
            row["usc_slot_reading"] = "reg-suffix"
            counts["reg-suffix"] += 1
        elif (
            oracle is not None
            and row["usc_section_verdict"] != "exists"
            and oracle.c7_chapter_as_section(int(title), section)
        ):
            row["usc_slot_reading"] = "chapter-in-slot"
            counts["chapter-in-slot"] += 1
    return counts


#: One occurrence of a bare section token in an authority string, with
#: whatever the citation writes immediately after it: a first parenthesised
#: group (the letter a lost suffix would have been), any further groups
#: ("78(c)(3)"), and a stated tail ("78(s)-37"). The bounds on the left and
#: right are :func:`usc_section_pinpoint`'s own -- a token inside a
#: parenthesis is a LABEL and not a section, and a digit or letter either side
#: means this is a different token -- so the two readers cannot disagree about
#: what an occurrence IS.
_USC_OCCURRENCE = (
    r"(?<![0-9A-Za-z.\-(]){token}(?![0-9A-Za-z\-])"
    r"(?:\s*\(\s*(?P<letter>[0-9A-Za-z]{{1,4}})\s*\)"
    r"(?:\s*\(\s*[0-9A-Za-z]{{1,4}}\s*\))*"
    r"(?:\s*-\s*(?P<tail>[0-9A-Za-z]+))?)?"
)


#: A parenthesised group that could be a LOST LETTER SUFFIX rather than a
#: subsection number -- the only shape ``c3_proposals`` reads, and so the only
#: one this fence counts. "(3)" is a subsection and nothing else.
_A_LETTER_SUFFIX = re.compile(r"[a-z]{1,4}")


def _paren_suffix_occurrences(section: str, text: str) -> tuple[tuple[str, str], ...]:
    """Every occurrence of this stem in ``text``, as (first letter group, tail).

    ``("", "")`` for an occurrence the citation writes bare. One reader for
    both the binding below and the refusal census beside it, so "what counts
    as an occurrence of section 183" cannot have two answers -- "42 USC183(e)"
    (the publisher's lost space) is not one under this pattern's left bound,
    and a census that used a looser bound would report a refusal on a row this
    fence never judged.
    """

    token = str(section or "").strip().lower()
    if not token:
        return ()
    pattern = re.compile(_USC_OCCURRENCE.format(token=re.escape(token)), re.IGNORECASE)
    return tuple(
        ((match.group("letter") or "").lower(), (match.group("tail") or "").lower())
        for match in pattern.finditer(str(text or ""))
    )


def _bound_paren_suffix(section: str, text: str) -> str | None:
    """The row's OWN "78(b)" occurrence, or None where the text cannot bind one.

    The C3 promotion below rests on the claim "the parenthetical this row's
    citation wrote was a real letter suffix". A pre-filter that only asked
    whether the STRING contains "78(b)" somewhere cannot make that claim, and
    two shapes prove it: ``"15 USC 78; 15 USC 78(b)"`` promotes the row for the
    FIRST citation on the second one's parenthetical, and ``"15 USC 78;
    42 USC 78(b)"`` promotes a title-15 row on a title-42 citation's -- the
    letter is read from another citation entirely and 15 U.S.C. 78b happens to
    be real, so nothing downstream can tell.

    So the binding is the reading, and it is :func:`usc_section_pinpoint`'s own
    rule one field wider: **every** occurrence of this stem in the text is
    collected with its first parenthesised group and its stated tail, and the
    text binds a suffix only where all of them agree. Two spellings refuse
    rather than pick, exactly as a pinpoint does -- a bare occurrence beside a
    parenthesised one, ``"81(a) to 81(u)"``, ``"2000(d) to 2000(d)-7"`` -- and
    the row keeps the ``absent`` verdict it already had. Occurrences that
    differ only BELOW the first group ("78(c)(b), 78(c)(3)") agree here,
    because the first group is the whole of what a fused reading uses.

    The title is not read out of the text at all: the oracle is asked about the
    ROW's ``usc_title`` and the bound occurrence, so a stem that only appears
    under some other title's label cannot answer for this row. Returns the
    occurrence spelled canonically ("78(s)-37"), which is what the oracle
    reads and all it reads.
    """

    stated = set(_paren_suffix_occurrences(section, text))
    if len(stated) != 1:
        return None
    letter, tail = stated.pop()
    if not _A_LETTER_SUFFIX.fullmatch(letter):
        return None
    return f"{section.strip().lower()}({letter})" + (f"-{tail}" if tail else "")


#: The rule name this promotion writes into
#: ``usc_section_correction_evidence``, named after the oracle's own C3
#: miss-class. Deliberately NOT one of ``usc_section_oracle.CORRECTION_RULES``
#: -- C3 is excluded from that tuple by the oracle's own design (see
#: ``MISS_CLASSES``), because turning "exactly one candidate survived" into a
#: publication is a decision about how much a builder trusts a proposal, not
#: a fact the oracle's other inputs can settle, and every other rule in that
#: tuple requires the AS-FILED bare section to already be real. C3's bare
#: section never is, by definition of the class.
USC_C3_PROMOTION_RULE = "C3-paren-suffix-eaten"

#: Every outcome :func:`_promote_paren_eaten_lettered_suffix` counts, named
#: once so the receipt's key set and the function's own tally cannot drift.
#: Three of the five are refusals and each names a DIFFERENT reason to refuse:
#: the text binds no occurrence to this row (``unbound``), the bound occurrence
#: names no fused reading at all (``witnessless``), it names two or more
#: (``ambiguous``), or it states a tail the surviving reading does not honour
#: (``stated_tail_refused``). A single "refused" total would hide which.
USC_C3_PROMOTION_OUTCOMES: tuple[str, ...] = (
    "promoted", "ambiguous", "witnessless", "unbound", "stated_tail_refused",
)


def _promote_paren_eaten_lettered_suffix(
    authorities: list[dict[str, object]], oracle: UscSectionOracle | None
) -> dict[str, int]:
    """"15 USC 78(d)" -> 78d: publish the oracle's own single-candidate answer.

    :meth:`UscSectionOracle.c3_proposals` has read this shape since it
    existed -- the grammar's own parenthetical strip ate a real letter suffix
    -- but it is a MISS class, not a correction rule: ``corrected_section``
    proposes nothing for it, because every rule there requires the as-filed
    bare section to already be a real one, and C3's never is. This is the
    builder's own promotion of that proposal, run once
    ``usc_section_corrected`` has had its ordinary turn from the fence in
    :func:`_judge_usc_sections`, and it never overwrites a value that pass
    already wrote (``usc_section_corrected is None`` gates every row here).

    **The parenthetical is bound to the row's own citation, or nothing is
    published.** The oracle reads a whole authority string, which is right for
    a classifier counting what a text could mean and wrong for a builder
    filling one row's column: over ``"15 USC 78; 15 USC 78(b)"`` it answers
    78b for BOTH rows, and over ``"15 USC 78; 42 USC 78(b)"`` it answers 78b
    for the title-15 row on a title-42 citation's parenthetical.
    :func:`_bound_paren_suffix` decides first, on the row's own stem, and hands
    the oracle THAT occurrence and nothing else; a text that spells the stem
    two ways binds nothing and is counted ``unbound`` rather than guessed at.

    **A stated tail the surviving reading does not honour refuses.** RIN
    3235-AI17 files ``"15 USC 78(s)-37(a)"`` in 17 editions (200104-200904);
    the tail 78s-37 is not a section, the oracle falls back to the bare
    lettered 78s -- which IS one -- and publishing it would drop characters the
    filer wrote. The raw record forbids it outright: the SAME rule's later
    editions (200910, 201004, 201010) spell the box ``"15 USC 78a-37(a)"``,
    letter "a", not "s", beside four sibling boxes that are the SEC's
    rulemaking quintet (77s(a), 78(wa), 77sss(a) and this one -- Securities
    Act 19(a), Exchange Act 23(a), Trust Indenture Act 319(a), and what reads
    as Investment Company Act 38(a) at 15 U.S.C. 80a-37(a)). Two spellings of
    one damaged token, neither of them 78s. Refused, counted, and named.

    Measured 2026-08-31 over the 1,417 rows of the then-current build that
    reach this fence at all (``absent``, uncorrected, a bare digit stem, and a
    parenthetical on that stem somewhere in the text): **200 promoted, 1,179
    witnessless, 21 unbound, 17 stated-tail-refused, 0 ambiguous.** The same
    1,417 rows read 217 / 1,186 / 14 before the binding, and the whole
    difference is a refusal: the 17 are the 3235-AI17 family, and the 21 are
    the 14 that were ambiguous plus 7 that were witnessless for a reason that
    had nothing to do with a lost suffix. Not one row the old pre-filter
    refused is newly admitted. The witnessless population -- the parenthetical
    is a genuine subsection, not a lost suffix -- MUST keep refusing, and does.
    ``ambiguous`` stays reachable and empty on this corpus: it is what a bound
    occurrence whose lettered reading is itself unenumerated gets, where the
    oracle offers that section's whole hyphen-child family ("15 USC 80(a)" ->
    80a-1 … 80a-64) and nothing in the text says which.

    Every count in this paragraph rides the pinned section oracle's artifact
    and code; re-measure after any rebuild that moves either.

    ``usc_section_end`` -- the far end of a stated range ("49 USC 2157(e) to
    2157(f)") -- is NOT corrected here even though #47 measured 15 such rows
    riding the identical rule: the end has no ``_corrected`` sibling column
    (:func:`_judge_usc_sections`'s own docstring: "only usc_section is
    judged... no verdict speaks for" the end), and writing one is schema
    work this wave leaves to whichever unit owns the range-endpoint shape
    generally (`inv-dropped`'s degenerate-endpoint finding is the sibling
    case). Left refused rather than mutating ``usc_section_end`` in place,
    which would be the one thing every other correction here is built never
    to do to ``usc_section`` itself. Such a row now refuses on the binding
    instead of on the schema: both endpoints write the same stem with
    different parentheticals, so nothing is bound.
    """

    counts = dict.fromkeys(USC_C3_PROMOTION_OUTCOMES, 0)
    if oracle is None:
        return counts
    for row in authorities:
        if (
            row["authority_type"] != "usc"
            or row["usc_title"] is None
            or row["usc_section"] is None
            or row["usc_section_verdict"] != "absent"
            or row["usc_section_corrected"] is not None
        ):
            continue
        section = row["usc_section"]
        if not re.fullmatch(r"\d+", section):
            continue
        bound = _bound_paren_suffix(section, row["authority_text"])
        if bound is None:
            # Only rows this fence would otherwise have judged are counted: the
            # census is of bindings REFUSED, not of every U.S.C. row in the
            # corpus that states no parenthetical at all. Read through the same
            # occurrence pattern the binding uses, so the two cannot disagree
            # about what an occurrence is and count a row neither ever judged.
            if any(
                _A_LETTER_SUFFIX.fullmatch(letter)
                for letter, _ in _paren_suffix_occurrences(section, row["authority_text"])
            ):
                counts["unbound"] += 1
            continue
        proposals = oracle.c3_proposals(row["usc_title"], section, bound)
        if not proposals:
            counts["witnessless"] += 1
            continue
        if len(proposals) > 1:
            counts["ambiguous"] += 1
            continue
        only = proposals[0]
        if "-" in bound.rsplit(")", 1)[-1] and "tail-stated" not in only.kinds:
            counts["stated_tail_refused"] += 1
            continue
        row["usc_section_corrected_section"] = only.section
        row["usc_section_corrected_pinpoint"] = None
        row["usc_section_corrected"] = only.section
        row["usc_section_correction_evidence"] = USC_C3_PROMOTION_RULE
        counts["promoted"] += 1
    return counts


#: Why one candidate a witness offered was withheld though its record's
#: two-witness intersection was otherwise non-empty. A row that hits both
#: carries both, sorted and joined by "; " the way its sibling column joins
#: candidates -- a refusal census that reported only the first reason would be
#: the same silence this column exists to end.
_PLACEHOLDER_CANDIDATE_REFUSALS: tuple[str, ...] = (
    #: A note read TODAY can name a Public Law enacted after the record's own
    #: edition -- ``inv-placeholders``'s own trap: a 2007 placeholder offered
    #: 2020 Public Laws by a 2026-dated note capture. The direction that
    #: matters is one-way: a note is free to be SILENT about a law the
    #: edition already knew (the note is a snapshot of what CURRENTLY stands,
    #: not a history), so only "the candidate's law postdates the edition" is
    #: refused, never the reverse.
    "note-names-a-later-public-law-than-the-edition-states",
    #: A U.S.C. candidate the pinned section oracle REFUTES: it prints no such
    #: section in any year of its window and no release point carries it.
    #: Two witnesses agreeing on a number is agreement about a STRING, not
    #: evidence that the string names law -- a sibling edition can restate a
    #: filer's own damaged citation verbatim, and the note reader can carry a
    #: number out of a badly split note. Candidates are not verdicts, which is
    #: why this fence is one-sided: only ``absent`` refuses, ``unknown``
    #: (the oracle's own coverage hole) publishes, because a hole is not a
    #: denial.
    "the-section-oracle-refutes-this-candidate",
)


def _usc_candidate_is_refuted(identity: str, oracle: UscSectionOracle | None) -> bool:
    """Whether the pinned oracle denies that "40:550" names a section at all.

    The identity spelling is :func:`cfr_authority_notes.usc_citation`'s own,
    "title:section", and it is read here rather than re-derived: one spelling
    of the join key, whichever side of the join is asking. Undated on purpose
    -- the question is "does this number name law", not "did it at this
    edition", because a candidate is offered to a RECORD and the edition
    question is the one ``usc_section_verdict`` answers on rows that state
    something. False wherever the oracle is absent or cannot parse the
    identity: a tree without the artifact refuses nothing rather than
    refusing everything.
    """

    if oracle is None:
        return False
    title, _, section = identity.partition(":")
    if not title.isdigit() or not section:
        return False
    return oracle.section_verdict(int(title), section).verdict == "absent"


def _write_placeholder_candidates(
    authorities: list[dict[str, object]],
    references: list[dict[str, object]],
    notes: CfrAuthorityNotes | None,
    calendar: _SeriesCalendar,
    oracle: UscSectionOracle | None = None,
) -> dict[str, int]:
    """Per-record candidate authorities for an "unstated" placeholder row.

    ``inv-placeholders`` (2026-08-24): 12,467 rows across three kinds
    (more-citations-follow, not-yet-determined, none-off-form) state nothing
    at all -- 6,876 + 5,461 + 130 -- and every one of them belongs to a
    RECORD, ``(rin, publication_id)``, that may say more elsewhere. Two
    witnesses, independently derived, each offer candidate authorities for
    the record as a whole, and this function publishes only where BOTH agree:

    **Witness A**, the publisher's own note. The SAME join
    :func:`_judge_against_cfr_notes` uses -- the record's own
    ``unified_agenda_cfr_references`` rows, filtered to parts the pinned
    authority-note cache holds -- names the CFR parts the rule amends; each
    held part's ``AuthorityNote.citations`` is a candidate, minus whatever
    the record already states for itself under the ordinary four-family
    reading (:data:`_CFR_NOTE_CITATION_BY_TYPE`).

    **Witness B**, a sibling edition of the SAME rule. Measured over every
    OTHER publication of the same RIN that carries no placeholder of its own
    and states strictly more distinct citations than this record does, the
    difference between what the donor states and what this record states.

    **The publishable tier is the intersection.** Measured 2026-08-24: where
    both witnesses answer and agree at all, they intersect far more often
    than they merely coexist (agreement.both_nonempty_and_intersect over
    agreement.both_nonempty, all three kinds) -- and where only one speaks,
    it is spending a single, weaker claim at the two-witness price, which
    this column does not do. A record most of the time gets nothing: only a
    small fraction of 12,467 records reach a non-empty intersection at all.

    **Two witnesses are a cardinality check, so each candidate faces the
    oracle that exists for its own kind.** Agreement between witness A and
    witness B says two readers produced the same STRING; it does not say the
    string names law, and both readers can carry the same defect -- a sibling
    edition restates the filer's own damaged citation verbatim, a badly split
    note carries a number out of its neighbour. So a U.S.C. candidate is put
    to the pinned section oracle and dropped where the oracle REFUTES it
    (``absent``: no year of the window prints it and no release point carries
    it); ``unknown`` publishes, because the oracle's own coverage hole is not
    a denial. A Public Law candidate faces the pinned series calendar below.
    Where no oracle exists for a family -- CFR parts, act names -- the
    two-witness agreement is all there is and the candidate is published as
    what it always was: a candidate, never a verdict, which nothing else in
    this table reads.

    **The note-date-vs-edition gate.** A note is read at BUILD TIME, against
    the rule's CURRENT CFR text, and can therefore name a Public Law the
    record's own edition could not possibly have known -- a 2007 placeholder
    offered 2020 Public Laws by a 2026-dated note capture is exactly the trap
    `inv-placeholders` names and nothing before this function caveats. Gated
    on the APPROVAL DATE the pinned roster already carries
    (:meth:`_SeriesCalendar.pl_approved_by_edition`) rather than on the
    congress alone, because a congress is a year-resolution answer and a year
    is too coarse here: Pub. L. 110-20 was approved 05/02/2007 and the
    congress bound passes it for the Spring 2007 edition, an edition
    published a month before the law existed. Where the roster carries no
    date for a law, or the edition states no month, the congress bound still
    answers and the residue is named in that method's own docstring. A
    candidate the gate drops is never published, and the row says why in
    ``placeholder_candidate_refusal`` when dropping it empties the record's
    whole intersection.

    Additive only: nothing here reads or writes any column but the row's own
    two, and a record with nothing to say gets NULL on both, exactly as it
    read before this function existed.
    """

    for row in authorities:
        row["placeholder_candidate_authorities"] = None
        row["placeholder_candidate_refusal"] = None

    counts: dict[str, int] = dict.fromkeys(
        ("published", "rows_withheld", "candidates_gated_by_edition", "candidates_refuted_by_oracle"), 0
    )
    if notes is None:
        return counts

    stated_by_record: dict[tuple[str, str], set[tuple[str, str]]] = {}
    unstated_by_record: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in authorities:
        key = (row["rin"], row["publication_id"])
        if row["authority_type"] == "unstated":
            unstated_by_record.setdefault(key, []).append(row)
            continue
        reader = _CFR_NOTE_CITATION_BY_TYPE.get(row["authority_type"])
        citation = reader(row) if reader is not None else None
        if citation is not None:
            stated_by_record.setdefault(key, set()).add((citation.family, citation.identity))

    if not unstated_by_record:
        return counts

    held_by_rule: dict[tuple[str, str], set[tuple[int, str]]] = {}
    for reference in references:
        title, part = reference["cfr_title"], normalize_part(reference["cfr_part"])
        if title is None or part is None or not notes.holds(title, part):
            continue
        held_by_rule.setdefault((reference["rin"], reference["publication_id"]), set()).add((int(title), part))

    editions_by_rin: dict[str, dict[str, set[tuple[str, str]]]] = {}
    for key in set(stated_by_record) | set(unstated_by_record):
        rin, pub = key
        editions_by_rin.setdefault(rin, {})[pub] = stated_by_record.get(key, set())
    placeholder_records = set(unstated_by_record)

    for key, rows in unstated_by_record.items():
        rin, pub = key
        own_stated = stated_by_record.get(key, set())

        witness_a: set[tuple[str, str]] = set()
        for title, part in held_by_rule.get(key, ()):
            note = notes.note(title, part)
            if note is None:
                continue
            witness_a.update((citation.family, citation.identity) for citation in note.citations)
        witness_a -= own_stated

        witness_b: set[tuple[str, str]] = set()
        for donor_pub, donor_stated in editions_by_rin.get(rin, {}).items():
            if donor_pub == pub or (rin, donor_pub) in placeholder_records:
                continue
            if len(donor_stated) <= len(own_stated):
                continue
            witness_b |= donor_stated - own_stated

        intersection = witness_a & witness_b
        if not intersection:
            continue

        published: set[tuple[str, str]] = set()
        refusals: set[str] = set()
        for family, identity in intersection:
            if family == "public_law" and calendar.pl_approved_by_edition(identity, pub) is False:
                refusals.add("note-names-a-later-public-law-than-the-edition-states")
                counts["candidates_gated_by_edition"] += 1
                continue
            if family == "usc" and _usc_candidate_is_refuted(identity, oracle):
                refusals.add("the-section-oracle-refutes-this-candidate")
                counts["candidates_refuted_by_oracle"] += 1
                continue
            published.add((family, identity))

        for row in rows:
            if published:
                row["placeholder_candidate_authorities"] = "; ".join(
                    sorted(f"{family}:{identity}" for family, identity in published)
                )
                counts["published"] += 1
            elif refusals:
                row["placeholder_candidate_refusal"] = "; ".join(sorted(refusals))
                counts["rows_withheld"] += 1
    return counts


#: A Table III key that is a RANGE of act sections ("2-6", "531-535"), which is
#: how OLRC files one classification covering several sections. A citation to a
#: member of the range finds nothing under its own number, and the absence the
#: section-keyed lookup reports is a fact about the KEY and not about the act.
_TABLE3_RANGE_KEY = re.compile(r"^(?P<low>\d+)[A-Za-z]*-(?P<high>\d+)[A-Za-z]*$")
_ACT_SECTION_NUMBER = re.compile(r"^(?P<number>\d+)[A-Za-z]*$")
#: OLRC's spelling for a statutory note in the U.S.C. column ("47 U.S.C. 303
#: nt", "49 U.S.C. nt. prec. 42301"). A note is real and citable and is not a
#: section, which is why the rkaf lexical space refuses it.
_USC_NOTE_TARGET = re.compile(r"(?:^|\s)(?:nts?|notes?)(?:\.|\b)", re.IGNORECASE)
#: A pre-codification citation standing where a currency status belongs: the
#: bulk Table III release writes "R.S. Sec 2319" into
#: ``<united-states-code-status>`` for 9,341 rows.
_REVISED_STATUTES_STATUS = re.compile(r"^\s*R\.\s*S\.", re.IGNORECASE)


@dataclass(frozen=True)
class _ActResolutionCensus:
    """What the act resolver said over the whole table, for the receipt."""

    #: Act-relative rows by their final parse_status. The bare "failed" this
    #: pass replaces is the thing it exists to remove.
    rows_by_status: Mapping[str, int]
    #: Every declared reason, listed even at zero: a refusal that stops being
    #: reported is exactly what this column exists to keep visible.
    rows_by_reason: Mapping[str, int]
    rows_by_evidence: Mapping[str, int]
    #: Resolved rows by the parse_status they carried BEFORE this pass, so the
    #: 2,782 rows already corroborated by RIN history stay countable apart from
    #: the ones whose only answer is this resolution.
    resolved_rows_by_prior_status: Mapping[str, int]
    #: Distinct (act key, act section) pairs, which is the unit the resolver
    #: actually answers -- rows are how often the corpus asked.
    pairs_resolved: int
    pairs_refused: int


def _range_key_covering(index: ActIndex, table3_key: str, section: str) -> bool:
    """Whether Table III files this act section under a range key containing it."""

    stated = _ACT_SECTION_NUMBER.fullmatch(section)
    if stated is None:
        return False
    number = int(stated.group("number"))
    return any(
        int(found.group("low")) <= number <= int(found.group("high"))
        for key in index.classifications.get(table3_key, ())
        if (found := _TABLE3_RANGE_KEY.fullmatch(key)) is not None
    )


def _classifies_only_to_revised_statutes(index: ActIndex, table3_key: str) -> bool:
    """Whether every Table III row of this act terminates in the Revised Statutes."""

    rows = [row for section in index.classifications.get(table3_key, {}).values() for row in section]
    return bool(rows) and all(_REVISED_STATUTES_STATUS.match(row.status or "") for row in rows)


def _resolve_one_act_citation(
    act_key: str, section: str | None, index: ActIndex, credits: SourceCreditIndex | None
) -> tuple[int | None, str | None, str | None, str | None]:
    """(usc_title, usc_section, evidence, reason) for one (act, section).

    One decider: the identifier, the source that produced it and the refusal
    are all :func:`resolve_act_relative_citation`'s, asked through its public
    API and never re-derived. What this adds is three NARROWINGS of a refusal
    the resolver states more widely than the corpus needs -- each reading the
    same pinned tables the resolver read, each named in
    :data:`ACT_RESOLUTION_REASONS` with its population and its specimen.

    No division is passed, and that is measured rather than assumed: of the
    9,065 act-relative rows the grammar reads, **none** yields a citation that
    names a division, so ``act_division_conflict`` cannot arise here and
    inventing a division to make it arise would be the guess this whole line of
    work exists to prevent.
    """

    resolved = resolve_act_name(act_key, index)
    if resolved is None:
        return (None, None, None, "act_not_in_index")
    table3_key = index.table3_key_by_name[resolved]
    if section is None:
        # Nothing to look up. Which of the two silences this is -- "the filer
        # named no section" or "no section of this act reaches the Code" -- is
        # the whole difference between a citation to finish and a dead end.
        if _classifies_only_to_revised_statutes(index, table3_key):
            return (None, None, None, "revised_statutes_only")
        return (None, None, None, "no_section_stated")

    outcome = resolve_act_relative_citation(
        ActRelativeCitation(act_name=act_key, act_key=act_key, section=section),
        index=index,
        source_credits=credits,
    )
    if outcome.iri is not None:
        return (
            int(str(outcome.usc_title).strip()),
            outcome.usc_section,
            _ACT_RESOLUTION_EVIDENCE_BY_SOURCE[outcome.answered_by],
            None,
        )
    reason = outcome.unresolved_reason
    if reason == "act_section_not_classified" and _range_key_covering(index, table3_key, section):
        reason = "act_section_inside_a_range_key"
    elif reason == "usc_section_not_expressible" and _USC_NOTE_TARGET.search(outcome.usc_section or ""):
        reason = "resolves_to_note"
    return (None, None, None, reason)


#: A box whose whole content is one section designation -- "316", "sec.206",
#: "and 510", "Section 4(b)." -- and nothing that could name where it lives. A
#: leading list connective is admitted because the run this rule reads IS a
#: list the publisher cut across boxes ("and 510" closes EPA 2040-AE95's Clean
#: Water Act run); it costs nothing, since the act still has to come from a
#: neighbour and the section still has to classify.
_BARE_SECTION_BOX = re.compile(
    r"^(?:and|or|,)?\s*(?:sec(?:tion)?s?\.?|§{1,2})?\s*(?P<section>\d{1,5}[a-z]?)"
    r"(?:\([^()]{1,12}\))*\s*[.;,]?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _SiblingActCensus:
    """What the sibling-act carry emitted, and every refusal beside it."""

    rows: int
    #: Keyed by what stopped it, the resolver's own reason included. A rule is
    #: only as trustworthy as what it declines to answer.
    refusals: Mapping[str, int]


def _carry_sibling_acts(
    authorities: list[dict[str, object]],
    index: ActIndex | None,
    credits: SourceCreditIndex | None,
    tally: _Tally,
    calendar: _SeriesCalendar,
) -> _SiblingActCensus:
    """Give a box holding only a section the act the box beside it names.

    EPA's RIN 2040-AE95, Fall 2008, files its Clean Water Act authority as nine
    boxes -- ``CWA 101``, ``301``, ``304``, ``308``, ``316``, ``401``, ``402``,
    ``501``, ``and 510``. The act is written once and the rest of the list is
    bare section numbers, so six boxes read as act-relative and three read as
    nothing at all. The list is not a list (review A, P1); the answer sits at
    ordinal +-1 in either direction (reviews A and B, H8).

    Four fences, and the fourth is the one worth stating:

    1. the box must hold a section designation and NOTHING else;
    2. the boxes at +-1 must name exactly ONE act between them, or the carry
       has to choose and refuses instead;
    3. the resolver must answer that (act, section) with exactly one U.S.C.
       section -- a carried act that resolves to nothing is not evidence that
       the carry was right, so nothing is emitted;
    4. **and where a box at +-1 states a U.S.C. citation of its own, the
       carried section must be among what those boxes state.** A neighbour
       that states a DIFFERENT section is not a refutation in general -- an
       authority list is a list of different provisions, and 532 of the 5,590
       rows resolved elsewhere in this module have a neighbour naming another
       section, every one of them correctly. It is a refutation HERE, because
       this rule's whole claim is that the box belongs to its neighbour's
       citation; if the neighbour spells that citation out and it is not this,
       the claim is already contradicted.

    The donor acts are read ONCE, from the table as it stands before this pass
    writes anything, so a carry never rests on another carry: a chain would
    walk an arbitrary distance one hop at a time, which is not what "the box
    beside it" means. Where both neighbours name the same act the preceding one
    is recorded as the donor, because a list is written forward.
    """

    refusals: dict[str, int] = {}
    if index is None:
        return _SiblingActCensus(rows=0, refusals=refusals)

    acts_by_box: dict[tuple[object, object, object], set[str]] = {}
    usc_by_box: dict[tuple[object, object, object], set[tuple[int, str]]] = {}
    for row in authorities:
        box = (row["rin"], row["publication_id"], row["ordinal"])
        if row["authority_type"] == "act_relative" and row["act_key"]:
            acts_by_box.setdefault(box, set()).add(row["act_key"])
        elif row["authority_type"] == "usc" and row["usc_title"] is not None and row["usc_section"]:
            usc_by_box.setdefault(box, set()).add((row["usc_title"], row["usc_section"].lower()))

    carried = 0
    for row in authorities:
        if row["authority_type"] != "other" or row["parse_status"] != "failed":
            continue
        stated = _BARE_SECTION_BOX.fullmatch(_WRAPPING_QUOTES.sub("", str(row["authority_text"] or "")).strip())
        if stated is None:
            continue
        neighbours = [
            (row["ordinal"] + step, acts_by_box.get((row["rin"], row["publication_id"], row["ordinal"] + step), set()))
            for step in (-1, 1)
        ]
        offered = {key for _, keys in neighbours for key in keys}
        if not offered:
            refusals["no-act-in-either-neighbour"] = refusals.get("no-act-in-either-neighbour", 0) + 1
            continue
        if len(offered) > 1:
            refusals["neighbours-name-two-acts"] = refusals.get("neighbours-name-two-acts", 0) + 1
            continue
        act_key = next(iter(offered))
        section = stated.group("section").lower()
        title, usc_section, evidence, reason = _resolve_one_act_citation(act_key, section, index, credits)
        if evidence is None:
            refusals[reason] = refusals.get(reason, 0) + 1
            continue
        spelled = {
            citation
            for ordinal, _ in neighbours
            for citation in usc_by_box.get((row["rin"], row["publication_id"], ordinal), set())
        }
        if spelled and (title, usc_section.lower()) not in spelled:
            refusals["neighbour-spells-another-section"] = refusals.get("neighbour-spells-another-section", 0) + 1
            continue
        donor = next(ordinal for ordinal, keys in neighbours if act_key in keys)
        _apply_corroboration(row, SIBLING_ACT_RULE, (_act_emission(act_key, section),), tally, calendar)
        row["act_resolution_sibling_ordinal"] = donor
        carried += 1
    return _SiblingActCensus(rows=carried, refusals=dict(sorted(refusals.items())))


# --------------------------------------------------------------------------- #
# The list that outran its box, put back together WITHOUT rewriting anything.
# --------------------------------------------------------------------------- #

#: A label the box names, in any of the spellings this corpus writes. A box
#: that names one is a DONOR -- it can govern a fragment -- and a box that
#: names one is never a fragment, because a fragment is a box that reads as
#: nothing for want of the label its neighbour has.
_JOIN_ANY_SCHEME = re.compile(
    r"\b(?:u\.?\s?s\.?\s?c|usc|c\.?\s?f\.?\s?r|cfr|stat|pub\.?\s?l|p\.?\s?l\b|pl\b|public\s+law"
    r"|e\.?\s?o\.?|exec(?:utive)?\s+order|f\.?\s?r\b|fed\.?\s*reg|reorg|proc\.?|proclamation"
    r"|treat|const|d\.?\s?c\.?\s?code|r\.?\s?s\.?)\b",
    re.IGNORECASE,
)

#: A label or connective left DANGLING at the end of a box -- the cut landed
#: mid-citation and the next box carries what it governs.
_JOIN_DANGLING_TAIL = re.compile(
    r"(?:^|[\s,;(])(?:"
    r"sec|secs|sect|sects|section|sections|§|§§|"
    r"pub|pub\.\s?l|p\.\s?l|pl|public\s+law|"
    r"u\.?\s?s\.?\s?c|usc|stat|c\.?\s?f\.?\s?r|cfr|"
    r"and|or|to|through|thru|no|nos"
    r")\.?$",
    re.IGNORECASE,
)
_JOIN_LEADING_CONNECTIVE = re.compile(r"^(?:and|or|to|through|thru|et\s+seq)\b", re.IGNORECASE)

#: One member of a section list, and the punctuation a list is cut at.
_JOIN_SECTION_TOKEN = re.compile(
    r"\d{1,5}[a-z]?(?:\.\d{1,3}[a-z]?)?(?:-\d{1,4}[a-z]?)?(?:\([^()]{1,12}\))*"
)
#: What may stand in front of the first section of a continuation: the
#: punctuation the cut left, a connective, and a section marker. The marker is
#: here because ``_BARE_SECTION_BOX`` admits one and the two shapes have to
#: agree -- "sec. 40503" is the same continuation "40503" is.
_JOIN_LEAD_STRIP = re.compile(
    r"^[\s,;)]*(?:and\s+|or\s+|to\s+|through\s+|thru\s+)?\s*(?:sec(?:tion)?s?\.?\s*|§{1,2}\s*)?",
    re.IGNORECASE,
)

#: A box that is nothing but a comma list of section-shaped tokens: Tier B's
#: whole population, and the shape "secs. 1.5, 1.7, 1.10" / "1.11, 1.12, 2.2"
#: is cut into.
_JOIN_SECTION_LIST_BOX = re.compile(
    r"^(?:and|or|,)?\s*(?:sec(?:tion)?s?\.?|§{1,2})?\s*"
    r"\d{1,5}[a-z]?(?:\.\d{1,3}[a-z]?)?(?:\([^()]{1,12}\))*"
    r"(?:\s*[,;]\s*(?:and\s+)?\d{1,5}[a-z]?(?:\.\d{1,3}[a-z]?)?(?:\([^()]{1,12}\))*)*"
    r"\s*[.,;]?\s*$",
    re.IGNORECASE,
)

#: The citation columns a joined row carries out of the grammar. The two
#: STATEMENT columns are read separately, by the same readers the main emit
#: path uses, because a statement is what a row has instead of a resolution.
_JOIN_CITATION_COLUMNS: tuple[str, ...] = (
    "usc_title", "usc_section", "usc_section_end", "usc_section_span_rule",
    "usc_chapter", "usc_chapter_end", "usc_appendix", "usc_note",
    "cfr_title", "cfr_part", "cfr_section", "cfr_part_is_plausible",
    "reorganization_plan", "act_key", "act_section",
    "public_law", "executive_order", "statute_volume", "statute_page",
    "statute_page_text", "statute_volume_text", "statute_volume_matches_public_law",
    "case_reporter", "case_volume", "case_page",
    "presidential_doc_kind", "proclamation", "admin_order_kind", "admin_order_number",
    "treaty_series", "treaty_volume", "treaty_number", "treaty_page",
    "constitution_article", "constitution_section",
    "eo_compilation_start", "eo_compilation_page",
    "fr_volume", "fr_page", "revised_statute_section", "dc_code_section",
)

#: What "the same citation" means to the join: the citation, statements
#: excluded. A joined reading that ADDS a statement to the citation its donor
#: already read has lost nothing -- and whether it may KEEP that statement is a
#: separate question, which ``_join_arrivals`` asks.
_JOIN_CITATION_IDENTITY: tuple[str, ...] = tuple(
    column for column in _CITATION_IDENTITY_COLUMNS if column != "authority_type"
)

#: The two types that TAKE a stated section. A U.S.C. citation's section is a
#: structural field and a chapter has none, so a "sec N" arriving beside either
#: is a second authority rather than that citation's pinpoint.
_JOIN_TYPES_THAT_TAKE_A_SECTION = frozenset({"public_law", "statute_at_large"})


def _join_continues_a_section_list(text: str) -> bool:
    """Whether the box opens with a SECTION and then only list furniture.

    "42 2000d-1", "10 ch 137" and "18 U,S,C, 5039" open with a U.S.C. TITLE
    whose label was lost, not with a section, and a join reading that title as
    a section of the donor's title mints a place nobody cited -- 40 U.S.C. 42,
    15 U.S.C. 15, 18 U.S.C. 18. What may follow the section is a list
    separator, a subsection parenthesis, the end of the box, or a word the
    GRAMMAR itself names as citation structure ("note", "et seq.", "to"), so
    "1437f note and 3535(d)" keeps reading and "42 U.S" stops.
    """

    stripped = _JOIN_LEAD_STRIP.sub("", str(text or "").strip(), count=1)
    match = _JOIN_SECTION_TOKEN.match(stripped)
    if match is None:
        return False
    rest = stripped[match.end() :].lstrip()
    if not rest or rest[0] in ",;.":
        return True
    word = re.match(r"[A-Za-z]+", rest)
    return word is not None and names_citation_structure(word.group(0))


def _join_is_a_lone_title(text: str) -> bool:
    """A box holding NOTHING but a number a U.S.C. title could be.

    The most ambiguous thing this corpus writes: "12" beside "USC 2093" is the
    title its own label lost, and "12" absorbed into "12 USC 2073 to 2076"
    instead mints 12 U.S.C. 12 -- a real section nobody cited. "and 15" is not
    this: the connective is the filer saying the number continues a list, and
    7 U.S.C. 15 stays readable because of it.
    """

    stripped = str(text or "").strip()
    return stripped.isdigit() and usc_title_is_possible(int(stripped)) is True


def _join_right_signals(text: str) -> tuple[str, ...]:
    """The shapes that make this box a continuation of the one before it."""

    if (
        _JOIN_ANY_SCHEME.search(text)
        or _join_is_a_lone_title(text)
        or not _join_continues_a_section_list(text)
    ):
        return ()
    stripped = text.lstrip()
    signals: list[str] = []
    if stripped[:1] in {")", ",", ";"}:
        signals.append("fragment-right:R1-opens-with-close-or-comma")
    if _JOIN_LEADING_CONNECTIVE.match(stripped):
        signals.append("fragment-right:R3-opens-with-connective")
    if _BARE_SECTION_BOX.fullmatch(stripped):
        signals.append("fragment-right:R4-whole-box-is-a-bare-section")
    elif stripped[:1].isdigit():
        signals.append("fragment-right:R5-opens-with-digit-no-scheme")
    return tuple(signals)


def _join_left_signals(text: str) -> tuple[str, ...]:
    """The shapes that make this box something the NEXT one completes."""

    if _JOIN_ANY_SCHEME.search(text) or _join_is_a_lone_title(text):
        return ()
    stripped = text.rstrip()
    signals: list[str] = []
    if _JOIN_DANGLING_TAIL.search(stripped):
        signals.append("fragment-left:L1-dangling-label-or-connective")
    if stripped.endswith((",", ";", "-", "–", "—", "/", "&", "+")):
        signals.append("fragment-left:L2-open-punctuation")
    if stripped.count("(") > stripped.count(")"):
        signals.append("fragment-left:L3-unbalanced-paren")
    if _BARE_SECTION_BOX.fullmatch(stripped.lstrip()):
        signals.append("fragment-left:L4-whole-box-is-a-bare-section")
    return tuple(signals)


def _join_reads_nothing(rows: list[dict[str, object]]) -> bool:
    """NEED: every row this box produced reads as nothing.

    Asked AFTER corroboration and the sibling carry, deliberately: a box the
    RIN's own history or a damaged label already answered is not a fragment,
    and asking before them would absorb boxes another rule had read.
    """

    return bool(rows) and all(
        row["authority_type"] == "other" and row["parse_status"] == "failed" for row in rows
    )


def _join_citation_key(row: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(row.get(column) for column in _JOIN_CITATION_IDENTITY)


def _joined_citation_row(donor: Mapping[str, object], citation, joined: str, calendar) -> dict:
    """One row the joined string yields, on the DONOR's ordinal.

    ``authority_text`` is the donor box's own bytes, unchanged: the joined
    string lives in ``authority_join_text`` where a consumer can see exactly
    what was read, and nothing in this module ever rewrites what the filer
    typed.
    """

    row = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
    row.update(
        rin=donor["rin"],
        publication_id=donor["publication_id"],
        ordinal=donor["ordinal"],
        authority_text=donor["authority_text"],
        authority_source=donor["authority_source"],
        authority_type=citation.authority_type,
        parse_status=citation.parse_status,
        usc_appendix=False,
        usc_note=False,
    )
    row.update({column: getattr(citation, column) for column in _JOIN_CITATION_COLUMNS})
    row["stated_act_name"] = citation.stated_act_name or stated_act_name(joined)
    row["stated_section"] = citation.stated_section or stated_section(joined)
    publication_id = donor["publication_id"]
    row["usc_title_is_possible"] = calendar.usc_title_is_possible(citation.usc_title, publication_id)
    row["eo_in_known_series"] = calendar.eo_in_known_series(citation.executive_order)
    row["pl_congress_in_series"] = calendar.pl_congress_in_series(citation.public_law, publication_id)
    row["stat_volume_in_series"] = calendar.stat_volume_in_series(
        citation.statute_volume, publication_id
    )
    row["fr_volume_in_series"] = calendar.fr_volume_in_series(citation.fr_volume, publication_id)
    row["fr_page_in_series"] = calendar.fr_page_in_series(citation.fr_page)
    return row


def _join_arrivals(joined: str, donor_rows, present, all_fragments_are_bare: bool, calendar):
    """(rows, welded) -- what the joined string adds, and what it may not weld.

    An arrival that differs from a citation the donor already read ONLY in its
    statement is a stated section looking for a home. It gets one when the
    donor is a Public Law or a Statutes page -- those take a section -- and
    when every absorbed box is nothing but that section, so "sec.206" +
    "PL 106-159" joins and "sec 5008 (a) of the Recovery Act" does not: prose
    beside a law names its own act, and this rule does not adjudicate acts.
    """

    donor_keys = [
        _join_citation_key(row) for row in donor_rows if row["authority_type"] != "other"
    ]
    donor_takes_a_section = all(
        row["authority_type"] in _JOIN_TYPES_THAT_TAKE_A_SECTION for row in donor_rows
    )
    arrivals, welded = [], 0
    for citation in parse_authority_citation(joined):
        if citation.authority_type == "other":
            continue
        row = _joined_citation_row(donor_rows[0], citation, joined, calendar)
        identity = (row["authority_type"], *_join_citation_key(row),
                    row["stated_act_name"], row["stated_section"])
        if identity in present:
            continue
        if _join_citation_key(row) in donor_keys and not (
            all_fragments_are_bare and donor_takes_a_section and row["stated_act_name"] is None
        ):
            welded += 1
            continue
        arrivals.append(row)
    return arrivals, welded


def _boxes_by_record(authorities: list[dict[str, object]]):
    """The record's BOXES, by ordinal, with every row each one yielded.

    Two passes read the publisher's boxes as a sequence -- the box-run join and
    the title carry -- and both need the same grouping asked the same way: a
    continuation is not a box, and a box that exploded into several rows is
    still one box.
    """

    order: dict[tuple[object, object], dict[object, list[dict]]] = {}
    for row in authorities:
        if row["authority_source"] != AUTHORITY_SOURCE_BOX:
            continue
        order.setdefault((row["rin"], row["publication_id"]), {}).setdefault(
            row["ordinal"], []
        ).append(row)
    return order


@dataclass(frozen=True)
class _JoinCensus:
    """What the join published, and every refusal beside it."""

    runs: int
    boxes: int
    rows: int
    superseded: int
    list_continuation_runs: int
    list_continuation_boxes: int
    rules: dict[str, int]
    refusals: dict[str, int]


def _join_box_runs(authorities: list[dict[str, object]], oracle, calendar) -> tuple[list, _JoinCensus]:
    """Put back the citation lists the publisher's boxes cut, and record it.

    Two tiers. TIER A is a box that names a scheme absorbing the consecutive
    boxes after it that read as nothing and continue its list, plus one such
    box before it. TIER B is a run of boxes that ALL read as nothing and are
    all bare comma lists: joining restores the filer's one list and yields no
    citation at all, which is recorded rather than published, because "these
    four boxes are one list" is true and useful even where nothing parses.

    Nothing is rewritten and nothing is dropped. The joined citations are new
    rows on the DONOR's ordinal; the absorbed boxes keep their rows and gain
    ``superseded_by_join``; ``authority_text`` and ``ordinal`` are untouched
    everywhere. An in-place rewrite would have moved 989 existing cells,
    including 20 ``stated_section`` and 3 ``stated_act_name`` values that would
    each have needed a proof of their own.
    """

    order = _boxes_by_record(authorities)

    rules: dict[str, int] = dict.fromkeys(AUTHORITY_JOIN_RULES, 0)
    refusals: dict[str, int] = dict.fromkeys(AUTHORITY_JOIN_REFUSALS, 0)
    census = {"runs": 0, "boxes": 0, "rows": 0, "superseded": 0, "b_runs": 0, "b_boxes": 0}
    joined_by_donor: dict[int, list[dict]] = {}

    for (_rin, publication_id), by_ordinal in order.items():
        ordinals = sorted(by_ordinal)
        if len(ordinals) < 2:
            continue
        texts = [str(by_ordinal[o][0]["authority_text"] or "") for o in ordinals]
        rows = [by_ordinal[o] for o in ordinals]
        silent = [_join_reads_nothing(r) for r in rows]
        placeholder = [bool(_unstated_kind(text)) for text in texts]
        donor = [bool(_JOIN_ANY_SCHEME.search(text)) for text in texts]
        used = [False] * len(ordinals)
        year = _SeriesCalendar._edition_year(publication_id)

        index = 0
        while index < len(ordinals):
            if placeholder[index] or silent[index] or used[index] or not donor[index]:
                index += 1
                continue
            # An anchor absorbs the consecutive fragments after it, and one
            # before: the publisher's list runs forward, and a cut that landed
            # before the label leaves exactly one orphan.
            last, signals = index, []
            while (
                last + 1 < len(ordinals)
                and silent[last + 1]
                and not placeholder[last + 1]
                and not used[last + 1]
            ):
                found = _join_right_signals(texts[last + 1])
                if not found:
                    break
                signals.append((last + 1, found[0]))
                last += 1
            first = index
            if index and silent[index - 1] and not placeholder[index - 1] and not used[index - 1]:
                found = _join_left_signals(texts[index - 1])
                if found:
                    signals.insert(0, (index - 1, found[0]))
                    first = index - 1
            if first == index and last == index:
                index += 1
                continue
            for position in range(first, last + 1):
                used[position] = True
            span = range(first, last + 1)
            joined = ", ".join(texts[position] for position in span)
            rule = signals[0][1]
            present = {
                (row["authority_type"], *_join_citation_key(row),
                 row["stated_act_name"], row["stated_section"])
                for position in span
                for row in rows[position]
            }
            all_bare = all(
                _BARE_SECTION_BOX.fullmatch(texts[position].strip()) is not None
                for position, _signal in signals
            )
            arrivals, welded = _join_arrivals(
                joined, rows[index], present, all_bare, calendar
            )
            produced = [
                citation
                for citation in parse_authority_citation(joined)
                if citation.authority_type != "other"
            ]
            reason = None
            # A join may only ADD. Every value the donor read alone has to
            # survive in some joined reading, or the join is a different
            # citation rather than a longer one.
            if not all(
                any(
                    all(getattr(citation, column, None) == value for column, value in stated.items())
                    for citation in produced
                )
                for stated in (
                    {
                        column: row[column]
                        for column in _JOIN_CITATION_IDENTITY
                        if row[column] is not None and row[column] is not False
                    }
                    for row in rows[index]
                    if row["authority_type"] != "other"
                )
            ):
                reason = "the-join-loses-what-the-donor-already-read"
            elif any(
                row["authority_type"] == "usc"
                and row["usc_title"]
                and row["usc_section"]
                and (
                    oracle is None
                    or oracle.section_verdict(
                        row["usc_title"], row["usc_section"], year, appendix=bool(row["usc_appendix"])
                    ).verdict
                    != "exists"
                )
                for row in arrivals
            ):
                reason = "the-oracle-does-not-print-a-section-the-join-mints"
            elif not arrivals:
                reason = (
                    "a-statement-welded-to-a-citation-that-has-its-own-section"
                    if welded
                    else "the-join-adds-no-citation"
                )
            if reason is not None:
                refusals[reason] += 1
                index = last + 1
                continue

            census["runs"] += 1
            census["boxes"] += last - first + 1
            census["rows"] += len(arrivals)
            rules[rule] += 1
            run = {
                "authority_box_run_start": int(ordinals[first]),
                "authority_box_run_length": last - first + 1,
                "authority_join_rule": rule,
                "authority_join_text": joined,
            }
            for position in span:
                for row in rows[position]:
                    row.update(run)
                    if position != index:
                        row["superseded_by_join"] = True
                        census["superseded"] += 1
            for row in arrivals:
                row.update(run)
            joined_by_donor.setdefault(id(rows[index][-1]), []).extend(arrivals)
            index = last + 1

        # Tier B: every box reads as nothing and every box is a bare comma
        # list. No citation comes of it and none is claimed; what is recorded
        # is that these boxes are ONE list, which nothing else in the table
        # says.
        index = 0
        while index < len(ordinals):
            if not (
                silent[index]
                and not placeholder[index]
                and not used[index]
                and _JOIN_SECTION_LIST_BOX.fullmatch(texts[index].strip())
            ):
                index += 1
                continue
            last = index
            while (
                last + 1 < len(ordinals)
                and silent[last + 1]
                and not placeholder[last + 1]
                and not used[last + 1]
                and _JOIN_SECTION_LIST_BOX.fullmatch(texts[last + 1].strip())
            ):
                last += 1
            if last > index:
                span = range(index, last + 1)
                run = {
                    "authority_box_run_start": int(ordinals[index]),
                    "authority_box_run_length": last - index + 1,
                    "authority_join_rule": "list-continuation",
                    "authority_join_text": ", ".join(texts[position] for position in span),
                }
                for position in span:
                    used[position] = True
                    for row in rows[position]:
                        row.update(run)
                census["b_runs"] += 1
                census["b_boxes"] += last - index + 1
                rules["list-continuation"] += 1
            index = last + 1

    if not joined_by_donor:
        rebuilt = authorities
    else:
        rebuilt = []
        for row in authorities:
            rebuilt.append(row)
            rebuilt.extend(joined_by_donor.pop(id(row), ()))
    return rebuilt, _JoinCensus(
        runs=census["runs"],
        boxes=census["boxes"],
        rows=census["rows"],
        superseded=census["superseded"],
        list_continuation_runs=census["b_runs"],
        list_continuation_boxes=census["b_boxes"],
        rules=dict(sorted(rules.items())),
        refusals=dict(sorted(refusals.items())),
    )


# --------------------------------------------------------------------------- #
# The title the box beside it states.
# --------------------------------------------------------------------------- #

#: One member of a title-less section box, and the whole box. Wider than
#: ``_BARE_SECTION_BOX`` in exactly one direction: a trailing group of
#: SUBSECTIONS is part of the section before it, not a new member, so
#: "41102(2), (4) and (8)" is one section and reads as one.
_CARRY_SECTION = r"\d{1,5}[a-z]{0,3}(?:-\d{1,4}[a-z]?)?(?:\([^()]{1,12}\))*"
_CARRY_MEMBER = rf"(?:{_CARRY_SECTION}|\([^()]{{1,12}}\))"
#: Members are SEPARATED, and a bare space is not a separator. "42 2000d-1" and
#: "15 1681s-2" are two section-shaped tokens with nothing between them, and
#: they are not lists: they are "42 U.S.C. 2000d-1" and "15 U.S.C. 1681s-2"
#: with the label gone, and a carry that read the first as a section published
#: 40 U.S.C. 42 and 15 U.S.C. 15. A space IS allowed before a parenthesised
#: group, because a subsection is often spaced off its section ("1819 (Tenth)",
#: "1813 (m)").
_CARRY_GROUP = r"\s*\([^()]{1,12}\)"
_CARRY_SEPARATED = (
    rf"(?:\s*[,;]\s*(?:and\s+|or\s+|to\s+|through\s+)?{_CARRY_MEMBER}"
    rf"|\s+(?:and|or|to|through)\s+{_CARRY_MEMBER}"
    rf"|{_CARRY_GROUP})"
)
_TITLELESS_SECTION_BOX = re.compile(
    rf"^(?:and\s+|or\s+)?(?:sec(?:tion)?s?\.?\s*|§{{1,2}}\s*)?{_CARRY_SECTION}"
    rf"{_CARRY_SEPARATED}*"
    r"(?:\s*(?:,\s*)?(?:et\s+seq\.?|as\s+amended|note))?\s*[.,;]?\s*$",
    re.IGNORECASE,
)
_CARRY_LEAD_MARKER = re.compile(
    r"^(?:and\s+|or\s+)?(?:sec(?:tion)?s?\.?\s*|§{1,2}\s*)", re.IGNORECASE
)
#: "93-87" is a Public Law number wearing a section's shape.
_CARRY_PUBLIC_LAW_SHAPE = re.compile(r"(?:and\s+|or\s+)?\d{1,3}-\d{1,4}\s*[.,;]?", re.IGNORECASE)

#: How far back a title may be carried. Six boxes is the measured reach of the
#: candidate population; beyond it the "last stated title" stops being a fact
#: about the list the filer was writing.
TITLE_CARRY_MAX_DISTANCE = 6

TITLE_CARRY_RULE = "sibling-usc-title-within-six-boxes"

#: Why a title-less section box kept its silence. Counted by the fence that
#: spoke: this rule refuses four times what it answers, and the shape of the
#: refusals is the argument that it is narrow rather than shy.
TITLE_CARRY_REFUSALS: tuple[str, ...] = (
    #: The box-run join already read this box as part of its neighbour's list.
    #: Nothing is read twice.
    "the-join-already-absorbed-the-box",
    #: No single U.S.C. title in the six boxes before it -- none at all, or two
    #: that disagree. A carry that chose would be guessing.
    "no-single-title-in-the-six-boxes-before",
    #: The box writes "sec N", and an ACT section is not a Code section.
    #: SSA sec. 1861 is 42 U.S.C. 1395x, and 42 U.S.C. 1861 is the National
    #: Science Foundation Act -- both real, and no question this rule can put
    #: to the oracle separates them. 19 of the 19 boxes measured this way were
    #: act sections wearing a Code title.
    "the-box-writes-sec-and-an-act-section-is-not-a-code-one",
    #: The whole box is a number a U.S.C. TITLE could be. The same ambiguity
    #: the join refuses, for the same reason.
    "the-box-is-a-lone-title",
    #: "93-87" is a Public Law number, not a section.
    "the-box-is-shaped-like-a-public-law-number",
    #: The carried string does not read as a citation at all.
    "the-carry-does-not-read",
    #: The oracle does not print a section -- or a RANGE END -- the carry would
    #: mint, at the edition's year.
    "the-oracle-does-not-print-a-section-the-carry-mints",
)


@dataclass(frozen=True)
class _TitleCarryCensus:
    """What the carry answered, and every refusal beside it."""

    boxes: int
    rows: int
    shaped_boxes: int
    silent_boxes: int
    refusals: dict[str, int]


ACT_CARRY_RULE = "sibling-act-from-an-earlier-box"

#: Why a bare-section box under an act-naming box kept its silence. Counted by
#: the fence that spoke, like every other refusal here.
ACT_CARRY_REFUSALS: tuple[str, ...] = (
    #: No box before it in this record names an act, or the last one that did
    #: named two and the carry refuses to choose.
    "no-single-act-named-earlier-in-the-record",
    #: The box-run join already read this box as part of its neighbour's list.
    #: Nothing is read twice.
    "the-join-already-absorbed-the-box",
    #: THE DATE TRAP. "11/04/1980" (1105-AB50) is a Federal Register issue
    #: date continuing the box before it, and a separator set that admitted
    #: "/" would read it as sections 11, 04 and 1980. The shape below does not
    #: admit "/" at all; this fence is stated and counted anyway, because a
    #: guard nobody can see is a guard nobody can keep.
    "the-box-separates-its-numbers-with-a-slash",
    #: The whole box is a number a U.S.C. TITLE could be, or a Public Law
    #: number wearing a section's shape. The title carry's own two fences,
    #: asked here for the same reason.
    "the-box-is-a-lone-title-or-a-public-law-number",
    #: The members are joined by "to"/"through". An act citation has ONE
    #: section column and no end, so "secs 1301 to 1343" of the Affordable
    #: Care Act could only be published as its two ends -- dropping 1302 to
    #: 1342, which is the "reading one member is dropping the rest" defect
    #: this module refuses everywhere else. 5 boxes, and they are a gap this
    #: schema has rather than a reading nobody found.
    "the-box-states-a-range-an-act-citation-cannot-hold",
    #: A DOTTED section number. The Farm Credit Act numbers its sections N.NN
    #: and 3052-AD51's "secs.4.12, 5.9, 5.17, 8.11" resolve perfectly under
    #: it -- but NO BOX IN THAT RECORD STATES THAT ACT (the donor box is
    #: truncated to "Credit Act", which the index does not hold), so the
    #: resolution would rest on the reader knowing which act numbers sections
    #: that way. Refused by name. Zero here, because the shape excludes dots
    #: too; carried so the count says so.
    "the-box-states-a-dotted-section-number",
    #: The DONOR box states a U.S.C. citation of its own. "Credit Act (12
    #: U.S.C. 2183" followed by "2243, 2244, 2252, 2277a" is an open U.S.C.
    #: list the filer cut across boxes, not four sections of an act, and the
    #: numbers are U.S.C. sections either way -- reading them as act sections
    #: would publish a different citation from the one the box beside them
    #: spells out.
    "the-donor-box-spells-a-usc-citation-of-its-own",
    #: The resolver does not answer the member. Table III holds no row for
    #: that section of that act, so the carry has no corroboration at all --
    #: the same fence ``_carry_sibling_acts`` states as "a carried act that
    #: resolves to nothing is not evidence that the carry was right".
    "the-resolver-does-not-answer-a-section-the-carry-mints",
)

#: The refusal reasons that are an ANSWER rather than a silence: Table III
#: holds the act's section and says it reaches a statutory note instead of a
#: Code section. 2130-AC05/AC10/AC20 write "sec 412 (uncodified)" in the box
#: itself, and publishing "the Rail Safety Improvement Act of 2008, section
#: 412, which is a note" is the fact the filer stated. Every other refusal of
#: the resolver's leaves the box silent.
_ACT_CARRY_ANSWERED_REFUSALS = frozenset({"usc_section_not_expressible", "resolves_to_note"})


@dataclass(frozen=True)
class _ActCarryCensus:
    """What the act carry emitted, and every refusal beside it."""

    boxes: int
    rows: int
    max_distance: int
    refusals: Mapping[str, int]


#: A "to"/"through" between two members, which is a RANGE and not a list.
_ACT_CARRY_RANGE = re.compile(r"\b(?:to|through)\b", re.IGNORECASE)
#: One member of a carried box, section and subsections together.
_ACT_CARRY_MEMBER = re.compile(r"\d{1,5}[a-z]{0,3}(?:-\d{1,4}[a-z]?)?(?:\s*\([^()]{1,12}\))*")


def _act_naming_a_box(
    record_rows: list[dict[str, object]],
    rin: str,
    index: ActIndex,
    oracles: _ActOracles | None,
) -> tuple[str | None, str | None]:
    """(how the box names an act, which act) -- ``(None, None)`` when it names none.

    Three ways a box can name an act, strongest first, and the second and third
    exist because the specimen needs them: CMS RIN 0936-AA07's box 0 is
    ``1007: SSA subsection 1902 (a) (61)``, which reads as NOTHING -- no act
    key, no stated name, ``stated_act_name`` needs the literal word "Act" --
    and the four boxes after it are bare Social Security Act sections. The act
    is in that box, written as three letters, and the RIN's own roster is what
    turns those letters into the act.

    A box naming TWO acts names none of them for this purpose: the second
    element of the pair is None and the caller drops its donor rather than
    choosing.
    """

    keys = {row["act_key"] for row in record_rows if row["act_key"]}
    if keys:
        return "act-key", next(iter(keys)) if len(keys) == 1 else None
    stated = {row["stated_act_name"] for row in record_rows if row["stated_act_name"]}
    if stated:
        resolved = {resolve_act_name(normalize_popular_name(name), index) for name in stated}
        resolved.discard(None)
        return "stated-name", next(iter(resolved)) if len(resolved) == 1 else None
    if oracles is None:
        return None, None
    text = str(record_rows[0]["authority_text"] or "")
    survivors: set[str] = set()
    for token in {t for t in _ABBREV_INITIALISM.findall(text) if t not in _ABBREV_LABEL_TOKENS}:
        for roster in oracles.rosters(rin):
            found = _abbrev_survivors(token, None, roster)
            if found:
                survivors |= set(found)
                break
    if not survivors:
        return None, None
    return "roster-initialism", next(iter(survivors)) if len(survivors) == 1 else None


def _carry_acts_from_an_earlier_box(
    authorities: list[dict[str, object]],
    index: ActIndex | None,
    credits: SourceCreditIndex | None,
    oracles: _ActOracles | None,
    tally: _Tally,
    calendar: _SeriesCalendar,
) -> tuple[list[dict[str, object]], _ActCarryCensus]:
    """Give a box holding only section numbers the act an EARLIER box named.

    The act analogue of ``sibling-usc-title-within-six-boxes``, and the same
    argument: an act section number says nothing about which act it belongs
    to, and for 53 boxes of this corpus the act is in a box the filer wrote
    once and did not repeat. CMS RIN 0936-AA07, Fall 2017, is the shape --
    ``1007: SSA subsection 1902 (a) (61)``, then ``1903 (a)(6)``,
    ``1903(b)(3)``, ``1903(q)``, ``1102``, four boxes that read as nothing and
    are Social Security Act sections 1903 and 1102, 42 U.S.C. 1396b and 1302.

    Three things separate it from ``sibling-act-at-ordinal±1``, which stays
    exactly as it was:

    1. **The donor persists.** It is not the box at ±1, it is the last box in
       the record that named an act, and it governs until another box names a
       different one. The specimen's donor is four boxes back by the end of
       the list. A box that names TWO acts clears the donor rather than
       choosing between them.
    2. **The taker may be a LIST.** ``_TITLELESS_SECTION_BOX`` rather than
       ``_BARE_SECTION_BOX``, so ``2243, 2244, 2252`` is read as three members
       and each is resolved on its own -- reading only the first is dropping
       the rest.
    3. **A section Table III calls a NOTE is published as one.** The
       ±1 rule emits nothing where the resolver refuses, which is right for a
       rule with no other corroboration; here the box itself often says
       ``(uncodified)``, and "the Rail Safety Improvement Act of 2008, section
       412, which the Code carries as a note" is a fact rather than a gap.
       Every other refusal of the resolver's still leaves the box silent.

    Runs after the box-run join and the title carry, so a box either of them
    already read is never read twice.
    """

    refusals: dict[str, int] = dict.fromkeys(ACT_CARRY_REFUSALS, 0)
    if index is None:
        return authorities, _ActCarryCensus(boxes=0, rows=0, max_distance=0, refusals=refusals)
    carried_extras: dict[int, list[dict[str, object]]] = {}
    boxes = rows = max_distance = 0
    for (rin, _publication_id), by_ordinal in _boxes_by_record(authorities).items():
        ordinals = sorted(by_ordinal)
        donor: tuple[object, str] | None = None
        for position, ordinal in enumerate(ordinals):
            record_rows = by_ordinal[ordinal]
            text = _WRAPPING_QUOTES.sub("", str(record_rows[0]["authority_text"] or "")).strip()
            how, act_key = _act_naming_a_box(record_rows, rin, index, oracles)
            reading = _join_reads_nothing(record_rows) and not _JOIN_ANY_SCHEME.search(text) and (
                _TITLELESS_SECTION_BOX.fullmatch(text) is not None
            )
            if not reading:
                if how is not None:
                    donor = (ordinal, act_key, position) if act_key else None
                continue
            if donor is None:
                refusals["no-single-act-named-earlier-in-the-record"] += 1
                continue
            if any(row.get("superseded_by_join") for row in record_rows):
                refusals["the-join-already-absorbed-the-box"] += 1
                continue
            if "/" in text:
                refusals["the-box-separates-its-numbers-with-a-slash"] += 1
                continue
            if _join_is_a_lone_title(text) or _CARRY_PUBLIC_LAW_SHAPE.fullmatch(text):
                refusals["the-box-is-a-lone-title-or-a-public-law-number"] += 1
                continue
            if _ACT_CARRY_RANGE.search(text):
                refusals["the-box-states-a-range-an-act-citation-cannot-hold"] += 1
                continue
            members = [match.group(0) for match in _ACT_CARRY_MEMBER.finditer(text)]
            if any("." in member for member in members):
                refusals["the-box-states-a-dotted-section-number"] += 1
                continue
            if any(
                row["usc_title"] is not None and row["usc_section"]
                for row in by_ordinal[donor[0]]
            ):
                refusals["the-donor-box-spells-a-usc-citation-of-its-own"] += 1
                continue
            sections = [re.sub(r"\s+", "", member).split("(")[0].lower() for member in members]
            answered = [
                _resolve_one_act_citation(donor[1], section, index, credits) for section in sections
            ]
            if not answered or any(
                outcome[2] is None and outcome[3] not in _ACT_CARRY_ANSWERED_REFUSALS
                for outcome in answered
            ):
                refusals["the-resolver-does-not-answer-a-section-the-carry-mints"] += 1
                continue
            anchor = record_rows[-1]
            carried_extras[id(anchor)] = _apply_corroboration(
                anchor,
                ACT_CARRY_RULE,
                [
                    {**_act_emission(donor[1], section),
                     "act_resolution_sibling_ordinal": int(donor[0])}
                    for section in sections
                ],
                tally,
                calendar,
            )
            boxes += 1
            rows += len(sections)
            max_distance = max(max_distance, position - donor[2])

    if carried_extras:
        rebuilt: list[dict[str, object]] = []
        for row in authorities:
            rebuilt.append(row)
            rebuilt.extend(carried_extras.pop(id(row), ()))
        authorities = rebuilt
    return authorities, _ActCarryCensus(
        boxes=boxes, rows=rows, max_distance=max_distance, refusals=dict(sorted(refusals.items()))
    )


def _carry_usc_titles(
    authorities: list[dict[str, object]], oracle, tally: _Tally, calendar
) -> tuple[list[dict[str, object]], _TitleCarryCensus]:
    """A box holding nothing but section numbers takes the title beside it.

    The publisher's own list order again -- the third rule in this module to
    read it, after the Public Law split and the sibling act carry -- and the
    narrowest, because a U.S.C. section number says nothing about which title
    it belongs to. So the title comes from the nearest EARLIER box that states
    exactly one, within six; the carried string is handed to the GRAMMAR rather
    than assembled by hand; and every section AND every range end it produces
    has to be one the oracle prints at the edition's year. "89-670 and 91-605"
    under title 23 is why the end is gated too: 605 exists, and gating the
    start alone would have published it.

    Runs AFTER the box-run join, so a box the join already read is not read
    again, and after corroboration, so a box the RIN's own history answered
    (``rin-history-titleless-usc``, which is this same shape read from a
    different oracle) keeps that answer.
    """

    refusals: dict[str, int] = dict.fromkeys(TITLE_CARRY_REFUSALS, 0)
    shaped = silent = boxes = rows = 0
    #: The explosion rows, by the row they explode, so they can be placed
    #: BESIDE it rather than at the end of the file -- the posture
    #: ``_corroborate`` takes, and the reason a consumer reading in order meets
    #: a record's citations together.
    carried_extras: dict[int, list[dict[str, object]]] = {}
    for (_rin, publication_id), by_ordinal in _boxes_by_record(authorities).items():
        ordinals = sorted(by_ordinal)
        year = _SeriesCalendar._edition_year(publication_id)
        for position, ordinal in enumerate(ordinals):
            record_rows = by_ordinal[ordinal]
            text = str(record_rows[0]["authority_text"] or "").strip()
            if not _TITLELESS_SECTION_BOX.fullmatch(text) or _unstated_kind(text):
                continue
            shaped += 1
            if not _join_reads_nothing(record_rows):
                continue
            silent += 1
            if any(row.get("superseded_by_join") for row in record_rows):
                refusals["the-join-already-absorbed-the-box"] += 1
                continue
            donor = None
            for back in range(1, TITLE_CARRY_MAX_DISTANCE + 1):
                if position - back < 0:
                    break
                earlier = ordinals[position - back]
                titles = {
                    row["usc_title"] for row in by_ordinal[earlier] if row["usc_title"] is not None
                }
                if titles:
                    donor = (earlier, next(iter(titles))) if len(titles) == 1 else None
                    break
            if donor is None:
                refusals["no-single-title-in-the-six-boxes-before"] += 1
                continue
            if _CARRY_LEAD_MARKER.match(text):
                refusals["the-box-writes-sec-and-an-act-section-is-not-a-code-one"] += 1
                continue
            if _join_is_a_lone_title(text):
                refusals["the-box-is-a-lone-title"] += 1
                continue
            if _CARRY_PUBLIC_LAW_SHAPE.fullmatch(text):
                refusals["the-box-is-shaped-like-a-public-law-number"] += 1
                continue
            carried = f"{donor[1]} U.S.C. {text}"
            citations = list(parse_authority_citation(carried))
            if not citations or any(one.authority_type != "usc" for one in citations):
                refusals["the-carry-does-not-read"] += 1
                continue
            # EVERY section and EVERY range end. "89-670 and 91-605" under
            # title 23 reads 605 as a real section, and a gate on the start
            # alone would have let the range through on it.
            named = [
                (one.usc_title, section, one.usc_appendix)
                for one in citations
                for section in (one.usc_section, one.usc_section_end)
                if section is not None
            ]
            if oracle is None or not named or len(named) < len(citations) or any(
                oracle.section_verdict(title, section, year, appendix=appendix).verdict != "exists"
                for title, section, appendix in named
            ):
                refusals["the-oracle-does-not-print-a-section-the-carry-mints"] += 1
                continue
            emissions = [
                {
                    "authority_type": "usc",
                    "usc_title": one.usc_title,
                    "usc_section": one.usc_section,
                    "usc_section_end": one.usc_section_end,
                    "usc_section_span_rule": one.usc_section_span_rule,
                    "usc_appendix": one.usc_appendix,
                    "usc_note": one.usc_note,
                    "usc_title_carried_from_ordinal": int(donor[0]),
                    "authority_carry_text": carried,
                }
                for one in citations
            ]
            anchor = record_rows[-1]
            carried_extras[id(anchor)] = _apply_corroboration(
                anchor, TITLE_CARRY_RULE, emissions, tally, calendar
            )
            boxes += 1
            rows += len(emissions)

    if carried_extras:
        rebuilt: list[dict[str, object]] = []
        for row in authorities:
            rebuilt.append(row)
            rebuilt.extend(carried_extras.pop(id(row), ()))
        authorities = rebuilt
    return authorities, _TitleCarryCensus(
        boxes=boxes,
        rows=rows,
        shaped_boxes=shaped,
        silent_boxes=silent,
        refusals=dict(sorted(refusals.items())),
    )


#: Why a row that states an act name was left saying "other". Counted by the
#: fence, because this pass changes ONE column on 471 rows and what it declines
#: to change is the argument that the change is a label rather than a claim.
STATED_ACT_REFUSALS: tuple[str, ...] = (
    #: The closure DOES hold the name, and one of the two fences on
    #: ``index-holds-the-stated-name`` refused the key: a value naming an
    #: amendment, or one carrying a year the name itself does not. Those
    #: fences exist because an amendment is its own entry -- "Section 172(a) of
    #: the 1990 Clean Air Act amendments" is not the base act -- and typing the
    #: row here would assert the act-relative reading they exist to withhold.
    "the-closure-holds-the-name-and-a-fence-refused-the-key",
    #: The row states something besides its two statements, so it is not a row
    #: that read NOTHING and this pass has no business relabelling it.
    "the-row-states-more-than-a-name-and-a-section",
)


@dataclass(frozen=True)
class _StatedActCensus:
    """What the stated-act labelling typed, and everything it left alone."""

    rows: int
    states_something: int
    section_only_rows: int
    names_an_act_rows: int
    refusals: dict[str, int]


#: What a row may carry and still be offered to the stated-act labelling: the
#: keys, the text, the type and status, the two non-nullable flags, and the two
#: STATEMENTS -- which are the whole reason the row is offered.
_STATED_ACT_NEUTRAL_COLUMNS: frozenset[str] = frozenset({
    "rin", "publication_id", "ordinal", "citation_ordinal", "authority_text",
    "authority_source", "authority_type", "parse_status", "restates_box_citation",
    "usc_appendix", "usc_note", "stated_act_name", "stated_section",
})


def _type_stated_acts(
    authorities: list[dict[str, object]], act_lookup: Mapping[str, str] | None
) -> _StatedActCensus:
    """A row that names an act IS act-relative, even where nothing can resolve it.

    1,142 rows of this corpus read as nothing and yet state something: 624 a
    section alone, 518 an act's NAME. A consumer meets all of them as
    ``other``/``failed``, which says "unreadable" -- and for the 471 whose name
    the OLRC index holds no key for, the truth is narrower and more useful:
    this is an act-relative citation whose ACT the index cannot name. The table
    already has a word for that, ``act_not_in_index``, and a status for it --
    ``_ACT_UNKNOWN_REASONS`` keeps such a row "failed" -- so the row needs no
    new vocabulary and no new column.

    ONE COLUMN CHANGES: ``authority_type``, "other" -> "act_relative".
    ``parse_status`` stays "failed", the statements stay exactly where the
    filer put them (there is no act key to supersede them), and every other
    column on these rows was and stays NULL.

    It runs before :func:`_resolve_act_citations` so the resolver counts these
    rows in its own census rather than beside it, and it deliberately does NOT
    touch a row whose name the closure holds: those belong to
    ``index-holds-the-stated-name`` and to the two fences that guard it, and 0
    of them are left unread that its fences would pass.
    """

    refusals: dict[str, int] = dict.fromkeys(STATED_ACT_REFUSALS, 0)
    typed = states_something = section_only = names_an_act = 0
    for row in authorities:
        if row["authority_type"] != "other" or row["parse_status"] != "failed":
            continue
        if not row["stated_act_name"] and not row["stated_section"]:
            continue
        states_something += 1
        if not row["stated_act_name"]:
            section_only += 1
            continue
        names_an_act += 1
        if any(
            row.get(column) is not None and row.get(column) is not False
            for column in LEGAL_AUTHORITIES_SCHEMA.names
            if column not in _STATED_ACT_NEUTRAL_COLUMNS
        ):
            refusals["the-row-states-more-than-a-name-and-a-section"] += 1
            continue
        if act_lookup is not None and normalize_popular_name(row["stated_act_name"]) in act_lookup:
            refusals["the-closure-holds-the-name-and-a-fence-refused-the-key"] += 1
            continue
        row["authority_type"] = "act_relative"
        row["act_resolution_reason"] = "act_not_in_index"
        typed += 1
    return _StatedActCensus(
        rows=typed,
        states_something=states_something,
        section_only_rows=section_only,
        names_an_act_rows=names_an_act,
        refusals=dict(sorted(refusals.items())),
    )


def _resolve_act_citations(
    authorities: list[dict[str, object]],
    index: ActIndex | None,
    credits: SourceCreditIndex | None,
) -> _ActResolutionCensus:
    """Fill the U.S.C. section an act-relative row names, or say why not.

    The builder has recognised act-relative citations since it could read the
    OLRC name index, and has never once ASKED the resolver what they resolve
    to: all 9,065 rows came out with ``usc_title`` and ``usc_section`` NULL and
    6,214 of them saying parse_status "failed", which a consumer reads as
    "could not resolve" when every one of those parses had succeeded.

    Two rules make this a fill and never a move. **Only NULL columns are
    written** -- ``act_key`` and ``act_section`` stay exactly as the grammar
    read them, and the filer's own text stays in ``authority_text`` -- so a
    resolution can be dropped by ignoring two columns and nothing is lost.
    **Only a "failed" parse_status changes**: the 2,782 rows corroborated by
    RIN history keep that word, because their corroboration is a different fact
    from this resolution and 2,101 of them carry both.

    Run LAST, after both U.S.C. fences, deliberately. The section a resolution
    publishes is OLRC's answer about an act, not the filer's claim about the
    Code, so folding it into either fence would let derived rows move a verdict
    about what filers wrote -- and the magnitude ceiling those fences derive
    from the corpus's own rows would move with them. Every fence census here is
    a statement about the same population it was before.

    The section-existence oracle DOES see these sections, since 2026-08-24, in
    a pass and a census of its own that runs after this one
    (:func:`_judge_act_derived_sections`): Table III states what an act section
    maps to TODAY, and whether the citing edition printed that section is a
    dated question only the oracle answers. That pass writes three verdict
    columns and touches no identity column here.
    """

    memo: dict[tuple[str, str | None], tuple[int | None, str | None, str | None, str | None]] = {}
    rows_by_status: dict[str, int] = {}
    rows_by_reason: dict[str, int] = dict.fromkeys(ACT_RESOLUTION_REASONS, 0)
    rows_by_evidence: dict[str, int] = dict.fromkeys(ACT_RESOLUTION_EVIDENCE, 0)
    resolved_by_prior: dict[str, int] = {}
    pairs: dict[tuple[str, str], bool] = {}

    for row in authorities:
        row["act_resolution_evidence"] = None
        # A reason an earlier pass established about a row with NO act key is
        # not overwritten here. Keyless used to mean exactly one thing -- the
        # calendar refused the key the grammar proposed, 3 rows -- and since
        # the stated-act labelling it also means "the index holds no key for
        # the name this row states". Both are act-relative and both are
        # "failed"; only the row knows which, so the row is asked.
        stated_reason = row.get("act_resolution_reason")
        row["act_resolution_reason"] = None
        if row["authority_type"] != "act_relative":
            continue
        prior = row["parse_status"]
        if index is None:
            rows_by_status[prior] = rows_by_status.get(prior, 0) + 1
            continue
        act_key, section = row["act_key"], row["act_section"]
        if act_key is None:
            # The calendar refused the key the grammar proposed, so there is no
            # act to look up -- and the row still states what it states.
            title, usc_section, evidence, reason = (
                None, None, None, stated_reason or "act_key_refused_by_edition_calendar"
            )
        else:
            key = (act_key, section)
            if key not in memo:
                memo[key] = _resolve_one_act_citation(act_key, section, index, credits)
            title, usc_section, evidence, reason = memo[key]
            if section is not None:
                pairs[(act_key, section)] = evidence is not None
        if evidence is not None:
            row["usc_title"] = title
            row["usc_section"] = usc_section
            row["act_resolution_evidence"] = evidence
            rows_by_evidence[evidence] += 1
            resolved_by_prior[prior] = resolved_by_prior.get(prior, 0) + 1
            if prior == "failed":
                row["parse_status"] = "resolved"
        else:
            row["act_resolution_reason"] = reason
            rows_by_reason[reason] += 1
            if prior == "failed":
                row["parse_status"] = "failed" if reason in _ACT_UNKNOWN_REASONS else "partial"
        status = row["parse_status"]
        rows_by_status[status] = rows_by_status.get(status, 0) + 1

    return _ActResolutionCensus(
        rows_by_status=dict(sorted(rows_by_status.items())),
        rows_by_reason=rows_by_reason,
        rows_by_evidence=rows_by_evidence,
        resolved_rows_by_prior_status=dict(sorted(resolved_by_prior.items())),
        pairs_resolved=sum(1 for answered in pairs.values() if answered),
        pairs_refused=sum(1 for answered in pairs.values() if not answered),
    )


#: Spelling operators for act-name prose, each derived from the pinned index
#: by a declared convention and measured on the failed pool 2026-08-22. The
#: index stays the grammar: every operator produces CANDIDATE spellings the
#: closure must already know; no operator invents a name.
_AS_AMENDED_TAIL = re.compile(r"\s*[,(]?\s*as\s+amended\s*\)?\s*\.?\s*$", re.IGNORECASE)
_INTERNAL_PARENTHETICAL = re.compile(r"\s*\([^()]{1,60}\)")
_LEADING_DESIGNATOR = re.compile(
    r"^\s*(?:title|division|div\.?|subtitle|part)\s+[IVXLC0-9]+[A-Za-z]?\s+of\s+(?:the\s+)?",
    re.IGNORECASE,
)
_TRAILING_SECTION = re.compile(
    r",?\s*(?:sec(?:tion)?s?\.?|§{1,2})\s*(?P<section>\d{1,5}[A-Za-z]?)(?:\([^()]{1,12}\))*\s*$",
    re.IGNORECASE,
)
_YEAR_PREFIXED_NAME = re.compile(r"^\s*(?:the\s+)?((?:18|19|20)\d{2})\s+(\S.*)$", re.IGNORECASE)
#: The ELIDED list member: "Section 172(a) and (c)" is one section twice, not a
#: section and a nameless second thing. The filer omits the repeated number,
#: and until 2026-08-24 the list splitter required every "and"-joined member to
#: open on digits, so the whole match failed and the value recovered NOTHING --
#: not even the act. Review #2 traced it on 2060-AF01, where the same box's
#: four self-contained siblings ("Section 110(a)(2) of the 1990 Clean Air Act
#: amendments" and three more) all resolved, and on 0938-AM02's "1883(i)(l) and
#: (2) of the Social Security Act", where the unread 1883 was then taken for a
#: year by the fence downstream (notes/F.json).
#:
#: It joins the member it follows rather than starting one, because that is
#: what it means -- and this reader publishes the SECTION, dropping every
#: parenthesised tail from it, so a borrowed member adds no section this reader
#: would otherwise have published. The abbreviated-initialism shapes carry the
#: same elision ("CAA 112(d)(2) & (3)") and are deliberately not widened here;
#: that is task #44's unit, with its own roster fence.
_ELIDED_SECTION_MEMBER = r"(?:\s*(?:,|and|or)\s*\([^()]{1,8}\))*"
_SECTION_LIST_MEMBER = rf"{_ABBREV_SECTION_TOKEN}{_ELIDED_SECTION_MEMBER}"
#: Bare sections or a marker-led list/range in front of "of the <NAME>":
#: "205(u) and 1631(e)(7) of the Social Security Act", "sec 371 to 376 of
#: the Public Health Service Act". Whole-value only.
_SECTIONS_OF_NAME = re.compile(
    rf"^(?:[Ss]ec(?:tion)?s?\.?|§{{1,2}})?\s*"
    rf"(?P<sections>{_SECTION_LIST_MEMBER}(?:(?:\s*(?:,|and|or|to|through)\s*)+{_SECTION_LIST_MEMBER})*)"
    rf"\s*,?\s+of\s+(?:the\s+)?(?P<name>.+?)\s*$",
    re.DOTALL,
)
#: The connective-less spelling: "sec 307 FDA Food Safety Modernization
#: Act". The name must open on a capital; whole-value only.
_SECTION_NAME_ADJACENT = re.compile(
    rf"^(?:[Ss]ec(?:tion)?s?\.?|§{{1,2}})\s*"
    rf"(?P<sections>{_SECTION_LIST_MEMBER}(?:(?:\s*(?:,|and|or|to|through)\s*)+{_SECTION_LIST_MEMBER})*)"
    rf"\s+(?P<name>[A-Z].+?)\s*$"
)
#: Dropped before the list is split, so an elided member never becomes a member
#: of its own -- which would emit a second citation row stating the same
#: section, since the split's own next step strips every parenthesis.
_ELIDED_MEMBER_TAIL = re.compile(r"\s*(?:,|\band\b|\bor\b)\s*\([^()]{1,8}\)")
_SECTION_LIST_SPLIT = re.compile(r"\s*(?:,|\band\b|\bor\b)\s*")


def _act_prose_recoveries(text: str, act_lookup) -> tuple[tuple[str, str | None], ...]:
    """(act_key, act_section) readings for act-name prose, or ().

    Every reading passes through ``act_lookup`` — the spelling closure over
    the pinned OLRC index — so the operators here only ever REACH spellings
    the index already answers for. A list of sections yields one reading per
    member, the executive-order-plural rule. A range member ("1154 to 1160")
    is kept as its stated pair, never expanded.
    """

    stripped = _SUBSECTION_GAP.sub("", _WRAPPING_QUOTES.sub("", text.strip()))

    def _lookup(candidate: str) -> str | None:
        key = normalize_popular_name(candidate)
        hit = act_lookup.get(key)
        if hit is None:
            hit = act_lookup.get(_LEADING_ARTICLE.sub("", key))
        return hit

    # Section-led whole-value shapes first: they carry the most structure.
    for shape in (_SECTIONS_OF_NAME, _SECTION_NAME_ADJACENT):
        match = shape.match(stripped)
        if match is None:
            continue
        name = _AS_AMENDED_TAIL.sub("", match.group("name"))
        name_candidates = [name, _INTERNAL_PARENTHETICAL.sub("", name)]
        # The year-prefix reordering composes here too: "sec. 403 of the
        # 2018 FAA Reauthorization Act" names the act of 2018.
        year_led = _YEAR_PREFIXED_NAME.match(name_candidates[-1])
        if year_led is not None:
            name_candidates.append(f"{year_led.group(2)} of {year_led.group(1)}")
        for candidate in name_candidates:
            hit = _lookup(candidate)
            if hit is not None:
                sections = tuple(
                    re.sub(r"\([^)]*\)", "", token).strip().lower().replace(" to ", "-").replace(" through ", "-")
                    for token in _SECTION_LIST_SPLIT.split(
                        _ELIDED_MEMBER_TAIL.sub("", match.group("sections"))
                    )
                    if token.strip()
                )
                return tuple((hit, section or None) for section in sections) or ((hit, None),)

    # Name-led operators, applied to one working copy so they compose:
    # ", as amended" and designator tails strip; a terminal "sec. N" is the
    # citation's own section; parentheticals drop; a leading year reorders.
    work = _AS_AMENDED_TAIL.sub("", stripped)
    section = None
    section_match = _TRAILING_SECTION.search(work)
    if section_match is not None:
        section = section_match.group("section").lower()
        work = work[: section_match.start()]
    while True:
        trimmed = _ACT_DESIGNATOR_TAIL.sub("", _AS_AMENDED_TAIL.sub("", work))
        if trimmed == work:
            break
        work = trimmed
    candidates = [work, _INTERNAL_PARENTHETICAL.sub("", work)]
    lead = _LEADING_DESIGNATOR.sub("", work)
    if lead != work:
        candidates.append(lead)
    year_prefixed = _YEAR_PREFIXED_NAME.match(_INTERNAL_PARENTHETICAL.sub("", work))
    if year_prefixed is not None:
        candidates.append(f"{year_prefixed.group(2)} of {year_prefixed.group(1)}")
    for candidate in candidates:
        hit = _lookup(candidate)
        if hit is not None:
            return ((hit, section),)
    return ()

#: A Public Law whose separator was lost: fused digits ("Pub. L. 108199" —
#: optionally with the value's own section tail, "Pub. L. 10811, sec 1503"),
#: a bare space ("PL 95 616"), or the range word where the dash belongs
#: ("Pub. L. 111 to 203" is Dodd-Frank; a genuine range of bare law numbers
#: names no congress and recovers nothing, so roster-existence of the pair
#: is the only reading that survives). Whole-value only; the to-form
#: tolerates the title-designator prefix one value carries.
_FUSED_PL = re.compile(
    r"^\s*(?:pub(?:lic)?\.?\s*l(?:aw)?\.?|p\.?\s*l\.?)\s*(?:no\.?\s*)?(?P<digits>\d{5,6})\s*"
    r"(?:,\s*(?:sec(?:tion)?s?\.?|§{1,2})\s*\d{1,5}[A-Za-z]?(?:\([^()]{1,8}\))*)?\s*$",
    re.IGNORECASE,
)
_SPACED_PL = re.compile(
    r"^\s*(?:pub(?:lic)?\.?\s*l(?:aw)?\.?|p\.?\s*l\.?)\s*(?:no\.?\s*)?"
    r"(?P<congress>[1-9]\d{1,2})\s+(?P<number>[1-9]\d{0,3})\s*$",
    re.IGNORECASE,
)
_TO_SEPARATOR_PL = re.compile(
    r"^\s*(?:title\s+[IVXLC]+\s*,\s*)?(?:pub(?:lic)?\.?\s*l(?:aw)?\.?|p\.?\s*l\.?)\s*(?:no\.?\s*)?"
    r"(?P<congress>[1-9]\d{1,2})\s+to\s+(?P<number>[1-9]\d{0,3})\s*$",
    re.IGNORECASE,
)
#: The pair stated with the LABEL between its halves instead of a dash:
#: "94 Pub. L. 588" for Pub. L. 94-588 (0596-AD59 202504, the National Forest
#: Management Act; review #2 class D), "114 Pub. L. 185" for the FOIA
#: Improvement Act. Same fence as its two neighbours above -- the pair must
#: exist in the pinned roster with a congress inside the numbered series -- and
#: that fence does the whole work here, because the halves READ THE OTHER WAY
#: name no law: 588-94 and 185-114 are outside the series that ever legislated.
_REORDERED_PL = re.compile(
    r"^\s*(?P<congress>[1-9]\d{1,2})\s*(?:pub(?:lic)?\.?\s*l(?:aw)?\.?|p\.?\s*l\.?)\s*"
    r"(?:no\.?\s*)?(?P<number>[1-9]\d{0,3})\s*[.,]?\s*$",
    re.IGNORECASE,
)


_ACT_KEY_YEAR = re.compile(r"(1[7-9]\d\d|20\d\d)\s*$")
#: The same range, unanchored: every year an authority value or an act's own
#: published name states.
_ACT_TEXT_YEAR = re.compile(r"\b(1[7-9]\d\d|20\d\d)\b")


def _act_key_within_calendar(act_key, publication_id, tally: _Tally) -> str | None:
    """The act key, unless it names a year the citing edition had not reached."""

    if not act_key:
        return act_key
    year = _ACT_KEY_YEAR.search(act_key)
    if year is None:
        return act_key
    edition = str(publication_id or "")[:4]
    if not edition.isdigit() or int(year.group(1)) <= int(edition):
        return act_key
    tally.anachronisms += 1
    return None


#: The two shapes that STATE the pair and lost only the glyph between its
#: halves. Their fence is identical -- roster existence of the stated pair,
#: congress inside the numbered series -- so what separates them is the name of
#: the damage, and the name is what a consumer reads in
#: ``pl_correction_evidence``. The fused shape is NOT in this table because its
#: operator is a different thing: it has to FIND the pair, not check one.
_STATED_PL_PAIR_SHAPES: tuple[tuple[re.Pattern[str], str], ...] = (
    (_SPACED_PL, "space-separator-roster-existence"),
    (_TO_SEPARATOR_PL, "to-separator-roster-existence"),
    (_REORDERED_PL, "reordered-public-law-roster-existence"),
)


def _corroborated_public_law_from_failed(text: str, roster) -> tuple[str, str] | None:
    """A Public Law recovered from a separator-damaged whole value, or None.

    Fail-closed like every corroborated correction: candidates come from a
    named damage operator (a dash inserted at each split of the fused run; the
    stated pair for the spaced and to-forms), must EXIST in the pinned roster
    with a congress inside the numbered series, and exactly one may survive.
    "Pub. L. 108199" -> 108-199 (the split 10-8199 names no congress that ever
    legislated; 1081-99 is out of series); "PL 95 616" -> 95-616;
    "Pub. L. 111 to 203" -> 111-203, which is Dodd-Frank -- a genuine range of
    bare law numbers names no congress and recovers nothing, so roster
    existence of the pair is the only reading that survives; and
    "94 Pub. L. 588" -> 94-588, the pair written with the LABEL between its
    halves rather than a dash.
    """

    dates, _volumes = roster

    def exists(congress: int, number: int) -> bool:
        return (
            PL_FIRST_NUMBERED_CONGRESS <= congress <= CONGRESS_CURRENT
            and (congress, number) in dates
        )

    fused = _FUSED_PL.match(text)
    if fused is not None:
        digits = fused.group("digits")
        survivors = [
            f"{int(digits[:split])}-{int(digits[split:])}"
            for split in (2, 3)
            if not digits[split:].startswith("0") and exists(int(digits[:split]), int(digits[split:]))
        ]
        return (survivors[0], "unique-dash-insertion") if len(survivors) == 1 else None

    for shape, evidence in _STATED_PL_PAIR_SHAPES:
        match = shape.match(text)
        if match is None:
            continue
        congress, number = int(match.group("congress")), int(match.group("number"))
        if exists(congress, number):
            return f"{congress}-{number}", evidence
    return None


_TEXT_DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),?\s+((?:1[89]|20)\d{2})"
)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ("January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"))}


def _digit_variants(token: str) -> set[str]:
    """The named damage operators: adjacent transposition and single drop."""

    out = set()
    for i in range(len(token) - 1):
        out.add(token[:i] + token[i + 1] + token[i] + token[i + 2:])
    for i in range(len(token)):
        dropped = token[:i] + token[i + 1:]
        if dropped and dropped[0] != "0":
            out.add(dropped)
    out.discard(token)
    return out


def _corrected_public_law(text: str, congress: int, law: int, roster) -> tuple[str, str] | None:
    """Corroborated correction of an out-of-series Public Law, or None.

    Fail-closed: candidates come from named damage operators on the congress
    token, must EXIST in the pinned roster, must match any date the string
    itself states, and exactly one may survive. "155-271, Title VIII
    (October 24, 2018)" -> 115-271 is a derivation — the roster says 115-271
    was approved 10/24/2018 — not a guess.
    """

    dates, _volumes = roster
    stated = _TEXT_DATE.search(text)
    stated_date = (
        f"{_MONTHS[stated.group(1)]:02d}/{int(stated.group(2)):02d}/{stated.group(3)}"
        if stated else None
    )
    survivors = []
    for variant in _digit_variants(str(congress)):
        candidate = (int(variant), law)
        if candidate not in dates:
            continue
        if stated_date is not None and dates[candidate] != stated_date:
            continue
        survivors.append(candidate)
    if len(survivors) != 1:
        return None
    winner = survivors[0]
    evidence = "date-matched" if stated_date else "unique-roster-existence"
    return f"{winner[0]}-{winner[1]}", evidence


@dataclass(frozen=True)
class _ActOracles:
    """Everything the act-name rules are allowed to consult, and nothing else.

    ``lookup`` is the spelling closure over the pinned OLRC index; the two
    rosters hold the act keys the GRAMMAR resolved, at the RIN and at the
    agency; ``glosses`` holds the expansions the corpus wrote for its own
    abbreviations.

    The corpus-wide roster is deliberately absent, and its absence is the
    fence that carries the accuracy. "CAA" reaches both the Clean Air Act and
    the Consolidated Appropriations Act, 2014 corpus-wide — only the agency
    fence makes uniqueness — and wave 5 measured the corpus-wide roster
    inventing a wrong survivor 15.25% of the time even date-bounded. A row
    whose own agency is silent therefore stays refused rather than borrowing
    another agency's testimony.
    """

    lookup: Mapping[str, str]
    keys_by_rin: Mapping[str, set[str]]
    keys_by_agency: Mapping[str, set[str]]
    glosses: Mapping[str, dict[str, set[str]]]
    #: The pinned initialism roster, the one oracle here that is a FILE rather
    #: than something the corpus said about itself. It sits inside this
    #: dataclass for the reason the dataclass exists: an act rule may consult
    #: it and nothing else may, and what it is allowed to answer is fixed by
    #: the tier in each of its rows rather than by the rule that asks.
    pinned: Mapping[tuple[str, str], tuple[_InitialismRosterEntry, ...]] | None = None

    def pinned_rows(self, abbreviation: str, rin: str) -> tuple[_InitialismRosterEntry, ...]:
        """What the pinned roster says about this token AT THIS AGENCY."""

        if self.pinned is None:
            return ()
        return self.pinned.get((abbreviation.upper(), rin[:4]), ())

    def rosters(self, rin: str) -> tuple[Collection[str], Collection[str]]:
        """The same two altitudes ``_oracle_levels`` names, as act rosters."""

        return self.keys_by_rin.get(rin, ()), self.keys_by_agency.get(rin[:4], ())


def _read_abbreviated_act(row, oracles: _ActOracles):
    """"CAA sec 112" resolves only against the publisher's own resolved-act
    roster -- the same RIN's authority lists first (wave 2's oracle, measured
    2026-08-21 with zero ambiguous survivors), then the same agency's.

    "INA 212" at a DHS RIN resolves because DHS RINs spell out the Immigration
    and Nationality Act, which is the testimony the wave-1 identity fence
    demanded before it would read "INA". Measured 2026-08-22: the agency
    oracle agrees with the RIN oracle on all 339 rows both answer, and answers
    1,323 more with zero ambiguous survivors.

    Where a level answers several ways the corpus's own gloss discriminates,
    and only then -- the gloss cannot NAME an act (it is not an index name),
    it can only pick among acts the fenced roster already holds.
    """

    reading = _abbrev_act_reading(row["authority_text"])
    if reading is None:
        return None
    abbreviation, year, sections, marked = reading
    if abbreviation.split("-")[0] in _ABBREV_LABEL_TOKENS:
        return None
    gloss = oracles.glosses.get(row["rin"][:4], {}).get(abbreviation)

    def survivors_of(keys) -> list[tuple[str, str]]:
        survivors = _abbrev_survivors(abbreviation, year, keys)
        if len(survivors) > 1:
            narrowed = _gloss_narrowed(gloss, survivors)
            if narrowed and len(narrowed) == 1:
                return [("agency-gloss-narrowed-initialism", narrowed[0])]
        return [("agency-roster-initialism", key) for key in survivors]

    answer = _first_level_answer(oracles.rosters(row["rin"]), survivors_of)
    if answer is None:
        return None
    rule, resolved = answer
    emitted = _corroborated_act_sections(resolved, year, sections, marked=marked)
    if emitted is None:
        return None
    return rule, [_act_emission(resolved, section) for section in (emitted or (None,))]


#: Why the pinned roster declined a row whose token it holds. Counted by the
#: fence that spoke, for the reason every refusal in this module is.
INITIALISM_ROSTER_REFUSALS: tuple[str, ...] = (
    #: The corpus's own roster reaches two or more acts by these initials. That
    #: refusal is older, better founded and NOT the roster's to overturn: "mma,
    #: sec 811" at CMS (0938-AQ16, Fall 2010) reaches the Medicare
    #: Modernization Act, the Balanced Budget Refinement Act and the Benefits
    #: Improvement and Protection Act, and this file carries an MMA/0938 row
    #: that must not save it.
    "the-corpus-roster-is-already-ambiguous",
    #: The corpus's own roster answered with exactly one act, so
    #: ``agency-roster-initialism`` had its turn and whatever stopped it there
    #: -- a year in the section slot, a section the act does not classify --
    #: stops it here too. The file may fill a silence; it may not argue with
    #: testimony.
    "the-corpus-roster-already-speaks",
    #: The whole-value shape read an initialism the roster has never heard of.
    #: The commonest refusal by far, and the one that says how much of this
    #: corpus's shorthand nobody has pinned yet.
    "the-roster-does-not-hold-this-token",
    #: The token is in the roster and this agency is not. Every row is keyed to
    #: the filer whose evidence was gathered, and a token travelling to another
    #: agency is exactly what the keying refuses.
    "no-roster-row-at-this-agency",
    #: NDAA and FOIA name a different act every year. The roster holds the
    #: years; the row states none, and no year means no act.
    "the-roster-row-is-keyed-by-a-year-the-text-does-not-state",
    #: ``ambiguous`` or ``belief-only``: the roster looked and could not say.
    "the-roster-row-names-no-act",
    #: The token names a directive, an agency, a treaty, a reporter, a
    #: standard, a division letter or an identifier. The row is TYPED and
    #: resolves nothing, which is the right answer rather than a failure.
    "the-token-is-not-an-act",
    #: ``candidate-index-match`` with no corroboration from the filer's own
    #: resolved acts. The name is recorded in ``act_initialism_roster`` as a
    #: candidate and nothing is published.
    "the-candidate-tier-is-unfenced-here",
    #: The name resolved, the section slot did not: a stated year that is not
    #: the act's, or a year-shaped token in an unmarked section slot.
    "the-sections-do-not-corroborate",
)


def _initialism_roster_entry(entries, year: str | None):
    """The one roster row a reading reaches, or None when none does.

    A year-keyed token (NDAA, FOIA) is several rows at one (token, agency), and
    which one a citation means is settled by the year IN THE TEXT and by
    nothing else -- the year-less row of such a token is the ``ambiguous`` one
    and says so itself.
    """

    by_year = {entry.year_key: entry for entry in entries}
    if year is not None and year in by_year:
        return by_year[year]
    return by_year.get("")


def _read_pinned_roster_act(row, oracles: _ActOracles, tally: _Tally):
    """"BBRA, sec 123" resolves against a FILE, because no record defines it.

    ``_read_abbreviated_act`` above answers where some other filing at the same
    agency spelled the act out. For 610 rows of this corpus nothing did:
    measured on the artifact built from dc59a800, the corpus roster finds no
    survivor at either level for 487 of them. Those letters are not
    recoverable from the corpus, and the pinned roster
    (``research/evidence/initialism-roster-2026-08-24/roster.csv``) is a
    publisher's or the filer's own word about what they expand to.

    **It runs after the corpus's own roster and never over it.** Where the
    agency's own filings reach one act, that rule has already spoken; where
    they reach two, the row is refused and stays refused. A file that broke
    that tie would be spending a general claim about letters on a question
    about which of two acts one filer meant.

    **The weakest tier is fenced twice.** ``candidate-index-match`` is nothing
    more than "the hypothesised name resolves in the pinned act index", which
    is the operator wave 5 measured inventing a wrong survivor 15.25% of the
    time; it publishes only where the RIN's or the agency's own resolved acts
    ALSO hold that act -- which they can, without the initials reaching it,
    because "USPHSA" is not "PHSA" and "BBRA" is not "MMSBBRA". Unfenced, the
    name is recorded as a candidate and nothing is published.

    **A token that names no act is typed rather than resolved.** "FSH 2709.11"
    is a Forest Service Handbook and "56 DCR 7413" is the District of Columbia
    Register; ``act_initialism_roster`` says so and the row keeps its honest
    "failed".
    """

    reading = _abbrev_act_reading(row["authority_text"])
    if reading is None:
        return None
    abbreviation, year, sections, marked = reading
    if abbreviation.split("-")[0] in _ABBREV_LABEL_TOKENS:
        return None
    entries = oracles.pinned_rows(abbreviation, row["rin"])

    def refuse(reason: str, note: str | None = None) -> None:
        """Count the fence that spoke, and leave its note where it has one."""

        tally.initialism_roster_refusals[reason] += 1
        if note is not None:
            row["act_initialism_roster"] = note

    if oracles.pinned is None:
        return None
    if not entries:
        return refuse(
            "no-roster-row-at-this-agency"
            if any(token == abbreviation.upper() for token, _ in oracles.pinned)
            else "the-roster-does-not-hold-this-token"
        )
    for keys in oracles.rosters(row["rin"]):
        survivors = _abbrev_survivors(abbreviation, year, keys)
        if len(survivors) > 1:
            return refuse("the-corpus-roster-is-already-ambiguous")
        if survivors:
            return refuse("the-corpus-roster-already-speaks")
    entry = _initialism_roster_entry(entries, year)
    if entry is None:
        return refuse("the-roster-row-is-keyed-by-a-year-the-text-does-not-state")
    note = f"{entry.token}@{entry.agency_prefix}"
    if entry.year_key:
        note += f"/{entry.year_key}"
    note += f" {entry.status}"
    if entry.not_an_act_type is not None:
        return refuse("the-token-is-not-an-act", note)
    if not entry.act_name:
        return refuse("the-roster-row-names-no-act", note)
    if entry.status == INITIALISM_ROSTER_FENCED_TIER and not any(
        entry.act_name in keys for keys in oracles.rosters(row["rin"])
    ):
        return refuse("the-candidate-tier-is-unfenced-here", f"{note} (candidate: {entry.act_name})")
    emitted = _corroborated_act_sections(entry.act_name, year, sections, marked=marked)
    if emitted is None:
        return refuse("the-sections-do-not-corroborate", note)
    return f"pinned-roster-initialism:{entry.status}", [
        {**_act_emission(entry.act_name, section), "act_initialism_roster": note}
        for section in (emitted or (None,))
    ]


def _read_word_prefixed_act(row, oracles: _ActOracles):
    """The word-prefix operator, fenced by the same agency roster.

    Wave 3 measured it against the whole index, found it recovered 15 rows
    over one distinct value, and refused it on yield. Wave 4 measured its
    false-positive surface instead -- held out over the 1,964 distinct
    (text, RIN) act citations the grammar resolved, with the true act removed
    from the roster, the operator invented a survivor 0 times -- and it is the
    fence, not the yield, that licenses it.
    """

    key, section = _act_prose_key(row["authority_text"])
    if "act" not in key or key in oracles.lookup:
        return None
    resolved = _first_level_answer(
        oracles.rosters(row["rin"]),
        lambda keys: _one_word_prefix_survivors(key, keys)
        | _one_word_prefix_survivors(_LEADING_ARTICLE.sub("", key), keys),
    )
    if resolved is None:
        return None
    return "agency-roster-word-prefix", [_act_emission(resolved, section)]


#: A statement may only become a resolution if it states a NUMBER.
#:
#: ``stated_section`` finds the literal "sec" inside ordinary words: "**Sec**
#: retary" yields "retary", "**Sec**urity" yields "urity", "**Sec**recy"
#: yields "recy", "**sec**tions" yields "s". Those are sliced words, not
#: section designations, and this rule used to promote one straight into
#: ``act_section`` -- 22 rows of the artifact stated Social Security Act
#: section "urity". (The statement column itself carries 1,323 such rows; that
#: is the grammar's to answer, not this module's, and the original text always
#: stays beside it.)
#:
#: Deliberately the WEAKEST test that separates the two: does it state a digit
#: at all. A shape would have thrown away real designations -- the Farm Credit
#: Act numbers its sections by title and decimal ("4.9", "4.14B"), and acts
#: carry letter suffixes ("1860D-31"), hyphenated compounds ("290dd-1") and
#: subsections ("1861(v)(1)(A)"). Measured across this artifact: of 686,401
#: usc_section, 4,382 usc_chapter, 6,575 cfr_part and 7,105 act_section values
#: every one states a digit, and the only digit-free values anywhere are the
#: sliced words above.
_STATES_A_NUMBER = re.compile(r"\d")


def _stated_section_that_is_one(statement: str | None) -> str | None:
    """A stated section, or None where what was read is not a section at all."""

    return statement if statement and _STATES_A_NUMBER.search(statement) else None


#: "Clean Air Act **as amended in 1990**, section 112" -- a participial clause
#: giving the vintage of the act just named, and the ONE construction review #2
#: proved is not a second act (notes/G.json, 2060-AE11 and 2060-AE83).
#:
#: The distinction is the preposition and nothing softer. "as amended IN YEAR"
#: dates the same act; "as amended BY <name>" introduces a second one, and the
#: corpus writes both: "The Federal Civil Penalties Inflation Adjustment Act of
#: 1990, as amended by the Federal Civil Penalties Inflation Adjustment Act
#: Improvements Act of 2015" names two acts that both resolve, and refusing it
#: is the fence working. A year sitting beside anything else -- an initialism
#: ("MMA 2003, MIPPA (title XVIII of the Social Security Act)"), a comma-joined
#: second name ("Motor Carrier Act of 1935, Omnibus Transportation Employee
#: Testing Act of 1991") -- is untouched by this and still refuses.
_ACT_VINTAGE_YEAR = re.compile(r"as\s+amended\s+in\s+(1[7-9]\d\d|20\d\d)\b", re.IGNORECASE)

#: The qualifier a defence bill's name ends on, which the statement reader's
#: forward walk does not take: it appends "Amendments" and a year, and the
#: fiscal year is neither. "…division F of the National Defense Authorization
#: Act for Fiscal Year 2020" therefore stated the bare family name, which names
#: no act -- there is one nearly every year -- while the qualifier that picks
#: one out sits VERBATIM in the same box (3206-AN96 202410, notes/G.json).
_ACT_FISCAL_YEAR_TAIL = re.compile(
    r"\s*,?\s*for\s+(?:the\s+)?fiscal\s+years?\s+((?:19|20)\d{2})", re.IGNORECASE
)


def _qualified_by_the_boxs_own_tail(text: object, stated: str) -> str | None:
    """``stated`` plus the fiscal year the box writes right after it, or None.

    The qualifier is taken from THIS box only, from the position the captured
    name actually ends at, so it can neither be borrowed from a neighbouring
    citation nor assembled out of a year mentioned elsewhere in the value.
    """

    document = str(text or "")
    start = document.find(stated)
    if start < 0:
        return None
    tail = _ACT_FISCAL_YEAR_TAIL.match(document, start + len(stated))
    return f"{stated} for Fiscal Year {tail.group(1)}" if tail is not None else None


def _read_index_held_name(row, oracles: _ActOracles, tally: _Tally):
    """A name the OLRC index holds, read out of the prose around it.

    The index answers "Clean Air Act" and always did; what failed was the
    packaging -- "Clean Air Act as amended in 1990, title I", "of the Social
    Security Act", "sec 1819(a) to (f) of the Social Security Act". The
    statement reader already isolates the name, so the index can answer it.

    Two fences, because an amendment is its own entry and not the base act: a
    value naming an amendment is refused outright, and so is one carrying a
    year the name itself does not, since that year designates some other
    member of the family. Both refuse "Section 172(a) of the 1990 Clean Air
    Act amendments", which would otherwise have claimed the base act.
    """

    if row["act_key"] or not row["stated_act_name"]:
        return None
    stated_name = row["stated_act_name"]
    name = normalize_popular_name(stated_name)
    if name not in oracles.lookup:
        # The box's OWN continuation, read only where the captured name names
        # nothing -- so this can add a reading and never displace one. The
        # statement column is deliberately left as the reader wrote it: making
        # the forward walk take the qualifier lengthens the name the
        # longest-match rule picks, and measured over this corpus that flips
        # seven rows off "Fair Chance to Compete for Jobs Act of 2019" and onto
        # a "National Defense Authorization Act for Fiscal Year 2019" the index
        # does not list (its entry carries "John S. McCain" in front).
        qualified = _qualified_by_the_boxs_own_tail(row["authority_text"], stated_name)
        if qualified is None or normalize_popular_name(qualified) not in oracles.lookup:
            return None
        stated_name = qualified
        name = normalize_popular_name(qualified)
    text_low = (row["authority_text"] or "").lower()
    if "amendment" in text_low:
        return None
    # Deliberately a WIDER year range than ``_YEAR_TOKEN``: a published act
    # name can carry an eighteenth-century year, and a fence that cannot see
    # one is not a fence.
    #
    # A NUMBER THE ROW STATES AS ITS OWN SECTION IS NOT A YEAR. "sec 1919(a) to
    # (g) of the Social Security Act" -- the shape this reader's own docstring
    # names -- was refused by this fence for thirteen editions because 1919
    # matches a year: so did 1819, 1815 and 1833, every one of them a real
    # Social Security Act section and not a member of any act family. The 34
    # rows carrying a year that is NOT their section keep the refusal, which is
    # what it was written for: "Section 172(a) of the 1990 Clean Air Act
    # amendments" states 172(a) and still carries 1990.
    #
    # AND A YEAR THE TEXT GIVES AS THIS ACT'S OWN VINTAGE IS NOT ANOTHER ACT'S.
    # The fence read "Clean Air Act as amended in 1990" as it reads "the 1990
    # Clean Air Act amendments" -- alike -- and only the second names a
    # separately indexed entity. The first is one act with a date on it, and
    # the cost of conflating them was measured: the base-act key resolves
    # section 112 to 42 U.S.C. 7412 (2060-AE83's own hazardous-air-pollutant
    # subject), where 'clean air act amendments of 1990' does not classify
    # section 112 at all. :data:`_ACT_VINTAGE_YEAR` is the whole narrowing --
    # the preposition, nothing softer.
    stated = row["act_section"] or _stated_section_that_is_one(row["stated_section"])
    section_digits = re.match(r"\d+", str(stated or ""))
    if set(_ACT_TEXT_YEAR.findall(text_low)) - set(
        _ACT_TEXT_YEAR.findall(stated_name)
    ) - ({section_digits.group(0)} if section_digits else set()) - set(
        _ACT_VINTAGE_YEAR.findall(text_low)
    ):
        return None
    resolved = _act_key_within_calendar(oracles.lookup[name], row["publication_id"], tally)
    if resolved is None:
        return None
    return "index-holds-the-stated-name", [
        _act_emission(resolved, row["act_section"] or _stated_section_that_is_one(row["stated_section"]))
    ]


#: Why a slash was not read as a separator between two authorities. Counted the
#: way every refusal in this module is: by the fence that spoke.
SLASH_REFUSALS: tuple[str, ...] = (
    #: The value carries no slash a separator could be, or only slashes
    #: flanked by digits ("the 9/11 Commission Act", "5/1/2003").
    "no-slash-that-could-separate-two-authorities",
    #: The head reads as nothing on its own, so the slash is inside whatever
    #: the value is rather than between two things. "S/B Improving Head Start
    #: for School Readiness Act of 2007, PL 110-134" is the shape: "S" is not
    #: an authority and the value's one citation is the Public Law at the end.
    #: A value whose head is empty ("/CAA 112 & 103") is refused here too, and
    #: is already read by the scheme-label prefix the abbreviated shapes carry.
    "the-head-does-not-read-as-a-citation-on-its-own",
    #: Every piece after the head read as a citation already, so the grammar
    #: never dropped anything: "33 USC 1251/33 USC 1345" and "33 USC
    #: 1361(a)/76 Stat 816" are both read whole today.
    "the-tail-is-already-read-by-the-grammar",
    #: The commonest refusal, and the fence that holds the traps: no act
    #: reader could BIND the piece. "42 USC 7401/et seq" states no act,
    #: "Docket 41683, EDR 468/PSDR-81" names a docket the roster has never
    #: heard of, and "Pub. L. 117-180, Division G - Hermit's Peak/Calf Canyon
    #: Fire Assistance Act" halves a place name.
    "no-act-reader-binds-the-tail",
    #: The piece resolves, and to exactly what the box already says. "42 USC
    #: /RCRA 3004(a)(q)" is read WHOLE by the scheme-label prefix the
    #: abbreviated shapes carry, so a second reading of its tail would put the
    #: filer's one authority on the record twice.
    "the-box-already-names-this-act-at-this-section",
)


def _slash_pieces(text: str) -> list[str]:
    """``text`` cut at every slash that could separate two authorities.

    A slash flanked by digits on BOTH sides is never one. It is a date
    ("5/1/2003"), a numeric pair, or the name of the day two towers fell --
    "PL 110-53, sec 1413, The Implementing Recommendations of the 9/11
    Commission Act of 2007" is 13 rows in this corpus and a cut inside it
    hands the reader "11 Commission Act of 2007", which is not an act.

    Everything else is offered, because the corpus's own separator has no
    other regularity: "15 USC 2603/TSCA 4", "15 USC 2604/ TSCA 5", "42 USC
    7414, 7601, 7671 / Clean Air Act section 612" and "PL 101-549 /Clean Air
    Act sections 112 and 183" all write it differently. What decides is
    whether both sides read as authorities, not how the filer spaced them.
    """

    pieces: list[str] = []
    last = 0
    for match in re.finditer(r"/", text):
        before = text[match.start() - 1] if match.start() else ""
        after = text[match.end()] if match.end() < len(text) else ""
        if before.isdigit() and after.isdigit():
            continue
        pieces.append(text[last : match.start()])
        last = match.end()
    pieces.append(text[last:])
    return pieces


def _reads_as_a_citation(text: str) -> bool:
    """Whether the grammar reads ``text`` as an authority of any family."""

    return any(citation.authority_type != "other" for citation in parse_authority_citation(text))


def _slash_arrivals(block, act_readers, tally: _Tally, calendar: _SeriesCalendar):
    """The rows a second authority behind a slash adds to one box.

    THE DEFECT. ``parse_authority_citation``'s whole-value fallback fires only
    when the ENTIRE string yielded nothing, so once "42 USC 7401" matches, the
    text after the slash is never scanned again by anything. Measured on
    rebuild #11: 260 non-date values carry a slash and 235 of them lose a
    second authority the filer wrote -- 223 spelling it with an act's
    initials (CAA, CWA, TSCA, RCRA, FFDCA, CERCLA, SDWA, FIFRA, AEA, MPRSA,
    EPCRA, SARA, FWPCA) and 8 spelling the act out.

    THE RULE. Cut at a slash; the head must read as a citation on its own, and
    each piece behind it is offered to the SAME act readers a whole value
    meets. Nothing about the head is touched -- its rows are already published
    and this pass only appends -- so the rule can add a citation and can never
    move one. A piece that no reader binds is refused and counted, which is
    what keeps the traps out: they are not exceptions, they are pieces that
    read as nothing.

    THE READERS ARE NOT COPIED, they are re-run. A piece is put to
    ``_read_abbreviated_act``, ``_read_pinned_roster_act``,
    ``_read_word_prefixed_act`` and ``_read_index_held_name`` on a synthetic
    row carrying the piece as its text, so "CAA 112" behind a slash resolves
    on exactly the evidence "CAA 112" resolves on when a filer writes it
    alone -- the same RIN's own resolved acts first, then the agency's, then
    the pinned roster. A rule that re-implemented the binding would be a
    second opinion about what CAA means.
    """

    row = block[0]
    text = str(row["authority_text"] or "")
    pieces = _slash_pieces(text)
    if len(pieces) < 2:
        tally.slash_refusals["no-slash-that-could-separate-two-authorities"] += 1
        return []
    head, tails = pieces[0], pieces[1:]
    if not head.strip() or not _reads_as_a_citation(head):
        tally.slash_refusals["the-head-does-not-read-as-a-citation-on-its-own"] += 1
        return []
    # WHAT THE BOX ALREADY SAYS. A value whose whole text read as nothing has
    # already met these readers in the corroboration sweep, and for one shape
    # it met them on the same piece: "42 USC /RCRA 3004(a)(q)" is read whole by
    # the scheme-label prefix the abbreviated shapes carry, which steps over a
    # bare title and a slash. Without this the box carried the identical
    # reading twice, on two ordinals, and a consumer counting citations would
    # have counted the filer's one authority as two. The fence is the reading,
    # not the rule that made it: a piece states nothing new when the box
    # already names that act at that section.
    already = {
        (row.get("act_key"), row.get("act_section"))
        for row in block
        if row.get("authority_type") == "act_relative"
    }
    arrivals: list[dict[str, object]] = []
    read_already = 0
    for piece in tails:
        piece = piece.strip()
        if not piece:
            continue
        if _reads_as_a_citation(piece):
            read_already += 1
            continue
        synthetic = {
            **row,
            "authority_text": piece,
            "act_key": None,
            "act_section": None,
            "stated_act_name": stated_act_name(piece),
            "stated_section": stated_section(piece),
        }
        reading = next(
            (answer for answer in (reader(synthetic) for reader in act_readers) if answer is not None),
            None,
        )
        if reading is None:
            tally.slash_refusals["no-act-reader-binds-the-tail"] += 1
            continue
        if all(
            (emission.get("act_key"), emission.get("act_section")) in already
            for emission in reading[1]
        ):
            tally.slash_refusals["the-box-already-names-this-act-at-this-section"] += 1
            continue
        fresh = dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names)
        fresh.update(
            rin=row["rin"],
            publication_id=row["publication_id"],
            ordinal=row["ordinal"],
            # The filer's whole value, unchanged. The piece that was read is
            # recoverable from it by this rule's own cut, and nothing in this
            # module ever rewrites what the publisher typed.
            authority_text=row["authority_text"],
            authority_source=row["authority_source"],
            restates_box_citation=None,
            usc_appendix=False,
            usc_note=False,
        )
        # The rule that BOUND the piece is half the published name; this rule
        # is the other half. ``act_resolution_evidence`` is NOT written here:
        # that column belongs to the act resolver, which runs later and says
        # which OLRC table classified the section -- a different question, and
        # writing it here only got it overwritten.
        extras = _apply_corroboration(fresh, f"{SLASH_RULE}:{reading[0]}", reading[1], tally, calendar)
        arrivals.extend([fresh, *extras])
    if not arrivals and read_already:
        tally.slash_refusals["the-tail-is-already-read-by-the-grammar"] += 1
    return arrivals


def _read_index_held_bare_name(row, oracles: _ActOracles, tally: _Tally):
    """A name the index holds, with a bare section and no prose around it.

    The corroboration family's reader for :func:`_bare_name_section_reading`.
    The parse loop reads that shape out of a WHOLE value; nothing read it out
    of a piece until the slash rule needed it, and the piece it needed it for
    is "CERCLA 102" — 65 rows over 15 values whose second authority no
    initialism roster can bind, because CERCLA is a name and not an initialism
    as far as the index is concerned.
    """

    reading = _bare_name_section_reading(row["authority_text"], oracles.lookup)
    if reading is None:
        return None
    resolved = _act_key_within_calendar(reading[0], row["publication_id"], tally)
    if resolved is None:
        return None
    return "index-holds-a-bare-name-and-section", [_act_emission(resolved, reading[1])]


def _slash_act_readers(oracles, tally: _Tally):
    """The act readers a slash's tail is offered, in the order a whole value meets them.

    The same four, in the same order, built from the same oracles -- so a
    piece behind a slash is bound by the corpus's own resolved acts before the
    pinned roster is asked, exactly as a whole value is. The history readers
    are deliberately absent: their oracle is the RIN's own citation slots, and
    a fragment of a value is not a slot.
    """

    if oracles is None:
        return ()
    return (
        lambda row: _read_abbreviated_act(row, oracles),
        lambda row: _read_pinned_roster_act(row, oracles, tally),
        lambda row: _read_word_prefixed_act(row, oracles),
        lambda row: _read_index_held_name(row, oracles, tally),
        lambda row: _read_index_held_bare_name(row, oracles, tally),
    )


def _read_slash_second_authorities(authorities, act_readers, tally: _Tally, calendar: _SeriesCalendar):
    """One sweep over the boxes, appending what a slash hid.

    Boxes are contiguous in emission order, so an arrival appended after a
    box's last row takes the next ``citation_ordinal`` when
    :func:`_number_citations` runs -- the citation list continues rather than
    renumbering, which is what the contract says the column is.
    """

    if not act_readers:
        return authorities
    rebuilt: list[dict[str, object]] = []
    index, total = 0, len(authorities)
    while index < total:
        key = (
            authorities[index]["rin"],
            authorities[index]["publication_id"],
            authorities[index]["ordinal"],
        )
        last = index
        while last + 1 < total and (
            authorities[last + 1]["rin"],
            authorities[last + 1]["publication_id"],
            authorities[last + 1]["ordinal"],
        ) == key:
            last += 1
        block = authorities[index : last + 1]
        rebuilt.extend(block)
        if "/" in str(block[0]["authority_text"] or ""):
            rebuilt.extend(_slash_arrivals(block, act_readers, tally, calendar))
        index = last + 1
    return rebuilt


#: A value's tokens, and the shape a damaged label wears inside one. The
#: second pattern is what lets "113tat." be read: the corpus welds a number to
#: a label as often as it spaces them, and a tokenizer that split on the digit
#: boundary would hand the fence a token that is already a label.
_LABEL_TOKEN = re.compile(r"[A-Za-z0-9.]+")
_LABEL_TOKEN_SHAPE = re.compile(r"^(?P<lead>\d*)(?P<word>[A-Za-z.]+)(?P<trail>\d*)$")

#: The columns each repaired reading carries out of the grammar. Declared per
#: type rather than copied wholesale, because ``public_law`` is deliberately
#: absent from its own row: a recovered law goes to ``public_law_corrected``,
#: the posture every Public Law rule in this module already takes.
_SCHEME_LABEL_EMISSION_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "usc": (
        "usc_title", "usc_section", "usc_section_end", "usc_section_span_rule",
        "usc_chapter", "usc_chapter_end", "usc_appendix", "usc_note",
    ),
    "statute_at_large": (
        "statute_volume", "statute_page", "statute_page_text", "statute_volume_text",
    ),
    "federal_register": ("fr_volume", "fr_page"),
    "public_law": (),
}

#: The columns a row is allowed to carry and still be offered to this rule.
#: Everything else NULL is the fence that makes the rule additive BY
#: CONSTRUCTION rather than by inspection: it fills columns nothing filled, and
#: no existing value is ever the thing it changes. "OL 111-148, sec 3301,
#: sec 6402" is refused here -- the row already states section 3301, and a
#: reading that arrived beside a statement would leave a consumer holding two
#: answers with nothing to choose between them.
_SCHEME_LABEL_NEUTRAL_COLUMNS: frozenset[str] = frozenset({
    "rin", "publication_id", "ordinal", "citation_ordinal", "authority_text",
    "authority_source", "authority_type", "parse_status", "restates_box_citation",
    "usc_appendix", "usc_note",
})


def _label_letters(value: object) -> str:
    """A label or a token reduced to the letters that spell it."""

    return re.sub(r"[^a-z]", "", str(value or "").lower())


_LABEL_LETTERS: Mapping[str, str] = {label: _label_letters(label) for label in SCHEME_LABELS}


def _one_edit_apart(candidate: str, label: str) -> bool:
    """Levenshtein distance exactly :data:`SCHEME_LABEL_MAX_EDITS`.

    Substitution, insertion, deletion. No transposition -- see
    :data:`SCHEME_LABEL_MAX_EDITS` for why that fence is drawn where the
    Register-label rule's is not.
    """

    if abs(len(candidate) - len(label)) > SCHEME_LABEL_MAX_EDITS:
        return False
    previous = list(range(len(label) + 1))
    for i, left in enumerate(candidate, 1):
        row = [i]
        for j, right in enumerate(label, 1):
            row.append(min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + (left != right)))
        previous = row
    return previous[-1] == SCHEME_LABEL_MAX_EDITS


_GRAMMAR_ACCEPTS_LABEL: dict[str, bool] = {}


def _grammar_accepts_label(word: str) -> bool:
    """F2, as a PROBE and never as a list.

    Whether the grammar already reads this spelling as a label. Asked by
    putting the spelling where a label goes and seeing whether anything types,
    so a label the grammar learns tomorrow leaves this fence automatically --
    which a hand-kept list of accepted spellings would not.
    """

    if word not in _GRAMMAR_ACCEPTS_LABEL:
        _GRAMMAR_ACCEPTS_LABEL[word] = any(
            citation.authority_type != "other"
            for probe in (f"42 {word} 1983", f"{word} 1983", f"110 {word} 1936")
            for citation in parse_authority_citation(probe)
        )
    return _GRAMMAR_ACCEPTS_LABEL[word]


def _scheme_label_candidates(text: str):
    """Every token one edit from a scheme label, past fences F1-F3.

    F1 two letters, F2 not a spelling the grammar already accepts, F3 in
    citation shape -- welded to digits ("113tat.") or standing beside a bare
    number ("16 USE 715"). F3 is what keeps ordinary prose out: a two-letter
    word one edit from "PL" is everywhere, and one BESIDE A NUMBER is rare.
    """

    tokens = list(_LABEL_TOKEN.finditer(text))
    for index, token in enumerate(tokens):
        shape = _LABEL_TOKEN_SHAPE.match(token.group(0))
        if shape is None:
            continue
        letters = _label_letters(shape.group("word"))
        if len(letters) < SCHEME_LABEL_MIN_LETTERS:
            continue
        if letters in _LABEL_LETTERS.values() or _grammar_accepts_label(shape.group("word")):
            continue
        welded = bool(shape.group("lead") or shape.group("trail"))
        beside = any(
            tokens[near].group(0).strip(".").isdigit()
            for near in (index - 1, index + 1)
            if 0 <= near < len(tokens)
        )
        if not (welded or beside):
            continue
        labels = [
            label for label, spelling in _LABEL_LETTERS.items() if _one_edit_apart(letters, spelling)
        ]
        if labels:
            yield token.span(), shape.group("lead"), shape.group("trail"), labels


def _label_repair(text: str, span: tuple[int, int], lead: str, trail: str, label: str) -> str:
    """The value with the damaged token replaced by the label it names."""

    replacement = (f"{lead} " if lead else "") + label + (f" {trail}" if trail else "")
    return text[: span[0]] + replacement + text[span[1] :]


def _label_residue(text: str, span: tuple[int, int]) -> list[str]:
    """The alphabetic runs the repair leaves behind.

    A run welded to digits is not residue: its letters belong to a section, a
    page or a Public Law ("299b-12", "1735f-14"), and the operator was never
    asked to explain them.
    """

    return [
        run.group(0)
        for run in re.finditer(r"[A-Za-z0-9.\-()§,;:]+", text)
        if not (run.start() >= span[0] and run.end() <= span[1])
        and not any(character.isdigit() for character in run.group(0))
        and _label_letters(run.group(0))
    ]


def _label_residue_closes(text: str, span: tuple[int, int], label: str) -> str | None:
    """F5. The refusal reason, or None where the residue closes.

    Every run left beside the repaired token has to be one of three things: a
    label the grammar already accepts (and then this rule is inventing a
    SECOND label rather than repairing the first -- "29 USC UC 794" already
    says USC); a fragment of the label's own letters, which is the filer
    splitting it in two ("16 U..C."); or citation structure the grammar names
    ("et seq.", "note", "to"). Anything else is prose the operator does not
    explain, and "Pu. Bl. 111-148" reaching Pub. L. 111-148 by repairing only
    "Bl." is the right answer by the wrong token, which is still a guess.
    """

    spelling = _LABEL_LETTERS[label]
    for run in _label_residue(text, span):
        stripped = run.strip(".,;:()§")
        if _grammar_accepts_label(run) or _grammar_accepts_label(stripped):
            return "the-label-already-stands-in-the-residue"
        letters = _label_letters(run)
        if len(letters) < len(spelling) and all(
            letters.count(character) <= spelling.count(character) for character in set(letters)
        ):
            continue
        if names_citation_structure(stripped):
            continue
        return "residue-the-operator-does-not-explain"
    return None


_LABEL_ALPHABET = "abcdefghijklmnopqrstuvwxyz"


def _competing_repairs(token: str):
    """Every OTHER one-edit spelling of the token, label or not."""

    seen = {token}
    for index in range(len(token) + 1):
        for character in _LABEL_ALPHABET:
            for variant in (token[:index] + character + token[index:],
                            token[:index] + character + token[index + 1 :]):
                if variant and variant not in seen:
                    seen.add(variant)
                    yield variant
        if index < len(token):
            dropped = token[:index] + token[index + 1 :]
            if dropped and dropped not in seen:
                seen.add(dropped)
                yield dropped


def _another_repair_types_it_in_full(text: str, span: tuple[int, int], label: str) -> bool:
    """F4. Whether a competing repair types the WHOLE value, prose included.

    ``Reorganization Plan No. 4 or 1978`` is a reorganization plan under one
    edit ('or' -> 'of') and "4 FR 1978" under another ('or' -> 'FR'). Register
    volume 4 is real and the series bound says so, which is exactly why the
    series bound cannot be the judge here: two repairs survive, so neither is
    the single survivor, and the one that reads the value's own prose is the
    one the filer wrote. Measured by DELETION -- a competing reading that
    stops typing when a residue run is removed is a reading built out of that
    run, not one that ignored it.
    """

    residue = _label_residue(text, span)
    if not residue:
        return False
    token = text[span[0] : span[1]]
    for variant in _competing_repairs(token):
        if _label_letters(variant) == _LABEL_LETTERS[label]:
            continue
        competing = text[: span[0]] + variant + text[span[1] :]
        if not any(
            citation.authority_type != "other"
            for citation in parse_authority_citation(competing)
        ):
            continue
        for run in residue:
            without = competing.replace(run, "", 1)
            if not any(
                citation.authority_type != "other"
                for citation in parse_authority_citation(without)
            ):
                return True
    return False


def _scheme_label_reading(citation, repaired, publication_id, oracle, calendar, roster_pairs):
    """(emission, witness) where a PINNED ORACLE affirms this reading, else None.

    Four witnesses, one per type the corpus's damaged labels actually reach.
    A type none of them answers -- a case reporter, a treaty -- refuses here
    rather than publishing on the operator alone, which is the whole posture:
    "42 USE 1382" and "42 USO 299b-12" are the same single edit, and what
    separates them from a guess is that a pinned oracle prints the place the
    repaired value names.
    """

    columns = _SCHEME_LABEL_EMISSION_COLUMNS.get(citation.authority_type)
    if columns is None:
        return None
    emission: dict[str, object] = {"authority_type": citation.authority_type}
    emission.update({column: getattr(citation, column) for column in columns})

    if citation.authority_type == "usc":
        if oracle is None or citation.usc_title is None or citation.usc_section is None:
            return None
        witness = "section-oracle"
        section = citation.usc_section
        # The tail rides along. "12 USC 1735(f)-14" cannot mean 12 U.S.C. 1735:
        # the filer stated a tail, and a question asked about the truncated
        # stem is a question about a different section. Two stated tails is an
        # ambiguity, and this rule refuses one.
        stated = oracle.tail_stated_sections(citation.usc_title, section, repaired)
        if len(stated) > 1:
            return None
        if stated:
            section, witness = stated[0], "section-oracle-on-the-stated-tail"
            emission["usc_section_end"] = None
            emission["usc_section_span_rule"] = None
        verdict = oracle.section_verdict(
            citation.usc_title,
            section,
            _SeriesCalendar._edition_year(publication_id),
            appendix=citation.usc_appendix,
        )
        if verdict.verdict != "exists":
            return None
        emission["usc_section"] = section
        return emission, witness

    if citation.authority_type == "statute_at_large":
        # The VOLUME is what the roster's series bound can affirm; the page is
        # carried as the filer stated it and nothing here affirms it. RIN
        # 2126-AA64 writes "113tat. 1754 (1999)" in two editions and 1765 in
        # its later ones, which is the reason that distinction is not academic.
        if calendar is None or citation.statute_volume is None:
            return None
        if not calendar.stat_volume_in_series(citation.statute_volume, publication_id):
            return None
        return emission, "statutes-volume-series"

    if citation.authority_type == "public_law":
        if roster_pairs is None or citation.public_law is None:
            return None
        try:
            congress, number = (int(half) for half in citation.public_law.split("-", 1))
        except ValueError:
            return None
        if (congress, number) not in roster_pairs:
            return None
        emission.update({
            "public_law_corrected": citation.public_law,
            "pl_correction_evidence": SCHEME_LABEL_RULE,
        })
        return emission, "public-law-roster"

    if calendar is None or citation.fr_volume is None:
        return None
    if not calendar.fr_volume_in_series(citation.fr_volume, publication_id):
        return None
    return emission, "federal-register-volume-series"


def _read_damaged_scheme_label(row, oracle, calendar, roster_pairs, tally: _Tally):
    """A scheme label one edit from its spelling, and the oracle that prints it.

    The census this rule answers is small and hostile: 178 values in the failed
    pool carry a token one edit from a label, 55 reach a corroborated reading,
    and TWELVE of those 55 are traps. So the operator is fenced six ways --
    F1 two letters, F2 not a spelling the grammar reads, F3 citation shape,
    F4 no competing repair that types the value in full, F5 residue closure,
    and the row itself stating nothing else -- and every refusal is counted by
    the fence that spoke rather than folded into a total.

    It runs LAST among the readers, which is not a preference: every row it can
    see is a row no other rule claimed, so its placement is what makes "only
    these rows moved" a fact about the order rather than a hope.
    """

    text = row["authority_text"]
    if not text:
        return None
    survivors: dict[tuple, tuple[dict[str, object], str, str]] = {}
    refusals: set[str] = set()
    offered = False
    for span, lead, trail, labels in _scheme_label_candidates(text):
        for label in labels:
            offered = True
            repaired = _label_repair(text, span, lead, trail, label)
            # EVERY citation the repaired value states, and every one of them
            # affirmed. "49 U.S 41102, 41301, 41708, 41709, and 41712" is one
            # label and five sections, and a reader that stopped at the first
            # would publish 41102 and drop four real citations the same repair
            # produced -- the loss this module refuses everywhere else. One
            # member unaffirmed refuses the whole value: the repair is a claim
            # about the LABEL, and a label that makes four sections real and
            # one imaginary was not the damage.
            citations = list(parse_authority_citation(repaired))
            if any(citation.authority_type == "other" for citation in citations):
                continue
            readings = [
                _scheme_label_reading(
                    citation, repaired, row["publication_id"], oracle, calendar, roster_pairs
                )
                for citation in citations
            ]
            if not readings or any(reading is None for reading in readings):
                continue
            witnesses = {witness for _emission, witness in readings}
            if len(witnesses) != 1:
                continue
            # Fenced only where something SURVIVED: a fence that never had a
            # reading to refuse has refused nothing, and counting it would
            # report the corpus's prose as this rule's near misses.
            if _another_repair_types_it_in_full(text, span, label):
                refusals.add("another-repair-types-the-value-in-full")
                continue
            residue = _label_residue_closes(text, span, label)
            if residue is not None:
                refusals.add(residue)
                continue
            emissions = [emission for emission, _witness in readings]
            # Keyed by the READING, so "U.S.C." and "USC" -- two spellings of
            # one label, which the grammar reads identically -- are one
            # survivor and not two. ``setdefault`` so the spelling published is
            # the first in :data:`SCHEME_LABELS`, which makes the column a
            # function of the declaration rather than of loop order.
            survivors.setdefault(
                tuple(
                    tuple(sorted(emission.items(), key=lambda item: item[0]))
                    for emission in emissions
                ),
                (emissions, next(iter(witnesses)), f"{text[span[0] : span[1]]} -> {label}"),
            )
    if len(survivors) == 1:
        # ``.get``, because the emit path writes the columns the GRAMMAR fills
        # and leaves the later passes' columns absent rather than None. A
        # missing key is a column nothing has written, which is what this fence
        # is asking about.
        if any(
            row.get(column) is not None and row.get(column) is not False
            for column in LEGAL_AUTHORITIES_SCHEMA.names
            if column not in _SCHEME_LABEL_NEUTRAL_COLUMNS
        ):
            tally.scheme_label_refusals["the-row-already-states-something"] += 1
            return None
        emissions, witness, operator = next(iter(survivors.values()))
        return SCHEME_LABEL_RULE, [
            {**emission, "authority_label_corrected": operator, "label_correction_evidence": witness}
            for emission in emissions
        ]
    if offered:
        # Each fence that spoke, once per row, and the catch-all only where no
        # named fence did: "no oracle affirmed anything" is the shape of 123 of
        # these 178 values and has to be countable apart from the traps.
        for refusal in sorted(refusals):
            tally.scheme_label_refusals[refusal] += 1
        if not refusals:
            tally.scheme_label_refusals["no-single-corroborated-reading"] += 1
    return None


def _corroboration_readers(
    authorities,
    oracles: _ActOracles | None,
    roster_pairs,
    tally: _Tally,
    *,
    section_oracle: UscSectionOracle | None = None,
    calendar: _SeriesCalendar | None = None,
):
    """The closed, ordered set of rules a failed value meets, and their oracles.

    Order is priority: the first reader that answers claims the row. Both
    oracles are built from the table BEFORE any corroboration runs, which is
    the rule that corroboration never bootstraps on corroboration -- stated
    here once instead of relying on four sweeps happening to run in sequence.

    The act rules come first because their oracle is a NAME index; the
    citation-history rules follow because theirs is the publisher's own
    resolved citations, which answer the shapes that lost a LABEL or a
    CONTAINER rather than a name. Wave 3 escalated the act oracle from the RIN
    to the agency and recovered 2,758 rows; the history rules are that same
    escalation with the same posture -- the RIN speaks before its agency,
    ambiguity refuses, and the original text never leaves the row.

    The split-citation rule comes LAST, and deliberately: its oracle is the
    weakest of the three -- one slot's neighbour rather than a name index or a
    resolved citation -- so it claims only what nothing better could read. That
    ordering is also what keeps its held-out score honest. The rows it answers
    are scored against joined "PL X-Y, sec N" spellings it never consults, and
    a rule placed ahead of the history reader would be answering rows the
    history reader had read out of exactly those spellings.
    """

    readers: list[Callable] = []
    if oracles is not None:
        readers += [
            lambda row: _read_abbreviated_act(row, oracles),
            # Immediately after, and never before: the same shape, read from a
            # FILE where the corpus itself is silent. Placed ahead of the
            # corpus roster it would answer rows the agency's own filings
            # already spell out, and the published row would name a pinned
            # quote for a reading the corpus already held.
            lambda row: _read_pinned_roster_act(row, oracles, tally),
            lambda row: _read_word_prefixed_act(row, oracles),
            lambda row: _read_index_held_name(row, oracles, tally),
        ]
    history = _CitationHistory.build(authorities)
    splits = _SplitCitations.build(authorities)
    readers += [
        lambda row: _history_read_section_list(row, history),
        lambda row: _history_read_titleless_usc(row, history),
        lambda row: _history_read_labelless_pair(row, history),
        lambda row: _history_read_volumeless_stat(row, history),
        lambda row: _history_read_public_law_pairs(row, history, roster_pairs),
        lambda row: _read_split_public_law(row, splits, history, tally),
        # And the scheme-label rule after even that one, for a reason of its
        # own: its operator edits the value's LABEL, which is the one thing
        # every rule above reads before it reads anything else. Placed
        # earlier it would repair a label out from under a reader that was
        # about to answer the row from the publisher's own history, and the
        # published row would name this rule for a reading the corpus already
        # held. Last means it sees only what nothing else could read.
        lambda row: _read_damaged_scheme_label(row, section_oracle, calendar, roster_pairs, tally),
    ]
    return tuple(readers)


def _public_law_correction(text: str, public_law: str | None, roster) -> tuple[str | None, str | None]:
    """(corrected, evidence) for an OUT-OF-SERIES Public Law, else (None, None).

    A congress inside the numbered series is never second-guessed: the
    correction machinery exists for values whose own numbers refute them.
    """

    if roster is None or public_law is None:
        return None, None
    congress, law = public_law.split("-")[0], public_law.split("-")[1]
    if PL_FIRST_NUMBERED_CONGRESS <= int(congress) <= CONGRESS_CURRENT:
        return None, None
    return _corrected_public_law(text, int(congress), int(law), roster) or (None, None)


_OFR_INDEX_CSV = (
    Path(__file__).resolve().parents[3]
    / "research/evidence/cfr-subject-index-2026-08-20/part-subjects.csv"
)


def _current_ofr_parts() -> frozenset[tuple[int, str]] | None:
    import csv

    if not _OFR_INDEX_CSV.is_file():
        return None
    parts = set()
    with _OFR_INDEX_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            parts.add((int(row["cfr_title"]), row["cfr_part"].lstrip("0").lower() or "0"))
    return frozenset(parts)


#: The Federal Register's own metadata for the documents eight damaged timetable
#: citations turn out to have meant, captured 2026-08-23 from
#: https://www.federalregister.gov/api/v1/documents/ and pinned beside the
#: verbatim responses it was cut from. The fifth oracle found relative to this
#: file, with the same sharp edge as the other four: absent, every one of those
#: rows stays "failed" and nothing says so, which is what ``main``'s refusal is
#: for.
_FR_DOCUMENT_ROSTER_CSV = (
    Path(__file__).resolve().parents[3]
    / "research/evidence/unified-agenda-fr-document-roster-2026-08-23/documents.csv"
)


@dataclass(frozen=True)
class _FrRosterDocument:
    """One Federal Register document, as its publisher describes it."""

    document_number: str
    volume: int
    start_page: int
    #: MM/DD/YYYY, converted at load from the ISO the API prints, because that
    #: is the spelling the timetable's own ``date_text`` uses.
    publication_date: str
    rins: frozenset[str]
    #: The four-digit OMB agency codes the research note verified for a document
    #: whose own RIN list is EMPTY -- the FCC files none into Federal Register
    #: metadata at all. A document with neither witnesses nothing about any
    #: filer and can corroborate nothing.
    rin_agency_prefixes: frozenset[str]


def _fr_document_roster() -> dict[tuple[int, int], _FrRosterDocument] | None:
    """(volume, start page) -> the document, or None where this tree lacks it.

    Keyed on the START page because that is what a Federal Register citation
    names: a page merely INSIDE a document is not that document's citation, and
    89 FR 102209 -- the competing reading of "89 FR 1022091" -- is exactly that.
    Two documents at one key would make exactly-one-survivor a lie, so the load
    refuses by name rather than letting a build choose between them.
    """

    import csv

    if not _FR_DOCUMENT_ROSTER_CSV.is_file():
        return None
    roster: dict[tuple[int, int], _FrRosterDocument] = {}
    with _FR_DOCUMENT_ROSTER_CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (int(row["volume"]), int(row["start_page"]))
            year, month, day = row["publication_date"].split("-")
            document = _FrRosterDocument(
                document_number=row["document_number"],
                volume=key[0],
                start_page=key[1],
                publication_date=f"{month}/{day}/{year}",
                rins=frozenset(filter(None, row["regulation_id_numbers"].split(";"))),
                rin_agency_prefixes=frozenset(filter(None, row["rin_agency_prefixes"].split(";"))),
            )
            if key in roster:
                raise ValueError(
                    f"the FR document roster holds two documents at {key[0]} FR {key[1]}: "
                    f"{roster[key].document_number} and {document.document_number}"
                )
            roster[key] = document
    return roster


#: QWERTY neighbours of the two letters the Register's own label is spelled
#: with. A substitution is only named "adjacent-key" where it IS one: "85 DR
#: 34525" is F mistyped as the key beside it, and "85 XR 34525" -- the same
#: shape without the adjacency -- stays refused, so the name cannot drift into
#: meaning "any letter".
_QWERTY_NEIGHBOURS: dict[str, frozenset[str]] = {
    "F": frozenset("DGRTCV"),
    "R": frozenset("ETDFG45"),
}

#: The named single-character edits a corroborated Federal Register citation
#: repair may spend -- ONE per row, never two. Declared as a closed set so the
#: receipt counts every one of them, including ``page-digit-dropped``, which
#: corroborates nothing in this corpus and is carried because it is the operator
#: that generates the COMPETING reading of "89 FR 1022091": 102209, a real page
#: inside 2024-29633. Its count at zero is a measurement, not an absence, and an
#: operator that silently went positive would be a new class of repair.
FR_CITATION_DAMAGE_OPERATORS: tuple[str, ...] = (
    "page-doubled-digit",
    "page-digit-dropped",
    "page-trailing-character",
    "label-insertion-leading-letter",
    "label-insertion-medial-letter",
    "label-substitution-adjacent-key",
)

#: Which witnesses closed a corroboration, spelled into the evidence after the
#: operator. The second exists because the FCC files no RIN into Federal
#: Register metadata at all -- all 27 documents mentioning either FCC RIN in
#: this repair list an empty RIN field -- so the filer's own four-digit OMB
#: agency code stands in for it, with the shared docket recorded in the roster's
#: README as the witness a timetable row has no column to check.
FR_CITATION_WITNESSES: tuple[str, ...] = ("date-and-rin", "date-and-rin-agency")

#: Volume, label, page: the three tokens this column writes. The page may carry
#: one trailing letter, which is one of the damages this repair reads.
_FR_DAMAGED_CITATION = re.compile(
    r"^\s*(?P<volume>\d{1,3})\s+(?P<label>[A-Za-z]{1,4})\s+(?P<page>\d{1,7})(?P<tail>[A-Za-z]?)\s*$"
)


def _fr_label_damage(label: str) -> str | None:
    """Which named single-character edit turns this label into "FR", or None."""

    if len(label) == 3:
        for index in range(3):
            if label[:index] + label[index + 1:] == "FR":
                return (
                    "label-insertion-leading-letter" if index == 0
                    else "label-insertion-medial-letter"
                )
        return None
    if len(label) == 2:
        differing = [index for index in range(2) if label[index] != "FR"[index]]
        if len(differing) == 1 and label[differing[0]] in _QWERTY_NEIGHBOURS["FR"[differing[0]]]:
            return "label-substitution-adjacent-key"
    return None


def _fr_citation_candidates(text: str) -> tuple[int, dict[int, str]] | None:
    """(volume, {page: damage operator}) for a citation nothing could read.

    ONE named edit, never two: either the LABEL is damaged and the page is read
    exactly as the filer wrote it, or the label is a clean "FR" and the PAGE is.
    The volume is never edited -- no row in this corpus asks for it, and an
    operator with nothing to correct is structure that earns nothing.
    """

    match = _FR_DAMAGED_CITATION.match(text)
    if match is None:
        return None
    volume = int(match.group("volume"))
    label, page, tail = match.group("label").upper(), match.group("page"), match.group("tail")
    if label != "FR":
        operator = _fr_label_damage(label)
        return None if operator is None or tail else (volume, {int(page): operator})
    if tail:
        return volume, {int(page): "page-trailing-character"}
    candidates: dict[int, str] = {}
    for index in range(len(page)):
        shortened = page[:index] + page[index + 1:]
        if not shortened or shortened[0] == "0":
            continue
        doubled = page[index] in page[max(index - 1, 0):index] + page[index + 1:index + 2]
        candidates.setdefault(
            int(shortened), "page-doubled-digit" if doubled else "page-digit-dropped"
        )
    return volume, candidates


def _corroborated_fr_citation(
    text: str,
    *,
    rin: str,
    date_text: str,
    roster: dict[tuple[int, int], _FrRosterDocument] | None,
) -> dict[str, object] | None:
    """The Federal Register document a damaged citation meant, or None.

    Fail-closed like every corroborated correction in this module. A candidate
    comes from one named damage operator, and survives only if all three of
    these hold: its (volume, page) is a roster document's (volume, START page);
    the row's own date_text is that document's publication date; and a witness
    ties the filer to it -- the row's RIN among the document's own, or, where
    the document lists none, the RIN's OMB agency code among those the roster
    records for it. Exactly one may survive.

    The operator alone is never the corroboration. "89 FR 1022091" has two real
    single-digit-deletion readings in volume 89 -- 102091 (2024-29238, NOAA, and
    the citing rule's own RIN is in its RIN list) and 102209 (a page inside
    2024-29633, an SEC notice with no RIN) -- and the second loses because it is
    not a start page and because that document witnesses nothing about any filer.
    """

    if roster is None:
        return None
    generated = _fr_citation_candidates(text)
    if generated is None:
        return None
    volume, candidates = generated
    survivors: list[tuple[_FrRosterDocument, str]] = []
    for page, operator in candidates.items():
        document = roster.get((volume, page))
        if document is None or document.publication_date != date_text:
            continue
        if rin in document.rins:
            witness = "date-and-rin"
        elif not document.rins and rin[:4] in document.rin_agency_prefixes:
            witness = "date-and-rin-agency"
        else:
            continue
        survivors.append((document, f"{operator}-witnessed-by-{witness}"))
    if len(survivors) != 1:
        return None
    document, evidence = survivors[0]
    return {
        "fr_corrected_document_number": document.document_number,
        "fr_corrected_volume": document.volume,
        "fr_corrected_page": document.start_page,
        "fr_correction_evidence": evidence,
    }


def build_unified_agenda_parquet(
    source_root: Path,
    output_root: Path,
    *,
    pins: tuple[UnifiedAgendaEditionPin, ...] = UNIFIED_AGENDA_EDITION_PINS,
    act_names: Collection[str] | None = None,
    #: The same sealed act index ``act_names`` was read from, this time read as
    #: the two JOINS rather than as a name set: without it every act-relative
    #: row still carries its act and its section and no U.S.C. section, which
    #: is what this table published until 2026-08-23.
    act_index_dir: Path | None = None,
) -> UnifiedAgendaParquetReceipt:
    """Read every pinned edition once and write the four tables."""

    output_root.mkdir(parents=True, exist_ok=True)
    actions: list[dict[str, object]] = []
    references: list[dict[str, object]] = []
    authorities: list[dict[str, object]] = []
    timetables: list[dict[str, object]] = []
    ofr_parts = _current_ofr_parts()
    # The act index is read ONCE, here, and answers three different questions
    # downstream: which two names the Popular Name Tool has made one (the
    # closure below), which act a neighbouring box names (the sibling carry),
    # and what an act section resolves to (the resolution pass).
    act_index = ActIndex.from_artifact(act_index_dir) if act_index_dir is not None else None
    credits = _usc_source_credits() if act_index is not None else None
    #: Read before the closure, which now asks it for the approval dates that
    #: license :data:`ACT_ENACTMENT_YEAR_RULE`; the series calendar below reads
    #: the same roster object.
    pl_roster = _pl_roster()
    act_lookup = (
        _act_name_spelling_closure(
            act_names,
            _act_name_resolver(act_index),
            _act_enactment_years(act_index, pl_roster),
        )
        if act_names is not None
        else None
    )
    act_matcher = _ActNameMatcher(act_names) if act_names is not None else None
    tally = _Tally()
    #: Every act key any of a RIN's editions resolved, for the initialism
    #: corroboration pass below — and the same roster at the agency level,
    #: keyed by the RIN's OMB-assigned four-digit agency code.
    act_keys_by_rin: dict[str, set[str]] = {}
    act_keys_by_agency: dict[str, set[str]] = {}
    #: The Federal Register's own metadata for the documents the timetable
    #: column's unreadable values meant. Read once, here, like every oracle.
    fr_roster = _fr_document_roster()
    #: The same roster, read as a calendar, so a series verdict is judged
    #: against what existed when the citation was made.
    calendar = _SeriesCalendar.build(pl_roster)
    #: The section oracle, read once. Two passes ask it questions -- the
    #: scheme-label corroboration before the fence, the fence after it -- and
    #: loading the pinned tables twice for one immutable answer set was a cost
    #: with no reader.
    section_oracle = _usc_section_oracle()
    digests: dict[str, str] = {}

    for pin in pins:
        payload = _edition_payload(pin, source_root)
        # parse_unified_agenda_edition authenticates the digest against the pin
        # and applies the 2004 apostrophe repair in memory. Both happen here so
        # no consumer has to know either is necessary.
        records = parse_unified_agenda_edition(payload, pin=pin)
        digests[pin.publication_id] = pin.expected_sha256
        for record in records:
            actions.append(
                {
                    "rin": record.rin,
                    "publication_id": record.publication_id,
                    "cfr_reference_count": len(record.cfr_references),
                    "legal_authority_count": len(record.legal_authorities),
                    "legal_authorities_declared_incomplete": any(
                        _unstated_kind(text) == "more-citations-follow" for text in record.legal_authorities
                    ),
                    "cfr_references_declared_incomplete": any(
                        _unstated_kind(text) == "more-citations-follow" for text in record.cfr_references
                    ),
                }
            )
            for ordinal, text in enumerate(record.cfr_references):
                # A structured field is entirely a citation, so a comma-list
                # continues it whatever label it carries -- 953 references in
                # this field list parts with no label at all.
                parsed = parse_cfr_citations(text, list_expansion="always")
                if not parsed:
                    references.append(
                        {
                            "rin": record.rin,
                            "publication_id": record.publication_id,
                            "ordinal": ordinal,
                            "reference_text": text,
                            "cfr_title": None,
                            "cfr_part": None,
                            "cfr_title_is_possible": None,
                            "cfr_section": None,
                            "cfr_part_is_plausible": None,
                            # Stated, not left to the schema to fill: there is
                            # no part here to look up, and a counter over this
                            # column must not have to know that.
                            "cfr_part_in_current_ofr_index": None,
                            "citation_ordinal": 0,
                        }
                    )
                for citation_ordinal, citation in enumerate(parsed):
                    references.append(
                        {
                            "rin": record.rin,
                            "publication_id": record.publication_id,
                            "ordinal": ordinal,
                            "reference_text": text,
                            "cfr_title": citation.cfr_title,
                            "cfr_part": citation.cfr_part,
                            "cfr_title_is_possible": citation.title_is_possible,
                            "cfr_section": citation.cfr_section,
                            "cfr_part_is_plausible": citation.part_is_plausible,
                            "cfr_part_in_current_ofr_index": (
                                None
                                if citation.cfr_part is None or ofr_parts is None
                                else (citation.cfr_title, citation.cfr_part.lower()) in ofr_parts
                            ),
                            "citation_ordinal": citation_ordinal,
                        }
                    )
            for ordinal, entry in enumerate(record.timetable):
                # The field is structured, so lowercase "fr" is the
                # publisher's damage rather than prose; uppercasing before the
                # parse is field-level normalization the grammar itself must
                # not perform ("84 cfr 1402" still refuses after it). A row
                # citing several documents yields several rows, one per
                # citation — the earlier exactly-one rule silently FAILED
                # real multi-citation rows like "81 FR 45095, 81 FR 45055".
                citations = (
                    parse_federal_register_citations(entry.fr_citation.upper())
                    if entry.fr_citation
                    else ()
                )
                relabeled = False
                if entry.fr_citation and not citations:
                    # "84 CFR 1402" in the FR column: the text names a scheme
                    # its own numbers refute — no such row parses as a valid
                    # CFR citation (title 84 does not exist; measured: 0 of 64
                    # do) — while the volume/page fit the column's own scheme
                    # exactly. The C is the damage. Read as FR, labelled
                    # 'relabeled', never 'ok'.
                    cfr_shape = re.match(
                        r"\s*(\d+)\s*C\.?\s?F\.?\s?R\.?\s*(\d{1,6})\s*$",
                        entry.fr_citation, re.IGNORECASE,
                    )
                    if cfr_shape:
                        title, number = int(cfr_shape.group(1)), cfr_shape.group(2)
                        impossible_as_cfr = not (1 <= title <= 50 and title != 35) or len(number) > 4
                        if impossible_as_cfr and 1 <= title <= 999:
                            citations = parse_federal_register_citations(f"{title} FR {int(number)}")
                            relabeled = bool(citations)
                if entry.fr_citation and not citations:
                    # The grammar needs an "FR" token; this COLUMN is itself
                    # the anchor. A value that is exactly two plausible
                    # numbers — "71 66120", or "76 R 11462" with its lost F —
                    # is read positionally and labelled as such, never "ok":
                    # the reading rests on column semantics, not on the text.
                    tokens = re.findall(r"\d+", entry.fr_citation)
                    if len(tokens) == 2 and (1 <= int(tokens[0]) <= 999) and (1 <= int(tokens[1]) <= 999_999):
                        stray = re.sub(r"[\d\s.]+", "", entry.fr_citation)
                        # "RF" is the label transposed, "FRFR" the label
                        # stuttered, "/FR" the separator's slash — each a
                        # named damage on the one token this column writes.
                        #
                        # The boundary is NOT an edit distance, and an earlier
                        # comment here claiming "no single named operation
                        # derives them from FR" was simply false: "NFR" is one
                        # insertion, "DR" one substitution, "FSR" one
                        # insertion. What the accepted set has in common is
                        # that every residue is spelled out of the LABEL'S OWN
                        # letters plus the separator's slash — nothing is left
                        # over that the column does not account for. The six
                        # refused rows each leave a letter behind that nothing
                        # explains ("81 NFR 66900", "85 DR 34525",
                        # "85 FSR 62651", "85 FR 75770x" x3), and this repair
                        # has no page oracle to check the reading against; it
                        # rests on column semantics alone, which is why it is
                        # labelled "positional" and never "ok".
                        #
                        # Those six are answered further down, and the reason
                        # the answer belongs there and not here is precisely the
                        # missing oracle: ``_corroborated_fr_citation`` checks
                        # its reading against the Register's own metadata for a
                        # named document and labels it "corroborated", which is
                        # a different claim from anything column semantics can
                        # support. This branch still refuses them.
                        #
                        # Widening to Damerau-Levenshtein <= 2 was measured and
                        # refused: it admits exactly four rows and is wrong on
                        # all four, invisibly — "70 FR AT97", "72 FR AU91" and
                        # "83 FR AK07" put the row's own RIN suffix where the
                        # page goes (70 FR 97, 72 FR 91 and 83 FR 7 are all
                        # real pages, so no range check would catch it), and
                        # "90-21215" is a document number, not a page.
                        # ``parse_agenda_timetable_citation`` names all four.
                        if stray in {"", "R", "F", "FR", "RF", "FRFR", "/FR"}:
                            citations = (
                                parse_federal_register_citations(f"{int(tokens[0])} FR {int(tokens[1])}")
                            )
                            positional = True
                        else:
                            positional = False
                    else:
                        positional = False
                else:
                    positional = False
                base = {
                    "rin": record.rin,
                    "publication_id": record.publication_id,
                    "ordinal": ordinal,
                    "action": entry.action,
                    "date_text": entry.date_text,
                    "fr_citation_text": entry.fr_citation,
                    "fr_citation_scheme": None,
                    "fr_document_number": None,
                    # Stated on every row rather than left to the schema: the
                    # correction columns are NULL everywhere the roster did not
                    # speak, and a counter over them must not have to know that.
                    "fr_corrected_document_number": None,
                    "fr_corrected_volume": None,
                    "fr_corrected_page": None,
                    "fr_correction_evidence": None,
                }
                if entry.fr_citation is None:
                    timetables.append({**base, "citation_ordinal": 0, "fr_volume": None,
                                       "fr_page": None, "parse_status": "absent"})
                elif not citations:
                    # The column declares its scheme, so a value the FEDERAL
                    # REGISTER grammar cannot read may still be a complete
                    # citation under a grammar that grammar does not know.
                    # NARA writes "<volume>-<issue>; <first>-<last>", and
                    # "89 FR 21436" is DERIVABLE from it -- no damage operator
                    # involved, so the reading is "ok" like any other text-
                    # grounded one. The other three schemes state a volume and
                    # NO page, which is "partial": a different fact from a
                    # value nothing could read, and one this table used to hide
                    # inside a single "failed" bucket of 21.
                    reading = parse_agenda_timetable_citation(entry.fr_citation, rin=record.rin)
                    if reading.scheme == "unread":
                        # No grammar read this text, so it is damage rather than
                        # a scheme: ask the pinned Federal Register roster which
                        # document it meant. A row the roster cannot corroborate
                        # stays "failed" with its text exactly as the filer
                        # wrote it -- the repair is additive in both directions.
                        repair = _corroborated_fr_citation(
                            entry.fr_citation,
                            rin=record.rin,
                            date_text=entry.date_text,
                            roster=fr_roster,
                        )
                        timetables.append({
                            **base, "citation_ordinal": 0, "fr_volume": None, "fr_page": None,
                            "parse_status": "failed" if repair is None else "corroborated",
                            **(repair or {}),
                        })
                    else:
                        timetables.append({
                            **base,
                            "citation_ordinal": 0,
                            "fr_volume": reading.volume,
                            "fr_page": reading.page,
                            "fr_citation_scheme": reading.scheme,
                            "fr_document_number": reading.fr_document_number,
                            "parse_status": "ok" if reading.page is not None else "partial",
                        })
                else:
                    status = "relabeled" if relabeled else ("positional" if positional else "ok")
                    for citation_ordinal, citation in enumerate(citations):
                        timetables.append({**base, "citation_ordinal": citation_ordinal,
                                           "fr_volume": citation.volume, "fr_page": citation.page,
                                           "parse_status": status})
            # A record's authorities are its BOXES and then, where the list
            # outran them, the continuations the filer typed into
            # ADDITIONAL_INFO. One loop reads both: a continuation is a
            # publisher reference like any other, and the only things that
            # differ are which field it came from and its ordinal, which
            # continues the box numbering (box count + k, k from zero) so the
            # two can never collide. See LEGAL_AUTHORITIES_SCHEMA's
            # authority_source for the measurement.
            authority_references = [
                (ordinal, text, AUTHORITY_SOURCE_BOX)
                for ordinal, text in enumerate(record.legal_authorities)
            ] + [
                (
                    len(record.legal_authorities) + offset,
                    continuation.text,
                    f"additional-info:{continuation.label_family}",
                )
                for offset, continuation in enumerate(
                    legal_authority_continuations(record.additional_info)
                )
            ]
            for ordinal, text, authority_source in authority_references:
                # parse_authority_citation always returns at least one row —
                # unreadable text comes back typed "other"/"failed" — so no
                # empty-branch here can silently drop a string.
                parsed_authorities = list(parse_authority_citation(text))
                # An authority the grammars cannot read may still be an
                # act-relative citation — "Clean Air Act sec 112" — decidable
                # only against the OLRC's own name index (the index IS the
                # grammar). 659 distinct failed texts resolve this way.
                if (
                    act_lookup is not None
                    and len(parsed_authorities) == 1
                    and parsed_authorities[0].authority_type == "other"
                ):
                    # The lookup is the spelling closure over the OLRC index:
                    # membership admits a derived variant, the value is always
                    # the canonical key.
                    act_citations = find_act_relative_citations(text, act_names=act_lookup)
                    normalized_whole = normalize_popular_name(text)
                    bare_key = next(
                        (
                            act_lookup[candidate]
                            for candidate in (
                                normalized_whole,
                                _LEADING_ARTICLE.sub("", normalized_whole),
                                normalize_popular_name(_TRAILING_PARENTHETICAL.sub("", text)),
                                normalize_popular_name(_ACT_DESIGNATOR_TAIL.sub("", text)),
                                _LEADING_ARTICLE.sub(
                                    "", normalize_popular_name(_ACT_DESIGNATOR_TAIL.sub("", text))
                                ),
                            )
                            if candidate in act_lookup
                        ),
                        None,
                    )
                    name_section = _bare_name_section_reading(text, act_lookup)
                    if act_citations:
                        parsed_authorities = [
                            replace(
                                parsed_authorities[0],
                                authority_type="act_relative",
                                act_key=citation.act_key,
                                act_section=citation.section,
                            )
                            for citation in act_citations
                        ]
                    elif name_section is not None:
                        parsed_authorities = [
                            replace(
                                parsed_authorities[0],
                                authority_type="act_relative",
                                act_key=name_section[0],
                                act_section=name_section[1],
                            )
                        ]
                    elif bare_key is not None:
                        parsed_authorities = [
                            replace(
                                parsed_authorities[0],
                                authority_type="act_relative",
                                act_key=bare_key,
                            )
                        ]
                    elif prose_readings := _act_prose_recoveries(text, act_lookup):
                        # The wave-3 spelling operators: sections-in-front,
                        # parenthetical drops, year-prefix reordering,
                        # designator strips — every reading reaches a key the
                        # closure already answers, one row per listed section.
                        parsed_authorities = [
                            replace(
                                parsed_authorities[0],
                                authority_type="act_relative",
                                act_key=key,
                                act_section=section,
                            )
                            for key, section in prose_readings
                        ]
                    elif act_matcher is not None and (
                        "act" in text.lower() or "amendment" in text.lower()
                    ):
                        matched = act_matcher.match(normalized_whole)
                        if matched is not None:
                            parsed_authorities = [
                                replace(
                                    parsed_authorities[0],
                                    authority_type="act_relative",
                                    parse_status="partial",
                                    act_key=matched,
                                )
                            ]
                            tally.fuzzy_act_rows += 1
                    if (
                        parsed_authorities[0].authority_type == "other"
                        and len(normalized_whole) >= 40
                    ):
                        # Truncation completion: the value is a PREFIX of
                        # exactly one canonical name ("...Equity Act: A
                        # Legacy for U" lost "sers" to a field boundary).
                        # 40 is the measured floor of the recovered set;
                        # exactly-one-survivor refuses shared prefixes.
                        completions = {
                            canonical
                            for canonical in act_names
                            if canonical.startswith(normalized_whole)
                        }
                        if len(completions) == 1:
                            parsed_authorities = [
                                replace(
                                    parsed_authorities[0],
                                    authority_type="act_relative",
                                    parse_status="partial",
                                    act_key=next(iter(completions)),
                                )
                            ]
                            tally.prefix_act_rows += 1
                corroborated_pl: tuple[str, str] | None = None
                if (
                    pl_roster is not None
                    and len(parsed_authorities) == 1
                    and parsed_authorities[0].authority_type == "other"
                ):
                    corroborated_pl = _corroborated_public_law_from_failed(text, pl_roster)
                # ``citation_ordinal`` is NOT numbered here. Corroboration
                # explodes one failed row into several readings, and a number
                # assigned before that happens cannot tell those apart --
                # ``_number_citations`` assigns it once, after every row exists.
                for authority in parsed_authorities:
                    if corroborated_pl is not None:
                        # A separator-damaged Public Law recovered against the
                        # pinned roster: typed, labelled "corroborated" (the
                        # grammar read nothing; the roster did), the reading
                        # in the correction columns and never in public_law.
                        tally.corroborated_rows += 1
                        authorities.append(
                            {
                                # Every schema column present, so the contract
                                # counters below never meet a missing key.
                                **dict.fromkeys(LEGAL_AUTHORITIES_SCHEMA.names),
                                "rin": record.rin,
                                "publication_id": record.publication_id,
                                "ordinal": ordinal,
                                "authority_text": text,
                                "authority_source": authority_source,
                                "authority_type": "public_law",
                                "parse_status": "corroborated",
                                "usc_appendix": False,
                                "usc_note": False,
                                "public_law_corrected": corroborated_pl[0],
                                "pl_correction_evidence": corroborated_pl[1],
                                "corroboration_rule": corroborated_pl[1],
                            }
                        )
                        continue
                    if authority.act_key is not None:
                        act_keys_by_rin.setdefault(record.rin, set()).add(authority.act_key)
                        act_keys_by_agency.setdefault(record.rin[:4], set()).add(authority.act_key)
                    # Validity carries a calendar. An act named with a year
                    # later than the edition citing it cannot be the act that
                    # edition meant: a 2006 filing cannot cite a 2008 law. The
                    # alias rule supplies a year when exactly one act supplies
                    # it, which is right in general and wrong when the only
                    # candidate had not been enacted yet, so the date refuses
                    # the resolution rather than choosing another.
                    resolved_act_key = _act_key_within_calendar(
                        authority.act_key, record.publication_id, tally
                    )
                    corrected_pl, correction_evidence = _public_law_correction(
                        text, authority.public_law, pl_roster
                    )
                    # Three different facts wore one type. Which one this
                    # row is is what lets a consumer report the incomplete
                    # lists and the off-form "None" rather than absorb both
                    # as "placeholder". The kind table decides, not the
                    # grammar: the rule-level completeness flags read the
                    # same table, and a spelling it knows that the grammar
                    # does not (". . ." with spaces, RIN 0625-AA66) would
                    # otherwise flag a rule whose row denies the flag.
                    unstated_kind = _unstated_kind(text)
                    authorities.append(
                        {
                            "rin": record.rin,
                            "publication_id": record.publication_id,
                            "ordinal": ordinal,
                            "authority_text": text,
                            "authority_source": authority_source,
                            "restates_box_citation": None,
                            "authority_type": (
                                "unstated" if unstated_kind else authority.authority_type
                            ),
                            "parse_status": (
                                "failed" if unstated_kind else authority.parse_status
                            ),
                            "unstated_kind": unstated_kind,
                            "usc_title": authority.usc_title,
                            "usc_section": authority.usc_section,
                            "usc_section_end": authority.usc_section_end,
                            "usc_section_span_rule": authority.usc_section_span_rule,
                            "usc_chapter": authority.usc_chapter,
                            "usc_chapter_end": authority.usc_chapter_end,
                            "usc_appendix": authority.usc_appendix,
                            "cfr_title": authority.cfr_title,
                            "cfr_part": authority.cfr_part,
                            "cfr_section": authority.cfr_section,
                            # The reader's own verdict on the part, carried
                            # rather than dropped: the sibling reference table
                            # judges the identical string and this one did not.
                            "cfr_part_is_plausible": authority.cfr_part_is_plausible,
                            "reorganization_plan": authority.reorganization_plan,
                            "act_key": resolved_act_key,
                            "act_section": authority.act_section,
                            # Every series verdict is dated to the edition that
                            # made the citation, not to today: "54 USC 4118" in
                            # a Spring 2004 filing read as possible until this
                            # was, because title 54 exists NOW. See
                            # ``_SeriesCalendar`` for what each bound is pinned
                            # to and why the executive-order one is not dated.
                            "usc_title_is_possible": calendar.usc_title_is_possible(
                                authority.usc_title, record.publication_id
                            ),
                            "eo_in_known_series": calendar.eo_in_known_series(
                                authority.executive_order
                            ),
                            "pl_congress_in_series": calendar.pl_congress_in_series(
                                authority.public_law, record.publication_id
                            ),
                            "public_law_corrected": corrected_pl,
                            "pl_correction_evidence": correction_evidence,
                            "stat_volume_in_series": calendar.stat_volume_in_series(
                                authority.statute_volume, record.publication_id
                            ),
                            # The other Statutes fence, and the one the series
                            # bound cannot reach: a real volume printed beside
                            # a Public Law that cannot be in it.
                            "statute_volume_matches_public_law": (
                                authority.statute_volume_matches_public_law
                            ),
                            "case_reporter": authority.case_reporter,
                            "case_volume": authority.case_volume,
                            "case_page": authority.case_page,
                            "presidential_doc_kind": authority.presidential_doc_kind,
                            "proclamation": authority.proclamation,
                            "admin_order_kind": authority.admin_order_kind,
                            "admin_order_number": authority.admin_order_number,
                            "treaty_series": authority.treaty_series,
                            "treaty_volume": authority.treaty_volume,
                            "treaty_number": authority.treaty_number,
                            "treaty_page": authority.treaty_page,
                            "constitution_article": authority.constitution_article,
                            "constitution_section": authority.constitution_section,
                            "eo_compilation_start": authority.eo_compilation_start,
                            "eo_compilation_page": authority.eo_compilation_page,
                            "usc_note": authority.usc_note,
                            "public_law": authority.public_law,
                            "executive_order": authority.executive_order,
                            "statute_volume": authority.statute_volume,
                            "statute_page": authority.statute_page,
                            "statute_page_text": authority.statute_page_text,
                            "statute_volume_text": authority.statute_volume_text,
                            # A statement is what a row has INSTEAD of a
                            # resolution. Later passes resolve some rows the
                            # grammar could not read, and where one does, the
                            # resolution supersedes the statement rather than
                            # sitting beside it -- so no consumer ever has to
                            # decide which of the two to believe.
                            # A value states both when it carries both:
                            # "42 USC 7401 Clean Air Act" reads as USC 42:7401
                            # AND names an act. The citation used to survive
                            # while the name was dropped, because statements
                            # were emitted only on rows nothing could read.
                            # Guarded on the RESOLVED key, not the one the
                            # grammar proposed. Where the calendar refuses a
                            # resolution the row has no act key, so it is back
                            # to stating what it states -- and three rows
                            # ("The Emergency Supplemental Appropriations Act
                            # for Defense" in 2006 and 2007 editions) used to
                            # come out holding neither, which is the one thing
                            # a refusal must never cost.
                            "stated_act_name": (
                                None if resolved_act_key else (authority.stated_act_name or stated_act_name(text))
                            ),
                            "stated_section": (
                                None if resolved_act_key else (authority.stated_section or stated_section(text))
                            ),
                            "fr_volume": authority.fr_volume,
                            "fr_page": authority.fr_page,
                            "fr_volume_in_series": calendar.fr_volume_in_series(
                                authority.fr_volume, record.publication_id
                            ),
                            "fr_page_in_series": calendar.fr_page_in_series(authority.fr_page),
                            "revised_statute_section": authority.revised_statute_section,
                            "dc_code_section": authority.dc_code_section,
                            # Non-NULL exactly when parse_status is
                            # "corroborated"; the passes below set it.
                            "corroboration_rule": None,
                            # Written by the sibling-act carry alone, which is
                            # a later pass; stated here so every schema column
                            # is a key the emission writes.
                            "act_resolution_sibling_ordinal": None,
                            # Written by the pinned-roster reader alone, which
                            # is a later pass; stated here so every schema
                            # column is a key the emission writes.
                            "act_initialism_roster": None,
                        }
                    )

    # Corroboration: a dozen named damage operators, each fenced by a pinned
    # oracle and each required to leave exactly one survivor. The order below
    # IS the priority of the rules, and it is what makes four separate sweeps
    # over 798k rows equivalent to one sweep over the failed pool -- so it is
    # written down as an object rather than left implicit in the statement
    # order of a function body.
    act_oracles = (
        None
        if act_lookup is None
        else _ActOracles(
            lookup=act_lookup,
            keys_by_rin=act_keys_by_rin,
            keys_by_agency=act_keys_by_agency,
            glosses=_harvest_act_glosses(authorities),
            pinned=_initialism_roster(),
        )
    )
    authorities = _corroborate(
        authorities,
        _corroboration_readers(
            authorities,
            act_oracles,
            set(pl_roster[0]) if pl_roster is not None else None,
            tally,
            # Loaded ONCE and handed to both readers of it: the scheme-label
            # rule asks the section oracle whether a repaired U.S.C. reading
            # names a section the Code prints, and ``_judge_usc_sections``
            # asks the same object the same question of every row afterwards.
            section_oracle=section_oracle,
            calendar=calendar,
        ),
        tally,
        calendar,
    )
    # And the slash, immediately after: its pieces are put to the SAME act
    # readers corroboration just ran, so a second authority behind a slash
    # resolves on the evidence it would resolve on standing alone. It runs
    # after rather than inside that sweep because it is the one rule here that
    # ADDS a citation to a box the grammar already read -- corroboration is
    # offered only rows that read nothing, and rightly so.
    authorities = _read_slash_second_authorities(
        authorities, _slash_act_readers(act_oracles, tally), tally, calendar
    )
    # After corroboration, deliberately: the box a carry reads its act from is
    # itself often a corroborated one ("CWA 101" is an initialism nothing but
    # the RIN's own roster could read), so a carry run earlier would find the
    # neighbour empty.
    sibling_acts = _carry_sibling_acts(authorities, act_index, credits, tally, calendar)
    # And the box-run join after BOTH, for the same reason: a box the RIN's own
    # history, a damaged label or a neighbouring act already answered is not a
    # fragment, and a join run earlier would absorb boxes another rule read.
    authorities, joins = _join_box_runs(authorities, section_oracle, calendar)
    # And the title carry after the join, so a box the join already read as
    # part of its neighbour's list is never read a second time here.
    authorities, title_carry = _carry_usc_titles(authorities, section_oracle, tally, calendar)
    # And the ACT carry last of all, for the same reason twice over: a box the
    # join absorbed or the title carry already read is not a box waiting for an
    # act. Its donor may be a box CORROBORATION answered and its donor's act
    # may be three letters only the RIN's own roster can read, so the same
    # oracles the readers were fenced with are handed to it.
    authorities, act_carry = _carry_acts_from_an_earlier_box(
        authorities,
        act_index,
        credits,
        None
        if act_lookup is None
        else _ActOracles(
            lookup=act_lookup,
            keys_by_rin=act_keys_by_rin,
            keys_by_agency=act_keys_by_agency,
            glosses={},
            pinned=None,
        ),
        tally,
        calendar,
    )
    # And the span-endpoint gate before the numbering, so every row that will
    # ever carry a far end has been asked about it: corroboration and the
    # carries mint U.S.C. readings of their own, and a gate applied earlier
    # would leave those unasked.
    _refuse_unprintable_span_ends(authorities, section_oracle, tally)
    # One writer for the key column, after every row that will ever exist does.
    authorities = _number_citations(authorities)
    # And one writer for the restatement flag, in the same place and for the
    # same reason: corroboration explodes rows and the carry fills identity
    # columns, so a flag written at emission would describe a citation the
    # published row no longer states.
    restating_rows = _judge_restatements(authorities)
    # And one writer for the section fence, in the same place and for the same
    # reason: corroboration mints U.S.C. readings of its own, and a fence
    # applied before them would leave those rows unjudged.
    usc_sections = _judge_usc_sections(
        authorities,
        section_oracle,
        # The same two rosters the corroboration readers above were fenced
        # with, read a second time for a different question: not "which act is
        # this box naming" but "does an act this filer administers number the
        # section token itself". Built here rather than inside the fence so the
        # act index is opened once for the whole build.
        _ActNumbering.build(act_index, act_keys_by_rin, act_keys_by_agency),
    )
    # And the cheap fence beside it, derived from this build's own rows.
    implausible_magnitudes = _judge_usc_section_magnitudes(authorities)
    # A row that names an act IS act-relative, even where nothing can resolve
    # it. Before the resolver, so the rows it types are counted in the
    # resolver's own census rather than beside it.
    stated_acts = _type_stated_acts(authorities, act_lookup)
    # And LAST, the act resolver -- after both fences, so the sections it fills
    # from OLRC's tables never enter a verdict about what the filers wrote.
    act_resolutions = _resolve_act_citations(authorities, act_index, credits)
    # And the section fence a second time, over exactly the rows the resolver
    # just filled and no others. Here rather than inside the fence above for
    # the reason the resolver's own docstring gives: these sections are OLRC's
    # answer about an act, so they are judged in a census of their own and
    # every U.S.C. fence count stays a statement about the same population it
    # always was. The magnitude ceiling is still not asked -- it is derived
    # from the corpus's own rows, and derived rows would move it.
    act_sections = _judge_act_derived_sections(authorities, section_oracle)
    # The publisher's own answer key, after everything: it judges what the row
    # SAYS, and corroboration, the sibling carry and the act resolver are all
    # able to change that. Additive -- it writes two columns of its own and
    # touches no other value.
    cfr_notes_reader = _cfr_authority_notes()
    cfr_notes = _judge_against_cfr_notes(authorities, references, cfr_notes_reader)
    # And the U.S.C.-slot naming, additive and last for the same reason: it
    # only ever reads usc_title/usc_section/usc_section_verdict, never writes
    # them, so where it runs relative to every fence above changes nothing it
    # sees.
    usc_slot_readings = _write_usc_slot_reading(authorities, references, section_oracle)
    # And the C3 promotion, additive and last for the same reason: it only
    # ever reads usc_section_verdict/usc_section_corrected and writes the
    # correction columns where the fence above left them NULL.
    paren_eaten_suffixes = _promote_paren_eaten_lettered_suffix(authorities, section_oracle)
    # And the placeholder-candidate cross-reference, additive and last: it
    # reads every row's own family reading and every record's CFR_LIST, and
    # writes only the two columns an "unstated" row carries. The SAME notes
    # reader the CFR-note join above just loaded, not a second read of the
    # 8,240-part cache, and the SAME section oracle every fence above asked,
    # which is what lets a candidate be put to the oracle that exists for its
    # own family instead of resting on two witnesses counting to two.
    placeholder_candidates = _write_placeholder_candidates(
        authorities, references, cfr_notes_reader, calendar, section_oracle
    )

    outputs: dict[str, str] = {}
    schema_digests: dict[str, str] = {}
    for name, rows, schema in (
        ("unified_agenda_actions", actions, ACTIONS_SCHEMA),
        ("unified_agenda_cfr_references", references, CFR_REFERENCES_SCHEMA),
        ("unified_agenda_legal_authorities", authorities, LEGAL_AUTHORITIES_SCHEMA),
        ("unified_agenda_timetables", timetables, TIMETABLES_SCHEMA),
    ):
        table = pa.Table.from_pylist(rows, schema=schema)
        path = output_root / f"{name}.parquet"
        # Deterministic settings: the same pinned bytes must produce the same
        # file, or this artifact cannot be pinned in turn.
        pq.write_table(table, path, compression="zstd", compression_level=3, write_statistics=False)
        outputs[name] = file_sha256(path)
        schema_digests[name] = arrow_schema_sha256(schema)

    # The receipt declares the contract so a consumer's pin failure names the
    # change instead of just failing: schema semantics, and the classification
    # counts that moved twice in one day before this block existed.
    # The stem table the closure's year-less rule reads, restated so the
    # receipt can count what that rule admitted and what it refused.
    yearless = _yearless_stems(act_names or ())
    impossible = sum(1 for row in references if row["cfr_title_is_possible"] is False)
    implausible = sum(1 for row in references if row["cfr_part_is_plausible"] is False)
    titleless = sum(1 for row in references if row["cfr_title"] is None)
    failed = sum(
        1 for row in authorities if row["parse_status"] == "failed" and row["authority_type"] == "other"
    )
    unstated = sum(1 for row in authorities if row["authority_type"] == "unstated")
    cfr_unstated = sum(
        1 for row in references if row["cfr_title"] is None and states_nothing(row["reference_text"])
    )
    partial = sum(1 for row in authorities if row["parse_status"] == "partial")
    # The ADDITIONAL_INFO continuations, counted three ways: the RECORDS each
    # label family answered for, the ROWS they yielded, and those rows split by
    # (authority_type, parse_status). A record is counted once per family it
    # used, which is exactly what the reader emits.
    continuation_records: dict[str, set[tuple[object, object]]] = {
        source: set() for source in AUTHORITY_SOURCES if source != AUTHORITY_SOURCE_BOX
    }
    continuation_rows: dict[str, int] = dict.fromkeys(continuation_records, 0)
    continuation_shape: dict[str, int] = {}
    for row in authorities:
        source = row["authority_source"]
        if source == AUTHORITY_SOURCE_BOX:
            continue
        continuation_records[source].add((row["rin"], row["publication_id"]))
        continuation_rows[source] += 1
        shape = f"{row['authority_type']}/{row['parse_status']}"
        continuation_shape[shape] = continuation_shape.get(shape, 0) + 1
    contract = {
        "schemaVersion": "exploded-v3",
        "rowSemantics": (
            "one row per parsed citation; a publisher reference that names N "
            "citations yields N rows sharing (rin, publication_id, ordinal) and "
            "distinguished by citation_ordinal; a reference with no readable "
            "citation yields one all-null row so nothing vanishes. A publisher "
            "reference is a LEGAL_AUTHORITY_LIST box or an ADDITIONAL_INFO "
            "continuation; authority_source says which"
        ),
        "authorityContinuationsAreThePublishersOwnBytes": (
            "the Agenda's form gives a filer a fixed number of legal-authority "
            "boxes, and a filer whose list outran them typed the rest into "
            "ADDITIONAL_INFO under a label. Those citations were in the "
            "publisher's bytes and in no column of this table until 2026-08-23. "
            "authority_source names the field and the label family a row was read "
            "from: 'box' for the structured LEGAL_AUTHORITY_LIST element, "
            "'additional-info:legal-authority-cont' for the "
            "AUTHORIT(Y|IES)-CONT family (six case-folded spellings) and "
            "'additional-info:additional-legal-authority' for the Additional "
            "Legal Authority family. ORDINAL on a continuation row is the "
            "record's box count plus k for the k-th continuation, counting from "
            "zero, so it continues the box numbering and cannot collide with it. "
            "The WHOLE continuation string is read as one reference and never "
            "pre-split: RIN 1115-AE47's Spring 1997 continuation is a bare comma "
            "list under one title that reads to 41 citations whole and 7 split. "
            "A continuation is read from its label's end to the publisher's '^' "
            "paragraph mark, a blank line, or another field continuing under its "
            "own label. 'STATUTORY DEADLINE CONT:' and 'CFR CITATION(S) CONT:' "
            "are OTHER fields' continuations and are not read here, and neither "
            "is a bare 'Legal Authority:' label, which restates a field rather "
            "than continuing it. restates_box_citation marks the continuation "
            "rows whose published identity a box of the same record already "
            "carries -- emitted, never dropped, because the filer wrote them"
        ),
        "grammar": "refspec.registry.citation_grammar",
        "verdictColumnsAreThreeValued": (
            "cfr_title_is_possible and cfr_part_is_plausible are NULL when there "
            "is nothing to judge; truthiness misreads NULL as False"
        ),
        "seriesVerdictsAreDated": (
            "usc_title_is_possible, pl_congress_in_series and stat_volume_in_series "
            "judge the citation against the series as it stood in the edition's own "
            "year, not as it stands today: '54 USC 4118' in a 2004 edition is False "
            "because title 54 was enacted in 2014. The bound comes from the pinned "
            "congress.gov roster read by approval date. eo_in_known_series is NOT "
            "dated -- no EO date oracle is pinned in this tree, and the cost was "
            "measured at zero rows"
        ),
        "uscSectionMagnitudeIsAHeuristicNotTheOracle": (
            "usc_section_magnitude_is_plausible is the CORPUS judging itself -- the "
            "99th percentile of the section stems each title attests in THIS build, "
            "times ten -- and it is a label, never a repair. It is not the "
            "section-existence oracle and does not stand in for one: the oracle "
            "columns beside it find these and 18,000 rows more. What it has instead "
            "is a cost measured against all 66,780 real (title, section) pairs the "
            "OLRC oracle holds, where the row-weighted ceiling refuses exactly one "
            "real section (47 U.S.C. 11007, Broadband DATA Act 2020, which this "
            "corpus never cites). NULL for a title the corpus never cited, which is "
            "a silence and not a verdict"
        ),
        "uscSectionsAreFencedByTheOracle": (
            "usc_section_verdict / _reason / _attested_at_edition / _corrected / "
            "_correction_evidence are refspec.registry.usc_section_oracle's answers "
            "about usc_section, from OLRC release point 119-102 plus every annual "
            "archive 1994-2024. NULL where there is nothing to judge: no section "
            "stated, or a title the citing edition could not have cited "
            "(usc_title_is_possible = false, which outranks the section question). "
            "The three verdict columns also stand on act-derived sections -- see "
            "anActDerivedSectionIsJudgedAtTheCitingEdition -- and the correction "
            "columns do not, so the invariant is: a verdict wherever usc_section is "
            "non-null and the row is either authority_type 'usc' or act_relative with "
            "an act_resolution_evidence, and NULL on every other row. "
            "'absent' means printed in NO edition the oracle covers, 1994-2026 -- "
            "never 'never existed': a section repealed before the 1994 edition and "
            "not stubbed in the release point is invisible to it, and 18 U.S.C. 3568 "
            "(repealed effective 1987-11-01, still cited deliberately for pre-1987 "
            "conduct, 182 rows) is the specimen that reads absent here and is not a "
            "misread. Where coverage is structurally missing the verdict is "
            "'unknown' and NAMES the hole. usc_section_attested_at_edition = false "
            "beside 'exists' is an ERA MISMATCH and not a misread: the archives lag "
            "enactment, so the edition year narrows and never accuses. A correction "
            "is published only where exactly one reading survives the oracle, in the "
            "Code's own spelling, and the original stays in usc_section; only "
            "usc_section is judged, never usc_section_end"
        ),
        "uscSectionCorrectedIsSplitForKeying": (
            "usc_section_corrected carries the CODE's spelling, where '371(a)' is a "
            "pinpoint into section 371 and '1395hh' is a lettered section, so it is "
            "not a key: usc_section_corrected_section is the section IDENTITY the "
            "surviving reading names and usc_section_corrected_pinpoint the "
            "parenthesised pinpoint beside it (NULL where there is none), both from "
            "that one Correction, and concatenating them re-spells "
            "usc_section_corrected exactly. Key on the identity -- and, where the "
            "correction is B8-lettered-section-rather-than-a-pinpoint, treat the "
            "identity it proposes as a CANDIDATE beside the parsed usc_section "
            "rather than in place of it: B8 rests on the release point printing no "
            "lettered subsection on the bare section, which is high precision and "
            "not a proof, and the four keys with measured document exposure (15 "
            "U.S.C. 18, 12 U.S.C. 1715, 47 U.S.C. 399, 25 U.S.C. 161) are correct "
            "citations that B8 would move. uscSectionCorrectedIdentityMovedRowsByRule "
            "counts the rows where the identity is not the parsed section"
        ),
        "actRelativeRowsAreResolvedNotJustRecognised": (
            "an act_relative row is resolved through the pinned OLRC act index and "
            "the Code's own source credits at build time. Where exactly one U.S.C. "
            "section answers, usc_title and usc_section carry it and "
            "act_resolution_evidence names which source classified it; act_key and "
            "act_section keep the citation as the filer made it, so the resolution "
            "can be dropped by ignoring two columns. Where none answers, "
            "act_resolution_reason names the refusal (ACT_RESOLUTION_REASONS: the "
            "resolver's own codes, plus no_section_stated, "
            "act_key_refused_by_edition_calendar, and three narrowings -- "
            "act_section_inside_a_range_key, resolves_to_note, "
            "revised_statutes_only). parse_status on these rows therefore reads "
            "'resolved' where a section was filled, 'partial' where the act "
            "resolved and the section did not, and 'failed' only where the act "
            "itself is unknown -- 'failed' used to mean 'not corroborated by RIN "
            "history' and was published on 6,214 rows whose parse had succeeded. "
            "Rows already corroborated by RIN history keep parse_status "
            "'corroborated': that corroboration is a different fact, and it is the "
            "one their corroboration_rule names. The MAGNITUDE fence never sees "
            "these sections -- its ceiling is derived from the corpus's own rows, "
            "and a derived row would move it; the section-existence fence does, in "
            "a census of its own (anActDerivedSectionIsJudgedAtTheCitingEdition)"
        ),
        "anActDerivedSectionIsJudgedAtTheCitingEdition": (
            "a section an act resolution filled is judged like any other: the same "
            "oracle, the same usc_section_verdict / _reason / _attested_at_edition, "
            "the same edition year, written by the same function. It is a WITNESS "
            "beside the identity and never a rewrite -- usc_title, usc_section, "
            "act_key and act_section are untouched, no correction is asked for "
            "(nothing here was typed as a U.S.C. citation) and no recodification "
            "table is read. Table III states a CURRENT classification, so the "
            "question the verdict answers is the one the classification cannot: did "
            "the edition that filed this citation print the section it now maps to. "
            "usc_section_attested_at_edition = false beside 'exists' is that answer "
            "and is an era mismatch, not a misread -- 20 U.S.C. 10005 (ARRA 2009 sec "
            "14005) is first printed in the 2014 archive and RIN 1810-AB17 cited the "
            "act section in the 2013 edition. The counts are actSectionVerdict* and "
            "actSectionExistsNotAtEditionRows, kept apart from the uscSection* keys "
            "because the two populations are disjoint and a consumer gating on these "
            "identities needs its own number"
        ),
        "aSuccessorIsEvidenceAndNeverAnIdentity": (
            "usc_disposition_verdict, usc_disposition_successors and "
            "usc_disposition_table say what a positive-law recodification did with a "
            "former section the U.S.C. section oracle cannot see, from "
            "refspec.registry.usc_disposition_tables over the printed 'TABLE SHOWING "
            "DISPOSITION OF FORMER SECTIONS OF TITLE 49' in the 1994 volume (govinfo "
            "USCODE-1994-title49, digest-pinned in that module). They are written ONLY "
            "beside a usc_section_verdict of 'unknown' whose reason is "
            "title_49_appendix_not_published and are NULL on every other row. THE "
            "VERDICT BESIDE THEM DOES NOT MOVE and neither does its reason: no OLRC "
            "archive year publishes a Title 49 Appendix, which is still true, and what "
            "the table adds is a different question's answer -- Pub. L. 103-272 6(b) "
            "deems a citation to a former section to refer to its successor. "
            "usc_section_corrected is NOT written from this and no existing value in "
            "the row depends on it. THE SUCCESSOR IS EVIDENCE AND NEVER AN IDENTITY: "
            "usc_disposition_successors is a LIST of every successor the table names, "
            "because a former section is not a unit the recodification preserved -- "
            "1432 becomes four sections and 1432(a) alone becomes two, separated only "
            "by printed prose ('(related to standards)' -> 44701 against '(related to "
            "issuing certificates).' -> 44702) that is not an address and is not in "
            "this column. On 62 of the 146 sections in this corpus the table names "
            "more than one, carrying the majority of the rows, so a consumer that "
            "keyed a tag on 'the' successor would be wrong more often than not; "
            "uscDispositionRowsBySuccessorCount is the number that says so. "
            "'not-in-table' is an ANSWER and not a silence -- the pinned table was read "
            "and lists no such former section -- and it is only as wide as the table: "
            "the table lists what existed to be restated in 1994, so a section repealed "
            "before that was never in it. One table is pinned; six other "
            "recodifications (31, 41, 46, 51, 54, 34, 10 ch. 1201) are not, which is "
            "why usc_disposition_table names which one answered"
        ),
        "theTableIsAskedTheCITATIONSOwnQuestion": (
            "the recodification table is asked over exactly what the citation states "
            "about its token, which is not always a bare section. A STATED span is "
            "asked member by member: usc_disposition_span_members names every former "
            "section the 1994 volume prints inside the range and usc_disposition_"
            "successors is the UNION over them, so '49 USC 1421 to 1431' answers for "
            "eleven former sections and not for 1421 alone as it did before "
            "2026-08-24. The members are the volume's own keys inside the endpoints, "
            "never a count from one to the other -- a count could not reach the "
            "lettered members (1a, 5a, 15b) and would claim members the volume does "
            "not print. An ABBREVIATED span (usc_section_span_rule 'abbreviated', this "
            "module's reading of '1421-31' rather than the filer's words) is never "
            "expanded here; uscDispositionAbbreviatedSpanRowsNotExpanded counts them "
            "and is zero. A STATED pinpoint NARROWS: where the printed table resolves "
            "the subsection the citation writes, only the rows that match it answer, "
            "and usc_disposition_pinpoint carries the pinpoint that did it -- '49 USC "
            "1651(b)(2)' answers 49:303 alone where bare '49 USC 1651' keeps both "
            "49:101 and 49:303, because the volume prints '1651(b)(2) -> 303' as a row "
            "of its own. Where the table knows the section but not that subsection the "
            "answer comes back UNNARROWED and usc_disposition_pinpoint is NULL: a "
            "subsection narrows and never accuses. usc_disposition_refusal names a row "
            "where no table was read at all -- 'chapter_qualifier_governs_the_token', "
            "where the citation writes 'ch' once over a list ('49 USC 106(g), ch 447 "
            "and 451'), the parse hands the later member on as a bare section, the "
            "number is a CURRENT chapter of the title in the pinned oracle's register, "
            "the row's own usc_appendix denies it is an appendix citation, and the "
            "record cites current law in that title. All three disposition columns are "
            "NULL there: an answer about a repealed 1930s block would be a true fact "
            "about a citation this filer did not make"
        ),
        "theRulesOwnCfrPartNoteIsAWitness": (
            "authority_in_own_cfr_note is the PUBLISHER's answer key beside the filer's "
            "text: present / near-miss / absent for the row's own citation against the "
            "authority note printed at the head of one of the rule's own CFR parts, from "
            "refspec.registry.cfr_authority_notes over 8,240 notes fetched 2026-08-24 from "
            "https://www.ecfr.gov/api/versioner/v1/ and digest-pinned there -- every "
            "authority note the register publishes, one request per title at that title's "
            "own latest issue date, where the 287 this column carried before were a "
            "set-cover over the agenda-to-CFR mapping. cfr_note_part "
            "names which part's note judged it. A VERDICT AND NEVER A REPAIR -- nothing in "
            "this table moves because of it. 'present' is identity, with a note range "
            "covering the sections between its endpoints and 'et seq.' never read as a "
            "range. 'near-miss' is one edit (Damerau-Levenshtein 1) on the identity, title "
            "included, and it is A LEAD AND NOT AN ACCUSATION: the campaign adjudicated 31 "
            "random near-miss texts at 12.9% precision by text and 5.6% by rows, because "
            "agencies legitimately cite neighbouring sections. 'absent' means absent from "
            "the note AS FETCHED 2026-08-24, which a corpus starting in 1995 predates: 49 "
            "CFR 192's note enumerated 60102-60137 when RIN 2137-AE60 cited them in 2010 "
            "and reads '60101 et. seq.' today. Four families are judged -- usc, "
            "public_law, cfr and act_relative -- and the rest are NULL and counted by type "
            "in cfrNoteUnjudgedRowsByType; the join key is the rule's own CFR Citation "
            "field, never a CFR part cited as authority"
        ),
        "unstatedIsThreeFacts": (
            "an unstated row names WHICH placeholder in unstated_kind: "
            "'more-citations-follow' is the agency saying the list is incomplete "
            "(so a consumer joining on legal authorities does NOT have the whole "
            "list for those rules), 'not-yet-determined' is the controlled value "
            "the RID form offers, and 'none-off-form' is a publisher defect -- the "
            "form offers no None box for Legal Authority and EO 12866 4(b) requires "
            "one. Join the timetable table to find the ones that carry a published "
            "document anyway"
        ),
        "aRowThatNamesAnActIsActRelativeEvenUnresolved": (
            "1,129 rows of this table read as NOTHING and yet state something: 624 "
            "a section alone, 505 an act's NAME. For the 471 whose name the OLRC "
            "index holds no key for, authority_type says 'act_relative' and "
            "act_resolution_reason says 'act_not_in_index' -- which is narrower and "
            "more useful than 'other'/'failed', a word a consumer reads as "
            "'unreadable'. ONE VALUE CHANGES on those rows: authority_type. "
            "parse_status stays 'failed' because the act is unknown, which is "
            "exactly what _ACT_UNKNOWN_REASONS already means; the statements stay "
            "where the filer put them, because no act key arrived to supersede "
            "them; and every other column on these rows was and stays NULL. A name "
            "the closure DOES hold is not this pass's business (34 rows): it "
            "belongs to index-holds-the-stated-name and to the two fences that "
            "guard it. Those fences also refused 13 rows they were never meant to: "
            "a number the row states as its own SECTION is not a year, and "
            "'sec 1919(a) to (g) of the Social Security Act' -- the shape that "
            "reader's own docstring names -- was refused for thirteen editions "
            "because 1919 matches a year. The 34 rows carrying a year that is NOT "
            "their section keep the refusal, which is what it was written for. The "
            "624 section-only rows are counted and left alone: a section with no "
            "act names nothing this module can type"
        ),
        "aTitlelessSectionTakesTheTitleBesideItOrNothing": (
            "usc_title_carried_from_ordinal and authority_carry_text are the "
            "sibling-usc-title-within-six-boxes rule's answer for a box holding "
            "nothing but section numbers. A U.S.C. section number says NOTHING "
            "about which title it belongs to, so the title comes from the nearest "
            "EARLIER box that states exactly one, within six; the carried string is "
            "handed to the grammar rather than assembled by hand; and every section "
            "AND EVERY RANGE END it produces has to be one the section oracle prints "
            "at the EDITION'S year -- '89-670 and 91-605' under title 23 is why the "
            "end is gated too, because 23 U.S.C. 605 is real and a gate on the start "
            "alone would have published both spans. It runs after the box-run join, "
            "so a box the join already read is never read twice, and after "
            "corroboration, so a box the RIN's own history answered keeps that "
            "answer. Four more fences, all counted: a box writing 'sec N' is refused "
            "because an ACT section is not a Code section (SSA sec. 1861 is 42 "
            "U.S.C. 1395x while 42 U.S.C. 1861 is the National Science Foundation "
            "Act, and nothing this rule can ask separates them); a box holding only "
            "a number a title could be is a title; '93-87' is a Public Law number; "
            "and two section-shaped tokens with a bare space between them are not a "
            "list at all -- '42 2000d-1' is 42 U.S.C. 2000d-1 with its label gone, "
            "and carrying title 40 onto it published 40 U.S.C. 42. The IN-BOX "
            "variant -- a bare number between semicolons under a stated title -- has "
            "a population of ZERO in this corpus and nothing is published for it"
        ),
        "aCutCitationListIsRECORDEDNeverRewritten": (
            "authority_box_run_start / _length, authority_join_rule and "
            "authority_join_text say that a run of <LEGAL_AUTHORITY> boxes is ONE "
            "citation list the publisher's form cut -- '46 USC 40501(a)-(e) and (g)' "
            "+ '40503' + '41102(2), (4) and (8)'. NO FIXED-WIDTH CHOP EXISTS to "
            "undo (box lengths mode at 10-11 characters and decay to 212), so the "
            "join is justified box by box and RECORDED rather than performed: "
            "authority_text is never rewritten and ordinal is never renumbered, "
            "because a consumer keyed on either would silently move, and an "
            "in-place rewrite would have moved 989 existing cells including 20 "
            "stated_section and 3 stated_act_name values. The citations the joined "
            "string yields that no box in the run already read are NEW rows on the "
            "DONOR box's ordinal; the absorbed boxes keep every row they had and "
            "gain superseded_by_join. NOTHING VANISHES. Four fences, each counted "
            "in authorityJoinRefusalsByReason: the join must ADD something; every "
            "value the donor read alone must survive it; the section oracle must "
            "print every U.S.C. section it mints AT THE EDITION'S YEAR; and a "
            "stated section may be welded only onto a Public Law or a Statutes "
            "page, only from a box that is nothing but that section -- so "
            "'sec.206' + 'PL 106-159' joins and 'MIPPA sec 153 (b' + 'PL 111-148 "
            "sec 3401(h)' does not. A fragment box must also OPEN with a section "
            "and then only list furniture, which is what keeps '42 2000d-1' and "
            "'10 ch 137' -- a lost LABEL, not a continuation -- from minting "
            "40 U.S.C. 42. Tier B (authority_join_rule 'list-continuation') is the "
            "other shape: a run of bare comma lists that yields no citation at "
            "all, recorded because 'these four boxes are one list' is true and "
            "nothing else in this table says it"
        ),
        "aDamagedSchemeLabelIsCorroboratedNeverGuessed": (
            "authority_label_corrected and label_correction_evidence carry the "
            "one-edit-on-a-scheme-label rule's reading of a value whose LABEL is "
            "damaged -- '16 USE 715(i)', '113tat. 1754 (1999)', '12 UDC 1735(f)-14'. "
            "The operator is one Levenshtein edit (substitution, insertion or "
            "deletion; NEVER a transposition) on one of SCHEME_LABELS, and the "
            "OPERATOR ALONE IS NEVER THE CORROBORATION: a pinned oracle has to "
            "print the place the repaired value names -- the U.S.C. section oracle "
            "at the EDITION's year, the Statutes volume series, the congress.gov "
            "Public Law roster, the Register's volume bound -- and exactly one "
            "reading may survive. Six fences, because 12 of the 55 values that "
            "reach a corroborated reading are traps: two letters minimum; a "
            "spelling the grammar already accepts is not damage; the token must "
            "stand in citation shape; NO COMPETING REPAIR MAY TYPE THE VALUE IN "
            "FULL ('Reorganization Plan No. 4 or 1978' is a reorganization plan "
            "under 'or' -> 'of' and never '4 FR 1978', however real Register "
            "volume 4 is); every residue run must be a fragment of the label's own "
            "letters or citation structure the grammar names, so 'Pu. Bl. 111-148' "
            "and '29 USC UC 794' -- right answer, wrong token -- are refused; and "
            "the row must state nothing else, which is what makes the rule "
            "additive by construction. THE TAIL RIDES ALONG: '12 USC 1735(f)-14' "
            "is 12 U.S.C. 1735f-14 by the oracle's exact tail enumeration and "
            "never the truncated 1735, which is the defect that demoted class B8. "
            "authority_text is never rewritten; the filer's spelling stays where "
            "the filer put it and this column says which single edit the reading "
            "beside it rests on"
        ),
        "aDamagedFrCitationIsCorroboratedNeverGuessed": (
            "fr_corrected_document_number / _volume / _page and "
            "fr_correction_evidence on the TIMETABLE table are the pinned Federal "
            "Register roster's answer for a citation NOTHING could read, from "
            "research/evidence/unified-agenda-fr-document-roster-2026-08-23/documents.csv "
            "-- six documents captured 2026-08-23 from "
            "https://www.federalregister.gov/api/v1/documents/, stored verbatim beside "
            "the CSV and digest-pinned in this receipt's producer block. NO NETWORK IS "
            "READ AT BUILD TIME. They are written ONLY on a row whose parse_status is "
            "'corroborated' and are NULL on every other row; fr_citation_text keeps the "
            "filer's damage untouched and fr_volume / fr_page stay NULL there, because "
            "no grammar read this text and these columns are what the ROSTER said. A "
            "consumer wanting only text-grounded readings is unaffected; one wanting "
            "the document joins on fr_corrected_volume / fr_corrected_page or straight "
            "on fr_corrected_document_number. ONE RULE, THREE FENCES, EXACTLY ONE "
            "SURVIVOR: a candidate comes from one named damage operator "
            "(FR_CITATION_DAMAGE_OPERATORS, at most one edit per row -- either the "
            "label is damaged and the page is read as written, or the label is a clean "
            "FR and the page is damaged), its (volume, page) must equal a roster "
            "document's (volume, START page) because that is what an FR citation names, "
            "the row's own date_text must equal that document's publication date, and a "
            "witness must tie the filer to it -- the row's RIN among the document's own, "
            "or, where the document lists none, the RIN's four-digit OMB agency code "
            "among those the roster records. Two survivors publish nothing, and a roster "
            "holding two documents at one (volume, start page) refuses at load. THE "
            "OPERATOR ALONE IS NEVER THE CORROBORATION: '89 FR 1022091' has two real "
            "single-digit-deletion readings in volume 89, 102091 (2024-29238, NOAA, "
            "carrying the citing rule's own RIN) and 102209 (a page inside 2024-29633, "
            "an SEC notice with no RIN, published the same day), and the second is "
            "refused by a roster row that holds it rather than by not being looked at. "
            "The evidence names both halves, '<operator>-witnessed-by-<witnesses>', so a "
            "consumer that trusts the exact-RIN witness and not the agency one can tell "
            "them apart; the agency witness exists because the FCC files no RIN into "
            "Federal Register metadata at all, and the shared docket that completes it "
            "is recorded in the roster's README because a timetable row has no docket "
            "column to check it against"
        ),
        "declaredClassifications": {
            "zeroPaddedTitlesReadAsInt": "07 CFR -> title 7 possible; 00 CFR -> title 0 impossible",
            "partIsAJoinKey": "leading zeros stripped: 0718 and 718 are one part",
            "compilationLocatorsAreNotCfrCitations": (
                "'3 CFR, 1977 Comp., p. 123' locates an EO's printed page and "
                "is excised before CFR matching; read them via "
                "parse_eo_compilation_locators"
            ),
            "impossibleTitleRows": impossible,
            "implausiblePartRows": implausible,
            "titlelessRows": titleless,
            "authorityFailedRows": failed,
            "authorityUnstatedRows": unstated,
            #: The ADDITIONAL_INFO continuations. Records and rows per label
            #: family, the rows by (authority_type, parse_status) -- a
            #: continuation states two or more citations by definition, so
            #: every readable row is "partial" and a shift out of that bucket
            #: is a finding -- and the rows whose identity a box of the same
            #: record already carries.
            "authorityContinuationRecordsBySource": {
                source: len(records) for source, records in sorted(continuation_records.items())
            },
            "authorityContinuationRowsBySource": dict(sorted(continuation_rows.items())),
            "authorityContinuationRowsByTypeAndStatus": dict(sorted(continuation_shape.items())),
            "authorityContinuationRestatingRows": restating_rows,
            #: The three facts the one type held, each counted, so a shift
            #: between them is visible instead of hiding inside the total.
            "authorityUnstatedRowsByKind": {
                kind: sum(1 for r in authorities if r["unstated_kind"] == kind)
                for kind in UNSTATED_KINDS
            },
            #: The act resolver's own census. Rows by outcome, rows by refusal
            #: reason (every declared reason, at zero if it stops firing), rows
            #: by answering source, and the resolved rows split by the status
            #: they carried before -- so the RIN-history corroborations stay
            #: countable apart from the rows this resolution alone answers.
            #: Counted in (act, section) PAIRS too, because that is the unit
            #: the resolver answers; rows are how often the corpus asked.
            "actRelativeRowsByStatus": act_resolutions.rows_by_status,
            "actRelativeRowsByResolutionReason": act_resolutions.rows_by_reason,
            "actRelativeResolvedRowsByEvidence": act_resolutions.rows_by_evidence,
            "actRelativeResolvedRowsByPriorStatus": act_resolutions.resolved_rows_by_prior_status,
            "actRelativeResolvedPairs": act_resolutions.pairs_resolved,
            "actRelativeRefusedPairs": act_resolutions.pairs_refused,
            #: The section fence over those resolved sections, counted the same
            #: four ways as the U.S.C. one and kept apart from it: a row here
            #: carries a section OLRC classified, not one a filer typed, and a
            #: consumer gating on these identities needs the number for its own
            #: population. actSectionVerdictActSections closes against
            #: actRelativeResolvedPairs above -- same unit, judged rather than
            #: resolved.
            "actSectionVerdictRows": act_sections.rows_by_verdict,
            "actSectionVerdictTexts": act_sections.texts_by_verdict,
            "actSectionVerdictPairs": act_sections.pairs_by_verdict,
            "actSectionVerdictRins": act_sections.rins_by_verdict,
            "actSectionVerdictActSections": act_sections.act_sections_by_verdict,
            "actSectionUnknownRowsByReason": act_sections.unknown_rows_by_reason,
            #: ``exists`` and the citing edition did not print it: Table III
            #: states a CURRENT classification, so a filing predating the Code
            #: home its act section now has is narrowed here and never accused.
            "actSectionExistsNotAtEditionRows": act_sections.exists_not_at_edition_rows,
            "actSectionTitleImpossibleRows": act_sections.title_impossible_rows,
            #: Which source classified it, and what the row already said,
            #: against the verdict -- the two splits the consumer's named
            #: reading is written in terms of.
            "actSectionVerdictRowsByEvidence": act_sections.rows_by_evidence_and_verdict,
            "actSectionVerdictRowsByStatus": act_sections.rows_by_status_and_verdict,
            #: The box-run join. Runs, boxes, the rows the joined strings
            #: yielded and the boxes those rows supersede -- plus the Tier-B
            #: runs, which yield no citation at all and are counted apart for
            #: exactly that reason. Rules and refusals both at their full
            #: declared vocabulary, so a shape that stops firing breaks a pin
            #: instead of shrinking a total.
            "authorityJoinRuns": joins.runs,
            "authorityJoinBoxes": joins.boxes,
            "authorityJoinRows": joins.rows,
            "authorityJoinSupersededRows": joins.superseded,
            "authorityJoinListContinuationRuns": joins.list_continuation_runs,
            "authorityJoinListContinuationBoxes": joins.list_continuation_boxes,
            "authorityJoinRunsByRule": joins.rules,
            "authorityJoinRefusalsByReason": joins.refusals,
            #: The stated-act labelling: how many rows read as nothing and yet
            #: state something, how they split between a section alone and an
            #: act's name, how many were typed act-relative, and what the pass
            #: declined to touch. The section-only rows are counted and left
            #: alone on purpose: a section with no act names nothing this
            #: module can type.
            "statedActRowsStatingSomething": stated_acts.states_something,
            "statedActSectionOnlyRows": stated_acts.section_only_rows,
            "statedActNamingAnActRows": stated_acts.names_an_act_rows,
            "statedActTypedRows": stated_acts.rows,
            "statedActRefusalsByReason": stated_acts.refusals,
            #: The title carry. The boxes of the right SHAPE, the ones that
            #: read as nothing, the ones that took a title and the rows they
            #: yielded -- and every refusal by the fence that spoke, because
            #: this rule refuses four times what it answers and the shape of
            #: the refusals is the argument that it is narrow rather than shy.
            "uscTitleCarryShapedBoxes": title_carry.shaped_boxes,
            "uscTitleCarrySilentBoxes": title_carry.silent_boxes,
            "uscTitleCarryBoxes": title_carry.boxes,
            "uscTitleCarryRows": title_carry.rows,
            "uscTitleCarryRefusalsByReason": title_carry.refusals,
            #: The sibling-act carry, and every refusal beside it. The yield is
            #: three rows and the refusals are three hundred, which is the
            #: honest shape of this rule and the reason it is counted rather
            #: than described.
            "siblingActCarriedRows": sibling_acts.rows,
            "siblingActRefusalsByReason": sibling_acts.refusals,
            #: The act carry from an EARLIER box, beside it. Its donor persists
            #: until another box names an act, so the reach is a measurement
            #: rather than a constant, and it is published: the furthest a
            #: carry actually travelled in this corpus.
            "actCarryBoxes": act_carry.boxes,
            "actCarryRows": act_carry.rows,
            "actCarryMaxDonorDistance": act_carry.max_distance,
            "actCarryRefusalsByReason": act_carry.refusals,
            #: The year-less short name, counted three ways. A name the corpus
            #: writes without its year answers only where the Popular Name Tool
            #: names exactly ONE act for it; where several acts claim the stem
            #: the variant is refused, and the refusal is counted rather than
            #: described, because "the lexicon was widened" and "the lexicon
            #: was widened by four names out of 638 candidates" are different
            #: claims. ``MergedByRename`` is the four the tool's own
            #: cross-references make one act.
            "actNameYearlessStemsAdmitted": sum(1 for acts in yearless.values() if len(acts) == 1),
            "actNameYearlessStemsRefused": sum(
                1 for stem, acts in yearless.items() if len(acts) > 1 and stem not in (act_lookup or {})
            ),
            "actNameYearlessStemsMergedByRename": sum(
                1 for stem, acts in yearless.items() if len(acts) > 1 and stem in (act_lookup or {})
            ),
            "actKeySimilarityMatchedRows": tally.fuzzy_act_rows,
            "actKeyPrefixCompletedRows": tally.prefix_act_rows,
            "authorityCorroboratedRows": tally.corroborated_rows,
            "actKeyAnachronismRefusals": tally.anachronisms,
            #: The split-citation rule's two refusals, each named: a run that
            #: two different Public Laws bound, and a run whose sections the
            #: publisher's own resolved citations bind elsewhere. Counted
            #: beside the rule's per-rule row count below, because a rule is
            #: only as trustworthy as what it declines to answer.
            "splitCitationAmbiguityRefusals": tally.split_run_ambiguities,
            "splitCitationPoolConflictRefusals": tally.split_run_pool_conflicts,
            #: The scheme-label rule's refusals, by the fence that spoke. This
            #: rule refuses far more than it publishes and that is its shape,
            #: not its failure: twelve of the fifty-five values that reach a
            #: corroborated reading are traps, and a total would hide which
            #: fence caught them.
            "schemeLabelRefusalsByReason": dict(sorted(tally.scheme_label_refusals.items())),
            #: The slash rule's refusals, by the fence that spoke, counted per
            #: BOX offered. The traps this rule must not read -- the 9/11
            #: Commission Act, a place name, a docket prefix, "7401/et seq" --
            #: are not exceptions to it; they are boxes one of these four
            #: reasons declined, and the reason is which.
            "slashRefusalsByReason": dict(sorted(tally.slash_refusals.items())),
            #: The span-endpoint gate's refusals, by the shape that was asked.
            #: A plain stated end is never asked -- 3,048 rows state one the
            #: oracle's coverage begins after, and they are repealed law the
            #: filer cited on purpose.
            "spanEndpointRefusalsByReason": dict(sorted(tally.span_endpoint_refusals.items())),
            #: The pinned initialism roster's refusals, by the fence that
            #: spoke, and what it wrote on the rows it did not resolve. The
            #: typed and candidate rows are counted here rather than under
            #: ``authorityCorroboratedRowsByRule`` because they carry no
            #: corroboration rule: nothing was corroborated, and saying which
            #: kind of nothing IS the answer for a token that names a Forest
            #: Service handbook.
            "initialismRosterRefusalsByReason": dict(
                sorted(tally.initialism_roster_refusals.items())
            ),
            "initialismRosterNotedRowsByStatus": {
                status: sum(
                    1
                    for r in authorities
                    if r.get("act_initialism_roster")
                    and r["corroboration_rule"] is None
                    and str(r["act_initialism_roster"]).split(" ", 1)[-1].split(" (", 1)[0] == status
                )
                for status in sorted(
                    {entry.status for entries in (_initialism_roster() or {}).values()
                     for entry in entries}
                )
            },
            #: And what it published, by the pinned oracle that spoke. The
            #: operator alone is never the corroboration.
            "schemeLabelCorrectedRowsByWitness": {
                witness: sum(
                    1 for r in authorities if r.get("label_correction_evidence") == witness
                )
                for witness in SCHEME_LABEL_WITNESSES
            },
            #: Per-rule counts. Every corroborated row names the rule that
            #: produced it, so a rule that silently stops firing breaks a pin
            #: instead of just shrinking a total.
            "authorityCorroboratedRowsByRule": {
                rule: sum(1 for r in authorities if r["corroboration_rule"] == rule)
                for rule in CORROBORATION_RULES
            },
            "publicLawCorrectedRows": sum(
                1 for r in authorities if r.get("public_law_corrected") is not None
            ),
            "uscTitleOutOfSeriesRows": sum(1 for r in authorities if r["usc_title_is_possible"] is False),
            #: The section fence, counted four ways because the oracle report
            #: counts it four ways: a defect that is one row across 2,000 RINs
            #: is a different animal from 2,000 rows in one.
            "uscSectionVerdictRows": usc_sections.rows_by_verdict,
            "uscSectionVerdictTexts": usc_sections.texts_by_verdict,
            "uscSectionVerdictPairs": usc_sections.pairs_by_verdict,
            "uscSectionVerdictRins": usc_sections.rins_by_verdict,
            #: An unknown NAMES its coverage hole. Every declared reason is
            #: listed even at zero: a hole that stops being reported is exactly
            #: the thing this column exists to keep visible.
            "uscSectionUnknownRowsByReason": usc_sections.unknown_rows_by_reason,
            #: ``exists``, and the citing edition did not print it. Era
            #: mismatch, never a misread; the verdict itself stays window-wide.
            "uscSectionExistsNotAtEditionRows": usc_sections.exists_not_at_edition_rows,
            #: The two ways a U.S.C. row has no section question: the title the
            #: edition could not cite (C0, which outranks it), and the row that
            #: names no section at all. Counted so the verdict census closes
            #: against the table's own U.S.C. row count.
            "uscSectionTitleImpossibleRows": usc_sections.title_impossible_rows,
            "uscSectionNotStatedRows": usc_sections.not_stated_rows,
            #: Corrections published, per named rule, and the readings refused
            #: because more than one survived, keyed by the surviving rules'
            #: family codes. 5 USC 552(a) is FOIA subsection (a) AND the Privacy
            #: Act at 552a; both are real, so neither is published.
            "uscSectionCorrectedRowsByRule": usc_sections.corrected_rows_by_rule,
            "uscSectionCorrectionRefusalRowsBySurvivors": usc_sections.refusal_rows_by_survivors,
            #: How many of those corrections move the KEY -- corrected identity
            #: not the parsed usc_section. The number a consumer needs before
            #: deciding what to key on, counted per rule because the rules do
            #: not carry the same risk.
            "uscSectionCorrectedIdentityMovedRowsByRule": usc_sections.identity_moved_rows_by_rule,
            #: What a recodification did with the sections the fence above
            #: refuses for title_49_appendix_not_published, and nothing else.
            #: The census CLOSES against that reason's own row count: every
            #: row the oracle refuses for that hole is a row the pinned table
            #: was asked about, and "not-in-table" is one of the answers, not
            #: a shortfall hidden outside the total.
            "uscDispositionVerdictRows": usc_sections.disposition_rows_by_verdict,
            "uscDispositionVerdictPairs": usc_sections.disposition_pairs_by_verdict,
            #: Rows by HOW MANY successors the table named. Everything above
            #: "1" is a set of candidates that only the printed prose
            #: separates, so this is the number that decides what a consumer
            #: may key on -- and the majority of the rows are up there.
            "uscDispositionRowsBySuccessorCount": usc_sections.disposition_rows_by_successor_count,
            #: How much of the corpus asks the table something WIDER or
            #: NARROWER than a bare section. A span row's successors are a
            #: union over usc_disposition_span_members and a pinpoint row's are
            #: one printed row's, so a consumer that read either as a bare
            #: section's answer would read them wrong in opposite directions.
            #: The abbreviated count is the fence beside them, and it is kept
            #: at zero visibly: a span this module EXPANDED out of "1421-31" is
            #: never asked over, only its start section is.
            "uscDispositionSpanRows": usc_sections.disposition_span_rows,
            "uscDispositionSpans": usc_sections.disposition_spans,
            "uscDispositionAbbreviatedSpanRowsNotExpanded": (
                usc_sections.disposition_abbreviated_span_rows
            ),
            "uscDispositionPinpointRows": usc_sections.disposition_pinpoint_rows,
            "uscDispositionPinpointResolvedRows": usc_sections.disposition_pinpoint_resolved_rows,
            #: Rows where no table was read at all, by refusal code, with the
            #: distinct (title, section, appendix) pairs behind them. A refusal
            #: is an answer and is counted like one -- these rows are inside
            #: the title_49_appendix_not_published population and outside
            #: uscDispositionVerdictRows, which is the only place the two
            #: totals differ.
            "uscDispositionRefusalRows": usc_sections.disposition_refusal_rows,
            "uscDispositionRefusalPairs": usc_sections.disposition_refusal_pairs,
            #: The publisher's own answer key, counted the way the campaign
            #: counted it: rows and distinct texts per verdict, and rows per
            #: (authority_type, verdict) because "absent" means one thing for a
            #: U.S.C. section and another for an act name. Coverage is counted
            #: beside them: a move in the verdicts that is really a move in
            #: which rules the notes reach is a different finding, and without
            #: these four numbers the two are indistinguishable.
            "cfrNoteVerdictRows": cfr_notes.rows_by_verdict,
            "cfrNoteVerdictTexts": cfr_notes.texts_by_verdict,
            "cfrNoteVerdictRowsByAuthorityType": cfr_notes.rows_by_type_and_verdict,
            "cfrNoteCoverage": {
                "rows": cfr_notes.covered_rows,
                "rins": cfr_notes.covered_rins,
                "rules": cfr_notes.covered_rules,
                "partsHeld": cfr_notes.parts_held,
                "partsNamedByARule": cfr_notes.parts_named_by_a_rule,
            },
            #: Covered rows this join leaves NULL, by type. The families it does
            #: not judge live here, and so does every "21 U.S.C." with no
            #: section: the census closes against cfrNoteCoverage.rows.
            "cfrNoteUnjudgedRowsByType": cfr_notes.unjudged_rows_by_type,
            #: Rows a non-U.S.C. numbering universe occupies the U.S.C. slot
            #: on, by the name :func:`_write_usc_slot_reading` gave it. Never
            #: a verdict count -- see the column's own schema comment.
            "uscSlotReadingRows": usc_slot_readings,
            #: The builder's own C3 promotion, by outcome
            #: (:data:`USC_C3_PROMOTION_OUTCOMES`): rows published -- exactly
            #: one fused reading survived, bound to this row's own citation --
            #: and rows refused for the four different reasons a refusal here
            #: has. See :func:`_promote_paren_eaten_lettered_suffix`.
            "uscC3PromotionRows": paren_eaten_suffixes,
            #: Placeholder ("unstated") rows the two-witness cross-reference
            #: published a candidate for, rows every candidate was withheld
            #: from, and the CANDIDATES each of the two gates dropped -- the
            #: approval-date gate and the section oracle's refutation, counted
            #: apart because they are different evidence refusing for
            #: different reasons. See :func:`_write_placeholder_candidates`.
            "placeholderCandidateRows": placeholder_candidates,
            #: The corpus's own magnitude fence, and the two verdicts the
            #: grammar computed all along while this table dropped them: an
            #: implausible CFR part (the sibling reference table has flagged the
            #: identical string since it existed) and a Statutes volume that
            #: cannot carry the Public Law printed beside it.
            "uscSectionMagnitudeImplausibleRows": implausible_magnitudes,
            "uscSectionAbbreviatedSpanRows": sum(
                1 for r in authorities if r["usc_section_span_rule"] == USC_SPAN_ABBREVIATED
            ),
            "authorityImplausiblePartRows": sum(
                1 for r in authorities if r["cfr_part_is_plausible"] is False
            ),
            "statVolumeMismatchesPublicLawRows": sum(
                1 for r in authorities if r["statute_volume_matches_public_law"] is False
            ),
            "eoOutOfSeriesRows": sum(1 for r in authorities if r["eo_in_known_series"] is False),
            "plCongressOutOfSeriesRows": sum(1 for r in authorities if r["pl_congress_in_series"] is False),
            "statVolumeOutOfSeriesRows": sum(1 for r in authorities if r["stat_volume_in_series"] is False),
            "frVolumeOutOfSeriesRows": sum(1 for r in authorities if r["fr_volume_in_series"] is False),
            "frPageOutOfSeriesRows": sum(1 for r in authorities if r["fr_page_in_series"] is False),
            "cfrReferenceUnstatedRows": cfr_unstated,
            "authorityPartialRows": partial,
            "timetableRows": len(timetables),
            "timetableRowsWithFrCitation": sum(1 for row in timetables if row["parse_status"] == "ok"),
            "timetableFrCitationFailures": sum(1 for row in timetables if row["parse_status"] == "failed"),
            #: The rows the pinned Federal Register roster answered, and which
            #: named damage operator answered each. Every declared operator is
            #: listed even at zero: page-digit-dropped generates the COMPETING
            #: reading of "89 FR 1022091" and corroborates none of these rows,
            #: and a zero that is printed is a measurement where a missing key
            #: would only be an absence.
            "timetableFrCitationsCorroboratedByRoster": sum(
                1 for row in timetables if row["parse_status"] == "corroborated"
            ),
            "timetableFrCorrectionRowsByOperator": {
                operator: sum(
                    1
                    for row in timetables
                    if (row["fr_correction_evidence"] or "").startswith(f"{operator}-witnessed-by-")
                )
                for operator in FR_CITATION_DAMAGE_OPERATORS
            },
            #: The timetable column's own grammars, each naming a reading or a
            #: refusal. A single "failed" bucket held all of these; counting
            #: them separately is what lets "the publisher stated no page" be
            #: reported instead of absorbed.
            "timetableRowsByCitationScheme": {
                scheme: sum(1 for row in timetables if row["fr_citation_scheme"] == scheme)
                for scheme in sorted(
                    {row["fr_citation_scheme"] for row in timetables if row["fr_citation_scheme"]}
                )
            },
        },
    }
    return UnifiedAgendaParquetReceipt(
        editions=len(pins),
        actions=len(actions),
        cfr_references=len(references),
        legal_authorities=len(authorities),
        timetable_rows=len(timetables),
        source_sha256_by_edition=digests,
        outputs=outputs,
        schema_digests=schema_digests,
        contract=contract,
        producer=_producer_block(),
    )


_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SOURCE_ROOT = _REPO_ROOT / "output/registry-real-data-sources/unified-agenda-editions"
_DEFAULT_OUTPUT_ROOT = _REPO_ROOT / "output/registry-real-data-sources/unified-agenda-parquet"
#: The bulk-built index since 2026-08-23. Both of its tables are read now: the
#: popular-name one supplies the names that make a citation act-relative, and
#: the classification one resolves the act section to a U.S.C. section. Which
#: build is named therefore MATTERS here, where it used to be inert — the
#: per-page artifact holds Table III for 24 laws against this one's 15,189, and
#: the difference is 1,969 resolved rows
#: (``research/evidence/act-index-bulk-table3-2026-08-22.md``).
_DEFAULT_ACT_INDEX = _REPO_ROOT / "output/usc-act-index-2026-08-22"


def resolvable_act_names(act_index_dir: Path) -> frozenset[str]:
    """The OLRC name keys the act resolver can answer, read through the pin.

    A name is resolvable when the Popular Name Tool cites it (table3_key) or
    aliases it (see_also_key). Reading through act_resolution's pinned loader
    means a drifted artifact refuses here rather than silently changing which
    names the builder recovers.
    """

    from refspec.registry.act_resolution import _read_pinned_parquet

    return frozenset(
        row["name_key"]
        for row in _read_pinned_parquet(Path(act_index_dir), "usc-popular-names.parquet")
        if row["table3_key"] is not None or row["see_also_key"] is not None
    )


def receipt_payload(receipt: UnifiedAgendaParquetReceipt) -> dict[str, object]:
    """The receipt.json shape, one spelling, so rebuilds stay byte-comparable."""

    return {
        "actions": receipt.actions,
        "cfrReferences": receipt.cfr_references,
        "contract": receipt.contract,
        "editions": receipt.editions,
        "legalAuthorities": receipt.legal_authorities,
        "outputs": receipt.outputs,
        "producer": receipt.producer,
        "schemaDigests": receipt.schema_digests,
        "sourceSha256ByEdition": receipt.source_sha256_by_edition,
        "timetableRows": receipt.timetable_rows,
    }


def verify_unified_agenda_parquet(output_root: Path) -> list[str]:
    """Check the artifact on disk against its own receipt; name every failure."""

    import hashlib
    import json

    output_root = Path(output_root)
    problems: list[str] = []
    receipt_path = output_root / "receipt.json"
    if not receipt_path.is_file():
        return [f"no receipt at {receipt_path}"]
    recorded = json.loads(receipt_path.read_text(encoding="utf-8"))
    outputs = recorded.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        return [f"receipt at {receipt_path} declares no outputs"]
    for table, expected in sorted(outputs.items()):
        path = output_root / f"{table}.parquet"
        if not path.is_file():
            problems.append(f"missing table file: {path.name}")
            continue
        observed = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if observed != expected:
            problems.append(f"{path.name} drifted: expected {expected}, observed {observed}")
    contract = recorded.get("contract")
    if not isinstance(contract, dict) or contract.get("schemaVersion") != "exploded-v3":
        problems.append("receipt contract does not declare schemaVersion exploded-v3")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Build (default) or verify the Unified Agenda Parquet artifact.

    ``python -m refspec.registry.unified_agenda_parquet`` rebuilds the four
    tables from the pinned editions and writes the receipt beside them.
    ``--verify`` re-hashes the tables on disk against the receipt and builds
    nothing. Both paths authenticate their inputs; neither guesses a path.
    """

    import argparse
    import json

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--source-root", type=Path, default=_DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=_DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--act-index",
        type=Path,
        default=_DEFAULT_ACT_INDEX,
        help="sealed usc-act-index artifact: the resolvable act names AND their classifications",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify the existing artifact against its receipt instead of building",
    )
    args = parser.parse_args(argv)

    if args.verify:
        problems = verify_unified_agenda_parquet(args.output_root)
        for problem in problems:
            print(f"FAIL  {problem}")
        if not problems:
            print(f"PASS  artifact at {args.output_root} matches its receipt")
            drift = describe_producer_drift(args.output_root)
            if drift:
                print(f"NOTE  {drift}")
        return 1 if problems else 0

    # Every oracle is found relative to this file, and every loader answers
    # None to a caller that has none. A BUILD is a caller that thinks it has
    # them: one run 2026-08-22 from an unpacked old tree found neither of the
    # two that existed then, wrote an artifact with no Public Law corrections
    # and no dated series verdicts, and passed --verify. Refuse, rather than
    # write that.
    missing = [
        path
        for path in (
            _PL_ROSTER_CSV,
            _OFR_INDEX_CSV,
            _CFR_AUTHORITY_NOTES_JSONL,
            _FR_DOCUMENT_ROSTER_CSV,
            _INITIALISM_ROSTER_CSV,
        )
        if not path.is_file()
    ]
    missing += [
        path
        for path in (
            _USC_SECTION_ORACLE_DIR,
            _USC_DISPOSITION_TABLES_DIR,
            _USC_SOURCE_CREDIT_DIR,
            args.act_index,
        )
        if not path.is_dir()
    ]
    if missing:
        parser.error(
            "refusing to build without the pinned oracles: "
            + ", ".join(str(path) for path in missing)
        )

    receipt = build_unified_agenda_parquet(
        args.source_root,
        args.output_root,
        act_names=resolvable_act_names(args.act_index),
        act_index_dir=args.act_index,
    )
    payload = receipt_payload(receipt)
    receipt_path = Path(args.output_root) / "receipt.json"
    receipt_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt.contract["declaredClassifications"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
