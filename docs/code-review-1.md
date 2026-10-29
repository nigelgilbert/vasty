# Code review 1

Range: `6290161..d765775`. Effort: medium. The review gave no per-finding verdict, so each one is marked reported.

1. `src/rig/commands/reserve.py:382`
   - Problem: `_give_up` ignores the return value of `engine.destroy_checked`. It marks the lease `released_here` and `destroy_pending` even when nothing was destroyed. A changed `expires` makes `destroy_checked` return False. The sweep, the refresh probe and `release_lease` then skip the lease, and the box bills until the watchdog fires.
   - Fix: check the return value. On False, keep the lease active and return an error that names `rig release`.
   - Verdict: reported.

2. `src/rig/commands/reserve.py:106`
   - Problem: the budget check uses a snapshot taken before the `leases.json` lock. Two local processes can both pass the check and together exceed `daily_budget` (§5.2). `extend` `_single` and `_bulk` have the same stale snapshot.
   - Fix: re-read the cache under the lock and project spend from that read, as the name check does.
   - Verdict: reported.

3. `src/rig/commands/reserve.py:400`
   - Problem: `wait_ready` destroys the new box only at its own raise sites. A `RigError` from `engine.refresh` or a `KeyboardInterrupt` during the poll leaves the box running. `run` and `serve` auto-reserve hit this before their cleanup.
   - Fix: wrap the wait in try/except that destroys the box this call created, then re-raise.
   - Verdict: reported.

4. `src/rig/commands/run.py:75`
   - Problem: `push_dir` passes the raw `--sync` string to rsync. `_check_sync_dir` validated the `~`-expanded path resolved against `ctx.cwd`. `--sync=~/proj` passes the check and then fails with `sync_failed`.
   - Fix: pass the resolved path from `_check_sync_dir` to `push_dir`.
   - Verdict: reported.

5. `src/rig/commands/run.py:142`
   - Problem: cleanup catches only `RigError` and `KeyboardInterrupt`. An `OSError` from `ctx.box.rsync` or `start_job` skips `release_quietly`, and the auto box bills until its TTL.
   - Fix: release the auto box in a `finally`, or catch `BaseException`.
   - Verdict: reported.

6. `src/rig/engine.py:481`
   - Problem: `spend_from` adds full `dph_total` for stopped instances, which bill storage only. `Snapshot.live_instances` also counts stopped leases in `burn_per_hr`. The inflated projection can raise `budget_exceeded` or `budget_low` falsely.
   - Fix: exclude stopped instances from the live estimate and from burn, or use their storage rate.
   - Verdict: reported.

7. `src/rig/commands/serve.py:75`
   - Problem: `apply_overrides` writes the model entry's vram, gpu and image into `ctx.flags`. Config resolution records them with source `flag`, and reusing a named lease emits a spurious `flag_mismatch`.
   - Fix: apply model-table values as their own config layer below flags.
   - Verdict: reported.

8. `src/rig/provider.py:327`
   - Problem: `parse_date_header` duplicates `timeutil.parse_http_date`, which nothing calls. The copy omits `OverflowError`, so an out-of-range Date year raises on every provider call.
   - Fix: call `timeutil.parse_http_date` and delete the copy.
   - Verdict: reported.

9. `src/rig/commands/serve.py:216`
   - Problem: `_put_job` and `_record_exit` copy `run._put_job` and `run._finish_job`. `tag._taken` copies `reserve._taken_ids`.
   - Fix: move the helpers into `commands/_common.py`.
   - Verdict: reported.

10. `src/rig/state.py:117`
    - Problem: `state.span` reimplements `timeutil.format_duration` with different rules. Warnings print `1h05m` where other output prints `1h5m`.
    - Fix: use one shared formatter.
    - Verdict: reported.
