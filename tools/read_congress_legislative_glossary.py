#!/usr/bin/env python3
"""Write a pinned reference view from a retained Congress.gov glossary original."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from refspec.registry.congress_legislative_glossary import (
    PARSER_VERSION,
    read_legislative_glossary,
)
from refspec.registry.infrastructure.artifact_serialization import canonical_json_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="exact original from central raw custody")
    parser.add_argument("--output", type=Path, required=True, help="new derived JSON reference; never a raw path")
    args = parser.parse_args()
    snapshot = read_legislative_glossary(args.source)
    result = {
        "format": PARSER_VERSION,
        **asdict(snapshot),
        "unresolved_fragment_links": list(snapshot.unresolved_fragment_links),
        "identity_scope": "Fragments locate entries in the pinned page; no stable concept identity is asserted.",
    }
    for row, entry in zip(result["entries"], snapshot.entries, strict=True):
        row.update(source_locator=entry.source_locator, source_url=entry.source_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(canonical_json_bytes(result))
    print(f"Read {len(snapshot.entries)} glossary entries from {snapshot.pin.expected_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
