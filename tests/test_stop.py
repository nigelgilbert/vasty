from __future__ import annotations

import json
from typing import Any

import pytest
from fakes import NOW, Harness, add_lease

from vasty.cli import build_parser
from vasty.commands import stop
from vasty.models import Job


def run_json(harness: Harness, *argv: str) -> tuple[int, Any]:
    code, out, _ = harness.run(*argv)
    return code, json.loads(out)


def live_job(job_id: str, started: int) -> Job:
    return Job(id=job_id, cmd=f"python {job_id}.py", started_at=started, exit=None, state="running")


@pytest.fixture
def box(harness: Harness) -> int:
    return add_lease(harness, label={"name": "ft"}).id


def status_jobs(harness: Harness) -> dict[str, Any]:
    _, data = run_json(harness, "status", "ft")
    return {entry["job"]: entry for entry in data["leases"][0]["jobs"]}


def test_stop_with_one_live_job_kills_it(harness: Harness, box: int) -> None:
    harness.box.state(box).jobs["j-1"] = live_job("j-1", NOW - 300)
    code, data = run_json(harness, "stop", "ft")
    assert code == 0
    assert data == {
        "lease": "l-0000a001", "job": "j-1", "cmd": "python j-1.py", "state": "killed",
        "exit": 143, "duration_s": 300, "warnings": [], "swept": [],
    }
    assert harness.box.state(box).signals == [("j-1", "TERM")]
    harness.time.advance(600)
    for _ in range(2):
        entry = status_jobs(harness)["j-1"]
        assert (entry["state"], entry["exit"], entry["duration_s"]) == ("killed", 143, 300)


def test_stop_with_two_live_jobs_needs_a_job(harness: Harness, box: int) -> None:
    state = harness.box.state(box)
    state.jobs["j-1"] = live_job("j-1", NOW - 300)
    state.jobs["j-2"] = live_job("j-2", NOW - 200)
    code, data = run_json(harness, "stop", "ft")
    assert code == 1
    assert data["error"] == "invalid_arguments"
    assert "j-1, j-2" in data["message"]
    assert data["details"] == {"lease": "l-0000a001", "jobs": ["j-1", "j-2"]}
    assert state.signals == []


def test_stop_named_job_leaves_the_other_running(harness: Harness, box: int) -> None:
    state = harness.box.state(box)
    state.jobs["j-1"] = live_job("j-1", NOW - 300)
    state.jobs["j-2"] = live_job("j-2", NOW - 200)
    code, data = run_json(harness, "stop", "ft", "j-2")
    assert code == 0
    assert (data["job"], data["state"], data["exit"]) == ("j-2", "killed", 143)
    assert state.signals == [("j-2", "TERM")]
    jobs = status_jobs(harness)
    assert jobs["j-1"]["state"] == "running"
    assert jobs["j-2"]["state"] == "killed"


def test_stop_job_that_ignores_term_gets_kill(harness: Harness, box: int) -> None:
    state = harness.box.state(box)
    state.ignores_term = True
    state.jobs["j-1"] = live_job("j-1", NOW - 300)
    start = harness.time.mono_now
    code, data = run_json(harness, "stop", "ft")
    assert code == 0
    assert (data["state"], data["exit"]) == ("killed", 137)
    assert harness.time.mono_now - start >= stop.STOP_WAIT_S
    assert state.signals == [("j-1", "TERM"), ("j-1", "KILL")]
    entry = status_jobs(harness)["j-1"]
    assert (entry["state"], entry["exit"]) == ("killed", 137)


def test_stop_job_that_survives_kill_stays_running(harness: Harness, box: int) -> None:
    state = harness.box.state(box)
    state.signal_exits = {}
    state.jobs["j-1"] = live_job("j-1", NOW - 300)
    start = harness.time.mono_now
    code, out, _ = harness.run("stop", "ft", "--plain")
    assert code == stop.RUNNING_EXIT == 2
    assert out.startswith("j-1 on l-0000a001 still runs 5s after KILL.")
    assert harness.time.mono_now - start >= stop.STOP_WAIT_S + stop.KILL_WAIT_S
    assert state.signals == [("j-1", "TERM"), ("j-1", "KILL")]
    code, data = run_json(harness, "stop", "ft")
    assert code == 2
    assert (data["state"], data["exit"]) == ("running", None)
    assert status_jobs(harness)["j-1"]["state"] == "running"


def test_stop_without_live_jobs_is_invalid(harness: Harness, box: int) -> None:
    harness.box.state(box).jobs["j-1"] = Job(
        id="j-1", cmd="ls", started_at=NOW - 60, exit=0, state="exited", finished_at=NOW - 50
    )
    code, data = run_json(harness, "stop", "ft")
    assert code == 1 and data["error"] == "invalid_arguments"
    code, data = run_json(harness, "stop", "ft", "j-1")
    assert code == 1 and data["error"] == "invalid_arguments"
    assert data["details"]["jobs"] == []


def test_stop_unknown_lease_is_not_found(harness: Harness, box: int) -> None:
    code, data = run_json(harness, "stop", "nope")
    assert code == 1 and data["error"] == "lease_not_found"


def test_stop_human_output(harness: Harness, box: int) -> None:
    harness.box.state(box).jobs["j-1"] = live_job("j-1", NOW - 300)
    code, out, _ = harness.run("stop", "ft", "--plain")
    assert code == 0
    assert out == "Stopped j-1 on l-0000a001: exit 143 after 5m\n"


def test_stop_takes_no_command(harness: Harness) -> None:
    code, out, _ = harness.run("stop", "ft", "--", "ls")
    assert code == 1 and json.loads(out)["error"] == "invalid_arguments"


def test_stop_positionals_have_help() -> None:
    sub = next(a for a in build_parser()._actions if a.dest == "verb")
    parser = sub.choices["stop"]  # type: ignore[index]
    helps = {a.dest: a.help for a in parser._actions if not a.option_strings}
    assert helps["lease"] and helps["job"]
