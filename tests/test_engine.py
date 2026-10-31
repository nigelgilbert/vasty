from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from fakes import NOW, START, Harness, add_lease, lease_label
from vasty import engine
from vasty.errors import VastyError
from vasty.labels import parse
from vasty.models import Balance, Instance, Job, Label
from vasty.timeutil import iso


def label_of(harness: Harness, instance_id: int) -> Label:
    parsed = parse(harness.provider.instances[instance_id].label)
    assert isinstance(parsed, Label)
    return parsed


def refresh(harness: Harness, probe: bool = True) -> engine.Snapshot:
    return engine.refresh(harness.context(), probe=probe)


def edit_cache(harness: Harness, lease_id: str, **fields: Any) -> None:
    ctx = harness.context()
    data = ctx.cache.load()
    for key, value in fields.items():
        setattr(data.leases[lease_id], key, value)
    ctx.cache.save(data)


# Sweep.


def test_sweep_destroys_past_expires(harness: Harness) -> None:
    row = add_lease(harness, label={"name": "ft", "expires": NOW - 10})
    snap = refresh(harness)
    assert harness.provider.destroyed == [row.id]
    assert len(snap.swept) == 1
    entry = snap.swept[0]
    assert (entry.lease, entry.name, entry.ok, entry.error) == ("l-0000a001", "ft", True, None)
    assert entry.expired_at == "2026-10-29T00:59:50Z"
    lease = snap.leases["l-0000a001"]
    assert (lease.state, lease.destroy_pending, lease.history_since) == ("expired", True, None)
    assert snap.active() == []
    assert snap.instances == []
    harness.time.advance(5)
    lease = refresh(harness).leases["l-0000a001"]
    assert (lease.state, lease.destroy_pending, lease.history_since) == ("expired", False, NOW + 5)


def test_sweep_uses_created_plus_ttl_without_expires(harness: Harness) -> None:
    old = add_lease(harness, "l-0000a001", label={"created": NOW - 4000, "ttl": 3600, "expires": None})
    fresh = add_lease(harness, "l-0000a002", label={"created": NOW - 100, "ttl": 3600, "expires": None})
    snap = refresh(harness)
    assert harness.provider.destroyed == [old.id]
    assert [lease.lease for lease in snap.active()] == ["l-0000a002"]
    assert fresh.id in harness.provider.instances


def test_sweep_not_past_at_exact_expiry(harness: Harness) -> None:
    add_lease(harness, label={"expires": NOW})
    snap = refresh(harness)
    assert snap.swept == []
    assert harness.provider.destroyed == []


def test_sweep_aborts_when_expires_moved(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": NOW - 10})
    real_get = harness.provider.get_instance
    extended = lease_label(expires=NOW + 1800)

    def get_instance(instance_id: int) -> Instance | None:
        harness.provider.instances[instance_id].label = extended
        return real_get(instance_id)

    harness.provider.get_instance = get_instance  # type: ignore[method-assign]
    snap = refresh(harness)
    assert harness.provider.destroyed == []
    assert snap.swept == []
    lease = snap.leases["l-0000a001"]
    assert lease.state == "running"
    assert lease.label.expires == NOW + 1800
    assert harness.box.state(row.id).clock == NOW + 1800


def test_sweep_failed_destroy_reports_error(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": NOW - 10})
    harness.provider.fail["destroy"] = VastyError("provider_error", "boom", "retry")
    snap = refresh(harness)
    assert snap.swept[0].ok is False
    assert snap.swept[0].error == "provider_error"
    assert row.id in harness.provider.instances
    lease = snap.leases["l-0000a001"]
    assert (lease.state, lease.destroy_pending, lease.destroy_attempts) == ("expired", True, 1)
    assert lease.last_provider_error == "destroy failed: provider_error"
    assert snap.active() == []
    same = refresh(harness)
    assert same.swept == []
    assert harness.provider.destroyed == []
    harness.time.advance(5)
    again = refresh(harness)
    assert again.swept == []
    assert harness.provider.destroyed == [row.id]
    lease = again.leases["l-0000a001"]
    assert (lease.destroy_pending, lease.last_provider_error) == (True, None)
    harness.time.advance(1)
    lease = refresh(harness).leases["l-0000a001"]
    assert (lease.state, lease.destroy_pending, lease.history_since) == ("expired", False, NOW + 6)


# Destroy lifecycle.


def release_in_cache(harness: Harness, lease_id: str = "l-0000a001") -> None:
    edit_cache(harness, lease_id, state="released", released_here=True, destroy_pending=True,
               destroy_attempts=1, destroy_at=NOW)


def test_retry_delay_doubles_and_caps_at_60s() -> None:
    assert [engine.retry_delay(n) for n in range(8)] == [0, 5, 10, 20, 40, 60, 60, 60]


def test_sweep_does_not_redestroy_a_listed_row(harness: Harness) -> None:
    harness.provider.keep_rows = True
    row = add_lease(harness, "l-0000a003", label={"expires": NOW - 10})
    swept = [[e.lease for e in refresh(harness).swept] for _ in range(3)]
    assert swept == [["l-0000a003"], [], []]
    assert harness.provider.destroyed == [row.id]
    lease = refresh(harness).leases["l-0000a003"]
    assert (lease.state, lease.destroy_pending, lease.destroy_attempts) == ("expired", True, 1)


def test_listed_row_retries_with_backoff_capped_at_60s(harness: Harness) -> None:
    harness.provider.keep_rows = True
    row = add_lease(harness, label={"expires": NOW - 10})
    refresh(harness)
    sent = [NOW]
    for _ in range(200):
        harness.time.advance(1)
        before = len(harness.provider.destroyed)
        snap = refresh(harness)
        assert snap.swept == []
        if len(harness.provider.destroyed) > before:
            sent.append(snap.now)
    assert set(harness.provider.destroyed) == {row.id}
    gaps = [b - a for a, b in zip(sent, sent[1:])]
    assert gaps == [5, 10, 20, 40, 60, 60]
    lease = harness.context().cache.load().leases["l-0000a001"]
    assert (lease.destroy_pending, lease.destroy_attempts, lease.destroy_at) == (True, 7, sent[-1])


def test_released_lease_retries_until_row_gone(harness: Harness) -> None:
    harness.provider.keep_rows = True
    row = add_lease(harness)
    refresh(harness)
    release_in_cache(harness)
    harness.time.advance(4)
    refresh(harness)
    assert harness.provider.destroyed == []
    harness.time.advance(1)
    snap = refresh(harness)
    assert harness.provider.destroyed == [row.id]
    lease = snap.leases["l-0000a001"]
    assert (lease.state, lease.destroy_pending, lease.destroy_attempts) == ("released", True, 2)
    assert lease.history_since is None
    del harness.provider.instances[row.id]
    harness.time.advance(1)
    lease = refresh(harness).leases["l-0000a001"]
    assert (lease.state, lease.destroy_pending, lease.history_since) == ("released", False, NOW + 6)
    assert (lease.destroy_attempts, lease.destroy_at) == (0, None)


def test_failed_retry_records_error_and_backs_off(harness: Harness) -> None:
    harness.provider.keep_rows = True
    add_lease(harness)
    refresh(harness)
    release_in_cache(harness)
    harness.time.advance(5)
    harness.provider.fail["destroy"] = VastyError("provider_error", "boom", "retry")
    lease = refresh(harness).leases["l-0000a001"]
    assert (lease.destroy_pending, lease.destroy_attempts) == (True, 2)
    assert lease.last_provider_error == "destroy failed: provider_error"
    assert harness.provider.destroyed == []
    harness.time.advance(9)
    refresh(harness)
    assert harness.provider.destroyed == []
    harness.time.advance(1)
    lease = refresh(harness).leases["l-0000a001"]
    assert len(harness.provider.destroyed) == 1
    assert lease.last_provider_error is None


def test_failed_retry_on_a_later_refresh_is_reported_in_swept(harness: Harness) -> None:
    row = add_lease(harness, label={"name": "ft", "expires": NOW - 10})
    harness.provider.fail["destroy"] = [VastyError("provider_error", "boom", "retry") for _ in range(2)]
    first = refresh(harness)
    assert [(e.lease, e.ok, e.error) for e in first.swept] == [("l-0000a001", False, "provider_error")]
    assert refresh(harness).swept == []
    harness.time.advance(5)
    snap = refresh(harness)
    assert len(snap.swept) == 1
    entry = snap.swept[0]
    assert (entry.lease, entry.name, entry.ok, entry.error) == ("l-0000a001", "ft", False, "provider_error")
    assert entry.expired_at == "2026-10-29T00:59:50Z"
    assert row.id in harness.provider.instances
    assert snap.leases["l-0000a001"].destroy_attempts == 2
    harness.time.advance(10)
    assert refresh(harness).swept == []
    assert harness.provider.destroyed == [row.id]


def test_refresh_records_sweep_before_a_failing_save(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_lease(harness, "l-0000a009", label={"name": "old", "expires": NOW - 10})
    ctx = harness.context()

    def fail(data: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(ctx.cache, "save", fail)
    with pytest.raises(OSError, match="disk full"):
        engine.refresh(ctx)
    assert [(e.lease, e.ok) for e in ctx.swept] == [("l-0000a009", True)]


def test_skipped_retry_leaves_attempts_and_error_unchanged(harness: Harness) -> None:
    harness.provider.keep_rows = True
    row = add_lease(harness)
    refresh(harness)
    release_in_cache(harness)
    edit_cache(harness, "l-0000a001", last_provider_error="destroy failed: provider_error")
    real_get = harness.provider.get_instance

    def get_instance(instance_id: int) -> Instance | None:
        harness.provider.instances[instance_id].label = lease_label(expires=NOW + 7200)
        return real_get(instance_id)

    harness.provider.get_instance = get_instance  # type: ignore[method-assign]
    harness.time.advance(5)
    snap = refresh(harness)
    assert harness.provider.destroyed == []
    assert snap.swept == []
    lease = snap.leases["l-0000a001"]
    assert (lease.state, lease.destroy_pending) == ("released", True)
    assert (lease.destroy_attempts, lease.destroy_at) == (1, NOW)
    assert lease.last_provider_error == "destroy failed: provider_error"
    harness.provider.get_instance = real_get  # type: ignore[method-assign]
    refresh(harness)
    assert harness.provider.destroyed == [row.id]


def test_failed_retry_of_an_early_release_reports_expired_at_by_now(harness: Harness) -> None:
    harness.provider.keep_rows = True
    add_lease(harness, label={"expires": NOW + 3000})
    refresh(harness)
    release_in_cache(harness)
    harness.time.advance(5)
    harness.provider.fail["destroy"] = VastyError("provider_error", "boom", "retry")
    snap = refresh(harness)
    assert [(e.lease, e.ok, e.error) for e in snap.swept] == [("l-0000a001", False, "provider_error")]
    assert snap.swept[0].expired_at <= iso(snap.now)
    assert snap.swept[0].expired_at == iso(NOW + 5)


def test_released_lease_listed_without_pending_is_destroyed(harness: Harness) -> None:
    harness.provider.keep_rows = True
    row = add_lease(harness)
    refresh(harness)
    edit_cache(harness, "l-0000a001", state="released", released_here=True)
    lease = refresh(harness).leases["l-0000a001"]
    assert harness.provider.destroyed == [row.id]
    assert (lease.state, lease.destroy_pending) == ("released", True)


def test_swept_lease_extended_elsewhere_turns_active(harness: Harness) -> None:
    harness.provider.keep_rows = True
    row = add_lease(harness, label={"expires": NOW - 10})
    refresh(harness)
    harness.provider.instances[row.id].label = lease_label(expires=NOW + 1800)
    harness.time.advance(5)
    lease = refresh(harness).leases["l-0000a001"]
    assert harness.provider.destroyed == [row.id]
    assert (lease.state, lease.destroy_pending, lease.destroy_attempts) == ("running", False, 0)


def test_released_lease_retries_after_label_moved(harness: Harness) -> None:
    harness.provider.keep_rows = True
    row = add_lease(harness)
    refresh(harness)
    release_in_cache(harness)
    harness.provider.instances[row.id].label = lease_label(expires=NOW + 7200)
    harness.time.advance(5)
    lease = refresh(harness).leases["l-0000a001"]
    assert harness.provider.destroyed == [row.id]
    assert (lease.state, lease.destroy_pending) == ("released", True)


def test_destroy_retry_runs_outside_the_probe_pool(harness: Harness) -> None:
    import threading

    harness.provider.keep_rows = True
    add_lease(harness, "l-0000a001")
    add_lease(harness, "l-0000a002")
    refresh(harness)
    release_in_cache(harness)
    threads: list[threading.Thread] = []
    real_destroy = harness.provider.destroy

    def destroy(instance_id: int) -> None:
        threads.append(threading.current_thread())
        real_destroy(instance_id)

    harness.provider.destroy = destroy  # type: ignore[method-assign]
    harness.time.advance(5)
    refresh(harness)
    assert threads == [threading.main_thread()]


def test_destroy_fields_survive_the_cache(harness: Harness) -> None:
    add_lease(harness)
    refresh(harness)
    edit_cache(harness, "l-0000a001", destroy_attempts=3, destroy_at=NOW - 7)
    lease = harness.context().cache.load().leases["l-0000a001"]
    assert (lease.destroy_attempts, lease.destroy_at) == (3, NOW - 7)


def test_sweep_skips_unreadable_rows(harness: Harness) -> None:
    row = harness.provider.add_instance(label=f"vasty:v1;lease=l-1;created={NOW - 9000}")
    snap = refresh(harness)
    assert harness.provider.destroyed == []
    assert snap.unreadable == [row]
    assert snap.orphans == []
    codes = [(w.code, w.lease) for w in snap.warnings]
    assert ("label_unreadable", f"i-{row.id}") in codes


def test_duplicate_lease_id_row_is_unreadable(harness: Harness) -> None:
    first = add_lease(harness)
    second = add_lease(harness)
    snap = refresh(harness)
    assert snap.leases["l-0000a001"].instance_id == first.id
    assert snap.unreadable == [second]


# Reconciliation.


def test_reconcile_released_clears_destroy_pending(harness: Harness) -> None:
    row = add_lease(harness)
    refresh(harness)
    edit_cache(harness, "l-0000a001", state="released", released_here=True, destroy_pending=True,
               destroy_attempts=1, destroy_at=NOW)
    still = refresh(harness)
    assert still.leases["l-0000a001"].state == "released"
    assert still.leases["l-0000a001"].destroy_pending is True
    del harness.provider.instances[row.id]
    harness.time.advance(30)
    snap = refresh(harness)
    lease = snap.leases["l-0000a001"]
    assert (lease.state, lease.destroy_pending, lease.history_since) == ("released", False, NOW + 30)


def test_reconcile_released_here_moves_to_released(harness: Harness) -> None:
    row = add_lease(harness)
    refresh(harness)
    edit_cache(harness, "l-0000a001", released_here=True)
    del harness.provider.instances[row.id]
    assert refresh(harness).leases["l-0000a001"].state == "released"


def test_reconcile_expired_when_past_effective_expiry(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": NOW + 10})
    refresh(harness)
    del harness.provider.instances[row.id]
    harness.time.advance(20)
    lease = refresh(harness).leases["l-0000a001"]
    assert lease.state == "expired"
    assert lease.expired_at == NOW + 10


def test_reconcile_gone_with_time_left(harness: Harness) -> None:
    row = add_lease(harness)
    refresh(harness)
    del harness.provider.instances[row.id]
    snap = refresh(harness)
    assert snap.leases["l-0000a001"].state == "gone"
    assert snap.active() == []


def test_reconcile_adopts_another_machines_lease(harness: Harness) -> None:
    add_lease(harness, "l-0000b001", label={"owner": "nick", "name": "scratch"},
              gpu_name="RTX 4090", dph_total=Decimal("0.38"), image="vasty/base:cuda12.4")
    snap = refresh(harness)
    lease = snap.leases["l-0000b001"]
    assert lease.state == "running"
    assert (lease.gpu, lease.price_per_hr, lease.image) == ("RTX 4090", Decimal("0.38"),
                                                             "vasty/base:cuda12.4")
    assert (lease.ssh_host, lease.ssh_port) == ("198.51.100.9", 40022)
    assert lease.ports == {22: 40022, 8000: 40080, 8080: 40081}
    assert "l-0000b001" in harness.context().cache.load().leases
    assert snap.warnings == []


def test_history_pruned_24h_after_first_seen_gone(harness: Harness) -> None:
    row = add_lease(harness, label={"ttl": 7200})
    refresh(harness)
    harness.time.advance(600)
    del harness.provider.instances[row.id]
    gone_at = refresh(harness).leases["l-0000a001"].history_since
    assert gone_at == NOW + 600
    harness.time.advance(86_400 - 1)
    assert "l-0000a001" in refresh(harness).leases
    harness.time.advance(1)
    assert "l-0000a001" not in refresh(harness).leases


def test_reappearing_gone_lease_is_active_again(harness: Harness) -> None:
    row = add_lease(harness)
    refresh(harness)
    saved = harness.provider.instances.pop(row.id)
    assert refresh(harness).leases["l-0000a001"].state == "gone"
    harness.provider.instances[row.id] = saved
    lease = refresh(harness).leases["l-0000a001"]
    assert lease.state == "running"
    assert lease.history_since is None


def test_cache_rebuilt_warning(harness: Harness) -> None:
    ctx = harness.context()
    ctx.cache.path.parent.mkdir(parents=True, exist_ok=True)
    ctx.cache.path.write_text("{not json")
    add_lease(harness)
    snap = refresh(harness)
    assert [w.code for w in snap.warnings] == ["cache_rebuilt"]
    assert "l-0000a001" in snap.leases
    assert [w.code for w in refresh(harness).warnings] == []


def test_clock_unverified_warning(harness: Harness) -> None:
    harness.provider.date_header = False
    snap = refresh(harness)
    assert [(w.code, w.lease, w.fix) for w in snap.warnings] == [
        ("clock_unverified", None, "vasty status")
    ]


def test_cache_saved_with_cached_at(harness: Harness) -> None:
    add_lease(harness)
    refresh(harness)
    data = harness.context().cache.load()
    assert data.cached_at == NOW
    assert len(data.instances) == 1


# Probe.


def test_probe_copies_clock_file_to_label(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": None})
    harness.box.state(row.id).clock = NOW + 1234
    snap = refresh(harness)
    assert label_of(harness, row.id).expires == NOW + 1234
    assert snap.leases["l-0000a001"].label.expires == NOW + 1234
    assert snap.leases["l-0000a001"].reachable_at == NOW


def test_probe_writes_and_clears_miss(harness: Harness) -> None:
    row = add_lease(harness)
    box = harness.box.state(row.id)
    box.guard_missing = ["destroy_key", "watchdog"]
    snap = refresh(harness)
    assert label_of(harness, row.id).miss == ["watchdog", "destroy_key"]
    assert snap.leases["l-0000a001"].guard_missing == ["watchdog", "destroy_key"]
    writes = [c for c in harness.provider.calls if c[0] == "set_label"]
    refresh(harness)
    assert [c for c in harness.provider.calls if c[0] == "set_label"] == writes
    box.guard_missing = []
    snap = refresh(harness)
    assert label_of(harness, row.id).miss == []
    assert snap.leases["l-0000a001"].guard_missing == []


def test_probe_label_write_aborts_when_expires_moved(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": None})
    harness.box.state(row.id).clock = NOW + 1234
    real_get = harness.provider.get_instance
    moved = lease_label(expires=NOW + 999)

    def get_instance(instance_id: int) -> Instance | None:
        harness.provider.instances[instance_id].label = moved
        return real_get(instance_id)

    harness.provider.get_instance = get_instance  # type: ignore[method-assign]
    snap = refresh(harness)
    assert not [c for c in harness.provider.calls if c[0] == "set_label"]
    assert snap.leases["l-0000a001"].label.expires == NOW + 999


def test_unreachable_after_answered_and_jobs_unknown(harness: Harness) -> None:
    row = add_lease(harness)
    box = harness.box.state(row.id)
    box.jobs["j-1"] = Job(id="j-1", cmd="python train.py", started_at=NOW - 60, exit=None,
                          state="running")
    assert refresh(harness).leases["l-0000a001"].state == "running"
    box.reachable = False
    harness.time.advance(360)
    snap = refresh(harness)
    lease = snap.leases["l-0000a001"]
    assert lease.state == "unreachable"
    assert lease.reachable_at == NOW
    from vasty.views import lease_view

    view = lease_view(lease, snap.now)
    assert [(j.id, j.state, j.exit) for j in view.jobs] == [("j-1", "unknown", None)]


def test_never_answered_is_pending(harness: Harness) -> None:
    add_lease(harness, reachable=False)
    assert refresh(harness).leases["l-0000a001"].state == "pending"


def test_startup_running_is_pending(harness: Harness) -> None:
    row = add_lease(harness)
    harness.box.state(row.id).startup_exit = None
    assert refresh(harness).leases["l-0000a001"].state == "pending"


def test_startup_cut_off_by_restart(harness: Harness) -> None:
    row = add_lease(harness)
    harness.box.state(row.id).startup_exit = -1
    lease = refresh(harness).leases["l-0000a001"]
    assert lease.state == "running"
    assert lease.startup_interrupted is True
    assert lease.startup_exit is None


def test_probe_skipped_when_not_running(harness: Harness) -> None:
    add_lease(harness, actual_status="loading")
    assert refresh(harness).leases["l-0000a001"].state == "pending"
    add_lease(harness, "l-0000a002", actual_status="stopped")
    assert refresh(harness).leases["l-0000a002"].state == "stopped"


def test_probe_false_keeps_state(harness: Harness) -> None:
    row = add_lease(harness)
    refresh(harness)
    harness.box.state(row.id).reachable = False
    assert refresh(harness, probe=False).leases["l-0000a001"].state == "running"


def test_jobs_merge_by_id(harness: Harness) -> None:
    row = add_lease(harness)
    box = harness.box.state(row.id)
    box.jobs["j-1"] = Job(id="j-1", cmd="a", started_at=NOW, exit=None, state="running")
    refresh(harness)
    box.jobs = {"j-2": Job(id="j-2", cmd="b", started_at=NOW, exit=None, state="running")}
    snap = refresh(harness)
    assert [j.id for j in snap.leases["l-0000a001"].jobs] == ["j-1", "j-2"]


def test_adopted_lease_retries_guard_steps(harness: Harness) -> None:
    row = add_lease(harness)
    box = harness.box.state(row.id)
    box.guard_missing = ["watchdog"]
    refresh(harness)
    assert label_of(harness, row.id).miss == ["watchdog"]
    edit_cache(harness, "l-0000a001", adopted=True)
    box.adopt_missing = []
    snap = refresh(harness)
    assert snap.leases["l-0000a001"].guard_missing == []
    assert label_of(harness, row.id).miss == []


def test_adoption_rerun_backs_off_while_a_layer_stays_missing(harness: Harness) -> None:
    row = add_lease(harness)
    box = harness.box.state(row.id)
    box.guard_missing = ["watchdog"]
    refresh(harness)
    edit_cache(harness, "l-0000a001", adopted=True)
    box.adopt_missing = ["watchdog"]
    counts = []
    for step in (0, 0, 5, 5, 5, 10):
        harness.time.advance(step)
        refresh(harness)
        counts.append(len(harness.box.adopts))
    assert counts == [1, 1, 2, 2, 3, 3]
    lease = refresh(harness).leases["l-0000a001"]
    assert (lease.adopt_attempts, lease.adopt_at) == (3, NOW + 15)
    box.adopt_missing = []
    harness.time.advance(10)
    lease = refresh(harness).leases["l-0000a001"]
    assert len(harness.box.adopts) == 4
    assert (lease.adopt_attempts, lease.adopt_at, lease.guard_missing) == (0, None, [])
    refresh(harness)
    assert len(harness.box.adopts) == 4


PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample test@host"
ALL_LAYERS = ["watchdog", "destroy_key", "clock_file"]


def add_key(harness: Harness) -> None:
    ssh = harness.home / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text("PRIVATE\n")
    (ssh / "id_ed25519.pub").write_text(PUB + "\n")


def adopted_orphan(harness: Harness, reachable: bool) -> Instance:
    """Add a row with the label `tag` writes before its guard steps, and no cache entry."""
    label = lease_label("l-abababab", created=NOW, ttl=1800, miss=list(ALL_LAYERS))
    row = harness.provider.add_instance(id=55120, label=label)
    if reachable:
        box = harness.box.state(row.id)
        box.startup_started, box.startup_exit = False, None
    return row


def test_failed_probe_retries_key_attach_on_main_thread_with_backoff(harness: Harness) -> None:
    import threading

    add_key(harness)
    row = adopted_orphan(harness, reachable=False)
    threads: list[threading.Thread] = []
    real_attach = harness.provider.attach_ssh_key

    def attach(public_key: str, instance_id: int | None = None) -> None:
        threads.append(threading.current_thread())
        real_attach(public_key, instance_id)

    harness.provider.attach_ssh_key = attach  # type: ignore[method-assign]
    counts = []
    for step in (0, 0, 5, 5, 5):
        harness.time.advance(step)
        refresh(harness)
        counts.append(len(harness.provider.attached))
    assert counts == [1, 1, 2, 2, 3]
    assert harness.provider.attached[0] == (PUB, row.id)
    assert threads == [threading.main_thread()] * 3
    assert harness.box.adopts == []


def test_failed_key_attach_records_the_error(harness: Harness) -> None:
    add_key(harness)
    adopted_orphan(harness, reachable=False)
    harness.provider.fail["attach_ssh_key"] = VastyError("provider_error", "boom", "Run vasty status.")
    lease = refresh(harness).leases["l-abababab"]
    assert (lease.key_attempts, lease.key_attach_at) == (1, NOW)
    assert lease.last_provider_error == "key attach failed: provider_error"


def test_successful_probe_reruns_adoption_and_resets_backoff(harness: Harness) -> None:
    add_key(harness)
    row = adopted_orphan(harness, reachable=False)
    refresh(harness)
    box = harness.box.state(row.id)
    box.startup_started, box.startup_exit = False, None
    lease = refresh(harness).leases["l-abababab"]
    assert harness.box.adopts == [row.id]
    assert (lease.adopted, lease.guard_missing, lease.key_attempts) == (True, [], 0)
    assert label_of(harness, row.id).miss == []


def test_failed_adoption_rerun_keeps_layers_in_label(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vasty.remote import BoxUnreachableError, SshTarget

    row = adopted_orphan(harness, reachable=True)

    def fail(target: SshTarget, expires: int) -> list[str]:
        raise BoxUnreachableError("adopt failed")

    monkeypatch.setattr(harness.box, "adopt", fail)
    lease = refresh(harness).leases["l-abababab"]
    assert label_of(harness, row.id).miss == ["watchdog", "destroy_key"]
    assert lease.adopted is True


def test_held_adoption_rerun_keeps_layers_in_label(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vasty.remote import BoxUnreachableError, SshTarget

    row = adopted_orphan(harness, reachable=True)

    def fail(target: SshTarget, expires: int) -> list[str]:
        raise BoxUnreachableError("adopt failed")

    monkeypatch.setattr(harness.box, "adopt", fail)
    refresh(harness)
    for step in (1, 2):
        harness.time.advance(step)
        lease = refresh(harness).leases["l-abababab"]
        assert label_of(harness, row.id).miss == ["watchdog", "destroy_key"]
        assert lease.guard_missing == ["watchdog", "destroy_key"]
        assert (lease.adopt_attempts, lease.adopt_at) == (1, NOW)


def test_lost_cache_entry_reruns_adoption_from_the_box_marker(harness: Harness) -> None:
    row = adopted_orphan(harness, reachable=True)
    refresh(harness)
    box = harness.box.state(row.id)
    assert (harness.box.adopts, box.adopted, box.guard_file) == ([row.id], True, True)
    ctx = harness.context()
    data = ctx.cache.load()
    del data.leases["l-abababab"]
    ctx.cache.save(data)
    box.alive_mtime = int(harness.time.wall_now) - 600
    lease = refresh(harness).leases["l-abababab"]
    assert harness.box.adopts == [row.id, row.id]
    assert lease.adopted is True


def test_box_marker_sets_adopted_without_a_rerun(harness: Harness) -> None:
    row = add_lease(harness)
    harness.box.state(row.id).adopted = True
    lease = refresh(harness).leases["l-0000a001"]
    assert harness.box.adopts == []
    assert lease.adopted is True


def test_marker_without_guard_file_or_startup_keeps_layers_and_reruns(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vasty.remote import BoxUnreachableError, SshTarget

    row = adopted_orphan(harness, reachable=True)
    box = harness.box.state(row.id)
    box.adopted = True
    real_adopt = harness.box.adopt

    def fail(target: SshTarget, expires: int) -> list[str]:
        raise BoxUnreachableError("adopt failed")

    monkeypatch.setattr(harness.box, "adopt", fail)
    lease = refresh(harness).leases["l-abababab"]
    assert (box.guard_file, box.startup_started) == (False, False)
    assert label_of(harness, row.id).miss == ["watchdog", "destroy_key"]
    assert lease.guard_missing == ["watchdog", "destroy_key"]
    assert lease.adopted is True
    monkeypatch.setattr(harness.box, "adopt", real_adopt)
    harness.time.advance(5)
    lease = refresh(harness).leases["l-abababab"]
    assert harness.box.adopts == [row.id]
    assert (lease.guard_missing, label_of(harness, row.id).miss) == ([], [])


def test_reserve_lease_with_missing_layers_skips_adoption_retries(harness: Harness) -> None:
    add_key(harness)
    row = add_lease(harness)
    box = harness.box.state(row.id)
    box.guard_missing = ["destroy_key"]
    refresh(harness)
    assert label_of(harness, row.id).miss == ["destroy_key"]
    refresh(harness)
    box.reachable = False
    harness.time.advance(60)
    refresh(harness)
    assert harness.box.adopts == []
    assert harness.provider.attached == []


def test_reserve_box_between_guard_file_and_startup_skips_adoption(harness: Harness) -> None:
    row = add_lease(harness)
    box = harness.box.state(row.id)
    box.startup_started, box.startup_exit, box.guard_file = False, None, True
    box.guard_missing = ["watchdog", "destroy_key"]
    lease = refresh(harness).leases["l-0000a001"]
    assert harness.box.adopts == []
    assert lease.adopted is False
    assert lease.guard_missing == ["watchdog", "destroy_key"]


# SSH endpoint.


def test_ssh_target_direct_and_proxy(harness: Harness) -> None:
    add_lease(harness, "l-0000a001")
    add_lease(harness, "l-0000a002", runtype="ssh_proxy", ssh_host="ssh5.vast.ai", ssh_port=12345)
    add_lease(harness, "l-0000a003", reachable=False, public_ipaddr=None, ports={})
    snap = refresh(harness)
    direct = engine.ssh_target(snap.leases["l-0000a001"])
    assert (direct.host, direct.port) == ("198.51.100.9", 40022)
    proxy = engine.ssh_target(snap.leases["l-0000a002"])
    assert (proxy.host, proxy.port) == ("ssh5.vast.ai", 12345)
    with pytest.raises(VastyError) as exc:
        engine.ssh_target(snap.leases["l-0000a003"])
    assert exc.value.code == "lease_pending"


# Billing.


def calls(harness: Harness, name: str) -> list[Any]:
    return [arg for call, arg in harness.provider.calls if call == name]


def test_read_charges_caches_for_60s(harness: Harness) -> None:
    add_lease(harness)
    harness.provider.billed = {999: Decimal("1.00")}
    ctx = harness.context()
    snap = engine.refresh(ctx)
    charges = engine.read_charges(ctx, snap)
    assert charges is not None and snap.charges == charges
    assert charges.per_instance == {999: Decimal("1.00")}
    assert charges.today == Decimal("1.00")
    assert len(calls(harness, "charges")) == 1
    harness.time.advance(30)
    engine.read_charges(ctx, engine.refresh(ctx))
    assert len(calls(harness, "charges")) == 1
    harness.time.advance(31)
    engine.read_charges(ctx, engine.refresh(ctx))
    assert len(calls(harness, "charges")) == 2


def test_charges_start_reaches_back_to_the_oldest_lease(harness: Harness) -> None:
    ctx = harness.context()
    engine.read_charges(ctx, engine.refresh(ctx))
    assert calls(harness, "charges") == [(START, NOW)]
    add_lease(harness, label={"created": START - 3600, "ttl": 4 * 3600})
    engine.read_charges(ctx, engine.refresh(ctx))
    assert calls(harness, "charges")[-1] == (START - 86_400, NOW)
    assert ctx.cache.load().charges_start == START - 86_400


def test_read_charges_failure_sets_none(harness: Harness) -> None:
    harness.provider.fail["charges"] = VastyError("provider_error", "down", "retry")
    ctx = harness.context()
    snap = engine.refresh(ctx)
    assert engine.read_charges(ctx, snap) is None
    assert snap.charges is None


def test_read_balance_caches_balance_and_credit(harness: Harness) -> None:
    harness.provider.account_balance = Decimal("0")
    harness.provider.account_credit = Decimal("19.90")
    ctx = harness.context()
    snap = engine.refresh(ctx)
    assert engine.read_balance(ctx, snap) == Balance(Decimal("0"), Decimal("19.90"))
    assert snap.balance == Balance(Decimal("0"), Decimal("19.90"))
    data = ctx.cache.load()
    assert (data.balance, data.credit, data.balance_at) == (Decimal("0"), Decimal("19.90"), NOW)
    harness.time.advance(59)
    engine.read_balance(ctx, engine.refresh(ctx))
    assert len(calls(harness, "balance")) == 1
    harness.time.advance(1)
    harness.provider.fail["balance"] = VastyError("provider_error", "down", "retry")
    snap = engine.refresh(ctx)
    assert engine.read_balance(ctx, snap) is None
    assert snap.balance is None


def test_cached_snapshot_keeps_billing_read_today_only(harness: Harness) -> None:
    harness.provider.billed = {999: Decimal("1.00")}
    ctx = harness.context()
    snap = engine.refresh(ctx)
    engine.read_charges(ctx, snap)
    engine.read_balance(ctx, snap)
    cached = engine.cached_snapshot(ctx)
    assert cached.charges == snap.charges
    assert cached.balance == snap.balance
    harness.time.advance(86_400)
    cached = engine.cached_snapshot(ctx)
    assert cached.charges is None
    assert cached.balance == snap.balance


# Guard of a lease no probe on this machine has answered.


def test_rebuilt_loading_lease_starts_with_every_layer_missing(harness: Harness) -> None:
    add_lease(harness, actual_status="loading")
    snap = refresh(harness)
    assert snap.leases["l-0000a001"].guard_missing == ["watchdog", "destroy_key", "clock_file"]


def test_rebuilt_lease_takes_layers_from_label_miss(harness: Harness) -> None:
    add_lease(harness, actual_status="loading", label={"miss": ["destroy_key"]})
    snap = refresh(harness)
    assert snap.leases["l-0000a001"].guard_missing == ["destroy_key"]


def test_rebuilt_lease_turns_full_once_the_probe_answers(harness: Harness) -> None:
    add_lease(harness)
    snap = refresh(harness)
    lease = snap.leases["l-0000a001"]
    assert lease.reachable_at == NOW
    assert lease.guard_missing == []


def test_rebuilt_lease_keeps_every_layer_missing_when_the_probe_fails(harness: Harness) -> None:
    add_lease(harness, reachable=False)
    snap = refresh(harness)
    lease = snap.leases["l-0000a001"]
    assert lease.reachable_at is None
    assert lease.guard_missing == ["watchdog", "destroy_key", "clock_file"]


@pytest.mark.parametrize("status, probe", [("running", True), ("running", False), ("loading", True)])
def test_legacy_unprobed_entry_turns_every_layer_missing(
    harness: Harness, status: str, probe: bool
) -> None:
    add_lease(harness, reachable=False, actual_status=status)
    refresh(harness)
    edit_cache(harness, "l-0000a001", guard_missing=[])
    lease = refresh(harness, probe=probe).leases["l-0000a001"]
    assert lease.guard_missing == ["watchdog", "destroy_key", "clock_file"]


def test_legacy_entry_keeps_observed_layers(harness: Harness) -> None:
    add_lease(harness, reachable=False)
    refresh(harness)
    edit_cache(harness, "l-0000a001", guard_missing=[], adopted=True)
    assert refresh(harness).leases["l-0000a001"].guard_missing == []


def test_row_label_reads_the_row(harness: Harness) -> None:
    ctx = harness.context()
    row = add_lease(harness)
    unreadable = harness.provider.add_instance(label=f"vasty:v1;lease=l-1;created={NOW - 9000}")
    found = engine.row_label(ctx, row.id)
    assert found is not None and found.lease == "l-0000a001"
    assert engine.row_label(ctx, unreadable.id) is None
    assert engine.row_label(ctx, 999_999) is None
    harness.provider.fail["get_instance"] = VastyError("provider_error", "boom", "retry")
    with pytest.raises(VastyError):
        engine.row_label(ctx, row.id)


def test_write_label_checks_expires(harness: Harness) -> None:
    row = add_lease(harness, label={"expires": NOW + 60})
    ctx = harness.context()
    new = Label(lease="l-0000a001", owner="claude", created=NOW - 600, ttl=3600, expires=NOW + 99)
    assert engine.write_label(ctx, row.id, NOW + 1, new) is False
    assert engine.write_label(ctx, row.id, NOW + 60, new) is True
    assert label_of(harness, row.id).expires == NOW + 99
    assert engine.destroy_checked(ctx, row.id, NOW + 60) is False
    assert engine.destroy_checked(ctx, row.id, NOW + 99) is True
    assert harness.provider.destroyed == [row.id]
