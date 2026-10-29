"""The networked-command prelude: list, sweep, reconcile and probe (spec §6, §8.1).

Every networked command calls `refresh` before it resolves its target. The
spend helpers back `status` totals and the budget check in the spending
commands (spec §5.2). `cached_snapshot` answers `status --cached` from the
local file and imports only the standard library.

Reconciliation keeps history leases in `Snapshot.leases` for 24h from the
moment rig first sees them gone. A lease listed by Vast is active unless this
machine released it (`destroy_pending`) or the sweep could not destroy it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from rig import budget, labels
from rig.errors import RigError
from rig.ids import orphan_id
from rig.models import (
    HISTORY_STATES,
    CachedLease,
    Charges,
    Instance,
    Job,
    Label,
    ProbeResult,
    SweptEntry,
    WarningItem,
)
from rig.state import GUARD_LAYERS, derive_state, effective_expiry, make_warning, resolve_state
from rig.timeutil import iso

if TYPE_CHECKING:
    from rig.cache import CacheData
    from rig.context import Context
    from rig.remote import SshTarget

HISTORY_KEEP_S = 86_400
PROBE_TIMEOUT_S = 5.0
MAX_PROBE_THREADS = 16
ZERO = Decimal("0")
BUDGET_HINT = "Run rig status to see today's spend, then release a lease or shorten the TTL."


@dataclass
class Snapshot:
    """The account after one refresh.

    `leases` holds active and history leases keyed by lease id. `instances` is
    the listing after the sweep. `charges` holds today's billing once `spend`
    has read it. `cached_at` is set when the snapshot comes from the cache file.
    """

    now: int
    instances: list[Instance]
    leases: dict[str, CachedLease]
    orphans: list[Instance]
    unreadable: list[Instance]
    swept: list[SweptEntry] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)
    charges: Charges | None = None
    cached_at: int | None = None

    def active(self) -> list[CachedLease]:
        """Return leases outside history, sorted by lease id."""
        return sorted(
            (lease for lease in self.leases.values() if lease.state not in HISTORY_STATES),
            key=lambda lease: lease.lease,
        )

    def history(self) -> list[CachedLease]:
        """Return leases in history, sorted by lease id."""
        return sorted(
            (lease for lease in self.leases.values() if lease.state in HISTORY_STATES),
            key=lambda lease: lease.lease,
        )

    def instance(self, instance_id: int) -> Instance | None:
        """Return the listed instance row with this id."""
        for inst in self.instances:
            if inst.id == instance_id:
                return inst
        return None

    def live_instances(self) -> list[Instance]:
        """Return the rows of active leases, orphans and unreadable rows."""
        ids = {lease.instance_id for lease in self.active()}
        ids.update(inst.id for inst in self.orphans)
        ids.update(inst.id for inst in self.unreadable)
        return [inst for inst in self.instances if inst.id in ids]


@dataclass
class _Rows:
    managed: list[tuple[Instance, Label]]
    orphans: list[Instance]
    unreadable: list[tuple[Instance, str]]


def classify(instances: list[Instance]) -> _Rows:
    """Split rows into managed leases, orphans and unreadable `rig:` rows.

    A second row carrying an already-seen lease id counts as unreadable, so the
    lowest instance id keeps the lease.
    """
    rows = _Rows([], [], [])
    seen: set[str] = set()
    for inst in sorted(instances, key=lambda i: i.id):
        parsed = labels.parse(inst.label)
        if parsed is None:
            rows.orphans.append(inst)
        elif isinstance(parsed, labels.Unreadable):
            rows.unreadable.append((inst, parsed.reason))
        elif parsed.lease in seen:
            rows.unreadable.append((inst, f"duplicate lease id {parsed.lease}"))
        else:
            seen.add(parsed.lease)
            rows.managed.append((inst, parsed))
    return rows


def unreadable_warning(inst: Instance, reason: str) -> WarningItem:
    return make_warning("label_unreadable", orphan_id(inst.id), f"label unreadable: {reason}")


def endpoint(inst: Instance) -> tuple[str, int] | None:
    """Return the SSH host and port for a row (spec §5.3), or None before it has one.

    Direct rows use `public_ipaddr` and the port mapped to 22. Proxy rows use
    `ssh_host` and `ssh_port`. A row without a runtype tries direct first.
    """
    direct = (inst.public_ipaddr, inst.ports.get(22))
    proxy = (inst.ssh_host, inst.ssh_port)
    order = [proxy, direct] if inst.runtype == "ssh_proxy" else [direct, proxy]
    for host, port in order:
        if host and port:
            return host, port
    return None


def ssh_target(lease: CachedLease) -> SshTarget:
    """Return the SSH endpoint for a lease. Raise `lease_pending` when it has none."""
    from rig.remote import SshTarget

    if not lease.ssh_host or not lease.ssh_port:
        raise RigError(
            "lease_pending",
            f"Lease {lease.lease} has no SSH endpoint yet.",
            f"Wait for the box, then run rig status {lease.lease}.",
        )
    return SshTarget(instance_id=lease.instance_id, host=lease.ssh_host, port=lease.ssh_port)


def past_clock(label: Label, now: int) -> bool:
    """Return True when the sweep destroys this label (spec §6 item 2)."""
    if label.expires is not None:
        return now > label.expires
    return now > label.created + label.ttl


def _reread_matches(ctx: Context, instance_id: int, read_expires: int | None) -> bool:
    row = ctx.provider.get_instance(instance_id)
    if row is None:
        return False
    parsed = labels.parse(row.label)
    return isinstance(parsed, Label) and parsed.expires == read_expires


def write_label(ctx: Context, instance_id: int, read_expires: int | None, label: Label) -> bool:
    """Re-read the row and write `label` when its `expires` still equals `read_expires`.

    Return False and write nothing when the row is gone or `expires` moved
    (spec §6 Robustness). Provider failures raise.
    """
    text = labels.format_label(label)
    if not _reread_matches(ctx, instance_id, read_expires):
        return False
    ctx.provider.set_label(instance_id, text)
    return True


def destroy_checked(ctx: Context, instance_id: int, read_expires: int | None) -> bool:
    """Re-read the row and destroy it when its `expires` still equals `read_expires`.

    Return False and destroy nothing when the row is gone or `expires` moved.
    Provider failures raise.
    """
    if not _reread_matches(ctx, instance_id, read_expires):
        return False
    ctx.provider.destroy(instance_id)
    return True


def _copy_row(lease: CachedLease, inst: Instance, label: Label) -> None:
    lease.instance_id = inst.id
    lease.label = label
    lease.gpu = inst.gpu_name
    lease.gpus = inst.num_gpus
    lease.vram_gb = inst.gpu_ram_gb
    lease.price_per_hr = inst.dph_total
    lease.image = inst.image
    lease.actual_status = inst.actual_status
    lease.ports = dict(inst.ports)
    found = endpoint(inst)
    lease.ssh_host, lease.ssh_port = found if found is not None else (None, None)


def _new_lease(inst: Instance, label: Label) -> CachedLease:
    lease = CachedLease(lease=label.lease, instance_id=inst.id, label=label, state="pending")
    _copy_row(lease, inst, label)
    return lease


def lease_from_row(inst: Instance, label: Label) -> CachedLease:
    """Return a `pending` cached lease built from an instance row and its label."""
    return _new_lease(inst, label)


def store_lease(ctx: Context, lease: CachedLease) -> None:
    """Write one lease into `leases.json` under the lock, keeping every other entry."""
    with ctx.cache.lock():
        data = ctx.cache.load()
        data.leases[lease.lease] = lease
        ctx.cache.save(data)


def _sweep(
    ctx: Context, rows: _Rows, leases: dict[str, CachedLease], now: int
) -> tuple[list[SweptEntry], dict[int, Instance | None]]:
    """Destroy managed rows past their clock.

    Return the swept entries and the rows to replace in the listing: None for
    a destroyed or vanished row, the re-read row when `expires` moved.
    """
    swept: list[SweptEntry] = []
    replaced: dict[int, Instance | None] = {}
    for inst, label in rows.managed:
        cached = leases.get(label.lease)
        if cached is not None and cached.destroy_pending:
            continue
        if not past_clock(label, now):
            continue
        ok, error = True, None
        try:
            row = ctx.provider.get_instance(inst.id)
            if row is None:
                replaced[inst.id] = None
                continue
            fresh = labels.parse(row.label)
            if not isinstance(fresh, Label) or fresh.expires != label.expires:
                replaced[inst.id] = row
                continue
            ctx.provider.destroy(inst.id)
        except RigError as err:
            ok, error = False, err.code
        lease = cached if cached is not None else _new_lease(inst, label)
        _copy_row(lease, inst, label)
        lease.state = "expired"
        lease.expired_at = effective_expiry(label)
        if ok:
            replaced[inst.id] = None
            lease.history_since = now
            lease.last_provider_error = None
        else:
            lease.last_provider_error = f"destroy failed: {error}"
        leases[label.lease] = lease
        swept.append(SweptEntry(lease.lease, label.name, iso(effective_expiry(label)), ok, error))
    return swept, replaced


def _to_history(lease: CachedLease, now: int) -> None:
    if lease.state in HISTORY_STATES:
        if lease.state == "released" and lease.destroy_pending:
            lease.destroy_pending = False
            lease.history_since = now
        elif lease.history_since is None:
            lease.history_since = now
        return
    if lease.released_here:
        lease.state = "released"
        lease.destroy_pending = False
    elif now > effective_expiry(lease.label):
        lease.state = "expired"
        lease.expired_at = effective_expiry(lease.label)
    else:
        lease.state = "gone"
    lease.history_since = now


@dataclass
class _Probed:
    result: ProbeResult | None
    adopt_missing: list[str] | None = None


def _probe_one(ctx: Context, lease: CachedLease) -> _Probed:
    try:
        target = ssh_target(lease)
        result = ctx.box.probe(target, lease.label.expires, timeout=PROBE_TIMEOUT_S)
    except (RigError, OSError):
        return _Probed(None)
    if result.startup_exit == -1:
        result = dataclasses.replace(result, startup_interrupted=True)
    probed = _Probed(result)
    if lease.adopted and _layers(result.guard_missing):
        try:
            probed.adopt_missing = _layers(ctx.box.adopt(target, effective_expiry(lease.label)))
        except (RigError, OSError):
            pass
    return probed


def _layers(names: list[str]) -> list[str]:
    present = set(names)
    return [layer for layer in GUARD_LAYERS if layer in present]


def _merge_jobs(cached: list[Job], fresh: list[Job]) -> list[Job]:
    by_id = {job.id: job for job in cached}
    for job in fresh:
        by_id[job.id] = job
    return list(by_id.values())


def _apply_probe(ctx: Context, lease: CachedLease, probed: _Probed, now: int) -> None:
    result = probed.result
    derived = derive_state(lease.actual_status, result, lease.reachable_at is not None)
    lease.state = resolve_state(lease.state, derived)
    if result is None:
        lease.guard_missing = _layers(lease.guard_missing + lease.label.miss)
        return
    lease.reachable_at = now
    lease.unsupported = list(result.unsupported)
    lease.startup_started = result.startup_started
    lease.startup_interrupted = result.startup_interrupted
    lease.startup_exit = None if result.startup_exit == -1 else result.startup_exit
    lease.jobs = _merge_jobs(lease.jobs, result.jobs)
    missing = probed.adopt_missing if probed.adopt_missing is not None else _layers(result.guard_missing)
    lease.guard_missing = missing
    label = lease.label
    wanted = dataclasses.replace(label, miss=list(missing))
    if label.expires is None and result.clock_expires is not None:
        wanted.expires = result.clock_expires
    if wanted.expires == label.expires and wanted.miss == label.miss:
        return
    try:
        if write_label(ctx, lease.instance_id, label.expires, wanted):
            lease.label = wanted
        else:
            row = ctx.provider.get_instance(lease.instance_id)
            parsed = labels.parse(row.label) if row is not None else None
            if isinstance(parsed, Label):
                lease.label = parsed
    except RigError as err:
        lease.last_provider_error = err.message


def _probe_all(ctx: Context, leases: list[CachedLease], now: int) -> None:
    if not leases:
        return
    with ThreadPoolExecutor(max_workers=min(MAX_PROBE_THREADS, len(leases))) as pool:
        results = list(pool.map(lambda lease: _probe_one(ctx, lease), leases))
    for lease, probed in zip(leases, results):
        _apply_probe(ctx, lease, probed, now)


def refresh(ctx: Context, probe: bool = True) -> Snapshot:
    """List instances, sweep expired leases, reconcile the cache, probe running boxes and save.

    Account warnings cover `clock_unverified`, `label_unreadable` and
    `cache_rebuilt`. Callers add per-lease and `orphan` warnings.
    """
    with ctx.cache.lock():
        data = ctx.cache.load()
        instances = ctx.provider.list_instances()
        now = ctx.clock.now()
        warnings: list[WarningItem] = []
        if not ctx.clock.verified:
            warnings.append(make_warning(
                "clock_unverified", None, "provider sent no Date header; using the local clock"
            ))
        rows = classify(instances)
        leases = data.leases
        swept, replaced = _sweep(ctx, rows, leases, now)
        instances = [
            row for row in (replaced.get(inst.id, inst) for inst in instances) if row is not None
        ]
        rows = classify(instances)
        warnings.extend(unreadable_warning(inst, reason) for inst, reason in rows.unreadable)

        listed = {label.lease for _, label in rows.managed}
        for lease_id, lease in list(leases.items()):
            if lease_id not in listed:
                _to_history(lease, now)
                if lease.history_since is not None and now - lease.history_since >= HISTORY_KEEP_S:
                    del leases[lease_id]

        to_probe: list[CachedLease] = []
        swept_ids = {entry.lease for entry in swept}
        for inst, label in rows.managed:
            found = leases.get(label.lease)
            if found is None:
                found = _new_lease(inst, label)
                leases[label.lease] = found
            else:
                _copy_row(found, inst, label)
            lease = found
            if lease.lease in swept_ids:
                continue
            if lease.state == "released" or lease.destroy_pending:
                continue
            if lease.state in HISTORY_STATES:
                lease.state = "pending"
                lease.history_since = None
                lease.expired_at = None
            running = (inst.actual_status or "").strip().lower() == "running"
            if running and probe:
                to_probe.append(lease)
            elif running:
                lease.guard_missing = _layers(lease.guard_missing + lease.label.miss)
            else:
                _apply_probe(ctx, lease, _Probed(None), now)
        _probe_all(ctx, to_probe, now)

        if data.rebuilt:
            warnings.append(make_warning(
                "cache_rebuilt", None, "leases.json was unreadable; rebuilt from the provider"
            ))
        data.leases = leases
        data.instances = instances
        data.cached_at = now
        data.rebuilt = False
        ctx.cache.save(data)
        return Snapshot(
            now=now,
            instances=instances,
            leases=leases,
            orphans=rows.orphans,
            unreadable=[inst for inst, _ in rows.unreadable],
            swept=swept,
            warnings=warnings,
            charges=_today_charges(data, now),
        )


def cached_snapshot(ctx: Context) -> Snapshot:
    """Build a snapshot from `leases.json` with no network call.

    `now` comes from the local clock. Warnings cover `label_unreadable` and
    `cache_rebuilt`. `charges` holds the cached billing for today of any age.
    """
    data = ctx.cache.load()
    now = ctx.clock.now()
    rows = classify(data.instances)
    warnings = [unreadable_warning(inst, reason) for inst, reason in rows.unreadable]
    if data.rebuilt:
        warnings.append(make_warning(
            "cache_rebuilt", None, "leases.json was unreadable; run rig status to rebuild it"
        ))
    return Snapshot(
        now=now,
        instances=data.instances,
        leases=data.leases,
        orphans=rows.orphans,
        unreadable=[inst for inst, _ in rows.unreadable],
        warnings=warnings,
        charges=_today_charges(data, now),
        cached_at=data.cached_at,
    )


def _today_charges(data: CacheData, now: int) -> Charges | None:
    if data.charges is None or data.charges_start != budget.day_start(now):
        return None
    return data.charges


def _read_charges(ctx: Context, now: int) -> Charges | None:
    start = budget.day_start(now)
    with ctx.cache.lock():
        data = ctx.cache.load()
        if data.charges_start == start and budget.billing_fresh(data.charges_at, now):
            return data.charges
        try:
            charges = ctx.provider.charges(start, now)
        except RigError:
            return None
        data.charges, data.charges_at, data.charges_start = charges, now, start
        ctx.cache.save(data)
        return charges


def spend_from(charges: Charges | None, snap: Snapshot) -> tuple[Decimal | None, str | None]:
    """Return `spent_today` and its `spend_source` from charges already read.

    `spend_source` is `billing` when billed charges cover the whole figure,
    `estimated` when nothing is billed yet and price × time fills it, and
    `mixed` when both parts are non-zero. Both are None when coverage is unknown.
    """
    if charges is None:
        return None, None
    start = budget.day_start(snap.now)
    spent = budget.spent_today(charges, snap.instances, snap.now, start)
    if spent is None:
        return None, None
    estimate = spent - charges.total
    if estimate == ZERO:
        return spent, "billing"
    if charges.total == ZERO:
        return spent, "estimated"
    return spent, "mixed"


def spend(ctx: Context, snap: Snapshot) -> tuple[Decimal | None, str | None]:
    """Return `spent_today` and its `spend_source` (see `spend_from`).

    Charges are read once per 60s and cached in `leases.json`. A failed
    charges call counts as unknown coverage. Sets `snap.charges`.
    """
    snap.charges = _read_charges(ctx, snap.now)
    return spend_from(snap.charges, snap)


def projection_for(
    ctx: Context,
    snap: Snapshot,
    extra: Decimal = ZERO,
    replace: Mapping[str, int] | None = None,
) -> tuple[Decimal, Decimal]:
    """Return `(projected, without_action)` for the account (spec §5.2).

    `without_action` is spend plus every active lease's commitment to its
    effective expiry. `projected` swaps in the expiry from `replace` (lease id
    to new expiry) for those leases and adds `extra`. Raise
    `spend_unavailable` when spend is unknown.
    """
    spent = budget.require_spent(spend(ctx, snap)[0])
    active = snap.active()
    swap = replace or {}
    base = budget.lease_commitments(active)
    changed = [
        (lease.price_per_hr, swap.get(lease.lease, effective_expiry(lease.label)))
        for lease in active
    ]
    without = budget.projection(spent, base, snap.now, ZERO)
    projected = budget.projection(spent, changed, snap.now, extra)
    return projected, without


def budget_check(
    ctx: Context,
    snap: Snapshot,
    extra: Decimal = ZERO,
    hint: str = BUDGET_HINT,
    replace: Mapping[str, int] | None = None,
) -> tuple[Decimal, Decimal]:
    """Refuse an action whose projection passes `daily_budget`.

    Return `(projected, daily_budget)` so callers can add `budget_low` with
    `budget.budget_low_warning`. Raise `spend_unavailable` or `budget_exceeded`.
    """
    projected, without = projection_for(ctx, snap, extra, replace)
    daily = ctx.settings.daily_budget
    budget.check(projected, without, daily, hint)
    return projected, daily
