"""Canonical Atlas 3.1 effective-period validation and historical ``as_of`` evaluation.

Atlas 3.1 separates assertion lifecycle status (``current``, ``superseded``,
``rescinded``, derived solely from ``rkaf:supersedesAssertion`` and
``rkaf:LifecycleEvent``) from temporal applicability (``rkaf:hasEffectivePeriod``
carrying ``rkaf:effectivePeriodStart`` and optional ``rkaf:effectivePeriodEnd``).

Pinned Atlas 3.1 conventions (``bindings/atlas/3.1/shapes/atlas.shacl.ttl``
``atlas:EffectivePeriodShape``):

* **Stored bounds (wire & Parquet):**
  - ``effectivePeriodStart``: canonical UTC day start
    ``<YYYY-MM-DD>T00:00:00+00:00`` (required whenever an assertion carries a
    period).
  - ``effectivePeriodEnd``: canonical UTC day end
    ``<YYYY-MM-DD>T23:59:59+00:00`` (optional; omission means open-ended,
    never invented). Must be ``>= effectivePeriodStart`` and MUST NOT appear
    without ``effectivePeriodStart``.
* **Inclusive interval semantics:**
  Evaluation is closed inclusive ``[start, end]`` in UTC.
  ``effectivePeriodStart <= as_of_utc`` and
  ``(effectivePeriodEnd is None or as_of_utc <= effectivePeriodEnd)``.
* **Date & timezone precision for ``as_of``:**
  - Canonical ISO-8601 calendar day ``YYYY-MM-DD`` or ``datetime.date`` is
    interpreted as UTC midnight ``<YYYY-MM-DD>T00:00:00+00:00``, which falls
    inside ``[start_day T00:00:00+00:00, end_day T23:59:59+00:00]`` if and only
    if ``start_day <= as_of_day <= end_day``.
  - Timezone-aware ``datetime.datetime`` or canonical ISO-8601 date-time string
    with explicit ``Z`` or numeric ``±HH:MM`` offset is normalized to UTC and
    compared at exact instant precision.
  - Naive datetimes, timezone-less timestamps, and non-canonical/malformed
    strings are refused with :class:`EffectivePeriodError`.
* **Distinct open vs. undated dispositions:**
  - ``effective``: bounded period containing ``as_of`` (eligible).
  - ``effective_open_ended``: dated start ``<= as_of`` with omitted end (eligible).
  - ``undated``: neither bound present, i.e. timeless/date-unknown assertion
    such as subject/entity/native relations or legacy views without period
    columns (eligible for any ``as_of`` without fabricating bounds).
  - ``future_effective``: ``as_of < start`` (excluded).
  - ``expired``: ``end is not None`` and ``as_of > end`` (excluded).

This module intentionally imports ONLY the Python standard library so
``AtlasVocabularyPack``'s stdlib-only serving hot path can reuse the exact same
rules without pulling in PyArrow, DuckDB, or RDFLib.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

_PERIOD_START_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T00:00:00\+00:00$", re.ASCII)
_PERIOD_END_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T23:59:59\+00:00$", re.ASCII)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$", re.ASCII)
_ISO_AWARE_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$",
    re.ASCII,
)


class EffectivePeriodError(ValueError):
    """An effective period bound or ``as_of`` query instant is malformed or inconsistent."""


class EffectiveAsOfDisposition(StrEnum):
    """Explicit temporal applicability disposition evaluated separately from lifecycle status."""

    EFFECTIVE = "effective"
    EFFECTIVE_OPEN_ENDED = "effective_open_ended"
    UNDATED = "undated"
    FUTURE_EFFECTIVE = "future_effective"
    EXPIRED = "expired"


_ELIGIBLE_DISPOSITIONS = frozenset(
    {
        EffectiveAsOfDisposition.EFFECTIVE,
        EffectiveAsOfDisposition.EFFECTIVE_OPEN_ENDED,
        EffectiveAsOfDisposition.UNDATED,
    }
)


def _parse_iso_aware_datetime(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value or value != value.strip():
        raise EffectivePeriodError(f"{label} must be a canonical ISO-8601 timezone-aware date-time string")
    if _ISO_AWARE_DATETIME_RE.fullmatch(value) is None:
        raise EffectivePeriodError(
            f"{label} must be a canonical ISO-8601 date-time with explicit timezone (Z or +/-HH:MM): {value!r}"
        )
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise EffectivePeriodError(f"{label} is not a valid calendar date-time: {value!r}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EffectivePeriodError(f"{label} must include an explicit timezone: {value!r}")
    try:
        return parsed.astimezone(UTC)
    except OverflowError as error:
        raise EffectivePeriodError(f"{label} overflows UTC calendar range: {value!r}") from error


def validate_effective_period_bounds(
    effective_period_start: Any,
    effective_period_end: Any,
    *,
    path: str = "$",
) -> tuple[str | None, str | None]:
    """Validate Atlas 3.1 ``rkaf:EffectivePeriod`` start/end bounds without inventing absent dates."""

    if effective_period_start is None:
        if effective_period_end is not None:
            raise EffectivePeriodError(f"{path}: effectivePeriodEnd requires effectivePeriodStart")
        return None, None

    if not isinstance(effective_period_start, str) or _PERIOD_START_RE.fullmatch(effective_period_start) is None:
        raise EffectivePeriodError(
            f"{path}.effectivePeriodStart: expected canonical UTC day start YYYY-MM-DDT00:00:00+00:00"
        )
    start_dt = _parse_iso_aware_datetime(effective_period_start, label=f"{path}.effectivePeriodStart")

    if effective_period_end is None:
        return effective_period_start, None

    if not isinstance(effective_period_end, str) or _PERIOD_END_RE.fullmatch(effective_period_end) is None:
        raise EffectivePeriodError(
            f"{path}.effectivePeriodEnd: expected canonical UTC day end YYYY-MM-DDT23:59:59+00:00"
        )
    end_dt = _parse_iso_aware_datetime(effective_period_end, label=f"{path}.effectivePeriodEnd")
    if end_dt < start_dt:
        raise EffectivePeriodError(
            f"{path}.effectivePeriodEnd: precedes effectivePeriodStart "
            f"({effective_period_end} < {effective_period_start})"
        )
    return effective_period_start, effective_period_end


def parse_as_of(as_of: date | datetime | str) -> datetime:
    """Parse an ``as_of`` date or timezone-aware datetime into a UTC ``datetime`` instant.

    Calendar dates (``datetime.date`` or canonical ``YYYY-MM-DD`` strings) are
    interpreted as UTC midnight ``<YYYY-MM-DD>T00:00:00+00:00``. Naive
    ``datetime`` values, timezone-less strings, and non-canonical dates are
    refused with :class:`EffectivePeriodError`.
    """

    if isinstance(as_of, datetime):
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise EffectivePeriodError("as_of datetime must include an explicit timezone")
        try:
            return as_of.astimezone(UTC)
        except OverflowError as error:
            raise EffectivePeriodError("as_of overflows UTC calendar range") from error
    if isinstance(as_of, date):
        return datetime(as_of.year, as_of.month, as_of.day, 0, 0, 0, tzinfo=UTC)
    if isinstance(as_of, str):
        if not as_of or as_of != as_of.strip():
            raise EffectivePeriodError(
                "as_of must be a canonical YYYY-MM-DD date or timezone-aware ISO-8601 date-time"
            )
        if _ISO_DATE_RE.fullmatch(as_of) is not None:
            try:
                parsed_date = date.fromisoformat(as_of)
            except ValueError as error:
                raise EffectivePeriodError(f"as_of is not a valid calendar date: {as_of!r}") from error
            return datetime(parsed_date.year, parsed_date.month, parsed_date.day, 0, 0, 0, tzinfo=UTC)
        return _parse_iso_aware_datetime(as_of, label="as_of")
    raise EffectivePeriodError(
        f"as_of must be a date, timezone-aware datetime, or ISO-8601 string, got {type(as_of).__name__}"
    )


def format_utc_instant(value: datetime) -> str:
    """Render a timezone-aware ``datetime`` in canonical UTC ``+00:00`` ISO-8601 form.

    Because the year is four zero-padded digits and every instant is normalized
    to ``+00:00`` (with ASCII ``'.'`` > ``'+'`` for fractional seconds), string
    comparison against canonical UTC ``+00:00`` bounds matches instant ordering
    in both DuckDB and SQLite.
    """

    if value.tzinfo is None or value.utcoffset() is None:
        raise EffectivePeriodError("instant must include an explicit timezone")
    try:
        utc = value.astimezone(UTC)
    except OverflowError as error:
        raise EffectivePeriodError("instant overflows UTC calendar range") from error
    base = f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}T{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}"
    if utc.microsecond:
        return f"{base}.{utc.microsecond:06d}+00:00"
    return f"{base}+00:00"


def normalize_as_of_utc(as_of: date | datetime | str) -> str:
    """Parse and render ``as_of`` as a canonical UTC ``+00:00`` ISO-8601 instant string."""

    return format_utc_instant(parse_as_of(as_of))


def _parse_stored_bounds(
    effective_period_start: str | None,
    effective_period_end: str | None,
) -> tuple[datetime | None, datetime | None]:
    if effective_period_start is None:
        if effective_period_end is not None:
            raise EffectivePeriodError("effectivePeriodEnd requires effectivePeriodStart")
        return None, None
    start_dt = _parse_iso_aware_datetime(effective_period_start, label="effectivePeriodStart")
    if effective_period_end is None:
        return start_dt, None
    end_dt = _parse_iso_aware_datetime(effective_period_end, label="effectivePeriodEnd")
    if end_dt < start_dt:
        raise EffectivePeriodError(
            f"effectivePeriodEnd precedes effectivePeriodStart ({effective_period_end} < {effective_period_start})"
        )
    return start_dt, end_dt


def effective_as_of_disposition(
    effective_period_start: str | None,
    effective_period_end: str | None,
    as_of: date | datetime | str,
) -> EffectiveAsOfDisposition:
    """Classify an assertion's temporal applicability at ``as_of`` under closed inclusive ``[start, end]``."""

    as_of_dt = parse_as_of(as_of)
    start_dt, end_dt = _parse_stored_bounds(effective_period_start, effective_period_end)
    if start_dt is None:
        return EffectiveAsOfDisposition.UNDATED
    if as_of_dt < start_dt:
        return EffectiveAsOfDisposition.FUTURE_EFFECTIVE
    if end_dt is None:
        return EffectiveAsOfDisposition.EFFECTIVE_OPEN_ENDED
    if as_of_dt > end_dt:
        return EffectiveAsOfDisposition.EXPIRED
    return EffectiveAsOfDisposition.EFFECTIVE


def is_effective_as_of(
    effective_period_start: str | None,
    effective_period_end: str | None,
    as_of: date | datetime | str | None,
) -> bool:
    """Return whether an assertion with bounds ``[start, end]`` is effective at ``as_of``.

    * ``as_of is None`` disables temporal filtering and returns ``True`` (while
      still refusing inconsistent bounds such as an end without a start).
    * Undated assertions (both bounds ``None``) remain effective for any
      ``as_of`` (disposition ``undated``).
    * Bounded and open-ended dated assertions are evaluated inclusively:
      ``start <= as_of`` and ``(end is None or as_of <= end)``.
    """

    if as_of is None:
        _parse_stored_bounds(effective_period_start, effective_period_end)
        return True
    return effective_as_of_disposition(effective_period_start, effective_period_end, as_of) in _ELIGIBLE_DISPOSITIONS


__all__ = [
    "EffectiveAsOfDisposition",
    "EffectivePeriodError",
    "effective_as_of_disposition",
    "format_utc_instant",
    "is_effective_as_of",
    "normalize_as_of_utc",
    "parse_as_of",
    "validate_effective_period_bounds",
]
