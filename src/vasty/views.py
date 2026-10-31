"""Output builders shared by the commands.

Lease cost is the sum of Vast's charge rows for the instance, or None before
Vast posts a row. Uptime runs from the first `running` sample and is None
before it.

This module imports only the standard library and vasty modules that do.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from vasty import labels
from vasty.errors import VastyError
from vasty.ids import orphan_id
from vasty.models import (
    HISTORY_STATES,
    CachedLease,
    Charges,
    Instance,
    Job,
    JobView,
    LeaseView,
    TagEntry,
    WarningItem,
)
from vasty.remote import SshTarget
from vasty.state import (
    GUARD_LAYERS,
    LIVE_JOB_STATES,
    effective_expiry,
    guard,
    lease_warnings,
    make_warning,
)
from vasty.timeutil import iso


def uptime_end(lease: CachedLease, now: int) -> int:
    """Return when the box stopped billing: now for active leases, else when vasty saw it go."""
    if lease.state not in HISTORY_STATES:
        return now
    if lease.state == "expired" and lease.expired_at is not None:
        return min(now, lease.expired_at)
    return lease.history_since if lease.history_since is not None else now


def uptime_s(lease: CachedLease, now: int) -> int | None:
    """Return seconds from `running_at` to `uptime_end`, floored at 0, or None before it."""
    if lease.running_at is None:
        return None
    return max(0, uptime_end(lease, now) - lease.running_at)


def lease_cost(instance_id: int, charges: Charges | None) -> Decimal | None:
    """Return the sum of Vast's charge rows for the instance, or None when none exist."""
    if charges is None:
        return None
    return charges.per_instance.get(instance_id)


def burn_per_hr(live: Iterable[Instance]) -> Decimal:
    """Return the sum of `dph_total` over live leases and orphans."""
    return sum((inst.dph_total for inst in live), Decimal("0"))


def show_jobs_unknown(state: str) -> bool:
    """Return True when live jobs show as `unknown`: the box is unreachable or gone."""
    return state == "unreachable" or state in HISTORY_STATES


def job_view(job: Job, now: int, lease_state: str) -> JobView:
    """Build a job entry. Live jobs on an unreachable or destroyed box report `unknown`."""
    state: str = job.state
    exit_code = job.exit
    if job.state in LIVE_JOB_STATES and show_jobs_unknown(lease_state):
        state, exit_code = "unknown", None
    if job.state == "unknown":
        exit_code = None
    duration = None
    if job.started_at is not None:
        end = job.finished_at if job.finished_at is not None else now
        duration = max(0, end - job.started_at)
    return JobView(id=job.id, cmd=job.cmd, state=state, exit=exit_code, duration_s=duration)


def ports_view(ports: dict[int, int]) -> dict[str, int]:
    """Return the port map with string keys, sorted by container port."""
    return {str(k): ports[k] for k in sorted(ports)}


def ssh_command(target: SshTarget) -> str:
    """Return `ssh -p PORT root@HOST`."""
    return f"ssh -p {target.port} {target.user}@{target.host}"


def rsync_target(target: SshTarget) -> str:
    """Return `root@HOST:`."""
    return f"{target.user}@{target.host}:"


@dataclass
class Endpoint:
    """The connection fields of a reserve-style result; all None before SSH has an endpoint."""

    ssh: str | None
    rsync_target: str | None
    ssh_port: int | None
    ports: dict[str, int] | None


def endpoint_fields(lease: CachedLease) -> Endpoint:
    """Return `ssh`, `rsync_target`, `ssh_port` and `ports` for a lease."""
    if not lease.ssh_host or not lease.ssh_port:
        return Endpoint(None, None, None, None)
    target = SshTarget(instance_id=lease.instance_id, host=lease.ssh_host, port=lease.ssh_port)
    return Endpoint(ssh_command(target), rsync_target(target), target.port, ports_view(lease.ports))


def _full_label(lease: CachedLease) -> str | None:
    try:
        return labels.format_label(lease.label)
    except VastyError:
        return None


def lease_verbose(lease: CachedLease) -> dict[str, Any]:
    """Return the `--verbose` extras: label, guard layers, instance id, image, ports, last error."""
    _, missing = guard(lease)
    return {
        "label": _full_label(lease),
        "guard_layers": {
            layer: "missing" if layer in missing else "ok" for layer in GUARD_LAYERS
        },
        "instance_id": lease.instance_id,
        "image": lease.image,
        "ports": ports_view(lease.ports),
        "actual_status": lease.actual_status,
        "reachable_at": iso(lease.reachable_at),
        "running_at": iso(lease.running_at),
        "last_provider_error": lease.last_provider_error,
    }


def lease_view(
    lease: CachedLease,
    now: int,
    verbose: bool = False,
    charges: Charges | None = None,
    log_tail: list[str] | None = None,
) -> LeaseView:
    """Build one `status.leases` entry for a managed lease."""
    level, missing = guard(lease)
    expiry = effective_expiry(lease.label)
    return LeaseView(
        lease=lease.lease,
        name=lease.label.name,
        group=lease.label.group,
        owner=lease.label.owner,
        state=lease.state,
        guard=level,
        guard_missing=missing,
        gpu=lease.gpu,
        price_per_hr=lease.price_per_hr,
        cost=lease_cost(lease.instance_id, charges),
        uptime_s=uptime_s(lease, now),
        expires_at=iso(expiry),
        ttl_remaining_s=max(0, expiry - now),
        jobs=[job_view(job, now, lease.state) for job in lease.jobs],
        log_tail=log_tail,
        destroy_pending=True if lease.destroy_pending else None,
        verbose=lease_verbose(lease) if verbose else None,
    )


def orphan_view(
    inst: Instance, verbose: bool = False, charges: Charges | None = None
) -> LeaseView:
    """Build a `status.leases` entry for an orphan or unreadable row.

    Cost is the instance's billed sum, else null.
    """
    extras: dict[str, Any] | None = None
    if verbose:
        extras = {
            "label": inst.label,
            "instance_id": inst.id,
            "image": inst.image,
            "ports": ports_view(inst.ports),
            "actual_status": inst.actual_status,
        }
    return LeaseView(
        lease=orphan_id(inst.id),
        name=None,
        group=None,
        owner=None,
        state="orphan",
        guard=None,
        guard_missing=None,
        gpu=inst.gpu_name,
        price_per_hr=inst.dph_total,
        cost=lease_cost(inst.id, charges),
        uptime_s=None,
        expires_at=None,
        ttl_remaining_s=None,
        jobs=[],
        verbose=extras,
    )


def tag_entry(lease: CachedLease, now: int) -> TagEntry:
    """Build one `tag` result entry."""
    level, missing = guard(lease)
    expiry = effective_expiry(lease.label)
    return TagEntry(
        lease=lease.lease,
        name=lease.label.name,
        group=lease.label.group,
        owner=lease.label.owner,
        expires_at=iso(expiry),
        ttl_remaining_s=max(0, expiry - now),
        guard=level,
        guard_missing=missing,
    )


def warnings_for(
    leases: Iterable[CachedLease], now: int, warn_before_expiry: int
) -> list[WarningItem]:
    """Return the per-lease warnings for each lease in order."""
    out: list[WarningItem] = []
    for lease in leases:
        out.extend(lease_warnings(lease, now, warn_before_expiry))
    return out


def orphan_warning(inst: Instance) -> WarningItem:
    """Return the `orphan` warning for a row vasty did not create."""
    return make_warning("orphan", orphan_id(inst.id), "not created by vasty")
