"""Lease ids, orphan ids and name validation (spec §4.0)."""

from __future__ import annotations

from typing import Callable


def new_lease_id(random_hex: Callable[[int], str], taken: set[str]) -> str:
    """Draw `l-` plus 8 hex digits, redrawing while the id is taken."""
    raise NotImplementedError


def orphan_id(instance_id: int) -> str:
    raise NotImplementedError


def parse_orphan_id(text: str) -> int | None:
    """Return the instance id for `i-<digits>`, else None."""
    raise NotImplementedError


def validate_value(kind: str, value: str) -> str:
    """Check a name, group or owner against the pattern. Raise `invalid_arguments` otherwise."""
    raise NotImplementedError
