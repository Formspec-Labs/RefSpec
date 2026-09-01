"""Re-derive the Executive Order existence roster from committed raw bytes.

Reads ONLY raw publisher captures, each verified against a committed sha256
manifest (or, for this lane's own two captures, against a digest literal
below) BEFORE it is parsed -- never the derived CSVs those investigations
already produced. Those derived CSVs appear in exactly one place, as the
comparison oracle in :func:`diff_against_investigation`, which runs after the
derivation is complete and cannot influence it.

The five populations:

* the NARA codification-numeric window's existence set (18 raw index pages,
  ``inv-eo/nara/eo-01.html`` .. ``eo-18.html``);
* the 109 per-order detail-page probes (``inv-eo/nara/orders/eo-*.html``),
  which resolve title/date metadata for a subset of cited numbers and record
  NARA's own "not found" verdict where the publisher's per-order ROUTE has
  none -- a route fact, never an existence claim (EO 8284 is the specimen:
  its detail route 404s and its year table lists it, see README.md);
* the FR-API window's existence set (``inv-eo/fr-api/fr-executive-orders-
  page{1,2}.json``);
* the 1990-1993 gap closure (``inv-eo-gap/nara/{eo-1989-bush,eo-1990,eo-1991,
  eo-1992}.html`` -- live NARA disposition pages -- and
  ``.../wayback-1993-{bush,clinton}.html`` -- Wayback captures of the two
  NARA pages now dead on the live site);
* the NARA 1939 disposition table (``raw/nara-eo-1939.html``, fetched and
  pinned by THIS lane on 2026-08-31 to resolve EO 8284, whose per-order
  detail route 404s while the year table publishes it -- see README.md).

Membership is always taken from the raw bytes. Nothing in this script
intersects a raw extraction down to a derived file's row set: an earlier
draft did exactly that for the gap closure, and the intersection hid a
parser defect (EO 12825's entry swallowed EO 12826's) that the raw pages
themselves make plain.

Run: ``.venv/bin/python derive_roster.py`` from this directory, or any cwd
(paths are resolved from ``__file__``).
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime
from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
INV_EO = REPO_ROOT / "research/evidence/investigations-2026-08-24/inv-eo"
INV_EO_GAP = REPO_ROOT / "research/evidence/investigations-2026-08-24/inv-eo-gap"
RAW_DIR = HERE / "raw"
OUT_DIR = HERE / "derived"

#: Each raw-evidence root and the committed manifest that pins its bytes.
#: Both manifests spell their paths relative to their root.
_MANIFEST_OF = {
    INV_EO: INV_EO / "derived/MANIFEST-sha256.csv",
    INV_EO_GAP: INV_EO_GAP / "MANIFEST-sha256.csv",
}

#: This lane's OWN captures, pinned here by digest literal rather than by the
#: evidence home's MANIFEST-sha256.csv -- that manifest is written after this
#: script runs, so trusting it would let a re-fetch of different bytes pass
#: unnoticed. ``(bytes, sha256)``, both checked.
RAW_CAPTURES: dict[str, tuple[int, str]] = {
    "nara-eo-1939.html": (
        144_520,
        "6575dcd808f06c39def77e7411d50813bdb32edb7c9359bbdda9f309a037711a",
    ),
    "nara-eo-1939.headers.txt": (
        624,
        "d4eddf13645f32a97ca7567602311261a605442f5e07e316a145e14a9dbc1eac",
    ),
    "govinfo-FR-1939-11-17.pdf": (
        2_400_332,
        "9a6a961b3e327c92b85a9afeaff4dafbfacf3178007467e3f83c3f1313b25987",
    ),
    "govinfo-FR-1939-11-17.headers.txt": (
        1_930,
        "15cfbcb03e9920ebf3bf43280fd6d5abd7b7b5738c586f5e63348f9888ba110f",
    ),
}

_TAG = re.compile(r"<[^>]+>")
_ROW = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
_CELL = re.compile(r"<td>(.*?)</td>", re.DOTALL)
_TITLE_TAG = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_META_DESC = re.compile(r'<meta name="description" content="(.*?)" */?>', re.DOTALL)
_ORDER_DESC = re.compile(
    r"Executive Order \d+--(.*?) Source: The provisions of Executive Order \d+ of ([^,]+),"
)

#: One entry of a NARA disposition table. The entry's own named anchor -- not
#: the prose around it -- is what delimits an entry, so a malformed line
#: INSIDE one entry can never let it swallow the next. The regex-over-prose
#: parser this replaced required a well-formed "Federal Register page and
#: date" line, and EO 12825's is malformed ("57 FR 60973; 22, 1992", no
#: month), so its match ran on through EO 12826's whole entry and dropped
#: 12826 from the roster entirely.
#:
#: Anchored on the name attribute alone because NARA publishes these tables in
#: two markups: the current one puts the anchor inside the heading
#: (``<strong>Executive Order <a name="8284"></a>8284</strong>``), the older
#: one -- which the two Wayback-captured 1993 pages preserve -- puts it before
#: a heading that is itself a PDF link
#: (``<a name="12866"></a><strong><a href="...pdf">Executive Order 12866</a>``).
#: An entry id is digits, optionally one letter suffix ("8193-a"); nothing
#: else on these pages carries a named anchor.
_ENTRY_ANCHOR = re.compile(r'<a name="(\d+(?:-[A-Za-z])?)"></a>', re.IGNORECASE)
_LIST_ITEM = re.compile(r"<li>(.*?)(?:</li>|(?=<li>)|$)", re.DOTALL | re.IGNORECASE)
_SIGNED_DATE = re.compile(r"^([A-Za-z]+\.?\s+\d{1,2},\s+\d{4})")


class DerivationRefusal(RuntimeError):
    """A raw input failed its manifest check, so nothing is derived from it."""


# --------------------------------------------------------------------------- #
# Verified reads: no byte is parsed before it is checked
# --------------------------------------------------------------------------- #


@cache
def _manifest(root: Path) -> dict[str, tuple[int, str]]:
    """``relative_path -> (bytes, sha256)`` from the manifest committed for ``root``."""

    path = _MANIFEST_OF[root]
    with path.open(newline="") as handle:
        return {
            row["relative_path"]: (int(row["bytes"]), row["sha256"])
            for row in csv.DictReader(handle)
        }


def verified_bytes(root: Path, relative_path: str) -> bytes:
    """Read one manifested raw file, refusing unless its bytes match the manifest."""

    expected = _manifest(root).get(relative_path)
    if expected is None:
        raise DerivationRefusal(
            f"{relative_path} is not listed in {_MANIFEST_OF[root].relative_to(REPO_ROOT)}; "
            f"an unmanifested file is not evidence this script may parse"
        )
    payload = (root / relative_path).read_bytes()
    observed = (len(payload), hashlib.sha256(payload).hexdigest())
    if observed != expected:
        raise DerivationRefusal(
            f"{relative_path} drifted from its manifest: expected bytes={expected[0]} "
            f"sha256={expected[1]}, observed bytes={observed[0]} sha256={observed[1]}"
        )
    return payload


def verified_text(root: Path, relative_path: str) -> str:
    return verified_bytes(root, relative_path).decode("utf-8", errors="replace")


def verified_capture(name: str) -> bytes:
    """Read one of THIS lane's own captures, checked against its digest literal."""

    expected = RAW_CAPTURES[name]
    payload = (RAW_DIR / name).read_bytes()
    observed = (len(payload), hashlib.sha256(payload).hexdigest())
    if observed != expected:
        raise DerivationRefusal(
            f"raw/{name} drifted from its pin in RAW_CAPTURES: expected bytes={expected[0]} "
            f"sha256={expected[1]}, observed bytes={observed[0]} sha256={observed[1]}"
        )
    return payload


def manifested_glob(root: Path, pattern: str) -> list[str]:
    """Every path matching ``pattern`` under ``root``, refusing an unmanifested one.

    A glob is how an unreviewed file gets read by accident: drop one HTML page
    into ``nara/orders/`` and the old loop would have parsed it as evidence.
    Membership is taken from the directory (so a manifested-but-deleted file
    is caught by :func:`verified_bytes`) and every hit must be manifested.
    """

    listed = _manifest(root)
    found = sorted(str(path.relative_to(root)) for path in root.glob(pattern))
    unmanifested = [name for name in found if name not in listed]
    if unmanifested:
        raise DerivationRefusal(
            f"{len(unmanifested)} file(s) matching {pattern!r} under "
            f"{root.relative_to(REPO_ROOT)} are not in its manifest: {unmanifested[:5]}"
        )
    return found


# --------------------------------------------------------------------------- #
# Parsers -- each takes the verified text, never a path to re-open
# --------------------------------------------------------------------------- #


def _strip_tags(html: str) -> str:
    text = _TAG.sub(" ", html)
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_codification_index_page(html: str) -> set[int]:
    """Pure-numeric first-column entries from one NARA numeric-index page.

    Dates ("Feb. 9, 1849") and lettered/compound identifiers ("9-2", "108A",
    "199A", "325A", "357D") are excluded on purpose: they are addenda to a
    numbered order or unnumbered pre-1907 orders cited by date, never a
    distinct EO number a citation grammar could produce.
    """

    table_start = html.find("<table")
    numbers: set[int] = set()
    for row in _ROW.findall(html[table_start:]):
        cells = _CELL.findall(row)
        if not cells:
            continue
        first = _TAG.sub("", cells[0]).strip()
        if first.isdigit():
            numbers.add(int(first))
    return numbers


def parse_order_detail_page(name: str, html: str) -> tuple[int, bool, str | None, str | None]:
    """(eo_number, route_not_found, title, signing_date_text) from one detail page.

    ``route_not_found`` is read from the page's own ``<title>``: NARA serves a
    real "Page Not Found" document, not an HTTP-level 404, where its per-order
    route has no page for a number. It is a fact about that ROUTE and nothing
    else -- EO 8284's detail route 404s while NARA's own 1939 disposition
    table publishes the order in full (README.md). Title/date are best-effort
    (the description sentence has at least two templates across 90+ years of
    publishing) and are not part of any existence claim.
    """

    eo_number = int(re.search(r"eo-(\d+)\.html", name).group(1))
    title_tag_match = _TITLE_TAG.search(html)
    title_tag = title_tag_match.group(1) if title_tag_match else ""
    if "Page Not Found" in title_tag:
        return eo_number, True, None, None
    desc_match = _META_DESC.search(html)
    desc = desc_match.group(1) if desc_match else ""
    order_match = _ORDER_DESC.match(desc)
    if order_match:
        return eo_number, False, order_match.group(1), order_match.group(2)
    return eo_number, False, None, None


def parse_fr_api_page(payload: bytes) -> dict[int, dict]:
    """eo_number -> latest FR-API record. Records with no assigned number

    (``executive_order_number`` null -- 22 across both pages, e.g. emergency
    "Notices" and one Military Order that the API's executive_order document
    type nonetheless returns) are skipped: they carry no number to roster.
    """

    data = json.loads(payload)
    out: dict[int, dict] = {}
    for record in data["results"]:
        number = record.get("executive_order_number")
        if number is None:
            continue
        out[int(number)] = record
    return out


def parse_disposition_page(html: str) -> dict[int, dict[str, str | None]]:
    """eo_number -> {title, signing_date_text, fr_citation} from one NARA

    disposition table (a per-year or per-president page, live or Wayback-
    captured). Anchor-delimited: see :data:`_ENTRY_ANCHOR` on why the entry
    boundary must not be the prose. Lettered anchors ("8193-a") are skipped
    for the same reason the numeric index skips them -- an addendum to a
    numbered order is not a distinct number a citation grammar can produce.
    """

    anchors = list(_ENTRY_ANCHOR.finditer(html))
    out: dict[int, dict[str, str | None]] = {}
    for index, match in enumerate(anchors):
        anchor = match.group(1)
        if not anchor.isdigit():
            continue
        end = anchors[index + 1].start() if index + 1 < len(anchors) else len(html)
        segment = html[match.end() : end]
        number = int(anchor)
        head = _strip_tags(segment.split("<ul", 1)[0])
        title = re.sub(rf"^(?:Executive\s+Order\s+)?{number}\b\s*", "", head).strip(" -–—")
        fields: dict[str, str | None] = {"title": title or None, "signing_date_text": None, "fr_citation": None}
        for item in (_strip_tags(raw) for raw in _LIST_ITEM.findall(segment.split("</ul", 1)[0])):
            if item.startswith("Signed:"):
                signed = item.removeprefix("Signed:").strip()
                found = _SIGNED_DATE.match(signed)
                fields["signing_date_text"] = found.group(1) if found else signed or None
            elif item.startswith("Federal Register page and date:"):
                fields["fr_citation"] = item.removeprefix("Federal Register page and date:").strip() or None
        out[number] = fields
    return out


def _iso_date(text: str | None) -> str:
    """A signing DATE, not an instant -- parsed and reformatted as a calendar

    string with no timezone attached, because a date NARA prints has none.
    """

    if not text:
        return ""
    cleaned = text.replace(".", "").strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")  # noqa: DTZ007
        except ValueError:
            continue
    return ""


# --------------------------------------------------------------------------- #
# The derivation
# --------------------------------------------------------------------------- #

#: The gap-closure captures, and the durability profile of each. A Wayback
#: capture is pinned publisher evidence, not prunable research: both 1993
#: routes are dead on the live site today.
GAP_SOURCES = (
    ("nara-live", "nara/eo-1989-bush.html"),
    ("nara-live", "nara/eo-1990.html"),
    ("nara-live", "nara/eo-1991.html"),
    ("nara-live", "nara/eo-1992.html"),
    ("wayback", "nara/wayback-1993-bush.html"),
    ("wayback", "nara/wayback-1993-clinton.html"),
)

#: Merge priority, weakest first: a number witnessed by several captures is
#: tagged with the last one that carries it. A bare numeric-index entry is
#: the weakest witness (a number and nothing else); a structured FR-API
#: record is the strongest.
SOURCE_PRIORITY = (
    "nara-codification-index",
    "nara-order-detail-probe",
    "nara-disposition-1939",
    "gap-closure-nara-live",
    "gap-closure-wayback",
    "fr-api",
)


def derive() -> dict[str, object]:
    """Run every parser over verified bytes and return the derived tables."""

    # 1. NARA codification-numeric index, 18 raw pages.
    index_by_page: dict[int, set[int]] = {}
    for page_num in range(1, 19):
        relative = f"nara/eo-{page_num:02d}.html"
        index_by_page[page_num] = parse_codification_index_page(verified_text(INV_EO, relative))
    index_numbers = set().union(*index_by_page.values())

    # 2. NARA per-order detail-page probes.
    probes: dict[int, tuple[bool, str | None, str | None]] = {}
    for relative in manifested_glob(INV_EO, "nara/orders/eo-*.html"):
        number, not_found, title, date = parse_order_detail_page(
            relative, verified_text(INV_EO, relative)
        )
        probes[number] = (not_found, title, date)
    probe_ok = {n: v for n, v in probes.items() if not v[0]}
    probe_route_404 = {n: v for n, v in probes.items() if v[0]}

    # 3. FR-API window, 2 raw JSON pages.
    fr_api: dict[int, dict] = {}
    for name in ("fr-api/fr-executive-orders-page1.json", "fr-api/fr-executive-orders-page2.json"):
        fr_api.update(parse_fr_api_page(verified_bytes(INV_EO, name)))

    # 4. 1990-1993 gap closure: 4 live pages + 2 Wayback captures. Membership
    # is every anchor these pages carry -- no intersection with the
    # investigation's own eo-gap.csv, which is a derived file and appears
    # only in the comparison below.
    gap: dict[int, dict] = {}
    for kind, relative in GAP_SOURCES:
        for number, fields in parse_disposition_page(verified_text(INV_EO_GAP, relative)).items():
            gap[number] = {
                "title": fields["title"] or "",
                "signing_date": _iso_date(fields["signing_date_text"]),
                "fr_citation": fields["fr_citation"] or "",
                "provenance": kind,
                "source_file": Path(relative).name,
            }

    # 5. NARA's 1939 disposition table -- this lane's own pinned capture. It
    # is here because EO 8284's per-order detail route 404s while this table
    # publishes the order (README.md); admitting the capture whole, rather
    # than lifting one number out of it, is what keeps the roster a
    # derivation instead of a hand edit.
    disposition_1939: dict[int, dict] = {}
    for number, fields in parse_disposition_page(
        verified_capture("nara-eo-1939.html").decode("utf-8", errors="replace")
    ).items():
        disposition_1939[number] = {
            "title": fields["title"] or "",
            "signing_date": _iso_date(fields["signing_date_text"]),
            "fr_citation": fields["fr_citation"] or "",
        }

    return {
        "index_by_page": index_by_page,
        "index_numbers": index_numbers,
        "probe_ok": probe_ok,
        "probe_route_404": probe_route_404,
        "fr_api": fr_api,
        "gap": gap,
        "disposition_1939": disposition_1939,
    }


def merge_roster(derived: dict[str, object]) -> dict[int, str]:
    """``eo_number -> source``, the existence-only union of every population."""

    contributions: dict[str, list[int]] = {
        "nara-codification-index": sorted(derived["index_numbers"]),
        "nara-order-detail-probe": sorted(derived["probe_ok"]),
        "nara-disposition-1939": sorted(derived["disposition_1939"]),
        "gap-closure-nara-live": sorted(
            n for n, v in derived["gap"].items() if v["provenance"] == "nara-live"
        ),
        "gap-closure-wayback": sorted(
            n for n, v in derived["gap"].items() if v["provenance"] == "wayback"
        ),
        "fr-api": sorted(derived["fr_api"]),
    }
    merged: dict[int, str] = {}
    for source in SOURCE_PRIORITY:
        for number in contributions[source]:
            merged[number] = source
    return merged


def source_ranges(merged: dict[int, str]) -> dict[str, tuple[int, int]]:
    """The min/max each source actually attains in the merged roster.

    ``src/refspec/registry/eo_roster.py`` restates these as literals and
    verifies them at load, so an ``exists`` verdict can be refused when its
    number falls outside the range of the capture that supposedly witnessed
    it. Printed by ``__main__`` so re-pinning them is a copy, not a guess.
    """

    ranges: dict[str, tuple[int, int]] = {}
    for number, source in merged.items():
        low, high = ranges.get(source, (number, number))
        ranges[source] = (min(low, number), max(high, number))
    return {source: ranges[source] for source in SOURCE_PRIORITY if source in ranges}


#: The declared windows, restated from ``src/refspec/registry/eo_roster.py``
#: so this script writes the same ``window`` column that module verifies.
WINDOWS = (
    ("nara_codification", 9, 12_667),
    ("nara_disposition", 12_668, 12_889),
    ("fr_api", 12_890, 14_420),
)


def window_for(number: int) -> str | None:
    for name, low, high in WINDOWS:
        if low <= number <= high:
            return name
    return None


def write_outputs(derived: dict[str, object], merged: dict[int, str]) -> None:
    OUT_DIR.mkdir(exist_ok=True)

    with (OUT_DIR / "nara-codification-index-numbers.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["eo_number", "page"])
        for page_num, numbers in sorted(derived["index_by_page"].items()):
            for number in sorted(numbers):
                w.writerow([number, page_num])

    with (OUT_DIR / "nara-order-probe.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["eo_number", "route_not_found", "title", "signing_date_text"])
        probes = {**derived["probe_ok"], **derived["probe_route_404"]}
        for number in sorted(probes):
            not_found = number in derived["probe_route_404"]
            title, date = (None, None) if not_found else probes[number][1:]
            w.writerow([number, not_found, title or "", date or ""])

    with (OUT_DIR / "fr-api-numbers.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["eo_number", "title", "signing_date", "president", "citation"])
        for number, rec in sorted(derived["fr_api"].items()):
            w.writerow(
                [
                    number,
                    rec.get("title") or "",
                    rec.get("signing_date") or "",
                    (rec.get("president") or {}).get("name") or "",
                    rec.get("citation") or "",
                ]
            )

    with (OUT_DIR / "gap-numbers.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["eo_number", "signing_date", "title", "fr_citation", "provenance", "source_file"])
        for number, rec in sorted(derived["gap"].items()):
            w.writerow(
                [number, rec["signing_date"], rec["title"], rec["fr_citation"], rec["provenance"], rec["source_file"]]
            )

    with (OUT_DIR / "nara-disposition-1939.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["eo_number", "signing_date", "title", "fr_citation"])
        for number, rec in sorted(derived["disposition_1939"].items()):
            w.writerow([number, rec["signing_date"], rec["title"], rec["fr_citation"]])

    # The merged roster: existence-only union, one row per number, tagged with
    # the window that contains it and the capture that witnessed it. This is
    # what ``src/refspec/registry/eo_roster.py`` pins by sha256.
    with (OUT_DIR / "roster.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["eo_number", "window", "source"])
        for number in sorted(merged):
            w.writerow([number, window_for(number), merged[number]])


# --------------------------------------------------------------------------- #
# The comparison oracle: the investigation's own derived CSVs, read only here
# --------------------------------------------------------------------------- #


def diff_against_investigation(derived: dict[str, object], merged: dict[int, str]) -> list[str]:
    """Compare the finished re-derivation to the investigation's derived CSVs.

    Every difference below is expected and named. A difference this function
    does NOT name is drift.
    """

    lines: list[str] = []

    def read_numbers(root: Path, relative: str, column: str) -> set[int]:
        text = verified_text(root, relative).splitlines()
        return {int(row[column]) for row in csv.DictReader(text)}

    # NARA codification-numeric index: exact set match expected.
    mine = set().union(*derived["index_by_page"].values())
    theirs = read_numbers(INV_EO, "derived/nara-codification-index.csv", "eo_number")
    lines.append(f"nara-codification-index: mine={len(mine)} theirs={len(theirs)} match={mine == theirs}")
    if mine != theirs:
        lines.append(f"  mine-theirs={sorted(mine - theirs)}")
        lines.append(f"  theirs-mine={sorted(theirs - mine)}")

    # NARA per-order probes: the route verdict must match for every number.
    theirs_probe = {
        int(row["eo_number"]): row["not_found"] == "True"
        for row in csv.DictReader(verified_text(INV_EO, "derived/nara-order-details.csv").splitlines())
    }
    mine_probe = dict.fromkeys(derived["probe_ok"], False) | dict.fromkeys(derived["probe_route_404"], True)
    mismatches = [n for n in theirs_probe if mine_probe.get(n) != theirs_probe[n]]
    lines.append(
        f"nara-order-probe route verdicts: {len(theirs_probe)} probed, "
        f"{len(mismatches)} mismatches: {mismatches}"
    )

    # FR-API numbers: exact set match expected.
    mine = set(derived["fr_api"])
    theirs = {
        int(row["eo_number"])
        for row in csv.DictReader(verified_text(INV_EO, "derived/eo-roster.csv").splitlines())
        if row["source"] == "fr-api"
    }
    lines.append(f"fr-api: mine={len(mine)} theirs={len(theirs)} match={mine == theirs}")
    if mine != theirs:
        lines.append(f"  mine-theirs={sorted(mine - theirs)}")
        lines.append(f"  theirs-mine={sorted(theirs - mine)}")

    # Gap closure: the investigation pinned the 32 numbers its corpus cites in
    # the dead zone; membership here comes from the raw pages, which enumerate
    # the whole contiguous run. The 32 must be a SUBSET and field-exact.
    theirs_gap = {
        int(row["eo_number"]): row
        for row in csv.DictReader(verified_text(INV_EO_GAP, "eo-gap.csv").splitlines())
    }
    mine_gap = derived["gap"]
    covered = set(theirs_gap) <= set(mine_gap)
    numbers = sorted(mine_gap)
    contiguous = numbers == list(range(numbers[0], numbers[-1] + 1))
    lines.append(
        f"gap-closure: mine={len(mine_gap)} [{numbers[0]}-{numbers[-1]}, contiguous={contiguous}] "
        f"theirs={len(theirs_gap)} covers-theirs={covered}"
    )
    field_mismatches = []
    for number, theirs_row in theirs_gap.items():
        mine_row = mine_gap.get(number)
        if mine_row is None:
            field_mismatches.append((number, "missing"))
            continue
        if mine_row["title"] != theirs_row["title"]:
            field_mismatches.append((number, "title"))
        if mine_row["signing_date"] != theirs_row["signing_date"]:
            field_mismatches.append((number, "signing_date"))
        if (mine_row["provenance"] == "wayback") != ("web.archive.org" in theirs_row["source_url"]):
            field_mismatches.append((number, "provenance"))
    lines.append(f"gap-closure field mismatches: {len(field_mismatches)} {field_mismatches}")

    # Overall roster. Two deliberate deltas, both named here so an unnamed
    # one is drift: the gap captures' full anchor set, and EO 8284 from this
    # lane's 1939 capture.
    theirs_roster = read_numbers(INV_EO, "derived/eo-roster.csv", "eo_number")
    theirs_all = theirs_roster | set(theirs_gap)
    mine_all = set(merged)
    added = sorted(mine_all - theirs_all)
    lost = sorted(theirs_all - mine_all)
    in_gap_run = [n for n in added if numbers[0] <= n <= numbers[-1]]
    from_1939 = [n for n in added if n in derived["disposition_1939"] and n not in in_gap_run]
    unexplained = sorted(set(added) - set(in_gap_run) - set(from_1939))
    lines.append(
        f"merged roster: mine={len(mine_all)} theirs(roster|gap)={len(theirs_all)} "
        f"lost={lost} added={len(added)}"
    )
    lines.append(
        f"  added, explained: {len(in_gap_run)} from the gap captures' full anchor set, "
        f"{len(from_1939)} from the pinned NARA 1939 disposition table"
    )
    lines.append(f"  added, UNEXPLAINED (expect empty): {unexplained}")
    lines.append(
        f"  EO 8284: on the roster={8284 in merged} source={merged.get(8284)} "
        f"(its per-order detail route 404s; the 1939 year table publishes it)"
    )
    return lines


if __name__ == "__main__":
    derived = derive()
    merged = merge_roster(derived)
    write_outputs(derived, merged)
    report = diff_against_investigation(derived, merged)
    report.append("source ranges (restate these in eo_roster.SOURCE_RANGES):")
    for source, (low, high) in source_ranges(merged).items():
        report.append(f"  {source}: ({low}, {high})")
    (HERE / "diff-report.txt").write_text("\n".join(report) + "\n")
    for line in report:
        print(line)
