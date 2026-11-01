# Swarm report 0: issues 016 to 018

Base commit 3711952 on `live-run-2`. Final commit b7b9d72. Two Opus agents ran in worktrees: one for 016, one for 017 and 018, which share `engine.py` and `state.py`.

## Per item

### 016 `stop` escalates TERM to KILL

Landed in ed63e43. `stop` sends TERM and waits 10 s, then KILL and waits 5 s. KILL goes to every process in the job group except the leader, so `run.sh` writes `finished` and `exit`. The still-running message reads "still runs 5s after KILL". `FakeBox.signal_exits` defaults to TERM 143 and KILL 137.

Files: `src/vasty/commands/stop.py`, `src/vasty/remote.py`, `tests/fakes.py`, `tests/test_stop.py`, `tests/test_remote.py`, README `stop` row.

Tests: `uv run pytest -q tests/test_stop.py tests/test_remote.py` pass. New tests cover ignore-TERM to KILL 137, survive-KILL exit 2 after 15 s, LocalBox KILL leaving `run.sh` alive with exit 137, and LocalBox KILL ending a forked child.

### 017 Retire `expired_with_running_jobs`

Landed in 768f292. The fix-table row, the expired branch of `lease_warnings`, the untargeted history pass in `status` and the README entry are gone. `grep -rn expired_with_running_jobs src tests README.md` prints nothing.

Files: `src/vasty/state.py`, `src/vasty/commands/status.py`, `tests/test_state.py`, `tests/test_status.py`, README warning list.

### 018 `release` freezes `uptime_s`

Landed in b7b9d72. `mark_released` sets `history_since` to the release time. `_to_history` clears the destroy bookkeeping on every confirmed absence and sets `history_since` only when unset. The engine docstring states the 24 h window runs from `history_since`. README `release` row defines `destroy_pending`.

Files: `src/vasty/engine.py`, `src/vasty/views.py`, `tests/test_engine.py`, `tests/test_release.py`, README `release` row.

Tests: `test_release_freezes_uptime_while_destroy_pending` reports the same `uptime_s` 60 s after release; `test_reconcile_released_clears_destroy_pending` covers the confirmed-absence path with `history_since` already set.

## Final check

```
uv run pytest -q     1395 passed, 1 skipped
uv run mypy          Success: no issues found in 35 source files
uv run ruff check    All checks passed!
```

`tests/test_remote.py::test_write_clock_translates_into_box_time` failed once in the baseline run and passed alone and in every later run. It predates this work.

## Dropped

None.

## Open items

- 016 live check with `stubborn.py` on a real box: not run. It needs a paid lease.
