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

The image pull took 20m35s of the 23 minutes. Vast's charges for the day bill instance 58355222 for `gpu` 0.060 hours and `disk` 0.394 hours. The two boxes released while `loading` bill `gpu` 0.0.

## Cause

`uptime_s` in `src/vasty/views.py` subtracts the label's `created` from `uptime_end`. Vast bills disk from create and GPU from `running`, and no instance field marks the move: `start_date` equals the create time (1793338271.86 against `created=1793338271`), `duration` is seconds since `start_date`, `status_msg` goes from null to `success, running <image>` with no timestamp, and `uptime_mins` is null on every row.

## Fix

1. The lease cache records `running_at`, the time vasty first saw the instance `running`. `engine.refresh` sets it on the first sample where `actual_status` reads `running`, which lands before the ssh readiness wait ends. The loading row carries `cur_state: running` beside `actual_status: loading`, so `cur_state` is left alone. `reachable_at` stays as it is: `_apply_probe` in `src/vasty/engine.py` rewrites it on every answered probe, so it holds the last probe time.
2. `uptime_s` counts from `running_at` and is null without it. A box released while `loading` reports null, matching its GPU bill of 0. `cost` and `spent_today` are covered by `issues/replace-daily-budget-with-vast-pass-through.md`, which reports Vast's billed figures and drops the estimate.

`running_at` has the granularity of vasty's sampling. A `reserve --wait` poll sets it within one interval; a `--no-wait` box gets it at the next command that refreshes. `uptime_s` is elapsed time since that sample and includes any interval the box spent stopped.

## Tests

- A lease with `running_at` 20 minutes after `created` reports `uptime_s` from `running_at`.
- A lease without `running_at` reports `uptime_s` null in JSON and a dash in the table.
- `engine.refresh` sets `running_at` once and leaves it unchanged on later `running` samples.
