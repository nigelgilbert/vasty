"""TARGET resolution for `extend`, `release`, `status` and `tag` (spec §4.0)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rig.models import CachedLease, Instance

if TYPE_CHECKING:
    from rig.context import Context
    from rig.engine import Snapshot


@dataclass
class Resolved:
    """Matched leases and orphans. `bulk` is True for selector targets."""

    leases: list[CachedLease]
    orphans: list[Instance]
    bulk: bool


def resolve_target(ctx: Context, snap: Snapshot, ns: argparse.Namespace, write: bool) -> Resolved:
    """Resolve a LEASE or selector. Writes default to the current owner; reads span owners."""
    raise NotImplementedError


def resolve_lease(ctx: Context, snap: Snapshot, ref: str) -> CachedLease | Instance:
    """Resolve one id or name under the current owner, or an orphan by `i-` id."""
    raise NotImplementedError
