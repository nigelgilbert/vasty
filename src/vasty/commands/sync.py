"""`vasty sync`.

`push SRC DEST` and `pull SRC DEST` run rsync over the lease's SSH options
with the default excludes. `--delete` on push mirrors the local tree and
keeps the box's `/workspace/.vasty`. A relative remote path resolves under
`/workspace`, and rsync's trailing-slash rules apply. rsync output goes to
stderr.
"""

from __future__ import annotations

import argparse

from vasty import engine
from vasty.cli import Outcome
from vasty.commands._common import DEFAULT_EXCLUDES, lease_warnings, pick_lease, require_tools
from vasty.context import Context
from vasty.errors import VastyError
from vasty.models import SyncResult
from vasty.remote import check_remote_path


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    check_remote_path(args.dest if args.direction == "push" else args.src)
    require_tools(ctx, "ssh", "rsync")
    snap = engine.refresh(ctx)
    lease = pick_lease(ctx, snap, args.lease)
    target = engine.ssh_target(lease)
    push = args.direction == "push"
    delete = bool(getattr(args, "delete", False))
    code = ctx.box.rsync(target, push, args.src, args.dest, delete, list(DEFAULT_EXCLUDES))
    if code != 0:
        raise VastyError(
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
