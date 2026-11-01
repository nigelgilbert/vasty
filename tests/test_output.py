from __future__ import annotations

from decimal import Decimal

import pytest

from vasty.output import money, to_jsonable


@pytest.mark.parametrize(
    ("value", "out"),
    [("0.0034", 0.0034), ("0.003", 0.003), ("0.272", 0.272), ("0.00005", 0.0001), ("2.5", 2.5)],
)
def test_to_jsonable_rounds_decimals_to_four_places(value: str, out: float) -> None:
    assert to_jsonable(Decimal(value)) == out
    assert to_jsonable({"cost": [Decimal(value)]}) == {"cost": [out]}


def test_money_rounds_to_cents_for_human_output() -> None:
    assert money(Decimal("0.003")) == 0.0
    assert money(Decimal("0.125")) == 0.13
