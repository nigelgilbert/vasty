# Review 7

Range: `305b32a7fbfeca5e50322a639fbd2b79adf9437b..cb1ee1fdbfd14e9dcffb7f97e12d42093dbe7316`. Target: the `rig` diff in `src/rig` and `tests` that implements `docs/review-5.md`. References: `spec.md`, `docs/review-5.md`, `docs/review-4.md`, `docs/swarm-report-6.md`, `docs/code-review-7.md`. Line numbers are at `cb1ee1f`. The `src` and `tests` trees at `fc0b5e1` match it.

**Verdict: ready after fixes.** All 6 review-5 items hold with tests that fail on revert, but an `attach_job` error leaves an auto-reserved box billing until its clock, and four paths drop or misreport destroys.

## Billing impact

- Leaves a box billing without telling the user: finding 1. The box stays up until `release` or its `run_ttl` clock, as §4.6 requires, and `run` prints nothing.
- Misleads the user: findings 2, 3 and 4 drop or misreport a destroy. Finding 6 repeats one failed destroy in `swept`. Finding 11 gives no fix for a failed duplicate destroy.
- Cleanup: findings 5, 7, 8, 9 and 10.

## Findings

### Gaps

1. **An `attach_job` error leaves the auto-reserved box running silently**
   - Location: `src/rig/commands/run.py:209-212` (`_attach`). Predates the range.
   - Problem: `_attach` catches only `KeyboardInterrupt`. Any other exception, such as `BrokenPipeError` from `out.write` in `subprocess_runner` stream mode (`src/rig/remote.py:150-153`), propagates with no stderr line. The box stays up, which spec §4.6 requires, but the user gets no lease, job id, expiry or recovery command.
   - Evidence: a harness auto run whose `attach_job` raised `BrokenPipeError` ended with `destroyed []`, the lease `running` and empty stderr.
   - Fix:
     - After `except KeyboardInterrupt: return _interrupted(...)`, add `except Exception:` that writes the lease, job id, expiry, `rig status LEASE` and `rig release LEASE` to `ctx.stderr` through the same helper `_lost` uses, then re-raises. Wrap the write so a broken stderr does not mask the original error.
     - Add a `tests/test_run.py` test: an auto run whose `attach_job` raises `OSError` propagates the error, leaves the box up, and prints the recovery commands.
   - Settled: spec §4.6 (decision on 2026-10-29, option B: a lost attach keeps the box). The earlier proposal to release the box is withdrawn.

2. **`serve` drops the `swept` entries of the reserve wait**
   - Location: `src/rig/commands/serve.py:195` (`_bring_up`), with `execute` at `:131-153`. Code review 7 finding 1. Predates the range.
   - Problem: `ServeResult.swept` is `list(snap.swept)`. `execute` keeps only the warnings of `reserved.result`, so a destroy during the wait goes unreported. Spec §4.4 says every networked command's JSON carries `swept`.
   - Evidence: a harness that expired `l-0000a009` before the wait and ran `rig serve --model QWEN` gave `swept: []` with the destroy accepted (`destroyed [1001]`) and with it failing. Astra reproduced it with exit 0 and empty stderr.
   - Fix:
     - In `execute`, set `swept = list(snap.swept)` beside `warnings`. In the `auto` branch set `swept = merge_swept(swept, reserved.result.swept)`. Set `result.swept = swept` before the `result.warnings = ...` line. Add `merge_swept` to the `_common` import.
     - Set `swept=[]` in `_bring_up`.
     - Add a `tests/test_serve.py` test, parametrized on an accepted and a failed destroy, that expires another lease during the reserve wait and asserts `data["swept"]` lists it.
   - Settled: initial match.

3. **`run` reports an auto box the release refresh swept as staying up**
   - Location: `src/rig/commands/run.py:73-90` (`release_quietly`). Predates the range.
   - Problem: when the job outlives the TTL, the release refresh's sweep destroys the auto box and `release_lease` returns `already_absent`. `run` then reports `released: false` and the human line `l-... stays up`.
   - Evidence: a harness gave `released: False`, `swept: [{lease: l-0000b001, ok: True}]` and the human tail "stays up".
   - Fix:
     - Change the last line of `release_quietly` to `return not summary.already_absent or any(e.lease == lease.lease and e.ok for e in swept), swept`.
     - Add a `tests/test_run.py` test where the clock passes the auto lease's expiry during attach. Assert `released` is true.
   - Settled: exchange 1.

4. **A command that raises drops the `swept` entries of its refreshes**
   - Location: `src/rig/cli.py:328` (`run`), `src/rig/engine.py:658` (`refresh`), `src/rig/commands/reserve.py:409-417` (`wait_ready`), `src/rig/commands/run.py:98-100` and `src/rig/commands/serve.py:147-151`. Predates the range.
   - Problem: the error object carries no `swept`, `wait_ready` errors drop the entries it gathered, and the cleanup handlers discard what `release_quietly` returns. A sweep destroy on a failing command goes unreported. A failed one resurfaces only when a later command's retry fires.
   - Evidence: `run --on nope` with another lease's destroy failing printed only `{"error":"lease_not_found",...}` and empty stderr. `serve` with the readiness wait timing out printed only `serve_failed`. Astra reproduced the `wait_ready` case with stderr empty, the row still listed and `destroy_attempts=1`.
   - Fix:
     - Add `swept: list[SweptEntry] = field(default_factory=list)` to `Context` in `src/rig/context.py`. Import `SweptEntry` under `TYPE_CHECKING`.
     - In `engine.refresh`, append `swept` to `ctx.swept` before the `return Snapshot(...)` at `:658`.
     - In `cli.py`, add `_report_swept(ctx)`. It writes `rig: ` plus each line of `swept_lines(merge_swept(ctx.swept))` to `ctx.stderr`. Import both helpers inside the function.
     - In `cli.run`, call `_report_swept(ctx)` in the `RigError` branch before `emit_error` when `ctx` is set. Add `except BaseException:` that calls `_report_swept(ctx)` when `ctx` is set and re-raises. This covers the `OSError` and second `KeyboardInterrupt` exits of the cleanup handlers.
     - Leave the error object unchanged.
     - Add tests: an erroring `run --on nope`, a failing `serve` bring-up and a `reserve` wait error each print the failed sweep line on stderr.
   - Settled: exchange 1. Astra's findings on `wait_ready` and on the cleanup handlers merged here. Astra held the `BaseException` branch, and Opus backed it.

5. **No test covers a box with the `adopted` marker and no guard file**
   - Location: `tests/test_engine.py`, after `test_box_marker_sets_adopted_without_a_rerun` (`:704-709`). Code review 7 finding 6.
   - Problem: the marker-first script leaves a box with the marker but no guard file or `startup.started` when it stops early. The code keeps the layers through the label `miss` and reruns adoption. No test covers that state.
   - Evidence: `test_lost_cache_entry_reruns_adoption_from_the_box_marker` runs a full `FakeBox.adopt` first. The failed and held rerun tests use `box.adopted` False.
   - Fix: add this test. It passes at `cb1ee1f`.
     ```python
     def test_marker_without_guard_file_or_startup_keeps_layers_and_reruns(
         harness: Harness, monkeypatch: pytest.MonkeyPatch
     ) -> None:
         from rig.remote import BoxUnreachableError, SshTarget

         row = adopted_orphan(harness, reachable=True)
         box = harness.box.state(row.id)
         box.adopted = True
         real_adopt = harness.box.adopt

         def fail(target: SshTarget, expires: int) -> list[str]:
             raise BoxUnreachableError("adopt failed")

         monkeypatch.setattr(harness.box, "adopt", fail)
         lease = refresh(harness).leases["l-abababab"]
         assert (box.guard_file, box.startup_started) == (False, False)
         assert label_of(harness, row.id).miss == ["watchdog", "destroy_key"]
         assert lease.guard_missing == ["watchdog", "destroy_key"]
         assert lease.adopted is True
         monkeypatch.setattr(harness.box, "adopt", real_adopt)
         harness.time.advance(5)
         lease = refresh(harness).leases["l-abababab"]
         assert harness.box.adopts == [row.id]
         assert (lease.guard_missing, label_of(harness, row.id).miss) == ([], [])
     ```
   - Settled: exchange 1.

### Nits

6. **`reserve` lists one failed destroy once per wait refresh**
   - Location: `src/rig/commands/reserve.py:135` (`reserve_lease`) and `:409` (`wait_ready`). Code review 7 finding 2. Predates the range.
   - Problem: both sites append with no dedup. A past-clock lease keeps one `expired_at`, so each failed retry adds an identical entry to `rig reserve` and `serve` output.
   - Evidence: with `WAIT_POLL_S` 10s and a failing destroy over 6 polls, `rig reserve` listed `('l-0000a009', False, '2026-10-29T00:59:50Z', 'provider_error')` four times. Changing only `wait_ready`, as code review 7 proposes, left two.
   - Fix:
     - Change `:409` to `swept = merge_swept(swept, snap.swept)` and `:135` to `swept = merge_swept(swept, more_swept)`.
     - Change the import at `:26` to `from rig.commands._common import merge_swept, taken_ids`.
     - Add a `tests/test_reserve.py` slow-boot test with `provider.fail["destroy"] = [err] * 50`, once for a past-clock lease and once for a user-released lease with time left. Assert one `swept` entry.
   - Settled: initial match.

7. **No test pins the `swept` handling in `_lost` and `_interrupted`**
   - Location: `tests/test_run.py`, covering `src/rig/commands/run.py:241` and `:284`.
   - Problem: the range threads `swept` through both paths, and the suite passes when either drops it.
   - Evidence: replacing `swept = merge_swept(swept, fresh.swept)` with `pass` gave `1106 passed, 1 skipped`. Passing `[]` to `_released_swept` in `_interrupted` gave `50 passed` in `tests/test_run.py`.
   - Fix:
     - Add a lost-attach test (`attach_job` returns None) where one lease expires during the reserve wait and another in the lost-attach refresh. Assert both entries.
     - Add a SIGINT test where a lease expires during the reserve wait. Assert `swept` lists it.
   - Settled: exchange 1.

8. **No test pins the `merge_swept` key**
   - Location: `src/rig/commands/_common.py:134-147`.
   - Problem: a key of `entry.lease` or `(entry.lease, entry.ok)` passes the suite.
   - Evidence: each weaker key gave `74 passed` over `tests/test_run.py` and `tests/test_serve.py`.
   - Fix: add unit tests. Two failed entries for one lease with different `expired_at` merge to one. Two failed entries with different `error` stay two. A failed and an ok entry for one lease stay two.
   - Settled: exchange 1.

9. **The `merge_swept` docstring says every failed retry moves `expired_at`**
   - Location: `src/rig/commands/_common.py:137`.
   - Problem: `_retry_destroy` sets `expired_at` to `min(now, effective_expiry(label))`, which moves only for a released lease with time left.
   - Evidence: `return SweptEntry(lease.lease, label.name, iso(min(now, effective_expiry(label))), False, error)` in `src/rig/engine.py`.
   - Fix: replace the sentence with "A failed retry for a released lease with time left moves `expired_at` with each refresh, so the key leaves it out."
   - Settled: exchange 1.

10. **The `run` docstrings repeat the dedup rule and the engine bullet omits two refreshes**
    - Location: `src/rig/engine.py:46-47` and `src/rig/commands/run.py:15-18`. Code review 7 finding 5.
    - Problem: the engine bullet names only the reserve wait and the release refresh. The dedup rule appears in the engine bullet, the run module docstring and the `merge_swept` docstring.
    - Evidence: `run.py:162` merges the first refresh and `:241` the lost-attach refresh. `run.py:17-18` reads "`merge_swept` keeps one entry per lease, `ok` and `error`."
    - Fix:
      - Make the engine bullet's last sentence "The `run` result's `swept` lists the entries of every refresh the call made."
      - Cut the `run.py` sentence "`merge_swept` keeps one entry per lease, `ok` and `error`."
    - Settled: exchange 1.

11. **A failed duplicate-instance destroy prints no fix**
    - Location: `src/rig/commands/reserve.py:323` (`create_with_recovery`). Predates the range.
    - Problem: the warning names the instance only. The twin row then shows as an unreadable duplicate that the sweep skips until the kept lease ends.
    - Evidence: `status` showed `('i-1002', 'orphan')` and a `label_unreadable` warning after `rig: could not destroy duplicate instance 1002: boom`.
    - Fix: append ` Run rig release i-{inst.id} --yes.` to the warning text.
    - Settled: exchange 1.

## Disagreements

None. Every dispute settled in exchange 1.

## Findings dropped

- **Code review 7 finding 3** (keep the latest `merge_swept` entry per lease): review-5 finding 3 prescribed the `(lease, ok, error)` key. Under review-3 item 3, an accepted retry returns no entry, so a fail-then-ok pair does not arise from the sweep. Both reviewers refuted it.
- **Code review 7 finding 4** (`run.py:162` merges `snap.swept` twice): review-5 finding 1 prescribed the expression, and `merge_swept` removes the overlap. The proposed `merge_swept(reserved.result.swept)` fails `test_auto_run_lists_failed_release_retry_once`, since `FakeReserve` omits `snap.swept`. Both reviewers refuted it.
- **Code review 7 finding 6 as a bug**: `tag` writes `miss` with every guard layer before the script runs. `_reruns_adoption` reads the label `miss`, `_unmarked` stays true, and `_apply_probe` keeps the adoption layers through failed and held reruns. Both reviewers refuted it. Finding 5 adds the missing test.
- **Code review 7 finding 7** (`merge_swept` dedups within the first list): the docstring states the dedup over all input. One refresh holds at most one entry per lease. Both reviewers refuted it.
- **Align `FakeReserve` with `reserve_lease`** (code review 7 finding 4, swarm report 6 item 1 note): the new tests fail on revert with the current fake. No rule backs the change.
- **Swarm report 6 style** (swarm): the report records a finished run.

## Settled questions

- Commands: `.venv/bin/pytest -q` gave `1106 passed, 1 skipped in 28.20s`. `.venv/bin/mypy --strict` gave `Success: no issues found in 34 source files`. No gap.
- Code review 7 finding 6: a box with the marker and no guard file or `startup.started` gets a probe `guard_missing` of `[]`, or `['clock_file']` when the clock was not yet written. The lease still reports `watchdog` and `destroy_key` from the label `miss` and reruns adoption after `retry_delay`. A lost cache entry rebuilds from the provider label and takes the same path. Finding 5 adds the test.
- Swarm report 6: every claim for items 1-6 holds at `cb1ee1f`. Each new test fails when its fix is reverted. The open item stands: a box adopted before the marker that loses its cache entry looks like a `reserve` box and leaves the account at its clock.
- Destroy re-read rule: the sweep and its retries, `release` and the `reserve` give-up follow review-4. No agreed finding contradicts it.
- Destroy lifecycle: with every destroy failing, sweep calls went out at 0, 5, 15, 35, 75, 135, 195 and 255s, and released-lease retries at 5, 15, 35, 75, 135, 195 and 255s. The cap is 60s. Each failed call added an `ok: false` entry. No path leaves a listed, billing box that every command skips. Unreadable and duplicate rows carry a `label_unreadable` warning with the `rig release i-N` fix. Findings 1-4 cover the paths that leave a box up or drop a destroy from the output.

## Run

- Angles: code review 7 findings 1-4 with the destroy re-read rule; code review 7 findings 5-7 with the finding 6 question; swarm report 6 claims, acceptance and tests for review-5 items 1-6; the destroy lifecycle across commands; correctness, tests and slop in the changed lines.
- Agents: 5 Sonnet.
- Reviewer model: astra.
- Exchanges: 1.
