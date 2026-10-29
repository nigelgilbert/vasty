"""`rig run` (spec §4.6).

Without `--on`, `run` reserves a box with `run_ttl` (or `--ttl`), runs the
command and releases the box when the command exits. `--detach` and `--name`
leave the box alive. Any exception before the job is saved to the cache
releases a box this call created. `--on LEASE` reuses a box and leaves it alive.

Every job starts under tmux in `/workspace` and is recorded in the cache. An
attached run streams the log to stdout in human mode and to stderr in JSON
mode, then exits with the remote exit code. A lost attach refreshes the
account: a lease now in history returns `lease_expired`, anything else
`box_unreachable`, both with exit 2. SIGINT forwards `INT` to the job, waits
up to 10s for it to exit, and exits 130.
"""

from __future__ import annotations

import argparse
import os
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from rig import engine
from rig.cli import Outcome
from rig.commands._common import (
    DEFAULT_EXCLUDES,
    finish_job,
    lease_warnings,
    merge_warnings,
    next_job_id,
    pick_lease,
    put_job,
    require_tools,
    save_lease,
)
from rig.context import Context
from rig.errors import RigError, invalid
from rig.models import (
    HISTORY_STATES,
    CachedLease,
    Job,
    RunAttachedResult,
    RunDetachedResult,
    WarningItem,
)
from rig.onstart import WORKDIR
from rig.remote import SshTarget
from rig.state import effective_expiry, fix_for
from rig.timeutil import format_duration, iso

if TYPE_CHECKING:
    from rig.engine import Snapshot

INTERRUPT_WAIT_S = 10.0
INTERRUPT_POLL_S = 0.5
INTERRUPT_EXIT = 130
LOST_EXIT = 2


def auto_ttl(ctx: Context) -> int:
    """Return `--ttl` when given, else the profile's `run_ttl`."""
    settings = ctx.settings
    return settings.ttl if settings.sources.get("ttl") == "flag" else settings.run_ttl


def release_quietly(ctx: Context, lease: CachedLease) -> bool:
    """Refresh, then release the lease. Return True when this call destroyed it.

    A failure prints one stderr line naming the lease and the fix.
    """
    from rig.commands.release import release_lease

    try:
        snap = engine.refresh(ctx, probe=False)
        fresh = snap.leases.get(lease.lease, lease)
        summary = release_lease(ctx, snap, fresh)
    except RigError as err:
        ctx.warn(f"rig: could not release {lease.lease}: {err.message} Run rig release {lease.lease}.")
        return False
    return not summary.already_absent


def push_dir(ctx: Context, target: SshTarget, directory: str) -> None:
    """Push the contents of `directory` into `/workspace/`. Raise `sync_failed` on a non-zero rsync exit."""
    src = os.path.join(directory, "")
    code = ctx.box.rsync(target, True, src, WORKDIR + "/", False, list(DEFAULT_EXCLUDES))
    if code != 0:
        raise RigError(
            "sync_failed",
            f"rsync of {directory} to {WORKDIR}/ exited {code}.",
            "Check the rsync output on stderr, then retry.",
            details={"exit": code},
        )


def warn_if_expiring(ctx: Context, lease: CachedLease, now: int) -> None:
    """Print a stderr warning and the `extend` command when the clock is under `warn_before_expiry`."""
    remaining = effective_expiry(lease.label) - now
    if remaining < ctx.settings.warn_before_expiry:
        fix = fix_for("expiring_soon", lease.lease)
        ctx.warn(f"rig: lease {lease.lease} expires in {format_duration(remaining)}. Extend it: {fix}")


def _check_sync_dir(ctx: Context, directory: str) -> Path:
    """Expand `~`, resolve against `ctx.cwd` and return the directory, else raise `invalid_arguments`."""
    path = Path(directory).expanduser()
    if not path.is_absolute():
        path = ctx.cwd / path
    if not path.is_dir():
        raise invalid(f"--sync {directory} is not a directory.", "Pass a local directory to --sync.")
    return path


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    command = shlex.join(args.command)
    detach = bool(args.detach)
    auto = args.on is None
    require_tools(ctx, "ssh", *(["rsync"] if args.sync_dir is not None else []))
    sync_dir = _check_sync_dir(ctx, args.sync_dir) if args.sync_dir is not None else None
    ttl = auto_ttl(ctx) if auto else 0

    snap = engine.refresh(ctx)
    warnings: list[WarningItem] = []
    created = False
    if auto:
        from rig.commands import reserve

        reserved = reserve.reserve_lease(ctx, args, snap, ttl=ttl, wait=True)
        lease = reserved.lease
        warnings = list(reserved.result.warnings)
        created = not reserved.result.reused
    else:
        lease = pick_lease(ctx, snap, args.on)
    release_on_exit = auto and args.name is None and not detach and created

    try:
        target = engine.ssh_target(lease)
        if sync_dir is not None:
            push_dir(ctx, target, str(sync_dir))
        now = ctx.clock.now()
        warn_if_expiring(ctx, lease, now)
        job = Job(id=next_job_id(lease), cmd=command, started_at=None, exit=None, state="running")
        started = ctx.box.start_job(target, job, command)
        save_lease(ctx, lease, lambda record: put_job(record, started))
    except BaseException:
        if created:
            release_quietly(ctx, lease)
        raise
    warnings = merge_warnings(warnings, lease_warnings(ctx, snap, lease, now))

    if detach:
        log_path = started.log_path or f"{WORKDIR}/.rig/jobs/{started.id}/log"
        detached = RunDetachedResult(
            lease=lease.lease,
            job=started.id,
            log_path=log_path,
            expires_at=iso(effective_expiry(lease.label)),
            warnings=warnings,
            swept=list(snap.swept),
        )
        human = (
            f"Started {started.id} on {lease.lease}. Log: {log_path}\n"
            f"Follow it with: rig ssh {lease.lease} -- tail -f {log_path}"
        )
        return Outcome(detached, human=human)
    return _attach(ctx, snap, lease, target, started, release_on_exit, warnings)


def _attach(
    ctx: Context,
    snap: Snapshot,
    lease: CachedLease,
    target: SshTarget,
    job: Job,
    release_on_exit: bool,
    warnings: list[WarningItem],
) -> Outcome:
    out: TextIO = ctx.stderr if ctx.mode == "json" else ctx.stdout
    started_at = job.started_at if job.started_at is not None else ctx.clock.now()
    try:
        code = ctx.box.attach_job(target, job.id, out)
    except KeyboardInterrupt:
        return _interrupted(ctx, snap, lease, target, job, release_on_exit, warnings, started_at)
    now = ctx.clock.now()
    duration = max(0, now - started_at)
    if code is None:
        return _lost(ctx, lease, job, duration, warnings, snap)
    save_lease(ctx, lease, lambda record: finish_job(record, job.id, code, now))
    released = release_quietly(ctx, lease) if release_on_exit else False
    result = RunAttachedResult(
        lease=lease.lease, job=job.id, exit=code, duration_s=duration, released=released,
        warnings=warnings, swept=list(snap.swept),
    )
    return Outcome(result, exit_code=code, human=_human(result))


def _lost(
    ctx: Context,
    lease: CachedLease,
    job: Job,
    duration: int,
    warnings: list[WarningItem],
    snap: Snapshot,
) -> Outcome:
    error = "box_unreachable"
    swept = list(snap.swept)
    try:
        fresh = engine.refresh(ctx)
    except RigError:
        fresh = None
    if fresh is not None:
        swept += [entry for entry in fresh.swept if entry not in swept]
        now_lease = fresh.leases.get(lease.lease)
        if now_lease is None or now_lease.state in HISTORY_STATES:
            error = "lease_expired"
    if error == "box_unreachable":
        ctx.warn(f"rig: lost the connection to {lease.lease}; the box stays up. "
                 f"Check it with rig status {lease.lease}.")
    result = RunAttachedResult(
        lease=lease.lease, job=job.id, exit=None, duration_s=duration, released=False,
        warnings=warnings, swept=swept, error=error,
    )
    return Outcome(result, exit_code=LOST_EXIT, human=_human(result))


def _interrupted(
    ctx: Context,
    snap: Snapshot,
    lease: CachedLease,
    target: SshTarget,
    job: Job,
    release_on_exit: bool,
    warnings: list[WarningItem],
    started_at: int,
) -> Outcome:
    exit_code: int | None = None
    try:
        ctx.box.signal_job(target, job.id, "INT")
        deadline = ctx.mono() + INTERRUPT_WAIT_S
        while True:
            status = ctx.box.job_status(target, job.id)
            if status.exit is not None:
                exit_code = status.exit
                break
            if ctx.mono() >= deadline:
                break
            ctx.sleep(INTERRUPT_POLL_S)
    except RigError as err:
        ctx.warn(f"rig: could not stop {job.id} on {lease.lease}: {err.message}")
    now = ctx.clock.now()
    if exit_code is not None:
        code = exit_code
        save_lease(ctx, lease, lambda record: finish_job(record, job.id, code, now))
    released = release_quietly(ctx, lease) if release_on_exit else False
    result = RunAttachedResult(
        lease=lease.lease, job=job.id, exit=exit_code, duration_s=max(0, now - started_at),
        released=released, warnings=warnings, swept=list(snap.swept),
    )
    return Outcome(result, exit_code=INTERRUPT_EXIT, human=_human(result))


def _human(result: RunAttachedResult) -> str:
    took = format_duration(result.duration_s or 0)
    if result.error is not None:
        head = f"{result.job} on {result.lease}: {result.error} after {took}"
    elif result.exit is None:
        head = f"{result.job} on {result.lease} interrupted after {took}"
    else:
        head = f"{result.job} on {result.lease} exited {result.exit} after {took}"
    tail = f"; released {result.lease}" if result.released else f"; {result.lease} stays up"
    return head + tail
