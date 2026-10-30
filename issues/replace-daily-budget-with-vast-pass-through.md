# Replace `daily_budget` with Vast's own balance and charges

Decided 2026-10-30 in `docs/budget-decisions.md`. Follow-up to PR #1.

## Why

`daily_budget` projects spend from an estimate: billed charges plus price times time since the last billing post for each live box. The estimate needed two fixes in one live run. Vast has no daily cap to defer to. It does return `balance` and `credit` from `GET /users/current` and billed rows from `GET /charges/`, and the provider already reads both.

## Change

1. `status` reports `balance`, `credit` and today's billed charges as Vast returns them, with `spend_source: billing`. Drop `spent_today`, `remaining_budget`, `spend_source: estimated` and `spend_source: mixed`.
2. Remove `daily_budget` from config, `budget_exceeded` and `budget_low` from `reserve`, `extend`, `run`, `serve` and `tag`, and the estimator in `src/vasty/budget.py`. `max_price` stays as the per-box guard.
3. Add an optional `min_credit` key in `[defaults]`. When set, `reserve` and `extend` refuse with `credit_low` when credit minus the remaining commitment of live leases would drop under it. Unset means no account-level check.
4. Update the README spend section and the error table.

## Tests

- `status` with charge rows shows Vast's totals unchanged.
- `reserve` with `min_credit` unset never raises `credit_low`.
- `reserve` with `min_credit` 5.00, credit 5.50 and a $1.00 new lease raises `credit_low` with `details` naming credit, committed and `min_credit`.
- `extend` that shortens a lease passes under any `min_credit`.
