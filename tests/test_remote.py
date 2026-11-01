"""Tests for `SshBox`: ssh argv, the probe, jobs, rsync and interactive ssh.

`FakeRunner` records argv and returns canned results. `LocalRunner` runs the
remote command with the local `sh`, so the box-side scripts run against a temp
directory. A `tmux` stub starts jobs in their own session.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

import pytest

import vasty.remote as remote_module
from vasty.errors import VastyError
from vasty.models import Job
from vasty.remote import (
    JOB_CLAIM_TRIES,
    BoxUnreachableError,
    ExecResult,
    RunMode,
    SshBox,
    SshTarget,
    parse_rsync_version,
    probe_script,
    subprocess_runner,
)

TARGET = SshTarget(instance_id=4242, host="198.51.100.7", port=41022)


def bash_n(script: str) -> None:
    done = subprocess.run(["bash", "-n"], input=script, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@dataclass
class Call:
    argv: list[str]
    input: str | None
    timeout: float | None
    mode: RunMode


@dataclass
class FakeRunner:
    results: list[ExecResult | BaseException] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    stream: str = ""

    def __call__(
        self, argv: list[str], *, input: str | None = None, timeout: float | None = None,
        mode: RunMode = "capture", out: TextIO | None = None,
    ) -> ExecResult:
        self.calls.append(Call(list(argv), input, timeout, mode))
        if mode == "stream" and out is not None:
            out.write(self.stream)
        result = self.results.pop(0) if self.results else ExecResult(0, "", "")
        if isinstance(result, BaseException):
            raise result
        return result


class LocalRunner:
    """Run the remote command of an ssh argv with the local shell."""

    def __init__(self, path: str) -> None:
        self.env = {**os.environ, "PATH": path, "VASTY_POLL": "1", "VASTY_MAX_LOOPS": "1",
                    "VASTY_API": "http://127.0.0.1:9"}

    def __call__(
        self, argv: list[str], *, input: str | None = None, timeout: float | None = None,
        mode: RunMode = "capture", out: TextIO | None = None,
    ) -> ExecResult:
        assert argv[0] == "ssh"
        remote = ["sh", "-c", argv[-1]]
        if mode == "stream":
            return subprocess_runner(remote, mode="stream", out=out)
        done = subprocess.run(remote, input=input, capture_output=True, text=True,
                              timeout=timeout or 30, env=self.env)
        return ExecResult(done.returncode, done.stdout, done.stderr)


def fake_box(
    tmp_path: Path, runner: FakeRunner, key: str | None = "~/.ssh/id_ed25519",
    protect_args: bool = True,
) -> SshBox:
    return SshBox(
        key, str(tmp_path / "state" / "known_hosts"), runner=runner,
        rsync_protect_args=protect_args,
    )


# SSH options and argv.


def test_ssh_options_follow_spec(tmp_path: Path) -> None:
    runner = FakeRunner([ExecResult(0, "hi\n", "")])
    box = fake_box(tmp_path, runner)
    result = box.exec(TARGET, "echo hi", timeout=7)
    assert result == ExecResult(0, "hi\n", "")
    call = runner.calls[0]
    argv = call.argv
    assert argv[0] == "ssh"
    assert argv[-2:] == ["root@198.51.100.7", "echo hi"]
    assert argv[argv.index("-p") + 1] == "41022"
    assert argv[argv.index("-i") + 1] == os.path.expanduser("~/.ssh/id_ed25519")
    opts = [argv[i + 1] for i, a in enumerate(argv) if a == "-o"]
    assert "StrictHostKeyChecking=accept-new" in opts
    assert f"UserKnownHostsFile={tmp_path / 'state' / 'known_hosts'}" in opts
    assert "HostKeyAlias=vast-4242" in opts
    assert "BatchMode=yes" in opts
    assert any(o.startswith("ConnectTimeout=") for o in opts)
    assert call.timeout == 7
    assert (tmp_path / "state").is_dir()


def test_no_key_omits_identity(tmp_path: Path) -> None:
    runner = FakeRunner()
    fake_box(tmp_path, runner, key=None).exec(TARGET, "true")
    assert "-i" not in runner.calls[0].argv


def test_exec_raises_on_ssh_failure_and_timeout(tmp_path: Path) -> None:
    runner = FakeRunner([
        ExecResult(255, "", "ssh: connect to host refused"),
        subprocess.TimeoutExpired(["ssh"], 3),
    ])
    box = fake_box(tmp_path, runner)
    with pytest.raises(BoxUnreachableError, match="refused"):
        box.exec(TARGET, "true")
    with pytest.raises(BoxUnreachableError) as err:
        box.exec(TARGET, "true", timeout=3)
    assert isinstance(err.value.__cause__, subprocess.TimeoutExpired)


def test_exec_passes_remote_exit_codes(tmp_path: Path) -> None:
    runner = FakeRunner([ExecResult(3, "out", "err")])
    assert fake_box(tmp_path, runner).exec(TARGET, "exit 3") == ExecResult(3, "out", "err")


def test_missing_ssh_binary_is_dependency_missing(tmp_path: Path) -> None:
    runner = FakeRunner([FileNotFoundError("ssh")])
    with pytest.raises(VastyError) as err:
        fake_box(tmp_path, runner).exec(TARGET, "true")
    assert err.value.code == "dependency_missing"


def test_interactive_passes_terminal_and_ssh_args(tmp_path: Path) -> None:
    runner = FakeRunner([ExecResult(7, "", "")])
    box = fake_box(tmp_path, runner)
    code = box.interactive(TARGET, None, ["-L", "8000:localhost:8000"])
    assert code == 7
    call = runner.calls[0]
    assert call.mode == "inherit"
    assert "BatchMode=yes" not in call.argv
    assert call.argv[-3:] == ["-L", "8000:localhost:8000", "root@198.51.100.7"]


def test_interactive_command_words(tmp_path: Path) -> None:
    runner = FakeRunner()
    box = fake_box(tmp_path, runner)
    box.interactive(TARGET, ["cat /workspace/.vasty/startup.log | tail"], [])
    box.interactive(TARGET, ["python", "-c", "print('a b')"], [])
    assert runner.calls[0].argv[-1] == "cat /workspace/.vasty/startup.log | tail"
    assert runner.calls[1].argv[-1] == "python -c 'print('\"'\"'a b'\"'\"')'"


# Rsync.


def test_rsync_push_resolves_relative_dest_under_workspace(tmp_path: Path) -> None:
    runner = FakeRunner([ExecResult(0, "", "")])
    box = fake_box(tmp_path, runner)
    code = box.rsync(TARGET, True, "./src/", "out/", True, [".git", "__pycache__"])
    assert code == 0
    call = runner.calls[0]
    argv = call.argv
    assert call.mode == "stderr"
    assert argv[0] == "rsync"
    assert "--delete" in argv
    assert "--exclude=.git" in argv and "--exclude=__pycache__" in argv
    assert argv[-2:] == ["./src/", "root@198.51.100.7:/workspace/out/"]
    ssh_cmd = argv[argv.index("-e") + 1]
    assert ssh_cmd.startswith("ssh ")
    assert "HostKeyAlias=vast-4242" in ssh_cmd and "-p 41022" in ssh_cmd


def test_rsync_pull_keeps_absolute_paths_and_trailing_slash(tmp_path: Path) -> None:
    runner = FakeRunner()
    box = fake_box(tmp_path, runner)
    box.rsync(TARGET, False, "/data/out/", "./out/", False, [])
    argv = runner.calls[0].argv
    assert "--delete" not in argv
    assert argv[-2:] == ["root@198.51.100.7:/data/out/", "./out/"]
    box.rsync(TARGET, False, "ckpt", "./", False, [])
    assert runner.calls[1].argv[-2:] == ["root@198.51.100.7:/workspace/ckpt", "./"]


def test_rsync_returns_its_exit_code(tmp_path: Path) -> None:
    runner = FakeRunner([ExecResult(23, "", "")])
    assert fake_box(tmp_path, runner).rsync(TARGET, True, "a", "b", False, []) == 23


@pytest.mark.parametrize(
    ("dest", "rule"),
    [
        ("./", "/.vasty/***"),
        (".", "/.vasty/***"),
        ("/workspace/", "/.vasty/***"),
        ("/workspace", "/.vasty/***"),
        ("/", "/workspace/.vasty/***"),
        ("sub/", None),
        ("/data/", None),
        ("~/", None),
        ("/workspace/.vasty/", None),
    ],
)
def test_rsync_push_delete_protects_the_state_dir(
    tmp_path: Path, dest: str, rule: str | None
) -> None:
    argv = fake_box(tmp_path, FakeRunner()).rsync_argv(TARGET, True, "./", dest, True, [".git"])
    filters = [a for a in argv if a.startswith("--filter=")]
    if rule is None:
        assert filters == []
    else:
        assert filters == [f"--filter=P {rule}"]
        assert argv.index(filters[0]) < argv.index("-e")


def test_rsync_protects_the_state_dir_only_on_push_with_delete(tmp_path: Path) -> None:
    box = fake_box(tmp_path, FakeRunner())
    pushed = box.rsync_argv(TARGET, True, "./", "/workspace/", False, [])
    pulled = box.rsync_argv(TARGET, False, "/workspace/", "./", True, [])
    assert not any(a.startswith("--filter=") for a in pushed + pulled)


@pytest.mark.parametrize(
    ("dest", "rsync_path"),
    [
        ("/workspace/a/b/", "mkdir -p /workspace/a/b && rsync"),
        ("/workspace/a/b", "mkdir -p /workspace/a && rsync"),
        ("out/run 1/", "mkdir -p '/workspace/out/run 1' && rsync"),
        ("model.bin", "mkdir -p /workspace && rsync"),
        ("~/a/b", "mkdir -p a && rsync"),
        ("/", None),
        ("/data", None),
        ("~", None),
        ("~/", None),
        ("~/a", None),
    ],
)
@pytest.mark.parametrize("protect", [True, False])
def test_rsync_push_creates_the_destination_parent(
    tmp_path: Path, dest: str, rsync_path: str | None, protect: bool
) -> None:
    box = fake_box(tmp_path, FakeRunner(), protect_args=protect)
    argv = box.rsync_argv(TARGET, True, "./", dest, False, [])
    paths = [a for a in argv if a.startswith("--rsync-path")]
    if rsync_path is None:
        assert paths == []
    else:
        assert paths == [f"--rsync-path={rsync_path}"]
        assert argv.index(paths[0]) < argv.index("-e")


def test_rsync_pull_passes_no_rsync_path(tmp_path: Path) -> None:
    box = fake_box(tmp_path, FakeRunner())
    argv = box.rsync_argv(TARGET, False, "/workspace/a/b/", "./out/", False, [])
    assert not any(a.startswith("--rsync-path") for a in argv)


def test_rsync_path_with_a_space_uses_protect_args(tmp_path: Path) -> None:
    box = fake_box(tmp_path, FakeRunner(), protect_args=True)
    argv = box.rsync_argv(TARGET, True, "./my src/", "my dir/", False, [])
    assert argv[3] == "-s"
    assert argv[-2:] == ["./my src/", "root@198.51.100.7:/workspace/my dir/"]
    argv = box.rsync_argv(TARGET, False, "~/a b", "./", False, [])
    assert argv[-2:] == ["root@198.51.100.7:./a b", "./"]


def test_rsync_path_with_a_space_is_quoted_on_old_rsync(tmp_path: Path) -> None:
    box = fake_box(tmp_path, FakeRunner(), protect_args=False)
    argv = box.rsync_argv(TARGET, True, "./my src/", "my dir/", False, [])
    assert "-s" not in argv
    assert argv[-2:] == ["./my src/", "root@198.51.100.7:'/workspace/my dir/'"]
    pulls = {
        "/data/out/": "/data/out/",
        "~": ".",
        "~/a b/": "'./a b/'",
    }
    for src, remote in pulls.items():
        argv = box.rsync_argv(TARGET, False, src, "./", False, [])
        assert argv[-2] == f"root@198.51.100.7:{remote}"


@pytest.mark.parametrize("protect", [True, False])
@pytest.mark.parametrize("path", ["~bob/a b", "~bob", "~$(id)/foo"])
@pytest.mark.parametrize("push", [True, False])
def test_rsync_path_rejects_tilde_user(tmp_path: Path, protect: bool, path: str, push: bool) -> None:
    box = fake_box(tmp_path, FakeRunner(), protect_args=protect)
    src, dest = ("./", path) if push else (path, "./")
    with pytest.raises(VastyError) as err:
        box.rsync_argv(TARGET, push, src, dest, False, [])
    assert err.value.code == "invalid_arguments"
    assert err.value.message == f"Remote path {path} uses ~user."
    assert err.value.hint == "Use an absolute path or ~/."


@pytest.mark.parametrize(
    ("version", "protect"), [((3, 2, 7), True), ((3, 0, 0), True), ((2, 6, 9), False), (None, False)]
)
def test_rsync_picks_protect_args_from_the_local_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    version: tuple[int, int, int] | None, protect: bool,
) -> None:
    calls: list[int] = []

    def fake_version() -> tuple[int, int, int] | None:
        calls.append(1)
        return version

    monkeypatch.setattr(remote_module, "local_rsync_version", fake_version)
    box = SshBox(None, str(tmp_path / "kh"), runner=FakeRunner())
    for _ in range(2):
        argv = box.rsync_argv(TARGET, True, "a", "b c", False, [])
        assert ("-s" in argv) is protect
    assert calls == [1]


def test_parse_rsync_version() -> None:
    assert parse_rsync_version("rsync  version 3.2.7  protocol version 31\n") == (3, 2, 7)
    assert parse_rsync_version("rsync  version v3.4.1  protocol version 32\n") == (3, 4, 1)
    assert parse_rsync_version(
        "openrsync: protocol version 29\nrsync version 2.6.9 compatible\n"
    ) == (2, 6, 9)
    assert parse_rsync_version("rsync version 3.1 protocol\n") == (3, 1, 0)
    assert parse_rsync_version("") is None


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync is not on PATH")
def test_rsync_push_delete_runs_against_a_path_with_a_space(tmp_path: Path) -> None:
    """Run the real local rsync with an ssh stub that runs the remote command in `sh -c`."""
    workspace = tmp_path / "box dir" / "workspace"
    (workspace / ".vasty" / "jobs").mkdir(parents=True)
    (workspace / ".vasty" / "clock").write_text("1\n")
    (workspace / "stale").write_text("old\n")
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "a.py").write_text("print(1)\n")
    stub = tmp_path / "ssh"
    stub.write_text(
        "#!/bin/sh\n"
        "while [ $# -gt 0 ]; do\n"
        '  case "$1" in -p|-o|-i|-l) shift 2;; -*) shift;; *) break;; esac\n'
        "done\n"
        "shift\n"
        'exec sh -c "$*"\n'
    )
    stub.chmod(0o755)
    box = SshBox(
        None, str(tmp_path / "kh"), runner=FakeRunner(), root=f"{workspace}/.vasty",
        workdir=str(workspace),
    )
    argv = box.rsync_argv(TARGET, True, f"{src}/", f"{workspace}/", True, [".git"])
    argv[argv.index("-e") + 1] = str(stub)
    done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert (workspace / "pkg" / "a.py").read_text() == "print(1)\n"
    assert not (workspace / "stale").exists()
    assert (workspace / ".vasty" / "clock").read_text() == "1\n"
    assert (workspace / ".vasty" / "jobs").is_dir()
    argv = box.rsync_argv(TARGET, True, f"{src}/", f"{workspace}/a/b/", False, [".git"])
    argv[argv.index("-e") + 1] = str(stub)
    done = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    assert (workspace / "a" / "b" / "pkg" / "a.py").read_text() == "print(1)\n"


# Probe with a fake runner.


def probe_output(**kw: str) -> str:
    values = {"now": "1000", "clock": "2000", "target": "2000", "rewrite": "none", "guard_file": "1", "guard": "",
              "startup_started": "1", "startup_exit": "0", "alive": "990", "key": "1",
              "unsupported": ""}
    values.update(kw)
    lines = ["vasty_probe=1"] + [f"{k}={v}" for k, v in values.items() if v != "<absent>"]
    return "\n".join(lines + ["vasty_probe=end"]) + "\n"


def test_probe_runs_one_ssh_command_with_timeout(tmp_path: Path) -> None:
    runner = FakeRunner([ExecResult(0, probe_output(), "")])
    result = fake_box(tmp_path, runner).probe(TARGET, 2000)
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call.timeout == 5.0
    assert call.argv[-1] == "sh -s"
    assert "ConnectTimeout=5" in call.argv
    assert call.input == probe_script(2000, "/workspace/.vasty", None)
    assert result.clock_expires == 2000
    assert result.guard_missing == []
    assert result.startup_exit == 0


@pytest.mark.parametrize("result", [
    ExecResult(255, "", "Connection timed out"),
    subprocess.TimeoutExpired(["ssh"], 5),
    ExecResult(0, "vasty_probe=1\nnow=1\n", ""),
    ExecResult(127, "", "sh: not found"),
])
def test_probe_non_answer_raises(tmp_path: Path, result: ExecResult | BaseException) -> None:
    with pytest.raises(BoxUnreachableError):
        fake_box(tmp_path, FakeRunner([result])).probe(TARGET, None)


@pytest.mark.parametrize("kw, missing", [
    ({"alive": "800"}, ["watchdog"]),
    ({"alive": "821"}, []),
    ({"alive": ""}, ["watchdog"]),
    ({"alive": "", "guard_file": "<absent>", "startup_started": "<absent>"}, []),
    ({"guard": "watchdog "}, ["watchdog"]),
    ({"guard": "destroy_key"}, ["destroy_key"]),
    ({"key": "0"}, ["destroy_key"]),
    ({"key": "0", "guard_file": "<absent>", "startup_started": "<absent>"}, []),
    ({"clock": ""}, ["clock_file"]),
    ({"clock": "1500"}, ["clock_file"]),
    ({"clock": "2004"}, []),
    ({"clock": "1994"}, ["clock_file"]),
    ({"clock": "1500", "target": ""}, []),
    ({"guard": "future_layer"}, ["future_layer"]),
])
def test_probe_guard_layers(tmp_path: Path, kw: dict[str, str], missing: list[str]) -> None:
    runner = FakeRunner([ExecResult(0, probe_output(**kw), "")])
    assert fake_box(tmp_path, runner).probe(TARGET, 2000).guard_missing == missing


@pytest.mark.parametrize("kw, guard_file", [
    ({}, True),
    ({"guard_file": "<absent>"}, False),
    ({"guard_file": "0"}, False),
])
def test_probe_reports_the_guard_file(tmp_path: Path, kw: dict[str, str], guard_file: bool) -> None:
    runner = FakeRunner([ExecResult(0, probe_output(**kw), "")])
    assert fake_box(tmp_path, runner).probe(TARGET, 2000).guard_file is guard_file


@pytest.mark.parametrize("kw, adopted", [
    ({}, False),
    ({"adopted": "1"}, True),
])
def test_probe_reports_the_adopted_marker(tmp_path: Path, kw: dict[str, str], adopted: bool) -> None:
    runner = FakeRunner([ExecResult(0, probe_output(**kw), "")])
    assert fake_box(tmp_path, runner).probe(TARGET, 2000).adopted is adopted


def test_probe_reports_unsupported_and_interrupted_startup(tmp_path: Path) -> None:
    out = probe_output(unsupported="apt-get root ", startup_exit="-1")
    result = fake_box(tmp_path, FakeRunner([ExecResult(0, out, "")])).probe(TARGET, None)
    assert result.unsupported == ["apt-get", "root"]
    assert result.startup_exit == -1


def test_generated_scripts_parse() -> None:
    box = SshBox(None, "/tmp/kh")
    bash_n(probe_script(None, "/workspace/.vasty"))
    bash_n(probe_script(123, "/workspace/.vasty"))
    bash_n(probe_script(123, "/workspace/.vasty", 456))
    bash_n(box.start_script(Job("j-1", "python train.py", None, None, "running"), "python 'x'"))
    bash_n(box.attach_script("j-1"))


def test_invalid_ids_and_signals_are_rejected(tmp_path: Path) -> None:
    box = fake_box(tmp_path, FakeRunner())
    with pytest.raises(ValueError):
        box.job_status(TARGET, "j-1; rm -rf /")
    with pytest.raises(ValueError):
        box.signal_job(TARGET, "j-1", "INT; reboot")


def test_attach_returns_exit_code_from_marker(tmp_path: Path) -> None:
    runner = FakeRunner([ExecResult(0, "", "vasty_exit=4\n")], stream="line one\nline two\n")
    out = io.StringIO()
    assert fake_box(tmp_path, runner).attach_job(TARGET, "j-1", out) == 4
    assert out.getvalue() == "line one\nline two\n"
    assert runner.calls[0].mode == "stream"


@pytest.mark.parametrize("result", [
    ExecResult(255, "", "Connection reset"),
    ExecResult(0, "", "vasty_exit=lost\n"),
    ExecResult(0, "", ""),
])
def test_attach_returns_none_when_dropped(tmp_path: Path, result: ExecResult) -> None:
    assert fake_box(tmp_path, FakeRunner([result])).attach_job(TARGET, "j-1", io.StringIO()) is None


def test_subprocess_runner_modes() -> None:
    out = io.StringIO()
    streamed = subprocess_runner(["sh", "-c", "printf 'a\\nb'; echo err >&2; exit 3"],
                                 mode="stream", out=out)
    assert streamed.exit == 3 and out.getvalue() == "a\nb" and streamed.stderr == "err\n"
    captured = subprocess_runner(["sh", "-c", "cat; exit 2"], input="in")
    assert captured == ExecResult(2, "in", "")


# Box-side scripts against a temp directory.


class LocalBox:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.workdir = tmp / "workspace"
        self.root = self.workdir / ".vasty"
        (self.root / "jobs").mkdir(parents=True)
        stubs = tmp / "stubs"
        stubs.mkdir()
        tmux = stubs / "tmux"
        tmux.write_text(
            f"#!{sys.executable}\n"
            "import os, signal, sys\n"
            "args = sys.argv[1:]\n"
            "cwd = args[args.index('-c') + 1]\n"
            "if os.fork() == 0:\n"
            "    os.setsid()\n"
            "    signal.signal(signal.SIGINT, signal.SIG_DFL)\n"
            "    os.chdir(cwd)\n"
            "    fd = os.open(os.devnull, os.O_RDWR)\n"
            "    for n in (0, 1, 2):\n"
            "        os.dup2(fd, n)\n"
            "    os.execvp('sh', ['sh', '-c', args[-1]])\n"
        )
        tmux.chmod(0o755)
        self.box = SshBox(
            None, str(tmp / "state" / "known_hosts"),
            runner=LocalRunner(f"{stubs}:{os.environ['PATH']}"),
            root=str(self.root), workdir=str(self.workdir), tmux=str(tmux), poll=0.05,
            services=False,
        )

    def write(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def read(self, name: str) -> str:
        return (self.root / name).read_text()

    def healthy(self, clock: int) -> None:
        self.write("clock", f"{clock}\n")
        self.write("guard", "\n")
        self.write("startup.started", "1\n")
        self.write("startup.exit", "0\n")
        self.write("env", "CONTAINER_ID=4242\nCONTAINER_API_KEY=key\n")
        (self.root / "alive").touch()

    def wait_exit(self, job_id: str) -> None:
        path = self.root / "jobs" / job_id / "exit"
        deadline = time.monotonic() + 10
        while not path.exists():
            assert time.monotonic() < deadline
            time.sleep(0.05)


@pytest.fixture
def local(tmp_path: Path) -> LocalBox:
    return LocalBox(tmp_path)


def test_probe_reads_a_healthy_box(local: LocalBox) -> None:
    local.healthy(4102444800)
    result = local.box.probe(TARGET, None)
    assert result.clock_expires == 4102444800
    assert result.clock_readable
    assert result.guard_missing == []
    assert result.startup_started and result.startup_exit == 0
    assert result.alive_mtime is not None and abs(result.alive_mtime - time.time()) < 60
    assert result.jobs == []
    assert result.unsupported == []
    assert result.adopted is False


def test_probe_translates_the_label_into_box_time(local: LocalBox) -> None:
    local.healthy(4102444800)
    sent = int(time.time()) - 300
    result = local.box.probe(TARGET, 4102448400, sent)
    written = int(local.read("clock"))
    assert 0 <= written - (4102448400 + 300) <= 5
    assert result.clock_expires == written
    assert result.box_now is not None and abs(result.box_now - time.time()) < 60
    assert result.guard_missing == []


def test_probe_keeps_a_clock_within_tolerance(local: LocalBox) -> None:
    local.healthy(4102444803)
    result = local.box.probe(TARGET, 4102444800, int(time.time()))
    assert local.read("clock") == "4102444803\n"
    assert result.guard_missing == []


def test_probe_rewrites_a_differing_clock(local: LocalBox) -> None:
    local.healthy(4102444800)
    result = local.box.probe(TARGET, 4102448400)
    assert local.read("clock") == "4102448400\n"
    assert result.clock_expires == 4102448400
    assert result.guard_missing == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory modes")
def test_probe_reports_failed_rewrite(local: LocalBox) -> None:
    local.healthy(4102444800)
    local.root.chmod(0o500)
    try:
        result = local.box.probe(TARGET, 4102448400)
    finally:
        local.root.chmod(0o700)
    assert result.clock_expires == 4102444800
    assert result.guard_missing == ["clock_file"]


def test_probe_reports_unreadable_clock(local: LocalBox) -> None:
    local.healthy(0)
    local.write("clock", "not a number\n")
    result = local.box.probe(TARGET, None)
    assert not result.clock_readable and result.clock_expires is None
    assert result.guard_missing == ["clock_file"]


def test_probe_reports_stale_alive_and_missing_key(local: LocalBox) -> None:
    local.healthy(4102444800)
    old = time.time() - 300
    os.utime(local.root / "alive", (old, old))
    local.write("env", "CONTAINER_ID=4242\n")
    local.write("unsupported", "apt-get\n")
    result = local.box.probe(TARGET, 4102444800)
    assert result.guard_missing == ["watchdog", "destroy_key"]
    assert result.unsupported == ["apt-get"]


def test_probe_reads_job_records(local: LocalBox) -> None:
    local.healthy(4102444800)
    live = subprocess.Popen(["sleep", "30"])
    dead = subprocess.Popen(["true"])
    dead.wait()
    try:
        local.write("jobs/j-1/cmd", "python train.py --lr 3e-4")
        local.write("jobs/j-1/started", "100\n")
        local.write("jobs/j-1/pid", f"{live.pid}\n")
        local.write("jobs/j-1/kind", "run\n")
        local.write("jobs/j-2/cmd", "python eval.py")
        local.write("jobs/j-2/started", "200\n")
        local.write("jobs/j-2/exit", "2\n")
        local.write("jobs/j-2/finished", "260\n")
        local.write("jobs/j-3/cmd", "vllm")
        local.write("jobs/j-3/started", "300\n")
        local.write("jobs/j-3/pid", f"{dead.pid}\n")
        local.write("jobs/j-4/cmd", "vllm serve")
        local.write("jobs/j-4/started", "400\n")
        local.write("jobs/j-4/pid", f"{live.pid}\n")
        local.write("jobs/j-4/kind", "serve\n")
        local.write("jobs/j-4/port", "8000\n")
        result = local.box.probe(TARGET, None)
    finally:
        live.kill()
        live.wait()
    jobs = {j.id: j for j in result.jobs}
    if not Path(f"/proc/{live.pid}").exists():
        assert jobs["j-1"].state == "running"
        assert jobs["j-4"].state == "serving"
    assert jobs["j-1"].cmd == "python train.py --lr 3e-4"
    assert jobs["j-1"].started_at == 100 and jobs["j-1"].pid == live.pid
    assert jobs["j-1"].log_path == f"{local.root}/jobs/j-1/log"
    assert jobs["j-2"].state == "exited" and jobs["j-2"].exit == 2
    assert jobs["j-2"].finished_at == 260
    assert jobs["j-3"].state == "unknown" and jobs["j-3"].exit is None
    assert jobs["j-4"].kind == "serve" and jobs["j-4"].port == 8000


def test_write_clock_replaces_the_file(local: LocalBox) -> None:
    local.box.write_clock(TARGET, 4102444800)
    assert local.read("clock") == "4102444800\n"
    assert not any(p.name.startswith("clock.tmp") for p in local.root.iterdir())


def test_write_clock_translates_into_box_time(local: LocalBox) -> None:
    local.box.write_clock(TARGET, 4102444800, int(time.time()) + 120)
    written = int(local.read("clock"))
    assert -5 <= written - (4102444800 - 120) <= 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory modes")
def test_write_clock_failure_raises(local: LocalBox) -> None:
    local.root.chmod(0o500)
    try:
        with pytest.raises(BoxUnreachableError):
            local.box.write_clock(TARGET, 4102444800)
    finally:
        local.root.chmod(0o700)


def test_adopt_returns_missing_layers(local: LocalBox) -> None:
    missing = local.box.adopt(TARGET, 4102444800)
    assert "destroy_key" in missing
    assert local.read("clock") == "4102444800\n"
    assert (local.root / "watchdog.sh").exists()
    result = local.box.probe(TARGET, 4102444800)
    assert result.startup_exit == 0
    assert result.adopted is True


def test_job_lifecycle(local: LocalBox) -> None:
    job = Job("j-1", "demo", None, None, "running")
    started = local.box.start_job(TARGET, job, "pwd; echo out; echo err >&2; exit 4")
    assert started.state == "running"
    assert started.pid is not None and started.started_at is not None
    assert started.log_path == f"{local.root}/jobs/j-1/log"
    local.wait_exit("j-1")
    status = local.box.job_status(TARGET, "j-1")
    assert status.state == "exited" and status.exit == 4 and status.cmd == "demo"
    log = local.read("jobs/j-1/log").splitlines()
    assert log[0] in (str(local.workdir), str(local.workdir.resolve()))
    assert log[1:] == ["out", "err"]
    assert local.box.log_tail(TARGET, "j-1", 2) == ["out", "err"]


def test_start_job_claims_the_next_free_id(local: LocalBox) -> None:
    (local.root / "jobs" / "j-2").mkdir()
    job = Job("j-1", "demo", None, None, "running")
    assert local.box.start_job(TARGET, job, "true").id == "j-1"
    again = local.box.start_job(TARGET, job, "true")
    assert again.id == "j-3"
    assert again.log_path == f"{local.root}/jobs/j-3/log"
    assert local.read("jobs/j-3/cmd") == "demo"
    assert not (local.root / "jobs" / "j-2" / "started").exists()


def test_start_job_with_a_taken_custom_id_is_refused(local: LocalBox) -> None:
    job = Job("custom", "demo", None, None, "running")
    local.box.start_job(TARGET, job, "true")
    with pytest.raises(VastyError, match="already exists"):
        local.box.start_job(TARGET, job, "true")


def test_start_job_gives_up_after_the_claim_limit(local: LocalBox) -> None:
    for n in range(1, JOB_CLAIM_TRIES + 1):
        (local.root / "jobs" / f"j-{n}").mkdir()
    job = Job("j-1", "demo", None, None, "running")
    with pytest.raises(VastyError, match=f"Job j-{JOB_CLAIM_TRIES} already exists"):
        local.box.start_job(TARGET, job, "true")


def test_start_job_keeps_other_mkdir_failures(local: LocalBox) -> None:
    (local.root / "jobs").rmdir()
    (local.root / "jobs").write_text("")
    job = Job("j-1", "demo", None, None, "running")
    with pytest.raises(VastyError, match="Could not start job j-1") as caught:
        local.box.start_job(TARGET, job, "true")
    assert "already exists" not in str(caught.value)


def test_start_script_claims_the_job_dir_with_mkdir(tmp_path: Path) -> None:
    box = fake_box(tmp_path, FakeRunner())
    script = box.start_script(Job("j-1", "demo", None, None, "running"), "true")
    lines = script.splitlines()
    assert lines[1] == "mkdir -p /workspace/.vasty/jobs || exit 3"
    assert lines[2] == 'mkdir "$J" || { [ -e "$J" ] && echo vasty_job=exists; exit 3; }'
    bash_n(script)


def test_serve_job_records_kind_and_port(local: LocalBox) -> None:
    job = Job("j-2", "vllm", None, None, "serving", kind="serve", port=8000)
    started = local.box.start_job(TARGET, job, "sleep 30")
    try:
        assert started.state == "serving"
        assert local.read("jobs/j-2/kind").strip() == "serve"
        assert local.read("jobs/j-2/port").strip() == "8000"
    finally:
        local.box.signal_job(TARGET, "j-2", "TERM")
        local.wait_exit("j-2")


def test_attach_streams_log_and_returns_exit(local: LocalBox) -> None:
    job = Job("j-1", "demo", None, None, "running")
    local.box.start_job(TARGET, job, "echo one; sleep 0.3; printf two; exit 5")
    out = io.StringIO()
    assert local.box.attach_job(TARGET, "j-1", out) == 5
    assert out.getvalue() == "one\ntwo"


def test_signal_reaches_the_process_group(local: LocalBox) -> None:
    job = Job("j-1", "demo", None, None, "running")
    local.box.start_job(TARGET, job, "sleep 30")
    local.box.signal_job(TARGET, "j-1", "SIGINT")
    local.wait_exit("j-1")
    assert int(local.read("jobs/j-1/exit")) == 130
    assert local.box.job_status(TARGET, "j-1").exit == 130


def test_log_tail_defaults_to_newest_job(local: LocalBox) -> None:
    local.write("jobs/j-1/started", "100\n")
    local.write("jobs/j-1/log", "old\n")
    local.write("jobs/j-2/started", "200\n")
    local.write("jobs/j-2/log", "a\nb\nc\n")
    assert local.box.log_tail(TARGET, None, 2) == ["b", "c"]
    assert local.box.log_tail(TARGET, "j-1", 5) == ["old"]
    assert local.box.log_tail(TARGET, "j-9", 5) == []


def test_log_tail_with_no_jobs(local: LocalBox) -> None:
    assert local.box.log_tail(TARGET, None, 10) == []
