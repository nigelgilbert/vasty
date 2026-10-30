# Replace `daily_budget` with Vast's own balance and charges

Decided 2026-10-30 in `docs/budget-decisions.md`. Follow-up to PR #1.

## Why

`daily_budget` projects spend from an estimate: billed charges plus price times time since the last billing post for each live box. The estimate needed two fixes in one live run. Vast has no daily cap to defer to. It does return `balance` and `credit` from `GET /users/current` and billed rows from `GET /charges/`, and the provider already reads both.

## Change

1. `status` reports `balance`, `credit` and today's billed charges as Vast returns them. Drop `spent_today`, `remaining_budget` and `spend_source`. `credit` is read beside `balance` from `GET /users/current` in `Provider.balance`, which returns `balance` alone today, and both are cached in `CacheData` with the same 60 s freshness as charges.
2. Remove `daily_budget` from config, `budget_exceeded` and `budget_low` from `reserve`, `extend`, `run`, `serve` and `tag`, and the estimator in `src/vasty/budget.py`. `max_price` stays as the per-box guard.
3. Add an optional `min_credit` key in `[defaults]`. When set, `reserve` and `extend` refuse with `credit_low` when credit minus the remaining commitment of live leases would drop under it. Unset means no account-level check.
4. `lease_cost` in `src/vasty/views.py` returns the billed sum for the instance or null. Drop `cost_source`. The charges query starts at the earlier of today and the oldest active lease's `created`; `CacheData.charges_start` records that start.
5. Update the README spend section and the error table.

## Tests

- `status` with charge rows shows Vast's totals unchanged.
- `reserve` with `min_credit` unset never raises `credit_low`.
- `reserve` with `min_credit` 5.00, credit 5.50 and a $1.00 new lease raises `credit_low` with `details` naming credit, committed and `min_credit`.
- `extend` that shortens a lease passes under any `min_credit`.
- A lease with no charge row reports `cost: null`; one with rows across two days reports their sum.
