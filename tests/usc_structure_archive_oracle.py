"""Frozen structure-archive routing from RefSpec 63947226.

The existing table-policy callbacks are unchanged; this oracle retains the
replaced ZIP routing, byte checks and ordered member receipt independently.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from spicy_docs.sources.uscode import (
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_ARCHIVE_ENTRIES,
    DEFAULT_MAX_XML_BYTES,
    UsCodeSourceError,
)
from spicy_docs.reading.zip_archive import archive_members, open_archive, read_member

from tools.build_usc_structure import Emit, read_annual_title, read_release_title

_CORPUS_MEMBER = re.compile(r"usc(?P<title>[0-9]+)(?P<appendix>[aA]?)\.xml")
_ANNUAL_MEMBER = re.compile(r"(?P<year>[0-9]{4})usc(?P<title>[0-9]+)(?P<appendix>[aA]?)\.htm", re.IGNORECASE)
_ANNUAL_SIDE = re.compile(
    r"(?:index\.html?|usc\.css|[0-9]{4}usc(?:PopularNames|Table[0-9]+)\.htm|tbl[0-9]+(?:cd|pl)_[a-z0-9]+\.htm)",
    re.IGNORECASE,
)


def _digest(body: bytes) -> str:
    """Return the canonical ``sha256:`` spelling of a payload."""

    return "sha256:" + hashlib.sha256(body).hexdigest()


def _archive(path: Path, *, year: int | None, emit: Emit) -> dict[str, Any]:
    """Read one structure archive into an ordered member receipt and emit selected titles.

    Refuses unclassified members, a member year that differs from the archive
    year, and an archive with no selected titles; the input is read only up to
    the declared compressed bound even if the file grows after stat.
    """

    # Read at most the declared compressed bound even if a file grows after stat.
    with path.open("rb") as stream:
        body = stream.read(DEFAULT_MAX_ARCHIVE_BYTES + 1)
    label = "retained U.S. Code structure archive"
    members = []
    with open_archive(
        body,
        max_bytes=DEFAULT_MAX_ARCHIVE_BYTES,
        max_entries=DEFAULT_MAX_ARCHIVE_ENTRIES,
        max_entry_bytes=DEFAULT_MAX_XML_BYTES,
        error_type=UsCodeSourceError,
        label=label,
    ) as archive:
        for info in archive_members(
            archive, max_entries=DEFAULT_MAX_ARCHIVE_ENTRIES, error_type=UsCodeSourceError, label=label
        ):
            stem = info.filename.rsplit("/", 1)[-1]
            match = (_CORPUS_MEMBER if year is None else _ANNUAL_MEMBER).fullmatch(stem)
            if match is None and (year is None or not _ANNUAL_SIDE.fullmatch(stem)):
                raise ValueError(f"unclassified U.S. Code archive member: {info.filename}")
            data = read_member(
                archive, info, max_bytes=DEFAULT_MAX_XML_BYTES, error_type=UsCodeSourceError, label=label
            )
            members.append(
                {"name": info.filename, "sha256": _digest(data), "bytes": len(data), "selected": match is not None}
            )
            if match is None:
                continue
            appendix = bool(match["appendix"])
            if year is None:
                read_release_title(data, appendix=appendix, emit=emit)
            else:
                if int(match["year"]) != year:
                    raise ValueError(f"annual archive year differs from member name: {info.filename}")
                read_annual_title(data, year=year, title=int(match["title"]), appendix=appendix, emit=emit)
    if not any(member["selected"] for member in members):
        raise ValueError(f"U.S. Code archive has no selected titles: {path}")
    return {"path": str(path.resolve()), "year": year, "sha256": _digest(body), "bytes": len(body), "members": members}
