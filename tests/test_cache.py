from __future__ import annotations

import fcntl
import json
import os
import threading
from decimal import Decimal
from pathlib import Path

import pytest

from rig.cache import Cache, CacheData
from rig.models import CachedLease, Job, Label


def full_lease() -> CachedLease:
    return CachedLease(
        lease="l-7f3a0001",
        instance_id=55120,
        label=Label(
            lease="l-7f3a0001", owner="claude", created=1793235840, ttl=10800,
            name="trainer", group="exp42", expires=1793247000, miss=["watchdog"],
            extra={"zeta": "1", "alpha": "2"},
        ),
        state="running",
        gpu="A100",
        gpus=2,
        vram_gb=80.0,
        price_per_hr=Decimal("2.4012"),
        image="vastai/base",
        actual_status="running",
        ssh_host="ssh5.vast.ai",
        ssh_port=41022,
        ports={22: 41022, 8000: 41080},
        reachable_at=1793236000,
        guard_missing=["watchdog"],
        startup_exit=0,
        startup_started=True,
        jobs=[
            Job(id="j-1", cmd="python train.py", started_at=1793236100, exit=None,
                state="running", log_path="/workspace/.rig/jobs/j-1/log", pid=4242),
            Job(id="j-2", cmd="vllm", started_at=1793236200, exit=0, state="serving",
                kind="serve", port=8000, finished_at=1793236300),
        ],
        released_here=True,
        destroy_pending=True,
        history_since=1793240000,
        expired_at=1793247000,
        last_provider_error="HTTP 500",
    )


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "state" / "rig" / "leases.json")


def test_missing_file_is_empty(cache: Cache) -> None:
    data = cache.load()
    assert data == CacheData()
    assert not data.rebuilt


def test_round_trip(cache: Cache) -> None:
    lease = full_lease()
    cache.save(CacheData(leases={lease.lease: lease}, cached_at=1793236500))
    data = cache.load()
    assert data.cached_at == 1793236500
    assert not data.rebuilt
    assert data.leases == {lease.lease: lease}
    restored = data.leases[lease.lease]
    assert isinstance(restored.price_per_hr, Decimal)
    assert list(restored.ports) == [22, 8000]
    assert list(restored.label.extra) == ["zeta", "alpha"]


def test_file_shape(cache: Cache) -> None:
    lease = full_lease()
    cache.save(CacheData(leases={lease.lease: lease}, cached_at=5))
    body = json.loads(cache.path.read_text())
    assert body["version"] == 1
    assert body["cached_at"] == 5
    entry = body["leases"][lease.lease]
    assert entry["price_per_hr"] == "2.4012"
    assert entry["ports"] == {"22": 41022, "8000": 41080}
    assert entry["label"]["miss"] == ["watchdog"]
    assert entry["jobs"][1]["kind"] == "serve"


def test_defaults_fill_absent_fields(cache: Cache) -> None:
    cache.path.parent.mkdir(parents=True)
    minimal = {
        "lease": "l-1", "instance_id": 7, "state": "pending",
        "label": {"lease": "l-1", "owner": "o", "created": 1, "ttl": 60},
        "future_field": 1,
    }
    cache.path.write_text(json.dumps({"version": 1, "cached_at": None, "leases": {"l-1": minimal}}))
    data = cache.load()
    assert not data.rebuilt
    assert data.leases["l-1"] == CachedLease(
        lease="l-1", instance_id=7, state="pending",
        label=Label(lease="l-1", owner="o", created=1, ttl=60),
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "{not json",
        "[]",
        json.dumps({"version": 2, "leases": {}}),
        json.dumps({"version": 1, "leases": []}),
        json.dumps({"version": 1, "cached_at": "yesterday", "leases": {}}),
        json.dumps({"version": 1, "leases": {"l-1": {"lease": "l-1"}}}),
        json.dumps({"version": 1, "leases": {"l-1": {
            "lease": "l-1", "instance_id": "7", "state": "pending",
            "label": {"lease": "l-1", "owner": "o", "created": 1, "ttl": 60}}}}),
        json.dumps({"version": 1, "leases": {"l-1": {
            "lease": "l-1", "instance_id": 7, "state": "sleepy",
            "label": {"lease": "l-1", "owner": "o", "created": 1, "ttl": 60}}}}),
        json.dumps({"version": 1, "leases": {"l-1": {
            "lease": "l-1", "instance_id": 7, "state": "pending", "price_per_hr": "abc",
            "label": {"lease": "l-1", "owner": "o", "created": 1, "ttl": 60}}}}),
        json.dumps({"version": 1, "leases": {"l-1": {
            "lease": "l-1", "instance_id": 7, "state": "pending", "ports": {"ssh": 1},
            "label": {"lease": "l-1", "owner": "o", "created": 1, "ttl": 60}}}}),
    ],
)
def test_corrupt_file_rebuilds(cache: Cache, text: str) -> None:
    cache.path.parent.mkdir(parents=True)
    cache.path.write_text(text)
    data = cache.load()
    assert data.rebuilt
    assert data.leases == {}
    assert data.cached_at is None


def test_non_utf8_file_rebuilds(cache: Cache) -> None:
    cache.path.parent.mkdir(parents=True)
    cache.path.write_bytes(b"\xff\xfe\x00")
    assert cache.load().rebuilt


def test_save_after_rebuild_recovers(cache: Cache) -> None:
    cache.path.parent.mkdir(parents=True)
    cache.path.write_text("garbage")
    data = cache.load()
    data.leases["l-1"] = full_lease()
    cache.save(data)
    again = cache.load()
    assert not again.rebuilt
    assert again.leases["l-1"] == full_lease()


def _try_flock(path: Path) -> bool:
    with open(path, "ab") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return True


def test_lock_creates_parent_and_is_exclusive(cache: Cache) -> None:
    lock_path = cache.path.with_name("leases.json.lock")
    with cache.lock():
        assert lock_path.exists()
        assert not _try_flock(lock_path)
    assert _try_flock(lock_path)


def test_lock_is_reentrant_and_nests_with_load_save(cache: Cache) -> None:
    lock_path = cache.path.with_name("leases.json.lock")
    with cache.lock():
        with cache.lock():
            data = cache.load()
            data.cached_at = 9
            cache.save(data)
        assert not _try_flock(lock_path)
        assert cache.load().cached_at == 9
    assert _try_flock(lock_path)


def test_lock_released_after_exception(cache: Cache) -> None:
    with pytest.raises(RuntimeError):
        with cache.lock():
            raise RuntimeError("boom")
    assert _try_flock(cache.path.with_name("leases.json.lock"))


def test_lock_blocks_other_threads(cache: Cache) -> None:
    entered = threading.Event()
    order: list[str] = []

    def other() -> None:
        with cache.lock():
            order.append("other")
        entered.set()

    with cache.lock():
        thread = threading.Thread(target=other)
        thread.start()
        assert not entered.wait(0.2)
        order.append("main")
    thread.join(5)
    assert order == ["main", "other"]


def test_save_replaces_by_rename(cache: Cache) -> None:
    cache.save(CacheData(cached_at=1))
    first = os.stat(cache.path).st_ino
    cache.save(CacheData(cached_at=2))
    assert os.stat(cache.path).st_ino != first
    assert cache.load().cached_at == 2
    assert sorted(p.name for p in cache.path.parent.iterdir()) == ["leases.json", "leases.json.lock"]
    assert os.stat(cache.path).st_mode & 0o077 == 0


def test_failed_replace_keeps_old_file(cache: Cache, monkeypatch: pytest.MonkeyPatch) -> None:
    cache.save(CacheData(cached_at=1))

    def fail(src: str, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        cache.save(CacheData(cached_at=2))
    monkeypatch.undo()
    assert cache.load().cached_at == 1
    assert sorted(p.name for p in cache.path.parent.iterdir()) == ["leases.json", "leases.json.lock"]


def test_unserializable_value_leaves_file_alone(cache: Cache) -> None:
    cache.save(CacheData(cached_at=1))
    bad = full_lease()
    bad.gpu = object()  # type: ignore[assignment]
    with pytest.raises(TypeError):
        cache.save(CacheData(leases={"l-1": bad}))
    assert cache.load().cached_at == 1
