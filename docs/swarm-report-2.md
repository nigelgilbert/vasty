# Swarm report 2

Work: findings 1 to 5 of `docs/review-2.md`.
Branch `refactor/live-run-followups`, base commit `30a358f`. Run without the validation pass.

## Grouping

Four Opus agents ran concurrently in worktrees from `30a358f`, one per file group:

- A: finding 1, over `README.md`.
- B: finding 2, over `cache.py` and `tests/test_cache.py`.
- C: findings 3 and 4, over `engine.py` and `tests/test_engine.py`.
- D: finding 5, over `tests/test_config.py`.

The groups share no file. Every commit was cherry-picked onto the branch in the order A, B, C, D with no conflict. Each agent passed on the first report, so no corrections went back.

## Per item

### 1. README `cost` paragraph misstates null and exposes query mechanics

- Landed: the paragraph now reads the fix text word for word. No other README line changed.
- Files: `README.md`.
- Commit: `94f0f0d`.
- Item note: issue 001 says "`cost: null` means Vast has posted no row yet, and `price_per_hr` times `uptime_s` approximates it." The review says "`cost` is null when no charge row is available, and `status` warns `spend_unavailable` when the read failed." The README follows the review. The issue's sentence misses the failed-read and `status --cached` cases.

### 2. Delete the old-cache-shape shim

- Landed: `decode` loses the `raw_charges` line, the `"today" not in raw_charges` block and its comment. `test_charges_without_today_load_as_absent` is gone. `Charges.today` keeps its `Decimal("0")` default in `models.py`, so old caches still load.
- Files: `src/vasty/cache.py`, `tests/test_cache.py`.
- Commit: `00e2e96`.

### 3. Make `read_charges` and `read_balance` set the snapshot and return None

- Landed: both helpers are annotated `-> None`. Early exits use bare `return` and the trailing value returns are gone. The summaries read "Set `snap.charges` to Vast's charges from `charges_start` to now." and "Set `snap.balance` to Vast's balance and credit." Four tests in `tests/test_engine.py` now assert on `snap.charges` or `snap.balance`. The production callers in `release.py` and `status.py` already ignored the return.
- Files: `src/vasty/engine.py`, `tests/test_engine.py`.
- Commit: `ba8b7b7`.

### 4. Cut the `charges_start` docstring to one sentence

- Landed: the docstring is `"""Return 00:00 UTC of the earlier of `now` and the oldest cached lease's `created`."""`. The line runs 91 characters.
- Files: `src/vasty/engine.py`.
- Commit: `ba8b7b7`, shared with finding 3.

### 5. Delete the removed-budget env test

- Landed: `test_removed_budget_key_in_env_is_ignored` is gone. `test_removed_budget_key_is_invalid_config` and `REMOVED_BUDGET_KEY` stay.
- Files: `tests/test_config.py`.
- Commit: `caff377`.

### README test count

- Landed: the README test count reads 1115, matching the two deleted tests.
- Files: `README.md`.
- Commit: `7fc0a42`.

## Tests

On `7fc0a42`: `uv run pytest` gives 1115 passed, 1 skipped. `uv run mypy` reports no issues in 33 source files. The two-test drop from 1117 matches findings 2 and 5.

## Findings dropped

None of findings 1 to 5. The review's own dropped list stands as written.

## Open items

None.
