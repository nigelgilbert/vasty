"""`rig sync` (spec §4.8).

`push SRC DEST` and `pull SRC DEST` run rsync over the lease's SSH options
with the default excludes. `--delete` on push mirrors the local tree. A
relative remote path resolves under `/workspace`, and rsync's trailing-slash
rules apply. rsync output goes to stderr.
"""

from __future__ import annotations

import argparse

from rig import engine
from rig.cli import Outcome
from rig.commands._common import DEFAULT_EXCLUDES, lease_warnings, pick_lease, require_tools
from rig.context import Context
from rig.errors import RigError
from rig.models import SyncResult


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    require_tools(ctx, "ssh", "rsync")
    snap = engine.refresh(ctx)
    lease = pick_lease(ctx, snap, args.lease)
    target = engine.ssh_target(lease)
    push = args.direction == "push"
    delete = bool(getattr(args, "delete", False))
    code = ctx.box.rsync(target, push, args.src, args.dest, delete, list(DEFAULT_EXCLUDES))
    if code != 0:
        raise RigError(
            "sync_failed",
            f"rsync {args.direction} {args.src} {args.dest} exited {code}.",
            "Check the rsync output on stderr, then retry.",
            details={"exit": code},
        )
    result = SyncResult(
        lease=lease.lease,
        direction="push" if push else "pull",
        src=args.src,
        dest=args.dest,
        warnings=lease_warnings(ctx, snap, lease, ctx.clock.now()),
        swept=list(snap.swept),
    )
    if push:
        arrow = f"{args.src} -> {lease.lease}:{args.dest}"
    else:
        arrow = f"{lease.lease}:{args.src} -> {args.dest}"
    return Outcome(result, human=f"{result.direction} {arrow} done")
