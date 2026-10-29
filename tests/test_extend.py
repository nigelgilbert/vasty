from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from fakes import NOW, Harness, add_lease, lease_label
from vasty.errors import VastyError
from vasty.labels import parse
from vasty.models import Label
from vasty.remote import BoxUnreachableError, SshTarget


@pytest.fixture
def h(harness: Harness) -> Harness:
    harness.provider.covered_through = NOW
    return harness


def run_json(harness: Harness, *argv: str) -> tuple[int, dict[str, Any]]:
    code, out, _ = harness.run(*argv)
    data: dict[str, Any] = json.loads(out)
    return code, data


def label_of(harness: Harness, instance_id: int) -> Label:
    parsed = parse(harness.provider.instances[instance_id].label)
    assert isinstance(parsed, Label)
    return parsed


def cached(harness: Harness, lease: str) -> Any:
    return harness.context().cache.load().leases[lease]


def record_writes(h: Harness, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    events: list[tuple[str, int]] = []
    set_label = h.provider.set_label
    write_clock = h.box.write_clock

    def label(instance_id: int, text: str) -> None:
        parsed = parse(text)
        assert isinstance(parsed, Label) and parsed.expires is not None
        events.append(("label", parsed.expires))
        set_label(instance_id, text)

    def clock(target: SshTarget, expires: int) -> None:
        events.append(("clock", expires))
        write_clock(target, expires)

    monkeypatch.setattr(h.provider, "set_label", label)
    monkeypatch.setattr(h.box, "write_clock", clock)
    return events


# Single lease.


def test_extend_by_moves_label_and_clock(h: Harness) -> None:
    row = add_lease(h, label={"name": "ft", "expires": NOW + 600})
    code, data = run_json(h, "extend", "ft", "--by", "30m")
    assert code == 0, data
    assert set(data) == {"lease", "expires_at", "ttl_remaining_s", "warnings", "swept"}
    assert data["lease"] == "l-0000a001"
    assert data["expires_at"] == "2026-10-29T01:40:00Z"
    assert data["ttl_remaining_s"] == 2400
    assert label_of(h, row.id).expires == NOW + 2400
    assert h.box.state(row.id).clock == NOW + 2400


def test_extend_to_counts_from_now(h: Harness) -> None:
    row = add_lease(h, label={"expires": NOW + 600})
    _, data = run_json(h, "extend", "l-0000a001", "--to", "2h")
    assert data["ttl_remaining_s"] == 7200
    assert label_of(h, row.id).expires == NOW + 7200


def test_extend_until_timestamp(h: Harness) -> None:
    row = add_lease(h, label={"expires": NOW + 600})
    _, data = run_json(h, "extend", "l-0000a001", "--until", "2026-10-29T03:00:00+01:00")
    assert data["expires_at"] == "2026-10-29T02:00:00Z"
    assert label_of(h, row.id).expires == NOW + 3600


def test_extend_keeps_unknown_label_fields(h: Harness) -> None:
    row = add_lease(h, label={"expires": NOW + 600, "extra": {"note": "x"}})
    run_json(h, "extend", "l-0000a001", "--by", "10m")
    assert label_of(h, row.id).extra == {"note": "x"}


@pytest.mark.parametrize("flags", [[], ["--by", "1h", "--to", "2h"]])
def test_extend_needs_exactly_one_flag(h: Harness, flags: list[str]) -> None:
    add_lease(h)
    code, data = run_json(h, "extend", "l-0000a001", *flags)
    assert code == 1
    assert data["error"] == "invalid_arguments"


@pytest.mark.parametrize("flag", ["--by", "--to"])
@pytest.mark.parametrize("text", ["1h1h", "30m1h", "1h0m"])
def test_extend_uses_reserve_ttl_grammar(h: Harness, flag: str, text: str) -> None:
    row = add_lease(h, label={"expires": NOW + 600})
    code, data = run_json(h, "extend", "l-0000a001", flag, text)
    assert (code, data["error"]) == (1, "invalid_arguments")
    assert label_of(h, row.id).expires == NOW + 600
    code, data = run_json(h, "reserve", "--ttl", text)
    assert (code, data["error"]) == (1, "invalid_arguments")


def test_extend_to_past_points_at_release(h: Harness) -> None:
    row = add_lease(h, label={"expires": NOW + 600})
    code, data = run_json(h, "extend", "l-0000a001", "--until", "2026-10-29T00:30:00Z")
    assert code == 1
    assert data["error"] == "invalid_arguments"
    assert data["hint"] == "vasty release l-0000a001"
    assert label_of(h, row.id).expires == NOW + 600


def test_extend_at_now_is_invalid(h: Harness) -> None:
    add_lease(h, label={"expires": NOW + 600})
    code, data = run_json(h, "extend", "l-0000a001", "--until", "2026-10-29T01:00:00Z")
    assert (code, data["error"]) == (1, "invalid_arguments")


def test_lengthen_writes_clock_then_label(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    add_lease(h, label={"expires": NOW + 600})
    h.run("status")
    events = record_writes(h, monkeypatch)
    run_json(h, "extend", "l-0000a001", "--by", "30m")
    assert events == [("clock", NOW + 2400), ("label", NOW + 2400)]


def test_shorten_writes_label_then_clock(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    add_lease(h, label={"expires": NOW + 3000})
    h.run("status")
    events = record_writes(h, monkeypatch)
    code, data = run_json(h, "extend", "l-0000a001", "--to", "10m")
    assert code == 0
    assert data["ttl_remaining_s"] == 600
    assert events == [("label", NOW + 600), ("clock", NOW + 600)]


def test_lengthen_label_failure_restores_clock(h: Harness) -> None:
    row = add_lease(h, label={"expires": NOW + 600})
    h.provider.fail["set_label"] = VastyError("provider_error", "boom", "Run vasty status.")
    code, data = run_json(h, "extend", "l-0000a001", "--by", "30m")
    assert code == 2
    assert data["error"] == "provider_error"
    assert label_of(h, row.id).expires == NOW + 600
    assert h.box.state(row.id).clock == NOW + 600
    assert h.box.clock_writes == [(row.id, NOW + 2400), (row.id, NOW + 600)]
    lease = cached(h, "l-0000a001")
    assert "clock_file" in lease.guard_missing


def test_lengthen_restore_failure_names_both_values(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = add_lease(h, label={"expires": NOW + 600})
    h.provider.fail["set_label"] = VastyError("provider_error", "boom", "Run vasty status.")
    write_clock = h.box.write_clock
    count = [0]

    def clock(target: SshTarget, expires: int) -> None:
        count[0] += 1
        if count[0] > 1:
            raise BoxUnreachableError("gone")
        write_clock(target, expires)

    monkeypatch.setattr(h.box, "write_clock", clock)
    code, data = run_json(h, "extend", "l-0000a001", "--by", "30m")
    assert code == 2
    assert data["error"] == "provider_error"
    assert data["details"] == {
        "old_expires_at": "2026-10-29T01:10:00Z", "new_expires_at": "2026-10-29T01:40:00Z",
    }
    assert h.box.state(row.id).clock == NOW + 2400
    code, out, _ = h.run("status", "--cached", "l-0000a001")
    view = json.loads(out)["leases"][0]
    assert view["guard"] == "partial"
    assert view["guard_missing"] == ["clock_file"]


def test_shorten_clock_failure_restores_label(h: Harness) -> None:
    row = add_lease(h, label={"expires": NOW + 3000})
    h.run("status")
    h.box.state(row.id).clock_write_fails = True
    code, data = run_json(h, "extend", "l-0000a001", "--to", "10m")
    assert code == 2
    assert data["error"] == "provider_error"
    assert label_of(h, row.id).expires == NOW + 3000
    assert h.box.state(row.id).clock == NOW + 3000
    assert "clock_file" in cached(h, "l-0000a001").guard_missing


def test_shorten_restore_failure_names_both_values(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = add_lease(h, label={"expires": NOW + 3000})
    h.run("status")
    h.box.state(row.id).clock_write_fails = True
    set_label = h.provider.set_label
    count = [0]

    def label(instance_id: int, text: str) -> None:
        count[0] += 1
        if count[0] > 1:
            raise VastyError("provider_error", "label api down", "Run vasty status.")
        set_label(instance_id, text)

    monkeypatch.setattr(h.provider, "set_label", label)
    code, data = run_json(h, "extend", "l-0000a001", "--to", "10m")
    assert code == 2
    assert data["error"] == "provider_error"
    assert data["details"] == {
        "old_expires_at": "2026-10-29T01:50:00Z", "new_expires_at": "2026-10-29T01:10:00Z",
    }
    assert label_of(h, row.id).expires == NOW + 600


def test_label_moved_since_read_aborts(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    row = add_lease(h, label={"expires": NOW + 600})
    get_instance = h.provider.get_instance

    def moved(instance_id: int) -> Any:
        inst = get_instance(instance_id)
        if inst is not None:
            parsed = parse(inst.label)
            assert isinstance(parsed, Label)
            parsed.expires = NOW + 999
            from vasty.labels import format_label

            inst.label = format_label(parsed)
        return inst

    monkeypatch.setattr(h.provider, "get_instance", moved)
    code, data = run_json(h, "extend", "l-0000a001", "--by", "30m")
    assert code == 2
    assert data["error"] == "provider_error"
    assert label_of(h, row.id).expires == NOW + 999
    assert h.box.state(row.id).clock == NOW + 600


# Refusals.


def test_label_over_limit_is_invalid_before_any_write(h: Harness) -> None:
    from vasty import engine
    from vasty.commands import extend

    base = len(lease_label(expires=None, extra={"note": ""}))
    row = add_lease(h, label={"expires": None, "extra": {"note": "x" * (1020 - base)}})
    ctx = h.context()
    lease = engine.refresh(ctx, probe=False).leases["l-0000a001"]
    with pytest.raises(VastyError) as exc:
        extend.apply(ctx, lease, NOW + 7200)
    assert exc.value.code == "invalid_arguments"
    assert h.box.clock_writes == []
    assert [c for c in h.provider.calls if c[0] == "set_label"] == []
    assert label_of(h, row.id).expires is None


def test_history_lease_is_expired(h: Harness) -> None:
    add_lease(h, label={"name": "ft", "expires": NOW - 5})
    code, data = run_json(h, "extend", "ft", "--by", "30m")
    assert (code, data["error"]) == (1, "lease_expired")


def test_unreachable_lease_changes_nothing(h: Harness) -> None:
    row = add_lease(h, label={"expires": NOW + 600})
    h.run("status")
    h.box.state(row.id).reachable = False
    code, data = run_json(h, "extend", "l-0000a001", "--by", "30m")
    assert (code, data["error"]) == (2, "box_unreachable")
    assert label_of(h, row.id).expires == NOW + 600
    assert h.box.clock_writes == []


def test_never_answered_lease_is_pending(h: Harness) -> None:
    add_lease(h, reachable=False, label={"expires": None}, actual_status="loading")
    code, data = run_json(h, "extend", "l-0000a001", "--by", "30m")
    assert (code, data["error"]) == (1, "lease_pending")


def test_running_startup_accepts_extend(h: Harness) -> None:
    row = add_lease(h, label={"expires": NOW + 600})
    h.box.state(row.id).startup_exit = None
    code, data = run_json(h, "extend", "l-0000a001", "--by", "30m")
    assert code == 0, data
    assert label_of(h, row.id).expires == NOW + 2400


def test_orphan_is_unmanaged(h: Harness) -> None:
    h.provider.add_instance(id=55120)
    code, data = run_json(h, "extend", "i-55120", "--by", "30m")
    assert (code, data["error"]) == (1, "orphan_unmanaged")
    assert data["hint"] == "vasty tag i-55120 --ttl 30m"


def test_budget_refusal_says_by_how_much(h: Harness) -> None:
    h.env["VASTY_DAILY_BUDGET"] = "1.00"
    row = add_lease(h, label={"expires": NOW + 3600}, dph_total=Decimal("0.50"))
    code, data = run_json(h, "extend", "l-0000a001", "--by", "2h")
    assert code == 3
    assert data["error"] == "budget_exceeded"
    assert data["details"] == {"projected": 1.5, "remaining": 0.5, "daily_budget": 1.0}
    assert "by $0.50" in data["message"]
    assert label_of(h, row.id).expires == NOW + 3600
    assert h.box.clock_writes == []


def test_shortening_passes_over_budget(h: Harness) -> None:
    h.env["VASTY_DAILY_BUDGET"] = "0.10"
    row = add_lease(h, label={"expires": NOW + 7200}, dph_total=Decimal("0.50"))
    code, _ = run_json(h, "extend", "l-0000a001", "--to", "1h")
    assert code == 0
    assert label_of(h, row.id).expires == NOW + 3600


def run_after_refresh(h: Harness, monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    """Run `argv` as a second local vasty command right after the next refresh returns."""
    from vasty import engine

    real = engine.refresh

    def refresh_then_run(ctx: Any, probe: bool = True) -> engine.Snapshot:
        snap = real(ctx, probe)
        monkeypatch.setattr(engine, "refresh", real)
        code, out, _ = h.run(*argv)
        assert code == 0, out
        return snap

    monkeypatch.setattr(engine, "refresh", refresh_then_run)


def reserve_after_refresh(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run a second local `reserve --no-wait` right after the next refresh returns."""
    from fakes import make_offer

    h.provider.offers = [make_offer(1)]
    h.hex_values = ["0000b001"]
    run_after_refresh(h, monkeypatch, "reserve", "--ttl", "1h", "--no-wait")


def test_budget_counts_local_reserve_between_refresh_and_lock(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.env["VASTY_DAILY_BUDGET"] = "1.00"
    row = add_lease(h, label={"expires": NOW + 3600}, dph_total=Decimal("0.50"))
    reserve_after_refresh(h, monkeypatch)
    code, data = run_json(h, "extend", "l-0000a001", "--by", "30m")
    assert code == 3
    assert data["details"] == {"projected": 1.13, "remaining": 0.12, "daily_budget": 1.0}
    assert label_of(h, row.id).expires == NOW + 3600


def test_budget_counts_local_extend_between_refresh_and_lock(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.env["VASTY_DAILY_BUDGET"] = "1.60"
    row = add_lease(h, "l-0000a001", label={"expires": NOW + 1800}, dph_total=Decimal("0.50"))
    add_lease(h, "l-0000a002", label={"expires": NOW + 1800}, dph_total=Decimal("0.50"))
    run_after_refresh(h, monkeypatch, "extend", "l-0000a002", "--by", "2h")
    code, data = run_json(h, "extend", "l-0000a001", "--by", "30m")
    assert code == 3, data
    assert data["error"] == "budget_exceeded"
    assert data["details"] == {"projected": 1.75, "remaining": 0.1, "daily_budget": 1.6}
    assert label_of(h, row.id).expires == NOW + 1800
    assert h.box.state(row.id).clock == NOW + 1800


def test_extend_stacks_on_local_extend_between_refresh_and_lock(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = add_lease(h, label={"expires": NOW + 600})
    run_after_refresh(h, monkeypatch, "extend", "l-0000a001", "--by", "1h")
    code, data = run_json(h, "extend", "l-0000a001", "--by", "30m")
    assert code == 0, data
    assert label_of(h, row.id).expires == NOW + 6000
    assert h.box.state(row.id).clock == NOW + 6000
    assert cached(h, "l-0000a001").label.expires == NOW + 6000


def test_release_between_refresh_and_lock_is_expired(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.provider.keep_rows = True
    row = add_lease(h, label={"expires": NOW + 600})
    run_after_refresh(h, monkeypatch, "release", "l-0000a001")
    code, data = run_json(h, "extend", "l-0000a001", "--by", "30m")
    assert (code, data["error"]) == (1, "lease_expired")
    lease = cached(h, "l-0000a001")
    assert lease.state == "released"
    assert lease.released_here and lease.destroy_pending
    assert label_of(h, row.id).expires == NOW + 600
    assert [c for c in h.provider.calls if c[0] == "set_label"] == []
    assert h.box.clock_writes == []


def edit_after_refresh(
    h: Harness, monkeypatch: pytest.MonkeyPatch, lease: str, **fields: Any
) -> None:
    """Set `fields` on the cache copy of `lease` right after the next refresh returns."""
    import dataclasses

    from vasty import engine

    real = engine.refresh

    def refresh_then_edit(ctx: Any, probe: bool = True) -> engine.Snapshot:
        snap = real(ctx, probe)
        monkeypatch.setattr(engine, "refresh", real)
        with ctx.cache.lock():
            data = ctx.cache.load()
            data.leases[lease] = dataclasses.replace(data.leases[lease], **fields)
            ctx.cache.save(data)
        return snap

    monkeypatch.setattr(engine, "refresh", refresh_then_edit)


UNWRITABLE_UNDER_LOCK = [
    pytest.param({"state": "unreachable"}, 2, "box_unreachable", id="unreachable"),
    pytest.param({"state": "stopped"}, 2, "box_unreachable", id="stopped"),
    pytest.param({"state": "pending", "reachable_at": None}, 1, "lease_pending", id="pending"),
    pytest.param({"state": "unreachable", "destroy_pending": True}, 1, "lease_expired",
                 id="unreachable-destroy-pending"),
    pytest.param({"state": "pending", "reachable_at": None, "destroy_pending": True}, 1,
                 "lease_expired", id="pending-destroy-pending"),
]


@pytest.mark.parametrize("change", [["--by", "30m"], ["--to", "10m"]], ids=["by", "to"])
@pytest.mark.parametrize(("fields", "exit_code", "error"), UNWRITABLE_UNDER_LOCK)
def test_unwritable_between_refresh_and_lock_changes_nothing(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
    change: list[str],
    fields: dict[str, Any],
    exit_code: int,
    error: str,
) -> None:
    row = add_lease(h, label={"expires": NOW + 1800})
    edit_after_refresh(h, monkeypatch, "l-0000a001", **fields)
    code, data = run_json(h, "extend", "l-0000a001", *change)
    assert (code, data["error"]) == (exit_code, error)
    assert label_of(h, row.id).expires == NOW + 1800
    assert h.box.state(row.id).clock == NOW + 1800
    assert [c for c in h.provider.calls if c[0] == "set_label"] == []
    assert h.box.clock_writes == []
    assert "clock_file" not in cached(h, "l-0000a001").guard_missing


# Bulk.


def test_bulk_by_extends_each_lease(h: Harness) -> None:
    a = add_lease(h, "l-0000a001", label={"group": "exp", "expires": NOW + 600})
    b = add_lease(h, "l-0000a002", label={"group": "exp", "expires": NOW + 1200})
    add_lease(h, "l-0000a003", label={"group": "other", "expires": NOW + 600})
    code, data = run_json(h, "extend", "--group", "exp", "--by", "30m")
    assert code == 0
    assert set(data) == {"results", "warnings", "swept"}
    assert data["results"] == [
        {"lease": "l-0000a001", "ok": True, "error": None, "expires_at": "2026-10-29T01:40:00Z"},
        {"lease": "l-0000a002", "ok": True, "error": None, "expires_at": "2026-10-29T01:50:00Z"},
    ]
    assert label_of(h, a.id).expires == NOW + 2400
    assert label_of(h, b.id).expires == NOW + 3000


def test_bulk_to_aligns_expiries_with_one_now(h: Harness) -> None:
    add_lease(h, "l-0000a001", label={"group": "exp", "expires": NOW + 600})
    add_lease(h, "l-0000a002", label={"group": "exp", "expires": NOW + 5000})
    _, data = run_json(h, "extend", "--group", "exp", "--to", "1h")
    assert {r["expires_at"] for r in data["results"]} == {"2026-10-29T02:00:00Z"}


def test_bulk_budget_counts_local_reserve_between_refresh_and_lock(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.env["VASTY_DAILY_BUDGET"] = "1.00"
    add_lease(h, "l-0000a001", label={"group": "exp", "expires": NOW + 1800},
              dph_total=Decimal("0.50"))
    reserve_after_refresh(h, monkeypatch)
    code, data = run_json(h, "extend", "--group", "exp", "--by", "1h")
    assert code == 3
    assert data["error"] == "budget_exceeded"
    assert data["details"] == {"projected": 1.13, "remaining": 0.37, "daily_budget": 1.0}


def test_bulk_release_between_refresh_and_lock_is_expired(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.provider.keep_rows = True
    a = add_lease(h, "l-0000a001", label={"group": "exp", "expires": NOW + 600})
    b = add_lease(h, "l-0000a002", label={"group": "exp", "expires": NOW + 600})
    run_after_refresh(h, monkeypatch, "release", "l-0000a002")
    code, data = run_json(h, "extend", "--group", "exp", "--by", "30m")
    assert code == 1
    assert data["results"] == [
        {"lease": "l-0000a001", "ok": True, "error": None, "expires_at": "2026-10-29T01:40:00Z"},
        {"lease": "l-0000a002", "ok": False, "error": "lease_expired",
         "expires_at": "2026-10-29T01:10:00Z"},
    ]
    lease = cached(h, "l-0000a002")
    assert lease.state == "released"
    assert lease.released_here and lease.destroy_pending
    assert label_of(h, a.id).expires == NOW + 2400
    assert label_of(h, b.id).expires == NOW + 600
    assert [c[1][0] for c in h.provider.calls if c[0] == "set_label"] == [a.id]
    assert h.box.clock_writes == [(a.id, NOW + 2400)]


@pytest.mark.parametrize(
    ("change", "expires"), [(["--by", "30m"], NOW + 3600), (["--to", "10m"], NOW + 600)],
    ids=["by", "to"],
)
@pytest.mark.parametrize(("fields", "exit_code", "error"), UNWRITABLE_UNDER_LOCK)
def test_bulk_unwritable_between_refresh_and_lock_changes_nothing(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
    change: list[str],
    expires: int,
    fields: dict[str, Any],
    exit_code: int,
    error: str,
) -> None:
    a = add_lease(h, "l-0000a001", label={"group": "exp", "expires": NOW + 1800})
    b = add_lease(h, "l-0000a002", label={"group": "exp", "expires": NOW + 1800})
    edit_after_refresh(h, monkeypatch, "l-0000a002", **fields)
    code, data = run_json(h, "extend", "--group", "exp", *change)
    assert code == exit_code
    results = {r["lease"]: r for r in data["results"]}
    assert results["l-0000a001"]["ok"] is True
    assert (results["l-0000a002"]["ok"], results["l-0000a002"]["error"]) == (False, error)
    assert label_of(h, a.id).expires == expires
    assert label_of(h, b.id).expires == NOW + 1800
    assert h.box.state(b.id).clock == NOW + 1800
    assert [c[1][0] for c in h.provider.calls if c[0] == "set_label"] == [a.id]
    assert h.box.clock_writes == [(a.id, expires)]
    assert "clock_file" not in cached(h, "l-0000a002").guard_missing


def test_bulk_budget_is_atomic(h: Harness) -> None:
    h.env["VASTY_DAILY_BUDGET"] = "2.00"
    a = add_lease(h, "l-0000a001", label={"group": "exp", "expires": NOW + 1800},
                  dph_total=Decimal("0.50"))
    b = add_lease(h, "l-0000a002", label={"group": "exp", "expires": NOW + 1800},
                  dph_total=Decimal("0.50"))
    code, data = run_json(h, "extend", "l-0000a001", "--by", "2h")
    assert code == 0
    code, data = run_json(h, "extend", "l-0000a001", "--to", "30m")
    assert code == 0
    h.box.clock_writes.clear()
    code, data = run_json(h, "extend", "--group", "exp", "--by", "2h")
    assert code == 3
    assert data["error"] == "budget_exceeded"
    assert data["details"] == {"projected": 2.5, "remaining": 1.5, "daily_budget": 2.0}
    assert label_of(h, a.id).expires == NOW + 1800
    assert label_of(h, b.id).expires == NOW + 1800
    assert h.box.clock_writes == []


def test_bulk_reports_per_lease_errors_with_highest_exit(h: Harness) -> None:
    add_lease(h, "l-0000a001", label={"group": "exp", "expires": NOW + 600})
    dead = add_lease(h, "l-0000a002", label={"group": "exp", "expires": NOW + 600})
    h.run("status")
    h.box.state(dead.id).reachable = False
    code, data = run_json(h, "extend", "--group", "exp", "--by", "10m")
    assert code == 2
    results = {r["lease"]: r for r in data["results"]}
    assert results["l-0000a001"]["ok"] is True
    assert results["l-0000a002"] == {
        "lease": "l-0000a002", "ok": False, "error": "box_unreachable",
        "expires_at": "2026-10-29T01:10:00Z",
    }


def test_bulk_skips_other_owners(h: Harness) -> None:
    add_lease(h, "l-0000a001", label={"group": "exp", "owner": "nick"})
    code, data = run_json(h, "extend", "--group", "exp", "--by", "10m")
    assert code == 0
    assert data["results"] == []


def test_bulk_empty_target_exits_zero(h: Harness) -> None:
    code, data = run_json(h, "extend", "--group", "nobody", "--by", "10m")
    assert code == 0
    assert data == {"results": [], "warnings": [], "swept": []}
