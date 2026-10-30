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

1. Add `OfferQuery.cuda_min: float | None`. `build_offer_query` adds `"cuda_max_good": {"gte": cuda_min}` when set.
2. Add `ModelEntry.cuda: float | None`. The builtin entry sets `13.0`. `serve` passes the entry's value into the query on the auto-reserve path.
3. Add `--cuda FLOOR` to `reserve` and `serve`. It applies to a plain `--image` and overrides the entry's value. The README names `NVIDIA_REQUIRE_CUDA` in `docker inspect IMAGE` as where to read an image's floor.
4. Add `Offer.cuda_max_good`, read from the `/bundles/` row, so `reserve --verbose` and the `no_offers` hint can show it.
5. The `no_offers` hint lists `cuda` beside `max_price` and `region`.
6. Add `CachedLease.cuda: float | None`, set from the offer at create. It stays None for leases cached before this change, tagged boxes and cache rebuilds, since the instance row carries `cuda_max_good` and `_apply_probe` can fill it on the next refresh. The box reuse hardware comparison treats None as a mismatch when the settings carry a `cuda` floor and as a match otherwise.
7. `serve --on` refuses with `cuda_too_low` when the lease's `cuda` is below the floor, before the preflight. The hint names `--cuda` and `reserve` with the model. A None `cuda` is refreshed from the instance row first; still None, `serve` proceeds.

## Tests

- `build_offer_query` with `cuda_min` 13.0 emits the `gte` filter; without it, the dict is unchanged.
- `serve --model Qwen/Qwen3-32B-AWQ` without `--on` searches with `cuda_min` 13.0 on the fake provider.
- `serve --cuda 12.8` with the same model searches with 12.8.
- `reserve --image vllm/vllm-openai:v0.32.0 --cuda 13.0` sends the filter.
- `reserve` with a plain image and no `--cuda` sends no `cuda_max_good` key.
- `serve --on` against a lease with `cuda` 12.8 and a 13.0 floor raises `cuda_too_low` without starting a job; with `cuda` None and an instance row at 13.0 it proceeds.
