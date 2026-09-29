"""Make the repository root importable, tier the suite, and point real-data tests at their pinned inputs.

``tools`` is a namespace package rather than an installed one, so the
repository root must be on ``sys.path`` for pytest's default prepend import
mode, which only inserts the test directory itself.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

import pytest

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# A shared assertion helper under tests/ is not a test module, so pytest would
# not rewrite its asserts; a failure there would print a bare AssertionError.
pytest.register_assert_rewrite("writer_path_equivalence")

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

#: Every test belongs to exactly one tier, and each tier is one job's selection
#: (REF-071). ``fast`` is `make test-package`, the one tier CI runs; ``slow`` is
#: `make test-slow`, run locally after `make build-derived`; ``full-atlas``
#: constructs the complete Atlas topology (~10 GB, tens of minutes) and is
#: `make test-full-atlas`, also local. One function rather than three
#: `-m` strings kept in step by hand, so the tiers partition the suite by
#: construction; tests/test_test_tiers.py checks that a job runs each tier.
TIERS = ("fast", "slow", "full-atlas")


def tier_of(item: pytest.Item) -> str:
    """The one tier a collected test belongs to."""

    if item.get_closest_marker("full_atlas"):
        return "full-atlas"
    if item.get_closest_marker("slow") or item.get_closest_marker("release_tier"):
        return "slow"
    return "fast"


#: The consolidated LCSH release (`load_lcsh_consolidated_release`, 514,837
#: resources) costs about 70-90 s and 4 GB to load, once per process: it is
#: lru-cached, and a process is one xdist worker. Every fast-tier test that
#: needs it carries this mark and `make test-package` runs `--dist loadgroup`,
#: so one worker loads it once. Under plain `--dist load` the tests of its two
#: modules could land on two workers, each paying the load, and whether they
#: did moved with the test count: on a loaded host that second load pushed the
#: tier past its runaway guard.
LCSH_RELEASE_GROUP = pytest.mark.xdist_group("lcsh-consolidated-release")


#: The variables that tell git WHICH repository, index, object store, namespace or
#: config file to use. Run from a linked worktree, `git rebase --exec` exports
#: GIT_DIR=<main>/.git/worktrees/<name> (git 2.50, measured 2026-09-27), whose
#: config is the main checkout's, and GIT_DIR outranks `git -C`: a test's
#: `git -C <tmp> config` or `commit` then writes into the caller's repository,
#: as one wrote into this repository's `.git/config` that day. Named rather
#: than every ``GIT_*``, so GIT_TRACE, GIT_SSH and GIT_EDITOR, which choose no
#: repository, still reach a developer's debugging run.
GIT_REPOSITORY_VARIABLES = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
    "GIT_CONFIG",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
)


@pytest.fixture(scope="session", autouse=True)
def _no_inherited_git_repository() -> Iterator[None]:
    """Run the whole session with no inherited git repository, so every git call answers for the directory it names.

    What this cannot see: a git call made before the first test's setup, at
    import or collection time; none exists today. tests/test_git_environment.py
    proves it in a subprocess whose parent environment points GIT_DIR at a
    throwaway repository.
    """

    with pytest.MonkeyPatch.context() as patch:
        for name in GIT_REPOSITORY_VARIABLES:
            patch.delenv(name, raising=False)
        yield


def missing_pinned_input(reason: str) -> NoReturn:
    """Fail a test whose pinned input or built artifact is absent: that is setup, not a skip (REF-071)."""

    pytest.fail(f"{reason} -- run `make fetch-pinned-inputs` (and `make build-derived` for built artifacts)", pytrace=False)


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Fail, before the test body, any test whose ``pinned_input`` condition says an input is absent.

    ``@pytest.mark.pinned_input(condition, reason=...)`` takes ``skipif``'s
    arguments, so a presence guard keeps its condition and its words and
    changes only what an absent input means.
    """

    for mark in item.iter_markers("pinned_input"):
        condition = mark.args[0] if mark.args else mark.kwargs.get("condition", True)
        if condition:
            missing_pinned_input(mark.kwargs.get("reason", "a pinned input is absent"))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--tier", choices=TIERS, help="run one tier of the suite (see conftest.TIERS)")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Tier built-artifact readers as slow, select ``--tier``, then dispatch the longest test first.

    A test that reads a derived artifact runs where ``make build-derived`` has
    written it, and fails there if it is missing; the fast tier deselects it
    instead of skipping it. ``tryfirst`` puts the marker in place before ``-m``
    selection reads it, so ``-m slow`` still means what the tier means.
    """

    for item in items:
        if item.get_closest_marker("reads_built_artifact") and not item.get_closest_marker("no_artifact"):
            item.add_marker(pytest.mark.slow)
    tier = config.getoption("tier")
    if tier:
        deselected = [item for item in items if tier_of(item) != tier]
        if deselected:
            config.hook.pytest_deselected(items=deselected)
            items[:] = [item for item in items if tier_of(item) == tier]
    hoisted = [item for item in items if item.nodeid == LONGEST_TEST]
    if hoisted:
        items[:] = hoisted + [item for item in items if item.nodeid != LONGEST_TEST]


def pytest_configure(config: pytest.Config) -> None:
    """Point every opt-in real-data test at its pinned input under ``output/``.

    ``make fetch-pinned-inputs`` puts the inputs in place, verified; the
    real-data audit sets the same variables from the same source-link
    manifest, so a value the caller already chose still wins. An input that is
    absent fails its test on the path rather than skipping it.
    """

    from tools.verify_registry_audit import DEFAULT_SOURCE_MANIFEST, load_source_manifest, pinned_input_environment

    manifest = load_source_manifest(DEFAULT_SOURCE_MANIFEST, ROOT)
    for variable, path in pinned_input_environment(ROOT, manifest).items():
        os.environ.setdefault(variable, path)
