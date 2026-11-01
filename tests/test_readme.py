"""The README "Result shapes" table names only fields the result dataclasses carry.

`ROWS` maps each table row to the dataclasses behind it. `data_keys` lists the
`BulkEntry.data` keys a bulk row names, and `prose` lists the backticked
values and verbs the row's notes mention. A new row fails the test until it
is added to `ROWS`.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from pathlib import Path

from vasty.commands.config import (
    ConfigProfilesResult,
    ConfigSetResult,
    ConfigShowResult,
)
from vasty.models import (
    BulkEntry,
    BulkResult,
    ExtendResult,
    JobView,
    LeaseView,
    ReleaseSummary,
    ReserveResult,
    RunAttachedResult,
    RunDetachedResult,
    ServeResult,
    StatusResult,
    StopResult,
    SweepResult,
    SyncResult,
    TagEntry,
    TagResult,
)

README = Path(__file__).resolve().parent.parent / "README.md"


@dataclass(frozen=True)
class Row:
    classes: tuple[type, ...]
    data_keys: frozenset[str] = frozenset()
    prose: frozenset[str] = frozenset()


ROWS: dict[str, Row] = {
    "`reserve`": Row((ReserveResult,)),
    "`extend` on one lease": Row((ExtendResult,), prose=frozenset({"ttl"})),
    "`release` on one lease": Row((ReleaseSummary,)),
    "bulk `extend`, `release`": Row(
        (BulkResult, BulkEntry),
        # Keys from the entry data in extend.py and from `_entry_data` and the failure entry in release.py.
        data_keys=frozenset({
            "previous_expires_at", "expires_at",
            "name", "uptime_s", "cost", "jobs", "destroy_pending", "message",
        }),
        prose=frozenset({"extend", "release"}),
    ),
    "`tag`": Row((TagResult, TagEntry)),
    "`status`": Row(
        (StatusResult, LeaseView),
        prose=frozenset({"pending", "released", "expired", "gone", "[]"}),
    ),
    "job entry in `status` and `release` `jobs`": Row(
        (JobView,),
        prose=frozenset({"running", "serving", "exited", "killed", "unknown", "release", "stop"}),
    ),
    "attached `run`": Row((RunAttachedResult,), prose=frozenset({"box_unreachable", "lease_expired"})),
    "`run --detach`": Row((RunDetachedResult,)),
    "`serve`": Row((ServeResult,)),
    "`stop`": Row((StopResult,), prose=frozenset({"stop"})),
    "`sync`": Row((SyncResult,)),
    "`sweep`": Row((SweepResult,)),
    "`config`": Row((ConfigShowResult, ConfigSetResult, ConfigProfilesResult)),
}


def result_table() -> dict[str, str]:
    """Return the "Result shapes" table as command cell to returns cell."""
    lines = README.read_text().splitlines()
    start = lines.index("### Result shapes")
    rows: dict[str, str] = {}
    for line in lines[start + 1:]:
        if line.startswith("#"):
            break
        if not line.startswith("|") or line.startswith("|---") or line == "| Command | Returns |":
            continue
        command, returns = (cell.strip() for cell in line.strip().strip("|").split("|"))
        rows[command] = returns
    return rows


def named(cell: str) -> set[str]:
    """Return the backticked names in a cell, splitting `{a, b}` into its keys."""
    out: set[str] = set()
    for token in re.findall(r"`([^`]+)`", cell):
        if token.startswith("{") and token.endswith("}"):
            out.update(part.strip() for part in token[1:-1].split(","))
        else:
            out.add(token)
    return out


def test_every_table_row_has_a_mapping() -> None:
    assert sorted(result_table()) == sorted(ROWS)


def test_every_named_field_is_a_dataclass_field() -> None:
    for command, returns in result_table().items():
        row = ROWS[command]
        fields = {f.name for cls in row.classes for f in dataclasses.fields(cls)}
        tokens = named(returns)
        unknown = tokens - fields - row.data_keys - row.prose
        assert not unknown, f"{command}: {sorted(unknown)} not in {[c.__name__ for c in row.classes]}"
        stale = (row.data_keys | row.prose) - tokens
        assert not stale, f"{command}: {sorted(stale)} in ROWS but not in the README row"
