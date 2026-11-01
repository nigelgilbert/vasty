"""Lease state, guard and per-lease warnings.

The fix table lives here so every module builds warnings the same way. Fixes
name a lease by its id, which resolves for every owner. The `expiring_*`
fixes extend by the lease's reserve ttl from the label.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from vasty.models import (
    HISTORY_STATES,
    CachedLease,
    Instance,
    Label,
    LeaseState,
    ProbeResult,
    WarningItem,
)
from vasty.timeutil import format_duration, format_duration_exact, format_minutes_up

if TYPE_CHECKING:
    from vasty.config import Settings
    from vasty.engine import Snapshot

GUARD_LAYERS: tuple[str, ...] = ("watchdog", "destroy_key", "clock_file")
CLOCK_SKEW_WARN_S = 120
"""Box clock skew past this many seconds raises `clock_skew`."""
LIVE_JOB_STATES: frozenset[str] = frozenset({"running", "serving"})

_PENDING_STATUSES = frozenset({"created", "loading"})
_STOPPED_STATUSES = frozenset({"exited", "stopped"})
_UNREACHABLE_STATUSES = frozenset({"offline", "unknown"})

_LAYER_MESSAGES: dict[str, str] = {
    "watchdog": "watchdog not running or without curl",
    "destroy_key": "destroy key missing",
    "clock_file": "clock file out of sync",
}

_L = "{L}"
_T = "{TTL}"
_FIXES: dict[str, list[str]] = {
    "expiring_soon": ["vasty", "extend", _L, "--by", _T],
    "expiring_with_running_job": ["vasty", "extend", _L, "--by", _T],
    "box_unreachable": ["vasty", "status", _L],
    "guard_partial": ["vasty", "release", _L],
    "clock_skew": ["vasty", "release", _L],
    "clock_skew_unknown": ["vasty", "release", _L],
    "sweep_not_spawned": ["vasty", "sweep", "--follow", _L],
    "orphan": ["vasty", "tag", _L, "--ttl", "30m"],
    "startup_failed": ["vasty", "ssh", _L, "--", "cat", "/workspace/.vasty/startup.log"],
    "expired_with_running_jobs": ["vasty", "status", _L],
    "flag_mismatch": ["vasty", "status", _L],
    "idle_box_available": ["vasty", "status", _L],
    "label_unreadable": ["vasty", "release", _L],
    "spend_unavailable": ["vasty", "status"],
    "clock_unverified": ["vasty", "status"],
    "cache_rebuilt": ["vasty", "status"],
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
    """Map the provider status and the probe to a vasty state.

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
    """Keep a history state over a derived `pending` or `unreachable`."""
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


def fix_for(code: str, target: str | None, ttl: int | None = None) -> str:
    """Return the shell-quoted fix command for a warning code.

    Pass the lease's label `ttl` in seconds for the `expiring_*` codes.
    """
    template = _FIXES.get(code)
    if template is None:
        raise ValueError(f"unknown warning code {code!r}")
    if _L in template and target is None:
        raise ValueError(f"warning {code!r} needs a lease")
    if _T in template and ttl is None:
        raise ValueError(f"warning {code!r} needs a ttl")
    fill = {_L: target, _T: format_duration_exact(ttl) if ttl is not None else None}
    return shlex.join(fill.get(part) or part for part in template)


def make_warning(code: str, lease: str | None, message: str, ttl: int | None = None) -> WarningItem:
    """Build a warning whose fix comes from the shared table. Pass `lease` None for account warnings."""
    return WarningItem(code=code, lease=lease, message=message, fix=fix_for(code, lease, ttl))


def live_jobs(lease: CachedLease) -> list[str]:
    """Return the ids of cached jobs in `running` or `serving` state."""
    return [job.id for job in lease.jobs if job.state in LIVE_JOB_STATES]


def busy(lease: CachedLease) -> bool | None:
    """Return whether a tracked job is live on a running box, else None.

    A job in `running`, `serving` or `unknown` state counts as live. The
    answer covers jobs vasty started.
    """
    if lease.state != "running":
        return None
    return any(job.state in LIVE_JOB_STATES or job.state == "unknown" for job in lease.jobs)


def gpu_matches(wanted: str, actual: str | None) -> bool:
    """Return True when `actual` is one of the GPU names `wanted` selects."""
    from vasty.provider import gpu_name_filter

    if actual is None:
        return False
    rule = gpu_name_filter(wanted)
    names = [rule["eq"]] if "eq" in rule else list(rule.get("in", []))
    return actual.lower() in {str(n).lower() for n in names}


def hardware_mismatch(
    lease: CachedLease, inst: Instance | None, settings: Settings, ports: list[int] | None
) -> list[str]:
    """Return the settings keys the lease fails to meet.

    Keys come back in the order `gpu`, `vram`, `gpus`, `max_price`, `image`,
    `cuda`, `ports`. `image` is checked when the lease records one. `cuda`
    reads `cuda_max_good` from the instance row `inst` when the settings
    carry a floor. An unknown `vram_gb` or `cuda_max_good`, from an absent
    row or value, skips its clause. `ports` is checked when the caller
    passes them.
    """
    out: list[str] = []
    if settings.gpu and not gpu_matches(settings.gpu, lease.gpu):
        out.append("gpu")
    if settings.vram is not None and lease.vram_gb is not None and lease.vram_gb < settings.vram:
        out.append("vram")
    if settings.gpus != lease.gpus:
        out.append("gpus")
    if lease.price_per_hr > settings.max_price:
        out.append("max_price")
    if lease.image is not None and settings.image != lease.image:
        out.append("image")
    if settings.cuda is not None:
        cuda = inst.cuda_max_good if inst is not None else None
        if cuda is not None and cuda < settings.cuda:
            out.append("cuda")
    if ports is not None and any(p not in lease.ports for p in ports):
        out.append("ports")
    return out


def reuse_candidates(
    snap: Snapshot, settings: Settings, ttl: int, now: int, ports: list[int] | None
) -> list[tuple[CachedLease, int]]:
    """Return up to three idle leases that fit the settings, each with its TTL shortfall.

    A candidate belongs to `settings.owner`, is `running` and reached, has no
    destroy pending, a startup hook that exited 0, no live tracked job, no
    `hardware_mismatch` and time left. The shortfall is the seconds the lease
    falls short of `ttl`, 0 when it outlasts it. Leases with no shortfall
    come first, then most time left first.
    """
    found: list[tuple[CachedLease, int, int]] = []
    for lease in snap.active():
        if lease.label.owner != settings.owner or lease.state != "running":
            continue
        if lease.reachable_at is None or lease.destroy_pending or lease.startup_exit != 0:
            continue
        if busy(lease) or hardware_mismatch(lease, snap.instance(lease.instance_id), settings, ports):
            continue
        remaining = ttl_remaining(lease.label, now)
        if remaining > 0:
            found.append((lease, max(0, ttl - remaining), remaining))
    found.sort(key=lambda item: (item[1] > 0, -item[2]))
    return [(lease, shortfall) for lease, shortfall, _ in found[:3]]


def startup_failed(lease: CachedLease) -> bool:
    """Return True when the hook exited non-zero or a restart cut it off."""
    if lease.startup_exit is not None and lease.startup_exit != 0:
        return True
    return lease.startup_exit is None and lease.startup_interrupted


def lease_warnings(lease: CachedLease, now: int, warn_before_expiry: int) -> list[WarningItem]:
    """Return the per-lease warnings with their fixes.

    Codes: `expiring_soon` or `expiring_with_running_job`, `box_unreachable`,
    `guard_partial`, `clock_skew`, `clock_skew_unknown`, `startup_failed` on
    active leases, and `expired_with_running_jobs` on an `expired` lease.
    `guard_partial` needs observed layers: a probe answered (`reachable_at`),
    another machine's probe wrote `miss=` to the label, or `tag` adopted the
    box without a guard. `clock_skew` fires when the last probe measured the
    box clock more than `CLOCK_SKEW_WARN_S` from the provider clock;
    `clock_skew_unknown` when the last probe returned no box time.
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
        left = f"{format_minutes_up(remaining)} left"
        ttl = lease.label.ttl
        if jobs:
            message = f"{left}, {', '.join(jobs)} running"
            out.append(make_warning("expiring_with_running_job", target, message, ttl))
        else:
            out.append(make_warning("expiring_soon", target, left, ttl))
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
    if lease.clock_skew is not None and abs(lease.clock_skew) > CLOCK_SKEW_WARN_S:
        sign = "ahead of" if lease.clock_skew > 0 else "behind"
        message = f"box clock {format_duration(abs(lease.clock_skew))} {sign} the provider"
        out.append(make_warning("clock_skew", target, message))
    if lease.clock_skew_unknown:
        out.append(make_warning("clock_skew_unknown", target, "the probe read no box time"))
    if startup_failed(lease):
        if lease.startup_exit is not None:
            message = f"startup exited {lease.startup_exit}"
        else:
            message = "startup cut off by a restart"
        out.append(make_warning("startup_failed", target, message))
    return out
