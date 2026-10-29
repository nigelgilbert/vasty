from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TextIO

import pytest

from fakes import NOW, FakeReserve, Harness, add_lease
from rig.errors import RigError
from rig.models import Job
from rig.remote import SshTarget


def run(harness: Harness, *argv: str) -> tuple[int, dict[str, Any], str]:
    code, out, err = harness.run("run", *argv)
    return code, json.loads(out), err


def cached(harness: Harness, lease_id: str) -> Any:
    return harness.context().cache.load().leases[lease_id]


@pytest.fixture
def box(harness: Harness) -> int:
    row = add_lease(harness, label={"name": "ft"})
    return row.id


@pytest.fixture
def reserve(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> FakeReserve:
    return FakeReserve(harness).install(monkeypatch)


# --on.


def test_run_on_streams_to_stderr_in_json_and_passes_exit(harness: Harness, box: int) -> None:
    harness.box.state(box).job_exit = 3
    code, data, err = run(harness, "--on", "ft", "--", "python", "train.py", "--lr", "1e-4")
    assert code == 3
    assert data == {
        "lease": "l-0000a001", "job": "j-1", "exit": 3, "duration_s": 0, "released": False,
        "warnings": [], "swept": [], "error": None,
    }
    assert "started python train.py --lr 1e-4" in err
    lease = cached(harness, "l-0000a001")
    assert [(j.id, j.cmd, j.exit, j.state) for j in lease.jobs] == [
        ("j-1", "python train.py --lr 1e-4", 3, "exited")
    ]
    assert box in harness.provider.instances


def test_run_shell_joins_command(harness: Harness, box: int) -> None:
    run(harness, "--on", "ft", "--", "echo", "a b", "$HOME")
    assert harness.box.state(box).jobs["j-1"].cmd == "echo 'a b' '$HOME'"


def test_run_human_mode_streams_to_stdout(harness: Harness, box: int) -> None:
    code, out, err = harness.run("run", "--on", "ft", "--plain", "--", "ls")
    assert code == 0
    assert out.startswith("started ls\n")
    assert "j-1 on l-0000a001 exited 0" in out
    assert "started ls" not in err


def test_run_job_ids_count_up(harness: Harness, box: int) -> None:
    harness.box.state(box).jobs["j-4"] = Job(id="j-4", cmd="x", started_at=NOW - 10, exit=0,
                                             state="exited")
    _, data, _ = run(harness, "--on", "ft", "--", "ls")
    assert data["job"] == "j-5"
    _, data, _ = run(harness, "--on", "ft", "--", "ls")
    assert data["job"] == "j-6"


def test_run_detach_returns_job_immediately(harness: Harness, box: int) -> None:
    attached: list[str] = []
    harness.box.attach_job = lambda t, j, o: attached.append(j)  # type: ignore[method-assign,assignment,return-value]
    code, data, _ = run(harness, "--on", "ft", "--detach", "--", "python", "train.py")
    assert code == 0
    assert data == {
        "lease": "l-0000a001", "job": "j-1", "log_path": "/workspace/.rig/jobs/j-1/log",
        "expires_at": "2026-10-29T01:50:00Z", "warnings": [], "swept": [],
    }
    assert attached == []
    assert cached(harness, "l-0000a001").jobs[0].state == "running"


def test_run_warns_when_clock_is_short(harness: Harness) -> None:
    add_lease(harness, label={"name": "ft", "expires": NOW + 120})
    code, data, err = run(harness, "--on", "ft", "--", "ls")
    assert code == 0
    assert "rig extend l-0000a001 --by 30m" in err
    assert [w["code"] for w in data["warnings"]] == ["expiring_with_running_job"]


def test_run_on_orphan_is_unmanaged(harness: Harness) -> None:
    harness.provider.add_instance(id=55120)
    code, data, _ = run(harness, "--on", "i-55120", "--", "ls")
    assert code == 1 and data["error"] == "orphan_unmanaged"


def test_run_on_history_lease_is_expired(harness: Harness) -> None:
    add_lease(harness, label={"name": "ft", "expires": NOW - 5})
    code, data, _ = run(harness, "--on", "ft", "--", "ls")
    assert code == 1 and data["error"] == "lease_expired"


def test_run_on_unreached_lease_is_pending(harness: Harness) -> None:
    add_lease(harness, label={"name": "ft"}, reachable=False)
    code, data, _ = run(harness, "--on", "ft", "--", "ls")
    assert code == 1 and data["error"] == "lease_pending"


def test_run_on_loading_lease_is_pending(harness: Harness) -> None:
    add_lease(harness, label={"name": "ft"}, actual_status="loading")
    code, data, _ = run(harness, "--on", "ft", "--", "ls")
    assert code == 1 and data["error"] == "lease_pending"


def test_run_without_ssh_is_dependency_missing(harness: Harness, box: int) -> None:
    harness.missing_tools.add("ssh")
    code, data, _ = run(harness, "--on", "ft", "--", "ls")
    assert code == 1 and data["error"] == "dependency_missing"


def test_run_on_rejects_creation_flags(harness: Harness, box: int) -> None:
    code, data, _ = run(harness, "--on", "ft", "--ttl", "1h", "--", "ls")
    assert code == 1 and data["error"] == "invalid_arguments"


# Connection loss and box death.


def test_dropped_connection_is_box_unreachable(harness: Harness, box: int) -> None:
    harness.box.state(box).job_exit = None
    code, data, err = run(harness, "--on", "ft", "--", "ls")
    assert code == 2
    assert data["error"] == "box_unreachable"
    assert data["exit"] is None and data["job"] == "j-1"
    assert "lost the connection" in err


def test_box_killed_with_job_is_lease_expired(harness: Harness, box: int) -> None:
    def killed(target: SshTarget, job_id: str, out: TextIO) -> int | None:
        harness.time.advance(4000)
        harness.provider.instances.pop(box)
        return None

    harness.box.attach_job = killed  # type: ignore[method-assign]
    code, data, _ = run(harness, "--on", "ft", "--", "python", "train.py")
    assert code == 2
    assert data["error"] == "lease_expired"
    assert data["exit"] is None


# SIGINT.


def _interrupt(harness: Harness, box: int, exit_code: int | None) -> None:
    def attach(target: SshTarget, job_id: str, out: TextIO) -> int | None:
        if exit_code is not None:
            job = harness.box.state(box).jobs[job_id]
            job.exit, job.state = exit_code, "exited"
        raise KeyboardInterrupt

    harness.box.attach_job = attach  # type: ignore[method-assign]


def test_sigint_forwards_and_exits_130(harness: Harness, box: int) -> None:
    _interrupt(harness, box, 130)
    code, data, _ = run(harness, "--on", "ft", "--", "python", "train.py")
    assert code == 130
    assert harness.box.state(box).signals == [("j-1", "INT")]
    assert data["exit"] == 130 and data["released"] is False
    assert box in harness.provider.instances
    assert cached(harness, "l-0000a001").jobs[0].exit == 130


def test_sigint_waits_up_to_10s(harness: Harness, box: int) -> None:
    _interrupt(harness, box, None)
    start = harness.time.mono_now
    code, data, _ = run(harness, "--on", "ft", "--", "sleep", "100")
    assert code == 130
    assert data["exit"] is None
    assert 10 <= harness.time.mono_now - start <= 11


def test_sigint_releases_auto_reserved_box(harness: Harness, reserve: FakeReserve) -> None:
    harness.box.attach_job = lambda t, j, o: (_ for _ in ()).throw(KeyboardInterrupt)  # type: ignore[method-assign,assignment,return-value]
    code, data, _ = run(harness, "--", "python", "train.py")
    assert code == 130
    assert data["released"] is True
    assert harness.provider.destroyed == [1001]


def test_sigint_keeps_named_box(harness: Harness, reserve: FakeReserve) -> None:
    harness.box.attach_job = lambda t, j, o: (_ for _ in ()).throw(KeyboardInterrupt)  # type: ignore[method-assign,assignment,return-value]
    code, data, _ = run(harness, "--name", "keep", "--", "python", "train.py")
    assert code == 130
    assert data["released"] is False
    assert harness.provider.destroyed == []


def _second_interrupt(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(seconds: float) -> None:
        raise KeyboardInterrupt

    harness.box.attach_job = lambda t, j, o: (_ for _ in ()).throw(KeyboardInterrupt)  # type: ignore[method-assign,assignment,return-value]
    monkeypatch.setattr(harness.time, "sleep", interrupted)


def test_second_sigint_releases_auto_reserved_box(
    harness: Harness, reserve: FakeReserve, monkeypatch: pytest.MonkeyPatch
) -> None:
    _second_interrupt(harness, monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        run(harness, "--", "python", "train.py")
    assert harness.box.state(1001).signals == [("j-1", "INT")]
    assert harness.provider.destroyed == [1001]


def test_second_sigint_keeps_existing_box(
    harness: Harness, box: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _second_interrupt(harness, monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        run(harness, "--on", "ft", "--", "python", "train.py")
    assert harness.provider.destroyed == []


# Auto-reserve.


def test_os_error_before_job_releases_auto_box(harness: Harness, reserve: FakeReserve) -> None:
    def broken(target: SshTarget, job: Job, command: str) -> Job:
        raise OSError("ssh: fork failed")

    harness.box.start_job = broken  # type: ignore[method-assign]
    with pytest.raises(OSError):
        run(harness, "--", "python", "train.py")
    assert harness.provider.destroyed == [1001]


def test_save_failure_after_job_start_releases_auto_box(
    harness: Harness, reserve: FakeReserve, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rig.commands import run as run_cmd

    def broken(*args: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(run_cmd, "save_lease", broken)
    with pytest.raises(OSError):
        run(harness, "--", "python", "train.py")
    assert harness.box.state(1001).jobs["j-1"].state == "running"
    assert harness.provider.destroyed == [1001]


def _fail_finish_save(monkeypatch: pytest.MonkeyPatch) -> None:
    from rig.commands import run as run_cmd

    real = run_cmd.save_lease
    calls: list[int] = []

    def flaky(*args: Any) -> Any:
        calls.append(1)
        if len(calls) > 1:
            raise OSError("disk full")
        return real(*args)

    monkeypatch.setattr(run_cmd, "save_lease", flaky)


def test_save_failure_after_job_exit_releases_auto_box(
    harness: Harness, reserve: FakeReserve, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_finish_save(monkeypatch)
    with pytest.raises(OSError, match="disk full"):
        run(harness, "--", "python", "train.py")
    assert harness.box.state(1001).jobs["j-1"].state == "exited"
    assert harness.provider.destroyed == [1001]


def test_save_failure_after_job_exit_keeps_existing_box(
    harness: Harness, box: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_finish_save(monkeypatch)
    with pytest.raises(OSError, match="disk full"):
        run(harness, "--on", "ft", "--", "python", "train.py")
    assert harness.provider.destroyed == []


def test_os_error_before_job_keeps_existing_box(harness: Harness, box: int) -> None:
    def broken(target: SshTarget, job: Job, command: str) -> Job:
        raise OSError("ssh: fork failed")

    harness.box.start_job = broken  # type: ignore[method-assign]
    with pytest.raises(OSError):
        run(harness, "--on", "ft", "--", "ls")
    assert harness.provider.destroyed == []


def test_auto_run_uses_run_ttl_and_releases(harness: Harness, reserve: FakeReserve) -> None:
    code, data, _ = run(harness, "--", "python", "train.py")
    assert code == 0
    assert reserve.calls[0]["ttl"] == 7200 and reserve.calls[0]["wait"] is True
    assert data["lease"] == "l-0000b001"
    assert data["released"] is True
    assert harness.provider.destroyed == [1001]
    lease = cached(harness, "l-0000b001")
    assert lease.released_here is True
    assert lease.jobs[0].exit == 0


def test_auto_run_ttl_flag_overrides_run_ttl(harness: Harness, reserve: FakeReserve) -> None:
    run(harness, "--ttl", "45m", "--", "ls")
    assert reserve.calls[0]["ttl"] == 2700


def test_auto_run_profile_ttl_does_not_override_run_ttl(
    harness: Harness, reserve: FakeReserve
) -> None:
    harness.env["RIG_TTL"] = "10m"
    run(harness, "--", "ls")
    assert reserve.calls[0]["ttl"] == 7200


def test_auto_run_passes_remote_exit(harness: Harness, reserve: FakeReserve) -> None:
    harness.box.state(1001).job_exit = 2
    code, data, _ = run(harness, "--", "false")
    assert code == 2
    assert data["exit"] == 2 and data["error"] is None and data["released"] is True


def test_auto_run_detach_leaves_box(harness: Harness, reserve: FakeReserve) -> None:
    code, data, _ = run(harness, "--detach", "--", "python", "train.py")
    assert code == 0
    assert data["lease"] == "l-0000b001" and data["job"] == "j-1"
    assert harness.provider.destroyed == []


def test_auto_run_named_leaves_box(harness: Harness, reserve: FakeReserve) -> None:
    code, data, _ = run(harness, "--name", "trainer", "--", "ls")
    assert code == 0
    assert data["released"] is False
    assert harness.provider.destroyed == []
    assert reserve.calls[0]["name"] == "trainer"


def test_auto_run_reuses_named_box(harness: Harness, reserve: FakeReserve, box: int) -> None:
    code, data, _ = run(harness, "--name", "ft", "--", "ls")
    assert code == 0
    assert data["lease"] == "l-0000a001" and data["released"] is False
    assert harness.provider.destroyed == []


def test_auto_run_rejects_no_wait(harness: Harness, reserve: FakeReserve) -> None:
    code, data, _ = run(harness, "--no-wait", "--", "ls")
    assert code == 1 and data["error"] == "invalid_arguments"
    assert reserve.calls == []


def test_auto_run_reserve_failure_propagates(harness: Harness, reserve: FakeReserve) -> None:
    reserve.fail = RigError("budget_exceeded", "over", "release something")
    code, data, _ = run(harness, "--", "ls")
    assert code == 3 and data["error"] == "budget_exceeded"


def test_auto_run_dropped_connection_keeps_box(harness: Harness, reserve: FakeReserve) -> None:
    harness.box.state(1001).job_exit = None
    code, data, _ = run(harness, "--", "ls")
    assert code == 2 and data["error"] == "box_unreachable"
    assert data["released"] is False
    assert harness.provider.destroyed == []


# --sync.


def test_sync_pushes_before_job(harness: Harness, box: int) -> None:
    src = harness.home / "project" / "code"
    src.mkdir()
    code, data, _ = run(harness, "--on", "ft", "--sync", str(src), "--", "python", "train.py")
    assert code == 0
    assert harness.box.rsyncs == [
        (box, True, str(src) + "/", "/workspace/", False,
         [".git", "__pycache__", ".venv", "node_modules"])
    ]
    assert data["job"] == "j-1"


def test_sync_failure_starts_no_job_and_releases_auto_box(
    harness: Harness, reserve: FakeReserve
) -> None:
    src = harness.home / "project" / "code"
    src.mkdir()
    harness.box.rsync_exit = 23
    code, data, _ = run(harness, "--sync", str(src), "--", "python", "train.py")
    assert code == 2 and data["error"] == "sync_failed"
    assert harness.box.state(1001).jobs == {}
    assert harness.provider.destroyed == [1001]


def test_sync_failure_on_existing_box_keeps_it(harness: Harness, box: int) -> None:
    src = harness.home / "project" / "code"
    src.mkdir()
    harness.box.rsync_exit = 12
    code, data, _ = run(harness, "--on", "ft", "--sync", str(src), "--", "ls")
    assert code == 2 and data["error"] == "sync_failed"
    assert harness.box.state(box).jobs == {}
    assert harness.provider.destroyed == []


def test_sync_missing_dir_is_invalid(harness: Harness, reserve: FakeReserve) -> None:
    code, data, _ = run(harness, "--sync", "nope", "--", "ls")
    assert code == 1 and data["error"] == "invalid_arguments"
    assert reserve.calls == []


def test_sync_relative_dir_resolves_from_cwd(harness: Harness, box: int) -> None:
    (harness.home / "project" / "src").mkdir()
    code, _, _ = run(harness, "--on", "ft", "--sync", "src", "--", "ls")
    assert code == 0
    assert harness.box.rsyncs[0][2] == f"{harness.home}/project/src/"


def test_sync_tilde_dir_pushes_the_expanded_path(
    harness: Harness, box: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(harness.home))
    (harness.home / "proj").mkdir()
    code, _, _ = run(harness, "--on", "ft", "--sync", "~/proj", "--", "ls")
    assert code == 0
    assert harness.box.rsyncs[0][2] == f"{harness.home}/proj/"


def test_sync_needs_rsync(harness: Harness, box: int, tmp_path: Path) -> None:
    harness.missing_tools.add("rsync")
    code, data, _ = run(harness, "--on", "ft", "--sync", str(tmp_path), "--", "ls")
    assert code == 1 and data["error"] == "dependency_missing"
