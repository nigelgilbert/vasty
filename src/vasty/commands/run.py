"""`vasty run`.

Without `--on`, `run` reserves a box with `run_ttl` (or `--ttl`), runs the
command and releases the box when the command exits. `--detach` and `--name`
leave the box alive. Any exception before the job is saved to the cache
releases a box this call created. `--on LEASE` reuses a box and leaves it alive.

Every job starts under tmux in `/workspace` and is recorded in the cache. An
attached run streams the log to stdout in human mode and to stderr in JSON
mode, then exits with the remote exit code. A lost attach refreshes the
account: a lease now in history returns `lease_expired`, anything else
`box_unreachable`, both with exit 2. Any other error from the attach counts
as a lost attach and leaves the box up with the job running. A reader that
closed the stream, as in `vasty run ... | head`, gets the stream pointed at
`/dev/null` so the exit is clean. `duration_s` runs from the box's `started`
to its `finished` record, the timestamps `status` reads. An exception from the attach prints
the lease, job id, expiry and recovery commands on stderr, leaves the box up
and propagates. SIGINT forwards `INT` to the job, waits
up to 10s for it to exit, and exits 130. After the job exits or SIGINT
arrives, an auto-reserved box is released even when saving the job or the
10s wait raises, and the exception then propagates. `swept` lists the
entries of every refresh this call made: the first one, the reserve wait, and
the lost-attach or release refresh.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shlex
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from vasty import engine
from vasty.cli import Outcome
from vasty.commands._common import (
    DEFAULT_EXCLUDES,
    finish_job,
    lease_warnings,
    merge_swept,
    merge_warnings,
    next_job_id,
    pick_lease,
    put_job,
    require_tools,
    save_lease,
    signal_and_wait,
)
from vasty.context import Context
from vasty.errors import VastyError, invalid
from vasty.models import (
    HISTORY_STATES,
    CachedLease,
    Job,
    RunAttachedResult,
    RunDetachedResult,
    SweptEntry,
    WarningItem,
)
from vasty.onstart import WORKDIR
from vasty.remote import SshTarget
from vasty.state import effective_expiry, fix_for
from vasty.timeutil import format_duration, format_minutes_up, iso

INTERRUPT_WAIT_S = 10.0
INTERRUPT_EXIT = 130
LOST_EXIT = 2


def auto_ttl(ctx: Context) -> int:
    """Return `--ttl` when given, else the profile's `run_ttl`."""
    settings = ctx.settings
    return settings.ttl if settings.sources.get("ttl") == "flag" else settings.run_ttl


def release_quietly(ctx: Context, lease: CachedLease) -> tuple[bool, list[SweptEntry]]:
    """Refresh, then release the lease.

    Return whether this call destroyed the lease and the `swept` entries of
    the refresh. A failure prints one stderr line naming the lease and the fix.
    """
    from vasty.commands.release import release_lease

    swept: list[SweptEntry] = []
    try:
        snap = engine.refresh(ctx, probe=False)
        swept = list(snap.swept)
        fresh = snap.leases.get(lease.lease, lease)
        summary = release_lease(ctx, snap, fresh)
    except VastyError as err:
        ctx.warn(f"vasty: could not release {lease.lease}: {err.message} Run vasty release {lease.lease}.")
        return False, swept
    return not summary.already_absent or any(e.lease == lease.lease and e.ok for e in swept), swept


@contextmanager
def _release_on_error(ctx: Context, lease: CachedLease, flag: bool) -> Iterator[None]:
    """Release the lease quietly when the body raises and `flag` is set, then re-raise."""
    try:
        yield
    except BaseException:
        if flag:
            release_quietly(ctx, lease)
        raise


def _released_swept(
    ctx: Context, lease: CachedLease, release_on_exit: bool, swept: list[SweptEntry]
) -> tuple[bool, list[SweptEntry]]:
    """Release the lease when `release_on_exit` is set and add its refresh's new entries to `swept`."""
    if not release_on_exit:
        return False, swept
    released, more = release_quietly(ctx, lease)
    return released, merge_swept(swept, more)


def push_dir(ctx: Context, target: SshTarget, directory: str) -> None:
    """Push the contents of `directory` into `/workspace/`. Raise `sync_failed` on a non-zero rsync exit."""
    src = os.path.join(directory, "")
    code = ctx.box.rsync(target, True, src, WORKDIR + "/", False, list(DEFAULT_EXCLUDES))
    if code != 0:
        raise VastyError(
            "sync_failed",
            f"rsync of {directory} to {WORKDIR}/ exited {code}.",
            "Check the rsync output on stderr, then retry.",
            details={"exit": code},
        )


def warn_if_expiring(ctx: Context, lease: CachedLease, now: int) -> None:
    """Print a stderr warning and the `extend` command when the clock is under `warn_before_expiry`."""
    remaining = effective_expiry(lease.label) - now
    if remaining < ctx.settings.warn_before_expiry:
        fix = fix_for("expiring_soon", lease.lease, lease.label.ttl)
        ctx.warn(f"vasty: lease {lease.lease} expires in {format_minutes_up(remaining)}. Extend it: {fix}")


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
        from vasty.commands import reserve

        reserved = reserve.reserve_lease(ctx, args, snap, ttl=ttl)
        lease = reserved.lease
        warnings = list(reserved.result.warnings)
        swept = merge_swept(list(snap.swept), reserved.result.swept)
        created = not reserved.result.reused
    else:
        lease = pick_lease(ctx, snap, args.on)
        swept = list(snap.swept)
    release_on_exit = auto and args.name is None and not detach and created

    with _release_on_error(ctx, lease, created):
        target = engine.ssh_target(lease)
        if sync_dir is not None:
            push_dir(ctx, target, str(sync_dir))
        now = ctx.clock.now()
        warn_if_expiring(ctx, lease, now)
        job = Job(id=next_job_id(lease), cmd=command, started_at=None, exit=None, state="running")
        started = ctx.box.start_job(target, job, command)
        save_lease(ctx, lease, lambda record: put_job(record, started))
    warnings = merge_warnings(warnings, lease_warnings(ctx, snap, lease, now))

    if detach:
        log_path = started.log_path or f"{WORKDIR}/.vasty/jobs/{started.id}/log"
        expiry = effective_expiry(lease.label)
        detached = RunDetachedResult(
            lease=lease.lease,
            job=started.id,
            gpu=lease.gpu,
            price_per_hr=lease.price_per_hr,
            log_path=log_path,
            expires_at=iso(expiry),
            ttl_remaining_s=max(0, expiry - ctx.clock.now()),
            warnings=warnings,
            swept=swept,
        )
        human = (
            f"Started {started.id} on {lease.lease}. Log: {log_path}\n"
            f"Follow it with: vasty ssh {lease.lease} -- tail -f {log_path}"
        )
        return Outcome(detached, human=human)
    return _attach(ctx, lease, target, started, release_on_exit, warnings, swept)


def _attach(
    ctx: Context,
    lease: CachedLease,
    target: SshTarget,
    job: Job,
    release_on_exit: bool,
    warnings: list[WarningItem],
    swept: list[SweptEntry],
) -> Outcome:
    out: TextIO = ctx.stderr if ctx.mode == "json" else ctx.stdout
    started_at = job.started_at if job.started_at is not None else ctx.clock.now()
    try:
        code = ctx.box.attach_job(target, job.id, out)
    except KeyboardInterrupt:
        return _interrupted(ctx, lease, target, job, release_on_exit, warnings, swept, started_at)
    except Exception as exc:  # noqa: BLE001
        _warn_attach_lost(ctx, lease, job)
        if isinstance(exc, BrokenPipeError):
            discard_stream(out)
        code = None
    now = ctx.clock.now()
    if code is None:
        return _lost(ctx, lease, job, max(0, now - started_at), warnings, swept)
    with _release_on_error(ctx, lease, release_on_exit):
        finished = _box_finished(ctx, target, job.id) or now
        save_lease(ctx, lease, lambda record: finish_job(record, job.id, code, finished))
    released, swept = _released_swept(ctx, lease, release_on_exit, swept)
    result = RunAttachedResult(
        lease=lease.lease, job=job.id, exit=code, duration_s=max(0, finished - started_at),
        released=released, warnings=warnings, swept=swept,
    )
    return Outcome(result, exit_code=code, human=_human(result))


def _box_finished(ctx: Context, target: SshTarget, job_id: str) -> int | None:
    """Return the `finished_at` the box recorded for the job, or None when the read fails."""
    try:
        return ctx.box.job_status(target, job_id).finished_at
    except VastyError:
        return None


def discard_stream(stream: TextIO) -> None:
    """Point the file descriptor under `stream` at `/dev/null` so later writes and the exit flush succeed."""
    try:
        fd = stream.fileno()
    except (OSError, ValueError):
        return
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, fd)
    finally:
        os.close(devnull)


def _warn_attach_lost(ctx: Context, lease: CachedLease, job: Job) -> None:
    """Print the lease, job id, expiry and recovery commands on stderr."""
    expires = iso(effective_expiry(lease.label))
    _warn_quietly(ctx, f"vasty: lost the attach to {job.id} on {lease.lease}; the box stays up until "
                       f"{expires}. Check it with vasty status {lease.lease}. "
                       f"Release it with vasty release {lease.lease}.")


def _warn_quietly(ctx: Context, message: str) -> None:
    """Write a warning to stderr and ignore a broken stderr."""
    with contextlib.suppress(Exception):
        ctx.warn(message)


def _lost(
    ctx: Context,
    lease: CachedLease,
    job: Job,
    duration: int,
    warnings: list[WarningItem],
    swept: list[SweptEntry],
) -> Outcome:
    error = "box_unreachable"
    try:
        fresh = engine.refresh(ctx)
    except VastyError:
        fresh = None
    if fresh is not None:
        swept = merge_swept(swept, fresh.swept)
        now_lease = fresh.leases.get(lease.lease)
        if now_lease is None or now_lease.state in HISTORY_STATES:
            error = "lease_expired"
    if error == "box_unreachable":
        _warn_quietly(ctx, f"vasty: lost the connection to {lease.lease}; the box stays up. "
                           f"Check it with vasty status {lease.lease}.")
    result = RunAttachedResult(
        lease=lease.lease, job=job.id, exit=None, duration_s=duration, released=False,
        warnings=warnings, swept=swept, error=error,
    )
    return Outcome(result, exit_code=LOST_EXIT, human=_human(result))


def _interrupted(
    ctx: Context,
    lease: CachedLease,
    target: SshTarget,
    job: Job,
    release_on_exit: bool,
    warnings: list[WarningItem],
    swept: list[SweptEntry],
    started_at: int,
) -> Outcome:
    exit_code: int | None = None
    with _release_on_error(ctx, lease, release_on_exit):
        status: Job | None = None
        try:
            status = signal_and_wait(ctx, target, job.id, "INT", INTERRUPT_WAIT_S)
        except VastyError as err:
            ctx.warn(f"vasty: could not stop {job.id} on {lease.lease}: {err.message}")
        end = ctx.clock.now()
        if status is not None and status.exit is not None:
            code = exit_code = status.exit
            end = status.finished_at or end
            save_lease(ctx, lease, lambda record: finish_job(record, job.id, code, end))
    released, swept = _released_swept(ctx, lease, release_on_exit, swept)
    result = RunAttachedResult(
        lease=lease.lease, job=job.id, exit=exit_code, duration_s=max(0, end - started_at),
        released=released, warnings=warnings, swept=swept,
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
