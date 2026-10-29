# Swarm report 10

Work: `docs/review-10.md`, 1 finding (a nit). Branch `spec-validation`. Base commit `58bb487687edcd3bb484417e897daf4c71c42596`. Run without validation (`swarm:implement-no-validate`).

The overseer implemented the one finding in the main checkout. Commit `52ea20f`.

Tests: `.venv/bin/pytest -q` gave `1128 passed, 1 skipped`. The baseline was 1128 passed, 1 skipped. `.venv/bin/mypy --strict` gave `Success: no issues found in 34 source files`.

## Items

### 1. `Harness.run` restores `last_ctx` in an untested `finally`, and its docstring is wrong after a nested run

- Landed: `Harness.run` calls `run(list(argv), make, early_out, early_err)` directly. The `try`/`finally` and its comment are gone. The `last_ctx` docstring reads "The context the latest `run` built, kept when an exception escapes."
- Files: `tests/fakes.py`.
- Commit: `52ea20f`. Tests: the full suite passes with the counts above. The change removes test-harness code only, so no new test applies.

## Findings dropped

None. The finding does not conflict with `spec.md`, and it does not guard against misuse of the user's own configuration.

## Open items

- The deferred item from review-5 stands: a box adopted before the marker existed that loses its cache entry looks like a `reserve` box to the probe. It leaves the account at its clock through the sweep.
