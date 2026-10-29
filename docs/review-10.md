# Review 10

Range: `34d2a815e3db1931fd0cea577265b094608f63fd..ec2ca4c03ae1e97efca9e976cd763061fd07fbda`. Target: the `rig` diff in `src/rig` and `tests` that implements `docs/review-9.md`. References: `docs/review-9.md`, `docs/swarm-report-9.md`, `docs/code-review-10.md`, `spec.md`, `docs/review-7.md`, `docs/review-5.md`. Line numbers are at `ec2ca4c`. The `src` and `tests` trees at `3a5c969` match it.

**Verdict: ready after fixes.** All 3 review-9 items hold with tests that fail on revert. One nit remains: an untested `finally` in the test harness leaves the `last_ctx` docstring wrong after a nested run.

## Billing impact

- No agreed finding leaves a box billing or misleads the user.
- Cleanup: finding 1.

## Findings

### Nits

1. **`Harness.run` restores `last_ctx` in an untested `finally`, and its docstring is wrong after a nested run**
   - Location: `tests/fakes.py:360-361` (`last_ctx` docstring) and `:410-414` (`try`/`finally` in `Harness.run`). Code review 10 finding 2.
   - Problem: a nested `Harness.run` inside a hook resets `last_ctx` and leaves the inner context there until the outer run exits. The docstring "The context the outermost `run` built" and the comment "Restore this run's context after a nested `run` inside a hook" overstate the behaviour. No test reaches the `finally`. The return path reads `holder[0]`, so the restore is dead for every caller.
   - Evidence:
     - Deleting the `try`/`finally` in a copy of `ec2ca4c` gave `1128 passed, 1 skipped`.
     - Swarm report 9 justifies the `finally` with "6 tests failed when the return path read it". The shipped return path reads `holder[0]` (`fakes.py:415-419`). Those 6 failures in `tests/test_extend.py` and `tests/test_reserve.py` occur only in a draft whose return path read `self.last_ctx`.
     - The report's "The `finally` also keeps the context when an exception escapes" does not hold: `make` sets `last_ctx` before any command code runs.
     - Nested `h.run` calls occur only in hooks in `tests/test_extend.py` and `tests/test_reserve.py`. None reads `last_ctx`.
   - Fix:
     - Replace `fakes.py:410-414` with:
       ```python
       code = run(list(argv), make, early_out, early_err)
       ```
     - Change the docstring at `fakes.py:361` to:
       ```python
       """The context the latest `run` built, kept when an exception escapes."""
       ```
   - Settled: exchange 1. Astra raised it as a gap with a depth-counter fix, then backed the deletion and the nit severity.

## Disagreements

None. Every dispute settled in exchange 1.

## Findings dropped

- **Code review 10 finding 1** (human-mode `emit_error` writes unguarded after `_report_swept` swallowed a closed stderr): the behaviour is real. `emit_error` at `34d2a81` is identical, so it predates the range. Review 9 dropped the same item: "predates the range, and human errors have no other stream." Review-9 gap 1 covered `_report_swept` and the JSON error object. Both reviewers refuted it.
- **Code review 10 finding 2**: merged into finding 1 with the deletion fix.
- **Code review 10 finding 3** (`except Exception` to `(OSError, ValueError)`): review-9 gap 1 asked for "the same guard `_warn_attach_lost` uses" and wrote `except Exception: pass`. `_warn_attach_lost` (`src/rig/commands/run.py:231-238`) catches `Exception`. The diff matches the reference. Both reviewers refuted it.
- **Code review 10 finding 4** (append to `ctx.swept` inside `_sweep`): review-9 gap 2 prescribed the `extend` directly after `_sweep` returns, and the diff puts it at `engine.py:611`. Review 9 dropped the mid-loop loss: "the interrupt also loses the sweep's cache writes, which predates the range. A reporting fix alone leaves that state behind." Both reviewers refuted it.
- **Code review 10 finding 5** (`test_attach_error_with_sweep_survives_broken_stderr` asserts only the propagated error): the suite catches both reverts the finding names. Deleting the `extend` fails 4 tests, including `test_attach_error_reports_sweep_on_stderr`. Dropping `_report_swept` from the `except BaseException:` branch fails `test_attach_error_reports_sweep_on_stderr`. The named test pins the guard and fails when it is removed. Both reviewers refuted it.
- **Code review 10 finding 6** (closed-stderr test closes stderr before `configure`): `tests/test_cli.py:150-152` calls `cli.configure(ctx, ns)` and then `ctx.stderr.close()`. `configure` runs no refresh. The proposed order is already in place. Both reviewers refuted it.
- **Correct the swarm report 9 deviation text** (Astra, exchange 1): the report records what that run did. Finding 1's evidence names the stale claims, and the fix removes the code they describe.

## Settled questions

- Commands: `.venv/bin/pytest -q` gave `1128 passed, 1 skipped in 29.13s`. `.venv/bin/mypy --strict` gave `Success: no issues found in 34 source files`. Both match the expected counts. No gap.
- Swarm report 9 claims: items 1 and 2 hold at `ec2ca4c`. The code and tests match review 9, with `harness.last_ctx` in place of `_contexts` per item 3. Removing the `_report_swept` guard fails `test_failing_run_with_closed_stderr_keeps_json_error` and `test_attach_error_with_sweep_survives_broken_stderr`. Removing the `except BaseException:` branch fails `test_attach_error_reports_sweep_on_stderr`. `engine.py` at `34d2a81` fails `test_refresh_records_sweep_before_a_failing_save` with `assert [] == [('l-0000a009', True)]`. Item 3 meets review 9. Its deviation is finding 1.
- Swarm report 9 open item: still open. The diff leaves `src/rig/onstart.py`, `_unmarked` (`engine.py:450`) and `_reruns_adoption` (`engine.py:455-466`) unchanged. A box adopted before the marker that loses its cache entry reads as a `reserve` box. Review 5 deferred it. No finding.
- Code review 10 finding 1: outside the diff. `emit_error` is unchanged from `34d2a81`, and review 9 dropped it.
- Code review 10 finding 3: the implementation matches review-9 gap 1 and the `_warn_attach_lost` guard. Dropped.
- Code review 10 finding 4: goes beyond what review-9 gap 2 prescribed, and review 9 dropped the mid-loop case. Dropped.

## Run

- Angles: code review 10 findings 1-6 with the finding 1, 3 and 4 questions; swarm report 9 claims, acceptance and revert tests for review-9 items 1-3 with the open item; correctness, coverage and slop in the changed lines and doc style in `docs/swarm-report-9.md`.
- Agents: 3 Sonnet.
- Reviewer model: astra.
- Exchanges: 1.
