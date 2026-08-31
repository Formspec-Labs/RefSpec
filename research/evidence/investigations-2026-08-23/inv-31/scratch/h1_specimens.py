from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import VALUE_COLUMNS, base_rows_by_box, load_base, load_boxes, nonnull  # noqa: E402

from refspec.registry.citation_grammar import parse_authority_citation  # noqa: E402

SPECIMENS = [
    ("2126-AA63", "200010"),
    ("3052-AD44", "202210"),
    ("3052-AD42", "202210"),
    ("3072-AC96", "202304"),
    ("3072-AC38", "201010"),
    ("0936-AA07", "201710"),
    ("2060-AP43", "201004"),
    ("2126-AA64", "200404"),
]

boxes = load_boxes()
table = load_base(VALUE_COLUMNS)
by_box = base_rows_by_box(table)


def show(citation) -> str:
    d = {k: v for k, v in vars(citation).items() if v is not None and v is not False}
    return ", ".join(f"{k}={v!r}" for k, v in sorted(d.items()))


for rin, pub in SPECIMENS:
    bs = boxes.get((rin, pub), [])
    print("=" * 100)
    print(f"RIN {rin}   edition {pub}   {len(bs)} box(es)")
    print("-" * 100)
    for i, text in enumerate(bs):
        print(f"  box[{i}] = {text!r}")
        rows = by_box.get((rin, pub, i), [])
        for row in rows:
            print(f"        BASELINE row co={row['citation_ordinal']}: {nonnull(row)}")
    print("-" * 100)
    joined = ", ".join(bs)
    print(f"  JOINED (', ') = {joined!r}")
    for j, c in enumerate(parse_authority_citation(joined)):
        print(f"        grammar[{j}]: {show(c)}")
    joined_sp = " ".join(bs)
    print(f"  JOINED (' ')  = {joined_sp!r}")
    for j, c in enumerate(parse_authority_citation(joined_sp)):
        print(f"        grammar[{j}]: {show(c)}")
    print()
