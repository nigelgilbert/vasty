"""In-memory fakes for the provider and box boundaries.

`FakeProvider` implements `rig.provider.Provider`. `FakeBox` implements
`rig.remote.BoxAccess`. `make_context` builds a `Context` wired to both, with
a fixed clock, captured I/O and a temp home directory.
"""

from __future__ import annotations

import io
import itertools
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO

from rig.context import Context
from rig.errors import RigError
from rig.models import Charges, CreateRequest, Instance, Job, Offer, OfferQuery, ProbeResult, SshKey
from rig.provider import ProviderTimeout
from rig.remote import BoxUnreachableError, ExecResult, SshTarget

START = 1_793_232_000  # 2026-10-29T00:00:00Z


class FakeTime:
    """A settable wall clock and monotonic clock."""

    def __init__(self, start: float = START + 3600) -> None:
        self.wall_now = start
        self.mono_now = 1000.0

    def wall(self) -> float:
        return self.wall_now

    def mono(self) -> float:
        return self.mono_now

    def advance(self, seconds: float) -> None:
        self.wall_now += seconds
        self.mono_now += seconds

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)


def make_offer(offer_id: int = 1, **kw: Any) -> Offer:
    base: dict[str, Any] = dict(
        id=offer_id, gpu_name="RTX 4090", num_gpus=1, gpu_ram_gb=24.0,
        dph_total=Decimal("0.38"), reliability=0.99, inet_down=500.0, direct_port_count=10,
    )
    base.update(kw)
    return Offer(**base)


@dataclass
class FakeProvider:
    """An account held in memory. Set `fail` entries to raise on the next call."""

    time: FakeTime
    offers: list[Offer] = field(default_factory=list)
    instances: dict[int, Instance] = field(default_factory=dict)
    billed: dict[int, Decimal] = field(default_factory=dict)
    covered_through: int | None = None
    account_balance: Decimal = Decimal("50")
    ssh_keys: list[SshKey] = field(default_factory=list)
    attached: list[tuple[str, int | None]] = field(default_factory=list)
    destroyed: list[int] = field(default_factory=list)
    calls: list[tuple[str, Any]] = field(default_factory=list)
    fail: dict[str, RigError | list[RigError]] = field(default_factory=dict)
    date_header: bool = True
    start_status: str | None = "running"
    created: list[CreateRequest] = field(default_factory=list)
    on_create: Callable[[Instance, CreateRequest], None] | None = None
    _ids: Any = field(default_factory=lambda: itertools.count(1001))
    _date: tuple[float, float] | None = None

    def _call(self, name: str, arg: Any = None) -> None:
        self.calls.append((name, arg))
        if self.date_header:
            self._date = (self.time.wall_now, self.time.mono_now)
        planned = self.fail.get(name)
        if planned is None:
            return
        if isinstance(planned, list):
            err = planned.pop(0)
            if not planned:
                del self.fail[name]
        else:
            err = planned
            del self.fail[name]
        raise err

    def add_instance(self, **kw: Any) -> Instance:
        iid = kw.pop("id", None) or next(self._ids)
        base: dict[str, Any] = dict(
            id=iid, label=None, actual_status="running", gpu_name="RTX 3090", num_gpus=1,
            gpu_ram_gb=24.0, dph_total=Decimal("0.22"), public_ipaddr="198.51.100.9",
            ssh_host=None, ssh_port=None, ports={22: 40022, 8000: 40080, 8080: 40081},
        )
        base.update(kw)
        inst = Instance(**base)
        self.instances[inst.id] = inst
        return inst

    def search_offers(self, query: OfferQuery) -> list[Offer]:
        self._call("search_offers", query)
        return [o for o in self.offers if o.dph_total <= query.max_price]

    def create(self, request: CreateRequest) -> int:
        self._call("create", request)
        self.created.append(request)
        offer = next((o for o in self.offers if o.id == request.offer_id), None)
        inst = self.add_instance(
            label=request.label, actual_status=self.start_status,
            gpu_name=offer.gpu_name if offer else "RTX 4090",
            num_gpus=offer.num_gpus if offer else 1,
            gpu_ram_gb=offer.gpu_ram_gb if offer else 24.0,
            dph_total=offer.dph_total if offer else Decimal("0.38"),
            public_ipaddr="198.51.100.7", image=request.image, runtype=request.runtype,
            ports={p: 41000 + p % 1000 for p in request.ports},
        )
        if self.on_create is not None:
            self.on_create(inst, request)
        return inst.id

    def list_instances(self) -> list[Instance]:
        self._call("list_instances")
        return list(self.instances.values())

    def get_instance(self, instance_id: int) -> Instance | None:
        self._call("get_instance", instance_id)
        return self.instances.get(instance_id)

    def destroy(self, instance_id: int) -> None:
        self._call("destroy", instance_id)
        self.instances.pop(instance_id, None)
        self.destroyed.append(instance_id)

    def set_label(self, instance_id: int, label: str) -> None:
        self._call("set_label", (instance_id, label))
        inst = self.instances.get(instance_id)
        if inst is None:
            raise RigError("provider_error", f"No instance {instance_id}.", "Run rig status.")
        inst.label = label

    def charges(self, start: int, end: int) -> Charges:
        self._call("charges", (start, end))
        return Charges(per_instance=dict(self.billed), covered_through=self.covered_through)

    def balance(self) -> Decimal:
        self._call("balance")
        return self.account_balance

    def list_ssh_keys(self) -> list[SshKey]:
        self._call("list_ssh_keys")
        return list(self.ssh_keys)

    def attach_ssh_key(self, public_key: str, instance_id: int | None = None) -> None:
        self._call("attach_ssh_key", (public_key, instance_id))
        self.attached.append((public_key, instance_id))
        if instance_id is None:
            self.ssh_keys.append(SshKey(id=len(self.ssh_keys) + 1, public_key=public_key))

    def last_date(self) -> tuple[float, float] | None:
        return self._date if self.date_header else None


def timeout_error() -> ProviderTimeout:
    return ProviderTimeout("create timed out")


@dataclass
class BoxState:
    """One box's `/workspace/.rig` as the fake sees it."""

    clock: int | None = None
    clock_readable: bool = True
    guard_missing: list[str] = field(default_factory=list)
    startup_started: bool = True
    startup_exit: int | None = 0
    alive_mtime: int | None = None
    jobs: dict[str, Job] = field(default_factory=dict)
    logs: dict[str, list[str]] = field(default_factory=dict)
    reachable: bool = True
    clock_write_fails: bool = False
    adopt_missing: list[str] = field(default_factory=list)
    job_exit: int | None = 0
    signals: list[tuple[str, str]] = field(default_factory=list)
    execs: list[str] = field(default_factory=list)
    exec_results: dict[str, ExecResult] = field(default_factory=dict)


@dataclass
class FakeBox:
    """Boxes keyed by instance id. A box with no state is unreachable."""

    time: FakeTime
    boxes: dict[int, BoxState] = field(default_factory=dict)
    rsyncs: list[tuple[int, bool, str, str, bool, list[str]]] = field(default_factory=list)
    rsync_exit: int = 0
    interactive_calls: list[tuple[int, list[str] | None, list[str]]] = field(default_factory=list)
    clock_writes: list[tuple[int, int]] = field(default_factory=list)

    def state(self, instance_id: int) -> BoxState:
        return self.boxes.setdefault(instance_id, BoxState())

    def _get(self, target: SshTarget) -> BoxState:
        box = self.boxes.get(target.instance_id)
        if box is None or not box.reachable:
            raise BoxUnreachableError()
        return box

    def probe(self, target: SshTarget, label_expires: int | None, timeout: float = 5.0) -> ProbeResult:
        box = self._get(target)
        if label_expires is not None and box.clock != label_expires and not box.clock_write_fails:
            box.clock = label_expires
            box.clock_readable = True
        missing = list(box.guard_missing)
        if box.alive_mtime is not None and self.time.wall_now - box.alive_mtime > 180:
            if "watchdog" not in missing:
                missing.append("watchdog")
        if label_expires is not None and box.clock != label_expires and "clock_file" not in missing:
            missing.append("clock_file")
        return ProbeResult(
            clock_expires=box.clock if box.clock_readable else None,
            clock_readable=box.clock_readable,
            guard_missing=missing,
            startup_started=box.startup_started,
            startup_exit=box.startup_exit,
            alive_mtime=box.alive_mtime,
            jobs=[Job(**vars(j)) for j in box.jobs.values()],
        )

    def write_clock(self, target: SshTarget, expires: int) -> None:
        box = self._get(target)
        if box.clock_write_fails:
            raise BoxUnreachableError("clock write failed")
        box.clock = expires
        box.clock_readable = True
        self.clock_writes.append((target.instance_id, expires))

    def adopt(self, target: SshTarget, expires: int) -> list[str]:
        box = self._get(target)
        box.clock = expires
        box.guard_missing = list(box.adopt_missing)
        return list(box.adopt_missing)

    def start_job(self, target: SshTarget, job: Job, command: str) -> Job:
        box = self._get(target)
        started = Job(**{**vars(job), "started_at": int(self.time.wall_now), "state": "running",
                         "log_path": f"/workspace/.rig/jobs/{job.id}/log", "pid": 4242})
        box.jobs[job.id] = started
        box.logs.setdefault(job.id, [f"started {command}"])
        return started

    def attach_job(self, target: SshTarget, job_id: str, out: TextIO) -> int | None:
        box = self._get(target)
        for line in box.logs.get(job_id, []):
            print(line, file=out)
        job = box.jobs[job_id]
        if box.job_exit is None:
            return None
        job.exit = box.job_exit
        job.state = "exited"
        job.finished_at = int(self.time.wall_now)
        return box.job_exit

    def signal_job(self, target: SshTarget, job_id: str, signal: str) -> None:
        self._get(target).signals.append((job_id, signal))

    def job_status(self, target: SshTarget, job_id: str) -> Job:
        return self._get(target).jobs[job_id]

    def log_tail(self, target: SshTarget, job_id: str | None, lines: int) -> list[str]:
        box = self._get(target)
        if job_id is None:
            if not box.jobs:
                return []
            job_id = list(box.jobs)[-1]
        return box.logs.get(job_id, [])[-lines:]

    def exec(self, target: SshTarget, command: str, timeout: float | None = None) -> ExecResult:
        box = self._get(target)
        box.execs.append(command)
        for prefix, result in box.exec_results.items():
            if command.startswith(prefix):
                return result
        return ExecResult(0, "", "")

    def rsync(
        self, target: SshTarget, push: bool, src: str, dest: str, delete: bool, excludes: list[str]
    ) -> int:
        self._get(target)
        self.rsyncs.append((target.instance_id, push, src, dest, delete, list(excludes)))
        return self.rsync_exit

    def interactive(self, target: SshTarget, command: list[str] | None, ssh_args: list[str]) -> int:
        self._get(target)
        self.interactive_calls.append((target.instance_id, command, list(ssh_args)))
        return 0


@dataclass
class Harness:
    """A provider, a box fleet and a clock shared by every context it builds."""

    home: Path
    time: FakeTime = field(default_factory=FakeTime)
    env: dict[str, str] = field(default_factory=dict)
    provider: FakeProvider = field(init=False)
    box: FakeBox = field(init=False)
    http_status: int = 200
    http_calls: list[str] = field(default_factory=list)
    hex_values: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.provider = FakeProvider(time=self.time)
        self.box = FakeBox(time=self.time)
        self.env.setdefault("RIG_OWNER", "claude")
        self.env.setdefault("USER", "nick")
        self.env.setdefault("HOME", str(self.home))

    def http_get(self, url: str, headers: Mapping[str, str], timeout: float) -> int:
        self.http_calls.append(url)
        return self.http_status

    def random_hex(self, nbytes: int) -> str:
        if self.hex_values:
            return self.hex_values.pop(0)
        return "ab" * nbytes

    def context(self, stdin: str = "", tty: bool = False) -> Context:
        return Context(
            env=self.env, cwd=self.home / "project", home=self.home,
            stdin=io.StringIO(stdin), stdout=io.StringIO(), stderr=io.StringIO(),
            stdin_tty=tty, stdout_tty=tty,
            wall=self.time.wall, mono=self.time.mono, sleep=self.time.sleep,
            random_hex=self.random_hex, which=lambda name: f"/usr/bin/{name}",
            http_get=self.http_get,
            provider_factory=lambda ctx: self.provider,
            box_factory=lambda ctx: self.box,
        )

    def run(self, *argv: str, stdin: str = "", tty: bool = False) -> tuple[int, str, str]:
        """Run the CLI and return exit code, stdout and stderr."""
        from rig.cli import configure, run

        holder: list[Context] = []

        def make(ns: Any) -> Context:
            ctx = self.context(stdin=stdin, tty=tty)
            configure(ctx, ns)
            holder.append(ctx)
            return ctx

        early_out, early_err = io.StringIO(), io.StringIO()
        code = run(list(argv), make, early_out, early_err)
        if not holder:
            return code, early_out.getvalue(), early_err.getvalue()
        out = holder[0].stdout
        err = holder[0].stderr
        assert isinstance(out, io.StringIO) and isinstance(err, io.StringIO)
        return code, out.getvalue(), err.getvalue()
