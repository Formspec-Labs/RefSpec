"""Backward-compatible facade re-exporting :mod:`spicy_docs.interpretation.citation_grammar`.

The canonical citation grammar moved to ``spicy-docs`` so every stack consumer
shares one implementation. This module preserves the historical
``refspec.registry.citation_grammar`` import path and synchronizes attribute
patches and deletions (both ``monkeypatch`` and ``unittest.mock.patch.object``)
to ``spicy_docs.interpretation.citation_grammar`` (including bidirectional
sync for the legacy private alias ``_usc_section_key`` <-> ``_usc_section_order``).
"""

from __future__ import annotations

import sys as _sys
from types import ModuleType as _ModuleType

from spicy_docs.interpretation import citation_grammar as _impl

__all__ = list(_impl.__all__)

_ALIASES = {"_usc_section_key": "_usc_section_order"}
_ALIAS_GROUP = ("_usc_section_key", "_usc_section_order")
_DELEGATED_ATTRS = frozenset(name for name in vars(_impl) if not (name.startswith("__") and name.endswith("__")))
_FACADE_INTERNALS = frozenset(
    {
        "_ALIASES",
        "_ALIAS_GROUP",
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
_usc_section_key = _impl._usc_section_order


class _FacadeModule(_ModuleType):
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
        if name in _ALIAS_GROUP:
            for alias_name in _ALIAS_GROUP:
                super().__setattr__(alias_name, value)
            _impl._usc_section_order = value
            return
        super().__setattr__(name, value)
        if name in _DELEGATED_ATTRS or hasattr(_impl, name):
            setattr(_impl, name, value)

    def __delattr__(self, name: str) -> None:
        if name in _LOCAL_ATTRS or (name.startswith("__") and name.endswith("__")):
            super().__delattr__(name)
            return
        if name in _ALIAS_GROUP:
            if name not in self.__dict__:
                raise AttributeError(name)
            for alias_name in _ALIAS_GROUP:
                if alias_name in self.__dict__:
                    super().__delattr__(alias_name)
            if hasattr(_impl, "_usc_section_order"):
                delattr(_impl, "_usc_section_order")
            return
        super().__delattr__(name)
        if hasattr(_impl, name):
            delattr(_impl, name)

    def __dir__(self) -> list[str]:
        return sorted((set(super().__dir__()) - _FACADE_INTERNALS) | set(dir(_impl)) | set(_ALIASES))


_sys.modules[__name__].__class__ = _FacadeModule
