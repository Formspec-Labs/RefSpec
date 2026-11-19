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
Each pinned recodification names its own sealed artifact directory under
``research/evidence/`` (:data:`USC_DISPOSITION_TABLES_ARTIFACTS`):

* ``research/evidence/usc-disposition-tables-2026-08-23`` — Title 49 (Pub. L.
  103-272, 1994), 3,102 rows over 1,852 printed entries and 909 former sections;
* ``research/evidence/usc-disposition-tables-2026-11-18`` — Title 31 (Pub. L.
  97-258, 1982, as supplemented by Pub. L. 97-452, 1983; 1,563 rows over 965
  printed entries and 1,158 former sections) and Title 46 / Title 46 Appendix
  (Pub. L. 98-89 through Pub. L. 109-304, 1983–2006; 2,169 rows over 1,344
  printed entries and 1,299 former sections).

Every row is one **(former section token x successor)** carrying the printed
former field and the printed value verbatim beside the parsed address, because
the prose that says *which words* of a former section moved (``(1st sentence)``,
``(related to standards)``) is not an address and is not parsed into one.

Only those pinned tables are read. Every digest is restated here rather than
read from the README beside it, for the reason
:mod:`~refspec.registry.usc_section_oracle` gives: reading the pin *from* the
paperwork in the directory would authenticate a swapped directory against its
own paperwork.

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

**Repealed, eliminated, and pointed elsewhere are three different facts.**
``Rep.`` means the provision was legally repealed (``repealed-no-successor``).
``Elim.`` is an editorial omission from the title — the underlying statutory
provision may remain in force or codified elsewhere (for example, former
``46 App. § 111`` prints ``Elim.`` while its substance remains at
``19 U.S.C. § 288``) — so it gets its own verdict (``eliminated-no-successor``)
and is never published as a repeal. ``(See § 2 of Pub. L. 97-449.)`` names no
successor either, but means *another act* made the transfer (``1655(a)(4)`` is
the specimen), so it — and any span mixing non-successor statuses such as
``Rep.`` beside ``Elim.`` — answers ``stated-without-successor``.

**An absence from the table is only as wide as the table.** The Title 49 table
lists the former sections that *existed to be restated in 1994*; a section
repealed before the 1978 or 1983 codifications was never in it. So
``not-in-table`` carries :data:`NOT_IN_TABLE_CAVEATS` on every verdict, the way
``absent`` carries
:data:`~refspec.registry.usc_section_oracle.ABSENT_CAVEATS`.

**And a title with no pinned table is not a title with nothing to say.** The
same shape of table exists for other positive-law recodifications — 10 ch. 1201
(1994), 34 (2017), 41 (2011), 51 (2010), 54 (2014) — and § H of the review
names ``10 U.S.C. 593`` → 12203. Titles 31, 46, and 49 are pinned today; a
question about an unpinned title gets ``no-table-for-title`` and never
``not-in-table``: a consumer that read the second as "no recodification" would
invert the answer. :data:`RECODIFICATIONS_NOT_PINNED` names what is still
missing, and adding one is adding a pinned directory and a row in
:data:`RECODIFICATIONS` — nothing about any title is special-cased in the
interface.

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
    "USC_DISPOSITION_TABLES_ARTIFACTS",
    "VERDICTS",
    "Disposition",
    "DispositionRow",
    "Recodification",
    "Successor",
    "UscDispositionTables",
    "normalize_section",
    "normalize_subsection",
]

#: The initial sealed artifact directory (Title 49), relative to the repository root.
USC_DISPOSITION_TABLES_ARTIFACT = "research/evidence/usc-disposition-tables-2026-08-23"
#: The 2026-11-18 sealed artifact directory (Title 31 and Title 46 / 46 App.).
_USC_DISPOSITION_TABLES_2026_11_18 = "research/evidence/usc-disposition-tables-2026-11-18"
#: The 2026-11-18 complete artifact directory (Titles 10 ROPMA, 34, 41, 51, 54 & Title 49 positive-law).
_USC_DISPOSITION_TABLES_2026_11_18_COMPLETE = "research/evidence/usc-disposition-tables-2026-11-18-complete"
#: Every sealed artifact directory read by :meth:`UscDispositionTables.from_repository`.
USC_DISPOSITION_TABLES_ARTIFACTS: tuple[str, ...] = (
    USC_DISPOSITION_TABLES_ARTIFACT,
    _USC_DISPOSITION_TABLES_2026_11_18,
    _USC_DISPOSITION_TABLES_2026_11_18_COMPLETE,
)


@dataclass(frozen=True)
class Recodification:
    """One positive-law recodification, and the printed table that maps it.

    The interface is per-recodification on purpose: a table is a document with
    a date, an enacting law, and a deeming provision, and two of them can
    cover the same former title (Title 42 provisions moved to Title 51 in 2010
    and to Title 34 in 2017; Title 49's 1994 Act restated former Title 49 / 49 App.
    and also renumbered pre-1994 positive-law Title 49 sections in place).
    Adding one is adding a member here and a pinned file.
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
    #: Sealed artifact directory containing :attr:`table`, relative to repo root.
    artifact: str = USC_DISPOSITION_TABLES_ARTIFACT
    #: Date the printed source volume was fetched (ISO ``YYYY-MM-DD``).
    source_fetched: str = "2026-08-23"
    #: RefSpec-owned relative path where the raw source PDF lives (or is
    #: materialized by ``verify_registry_audit.py``). When ``None``, defaults to
    #: ``<artifact>/<basename(source_url)>``.
    source_local_path: str | None = None
    #: All former titles whose sections appear in :attr:`table` when a table
    #: consolidates multiple source titles (e.g. Title 51 from Titles 15 and 42;
    #: Title 34 from Titles 18, 28, and 42). Defaults to ``(former_title,)``.
    former_titles: tuple[int, ...] = ()
    #: Destination U.S.C. title enacted or editorially populated by this table;
    #: defaults to ``former_title`` when ``None``.
    enacted_title: int | None = None
    #: Whether this table covers explicit ``<title> U.S.C. App.`` lookups.
    #: Only Appendix-bearing recodifications (Title 46 / 46 App., Title 49 / 49 App.,
    #: and Title 49's disjoint positive-law companion resolving audited mislabelled
    #: ``49 USC app 3102`` filings) set this ``True``; main-body recodifications
    #: (Titles 10, 31, 34, 41, 51, 54) refuse explicit ``appendix=True`` queries.
    covers_appendix: bool = False

    @property
    def effective_former_titles(self) -> tuple[int, ...]:
        """Every former U.S.C. title this table is authorised to carry rows for."""

        return self.former_titles or (self.former_title,)


RECODIFICATIONS = (
    Recodification(
        name="title-10-1994",
        former_title=10,
        table="usc-1996-title10-ropma-disposition.parquet",
        digest="sha256:5a08734b3c8ea948340203e0e3c67a256a6a62c95ece863a1328a662691eace6",
        enacted_by=(
            "Pub. L. 103-337, div. A, title XVI, Oct. 5, 1994, 108 Stat. 2924; "
            "Pub. L. 104-106, div. A, title XV, § 1501(c)(26), Feb. 10, 1996, 110 Stat. 499"
        ),
        deeming_provision="Pub. L. 103-337, § 1665(a)",
        source_url="https://www.govinfo.gov/content/pkg/USCODE-1996-title10/pdf/USCODE-1996-title10.pdf",
        source_digest="sha256:d1877b5aa58f17062263fed5a04da62f3ad885b4b01a0da7f0e41d0da15e0010",
        source_bytes=8_971_147,
        artifact=_USC_DISPOSITION_TABLES_2026_11_18_COMPLETE,
        source_fetched="2026-11-18",
        source_local_path="output/registry-real-data-sources/USCODE-1996-title10.pdf",
        enacted_title=10,
    ),
    Recodification(
        name="title-31-1982",
        former_title=31,
        table="usc-1994-title31-disposition.parquet",
        digest="sha256:febacca0f59193fc4524ce780d29ba5440d8ee47f8041f133fda161d0c765cd5",
        enacted_by=(
            "Pub. L. 97-258, § 1, Sept. 13, 1982, 96 Stat. 877; "
            "Pub. L. 97-452, § 1, Jan. 12, 1983, 96 Stat. 2467"
        ),
        deeming_provision="Pub. L. 97-258, § 4(b); Pub. L. 97-452, § 3(b)",
        source_url="https://www.govinfo.gov/content/pkg/USCODE-1994-title31/pdf/USCODE-1994-title31.pdf",
        source_digest="sha256:3b319dc182915b409d01c26d5fe46326e0416f5e725aa556738d17ba60340f0a",
        source_bytes=2_088_477,
        artifact=_USC_DISPOSITION_TABLES_2026_11_18,
        source_fetched="2026-11-18",
        source_local_path="output/registry-real-data-sources/USCODE-1994-title31.pdf",
        enacted_title=31,
    ),
    Recodification(
        name="title-34-2017",
        former_title=42,
        table="usc-2017-title34-disposition.parquet",
        digest="sha256:17e063ddd410d39c135e4d14550dceadc62707a811dc9e7bd2f63999014dd047",
        enacted_by="OLRC editorial reclassification under 2 U.S.C. 285b, eff. Sept. 1, 2017 (through Pub. L. 115-31)",
        deeming_provision="2 U.S.C. 285b (editorial reclassification without substantive change)",
        source_url="https://www.govinfo.gov/content/pkg/USCODE-2017-title34/pdf/USCODE-2017-title34.pdf",
        source_digest="sha256:c121b7ca9147571955edbb9857da95e17292f21eb00f0a90741ae5b99c40bcd9",
        source_bytes=2_753_424,
        artifact=_USC_DISPOSITION_TABLES_2026_11_18_COMPLETE,
        source_fetched="2026-11-18",
        source_local_path="output/registry-real-data-sources/USCODE-2017-title34.pdf",
        former_titles=(42, 18, 28),
        enacted_title=34,
    ),
    Recodification(
        name="title-41-2011",
        former_title=41,
        table="usc-2011-title41-disposition.parquet",
        digest="sha256:327de9b607eaf74679c21af8a6cf27086c7bf5aaf19c01dbcf3005959fa3a51b",
        enacted_by="Pub. L. 111-350, § 3, Jan. 4, 2011, 124 Stat. 3677",
        deeming_provision="Pub. L. 111-350, § 6(c)",
        source_url="https://www.govinfo.gov/content/pkg/USCODE-2011-title41/pdf/USCODE-2011-title41.pdf",
        source_digest="sha256:3b253b255aa058d05aa4b3e6b6aa2f345ee25a1f98cff5ea19f514c2d0a417c1",
        source_bytes=1_037_994,
        artifact=_USC_DISPOSITION_TABLES_2026_11_18_COMPLETE,
        source_fetched="2026-11-18",
        source_local_path="output/registry-real-data-sources/USCODE-2011-title41.pdf",
        enacted_title=41,
    ),
    Recodification(
        name="title-46-2006",
        former_title=46,
        table="usc-2006-title46-disposition.parquet",
        digest="sha256:2b6a315482a8b8ba142360ea3303e55e6e8e07d632ebe4c3a1a24d38a9efca84",
        enacted_by=(
            "Pub. L. 98-89, Aug. 26, 1983, 97 Stat. 500; "
            "Pub. L. 99-509, Oct. 21, 1986, 100 Stat. 1913; "
            "Pub. L. 100-424, Sept. 9, 1988, 102 Stat. 1591; "
            "Pub. L. 100-710, Nov. 23, 1988, 102 Stat. 4738; "
            "Pub. L. 109-304, Oct. 6, 2006, 120 Stat. 1485"
        ),
        deeming_provision="Pub. L. 98-89, § 2(b); Pub. L. 99-509, § 5103(b); Pub. L. 100-710, § 105(a); Pub. L. 109-304, § 18(c)",
        source_url="https://www.govinfo.gov/content/pkg/USCODE-2006-title46/pdf/USCODE-2006-title46.pdf",
        source_digest="sha256:6bda1578ab30e947d3f7e746bacd53048a197ef80c946f0f7300276c97a5887d",
        source_bytes=2_449_872,
        artifact=_USC_DISPOSITION_TABLES_2026_11_18,
        source_fetched="2026-11-18",
        source_local_path="output/registry-real-data-sources/USCODE-2006-title46.pdf",
        enacted_title=46,
        covers_appendix=True,
    ),
    Recodification(
        name="title-49-1994",
        former_title=49,
        table="usc-1994-title49-disposition.parquet",
        digest="sha256:8403212c0193b3361accf7ff4be238420634beb5aa5740d78b9960fef5b2aedd",
        enacted_by="Pub. L. 103-272, July 5, 1994, 108 Stat. 745",
        deeming_provision="Pub. L. 103-272, § 6(b)",
        source_url="https://www.govinfo.gov/content/pkg/USCODE-1994-title49/pdf/USCODE-1994-title49.pdf",
        source_digest="sha256:66f004679e27e0d16356e14b79cb3b4f7ebf63d91307435fa8f53c95bcc2848d",
        source_bytes=5_165_242,
        artifact=USC_DISPOSITION_TABLES_ARTIFACT,
        source_fetched="2026-08-23",
        enacted_title=49,
        covers_appendix=True,
    ),
    Recodification(
        name="title-49-1994-positivelaw",
        former_title=49,
        table="usc-1994-title49-positivelaw-disposition.parquet",
        digest="sha256:6387ca0487ec234ae04811e90d1490e9bf93407d1b3dd5f3fa40836e3bc21510",
        enacted_by="Pub. L. 103-272, §§ 1(c), (d), (e), 4(j)(9)(A), (11)(B), July 5, 1994, 108 Stat. 745, 1367, 1368",
        deeming_provision="Pub. L. 103-272, § 6(b)",
        source_url="https://www.govinfo.gov/content/pkg/USCODE-1994-title49/pdf/USCODE-1994-title49.pdf",
        source_digest="sha256:66f004679e27e0d16356e14b79cb3b4f7ebf63d91307435fa8f53c95bcc2848d",
        source_bytes=5_165_242,
        artifact=_USC_DISPOSITION_TABLES_2026_11_18_COMPLETE,
        source_fetched="2026-08-23",
        source_local_path=f"{USC_DISPOSITION_TABLES_ARTIFACT}/USCODE-1994-title49.pdf",
        enacted_title=49,
        covers_appendix=False,
    ),
    Recodification(
        name="title-51-2010",
        former_title=42,
        table="usc-2010-title51-disposition.parquet",
        digest="sha256:507bdd8da5dd9a1ff6b5f395193408e1f36120803637ee367ddfecc3792d7c0a",
        enacted_by="Pub. L. 111-314, § 3, Dec. 18, 2010, 124 Stat. 3326",
        deeming_provision="Pub. L. 111-314, § 5(e)",
        source_url="https://www.govinfo.gov/content/pkg/USCODE-2010-title51/pdf/USCODE-2010-title51.pdf",
        source_digest="sha256:66d48661b3bae9b9e9e7a1964a64ff093dc22d94fae81eda6429a4f9551cea84",
        source_bytes=914_412,
        artifact=_USC_DISPOSITION_TABLES_2026_11_18_COMPLETE,
        source_fetched="2026-11-18",
        source_local_path="output/registry-real-data-sources/USCODE-2010-title51.pdf",
        former_titles=(42, 15),
        enacted_title=51,
    ),
    Recodification(
        name="title-54-2014",
        former_title=16,
        table="usc-2014-title54-disposition.parquet",
        digest="sha256:49e79253f9240b75edd85afa3d8fe9b513e231e060434d4fea0d6bab3ac60034",
        enacted_by="Pub. L. 113-287, § 3, Dec. 19, 2014, 128 Stat. 3094",
        deeming_provision="Pub. L. 113-287, § 6(e)",
        source_url="https://www.govinfo.gov/content/pkg/USCODE-2014-title54/pdf/USCODE-2014-title54.pdf",
        source_digest="sha256:548f857e19f2ce9c384211062872d422142a2b55129251d3f82e35c80eafcf21",
        source_bytes=1_085_260,
        artifact=_USC_DISPOSITION_TABLES_2026_11_18_COMPLETE,
        source_fetched="2026-11-18",
        source_local_path="output/registry-real-data-sources/USCODE-2014-title54.pdf",
        enacted_title=54,
    ),
)

#: All eight recodification families named by the 2026-08-23 review (Titles 10
#: ROPMA, 31, 34, 41, 46, 49, 51, and 54) are now pinned above. Kept as an empty
#: mapping so callers inspecting remaining gaps observe closure directly.
RECODIFICATIONS_NOT_PINNED: Mapping[int, str] = {}

#: What a verdict can be. The first five answer the question; the last says the
#: question was not asked of anything.
VERDICTS = (
    #: At least one row names a successor. ALL of them are returned.
    "exists-as-recodified",
    #: Every matching row is ``Rep.`` — the provision was legally repealed.
    "repealed-no-successor",
    #: Every matching row is ``Elim.`` — editorial omission from the title
    #: (e.g. transferred or still codified elsewhere, such as 46 App. § 111
    #: remaining at 19 U.S.C. § 288), not a legal repeal.
    "eliminated-no-successor",
    #: Every matching row names no successor, and the rows point at another
    #: instrument (``(See § 2 of Pub. L. 97-449.)``) or mix non-successor
    #: statuses (such as a span mixing ``Rep.`` and ``Elim.``).
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

#: What a ``not-in-table`` verdict does NOT exclude, attached to every one of
#: them. The table lists the former sections that existed to be restated when
#: the recodification was enacted; one repealed before that was never in it.
NOT_IN_TABLE_CAVEATS = ("repealed_before_the_recodification_not_listed",)

#: Verified OLRC front-matter print errors where the printed disposition table
#: disagrees with the same volume's body Historical and Revision / Codification
#: Notes. The printed row is preserved verbatim so the table stays faithful to
#: the primary source, while callers querying any affected ``(former_title,
#: former_section)`` receive an explicit caveat on :attr:`Disposition.caveats`.
KNOWN_PRINT_DISCREPANCIES: Mapping[tuple[int, str], tuple[str, ...]] = {
    (42, "13136f"): ("olrc_front_matter_print_typo:printed_42:13136f_body_codification_42:14136f",),
    (42, "14136f"): ("olrc_front_matter_print_typo:printed_as_42:13136f_body_codification_34:40728",),
    (42, "3797ee-1"): ("olrc_front_matter_print_typo:printed_34:16902_body_codification_34:10692",),
    (41, "46"): ("olrc_hrn_divergence:printed_41:8502_body_hrn_also_cites_41:8501(2)",),
    (16, "458a"): ("olrc_front_matter_print_typo:printed_54:104908_body_hrn_54:104905",),
}
_KNOWN_PRINT_DISCREPANCY_CAVEATS = frozenset(
    caveat for caveats in KNOWN_PRINT_DISCREPANCIES.values() for caveat in caveats
)

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
#: over every former section the pinned tables list and holds the copy true.
#: Letter suffixes order length-first (``19d..19g`` before ``19aa..19gg``),
#: matching U.S. Code bijective letter numbering, and hyphenated numeric tails
#: order numerically (``1a-9`` before ``1a-10``).
_SECTION_KEY = re.compile(r"^(\d+)([a-z]*)(.*)$")
_TAIL_PART = re.compile(r"(\d+|[a-z]+|[^0-9a-z]+)")


def _tail_order(tail: str) -> tuple[tuple[int, int, str], ...]:
    parts: list[tuple[int, int, str]] = []
    for part in _TAIL_PART.findall(tail):
        if part.isdigit():
            parts.append((1, int(part), ""))
        elif part.isalpha():
            parts.append((2, len(part), part))
        else:
            parts.append((0, 0, part))
    return tuple(parts)


def _section_order(section: str) -> tuple[int, int, str, tuple[tuple[int, int, str], ...]] | None:
    match = _SECTION_KEY.match(section)
    return (int(match.group(1)), len(match.group(2)), match.group(2), _tail_order(match.group(3))) if match else None


def normalize_section(value: object) -> str:
    """Lowercase, trim and collapse every dash spelling. The join key."""

    return str(value or "").strip().lower().translate(_DASHES)


def normalize_subsection(value: object) -> tuple[str, ...]:
    """A subsection query as a path of labels: ``"d"`` and ``"(d)"`` -> ``("d",)``.

    ``"(a)(1)"`` -> ``("a", "1")``. Case is folded because a bare ``"d"`` from a
    citation cannot express whether the print meant ``(d)`` or ``(D)``, and no
    former section in the pinned tables distinguishes uppercase and lowercase
    labels at the same path position (e.g. Title 31 § 232 uses ``(A)``–``(F)``
    with no lowercase ``(a)``–``(f)``), so nothing is conflated by folding.
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
        if self.verdict == "not-in-table":
            if NOT_IN_TABLE_CAVEATS[0] not in self.caveats:
                raise ValueError("an absence from a table is only as wide as the table, and must say so")
            unknown = set(self.caveats) - set(NOT_IN_TABLE_CAVEATS) - _KNOWN_PRINT_DISCREPANCY_CAVEATS
            if unknown:
                raise ValueError(f"undeclared caveat(s) on not-in-table disposition: {sorted(unknown)}")
        elif self.caveats and not set(self.caveats).issubset(_KNOWN_PRINT_DISCREPANCY_CAVEATS):
            raise ValueError("only an absence from the table or a verified print discrepancy carries a caveat")
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
    """The pinned recodification tables, loaded from verified sealed directories."""

    directory: Path
    #: When bound via :meth:`from_repository`, each recodification is read from
    #: ``repository_root / recodification.artifact`` so sealed artifact
    #: directories stay untouched without duplicating bytes. When ``None``
    #: (:meth:`from_directory`), every pinned table is read flat from :attr:`directory`.
    repository_root: Path | None = None
    #: Optional override of :data:`RECODIFICATIONS` (used by unit tests to prove
    #: multi-table non-overwrite behavior without mutating module constants).
    recodifications: tuple[Recodification, ...] | None = None

    @property
    def _catalog(self) -> tuple[Recodification, ...]:
        return RECODIFICATIONS if self.recodifications is None else self.recodifications

    @classmethod
    def from_directory(
        cls, directory: Path | str, *, recodifications: tuple[Recodification, ...] | None = None
    ) -> UscDispositionTables:
        """Bind to a flat directory carrying every pinned table, verifying every digest first."""

        tables = cls(directory=Path(directory), recodifications=recodifications)
        tables.verify()
        return tables

    @classmethod
    def from_repository(cls, root: Path | str) -> UscDispositionTables:
        """Bind to the sealed artifact directories this repository carries."""

        root_path = Path(root)
        tables = cls(directory=root_path / USC_DISPOSITION_TABLES_ARTIFACT, repository_root=root_path)
        tables.verify()
        return tables

    def _directory_for(self, recodification: Recodification) -> Path:
        if self.repository_root is not None:
            return self.repository_root / recodification.artifact
        return self.directory

    def verify(self) -> None:
        """Hash every pinned table, whatever this caller goes on to ask.

        Written over :attr:`_catalog` rather than over one file so every pinned
        table is verified by existing code at bind time, and any duplicate
        recodification ``name`` fails loudly. Multiple recodifications sharing a
        ``former_title`` (such as Title 42 -> Titles 51 and 34, or Title 49's
        front-matter and positive-law tables) are indexed together without
        overwriting one another.
        """

        seen_names: set[str] = set()
        for recodification in self._catalog:
            if recodification.name in seen_names:
                raise ValueError(f"duplicate recodification name: {recodification.name!r}")
            seen_names.add(recodification.name)
        _ = self._by_title
        for recodification in self._catalog:
            _verify_pinned_parquet(
                self._directory_for(recodification), recodification.table, recodification.digest
            )

    @cached_property
    def _by_title(self) -> Mapping[int, tuple[Recodification, ...]]:
        by_title: dict[int, list[Recodification]] = {}
        for recodification in self._catalog:
            for ft in recodification.effective_former_titles:
                if recodification not in by_title.setdefault(ft, []):
                    by_title[ft].append(recodification)
        return {ft: tuple(recs) for ft, recs in by_title.items()}

    @cached_property
    def _tagged_rows(self) -> Mapping[int, Mapping[str, tuple[tuple[str, DispositionRow], ...]]]:
        """``former title -> former section -> (recodification name, DispositionRow)``, never overwriting."""

        import pyarrow.parquet as pq

        _ = self._by_title
        out: dict[int, dict[str, list[tuple[str, DispositionRow]]]] = {}
        for recodification in self._catalog:
            allowed_titles = frozenset(recodification.effective_former_titles)
            path = _verify_pinned_parquet(
                self._directory_for(recodification), recodification.table, recodification.digest
            )
            table = pq.read_table(path)
            columns = {name: table.column(name).to_pylist() for name in table.schema.names}
            for values in zip(*columns.values(), strict=True):
                row = dict(zip(columns, values, strict=True))
                ft = int(row["former_title"])
                if ft not in allowed_titles:
                    raise ValueError(
                        f"{recodification.table} states former title {ft}, outside {recodification.effective_former_titles}"
                    )
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
                out.setdefault(ft, {}).setdefault(section, []).append(
                    (
                        recodification.name,
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
                        ),
                    )
                )
        return {
            ft: {sec: tuple(items) for sec, items in sections.items()}
            for ft, sections in out.items()
        }

    @cached_property
    def _rows(self) -> Mapping[int, Mapping[str, tuple[DispositionRow, ...]]]:
        """``former title -> former section -> its printed rows``, in print order."""

        return {
            ft: {sec: tuple(row for _, row in items) for sec, items in sections.items()}
            for ft, sections in self._tagged_rows.items()
        }

    def _recodifications_for(self, former_title: int, *, appendix: bool = False) -> tuple[Recodification, ...]:
        recods = self._by_title.get(former_title, ())
        if appendix:
            return tuple(r for r in recods if r.covers_appendix)
        return recods

    def former_sections(self, former_title: int, *, appendix: bool = False) -> frozenset[str]:
        """Every former section the pinned table(s) for that title (and appendix scope) list."""

        if not appendix:
            return frozenset(self._rows.get(former_title, {}))
        allowed = {r.name for r in self._recodifications_for(former_title, appendix=True)}
        if not allowed:
            return frozenset()
        return frozenset(
            sec
            for sec, items in self._tagged_rows.get(former_title, {}).items()
            if any(name in allowed for name, _ in items)
        )

    def sections_in_span(
        self, former_title: int, former_section: str, section_end: object, *, appendix: bool = False
    ) -> tuple[str, ...]:
        """Every former section the pinned table(s) LIST inside a stated span.

        Sorted in canonical section order, endpoints included. Empty where no
        table is pinned, where either endpoint has no order key, where the span
        runs backwards, or where the table lists nothing between them.
        """

        low = _section_order(normalize_section(former_section))
        high = _section_order(normalize_section(section_end))
        if low is None or high is None or high < low:
            return ()
        matched = [
            (key, section)
            for section in self.former_sections(former_title, appendix=appendix)
            if (key := _section_order(section)) is not None and low <= key <= high
        ]
        matched.sort(key=lambda item: item[0])
        return tuple(section for _, section in matched)

    def disposition(
        self,
        former_title: int,
        former_section: str,
        subsection: object = None,
        *,
        section_end: object = None,
        appendix: bool = False,
    ) -> Disposition:
        """What became of one former section, of one subsection, or of a span."""

        section = normalize_section(former_section)
        wanted = normalize_subsection(subsection)
        end = normalize_section(section_end) or None
        recods = self._recodifications_for(former_title, appendix=appendix)
        if not recods:
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

        checked_names = "+".join(r.name for r in recods)
        allowed_names = {r.name for r in recods}
        print_caveats = KNOWN_PRINT_DISCREPANCIES.get((former_title, section), ())

        if end is not None:
            members = tuple(
                self.disposition(
                    former_title, member, subsection if member == section else None, appendix=appendix
                )
                for member in self.sections_in_span(former_title, section, end, appendix=appendix)
            )
            if not members:
                return Disposition(
                    former_title=former_title,
                    former_section=section,
                    former_section_end=end,
                    subsection=wanted,
                    verdict="not-in-table",
                    recodification=checked_names,
                    successors=(),
                    rows=(),
                    subsection_resolved=None,
                    caveats=NOT_IN_TABLE_CAVEATS + print_caveats,
                )
            matched = tuple(row for member in members for row in member.rows)
            start = next((member for member in members if member.former_section == section), None)
            span_recod = "+".join(
                dict.fromkeys(
                    part
                    for member in members
                    if member.recodification is not None
                    for part in member.recodification.split("+")
                )
            )
            span_caveats = tuple(dict.fromkeys(c for member in members for c in member.caveats))
            return Disposition(
                former_title=former_title,
                former_section=section,
                former_section_end=end,
                subsection=wanted,
                verdict=_verdict_over(matched),
                recodification=span_recod,
                successors=tuple(dict.fromkeys(one for member in members for one in member.successors)),
                rows=matched,
                subsection_resolved=None if start is None else start.subsection_resolved,
                members=members,
                caveats=span_caveats,
            )

        tagged = tuple(
            pair
            for pair in self._tagged_rows.get(former_title, {}).get(section, ())
            if pair[0] in allowed_names
        )
        if not tagged:
            return Disposition(
                former_title=former_title,
                former_section=section,
                subsection=wanted,
                verdict="not-in-table",
                recodification=checked_names,
                successors=(),
                rows=(),
                subsection_resolved=None,
                caveats=NOT_IN_TABLE_CAVEATS + print_caveats,
            )

        resolved: bool | None = None
        matched_tagged = tagged
        if wanted:
            narrowed = tuple(pair for pair in tagged if _row_covers(pair[1], wanted))
            resolved = bool(narrowed)
            matched_tagged = narrowed or tagged

        matched = tuple(row for _, row in matched_tagged)
        answering_names = "+".join(dict.fromkeys(name for name, _ in matched_tagged))
        return Disposition(
            former_title=former_title,
            former_section=section,
            subsection=wanted,
            verdict=_verdict_over(matched),
            recodification=answering_names,
            successors=tuple({row.successor: None for row in matched if row.successor is not None}),
            rows=matched,
            subsection_resolved=resolved,
            caveats=print_caveats,
        )


def _verdict_over(matched: tuple[DispositionRow, ...]) -> str:
    """The verdict a set of printed rows carries. One spelling, two callers."""

    if any(row.successor is not None for row in matched):
        return "exists-as-recodified"
    if all(row.status == "repealed" for row in matched):
        return "repealed-no-successor"
    if all(row.status == "eliminated" for row in matched):
        return "eliminated-no-successor"
    return "stated-without-successor"


_INTRODUCTORY_MATTER = re.compile(
    r"\((?:matter|words|provisions?|text)\s+(?:before|preceding)\s+"
    r"(?:(?:subsec\.|par\.|subpar\.|cl\.|subsection|paragraph|subparagraph|clause)\s*)?"
    r"\([0-9a-zA-Z]{1,4}\)",
    re.IGNORECASE,
)


def _trailing_child_labels_after_paren(text: str, open_idx: int) -> frozenset[str]:
    """Child labels listed after a balanced parenthetical qualifier, e.g. ``), (1) to (5)``."""

    depth = 0
    end_idx = len(text)
    for idx in range(open_idx, len(text)):
        ch = text[idx]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end_idx = idx + 1
                break
    tail = text[end_idx:].translate(_DASHES)
    if "(" not in tail:
        return frozenset()
    found: set[str] = set()
    for m_rng in re.finditer(
        r"\(([0-9a-zA-Z]{1,4})\)\s*(?:to|through|-)\s*\(([0-9a-zA-Z]{1,4})\)", tail, re.IGNORECASE
    ):
        lo, hi = m_rng.group(1), m_rng.group(2)
        if lo.isdigit() and hi.isdigit() and int(lo) <= int(hi):
            found.update(str(n) for n in range(int(lo), int(hi) + 1))
        elif len(lo) == 1 and len(hi) == 1 and lo.isalpha() and hi.isalpha() and lo.isupper() == hi.isupper() and lo <= hi:
            found.update(chr(c).lower() for c in range(ord(lo), ord(hi) + 1))
    for grp in _GROUP.findall(tail):
        found.add(grp.lower())
    return frozenset(found)


def _introductory_excludes_child(
    row: DispositionRow, labels: tuple[str, ...], wanted: tuple[str, ...]
) -> bool:
    """Whether ``row`` is an introductory-matter row at ``len(labels)`` that excludes ``wanted``."""

    m = _INTRODUCTORY_MATTER.search(row.former_text)
    if m is None:
        return False
    chapeau_depth = len(_GROUP.findall(row.former_text[: m.start()]))
    if len(labels) != chapeau_depth:
        return False
    trailing = _trailing_child_labels_after_paren(row.former_text, m.start())
    return not (trailing and wanted[chapeau_depth] in trailing)


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

    Two exceptions narrow chapeau / note entries:
    - A **note** row (``1374 note → 41706``, ``10927 (note) → 31138``) disposes
      of statutory notes under the section, not any subsection of it.
    - A **structural introductory-matter** row (``16 U.S.C. 1a-2 (matter before (a))``,
      ``41:35 (matter before subsec. (a) ...)``, ``42:16654(a) (matter before par. (1))``)
      disposes strictly of chapeau text preceding a structural unit (never
      punctuation splits such as ``words before semicolon``), so it speaks for
      its own level (``16654(a)``) and never for a deeper child (``1a-2(a)``,
      ``16654(a)(1)``) unless the same printed row also names that trailing
      child (``351(a) (words before par. (1) ...), (1) to (5)``).
    """

    if row.former_note is not None:
        return False
    printed = row.former_subsection
    if printed is None:
        return not _introductory_excludes_child(row, (), wanted)
    labels = tuple(g.lower() for g in _GROUP.findall(printed.split("-")[0]))
    if not labels:
        return False
    if "-" in printed:
        return wanted[0] == labels[0]
    if len(wanted) > len(labels) and _introductory_excludes_child(row, labels, wanted):
        return False
    return labels[: len(wanted)] == wanted[: len(labels)]
