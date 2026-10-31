# `uptime_s` counts from the first `running` sample

**Type**: AFK

**Status:** ✅ Done in 8a7840c

## Parent

`docs/followups-plan.md`, step 2. Decision in `docs/uptime-counts-the-image-pull.md` and serve decision 2 of `docs/serve-decisions.md`.

## What to build

`CachedLease` gains `running_at: int | None`. `engine.refresh` sets it once, on the first sample where the instance row's `actual_status` reads `running`, and leaves it unchanged on later samples. `cur_state` is ignored, since a loading row carries `cur_state: running` beside `actual_status: loading`. `reachable_at` keeps its current meaning. The field round-trips through `leases.json`.

`uptime_s` in `views.py` counts from `running_at` to `uptime_end` and is null without it. A box released while `loading` reports null in `release` and `status`, matching its GPU bill of 0. The table shows a dash. `ReleaseSummary.uptime_s` becomes nullable. `running_at` shows in the `--verbose` extras as ISO time.

## Acceptance criteria

- [x] A lease with `running_at` 20 minutes after `created` reports `uptime_s` measured from `running_at` in `status` and `release`.
- [x] A lease without `running_at` reports `uptime_s: null` in JSON and a dash in the table.
- [x] `engine.refresh` on a `loading` row leaves `running_at` None; the first `running` row sets it to the snapshot time; a later `running` row leaves the value unchanged.
- [x] `running_at` survives a cache save and load.
- [x] `uv run pytest` and `uv run mypy` pass.

## Blocked by

None - can start immediately
