# Budget pass-through

**Type**: AFK

**Status:** ✅ Done in 85633ca and b462d74

## Parent

`docs/followups-plan.md`, step 1a. Decisions in `docs/budget-decisions.md` and `docs/replace-daily-budget-with-vast-pass-through.md`.

## What to build

Replace the spend estimator with Vast's own figures. `status` totals report `balance`, `credit`, `charges_today` and `burn_per_hr`. `Provider.balance` reads `credit` beside `balance` from `GET /users/current`, and `CacheData` caches both with the same 60 s freshness as charges. The provider's fake returns both fields.

Delete the daily budget end to end. Config loses `daily_budget` from `DEFAULT_KEYS`, `SHOWN`, `BUILTIN` and `Settings`; a config file that still carries the key raises `invalid_config` naming it. Delete `src/vasty/budget.py`, `engine.budget_check`, `engine.projection_for`, `engine.spend`, `engine.spend_from`, `budget_exceeded`, `budget_low`, `spend_source`, `daily_budget_source`, `spent_today`, `remaining_budget`, `cost_source`, `RESERVE_BUDGET_HINT`, `_budget_warnings` in `tag`, and exit code 3 from `EXIT_CODES`. `reserve`, `extend`, `run`, `serve` and `tag` make no balance or charges call. `spend_unavailable` stays as a `status` warning when the balance or charges read fails, so a null total is never silent; the `spend_unavailable` error and its exit 2 row go, since nothing raises it. Deleting the estimator removes `instance_start`, which closes finding 4 of the PR #1 code review.

Per-lease `cost` becomes the sum of Vast's charge rows for the instance, or null when none exist. The charges query starts at the earlier of today and the oldest active lease's `created`, and `CacheData.charges_start` records that start, so a lease that crossed midnight UTC reports its lifetime billing. `release` reports the same figure. `burn_per_hr` and the `live` counts stay.

README: the spend section says per-box spend is `max_price` times `ttl`, storage and bandwidth bill outside that, and the account bound is the prepaid balance. `cost: null` means Vast has posted no row yet, and `price_per_hr` times `uptime_s` approximates it. Define `balance` and `credit` in one sentence each. Agents read `credit` over `burn_per_hr` for runway. Drop exit code 3, the `budget_exceeded` row, `budget_low` from the warning codes line, `cost_source` and `spend_source` from the result shapes, and `daily_budget` from the sample config.

## Acceptance criteria

- [x] `grep -rn "daily_budget\|budget_exceeded\|budget_low\|spend_source\|daily_budget_source\|spent_today\|remaining_budget\|cost_source\|budget_check\|spend_from\|instance_start\|RESERVE_BUDGET_HINT" src/ tests/ README.md` returns nothing, and `src/vasty/budget.py` and `tests/test_budget.py` are gone.
- [x] `EXIT_CODES` in `errors.py` has no value 3, and the README exit code line lists 0, 1 and 2.
- [x] `status` with charge rows reports `totals.balance`, `totals.credit`, `totals.charges_today` and `totals.burn_per_hr`, with `charges_today` equal to Vast's billed total unchanged.
- [x] A test asserts `reserve`, `extend`, `run`, `serve` and `tag` make no `balance` or `charges` call on the fake provider.
- [x] A config file with `daily_budget` raises `invalid_config` naming the key.
- [x] A lease with no charge row reports `cost: null`; one with rows across two days reports their sum from `status` and from `release`.
- [x] `status` with a failing charges read reports null totals and a `spend_unavailable` warning, and `errors.py` no longer lists `spend_unavailable` as an error code.
- [x] `CacheData` round-trips `balance`, `credit` and `charges_start` through `leases.json`.
- [x] `uv run pytest` and `uv run mypy` pass.

## Blocked by

None - can start immediately
