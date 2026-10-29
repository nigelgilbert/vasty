from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from fakes import Harness
from rig.cli import parse
from rig.context import Context
from rig.errors import RigError


def test_parser_error_is_invalid_arguments(harness: Harness) -> None:
    code, out, _ = harness.run("reserve", "--bogus")
    assert code == 1
    assert json.loads(out)["error"] == "invalid_arguments"


def test_json_and_plain_conflict() -> None:
    with pytest.raises(RigError) as exc:
        parse(["status", "--json", "--plain"])
    assert exc.value.code == "invalid_arguments"


def test_on_rejects_creation_flags() -> None:
    with pytest.raises(RigError):
        parse(["run", "--on", "ft", "--gpu", "4090", "--", "true"])


def test_run_on_accepts_sync() -> None:
    ns = parse(["run", "--on", "ft", "--sync", ".", "--", "python", "x.py"])
    assert ns.command == ["python", "x.py"]


def test_auto_reserve_rejects_no_wait() -> None:
    with pytest.raises(RigError):
        parse(["serve", "--model", "m", "--no-wait"])


def test_config_and_startup_stdin_conflict() -> None:
    with pytest.raises(RigError):
        parse(["reserve", "--config", "-", "--startup", "-"])


@pytest.mark.parametrize(
    "argv",
    [
        ["release", "ft", "--group", "g"],
        ["release", "--all", "--group", "g"],
        ["release", "--everyone", "--owner", "o"],
        ["release", "--everyone"],
    ],
)
def test_target_selector_rules(argv: list[str]) -> None:
    with pytest.raises(RigError):
        parse(argv)


def test_everyone_with_group_is_allowed() -> None:
    ns = parse(["release", "--group", "g", "--everyone"])
    assert ns.group == "g" and ns.everyone


@pytest.mark.parametrize(
    ("extra_env", "key_env"), [({}, "VAST_API_KEY"), ({"RIG_API_KEY_ENV": "MY_KEY"}, "MY_KEY")]
)
def test_status_without_api_key_is_auth_missing(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, extra_env: dict[str, str], key_env: str
) -> None:
    import rig.provider

    def no_provider(*args: Any, **kw: Any) -> Any:
        raise AssertionError("VastProvider constructed")

    monkeypatch.setattr(rig.provider, "VastProvider", no_provider)
    for name in ("VAST_API_KEY", "MY_KEY", "RIG_API_KEY_ENV"):
        monkeypatch.delenv(name, raising=False)
        harness.env.pop(name, None)
    harness.env.update(extra_env)
    make = harness.context

    def context(stdin: str = "", tty: bool = False) -> Context:
        return replace(make(stdin=stdin, tty=tty), provider_factory=None)

    monkeypatch.setattr(harness, "context", context)
    code, out, _ = harness.run("status")
    result = json.loads(out)
    assert code == 1
    assert result["error"] == "auth_missing"
    assert key_env in result["hint"]
    assert harness.http_calls == []
