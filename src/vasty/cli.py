"""Argument parsing, flag-combination checks and dispatch.

This module imports only the standard library and `vasty.errors` at load time.
Each verb lives in `vasty.commands.<verb>` and loads on dispatch. A command
module exposes `execute(ctx, args) -> Outcome`.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

from vasty.errors import VastyError, invalid

if TYPE_CHECKING:
    from vasty.context import Context

VERBS = (
    "reserve", "extend", "release", "status", "run", "serve", "stop",
    "sync", "ssh", "tag", "sweep", "config", "completion",
)

# Flags that set up a new lease; `--on` rejects them.
CREATION_FLAGS = (
    "name", "group", "owner", "profile", "ttl", "gpu", "vram", "cuda", "gpus", "disk",
    "image", "max_price", "region", "ports", "startup",
)

# Flags that feed config resolution as the `flag` layer.
SETTING_FLAGS = (
    "ttl", "gpu", "vram", "cuda", "gpus", "disk", "image", "max_price", "region", "ports",
    "startup",
)


@dataclass
class Outcome:
    """A command's result: the payload, its exit code and optional human text."""

    payload: Any
    exit_code: int = 0
    human: str | None = None
    emit: bool = True


# Replacements for removed flags, shown in the hint when argparse rejects one.
REMOVED_FLAGS = {
    "--no-wait": "drop it",
    "--plain": "drop it",
    "--cached": "drop it",
    "--yes": "drop it",
    "--everyone": "use plain vasty status",
    "--until": "use --by D to add D to the clock, or --to D to end it D from now",
    "--all": 'use --owner "$VASTY_OWNER"',
}


def removed_flag_hint(message: str) -> str | None:
    """Return the hint for removed flags named in an `unrecognized arguments:` message."""
    prefix = "unrecognized arguments:"
    if not message.startswith(prefix):
        return None
    flags = [token.split("=", 1)[0] for token in message[len(prefix):].split()]
    hits = [f"{flag} was removed: {REMOVED_FLAGS[flag]}." for flag in flags
            if flag in REMOVED_FLAGS]
    return " ".join(hits) or None


class Parser(argparse.ArgumentParser):
    """Raise `invalid_arguments` in place of printing usage and exiting."""

    def error(self, message: str) -> NoReturn:
        raise invalid(message, removed_flag_hint(message) or f"Run {self.prog} --help.")


class _Version(argparse.Action):
    """Print the installed package version from its metadata and exit 0."""

    def __init__(self, option_strings: list[str], dest: str, help: str | None = None) -> None:
        super().__init__(option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS,
                         nargs=0, help=help)

    def __call__(self, parser: argparse.ArgumentParser, namespace: argparse.Namespace,
                 values: Any, option_string: str | None = None) -> None:
        from importlib.metadata import version

        print(f"vasty {version('vasty')}")
        parser.exit()


def _output_flags() -> Parser:
    parent = Parser(add_help=False)
    parent.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="print JSON; default when stdout is not a terminal")
    parent.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS,
                        help="include extra fields in the output")
    return parent


def _setting_help() -> dict[str, str]:
    """Return help lines for the setting flags, with defaults read from `config.BUILTIN`.

    Config files, profiles and `VASTY_*` variables can replace a builtin
    default, so each line with a config key points at `vasty config show`.
    """
    from vasty.config import BUILTIN
    from vasty.timeutil import format_duration_exact

    see = "; see vasty config show"
    return {
        "owner": "owner label for a new lease; default: VASTY_OWNER, config, then $USER" + see,
        "ttl": "lease clock as a duration such as 45m or 2h; "
               f"builtin default: {format_duration_exact(BUILTIN['ttl'])}" + see,
        "profile": "config profile to apply; default: none",
        "startup": "script file that runs once on the box after setup, or - for stdin; "
                   "default: none" + see,
        "gpu": "GPU model name such as 4090 or A100, or any; default: any" + see,
        "vram": "minimum GPU memory in GB; default: any" + see,
        "cuda": "minimum CUDA version the host driver supports, such as 12.6; "
                "builtin default: the image's floor, 13 for the vllm image and 12.6 for the "
                "base image" + see,
        "gpus": f"number of GPUs; builtin default: {BUILTIN['gpus']}" + see,
        "disk": f"disk size in GB; builtin default: {BUILTIN['disk']}" + see,
        "image": f"Docker image; builtin default: {BUILTIN['image']}" + see,
        "max_price": "offer price cap in dollars per hour; "
                     f"builtin default: {BUILTIN['max_price']}" + see,
        "region": "region code or name such as US or Europe, or any; default: any" + see,
        "ports": "comma-separated ports to open such as 8000,8080; default: none" + see,
    }


def _target_flags(p: argparse.ArgumentParser, lease_optional: bool = True,
                  filters: bool = False) -> None:
    p.add_argument("target", nargs="?" if lease_optional else None, metavar="LEASE",
                   help="lease id or name")
    if filters:
        p.add_argument("--group", help="filter the account view to group G")
        p.add_argument("--owner", help="filter the account view to owner O")
    else:
        p.add_argument("--group", help="select the leases in group G")
        p.add_argument("--owner", help="select the leases of owner O")


def _hardware_flags(p: argparse.ArgumentParser, h: dict[str, str]) -> None:
    p.add_argument("--gpu", help=h["gpu"])
    p.add_argument("--vram", metavar="GB", help=h["vram"])
    p.add_argument("--cuda", metavar="FLOOR", help=h["cuda"])
    p.add_argument("--gpus", metavar="N", help=h["gpus"])
    p.add_argument("--disk", metavar="GB", help=h["disk"])
    p.add_argument("--image", help=h["image"])
    p.add_argument("--max-price", dest="max_price", metavar="USD_PER_HR", help=h["max_price"])
    p.add_argument("--region", help=h["region"])
    p.add_argument("--ports", metavar="N[,N...]", help=h["ports"])


def _reserve_flags(p: argparse.ArgumentParser, h: dict[str, str]) -> None:
    p.add_argument("--name", help="lease name, unique per owner; default: none")
    p.add_argument("--group", help="group label for the lease; default: none")
    p.add_argument("--owner", help=h["owner"])
    p.add_argument("--ttl", metavar="DURATION", help=h["ttl"])
    p.add_argument("--profile", help=h["profile"])
    p.add_argument("--startup", metavar="FILE|-", help=h["startup"])
    _hardware_flags(p, h)


def build_parser() -> Parser:
    out = _output_flags()
    root = Parser(prog="vasty", description="Leased GPU compute for agents.", parents=[out])
    root.add_argument("--version", action=_Version, help="print the vasty version and exit")
    sub = root.add_subparsers(dest="verb", parser_class=Parser, metavar="VERB")
    reserve_help = _setting_help()

    p = sub.add_parser("reserve", parents=[out], help="rent a box with a clock")
    _reserve_flags(p, reserve_help)

    p = sub.add_parser("extend", parents=[out], help="move a lease's clock")
    _target_flags(p)
    p.add_argument("--by", metavar="DURATION",
                   help="add a duration such as 30m to the clock; default: none")
    p.add_argument("--to", metavar="DURATION",
                   help="set the clock to a duration from now such as 2h; default: none")

    p = sub.add_parser("release", parents=[out], help="destroy a box now")
    _target_flags(p)

    p = sub.add_parser("status", parents=[out], help="show leases, spend and warnings")
    _target_flags(p, filters=True)

    p = sub.add_parser("run", parents=[out], help="run a command on a box",
                       usage="%(prog)s [options] -- COMMAND...")
    p.add_argument("--on", metavar="LEASE", help="run on this lease; default: reserve a new box")
    p.add_argument("--detach", action="store_true",
                   help="return once the job starts and leave the box up")
    p.add_argument("--sync", dest="sync_dir", metavar="DIR",
                   help="push DIR to the box before the command; default: none")
    _reserve_flags(p, reserve_help)

    p = sub.add_parser("serve", parents=[out], help="serve a model behind an OpenAI endpoint",
                       usage="%(prog)s [options] --model MODEL [-- VLLM_ARGS...]")
    p.add_argument("--on", metavar="LEASE",
                   help="serve on this lease; default: reserve a new box")
    p.add_argument("--model", required=True, help="model name or box path for vllm serve")
    p.add_argument("--bind-local", action="store_true", dest="bind_local",
                   help="bind vLLM to 127.0.0.1 for use through vasty ssh -L")
    _reserve_flags(p, reserve_help)

    p = sub.add_parser("stop", parents=[out], help="stop a job on a box")
    p.add_argument("lease", metavar="LEASE", help="lease id or name")
    p.add_argument("job", nargs="?", metavar="JOB", help="job id; required when several jobs run")

    p = sub.add_parser("sync", parents=[out], help="rsync files to or from a box",
                       usage="%(prog)s [options] LEASE push|pull [--delete] SRC DEST")
    p.add_argument("lease", metavar="LEASE", help="lease id or name")
    direction = p.add_subparsers(dest="direction", parser_class=Parser, required=True,
                                 metavar="push|pull SRC DEST")
    push = direction.add_parser("push", parents=[out],
                                help="copy local SRC to box DEST; --delete mirrors SRC")
    push.add_argument("--delete", action="store_true",
                      help="delete box files missing from SRC; keeps /workspace/.vasty")
    push.add_argument("src", metavar="SRC", help="local path")
    push.add_argument("dest", metavar="DEST",
                      help="box path; a relative path resolves under /workspace")
    pull = direction.add_parser("pull", parents=[out], help="copy box SRC to local DEST")
    pull.add_argument("src", metavar="SRC",
                      help="box path; a relative path resolves under /workspace")
    pull.add_argument("dest", metavar="DEST", help="local path")

    p = sub.add_parser("ssh", parents=[out], help="open a shell or run one command",
                       usage="%(prog)s [options] LEASE [-- COMMAND...]")
    p.add_argument("lease", metavar="LEASE",
                   help="lease id or name; add -- COMMAND to run one command")
    p.add_argument("-L", action="append", dest="forwards", default=[], metavar="SPEC",
                   help="forward a port as ssh -L SPEC; repeatable")

    p = sub.add_parser("tag", parents=[out], help="set labels or adopt an orphan")
    p.add_argument("target", metavar="LEASE", help="lease id or name, or an orphan's i- id")
    p.add_argument("--name", metavar="NAME", help="set the lease name; empty clears it")
    p.add_argument("--group", metavar="G", help="set the group label; empty clears it")
    p.add_argument("--owner", metavar="O", help="set the owner label")
    p.add_argument("--ttl", metavar="DURATION",
                   help="clock for an adopted orphan as a duration such as 30m; default: none")

    p = sub.add_parser("sweep", parents=[out], help="destroy boxes past their clock")
    p.add_argument("--follow", metavar="LEASE",
                   help="sleep to the lease's expiry and sweep until it is gone")

    p = sub.add_parser("config", parents=[out], help="show or change configuration")
    action = p.add_subparsers(dest="action", parser_class=Parser, required=True)
    show = action.add_parser("show", parents=[out], help="print the effective settings")
    show.add_argument("--profile", help=reserve_help["profile"])
    cset = action.add_parser("set", parents=[out], help="write one key to the user config")
    cset.add_argument("key", metavar="KEY", help="dotted key such as defaults.ttl or owner")
    cset.add_argument("value", metavar="VALUE", help="value in the key's unit, such as 45m")
    action.add_parser("profiles", parents=[out], help="list the configured profiles")

    p = sub.add_parser("completion", parents=[out], help="print a shell completion script")
    p.add_argument("shell", nargs="?", choices=["bash", "zsh", "fish"], help="target shell")
    p.add_argument("--list", dest="list_kind", choices=["leases", "groups", "profiles"],
                   help=argparse.SUPPRESS)
    return root


def split_command(argv: Sequence[str]) -> tuple[list[str], list[str] | None]:
    """Split argv at the first `--` into vasty args and the remote command."""
    args = list(argv)
    if "--" in args:
        i = args.index("--")
        return args[:i], args[i + 1 :]
    return args, None


def parse(argv: Sequence[str]) -> argparse.Namespace:
    head, command = split_command(argv)
    ns = build_parser().parse_args(head)
    if ns.verb is None:
        raise invalid("No verb given.", "Run vasty --help.")
    ns.command = command
    for flag in ("json", "verbose"):
        if not hasattr(ns, flag):
            setattr(ns, flag, False)
    check_combinations(ns)
    return ns


def check_combinations(ns: argparse.Namespace) -> None:
    """Apply the flag-combination rules."""
    verb = ns.verb
    if verb == "run" and not ns.command:
        raise invalid("run needs a command after --.", "vasty run -- COMMAND")
    if verb not in ("run", "serve", "ssh") and ns.command is not None:
        raise invalid(f"{verb} takes no command after --.", f"Run vasty {verb} --help.")
    if verb in ("run", "serve"):
        if ns.on is not None:
            given = [f for f in CREATION_FLAGS if getattr(ns, f, None) not in (None, False)]
            if given:
                flags = ", ".join("--" + f.replace("_", "-") for f in given)
                raise invalid(f"--on takes no creation flags: {flags}.", f"Drop {flags}.")


def setting_flags(ns: argparse.Namespace) -> dict[str, Any]:
    """Collect the flags that feed config resolution."""
    out: dict[str, Any] = {}
    for key in SETTING_FLAGS:
        value = getattr(ns, key, None)
        if value is not None:
            out[key] = value
    owner = getattr(ns, "owner", None)
    on_new_box = ns.verb == "reserve" or (
        ns.verb in ("run", "serve") and getattr(ns, "on", None) is None
    )
    if on_new_box and owner is not None:
        out["owner"] = owner
    return out


def build_context(ns: argparse.Namespace) -> Context:
    from vasty.context import Context

    ctx = Context()
    ctx.stdout_tty = sys.stdout.isatty()
    configure(ctx, ns)
    return ctx


def configure(ctx: Context, ns: argparse.Namespace) -> None:
    """Fill the parsed flags and output mode into a context."""
    ctx.flags = setting_flags(ns)
    ctx.profile = getattr(ns, "profile", None)
    ctx.mode = "json" if ns.json or not ctx.stdout_tty else "human"


def emit(ctx: Context, outcome: Outcome) -> None:
    from vasty.output import dumps, generic_human

    if not outcome.emit:
        return
    if ctx.mode == "json":
        print(dumps(outcome.payload), file=ctx.stdout)
    else:
        print(outcome.human if outcome.human is not None else generic_human(outcome.payload),
              file=ctx.stdout)


def emit_error(ctx_mode: str, stdout: Any, stderr: Any, err: VastyError) -> None:
    if ctx_mode == "json":
        print(json.dumps(err.to_dict(), indent=2), file=stdout)
    else:
        print(f"error: {err.code}: {err.message}", file=stderr)
        print(f"hint: {err.hint}", file=stderr)


def _report_swept(ctx: Context) -> None:
    """Write one `vasty: ` line to stderr for each entry the command's refreshes swept."""
    from vasty.commands._common import merge_swept
    from vasty.commands.status import swept_lines

    with contextlib.suppress(Exception):
        for line in swept_lines(merge_swept(ctx.swept)):
            print(f"vasty: {line}", file=ctx.stderr)


def _guess_mode(argv: Sequence[str], tty: bool) -> str:
    head, _ = split_command(argv)
    return "json" if "--json" in head or not tty else "human"


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
        module = importlib.import_module(f"vasty.commands.{ns.verb}")
        outcome: Outcome = module.execute(ctx, ns)
        emit(ctx, outcome)
        return outcome.exit_code
    except VastyError as err:
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
