"""Executable trust registry for relation machine-proof adapters.

Relation bundles accept proof facts only from adapter classes that RefSpec
code registers explicitly. Data files can name an adapter, but they cannot
grant one authority. Registration applies to the exact class: a subclass does
not inherit its parent's trust.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, TypeVar, runtime_checkable

from refspec.registry.infrastructure.identifier_validation import absolute_uri_issue


class RelationMachineProofTrustError(ValueError):
    """A proof adapter is unregistered or ambiguously registered."""


@runtime_checkable
class RelationMachineProofSource(Protocol):
    """Adapter that reopens exact proof bytes and returns a shared proof pin."""

    @property
    def path(self) -> Path:
        """Return the exact regular file reopened by :meth:`pin`."""

        ...

    def pin(self) -> Mapping[str, Any]:
        """Verify the source again and return one content-derived proof pin."""

        ...


_ProofAdapter = TypeVar("_ProofAdapter", bound=type[RelationMachineProofSource])
_ADAPTERS_BY_ID: dict[str, type[RelationMachineProofSource]] = {}
_ADAPTER_IDS_BY_CLASS: dict[type[RelationMachineProofSource], str] = {}


def _require_adapter_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise RelationMachineProofTrustError(
            "relation machine-proof adapter id must be non-empty trimmed text"
        )
    issue = absolute_uri_issue(value)
    if issue == "missing-scheme":
        raise RelationMachineProofTrustError(
            "relation machine-proof adapter id must be an absolute IRI"
        )
    if issue == "credentials":
        raise RelationMachineProofTrustError(
            "relation machine-proof adapter id must not contain credentials"
        )
    return value


def register_trusted_relation_machine_proof_adapter(
    adapter_id: str,
) -> Callable[[_ProofAdapter], _ProofAdapter]:
    """Register one exact executable adapter class as a proof authority.

    Calling this function expands process trust and therefore belongs in
    reviewed executable code, not configuration or captured input data.
    """

    identifier = _require_adapter_id(adapter_id)

    def register(adapter_class: _ProofAdapter) -> _ProofAdapter:
        if not isinstance(adapter_class, type) or not callable(
            getattr(adapter_class, "pin", None)
        ):
            raise RelationMachineProofTrustError(
                "relation machine-proof adapter must be a class with pin()"
            )
        existing_class = _ADAPTERS_BY_ID.get(identifier)
        if existing_class is not None:
            raise RelationMachineProofTrustError(
                f"relation machine-proof adapter id is already registered: {identifier}"
            )
        existing_id = _ADAPTER_IDS_BY_CLASS.get(adapter_class)
        if existing_id is not None:
            raise RelationMachineProofTrustError(
                f"relation machine-proof adapter class is already registered as {existing_id}"
            )
        _ADAPTERS_BY_ID[identifier] = adapter_class
        _ADAPTER_IDS_BY_CLASS[adapter_class] = identifier
        return adapter_class

    return register


def trusted_relation_machine_proof_adapter_id(source: RelationMachineProofSource) -> str:
    """Return the adapter id trusted for ``source``'s exact class."""

    identifier = _ADAPTER_IDS_BY_CLASS.get(type(source))
    if identifier is None:
        raise RelationMachineProofTrustError(
            "relation machine-proof source exact class is not registered as a trusted executable adapter"
        )
    return identifier


def registered_relation_machine_proof_adapters() -> Mapping[str, type[RelationMachineProofSource]]:
    """Return a read-only snapshot of the process's trusted adapters."""

    return MappingProxyType(dict(_ADAPTERS_BY_ID))


__all__ = [
    "RelationMachineProofSource",
    "RelationMachineProofTrustError",
    "register_trusted_relation_machine_proof_adapter",
    "registered_relation_machine_proof_adapters",
    "trusted_relation_machine_proof_adapter_id",
]
