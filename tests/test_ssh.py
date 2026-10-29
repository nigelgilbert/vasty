from __future__ import annotations

import json

import pytest

from fakes import Harness, add_lease
from rig.remote import SshTarget


@pytest.fixture
def box(harness: Harness) -> int:
    return add_lease(harness, label={"name": "ft"}).id


def test_interactive_shell_emits_nothing(harness: Harness, box: int) -> None:
    code, out, _ = harness.run("ssh", "ft")
    assert code == 0
    assert out == ""
    assert harness.box.interactive_calls == [(box, None, [])]


def test_one_off_command_passes_exit_code(harness: Harness, box: int) -> None:
    def interactive(target: SshTarget, command: list[str] | None, ssh_args: list[str]) -> int:
        harness.box.interactive_calls.append((target.instance_id, command, ssh_args))
        return 7

    harness.box.interactive = interactive  # type: ignore[method-assign]
    code, out, _ = harness.run("ssh", "ft", "--", "cat", "/workspace/.rig/startup.log")
    assert code == 7
    assert out == ""
    assert harness.box.interactive_calls == [(box, ["cat", "/workspace/.rig/startup.log"], [])]


def test_forwards_pass_through(harness: Harness, box: int) -> None:
    code, _, _ = harness.run("ssh", "ft", "-L", "8000:127.0.0.1:8000", "-L", "9000:localhost:9000")
    assert code == 0
    assert harness.box.interactive_calls == [
        (box, None, ["-L", "8000:127.0.0.1:8000", "-L", "9000:localhost:9000"])
    ]


def test_missing_ssh(harness: Harness, box: int) -> None:
    harness.missing_tools.add("ssh")
    code, out, _ = harness.run("ssh", "ft")
    assert code == 1
    assert json.loads(out)["error"] == "dependency_missing"


@pytest.mark.parametrize("flag", ["--config", "--startup"])
def test_ssh_rejects_stdin_flags(harness: Harness, box: int, flag: str) -> None:
    code, out, _ = harness.run("ssh", "ft", flag, "-")
    assert code == 1
    assert json.loads(out)["error"] == "invalid_arguments"


def test_ssh_orphan(harness: Harness) -> None:
    harness.provider.add_instance(id=55120)
    code, out, _ = harness.run("ssh", "i-55120")
    assert code == 1
    assert json.loads(out)["error"] == "orphan_unmanaged"


def test_ssh_pending(harness: Harness) -> None:
    add_lease(harness, label={"name": "ft"}, reachable=False)
    code, out, _ = harness.run("ssh", "ft", "--", "ls")
    assert code == 1
    assert json.loads(out)["error"] == "lease_pending"
