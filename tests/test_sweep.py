from __future__ import annotations

import json
import sys
from typing import Any

import pytest

from fakes import NOW, Harness, add_lease
from vasty.commands import sweep
from vasty.errors import VastyError

FOLLOW = [sys.executable, "-m", "vasty", "sweep", "--follow"]


def run_json(harness: Harness, *argv: str) -> tuple[int, dict[str, Any]]:
    code, out, _ = harness.run(*argv)
    data: dict[str, Any] = json.loads(out)
    return code, data


# One pass.


def test_sweep_destroys_past_clock_without_probing(harness: Harness) -> None:
    gone = add_lease(harness, "l-0000a001", label={"name": "old", "expires": NOW - 10})
    kept = add_lease(harness, "l-0000a002", label={"expires": NOW + 600})
    code, data = run_json(harness, "sweep")
    assert code == 0, data
    assert set(data) == {"swept", "warnings"}
    assert data["swept"] == [{
        "lease": "l-0000a001", "name": "old", "expired_at": "2026-10-29T00:59:50Z",
        "ok": True, "error": None,
    }]
    assert data["warnings"] == []
    assert harness.provider.destroyed == [gone.id]
    assert kept.id in harness.provider.instances
    assert harness.box.probes == []
    assert harness.spawned == []


def test_sweep_carries_account_warnings(harness: Harness) -> None:
    harness.provider.date_header = False
    _, data = run_json(harness, "sweep")
    assert [w["code"] for w in data["warnings"]] == ["clock_unverified"]


def test_sweep_human_output(harness: Harness) -> None:
    add_lease(harness, label={"expires": NOW - 10})
    code, out, _ = harness.run("sweep", "--plain")
    assert code == 0
    assert out.startswith("SWEPT  l-0000a001  expired 2026-10-29T00:59:50Z  destroyed")
    assert harness.run("sweep", "--plain") == (0, "nothing swept\n", "")


# Follow.


def test_follow_sleeps_to_expiry_and_destroys(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": NOW + 600})
    code, data = run_json(harness, "sweep", "--follow", "l-0000a001")
    assert code == 0, data
    assert harness.provider.destroyed == [row.id]
    assert harness.time.wall_now == NOW + 601 + sweep.FOLLOW_RETRY_S
    assert [e["lease"] for e in data["swept"]] == ["l-0000a001"]
    assert harness.provider.calls.count(("list_instances", None)) == 3
    assert harness.box.probes == []


def test_follow_accepts_a_name(harness: Harness) -> None:
    row = add_lease(harness, label={"name": "ft", "expires": NOW + 60})
    code, _ = run_json(harness, "sweep", "--follow", "ft")
    assert code == 0
    assert harness.provider.destroyed == [row.id]


def test_follow_picks_up_a_later_extend(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": NOW + 600})
    sleep = harness.time.sleep
    moved: list[int] = []

    def sleep_then_extend(seconds: float) -> None:
        sleep(seconds)
        if not moved:
            harness.provider.instances[row.id].label = add_label(harness, NOW + 3000)
            moved.append(1)

    harness.time.sleep = sleep_then_extend  # type: ignore[method-assign]
    code, _ = run_json(harness, "sweep", "--follow", "l-0000a001")
    assert code == 0
    assert harness.provider.destroyed == [row.id]
    assert harness.time.wall_now == NOW + 3001 + sweep.FOLLOW_RETRY_S


def add_label(harness: Harness, expires: int) -> str:
    from fakes import lease_label

    return lease_label(expires=expires)


def test_follow_retries_a_failed_destroy(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": NOW + 60})
    harness.provider.fail["destroy"] = VastyError("provider_error", "boom", "retry")
    code, data = run_json(harness, "sweep", "--follow", "l-0000a001")
    assert code == 0, data
    assert harness.provider.destroyed == [row.id]
    assert [(e["ok"], e["error"]) for e in data["swept"]] == [(False, "provider_error")]
    assert harness.time.wall_now == NOW + 61 + 2 * sweep.FOLLOW_RETRY_S


def test_follow_waits_while_the_destroyed_row_stays_listed(harness: Harness) -> None:
    harness.provider.keep_rows = True
    row = add_lease(harness, label={"expires": NOW + 60})
    sleeps: list[float] = []
    sleep = harness.time.sleep

    def record(seconds: float) -> None:
        sleeps.append(seconds)
        sleep(seconds)
        if len(sleeps) == 3:
            harness.provider.instances.pop(row.id)

    harness.time.sleep = record  # type: ignore[method-assign]
    code, _ = run_json(harness, "sweep", "--follow", "l-0000a001")
    assert code == 0
    assert sleeps == [61, sweep.FOLLOW_RETRY_S, sweep.FOLLOW_RETRY_S]


def test_follow_returns_at_once_for_a_history_lease(harness: Harness) -> None:
    add_lease(harness, label={"expires": NOW - 10})
    harness.run("status")
    code, data = run_json(harness, "sweep", "--follow", "l-0000a001")
    assert code == 0, data
    assert data["swept"] == []
    assert harness.time.wall_now == NOW


def test_follow_unknown_lease(harness: Harness) -> None:
    code, data = run_json(harness, "sweep", "--follow", "l-0000ffff")
    assert code == 1
    assert data["error"] == "lease_not_found"


def test_follow_rejects_an_orphan(harness: Harness) -> None:
    harness.provider.add_instance(id=55120)
    code, data = run_json(harness, "sweep", "--follow", "i-55120")
    assert code == 1
    assert data["error"] == "invalid_arguments"
    assert data["hint"] == "vasty tag i-55120 --ttl 30m"


def test_follow_sleeps_in_chunks_against_the_wall_clock(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": NOW + 1000})
    sleeps: list[float] = []
    sleep = harness.time.sleep

    def record(seconds: float) -> None:
        sleeps.append(seconds)
        sleep(seconds)
        if len(sleeps) == 1:
            harness.time.advance(5000)

    harness.time.sleep = record  # type: ignore[method-assign]
    code, _ = run_json(harness, "sweep", "--follow", "l-0000a001")
    assert code == 0
    assert sleeps == [sweep.SLEEP_CHUNK_S, sweep.FOLLOW_RETRY_S]
    assert harness.provider.destroyed == [row.id]


def test_follow_retries_a_failed_refresh(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": NOW + 60})
    harness.provider.fail["list_instances"] = [
        VastyError("provider_error", "down", "retry"), VastyError("provider_error", "down", "retry"),
    ]
    code, _ = run_json(harness, "sweep", "--follow", "l-0000a001")
    assert code == 0
    assert harness.provider.destroyed == [row.id]
    assert harness.time.wall_now == NOW + 3 * sweep.FOLLOW_RETRY_S


def test_follow_retries_through_an_outage_of_every_retry(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": NOW + 60})
    harness.provider.fail["list_instances"] = [
        VastyError("provider_error", "down", "retry") for _ in range(sweep.FOLLOW_RETRIES)
    ]
    code, _ = run_json(harness, "sweep", "--follow", "l-0000a001")
    assert code == 0
    assert harness.provider.destroyed == [row.id]
    assert harness.time.wall_now == NOW + (sweep.FOLLOW_RETRIES + 1) * sweep.FOLLOW_RETRY_S


def test_follow_gives_up_after_the_last_retry(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": NOW + 60})
    harness.provider.fail["list_instances"] = [
        VastyError("provider_error", "Vast list returned HTTP 401", "Check the Vast API key.")
        for _ in range(sweep.FOLLOW_RETRIES + 1)
    ]
    code, data = run_json(harness, "sweep", "--follow", "l-0000a001")
    assert code == 2
    assert data["error"] == "provider_error"
    assert data["hint"] == "Check the Vast API key."
    assert harness.provider.destroyed == []
    assert harness.time.wall_now == NOW + sweep.FOLLOW_RETRIES * sweep.FOLLOW_RETRY_S


def test_follow_retries_an_early_release_whose_row_stays_listed(harness: Harness) -> None:
    harness.provider.keep_rows = True
    row = add_lease(harness, label={"expires": NOW + 86_400})
    harness.run("release", "l-0000a001")
    sleeps: list[float] = []
    sleep = harness.time.sleep

    def record(seconds: float) -> None:
        sleeps.append(seconds)
        sleep(seconds)
        harness.provider.instances.pop(row.id, None)

    harness.time.sleep = record  # type: ignore[method-assign]
    code, _ = run_json(harness, "sweep", "--follow", "l-0000a001")
    assert code == 0
    assert sleeps == [sweep.FOLLOW_RETRY_S]


def test_follow_notices_a_release_during_the_sleep(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": NOW + 86_400})
    sleeps: list[float] = []
    sleep = harness.time.sleep

    def record(seconds: float) -> None:
        sleeps.append(seconds)
        sleep(seconds)
        if len(sleeps) == 2:
            assert harness.run("release", "l-0000a001")[0] == 0

    harness.time.sleep = record  # type: ignore[method-assign]
    code, data = run_json(harness, "sweep", "--follow", "l-0000a001")
    assert code == 0, data
    assert sleeps == [sweep.SLEEP_CHUNK_S, sweep.SLEEP_CHUNK_S]
    assert harness.provider.destroyed == [row.id]
    assert harness.time.wall_now == NOW + 2 * sweep.SLEEP_CHUNK_S


def test_follow_retries_a_release_left_pending_during_the_sleep(harness: Harness) -> None:
    harness.provider.keep_rows = True
    row = add_lease(harness, label={"expires": NOW + 86_400})
    sleeps: list[float] = []
    sleep = harness.time.sleep

    def record(seconds: float) -> None:
        sleeps.append(seconds)
        sleep(seconds)
        if len(sleeps) == 1:
            assert harness.run("release", "l-0000a001")[0] == 0
        if len(sleeps) == 3:
            harness.provider.instances.pop(row.id, None)

    harness.time.sleep = record  # type: ignore[method-assign]
    code, _ = run_json(harness, "sweep", "--follow", "l-0000a001")
    assert code == 0
    assert sleeps == [sweep.SLEEP_CHUNK_S, sweep.FOLLOW_RETRY_S, sweep.FOLLOW_RETRY_S]


# The spawn.


def test_spawn_follow_starts_a_detached_sweep(harness: Harness) -> None:
    ctx = harness.context()
    assert sweep.spawn_follow(ctx, "l-0000a001") is None
    assert harness.spawned == [[*FOLLOW, "l-0000a001"]]


def test_spawn_follow_warns_when_the_spawn_fails(harness: Harness) -> None:
    harness.spawn_error = OSError("no fork")
    warning = sweep.spawn_follow(harness.context(), "l-0000a001")
    assert warning is not None
    assert (warning.code, warning.lease, warning.fix) == (
        "sweep_not_spawned", "l-0000a001", "vasty sweep --follow l-0000a001")
    assert warning.message == "could not start the follower: no fork"


def test_default_spawn_detaches(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from vasty.context import default_spawn

    calls: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: calls.append((argv, kw)))
    default_spawn(["x"], {"A": "1"})
    [(argv, kw)] = calls
    assert argv == ["x"]
    assert kw["env"] == {"A": "1"}
    assert kw["start_new_session"] is True
    assert kw["stdin"] is kw["stdout"] is kw["stderr"] is subprocess.DEVNULL
