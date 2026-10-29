# Swarm report 9

Work: `docs/review-9.md`, 3 findings (2 gaps, 1 nit). Branch `spec-validation`. Base commit `34d2a815e3db1931fd0cea577265b094608f63fd`. Run without validation (`swarm:implement-no-validate`).

Two Opus agents ran in worktrees, grouped by file:

- Group A, findings 1 and 3: `cli.py`, `tests/fakes.py`, `tests/test_cli.py`, `tests/test_run.py`. Commit `55b041e`.
- Group B, finding 2: `engine.py`, `tests/test_engine.py`. Commit `c260561`.

Findings 1 and 3 shared `tests/test_run.py`, so one agent took both.

Tests: `.venv/bin/pytest -q` gave `1128 passed, 1 skipped`. The baseline was 1124 passed, 1 skipped. `.venv/bin/mypy --strict` gave `Success: no issues found in 34 source files`.

## Items

### 1. `_report_swept` writes to stderr unguarded

- Landed: `_report_swept` wraps its print loop in `try`/`except Exception: pass`, as the review wrote it.
- Files: `src/rig/cli.py`, `tests/test_cli.py`, `tests/test_run.py`.
- Commit: `55b041e`. Tests: `test_failing_run_with_closed_stderr_keeps_json_error` in `tests/test_cli.py`, verbatim with `import io` added. `test_attach_error_reports_sweep_on_stderr` and `test_attach_error_with_sweep_survives_broken_stderr` in `tests/test_run.py` read `harness.last_ctx` per finding 3. Removing the guard fails the closed-stderr JSON test and the broken-stderr attach test. Removing the `except BaseException:` branch fails `test_attach_error_reports_sweep_on_stderr`.

### 2. `refresh` records its sweep only after the probes and the cache save

- Landed: `ctx.swept.extend(swept)` sits directly after the `_sweep` call in `engine.refresh`. No docstring names the point where `ctx.swept` grows, so none changed.
- Files: `src/rig/engine.py`, `tests/test_engine.py`.
- Commit: `c260561`. Test: `test_refresh_records_sweep_before_a_failing_save`, verbatim. With `engine.py` at the base it fails with `assert [] == [('l-0000a009', True)]`.

### 3. `_contexts` duplicates the context capture in `Harness.run`

- Landed: `Harness` has the field `last_ctx: Context | None = None`. `Harness.run` sets it to None on entry and to `ctx` in `make`. `_contexts` is gone, and the two existing attach-error tests read `harness.last_ctx` and drop the unused `monkeypatch`. `tests/test_run.py` drops the unused `Context` import.
- Deviation: `Harness.run` keeps `holder` for its return path and sets `last_ctx` back to `holder[0]` in a `finally` around `cli.run`. Tests in `tests/test_extend.py` and `tests/test_reserve.py` call `h.run` from a hook inside an outer run. Without the restore, the inner call leaves its own context in `last_ctx`, and 6 tests failed when the return path read it. The `finally` also keeps the context when an exception escapes.
- Files: `tests/fakes.py`, `tests/test_run.py`.
- Commit: `55b041e`.

## Findings dropped

None. No finding conflicted with `spec.md`, and none guards against misuse of the user's own configuration.

## Open items

- The deferred item from review-5 stands: a box adopted before the marker existed that loses its cache entry looks like a `reserve` box to the probe. It leaves the account at its clock through the sweep.
