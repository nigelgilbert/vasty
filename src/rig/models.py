"""Shared dataclasses for provider rows, lease records and command output.

Provider rows are normalized by `provider.py`. Lease records live in labels and
in the local cache. Output dataclasses are the JSON shapes from spec §4 and §7;
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


@dataclass(frozen=True)
class SshKey:
    id: int
    public_key: str


@dataclass(frozen=True)
class Charges:
    """Billed charges for a UTC-day range.

    `per_instance` maps instance id to billed amount in the range, deleted
    instances included. `covered_through` is the epoch second billing covers;
    None when coverage cannot be read.
    """

    per_instance: dict[int, Decimal]
    covered_through: int | None

    @property
    def total(self) -> Decimal:
        return sum(self.per_instance.values(), Decimal("0"))


# Lease records.


@dataclass
class Label:
    """A parsed `rig:v1` label. `extra` keeps unknown fields in order."""

    lease: str
    owner: str
    created: int
    ttl: int
    name: str | None = None
    group: str | None = None
    expires: int | None = None
    miss: list[str] = field(default_factory=list)
    extra: dict[str, str] = field(default_factory=dict)


JobState = Literal["running", "exited", "unknown", "serving"]


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
    """What one probe SSH command read from the box (spec §3.2)."""

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


LeaseState = Literal[
    "pending", "running", "unreachable", "stopped", "expired", "released", "gone", "orphan"
]
HISTORY_STATES: frozenset[str] = frozenset({"expired", "released", "gone"})


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
    unsupported: list[str] = field(default_factory=list)
    """What the last probe found missing from a custom image; non-empty maps to `image_unsupported`."""


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
    expired_at: str
    ok: bool
    error: str | None


@dataclass
class JobView:
    id: str
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
    guard: str | None
    guard_missing: list[str] | None
    gpu: str | None
    price_per_hr: Decimal
    cost: Decimal | None
    cost_source: str | None
    expires_at: str | None
    ttl_remaining_s: int | None
    jobs: list[JobView]
    log_tail: list[str] | None = field(default=None, metadata=OMIT_NONE)
    destroy_pending: bool | None = field(default=None, metadata=OMIT_NONE)
    verbose: dict[str, Any] | None = field(default=None, metadata=OMIT_NONE)


@dataclass
class Totals:
    spent_today: Decimal | None
    daily_budget: Decimal
    remaining_budget: Decimal | None
    burn_per_hr: Decimal
    live: int
    live_mine: int
    spend_source: str | None
    daily_budget_source: str


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
    guard: str
    guard_missing: list[str]
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
class ReleaseJob:
    id: str
    cmd: str
    exit: int | None
    duration_s: int | None


@dataclass
class ReleaseSummary:
    lease: str
    name: str | None
    uptime_s: int | None
    cost: Decimal | None
    jobs: list[ReleaseJob]
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
    guard: str
    guard_missing: list[str]


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
