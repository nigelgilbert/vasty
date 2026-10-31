# Box reuse change A: `status` answers "can I reuse this box"

**Type**: AFK

**Status:** ✅ Done in 85a209d

## Parent

`docs/followups-plan.md`, step 2. Change A in `docs/box-reuse-decisions.md`.

## What to build

Add `busy`, `gpus` and `vram_gb` to `LeaseView`, in JSON and the table, outside `--verbose`. Both `lease_view` and `orphan_view` populate them, so group rendering and history views follow.

`busy` is true when a tracked job is live, false when the box is `running` with no tracked live job, and null when the box is `pending`, `unreachable`, in a history state or an orphan. The field describes jobs vasty started. Add one helper in `state.py`, `busy(lease) -> bool | None`, that counts a job in `running`, `serving` or `unknown` state as busy; change B reuses it.

`gpus` and `vram_gb` come from the cached lease for managed rows and from `num_gpus` and `gpu_ram_gb` for orphans. The table's jobs cell shows `idle` for a running box with no tracked live job. Pending and unreachable boxes keep their current cell. The hardware column shows `2x12` style when `gpus` is above one.

## Acceptance criteria

- [x] `status` JSON on a running lease with a `running` job reports `busy: true`; with no jobs `busy: false`; with one `unknown` job `busy: true`; on a `pending` lease and on an orphan `busy: null`.
- [x] Every `LeaseView` carries `gpus` and `vram_gb`, and an orphan row reports them from the instance row.
- [x] The table jobs cell reads `idle` for a running lease with no live job, and keeps its current text for `pending` and `unreachable`.
- [x] `state.busy` has a unit test per state above.
- [x] Group rendering and a history lease named directly show the three fields.
- [x] `uv run pytest` and `uv run mypy` pass.

## Blocked by

None - can start immediately
