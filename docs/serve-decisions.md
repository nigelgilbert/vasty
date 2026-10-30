# Serve decisions, 2026-10-30

Five decisions from the Phase 5 rerun of the live test, written by the agent that ran it. Edit before acting. The rerun is recorded in `docs/live-test-report.md`; raw output is under `docs/live/p5r/`.

## Settled by the rerun

- `vllm` resolves on `vllm/vllm-openai:v0.32.0`: `command -v vllm` returned `/usr/local/bin/vllm` in a Vast ssh session. Finding 1 of code review 0 on PR #1 closes with no code change.
- A host with a driver below the image's CUDA floor passes container create and fails when vLLM initialises its device. `serve` reports it as `serve_failed` within a minute.
- The job runs without the image's `ENV` values (`CUDA_HOME`, `LD_LIBRARY_PATH`, `VLLM_*`) and serves. `nvidia-smi` and `torch.cuda` work in the session.

## 1. The offer search filters on host CUDA

`OfferQuery` gets a `cuda_min` field. `build_offer_query` adds `cuda_max_good: {"gte": cuda_min}` when it is set. The builtin model entry sets `cuda = 13.0`, and `serve` passes the entry's value into the query on the auto-reserve path. The `no_offers` hint names `cuda` beside `max_price` and `region`. Filed as `issues/filter-offers-on-host-cuda.md`.

Why. `vllm/vllm-openai:v0.32.0` is built on CUDA 13.0 and a GeForce card needs driver 580 or later to run it. At 05:30Z, four of the top five verified RTX 3060 offers by reliability ran CUDA 12.2 to 12.8. The plan's command landed on a 12.8 host, where vLLM died with `Error 804: forward compatibility was attempted on non supported HW`. Two retries with `--region` landed on 12.x hosts too. All 30 RTX 5060 Ti offers ran 13.0 or later.

Scope. The filter applies when the resolved image declares a floor. `reserve` with a plain image searches as before.

Until it lands. Phase 5 of the plan reserves with `--gpu 5060ti --max-price 0.21`, whose pool ran CUDA 13 throughout the rerun.

## 2. `uptime_s` starts at the first `running` sample

`uptime_s` in `views.py` counts from the moment `engine.refresh` first saw the provider report the instance `running`. The lease cache records that time. Leases without it fall back to the label's `created`. Filed as `issues/uptime-counts-the-image-pull.md`.

Why. Vast bills no GPU time while an instance is `loading`. Vast's `start_date` equals the create time: instance 58355222 reported `start_date` 1793338271.86 against label `created=1793338271`. So the PR #1 clamp at `start_date` still counts the pull. The first rerun box pulled for 20 minutes and `release` reported `cost: 0.04` against a $0.007 balance drop. With the 5060 Ti live, `spent_today` read 0.13 against 0.10.

Scope. Decisions 2 and 3 in `docs/budget-decisions.md` replace the spend estimate and per-lease `cost` with Vast's billed figures, so this decision covers `uptime_s` alone.

## 3. The builtin model entry is `Qwen/Qwen3-32B-AWQ`

`BUILTIN_MODELS` replaces `Qwen/Qwen3-72B-Instruct` with `Qwen/Qwen3-32B-AWQ`: `vram = 24`, `quant = "awq"`, `image = VLLM_IMAGE`, `cuda = 13.0`. The README's serve example, models section and `[models]` sample change to match.

Why. `Qwen/Qwen3-72B-Instruct` returns 401 from the Hugging Face API; the dense Qwen3 line stops at 32B. `Qwen/Qwen3-32B-AWQ` exists, is ungated and is 4-bit, so it fits a 24 GB card. The memo of 2026-10-29 proposed it.

## 4. `serve_failed` carries the log tail

`details` gains `log_tail`: the last 100 lines of the job log, with the serve key redacted by value. The single-lease `status` already returns `log_tail`, so `serve` reuses that path.

Why. On the 12.8 host the root cause sat 60 lines above the end of the log; the last lines said `Engine core initialization failed. See root cause above.` A tail of 100 held the cause. The arg dump at the top of every vLLM log prints `--api-key`.

## 5. `status` keeps hiding expired leases by default

No change. `status NAME` shows an expired lease, and history keeps it for 24 hours.

Why. The rerun gave no case where an agent needed the expired list without a name.
