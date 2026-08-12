#!/usr/bin/env python
"""Serialize `_batched_shacl_plan(shapes).shapes` so Jena can run HEAD's plan.

The whole-graph Jena runs are slow because of a constraint COMBINATION inside a
single node shape -- every constraint is fast on its own at 29.3M triples.
`_batched_shacl_plan` already decomposes shapes exactly that way for pySHACL:
each `sh:property` of a targeted node shape is given the parent's targets and
detached, `sh:closed` and the two high-volume `sh:xone` guarantees are lifted
into Python prechecks, and inline value shapes are folded in. That plan is
already proved conformance-equivalent and is what HEAD's green path runs.

So the question this answers is: does handing Jena the SAME plan sidestep the
blowup? If it does, a Jena subprocess needs no new machinery -- it reuses the
decomposition RefSpec already ships and already tests.

Usage: emit_batched_shapes.py <out.ttl>
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path("/Users/mikewolfd/Work/spicy-regs/RefSpec")
sys.path.insert(0, str(REPO / "bindings/atlas/3.1/tools"))

import validate  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1])
    _, shapes = validate._parse_binding_graphs()
    plan = validate._batched_shacl_plan(shapes)
    out.write_bytes(plan.shapes.serialize(format="turtle", encoding="utf-8"))
    print(f"normative shapes: {len(shapes)} triples")
    print(f"batched plan:     {len(plan.shapes)} triples -> {out}")
    print(f"lifted closed shapes:      {len(plan.closed_shapes)}")
    print(f"lifted ring context:       {plan.checks_relation_ring_context}")
    print(
        "lifted warrant branches:   "
        f"{len(plan.warrant_branches) if plan.warrant_branches is not None else None}"
    )


if __name__ == "__main__":
    main()
