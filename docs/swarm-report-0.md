# Swarm report 0: live run defects

Work files: `issues/serve-runs-the-image-vllm.md`, `issues/spent-today-estimates-from-midnight.md`. Base commit `5c17670` on `fix/live-run-defects`. Two Opus implementers, one validation round with GPT-6.1 Sol, three Opus fixers.

## Items

### 1. `serve` runs the vLLM the image ships

Landed in `e28f372`. The venv install path is gone: `VENV`, `DEFAULT_VLLM`, `INSTALL_TIMEOUT_S`, `INSTALL_HINT`, `_TAG_VERSION`, `vllm_pin`, `install_command` and `_install` are deleted. `server_argv` launches `vllm` from PATH. `_preflight` runs `command -v vllm` with a 30 s timeout before `start_job` and raises `vllm_missing` with the issue's message and hint. `vllm_missing` exits 1. The builtin entry's image is `vllm/vllm-openai:v0.32.0`. README error table, serve section and Status updated.

Files: `src/vasty/commands/serve.py`, `src/vasty/errors.py`, `src/vasty/config.py`, `README.md`, `tests/test_serve.py`, `tests/test_config.py`, `tests/test_integration.py`.

Tests: the four tests the issue names plus `test_serve_pin_from_config_entry` removed. Added `test_serve_vllm_missing_on_box`, `test_serve_vllm_present_starts_job`, `test_serve_vllm_missing_releases_reserved_box`. `uv run pytest -q`: 1128 passed, 1 skipped at that commit.

Live acceptance (Phase 5 rerun and the plain-image negative check) is unrun. The plan now carries both steps.

### 2. `spent_today` bills every live box from midnight

Landed in `b108291`. `Instance.start_date: int | None = None`; `normalize_instance` reads the row's `start_date` with `_to_int`. `budget.instance_start` returns `start_date`, else the `created` of a label that parses as `Label`, else None. `spent_today` runs each instance's estimate from `max(covered_through, day_start, start)` capped at `now`. `lease_cost` is unchanged. `FakeProvider.create` sets `start_date`.

Files: `src/vasty/budget.py`, `src/vasty/models.py`, `src/vasty/provider.py`, `tests/fakes.py`, `tests/test_budget.py`, `tests/test_provider.py`, `tests/test_engine.py`.

Tests: the issue's four cases plus future start, label fallback, `start_date` over label, and four unusable labels. `test_spend_sources_and_charges_cache` expected value changed from 1.30 to 1.10, the correct total under the clamp. `uv run pytest -q`: 1141 passed, 1 skipped after merge.

## Validation

Write-up: `docs/validation-0.md`, committed as `a0774c0`. Verdict: ready after fixes. 0 blockers, 2 gaps, 7 nits. One exchange of a cap of three. No disagreements.

## Consensus findings fixed

All nine agreed findings were fixed. Exchanges run: 1.

| Finding | Commit |
|---|---|
| 1. Dead python3-venv probe in `onstart._installer` and its two tests | `38825b4` |
| 2. Live-test plan Phase 5 reserves from the vLLM image, adds the `vllm_missing` negative check, drops the install text and the midnight bullet | `2bb4771` |
| 3. `VLLM_IMAGE` defined once in `config.py` | `38825b4` |
| 4. Engine spend test with `start_date` after the label's `created` | `20ab668` |
| 5. Serve preflight `box_unreachable` test, `--on` and auto-reserve | `38825b4` |
| 6. Serve test that reads a user `[models]` entry | `38825b4` |
| 7. Budget test for a start before `day_start` | `20ab668` |
| 8. README serve paragraph no longer restates the error-table row | `38825b4` |
| 9. `test_engine.py` comment is one sentence | `20ab668` |

## Unreviewed fixes

The three fix commits above (`20ab668`, `2bb4771`, `38825b4`) and the README test-count edits in `2c012c5` and the report commit. The plan agent also updated section 2's image bullet, the Phase 5 cost row (2 boxes, 40m), the bandwidth estimate (14 boxes, 88 GB) and the total ($1.76 to $2.73) for the larger vLLM image and the extra `pl` box.

## Findings dropped

See `docs/validation-0.md`, Dropped. Summary: hint omits `--vram` (issue prescribes the hint); shell-quote the model in the hint (user decision: batteries included); preflight before `_public_url` (preference); "serve is unverified" Status bullet (issue prescribes dropping it); drop the `python3` essential (user commands use it); PATH divergence between tmux and the preflight (fails loudly); nonexistent model id and `serve_failed` row text (issue scope and prescribed text); README lines outside the range.

## Disagreements

None.

## Open items

- Rerun Phase 5 of `docs/live-test-plan.md` on real hardware, with the negative check.
- Design questions from `docs/live-test-memo.md`: the `Qwen/Qwen3-72B-Instruct` model id, the log tail in `serve_failed.details`, expired leases in default `status`.

## Final state

`uv run pytest -q`: 1143 passed, 1 skipped. `uv run mypy`: no issues in 34 source files.
