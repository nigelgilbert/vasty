"""Box access over SSH and rsync (spec §3.2, §4.6, §4.8, §5.3).

`BoxAccess` is the semantic interface commands use to reach a box. `SshBox`
implements it with local `ssh`, `rsync` and `tmux` on the box. Tests use the
in-memory fake in `tests/fakes.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TextIO

from rig.errors import RigError
from rig.models import Job, ProbeResult


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


class SshBox:
    """`BoxAccess` over the local `ssh` and `rsync` binaries."""

    def __init__(self, ssh_key: str | None, known_hosts: str) -> None:
        self.ssh_key = ssh_key
        self.known_hosts = known_hosts

    def probe(self, target: SshTarget, label_expires: int | None, timeout: float = 5.0) -> ProbeResult:
        raise NotImplementedError

    def write_clock(self, target: SshTarget, expires: int) -> None:
        raise NotImplementedError

    def adopt(self, target: SshTarget, expires: int) -> list[str]:
        raise NotImplementedError

    def start_job(self, target: SshTarget, job: Job, command: str) -> Job:
        raise NotImplementedError

    def attach_job(self, target: SshTarget, job_id: str, out: TextIO) -> int | None:
        raise NotImplementedError

    def signal_job(self, target: SshTarget, job_id: str, signal: str) -> None:
        raise NotImplementedError

    def job_status(self, target: SshTarget, job_id: str) -> Job:
        raise NotImplementedError

    def log_tail(self, target: SshTarget, job_id: str | None, lines: int) -> list[str]:
        raise NotImplementedError

    def exec(self, target: SshTarget, command: str, timeout: float | None = None) -> ExecResult:
        raise NotImplementedError

    def rsync(
        self, target: SshTarget, push: bool, src: str, dest: str, delete: bool, excludes: list[str]
    ) -> int:
        raise NotImplementedError

    def interactive(self, target: SshTarget, command: list[str] | None, ssh_args: list[str]) -> int:
        raise NotImplementedError
