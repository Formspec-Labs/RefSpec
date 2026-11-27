"""Backward-compatible facade re-exporting :mod:`spicy_docs.interpretation.identifier_shapes`.

The canonical identifier-shape detectors and normalizers moved to ``spicy-docs``
so every stack consumer shares one implementation. This module preserves the
historical ``refspec.registry.identifier_shapes`` import path and proxies reads
and test-time attribute patches to ``spicy_docs.interpretation.identifier_shapes``.
"""

from __future__ import annotations

import sys
from types import ModuleType

from spicy_docs.interpretation import identifier_shapes as _impl

__all__ = list(_impl.__all__)

_LOCAL_ATTRS = frozenset(
    {
        "__all__",
        "__annotations__",
        "__builtins__",
        "__cached__",
        "__doc__",
        "__file__",
        "__loader__",
        "__name__",
        "__package__",
        "__spec__",
        "_LOCAL_ATTRS",
        "_FacadeModule",
        "_impl",
    }
)


class _FacadeModule(ModuleType):
    def __getattr__(self, name: str) -> object:
        try:
            return getattr(_impl, name)
        except AttributeError:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

    def __setattr__(self, name: str, value: object) -> None:
        if name in _LOCAL_ATTRS or (name.startswith("__") and name.endswith("__")):
            super().__setattr__(name, value)
            return
        if hasattr(_impl, name):
            setattr(_impl, name, value)
        else:
            super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if name in _LOCAL_ATTRS or (name.startswith("__") and name.endswith("__")):
            super().__delattr__(name)
            return
        if hasattr(_impl, name):
            delattr(_impl, name)
        else:
            super().__delattr__(name)

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | set(dir(_impl)))


sys.modules[__name__].__class__ = _FacadeModule
