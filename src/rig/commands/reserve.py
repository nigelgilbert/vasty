"""`rig reserve` (spec §4.1, §5.1, §5.2, §5.3).

`reserve_lease` does the work for `reserve` and for auto-reserved `run` and
`serve`. Under the `leases.json` lock it checks the name, searches offers,
checks the budget, registers the SSH key and creates the instance. A create
that times out is recovered by listing instances for the lease id. Outside
the lock it waits for the lease to leave `pending` by refreshing every
`WAIT_POLL_S` seconds.

The wait gives up at the lease's effective expiry with `box_unreachable`.
Once SSH answers, every required port has `PORT_GRACE_S` seconds to show a
mapping before `port_mapping_missing`; on a direct offer the required ports
are every requested port, and a proxy offer has none. A box this call created
and then gave up on is destroyed before the error propagates.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, TypeVar

from rig import budget, engine, ids, labels, onstart, views
from rig.cli import Outcome
from rig.commands._common import taken_ids
from rig.context import Context
from rig.errors import RigError, invalid
from rig.keys import public_key
from rig.models import (
    HISTORY_STATES,
    CachedLease,
    CreateRequest,
    Instance,
    Label,
    Offer,
    OfferQuery,
    ReserveResult,
    SweptEntry,
    WarningItem,
)
from rig.state import GUARD_LAYERS, effective_expiry, guard, lease_warnings, make_warning
from rig.timeutil import format_duration, iso

if TYPE_CHECKING:
    from rig.engine import Snapshot

DEFAULT_IMAGE = "rig/base:cuda12.4"
DEFAULT_PORTS = (22, 8000, 8080)
MAX_PORTS = 64
WAIT_POLL_S = 10.0
PORT_GRACE_S = 60
RECOVER_POLL_S = 5.0
RECOVER_WINDOW_S = 60
RESERVE_BUDGET_HINT = "Shorten --ttl, lower --max-price, or release a lease. Run rig status."


@dataclass
class Reserved:
    """A reserved or reused lease and its `reserve` output."""

    result: ReserveResult
    lease: CachedLease


def reserve_lease(
    ctx: Context, args: argparse.Namespace, snap: Snapshot, *, ttl: int, wait: bool
) -> Reserved:
    """Reserve a box from the creation flags in `args` and `ctx.settings`.

    Apply name idempotency, the budget check with `ttl`, offer search, create
    with recovery and the readiness wait. `run` and `serve` call this for
    auto-reserve. Raise `RigError` on failure; a box this call created and
    then gave up on is destroyed before the error propagates.
    """
    settings = ctx.settings
    name = getattr(args, "name", None)
    group = getattr(args, "group", None)
    owner = settings.owner
    if name is not None:
        ids.validate_value("name", name)
    if group is not None:
        ids.validate_value("group", group)
    ports = request_ports(settings.ports)
    warnings: list[WarningItem] = []
    swept = list(snap.swept)
    created = False
    required: list[int] = []

    with ctx.cache.lock():
        hit = _name_hit(ctx, snap, name, owner) if name is not None else None
        if hit is not None:
            mismatch = flag_mismatch(ctx, args, hit, ttl, ports)
            if mismatch is not None:
                warnings.append(mismatch)
        else:
            custom = settings.image != DEFAULT_IMAGE
            onstart_cmd = onstart.build_onstart(ttl, settings.startup, custom)
            query = OfferQuery(
                gpu=settings.gpu, vram_min_gb=settings.vram, gpus=settings.gpus,
                disk_gb=settings.disk, max_price=settings.max_price, region=settings.region,
            )
            offer = choose_offer(ctx, query)
            projected, daily = engine.budget_check(
                ctx, snap, budget.cost(offer.dph_total, ttl), RESERVE_BUDGET_HINT,
                leases=engine.locked_active(ctx, snap),
            )
            low = budget.budget_low_warning(projected, daily)
            if low is not None:
                warnings.append(low)
            register_key(ctx)
            taken = taken_ids(snap)
            lease_id = ids.new_lease_id(ctx.random_hex, taken)
            now = ctx.clock.now()
            label = Label(lease=lease_id, owner=owner, created=now, ttl=ttl, name=name, group=group)
            request = CreateRequest(
                offer_id=offer.id,
                image=settings.image,
                disk_gb=settings.disk,
                label=labels.format_label(label),
                onstart=onstart_cmd,
                ports=ports,
                runtype="ssh_direct" if offer.direct_port_count > 0 else "ssh_proxy",
            )
            row = create_with_recovery(ctx, request, lease_id)
            hit = _new_cached(row, label, offer, request)
            engine.store_lease(ctx, hit)
            created = True
            required = ports if request.runtype == "ssh_direct" else []
    lease = hit
    reused = not created

    if wait and lease.state == "pending":
        lease, more_swept, account = wait_ready(ctx, lease, required, created)
        swept += more_swept
        warnings = account + warnings
    else:
        warnings = list(snap.warnings) + warnings
    warnings += lease_warnings(lease, ctx.clock.now(), settings.warn_before_expiry)
    result = reserve_result(lease, ctx.clock.now(), reused, warnings, swept)
    return Reserved(result=result, lease=lease)


def request_ports(extra: list[int]) -> list[int]:
    """Return the default ports plus `extra`, deduplicated in order.

    `config` checks each port's type and range. Raise `invalid_arguments` for
    more than 64 ports.
    """
    out: list[int] = []
    for port in (*DEFAULT_PORTS, *extra):
        if port not in out:
            out.append(port)
    if len(out) > MAX_PORTS:
        raise invalid(
            f"{len(out)} ports requested; Vast allows {MAX_PORTS}, defaults 22, 8000 and 8080 included.",
            "Pass fewer --ports.",
        )
    return out


def _name_hit(ctx: Context, snap: Snapshot, name: str, owner: str) -> CachedLease | None:
    """Return the active lease named `name` for `owner` from the snapshot or the cache file."""
    data = ctx.cache.load()
    pool = list(snap.active()) + [
        lease for lease in data.leases.values()
        if lease.lease not in snap.leases and lease.state not in HISTORY_STATES
    ]
    hits = sorted(
        (lease for lease in pool if lease.label.name == name and lease.label.owner == owner),
        key=lambda lease: lease.lease,
    )
    if len(hits) > 1:
        matches = [lease.lease for lease in hits]
        raise RigError(
            "ambiguous_target",
            f"Name {name!r} matches {len(matches)} leases of owner {owner}.",
            f"Release the extra lease: rig release {matches[-1]}.",
            details={"matches": matches},
        )
    return hits[0] if hits else None


def _gpu_matches(wanted: str, actual: str | None) -> bool:
    from rig.provider import gpu_name_filter

    if actual is None:
        return False
    rule = gpu_name_filter(wanted)
    names = [rule["eq"]] if "eq" in rule else list(rule.get("in", []))
    return actual.lower() in {str(n).lower() for n in names}


def flag_mismatch(
    ctx: Context, args: argparse.Namespace, lease: CachedLease, ttl: int, ports: list[int]
) -> WarningItem | None:
    """Return the `flag_mismatch` warning listing flags the reused lease does not match."""
    settings = ctx.settings
    given = {key for key, source in settings.sources.items() if source == "flag"}
    differ: list[str] = []
    group = getattr(args, "group", None)
    if group is not None and group != lease.label.group:
        differ.append("--group")
    if "ttl" in given and ttl != lease.label.ttl:
        differ.append("--ttl")
    if "gpu" in given and settings.gpu and not _gpu_matches(settings.gpu, lease.gpu):
        differ.append("--gpu")
    if "vram" in given and settings.vram is not None and (
        lease.vram_gb is None or lease.vram_gb < settings.vram
    ):
        differ.append("--vram")
    if "gpus" in given and settings.gpus != lease.gpus:
        differ.append("--gpus")
    if "max_price" in given and lease.price_per_hr > settings.max_price:
        differ.append("--max-price")
    if "image" in given and lease.image is not None and settings.image != lease.image:
        differ.append("--image")
    if "ports" in given and lease.ports and any(p not in lease.ports for p in ports):
        differ.append("--ports")
    if not differ:
        return None
    message = f"lease {lease.lease} differs from {', '.join(differ)}"
    return make_warning("flag_mismatch", lease.lease, message)


def _offer_ok(offer: Offer, query: OfferQuery) -> bool:
    if offer.num_gpus != query.gpus or offer.dph_total > query.max_price:
        return False
    if query.vram_min_gb is not None and offer.gpu_ram_gb < query.vram_min_gb:
        return False
    return not query.gpu or _gpu_matches(query.gpu, offer.gpu_name)


def rank_offers(offers: list[Offer], query: OfferQuery) -> list[Offer]:
    """Filter offers by the query, then sort by reliability, download bandwidth, price and id."""
    kept = [offer for offer in offers if _offer_ok(offer, query)]
    return sorted(kept, key=lambda o: (-o.reliability, -o.inet_down, o.dph_total, o.id))


def _no_offers(query: OfferQuery) -> RigError:
    parts = []
    if query.gpu:
        parts.append(f"gpu={query.gpu}")
    if query.vram_min_gb is not None:
        parts.append(f"vram>={query.vram_min_gb:g}GB")
    if query.gpus != 1:
        parts.append(f"gpus={query.gpus}")
    if query.region:
        parts.append(f"region={query.region}")
    what = " ".join(parts) or "the request"
    higher = (query.max_price * Decimal("1.5")).quantize(Decimal("0.01"))
    tips = [f"--max-price {higher}"]
    if query.gpu:
        tips.append("another --gpu")
    if query.vram_min_gb is not None:
        tips.append("a lower --vram")
    if query.region:
        tips.append("relax --region")
    hint = "Try " + (", ".join(tips[:-1]) + ", or " + tips[-1] if len(tips) > 1 else tips[0]) + "."
    return RigError(
        "no_offers", f"No offers match {what} under ${query.max_price}/hr.", hint,
    )


def choose_offer(ctx: Context, query: OfferQuery) -> Offer:
    """Search offers and return the best one. Raise `no_offers` when none match."""
    ranked = rank_offers(ctx.provider.search_offers(query), query)
    if not ranked:
        raise _no_offers(query)
    return ranked[0]


def _key_body(text: str) -> str:
    return " ".join(text.split()[:2])


def register_key(ctx: Context) -> None:
    """Register the public key on the account when no matching key exists (spec §5.3)."""
    key = public_key(ctx)
    if key is None:
        ctx.warn("rig: no SSH public key found next to ssh_key; skipping key registration")
        return
    body = _key_body(key)
    if any(_key_body(k.public_key) == body for k in ctx.provider.list_ssh_keys()):
        return
    ctx.provider.attach_ssh_key(key)


def _rows_for(instances: list[Instance], lease_id: str) -> list[Instance]:
    out = []
    for inst in instances:
        parsed = labels.parse(inst.label)
        if isinstance(parsed, Label) and parsed.lease == lease_id:
            out.append(inst)
    return sorted(out, key=lambda inst: inst.id)


def create_with_recovery(ctx: Context, request: CreateRequest, lease_id: str) -> Instance | int:
    """Send one create call. On a timeout, find the instance by its `lease=` label.

    Return the created row, or its instance id when no row is at hand. Keep
    the lowest instance id among several matches and destroy the rest. Raise
    `provider_error` naming the lease id when no match appears within 60s.
    """
    from rig.provider import ProviderTimeout

    try:
        return ctx.provider.create(request)
    except ProviderTimeout:
        pass
    waited = 0.0
    while True:
        try:
            rows = _rows_for(ctx.provider.list_instances(), lease_id)
        except RigError:
            rows = []
        if rows:
            keep, extra = rows[0], rows[1:]
            for inst in extra:
                try:
                    ctx.provider.destroy(inst.id)
                except RigError as err:
                    ctx.warn(f"rig: could not destroy duplicate instance {inst.id}: {err.message}")
            return keep
        if waited >= RECOVER_WINDOW_S:
            break
        ctx.sleep(RECOVER_POLL_S)
        waited += RECOVER_POLL_S
    raise RigError(
        "provider_error",
        f"Create timed out and no instance carries lease {lease_id} after {RECOVER_WINDOW_S}s.",
        f"Run rig status to look for {lease_id} before reserving again.",
        details={"lease": lease_id},
    )


def _new_cached(
    row: Instance | int, label: Label, offer: Offer, request: CreateRequest
) -> CachedLease:
    if isinstance(row, Instance):
        lease = engine.lease_from_row(row, label)
    else:
        lease = CachedLease(lease=label.lease, instance_id=row, label=label, state="pending")
    lease.guard_missing = list(GUARD_LAYERS)
    if lease.gpu is None:
        lease.gpu = offer.gpu_name
        lease.gpus = offer.num_gpus
        lease.vram_gb = offer.gpu_ram_gb
    if lease.price_per_hr == 0:
        lease.price_per_hr = offer.dph_total
    if lease.image is None:
        lease.image = request.image
    return lease


_E = TypeVar("_E", bound=BaseException)


def _row_expires(ctx: Context, instance_id: int) -> int | None:
    """Return `expires` from the row's label, or None when the row or the value is missing."""
    label = engine.row_label(ctx, instance_id)
    return label.expires if label else None


def _give_up(ctx: Context, lease: CachedLease, created: bool, err: _E) -> _E:
    """Destroy a box this call created and return `err` to raise.

    A stored label without `expires` takes the value from the row, since a
    probe may have written the clock to the label before the wait stopped.
    The lease turns `released` only when Vast accepts the destroy or the row
    is already gone. Otherwise it stays active and a stderr line names the
    `rig release` fix.
    """
    if not created:
        return err
    fix = f"Run rig release {lease.lease}."
    try:
        expires = lease.label.expires
        if expires is None:
            expires = _row_expires(ctx, lease.instance_id)
        destroyed = engine.destroy_checked(ctx, lease.instance_id, expires)
        if not destroyed and ctx.provider.get_instance(lease.instance_id) is not None:
            ctx.warn(f"rig: {lease.lease} changed before it could be destroyed. {fix}")
            return err
        engine.mark_released(lease, ctx.clock.now())
        engine.store_lease(ctx, lease)
    except RigError as failure:
        ctx.warn(f"rig: could not destroy {lease.lease}: {failure.message} {fix}")
    return err


def wait_ready(
    ctx: Context, lease: CachedLease, required: list[int], created: bool
) -> tuple[CachedLease, list[SweptEntry], list[WarningItem]]:
    """Refresh until the lease leaves `pending` and the `required` ports are mapped.

    Return the lease, the entries every refresh swept and the latest account
    warnings. Raise `box_unreachable`, `image_unsupported` or
    `port_mapping_missing`. A refresh error or Ctrl-C during the wait destroys
    a box this call created and re-raises.
    """
    swept: list[SweptEntry] = []
    ready_at: int | None = None
    while True:
        try:
            snap = engine.refresh(ctx)
        except (RigError, KeyboardInterrupt) as exc:
            raise _give_up(ctx, lease, created, exc)
        swept += snap.swept
        now = snap.now
        fresh = snap.leases.get(lease.lease)
        if fresh is None or fresh.state in HISTORY_STATES:
            raise RigError(
                "box_unreachable",
                f"Lease {lease.lease} ended before it became ready.",
                f"Run rig status {lease.lease}, then rig reserve again.",
            )
        lease = fresh
        if lease.unsupported:
            missing = ", ".join(lease.unsupported)
            raise _give_up(ctx, lease, created, RigError(
                "image_unsupported",
                f"Image {lease.image or '?'} lacks {missing}.",
                "Use an image with Linux, bash, root and apt-get, or drop --image.",
                details={"missing": list(lease.unsupported)},
            ))
        deadline = effective_expiry(lease.label)
        if lease.state != "pending":
            unmapped = [p for p in required if p not in lease.ports]
            if lease.state != "running" or not unmapped:
                return lease, swept, list(snap.warnings)
            ready_at = now if ready_at is None else ready_at
            if now >= min(deadline, ready_at + PORT_GRACE_S):
                raise _give_up(ctx, lease, created, RigError(
                    "port_mapping_missing",
                    f"Lease {lease.lease} has no external mapping for port "
                    f"{', '.join(str(p) for p in unmapped)}.",
                    "Run rig reserve again; another offer maps its ports.",
                    details={"ports": unmapped},
                ))
        elif now >= deadline:
            raise _give_up(ctx, lease, created, RigError(
                "box_unreachable",
                f"Lease {lease.lease} did not become ready before its clock ran out.",
                "Run rig reserve again, or pick another offer with --gpu or --region.",
            ))
        try:
            ctx.sleep(WAIT_POLL_S)
        except (RigError, KeyboardInterrupt) as exc:
            raise _give_up(ctx, lease, created, exc)


def reserve_result(
    lease: CachedLease,
    now: int,
    reused: bool,
    warnings: list[WarningItem],
    swept: list[SweptEntry],
) -> ReserveResult:
    """Build the §4.1 output. A `pending` lease has null clock and endpoint fields."""
    level, missing = guard(lease)
    pending = lease.state == "pending"
    expiry = effective_expiry(lease.label)
    endpoint = views.endpoint_fields(lease)
    return ReserveResult(
        lease=lease.lease,
        name=lease.label.name,
        owner=lease.label.owner,
        group=lease.label.group,
        state=lease.state,
        guard=level,
        guard_missing=missing,
        reused=reused,
        gpu=lease.gpu,
        gpus=lease.gpus,
        vram_gb=lease.vram_gb,
        price_per_hr=lease.price_per_hr,
        expires_at=None if pending else iso(expiry),
        ttl_remaining_s=None if pending else max(0, expiry - now),
        ssh=None if pending else endpoint.ssh,
        rsync_target=None if pending else endpoint.rsync_target,
        ssh_port=None if pending else endpoint.ssh_port,
        ports=None if pending else endpoint.ports,
        warnings=warnings,
        swept=swept,
    )


def render(result: ReserveResult) -> str:
    """Return the human summary: lease line, ssh line, swept and warnings."""
    from rig.commands.status import swept_lines, warning_lines
    from rig.output import money

    head = [result.lease]
    if result.name:
        head.append(result.name)
    head.append(result.state)
    head.append(f"{result.gpus}× {result.gpu}" if result.gpus > 1 else str(result.gpu or "?"))
    head.append(f"${money(result.price_per_hr):.2f}/hr")
    if result.ttl_remaining_s is not None:
        head.append(f"expires in {format_duration(result.ttl_remaining_s)}")
    if result.reused:
        head.append("reused")
    lines = ["  ".join(head)]
    if result.ssh:
        lines.append(result.ssh)
    elif result.state == "pending":
        lines.append(f"booting; run rig status {result.lease}")
    blocks = [lines, swept_lines(result.swept), warning_lines(result.warnings)]
    return "\n\n".join("\n".join(block) for block in blocks if block)


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    snap = engine.refresh(ctx)
    reserved = reserve_lease(
        ctx, args, snap, ttl=ctx.settings.ttl, wait=not getattr(args, "no_wait", False)
    )
    human = render(reserved.result) if ctx.mode == "human" else None
    return Outcome(reserved.result, human=human)
