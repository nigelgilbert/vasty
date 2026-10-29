"""The networked-command prelude: list, sweep, reconcile and probe (spec §6, §8.1).

Every networked command calls `refresh` before it resolves its target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rig.models import CachedLease, Instance, SweptEntry, WarningItem

if TYPE_CHECKING:
    from rig.context import Context
    from rig.remote import SshTarget


@dataclass
class Snapshot:
    """The account after one refresh."""

    now: int
    instances: list[Instance]
    leases: dict[str, CachedLease]
    orphans: list[Instance]
    unreadable: list[Instance]
    swept: list[SweptEntry] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)

    def active(self) -> list[CachedLease]:
        """Return leases outside history."""
        raise NotImplementedError


def refresh(ctx: Context, probe: bool = True) -> Snapshot:
    """List instances, sweep expired leases, reconcile the cache, probe running boxes and save."""
    raise NotImplementedError


def ssh_target(lease: CachedLease) -> SshTarget:
    """Return the SSH endpoint for a lease. Raise `lease_pending` when it has none."""
    raise NotImplementedError
