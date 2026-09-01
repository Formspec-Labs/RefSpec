"""Replay REF-056's measurement from the pinned parquet, without circularity.

THE POINT OF THIS FILE. The baseline this lane argues from is the population
``identifier_shapes`` refused BEFORE REF-056 widened it. Importing the live
module to compute that baseline would be circular: once the widening lands,
the live minter reports 360 refusals, not 2,016, and the "before" column of
the ruling can no longer be reproduced from the artifact that the ruling
changed. (The first draft of this script did exactly that.)

So the pre-widening decision is FROZEN HERE, as literal patterns copied out
of ``identifier_shapes`` as committed -- git blob ``991d7ca4``, the state of
the module before this lane's edits, introduced by commit 908d74bf
(REF-052). Nothing in the baseline path imports refspec at all. The frozen
oracle was validated once, on 2026-08-31, by exec'ing that committed file
straight out of ``git show`` and classifying all 1,004,233 values with both
readers: the two refusal sets were IDENTICAL, member for member (not merely
equal in count). The blob id is the durable reference here -- the branch
moved under this lane mid-measurement, and a commit id would already be
stale; ``git rev-parse HEAD:src/refspec/registry/identifier_shapes.py``
answers 991d7ca4 for as long as that content is what the widening widened.

The live module is imported for ONE thing, at the very end and clearly
labelled: the DELTA check -- that what the live minter still refuses is
exactly the 360 this script's frozen baseline predicts. That direction is
not circular. It is the assertion the ruling actually makes.

Run:  .venv/bin/python research/evidence/fr-short-tails-2026-08-31/scratch/classify_refused.py
Writes: refused_baseline.json, partition_of_360.json (beside this file).
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
PARQUET = (
    REPO
    / "output/registry-real-data-sources/rulespec-stabilization-candidate-final/federal_register.parquet"
)

# --------------------------------------------------------------------------- #
# The frozen pre-widening oracle. Copied literals, deliberately duplicated
# rather than imported -- a duplicate that drifts is the whole point: it must
# state what the module said BEFORE, not what it says now.

_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—―−", "-"))

_FROZEN_MODERN = re.compile(r"\d{4}-\d{3,5}")
_FROZEN_BARE_LEGACY = re.compile(r"\d{2}-\d{3,6}")
_FROZEN_LETTER_FORMS = (
    re.compile(r"[A-Za-z]\d-\d{1,3}"),
    re.compile(r"[A-Za-z]\d{2}-\d{5}"),
    re.compile(r"[A-Za-z]\d{2}-\d{6}"),
    re.compile(r"(?![CcRr])[A-Za-z]\d-\d{4}-\d{3,5}"),
)
#: The prose reader's four forms, which the mint layer consults whole and
#: unconditionally (``_states_a_federal_register_document``). Frozen too: a
#: value the prose reader read was never in ``refused``, license or no.
_FROZEN_PROSE_FORMS = (
    re.compile(r"\d{4}-\d{3,5}"),
    re.compile(r"[Cc]\d-\d{4}-\d{5}"),
    re.compile(r"[Rr]\d-(?:\d{4}-)?\d{3,5}"),
    re.compile(r"[A-Za-z]\d-\d{4,5}"),
)


def frozen_admitted(value: str) -> bool:
    """What ``mint_federal_register_document_iri(v, column_licensed=True)``
    answered before REF-056: ``True`` where it minted anything at all."""

    text = str(value).strip().translate(_DASHES)
    folded = text.upper()
    if _FROZEN_MODERN.fullmatch(folded):
        return True
    if _FROZEN_BARE_LEGACY.fullmatch(folded):
        return True
    if any(pattern.fullmatch(folded) for pattern in _FROZEN_LETTER_FORMS):
        return True
    return any(pattern.fullmatch(text) for pattern in _FROZEN_PROSE_FORMS)


# --------------------------------------------------------------------------- #
# REF-056's two new productions, also frozen here, so the split below is this
# script's own arithmetic rather than a reading of the module it is checking.

_BARE_LEGACY_SHORT_TAIL = re.compile(r"\d{2}-\d{1,2}")
_MODERN_SHORT_TAIL = re.compile(r"\d{4}-\d{1,2}")

# The seven classes the leftover 360 really fall into, measured 2026-08-31.
# Mutually exclusive over that population -- asserted below, not assumed.
_PARTITION: tuple[tuple[str, re.Pattern[str]], ...] = (
    # A collision-disambiguation suffix the aggregator appended; all 224 have
    # their own un-suffixed twin present in this same column.
    ("collision -2 suffix", re.compile(r"\d{2}-\d{3,5}-2")),
    # REF-054's deferred population: the correction form one digit short.
    ("short-tail correction", re.compile(r"[Cc]\d-\d{4}-\d{2,4}")),
    # The printed-page composition defect: the colophon's next word welded on.
    ("colophon-fused", re.compile(r".*(?:Filed|Doc)")),
    # Real ids the publisher prints with an extra hyphenated segment.
    ("extra-hyphen", re.compile(r"\d{2}-\d{2}-\d{2,5}")),
    # Real ids the publisher prints with ONE trailing letter after the digits.
    ("trailing letter", re.compile(r"(?:[A-Za-z]\d|\d{2}|\d{4})-\d+[A-Za-z]")),
    # The one value whose document the publisher numbers something else.
    ("not the publisher's number", re.compile(r"\d{2}-S\d+")),
    ("granule293", re.compile(r"granule293")),
)


def main() -> int:
    if not PARQUET.is_file():
        print(f"missing pinned parquet: {PARQUET}", file=sys.stderr)
        return 2

    values: set[str] = set()
    for batch in pq.ParquetFile(PARQUET).iter_batches(
        columns=["document_number"], batch_size=200_000
    ):
        values.update(v for v in batch.column(0).to_pylist() if v is not None)
    print(f"distinct document_number values: {len(values):,}")
    assert len(values) == 1_004_233, len(values)

    baseline = sorted(v for v in values if not frozen_admitted(v))
    print(f"refused BEFORE REF-056 (frozen oracle): {len(baseline):,}")
    assert len(baseline) == 2_016, len(baseline)

    def folded(value: str) -> str:
        return str(value).strip().translate(_DASHES).upper()

    def tail_lengths(population: list[str]) -> Counter[int]:
        return Counter(len(folded(v).split("-")[-1]) for v in population)

    bare_short = [v for v in baseline if _BARE_LEGACY_SHORT_TAIL.fullmatch(folded(v))]
    modern_short = [v for v in baseline if _MODERN_SHORT_TAIL.fullmatch(folded(v))]
    print(f"  bare-legacy short tail: {len(bare_short):,}  by tail length {dict(tail_lengths(bare_short))}")
    print(f"  modern short tail:      {len(modern_short):,}  by tail length {dict(tail_lengths(modern_short))}")
    assert len(bare_short) == 1_370 and tail_lengths(bare_short) == Counter({1: 112, 2: 1_258})
    assert len(modern_short) == 286 and tail_lengths(modern_short) == Counter({1: 27, 2: 259})

    remaining = sorted(set(baseline) - set(bare_short) - set(modern_short))
    print(f"  still refused after REF-056: {len(remaining):,}")
    assert len(remaining) == 360, len(remaining)

    # The partition of the 360, and its disjointness, measured rather than
    # asserted from the class names.
    classified: dict[str, list[str]] = {name: [] for name, _ in _PARTITION}
    unclassified: list[str] = []
    for value in remaining:
        text = str(value).strip()
        hits = [name for name, pattern in _PARTITION if pattern.fullmatch(text)]
        assert len(hits) <= 1, f"{value} matches {hits} -- the classes are not disjoint"
        if hits:
            classified[hits[0]].append(value)
        else:
            unclassified.append(value)
    assert not unclassified, unclassified

    print("\n  the 360, partitioned:")
    for name, members in classified.items():
        sample = ", ".join(sorted(members)[:3])
        print(f"    {len(members):5,}  {name:<28}  e.g. {sample}")
    assert {name: len(v) for name, v in classified.items()} == {
        "collision -2 suffix": 224,
        "short-tail correction": 99,
        "colophon-fused": 27,
        "extra-hyphen": 4,
        "trailing letter": 4,
        "not the publisher's number": 1,
        "granule293": 1,
    }
    assert sum(len(v) for v in classified.values()) == 360

    # Every -2 value's un-suffixed twin is present, which is what makes
    # "collision suffix" a reading rather than a guess about the shape.
    orphans = [v for v in classified["collision -2 suffix"] if v.strip()[:-2] not in values]
    print(f"    (-2 values whose un-suffixed twin is absent from the column: {len(orphans)})")
    assert not orphans, orphans

    (HERE / "refused_baseline.json").write_text(
        json.dumps(
            {
                "measured": "2026-08-31",
                "parquet": str(PARQUET.relative_to(REPO)),
                "distinct_values": len(values),
                "refused_before_ref_056": baseline,
                "bare_legacy_short_tail": sorted(bare_short),
                "modern_short_tail": sorted(modern_short),
            },
            indent=1,
        )
        + "\n"
    )
    (HERE / "partition_of_360.json").write_text(
        json.dumps({name: sorted(v) for name, v in classified.items()}, indent=1) + "\n"
    )

    # ----------------------------------------------------------------- #
    # THE DELTA CHECK, and the only place the live module is consulted.
    # Not the baseline: the claim that the widening moved exactly the two
    # named populations and nothing else.
    sys.path.insert(0, str(REPO / "src"))
    from refspec.registry.iri_minting import mint_federal_register_document_iri

    live_refused = {
        v for v in values if mint_federal_register_document_iri(v, column_licensed=True) is None
    }
    print(f"\n  live minter refuses: {len(live_refused):,}")
    assert live_refused == set(remaining), "the widening moved something other than the two populations"

    # Global mint safety: no two admitted values share an IRI.
    iris = [
        m.iri
        for m in (
            mint_federal_register_document_iri(v, column_licensed=True) for v in sorted(values)
        )
        if m is not None
    ]
    print(f"  admitted: {len(iris):,}  distinct IRIs: {len(set(iris)):,}")
    assert len(iris) == len(set(iris)) == 1_003_873

    print("\nall assertions held.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
