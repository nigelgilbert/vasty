# Swarm report 3: review 3

Work: `docs/review-3.md`, 17 findings (8 gaps, 9 nits). Spec: `spec.md`. Base commit: `e53eb3de74e2348bf8d4dda4f238611e604c5458`. Branch: `spec-validation`. Run without a validation pass.

## Commands

```
.venv/bin/pytest -q
.venv/bin/mypy --strict
```

Result on the final commit: 1070 passed, 1 skipped. mypy strict reports no issues in 34 source files. The skipped test needs `fish` on PATH. Baseline: 1031 passed, 1 skipped, 33 files. The new file is `src/rig/keys.py`.

## Run

Seven Opus agents in one wave from `e53eb3d`, one per group. Groups that shared a file edited separate functions.

- A: items 1, 2, 3 (destroy lifecycle).
- B: items 9, 10, 11 (probe, adoption, guard state).
- C: items 6, 13, 14, 17 (remote paths, ids).
- D: items 4, 8 (extend under the lock).
- E: item 5 (run release paths).
- F: items 7, 12 (completion, release).
- G: items 15, 16 (`locked_active`, `rig.keys`).

Every commit merged by cherry-pick without conflicts. The overseer added `27c9792` to record items 4, 5 and 12 in the engine destroy lifecycle docstring.

## Per item

### 1. `_retry_destroy` records a skipped destroy as an accepted call

- Landed: `_retry_destroy` returns before `mark_destroy_sent` when `destroy_checked` returns False. Sent and failed calls still record the attempt.
- Files: `src/rig/engine.py`, `tests/test_engine.py`.
- Commit: `72c0911`. Test: `test_skipped_retry_leaves_attempts_and_error_unchanged` checks `destroy_attempts`, `destroy_at` and `last_provider_error`, then checks the destroy goes out on the next refresh.

### 2. `_give_up` skips the destroy after the first probe fills `expires`

- Landed: `_give_up` keeps a stored `expires`. When it is None, `_row_expires` reads the row with `get_instance`, parses the label and passes its `expires` to `destroy_checked`.
- Files: `src/rig/commands/reserve.py`, `src/rig/engine.py` (docstring), `tests/test_reserve.py`.
- Commit: `72c0911`. Tests: probe writes `expires` then Ctrl-C destroys the box; `expires` moving after the row read skips with the warning; a stored `expires` that differs from the row skips without a row read.

### 3. Failed destroy retries show only under `--verbose`

- Landed: `_retry_destroy` returns `SweptEntry(lease.lease, label.name, iso(effective_expiry(label)), False, code)` for a failed sent call and None otherwise. `_sweep` appends it to `swept`.
- Files: `src/rig/engine.py`, `tests/test_engine.py`.
- Commit: `72c0911`. Test: `test_failed_retry_on_a_later_refresh_is_reported_in_swept` covers a failed retry, a backoff-gated refresh and an accepted retry.

### 4. `extend` overwrites a release another local process made after `refresh`

- Landed: under the lock, `_single` and `_bulk` reload each target from `leases.json` with `_reload`. A copy in history or with `destroy_pending` returns `lease_expired` with no write. The expiry, the "at or before now" check, the budget `replace` map and `apply` use the reloaded copy. A target the cache lacks keeps its snapshot copy.
- Choice: bulk reports a released target as a per-lease `{ok: false, error: "lease_expired"}` entry and the other targets go ahead. Spec §4.2: "returns a per-lease array of `{lease, ok, expires_at, error}`."
- Files: `src/rig/commands/extend.py`, `src/rig/engine.py` (docstring), `tests/test_extend.py`.
- Commits: `e7a7267`, `27c9792`. Tests: single and bulk release between refresh and lock, and a second local extend of the same lease that the new extend stacks on.

### 5. A second Ctrl-C or a failed save after the job exits skips the auto-release

- Landed: `_attach` wraps the post-exit save, and `_interrupted` wraps the signal, the 10s wait and the save, in `try`/`except BaseException`. Each calls `release_quietly` when `release_on_exit` and re-raises. `_lost` is unchanged.
- Files: `src/rig/commands/run.py`, `src/rig/engine.py` (docstring), `tests/test_run.py`.
- Commits: `fbe0de3`, `27c9792`. Tests: a raising save and a second `KeyboardInterrupt` each give `provider.destroyed == [1001]` on an auto box and `[]` with `--on`.

### 6. `~user` remote paths reach the remote shell unquoted

- Landed: `_rsync_path` raises `invalid_arguments` "Remote path {path} uses ~user." with hint "Use an absolute path or ~/." when the resolved path still starts with `~`, with and without `-s`. The `~user/` docstring sentence is gone.
- Files: `src/rig/remote.py`, `tests/test_remote.py`.
- Commit: `9744009`. Test: `test_rsync_path_rejects_tilde_user` covers `~bob/a b`, `~bob` and `~$(id)/foo` for push and pull, with and without `-s`.

### 7. Bash completion runs command substitutions from profile names

- Landed: `_profile_names` keeps names that match `ids.VALUE`.
- Files: `src/rig/commands/completion.py`, `tests/test_completion.py`.
- Commit: `683e9c8`. Tests: `--list profiles` drops a `$(touch ...)` profile, and the bash script completes `--profile` without creating the file.

### 8. No test covers a cached lease replacing its snapshot copy in `locked_active`

- Landed: `test_budget_counts_local_extend_between_refresh_and_lock`. A second local extend of `l-0000a002` lands between refresh and lock, and extending `l-0000a001` returns `budget_exceeded` with projected 1.75. The snapshot copy alone gives 0.75. A shared `run_after_refresh` helper backs `reserve_after_refresh`.
- Files: `tests/test_extend.py`.
- Commit: `e7a7267`.

### 9. A reserve box in the guard-file window counts as an adopted orphan

- Landed: `ProbeResult.guard_file`, set by `parse_probe`. `_reruns_adoption` ends with `lease.adopted or not (result.startup_started or result.guard_file)`. `FakeBox` carries `guard_file`, and `adopt` sets it.
- Files: `src/rig/models.py`, `src/rig/remote.py`, `src/rig/engine.py`, `tests/fakes.py`, `tests/test_engine.py`, `tests/test_remote.py`.
- Commit: `7eb6b25`. Tests: a reserve box in the window gets no adopt call; `parse_probe` reads `guard_file`. The cache-loss recovery tests pass unchanged.

### 10. The adoption rerun has no backoff

- Landed: `CachedLease.adopt_attempts` and `adopt_at`. `_probe_all` passes `now` to `_probe_one`, which passes it to `_reruns_adoption`. A rerun waits `retry_delay(adopt_attempts)` from `adopt_at`. `_apply_probe` bumps both after a rerun and resets them once no `ADOPT_LAYERS` are missing. `key_attach_at` stays separate.
- Deviation: the backoff check sits in `_reruns_adoption`, which `_probe_one` calls with `now`. The condition matches the fix text.
- Files: `src/rig/models.py`, `src/rig/engine.py`, `tests/test_engine.py`, `tests/test_cache.py`.
- Commit: `7eb6b25`. Test: `test_adoption_rerun_backs_off_while_a_layer_stays_missing`. The cache round trip covers the new fields, and an old cache fills their defaults.

### 11. Leases cached before this change still read `guard: full` until a probe answers

- Landed: `_unprobed_guard` sets all three `GUARD_LAYERS` missing when `reachable_at is None`, the label has no `miss` and the lease is not `adopted`. `_keep_guard` applies it on a failed probe and on a running lease with `probe=False`. `cached_snapshot` applies it to each loaded lease in memory.
- Files: `src/rig/engine.py`, `tests/test_engine.py`, `tests/test_status.py`.
- Commit: `7eb6b25`. Tests: a legacy entry through a failed probe, a skipped probe and a load; an adopted entry left alone; `status --cached` shows `partial` with no `guard_partial` warning, per the item 31 choice.

### 12. `release` reports "its expiry moved" for an unreadable label

- Landed: `release_lease` parses the row it already re-reads. A label that does not parse to a `Label` raises `provider_error` "Lease {lease}'s label is unreadable." with hint `rig release i-{instance_id} --yes`. No provider call is added.
- Files: `src/rig/commands/release.py`, `src/rig/engine.py` (docstring), `tests/test_release.py`.
- Commits: `6b83b7e`, `27c9792`. Test: `test_release_reports_unreadable_label_on_reread` checks the message and hint, then runs the hint and checks the destroy.

### 13. The exec timeout test does not pin the `TimeoutExpired` cause

- Landed: the test binds `as err` and asserts `isinstance(err.value.__cause__, subprocess.TimeoutExpired)`.
- Files: `tests/test_remote.py`.
- Commit: `9744009`.

### 14. `SshBox` repeats the `onstart` paths

- Landed: `remote.py` imports `ROOT` and `WORKDIR` from `rig.onstart` for the `SshBox` defaults.
- Files: `src/rig/remote.py`.
- Commit: `9744009`.

### 15. `locked_active` takes the lock that `load` already takes

- Landed: `cached = ctx.cache.load().leases` and the docstring sentence from the fix text. Reserve, extend `_single` and extend `_bulk` hold the lock around the call.
- Files: `src/rig/engine.py`.
- Commit: `c11d413`.

### 16. The engine imports `public_key` from a command module

- Landed: `src/rig/keys.py` holds `public_key(ctx)` and imports `Context` under `TYPE_CHECKING`. `engine`, `reserve` and `tag` import it at the top. Both function-local imports and the unused `Path` import in `reserve.py` are gone. `import rig.engine` loads no `rig.commands` module, and `test_status_cached_imports_stdlib_only` passes.
- Files: `src/rig/keys.py`, `src/rig/engine.py`, `src/rig/commands/reserve.py`, `src/rig/commands/tag.py`.
- Commit: `c11d413`.

### 17. The `j-N` regex is defined twice

- Landed: `ids.JOB_NUMBER` and `ids.job_number`. `following_job_id` and `next_job_id` call `job_number`. Both `_JOB_NUMBER` regexes are deleted.
- Files: `src/rig/ids.py`, `src/rig/remote.py`, `src/rig/commands/_common.py`, `tests/test_ids.py`.
- Commit: `9744009`. Test: `test_job_number`.

## Spec conflicts

None found. The item notes for review-1 items 15, 16 and 31 hold: `_lost` is unchanged, `config show` still omits `model`, and an unprobed lease reads `partial`.

## Findings dropped

None.

## Open items

- `uv` is not on PATH. Install it (`brew install uv`), run `uv sync`, then rerun `uv run pytest -q` and `uv run mypy --strict`.
- An adopted box that loses its cache entry and its watchdog to a container restart gets no adoption rerun, because `startup.started` and the guard file survive on `/workspace`. The sweep still enforces the clock. A fix needs a label field spec §8.0 does not define.
- A failed destroy retry for a lease the user released reports `expired_at` from the label's effective expiry, which can be in the future. This follows the item 3 fix text and spec §4's `{lease, name, expired_at, ok, error}` entry.
