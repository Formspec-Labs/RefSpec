"""Frozen first-selected-law enactment-year check."""
from __future__ import annotations

import re
from collections.abc import Mapping

from refspec.registry.act_resolution import ActIndex
from refspec.registry.unified_agenda_parquet import _SESSION_LAW_YEAR, _TRAILING_YEAR_DESIGNATOR


def _act_enactment_years(
    index: ActIndex | None, pl_roster: tuple[Mapping, Mapping] | None
) -> dict[str, str]:
    """Year-less listed act name -> the year its own enacting law was approved.

    Both halves are read, never derived: a session-law Table III key states the
    year in the key itself, and a public-law key is dated by the pinned roster.
    An act whose key is neither — or whose law predates the roster's earliest
    congress — contributes nothing, which is why this is a mapping and not a
    computation over every name.
    """

    if index is None:
        return {}
    dates = pl_roster[0] if pl_roster else {}
    years: dict[str, str] = {}
    for name, table3_key in index.table3_key_by_name.items():
        if _TRAILING_YEAR_DESIGNATOR.search(name):
            continue
        session = _SESSION_LAW_YEAR.match(table3_key or "")
        if session is not None:
            years[name] = session.group(1)
            continue
        public_law = re.fullmatch(r"(\d+)-(\d+)", table3_key or "")
        if public_law is None:
            continue
        approved = dates.get((int(public_law.group(1)), int(public_law.group(2))))
        if approved:
            years[name] = approved[-4:]
    return years
