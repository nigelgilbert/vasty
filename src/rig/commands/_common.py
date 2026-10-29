"""Helpers shared by `release`, `reserve`, `run`, `serve`, `sync`, `ssh` and `tag`.

`pick_lease` resolves the single LEASE that `run --on`, `serve --on`, `sync`
and `ssh` act on and raises the §7 code for a lease they cannot use.
`save_lease` applies one change to a lease in the snapshot and in
`leases.json`. Job ids count up from the highest `j-N` the lease has seen.
`taken_ids` lists the lease ids a new lease id avoids.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from rig import labels
from rig.errors import RigError
from rig.ids import job_number
from rig.models import (
    HISTORY_STATES,
    CachedLease,
    Instance,
    Job,
    Label,
    SweptEntry,
    WarningItem,
)
from rig.targeting import resolve_lease
from rig.views import warnings_for

if TYPE_CHECKING:
    from rig.context import Context
    from rig.engine import Snapshot

DEFAULT_EXCLUDES: tuple[str, ...] = (".git", "__pycache__", ".venv", "node_modules")


def require_tools(ctx: Context, *names: str) -> None:
    """Raise `dependency_missing` for the first tool missing from PATH."""
    for name in names:
        if ctx.which(name) is None:
            raise RigError(
                "dependency_missing", f"{name} is not on PATH.", f"Install {name} and retry."
            )


def pick_lease(ctx: Context, snap: Snapshot, ref: str) -> CachedLease:
    """Resolve one lease that SSH can use.

    Raise `orphan_unmanaged` for an orphan or unreadable row, `lease_expired`
    for a lease in history and `lease_pending` for a lease SSH has never
    reached or that has no endpoint.
    """
    found = resolve_lease(ctx, snap, ref)
    if isinstance(found, Instance):
        raise RigError(
            "orphan_unmanaged",
            f"{ref} is an instance rig does not manage.",
            f"Adopt it first: rig tag {ref} --ttl 30m.",
        )
    if found.state in HISTORY_STATES or found.destroy_pending:
        raise RigError(
            "lease_expired",
            f"Lease {found.lease} is {found.state}.",
            "Reserve a new box with rig reserve.",
        )
    if found.reachable_at is None or not found.ssh_host or not found.ssh_port:
        raise RigError(
            "lease_pending",
            f"Lease {found.lease} has not answered SSH yet.",
            f"Wait for the box, then run rig status {found.lease}.",
        )
    return found


def next_job_id(lease: CachedLease) -> str:
    """Return `j-N` one past the highest job number on the lease."""
    highest = 0
    for job in lease.jobs:
        number = job_number(job.id)
        if number is not None:
            highest = max(highest, number)
    return f"j-{highest + 1}"


def put_job(lease: CachedLease, job: Job) -> None:
    """Add `job` to the lease, replacing any job with the same id."""
    lease.jobs = [j for j in lease.jobs if j.id != job.id] + [job]


def finish_job(lease: CachedLease, job_id: str, exit_code: int | None, finished: int | None) -> None:
    """Mark job `job_id` exited with `exit_code` at `finished`."""
    for job in lease.jobs:
        if job.id == job_id:
            job.exit = exit_code
            job.state = "exited"
            job.finished_at = finished


def taken_ids(snap: Snapshot) -> set[str]:
    """Return the lease ids in the snapshot's leases and in its instances' `rig:` labels."""
    taken = set(snap.leases)
    for inst in snap.instances:
        parsed = labels.parse(inst.label)
        if isinstance(parsed, Label):
            taken.add(parsed.lease)
    return taken


def save_lease(ctx: Context, lease: CachedLease, change: Callable[[CachedLease], None]) -> None:
    """Apply `change` to `lease` and to its record in `leases.json`, adding the record when absent."""
    change(lease)
    with ctx.cache.lock():
        data = ctx.cache.load()
        cached = data.leases.get(lease.lease)
        if cached is None:
            data.leases[lease.lease] = lease
        elif cached is not lease:
            change(cached)
        ctx.cache.save(data)


def merge_warnings(*groups: list[WarningItem]) -> list[WarningItem]:
    """Concatenate warning lists, dropping repeats of the same code, lease and message."""
    seen: set[tuple[str, str | None, str]] = set()
    out: list[WarningItem] = []
    for group in groups:
        for item in group:
            key = (item.code, item.lease, item.message)
            if key not in seen:
                seen.add(key)
                out.append(item)
    return out


def merge_swept(*groups: list[SweptEntry]) -> list[SweptEntry]:
    """Concatenate `swept` lists, keeping the first entry for each lease, `ok` and `error`.

    A failed retry's `expired_at` moves with each refresh, so the key leaves it out.
    """
    seen: set[tuple[str, bool, str | None]] = set()
    out: list[SweptEntry] = []
    for group in groups:
        for entry in group:
            key = (entry.lease, entry.ok, entry.error)
            if key not in seen:
                seen.add(key)
                out.append(entry)
    return out


def lease_warnings(ctx: Context, snap: Snapshot, lease: CachedLease, now: int) -> list[WarningItem]:
    """Return the refresh's account warnings plus the lease's own warnings."""
    return merge_warnings(
        snap.warnings, warnings_for([lease], now, ctx.settings.warn_before_expiry)
    )
