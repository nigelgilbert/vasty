from __future__ import annotations

import pytest

from vasty import labels
from vasty.errors import VastyError
from vasty.labels import Unreadable, format_label, parse
from vasty.models import Label

SPEC = (
    "vasty:v1;lease=l-7f3a;name=trainer;owner=claude-code;group=exp42;"
    "created=1793235840;ttl=10800;expires=1793247000"
)


def test_spec_example_parses() -> None:
    label = parse(SPEC)
    assert label == Label(
        lease="l-7f3a", owner="claude-code", created=1793235840, ttl=10800,
        name="trainer", group="exp42", expires=1793247000,
    )


def test_spec_example_round_trips() -> None:
    label = parse(SPEC)
    assert isinstance(label, Label)
    assert format_label(label) == SPEC


def test_orphans_return_none() -> None:
    assert parse(None) is None
    assert parse("") is None
    assert parse("my box") is None
    assert parse("VASTY:v1;lease=l-1") is None


def test_minimal_label_and_optional_fields() -> None:
    label = Label(lease="l-00000001", owner="nick", created=100, ttl=1800)
    text = format_label(label)
    assert text == "vasty:v1;lease=l-00000001;owner=nick;created=100;ttl=1800"
    assert parse(text) == label


def test_miss_round_trips_with_comma_separator() -> None:
    label = Label(
        lease="l-1", owner="o", created=1, ttl=60, expires=61,
        miss=["watchdog", "destroy_key"],
    )
    text = format_label(label)
    assert text.endswith(";expires=61;miss=watchdog,destroy_key")
    assert parse(text) == label


def test_unknown_fields_kept_in_order() -> None:
    raw = "vasty:v1;zeta=1;lease=l-1;owner=o;alpha=a=b;created=1;ttl=60;mid=x"
    label = parse(raw)
    assert isinstance(label, Label)
    assert list(label.extra.items()) == [("zeta", "1"), ("alpha", "a=b"), ("mid", "x")]
    label.group = "g2"
    text = format_label(label)
    assert text == "vasty:v1;lease=l-1;owner=o;group=g2;created=1;ttl=60;zeta=1;alpha=a=b;mid=x"
    assert format_label(parse(text)) == text  # type: ignore[arg-type]


def test_field_order_is_canonical() -> None:
    raw = "vasty:v1;ttl=60;expires=70;created=1;owner=o;group=g;name=n;lease=l-1"
    label = parse(raw)
    assert isinstance(label, Label)
    assert format_label(label) == "vasty:v1;lease=l-1;name=n;owner=o;group=g;created=1;ttl=60;expires=70"


def test_empty_name_and_group_clear() -> None:
    label = parse("vasty:v1;lease=l-1;name=;owner=o;group=;created=1;ttl=60")
    assert isinstance(label, Label)
    assert label.name is None and label.group is None
    assert "name" not in format_label(label)


def test_over_length_raises_invalid_arguments() -> None:
    label = Label(lease="l-1", owner="o", created=1, ttl=60, extra={"note": "x" * 1024})
    with pytest.raises(VastyError) as exc:
        format_label(label)
    assert exc.value.code == "invalid_arguments"


def test_exact_limit_is_allowed() -> None:
    base = format_label(Label(lease="l-1", owner="o", created=1, ttl=60, extra={"n": ""}))
    pad = labels.MAX_LEN - len(base)
    text = format_label(Label(lease="l-1", owner="o", created=1, ttl=60, extra={"n": "x" * pad}))
    assert len(text) == labels.MAX_LEN


@pytest.mark.parametrize(
    "raw",
    [
        "vasty:v2;lease=l-1;owner=o;created=1;ttl=60",
        "vasty:;lease=l-1;owner=o;created=1;ttl=60",
        "vasty:",
        "vasty:v1",
        "vasty:v1;owner=o;created=1;ttl=60",
        "vasty:v1;lease=l-1;created=1;ttl=60",
        "vasty:v1;lease=l-1;owner=o;ttl=60",
        "vasty:v1;lease=l-1;owner=o;created=1",
        "vasty:v1;lease=;owner=o;created=1;ttl=60",
        "vasty:v1;lease=l-1;owner=o;created=1;ttl=abc",
        "vasty:v1;lease=l-1;owner=o;created=1;ttl=1.5",
        "vasty:v1;lease=l-1;owner=o;created=1;ttl=0",
        "vasty:v1;lease=l-1;owner=o;created=1;ttl=-5",
        "vasty:v1;lease=l-1;owner=o;created=x;ttl=60",
        "vasty:v1;lease=l-1;owner=o;created=1;ttl=60;expires=soon",
        "vasty:v1;lease=l-1;lease=l-2;owner=o;created=1;ttl=60",
        "vasty:v1;lease=l-1;owner=o;created=1;ttl=60;x=1;x=2",
        "vasty:v1;lease=l-1;owner=o;created=1;ttl=60;junk",
        "vasty:v1;lease=l-1;owner=o;created=1;ttl=60;miss=a,,b",
        "vasty:v1;lease=l-xyz;owner=o;created=1;ttl=60",
        "vasty:v1;lease=l-7F3A;owner=o;created=1;ttl=60",
        "vasty:v1;lease=l-aa$(id);owner=o;created=1;ttl=60",
        "vasty:v1;lease=l-aa;owner=a b;created=1;ttl=60",
        "vasty:v1;lease=l-aa;owner=-o;created=1;ttl=60",
        "vasty:v1;lease=l-aa;owner=a;name=x y$(id);created=1;ttl=5",
        "vasty:v1;lease=l-aa;owner=a;group=`id`;created=1;ttl=5",
        "vasty:v1;lease=l-aa;owner=a;name=" + "n" * 64 + ";created=1;ttl=5",
        "vasty:v1;lease=l-0000aaaa;owner=a;created=1;ttl=5;expires=999999999999999999999",
        "vasty:v1;lease=l-0000aaaa;owner=a;created=253402300800;ttl=5",
        "vasty:v1;lease=l-0000aaaa;owner=a;created=253402300795;ttl=5",
        "vasty:v1;lease=l-0000aaaa;owner=a;created=1;ttl=" + "9" * 5000,
    ],
)
def test_unreadable(raw: str) -> None:
    result = parse(raw)
    assert isinstance(result, Unreadable)
    assert result.raw == raw
    assert result.reason


def test_max_epoch_is_allowed() -> None:
    raw = "vasty:v1;lease=l-0000aaaa;owner=a;created=253402300794;ttl=5;expires=253402300799"
    label = parse(raw)
    assert isinstance(label, Label)
    assert label.expires == labels.MAX_EPOCH


def test_format_rejects_separator_in_value() -> None:
    with pytest.raises(VastyError):
        format_label(Label(lease="l-1", owner="a;b", created=1, ttl=60))
    with pytest.raises(VastyError):
        format_label(Label(lease="l-1", owner="o", created=1, ttl=60, miss=["a,b"]))


def test_is_managed() -> None:
    assert labels.is_managed("vasty:v9")
    assert not labels.is_managed(None)
    assert not labels.is_managed("other")
