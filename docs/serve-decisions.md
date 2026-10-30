# Serve decisions, 2026-10-30

Five decisions from the Phase 5 rerun of the live test, written by the agent that ran it and revised after a research pass the same day. The rerun is recorded in `docs/live-test-report.md`; raw output is under `docs/live/p5r/`. Reviewed by GPT-6 Astra; the accepted points are folded in below.

Research sources: unauthenticated `POST /bundles/` searches through the vastai SDK, the image config of `vllm/vllm-openai:v0.32.0` from Docker Hub, vLLM v0.32.0 source at the tag, the Hugging Face API, NVIDIA's CUDA compatibility pages, a read-only `GET /charges/` for the rerun day and the instance rows under `docs/live/`.

## Settled by the rerun

- `vllm` resolves on `vllm/vllm-openai:v0.32.0`: `command -v vllm` returned `/usr/local/bin/vllm` in a Vast ssh session. Finding 1 of code review 0 on PR #1 closes with no code change.
- A host with a driver below the image's CUDA floor passes container create and fails when vLLM initialises its device. `serve` reports it as `serve_failed` within a minute.
- The job runs without the image's `ENV` values (`CUDA_HOME`, `LD_LIBRARY_PATH`, `VLLM_*`) and serves. `nvidia-smi` and `torch.cuda` work in the session.

## 1. The offer search filters on host CUDA

`OfferQuery` gets a `cuda_min` field. `build_offer_query` adds `cuda_max_good: {"gte": cuda_min}` when it is set. The floor comes from the model entry's `cuda` key or a `--cuda` flag on `reserve` and `serve`; the flag overrides the entry. The builtin model entry sets `cuda = 13.0`. `serve --on` compares the lease's recorded `cuda_max_good` with the floor and refuses with `cuda_too_low` before the preflight. The `no_offers` hint names `cuda` beside `max_price` and `region`. Filed as `issues/filter-offers-on-host-cuda.md`.

Why. `vllm/vllm-openai:v0.32.0` declares `NVIDIA_REQUIRE_CUDA=cuda>=13.0` and ships torch built for CUDA 13.0. At 05:30Z, four of the top five verified RTX 3060 offers by reliability ran CUDA 12.2 to 12.8. The plan's command landed on a 12.8 host, where vLLM died with `Error 804`, NVIDIA's `CUDA_ERROR_COMPAT_NOT_SUPPORTED_ON_DEVICE`. Two retries with `--region` landed on 12.x hosts too.

Vast honours the filter server-side. An unauthenticated search for one verified RTX 3060 returned 30 offers, 21 of them at 13.0 or above. The same search with `cuda_max_good: {"gte": 13.0}` returned 29, all at 13.0 or above. The search caps its result set around 30 rows, so a client-side filter would lose offers the server would have returned.

Where the floor comes from. The image config carries `NVIDIA_REQUIRE_CUDA`, which reaches a client after a token request, the manifest list, the per-arch manifest and the config blob: four unauthenticated calls to Docker Hub per image, cacheable per tag. Other registries need their own auth flow, and a registry outage would block or silently unfilter `reserve`. The value is a constraint expression (`cuda>=13.0` followed by brand and driver pairs for forward compatibility), so the floor needs parsing out of it. The config key and the flag give the same floor with no network call, and the README tells the user where to read it: `docker inspect IMAGE`, key `NVIDIA_REQUIRE_CUDA`. Changed from the first draft: `--cuda` on `reserve` and `serve`, and the `serve --on` check.

Forward compatibility. `cuda_max_good` tracks `driver_version` on every card sampled. A100 and L40S offers on driver 570 reported 12.8 beside 580 hosts at 13.0, the same as RTX 4090 and 5090 offers. NVIDIA lists forward compatibility for data center GPUs and select NGC-ready RTX SKUs; its table marks the 535 and 570 branches compatible with `cuda-compat-13-x` and 580 as the base driver. A 13.0 floor therefore excludes data center hosts on those branches that could run the image through the compat libraries, if the host runtime installs and selects them. Error 804 on the 3060 shows a compat path was attempted; vLLM's own switch, `VLLM_ENABLE_CUDA_COMPATIBILITY`, is off whether the image's `ENV` reaches the job or not, so the attempt came from outside vLLM. Whether an A100 host on 570 then runs the image is unsettled without a live box. The exclusion stands, and no GPU name is exempted: a supported card alone does not establish that the libraries are present and selected. `--cuda 12.8` lowers the floor for a deliberate try.

Scope. The filter applies when a floor is set. `reserve` with a plain image and no `--cuda` searches as before. On `serve --on`, a lease with no recorded `cuda_max_good` is refreshed from the instance row first; if the value is still unknown, `serve` proceeds.

Until it lands. Phase 5 of the plan reserves with `--gpu 5060ti --max-price 0.21`, whose pool ran CUDA 13 throughout the rerun.

## 2. `uptime_s` starts at the first `running` sample

`uptime_s` in `views.py` counts from the moment `engine.refresh` first saw `actual_status` equal `running`. The lease cache records that time as `running_at`. A lease without it reports `uptime_s` null. Filed as `issues/uptime-counts-the-image-pull.md`. Changed from the first draft: the fallback to the label's `created` is dropped.

Why. Vast bills no GPU time while an instance is `loading`. The charges for 2026-10-30 show it per item: instance 58355222 lived 23 minutes, pulled for 20m35s, and billed `gpu` for 0.060 hours against `disk` for 0.394 hours. The two boxes released while `loading` billed `gpu` 0.0 and `disk` for 0.008 and 0.080 hours. Disk bills from create, GPU from `running`. A fallback to `created` would report positive uptime for a box released while `loading`, which is the original bug.

No Vast field marks the move. `start_date` equals the create time: instance 58355222 reported 1793338271.86 against label `created=1793338271`. `duration` is seconds since `start_date` on every row sampled. `status_msg` is null while `loading` and reads `success, running <image>` once `running`, with no timestamp. `uptime_mins` is null on every row, and `client_run_time` and `host_run_time` have no documented meaning. The loading row carries `cur_state: running` beside `actual_status: loading`, so `actual_status` is the field to sample, which `engine.refresh` already does. Vast's schema documents none of these fields.

Scope. Decisions 2 and 3 in `docs/budget-decisions.md` replace the spend estimate and per-lease `cost` with Vast's billed figures, so this decision covers `uptime_s` alone. `running_at` is the first observed `running` sample with the granularity of vasty's own sampling: a `reserve --wait` poll sets it within one interval, and a `--no-wait` box gets it at the next command that refreshes. `uptime_s` is elapsed time since that sample and includes any interval the box spent stopped. The charges `gpu` item carries billed hours as a string (`0.060 hours at $0.073/hour`) in a daily bucket; parsing it for `uptime_s` is declined.

## 3. The builtin model entry is `Qwen/Qwen3-32B-AWQ`

`BUILTIN_MODELS` replaces `Qwen/Qwen3-72B-Instruct` with `Qwen/Qwen3-32B-AWQ`: `vram = 24`, `image = VLLM_IMAGE`, `cuda = 13.0`. `ModelEntry` gains `max_model_len: int | None` and keeps `quant` for other models. `server_argv` passes `--max-model-len N` when the entry sets it, `--max-model-len auto` when the entry sets nothing and the resolved image is `VLLM_IMAGE`, and nothing otherwise. `ServeResult` gains `max_model_len`, read from the `max_model_len` field of the `/v1/models` response that `_ready` already fetches; `ctx.http_get` returns a status code today and grows a body for this. The README's serve example, models section and `[models]` sample change to match, and the README states the expected context on a 24 GB card. Changed from the first draft: `quant` is dropped from the builtin entry, `--max-model-len` is added, and the serve result reports the context.

Why. `Qwen/Qwen3-72B-Instruct` returns 401 from the Hugging Face API; the dense Qwen3 line stops at 32B. `Qwen/Qwen3-32B-AWQ` is ungated (`gated: false`, 452k downloads), four safetensors shards totalling 19.3 GB, `config.json` with `quantization_config.quant_method = "awq"`, 4-bit, group size 128, `torch_dtype` float16.

Quantization. vLLM 0.32.0 reads `quantization_config` from the checkpoint and maps `awq` to its `auto_awq` method whether `--quantization` is unset or set to `awq`, `awq_marlin` or `marlin` (`AutoAWQConfig.override_quantization_method`). `auto_awq` runs the Marlin kernel when `check_marlin_supported` passes, which covers Ampere, Ada and Blackwell, and the plain AWQ kernel on Turing (`get_min_capability` is 75). The `--quantization awq` flag changes nothing for this checkpoint, so the entry drops it.

Context length. `max_position_embeddings` is 40960. The model has 64 layers, 8 KV heads and head dim 128 in fp16, so one token of KV cache is 256 KiB and one request at 40960 tokens needs 10 GiB. A 24 GB card at the default `gpu_memory_utilization` 0.9 has about 21.6 GiB to spend; the weights take about 18 GiB and activations plus CUDA graphs about 1.5 GiB, leaving 1.5 to 2.5 GiB for KV. `check_enough_kv_cache_memory` then raises `To serve at least one request with the model's max seq len (40960) ... larger than the available KV cache memory` and the engine exits. `--max-model-len auto` (`-1`) makes vLLM pick the largest length that fits, the full 40960 on a card with room. The 0.32.0 CLI parses `auto` through `human_readable_int_or_auto` in `vllm/utils/argparse_utils.py`. Older vLLM builds in a custom image reject it, hence the `VLLM_IMAGE` condition. Automatic sizing settles the KV check only; weight loading and profiling can still run out of memory, and the chosen length can be short. Expect 6k to 9k tokens on 24 GB; the figure is an estimate and the serve result reports the real one.

## 4. `serve_failed` carries the log tail

`details` gains `log_tail`: the last 100 lines of the job log, capped at 64 KiB, with the serve key replaced by `<redacted>` wherever its value appears. `_wait_ready` reads the tail with one `ctx.box.log_tail(target, job_id, 100)` call on the failure path, for both the exit and the deadline case, before it signals or raises. A failed tail read is swallowed and `serve_failed` goes out with `exit` alone. `server_argv` passes the key through the `VLLM_API_KEY` environment variable in the job script and drops `--api-key`. `LOG_LINES` moves to a shared constant. Changed from the first draft: the env var, the byte cap, the best-effort read and the deadline ordering.

Why. On the 12.8 host the root cause sat 60 lines above the end of the log; the last lines said `Engine core initialization failed. See root cause above.` A tail of 100 held the cause.

One round trip, on failure only. `_wait_ready` already runs `job_status` once per 5 s poll, a single ssh call that prints one `job=` line per job directory. The script could print the tail only once the job has exited, but the deadline case has a live job, and the separate call covers both with one code path. The extra call costs one ssh round trip on the path that already failed. `execute` releases an auto-created box after `_bring_up` raises, and `_wait_ready` runs inside `_bring_up`, so the tail is read before the release. On the deadline, the tail is read before `TERM` so shutdown output does not displace the cause.

Redaction. vLLM 0.32.0 prints `'api_key': '***'` in its `non-default args` line (`docs/live/p5r/18-serve-log.txt`, line 7), so the arg dump is already clean. With `--api-key`, the key sits on the `vllm serve` command line, in `ps` output and in any traceback that echoes argv. vLLM 0.32.0 reads `VLLM_API_KEY` from the environment (`vllm/envs.py`), so the job script sets it and the command line carries no secret. The replacement by value in serve.py stays as a second guard, in a helper the two raise sites share. `status NAME` has no key to redact and keeps its tail as it is.

## 5. `status` keeps hiding expired leases by default

No change. `status NAME` shows an expired lease, and history keeps it for 24 hours.

Why. The rerun gave no case where an agent needed the expired list without a name.

Scope. The hidden rows are leases in history states, hidden by lease expiry. `_sweep` in `engine.refresh` destroys every managed row past its clock before any view is built, so an expired lease whose instance still runs is swept whether or not `status` lists it.

## Open without a live box

- Whether a data center host on driver 570 runs `vllm/vllm-openai:v0.32.0` through the runtime's compat libraries.
- The context length `--max-model-len auto` settles on for `Qwen/Qwen3-32B-AWQ` on a 24 GB card, and the load time for 19.3 GB of weights.

## Astra review, disposition

Accepted: `--cuda` on `serve` as well as `reserve`; the `serve --on` check against the lease's recorded CUDA, with a refresh before an unknown counts; no GPU-name exemption; Error 804 proves an attempted compat path and nothing about who installed it; cite the 535 and 570 table entries instead of a range; registry calls are cacheable and `NVIDIA_REQUIRE_CUDA` is an expression; drop the `created` fallback for `uptime_s` and report null; name `actual_status` as the sampled field; state that `uptime_s` is elapsed time including stopped intervals; `auto` is settled by source inspection and scoped to the pinned image; keep `quant` for other models; report the chosen context in the serve result; best-effort tail read, byte cap, tail before `TERM`; move the key off the command line with `VLLM_API_KEY`; decision 5 names the sweep.

Declined: renaming `running_at` to `first_seen_running_at`. The field's definition says it is the first observed sample, and `docs/followups-plan.md` already uses the shorter name. Shared sanitisation for `status`: `status` never holds the key, and with `VLLM_API_KEY` the log no longer carries it on the command line.
