# Code review 10

Range: `34d2a815e3db1931fd0cea577265b094608f63fd..ec2ca4c03ae1e97efca9e976cd763061fd07fbda`. Effort: medium. Line numbers are at `ec2ca4c`. The review returned each finding without a confidence verdict; the verdict column records the review's own framing.

1. `src/rig/cli.py:344` (`emit_error`, human mode)
   - Problem: in human mode `emit_error` writes to `ctx.stderr` unguarded right after `_report_swept` swallowed the closed-stream failure. With `rig run --on nope -- ls` in plain mode and stderr closed, the `print` in `emit_error` raises `ValueError: I/O operation on closed file` and the process exits with a traceback in place of `err.exit_code`. `test_failing_run_with_closed_stderr_keeps_json_error` covers JSON mode only.
   - Proposed fix: guard the human-mode write in `emit_error` the same way, and add a plain-mode case to the closed-stderr test.
   - Verdict: correctness bug.

2. `tests/fakes.py:414` (`Harness.run`, `last_ctx`)
   - Problem: a nested `Harness.run` inside a hook sets `last_ctx` to the nested context and leaves it there until the outer run's `finally`. A fake `attach_job` that closes `harness.last_ctx.stderr` after a hook ran a nested command closes the nested context's stream, and the outer assertion reads an empty buffer.
   - Proposed fix: save the previous `last_ctx` on entry and restore it in `finally` when the run was nested.
   - Verdict: test-harness bug.

3. `src/rig/cli.py:309` (`_report_swept`)
   - Problem: `except Exception: pass` swallows every error, including bugs in `merge_swept` or `swept_lines`, when the guarded failure is a broken or closed stderr. A future `SweptEntry` change that makes `swept_lines` raise is hidden.
   - Proposed fix: catch `(OSError, ValueError)`, which a closed file and EPIPE raise.
   - Verdict: robustness.

4. `src/rig/engine.py:611` (`_sweep` and the `ctx.swept.extend` in `refresh`)
   - Problem: recording the sweep after `_sweep` returns still loses every destroy `_sweep` already sent when the loop raises part-way. With two expired leases, the first destroy succeeds and a non-`RigError` from `get_instance` on the second propagates with `ctx.swept` empty.
   - Proposed fix: append to `ctx.swept` inside `_sweep` as each entry is produced, or have `_sweep` take the list to extend.
   - Verdict: correctness gap, extends review 9 finding 2.

5. `tests/test_run.py:530` (`test_attach_error_with_sweep_survives_broken_stderr`)
   - Problem: the test asserts only that the attach error propagates. It passes with `ctx.swept.extend(swept)` reverted in `engine.refresh` or with the `_report_swept` call dropped from the `except BaseException` branch, since nothing reaches the closed stderr either way.
   - Proposed fix: assert `harness.last_ctx.swept` holds `l-0000a009` after the run.
   - Verdict: test coverage.

6. `tests/test_cli.py:156` (closed-stderr test)
   - Problem: the test closes stderr inside `make`, before `configure` ran any refresh. A later change that makes `configure` or `parse` write to stderr surfaces as a `ValueError` from inside `make` and an `IndexError` on `made[0]`, masking which guard broke.
   - Proposed fix: close stderr after `configure`, or in a hook that runs after the refresh, so the test exercises the `_report_swept` write only.
   - Verdict: test hygiene.
