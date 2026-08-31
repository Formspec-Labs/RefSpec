#!/usr/bin/env python
"""Cut the test fixtures out of the two pinned sources, verbatim.

Every fragment in ``fixtures/`` is a byte slice of a source this directory
pins — ``popularnames.htm.gz`` here, and the release-point USLM zip named in
``README.md`` — so a fast unit test asserts against what OLRC actually
published rather than against prose invented to make a regular expression pass.

Run from the repository root::

    .venv/bin/python research/evidence/usc-regeneration-2026-08-31/scripts/extract_fixtures.py
"""

from __future__ import annotations

import gzip
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from tools.build_usc_popular_names import ENTRY as _ENTRY
from tools.build_usc_source_credits import iter_source_credits

# Came home 2026-08-31: the archive's canonical location is the repo's own
# top-level output/ (the corpora salvage path was temporary staging).
USLM_ARCHIVE = Path(__file__).resolve().parents[4] / "output" / "usc-annual-2026-08-24" / "xml_uscAll_119-102.zip"

#: Popular-name entries cut whole, each demonstrating one stated shape. Keyed by
#: the entry's own ``id`` attribute, which is how OLRC anchors it in the page.
POPULAR_NAME_ANCHORS = {
    # A cite with both a statviewer query and a stated "134 Stat. 4879", and a
    # usckey the anchor grammar accepts.
    "statviewer_and_stated_citation_agree": "1921SilverDollarCoinAnniversaryAct",
    # A cite whose statviewer query is absent: the volume survives only in the
    # stated citation. One of the 56 such rows on release point 119-102.
    "stated_citation_only": "21stCenturyCuresAct",
    # "see" and "renamed" -- the two kinds that state a target -- and
    # "also-known-as", the kind that reads like one and states none.
    "see": "CleanWaterAct",
    "renamed": "InternalRevenueCode",
    "also_known_as": "21stCenturyIntegratedDigitalExperienceAct",
    # One entry stating a usckey the anchor grammar accepts ("18:App.)") beside
    # one it refuses ("18A:1"): an appendix title is not a U.S. Code title.
    "usckey_accepted_and_refused": "InterstateAgreementonDetainersAct",
    # One name, two enacting acts. Collapsing them would invent a citation.
    "ambiguous_name": "DetaineeTreatmentActof2005",
}

#: USLM source credits cut whole, by the identifier of the section carrying them.
CREDIT_SECTIONS = {
    # The enactment construction, stated plainly.
    "added_enactment": "/us/usc/t26/s6038E",
    # The same public law, division and act section, with no construction at
    # all -- and never the word "amended" either. The measured false positive
    # that the strict rule removes.
    "no_construction_7652": "/us/usc/t26/s7652",
    # A citation naming a division and an act section with no lead. This module
    # carries no row for it.
    "no_construction_2714a": "/us/usc/t22/s2714a",
    # An enactment followed by an amendment, each stating its own page. The
    # bound is what keeps the amendment's 133 Stat. 1604 off the enactment.
    "enactment_then_amendment": "/us/usc/t5/s3116",
    # A section identifier USLM spells with an EN DASH.
    "en_dash_section": "/us/usc/t16/s824s–1",
}


def popular_name_fixtures(document: str) -> dict:
    entries = {match.group("anchor"): match.group(0) for match in _ENTRY.finditer(document)}
    return {label: entries[anchor] for label, anchor in POPULAR_NAME_ANCHORS.items()}


def credit_fixtures(archive: Path) -> dict:
    wanted = set(CREDIT_SECTIONS.values())
    found: dict[str, str] = {}
    with zipfile.ZipFile(archive) as bundle:
        for member in sorted(name for name in bundle.namelist() if name.endswith(".xml")):
            payload = bundle.read(member)
            for identifier, text in iter_source_credits(payload):
                if identifier in wanted:
                    found[identifier] = text
            if wanted <= set(found):
                break
    return {
        label: {"identifier": identifier, "credit": found[identifier]} for label, identifier in CREDIT_SECTIONS.items()
    }


def main() -> int:
    document = gzip.decompress((HERE / "popularnames.htm.gz").read_bytes()).decode("utf-8")
    (HERE / "fixtures" / "popular-name-entries.json").write_text(
        json.dumps(popular_name_fixtures(document), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if not USLM_ARCHIVE.exists():
        print(f"missing {USLM_ARCHIVE}; source-credit fixtures not rewritten", file=sys.stderr)
        return 1
    (HERE / "fixtures" / "uslm-source-credits.json").write_text(
        json.dumps(credit_fixtures(USLM_ARCHIVE), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
