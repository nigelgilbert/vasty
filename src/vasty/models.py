"""Shared dataclasses for provider rows, lease records and command output.

Provider rows are normalized by `provider.py`. Lease records live in labels and
in the local cache. Output dataclasses are the JSON shapes the commands print;
`output.to_jsonable` turns them into plain JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

OMIT_NONE: dict[str, bool] = {"omit_none": True}
"""Field metadata: drop the key from JSON when the value is None."""

# Provider rows.


@dataclass(frozen=True)
class OfferQuery:
    """Resolved hardware constraints for an offer search."""

    gpu: str | None
    vram_min_gb: float | None
    gpus: int
    disk_gb: int
    max_price: Decimal
    region: str | None
    cuda: float | None = None


@dataclass(frozen=True)
class Offer:
    id: int
    gpu_name: str
    num_gpus: int
    gpu_ram_gb: float
    dph_total: Decimal
    reliability: float
    inet_down: float
    direct_port_count: int
    geolocation: str | None = None


@dataclass(frozen=True)
class CreateRequest:
    offer_id: int
    image: str
    disk_gb: int
    label: str
    onstart: str
    ports: list[int]
    runtype: Literal["ssh_direct", "ssh_proxy"]
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class Instance:
    """One instance row from the provider, normalized."""

    id: int
    label: str | None
    actual_status: str | None
    gpu_name: str | None
    num_gpus: int
    gpu_ram_gb: float | None
    dph_total: Decimal
    public_ipaddr: str | None
    ssh_host: str | None
    ssh_port: int | None
    ports: dict[int, int] = field(default_factory=dict)
    image: str | None = None
    runtype: str | None = None
    cuda_max_good: float | None = None
    """The highest CUDA version the host driver supports."""


@dataclass(frozen=True)
class SshKey:
    id: int
    public_key: str


@dataclass(frozen=True)
class Charges:
    """Billed instance charges from a range start to the read.

    `per_instance` maps instance id to the billed amount in the range, deleted
    instances included. `today` is the billed total of the rows that start on
    the UTC day of the range end.
    """

    per_instance: dict[int, Decimal]
    today: Decimal = Decimal("0")


@dataclass(frozen=True)
class Balance:
    """The account's `balance` and `credit` from `GET /users/current`."""

    balance: Decimal
    credit: Decimal


# Lease records.


@dataclass
class Label:
    """A parsed `vasty:v1` label. `extra` keeps unknown fields in order."""

    lease: str
    owner: str
    created: int
    ttl: int
    name: str | None = None
    group: str | None = None
    expires: int | None = None
    miss: list[str] = field(default_factory=list)
    extra: dict[str, str] = field(default_factory=dict)


JobState = Literal["running", "exited", "unknown", "serving", "killed"]
"""`killed` marks a job that `release` or `stop` ended."""


@dataclass
class Job:
    id: str
    cmd: str
    started_at: int | None
    exit: int | None
    state: JobState
    log_path: str | None = None
    pid: int | None = None
    finished_at: int | None = None
    kind: Literal["run", "serve"] = "run"
    port: int | None = None


@dataclass
class ProbeResult:
    """What one probe SSH command read from the box."""

    clock_expires: int | None
    clock_readable: bool
    guard_missing: list[str]
    startup_started: bool
    startup_exit: int | None
    alive_mtime: int | None
    jobs: list[Job] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    """What a custom image lacks (`bash`, `root`, `apt-get`); non-empty maps to `image_unsupported`."""
    startup_interrupted: bool = False
    """Set when the hook started, the container restarted, and no exit marker exists."""
    guard_file: bool = False
    """Set when the watchdog has written the guard file."""
    adopted: bool = False
    """Set when the adoption script has written its `adopted` marker."""
    box_now: int | None = None
    """The box's `date +%s` when the probe ran, or None when it printed nothing numeric."""


LeaseState = Literal[
    "pending", "running", "unreachable", "stopped", "expired", "released", "gone", "orphan"
]
HISTORY_STATES: frozenset[str] = frozenset({"expired", "released", "gone"})
SERVE_PORT = 8000


@dataclass
class CachedLease:
    """One lease in `leases.json`: label data plus what the provider does not hold."""

    lease: str
    instance_id: int
    label: Label
    state: LeaseState
    gpu: str | None = None
    gpus: int = 1
    vram_gb: float | None = None
    price_per_hr: Decimal = Decimal("0")
    image: str | None = None
    actual_status: str | None = None
    ssh_host: str | None = None
    ssh_port: int | None = None
    ports: dict[int, int] = field(default_factory=dict)
    reachable_at: int | None = None
    running_at: int | None = None
    """When `engine.refresh` first saw `actual_status` read `running`."""
    guard_missing: list[str] = field(default_factory=list)
    startup_exit: int | None = None
    startup_started: bool = False
    jobs: list[Job] = field(default_factory=list)
    released_here: bool = False
    destroy_pending: bool = False
    destroy_attempts: int = 0
    """Destroy calls sent since `destroy_pending` was set; sets the retry backoff."""
    destroy_at: int | None = None
    """When the last destroy call was sent."""
    history_since: int | None = None
    expired_at: int | None = None
    last_provider_error: str | None = None
    startup_interrupted: bool = False
    adopted: bool = False
    """Set by `tag` on an adopted orphan and by a probe that reruns the adoption script."""
    key_attempts: int = 0
    """Key attach retries sent since the lease last answered SSH; sets the retry backoff."""
    key_attach_at: int | None = None
    """When the last key attach retry was sent."""
    adopt_attempts: int = 0
    """Adoption reruns since the lease last had every adoption layer; sets the rerun backoff."""
    adopt_at: int | None = None
    """When the last adoption rerun ran."""
    unsupported: list[str] = field(default_factory=list)
    """What the last probe found missing from the image; non-empty maps to `image_unsupported`."""
    clock_skew: int | None = None
    """Box clock minus provider clock in seconds, from the last probe under a verified clock."""
    clock_skew_unknown: bool = False
    """Set when the last probe returned no box time."""
    follower_pid: int | None = None
    """The pid of the last `vasty sweep --follow` this machine started for the lease."""


# Output shapes.


@dataclass
class WarningItem:
    code: str
    lease: str | None
    message: str
    fix: str


@dataclass
class SweptEntry:
    lease: str
    name: str | None
    owner: str
    expired_at: str
    ok: bool
    error: str | None


@dataclass
class JobView:
    """One job entry in `status`, `release` and `stop` results."""

    job: str
    cmd: str
    state: str
    exit: int | None
    duration_s: int | None


@dataclass
class LeaseView:
    """One entry in `status.leases`. Verbose fields stay None unless `--verbose`."""

    lease: str
    name: str | None
    group: str | None
    owner: str | None
    state: str
    gpu: str | None
    gpus: int
    vram_gb: float | None
    price_per_hr: Decimal
    cost: Decimal | None
    uptime_s: int | None
    expires_at: str | None
    ttl_remaining_s: int | None
    busy: bool | None
    jobs: list[JobView]
    log_tail: list[str] | None = field(default=None, metadata=OMIT_NONE)
    destroy_pending: bool | None = field(default=None, metadata=OMIT_NONE)
    verbose: dict[str, Any] | None = field(default=None, metadata=OMIT_NONE)


@dataclass
class Totals:
    balance: Decimal | None
    credit: Decimal | None
    charges_today: Decimal | None
    burn_per_hr: Decimal
    live: int
    live_mine: int


@dataclass
class StatusResult:
    leases: list[LeaseView]
    warnings: list[WarningItem]
    totals: Totals
    swept: list[SweptEntry]
    cached_at: str | None


@dataclass
class ReserveResult:
    lease: str
    name: str | None
    owner: str
    group: str | None
    state: str
    reused: bool
    gpu: str | None
    gpus: int
    vram_gb: float | None
    price_per_hr: Decimal
    expires_at: str | None
    ttl_remaining_s: int | None
    ssh: str | None
    rsync_target: str | None
    ssh_port: int | None
    ports: dict[str, int] | None
    warnings: list[WarningItem]
    swept: list[SweptEntry]


@dataclass
class ExtendResult:
    lease: str
    expires_at: str
    ttl_remaining_s: int
    warnings: list[WarningItem]
    swept: list[SweptEntry]


@dataclass
class BulkEntry:
    """One entry of a bulk result. `data` fields merge into the entry's JSON."""

    lease: str
    ok: bool
    error: str | None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class BulkResult:
    results: list[BulkEntry]
    warnings: list[WarningItem]
    swept: list[SweptEntry]


@dataclass
class ReleaseSummary:
    lease: str
    name: str | None
    uptime_s: int | None
    cost: Decimal | None
    jobs: list[JobView]
    destroy_pending: bool | None = field(default=True, metadata=OMIT_NONE)
    already_absent: bool | None = field(default=None, metadata=OMIT_NONE)
    warnings: list[WarningItem] | None = field(default=None, metadata=OMIT_NONE)
    swept: list[SweptEntry] | None = field(default=None, metadata=OMIT_NONE)


@dataclass
class TagEntry:
    lease: str
    name: str | None
    group: str | None
    owner: str
    expires_at: str | None
    ttl_remaining_s: int | None


@dataclass
class SweepResult:
    swept: list[SweptEntry]
    warnings: list[WarningItem]


@dataclass
class TagResult:
    results: list[TagEntry]
    warnings: list[WarningItem]
    swept: list[SweptEntry]


@dataclass
class RunDetachedResult:
    lease: str
    job: str
    log_path: str
    expires_at: str | None
    warnings: list[WarningItem]
    swept: list[SweptEntry]


@dataclass
class RunAttachedResult:
    lease: str
    job: str | None
    exit: int | None
    duration_s: int | None
    released: bool
    warnings: list[WarningItem]
    swept: list[SweptEntry]
    error: str | None = None


@dataclass
class ServeResult:
    lease: str
    job: str
    model: str
    url: str
    api_key: str
    expires_at: str | None
    warnings: list[WarningItem]
    swept: list[SweptEntry]


@dataclass
class StopResult:
    """The `stop` result: the lease and the stopped job's entry."""

    lease: str
    job: str
    cmd: str
    state: str
    exit: int | None
    duration_s: int | None
    warnings: list[WarningItem]
    swept: list[SweptEntry]


@dataclass
class SyncResult:
    lease: str
    direction: Literal["push", "pull"]
    src: str
    dest: str
    warnings: list[WarningItem]
    swept: list[SweptEntry]


@dataclass
class ReleaseAbsent:
    """`release` output for a LEASE that matches no active or history lease."""

    lease: str
    already_absent: bool
    warnings: list[WarningItem]
    swept: list[SweptEntry]
