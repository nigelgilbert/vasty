from __future__ import annotations

import json
from typing import Any

import pytest

from fakes import NOW, Harness, add_lease

EXCLUDES = [".git", "__pycache__", ".venv", "node_modules"]


def sync(harness: Harness, *argv: str) -> tuple[int, dict[str, Any], str]:
    code, out, err = harness.run("sync", *argv)
    return code, json.loads(out), err


@pytest.fixture
def box(harness: Harness) -> int:
    return add_lease(harness, label={"name": "ft"}).id


def test_push(harness: Harness, box: int) -> None:
    code, data, _ = sync(harness, "ft", "push", "./", "/workspace/")
    assert code == 0
    assert data == {
        "lease": "l-0000a001", "direction": "push", "src": "./", "dest": "/workspace/",
        "warnings": [], "swept": [],
    }
    assert harness.box.rsyncs == [(box, True, "./", "/workspace/", False, EXCLUDES)]


def test_push_delete(harness: Harness, box: int) -> None:
    code, _, _ = sync(harness, "ft", "push", "--delete", "src/", "code/")
    assert code == 0
    assert harness.box.rsyncs == [(box, True, "src/", "code/", True, EXCLUDES)]


def test_pull(harness: Harness, box: int) -> None:
    code, data, _ = sync(harness, "ft", "pull", "/workspace/out/", "./out/")
    assert code == 0
    assert data["direction"] == "pull"
    assert harness.box.rsyncs == [(box, False, "/workspace/out/", "./out/", False, EXCLUDES)]


def test_pull_rejects_delete(harness: Harness, box: int) -> None:
    code, data, _ = sync(harness, "ft", "pull", "--delete", "a", "b")
    assert code == 1 and data["error"] == "invalid_arguments"


def test_failed_transfer_is_sync_failed(harness: Harness, box: int) -> None:
    harness.box.rsync_exit = 23
    code, data, _ = sync(harness, "ft", "push", "./", "/workspace/")
    assert code == 2
    assert data["error"] == "sync_failed"
    assert data["details"] == {"exit": 23}


@pytest.mark.parametrize("tool", ["ssh", "rsync"])
def test_missing_tool_is_dependency_missing(harness: Harness, box: int, tool: str) -> None:
    harness.missing_tools.add(tool)
    code, data, _ = sync(harness, "ft", "push", "./", "/workspace/")
    assert code == 1 and data["error"] == "dependency_missing"
    assert tool in data["message"]
    assert harness.box.rsyncs == []


def test_sync_orphan_is_unmanaged(harness: Harness) -> None:
    harness.provider.add_instance(id=55120)
    code, data, _ = sync(harness, "i-55120", "pull", "a", "b")
    assert code == 1 and data["error"] == "orphan_unmanaged"


def test_sync_pending_lease(harness: Harness) -> None:
    add_lease(harness, label={"name": "ft"}, reachable=False)
    code, data, _ = sync(harness, "ft", "pull", "a", "b")
    assert code == 1 and data["error"] == "lease_pending"


def test_sync_history_lease_is_expired(harness: Harness) -> None:
    add_lease(harness, label={"name": "ft", "expires": NOW - 1})
    code, data, _ = sync(harness, "ft", "pull", "a", "b")
    assert code == 1 and data["error"] == "lease_expired"


def test_sync_carries_lease_warnings(harness: Harness) -> None:
    add_lease(harness, label={"name": "ft", "expires": NOW + 60})
    code, data, _ = sync(harness, "ft", "pull", "a", "b")
    assert code == 0
    assert [w["code"] for w in data["warnings"]] == ["expiring_soon"]
