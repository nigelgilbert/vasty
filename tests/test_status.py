from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fakes import NOW, START, Harness, add_lease
from vasty.errors import VastyError
from vasty.models import Job
from vasty.timeutil import iso

SRC = Path(__file__).resolve().parents[1] / "src"

LEASE_KEYS = {
    "lease", "name", "group", "owner", "state", "gpu", "gpus",
    "vram_gb", "price_per_hr", "cost", "uptime_s", "expires_at", "ttl_remaining_s", "busy",
    "jobs",
}
TOTALS_KEYS = {"balance", "credit", "charges_today", "burn_per_hr", "live", "live_mine"}


def status(harness: Harness, *argv: str) -> dict[str, Any]:
    code, out, err = harness.run("status", *argv)
    assert code == 0, out + err
    data: dict[str, Any] = json.loads(out)
    return data


def by_lease(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["lease"]: row for row in data["leases"]}


def codes(data: dict[str, Any]) -> list[tuple[str, str | None]]:
    return [(w["code"], w["lease"]) for w in data["warnings"]]


@pytest.fixture
def account(harness: Harness) -> Harness:
    """A full status page in miniature: a group, a dead host, an orphan and another owner's box."""
    p = harness.provider
    trainer = add_lease(harness, "l-7f3a", label={"name": "trainer", "group": "exp42",
                                                  "created": NOW - 7260, "ttl": 4 * 3600,
                                                  "expires": NOW + 4320},
                        gpu_name="A100 SXM4", num_gpus=2, dph_total=Decimal("2.40"))
    harness.box.state(trainer.id).jobs["j-1"] = Job(
        id="j-1", cmd="python train.py", started_at=NOW - 7260, exit=None, state="running")
    add_lease(harness, "l-8b10", label={"name": "eval-0", "group": "exp42",
                                        "expires": NOW + 720},
              gpu_name="L40S", dph_total=Decimal("0.82"))
    dead = add_lease(harness, "l-8b11", label={"name": "eval-1", "group": "exp42",
                                               "expires": NOW + 720},
                     gpu_name="L40S", dph_total=Decimal("0.82"))
    harness.box.state(dead.id).jobs["j-3"] = Job(
        id="j-3", cmd="vllm serve", started_at=NOW - 60, exit=None, state="serving",
        kind="serve", port=8000)
    add_lease(harness, "l-8b12", label={"name": "eval-2", "group": "exp42",
                                        "expires": NOW + 180},
              gpu_name="L40S", dph_total=Decimal("0.82"))
    add_lease(harness, "l-a003", label={"name": "scratch", "owner": "nick",
                                        "expires": NOW + 1140},
              gpu_name="RTX 4090", dph_total=Decimal("0.38"))
    p.add_instance(id=55120, label=None, gpu_name="RTX 3090", dph_total=Decimal("0.22"))
    p.billed = {1: Decimal("2.32"), trainer.id: Decimal("4.80")}
    p.charge_rows = [(trainer.id, Decimal("1.20"), START - 3600)]
    harness.run("status")
    harness.box.state(dead.id).reachable = False
    return harness


def test_status_json_shape(account: Harness) -> None:
    data = status(account)
    assert set(data) == {"leases", "warnings", "totals", "swept", "cached_at"}
    assert data["cached_at"] is None
    assert data["swept"] == []
    for row in data["leases"]:
        assert set(row) == LEASE_KEYS
    for warning in data["warnings"]:
        assert set(warning) == {"code", "lease", "message", "fix"}
    assert set(data["totals"]) == TOTALS_KEYS
    assert [row["lease"] for row in data["leases"]] == [
        "l-7f3a", "l-8b10", "l-8b11", "l-8b12", "l-a003", "i-55120"
    ]
    row = by_lease(data)["l-8b12"]
    assert row == {
        "lease": "l-8b12", "name": "eval-2", "group": "exp42", "owner": "claude",
        "state": "running", "gpu": "L40S", "gpus": 1,
        "vram_gb": 24.0, "price_per_hr": 0.82, "cost": None, "uptime_s": 0,
        "expires_at": "2026-10-29T01:03:00Z", "ttl_remaining_s": 180, "busy": False, "jobs": [],
    }


def test_status_orphan_row(account: Harness) -> None:
    row = by_lease(status(account))["i-55120"]
    assert row["state"] == "orphan"
    for key in ("owner", "expires_at", "ttl_remaining_s", "uptime_s", "busy"):
        assert row[key] is None
    assert row["gpu"] == "RTX 3090"
    assert row["price_per_hr"] == 0.22


def test_status_orphan_hardware_from_instance_row(harness: Harness) -> None:
    harness.provider.add_instance(id=55120, label=None, num_gpus=2, gpu_ram_gb=12.288)
    row = by_lease(status(harness))["i-55120"]
    assert (row["gpus"], row["vram_gb"], row["busy"]) == (2, 12.288, None)
    _, out, _ = harness.run("status", "--plain")
    assert "2x12 3090" in out.splitlines()[1]


def test_status_busy(account: Harness) -> None:
    rows = by_lease(status(account))
    busy = {lease: row["busy"] for lease, row in rows.items()}
    assert busy == {"l-7f3a": True, "l-8b10": False, "l-8b11": None, "l-8b12": False,
                    "l-a003": False, "i-55120": None}
    assert (rows["l-7f3a"]["gpus"], rows["l-7f3a"]["vram_gb"]) == (2, 24.0)


def test_status_busy_with_unknown_job(harness: Harness) -> None:
    row = add_lease(harness)
    harness.box.state(row.id).jobs["j-1"] = Job(
        id="j-1", cmd="python train.py", started_at=NOW - 60, exit=None, state="unknown")
    assert by_lease(status(harness))["l-0000a001"]["busy"] is True


def test_status_busy_null_while_pending(harness: Harness) -> None:
    add_lease(harness, actual_status="loading")
    row = by_lease(status(harness))["l-0000a001"]
    assert (row["state"], row["busy"]) == ("pending", None)
    _, out, _ = harness.run("status", "--plain")
    assert out.splitlines()[1].split()[-1] == "—"


def test_status_busy_null_while_unreachable(harness: Harness) -> None:
    lease = add_lease(harness)
    harness.run("status")
    harness.box.state(lease.id).reachable = False
    row = by_lease(status(harness))["l-0000a001"]
    assert (row["state"], row["busy"], row["jobs"]) == ("unreachable", None, [])
    _, out, _ = harness.run("status", "--plain")
    assert out.splitlines()[1].split()[-1] == "—"


def test_status_totals(account: Harness) -> None:
    totals = status(account)["totals"]
    assert totals == {
        "balance": 0.0, "credit": 20.0, "charges_today": 7.12,
        "burn_per_hr": 5.46, "live": 5, "live_mine": 4,
    }


def test_status_cost_sums_charge_rows_across_two_days(account: Harness) -> None:
    rows = by_lease(status(account))
    assert rows["l-7f3a"]["cost"] == 6.0
    assert rows["l-8b10"]["cost"] is None
    starts = [arg[0] for call, arg in account.provider.calls if call == "charges"]
    assert starts and set(starts) == {START - 86_400}


def test_status_warnings(account: Harness) -> None:
    data = status(account)
    found = codes(data)
    assert ("expiring_soon", "l-8b12") in found
    assert ("box_unreachable", "l-8b11") in found
    assert ("orphan", "i-55120") in found
    assert ("spend_unavailable", None) not in found
    fixes = {w["code"]: w["fix"] for w in data["warnings"]}
    assert fixes["expiring_soon"] == "vasty extend l-8b12 --by 30m"
    assert fixes["orphan"] == "vasty tag i-55120 --ttl 30m"


def test_status_unreachable_jobs_unknown(account: Harness) -> None:
    row = by_lease(status(account))["l-8b11"]
    assert row["state"] == "unreachable"
    assert row["jobs"] == [{"id": "j-3", "cmd": "vllm serve", "state": "unknown", "exit": None,
                            "duration_s": 60}]


@pytest.mark.parametrize(
    ("failing", "nulls", "kept"),
    [("charges", ["charges_today"], ["balance", "credit"]),
     ("balance", ["balance", "credit"], ["charges_today"])],
)
def test_status_spend_unavailable(
    harness: Harness, failing: str, nulls: list[str], kept: list[str]
) -> None:
    row = add_lease(harness)
    harness.provider.billed = {row.id: Decimal("1.00")}
    harness.provider.fail[failing] = VastyError("provider_error", "down", "Run vasty status.")
    data = status(harness)
    assert all(data["totals"][key] is None for key in nulls)
    assert all(data["totals"][key] is not None for key in kept)
    assert data["leases"][0]["cost"] == (None if failing == "charges" else 1.0)
    assert ("spend_unavailable", None) in codes(data)


def test_status_single_target_log_tail(account: Harness) -> None:
    trainer = account.provider.instances[next(
        i for i, inst in account.provider.instances.items() if "l-7f3a" in (inst.label or ""))]
    account.box.state(trainer.id).logs["j-1"] = [f"line {n}" for n in range(150)]
    data = status(account, "trainer")
    assert [row["lease"] for row in data["leases"]] == ["l-7f3a"]
    tail = data["leases"][0]["log_tail"]
    assert len(tail) == 100 and tail[-1] == "line 149"
    assert ("orphan", "i-55120") not in codes(data)
    assert data["totals"]["live"] == 5


def test_status_unreachable_target_skips_log_tail(account: Harness) -> None:
    data = status(account, "eval-1")
    assert "log_tail" not in data["leases"][0]


def test_status_group_and_owner_filters(account: Harness) -> None:
    data = status(account, "--group", "exp42")
    assert [row["lease"] for row in data["leases"]] == ["l-7f3a", "l-8b10", "l-8b11", "l-8b12"]
    assert [(row["busy"], row["gpus"], row["vram_gb"]) for row in data["leases"]] == [
        (True, 2, 24.0), (False, 1, 24.0), (None, 1, 24.0), (False, 1, 24.0)
    ]
    data = status(account, "--owner", "nick")
    assert [row["lease"] for row in data["leases"]] == ["l-a003"]


def test_status_empty_bulk_target(account: Harness) -> None:
    assert status(account, "--group", "nope")["leases"] == []


def test_status_orphan_by_instance_id(account: Harness) -> None:
    data = status(account, "i-55120")
    assert [row["lease"] for row in data["leases"]] == ["i-55120"]


def test_status_unknown_target(account: Harness) -> None:
    code, out, _ = account.run("status", "nope")
    assert code == 1
    assert json.loads(out)["error"] == "lease_not_found"


def test_status_verbose_fields(account: Harness) -> None:
    row = by_lease(status(account, "--verbose"))["l-8b12"]
    extra = row["verbose"]
    assert extra["label"].startswith("vasty:v1;lease=l-8b12;name=eval-2")
    assert extra["guard_layers"] == {"watchdog": "ok", "destroy_key": "ok", "clock_file": "ok"}
    assert extra["ports"] == {"22": 40022, "8000": 40080, "8080": 40081}
    assert extra["clock_skew_s"] == 0
    assert set(extra) >= {"instance_id", "image", "last_provider_error"}


def test_status_verbose_leaves_out_the_follower_pid(harness: Harness) -> None:
    add_lease(harness)
    harness.run("extend", "l-0000a001", "--by", "30m")
    assert harness.context().cache.load().leases["l-0000a001"].follower_pid == 4001
    _, out, _ = harness.run("status", "--verbose")
    assert "follower" not in out
    _, out, _ = harness.run("status", "--cached", "--verbose")
    assert "follower" not in out


def test_uptime_counts_from_first_running_sample(harness: Harness) -> None:
    add_lease(harness, label={"name": "ft", "created": NOW - 1200})
    harness.run("status")
    harness.time.advance(600)
    row = by_lease(status(harness, "--verbose"))["l-0000a001"]
    assert row["uptime_s"] == 600
    assert row["verbose"]["running_at"] == iso(NOW)
    _, out, _ = harness.run("status", "--plain")
    assert "10m" in out.splitlines()[1].split()


def test_uptime_null_before_running(harness: Harness) -> None:
    add_lease(harness, label={"name": "ft", "created": NOW - 1200}, actual_status="loading")
    assert by_lease(status(harness))["l-0000a001"]["uptime_s"] is None
    _, out, _ = harness.run("status", "--plain")
    header, line = out.splitlines()[:2]
    assert line[header.index("UPTIME"):].split()[0] == "—"


def test_history_only_when_named_or_verbose(harness: Harness) -> None:
    row = add_lease(harness, label={"name": "ft"})
    harness.run("status")
    del harness.provider.instances[row.id]
    assert status(harness)["leases"] == []
    assert [r["state"] for r in status(harness, "--verbose")["leases"]] == ["gone"]
    named = status(harness, "ft")["leases"]
    assert [r["state"] for r in named] == ["gone"]
    assert (named[0]["busy"], named[0]["gpus"], named[0]["vram_gb"]) == (None, 1, 24.0)


def test_swept_lease_in_status(harness: Harness) -> None:
    row = add_lease(harness, label={"name": "ft", "expires": NOW + 30})
    harness.box.state(row.id).jobs["j-1"] = Job(
        id="j-1", cmd="python train.py", started_at=NOW, exit=None, state="running")
    harness.run("status")
    harness.time.advance(60)
    data = status(harness)
    assert data["swept"] == [{"lease": "l-0000a001", "name": "ft",
                              "expired_at": "2026-10-29T01:00:30Z", "ok": True, "error": None}]
    assert ("expired_with_running_jobs", "l-0000a001") in codes(data)
    assert ("expired_with_running_jobs", "l-0000a001") in codes(status(harness))


def test_swept_line_in_human_mode(harness: Harness) -> None:
    add_lease(harness, label={"name": "ft", "expires": NOW - 30})
    _, out, _ = harness.run("status", "--plain")
    assert out.splitlines()[0] == "SWEPT  l-0000a001 ft  expired 2026-10-29T00:59:30Z  destroyed"


def test_status_cached_makes_no_network_call(account: Harness) -> None:
    account.provider.calls.clear()
    data = status(account, "--cached")
    assert account.provider.calls == []
    assert data["cached_at"] == "2026-10-29T01:00:00Z"
    assert data["swept"] == []
    assert [row["lease"] for row in data["leases"]] == [
        "l-7f3a", "l-8b10", "l-8b11", "l-8b12", "l-a003", "i-55120"
    ]
    assert (data["totals"]["charges_today"], data["totals"]["credit"]) == (7.12, 20.0)
    assert by_lease(data)["l-7f3a"]["cost"] == 6.0
    assert ("expiring_soon", "l-8b12") in codes(data)
    assert ("orphan", "i-55120") in codes(data)
    assert "log_tail" not in status(account, "--cached", "trainer")["leases"][0]


def test_status_cached_without_cache(harness: Harness) -> None:
    data = status(harness, "--cached")
    assert data["leases"] == [] and data["cached_at"] is None
    assert harness.provider.calls == []
    assert ("spend_unavailable", None) in codes(data)


def test_status_cached_ages_with_local_clock(account: Harness) -> None:
    account.time.advance(120)
    row = by_lease(status(account, "--cached"))["l-8b12"]
    assert row["ttl_remaining_s"] == 60


def test_status_cached_reads_legacy_unprobed_entry_as_partial(harness: Harness) -> None:
    add_lease(harness, reachable=False)
    status(harness)
    ctx = harness.context()
    data = ctx.cache.load()
    data.leases["l-0000a001"].guard_missing = []
    ctx.cache.save(data)
    cached = status(harness, "--cached", "--verbose")
    row = by_lease(cached)["l-0000a001"]
    assert row["verbose"]["guard_layers"] == {
        "watchdog": "missing", "destroy_key": "missing", "clock_file": "missing"
    }
    assert ("guard_partial", "l-0000a001") not in codes(cached)


def test_status_human_table(account: Harness) -> None:
    code, out, _ = account.run("status", "--plain")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].split() == ["LEASE", "NAME", "GROUP", "OWNER", "GPU", "STATE", "EXPIRES",
                                "UPTIME", "$/HR", "COST", "JOBS"]
    rows = {line.split()[0]: line for line in lines[1:7]}
    assert "2x24 A100 SXM4" in rows["l-7f3a"]
    assert rows["l-8b10"].endswith("idle")
    assert "j-1 train.py (running 2h01m)" in rows["l-7f3a"]
    assert "⚠ 3m" in rows["l-8b12"]
    assert "j-3 vllm (unknown)" in rows["l-8b11"]
    assert "4090" in rows["l-a003"] and "RTX" not in rows["l-a003"]
    orphan = rows["i-55120"].split()
    assert orphan[1:6] == ["—", "—", "?", "1x24", "3090"] and "none" in orphan and "?" in orphan[-3:]
    assert "WARNINGS" in lines
    warn = next(line for line in lines if "expiring_soon" in line)
    assert warn.split()[0] == "l-8b12" and warn.endswith("fix: vasty extend l-8b12 --by 30m")
    assert lines[-1] == ("TODAY  charged $7.12  ·  credit $20.00  ·  balance $0.00  ·  "
                         "5 leases live (4 yours)  ·  burning $5.46/hr")


def test_status_human_group_view(account: Harness) -> None:
    code, out, _ = account.run("status", "--group", "exp42", "--plain")
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith(
        "GROUP exp42 · 4 leases · 3 healthy, 1 unreachable · expiries 3m–1h12m · $")
    assert lines[0].endswith(" so far · $4.86/hr")
    body = {line.split()[0]: line for line in lines[1:5]}
    assert body["l-7f3a"].split()[1:3] == ["trainer", "running"]
    assert body["l-7f3a"].endswith("j-1 train.py running")
    assert body["l-8b11"].endswith("j-3 unknown")
    assert "⚠ 3m" in body["l-8b12"] and body["l-8b12"].endswith("idle")


def test_status_human_cached_header(account: Harness) -> None:
    _, out, _ = account.run("status", "--cached", "--plain")
    assert out.splitlines()[0] == "CACHED  as of 2026-10-29T01:00:00Z"


def test_status_cached_imports_stdlib_only(account: Harness) -> None:
    probe = (
        "import json, sys\n"
        "before = set(sys.modules)\n"
        "from vasty.cli import main\n"
        "code = main(sys.argv[1:])\n"
        "loaded = set(sys.modules) - before\n"
        "third = sorted(m for m in loaded if m.split('.')[0] not in sys.stdlib_module_names"
        " and m.split('.')[0] != 'vasty')\n"
        "print(json.dumps({'code': code, 'vastai': 'vastai' in sys.modules,"
        " 'provider': 'vasty.provider' in sys.modules, 'third': third}), file=sys.stderr)\n"
    )
    env = {"HOME": str(account.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "PYTHONPATH": str(SRC), "USER": "nick", "VASTY_OWNER": "claude"}
    result = subprocess.run([sys.executable, "-c", probe, "status", "--cached", "--json"],
                            env=env, cwd=account.home, capture_output=True, text=True, check=True)
    report = json.loads(result.stderr.strip().splitlines()[-1])
    assert report == {"code": 0, "vastai": False, "provider": False, "third": []}
    assert len(json.loads(result.stdout)["leases"]) == 6
