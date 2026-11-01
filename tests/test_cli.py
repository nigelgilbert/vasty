from __future__ import annotations

import argparse
import io
import json
from dataclasses import replace
from importlib.metadata import version
from typing import Any

import pytest

from fakes import NOW, Harness, add_lease, make_offer
from vasty.cli import build_parser, main, parse
from vasty.context import Context
from vasty.errors import EXIT_CODES, VastyError


def test_exit_codes_are_0_1_and_2() -> None:
    assert set(EXIT_CODES.values()) == {1, 2}
    assert "spend_unavailable" not in EXIT_CODES
    with pytest.raises(ValueError):
        VastyError("spend_unavailable", "x", "y")


def test_parser_error_is_invalid_arguments(harness: Harness) -> None:
    code, out, _ = harness.run("reserve", "--bogus")
    assert code == 1
    assert json.loads(out)["error"] == "invalid_arguments"


def test_json_and_plain_conflict() -> None:
    with pytest.raises(VastyError) as exc:
        parse(["status", "--json", "--plain"])
    assert exc.value.code == "invalid_arguments"


def test_on_rejects_creation_flags() -> None:
    with pytest.raises(VastyError):
        parse(["run", "--on", "ft", "--gpu", "4090", "--", "true"])


def test_run_on_accepts_sync() -> None:
    ns = parse(["run", "--on", "ft", "--sync", ".", "--", "python", "x.py"])
    assert ns.command == ["python", "x.py"]


@pytest.mark.parametrize(
    "argv",
    [
        ["reserve", "--cuda", "13"],
        ["run", "--cuda", "13", "--", "true"],
        ["serve", "--model", "m", "--cuda", "13"],
    ],
)
def test_cuda_flag_parses(argv: list[str]) -> None:
    assert parse(argv).cuda == "13"


def test_on_rejects_cuda() -> None:
    with pytest.raises(VastyError) as exc:
        parse(["serve", "--on", "ft", "--model", "m", "--cuda", "13"])
    assert "--cuda" in exc.value.message


@pytest.mark.parametrize("verb", [["reserve"], ["run", "--", "true"], ["serve", "--model", "m"]])
def test_cuda_flag_rejects_text(harness: Harness, verb: list[str]) -> None:
    argv = [verb[0], "--cuda", "abc", *verb[1:]]
    code, out, _ = harness.run(*argv)
    assert code == 1
    data = json.loads(out)
    assert data["error"] == "invalid_arguments"
    assert "--cuda" in data["message"]
    assert "search_offers" not in [name for name, _ in harness.provider.calls]


def test_auto_reserve_rejects_no_wait() -> None:
    with pytest.raises(VastyError):
        parse(["serve", "--model", "m", "--no-wait"])


def test_config_and_startup_stdin_conflict() -> None:
    with pytest.raises(VastyError):
        parse(["reserve", "--config", "-", "--startup", "-"])


@pytest.mark.parametrize(
    "argv",
    [
        ["release", "ft", "--group", "g"],
        ["release", "--all", "--group", "g"],
        ["release", "--everyone", "--owner", "o"],
        ["release", "--everyone"],
        ["extend", "--everyone", "--by", "30m"],
        ["status", "--everyone", "--owner", "o"],
    ],
)
def test_target_selector_rules(argv: list[str]) -> None:
    with pytest.raises(VastyError):
        parse(argv)


def test_status_everyone_alone_is_allowed() -> None:
    assert parse(["status", "--everyone"]).everyone


def test_everyone_with_group_is_allowed() -> None:
    ns = parse(["release", "--group", "g", "--everyone"])
    assert ns.group == "g" and ns.everyone


@pytest.mark.parametrize(
    ("extra_env", "key_env"), [({}, "VAST_API_KEY"), ({"VASTY_API_KEY_ENV": "MY_KEY"}, "MY_KEY")]
)
def test_status_without_api_key_is_auth_missing(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, extra_env: dict[str, str], key_env: str
) -> None:
    import vasty.provider

    def no_provider(*args: Any, **kw: Any) -> Any:
        raise AssertionError("VastProvider constructed")

    monkeypatch.setattr(vasty.provider, "VastProvider", no_provider)
    for name in ("VAST_API_KEY", "MY_KEY", "VASTY_API_KEY_ENV"):
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


# Sweep entries of a failing command.

FAILED_SWEEP = (
    "vasty: SWEPT  l-0000a009 old  expired 2026-10-29T00:59:50Z  destroy failed (provider_error)"
)


def _fail_next_destroy(harness: Harness) -> None:
    harness.provider.fail["destroy"] = VastyError("provider_error", "boom", "retry")


def test_failing_run_reports_failed_sweep_on_stderr(harness: Harness) -> None:
    add_lease(harness, "l-0000a009", label={"name": "old", "expires": NOW - 10})
    _fail_next_destroy(harness)
    code, out, err = harness.run("run", "--on", "nope", "--", "ls")
    assert code == 1
    assert json.loads(out)["error"] == "lease_not_found"
    assert err.splitlines() == [FAILED_SWEEP]


def test_failing_command_without_sweep_writes_no_stderr(harness: Harness) -> None:
    code, out, err = harness.run("run", "--on", "nope", "--", "ls")
    assert code == 1
    assert json.loads(out)["error"] == "lease_not_found"
    assert err == ""


def test_reserve_wait_error_reports_failed_sweep_on_stderr(harness: Harness) -> None:
    from vasty.models import CreateRequest, Instance

    def lacking(inst: Instance, request: CreateRequest) -> None:
        add_lease(harness, "l-0000a009", label={"name": "old", "expires": NOW - 10})
        harness.box.state(inst.id).unsupported = ["apt-get"]

    harness.provider.offers = [make_offer(1)]
    harness.provider.on_create = lacking
    _fail_next_destroy(harness)
    code, out, err = harness.run("reserve", "--image", "alpine:3")
    assert code == 1
    assert json.loads(out)["error"] == "image_unsupported"
    assert FAILED_SWEEP in err.splitlines()


def test_failing_run_with_closed_stderr_keeps_json_error(harness: Harness) -> None:
    from vasty import cli

    add_lease(harness, "l-0000a009", label={"name": "old", "expires": NOW - 10})
    _fail_next_destroy(harness)
    made: list[Context] = []

    def make(ns: Any) -> Context:
        ctx = harness.context()
        cli.configure(ctx, ns)
        ctx.stderr.close()
        made.append(ctx)
        return ctx

    code = cli.run(["run", "--on", "nope", "--", "ls"], make)
    out = made[0].stdout
    assert isinstance(out, io.StringIO)
    assert code == 1
    assert json.loads(out.getvalue())["error"] == "lease_not_found"


def _walk(parser: argparse.ArgumentParser, path: str) -> list[tuple[str, argparse.Action]]:
    """Return every action under `parser`, recursing into subparsers, with its command path."""
    found: list[tuple[str, argparse.Action]] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for word, child in action.choices.items():
                found += _walk(child, f"{path} {word}")
            continue
        found.append((path, action))
    return found


def test_every_flag_and_positional_has_help() -> None:
    actions = _walk(build_parser(), "vasty")
    paths = {path for path, _ in actions}
    assert {"vasty sync push", "vasty sync pull", "vasty config show", "vasty ssh"} <= paths
    missing = [
        f"{path} {'/'.join(action.option_strings) or action.dest}"
        for path, action in actions
        if not isinstance(action, argparse._HelpAction)
        and action.help != argparse.SUPPRESS
        and not (action.help or "").strip()
    ]
    assert missing == []


def _verb_action(verb: str, flag: str) -> argparse.Action:
    sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    return next(a for a in sub.choices[verb]._actions if flag in a.option_strings)


@pytest.mark.parametrize(
    ("verb", "flag", "words"),
    [
        ("reserve", "--ttl", ["duration", "default: 30m"]),
        ("run", "--ttl", ["duration", "default: run_ttl, 2h"]),
        ("serve", "--ttl", ["duration", "default: run_ttl, 2h"]),
        ("reserve", "--cuda", ["CUDA version", "12.6", "default: none"]),
        ("reserve", "--max-price", ["dollars per hour", "default: 0.60"]),
        ("reserve", "--image", ["default: vastai/base-image:cuda-12.6.3-auto"]),
        ("reserve", "--disk", ["GB", "default: 50"]),
        ("reserve", "--vram", ["GB", "default: any"]),
        ("extend", "--by", ["duration", "default: none"]),
        ("extend", "--until", ["ISO time"]),
    ],
)
def test_help_names_unit_and_default(verb: str, flag: str, words: list[str]) -> None:
    text = _verb_action(verb, flag).help or ""
    for word in words:
        assert word in text


def _help(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    with pytest.raises(SystemExit) as exc:
        main([*argv, "--help"])
    assert exc.value.code == 0
    return capsys.readouterr().out


def test_ssh_help_shows_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert "LEASE [-- COMMAND...]" in _help(capsys, "ssh")


def test_sync_help_shows_direction_and_delete(capsys: pytest.CaptureFixture[str]) -> None:
    text = _help(capsys, "sync")
    assert "push|pull" in text
    assert "SRC DEST" in text
    assert "--delete" in text


def test_version_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out == f"vasty {version('vasty')}\n"
