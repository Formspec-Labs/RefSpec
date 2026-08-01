"""Immutable public views over verified JSON-compatible values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any


def deep_freeze_json(value: Any) -> Any:
    """Recursively freeze JSON mappings and arrays without copying scalars.

    Verified readers use this at their public boundary. Mappings become
    read-only proxies and sequences become tuples. Immutable non-JSON values
    retained alongside those records, such as ``bytes`` and ``Path`` objects,
    pass through unchanged.
    """

    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): deep_freeze_json(child)
                for key, child in value.items()
            }
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(deep_freeze_json(child) for child in value)
    return value


__all__ = ["deep_freeze_json"]
