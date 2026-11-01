# Live test report 3: an agent swarm on vasty

Run of `docs/live-test-plan-3.md`, 2026-10-31, 22:31 to 23:40 UTC, from `/private/tmp/vasty-live3`. The run record is copied to `docs/live/run3/`. Evidence paths below are relative to that directory, which mirrors `/private/tmp/vasty-live3/out`.

Lead: an Opus subagent. The plan names a Fable lead. Workers: Opus, `general-purpose`, run in the background, briefed with the plan's section 4 preamble and task blocks.

Nigel was away for the whole run. The lead gave the go, made Nigel's in-run decisions and ran the phase 5 comeback reads. Each is listed under Deviations.

## Outcome

| Phase | Result |
|---|---|
| Setup | PASS on every step |
| 1 Shared box, two workers | PASS. The first `hub` reserve failed with `provider_error` and destroyed its own box; the retry passed |
| 2 Job that outlives its lease | Neither branch. w3 tried `extend`, the Claude Code permission classifier blocked it, and w3 stopped without starting the job. The box expired on its clock |
| 3 One endpoint, two consumers | PASS except interleaving. The two workers' requests ran one after the other. The endpoint answered for 28 s after `release` |
| 4 Abandoned worker | NOT RUN. w4 declined to create a box because the 25-minute task cannot finish under the 20-minute cap |
| 5 Comeback | PASS. Account empty, per-lease costs match the ledger, no vasty process after teardown |

Balance drop: $0.2087 at the comeback read, start credit 19.25965994938 (`ledger.md`, `ledger-raw.tsv`). Final drop after teardown: $0.2087. Instances created: 4 of 7 allowed. Every clock stayed at 30 minutes or less.

## Prior attempt

Attempt 1 ran the same plan earlier today; its record is in `/private/tmp/vasty-live3-attempt1`. Its lead stopped writing at 21:57 UTC right after phase 2's `reserve --name long` returned. w3 was never spawned. `long` (`l-0b4e735f`) expired on its clock at 22:08 with no job on it, and the overseer released `hub` (`l-fb926b1b`) at 22:29.

Attempt 1's phase 1 findings:

- The first `hub` failed the ready check. The plan's hook calls `python`, which the base image does not have (startup exited 127). Torch cu126 on a 12.2 host raised Error 804. The lead released it ($0.04) and re-reserved with `python3` and `cuda = 12.6` in the worker profile.
- Both workers found `vasty` off PATH and `VAST_API_KEY` unset and fixed it themselves from the lead's scripts.
- Both hit `sync_failed` (rsync exit 11) pushing to a nested destination.
- One `status hub --json` read returned `state: unreachable` with `box_unreachable` and fix `vasty release l-fb926b1b`. The read 30 s later was `running`.
- The lead extended `hub` by 30m after phase 1 so it would survive to phase 3.
- w1 got 27.61 TFLOPS; w2 reported exit 3 with the ValueError; both reused `hub` with `run --on`.

This run repeated each of those findings except the first, which the config change avoided.

## Setup

| Step | Result | Evidence |
|---|---|---|
| 0 empty account, start credit | PASS. `[]`, credit 19.25965994938. No vasty process | `lead/s0-instances.json`, `lead/s0-user.json` |
| 1 no `VASTY_*`, no user config | PASS | `lead/s1-env.txt` |
| 2 offer pool | PASS. 25 offers, 23 with CUDA 13 | `lead/s2-offers*.json` |
| 3 config and fixtures | Copied from attempt 1. Fixtures match the plan. Worker profile deviates: `python3` and `cuda = 12.6` | `vasty.toml` |
| 4 `config show` sources | PASS | `lead/s4-config-show*.json` |
| 6 `status` on empty account | PASS. `leases: []`, credit 19.26, no warnings | `lead/s6-status.json` |
| 7 ledger loop | Started; ran for the whole run | `ledger-raw.tsv` |

## Phase 1: shared box, two workers

First reserve, 22:31:53 to 22:39:44, exit 2 (`lead/p1-01-reserve.*`):

```
{"error": "provider_error", "message": "Vast list instances failed: ReadTimeout: HTTPSConnectionPool(host='console.vast.ai', port=443): Read timed out. (read timeout=120).", "hint": "Check the network and retry.", "details": {"action": "list instances"}}
```

- The box (`l-49819444`, instance 58585599, Poland) had reached SSH at 22:35:29 and was installing torch. The reserve destroyed it and exited.
- The error object names no lease and does not say the box was destroyed. `status --all` listed nothing. The lead found the id from the instance label in its own watch loop. `status l-49819444` then showed `state: released`, `cost: 0.04`, `uptime_s: 315` (`lead/p1-03-status-hub.json`).
- The Vast API was slow from 22:35 to 22:40; the lead's watch loop got no rows in that window. At 22:40 list calls took 0.6 s.

Second reserve, same command, 22:40:36 to 22:46:16, exit 0, no warnings (`lead/p1-05-reserve.json`). `l-98280219`, instance 58586205, New Jersey, $0.1426/hr.

- Setup's offer pool held 3060s at $0.05 to $0.07. vasty took one at 95% of `max_price`.
- Ready check passed; torch 2.14.1+cu126 on the GPU (`lead/p1-06-ready.out`, `lead/p1-07-torch.out`).

| Check | Result | Evidence |
|---|---|---|
| w1 returns TFLOPS and `w1/bench.json` exists | PASS. 27.12 TFLOPS | `w1/bench.json`, `w1/04-run.*` |
| w2 reports exit 3 and quotes the ValueError | PASS | `w2/04-run.*`, `w2/report.md` |
| `hub` running after both, jobs with exits 0 and 3 | PASS. j-1 exit 0, j-2 exit 3, `busy: false` | `lead/p1-09-status-hub.json` |
| instances created beyond hub | 0 by workers | `lead/instance-watch.tsv`, `lead/p1-10-status-all.json` |

Both workers finished in about 90 s, before the lead regained control, so the lead's 60-second group samples were never taken.

## Phase 2: a job that outlives its lease

- `reserve --name long --profile worker --ttl 12m` 22:49:30 to 22:53:01, exit 0 (`lead/p2-01-reserve.json`). `l-7d5a7a62`, South Korea, $0.0844/hr. It returned `ttl_remaining_s: 541`: the torch install had used 3 of the 12 minutes. It warned `idle_box_available` for hub.
- w3's first command, `status l-7d5a7a62 --json --verbose`, returned `state: unreachable`, warning `box_unreachable` "no answer for 49s", fix `vasty release l-7d5a7a62` (`w3/01-status.out`). w3's ssh probe 1 to 2 s later worked (`w3/02-ssh.out`).
- w3 then ran `vasty extend l-7d5a7a62 --by 15m`. The Claude Code auto-mode classifier blocked it as "Modify Shared Resources" because the box belongs to `lead` (`w3/00-notes.txt`). w3 stopped, started no job, and asked the lead to run the extend and re-dispatch it.
- The lead did neither. The plan bars a lead extend in phase 2, and running an action the permission system denied a worker would route around that denial.
- The lead's samples (`lead/p2-sample-01..08.json`) show `running`, `busy: false`, `expiring_soon` from 22:57:37 with fix `vasty extend l-7d5a7a62 --by 30m`, then `expired` from 23:02:06.
- The instance was last listed at 23:01:46 and gone by 23:02:07; expiry was 23:02:02. The cache shows `released_here: false` and `destroy_attempts: 0`, and no sample's `swept` names it, so the watchdog or the follower destroyed it. `status long --verbose`: `expired`, `jobs: []`, `cost: 0.04`, later 0.05 (`lead/p2-03-status-long.json`, `lead/p5-03-status-l-7d5a7a62.json`).

| Branch | Result |
|---|---|
| Extended | Did not happen; the harness blocked the extend |
| Lost | Did not happen; no job ran |
| Clock | Held, within 5 s of `expires_at` |

## Phase 3: one endpoint, two consumers

- `serve --profile vllm --model Qwen/Qwen2.5-0.5B-Instruct --name llm --group swarm --ttl 30m` 23:03:52 to 23:12:57, exit 0 (`lead/p3-01-serve.json`, key redacted). `l-3246e2a0`, Norway, $0.1044/hr. Image pull 23:06:36 to 23:11:27; vLLM routes up 23:12:50.
- Without key: 401. With key: the model list (`lead/p3-02*.out`, `lead/p3-03*.out`). PASS.
- `status --group swarm` listed `llm` and `hub` (`lead/p3-04-status-group.json`). PASS.
- `extend --group swarm --to 20m`: two results, `ok: true`, both `expires_at` 23:33:17 (`lead/p3-05-extend-group.json`). PASS.
- The classifier denied the lead a command that printed the serve key. The lead wrote the key to `/private/tmp/vasty-live3/llm.key` (mode 600) unseen and the briefs named that file in place of the key.

| Check | Result | Evidence |
|---|---|---|
| Both `summaries.jsonl` have 12 lines | PASS | `w5/summaries.jsonl`, `w6/summaries.jsonl` |
| Requests interleaved | FAIL. Two blocks of 12 by client port; w6 done about 23:14:10, w5 about 23:14:28 | `lead/p3-08-vllm-posts.out` |
| First to last under 1 minute | PASS | `lead/p3-07-vllm-log.out` |
| No key in reports | PASS. The only hit was the lead's serve capture, redacted | |
| `release --group` returns one summary per lease with `cost` | PASS. `llm` 0.03, `hub` 0.09, both `destroy_pending: true` | `lead/p3-09-release-group.json` |
| curl fails after release | FAIL then PASS. 401 at 23:15:31, 23:15:38 and 23:15:48; connection refused at 23:15:59 | `lead/p3-10-curl-after.out`, `lead/p3-12-curl-retry.out` |
| `vastai show instances` lists nothing from the group | PASS. `[]` right after release | `lead/p3-11-instances.json` |

## Phase 4: the abandoned worker

w4 ran `vasty config show --json` and nothing else (`w4/01-config.*`). It saw the 20-minute cap and `ttl`/`run_ttl` 20m and decided a 25-minute burn could not finish. It created no box. No w4 lease ever showed `busy: true`, so there was nothing to stop and nothing to watch.

w4 reported that `config show --json` writes the API key to stdout. It does not: the output has `"api_key_env": {"value": "VAST_API_KEY", ...}`, and the key occurs 0 times in the file. The field misled the worker.

The lead did not create an abandoned box of its own; that is a create outside the plan, which the plan reserves for Nigel. The DELETE canary with a live job remains untested in this plan. Phase 2's `long` shows the clock acting with no sweep destroy, but with followers running on the laptop and no job on the box.

## Phase 5: comeback

Lead-run (deviation). At 23:18 (`lead/p5-*`):

- `vastai show instances --raw`: `[]`.
- Leases from this run in `status`:

| Lease | Name | State | cost | Jobs |
|---|---|---|---|---|
| l-49819444 | hub (first) | released | 0.04 | none |
| l-98280219 | hub | released | 0.09 | j-1 exit 0, j-2 exit 3 |
| l-7d5a7a62 | long | expired | 0.05 | none |
| l-3246e2a0 | llm | released | 0.03 | j-1 vllm `exit: null`, `state: unknown` |

- Sum of `cost` 0.21 against a ledger drop of 0.2087 at the same time. Within $0.05. PASS.
- `ps aux | grep '[v]asty'`: four `vasty sweep --follow` processes, two for `l-98280219` and two for `l-3246e2a0`, both released 3 minutes earlier (`lead/p5-05-ps.txt`). The plan's "no process remains" check: FAIL at 23:18, PASS by 23:20:37.
- `uv run pytest`: 1246 passed, 1 skipped. `uv run mypy`: no issues in 34 files (`lead/p5-06-pytest.txt`, `lead/p5-07-mypy.txt`).

Teardown, 23:20:
- The four followers exited on their own between 23:20:22 and 23:20:37, about 5 minutes after the release and 13 minutes before the leases' old expiry.
- `vasty release --all --everyone --yes --json`: `results: []`, exit 0 (`lead/p5-08-release-all.json`).
- `vastai show instances --raw`: `[]` (`lead/p5-09-instances.json`).
- Ledger and watch loops stopped. `ps aux | grep '[v]asty'` empty afterwards.
- Redaction: the serve key in `lead/p3-01-serve.json` was replaced with `<redacted>`. The Vast key and `CONTAINER_API_KEY=` had no hits in `out/`. `llm.key` stays outside `out/` and was not copied.

## Worker scorecards

w1, bench (`w1/01..06-*.cmd`)

| Rule | Result |
|---|---|
| `status` before any create | yes (`status l-98280219 --verbose`); created nothing |
| reuse with `--on` | yes |
| id or name | id; set `VASTY_OWNER=w1` |
| JSON mode | `--json` on every command |
| job sized against the clock | read 1617 s left before a 3 s job |
| warnings acted on | none raised |
| cleanup | hub left up |
| honest report | exit 0 as returned; no cost since nothing released; no key |

w2, check (`w2/01..06-*.cmd`)

| Rule | Result |
|---|---|
| `status` before any create | yes (`status --all --everyone`); created nothing |
| reuse with `--on` | yes |
| id or name | id; set `VASTY_OWNER=w2` |
| JSON mode | `--json` on every command |
| job sized against the clock | read 1603 s left |
| warnings acted on | none raised |
| cleanup | hub left up; files left in `/workspace/w2` |
| honest report | exit 3 and the ValueError; no key |

w3, burn (`w3/01..02-*.cmd`, `w3/00-notes.txt`)

| Rule | Result |
|---|---|
| `status` before any create | yes; created nothing |
| reuse with `--on` | not reached |
| id or name | id; kept owner `lead` from config |
| JSON mode | yes on status |
| job sized against the clock | yes. Read 475 s left for a 15-minute job and tried `extend --by 15m` |
| warnings acted on | did not run the `box_unreachable` fix `vasty release`; probed with ssh |
| cleanup | `long` left as found |
| honest report | reported the blocked extend and no job; no key |

w4, solo (`w4/01-config.*`, `w4/DECISION.txt`)

| Rule | Result |
|---|---|
| `status` before any create | no `status`; ran `config show` and created nothing |
| others | not reached |
| honest report | accurate on what it did; wrong that `config show` leaks the key |

w5 and w6, summarize (`w5/`, `w6/`)

| Rule | w5 | w6 |
|---|---|---|
| vasty commands | one `status l-3246e2a0`, failed exit 127 then `auth_missing`; w5 chose not to find the key | none |
| `.cmd` records | yes | no; saved `summarize.*` and `notes.txt` |
| task | 12 summaries | 12 summaries |
| key in report | no | no |

Every worker found `vasty` off PATH. Every worker that needed the Vast key found it unset. w1, w2 and w3 loaded it from `~/.config/vastai/vast_api_key` by copying the lead's scripts; w5 declined to.

## Boot and install times

| Box | Create to Vast `running` | Hook (torch) | Command wall time |
|---|---|---|---|
| hub 1, Poland | 2 min 56 s | killed at about 4 min by the failed reserve | 7 min 51 s, exit 2 |
| hub 2, New Jersey | 3 min 47 s | 117 s | reserve 5 min 40 s |
| long, South Korea | 0 min 34 s | 174 s | reserve 3 min 31 s |
| llm, Norway, vLLM image | 7 min 15 s (pull 4 min 51 s) | none | serve 9 min 5 s |

## Ledger

| UTC | Credit | Drop | Note |
|---|---|---|---|
| 22:31:09 | 19.25966 | 0 | start |
| 22:48:47 | 19.19205 | 0.0676 | end of phase 1; two hub boxes, two torch downloads |
| 23:03:09 | 19.11405 | 0.1456 | end of phase 2 |
| 23:15:27 | 19.05605 | 0.2036 | phase 3 release |
| 23:18:31 | 19.05093 | 0.2087 | comeback read |

Final credit after teardown at 23:20:57: 19.05092903711. Final drop: $0.2087, under the $5.00 stop. Every phase stayed under its cap: phase 1 $0.068 of $1.00, phase 2 $0.078 of $0.50, phase 3 $0.058 of $1.50, phase 4 $0 of $0.50.

## Deviations

- Opus lead in place of Fable. The lead gave the go and ran the comeback reads; Nigel was away.
- Worker profile uses `python3` and `cuda = 12.6`; the plan's ready-check torch line uses `python3`.
- The lead extended `hub` with `--to 30m` at 23:03:50 so it would live until phase 3's group commands.
- The serve key went to workers as a file path, because the classifier blocked the lead from reading it.
- The planned 60-second samples in phase 1 and the vLLM log read at 60 s in phase 3 came late or not at all; the workers finished first.
- No re-dispatch of w3 after its blocked extend, and no lead-created box for phase 4.

## Hiccups, surprises and confusing output

Each item names the command that exposed it.

1. `vasty reserve --name hub ... --json` returned `provider_error` on a Vast list timeout after creating a box, then destroyed the box. The error carries no lease id and does not say a box was created and destroyed (`lead/p1-01-reserve.json`).
2. After (1), `vasty status --all --json` listed nothing; the lease shows only when named (`lead/p1-02-status.json`, `lead/p1-03-status-hub.json`).
3. `vasty status l-7d5a7a62 --json --verbose` (w3) returned `unreachable` with `box_unreachable` and fix `vasty release l-7d5a7a62` on a box that answered ssh a second later. Attempt 1 saw the same on hub. An agent that runs fixes as given would destroy a healthy box it does not own.
4. `vasty sync l-98280219 push fx/bench/ /workspace/w1/bench/` (w1) and `... /workspace/w2/check/` (w2) failed with `sync_failed`, rsync exit 11, because the parent directory did not exist. The hint is "Check the rsync output on stderr, then retry." Same in attempt 1.
5. `vasty reserve` on hub picked a $0.1426/hr offer while $0.05 to $0.07 offers were in the pool (`lead/p1-05-reserve.json`, `lead/s2-offers.json`).
6. `vasty reserve --name long --ttl 12m` returned with 541 s left. The torch install ran on the clock, so `--ttl` is not the time the caller gets (`lead/p2-01-reserve.json`).
7. `status` job entries use `id`; attached `run` returns `job` (`lead/p1-09-status-hub.json`, `w1/04-run.out`).
8. Attached `run` JSON includes `error: null`; `serve` JSON includes `model`. Neither is in the README's result table.
9. Bulk `release --group` results carry `name`, `uptime_s`, `cost`, `jobs` and `destroy_pending`; the README lists only `lease`, `ok`, `error` (`lead/p3-09-release-group.json`).
10. `vasty release --group swarm` returned with the instances gone from `vastai show instances`, and the endpoint kept answering 401 for 28 s (`lead/p3-12-curl-retry.out`).
11. Released leases show nonzero `ttl_remaining_s` (920 for hub and llm) and `verbose.actual_status: "running"` (`lead/p5-02-status.json`, `lead/p1-03-status-hub.json`).
12. Old serve jobs in history show `state: unknown` with `duration_s` that keeps growing (52736 s for `l-2787ec15`) (`lead/p5-02-status.json`).
13. `vasty status --verbose --json` with no target lists 15 history leases across all owners and earlier runs. `vasty status --all --json` lists none. The README says history shows only when named (`lead/p5-02-status.json`).
14. A lease's `cost` grew after it ended: `long` read 0.04 at expiry and 0.05 later. `uptime_s` on released leases also moved (llm 261 then 270).
15. Each `extend` spawned a new `sweep --follow`, so two followers ran per lease. They kept running for about 5 minutes after `release` and then exited (`lead/p5-05-ps.txt`).
16. `vasty config show --json` (w4) prints `api_key_env` with value `VAST_API_KEY`. w4 read it as the key and reported a leak.
17. `vasty --version` returns `invalid_arguments`.
18. `verbose.reachable_at` moves with later probes; w1 read 22:47:20 after the reserve returned at 22:46:16 (`w1/01-status.out`).
19. The plan's worker profile calls `python`, which the base image lacks, and the default image has no CUDA floor (attempt 1).

## Driving vasty as an agent

- The JSON is easy to act on. Workers used `--json` everywhere without being told, read `ttl_remaining_s` before running, and reused `hub` with `run --on`. w1 and w2 each needed six commands.
- The README's "For agents" section got followed closely. Four of six workers ran a `status` first. w1 and w2 set their own `VASTY_OWNER` and switched to lease ids because names resolve per owner.
- The `box_unreachable` fix is the one place where following the README's "loop over the warnings and run the fixes" would do damage. w3 did not run it; it probed with ssh instead.
- `expiring_soon` suggests `extend --by 30m`, longer than the 20-minute limit these workers worked under.
- A shared project `vasty.toml` that sets `owner` makes every worker the lead unless it sets `VASTY_OWNER`. w1, w2, w4 and w5 all noted this; w3 kept `lead`.
- Shared boxes have no per-job scratch space. Both fixtures write to `/workspace/out/`, and w1 and w2 each worked around it unprompted.
- Clock budgeting is hard to see. `long`'s 12 minutes became 9 after install, and the brief's 15-minute job could never fit. w4 refused its task on the same arithmetic.
- The permission layer between the agent and vasty mattered more than vasty did in phases 2 and 3. An extend on another owner's box and a read of the serve key were both blocked.

## Proposed changes to vasty

- Put `lease`, `instance_id` and whether the box was destroyed in the `provider_error` that `reserve` returns after it has created a box. (`vasty reserve --name hub --group swarm --profile worker --ttl 30m --json`, `lead/p1-01-reserve.json`)
- Retry a timed-out list call during `reserve`'s wait before destroying the box, or keep the box and return `pending` with the lease. (same command)
- Change the `box_unreachable` fix from `vasty release` to a re-read such as `vasty status LEASE`, and raise the warning only after more than one failed probe. (w3 `vasty status l-7d5a7a62 --json --verbose`; attempt 1 `status hub --json`)
- Have `sync push` create the destination's parent directories, or name `mkdir -p` in the `sync_failed` hint. (w1 `vasty sync l-98280219 push fx/bench/ /workspace/w1/bench/`)
- Prefer the cheaper offers among those that match, or document the offer order. (`vasty reserve --name hub ...`, $0.1426/hr against a $0.05 to $0.07 pool)
- Start the clock when the startup hook exits, or report the hook's time in the `reserve` result so a caller sees why `ttl_remaining_s` is short. (`vasty reserve --name long --profile worker --ttl 12m --json`)
- Use one key for job ids: `job` in `run`, `id` in `status` and `release`. (`lead/p1-09-status-hub.json`, `w1/04-run.out`)
- Add `error` to attached `run`, `model` to `serve` and the per-lease summary fields to bulk `release` in the README's result table. (`w1/04-run.out`, `lead/p3-01-serve.json`, `lead/p3-09-release-group.json`)
- Wait until the endpoint stops answering, or say so in the `release` result, when releasing a serve box. (`vasty release --group swarm --json`, then `curl URL/models`)
- Set `ttl_remaining_s` to 0 or null and drop `actual_status` on released and expired leases. (`vasty status --verbose --json`)
- Freeze `duration_s` and resolve `state: unknown` for jobs on leases in history. (`vasty status --verbose --json`, `l-2787ec15`)
- Make `status --verbose` with no target follow the same selection as `status`, or document that it lists history for every owner. (`vasty status --verbose --json` against `vasty status --all --json`)
- Spawn one follower per lease, and have `release` stop that lease's follower. (`vasty extend hub --to 30m`, then `vasty extend --group swarm --to 20m`; `ps aux | grep '[v]asty'` at 23:18)
- Rename `api_key_env` in `config show` output to something that does not read as the key, or add a `source`-style note. (w4 `vasty config show --json`)
- Add `vasty --version`. (`vasty --version`)
- Match `expiring_soon`'s fix to the remaining job time or the lease's original ttl in place of a fixed `--by 30m`. (`vasty status long --json`, `lead/p2-sample-03.json`)
- Fix the plan's worker profile to `python3` and add a CUDA floor, or have vasty default the base image's floor to 12.6. (attempt 1 `p1-03-startuplog.out`, `p1-05-torch3.out`)
