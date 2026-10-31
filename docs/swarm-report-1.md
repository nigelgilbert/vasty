# Swarm report 1

Run of `swarm:implement-no-validate` on the five findings in `docs/review-1.md`, branch `refactor/live-run-followups`, base `44760b8`. Four Opus subagents ran in parallel, each in its own worktree: finding 1, finding 2, findings 3 and 4 together, and finding 5. The overseer read each diff, cherry-picked it onto the branch and reran the tests. No validation pass ran.

Final checks on the last code commit `36f16bb`: `uv run pytest` 1170 passed, 1 skipped. `uv run mypy` clean on 33 source files.

## Per item

### 1. The tier two `extend --to` value floors the TTL

`idle_warning` renders `extend --to {ttl}s`. The shortfall still goes through `format_duration`. The expectations read `3600s`, `1800s` and `7200s`. `test_name_miss_extend_to_keeps_seconds` runs `reserve --name other --ttl 5430s` and asserts `extend --to 5430s`. `parse_duration("5430s")` returns 5430.

- Commit: `9c246ba`
- Files: `src/vasty/commands/reserve.py`, `tests/test_reserve.py`, `tests/test_integration.py`
- Tests: 1169 passed, 1 skipped in the worktree.

### 2. The `reuse_candidates` docstring pre-empts an objection

The guard sentence is deleted and the rest of the docstring rewrapped.

- Commit: `3d583e8`
- Files: `src/vasty/state.py`
- Tests: 1168 passed, 1 skipped in the worktree.

### 3. The `uptime_s` README sentence restates the billing start

The sentence reads "`uptime_s` counts from vasty's first `running` sample and is null before it."

- Commit: `729a29d`
- Files: `README.md`
- Tests: 1168 passed, 1 skipped in the worktree.

### 4. The error table promises `log_tail` on every `serve_failed`

The `serve_failed` row reads "`details` carries `exit` and `lease`, plus `log_tail` when the read succeeds".

- Commit: `729a29d`, with finding 3
- Files: `README.md`
- Tests: 1168 passed, 1 skipped in the worktree.

### 5. No test covers the jobs cell of an unreachable lease with no jobs

`test_status_busy_null_while_unreachable` sits after `test_status_busy_null_while_pending`. It adds a reachable lease, runs `status` once, then marks the box unreachable. `state.py` reports `unreachable` only for a box reached before, so a lease added with `reachable=False` reads `pending`. The test asserts `state` `unreachable`, `busy` null and `jobs` empty in JSON, and `—` in the `--plain` jobs cell. With `jobs_cell` changed to return `idle` for any non-true `busy`, the test fails.

- Commit: `36f16bb`
- Files: `tests/test_status.py`
- Tests: 1169 passed, 1 skipped in the worktree.

## Findings dropped

None. The review's Dropped section was context only. No subagent proposed work beyond its fix.

## Open items

- README line 301 still states 1168 unit tests. The suite now has 1170. No finding names the line.
