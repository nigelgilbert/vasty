# Review 5

Range: `715a5921443c7d593e3112a91e65ec3cc0012c1b..a94be3e8eeb54a64efe937ede2bd3d6ec933e6cf`. Target: the `rig` diff in `src/rig` and `tests` that implements `docs/review-4.md`. References: `spec.md`, `docs/review-4.md`, `docs/review-3.md`, `docs/swarm-report-4.md`, `docs/code-review-5.md`. Line numbers are at `a94be3e`. The `src` and `tests` trees at `5bb59ce` match it.

**Verdict: ready after fixes.** All 9 review-4 items hold and no path leaves a box billing, but `run` drops the swept entries of its reserve wait and two new branches lack tests.

## Billing impact

No agreed finding leaves a listed box billing or loses a destroy. Finding 1 drops destroys from the `run` report. Findings 2-6 are test coverage and cleanup.

## Findings

### Gaps

1. **`run` drops the `swept` entries of the reserve wait**
   - Location: `src/rig/commands/run.py:157-161` (`execute`), `:186`, `:217` (`_attach`), `:234` (`_lost`), `:283` (`_interrupted`). Code review 5 finding 3. The behaviour predates the range.
   - Problem: `reserve_lease` returns the entries of every wait refresh in `reserved.result.swept`. `execute` copies only its warnings, and every result uses `list(snap.swept)` from the first refresh. A box destroyed during the wait goes unreported. Spec §4.4 says every networked command's JSON carries `swept`.
   - Evidence: `reserve.py:86` `swept = list(snap.swept)` and `:135` `swept += more_swept`; `run.py:161` `warnings = list(reserved.result.warnings)`; `run.py:186` `swept=list(snap.swept)`. A harness whose `FakeReserve` expired another lease before the wait gave `swept: []` for `run --detach -- ls` and `run -- ls`, with `provider.destroyed == [1001]`.
   - Fix:
     - In `execute`, set `swept = merge_swept(list(snap.swept), reserved.result.swept)` in the `auto` branch and `swept = list(snap.swept)` in the `else` branch. `merge_swept` comes from finding 3.
     - Pass `swept` to `RunDetachedResult` at `:186`.
     - Add a `swept` parameter to `_attach` and pass it on to `_lost` and `_interrupted`. Use it in place of `list(snap.swept)` at `:217`, `:234` and `:283`. Drop the `snap` parameter where it is then unused.
     - Add attached and detached tests where another lease expires during the reserve wait. Cover one accepted and one failed destroy.
   - Settled: initial match.

2. **No test covers the `destroy_pending` check in `extend._reload`**
   - Location: `tests/test_extend.py:424-428` (`UNWRITABLE_UNDER_LOCK`), covering `src/rig/commands/extend.py:139-142`.
   - Problem: the new tests reach `_reload` only with states `check_writable` rejects alone. Deleting the `destroy_pending` check or moving it after `check_writable` passes the suite.
   - Evidence: in a scratch copy, deleting `if found.destroy_pending: raise _expired(found)` gave `53 passed` in `tests/test_extend.py`. Moving `check_writable(found)` first also gave `53 passed`. `test_release_between_refresh_and_lock_is_expired` sets state `released`, which `check_writable` rejects.
   - Fix: add two cases to `UNWRITABLE_UNDER_LOCK`:
     ```python
     pytest.param({"state": "unreachable", "destroy_pending": True}, 1, "lease_expired",
                  id="unreachable-destroy-pending"),
     pytest.param({"state": "pending", "reachable_at": None, "destroy_pending": True}, 1,
                  "lease_expired", id="pending-destroy-pending"),
     ```
     The single and bulk tests already assert no label or clock write on the target and success on the other bulk target.
   - Settled: exchange 1.

### Nits

3. **The `swept` dedup in `run` lists one failing release twice**
   - Location: `src/rig/commands/run.py:111` (`_released_swept`) and `:240` (`_lost`). Code review 5 findings 2 and 7.
   - Problem: review-4 item 4 made a failed retry for a user-released lease report `expired_at` as `min(now, effective_expiry)`, which moves with each refresh. `entry not in swept` compares every `SweptEntry` field, so the first snapshot's entry and the release refresh's entry both appear. Swarm report 4 item 5 says the dedup exists to drop that repeat. The same merge expression is written twice.
   - Evidence: a harness with a cached user-released lease at `expires` NOW+3000 and a failing destroy, running `run -- ls` with the clock advanced 10s during attach, gave two entries for `l-0000a001` with `expired_at` `01:00:00Z` and `01:00:10Z`. A past-clock lease over three failing refreshes gave one entry.
   - Fix:
     - Add `merge_swept(*groups: list[SweptEntry]) -> list[SweptEntry]` beside `merge_warnings` in `src/rig/commands/_common.py`. Drop repeats of the same `(lease, ok, error)` and keep the first.
     - Change `:111` to `return released, merge_swept(swept, more)` and `:240` to `swept = merge_swept(swept, fresh.swept)`.
     - Add a `run` test with a released lease that has time left, a failing destroy and a clock that advances during attach. Assert one `swept` entry for that lease.
   - Settled: exchange 1.

4. **The adoption script writes the `adopted` marker last**
   - Location: `src/rig/onstart.py:294`, with the docstring at `:275-279`. Code review 5 finding 1.
   - Problem: a script that dies after `_GUARD_WRITE` (`:291`) leaves the guard file and `startup.started` without the marker. After a later cache loss and container restart, `_reruns_adoption` returns False for that box.
   - Evidence: `:291 body += _GUARD_WRITE`, `:292-293` the startup writes, `:294 body += ': >"$R/adopted"\n'`.
   - Fix:
     - Move `body += ': >"$R/adopted"\n'` to directly after `body = _head(...)` at `:281`. `_head` creates `$R`. Add no `|| exit 1`.
     - Reword the docstring to "It writes the `adopted` marker and the clock file, copies the container env from `/proc/1/environ`, installs the watchdog at `/workspace/.rig/watchdog.sh`, starts it under cron and `nohup`, and marks startup done."
     - Add a test in `tests/test_onstart.py` that the marker write comes before the guard write in the text of `adopt_script(...)`.
   - Settled: exchange 1.

5. **No test covers the `swept` entries `release_quietly` returns on a failed release**
   - Location: `src/rig/commands/run.py:84-89`.
   - Problem: `return False, swept` keeps the release refresh's entries when `release_lease` raises. No test asserts it.
   - Evidence: changing `return False, swept` to `return False, []` gave `68 passed` in `tests/test_run.py` and `tests/test_serve.py`.
   - Fix: add a `run` test where the release refresh sweeps another expired lease and `release_lease` raises `RigError`. Assert `released` is false and `swept` lists the swept lease.
   - Settled: exchange 1.

6. **The unmarked-box predicate is written twice**
   - Location: `src/rig/engine.py:461` (`_reruns_adoption`) and `:550` (`_apply_probe`).
   - Problem: both sites spell out `not (result.startup_started or result.guard_file)` for one rule: a box without either marker is an adopted orphan.
   - Evidence: `:461 return lease.adopted or result.adopted or not (result.startup_started or result.guard_file)` and `:550 elif probed.adopt_ran or not (result.startup_started or result.guard_file):`.
   - Fix: add `_unmarked(result: ProbeResult) -> bool` with the docstring "Return True when the box has neither the guard file nor `startup.started`." Use it at both sites.
   - Settled: exchange 1.

## Disagreements

None. Every dispute settled in exchange 1.

## Findings dropped

- **Code review 5 finding 2, its fix**: a stable first-destroy `expired_at` needs a new cache field, since each `mark_destroy_sent` overwrites `destroy_at`. `_sweep` handles only past-clock labels, where `min(now, effective_expiry)` equals `effective_expiry`. Finding 3 fixes the duplicate with a dedup key. Both reviewers rejected the review's fix.
- **Code review 5 finding 4** (`_reload` falls back to the snapshot copy): the line predates the range. A release by another process moves the entry to history, which `_reload` rejects. An entry is absent only after a lost or rebuilt cache, and `locked_active` keeps the snapshot lease by design. Both reviewers refuted it.
- **Code review 5 finding 5** (the `elif` copies `miss` layers for any unmarked box): review-4 item 1 prescribed that condition. A held rerun needs `adopt_at`, which only a rerun sets alongside `lease.adopted`, so the narrower condition takes the same branch. A guard injected into a scratch copy never fired across the full suite. Both reviewers refuted it.
- **Code review 5 finding 6** (`release_quietly` returns a tuple): every caller unpacks or ignores it. Review-4 item 5 prescribed the shape. Both reviewers refuted it.
- **Code review 5 finding 8** (drop the pre-lock `check_writable`): the two checks read different copies, the snapshot and the locked cache. The pre-lock check fails before the lock and the budget check, and review-4 item 3 added the second without removing the first. Both reviewers refuted it.
- **Code review 5 finding 9** (`_row_expires` tests a `Label` by truthiness): `Label` defines no `__bool__` or `__len__`, and review-4 item 9 prescribed the line. Both reviewers refuted it.
- **Swarm report 4 item 3 says "the separate history test is gone"** (swarm): the range deletes no test lines, but the report is a record of a finished run and the code is correct.
- **Swarm report 4 open item on `uv`**: the user keeps `uv` off PATH.

## Settled questions

- Commands: `.venv/bin/pytest -q` gave `1091 passed, 1 skipped in 24.43s`. `.venv/bin/mypy --strict` gave `Success: no issues found in 34 source files`. No gap.
- Spec conflict: spec §4.2 says "A lease whose clock file cannot be reached returns `box_unreachable` and changes nothing" and "`extend` returns `lease_pending` until SSH answers." The §7 table gives `lease_pending` for "`extend` ... on a lease SSH cannot reach yet". `check_writable` returns `lease_pending` with exit 1 for `pending` with no SSH answer, and the tests assert it with no label or clock write. The choice follows spec.md. Review-4 item 3's problem text misnamed the code.
- Open item: deferred. A box adopted before the marker that loses its cache entry holds the same files as a `reserve` box, so no probe can tell them apart. Review-3 item 9 rejected rerunning adoption on `reserve` boxes. A harness with that box gave no adopt call over four refreshes and destroyed it in the sweep once past its clock. Such boxes leave the account at their clocks.
- Destroy re-read rule: the sweep and its retries compare the listed row, `release` the cached label, and the `reserve` give-up the stored label or the row read at give-up. No finding contradicts it.
- Destroy lifecycle: with every destroy failing, sweep calls went out at 0, 5, 15, 35, 75, 135, 195 and 255s, and released-lease retries at the same gaps. Each failed call added an `ok: false` entry to `swept`. A failed `release` returned `provider_error`. Failed `run` auto-releases, on exit, on a raised start and on SIGINT, printed `rig: could not release L: ... Run rig release L.` A skipped retry lasts one refresh. No path leaves a listed, billing box that every command skips. Finding 1 covers the one unreported sweep.

## Run

- Angles: code review 5 findings 1-5 with the destroy re-read rule; code review 5 findings 6-9 and slop in the changed lines; swarm report claims, acceptance and tests for review-4 items 1-9 with the spec conflict and open item; the destroy lifecycle and the changed engine lines; correctness and tests of the `run`, `extend`, `onstart` and `remote` changes.
- Agents: 5 Sonnet.
- Reviewer model: astra.
- Exchanges: 1.
