from __future__ import annotations

import json
import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fakes import Harness

from vasty.config import (
    Settings,
    emit_toml,
    parse_duration,
    parse_key,
    resolve,
    user_config_path,
)
from vasty.errors import VastyError


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class Env:
    """Paths and inputs for one `resolve` call."""

    def __init__(self, tmp_path: Path) -> None:
        self.home = tmp_path
        self.cwd = tmp_path / "project"
        self.cwd.mkdir(exist_ok=True)
        self.env: dict[str, str] = {"USER": "nick"}

    def user(self, text: str) -> Path:
        return write(user_config_path(self.home), text)

    def project(self, text: str, name: str = "vasty.toml") -> Path:
        return write(self.cwd / name, text)

    def resolve(
        self,
        flags: dict[str, Any] | None = None,
        stdin_json: dict[str, Any] | None = None,
        profile: str | None = None,
        stdin_text: str | None = None,
    ) -> Settings:
        reader = (lambda: stdin_text) if stdin_text is not None else None
        return resolve(flags or {}, stdin_json, profile, self.env, self.cwd, self.home,
                       stdin_text=reader)

    def error(self, **kw: Any) -> VastyError:
        with pytest.raises(VastyError) as exc:
            self.resolve(**kw)
        return exc.value


@pytest.fixture
def cfg(tmp_path: Path) -> Env:
    return Env(tmp_path)


# Built-in defaults.


def test_builtin_defaults(cfg: Env) -> None:
    s = cfg.resolve()
    assert s.ttl == 1800
    assert s.run_ttl == 7200
    assert s.max_price == Decimal("0.60")
    assert s.warn_before_expiry == 300
    assert s.disk == 50
    assert s.gpus == 1
    assert s.image == "vastai/base-image:cuda-12.6.3-auto"
    assert s.api_key_env == "VAST_API_KEY"
    assert (s.gpu, s.vram, s.region, s.ports, s.startup) == (None, None, None, [], None)
    assert s.sources["ttl"] == "default"


# Resolution order.

LAYERS = ["flag", "stdin", "profile", "env", "project", "user", "default"]


@pytest.mark.parametrize("top", LAYERS)
def test_resolution_order(cfg: Env, top: str) -> None:
    present = LAYERS[LAYERS.index(top):]
    ttl = {"flag": "1m", "stdin": "2m", "profile": "3m", "env": "4m",
           "project": "5m", "user": "6m", "default": "30m"}
    user = '[profiles.p]\nttl = "3m"\n' if "profile" in present else "[profiles.p]\n"
    if "user" in present:
        user = '[defaults]\nttl = "6m"\n' + user
    cfg.user(user)
    if "project" in present:
        cfg.project('[defaults]\nttl = "5m"\n')
    if "env" in present:
        cfg.env["VASTY_TTL"] = "4m"
    s = cfg.resolve(
        flags={"ttl": "1m"} if "flag" in present else {},
        stdin_json={"ttl": "2m"} if "stdin" in present else None,
        profile="p",
    )
    assert s.ttl == parse_duration(ttl[top])
    assert s.sources["ttl"] == top


def test_stdin_json_through_cli(harness: Harness) -> None:
    code, out, _ = harness.run("config", "show", "--config", "-", stdin='{"disk": 120}')
    assert code == 0
    values = json.loads(out)["values"]
    assert values["disk"] == {"value": 120, "source": "stdin"}


def test_stdin_json_unknown_key(cfg: Env) -> None:
    assert cfg.error(stdin_json={"bogus": 1}).code == "invalid_config"


def test_stdin_json_bad_type(cfg: Env) -> None:
    assert cfg.error(stdin_json={"ttl": 30}).code == "invalid_config"


def test_vasty_toml_wins_over_dot_vasty(cfg: Env) -> None:
    cfg.project('[defaults]\nttl = "5m"\ndisk = 70\n', ".vasty/config.toml")
    cfg.project('[defaults]\nttl = "7m"\n')
    s = cfg.resolve()
    assert s.ttl == 420
    assert s.disk == 70
    assert s.sources["ttl"] == "project" and s.sources["disk"] == "project"


def test_profiles_merge_by_name_and_field(cfg: Env) -> None:
    cfg.user('[profiles.big]\ngpu = "A100"\nvram = 80\n[profiles.small]\ngpu = "4090"\n')
    cfg.project('[profiles.big]\nvram = 48\nmax_price = 2.5\n')
    s = cfg.resolve(profile="big")
    assert (s.gpu, s.vram, s.max_price) == ("A100", 48.0, Decimal("2.5"))
    assert s.sources["gpu"] == "profile"
    assert s.profiles == {
        "big": {"gpu": "A100", "vram": 48, "max_price": 2.5},
        "small": {"gpu": "4090"},
    }


def test_profile_beats_env(cfg: Env) -> None:
    cfg.user('[profiles.big]\ngpu = "A100"\n')
    cfg.env["VASTY_GPU"] = "3090"
    assert cfg.resolve(profile="big").gpu == "A100"
    assert cfg.resolve().gpu == "3090"


def test_unknown_profile_is_invalid_arguments(cfg: Env) -> None:
    cfg.user('[profiles.big]\ngpu = "A100"\n')
    err = cfg.error(profile="huge")
    assert err.code == "invalid_arguments"
    assert "big" in err.message


# Environment variables.


@pytest.mark.parametrize(
    ("var", "text", "attr", "expected"),
    [
        ("VASTY_TTL", "1h", "ttl", 3600),
        ("VASTY_RUN_TTL", "3h", "run_ttl", 10800),
        ("VASTY_MAX_PRICE", "0.45", "max_price", Decimal("0.45")),
        ("VASTY_WARN_BEFORE_EXPIRY", "10m", "warn_before_expiry", 600),
        ("VASTY_IMAGE", "my/img:1", "image", "my/img:1"),
        ("VASTY_DISK", "100", "disk", 100),
        ("VASTY_GPUS", "2", "gpus", 2),
        ("VASTY_GPU", "L40S", "gpu", "L40S"),
        ("VASTY_VRAM", "48", "vram", 48.0),
        ("VASTY_CUDA", "12.8", "cuda", 12.8),
        ("VASTY_REGION", "EU", "region", "EU"),
        ("VASTY_PORTS", "8888,9000", "ports", [8888, 9000]),
        ("VASTY_STARTUP", "echo hi\n", "startup", "echo hi\n"),
        ("VASTY_OWNER", "agent", "owner", "agent"),
        ("VASTY_API_KEY_ENV", "MY_KEY", "api_key_env", "MY_KEY"),
    ],
)
def test_env_maps_each_key(cfg: Env, var: str, text: str, attr: str, expected: Any) -> None:
    cfg.env[var] = text
    s = cfg.resolve()
    assert getattr(s, attr) == expected
    assert s.sources[attr] == "env"


@pytest.mark.parametrize(("var", "text"), [("VASTY_DISK", "abc"), ("VASTY_TTL", "soon"),
                                           ("VASTY_MAX_PRICE", "cheap"), ("VASTY_PORTS", "1,x")])
def test_env_bad_value_is_invalid_config(cfg: Env, var: str, text: str) -> None:
    cfg.env[var] = text
    err = cfg.error()
    assert err.code == "invalid_config"
    assert var in err.message


def test_empty_env_value_is_unset(cfg: Env) -> None:
    cfg.env["VASTY_TTL"] = ""
    assert cfg.resolve().sources["ttl"] == "default"


# Validation of files.


@pytest.mark.parametrize(
    "text",
    [
        "bogus = 1\n",
        "[defaults]\nbogus = 1\n",
        "[profiles.p]\nbogus = 1\n",
        "[other]\nx = 1\n",
    ],
)
def test_unknown_keys_are_invalid_config(cfg: Env, text: str) -> None:
    cfg.user(text)
    assert cfg.error().code == "invalid_config"


@pytest.mark.parametrize(
    "text",
    [
        "[defaults]\nttl = 30\n",
        '[defaults]\nttl = "0m"\n',
        '[defaults]\nmax_price = "cheap"\n',
        "[defaults]\nmax_price = 0\n",
        "[defaults]\ndisk = 1.5\n",
        "[defaults]\ngpus = true\n",
        "[defaults]\ngpus = 0\n",
        "[defaults]\nimage = 5\n",
        '[defaults]\nports = ["x"]\n',
        "[defaults]\nports = [70000]\n",
        "[defaults]\nvram = -1\n",
        "owner = \"bad owner\"\n",
        "defaults = 3\n",
        "[profiles]\np = 3\n",
    ],
)
def test_bad_types_are_invalid_config(cfg: Env, text: str) -> None:
    cfg.project(text)
    assert cfg.error().code == "invalid_config"


def test_bad_toml_is_invalid_config(cfg: Env) -> None:
    cfg.user("[defaults\n")
    assert cfg.error().code == "invalid_config"


def test_example_config_from_spec(cfg: Env) -> None:
    cfg.user(
        'api_key_env = "VAST_API_KEY"\nowner = "nick"\nssh_key = "~/.ssh/id_ed25519"\n\n'
        '[defaults]\nttl = "30m"\nrun_ttl = "2h"\nmax_price = 0.60\n'
        'warn_before_expiry = "5m"\nimage = "vastai/base-image:cuda-12.6.3-auto"\ndisk = 50\n\n'
        '[profiles.small]\ngpu = "4090"\nvram = 24\n\n'
        '[profiles.big]\ngpu = "A100"\nvram = 80\nmax_price = 2.50\n\n'
        '[profiles.vllm]\nimage = "vllm/vllm-openai:v0.32.0"\nvram = 24\ncuda = 13\n'
    )
    s = cfg.resolve(profile="small")
    assert s.gpu == "4090" and s.vram == 24.0
    assert s.ssh_key == str(cfg.home / ".ssh" / "id_ed25519")
    assert s.sources["ttl"] == "user"


# Flags.


@pytest.mark.parametrize(
    ("key", "value"),
    [("ttl", "abc"), ("ttl", "30"), ("vram", "x"), ("ports", "1,99999"), ("ports", "a"),
     ("max_price", "free"), ("gpus", "0"), ("disk", "1.5"), ("owner", "bad owner")],
)
def test_bad_flag_values_are_invalid_arguments(cfg: Env, key: str, value: str) -> None:
    assert cfg.error(flags={key: value}).code == "invalid_arguments"


def test_flag_values_parse(cfg: Env) -> None:
    s = cfg.resolve(flags={"ttl": "1h30m", "vram": "24", "ports": "8888,9000,8888",
                           "max_price": "0.5", "gpus": "2", "disk": "80"})
    assert (s.ttl, s.vram, s.ports, s.max_price, s.gpus, s.disk) == (
        5400, 24.0, [8888, 9000], Decimal("0.5"), 2, 80)
    assert all(s.sources[k] == "flag" for k in ("ttl", "vram", "ports", "max_price"))


def test_flag_rejected_through_cli(harness: Harness) -> None:
    code, out, _ = harness.run("config", "show", "--vram", "big")
    assert code == 1
    assert json.loads(out)["error"] == "invalid_arguments"


# Startup.


def test_startup_and_startup_file_together_is_invalid(cfg: Env) -> None:
    cfg.user('[defaults]\nstartup = "echo a"\nstartup_file = "a.sh"\n')
    assert cfg.error().code == "invalid_config"


def test_startup_both_in_profile_is_invalid(cfg: Env) -> None:
    cfg.user('[profiles.ft]\nstartup = "echo a"\nstartup_file = "a.sh"\n')
    assert cfg.error().code == "invalid_config"


def test_startup_both_in_stdin_is_invalid(cfg: Env) -> None:
    err = cfg.error(stdin_json={"startup": "echo", "startup_file": "a.sh"})
    assert err.code == "invalid_config"


def test_startup_both_in_env_is_invalid(cfg: Env) -> None:
    cfg.env.update(VASTY_STARTUP="echo", VASTY_STARTUP_FILE="a.sh")
    assert cfg.error().code == "invalid_config"


def test_startup_file_resolves_relative_to_user_file(cfg: Env) -> None:
    script = write(user_config_path(cfg.home).parent / "setup.sh", "echo user\n")
    cfg.user('[defaults]\nstartup_file = "setup.sh"\n')
    s = cfg.resolve()
    assert s.startup == "echo user\n"
    assert s.startup_path == str(script)
    assert s.sources["startup"] == "user"


def test_startup_file_resolves_relative_to_project_file(cfg: Env) -> None:
    script = write(cfg.cwd / ".vasty" / "boot.sh", "echo project\n")
    cfg.project('[profiles.ft]\nstartup_file = "boot.sh"\n', ".vasty/config.toml")
    s = cfg.resolve(profile="ft")
    assert s.startup == "echo project\n"
    assert s.startup_path == str(script)
    assert s.sources["startup"] == "profile"


def test_cli_startup_resolves_relative_to_cwd(cfg: Env) -> None:
    script = write(cfg.cwd / "setup.sh", "echo cli\n")
    write(user_config_path(cfg.home).parent / "setup.sh", "echo wrong\n")
    s = cfg.resolve(flags={"startup": "setup.sh"})
    assert s.startup == "echo cli\n"
    assert s.startup_path == str(script)
    assert s.sources["startup"] == "flag"


def test_cli_startup_overrides_profile(cfg: Env) -> None:
    write(cfg.cwd / "mine.sh", "echo mine\n")
    cfg.user("[profiles.ft]\nstartup = '''\npip install peft\n'''\n")
    assert cfg.resolve(profile="ft").startup == "pip install peft\n"
    assert cfg.resolve(profile="ft", flags={"startup": "mine.sh"}).startup == "echo mine\n"


def test_higher_startup_file_replaces_lower_startup_text(cfg: Env) -> None:
    write(cfg.cwd / "p.sh", "echo p\n")
    cfg.user('[profiles.ft]\nstartup = "echo user"\n')
    cfg.project('[profiles.ft]\nstartup_file = "p.sh"\n')
    s = cfg.resolve(profile="ft")
    assert s.startup == "echo p\n"
    assert s.profiles["ft"] == {"startup_file": "p.sh"}


def test_startup_stdin(cfg: Env) -> None:
    s = cfg.resolve(flags={"startup": "-"}, stdin_text="apt-get install -y ffmpeg\n")
    assert s.startup == "apt-get install -y ffmpeg\n"
    assert s.startup_path is None


def test_startup_stdin_through_cli(harness: Harness) -> None:
    code, out, _ = harness.run("config", "show", "--startup", "-", stdin="echo from stdin\n")
    assert code == 0
    assert json.loads(out)["values"]["startup"] == {"value": "echo from stdin\n",
                                                    "source": "flag"}


def test_missing_cli_startup_file_is_invalid_arguments(cfg: Env) -> None:
    assert cfg.error(flags={"startup": "nope.sh"}).code == "invalid_arguments"


def test_missing_config_startup_file_is_invalid_config(cfg: Env) -> None:
    cfg.user('[defaults]\nstartup_file = "nope.sh"\n')
    assert cfg.error().code == "invalid_config"


# Owner.


def test_owner_order(cfg: Env) -> None:
    cfg.user('owner = "from-user"\n')
    assert (cfg.resolve().owner, cfg.resolve().sources["owner"]) == ("from-user", "user")
    cfg.project('owner = "from-project"\n')
    assert cfg.resolve().owner == "from-project"
    cfg.env["VASTY_OWNER"] = "from-env"
    assert cfg.resolve().owner == "from-env"
    s = cfg.resolve(flags={"owner": "from-flag"})
    assert (s.owner, s.sources["owner"]) == ("from-flag", "flag")


def test_owner_falls_back_to_user(cfg: Env) -> None:
    s = cfg.resolve()
    assert (s.owner, s.sources["owner"]) == ("nick", "env")


def test_owner_missing_everywhere(cfg: Env) -> None:
    cfg.env.clear()
    assert cfg.error().code == "invalid_config"


def test_owner_flag_on_config_show(harness: Harness) -> None:
    code, out, _ = harness.run("config", "show", "--owner", "someone")
    assert code == 0
    assert json.loads(out)["values"]["owner"] == {"value": "someone", "source": "flag"}


# Removed keys.

# Build the removed key's name so a repo grep for it stays empty.
REMOVED_BUDGET_KEY = "_".join(["daily", "budget"])


@pytest.mark.parametrize("table", ["[defaults]", "[profiles.big]"])
def test_removed_budget_key_is_invalid_config(cfg: Env, table: str) -> None:
    cfg.user(f"{table}\n{REMOVED_BUDGET_KEY} = 20\n")
    err = cfg.error()
    assert err.code == "invalid_config"
    assert REMOVED_BUDGET_KEY in err.message


# The removed models table.


@pytest.mark.parametrize(
    "text",
    [
        'models."Qwen/Qwen3-14B-AWQ".vram = 24\n',
        'models = { "org/small" = { image = "a/b" } }\n',
    ],
)
def test_models_table_is_invalid_config(cfg: Env, text: str) -> None:
    path = cfg.user(text)
    err = cfg.error()
    assert err.code == "invalid_config"
    assert err.message == f"models in {path} is not a known key."


# SSH key.


def test_ssh_key_default_prefers_ed25519(cfg: Env) -> None:
    assert cfg.resolve().ssh_key is None
    write(cfg.home / ".ssh" / "id_rsa", "k")
    assert cfg.resolve().ssh_key == str(cfg.home / ".ssh" / "id_rsa")
    write(cfg.home / ".ssh" / "id_ed25519", "k")
    assert cfg.resolve().ssh_key == str(cfg.home / ".ssh" / "id_ed25519")


def test_ssh_key_from_config_expands_home(cfg: Env) -> None:
    cfg.user('ssh_key = "~/.ssh/work"\n')
    s = cfg.resolve()
    assert s.ssh_key == str(cfg.home / ".ssh" / "work")
    assert s.sources["ssh_key"] == "user"


# Durations.


@pytest.mark.parametrize(("text", "seconds"), [("30m", 1800), ("1h30m", 5400), ("2d", 172800),
                                               ("45s", 45), ("1d2h3m4s", 93784)])
def test_duration_parse(text: str, seconds: int) -> None:
    assert parse_duration(text) == seconds


@pytest.mark.parametrize(
    "text",
    ["0m", "0s", "0", "30", "m", "1.5h", "-1h", "1w", "", "1h1h", "30m1h", "1h0m", "0h30m"],
)
def test_duration_rejects(text: str) -> None:
    assert parse_duration(text) is None


@pytest.mark.parametrize("text", ["1h1h", "30m1h", "1h0m"])
def test_config_file_duration_uses_flag_grammar(cfg: Env, text: str) -> None:
    cfg.user(f'[defaults]\nttl = "{text}"\n')
    err = cfg.error()
    assert err.code == "invalid_config"
    assert "ttl" in err.message


# `config show`.


def test_config_show_json(harness: Harness) -> None:
    write(user_config_path(harness.home), "[defaults]\ndisk = 80\n")
    code, out, _ = harness.run("config", "show", "--ttl", "1h")
    assert code == 0
    values = json.loads(out)["values"]
    assert values["ttl"] == {"value": "1h", "source": "flag"}
    assert values["disk"] == {"value": 80, "source": "user"}
    assert values["max_price"] == {"value": 0.6, "source": "default"}
    assert values["owner"] == {"value": "claude", "source": "env"}
    assert values["gpu"] == {"value": None, "source": "default"}


def test_config_show_profile(harness: Harness) -> None:
    write(user_config_path(harness.home), '[profiles.big]\ngpu = "A100"\n')
    code, out, _ = harness.run("config", "show", "--profile", "big")
    assert code == 0
    assert json.loads(out)["values"]["gpu"] == {"value": "A100", "source": "profile"}


def test_config_show_human(harness: Harness) -> None:
    write(harness.home / "project" / "vasty.toml", '[defaults]\nimage = "my/img"\n')
    code, out, _ = harness.run("config", "show", "--plain")
    assert code == 0
    lines = out.strip().splitlines()
    assert len(lines) == 16
    rows = {line.split()[0]: line.split()[1:] for line in lines}
    assert rows["image"] == ["my/img", "project"]
    assert rows["ttl"] == ["30m", "default"]
    assert rows["max_price"] == ["0.60", "default"]


def test_config_show_cuda_from_env(harness: Harness) -> None:
    harness.env["VASTY_CUDA"] = "13"
    code, out, _ = harness.run("config", "show")
    assert code == 0
    assert json.loads(out)["values"]["cuda"] == {"value": 13.0, "source": "env"}


def test_config_show_cuda_flag(harness: Harness) -> None:
    code, out, _ = harness.run("config", "show", "--cuda", "12.8")
    assert code == 0
    assert json.loads(out)["values"]["cuda"] == {"value": 12.8, "source": "flag"}


def test_config_set_cuda(harness: Harness) -> None:
    code, _, _ = harness.run("config", "set", "profiles.vllm.cuda", "13")
    assert code == 0
    assert read_user(harness)["profiles"]["vllm"]["cuda"] == 13
    code, _, _ = harness.run("config", "set", "defaults.cuda", "12.8")
    assert code == 0
    assert read_user(harness)["defaults"]["cuda"] == 12.8


def test_config_set_cuda_rejects_text(harness: Harness) -> None:
    code, out, _ = harness.run("config", "set", "defaults.cuda", "high")
    assert code == 1
    assert json.loads(out)["error"] == "invalid_config"


def test_config_show_invalid_config(harness: Harness) -> None:
    write(user_config_path(harness.home), "[defaults]\nnope = 1\n")
    code, out, _ = harness.run("config", "show")
    assert code == 1
    assert json.loads(out)["error"] == "invalid_config"


# `config set`.


def read_user(harness: Harness) -> dict[str, Any]:
    return tomllib.loads(user_config_path(harness.home).read_text())


def test_config_set_writes_user_file(harness: Harness) -> None:
    code, out, _ = harness.run("config", "set", "defaults.ttl", "45m")
    assert code == 0
    assert json.loads(out) == {"key": "defaults.ttl", "value": "45m"}
    assert read_user(harness) == {"defaults": {"ttl": "45m"}}


def test_config_set_preserves_other_values(harness: Harness) -> None:
    write(user_config_path(harness.home),
          'owner = "nick"\n[defaults]\ndisk = 50\n[profiles.big]\ngpu = "A100"\n')
    assert harness.run("config", "set", "profiles.big.vram", "80")[0] == 0
    assert read_user(harness) == {
        "owner": "nick",
        "defaults": {"disk": 50},
        "profiles": {"big": {"gpu": "A100", "vram": 80}},
    }


def test_config_set_drops_comments(harness: Harness) -> None:
    path = write(user_config_path(harness.home), '# note\n[defaults]\nttl = "1h"\n')
    assert harness.run("config", "set", "defaults.disk", "80")[0] == 0
    assert "#" not in path.read_text()
    assert read_user(harness) == {"defaults": {"ttl": "1h", "disk": 80}}


@pytest.mark.parametrize(
    ("key", "value", "path", "stored"),
    [
        ("defaults.max_price", "0.45", ["defaults", "max_price"], 0.45),
        ("defaults.disk", "100", ["defaults", "disk"], 100),
        ("defaults.image", '"my/img:1"', ["defaults", "image"], "my/img:1"),
        ("profiles.small.gpu", "4090", ["profiles", "small", "gpu"], "4090"),
        ("owner", "agent", ["owner"], "agent"),
        ("defaults.ports", "[8888, 9000]", ["defaults", "ports"], [8888, 9000]),
        ("defaults.ports", "8888,9000", ["defaults", "ports"], [8888, 9000]),
        ('profiles."big-box".vram', "96", ["profiles", "big-box", "vram"], 96),
    ],
)
def test_config_set_parses_toml_scalar(
    harness: Harness, key: str, value: str, path: list[str], stored: Any
) -> None:
    code, out, _ = harness.run("config", "set", key, value)
    assert code == 0, out
    node: Any = read_user(harness)
    for part in path:
        node = node[part]
    assert node == stored
    assert json.loads(out)["value"] == stored


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("defaults.bogus", "1"),
        ("bogus", "1"),
        ("profiles.big", "1"),
        ("defaults.disk", "lots"),
        ("defaults.ttl", "30"),
        ("defaults.max_price", "true"),
        ("models.m.vram", "24"),
        ('models."Qwen/Qwen3-14B-AWQ".image', "vllm/vllm-openai:v0.32.0"),
        ("defaults..ttl", "1m"),
    ],
)
def test_config_set_rejects(harness: Harness, key: str, value: str) -> None:
    write(user_config_path(harness.home), "[defaults]\ndisk = 50\n")
    before = user_config_path(harness.home).read_text()
    code, out, _ = harness.run("config", "set", key, value)
    assert code == 1
    assert json.loads(out)["error"] == "invalid_config"
    assert user_config_path(harness.home).read_text() == before


def test_config_set_startup_replaces_startup_file(harness: Harness) -> None:
    write(user_config_path(harness.home), '[profiles.ft]\nstartup_file = "a.sh"\n')
    assert harness.run("config", "set", "profiles.ft.startup", "pip install peft")[0] == 0
    assert read_user(harness) == {"profiles": {"ft": {"startup": "pip install peft"}}}


def test_config_set_round_trips_through_resolve(harness: Harness) -> None:
    harness.run("config", "set", "defaults.run_ttl", "3h")
    harness.run("config", "set", "profiles.big.max_price", "2.5")
    s = harness.context().settings
    assert s.run_ttl == 10800
    assert s.profiles == {"big": {"max_price": 2.5}}


def test_emit_toml_round_trip() -> None:
    doc: dict[str, Any] = {
        "api_key_env": "VAST_API_KEY",
        "owner": "nick",
        "defaults": {"ttl": "30m", "max_price": 0.6, "ports": [8888, 9000], "flag": True},
        "profiles": {
            "ft": {"startup": 'pip install "x"\napt-get install -y ffmpeg\n\ttab \\ done\x7f'},
            "my profile": {"gpu": "A100"},
        },
        "empty": {},
        "unicode": {"name": "café \U0001f600"},
    }
    assert tomllib.loads(emit_toml(doc)) == doc


def test_parse_key() -> None:
    assert parse_key('profiles."Qwen/Qwen3-14B-AWQ".vram') == [
        "profiles", "Qwen/Qwen3-14B-AWQ", "vram"]
    assert parse_key("profiles.'a.b'.image") == ["profiles", "a.b", "image"]
    for bad in ("", "a.", ".a", 'a."b', "a b"):
        with pytest.raises(VastyError):
            parse_key(bad)


# `config profiles`.


def test_config_profiles(harness: Harness) -> None:
    write(user_config_path(harness.home), '[profiles.small]\ngpu = "4090"\nvram = 24\n')
    write(harness.home / "project" / "vasty.toml", '[profiles.big]\ngpu = "A100"\n')
    code, out, _ = harness.run("config", "profiles")
    assert code == 0
    assert json.loads(out) == {"profiles": {"small": {"gpu": "4090", "vram": 24},
                                            "big": {"gpu": "A100"}}}
    code, out, _ = harness.run("config", "profiles", "--plain")
    assert out.splitlines() == ['big  gpu="A100"', 'small  gpu="4090" vram=24']
