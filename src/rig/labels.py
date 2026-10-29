"""The `rig:v1` instance label (spec §8.0).

A label is `rig:v1` followed by `;`-separated `key=value` fields with unique
keys. `format_label` writes known fields in the order `lease`, `name`, `owner`,
`group`, `created`, `ttl`, `expires`, `miss`, then unknown fields in the order
they were read. `miss` holds guard layers separated by commas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rig import ids
from rig.errors import invalid
from rig.models import Label

PREFIX = "rig:"
VERSION = "v1"
MAX_LEN = 1024
MISS_SEP = ","
MAX_EPOCH = 253402300799

KNOWN_KEYS = ("lease", "name", "owner", "group", "created", "ttl", "expires", "miss")
_REQUIRED = ("lease", "owner", "created", "ttl")
_UINT = re.compile(r"[0-9]+")
_KEY = re.compile(r"[A-Za-z0-9_.-]+")
_PAST_MAX = "time is past 9999-12-31T23:59:59Z"


@dataclass(frozen=True)
class Unreadable:
    """A `rig:` label with an unknown version, missing fields or a bad value."""

    raw: str
    reason: str


def is_managed(raw: str | None) -> bool:
    """Return True when the label starts with `rig:`."""
    return raw is not None and raw.startswith(PREFIX)


def parse(raw: str | None) -> Label | Unreadable | None:
    """Return a `Label`, `Unreadable` for a broken `rig:` label, or None for an orphan."""
    if raw is None or not raw.startswith(PREFIX):
        return None
    parts = raw.split(";")
    version = parts[0][len(PREFIX):]
    if version != VERSION:
        return Unreadable(raw, f"unknown label version {version!r}")
    fields: dict[str, str] = {}
    for part in parts[1:]:
        if part == "":
            continue
        key, sep, value = part.partition("=")
        if not sep or not _KEY.fullmatch(key):
            return Unreadable(raw, f"malformed field {part!r}")
        if key in fields:
            return Unreadable(raw, f"duplicate field {key!r}")
        fields[key] = value
    missing = [k for k in _REQUIRED if not fields.get(k)]
    if missing:
        return Unreadable(raw, "missing " + ", ".join(missing))
    if not ids.LEASE_ID.fullmatch(fields["lease"]):
        return Unreadable(raw, f"malformed lease {fields['lease']!r}")
    for key in ("owner", "name", "group"):
        if fields.get(key) and not ids.VALUE.fullmatch(fields[key]):
            return Unreadable(raw, f"malformed {key} {fields[key]!r}")
    for key in ("created", "ttl", "expires"):
        if key in fields and not _UINT.fullmatch(fields[key]):
            return Unreadable(raw, f"{key} is not an integer")
        if len(fields.get(key, "").lstrip("0")) > len(str(MAX_EPOCH)):
            return Unreadable(raw, _PAST_MAX)
    created = int(fields["created"])
    ttl = int(fields["ttl"])
    if ttl <= 0:
        return Unreadable(raw, "ttl is not positive")
    expires = int(fields["expires"]) if "expires" in fields else None
    if max(created + ttl, expires or 0) > MAX_EPOCH:
        return Unreadable(raw, _PAST_MAX)
    miss_text = fields.get("miss", "")
    miss = miss_text.split(MISS_SEP) if miss_text else []
    if any(not layer for layer in miss):
        return Unreadable(raw, f"malformed miss {miss_text!r}")
    return Label(
        lease=fields["lease"],
        owner=fields["owner"],
        created=created,
        ttl=ttl,
        name=fields.get("name") or None,
        group=fields.get("group") or None,
        expires=expires,
        miss=miss,
        extra={k: v for k, v in fields.items() if k not in KNOWN_KEYS},
    )


def format_label(label: Label) -> str:
    """Render a label. Raise `invalid_arguments` when it exceeds 1024 characters."""
    if label.ttl <= 0:
        raise invalid(f"Label ttl {label.ttl} is not positive.", "Pass a positive --ttl.")
    pairs: list[tuple[str, str]] = [("lease", label.lease)]
    if label.name:
        pairs.append(("name", label.name))
    pairs.append(("owner", label.owner))
    if label.group:
        pairs.append(("group", label.group))
    pairs.append(("created", str(label.created)))
    pairs.append(("ttl", str(label.ttl)))
    if label.expires is not None:
        pairs.append(("expires", str(label.expires)))
    if label.miss:
        for layer in label.miss:
            if not layer or any(c in layer for c in ";=,"):
                raise invalid(f"Guard layer {layer!r} cannot go in a label.")
        pairs.append(("miss", MISS_SEP.join(label.miss)))
    for key, value in label.extra.items():
        if key in KNOWN_KEYS or not _KEY.fullmatch(key):
            raise invalid(f"Label field {key!r} cannot go in a label.")
        pairs.append((key, value))
    for key, value in pairs:
        if ";" in value:
            raise invalid(f"Label field {key} contains ';'.", "Remove ';' from the value.")
    text = ";".join([PREFIX + VERSION, *(f"{k}={v}" for k, v in pairs)])
    if len(text) > MAX_LEN:
        raise invalid(
            f"Label is {len(text)} characters; the limit is {MAX_LEN}.",
            "Use a shorter name, group or owner.",
        )
    return text
