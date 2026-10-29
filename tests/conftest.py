from __future__ import annotations

from pathlib import Path

import pytest

from fakes import Harness


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    (tmp_path / "project").mkdir()
    return Harness(home=tmp_path)
