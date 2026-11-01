"""`vasty status`.

With no target, `status` lists every active lease, then orphans and
unreadable rows. `--verbose` adds history leases: the current owner's,
`--owner O`'s, or every owner's with `--everyone`, narrowed by `--group`.
`--everyone` alone reads as `--all --everyone`. A named lease in history
always shows. A single LEASE carries `log_tail` in every state, `[]` when
the log is empty or unread. Warnings cover the shown leases,
`expired_with_running_jobs` for every history lease when no target is
given, the account warnings from the refresh, `orphan` per shown orphan,
and `spend_unavailable` when the balance or charges are unavailable.
`totals` covers the whole account with Vast's own `balance`, `credit` and
today's billed charges.

`--cached` reads `leases.json` only. It uses the local clock, returns
`swept: []`, sets `cached_at` and skips the log read. That path imports only
the standard library.
"""

from __future__ import annotations

import argparse
import posixpath
import shlex
from decimal import Decimal

from vasty import engine, views
from vasty.cli import Outcome
from vasty.context import Context
from vasty.errors import VastyError
from vasty.models import (
    HISTORY_STATES,
    SERVE_PORT,
    CachedLease,
    JobView,
    LeaseView,
    StatusResult,
    SweptEntry,
    Totals,
    WarningItem,
)
from vasty.output import money
from vasty.remote import LOG_LINES
from vasty.state import LIVE_JOB_STATES, make_warning
from vasty.targeting import has_target, resolve_target
from vasty.timeutil import format_duration, iso

DASH = "—"
WARN_MARK = "⚠ "
EXPIRING_CODES = frozenset({"expiring_soon", "expiring_with_running_job"})
SHORT_SKIP = frozenset({"python", "python3", "uv", "uvx", "run", "bash", "sh", "exec", "env"})


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    cached = bool(args.cached)
    if cached:
        snap = engine.cached_snapshot(ctx)
    else:
        snap = engine.refresh(ctx)
        engine.read_charges(ctx, snap)
        engine.read_balance(ctx, snap)
    verbose = bool(args.verbose)
    now = snap.now
    settings = ctx.settings

    targeted = has_target(args)
    single = False
    if targeted:
        resolved = resolve_target(ctx, snap, args, write=False)
        leases = resolved.leases
        rows = resolved.orphans
        single = not resolved.bulk
        if verbose and resolved.bulk:
            leases = leases + _history(snap, args, settings.owner)
    else:
        leases = snap.active() + (_history(snap, args, settings.owner) if verbose else [])
        rows = sorted(snap.orphans + snap.unreadable, key=lambda inst: inst.id)

    tail: list[str] = []
    if single and leases and not cached:
        tail = _log_tail(ctx, leases[0])
    lease_views = [
        views.lease_view(lease, now, verbose, snap.charges, tail if single else None)
        for lease in leases
    ]
    lease_views += [views.orphan_view(inst, verbose, snap.charges) for inst in rows]

    warnings = views.warnings_for(leases, now, settings.warn_before_expiry)
    if not targeted:
        shown = {lease.lease for lease in leases}
        extra = [lease for lease in snap.history() if lease.lease not in shown]
        warnings += [
            w for w in views.warnings_for(extra, now, settings.warn_before_expiry)
            if w.code == "expired_with_running_jobs"
        ]
    unreadable_ids = {inst.id for inst in snap.unreadable}
    warnings += [views.orphan_warning(inst) for inst in rows if inst.id not in unreadable_ids]
    warnings += snap.warnings

    if snap.charges is None or snap.balance is None:
        warnings.append(make_warning(
            "spend_unavailable", None, "Vast's balance or charges cannot be read"
        ))

    active = snap.active()
    totals = Totals(
        balance=snap.balance.balance if snap.balance is not None else None,
        credit=snap.balance.credit if snap.balance is not None else None,
        charges_today=snap.charges.today if snap.charges is not None else None,
        burn_per_hr=views.burn_per_hr(snap.live_instances()),
        live=len(active),
        live_mine=sum(1 for lease in active if lease.label.owner == settings.owner),
    )
    result = StatusResult(
        leases=lease_views,
        warnings=warnings,
        totals=totals,
        swept=[] if cached else snap.swept,
        cached_at=iso(snap.cached_at) if cached else None,
    )
    human = None
    if ctx.mode == "human":
        by_id = {lease.lease: lease for lease in leases}
        group = getattr(args, "group", None)
        human = render(result, by_id, group, cached)
    return Outcome(result, human=human)


def _history(snap: engine.Snapshot, args: argparse.Namespace, owner: str) -> list[CachedLease]:
    """Return history leases of `--owner O`, else the current owner, or every owner with `--everyone`."""
    scope = getattr(args, "owner", None) or (None if getattr(args, "everyone", False) else owner)
    group = getattr(args, "group", None)
    return [
        lease for lease in snap.history()
        if (scope is None or lease.label.owner == scope)
        and (not group or lease.label.group == group)
    ]


def _log_tail(ctx: Context, lease: CachedLease) -> list[str]:
    if lease.state in HISTORY_STATES or lease.state in ("unreachable", "stopped"):
        return []
    try:
        return ctx.box.log_tail(engine.ssh_target(lease), None, LOG_LINES)
    except (VastyError, OSError):
        return []


# Human rendering.


def short_cmd(cmd: str, kind: str) -> str:
    """Return a short job name: `vllm` for a served model, else the script's basename."""
    if kind == "serve":
        return "vllm"
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = cmd.split()
    for token in tokens:
        if token.startswith("-") or token in SHORT_SKIP or "=" in token:
            continue
        return posixpath.basename(token.rstrip("/")) or token
    return cmd


def gpu_text(gpu: str | None, gpus: int, vram_gb: float | None) -> str:
    """Return the GPU cell as count, per-GPU GB and name, such as `1x12 3060`."""
    if gpu is None:
        return "?"
    name = gpu
    for prefix in ("RTX ", "GTX "):
        if name.startswith(prefix):
            name = name[len(prefix):]
    vram = "?" if vram_gb is None else str(int(vram_gb))
    return f"{gpus}x{vram} {name}"


def _job_parts(view: JobView, lease: CachedLease | None) -> tuple[str, str]:
    kind, port = "run", None
    if lease is not None:
        for job in lease.jobs:
            if job.id == view.id:
                kind, port = job.kind, job.port
    return short_cmd(view.cmd, kind), str(port or SERVE_PORT)


def _shown_jobs(view: LeaseView) -> list[JobView]:
    return [job for job in view.jobs if job.state in LIVE_JOB_STATES or job.state == "unknown"]


def jobs_cell(view: LeaseView, lease: CachedLease | None) -> str:
    parts = []
    for job in _shown_jobs(view):
        name, port = _job_parts(job, lease)
        if job.state == "running":
            parts.append(f"{job.id} {name} (running {format_duration(job.duration_s or 0, pad=True)})")
        elif job.state == "serving":
            parts.append(f"{job.id} {name} (serving :{port})")
        else:
            parts.append(f"{job.id} {name} (unknown)")
    if parts:
        return ", ".join(parts)
    return "idle" if view.busy is False else DASH


def group_jobs_cell(view: LeaseView, lease: CachedLease | None) -> str:
    parts = []
    for job in _shown_jobs(view):
        name, _ = _job_parts(job, lease)
        if job.state == "running":
            parts.append(f"{job.id} {name} running")
        else:
            parts.append(f"{job.id} {job.state}")
    return ", ".join(parts) if parts else "idle"


def expires_cell(view: LeaseView, expiring: set[str]) -> str:
    if view.state == "orphan":
        return "none"
    if view.state in HISTORY_STATES or view.ttl_remaining_s is None:
        return DASH
    text = format_duration(view.ttl_remaining_s)
    return WARN_MARK + text if view.lease in expiring else text


def _money(value: Decimal | None) -> str:
    return "?" if value is None else f"{money(value):.2f}"


def table(rows: list[list[str]], indent: str = "", gap: str = "  ") -> list[str]:
    """Align columns; the last column is not padded."""
    if not rows:
        return []
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    out = []
    for row in rows:
        cells = [cell.ljust(widths[i]) for i, cell in enumerate(row[:-1])] + [row[-1]]
        out.append((indent + gap.join(cells)).rstrip())
    return out


def lease_table(result: StatusResult, by_id: dict[str, CachedLease], expiring: set[str]) -> list[str]:
    header = ["LEASE", "NAME", "GROUP", "OWNER", "GPU", "STATE", "EXPIRES", "UPTIME", "$/HR",
              "COST", "JOBS"]
    rows = [header]
    for view in result.leases:
        lease = by_id.get(view.lease)
        rows.append([
            view.lease,
            view.name or DASH,
            view.group or DASH,
            view.owner or "?",
            gpu_text(view.gpu, view.gpus, view.vram_gb),
            view.state,
            expires_cell(view, expiring),
            DASH if view.uptime_s is None else format_duration(view.uptime_s),
            _money(view.price_per_hr),
            _money(view.cost),
            jobs_cell(view, lease),
        ])
    return table(rows)


def group_lines(
    result: StatusResult, by_id: dict[str, CachedLease], group: str, expiring: set[str]
) -> list[str]:
    managed = [view for view in result.leases if view.state != "orphan"]
    count = len(managed)
    head = [f"GROUP {group}", f"{count} lease{'s' if count != 1 else ''}"]
    if managed:
        states: dict[str, int] = {}
        for view in managed:
            key = "healthy" if view.state == "running" else view.state
            states[key] = states.get(key, 0) + 1
        order = sorted(states, key=lambda k: (k != "healthy", list(states).index(k)))
        head.append(", ".join(f"{states[k]} {k}" for k in order))
        ttls = [view.ttl_remaining_s for view in managed
                if view.ttl_remaining_s is not None and view.state not in HISTORY_STATES]
        if ttls:
            low, high = format_duration(min(ttls)), format_duration(max(ttls))
            head.append(f"expiries {low}" if low == high else f"expiries {low}–{high}")
        cost = sum((view.cost for view in managed if view.cost is not None), Decimal("0"))
        burn = sum((view.price_per_hr for view in managed if view.state not in HISTORY_STATES),
                   Decimal("0"))
        head.append(f"${money(cost):.2f} so far")
        head.append(f"${money(burn):.2f}/hr")
    lines = [" · ".join(head)]
    rows = [
        [f"{view.lease} {view.name or DASH}", view.state, expires_cell(view, expiring),
         group_jobs_cell(view, by_id.get(view.lease))]
        for view in managed
    ]
    return lines + table(rows, indent="  ")


def warning_lines(warnings: list[WarningItem]) -> list[str]:
    if not warnings:
        return []
    rows = [[w.lease or DASH, w.code, w.message, f"fix: {w.fix}"] for w in warnings]
    return ["WARNINGS", *table(rows, indent="  ")]


def swept_lines(swept: list[SweptEntry]) -> list[str]:
    out = []
    for entry in swept:
        outcome = "destroyed" if entry.ok else f"destroy failed ({entry.error})"
        name = f" {entry.name}" if entry.name else ""
        out.append(f"SWEPT  {entry.lease}{name}  expired {entry.expired_at}  {outcome}")
    return out


def _dollars(value: Decimal | None) -> str:
    return "unknown" if value is None else f"${money(value):.2f}"


def today_line(totals: Totals) -> str:
    noun = "lease" if totals.live == 1 else "leases"
    return (
        f"TODAY  charged {_dollars(totals.charges_today)}  ·  "
        f"credit {_dollars(totals.credit)}  ·  balance {_dollars(totals.balance)}  ·  "
        f"{totals.live} {noun} live ({totals.live_mine} yours)  ·  "
        f"burning ${money(totals.burn_per_hr):.2f}/hr"
    )


def verbose_lines(result: StatusResult) -> list[str]:
    out: list[str] = []
    for view in result.leases:
        if view.verbose is None:
            continue
        out.append(f"DETAIL {view.lease}")
        for key, value in view.verbose.items():
            if isinstance(value, dict):
                value = " ".join(f"{k}={v}" for k, v in value.items())
            out.append(f"  {key}: {DASH if value is None or value == '' else value}")
    return out


def render(
    result: StatusResult, by_id: dict[str, CachedLease], group: str | None, cached: bool
) -> str:
    """Render the human table, or the group view for `--group`, then warnings and totals."""
    expiring = {w.lease for w in result.warnings if w.code in EXPIRING_CODES and w.lease}
    blocks: list[list[str]] = []
    if cached:
        blocks.append([f"CACHED  as of {result.cached_at or 'never'}"])
    if result.swept:
        blocks.append(swept_lines(result.swept))
    if group:
        blocks.append(group_lines(result, by_id, group, expiring))
    else:
        blocks.append(lease_table(result, by_id, expiring))
    details = verbose_lines(result)
    if details:
        blocks.append(details)
    for view in result.leases:
        if view.log_tail:
            blocks.append([f"LOG {view.lease}", *view.log_tail])
    warn = warning_lines(result.warnings)
    if warn:
        blocks.append(warn)
    blocks.append([today_line(result.totals)])
    return "\n\n".join("\n".join(block) for block in blocks if block)

