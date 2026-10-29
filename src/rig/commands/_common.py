"""Helpers shared by `release`, `run`, `serve`, `sync` and `ssh`.

`pick_lease` resolves the single LEASE that `run --on`, `serve --on`, `sync`
and `ssh` act on and raises the §7 code for a lease they cannot use.
`save_lease` applies one change to a lease in the snapshot and in
`leases.json`. Job ids count up from the highest `j-N` the lease has seen.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Callable

from rig.errors import RigError
from rig.models import HISTORY_STATES, CachedLease, Instance, WarningItem
from rig.targeting import resolve_lease
from rig.views import warnings_for

if TYPE_CHECKING:
    from rig.context import Context
    from rig.engine import Snapshot

DEFAULT_EXCLUDES: tuple[str, ...] = (".git", "__pycache__", ".venv", "node_modules")
WORKDIR = "/workspace"
_JOB_NUMBER = re.compile(r"j-([0-9]+)")


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
        match = _JOB_NUMBER.fullmatch(job.id)
        if match is not None:
            highest = max(highest, int(match.group(1)))
    return f"j-{highest + 1}"


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


def lease_warnings(ctx: Context, snap: Snapshot, lease: CachedLease, now: int) -> list[WarningItem]:
    """Return the refresh's account warnings plus the lease's own warnings."""
    return merge_warnings(
        snap.warnings, warnings_for([lease], now, ctx.settings.warn_before_expiry)
    )
