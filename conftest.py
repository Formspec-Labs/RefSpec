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

import pytest

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The sealed-corpus pass is one indivisible subprocess that validates all 110
# Atlas 3.0 conformance cases. At ~205s it is not merely the slowest test in
# the suite, it is four times everything else put together (~49s under
# `-n auto`), so it alone sets the wall clock and no amount of extra workers
# moves it. pytest-xdist hands tests out in collection order, and in its
# natural alphabetical position this one is not dispatched until roughly 35s
# of other work has already gone out -- 35s that then hang off the end of the
# run as pure serial tail. Hoisting it to the front costs nothing and lets it
# overlap the entire rest of the suite instead.
LONGEST_TEST = "tests/test_atlas_v3_binding.py::test_atlas_v3_binding_and_sealed_corpus_pass"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Dispatch the suite's one dominating test first so it overlaps the rest."""

    owning_module = LONGEST_TEST.split("::", 1)[0]
    if not any(item.nodeid.split("::", 1)[0] == owning_module for item in items):
        # A narrower run that does not collect the module at all; nothing to do.
        return
    hoisted = [item for item in items if item.nodeid == LONGEST_TEST]
    if not hoisted:
        raise pytest.UsageError(
            f"conftest.py schedules {LONGEST_TEST} first because it dominates the "
            "suite's wall clock, but no such test was collected. It was renamed or "
            "removed -- point LONGEST_TEST at the new slowest test, or delete the "
            "hook if nothing dominates any more."
        )
    items[:] = hoisted + [item for item in items if item.nodeid != LONGEST_TEST]
