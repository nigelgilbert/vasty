from __future__ import annotations

import json
from typing import Any

import pytest

from fakes import NOW, FakeReserve, Harness, add_lease
from vasty.commands import serve
from vasty.errors import VastyError
from vasty.models import Job
from vasty.remote import BoxUnreachableError, ExecResult, SshTarget

QWEN = "Qwen/Qwen3-14B-AWQ"
VLLM_PROFILE = '[profiles.vllm]\nimage = "vllm/vllm-openai:v0.32.0"\nvram = 24\ncuda = 13\n'
KEY = "vasty-" + "ab" * 32
NO_VLLM = ExecResult(1, "", "")


def run_serve(harness: Harness, *argv: str) -> tuple[int, dict[str, Any], str]:
    code, out, err = harness.run("serve", *argv)
    return code, json.loads(out), err


def write_user(harness: Harness, text: str) -> None:
    path = harness.home / ".config" / "vasty" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def box(harness: Harness) -> int:
    return add_lease(harness, label={"name": "ft"}).id


@pytest.fixture
def started(harness: Harness) -> list[tuple[Job, str]]:
    calls: list[tuple[Job, str]] = []
    real = harness.box.start_job

    def start(target: SshTarget, job: Job, command: str) -> Job:
        calls.append((job, command))
        return real(target, job, command)

    harness.box.start_job = start  # type: ignore[method-assign]
    return calls


@pytest.fixture
def reserve(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> FakeReserve:
    return FakeReserve(harness).install(monkeypatch)


def test_serve_on_box(harness: Harness, box: int, started: list[tuple[Job, str]]) -> None:
    code, data, _ = run_serve(harness, "--on", "ft", "--model", QWEN)
    assert code == 0
    assert data == {
        "lease": "l-0000a001", "job": "j-1", "model": QWEN,
        "url": "http://198.51.100.9:40080/v1", "api_key": KEY,
        "expires_at": "2026-10-29T01:50:00Z", "warnings": [], "swept": [],
    }
    assert harness.box.state(box).execs == ["command -v vllm"]
    job, command = started[0]
    assert (job.kind, job.port, job.state) == ("serve", 8000, "serving")
    assert command == (
        f"export VLLM_API_KEY={KEY}\nvllm serve {QWEN} --host 0.0.0.0 --port 8000"
    )
    assert "--api-key" not in command
    assert KEY not in job.cmd
    assert job.cmd == f"vllm serve {QWEN} --host 0.0.0.0 --port 8000"
    assert harness.http_calls == ["http://198.51.100.9:40080/v1/models"]
    assert harness.http_headers == [{"Authorization": f"Bearer {KEY}"}]
    lease = harness.context().cache.load().leases["l-0000a001"]
    assert [(j.id, j.kind) for j in lease.jobs] == [("j-1", "serve")]


def test_serve_polls_until_200(harness: Harness, box: int) -> None:
    harness.http_statuses = [0, 503, 401]
    start = harness.time.mono_now
    code, _, _ = run_serve(harness, "--on", "ft", "--model", QWEN)
    assert code == 0
    assert len(harness.http_calls) == 4
    assert harness.time.mono_now - start == 3 * serve.POLL_INTERVAL_S


def test_serve_fresh_key_per_job(harness: Harness, box: int) -> None:
    harness.hex_values = ["11" * 32, "22" * 32]
    _, first, _ = run_serve(harness, "--on", "ft", "--model", QWEN)
    _, second, _ = run_serve(harness, "--on", "ft", "--model", QWEN)
    assert first["api_key"] == "vasty-" + "11" * 32
    assert second["api_key"] == "vasty-" + "22" * 32
    assert (first["job"], second["job"]) == ("j-1", "j-2")


def test_serve_job_exit_before_ready_is_serve_failed(harness: Harness, box: int) -> None:
    harness.http_status = 0

    def exited(target: SshTarget, job_id: str) -> Job:
        job = harness.box.state(box).jobs[job_id]
        job.exit, job.state = 1, "exited"
        return job

    harness.box.job_status = exited  # type: ignore[method-assign]
    code, data, _ = run_serve(harness, "--on", "ft", "--model", QWEN)
    assert code == 2 and data["error"] == "serve_failed"
    assert "exited 1" in data["message"]
    assert box in harness.provider.instances


def test_serve_deadline_is_serve_failed(harness: Harness, box: int) -> None:
    harness.http_status = 503
    code, data, _ = run_serve(harness, "--on", "ft", "--model", QWEN)
    assert code == 2 and data["error"] == "serve_failed"
    assert harness.box.state(box).signals == [("j-1", "TERM")]


def test_serve_vllm_missing_on_box(
    harness: Harness, box: int, started: list[tuple[Job, str]]
) -> None:
    harness.box.state(box).exec_results["command -v vllm"] = NO_VLLM
    code, data, _ = run_serve(harness, "--on", "ft", "--model", QWEN)
    assert code == 1
    assert data == {
        "error": "vllm_missing",
        "message": "Lease l-0000a001 has no vllm on PATH.",
        "hint": f"Reserve with a vLLM image: vasty serve --model {QWEN} "
                "--image vllm/vllm-openai:v0.32.0.",
    }
    assert started == []
    assert box in harness.provider.instances
    assert harness.provider.destroyed == []


def test_serve_vllm_present_starts_job(
    harness: Harness, box: int, started: list[tuple[Job, str]]
) -> None:
    harness.box.state(box).exec_results["command -v vllm"] = ExecResult(0, "/usr/bin/vllm\n", "")
    code, _, _ = run_serve(harness, "--on", "ft", "--model", QWEN)
    assert code == 0
    assert harness.box.state(box).execs[0] == "command -v vllm"
    assert len(started) == 1


def test_serve_warnings_use_the_clock_after_bring_up(harness: Harness, box: int) -> None:
    real = harness.box.exec

    def slow(target: SshTarget, command: str, timeout: float | None = None) -> ExecResult:
        harness.time.advance(2800)
        return real(target, command, timeout)

    harness.box.exec = slow  # type: ignore[method-assign]
    code, data, _ = run_serve(harness, "--on", "ft", "--model", QWEN)
    assert code == 0
    assert [w["code"] for w in data["warnings"]] == ["expiring_with_running_job"]


def test_serve_on_unknown_model_serves_path(
    harness: Harness, box: int, started: list[tuple[Job, str]]
) -> None:
    code, data, _ = run_serve(harness, "--on", "ft", "--model", "./out/checkpoint")
    assert code == 0
    assert data["model"] == "./out/checkpoint"
    assert started[0][1].splitlines()[1].startswith("vllm serve ./out/checkpoint ")


# Passthrough after `--`.


def test_serve_passes_flags_after_dashes(
    harness: Harness, box: int, started: list[tuple[Job, str]]
) -> None:
    code, _, _ = run_serve(
        harness, "--on", "ft", "--model", QWEN, "--", "--max-model-len", "16384",
        "--gpu-memory-utilization=0.85",
    )
    assert code == 0
    job, command = started[0]
    tail = " --max-model-len 16384 --gpu-memory-utilization=0.85"
    assert command == f"export VLLM_API_KEY={KEY}\n{job.cmd}"
    assert job.cmd == f"vllm serve {QWEN} --host 0.0.0.0 --port 8000" + tail
    lease = harness.context().cache.load().leases["l-0000a001"]
    assert lease.jobs[0].cmd == job.cmd


def test_serve_auto_reserve_passes_flags_after_dashes(
    harness: Harness, reserve: FakeReserve, started: list[tuple[Job, str]]
) -> None:
    code, _, _ = run_serve(harness, "--model", QWEN, "--", "--max-model-len", "16384")
    assert code == 0
    assert started[0][1].endswith("--max-model-len 16384")
    assert started[0][0].cmd.endswith("--max-model-len 16384")


def test_serve_quotes_passthrough_tokens(
    harness: Harness, box: int, started: list[tuple[Job, str]]
) -> None:
    run_serve(harness, "--on", "ft", "--model", QWEN, "--", "--chat-template", "a b; rm -rf /")
    assert started[0][1].endswith("--chat-template 'a b; rm -rf /'")


@pytest.mark.parametrize(
    "extra",
    [
        ["--port", "9000"],
        ["--host", "0.0.0.0"],
        ["--api-key=k"],
        ["--api-key", "k"],
        ["--port=9000"],
        ["--max-model-len", "16384", "--api_key", "k"],
    ],
)
@pytest.mark.parametrize("on", [True, False])
def test_serve_rejects_owned_flags_after_dashes(
    harness: Harness, reserve: FakeReserve, started: list[tuple[Job, str]],
    extra: list[str], on: bool,
) -> None:
    argv = ["--on", "ft"] if on else []
    code, data, _ = run_serve(harness, *argv, "--model", QWEN, "--", *extra)
    assert code == 1
    assert data["error"] == "invalid_arguments"
    assert harness.provider.calls == []
    assert reserve.calls == []
    assert started == []


def test_serve_bind_local(harness: Harness, box: int, started: list[tuple[Job, str]]) -> None:
    state = harness.box.state(box)
    state.exec_results["curl"] = ExecResult(0, "200", "")
    code, data, _ = run_serve(harness, "--on", "ft", "--model", QWEN, "--bind-local")
    assert code == 0
    assert data["url"] == "http://127.0.0.1:8000/v1"
    assert "--host 127.0.0.1" in started[0][1]
    assert harness.http_calls == []
    assert state.execs[1].startswith("curl ")
    assert f"Authorization: Bearer {KEY}" in state.execs[1]


def test_serve_port_mapping_missing(harness: Harness) -> None:
    add_lease(harness, label={"name": "ft"}, ports={22: 40022})
    code, data, _ = run_serve(harness, "--on", "ft", "--model", QWEN)
    assert code == 2 and data["error"] == "port_mapping_missing"


def test_serve_human_mode_notes_key_once(harness: Harness, box: int) -> None:
    code, out, _ = harness.run("serve", "--on", "ft", "--model", QWEN, "--plain")
    assert code == 0
    assert KEY in out
    assert "will not be shown again" in out


def test_serve_on_orphan(harness: Harness) -> None:
    harness.provider.add_instance(id=55120)
    code, data, _ = run_serve(harness, "--on", "i-55120", "--model", QWEN)
    assert code == 1 and data["error"] == "orphan_unmanaged"


# Auto-reserve.


def test_serve_auto_reserves_with_profile_hardware(
    harness: Harness, reserve: FakeReserve
) -> None:
    write_user(harness, VLLM_PROFILE)
    code, data, _ = run_serve(harness, "--profile", "vllm", "--model", QWEN)
    assert code == 0
    call = reserve.calls[0]
    assert (call["ttl"], call["vram"], call["image"]) == (7200, 24.0, "vllm/vllm-openai:v0.32.0")
    assert data["lease"] == "l-0000b001"
    assert data["url"] == "http://198.51.100.7:41080/v1"
    assert harness.provider.destroyed == []


def test_serve_flags_beat_profile(harness: Harness, reserve: FakeReserve) -> None:
    write_user(harness, VLLM_PROFILE)
    run_serve(harness, "--profile", "vllm", "--model", QWEN, "--vram", "48", "--gpu", "L40S",
              "--ttl", "1h")
    call = reserve.calls[0]
    assert (call["vram"], call["gpu"], call["image"], call["ttl"]) == (
        48.0, "L40S", "vllm/vllm-openai:v0.32.0", 3600
    )


def test_serve_reads_stdin_json_like_reserve(harness: Harness, reserve: FakeReserve) -> None:
    code, out, _ = harness.run(
        "serve", "--model", QWEN, "--config", "-",
        stdin='{"vram": 24, "image": "vllm/vllm-openai:v0.32.0"}',
    )
    assert code == 0, out
    call = reserve.calls[0]
    assert (call["vram"], call["image"]) == (24.0, "vllm/vllm-openai:v0.32.0")


def test_serve_name_reuse_checks_only_given_flags(harness: Harness, box: int) -> None:
    code, data, _ = run_serve(harness, "--model", QWEN, "--name", "ft")
    assert code == 0
    assert data["lease"] == "l-0000a001"
    assert not [w for w in data.get("warnings", []) if w["code"] == "flag_mismatch"]
    code, data, _ = run_serve(harness, "--model", QWEN, "--name", "ft", "--vram", "48")
    assert code == 0
    mismatch = [w for w in data["warnings"] if w["code"] == "flag_mismatch"]
    assert len(mismatch) == 1
    assert mismatch[0]["message"].endswith("differs from --vram")


def test_bare_serve_reserves_default_image_and_releases_without_vllm(
    harness: Harness, reserve: FakeReserve, started: list[tuple[Job, str]]
) -> None:
    harness.box.state(1001).exec_results["command -v vllm"] = NO_VLLM
    code, data, _ = run_serve(harness, "--model", "org/mystery")
    assert code == 1 and data["error"] == "vllm_missing"
    assert "--image vllm/vllm-openai:v0.32.0" in data["hint"]
    assert "profile" not in data["hint"]
    assert reserve.calls[0]["image"] == "vasty/base:cuda12.4"
    assert started == []
    assert harness.provider.destroyed == [1001]


def test_serve_vllm_missing_releases_reserved_box(
    harness: Harness, reserve: FakeReserve, started: list[tuple[Job, str]]
) -> None:
    harness.box.state(1001).exec_results["command -v vllm"] = NO_VLLM
    code, data, _ = run_serve(harness, "--model", QWEN)
    assert code == 1 and data["error"] == "vllm_missing"
    assert started == []
    assert harness.provider.destroyed == [1001]


def test_serve_os_error_releases_reserved_box(harness: Harness, reserve: FakeReserve) -> None:
    harness.box.state(1001).exec_errors["command -v vllm"] = OSError("ssh: fork failed")
    with pytest.raises(OSError):
        run_serve(harness, "--model", QWEN)
    assert harness.provider.destroyed == [1001]


@pytest.mark.parametrize("on", [True, False])
def test_serve_preflight_box_unreachable(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, started: list[tuple[Job, str]], on: bool
) -> None:
    if on:
        box_id = add_lease(harness, label={"name": "ft"}).id
        argv: tuple[str, ...] = ("--on", "ft")
    else:
        FakeReserve(harness).install(monkeypatch)
        box_id = 1001
        argv = ()
    unreachable = BoxUnreachableError("The box did not answer within 30s.")
    harness.box.state(box_id).exec_errors["command -v vllm"] = unreachable
    code, data, _ = run_serve(harness, *argv, "--model", QWEN)
    assert code == 2 and data["error"] == "box_unreachable"
    assert started == []
    assert harness.provider.destroyed == ([] if on else [1001])


def test_serve_failure_keeps_reused_box(harness: Harness, reserve: FakeReserve, box: int) -> None:
    harness.box.state(box).exec_results["command -v vllm"] = NO_VLLM
    code, data, _ = run_serve(harness, "--model", QWEN, "--name", "ft")
    assert code == 1 and data["error"] == "vllm_missing"
    assert harness.provider.destroyed == []


@pytest.mark.parametrize("ok", [True, False])
def test_serve_reports_reserve_wait_sweep(
    harness: Harness, reserve: FakeReserve, monkeypatch: pytest.MonkeyPatch, ok: bool
) -> None:
    def wait(ctx: Any, args: Any, snap: Any, *, ttl: int, wait: bool = True) -> Any:
        add_lease(harness, "l-0000a009", label={"name": "old", "expires": NOW - 10})
        return reserve(ctx, args, snap, ttl=ttl, wait=wait)

    monkeypatch.setattr("vasty.commands.reserve.reserve_lease", wait)
    if not ok:
        harness.provider.fail["destroy"] = VastyError("provider_error", "boom", "retry")
    code, data, _ = run_serve(harness, "--model", QWEN)
    assert code == 0
    error = None if ok else "provider_error"
    assert [(s["lease"], s["name"], s["ok"], s["error"]) for s in data["swept"]] == [
        ("l-0000a009", "old", ok, error)
    ]
    assert (1001 in harness.provider.destroyed) is ok


def test_serve_failure_reports_failed_sweep_on_stderr(harness: Harness, box: int) -> None:
    add_lease(harness, "l-0000a009", label={"name": "old", "expires": NOW - 10})
    harness.provider.fail["destroy"] = VastyError("provider_error", "boom", "retry")
    harness.box.state(box).exec_results["command -v vllm"] = NO_VLLM
    code, data, err = run_serve(harness, "--on", "ft", "--model", QWEN)
    assert code == 1 and data["error"] == "vllm_missing"
    assert "swept" not in data
    assert err.splitlines() == [
        "vasty: SWEPT  l-0000a009 old  expired 2026-10-29T00:59:50Z  destroy failed (provider_error)"
    ]

