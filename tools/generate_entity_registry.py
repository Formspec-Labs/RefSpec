"""Generate the standalone entity-registry object from pinned registry captures.

Registrant populations (SAM registrants, CAGE facilities, NPI providers,
CompTox substances) live here, not in the Atlas; see REF-030.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from refspec.registry.entity_registry_release import (
    EntityRegistryError,
    verify_entity_registry,
    write_entity_registry,
)

DEFAULT_OUTPUT = REPO_ROOT / "output" / "entity-registry-2026-08-03"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify_only:
            manifest = verify_entity_registry(args.output)
        else:
            write_entity_registry(REPO_ROOT, args.output)
            manifest = verify_entity_registry(args.output)
    except EntityRegistryError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "counts": manifest["counts"],
                "output": str(args.output),
                "payloadSha256": manifest["payloadSha256"],
                "status": "passed",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
