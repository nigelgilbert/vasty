# Live run 4: warnings, jobs and pending boxes

Runs 1 and 2 checked each verb against a checklist. Run 3 puts a swarm of workers on shared boxes. This run provokes each `status` warning and runs its `fix`, checks job states on a real box, and hands a blind driver a `reserve --no-wait`. The record is the transcripts.

## Roles

- **Manager**: sets up, hands each scenario to a driver, watches the balance and `vastai show instances --raw`, writes the report. The manager runs unattended. It creates instances only where this plan says so and within the caps below.
- **Driver**: a fresh agent per scenario. It receives its task line, the README section "For agents", and the output of `vasty --help` and `vasty VERB --help` for every verb. It receives nothing from this file. Before each command it writes what it expects into `notes.md`. After a surprise it writes what it did. It asks the manager nothing about vasty. If it is stuck, it writes the question into `notes.md` and either continues on its own or stops with the blocker recorded. A driver gets 40 minutes. At 40 minutes the manager stops it, releases its boxes, and records the stop.

## Setup

Local, no spend. Root `/private/tmp/vasty-live-4`, repo venv on PATH, `VAST_API_KEY` exported and never echoed.

1. `vastai show instances --raw` returns `[]`. Destroy anything listed with `vastai destroy instance ID -y` and record the ids.
2. Account 836500 has a card on file. Record the starting credit from `vastai show user --raw` in `out/ledger.md`.
3. `~/.ssh/id_ed25519` present. `env | grep '^VASTY_'` prints nothing. `~/.config/vasty/config.toml` is absent.
4. Offer pool, as run 1 section 3 step 5. Set `max_price` to the highest `dph_total` among the top 5 RTX 3060 offers by reliability.
5. Write `vasty.toml`:

```toml
owner = "run4"

[defaults]
ttl = "10m"
run_ttl = "10m"
gpu = "3060"
max_price = 0.12          # from step 4
warn_before_expiry = "4m"
disk = 16
image = "vastai/base-image:cuda-12.6.3-auto"
```

6. `vasty config show` reports `project` for owner, ttl, run_ttl, gpu, max_price, warn_before_expiry, disk and image, and no `invalid_config`.
7. Fixtures in `fx/`:
   - `train.py`: every 30 s for 14 minutes, write `/workspace/out/ckpt-N.txt` containing `N` and print the path; 28 files, then exit 0.
   - `short.py`: print the hostname, sleep 90 s, exit 3.
   - `hello.py`: print the hostname and `nvidia-smi -L`.
   - `bad-startup.sh`: `echo broken >&2; exit 1`.
8. `vasty status` on the empty account. Pass: `leases: []`, `totals.charges_today` is a number, no `spend_unavailable` warning.

Stop the run if step 6 or 8 fails.

Each driver works in `/private/tmp/vasty-live-4/<scenario>/`, which holds a copy of `vasty.toml` and `fx/`. Its shell has `VAST_API_KEY` and `VASTY_OWNER=run4-<scenario>`. Every vasty command runs with `--json` and its output is saved as `out/<scenario>/NN-<verb>.json`. Drivers run one at a time.

## Scenarios

Each scenario starts and ends with `vastai show instances --raw` returning `[]`. Read the balance before each create and every 60 s while any instance exists. Cap per scenario: a balance drop of $0.75. Cap for the run: $3.00. Every clock in this run runs at most 20 minutes.

### 4A. Warnings and their fixes

Manager-driven. One fresh lease per warning, named after it. For each: provoke, run `status L --json`, copy the warning entry, run `fix` verbatim, run `status L --json` again. Record four facts per warning: the warning appeared, the fix exited 0, the warning afterwards matches the table, the lease is in the state the fix implies. A fix that exits 0 and leaves the lease in another state is a finding.

| Lease | Provocation | Fix the code emits | State the fix implies | Warning after the fix |
|---|---|---|---|---|
| `startup` | `reserve --name startup --startup fx/bad-startup.sh` | `vasty ssh L -- cat /workspace/.vasty/startup.log` | lease still up, output shows `broken`. Then `release startup` | still present |
| `guard` | `reserve --name guard`, box ready check, then `vasty ssh guard -- 'rm -f /etc/cron.d/vasty; pkill -f "[w]atchdog.sh"; sleep 2; rm -f /workspace/.vasty/alive; pgrep -f "[w]atchdog.sh" \|\| echo watchdog_dead'`. Wait 200 s. `status guard --verbose --json` | `vasty release L` | gone; `guard_layers` before the fix names `watchdog` | lease released |
| `unreach` | `reserve --name unreach`, then `vasty ssh unreach -- 'nohup sh -c "sleep 2; pkill sshd" >/dev/null 2>&1 &'`. Wait 15 s. Confirm `vasty ssh unreach -- true` fails. Then `status unreach --json` | `vasty release L` | gone | lease released |
| `expiring` | `reserve --name expiring --ttl 10m`, `sync expiring push fx/ /workspace/fx/`, `run --on expiring --detach -- python3 /workspace/fx/train.py`. Seven minutes after the reserve returned: `status expiring --json` | `vasty extend L --by 30m` | `ttl_remaining_s` over 1800. Then `release expiring` | gone |

Observe only, with the command that showed it: `expired_with_running_jobs`, `clock_skew`, `clock_skew_unknown`, `sweep_not_spawned`, `cache_rebuilt`.

If `unreach` is still listed 3 minutes after the fix, destroy it with `vastai destroy instance ID -y` and record that as a finding.

### 4B. Job lifecycle on a real box

Manager-driven on one box: `reserve --name jobs --ttl 20m`, box ready check, `sync jobs push fx/ /workspace/fx/`.

1. `run --on jobs --detach -- python3 /workspace/fx/short.py`. Wait 4 minutes without polling. `status jobs --json`. Expect `jobs[0].state` `exited` and `exit` 3.
2. `run --on jobs --detach -- python3 /workspace/fx/train.py`. Confirm `status jobs --json` shows it `running`. Hand the box to a driver with the task line: "A job on lease `jobs` is running. Stop it without releasing the box. Show the box's job list afterwards." Record every command it tries and how it ends. The README names no verb for this.
3. Pid reuse. `vasty ssh jobs -- 'pidof cron'`. Over `ssh`, write that pid into `/workspace/.vasty/jobs/j-1/pid` and remove `/workspace/.vasty/jobs/j-1/exit` if present. `status jobs --json`. Expect `j-1` `state: "unknown"`. This is the probe's `/proc/PID/cmdline` check, covered on fakes and first run on Linux by CI on 2026-10-31.
4. `release jobs`. Record `jobs` in the release JSON against the states seen in steps 1 to 3.

### 4C. Reserve without waiting, blind

Task line: "Reserve a GPU box without waiting for it to boot. When it is ready, run `fx/hello.py` on it once, then release it."

Pass: the first JSON has `state: "pending"` with null `expires_at`, `ttl_remaining_s`, `ssh` and `ports`; the transcript shows how the driver found out the box was ready; any `lease_pending` error and what the driver did next; the box is gone at the end.

## Guardrails

- Every clock runs at most 20 minutes from its start.
- Read the balance before each create and every 60 s while any instance exists, into `out/ledger.md`.
- Stop the run when: a scenario passes its cap; the cumulative drop passes $3.00; an id in `vastai show instances --raw` matches no `instance_id` in `vasty status --verbose`; vasty prints a traceback; two consecutive `reserve` calls return `no_offers` or `provider_error`.
- On any stop: create nothing more, release every lease, destroy any remaining instance by id, write the report.
- Redact `CONTAINER_API_KEY` by value in every saved file.

## Report

Append per scenario to `out/report.md` as it ends: each pass line, the JSON that proves it, the balance delta, and the driver's surprises in its own words. Then mine every `notes.md` and transcript for four lists:

1. Warnings that did not fire when the state called for one.
2. Hints and `fix` strings that did not lead to the fix.
3. Fields that were null or missing at the moment the driver needed them.
4. Commands the driver reached for that do not exist.

Copy the reviewed output to `docs/live/run4/` and the report to `docs/live-test-report-4.md`. File each defect under `issues/` with the command, the output and the rule it breaks.
