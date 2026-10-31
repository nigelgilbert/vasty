from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from fakes import NOW, Harness, add_lease, lease_label
from vasty.errors import VastyError
from vasty.labels import parse
from vasty.models import Label

PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample test@host"
ENTRY_KEYS = {
    "lease", "name", "group", "owner", "expires_at", "ttl_remaining_s", "guard", "guard_missing",
}


@pytest.fixture
def h(harness: Harness) -> Harness:
    return harness


def run_json(harness: Harness, *argv: str) -> tuple[int, dict[str, Any]]:
    code, out, _ = harness.run(*argv)
    data: dict[str, Any] = json.loads(out)
    return code, data


def label_of(harness: Harness, instance_id: int) -> Label:
    parsed = parse(harness.provider.instances[instance_id].label)
    assert isinstance(parsed, Label)
    return parsed


def add_key(harness: Harness) -> None:
    ssh = harness.home / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text("PRIVATE\n")
    (ssh / "id_ed25519.pub").write_text(PUB + "\n")


def orphan(harness: Harness, reachable: bool = True) -> int:
    row = harness.provider.add_instance(id=55120, dph_total=Decimal("0.22"))
    if reachable:
        harness.box.state(row.id)
    return row.id


# Setters on leases.


def test_set_group_rewrites_label_and_keeps_clock(h: Harness) -> None:
    row = add_lease(h, label={"name": "ft", "expires": NOW + 600, "extra": {"note": "x"}})
    code, data = run_json(h, "tag", "ft", "--set-group", "exp42")
    assert code == 0, data
    assert set(data) == {"results", "warnings", "swept"}
    (entry,) = data["results"]
    assert set(entry) == ENTRY_KEYS
    assert (entry["lease"], entry["name"], entry["group"], entry["owner"]) == (
        "l-0000a001", "ft", "exp42", "claude")
    assert entry["expires_at"] == "2026-10-29T01:10:00Z"
    assert entry["ttl_remaining_s"] == 600
    assert (entry["guard"], entry["guard_missing"]) == ("full", [])
    label = label_of(h, row.id)
    assert (label.group, label.expires, label.extra) == ("exp42", NOW + 600, {"note": "x"})
    assert h.box.clock_writes == []


def test_empty_value_clears_name_and_group(h: Harness) -> None:
    row = add_lease(h, label={"name": "ft", "group": "exp42"})
    code, data = run_json(h, "tag", "l-0000a001", "--set-name", "", "--set-group", "")
    assert code == 0
    assert (data["results"][0]["name"], data["results"][0]["group"]) == (None, None)
    label = label_of(h, row.id)
    assert (label.name, label.group) == (None, None)


def test_group_rename_across_members(h: Harness) -> None:
    a = add_lease(h, "l-0000a001", label={"group": "old"})
    b = add_lease(h, "l-0000a002", label={"group": "old"})
    c = add_lease(h, "l-0000a003", label={"group": "old", "owner": "nick"})
    code, data = run_json(h, "tag", "--group", "old", "--set-group", "new")
    assert code == 0
    assert [r["lease"] for r in data["results"]] == ["l-0000a001", "l-0000a002"]
    assert label_of(h, a.id).group == "new"
    assert label_of(h, b.id).group == "new"
    assert label_of(h, c.id).group == "old"


def test_set_owner(h: Harness) -> None:
    row = add_lease(h, label={"name": "ft"})
    code, data = run_json(h, "tag", "ft", "--set-owner", "agent-7")
    assert code == 0
    assert data["results"][0]["owner"] == "agent-7"
    assert label_of(h, row.id).owner == "agent-7"


def test_set_name_on_bulk_target_is_invalid(h: Harness) -> None:
    add_lease(h, label={"group": "exp"})
    code, data = run_json(h, "tag", "--group", "exp", "--set-name", "ft")
    assert (code, data["error"]) == (1, "invalid_arguments")


def test_set_name_conflict(h: Harness) -> None:
    add_lease(h, "l-0000a001", label={"name": "ft"})
    row = add_lease(h, "l-0000a002")
    code, data = run_json(h, "tag", "l-0000a002", "--set-name", "ft")
    assert (code, data["error"]) == (1, "name_conflict")
    assert label_of(h, row.id).name is None


def test_same_name_other_owner_is_fine(h: Harness) -> None:
    add_lease(h, "l-0000a001", label={"name": "ft", "owner": "nick"})
    add_lease(h, "l-0000a002")
    code, _ = run_json(h, "tag", "l-0000a002", "--set-name", "ft")
    assert code == 0


def test_set_owner_checks_new_owners_names(h: Harness) -> None:
    add_lease(h, "l-0000a001", label={"name": "ft", "owner": "nick"})
    row = add_lease(h, "l-0000a002", label={"name": "ft"})
    code, data = run_json(h, "tag", "l-0000a002", "--set-owner", "nick")
    assert (code, data["error"]) == (1, "name_conflict")
    assert label_of(h, row.id).owner == "claude"


def test_bulk_set_owner_conflict_writes_nothing(h: Harness) -> None:
    a = add_lease(h, "l-0000a001", label={"name": "ft", "group": "g"})
    add_lease(h, "l-0000a002", label={"name": "ft", "owner": "nick"})
    code, data = run_json(h, "tag", "--group", "g", "--set-owner", "nick")
    assert (code, data["error"]) == (1, "name_conflict")
    assert label_of(h, a.id).owner == "claude"


def test_unchanged_shared_name_is_not_a_conflict(h: Harness) -> None:
    a = add_lease(h, "l-0000a001", label={"name": "ft"})
    add_lease(h, "l-0000a002", label={"name": "ft"})
    code, data = run_json(h, "tag", "l-0000a001", "--set-group", "g")
    assert code == 0, data
    assert label_of(h, a.id).group == "g"


def test_bulk_group_change_keeps_shared_names(h: Harness) -> None:
    a = add_lease(h, "l-0000a001", label={"name": "ft", "group": "old"})
    b = add_lease(h, "l-0000a002", label={"name": "ft", "group": "old"})
    code, data = run_json(h, "tag", "--group", "old", "--set-group", "new")
    assert code == 0, data
    assert (label_of(h, a.id).group, label_of(h, b.id).group) == ("new", "new")


def test_rename_onto_an_unchanged_lease_name_conflicts(h: Harness) -> None:
    add_lease(h, "l-0000a001", label={"name": "ft", "group": "g"})
    row = add_lease(h, "l-0000a002", label={"name": "other", "group": "g"})
    code, data = run_json(h, "tag", "l-0000a002", "--set-name", "ft")
    assert (code, data["error"]) == (1, "name_conflict")
    assert label_of(h, row.id).name == "other"


def padded_label(length: int, lease: str, **label: Any) -> dict[str, Any]:
    """Return `add_lease` label fields whose rendered label is `length` characters."""
    base = len(lease_label(lease, **label, extra={"note": ""}))
    return {**label, "extra": {"note": "x" * (length - base)}}


def test_label_over_limit_is_invalid_and_writes_nothing(h: Harness) -> None:
    a = add_lease(h, "l-0000a001", label=padded_label(1000, "l-0000a001", group="g1"))
    b = add_lease(h, "l-0000a002", label=padded_label(1023, "l-0000a002", group="g1"))
    assert len(h.provider.instances[b.id].label or "") == 1023
    code, data = run_json(h, "tag", "--group", "g1", "--set-group", "g12345")
    assert (code, data["error"]) == (1, "invalid_arguments")
    assert [c for c in h.provider.calls if c[0] == "set_label"] == []
    assert (label_of(h, a.id).group, label_of(h, b.id).group) == ("g1", "g1")


def test_ttl_on_lease_points_at_extend(h: Harness) -> None:
    add_lease(h)
    code, data = run_json(h, "tag", "l-0000a001", "--ttl", "30m")
    assert (code, data["error"]) == (1, "invalid_arguments")
    assert "vasty extend" in data["hint"]


def test_no_setter_and_no_ttl_is_invalid(h: Harness) -> None:
    add_lease(h)
    code, data = run_json(h, "tag", "l-0000a001")
    assert (code, data["error"]) == (1, "invalid_arguments")


def test_empty_owner_is_invalid(h: Harness) -> None:
    add_lease(h)
    code, data = run_json(h, "tag", "l-0000a001", "--set-owner", "")
    assert (code, data["error"]) == (1, "invalid_arguments")


def test_history_lease_is_expired(h: Harness) -> None:
    add_lease(h, label={"name": "ft", "expires": NOW - 5})
    code, data = run_json(h, "tag", "ft", "--set-group", "g")
    assert (code, data["error"]) == (1, "lease_expired")


def test_label_write_failure_is_provider_error(h: Harness) -> None:
    add_lease(h)
    h.provider.fail["set_label"] = VastyError("provider_error", "boom", "Run vasty status.")
    code, data = run_json(h, "tag", "l-0000a001", "--set-group", "g")
    assert (code, data["error"]) == (2, "provider_error")


# Orphan adoption.


def test_adopt_orphan_writes_label_clock_and_key(h: Harness) -> None:
    add_key(h)
    iid = orphan(h)
    code, data = run_json(h, "tag", "i-55120", "--ttl", "30m")
    assert code == 0, data
    (entry,) = data["results"]
    assert entry["lease"] == "l-abababab"
    assert entry["owner"] == "claude"
    assert entry["expires_at"] == "2026-10-29T01:30:00Z"
    assert entry["ttl_remaining_s"] == 1800
    assert (entry["guard"], entry["guard_missing"]) == ("full", [])
    label = label_of(h, iid)
    assert (label.lease, label.owner, label.created, label.ttl, label.expires) == (
        "l-abababab", "claude", NOW, 1800, NOW + 1800)
    assert h.box.state(iid).clock == NOW + 1800
    assert label.miss == []
    assert h.provider.attached == [(PUB, iid)]
    lease = h.context().cache.load().leases["l-abababab"]
    assert lease.adopted is True
    assert lease.state == "running"
    assert data["warnings"] == []


def test_adopt_orphan_with_setters(h: Harness) -> None:
    iid = orphan(h)
    code, data = run_json(h, "tag", "i-55120", "--ttl", "1h", "--set-owner", "nick",
                          "--set-name", "found", "--set-group", "g")
    assert code == 0
    label = label_of(h, iid)
    assert (label.owner, label.name, label.group, label.ttl) == ("nick", "found", "g", 3600)


def test_adopted_lease_shows_in_status(h: Harness) -> None:
    orphan(h)
    run_json(h, "tag", "i-55120", "--ttl", "30m")
    _, data = run_json(h, "status")
    (view,) = data["leases"]
    assert (view["lease"], view["state"]) == ("l-abababab", "running")


def test_orphan_without_ttl_is_invalid(h: Harness) -> None:
    orphan(h)
    code, data = run_json(h, "tag", "i-55120", "--set-group", "g")
    assert (code, data["error"]) == (1, "invalid_arguments")
    assert h.provider.instances[55120].label is None


def test_adopt_partial_guard_keeps_label(h: Harness) -> None:
    iid = orphan(h)
    h.box.state(iid).adopt_missing = ["destroy_key"]
    code, data = run_json(h, "tag", "i-55120", "--ttl", "30m")
    assert code == 0
    (entry,) = data["results"]
    assert (entry["guard"], entry["guard_missing"]) == ("partial", ["destroy_key"])
    assert [w["code"] for w in data["warnings"]] == ["guard_partial"]
    assert data["warnings"][0]["fix"] == "vasty release l-abababab"
    assert label_of(h, iid).lease == "l-abababab"
    assert label_of(h, iid).miss == ["destroy_key"]


def test_adopt_unreachable_box_keeps_label_with_partial_guard(h: Harness) -> None:
    iid = orphan(h, reachable=False)
    code, data = run_json(h, "tag", "i-55120", "--ttl", "30m")
    assert code == 0
    (entry,) = data["results"]
    assert entry["guard"] == "partial"
    assert entry["guard_missing"] == ["watchdog", "destroy_key", "clock_file"]
    assert "guard_partial" in [w["code"] for w in data["warnings"]]
    assert label_of(h, iid).expires == NOW + 1800
    assert label_of(h, iid).miss == ["watchdog", "destroy_key", "clock_file"]
    lease = h.context().cache.load().leases["l-abababab"]
    assert lease.adopted is True


def test_adopt_retried_by_later_probe(h: Harness) -> None:
    iid = orphan(h)
    h.box.state(iid).adopt_missing = ["watchdog"]
    run_json(h, "tag", "i-55120", "--ttl", "30m")
    h.box.state(iid).guard_missing = ["watchdog"]
    h.box.state(iid).adopt_missing = []
    _, data = run_json(h, "status", "l-abababab")
    assert data["leases"][0]["guard"] == "full"


def test_failed_key_attach_is_retried_and_adoption_finishes(h: Harness) -> None:
    add_key(h)
    iid = orphan(h, reachable=False)
    h.provider.fail["attach_ssh_key"] = VastyError("provider_error", "boom", "Run vasty status.")
    code, data = run_json(h, "tag", "i-55120", "--ttl", "30m")
    assert code == 0
    assert data["results"][0]["guard"] == "partial"
    assert h.provider.attached == []
    run_json(h, "status")
    assert h.provider.attached == [(PUB, iid)]
    box = h.box.state(iid)
    box.startup_started, box.startup_exit = False, None
    h.time.advance(5)
    _, data = run_json(h, "status", "l-abababab")
    assert data["leases"][0]["guard"] == "full"
    assert h.box.adopts == [iid]
    assert label_of(h, iid).miss == []


def test_adoption_retry_survives_cache_loss(h: Harness) -> None:
    iid = orphan(h, reachable=False)
    run_json(h, "tag", "i-55120", "--ttl", "30m")
    ctx = h.context()
    data = ctx.cache.load()
    data.leases.clear()
    ctx.cache.save(data)
    box = h.box.state(iid)
    box.startup_started, box.startup_exit = False, None
    _, status = run_json(h, "status", "l-abababab")
    assert status["leases"][0]["guard"] == "full"
    assert h.box.adopts == [iid]
    assert box.clock == NOW + 1800
    assert label_of(h, iid).miss == []
    assert h.context().cache.load().leases["l-abababab"].adopted is True


def test_adopt_reads_no_billing(h: Harness) -> None:
    orphan(h)
    code, data = run_json(h, "tag", "i-55120", "--ttl", "1h")
    assert code == 0
    assert data["warnings"] == []
    assert [c for c, _ in h.provider.calls if c in ("balance", "charges")] == []


def test_adopt_name_conflict(h: Harness) -> None:
    add_lease(h, "l-0000a001", label={"name": "ft"})
    orphan(h)
    code, data = run_json(h, "tag", "i-55120", "--ttl", "30m", "--set-name", "ft")
    assert (code, data["error"]) == (1, "name_conflict")
    assert h.provider.instances[55120].label is None


def test_unreadable_label_is_refused(h: Harness) -> None:
    h.provider.add_instance(id=55120, label="vasty:v9;lease=l-1")
    code, data = run_json(h, "tag", "i-55120", "--ttl", "30m")
    assert (code, data["error"]) == (1, "invalid_arguments")
    assert data["hint"] == "vasty release i-55120"
    assert h.provider.instances[55120].label == "vasty:v9;lease=l-1"
