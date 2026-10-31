# Live run 4: two agents and a long lease

Run 1 phase 4 tested owners and groups with one actor. Runs 1 and 2 kept every box under 20 minutes. This run puts two agents on one account at the same time, beside a box that stays up for three hours.

## Roles

- **Manager**: sets up, starts the long lease, runs drivers A and B through the gates below, polls the long lease, writes the report. The manager runs unattended. It creates instances only where this plan says so and within the caps.
- **Drivers A and B**: fresh agents with `VASTY_OWNER=agent-a` and `VASTY_OWNER=agent-b`. Each works in its own directory, `/private/tmp/vasty-live-4/a/` or `b/`, holding a copy of `vasty.toml` and `fx/`. Both share the default vasty state directory. Each receives its task lines one gate at a time, the README section "For agents", and the `--help` output for every verb. Neither knows the other exists. Driver rules from run 3 apply: expectations and surprises in `notes.md`, no questions answered, 40 minutes each.

## Setup

Run 3's setup steps 1 to 4 and 8, in `/private/tmp/vasty-live-4`. Config:

```toml
[defaults]
ttl = "10m"
run_ttl = "10m"
gpu = "3060"
max_price = 0.12          # from the offer pool
disk = 16
image = "vastai/base-image:cuda-12.6.3-auto"
```

Owner comes from each shell's `VASTY_OWNER`. The manager's shell sets `VASTY_OWNER=manager`. `vasty config show` reports `env` for owner and `project` for ttl, run_ttl, gpu, max_price, disk and image, with no `invalid_config`. Stop the run if it does not. Fixtures: `fx/hello.py` from run 3.

## Scenarios

Cap for the run: $3.00. Clocks in this run run at most 20 minutes, except `long` and B's `ft`.

### 4A. The long lease

Manager-driven. Starts first and ends last.

1. `reserve --name long --ttl 3h --json`. Record `instance_id` from `status long --verbose`, `expires_at`, `price_per_hr` and the credit.
2. Every 10 minutes: `status long --json` and `vastai show user --raw`. Append UTC, `cost`, `uptime_s`, `ttl_remaining_s`, `warnings` and the credit to `out/4A/poll.tsv`.
3. At 1h: `extend long --by 1h`. At 2h: `extend long --to 1h30m`. Record both results and the next poll.
4. At 3h20m from the start, or when `ttl_remaining_s` passes under 5 minutes: `release long`. Record `cost` and `uptime_s`.
5. `vastai show invoices-v1 --charges -s START -e END --raw` with epoch seconds. Sum the rows for `long`'s instance id. Sum the rows for every instance this run created.

Pass:

- `cost` from step 4 is within $0.02 of the summed charge rows for `long`'s instance.
- `uptime_s` grows by the wall-clock interval between polls, within 30 s.
- The credit drop over the run is within $0.05 of the summed charge rows for all instances, allowing for charges that land after the last reading.
- No `clock_skew` warning without a cause the transcript shows.
- `long` is listed in every manager `status` during 4B and is released by step 4 alone.

### 4B. Two agents, one account

Starts 15 minutes into 4A. The manager advances both drivers gate by gate. A gate opens when the condition holds and the manager has saved its captures. The manager records `status --all --everyone --json` at every gate into `out/4B/manager/`.

**Gate 1.** Both drivers, at the same time: "Reserve a box named `ft`, run `fx/hello.py` on it, keep the box up."

Opens when both `ft` leases show `running` in the manager's `status --all --everyone`. Captures at the gate:

- Manager: `status ft --json`. Record whether it returns `ambiguous_target`, one lease, or `lease_not_found`.
- Driver A and B, each: `status ft --json`, `status --cached --json`, `extend ft --by 5m --json`. Record whose lease each command touched, from `lease` in the result, and whether the other owner's `ft` appears in `status --cached`.

**Gate 2.** Driver A: "Release every box you own. Then list every box on the account and report which remain."

Opens when A's `ft` is gone from `vastai show instances --raw`. Captures: manager `status --all --everyone`. Pass: B's `ft` and `long` are listed. A's transcript names B's `ft` and `long` as not A's.

**Gate 3.** Cross-owner sweep with a controlled victim. First, driver B: "Give your box `ft` twenty more minutes." Record B's new `expires_at`. Then the manager, with `VASTY_OWNER=victim`: `reserve --name victim --ttl 10m`, box ready check. Confirm B's `expires_at` is at least 5 minutes after `victim`'s `expires_at` plus 1 minute. If it is not, have B extend again before going on. Then isolate the victim as run 1 phase 2b' did:

```
pkill -f "vasty sweep --follow"
vasty ssh victim -- 'rm -f /etc/cron.d/vasty; pkill -f "[w]atchdog.sh"; sleep 2; rm -f /workspace/.vasty/alive; pgrep -f "[w]atchdog.sh" || echo watchdog_dead'
pgrep -af "vasty sweep --follow" || echo no_follower
```

`pkill` here also stops B's follower for `ft` and the follower for `long`. Record that. The manager runs no networked vasty command from `victim`'s `expires_at` until the gate. B is idle during this wait. At `expires_at` + 1 minute, confirm `vastai show instances --raw` still lists `victim`, then open the gate.

Driver B: "List every box on the account. Report anything in `swept`."

Pass: B's `swept` names `victim` with `ok: true`, `victim` is gone from `vastai show instances --raw`, and B's `ft` and `long` are listed. If `victim` is still listed 3 minutes after B's command, the manager runs `vasty release victim` under `VASTY_OWNER=victim` and fails the gate.

**Gate 4.** Driver B: "Release every box you own."

Opens when B's `ft` is gone. Captures: manager `status --all --everyone`. Pass: `long` is the only lease listed. Then the manager runs `vasty sweep --follow long` detached, to replace the follower killed at gate 3, and 4A continues.

Questions the transcripts answer, written up in the report:

- Same name, two owners. Both `ft` reserves succeed with no `name_conflict`. What each owner's `status ft` and `extend ft` resolved to, and what the manager's `status ft` did.
- Scope of `release --all`. Gate 2 and gate 4 captures.
- Sweep across owners. Gate 3.
- Concurrent state. Any traceback, any lease missing from one agent's `status` that the other created, any `cache_rebuilt` warning, across every capture.

## Guardrails

- `long` is exempt from the 20-minute clock limit. B's `ft` runs at most 40 minutes, to outlive the gate 3 wait. Every other clock runs at most 20 minutes.
- Followers stay alive except at gate 3, where the plan kills them and gate 4 restores `long`'s.
- Read the credit before each create and every 60 s while any instance besides `long` exists, into `out/ledger.md`.
- Stop the run when: the cumulative drop passes $3.00; `long` leaves `vastai show instances --raw` before 4A step 4; an id in `vastai show instances --raw` matches no `instance_id` in `vasty status --all --everyone --verbose`, apart from `victim` between its expiry and gate 3; vasty prints a traceback; two consecutive `reserve` calls return `no_offers` or `provider_error`.
- On any stop: stop both drivers, create nothing more, release every lease under each owner, destroy any remaining instance by id, write the report.
- Redact `CONTAINER_API_KEY` by value in every saved file.

## Report

Append per gate and per 4A step to `out/report.md` as each ends. Mine the 4B transcripts with the four lists from run 3's report section. Copy the reviewed output to `docs/live/run4/` and the report to `docs/live-test-report-4.md`. File each defect under `issues/` with the command, the output and the rule it breaks.
