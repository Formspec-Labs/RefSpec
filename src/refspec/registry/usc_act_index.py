"""Seal the U.S. Code act index from OLRC's Table III **bulk** release.

The 2026-08-02 artifact was built one HTTP request per act, so its Table III
side covers the 24 laws a bootstrap corpus happened to cite. OLRC also
publishes the *whole* of Table III as one file, and that file has been sitting
in this repository's source tree, unread, since 2026-08-06:
:data:`BULK_SOURCE` -> :data:`BULK_MEMBER`, 48,973 acts and 317,590
classification records covering Congresses 1 through 119. This module reads it
and writes the same artifact, with the same schema, from that one file and no
network at all.

**What this build changes and what it carries.** Only the Table III side is
rebuilt. ``usc-popular-names.parquet`` is *carried over byte-identically* from
the artifact named by ``--popular-names-from``: the popular names come from a
different OLRC document (``popularnames.htm``) that this bulk file does not
contain, and re-fetching it would move the release point for no reason this
work needs. The carried digest is restated in the receipt, so the two halves of
the artifact each name their own provenance.

**The member is not a well-formed XML document.** It is a bare concatenation of
sibling ``<act>`` elements -- no XML declaration, no wrapping root -- so the
second ``<act>`` is junk after the document element and both
``ElementTree.parse`` and ``ElementTree.iterparse`` refuse the whole file with
:data:`BULK_WELL_FORMEDNESS_DEFECT`. :func:`iter_act_fragments` is therefore a
streaming split on ``</act>`` that hands each fragment to ``fromstring``
separately -- and *checks* what it splits: a byte between two fragments that is
not whitespace fails the build rather than being skipped.

**Label, never guess.** Two source-side spellings had to be decided, and both
are decided by reading what OLRC states rather than by re-deriving it:

* :data:`TABLE3_KEY_RULE` -- the Table III key is the ``search-key`` attribute
  OLRC puts on every ``<act>``, with a pre-1957 act's full date narrowed to its
  year, because that is the spelling ``usc-popular-names.parquet`` joins on.
  Deriving the key from ``<num>`` instead -- the rule a reader would guess --
  mints ``78-80`` (Public Law 78-80) for the 1956 session-law chapter 78-80,
  whose ``search-key`` says plainly it is ``1956-03-02:78-80``.
* :data:`PAGE_SPAN_RULE` -- 20,809 records state a Statutes at Large page
  *span* ("3440, 3441", "1007-1009") where the per-page build stored the single
  page its statviewer link carried. 20,371 of those have an ``<act-section>``:
  the column is read as an integer by
  :class:`~refspec.registry.act_resolution.ActIndex`, so the row keeps the
  span's first page and the verbatim span is written to ``quarantine.parquet``
  and counted in the receipt. The other 438 have no ``<act-section>`` at all,
  so they are already in ``quarantine.parquet`` under
  ``record_without_act_section`` -- span text and all -- before the page
  column is ever read. Narrowed, named, and countable -- not dropped.

Nothing the file states is discarded in silence. A record with no
``<act-section>`` has no key to be filed under and goes to ``quarantine.parquet``
with its reason; every attribute and element the reader sees but the sealed
schema has no column for is named with its count in the receipt's
``stated_but_not_carried``; and the status vocabulary is published as it is
spelled, R.S. citations and all.

Usage::

    python -m refspec.registry.usc_act_index --output output/usc-act-index-2026-08-22
    python -m refspec.registry.usc_act_index --output output/usc-act-index-2026-08-22 --verify
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: The artifact shape, unchanged: this build writes the same three tables and
#: the same columns the 2026-08-02 artifact writes, because the consumer reads
#: them and a new shape would be a new consumer.
ARTIFACT_SCHEMA_VERSION = "usc-act-index-artifact-v2"

#: The parser these bytes were read by. The per-page ancestor is
#: ``uscode-olrc-parser-v2``; this one reads a different document in a
#: different format, so it says so rather than inheriting a version that would
#: make a receipt describe bytes a different parser read.
PARSER_VERSION = "uscode-olrc-table3-bulk-xml-v1"

#: OLRC's whole-of-Table-III release, acquired 2026-08-06, pinned by digest and
#: by byte length. Both halves are checked: a truncated download has the right
#: name and the wrong length, and a different release has the right length only
#: by coincidence.
BULK_SOURCE = "output/registry-real-data-sources/olrc-table3-xml-bulk-119-73.zip"
BULK_SOURCE_DIGEST = "sha256:93e1f233e081e47fc3680c4b699151c6d66329988fe21add3b6e9e62746aeea7"
BULK_SOURCE_BYTES = 14966992
BULK_MEMBER = "fulldump@119-73.xml"
BULK_MEMBER_BYTES = 126260704

#: The release point the bulk file states in its own name, and it is EARLIER
#: than the 119-102 the per-page artifact fetched. Every content difference
#: between the two Table III tables traces to that gap, and the receipt's
#: ``reproduction`` block counts them rather than asserting they are absent.
BULK_RELEASE_POINT = "119-73"

#: Why ``ElementTree.parse`` cannot read :data:`BULK_MEMBER`, stated as the
#: parser states it. The file opens with a blank line and 48,973 sibling
#: ``<act>`` elements at top level; line 29 is where the first ``</act>`` is
#: followed, on the same line, by the second ``<act`` at column 6. ``iterparse``
#: fails identically -- the defect is the document's shape, not the API.
BULK_WELL_FORMEDNESS_DEFECT = "junk after document element: line 29, column 6"

#: The key spelling ``usc-popular-names.parquet`` joins on, taken from OLRC's
#: own ``search-key`` rather than rebuilt from ``<num>``.
TABLE3_KEY_RULE = "olrc-search-key-with-a-pre-1957-date-narrowed-to-its-year-v1"

#: A stated page span keeps its first page in the column and its whole text in
#: quarantine, because the column is read as one integer.
PAGE_SPAN_RULE = "statutes-at-large-page-span-narrowed-to-its-first-page-v1"

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
ACT_SECTION_COLUMNS = (
    "table3_key",
    "act_section",
    "usc_title",
    "usc_section",
    "status",
    "statutes_at_large_volume",
    "statutes_at_large_page",
)
QUARANTINE_COLUMNS = ("source", "reason", "table3_key", "raw_value")

#: The two shapes a Table III key comes in, restated from the URL grammar the
#: per-page builder fetched by. A key outside it is not refused -- OLRC really
#: states 210 of them, all Public Resolutions -- but it is counted, because a
#: key the Popular Name Tool cannot spell is a row no citation can reach.
_TABLE3_KEY_SHAPE = re.compile(r"^(?:[1-9]\d{0,2}-[1-9]\d*|(?:1[789]|20)\d{2}:[1-9]\d*)$")

#: The leading integer of a stated Statutes at Large page, which is the page the
#: classification begins on whether the text names one page or a span.
_FIRST_PAGE = re.compile(r"^\s*(\d+)")

_ACT_OPEN = b"<act "
_ACT_CLOSE = b"</act>"

#: A build must not seal a secret. The scan is over what is written, not what
#: was read, so a credential in an environment variable cannot reach the file.
_SECRET_LIKE = re.compile(r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|api[_-]?key=[^\s&]{8,})\b", re.IGNORECASE)

#: Everything the reader sees on an ``<act>`` or a ``<record>`` that the sealed
#: columns have nowhere to put. Named here, counted in the receipt: "the schema
#: cannot carry this" is a fact a consumer is owed, and a silent drop is not.
_NOT_CARRIED_ACT = (
    "id",
    "congress",
    "date",
    "sequence",
    "insertion",
    "format",
    "print-in-supplement",
    "include-in-online-release-point",
)
_NOT_CARRIED_RECORD = ("id", "sequence", "usckey", "print-in-supplement")


class BulkFormatError(ValueError):
    """The bulk member is not shaped the way this reader proved it was."""


@dataclass(frozen=True)
class BulkRecord:
    """One ``<record>``: what OLRC states about one classification."""

    act_section: str | None
    statutes_at_large_page: str | None
    usc_title: str | None
    usc_section: str | None
    status: str | None


@dataclass(frozen=True)
class BulkAct:
    """One ``<act>`` element, with the key it is filed under."""

    table3_key: str
    search_key: str
    congress: str
    date: str
    num: str
    statutes_at_large_volume: str
    records: tuple[BulkRecord, ...]


def table3_key_from_search_key(search_key: str) -> str:
    """OLRC's ``search-key``, in the spelling the popular-name table joins on.

    A modern act's search key is already the Table III key (``103-414``). A
    pre-1957 act's carries the full enactment date (``1948-06-30:758``) where
    the Popular Name Tool carries only the year (``1948:758``), so the date is
    narrowed and nothing else is touched.

    Reading the *stated* key is the whole point. ``<num>`` alone is ambiguous:
    ``78-80`` is both a plausible public law number and the 1956 session-law
    chapter this file actually contains, and only ``search-key`` says which.
    """

    head, separator, tail = search_key.partition(":")
    if not separator:
        return search_key
    if not re.fullmatch(r"(?:1[789]|20)\d{2}-\d{2}-\d{2}", head):
        raise BulkFormatError(f"a pre-1957 search key that is not date-prefixed: {search_key!r}")
    return f"{head[:4]}:{tail}"


def iter_act_fragments(stream: BinaryIO, *, block_size: int = 1 << 22) -> Iterator[bytes]:
    """Every ``<act>`` element of the bulk member, one at a time.

    The member has no root element (:data:`BULK_WELL_FORMEDNESS_DEFECT`), so it
    is split on ``</act>`` rather than parsed. The split is *checked*: bytes
    before an ``<act`` or after the last ``</act>`` that are not whitespace
    raise, so a shape this reader has not proved cannot be read as if it had.
    """

    pending = b""
    for block in iter(lambda: stream.read(block_size), b""):
        pending += block
        while (cut := pending.find(_ACT_CLOSE)) >= 0:
            fragment, pending = pending[: cut + len(_ACT_CLOSE)], pending[cut + len(_ACT_CLOSE) :]
            start = fragment.find(_ACT_OPEN)
            if start < 0:
                raise BulkFormatError("a </act> with no <act> opening it")
            junk = fragment[:start].strip()
            if junk:
                raise BulkFormatError(f"{len(junk)} bytes between two <act> elements: {junk[:60]!r}")
            yield fragment[start:]
    junk = pending.strip()
    if junk:
        raise BulkFormatError(f"{len(junk)} bytes after the last </act>: {junk[:60]!r}")


def parse_act(fragment: bytes | str) -> BulkAct:
    """One ``<act>`` fragment, as the file states it."""

    text = fragment.decode("utf-8") if isinstance(fragment, bytes) else fragment
    element = ET.fromstring(text)
    if element.tag != "act":
        raise BulkFormatError(f"fragment is not an <act>: {element.tag!r}")

    def required(attribute: str) -> str:
        # A bare KeyError says nothing about WHICH attribute or WHICH
        # fragment; this names both, the way every other refusal here does.
        try:
            return element.attrib[attribute]
        except KeyError:
            raise BulkFormatError(f"<act> has no {attribute!r} attribute: {text[:60]!r}") from None

    search_key = required("search-key")
    return BulkAct(
        table3_key=table3_key_from_search_key(search_key),
        search_key=search_key,
        congress=required("congress"),
        date=required("date"),
        num=(element.findtext("num") or "").strip(),
        statutes_at_large_volume=required("statutes-at-large-volume"),
        records=tuple(
            BulkRecord(
                act_section=_stated(record, "act-section"),
                statutes_at_large_page=_stated(record, "statutes-at-large-page"),
                usc_title=_stated(record, "united-states-code-title"),
                usc_section=_stated(record, "united-states-code-section"),
                status=_stated(record, "united-states-code-status"),
            )
            for record in element.findall("record")
        ),
    )


def _stated(element: ET.Element, tag: str) -> str | None:
    """The text of a child element, or ``None`` when the file states none."""

    child = element.find(tag)
    if child is None:
        return None
    return (child.text or "").strip() or None


def _is_stated_span(page: str) -> bool:
    """True when a stated Statutes at Large page names a span, not one page.

    The same rule :data:`PAGE_SPAN_RULE` narrows by: the text's leading
    integer (:data:`_FIRST_PAGE`) differs from the whole trimmed string --
    "3440, 3441" narrows to "3440" and is a span; "23" matches itself and is
    not. A page with no leading integer at all is not a span; that is counted
    separately as ``pages_unreadable``. Read the same way whether or not the
    record keeps its own row in ``usc-act-sections.parquet``, so the acts
    stating a span are one countable population instead of two.
    """

    first = _FIRST_PAGE.match(page)
    return first is not None and first.group(1) != page.strip()


def iter_bulk_acts(zip_path: Path, *, member: str = BULK_MEMBER) -> Iterator[BulkAct]:
    """Every act of the bulk release, streamed out of the zip."""

    with zipfile.ZipFile(zip_path) as archive, archive.open(member) as handle:
        for fragment in iter_act_fragments(handle):
            yield parse_act(fragment)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _write_parquet(path: Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    """Write VARCHAR columns in a fixed order, sorted, so bytes are stable."""

    import pyarrow as pa
    import pyarrow.parquet as pq

    ordered = sorted(rows, key=lambda row: tuple("" if row.get(c) is None else str(row[c]) for c in columns))
    table = pa.table(
        {c: pa.array([None if r.get(c) is None else str(r[c]) for r in ordered], pa.string()) for c in columns}
    )
    pq.write_table(table, path, compression="zstd", sorting_columns=None)


def _scan_for_secrets(rows: list[dict[str, Any]], where: str) -> None:
    for row in rows:
        for key, value in row.items():
            if value is not None and _SECRET_LIKE.search(str(value)):
                raise SystemExit(f"refusing to seal a secret-like value in {where}.{key}")


def verify_source(zip_path: Path) -> list[str]:
    """Check the bulk zip and its one member against the pins above."""

    problems: list[str] = []
    if not zip_path.is_file():
        return [f"no bulk source at {zip_path}"]
    if zip_path.stat().st_size != BULK_SOURCE_BYTES:
        problems.append(f"bulk source is {zip_path.stat().st_size} bytes, pinned at {BULK_SOURCE_BYTES}")
    observed = file_sha256(zip_path)
    if observed != BULK_SOURCE_DIGEST:
        problems.append(f"bulk source drifted: expected {BULK_SOURCE_DIGEST}, observed {observed}")
    with zipfile.ZipFile(zip_path) as archive:
        members = {info.filename: info.file_size for info in archive.infolist()}
    if BULK_MEMBER not in members:
        problems.append(f"bulk source has no member {BULK_MEMBER}: {sorted(members)}")
    elif members[BULK_MEMBER] != BULK_MEMBER_BYTES:
        problems.append(f"{BULK_MEMBER} is {members[BULK_MEMBER]} bytes, pinned at {BULK_MEMBER_BYTES}")
    return problems


def _repo_relative(path: Path) -> str:
    """A repo-relative path when possible, else the basename.

    Absolute scratch paths in a receipt make two rebuilds from two working
    directories differ for a reason that is not about the data.
    """

    resolved = path.resolve()
    try:
        return str(resolved.relative_to(_REPO_ROOT))
    except ValueError:
        return resolved.name


def _read_rows(path: Path) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    return pq.read_table(path).to_pylist()


def _compare_with(reference_dir: Path, section_rows: list[dict[str, Any]]) -> dict[str, object]:
    """How much of a reference artifact's Table III table this one reproduces.

    Restricted to the keys the reference actually holds -- it fetched 24 laws
    and this build reads 23,147, so a comparison over everything would say only
    that this one is larger. Rows are compared as a MULTISET of all seven
    columns, so a row that moved between keys is not counted as unchanged.
    """

    reference = _read_rows(reference_dir / "usc-act-sections.parquet")
    shared = {row["table3_key"] for row in reference}
    mine = [row for row in section_rows if row["table3_key"] in shared]

    def multiset(rows: list[dict[str, Any]]) -> Counter:
        return Counter(tuple(row.get(column) for column in ACT_SECTION_COLUMNS) for row in rows)

    theirs, ours = multiset(reference), multiset(mine)
    return {
        "reference": _repo_relative(reference_dir),
        "reference_rows": len(reference),
        "reference_table3_keys": len(shared),
        "table3_keys_present_here": len(shared & {row["table3_key"] for row in mine}),
        "rows_here_for_those_keys": len(mine),
        "rows_reproduced_identically": sum((theirs & ours).values()),
        "rows_only_in_reference": sum((theirs - ours).values()),
        "rows_only_here": sum((ours - theirs).values()),
    }


def build(
    output_dir: Path,
    *,
    zip_path: Path,
    popular_names_from: Path,
    compare_with: Path | None,
) -> dict:
    """Read the bulk file once and seal the artifact from it."""

    problems = verify_source(zip_path)
    if problems:
        raise SystemExit("refusing to build from an unpinned bulk source: " + "; ".join(problems))

    output_dir.mkdir(parents=True, exist_ok=True)
    quarantine: list[dict[str, Any]] = []
    section_rows: list[dict[str, Any]] = []

    acts = records = 0
    keys: Counter[str] = Counter()
    volumes_by_key: dict[str, set[str]] = {}
    congresses_by_key: dict[str, set[str]] = {}
    nonstandard_keys: Counter[str] = Counter()
    status_prefixes: Counter[str] = Counter()
    status_values: set[str] = set()
    not_carried: Counter[str] = Counter()
    narrowed = unreadable_page = without_act_section = page_spans_stated = 0

    for act in iter_bulk_acts(zip_path):
        acts += 1
        keys[act.table3_key] += 1
        volumes_by_key.setdefault(act.table3_key, set()).add(act.statutes_at_large_volume)
        congresses_by_key.setdefault(act.table3_key, set()).add(act.congress)
        if not _TABLE3_KEY_SHAPE.fullmatch(act.table3_key):
            nonstandard_keys[act.table3_key] += 1
        for attribute in _NOT_CARRIED_ACT:
            not_carried[f"act/@{attribute}"] += 1
        for record in act.records:
            records += 1
            for attribute in _NOT_CARRIED_RECORD:
                not_carried[f"record/@{attribute}"] += 1
            if record.status:
                status_values.add(record.status)
                status_prefixes[record.status.split()[0]] += 1
            if not record.act_section:
                # No act section is no key: Table III answers "which section of
                # WHICH act", and this record names only the second half. Its
                # page is never narrowed -- there is no row to narrow it INTO
                # -- but a span stated here is still part of the 20,809, so it
                # is counted before the row is quarantined out of reach.
                without_act_section += 1
                if record.statutes_at_large_page is not None and _is_stated_span(record.statutes_at_large_page):
                    page_spans_stated += 1
                quarantine.append(
                    {
                        "source": "table3_bulk_xml",
                        "reason": "record_without_act_section",
                        "table3_key": act.table3_key,
                        "raw_value": canonical_json(
                            {
                                "statutes_at_large_page": record.statutes_at_large_page,
                                "usc_title": record.usc_title,
                                "usc_section": record.usc_section,
                                "status": record.status,
                            }
                        ),
                    }
                )
                continue
            page = record.statutes_at_large_page
            if page is not None:
                first = _FIRST_PAGE.match(page)
                if first is None:
                    unreadable_page += 1
                    quarantine.append(
                        {
                            "source": "table3_bulk_xml",
                            "reason": "statutes_at_large_page_unreadable",
                            "table3_key": act.table3_key,
                            "raw_value": f"{record.act_section} -> {page}",
                        }
                    )
                    page = None
                elif _is_stated_span(page):
                    narrowed += 1
                    page_spans_stated += 1
                    quarantine.append(
                        {
                            "source": "table3_bulk_xml",
                            "reason": "statutes_at_large_page_span_narrowed",
                            "table3_key": act.table3_key,
                            "raw_value": f"{record.act_section} -> {page}",
                        }
                    )
                    page = first.group(1)
                else:
                    page = first.group(1)
            section_rows.append(
                {
                    "table3_key": act.table3_key,
                    "act_section": record.act_section,
                    "usc_title": record.usc_title,
                    "usc_section": record.usc_section,
                    "status": record.status,
                    "statutes_at_large_volume": act.statutes_at_large_volume,
                    "statutes_at_large_page": page,
                }
            )

    name_rows = _read_rows(popular_names_from / "usc-popular-names.parquet")
    # Every table3_key any "cite" row states, as a SET -- order-free by
    # construction, and deliberately not a per-name resolution. 34 of the
    # table's name_keys name two different table3_keys each ('detainee
    # treatment act of 2005' -> {109-148, 109-163}), which is real ambiguity
    # in the source; picking a winner per name is ActIndex.from_artifact's
    # job, done at query time with its own alias-chasing, and a private
    # setdefault restating that choice here previously made this count move
    # with parquet row order (8,391 by file order, 8,392 by a sorted
    # tie-break) while also reading the STORED name_key rather than the
    # normalized one ActIndex now keys by.
    index_keys = {row["table3_key"] for row in name_rows if row["content_type"] == "cite" and row["table3_key"]}

    _scan_for_secrets(section_rows, "usc-act-sections")
    _scan_for_secrets(quarantine, "quarantine")

    names_path = output_dir / "usc-popular-names.parquet"
    sections_path = output_dir / "usc-act-sections.parquet"
    quarantine_path = output_dir / "quarantine.parquet"
    shutil.copyfile(popular_names_from / "usc-popular-names.parquet", names_path)
    _write_parquet(sections_path, ACT_SECTION_COLUMNS, section_rows)
    _write_parquet(quarantine_path, QUARANTINE_COLUMNS, quarantine)

    carried_receipt = json.loads((popular_names_from / "receipt.json").read_text(encoding="utf-8"))
    reached = {row["table3_key"] for row in section_rows}
    receipt = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "coverage": {
            "acts_requested": len(keys),
            "acts_reached": len(reached),
            "acts_incomplete": 0,
            "popular_name_rows": len(name_rows),
            "distinct_names": len({row["name_key"] for row in name_rows}),
            "act_section_rows": len(section_rows),
            "act_section_rows_with_stat_page": sum(1 for row in section_rows if row["statutes_at_large_page"]),
            "acts_with_division": sum(1 for row in name_rows if row["division"]),
            "quarantine_rows": len(quarantine),
            "quarantine_reasons": dict(sorted(Counter(row["reason"] for row in quarantine).items())),
        },
        # Nothing failed to be read: the source is one local file that either
        # parses whole or fails the build. The key is kept so a consumer's
        # `incomplete_sources` has the same shape it has for the 08-02 artifact
        # -- and its emptiness is the finding that Pub. L. 119-21, the one page
        # the per-page build could not fetch, is in this file.
        "source_incomplete": [],
        "inputs": {
            "bulk_source": BULK_SOURCE,
            "bulk_source_digest": BULK_SOURCE_DIGEST,
            "bulk_source_bytes": BULK_SOURCE_BYTES,
            "bulk_member": BULK_MEMBER,
            "bulk_member_bytes": BULK_MEMBER_BYTES,
            "bulk_release_point": BULK_RELEASE_POINT,
            "popular_names_carried_from": _repo_relative(popular_names_from),
            "popular_names_digest": file_sha256(names_path),
            "popular_names_url": carried_receipt["inputs"]["popular_names_url"],
            "popular_names_source_digest": carried_receipt["inputs"]["popular_names_digest"],
            "popular_names_release_point": sorted(
                {row["release_point"] for row in name_rows if row["release_point"]}
            ),
        },
        "measured": {
            "bulk_act_elements": acts,
            "bulk_record_elements": records,
            "bulk_distinct_table3_keys": len(keys),
            "table3_keys_stated_by_more_than_one_act_element": sum(1 for count in keys.values() if count > 1),
            # A key whose every record states a U.S. Code target but no act
            # section classifies nothing Table III can be ASKED about, since a
            # lookup is (key, act section). Counted, because "reached 15,189 of
            # 23,147" is otherwise an unexplained subtraction.
            "table3_keys_classifying_no_keyable_record": len(keys) - len(reached),
            "records_without_act_section": without_act_section,
            # Every record stating a page SPAN, whether or not it has an
            # <act-section> to be narrowed into a kept row. The narrower field
            # below is the subset that does; the gap between the two is the
            # count already quarantined as `record_without_act_section`.
            "page_spans_stated": page_spans_stated,
            "page_spans_narrowed_to_first_page": narrowed,
            "pages_unreadable": unreadable_page,
            # OLRC states 210 Public Resolution keys the Table III URL grammar
            # cannot spell. They are CARRIED, not refused -- they are real
            # classifications -- and counted here because no popular name
            # reaches them.
            "table3_keys_outside_the_url_grammar": len(nonstandard_keys),
            "acts_outside_the_url_grammar": sum(nonstandard_keys.values()),
            "table3_keys_outside_the_url_grammar_sample": sorted(nonstandard_keys)[:5],
            # A year:chapter key is not unique across sessions: 49 keys are
            # stated by acts in two Statutes at Large volumes -- '1813:18' is
            # in volumes 2 and 3. The popular-name table uses the same
            # spelling, so this is the source's ambiguity, not this build's --
            # named so a consumer can see it.
            "table3_keys_spanning_two_statutes_at_large_volumes": sum(
                1 for volumes in volumes_by_key.values() if len(volumes) > 1
            ),
            # A SEPARATE 49, over a SEPARATE condition -- not the same 49 keys
            # under another name. The two sets differ by six each way: 1939:2,
            # 1954:736, 87-845, 93-107, 98-47 and 98-53 span two volumes but
            # one Congress; 1797:7, 1837:1, 1861:20, 1861:49, 1861:59 and
            # 1861:60 span two Congresses but one volume. The four
            # public-law-shaped keys in the first group are not a
            # year:chapter collision at all -- OLRC states two <act> elements
            # for that one law, and the elements disagree with each other
            # about which Statutes at Large volume it is in (87-845: '76' and
            # '76A'), so the sealed table carries both.
            "table3_keys_spanning_two_congresses": sum(
                1 for congresses in congresses_by_key.values() if len(congresses) > 1
            ),
            "status_values_distinct": len(status_values),
            "status_value_prefixes": dict(sorted(status_prefixes.items(), key=lambda item: (-item[1], item[0]))),
            "popular_name_cite_table3_keys": len(index_keys),
            "popular_name_cite_table3_keys_covered": len(index_keys & set(keys)),
            "popular_name_cite_table3_keys_absent": len(index_keys - set(keys)),
            # Read but uncarryable: the sealed columns have nowhere to put
            # these, and a consumer is owed the count rather than the silence.
            "stated_but_not_carried": dict(sorted(not_carried.items())),
        },
        "rules": {
            **carried_receipt["rules"],
            "coverage_selection": "every-act-the-bulk-release-states-v1",
            "coverage_selection_derivation": (
                "the per-page ancestor asked for the acts one corpus cited, so `acts_requested` "
                "was 27; this build reads one local file and asks for nothing, so the same field "
                "counts every Table III key the release states (23,147) and `acts_reached` counts "
                "those with at least one record this schema can key"
            ),
            "table3_key_rule": TABLE3_KEY_RULE,
            "table3_key_rule_derivation": (
                "the Table III key is OLRC's own search-key attribute, with a pre-1957 act's full "
                "enactment date narrowed to its year because that is the spelling the Popular Name "
                "Tool joins on ('1948-06-30:758' -> '1948:758'). Re-deriving the key from <num> "
                "instead reads the 1956 session-law chapter 78-80 as Public Law 78-80, which "
                "search-key ('1956-03-02:78-80') states plainly that it is not"
            ),
            "page_span_rule": PAGE_SPAN_RULE,
            "page_span_rule_derivation": (
                "20,809 records state a page SPAN ('3440, 3441', '1007-1009'). 20,371 of them have "
                "an <act-section>, so the column is read as one integer by the consumer, the row "
                "keeps the span's first page -- the page the classification begins on -- and the "
                "verbatim span is written to quarantine.parquet under "
                "statutes_at_large_page_span_narrowed, counted here, and lost by nobody. The other "
                "438 have no <act-section> at all, so they were already quarantined as "
                "record_without_act_section -- span text and all -- before the page column is ever "
                "read"
            ),
            "well_formedness_defect": BULK_WELL_FORMEDNESS_DEFECT,
            "well_formedness_defect_derivation": (
                "the member is a bare concatenation of sibling <act> elements with no XML "
                "declaration and no wrapping root, so the SECOND <act> is junk after the document "
                "element; ElementTree.parse and ElementTree.iterparse both refuse the whole file, "
                "and the reader splits on </act> and checks that every byte between two fragments "
                "is whitespace"
            ),
        },
        "outputs": {
            _repo_relative(path): {"digest": file_sha256(path), "rows": len(rows)}
            for path, rows in ((names_path, name_rows), (sections_path, section_rows), (quarantine_path, quarantine))
        },
    }
    if compare_with is not None:
        receipt["reproduction"] = _compare_with(compare_with, section_rows)
    receipt_text = canonical_json(receipt)
    if _SECRET_LIKE.search(receipt_text):
        raise SystemExit("refusing to seal a secret-like value in receipt.json")
    (output_dir / "receipt.json").write_text(receipt_text, encoding="utf-8")
    return receipt


def verify_artifact(output_dir: Path, *, zip_path: Path | None = None) -> list[str]:
    """Check the artifact on disk against its own receipt; name every failure."""

    import pyarrow.parquet as pq

    output_dir = Path(output_dir)
    receipt_path = output_dir / "receipt.json"
    if not receipt_path.is_file():
        return [f"no receipt at {receipt_path}"]
    recorded = json.loads(receipt_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if recorded.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        problems.append(f"receipt declares schema_version {recorded.get('schema_version')!r}")
    if recorded.get("parser_version") != PARSER_VERSION:
        problems.append(f"receipt declares parser_version {recorded.get('parser_version')!r}")
    for stated, expected in (
        ("bulk_source_digest", BULK_SOURCE_DIGEST),
        ("bulk_source_bytes", BULK_SOURCE_BYTES),
        ("bulk_member", BULK_MEMBER),
        ("bulk_member_bytes", BULK_MEMBER_BYTES),
    ):
        if recorded.get("inputs", {}).get(stated) != expected:
            problems.append(f"receipt states {stated}={recorded.get('inputs', {}).get(stated)!r}, pinned {expected!r}")
    expected_columns = {
        "usc-popular-names.parquet": POPULAR_NAME_COLUMNS,
        "usc-act-sections.parquet": ACT_SECTION_COLUMNS,
        "quarantine.parquet": QUARANTINE_COLUMNS,
    }
    for stated_path, meta in sorted(recorded.get("outputs", {}).items()):
        path = output_dir / Path(stated_path).name
        if not path.is_file():
            problems.append(f"missing table file: {path.name}")
            continue
        observed = file_sha256(path)
        if observed != meta["digest"]:
            # Named and then left alone. Bytes the receipt disowns are not this
            # artifact's, and reading them would raise where a verifier owes a
            # message: a truncated parquet is not even a parquet.
            problems.append(f"{path.name} drifted: expected {meta['digest']}, observed {observed}")
            continue
        schema = pq.read_schema(path)
        columns = expected_columns.get(path.name)
        if columns is not None and tuple(schema.names) != columns:
            problems.append(f"{path.name} columns are {tuple(schema.names)}, expected {columns}")
        if columns is not None and any(str(schema.field(name).type) != "string" for name in schema.names):
            problems.append(f"{path.name} has a non-string column: {schema}")
        rows = pq.ParquetFile(path).metadata.num_rows
        if rows != meta["rows"]:
            problems.append(f"{path.name} has {rows} rows, receipted at {meta['rows']}")
    coverage = recorded.get("coverage", {})
    sections = output_dir / "usc-act-sections.parquet"
    # Only over bytes the digest already vouched for; a file the loop above
    # named as drifted has nothing left to say about coverage.
    if (
        sections.is_file()
        and not any(sections.name in problem for problem in problems)
        and coverage.get("act_section_rows") != pq.ParquetFile(sections).metadata.num_rows
    ):
        problems.append("receipt coverage.act_section_rows disagrees with the sealed table")
    if zip_path is not None:
        problems.extend(verify_source(zip_path))
    return problems


def main(argv: list[str] | None = None) -> int:
    """Build (default) or verify the U.S. Code act index from OLRC's bulk Table III.

    ``python -m refspec.registry.usc_act_index`` reads
    ``olrc-table3-xml-bulk-119-73.zip`` once, carries the popular-name table
    over from the artifact ``--popular-names-from`` names, and writes the three
    tables and the receipt. ``--verify`` re-hashes what is on disk against that
    receipt and builds nothing. Neither path reaches the network.
    """

    import argparse

    parser = argparse.ArgumentParser(description=(main.__doc__ or "").splitlines()[0])
    parser.add_argument("--output", type=Path, default=_REPO_ROOT / "output/usc-act-index-2026-08-22")
    parser.add_argument("--bulk-source", type=Path, default=_REPO_ROOT / BULK_SOURCE)
    parser.add_argument(
        "--popular-names-from",
        type=Path,
        default=_REPO_ROOT / "output/usc-act-index-2026-08-02",
        help="sealed artifact whose usc-popular-names.parquet is carried over unchanged",
    )
    parser.add_argument(
        "--compare-with",
        type=Path,
        default=_REPO_ROOT / "output/usc-act-index-2026-08-02",
        help="sealed artifact whose Table III rows this build's reproduction is measured against",
    )
    parser.add_argument("--verify", action="store_true", help="verify the artifact against its receipt")
    args = parser.parse_args(argv)

    if args.verify:
        problems = verify_artifact(args.output, zip_path=args.bulk_source)
        for problem in problems:
            print(f"FAIL  {problem}")
        if not problems:
            print(f"PASS  artifact at {args.output} matches its receipt")
        return 1 if problems else 0

    receipt = build(
        args.output,
        zip_path=args.bulk_source,
        popular_names_from=args.popular_names_from,
        compare_with=args.compare_with,
    )
    print(json.dumps(receipt["coverage"], indent=2, sort_keys=True))
    print(json.dumps(receipt["measured"], indent=2, sort_keys=True))
    if "reproduction" in receipt:
        print(json.dumps(receipt["reproduction"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
