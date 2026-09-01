"""Tests for the shared registry acyclicity invariant.

Covers ``assert_acyclic`` directly (acyclic, empty, and diamond graphs pass; a
2-node cycle and a self-loop fail and name the cycle they found), the
replacement oracle battery required when a running check is replaced, and
integration tests proving the managed vocabulary bundle's refresh path
(``reseal_linked_ref_records``) actually routes real graphs through it, rather
than merely narrating acyclicity in a docstring.

``assert_acyclic`` replaced a bespoke self-reference check inside
``reseal_linked_ref_records``. Per AGENTS.md, that removed check survives here
as a test-only oracle -- copied, never imported -- and the battery below proves
the replacement rejects everything the oracle rejected, over adversarial graphs
and randomized small ones. The replacement is deliberately stricter: it also
rejects cycles of length two or more, which the oracle could not see. Those are
the only permitted divergences, and they are frozen as such below.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping

import pytest

import refspec.registry.infrastructure.managed_vocabulary_bundle as bundle_module
from refspec.registry.infrastructure.invariants import (
    RegistryInvariantError,
    assert_acyclic,
)
from refspec.registry.infrastructure.managed_vocabulary_bundle import (
    ManagedVocabularyBundleError,
    reseal_linked_ref_records,
)
from refspec.vocabulary import seal_payload


def _record(identifier: str) -> dict[str, object]:
    return seal_payload(
        {
            "type": "urn:ref:type:RunReceipt",
            "id": identifier,
            "version": "1.0",
        }
    )


def _reference(record: Mapping[str, object]) -> dict[str, object]:
    """One exact local ``{id, digest}`` reference to ``record``."""

    return {"id": record["id"], "digest": record["canonicalPayloadDigest"]}


def test_an_acyclic_graph_passes() -> None:
    assert_acyclic({"a": ["b"], "b": ["c"], "c": []})


def test_an_empty_graph_passes() -> None:
    assert_acyclic({})


def test_a_diamond_shared_descendant_passes() -> None:
    """Two paths converging on one shared descendant is not a cycle."""

    assert_acyclic({"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []})


def test_a_two_node_cycle_fails_naming_the_cycle() -> None:
    with pytest.raises(RegistryInvariantError, match=r"a -> b -> a"):
        assert_acyclic({"a": ["b"], "b": ["a"]})


def test_a_self_loop_fails_naming_the_node() -> None:
    with pytest.raises(RegistryInvariantError, match=r"a -> a"):
        assert_acyclic({"a": ["a"]})


def test_a_dangling_reference_to_a_node_outside_the_map_is_not_a_cycle() -> None:
    """``assert_acyclic`` only judges the graph it is given; resolvability is
    a separate concern its callers already enforce before invoking it."""

    assert_acyclic({"a": ["nowhere"]})


# --------------------------------------------------------------------------
# Replacement oracle battery (AGENTS.md: a replaced check survives as a
# test-only oracle, and verdict agreement is proven by mutation, not by clean
# data alone).
# --------------------------------------------------------------------------


def _self_reference_oracle(edges: Mapping[str, Iterable[str]]) -> frozenset[str]:
    """The check ``assert_acyclic`` replaced, copied verbatim from the removed
    body of ``reseal_linked_ref_records`` (git: the pre-wire-in revision of
    ``managed_vocabulary_bundle.py``). Copied, not imported: importing the
    thing under replacement would make the comparison circular."""

    return frozenset(
        identifier
        for identifier, dependencies in edges.items()
        if identifier in dependencies
    )


def _rejects(edges: Mapping[str, Iterable[str]]) -> bool:
    """The replacement's verdict, as a boolean."""

    try:
        assert_acyclic(edges)
    except RegistryInvariantError:
        return True
    return False


def _brute_force_has_cycle(edges: Mapping[str, Iterable[str]]) -> bool:
    """Third opinion for the small randomized graphs: exhaustive simple-path
    enumeration, with no coloring and no shared code with the DFS under test."""

    def walk(node: str, path: frozenset[str]) -> bool:
        for neighbor in edges.get(node, ()):
            if neighbor not in edges:
                continue
            if neighbor in path:
                return True
            if walk(neighbor, path | {neighbor}):
                return True
        return False

    return any(walk(node, frozenset({node})) for node in edges)


# Adversarial graphs, named. The names in _FROZEN_DIVERGENCES are the cases
# where the replacement rejects and the oracle accepts; an unlisted divergence
# fails the battery instead of becoming a diff nobody reads.
_ADVERSARIAL_GRAPHS: dict[str, dict[str, list[str]]] = {
    "empty": {},
    "single edgeless node": {"a": []},
    "chain": {"a": ["b"], "b": ["c"], "c": []},
    "diamond": {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []},
    "dangling reference only": {"a": ["nowhere"]},
    "self loop on the only node": {"a": ["a"]},
    # The concrete miss a first-root-only DFS would let through: the self-loop
    # hangs off a later root, and reseal's dependency map then strips the
    # self-dependency, admitting a record the oracle rejected.
    "self loop on a late root": {"a": [], "z": ["z"]},
    "self loop behind several clean roots": {"a": [], "b": ["a"], "c": [], "z": ["z"]},
    "self loop reachable only from a later component": {"a": [], "m": ["z"], "z": ["z"]},
    "self loop plus dangling reference": {"a": ["nowhere"], "z": ["z", "nowhere"]},
    "self loop inside a larger acyclic graph": {"a": ["b"], "b": ["c"], "c": [], "z": ["z"]},
    "two node cycle": {"a": ["b"], "b": ["a"]},
    "three node cycle behind a clean root": {"a": [], "p": ["q"], "q": ["r"], "r": ["p"]},
    "two node cycle among later roots only": {"a": [], "b": [], "y": ["z"], "z": ["y"]},
}

_FROZEN_DIVERGENCES = frozenset(
    {
        "two node cycle",
        "three node cycle behind a clean root",
        "two node cycle among later roots only",
    }
)


@pytest.mark.parametrize("name", sorted(_ADVERSARIAL_GRAPHS))
def test_replacement_rejects_everything_the_old_oracle_rejected(name: str) -> None:
    """Verdict comparison over adversarial graphs: the replacement must reject
    every graph the removed self-reference check rejected, and may reject more
    only in the frozen divergence classes."""

    edges = _ADVERSARIAL_GRAPHS[name]
    oracle_rejects = bool(_self_reference_oracle(edges))
    replacement_rejects = _rejects(edges)

    if oracle_rejects:
        assert replacement_rejects, (
            f"{name!r}: the old oracle rejected "
            f"{sorted(_self_reference_oracle(edges))} and assert_acyclic accepted it"
        )
    diverges = replacement_rejects and not oracle_rejects
    assert diverges == (name in _FROZEN_DIVERGENCES), (
        f"{name!r}: unlisted divergence -- oracle_rejects={oracle_rejects}, "
        f"replacement_rejects={replacement_rejects}"
    )


def test_the_oracle_battery_exercises_both_verdicts() -> None:
    """Guard against a battery that proves agreement vacuously."""

    verdicts = {
        name: (
            bool(_self_reference_oracle(edges)),
            _rejects(edges),
        )
        for name, edges in _ADVERSARIAL_GRAPHS.items()
    }
    assert sum(oracle for oracle, _ in verdicts.values()) >= 5
    assert sum(
        replacement and not oracle for oracle, replacement in verdicts.values()
    ) == len(_FROZEN_DIVERGENCES)


def test_replacement_agrees_with_the_oracle_over_randomized_small_graphs() -> None:
    """Randomized battery: over small graphs with self-loops, multi-node
    cycles, and dangling references, the replacement rejects a superset of the
    oracle's rejections, and every divergence is a cycle of length >= 2 with no
    self-loop -- the one class the removed check structurally could not see."""

    rng = random.Random(20260831)
    node_pool = "abcde"
    oracle_rejections = 0
    divergences = 0

    for _ in range(600):
        size = rng.randint(1, 5)
        nodes = list(node_pool[:size])
        edges = {
            node: sorted(
                {target for target in nodes if rng.random() < 0.28}
                | ({"nowhere"} if rng.random() < 0.15 else set())
            )
            for node in nodes
        }
        oracle_rejects = bool(_self_reference_oracle(edges))
        replacement_rejects = _rejects(edges)

        if oracle_rejects:
            oracle_rejections += 1
            assert replacement_rejects, f"assert_acyclic accepted {edges} with a self-loop"
        assert replacement_rejects == _brute_force_has_cycle(edges), (
            f"assert_acyclic disagreed with exhaustive path search on {edges}"
        )
        if replacement_rejects and not oracle_rejects:
            divergences += 1
            assert _brute_force_has_cycle(edges), f"unexplained divergence on {edges}"
            assert not any(node in targets for node, targets in edges.items()), (
                f"divergence on {edges} is not the frozen multi-node-cycle class"
            )

    assert oracle_rejections >= 50, oracle_rejections
    assert divergences >= 20, divergences


# --------------------------------------------------------------------------
# Wire-in: the real refresh path routes real graphs through the invariant.
# --------------------------------------------------------------------------


def test_bundle_refresh_calls_assert_acyclic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove the wire-in: the refresh path hands the shared invariant the
    actual linked-reference graph, edges included -- not just narrates one in
    a docstring."""

    calls: list[dict[str, frozenset[str]]] = []
    real_assert_acyclic = bundle_module.assert_acyclic

    def spy(edges: dict[str, frozenset[str]]) -> None:
        calls.append(edges)
        real_assert_acyclic(edges)

    monkeypatch.setattr(bundle_module, "assert_acyclic", spy)

    leaf = _record("urn:test:record:leaf")
    trunk = _record("urn:test:record:trunk")
    trunk["input"] = _reference(leaf)
    branch = _record("urn:test:record:branch")
    branch["input"] = [_reference(leaf), _reference(trunk)]

    reseal_linked_ref_records((branch, trunk, leaf))

    assert len(calls) == 1
    assert calls[0] == {
        "urn:test:record:leaf": frozenset(),
        "urn:test:record:trunk": frozenset({"urn:test:record:leaf"}),
        "urn:test:record:branch": frozenset(
            {"urn:test:record:leaf", "urn:test:record:trunk"}
        ),
    }


def test_bundle_refresh_rejects_a_self_referencing_record_naming_the_cycle() -> None:
    """A crafted cyclic fixture through the real refresh path must fail,
    proving the assertion is load-bearing rather than decorative."""

    record = _record("urn:test:record:self")
    record["input"] = _reference(record)

    with pytest.raises(
        ManagedVocabularyBundleError,
        match=r"digest cycle.*urn:test:record:self -> urn:test:record:self",
    ) as raised:
        reseal_linked_ref_records((record,))

    cause = raised.value.__cause__
    assert isinstance(cause, RegistryInvariantError)
    assert str(cause) == "cycle detected: urn:test:record:self -> urn:test:record:self"


def test_bundle_refresh_rejects_a_multi_record_cycle_behind_a_clean_record() -> None:
    """A two-record cycle -- the class the removed self-reference check could
    not see -- reaching the invariant from a later root, with an acyclic
    record sorting ahead of it. The failure must come from ``assert_acyclic``
    (carried as ``__cause__``), not from the downstream topological sort's
    fallback, which reports the same words with no chain and no cause."""

    clean = _record("urn:test:record:alpha")
    left = _record("urn:test:record:mid")
    right = _record("urn:test:record:zed")
    left["input"] = _reference(right)
    right["input"] = _reference(left)

    with pytest.raises(ManagedVocabularyBundleError) as raised:
        reseal_linked_ref_records((clean, left, right))

    assert "linked REF records contain a digest cycle" in str(raised.value)
    cause = raised.value.__cause__
    assert isinstance(cause, RegistryInvariantError), (
        f"expected the invariant to raise, got __cause__={cause!r} "
        f"and message {str(raised.value)!r}"
    )
    assert str(cause) == (
        "cycle detected: urn:test:record:mid -> urn:test:record:zed "
        "-> urn:test:record:mid"
    )
    assert str(raised.value) == f"linked REF records contain a digest cycle: {cause}"
