"""`vasty config`.

`show` returns `{values}`, each key mapped to `{value, source}`. `set` returns
`{key, value}` and writes the user config file. `profiles` returns
`{profiles}`, each name mapped to its merged fields.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from vasty.cli import Outcome
from vasty.config import SHOWN, Settings, set_value, toml_value, user_config_path
from vasty.context import Context
from vasty.timeutil import format_duration_exact

DURATION_KEYS = ("ttl", "run_ttl", "warn_before_expiry")


@dataclass
class ConfigValue:
    value: Any
    source: str


@dataclass
class ConfigShowResult:
    values: dict[str, ConfigValue]


@dataclass
class ConfigSetResult:
    key: str
    value: Any


@dataclass
class ConfigProfilesResult:
    profiles: dict[str, dict[str, Any]]


def show_values(settings: Settings) -> dict[str, ConfigValue]:
    """Return each effective value in config form with its source."""
    out: dict[str, ConfigValue] = {}
    for key in SHOWN:
        value: Any = getattr(settings, key)
        if key in DURATION_KEYS:
            value = format_duration_exact(value)
        elif key == "startup" and settings.startup_path is not None:
            value = settings.startup_path
        out[key] = ConfigValue(value, settings.sources.get(key, "default"))
    return out


def _human_value(key: str, value: Any, settings: Settings) -> str:
    if value is None:
        return "-"
    if key == "startup" and settings.startup_path is None:
        lines = len(str(value).splitlines())
        return f"<inline script, {lines} line{'s' if lines != 1 else ''}>"
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, list):
        return ",".join(str(v) for v in value) or "-"
    return str(value)


def _show(ctx: Context, args: argparse.Namespace) -> Outcome:
    if getattr(args, "owner", None) is not None:
        ctx.flags["owner"] = args.owner
    settings = ctx.settings
    values = show_values(settings)
    width = max(len(k) for k in values)
    rows = [(k, _human_value(k, v.value, settings), v.source) for k, v in values.items()]
    vwidth = max(len(r[1]) for r in rows)
    human = "\n".join(f"{k:<{width}}  {v:<{vwidth}}  {s}" for k, v, s in rows)
    return Outcome(ConfigShowResult(values), human=human)


def _set(ctx: Context, args: argparse.Namespace) -> Outcome:
    value = set_value(ctx.home, args.key, args.value)
    path = user_config_path(ctx.home)
    human = f"{args.key} = {toml_value(value)}  (written to {path})"
    return Outcome(ConfigSetResult(args.key, value), human=human)


def _profiles(ctx: Context, args: argparse.Namespace) -> Outcome:
    profiles = ctx.settings.profiles
    lines = []
    for name in sorted(profiles):
        fields = " ".join(f"{k}={toml_value(v)}" for k, v in profiles[name].items())
        lines.append(f"{name}  {fields}".rstrip())
    human = "\n".join(lines) if lines else "No profiles."
    return Outcome(ConfigProfilesResult(dict(profiles)), human=human)


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    if args.action == "set":
        return _set(ctx, args)
    if args.action == "profiles":
        return _profiles(ctx, args)
    return _show(ctx, args)
