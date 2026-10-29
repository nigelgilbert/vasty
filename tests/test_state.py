from __future__ import annotations

from typing import Any

import pytest

from vasty.models import CachedLease, Job, Label, LeaseState, ProbeResult
from vasty.state import (
    derive_state,
    effective_expiry,
    fix_for,
    guard,
    lease_warnings,
    make_warning,
    resolve_state,
    ttl_remaining,
)
from vasty.timeutil import format_duration

NOW = 1_793_235_600
WARN = 300


def probe(started: bool = False, exit: int | None = None, interrupted: bool = False) -> ProbeResult:
    return ProbeResult(
        clock_expires=NOW + 600, clock_readable=True, guard_missing=[],
        startup_started=started, startup_exit=exit, alive_mtime=NOW,
        startup_interrupted=interrupted,
    )


def label(**kw: Any) -> Label:
    base: dict[str, Any] = dict(lease="l-8b12", owner="claude", created=NOW - 600, ttl=1800)
    base.update(kw)
    return Label(**base)


def lease(state: LeaseState = "running", **kw: Any) -> CachedLease:
    lab = kw.pop("label", None) or label(expires=NOW + 3600)
    return CachedLease(lease=lab.lease, instance_id=1001, label=lab, state=state, **kw)


def job(job_id: str, state: Any) -> Job:
    return Job(id=job_id, cmd="python train.py", started_at=NOW - 60, exit=None, state=state)


def test_effective_expiry_prefers_label_expires() -> None:
    assert effective_expiry(label(expires=NOW + 5)) == NOW + 5
    assert effective_expiry(label()) == NOW - 600 + 1800


def test_ttl_remaining_floors_at_zero() -> None:
    assert ttl_remaining(label(expires=NOW + 90), NOW) == 90
    assert ttl_remaining(label(expires=NOW - 90), NOW) == 0


@pytest.mark.parametrize(
    "status, result, before, expected",
    [
        (None, None, False, "pending"),
        ("created", None, False, "pending"),
        ("loading", None, True, "pending"),
        ("running", None, False, "pending"),
        ("running", None, True, "unreachable"),
        ("running", probe(started=True), True, "pending"),
        ("running", probe(started=True), False, "pending"),
        ("running", probe(started=False), False, "running"),
        ("running", probe(started=True, exit=0), False, "running"),
        ("running", probe(started=True, exit=1), True, "running"),
        ("running", probe(started=True, interrupted=True), True, "running"),
        ("exited", None, True, "stopped"),
        ("stopped", None, False, "stopped"),
        ("offline", None, False, "unreachable"),
        ("unknown", None, True, "unreachable"),
        ("Running", probe(exit=0), False, "running"),
        ("scheduling", None, False, "pending"),
        ("scheduling", None, True, "unreachable"),
    ],
)
def test_derive_state(status: str | None, result: ProbeResult | None, before: bool, expected: str) -> None:
    assert derive_state(status, result, before) == expected


@pytest.mark.parametrize(
    "previous, derived, expected",
    [
        ("expired", "pending", "expired"),
        ("released", "unreachable", "released"),
        ("gone", "pending", "gone"),
        ("running", "unreachable", "unreachable"),
        ("released", "running", "running"),
    ],
)
def test_history_takes_precedence(previous: LeaseState, derived: LeaseState, expected: str) -> None:
    assert resolve_state(previous, derived) == expected


@pytest.mark.parametrize(
    "missing, expected",
    [
        ([], ("full", [])),
        (["watchdog"], ("partial", ["watchdog"])),
        (["destroy_key"], ("partial", ["destroy_key"])),
        (["clock_file"], ("partial", ["clock_file"])),
        (["clock_file", "watchdog"], ("partial", ["watchdog", "clock_file"])),
        (["clock_file", "destroy_key", "watchdog", "watchdog"], ("partial", ["watchdog", "destroy_key", "clock_file"])),
        (["sweep"], ("full", [])),
    ],
)
def test_guard(missing: list[str], expected: tuple[str, list[str]]) -> None:
    assert guard(lease(guard_missing=missing)) == expected


@pytest.mark.parametrize(
    "seconds, text",
    [
        (0, "0s"), (45, "45s"), (60, "1m"), (180, "3m"), (359, "5m"), (4320, "1h12m"),
        (7260, "2h1m"), (90000, "1d1h"), (-5, "0s"),
    ],
)
def test_warning_durations(seconds: int, text: str) -> None:
    assert format_duration(seconds) == text


def codes(items: list[Any]) -> list[str]:
    return [w.code for w in items]


def test_expiring_soon() -> None:
    [w] = lease_warnings(lease(label=label(expires=NOW + 180)), NOW, WARN)
    assert (w.code, w.lease, w.message, w.fix) == ("expiring_soon", "l-8b12", "3m left", "vasty extend l-8b12 --by 30m")


@pytest.mark.parametrize("remaining", [0, WARN + 1, 3600])
def test_no_expiring_soon_outside_window(remaining: int) -> None:
    assert lease_warnings(lease(label=label(expires=NOW + remaining)), NOW, WARN) == []


def test_expiring_soon_at_threshold() -> None:
    assert codes(lease_warnings(lease(label=label(expires=NOW + WARN)), NOW, WARN)) == ["expiring_soon"]


def test_expiring_soon_only_on_running() -> None:
    assert lease_warnings(lease("pending", label=label(expires=NOW + 60)), NOW, WARN) == []


@pytest.mark.parametrize("job_state", ["running", "serving"])
def test_expiring_with_running_job_replaces_expiring_soon(job_state: str) -> None:
    item = lease(label=label(expires=NOW + 120), jobs=[job("j-1", job_state), job("j-2", "exited")])
    [w] = lease_warnings(item, NOW, WARN)
    assert w.code == "expiring_with_running_job"
    assert w.message == "2m left, j-1 running"
    assert w.fix == "vasty extend l-8b12 --by 30m"


def test_box_unreachable() -> None:
    [w] = lease_warnings(lease("unreachable", reachable_at=NOW - 360), NOW, WARN)
    assert (w.code, w.message, w.fix) == ("box_unreachable", "no answer for 6m", "vasty release l-8b12")


def test_box_unreachable_never_answered() -> None:
    [w] = lease_warnings(lease("unreachable"), NOW, WARN)
    assert w.message == "no answer"


def test_unreachable_lease_gets_no_expiring_soon() -> None:
    item = lease("unreachable", label=label(expires=NOW + 60), reachable_at=NOW - 60)
    assert codes(lease_warnings(item, NOW, WARN)) == ["box_unreachable"]


def test_guard_partial() -> None:
    [w] = lease_warnings(lease(guard_missing=["watchdog"], reachable_at=NOW), NOW, WARN)
    assert (w.code, w.message, w.fix) == ("guard_partial", "watchdog not running", "vasty release l-8b12")


def test_guard_partial_names_every_layer() -> None:
    [w] = lease_warnings(lease(guard_missing=["clock_file", "destroy_key"], reachable_at=NOW), NOW, WARN)
    assert w.message == "destroy key missing, clock file out of sync"


ALL_LAYERS = ["watchdog", "destroy_key", "clock_file"]


def test_unprobed_pending_lease_is_partial_without_warning() -> None:
    item = lease("pending", guard_missing=list(ALL_LAYERS))
    assert guard(item) == ("partial", ALL_LAYERS)
    assert lease_warnings(item, NOW, WARN) == []


def test_probed_pending_lease_with_missing_layers_warns() -> None:
    item = lease("pending", guard_missing=["destroy_key"], reachable_at=NOW - 30)
    assert codes(lease_warnings(item, NOW, WARN)) == ["guard_partial"]


def test_label_miss_from_another_machine_counts_as_observed() -> None:
    item = lease("pending", label=label(miss=["watchdog"]), guard_missing=["watchdog"])
    [w] = lease_warnings(item, NOW, WARN)
    assert (w.code, w.message) == ("guard_partial", "watchdog not running")


def test_adopted_lease_without_answer_warns() -> None:
    item = lease("pending", guard_missing=list(ALL_LAYERS), adopted=True)
    assert codes(lease_warnings(item, NOW, WARN)) == ["guard_partial"]


def test_probed_lease_with_no_missing_layers_is_full() -> None:
    item = lease("running", guard_missing=[], reachable_at=NOW)
    assert guard(item) == ("full", [])
    assert lease_warnings(item, NOW, WARN) == []


def test_startup_failed_on_non_zero_exit() -> None:
    [w] = lease_warnings(lease(startup_started=True, startup_exit=2), NOW, WARN)
    assert w.code == "startup_failed"
    assert w.message == "startup exited 2"
    assert w.fix == "vasty ssh l-8b12 -- cat /workspace/.vasty/startup.log"


def test_startup_failed_on_restart_cut_off() -> None:
    [w] = lease_warnings(lease(startup_started=True, startup_interrupted=True), NOW, WARN)
    assert (w.code, w.message) == ("startup_failed", "startup cut off by a restart")


@pytest.mark.parametrize(
    "started, exit, interrupted",
    [(False, None, False), (True, 0, False), (True, None, False), (True, 0, True)],
)
def test_no_startup_failed(started: bool, exit: int | None, interrupted: bool) -> None:
    item = lease(startup_started=started, startup_exit=exit, startup_interrupted=interrupted)
    assert lease_warnings(item, NOW, WARN) == []


def test_expired_with_running_jobs() -> None:
    item = lease("expired", label=label(expires=NOW - 60), jobs=[job("j-1", "running"), job("j-2", "serving")])
    [w] = lease_warnings(item, NOW, WARN)
    assert w.code == "expired_with_running_jobs"
    assert w.message == "expired with j-1, j-2 running"
    assert w.fix == "vasty status l-8b12"


@pytest.mark.parametrize("state", ["expired", "released", "gone"])
def test_history_leases_carry_only_expired_with_running_jobs(state: LeaseState) -> None:
    item = lease(state, label=label(expires=NOW - 60), guard_missing=["watchdog"], startup_exit=1,
                 jobs=[job("j-1", "exited")])
    assert lease_warnings(item, NOW, WARN) == []


def test_warnings_combine_in_order() -> None:
    item = lease(label=label(expires=NOW + 60), guard_missing=["destroy_key"], startup_exit=1,
                 reachable_at=NOW)
    assert codes(lease_warnings(item, NOW, WARN)) == ["expiring_soon", "guard_partial", "startup_failed"]


def test_fixes_use_the_lease_id_and_shell_quote_it() -> None:
    odd = "l-x'; rm -rf ~"
    item = lease(label=label(lease=odd, name="eval-2", expires=NOW + 60))
    [w] = lease_warnings(item, NOW, WARN)
    assert w.lease == odd
    assert w.fix == "vasty extend 'l-x'\"'\"'; rm -rf ~' --by 30m"


@pytest.mark.parametrize(
    "code, target, fix",
    [
        ("expiring_soon", "l-1", "vasty extend l-1 --by 30m"),
        ("expiring_with_running_job", "l-1", "vasty extend l-1 --by 30m"),
        ("box_unreachable", "l-1", "vasty release l-1"),
        ("guard_partial", "l-1", "vasty release l-1"),
        ("orphan", "i-55120", "vasty tag i-55120 --ttl 30m"),
        ("startup_failed", "l-1", "vasty ssh l-1 -- cat /workspace/.vasty/startup.log"),
        ("expired_with_running_jobs", "l-1", "vasty status l-1"),
        ("flag_mismatch", "l-1", "vasty status l-1"),
        ("label_unreadable", "i-7", "vasty release i-7"),
        ("budget_low", None, "vasty status"),
        ("spend_unavailable", None, "vasty status"),
        ("clock_unverified", None, "vasty status"),
        ("cache_rebuilt", None, "vasty status"),
        ("orphan", "i-1 2", "vasty tag 'i-1 2' --ttl 30m"),
    ],
)
def test_fix_table(code: str, target: str | None, fix: str) -> None:
    assert fix_for(code, target) == fix


def test_make_warning() -> None:
    w = make_warning("orphan", "i-55120", "not created by vasty")
    assert (w.code, w.lease, w.message, w.fix) == ("orphan", "i-55120", "not created by vasty", "vasty tag i-55120 --ttl 30m")
    assert make_warning("budget_low", None, "x").lease is None


def test_fix_errors() -> None:
    with pytest.raises(ValueError):
        fix_for("nope", None)
    with pytest.raises(ValueError):
        fix_for("orphan", None)
