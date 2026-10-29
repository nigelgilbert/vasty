from __future__ import annotations

import pytest

from fakes import START, FakeTime, Harness
from rig.errors import RigError
from rig.timeutil import Clock, format_duration, iso, parse_duration, parse_http_date, parse_time


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("45s", 45), ("30m", 1800), ("2h", 7200), ("2d", 172800), ("1h30m", 5400),
        ("1d2h3m4s", 93784), ("90m", 5400), ("05m", 300), ("1h1s", 3601),
    ],
)
def test_parse_duration(text: str, seconds: int) -> None:
    assert parse_duration(text) == seconds


@pytest.mark.parametrize(
    "text",
    ["", "0s", "0m", "1h0m", "-5m", "30", "m", "1.5h", "30M", "1w", "30m1h", "1h1h", " 30m",
     "30m ", "1h 30m", "+5m", "1h30"],
)
def test_parse_duration_rejects(text: str) -> None:
    with pytest.raises(RigError) as exc:
        parse_duration(text)
    assert exc.value.code == "invalid_arguments"


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "0s"), (-10, "0s"), (45, "45s"), (180, "3m"), (179, "2m"), (720, "12m"),
        (4320, "1h12m"), (7260, "2h1m"), (7200, "2h"), (90000, "1d1h"), (86400, "1d"),
    ],
)
def test_format_duration(seconds: int, text: str) -> None:
    assert format_duration(seconds) == text


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(7260, "2h01m"), (7200, "2h00m"), (4320, "1h12m"), (720, "12m"), (45, "45s")],
)
def test_format_duration_padded(seconds: int, text: str) -> None:
    assert format_duration(seconds, pad=True) == text


@pytest.mark.parametrize(
    ("text", "epoch"),
    [
        ("2026-10-29T01:04:00Z", 1793235840),
        ("2026-10-29T01:04:00z", 1793235840),
        ("2026-10-29t01:04:00Z", 1793235840),
        ("2026-10-29T01:04:00.999Z", 1793235840),
        ("2026-10-29T01:04:00+00:00", 1793235840),
        ("2026-10-29T03:04:00+02:00", 1793235840),
        ("2026-10-28T20:04:00-05:00", 1793235840),
        ("2026-10-29T06:34:00+05:30", 1793235840),
    ],
)
def test_parse_time(text: str, epoch: int) -> None:
    assert parse_time(text) == epoch


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-29T01:04:00", "2026-10-29", "2026-10-29T01:04Z", "2026-13-01T00:00:00Z",
        "2026-02-30T00:00:00Z", "2026-10-29T24:00:00Z", "2026-10-29T01:04:00+2:00",
        "2026-10-29T01:04:00+24:00", "1793235840", "tomorrow", "",
    ],
)
def test_parse_time_rejects(text: str) -> None:
    with pytest.raises(RigError) as exc:
        parse_time(text)
    assert exc.value.code == "invalid_arguments"


def test_iso() -> None:
    assert iso(1793235840) == "2026-10-29T01:04:00Z"
    assert iso(START) == "2026-10-29T00:00:00Z"
    assert iso(None) is None
    assert parse_time(iso(1793235840)) == 1793235840


@pytest.mark.parametrize(
    "value",
    [
        "Thu, 29 Oct 2026 01:04:00 GMT",
        "Thursday, 29-Oct-26 01:04:00 GMT",
        "Thu Oct 29 01:04:00 2026",
    ],
)
def test_parse_http_date(value: str) -> None:
    assert parse_http_date(value) == 1793235840.0


@pytest.mark.parametrize("value", [None, "", "garbage", "Thu, 99 Oct 2026 01:04:00 GMT"])
def test_parse_http_date_unparsable(value: str | None) -> None:
    assert parse_http_date(value) is None


def test_clock_uses_header_and_monotonic_time() -> None:
    t = FakeTime()
    header = (float(START), t.mono_now)
    clock = Clock(lambda: header, t.wall, t.mono)
    t.wall_now = START + 99999  # a skewed local wall clock
    assert clock.verified
    assert clock.now() == START
    t.mono_now += 90.7
    assert clock.now() == START + 90


def test_clock_ignores_monotonic_regression() -> None:
    t = FakeTime()
    clock = Clock(lambda: (float(START), t.mono_now + 5), t.wall, t.mono)
    assert clock.now() == START


def test_clock_falls_back_to_wall() -> None:
    t = FakeTime()
    clock = Clock(lambda: None, t.wall, t.mono)
    assert not clock.verified
    assert clock.now() == int(t.wall_now)
    t.advance(30)
    assert clock.now() == int(t.wall_now)


def test_clock_follows_latest_header() -> None:
    t = FakeTime()
    latest: list[tuple[float, float] | None] = [None]
    clock = Clock(lambda: latest[0], t.wall, t.mono)
    assert not clock.verified
    latest[0] = (float(START + 500), t.mono_now)
    assert clock.verified
    assert clock.now() == START + 500


def test_clock_through_harness_provider(harness: Harness) -> None:
    ctx = harness.context()
    assert not ctx.clock.verified
    ctx.provider.list_instances()
    assert ctx.clock.verified
    harness.time.advance(60)
    assert ctx.clock.now() == int(harness.time.wall_now)
    harness.provider.date_header = False
    assert not ctx.clock.verified
