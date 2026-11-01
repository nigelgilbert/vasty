"""Durations, RFC 3339 times and vasty's notion of `now`.

A duration is one or more `<positive integer><unit>` parts with units `d`,
`h`, `m`, `s`. Each unit appears at most once and in that order, so `1h30m`
parses and `30m1h`, `1h1h`, `1h0m` and `0s` return `invalid_arguments`.
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, overload

from vasty.errors import invalid

UNITS: dict[str, int] = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_PART = re.compile(r"([0-9]+)([dhms])")
_RFC3339 = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt ]([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]+)?"
    r"(?:([Zz])|([+-])([0-9]{2}):([0-9]{2}))"
)
_DURATION_HINT = "Use a positive duration such as 30m, 2h or 1h30m."
_TIME_HINT = "Use RFC 3339 with an offset, such as 2026-10-29T01:04:00Z."


def parse_duration(text: str) -> int:
    """Parse `30m`, `1h30m` or `2d` into seconds. Raise `invalid_arguments` otherwise."""
    order = list(UNITS)
    pos = 0
    last = -1
    total = 0
    while pos < len(text):
        match = _PART.match(text, pos)
        if match is None:
            raise invalid(f"Invalid duration {text!r}.", _DURATION_HINT)
        amount, unit = int(match.group(1)), match.group(2)
        rank = order.index(unit)
        if amount <= 0 or rank <= last:
            raise invalid(f"Invalid duration {text!r}.", _DURATION_HINT)
        last = rank
        total += amount * UNITS[unit]
        pos = match.end()
    if total <= 0:
        raise invalid(f"Invalid duration {text!r}.", _DURATION_HINT)
    return total


def format_duration(seconds: int, *, pad: bool = False) -> str:
    """Format seconds as `1h12m`, `12m` or `45s` for human output.

    Values floor to the largest two units. Negative values print as `0s`.
    With `pad`, the second unit has two digits and a zero second unit stays,
    giving job runtimes such as `2h01m` and `2h00m`.
    """
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return _two(days, "d", hours, "h", pad)
    if hours:
        return _two(hours, "h", minutes, "m", pad)
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"


def format_minutes_up(seconds: int) -> str:
    """Format seconds rounded up to the whole minute, so 174 reads `3m` and 3601 reads `1h1m`."""
    return format_duration(-(-int(seconds) // 60) * 60)


def format_duration_exact(seconds: int) -> str:
    """Format seconds with every nonzero unit, as `1h30m`, `2d` or `1d2h3m4s`.

    The output parses back to the same value with `parse_duration`. Values
    at or below zero print as `0s`.
    """
    seconds = int(seconds)
    if seconds <= 0:
        return "0s"
    parts = []
    for unit, size in UNITS.items():
        count, seconds = divmod(seconds, size)
        if count:
            parts.append(f"{count}{unit}")
    return "".join(parts)


def _two(big: int, big_unit: str, small: int, small_unit: str, pad: bool) -> str:
    if pad:
        return f"{big}{big_unit}{small:02d}{small_unit}"
    if small:
        return f"{big}{big_unit}{small}{small_unit}"
    return f"{big}{big_unit}"


def parse_time(text: str) -> int:
    """Parse an RFC 3339 timestamp with an offset into UTC epoch seconds.

    Fractional seconds are dropped. A time without an offset returns `invalid_arguments`.
    """
    match = _RFC3339.fullmatch(text)
    if match is None:
        raise invalid(f"Invalid time {text!r}.", _TIME_HINT)
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    try:
        datetime(year, month, day, hour, minute, second)
    except ValueError:
        raise invalid(f"Invalid time {text!r}.", _TIME_HINT) from None
    offset = 0
    if match.group(9):
        off_h, off_m = int(match.group(10)), int(match.group(11))
        if off_h > 23 or off_m > 59:
            raise invalid(f"Invalid time {text!r}.", _TIME_HINT)
        offset = (off_h * 3600 + off_m * 60) * (1 if match.group(9) == "+" else -1)
    return calendar.timegm((year, month, day, hour, minute, second)) - offset


@overload
def iso(epoch: int) -> str: ...
@overload
def iso(epoch: None) -> None: ...
@overload
def iso(epoch: int | None) -> str | None: ...
def iso(epoch: int | None) -> str | None:
    """Format epoch seconds as `2026-10-29T01:04:00Z`."""
    if epoch is None:
        return None
    return datetime.fromtimestamp(int(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_start(epoch: int) -> int:
    """Return 00:00 UTC of the day that holds `epoch`."""
    return epoch - epoch % UNITS["d"]


def parse_http_date(value: str | None) -> float | None:
    """Parse an HTTP `Date` header into epoch seconds, or None when missing or unparsable.

    Accepts the RFC 7231 forms: IMF-fixdate, RFC 850 and asctime. A date
    without a zone reads as UTC.
    """
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


class Clock:
    """`now` from the provider's latest `Date` header plus local monotonic time.

    Falls back to the wall clock and sets `verified` to False when no header is known.
    `last_date` returns the header as epoch seconds and the monotonic time it arrived.
    """

    def __init__(
        self,
        last_date: Callable[[], tuple[float, float] | None],
        wall: Callable[[], float],
        mono: Callable[[], float],
    ) -> None:
        self._last_date = last_date
        self._wall = wall
        self._mono = mono

    def now(self) -> int:
        """Return `now` as int UTC epoch seconds."""
        known = self._last_date()
        if known is None:
            return int(self._wall())
        date, arrived = known
        return int(date + max(0.0, self._mono() - arrived))

    @property
    def verified(self) -> bool:
        """Return True when `now` comes from a provider `Date` header."""
        return self._last_date() is not None
