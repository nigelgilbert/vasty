"""`rig sync`."""

from __future__ import annotations

import argparse

from rig.cli import Outcome
from rig.context import Context


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    raise NotImplementedError
