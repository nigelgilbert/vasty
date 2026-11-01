
Run 8 second pass, target opus/medium, seven scenarios (A to G, C rerun as r8cc), run dir `/private/tmp/vasty-live-8b`.

## Friction

File paths are under `/private/tmp/vasty-live-8b/out/`. `p1` marks pass 1 files under `/private/tmp/vasty-live-8/out/`. Run 7 is `/private/tmp/vasty-live-7/out/report.md`. Verdicts: A, B, C, D, E and G PASS. F FAIL on its fixture (f/verdict.md). The full write-up is in out/report.md.

### Hints

- G, g/02-reserve.json lines 2 to 7, `"message": "Lease l-0ebcec95 ended before it became ready."`, `"hint": "Run vasty status l-0ebcec95, then vasty reserve again."`, `"destroyed": true`. The status G ran (g/03-status.json) showed only `expired`, `running_at: null` and every guard layer `missing`. G then retried. One extra command. [persisted from pass 1, same message and hint in p1 a/03-reserve.json; fixed since pass 1 for `destroyed: false`]
- A, a/02-reserve.json lines 3 to 4, `"message": "No offers match cuda>=12.6 under $0.045/hr."`, `"hint": "Try a higher --max-price, or a lower --cuda."`. The message names neither `gpu=any` nor `disk = 16`. One retry (a/03-reserve.json). [persisted from pass 1; persisted from run 7 for the unnamed filter; fixed since run 7 for the price suggestion]
- E, e/03-extend.json lines 3 to 4, `"hint": "--until was removed: use --by or --to."`. E read `extend --help` to learn `--to` is a duration from now. One help read. [persisted from pass 1]
- E, e/04-release.json lines 3 to 4, `"hint": "--all was removed: use --owner O. --yes was removed: drop it."`. E read README line 55 for `--owner "$VASTY_OWNER"`. One README read. [persisted from pass 1]

### Help and docs

- D, README line 306 "An auto-reserved `run` or `serve` without `--ttl` gets the 30m built-in" against line 304. D ran d/02-config-show.json and saw `ttl` `"20m"` from `"profile"`. One command. [persisted from pass 1 in a new form; fixed since run 7 for serve ignoring profile ttl, ledger line 25 `ttl=1200`]
- C, c/03-tag.json and c/04-tag.json, plus a `tag --help` read. out/c/final.md: "`tag` takes a single LEASE with no `--group` selector". One extra call. [new in pass 2; p1 c/04-tag and c/05-tag made the same calls without remark]
- C, c/02-extend.json after an `extend --help` read. out/c/final.md: "The README's `--to 2h` doesn't say it is relative to now." README line 64. [persisted from pass 1]
- B, `run --help` reads "push DIR to the box before the command". B read README line 82 before b/02-run.json. [persisted from pass 1]
- A, out/a/final.md: "I had to guess whether `--gpu any` was needed." README line 308 settled it. [new in pass 2; fixed since run 7 for the missing wildcard]
- A, a/07-status.json `burn_per_hr: 0.2037`, `live: 3` under `--owner r8a`. A read README line 300. [persisted from pass 1]
- B, out/b/final.md: "I checked `sync --help` for argument order". [persisted from pass 1]
- A, a/04-run.rc `0` on `run --on r8a-c --sync fx`. README line 78 does not say whether `--sync` counts as a creation flag. [new in pass 2]
- B, out/b/final.md: "I guessed `python3` over `python`". [persisted from pass 1]
- D, d/02-config-show.json lines 19 to 21 `"disk": {"value": 16, "source": "project"}`, doubted and left alone. [persisted from pass 1]
- C, c/05-release.json `results` with no `already_absent`; README line 148 lists it. [new in pass 2]
- B, out/b/final.md: "Neither the README nor `--help` says when the clock starts." This disagrees with README line 257 and with the ledger (see Disagreements). [persisted from pass 1]

### Output shape

- G, g/15-status.json line 8 `"state": "expired"` with no `destroy_pending`. G ran g/16-status.json to confirm the box left. One command. [persisted from pass 1, p1 g/14-status]
- B, b/03-status.json run 22 s after b/02-run.json to see job state. Not flagged. One command. [persisted from pass 1; persisted from run 7 item 8 for the follow-up status; fixed since run 7 for gpu and price]
- F, f/07-config-show.json lines 15 to 17 `"max_price": {"value": 0.09, "source": "project"}` after f/06-config-set.json wrote 0.08. No shadow notice. [persisted from pass 1]
- B, F: no `cmd` in attached `run` JSON (b/08-run.json, f/03-run.json). It first shows in b/09-release.json lines 15 to 16. [new in pass 2]
- B, E, F: job stdout lands in `.err`: b/08-run.err line 1 "eval ok: final loss 0.0417", e/09-run.err "smoke ok", f/03-run.err lines 4 to 5. README line 94. [persisted from pass 1; persisted from run 7]
- F, f/05-run.json `"released": true` with no `cost` or `uptime_s`. [new in pass 2]
- C, c/09-release.json `"uptime_s": 7` after c/01-status.json line 90 `"uptime_s": 94`. Adoption restarts uptime. [persisted from pass 1]
- C, F: release cost below a later reading: c/09-release.json `"cost": 0.0` against c/11-status.json `"cost": 0.002`; f/04-release.json `"cost": 0.0`. README line 275. [persisted from pass 1; persisted from run 7]
- C, G: `live` leaves out orphans and `burn_per_hr` counts them: c/01-status.json lines 109 to 111 `burn_per_hr: 0.3453`, `live: 4`; g/16-status.json `burn_per_hr: 0.0536`, `live: 0`. [new in pass 2]
- A, E, F: `uptime_s` read as low: a/06-release.json 62, e/10-release.json `results[0].uptime_s` 69, f/04-release.json 46. The files match README line 162. [new in pass 2]
- A, B, D, E, F, G: milestone line 1 prints the raw price, e.g. a/03-reserve.err "RTX 3060 at $0.06296296296296297/hr" and d/03-serve.err "RTX 5060 Ti at $0.1748148148148148/hr". [new in pass 2]
- C, c/08-tag.json lines 3 to 10 return `l-eeb272a3` with no `i-58724589`. [new in pass 2 as friction]
- G, g/15-status.json `"swept": []` and no field naming the destroyer. [persisted from pass 1]
- D, d/04-stop.json lines 5 to 6 `"state": "killed"`, `"exit": 0`. README line 151. [new in pass 2]
- E, e/01-reserve.rc to e/04-release.rc all `1`; E expected 2. README line 126. [new in pass 2]
- E, F: `duration_s: 0` in e/09-run.json, f/03-run.json and f/05-run.json. [persisted from pass 1; persisted from run 7]
- F, f/08-config-profiles.json `profiles.prep` with no source. [persisted from pass 1]
- E, e/11-status.json `leases: []` under `--owner r8e` after release. [persisted from pass 1]

### Timing

- D, d/03-serve.err line 4 "vasty: l-947a5deb startup done" at 22:19:24Z, then silence until d/03-serve.rc at 22:25:48Z: 6m24s. [new in pass 2 for this shape; fixed since pass 1 and run 7 for the boot phase; persisted from pass 1 and run 7 for the vLLM phase]
- B, b/04-status.json `"message": "4m left, j-1 running"`, `"fix": "vasty extend l-9dc4e45b --by 10m"`. B ran it (b/05-extend.json), then waited 125 s with no completion signal before b/06-status.json. [persisted from pass 1; persisted from run 7 for the margin; fixed since run 7 because the warning fired]
- G, g/05-status.json to g/15-status.json: eleven polls (g/poll.log). out/g/final.md: "there is no way to wait on a lease until it is gone". [persisted from pass 1]

### Provider

- G, g/02-reserve.err line 1 "created" and no further milestone. Vast held 58721333 in `loading` (ledger lines 25 to 26) and `created` (lines 27 to 30). Reserve blocked for 6m10s, until `created + ttl` (g/03-status.json `expires_at` 22:24:45Z). [persisted from pass 1 for a reserve held the whole TTL by a box that never became ready, p1 a/03 15m07s; new in pass 2 for a box Vast never ran]
- F, box 2: f/04-release.rc 16:01:19 to f/05-run.rc 16:04:36 local, `loading` at ledger line 8. Not flagged. [new in pass 2]
- G, retry box 58722223: `loading` at ledger lines 32 to 33, running at line 34; g/04-reserve.json returned about 3 min after start. Not flagged. [new in pass 2]

### Harness

- C, wave 2 never spawned the agent. out/c-setup-1/ boxes expired unattended (ledger lines 37 to 39). C reran under r8cc (run.md lines 46 to 60). [new in pass 2]
- C, c/BRIEF.md exported `VASTY_OWNER=r8c` after setup moved to r8cc (out/c-brief-before-owner-fix.md line 13). [new in pass 2]
- B, follow-up sent about 5.5 min after Task 1 instead of 4 (run.md line 24; b/04-status.err 22:05:35Z). [new in pass 2]
- E, e/check.txt four FAIL "no line contains it": check.sh searched `.err`, and the errors are in e/01-reserve.json to e/04-release.json lines 3 to 4. [new in pass 2]
- F, f/check.txt FAIL for `prep.ok` and `extra.ok`: check.sh searched run `.json`, and the lines are in f/03-run.err lines 4 to 5 and f/05-run.err lines 8 to 9. [new in pass 2]
- F, f/check.txt FAIL `values.max_price={'value': 0.09, 'source': 'project'}`: the fixture vasty.toml outranks the user file (README line 304). [persisted from pass 1]
- B, b/check.txt line 3 passes `eval.py` on `08-run.json:lease`, which names no command. [new in pass 2]
- C, c/check.txt line 5 passes adoption on 03-tag.json, a rename. The adoption is c/08-tag.json. [new in pass 2]
- G, g/check.txt line 2 passes `expired` on g/03-status.json, the dead first lease. The lease under test is in g/15-status.json line 8. [new in pass 2]
- C, the pass line wants keep in the last ledger line; cleanup released keep at 22:49:23Z (run.md line 72). The verdict used line 54. [new in pass 2]
- D, out/d/final.md: "The harness blocked a plain `sleep 240` wait". F, out/f/final.md: "My first background wrapper for the reserve exited at once". [new in pass 2]
- Manager, the first `vastai destroy instance 58721087` without `-y` aborted at the prompt (run.md line 71). [new in pass 2]
- ledger.log line 5 `instances=ERR Expecting value: line 1 column 1 (char 0)`. [new in pass 2]
- `~/.config/vasty/config.toml` held `max_price = 0.08` from f/06-config-set.json until 22:55:23Z (run.md last line). [persisted from pass 1]
- `ledger.sh` and `manager.sh` still ran after the run ended (pids 28459 and 28460 at 22:59Z). [new in pass 2]

### Fixed since pass 1

- Silent waits during box boot (p1 A 03 15 min, p1 B 02 3m50s, p1 D 03 7 min, all with empty `.err`). Exercised: a/03-reserve.err, b/02-run.err, e/06-reserve.err, f/02-reserve.err, f/05-run.err, d/03-serve.err and g/04-reserve.err each carry four milestone lines.
- `serve` lacked `ttl_remaining_s`, `gpu` and `price_per_hr` (p1 D ran 04-status). Exercised: d/03-serve.json lines 7 to 10.
- Lease id late from `run --detach` (p1 B). Exercised: b/02-run.err line 1 names `l-9dc4e45b` at create.
- Removed-flag hint "Run vasty --help." (p1 E). Exercised: e/01-reserve.json to e/04-release.json `hint`.
- No replacement for `--cached` (p1 E). Exercised: e/02-status.json "--cached was removed: drop it."
- Attached `run` with no clock (p1 F 02). Exercised: a/04-run.json `expires_at`, `ttl_remaining_s: 861`; f/03-run.json.
- `config set` with no path (p1 f/09-config.json). Exercised: f/06-config-set.json `path`.
- `sync pull` into a missing parent (p1 C ran `mkdir -p`). Exercised: a/out born 16:00:04 during a/05-sync, b/logs born 16:08:23 during b/07-sync, no mkdir in a/notes.md or b/notes.md; README line 82.
- README "2 hours" for auto-reserve (p1 A, D). Exercised: README line 21 now says 30 minutes; D quoted line 306 and no 2h figure.
- `destroyed: false` on a destroyed box (p1 a/03-reserve.json). Exercised: g/02-reserve.json `"destroyed": true`.
- `expiring_soon` fix applied to a box meant to expire (p1 G). Exercised: g/07-status.json to g/14-status.json still carry "vasty extend l-51a8311e --by 6m"; README line 128 now limits fixes to leases the agent "means to keep", and G ran none.
- Per-owner burn (p1 C vote). Exercised: c/01-status.json line 110 `burn_per_hr_mine: 0.2839`.
- `box_unreachable` warning on `tag` (p1 c/05-tag.json) and the SSH key stderr line on adoption (p1 c/08-tag.err). Exercised: c/03-tag.json, c/04-tag.json and c/08-tag.json carry `warnings: []`; c/08-tag.err is empty. Fixed by non-recurrence only.
- Orphan rows with no uptime (run 7 item 12). Exercised: c/01-status.json line 90 `uptime_s: 94`.
- Orphan cleanup blocked by the permission classifier (run 7 C). Exercised: c/08-tag.rc and c/09-release.rc are 0, and ledger line 54 has 58724589 gone.

### Disagreements with the files

- out/a/final.md and a/notes.md say the reserve took "about 3 minutes". a/02-reserve.rc 15:58:42 to a/03-reserve.rc 15:59:33 local, created 21:58:49Z: about 51 s.
- out/b/final.md says no doc gives the clock start and that it "starts at reserve". README line 257 gives it. Ledger line 6 puts the clock start at 21:59:10Z, 30 s after create and 3 s after `running_at` 21:59:07Z (e/07-status.json).
- out/c/final.md "about 5 minutes": the commands span 1m42s (c/01-status.err 22:46:53Z to c/11-status.rc 22:48:35Z).
- c/notes.md "several minutes before adoption": 74 s (c/01-status.json 22:46:56Z, c/08-tag.json 22:48:10Z).
- out/e/final.md "rented for several minutes": created 21:59:17Z (ledger line 6), released 22:01:01Z (e/10-release.rc).
- out/f/final.md "running from about 22:00:26 to 22:01:40": f/04-release.rc is 22:01:19Z. f/notes.md "~1.5 min after startup" is 53 s on the same files.
- out/g/final.md "Reserve eats most of a short clock (04)": g/04-reserve.json spent 7 s of 360, and the clock started at `running_at` 22:28:09Z (g/05-status.json).
- out/g/final.md puts poll 16 at "22:34:50 or so". g/16-status.json mtime is 22:34:39Z.
- The verdicts agree with the raw files. check.txt disagrees with the verdict for B, C, E, F and G as listed under Harness.

## Design notes

### A removal that cost an agent something

- One correct way to do each thing. E, `extend ft --until 22:18` (e/03-extend.json). One help read. Keep `--until` removed and fix the hint.
- One correct way to do each thing. E, `release --all --yes` (e/04-release.json). One README read. Keep `--all` removed and fix the hint.
- One correct way to do each thing. C, `tag b1 --name arch-1 --group archive` and `tag b2 ...` (c/03-tag.json, c/04-tag.json). Each box takes its own name, so a selector still needs two calls, and a selector with `--name` adds a combination rule. Keep `tag LEASE`.

### A hint or message to change

- Fix the guarantee. G, `reserve --name tick --ttl 6m` (g/02-reserve.json). With `destroyed: true`, drop "Run vasty status" and name the last Vast status in the message. README line 183 says `box_unreachable` means no SSH answer, and this box never reached `running`.
- Fix the guarantee. A, `--gpu any --max-price 0.045` with `disk = 16` (a/02-reserve.json). List every applied filter, as README line 121 does.
- Fix the guarantee. E, `extend --until` (e/03-extend.json). Say `--by` and `--to` take a duration from now.
- Fix the guarantee. E, `release --all` (e/04-release.json). Say `use --owner "$VASTY_OWNER"`.
- Build for the caller in front of you. D, `serve --profile vllm` (d/03-serve.err). Add milestones for vLLM launch and `/v1/models` answering.
- Code is the record. D (d/02-config-show.json). Reword README line 306 so the 30m built-in applies when no layer sets `ttl`.
- Code is the record. B (b/02-run.json). Make the `run --help` `--sync` line say DIR's contents land in `/workspace`.
- Code is the record. A (a/04-run.json). Name `--sync` as allowed with `--on` in README line 78.
- Code is the record. C and E (c/02-extend.json, e/03-extend.json). Say in README line 64 that `--to` is a duration from now.
- Code is the record. C and G (c/01-status.json, g/16-status.json). Say in README line 300 that `live` leaves out orphans.
- Code is the record. C (c/05-release.json). Align README line 148 on `already_absent` with line 147.
- Code is the record. C (c/09-release.json). Say in README line 162 that adoption restarts `uptime_s`.
- One correct way to do each thing. A, B, D, E, F, G (a/03-reserve.err line 1). Round the milestone price as the JSON does.

### A field to add or drop

- Pass through the provider. G (g/15-status.json). Add `destroy_pending` to `expired` rows.
- Build for the caller in front of you. B and F (b/08-run.json, f/03-run.json). Add `cmd` to attached `run` JSON.
- Pass through the provider. F (f/05-run.json). Add `cost` and `uptime_s` when `released` is true.
- One correct way to do each thing. F (f/08-config-profiles.json). Add `source` to each profile.

### A deferred item now confirmed by a live caller

- Guards are direct and deterministic. Boot timeout (p1 A vote). Commit 059bd21 gives up 5 min after `running`. G's box never reached `running` (ledger lines 25 to 30), so reserve waited the whole clock (g/02-reserve.json). Spend stayed bounded (g/03-status.json `cost: 0.0`).
- Guards are direct and deterministic. `destroyed_at` and `destroyed_by` (p1 G vote). Commit 059bd21's subject reads "drop destroyed_at and destroyed_by". G asked again (g/15-status.json `swept: []`). It cost no command.
- One correct way to do each thing. Shadowed config values (p1 F vote). F hit it again and voted for `shadowed_by` (f/06-config-set.json, f/07-config-show.json).

### Leave alone

- TTL bounds spend. Five unreleased boxes left within 58 s of their clocks (ledger lines 37 to 40).
- TTL bounds spend. The clockless vastai instance 58721087 showed as `orphan` with fix "vasty tag i-58721087 --ttl 30m" (g/01-status.json lines 97 to 103).
- Guards are direct and deterministic. `swept` stayed `[]` through G's polls (g/05-status.json to g/16-status.json). Keep the sweep always on.
- Guards are direct and deterministic. B's runtime-aware warning vote. The time-based warning fired and B used its fix (b/04-status.json).
- One correct way to do each thing. A wait verb has one test caller. G finished with eleven polls.
- One correct way to do each thing. E's `release --owner` default vote. It adds an optional-value rule, and the hint change covers the caller.
- Stop cutting when a fresh agent would need a long chain. A finished reserve, run, sync and release in seven commands (a/01 to a/07).
- Pass through the provider. `uptime_s` from the first `running` sample matches the labels (a/06-release.json, e/10-release.json, f/04-release.json).
- One correct way to do each thing. `totals` stay account-wide under `--owner` (a/07-status.json).
- One correct way to do each thing. `stop` reports `killed` with the job's exit code (d/04-stop.json).
- One correct way to do each thing. The `--no-wait`, `--plain`, `--everyone` and `--cached` removals cost nothing (e/01-reserve.json, e/02-status.json).
- Fix the guarantee. The orphan fix led C to adopt and release in two commands (c/08-tag.json, c/09-release.json).
- Build for the caller in front of you. The missing `i-` id on `tag` cost C nothing. `status --verbose` has `instance_id` (manager/224829-status.json line 26).
- One correct way to do each thing. `release --group` and `extend --to` worked in one call each (c/05-release.json, c/02-extend.json).

### Harness

- Spawn each wave 2 agent in the step that sees its setup DONE (run.md line 34).
- Read the owner name from one place in setup, brief and check scripts (out/c-brief-before-owner-fix.md line 13).
- Send follow-ups on schedule. B's went out at 5.5 min (run.md line 24).
- Save each command line as `NN-<verb>.cmd`, so checks can test `--group` and `i-` arguments (c/check.txt line 5).
- Point check scripts at the files `--json` writes: errors in stdout `.json`, job output in `.err` (e/check.txt, f/check.txt, b/check.txt line 3).
- Match G's `expired` check on the lease from the passing `reserve` (g/check.txt line 2).
- Drop `max_price` from the F fixture `[defaults]`, so `config show` can report the user value (f/verdict.md).
- Check C's last-ledger condition before the end-of-phase cleanup (c/verdict.md, run.md line 72).
- Allow a plain `sleep` in agent briefs or name the `.rc` polling pattern (out/d/final.md, out/f/final.md).
- Pass `-y` to `vastai destroy instance` (run.md line 71).
- Retry the ledger sample once on a parse error (ledger.log line 5).
- Stop `ledger.sh` and `manager.sh` at run end (pids 28459, 28460).
- Plan rows left without a caller: profile ttl on an auto-reserved `run`, `log_tail` tqdm collapse, D's release cost against a later status, explicit `sweep --follow`, `--help` builtin default labels, and `status --group`, `extend --group` and LEASE plus selector rejection (run.md lines 27 and 65).

Checked and declined: B at $0.0778 and F box 2 at $0.0756 (no hiccup); `pending` rows with every guard layer `missing` during create (e/05-status.json); single-lease `release` returning `name` (no agent hit it); `expiring_soon` "5m left" at 268 s (g/07-status.json, README line 134 rounds up); status latency of 6 to 9 s (g/poll.log, not flagged); `d/03-serve.json` `ttl_remaining_s: 807` (not flagged); `c/08-tag.json` `ttl_remaining_s: 602` (not flagged); `c/06-release.json` j-1 `killed` with `exit: null` (README line 151); `log_tail: []` on a released lease (c/11-status.json, README line 150); `balance: 0.0` beside `credit` (no pass 2 cost); manager samples, which match the agents' views and the ledger.