"""`vasty release`.

`release` destroys the box and returns once the provider accepts the destroy
call. The lease is then `released` with `destroy_pending` until a list call
shows it gone; `released_here` lets reconciliation record `released`.
Uptime and jobs come from the local cache. Cost is Vast's billed sum for the
instance, the same figure `status` reports. The engine module docstring
describes the destroy lifecycle.

A LEASE that matches nothing returns `{lease, already_absent: true}`. A lease
already in history returns its summary with `already_absent: true` once Vast
no longer lists its row. While the row is listed, `release` sends the destroy
again and keeps the history state. An orphan or unreadable row released by
instance id needs `--yes` or a TTY confirmation. Before destroying, `release`
re-reads the row and aborts with `provider_error` when its `expires` moved
or its label became unreadable. After a destroy, or when the lease is
already absent, `release` sends TERM to the lease's recorded follower
through `stop_follower`. A destroy left pending falls to the next command's
sweep.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
from typing import Any

from vasty import engine, labels, views
from vasty.cli import Outcome
from vasty.commands._common import save_lease
from vasty.commands.sweep import stop_follower
from vasty.context import Context
from vasty.engine import Snapshot
from vasty.errors import VastyError
from vasty.ids import orphan_id
from vasty.models import (
    HISTORY_STATES,
    BulkEntry,
    BulkResult,
    CachedLease,
    Instance,
    Label,
    ReleaseAbsent,
    ReleaseJob,
    ReleaseSummary,
    SweptEntry,
    WarningItem,
)
from vasty.output import money
from vasty.targeting import resolve_lease, resolve_target
from vasty.timeutil import format_duration


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    snap = engine.refresh(ctx)
    engine.read_charges(ctx, snap)
    if args.target is not None:
        return _release_one(ctx, snap, args.target, bool(args.yes))
    resolved = resolve_target(ctx, snap, args, write=True)
    entries: list[BulkEntry] = []
    worst = 0
    for lease in resolved.leases:
        try:
            summary = release_lease(ctx, snap, lease)
        except VastyError as err:
            worst = max(worst, err.exit_code)
            data = {"name": lease.label.name, "message": err.message}
            entries.append(BulkEntry(lease.lease, False, err.code, data))
            continue
        entries.append(BulkEntry(lease.lease, True, None, _entry_data(summary)))
    result = BulkResult(entries, list(snap.warnings), list(snap.swept))
    return Outcome(result, exit_code=worst, human=_render_bulk(result))


def _release_one(ctx: Context, snap: Snapshot, ref: str, yes: bool) -> Outcome:
    try:
        found = resolve_lease(ctx, snap, ref)
    except VastyError as err:
        if err.code != "lease_not_found":
            raise
        ctx.warn(f"vasty: {err.message} Nothing to release.")
        absent = ReleaseAbsent(ref, True, list(snap.warnings), list(snap.swept))
        return Outcome(absent, human=f"{ref} is already absent.")
    if isinstance(found, Instance):
        summary = _release_orphan(ctx, snap, found, yes)
    else:
        summary = release_lease(ctx, snap, found)
    summary.warnings = list(snap.warnings)
    summary.swept = list(snap.swept)
    return Outcome(summary, human=_render_one(summary, summary.warnings, summary.swept))


def release_lease(ctx: Context, snap: Snapshot, lease: CachedLease) -> ReleaseSummary:
    """Destroy one managed lease and return its summary.

    A lease in history whose row Vast no longer lists, or one whose row
    vanished, returns its summary with `already_absent`. A lease in history
    whose row is still listed gets the destroy again. Raise `provider_error`
    when the destroy call fails, the row's `expires` moved since `lease` was
    read, or the re-read label is unreadable. Stop the lease's follower
    before returning.
    """
    summary = _destroy(ctx, snap, lease)
    stop_follower(ctx, lease.lease)
    return summary


def _destroy(ctx: Context, snap: Snapshot, lease: CachedLease) -> ReleaseSummary:
    in_history = lease.state in HISTORY_STATES or lease.destroy_pending
    if in_history and snap.instance(lease.instance_id) is None:
        return summarize(lease, max(snap.now, ctx.clock.now()), snap, already_absent=True)
    with ctx.cache.lock():
        destroyed = engine.destroy_checked(ctx, lease.instance_id, lease.label.expires)
        if not destroyed:
            row = ctx.provider.get_instance(lease.instance_id)
            if row is not None and not isinstance(labels.parse(row.label), Label):
                raise VastyError(
                    "provider_error",
                    f"Lease {lease.lease}'s label is unreadable.",
                    f"vasty release {orphan_id(lease.instance_id)} --yes",
                )
            if row is not None:
                raise VastyError(
                    "provider_error",
                    f"Lease {lease.lease} changed while releasing: its expiry moved.",
                    f"Run vasty status {lease.lease}, then vasty release {lease.lease} again.",
                )
            return summarize(lease, max(snap.now, ctx.clock.now()), snap, already_absent=True)
        now = ctx.clock.now()
        if lease.state in HISTORY_STATES:
            save_lease(ctx, lease, lambda found: engine.mark_destroy_sent(found, now))
        else:
            save_lease(ctx, lease, lambda found: engine.mark_released(found, now))
    return summarize(lease, max(snap.now, ctx.clock.now()), snap)


def summarize(
    lease: CachedLease, now: int, snap: Snapshot, already_absent: bool = False
) -> ReleaseSummary:
    """Build the release summary from the cached lease."""
    jobs = []
    for job in lease.jobs:
        view = views.job_view(job, now, lease.state)
        jobs.append(ReleaseJob(view.id, view.cmd, view.exit, view.duration_s))
    return ReleaseSummary(
        lease=lease.lease,
        name=lease.label.name,
        uptime_s=views.uptime_s(lease, now),
        cost=views.lease_cost(lease.instance_id, snap.charges),
        jobs=jobs,
        destroy_pending=True if lease.destroy_pending else None,
        already_absent=True if already_absent else None,
    )


def _release_orphan(ctx: Context, snap: Snapshot, inst: Instance, yes: bool) -> ReleaseSummary:
    ref = orphan_id(inst.id)
    if not yes:
        if not ctx.stdin_tty:
            raise VastyError(
                "confirmation_required",
                f"{ref} is an instance vasty did not create.",
                f"Pass --yes to destroy it: vasty release {ref} --yes.",
            )
        gpu = inst.gpu_name or "unknown GPU"
        ctx.stderr.write(f"Destroy {ref} ({gpu}, ${money(inst.dph_total):.2f}/hr)? [y/N] ")
        ctx.stderr.flush()
        answer = ctx.stdin.readline().strip().lower()
        if answer not in ("y", "yes"):
            raise VastyError(
                "confirmation_required",
                f"Release of {ref} cancelled.",
                f"Pass --yes to destroy it: vasty release {ref} --yes.",
            )
    ctx.provider.destroy(inst.id)
    cost = views.lease_cost(inst.id, snap.charges)
    return ReleaseSummary(lease=ref, name=None, uptime_s=None, cost=cost, jobs=[])


def _entry_data(summary: ReleaseSummary) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": summary.name,
        "uptime_s": summary.uptime_s,
        "cost": summary.cost,
        "jobs": summary.jobs,
    }
    if summary.destroy_pending is not None:
        data["destroy_pending"] = summary.destroy_pending
    if summary.already_absent is not None:
        data["already_absent"] = summary.already_absent
    return data


# Human rendering.


def _cost(value: Decimal | None) -> str:
    return "?" if value is None else f"${money(value):.2f}"


def _summary_lines(summary: ReleaseSummary) -> list[str]:
    name = f" ({summary.name})" if summary.name else ""
    verb = "already gone" if summary.already_absent else "released"
    uptime = "?" if summary.uptime_s is None else format_duration(summary.uptime_s)
    head = f"{summary.lease}{name} {verb}  uptime {uptime}  cost {_cost(summary.cost)}"
    if summary.destroy_pending:
        head += "  destroy pending"
    lines = [head]
    for job in summary.jobs:
        code = "running" if job.exit is None else f"exit {job.exit}"
        took = "" if job.duration_s is None else f"  {format_duration(job.duration_s)}"
        lines.append(f"  {job.id} {job.cmd}  {code}{took}")
    return lines


def _tail(warnings: list[WarningItem], swept: list[SweptEntry]) -> list[str]:
    from vasty.commands.status import swept_lines, warning_lines

    blocks = [swept_lines(swept), warning_lines(warnings)]
    return ["\n".join(block) for block in blocks if block]


def _render_one(
    summary: ReleaseSummary, warnings: list[WarningItem], swept: list[SweptEntry]
) -> str:
    return "\n\n".join(["\n".join(_summary_lines(summary)), *_tail(warnings, swept)])


def _render_bulk(result: BulkResult) -> str:
    lines: list[str] = []
    for entry in result.results:
        if entry.ok:
            summary = ReleaseSummary(
                lease=entry.lease,
                name=entry.data.get("name"),
                uptime_s=entry.data.get("uptime_s"),
                cost=entry.data.get("cost"),
                jobs=entry.data.get("jobs", []),
                destroy_pending=entry.data.get("destroy_pending"),
                already_absent=entry.data.get("already_absent"),
            )
            lines += _summary_lines(summary)
        else:
            lines.append(f"{entry.lease} failed: {entry.error}: {entry.data.get('message', '')}")
    if not lines:
        lines.append("No leases matched.")
    return "\n\n".join(["\n".join(lines), *_tail(result.warnings, result.swept)])
