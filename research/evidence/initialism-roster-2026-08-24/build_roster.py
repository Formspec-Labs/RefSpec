"""Derive ``roster.csv`` from the 2026-08-23 initialism investigation.

The investigation left one file, ``initialisms.csv``, with a single ``status``
column that lumped every kind of evidence under the word "pinned" — a live
publisher quote and "the full name the investigator hypothesised resolves in
the index" sat in the same bucket. Those are not the same claim, and a rule
that treated them alike would be spending the second one's 15.25% wrong-survivor
rate on rows the first one earned honestly. This script splits them, keys every
row by the agency whose filings the evidence was gathered from, and checks each
act name against the pinned act index before it will write it.

    uv run python research/evidence/initialism-roster-2026-08-24/build_roster.py \
        [--artifact <dir with unified_agenda_legal_authorities.parquet>]

Deterministic: no clock, no network. The ``rows_observed`` column is the only
thing the artifact is read for, and the README names the build it was measured
on. Without ``--artifact`` the column is written empty and everything else is
identical.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from refspec.registry.act_resolution import ActIndex, resolve_act_name  # noqa: E402
from refspec.registry.citation_grammar import normalize_popular_name  # noqa: E402

SOURCE = REPO / "research/evidence/investigations-2026-08-23/inv-initialisms/initialisms.csv"
RAW = "research/evidence/investigations-2026-08-23/inv-initialisms/raw"
ACT_INDEX = REPO / "output/usc-act-index-2026-08-22"
#: The pinned act index is itself an in-repo, digest-carrying receipt, and it is
#: what every ``candidate-index-match`` row cites: the claim such a row makes is
#: exactly "this name is listed in that artifact", which the artifact settles.
ACT_INDEX_EVIDENCE = "output/usc-act-index-2026-08-22/usc-popular-names.parquet"

#: Which committed receipt carries the quote a ``pinned-quote`` row cites. The
#: Federal Register bodies are stored verbatim under ``raw/``; the OLRC popular
#: names page is NOT (14 MB of HTML), so its two rows cite the fetch's own HTTP
#: response headers, which ARE committed, and repeat the digest the
#: investigation recorded for the body in ``SHA256SUMS.txt``.
QUOTE_RECEIPTS: dict[str, tuple[str, str]] = {
    "BBRA": (f"{RAW}/fr_BBRA_2000.json", "8cf0638c3a0f3db0fd8fa5954fd1a48c204b4b422784788b50994c9bee61eeee"),
    "FD&C": (f"{RAW}/fr_FDC_quote.json", "7f38ae523deb08e9d1372370bb37d93d4b9eeb136d2cc53b0eb01ea71773100d"),
    "HSIA": (f"{RAW}/fr_HSIA_2024-15790.xml", "b2cce2bb44de9b04a963a7f5ca2aade8a54e5db12e715783d8dd4b0ba99cd489"),
    "IIJA": (f"{RAW}/fr_IIJA_phrase.json", "f4aadd3e78385c0be8bb62a09338039d39a8657a451d2228de16c7af2f88b8ec"),
    "PHS": (f"{RAW}/fr_PHS_search.json", "f081cd2f42ce708f084c11aad45958e3147b9149714b318621212146bfdba746"),
    "SMART": (f"{RAW}/fr_SMART_named.json", "20af5dca25add9226869db113fb123e4987e9c879e1e8a46251ccdc21b7d9990"),
    "TEA-21": (f"{RAW}/fr_TEA21_1998.json", "d54746d6362138e1b2d88562d8ca7047b8242f4030613f4141c1b8f3641e82b0"),
    "LU": (f"{RAW}/popularnames.headers.txt", "7cbacdbcea8834be6591226dfc8c0f1714bbf7006a0b2dff300f3112f1c26489"),
    "SAFTEA": (f"{RAW}/popularnames.headers.txt", "7cbacdbcea8834be6591226dfc8c0f1714bbf7006a0b2dff300f3112f1c26489"),
}

#: A Public Law number written in the SAME authority text whose act's initials
#: are the token. The corpus states the law; the index states the law's name;
#: the two meet on the number, and nothing was hypothesised.
REVERSE_PL = {"FAA", "FAST", "FDASIA", "HIPAA", "PPAC", "PPACA", "PRWORA"}

#: The row itself spells the name beside the token — "Division B--REAL ID Act of
#: 2005", "North Pacific Halibut Act of 1982 (NPHA)". Testimony from the filer,
#: which is the posture ``_ACT_GLOSS`` already takes for "Name (ABBR)".
SELF_GLOSSING = {"ESSA", "IEEPA", "NPHA", "REAL", "USHA", "WSARA"}

#: Names the investigation wrote for a human that the index lists differently.
#: Each is verified below; none is a second reading of the evidence.
NAME_FIXES = {
    "FAST": "FAST Act",
    "HSIA": "Hydrographic Services Improvement Act of 1998",
    "LU": "Safe, Accountable, Flexible, Efficient Transportation Equity Act: A Legacy for Users",
    "SAFTEA": "Safe, Accountable, Flexible, Efficient Transportation Equity Act: A Legacy for Users",
    "MAP-21": "Moving Ahead for Progress in the 21st Century Act",
}

#: The eight tokens #45 keys by agency because the token means different things
#: at different filers. Written out rather than derived, because which agency
#: means which act is a finding, not a rule.
AGENCY_KEYED: dict[str, dict[str, tuple[str, str, str]]] = {
    # token -> agency -> (status, act name or "", note)
    "EPA": {
        "0596": ("candidate-index-match", "Energy Policy Act of 1992",
                 "the Forest Service writes 'EPA 1992'; the index lists the Energy Policy Act of 1992 at "
                 "102-486, and no document glossing 'EPA 1992' that way was found"),
        "2030": ("ambiguous", "",
                 "'EPA Acquisition Regulation sec 205' is the Environmental Protection Agency's own "
                 "procurement regulation — the agency, not an act"),
    },
    "MMA": {
        "0917": ("candidate-index-match", "Medicare Prescription Drug, Improvement, and Modernization Act of 2003",
                 "IHS writes 'MMA, sec 506'; one act survives at this agency"),
        "0938": ("candidate-index-match", "Medicare Prescription Drug, Improvement, and Modernization Act of 2003",
                 "CMS's own roster reaches three Medicare acts by these initials and the builder refuses "
                 "the row on that count — this entry never overrides that refusal"),
    },
    "SAFE": {
        "1515": ("self-glossing", "Security and Accountability for Every Port Act of 2006",
                 "CBP's own text writes 'Security and Accountability for Every (SAFE) Port Act of 2006'"),
        "3133": ("candidate-index-match", "Secure and Fair Enforcement for Mortgage Licensing Act of 2008",
                 "NCUA writes 'SAFE Mortgage Licensing Act', close to but not OLRC's wording; OLRC "
                 "carries a third, unrelated SAFE as well"),
    },
    "DHS": {
        "1601": ("not-an-act:agency", "", "OLRC lists 'DHS' as an also-known-as of the DART Act, which is "
                                          "exactly why this token must never resolve"),
        "1625": ("not-an-act:agency", "", "same"),
    },
    "USCG": {"1625": ("ambiguous", "", "'33 USCG 1231' is either 33 U.S.C. 1231 with a damaged label or the "
                                       "issuing agency's own initials, and the text cannot say which")},
    "INS": {"1615": ("ambiguous", "", "'INS secs. 208, 241, and 274A' are Immigration and Nationality Act "
                                      "section numbers, but INS is also the pre-2003 agency")},
    "NPS": {"0938": ("ambiguous", "", "'NPS System of Records' is a Privacy Act system of records, not an act")},
    "USA": {
        "1506": ("ambiguous", "", "'USA' here is part of 'USA PATRIOT Act'; the index's only literal '(USA)' "
                                  "is the Uninterrupted Scholars Act, a false match"),
        "1902": ("ambiguous", "", "'49 USA app 1 to 85' is the damaged-label family, task #31's, not a roster's"),
    },
}

#: NDAA is not agency-ambiguous, it is YEAR-ambiguous: every fiscal year is a
#: different act. The key is (token, year) and a row that states no year stays
#: refused. Two of the five are not listed in the pinned index at all, which is
#: recorded rather than papered over.
NDAA_YEARS = {
    "2009": ("National Defense Authorization Act for Fiscal Year 2009", "110-417"),
    "2013": ("National Defense Authorization Act for Fiscal Year 2013", "112-239"),
    "2017": ("National Defense Authorization Act for Fiscal Year 2017", "114-328"),
    "2021": ("National Defense Authorization Act for Fiscal Year 2021", "116-283"),
    "2023": ("National Defense Authorization Act for Fiscal Year 2023", "117-263"),
}
#: FOIA splits the same way: the base 1966 act is not a listed name, and which
#: amending act a row means depends on the year it states.
FOIA_YEARS = {
    "1996": "Electronic Freedom of Information Act Amendments of 1996",
    "2016": "FOIA Improvement Act of 2016",
}

FIELDS = (
    "token", "agency_prefix", "year_key", "status", "act_name", "table3_key",
    "evidence_path", "evidence_sha256", "evidence_quote", "rows_observed", "notes",
)


def tier(row: dict[str, str]) -> str:
    """Which evidence tier one investigation row actually stands on."""

    if row["status"].startswith("not-an-act") or row["status"] in {"ambiguous", "belief-only"}:
        return row["status"]
    if row["evidence_kind"] in {"federal-register-document", "olrc-popular-names-table"}:
        return "pinned-quote"
    if row["token"] in REVERSE_PL:
        return "reverse-pl-verified"
    if row["token"] in SELF_GLOSSING:
        return "self-glossing"
    return "candidate-index-match"


def observed(artifact: Path | None) -> dict[tuple[str, str], int]:
    """(token, agency prefix) -> rows the artifact still leaves unread."""

    if artifact is None:
        return {}
    import pyarrow.parquet as pq

    table = pq.read_table(
        artifact / "unified_agenda_legal_authorities.parquet",
        columns=["rin", "authority_text", "authority_type", "parse_status"],
    )
    caps = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9&-]{1,7}(?![A-Za-z0-9])")
    tokens = {row["token"].upper() for row in csv.DictReader(SOURCE.open(encoding="utf-8"))}
    counts: dict[tuple[str, str], int] = {}
    for row in table.to_pylist():
        if row["authority_type"] != "other" or row["parse_status"] != "failed":
            continue
        for found in caps.findall(str(row["authority_text"] or "")):
            if found.upper() in tokens:
                counts[(found.upper(), row["rin"][:4])] = counts.get((found.upper(), row["rin"][:4]), 0) + 1
                break
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "roster.csv")
    args = parser.parse_args()

    index = ActIndex.from_artifact(ACT_INDEX)
    counts = observed(args.artifact)
    source_rows = list(csv.DictReader(SOURCE.open(encoding="utf-8")))
    out: list[dict[str, object]] = []
    unresolved: list[str] = []
    #: The census is per (token, agency); a token keyed by year has several rows
    #: at one such pair, and writing the count on each would report the same
    #: rows five times. It goes on the first row of the pair and nowhere else.
    counted: set[tuple[str, str]] = set()

    def emit(token, agency, year, status, name, quote, path, sha, note, table3=""):
        resolved = ""
        if name:
            normalized = normalize_popular_name(name)
            found = resolve_act_name(normalized, index)
            if found is None and status in {"pinned-quote", "reverse-pl-verified", "self-glossing",
                                            "candidate-index-match"}:
                # A resolving tier whose name the index does not list is not an
                # error -- SMART is real and unlisted -- but it MUST be visible.
                note = (note + "; " if note else "") + "not listed in the pinned act index"
                unresolved.append(f"{token}@{agency}: {normalized!r}")
            resolved = found or normalized
            table3 = index.table3_key_by_name.get(found, "") if found else table3
        rows_observed = ""
        if counts and (token.upper(), agency) not in counted:
            counted.add((token.upper(), agency))
            rows_observed = counts.get((token.upper(), agency), 0)
        out.append({
            "token": token, "agency_prefix": agency, "year_key": year, "status": status,
            "act_name": resolved, "table3_key": table3, "evidence_path": path,
            "evidence_sha256": f"sha256:{sha}" if sha else "",
            "evidence_quote": quote, "rows_observed": rows_observed,
            "notes": note,
        })

    for row in source_rows:
        token = row["token"]
        agencies = [a for a in row["agency_prefix_or_any"].split(",") if a]
        quote = row["evidence_quote"]
        note = row["notes"]
        if token == "NDAA":
            for agency in agencies:
                for year, (name, key) in NDAA_YEARS.items():
                    emit(token, agency, year, "candidate-index-match", name, quote,
                         ACT_INDEX_EVIDENCE, file_digest(REPO / ACT_INDEX_EVIDENCE),
                         "the fiscal year names the act; a row stating none stays refused", key)
                emit(token, agency, "", "ambiguous", "", quote, "", "",
                     "bare 'NDAA' names no act: every fiscal year is a different one")
            continue
        if token == "FOIA":
            for agency in agencies:
                for year, name in FOIA_YEARS.items():
                    emit(token, agency, year, "candidate-index-match", name, quote,
                         ACT_INDEX_EVIDENCE, file_digest(REPO / ACT_INDEX_EVIDENCE),
                         "which amending act depends on the year the row states")
                emit(token, agency, "", "ambiguous", "", quote, "", "",
                     "the 1966 act itself is not a listed name")
            continue
        if token in AGENCY_KEYED:
            for agency in agencies:
                status, name, note = AGENCY_KEYED[token][agency]
                path, sha = ("", "")
                if status in {"candidate-index-match", "self-glossing"}:
                    path, sha = ACT_INDEX_EVIDENCE, file_digest(REPO / ACT_INDEX_EVIDENCE)
                emit(token, agency, "", status, name, quote, path, sha, note)
            continue
        status = tier(row)
        name = NAME_FIXES.get(token, row["expansion"]) if status not in {
            "ambiguous", "belief-only"} and not status.startswith("not-an-act") else ""
        if status == "pinned-quote":
            path, sha = QUOTE_RECEIPTS[token]
        elif status in {"reverse-pl-verified", "self-glossing", "candidate-index-match"}:
            path, sha = ACT_INDEX_EVIDENCE, file_digest(REPO / ACT_INDEX_EVIDENCE)
        else:
            path, sha = "", ""
        for agency in agencies:
            emit(token, agency, "", status, name, quote, path, sha, note)

    out.sort(key=lambda r: (r["token"].upper(), r["agency_prefix"], r["year_key"]))
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(out)
    print(f"{len(out)} roster rows -> {args.out}")
    if unresolved:
        print("names a resolving tier carries that the index does not list:")
        for line in unresolved:
            print(f"  {line}")
    return 0


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


if __name__ == "__main__":
    raise SystemExit(main())
