#!/usr/bin/env python
"""Rebuild ``usc-popular-names.parquet`` from OLRC's Popular Name Tool.

:mod:`refspec.registry.usc_act_index` rebuilds the **Table III** half of the act
index from a bulk file in this repository, and *carries the other half over
byte-identically* -- ``--popular-names-from``, ``usc_act_index.py:428,532`` --
because the popular names come from a different OLRC document that the bulk file
does not contain. This module is the missing half: the reader for that document.

**What the document is.** One machine-generated page, 11 MB, listing every
popular name Congress has used, each with the enacting act's Table III key and
often the U.S. Code section where the act's short title lives. It carries the
aliases too, which is what makes "ERISA" resolvable without hand-curation. The
page states one ``<div class='popular-name-table-entry'>`` per name and one
``<p class='popular-name-information'>`` per thing it has to say about that
name, with the identifying facts in attributes rather than in nesting. There is
no tree to walk, so this reads the flat elements the generator emits, and every
expression below is asserted against captured bytes
(``research/evidence/usc-regeneration-2026-08-31/``).

**Read what OLRC states, twice, and say when the two agree.** Each ``cite``
paragraph states its Statutes at Large place twice -- once as a
``statviewer.htm?volume=&page=`` query, once as prose ("134 Stat. 4879") --
and :data:`STATUTES_AT_LARGE_RULE` reads the query first because it is the
machine-stated fact, falling back to the prose where the page states no link.
Measured on release point 119-102: **12,988 cite rows state both and every one
of them agrees; 56 state only the prose; 43 state neither.** Zero disagree, so
the rule adds a witness without moving a value -- which is why this build
reproduces the frozen table rather than improving on it.

**Kinds are the tool's own vocabulary, kept verbatim.** ``cite``,
``short-title-ref``, ``also-known-as``, ``see`` and ``renamed`` are not
collapsed, because the difference between "this act is" and "this name means"
is the difference between an identity and a redirect. What follows from the
kind is a refusal rather than a guess: an alias target is read only out of a
``see``/``renamed`` construction (:data:`SEE_TARGET_RULE`), so
``also-known-as``'s "Also known as the 21st Century IDEA" -- which reads exactly
like one -- mints no target; and a Statutes at Large place is read only out of a
``cite``, so a ``short-title-ref`` cannot contribute one.

**Ambiguity is kept, counted, and never collapsed**
(:data:`NAME_AMBIGUITY_RULE`). 34 normalized names state more than one enacting
act -- the Detainee Treatment Act of 2005 is both Pub. L. 109-148 and
Pub. L. 109-163 -- and both rows are written. Choosing one would invent a
citation OLRC never made; dropping the name would lose an act the tool lists.

Usage::

    python tools/build_usc_popular_names.py --output output/usc-popular-names-2026-08-31
    python tools/build_usc_popular_names.py --verify output/usc-act-index-2026-08-22
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from refspec.registry.citation_grammar import normalize_popular_name

#: The document this reads. Recorded in the receipt; never fetched by a build,
#: which reads the pinned bytes below so a rebuild is offline and repeatable.
POPULAR_NAMES_URL = "https://uscode.house.gov/popularnames/popularnames.htm"

#: The pinned capture. ``research/evidence/usc-regeneration-2026-08-31/README.md``
#: carries the fetch instant, the digest, and the accounting for the 16 bytes by
#: which it differs from the capture the frozen artifact was sealed from.
PINNED_HTML = REPO_ROOT / "research" / "evidence" / "usc-regeneration-2026-08-31" / "popularnames.htm.gz"

ARTIFACT_SCHEMA_VERSION = "usc-popular-names-artifact-v1"

#: Bump when a parse changes shape, so a receipt cannot silently describe bytes
#: a different parser would read.
PARSER_VERSION = "uscode-olrc-popular-names-v1"

#: Where the Statutes at Large volume and page come from, in order.
STATUTES_AT_LARGE_RULE = "statviewer-query-then-stated-citation-v1"

#: An alias target is read out of a construction, never out of prose that
#: resembles one.
SEE_TARGET_RULE = "target-read-only-from-a-see-or-renamed-construction-v1"

#: ``usckey`` is read as an anchor only in the one shape that is one.
USC_ANCHOR_RULE = "usckey-read-only-as-title-colon-section-v1"

#: One name, several enacting acts: kept, counted, never collapsed.
NAME_AMBIGUITY_RULE = "a-name-stating-several-enacting-acts-is-kept-and-counted-v1"

#: Every way this build declines to read something. Codes are data: the artifact
#: records them per row and the receipt counts them.
QUARANTINE_REASONS = (
    #: An entry whose ``<p class='popular-name'>`` is absent or empty. There is
    #: no name to file the entry's facts under.
    "entry_without_a_name",
    #: An information paragraph stating no ``content-type``. The kind is what
    #: says how the paragraph is to be read, so a paragraph without one is not
    #: read at all.
    "information_without_a_content_type",
    #: A ``usckey`` that is not ``title:section``. The appendix titles carry
    #: "18A:1" and "28A:Rule", and 18A is not U.S. Code title 18. The record is
    #: still written, with no anchor; this row is where the refused value
    #: survives.
    "usc_anchor_unparsable",
    #: A normalized name whose ``cite`` paragraphs state more than one Table III
    #: key. Every row is written; this is the count and the evidence.
    "name_states_several_enacting_acts",
)

#: The columns of the sealed table, in the order the frozen artifact states
#: them. ``name_key`` and ``see_also_key`` are the only derived columns; both
#: are :func:`refspec.registry.citation_grammar.normalize_popular_name` applied
#: to the column beside them.
POPULAR_NAME_COLUMNS = (
    "name",
    "name_key",
    "content_type",
    "table3_key",
    "usc_title",
    "usc_section",
    "see_also",
    "see_also_key",
    "release_point",
    "division",
    "statutes_at_large_volume",
    "statutes_at_large_page",
)
QUARANTINE_COLUMNS = ("source", "reason", "name", "raw_value")

#: One entry: the anchor, the release point the page was generated at, and the
#: paragraphs. ``release-point`` is optional in the expression because a
#: generator that stopped emitting it must produce records with a null release
#: point rather than no records at all.
ENTRY = re.compile(
    r"<div id='(?P<anchor>[^']*)' class='popular-name-table-entry'"
    r"(?:[^>]*?release-point='(?P<release_point>[^']*)')?[^>]*>"
    r"(?P<body>.*?)</div>",
    re.DOTALL,
)
NAME = re.compile(r"<p class='popular-name'>(?P<name>.*?)</p>", re.DOTALL)
INFORMATION = re.compile(
    r"<p class='popular-name-information'(?P<attributes>[^>]*)>(?P<text>.*?)</p>",
    re.DOTALL,
)
ATTRIBUTE = re.compile(r"(?P<name>[a-z0-9_-]+)='(?P<value>[^']*)'")

#: "See Federal Water Pollution Control Act", "Renamed Internal Revenue Code of
#: 1939". Anchored at the start: the construction is how the tool spells a
#: redirect, and text that merely mentions an act is not one.
SEE_TARGET = re.compile(r"^\s*(?:see|renamed(?:\s+as)?)\s+(?P<target>.+?)\s*$", re.IGNORECASE)

#: A ``usckey`` is ``title:section``. The section may carry a suffix the U.S.C.
#: identifier grammar excludes ("18:App.)"), which is the source speaking and is
#: kept; a title that is not a number ("18A") is an appendix and is refused.
USC_ANCHOR = re.compile(r"^(?P<title>[1-9]\d*):(?P<section>[^\s:]+)$")

#: The Statutes at Large place as the page's own link states it. The volume is a
#: query parameter, so it survives even where the link text omits it -- which is
#: the whole reason to read the query rather than the words.
STATVIEWER = re.compile(r"statviewer\.htm\?volume=(?P<volume>\d+)&(?:amp;)?page=(?P<page>\d+)")

#: The same place as prose. Read only where no link states it.
STATED_CITATION = re.compile(r"\b(?P<volume>\d+)\s+Stat\.\s+(?P<page>\d+)")

#: "Pub. L. 116-260, div. EE, ..." -- one public law may enact dozens of acts,
#: each in its own division, and this is the only thing that tells them apart.
DIVISION = re.compile(r"\bdiv\.\s*(?P<division>[A-Z]{1,3})\b")

TAG = re.compile(r"<[^>]*>")

#: Attributes the page states on an entry or a paragraph that the sealed schema
#: has no column for. Counted in the receipt rather than dropped in silence.
_CARRIED_ATTRIBUTES = frozenset({"content-type", "t3searchkey", "usckey"})


def visible_text(fragment: str) -> str:
    """The visible text of an HTML fragment, whitespace collapsed."""
    return re.sub(r"\s+", " ", unescape(TAG.sub("", fragment))).strip()


@dataclass(frozen=True)
class PopularNameRecord:
    """One popular name and one thing the tool says about it.

    An entry may carry several information paragraphs -- the enacting citation,
    a short-title reference, an alias -- so one name yields several records.
    """

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
    #: Which of the two statements the place was read from: ``"statviewer"``,
    #: ``"stated"``, ``"both"`` (they agree), ``"disagreement"``, or ``None``.
    #: Not a column of the sealed table -- it is the measurement that makes
    #: :data:`STATUTES_AT_LARGE_RULE` checkable, and the receipt counts it.
    statutes_at_large_witness: str | None = None
    #: The verbatim ``usckey`` where it is not an anchor, so the refusal keeps
    #: the value it refused.
    refused_usc_anchor: str | None = None


@dataclass(frozen=True)
class EntryDefect:
    """An entry or paragraph this reader declined to read."""

    reason: str
    name: str
    raw_value: str | None = None

    def __post_init__(self) -> None:
        if self.reason not in QUARANTINE_REASONS:
            raise ValueError(f"undeclared quarantine reason: {self.reason!r}")


@dataclass(frozen=True)
class PopularNameScan:
    """What the page said, including what it said nothing readable about."""

    records: tuple[PopularNameRecord, ...] = ()
    defects: tuple[EntryDefect, ...] = ()
    entries: int = 0
    #: Attribute name -> how many times the page stated it without a column.
    stated_but_not_carried: dict[str, int] | None = None


def statutes_at_large(paragraph: str, stated: str) -> tuple[str | None, str | None, str | None]:
    """The Statutes at Large volume and page, and which statement supplied it.

    Implements :data:`STATUTES_AT_LARGE_RULE`. The link's query is preferred
    because it is machine-stated; the prose is the fallback and, where both are
    present, the cross-check. A disagreement is reported rather than resolved --
    on release point 119-102 there are none, and one appearing later is a fact
    about the page that must not arrive as a silently-changed value.
    """

    link = STATVIEWER.search(paragraph)
    prose = STATED_CITATION.search(stated)
    linked = (link.group("volume"), link.group("page")) if link else None
    spoken = (prose.group("volume"), prose.group("page")) if prose else None
    if linked is None and spoken is None:
        return None, None, None
    if linked is None:
        return spoken[0], spoken[1], "stated"
    if spoken is None:
        return linked[0], linked[1], "statviewer"
    if linked == spoken:
        return linked[0], linked[1], "both"
    return linked[0], linked[1], "disagreement"


def parse_popular_names(document: str) -> PopularNameScan:
    """Read the Popular Name Tool page into one record per stated fact."""

    records: list[PopularNameRecord] = []
    defects: list[EntryDefect] = []
    uncarried: Counter[str] = Counter()
    entries = 0

    for entry in ENTRY.finditer(document):
        entries += 1
        body = entry.group("body")
        heading = NAME.search(body)
        name = visible_text(heading.group("name")) if heading is not None else ""
        if not name:
            defects.append(EntryDefect(reason="entry_without_a_name", name="", raw_value=entry.group("anchor") or None))
            continue
        release_point = entry.group("release_point")
        for information in INFORMATION.finditer(body):
            attributes = dict(ATTRIBUTE.findall(information.group("attributes")))
            uncarried.update(key for key in attributes if key not in _CARRIED_ATTRIBUTES)
            content_type = attributes.get("content-type")
            if not content_type:
                defects.append(
                    EntryDefect(
                        reason="information_without_a_content_type",
                        name=name,
                        raw_value=visible_text(information.group("text")) or None,
                    )
                )
                continue
            stated = visible_text(information.group("text"))
            anchor = attributes.get("usckey")
            match = USC_ANCHOR.fullmatch(anchor) if anchor else None
            refused = anchor if anchor and match is None else None
            if refused is not None:
                defects.append(EntryDefect(reason="usc_anchor_unparsable", name=name, raw_value=refused))
            is_cite = content_type == "cite"
            division = DIVISION.search(stated) if is_cite else None
            volume, page, witness = (
                statutes_at_large(information.group("text"), stated) if is_cite else (None, None, None)
            )
            alias = SEE_TARGET.match(stated) if content_type in {"see", "renamed"} else None
            records.append(
                PopularNameRecord(
                    name=name,
                    content_type=content_type,
                    table3_key=attributes.get("t3searchkey") or None,
                    usc_title=match.group("title") if match else None,
                    usc_section=match.group("section") if match else None,
                    see_also=alias.group("target") if alias else None,
                    release_point=release_point,
                    division=division.group("division") if division else None,
                    statutes_at_large_volume=volume,
                    statutes_at_large_page=page,
                    statutes_at_large_witness=witness,
                    refused_usc_anchor=refused,
                )
            )
    return PopularNameScan(
        records=tuple(records),
        defects=tuple(defects),
        entries=entries,
        stated_but_not_carried=dict(sorted(uncarried.items())),
    )


def ambiguous_names(records: tuple[PopularNameRecord, ...]) -> dict[str, tuple[str, ...]]:
    """Normalized names whose ``cite`` paragraphs state several enacting acts.

    Implements :data:`NAME_AMBIGUITY_RULE`. The map is the receipt's evidence
    and the quarantine's content; no row is removed on account of it.
    """

    keys: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if record.content_type == "cite" and record.table3_key:
            keys[normalize_popular_name(record.name)].add(record.table3_key)
    return {name: tuple(sorted(found)) for name, found in sorted(keys.items()) if len(found) > 1}


def table_rows(records: tuple[PopularNameRecord, ...]) -> list[dict[str, Any]]:
    """The sealed table's rows, in the frozen artifact's own column set."""

    return [
        {
            "name": record.name,
            "name_key": normalize_popular_name(record.name),
            "content_type": record.content_type,
            "table3_key": record.table3_key,
            "usc_title": record.usc_title,
            "usc_section": record.usc_section,
            "see_also": record.see_also,
            "see_also_key": normalize_popular_name(record.see_also) if record.see_also else None,
            "release_point": record.release_point,
            "division": record.division,
            "statutes_at_large_volume": record.statutes_at_large_volume,
            "statutes_at_large_page": record.statutes_at_large_page,
        }
        for record in records
    ]


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def read_pinned_html(path: Path = PINNED_HTML) -> str:
    """The captured page, decompressed. ``.gz`` because 11 MB of it is chrome."""
    payload = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return payload.decode("utf-8")


def canonical_key(row: dict[str, Any], columns: tuple[str, ...] = POPULAR_NAME_COLUMNS) -> tuple[str, ...]:
    """A row as the sort key the sealed writer orders by."""
    return tuple("" if row.get(column) is None else str(row[column]) for column in columns)


def write_parquet(path: Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    """Write VARCHAR columns in a fixed order, sorted, so bytes are stable."""
    ordered = sorted(rows, key=lambda row: canonical_key(row, columns))
    table = pa.table(
        {c: pa.array([None if r.get(c) is None else str(r[c]) for r in ordered], pa.string()) for c in columns}
    )
    pq.write_table(table, path, compression="zstd", sorting_columns=None)


def compare_to_frozen(rows: list[dict[str, Any]], frozen_table: Path) -> dict[str, Any]:
    """Account for every difference between derived and frozen rows.

    Two verdicts are reported separately, because they answer different
    questions. ``rows_identical`` compares all twelve columns. ``parsed_rows_
    identical`` compares the ten columns this parser reads out of the page,
    leaving out ``name_key`` and ``see_also_key`` -- the two columns that are
    not read but *derived*, by a normalizer that has changed since the frozen
    artifact was sealed. Where the derived columns differ,
    ``normalized_agreement`` states whether the two spellings collapse to one
    under the normalizer :class:`refspec.registry.act_resolution.ActIndex`
    applies to that column on load (``act_resolution.py:499,501``), which is
    what decides whether the difference can reach a consumer.
    """

    frozen = pq.read_table(frozen_table).to_pylist()
    parsed = tuple(c for c in POPULAR_NAME_COLUMNS if c not in {"name_key", "see_also_key"})
    parsed_key = lambda row: canonical_key(row, parsed)  # noqa: E731

    derived_parsed = Counter(parsed_key(row) for row in rows)
    frozen_parsed = Counter(parsed_key(row) for row in frozen)
    report: dict[str, Any] = {
        "frozen_table": str(frozen_table),
        "derived_rows": len(rows),
        "frozen_rows": len(frozen),
        "rows_identical": sorted(canonical_key(r) for r in rows) == sorted(canonical_key(r) for r in frozen),
        "parsed_rows_identical": derived_parsed == frozen_parsed,
    }
    if derived_parsed != frozen_parsed:
        # The parse itself moved. Nothing below is meaningful, and forcing a
        # pairing would hide which rows appeared and which vanished.
        report["parsed_rows_only_in_derived"] = sorted((derived_parsed - frozen_parsed).elements())
        report["parsed_rows_only_in_frozen"] = sorted((frozen_parsed - derived_parsed).elements())
        return report

    differing = [
        {
            "name": f["name"],
            "content_type": f["content_type"],
            "column": column,
            "frozen": f[column],
            "derived": d[column],
            "normalized_agreement": normalize_popular_name(f[column]) == d[column],
        }
        for d, f in zip(sorted(rows, key=parsed_key), sorted(frozen, key=parsed_key), strict=True)
        for column in ("name_key", "see_also_key")
        if (d[column] or "") != (f[column] or "")
    ]
    report["rows_differing_only_in_a_derived_key"] = len(differing)
    report["all_differences_collapse_under_the_loader_normalizer"] = all(
        item["normalized_agreement"] for item in differing
    )
    report["differences"] = differing
    return report


def build(output_dir: Path, *, html_path: Path) -> dict:
    """Seal the popular-name table from one captured page."""

    output_dir.mkdir(parents=True, exist_ok=True)
    document = read_pinned_html(html_path)
    scan = parse_popular_names(document)
    rows = table_rows(scan.records)
    ambiguous = ambiguous_names(scan.records)

    quarantine = [
        {"source": "popular_names", "reason": defect.reason, "name": defect.name or None, "raw_value": defect.raw_value}
        for defect in scan.defects
    ] + [
        {
            "source": "popular_names",
            "reason": "name_states_several_enacting_acts",
            "name": name,
            "raw_value": " ".join(keys),
        }
        for name, keys in ambiguous.items()
    ]

    names_path = output_dir / "usc-popular-names.parquet"
    quarantine_path = output_dir / "quarantine.parquet"
    write_parquet(names_path, POPULAR_NAME_COLUMNS, rows)
    write_parquet(quarantine_path, QUARANTINE_COLUMNS, quarantine)

    witnesses = Counter(r.statutes_at_large_witness for r in scan.records if r.content_type == "cite")
    receipt = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "coverage": {
            "entries": scan.entries,
            "popular_name_rows": len(rows),
            "distinct_names": len({row["name_key"] for row in rows}),
            "content_types": dict(sorted(Counter(row["content_type"] for row in rows).items())),
            "release_points": sorted({row["release_point"] for row in rows if row["release_point"]}),
            "ambiguous_names": len(ambiguous),
            "quarantine_rows": len(quarantine),
            "quarantine_reasons": dict(sorted(Counter(row["reason"] for row in quarantine).items())),
        },
        "measured": {
            # The cross-check that makes STATUTES_AT_LARGE_RULE checkable rather
            # than merely stated. A non-zero disagreement count is a fact about
            # the page and must fail a build's reader, not change a value.
            "cite_rows_stating_both_places_and_agreeing": witnesses.get("both", 0),
            "cite_rows_stating_only_the_statviewer_query": witnesses.get("statviewer", 0),
            "cite_rows_stating_only_the_prose_citation": witnesses.get("stated", 0),
            "cite_rows_stating_neither": witnesses.get(None, 0),
            "cite_rows_where_the_two_places_disagree": witnesses.get("disagreement", 0),
            "stated_but_not_carried": scan.stated_but_not_carried,
            "ambiguous_names_sample": dict(list(ambiguous.items())[:5]),
        },
        "inputs": {
            "popular_names_url": POPULAR_NAMES_URL,
            "popular_names_capture": str(html_path.resolve().relative_to(REPO_ROOT))
            if html_path.resolve().is_relative_to(REPO_ROOT)
            else html_path.name,
            "popular_names_digest": f"sha256:{hashlib.sha256(document.encode('utf-8')).hexdigest()}",
            "popular_names_bytes": len(document.encode("utf-8")),
        },
        "rules": {
            "statutes_at_large_rule": STATUTES_AT_LARGE_RULE,
            "statutes_at_large_rule_derivation": (
                "Each cite paragraph states its Statutes at Large place twice: as a "
                "statviewer.htm?volume=&page= query and as prose. The query is read first because it "
                "is the machine-stated fact and carries a volume that link text elsewhere on OLRC "
                "omits; the prose is the fallback. Measured on release point 119-102: 12,988 cite "
                "rows state both and every one agrees, 56 state only the prose, 0 state only the "
                "query, 43 state neither, and none disagree. On this page the query is therefore a "
                "second witness rather than extra reach -- the rule adds a check without moving a "
                "value, which is why this build reproduces the frozen table exactly."
            ),
            "see_target_rule": SEE_TARGET_RULE,
            "see_target_rule_derivation": (
                "An alias target is read only out of a see/renamed construction at the start of the "
                "paragraph, and only from a see or renamed paragraph. 'Also known as the 21st Century "
                "IDEA' reads exactly like a redirect and is not one: its content-type is "
                "also-known-as, so no target is minted from it."
            ),
            "usc_anchor_rule": USC_ANCHOR_RULE,
            "usc_anchor_rule_derivation": (
                "usckey is read as an anchor only in the shape title:section. Six paragraphs on "
                "release point 119-102 state an appendix key instead ('18A:1', '18A:16', '18A:61', "
                "'18A:Rule', '28A:Rule' twice); 18A is not U.S. Code title 18 and reading it as one "
                "would mint a section that does not exist. The record is written with no anchor and "
                "the refused value is kept in quarantine.parquet."
            ),
            "name_ambiguity_rule": NAME_AMBIGUITY_RULE,
            "name_ambiguity_rule_derivation": (
                "34 normalized names state more than one enacting act -- the Detainee Treatment Act "
                "of 2005 is both Pub. L. 109-148 and Pub. L. 109-163. Every row is written and the "
                "name is counted here. Choosing one act would invent a citation OLRC never made, and "
                "dropping the name would lose an act the tool lists."
            ),
            "quarantine_reasons": list(QUARANTINE_REASONS),
        },
        "outputs": {
            # Resolve ONCE and key from the resolved path: guarding on
            # path.resolve() while calling relative_to on the unresolved path
            # raised ValueError for the relative --output the usage block
            # itself shows, after both tables were written and before the
            # receipt existed (xhigh review catch, 2026-08-31).
            str(resolved.relative_to(REPO_ROOT)) if resolved.is_relative_to(REPO_ROOT) else resolved.name: {
                "digest": file_sha256(resolved),
                "rows": pq.ParquetFile(resolved).metadata.num_rows,
            }
            for resolved in (names_path.resolve(), quarantine_path.resolve())
        },
    }
    (output_dir / "receipt.json").write_text(canonical_json(receipt), encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--output", type=Path, help="directory to seal the derived table into")
    parser.add_argument("--html", type=Path, default=PINNED_HTML, help="the captured popularnames.htm (.gz accepted)")
    parser.add_argument(
        "--verify",
        type=Path,
        help="a sealed artifact directory to compare the derived table against, row by row",
    )
    args = parser.parse_args(argv)
    if args.output is None and args.verify is None:
        parser.error("one of --output or --verify is required")

    if args.output is not None:
        receipt = build(args.output, html_path=args.html)
        print(canonical_json(receipt["coverage"]))
    if args.verify is not None:
        rows = table_rows(parse_popular_names(read_pinned_html(args.html)).records)
        report = compare_to_frozen(rows, args.verify / "usc-popular-names.parquet")
        print(canonical_json(report))
        return 0 if report["parsed_rows_identical"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
