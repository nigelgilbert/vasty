# Replace `daily_budget` with Vast's own balance and charges

Decided 2026-10-30 in `docs/budget-decisions.md`. Follow-up to PR #1.

## Why

`daily_budget` projects spend from an estimate: billed charges plus price times time since the last billing post for each live box. The estimate needed two fixes in one live run. Vast has no daily cap to defer to. It does return `balance` and `credit` from `GET /users/current` and billed rows from `GET /charges/`, and the provider already reads both.

## Change

1. `status` totals report `balance`, `credit`, `charges_today` and `burn_per_hr`. Drop `spent_today`, `remaining_budget`, `spend_source` and `daily_budget_source`. `credit` is read beside `balance` from `GET /users/current` in `Provider.balance`, which returns `balance` alone today, and both are cached in `CacheData` with the same 60 s freshness as charges.
2. Remove `daily_budget` from config, `budget_exceeded` and `budget_low` from `reserve`, `extend`, `run`, `serve` and `tag`, exit code 3, and `src/vasty/budget.py`. No account-level check replaces them. The account bound is the prepaid balance. `max_price` stays as an offer filter.
3. `lease_cost` in `src/vasty/views.py` returns the billed sum for the instance or null. Drop `cost_source`. The charges query starts at the earlier of today and the oldest active lease's `created`; `CacheData.charges_start` records that start. `release` reports the same figure.
4. README: the spend section says per-box spend is `max_price` times `ttl`, storage and bandwidth bill outside that, and the account bound is the prepaid balance. `cost: null` means Vast has posted no row yet, and `price_per_hr` times `uptime_s` approximates it. Define `balance` and `credit` in one sentence each. Agents read `credit` over `burn_per_hr` for runway. Drop exit code 3 and the `budget_exceeded` row from the error table.

## Tests

- `status` with charge rows shows Vast's totals unchanged, and `credit` beside `balance`.
- `reserve`, `extend`, `run`, `serve` and `tag` make no balance or charges call.
- A config file with `daily_budget` raises `invalid_config` naming the key.
- A lease with no charge row reports `cost: null`; one with rows across two days reports their sum.
