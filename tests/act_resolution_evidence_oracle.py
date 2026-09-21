"""Frozen pre-evidence-copy of the act resolver and the source-credit lookup.

Copied from 31ca84c2^:src/refspec/registry/act_resolution.py -- the resolver as
it stood before production began retaining competing source readings -- and
kept test-only, since importing the thing under comparison would make the
comparison circular. Live types (ActResolution, ActIndex, verdicts) are
imported, so only the two functions are pinned.
"""
from __future__ import annotations

from refspec.registry.act_resolution import (
    _PUBLIC_LAW_KEY,
    _SILENT,
    ActIndex,
    ActResolution,
    SourceCreditAnswer,
    SourceCreditIndex,
    _Verdict,
    act_name_absence_reason,
    canonical_usc_iri,
    resolve_act_name,
)
from refspec.registry.citation_grammar import ActRelativeCitation


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

def lookup(self, public_law: str | None, division: str | None, act_section: str) -> SourceCreditAnswer:
        """This source's answer, with "nothing to look under" kept distinct.

        The division is part of the key, not a filter applied afterwards, so a
        citation with no division has no key here at all; every credit row in
        the pinned index names a division, so nothing is lost to that.
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
