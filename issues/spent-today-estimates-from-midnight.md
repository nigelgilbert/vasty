# `spent_today` bills every live box from midnight on a fresh day

Live run 2026-10-29, phase 1, lease `l-ce63a58a`, $0.06/hr.

## Command

```
vasty status
```

## Output

Ten minutes after reserve, with a real balance drop of $0.013:

```json
{"totals": {"spent_today": 1.5, "remaining_budget": 4.5, "spend_source": "mixed"}}
```

Per-lease `cost` on the same call was 0.02, source `mixed`.

## Cause

`spent_today` in `src/vasty/budget.py` estimates each live instance as `dph_total × (now − since)` with `since = max(covered_through, day_start)`. `parse_charges` in `src/vasty/provider.py` sets `covered_through` to the day start when the account has no charge rows yet. A box created minutes ago is then billed from 00:00 UTC: 23.5 h × 0.06 = 1.41.

`lease_cost` in `src/vasty/views.py` clamps the same gap at the lease's `created`, which is why the per-lease figure was right and the total was wrong.

Consequence: under the default daily budget, the first box of the day on a $0.25/hr GPU projects over budget late in the UTC day and `reserve` and `extend` refuse with `budget_exceeded`.

## Fix

Clamp each instance's estimate at its own start time: `since = max(covered_through, day_start, start)`.

1. Add `start_date: int | None` to `Instance` in `src/vasty/models.py`. `normalize_instance` in `src/vasty/provider.py` reads it from the row's `start_date`, which Vast returns on every instance row (see `docs/live/p2c-08-instances.json`).
2. `spent_today` uses `inst.start_date` when present. When absent, fall back to the label's `created` for a vasty lease. With neither, keep today's behavior.
3. `lease_cost` keeps its `created` clamp.

## Tests

- No charge rows, one live instance started 10 minutes ago at $0.06/hr: `spent_today` is 0.01, not 1.41.
- Charge rows covering through T, instance started before T: estimate runs from T.
- Charge rows covering through T, instance started after T: estimate runs from its start.
- Instance with no `start_date` and no label: estimate runs from `covered_through`, as today.
