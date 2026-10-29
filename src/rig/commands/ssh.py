"""`rig ssh` (spec §4.9, §7).

`rig ssh LEASE` opens a shell on the terminal. `rig ssh LEASE -- COMMAND`
runs one command and passes its stdout, stderr and exit code through. Each
`-L SPEC` passes to ssh. Neither form writes JSON.
"""

from __future__ import annotations

import argparse

from rig import engine
from rig.cli import Outcome
from rig.commands._common import pick_lease, require_tools
from rig.context import Context


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    require_tools(ctx, "ssh")
    snap = engine.refresh(ctx)
    lease = pick_lease(ctx, snap, args.lease)
    target = engine.ssh_target(lease)
    ssh_args: list[str] = []
    for spec in args.forwards:
        ssh_args += ["-L", spec]
    command = args.command or None
    code = ctx.box.interactive(target, command, ssh_args)
    return Outcome(None, exit_code=code, emit=False)
