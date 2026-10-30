# Live test plan: vasty against a funded Vast.ai account

Run by a Claude Code agent with Nigel supervising. Spend ceiling: $20 on the account. Stop the run at a cumulative balance drop of $5.50.

## 1. What this run settles

The unit suite runs against fakes. Nothing in the repo has touched Vast. This run checks, in order of value:

1. The clock holds. A box destroys itself when its clock runs out, with no vasty process on the laptop. The sweep destroys a box whose watchdog is dead.
2. `reserve`, `status`, `extend`, `release`, `run`, `sync`, `ssh`, `tag` work end to end on a real box, with the JSON shapes the README documents.
3. The open questions below.
4. `serve` brings up a small model behind the endpoint.

Open questions and where each is answered:

| Question | Phase | Command | Record |
|---|---|---|---|
| `CONTAINER_API_KEY` present in the container | 1 | `sed` over `/workspace/.vasty/env` | set or absent |
| Container key can read its own instance row | 1 | curl `GET /instances/ID/` with the key | HTTP status |
| `ports` absent until running | 1 | `reserve --no-wait`, poll `vastai show instances --raw` every 10s | first sample with `ports`, or "transition not observed" |
| `/charges` clips to the day and its lag | 1, 3 | `vasty status` beside the balance drop | `spent_today` vs balance drop |
| Container key `DELETE` destroys a running box | 2a | watchdog runs unattended | box gone or not |
| Container key `DELETE` while `loading` | deferred | | |
| Label length at create, 404 as unauthorized, `on-demand` spelling, `schedule_job` | deferred | | |

Each phase lists its commands, the pass check, the spend cap, and the cleanup. The agent records every command and its output under `/private/tmp/vasty-live/out/`, appends each phase's results to the report as the phase ends, and copies reviewed files into the repo at the end (section 7).

## 2. Facts that shape the run

- The default image `vasty/base:cuda12.4` is not published. Docker Hub has no `vasty` namespace. Every live box uses `vastai/base-image:cuda-12.6.3-auto` through `defaults.image` in the test config. This exercises the custom-image path in `onstart.py`: the essentials installer and the watchdog carried in `onstart`. The published-image path stays untested until the image exists.
- vasty takes the most reliable offer under `max_price` (the offer sort: reliability, bandwidth, price). The test config pins `gpu = "3060"` and a `max_price` read from the live pool, so the rate is known before the first create. A snapshot of verified on-demand offers on 2026-10-29 (unauthenticated `POST /bundles/`, cheapest `dph_total`): RTX 3060 $0.056 with 27 offers, RTX A2000 $0.052, GTX 1080 Ti $0.062, RTX 2080 Ti $0.084, RTX 3070 $0.082, RTX 3090 $0.156, RTX 4090 $0.342. `dph_total` carries the disk charge at a median $0.20/GB/month, so 16 GB adds about $0.005/hr.
- Vast bills no GPU time while an instance is `loading`. Storage and bandwidth bill in every state. The `cuda-12.6.3-auto` tag is 6 GB compressed and is often cached on hosts; `vastai/base-image:cuda-12.9-mini-py312` is 2.5 GB when a pull is slow.
- `vastai/base-image` ships cron, rsync, curl and python 3.12. Vast's runtime injects sshd in SSH launch mode. tmux is absent, so the essentials installer in `onstart` puts it there on every box. Boot is 1 to 5 minutes plus the pull.
- `onstart` writes `startup.started` last, after the installer, the watchdog and `/etc/cron.d/vasty`. A probe that lands earlier can report `running` with `guard: full` before the watchdog exists. Every phase that depends on the guard or on tmux checks the box first (section 4, "box ready check").
- Vast injects `CONTAINER_ID` and `CONTAINER_API_KEY` into every instance. The create response names the key as restricted to start, stop and destroy of that instance. The raw `DELETE` the watchdog sends is untested until phase 2a.
- vasty creates `ssh_proxy` on an offer without direct ports and then requires no port mapping, so a proxy box has no 8000 or 8080 mapping. Search does not filter on `direct_port_count`.
- `spent_today` on an account with no charge rows estimates every live box as running since 00:00 UTC. The budget check can refuse a valid reserve late in the UTC day. 00:00 UTC is 19:00 Central. The ledger in this plan uses the account balance, which has no day boundary.
- `vasty status` runs the sweep. `vasty status --cached` reads `leases.json` and shows a local countdown only. Watching a box leave means `vastai show instances --raw`.
- Bulk selectors never include orphans, `--everyone --yes` included. An orphan is released by its `i-` id or by `vastai destroy instance`.
- vLLM 0.6.3 needs compute capability 7.0 and CUDA 12.1 wheels, about 3 GB of downloads. The 1080 Ti is out for `serve`; the 3060 qualifies.
- Minimum deposit is $5. With no card on file, Vast stops instances at $0 and destroys them after a grace period. A card-free account has no autobilling. The account-level stop is the prepaid balance with no card saved. Fund the account with the ceiling and nothing more.

## 3. Setup

Local, no spend. Every command in this plan runs from `/private/tmp/vasty-live` with the repo venv on PATH.

```
export PATH=/Users/nigel.gilbert/Desktop/bench/vasty/.venv/bin:$PATH
export VAST_API_KEY=...            # never echo it
mkdir -p /private/tmp/vasty-live/fx /private/tmp/vasty-live/out
cd /private/tmp/vasty-live
```

0. `vastai show instances --raw`. Destroy anything listed with `vastai destroy instance ID -y`. Record the ids in the ledger.
1. Vast account holds $20 and no saved card. `vastai show user --raw` returns the account. Record the starting balance in `/private/tmp/vasty-live/out/ledger.md`.
2. `~/.ssh/id_ed25519` present. `reserve` registers the public key on first use.
3. `env | grep '^VASTY_'` prints nothing and `~/.config/vasty/config.toml` is absent.
4. Fixtures in `/private/tmp/vasty-live/fx/`: `hello.py` printing the hostname and the output of `nvidia-smi -L`, and `data.txt` with one known line.
5. Offer pool. Run:

```
vastai search offers 'gpu_name=RTX_3060 verified=true rentable=true rented=false num_gpus=1 dph_total<=0.25 disk_space>=16' -o dph_total --raw
```

Print `id`, `gpu_name`, `dph_total`, `reliability`, `cuda_max_good`, `direct_port_count` and the bandwidth rates for each row. Set `max_price` below to the highest `dph_total` among the top 5 by reliability, about 0.12. Note hosts with `direct_port_count` under 3.

6. Test config at `/private/tmp/vasty-live/vasty.toml`:

```toml
owner = "live-test"

[defaults]
ttl = "15m"
run_ttl = "15m"
gpu = "3060"
max_price = 0.12          # from step 5
daily_budget = 6.00
warn_before_expiry = "5m"
disk = 16
image = "vastai/base-image:cuda-12.6.3-auto"
```

7. `vasty config show` reports `project` for owner, ttl, run_ttl, gpu, max_price, daily_budget, warn_before_expiry, disk and image.
8. `/Users/nigel.gilbert/Desktop/bench/vasty/.venv/bin/python -X importtime -c 'import vastai' 2>&1 | tail -1`, for the import-time budget. Record the number.
9. `vasty status` on the empty account. Pass: `leases: []`, `totals.spent_today` is a number, `spend_source` is `billing`, no `spend_unavailable` warning.

Stop here if step 9 fails. The charges endpoint is the base for every budget check.

## 4. Phases

Every phase ends with `vastai show instances --raw` returning `[]`. Boxes carry a 15m default TTL. Two windows have no working clock: 2b after the watchdog is killed, and the phase 4 orphan before `vasty tag`. Nigel watches both. If the agent stops, Nigel runs `vastai show instances --raw` and destroys each id.

Read the balance before each create and every 60 seconds while any instance exists. After a phase's last box leaves `vastai show instances --raw`, read it twice 120 seconds apart and keep the second reading. Spend caps are per phase, measured as balance drop. Stop the phase at the cap and report.

Box ready check, run after every `reserve` that precedes a guard check, phase 2b, or a `run`:

```
vasty ssh L -- 'cat /workspace/.vasty/startup.exit; ls /workspace/.vasty/alive /workspace/.vasty/guard; command -v tmux'
```

Continue when `startup.exit` holds `0`, both files exist and tmux resolves. If `reserve` returned `running` before that, file a bug against the `pending` state rule and keep going.

### Phase 1: one box, full lifecycle. Cap $0.50.

```
vasty reserve --name p1 --no-wait
vastai show instances --raw            # every 10s until ports appear; record the first sample with ports
vasty status p1                          # poll every 30s until state is running
vasty reserve --name p1                  # same name: reused, no second instance
vasty status
vasty status p1 --verbose
vasty ssh p1 -- "sed 's/^CONTAINER_API_KEY=.*/CONTAINER_API_KEY=<redacted>/' /workspace/.vasty/env; cat /workspace/.vasty/clock /workspace/.vasty/guard"
vasty ssh p1 -- 'cat /etc/cron.d/vasty; pgrep -af "[w]atchdog.sh"; ls /workspace/.vasty'
vasty ssh p1 -- 'curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $(sed -n s/^CONTAINER_API_KEY=//p /workspace/.vasty/env)" https://console.vast.ai/api/v0/instances/$(sed -n s/^CONTAINER_ID=//p /workspace/.vasty/env)/'
vastai show instances --raw
vasty status p1                          # one minute after the previous status
vasty release p1
```

Pass:

- The second `reserve --name p1` returns `reused: true` and `vastai show instances --raw` lists one instance.
- Once `running`, `status p1` returns `ports` with 22, 8000 and 8080 mapped. A proxy box (no `direct_port_count`) returns `{}` for ports; record it as an offer note.
- `expires_at` as epoch seconds equals the clock file.
- The instance label on Vast parses as `vasty:v1;lease=X;name=p1;owner=live-test;created=N;ttl=900;expires=M`.
- The JSON `guard` is `full`. If `partial`, record `guard_missing` and whether `CONTAINER_API_KEY` is set.
- The curl line prints an HTTP status. Record it as the answer to "the container key reads its own row".
- `status` reports `cost_source` in billing, mixed or estimated, and a numeric `cost`. Record `cost`, `uptime_s` and `totals.spent_today` from both calls beside the balance drop.
- `release` returns `uptime_s`, `cost`, `jobs: []`, and `cost` is within $0.02 of `price_per_hr` × `uptime_s` / 3600.
- Boot time from the first `reserve` to `running` recorded, for the TTL floor used later.

### Phase 2: the clock. Cap $1.00.

2a. Watchdog alone.

```
vasty reserve --name wd --ttl 8m
# box ready check
vastai show instances --raw            # every 60s past expires_at
```

Run no networked vasty command from `expires_at` until `vastai show instances --raw` no longer lists the box. Pass: the instance is gone within 2 minutes after `expires_at`. The watchdog log is lost with the box, so the proof is the disappearance. Then `vasty status wd`. Pass: `state: expired`, `swept: []`.

Rerun with `--ttl 6m` only if 2a passes, to find the floor where boot eats the TTL. Skip if boot in phase 1 took over 3 minutes.

2b. Sweep alone.

```
vasty reserve --name sw --ttl 8m
# box ready check
vasty ssh sw -- 'rm -f /etc/cron.d/vasty; pkill -f "[w]atchdog.sh"; sleep 2; rm -f /workspace/.vasty/alive; pgrep -f "[w]atchdog.sh" || echo watchdog_dead'
vasty status sw                          # expect guard_partial, watchdog missing
# after 70s
vasty ssh sw -- 'pgrep -f "[w]atchdog.sh" || echo watchdog_dead; ls /workspace/.vasty/alive'
```

Continue only when both checks print `watchdog_dead` and `alive` is absent. Run no networked vasty command from `expires_at` until the next step. At `expires_at` + 1m, confirm `vastai show instances --raw` still lists the box, then run `vasty status sw`. Pass: `swept` names `sw` with `ok: true` and `error: null`, the instance is gone, and `vasty status sw` reports `expired`. If `sw` is still listed at `expires_at` + 3m, run `vasty release sw` and fail 2b.

2c. Extend both ways.

```
vasty reserve --name ex --ttl 10m
vasty extend ex --by 10m
vasty ssh ex -- cat /workspace/.vasty/clock
VASTY_DAILY_BUDGET=0.01 vasty extend ex --by 10m     # expect budget_exceeded, exit 3
vasty ssh ex -- cat /workspace/.vasty/clock
vasty extend ex --to 3m
vasty ssh ex -- cat /workspace/.vasty/clock
vastai show instances --raw            # every 60s past the new expires_at
```

Pass: after each successful `extend`, the clock file and the label `expires=` equal the returned `expires_at` as epoch seconds. The refused `extend` returns `budget_exceeded`, exit 3, and leaves the clock file and label unchanged. After `--to 3m`, the watchdog destroys the box within 2 minutes of the new expiry. This proves a shortened clock is honored after the sleep.

2d. Reserve past budget. No box needed.

```
VASTY_DAILY_BUDGET=0.01 vasty reserve --name nope
```

Pass: `budget_exceeded`, exit 3, `details` with `projected`, `remaining`, `daily_budget`, and no instance created.

### Phase 3: run and sync. Cap $1.00.

```
vasty run -- nvidia-smi -L
vasty run -- false
vasty run --sync /private/tmp/vasty-live/fx -- python3 hello.py
vasty reserve --name rb --ttl 15m
# box ready check
vasty sync rb push /private/tmp/vasty-live/fx/ work/
vasty run --on rb -- cat work/data.txt
vasty run --on rb --detach -- bash -c 'sleep 120; echo done | tee work/out.txt'
vasty status rb                          # poll until the job exits 0, 3 minute deadline
vasty sync rb pull work/out.txt /private/tmp/vasty-live/out/out.txt
python3 -c 'import subprocess,signal,time;p=subprocess.Popen(["vasty","run","--on","rb","--","sleep","300"]);time.sleep(10);t=time.time();p.send_signal(signal.SIGINT);rc=p.wait(timeout=30);print(rc,round(time.time()-t,1))'
vasty release rb
```

Pass:

- Auto-reserved `run` returns `exit: 0`, `released: true`, and the box is gone.
- `run -- false` exits 1 with `exit: 1`, `error: null`, `released: true`, and the box is gone.
- `--sync` lands the fixture under `/workspace` and the job prints the hostname and a GPU line.
- `--detach` returns `job` and `log_path` at once. `status rb` lists the job as running, then exited 0, and `log_tail` ends with `done`. The pulled file holds `done`.
- The SIGINT script prints `130` within 10s of the signal, and `rb` stays listed.
- `release rb` lists every job with its exit code.
- On `budget_exceeded`, record `details` and compare with the balance drop before any retry.

### Phase 4: owners, groups, orphans. Cap $1.00.

Pick OFFER as the first `id` from:

```
vastai search offers 'gpu_name=RTX_3060 verified=true rentable=true rented=false num_gpus=1 dph_total<=0.12 disk_space>=16 direct_port_count>=3' -o dph_total --raw
```

```
vastai create instance OFFER --image vastai/base-image:cuda-12.6.3-auto --disk 16 --ssh --direct
# the orphan is i-<new_contract>; record it in the ledger at once
vastai show instances --raw            # poll until actual_status is running with ssh_host and ssh_port set
vasty status                             # orphan with i- id and orphan warning
vasty tag i-ID --ttl 8m
vasty status i-ID --verbose
vastai show instances --raw            # every 60s past expires_at
```

Pass: the orphan appears with `state: orphan` and the `vasty tag` fix. `tag` returns `results[0].guard: full`. If `partial`, record it and run `vasty status i-ID` once to retry the adoption. The watchdog destroys the box within 2 minutes of the clock. If the box is still listed at `expires_at` + 3m, run `vasty release i-ID --yes` and fail the check.

```
vasty reserve --name g0 --group grp --ttl 15m
vasty reserve --name g1 --group grp --ttl 15m
vasty status --group grp
vasty extend --group grp --to 12m
VASTY_OWNER=other vasty release --all      # releases nothing
vasty release --group grp
```

Pass: `status --group` lists both; bulk `extend` returns `results` with two entries, each `ok: true`; `release --all` under another owner returns an empty result with exit 0 and both boxes live; `release --group` returns two summaries. On `budget_exceeded`, record `details` and compare with the balance drop before any retry.

### Phase 5: serve. Cap $2.00. Needs a go from Nigel before it starts.

A 3060 has 12 GB VRAM and compute capability 8.6, enough for a 0.5B model under vLLM 0.6.3. The install downloads about 3 GB of wheels into `/workspace/.vasty/venv`. The model is ungated, 988 MB. The box clock starts at onstart and covers the essentials install, and `serve` allows 30m for the vLLM install plus 30m for readiness, so the lease runs 45m and the install has a 20m stop.

```
vasty reserve --name sv --vram 12 --ttl 45m --disk 40
# box ready check
vasty ssh sv -- df -h /workspace
vasty serve --on sv --model Qwen/Qwen2.5-0.5B-Instruct
curl -H "Authorization: Bearer $KEY" URL/models
curl URL/models                        # expect 401
vasty release sv
```

Before `serve`, check that `sv` returned `ports` with `8000`. If it is missing, release `sv` and reserve again. Stop the phase if the install runs past 20 minutes.

Pass: `serve` returns `url` and `api_key`, the authorized call lists the model, the unauthorized call gets 401. On `serve_failed`, save the error's `details.output` and run `vasty ssh sv -- 'tail -n 100 /workspace/.vasty/jobs/*/log'`. Check the remaining lease time, then rerun `vasty serve --on sv` once; the retry reuses the installed venv. Stop after the retry. After the phase, run `grep -r "$KEY" /private/tmp/vasty-live/out` and expect no match.

### Phase 6: teardown. No spend.

```
vasty release --all --everyone --yes
vasty status
vastai show instances --raw
vastai show user --raw
```

For each id that `vastai show instances --raw` still lists, run `vasty release i-ID --yes`. If vasty fails, run `vastai destroy instance ID -y` for each id. Rerun `vastai show instances --raw` until it returns `[]`.

Pass: `vastai show instances --raw` returns `[]`. Final balance recorded.

## 5. Cost proposal

vasty takes the most reliable offer under `max_price`. The estimate uses `max_price` at $0.12/hr plus disk. Box time is the sum of TTLs each phase can consume if every box runs to its clock. Loading time is unbilled.

| Phase | Boxes | Box time | Estimate | Cap |
|---|---|---|---|---|
| 1 Lifecycle | 1 | 15m | $0.05 | $0.50 |
| 2 Clock | 3 to 4 | 45m | $0.10 | $1.00 |
| 3 Run and sync | 4 | 60m | $0.15 | $1.00 |
| 4 Owners, groups, orphans | 3 | 40m | $0.10 | $1.00 |
| 5 Serve, 40 GB disk | 1 | 45m | $0.10 | $2.00 |
| Bandwidth: image pulls, wheels, model | | | $0.25 to $1.15 | |
| Retries and mistakes | | | $1.00 | |
| Total | | ~3.5h | $1.75 to $2.60 | $5.50 |

Bandwidth is host-priced at $3 to $14 per TB, with outliers to $27. 13 boxes pull about 82 GB: $0.25 at $3/TB, $1.15 at $14/TB, $2.21 at $27/TB. Layers cached on the host cost nothing. Each host's bandwidth rate goes in the ledger. Fund $20 as the account stop. The per-phase caps act as alarms; the run stops at a cumulative balance drop of $5.50.

## 6. Guardrails for the agent

- Every clock runs at most 20m from its start, except phase 5.
- Watch an expiry with `vastai show instances --raw`. Run no networked vasty command from `expires_at` until the box is gone, or until the 2b sweep step.
- Read the balance before each create and every 60 seconds while any instance exists, into `/private/tmp/vasty-live/out/ledger.md`.
- Stop and report when: a phase passes its cap; the cumulative balance drop passes $5.50; an id in `vastai show instances --raw` matches no `instance_id` in `vasty status --verbose`, apart from the phase 4 orphan before `tag`; vasty prints a traceback; two consecutive `reserve` calls return `no_offers` or `provider_error`.
- On any stop, create nothing more, run phase 6, then write the report.
- Redact `CONTAINER_API_KEY` and the serve key by value in every saved file. Instance ids, ips and ports are fine to keep.
- Ask Nigel before phase 5 and before any command outside this plan that creates an instance.

## 7. Report

Append each phase's results to `/private/tmp/vasty-live/out/report.md` as the phase ends: pass or fail per check, the JSON that proves it, boot times, the balance delta, and the answers to the open questions touched. After the run, review the files for keys and copy them to `/Users/nigel.gilbert/Desktop/bench/vasty/docs/live/` (gitignored) with the report at `/Users/nigel.gilbert/Desktop/bench/vasty/docs/live-test-report.md`. Bugs found go to `/Users/nigel.gilbert/Desktop/bench/vasty/issues/` as one file each, with the command, the output and the rule it breaks.
