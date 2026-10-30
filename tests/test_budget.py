from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from vasty.budget import (
    billing_fresh,
    budget_low,
    budget_low_warning,
    burn_per_hr,
    check,
    cost,
    day_start,
    extend_delta,
    lease_commitments,
    projection,
    require_spent,
    spend_unavailable_warning,
    spent_today,
)
from vasty.errors import VastyError
from vasty.models import CachedLease, Charges, Instance, Label, LeaseState

D = Decimal
MIDNIGHT = 1_793_232_000  # 2026-10-29T00:00:00Z
NOW = MIDNIGHT + 3600


def inst(instance_id: int, dph: str, label: str | None = None, **kw: Any) -> Instance:
    return Instance(
        id=instance_id, label=label, actual_status="running", gpu_name="RTX 4090", num_gpus=1,
        gpu_ram_gb=24.0, dph_total=D(dph), public_ipaddr=None, ssh_host=None, ssh_port=None, **kw,
    )


def cached(state: LeaseState, price: str, expires: int | None, **kw: Any) -> CachedLease:
    lab = Label(lease="l-1", owner="o", created=NOW - 600, ttl=1800, expires=expires)
    return CachedLease(lease="l-1", instance_id=1, label=lab, state=state, price_per_hr=D(price), **kw)


def test_day_start() -> None:
    assert day_start(MIDNIGHT) == MIDNIGHT
    assert day_start(MIDNIGHT + 86_399) == MIDNIGHT
    assert day_start(MIDNIGHT - 1) == MIDNIGHT - 86_400


def test_cost_is_decimal() -> None:
    assert cost(D("0.60"), 1800) == D("0.30")
    assert isinstance(cost(D("0.60"), 1), Decimal)


def test_spent_today_adds_estimate_since_coverage() -> None:
    charges = Charges(per_instance={1: D("1.00"), 2: D("0.50"), 3: D("2.00")}, covered_through=NOW - 1800)
    spent = spent_today(charges, [inst(1, "0.40"), inst(2, "0.20")], NOW, MIDNIGHT)
    assert spent == D("3.50") + D("0.20") + D("0.10")


def test_spent_today_clips_coverage_to_today() -> None:
    charges = Charges(per_instance={}, covered_through=MIDNIGHT - 7200)
    assert spent_today(charges, [inst(1, "1.00")], NOW, MIDNIGHT) == D("1.00")


def test_spent_today_coverage_after_now() -> None:
    charges = Charges(per_instance={1: D("0.25")}, covered_through=NOW + 60)
    assert spent_today(charges, [inst(1, "1.00")], NOW, MIDNIGHT) == D("0.25")


def test_spent_today_none_without_coverage() -> None:
    assert spent_today(Charges(per_instance={1: D("1")}, covered_through=None), [], NOW, MIDNIGHT) is None


def test_spent_today_fresh_day_runs_from_start_date() -> None:
    now = MIDNIGHT + 84_600
    charges = Charges(per_instance={}, covered_through=MIDNIGHT)
    spent = spent_today(charges, [inst(1, "0.06", start_date=now - 600)], now, MIDNIGHT)
    assert spent == D("0.01")


def test_spent_today_start_before_coverage_runs_from_coverage() -> None:
    charges = Charges(per_instance={1: D("0.50")}, covered_through=NOW - 1800)
    spent = spent_today(charges, [inst(1, "1.00", start_date=NOW - 3000)], NOW, MIDNIGHT)
    assert spent == D("0.50") + D("0.50")


def test_spent_today_start_after_coverage_runs_from_start() -> None:
    charges = Charges(per_instance={}, covered_through=NOW - 1800)
    spent = spent_today(charges, [inst(1, "1.00", start_date=NOW - 900)], NOW, MIDNIGHT)
    assert spent == D("0.25")


def test_spent_today_start_in_future_costs_nothing() -> None:
    charges = Charges(per_instance={}, covered_through=NOW - 1800)
    assert spent_today(charges, [inst(1, "1.00", start_date=NOW + 600)], NOW, MIDNIGHT) == D("0")


def test_spent_today_falls_back_to_label_created() -> None:
    charges = Charges(per_instance={}, covered_through=MIDNIGHT)
    label = "vasty:v1;lease=l-0000a001;owner=o;created=" + str(NOW - 1800) + ";ttl=3600"
    assert spent_today(charges, [inst(1, "1.00", label=label)], NOW, MIDNIGHT) == D("0.50")


def test_spent_today_start_date_wins_over_label() -> None:
    charges = Charges(per_instance={}, covered_through=MIDNIGHT)
    label = "vasty:v1;lease=l-0000a001;owner=o;created=" + str(NOW - 1800) + ";ttl=3600"
    live = [inst(1, "1.00", label=label, start_date=NOW - 900)]
    assert spent_today(charges, live, NOW, MIDNIGHT) == D("0.25")


@pytest.mark.parametrize("label", [None, "my-box", "vasty:v1;lease=bad", "vasty:v9;lease=l-0000a001"])
def test_spent_today_without_start_runs_from_coverage(label: str | None) -> None:
    charges = Charges(per_instance={}, covered_through=NOW - 1800)
    assert spent_today(charges, [inst(1, "1.00", label=label)], NOW, MIDNIGHT) == D("0.50")


def test_require_spent() -> None:
    assert require_spent(D("1.5")) == D("1.5")
    with pytest.raises(VastyError) as exc:
        require_spent(None)
    assert exc.value.code == "spend_unavailable"
    assert exc.value.exit_code == 2


def test_spend_unavailable_warning() -> None:
    w = spend_unavailable_warning()
    assert (w.code, w.lease, w.fix) == ("spend_unavailable", None, "vasty status")


def test_projection_live_and_expired_floored() -> None:
    commitments = [(D("0.60"), NOW + 1800), (D("1.20"), NOW + 3600), (D("5.00"), NOW - 600)]
    assert projection(D("2.00"), commitments, NOW, D("0")) == D("2.00") + D("0.30") + D("1.20")


def test_projection_adds_new_lease() -> None:
    assert projection(D("1"), [], NOW, cost(D("0.38"), 7200)) == D("1.76")


def test_projection_counts_time_past_midnight() -> None:
    late = MIDNIGHT + 86_400 - 1800
    assert projection(D("0"), [(D("1.00"), late + 7200)], late, D("0")) == D("2.00")


def test_lease_commitments_skip_history_and_orphans() -> None:
    leases = [
        cached("running", "0.60", NOW + 1800),
        cached("pending", "0.40", None),
        cached("unreachable", "0.82", NOW + 60),
        cached("stopped", "0.10", NOW + 60),
        cached("expired", "9.00", NOW - 60),
        cached("released", "9.00", NOW + 600),
        cached("gone", "9.00", NOW + 600),
        cached("orphan", "9.00", NOW + 600),
    ]
    assert lease_commitments(leases) == [
        (D("0.60"), NOW + 1800),
        (D("0.40"), NOW - 600 + 1800),
        (D("0.82"), NOW + 60),
        (D("0.10"), NOW + 60),
    ]


def test_orphans_count_in_spent_today_only() -> None:
    charges = Charges(per_instance={1: D("0.50"), 99: D("0.30")}, covered_through=NOW)
    live = [inst(1, "0.60"), inst(99, "0.22")]
    spent = spent_today(charges, live, NOW, MIDNIGHT)
    assert spent == D("0.80")
    managed = lease_commitments([cached("running", "0.60", NOW + 3600)])
    assert projection(spent, managed, NOW, D("0")) == D("1.40")
    assert burn_per_hr(live) == D("0.82")


def test_extend_delta_replaces_commitment() -> None:
    targets = [(D("1.00"), NOW + 1800, NOW + 5400), (D("0.50"), NOW + 600, NOW + 3600)]
    assert extend_delta(targets, NOW) == D("1.00") + D("0.50") * D(3000) / D(3600)


def test_extend_delta_shortening_is_negative() -> None:
    assert extend_delta([(D("1.00"), NOW + 3600, NOW + 1800)], NOW) == D("-0.50")


def test_extend_delta_from_expired_clock() -> None:
    assert extend_delta([(D("1.00"), NOW - 600, NOW + 1800)], NOW) == D("0.50")


def test_check_passes_under_budget() -> None:
    check(D("9.99"), D("5"), D("10"))
    check(D("10.00"), D("5"), D("10"))


def test_check_passes_when_action_holds_or_lowers() -> None:
    check(D("12"), D("12"), D("10"))
    check(D("11"), D("12"), D("10"))


def test_check_lowering_extend_passes_over_budget() -> None:
    commitments = [(D("2.00"), NOW + 7200)]
    without = projection(D("8"), commitments, NOW, D("0"))
    delta = extend_delta([(D("2.00"), NOW + 7200, NOW + 3600)], NOW)
    check(projection(D("8"), commitments, NOW, delta), without, D("10"))


def test_check_refusal_details() -> None:
    with pytest.raises(VastyError) as exc:
        check(D("10.555"), D("8.004"), D("10"))
    err = exc.value
    assert err.code == "budget_exceeded"
    assert err.exit_code == 3
    assert err.details == {"projected": 10.56, "remaining": 2.0, "daily_budget": 10.0}
    assert "by $0.56" in err.message
    assert json.loads(json.dumps(err.to_dict()))["details"]["remaining"] == 2.0


def test_check_refusal_remaining_can_be_negative() -> None:
    with pytest.raises(VastyError) as exc:
        check(D("13"), D("11"), D("10"))
    assert exc.value.details is not None
    assert exc.value.details["remaining"] == -1.0


def test_check_custom_hint() -> None:
    with pytest.raises(VastyError) as exc:
        check(D("11"), D("1"), D("10"), hint="Try --ttl 15m.")
    assert exc.value.hint == "Try --ttl 15m."


@pytest.mark.parametrize(
    "projected, expected",
    [("8.99", False), ("9.00", True), ("9.50", True), ("12", True)],
)
def test_budget_low_threshold(projected: str, expected: bool) -> None:
    assert budget_low(D(projected), D("10.00")) is expected


def test_budget_low_warning() -> None:
    assert budget_low_warning(D("8.99"), D("10")) is None
    w = budget_low_warning(D("9.2"), D("10"))
    assert w is not None
    assert (w.code, w.lease, w.message, w.fix) == ("budget_low", None, "projected $9.20 of $10.00", "vasty status")


def test_burn_per_hr() -> None:
    assert burn_per_hr([]) == D("0")
    rates = ["2.40", "0.82", "0.82", "0.82", "0.55", "0.38", "0.22"]
    assert burn_per_hr([inst(i, r) for i, r in enumerate(rates)]) == D("6.01")


@pytest.mark.parametrize("fetched, fresh", [(NOW, True), (NOW - 59, True), (NOW - 60, False), (None, False)])
def test_billing_fresh(fetched: int | None, fresh: bool) -> None:
    assert billing_fresh(fetched, NOW) is fresh
