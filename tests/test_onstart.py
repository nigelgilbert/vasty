"""Tests for the onstart payload, startup wrapper, adopt script and watchdog.

The generated scripts run locally in a temp directory. Stubs on PATH replace
`date`, `sleep` and `curl` for the watchdog so time and the destroy call are
under test control.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from rig.errors import RigError
from rig.onstart import (
    IMAGE_WATCHDOG,
    ONSTART_LIMIT,
    STARTUP_INTERRUPTED,
    adopt_script,
    build_onstart,
    build_payload,
    decode_onstart,
    watchdog_script,
)


def bash_n(script: str) -> None:
    done = subprocess.run(["bash", "-n"], input=script, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def wait_for(path: Path, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists():
        assert time.monotonic() < deadline, f"{path} did not appear"
        time.sleep(0.05)


def write_exe(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o755)


# Watchdog.


class Watchdog:
    """The watchdog script in a temp `.rig` root with stubbed `date`, `sleep` and `curl`."""

    def __init__(self, tmp: Path) -> None:
        self.root = tmp / "rig"
        self.root.mkdir()
        self.stubs = tmp / "stubs"
        self.stubs.mkdir()
        self.script = tmp / "watchdog.sh"
        self.script.write_text(watchdog_script())
        write_exe(self.stubs / "date", '#!/bin/sh\ncat "$STUB_DIR/now"\n')
        write_exe(
            self.stubs / "sleep",
            "#!/bin/sh\n"
            'echo "$PPID $1" >>"$STUB_DIR/sleeps"\n'
            "n=$(wc -l <\"$STUB_DIR/sleeps\" | tr -d ' ')\n"
            '[ -x "$STUB_DIR/hook$n" ] && "$STUB_DIR/hook$n"\n'
            '/bin/sleep "${STUB_SLEEP:-0}"\n',
        )
        write_exe(
            self.stubs / "curl",
            "#!/bin/sh\n"
            "printf '%s\\037' \"$@\" >>\"$STUB_DIR/curl.log\"; echo >>\"$STUB_DIR/curl.log\"\n"
            'exit "$(cat "$STUB_DIR/curl_exit" 2>/dev/null || echo 0)"\n',
        )
        self.set_now(1000)

    def set_now(self, now: int) -> None:
        (self.stubs / "now").write_text(f"{now}\n")

    def set_clock(self, value: str) -> None:
        (self.root / "clock").write_text(value)

    def set_env(self, cid: str | None = "123", key: str | None = "k-secret") -> None:
        lines = []
        if cid is not None:
            lines.append(f"CONTAINER_ID={cid}")
        if key is not None:
            lines.append(f"CONTAINER_API_KEY={key}")
        (self.root / "env").write_text("\n".join(lines) + "\n")

    def hook(self, n: int, body: str) -> None:
        write_exe(self.stubs / f"hook{n}", f"#!/bin/sh\n{body}\n")

    def env(self, max_loops: int, stub_sleep: float = 0.0) -> dict[str, str]:
        return {
            "PATH": f"{self.stubs}:{os.environ['PATH']}",
            "RIG_ROOT": str(self.root),
            "RIG_MAX_LOOPS": str(max_loops),
            "STUB_DIR": str(self.stubs),
            "STUB_SLEEP": str(stub_sleep),
        }

    def run(self, max_loops: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.script)], env=self.env(max_loops), capture_output=True,
            text=True, timeout=30,
        )

    def start(self, max_loops: int = 0, stub_sleep: float = 0.05) -> subprocess.Popen[str]:
        return subprocess.Popen(
            ["bash", str(self.script)], env=self.env(max_loops, stub_sleep),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
        )

    def curl_calls(self) -> list[list[str]]:
        log = self.stubs / "curl.log"
        if not log.exists():
            return []
        return [line.split("\x1f")[:-1] for line in log.read_text().splitlines()]

    def sleeps(self) -> list[tuple[int, str]]:
        log = self.stubs / "sleeps"
        if not log.exists():
            return []
        out = []
        for line in log.read_text().splitlines():
            pid, arg = line.split(" ")
            out.append((int(pid), arg))
        return out

    def sleep_args(self) -> list[str]:
        return [arg for _, arg in self.sleeps()]


@pytest.fixture
def wd(tmp_path: Path) -> Watchdog:
    return Watchdog(tmp_path)


def test_watchdog_script_parses() -> None:
    bash_n(watchdog_script())


def test_expired_clock_destroys_once(wd: Watchdog) -> None:
    wd.set_env()
    wd.set_clock("990\n")
    done = wd.run(max_loops=4)
    assert done.returncode == 0, done.stderr
    calls = wd.curl_calls()
    assert len(calls) == 1
    args = calls[0]
    assert args[args.index("-X") + 1] == "DELETE"
    assert "Authorization: Bearer k-secret" in args
    assert args[-1] == "https://console.vast.ai/api/v0/instances/123/"
    assert "destroy accepted" in done.stdout


def test_clock_equal_to_now_destroys_at_once(wd: Watchdog) -> None:
    wd.set_env()
    wd.set_clock("1000\n")
    wd.run(max_loops=1)
    assert len(wd.curl_calls()) == 1


def test_future_clock_sleeps_until_expiry(wd: Watchdog) -> None:
    wd.set_env()
    wd.set_clock("1045\n")
    wd.run(max_loops=1)
    assert wd.curl_calls() == []
    assert wd.sleep_args() == ["45"]


def test_far_clock_sleeps_at_most_60s(wd: Watchdog) -> None:
    wd.set_env()
    wd.set_clock("5000\n")
    wd.run(max_loops=2)
    assert wd.curl_calls() == []
    assert wd.sleep_args() == ["60", "60"]


def test_late_extend_is_honored(wd: Watchdog) -> None:
    wd.set_env()
    wd.set_clock("1030\n")
    wd.hook(1, f'echo 1030 >"$STUB_DIR/now"; echo 2000 >{wd.root}/clock')
    wd.run(max_loops=2)
    assert wd.curl_calls() == []
    assert wd.sleep_args() == ["30", "60"]


def test_clock_reached_after_sleep_destroys(wd: Watchdog) -> None:
    wd.set_env()
    wd.set_clock("1030\n")
    wd.hook(1, 'echo 1030 >"$STUB_DIR/now"')
    wd.run(max_loops=2)
    assert len(wd.curl_calls()) == 1


def test_failed_destroy_backs_off_capped_at_60s(wd: Watchdog) -> None:
    wd.set_env()
    wd.set_clock("900\n")
    (wd.stubs / "curl_exit").write_text("22\n")
    wd.run(max_loops=8)
    assert len(wd.curl_calls()) == 8
    assert wd.sleep_args() == ["2", "4", "8", "16", "32", "60", "60", "60"]


def test_unreadable_clock_is_logged_and_reread_within_60s(wd: Watchdog) -> None:
    wd.set_env()
    wd.set_clock("garbage\n")
    done = wd.run(max_loops=2)
    assert "clock file unreadable" in done.stdout
    assert wd.curl_calls() == []
    assert all(int(arg) <= 60 for arg in wd.sleep_args())


def test_missing_clock_file_is_unreadable(wd: Watchdog) -> None:
    wd.set_env()
    done = wd.run(max_loops=1)
    assert "clock file unreadable" in done.stdout
    assert wd.curl_calls() == []


def test_missing_key_reports_destroy_key(wd: Watchdog) -> None:
    wd.set_env(key=None)
    wd.set_clock("900\n")
    done = wd.run(max_loops=2)
    assert wd.curl_calls() == []
    assert "destroy_key" in (wd.root / "guard").read_text().split()
    assert "no destroy key" in done.stdout


def test_missing_env_file_reports_destroy_key(wd: Watchdog) -> None:
    wd.set_clock("5000\n")
    wd.run(max_loops=1)
    assert (wd.root / "guard").read_text().split() == ["destroy_key"]


def test_watchdog_touches_alive_and_releases_lock(wd: Watchdog) -> None:
    wd.set_env()
    wd.set_clock("5000\n")
    wd.run(max_loops=1)
    assert (wd.root / "alive").exists()
    assert not (wd.root / "watchdog.lock").exists()


def test_lock_blocks_a_second_copy(wd: Watchdog) -> None:
    wd.set_env()
    wd.set_clock("5000\n")
    first = wd.start()
    try:
        deadline = time.monotonic() + 10
        while not wd.sleeps():
            assert time.monotonic() < deadline
            time.sleep(0.02)
        second = subprocess.Popen(
            ["bash", str(wd.script)], env=wd.env(1), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        assert second.wait(timeout=10) == 0
        assert second.pid not in {pid for pid, _ in wd.sleeps()}
        assert first.poll() is None
    finally:
        first.terminate()
        first.wait(timeout=10)


def test_live_lock_holder_keeps_lock(wd: Watchdog) -> None:
    holder = subprocess.Popen(["bash", "-c", "sleep 30; :", "watchdog"])
    try:
        (wd.root / "watchdog.lock").mkdir()
        (wd.root / "watchdog.lock" / "pid").write_text(f"{holder.pid}\n")
        wd.set_clock("900\n")
        wd.set_env()
        done = wd.run(max_loops=1)
        assert done.returncode == 0
        assert wd.sleeps() == []
        assert wd.curl_calls() == []
    finally:
        holder.kill()
        holder.wait()


def test_stale_lock_is_taken_over(wd: Watchdog) -> None:
    dead = subprocess.Popen(["true"])
    dead.wait()
    (wd.root / "watchdog.lock").mkdir()
    (wd.root / "watchdog.lock" / "pid").write_text(f"{dead.pid}\n")
    wd.set_env()
    wd.set_clock("5000\n")
    wd.run(max_loops=1)
    assert wd.sleep_args() == ["60"]


# Onstart payload, run locally.


class Box:
    """A fake box filesystem for running the onstart payload locally."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.root = tmp / "workspace" / ".rig"
        self.workdir = tmp / "workspace"
        self.workdir.mkdir()
        self.environ = tmp / "environ"
        self.environ.write_bytes(b"PATH=/bin\0")
        self.watchdog = tmp / "image-watchdog.sh"
        self.watchdog.write_text(watchdog_script())

    def payload(self, ttl: int = 600, startup: str | None = None, custom: bool = False,
                **kw: object) -> str:
        args: dict[str, object] = dict(
            root=str(self.root), workdir=str(self.workdir), services=False,
            proc_environ=str(self.environ), alive_wait=5.0,
        )
        if not custom:
            args["watchdog_path"] = str(self.watchdog)
        args.update(kw)
        return build_payload(ttl, startup, custom, **args)  # type: ignore[arg-type]

    def run(self, payload: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        base = {
            "PATH": os.environ["PATH"],
            "RIG_POLL": "1",
            "RIG_MAX_LOOPS": "1",
            "CONTAINER_ID": "777",
            "CONTAINER_API_KEY": "ck-777",
        }
        if env is not None:
            base.update(env)
        base = {k: v for k, v in base.items() if v}
        done = subprocess.run(["bash"], input=payload, env=base, capture_output=True, text=True,
                              timeout=60)
        assert done.returncode == 0, done.stderr
        return done

    def read(self, name: str) -> str:
        return (self.root / name).read_text()

    def guard(self) -> list[str]:
        return self.read("guard").split()

    def wait_startup(self) -> int:
        wait_for(self.root / "startup.exit")
        return int(self.read("startup.exit"))


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return Box(tmp_path)


def test_payload_parses_for_each_mode() -> None:
    for custom in (False, True):
        for startup in (None, "echo hi\n"):
            bash_n(build_payload(1800, startup, custom))


def test_onstart_writes_clock_env_guard_and_exit(box: Box) -> None:
    before = int(time.time())
    box.run(box.payload(ttl=600))
    after = int(time.time())
    assert before + 600 <= int(box.read("clock")) <= after + 600
    env = box.read("env")
    assert "CONTAINER_ID=777\n" in env and "CONTAINER_API_KEY=ck-777\n" in env
    assert stat.S_IMODE((box.root / "env").stat().st_mode) == 0o600
    assert box.guard() == []
    assert (box.root / "alive").exists()
    assert (box.root / "startup.started").exists()
    assert box.wait_startup() == 0


def test_onstart_keeps_existing_clock_on_restart(box: Box) -> None:
    box.root.mkdir(parents=True)
    (box.root / "clock").write_text("4102444800\n")
    box.run(box.payload(ttl=600))
    assert box.read("clock") == "4102444800\n"


def test_onstart_reads_container_env_from_proc_environ(box: Box) -> None:
    box.environ.write_bytes(b"PATH=/bin\0CONTAINER_ID=55\0CONTAINER_API_KEY=pk-55\0")
    box.run(box.payload(), env={"CONTAINER_ID": "", "CONTAINER_API_KEY": ""})
    assert box.read("env") == "CONTAINER_ID=55\nCONTAINER_API_KEY=pk-55\n"
    assert box.guard() == []


def test_onstart_missing_key_marks_destroy_key(box: Box) -> None:
    box.run(box.payload(), env={"CONTAINER_API_KEY": ""})
    assert "destroy_key" in box.guard()
    assert not (box.root / "env").exists()


def test_onstart_without_watchdog_marks_watchdog(box: Box) -> None:
    box.run(box.payload(watchdog_path=str(box.tmp / "absent.sh"), alive_wait=0.4))
    assert box.guard() == ["watchdog"]


def test_default_image_uses_image_watchdog() -> None:
    payload = build_payload(600, None, False)
    assert f"WD={IMAGE_WATCHDOG}" in payload
    assert "RIG_WATCHDOG_EOF" not in payload
    assert "/etc/cron.d/rig" in payload
    assert "* * * * * root" in payload


def test_startup_runs_in_workdir_with_env_and_logs(box: Box) -> None:
    script = 'pwd >"$PWD/cwd.txt"\necho "hello $LEASE_VAR"\nexit 3\n'
    box.run(box.payload(startup=script), env={"LEASE_VAR": "from-env"})
    assert box.wait_startup() == 3
    assert "hello from-env" in box.read("startup.log")
    assert (box.workdir / "cwd.txt").read_text().strip() == str(box.workdir.resolve()) or \
        (box.workdir / "cwd.txt").read_text().strip() == str(box.workdir)


def test_restart_skips_a_started_hook(box: Box) -> None:
    script = f"echo run >>{box.tmp}/count\n"
    payload = box.payload(startup=script)
    box.run(payload)
    assert box.wait_startup() == 0
    box.run(payload)
    time.sleep(0.3)
    assert (box.tmp / "count").read_text() == "run\n"


def test_hook_cut_off_by_restart_reports_failure(box: Box) -> None:
    box.root.mkdir(parents=True)
    (box.root / "startup.started").write_text("1\n")
    box.run(box.payload(startup=f"echo run >>{box.tmp}/count\n"))
    assert box.wait_startup() == STARTUP_INTERRUPTED
    assert "cut off" in box.read("startup.log")
    assert not (box.tmp / "count").exists()


def test_startup_containing_the_delimiter_runs(box: Box) -> None:
    script = "cat <<'RIG_STARTUP_EOF'\nline\nRIG_STARTUP_EOF\n"
    box.run(box.payload(startup=script))
    assert box.wait_startup() == 0
    assert "line" in box.read("startup.log")


def test_custom_image_installs_essentials_and_writes_watchdog(box: Box) -> None:
    apt = box.tmp / "apt-get"
    write_exe(apt, f'#!/bin/sh\necho "$@" >>{box.tmp}/apt.log\n')
    essentials = (("rig-missing-tool", "rig-pkg"), ("sh", "sh-pkg"))
    box.run(box.payload(custom=True, apt=str(apt), essentials=essentials))
    log = (box.tmp / "apt.log").read_text()
    assert "update -qq" in log
    assert "install -y -qq --no-install-recommends rig-pkg" in log
    assert "sh-pkg" not in log
    assert (box.root / "watchdog.sh").exists()
    assert box.guard() == []


@pytest.mark.parametrize(("venv_exit", "installs"), [(1, True), (0, False)])
def test_custom_image_installs_python3_venv_when_python_lacks_it(
    box: Box, venv_exit: int, installs: bool
) -> None:
    stubs = box.tmp / "stubs"
    stubs.mkdir()
    write_exe(stubs / "python3", f'#!/bin/sh\necho "$@" >>{box.tmp}/python3.log\nexit {venv_exit}\n')
    apt = box.tmp / "apt-get"
    write_exe(apt, f'#!/bin/sh\necho "$@" >>{box.tmp}/apt.log\n')
    essentials = (("python3", "python3"),)
    box.run(box.payload(custom=True, apt=str(apt), essentials=essentials),
            env={"PATH": f"{stubs}:{os.environ['PATH']}"})
    assert "-c import ensurepip,venv" in (box.tmp / "python3.log").read_text()
    if installs:
        log = (box.tmp / "apt.log").read_text()
        assert "install -y -qq --no-install-recommends python3-venv" in log
    else:
        assert not (box.tmp / "apt.log").exists()


def test_custom_image_without_apt_is_unsupported(box: Box) -> None:
    essentials = (("rig-missing-tool", "rig-pkg"),)
    box.run(box.payload(custom=True, apt=str(box.tmp / "no-apt"), essentials=essentials))
    assert "apt-get" in box.read("unsupported").split()


@pytest.mark.skipif(os.geteuid() == 0, reason="runs as root")
def test_custom_image_without_root_is_unsupported(box: Box) -> None:
    box.run(box.payload(custom=True, essentials=()))
    assert "root" in box.read("unsupported").split()


# Encoded onstart.


def test_onstart_command_decodes_to_payload() -> None:
    cmd = build_onstart(1800, "echo hi\n", False)
    assert cmd.startswith("echo ") and cmd.endswith("|base64 -d|gunzip|bash")
    assert decode_onstart(cmd) == build_payload(1800, "echo hi\n", False)


def test_custom_onstart_checks_for_bash() -> None:
    cmd = build_onstart(1800, None, True)
    assert cmd.startswith("command -v bash >/dev/null||")
    assert "RIG_WATCHDOG_EOF" in decode_onstart(cmd)


def test_onstart_sizes_fit() -> None:
    sizes = {custom: len(build_onstart(1800, None, custom)) for custom in (False, True)}
    print(f"onstart sizes: default={sizes[False]} custom={sizes[True]}", file=sys.stderr)
    assert sizes[False] < sizes[True] <= ONSTART_LIMIT


def test_large_startup_is_rejected() -> None:
    script = "".join(f"echo {os.urandom(16).hex()}\n" for _ in range(200))
    with pytest.raises(RigError) as err:
        build_onstart(1800, script, False)
    assert err.value.code == "startup_too_large"
    assert err.value.details is not None and err.value.details["size"] > ONSTART_LIMIT


# Adopt.


def test_adopt_script_parses() -> None:
    bash_n(adopt_script(4102444800))


def test_adopt_writes_the_marker_before_the_guard() -> None:
    script = adopt_script(4102444800)
    marker = script.index(': >"$R/adopted"')
    assert script.count(': >"$R/adopted"') == 1
    assert marker < script.index("printf '%s\\n' $g>\"$R/guard.tmp\"")


def test_adopt_writes_clock_env_and_starts_watchdog(box: Box) -> None:
    box.environ.write_bytes(b"CONTAINER_ID=88\0CONTAINER_API_KEY=ak-88\0")
    script = adopt_script(4102444800, root=str(box.root), workdir=str(box.workdir),
                          services=False, proc_environ=str(box.environ), alive_wait=5.0)
    done = box.run(script, env={"CONTAINER_ID": "", "CONTAINER_API_KEY": ""})
    assert "missing=\n" in done.stdout
    assert box.read("clock") == "4102444800\n"
    assert box.read("env") == "CONTAINER_ID=88\nCONTAINER_API_KEY=ak-88\n"
    assert stat.S_IMODE((box.root / "env").stat().st_mode) == 0o600
    assert (box.root / "alive").exists()
    assert box.read("startup.exit") == "0\n"
    assert (box.root / "adopted").exists()


def test_adopt_again_keeps_the_running_watchdog(box: Box) -> None:
    box.environ.write_bytes(b"CONTAINER_ID=88\0CONTAINER_API_KEY=ak-88\0")
    script = adopt_script(4102444800, root=str(box.root), workdir=str(box.workdir),
                          services=False, proc_environ=str(box.environ), alive_wait=5.0)
    env = {"CONTAINER_ID": "", "CONTAINER_API_KEY": "", "RIG_MAX_LOOPS": "0"}
    box.run(script, env=env)
    pid = int(box.read("watchdog.lock/pid"))
    try:
        done = box.run(script, env=env)
        assert "missing=\n" in done.stdout
        assert int(box.read("watchdog.lock/pid")) == pid
    finally:
        os.kill(pid, 15)


def test_adopt_reports_missing_key(box: Box) -> None:
    script = adopt_script(4102444800, root=str(box.root), workdir=str(box.workdir),
                          services=False, proc_environ=str(box.environ), alive_wait=5.0)
    done = box.run(script, env={"CONTAINER_ID": "", "CONTAINER_API_KEY": ""})
    assert "missing= destroy_key" in done.stdout
    assert box.guard() == ["destroy_key"]
