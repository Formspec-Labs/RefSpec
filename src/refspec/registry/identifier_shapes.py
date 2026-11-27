"""Backward-compatible facade re-exporting :mod:`spicy_docs.interpretation.identifier_shapes`.

The canonical identifier-shape detectors and normalizers moved to ``spicy-docs``
so every stack consumer shares one implementation. This module preserves the
historical ``refspec.registry.identifier_shapes`` import path and synchronizes
attribute patches and deletions (both ``monkeypatch`` and
``unittest.mock.patch.object``) to ``spicy_docs.interpretation.identifier_shapes``.
"""

from __future__ import annotations

import sys as _sys
from types import ModuleType as _ModuleType

from spicy_docs.interpretation import identifier_shapes as _impl

__all__ = list(_impl.__all__)

_DELEGATED_ATTRS = frozenset(name for name in vars(_impl) if not (name.startswith("__") and name.endswith("__")))
_FACADE_INTERNALS = frozenset(
    {
        "_DELEGATED_ATTRS",
        "_FACADE_INTERNALS",
        "_FacadeModule",
        "_LOCAL_ATTRS",
        "_ModuleType",
        "_impl",
        "_sys",
    }
)
_LOCAL_ATTRS = _FACADE_INTERNALS | frozenset(
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
    }
)

globals().update({name: getattr(_impl, name) for name in _DELEGATED_ATTRS})


class _FacadeModule(_ModuleType):
    def __getattr__(self, name: str) -> object:
        try:
            return getattr(_impl, name)
        except AttributeError:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name in _LOCAL_ATTRS or (name.startswith("__") and name.endswith("__")):
            return
        if name in _DELEGATED_ATTRS or hasattr(_impl, name):
            setattr(_impl, name, value)

    def __delattr__(self, name: str) -> None:
        super().__delattr__(name)
        if name in _LOCAL_ATTRS or (name.startswith("__") and name.endswith("__")):
            return
        if hasattr(_impl, name):
            delattr(_impl, name)

    def __dir__(self) -> list[str]:
        return sorted((set(super().__dir__()) - _FACADE_INTERNALS) | set(dir(_impl)))


_sys.modules[__name__].__class__ = _FacadeModule
