"""Zyte transport and command-line acquisition for the ICPSR public index."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from refspec.registry.icpsr_subject import (
    DEFAULT_MAX_PAGE_BYTES,
    DEFAULT_MINIMUM_INTERVAL_SECONDS,
    IcpsrFetchedPage,
    IcpsrSubjectError,
    acquire_icpsr_subject_index,
    compare_icpsr_xml_to_official_index,
    join_icpsr_xml_to_official_index,
    open_pinned_icpsr_subject_xml,
    write_icpsr_subject_index_capture,
)
from refspec.registry.zyte_transport import (
    ZYTE_API_URL,
    ZYTE_TOKEN_ENV,
    ZyteHttpFetcher,
    ZyteTransportError,
    require_zyte_token_from_environment,
)


class IcpsrZyteError(IcpsrSubjectError):
    """Zyte could not return a bounded target response."""


@dataclass(frozen=True, slots=True)
class ZyteIcpsrPageFetcher:
    """Small stdlib-only Zyte API adapter implementing IcpsrPageFetcher."""

    token: str
    api_url: str = ZYTE_API_URL

    def __post_init__(self) -> None:
        try:
            ZyteHttpFetcher(token=self.token, api_url=self.api_url)
        except ZyteTransportError as error:
            raise IcpsrZyteError(str(error)) from error

    @classmethod
    def from_environment(cls) -> ZyteIcpsrPageFetcher:
        try:
            return cls(token=require_zyte_token_from_environment())
        except ZyteTransportError as error:
            message = str(error).replace(
                "required for live acquisition",
                "required for live ICPSR acquisition",
            )
            raise IcpsrZyteError(message) from error

    def __call__(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> IcpsrFetchedPage:
        try:
            response = ZyteHttpFetcher(
                token=self.token,
                api_url=self.api_url,
            ).fetch(
                url,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            )
        except ZyteTransportError as error:
            raise IcpsrZyteError(str(error)) from error
        return IcpsrFetchedPage(
            requested_url=url,
            resolved_url=response.resolved_url,
            status_code=response.status_code,
            content_type=response.content_type,
            body=response.body,
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Capture the 27-page official ICPSR Subject Thesaurus index "
            "through Zyte and write a deterministic offline snapshot."
        )
    )
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--xml",
        type=Path,
        help=("Optional pinned ICPSR subject.xml to verify against the captured public identities"),
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--max-page-bytes",
        type=int,
        default=DEFAULT_MAX_PAGE_BYTES,
    )
    parser.add_argument(
        "--minimum-interval-seconds",
        type=float,
        default=DEFAULT_MINIMUM_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--observed-at",
        help=("ISO 8601 capture observation date/time; defaults to the current UTC second"),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        observed_at = args.observed_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
        fetcher = ZyteIcpsrPageFetcher.from_environment()
        index = acquire_icpsr_subject_index(
            fetch_page=fetcher,
            timeout_seconds=args.timeout_seconds,
            max_page_bytes=args.max_page_bytes,
            minimum_interval_seconds=args.minimum_interval_seconds,
            observed_at=observed_at,
        )
        manifest = write_icpsr_subject_index_capture(index, args.output)
        result: dict[str, object] = {
            "captureDigest": index.capture_digest,
            "manifest": str(manifest),
            "officialIdentityCount": len(index.terms),
            "observedAt": index.observed_at,
            "requestCount": 28,
        }
        if args.xml is not None:
            if args.xml.is_symlink() or not args.xml.is_file():
                raise IcpsrZyteError(f"XML source is not a regular file: {args.xml}")
            xml = open_pinned_icpsr_subject_xml(args.xml)
            compatibility = compare_icpsr_xml_to_official_index(
                xml,
                index,
            )
            result["xmlCompatibility"] = {
                "compatible": compatibility.compatible,
                "indexOnlyCount": len(compatibility.index_only_terms),
                "indexOnlyTerms": [
                    {
                        "code": term.code,
                        "conceptIri": term.concept_iri,
                        "identifiers": [identifier.as_dict() for identifier in term.identifiers],
                        "label": term.label,
                        "preferred": term.preferred,
                    }
                    for term in compatibility.index_only_terms
                ],
                "matchedTermCount": compatibility.matched_term_count,
                "roleConflicts": [
                    {
                        "indexPreferred": conflict.index_preferred,
                        "label": conflict.label,
                        "xmlPreferred": conflict.xml_preferred,
                    }
                    for conflict in compatibility.role_conflicts
                ],
                "xmlOnlyCount": len(compatibility.xml_only_labels),
                "xmlOnlyLabels": list(compatibility.xml_only_labels),
            }
            result["xmlSha256"] = compatibility.xml_sha256
            if not compatibility.compatible:
                result["xmlJoinStatus"] = "blockedBySourceVersionDrift"
                print(json.dumps(result, sort_keys=True))
                return 2
            joined = join_icpsr_xml_to_official_index(xml, index)
            result["xmlJoinedCount"] = len(joined.terms)
            result["indexOnlyCount"] = len(joined.index_only_terms)
    except IcpsrSubjectError as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ZYTE_API_URL",
    "ZYTE_TOKEN_ENV",
    "IcpsrZyteError",
    "ZyteIcpsrPageFetcher",
    "main",
]
