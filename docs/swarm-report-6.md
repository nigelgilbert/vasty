# Swarm report 6

Work: `docs/review-5.md`, 6 findings (2 gaps, 4 nits). Branch `spec-validation`. Base commit `305b32a7fbfeca5e50322a639fbd2b79adf9437b`. Run without validation (`swarm:implement-no-validate`).

Four Opus agents ran in worktrees, grouped by file:

- Group A, items 1, 3 and 5: `commands/run.py`, `commands/_common.py`, `tests/test_run.py`. Commit `0e2dbc2`.
- Group B, item 2: `tests/test_extend.py`. Commit `7b06f7b`.
- Group C, item 4: `onstart.py`, `tests/test_onstart.py`. Commit `e75c570`.
- Group D, item 6: `engine.py`. Commit `dbc1f37`.

The overseer updated the engine docstring's `run` bullet and adoption marker line in `36e17e1`.

Tests: `.venv/bin/pytest -q` gave `1106 passed, 1 skipped`. The baseline was 1091 passed, 1 skipped. `.venv/bin/mypy --strict` gave `Success: no issues found in 34 source files`.

## Items

### 1. `run` drops the `swept` entries of the reserve wait

- Landed: `execute` sets `swept = merge_swept(list(snap.swept), reserved.result.swept)` in the `auto` branch and `swept = list(snap.swept)` otherwise. `RunDetachedResult` gets `swept`. `_attach`, `_lost` and `_interrupted` take `swept` in place of `snap`. The unused `Snapshot` import is gone. The run module docstring and the engine `run` bullet say `swept` lists the entries of every refresh the call made.
- Files: `src/rig/commands/run.py`, `src/rig/engine.py` (docstring), `tests/test_run.py`.
- Commits: `0e2dbc2`, `36e17e1`. Test: `test_auto_run_reports_reserve_wait_sweep` expires another lease before the reserve wait, attached and detached, with an accepted and a failed destroy (4 cases). Each case fails with the `auto` branch set back to `list(snap.swept)`.
- Note: `FakeReserve` returns only its own refresh's `swept`. The overlap with `snap.swept` that the real `reserve_lease` produces goes through `merge_swept`, and no test runs the real `reserve_lease` through `run`.

### 2. No test covers the `destroy_pending` check in `extend._reload`

- Landed: the two `pytest.param` cases from the review, verbatim, in `UNWRITABLE_UNDER_LOCK`. They add 8 cases across by/to and the single and bulk tests.
- Files: `tests/test_extend.py`.
- Commit: `7b06f7b`. Scratch checks: deleting the `destroy_pending` check gave `8 failed, 53 passed`. Moving `check_writable(found)` first gave the same. The 8 failures were the new cases.
- Note: `pyproject.toml` sets `pythonpath = ["src", "tests"]`, which puts the checkout's `src` ahead of `PYTHONPATH`. Run a scratch copy with `-o pythonpath=tests` and `PYTHONPATH=<scratch>/src`.

### 3. The `swept` dedup in `run` lists one failing release twice

- Landed: `merge_swept(*groups)` beside `merge_warnings` in `_common.py`. It keeps the first entry for each `(lease, ok, error)`. `_released_swept` and `_lost` use it, as does `execute` from item 1. No other `swept` merge remains in `run.py`.
- Files: `src/rig/commands/_common.py`, `src/rig/commands/run.py`, `tests/test_run.py`.
- Commit: `0e2dbc2`. Test: `test_auto_run_lists_failed_release_retry_once` caches a user-released lease at NOW+3000 with failing destroys and advances the clock 10s during attach. It asserts one entry, `("l-0000a001", False, "2026-10-29T01:00:00Z")`, and fails with the old dedup.

### 4. The adoption script writes the `adopted` marker last

- Landed: `adopt_script` writes `: >"$R/adopted"` directly after `_head`, which creates `$R`. The old line is gone. The docstring uses the review's wording and keeps the `missing=` sentence. The engine docstring says the script writes the marker first.
- Files: `src/rig/onstart.py`, `tests/test_onstart.py`, `src/rig/engine.py` (docstring).
- Commits: `e75c570`, `36e17e1`. Test: `test_adopt_writes_the_marker_before_the_guard` asserts one marker line before the `_GUARD_WRITE` line. It fails on the old script. The bash-run adoption tests and `test_adopt_script_parses` pass.

### 5. No test covers the `swept` entries `release_quietly` returns on a failed release

- Landed: `test_failed_auto_release_reports_release_refresh_sweep`. The release refresh sweeps `l-0000a009` and the destroy of the auto box raises `RigError`. It asserts `released` is false, `swept` lists `l-0000a009` with `ok: true`, and stderr names the failed release.
- Files: `tests/test_run.py`.
- Commit: `0e2dbc2`. The test fails with `return False, []` in `release_quietly`.

### 6. The unmarked-box predicate is written twice

- Landed: `_unmarked(result: ProbeResult) -> bool` with the review's docstring, above `_reruns_adoption`. Both sites call it. No third copy exists in `src/rig`. `remote.py:333` builds the positive form from parsed probe output before a `ProbeResult` exists, so it stays.
- Files: `src/rig/engine.py`.
- Commit: `dbc1f37`.

## Findings dropped

None. No item conflicted with `spec.md`, and none guards against misuse of the user's own configuration.

## Open items

- The deferred item from review-5 stands: a box adopted before the marker existed that loses its cache entry looks like a `reserve` box to the probe. It leaves the account at its clock through the sweep.
