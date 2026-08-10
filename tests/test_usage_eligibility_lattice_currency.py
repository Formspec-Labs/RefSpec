"""Every RefSpec-side usage-eligibility list must track rulespec's ORDER.

REF-023 item 3 ("typed rights and scope") replaces a hand-rolled, partial
usage-eligibility enum (``release-graph-validation-receipt.schema.json``'s
``minimumUsageEligibility``/``effectiveUsageEligibility``) with a canonical
7-value closed lattice defined once, in ``common.schema.json``'s
``usageEligibility`` ``$def``, and mirrored in
``refspec.binding.USAGE_ELIGIBILITY_ORDER``. The receipt schema deliberately
keeps its narrower 3/1-value enums -- only the top of the lattice is ever a
*reachable* evaluation outcome for an accepted-output gate -- rather than
widening them to the full 7. That choice only stays honest if drift breaks
the build: if rulespec ever renames, removes, or **reorders** a lattice
member RefSpec still names, nothing about JSON Schema validity would catch
it (every RefSpec-side value would still be *some* string, and a set
comparison cannot see a permutation), so this test parses rulespec's own
``usage-eligibility.cue`` and asserts every RefSpec-side list matches it as
an ORDERED sequence, following the live-checkout pattern in
``test_rulespec_vocabulary_currency.py``.

The CUE comment is explicit that ORDER is normative -- "the lattice ORDER is
normative -- consumers MAY narrow (move down), MUST NOT broaden (move up)"
-- and every narrow-only/floor/ceiling comparison in this codebase
(accepted_output.py, subject_emission.py, vocabulary.py's open-label
clamp) is a *rank* comparison keyed off that order. A set-equality check
would pass on a rulespec revision that silently transposed two ranks and
break every one of those comparisons without this test noticing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from refspec import binding, managed_release, release_graph
from tests.test_rulespec_vocabulary_currency import (
    _RKAF_COMPACT_IRI,
    discover_rulespec_checkout,
)

REFSPEC_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REFSPEC_ROOT / "bindings" / "json" / "1.0" / "schemas"
COMMON_SCHEMA = SCHEMA_ROOT / "common.schema.json"
RECEIPT_SCHEMA = SCHEMA_ROOT / "release-graph-validation-receipt.schema.json"


def _rulespec_usage_eligibility_order(rulespec_dir: Path) -> tuple[str, ...]:
    """The closed lattice in rulespec's own declared ORDER, parsed not scanned.

    ``usage-eligibility.cue`` contains nothing but a package clause, comments,
    and the ``#UsageEligibility`` disjunction, and the comments never spell a
    member with its ``rkaf:`` prefix (they read "notEligible", not
    "rkaf:notEligible") -- so a plain ordered scan of every ``rkaf:`` compact
    IRI in the file yields exactly the disjunction's members in declaration
    order, with no block-boundary parsing needed.
    """

    path = rulespec_dir / "constraints" / "core" / "usage-eligibility.cue"
    text = path.read_text(encoding="utf-8")
    order = tuple(f"rkaf:{name}" for name in _RKAF_COMPACT_IRI.findall(text))
    assert order, f"found no rkaf: terms in {path} -- the file looks empty or moved"
    return order


def _output_profile_permission_base_order() -> tuple[str, ...]:
    schema = json.loads(COMMON_SCHEMA.read_text(encoding="utf-8"))
    return tuple(schema["$defs"]["usageEligibility"]["enum"])


def _receipt_evaluation_values() -> tuple[set[str], set[str]]:
    schema = json.loads(RECEIPT_SCHEMA.read_text(encoding="utf-8"))
    evaluation = schema["properties"]["authorizationEvaluations"]["items"]["properties"]
    minimum = {evaluation["minimumUsageEligibility"]["const"]}
    effective = set(evaluation["effectiveUsageEligibility"]["enum"])
    return minimum, effective


def _require_rulespec() -> Path:
    rulespec_dir = discover_rulespec_checkout()
    if rulespec_dir is None:
        pytest.skip(
            "no Rulespec checkout found (set REFSPEC_RULESPEC_CHECKOUT or "
            "clone Rulespec to ~/Work/rulespec) -- skipping the usage-eligibility "
            "lattice currency check"
        )
    return rulespec_dir


def test_common_schema_usage_eligibility_matches_the_rulespec_lattice_in_order() -> None:
    """The canonical closed enum is a full, order-preserving mirror."""

    rulespec_dir = _require_rulespec()
    upstream = _rulespec_usage_eligibility_order(rulespec_dir)

    assert _output_profile_permission_base_order() == upstream


def test_binding_py_usage_eligibility_order_matches_the_rulespec_lattice_in_order() -> None:
    """The Python-side lattice order used by vocabulary.py and accepted_output.py."""

    rulespec_dir = _require_rulespec()
    upstream = _rulespec_usage_eligibility_order(rulespec_dir)

    assert binding.USAGE_ELIGIBILITY_ORDER == upstream
    assert binding.USAGE_ELIGIBILITY_VALUES == set(upstream)
    assert len(binding.USAGE_ELIGIBILITY_ORDER) == len(set(upstream)), (
        "USAGE_ELIGIBILITY_ORDER repeats a value -- the ORDER tuple must be a "
        "bijection with the lattice, not just cover it"
    )


def test_receipt_evaluation_enums_are_a_subset_of_the_rulespec_lattice() -> None:
    """The receipt's deliberately-narrower enums must still only name real values.

    ``minimumUsageEligibility`` and ``effectiveUsageEligibility`` stay at 1 and
    3 reachable values on purpose (see module docstring); this only asserts
    they never name a value rulespec does not.
    """

    rulespec_dir = _require_rulespec()
    upstream = set(_rulespec_usage_eligibility_order(rulespec_dir))

    minimum, effective = _receipt_evaluation_values()
    assert minimum <= upstream
    assert effective <= upstream


def test_release_graph_authorized_levels_are_the_top_of_the_lattice_in_order() -> None:
    """release_graph.py:93's eligibility list, pinned to Finding 1's prior art.

    ``AUTHORIZED_LEVELS`` is not an arbitrary 3-value subset: it is exactly
    the top three ranks of the 7-value lattice, in the lattice's own order,
    and ``AUTHORIZATION_MINIMUM`` is exactly the lowest of those three. If
    rulespec ever reordered the lattice, this pins that ``AUTHORIZED_LEVELS``
    would silently stop being "the top" without this test.
    """

    rulespec_dir = _require_rulespec()
    upstream = _rulespec_usage_eligibility_order(rulespec_dir)

    assert set(release_graph.AUTHORIZED_LEVELS) <= set(upstream)
    assert release_graph.AUTHORIZED_LEVELS == upstream[-len(release_graph.AUTHORIZED_LEVELS) :]
    assert release_graph.AUTHORIZATION_MINIMUM == release_graph.AUTHORIZED_LEVELS[0]


def test_managed_release_authorized_usage_levels_are_a_subset_of_the_lattice() -> None:
    """managed_release.py:124's independent copy of the same reachable band."""

    rulespec_dir = _require_rulespec()
    upstream = set(_rulespec_usage_eligibility_order(rulespec_dir))

    assert managed_release._AUTHORIZED_USAGE_LEVELS <= upstream
    assert managed_release._AUTHORIZED_USAGE_LEVELS == set(release_graph.AUTHORIZED_LEVELS)


def test_a_lattice_member_removed_upstream_would_fail_this_test(
    tmp_path: Path,
) -> None:
    """Prove the order check actually fires -- not just checks non-emptiness."""

    narrowed = tmp_path / "constraints" / "core"
    narrowed.mkdir(parents=True)
    (narrowed / "usage-eligibility.cue").write_text(
        'package rkaf\n\n#UsageEligibility: "rkaf:notEligible" | "rkaf:searchOnly"\n',
        encoding="utf-8",
    )

    upstream = _rulespec_usage_eligibility_order(tmp_path)
    assert upstream == ("rkaf:notEligible", "rkaf:searchOnly")
    assert _output_profile_permission_base_order() != upstream


def test_a_permuted_lattice_upstream_would_fail_this_test(
    tmp_path: Path,
) -> None:
    """Prove ORDER, not just membership, is checked: a same-set permutation must fire.

    Swapping two adjacent members keeps the set identical to the real
    lattice -- a set-equality check (what this test replaced) would pass.
    The ordered-tuple comparison this module now uses must not.
    """

    reordered = tmp_path / "constraints" / "core"
    reordered.mkdir(parents=True)
    reordered_cue = (
        'package rkaf\n\n'
        '#UsageEligibility: "rkaf:notEligible" | "rkaf:searchOnly" | "rkaf:reviewQueueOnly" |\n'
        '\t"rkaf:draftGenerationAllowed" | "rkaf:publicationAllowed" | "rkaf:localOperationalUse" |\n'
        '\t"rkaf:officialUse"\n'
    )
    (reordered / "usage-eligibility.cue").write_text(reordered_cue, encoding="utf-8")

    upstream = _rulespec_usage_eligibility_order(tmp_path)
    assert set(upstream) == binding.USAGE_ELIGIBILITY_VALUES, (
        "the fixture must permute, not change, the real member set"
    )
    assert upstream != binding.USAGE_ELIGIBILITY_ORDER
    assert _output_profile_permission_base_order() != upstream
