# `uptime_s` counts the unbilled image pull

Live run 2026-10-30, lease `l-b5c8ea2b`, RTX 3060 at $0.08/hr. Decided in `docs/serve-decisions.md`, decision 2.

## Command

```
vasty release sv
```

## Output

```json
{"lease": "l-b5c8ea2b", "name": "sv", "uptime_s": 1380, "cost": 0.04, ...}
```

The balance dropped $0.007 over the box's life. The image pull took 20m35s of the 23 minutes.

## Cause

`uptime_s` in `src/vasty/views.py` subtracts the label's `created` from `uptime_end`. `lease_cost` multiplies that span by `price_per_hr` when no billed row covers the lease. `spent_today` in `src/vasty/budget.py` clamps its estimate at Vast's `start_date`. `start_date` equals the create time: instance 58355222 reported `start_date` 1793338271.86 against `created=1793338271`. Vast bills no GPU time while an instance is `loading`, so all three count the pull.

## Fix

1. The lease cache records `running_at`, the time vasty first saw the instance `running`. `engine.refresh` sets it on the first sample where the provider reports `running`, which lands before the ssh readiness wait ends. `reachable_at` stays as it is: `_apply_probe` in `src/vasty/engine.py` rewrites it on every answered probe, so it holds the last probe time.
2. `uptime_s` counts from `running_at`, falling back to `created`. `cost` and `spent_today` are covered by `issues/replace-daily-budget-with-vast-pass-through.md`, which reports Vast's billed figures and drops the estimate.

## Tests

- A lease with `running_at` 20 minutes after `created` reports `uptime_s` from `running_at`.
- A lease without `running_at` keeps the current numbers.
