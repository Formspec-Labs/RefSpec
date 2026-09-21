"""Copied pre-range consumer checks; tests name every deliberate divergence.

Frozen from the working branch HEAD before the CFR range consumer changes.
The grammar remains separately oracle-tested; these preserve consumer decisions.
"""
from __future__ import annotations

from refspec.registry.act_resolution import ActIndex
from refspec.registry.cfr_authority_notes import CfrAuthorityNotes, Citation, normalize_part
from refspec.registry.citation_grammar import parse_cfr_citations
from refspec.registry.term_explanation import TermExplanation, acts_classifying


def old_cfr_citation(cfr_title: object, cfr_part: object) -> Citation | None:
    """``(49, "1")`` -> ``cfr 49:1``. The SECTION under the part is not identity
    here: a note naming "49 CFR 1.97" names part 1, and a rule citing 49 CFR
    1.53 names the same part. Judging the section would call two delegations of
    the same part a mismatch."""

    part = normalize_part(cfr_part)
    if cfr_title is None or part is None:
        return None
    return Citation(family="cfr", identity=f"{int(cfr_title)}:{part}")


def old__held_parts_by_rule(
    references: list[dict[str, object]], notes: CfrAuthorityNotes | None
) -> dict[tuple[str, str], set[tuple[int, str]]]:
    """One rule's held CFR parts, keyed by ``(rin, publication_id)``.

    A rule's ``unified_agenda_cfr_references`` rows restricted to parts the
    pinned authority-note cache HOLDS: a LEGAL AUTHORITY citation is a
    delegation the rule cites, not a part it amends, so only the reference
    table's own part list is read. Shared by the three readers that need the
    same join (:func:`_judge_against_cfr_notes`,
    :func:`_write_placeholder_candidates`, :func:`_promote_two_witness_b8`).
    """

    held: dict[tuple[str, str], set[tuple[int, str]]] = {}
    if notes is None:
        return held
    for reference in references:
        title, part = reference["cfr_title"], normalize_part(reference["cfr_part"])
        if title is None or part is None or not notes.holds(title, part):
            continue
        held.setdefault((reference["rin"], reference["publication_id"]), set()).add((int(title), part))
    return held


def old__explain_cfr_part(text: str, index: ActIndex, notes: CfrAuthorityNotes) -> TermExplanation | None:
    """Pre-range oracle: first citation only, and attribution withheld unless exactly one act classifies it."""

    citations = parse_cfr_citations(text)
    if not citations:
        return None
    first = citations[0]
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
