"""The `rig:v1` instance label (spec §8.0)."""

from __future__ import annotations

from dataclasses import dataclass

from rig.models import Label

PREFIX = "rig:"
MAX_LEN = 1024


@dataclass(frozen=True)
class Unreadable:
    """A `rig:` label with an unknown version or missing fields."""

    raw: str
    reason: str


def parse(raw: str | None) -> Label | Unreadable | None:
    """Return a `Label`, `Unreadable` for a broken `rig:` label, or None for an orphan."""
    raise NotImplementedError


def format_label(label: Label) -> str:
    """Render a label. Raise `invalid_arguments` when it exceeds 1024 characters."""
    raise NotImplementedError
