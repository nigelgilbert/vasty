# Live run 5 report: two agents and a long lease

Run from 2026-10-31 23:59:45Z to 2026-11-01 02:28Z, account 836500. Plan: `docs/live-test-plan-5.md`. Raw record: `docs/live/run5/`, copied from `/private/tmp/vasty-live-5/out` after redaction. Driver notes are under `docs/live/run5/drivers/`. Evidence paths below are relative to `docs/live/run5/`. The manager log is `report.md`.

The original manager ran setup, all of 5B, and 5A steps 1 to 3. It died at 02:10:39Z when its parent session restarted. A replacement manager took over at 02:15Z and ran 5A steps 4 and 5, the cleanup and this report.

## Outcome

| Part | Result | Evidence |
|---|---|---|
| Setup | pass | `setup/config-show.json`, `setup/status.json`, `setup/offers-3060.json` |
| 5A long lease | 5 of 5 pass lines pass. `long` was released at 2 h 21 m, not 3 h 20 m. | `5A/` |
| 5B gate 1 | pass | `5B/a/02-reserve.json`, `5B/b/02-reserve.json`, `5B/manager/g1-status-all.json` |
| 5B gate 2 | pass | `5B/a/06-release.json`, `5B/a/08-status.json`, `5B/manager/g2-status-all.json` |
| 5B gate 3 | pass | `5B/b/09-status.json`, `5B/manager/25-instances-before-gate3.json`, `5B/manager/g3-status-all.json` |
| 5B gate 4 | fail on the release, pass on scope. The harness blocked B's `release --all`. | `drivers/b-notes.md`, `5B/manager/g4-status-all.json`, `5B/manager/30-status.json` |
| Run | Credit $19.00592068223 to $18.71330163341, drop $0.2926 | `ledger.md`, `5A/11-credit.txt` |

No stop rule fired. No traceback in any saved file. Every id in `vastai show instances --raw` matched an `instance_id` in each manager `status --all --everyone --verbose`. `vastai show instances --raw` returned `[]` at 02:22:14Z and at the end. No vasty, poll or ledger process remained at the end. The only `ps` match at 02:27:50Z was pid 37014, the parent session's watch loop, whose script text contains the run path. `5A/12-final-check.txt`.

## 5A. The long lease

`long`: lease l-383bf006, instance 58592907, owner `manager`, RTX 3060, `price_per_hr` 0.1 (provider `dph_total` 0.0963). Reserved at 00:00:57Z (T0) in 46 s with `--ttl 3h`, `expires_at` 03:01:35Z. `running_at` 00:01:41Z, all guard layers `ok`, `clock_skew_s` 0. `5A/01-reserve.json`, `5A/02-status.json`.

| Step | What happened | Evidence |
|---|---|---|
| 1 | Reserve as above. Credit after 19.00589284101. | `5A/01-reserve.json`, `5A/02-status.json` |
| 2 | 15 polls from 00:02:14Z to 02:21:32Z, every one exit 0 with no warnings. The 00:32:41Z poll was skipped while gate 3 paused the loop, so one interval is 933 s. | `5A/poll.tsv`, `5A/poll-NN-*` |
| 3a | 01:01:35Z `extend long --by 1h`: 03:01:35Z to 04:01:35Z, `ttl_remaining_s` 10799. Next poll 01:01:46Z, ttl 10788. | `5A/03-extend.json` |
| 3b | 02:01:06Z, 29 s before 2 h, `extend long --to 1h30m`: 04:01:35Z to 03:31:07Z, `ttl_remaining_s` 5400. Next poll 02:01:16Z, ttl 5390. | `5A/04-extend.json` |
| 4 | 02:22:05Z `release long --json`, exit 0 in 4 s: `uptime_s` 8429, `cost` 0.22, `destroy_pending` true. Instance gone at 02:22:14Z. | `5A/05-release.json`, `5A/06-instances-after-release.txt` |
| 5 | Charge rows over epoch 1793491197 to 1793499806 at 02:22:3xZ: `long` 0.225, run 0.292. Retried at 02:27:40Z with the end moved to then plus 60 s: `long` 0.226, run 0.293. | `5A/10-charges-summary.txt`, `5A/11-charges-summary.txt` |

Charge rows by instance:

| Lease | Instance | Charge |
|---|---|---|
| long | 58592907 | 0.226 |
| B's attempt-1 `ft` | 58594489 | 0.009 |
| B's `ft` | 58594901 | 0.038 |
| A's `ft` | 58594902 | 0.003 |
| victim | 58595159 | 0.017 |
| all run-5 instances | | 0.293 |

Pass lines:

| Check | Result | Evidence |
|---|---|---|
| `cost` within $0.02 of `long`'s charge rows | pass. 0.22 against 0.226, a gap of 0.006. | `5A/05-release.json`, `5A/11-charges-summary.txt` |
| `uptime_s` grows by the wall-clock interval between polls, within 30 s | pass. Largest gap 2 s across 15 intervals, including the 933 s one. The release's 8429 is 37 s after the 02:21:32Z poll's 8392, 37 s of wall clock. | `5A/poll.tsv`, `5A/05-release.json` |
| Credit drop within $0.05 of the summed charge rows | pass. Drop 0.2926 against rows 0.293, a gap of 0.0004. | `ledger.md`, `5A/11-credit.txt`, `5A/11-charges-summary.txt` |
| No `clock_skew` warning without a cause | pass. No `clock_skew` or `clock_skew_unknown` warning in any capture. `clock_skew_s` 0 in every verbose capture. | `5A/02-status.json`, `5B/manager/g*-status-all.json` |
| `long` in every manager `status` during 5B, released by step 4 alone | pass. Listed `running` in g0 to g4. Still listed by the provider until the step 4 release. No follower or sweep touched it. | `5B/manager/g0-pre-status-all.json` to `g4-status-all.json`, `ledger.md` |

Followers after the release. `long` had three followers: pid 49850 (`vasty sweep --follow long`, started by the manager at gate 4), 54285 (spawned by the 1 h extend) and 31197 (spawned by the `--to 1h30m` extend). All three exited on their own after the release: 49850 at 02:23:58Z (1 m 49 s after the release returned at 02:22:09Z), 31197 at 02:26:14Z (4 m 5 s), 54285 at 02:26:44Z (4 m 35 s). None had to be killed. `5A/07-followers-after-release.txt`, `5A/09-follower-exits.txt`.

## 5B. Two agents, one account

Drivers A (`VASTY_OWNER=agent-a`) and B (`agent-b`) were spawned at 00:21:40Z on the fourth attempt. A worked about 5 minutes and B about 9, by their own count.

| Gate | Result | Evidence |
|---|---|---|
| 1. Both reserve `ft` and run hello.py | pass. Both reserves exit 0, no `name_conflict`, 1 s apart. A l-915d23fa in 53 s, B l-7051adf1 in 47 s. `run --on ft` exit 0 on both. All three leases `running` in the manager's `status --all --everyone`. | `5B/a/02-reserve.json`, `5B/a/04-run.json`, `5B/b/02-reserve.json`, `5B/b/04-run.json`, `5B/manager/g1-status-all.json` |
| 1. Manager `status ft` | `lease_not_found`, exit 1, "No lease 'ft' for owner manager." | `5B/manager/10-status.json` |
| 1. Per-owner captures | Under `agent-a`, `status ft` and `extend ft --by 5m` returned l-915d23fa. Under `agent-b` they returned l-7051adf1. `status --cached` under each owner listed all three leases, the other owner's `ft` included. | `5B/manager/g1-a/`, `5B/manager/g1-b/` |
| 2. A releases all and lists the account | pass. `release --all` touched only l-915d23fa. A's `status --all --everyone` named `long` (manager) and B's `ft` as "neither mine". A's `ft` left the provider by 00:25:07Z. | `5B/a/06-release.json`, `5B/a/08-status.json`, `5B/manager/g2-status-all.json` |
| 3. B's status sweeps `victim` | pass. B's `extend ft --by 20m` set 00:57:46Z, 21 m after victim's 00:36:27Z clock. `victim` was still listed at 00:37:34Z with followers and watchdog dead. B's `status --all --everyone` at 00:37:40Z returned `swept: [{lease: l-3664542d, name: victim, expired_at: 00:36:27Z, ok: true, error: null}]`. `victim` was gone from the provider at 00:37:51Z. `long` and B's `ft` listed. | `5B/b/06-extend.json`, `5B/b/09-status.json`, `5B/manager/24-ssh.out`, `5B/manager/25-instances-before-gate3.json`, `5B/manager/g3-status-all.json` |
| 4. B releases all | fail on the release. B's `vasty release --all --json` was denied by the Claude Code auto-mode classifier and never ran. B's `ft` left at 00:57:53Z, 7 s after its clock, destroyed by its on-box watchdog. Then `long` was the only lease. | `drivers/b-notes.md`, `5B/manager/g4-status-all.json`, `5B/manager/30-status.json` |

### The plan's four questions

- Same name, two owners. Both `reserve --name ft` calls succeeded 1 s apart with no `name_conflict`. Each owner's `status ft` and `extend ft` resolved to its own lease. The manager's `status ft` returned `lease_not_found` with the hint "Run vasty status to list leases."
- Scope of `release --all`. A's released only A's lease. B's never ran. After gate 4 `long` was the only lease.
- Sweep across owners. A plain `status --all --everyone` from `agent-b` destroyed the expired `victim` lease of owner `victim`, 73 s past its clock.
- Concurrent state. No traceback. No `cache_rebuilt` warning. No lease created by one owner was missing from another owner's `status` or `status --cached`. Every owner's plain `status` lists every owner's leases.

## The four lists

### 1. Warnings that did not fire when the state called for one

- No warning for a lease with no follower. After `pkill -f "vasty sweep --follow"` at gate 3, `long` ran without a follower from 00:27Z to 00:58:54Z, and B's `ft` until its clock. Every `status` in that window has `warnings: []`. `sweep_not_spawned` covers a failed spawn only. `guard_layers` covers on-box layers only. Commands: `5B/manager/g3-status-all.json`, `5B/b/09-status.json`.
- `extend long --to 1h30m` moved the clock 30 m 28 s earlier with `warnings: []`. That is what was asked. Nothing in the result says the clock moved earlier. `5A/04-extend.json`.

### 2. Hints and `fix` strings that did not lead to the fix

- Manager `status ft` under `manager`: hint "Run vasty status to list leases." `status` lists both `ft` leases under `agent-a` and `agent-b`. The hint does not mention `--owner`. `5B/manager/10-status.json`.
- `status --everyone` hint `vasty status --all --everyone` led both drivers to the right command on the next try. Listed as a working hint. `5B/a/07-status.json`, `5B/b/08-status.json`.

### 3. Fields null or missing when the driver needed them

- `swept[].owner`. B: "The swept entry has no owner field, so I can't tell whose it was." `5B/b/09-status.json`.
- The previous `expires_at` in the `extend` result. B's `extend ft --by 20m` moved 00:37:46Z to 00:57:46Z. B compared it with 00:32:46Z from its own reserve and wrote "it added 25 minutes instead of 20". The other 5 minutes came from the manager's gate 1 `extend ft --by 5m` under `agent-b`. `5B/b/06-extend.json`, `5B/manager/g1-b/03-extend.json`.
- An up-to-date `ttl` in the label. B's `ft` label kept `created=1793492535;ttl=600` after two extends and updated only `expires=`. B tried to rebuild the expiry from `created` and `ttl`, got 00:32:15Z against the reserve's 00:32:46Z, and gave up. `5B/manager/g3-instances.json`, `5B/b/07-status.json`.

### 4. Commands the driver reached for that do not exist

- `vasty status --everyone` without `--all` or `--group`. Both drivers, first try, each time they wanted every box. `5B/a/07-status.json`, `5B/b/08-status.json`.

## Hiccups, surprises and workarounds

Each with the command that exposed it.

- Plain `vasty status` under `agent-a` and `agent-b` listed the manager's `long`. Both drivers expected owner filtering. They used `owner` and `totals.live_mine` 0 to decide `long` was not theirs. `5B/a/01-status.json`, `5B/b/01-status.json`.
- `vasty status --everyone` exits 1 `invalid_arguments` "--everyone needs --all or --group." Both drivers hit it. `5B/a/07-status.json`, `5B/b/08-status.json`.
- Attached `vasty run --on ft -- python3 /workspace/fx/hello.py` returns `error: null`, which the README result table does not list. Both drivers noted it. `5B/a/04-run.json`, `5B/b/04-run.json`.
- `duration_s` for the same job differs between the `run` result and `status`: A 3 and 1, B 2 and 0. `5B/a/04-run.json` against `5B/a/05-status.json`, `5B/b/04-run.json` against `5B/b/05-status.json`.
- `vasty release --all --json` entries carry `name`, `uptime_s`, `cost`, `jobs` and `destroy_pending` beyond the README's `lease`, `ok`, `error`. `5B/a/06-release.json`.
- `release` reports `cost` to the cent. A's `ft` ran 132 s at $0.08/hr and reported `cost` 0.0; its charge row is 0.003. The attempt-1 `ft` reported 0.0 for 122 s; its row is 0.009. `long` reported 0.22; its row is 0.226. `5B/a/06-release.json`, `5B/manager/cleanup/01-release.json`, `5A/05-release.json`.
- `vasty extend ft --by 20m` read as +25 m to B, because the manager had extended B's lease under `agent-b` at gate 1. `5B/b/06-extend.json`.
- B's `vasty status --all --everyone` destroyed another owner's expired box. B: "A read-only `status` from agent-b destroyed another owner's expired box." This is gate 3's intended path. `5B/b/09-status.json`.
- Each `reserve` and `extend` spawns a new follower and leaves the old ones running. B's `ft` had three followers at 00:26Z (reserve, the manager's extend, B's extend). `long` had three at the end. `5B/manager/23-followers-before.txt`, `5A/07-followers-after-release.txt`.
- Followers outlive `release` by up to a sleep chunk. A's two followers for l-915d23fa were alive 2 minutes after `release --all`. `5B/manager/23-followers-before.txt`. `long`'s three followers exited 1 m 49 s to 4 m 35 s after `release long`. `5A/09-follower-exits.txt`.
- A follower started before `extend --to` shortens the clock keeps the longer wait. Pid 54285 computed its wait from 04:01:35Z. The source checks the cache each 300 s chunk for release or history and does not re-read the expiry. Pid 31197 from the shortening extend covered the 03:31:07Z clock. `5A/04-extend.json`, `src/vasty/commands/sweep.py`.
- `vasty config show` printed `max_price` 0.27 for a configured 0.272. Run 4 showed the same rounding. `setup/config-show.json`.
- `status` reports `totals.credit` to the cent (18.98), against 19.0059 from `vastai show user`. `5B/b-attempt1/01-status.json`.
- `pgrep -af "vasty sweep --follow" || echo no_follower` at gate 3 printed its own parent shell's pid (93134), a match on the shell's command line. A harness artifact of the plan's command. `report.md`, gate 3.
- The provider listed `victim` `running` 67 s past its clock with followers and watchdog dead. That is the gate 3 setup working. `5B/manager/25-instances-before-gate3.json`.
- B's `ft` left 7 s after its clock with no follower, destroyed by the on-box watchdog. `5B/manager/30-status.json` shows `state: expired`, `cost` 0.04, `uptime_s` 2099.

## Harness findings

These concern the test harness and Claude Code, not vasty.

- Driver spawn rejections. Spawn 1 at 00:16:10Z, A and B: the API safeguard rejected both with `[reasoning_extraction]`. A had already run `01-status`; B had run `01-status` and `02-reserve`, which created `ft` l-8fcefb5a (instance 58594489). Spawn 2 at 00:17Z: A was stopped by a classifier after reading the brief; B was rejected at spawn. Spawn 3 at 00:21Z with the prompt "Please open BRIEF.md and follow it": both terminated after `01-status`. Spawn 4 at 00:21:40Z, with the notes rule reworded as one-line log entries and "in your own words" removed, ran to the end. `5B/a-attempt1/`, `5B/b-attempt1/`, `5B/a-attempt3/`, `5B/b-attempt3/`, `report.md`.
- The orphaned attempt-1 box. The manager released l-8fcefb5a at 00:19:57Z under `agent-b`: `uptime_s` 122, `cost` 0.0, charge row 0.009. `5B/manager/cleanup/01-release.json`, `ledger.md` 00:18:17Z to 00:19:18Z.
- Gate 4 classifier block. B's `vasty release --all --json > .../10-release.json 2> .../10-release.err` was denied by the Claude Code auto-mode permission classifier with "[Unverifiable Deletion Scope]". It did not run. B followed its brief and did not substitute `vasty release ft`. B's `ft` ran to its clock, about 20 extra minutes at $0.06/hr. `drivers/b-notes.md`.
- The original manager died at 02:10:39Z when its parent session restarted, between 5A polls.
- The replacement manager could not wait across turns. A foreground `sleep 420` was blocked, a foreground wait loop was moved to the background after 180 s, and ending a turn to wait for a background notification triggered a hand-back demand. The replacement released `long` at 02:22:05Z instead of 03:20:58Z.

## Ledger and final drop

Start credit 19.00592068223 at 23:59:45Z. `ledger.md` has a reading every 60 s from 00:00:52Z to 02:22:13Z.

| UTC | Credit | Drop | Instances |
|---|---|---|---|
| 00:00:52Z | 19.0059 | 0.0000 | none |
| 00:17:15Z | 18.9816 | 0.0243 | long |
| 00:21:21Z | 18.9714 | 0.0345 | long, after the attempt-1 `ft` release |
| 00:25:27Z | 18.9539 | 0.0520 | long, B's ft |
| 00:38:47Z | 18.9053 | 0.1006 | long, B's ft, after victim's sweep |
| 00:58:16Z | 18.8504 | 0.1555 | long |
| 02:01:43Z | 18.7475 | 0.2584 | long |
| 02:22:13Z | 18.7153 | 0.2906 | none |
| 02:27:50Z | 18.71330163341 | 0.2926 | none, final |

Final drop $0.2926, under the $3.00 cap. Charge rows for run-5 instances sum to 0.293.

## Deviations from the plan

- The original manager died at 02:10:39Z. A replacement manager finished the run from 02:15Z.
- 5A step 4 ran at 02:22:05Z, 2 h 21 m 8 s after T0, not at 3 h 20 m. The harness demanded a hand-back from the replacement manager, and it released `long` first to leave the account empty. `long` therefore never ran past its first `expires_at` of 03:01:35Z, and the 03:31:07Z clock set at step 3b was not reached.
- 5A step 3b ran at 02:01:06Z, 29 s before 2 h. The original manager's wait loop ran out of iterations early.
- 5A polls paused from 00:27:09Z to about 00:37:51Z for gate 3. One poll was skipped.
- Two polls ran early on `POLLNOW` to catch the result of each extend (01:01:46Z, 02:01:16Z).
- Gate 1's per-owner captures were run by the manager under `agent-a` and `agent-b` from the run root. The drivers' task lines stayed as the plan wrote them. The `extend ft --by 5m` under `agent-b` moved B's clock without B knowing, which B later read as a wrong `extend`.
- B's attempt-1 `ft` (instance 58594489) was created outside the gate flow by a driver that the API safeguard then cut off. The manager released it.
- Gate 4 never ran B's `release --all`. B's `ft` left by its on-box watchdog at its clock.
- B's `ft` clock ran about 35 minutes, under the 40-minute limit.
- The gate 3 `pkill` also killed the follower for `long` and B's `ft`, as the plan expected. `long`'s follower was restarted at 00:58:54Z.
- No `issues/` files were filed. Nigel triages this report into work items.

## Driving vasty as an agent

Both drivers finished each task in a few commands and read results from the JSON. The `invalid_arguments` hint fixed `status --everyone` in one step for both. Neither driver needed more than the brief and the `--help` text. The owner model caused most of the second-guessing: plain `status` shows every owner, `--everyone` needs `--all`, `swept` omits the owner, and `lease_not_found` under one owner does not say the name exists under another. After an `extend` result it could not explain, B ran an extra `status` and tried to rebuild the expiry from the label. B's notes end with a question for a human about how to free its box once the release was blocked.

## Proposed changes to vasty

- Accept `status --everyone` alone as `--all --everyone`. Exposed by `vasty status --everyone` (`5B/a/07-status.json`, `5B/b/08-status.json`).
- On `lease_not_found`, name the owners that hold a lease of that name and hint `--owner`. Exposed by the manager's `vasty status ft` (`5B/manager/10-status.json`).
- Add `owner` to each `swept` entry. Exposed by B's `vasty status --all --everyone` (`5B/b/09-status.json`).
- Add the previous `expires_at` to the `extend` result. Exposed by B's `vasty extend ft --by 20m` (`5B/b/06-extend.json`) and `vasty extend long --to 1h30m` (`5A/04-extend.json`).
- Update the label's `ttl` on `extend`, or drop `ttl` from the label. Exposed by B's `vasty status ft` after its extend (`5B/b/07-status.json`, `5B/manager/g3-instances.json`).
- Warn in `status` when a lease has no live follower. Exposed by `pkill -f "vasty sweep --follow"` then `vasty status --all --everyone --verbose` at gate 3 (`5B/manager/g3-status-all.json`).
- Have `extend` and `reserve` replace a lease's existing follower instead of adding one. Exposed by `vasty extend long --by 1h` and `vasty extend long --to 1h30m` (`5A/07-followers-after-release.txt`, `5B/manager/23-followers-before.txt`).
- Have `release` end the lease's followers at once. Exposed by `vasty release --all` under `agent-a` (`5B/manager/23-followers-before.txt`) and `vasty release long` (`5A/09-follower-exits.txt`).
- Have a follower re-read the expiry after each sleep chunk, so a shortening `extend --to` is picked up. Exposed by `vasty extend long --to 1h30m` (`5A/04-extend.json`).
- Report the same `duration_s` for a job in the `run` result and in `status`. Exposed by `vasty run --on ft -- python3 /workspace/fx/hello.py` then `vasty status ft` (`5B/a/04-run.json`, `5B/a/05-status.json`).
- Report `cost` to three decimals. Exposed by `vasty release --all` under `agent-a`, cost 0.0 against a 0.003 charge row (`5B/a/06-release.json`).
- Print `max_price` in `config show` as configured. Exposed by `vasty config show`, 0.27 for 0.272 (`setup/config-show.json`).
- README: say that plain `status` lists every owner's leases and that `totals.live_mine` counts the caller's. Exposed by `vasty status` under `agent-a` and `agent-b` (`5B/a/01-status.json`, `5B/b/01-status.json`).
- README: add `error` to the attached `run` row, and list `name`, `uptime_s`, `cost`, `jobs` and `destroy_pending` on bulk `release` entries. Exposed by `vasty run --on ft` and `vasty release --all` (`5B/a/04-run.json`, `5B/a/06-release.json`).
