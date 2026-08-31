#!/usr/bin/env python
"""Rebuild ``usc-source-credits.parquet`` from OLRC's USLM release-point XML.

:mod:`refspec.registry.act_resolution` consults **two** independent sources for
an act-relative citation and refuses when they disagree
(:data:`~refspec.registry.act_resolution.SOURCE_COMPOSITION_RULE`). The first,
Table III, this repository can rebuild
(:mod:`refspec.registry.usc_act_index`). The second -- the U.S. Code's own
source credits -- it could only *load*
(``USC_SOURCE_CREDIT_ARTIFACT = "output/usc-source-credit-index-2026-08-02"``).
This module is the builder that was missing.

Every section of the Code carries a ``<sourceCredit>`` naming the law that
enacted it and every law that has amended it since::

    26 U.S.C. 6038E  <-  (Added Pub. L. 116-260, div. EE, title I, § 107(d)(1),
                          Dec. 27, 2020, 134 Stat. 3048.)

That states something Table III does not: the **division**, per section. Table
III is keyed by the enacting public law alone and one public law may enact
dozens of acts -- 116-260 enacts 94 -- so a division stated per section is
exactly the discriminator Table III lacks.

**The rule is a refusal rule, and the mess is why.** A credit lists the
enactment *and* every amendment, so an expression accepting any ``Pub. L. N-M,
div. X ... § S`` anywhere in a credit pairs a division with a section number
belonging to a different citation in the same credit.
:data:`STRICT_ENACTMENT_RULE` requires the citation to sit in an explicit
enactment construction -- ``Added Pub. L. ...`` or ``as added Pub. L. ...``.
What it does not retain, it does not guess at: 22 U.S.C. 2714a reads
``(Pub. L. 114-94, div. C, title XXXII, § 32101, Dec. 4, 2015, 129 Stat.
1729.)`` with no such construction, and this build carries no row for it.
Neither does 26 U.S.C. 7652, whose long amendment chain names (116-260, div. EE,
§ 107) -- the act section that enacted 6038E -- and never uses the word
"amended" at all, which is why reading the role by proximity to that word does
not work either.

**The page belongs to the citation it follows** (:data:`BOUNDED_PAGE_RULE`).
The Statutes at Large search for a retained citation ends where the *next*
citation begins, so a credit listing several enactments cannot lend one
citation's page to another. 5 U.S.C. 3116 is the shape: ``(Added Pub. L.
115-232, div. A, title XI, § 1108(a), Aug. 13, 2018, 132 Stat. 2007; amended
Pub. L. 116-92, div. A, title XI, § 1115, Dec. 20, 2019, 133 Stat. 1604.)`` --
the enactment is at 2007 and 1604 is the amendment's. Measured on release point
119-102, the bound changes **no** retained answer, because every retained
citation states its page before the next one begins
(:data:`BOUND_CHANGES_NO_ANSWER_ON_119_102`). That is a fact about this release
point and not a licence to drop the bound: what proves the bound works is the
mutation battery in ``tests/test_build_usc_source_credits.py``, which deletes
the enactment's own page from the real 3116 credit and watches an unbounded
search reach for the amendment's.

**Why an XML parse rather than an expression over the file.** USLM
``<section>`` elements nest, and a credit must be attributed to the section that
*contains* it. A nearest-preceding-tag scan attributes a credit sitting after a
nested close to the wrong section. The ancestry is the fact being read, so it is
read structurally; the strict rule itself is an expression over the credit's own
flattened text, because the construction it looks for is prose.

Usage::

    python tools/build_usc_source_credits.py --output output/usc-source-credits-2026-08-31
    python tools/build_usc_source_credits.py --verify output/usc-source-credit-index-2026-08-02
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import xml.etree.ElementTree as ElementTree
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The whole Code for one release point, one zip. There is no per-section
#: endpoint worth 51,548 requests.
USLM_RELEASE_URL_TEMPLATE = (
    "https://uscode.house.gov/download/releasepoints/us/pl/{congress}/{law}/xml_uscAll@{congress}-{law}.zip"
)

#: The salvaged archive this build reads, and the release point it is. It sits
#: beside the USC *annual* editions in the same salvage directory, and is not
#: one of them: the annual archives are XHTML historical editions with no USLM
#: in them at all, so they cannot feed this parser. 108 MB of the directory's
#: 2.1 GB is the input; the rest is a different corpus.
DEFAULT_ARCHIVE = Path(
    "~/Work/corpora/_salvage-2026-08-28/refspec-output/usc-annual-2026-08-24/xml_uscAll_119-102.zip"
).expanduser()
DEFAULT_RELEASE_POINT = "119-102"

ARTIFACT_SCHEMA_VERSION = "usc-source-credit-artifact-v1"

#: Bump when a parse changes shape, so a receipt cannot silently describe bytes
#: a different parser would read.
PARSER_VERSION = "uscode-uslm-source-credits-v1"

#: Require an explicit enactment construction. See the module docstring for the
#: measured alternative and why it is unsafe.
STRICT_ENACTMENT_RULE = "added-or-as-added-pub-law-division-act-section-v1"

#: The Statutes at Large search for a citation ends where the next one begins.
BOUNDED_PAGE_RULE = "statutes-at-large-page-searched-only-until-the-next-citation-v1"

#: Measured: over all 51,548 credits of release point 119-102, bounding the page
#: search changes no retained row's answer. Pinned so a release point where it
#: starts to matter fails the suite instead of arriving as a changed value.
BOUND_CHANGES_NO_ANSWER_ON_119_102 = 0

#: USLM spells a section suffix with an EN DASH (``/us/usc/t16/s824s–1``); Table
#: III, the citation grammar and ``rkaf:us-usc`` all spell it with a hyphen.
#: Straightening it is what lets the two OLRC surfaces join at all; the verbatim
#: identifier is carried alongside so nothing is lost.
SECTION_DASH_RULE = "straighten-uslm-en-dash-to-hyphen-v1"

#: A triple naming several U.S. Code sections is kept and marked, never dropped:
#: "the source said two things" is a different fact from "the source said
#: nothing", and the two call for different fixes.
MULTI_TARGET_POLICY = "retain-and-mark-refusal-multi_target-v1"

#: Every way this build declines to attribute a credit the strict rule matched.
QUARANTINE_REASONS = (
    #: The credit sits under no ``<section>`` at all -- a chapter-level or
    #: appendix credit.
    "credit_outside_usc_section",
    #: The enclosing section's identifier is not ``/us/usc/tN/sX``. The appendix
    #: titles carry ``/us/usc/t18a/pl/91/538/s1`` and its kin.
    "section_identifier_unparsable",
)

CREDIT_COLUMNS = (
    "public_law",
    "division",
    "act_section",
    "usc_title",
    "usc_section",
    "usc_identifier",
    "statutes_at_large_volume",
    "statutes_at_large_page",
    "target_count",
    "refusal",
)
QUARANTINE_COLUMNS = ("source", "reason", "public_law", "division", "act_section", "raw_value")

_RELEASE_POINT = re.compile(r"^(?P<congress>[1-9]\d{0,2})-(?P<law>[1-9]\d*)$")

#: A U.S. Code section identifier, and only that shape. A subsection
#: (``/us/usc/t26/s6038E/a``) or an appendix path is not a section identifier
#: and must not be read as one.
USC_SECTION_IDENTIFIER = re.compile(r"^/us/usc/t(?P<title>[1-9]\d*)/s(?P<section>[^/]+)$")

#: Every dash the Statutes at Large, USLM and prose spell a range with.
DASH = re.compile(r"[‐‑‒–—―]")

#: The enactment construction, the public law, its division, and the act
#: section. ``lead`` is the whole rule: an empty lead is an amendment (or a
#: re-statement of the amended act's own citation) and is discarded. Intervening
#: structural units -- ``title I``, ``subtitle B``, ``ch. 2`` -- are crossed but
#: never captured, because the act section is the last one and the earlier ones
#: are not it.
ENACTMENT = re.compile(
    r"(?P<lead>as\s+added\s+|added\s+|)"
    r"Pub\.\s*L\.\s*(?P<congress>[1-9]\d{0,2})[-‐-―](?P<law>[1-9]\d*)"
    r"\s*,\s*div\.\s*(?P<division>[A-Z]{1,3})\b"
    r"(?:\s*,\s*(?:title|subtitle|part|ch\.|chapter|subch\.|subchapter)[^,§]{0,40})*"
    r"\s*,?\s*§+\s*(?P<section>[1-9]\d*[A-Za-z]?)",
    re.IGNORECASE,
)

STATUTES_AT_LARGE = re.compile(r"(?P<volume>[1-9]\d{0,2})\s+Stat\.\s+(?P<page>[1-9]\d{0,4})")

#: The two leads that make a citation an enactment. Anything else -- including
#: no lead at all -- is not one.
ENACTMENT_LEADS = frozenset({"added", "as added"})


def uslm_release_url(release_point: str) -> str:
    """The whole-Code zip for a release point such as ``"119-102"``.

    A release point of any other shape is refused rather than turned into a URL
    that would 404, so a build fails on the key rather than on the response.
    """
    match = _RELEASE_POINT.fullmatch(release_point or "")
    if match is None:
        raise ValueError(f"invalid U.S. Code release point: {release_point!r}")
    return USLM_RELEASE_URL_TEMPLATE.format(congress=match.group("congress"), law=match.group("law"))


def normalize_usc_section(value: object) -> str:
    """Straighten a USLM section suffix to the spelling everything else uses.

    Implements :data:`SECTION_DASH_RULE`. Nothing else about the section is
    touched: this is a dash, not a normalization policy.
    """
    return DASH.sub("-", str(value or ""))


@dataclass(frozen=True)
class SourceCredit:
    """One U.S. Code section, and the act section that added it."""

    public_law: str
    division: str
    act_section: str
    usc_title: str
    usc_section: str
    #: The USLM identifier verbatim, en dash and all, so the row stays auditable
    #: against the bytes it was read from.
    usc_identifier: str
    statutes_at_large_volume: str | None = None
    statutes_at_large_page: str | None = None


@dataclass(frozen=True)
class QuarantinedCredit:
    """A credit that matched the strict rule and could not be attributed."""

    reason: str
    public_law: str
    division: str
    act_section: str
    raw_value: str

    def __post_init__(self) -> None:
        if self.reason not in QUARANTINE_REASONS:
            raise ValueError(f"undeclared quarantine reason: {self.reason!r}")


@dataclass(frozen=True)
class CreditScan:
    """What was read, including what was read and not retained."""

    credits: tuple[SourceCredit, ...] = ()
    quarantine: tuple[QuarantinedCredit, ...] = ()
    credits_scanned: int = 0
    credits_naming_a_division: int = 0
    credits_outside_a_section: int = 0
    strict_matches: int = 0
    #: Retained citations whose page would differ if the search were not bounded
    #: at the next citation. Pinned against
    #: :data:`BOUND_CHANGES_NO_ANSWER_ON_119_102`.
    pages_the_bound_changed: int = 0

    def merge(self, other: CreditScan) -> CreditScan:
        return CreditScan(
            credits=self.credits + other.credits,
            quarantine=self.quarantine + other.quarantine,
            credits_scanned=self.credits_scanned + other.credits_scanned,
            credits_naming_a_division=self.credits_naming_a_division + other.credits_naming_a_division,
            credits_outside_a_section=self.credits_outside_a_section + other.credits_outside_a_section,
            strict_matches=self.strict_matches + other.strict_matches,
            pages_the_bound_changed=self.pages_the_bound_changed + other.pages_the_bound_changed,
        )


def flatten_credit(element: ElementTree.Element) -> str:
    """The credit's visible text.

    Only ASCII whitespace is collapsed. USLM writes ``§ 107`` with a narrow
    no-break space, and rewriting it would be editing the source to suit the
    expression rather than the other way round.
    """
    return re.sub(r"[ \t\r\n]+", " ", "".join(element.itertext())).strip()


def iter_source_credits(document: bytes | str) -> Iterator[tuple[str | None, str]]:
    """Yield ``(enclosing section identifier, credit text)`` for one USLM title.

    The identifier is the nearest **ancestor** ``<section>``'s, which is why
    this walks the tree: a credit that follows a nested section's close tag has
    a different nearest-preceding tag than it has ancestor.
    """
    payload = document.encode("utf-8") if isinstance(document, str) else document
    stack: list[str | None] = []
    for event, element in ElementTree.iterparse(io.BytesIO(payload), events=("start", "end")):
        tag = element.tag.rsplit("}", 1)[-1]
        if event == "start":
            stack.append(element.get("identifier") if tag == "section" else None)
            continue
        if tag == "sourceCredit":
            yield next((s for s in reversed(stack) if s), None), flatten_credit(element)
        stack.pop()


def bounded_page(text: str, matches: list[re.Match[str]], position: int) -> re.Match[str] | None:
    """The Statutes at Large place stated between one citation and the next.

    Implements :data:`BOUNDED_PAGE_RULE`. Returning ``None`` where a citation
    states no page of its own is the point: the alternative is silently
    borrowing the next citation's.
    """
    match = matches[position]
    end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
    return STATUTES_AT_LARGE.search(text, match.end(), end)


def scan_source_credits(document: bytes | str) -> CreditScan:
    """Apply :data:`STRICT_ENACTMENT_RULE` to one USLM title's source credits."""

    credits: list[SourceCredit] = []
    quarantine: list[QuarantinedCredit] = []
    scanned = naming_a_division = outside = strict_matches = bound_changed = 0

    for identifier, text in iter_source_credits(document):
        scanned += 1
        if "div." in text:
            naming_a_division += 1
        matches = list(ENACTMENT.finditer(text))
        for position, match in enumerate(matches):
            if (match.group("lead") or "").strip().lower() not in ENACTMENT_LEADS:
                continue
            strict_matches += 1
            public_law = f"{match.group('congress')}-{match.group('law')}"
            division, act_section = match.group("division"), match.group("section")
            section = USC_SECTION_IDENTIFIER.fullmatch(identifier or "")
            if section is None:
                if identifier is None:
                    outside += 1
                quarantine.append(
                    QuarantinedCredit(
                        reason="credit_outside_usc_section" if identifier is None else "section_identifier_unparsable",
                        public_law=public_law,
                        division=division,
                        act_section=act_section,
                        raw_value=identifier or "",
                    )
                )
                continue
            page = bounded_page(text, matches, position)
            unbounded = STATUTES_AT_LARGE.search(text, match.end())
            if (page and page.span()) != (unbounded and unbounded.span()):
                bound_changed += 1
            credits.append(
                SourceCredit(
                    public_law=public_law,
                    division=division,
                    act_section=act_section,
                    usc_title=section.group("title"),
                    usc_section=normalize_usc_section(section.group("section")),
                    usc_identifier=identifier or "",
                    statutes_at_large_volume=page.group("volume") if page else None,
                    statutes_at_large_page=page.group("page") if page else None,
                )
            )

    return CreditScan(
        credits=tuple(credits),
        quarantine=tuple(quarantine),
        credits_scanned=scanned,
        credits_naming_a_division=naming_a_division,
        credits_outside_a_section=outside,
        strict_matches=strict_matches,
        pages_the_bound_changed=bound_changed,
    )


def scan_release_zip(archive: Path) -> tuple[CreditScan, list[tuple[str, str]]]:
    """Scan every title in a whole-Code release zip.

    Returns the merged scan and one ``(member, sha256)`` pair per title, sorted,
    so a receipt pins the bytes each count was read from rather than only the
    zip they arrived in.
    """
    scan = CreditScan()
    members: list[tuple[str, str]] = []
    with zipfile.ZipFile(archive) as bundle:
        for name in sorted(n for n in bundle.namelist() if n.endswith(".xml")):
            payload = bundle.read(name)
            members.append((name, f"sha256:{hashlib.sha256(payload).hexdigest()}"))
            scan = scan.merge(scan_source_credits(payload))
    return scan, members


def credit_rows(credits: tuple[SourceCredit, ...]) -> list[dict[str, Any]]:
    """The sealed table's rows, with :data:`MULTI_TARGET_POLICY` applied."""

    targets: dict[tuple[str, str, str], set[tuple[str, str]]] = defaultdict(set)
    for credit in credits:
        targets[(credit.public_law, credit.division, credit.act_section)].add((credit.usc_title, credit.usc_section))
    rows = []
    for credit in credits:
        count = len(targets[(credit.public_law, credit.division, credit.act_section)])
        rows.append(
            {
                "public_law": credit.public_law,
                "division": credit.division,
                "act_section": credit.act_section,
                "usc_title": credit.usc_title,
                "usc_section": credit.usc_section,
                "usc_identifier": credit.usc_identifier,
                "statutes_at_large_volume": credit.statutes_at_large_volume,
                "statutes_at_large_page": credit.statutes_at_large_page,
                "target_count": str(count),
                "refusal": "multi_target" if count > 1 else None,
            }
        )
    return rows


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def canonical_key(row: dict[str, Any], columns: tuple[str, ...] = CREDIT_COLUMNS) -> tuple[str, ...]:
    return tuple("" if row.get(column) is None else str(row[column]) for column in columns)


def write_parquet(path: Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    """Write VARCHAR columns in a fixed order, sorted, so bytes are stable."""
    ordered = sorted(rows, key=lambda row: canonical_key(row, columns))
    table = pa.table(
        {c: pa.array([None if r.get(c) is None else str(r[c]) for r in ordered], pa.string()) for c in columns}
    )
    pq.write_table(table, path, compression="zstd", sorting_columns=None)


def compare_to_frozen(rows: list[dict[str, Any]], frozen_table: Path) -> dict[str, Any]:
    """Account for every difference between derived and frozen rows."""

    frozen = pq.read_table(frozen_table).to_pylist()
    derived_keys = Counter(canonical_key(row) for row in rows)
    frozen_keys = Counter(canonical_key(row) for row in frozen)
    return {
        "frozen_table": str(frozen_table),
        "derived_rows": len(rows),
        "frozen_rows": len(frozen),
        "rows_identical": derived_keys == frozen_keys,
        "rows_only_in_derived": sorted((derived_keys - frozen_keys).elements()),
        "rows_only_in_frozen": sorted((frozen_keys - derived_keys).elements()),
    }


def build(output_dir: Path, *, archive: Path, release_point: str) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    scan, members = scan_release_zip(archive)
    rows = credit_rows(scan.credits)
    quarantine = [
        {
            "source": "uslm_source_credit",
            "reason": entry.reason,
            "public_law": entry.public_law,
            "division": entry.division,
            "act_section": entry.act_section,
            "raw_value": entry.raw_value or None,
        }
        for entry in scan.quarantine
    ]
    targets = {(r["public_law"], r["division"], r["act_section"]): r["target_count"] for r in rows}

    credits_path = output_dir / "usc-source-credits.parquet"
    quarantine_path = output_dir / "quarantine.parquet"
    write_parquet(credits_path, CREDIT_COLUMNS, rows)
    write_parquet(quarantine_path, QUARANTINE_COLUMNS, quarantine)

    receipt = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "coverage": {
            "titles": len(members),
            "source_credits_scanned": scan.credits_scanned,
            "credits_naming_a_division": scan.credits_naming_a_division,
            "credits_outside_a_section": scan.credits_outside_a_section,
            "strict_matches": scan.strict_matches,
            "triples": len(targets),
            "unambiguous_triples": sum(1 for count in targets.values() if count == "1"),
            "multi_target_triples": sum(1 for count in targets.values() if count != "1"),
            "distinct_public_law_division_pairs": len({(law, division) for law, division, _ in targets}),
            "rows": len(rows),
            "rows_refusing": sum(1 for row in rows if row["refusal"]),
            "rows_without_a_statutes_at_large_page": sum(1 for row in rows if not row["statutes_at_large_page"]),
            "quarantine_rows": len(quarantine),
            "quarantine_reasons": dict(sorted(Counter(row["reason"] for row in quarantine).items())),
        },
        "measured": {
            # What the bound actually did. Zero is the answer on 119-102 and is
            # pinned as such: a release point where it stops being zero is a
            # fact that must surface, not a value that quietly changes.
            "retained_pages_the_bound_changed": scan.pages_the_bound_changed,
        },
        "inputs": {
            "release_point": release_point,
            "release_url": uslm_release_url(release_point),
            "archive": archive.name,
            "archive_digest": file_sha256(archive),
            "archive_bytes": archive.stat().st_size,
            # The archive digest says which bundle; the member digests say which
            # bytes each count was read from.
            "titles": [{"member": member, "digest": digest} for member, digest in members],
        },
        "rules": {
            "strict_enactment_rule": STRICT_ENACTMENT_RULE,
            "strict_enactment_rule_derivation": (
                "A source credit lists the original enactment AND every later amendment, so an "
                "expression accepting any 'Pub. L. N-M, div. X ... section S' anywhere in a credit "
                "pairs a division with a section number belonging to a different citation in the "
                "same credit. Reading the role by proximity to the word 'amended' does not fix it: "
                "26 U.S.C. 7652 names (116-260, div. EE, sec. 107) -- the act section that enacted "
                "26 U.S.C. 6038E -- and its credit never uses the word 'amended' at all. Requiring "
                "an explicit enactment construction ('Added Pub. L. ...' or 'as added Pub. L. ...') "
                "removes that false positive. What it does not retain it does not guess at: "
                "22 U.S.C. 2714a reads '(Pub. L. 114-94, div. C, title XXXII, sec. 32101, ...)' with "
                "no such construction and this index carries no row for it."
            ),
            "bounded_page_rule": BOUNDED_PAGE_RULE,
            "bounded_page_rule_derivation": (
                "The Statutes at Large page belongs to the citation it follows, so the search window "
                "ends where the next citation begins. 5 U.S.C. 3116 states an enactment at 132 Stat. "
                "2007 and an amendment at 133 Stat. 1604 in one credit, and they are not "
                "interchangeable. Measured on this release point the bound changes no retained "
                "answer -- every retained citation states its own page before the next one begins -- "
                "so the count is pinned at zero and a release point where it stops being zero fails "
                "the suite instead of arriving as a changed value."
            ),
            "section_dash_rule": SECTION_DASH_RULE,
            "section_dash_rule_derivation": (
                "USLM spells a section suffix with an EN DASH ('/us/usc/t16/s824s-1' with U+2013) "
                "while Table III, the citation grammar and rkaf:us-usc all spell it with a hyphen. "
                "It is a spelling convention of the source rather than a distinction it draws, and "
                "the verbatim identifier is carried in usc_identifier, so straightening loses nothing."
            ),
            "multi_target_policy": MULTI_TARGET_POLICY,
            "multi_target_policy_derivation": (
                "A triple naming several U.S. Code sections is kept, marked refusal='multi_target' "
                "on every one of its rows, and refused at resolution time. Dropping it would tell a "
                "consumer the source was silent when it was plural, and those are different facts "
                "that call for different fixes."
            ),
            "quarantine_reasons": list(QUARANTINE_REASONS),
        },
        "outputs": {
            path.name: {"digest": file_sha256(path), "rows": pq.ParquetFile(path).metadata.num_rows}
            for path in (credits_path, quarantine_path)
        },
    }
    (output_dir / "receipt.json").write_text(canonical_json(receipt), encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--output", type=Path, help="directory to seal the derived table into")
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE, help="the whole-Code USLM zip")
    parser.add_argument("--release-point", default=DEFAULT_RELEASE_POINT, help='the release point, e.g. "119-102"')
    parser.add_argument("--verify", type=Path, help="a sealed artifact directory to compare against, row by row")
    args = parser.parse_args(argv)
    if args.output is None and args.verify is None:
        parser.error("one of --output or --verify is required")
    if not args.archive.exists():
        print(
            f"missing archive {args.archive}; fetch {uslm_release_url(args.release_point)} (~109 MB)",
            file=sys.stderr,
        )
        return 2

    if args.output is not None:
        receipt = build(args.output, archive=args.archive, release_point=args.release_point)
        print(canonical_json(receipt["coverage"]))
    if args.verify is not None:
        scan, _ = scan_release_zip(args.archive)
        report = compare_to_frozen(credit_rows(scan.credits), args.verify / "usc-source-credits.parquet")
        print(canonical_json(report))
        return 0 if report["rows_identical"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
