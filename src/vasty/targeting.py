"""TARGET resolution for `extend`, `release`, `status` and `tag`.

A LEASE resolves as a lease id first, then as a name under the current
owner. `i-<id>` names an orphan or an unreadable row; it also resolves a
managed lease by its instance id. A named lease in history resolves when no
active lease matches, so callers can raise `lease_expired` or return
`already_absent`. Selectors match active leases only and never orphans.

Owner scope: writes act on the current owner (`ctx.settings.owner`) unless
`--owner` is given. Reads span owners unless `--owner` filters them.

A name that matches no lease of the current owner raises `lease_not_found`.
When other owners hold active leases under that name, `details.matches`
lists their ids and the hint names `vasty status <id>`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vasty import ids
from vasty.errors import VastyError, invalid
from vasty.models import HISTORY_STATES, CachedLease, Instance

if TYPE_CHECKING:
    from vasty.context import Context
    from vasty.engine import Snapshot


@dataclass
class Resolved:
    """Matched leases and orphans. `bulk` is True for selector targets."""

    leases: list[CachedLease]
    orphans: list[Instance]
    bulk: bool


def has_target(ns: argparse.Namespace) -> bool:
    """Return True when a LEASE or any selector is given."""
    return bool(
        getattr(ns, "target", None) is not None
        or getattr(ns, "group", None)
        or getattr(ns, "owner", None)
    )


def _not_found(ref: str, owner: str | None) -> VastyError:
    scope = f" for owner {owner}" if owner is not None else ""
    return VastyError(
        "lease_not_found", f"No lease {ref!r}{scope}.", "Run vasty status to list leases."
    )


def _held_by_others(ref: str, owner: str, matches: list[str]) -> VastyError:
    return VastyError(
        "lease_not_found",
        f"No lease {ref!r} for owner {owner}. Other owners hold {', '.join(matches)}.",
        f"Run vasty status {matches[0]}." if len(matches) == 1
        else f"Run vasty status ID with one of {', '.join(matches)}.",
        details={"matches": matches},
    )


def resolve_target(ctx: Context, snap: Snapshot, ns: argparse.Namespace, write: bool) -> Resolved:
    """Resolve a LEASE or selector. Writes default to the current owner; reads span owners.

    Raise `invalid_arguments` when nothing is selected or a group or owner
    value is invalid. A selector that matches nothing returns empty lists.
    """
    ref = getattr(ns, "target", None)
    check_selector(ns)
    if ref is not None:
        found = resolve_lease(ctx, snap, ref)
        if isinstance(found, Instance):
            return Resolved([], [found], bulk=False)
        return Resolved([found], [], bulk=False)
    group = getattr(ns, "group", None)
    owner_flag = getattr(ns, "owner", None)
    if not (group or owner_flag):
        raise invalid("No target given.", "Pass a LEASE, --group G or --owner O.")
    if group:
        ids.validate_value("group", group)
    if owner_flag:
        ids.validate_value("owner", owner_flag)
    owner = owner_flag or (ctx.settings.owner if write else None)
    leases = [
        lease for lease in snap.active()
        if (not group or lease.label.group == group)
        and (owner is None or lease.label.owner == owner)
    ]
    return Resolved(leases, [], bulk=True)


def check_selector(ns: argparse.Namespace) -> None:
    """Raise `invalid_arguments` when a LEASE comes with `--group` or `--owner`."""
    if getattr(ns, "target", None) is not None and (
        getattr(ns, "group", None) or getattr(ns, "owner", None)
    ):
        raise invalid("A LEASE takes no selector.", "Pass a LEASE or a selector.")


def resolve_lease(ctx: Context, snap: Snapshot, ref: str) -> CachedLease | Instance:
    """Resolve one id or name under the current owner, or an orphan by `i-` id.

    Raise `lease_not_found`, with other owners' matching ids in `details`
    when they hold the name, `ambiguous_target` with the matching ids in
    `details`, or `invalid_arguments` for a malformed name.
    """
    instance_id = ids.parse_orphan_id(ref)
    if instance_id is not None:
        for inst in snap.orphans + snap.unreadable:
            if inst.id == instance_id:
                return inst
        for lease in snap.active() + snap.history():
            if lease.instance_id == instance_id:
                return lease
        raise _not_found(ref, None)
    if ids.is_lease_id(ref):
        lease_match = snap.leases.get(ref)
        if lease_match is None:
            raise _not_found(ref, None)
        return lease_match
    ids.validate_value("name", ref)
    owner = ctx.settings.owner
    named = [
        lease for lease in snap.leases.values()
        if lease.label.name == ref and lease.label.owner == owner
    ]
    active = sorted(
        (lease for lease in named if lease.state not in HISTORY_STATES), key=lambda x: x.lease
    )
    if len(active) > 1:
        matches = [lease.lease for lease in active]
        raise VastyError(
            "ambiguous_target",
            f"Name {ref!r} matches {len(matches)} leases of owner {owner}.",
            f"Pass a lease id: {', '.join(matches)}.",
            details={"matches": matches},
        )
    if active:
        return active[0]
    if named:
        return max(named, key=lambda lease: (lease.history_since or 0, lease.lease))
    others = sorted(lease.lease for lease in snap.active() if lease.label.name == ref)
    if others:
        raise _held_by_others(ref, owner, others)
    raise _not_found(ref, owner)
