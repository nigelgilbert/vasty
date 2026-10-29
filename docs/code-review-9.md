# Code review 9

Range: `80635e3ed2df276207975485e4af11a4b7a3b5af..8278ebde57940fd6a003ea3f35ad463924e651ea`. Effort: medium. Line numbers are at `8278ebd`. The review returned each finding without a confidence verdict; the verdict column records the review's own framing.

1. `src/rig/cli.py:307` (`_report_swept`)
   - Problem: the write to `ctx.stderr` is unguarded. A closed or broken stderr turns the sweep report into a new exception that replaces the original error and skips `emit_error`. With `rig run ... 2>&-` and a refresh that swept a lease, a `RigError` ends in a traceback with no JSON payload and no `err.exit_code`. In the `except BaseException` branch the same write masks the original `OSError` that `_warn_attach_lost` preserves. Swarm report 8 names this as an open item.
   - Proposed fix: wrap the write in the same guard `_warn_attach_lost` uses, so a failing stderr write is swallowed and the original error propagates.
   - Verdict: correctness bug.

2. `src/rig/engine.py:658` (`refresh`)
   - Problem: `ctx.swept.extend(swept)` runs after probing, label writes and `ctx.cache.save`. When `_sweep` destroys a lease and a later step raises (`cache.save` on a full disk, a non-`RigError` from a probe helper), `refresh` propagates with `ctx.swept` empty and `_report_swept` prints nothing.
   - Proposed fix: move the `extend` to directly after `_sweep` returns.
   - Verdict: correctness bug.

3. `src/rig/commands/serve.py:143` (and `serve.py:134`, `reserve.py:135,412`, `run.py:112,163,255`)
   - Problem: the diff adds a general `ctx.swept` collector in `refresh` and more hand-threaded `merge_swept` plumbing in `serve`, `reserve` and `run`. Every command merges each refresh's `swept` into its result by hand while `engine.refresh` already records every entry on `ctx.swept`. Review 7 item 2 existed because one hand merge was missed.
   - Proposed fix: set `result.swept = merge_swept(ctx.swept)` once in `cli.run` or the result builder and delete the per-command threading.
   - Verdict: simplification.

4. `src/rig/cli.py:338` (`run`, `RigError` branch)
   - Problem: on a `RigError` in JSON mode the swept entries go only to stderr as human lines. The JSON error payload on stdout carries no `swept`, so an agent caller cannot learn which boxes the failing command destroyed. Spec §4.4 line 306 says the JSON carries `warnings` and `swept`. Review 7 finding 4 said "leave the error object unchanged".
   - Proposed fix: add the merged entries to the error dict, for example under `details.swept`, in `emit_error`.
   - Verdict: spec gap, conflicts with review 7 finding 4.

5. `tests/test_cli.py:96`
   - Problem: no test drives `cli.run`'s `except BaseException` branch with a non-empty `ctx.swept`. `test_auto_run_attach_error_survives_broken_stderr` closes stderr with nothing swept, so `_report_swept` prints nothing and the test passes even though the branch would raise with one swept entry.
   - Proposed fix: add a case that expires a lease before the attach raises `OSError` and asserts the `OSError` still propagates, and with stderr open, that the `SWEPT` line was written.
   - Verdict: test coverage.

6. `src/rig/commands/run.py:77` (`release_quietly` docstring)
   - Problem: the docstring says the function returns whether this call destroyed the lease. The new return also reports `True` when the release refresh's sweep destroyed it.
   - Proposed fix: say the sweep counts, or derive `released` from the swept entry in `_released_swept`.
   - Verdict: documentation.

7. `tests/test_serve.py:313`
   - Problem: the literal `rig: SWEPT  l-0000a009 old  expired 2026-10-29T00:59:50Z  destroy failed (provider_error)` duplicates `FAILED_SWEEP` in `tests/test_cli.py`. A change to `swept_lines` formatting needs two edits.
   - Proposed fix: move the constant and `_fail_next_destroy` into `tests/fakes.py` and import from both.
   - Verdict: reuse.

8. `tests/test_run.py:485` (`_contexts`)
   - Problem: `_contexts` re-implements the context capture that `Harness.run` already does with its `holder` list, to reach `ctx.stderr` after an escaping exception.
   - Proposed fix: have `Harness.run` expose the last context and drop the monkeypatch.
   - Verdict: reuse.
