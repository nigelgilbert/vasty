# Swarm report 2: review 1

Work: `docs/review-1.md`, 31 findings. Spec: `spec.md`. Base commit: `ffcb65a9592ec6331d0119e03307ef8e3bc3bc47`. Branch: `spec-validation`.

## Commands

```
.venv/bin/pytest -q
.venv/bin/mypy --strict
```

Result on the final commit: 1031 passed, 1 skipped. mypy strict reports no issues in 33 source files. The skipped test needs `fish` on PATH. Baseline: 898 passed, 1 skipped.

## Run

Ten Opus agents in three waves. Each wave's groups touched separate functions, and each wave started from the HEAD the previous wave left.

- Wave 1 from `ffcb65a`: groups A (items 2, 4, 10, 13, 22), B (5, 6, 17), C (7, 28, 29), D (20, 23), E (11, 12, 30), G (14, 15, 24, 25).
- Wave 2 from `aafa16b`: groups H1 (8, 9, 21), H2 (3, 31), I (16).
- Wave 3 from `7c1c551`: group J (18, 19, 26, 27) and the `Context.model` cleanup.

Every commit merged by cherry-pick without conflicts. The suite and mypy ran after each wave.

## Per item

### 1. uv is missing on the host

Skipped. The caller asked to leave the host alone. See open items.

### 2. `_give_up` marks a box released when the destroy was skipped

- Landed: `_give_up` marks the lease `released` only when `destroy_checked` returns True or the row is gone. Otherwise the lease stays active and stderr reads `rig: {lease} changed before it could be destroyed. Run rig release {lease}.` The `except RigError` warning ends with the same fix. The original error returns in every case.
- Files: `src/rig/commands/reserve.py`, `src/rig/engine.py`, `tests/test_reserve.py`.
- Commit: `aafa16b`.

### 3. Budget check reads a snapshot taken before the lock

- Landed: `engine.locked_active` loads `leases.json` under the lock and merges it over `snap.active()` by lease id, with the cache copy winning and history dropped. `projection_for` and `budget_check` take a `leases` argument. Reserve, extend `_single` and extend `_bulk` pass it. Spend still reads `snap.instances`.
- Choice: the merge keeps a lease the snapshot holds and a damaged cache lost. The cache alone would drop its commitment.
- Files: `src/rig/engine.py`, `src/rig/budget.py`, `src/rig/commands/reserve.py`, `src/rig/commands/extend.py`, tests.
- Commit: `510d09f`. Tests cover a second local reserve or extend landing between the refresh and the lock.

### 4. `wait_ready` leaks the box on a refresh error or Ctrl-C

- Landed: `engine.refresh` and `ctx.sleep` in `wait_ready` sit in `except (RigError, KeyboardInterrupt)` handlers that call `_give_up` and re-raise. The other `_give_up` raise sites stay outside.
- Files: `src/rig/commands/reserve.py`, `tests/test_reserve.py`.
- Commit: `aafa16b`.

### 5. Bash completion runs command substitutions from lease names

- Landed: `labels.parse` returns `Unreadable` for a lease id that fails `ids.LEASE_ID` and for an owner, name or group that fails `ids.VALUE`. `cached_names` keeps only matching values. A test runs the bash script against a hostile cache and checks nothing executes.
- Files: `src/rig/labels.py`, `src/rig/commands/completion.py`, `tests/test_labels.py`, `tests/test_completion.py`.
- Commit: `6a595a2`.

### 6. An oversized epoch in a label crashes `status`

- Landed: `parse` returns `Unreadable` when `expires` or `created + ttl` exceeds `253402300799`. It also rejects digit strings over 12 significant digits before `int()`.
- Files: `src/rig/labels.py`, `tests/test_labels.py`.
- Commit: `6a595a2`.

### 7. `sync push --delete` deletes rig's state on the box

- Landed: a push with `--delete` adds a protect filter before `-e` when the destination contains `/workspace/.rig`.
- Deviation from the fix text: the rule is anchored and recursive, `--filter=P /.rig/***`, and is computed from the destination (`P /workspace/.rig/***` for `/`). The unanchored `P .rig` also blocks deletion of a user's nested `.rig` directories. `P /.rig` alone lets rsync delete the directory's contents when the pushed tree has its own `.rig`.
- Files: `src/rig/remote.py`, `src/rig/commands/sync.py` (docstring), `tests/test_remote.py`.
- Commit: `570f47e`.

### 8. `tag` raises `name_conflict` for a name it does not change

- Landed: `update` passes `check_names` only the targets whose `(name, owner)` changes. Unchanged leases stay in `claimed`.
- Files: `src/rig/commands/tag.py`, `tests/test_tag.py`.
- Commit: `344b9c0`.

### 9. Adoption never retries a failed key attach, and cache loss stops retries

- Landed: `tag` writes `miss=watchdog,destroy_key,clock_file` in the first label of an adoption and rewrites it with the layers still missing. A failed probe of a lease whose `miss` lists `watchdog` or `destroy_key`, and that never answered SSH, retries `attach_ssh_key` on the main thread after the probe pool. The retry backs off 5s doubling to 60s. A successful probe reruns the adoption script when the cache marks the lease `adopted` or the box lacks `startup.started`. A rerun sets `adopted` again after cache loss.
- Choice: the label carries no marker for adoption, so the rerun rule reads `startup.started` on the box. `onstart` writes it on every `reserve` box, so a `reserve` lease never reruns the adoption script.
- Files: `src/rig/engine.py`, `src/rig/commands/tag.py`, `src/rig/models.py` (`key_attempts`, `key_attach_at`), `tests/fakes.py`, tests.
- Commit: `344b9c0`. Tests cover attach failure, retry after cache loss, the main-thread rule and the backoff.

### 10. `release` reports `already_absent` after a failed sweep destroy

- Landed: a history or `destroy_pending` lease returns `already_absent` only when the listing no longer shows its row. Otherwise `release` runs `destroy_checked` and raises `provider_error` on failure.
- Files: `src/rig/commands/release.py`, `tests/test_release.py`.
- Commit: `aafa16b`.

### 11. Custom images can lack `python3-venv`

- Landed: the essentials installer runs `python3 -c 'import ensurepip,venv'` and adds `python3-venv` to the apt-get list when it fails. The check runs only when `python3` is an essential.
- Files: `src/rig/onstart.py`, `tests/test_onstart.py`.
- Commit: `fba6366`.

### 12. `auth_missing` has no test

- Landed: `test_status_without_api_key_is_auth_missing`, parametrized over the default env and `RIG_API_KEY_ENV=MY_KEY`. It asserts exit 1, `auth_missing`, and the key name in the hint, and blocks real provider construction.
- Files: `tests/test_cli.py`.
- Commit: `de07366`.

### 13. The missing `.pub` branch of `reserve` has no test

- Landed: `test_reserve_without_public_key_skips_registration`.
- Files: `tests/test_reserve.py`.
- Commit: `aafa16b`.

### 14. `--sync` validates one path and transfers another

- Landed: `_check_sync_dir` returns the resolved `Path` and `run` pushes it. The relative-dir test expects `f"{harness.home}/project/src/"`. A new test covers `~/proj`.
- Files: `src/rig/commands/run.py`, `tests/test_run.py`.
- Commit: `fb9e197`.

### 15. Pre-job cleanup misses `OSError`

- Landed: `run` and `serve` catch `BaseException` before the job starts, release a box this call created, and re-raise. `save_lease` after `start_job` moved inside that `try`.
- Skipped: the `_attach` part. See spec conflicts.
- Files: `src/rig/commands/run.py`, `src/rig/commands/serve.py`, `tests/fakes.py`, `tests/test_run.py`, `tests/test_serve.py`.
- Commit: `fb9e197`.

### 16. Model-table values carry source `flag`

- Landed: `config.resolve` takes `model`. The entry's vram, gpu and image form a `model` layer after `flag`. `apply_overrides` is deleted. `Context.model` carries the model to `Context.settings`, and `serve` sets it without `--on`. `flag_mismatch` on reuse compares only flags the user passed.
- Skipped: adding `model` to the `config show` source list. See spec conflicts.
- Files: `src/rig/config.py`, `src/rig/commands/serve.py`, `src/rig/context.py`, `tests/test_config.py`, `tests/test_serve.py`.
- Commits: `7c1c551`, `e612d90`.

### 17. `parse_date_header` duplicates `parse_http_date` and misses `OverflowError`

- Landed: `parse_date_header` is deleted. `_record` calls `timeutil.parse_http_date`. The header test is now a parametrized `_record` test, and `test_timeutil.py` has the overflow case.
- Files: `src/rig/provider.py`, `tests/test_provider.py`, `tests/test_timeutil.py`.
- Commit: `2c43ff2`.

### 18. Job and taken-id helpers are duplicated

- Landed: `put_job`, `finish_job` and `taken_ids` live in `commands/_common.py`. The six copies are deleted.
- Files: `src/rig/commands/{_common,run,serve,reserve,tag}.py`.
- Commit: `592e530`.

### 19. `state.span` duplicates `format_duration` with different rules

- Landed: `span` is deleted. `state.py` and `run.py` call `timeutil.format_duration`. Tests expect `"2h1m"` for 7260 and `"1d1h"` for 90000.
- Files: `src/rig/state.py`, `src/rig/commands/run.py`, `tests/test_state.py`.
- Commit: `e143a92`.

### 20. Two duration parsers accept different grammars

- Landed: config's duration regexes are gone and `config.parse_duration` calls `timeutil.parse_duration`. `1h1h`, `30m1h`, `1h0m` and `0h30m` now fail in config files, `reserve --ttl` and `extend`.
- Files: `src/rig/config.py`, `tests/test_config.py`, `tests/test_extend.py`, `tests/test_reserve.py`.
- Commit: `7cd724b`.

### 21. A label over 1024 characters returns `provider_error`

- Landed: `tag.update` formats every planned label before the write loop. `extend.apply` formats the new label before the first write. Both return `invalid_arguments` with no write.
- Files: `src/rig/commands/tag.py`, `src/rig/commands/extend.py`, tests.
- Commit: `344b9c0`.

### 22. The sweep re-destroys a swept lease while Vast still lists it

- Landed: as part of the destroy lifecycle below. Three refreshes against a provider that keeps the row give one `swept` entry and one destroy call.
- Deviation from the fix text: `refresh` computes the listed set before it drops the rows destroyed this call. With the literal fix, `_to_history` cleared `destroy_pending` in the same refresh.
- Commit: `aafa16b`.

### 23. The `config set` comment choice has no test

- Landed: `test_config_set_drops_comments`.
- Files: `tests/test_config.py`.
- Commit: `7cd724b`.

### 24. `serve` and `sync` warnings use a stale `now`

- Landed: both pass `ctx.clock.now()`. The serve test gets `expiring_with_running_job`, the code a lease with a live serve job carries. The sync test gets `expiring_soon`.
- Files: `src/rig/commands/serve.py`, `src/rig/commands/sync.py`, tests.
- Commit: `fb9e197`.

### 25. A vLLM install timeout returns `box_unreachable`

- Landed: `_install` raises `serve_failed` when the `BoxUnreachableError` is caused by `subprocess.TimeoutExpired`. A lost connection stays `box_unreachable`.
- Files: `src/rig/commands/serve.py`, `tests/test_serve.py`.
- Commit: `fb9e197`.

### 26. Dead and redundant code

- Landed: `config.SOURCES`, `state.WARNING_CODES`, `views.ZERO` and `Context.verbose` are deleted. `status` reads `--verbose` from `args`, so the flag stays. The two extra assignments in `_new_cached` are gone. `_new_lease` is renamed `lease_from_row`. `request_ports` keeps dedup and the 64-port check, since every port source passes through `config._ports`.
- Files: `src/rig/{cli,config,context,engine,state,views}.py`, `src/rig/commands/reserve.py`.
- Commit: `a88127f`.

### 27. Duplicated constants

- Landed: one definition each for `ZERO` and `BUDGET_HINT` (`budget`), the owner pattern (`ids.VALUE`), `WORKDIR` (`onstart`), history states (`models.HISTORY_STATES`), `STARTUP_INTERRUPTED` (`onstart`) and the serve port (`models.SERVE_PORT`). The owner re-check in `reserve_lease` is gone. The serve port moved to `models` so `status --cached` stays light.
- Files: `src/rig/{budget,config,engine,models}.py`, `src/rig/commands/{_common,completion,reserve,run,serve,status}.py`.
- Commit: `211d736`.

### 28. Two clients can claim the same job id

- Landed: the start script claims the id with `mkdir "$J"` and prints `rig_job=exists` when `$J` exists. `SshBox.start_job` retries with the next `j-N` up to 10 times. Other mkdir failures keep exit 3. `FakeBox` matches.
- Choice: the retry lives in `SshBox.start_job`, since `_common.py` holds only `next_job_id` and the callers use the returned id. A leftover job directory without `started` now counts as taken.
- Files: `src/rig/remote.py`, `tests/fakes.py`, `tests/test_remote.py`.
- Commit: `570f47e`.

### 29. The rsync remote path is exposed to the remote shell on old rsync

- Landed: `SshBox` adds `-s` when the local rsync is 3.0 or later and shell-quotes the remote path otherwise. `local_rsync_version` runs once per process. `~` and `~/x` become `.` and `./x`. Tests cover both branches with a spaced path, and an end-to-end push through local rsync and an ssh stub.
- Files: `src/rig/remote.py`, `tests/test_remote.py`.
- Commit: `570f47e`.

### 30. The report overstates the fakes' reach

- Landed: `docs/swarm-report-0.md` line 20 reads "No test makes a network call. Provider tests stub the HTTP session."
- Commit: `7465576`.

### 31. An unprobed lease reports `guard: full`

- Landed: `_new_cached` and `lease_from_row` start with all three layers missing. A label `miss=` replaces that default with what another machine observed. A probe answer sets the observed layers. `guard_partial` is skipped only when no layer was observed: no `reachable_at`, no label `miss=`, and not `adopted`.
- Files: `src/rig/commands/reserve.py`, `src/rig/engine.py`, `src/rig/state.py`, tests.
- Commit: `510d09f`. Tests cover a `--no-wait` reserve, a probed pending lease that still warns, a `miss=` label, an adopted lease, and a probed lease that turns `full`.

## Destroy lifecycle

The `src/rig/engine.py` module docstring holds the lifecycle:

- `release` and the `reserve` give-up path set `destroy_pending` with `released_here` and state `released` once Vast accepts the destroy. A give-up whose destroy fails or finds the row changed leaves the lease active.
- The sweep sets it with state `expired` when it sends a destroy, accepted or failed.
- `refresh` resends the destroy while the row stays listed, on the main thread before the probe pool. The wait starts at 5s and doubles to a 60s cap. `destroy_attempts` and `destroy_at` on `CachedLease` hold the backoff.
- A swept lease whose label is no longer past its clock clears `destroy_pending` and turns active. A `released_here` lease keeps retrying.
- Reconciliation clears `destroy_pending` and starts the history window once the row is gone.
- The probe skips `destroy_pending` leases. `release` resends the destroy for a history lease whose row is still listed.

Tests cover each transition, the 5-10-20-40-60-60 backoff, and the main-thread rule.

## Spec conflicts

- Item 15. The item: "In `_attach`, release a release-on-exit box on any exception from `attach_job` and re-raise." Spec §4.6: "On SIGINT, `run` forwards SIGINT to the remote job, waits up to 10s, then exits 130. An auto-reserved box is released." Spec §8.2, agent crash mid-`run`: "The job keeps running until it exits or the clock runs out." `_attach` releases on `KeyboardInterrupt` only, and a RigError from the attach propagates unchanged.
- Item 16. The item: "Add `model` to the `config show` source list." Spec §4.10: "`show` prints each effective value and its source (`flag`, `stdin`, `profile`, `env`, `project`, `user`, `default`)." The list is unchanged. `config show` never sets a model, and a test pins that it never prints source `model`.
- Item 31. The item: "In `state.lease_warnings`, emit `guard_partial` only when the state is not `pending`." Spec §8.2: "Lease is `guard: partial` with the missing layers listed. Warning on every `status` until fixed or released." The warning is skipped only for a lease no probe has answered.

## Findings dropped

- Item 1: the caller asked to install nothing on the host.

## Open items

- Item 1: `uv` is not on PATH. Install it (`brew install uv`), run `uv sync`, then rerun `uv run pytest -q` and `uv run mypy --strict`.
- A lease cached before this change with an empty `guard_missing` shows `full` until a probe answers.
- An adopted box that loses its cache entry and its watchdog to a container restart gets no adoption rerun, because `startup.started` survives on `/workspace`. The sweep still enforces the clock.
- The adoption-script rerun for an `adopted` lease has no backoff. A box without `CONTAINER_API_KEY` reruns it on every successful probe.
- `extend` after another local process released the target between refresh and lock counts the target as history in the budget pool, and `apply` still writes the label.
- In `-s` mode, an rsync path of the form `~user/...` passes literally and is not expanded.
