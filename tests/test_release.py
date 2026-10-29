from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from fakes import NOW, Harness, add_lease
from rig.errors import RigError
from rig.models import Instance, Job


def release(harness: Harness, *argv: str, tty: bool = False, stdin: str = "") -> tuple[int, Any, str]:
    code, out, err = harness.run("release", *argv, tty=tty, stdin=stdin)
    if tty:
        return code, out, err
    return code, json.loads(out), err


def cached(harness: Harness, lease_id: str) -> Any:
    return harness.context().cache.load().leases[lease_id]


def test_release_returns_summary_and_marks_cache(harness: Harness) -> None:
    row = add_lease(harness, label={"name": "trainer", "created": NOW - 5820,
                                           "ttl": 4 * 3600},
                    dph_total=Decimal("0.38"))
    box = harness.box.state(row.id)
    box.jobs["j-1"] = Job(id="j-1", cmd="python train.py", started_at=NOW - 5400, exit=0,
                          state="exited", finished_at=NOW)
    box.jobs["j-2"] = Job(id="j-2", cmd="python eval.py", started_at=NOW - 60, exit=None,
                          state="running")
    code, data, _ = release(harness, "trainer")
    assert code == 0
    assert harness.provider.destroyed == [row.id]
    assert data["lease"] == "l-0000a001"
    assert data["name"] == "trainer"
    assert data["uptime_s"] == 5820
    assert data["cost"] == 0.61
    assert data["destroy_pending"] is True
    assert "already_absent" not in data
    assert data["jobs"] == [
        {"id": "j-1", "cmd": "python train.py", "exit": 0, "duration_s": 5400},
        {"id": "j-2", "cmd": "python eval.py", "exit": None, "duration_s": 60},
    ]
    assert data["warnings"] == [] and data["swept"] == []
    lease = cached(harness, "l-0000a001")
    assert (lease.state, lease.released_here, lease.destroy_pending) == ("released", True, True)


def test_release_stays_destroy_pending_until_gone(harness: Harness) -> None:
    row = add_lease(harness)
    calls: list[int] = []
    harness.provider.destroy = calls.append  # type: ignore[method-assign]
    code, _, _ = release(harness, "l-0000a001")
    assert code == 0 and calls == [row.id]
    harness.run("status")
    lease = cached(harness, "l-0000a001")
    assert (lease.state, lease.destroy_pending) == ("released", True)
    assert harness.provider.destroyed == []
    del harness.provider.instances[row.id]
    harness.time.advance(30)
    harness.run("status")
    lease = cached(harness, "l-0000a001")
    assert (lease.state, lease.destroy_pending) == ("released", False)
    assert lease.history_since == NOW + 30


def test_reconciliation_records_released(harness: Harness) -> None:
    add_lease(harness, label={"expires": NOW + 600})
    release(harness, "l-0000a001")
    harness.time.advance(1200)
    code, out, _ = harness.run("status", "l-0000a001")
    assert code == 0
    assert json.loads(out)["leases"][0]["state"] == "released"


def test_release_unknown_lease_is_already_absent(harness: Harness) -> None:
    code, data, err = release(harness, "ghost")
    assert code == 0
    assert data == {"lease": "ghost", "already_absent": True, "warnings": [], "swept": []}
    assert "ghost" in err and "claude" in err
    assert harness.provider.destroyed == []


def test_release_history_lease_returns_summary_with_already_absent(harness: Harness) -> None:
    row = add_lease(harness, label={"name": "ft"})
    release(harness, "ft")
    harness.time.advance(10)
    code, data, _ = release(harness, "ft")
    assert code == 0
    assert data["lease"] == "l-0000a001"
    assert data["already_absent"] is True
    assert "destroy_pending" not in data
    assert harness.provider.destroyed == [row.id]


def test_release_unreachable_lease(harness: Harness) -> None:
    row = add_lease(harness)
    harness.run("status")
    harness.box.state(row.id).reachable = False
    code, data, _ = release(harness, "l-0000a001")
    assert code == 0
    assert harness.provider.destroyed == [row.id]
    assert data["destroy_pending"] is True


def test_release_failed_destroy_is_provider_error(harness: Harness) -> None:
    add_lease(harness)
    harness.provider.fail["destroy"] = RigError("provider_error", "boom", "retry")
    code, data, _ = release(harness, "l-0000a001")
    assert code == 2
    assert data["error"] == "provider_error"
    lease = cached(harness, "l-0000a001")
    assert lease.released_here is False


def test_release_aborts_when_expires_moved(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": NOW + 600})
    real_get = harness.provider.get_instance

    def moved(instance_id: int) -> Instance | None:
        inst = real_get(instance_id)
        if inst is not None:
            inst.label = (inst.label or "").replace(f"expires={NOW + 600}", f"expires={NOW + 9999}")
        return inst

    harness.provider.get_instance = moved  # type: ignore[method-assign]
    code, data, _ = release(harness, "l-0000a001")
    assert code == 2
    assert data["error"] == "provider_error"
    assert "expiry moved" in data["message"]
    assert row.id in harness.provider.instances


def test_release_by_instance_id_of_managed_lease(harness: Harness) -> None:
    row = add_lease(harness)
    code, data, _ = release(harness, f"i-{row.id}")
    assert code == 0
    assert data["lease"] == "l-0000a001"
    assert harness.provider.destroyed == [row.id]


# Orphans.


def test_orphan_release_non_tty_needs_yes(harness: Harness) -> None:
    harness.provider.add_instance(id=55120)
    code, data, _ = release(harness, "i-55120")
    assert code == 1
    assert data["error"] == "confirmation_required"
    assert "--yes" in data["hint"]
    assert harness.provider.destroyed == []


def test_orphan_release_with_yes(harness: Harness) -> None:
    harness.provider.add_instance(id=55120)
    harness.provider.billed = {55120: Decimal("0.44")}
    harness.provider.covered_through = NOW
    code, data, _ = release(harness, "i-55120", "--yes")
    assert code == 0
    assert harness.provider.destroyed == [55120]
    assert data["lease"] == "i-55120"
    assert data["name"] is None and data["uptime_s"] is None
    assert data["cost"] == 0.44
    assert data["jobs"] == []


def test_orphan_release_tty_prompts(harness: Harness) -> None:
    harness.provider.add_instance(id=55120)
    code, out, err = release(harness, "i-55120", tty=True, stdin="y\n")
    assert code == 0
    assert "Destroy i-55120" in err
    assert harness.provider.destroyed == [55120]
    assert "i-55120 released" in out


def test_orphan_release_tty_declined(harness: Harness) -> None:
    harness.provider.add_instance(id=55120)
    code, _, err = release(harness, "i-55120", tty=True, stdin="n\n")
    assert code == 1
    assert "confirmation_required" in err
    assert harness.provider.destroyed == []


def test_orphan_release_tty_with_yes_skips_prompt(harness: Harness) -> None:
    harness.provider.add_instance(id=55120)
    code, _, err = release(harness, "i-55120", "--yes", tty=True)
    assert code == 0
    assert "Destroy" not in err
    assert harness.provider.destroyed == [55120]


def test_unreadable_label_releases_by_instance_id(harness: Harness) -> None:
    harness.provider.add_instance(id=777, label="rig:v9;lease=l-1")
    code, data, _ = release(harness, "i-777", "--yes")
    assert code == 0
    assert harness.provider.destroyed == [777]
    assert data["lease"] == "i-777"
    assert [w["code"] for w in data["warnings"]] == ["label_unreadable"]


# Bulk.


def test_bulk_release_group(harness: Harness) -> None:
    a = add_lease(harness, "l-0000a001", label={"name": "eval-0", "group": "exp42"})
    b = add_lease(harness, "l-0000a002", label={"name": "eval-1", "group": "exp42"})
    other = add_lease(harness, "l-0000a003", label={"group": "exp42", "owner": "nick"})
    keep = add_lease(harness, "l-0000a004", label={"group": "other"})
    harness.provider.add_instance(id=55120)
    code, data, _ = release(harness, "--group", "exp42")
    assert code == 0
    assert set(data) == {"results", "warnings", "swept"}
    assert [r["lease"] for r in data["results"]] == ["l-0000a001", "l-0000a002"]
    first = data["results"][0]
    assert first["ok"] is True and first["error"] is None
    assert first["name"] == "eval-0"
    assert set(first) >= {"uptime_s", "cost", "jobs", "destroy_pending"}
    assert sorted(harness.provider.destroyed) == [a.id, b.id]
    assert other.id in harness.provider.instances and keep.id in harness.provider.instances
    assert 55120 in harness.provider.instances


def test_bulk_release_empty_match(harness: Harness) -> None:
    add_lease(harness, label={"group": "a"})
    code, data, _ = release(harness, "--group", "nothing")
    assert code == 0
    assert data["results"] == []


def test_bulk_release_reports_failed_entries(harness: Harness) -> None:
    add_lease(harness, "l-0000a001")
    b = add_lease(harness, "l-0000a002")
    harness.provider.fail["destroy"] = RigError("provider_error", "boom", "retry")
    code, data, _ = release(harness, "--all")
    assert code == 2
    first, second = data["results"]
    assert (first["ok"], first["error"]) == (False, "provider_error")
    assert (second["ok"], second["error"]) == (True, None)
    assert harness.provider.destroyed == [b.id]


def test_bulk_release_human(harness: Harness) -> None:
    add_lease(harness, label={"name": "ft"})
    code, out, _ = harness.run("release", "--all", "--plain")
    assert code == 0
    assert "l-0000a001 (ft) released" in out
