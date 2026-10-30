# vasty live test report, 2026-10-29

Account 836500, burner. Starting credit $20.00, balance $0. Run from `/private/tmp/vasty-live` with the repo venv on PATH. Raw command output stays local under `docs/live/`, which is gitignored.

## Setup

| Step | Result |
|---|---|
| 0 `vastai show instances --raw` | `[]`, nothing to destroy |
| 1 account | id 836500, credit 20.00, balance 0, `has_billing: true` (confirmed with Nigel before phase 1, see below) |
| 2 ssh key | `~/.ssh/id_ed25519` present |
| 3 env | no `VASTY_*`, no `~/.config/vasty/config.toml` |
| 4 fixtures | `fx/hello.py`, `fx/data.txt` |
| 5 offer pool | 32 verified RTX 3060 offers, dph 0.052 to 0.207. Top 5 by reliability all 0.999, max dph 0.084. `max_price` set to 0.09. No host under `direct_port_count` 3. Bandwidth outliers: Vietnam hosts at $0.04/GB, Texas at $0.039/GB, Poland at $0.0088/GB. Full table in `docs/live/setup-5-offers.json`. |
| 6 config | `vasty.toml` written |
| 7 `vasty config show` | owner, ttl, run_ttl, gpu, max_price, daily_budget, warn_before_expiry, disk, image all `source: project`. Pass. |
| 8 `import vastai` | 244,611 us cumulative (244 ms) |
| 9 `vasty status` empty | `leases: []`, `spent_today: 0.0`, `spend_source: billing`, no warnings. Pass. |

Nigel confirmed a card is saved on the account. The $5.50 cumulative balance drop in plan section 6 is the only ceiling.

## Phase 1: one box, full lifecycle. Cap $0.50. PASS with notes.

Instance 58321352, lease `l-ce63a58a`, offer 45600114 (Poland, 0.999 reliability, $0.0088/GB bandwidth), `price_per_hr` 0.06. Reserve at 23:27:15Z, `actual_status: running` at 23:28:09Z. Boot 54 s. Image was cached on the host (pull to loaded in 10 s).

| Check | Result |
|---|---|
| `reserve --no-wait` | `state: pending`, `guard: partial`, `guard_missing: [watchdog, destroy_key, clock_file]`, `ports: null`. Pass. |
| `ports` absent until running | Samples at 1 s, 11 s (`actual_status: null`), 22 s and 33 s (`loading`) all had `ports: null`. The 44 s sample was `running` with 22, 8000, 8080 mapped. Transition observed: ports appear with `running`. `docs/live/p1-02-first-sample-with-ports.json`. |
| Second `reserve --name p1` | `reused: true`, same lease, `vastai show instances --raw` lists one instance. Pass. |
| `ports` once running | `{"22": 15124, "8000": 15121, "8080": 15129}`. Direct box. Pass. |
| `expires_at` vs clock file | `2026-10-29T23:43:05Z` = 1793317385 = clock file. Pass. |
| Label | `vasty:v1;lease=l-ce63a58a;name=p1;owner=live-test;created=1793316437;ttl=900;expires=1793317385`. Pass. `expires - created` = 948 s, so the clock starts at onstart, 48 s after create. |
| `guard` | `full`, `guard_layers` all `ok`. Pass. Box ready check: `startup.exit` 0, `alive` and `guard` present, tmux at `/usr/bin/tmux`. |
| `CONTAINER_API_KEY` in `/workspace/.vasty/env` | set. `CONTAINER_ID=58321352` also set. |
| Container key reads its own row | `GET /instances/58321352/` with the container key: HTTP 200. |
| Watchdog | `/etc/cron.d/vasty` runs `watchdog.sh` every minute; `pgrep` shows pid 384 running it. `/workspace/.vasty` holds alive, clock, env, guard, jobs, startup.exit, startup.started, watchdog.lock, watchdog.log, watchdog.sh. |
| `status` cost fields | `cost_source: mixed`, `cost` 0.02 at 23:38 and 0.03 at 23:40, `totals.spent_today: 1.5`, `spend_source: mixed`. Balance drop at those times: $0.0118 and $0.0131. |
| `release` | `uptime_s: 793`, `cost: 0.03`, `jobs: []`, `destroy_pending: true`. 0.06 × 793 / 3600 = 0.0132, within $0.02 of 0.03. Pass. Instances `[]` right after. |

Observations:

- `spent_today` 1.5 against a real balance drop of $0.013. Charge rows lag, so the estimator counts the live box from 00:00 UTC (23.5 h × 0.06 = 1.41) and `spend_source` flips to `mixed`. This is the plan's section 2 caveat in action. `remaining_budget` dropped to 4.5 on a run that had cost one cent.
- `cost` rounds to cents, so the $0.02 tolerance is loose at this rate.
- `status p1` (one lease) includes `log_tail`; `status` (list) omits it.
- `cat /workspace/.vasty/guard` printed an empty line. The guard file exists but holds no content.
- The ssh target in `reserve` is `root@91.150.160.38:15124` (direct), while the Vast row's `ssh_host` is `ssh5.vast.ai:17744` (proxy). vasty prefers the direct mapping.
- The plan's section 4 box ready check was run 10 minutes after boot because of a bug in my poll script, so the earliest point at which `startup.exit` appears is not measured here. `vasty status p1` at 23:28:17 (8 s after `running`) returned `guard: full`, so the watchdog landed within those 8 s or the probe reported full early. Phase 2 checks this sooner.

## Phase 2: the clock. Cap $1.00.

### 2a watchdog alone. PASS.

Instance 58322443, lease `l-15c77c42`, Korean host at $0.08/hr. `reserve --ttl 8m` blocked from 23:43:10Z to 23:47:23Z (4m13s, image pulled). Returned `running`, `guard: full`, `expires_at: 23:55:12Z`, `ttl_remaining_s: 469`. The box ready check passed on the first try right after `reserve` returned: `startup.exit` 0, `alive` and `guard` present, tmux installed. So the blocking `reserve` returned after the watchdog was installed. No bug against the `pending` state rule.

Watched with `vastai show instances --raw` every 30 s from 23:47:47Z. Listed as `running` at expires -15 s (23:54:57Z). Gone at 23:55:27Z, 16 s after `expires_at`. No vasty process ran on the laptop between `expires_at` and the disappearance. `docs/live/p2a-03-watch.txt`.

Answers the open question: the container key `DELETE` destroys a running box. Confirmed by disappearance.

The 6 m rerun is skipped: boot took over 3 minutes.

### 2b sweep alone. PASS.

Instance 58323451, lease `l-7807c965`, $0.07/hr. `reserve --ttl 8m` 23:55:42Z to 23:57:40Z (1m58s). Ready check passed at once. Killed cron entry, watchdog process and `alive` at 23:57:53Z. `vasty status sw` then reported `guard: partial`, `guard_missing: [watchdog]`, warning `guard_partial` with fix `vasty release l-7807c965`. Recheck at 23:59:17Z: `watchdog_dead`, `alive` absent.

`expires_at` 00:05:34Z. `vastai show instances --raw` still listed 58323451 as `running` at expires +5 s and +62 s. `vasty status sw` at 00:06:36Z returned `swept: [{lease: l-7807c965, name: sw, expired_at: 00:05:34Z, ok: true, error: null}]`, lease `state: expired`, `destroy_pending: true`. `vastai show instances --raw` returned `[]` immediately after. A second `vasty status sw` reports `expired` with `swept: []`.

Note: the UTC day rolled over at 00:00 during this phase. `spent_today` reset to 0.01 and `spend_source` returned to `billing`.

### 2c extend both ways. PASS.

Instance 58324722, lease `l-b293ffae`, $0.07/hr, same Korean host as 2b. `reserve --ttl 10m` 00:06:55Z to 00:07:21Z (26 s, image cached). `expires_at: 00:17:08Z`.

| Step | Returned `expires_at` | Clock file | Match |
|---|---|---|---|
| `extend --by 10m` | 00:27:08Z | 1793320028 | yes |
| `VASTY_DAILY_BUDGET=0.01 extend --by 10m` | `budget_exceeded`, exit 3, `details: {projected: 0.05, remaining: -0.03, daily_budget: 0.01}` | 1793320028, unchanged | yes |
| `extend --to 3m` | 00:10:42Z | 1793319042 | yes |

Label after the sequence: `...created=1793318816;ttl=600;expires=1793319042`, equal to the clock file. The label was read only after the final extend; the clock file was read after each one.

Watched past 00:10:42Z. Listed `running` at +1 s, gone at +31 s. A shortened clock is honored after the watchdog's sleep.

### 2d reserve past budget. PASS.

`VASTY_DAILY_BUDGET=0.01 vasty reserve --name nope`: `budget_exceeded`, exit 3, `details: {projected: 0.03, remaining: -0.01, daily_budget: 0.01}`, hint names `--ttl`, `--max-price` and release. `vastai show instances --raw` returned `[]`.

Observation: after 2d, `vasty status` with no selector returned `leases: []` and no warnings, while `vasty status wd` and `vasty status sw` by name returned the expired lease. The default list hides expired leases.

Phase 2 balance: start 19.9862, end 19.9531 after the second post-phase read. Drop $0.033 against a $1.00 cap.

## Phase 3: run and sync. Cap $1.00. PASS.

| Check | Result |
|---|---|
| `run -- nvidia-smi -L` | Printed `GPU 0: NVIDIA GeForce RTX 3060`. `exit: 0`, `duration_s: 2`, `released: true`, `error: null`. Whole command 31 s (00:13:46Z to 00:14:17Z). Instances `[]` after. Pass. |
| `run -- false` | Exit code 1, `exit: 1`, `error: null`, `released: true`. 51 s. Instances `[]` after. Pass. |
| `run --sync fx -- python3 hello.py` | Printed `hostname: 02f726e22312` and the GPU line. `exit: 0`, `released: true`. 46 s. Pass. |
| `reserve --name rb --ttl 15m` | Instance 58325740, lease `l-b970ddcc`, $0.06/hr, Poland host. 2m50s to running. Ready check passed at once. |
| `sync rb push fx/ work/` | Returned `direction: push`, `src`, `dest`. Pass. |
| `run --on rb -- cat work/data.txt` | Printed the fixture line. `exit: 0`, `released: false`. Pass. |
| `run --on rb --detach` | Returned `job: j-2`, `log_path: /workspace/.vasty/jobs/j-2/log`, `expires_at` in 5 s. Pass. |
| `status rb` during the job | `jobs` lists j-1 `exited 0` and j-2 `running`, `exit: null`. `log_tail: []`. |
| `status rb` after | j-2 `exited`, `exit: 0`, `duration_s: 120`, `log_tail: ["done"]`. Seen at 00:21:23Z, 2m08s after start. Pass. |
| `sync rb pull` | `docs/live/out.txt` holds `done`. Pass. |
| SIGINT | Script printed `130 4.5`. vasty printed the job summary `exit: 130`, `duration_s: 8`, `released: false`. `rb` stayed listed. Pass. |
| `release rb` | `uptime_s: 346`, `cost: 0.01`, three jobs with exit 0, 0, 130. Pass. |

No `budget_exceeded` during the phase. Three auto-reserved boxes each lived under a minute and the balance moved by less than a cent each.

## Phase 4: owners, groups, orphans. Cap $1.00. PASS.

### Orphan

`vastai create instance 45598257 --image vastai/base-image:cuda-12.6.3-auto --disk 16 --ssh --direct` at 00:24:30Z returned `new_contract: 58326611` and an `instance_api_key` (redacted in `docs/live/p4-02-create.json`). Running with `ssh_host`/`ssh_port` after 76 s.

| Check | Result |
|---|---|
| `vasty status` | Lease `i-58326611`, `state: orphan`, `owner: null`, `guard: null`, `expires_at: null`, `price_per_hr: 0.05`. Warning `orphan`, message `not created by vasty`, fix `vasty tag i-58326611 --ttl 30m`. `totals.live: 0`, `live_mine: 0` while the orphan is listed. Pass. |
| `vasty tag i-58326611 --ttl 8m` | `results[0]`: lease `l-3905726c`, `owner: live-test`, `expires_at: 00:33:59Z`, `guard: full`. Exit 0. stderr printed `could not attach the SSH key to l-3905726c: Vast attach ssh key failed: SSH key already associated with instance.` Harmless on this account, since `vastai create --ssh` had already attached the same key. Pass. |
| `status i-58326611 --verbose` | The `i-` id resolved to the new lease. Label `vasty:v1;lease=l-3905726c;owner=live-test;created=1793319959;ttl=480;expires=1793320439`, `guard_layers` all `ok`, `ports: {"22": 11724}` (no 8000/8080, as `vastai create` did not map them). |
| Watchdog | Listed `running` at expires -27 s, gone at +4 s. Pass. |

### Group

| Check | Result |
|---|---|
| `reserve g0 --group grp` | Instance 58327540, `l-b7020ec5`, $0.07/hr, 26 s to running. |
| `reserve g1 --group grp` | Instance 58327595, `l-577c8702`, $0.06/hr, 60 s to running. |
| `status --group grp` | Both listed, `live: 2`, `burn_per_hr: 0.13`. Pass. |
| `extend --group grp --to 12m` | `results` with two entries, each `ok: true`, `error: null`, both `expires_at: 00:47:47Z`. Pass. Labels then read `ttl=900;expires=1793321267`, so `expires=` tracks the extend while `ttl=` keeps the original value. |
| `VASTY_OWNER=other release --all` | `results: []`, exit 0. Both boxes still listed on Vast. Pass. |
| `release --group grp` | Two summaries, `ok: true`, `uptime_s` 78 and 109, `cost: 0.0`, `destroy_pending: true`. Instances `[]` after. Pass. |

No `budget_exceeded` during the phase.

Nigel gave the go for phase 5 at 00:42:27Z.
## Phase 5: serve. Cap $2.00. FAIL (dependency pin).

Instance 58328062, lease `l-c38505e0`, $0.08/hr, Korean host. `reserve --name sv --vram 12 --ttl 45m --disk 40` 00:42:28Z to 00:43:05Z. Ready check passed at once. `df -h /workspace`: 40G overlay, 1.5M used. `ports` had 8000 mapped (10872).

`vasty serve --on sv --model Qwen/Qwen2.5-0.5B-Instruct` started 00:43:24Z and returned at 00:46:29Z, exit 2:

```json
{"error": "serve_failed", "message": "vLLM exited 1 before /v1/models answered.",
 "hint": "Read the log: vasty ssh l-c38505e0 -- tail -n 100 /workspace/.vasty/jobs/j-1/log",
 "details": {"exit": 1}}
```

`details.output` was absent. The venv install itself finished in about 2 minutes: 6.8 GB under `/workspace/.vasty/venv`. The job ran 8 s. Log (`docs/live/p5-05-serve-log.txt`):

```
[transformers] Disabling PyTorch because PyTorch >= 2.6 is required but found 2.4.0
...
  File ".../vllm/config.py", line 1764, in _get_and_verify_max_len
    assert "factor" in rope_scaling
AssertionError
```

Installed versions: vllm 0.6.3, torch 2.4.0, transformers 5.22.0, tokenizers 0.23.3. `pip install vllm==0.6.3` pulls an unpinned transformers, and transformers 5.x refuses torch 2.4 and rewrites Qwen2.5's `rope_scaling` into a form without `factor`. The retry (`j-2`) failed the same way in 8 s. The model itself never downloaded. Filed as `issues/serve-vllm-063-transformers-pin.md`.

The curl checks were not reachable. `release sv`: `uptime_s: 313`, `cost: 0.02`, two jobs each `exit: 1`.

Redaction: the vLLM arg dump in the job log carried the serve `api_key`. It was redacted by value in three saved files. `grep -rE "vasty-[0-9a-f]{64}" out/` returns nothing.

## Phase 6: teardown. PASS.

`vasty release --all --everyone --yes` returned `results: []` (sv was already released). `vasty status`: `leases: []`, `spent_today: 0.07`, `spend_source: billing`. `vastai show instances --raw`: `[]`. Final credit 19.90616859492, balance 0.

## Summary

| Phase | Result | Balance drop |
|---|---|---|
| Setup | pass | 0 |
| 1 lifecycle | pass | $0.014 |
| 2 clock (2a, 2b, 2c, 2d) | pass | $0.033 |
| 3 run and sync | pass | $0.017 |
| 4 owners, groups, orphans | pass | $0.015 |
| 5 serve | fail, dependency pin | $0.014 |
| 6 teardown | pass | 0 |
| Total | | $0.094 of the $5.50 ceiling |

Twelve instances created, all gone. Nine hosts' bandwidth rates ranged $0.0026 to $0.0088 per GB. The open-question answers:

| Question | Answer |
|---|---|
| `CONTAINER_API_KEY` present in the container | set, with `CONTAINER_ID` |
| Container key can read its own instance row | HTTP 200 |
| `ports` absent until running | yes, null at 1 s, 11 s, 22 s, 33 s (`loading`), present at 44 s with `running` |
| `/charges` clip and lag | with no charge rows yet, `spent_today` estimated 1.5 against a $0.013 real drop and `spend_source` went `mixed`; after the UTC rollover and the first charge rows it tracked the ledger (0.07 against 0.094 at the end) |
| Container key `DELETE` destroys a running box | yes, three times: +16 s, +31 s, +4 s after the clock. The sweep from the laptop handled the fourth within a second of the call. |

Boot times to `running`: 54 s, 4m13s, 1m58s, 26 s, 2m50s, 76 s, 26 s, 60 s, 37 s. The three auto-reserved `run` boxes each completed in under a minute end to end.

Observations for follow-up, none filed as bugs:

- `status` with no selector hides expired leases; by name they show as `expired`.
- `status` list rows omit `log_tail`; a single-lease query includes it.
- `/workspace/.vasty/guard` is an empty file.
- `tag` on a box created with `vastai create --ssh` prints `SSH key already associated with instance` on stderr and still returns exit 0 with `guard: full`.
- After a bulk `extend --to`, the label's `ttl=` keeps its original value while `expires=` moves.
- `serve_failed` carries only `details.exit`; the plan expected `details.output`.
