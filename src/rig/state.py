"""Lease state, guard and per-lease warnings (spec §3, §3.1, §4.4)."""

from __future__ import annotations

from rig.models import CachedLease, Label, LeaseState, ProbeResult, WarningItem


def effective_expiry(label: Label) -> int:
    """Return `expires`, else `created + ttl`."""
    raise NotImplementedError


def derive_state(actual_status: str | None, probe: ProbeResult | None, reachable_before: bool) -> LeaseState:
    """Map the provider status and the probe to a rig state (spec §3.1 table)."""
    raise NotImplementedError


def guard(lease: CachedLease) -> tuple[str, list[str]]:
    """Return `full` or `partial` and the missing layers."""
    raise NotImplementedError


def lease_warnings(lease: CachedLease, now: int, warn_before_expiry: int) -> list[WarningItem]:
    """Return the per-lease warnings with their fixes."""
    raise NotImplementedError
