"""Backward-compatible facade re-exporting :mod:`spicy_docs.interpretation.citation_grammar`.

The canonical citation grammar moved to ``spicy-docs`` so every stack consumer
shares one implementation. This module preserves the historical
``refspec.registry.citation_grammar`` import path and synchronizes attribute
patches (both ``monkeypatch.setattr`` and ``unittest.mock.patch.object``) to
``spicy_docs.interpretation.citation_grammar`` (including the legacy private
alias ``_usc_section_key`` for ``_usc_section_order``).
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

globals().update(
    {name: value for name, value in vars(_impl).items() if not (name.startswith("__") and name.endswith("__"))}
)
_usc_section_key = _impl._usc_section_order


class _FacadeModule(ModuleType):
    def __getattr__(self, name: str) -> object:
        target = _ALIASES.get(name, name)
        try:
            return getattr(_impl, target)
        except AttributeError:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name in _LOCAL_ATTRS or (name.startswith("__") and name.endswith("__")):
            return
        target = _ALIASES.get(name, name)
        if hasattr(_impl, target):
            setattr(_impl, target, value)

    def __delattr__(self, name: str) -> None:
        super().__delattr__(name)
        if name in _LOCAL_ATTRS or (name.startswith("__") and name.endswith("__")):
            return
        target = _ALIASES.get(name, name)
        if hasattr(_impl, target):
            delattr(_impl, target)

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | set(dir(_impl)) | set(_ALIASES))


sys.modules[__name__].__class__ = _FacadeModule
