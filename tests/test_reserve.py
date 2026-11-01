from __future__ import annotations

import io
import json
import os
import sys
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from fakes import NOW, Harness, add_lease, make_offer, rejected_error, timeout_error

from vasty import engine
from vasty.commands import reserve
from vasty.config import user_config_path
from vasty.context import Context
from vasty.errors import VastyError
from vasty.labels import format_label, parse
from vasty.models import CreateRequest, Instance, Label
from vasty.onstart import decode_onstart
from vasty.provider import build_offer_query

RESULT_KEYS = {
    "lease", "name", "owner", "group", "state", "reused", "gpu",
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
    harness.provider.offers = [make_offer(1)]
    harness.provider.on_create = lambda inst, req: boot(harness, inst, req)
    return harness


def run_json(harness: Harness, *argv: str) -> tuple[int, dict[str, Any]]:
    code, out, _err = harness.run(*argv)
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
    assert (data["gpu"], data["gpus"], data["vram_gb"], data["price_per_hr"]) == (
        "RTX 4090", 1, 24.0, 0.38)
    assert data["expires_at"] == "2026-10-29T01:30:00Z"
    assert data["ttl_remaining_s"] == 1800
    assert data["ssh"] == "ssh -p 41022 root@198.51.100.7"
    assert data["rsync_target"] == "root@198.51.100.7:"
    assert data["ssh_port"] == 41022
    assert data["ports"] == {"22": 41022, "8000": 41000, "8080": 41080}
    assert data["warnings"] == [] and data["swept"] == []


def test_reserve_spawns_a_follower(h: Harness) -> None:
    code, data = run_json(h, "reserve")
    assert code == 0, data
    assert h.spawned == [[sys.executable, "-m", "vasty", "sweep", "--follow", "l-abababab"]]


def test_reserve_then_extend_spawns_one_follower(h: Harness) -> None:
    assert run_json(h, "reserve")[0] == 0
    code, data = run_json(h, "extend", "l-abababab", "--by", "30m")
    assert code == 0, data
    assert len(h.spawned) == 1
    assert h.context().cache.load().leases["l-abababab"].follower_pid == 4001


def test_reserve_with_a_failed_spawn_warns_and_succeeds(h: Harness) -> None:
    h.spawn_error = OSError("no fork")
    code, data = run_json(h, "reserve")
    assert code == 0, data
    assert [(w["code"], w["lease"], w["fix"]) for w in data["warnings"]] == [
        ("sweep_not_spawned", "l-abababab", "vasty sweep --follow l-abababab"),
    ]


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
    assert request.image == "vastai/base-image:cuda-12.6.3-auto"
    assert request.disk_gb == 50
    (iid,) = h.provider.instances
    assert label_of(h, iid).expires == NOW + 3600


def test_reserve_owner_flag_sets_owner(h: Harness) -> None:
    _, data = run_json(h, "reserve", "--owner", "agent-7")
    assert data["owner"] == "agent-7"
    assert "owner=agent-7" in h.provider.created[0].label


def test_reserve_human_summary(h: Harness) -> None:
    code, out, _ = h.run("reserve", "--name", "trainer", tty=True)
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
                           max_price=Decimal(1), region=None),
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


@pytest.mark.parametrize("value", ["any", ""])
def test_gpu_any_clears_a_configured_pin(h: Harness, value: str) -> None:
    write_user(h, '[defaults]\ngpu = "A100"\nregion = "US"\n')
    code, data = run_json(h, "reserve", "--gpu", value, "--region", value)
    assert code == 0, data
    query = calls(h, "search_offers")[0]
    assert (query.gpu, query.region) == (None, None)


def test_no_offers_names_constraints_and_hint(h: Harness) -> None:
    code, data = run_json(h, "reserve", "--gpu", "4090", "--max-price", "0.30")
    assert code == 1
    assert data["error"] == "no_offers"
    assert data["message"] == "No offers match gpu=4090 disk>=50GB cuda>=12.6 under $0.30/hr."
    assert data["hint"] == "Try a higher --max-price, another --gpu, a lower --disk, or a lower --cuda."
    assert calls(h, "create") == []


def write_user(harness: Harness, text: str) -> None:
    path = user_config_path(harness.home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def cuda_filter(harness: Harness) -> Any:
    query = calls(harness, "search_offers")[0]
    return build_offer_query(query).get("cuda_max_good")


def test_cuda_flag_sends_filter(h: Harness) -> None:
    code, _ = run_json(h, "reserve", "--image", "vllm/vllm-openai:v0.32.0", "--cuda", "13")
    assert code == 0
    assert cuda_filter(h) == {"gte": 13.0}


def test_cuda_profile_sends_filter(h: Harness) -> None:
    write_user(h, '[profiles.vllm]\nimage = "vllm/vllm-openai:v0.32.0"\nvram = 24\ncuda = 13\n')
    h.provider.offers = [make_offer(1, gpu_ram_gb=24.0)]
    code, _ = run_json(h, "reserve", "--profile", "vllm")
    assert code == 0
    assert cuda_filter(h) == {"gte": 13.0}


def test_cuda_env_sends_filter(h: Harness) -> None:
    h.env["VASTY_CUDA"] = "13"
    code, _ = run_json(h, "reserve")
    assert code == 0
    assert cuda_filter(h) == {"gte": 13.0}


def test_vllm_image_without_cuda_filters_at_13(h: Harness) -> None:
    code, _ = run_json(h, "reserve", "--image", "vllm/vllm-openai:v0.32.0")
    assert code == 0
    assert cuda_filter(h) == {"gte": 13.0}


def test_base_image_without_cuda_filters_at_12_6(h: Harness) -> None:
    code, _ = run_json(h, "reserve")
    assert code == 0
    assert calls(h, "search_offers")[0].cuda == 12.6
    assert cuda_filter(h) == {"gte": 12.6}


def test_cuda_flag_overrides_image_floor(h: Harness) -> None:
    code, _ = run_json(h, "reserve", "--image", "vllm/vllm-openai:v0.32.0", "--cuda", "12.4")
    assert code == 0
    assert cuda_filter(h) == {"gte": 12.4}


def test_cuda_profile_overrides_image_floor(h: Harness) -> None:
    write_user(h, '[profiles.old]\nimage = "vllm/vllm-openai:v0.32.0"\ncuda = 12.4\n')
    code, _ = run_json(h, "reserve", "--profile", "old")
    assert code == 0
    assert cuda_filter(h) == {"gte": 12.4}


def test_cuda_config_overrides_image_floor(h: Harness) -> None:
    write_user(h, "[defaults]\ncuda = 12.4\n")
    code, _ = run_json(h, "reserve", "--image", "vllm/vllm-openai:v0.32.0")
    assert code == 0
    assert cuda_filter(h) == {"gte": 12.4}


def test_custom_image_without_cuda_sends_no_filter(h: Harness) -> None:
    code, _ = run_json(h, "reserve", "--image", "ubuntu:24.04")
    assert code == 0
    assert "cuda_max_good" not in build_offer_query(calls(h, "search_offers")[0])


def test_no_offers_names_disk(h: Harness) -> None:
    h.provider.offers = []
    code, data = run_json(h, "reserve", "--disk", "200")
    assert code == 1
    assert "disk>=200GB" in data["message"]
    assert "a lower --disk" in data["hint"]


def test_no_offers_names_cuda(h: Harness) -> None:
    h.provider.offers = []
    code, data = run_json(h, "reserve", "--cuda", "13")
    assert code == 1
    assert data["error"] == "no_offers"
    assert "cuda>=13" in data["message"]
    assert "--cuda" in data["hint"]


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
    assert data["details"] == {"ports": [8080], "lease": "l-abababab", "destroyed": True}
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


def test_onstart_carries_watchdog_for_any_image(h: Harness) -> None:
    run_json(h, "reserve", "--image", "ubuntu:22.04")
    request = h.provider.created[0]
    assert request.image == "ubuntu:22.04"
    assert "watchdog.sh" in decode_onstart(request.onstart)
    assert request.onstart.startswith("command -v bash")


def test_onstart_has_startup_script(h: Harness) -> None:
    script = h.home / "setup.sh"
    script.write_text("pip install -U peft\n")
    run_json(h, "reserve", "--startup", str(script))
    request = h.provider.created[0]
    assert "pip install -U peft" in decode_onstart(request.onstart)


def test_onstart_has_startup_script_from_stdin(h: Harness) -> None:
    code, out, _ = h.run("reserve", "--startup", "-", stdin="echo from stdin\n")
    assert code == 0, out
    assert "echo from stdin" in decode_onstart(h.provider.created[0].onstart)


def test_startup_key_in_config_is_script_text(h: Harness) -> None:
    write_user(h, '[defaults]\nstartup = "echo from config"\n')
    run_json(h, "reserve")
    assert "echo from config" in decode_onstart(h.provider.created[0].onstart)


def test_startup_failure_ends_wait_with_warning(h: Harness) -> None:
    def failing(inst: Instance, req: CreateRequest) -> None:
        boot(h, inst, req)
        h.box.state(inst.id).startup_exit = 3

    h.provider.on_create = failing
    code, data = run_json(h, "reserve")
    assert code == 0
    assert data["state"] == "running"
    assert [w["code"] for w in data["warnings"]] == ["startup_failed"]
    assert data["warnings"][0]["fix"] == f"vasty ssh {data['lease']} -- cat /workspace/.vasty/startup.log"
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


def _past_clock_lease(h: Harness) -> None:
    add_lease(h, label={"name": "old", "expires": NOW - 10})


def _released_lease_with_time_left(h: Harness) -> None:
    add_lease(h, label={"name": "old", "expires": NOW + 3000})
    ctx = h.context()
    engine.refresh(ctx)
    cache = ctx.cache.load()
    lease = cache.leases["l-0000a001"]
    lease.state, lease.released_here, lease.destroy_pending = "released", True, True
    lease.destroy_attempts, lease.destroy_at = 1, NOW - 60
    ctx.cache.save(cache)


@pytest.mark.parametrize("setup", [_past_clock_lease, _released_lease_with_time_left])
def test_wait_lists_failed_destroy_retry_once(
    h: Harness, monkeypatch: pytest.MonkeyPatch, setup: Any
) -> None:
    setup(h)
    h.provider.fail["destroy"] = [VastyError("provider_error", "boom", "retry")] * 50

    def slow(inst: Instance, req: CreateRequest) -> None:
        boot(h, inst, req)
        h.box.state(inst.id).startup_exit = None

    h.provider.on_create = slow
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        h.time.advance(seconds)
        if len(sleeps) == 6:
            for box in h.box.boxes.values():
                box.startup_exit = 0

    monkeypatch.setattr(h.time, "sleep", sleep)
    waited: list[list[Any]] = []
    real_wait = reserve.wait_ready

    def wait_ready(*args: Any) -> Any:
        out = real_wait(*args)
        waited.append(out[1])
        return out

    monkeypatch.setattr(reserve, "wait_ready", wait_ready)
    code, data = run_json(h, "reserve")
    assert code == 0, data
    assert len(sleeps) == 6
    assert [(e.lease, e.ok, e.error) for e in waited[0]] == [("l-0000a001", False, "provider_error")]
    entries = [(s["lease"], s["ok"], s["error"]) for s in data["swept"]]
    assert entries == [("l-0000a001", False, "provider_error")]


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


def test_wait_gives_up_on_a_created_box_with_no_ssh(h: Harness) -> None:
    h.provider.on_create = None
    code, data = run_json(h, "reserve", "--ttl", "30m")
    assert code == 2
    assert data["error"] == "box_unreachable"
    assert data["message"] == (
        "Lease l-abababab answered no SSH for 5m after Vast reported it running."
    )
    assert data["hint"] == "Run vasty reserve again."
    assert data["details"] == {"lease": "l-abababab", "destroyed": True}
    assert h.provider.instances == {}
    assert NOW + 300 <= h.time.wall_now < NOW + 300 + reserve.WAIT_POLL_S + 1


def test_wait_gives_up_on_a_reused_box_with_no_ssh_and_keeps_it(h: Harness) -> None:
    row = add_lease(h, label={"name": "ft", "expires": NOW + 1800}, reachable=False)
    code, data = run_json(h, "reserve", "--name", "ft")
    assert code == 2
    assert data["error"] == "box_unreachable"
    assert data["details"] == {"lease": "l-0000a001", "destroyed": False}
    assert h.provider.destroyed == []
    assert row.id in h.provider.instances


def test_wait_passes_a_box_that_answers_ssh_at_4_minutes(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_sleep = h.time.sleep
    states: dict[int, CreateRequest] = {}

    def late_boot(inst: Instance, req: CreateRequest) -> None:
        states[inst.id] = req

    def sleep(seconds: float) -> None:
        real_sleep(seconds)
        if h.time.wall_now >= NOW + 240:
            for iid, req in states.items():
                if h.box.boxes.get(iid) is None:
                    boot(h, h.provider.instances[iid], req)

    h.provider.on_create = late_boot
    monkeypatch.setattr(h.time, "sleep", sleep)
    code, data = run_json(h, "reserve", "--ttl", "30m")
    assert code == 0
    assert data["state"] == "running"
    assert h.provider.destroyed == []


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
    monkeypatch.setattr("vasty.engine.destroy_checked", lambda ctx, iid, expires: False)
    code, out, err = h.run("reserve", "--image", "alpine:3")
    assert code == 1
    assert json.loads(out)["error"] == "image_unsupported"
    assert "vasty: l-abababab changed before it could be destroyed. Run vasty release l-abababab." in err
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

    monkeypatch.setattr("vasty.engine.destroy_checked", vanish)
    code, _out, err = h.run("reserve", "--image", "alpine:3")
    assert code == 1
    assert "changed before" not in err
    lease = cached_lease(h)
    assert (lease.state, lease.released_here, lease.destroy_pending) == ("released", True, True)


def test_give_up_failed_destroy_names_release_fix(h: Harness) -> None:
    unsupported_image(h)
    h.provider.fail["destroy"] = VastyError("provider_error", "boom.", "retry")
    code, out, err = h.run("reserve", "--image", "alpine:3")
    assert code == 1
    assert json.loads(out)["error"] == "image_unsupported"
    assert "vasty: could not destroy l-abababab: boom. Run vasty release l-abababab." in err
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


def interrupt_after_probe(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """Raise Ctrl-C inside the first refresh that probes, after the probe writes the label."""
    real_probe_all = engine._probe_all

    def probe_all(ctx: Any, leases: list[Any], *args: Any) -> None:
        real_probe_all(ctx, leases, *args)
        if leases:
            raise KeyboardInterrupt

    monkeypatch.setattr("vasty.engine._probe_all", probe_all)


def test_ctrl_c_after_probe_writes_expires_destroys_box(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    interrupt_after_probe(h, monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        h.run("reserve")
    assert h.provider.destroyed == [1001]
    assert h.provider.instances == {}
    lease = cached_lease(h)
    assert (lease.state, lease.released_here, lease.destroy_pending) == ("released", True, True)


def test_give_up_skips_destroy_when_expires_moves_after_row_read(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    interrupt_after_probe(h, monkeypatch)
    real_row_expires = reserve._row_expires

    def row_expires(ctx: Any, iid: int) -> int | None:
        value = real_row_expires(ctx, iid)
        assert value is not None
        moved = replace(label_of(h, iid), expires=value + 600)
        h.provider.instances[iid].label = format_label(moved)
        return value

    monkeypatch.setattr(reserve, "_row_expires", row_expires)
    contexts: list[Context] = []
    real_context = h.context

    def context(stdin: str = "", tty: bool = False) -> Context:
        contexts.append(real_context(stdin, tty))
        return contexts[-1]

    monkeypatch.setattr(h, "context", context)
    with pytest.raises(KeyboardInterrupt):
        h.run("reserve")
    monkeypatch.setattr(h, "context", real_context)
    assert h.provider.destroyed == []
    assert list(h.provider.instances) == [1001]
    err = contexts[0].stderr
    assert isinstance(err, io.StringIO)
    assert "vasty: l-abababab changed before it could be destroyed. Run vasty release l-abababab." in (
        err.getvalue())
    lease = cached_lease(h)
    assert (lease.released_here, lease.destroy_pending) == (False, False)


def test_give_up_keeps_stored_expires_when_row_differs(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsupported_image(h)
    real_refresh = engine.refresh

    def refresh(ctx: Any, probe: bool = True) -> Any:
        snap = real_refresh(ctx, probe)
        for iid in h.provider.instances:
            label = label_of(h, iid)
            if label.expires is not None:
                h.provider.instances[iid].label = format_label(replace(label, expires=label.expires + 600))
        return snap

    def no_row_read(ctx: Any, iid: int) -> int | None:
        raise AssertionError("stored expires is set")

    monkeypatch.setattr("vasty.engine.refresh", refresh)
    monkeypatch.setattr(reserve, "_row_expires", no_row_read)
    code, out, err = h.run("reserve", "--image", "alpine:3")
    assert code == 1
    assert json.loads(out)["error"] == "image_unsupported"
    assert "vasty: l-abababab changed before it could be destroyed. Run vasty release l-abababab." in err
    assert h.provider.destroyed == []


def fail_list_on_sleep(h: Harness, monkeypatch: pytest.MonkeyPatch, times: int) -> None:
    """Fail the list call after each of the first `times` sleeps, then let the box run."""
    real_sleep = h.time.sleep
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) <= times:
            h.provider.fail["list_instances"] = VastyError("provider_error", "list failed", "retry")
        else:
            for inst in h.provider.instances.values():
                inst.actual_status = "running"
        real_sleep(seconds)

    monkeypatch.setattr(h.time, "sleep", sleep)


def test_refresh_error_during_wait_warns_and_keeps_waiting(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.provider.start_status = "loading"
    fail_list_on_sleep(h, monkeypatch, 1)
    code, out, err = h.run("reserve")
    data = json.loads(out)
    assert code == 0, data
    assert data["state"] == "running"
    assert err.count("vasty: refresh failed while waiting for l-abababab: list failed") == 1
    assert h.provider.destroyed == []


def test_refresh_errors_for_the_whole_clock_end_with_box_unreachable(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.provider.start_status = "loading"
    fail_list_on_sleep(h, monkeypatch, 10_000)
    code, out, err = h.run("reserve", "--ttl", "5m")
    data = json.loads(out)
    assert code == 2
    assert data["error"] == "box_unreachable"
    assert "l-abababab" in data["message"]
    assert data["details"] == {"lease": "l-abababab", "destroyed": True}
    assert h.provider.destroyed == [1001]
    assert NOW + 300 <= h.time.wall_now < NOW + 300 + reserve.WAIT_POLL_S + 1
    assert err.count("vasty: refresh failed while waiting for l-abababab") == 30


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


def test_name_hit_warns_on_cuda_below_flag(h: Harness) -> None:
    add_lease(h, label={"name": "ft"}, cuda_max_good=12.4)
    _, data = run_json(h, "reserve", "--name", "ft", "--cuda", "13")
    (warning,) = data["warnings"]
    assert warning["message"] == "lease l-0000a001 differs from --cuda"


def idle(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [w for w in data["warnings"] if w["code"] == "idle_box_available"]


def test_reserve_warns_idle_box_available(h: Harness) -> None:
    add_lease(h, label={"name": "ft"}, gpu_name="RTX 3060", gpu_ram_gb=12.0)
    code, data = run_json(h, "reserve")
    assert code == 0, data
    assert data["reused"] is False
    assert idle(data) == [{
        "code": "idle_box_available", "lease": "l-0000a001",
        "message": "lease l-0000a001 (ft) is idle: RTX 3060, 1x12 GB, 50m left",
        "fix": "vasty status l-0000a001",
    }]


def test_name_miss_warns_idle_box_available(h: Harness) -> None:
    add_lease(h, label={"name": "ft"})
    _, data = run_json(h, "reserve", "--name", "other", "--ttl", "1h")
    assert data["reused"] is False
    [warning] = idle(data)
    assert warning["message"] == (
        "lease l-0000a001 (ft) is idle: RTX 3090, 1x24 GB, 50m left, 10m short; extend --to 1h"
    )


def test_name_miss_extend_to_keeps_seconds(h: Harness) -> None:
    add_lease(h, label={"name": "ft"})
    _, data = run_json(h, "reserve", "--name", "other", "--ttl", "5430s")
    [warning] = idle(data)
    assert warning["message"].endswith("short; extend --to 1h30m30s")


def test_four_idle_boxes_yield_three_warnings(h: Harness) -> None:
    for lease, left in (("l-0000a001", 600), ("l-0000a002", 2400), ("l-0000a003", 900),
                        ("l-0000a004", 3600)):
        add_lease(h, lease, label={"expires": NOW + left})
    _, data = run_json(h, "reserve")
    assert [(w["lease"], w["message"].split(": ")[1]) for w in idle(data)] == [
        ("l-0000a004", "RTX 3090, 1x24 GB, 1h left"),
        ("l-0000a002", "RTX 3090, 1x24 GB, 40m left"),
        ("l-0000a003", "RTX 3090, 1x24 GB, 15m left, 15m short; extend --to 30m"),
    ]


def test_name_hit_emits_no_idle_box_available(h: Harness) -> None:
    add_lease(h, "l-0000a001", label={"name": "ft"})
    add_lease(h, "l-0000a002", label={"name": "other"})
    _, data = run_json(h, "reserve", "--name", "ft")
    assert data["reused"] is True
    assert idle(data) == []


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


# SSH key.


def test_registers_public_key_before_create(h: Harness) -> None:
    add_key(h)
    run_json(h, "reserve")
    names = [call for call, _ in h.provider.calls]
    assert names.index("attach_ssh_key") < names.index("create")
    assert h.provider.attached == [(PUB, None)]


def test_skips_registration_when_key_exists(h: Harness) -> None:
    from vasty.models import SshKey

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


def test_create_timeout_failed_duplicate_destroy_names_release_fix(h: Harness) -> None:
    _timing_out_create(h, 2)
    h.provider.fail["destroy"] = VastyError("provider_error", "boom", "retry")
    code, out, err = h.run("reserve")
    assert code == 0, out
    kept = min(h.provider.instances)
    assert (
        f"vasty: could not destroy duplicate instance {kept + 1}: boom"
        f" Run vasty release i-{kept + 1}."
    ) in err


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


def test_create_rejected_destroys_the_labelled_instance(h: Harness) -> None:
    h.provider.reject_created = True
    code, data = run_json(h, "reserve")
    assert code == 2
    assert data["error"] == "provider_error"
    assert "offer taken" in data["message"]
    details = data["details"]
    assert (details["lease"], details["instance_id"], details["destroyed"]) == (
        "l-abababab", 1001, True)
    assert h.provider.destroyed == [1001]
    assert calls(h, "destroy") == [1001]
    assert h.provider.instances == {}


def test_create_rejected_without_an_instance_destroys_nothing(h: Harness) -> None:
    h.provider.fail["create"] = rejected_error()
    code, data = run_json(h, "reserve")
    assert code == 2
    assert data["error"] == "provider_error"
    details = data["details"]
    assert (details["lease"], details["instance_id"], details["destroyed"]) == (
        "l-abababab", None, False)
    assert calls(h, "destroy") == []
    assert data["hint"] == "Run vasty status to look for l-abababab before reserving again."


def test_create_rejected_failed_destroy_names_release_fix(h: Harness) -> None:
    h.provider.reject_created = True
    h.provider.fail["destroy"] = VastyError("provider_error", "boom.", "retry")
    code, out, err = h.run("reserve")
    data = json.loads(out)
    assert code == 2
    assert (data["details"]["instance_id"], data["details"]["destroyed"]) == (1001, False)
    assert "vasty: could not destroy instance 1001 for l-abababab: boom. Run vasty release i-1001." in err


def test_create_error_other_than_timeout_is_not_retried(h: Harness) -> None:
    h.provider.fail["create"] = VastyError("provider_error", "no", "Run vasty status.")
    code, data = run_json(h, "reserve")
    assert code == 2
    assert data["error"] == "provider_error"
    assert len(calls(h, "create")) == 1


# reserve_lease for run and serve.


def test_reserve_lease_accepts_sparse_args(h: Harness) -> None:
    import argparse

    from vasty import engine

    ctx = h.context()
    snap = engine.refresh(ctx)
    reserved = reserve.reserve_lease(ctx, argparse.Namespace(), snap, ttl=7200)
    assert reserved.result.state == "running"
    assert reserved.lease.label.ttl == 7200
    assert reserved.result.ttl_remaining_s == 7200


# Every error after create names the lease and whether the box was destroyed.


def _rejected_with_row(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    h.provider.reject_created = True


def _rejected_without_row(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    h.provider.fail["create"] = rejected_error()


def _timeout_without_row(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    _timing_out_create(h, 0)


def _unsupported(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    unsupported_image(h)


def _port_missing(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    def drop_port(inst: Instance, req: CreateRequest) -> None:
        boot(h, inst, req)
        del inst.ports[8080]

    h.provider.on_create = drop_port


def _never_ready(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    h.provider.start_status = "loading"


def _refresh_always_fails(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    h.provider.start_status = "loading"
    fail_list_on_sleep(h, monkeypatch, 10_000)


def _ended_before_ready(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    h.provider.start_status = "loading"
    real_sleep = h.time.sleep

    def sleep(seconds: float) -> None:
        h.provider.instances.clear()
        real_sleep(seconds)

    monkeypatch.setattr(h.time, "sleep", sleep)


def _sleep_error(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    h.provider.start_status = "loading"

    def sleep(seconds: float) -> None:
        raise VastyError("provider_error", "sleep failed", "retry")

    monkeypatch.setattr(h.time, "sleep", sleep)


@pytest.mark.parametrize(("setup", "error", "destroyed"), [
    (_rejected_with_row, "provider_error", True),
    (_rejected_without_row, "provider_error", False),
    (_timeout_without_row, "provider_error", False),
    (_unsupported, "image_unsupported", True),
    (_port_missing, "port_mapping_missing", True),
    (_never_ready, "box_unreachable", True),
    (_refresh_always_fails, "box_unreachable", True),
    (_ended_before_ready, "box_unreachable", True),
    (_sleep_error, "provider_error", True),
])
def test_every_error_after_create_names_lease_and_destroyed(
    h: Harness, monkeypatch: pytest.MonkeyPatch, setup: Any, error: str, destroyed: bool
) -> None:
    setup(h, monkeypatch)
    code, data = run_json(h, "reserve", "--image", "alpine:3", "--ttl", "5m")
    assert code != 0
    assert data["error"] == error
    assert data["details"]["lease"] == "l-abababab"
    assert data["details"]["destroyed"] is destroyed


def test_wait_writes_each_milestone_once(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    h.provider.start_status = "loading"
    real_sleep = h.time.sleep
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        real_sleep(seconds)
        if len(sleeps) == 2:
            for inst in h.provider.instances.values():
                inst.actual_status = "running"

    monkeypatch.setattr(h.time, "sleep", sleep)
    code, _out, err = h.run("reserve", "--json")
    assert code == 0
    prefix = "vasty: l-abababab "
    said = [line.removeprefix(prefix) for line in err.splitlines() if line.startswith(prefix)]
    assert said[0].startswith("created on instance ")
    assert said[1:] == [
        "running on Vast; waiting for SSH",
        "answers SSH; waiting for startup",
        "startup done",
    ]


@pytest.mark.parametrize(("fail", "destroyed"), [(False, True), (True, False)])
def test_lease_swept_by_the_follower_during_wait_reports_destroyed(
    h: Harness, monkeypatch: pytest.MonkeyPatch, fail: bool, destroyed: bool
) -> None:
    h.provider.start_status = "loading"
    h.provider.keep_rows = fail
    real_sleep = h.time.sleep

    def sleep(seconds: float) -> None:
        real_sleep(7)
        if h.time.wall_now > NOW + 120 and not h.provider.destroyed:
            if fail:
                h.provider.fail["destroy"] = VastyError("provider_error", "boom", "retry")
            engine.refresh(h.context(), probe=False)

    monkeypatch.setattr(h.time, "sleep", sleep)
    code, data = run_json(h, "reserve", "--ttl", "2m")
    assert code == 2
    assert data["message"] == (
        "Lease l-abababab did not become ready before its clock ran out; Vast last reported it loading."
    )
    assert data["details"] == {"lease": "l-abababab", "destroyed": destroyed}
