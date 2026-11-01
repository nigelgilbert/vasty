"""`vasty reserve`.

`reserve_lease` does the work for `reserve` and for auto-reserved `run` and
`serve`. Under the `leases.json` lock it checks the name, searches offers,
registers the SSH key and creates the instance. A create
that times out is recovered by listing instances for the lease id. A create
that returns `success: false` lists instances for the lease id and destroys
each one. Outside the lock it starts `vasty sweep --follow` for the lease and
waits for the lease to leave `pending` by refreshing every `WAIT_POLL_S`
seconds.

A refresh error during the wait writes one stderr line and the wait goes on.
The wait gives up at the lease's effective expiry with `box_unreachable`.
Once SSH answers, every required port has `PORT_GRACE_S` seconds to show a
mapping before `port_mapping_missing`; on a direct offer the required ports
are every requested port, and a proxy offer has none. A box this call created
and then gave up on is destroyed before the error propagates. Every error
raised after create carries `lease` and `destroyed` in its details.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from vasty import engine, ids, labels, onstart, views
from vasty.cli import Outcome
from vasty.commands._common import merge_swept, taken_ids
from vasty.commands.sweep import spawn_follow
from vasty.context import Context
from vasty.errors import VastyError, invalid
from vasty.keys import public_key
from vasty.models import (
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
from vasty.state import (
    GUARD_LAYERS,
    effective_expiry,
    gpu_matches,
    hardware_mismatch,
    lease_warnings,
    make_warning,
    reuse_candidates,
    ttl_remaining,
)
from vasty.timeutil import format_duration, format_duration_exact, iso

if TYPE_CHECKING:
    from vasty.engine import Snapshot

DEFAULT_PORTS = (22, 8000, 8080)
MAX_PORTS = 64
WAIT_POLL_S = 10.0
PORT_GRACE_S = 60
RECOVER_POLL_S = 5.0
RECOVER_WINDOW_S = 60


@dataclass
class Reserved:
    """A reserved or reused lease and its `reserve` output."""

    result: ReserveResult
    lease: CachedLease


def reserve_lease(
    ctx: Context,
    args: argparse.Namespace,
    snap: Snapshot,
    *,
    ttl: int,
) -> Reserved:
    """Reserve a box from the creation flags in `args` and `ctx.settings`.

    Apply name idempotency, offer search, create with recovery and the
    readiness wait. `run` and `serve` call this for auto-reserve. Raise
    `VastyError` on failure; a box this call created and then gave up on is
    destroyed before the error propagates.

    A creation adds one `idle_box_available` warning per reuse candidate. A
    candidate maps every requested port.
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
            mismatch = flag_mismatch(ctx, args, hit, snap.instance(hit.instance_id), ttl, ports)
            if mismatch is not None:
                warnings.append(mismatch)
        else:
            for idle, shortfall in reuse_candidates(snap, settings, ttl, snap.now, ports):
                warnings.append(idle_warning(idle, shortfall, ttl, snap.now))
            onstart_cmd = onstart.build_onstart(ttl, settings.startup)
            query = OfferQuery(
                gpu=settings.gpu, vram_min_gb=settings.vram, gpus=settings.gpus,
                disk_gb=settings.disk, max_price=settings.max_price, region=settings.region,
                cuda=settings.cuda,
            )
            offer = choose_offer(ctx, query)
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
    not_spawned = spawn_follow(ctx, lease.lease)

    if lease.state == "pending":
        lease, more_swept, account = wait_ready(ctx, lease, required, created)
        swept = merge_swept(swept, more_swept)
        warnings = account + warnings
    else:
        warnings = list(snap.warnings) + warnings
    warnings += lease_warnings(lease, ctx.clock.now())
    if not_spawned is not None:
        warnings.append(not_spawned)
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
        raise VastyError(
            "ambiguous_target",
            f"Name {name!r} matches {len(matches)} leases of owner {owner}.",
            f"Release the extra lease: vasty release {matches[-1]}.",
            details={"matches": matches},
        )
    return hits[0] if hits else None


def flag_mismatch(
    ctx: Context,
    args: argparse.Namespace,
    lease: CachedLease,
    inst: Instance | None,
    ttl: int,
    ports: list[int],
) -> WarningItem | None:
    """Return the `flag_mismatch` warning listing flags the reused lease does not match.

    Hardware keys come from `hardware_mismatch` on the instance row `inst`,
    kept when a flag set them. Ports are checked when the lease has a mapping.
    """
    settings = ctx.settings
    given = {key for key, source in settings.sources.items() if source == "flag"}
    differ: list[str] = []
    group = getattr(args, "group", None)
    if group is not None and group != lease.label.group:
        differ.append("--group")
    if "ttl" in given and ttl != lease.label.ttl:
        differ.append("--ttl")
    hardware = hardware_mismatch(lease, inst, settings, ports if lease.ports else None)
    differ += ["--" + key.replace("_", "-") for key in hardware if key in given]
    if not differ:
        return None
    message = f"lease {lease.lease} differs from {', '.join(differ)}"
    return make_warning("flag_mismatch", lease.lease, message)


def idle_warning(lease: CachedLease, shortfall: int, ttl: int, now: int) -> WarningItem:
    """Return the `idle_box_available` warning for a reuse candidate.

    A candidate short of `ttl` names the shortfall and the `extend --to` that
    covers it.
    """
    named = f"{lease.lease} ({lease.label.name})" if lease.label.name else lease.lease
    vram = "?" if lease.vram_gb is None else str(int(lease.vram_gb))
    left = format_duration(ttl_remaining(lease.label, now))
    message = f"lease {named} is idle: {lease.gpu or '?'}, {lease.gpus}x{vram} GB, {left} left"
    if shortfall:
        message += f", {format_duration(shortfall)} short; extend --to {format_duration_exact(ttl)}"
    return make_warning("idle_box_available", lease.lease, message)


def _offer_ok(offer: Offer, query: OfferQuery) -> bool:
    if offer.num_gpus != query.gpus or offer.dph_total > query.max_price:
        return False
    if query.vram_min_gb is not None and offer.gpu_ram_gb < query.vram_min_gb:
        return False
    return not query.gpu or gpu_matches(query.gpu, offer.gpu_name)


def rank_offers(offers: list[Offer], query: OfferQuery) -> list[Offer]:
    """Filter offers by the query, then sort by reliability, download bandwidth, price and id."""
    kept = [offer for offer in offers if _offer_ok(offer, query)]
    return sorted(kept, key=lambda o: (-o.reliability, -o.inet_down, o.dph_total, o.id))


def _no_offers(query: OfferQuery) -> VastyError:
    parts = []
    if query.gpu:
        parts.append(f"gpu={query.gpu}")
    if query.vram_min_gb is not None:
        parts.append(f"vram>={query.vram_min_gb:g}GB")
    if query.gpus != 1:
        parts.append(f"gpus={query.gpus}")
    if query.region:
        parts.append(f"region={query.region}")
    if query.cuda is not None:
        parts.append(f"cuda>={query.cuda:g}")
    what = " ".join(parts) or "the request"
    tips = ["a higher --max-price"]
    if query.gpu:
        tips.append("another --gpu")
    if query.vram_min_gb is not None:
        tips.append("a lower --vram")
    if query.region:
        tips.append("relax --region")
    if query.cuda is not None:
        tips.append("a lower --cuda")
    hint = "Try " + (", ".join(tips[:-1]) + ", or " + tips[-1] if len(tips) > 1 else tips[0]) + "."
    return VastyError(
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
    """Register the public key on the account when no matching key exists."""
    key = public_key(ctx)
    if key is None:
        ctx.warn("vasty: no SSH public key found next to ssh_key; skipping key registration")
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
    On a `success: false` create, destroy every match and raise the create
    error through `_clear_rejected`.
    """
    from vasty.provider import CreateRejected, ProviderTimeout

    try:
        return ctx.provider.create(request)
    except ProviderTimeout:
        pass
    except CreateRejected as err:
        raise _clear_rejected(ctx, lease_id, err) from None
    waited = 0.0
    while True:
        try:
            rows = _rows_for(ctx.provider.list_instances(), lease_id)
        except VastyError:
            rows = []
        if rows:
            keep, extra = rows[0], rows[1:]
            for inst in extra:
                try:
                    ctx.provider.destroy(inst.id)
                except VastyError as err:
                    ctx.warn(
                        f"vasty: could not destroy duplicate instance {inst.id}: {err.message}"
                        f" Run vasty release i-{inst.id}."
                    )
            return keep
        if waited >= RECOVER_WINDOW_S:
            break
        ctx.sleep(RECOVER_POLL_S)
        waited += RECOVER_POLL_S
    raise VastyError(
        "provider_error",
        f"Create timed out and no instance carries lease {lease_id} after {RECOVER_WINDOW_S}s.",
        f"Run vasty status to look for {lease_id} before reserving again.",
        details={"lease": lease_id, "destroyed": False},
    )


def _clear_rejected(ctx: Context, lease_id: str, err: VastyError) -> VastyError:
    """List instances for `lease_id` after a `success: false` create and destroy each one.

    Return `err` with `lease`, `instance_id` and `destroyed` added to its
    details. `instance_id` is the lowest matching id, or None when no row
    carries the lease. `destroyed` is true when Vast accepted every destroy.
    With no row the hint sends the caller to `status` before a retry, since
    Vast can list the row late. A failed list or destroy writes one stderr
    line naming the fix.
    """
    try:
        rows = _rows_for(ctx.provider.list_instances(), lease_id)
    except VastyError as failure:
        ctx.warn(
            f"vasty: could not list instances for {lease_id}: {failure.message}"
            f" Run vasty status to look for {lease_id}."
        )
        rows = []
    destroyed = bool(rows)
    for inst in rows:
        try:
            ctx.provider.destroy(inst.id)
        except VastyError as failure:
            destroyed = False
            ctx.warn(
                f"vasty: could not destroy instance {inst.id} for {lease_id}: {failure.message}"
                f" Run vasty release i-{inst.id}."
            )
    instance_id = rows[0].id if rows else None
    if instance_id is None:
        err.hint = f"Run vasty status to look for {lease_id} before reserving again."
    err.details = {
        **(err.details or {}), "lease": lease_id, "instance_id": instance_id, "destroyed": destroyed,
    }
    return err


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
    `vasty release` fix. A `VastyError` gets `lease` and `destroyed` added to
    its details.
    """
    destroyed = created and _destroy_created(ctx, lease)
    if isinstance(err, VastyError):
        _name_lease(err, lease, destroyed)
    return err


def _destroy_created(ctx: Context, lease: CachedLease) -> bool:
    """Destroy the lease's box and mark it `released`. Return True when the lease turned `released`."""
    fix = f"Run vasty release {lease.lease}."
    try:
        expires = lease.label.expires
        if expires is None:
            expires = _row_expires(ctx, lease.instance_id)
        destroyed = engine.destroy_checked(ctx, lease.instance_id, expires)
        if not destroyed and ctx.provider.get_instance(lease.instance_id) is not None:
            ctx.warn(f"vasty: {lease.lease} changed before it could be destroyed. {fix}")
            return False
        engine.mark_released(lease, ctx.clock.now())
        engine.store_lease(ctx, lease)
    except VastyError as failure:
        ctx.warn(f"vasty: could not destroy {lease.lease}: {failure.message} {fix}")
        return False
    return True


def _name_lease(err: VastyError, lease: CachedLease, destroyed: bool) -> VastyError:
    """Add `lease` and `destroyed` to the details of `err` and return it."""
    err.details = {**(err.details or {}), "lease": lease.lease, "destroyed": destroyed}
    return err


def _not_ready(lease: CachedLease) -> VastyError:
    return VastyError(
        "box_unreachable",
        f"Lease {lease.lease} did not become ready before its clock ran out.",
        "Run vasty reserve again, or pick another offer with --gpu or --region.",
    )


def wait_ready(
    ctx: Context, lease: CachedLease, required: list[int], created: bool
) -> tuple[CachedLease, list[SweptEntry], list[WarningItem]]:
    """Refresh until the lease leaves `pending` and the `required` ports are mapped.

    Return the lease, the entries every refresh swept and the latest account
    warnings. Raise `box_unreachable`, `image_unsupported` or
    `port_mapping_missing`. A refresh error writes one stderr line and the
    wait goes on until the lease's effective expiry. Ctrl-C during the wait
    destroys a box this call created and re-raises.
    """
    swept: list[SweptEntry] = []
    ready_at: int | None = None
    while True:
        try:
            snap = engine.refresh(ctx)
        except KeyboardInterrupt as exc:
            raise _give_up(ctx, lease, created, exc)
        except VastyError as err:
            ctx.warn(f"vasty: refresh failed while waiting for {lease.lease}: {err.message}")
            if ctx.clock.now() >= effective_expiry(lease.label):
                raise _give_up(ctx, lease, created, _not_ready(lease)) from None
            _pause(ctx, lease, created)
            continue
        swept = merge_swept(swept, snap.swept)
        now = snap.now
        fresh = snap.leases.get(lease.lease)
        if fresh is None or fresh.state in HISTORY_STATES:
            raise _name_lease(VastyError(
                "box_unreachable",
                f"Lease {lease.lease} ended before it became ready.",
                f"Run vasty status {lease.lease}, then vasty reserve again.",
            ), lease, False)
        lease = fresh
        if lease.unsupported:
            missing = ", ".join(lease.unsupported)
            raise _give_up(ctx, lease, created, VastyError(
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
                raise _give_up(ctx, lease, created, VastyError(
                    "port_mapping_missing",
                    f"Lease {lease.lease} has no external mapping for port "
                    f"{', '.join(str(p) for p in unmapped)}.",
                    "Run vasty reserve again; another offer maps its ports.",
                    details={"ports": unmapped},
                ))
        elif now >= deadline:
            raise _give_up(ctx, lease, created, _not_ready(lease))
        _pause(ctx, lease, created)


def _pause(ctx: Context, lease: CachedLease, created: bool) -> None:
    """Sleep `WAIT_POLL_S`. On an error or Ctrl-C, destroy a box this call created and re-raise."""
    try:
        ctx.sleep(WAIT_POLL_S)
    except (VastyError, KeyboardInterrupt) as exc:
        raise _give_up(ctx, lease, created, exc)


def reserve_result(
    lease: CachedLease,
    now: int,
    reused: bool,
    warnings: list[WarningItem],
    swept: list[SweptEntry],
) -> ReserveResult:
    """Build the `reserve` output. A `pending` lease has null clock and endpoint fields."""
    pending = lease.state == "pending"
    expiry = effective_expiry(lease.label)
    endpoint = views.endpoint_fields(lease)
    return ReserveResult(
        lease=lease.lease,
        name=lease.label.name,
        owner=lease.label.owner,
        group=lease.label.group,
        state=lease.state,
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
    from vasty.commands.status import swept_lines, warning_lines
    from vasty.output import money

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
        lines.append(f"booting; run vasty status {result.lease}")
    blocks = [lines, swept_lines(result.swept), warning_lines(result.warnings)]
    return "\n\n".join("\n".join(block) for block in blocks if block)


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    snap = engine.refresh(ctx)
    reserved = reserve_lease(ctx, args, snap, ttl=ctx.settings.ttl)
    human = render(reserved.result) if ctx.mode == "human" else None
    return Outcome(reserved.result, human=human)
