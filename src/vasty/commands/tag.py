"""`vasty tag LEASE`.

`tag` acts on one lease per call. On a lease, `tag` rewrites `name`, `group`
and `owner` in the label and keeps unknown fields and the clock. Before the
write, `tag` checks a changed name or owner for name conflicts and formats
the new label. On an orphan, `tag` writes a new `vasty:` label with `expires = now + ttl`
and `miss` listing every guard layer, then attaches the SSH key, runs the
adoption script over SSH and starts a detached `vasty sweep --follow`. The label stays when a later step fails; the lease
then carries a `guard_partial` warning and later networked commands retry the
missing steps (see `engine`).
"""

from __future__ import annotations

import argparse
import dataclasses
import shlex

from vasty import engine, ids, labels, views
from vasty.cli import Outcome
from vasty.commands._common import taken_ids
from vasty.commands.sweep import spawn_follow
from vasty.context import Context
from vasty.errors import VastyError, invalid
from vasty.ids import orphan_id
from vasty.keys import public_key
from vasty.models import HISTORY_STATES, CachedLease, Instance, Label, TagResult
from vasty.state import GUARD_LAYERS, derive_state, effective_expiry
from vasty.timeutil import format_duration, parse_duration


@dataclasses.dataclass(frozen=True)
class Setters:
    """The requested label changes. None leaves a field alone; "" clears `name` or `group`."""

    name: str | None
    group: str | None
    owner: str | None

    def any(self) -> bool:
        return self.name is not None or self.group is not None or self.owner is not None


def parse_setters(args: argparse.Namespace) -> Setters:
    """Read and validate `--name`, `--group` and `--owner`."""
    setters = Setters(
        name=getattr(args, "name", None),
        group=getattr(args, "group", None),
        owner=getattr(args, "owner", None),
    )
    if setters.name:
        ids.validate_value("name", setters.name)
    if setters.group:
        ids.validate_value("group", setters.group)
    if setters.owner is not None:
        if setters.owner == "":
            raise invalid("--owner cannot be empty.", "Pass --owner NAME.")
        ids.validate_value("owner", setters.owner)
    return setters


def relabel(label: Label, setters: Setters) -> Label:
    """Return the label with the setters applied."""
    out = dataclasses.replace(label)
    if setters.name is not None:
        out.name = setters.name or None
    if setters.group is not None:
        out.group = setters.group or None
    if setters.owner is not None:
        out.owner = setters.owner
    return out


def _name_conflict(name: str, owner: str, holder: str) -> VastyError:
    return VastyError(
        "name_conflict",
        f"Name {name!r} is already used by {holder} for owner {owner}.",
        f"Pick another name, or vasty tag {holder} --name NEW.",
        details={"lease": holder},
    )


def check_names(snap: engine.Snapshot, planned: dict[str, Label]) -> None:
    """Raise `name_conflict` when a planned name clashes with another active lease of its owner."""
    claimed: dict[tuple[str, str], str] = {
        (lease.label.name, lease.label.owner): lease.lease
        for lease in snap.active()
        if lease.label.name and lease.lease not in planned
    }
    for lease_id in sorted(planned):
        label = planned[lease_id]
        if not label.name:
            continue
        key = (label.name, label.owner)
        holder = claimed.get(key)
        if holder is not None and holder != lease_id:
            raise _name_conflict(label.name, label.owner, holder)
        claimed[key] = lease_id


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    setters = parse_setters(args)
    ttl_text = getattr(args, "ttl", None)
    ttl = parse_duration(ttl_text) if ttl_text is not None else None
    if not setters.any() and ttl is None:
        raise invalid(
            "tag needs --name, --group, --owner or --ttl.",
            "vasty tag LEASE --group G",
        )

    from vasty.targeting import resolve_lease

    snap = engine.refresh(ctx)
    found = resolve_lease(ctx, snap, args.target)
    not_spawned = None
    if isinstance(found, Instance):
        lease = adopt(ctx, snap, found, setters, ttl)
        not_spawned = spawn_follow(ctx, lease.lease)
    else:
        if ttl is not None:
            raise invalid("--ttl applies to orphans only.", "vasty extend LEASE --by 30m")
        lease = update(ctx, snap, found, setters)
    results = [lease]
    warnings = (
        views.warnings_for(results, snap.now)
        + list(snap.warnings)
    )
    if not_spawned is not None:
        warnings.append(not_spawned)
    entries = [views.tag_entry(lease, snap.now) for lease in results]
    result = TagResult(results=entries, warnings=warnings, swept=snap.swept)
    human = None
    if ctx.mode == "human":
        lines = [
            f"{e.lease}  name={e.name or '—'}  group={e.group or '—'}  owner={e.owner}  "
            f"expires {format_duration(e.ttl_remaining_s or 0)}"
            for e in entries
        ]
        human = "\n".join(lines)
    return Outcome(result, human=human)


def update(
    ctx: Context, snap: engine.Snapshot, lease: CachedLease, setters: Setters
) -> CachedLease:
    """Rewrite the lease's label with the setters. Leave the clock alone."""
    if lease.state in HISTORY_STATES:
        raise VastyError(
            "lease_expired", f"Lease {lease.lease} is {lease.state}.",
            "Run vasty status to list active leases.",
        )
    label = relabel(lease.label, setters)
    if (label.name, label.owner) != (lease.label.name, lease.label.owner):
        check_names(snap, {lease.lease: label})
    labels.format_label(label)
    try:
        ok = engine.write_label(ctx, lease.instance_id, lease.label.expires, label)
    except VastyError as err:
        raise _write_failed(lease, err.message) from err
    if not ok:
        raise _write_failed(lease, "the label changed since vasty read it.")
    lease.label = label
    engine.store_lease(ctx, lease)
    return lease


def _write_failed(lease: CachedLease, why: str) -> VastyError:
    return VastyError(
        "provider_error",
        f"Label write for {lease.lease} failed: {why}",
        f"Run vasty status {lease.lease}, then tag again.",
    )


def adopt(
    ctx: Context, snap: engine.Snapshot, inst: Instance, setters: Setters, ttl: int | None
) -> CachedLease:
    """Give an orphan a `vasty:` label and a guard and return the lease.

    Raise `invalid_arguments` for an unreadable `vasty:` label or a missing
    `--ttl`, and `name_conflict` for a name the owner already uses.
    """
    ref = orphan_id(inst.id)
    if any(row.id == inst.id for row in snap.unreadable):
        raise invalid(
            f"{ref} has an unreadable vasty: label; tag refuses it.",
            shlex.join(["vasty", "release", ref]),
        )
    if ttl is None:
        raise invalid(f"{ref} is an orphan and needs --ttl.", f"vasty tag {ref} --ttl 30m")
    owner = setters.owner or ctx.settings.owner
    lease_id = ids.new_lease_id(ctx.random_hex, taken_ids(snap))
    now = ctx.clock.now()
    label = Label(
        lease=lease_id, owner=owner, created=now, ttl=ttl,
        name=setters.name or None, group=setters.group or None, expires=now + ttl,
        miss=list(GUARD_LAYERS),
    )
    check_names(snap, {lease_id: label})
    text = labels.format_label(label)

    row = ctx.provider.get_instance(inst.id)
    if row is None:
        raise VastyError("lease_not_found", f"No instance {ref}.", "Run vasty status to list leases.")
    if labels.is_managed(row.label):
        raise VastyError(
            "provider_error", f"{ref} gained a vasty: label since vasty read it.",
            f"Run vasty status {ref}.",
        )
    ctx.provider.set_label(inst.id, text)
    lease = engine.lease_from_row(row, label)
    lease.adopted = True
    lease.guard_missing = list(GUARD_LAYERS)
    lease.state = derive_state(row.actual_status, None, False)
    try:
        _guard_steps(ctx, lease)
        lease.reachable_at = now
        if (row.actual_status or "").strip().lower() == "running":
            lease.state = "running"
        _record_miss(ctx, lease)
    except (VastyError, OSError) as err:
        lease.last_provider_error = str(err)
    finally:
        engine.store_lease(ctx, lease)
    return lease


def _guard_steps(ctx: Context, lease: CachedLease) -> None:
    """Attach the SSH key and run the adoption script. Set the missing guard layers."""
    key = public_key(ctx)
    if key is None:
        ctx.warn("vasty: no SSH public key found next to ssh_key; skipping key attach")
    else:
        try:
            ctx.provider.attach_ssh_key(key, lease.instance_id)
        except VastyError as err:
            ctx.warn(f"vasty: could not attach the SSH key to {lease.lease}: {err.message}")
    missing = ctx.box.adopt(
        engine.ssh_target(lease), effective_expiry(lease.label), engine.provider_now(ctx)
    )
    present = set(missing)
    lease.guard_missing = [layer for layer in GUARD_LAYERS if layer in present]


def _record_miss(ctx: Context, lease: CachedLease) -> None:
    """Write the layers the adoption script left missing to the label's `miss`."""
    if lease.guard_missing == lease.label.miss:
        return
    label = dataclasses.replace(lease.label, miss=list(lease.guard_missing))
    if engine.write_label(ctx, lease.instance_id, lease.label.expires, label):
        lease.label = label
