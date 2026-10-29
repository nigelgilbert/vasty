from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any

import pytest

from fakes import NOW, Harness, add_lease, make_offer, timeout_error
from rig.commands import reserve
from rig.errors import RigError
from rig.labels import parse
from rig.models import CreateRequest, Instance, Label
from rig.onstart import decode_onstart

RESULT_KEYS = {
    "lease", "name", "owner", "group", "state", "guard", "guard_missing", "reused", "gpu",
    "gpus", "vram_gb", "price_per_hr", "expires_at", "ttl_remaining_s", "ssh", "rsync_target",
    "ssh_port", "ports", "warnings", "swept",
}
PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample test@host"


def boot(harness: Harness, inst: Instance, request: CreateRequest) -> None:
    """Give the created box a clock file the way onstart does."""
    label = parse(request.label)
    assert isinstance(label, Label)
    harness.box.state(inst.id).clock = int(harness.time.wall_now) + label.ttl


@pytest.fixture
def h(harness: Harness) -> Harness:
    harness.provider.covered_through = NOW
    harness.provider.offers = [make_offer(1)]
    harness.provider.on_create = lambda inst, req: boot(harness, inst, req)
    return harness


def run_json(harness: Harness, *argv: str) -> tuple[int, dict[str, Any]]:
    code, out, err = harness.run(*argv)
    data: dict[str, Any] = json.loads(out)
    return code, data


def add_key(harness: Harness) -> None:
    ssh = harness.home / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text("PRIVATE\n")
    (ssh / "id_ed25519.pub").write_text(PUB + "\n")


def label_of(harness: Harness, instance_id: int) -> Label:
    parsed = parse(harness.provider.instances[instance_id].label)
    assert isinstance(parsed, Label)
    return parsed


def calls(harness: Harness, name: str) -> list[Any]:
    return [arg for call, arg in harness.provider.calls if call == name]


# Happy path and output.


def test_reserve_returns_running_lease(h: Harness) -> None:
    code, data = run_json(h, "reserve", "--name", "trainer", "--group", "exp42")
    assert code == 0, data
    assert set(data) == RESULT_KEYS
    assert data["lease"] == "l-abababab"
    assert (data["name"], data["owner"], data["group"]) == ("trainer", "claude", "exp42")
    assert data["state"] == "running"
    assert data["reused"] is False
    assert (data["guard"], data["guard_missing"]) == ("full", [])
    assert (data["gpu"], data["gpus"], data["vram_gb"], data["price_per_hr"]) == (
        "RTX 4090", 1, 24.0, 0.38)
    assert data["expires_at"] == "2026-10-29T01:30:00Z"
    assert data["ttl_remaining_s"] == 1800
    assert data["ssh"] == "ssh -p 41022 root@198.51.100.7"
    assert data["rsync_target"] == "root@198.51.100.7:"
    assert data["ssh_port"] == 41022
    assert data["ports"] == {"22": 41022, "8000": 41000, "8080": 41080}
    assert data["warnings"] == [] and data["swept"] == []


def test_reserve_writes_create_label_and_copies_clock(h: Harness) -> None:
    run_json(h, "reserve", "--name", "trainer", "--group", "exp42", "--ttl", "1h")
    (request,) = h.provider.created
    created = parse(request.label)
    assert isinstance(created, Label)
    assert (created.lease, created.owner, created.name, created.group) == (
        "l-abababab", "claude", "trainer", "exp42")
    assert (created.created, created.ttl, created.expires) == (NOW, 3600, None)
    assert request.runtype == "ssh_direct"
    assert request.ports == [22, 8000, 8080]
    assert request.image == "rig/base:cuda12.4"
    assert request.disk_gb == 50
    (iid,) = h.provider.instances
    assert label_of(h, iid).expires == NOW + 3600


def test_reserve_owner_flag_sets_owner(h: Harness) -> None:
    _, data = run_json(h, "reserve", "--owner", "agent-7")
    assert data["owner"] == "agent-7"
    assert "owner=agent-7" in h.provider.created[0].label


def test_reserve_human_summary(h: Harness) -> None:
    code, out, _ = h.run("reserve", "--name", "trainer", "--plain")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith("l-abababab  trainer  running  RTX 4090  $0.38/hr")
    assert lines[1] == "ssh -p 41022 root@198.51.100.7"


def test_reserve_redraws_taken_lease_id(h: Harness) -> None:
    add_lease(h, "l-0000a001")
    h.hex_values = ["0000a001", "0000a002"]
    _, data = run_json(h, "reserve")
    assert data["lease"] == "l-0000a002"


# Offers.


def test_offers_sorted_by_reliability_bandwidth_price_id(h: Harness) -> None:
    h.provider.offers = [
        make_offer(5, reliability=0.95, inet_down=900.0),
        make_offer(4, reliability=0.99, inet_down=400.0),
        make_offer(3, reliability=0.99, inet_down=500.0, dph_total=Decimal("0.40")),
        make_offer(2, reliability=0.99, inet_down=500.0, dph_total=Decimal("0.30")),
        make_offer(1, reliability=0.99, inet_down=500.0, dph_total=Decimal("0.30")),
    ]
    run_json(h, "reserve")
    assert h.provider.created[0].offer_id == 1
    ranked = reserve.rank_offers(
        h.provider.offers,
        reserve.OfferQuery(gpu=None, vram_min_gb=None, gpus=1, disk_gb=50,
                           max_price=Decimal("1"), region=None),
    )
    assert [o.id for o in ranked] == [1, 2, 3, 4, 5]


def test_offers_filtered_by_gpu_vram_and_count(h: Harness) -> None:
    h.provider.offers = [
        make_offer(1, gpu_name="RTX 3090", reliability=1.0),
        make_offer(2, gpu_name="RTX 4090", gpu_ram_gb=16.0, reliability=1.0),
        make_offer(3, gpu_name="RTX 4090", num_gpus=2, reliability=1.0),
        make_offer(4, gpu_name="RTX 4090", reliability=0.5),
    ]
    run_json(h, "reserve", "--gpu", "4090", "--vram", "24")
    assert h.provider.created[0].offer_id == 4
    query = calls(h, "search_offers")[0]
    assert (query.gpu, query.vram_min_gb, query.gpus, query.disk_gb) == ("4090", 24.0, 1, 50)


def test_no_offers_names_constraints_and_hint(h: Harness) -> None:
    code, data = run_json(h, "reserve", "--gpu", "4090", "--max-price", "0.30")
    assert code == 1
    assert data["error"] == "no_offers"
    assert data["message"] == "No offers match gpu=4090 under $0.30/hr."
    assert "--max-price 0.45" in data["hint"]
    assert calls(h, "create") == []


def test_proxy_runtype_without_direct_ports(h: Harness) -> None:
    h.provider.offers = [make_offer(1, direct_port_count=0)]
    _, data = run_json(h, "reserve")
    assert h.provider.created[0].runtype == "ssh_proxy"
    assert data["state"] == "running"


# Ports.


def test_ports_dedupe_with_defaults(h: Harness) -> None:
    _, data = run_json(h, "reserve", "--ports", "8000,9000,9000,22")
    assert h.provider.created[0].ports == [22, 8000, 8080, 9000]
    assert data["ports"]["9000"] == 41000


@pytest.mark.parametrize("ports", ["0", "65536", "abc", "80,x"])
def test_invalid_port_list(h: Harness, ports: str) -> None:
    code, data = run_json(h, "reserve", "--ports", ports)
    assert code == 1
    assert data["error"] == "invalid_arguments"
    assert calls(h, "create") == []


def test_port_limit_counts_after_dedupe(h: Harness) -> None:
    fits = ",".join(str(p) for p in range(9000, 9061)) + ",22,8000"
    code, _ = run_json(h, "reserve", "--ports", fits)
    assert code == 0
    assert len(h.provider.created[0].ports) == 64
    over = ",".join(str(p) for p in range(9000, 9062))
    code, data = run_json(h, "reserve", "--ports", over)
    assert code == 1
    assert data["error"] == "invalid_arguments"


def test_port_mapping_missing_destroys_box(h: Harness) -> None:
    def drop_port(inst: Instance, req: CreateRequest) -> None:
        boot(h, inst, req)
        del inst.ports[8080]

    h.provider.on_create = drop_port
    code, data = run_json(h, "reserve")
    assert code == 2
    assert data["error"] == "port_mapping_missing"
    assert data["details"] == {"ports": [8080]}
    assert len(h.provider.destroyed) == 1
    assert h.time.wall_now >= NOW + reserve.PORT_GRACE_S


# Startup and onstart.


def test_startup_too_large_before_create(h: Harness) -> None:
    script = h.home / "big.sh"
    script.write_text("echo " + os.urandom(6000).hex() + "\n")
    code, data = run_json(h, "reserve", "--startup", str(script))
    assert code == 1
    assert data["error"] == "startup_too_large"
    assert calls(h, "create") == []
    assert calls(h, "search_offers") == []


def test_custom_image_onstart_carries_watchdog(h: Harness) -> None:
    run_json(h, "reserve", "--image", "ubuntu:22.04")
    request = h.provider.created[0]
    assert request.image == "ubuntu:22.04"
    assert "watchdog.sh" in decode_onstart(request.onstart)
    assert request.onstart.startswith("command -v bash")


def test_default_image_onstart_has_startup_script(h: Harness) -> None:
    script = h.home / "setup.sh"
    script.write_text("pip install -U peft\n")
    run_json(h, "reserve", "--startup", str(script))
    request = h.provider.created[0]
    assert not request.onstart.startswith("command -v bash")
    assert "pip install -U peft" in decode_onstart(request.onstart)


def test_startup_failure_ends_wait_with_warning(h: Harness) -> None:
    def failing(inst: Instance, req: CreateRequest) -> None:
        boot(h, inst, req)
        h.box.state(inst.id).startup_exit = 3

    h.provider.on_create = failing
    code, data = run_json(h, "reserve")
    assert code == 0
    assert data["state"] == "running"
    assert [w["code"] for w in data["warnings"]] == ["startup_failed"]
    assert data["warnings"][0]["fix"] == f"rig ssh {data['lease']} -- cat /workspace/.rig/startup.log"
    assert h.provider.destroyed == []


def test_wait_polls_until_startup_finishes(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(inst: Instance, req: CreateRequest) -> None:
        boot(h, inst, req)
        h.box.state(inst.id).startup_exit = None

    h.provider.on_create = slow
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        h.time.advance(seconds)
        if len(sleeps) == 3:
            for box in h.box.boxes.values():
                box.startup_exit = 0

    monkeypatch.setattr(h.time, "sleep", sleep)
    code, data = run_json(h, "reserve")
    assert code == 0
    assert data["state"] == "running"
    assert sleeps == [reserve.WAIT_POLL_S] * 3


def test_image_unsupported_destroys_box(h: Harness) -> None:
    def lacking(inst: Instance, req: CreateRequest) -> None:
        boot(h, inst, req)
        h.box.state(inst.id).unsupported = ["apt-get"]

    h.provider.on_create = lacking
    code, data = run_json(h, "reserve", "--image", "alpine:3")
    assert code == 1
    assert data["error"] == "image_unsupported"
    assert "apt-get" in data["message"]
    assert len(h.provider.destroyed) == 1


# Waiting.


def test_no_wait_returns_pending_with_nulls(h: Harness) -> None:
    code, data = run_json(h, "reserve", "--no-wait")
    assert code == 0
    assert data["state"] == "pending"
    for key in ("expires_at", "ttl_remaining_s", "ssh", "ssh_port", "rsync_target", "ports"):
        assert data[key] is None, key
    (iid,) = h.provider.instances
    assert label_of(h, iid).expires is None


def test_wait_timeout_destroys_box(h: Harness) -> None:
    h.provider.on_create = None
    code, data = run_json(h, "reserve", "--ttl", "5m")
    assert code == 2
    assert data["error"] == "box_unreachable"
    assert len(h.provider.destroyed) == 1
    assert h.provider.instances == {}
    assert NOW + 300 <= h.time.wall_now < NOW + 300 + reserve.WAIT_POLL_S + 1
    lease = h.context().cache.load().leases["l-abababab"]
    assert lease.released_here


def test_wait_ends_with_box_unreachable_when_loading_never_ends(h: Harness) -> None:
    h.provider.start_status = "loading"
    code, data = run_json(h, "reserve", "--ttl", "2m")
    assert code == 2
    assert data["error"] == "box_unreachable"
    assert len(h.provider.destroyed) == 1


def cached_lease(h: Harness) -> Any:
    return h.context().cache.load().leases["l-abababab"]


def unsupported_image(h: Harness) -> None:
    def lacking(inst: Instance, req: CreateRequest) -> None:
        boot(h, inst, req)
        h.box.state(inst.id).unsupported = ["apt-get"]

    h.provider.on_create = lacking


def test_give_up_keeps_lease_active_when_destroy_skipped(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsupported_image(h)
    monkeypatch.setattr("rig.engine.destroy_checked", lambda ctx, iid, expires: False)
    code, out, err = h.run("reserve", "--image", "alpine:3")
    assert code == 1
    assert json.loads(out)["error"] == "image_unsupported"
    assert "rig: l-abababab changed before it could be destroyed. Run rig release l-abababab." in err
    (iid,) = h.provider.instances
    lease = cached_lease(h)
    assert (lease.state, lease.released_here, lease.destroy_pending) == ("running", False, False)
    monkeypatch.undo()
    code, data = run_json(h, "release", "l-abababab")
    assert code == 0, data
    assert h.provider.destroyed == [iid]


def test_give_up_marks_released_when_row_already_gone(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsupported_image(h)

    def vanish(ctx: Any, iid: int, expires: int | None) -> bool:
        del h.provider.instances[iid]
        return False

    monkeypatch.setattr("rig.engine.destroy_checked", vanish)
    code, out, err = h.run("reserve", "--image", "alpine:3")
    assert code == 1
    assert "changed before" not in err
    lease = cached_lease(h)
    assert (lease.state, lease.released_here, lease.destroy_pending) == ("released", True, True)


def test_give_up_failed_destroy_names_release_fix(h: Harness) -> None:
    unsupported_image(h)
    h.provider.fail["destroy"] = RigError("provider_error", "boom.", "retry")
    code, out, err = h.run("reserve", "--image", "alpine:3")
    assert code == 1
    assert json.loads(out)["error"] == "image_unsupported"
    assert "rig: could not destroy l-abababab: boom. Run rig release l-abababab." in err
    lease = cached_lease(h)
    assert (lease.released_here, lease.destroy_pending) == (False, False)


def test_ctrl_c_during_wait_destroys_box(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    h.provider.start_status = "loading"

    def interrupt(seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(h.time, "sleep", interrupt)
    with pytest.raises(KeyboardInterrupt):
        h.run("reserve")
    assert h.provider.destroyed == [1001]
    assert h.provider.instances == {}
    lease = cached_lease(h)
    assert (lease.state, lease.released_here, lease.destroy_pending) == ("released", True, True)


def test_refresh_error_during_wait_destroys_box(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.provider.start_status = "loading"
    real_sleep = h.time.sleep

    def sleep(seconds: float) -> None:
        h.provider.fail["list_instances"] = RigError("provider_error", "list failed", "retry")
        real_sleep(seconds)

    monkeypatch.setattr(h.time, "sleep", sleep)
    code, data = run_json(h, "reserve")
    assert code == 2
    assert (data["error"], data["message"]) == ("provider_error", "list failed")
    assert h.provider.destroyed == [1001]
    assert calls(h, "destroy") == [1001]


# Name idempotency.


def test_name_hit_returns_existing_lease(h: Harness) -> None:
    row = add_lease(h, "l-0000a001", label={"name": "ft", "expires": NOW + 1200},
                    gpu_name="RTX 4090", dph_total=Decimal("0.38"))
    h.run("status")
    h.provider.calls.clear()
    code, data = run_json(h, "reserve", "--name", "ft")
    assert code == 0
    assert data["lease"] == "l-0000a001"
    assert data["reused"] is True
    assert data["warnings"] == []
    assert data["ssh"] == "ssh -p 40022 root@198.51.100.9"
    assert calls(h, "search_offers") == []
    assert calls(h, "charges") == []
    assert calls(h, "create") == []
    assert row.id in h.provider.instances


def test_name_hit_warns_on_flag_mismatch(h: Harness) -> None:
    add_lease(h, "l-0000a001", label={"name": "ft", "group": "a", "expires": NOW + 1200},
              gpu_name="RTX 3090", gpu_ram_gb=24.0)
    h.env["RIG_DAILY_BUDGET"] = "0.01"
    code, data = run_json(h, "reserve", "--name", "ft", "--gpu", "4090", "--vram", "48",
                          "--group", "b", "--ttl", "2h")
    assert code == 0
    assert data["reused"] is True
    (warning,) = data["warnings"]
    assert warning["code"] == "flag_mismatch"
    assert warning["lease"] == "l-0000a001"
    for flag in ("--gpu", "--vram", "--group", "--ttl"):
        assert flag in warning["message"]
    assert calls(h, "create") == []


def test_name_scoped_to_owner(h: Harness) -> None:
    add_lease(h, "l-0000a001", label={"name": "ft", "owner": "nick"})
    _, data = run_json(h, "reserve", "--name", "ft")
    assert data["reused"] is False
    assert data["lease"] != "l-0000a001"
    assert len(h.provider.created) == 1


def test_name_in_history_creates_new_lease(h: Harness) -> None:
    add_lease(h, "l-0000a001", label={"name": "ft", "expires": NOW - 5})
    _, data = run_json(h, "reserve", "--name", "ft")
    assert data["reused"] is False
    assert len(h.provider.created) == 1


def test_invalid_name(h: Harness) -> None:
    code, data = run_json(h, "reserve", "--name", "l-abc")
    assert code == 1
    assert data["error"] == "invalid_arguments"


@pytest.mark.parametrize("ttl", ["1h1h", "30m1h", "1h0m"])
def test_ttl_uses_extend_duration_grammar(h: Harness, ttl: str) -> None:
    code, data = run_json(h, "reserve", "--ttl", ttl)
    assert (code, data["error"]) == (1, "invalid_arguments")
    assert calls(h, "create") == []


def test_ttl_accepts_chained_units(h: Harness) -> None:
    code, data = run_json(h, "reserve", "--ttl", "1h30m")
    assert code == 0, data
    (request,) = h.provider.created
    created = parse(request.label)
    assert isinstance(created, Label)
    assert created.ttl == 5400


# Budget.


def test_budget_refusal_details_and_exit(h: Harness) -> None:
    h.env["RIG_DAILY_BUDGET"] = "1.00"
    h.provider.billed = {9: Decimal("0.20")}
    code, data = run_json(h, "reserve", "--ttl", "3h")
    assert code == 3
    assert data["error"] == "budget_exceeded"
    assert data["details"] == {"projected": 1.34, "remaining": 0.8, "daily_budget": 1.0}
    assert "by $0.34" in data["message"]
    assert calls(h, "create") == []


def test_budget_low_warning_near_cap(h: Harness) -> None:
    h.env["RIG_DAILY_BUDGET"] = "0.40"
    _, data = run_json(h, "reserve", "--ttl", "1h")
    assert [w["code"] for w in data["warnings"]] == ["budget_low"]


def test_spend_unavailable_refuses(h: Harness) -> None:
    h.provider.covered_through = None
    code, data = run_json(h, "reserve")
    assert code == 2
    assert data["error"] == "spend_unavailable"
    assert calls(h, "create") == []


# SSH key.


def test_registers_public_key_before_create(h: Harness) -> None:
    add_key(h)
    run_json(h, "reserve")
    names = [call for call, _ in h.provider.calls]
    assert names.index("attach_ssh_key") < names.index("create")
    assert h.provider.attached == [(PUB, None)]


def test_skips_registration_when_key_exists(h: Harness) -> None:
    from rig.models import SshKey

    add_key(h)
    h.provider.ssh_keys = [SshKey(id=1, public_key=PUB.rsplit(" ", 1)[0] + " other@host")]
    run_json(h, "reserve")
    assert h.provider.attached == []


def test_reserve_without_public_key_skips_registration(h: Harness) -> None:
    code, out, err = h.run("reserve")
    assert code == 0, out
    assert err.count("skipping key registration") == 1
    assert calls(h, "list_ssh_keys") == []
    assert calls(h, "attach_ssh_key") == []


# Create recovery.


def _timing_out_create(h: Harness, copies: int) -> list[CreateRequest]:
    sent: list[CreateRequest] = []

    def create(request: CreateRequest) -> int:
        sent.append(request)
        h.provider.calls.append(("create", request))
        for _ in range(copies):
            inst = h.provider.add_instance(label=request.label, public_ipaddr="198.51.100.7",
                                           ports={p: 41000 + p % 1000 for p in request.ports})
            boot(h, inst, request)
        raise timeout_error()

    h.provider.create = create  # type: ignore[method-assign]
    return sent


def test_create_timeout_one_match_is_the_lease(h: Harness) -> None:
    sent = _timing_out_create(h, 1)
    code, data = run_json(h, "reserve")
    assert code == 0, data
    assert len(sent) == 1
    assert data["lease"] == "l-abababab"
    assert data["state"] == "running"
    assert h.provider.destroyed == []


def test_create_timeout_two_matches_keep_lowest(h: Harness) -> None:
    sent = _timing_out_create(h, 2)
    code, data = run_json(h, "reserve")
    assert code == 0, data
    assert len(sent) == 1
    (kept,) = h.provider.instances
    assert h.provider.destroyed == [kept + 1]
    assert data["lease"] == "l-abababab"


def test_create_timeout_no_match_returns_provider_error(h: Harness) -> None:
    sent = _timing_out_create(h, 0)
    start = h.time.wall_now
    code, data = run_json(h, "reserve")
    assert code == 2
    assert data["error"] == "provider_error"
    assert "l-abababab" in data["hint"]
    assert len(sent) == 1
    assert len(calls(h, "create")) == 1
    assert h.time.wall_now - start == reserve.RECOVER_WINDOW_S
    lists = calls(h, "list_instances")
    assert len(lists) == 1 + reserve.RECOVER_WINDOW_S // int(reserve.RECOVER_POLL_S) + 1


def test_create_error_other_than_timeout_is_not_retried(h: Harness) -> None:
    h.provider.fail["create"] = RigError("provider_error", "no", "Run rig status.")
    code, data = run_json(h, "reserve")
    assert code == 2
    assert data["error"] == "provider_error"
    assert len(calls(h, "create")) == 1


# reserve_lease for run and serve.


def test_reserve_lease_accepts_sparse_args(h: Harness) -> None:
    import argparse

    from rig import engine

    ctx = h.context()
    snap = engine.refresh(ctx)
    reserved = reserve.reserve_lease(ctx, argparse.Namespace(), snap, ttl=7200, wait=True)
    assert reserved.result.state == "running"
    assert reserved.lease.label.ttl == 7200
    assert reserved.result.ttl_remaining_s == 7200
