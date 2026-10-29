"""Lease state, guard and per-lease warnings (spec §3, §3.1, §4.4).

The fix table lives here so every module builds warnings the same way. Fixes
name a lease by its id, which resolves for every owner.
"""

from __future__ import annotations

import shlex

from rig.models import HISTORY_STATES, CachedLease, Label, LeaseState, ProbeResult, WarningItem
from rig.timeutil import format_duration

GUARD_LAYERS: tuple[str, ...] = ("watchdog", "destroy_key", "clock_file")
LIVE_JOB_STATES: frozenset[str] = frozenset({"running", "serving"})

_PENDING_STATUSES = frozenset({"created", "loading"})
_STOPPED_STATUSES = frozenset({"exited", "stopped"})
_UNREACHABLE_STATUSES = frozenset({"offline", "unknown"})

_LAYER_MESSAGES: dict[str, str] = {
    "watchdog": "watchdog not running",
    "destroy_key": "destroy key missing",
    "clock_file": "clock file out of sync",
}

_L = "{L}"
_FIXES: dict[str, list[str]] = {
    "expiring_soon": ["rig", "extend", _L, "--by", "30m"],
    "expiring_with_running_job": ["rig", "extend", _L, "--by", "30m"],
    "box_unreachable": ["rig", "release", _L],
    "guard_partial": ["rig", "release", _L],
    "orphan": ["rig", "tag", _L, "--ttl", "30m"],
    "startup_failed": ["rig", "ssh", _L, "--", "cat", "/workspace/.rig/startup.log"],
    "expired_with_running_jobs": ["rig", "status", _L],
    "flag_mismatch": ["rig", "status", _L],
    "label_unreadable": ["rig", "release", _L],
    "budget_low": ["rig", "status"],
    "spend_unavailable": ["rig", "status"],
    "clock_unverified": ["rig", "status"],
    "cache_rebuilt": ["rig", "status"],
}


def effective_expiry(label: Label) -> int:
    """Return `expires`, else `created + ttl`."""
    if label.expires is not None:
        return label.expires
    return label.created + label.ttl


def ttl_remaining(label: Label, now: int) -> int:
    """Return seconds from `now` to the effective expiry, floored at 0."""
    return max(0, effective_expiry(label) - now)


def derive_state(actual_status: str | None, probe: ProbeResult | None, reachable_before: bool) -> LeaseState:
    """Map the provider status and the probe to a rig state (spec §3.1 table).

    `probe` is None when the probe failed or did not run. `reachable_before`
    is True when the probe answered on an earlier command. An `actual_status`
    outside the table maps like `running` without a probe: `unreachable` when
    the box answered before, else `pending`.
    """
    status = actual_status.strip().lower() if actual_status is not None else None
    if status is None or status in _PENDING_STATUSES:
        return "pending"
    if status in _STOPPED_STATUSES:
        return "stopped"
    if status in _UNREACHABLE_STATUSES:
        return "unreachable"
    if status == "running" and probe is not None:
        return "pending" if startup_unfinished(probe) else "running"
    return "unreachable" if reachable_before else "pending"


def startup_unfinished(probe: ProbeResult) -> bool:
    """Return True when the hook started and has neither an exit marker nor a restart cut-off."""
    return probe.startup_started and probe.startup_exit is None and not probe.startup_interrupted


def resolve_state(previous: LeaseState, derived: LeaseState) -> LeaseState:
    """Keep a history state over a derived `pending` or `unreachable` (spec §3.1)."""
    if previous in HISTORY_STATES and derived in ("pending", "unreachable"):
        return previous
    return derived


def guard(lease: CachedLease) -> tuple[str, list[str]]:
    """Return `full` or `partial` and the missing layers.

    Read `lease.guard_missing`, keep the known layers in the order `watchdog`,
    `destroy_key`, `clock_file`, and drop duplicates and unknown names.
    """
    present = set(lease.guard_missing)
    missing = [layer for layer in GUARD_LAYERS if layer in present]
    return ("partial" if missing else "full"), missing


def fix_for(code: str, target: str | None) -> str:
    """Return the shell-quoted fix command for a warning code."""
    template = _FIXES.get(code)
    if template is None:
        raise ValueError(f"unknown warning code {code!r}")
    if _L in template and target is None:
        raise ValueError(f"warning {code!r} needs a lease")
    return shlex.join(target if part == _L and target is not None else part for part in template)


def make_warning(code: str, lease: str | None, message: str) -> WarningItem:
    """Build a warning whose fix comes from the shared table. Pass `lease` None for account warnings."""
    return WarningItem(code=code, lease=lease, message=message, fix=fix_for(code, lease))


def live_jobs(lease: CachedLease) -> list[str]:
    """Return the ids of cached jobs in `running` or `serving` state."""
    return [job.id for job in lease.jobs if job.state in LIVE_JOB_STATES]


def startup_failed(lease: CachedLease) -> bool:
    """Return True when the hook exited non-zero or a restart cut it off."""
    if lease.startup_exit is not None and lease.startup_exit != 0:
        return True
    return lease.startup_exit is None and lease.startup_interrupted


def lease_warnings(lease: CachedLease, now: int, warn_before_expiry: int) -> list[WarningItem]:
    """Return the per-lease warnings with their fixes.

    Codes: `expiring_soon` or `expiring_with_running_job`, `box_unreachable`,
    `guard_partial`, `startup_failed` on active leases, and
    `expired_with_running_jobs` on an `expired` lease. `guard_partial` needs
    observed layers: a probe answered (`reachable_at`), another machine's
    probe wrote `miss=` to the label, or `tag` adopted the box without a
    guard.
    """
    target = lease.lease
    jobs = live_jobs(lease)
    out: list[WarningItem] = []
    if lease.state == "expired":
        if jobs:
            message = f"expired with {', '.join(jobs)} running"
            out.append(make_warning("expired_with_running_jobs", target, message))
        return out
    if lease.state in HISTORY_STATES or lease.state == "orphan":
        return out
    remaining = ttl_remaining(lease.label, now)
    if lease.state == "running" and 0 < remaining <= warn_before_expiry:
        if jobs:
            message = f"{format_duration(remaining)} left, {', '.join(jobs)} running"
            out.append(make_warning("expiring_with_running_job", target, message))
        else:
            out.append(make_warning("expiring_soon", target, f"{format_duration(remaining)} left"))
    if lease.state == "unreachable":
        if lease.reachable_at is None:
            message = "no answer"
        else:
            message = f"no answer for {format_duration(now - lease.reachable_at)}"
        out.append(make_warning("box_unreachable", target, message))
    level, missing = guard(lease)
    observed = lease.reachable_at is not None or bool(lease.label.miss) or lease.adopted
    if level == "partial" and observed:
        message = ", ".join(_LAYER_MESSAGES[layer] for layer in missing)
        out.append(make_warning("guard_partial", target, message))
    if startup_failed(lease):
        if lease.startup_exit is not None:
            message = f"startup exited {lease.startup_exit}"
        else:
            message = "startup cut off by a restart"
        out.append(make_warning("startup_failed", target, message))
    return out
