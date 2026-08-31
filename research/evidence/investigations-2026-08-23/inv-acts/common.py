"""Shared loading/caching for the act-name-carry and initialism measurement.

Read-only: reads the baseline parquet (rebuild #7 byte-identical copy) and the
pinned XML editions under output/registry-real-data-sources/. Writes only to
the evidence dir. Imports refspec.registry.* for grammar/act-resolution
functions -- never runs the builder.
"""
from __future__ import annotations

import pickle
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

REPO = Path("/Users/mikewolfd/Work/RefSpec")
EVID = Path("/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/inv-acts")
BASELINE_PARQUET = Path(
    "/Users/mikewolfd/.claude/jobs/9dfc0c64/tmp/old-rebuild7-c99177b8/out/unified_agenda_legal_authorities.parquet"
)

sys.path.insert(0, str(REPO / "src"))

from refspec.registry.act_resolution import (  # noqa: E402
    ActIndex,
    SourceCreditIndex,
    resolve_act_name,
    resolve_act_relative_citation,
)
from refspec.registry.citation_grammar import (  # noqa: E402
    ActRelativeCitation,
    _normalize_dashes,
    normalize_popular_name,
    stated_act_name,
)
from refspec.registry.unified_agenda_editions import UNIFIED_AGENDA_EDITION_PINS  # noqa: E402

# ---------------------------------------------------------------------------
# Population A: a box that is nothing but a section designation or a list of
# them, no scheme label anywhere. Finalized against the 1,054 distinct
# other/failed texts in the baseline (see inv-acts/regex-tuning notes in the
# report): 237 distinct texts match. Dashes normalized first (en-dash lists
# like "4201-4245" occur); "et seq." admitted as a tail; a marker
# (sec/section/secs/section-sign) may repeat before each list member.
_SECTION_TOK = r"\d{1,6}[a-zA-Z]{0,3}(?:-\d{1,6}[a-zA-Z]{0,2})?(?:\s*\([^()]{1,12}\))*(?:\s+et\.?\s+seq\.?)?"
#: NOT "/" -- admitting it as a separator matched "11/04/1980" (a date sitting
#: where a citation belongs, RIN 1105-AB50) as a 3-member section list. Found
#: by inspecting every Population A candidate before trusting the count.
_SECTION_SEP = r"(?:\s*,\s*(?:and|or)\s+|\s*,\s*|\s+(?:and|or|to|through)\s+|\s*&\s*)"
_MARKER = r"(?:sec(?:tion)?s?\.?|§{1,2})\s*"
BARE_SECTION_LIST = re.compile(
    rf"^(?:and|or|,)?\s*(?:{_MARKER})?{_SECTION_TOK}(?:{_SECTION_SEP}(?:{_MARKER})?{_SECTION_TOK})*\s*[.;,]?\s*$",
    re.IGNORECASE,
)


def is_bare_section_list(text: str) -> bool:
    return bool(BARE_SECTION_LIST.match(_normalize_dashes(text or "").strip()))


# ---------------------------------------------------------------------------
# Candidate initialism token: 2-6 capitals, optionally an internal "&" run,
# optionally a trailing hyphen-digits suffix ("NDAA-17"). Matches every
# example the task names: UMTRCA, HSIA, MIPPA, NDAA-17, FD&C.
INITIALISM_TOKEN = re.compile(r"\b[A-Z][A-Z&]{1,5}(?:-\d{1,4})?\b")

#: Scheme labels and other non-initialism uppercase tokens the corpus writes
#: routinely, curated by inspecting the raw frequency table (see the report).
#: Seeded from unified_agenda_parquet._ABBREV_LABEL_TOKENS, which is the
#: production module's own list of tokens that are never an act abbreviation.
EXCLUDED_INITIALISM_TOKENS = frozenset(
    {
        "PL", "USC", "USCA", "EO", "FR", "CFR", "RS", "DM", "STAT", "FSM",
        "OMB", "HR", "US", "DC", "IRC", "UST", "TIAS", "UNTS", "FAR", "DODD",
        # Roman numerals, routinely used as title/division/part designators
        "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI",
        "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
        # Ordinary short words/connectives that appear capitalized (list starts,
        # OCR-shifted case) and abbreviation-shaped OCR damage of "U.S.C."/"CFR"
        "AND", "OR", "OF", "THE", "TO", "IN", "ON", "AT", "BY", "FOR", "A", "AN",
        "NO", "ID", "ET", "AL", "SEQ", "NOTE", "NTS", "PP", "VOL", "ED", "REV",
        "SEC", "SECS", "APP", "CH", "PT", "TITLE", "PART", "DIV", "SUBP",
        "USG", "ISC", "UC",  # OCR/typo variants of "USC" seen in the corpus
    }
)


#: A token spelled entirely from Roman-numeral letters, checked as an actual
#: numeral (not just shape) so a genuine initialism that happens to be
#: numeral-shaped is not silently dropped -- none are in this corpus, but the
#: check is exact rather than a coincidence of the letters available.
_ROMAN_NUMERAL_LETTERS = re.compile(r"^[IVXLCDM]+$")
_ROMAN_NUMERAL_VALUE = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _is_roman_numeral(token: str) -> bool:
    if not _ROMAN_NUMERAL_LETTERS.match(token):
        return False
    total = 0
    prev = 0
    for ch in reversed(token):
        val = _ROMAN_NUMERAL_VALUE[ch]
        total += val if val >= prev else -val
        prev = val
    # Round-trips through a numeral formatter would be stricter; this corpus
    # only needs "reads as a numeral at all" to exclude "title LXXVI" shapes.
    return total > 0


def candidate_initialisms(text: str) -> list[str]:
    """Every uppercase token in text that isn't an excluded label."""

    return [
        tok for tok in INITIALISM_TOKEN.findall(text or "")
        if tok.upper() not in EXCLUDED_INITIALISM_TOKENS and not _is_roman_numeral(tok.upper())
    ]


# ---------------------------------------------------------------------------
# The corpus glossing its own abbreviation, applied to ABSTRACT text instead
# of authority_text: "... National Defense Authorization Act for Fiscal Year
# 2017 (NDAA-17)". Finding the initialism is a plain parenthetical scan; naming
# what it glosses reuses citation_grammar.stated_act_name on the text
# immediately BEFORE the parenthesis (walking backwards from "Act" over
# capitalized tokens, the same reader the production module uses for
# authority_text) rather than a second, hand-rolled greedy regex -- a first
# cut that captured raw text up to "Act" swallowed whole leading sentences
# ("Directive that provides for categorical exclusions under the National
# Environmental Policy Act") whenever the ABSTRACT's only "Act" before the
# parenthetical was the one that mattered, which then correctly failed to
# resolve and understated how often the abstract actually names a real act.
_ABSTRACT_INITIALISM_PAREN = re.compile(r"\(([A-Z][A-Z&]{1,5}(?:-\d{1,4})?)\)")
_ACT_TOKEN_SPAN = re.compile(r"\bActs?\b")
#: stated_act_name's own forward-tail reader (_ACT_NAME_YEAR) recognizes only
#: "of YYYY" / ", YYYY" / " YYYY" -- not "for Fiscal Year YYYY", the NDAA
#: family's own naming convention ("National Defense Authorization Act for
#: Fiscal Year 2017"). Found via RIN 0720-AB70/201904, whose ABSTRACT states
#: the fiscal-year-qualified name in full and which resolve_act_name answers
#: -- but stated_act_name alone truncates to the year-less, genuinely
#: ambiguous "National Defense Authorization Act" (an NDAA is enacted every
#: year). Supplementing the walk with this one extra tail, rather than
#: silently under-reporting what the ABSTRACT actually states, matters here:
#: it is the difference between "abstract names it, index still refuses" and
#: "abstract names it, index resolves".
_FISCAL_YEAR_TAIL = re.compile(r"^\s+for\s+Fiscal\s+Year\s+(?:18|19|20)\d{2}\b")


def abstract_glosses(abstract_text: str) -> dict[str, str]:
    """initialism -> the act name stated_act_name reads immediately before it.

    Windowed on the SINGLE "Act" occurrence nearest the parenthetical, not a
    wide span: stated_act_name keeps the LONGEST name among every "Act" in
    whatever text it is given, which is right when a value names one act and
    wrong here, where one ABSTRACT sentence often glosses several acts close
    together ("... Right-to-Know Act of 1986 (EPCRA) ... Pollution Prevention
    Act of 1990 (PPA)") -- a wide window fed the first, longer name to BOTH
    initialisms. Isolating the nearest "Act" keeps each gloss its own.
    """

    out: dict[str, str] = {}
    text = abstract_text or ""
    act_spans = list(_ACT_TOKEN_SPAN.finditer(text))
    for match in _ABSTRACT_INITIALISM_PAREN.finditer(text):
        earlier = [span for span in act_spans if span.end() <= match.start()]
        if not earlier:
            continue
        nearest = max(earlier, key=lambda span: span.end())
        earlier.remove(nearest)
        prior = max((span.end() for span in earlier), default=0)
        # The window ends EXACTLY at the parenthetical (not padded past it),
        # so a name stated_act_name finds is adjacent to it by construction;
        # bounded on the left by the PRECEDING "Act" occurrence (if any), so a
        # dense sentence naming two acts close together never lets the second
        # window see the first act's tokens.
        window = text[max(prior, nearest.start() - 120) : match.start()]
        name = stated_act_name(window)
        if name is None:
            continue
        # Adjacency check: the recognized name must run to the window's own
        # end (mod trailing whitespace) -- if it doesn't, unrelated text sits
        # between the name and this parenthetical (the "(HMO)" case: nearest
        # preceding "Act" was the NDAA's, three clauses earlier in the same
        # ABSTRACT sentence, not what "(HMO)" glosses).
        fiscal_year = _FISCAL_YEAR_TAIL.match(text[nearest.end() : match.start()])
        if fiscal_year is not None and name.rstrip().endswith("Act"):
            name = name.rstrip() + fiscal_year.group(0)
        if not _normalize_dashes(window).rstrip().endswith(name.rstrip()):
            continue
        out.setdefault(match.group(1), name.strip())
    return out


def abbrev_survivors(token: str, keys) -> list[str]:
    """Acts in one roster pool `token` can name -- exact-initials first, then
    the anchored-subsequence operator (unified_agenda_parquet._anchored_subsequence),
    ported verbatim: head and tail letters must match, interior may skip."""

    exact = [k for k in keys if act_initialism(k) == token]
    if exact:
        return exact

    def anchored_subsequence(abbreviation: str, initialism: str) -> bool:
        if len(abbreviation) < 2 or not initialism or len(abbreviation) > len(initialism):
            return False
        if abbreviation[0] != initialism[0] or abbreviation[-1] != initialism[-1]:
            return False
        index = 0
        for letter in initialism:
            if index < len(abbreviation) and abbreviation[index] == letter:
                index += 1
        return index == len(abbreviation)

    return [k for k in keys if anchored_subsequence(token, act_initialism(k))]

ACT_INDEX_DIR = REPO / "output/usc-act-index-2026-08-22"
SOURCE_CREDIT_DIR = REPO / "output/usc-source-credit-index-2026-08-02"
EDITIONS_DIR = REPO / "output/registry-real-data-sources/unified-agenda-editions"

NEEDED_COLUMNS = [
    "rin", "publication_id", "ordinal", "citation_ordinal", "authority_text",
    "authority_type", "parse_status", "act_key", "act_section",
    "act_resolution_evidence", "act_resolution_reason", "usc_title", "usc_section",
    "cfr_title", "public_law", "executive_order", "stated_act_name", "stated_section",
    "corroboration_rule",
]

_ACT_INITIALISM_STOPWORDS = frozenset(
    {"of", "the", "and", "for", "a", "an", "to", "in", "on", "with", "by"}
)


def act_initialism(key: str) -> str:
    """Port of unified_agenda_parquet._act_initialism (verbatim logic)."""

    letters = []
    for word in re.split(r"[\s,:\-]+", key):
        if not word or word in _ACT_INITIALISM_STOPWORDS:
            continue
        if re.fullmatch(r"(?:18|19|20)\d{2}", word) or not word[0].isalpha():
            continue
        letters.append(word[0])
    return "".join(letters).upper()


def load_rows(force: bool = False):
    """rows sorted by (rin, publication_id, ordinal, citation_ordinal)."""

    cache = EVID / "rows_sorted.pkl"
    if cache.is_file() and not force:
        with cache.open("rb") as fh:
            return pickle.load(fh)
    import pyarrow.parquet as pq

    tbl = pq.read_table(BASELINE_PARQUET, columns=NEEDED_COLUMNS)
    tbl = tbl.sort_by(
        [("rin", "ascending"), ("publication_id", "ascending"), ("ordinal", "ascending"), ("citation_ordinal", "ascending")]
    )
    rows = tbl.to_pylist()
    with cache.open("wb") as fh:
        pickle.dump(rows, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return rows


def build_roster(rows):
    """Faithful reconstruction of act_keys_by_rin / act_keys_by_agency.

    Built BEFORE any corroboration runs in the real builder (contract:
    "Both oracles are built from the table BEFORE any corroboration runs").
    Rows produced by a corroboration pass carry a non-NULL corroboration_rule;
    every other row with a non-NULL act_key is base-pass output, which is
    exactly what fed act_keys_by_rin/act_keys_by_agency at build time.
    """

    keys_by_rin: dict[str, set[str]] = {}
    keys_by_agency: dict[str, set[str]] = {}
    for row in rows:
        if row["act_key"] and row["corroboration_rule"] is None:
            keys_by_rin.setdefault(row["rin"], set()).add(row["act_key"])
            keys_by_agency.setdefault(row["rin"][:4], set()).add(row["act_key"])
    return keys_by_rin, keys_by_agency


def group_boxes(rows):
    """(rin, publication_id) -> [box, ...] ordinal-ascending.

    Each box: {"ordinal": int, "text": str, "rows": [row, ...]}.
    """

    records: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        key = (row["rin"], row["publication_id"])
        boxes = records.setdefault(key, [])
        if boxes and boxes[-1]["ordinal"] == row["ordinal"]:
            boxes[-1]["rows"].append(row)
        else:
            boxes.append({"ordinal": row["ordinal"], "text": row["authority_text"], "rows": [row]})
    return records


def load_act_index():
    index = ActIndex.from_artifact(ACT_INDEX_DIR)
    credits = SourceCreditIndex.from_artifact(SOURCE_CREDIT_DIR)
    return index, credits


def resolve_one(act_key_text: str, section: str | None, index: ActIndex, credits: SourceCreditIndex):
    """Same decision refspec.registry.unified_agenda_parquet._resolve_one_act_citation
    makes, ported verbatim (it is a thin wrapper over the public
    resolve_act_relative_citation API plus two narrowings we don't need for
    reporting -- we report the resolver's own reason directly)."""

    resolved = resolve_act_name(act_key_text, index)
    if resolved is None:
        return (None, None, None, "act_not_in_index")
    if section is None:
        return (None, None, None, "no_section_stated")
    outcome = resolve_act_relative_citation(
        ActRelativeCitation(act_name=act_key_text, act_key=act_key_text, section=section),
        index=index,
        source_credits=credits,
    )
    if outcome.iri is not None:
        return (outcome.usc_title, outcome.usc_section, outcome.answered_by, None)
    return (None, None, None, outcome.unresolved_reason)


# ---------------------------------------------------------------------------
# ABSTRACT extraction (the reader does not expose it) -- same pinned bytes,
# same digest verification the reader uses, read directly here.

_PIN_BY_PUBLICATION_ID = {pin.publication_id: pin for pin in UNIFIED_AGENDA_EDITION_PINS}
_MANGLED_APOSTROPHE = b"\x19"


def _text(element) -> str:
    return "" if element is None else " ".join((element.text or "").split())


def _load_edition_abstracts(publication_id: str) -> dict[str, str]:
    import hashlib

    pin = _PIN_BY_PUBLICATION_ID[publication_id]
    payload = (EDITIONS_DIR / f"REGINFO_RIN_DATA_{pin.file_stem}.xml").read_bytes()
    assert len(payload) == pin.expected_byte_length, "byte length drift"
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    assert digest == pin.expected_sha256, "digest drift"
    repaired = payload.replace(_MANGLED_APOSTROPHE, "’".encode())
    root = ET.fromstring(repaired)
    out: dict[str, str] = {}
    for element in root.findall(".//RIN_INFO"):
        rin = _text(element.find("RIN"))
        out[rin] = _text(element.find("ABSTRACT"))
    return out


class AbstractCache:
    def __init__(self):
        self._by_edition: dict[str, dict[str, str]] = {}

    def get(self, rin: str, publication_id: str) -> str:
        if publication_id not in self._by_edition:
            self._by_edition[publication_id] = _load_edition_abstracts(publication_id)
        return self._by_edition[publication_id].get(rin, "")


if __name__ == "__main__":
    rows = load_rows()
    print("rows loaded:", len(rows))
    keys_by_rin, keys_by_agency = build_roster(rows)
    print("distinct RINs with a base-pass act key:", len(keys_by_rin))
    print("distinct agencies with a base-pass act key:", len(keys_by_agency))
    records = group_boxes(rows)
    print("distinct (rin, publication_id) records:", len(records))

    # Specimen self-test
    spec = records[("0936-AA07", "201710")]
    print("\nspecimen RIN 0936-AA07 / 201710 boxes:")
    for box in spec:
        print(" ", box["ordinal"], repr(box["text"]), [(r["authority_type"], r["parse_status"]) for r in box["rows"]])

    print("\nagency 0936 roster (act keys resolved elsewhere, base pass):")
    for k in sorted(keys_by_agency.get("0936", ())):
        print(" ", repr(k), "->", act_initialism(k))
    print("\nrin 0936-AA07 own roster:", keys_by_rin.get("0936-AA07"))
