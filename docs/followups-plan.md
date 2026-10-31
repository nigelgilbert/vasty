# Live run follow-ups: plan, 2026-10-30

Order of work for PR #2, branch `refactor/live-run-followups`. Everything lands in this one PR, squash merged. Each step below is one or more commits, and each commit leaves `uv run pytest` and `uv run mypy` green.

Sources: `docs/budget-decisions.md`, `docs/box-reuse-decisions.md`, `docs/serve-decisions.md`, and the three files under `issues/`. GPT-6 Astra reviewed the sequencing; its points are folded in.

## 0. Settle the decisions. Done 2026-10-30.

No code until the docs agree with each other.

Vision, in two lines: provisioning comes with a TTL and cleans up after itself, and the API doesn't suck. Every step below is measured against that.

Settled in the second pass, after a workshop and an Astra review:

- No account-level spend guard. `min_credit` and `credit_low` are dropped. Spend per box is `max_price` times `ttl`, and the account bound is the prepaid balance. `max_price` is an offer filter, the same kind as `--vram`.
- The `[models]` table goes: `BUILTIN_MODELS`, `ModelEntry`, `MODEL_KEYS`, the model resolution layer, `model_unknown` and `--quant`. `serve` takes `--model` plus the same hardware flags and profiles as `reserve`. Serve decision 3 is replaced.
- `serve` passes everything after `--` to `vllm serve`. Vasty knows no vLLM flags. `--host`, `--port` and `--api-key` after `--` are rejected before provisioning, since `serve` owns the endpoint and the key.
- `cuda` is one more hardware key: flag, profile, config and env. It is the minimum host `cuda_max_good`. No cached lease field, no `cuda_too_low`.
- Train and serve get separate boxes sized for each. Train-then-serve on one box is out of scope. The startup hook stays as the way to put `vllm` on a box reserved with another image.
- The README pitch is the two lines above. "Bounded spend" comes off the promise list.

Done in `1eae72f`:

- Per-lease `cost` is Vast's billed sum or null, and `cost_source` goes. Budget decision 3.
- `spend_source` is dropped everywhere, which removes the contradiction between the budget issue and the budget decisions.
- `credit` is read beside `balance` and cached with the charges.
- A lease with unknown CUDA counts as a mismatch only when the settings carry a floor.
- `running_at` is set by `engine.refresh` on the first provider `running` sample, before ssh readiness.
- Phase 5 of the live test plan reserves a 5060 Ti.

Closed by the research pass and the second Astra review: `POST /bundles/` honours the `cuda_max_good` filter server-side; the floor is a hardware key the user sets, with the README naming `NVIDIA_REQUIRE_CUDA` in `docker inspect` as where to read it; `cuda_max_good` tracks driver version on every card sampled, so the filter is conservative on datacenter hosts; `_wait_ready` reads the tail with one extra ssh call on the failure path only.

## 1. Foundation

**1a. Budget pass-through.** `issues/replace-daily-budget-with-vast-pass-through.md`. Pure deletion plus pass-through. It rewrites the `status` JSON contract the later steps report through.

1. Read `credit` beside `balance` in `Provider.balance` and cache both in `CacheData`. Additive, so it can be its own commit.
2. Remove `daily_budget`, `src/vasty/budget.py`, `budget_exceeded`, `budget_low`, `spend_source` and exit code 3. `status` totals report `balance`, `credit`, `charges_today` and `burn_per_hr`.
3. Switch `lease_cost` to billed or null, widen the charges window to the oldest active lease, and report the same figure from `release`.
4. README spend section, exit codes and error table.

Deleting the estimator removes `instance_start`, which closes finding 4 of the PR #1 code review.

**1b. Serve and host CUDA.** `issues/filter-offers-on-host-cuda.md` and serve decisions 1 and 3.

1. Add `cuda` to the hardware keys in `src/vasty/config.py` and to `OfferQuery`. `build_offer_query` adds `cuda_max_good: {"gte": cuda}` when it is set. The `no_offers` hint names `cuda` beside `max_price` and `region`.
2. Remove the `[models]` table: `BUILTIN_MODELS`, `ModelEntry`, `MODEL_KEYS`, `MODEL_LAYER_KEYS`, the model layer in `resolve`, `model_unknown`, `--quant` and `ctx.model`. `serve` resolves settings the same way `reserve` does.
3. Add `--` passthrough to `serve`, the same split `run` uses. Tokens after `--` are appended to `server_argv`. `--host`, `--port` and `--api-key` among them raise `invalid_arguments` before any provider call.
4. README: a `train` profile and a `vllm` profile in the sample config, the serve example as `vasty serve --profile vllm --model Qwen/Qwen3-14B-AWQ --ttl 1h`, one sentence on reserving with a startup hook that installs `vllm` or installing through `run --on`.

The `vllm` profile sets `image = "vllm/vllm-openai:v0.32.0"`, `vram = 24` and `cuda = 13`. `Qwen/Qwen3-14B-AWQ` is ungated with 10.0 GB of weights. Step 4 confirms the context it serves on 24 GB before the README states a number.

1a and 1b touch separate functions in `reserve.py` and can be built in parallel worktrees.

## 2. Independent of the foundation

These can start now or fill gaps while step 1 is in review.

- **Box reuse change A.** `busy`, `gpus` and `vram_gb` on `LeaseView`, `idle` in the jobs cell. Add one busy helper in `state.py` that counts an `unknown` job as busy; change B reuses it.
- **Serve diagnostics.** `log_tail` on `serve_failed`, with the serve key redacted by value. Capture it in `_wait_ready` before `execute` releases an auto-created box. Fix the `vllm_missing` hint under `--on`, which today suggests reserving a second box (PR #1 code review, finding 2).
- **Uptime from first `running`.** `issues/uptime-counts-the-image-pull.md`. Add `running_at`, set in `engine.refresh`, and count `uptime_s` from it.

## 3. After the foundation

- **Box reuse change B.** `hardware_mismatch` in `state.py`, shared by `flag_mismatch` and `reuse_candidates`, with CUDA as a hardware key read from the instance row in the snapshot. `normalize_instance` in `provider.py` keeps `cuda_max_good` on `Instance` for this. Then the `idle_box_available` warning on `reserve`, auto-reserve `run` and auto-reserve `serve`. Needs 1b and change A.
- **README and skill text.** Agent guidance from `docs/box-reuse-decisions.md`, and the `status` fields from 1a, 1b and change A in one pass.

## 4. Before merge

- Live run, with a go from Nigel and a spend cap. Cover:
  - the README serve example as written, on a 24 GB CUDA 13 host, through to one `/v1/chat/completions` call with a long prompt, so the README can state the context it served;
  - `serve ... -- --max-model-len 16384` passing through to the job;
  - `uptime_s` against the balance ledger;
  - per-lease `cost` going from null to billed;
  - `idle_box_available` on a second `reserve`.
- Record the run in `docs/live-test-report.md`.
- Delete the issue files this PR closes, and this memo.

## Deferred

- `max_boxes`. Unfiled. Its refusal hint reuses the change B candidate predicate.
- A `--reuse` flag that picks an idle box automatically. Revisit if `idle_box_available` fires often.
- `cuda_too_low` on `serve --on`. Add it if the live run shows an agent cannot recover from Error 804 in the `serve_failed` log tail.
- Any builtin model or image catalog.
- The unpublished default image `vasty/base:cuda12.4`. The quick start already points at a Vast base image. Deciding whether to publish it or drop it is its own conversation after this PR.
