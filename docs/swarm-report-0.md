# Swarm report 0

Work: `issues/001-budget-pass-through.md`, `issues/002-cuda-hardware-key.md`, `issues/003-remove-models-table-serve-passthrough.md`.
Branch `refactor/live-run-followups`, base commit `2afb912`. Run without the validation pass.

## Grouping

Two Opus agents ran concurrently in worktrees from `2afb912`. One took 001. The other took 002 then 003, since 003 depends on 002 for the README `cuda = 13` line. All three issues touch `config.py` and the README. One agent for all three would have run past the size budget, so the overseer resolved the overlap at merge.

001 landed by fast-forward. 002 and 003 were cherry-picked on top. The 002 pick conflicted in `SHOWN` in `config.py` and in the `config show` row count in `tests/test_config.py`; the resolution keeps `cuda` and drops `daily_budget`, giving 16 rows. 003 applied cleanly.

## Per item

### 001 Budget pass-through

- Landed: `status` totals report `balance`, `credit`, `charges_today` and `burn_per_hr`. `Provider.balance` returns a `Balance(balance, credit)`. `CacheData` caches `balance`, `credit` and `balance_at` with 60 s freshness. `daily_budget`, `src/vasty/budget.py`, the budget checks in `reserve`, `extend` and `tag`, `budget_exceeded`, `budget_low`, `spend_source`, `cost_source`, the `spend_unavailable` error and exit code 3 are gone. `spend_unavailable` stays as a `status` warning. Per-lease `cost` and `release` report the sum of Vast's charge rows for the instance, or null.
- One charges read serves both figures. The query starts at 00:00 UTC of the earlier of now and the oldest lease's `created`. `parse_charges` sums every row per instance for `cost` and sums the rows that start today for `charges_today`.
- README: the "Bounded spend" bullet is removed and `## Budget` is now `## Spend`, with the content the issue lists.
- Files: `src/vasty/{budget.py (deleted), cache.py, config.py, engine.py, errors.py, models.py, provider.py, state.py, timeutil.py, views.py}`, `src/vasty/commands/{extend.py, release.py, reserve.py, status.py, tag.py}`, `tests/fakes.py`, `tests/test_budget.py` (deleted) and ten other test files, `README.md`.
- Commits: `85633ca`, `b462d74`.
- Tests on the agent branch: `uv run pytest` 1091 passed, 1 skipped. `uv run mypy` clean.
- Judgment calls:
  - The charges window starts on a UTC day boundary, since the provider filters on Vast's `day` field.
  - History leases widen the window too, so released leases in `status --verbose` and `release` report full billing.
  - The `daily_budget` rejection test builds the key name at runtime so the acceptance grep stays empty.

### 002 `cuda` hardware key

- Landed: `cuda` in `DEFAULT_KEYS`, `PROFILE_KEYS`, `FLAG_KEYS` and `SHOWN`, as `Settings.cuda`, `VASTY_CUDA` and `--cuda FLOOR` on `reserve`, `run`, `serve` and `config show`. `--on` rejects it as a creation flag. `OfferQuery.cuda` feeds `cuda_max_good: {"gte": cuda}` in `build_offer_query`. `no_offers` names `cuda>=N` and suggests a lower `--cuda`. The README hardware flags line lists `--cuda FLOOR` and points at `NVIDIA_REQUIRE_CUDA`.
- Files: `src/vasty/{cli.py, config.py, models.py, provider.py}`, `src/vasty/commands/reserve.py`, `tests/{test_cli.py, test_config.py, test_provider.py, test_reserve.py}`, `README.md`.
- Commit: `8e922bf`, cherry-picked from `2d57b46` with the conflict resolution above.
- Tests after the pick: `uv run pytest` 1109 passed, 1 skipped. `uv run mypy` clean.
- Judgment call: `flag_mismatch` does not compare `--cuda`, since leases record no CUDA field yet. Box reuse change B covers it.

### 003 Remove the models table and add `--` passthrough on `serve`

- Landed: `BUILTIN_MODELS`, `ModelEntry`, `MODEL_KEYS`, `MODEL_LAYER_KEYS`, the `model` layer, `model_unknown`, `--quant`, `ctx.model`, `model_entry` and `Settings.models` are gone. A `models` table and `config set models.NAME.KEY` raise `invalid_config`. `serve` resolves settings through `ctx.settings` like `reserve`. Tokens after `--` append to the `vllm serve` argv and the shown `cmd`. `check_extra` rejects `--host`, `--port` and `--api-key` in both forms before any provider call. The `vllm_missing` hint names `--image vllm/vllm-openai:v0.32.0`. `VLLM_IMAGE` moved to `serve.py`.
- README: sample config has `[profiles.train]` and `[profiles.vllm]` with `image`, `vram = 24` and `cuda = 13`. The serve example uses `--profile vllm --model Qwen/Qwen3-14B-AWQ` with a second `-- --max-model-len 16384` line. The models section, the `model_unknown` row and the `[models]` resolution entry are gone.
- Files: `src/vasty/{cli.py, config.py, context.py, errors.py}`, `src/vasty/commands/serve.py`, `tests/{test_config.py, test_integration.py, test_serve.py}` and related tests, `README.md`.
- Commit: `931bab7`, cherry-picked from `c371006`.
- Judgment calls:
  - The README `[profiles.big]` became `[profiles.train]`.
  - `check_extra` treats underscores as dashes, so `--api_key` is rejected as well.
  - `search_offers` never carries the image, so the profile test checks `vram` and `cuda` on the query and `image` on the create request.
  - The models-table test writes the table with dotted keys and an inline table so the `[models` grep stays empty.

### Follow-up commit

`8099123` updates the README test count to 1118 and marks the three issue Status lines done.

## Final check

On `8099123`: `uv run pytest` 1118 passed, 1 skipped. `uv run mypy` clean on 33 source files. The 001 and 003 acceptance greps return nothing. `src/vasty/budget.py` and `tests/test_budget.py` are gone. `grep -c "Qwen/Qwen3-72B-Instruct" README.md` returns 0, and `grep -n NVIDIA_REQUIRE_CUDA README.md` returns one line.

## Findings dropped

None. No item was dropped as a guard against user misconfiguration.

## Open items

- The README defines `balance` as what the account owes Vast beyond its credit, billed to a saved card. This comes from the live run, where balance stayed 0 while credit fell. Confirm it in the live run, issue 009.
- `reserve --cuda abc` makes one `list_instances` call before it raises `invalid_arguments`, since `reserve` resolves settings after refresh. `run` and `serve` make no provider call.
