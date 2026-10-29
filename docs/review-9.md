# Review 9

Range: `80635e3ed2df276207975485e4af11a4b7a3b5af..8278ebde57940fd6a003ea3f35ad463924e651ea`. Target: the `rig` diff in `src/rig` and `tests` that implements `docs/review-7.md`. References: `spec.md`, `docs/review-7.md`, `docs/swarm-report-8.md`, `docs/code-review-9.md`, `docs/review-5.md`, `docs/review-4.md`, `docs/review-3.md`. Line numbers are at `8278ebd`. The `src` and `tests` trees at `953b9a1` match it.

**Verdict: ready after fixes.** All 11 review-7 items hold with tests that fail on revert, but a broken stderr with swept entries drops the JSON error or masks the original exception, and a refresh that raises after its sweep drops the sweep from the report.

## Billing impact

- No agreed finding leaves a box billing.
- Misleads the user: findings 1 and 2 drop a destroy from the stderr report. Finding 1 also drops the JSON error object and exit code.
- Cleanup: finding 3.

## Findings

### Gaps

1. **`_report_swept` writes to stderr unguarded**
   - Location: `src/rig/cli.py:301-307` (`_report_swept`), called at `:339` (`RigError` branch) and `:348` (`except BaseException:` branch). Code review 9 findings 1 and 5. Swarm report 8 open item 2.
   - Problem: with a closed or broken stderr and a non-empty `ctx.swept`, the `print` raises. In the `RigError` branch `emit_error` never runs, so JSON mode loses the error object and the exit code. In the `BaseException` branch a `ValueError` replaces the original exception, which review-7 finding 1 and spec §4.6 ("when stderr still works") rule out. No test drives the `BaseException` branch: deleting it leaves `1124 passed, 1 skipped`.
   - Evidence: `run --on nope` with `l-0000a009` expired, its destroy failing and `ctx.stderr` closed raised `ValueError: I/O operation on closed file` from `cli.py:307` with stdout empty. An auto run with `l-0000a009` expired and `attach_job` closing stderr before raising `OSError("broken pipe")` raised `ValueError` in place of the `OSError`. `test_auto_run_attach_error_survives_broken_stderr` passes because its `ctx.swept` is empty.
   - Fix:
     - Wrap the loop in `_report_swept`:
       ```python
       try:
           for line in swept_lines(merge_swept(ctx.swept)):
               print(f"rig: {line}", file=ctx.stderr)
       except Exception:
           pass
       ```
     - Add to `tests/test_cli.py` (add `import io`). It fails without the guard.
       ```python
       def test_failing_run_with_closed_stderr_keeps_json_error(harness: Harness) -> None:
           from rig import cli

           add_lease(harness, "l-0000a009", label={"name": "old", "expires": NOW - 10})
           _fail_next_destroy(harness)
           made: list[Context] = []

           def make(ns: Any) -> Context:
               ctx = harness.context()
               cli.configure(ctx, ns)
               ctx.stderr.close()
               made.append(ctx)
               return ctx

           code = cli.run(["run", "--on", "nope", "--", "ls"], make)
           out = made[0].stdout
           assert isinstance(out, io.StringIO)
           assert code == 1
           assert json.loads(out.getvalue())["error"] == "lease_not_found"
       ```
     - Add to `tests/test_run.py`. The first fails when the `BaseException` branch is removed. The second fails without the guard.
       ```python
       def test_attach_error_reports_sweep_on_stderr(
           harness: Harness, reserve: FakeReserve, monkeypatch: pytest.MonkeyPatch
       ) -> None:
           made = _contexts(harness, monkeypatch)
           add_lease(harness, "l-0000a009", label={"name": "old", "expires": NOW - 10})
           harness.box.attach_job = _broken_attach  # type: ignore[method-assign]
           with pytest.raises(OSError, match="broken pipe"):
               run(harness, "--", "python", "train.py")
           err = made[0].stderr
           assert isinstance(err, io.StringIO)
           assert "rig: SWEPT  l-0000a009 old" in err.getvalue()


       def test_attach_error_with_sweep_survives_broken_stderr(
           harness: Harness, reserve: FakeReserve, monkeypatch: pytest.MonkeyPatch
       ) -> None:
           made = _contexts(harness, monkeypatch)
           add_lease(harness, "l-0000a009", label={"name": "old", "expires": NOW - 10})

           def attach(target: SshTarget, job_id: str, out: TextIO) -> int | None:
               made[0].stderr.close()
               raise OSError("broken pipe")

           harness.box.attach_job = attach  # type: ignore[method-assign]
           with pytest.raises(OSError, match="broken pipe"):
               run(harness, "--", "python", "train.py")
       ```
     - Finding 3 replaces `_contexts` in these tests with `harness.last_ctx`.
   - Settled: initial match.

2. **`refresh` records its sweep only after the probes and the cache save**
   - Location: `src/rig/engine.py:658` (`refresh`). Code review 9 finding 2.
   - Problem: `ctx.swept.extend(swept)` runs after `_probe_all` and `ctx.cache.save`. An `OSError` from the save or a `KeyboardInterrupt` during the probes, after `_sweep` destroyed a box, leaves `ctx.swept` empty, so `_report_swept` prints nothing. This is the review-7 finding 4 problem on a non-`RigError` exit. Moving the line keeps it before `return Snapshot(...)` as review-7 prescribed.
   - Evidence: `rig status` with one expired lease destroyed (`destroyed [1001]`) and `Cache.save` raising `OSError("disk full")` gave `ctx.swept []` and empty stderr. `box.probe` raising `KeyboardInterrupt` gave the same.
   - Fix:
     - Move `ctx.swept.extend(swept)` from `:658` to directly after `swept, replaced, destroyed = _sweep(ctx, rows, leases, now)` at `:610`.
     - Add to `tests/test_engine.py`. It fails at `8278ebd` and passes with the move.
       ```python
       def test_refresh_records_sweep_before_a_failing_save(
           harness: Harness, monkeypatch: pytest.MonkeyPatch
       ) -> None:
           add_lease(harness, "l-0000a009", label={"name": "old", "expires": NOW - 10})
           ctx = harness.context()

           def fail(data: Any) -> None:
               raise OSError("disk full")

           monkeypatch.setattr(ctx.cache, "save", fail)
           with pytest.raises(OSError, match="disk full"):
               engine.refresh(ctx)
           assert [(e.lease, e.ok) for e in ctx.swept] == [("l-0000a009", True)]
       ```
   - Settled: initial match.

### Nits

3. **`_contexts` duplicates the context capture in `Harness.run`**
   - Location: `tests/test_run.py:485-496` (`_contexts`) and `tests/fakes.py:393-412` (`Harness.run`). Code review 9 finding 8.
   - Problem: `_contexts` monkeypatches `harness.context` to repeat the capture that `Harness.run` keeps in its local `holder`. `Harness.run` drops that context when an exception escapes. Finding 1 adds two more users.
   - Evidence: `holder: list[Context] = []` and `holder.append(ctx)` in `Harness.run`; `made.append(ctx)` in `_contexts`, used at `test_run.py:505` and `:522`.
   - Fix:
     - Add the field `last_ctx: Context | None = None` to `Harness`.
     - In `Harness.run`, set `self.last_ctx = None` on entry and `self.last_ctx = ctx` in `make`.
     - Replace each `_contexts` use with `harness.last_ctx`, asserting it is not None. Delete `_contexts`.
   - Settled: exchange 1. Astra backed it and added the reset on entry.

## Disagreements

None. Every dispute settled in exchange 1.

## Findings dropped

- **Code review 9 finding 3** (set `result.swept = merge_swept(ctx.swept)` once and delete the per-command threading): review-5 finding 1 and review-7 findings 2 and 7 prescribed and pinned the threading. `run` and `release` build their human text inside `execute`, before `cli.run` could set `result.swept`, and `release_quietly` reads its own `swept` for `released`. Both reviewers refuted it.
- **Code review 9 finding 4** (`details.swept` in the JSON error): review-7 finding 4 says "Leave the error object unchanged." Spec §7 gives the error object as `error`, `message`, `hint` and optional `details`. The §4.4 line "Its JSON carries `warnings` and `swept`" sits in the result list, and error objects carry no `warnings` either. A `details.swept` key would also merge with existing `details`, such as `sync_failed`'s `{"exit": n}`. Both reviewers refuted it.
- **Code review 9 finding 5**: merged into finding 1.
- **Code review 9 finding 6** (`release_quietly` docstring): the docstring opens "Refresh, then release the lease", so a destroy by the refresh's sweep is a destroy by "this call". Both reviewers refuted it.
- **Code review 9 finding 7** (move `FAILED_SWEEP` to `tests/fakes.py`): the repeated literal is expected test data. No rule backs the move. Opus withdrew it in exchange 1.
- **`_sweep` loses entries on an interrupt between two destroys** (swarm): the interrupt also loses the sweep's cache writes, which predates the range. A reporting fix alone leaves that state behind.
- **A closed fd 2 sends `SWEPT` lines to stdout** (swarm): `sys.stderr` is None when fd 2 is closed at start, and `print(file=None)` writes to stdout. Every `ctx.warn` line has shared that path since before the range. The fix belongs in the `Context.stderr` default.
- **Human-mode `emit_error` raises on a broken stderr** (swarm): predates the range, and human errors have no other stream.
- **The engine and `run` docstrings both say `swept` lists every refresh** (swarm): review-7 finding 10 prescribed the engine sentence.
- **"lost the attach" names any attach exception** (swarm): spec §4.6 calls "an error while streaming output" losing the attach.
- **The `lacking` helper in `tests/test_cli.py` repeats one in `tests/test_reserve.py`** (swarm): the new one also adds the expired lease.

## Settled questions

- Commands: `.venv/bin/pytest -q` gave `1124 passed, 1 skipped in 35.50s`. `.venv/bin/mypy --strict` gave `Success: no issues found in 34 source files`. Both match the expected counts. No gap.
- Swarm report 8 claims: every claim for items 1-11 holds at `8278ebd`. Reverting each fix fails its test, for items 1, 2, 3, 4, 6, 7, 8 and 11. Item 5 adds a test for existing behaviour. Items 9 and 10 change docstrings.
- Swarm report 8 open item 1: still open. The diff leaves `_unmarked` (`engine.py:450`), `_reruns_adoption` (`engine.py:455`) and `onstart.py` unchanged. A box adopted before the marker that loses its cache entry reads as a `reserve` box and leaves the account at its clock. Review-5 deferred it. No finding.
- Swarm report 8 open item 2: still open at `cli.py:346-348`. It is finding 1.
- Code review 9 finding 4: review-7 finding 4 stands. The error object stays unchanged, and failing commands report swept entries on stderr.
- Code review 9 finding 3: contradicts review-5 finding 1 and review-7 findings 2 and 7. Dropped.

## Run

- Angles: code review 9 findings 1-4 with the finding 3 and 4 questions and swarm report 8 open item 2; code review 9 findings 5-8 and slop in the changed lines; swarm report 8 claims, acceptance and tests for review-7 items 1-11 with open item 1; correctness of the changed `run`, `serve`, `reserve`, `cli` and `engine` lines and the destroy report across refreshes.
- Agents: 4 Sonnet.
- Reviewer model: astra.
- Exchanges: 1.
