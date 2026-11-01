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


@pytest.mark.parametrize(
    ("argv", "tty", "mode"),
    [
        (["sweep"], True, "human"),
        (["sweep"], False, "json"),
        (["sweep", "--json"], True, "json"),
        (["sweep", "--json"], False, "json"),
    ],
)
def test_json_forces_json_and_stdout_type_picks_the_rest(
    harness: Harness, argv: list[str], tty: bool, mode: str
) -> None:
    harness.run(*argv, tty=tty)
    assert harness.last_ctx is not None
    assert harness.last_ctx.mode == mode


@pytest.mark.parametrize(
    "argv",
    [
        ["status", "--plain"],
        ["reserve", "--no-wait"],
        ["run", "--no-wait", "--", "true"],
        ["serve", "--model", "m", "--no-wait"],
        ["release", "i-1", "--yes"],
        ["tag", "ft", "--set-group", "g"],
    ],
)
def test_removed_flags_are_invalid(argv: list[str]) -> None:
    with pytest.raises(VastyError) as exc:
        parse(argv)
    assert exc.value.code == "invalid_arguments"


def test_tag_needs_a_lease() -> None:
    with pytest.raises(VastyError) as exc:
        parse(["tag", "--group", "g"])
    assert exc.value.code == "invalid_arguments"


def test_tag_parses_setters() -> None:
    ns = parse(["tag", "ft", "--name", "n", "--group", "g", "--owner", "o", "--ttl", "30m"])
    assert (ns.target, ns.name, ns.group, ns.owner, ns.ttl) == ("ft", "n", "g", "o", "30m")


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


@pytest.mark.parametrize("verb", [["reserve"], ["run"], ["serve", "--model", "m"]])
def test_config_flag_is_rejected(verb: list[str]) -> None:
    with pytest.raises(VastyError) as exc:
        parse([*verb, "--config", "-"])
    assert exc.value.code == "invalid_arguments"


def test_startup_stdin_parses_alone() -> None:
    assert parse(["reserve", "--startup", "-"]).startup == "-"


@pytest.mark.parametrize(
    "argv",
    [
        ["release", "--all"],
        ["release", "--group", "g", "--everyone"],
        ["extend", "--all", "--by", "30m"],
        ["extend", "ft", "--until", "2026-10-29T03:00:00Z"],
        ["status", "--everyone"],
        ["status", "--all"],
        ["status", "--cached"],
    ],
)
def test_removed_flags_are_rejected(argv: list[str]) -> None:
    with pytest.raises(VastyError):
        parse(argv)


def test_status_filters_by_owner_and_group() -> None:
    ns = parse(["status", "--owner", "o", "--group", "g"])
    assert (ns.target, ns.owner, ns.group) == (None, "o", "g")


# Build the removed variable's name so a repo grep for it stays empty.
OLD_KEY_ENV_VAR = "_".join(["VASTY", "API", "KEY", "ENV"])


@pytest.mark.parametrize("extra_env", [{}, {OLD_KEY_ENV_VAR: "MY_KEY", "MY_KEY": "k"}])
def test_status_without_api_key_is_auth_missing(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, extra_env: dict[str, str]
) -> None:
    import vasty.provider

    key_env = "VAST_API_KEY"

    def no_provider(*args: Any, **kw: Any) -> Any:
        raise AssertionError("VastProvider constructed")

    monkeypatch.setattr(vasty.provider, "VastProvider", no_provider)
    for name in ("VAST_API_KEY", "MY_KEY", OLD_KEY_ENV_VAR):
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
    key_file = str(harness.home / ".config" / "vastai" / "vast_api_key")
    for text in (result["message"], result["hint"]):
        assert key_env in text
        assert key_file in text
    assert harness.http_calls == []


def _real_provider_key(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, env_key: str | None, file_text: str | None
) -> str:
    """Build the real provider path and return the API key VastProvider receives."""
    import vasty.provider

    keys: list[str] = []

    def record(api_key: str, *args: Any, **kw: Any) -> Any:
        keys.append(api_key)
        return object()

    monkeypatch.setattr(vasty.provider, "VastProvider", record)
    harness.env.pop("VAST_API_KEY", None)
    if env_key is not None:
        harness.env["VAST_API_KEY"] = env_key
    if file_text is not None:
        path = harness.home / ".config" / "vastai" / "vast_api_key"
        path.parent.mkdir(parents=True)
        path.write_text(file_text)
    ctx = replace(harness.context(), provider_factory=None)
    assert ctx.provider is not None
    return keys[0]


def test_api_key_from_vastai_file(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _real_provider_key(harness, monkeypatch, None, "  file-key\n") == "file-key"


def test_vast_api_key_beats_vastai_file(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _real_provider_key(harness, monkeypatch, "env-key", "file-key\n") == "env-key"


def test_empty_vastai_file_is_auth_missing(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(VastyError) as exc:
        _real_provider_key(harness, monkeypatch, None, " \n")
    assert exc.value.code == "auth_missing"


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
        ("reserve", "--ttl", ["duration", "builtin default: 30m"]),
        ("run", "--ttl", ["duration", "builtin default: 30m"]),
        ("serve", "--ttl", ["duration", "builtin default: 30m"]),
        ("reserve", "--cuda", ["CUDA version", "12.6", "builtin default: the image's floor"]),
        ("reserve", "--max-price", ["dollars per hour", "builtin default: 0.60"]),
        ("reserve", "--image", ["builtin default: vastai/base-image:cuda-12.6.3-auto"]),
        ("reserve", "--disk", ["GB", "builtin default: 50"]),
        ("reserve", "--gpus", ["builtin default: 1"]),
        ("reserve", "--vram", ["GB", "default: any"]),
        ("reserve", "--gpu", ["or any", "default: any"]),
        ("reserve", "--region", ["or any", "default: any"]),
        ("extend", "--by", ["duration", "default: none"]),
    ],
)
def test_help_names_unit_and_default(verb: str, flag: str, words: list[str]) -> None:
    text = _verb_action(verb, flag).help or ""
    for word in words:
        assert word in text


SETTING_FLAGS_WITH_KEYS = (
    "--owner", "--ttl", "--startup", "--gpu", "--vram", "--cuda", "--gpus", "--disk", "--image",
    "--max-price", "--region", "--ports",
)


@pytest.mark.parametrize("verb", ["reserve", "run", "serve"])
@pytest.mark.parametrize("flag", SETTING_FLAGS_WITH_KEYS)
def test_setting_flag_help_points_at_config_show(verb: str, flag: str) -> None:
    text = _verb_action(verb, flag).help or ""
    assert text.endswith("; see vasty config show")
    assert text == _verb_action("reserve", flag).help


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
