"""What became of a U.S.C. section a positive-law recodification took away.

:mod:`refspec.registry.usc_section_oracle` answers ``unknown`` — never
``absent`` — where its own coverage is structurally missing, and its largest
such hole is ``title_49_appendix_not_published``: **no OLRC annual archive year
holds a** ``usc49a.htm``, so the pre-1996 Title 49 Appendix numbering (the
Federal Aviation Act, the Federal Transit Act, the ICC Act as they stood before
Pub. L. 103-272) is invisible to every source that oracle reads. 2,548 of the
2,551 ``unknown`` rows in the pinned Unified Agenda build carry that one
reason.

The reason is honest and the hole is real, but it is not the end of the
question. The human review of 2026-08-23
(``research/evidence/sample-review-2026-08-23/review.md`` § F) read ten of
those rows against the publisher's own pages and settled **all ten** from one
closed, authoritative, public document: the "TABLE SHOWING DISPOSITION OF
FORMER SECTIONS OF TITLE 49", printed in the front matter of the 1994 edition
of the positive-law title. Nine resolve to a current section; one — ``49 U.S.C.
1604(h)``, printed ``1604, 1604a … Rep.`` — resolves to *repealed, with no
successor*, which is a different fact and gets its own verdict here.

Pub. L. 103-272, § 6(b) is what makes the table more than a finding aid: a
reference to a law replaced by that Act is **deemed** to refer to the
corresponding provision enacted by it.

What this module reads
----------------------
``research/evidence/usc-disposition-tables-2026-08-23`` — the govinfo volume
pinned by sha256 and byte length, the committed extractor, and the derived
Parquet, all described in that directory's README. The Parquet is 3,102 rows,
one per **(former section token x successor)**, over 1,852 printed entries and
909 former sections; every row carries the printed former field and the printed
value verbatim beside the parsed address, because the prose that says *which
words* of a former section moved (``(1st sentence)``, ``(related to
standards)``) is not an address and is not parsed into one.

Only that table is read. The digest is restated here rather than read from the
README beside it, for the reason :mod:`~refspec.registry.usc_section_oracle`
gives: reading the pin *from* the paperwork in the directory would
authenticate a swapped directory against its own paperwork.

The rules
---------
**Return every successor, never one.** A former section is not a unit the
recodification preserved. ``1432`` alone becomes four sections — 44706 for
(b) and (c), 44914 for (d), and 44701 or 44702 for (a) depending on which
words of (a) are meant — and the table says so in four printed rows whose
prose is the only thing that separates them. Picking one would be a guess
dressed as a lookup; :attr:`Disposition.successors` holds all of them and
:attr:`Disposition.rows` holds the printed text that distinguishes them, for a
consumer or a human to read. That is the same doctrine
:meth:`~refspec.registry.usc_section_oracle.UscSectionOracle.corrected_section`
follows when two readings survive.

**A subsection narrows; it never accuses.** ``1604(h)`` is answered by the row
``1604, 1604a → Rep.``, which names no subsection and therefore speaks for the
whole section. Where the table *does* resolve the subsection — ``1432(d)`` —
only the rows that match it are returned and
:attr:`Disposition.subsection_resolved` is ``True``. Where a section is in the
table but that subsection is not, the section's own rows come back with
``subsection_resolved`` ``False`` rather than ``not-in-table``: the table
plainly knows the section, and answering "not in the table" because a pinpoint
missed would be the worse error.

**A span is asked member by member, and the answer says so.** A citation that
states a range — ``49 U.S.C. 1421 to 1431`` — names eleven former sections, and
this table is keyed by one. Asking it about ``1421`` alone and publishing that
as the range's answer would drop ten of the eleven silently, which is what the
visual review of 2026-08-23 (§ J, RIN 2120-AE42) found published. So
:meth:`UscDispositionTables.disposition` takes a ``section_end``, asks the
table about **every former section it lists inside the span**, and returns the
union of their successors with :attr:`Disposition.members` holding each
member's own answer beside it. Nothing is flattened into a single identity: the
union is candidates, exactly as one section's several successors are.

The members are the sections the **printed table lists** between the endpoints,
found by order key, and never a count from low to high. Counting is wrong in
both directions at once, and ``1 to 85`` measures it: 17 of the integers 1-85
are not in the volume at all (24, 28-40, 68-70), and 16 of the 84 members it
does print are LETTERED (``1a``, ``5a``, ``15b``, ``26c``) and unreachable by
any integer walk.
:attr:`~refspec.registry.citation_grammar.AuthorityCitation.usc_section_span_rule`
already carries the warning that expanding a span is a claim about every
section between its endpoints. Here the claim is only ever about sections the
1994 volume itself prints, so the enumeration cannot invent one.

**Repealed is not the same as pointed elsewhere.** ``Rep.`` and ``Elim.`` name
no successor and mean the provision is gone; ``(See § 2 of Pub. L. 97-449.)``
names no successor either, but means *another act* made the transfer.
``1655(a)(4)`` is the specimen. Publishing that as ``repealed-no-successor``
would state something the table denies, so it has its own verdict.

**An absence from the table is only as wide as the table.** The Title 49 table
lists the former sections that *existed to be restated in 1994*; a section
repealed before the 1978 or 1983 codifications was never in it. So
``not-in-table`` carries :data:`NOT_IN_TABLE_CAVEATS` on every verdict, the way
``absent`` carries
:data:`~refspec.registry.usc_section_oracle.ABSENT_CAVEATS`.

**And a title with no pinned table is not a title with nothing to say.** The
same shape of table exists for every other positive-law recodification — 31
(1982), 41 (2011), 46 (1983-2006), 51 (2010), 54 (2014), 34 (2017), 10 ch. 1201
— and § E of the same review names two of them as live misses (``31 USC 483a``
→ 9701; ``10 U.S.C. 593`` → 12203). Only Title 49 is pinned today, so a
question about title 31 gets ``no-table-for-title`` and never ``not-in-table``:
a consumer that read the second as "no recodification" would invert the answer.
:data:`RECODIFICATIONS_NOT_PINNED` names what is missing, and adding one is
adding a pinned directory and a row in :data:`RECODIFICATIONS` — nothing about
Title 49 is special-cased in the interface.

What this module is NOT
-----------------------
It does not decide whether a citation means the former section or a current
one. ``49 U.S.C. 106`` is a live section of the new title and ``49 App. 106``
is not a question anyone is asking. The gate belongs to the caller, and for the
2,548 rows this was built for the gate is already exact: the oracle reaches
``title_49_appendix_not_published`` only for a token it found in **no** edition
1994-2026, so by construction the citation cannot mean a current section.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

__all__ = [
    "NOT_IN_TABLE_CAVEATS",
    "RECODIFICATIONS",
    "RECODIFICATIONS_NOT_PINNED",
    "STATUSES",
    "USC_DISPOSITION_TABLES_ARTIFACT",
    "VERDICTS",
    "Disposition",
    "DispositionRow",
    "Recodification",
    "Successor",
    "UscDispositionTables",
    "normalize_section",
    "normalize_subsection",
]

#: The sealed artifact, relative to the repository root.
USC_DISPOSITION_TABLES_ARTIFACT = "research/evidence/usc-disposition-tables-2026-08-23"


@dataclass(frozen=True)
class Recodification:
    """One positive-law recodification, and the printed table that maps it.

    The interface is per-recodification on purpose: a table is a document with
    a date, an enacting law, and a deeming provision, and two of them can
    disagree about the same former title (title 46 was recodified in pieces
    from 1983 to 2006). Adding one is adding a member here and a pinned file.
    """

    #: Stable name, used in :attr:`Disposition.recodification`.
    name: str
    former_title: int
    #: The derived table inside the artifact, and its sha256.
    table: str
    digest: str
    #: The act that did the recodification, and the provision that deems an old
    #: citation to refer to its successor.
    enacted_by: str
    deeming_provision: str
    #: The printed volume the table was cut from, pinned in the artifact README
    #: and re-checked by the extractor there. Stated here so the chain from a
    #: verdict back to a page is in the code, not only in the paperwork.
    source_url: str
    source_digest: str
    source_bytes: int


RECODIFICATIONS = (
    Recodification(
        name="title-49-1994",
        former_title=49,
        table="usc-1994-title49-disposition.parquet",
        digest="sha256:8403212c0193b3361accf7ff4be238420634beb5aa5740d78b9960fef5b2aedd",
        enacted_by="Pub. L. 103-272, July 5, 1994, 108 Stat. 745",
        deeming_provision="Pub. L. 103-272, § 6(b)",
        source_url="https://www.govinfo.gov/content/pkg/USCODE-1994-title49/pdf/USCODE-1994-title49.pdf",
        source_digest="sha256:66f004679e27e0d16356e14b79cb3b4f7ebf63d91307435fa8f53c95bcc2848d",
        source_bytes=5165242,
    ),
)

#: The recodifications this module does not read yet, so that
#: ``no-table-for-title`` has somewhere to point and the gap is a list rather
#: than a silence. Each is a printed disposition table in the front matter of
#: the enacting edition, reachable the same way Title 49's was.
RECODIFICATIONS_NOT_PINNED: Mapping[int, str] = {
    10: "Pub. L. 103-337 (1994), ch. 1201 — reserve component renumbering; the review's § H row 8 (593 → 12203)",
    31: "Pub. L. 97-258 (1982) — Money and Finance; the review's § E row 7 (483a → 9701)",
    34: "Pub. L. 115-31 (2017) — Crime Control and Law Enforcement",
    41: "Pub. L. 111-350 (2011) — Public Contracts; the review's § E row 10 neighbours",
    46: "Pub. L. 98-89 (1983) through Pub. L. 109-304 (2006) — Shipping, in pieces",
    51: "Pub. L. 111-314 (2010) — National and Commercial Space Programs",
    54: "Pub. L. 113-287 (2014) — National Park Service and Related Programs",
}

#: What a verdict can be. The first four answer the question; the last says the
#: question was not asked of anything.
VERDICTS = (
    #: At least one row names a successor. ALL of them are returned.
    "exists-as-recodified",
    #: Every matching row is ``Rep.`` or ``Elim.`` — the provision is gone.
    "repealed-no-successor",
    #: Every matching row names no successor, and at least one points at
    #: another instrument instead (``(See § 2 of Pub. L. 97-449.)``).
    "stated-without-successor",
    #: The pinned table for that title lists no such former section.
    "not-in-table",
    #: No table is pinned for that title. NEVER read as ``not-in-table``.
    "no-table-for-title",
)

#: The printed value's own vocabulary, restated from the extractor.
STATUSES = ("restated", "restated-as-note", "repealed", "eliminated", "see-reference")
#: The statuses that name a successor, and so make a verdict of
#: ``exists-as-recodified``.
_WITH_SUCCESSOR = frozenset({"restated", "restated-as-note"})
#: The statuses that say the provision is gone rather than moved.
_GONE = frozenset({"repealed", "eliminated"})

#: What a ``not-in-table`` verdict does NOT exclude, attached to every one of
#: them. The table lists the former sections that existed to be restated when
#: the recodification was enacted; one repealed before that was never in it.
NOT_IN_TABLE_CAVEATS = ("repealed_before_the_recodification_not_listed",)

#: Restated from :mod:`refspec.registry.citation_grammar`, the way
#: :mod:`refspec.registry.usc_section_oracle` restates it, rather than imported:
#: the section oracle will consult this module in the next cycle, and an import
#: in this direction is the half of a cycle that is cheap to avoid.
#: ``test_the_dash_table_is_the_grammars_verbatim`` holds the copy true.
_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—―−\x96\x97", "-"))

_GROUP = re.compile(r"\(([0-9A-Za-z]{1,4})\)")

#: A former section's sort key, restated from ``usc_section_oracle._section_key``
#: for the same reason the dash table is restated, and the same reason
#: ``cfr_authority_notes._section_order`` restates it: it is private there, and
#: this module may not import in that direction.
#: ``test_the_span_order_is_the_oracles_over_every_former_section`` runs both
#: over all 909 former sections the pinned table lists and holds the copy true.
#: Comparing numeric prefixes alone would order ``1421a`` before ``1421``.
_LEADING_DIGITS = re.compile(r"^(\d+)(.*)$")


def _section_order(section: str) -> tuple[int, str] | None:
    match = _LEADING_DIGITS.match(section)
    return (int(match.group(1)), match.group(2)) if match else None


def normalize_section(value: object) -> str:
    """Lowercase, trim and collapse every dash spelling. The join key."""

    return str(value or "").strip().lower().translate(_DASHES)


def normalize_subsection(value: object) -> tuple[str, ...]:
    """A subsection query as a path of labels: ``"d"`` and ``"(d)"`` -> ``("d",)``.

    ``"(a)(1)"`` -> ``("a", "1")``. Case is folded because a bare ``"d"`` from a
    citation cannot express whether the print meant ``(d)`` or ``(D)``, and no
    row in the pinned table opens its path with an uppercase label, so nothing
    is conflated by folding.
    """

    text = str(value or "").strip().translate(_DASHES)
    if not text:
        return ()
    groups = _GROUP.findall(text)
    if groups and "".join(f"({g})" for g in groups) == text.replace(" ", ""):
        return tuple(g.lower() for g in groups)
    return (text.strip("()").lower(),)


@dataclass(frozen=True)
class Successor:
    """One section a printed value names as the home of a former provision."""

    title: int
    section: str
    #: Set only where the printed value is a pinpoint: ``308(e)``.
    subsection: str | None
    status: str

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"undeclared status: {self.status!r}")
        if self.status not in _WITH_SUCCESSOR:
            raise ValueError(f"a successor cannot carry the status {self.status!r}")


@dataclass(frozen=True)
class DispositionRow:
    """One printed row: the parsed address, the successor, and the print itself."""

    former_section: str
    former_subsection: str | None
    #: ``note`` / ``notes`` when the entry disposes of the section's notes.
    former_note: str | None
    successor: Successor | None
    status: str
    #: **The printed former field and value, verbatim.** The prose that says
    #: which words of a former section moved lives here and nowhere else.
    former_text: str
    new_text: str
    page: int
    column: str

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"undeclared status: {self.status!r}")
        if (self.successor is not None) != (self.status in _WITH_SUCCESSOR):
            raise ValueError("a row names a successor exactly when its status says it has one")


@dataclass(frozen=True)
class Disposition:
    """What a pinned table says about one former ``(title, section[, subsection])``."""

    former_title: int
    former_section: str
    #: The subsection asked about, as a path of labels; empty when none was.
    subsection: tuple[str, ...]
    verdict: str
    #: Which recodification answered; ``None`` for ``no-table-for-title``.
    recodification: str | None
    #: **Every** successor the matching rows name, de-duplicated, in print
    #: order. Never one of several: see the module docstring. Over a span this
    #: is the UNION over :attr:`members`, in member order — still candidates,
    #: and still never an identity.
    successors: tuple[Successor, ...]
    #: The printed rows behind them, with their text.
    rows: tuple[DispositionRow, ...]
    #: ``None`` when no subsection was asked about; ``True`` when the table
    #: resolved it; ``False`` when the section is in the table but that
    #: subsection is not, and the section's own rows are what came back.
    subsection_resolved: bool | None
    #: The far end of the span asked about, as the citation stated it; ``None``
    #: where the question was about one former section.
    former_section_end: str | None = None
    #: One answer per former section the pinned table lists inside the span,
    #: in print order — the per-member breakdown a union would otherwise hide.
    #: Empty where no span was asked about, and where a span was asked about
    #: and the table lists no former section inside it.
    members: tuple[Disposition, ...] = ()
    caveats: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"undeclared verdict: {self.verdict!r}")
        if self.verdict == "not-in-table" and self.caveats != NOT_IN_TABLE_CAVEATS:
            raise ValueError("an absence from a table is only as wide as the table, and must say so")
        if self.verdict != "not-in-table" and self.caveats:
            raise ValueError("only an absence from the table carries the table's caveat")
        if (self.verdict == "exists-as-recodified") != bool(self.successors):
            raise ValueError("a recodified verdict names its successors, and no other verdict names any")
        if self.verdict in ("not-in-table", "no-table-for-title") and self.rows:
            raise ValueError("a verdict that found no row cannot carry rows")
        if self.members and self.former_section_end is None:
            raise ValueError("only a span has members")
        if any(member.members or member.former_section_end is not None for member in self.members):
            raise ValueError("a span's member is one former section, and cannot itself be a span")
        if self.members and self.successors != tuple(
            dict.fromkeys(one for member in self.members for one in member.successors)
        ):
            raise ValueError("a span's successors are the union over its members, in member order")

    @property
    def answered(self) -> bool:
        """Whether the table said anything at all about this section."""

        return self.verdict not in ("not-in-table", "no-table-for-title")

    @property
    def covers(self) -> tuple[str, ...]:
        """The former sections this verdict speaks for, in print order.

        One section where one was asked about, and every member the table
        listed inside a span. A consumer reading
        :attr:`successors` off a span row needs this beside it, or the union
        reads as one section's answer.
        """

        return tuple(member.former_section for member in self.members) or (self.former_section,)


def _verify_pinned_parquet(directory: Path, name: str, expected: str) -> Path:
    """Hash one pinned table, refusing loudly on drift. Returns its path."""

    path = directory / name
    digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    if digest != expected:
        raise ValueError(f"pinned disposition table drifted: {name}; expected={expected}, observed={digest}")
    return path


@dataclass(frozen=True)
class UscDispositionTables:
    """The pinned recodification tables, loaded from one verified directory."""

    directory: Path

    @classmethod
    def from_directory(cls, directory: Path | str) -> UscDispositionTables:
        """Bind to a sealed artifact directory, verifying every digest first."""

        tables = cls(directory=Path(directory))
        tables.verify()
        return tables

    @classmethod
    def from_repository(cls, root: Path | str) -> UscDispositionTables:
        """Bind to the copy this repository carries."""

        return cls.from_directory(Path(root) / USC_DISPOSITION_TABLES_ARTIFACT)

    def verify(self) -> None:
        """Hash every pinned table, whatever this caller goes on to ask.

        One table today, so this costs 0.1 ms; it is written over
        :data:`RECODIFICATIONS` rather than over the one file because the next
        table must be verified by existing code, not by a reader who
        remembered to add it. Same reason
        :meth:`~refspec.registry.usc_section_oracle.UscSectionOracle.verify`
        hashes all six of its tables rather than the one a caller reads.
        """

        for recodification in RECODIFICATIONS:
            _verify_pinned_parquet(self.directory, recodification.table, recodification.digest)

    @cached_property
    def _by_title(self) -> Mapping[int, Recodification]:
        return {recodification.former_title: recodification for recodification in RECODIFICATIONS}

    @cached_property
    def _rows(self) -> Mapping[int, Mapping[str, tuple[DispositionRow, ...]]]:
        """``former title -> former section -> its printed rows``, in print order."""

        import pyarrow.parquet as pq

        out: dict[int, dict[str, list[DispositionRow]]] = {}
        for recodification in RECODIFICATIONS:
            path = _verify_pinned_parquet(self.directory, recodification.table, recodification.digest)
            table = pq.read_table(path)
            columns = {name: table.column(name).to_pylist() for name in table.schema.names}
            sections: dict[str, list[DispositionRow]] = {}
            for values in zip(*columns.values(), strict=True):
                row = dict(zip(columns, values, strict=True))
                if row["former_title"] != recodification.former_title:
                    raise ValueError(f"{recodification.table} states former title {row['former_title']}")
                successor = (
                    Successor(
                        title=row["new_title"],
                        section=normalize_section(row["new_section"]),
                        subsection=row["new_subsection"],
                        status=row["status"],
                    )
                    if row["status"] in _WITH_SUCCESSOR
                    else None
                )
                section = normalize_section(row["former_section"])
                sections.setdefault(section, []).append(
                    DispositionRow(
                        former_section=section,
                        former_subsection=row["former_subsection"],
                        former_note=row["former_note"],
                        successor=successor,
                        status=row["status"],
                        former_text=row["former_text"],
                        new_text=row["new_text"],
                        page=row["page"],
                        column=row["column"],
                    )
                )
            out[recodification.former_title] = {key: tuple(value) for key, value in sections.items()}
        return out

    def former_sections(self, former_title: int) -> frozenset[str]:
        """Every former section the pinned table for that title lists."""

        return frozenset(self._rows.get(former_title, {}))

    def sections_in_span(self, former_title: int, former_section: str, section_end: object) -> tuple[str, ...]:
        """Every former section the pinned table LISTS inside a stated span.

        In print order, endpoints included. Empty where no table is pinned,
        where either endpoint has no order key, where the span runs backwards,
        or where the table lists nothing between them.

        Membership, never a count: the members are the table's own keys whose
        order key falls inside the span, the way
        :meth:`~refspec.registry.cfr_authority_notes.AuthorityNote._span_covers`
        tests a note's printed range. For ``1 to 85`` a count would claim 17
        integers the volume never prints and miss 16 lettered sections it
        does; see the module docstring.
        """

        low = _section_order(normalize_section(former_section))
        high = _section_order(normalize_section(section_end))
        if low is None or high is None or high < low:
            return ()
        return tuple(
            section
            for section in self._rows.get(former_title, {})
            if (key := _section_order(section)) is not None and low <= key <= high
        )

    def disposition(
        self,
        former_title: int,
        former_section: str,
        subsection: object = None,
        *,
        section_end: object = None,
    ) -> Disposition:
        """What became of one former section, of one subsection, or of a span.

        Returns every successor the table names — see the module docstring on
        why picking one would be a guess — with the printed rows beside them.

        ``section_end`` asks the same question of a stated range. Every member
        :meth:`sections_in_span` finds is asked on its own and kept in
        :attr:`Disposition.members`; the successors are their union in member
        order, and the verdict is read off the union of their printed rows
        exactly as one section's verdict is read off its own. A ``subsection``
        beside a span narrows the START member and no other: a pinpoint is
        written on the section it follows, and carrying it to the other members
        would apply one citation's ``(b)(2)`` to ten sections that never saw it.
        """

        section = normalize_section(former_section)
        wanted = normalize_subsection(subsection)
        end = normalize_section(section_end) or None
        recodification = self._by_title.get(former_title)
        if recodification is None:
            return Disposition(
                former_title=former_title,
                former_section=section,
                former_section_end=end,
                subsection=wanted,
                verdict="no-table-for-title",
                recodification=None,
                successors=(),
                rows=(),
                subsection_resolved=None,
            )

        if end is not None:
            # Every member comes from the table's own keys, so each one's own
            # answer is an answer -- there is no not-in-table member to filter.
            members = tuple(
                self.disposition(former_title, member, subsection if member == section else None)
                for member in self.sections_in_span(former_title, section, end)
            )
            if not members:
                return Disposition(
                    former_title=former_title,
                    former_section=section,
                    former_section_end=end,
                    subsection=wanted,
                    verdict="not-in-table",
                    recodification=recodification.name,
                    successors=(),
                    rows=(),
                    subsection_resolved=None,
                    caveats=NOT_IN_TABLE_CAVEATS,
                )
            matched = tuple(row for member in members for row in member.rows)
            start = next((member for member in members if member.former_section == section), None)
            return Disposition(
                former_title=former_title,
                former_section=section,
                former_section_end=end,
                subsection=wanted,
                verdict=_verdict_over(matched),
                recodification=recodification.name,
                successors=tuple(dict.fromkeys(one for member in members for one in member.successors)),
                rows=matched,
                subsection_resolved=None if start is None else start.subsection_resolved,
                members=members,
            )

        rows = self._rows[former_title].get(section, ())
        if not rows:
            return Disposition(
                former_title=former_title,
                former_section=section,
                subsection=wanted,
                verdict="not-in-table",
                recodification=recodification.name,
                successors=(),
                rows=(),
                subsection_resolved=None,
                caveats=NOT_IN_TABLE_CAVEATS,
            )

        resolved: bool | None = None
        matched = rows
        if wanted:
            narrowed = tuple(row for row in rows if _row_covers(row, wanted))
            resolved = bool(narrowed)
            matched = narrowed or rows

        return Disposition(
            former_title=former_title,
            former_section=section,
            subsection=wanted,
            verdict=_verdict_over(matched),
            recodification=recodification.name,
            successors=tuple({row.successor: None for row in matched if row.successor is not None}),
            rows=matched,
            subsection_resolved=resolved,
        )


def _verdict_over(matched: tuple[DispositionRow, ...]) -> str:
    """The verdict a set of printed rows carries. One spelling, two callers."""

    if any(row.successor is not None for row in matched):
        return "exists-as-recodified"
    if all(row.status in _GONE for row in matched):
        return "repealed-no-successor"
    return "stated-without-successor"


def _row_covers(row: DispositionRow, wanted: tuple[str, ...]) -> bool:
    """Whether a printed row speaks for the queried subsection.

    A row naming no subsection — the entry names the whole section — speaks for
    every subsection of it, which is what answers ``1604(h)`` from the row
    ``1604, 1604a → Rep.`` Otherwise the two paths match when one is a prefix of
    the other: a query for ``(a)`` takes ``1602(a)(2)(A)``, and a query for
    ``(a)(2)(A)`` takes the row printed ``1602(a)``. A path kept whole because
    it spans levels — ``(e)(5)-(7)(A)`` — matches on its first label only; the
    span's members are not enumerable without inventing them, and the printed
    text says so.

    A **note** row is the exception to the whole-section rule: ``1374 note →
    41706`` and ``1421 notes → 44716, 44717, 44722`` dispose of the notes under
    a section, not of any subsection of it, so they answer a question about the
    section and not one about ``1374(c)``. Without that, the review's cleanest
    row — ``1374(c)`` → 41705, one successor — would come back with two.
    """

    if row.former_note is not None:
        return False
    printed = row.former_subsection
    if printed is None:
        return True
    labels = tuple(g.lower() for g in _GROUP.findall(printed.split("-")[0]))
    if not labels:
        return False
    if "-" in printed:
        return wanted[0] == labels[0]
    return labels[: len(wanted)] == wanted[: len(labels)]
