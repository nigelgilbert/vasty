"""`rig extend` (spec §4.2, §4.0, §6).

`extend` takes one `now` for every target and checks the budget once for the
whole target, replacing each lease's commitment with its new expiry. Each
lease then gets two writes in the order §6 sets: clock file then label when
lengthening, label then clock file when shortening. A failed second write
restores the first and returns `provider_error`; the lease shows
`guard: partial` with `clock_file` missing until the next probe.

Under the `leases.json` lock, `extend` reloads each target from the file and
computes the new expiry and the budget from that copy. A target another local
process released since `refresh` returns `lease_expired` and keeps its cache
entry.

A lease is writable when the refresh's probe reached it. A `pending` lease
that SSH has never answered returns `lease_pending`. An `unreachable` or
`stopped` lease returns `box_unreachable` and changes nothing.
"""

from __future__ import annotations

import argparse
import dataclasses
import shlex
from collections.abc import Mapping

from rig import budget, engine, labels, views
from rig.cli import Outcome
from rig.context import Context
from rig.errors import EXIT_CODES, RigError, invalid
from rig.ids import orphan_id
from rig.models import (
    HISTORY_STATES,
    BulkEntry,
    BulkResult,
    CachedLease,
    ExtendResult,
    Label,
    WarningItem,
)
from rig.state import effective_expiry
from rig.targeting import resolve_target
from rig.timeutil import format_duration, iso, parse_duration, parse_time

EXTEND_BUDGET_HINT = "Extend by less, or release a lease. Run rig status."


@dataclasses.dataclass(frozen=True)
class Change:
    """How the command moves each clock: by a delta, or to one expiry.

    `after` is the `--to` duration counted from `now`. `at` resolves it once
    `now` is known, so every target shares one `now`.
    """

    by: int | None = None
    to: int | None = None
    after: int | None = None

    def at(self, now: int) -> Change:
        if self.after is None:
            return self
        return Change(to=now + self.after)


def parse_change(args: argparse.Namespace) -> Change:
    """Read exactly one of `--by`, `--to` and `--until`. Raise `invalid_arguments` otherwise."""
    given = [flag for flag in ("by", "to", "until") if getattr(args, flag, None) is not None]
    if len(given) != 1:
        raise invalid(
            "extend takes exactly one of --by, --to or --until.",
            "rig extend LEASE --by 30m",
        )
    flag = given[0]
    value = getattr(args, flag)
    if flag == "by":
        return Change(by=parse_duration(value))
    if flag == "to":
        return Change(after=parse_duration(value))
    return Change(to=parse_time(value))


def new_expiry(lease: CachedLease, change: Change) -> int:
    """Return the lease's expiry after the change."""
    if change.to is not None:
        return change.to
    assert change.by is not None
    return effective_expiry(lease.label) + change.by


def _release_hint(args: argparse.Namespace | None, lease: str | None) -> str:
    if lease is not None or args is None:
        return shlex.join(["rig", "release", lease or "LEASE"])
    argv = ["rig", "release"]
    for flag in ("group", "owner"):
        value = getattr(args, flag, None)
        if value:
            argv += [f"--{flag}", value]
    if getattr(args, "all", False):
        argv.append("--all")
    if getattr(args, "everyone", False):
        argv.append("--everyone")
    return shlex.join(argv)


def _expired(lease: CachedLease) -> RigError:
    state = lease.state if lease.state in HISTORY_STATES else "being destroyed"
    return RigError(
        "lease_expired", f"Lease {lease.lease} is {state}.", "Run rig reserve for a new box."
    )


def check_writable(lease: CachedLease) -> None:
    """Raise `lease_expired`, `lease_pending` or `box_unreachable` for a lease extend cannot write."""
    if lease.state in HISTORY_STATES:
        raise _expired(lease)
    if lease.state == "pending" and lease.reachable_at is None:
        raise RigError(
            "lease_pending", f"Lease {lease.lease} does not answer SSH yet.",
            f"Wait for the box, then run rig status {lease.lease}.",
        )
    if lease.state in ("unreachable", "stopped"):
        raise RigError(
            "box_unreachable",
            f"Lease {lease.lease} is {lease.state}; its clock file cannot be reached.",
            shlex.join(["rig", "release", lease.lease]),
        )


def _reload(cached: Mapping[str, CachedLease], lease: CachedLease) -> CachedLease:
    """Return the copy of `lease` in `cached`, or `lease` when `cached` lacks it.

    Pass the leases from `leases.json` read under its lock, so a release or
    extend by another local process since `refresh` counts. Raise
    `lease_expired` when that copy is in history or has `destroy_pending`.
    """
    found = cached.get(lease.lease, lease)
    if found.state in HISTORY_STATES or found.destroy_pending:
        raise _expired(found)
    return found


def _mark_partial(lease: CachedLease) -> None:
    if "clock_file" not in lease.guard_missing:
        lease.guard_missing = [*lease.guard_missing, "clock_file"]


def _write_clock(ctx: Context, lease: CachedLease, expires: int) -> None:
    try:
        ctx.box.write_clock(engine.ssh_target(lease), expires)
    except OSError as exc:
        raise RigError("box_unreachable", f"Clock write failed: {exc}.", "Run rig status.") from exc


def _next_label(lease: CachedLease, expires: int) -> Label:
    return dataclasses.replace(
        lease.label, expires=expires, miss=[m for m in lease.label.miss if m != "clock_file"]
    )


def _write_label(ctx: Context, lease: CachedLease, read_expires: int | None, label: Label) -> None:
    if not engine.write_label(ctx, lease.instance_id, read_expires, label):
        raise RigError(
            "provider_error",
            f"Lease {lease.lease} changed since rig read it.",
            f"Run rig status {lease.lease}, then extend again.",
        )
    lease.label = label


def apply(ctx: Context, lease: CachedLease, expires: int) -> None:
    """Write `expires` to the clock file and the label in the §6 order and update the cache.

    Raise `invalid_arguments` before any write when the new label is too long,
    `box_unreachable` when the first write is a failed clock write, and
    `provider_error` when the label write fails or a second write fails.
    """
    old_label = lease.label
    new_label = _next_label(lease, expires)
    labels.format_label(new_label)
    old = effective_expiry(old_label)
    lengthen = expires >= old
    try:
        if lengthen:
            _write_clock(ctx, lease, expires)
            try:
                _write_label(ctx, lease, old_label.expires, new_label)
            except RigError as err:
                _restore_clock(ctx, lease, old, expires, err)
        else:
            _write_label(ctx, lease, old_label.expires, new_label)
            try:
                _write_clock(ctx, lease, expires)
            except RigError as err:
                _restore_label(ctx, lease, old_label, expires, err)
        lease.guard_missing = [m for m in lease.guard_missing if m != "clock_file"]
    finally:
        engine.store_lease(ctx, lease)


def _restore_clock(ctx: Context, lease: CachedLease, old: int, new: int, cause: RigError) -> None:
    _mark_partial(lease)
    try:
        _write_clock(ctx, lease, old)
    except RigError as again:
        raise _both_failed(lease, old, new, cause, again) from cause
    raise RigError(
        "provider_error",
        f"Label write for {lease.lease} failed: {cause.message} The clock file is back at {iso(old)}.",
        f"Run rig extend {lease.lease} again.",
    ) from cause


def _restore_label(
    ctx: Context, lease: CachedLease, old_label: Label, new: int, cause: RigError
) -> None:
    old = effective_expiry(old_label)
    _mark_partial(lease)
    try:
        if not engine.write_label(ctx, lease.instance_id, new, old_label):
            raise RigError("provider_error", "label changed since rig wrote it", "Run rig status.")
    except RigError as again:
        raise _both_failed(lease, old, new, cause, again) from cause
    lease.label = old_label
    raise RigError(
        "provider_error",
        f"Clock write for {lease.lease} failed: {cause.message} The label is back at {iso(old)}.",
        f"Run rig extend {lease.lease} again.",
    ) from cause


def _both_failed(
    lease: CachedLease, old: int, new: int, cause: RigError, again: RigError
) -> RigError:
    return RigError(
        "provider_error",
        f"Extend of {lease.lease} failed and the restore failed too: {cause.message} {again.message}",
        f"Run rig status {lease.lease}; the next networked command rewrites the clock file "
        "from the label.",
        details={"old_expires_at": iso(old), "new_expires_at": iso(new)},
    )


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    requested = parse_change(args)
    snap = engine.refresh(ctx)
    now = snap.now
    change = requested.at(now)
    resolved = resolve_target(ctx, snap, args, write=True)
    if resolved.orphans:
        inst = resolved.orphans[0]
        raise RigError(
            "orphan_unmanaged",
            f"{orphan_id(inst.id)} is not a rig lease.",
            shlex.join(["rig", "tag", orphan_id(inst.id), "--ttl", "30m"]),
        )
    if change.to is not None and change.to <= now:
        single = resolved.leases[0].lease if not resolved.bulk and resolved.leases else None
        raise invalid("The new expiry is at or before now.", _release_hint(args, single))
    if not resolved.bulk:
        return _single(ctx, snap, resolved.leases[0], change)
    return _bulk(ctx, snap, args, resolved.leases, change)


def _single(
    ctx: Context, snap: engine.Snapshot, lease: CachedLease, change: Change
) -> Outcome:
    now = snap.now
    check_writable(lease)
    with ctx.cache.lock():
        lease = _reload(ctx.cache.load().leases, lease)
        expires = new_expiry(lease, change)
        if expires <= now:
            raise invalid("The new expiry is at or before now.", _release_hint(None, lease.lease))
        projected, daily = engine.budget_check(
            ctx, snap, hint=EXTEND_BUDGET_HINT, replace={lease.lease: expires},
            leases=engine.locked_active(ctx, snap),
        )
        apply(ctx, lease, expires)
    warnings = views.warnings_for([lease], now, ctx.settings.warn_before_expiry)
    warnings += snap.warnings
    low = budget.budget_low_warning(projected, daily)
    if low is not None:
        warnings.append(low)
    final = effective_expiry(lease.label)
    result = ExtendResult(
        lease=lease.lease,
        expires_at=iso(final),
        ttl_remaining_s=max(0, final - now),
        warnings=warnings,
        swept=snap.swept,
    )
    human = None
    if ctx.mode == "human":
        human = f"{lease.lease}  expires {iso(final)}  ({format_duration(max(0, final - now))} left)"
    return Outcome(result, human=human)


def _bulk(
    ctx: Context,
    snap: engine.Snapshot,
    args: argparse.Namespace,
    leases: list[CachedLease],
    change: Change,
) -> Outcome:
    now = snap.now
    leases = list(leases)
    errors: dict[str, RigError] = {}
    targets: dict[str, int] = {}
    for lease in leases:
        try:
            check_writable(lease)
        except RigError as err:
            errors[lease.lease] = err
    warnings: list[WarningItem] = []
    entries: list[BulkEntry] = []
    with ctx.cache.lock():
        cached = ctx.cache.load().leases
        for index, lease in enumerate(leases):
            if lease.lease in errors:
                continue
            try:
                leases[index] = lease = _reload(cached, lease)
                expires = new_expiry(lease, change)
                if expires <= now:
                    raise invalid(
                        "The new expiry is at or before now.", _release_hint(args, lease.lease)
                    )
                targets[lease.lease] = expires
            except RigError as err:
                errors[lease.lease] = err
        if targets:
            projected, daily = engine.budget_check(
                ctx, snap, hint=EXTEND_BUDGET_HINT, replace=targets,
                leases=engine.locked_active(ctx, snap),
            )
            low = budget.budget_low_warning(projected, daily)
            if low is not None:
                warnings.append(low)
        for lease in leases:
            if lease.lease in targets:
                try:
                    apply(ctx, lease, targets[lease.lease])
                except RigError as failure:
                    errors[lease.lease] = failure
            found = errors.get(lease.lease)
            entries.append(BulkEntry(
                lease=lease.lease,
                ok=found is None,
                error=found.code if found is not None else None,
                data={"expires_at": iso(effective_expiry(lease.label))},
            ))
    warnings = views.warnings_for(leases, now, ctx.settings.warn_before_expiry) + warnings
    warnings = warnings + list(snap.warnings)
    exit_code = max((EXIT_CODES[err.code] for err in errors.values()), default=0)
    result = BulkResult(results=entries, warnings=warnings, swept=snap.swept)
    human = None
    if ctx.mode == "human":
        lines = []
        for entry in entries:
            outcome = "ok" if entry.ok else f"failed ({entry.error})"
            lines.append(f"{entry.lease}  expires {entry.data['expires_at']}  {outcome}")
        human = "\n".join(lines) if lines else "no leases matched"
    return Outcome(result, exit_code=exit_code, human=human)
