from __future__ import annotations

from vasty.commands._common import merge_swept
from vasty.models import SweptEntry


def entry(expired_at: str, ok: bool, error: str | None) -> SweptEntry:
    return SweptEntry("l-0000a001", "vasty-a", expired_at, ok, error)


def test_merge_swept_merges_failed_retries_with_moving_expired_at() -> None:
    first = entry("2026-01-01T00:00:00Z", False, "destroy failed")
    later = entry("2026-01-01T00:00:05Z", False, "destroy failed")
    assert merge_swept([first], [later]) == [first]


def test_merge_swept_keeps_failed_entries_with_different_errors() -> None:
    first = entry("2026-01-01T00:00:00Z", False, "destroy failed")
    other = entry("2026-01-01T00:00:00Z", False, "provider timeout")
    assert merge_swept([first], [other]) == [first, other]


def test_merge_swept_keeps_failed_and_ok_entries_for_one_lease() -> None:
    failed = entry("2026-01-01T00:00:00Z", False, "destroy failed")
    ok = entry("2026-01-01T00:00:00Z", True, None)
    assert merge_swept([failed], [ok]) == [failed, ok]
