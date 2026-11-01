"""Lease ids, orphan ids, job numbers and name validation."""

from __future__ import annotations

import re
from collections.abc import Callable

from vasty.errors import invalid

LEASE_ID = re.compile(r"l-[0-9a-f]+")
ORPHAN_ID = re.compile(r"i-[0-9]+")
JOB_NUMBER = re.compile(r"j-([0-9]+)")
VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")
KINDS = ("name", "group", "owner")
MAX_DRAWS = 1000


def new_lease_id(random_hex: Callable[[int], str], taken: set[str]) -> str:
    """Draw `l-` plus 8 hex digits, redrawing while the id is taken.

    `random_hex(n)` returns n random bytes as 2n hex digits. Raise RuntimeError
    after `MAX_DRAWS` taken draws.
    """
    for _ in range(MAX_DRAWS):
        lease = "l-" + random_hex(4).lower()
        if lease not in taken:
            return lease
    raise RuntimeError("random_hex keeps returning taken lease ids")


def orphan_id(instance_id: int) -> str:
    """Return `i-` plus the Vast instance id."""
    return f"i-{instance_id}"


def parse_orphan_id(text: str) -> int | None:
    """Return the instance id for `i-<digits>`, else None."""
    if ORPHAN_ID.fullmatch(text):
        return int(text[2:])
    return None


def job_number(job_id: str) -> int | None:
    """Return N for a `j-N` job id, else None."""
    match = JOB_NUMBER.fullmatch(job_id)
    return None if match is None else int(match.group(1))


def is_lease_id(text: str) -> bool:
    """Return True when the text has the `l-<hex>` lease id form."""
    return LEASE_ID.fullmatch(text) is not None


def validate_value(kind: str, value: str) -> str:
    """Check a name, group or owner against the pattern. Raise `invalid_arguments` otherwise."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    if not VALUE.fullmatch(value):
        raise invalid(
            f"Invalid {kind} {value!r}.",
            "Use 1 to 63 letters, digits, '.', '_' or '-', starting with a letter or digit.",
        )
    if kind == "name" and (LEASE_ID.fullmatch(value) or ORPHAN_ID.fullmatch(value)):
        raise invalid(
            f"Name {value!r} looks like a lease or instance id.",
            "Pick a name outside the l-HEX and i-DIGITS forms.",
        )
    return value
