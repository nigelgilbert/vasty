"""Daily budget projection.

All money is `Decimal`. Prices are dollars per hour and times are UTC epoch
seconds. Output rounds to 2 places through `vasty.output.money`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal

from vasty.errors import VastyError
from vasty.models import HISTORY_STATES, CachedLease, Charges, Instance, WarningItem
from vasty.output import money
from vasty.state import effective_expiry, make_warning

DAY_S = 86_400
HOUR = Decimal(3600)
BILLING_FRESH_S = 60
LOW_FRACTION = Decimal("0.9")
ZERO = Decimal("0")
BUDGET_HINT = "Run vasty status to see today's spend, then release a lease or shorten the TTL."


def day_start(now: int) -> int:
    """Return 00:00 UTC of the day that holds `now`."""
    return now - now % DAY_S


def cost(dph_total: Decimal, seconds: int) -> Decimal:
    """Return `dph_total` times `seconds` in hours."""
    return dph_total * Decimal(seconds) / HOUR


def billing_fresh(fetched_at: int | None, now: int) -> bool:
    """Return True when billing data fetched at `fetched_at` is under 60s old."""
    return fetched_at is not None and 0 <= now - fetched_at < BILLING_FRESH_S


def spent_today(charges: Charges, live: list[Instance], now: int, day_start: int) -> Decimal | None:
    """Return billed charges plus `dph_total` since coverage for live instances, or None when coverage is unknown.

    `charges` holds today's billed amounts for every instance, deleted ones
    included. The estimate for each live instance runs from `covered_through`,
    clipped to `[day_start, now]`, to `now`.
    """
    if charges.covered_through is None:
        return None
    since = min(max(charges.covered_through, day_start), now)
    estimate = sum((cost(inst.dph_total, now - since) for inst in live), ZERO)
    return charges.total + estimate


def require_spent(spent: Decimal | None) -> Decimal:
    """Return `spent`, or raise `spend_unavailable` when it is None."""
    if spent is None:
        raise VastyError("spend_unavailable", "Billing coverage for today cannot be read.", "Run vasty status.")
    return spent


def lease_commitments(
    leases: Iterable[CachedLease], replace: Mapping[str, int] | None = None
) -> list[tuple[Decimal, int]]:
    """Return `(price_per_hr, expiry)` for each managed lease outside history.

    `expiry` is the effective expiry, or the value `replace` maps the lease id to.
    """
    swap = replace or {}
    return [
        (lease.price_per_hr, swap.get(lease.lease, effective_expiry(lease.label)))
        for lease in leases
        if lease.state not in HISTORY_STATES and lease.state != "orphan"
    ]


def projection(
    spent: Decimal, commitments: list[tuple[Decimal, int]], now: int, extra: Decimal
) -> Decimal:
    """Return spent plus each `(dph_total, effective_expiry)` commitment from now, floored at 0, plus `extra`.

    Remaining time counts in full on the day of the check, past midnight too.
    `extra` is the action's own cost: a new lease, an orphan's TTL, or an
    `extend_delta`.
    """
    committed = sum((cost(dph, max(0, expiry - now)) for dph, expiry in commitments), ZERO)
    return spent + committed + extra


def extend_delta(targets: list[tuple[Decimal, int, int]], now: int) -> Decimal:
    """Return the sum over `(dph_total, old_expiry, new_expiry)` of the new commitment minus the old.

    A bulk `extend` passes every target at once, so the check is atomic. The
    result is negative when the targets shorten.
    """
    total = ZERO
    for dph, old, new in targets:
        total += cost(dph, max(0, new - now)) - cost(dph, max(0, old - now))
    return total


def _dollars(value: Decimal) -> str:
    return f"${value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"


def check(
    projected: Decimal,
    without_action: Decimal,
    daily_budget: Decimal,
    hint: str = BUDGET_HINT,
) -> None:
    """Raise `budget_exceeded` with `details` when `projected` passes `daily_budget`.

    An action that holds or lowers the projection always passes. `details`
    holds `projected`, `remaining` (`daily_budget` minus `without_action`) and
    `daily_budget`, each rounded to 2 places.
    """
    if projected <= without_action or projected <= daily_budget:
        return
    over = projected - daily_budget
    raise VastyError(
        "budget_exceeded",
        f"Projected spend {_dollars(projected)} exceeds the daily budget "
        f"{_dollars(daily_budget)} by {_dollars(over)}.",
        hint,
        details={
            "projected": money(projected),
            "remaining": money(daily_budget - without_action),
            "daily_budget": money(daily_budget),
        },
    )


def budget_low(projected: Decimal, daily_budget: Decimal) -> bool:
    """Return True when the projection reaches 90% of `daily_budget`."""
    return projected >= daily_budget * LOW_FRACTION


def budget_low_warning(projected: Decimal, daily_budget: Decimal) -> WarningItem | None:
    """Return the account `budget_low` warning, or None below 90%."""
    if not budget_low(projected, daily_budget):
        return None
    message = f"projected {_dollars(projected)} of {_dollars(daily_budget)}"
    return make_warning("budget_low", None, message)


def spend_unavailable_warning() -> WarningItem:
    """Return the account `spend_unavailable` warning for `status`."""
    return make_warning("spend_unavailable", None, "billing coverage for today cannot be read")


def burn_per_hr(live: Iterable[Instance]) -> Decimal:
    """Return the sum of `dph_total` over live leases and orphans."""
    return sum((inst.dph_total for inst in live), ZERO)
