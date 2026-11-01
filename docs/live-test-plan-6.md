# Live run 6: the fixes from runs 2 to 5

PR #4 closed issues 001 to 015 against fakes. This run puts each fix on a real box. Items that need no box run in phase 0 with no spend. The create-failure fix (#006) has no deterministic trigger on Vast; the run records any create failure it meets and otherwise leaves #006 to the unit tests.

## Coverage

| Issue | Fix under test | Phase |
|---|---|---|
| 001 | help text, `--version` | 0 |
| 002 | image CUDA floor, `vllm_missing` hint | 0, 4 |
| 003 | one job entry shape, frozen `duration_s`, `run` and `status` agree | 1, 2 |
| 004 | `vasty stop` | 1, 4 |
| 005 | `box_unreachable` and `expiring_*` fixes, rounding up | 1 |
| 006 | create and wait failures | opportunistic |
| 007 | null clock while pending, null `ttl_remaining_s` in history, `log_tail` in every state | 1 |
| 008 | `status --everyone`, history scope, `lease_not_found` matches, `swept.owner` | 0, 3 |
| 009 | `sync push` creates the parent | 1 |
| 010 | one follower per lease, shortened clock holds, `release` stops the follower | 1, 2 |
| 011 | `previous_expires_at`, label `ttl` unchanged | 1 |
| 012 | JSON money to four places | 0, 2 |
| 013 | API key from the vastai file | setup, every phase |
| 014 | `serve_failed` hint for error 804 | 4 |
| 015 | README follows the code | 5 |
| review | `run --on` expiry line rounds up | 1 |

## Roles

- **Manager**: sets up, runs phases 0 to 4 by hand, drives phase 5, watches the balance and `vastai show instances --raw`, writes the report. The manager creates instances only where this plan says so and within the caps.
- **Driver**: one fresh agent for phase 5, with `VASTY_OWNER=agent-a`. It receives its task line, the README section "For agents", and the output of `vasty --help` and `vasty VERB --help` for every verb. It writes expectations and surprises to `notes.md`, asks nothing, and gets 40 minutes.

## Setup

Root `/private/tmp/vasty-live-6`, repo venv on PATH. Before anything else, check for a run in flight: `vastai show instances --raw` returns `[]`, `pgrep -af "vasty sweep --follow"` prints nothing, and no `/private/tmp/vasty-live*` directory has files newer than 15 minutes. Destroy anything listed with `vastai destroy instance ID -y` and record the ids.

1. `VAST_API_KEY` is unset in every shell of this run. `~/.config/vastai/vast_api_key` holds the key. Every networked command in this run exercises #013.
2. Record the starting credit from `vastai show user --raw` in `out/ledger.md`.
3. `~/.ssh/id_ed25519` present. `env | grep '^VASTY_'` prints only `VASTY_OWNER`. `~/.config/vasty/config.toml` is absent.
4. Offer pool: `vastai search offers 'gpu_name=RTX_3060 num_gpus=1 verified=true rentable=true disk_space>=16' -o 'reliability-' --raw`. Record `id`, `dph_total`, `reliability`, `cuda_max_good` and `direct_port_count` for the top 10. Set `max_price` to the highest `dph_total` among the top 5, as a three-decimal value such as 0.272. Note how many of the top 10 run CUDA 12.x; phase 4 step 3 needs one.
5. Same query for `RTX_5060_Ti`. Record the cheapest `dph_total` and its `cuda_max_good`.
6. Write `vasty.toml`:

```toml
[defaults]
ttl = "15m"
run_ttl = "15m"
gpu = "3060"
max_price = 0.272         # from step 4, three decimals
warn_before_expiry = "5m"
disk = 16
image = "vastai/base-image:cuda-12.6.3-auto"

[profiles.vllm]
image = "vllm/vllm-openai:v0.32.0"
gpu = "5060 Ti"
max_price = 0.40          # from step 5
ttl = "20m"
```

The manager's shell sets `VASTY_OWNER=run6`.

7. Fixtures in `fx/`:
   - `hello.py`: print the hostname and `nvidia-smi -L`.
   - `short.py`: print the hostname, sleep 20 s, exit 3.
   - `sleeper.py`: sleep 900 s, exit 0.
   - `stubborn.py`: ignore TERM, sleep 900 s, exit 0.
   - `data.txt`: one known line.

Every vasty command runs with `--json` and saves to `out/<phase>/NN-<verb>.json`, stderr beside it. Read the credit before each create and every 60 s while any instance exists.

## Phase 0: local checks. No spend.

1. `vasty --version` prints the version from `pyproject.toml`, exit 0.
2. `vasty VERB --help` for every verb. Pass: every flag has a help line; `--ttl`, `--cuda`, `--max-price`, `--image` and `--by` name a unit and a default; `ssh --help` shows `-- COMMAND`; `sync --help` shows `push|pull SRC DEST` and `--delete`; `stop` appears in `vasty --help`. Save the output as `out/0/help.txt`; phase 5 hands it to the driver.
3. `vasty config show`. Pass: `api_key` source is the vastai file, `cuda` is 12.6 with source `image`, `max_price` is 0.272 in JSON and `$0.27` in the table.
4. `vasty config show --profile vllm`. Pass: `cuda` 13 with source `image`; `image`, `gpu`, `max_price` and `ttl` from the profile.
5. `vasty config show --cuda 12.4`. Pass: `cuda` 12.4 with source `flag`.
6. `HOME=$(mktemp -d) vasty status`. Pass: `auth_missing`, message naming `VAST_API_KEY` and the file path, exit 1.
7. `vasty status --everyone` on the empty account. Pass: exit 0, `leases: []`.
8. `vasty release --everyone`. Pass: `invalid_arguments`, exit 1. Same for `vasty extend --everyone --by 5m`.
9. `vasty completion bash | grep -c stop` prints at least 1.
10. `vasty status`. Pass: `leases: []`, `totals.credit` matches `vastai show user --raw` to four places.

Stop the run if step 3 or 10 fails.

## Phase 1: one box, the lifecycle fixes. Cap $0.40.

```
vasty reserve --name p1 --no-wait                                  # 01
vasty status p1                                                    # 02, at once
vasty status p1                                                    # 03, every 30 s until running
pgrep -af "vasty sweep --follow"                                   # 04
vasty extend p1 --by 5m                                            # 05
pgrep -af "vasty sweep --follow"                                   # 06
vastai show instances --raw                                        # 07, read the label
vasty sync p1 push fx/ /workspace/a/b/c/                           # 08
vasty ssh p1 -- ls /workspace/a/b/c                                # 09
vasty sync p1 pull /workspace/a/b/c/data.txt out/1/pulled.txt      # 10
vasty run --on p1 --detach -- python3 /workspace/a/b/c/sleeper.py  # 11
vasty run --on p1 --detach -- python3 /workspace/a/b/c/stubborn.py # 12
vasty status p1                                                    # 13
vasty stop p1                                                      # 14
vasty stop p1 JOB_OF_11                                            # 15
vasty status p1                                                    # 16
vasty stop p1                                                      # 17, stubborn is the only live job
vasty status p1                                                    # 18
vasty ssh p1 -- 'rm -f /etc/cron.d/vasty; pkill -f "[w]atchdog.sh"; sleep 2; rm -f /workspace/.vasty/alive; pgrep -f "[w]atchdog.sh" || echo watchdog_dead'   # 19
vasty extend p1 --to 4m                                            # 20
vasty run --on p1 -- python3 /workspace/a/b/c/hello.py             # 21, within 60 s of 20
```

After 21 run no networked vasty command until p1 leaves `vastai show instances --raw`. Poll `vastai show instances --raw` every 15 s. Then:

```
vasty status p1 --verbose                                          # 22
vasty status p1 --verbose                                          # 23, 60 s later
pgrep -af "vasty sweep --follow"                                   # 24
```

Pass:

- 01 and 02: `expires_at` and `ttl_remaining_s` null, `state: pending`, 02 carries a `log_tail` key (#007).
- 04: one follower for p1. 06: still one, same pid (#010).
- 05: `previous_expires_at` equals 03's `expires_at`; `expires_at` is 300 s later (#011). 07: the label's `ttl` is `15m`.
- 08: exit 0 with no rsync error 11. 09 lists the fixtures. 10: `pulled.txt` matches `fx/data.txt` (#009).
- 13: two job entries with keys `job`, `cmd`, `state`, `exit`, `duration_s` and no `id` key; `busy: true` (#003).
- 14: `invalid_arguments` listing both job ids. 15: `state: killed`, a non-null `exit`, `duration_s`. 16: the sleeper entry shows 15's `exit` and `duration_s`; stubborn still `running` (#004).
- 17: returns after about 10 s with `state: running`, exit code 2. 18: stubborn still `running`.
- 20 and 21: `expiring_with_running_job` with `fix: ["vasty", "extend", LEASE, "--by", "15m"]`; the message reads `4m left`, and 21's stderr line reads `expires in 4m`; both round the same way (#005, review row). The run exits 0 with hello's output on stderr.
- p1 leaves the provider between the new `expires_at` and that time plus 330 s, with no vasty command in flight and no watchdog on the box (#010).
- 22: `state` is `expired` or `gone`, `ttl_remaining_s` null, no `actual_status` key, a `log_tail` key, the stubborn job frozen with a `duration_s`. 23: the same `duration_s` (#003, #007).
- 24: no follower for p1.

If p1 is still listed 6 minutes past the new `expires_at`, run `vasty release p1`, record the follower's state from `ps`, and fail the step.

## Phase 2: release. Cap $0.30.

```
vasty reserve --name p2                                            # 01
vasty run --on p2 --sync fx -- python3 /workspace/short.py         # 02
vasty status p2                                                    # 03
vasty run --on p2 --detach -- python3 /workspace/sleeper.py        # 04
pgrep -af "vasty sweep --follow"                                   # 05, record the pid
vasty release p2                                                   # 06
pgrep -af "vasty sweep --follow"                                   # 07, 5 s later
vasty status p2 --verbose                                          # 08
vasty status p2 --verbose                                          # 09, 60 s later
vasty reserve --name p3                                            # 10
vastai destroy instance INSTANCE_ID -y                             # 11, from status p3 --verbose
vasty release p3                                                   # 12
vasty status                                                       # 13
```

Pass:

- 02 exits 3; its `duration_s` equals the `short.py` entry's `duration_s` in 03 (#003).
- 06: the sleeper entry has `state: killed`, `exit: null`; `cost` has up to four decimals and a non-zero value for a box up over a minute (#012). `already_absent` is absent or false.
- 07: 05's pid is gone (#010).
- 08 and 09: `state: released`, `ttl_remaining_s` null, no `actual_status`, the same `duration_s` on the sleeper entry.
- 12: `already_absent: true` with the summary fields. 13 lists no p3 and no orphan.

## Phase 3: owners. Cap $0.40.

Shells: `VASTY_OWNER=run6` for the manager, `VASTY_OWNER=agent-b` for B, `VASTY_OWNER=victim` for the victim. The manager runs each from the root directory.

```
VASTY_OWNER=run6    vasty reserve --name ft --no-wait                      # 01
VASTY_OWNER=agent-b vasty status ft                                        # 02
VASTY_OWNER=agent-b vasty status --everyone                                # 03
VASTY_OWNER=agent-b vasty status --verbose                                 # 04
VASTY_OWNER=agent-b vasty status --verbose --owner run6                    # 05
VASTY_OWNER=agent-b vasty status --verbose --everyone                      # 06
VASTY_OWNER=victim  vasty reserve --name victim --ttl 8m                   # 07
```

Box ready check on victim: `status victim` running with every guard layer ok. Then:

```
pkill -f "vasty sweep --follow"                                            # 08, kills ft's follower too
vasty ssh victim -- 'rm -f /etc/cron.d/vasty; pkill -f "[w]atchdog.sh"; sleep 2; rm -f /workspace/.vasty/alive; pgrep -f "[w]atchdog.sh" || echo watchdog_dead'   # 09
```

No networked vasty command from victim's `expires_at` minus 2 minutes until the gate. At `expires_at` plus 60 s, confirm `vastai show instances --raw` lists victim, then:

```
VASTY_OWNER=agent-b vasty status --everyone                                # 10
VASTY_OWNER=run6    vasty release ft                                       # 11
```

Pass:

- 02: `lease_not_found`, `details.matches` holds ft's lease id, hint names `vasty status l-...` (#008).
- 03: exit 0, lists ft under owner run6.
- 04: history empty for agent-b. 05: run6's p1, p2 and p3. 06: both owners' history. Active leases list every owner in all three (#008).
- 10: `swept` has one entry for victim with `owner: victim`, `ok: true`; victim is gone from the provider within 60 s (#008).
- 11: ft released, `destroy_pending` recorded. The account is empty.

If victim is still listed 3 minutes after 10, run `VASTY_OWNER=victim vasty release victim` and fail the step.

## Phase 4: the vLLM path. Cap $1.00.

```
vasty serve --on p4 --model Qwen/Qwen2.5-0.5B-Instruct --ttl 20m --name n  # 01, p4 is a fresh base box: reserve --name p4 first
vasty serve --profile vllm --model Qwen/Qwen2.5-0.5B-Instruct --name sv    # 02
vasty status sv --verbose                                                  # 03
curl against the endpoint in 02: GET /v1/models, then one chat completion  # 04
vasty stop sv                                                              # 05
vasty status sv                                                            # 06
vasty release sv                                                           # 07
vasty reserve --name old --image vllm/vllm-openai:v0.32.0 --cuda 12.4      # 08, 3060 pool, aiming at a 12.x host
vastai show instances --raw                                                # 09, read cuda_max_good
vasty serve --on old --model Qwen/Qwen2.5-0.5B-Instruct                    # 10
vasty release old                                                          # 11
vasty release p4                                                           # 12
```

Pass:

- 01: `vllm_missing`, hint `vasty reserve --profile vllm --ttl 20m --name n --cuda 13`, or the `--on` form of it; record the exact hint (#002).
- 02: the chosen host's `cuda_max_good` in 03 is 13 or higher; `serve` returns the endpoint and `model`. 04: the model lists and the chat answers.
- 05: the serving job returns `state: killed`. 06: `busy: false`, the job entry keeps 05's `exit` and `duration_s` (#004).
- 09: if `cuda_max_good` is 13 or higher, release `old`, record "no 12.x host", and skip 10. Otherwise 10: `serve_failed`, `log_tail` holds `Error 804`, hint names `--image vllm/vllm-openai:v0.32.0 --cuda 13` on a new box with the caller's `--model` (#014).
- Every clock in this phase is 20 minutes or shorter.

## Phase 5: a fresh agent with the help text. Cap $0.50.

One driver, `VASTY_OWNER=agent-a`, in `/private/tmp/vasty-live-6/a/` with a copy of `vasty.toml` and `fx/`. Task line: "Serve Qwen/Qwen2.5-0.5B-Instruct on a GPU box for twenty minutes, confirm it answers a chat request, stop the server, release the box."

Runs 2 to 4 saw every fresh agent guess `--cuda`, `--ttl` and the default image. The report answers:

- Which flags the driver read from `--help` and which it guessed. Count the `invalid_arguments` and `no_offers` results.
- Whether it reached `vllm_missing` or `serve_failed` and whether it ran the hint as given.
- Whether it used `stop` or fell back to `ssh` and `kill`.
- Whether `release` happened and what `jobs` showed.

The manager records `status --all --everyone --json` every 2 minutes into `out/5/manager/`. At 40 minutes the manager stops the driver and releases its leases.

## Opportunistic: #006

Any `reserve`, `run` or `serve` in this run that returns `provider_error` is saved in full. Record `details.lease`, `details.instance_id` and `details.destroyed`, then `vastai show instances --raw` within 10 s and again at 60 s. Any stderr line about a refresh error during a readiness wait is saved with the reserve that printed it. Pass for a rejected create: no instance carrying the lease label is listed at 60 s.

## Guardrails

- Cap for the run: $3.00 cumulative drop.
- Every clock runs 20 minutes or shorter.
- Followers stay alive except at phase 3 step 08.
- Stop the run when: the drop passes $3.00; an id in `vastai show instances --raw` matches no `instance_id` in `vasty status --all --everyone --verbose`, apart from victim between its expiry and phase 3 step 10 and p1 between phase 1 step 21 and its sweep; vasty prints a traceback; two consecutive creates return `no_offers` or `provider_error`.
- On any stop: stop the driver, create nothing more, release every lease under each owner, destroy any remaining instance by id, write the report.
- Redact `CONTAINER_API_KEY` and the Vast key by value in every saved file.

## Report

Append per phase to `out/report.md` as each ends, one line per numbered command with pass or fail and the file. Copy the reviewed output to `docs/live/run6/` and the report to `docs/live/run6/report.md`. File each defect under `issues/` with the command, the output and the issue it reopens. Delete this plan with the merge, as runs 3 to 5 did.
