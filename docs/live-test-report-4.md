# Live run 4 report: warnings, jobs and pending boxes

Run on 2026-10-31 from 23:22Z to 23:58Z, account 836500, manager unattended. Plan: `docs/live-test-plan-4.md`. Raw record: `docs/live/run4/` (copied from `/private/tmp/vasty-live-4/out`). Evidence paths below are relative to `docs/live/run4/`.

## Outcome

| Scenario | Result | Balance drop |
|---|---|---|
| Setup | pass | $0.00 |
| 4A warnings and fixes | 4 of 4 warnings provoked and fixed. One reserve failed with `provider_error` and left a labelled instance behind. | $0.0237 |
| 4B job lifecycle | pass on all four steps. Driver stopped the job over `ssh` in about a minute. | $0.0110 |
| 4C reserve without waiting | pass. Box was ready in about 70 s, so the driver never saw `lease_pending`. | $0.0040 |
| Run | Credit $19.0509 to $19.0059 | $0.0450 |

No stop rule fired. No traceback. Every instance id seen in `vastai show instances --raw` matched a lease in `vasty status --verbose`. `vastai show instances --raw` returned `[]` at the end of every scenario and at the end of the run.

## Setup

- Pre-flight at 23:22:59Z: no instances, no vasty process, no `VASTY_*` env, no user config, `~/.ssh/id_ed25519` present. Credit $19.0509. `ledger.md`.
- Offer pool: `vastai search offers 'gpu_name=RTX_3060 verified=true rentable=true rented=false num_gpus=1 dph_total<=0.20 disk_space>=16' -o dph_total --raw` returned 28 offers (`offers-3060.json`). Top 5 by `reliability2`: 0.0694, 0.0609, 0.0747, 0.1345, 0.0609 $/hr. `max_price = 0.135` (decision: round the highest, 0.13449, up to the next tenth of a cent).
- Step 6 pass: `config show` reports `project` for owner, ttl, run_ttl, gpu, max_price, warn_before_expiry, disk, image. `setup-06-config.json`. It prints `max_price` as `0.14` for a configured `0.135`.
- Step 8 pass: `leases: []`, `charges_today: 0.81`, no warnings. `setup-08-status.json`.

## 4A. Warnings and their fixes

All four leases ran under `VASTY_OWNER=run4-warnings`. `warnings/log.md` lists every command with its start time and exit code.

| Lease | Warning appeared | Fix exited 0 | Warning after fix as table | Lease state as fix implies |
|---|---|---|---|---|
| startup | pass. `startup_failed` already in the reserve result, `01-reserve.json`, and in `02-status.json` | pass. `vasty ssh l-d0b0a86a -- cat /workspace/.vasty/startup.log` printed `broken`, `03-ssh.out` | pass. still present, `04-status.json` | pass. `running`, then `release` gave `destroy_pending: true`, `05-release.json` |
| guard | pass. `guard_partial` "watchdog not running or without curl", `guard_layers.watchdog: missing`, `13-status.json` | pass. `vasty release l-4294b026`, `14-release.json` | pass. `released`, no warning, `15-status.json` | pass |
| unreach | pass. `ssh unreach -- true` exit 255 "Connection refused" (`22-ssh.err`); status `unreachable`, `box_unreachable` "no answer for 26s", `23-status.json` | pass. `vasty release l-a2934a43`, `24-release.json` | pass. `released`, `25-status.json` | pass. Instance row gone 4 s after release (checked 23:31:29Z) |
| expiring | pass. `expiring_with_running_job` "2m left, j-1 running", `ttl_remaining_s` 174, `37-status.json` | deviation. Ran `vasty extend l-104b2888 --by 15m` in place of the emitted `--by 30m`, exit 0, `38-extend.json` | pass. No warning, `39-status.json` | not checked as written. `ttl_remaining_s` 1052 after `--by 15m`; 1800 would have needed a 32-minute clock. Released at once, `41-release.json` |

Decision on `expiring`: the run's hard limit is 20 minutes per clock. The emitted fix would have set the clock to about 32 minutes. I ran the same command with `--by 15m` and released the lease 20 s later. `guard_layers` stayed all `ok` after the extend (`40-status.json`), so the clock file followed the label.

Observe-only codes: `expired_with_running_jobs`, `clock_skew`, `clock_skew_unknown`, `sweep_not_spawned` and `cache_rebuilt` never appeared in any saved output.

### The failed `expiring` reserve

1. 23:24:06 to 23:24:10Z I started three reserves 2 s apart: `startup`, `guard`, `expiring`.
2. `vasty reserve --name expiring --ttl 10m --json` exited 2 after 2 s with `provider_error`, "Vast create failed: success is false", `details.response: {}`. `30-reserve.json`.
3. Instance 58589915 existed anyway, with the full lease label, on machine 20937, the same machine as `guard`. Vast showed it `actual_status: loading`, `cur_state: stopped`. No sweep follower was spawned for it. `status --verbose` listed it as `pending`, `instance_id` 58589915, all three guard layers `missing`, no warning. `31-status.json`.
4. I retried the same command at 23:25:59Z (`32-reserve`). It attached to the existing pending lease `l-d0eb8e9a`, spawned a follower for it, and waited 497 s on an instance that never left `loading`. It then exited 2 with `box_unreachable`, "Lease l-d0eb8e9a ended before it became ready.", hint "Run vasty status l-d0eb8e9a, then vasty reserve again." `32-reserve.json`.
5. `status l-d0eb8e9a --verbose` then showed `expired`, `cost: 0.0`, `verbose.actual_status: loading`. `33-status.json`.
6. A third `reserve --name expiring --ttl 10m` at 23:34:34Z succeeded in 46 s. `34-reserve.json`.

The ghost instance billed for 10 minutes while it sat in `loading`. The ledger shows it from 23:25:13Z to 23:33:25Z.

## 4B. Job lifecycle on a real box

Lease `jobs` (`l-fa8d6330`), owner `run4-jobs`, `--ttl 20m`, reserved in 34 s. `jobs/01-reserve.json`.

1. Pass. `short.py` started as `j-1` at 23:44:13Z (`03-run.json`). After 4 minutes `status jobs` showed `j-1` `state: exited`, `exit: 3`, `duration_s: 90`. `log_tail` was `['a8f7462bbe1a']`. `04-status.json`.
2. Pass. `train.py` started as `j-2` and showed `running`, `busy: true` (`05-run.json`, `06-status.json`). The driver stopped it without releasing the box and showed the job list. It ended with `j-2` `exited`, `exit: 143`, lease `running`, `busy: false`. `jobs/driver/05-status.json`. Commands it ran, in order:
   - `vasty status jobs --verbose --json`
   - `vasty ssh jobs -- ps ...` (found tmux session `vasty-j-2`: `run.sh` 780, `script` 784, `python3 train.py` 785)
   - `vasty ssh jobs -- kill -TERM 785`
   - `vasty ssh jobs -- ps ...; tmux ls` (exit 1 because no tmux server was left)
   - `vasty status jobs --json`
3. Pass. `pidof cron` gave 403. I wrote 403 into `/workspace/.vasty/jobs/j-1/pid` and removed `exit`. `/proc/403/cmdline` read `/usr/sbin/cron -P`. `status jobs` then showed `j-1` `state: unknown`, `exit: null`, and `busy: true`. No warning. `07-ssh.out`, `08-ssh.out`, `09-status.json`.
4. `release jobs` returned `jobs` as `[{id: j-1, exit: null, duration_s: 90}, {id: j-2, exit: 143, duration_s: 111}]`. Compared with steps 1 to 3: `j-1` was `exited 3` in step 1 and `unknown` in step 3; the release shows only `exit: null`. `j-2` matches step 2. The release entries carry no `state`. `10-release.json`.

Driver spawn: the first driver was spawned with the full brief inline (task, rules, README "For agents", all `--help` text). The Agent call failed before the driver ran anything: "API Error: Opus 5.5's safeguards flagged this message ... `[reasoning_extraction]`", request `req_011CgbD9xUZh8NLtNo2ZyCNW`. I spawned a second driver with the same brief saved as a file it read with `cat` (`prompt-jobs.md`). The text was identical. I used the file form for 4C too.

## 4C. Reserve without waiting, blind

Driver, owner `run4-nowait`. All files in `nowait/`.

- Pass. `reserve --name hello --no-wait --ttl 20m --json` returned in 1.6 s with `state: pending` and `expires_at`, `ttl_remaining_s`, `ssh`, `ssh_port`, `rsync_target`, `ports` all null. `02-reserve.json`. The driver chose `--ttl 20m` because it thought 10m might not cover boot.
- Pass. It found readiness by polling `status hello --json` every 30 s: `pending`, `pending`, then `running` about 70 s after the reserve. `03-status.json` to `05-status.json`.
- No `lease_pending` error appeared. `run --on hello --sync . --json -- python3 fx/hello.py` worked first time, exit 0, hostname and `GPU 0: NVIDIA GeForce RTX 3060` on stderr. `06-run.json`, `06-run.err`.
- Pass. `release hello` exit 0, then `status` showed no leases. `07-release.json`, `08-status.json`.

## The four lists

### 1. Warnings that did not fire when the state called for one

- A lease whose `reserve` failed with `provider_error` but whose instance exists (`l-d0eb8e9a`). `status --verbose` showed it `pending` with all three guard layers `missing` and no warning, and Vast's `cur_state` was `stopped`. Command: `vasty status --verbose --json` at 23:24:33Z, `warnings/31-status.json`.
- The same lease after it expired without ever booting: `expired`, no warning, `verbose.actual_status` still `loading`. Command: `vasty status l-d0eb8e9a --verbose --json`, `warnings/33-status.json`.
- A job in `state: unknown` (`j-1` after the pid swap). No warning, and `busy` turned `true` on a box with no live vasty job. Command: `vasty status jobs --json`, `jobs/09-status.json`.
- `release` of a lease with a running job (`expiring`, `j-1` running `train.py`). The result has no warning and reports the job as `exit: null`. Command: `vasty release expiring --json`, `warnings/41-release.json`.

### 2. Hints and fixes that did not lead to the fix

- `expiring_with_running_job` fix `vasty extend L --by 30m` is a fixed 30 minutes on a lease configured with `ttl = "10m"`. Running it verbatim would have broken the run's 20-minute clock limit. Command: `vasty status expiring --json`, `warnings/37-status.json`.
- `provider_error` hint "Check the request and retry." Retrying the same `reserve --name expiring` attached to the ghost lease and spent 497 s waiting on a box that never booted. Command: `vasty reserve --name expiring --ttl 10m --json`, `warnings/30-reserve.json` then `32-reserve.json`.
- `box_unreachable` from `reserve`, hint "Run vasty status l-d0eb8e9a, then vasty reserve again." The status it points at says `expired` with no reason (`33-status.json`). The second half worked.

### 3. Fields null or missing when needed

- `reserve --no-wait` returns `expires_at` and `ttl_remaining_s` null, while `status` on the same pending lease seconds later shows both (`expires_at` 00:11:45Z, `ttl_remaining_s` 1192). When the lease turned `running`, `expires_at` moved to 00:12:51Z. Commands: `nowait/02-reserve.json`, `03-status.json`, `05-status.json`.
- `log_tail` is absent from a single-lease `status` while the lease is `pending`, and `[]` once it is `running`. `nowait/03-status.json`, `05-status.json`.
- `release` job entries have no `state`, so a killed running job, an `unknown` job and a job that never wrote an exit code all read `exit: null`. `warnings/41-release.json`, `jobs/10-release.json`.
- `status` and `release` job entries name the job `id`; `run` names it `job`. The README result table does not list the job entry fields.
- The `run` result carries `"error": null`, which the README table does not list. `nowait/06-run.json`.
- `run --detach` and `status` give no pid or process handle for a job. The tmux session name `vasty-j-2` was the driver's only link from job id to process. `jobs/driver/02-ssh.json`.
- `provider_error` from create had `details.response: {}`: Vast's body had neither `msg` nor `error`. `warnings/30-reserve.json`.

### 4. Commands reached for that do not exist

- A verb to stop a job on a lease. The driver wrote "vasty has no explicit 'kill job' verb" before its first command and used `vasty ssh jobs -- kill -TERM 785`. `jobs/notes.md`.
- No other missing commands came up. The nowait driver asked in its notes where `run --sync .` puts files and what the remote working directory is; neither help nor README says.

## Hiccups, surprises and workarounds

Manager:

- `config show` prints `max_price` 0.14 for a configured 0.135. Output rounds money to cents. `setup-06-config.json`.
- `vasty --help` and every verb's `--help` list flags with no descriptions. `vasty ssh --help` does not show `-- COMMAND`. `vasty sync --help` does not show `SRC DEST` or `--delete`. `help.txt`.
- Three concurrent reserves: one got `provider_error` and left a labelled, stopped instance on the same machine as another lease. See 4A. `warnings/30-reserve.json`.
- Retrying `reserve --name expiring` after that error attached to the ghost lease. Its result never said `reused`, and it waited the whole clock. `warnings/32-reserve.json`.
- Vast reported the ghost as `cur_state: stopped`; vasty showed `pending`, not the README's `stopped` state. `warnings/31-status.json`.
- `status --verbose` with no target listed 15 history leases (`released`, `expired`) from earlier runs and other owners (`lead` and others), beside the three live `run4-warnings` leases. `warnings/31-status.json`.
- `expiring_with_running_job` message said "2m left" at `ttl_remaining_s` 174. `warnings/37-status.json`.
- `startup_failed` came back in the `reserve` result with `state: running`. The README says a box reports `pending` until startup exits 0, and a failing hook leaves it up with the warning. `warnings/01-reserve.json`.
- `guard_partial` took between 15 s and 200 s to appear after the watchdog died; I only checked at 200 s. The label gained `miss=watchdog`. `warnings/13-status.json`.
- `reserve` and `extend` each spawned a `sweep --follow` for `l-104b2888`, so two followers ran for one lease. Followers for released leases stayed up for minutes after `release`. The follower for `l-daaefdcd` (released 23:53Z) was still running at 23:56Z and exited at 23:56:51Z, about 4 minutes after `release`. I did not kill any follower.
- The first 4B driver was rejected at spawn by an API safeguard. The same brief delivered as a file worked. See 4B.
- Foreground waits in my harness were capped at 3 minutes, so every wait over that ran in the background.

Drivers, in their own words:

- 4B: "vasty behaved as expected. One gap: it has no verb to stop a job. I had to use `vasty ssh` and `ps` to find the PID, and the tmux session name `vasty-j-2` was the only link from the job id to the process."
- 4B notes: "ssh exited 1 because `tmux ls` found no server; expected given the job ended."
- 4C: "`reserve --no-wait` returned `expires_at: null`, but `status` on the same pending lease a few seconds later already showed `expires_at` 00:11:45 and a TTL of 1192s."
- 4C: "When the lease turned running, `expires_at` moved later to 00:12:51 and the TTL went back up to 1195. The clock seems to restart at `running`."
- 4C: "`status` on a single lease left out `log_tail` while it was pending. It appeared as `[]` once the lease was running."
- 4C: "The attached `run` result has an extra `\"error\": null` field that the README table does not list."
- 4C: "`duration_s` was 0 for the sub-second job."
- 4C: "`release` returned `destroy_pending: true`, so the destroy was not confirmed at that point. The `status` right after showed the box gone."
- 4C: "The README doesn't say where `run --sync .` puts files or what the remote working directory is. I guessed the relative path `fx/hello.py` and it worked first try."
- 4C: "SSH answered on the first `run` immediately after `status` reported running. I never saw `lease_pending`."

No driver reported a permission block.

## What it is like to drive vasty as an agent

Both drivers finished in under three minutes with no wrong turns. Each read the task, mapped it to two or three verbs from the README, and wrote correct expectations before almost every command. The JSON shapes matched their expectations closely enough that their surprises were small: fields appearing earlier than documented, an extra `error: null`, a missing `log_tail`. The warnings with `fix` strings worked as advertised for three of four cases; the agent can run them blind. The weak spots sit where vasty hands the agent back to raw ssh (stopping a job) and where a provider failure leaves state that vasty does not explain (the ghost lease). The 4C driver never had to handle `lease_pending`, because the box came up in 70 s; that path is still untested live.

## Balance ledger

Full ledger, one row a minute: `ledger.md`. Credit kept falling for about 3 minutes after the last instance was gone, from $19.0122 at 23:53:54Z to $19.0059 at 23:56:58Z, then held. Per-scenario drops above are read at each scenario's end and exclude that lag.

| Point | Time | Credit | Cumulative drop |
|---|---|---|---|
| Start | 23:22:59Z | 19.0509 | 0.0000 |
| 4A end | 23:43:14Z | 19.0272 | 0.0237 |
| 4B end | 23:51:12Z | 19.0162 | 0.0347 |
| 4C end | 23:53:54Z | 19.0122 | 0.0387 |
| Final | 23:58:11Z | 19.0059 | 0.0450 |

## Deviations from the plan

- Offer pool search modelled on plan 3 section 3 step 2 with `disk_space>=16`; `max_price` 0.135.
- 4A leases ran in parallel, two or three at a time, to fit the run into one sitting. This is how the concurrent-create failure surfaced.
- `expiring` fix run with `--by 15m` in place of `--by 30m`, for the 20-minute clock limit.
- 4B jobs driver brief delivered as a file after the inline brief was rejected.
- Driver output for 4B is in `jobs/driver/` so it does not collide with the manager's numbering in `jobs/`.
- Drivers were told not to read vasty's source or the repo.
- Nothing filed under `issues/`; this report replaces that.

## Proposed changes to vasty

- On a create that returns `success: false`, list instances for the new lease id and either destroy what it finds or adopt it into the result. Exposed by `vasty reserve --name expiring --ttl 10m --json` (`warnings/30-reserve.json`).
- Map Vast `cur_state: stopped` on a pending lease to `stopped` or warn on it. Exposed by `vasty status --verbose --json` (`warnings/31-status.json`).
- Give `reserve` its own readiness deadline for a box stuck in `loading`, shorter than the lease clock, and destroy and say so when it passes. Exposed by the 497 s `vasty reserve --name expiring` (`warnings/32-reserve.json`).
- When `reserve --name X` attaches to an existing pending lease, say so in the result or on stderr before waiting. Exposed by the same command.
- Size the `expiring_with_running_job` fix from the lease's ttl or `warn_before_expiry`, not a fixed 30m. Exposed by `vasty status expiring --json` (`warnings/37-status.json`).
- Add a verb to stop a job, such as `vasty stop LEASE JOB`, that signals the job's process group and records the exit. Exposed by the 4B driver's `vasty ssh jobs -- kill -TERM 785`.
- Add `state` to job entries in `release` results, and warn in `release` when it destroys a running job. Exposed by `vasty release expiring --json` (`warnings/41-release.json`) and `vasty release jobs --json` (`jobs/10-release.json`).
- Warn on a job in `state: unknown`, and decide whether `unknown` should set `busy`. Exposed by `vasty status jobs --json` (`jobs/09-status.json`).
- Return `expires_at` and `ttl_remaining_s` from `reserve --no-wait` as `status` does, or keep both null in `status` until `running`. Exposed by `nowait/02-reserve.json` against `nowait/03-status.json`.
- Return `log_tail` on single-lease `status` in every state, empty when there is nothing. Exposed by `vasty status hello --json` (`nowait/03-status.json`).
- Name the job field the same in `run`, `status` and `release` (`job` or `id`), and list job entry fields in the README table. Exposed by `nowait/06-run.json` and `jobs/10-release.json`.
- Drop `error: null` from the `run` result or document it. Exposed by `nowait/06-run.json`.
- Document where `run --sync DIR` puts files and the remote working directory. Exposed by the 4C driver's `vasty run --on hello --sync . -- python3 fx/hello.py`.
- Add help text for each flag, show `-- COMMAND` in `ssh --help` and the push and pull arguments in `sync --help`. Exposed by `vasty VERB --help` (`help.txt`).
- Print `max_price` in `config show` at the precision it was set. Exposed by `vasty config show --json` (`setup-06-config.json`).
- Keep history leases out of untargeted `status --verbose`, or limit them to the current owner. Exposed by `vasty status --verbose --json` (`warnings/31-status.json`).
- Spawn one `sweep --follow` per lease and have it exit when its lease is released. Exposed by `vasty extend l-104b2888 --by 15m` and `vasty release hello`.
- Report `expiring_with_running_job` time left rounded up or in seconds. Exposed by `warnings/37-status.json` ("2m left" at 174 s).
