"""`vasty sweep`.

`vasty sweep` runs the network-only refresh once: list, sweep, reconcile, no
probe. It is the verb for a scheduler. `vasty sweep --follow LEASE` waits
on one lease: it sleeps to the lease's expiry, runs the refresh, and repeats
until the row leaves the listing. A lease with `destroy_pending` gets one
more pass `FOLLOW_RETRY_S` later, so a failed destroy, a probe that moves
`expires` and a later `extend` are each picked up on the next pass.

`reserve`, `tag` on adopt and `extend` start `sweep --follow` detached on the
laptop through `spawn_follow`. The follower inherits the parent's
environment and working directory, so it reads the same config files and
API key. A spawn that fails returns a `sweep_not_spawned` warning and the
command succeeds.

The follower sleeps in bounded chunks against the wall clock, so a laptop
that slept through the expiry refreshes on wake. After each chunk it reads
`leases.json` without a network call and refreshes early when the lease has
left the cache, moved to history or has a destroy pending, so a `release`
during the sleep ends the follower within one chunk. A refresh that raises
waits `FOLLOW_RETRY_S` and tries again, up to `FOLLOW_RETRIES` times in a
row, so a short outage at expiry sweeps once it is over. The retry after
that raises the last error, so a revoked key or a broken config ends the
follower. The watchdog on the box and the next `vasty` command sweep the
lease either way.
"""

from __future__ import annotations

import argparse
import sys

from vasty import engine
from vasty.cli import Outcome
from vasty.commands._common import merge_swept
from vasty.context import Context
from vasty.errors import VastyError, invalid
from vasty.models import HISTORY_STATES, Instance, SweepResult, SweptEntry, WarningItem
from vasty.state import effective_expiry, make_warning
from vasty.targeting import resolve_lease

FOLLOW_RETRY_S = 60
"""Wait between passes while a destroy is pending, and after a failed refresh."""
FOLLOW_RETRIES = 5
"""Retries after a failed refresh before the follower raises the error."""
SLEEP_CHUNK_S = 300
"""Longest single sleep, so a wall-clock jump is noticed."""


def spawn_follow(ctx: Context, lease_id: str) -> WarningItem | None:
    """Start `vasty sweep --follow LEASE` detached. Return a `sweep_not_spawned` warning on failure."""
    argv = [sys.executable, "-m", "vasty", "sweep", "--follow", lease_id]
    try:
        ctx.spawn(argv, ctx.env)
    except OSError as exc:
        return make_warning("sweep_not_spawned", lease_id, f"could not start the follower: {exc}")
    return None


def _sleep(ctx: Context, seconds: int) -> None:
    deadline = ctx.wall() + seconds
    while True:
        left = deadline - ctx.wall()
        if left <= 0:
            return
        ctx.sleep(min(left, SLEEP_CHUNK_S))


def _lease_changed(ctx: Context, lease_id: str) -> bool:
    """Return True when the cache shows `lease_id` gone, in history or with a destroy pending."""
    with ctx.cache.lock():
        lease = ctx.cache.load().leases.get(lease_id)
    return lease is None or lease.state in HISTORY_STATES or lease.destroy_pending


def _wait(ctx: Context, lease_id: str, seconds: int) -> None:
    """Sleep `seconds` in chunks, returning early once `_lease_changed` holds."""
    deadline = ctx.wall() + seconds
    while True:
        left = deadline - ctx.wall()
        if left <= 0:
            return
        ctx.sleep(min(left, SLEEP_CHUNK_S))
        if _lease_changed(ctx, lease_id):
            return


def _refresh(ctx: Context) -> engine.Snapshot:
    """Run the refresh, retrying `FOLLOW_RETRIES` times `FOLLOW_RETRY_S` apart. Raise the last error."""
    failures = 0
    while True:
        try:
            return engine.refresh(ctx, probe=False)
        except VastyError:
            failures += 1
            if failures > FOLLOW_RETRIES:
                raise
            _sleep(ctx, FOLLOW_RETRY_S)


def follow(ctx: Context, ref: str) -> SweepResult:
    """Refresh at each expiry of lease `ref` until its row leaves the listing."""
    snap = _refresh(ctx)
    found = resolve_lease(ctx, snap, ref)
    if isinstance(found, Instance):
        raise invalid(f"{ref} is not a vasty lease.", f"vasty tag {ref} --ttl 30m")
    lease_id = found.lease
    swept: list[SweptEntry] = list(snap.swept)
    while True:
        lease = snap.leases.get(lease_id)
        if lease is None or (lease.state in HISTORY_STATES and not lease.destroy_pending):
            return SweepResult(swept=swept, warnings=list(snap.warnings))
        wait = effective_expiry(lease.label) - snap.now + 1
        if lease.destroy_pending or wait <= 0:
            wait = FOLLOW_RETRY_S
        _wait(ctx, lease_id, wait)
        snap = _refresh(ctx)
        swept = merge_swept(swept, snap.swept)


def render(result: SweepResult) -> str:
    from vasty.commands.status import swept_lines, warning_lines

    blocks = [swept_lines(result.swept), warning_lines(result.warnings)]
    text = "\n\n".join("\n".join(block) for block in blocks if block)
    return text or "nothing swept"


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    ref = getattr(args, "follow", None)
    if ref is None:
        snap = engine.refresh(ctx, probe=False)
        result = SweepResult(swept=list(snap.swept), warnings=list(snap.warnings))
    else:
        result = follow(ctx, ref)
    return Outcome(result, human=render(result) if ctx.mode == "human" else None)
