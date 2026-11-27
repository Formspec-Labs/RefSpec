"""Backward-compatible facade re-exporting :mod:`spicy_docs.interpretation.citation_grammar`.

The canonical citation grammar moved to ``spicy-docs`` so every stack consumer
shares one implementation. This module preserves the historical
``refspec.registry.citation_grammar`` import path and proxies reads and
test-time attribute patches to ``spicy_docs.interpretation.citation_grammar``
(including the legacy private alias ``_usc_section_key`` for
``_usc_section_order``).
"""

from __future__ import annotations

import sys
from types import ModuleType

from spicy_docs.interpretation import citation_grammar as _impl

__all__ = list(_impl.__all__)

_ALIASES = {"_usc_section_key": "_usc_section_order"}
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
        "_ALIASES",
        "_LOCAL_ATTRS",
        "_FacadeModule",
        "_impl",
    }
)


class _FacadeModule(ModuleType):
    def __getattr__(self, name: str) -> object:
        target = _ALIASES.get(name, name)
        try:
            return getattr(_impl, target)
        except AttributeError:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

    def __setattr__(self, name: str, value: object) -> None:
        if name in _LOCAL_ATTRS or (name.startswith("__") and name.endswith("__")):
            super().__setattr__(name, value)
            return
        target = _ALIASES.get(name, name)
        if hasattr(_impl, target):
            setattr(_impl, target, value)
        else:
            super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if name in _LOCAL_ATTRS or (name.startswith("__") and name.endswith("__")):
            super().__delattr__(name)
            return
        target = _ALIASES.get(name, name)
        if hasattr(_impl, target):
            delattr(_impl, target)
        else:
            super().__delattr__(name)

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | set(dir(_impl)) | set(_ALIASES))


sys.modules[__name__].__class__ = _FacadeModule
