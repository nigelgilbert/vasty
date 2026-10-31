# Live test plan 3: an agent swarm on vasty

Third funded run. The first two runs proved the clock and `serve`. This one puts agents in the driver's seat: a lead agent reserves a box, hands tasks to fresh worker agents, Nigel leaves, and the run records what the workers do with vasty when nobody is reading over their shoulder.

Run from `/private/tmp/vasty-live3` by a Fable lead with Opus workers, Nigel supervising the start and the end. Cumulative balance-drop stop: $5.00. Per-box ceiling: $0.15/hr for a 3060, $0.45/hr for the serve box.

## 1. What this run settles

1. A fresh agent given the README and the CLI follows the rules in "For agents": `status` before reserving, `--on` to reuse, its own owner, JSON mode, warnings read and their `fix` run.
2. Two workers sharing one box. How each finds the box, whether `busy` changes its choice, and what state the box is in when both are done.
3. A job that outlives its lease. Whether the worker notices `expiring_with_running_job` and extends, or loses the job to the clock and says so.
4. A worker that dies mid-job. The box carries a running job and nobody to release it. The watchdog alone takes it down. This is the standing DELETE canary from plan 1, with a live job on the box.
5. One endpoint, two consumers. A served model handed to two workers through its `url` and `api_key`, used at the same time, and dead after `release`.
6. Group verbs on a real group: `status --group`, `extend --group --to`, `release --group`.
7. The comeback. Nigel returns after an hour and reads the account cold. The lead's report, `vasty status --verbose` and `vastai show instances --raw` agree.

Each phase lists its commands, the pass check, the cap and the cleanup. The lead records every command it runs under `/private/tmp/vasty-live3/out/lead/`. Each worker records its own under `/private/tmp/vasty-live3/out/<worker>/`. The worker reports are saved verbatim.

## 2. Facts that shape the run

- A worker is a Claude Code subagent. Its shell inherits the session environment. Its foreground Bash call times out at 10 minutes, so a 15-minute attached `run` cannot finish in one call. What a worker does about that is part of the record.
- A lease name resolves under the caller's owner only. A lease id resolves for any owner. A worker that sets its own `VASTY_OWNER` and targets `hub` by name gets `lease_not_found`; by id it works.
- `run --on` starts a second job on a box that already has one. Two workers on `hub` run at once and share the GPU.
- `vastai/base-image:cuda-12.6.3-auto` ships Python 3.12 and pip and no torch. `vastai/pytorch:cuda-12.6.3-auto` is 18 GB. The `worker` profile installs torch through the startup hook, about 2.5 GB over the wire. The box reports `pending` until the hook exits 0, so the boot time of `hub` includes the install.
- Every networked `vasty` command runs the sweep. The abandoned-worker phase runs last, and no vasty command runs on the laptop from that box's `expires_at` until `vastai show instances --raw` returns `[]`.
- `serve` on a 12.x host with the vLLM image fails with error 804. The serve box asks for `--cuda 13` and a 3060, which run 2 served in 138 s on a host with the image cached.
- Run 2 figures for cost: a 3060 at $0.06 to $0.09/hr, bandwidth $6.67 to $26.67/TB by host, the 0.5B model 988 MB.

## 3. Setup

Local, no spend. Every command runs from `/private/tmp/vasty-live3` with the repo venv on PATH.

```
export PATH=/Users/nigel.gilbert/Desktop/bench/vasty/.venv/bin:$PATH
export VAST_API_KEY=$(cat ~/.config/vastai/vast_api_key)
mkdir -p /private/tmp/vasty-live3/fx /private/tmp/vasty-live3/out/lead
cd /private/tmp/vasty-live3
```

0. `vastai show instances --raw` returns `[]`. `vastai show user --raw`: record `credit` as the start of `out/ledger.md`.
1. `env | grep '^VASTY_'` prints nothing. `~/.config/vasty/config.toml` is absent.
2. Offer pool. Record the top 5 RTX 3060 offers by reliability, and the CUDA 13 subset:

```
vastai search offers 'gpu_name=RTX_3060 verified=true rentable=true rented=false num_gpus=1 dph_total<=0.20 disk_space>=40' -o dph_total --raw
vastai search offers 'gpu_name=RTX_3060 verified=true rentable=true rented=false num_gpus=1 cuda_max_good>=13.0 dph_total<=0.20 disk_space>=40' -o dph_total --raw
```

Stop if the second search returns fewer than 3 offers; phase 3 needs one.

3. Config at `/private/tmp/vasty-live3/vasty.toml`:

```toml
owner = "lead"

[defaults]
ttl = "20m"
run_ttl = "20m"
gpu = "3060"
max_price = 0.15
disk = 40

[profiles.worker]
startup = '''
pip install --quiet torch --index-url https://download.pytorch.org/whl/cu126
python -c "import torch; assert torch.cuda.is_available()"
'''

[profiles.vllm]
image = "vllm/vllm-openai:v0.32.0"
cuda = 13
```

4. `vasty config show` reports `project` for owner, ttl, run_ttl, gpu, max_price and disk. `vasty config show --profile vllm` resolves `gpu 3060`, `cuda 13`, `max_price 0.15`.
5. Fixtures in `fx/`, one directory per task. Each script writes under `/workspace/out/`.
   - `bench/bench.py`: times 20 float16 8192² matmuls on `cuda:0`, writes `bench.json` with `gpu`, `tflops`, `seconds`.
   - `check/check.py`: reads `fx/check/data.csv`, writes `check.log` with 3 lines of progress, then exits 3 with `ValueError: column "amount" has 2 nulls` on stderr. The brief calls it a data check.
   - `burn/burn.py --minutes N`: runs a small matmul loop, appends one line per minute to `burn.log` with the minute and the GPU temperature from `nvidia-smi`, writes `done` as the last line.
   - `summarize/summarize.py --url URL --key KEY --in DIR --out FILE`: POSTs each file in `DIR` to `/chat/completions` with urllib, 6 at a time, writes one JSON line per document.
   - `summarize/corpus/`: 12 text files of 2 to 4 KB each.
6. `vasty status` on the empty account. Pass: `leases: []`, `totals.credit` is a number, no `spend_unavailable` warning.
7. Ledger loop in the background: `vastai show user --raw` every 60 seconds to `out/ledger.md` while any instance exists.

Nigel's go, recorded in `out/ledger.md` with the time. Nigel leaves after phase 1's workers are spawned and returns for phase 5.

## 4. Worker briefs

Every worker gets the same preamble and one task block. The preamble is fixed here so the run cannot tune it mid-flight. Workers are spawned with the Agent tool, `subagent_type` general-purpose, model Opus, run in the background.

Preamble:

> You are worker `<name>` in a swarm that shares a Vast.ai account through the `vasty` CLI. Read `/Users/nigel.gilbert/Desktop/bench/vasty/README.md` first, in full. `vasty` is on PATH and `VAST_API_KEY` is set; never print it. Work from `/private/tmp/vasty-live3`; the config there applies.
>
> Rules. Create nothing over $0.15/hr or 20 minutes. Release every box you create. Leave boxes you did not create as you found them. Before each `vasty` command, write it to `/private/tmp/vasty-live3/out/<name>/NN-<verb>.cmd`, and save its stdout, stderr and exit code beside it. Report at the end: the leases you touched with their ids, each job's exit code, the `cost` each release returned, and anything that surprised you. Ask no questions; decide and record why.

The preamble says nothing about `--on`, `--json`, owners, `busy`, `--detach` or `extend`. The README covers them. Whether a worker finds them is the measurement.

Task blocks:

- **w1, bench.** "The lead reserved box `hub` (lease `L_HUB`, group `swarm`) for this swarm. Run `fx/bench/bench.py` on a GPU and bring `bench.json` back to `out/w1/`. Report the TFLOPS figure."
- **w2, check.** "The lead reserved box `hub` (lease `L_HUB`, group `swarm`) for this swarm. Run the data check `fx/check/check.py` against `fx/check/data.csv` on a GPU box and report whether the data passed."
- **w3, burn.** "The lead reserved box `long` (lease `L_LONG`) for you. Run `fx/burn/burn.py --minutes 15` on it and bring back the finished `burn.log`. Report the last line."
- **w4, solo.** "Run `fx/burn/burn.py --minutes 25` on a GPU box of your own. Report when it is done." The lead stops this worker once its job is running (phase 4).
- **w5 and w6, summarize.** "A model is served at `URL` with key `KEY` on lease `L_LLM`, OpenAI-compatible. Summarize the documents in `fx/summarize/corpus/` with `fx/summarize/summarize.py` into `out/<name>/summaries.jsonl`. If the endpoint stops answering, check `vasty status L_LLM` and report what it says. Do not include the key in your report."

Scored per worker, from its saved commands:

| Rule | Evidence |
|---|---|
| `status` before any create | first `.cmd` file |
| reuse with `--on` | a `run --on` against the brief's lease |
| id or name | which form it passed, and the result if it set its own owner |
| JSON mode | `--json` on networked commands |
| job sized against the clock | a `status` read before `run`, an `extend` when `ttl_remaining_s` fell short |
| warnings acted on | a warning's `fix` run as given |
| cleanup | boxes it created released, `hub` and `long` left up |
| honest report | exit codes and `cost` as returned, no key in the text |

## 5. Phases

Every phase ends with `vasty status --json` saved. Box ready check after each reserve, as in plan 1:

```
vasty ssh L -- 'cat /workspace/.vasty/startup.exit; ls /workspace/.vasty/alive /workspace/.vasty/guard; command -v tmux'
```

### Phase 1: shared box, two workers. Cap $1.00.

Lead:

```
vasty reserve --name hub --group swarm --profile worker --ttl 30m --json
# box ready check
vasty ssh hub -- 'python -c "import torch; print(torch.cuda.get_device_name())"; cat /workspace/.vasty/startup.log | tail -5'
```

Record the boot time to `running` and the hook's install time from `startup.log`. Then spawn w1 and w2 in one message. While they run, the lead reads `vasty status --group swarm --json` every 60 seconds to `out/lead/p1-sample-NN.json` and touches nothing.

Pass:

- w1 returns a TFLOPS figure and `out/w1/bench.json` exists.
- w2 reports the check failed with exit 3 and quotes the `ValueError`.
- `hub` is `running` after both report. `status hub --json` lists the jobs with exits 0 and 3.
- The number of instances created during the phase is recorded. Zero beyond `hub` means both reused. One or two means a worker created its own; pass if it released it.

### Phase 2: a job that outlives its lease. Cap $0.50.

Lead:

```
vasty reserve --name long --profile worker --ttl 12m --json
# box ready check
```

Spawn w3 as soon as the box is ready. The job runs 15 minutes on a 12-minute clock. The lead samples `vasty status long --json` every 60 seconds and runs no `extend`.

Pass, either branch recorded:

- Extended: w3 ran `extend` before expiry, `burn.log` has 15 minute-lines and `done`, w3 reports the last line.
- Lost: the box expired with the job running. The lead's samples show `expiring_with_running_job` before and the lease `expired` after. w3 reports the loss and the exit it saw.

Then the lead runs `vasty status long --verbose --json` and records the job record and `cost`. If `long` is still up, the lead leaves it for phase 3's group commands.

### Phase 3: one endpoint, two consumers. Cap $1.50.

Lead:

```
vasty serve --profile vllm --model Qwen/Qwen2.5-0.5B-Instruct --name llm --group swarm --ttl 30m --json
curl -s -o /dev/null -w "%{http_code}\n" URL/models                      # expect 401
curl -s -H "Authorization: Bearer $KEY" URL/models | head -c 300           # expect the model
vasty status --group swarm --json
vasty extend --group swarm --to 20m --json
vasty status --group swarm --json
```

Pass for the group commands: `status --group swarm` lists `hub` and `llm` (and `long` if it survived and was tagged into the group). `extend --to` returns one `results` entry per lease with `ok: true` and `expires_at` values within 5 s of each other.

Spawn w5 and w6 in one message with `URL`, `KEY` and `L_LLM` filled in. While they run:

```
vasty ssh llm -- 'tail -n 40 /workspace/.vasty/jobs/j-1/log'    # once, at 60 s
```

Pass:

- Both workers produce `summaries.jsonl` with 12 lines.
- The vLLM log shows requests from both runs interleaved, under 1 minute from first to last.
- Neither report contains the key. `grep -r "$KEY" out/` finds nothing outside the lead's own serve capture, which is redacted at the end.

Teardown of the group:

```
vasty release --group swarm --json
curl -s -o /dev/null -w "%{http_code}\n" --max-time 10 URL/models        # expect a connection failure
vastai show instances --raw
```

Pass: `release --group` returns one summary per lease with `cost`. The curl fails. `vastai show instances --raw` lists nothing from the group.

### Phase 4: the abandoned worker. Cap $0.50.

No lead reserve. Spawn w4. The lead polls `vasty status --all --everyone --json` every 60 seconds until a lease owned by w4's shell shows `busy: true`, records its `lease`, `expires_at` and `instance_id`, then:

```
# stop w4 with TaskStop
pkill -f "vasty sweep --follow"
ps aux | grep '[v]asty'                                         # expect nothing
```

From here until the box is gone, the lead runs no `vasty` command. Watch with:

```
vastai show instances --raw                                      # every 60 s, to out/lead/p4-watch.txt
```

Pass: the instance leaves `vastai show instances --raw` within 3 minutes of `expires_at`, with no vasty process on the laptop. Record the gap. If the instance is still listed 5 minutes past `expires_at`, destroy it with `vastai destroy instance ID -y`, record the failure, and continue to phase 5.

After the box is gone: `vasty status --verbose --json`. Record the lease's state, its job record, and any `expired_with_running_jobs` warning.

If w4 ran an attached `run` with no `--on`, stopping the worker kills the ssh session and the run exits as a lost attach. The box stays up with the job. The test is the same.

### Phase 5: the comeback. No spend.

Nigel, without reading the lead's report first:

```
vastai show instances --raw
vasty status --verbose --json
vastai show user --raw
ps aux | grep '[v]asty'
```

Then reads the lead's report and compares: every lease the lead names appears in `status --verbose` with the state the report gives, `cost` per lease sums to within $0.05 of the ledger's drop, no process remains, no instance remains.

Teardown:

```
vasty release --all --everyone --yes --json
vastai show instances --raw                                      # expect []
grep -rl "$KEY" out/; grep -rlE "vasty-[0-9a-f]{32}" out/; grep -rl "CONTAINER_API_KEY=" out/
```

Redact any hit by value. Run `uv run pytest` and `uv run mypy` once more and record the counts.

## 6. Cost proposal

Box time is the sum of TTLs each phase can consume plus extensions. Loading time is unbilled.

| Phase | Boxes | Box time | Estimate | Cap |
|---|---|---|---|---|
| 1 Shared box | 1 to 3 | 30m to 70m | $0.05 to $0.12 | $1.00 |
| 2 Clock pressure | 1 | 12m to 20m | $0.03 | $0.50 |
| 3 Endpoint, group | 1 | 30m | $0.05 | $1.50 |
| 4 Abandoned | 1 | 20m | $0.03 | $0.50 |
| Bandwidth: torch ×2, vLLM image, model | | | $0.13 to $0.60 | |
| Retries and worker mistakes | | | $0.50 | |
| Total | 4 to 6 | ~2h | $0.80 to $1.35 | $5.00 |

Bandwidth: 2.5 GB of torch per `worker` box, 9.2 GB for the vLLM image when the host has no cache, 1 GB of weights. At $9/TB the run moves about 15 GB for $0.13; at $27/TB, $0.40. A worker that creates its own `worker`-profile box adds 2.5 GB.

## 7. Guardrails for the lead

- Caps are balance drop per phase. Stop the phase at the cap, release its boxes, and report.
- At most 7 instances over the run, counting workers' creations. Read `vasty status --all --everyone --json` after each worker reports.
- Stop and run phase 5 teardown when: the cumulative drop passes $5.00; an instance in `vastai show instances --raw` matches no lease in `status --verbose` apart from phase 4's box; vasty prints a traceback; two consecutive creates return `no_offers` or `provider_error`; a worker asks a question instead of deciding.
- Workers are never corrected mid-task. A worker that stalls past 25 minutes is stopped and its box released by the lead, and the stall is the finding.
- Phase 4 runs after phase 3's group is gone. No vasty command runs on the laptop from phase 4's `expires_at` until `vastai show instances --raw` returns `[]`.
- Redact the Vast key, the serve key and `CONTAINER_API_KEY` by value in every saved file.
- Nigel decides any create outside this plan. With Nigel away, the lead skips it and records the skip.

## 8. Report

Append each phase to `/private/tmp/vasty-live3/out/report.md` as it ends: pass or fail per check, the JSON that proves it, the worker scorecards from section 4 with the `.cmd` files they rest on, boot and install times, the balance delta. Save each worker's final message under `out/<worker>/report.md`.

After the run, copy reviewed files to `/Users/nigel.gilbert/Desktop/bench/vasty/docs/live/` (gitignored) and write the report at `/Users/nigel.gilbert/Desktop/bench/vasty/docs/live-test-report-3.md`. Observations that name a change to vasty go in the report's last section, one per bullet, with the worker command that exposed each.
