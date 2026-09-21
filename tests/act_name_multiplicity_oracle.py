"""Frozen name loader and resolver before preserving multiple source identities.

Only the replaced checks are copied. Unchanged pin readers, source verdict
helpers and shared output types remain native; result comparison excludes new fields.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from refspec.registry.act_resolution import (
    _PAGE_RANGE_OPEN_END,
    _PUBLIC_LAW_KEY,
    _YEAR_SUFFIX,
    ActResolution,
    Classification,
    SourceCreditAnswer,
    SourceCreditIndex,
    _artifacts_stating,
    _read_pinned_parquet,
    _resolve_through_table3,
    _Verdict,
    _verdict_from_credits,
    act_name_absence_reason,
    normalize_popular_name,
    resolve_act_name,
)
from refspec.registry.citation_grammar import ActRelativeCitation


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
        truncates the division. Validated against the Code's own source credits:
        936 of 1,350 testable acts had USLM pages outside the act-derived range,
        and none outside the division-derived one. The end is the next
        division's start, *strictly* later, so two divisions that begin on one
        page (5 laws in the pinned index) do not truncate each other.
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
        if not (_artifacts_stating(directory / "usc-act-sections.parquet")
                & _artifacts_stating(directory / "quarantine.parquet")):
            raise ValueError("classifications and quarantine must belong to the same act artifact")
        narrowed = frozenset(
            (row["table3_key"], row["raw_value"].partition(" -> ")[0])
            for row in _read_pinned_parquet(directory, "quarantine.parquet")
            if row["reason"] == "statutes_at_large_page_span_narrowed"
        )
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
            narrowed_page_sections=narrowed,
        )


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
