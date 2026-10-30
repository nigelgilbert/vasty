"""JSON and human rendering."""

from __future__ import annotations

import dataclasses
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from vasty.models import BulkEntry


def money(value: Decimal) -> float:
    """Round money to 2 places for output."""
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def to_jsonable(obj: Any) -> Any:
    """Convert dataclasses, Decimals and containers to plain JSON values.

    Fields with `omit_none` metadata drop out when None. A `BulkEntry` merges
    its `data` into the entry.
    """
    if isinstance(obj, BulkEntry):
        out: dict[str, Any] = {"lease": obj.lease, "ok": obj.ok, "error": obj.error}
        for key, value in obj.data.items():
            out[key] = to_jsonable(value)
        return out
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        result: dict[str, Any] = {}
        for f in dataclasses.fields(obj):
            value = getattr(obj, f.name)
            if value is None and f.metadata.get("omit_none"):
                continue
            result[f.name] = to_jsonable(value)
        return result
    if isinstance(obj, Decimal):
        return money(obj)
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


def dumps(obj: Any) -> str:
    return json.dumps(to_jsonable(obj), indent=2)


def generic_human(obj: Any) -> str:
    """Render any payload as `key: value` lines."""
    data = to_jsonable(obj)
    if not isinstance(data, dict):
        return json.dumps(data, indent=2)
    lines = []
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        lines.append(f"{key}: {value}")
    return "\n".join(lines)
