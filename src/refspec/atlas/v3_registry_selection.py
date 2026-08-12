"""Fail-closed selection helpers for Atlas 3 registry release loaders."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Protocol


class _KeyedRelease(Protocol):
    @property
    def key(self) -> str: ...


def normalize_only_keys(
    only_keys: Collection[str] | None,
    *,
    allowed_keys: Collection[str],
    loader_name: str,
) -> frozenset[str] | None:
    """Normalize a caller's release selection and reject unknown keys."""

    if only_keys is None:
        return None
    if isinstance(only_keys, (str, bytes)):
        raise TypeError(f"{loader_name} only_keys must be a collection of release keys")
    requested = frozenset(only_keys)
    if any(not isinstance(key, str) or not key for key in requested):
        raise TypeError(f"{loader_name} only_keys must contain non-empty strings")
    unknown = requested - frozenset(allowed_keys)
    if unknown:
        raise ValueError(f"{loader_name} does not know release keys: {sorted(unknown)!r}")
    return requested


def wants_group(
    requested_keys: frozenset[str] | None,
    group_keys: Collection[str],
) -> bool:
    """Return whether a declared loader group should parse its source bytes."""

    return requested_keys is None or bool(requested_keys.intersection(group_keys))


def select_declared_group[ReleaseT: _KeyedRelease](
    releases: Iterable[ReleaseT],
    *,
    declared_keys: Collection[str],
    requested_keys: frozenset[str] | None,
    loader_name: str,
) -> tuple[ReleaseT, ...]:
    """Check a loader group's topology and retain only requested releases."""

    loaded = tuple(releases)
    observed = [release.key for release in loaded]
    observed_set = frozenset(observed)
    declared = frozenset(declared_keys)
    if len(observed) != len(observed_set):
        raise ValueError(f"{loader_name} produced duplicate release keys")
    if observed_set != declared:
        missing = sorted(declared - observed_set)
        unexpected = sorted(observed_set - declared)
        raise ValueError(
            f"{loader_name} release topology differs; missing={missing!r}, "
            f"unexpected={unexpected!r}"
        )
    if requested_keys is None:
        return loaded
    return tuple(release for release in loaded if release.key in requested_keys)


__all__ = ["normalize_only_keys", "select_declared_group", "wants_group"]
