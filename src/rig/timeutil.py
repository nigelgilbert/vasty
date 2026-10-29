"""Durations, RFC 3339 times and rig's notion of `now` (spec §3, §4.2)."""

from __future__ import annotations

from typing import Callable


def parse_duration(text: str) -> int:
    """Parse `30m`, `1h30m` or `2d` into seconds. Raise `invalid_arguments` otherwise."""
    raise NotImplementedError


def format_duration(seconds: int) -> str:
    """Format seconds as `1h12m`, `12m` or `45s` for human output."""
    raise NotImplementedError


def parse_time(text: str) -> int:
    """Parse an RFC 3339 timestamp with an offset into UTC epoch seconds."""
    raise NotImplementedError


def iso(epoch: int | None) -> str | None:
    """Format epoch seconds as `2026-10-29T01:04:00Z`."""
    raise NotImplementedError


def parse_http_date(value: str | None) -> float | None:
    """Parse an HTTP `Date` header into epoch seconds, or None when missing or unparsable."""
    raise NotImplementedError


class Clock:
    """`now` from the provider's latest `Date` header plus local monotonic time.

    Falls back to the wall clock and sets `verified` to False when no header is known.
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
        raise NotImplementedError

    @property
    def verified(self) -> bool:
        raise NotImplementedError
