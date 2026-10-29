"""`rig reserve`."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rig.cli import Outcome
from rig.context import Context
from rig.models import CachedLease, ReserveResult

if TYPE_CHECKING:
    from rig.engine import Snapshot


@dataclass
class Reserved:
    """A reserved or reused lease and its `reserve` output."""

    result: ReserveResult
    lease: CachedLease


def reserve_lease(
    ctx: Context, args: argparse.Namespace, snap: Snapshot, *, ttl: int, wait: bool
) -> Reserved:
    """Reserve a box from the creation flags in `args` and `ctx.settings`.

    Apply name idempotency, the budget check with `ttl`, offer search, create
    with recovery and the readiness wait. `run` and `serve` call this for
    auto-reserve. Raise `RigError` on failure; a box this call created and
    then gave up on is destroyed before the error propagates.
    """
    raise NotImplementedError


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    raise NotImplementedError
