# vasty live test report, 2026-10-31

Second funded run, for issue 009. Account 836500, credit $19.86 at start, card on file. Run from `/private/tmp/vasty-live2` by an Opus agent with a Fable overseer, Nigel supervising. Raw command output is under `docs/live/`, which is gitignored.

Nigel's go, recorded before the first reserve: cap $5.00 cumulative balance drop, per-box ceiling $0.45/hr.

## Spend

| Reading | UTC | Credit | Drop |
|---|---|---|---|
| Start | 07:21 | 19.8603 | 0 |
| After rd released | 07:40 | 19.5456 | 0.3146 |
| After D2 | 07:54 | 19.5381 | 0.3222 |
| After R round 1 | 08:15 | 19.5193 | 0.3410 |
| After R round 2, end | 08:43 | 19.4870 | 0.3733 |

Boxes created:

| Name | Lease | Instance | GPU | Host | $/hr | Fate |
|---|---|---|---|---|---|---|
| rd | `l-fe6aab28` | 58505964 | RTX 3090 24 GB, driver 590, CUDA 13.1 | Taiwan, $26.67/TB down | 0.28 | released, cost 0.31 |
| rd2 | `l-f85bcec9` | | Tesla V100 32 GB | | 0.24 | released while loading, cost null |
| cl | `l-a93ebd84` | 58507490 | RTX 3060 12 GB, driver 550, CUDA 12.4 | Poland, $9/TB down | 0.06 | released in R1 |
| bare | `l-e5e67fc6` | 58507967 | RTX 3060 12 GB, CUDA 12.8 | South Korea | 0.09 | destroyed by `serve` on `vllm_missing`, uptime 20 s |
| R1 retry | `l-14cabb6b` | 58508415 | RTX 3060 12 GB, driver 580, CUDA 13.0 | South Korea | 0.09 | destroyed by `serve` on `vllm_missing`, uptime 15 s |
| R2 retry | `l-a7730687` | 58509291 | RTX 3060 12 GB, driver 535, CUDA 12.2 | Poland | 0.07 | destroyed by `serve` on `serve_failed`, uptime 74 s |
| R1b retry | `l-f6be4fd7` | 58509958 | RTX 3060 12 GB, driver 580, CUDA 13.0 | South Korea, $6.67/TB | 0.09 | served, released, uptime 198 s, cost 0.01 |
| R2b retry | `l-2787ec15` | 58511601 | RTX 3060 12 GB, driver 595, CUDA 13.2 | Poland, $9/TB | 0.07 | served, released, uptime 119 s, cost 0.01 |

Vast's charge row for rd, the one box that ran long enough to bill: $0.314. GPU 0.210 h at $0.267 = $0.056, disk 0.287 h = $0.004, download 9.6 GB at $0.026/GB = $0.251, upload $0.003. The weights were four fifths of the bill; the image was cached on the host.

## Setup, no spend

- `vastai show instances --raw` returned `[]`. Credit 19.86028973688, `has_billing: true`.
- `vasty` reads the API key from the env var named by `api_key_env` only. With the key in `~/.config/vastai/vast_api_key` and nothing exported, every networked verb returns `auth_missing`. Every vasty call in this run set `VAST_API_KEY` inline from that file.
- The run 1 config carried `gpu = "3060"`, `disk = 16` and `daily_budget` in `[defaults]`. `config show` rejects `daily_budget` as `invalid_config`. `config show --profile vllm` resolved `gpu "3060"` and `disk 16` from the project defaults into the profile, so the README serve example from that config would have returned `no_offers` (a 12 GB card against `vram = 24`). The three lines were removed. Final profile: `image vllm/vllm-openai:v0.32.0`, `vram 24`, `cuda 13`, `max_price 0.45`; disk 50 from the builtin default. Files `docs/live/a-07-config-show-vllm.txt` and `a-09-config-show-vllm.txt`.
- Serve pool, verified single GPU, 24 GB and up, CUDA 13 and up, under $0.45, 40 GB disk: 64 offers. RTX 3090 x23, RTX 4090 x10, RTX PRO 4000 x10, Tesla V100 x4, RTX 3090 Ti x3, CMP 170HX x3, Quadro RTX 8000 x2, RTX A6000 x2, one each of P40, A5000, Titan RTX, 4080 Super, Quadro RTX 6000, RTX 5000 Ada, A40. The vastai CLI takes `gpu_ram` in GB. `docs/live/a-12-offers-serve-table.md`.
- Proxy-only pool (`direct_port_count=0`, verified, single GPU): one offer at 07:20, an RTX 5090 at $0.4943/hr in Nevada. Gone by 07:42.

## Item 1: README serve example. PASS.

```
vasty serve --profile vllm --model Qwen/Qwen3-14B-AWQ --ttl 1h --name rd --json
```

Started 07:21:17Z. vasty picked the RTX 3090 on its own. Returned at 07:30:38Z, 561 s, exit 0:

```json
{
  "lease": "l-fe6aab28",
  "job": "j-1",
  "model": "Qwen/Qwen3-14B-AWQ",
  "url": "http://220.130.209.122:41672/v1",
  "api_key": "<redacted>",
  "expires_at": "2026-10-31T08:26:11Z",
  "warnings": [],
  "swept": []
}
```

Timeline, from `docs/live/b-00-instance-watch.txt` and the job log:

| UTC | Event |
|---|---|
| 07:21:17 | serve starts, instance created |
| 07:26:17 | Vast reports `running`; boot 5m00s |
| 07:26:38 | vLLM 0.32.0 starts, V1 engine, float16, FlashAttention 2 |
| 07:29:00 | "Loading weights took 11.25 seconds" |
| 07:29:03 | "Model loading took 9.44 GiB memory and 104.32 seconds" (includes the 9.6 GB download) |
| 07:30:00 | torch.compile 55.46 s |
| 07:30:14 | "GPU KV cache size: 65,200 tokens, Maximum concurrency for 40,960 tokens per request: 1.59x" |
| 07:30:34 | "Starting vLLM server on http://0.0.0.0:8000" |
| 07:30:38 | serve returns |

Context served on the 24 GB host: vLLM chose `max_seq_len=40960`, the model's full window, with 9.95 GiB of KV cache. Job command recorded in `/workspace/.vasty/jobs/j-1/cmd`: `vllm serve Qwen/Qwen3-14B-AWQ --host 0.0.0.0 --port 8000`.

Endpoint checks (`docs/live/b-04*`):

| Call | Result |
|---|---|
| `GET /models`, no key | 401 `{"error":"Unauthorized"}` |
| `GET /models`, key | 200, one model, `max_model_len` 40960 |
| chat, 45k chars | `prompt_tokens` 8559, 200 completion tokens, 7.10 s |
| chat, 63.8k chars | `prompt_tokens` 12039, 200 completion tokens, 5.68 s (prefix cache shared with the previous prompt) |
| chat, "Say hi" | 1.00 s |

The second 12,039-token prompt against a cold job (item 2 below) took 9.35 s.

Boot observation: one `status` sample at 07:27:47, 90 s into the run and during the weight download, returned `state: unreachable`, job `unknown`, warning `box_unreachable`. The samples 60 s either side were `running`. `docs/live/b-01b-boot-06.json`.

## Item 2: `-- --max-model-len 16384` pass-through. PASS.

Run on the same box after the first job was stopped (see item 5 for the stop).

```
vasty serve --on l-fe6aab28 --model Qwen/Qwen3-14B-AWQ --json -- --max-model-len 16384
```

Returned job `j-2` in 149 s with the same url and a new key. The old key then gets 401. `docs/live/b-06*`.

- `jobs/j-2/cmd`: `vllm serve Qwen/Qwen3-14B-AWQ --host 0.0.0.0 --port 8000 --max-model-len 16384`
- log: `non-default args: {..., 'max_model_len': 16384}`, "Using max model len 16384", `max_seq_len=16384`, "Maximum concurrency for 16,384 tokens per request: 3.98x"
- `GET /models` with the j-2 key: 200, `max_model_len` 16384
- warm reload: "Loading weights took 5.13 seconds", "Model loading took 9.44 GiB memory and 12.02 seconds"; torch.compile ran again, 55.63 s
- 12,039-token prompt: 9.35 s

## Item 3: `uptime_s` against the ledger. PASS.

`running_at` in the verbose view: 07:26:18Z. Vast's own first `running` sample: 07:26:17Z. Release at 07:38:32Z returned `uptime_s: 738`. Vast's charge row bills 0.210 GPU hours, 756 s. The two differ by 18 s, with Vast's clock starting at its `running` transition and vasty's at its first `running` sample plus the destroy lag. `docs/live/b-07b-release.json`, `b-07e-charges.json`.

The charge row needs epoch seconds: `vastai show invoices-v1 --charges -s 1793404800 -e 1793432342 --raw`. The CLI raises `TypeError` on a date string, a vastai bug, `docs/live/b-07d`.

## Item 4: per-lease `cost`, null to billed. PASS.

`status` samples beside the ledger (`docs/live/b-01b-boot-summary.txt`, `b-02-sample-summary.txt`):

| UTC | state | cost | uptime_s | ledger drop |
|---|---|---|---|---|
| 07:22:00 | pending | null | null | 0.0000 |
| 07:22:33 | pending | 0.0 | null | 0.0001 |
| 07:26:41 | running | 0.0 | 23 | 0.0011 |
| 07:27:47 | unreachable | 0.01 | 90 | 0.0070 |
| 07:28:54 | running | 0.01 | 157 | 0.1499 |
| 07:30:01 | running | 0.27 | 225 | 0.2719 |
| 07:31:23 | running | 0.28 | 309 | 0.2781 |
| 07:33:44 | running | 0.29 | 446 | 0.2902 |
| 07:35:58 | running | 0.30 | 581 | 0.3000 |
| 07:38:13 | running | 0.31 | 716 | 0.3117 |

`cost` is null before the first sample, 0.0 while pending, then follows the balance drop within a cent once the bandwidth charge lands at 07:30. The `cost_source` field in issue 009's brief no longer exists in the code.

## Item 5: `idle_box_available` on a second reserve. PASS.

A reuse candidate has no live job, so the first serve job was stopped the way `remote.signal_job` does it, since no verb stops a job:

```
vasty ssh l-fe6aab28 -- 'kill -s TERM -- -$(cat /workspace/.vasty/jobs/j-1/pid)'
```

vLLM exited 143, GPU memory fell to 1 MiB, `status` showed `busy: false`. Then:

```
vasty reserve --profile vllm --name rd2 --ttl 20m --no-wait --json
```

```json
{
  "lease": "l-f85bcec9",
  "name": "rd2",
  "state": "pending",
  "reused": false,
  "gpu": "Tesla V100",
  "vram_gb": 32.768,
  "price_per_hr": 0.24,
  "warnings": [
    {
      "code": "idle_box_available",
      "lease": "l-fe6aab28",
      "message": "lease l-fe6aab28 (rd) is idle: RTX 3090, 1x24 GB, 52m left",
      "fix": "vasty status l-fe6aab28"
    }
  ],
  "swept": []
}
```

The warning informs and the create goes ahead. rd2 was released at once: `uptime_s null, cost null, jobs [], destroy_pending true`. `docs/live/b-05c-reserve-rd2.json`, `b-05d-release-rd2.json`.

Release of rd: `uptime_s 738, cost 0.31`, jobs `j-1` exit 143 after 395 s and `j-2` exit null after 259 s. `vastai show instances --raw` was `[]` ten seconds later.

## Item 6: `idle_box_available` with a proxy-only box. NOT RUN.

The one verified single-GPU offer with `direct_port_count` 0 seen at setup, RTX 5090 57086600 at $0.4943/hr, was gone by 07:42. Searches without a price cap found no other: the remaining proxy-only offers were multi-GPU 5090 rows at $0.93 and up and H200 NVL at $7.95 and up. `vasty reserve` cannot pin an offer id, so the path would have been `vastai create instance` plus `vasty tag`. No box was created. `docs/live/c-00`, `c-01`.

## Item 7: two failure paths, read by a fresh agent. FAIL on the first try for both, recovered on the second.

### 7a. `serve --on` a vLLM-image box on a 12.x host

```
vasty reserve --name cl --gpu 3060 --ttl 25m --disk 40 --image vllm/vllm-openai:v0.32.0 --max-price 0.15 --json
```

Landed on a Poland RTX 3060, host `cuda_max_good` 12.4, driver 550.120, running after 4m12s, ports 22, 8000, 8080 mapped. Inside the container `nvidia-smi` reports "CUDA Version: 13.0" over driver 550, from the compat libraries in the image. `vllm` is on PATH.

```
vasty serve --on l-a93ebd84 --model Qwen/Qwen2.5-0.5B-Instruct --json
```

Exit 2 after 64 s:

```json
{
  "error": "serve_failed",
  "message": "vLLM exited 1 before /v1/models answered.",
  "hint": "Read the log: vasty ssh l-a93ebd84 -- tail -n 100 /workspace/.vasty/jobs/j-1/log",
  "details": {
    "exit": 1,
    "lease": "l-a93ebd84",
    "log_tail": [
      "... 35 traceback lines ...",
      "RuntimeError: Unexpected error from cudaGetDeviceCount(). Did you run some cuda functions before calling NumCudaDevices() that might have already set an error? Error 804: forward compatibility was attempted on non supported HW",
      "... 63 more lines ...",
      "RuntimeError: Engine core initialization failed. See root cause above. Failed core proc(s): {}"
    ]
  }
}
```

The root cause sits at line 36 of the 100-line tail; the last line is the generic engine failure. Full object in `docs/live/d-01-serve-failed.json`.

A fresh Opus agent was given the command, this object, and read access to `vasty --help`, `serve --help`, `reserve --help` and `release --help`, nothing else. Its reply:

- Diagnosis: error 804 means the image's CUDA runtime is newer than the host driver and the compat libraries only cover datacenter GPUs, so no retry on this lease helps. Correct.
- Commands: `vasty ssh l-a93ebd84 -- nvidia-smi`; `vasty release l-a93ebd84 --yes --json`; `vasty serve --model Qwen/Qwen2.5-0.5B-Instruct --cuda 12.9 --ttl 2h --json`; on a repeat of error 804, release and retry with `--cuda 13.0`.
- It found `--cuda` and read it as a driver floor. It dropped the image, so the retry reserves the default image. It guessed 12.9 for the floor because the help text describes no flag and the error names no CUDA version.
- It would ask a human if `--cuda 13.0` also failed.

Its commands were run verbatim (`docs/live/r1-*`). The release returned `uptime_s 562, cost 0.01`. The serve ran 708 s, most of it a base image pull, landed on a South Korea RTX 3060 with CUDA 13.0 and driver 580, and exited 1 with `vllm_missing` for lease `l-14cabb6b`. `serve` destroyed that box. The agent had swapped one failure for the other: the `--cuda` floor worked and the image was gone.

Given that result, the agent's second round: `serve` without `--on` had reserved the default image, so `--image` is needed, and driver 550 supports 12.4 natively, so the printed "CUDA Version: 13.0" came from the compat library and the floor has to be 13.0. Its command:

```
vasty serve --model Qwen/Qwen2.5-0.5B-Instruct --image vllm/vllm-openai:v0.32.0 --cuda 13.0 --ttl 2h --json
```

Run verbatim (`docs/live/r1b-*`): exit 0 after 1236 s, about 17 minutes of it the 9.2 GB image pull on a South Korea RTX 3060 with CUDA 13.0 and driver 580.

```json
{
  "lease": "l-f6be4fd7",
  "job": "j-1",
  "model": "Qwen/Qwen2.5-0.5B-Instruct",
  "url": "http://121.153.254.120:33442/v1",
  "api_key": "<redacted>",
  "expires_at": "2026-10-31T10:34:50Z",
  "warnings": [],
  "swept": []
}
```

`/models` with the key: 200 in 0.41 s, `max_model_len` 32768. "Say hi": 200 in 0.47 s, "Hello! How can I assist you today?". Released at once: `uptime_s 198, cost 0.01`.

Verdict for 7a: the agent read the cause from the log tail on the first try and reached the fix on the second. The miss was the dropped image and the guessed floor, two reserves and 20 minutes of wall time.

### 7b. bare `serve --model X` with no profile

```
vasty serve --model Qwen/Qwen2.5-0.5B-Instruct --ttl 15m --name bare --json
```

Reserved a South Korea RTX 3060 on the default image. Exit 1 after 238 s:

```json
{
  "error": "vllm_missing",
  "message": "Lease l-e5e67fc6 has no vllm on PATH.",
  "hint": "Reserve with a vLLM image: vasty serve --model Qwen/Qwen2.5-0.5B-Instruct --image vllm/vllm-openai:v0.32.0."
}
```

`serve` destroyed the box it had created: `vastai show instances` listed only cl right after, and `status --verbose` shows bare as `released`, cost 0.0, `uptime_s` 20.

A second fresh Opus agent, same rules, replied:

- Diagnosis: the default image has no vLLM. It could not tell from the error whether the lease was still billing.
- Commands: `vasty status --json`; `vasty release l-e5e67fc6 --json` if still listed; `vasty serve --model Qwen/Qwen2.5-0.5B-Instruct --image vllm/vllm-openai:v0.32.0 --ttl 15m --name bare --json`.
- It restored `--ttl` and `--name`, which the hint drops. It did not add `--cuda`, since the help gives no meaning for it, and said `--cuda` and `--disk` would be its next flags if the retry failed.

Its commands were run verbatim (`docs/live/r2-*`). `status` showed no leases. `release` on the gone lease returned exit 0 with `already_absent: true`. The serve ran 335 s, landed on a Poland RTX 3060 with `cuda_max_good` 12.2 and driver 535, and exited 2 with `serve_failed` for lease `l-a7730687`, the same error 804 tail as 7a. `serve` destroyed that box. The hint as written reproduced 7a.

Given that result, the agent's second round: the host driver is older than the image's CUDA and vasty adds no driver floor for an image on its own, so ask for one. Its command:

```
vasty serve --model Qwen/Qwen2.5-0.5B-Instruct --image vllm/vllm-openai:v0.32.0 --cuda 13.0 --ttl 15m --name bare --json
```

It picked 13.0 over 12.9 because a floor set too high costs offers and one set too low costs another five-minute failure.

Run verbatim (`docs/live/r2b-*`): exit 0 after 138 s on a Poland RTX 3060 with CUDA 13.2 and driver 595, the same host as cl, so the image was cached.

```json
{
  "lease": "l-2787ec15",
  "job": "j-1",
  "model": "Qwen/Qwen2.5-0.5B-Instruct",
  "url": "http://91.150.160.38:11416/v1",
  "api_key": "<redacted>",
  "expires_at": "2026-10-31T08:53:45Z",
  "warnings": [],
  "swept": []
}
```

`/models` with the key: 200 in 0.31 s. "Say hi": 200 in 0.37 s. Released at once: `uptime_s 119, cost 0.01`.

Verdict for 7b: the agent followed the hint as written on the first try and hit 7a, then added the floor on the second. The hint carries the miss: with `--cuda 13` in it the first retry would have served.

## Teardown

- `vastai show instances --raw` returned `[]` at 08:41:00Z and at 08:43:05Z. `docs/live/t-01`, `t-06`.
- `vasty status --verbose --json` lists all eight leases of this run as `released`, no warnings. `docs/live/t-02`.
- `vasty status --all --everyone --json` returns `leases: []`, `charges_today 0.37`. `docs/live/t-03`.
- Killed on the laptop: the ledger loop and the followers for `l-f6be4fd7` and `l-2787ec15`. No `vasty sweep` process remains.
- `grep -rl` over the captures for both round 2 keys, the pattern `vasty-` plus 32 hex, the Vast key and `CONTAINER_API_KEY=` finds nothing. `docs/live/t-07`.
- Final credit 19.48695107172, drop $0.3733 against the $5.00 cap.
- `uv run pytest`: 1246 passed, 1 skipped. `uv run mypy`: no issues in 34 files.

## Observations

- **Profile inherits project defaults.** `[defaults]` values flow into a named profile. A config with `gpu = "3060"` in defaults makes `--profile vllm` unreservable.
- **The README example can land on old silicon.** The same `--profile vllm` picked an RTX 3090 and, two minutes later, a Tesla V100. The pool under $0.45 holds Pascal, Volta, Turing and CMP cards. vLLM 0.32 ships no Volta kernels.
- **`status LEASE --json` without `--verbose` carries the job's log tail.** 236 of its 280 lines were vLLM "Attempted to load weight ... bfloat16 into float16" warnings.
- **`status --all --everyone` lists active leases only.** Released and expired leases show in plain `vasty status --verbose` and by name. Issue 009's teardown line names the wrong command.
- **A follower outlives its box.** `vasty sweep --follow` for rd and for bare kept running after their rows were gone, until the lease's original expiry. The README describes this loop; the cost is one sleeping process per released lease.
- **Released leases keep a countdown.** `ttl_remaining_s` in the history view counts down to the label's expiry after release (`bare` 879, `rd` 1934).
- **Both error hints stop short of the fix.** `serve_failed` says read the log, and the log tail it already carries holds the cause 64 lines from the end. `vllm_missing` names the image and no `--cuda` floor, so the hint as written can land on a 12.x host and hit 7a.
- **Help text describes no flag.** Both fresh agents said `serve --help` and `reserve --help` list flags with no description, default or unit, so `--cuda FLOOR`, `--ttl` and the default image had to be guessed. Both asked for the `vllm_missing` hint to keep the caller's `--ttl` and `--name`, and for `serve_failed` to map error 804 to `--cuda`.
- **No verb stops a job.** Stopping the first serve job meant `kill` over `vasty ssh`.
- **The vastai CLI rejects date strings** on `show invoices-v1 --charges -s`. Epoch seconds work.
