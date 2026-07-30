"""Zyte transport adapter for exact Congress.gov CRS page captures."""

from __future__ import annotations

from dataclasses import dataclass

from refspec.registry.crs_legislative_resources import (
    CRSAcquisitionError,
    CRSPageFetcher,
    FetchedCRSPage,
)
from refspec.registry.zyte_transport import (
    ZYTE_API_URL,
    ZyteHttpFetcher,
    ZyteTransportError,
    require_zyte_token_from_environment,
)

DEFAULT_CRS_MAX_BYTES = 5 * 1024 * 1024


class CRSZyteError(CRSAcquisitionError):
    """Zyte could not return an exact, bounded Congress.gov page."""


@dataclass(frozen=True, slots=True)
class ZyteCRSPageFetcher(CRSPageFetcher):
    """Zyte-backed implementation of the CRS provider boundary."""

    token: str
    api_url: str = ZYTE_API_URL
    max_bytes: int = DEFAULT_CRS_MAX_BYTES

    def __post_init__(self) -> None:
        if self.max_bytes <= 0:
            raise CRSZyteError("max_bytes must be positive")
        try:
            ZyteHttpFetcher(token=self.token, api_url=self.api_url)
        except ZyteTransportError as error:
            raise CRSZyteError(str(error)) from error

    @classmethod
    def from_environment(
        cls,
        *,
        max_bytes: int = DEFAULT_CRS_MAX_BYTES,
    ) -> ZyteCRSPageFetcher:
        try:
            return cls(
                token=require_zyte_token_from_environment(),
                max_bytes=max_bytes,
            )
        except ZyteTransportError as error:
            message = str(error).replace(
                "required for live acquisition",
                "required for live CRS acquisition",
            )
            raise CRSZyteError(message) from error

    def fetch(
        self,
        source_url: str,
        *,
        timeout_seconds: float,
    ) -> FetchedCRSPage:
        try:
            response = ZyteHttpFetcher(
                token=self.token,
                api_url=self.api_url,
            ).fetch(
                source_url,
                timeout_seconds=timeout_seconds,
                max_bytes=self.max_bytes,
            )
        except ZyteTransportError as error:
            raise CRSZyteError(str(error)) from error
        if response.content_type is None:
            raise CRSZyteError("Zyte target response omitted Content-Type")
        return FetchedCRSPage(
            body=response.body,
            status_code=response.status_code,
            content_type=response.content_type,
            resolved_url=response.resolved_url,
        )


__all__ = [
    "DEFAULT_CRS_MAX_BYTES",
    "CRSZyteError",
    "ZyteCRSPageFetcher",
]
