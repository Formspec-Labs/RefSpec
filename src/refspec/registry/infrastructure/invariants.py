"""Structural invariants shared across registry infrastructure modules.

Today this holds one assertion: acyclicity of a node-to-linked-node graph.
Other adjacent checks exist in the archived reference this module ports from
(``research/evidence/spicy-regs-nuggets-2026-08-27/invariants.py``) but have no
call site in this repository yet, so they are left out. Add them here only
when a real caller needs them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

_WHITE, _GRAY, _BLACK = 0, 1, 2
_UNSEEN = object()


class RegistryInvariantError(ValueError):
    """Raised when a registry structure violates a published invariant."""


def assert_acyclic(edges: Mapping[str, Iterable[str]]) -> None:
    """Assert that ``edges`` (node id -> the node ids it links to) has no cycle.

    ``edges`` need not be resolvable: a linked id absent from ``edges`` is
    simply not visited as a node in its own right. On a cycle, raises
    :class:`RegistryInvariantError` naming the exact chain found, e.g.
    ``"cycle detected: a -> b -> a"``.
    """

    color: dict[str, int] = dict.fromkeys(edges, _WHITE)
    for root in sorted(edges):
        if color[root] != _WHITE:
            continue
        path = [root]
        color[root] = _GRAY
        stack = [iter(sorted(edges[root]))]
        while stack:
            neighbor = next(stack[-1], _UNSEEN)
            if neighbor is _UNSEEN:
                color[path.pop()] = _BLACK
                stack.pop()
                continue
            state = color.get(neighbor)
            if state is None:
                continue
            if state == _GRAY:
                cycle = [*path[path.index(neighbor) :], neighbor]
                raise RegistryInvariantError("cycle detected: " + " -> ".join(cycle))
            if state == _WHITE:
                color[neighbor] = _GRAY
                path.append(neighbor)
                stack.append(iter(sorted(edges[neighbor])))
