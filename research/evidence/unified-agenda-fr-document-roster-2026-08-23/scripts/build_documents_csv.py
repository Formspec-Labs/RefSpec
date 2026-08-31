#!/usr/bin/env python3
"""Write documents.csv from the pinned receipts beside it. No network.

Every column but two is copied verbatim out of a receipt. The two that are not
are stated here rather than hidden:

* ``rin_agency_prefixes`` is the OMB agency code the research note verified for
  a document whose own ``regulation_id_numbers`` is EMPTY, so that a filer's RIN
  still has a witness. It is written for the two FCC documents and nowhere else.
* the near-miss row 2024-29633 comes from the ISSUE listing, which carries no
  volume, no publication date, no agency and no html_url. Its volume is read off
  its own citation and its publication date is the issue the listing names
  ("Documents published on 12/17/2024"); the rest stay empty.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
RECEIPTS = HERE / "receipts"
FETCHED_AT = "2026-08-23"

#: Documents whose FR metadata lists no RIN at all, with the OMB agency code the
#: research note verified for them. Without this the filer's RIN has no witness
#: and the corroboration refuses.
RIN_AGENCY_PREFIXES = {"2020-09815": "3060", "2020-24486": "3060"}

FIELDS = (
    "document_number", "volume", "start_page", "end_page", "publication_date",
    "citation", "type", "title", "regulation_id_numbers", "agencies",
    "docket_ids", "rin_agency_prefixes", "html_url", "fetched_at", "source_sha256",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def from_document(name: str) -> dict[str, object]:
    path = RECEIPTS / f"{name}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "document_number": payload["document_number"],
        "volume": payload["volume"],
        "start_page": payload["start_page"],
        "end_page": payload["end_page"],
        "publication_date": payload["publication_date"],
        "citation": payload["citation"],
        "type": payload["type"],
        "title": payload["title"],
        "regulation_id_numbers": ";".join(payload["regulation_id_numbers"]),
        "agencies": ";".join(a.get("raw_name") or a["name"] for a in payload["agencies"]),
        "docket_ids": ";".join(payload["docket_ids"]),
        "rin_agency_prefixes": RIN_AGENCY_PREFIXES.get(payload["document_number"], ""),
        "html_url": payload["html_url"],
        "fetched_at": FETCHED_AT,
        "source_sha256": digest(path),
    }


def from_issue(name: str) -> dict[str, object]:
    path = RECEIPTS / "issue-2024-12-17.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    entry = next(r for r in payload["results"] if r["document_number"] == name)
    return {
        "document_number": entry["document_number"],
        "volume": int(entry["citation"].split()[0]),
        "start_page": entry["start_page"],
        "end_page": entry["end_page"],
        "publication_date": "2024-12-17",
        "citation": entry["citation"],
        "type": entry["type"],
        "title": entry["title"],
        "regulation_id_numbers": ";".join(entry["regulation_id_numbers"]),
        "agencies": "",
        "docket_ids": "",
        "rin_agency_prefixes": "",
        "html_url": "",
        "fetched_at": FETCHED_AT,
        "source_sha256": digest(path),
    }


def main() -> None:
    rows = [from_document(n) for n in
            ("2016-23432", "2020-09815", "2020-21071", "2020-24486", "2024-29238")]
    rows.append(from_issue("2024-29633"))
    rows.sort(key=lambda row: row["document_number"])
    with (HERE / "documents.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} roster rows")


if __name__ == "__main__":
    main()
