"""End-to-end flows through the real `reserve_lease`, against the fakes."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from fakes import Harness, add_lease, make_offer

from vasty.labels import parse
from vasty.models import CreateRequest, Instance, Label
from vasty.provider import build_offer_query


def boot(harness: Harness, inst: Instance, request: CreateRequest) -> None:
    """Give the created box a clock file the way onstart does."""
    label = parse(request.label)
    assert isinstance(label, Label)
    harness.box.state(inst.id).clock = int(harness.time.wall_now) + label.ttl


@pytest.fixture
def h(harness: Harness) -> Harness:
    harness.provider.offers = [make_offer(1), make_offer(2, gpu_name="A100 SXM4", gpu_ram_gb=80.0, dph_total=Decimal("1.20"))]
    harness.provider.on_create = lambda inst, req: boot(harness, inst, req)
    harness.hex_values = [f"{i:08x}" for i in range(1, 50)]
    return harness


def run_json(harness: Harness, *argv: str) -> tuple[int, dict[str, Any]]:
    code, out, _ = harness.run(*argv)
    data: dict[str, Any] = json.loads(out)
    return code, data


def test_auto_reserved_run_releases_the_box(h: Harness) -> None:
    code, data = run_json(h, "run", "--", "python", "train.py")
    assert code == 0, data
    assert data["exit"] == 0
    assert data["released"] is True
    assert h.provider.instances == {}
    assert len(h.provider.created) == 1
    label = parse(h.provider.created[0].label)
    assert isinstance(label, Label)
    assert label.ttl == 1800


def test_auto_reserved_run_passes_remote_exit_code(h: Harness) -> None:
    h.provider.on_create = lambda inst, req: (boot(h, inst, req), setattr(h.box.state(inst.id), "job_exit", 2))  # type: ignore[func-returns-value]
    code, data = run_json(h, "run", "--", "false")
    assert code == 2
    assert data["exit"] == 2
    assert data["error"] is None


def test_detached_run_leaves_the_box_alive(h: Harness) -> None:
    code, data = run_json(h, "run", "--detach", "--", "sleep", "100")
    assert code == 0, data
    assert data["job"] == "j-1"
    assert len(h.provider.instances) == 1
    code, status = run_json(h, "status", data["lease"])
    assert code == 0
    entry = status["leases"][0]["jobs"][0]
    assert entry["job"] == "j-1" and "id" not in entry


def test_auto_reserved_serve_returns_endpoint(h: Harness) -> None:
    code, data = run_json(h, "serve", "--model", "Qwen/Qwen3-14B-AWQ",
                          "--image", "vllm/vllm-openai:v0.32.0", "--max-price", "2")
    assert code == 0, data
    assert data["url"].startswith("http://198.51.100.7:")
    assert data["url"].endswith("/v1")
    assert data["api_key"].startswith("vasty-")
    assert h.provider.created[0].image == "vllm/vllm-openai:v0.32.0"
    assert len(h.provider.instances) == 1


def idle(data: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(w["lease"], w["message"], w["fix"]) for w in data["warnings"]
            if w["code"] == "idle_box_available"]


def test_auto_reserved_run_warns_idle_box_available(h: Harness) -> None:
    add_lease(h, "l-0000a001", gpu_name="RTX 3060", gpu_ram_gb=12.0)
    code, data = run_json(h, "run", "--ttl", "2h", "--", "python", "train.py")
    assert code == 0, data
    assert idle(data) == [(
        "l-0000a001",
        "lease l-0000a001 is idle: RTX 3060, 1x12 GB, 50m left, 1h10m short; extend --to 2h",
        "vasty status l-0000a001",
    )]


def test_auto_reserved_serve_warns_idle_box_with_serve_port(h: Harness) -> None:
    add_lease(h, "l-0000a001")
    add_lease(h, "l-0000a002", ports={22: 40022})
    code, data = run_json(h, "serve", "--model", "Qwen/Qwen3-14B-AWQ",
                          "--image", "vllm/vllm-openai:v0.32.0", "--max-price", "2")
    assert code == 0, data
    assert [(lease, fix) for lease, _, fix in idle(data)] == [
        ("l-0000a001", "vasty status l-0000a001"),
    ]


def test_serve_profile_sends_hardware_to_search(h: Harness) -> None:
    path = h.home / ".config" / "vasty" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[profiles.vllm]\nimage = "vllm/vllm-openai:v0.32.0"\nvram = 24\ncuda = 13\n')
    code, data = run_json(h, "serve", "--profile", "vllm", "--model", "Qwen/Qwen3-14B-AWQ")
    assert code == 0, data
    query = next(arg for name, arg in h.provider.calls if name == "search_offers")
    assert (query.vram_min_gb, query.cuda) == (24.0, 13.0)
    assert build_offer_query(query)["cuda_max_good"] == {"gte": 13.0}
    assert h.provider.created[0].image == "vllm/vllm-openai:v0.32.0"


def test_serve_failure_releases_reserved_box(h: Harness) -> None:
    h.http_status = 500
    code, data = run_json(h, "serve", "--model", "Qwen/Qwen3-14B-AWQ", "--max-price", "2")
    assert code == 2
    assert data["error"] == "serve_failed"
    assert "log_tail" in data["details"]
    assert h.provider.instances == {}


def test_spending_commands_make_no_balance_or_charges_call(h: Harness) -> None:
    """`reserve`, `extend`, `run`, `serve` and `tag` leave Vast's billing endpoints alone."""
    orphan = h.provider.add_instance(id=55120)
    h.box.state(orphan.id)
    steps = [
        ["reserve", "--name", "ft", "--ttl", "1h"],
        ["extend", "ft", "--by", "30m"],
        ["run", "--on", "ft", "--", "true"],
        ["run", "--", "true"],
        ["serve", "--on", "ft", "--model", "Qwen/Qwen3-14B-AWQ"],
        ["tag", "ft", "--group", "exp"],
        ["tag", "i-55120", "--ttl", "30m"],
    ]
    for argv in steps:
        code, data = run_json(h, *argv)
        assert code == 0, (argv, data)
    assert [call for call, _ in h.provider.calls if call in ("balance", "charges")] == []


def test_post_training_workflow(h: Harness, tmp_path: Any) -> None:
    """The post-training workflow with a named box."""
    code, res = run_json(h, "reserve", "--name", "ft", "--ttl", "3h")
    assert code == 0, res
    src = tmp_path / "project" / "code"
    src.mkdir()
    code, sync = run_json(h, "sync", "ft", "push", str(src) + "/", "/workspace/")
    assert code == 0, sync
    code, job = run_json(h, "run", "--on", "ft", "--detach", "--", "python", "train.py")
    assert code == 0, job
    code, ext = run_json(h, "extend", "ft", "--by", "1h")
    assert code == 0, ext
    assert ext["ttl_remaining_s"] == 4 * 3600
    code, rel = run_json(h, "release", "ft")
    assert code == 0, rel
    assert rel["jobs"][0]["job"] == "j-1" and "id" not in rel["jobs"][0]
    assert rel["jobs"][0]["state"] == "killed" and rel["jobs"][0]["exit"] is None
    assert h.provider.instances == {}


def test_group_workflow(h: Harness) -> None:
    """A multi-box experiment: reserve a group, align clocks, release together."""
    for i in range(3):
        code, res = run_json(h, "reserve", "--name", f"eval-{i}", "--group", "exp42", "--ttl", "1h")
        assert code == 0, res
    code, ext = run_json(h, "extend", "--group", "exp42", "--to", "2h")
    assert code == 0, ext
    expiries = {r["expires_at"] for r in ext["results"]}
    assert len(expiries) == 1
    code, rel = run_json(h, "release", "--group", "exp42")
    assert code == 0, rel
    assert len(rel["results"]) == 3
    assert h.provider.instances == {}


def test_reserve_name_reuse_through_run(h: Harness) -> None:
    code, first = run_json(h, "reserve", "--name", "ft")
    assert code == 0
    code, data = run_json(h, "run", "--name", "ft", "--", "true")
    assert code == 0, data
    assert data["lease"] == first["lease"]
    assert data["released"] is False
    assert len(h.provider.created) == 1


def test_expired_box_is_swept_by_next_command(h: Harness) -> None:
    code, res = run_json(h, "reserve", "--name", "short", "--ttl", "10m")
    assert code == 0
    h.time.advance(11 * 60)
    code, status = run_json(h, "status")
    assert code == 0
    assert [s["lease"] for s in status["swept"]] == [res["lease"]]
    assert h.provider.instances == {}
    assert Decimal(str(status["totals"]["burn_per_hr"])) == 0
