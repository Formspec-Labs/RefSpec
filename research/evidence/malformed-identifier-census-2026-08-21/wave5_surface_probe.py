"""Wave 5: the two surfaces wave 3 named and left open, audited.

``docket-and-document-surfaces.md`` closed with two "still open" items. This
probe measures both, and each turns out to hold a decision rather than a
mystery:

A. ``court_opinions.parquet``'s citation column mixes two schemes, and the
   discriminator is already in the row.
B. the Federal Register API's RIN column carries 444 invalid tokens, and the
   Unified Agenda's own RIN roster is a pinned oracle nobody had asked.

Run: ``uv run python research/evidence/malformed-identifier-census-2026-08-21/wave5_surface_probe.py``
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

OPINIONS = ROOT / "output/court-opinions-2026-08-21/court_opinions.parquet"
FEDREG = ROOT / "output/registry-real-data-sources/regulatory-native-current/federal_register.parquet"
AGENDA = ROOT / "output/registry-real-data-sources/unified-agenda-parquet/unified_agenda_actions.parquet"

from refspec.registry.identifier_shapes import (  # noqa: E402
    is_regulation_identifier_number,
    normalize_rin,
)

#: The Bluebook U.S. Reports citation: a volume and a first page.
US_REPORTS = re.compile(r"^(?P<volume>\d{1,3})\s+U\.\s?S\.\s+(?P<page>\d{1,4})$")
#: The Court's own preliminary-print designation: a volume and a PART. It
#: locates no page, so it is not a citation and must not be validated as one.
PRELIMINARY_PART = re.compile(r"^(?P<volume>\d{1,3})/(?P<part>[1-4])$")


def audit_opinions() -> None:
    if not OPINIONS.exists():
        print("court_opinions.parquet absent; skipping")
        return
    rows = pq.read_table(OPINIONS).to_pylist()
    kinds = collections.Counter()
    by_kind = collections.defaultdict(collections.Counter)
    for row in rows:
        citation = (row["citation"] or "").strip()
        if US_REPORTS.match(citation):
            kind = "us-reports-citation"
        elif PRELIMINARY_PART.match(citation):
            kind = "preliminary-print-part"
        elif not citation:
            kind = "empty"
        else:
            kind = "unrecognised"
        kinds[kind] += 1
        by_kind[kind][citation] += 1
        # The discriminator the row already carries: a bound release names its
        # own volume in the filename ("608us1r32_*.pdf"); a slip opinion names
        # its docket ("24-43_2b35.pdf").
        stem = row["source_url"].rsplit("/", 1)[-1]
        by_kind[kind + ":filename"]["bound" if re.match(r"^\d{3}us\d", stem) else "slip"] += 1
    print("== A. court_opinions.citation ==")
    print(f"   rows {len(rows)}")
    for kind, n in kinds.most_common():
        distinct = len(by_kind[kind])
        print(f"   {n:4d}  {distinct:3d} distinct  {kind}   filename form: "
              f"{dict(by_kind[kind + ':filename'])}")
        for value, c in by_kind[kind].most_common(4):
            print(f"          {c:3d}  {value!r}")
    docket = collections.Counter(
        "application" if re.match(r"^\d{2}A\d", r["docket_number"] or "") else "certiorari"
        for r in rows
    )
    print(f"   docket_number forms: {dict(docket)}")


#: Homoglyph pairs, applied only in the slot whose alphabet the shape fixes:
#: the two letters of the sequence prefix and the two digits after it.
_HOMOGLYPHS = (("0", "O"), ("1", "I"), ("5", "S"), ("8", "B"), ("2", "Z"))


def rin_variants(value: str) -> set[str]:
    """Candidates from named damage operators, never from a guess."""

    out: set[str] = set()
    base = value
    if re.match(r"^\d{4}[\s_]\w{4}$", value):
        base = value[:4] + "-" + value[5:]
        out.add(base)
    out.add(re.sub(r"\s+", "", base))
    body = base[5:] if len(base) > 5 and base[4] == "-" else ""
    if len(body) == 4:
        for index in (0, 1):  # letters
            for digit, letter in _HOMOGLYPHS:
                if body[index] == digit:
                    out.add(base[:5] + body[:index] + letter + body[index + 1:])
        for index in (2, 3):  # digits
            for digit, letter in _HOMOGLYPHS:
                if body[index] == letter:
                    out.add(base[:5] + body[:index] + digit + body[index + 1:])
    return {candidate for candidate in out if candidate != value}


def audit_fedreg_rins() -> None:
    if not FEDREG.exists() or not AGENDA.exists():
        print("federal_register or agenda parquet absent; skipping")
        return
    tokens: collections.Counter = collections.Counter()
    for value in pq.read_table(FEDREG, columns=["regulation_id_numbers_json"]).column(0).to_pylist():
        if not value:
            continue
        try:
            items = json.loads(value)
        except (TypeError, ValueError):
            continue
        for item in items or ():
            tokens[item] += 1
    roster = {
        rin.upper() for rin in pq.read_table(AGENDA, columns=["rin"]).column(0).to_pylist()
    }
    invalid = {k: v for k, v in tokens.items() if not is_regulation_identifier_number(k)}
    corroborated: collections.Counter = collections.Counter()
    shaped_only: collections.Counter = collections.Counter()
    alien: collections.Counter = collections.Counter()
    for token, count in invalid.items():
        value = token.strip().upper().replace("–", "-").replace("—", "-")
        wellformed = {
            normalize_rin(c) for c in rin_variants(value) if is_regulation_identifier_number(c)
        }
        survivors = wellformed & roster
        if len(survivors) == 1:
            corroborated[token] = count
        elif wellformed:
            shaped_only[token] = count
        else:
            alien[token] = count
    print("\n== B. federal_register.regulation_id_numbers_json ==")
    print(f"   {len(tokens)} distinct tokens, {sum(tokens.values())} occurrences")
    print(f"   invalid by the pinned RIN shape: {sum(invalid.values())} / {len(invalid)} distinct")
    print(f"   agenda roster: {len(roster)} RINs")
    print(f"   CORROBORATED (exactly one roster survivor): "
          f"{sum(corroborated.values())} / {len(corroborated)}")
    for token, count in corroborated.most_common(8):
        value = token.strip().upper()
        survivor = next(iter({normalize_rin(c) for c in rin_variants(value)
                              if is_regulation_identifier_number(c)} & roster))
        print(f"      {count:3d}  {token!r} -> {survivor!r}")
    print(f"   REFUSED, operator reaches a well-formed RIN the roster does not hold: "
          f"{sum(shaped_only.values())} / {len(shaped_only)}")
    print(f"      e.g. {sorted(shaped_only, key=lambda k: -shaped_only[k])[:8]}")
    print(f"   REFUSED, no operator reaches a RIN: {sum(alien.values())} / {len(alien)}")
    omb = {k: v for k, v in alien.items() if re.match(r"^\d{4}-\d{4}$", k)}
    print(f"      of which OMB control numbers filed as RINs: {sum(omb.values())} / {len(omb)}"
          f"  e.g. {sorted(omb)[:6]}")
    print(f"      remainder: {sorted(set(alien) - set(omb))}")


if __name__ == "__main__":
    audit_opinions()
    audit_fedreg_rins()
