"""Argument parsing, flag-combination checks and dispatch (spec §4, §7).

This module imports only the standard library and `rig.errors` at load time.
Each verb lives in `rig.commands.<verb>` and loads on dispatch. A command
module exposes `execute(ctx, args) -> Outcome`.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, NoReturn, Sequence

from rig.errors import RigError, invalid

if TYPE_CHECKING:
    from rig.context import Context

VERBS = (
    "reserve", "extend", "release", "status", "run", "serve",
    "sync", "ssh", "tag", "config", "completion",
)

# Flags that set up a new lease; `--on` rejects them.
CREATION_FLAGS = (
    "name", "group", "owner", "profile", "ttl", "gpu", "vram", "gpus", "disk",
    "image", "max_price", "region", "ports", "startup", "no_wait",
)

# Flags that feed config resolution as the `flag` layer.
SETTING_FLAGS = (
    "ttl", "gpu", "vram", "gpus", "disk", "image", "max_price", "region", "ports", "startup",
)


@dataclass
class Outcome:
    """A command's result: the payload, its exit code and optional human text."""

    payload: Any
    exit_code: int = 0
    human: str | None = None
    emit: bool = True


class Parser(argparse.ArgumentParser):
    """Raise `invalid_arguments` in place of printing usage and exiting."""

    def error(self, message: str) -> NoReturn:
        raise invalid(message, f"Run {self.prog} --help.")


def _output_flags() -> Parser:
    parent = Parser(add_help=False)
    parent.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    parent.add_argument("--plain", action="store_true", default=argparse.SUPPRESS)
    parent.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS)
    return parent


def _target_flags(p: argparse.ArgumentParser, lease_optional: bool = True) -> None:
    p.add_argument("target", nargs="?" if lease_optional else None, metavar="LEASE")
    p.add_argument("--group")
    p.add_argument("--owner")
    p.add_argument("--all", action="store_true")
    p.add_argument("--everyone", action="store_true")


def _reserve_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--name")
    p.add_argument("--group")
    p.add_argument("--owner")
    p.add_argument("--ttl")
    p.add_argument("--profile")
    p.add_argument("--startup", metavar="FILE|-")
    p.add_argument("--no-wait", action="store_true", dest="no_wait")
    p.add_argument("--config", dest="config_stdin", metavar="-")
    p.add_argument("--gpu")
    p.add_argument("--vram")
    p.add_argument("--gpus")
    p.add_argument("--disk")
    p.add_argument("--image")
    p.add_argument("--max-price", dest="max_price")
    p.add_argument("--region")
    p.add_argument("--ports")


def build_parser() -> Parser:
    out = _output_flags()
    root = Parser(prog="rig", description="Leased GPU compute for agents.", parents=[out])
    sub = root.add_subparsers(dest="verb", parser_class=Parser, metavar="VERB")

    p = sub.add_parser("reserve", parents=[out], help="rent a box with a clock")
    _reserve_flags(p)

    p = sub.add_parser("extend", parents=[out], help="move a lease's clock")
    _target_flags(p)
    p.add_argument("--by")
    p.add_argument("--to")
    p.add_argument("--until")

    p = sub.add_parser("release", parents=[out], help="destroy a box now")
    _target_flags(p)
    p.add_argument("--yes", action="store_true")

    p = sub.add_parser("status", parents=[out], help="show leases, spend and warnings")
    _target_flags(p)
    p.add_argument("--cached", action="store_true")

    p = sub.add_parser("run", parents=[out], help="run a command on a box")
    p.add_argument("--on")
    p.add_argument("--detach", action="store_true")
    p.add_argument("--sync", dest="sync_dir", metavar="DIR")
    _reserve_flags(p)

    p = sub.add_parser("serve", parents=[out], help="serve a model behind an OpenAI endpoint")
    p.add_argument("--on")
    p.add_argument("--model", required=True)
    p.add_argument("--quant")
    p.add_argument("--bind-local", action="store_true", dest="bind_local")
    _reserve_flags(p)

    p = sub.add_parser("sync", parents=[out], help="rsync files to or from a box")
    p.add_argument("lease", metavar="LEASE")
    direction = p.add_subparsers(dest="direction", parser_class=Parser, required=True)
    push = direction.add_parser("push", parents=[out])
    push.add_argument("--delete", action="store_true")
    push.add_argument("src")
    push.add_argument("dest")
    pull = direction.add_parser("pull", parents=[out])
    pull.add_argument("src")
    pull.add_argument("dest")

    p = sub.add_parser("ssh", parents=[out], help="open a shell or run one command")
    p.add_argument("lease", metavar="LEASE")
    p.add_argument("-L", action="append", dest="forwards", default=[], metavar="SPEC")

    p = sub.add_parser("tag", parents=[out], help="set labels or adopt an orphan")
    _target_flags(p)
    p.add_argument("--set-name", dest="set_name")
    p.add_argument("--set-group", dest="set_group")
    p.add_argument("--set-owner", dest="set_owner")
    p.add_argument("--ttl")

    p = sub.add_parser("config", parents=[out], help="show or change configuration")
    action = p.add_subparsers(dest="action", parser_class=Parser, required=True)
    show = action.add_parser("show", parents=[out])
    show.add_argument("--profile")
    show.add_argument("--config", dest="config_stdin", metavar="-")
    show.add_argument("--owner")
    show.add_argument("--ttl")
    show.add_argument("--startup", metavar="FILE|-")
    show.add_argument("--gpu")
    show.add_argument("--vram")
    show.add_argument("--gpus")
    show.add_argument("--disk")
    show.add_argument("--image")
    show.add_argument("--max-price", dest="max_price")
    show.add_argument("--region")
    show.add_argument("--ports")
    cset = action.add_parser("set", parents=[out])
    cset.add_argument("key")
    cset.add_argument("value")
    action.add_parser("profiles", parents=[out])

    p = sub.add_parser("completion", parents=[out], help="print a shell completion script")
    p.add_argument("shell", nargs="?", choices=["bash", "zsh", "fish"])
    p.add_argument("--list", dest="list_kind", choices=["leases", "groups", "profiles"],
                   help=argparse.SUPPRESS)
    return root


def split_command(argv: Sequence[str]) -> tuple[list[str], list[str] | None]:
    """Split argv at the first `--` into rig args and the remote command."""
    args = list(argv)
    if "--" in args:
        i = args.index("--")
        return args[:i], args[i + 1 :]
    return args, None


def parse(argv: Sequence[str]) -> argparse.Namespace:
    head, command = split_command(argv)
    ns = build_parser().parse_args(head)
    if ns.verb is None:
        raise invalid("No verb given.", "Run rig --help.")
    ns.command = command
    for flag in ("json", "plain", "verbose"):
        if not hasattr(ns, flag):
            setattr(ns, flag, False)
    check_combinations(ns)
    return ns


def check_combinations(ns: argparse.Namespace) -> None:
    """Apply the flag-combination rules from spec §4 and §4.0."""
    if ns.json and ns.plain:
        raise invalid("--json and --plain conflict.", "Pass one of --json or --plain.")
    verb = ns.verb
    if verb == "run" and not ns.command:
        raise invalid("run needs a command after --.", "rig run -- COMMAND")
    if verb not in ("run", "ssh") and ns.command is not None:
        raise invalid(f"{verb} takes no command after --.", f"Run rig {verb} --help.")
    config_stdin = getattr(ns, "config_stdin", None)
    if config_stdin is not None and config_stdin != "-":
        raise invalid("--config takes only '-'.", "Pass --config - and JSON on stdin.")
    if config_stdin == "-" and getattr(ns, "startup", None) == "-":
        raise invalid("--config - and --startup - both read stdin.", "Pass --startup FILE.")
    if verb in ("run", "serve"):
        if ns.on is not None:
            given = [f for f in CREATION_FLAGS if getattr(ns, f, None) not in (None, False)]
            if config_stdin is not None:
                given.append("config")
            if given:
                flags = ", ".join("--" + f.replace("_", "-") for f in given)
                raise invalid(f"--on takes no creation flags: {flags}.", f"Drop {flags}.")
        elif ns.no_wait:
            raise invalid(f"{verb} without --on waits for the box.", "Drop --no-wait.")
    if hasattr(ns, "everyone"):
        _check_target(ns)


def _check_target(ns: argparse.Namespace) -> None:
    if ns.target is not None and (ns.group or ns.owner or ns.all or ns.everyone):
        raise invalid("A LEASE takes no selector.", "Pass a LEASE or a selector.")
    if ns.all and (ns.group or ns.owner):
        raise invalid("--all takes no --group or --owner.", "Pass --all or a selector.")
    if ns.everyone and ns.owner:
        raise invalid("--everyone takes no --owner.", "Drop --owner or --everyone.")
    if ns.everyone and not (ns.all or ns.group):
        raise invalid("--everyone needs --all or --group.", "rig status --all --everyone")


def setting_flags(ns: argparse.Namespace) -> dict[str, Any]:
    """Collect the flags that feed config resolution."""
    out: dict[str, Any] = {}
    for key in SETTING_FLAGS:
        value = getattr(ns, key, None)
        if value is not None:
            out[key] = value
    owner = getattr(ns, "owner", None)
    if ns.verb == "reserve" or (ns.verb in ("run", "serve") and getattr(ns, "on", None) is None):
        if owner is not None:
            out["owner"] = owner
    return out


def build_context(ns: argparse.Namespace) -> Context:
    from rig.context import Context

    ctx = Context()
    ctx.stdout_tty = sys.stdout.isatty()
    ctx.stdin_tty = sys.stdin.isatty()
    configure(ctx, ns)
    return ctx


def configure(ctx: Context, ns: argparse.Namespace) -> None:
    """Fill the parsed flags, output mode and stdin JSON into a context."""
    ctx.flags = setting_flags(ns)
    ctx.profile = getattr(ns, "profile", None)
    if ns.json:
        ctx.mode = "json"
    elif ns.plain:
        ctx.mode = "human"
    else:
        ctx.mode = "human" if ctx.stdout_tty else "json"
    if getattr(ns, "config_stdin", None) == "-":
        try:
            data = json.loads(ctx.stdin.read())
        except json.JSONDecodeError as exc:
            raise invalid(f"--config - read invalid JSON: {exc}.", "Pass a JSON object on stdin.")
        if not isinstance(data, dict):
            raise invalid("--config - needs a JSON object.", "Pass a JSON object on stdin.")
        ctx.stdin_json = data


def emit(ctx: Context, outcome: Outcome) -> None:
    from rig.output import dumps, generic_human

    if not outcome.emit:
        return
    if ctx.mode == "json":
        print(dumps(outcome.payload), file=ctx.stdout)
    else:
        print(outcome.human if outcome.human is not None else generic_human(outcome.payload),
              file=ctx.stdout)


def emit_error(ctx_mode: str, stdout: Any, stderr: Any, err: RigError) -> None:
    if ctx_mode == "json":
        print(json.dumps(err.to_dict(), indent=2), file=stdout)
    else:
        print(f"error: {err.code}: {err.message}", file=stderr)
        print(f"hint: {err.hint}", file=stderr)


def _report_swept(ctx: Context) -> None:
    """Write one `rig: ` line to stderr for each entry the command's refreshes swept."""
    from rig.commands._common import merge_swept
    from rig.commands.status import swept_lines

    for line in swept_lines(merge_swept(ctx.swept)):
        print(f"rig: {line}", file=ctx.stderr)


def _guess_mode(argv: Sequence[str], tty: bool) -> str:
    head, _ = split_command(argv)
    if "--json" in head:
        return "json"
    if "--plain" in head:
        return "human"
    return "human" if tty else "json"


def run(
    argv: Sequence[str],
    make_context: Callable[[argparse.Namespace], Context],
    stdout: Any = None,
    stderr: Any = None,
) -> int:
    """Parse, dispatch and render. Return the exit code.

    `stdout` and `stderr` receive errors raised before a context exists.
    """
    ctx: Context | None = None
    try:
        ns = parse(argv)
        ctx = make_context(ns)
        module = importlib.import_module(f"rig.commands.{ns.verb}")
        outcome: Outcome = module.execute(ctx, ns)
        emit(ctx, outcome)
        return outcome.exit_code
    except RigError as err:
        if ctx is not None:
            _report_swept(ctx)
            emit_error(ctx.mode, ctx.stdout, ctx.stderr, err)
        else:
            out = stdout if stdout is not None else sys.stdout
            errs = stderr if stderr is not None else sys.stderr
            emit_error(_guess_mode(argv, out.isatty()), out, errs, err)
        return err.exit_code
    except BaseException:
        if ctx is not None:
            _report_swept(ctx)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        build_parser().print_help()
        return 0
    return run(args, build_context)
