"""Storage-neutral data access used by the interactive Atlas explorer."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AtlasExplorerData(Protocol):
    """Read the three kinds of data the graph browser needs."""

    def facets(self) -> dict[str, Any]:
        """Return corpus counts, filters, and a useful starting resource."""

    def search(
        self,
        query: str = "",
        *,
        release: str = "",
        releases: Sequence[str] = (),
        ring: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Find resources using the explorer's visible filters."""

    def resource(self, resource_id: str) -> dict[str, Any]:
        """Return one resource, its immediate relations, and their evidence."""


__all__ = ["AtlasExplorerData"]
