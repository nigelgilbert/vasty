"""`vasty sweep`.

`vasty sweep` runs the network-only refresh once: list, sweep, reconcile, no
probe. It is the verb for a scheduler. `vasty sweep --follow LEASE` waits
on one lease: it sleeps to the lease's expiry, runs the refresh, and repeats
until the row leaves the listing. A lease with `destroy_pending` gets one
more pass `FOLLOW_RETRY_S` later, so a failed destroy, a probe that moves
`expires` and a later `extend` are each picked up on the next pass.

`reserve`, `tag` on adopt and `extend` start `sweep --follow` detached on the
laptop through `spawn_follow`. The lease's `follower_pid` in `leases.json`
records the pid, and `spawn_follow` starts a new follower only when that pid
no longer runs `vasty sweep --follow LEASE`. The follower inherits the
parent's environment and working directory, so it reads the same config
files and API key. A spawn that fails returns a `sweep_not_spawned` warning
and the command succeeds. `release` calls `stop_follower`, which sends TERM
to the recorded pid when its command line still names the lease.

The follower sleeps in bounded chunks against the wall clock, so a laptop
that slept through the expiry refreshes on wake. After each chunk it reads
`leases.json` without a network call and recomputes its wait from the
cached expiry, so an `extend` that moves the clock either way holds within
one chunk. It refreshes early when the lease has left the cache, moved to
history or has a destroy pending, so a `release` whose TERM missed the
follower ends it within one chunk. A refresh that raises waits
`FOLLOW_RETRY_S` and tries again, up to `FOLLOW_RETRIES` times in a row, so
a short outage at expiry sweeps once it is over. The retry after that
raises the last error, so a revoked key or a broken config ends the
follower. The watchdog on the box and the next `vasty` command sweep the
lease either way.
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from vasty import engine
from vasty.cli import Outcome
from vasty.commands._common import merge_swept
from vasty.context import Context
from vasty.errors import VastyError, invalid
from vasty.models import (
    HISTORY_STATES,
    CachedLease,
    Instance,
    SweepResult,
    SweptEntry,
    WarningItem,
)
from vasty.state import effective_expiry, make_warning
from vasty.targeting import resolve_lease

FOLLOW_RETRY_S = 60
"""Wait between passes while a destroy is pending, and after a failed refresh."""
FOLLOW_RETRIES = 5
"""Retries after a failed refresh before the follower raises the error."""
SLEEP_CHUNK_S = 300
"""Longest single sleep, so a wall-clock jump is noticed."""


def spawn_follow(ctx: Context, lease_id: str) -> WarningItem | None:
    """Start `vasty sweep --follow LEASE` detached unless the lease's recorded follower runs.

    Record the new pid as the lease's `follower_pid` in `leases.json`. Return
    a `sweep_not_spawned` warning when the spawn fails.
    """
    argv = [sys.executable, "-m", "vasty", "sweep", "--follow", lease_id]
    with ctx.cache.lock():
        data = ctx.cache.load()
        lease = data.leases.get(lease_id)
        if lease is not None and _follower_runs(ctx, lease):
            return None
        try:
            pid = ctx.spawn(argv, ctx.env)
        except OSError as exc:
            return make_warning(
                "sweep_not_spawned", lease_id, f"could not start the follower: {exc}"
            )
        if lease is not None:
            lease.follower_pid = pid
            ctx.cache.save(data)
    return None


def stop_follower(ctx: Context, lease_id: str) -> None:
    """Send TERM to the lease's recorded follower when that pid still runs `vasty sweep --follow LEASE`."""
    with ctx.cache.lock():
        lease = ctx.cache.load().leases.get(lease_id)
    if lease is None or lease.follower_pid is None or not _follower_runs(ctx, lease):
        return
    try:
        ctx.kill(lease.follower_pid, signal.SIGTERM)
    except OSError:
        pass


def _follower_runs(ctx: Context, lease: CachedLease) -> bool:
    """Return True when `lease.follower_pid` runs `vasty sweep --follow` for the lease."""
    if lease.follower_pid is None:
        return False
    args = ctx.process_args(lease.follower_pid)
    if args is None:
        return False
    words = args.split()
    return (
        len(words) >= 4
        and Path(words[-4]).name == "vasty"
        and words[-3:] == ["sweep", "--follow", lease.lease]
    )


def _sleep(ctx: Context, seconds: int) -> None:
    deadline = ctx.wall() + seconds
    while True:
        left = deadline - ctx.wall()
        if left <= 0:
            return
        ctx.sleep(min(left, SLEEP_CHUNK_S))


def _wait(ctx: Context, lease_id: str, seconds: int, now: int) -> None:
    """Sleep `seconds` from `now` in chunks, re-reading the lease from the cache after each.

    Return early when the cache shows the lease gone, in history or with a
    destroy pending. Otherwise reset the deadline to one second past the
    cached expiry, read through the offset between `now` and the wall clock.
    """
    offset = now - ctx.wall()
    deadline = ctx.wall() + seconds
    while True:
        left = deadline - ctx.wall()
        if left <= 0:
            return
        ctx.sleep(min(left, SLEEP_CHUNK_S))
        with ctx.cache.lock():
            lease = ctx.cache.load().leases.get(lease_id)
        if lease is None or lease.state in HISTORY_STATES or lease.destroy_pending:
            return
        deadline = effective_expiry(lease.label) + 1 - offset


def _refresh(ctx: Context) -> engine.Snapshot:
    """Run the refresh, retrying `FOLLOW_RETRIES` times `FOLLOW_RETRY_S` apart. Raise the last error."""
    failures = 0
    while True:
        try:
            return engine.refresh(ctx, probe=False, by="follower")
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
        _wait(ctx, lease_id, wait, snap.now)
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
