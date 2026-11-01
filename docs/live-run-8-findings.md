Run 8 second pass (`/private/tmp/vasty-live-8b`, owners r8a to r8g), target opus/medium, six of seven scenarios run: A, B, D, E, F and G.

## Friction

Paths are under `/private/tmp/vasty-live-8b/out/`. Pass 1 is `/private/tmp/vasty-live-8`. Run 7 is `/private/tmp/vasty-live-7/out/report.md`.

Verdicts: A, B, D, E and G PASS. F FAIL on its fixture (`f/verdict.md`). C did not run in this pass. Its setup made four r8c boxes on 15 minute clocks and one unlabeled instance at 22:17Z to 22:18Z (`c-setup/01-reserve-keep.json` to `c-setup/05-orphan-create.json`). The orchestrator never spawned the C agent. Pass 1 C items below carry the tag `not exercised in pass 2` and cite pass 1 files as `p1 c/NN`.

### Hints

- A, `a/02-reserve.json` `message` "No offers match cuda>=12.6 under $0.045/hr." and `hint` "Try a higher --max-price, or a lower --cuda." A could not tell which filter ruled out the offers, since the message omits `gpu=any` and the project `disk = 16`. It cost one retry: `a/03-reserve.json` at `--max-price 0.07` got `price_per_hr: 0.063`. Run 7 needed four reserves for the same task. The price number in the hint is gone. [new in pass 2, persisted from run 7 for the unnamed blocking filter, fixed since run 7 for the price suggestion]
- G, `g/02-reserve.json` lines 3 to 7, `message` "Lease l-0ebcec95 ended before it became ready.", `hint` "Run vasty status l-0ebcec95, then vasty reserve again.", `details.destroyed: true`. G ran the status (`g/03-status.json`) and got `state: "expired"`, `running_at: null` and every `guard_layers` entry `"missing"`. out/g/final.md: "Status (03) explained nothing beyond `expired`". One extra command before the retry the hint also named. [new in pass 2]
- E, `e/03-extend.json` lines 3 to 4, `message` "unrecognized arguments: --until 22:18", `hint` "--until was removed: use --by or --to." `--until` took a wall-clock time and `--to` takes a duration from now. E read `extend --help` to learn that, then wrote `extend ft --by 20m` (`e/08-extend.json`). One extra help read. [persisted from pass 1]
- E, `e/04-release.json` lines 3 to 4, `hint` "--all was removed: use --owner O. --yes was removed: drop it." `--owner` needs a value. E read README line 55 and wrote `release --owner "${VASTY_OWNER:-$USER}"` (`e/10-release.json`). One extra README read. [persisted from pass 1]

### Help and docs

- D, README line 306 "An auto-reserved `run` or `serve` without `--ttl` gets the 30m built-in". D read it against line 304, which ranks `--profile` above built-ins, and ran `d/02-config-show.json` to confirm `ttl` `"20m"` from source `"profile"` before spending. One extra command. Serve honored the profile ttl (`ledger.log` line 25 `owner=r8d;...;ttl=1200`). [persisted from pass 1 as a README ttl contradiction, fixed since run 7 for serve ignoring the profile ttl]
- B, `run --help` for `--sync`: "push DIR to the box before the command". B re-read README line 82 to learn DIR's contents land in `/workspace/`, so the command is `python3 train.py` (`b/02-run.json`). [persisted from pass 1]
- A, out/a/final.md: "I had to guess whether `--gpu any` was needed." README line 308 "`any` clears `gpu`" settled it, and `a/02-reserve.json` with `--gpu any` cleared the project pin. One README read. [new in pass 2, fixed since run 7 for the missing wildcard]
- B, `b/02-run.json` `ttl_remaining_s: 577` on a 10m clock. B's out/b/final.md says "Neither the README nor `--help` says when the clock starts." README line 257 says "The clock starts when the box boots and writes its clock file". The B claim disagrees with the README. The ledger agrees with the README: lease l-9dc4e45b was created 21:58:40Z and its clock started 21:59:10Z (`ledger.log` line 6, `expires=1793570950` minus `ttl=600`). [persisted from pass 1]
- A, `a/04-run.rc` `0` for `run --on r8a-c --sync fx`. README line 78 says `run --on` "reject[s] creation flags" and does not say whether `--sync` is one. A guessed and it worked. [new in pass 2]
- B, out/b/final.md: "I guessed `python3` over `python` for the base image." The guess worked (`b/02-run.json`). [persisted from pass 1]
- B, out/b/final.md: "I checked `sync --help` for argument order: `LEASE push|pull SRC DEST`." One help read before `b/07-sync.json`. [persisted from pass 1]
- D, `d/02-config-show.json` lines 19 to 21 `"disk": {"value": 16, "source": "project"}` on the vllm box. out/d/final.md: "I wasn't sure it would hold the vLLM image plus weights." It held for the 0.5B model. No extra command. [persisted from pass 1]
- C, p1 `c/03-extend.json`: C read `extend --help` to confirm `--to` is a duration from now. E hit the same question in pass 2 through the `--until` hint above. [not exercised in pass 2]

### Output shape

- B, `b/02-run.json` carries `gpu`, `price_per_hr` and `ttl_remaining_s` and no job state. B still ran `b/03-status.json` 22 s later to see `busy: true`, j-1 `state: "running"` and `log_tail`. B did not list this as friction. One extra command. [persisted from pass 1, persisted from run 7 for the follow-up status, fixed since run 7 for gpu and price]
- G, `g/15-status.json` line 8 `"state": "expired"` with no `destroy_pending`. README line 295 defines `expired` as "Destroyed or being destroyed." G ran the account view `g/16-status.json` to confirm the instance had left. One extra command. [new in pass 2]
- B, E, F: job stdout lands in `.err` under `--json`. `b/08-run.err` line 1 "eval ok: final loss 0.0417", `e/09-run.err` line 1 "smoke ok", `f/03-run.err` lines 4 to 5 and `f/05-run.err` lines 8 to 9. README line 94 documents it. The run 8b check.sh for F looked in the run `.json` and reported two false FAILs. [persisted from pass 1, persisted from run 7]
- B, F: the attached `run` JSON has no `cmd`. `b/08-run.json` shows `job: "j-2"` only, and `cmd: "python3 eval.py"` first appears in `b/09-release.json` lines 15 to 16. F hit the same in `f/03-run.json` and `f/04-release.json` `jobs[0].cmd`. [new in pass 2]
- A, `a/07-status.json` `totals.burn_per_hr: 0.2037` and `live: 3` under `--owner r8a` with `leases: []`. A read this as its box still billing until README line 300 and `live_mine: 0` settled it. One README read. [persisted from pass 1, persisted from run 7]
- A, E, F: `uptime_s` reads low. `a/06-release.json` `uptime_s: 62`, `e/10-release.json` `results[0].uptime_s: 69`, `f/04-release.json` `uptime_s: 46`. README line 162 counts from the first `running` sample, and the ledger labels match. A's "roughly 3-minute reserve wait" and E's "the box had been rented for several minutes" disagree with the raw files. A's reserve ran from `a/02-reserve.rc` at 15:58:42 to `a/03-reserve.rc` at 15:59:33 local, and its label says `created=1793570329` (21:58:49Z). E's box was created 21:59:17Z (`ledger.log` line 6) and released at 22:01:01Z (`e/10-release.rc` mtime). [new in pass 2]
- F, `f/07-config-show.json` lines 15 to 17 `"max_price": {"value": 0.09, "source": "project"}` right after `f/06-config-set.json` wrote `value: 0.08`. Nothing says the user value is shadowed. [persisted from pass 1]
- F, `f/05-run.json` `released: true`, `expires_at: null`, `ttl_remaining_s: null`, and no `cost` or `uptime_s`. F: "Box 2's spend is not reported anywhere." [new in pass 2]
- F, `f/04-release.json` `cost: 0.0` for `uptime_s: 46` at $0.063/hr. README line 275 says release sums the rows posted so far. [persisted from pass 1, persisted from run 7]
- F, `f/08-config-profiles.json` `profiles.prep` carries `ttl` and `startup` and no source or path. F inferred `./vasty.toml`. [persisted from pass 1]
- E, F: `duration_s: 0` for jobs that ran Python. `e/09-run.json`, `f/03-run.json`, `f/05-run.json`. [persisted from pass 1, persisted from run 7]
- E, `e/11-status.json` `leases: []` under `--owner r8e` after release. E: "To see it after release I would have to name it with `status ft`." [persisted from pass 1]
- G, `g/15-status.json` `swept: []` on the first poll that showed `expired`. out/g/final.md: "nothing in status says whether the watchdog or the follower did it." No extra command. [persisted from pass 1]
- A, B, D, E, F, G: the milestone line prints the raw price. `a/03-reserve.err` line 1 "RTX 3060 at $0.06296296296296297/hr" beside `a/03-reserve.json` `price_per_hr: 0.063`. `d/03-serve.err` line 1 "RTX 5060 Ti at $0.1748148148148148/hr" beside `d/03-serve.json` `price_per_hr: 0.1748`. Same in `b/02-run.err`, `e/06-reserve.err`, `f/02-reserve.err` and `g/04-reserve.err` line 1. A, B, D, E and F noted it. No extra command. [new in pass 2]
- G, `g/16-status.json` `totals.burn_per_hr: 0.0536` with `live: 0`. The figure is the unlabeled C setup instance i-58721087 (`g/01-status.json` line 88 `price_per_hr: 0.0536`). README line 270 counts orphans in `burn_per_hr` and does not say `live` leaves them out. G worked it out without a command. [new in pass 2]
- D, `d/04-stop.json` lines 5 to 6 `"state": "killed"`, `"exit": 0`. out/d/final.md: "reads oddly for a clean TERM shutdown". README line 151 documents `killed` with the job's exit code. No extra command. [new in pass 2]
- E, `e/01-reserve.rc` to `e/04-release.rc` all `1`. E expected argparse's 2. README line 126 gives 1 for bad input. No retry. [new in pass 2]
- C, p1 `c/02-status.json` lines 85 to 86 `burn_per_hr: 0.5898`, `live: 6` under `--owner ex8c`. C summed its own burn by hand. A hit the same totals in pass 2 (above). [not exercised in pass 2]
- C, p1 `c/05-tag.json` `warnings[0]` `"code": "box_unreachable"`, `"message": "no answer for 10s"` on a box that was running a minute earlier. [not exercised in pass 2]
- C, p1 `c/08-tag.err` line 1 "vasty: could not attach the SSH key to l-91c2422f: Vast attach ssh key failed: SSH key already associated with instance." The JSON `warnings` stayed empty. [not exercised in pass 2]
- C, adoption reset `uptime_s`: p1 `c/01-status.json` line 132 `uptime_s: 279` on the orphan, p1 `c/09-release.json` line 4 `uptime_s: 15` after `tag --ttl`. [not exercised in pass 2]
- C, p1 `c/06-release.json` line 19 `cost: 0.001` and p1 `c/11-status.json` line 13 `cost: 0.002` for the same lease. F's `cost: 0.0` above is the pass 2 case. [not exercised in pass 2, persisted from run 7]
- C, p1 `c/01-status.json` line 154 `balance: 0.0` beside `credit` 18.3 confused C at first read. No pass 2 agent remarked on it. [not exercised in pass 2]

### Timing

- B, `b/04-status.json` `warnings[0]` "4m left, j-1 running" with fix "vasty extend l-9dc4e45b --by 10m". The 10m clock covered the 8 minute job with about 90 s to spare and no room for pull and eval. B ran the fix as given (`b/05-extend.json` 22:09:10Z to 22:19:10Z). One extend, supplied by the warning. [persisted from pass 1, persisted from run 7; the warning fired this time]
- G, `g/05-status.json` to `g/15-status.json`: eleven `status tick2 --verbose` polls from a background loop. out/g/final.md: "there is no way to wait on a lease until it is gone, so I wrote a status polling loop. `sweep --follow` exists, but it sweeps rather than watches." [persisted from pass 1]
- D, `d/03-serve.err` line 4 "vasty: l-947a5deb startup done" was the last write at 16:19:24 local. `d/03-serve.rc` landed at 16:25:48. D: "There was no "waiting for vLLM" or "endpoint ready" line, so it was hard to tell progress from a hang." Six minutes 24 seconds of silence. D ran no extra command. [new in pass 2 for this shape, fixed since pass 1 and run 7 for the box boot phase, persisted from run 7 for the vLLM load phase]
- B, `b/04-status.json` j-1 at "epoch 18/24" with `ttl_remaining_s: 214`. B waited 125 s with no completion signal, then confirmed `exit: 0` in `b/06-status.json`. Two minutes waited. [persisted from pass 1]

### Provider

- G, `g/02-reserve.err` line 1 "vasty: l-0ebcec95 created on instance 58721333, RTX 3060 at $0.06296296296296297/hr" and no further milestone. Vast never reported the box running: `ledger.log` lines 25 to 26 show `58721333:loading` and lines 27 to 30 show `58721333:created`. `reserve` blocked from 16:18:41 to 16:24:51 local, 6 min 10 s, then returned `box_unreachable` with `details.destroyed: true` at `created + ttl` (`g/03-status.json` `expires_at` 22:24:45Z). G retried once (`g/04-reserve.json`). README line 183 defines `box_unreachable` as "the box does not answer SSH". out/g/final.md says "Reserve eats most of a short clock (04)" for the retry. The raw files disagree: the retry's clock started at boot (`g/05-status.json` `running_at` 22:28:09Z, `expires_at` 22:34:05Z), so `g/04-reserve.json` spent 7 s of 360. Only the never-booted box lost its clock to the wait. Six minutes waited and one retry. [new in pass 2, persisted from pass 1 for a waiting reserve held for the whole TTL by a box that never became ready]
- F, `f/05-run.err` lines 1 to 4. The auto-reserved box l-ed82caa8 sat in `loading` at `ledger.log` line 8 (22:02:01Z) and reached `running` by line 9 (22:03:02Z). `f/04-release.rc` 16:01:19 to `f/05-run.rc` 16:04:36 local is 3 min 17 s. F did not flag it. A, B and E had their boxes in about a minute, and F's first box took about 2 minutes (`f/01-status.rc` 15:58:39 to `f/02-reserve.rc` 16:00:40 local). [new in pass 2]
- G, the retry box 58722223 shows `None` at `ledger.log` line 31 (22:25:33Z), `loading` on lines 32 to 33, and `running` on line 34 (22:28:38Z). `g/04-reserve.json` returned at 16:28:12 local, 3 min 5 s after G started it. G did not flag it. [new in pass 2]

### Harness

- C did not run. The orchestrator built C's setup (`c-setup/DONE`) and never spawned the agent. `out/c/` holds only `check.sh`. The four r8c boxes ran out their clocks unattended and left the ledger by line 39 (22:33:45Z). The orchestrator destroyed the unlabeled instance 58721087 by hand at 22:36:34Z (out/run.md "## Manual releases"). Its first `vastai destroy instance` without `-y` hit vastai's confirmation prompt and aborted. Every pass 2 change in the plan table assigned to C alone went unexercised. [new in pass 2]
- E, `e/check.txt` four FAILs "no line contains it". check.sh searched `.err` files. With `--json` the removed-flag errors land in stdout `message` and `hint` (`e/01-reserve.json` to `e/04-release.json` lines 3 to 4). E passes on the raw files. [new in pass 2]
- F, `f/check.txt` FAILs for `prep.ok` and `extra.ok`. check.sh searched the run `.json` files. The proof lines are in `f/03-run.err` lines 4 to 5 and `f/05-run.err` lines 8 to 9. F predicted this in out/f/final.md. [new in pass 2]
- F, `f/check.txt` FAIL `values.max_price={'value': 0.09, 'source': 'project'}`. The F fixture `vasty.toml` sets `max_price = 0.09` under `[defaults]`, which outranks the user file by README line 304. The pass condition cannot be met with this fixture. This is the only FAIL in out/f/verdict.md. [persisted from pass 1]
- G, `g/check.txt` passes "some status or sweep json contains "expired"" on `g/03-status.json`. That file reports `l-0ebcec95`, the box that never became ready. The lease under test shows `expired` in `g/15-status.json` line 8. The verdict holds on either file. [new in pass 2]
- D, out/d/final.md: "The harness blocked a plain `sleep 240` wait, so I polled the `.rc` file with a background until-loop instead." [new in pass 2]
- F, out/f/final.md: "My first background wrapper for the reserve exited at once while vasty kept running, so I added a loop that waited for 02-reserve.rc." [new in pass 2]
- `ledger.log` line 5 `instances=ERR Expecting value: line 1 column 1 (char 0)` at 21:58:52Z, as four boxes were being created. One ledger sample lost. [new in pass 2]
- `/Users/nigel.gilbert/.config/vasty/config.toml` still holds `max_price = 0.08` from `f/06-config-set.json` after wave 2. The C and G fixtures set `max_price = 0.09` and D's vllm profile sets 0.40 (`d/02-config-show.json` `max_price` source `"profile"`), so none of them read it. Pass 1's manager removed the file after the run. [persisted from pass 1]

### Fixed since pass 1

- Silent waits (pass 1 A 03, 15 min; B 02, 3 min 50 s; D 03, stderr empty for 7 min): every create now prints milestones. `a/03-reserve.err`, `b/02-run.err`, `e/06-reserve.err`, `f/02-reserve.err` lines 1 to 4, `f/05-run.err` lines 1 to 4, `d/03-serve.err` lines 1 to 4, `g/04-reserve.err` lines 1 to 4. Also fixed since run 7. The vLLM load phase after "startup done" stays silent (Timing).
- `serve` result without `ttl_remaining_s`, `gpu` or `price_per_hr` (pass 1 D 03, which then ran a status): `d/03-serve.json` lines 7 to 10 carry all three. D ran no status until after release.
- Lease id late from `run --detach` (pass 1 B): `b/02-run.err` line 1 names `l-9dc4e45b` at create, and `b/02-run.json` adds `gpu` and `price_per_hr`.
- Removed-flag hint "Run vasty --help." (pass 1 E): each hint in `e/01-reserve.json` to `e/04-release.json` names the replacement or says "drop it".
- No replacement for `--cached` (pass 1 E): `e/02-status.json` hint "--cached was removed: drop it."
- Attached `run` with no clock (pass 1 F 02): `a/04-run.json` `expires_at: "2026-11-01T22:14:17Z"`, `ttl_remaining_s: 861`; `f/03-run.json` the same.
- `config set` with no path (pass 1 F 09): `f/06-config-set.json` `path: "/Users/nigel.gilbert/.config/vasty/config.toml"`. README line 141 now exempts `config` from `warnings` and `swept`.
- `sync pull` into a missing parent (pass 1 manager gap, C ran `mkdir -p`): `a/out` was born at 16:00:04 during `a/05-sync` (rc 16:00:07) with no mkdir in a/notes.md, and `b/logs` was born at 16:08:23 during `b/07-sync`. README line 82 documents it. Also fixed since run 7.
- README auto-reserve "2 hours" (pass 1 A, D): README line 11 now says "a 30-minute clock" and line 306 names the old 2h. F's auto-reserved `f/05-run` took the project ttl (`ledger.log` line 8 `ttl=900`). D quoted the 30m line and no 2h figure.
- `reachable_at` read as first reachable (pass 1 G): README line 162 defines it as "the last probe that got an answer". `g/05-status.json` to `g/14-status.json` show it advance from 22:28:24Z to 22:33:53Z, and G did not remark on it.
- `expiring_soon` fix that would extend a box meant to expire (pass 1 G 05 to 12): `g/07-status.json` to `g/14-status.json` carry fix "vasty extend l-51a8311e --by 6m". README line 128 limits running fixes to leases the agent "means to keep". G ran no extend and the box expired on its clock.

## Design notes

### A removal that cost an agent something

- One correct way to do each thing. E's `fx/nightly.sh` passed `--until "$(date -u -v+20M +%H:%M)"` (`e/03-extend.json`). Recovery took one `extend --help` read. Keep `--until` removed and fix the hint below.
- One correct way to do each thing. E's script ran `release --all --yes` (`e/04-release.json`). Recovery took one README read for the `--owner "$VASTY_OWNER"` pattern. Keep `--all` removed and fix the hint below.

### A hint or message to change

- Fix the guarantee: point recovery hints at the safest action. Caller G, `reserve --name tick --ttl 6m` on a box Vast never ran (`g/02-reserve.json`). When `details.destroyed` is true, drop "Run vasty status" from the hint and put the last Vast status in the message, for example "Vast still reported it `created` when its 6m clock ran out."
- Fix the guarantee: point recovery hints at the safest action. Caller A, input `--gpu any --max-price 0.045` with project `disk = 16` (`a/02-reserve.json`). List every filter applied in the `no_offers` message, for example `gpu=any disk>=16 cuda>=12.6 under $0.045/hr`.
- Fix the guarantee: point recovery hints at the safest action. Caller E, input `extend ft --until 22:18` (`e/03-extend.json`). Make the hint say `--to` and `--by` take a duration from now, for example "--until was removed: use --by 20m or --to 20m (duration from now)."
- Fix the guarantee: point recovery hints at the safest action. Caller E, input `release --all --yes` (`e/04-release.json`). Make the hint name the README form: `use --owner "$VASTY_OWNER"`.
- Build for the caller in front of you. Caller D, `serve --profile vllm --model Qwen/Qwen2.5-0.5B-Instruct` (`d/03-serve.err`). Add milestones after "startup done" for vLLM launch and for `/v1/models` answering, and list them in README line 94. This was D's first-change vote.
- Code is the record. Caller D (`d/02-config-show.json`). Reword README line 306 so the 30m built-in applies only when no flag, profile, env or config file sets `ttl`.
- Code is the record. Caller B, `run --help` (`b/02-run.json`). Make the `--sync` help line say DIR's contents land in `/workspace`, where the job starts, as README line 82 does.
- Code is the record. Caller A, `run --on r8a-c --sync fx` (`a/04-run.json`). Name `--sync` as allowed with `--on` in README line 78.
- One correct way to do each thing. Callers A, B, D, E, F, G (`a/03-reserve.err`, `d/03-serve.err` line 1). Round the milestone price the way the JSON does: `$0.063/hr`.

### A field to add or drop

- Pass through the provider. Caller G, `status tick2 --verbose` on an expired lease (`g/15-status.json`). Add `destroy_pending` to `expired` rows with the meaning `release` already gives it, so the caller skips the account view (`g/16-status.json`).
- Build for the caller in front of you. Callers B and F and the run 8b check.sh (`b/08-run.json`, `f/03-run.json`). Add `cmd` to attached `run` and `run --detach` JSON, as `release` and `status` jobs already carry it.
- Pass through the provider. Caller F, auto-released `run` (`f/05-run.json`). Add `cost` and `uptime_s` when `released` is true, the same fields single-lease `release` returns.
- One correct way to do each thing. Caller F (`f/08-config-profiles.json`). Add the `source` word `config show` already uses to each profile.

### A deferred item now confirmed by a live caller

- Guards are direct and deterministic. Pass 1 A voted for a boot timeout separate from the TTL after its box burned 15 minutes. Pass 2 G's first `reserve` waited the whole 6m clock on a box Vast held in `loading` and `created` (`g/02-reserve.json`, `ledger.log` lines 25 to 30). A fixed deadline from create, like the existing 5 minutes after `running` (README line 257), would return sooner. The TTL already bounded spend: `g/03-status.json` `cost: 0.0`. The cost is agent time only.
- Guards are direct and deterministic. Pass 1 G voted for `destroyed_at` and `destroyed_by` on expired leases. Pass 2 G asked again (`g/15-status.json` `swept: []`). Vasty holds which layer fired only when its own sweep or follower does the destroy, so the field could name `sweep`, `follower` or `unknown`.
- One correct way to do each thing. Pass 1 F voted for `config show` to list shadowed lower-layer values. Pass 2 F hit it again (`f/06-config-set.json`, `f/07-config-show.json`) and voted for a `shadowed_by` field. Add the shadowed layer and value to `config show`, or a `shadowed_by` field to `config set` output.

### Leave alone

- TTL bounds spend. With no agent attached, C's four 15 minute boxes left the account within 58 s of their clocks (`ledger.log` lines 37 to 39). G's box left within 41 s (lines 39 to 40). The promise held for five boxes nobody released.
- TTL bounds spend. The vastai-made instance 58721087 had no clock and ran from 22:17Z until the manual destroy at 22:36:34Z. Every status showed it as `orphan` with fix "vasty tag i-58721087 --ttl 30m" (`g/01-status.json` lines 97 to 103). Vasty cannot clock a box it did not create, and the warning is the right reach.
- Guards are direct and deterministic. G worried that its own `status` polls might do the destroy, since every networked command sweeps (README line 237). `swept` stayed `[]` in `g/05-status.json` to `g/16-status.json`. Keep the sweep always on.
- Guards are direct and deterministic. B's vote: warn at `run --detach` when the TTL is close to the job's expected runtime. Vasty holds no runtime estimate. The time-based `expiring_with_running_job` warning fired with a runnable fix and B used it (`b/04-status.json`, `b/05-extend.json`).
- One correct way to do each thing. A wait-until-gone verb has one caller, G's test task. G finished with eleven polls (`g/05-status.json` to `g/15-status.json`) and no wrong guess.
- One correct way to do each thing. E's vote: give `release --owner` a default of the current owner (`e/10-release.json`). That adds an optional-value rule to `--owner`. The hint change above covers the caller.
- Stop cutting when a fresh agent would need a long chain. A wanted an auto-reserved `run` that pulls outputs before release. Reserve, run, sync, release is four documented commands (README lines 194 to 200) and A finished in seven (`a/01` to `a/07`).
- Pass through the provider. `uptime_s` from the first `running` sample (README line 162). A, E and F read it as low, and the ledger labels confirm the figures (`a/06-release.json`, `e/10-release.json`, `f/04-release.json`).
- One correct way to do each thing. `totals` stay account-wide under `--owner` (README line 300). A resolved it from `live_mine: 0` (`a/07-status.json`). G resolved `burn_per_hr: 0.0536` beside `live: 0` from README line 270 (`g/16-status.json`).
- One correct way to do each thing. `stop` reports `killed` with the job's exit code (README line 151). D read `exit: 0` as odd and moved on (`d/04-stop.json`).
- One correct way to do each thing. The removed `--no-wait`, `--plain`, `--everyone` and `--cached` cost nothing. Each "drop it" or "use plain vasty status" hint fixed its line on the first try (`e/01-reserve.json`, `e/02-status.json`).

### Harness

- Spawn C in a rerun. Its plan rows went unexercised in pass 2: `--owner` and `--group` selectors, `tag LEASE`, `tag i-ID --ttl` adoption, `release --group` and `extend --to`. G's plain `status` covered the orphan row with `uptime_s: 73` (`g/01-status.json` line 90).
- Pass `-y` to `vastai destroy instance` in manual cleanup. The first try at 22:36Z stopped at the confirmation prompt (out/run.md).
- Point check scripts at the files `--json` actually writes. Error objects go to stdout `.json`, and job output goes to `.err` (`e/check.txt`, `f/check.txt`).
- Match G's `expired` check on the lease from the passing `reserve`. The current check matched the dead first lease (`g/check.txt`, `g/03-status.json`).
- Allow a plain `sleep` in agent briefs or name the `.rc` polling pattern. D and F each built a background wait loop (out/d/final.md, out/f/final.md).
- Drop `max_price` from the F fixture `vasty.toml`, or move it into a profile, so `config show` can report the user value.
- Remove `~/.config/vasty/config.toml` now. It still holds `max_price = 0.08` from `f/06-config-set.json`.
- Plan rows left without a caller in pass 2: profile ttl on an auto-reserved `run` (F used `reserve --profile prep`, label `ttl=720`), `log_tail` tqdm collapse (D ran no status during serve), release cost against a later status for D, and an explicit `sweep --follow` (G never called it).
- The ledger lost one sample to a non-JSON `vastai` reply at 21:58:52Z (`ledger.log` line 5). Retry once on a parse error.

Checked and declined: B at $0.0778 and F 05 at $0.0756 beside $0.063 rentals (no agent hiccup); `e/05-status.json` `pending` rows with every `guard_layers` entry `missing` during create, and the same on the never-booted `g/03-status.json` (expected for a box that never ran the hook); single-lease `release` returning `name`, absent from README line 147 (no agent hit it); bulk `results` shape of `e/10-release.json` (documented at README line 148); `--help` builtin default label (no agent read it); `expiring_soon` "4m left" at `ttl_remaining_s: 195` in `g/09-status.json` (README line 134 rounds up); status latency of 6 to 9 s in g/poll.log (G did not flag it); `d/03-serve.json` `ttl_remaining_s: 807` of 1200 after the vLLM load (D did not flag it); G's plain `status` listing r8c leases and an orphan fix it did not own (`g/01-status.json`, G left them alone); manager samples in `out/manager/` up to `223413-status.json` (they match the agents' own views and the ledger).
