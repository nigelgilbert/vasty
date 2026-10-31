# `reserve` picks hosts whose driver cannot run the vLLM image

Live run 2026-10-30, lease `l-b5c8ea2b`, RTX 3060, `vllm/vllm-openai:v0.32.0`. Decided in `docs/serve-decisions.md`, decision 1.

## Command

```
vasty reserve --name sv --vram 12 --ttl 45m --disk 40 --image vllm/vllm-openai:v0.32.0
vasty serve --on sv --model Qwen/Qwen2.5-0.5B-Instruct
```

## Output

`reserve` returned `running` on a South Korean host with driver 570.172.08, `cuda_max_good` 12.8. `serve` returned in 54 s:

```json
{"error": "serve_failed", "message": "vLLM exited 1 before /v1/models answered.",
 "hint": "Read the log: vasty ssh l-b5c8ea2b -- tail -n 100 /workspace/.vasty/jobs/j-1/log",
 "details": {"exit": 1}}
```

Job log:

```
  File ".../vllm/v1/worker/gpu_worker.py", line 501, in init_device
    torch.accelerator.set_device_index(self.device)
RuntimeError: Unexpected error from cudaGetDeviceCount(). Did you run some cuda functions before calling NumCudaDevices() that might have already set an error? Error 804: forward compatibility was attempted on non supported HW
```

`python3 -c "import torch; print(torch.cuda.is_available())"` printed `False` on the box.

## Cause

The image declares `NVIDIA_REQUIRE_CUDA=cuda>=13.0` and ships torch built for CUDA 13.0. Error 804 is NVIDIA's `CUDA_ERROR_COMPAT_NOT_SUPPORTED_ON_DEVICE`: forward compatibility covers data center GPUs and select NGC-ready RTX SKUs, so a GeForce card needs driver 580 or later. `build_offer_query` in `src/vasty/provider.py` sends no `cuda_max_good` filter, and `Offer` carries no CUDA field. At 05:30Z four of the top five verified RTX 3060 offers by reliability ran CUDA 12.2 to 12.8, so the plan's command picked a failing host more often than a working one. Two retries with `--region KR` and `--region CA` also landed on 12.x hosts.

The same commands on an RTX 5060 Ti box with driver 580.173.02 served the model in 5m22s.

Vast applies `cuda_max_good: {"gte": 13.0}` server-side. A verified RTX 3060 search returned 30 offers with 21 at 13.0 or above; the filtered search returned 29, all at 13.0 or above. `cuda_max_good` follows `driver_version` on every card sampled, data center cards included (A100 on 570 reports 12.8), so the floor excludes data center hosts on the 535 and 570 branches, which NVIDIA lists as compatible with `cuda-compat-13-x`, when their runtime selects the compat libraries.

## Fix

1. Add `cuda` as a hardware key: `DEFAULT_KEYS`, `PROFILE_KEYS` and `FLAG_KEYS` in `src/vasty/config.py`, `Settings.cuda: float | None`, `VASTY_CUDA`, and `--cuda FLOOR` on `reserve`, `run` and `serve`. It is the minimum host `cuda_max_good`.
2. Add `OfferQuery.cuda: float | None`. `build_offer_query` adds `"cuda_max_good": {"gte": cuda}` when set.
3. The `no_offers` hint lists `cuda` beside `max_price` and `region`.
4. The README names `NVIDIA_REQUIRE_CUDA` in `docker inspect IMAGE` as where to read an image's floor, and the sample `vllm` profile sets `cuda = 13`.

Decided against: a cached lease CUDA field and a `cuda_too_low` refusal on `serve --on`. A host under the floor fails inside a minute and `serve_failed` carries the log tail with Error 804. `cuda_too_low` is deferred until a live run shows an agent cannot recover from that tail.

## Tests

- `build_offer_query` with `cuda` 13.0 emits the `gte` filter; without it, the dict is unchanged.
- `reserve --image vllm/vllm-openai:v0.32.0 --cuda 13` sends the filter.
- `reserve --profile vllm` with `cuda = 13` in the profile sends the filter.
- `reserve` with no `cuda` in any layer sends no `cuda_max_good` key.
- `no_offers` with a floor set names `cuda` in the hint.
