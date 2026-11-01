from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fakes import Harness

from vasty.cli import VERBS

SRC = Path(__file__).resolve().parent.parent / "src"

CACHE = {
    "leases": {
        "l-00000001": {"state": "running", "label": {"name": "ft", "group": "exp42"}},
        "l-00000002": {"state": "pending", "label": {"name": "eval-0", "group": "exp42"}},
        "l-00000003": {"state": "expired", "label": {"name": "old", "group": "gone-group"}},
        "l-00000004": {"label": {"name": None, "group": 7}},
        "l-00000005": "junk",
    }
}


def write_cache(home: Path, data: object) -> None:
    path = home / ".local" / "state" / "vasty" / "leases.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_completion_prints_raw_script(harness: Harness, shell: str) -> None:
    code, out, _ = harness.run("completion", shell)
    assert code == 0
    assert out.startswith("#")
    for verb in VERBS:
        assert verb in out
    assert "completion --list" in out
    assert "vasty_names leases" in out
    assert "vasty_names groups" in out


def test_completion_json(harness: Harness) -> None:
    code, out, _ = harness.run("completion", "bash", "--json")
    assert code == 0
    data = json.loads(out)
    assert data["shell"] == "bash"
    assert "complete -o default -F _vasty vasty" in data["script"]


def test_completion_needs_shell(harness: Harness) -> None:
    code, out, _ = harness.run("completion")
    assert code == 1
    assert json.loads(out)["error"] == "invalid_arguments"


def test_list_leases_from_cache(harness: Harness) -> None:
    write_cache(harness.home, CACHE)
    code, out, _ = harness.run("completion", "--list", "leases")
    assert code == 0
    assert out.split() == ["eval-0", "ft", "l-00000001", "l-00000002", "l-00000004"]


def test_list_groups_from_cache(harness: Harness) -> None:
    write_cache(harness.home, CACHE)
    code, out, _ = harness.run("completion", "--list", "groups")
    assert code == 0
    assert out.split() == ["exp42"]


@pytest.mark.parametrize("data", ["{not json", "[]", {"leases": []}, {"other": 1}])
def test_list_tolerates_bad_cache(harness: Harness, data: object) -> None:
    write_cache(harness.home, data)
    assert harness.run("completion", "--list", "leases") == (0, "", "")


def test_list_without_cache(harness: Harness) -> None:
    assert harness.run("completion", "--list", "groups") == (0, "", "")


def test_list_profiles(harness: Harness) -> None:
    path = harness.home / ".config" / "vasty" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text("[profiles.small]\ngpu = \"4090\"\n[profiles.big]\ngpu = \"A100\"\n")
    assert harness.run("completion", "--list", "profiles") == (0, "big\nsmall\n", "")


def test_list_profiles_with_bad_config(harness: Harness) -> None:
    path = harness.home / ".config" / "vasty" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text("[defaults]\nbogus = 1\n")
    assert harness.run("completion", "--list", "profiles") == (0, "", "")


def _hostile_profile(harness: Harness, tmp_path: Path) -> Path:
    marker = tmp_path / "pwned"
    path = harness.home / ".config" / "vasty" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(f'[profiles.small]\ngpu = "4090"\n[profiles."$(touch {marker})"]\ngpu = "A100"\n')
    return marker


def test_list_profiles_drops_hostile_names(harness: Harness, tmp_path: Path) -> None:
    _hostile_profile(harness, tmp_path)
    assert harness.run("completion", "--list", "profiles") == (0, "small\n", "")


def test_bash_skips_hostile_profile_names(harness: Harness, tmp_path: Path) -> None:
    marker = _hostile_profile(harness, tmp_path)
    result = _bash_complete(harness, tmp_path, ["vasty", "reserve", "--profile", ""])
    assert result.stdout.split() == ["small"]
    assert not marker.exists()


def _render(harness: Harness, shell: str, tmp_path: Path) -> Path:
    code, out, _ = harness.run("completion", shell)
    assert code == 0
    path = tmp_path / f"vasty.{shell}"
    path.write_text(out)
    return path


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_script_syntax(harness: Harness, tmp_path: Path, shell: str) -> None:
    exe = shutil.which(shell)
    if exe is None:
        pytest.skip(f"{shell} not installed")
    script = _render(harness, shell, tmp_path)
    subprocess.run([exe, "-n", str(script)], check=True)


def test_fish_syntax(harness: Harness, tmp_path: Path) -> None:
    exe = shutil.which("fish")
    if exe is None:
        pytest.skip("fish not installed")
    script = _render(harness, "fish", tmp_path)
    subprocess.run([exe, "--no-execute", str(script)], check=True)


def _clean_env(home: Path) -> dict[str, str]:
    return {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": str(SRC), "USER": "nick"}


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        (["vasty", "st"], ["status", "stop"]),
        (["vasty", "status", ""], ["eval-0", "ft", "l-00000001", "l-00000002", "l-00000004"]),
        (["vasty", "stop", ""], ["eval-0", "ft", "l-00000001", "l-00000002", "l-00000004"]),
        (["vasty", "release", "--group", ""], ["exp42"]),
        (["vasty", "run", "--on", "f"], ["ft"]),
        (["vasty", "sync", "ft", "p"], ["pull", "push"]),
        (["vasty", "config", "s"], ["set", "show"]),
        (["vasty", "completion", "z"], ["zsh"]),
        (["vasty", "extend", "--by", ""], []),
        (["vasty", "tag", "--no"], []),
        (["vasty", "status", "--ca"], ["--cached"]),
    ],
)
def test_bash_completes_from_cache(
    harness: Harness, tmp_path: Path, words: list[str], expected: list[str]
) -> None:
    write_cache(harness.home, CACHE)
    result = _bash_complete(harness, tmp_path, words)
    assert sorted(result.stdout.split()) == sorted(expected)


HOSTILE = {
    "leases": {
        "l-00000001": {"state": "running", "label": {"name": "ft", "group": "exp42"}},
        "l-0$(echo PWNED >&2)": {"state": "running", "label": {}},
        "l-00000002": {"state": "running",
                       "label": {"name": "x y$(echo PWNED >&2)", "group": "`echo PWNED >&2`"}},
        "l-00000003": {"state": "running", "label": {"name": "-n", "group": "a b"}},
    }
}


def test_list_drops_hostile_values(harness: Harness) -> None:
    write_cache(harness.home, HOSTILE)
    assert harness.run("completion", "--list", "leases") == (
        0, "ft\nl-00000001\nl-00000002\nl-00000003\n", "")
    assert harness.run("completion", "--list", "groups") == (0, "exp42\n", "")


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        (["vasty", "status", ""], ["ft", "l-00000001", "l-00000002", "l-00000003"]),
        (["vasty", "release", "--group", ""], ["exp42"]),
    ],
)
def test_bash_skips_hostile_names(
    harness: Harness, tmp_path: Path, words: list[str], expected: list[str]
) -> None:
    write_cache(harness.home, HOSTILE)
    result = _bash_complete(harness, tmp_path, words)
    assert "PWNED" not in result.stderr
    assert sorted(result.stdout.split()) == sorted(expected)


def _bash_complete(harness: Harness, tmp_path: Path,
                   words: list[str]) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not installed")
    script = _render(harness, "bash", tmp_path)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    vasty = bindir / "vasty"
    vasty.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m vasty "$@"\n')
    vasty.chmod(0o755)
    env = _clean_env(harness.home)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    quoted = " ".join("'" + w + "'" for w in words)
    program = (
        f"source '{script}'\n"
        f"COMP_WORDS=({quoted}); COMP_CWORD={len(words) - 1}\n"
        "_vasty\n"
        'printf "%s\\n" "${COMPREPLY[@]}"\n'
    )
    return subprocess.run([bash, "--norc", "--noprofile", "-c", program], env=env,
                          capture_output=True, text=True, check=True)


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        (["vasty", ""], list(VERBS)),
        (["vasty", "status", ""], ["eval-0", "ft", "l-00000001", "l-00000002", "l-00000004"]),
        (["vasty", "stop", ""], ["eval-0", "ft", "l-00000001", "l-00000002", "l-00000004"]),
        (["vasty", "release", "--group", ""], ["exp42"]),
        (["vasty", "sync", "ft", ""], ["push", "pull"]),
        (["vasty", "reserve", "--startup", ""], ["FILES"]),
        (["vasty", "extend", "--by", ""], []),
        (["vasty", "sweep", "--follow", ""], ["eval-0", "ft", "l-00000001", "l-00000002", "l-00000004"]),
    ],
)
def test_zsh_completes_from_cache(
    harness: Harness, tmp_path: Path, words: list[str], expected: list[str]
) -> None:
    zsh = shutil.which("zsh")
    if zsh is None:
        pytest.skip("zsh not installed")
    write_cache(harness.home, CACHE)
    script = _render(harness, "zsh", tmp_path)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    vasty = bindir / "vasty"
    vasty.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m vasty "$@"\n')
    vasty.chmod(0o755)
    env = _clean_env(harness.home)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    quoted = " ".join("'" + w + "'" for w in words)
    program = (
        "compadd() { [[ $1 == -a ]] && print -l ${(P)2} }\n"
        "_files() { print FILES }\n"
        "compdef() { : }\n"
        f"source '{script}'\n"
        f"words=({quoted}); CURRENT={len(words)}\n"
        "_vasty\n"
    )
    result = subprocess.run([zsh, "-f", "-c", program], env=env,
                            capture_output=True, text=True, check=False)
    assert sorted(result.stdout.split()) == sorted(expected)


PROBE = """
import json, sys
before = set(sys.modules)
from vasty.cli import main
code = main(sys.argv[1:])
loaded = set(sys.modules) - before
third_party = sorted(
    m for m in loaded
    if m.split(".")[0] not in sys.stdlib_module_names and m.split(".")[0] != "vasty"
)
print(json.dumps({"code": code, "vastai": "vastai" in sys.modules, "third_party": third_party}),
      file=sys.stderr)
"""


@pytest.mark.parametrize(
    "argv",
    [
        ["config", "show", "--json"],
        ["completion", "bash"],
        ["completion", "zsh"],
        ["completion", "fish"],
        ["completion", "--list", "leases"],
    ],
)
def test_stdlib_only_imports(tmp_path: Path, argv: list[str]) -> None:
    write_cache(tmp_path, CACHE)
    result = subprocess.run([sys.executable, "-c", PROBE, *argv], env=_clean_env(tmp_path),
                            cwd=tmp_path, capture_output=True, text=True, check=True)
    report = json.loads(result.stderr.strip().splitlines()[-1])
    assert report == {"code": 0, "vastai": False, "third_party": []}
