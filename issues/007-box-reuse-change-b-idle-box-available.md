# Box reuse change B: `idle_box_available` warning on creation

**Type**: AFK

**Status:** ✅ Done in 0cce9ab, f70b804 and a94bfbf

## Parent

`docs/followups-plan.md`, step 3. Change B in `docs/box-reuse-decisions.md`.

## What to build

`normalize_instance` in `provider.py` keeps `cuda_max_good` on `Instance` as `cuda_max_good: float | None`.

`state.py` gains `hardware_mismatch(lease, inst, settings, ports) -> list[str]`, returning the keys the lease fails to meet: `gpu` name match, `vram_gb` at or above `vram`, `gpus` equal, `image` equal when the lease records one, `price_per_hr` at or under `max_price`, the instance row's `cuda_max_good` at or above `cuda` when a floor is set, an unknown `vram_gb` or `cuda_max_good` skipping its clause, and requested `ports` present in the mapping when the caller passes them. `flag_mismatch` in `reserve.py` calls it and keeps checking flag-sourced keys only.

`state.py` also gains `reuse_candidates(snap, settings, ttl, now, ports) -> list[tuple[CachedLease, int]]`. A candidate is a lease in the snapshot whose `label.owner` equals `settings.owner`, state `running`, `reachable_at` set, `destroy_pending` false, `guard` full or partial with `startup_exit` 0, `busy` false by the change A helper, `hardware_mismatch` empty and `ttl_remaining` above zero. Each entry carries its shortfall against the requested `ttl`, zero when the lease outlasts it. Tier one is zero shortfall, tier two is positive. Sort tier one first, most time left first, and cap at three.

`reserve_lease` computes candidates from the refreshed snapshot before `choose_offer` on every actual creation, including a `--name` miss, and appends one `idle_box_available` warning per candidate to the result. A name hit emits none. Auto-reserve `run` and `serve` pass the warnings through. Message: `lease l-x (name) is idle: RTX 3060, 1x12 GB, 22m left`; a tier two message adds the shortfall and `extend --to`. Fix: `vasty status l-x`, added to the static fix table. Every caller passes the full requested port list, so a candidate has each one mapped.

## Acceptance criteria

- [x] `normalize_instance` reads `cuda_max_good` from the row and leaves it None when absent.
- [x] `hardware_mismatch` has a test per clause: gpu, vram, gpus, image, price, cuda with a floor, cuda unknown with a floor, cuda unknown without a floor, vram unknown with a floor, ports.
- [x] `flag_mismatch` tests pass unchanged after it calls `hardware_mismatch`.
- [x] `reuse_candidates` excludes a busy lease, a lease of another owner, a `pending` lease, a lease with `destroy_pending`, a lease with `startup_exit` 1 and a lease with zero `ttl_remaining`.
- [x] Four idle candidates yield three warnings, tier one before tier two, most time left first.
- [x] `reserve`, auto-reserve `run` and auto-reserve `serve` on the fake provider each return `idle_box_available` with `fix` equal to `vasty status l-x` when an idle compatible lease exists.
- [x] `reserve --name X` on an existing lease returns `reused: true` and no `idle_box_available`.
- [x] `uv run pytest` and `uv run mypy` pass.

## Blocked by

- #001, since the plan orders step 3 after the foundation
- #002 for `settings.cuda`
- #003 for `serve` resolving settings like `reserve`
- #005 for the `busy` helper
