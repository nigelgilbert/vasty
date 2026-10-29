# Swarm report 4

Work: `docs/review-4.md`, 9 findings (3 gaps, 6 nits). Branch `spec-validation`. Base commit `715a5921443c7d593e3112a91e65ec3cc0012c1b`. Run without validation (`swarm:implement-no-validate`).

Three Opus agents ran in worktrees, grouped by file:

- Group A, items 1, 2, 4, 6, 7 and 9: `engine.py`, `remote.py`, `onstart.py`, `models.py`, `commands/reserve.py`, `tests/fakes.py`. Commit `a229fbf`.
- Group B, item 3: `commands/extend.py`. Commit `9208aee`.
- Group C, items 5 and 8: `commands/run.py`. Commit `87c9049`.

The overseer added the extend and run bullets to the engine docstring and rewrapped two docstrings in `ebeb32c`.

Tests: `.venv/bin/pytest -q` gave `1091 passed, 1 skipped`. The baseline was 1070 passed, 1 skipped. `.venv/bin/mypy --strict` gave `Success: no issues found in 34 source files`.

## Items

### 1. A held adoption rerun clears the label's `watchdog` and `destroy_key`

- Landed: `_apply_probe` keeps the label's `ADOPT_LAYERS` when `probed.adopt_ran or not (result.startup_started or result.guard_file)`. The engine docstring says a probe on a box without markers keeps those layers and a probe inside the backoff leaves `adopt_attempts` and `adopt_at` unchanged.
- Files: `src/rig/engine.py`, `tests/test_engine.py`.
- Commit: `a229fbf`. Test: `test_held_adoption_rerun_keeps_layers_in_label` runs two refreshes inside the backoff after a failed adopt. Label `miss` and `guard_missing` stay `[watchdog, destroy_key]` and `(adopt_attempts, adopt_at)` stays `(1, NOW)`.

### 2. An adopted box that loses its cache entry gets no adoption rerun after a container restart

- Landed: `adopt_script` writes `: >"$R/adopted"` before `echo "missing=$g"`. The probe script prints `adopted=1` when the marker exists. `ProbeResult.adopted` is set in `parse_probe`. `_reruns_adoption` returns `lease.adopted or result.adopted or not (result.startup_started or result.guard_file)`. `_apply_probe` sets `lease.adopted` when the probe reports the marker. The engine and `adopt_script` docstrings describe the marker.
- Deviation: the fake's `adopted` field sits on `BoxState`, which holds each fake box's state. `FakeBox.adopt` sets it and `FakeBox.probe` returns it.
- Files: `src/rig/onstart.py`, `src/rig/remote.py`, `src/rig/models.py`, `src/rig/engine.py`, `tests/fakes.py`, `tests/test_engine.py`, `tests/test_remote.py`, `tests/test_onstart.py`.
- Commit: `a229fbf`. Tests: `test_lost_cache_entry_reruns_adoption_from_the_box_marker` deletes the cache entry, makes `alive` stale and expects one adopt call. `test_box_marker_sets_adopted_without_a_rerun`, `test_probe_reports_the_adopted_marker` (2 cases), and `adopted` asserts in `test_probe_reads_a_healthy_box`, `test_adopt_returns_missing_layers` and `test_adopt_writes_clock_env_and_starts_watchdog`.

### 3. `extend` skips `check_writable` on the copy it reloads under the lock

- Landed: `_reload` raises `_expired(found)` on `destroy_pending`, then calls `check_writable(found)` and returns `found`. `check_writable` covers history, so the separate history test is gone. The extend module docstring and the engine destroy lifecycle bullet describe the check.
- Files: `src/rig/commands/extend.py`, `tests/test_extend.py`, `src/rig/engine.py` (docstring).
- Commits: `9208aee`, `ebeb32c`. Tests: `test_unwritable_between_refresh_and_lock_changes_nothing` and `test_bulk_unwritable_between_refresh_and_lock_changes_nothing`, each over `unreachable`, `stopped` and `pending` with `reachable_at` None, and over `--by 30m` and `--to 10m` (12 cases). Each edits the cache copy after `refresh` and asserts no `set_label` call and no clock write.

### 4. A failed retry for a user-released lease reports a future `expired_at`

- Landed: `_retry_destroy` returns `SweptEntry(lease.lease, label.name, iso(min(now, effective_expiry(label))), False, error)`. The engine docstring states the value.
- Files: `src/rig/engine.py`, `tests/test_engine.py`.
- Commit: `a229fbf`. Test: `test_failed_retry_of_an_early_release_reports_expired_at_by_now`.

### 5. `run` drops the `swept` entries of its release refresh

- Landed: `release_quietly` returns `(released, swept)` with the entries of its refresh. A refresh that succeeds before `release_lease` raises still returns its entries. `_attach` and `_interrupted` add them to the result's `swept` through `_released_swept`. The error-path callers in `run.py` and `serve.py` ignore the return. The run module docstring and the engine destroy lifecycle bullet say the attached result carries these entries.
- Deviation: `_released_swept` skips entries already in the first snapshot's `swept`, since a failed retry can produce an identical `ok: false` entry in both refreshes. `_lost` merges its refresh's entries the same way.
- Files: `src/rig/commands/run.py`, `tests/test_run.py`, `src/rig/engine.py` (docstring).
- Commits: `87c9049`, `ebeb32c`. Tests: `test_auto_run_reports_release_refresh_sweep` and `test_sigint_reports_release_refresh_sweep`.

### 6. The engine docstring does not state the destroy re-read baseline

- Landed: the review's sentence opens the "Destroy lifecycle" section of the engine docstring. `_retry_destroy` and `_give_up` keep their behaviour apart from items 4 and 9.
- Files: `src/rig/engine.py`.
- Commit: `a229fbf`.

### 7. `SshBox.adopt` imports `rig.onstart` inline after the module imports it

- Landed: `remote.py` imports `LAYERS, ROOT, WORKDIR, adopt_script` at module level. The inline import is gone.
- Files: `src/rig/remote.py`.
- Commit: `a229fbf`.

### 8. The release-on-error block appears three times in `run.py`

- Landed: `_release_on_error(ctx, lease, flag)`, a `contextlib.contextmanager`, calls `release_quietly` on `BaseException` when `flag` is set and re-raises. It wraps `execute` with `created` and `_attach` and `_interrupted` with `release_on_exit`. `_lost` stays outside it and unchanged.
- Files: `src/rig/commands/run.py`.
- Commit: `87c9049`. The existing release-on-error tests in `tests/test_run.py` pass.

### 9. The row-label lookup is written three times

- Landed: `engine.row_label(ctx, instance_id) -> Label | None` returns None for a missing row or an unreadable label and lets provider errors raise. `_reread_matches`, the fallback branch of `_apply_probe` and `reserve._row_expires` use it. `release.py:104` is unchanged.
- Concurrency: `_apply_probe` runs on the main thread after the probe pool exits. Only `_probe_one` runs in the pool, so `row_label` makes no provider call from the pool.
- Files: `src/rig/engine.py`, `src/rig/commands/reserve.py`, `tests/test_engine.py`.
- Commit: `a229fbf`. Test: `test_row_label_reads_the_row` covers a found row, an unreadable label, a missing row and a raising provider.

## Spec conflicts

- Item 3's problem names `pending` with `reachable_at None` among leases that should return `box_unreachable`: "Spec §4.2 says such a lease 'returns `box_unreachable` and changes nothing'." Spec §4.2 says "`extend` returns `lease_pending` until SSH answers." The fix text calls `check_writable`, which returns `lease_pending` for that case. The tests expect `lease_pending` with exit 1, following spec.md. No label or clock write happens in either case.

## Findings dropped

None. No item guards only against misuse of the user's own configuration.

## Open items

- Boxes adopted before this change lack the `adopted` marker. If such a box loses its cache entry and its watchdog to a container restart, it gets no adoption rerun. The sweep still enforces the clock.
- `uv` is not on PATH. Install it (`brew install uv`), run `uv sync`, then rerun `uv run pytest -q` and `uv run mypy --strict`.
