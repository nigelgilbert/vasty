"""Configuration resolution.

Layers, highest first: flags, `--config -` JSON, `--profile`, environment,
project file, user file, built-in defaults. `resolve` returns the effective
`Settings` and the source of each value.

Bad flag values raise `invalid_arguments`. Bad file, environment or stdin
values raise `invalid_config`. An unknown `--profile` name raises
`invalid_arguments`. `startup` and `startup_file` are two spellings of one
setting: the highest layer that sets either wins, and one table setting both
raises `invalid_config`.

This module imports only the standard library, `vasty.errors`, `vasty.ids` and `vasty.timeutil`.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping

from vasty import timeutil
from vasty.errors import VastyError
from vasty.ids import VALUE

# Value kinds for every key a config table accepts.
DEFAULT_KEYS: dict[str, str] = {
    "ttl": "duration",
    "run_ttl": "duration",
    "max_price": "money",
    "daily_budget": "money",
    "warn_before_expiry": "duration",
    "image": "str",
    "disk": "int",
    "gpus": "int",
    "gpu": "str",
    "vram": "number",
    "region": "str",
    "ports": "ports",
    "startup": "text",
    "startup_file": "path",
}
PROFILE_KEYS: dict[str, str] = {k: v for k, v in DEFAULT_KEYS.items() if k != "daily_budget"}
TOP_KEYS: dict[str, str] = {"api_key_env": "str", "owner": "owner", "ssh_key": "path"}
MODEL_KEYS: dict[str, str] = {"vram": "number", "quant": "str", "image": "str", "gpu": "str"}
# Model-entry keys `serve` applies as reservation settings.
MODEL_LAYER_KEYS: dict[str, str] = {k: MODEL_KEYS[k] for k in ("vram", "gpu", "image")}
TABLE_KEYS = ("defaults", "profiles", "models")
FLAG_KEYS: dict[str, str] = {**PROFILE_KEYS, "owner": "owner"}

# Keys `config show` reports, in display order.
SHOWN = (
    "owner", "api_key_env", "ssh_key", "ttl", "run_ttl", "max_price", "daily_budget",
    "warn_before_expiry", "disk", "gpus", "image", "gpu", "vram", "region", "ports", "startup",
)

BUILTIN: dict[str, Any] = {
    "api_key_env": "VAST_API_KEY",
    "ttl": 30 * 60,
    "run_ttl": 2 * 3600,
    "max_price": Decimal("0.60"),
    "daily_budget": Decimal("10.00"),
    "warn_before_expiry": 5 * 60,
    "disk": 50,
    "gpus": 1,
    "image": "vasty/base:cuda12.4",
}
BUILTIN_MODELS: dict[str, dict[str, Any]] = {
    "Qwen/Qwen3-72B-Instruct": {
        "vram": 80.0, "quant": "awq", "image": "vllm/vllm-openai:v0.6.3",
    },
}

_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True)
class ModelEntry:
    """One `[models."NAME"]` table."""

    vram: float | None = None
    quant: str | None = None
    image: str | None = None
    gpu: str | None = None


@dataclass
class Settings:
    """Effective values for one invocation. Durations are seconds."""

    owner: str
    api_key_env: str
    ssh_key: str | None
    ttl: int
    run_ttl: int
    max_price: Decimal
    daily_budget: Decimal
    warn_before_expiry: int
    disk: int
    gpus: int
    image: str
    gpu: str | None = None
    vram: float | None = None
    region: str | None = None
    ports: list[int] = field(default_factory=list)
    startup: str | None = None
    startup_path: str | None = None
    models: dict[str, ModelEntry] = field(default_factory=dict)
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StartupSpec:
    """Where the startup script comes from: inline text, a file, or stdin."""

    kind: str
    text: str | None = None
    path: Path | None = None


@dataclass(frozen=True)
class _Origin:
    """One layer's identity, used for error codes, messages and relative paths."""

    source: str
    where: str
    base: Path
    code: str = "invalid_config"
    text: bool = False

    def name(self, key: str) -> str:
        if self.source == "flag":
            return "--" + key.replace("_", "-")
        if self.source == "env":
            return "VASTY_" + key.upper()
        return f"{key} in {self.where}"

    def fail(self, key: str, problem: str) -> VastyError:
        if self.code == "invalid_arguments":
            hint = f"Fix {self.name(key)}."
        elif self.source == "env":
            hint = f"Fix or unset {self.name(key)}."
        else:
            hint = f"Fix {key} in {self.where}."
        return VastyError(self.code, f"{self.name(key)} {problem}.", hint)


def parse_duration(text: str) -> int | None:
    """Return seconds for `30m`, `1h30m` or `2d`, or None when the text is no duration.

    The grammar is `timeutil.parse_duration`'s, so config values and flags agree.
    """
    try:
        return timeutil.parse_duration(text)
    except VastyError:
        return None


def format_duration(seconds: int) -> str:
    """Format seconds as `1h30m`, `2d` or `45s`."""
    if seconds <= 0:
        return "0s"
    parts = []
    for unit, size in timeutil.UNITS.items():
        count, seconds = divmod(seconds, size)
        if count:
            parts.append(f"{count}{unit}")
    return "".join(parts)


def _decimal(value: Any, text: bool) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value)) if math.isfinite(value) else None
    if text and isinstance(value, str):
        try:
            dec = Decimal(value.strip())
        except InvalidOperation:
            return None
        return dec if dec.is_finite() else None
    return None


def _number(value: Any, text: bool) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        out = float(value)
    elif text and isinstance(value, str):
        try:
            out = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return out if math.isfinite(out) else None


def _ports(value: Any, origin: _Origin, key: str) -> list[int]:
    items: list[Any]
    if isinstance(value, str):
        items = [p.strip() for p in value.split(",")] if value.strip() else []
    elif isinstance(value, list):
        items = value
    else:
        raise origin.fail(key, "takes a list of ports")
    out: list[int] = []
    for item in items:
        if isinstance(item, str) and item.isdigit():
            port = int(item)
        elif isinstance(item, int) and not isinstance(item, bool):
            port = item
        else:
            raise origin.fail(key, f"has a bad port {item!r}")
        if not 1 <= port <= 65535:
            raise origin.fail(key, f"has port {port} outside 1-65535")
        if port not in out:
            out.append(port)
    return out


def _path(value: str, base: Path, home: Path) -> Path:
    if value == "~" or value.startswith("~/"):
        return home / value[2:] if value != "~" else home
    path = Path(value)
    return path if path.is_absolute() else base / path


def _convert(kind: str, key: str, value: Any, origin: _Origin, home: Path) -> Any:
    """Check one value against its kind and return it in Settings form."""
    if kind == "duration":
        if isinstance(value, int) and not isinstance(value, bool) and origin.source == "flag":
            if value > 0:
                return value
        elif isinstance(value, str):
            seconds = parse_duration(value.strip())
            if seconds is not None:
                return seconds
        raise origin.fail(key, "takes a duration such as 30m or 1h30m")
    if kind == "money":
        dec = _decimal(value, origin.text)
        if dec is None or dec < 0 or (key.endswith("max_price") and dec == 0):
            raise origin.fail(key, "takes a positive dollar amount")
        return dec
    if kind == "int":
        number: int | None = None
        if isinstance(value, int) and not isinstance(value, bool):
            number = value
        elif origin.text and isinstance(value, str) and value.strip().isdigit():
            number = int(value.strip())
        if number is None or number < 1:
            raise origin.fail(key, "takes a positive integer")
        return number
    if kind == "number":
        num = _number(value, origin.text)
        if num is None or num <= 0:
            raise origin.fail(key, "takes a positive number")
        return num
    if kind == "ports":
        return _ports(value, origin, key)
    if not isinstance(value, str):
        raise origin.fail(key, "takes a string")
    if kind == "text":
        return value
    if not value.strip():
        raise origin.fail(key, "takes a non-empty string")
    if kind == "owner" and not VALUE.fullmatch(value):
        raise origin.fail(key, "takes 1-63 characters from A-Z, a-z, 0-9, '.', '_' and '-'")
    if kind == "path":
        return _path(value, origin.base, home)
    return value


def _convert_table(
    table: Mapping[str, Any],
    allowed: Mapping[str, str],
    origin: _Origin,
    prefix: str,
    home: Path,
) -> dict[str, Any]:
    """Check a table's keys and values. Fold `startup` and `startup_file` into one key."""
    if "startup" in table and "startup_file" in table:
        raise VastyError(
            "invalid_config",
            f"{origin.name(prefix + 'startup')} and {origin.name(prefix + 'startup_file')}"
            " are both set.",
            "Keep one of startup or startup_file.",
        )
    out: dict[str, Any] = {}
    for key, value in table.items():
        full = prefix + key
        kind = allowed.get(key)
        if kind is None:
            if key == "daily_budget":
                raise origin.fail(full, "has no profile, flag or stdin form; set it in [defaults]")
            raise origin.fail(full, "is not a known key")
        if key == "startup_file" and origin.source == "flag" and value == "-":
            out["startup"] = StartupSpec("stdin")
            continue
        converted = _convert(kind, full, value, origin, home)
        if key == "startup":
            out["startup"] = StartupSpec("text", text=converted)
        elif key == "startup_file":
            out["startup"] = StartupSpec("file", path=converted)
        else:
            out[key] = converted
    return out


def overlay(low: Mapping[str, Any], high: Mapping[str, Any]) -> dict[str, Any]:
    """Merge two tables by field. A high `startup` or `startup_file` drops both from low."""
    out = dict(low)
    if "startup" in high or "startup_file" in high:
        out.pop("startup", None)
        out.pop("startup_file", None)
    out.update(high)
    return out


@dataclass
class ConfigFile:
    """One parsed config file. `values` holds top-level and `[defaults]` keys."""

    path: Path
    values: dict[str, Any]
    profiles: dict[str, dict[str, Any]]
    raw_profiles: dict[str, dict[str, Any]]
    models: dict[str, dict[str, Any]]


def _subtables(doc: Mapping[str, Any], key: str, origin: _Origin) -> dict[str, dict[str, Any]]:
    tables = doc.get(key, {})
    if not isinstance(tables, dict):
        raise origin.fail(key, "is not a table")
    for name, table in tables.items():
        if not isinstance(table, dict):
            raise origin.fail(f"{key}.{name}", "is not a table")
    return tables


def check_document(doc: Mapping[str, Any], path: Path, source: str, home: Path) -> ConfigFile:
    """Validate a parsed TOML document against the config schema."""
    origin = _Origin(source, str(path), path.parent)
    top: dict[str, Any] = {}
    for key, value in doc.items():
        if key in TOP_KEYS:
            top[key] = value
        elif key not in TABLE_KEYS:
            raise origin.fail(key, "is not a known key")
    values = _convert_table(top, TOP_KEYS, origin, "", home)
    defaults = doc.get("defaults", {})
    if not isinstance(defaults, dict):
        raise origin.fail("defaults", "is not a table")
    values.update(_convert_table(defaults, DEFAULT_KEYS, origin, "defaults.", home))
    raw_profiles = _subtables(doc, "profiles", origin)
    profiles = {
        name: _convert_table(table, PROFILE_KEYS, origin, f"profiles.{name}.", home)
        for name, table in raw_profiles.items()
    }
    models = {
        name: _convert_table(table, MODEL_KEYS, origin, f"models.{name}.", home)
        for name, table in _subtables(doc, "models", origin).items()
    }
    return ConfigFile(path, values, profiles, raw_profiles, models)


def read_toml(path: Path) -> dict[str, Any] | None:
    """Parse a TOML file, or return None when it is absent. Raise `invalid_config` on bad TOML."""
    if not path.is_file():
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise VastyError("invalid_config", f"{path}: {exc}.", f"Fix {path}.") from exc


def _load(path: Path, source: str, home: Path) -> ConfigFile | None:
    doc = read_toml(path)
    return None if doc is None else check_document(doc, path, source, home)


def user_config_path(home: Path) -> Path:
    return home / ".config" / "vasty" / "config.toml"


def project_config_paths(cwd: Path) -> tuple[Path, Path]:
    """Return the project files, lower precedence first."""
    return cwd / ".vasty" / "config.toml", cwd / "vasty.toml"


def _env_layer(env: Mapping[str, str], cwd: Path, home: Path) -> dict[str, Any]:
    origin = _Origin("env", "environment", cwd, text=True)
    raw: dict[str, Any] = {}
    for key in (*TOP_KEYS, *DEFAULT_KEYS):
        value = env.get("VASTY_" + key.upper())
        if value:
            raw[key] = value
    return _convert_table(raw, {**TOP_KEYS, **DEFAULT_KEYS}, origin, "", home)


def _flag_layer(flags: Mapping[str, Any], cwd: Path, home: Path) -> dict[str, Any]:
    origin = _Origin("flag", "flags", cwd, code="invalid_arguments", text=True)
    raw = {k: v for k, v in flags.items() if k in FLAG_KEYS and v is not None}
    if "startup" in raw:
        raw["startup_file"] = raw.pop("startup")
    return _convert_table(raw, FLAG_KEYS, origin, "", home)


def _read_startup(
    spec: StartupSpec, source: str, stdin_text: Callable[[], str] | None
) -> tuple[str, str | None]:
    if spec.kind == "text":
        return spec.text or "", None
    if spec.kind == "stdin":
        if stdin_text is None:
            raise VastyError("invalid_arguments", "--startup - has no stdin to read.",
                           "Pass --startup FILE.")
        return stdin_text(), None
    assert spec.path is not None
    code = "invalid_arguments" if source == "flag" else "invalid_config"
    try:
        return spec.path.read_text(encoding="utf-8"), str(spec.path)
    except (OSError, UnicodeDecodeError) as exc:
        raise VastyError(code, f"Cannot read startup file {spec.path}: {exc}.",
                       "Pass a readable bash script.") from exc


def resolve(
    flags: Mapping[str, Any],
    stdin_json: Mapping[str, Any] | None,
    profile: str | None,
    env: Mapping[str, str],
    cwd: Path,
    home: Path,
    stdin_text: Callable[[], str] | None = None,
    model: str | None = None,
) -> Settings:
    """Merge every layer into `Settings`. Raise `invalid_config` on unknown keys or bad types.

    `stdin_text` returns stdin for `--startup -`. `model` names a `[models]`
    entry whose `vram`, `gpu` and `image` form the `model` layer. That layer
    sits below flags and above stdin, so `serve --vram` beats the entry.
    """
    user = _load(user_config_path(home), "user", home)
    project_files = [_load(p, "project", home) for p in project_config_paths(cwd)]
    files = [f for f in (user, *project_files) if f is not None]
    project: dict[str, Any] = {}
    for pf in project_files:
        if pf is not None:
            project = overlay(project, pf.values)

    profiles: dict[str, dict[str, Any]] = {}
    raw_profiles: dict[str, dict[str, Any]] = {}
    models: dict[str, dict[str, Any]] = {k: dict(v) for k, v in BUILTIN_MODELS.items()}
    for f in files:
        for name, table in f.profiles.items():
            profiles[name] = overlay(profiles.get(name, {}), table)
        for name, table in f.raw_profiles.items():
            raw_profiles[name] = overlay(raw_profiles.get(name, {}), table)
        for name, table in f.models.items():
            models[name] = {**models.get(name, {}), **table}

    selected: dict[str, Any] = {}
    if profile is not None:
        if profile not in profiles:
            known = ", ".join(sorted(profiles)) or "none"
            raise VastyError("invalid_arguments", f"Unknown profile {profile!r} (known: {known}).",
                           "Run vasty config profiles.")
        selected = profiles[profile]

    stdin_layer: dict[str, Any] = {}
    if stdin_json is not None:
        origin = _Origin("stdin", "--config - JSON", cwd)
        stdin_layer = _convert_table(stdin_json, PROFILE_KEYS, origin, "", home)

    model_layer: dict[str, Any] = {}
    if model is not None and model in models:
        origin = _Origin("model", f'[models."{model}"]', cwd)
        entry = {k: v for k, v in models[model].items() if k in MODEL_LAYER_KEYS}
        model_layer = _convert_table(entry, MODEL_LAYER_KEYS, origin, "", home)

    layers: list[tuple[str, Mapping[str, Any]]] = [
        ("flag", _flag_layer(flags, cwd, home)),
        ("model", model_layer),
        ("stdin", stdin_layer),
        ("profile", selected),
        ("env", _env_layer(env, cwd, home)),
        ("project", project),
        ("user", user.values if user is not None else {}),
        ("default", BUILTIN),
    ]
    sources: dict[str, str] = {}

    def pick(key: str) -> Any:
        for source, values in layers:
            if key in values:
                sources[key] = source
                return values[key]
        sources[key] = "default"
        return None

    owner = pick("owner")
    if owner is None:
        owner = env.get("USER", "")
        sources["owner"] = "env"
        if not VALUE.fullmatch(owner):
            raise VastyError("invalid_config", f"No usable owner: $USER is {owner!r}.",
                           "Export VASTY_OWNER=NAME.")

    ssh_path = pick("ssh_key")
    if ssh_path is None:
        for candidate in (home / ".ssh" / "id_ed25519", home / ".ssh" / "id_rsa"):
            if candidate.is_file():
                ssh_path = candidate
                break

    startup, startup_path = None, None
    spec = pick("startup")
    if spec is not None:
        startup, startup_path = _read_startup(spec, sources["startup"], stdin_text)

    return Settings(
        owner=owner,
        api_key_env=pick("api_key_env"),
        ssh_key=str(ssh_path) if ssh_path is not None else None,
        ttl=pick("ttl"),
        run_ttl=pick("run_ttl"),
        max_price=pick("max_price"),
        daily_budget=pick("daily_budget"),
        warn_before_expiry=pick("warn_before_expiry"),
        disk=pick("disk"),
        gpus=pick("gpus"),
        image=pick("image"),
        gpu=pick("gpu"),
        vram=pick("vram"),
        region=pick("region"),
        ports=list(pick("ports") or []),
        startup=startup,
        startup_path=startup_path,
        models={name: ModelEntry(**fields) for name, fields in models.items()},
        profiles=raw_profiles,
        sources=sources,
    )


# `config set`: dotted keys, TOML scalars and a small TOML emitter.


def parse_key(text: str) -> list[str]:
    """Split a dotted TOML key such as `models."Qwen/Qwen3-72B-Instruct".vram`."""
    parts: list[str] = []
    i = 0
    bad = VastyError("invalid_config", f"Bad config key {text!r}.",
                   "Pass a dotted key such as defaults.ttl.")
    while True:
        if i < len(text) and text[i] in "\"'":
            quote = text[i]
            end = text.find(quote, i + 1)
            if end < 0:
                raise bad
            raw = text[i : end + 1]
            try:
                part = json.loads(raw) if quote == '"' else raw[1:-1]
            except json.JSONDecodeError as exc:
                raise bad from exc
            i = end + 1
        else:
            m = _BARE_KEY.match(text, i)
            if m is None:
                raise bad
            part = m.group(0)
            i = m.end()
        if not part:
            raise bad
        parts.append(part)
        if i == len(text):
            return parts
        if text[i] != ".":
            raise bad
        i += 1


def key_kind(parts: list[str]) -> str:
    """Return the value kind for a dotted key. Raise `invalid_config` for an unknown key."""
    dotted = ".".join(parts)
    kind: str | None = None
    if len(parts) == 1:
        kind = TOP_KEYS.get(parts[0])
    elif len(parts) == 2 and parts[0] == "defaults":
        kind = DEFAULT_KEYS.get(parts[1])
    elif len(parts) == 3 and parts[0] == "profiles":
        if parts[2] == "daily_budget":
            raise VastyError("invalid_config", "daily_budget has no profile key.",
                           "vasty config set defaults.daily_budget VALUE")
        kind = PROFILE_KEYS.get(parts[2])
    elif len(parts) == 3 and parts[0] == "models":
        kind = MODEL_KEYS.get(parts[2])
    if kind is None:
        raise VastyError(
            "invalid_config", f"Unknown config key {dotted!r}.",
            "Pass api_key_env, owner, ssh_key, defaults.KEY, profiles.NAME.KEY "
            "or models.NAME.KEY.",
        )
    return kind


def parse_value(text: str, kind: str) -> Any:
    """Parse VALUE as a TOML value. String-typed keys keep the text as given."""
    value: Any = text
    try:
        doc = tomllib.loads(f"v = {text}")
    except tomllib.TOMLDecodeError:
        doc = {}
    if list(doc) == ["v"]:
        value = doc["v"]
    if kind in ("str", "owner", "text", "path") and not isinstance(value, str):
        return text
    if kind == "ports":
        return _ports(value, _Origin("user", "VALUE", Path("."), text=True), "ports")
    return value


def set_value(home: Path, key_text: str, value_text: str) -> Any:
    """Write one key to the user config file and return the stored value."""
    parts = parse_key(key_text)
    kind = key_kind(parts)
    value = parse_value(value_text, kind)
    path = user_config_path(home)
    doc = read_toml(path) or {}
    node: dict[str, Any] = doc
    for part in parts[:-1]:
        child = node.setdefault(part, {})
        if not isinstance(child, dict):
            raise VastyError("invalid_config", f"{part} in {path} is not a table.", f"Fix {path}.")
        node = child
    leaf = parts[-1]
    if leaf in ("startup", "startup_file"):
        node.pop("startup_file" if leaf == "startup" else "startup", None)
    node[leaf] = value
    check_document(doc, path, "user", home)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config.", suffix=".toml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(emit_toml(doc))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return value


def _toml_key(key: str) -> str:
    return key if _BARE_KEY.fullmatch(key) else _toml_string(key)


def _toml_string(text: str) -> str:
    return json.dumps(text, ensure_ascii=False).replace("\x7f", "\\u007f")


def toml_value(value: Any) -> str:
    """Render one TOML value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        inner = ", ".join(f"{_toml_key(k)} = {toml_value(v)}" for k, v in value.items())
        return "{" + inner + "}"
    raise TypeError(f"cannot render {type(value).__name__} as TOML")


def emit_toml(doc: Mapping[str, Any]) -> str:
    """Render a parsed TOML document. Scalars come before sub-tables in each table."""
    lines: list[str] = []
    _emit_table(doc, [], lines)
    return "\n".join(lines).strip("\n") + "\n"


def _emit_table(table: Mapping[str, Any], path: list[str], lines: list[str]) -> None:
    scalars = [(k, v) for k, v in table.items() if not isinstance(v, dict)]
    tables = [(k, v) for k, v in table.items() if isinstance(v, dict)]
    if path and (scalars or not tables):
        if lines:
            lines.append("")
        lines.append("[" + ".".join(_toml_key(p) for p in path) + "]")
    for key, value in scalars:
        lines.append(f"{_toml_key(key)} = {toml_value(value)}")
    for key, value in tables:
        _emit_table(value, [*path, key], lines)
