"""Configuration resolution (spec §5).

Layers, highest first: flags, `--config -` JSON, `--profile`, environment,
project file, user file, built-in defaults. `resolve` returns the effective
`Settings` and the source of each value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

SOURCES = ("flag", "stdin", "profile", "env", "project", "user", "default")


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


def resolve(
    flags: Mapping[str, Any],
    stdin_json: Mapping[str, Any] | None,
    profile: str | None,
    env: Mapping[str, str],
    cwd: Path,
    home: Path,
) -> Settings:
    """Merge every layer into `Settings`. Raise `invalid_config` on unknown keys or bad types."""
    raise NotImplementedError
