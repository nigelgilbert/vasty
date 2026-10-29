from __future__ import annotations

import secrets

import pytest

from rig import ids
from rig.errors import RigError


def test_new_lease_id_shape() -> None:
    lease = ids.new_lease_id(secrets.token_hex, set())
    assert ids.is_lease_id(lease)
    assert len(lease) == 10


def test_new_lease_id_redraws_taken() -> None:
    draws = iter(["deadbeef", "deadbeef", "0badf00d"])
    calls: list[int] = []

    def random_hex(n: int) -> str:
        calls.append(n)
        return next(draws)

    assert ids.new_lease_id(random_hex, {"l-deadbeef"}) == "l-0badf00d"
    assert calls == [4, 4, 4]


def test_new_lease_id_gives_up() -> None:
    with pytest.raises(RuntimeError):
        ids.new_lease_id(lambda n: "ab" * n, {"l-abababab"})


def test_orphan_ids() -> None:
    assert ids.orphan_id(55120) == "i-55120"
    assert ids.parse_orphan_id("i-55120") == 55120
    for text in ["i-", "i-12a", "l-55120", "55120", "i-55120\n", "I-1"]:
        assert ids.parse_orphan_id(text) is None


def test_job_number() -> None:
    assert ids.job_number("j-1") == 1
    assert ids.job_number("j-042") == 42
    for text in ["j-", "j-1a", "job-1", "1", "j-1\n", "J-1", "x-j-1"]:
        assert ids.job_number(text) is None


@pytest.mark.parametrize("kind", ["name", "group", "owner"])
@pytest.mark.parametrize("value", ["a", "trainer", "claude-code", "exp_42.v2", "A" * 63, "9x"])
def test_valid_values(kind: str, value: str) -> None:
    assert ids.validate_value(kind, value) == value


@pytest.mark.parametrize("kind", ["name", "group", "owner"])
@pytest.mark.parametrize(
    "value", ["", "-x", ".x", "_x", "a b", "a/b", "a;b", "a=b", "A" * 64, "é", "x\n"]
)
def test_invalid_values(kind: str, value: str) -> None:
    with pytest.raises(RigError) as exc:
        ids.validate_value(kind, value)
    assert exc.value.code == "invalid_arguments"


@pytest.mark.parametrize("value", ["l-7f3a", "l-0", "i-55120", "i-0"])
def test_name_rejects_id_forms(value: str) -> None:
    with pytest.raises(RigError) as exc:
        ids.validate_value("name", value)
    assert exc.value.code == "invalid_arguments"
    assert ids.validate_value("group", value) == value
    assert ids.validate_value("owner", value) == value


@pytest.mark.parametrize("value", ["l-xyz", "l-7F3A", "i-12a", "l-", "lease-1"])
def test_name_allows_near_id_forms(value: str) -> None:
    assert ids.validate_value("name", value) == value


def test_unknown_kind() -> None:
    with pytest.raises(ValueError):
        ids.validate_value("colour", "red")
