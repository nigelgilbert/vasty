# Box reuse decisions

2026-10-30. Strategy for spend guards and box reuse, with the plan for the first two reuse changes. Reviewed by GPT-6 Astra; the review's accepted points are folded in below.

## Decisions

1. `daily_budget` is retired for a pass-through of Vast's balance and charges, with an optional `min_credit` floor. Recorded in `docs/budget-decisions.md` and filed as `issues/replace-daily-budget-with-vast-pass-through.md`.
2. The spend model is rate cap, time cap, count cap, prepaid credit. `max_price` bounds dollars per hour per box. `ttl` bounds hours per box through the watchdog and sweep. `max_boxes` bounds live boxes per owner and is unfiled.
3. The remaining failure is fan-out: an agent reserves a box while one it owns sits idle. Reuse already works through `reserve --name`, `run --on` and `serve --on`. The gap is visibility before creation and a prompt after it. This doc plans those two changes.

## Change A: `status` answers "can I reuse this box"

Add to `LeaseView` in JSON and the table, outside `--verbose`:

- `busy`: true when a tracked job is `running` or `serving`, false when the box is running with no tracked live job, null when the box is pending, unreachable or an orphan. The field describes jobs vasty started. SSH sessions and processes started by hand are invisible to it.
- `gpus` and `vram_gb`: per-GPU VRAM beside the count, so an agent can tell a 2x12 from a 1x24. Neither is in `status` today, verbose or plain.

Table: the jobs cell shows `idle` for a running box with no tracked live job. Pending and unreachable boxes keep their current cell.

Both `lease_view` and `orphan_view` in `views.py` build `LeaseView`, so both change. Group rendering and history views follow.

Staleness: `_merge_jobs` keeps a cached job the probe stops reporting. A job whose state is `unknown` counts as busy.

## Change B: `idle_box_available` warning on creation

Emitted by `reserve`, auto-reserve `run` and auto-reserve `serve` on every actual creation, including a `--name` that misses. Suppressed on a name hit, which already returns the existing lease.

A candidate is a lease in the snapshot that meets all of:

- `label.owner` equals `settings.owner`
- state `running`, `reachable_at` set, `destroy_pending` false, `guard` full or partial with `startup_exit` 0
- `busy` false
- hardware compatible with the resolved settings, whatever their source: `gpu` name match, `vram_gb` at or above `vram`, `gpus` equal, `image` equal when the lease records one, `price_per_hr` at or under `max_price`, requested `ports` present in the mapping when `serve` is the caller
- `ttl_remaining` above zero

Candidates sort into two tiers. Tier one has `ttl_remaining` at or above the requested `ttl`. Tier two is shorter and the message names the shortfall and `extend --to`. At most three warnings, tier one first, most time left first.

The hardware comparison is a shared function in `state.py` that returns the list of mismatched keys. `flag_mismatch` in `reserve.py` and this check both call it, so the two stay aligned. `flag_mismatch` keeps its own behaviour of checking flag-sourced keys only.

The warning's `lease` is the candidate. Message: `lease l-x (name) is idle: RTX 3060, 1x12 GB, 22m left`. Fix: `vasty status l-x`. The README promises every `fix` is runnable, and a `run --on` or `serve --on` fix would rerun the work on a second box. `make_warning` keeps its static fix table.

The warning rides on the result of the command that created the box. Creation proceeds. For attached `run` the warning arrives after the job and the release, so for that command it informs the next decision. Change A is the preventive half.

Disk and region are omitted from the comparison. The lease cache records neither. Reuse of a box with less disk than a job needs fails at the job, where the error names the disk.

## Agent guidance

Add to the README under "For agents" and to the skill:

Run `vasty status` before reserving. Reuse a lease with `--on` when it is yours, `state` is `running`, `busy` is false, `gpu`, `vram_gb` and `gpus` cover the job, and `ttl_remaining_s` covers the job or `extend` can. `run --on` leaves the lease up after the job. Auto-reserved attached `run` releases it.

## Out of scope

- A `--reuse` flag that picks a candidate automatically. Revisit if the warning fires often in practice.
- `max_boxes`. Its refusal hint lists candidates with the same predicate.
- Reserving idle capacity across machines. The snapshot is advisory and two agents can both pick the same idle box.

## Work

1. `models.py`: `busy`, `gpus`, `vram_gb` on `LeaseView`. `views.py`: populate in `lease_view` and `orphan_view`. `status.py`: `idle` in the jobs cell. Tests for running with jobs, running idle, unknown job, pending, orphan, group rendering.
2. `state.py`: `hardware_mismatch(lease, settings, ports) -> list[str]`, `reuse_candidates(snap, settings, ttl, now, ports) -> list[tuple[CachedLease, int]]` returning each candidate with its shortfall. `reserve.py`: `flag_mismatch` calls `hardware_mismatch`. Tests for each predicate clause, tier ordering, cap at three, name hit suppression.
3. `reserve.py`: compute candidates before `choose_offer` from the refreshed snapshot, append warnings to the result. `run.py` and `serve.py` pass through on the auto path. Tests on the fake provider for each of the three commands.
4. README: `status` fields, warnings table row, agent guidance. Skill text.

## Astra review, disposition

Accepted: fix is `vasty status`; `busy` is nullable and documents tracked jobs only; `unknown` counts as busy; shared hardware comparison instead of copying `flag_mismatch`; `gpus` beside `vram_gb`; both view builders change; candidates carry a shortfall instead of a boolean; two tiers for TTL; warn on every creation including a `--name` miss; stricter agent guidance; the attached `run` timing caveat.

Declined: validating disk and region. The cache lacks both, and the job error already names a disk shortfall.
