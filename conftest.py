"""Make the repository root importable so tests can import ``tools`` modules.

Several test modules import analysis tooling as ``from tools import ...``.
The ``tools`` directory is a namespace package rather than an installed one,
so the repository root must be on ``sys.path`` for those imports to resolve
under pytest's default prepend import mode, which only inserts the test
directory itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The sealed-corpus pass validates all 159 conformance cases in one indivisible
# subprocess. At ~40s (39.96s measured 2026-08-23) it is still the longest
# single test by a wide margin, and pytest-xdist hands work out in collection
# order, so in its natural alphabetical position it is dispatched late and its
# tail becomes serial time at the end of the run. Hoisting it lets it overlap
# everything else: measured 86s -> 52s across the suite.
#
# Missing is not an error. A narrower run legitimately collects some of that
# module without this test, so the hook simply does nothing when it is absent;
# `test_the_hoisted_longest_test_still_exists` is what fails if the id rots.
LONGEST_TEST = "tests/test_atlas_v3_binding.py::test_atlas_v3_binding_and_sealed_corpus_pass"


def pytest_collection_modifyitems(items: list) -> None:
    """Dispatch the suite's longest test first so it overlaps the rest."""

    hoisted = [item for item in items if item.nodeid == LONGEST_TEST]
    if hoisted:
        items[:] = hoisted + [item for item in items if item.nodeid != LONGEST_TEST]
