# Swarm report 0

Run of `swarm:implement-no-validate` on issues 004 to 008, branch `refactor/live-run-followups`, base `fe08718`. Each issue ran in one Opus subagent in its own worktree. The overseer read each diff, cherry-picked it onto the branch, reran the tests and marked the issue's Status line. No validation pass ran.

Order: 004 and 006 in parallel, then 005, then 007, then 008.

Final checks on the last code commit: `uv run pytest` 1168 passed, 1 skipped. `uv run mypy` clean on 33 source files.

## Per item

### 004 `uptime_s` from the first `running` sample

`CachedLease.running_at` is set by `engine.refresh` on the first `actual_status` `running` sample and kept after. `views.uptime_s` counts from it and returns None before it. `LeaseView` gains `uptime_s`, the `status` table gains an `UPTIME` column with a dash for null, and `--verbose` shows `running_at`.

- Commit: `8a7840c`
- Files: `models.py`, `engine.py`, `views.py`, `commands/status.py`, `tests/test_engine.py`, `tests/test_cache.py`, `tests/test_status.py`, `tests/test_release.py`
- Tests: 1119 passed, 1 skipped in the worktree; 1122 after merging with 006.

### 005 Box reuse change A

`state.busy(lease)` returns None outside `running`, else whether a job is `running`, `serving` or `unknown`. `LeaseView` gains `gpus`, `vram_gb` and `busy`, filled by `lease_view` and `orphan_view`. The jobs cell reads `idle` when `busy` is false. The GPU cell reads `2x12 3060` when `gpus` is above one. `_lease_gpu` is deleted.

- Commit: `85a209d`
- Files: `models.py`, `state.py`, `views.py`, `commands/status.py`, `tests/test_state.py`, `tests/test_status.py`
- Tests: 1137 passed, 1 skipped.

### 006 Serve diagnostics

`LOG_LINES` lives in `remote.py`. `server_argv` drops the key, and the job script exports `VLLM_API_KEY` ahead of `vllm serve`. `_serve_failed` reads the tail once on either failure path, redacts the key, keeps the last 64 KiB and returns `serve_failed` with `exit`, `lease` and `log_tail`. On the deadline it runs before `TERM`. The `vllm_missing` hint under `--on` names the lease and `run --on` or `ssh`.

- Commits: `f6adf3c`, `abd6279`, `f3609ee`, `c1b26e8`
- Files: `commands/serve.py`, `commands/status.py`, `remote.py`, `tests/fakes.py`, `tests/test_serve.py`, `tests/test_integration.py`
- Tests: 1118 passed, 1 skipped in the worktree.

### 007 Box reuse change B

`Instance.cuda_max_good` is read by `normalize_instance`. `state.hardware_mismatch` holds the shared comparison, and `flag_mismatch` keeps the flag-sourced keys from it. `state.reuse_candidates` returns up to three idle leases with their TTL shortfall, tier one first. `reserve_lease` adds one `idle_box_available` warning per candidate on every creation, with fix `vasty status l-x`. `serve` passes port 8000. `run` already passed warnings through.

- Commits: `0cce9ab`, `f70b804`, `a94bfbf`
- Files: `models.py`, `provider.py`, `state.py`, `commands/reserve.py`, `commands/serve.py`, `tests/fakes.py`, `tests/test_provider.py`, `tests/test_state.py`, `tests/test_reserve.py`, `tests/test_serve.py`, `tests/test_integration.py`
- Tests: 1168 passed, 1 skipped. Existing `flag_mismatch` tests pass with no edits.

### 008 README and skill text

Two-line pitch, `max_price` as an offer filter, reuse guidance under "For agents", `idle_box_available` in the warning codes, `busy`, `gpus`, `vram_gb` and `uptime_s` on the `status` row, `serve_failed` details, `VLLM_API_KEY` in the serve section, account-level spend limits in Non-goals, test count 1168. The repo has no separate skill file, so "For agents" is the skill text. The result shapes table was checked field by field against `models.py`, and the error table against `EXIT_CODES`.

- Commits: `53f26c8`, `61ff9d6`
- Files: `README.md`
- Tests: 1168 passed, 1 skipped.

## Findings dropped

- Declined, out of scope: README prose on the `status` table's `idle` and `2x12` cells. The overseer removed it in `61ff9d6`.
- Declined, out of scope: the `--bind-local` readiness poll sends the key in a `curl -H` command over ssh, which shows on the box's process list for a moment. 006 does not name it.

## Open items

- Commit trailer. The run brief named `Claude Fable 5.1`. The commits carry `Claude Opus 5.5`, the model that wrote them. Amend if the brief's line is wanted.
- `a938a02`, which checks off the 001 to 003 criteria, landed on the branch from outside this run. The overseer checked off the 004 to 008 criteria to match.
- 004: `status` had no `uptime_s` before. The criteria call for it in JSON and the table, so `LeaseView.uptime_s` and the `UPTIME` column are new.
- 004: `release` human output still prints `?` for a null `uptime_s`.
- 005: the GPU cell format moved from `2× 3060` to `2x12 3060`, with VRAM truncated to whole GB. Orphans now show their real GPU count.
- 005: the `status --group` jobs cell still reads `idle` for pending and unreachable leases.
- 006: the deadline case now carries `exit: null`. Before it had no `details`.
- 006: a failed tail read means `VastyError` or `OSError`, the pair `status` already catches.
- 006: `_Plan` gains `auto` to pick the `vllm_missing` hint.
- 007: `reserve_lease` gains a `reuse_ports` keyword, which only `serve` passes.
- 007: `flag_mismatch` takes the instance row and now reports `--cuda` on a `--name` hit whose host falls short of a `--cuda` flag.
- 007: `_gpu_matches` moved to `state.gpu_matches`, shared by `hardware_mismatch` and `_offer_ok`.
- 007: the guard clause has no explicit check, since `state.guard` returns only `full` or `partial`.
- 007: the tier two message appends `, 10m short; extend --to 1h`, with the requested TTL as the `--to` value.
- 008: the `tag` row in the result shapes table is split out to match `TagResult` and `TagEntry`.
- 008: the Spend section's first sentence drops its `max_price` clause, now stated in the intro.
