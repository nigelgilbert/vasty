# Swarm report 8

Work: `docs/review-7.md`, 11 findings (5 gaps, 6 nits). Branch `spec-validation`. Base commit `80635e3ed2df276207975485e4af11a4b7a3b5af`. Run without validation (`swarm:implement-no-validate`).

Four Opus agents ran in worktrees, grouped by file:

- Group A, items 1, 3, 7 and the `run.py` half of 10: `commands/run.py`, `tests/test_run.py`. Commit `536e9b8`.
- Group B, items 2 and 4: `commands/serve.py`, `cli.py`, `context.py`, `engine.py` (`refresh`), `tests/test_serve.py`, `tests/test_cli.py`. Commit `f434dc4`.
- Group C, items 6 and 11: `commands/reserve.py`, `tests/test_reserve.py`. Commit `140697b`.
- Group D, items 5, 8 and 9: `commands/_common.py` (docstring), `tests/test_engine.py`, `tests/test_common.py` (new). Commit `19df420`.

The overseer applied the engine docstring half of item 10 in `061a443`. The item 4 tests for `run` and `reserve` went to `tests/test_cli.py` so no two groups shared a test file.

Tests: `.venv/bin/pytest -q` gave `1124 passed, 1 skipped`. The baseline was 1106 passed, 1 skipped. `.venv/bin/mypy --strict` gave `Success: no issues found in 34 source files`.

## Items

### 1. An `attach_job` error leaves the auto-reserved box running silently

- Landed: `_attach` has `except Exception:` after the `KeyboardInterrupt` branch. It calls `_warn_attach_lost`, which writes one line through `ctx.warn`, the helper `_lost` uses, and re-raises. The line names the job, the lease, the expiry, `rig status LEASE` and `rig release LEASE`. A `try`/`except Exception: pass` around the write keeps a broken stderr from masking the original error. The run module docstring describes the path.
- Files: `src/rig/commands/run.py`, `tests/test_run.py`.
- Commit: `536e9b8`. Tests: `test_auto_run_attach_error_keeps_box_and_prints_recovery` raises `OSError` from `attach_job` and asserts the error propagates, nothing is destroyed, the job is still running, and stderr carries the recovery line. `test_auto_run_attach_error_survives_broken_stderr` closes stderr first and asserts the `OSError` still propagates. Each fails when its part of the fix is removed.

### 2. `serve` drops the `swept` entries of the reserve wait

- Landed: `execute` sets `swept = list(snap.swept)` beside `warnings`, merges `reserved.result.swept` in the `auto` branch, and sets `result.swept` before `result.warnings`. `_bring_up` passes `swept=[]`. `merge_swept` joins the `_common` import.
- Files: `src/rig/commands/serve.py`, `tests/test_serve.py`.
- Commit: `f434dc4`. Test: `test_serve_reports_reserve_wait_sweep`, parametrized on an accepted and a failed destroy, expires `l-0000a009` during the reserve wait and asserts `data["swept"]` lists it. Both cases fail with `serve.py` restored to the base.

### 3. `run` reports an auto box the release refresh swept as staying up

- Landed: the last line of `release_quietly` is `return not summary.already_absent or any(e.lease == lease.lease and e.ok for e in swept), swept`.
- Files: `src/rig/commands/run.py`, `tests/test_run.py`.
- Commit: `536e9b8`. Test: `test_auto_run_reports_box_the_release_refresh_swept_as_released` advances the clock 7300s during attach. It asserts `swept` is `[("l-0000b001", True)]`, `released` is true and `destroyed == [1001]`. It fails with the old return.

### 4. A command that raises drops the `swept` entries of its refreshes

- Landed: `Context.swept` defaults to an empty list, with `SweptEntry` imported under `TYPE_CHECKING`. `engine.refresh` extends `ctx.swept` before `return Snapshot(...)`. `cli._report_swept(ctx)` writes `rig: ` plus each line of `swept_lines(merge_swept(ctx.swept))` to `ctx.stderr`. `cli.run` calls it in the `RigError` branch before `emit_error` and in a new `except BaseException:` branch that re-raises. The error object is unchanged. The success path does not call it.
- Files: `src/rig/context.py`, `src/rig/engine.py`, `src/rig/cli.py`, `tests/test_cli.py`, `tests/test_serve.py`.
- Commit: `f434dc4`. Tests: `test_failing_run_reports_failed_sweep_on_stderr` (`run --on nope`), `test_reserve_wait_error_reports_failed_sweep_on_stderr` (`wait_ready` sweeps a lease and then raises `image_unsupported`) and `test_serve_failure_reports_failed_sweep_on_stderr` each assert the failed `SWEPT` line on stderr. `test_failing_command_without_sweep_writes_no_stderr` checks the error output with nothing swept. The three item tests fail with `cli.py` or `engine.py` restored to the base.
- Note: no test drives the `BaseException` branch. `harness.run` returns no stderr when an exception escapes.

### 5. No test covers a box with the `adopted` marker and no guard file

- Landed: `test_marker_without_guard_file_or_startup_keeps_layers_and_reruns`, verbatim, after `test_box_marker_sets_adopted_without_a_rerun`. It passes.
- Files: `tests/test_engine.py`.
- Commit: `19df420`.

### 6. `reserve` lists one failed destroy once per wait refresh

- Landed: `reserve_lease` sets `swept = merge_swept(swept, more_swept)` and `wait_ready` sets `swept = merge_swept(swept, snap.swept)`. The import is `from rig.commands._common import merge_swept, taken_ids`.
- Files: `src/rig/commands/reserve.py`, `tests/test_reserve.py`.
- Commit: `140697b`. Test: `test_wait_lists_failed_destroy_retry_once` runs a slow boot over 6 polls with `provider.fail["destroy"] = [err] * 50`, once for a past-clock lease and once for a user-released lease with 3000s left. It asserts one `swept` entry in the `rig reserve` JSON and one in the list `wait_ready` returns. Reverting either site to a plain append fails both cases.

### 7. No test pins the `swept` handling in `_lost` and `_interrupted`

- Landed: `test_lost_attach_reports_wait_and_lost_refresh_sweeps` expires `l-0000a009` during the reserve wait and `l-0000a00b` in the lost-attach refresh and asserts both entries. `test_sigint_reports_reserve_wait_sweep` expires `l-0000a009` during the reserve wait, sends SIGINT, and asserts `swept` lists it.
- Files: `tests/test_run.py`.
- Commit: `536e9b8`. Replacing the `_lost` merge with `pass` fails the first test. Passing `[]` to `_released_swept` in `_interrupted` fails the second.

### 8. No test pins the `merge_swept` key

- Landed: three unit tests in a new `tests/test_common.py`. Two failed entries for one lease with different `expired_at` merge to one. Two failed entries with different `error` stay two. A failed and an ok entry for one lease stay two.
- Files: `tests/test_common.py`.
- Commit: `19df420`. A key of `entry.lease` fails 2 of the 3 tests. A key of `(entry.lease, entry.ok)` fails 1.

### 9. The `merge_swept` docstring says every failed retry moves `expired_at`

- Landed: the sentence reads "A failed retry for a released lease with time left moves `expired_at` with each refresh, so the key leaves it out.", wrapped over two lines.
- Files: `src/rig/commands/_common.py`.
- Commit: `19df420`.

### 10. The `run` docstrings repeat the dedup rule and the engine bullet omits two refreshes

- Landed: the engine bullet's last sentence is "The `run` result's `swept` lists the entries of every refresh the call made." The `run.py` sentence on `merge_swept` is gone.
- Files: `src/rig/engine.py`, `src/rig/commands/run.py`.
- Commits: `536e9b8`, `061a443`.

### 11. A failed duplicate-instance destroy prints no fix

- Landed: the warning ends with ` Run rig release i-{inst.id} --yes.`
- Files: `src/rig/commands/reserve.py`, `tests/test_reserve.py`.
- Commit: `140697b`. Test: `test_create_timeout_failed_duplicate_destroy_names_release_fix` asserts the full warning on stderr. No earlier test checked the text.

## Findings dropped

None. No item conflicted with `spec.md`, and none guards against misuse of the user's own configuration.

## Open items

- The deferred item from review-5 stands: a box adopted before the marker existed that loses its cache entry looks like a `reserve` box to the probe. It leaves the account at its clock through the sweep.
- `cli.run`'s `except BaseException:` branch writes to stderr unguarded. On the item 1 path with a broken stderr and a non-empty `ctx.swept`, the write raises over the original error. No test covers the branch.
