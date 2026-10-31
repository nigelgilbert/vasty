# Remove the models table and add `--` passthrough on `serve`

**Type**: AFK

**Status:** ✅ Done in 931bab7

## Parent

`docs/followups-plan.md`, step 1b items 2 to 4. Serve decision 3 of `docs/serve-decisions.md`.

## What to build

Delete the `[models]` table. Remove `BUILTIN_MODELS`, `ModelEntry`, `MODEL_KEYS`, `MODEL_LAYER_KEYS`, `models` from `TABLE_KEYS`, the `model` layer in `resolve`, `model_unknown`, `--quant`, `ctx.model`, `model_entry` in `serve`, and `Settings.models`. A config file with a `[models]` table raises `invalid_config` naming the table, and `config set models.NAME.KEY` raises `invalid_config`. `serve` resolves settings the same way `reserve` does: flags, stdin JSON, profile, env, files, defaults. `serve --model X` with no profile and no `--image` reserves on `defaults.image`, finds no `vllm`, releases the box and reports `vllm_missing`. The `vllm_missing` hint names `--image vllm/vllm-openai:v0.32.0`. The `vllm` profile is README sample config, so no hint names it.

Add `--` passthrough to `serve` with the same split `run` uses. Tokens after `--` are appended to the `vllm serve` argv after the model name, and the displayed `cmd` shows them. `--host`, `--port` and `--api-key` among them, in either `--flag value` or `--flag=value` form, raise `invalid_arguments` before any provider call, since `serve` owns the endpoint and the key.

README: the sample config gains a `train` profile and a `vllm` profile, the latter with `image = "vllm/vllm-openai:v0.32.0"`, `vram = 24` and `cuda = 13`. The serve example becomes `vasty serve --profile vllm --model Qwen/Qwen3-14B-AWQ --ttl 1h`, with a second line showing `-- --max-model-len 16384`. One sentence says a box reserved with a startup hook that installs `vllm`, or one set up through `run --on`, can serve with `serve --on`. Drop the models section, the `model_unknown` row, `--quant` from the command table, and the `[models]` entry from the resolution order line.

## Acceptance criteria

- [x] `grep -rn "BUILTIN_MODELS\|ModelEntry\|MODEL_KEYS\|MODEL_LAYER_KEYS\|model_unknown\|model_entry\|ctx\.model\|\"quant\"\|--quant\|\[models" src/ tests/ README.md` returns nothing.
- [x] A config file with a `[models."X"]` table raises `invalid_config` naming `models`.
- [x] `serve --profile vllm --model Qwen/Qwen3-14B-AWQ` on the fake provider sends the profile's `vram`, `image` and `cuda` to `search_offers`.
- [x] `serve --model X -- --max-model-len 16384` starts a job whose command ends with `--max-model-len 16384`.
- [x] `serve --model X -- --port 9000`, `-- --host 0.0.0.0` and `-- --api-key=k` each raise `invalid_arguments` with zero calls on the fake provider.
- [x] `serve --model X` with no `--image` and no profile on a box without `vllm` releases the box and raises `vllm_missing` with a hint that names `--image vllm/vllm-openai:v0.32.0`.
- [x] The README sample config contains `[profiles.vllm]` with `image`, `vram = 24` and `cuda = 13`, and `[profiles.train]`.
- [x] `grep -c "Qwen/Qwen3-72B-Instruct" README.md` returns 0.
- [x] `uv run pytest` and `uv run mypy` pass.

## Blocked by

- #002 for the `cuda = 13` line in the README `vllm` profile
