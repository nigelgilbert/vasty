"""Box access over SSH and rsync (spec §3.2, §4.6, §4.8, §5.3).

`BoxAccess` is the semantic interface commands use to reach a box. `SshBox`
implements it with local `ssh`, `rsync` and `tmux` on the box. Tests use the
in-memory fake in `tests/fakes.py`.
"""

from __future__ import annotations

import base64
import codecs
import os
import posixpath
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TextIO

from rig.errors import RigError
from rig.models import Job, JobState, ProbeResult


class BoxUnreachableError(RigError):
    """The box did not answer SSH."""

    def __init__(self, message: str = "The box does not answer SSH.") -> None:
        super().__init__("box_unreachable", message, "Run rig status.")


@dataclass(frozen=True)
class SshTarget:
    instance_id: int
    host: str
    port: int
    user: str = "root"


@dataclass(frozen=True)
class ExecResult:
    exit: int
    stdout: str
    stderr: str


class BoxAccess(Protocol):
    def probe(self, target: SshTarget, label_expires: int | None, timeout: float = 5.0) -> ProbeResult:
        """Run the probe. Rewrite the clock file when `label_expires` is set and differs.

        Raise `BoxUnreachableError` when SSH does not answer.
        """
        ...

    def write_clock(self, target: SshTarget, expires: int) -> None:
        """Write the clock file by temp file and rename."""
        ...

    def adopt(self, target: SshTarget, expires: int) -> list[str]:
        """Write the clock file, copy the container env and start the watchdog.

        Return the guard layers still missing.
        """
        ...

    def start_job(self, target: SshTarget, job: Job, command: str) -> Job:
        """Start a job under tmux in `/workspace`, write its record and return it."""
        ...

    def attach_job(self, target: SshTarget, job_id: str, out: TextIO) -> int | None:
        """Stream the job log to `out` until it exits; return its exit code, or None when the connection drops."""
        ...

    def signal_job(self, target: SshTarget, job_id: str, signal: str) -> None: ...

    def job_status(self, target: SshTarget, job_id: str) -> Job: ...

    def log_tail(self, target: SshTarget, job_id: str | None, lines: int) -> list[str]:
        """Return the last lines of a job log, or the newest job's log when `job_id` is None."""
        ...

    def exec(self, target: SshTarget, command: str, timeout: float | None = None) -> ExecResult: ...

    def rsync(
        self, target: SshTarget, push: bool, src: str, dest: str, delete: bool, excludes: list[str]
    ) -> int: ...

    def interactive(self, target: SshTarget, command: list[str] | None, ssh_args: list[str]) -> int:
        """Run `ssh` attached to the terminal and return its exit code."""
        ...


RunMode = Literal["capture", "inherit", "stderr", "stream"]
"""How a runner wires the child's stdio.

`capture` collects stdout and stderr. `inherit` leaves all three on the
terminal. `stderr` sends the child's stdout to our stderr. `stream` copies
stdout to `out` as it arrives and collects stderr.
"""


class Runner(Protocol):
    def __call__(
        self,
        argv: list[str],
        *,
        input: str | None = None,
        timeout: float | None = None,
        mode: RunMode = "capture",
        out: TextIO | None = None,
    ) -> ExecResult:
        """Run `argv` and return its exit code and captured output.

        Raise `subprocess.TimeoutExpired` past `timeout` and `FileNotFoundError`
        when the binary is missing.
        """
        ...


def subprocess_runner(
    argv: list[str],
    *,
    input: str | None = None,
    timeout: float | None = None,
    mode: RunMode = "capture",
    out: TextIO | None = None,
) -> ExecResult:
    """Run a local process with `subprocess`."""
    if mode == "capture":
        done = subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout)
        return ExecResult(done.returncode, done.stdout, done.stderr)
    if mode == "inherit":
        code = subprocess.run(argv, input=input, text=True, timeout=timeout).returncode
        return ExecResult(code, "", "")
    if mode == "stderr":
        done = subprocess.run(argv, input=input, text=True, timeout=timeout, stdout=2)
        return ExecResult(done.returncode, "", "")
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err)
        assert proc.stdout is not None
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while chunk := os.read(proc.stdout.fileno(), 65536):
            if out is not None:
                out.write(decoder.decode(chunk))
                out.flush()
        if out is not None:
            out.write(decoder.decode(b"", final=True))
        code = proc.wait(timeout=timeout)
        err.seek(0)
        return ExecResult(code, "", err.read().decode("utf-8", errors="replace"))


_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SIGNAL = re.compile(r"^(?:[A-Z][A-Z0-9+-]*|[0-9]{1,2})$")
WATCHDOG_STALE_S = 180


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _job_id(job_id: str) -> str:
    if not _JOB_ID.match(job_id):
        raise ValueError(f"invalid job id {job_id!r}")
    return job_id


def _int(text: str | None) -> int | None:
    if text is None or not re.fullmatch(r"-?[0-9]+", text.strip()):
        return None
    return int(text.strip())


def _job_lines(root: str, pattern: str) -> str:
    """Return shell that prints one `job=` line per job directory matching `pattern`."""
    return (
        f"R={shlex.quote(root)}\n"
        "n(){ tr -cd '0-9-' 2>/dev/null <\"$1\"; }\n"
        f'for d in "$R"/jobs/{pattern}; do\n'
        '  [ -d "$d" ] || continue\n'
        '  id=${d##*/}; st=$(n "$d/started"); pid=$(n "$d/pid"); ex=$(n "$d/exit")\n'
        '  fin=$(n "$d/finished"); port=$(n "$d/port")\n'
        "  kind=$(tr -cd 'a-z' 2>/dev/null <\"$d/kind\")\n"
        "  cmd=$(base64 2>/dev/null <\"$d/cmd\" | tr -d '\\n')\n"
        "  live=0\n"
        '  if [ -z "$ex" ] && [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then\n'
        "    live=1\n"
        '    if [ -r "/proc/$pid/cmdline" ] && ! tr "\\0" " " <"/proc/$pid/cmdline"'
        ' | grep -q "jobs/$id/"; then live=0; fi\n'
        "  fi\n"
        '  echo "job=$id ${cmd:--} ${st:--} ${pid:--} ${ex:--} ${fin:--} ${kind:--} ${port:--} $live"\n'
        "done\n"
    )


def probe_script(label_expires: int | None, root: str) -> str:
    """Return the POSIX shell the probe runs on the box (spec §3.2).

    It rewrites the clock file when `label_expires` is set and differs, then
    prints `key=value` lines between `rig_probe=1` and `rig_probe=end`.
    """
    label = "" if label_expires is None else str(int(label_expires))
    return (
        f"R={shlex.quote(root)}; L={label}\n"
        "echo rig_probe=1\n"
        'echo "now=$(date +%s)"\n'
        "rc(){ head -c 64 \"$R/clock\" 2>/dev/null | tr -d ' \\n\\r\\t'; }\n"
        "c=$(rc); rw=none\n"
        'if [ -n "$L" ] && [ "$c" != "$L" ]; then\n'
        "  if printf '%s\\n' \"$L\" 2>/dev/null >\"$R/clock.tmp.$$\""
        ' && mv -f "$R/clock.tmp.$$" "$R/clock" 2>/dev/null; then rw=ok\n'
        '  else rw=failed; rm -f "$R/clock.tmp.$$" 2>/dev/null; fi\n'
        "  c=$(rc)\n"
        "fi\n"
        'echo "clock=$c"; echo "rewrite=$rw"\n'
        '[ -e "$R/guard" ] && echo guard_file=1\n'
        "echo \"guard=$(cat \"$R/guard\" 2>/dev/null | tr '\\n\\r\\t' '   ')\"\n"
        '[ -e "$R/startup.started" ] && echo startup_started=1\n'
        "echo \"startup_exit=$(head -c 16 \"$R/startup.exit\" 2>/dev/null | tr -d ' \\n\\r\\t')\"\n"
        'echo "alive=$(stat -c %Y "$R/alive" 2>/dev/null || stat -f %m "$R/alive" 2>/dev/null)"\n'
        "if grep -q '^CONTAINER_ID=.' \"$R/env\" 2>/dev/null && "
        "grep -q '^CONTAINER_API_KEY=.' \"$R/env\" 2>/dev/null; then echo key=1; else echo key=0; fi\n"
        "echo \"unsupported=$(cat \"$R/unsupported\" 2>/dev/null | tr '\\n\\r\\t' '   ')\"\n"
        + _job_lines(root, "*")
        + "echo rig_probe=end\n"
    )


def _parse_job(line: str, root: str) -> Job | None:
    parts = line.split(" ")
    if len(parts) != 9:
        return None
    jid, cmd64, started, pid, exit_, finished, kind, port, live = parts
    try:
        cmd = base64.b64decode(cmd64).decode("utf-8", errors="replace") if cmd64 != "-" else ""
    except ValueError:
        cmd = ""
    exit_code = _int(exit_)
    job_kind: Literal["run", "serve"] = "serve" if kind == "serve" else "run"
    state: JobState
    if exit_code is not None:
        state = "exited"
    elif live == "1":
        state = "serving" if job_kind == "serve" else "running"
    else:
        state = "unknown"
    return Job(
        id=jid,
        cmd=cmd,
        started_at=_int(started),
        exit=exit_code,
        state=state,
        log_path=f"{root}/jobs/{jid}/log",
        pid=_int(pid),
        finished_at=_int(finished),
        kind=job_kind,
        port=_int(port),
    )


def parse_probe(stdout: str, label_expires: int | None, root: str) -> ProbeResult:
    """Parse probe output into a `ProbeResult`.

    `watchdog` is missing when `alive` is older than 180s, or absent once
    `onstart` has written the guard file or started the startup hook.
    `destroy_key` is missing when the env file lacks the container key.
    `clock_file` is missing when the clock file is unreadable or still differs
    from the label. Raise `BoxUnreachableError` on a partial answer.
    """
    lines = stdout.splitlines()
    if "rig_probe=1" not in lines or "rig_probe=end" not in lines:
        raise BoxUnreachableError("The probe returned no answer.")
    values: dict[str, str] = {}
    jobs: list[Job] = []
    for line in lines:
        key, sep, value = line.partition("=")
        if not sep:
            continue
        if key == "job":
            job = _parse_job(value, root)
            if job is not None:
                jobs.append(job)
        else:
            values[key] = value
    now = _int(values.get("now"))
    clock = _int(values.get("clock"))
    alive = _int(values.get("alive"))
    startup_started = values.get("startup_started") == "1"
    onstart_done = values.get("guard_file") == "1" or startup_started
    file_layers = values.get("guard", "").split()

    missing: list[str] = []
    if alive is None:
        watchdog_down = onstart_done
    else:
        watchdog_down = now is not None and now - alive > WATCHDOG_STALE_S
    if watchdog_down:
        missing.append("watchdog")
    if onstart_done:
        if values.get("key") != "1":
            missing.append("destroy_key")
    elif "destroy_key" in file_layers:
        missing.append("destroy_key")
    if clock is None or (label_expires is not None and clock != label_expires):
        missing.append("clock_file")
    for layer in file_layers:
        if layer not in ("watchdog", "destroy_key", "clock_file") and layer not in missing:
            missing.append(layer)

    return ProbeResult(
        clock_expires=clock,
        clock_readable=clock is not None,
        guard_missing=missing,
        startup_started=startup_started,
        startup_exit=_int(values.get("startup_exit")),
        alive_mtime=alive,
        jobs=jobs,
        unsupported=values.get("unsupported", "").split(),
    )


class SshBox:
    """`BoxAccess` over the local `ssh` and `rsync` binaries.

    `runner` wraps `subprocess` so tests can check argv and scripts without a
    network. `root`, `workdir`, `tmux` and `poll` set the box paths, the tmux
    command and the attach poll interval. `services` set to False skips the
    cron and sshd steps in `adopt`.
    """

    def __init__(
        self,
        ssh_key: str | None,
        known_hosts: str,
        *,
        runner: Runner = subprocess_runner,
        root: str = "/workspace/.rig",
        workdir: str = "/workspace",
        tmux: str = "tmux",
        poll: float = 1.0,
        services: bool = True,
    ) -> None:
        self.ssh_key = ssh_key
        self.known_hosts = known_hosts
        self.runner = runner
        self.root = root
        self.workdir = workdir
        self.tmux = tmux
        self.poll = poll
        self.services = services

    # SSH plumbing.

    def ssh_options(
        self, target: SshTarget, batch: bool = True, connect_timeout: int = 10
    ) -> list[str]:
        """Return the ssh options from spec §5.3, without the destination."""
        opts: list[str] = []
        if self.ssh_key:
            opts += ["-i", os.path.expanduser(self.ssh_key), "-o", "IdentitiesOnly=yes"]
        opts += [
            "-p", str(target.port),
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={self.known_hosts}",
            "-o", f"HostKeyAlias=vast-{target.instance_id}",
            "-o", f"ConnectTimeout={connect_timeout}",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3",
            "-o", "LogLevel=ERROR",
        ]
        if batch:
            opts += ["-o", "BatchMode=yes"]
        return opts

    def _run(
        self,
        argv: list[str],
        *,
        input: str | None = None,
        timeout: float | None = None,
        mode: RunMode = "capture",
        out: TextIO | None = None,
    ) -> ExecResult:
        Path(self.known_hosts).expanduser().parent.mkdir(parents=True, exist_ok=True)
        try:
            return self.runner(argv, input=input, timeout=timeout, mode=mode, out=out)
        except subprocess.TimeoutExpired as exc:
            raise BoxUnreachableError(f"The box did not answer within {exc.timeout:g}s.") from exc
        except FileNotFoundError as exc:
            raise RigError(
                "dependency_missing", f"{argv[0]} is not on PATH.", f"Install {argv[0]}."
            ) from exc

    def _ssh(
        self,
        target: SshTarget,
        remote: str,
        *,
        input: str | None = None,
        timeout: float | None = None,
        connect_timeout: int = 10,
        mode: RunMode = "capture",
        out: TextIO | None = None,
    ) -> ExecResult:
        """Run one remote command. Raise `BoxUnreachableError` on ssh exit 255 or a timeout."""
        argv = [
            "ssh", *self.ssh_options(target, True, connect_timeout),
            f"{target.user}@{target.host}", remote,
        ]
        result = self._run(argv, input=input, timeout=timeout, mode=mode, out=out)
        if result.exit == 255:
            raise BoxUnreachableError(result.stderr.strip() or "The box does not answer SSH.")
        return result

    def _script(self, target: SshTarget, script: str, timeout: float | None = 60.0) -> ExecResult:
        return self._ssh(target, "bash -s", input=script, timeout=timeout)

    def _job_dir(self, job_id: str) -> str:
        return f"{self.root}/jobs/{_job_id(job_id)}"

    # BoxAccess.

    def probe(self, target: SshTarget, label_expires: int | None, timeout: float = 5.0) -> ProbeResult:
        script = probe_script(label_expires, self.root)
        result = self._ssh(
            target, "sh -s", input=script, timeout=timeout, connect_timeout=max(1, int(timeout))
        )
        return parse_probe(result.stdout, label_expires, self.root)

    def write_clock(self, target: SshTarget, expires: int) -> None:
        n = int(expires)
        script = (
            f"R={shlex.quote(self.root)}\n"
            f"mkdir -p \"$R\" && printf '%s\\n' {n} >\"$R/clock.tmp.$$\""
            ' && mv -f "$R/clock.tmp.$$" "$R/clock"'
            f' && [ "$(cat "$R/clock")" = {n} ] && echo rig_clock=ok\n'
        )
        result = self._ssh(target, "sh -s", input=script, timeout=15.0)
        if "rig_clock=ok" not in result.stdout.split():
            raise BoxUnreachableError(f"Could not write the clock file. {result.stderr.strip()}")

    def adopt(self, target: SshTarget, expires: int) -> list[str]:
        from rig.onstart import LAYERS, adopt_script

        script = adopt_script(
            expires, root=self.root, workdir=self.workdir, services=self.services
        )
        result = self._script(target, script, timeout=60.0)
        for line in result.stdout.splitlines():
            if line.startswith("missing="):
                return line[len("missing="):].split()
        return list(LAYERS)

    def start_script(self, job: Job, command: str) -> str:
        """Return the shell that writes a job record and starts the job under tmux."""
        jdir = self._job_dir(job.id)
        j = shlex.quote(jdir)
        w = shlex.quote(self.workdir)
        run_sh = (
            "trap : INT TERM HUP\n"
            f"cd {w} || exit 1\n"
            f"echo $$ >{j}/pid.tmp && mv -f {j}/pid.tmp {j}/pid\n"
            f"bash {j}/script >>{j}/log 2>&1 </dev/null\n"
            "rc=$?\n"
            f"date +%s >{j}/finished\n"
            f"echo $rc >{j}/exit.tmp && mv -f {j}/exit.tmp {j}/exit\n"
        )
        session = shlex.quote(f"rig-{job.id}")
        tmux_cmd = shlex.quote(f"exec bash {j}/run.sh")
        lines = [
            f"J={j}",
            '[ -e "$J/started" ] && { echo rig_job=exists; exit 0; }',
            'mkdir -p "$J" || exit 3',
            f'printf %s {_b64(job.cmd)} | base64 -d >"$J/cmd"',
            f'(umask 077; printf %s {_b64(command)} | base64 -d >"$J/script")',
            f'printf %s {_b64(run_sh)} | base64 -d >"$J/run.sh"',
            f'echo {job.kind} >"$J/kind"',
        ]
        if job.port is not None:
            lines.append(f'echo {int(job.port)} >"$J/port"')
        lines += [
            ': >"$J/log"',
            'date +%s >"$J/started"',
            f"{self.tmux} new-session -d -s {session} -c {w} {tmux_cmd}"
            " || { echo rig_job=tmux_failed; exit 0; }",
            'i=0; while [ ! -s "$J/pid" ] && [ $i -lt 50 ]; do sleep 0.1; i=$((i+1)); done',
            'echo "started=$(cat "$J/started")"',
            'echo "pid=$(cat "$J/pid" 2>/dev/null)"',
            "echo rig_job=ok",
        ]
        return "\n".join(lines) + "\n"

    def start_job(self, target: SshTarget, job: Job, command: str) -> Job:
        jdir = self._job_dir(job.id)
        result = self._script(target, self.start_script(job, command), timeout=30.0)
        values: dict[str, str] = {}
        for line in result.stdout.splitlines():
            key, _, value = line.partition("=")
            values[key] = value
        status = values.get("rig_job")
        if status != "ok":
            reasons = {
                "exists": f"Job {job.id} already exists on the box.",
                "tmux_failed": "tmux could not start the job.",
            }
            raise RigError(
                "box_unreachable",
                reasons.get(status or "", f"Could not start job {job.id}. {result.stderr.strip()}"),
                f"Run rig ssh LEASE -- ls {jdir}.",
            )
        return Job(
            id=job.id,
            cmd=job.cmd,
            started_at=_int(values.get("started")),
            exit=None,
            state="serving" if job.kind == "serve" else "running",
            log_path=f"{jdir}/log",
            pid=_int(values.get("pid")),
            finished_at=None,
            kind=job.kind,
            port=job.port,
        )

    def attach_script(self, job_id: str) -> str:
        """Return the shell that streams a job log until the job exits.

        The script prints `rig_exit=CODE` on stderr when the exit file appears,
        or `rig_exit=lost` when the job's process died without one.
        """
        j = shlex.quote(self._job_dir(job_id))
        return (
            f"J={j}\n"
            '[ -d "$J" ] || { echo rig_exit=missing >&2; exit 0; }\n'
            "off=0\n"
            "while :; do\n"
            '  fin=0; [ -e "$J/exit" ] && fin=1\n'
            '  if [ $fin = 0 ] && [ -s "$J/pid" ] && ! kill -0 "$(cat "$J/pid")" 2>/dev/null; then\n'
            '    if [ -e "$J/exit" ]; then fin=1; else fin=2; fi\n'
            "  fi\n"
            '  sz=$(wc -c 2>/dev/null <"$J/log" || echo 0); sz=$((sz + 0))\n'
            '  if [ "$sz" -gt "$off" ]; then\n'
            '    tail -c +$((off + 1)) "$J/log" | head -c $((sz - off)); off=$sz\n'
            "  fi\n"
            "  [ $fin != 0 ] && break\n"
            f"  sleep {self.poll:g}\n"
            "done\n"
            'if [ $fin = 1 ]; then echo "rig_exit=$(cat "$J/exit")" >&2;'
            " else echo rig_exit=lost >&2; fi\n"
        )

    def attach_job(self, target: SshTarget, job_id: str, out: TextIO) -> int | None:
        remote = f"bash -c {shlex.quote(self.attach_script(job_id))}"
        argv = ["ssh", *self.ssh_options(target), f"{target.user}@{target.host}", remote]
        try:
            result = self._run(argv, mode="stream", out=out)
        except BoxUnreachableError:
            return None
        for line in reversed(result.stderr.splitlines()):
            if line.startswith("rig_exit="):
                return _int(line[len("rig_exit="):])
        return None

    def signal_job(self, target: SshTarget, job_id: str, signal: str) -> None:
        """Send `signal` to the job's process group; a job with no pid is left alone."""
        sig = signal.upper().removeprefix("SIG")
        if not _SIGNAL.match(sig):
            raise ValueError(f"invalid signal {signal!r}")
        j = shlex.quote(self._job_dir(job_id))
        script = (
            f'p=$(cat {j}/pid 2>/dev/null); [ -n "$p" ] || exit 0\n'
            f'kill -s {sig} -- "-$p" 2>/dev/null || kill -s {sig} "$p" 2>/dev/null\n'
            "exit 0\n"
        )
        self._script(target, script, timeout=15.0)

    def job_status(self, target: SshTarget, job_id: str) -> Job:
        result = self._script(target, _job_lines(self.root, _job_id(job_id)), timeout=15.0)
        for line in result.stdout.splitlines():
            if line.startswith("job="):
                job = _parse_job(line[len("job="):], self.root)
                if job is not None and job.id == job_id:
                    return job
        raise RigError("invalid_arguments", f"No job {job_id} on the box.", "Run rig status LEASE.")

    def log_tail(self, target: SshTarget, job_id: str | None, lines: int) -> list[str]:
        jid = "" if job_id is None else _job_id(job_id)
        script = (
            f"R={shlex.quote(self.root)}; id={jid}\n"
            'if [ -z "$id" ]; then\n'
            '  id=$(for d in "$R"/jobs/*; do [ -d "$d" ] &&'
            ' echo "$(tr -cd 0-9 2>/dev/null <"$d/started") ${d##*/}"; done'
            " | sort -n | tail -n 1 | cut -d' ' -f2)\n"
            "fi\n"
            f'[ -n "$id" ] && [ -f "$R/jobs/$id/log" ] && tail -n {max(0, int(lines))} "$R/jobs/$id/log"\n'
            "exit 0\n"
        )
        return self._script(target, script, timeout=15.0).stdout.splitlines()

    def exec(self, target: SshTarget, command: str, timeout: float | None = None) -> ExecResult:
        return self._ssh(target, command, timeout=timeout)

    def remote_path(self, path: str) -> str:
        """Resolve a relative remote path under the workdir; keep absolute and `~` paths."""
        if path.startswith(("/", "~")):
            return path
        return posixpath.join(self.workdir, path)

    def rsync_argv(
        self, target: SshTarget, push: bool, src: str, dest: str, delete: bool, excludes: list[str]
    ) -> list[str]:
        """Return the rsync argv for one transfer over the lease's ssh options."""
        argv = ["rsync", "-az", "--partial"]
        if delete:
            argv.append("--delete")
        argv += [f"--exclude={e}" for e in excludes]
        argv += ["-e", shlex.join(["ssh", *self.ssh_options(target)])]
        remote = f"{target.user}@{target.host}:"
        if push:
            argv += [src, remote + self.remote_path(dest)]
        else:
            argv += [remote + self.remote_path(src), dest]
        return argv

    def rsync(
        self, target: SshTarget, push: bool, src: str, dest: str, delete: bool, excludes: list[str]
    ) -> int:
        argv = self.rsync_argv(target, push, src, dest, delete, excludes)
        return self._run(argv, mode="stderr").exit

    def interactive(self, target: SshTarget, command: list[str] | None, ssh_args: list[str]) -> int:
        """Run ssh on the terminal and return its exit code.

        One command word passes through as a shell string. Several words are
        shell-quoted so each reaches the box as one argument.
        """
        argv = [
            "ssh", *self.ssh_options(target, batch=False), *ssh_args,
            f"{target.user}@{target.host}",
        ]
        if command:
            argv.append(command[0] if len(command) == 1 else shlex.join(command))
        return self._run(argv, mode="inherit").exit


