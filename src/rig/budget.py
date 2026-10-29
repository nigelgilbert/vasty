"""Daily budget projection (spec §5.2)."""

from __future__ import annotations

from decimal import Decimal

from rig.models import Charges, Instance


def spent_today(charges: Charges, live: list[Instance], now: int, day_start: int) -> Decimal | None:
    """Return billed charges plus `dph_total` since coverage for live instances, or None when coverage is unknown."""
    raise NotImplementedError


def projection(
    spent: Decimal, commitments: list[tuple[Decimal, int]], now: int, extra: Decimal
) -> Decimal:
    """Return spent plus each `(dph_total, effective_expiry)` commitment from now, floored at 0, plus `extra`."""
    raise NotImplementedError


def check(projected: Decimal, without_action: Decimal, daily_budget: Decimal) -> None:
    """Raise `budget_exceeded` with `details` when `projected` passes `daily_budget`."""
    raise NotImplementedError
