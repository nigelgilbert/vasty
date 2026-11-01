from __future__ import annotations

import pytest
from fakes import Harness, add_lease

from vasty import engine
from vasty.cli import parse
from vasty.errors import VastyError
from vasty.models import CachedLease, Instance
from vasty.targeting import resolve_lease, resolve_target


@pytest.fixture
def fleet(harness: Harness) -> Harness:
    add_lease(harness, "l-0000a001", label={"name": "ft", "group": "exp42"})
    add_lease(harness, "l-0000a002", label={"name": "eval", "group": "exp42"})
    add_lease(harness, "l-0000b001", label={"name": "ft", "owner": "nick", "group": "exp42"})
    add_lease(harness, "l-0000b002", label={"name": "scratch", "owner": "nick"})
    harness.provider.add_instance(id=55120, label=None)
    harness.provider.add_instance(id=55121, label="vasty:v2;lease=l-9")
    return harness


def ids_of(found: list[CachedLease]) -> list[str]:
    return [lease.lease for lease in found]


def target(harness: Harness, argv: list[str], write: bool) -> list[str]:
    ctx = harness.context()
    snap = engine.refresh(ctx)
    resolved = resolve_target(ctx, snap, parse(argv), write=write)
    assert resolved.orphans == [] or not resolved.bulk
    return ids_of(resolved.leases)


def lookup(harness: Harness, ref: str) -> CachedLease | Instance:
    ctx = harness.context()
    return resolve_lease(ctx, engine.refresh(ctx), ref)


def test_id_resolves_for_any_owner(fleet: Harness) -> None:
    found = lookup(fleet, "l-0000b002")
    assert isinstance(found, CachedLease) and found.label.owner == "nick"


def test_name_resolves_under_current_owner(fleet: Harness) -> None:
    found = lookup(fleet, "ft")
    assert isinstance(found, CachedLease) and found.lease == "l-0000a001"
    fleet.env["VASTY_OWNER"] = "nick"
    found = lookup(fleet, "ft")
    assert isinstance(found, CachedLease) and found.lease == "l-0000b001"


def test_other_owners_name_is_not_found(fleet: Harness) -> None:
    with pytest.raises(VastyError) as exc:
        lookup(fleet, "scratch")
    assert exc.value.code == "lease_not_found"


def test_unknown_id_is_not_found(fleet: Harness) -> None:
    with pytest.raises(VastyError) as exc:
        lookup(fleet, "l-deadbeef")
    assert exc.value.code == "lease_not_found"


def test_duplicate_name_is_ambiguous(fleet: Harness) -> None:
    add_lease(fleet, "l-0000a003", label={"name": "ft"})
    with pytest.raises(VastyError) as exc:
        lookup(fleet, "ft")
    assert exc.value.code == "ambiguous_target"
    assert exc.value.details == {"matches": ["l-0000a001", "l-0000a003"]}


def test_invalid_name_is_invalid_arguments(fleet: Harness) -> None:
    with pytest.raises(VastyError) as exc:
        lookup(fleet, "bad name")
    assert exc.value.code == "invalid_arguments"


def test_instance_id_resolves_orphan_and_unreadable(fleet: Harness) -> None:
    orphan = lookup(fleet, "i-55120")
    assert isinstance(orphan, Instance) and orphan.id == 55120
    unreadable = lookup(fleet, "i-55121")
    assert isinstance(unreadable, Instance) and unreadable.id == 55121
    with pytest.raises(VastyError) as exc:
        lookup(fleet, "i-1")
    assert exc.value.code == "lease_not_found"


def test_history_lease_resolves_by_name(fleet: Harness) -> None:
    ctx = fleet.context()
    snap = engine.refresh(ctx)
    del fleet.provider.instances[snap.leases["l-0000a002"].instance_id]
    found = lookup(fleet, "eval")
    assert isinstance(found, CachedLease) and found.state == "gone"


def test_active_name_wins_over_history(fleet: Harness) -> None:
    ctx = fleet.context()
    snap = engine.refresh(ctx)
    del fleet.provider.instances[snap.leases["l-0000a002"].instance_id]
    engine.refresh(ctx)
    add_lease(fleet, "l-0000a009", label={"name": "eval"})
    found = lookup(fleet, "eval")
    assert isinstance(found, CachedLease) and found.lease == "l-0000a009"


def test_group_write_acts_on_current_owner(fleet: Harness) -> None:
    assert target(fleet, ["release", "--group", "exp42"], write=True) == ["l-0000a001", "l-0000a002"]


def test_group_read_spans_owners(fleet: Harness) -> None:
    assert target(fleet, ["status", "--group", "exp42"], write=False) == [
        "l-0000a001", "l-0000a002", "l-0000b001"
    ]


def test_owner_selects_and_filters(fleet: Harness) -> None:
    assert target(fleet, ["release", "--owner", "nick"], write=True) == ["l-0000b001", "l-0000b002"]
    assert target(fleet, ["status", "--group", "exp42", "--owner", "nick"], write=False) == [
        "l-0000b001"
    ]


def test_owner_flag_selects_every_lease_of_that_owner(fleet: Harness) -> None:
    assert target(fleet, ["release", "--owner", "claude"], write=True) == [
        "l-0000a001", "l-0000a002"
    ]
    assert target(fleet, ["status", "--owner", "claude"], write=False) == [
        "l-0000a001", "l-0000a002"
    ]


def test_no_selector_is_invalid(fleet: Harness) -> None:
    ctx = fleet.context()
    snap = engine.refresh(ctx)
    with pytest.raises(VastyError) as exc:
        resolve_target(ctx, snap, parse(["release"]), write=True)
    assert exc.value.code == "invalid_arguments"


def test_lease_with_selector_is_invalid(fleet: Harness) -> None:
    ctx = fleet.context()
    snap = engine.refresh(ctx)
    for argv in (["release", "l-7f3a", "--group", "g"], ["status", "l-7f3a", "--owner", "claude"]):
        with pytest.raises(VastyError) as exc:
            resolve_target(ctx, snap, parse(argv), write=True)
        assert exc.value.code == "invalid_arguments"
    code, out, _ = fleet.run("release", "l-7f3a", "--owner", "claude")
    assert code == 1 and "invalid_arguments" in out


def test_other_owners_name_lists_matches(fleet: Harness) -> None:
    with pytest.raises(VastyError) as exc:
        lookup(fleet, "scratch")
    assert exc.value.code == "lease_not_found"
    assert exc.value.details == {"matches": ["l-0000b002"]}
    assert exc.value.hint == "Run vasty status l-0000b002."


def test_unknown_name_has_no_matches(fleet: Harness) -> None:
    with pytest.raises(VastyError) as exc:
        lookup(fleet, "nope")
    assert exc.value.code == "lease_not_found"
    assert not exc.value.details


def test_bulk_never_includes_orphans_or_history(fleet: Harness) -> None:
    ctx = fleet.context()
    snap = engine.refresh(ctx)
    del fleet.provider.instances[snap.leases["l-0000a002"].instance_id]
    snap = engine.refresh(ctx)
    resolved = resolve_target(ctx, snap, parse(["release", "--group", "exp42"]), write=True)
    assert resolved.bulk and resolved.orphans == []
    assert "l-0000a002" not in ids_of(resolved.leases)


def test_empty_bulk_target(fleet: Harness) -> None:
    assert target(fleet, ["release", "--group", "nope"], write=True) == []


def test_invalid_group_value(fleet: Harness) -> None:
    with pytest.raises(VastyError) as exc:
        target(fleet, ["release", "--group", "-bad"], write=True)
    assert exc.value.code == "invalid_arguments"


def test_lease_target_is_not_bulk(fleet: Harness) -> None:
    ctx = fleet.context()
    snap = engine.refresh(ctx)
    resolved = resolve_target(ctx, snap, parse(["release", "i-55120"]), write=True)
    assert not resolved.bulk
    assert [inst.id for inst in resolved.orphans] == [55120]


def test_no_target_is_invalid(fleet: Harness) -> None:
    ctx = fleet.context()
    with pytest.raises(VastyError) as exc:
        resolve_target(ctx, engine.refresh(ctx), parse(["release"]), write=True)
    assert exc.value.code == "invalid_arguments"
