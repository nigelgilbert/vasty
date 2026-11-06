# Live run 8 findings

Pass 3 of the plan in [live-run-8.md](live-run-8.md). Raw material is under `/private/tmp/vasty-live-8c`. Paths below are relative to its `out/` directory, except `<letter>/notes.md`, `<letter>/vasty.toml` and `<letter>/fx/` under the run root. "Run 7" is `/private/tmp/vasty-live-7/out/report.md`. "Pass 2" is `/private/tmp/vasty-live-8b/out/report.md`, and its items are that report's friction numbers. Branch `feature/reduce-api-surface` at `b1eec1b` (`run.md` line 5). Times are UTC. File mtimes read 6 h behind UTC.

Verdicts, from each `<letter>/verdict.md`:

- A (r8ca): PASS. 7 commands. Release cost 0.001 (`a/06-release.json` line 5).
- B (r8cb): PASS. 10 commands. Release cost 0.012 (`b/09-release.json` line 5).
- C (r8cc): PASS. 9 commands. Release cost 0.042 over four leases (`c/05-release.json` lines 9 and 19, `c/06-release.json` line 5, `c/08-release.json` line 5). The orchestrator released keep at 0.013 (`c-cleanup-release.json` line 5).
- D (r8cd): PASS. 5 commands. Release cost 0.027 (`d/04-release.json` line 5).
- E (r8ce): FAIL. No `.json` names `--all` (`e/verdict.md` line 6). 9 commands. Release cost 0.002 (`e/08-release.json` line 9).
- F (r8cf): PASS. 9 commands. Release cost 0.001, plus 0.002 for the auto-released box (`f/09-status.json` line 13).
- G (r8cg): PASS. 12 commands. No release. Last status cost 0.006 (`g/11-status.json` line 13).

Spend: credit 18.0802 at `ledger.log` line 1 to 17.9216 at line 43, flat through line 48. Total $0.1587. Wave 1 $0.0332 to line 26, wave 2 $0.1255 (`run.md` lines 31 and 60).

## Friction

### Hints

- A, `a/02-reserve.json` lines 3 to 4: "No offers match disk>=16GB cuda>=12.6 under $0.045/hr." with hint "Try a higher --max-price, a lower --disk, or a lower --cuda." A wanted the cheapest matching price in `details` (`a/final.md` lines 26 and 32). Cost: the task's planned retry. Run 7: fixed since item 1 for the over-cap price and the unnamed filter; persisted for run 7 A's cheapest-price vote. Pass 2: fixed since item 4, whose message left out `disk`.
- E, `e/05-extend.json` line 4: "--until was removed: use --by D to add D to the clock, or --to D to end it D from now." E needed no help read. E picked `--by 20m` from the task wording, and the old line matched `--to 20m` (`e/final.md` lines 20 and 37). Run 7: new in run 8. Pass 2: fixed since item 10, whose hint cost a help read.
- B, `b/04-status.json` line 46 `"warnings": []` at `ttl_remaining_s: 311` (line 16) with j-1 running at `duration_s: 274` (line 24). B computed the finish from the epoch rate, extended (`b/05-extend.json`), and waited 3m44s to a computed time before `b/06-status.json` (`b/05-extend.rc` 00:30:32Z, `b/06-status.rc` 00:34:16Z; `b/final.md` lines 53 to 54). Cost one blind wait. Run 7: persisted from item 7. Pass 2: persisted from item 3, where the warning fired at 214 s.
- D, `d/02-serve.err` line 5: "vllm started as j-1; polling /v1/models, up to 30m." The lease clock was 20m (`ledger.log` line 30 `ttl=1200`). D read the 30m as a deadline past the clock (`d/final.md` line 25). No command cost. Run 7: new in run 8. Pass 2: new.
- C, `c/03-tag.json` lines 13 to 17: `expiring_soon` "5m left" with fix `vasty extend l-9e2ef07c --by 15m`, on a lease C released two commands later. C ignored it (`c/notes.md` line 8, `c/final.md` line 32). No command cost. Run 7: new in run 8. Pass 2: new.
- G, `g/10-status.json` line 46 "1m left" at `ttl_remaining_s: 34` (line 16). README line 141 documents the round up (`g/final.md` line 29). No command cost. Run 7: new in run 8. Pass 2: new.

### Help and docs

- E, `release --all --yes` had no replacement on record because the classifier blocked it (Harness). E read `--help` on five verbs and grepped the README to reach `release --owner "$VASTY_OWNER"` (`e/final.md` lines 21 and 35, README lines 55 and 99). Run 7: new in run 8. Pass 2: pass 2's E got the hint "--all was removed: use --owner O." (pass 2 `e/04-release.json`).
- D, `d/final.md` line 27: help does not say `url` ends in `/v1` or that `api_key` goes as a Bearer token. D re-read README lines 223 and 235. One README read. Run 7: new in run 8. Pass 2: new.
- D, `d/final.md` line 24: `serve --help` reads "builtin default: 30m" and the profile sets 20m. D read `d/vasty.toml` for its clock. No help output is saved under `out/`. One file read. Run 7: persisted from item 2. Pass 2: persisted from item 9, where D ran `config show` for it.
- C, `c/final.md` line 34: C read `tag --help` and `extend --help`, and `extend --group hold --to 30m` worked first try. `c/02-extend.json` line 8 `expires_at` 01:24:37Z is 30 min after the call. README line 87 defines `--to`. Two help reads. Run 7: new in run 8. Pass 2: fixed since item 12.
- B, `b/final.md` Task 1 lines 19 and 24: B read boot as spent on the 10 minute clock. `b/02-run.json` line 8 `ttl_remaining_s: 586` shows 14 s spent. README line 264 says the clock starts at boot. No command cost. Run 7: new in run 8. Pass 2: persisted from Claims versus files, B.
- B, `b/final.md` Task 1 line 20: README examples use `python train.py`, and B guessed `python3`. Run 7: new in run 8. Pass 2: persisted from item 18.
- F, `f/02-config-show.json` lines 15 to 22 give `source` as `user` and `project` with no path. `f/03-config-profiles.json` lines 3 to 6 list `prep` with no source (`f/final.md` line 41). F mapped labels through README line 311. Run 7: new in run 8. Pass 2: persisted from item 35.
- C, `c/01-status.json` lines 196 to 198: `burn_per_hr: 0.3407`, `burn_per_hr_mine: 0.2815`, `live: 4` beside five rows. C matched the orphan's 0.0593 by hand (`c/final.md` line 31). README line 277 says `burn_per_hr` counts orphans. README line 307 is silent on `live`. `manager/004557-status.json` line 264 reads `live: 6` beside six leases, two `pending`, and one orphan. Run 7: fixed since item 3 for the orphan row. Pass 2: persisted from item 26.
- C, `c/05-release.json` lines 3 to 22: bulk entries carry no `already_absent`. README line 155 lists it among the added fields. Commit `49f00e7` names `already_absent` in its subject. C did not flag it. Run 7: new in run 8. Pass 2: persisted from item 30.
- E, `e/02-reserve.json` lines 17 to 21 open ports 8000 and 8080 with no `--ports` (`e/final.md` line 38). `f/02-config-show.json` lines 47 to 50 report `ports` `[]` from `default`. README line 117 shows the same ports in an example with no source. Run 7: new in run 8. Pass 2: new.
- E, `e/01-reserve.rc`, `e/03-status.rc` and `e/05-extend.rc` read `1`, and E expected 2 (`e/final.md` line 36). README line 133 gives 1. Run 7: new in run 8. Pass 2: persisted from item 33.

### Output shape

- F, `f/05-run.json` lines 6 to 8: `"released": true` with null clock fields and no `cost` or `uptime_s`. F passed `--name prep1` in `f/06-run.cmd` to read the profile clock, which added `f/07-release.json`, and ran `f/09-status.json` for box 1's cost (`f/final.md` lines 36 to 37). README line 159 documents the null clock. Cost two commands. Run 7: new in run 8. Pass 2: persisted from item 23.
- G, `g/11-status.json` line 8 `"state": "expired"`, line 51 `"swept": []`, and `verbose` lines 20 to 38 without `actual_status`. Nothing names the destroying layer or says whether Vast still lists the box (`g/final.md` lines 26 to 27). G ran `g/12-status.json` to confirm. Cost one command. Run 7: new in run 8. Pass 2: persisted from items 7 and 31.
- D, E: `destroy_pending: true` on release led to a confirming status. `d/04-release.json` line 15 then `d/05-status.json` (`d/final.md` line 28). `e/08-release.json` line 19 then `e/09-status.json` (`e/final.md` line 40). One command each. Run 7: new in run 8. Pass 2: persisted from item 36.
- G, `g/12-status.json` line 2 `"leases": []` under `--owner r8cg` after expiry. `g/11-status.json` shows the lease by name. README line 307 documents it (`g/final.md` line 28). Run 7: new in run 8. Pass 2: persisted from item 36.
- D, G: plain `status` lists other owners' rows (`d/01-status.json` lines 4 to 80, `g/01-status.json` lines 4 to 80). G filtered by eye until `--owner` in `g/12-status.cmd` (`g/final.md` line 30). README line 307 defines the account view. No command cost. Run 7: new in run 8. Pass 2: new.
- C, `c/08-release.json` lines 4 to 5 `"uptime_s": 13`, `"cost": 0.009` on the adopted orphan, which read `uptime_s: 605` at `c/01-status.json` line 170. `cost` keeps the instance history and `uptime_s` restarts at the tag. C read README line 169 as promising Vast's `start_date` (`c/notes.md` line 18, `c/final.md` lines 33 and 37). Run 7: fixed since item 12 for orphan `uptime_s`. Pass 2: persisted from item 24.
- C, `c/07-tag.json` lines 4 to 9 return `l-b0b179f2` with no field naming `i-58740864`. C linked them by command order (`c/notes.md` lines 15 to 16). Run 7: new in run 8. Pass 2: persisted from item 29.
- D, `d/02-serve.json` lines 2 to 12 carry no `ttl` or its source. D voted to echo both (`d/final.md` line 30). README line 161 matches the output. Run 7: new in run 8. Pass 2: new.
- D, `d/03-stop.json` lines 5 to 6 `"state": "killed"`, `"exit": 0` (`d/final.md` line 26). README line 158 documents it. Run 7: new in run 8. Pass 2: persisted from item 32.
- B: release and status cost read below price times uptime. `b/09-release.json` line 5 `0.012` at `uptime_s: 569`, where $0.0818/hr gives $0.0129 (`b/final.md` line 34). `b/03-status.json` line 13 `0.0`, `b/04-status.json` line 13 `0.006` (`b/final.md` line 55). Release and status figures across the run, keep's cleanup included, sum to $0.106 against `charges_today: 0.155` at `manager/010034-status.json`. README line 282 documents arrears. Run 7: persisted from item 4. Pass 2: persisted from item 25.
- E, F read `uptime_s` as low: `e/08-release.json` line 8 `122`, `f/07-release.json` line 4 `32`, `f/09-status.json` line 14 `18` (`e/final.md` line 39, `f/final.md` line 39). Each matches README line 169 (`f/verdict.md` lines 17 to 18). Run 7: new in run 8. Pass 2: persisted from item 27.
- A, B, E, F: `duration_s: 0` for sub-second jobs. `a/04-run.json` line 5 against `"elapsed_s": 0.17` in `a/04-run.err` line 1, `b/09-release.json` line 19, `e/08-release.json` line 16, `f/07-release.json` line 12. Run 7: persisted from item 13. Pass 2: persisted from item 34.
- A, B, E, F: job stdout lands in `.err` under `--json`: `a/04-run.err` line 1, `b/08-run.err` line 1, `e/07-run.err` line 1, `f/05-run.err` lines 5 to 9. README line 101 documents it. Run 7: persisted from item 13. Pass 2: persisted from item 22.
- F, `f/09-status.json` line 27 `"log_tail": []` on released box 1, whose job printed five lines (`f/05-run.err` lines 5 to 9, `f/final.md` line 40). Run 7: persisted from item 13. Pass 2: absent from the report.
- B ran `b/03-status.json` 19 s after `b/02-run.json` (rc mtimes 00:25:36Z and 00:25:55Z) for `busy`, job state and `log_tail`. `b/02-run.json` lines 4 to 8 carry `gpu`, `price_per_hr` and `ttl_remaining_s`. B did not flag it. Run 7: fixed since item 8 for the fields. Pass 2: persisted from item 8.
- D, `d/02-serve.err` lines 5 to 6 add "vllm started as j-1" and "/v1/models answers". Run 7: fixed since item 9. Pass 2: fixed since item 2.
- A, B, D, E, F, G: the created milestone prints the rounded price, such as `a/03-reserve.err` line 1 "$0.063/hr" and `d/02-serve.err` line 1 "$0.1748/hr". Run 7: new in run 8. Pass 2: fixed since item 28.
- B, `b/07-sync.json` lines 3 to 5: `sync pull` created `./logs/` (`b/final.md` line 56). Run 7: fixed since item 10. Pass 2: not recorded there.

### Timing

- Create to clock start, from labels and `expires_at`: A 42 s, E 23 s, F box 1 22 s, F prep1 17 s, D 23 s, G 27 s (`ledger.log` lines 6, 7 and 30; `a/03-reserve.json` line 12; `e/04-status.json` lines 44 and 81; `f/06-run.json` line 7; `g/11-status.json` line 36). B 3m32s: created 00:21:49Z, clock start 00:25:21Z (`b/02-run.json` line 7 less 10m). B planned for a long boot and did not flag it (`b/notes.md` line 5). Run 7: new in run 8; run 7 boots ran 44 s to 2 min. Pass 2: persisted from item 37.
- G's reserve returned in 44 s with `ttl_remaining_s: 354` (`g/02-reserve.cmd` 00:45:44Z, `g/02-reserve.rc` 00:46:28Z, `g/02-reserve.json` line 13). Run 7: new in run 8. Pass 2: fixed since item 1 for this caller; no box failed to run this pass.
- D's serve ran 7m07s (`d/02-serve.cmd` 00:45:45Z to `d/02-serve.rc` 00:52:52Z). `d/02-serve.json` line 10 `ttl_remaining_s: 808`, so boot and vLLM load spent 392 s of 1200 s (`d/final.md` line 23). Run 7: persisted from the 7 min manager note. Pass 2: persisted from its 6m24s vLLM phase.
- G saw `expired` at `g/11-status.json` (rc 00:52:37Z), 15 s after the 00:52:22Z clock. `manager/005218-status.json` line 127 shows t6 at `ttl_remaining_s: 3`. `ledger.log` line 36 (00:52:55Z) drops 58741098. G polled eight times from a background loop (`g/04` to `g/11`, `g/final.md` line 31). Run 7: new in run 8. Pass 2: persisted from item 5; pass 2 saw `expired` 24 s after the clock.

### Provider

- B's 58738027 shows status `None` at `ledger.log` line 6, `loading` at lines 7 to 9, `running` from line 10. Other owners saw it `pending` with every guard layer `missing` (`e/04-status.json` lines 86 to 116). Run 7: new in run 8. Pass 2: persisted from item 37.
- The vastai-made 58740864 sat `loading` at `ledger.log` lines 28 to 29 and ran from line 30. The four vasty setup boxes ran by line 29. No create failed (`c-setup/05-orphan-create.json` line 4). `ledger.log` holds no ERR line. Run 7: new in run 8. Pass 2: persisted from its note on slower vastai-made orphans.

### Harness

See Design notes, Harness.

## Design notes

### A removal that cost an agent something

- One correct way to do each thing. Caller E, `extend ft --until 00:42` (`e/05-extend.cmd`). Cost one rc 1 run and a choice between `--by` and `--to`, which the hint explains. Keep `--until` removed.
- One correct way to do each thing. Caller E, `release --all --yes` (`e/fx/nightly.sh` line 8). E found `release --owner "$VASTY_OWNER"` without the hint and noted that an account-wide release would have destroyed the r8cf and r8cb boxes (`e/final.md` lines 21 and 41, `e/04-status.json` lines 7 and 89). Keep `--all` removed.

### A hint or message to change

- Code is the record. Caller B (`b/final.md` Task 1 lines 19 and 24). Pass 2's B made the same reading. Add "counts from boot" to the `--ttl` help text, as README line 264 says. Untested: no `--help` output is saved, so the current wording is unknown.
- TTL bounds spend. Caller D (`d/02-serve.err` line 5). The milestone names a 30m wait on a 20m lease. Name the lease's `expires_at` there, or the smaller of the two deadlines. Untested: which limit ends the wait lives in `src/`.
- Code is the record. Caller C (`c/01-status.json` lines 196 to 198). Say in README line 307 that `live` counts leases, pending ones included, and leaves out orphans.
- Code is the record, or Pass through the provider. Caller C (`c/08-release.json` lines 4 to 5). Either say in README line 169 that adoption restarts `uptime_s` while `cost` keeps the history, or carry Vast's `start_date` into the adopted lease. C voted for the second (`c/final.md` line 37). Pass 2 proposed the first.
- Code is the record. Caller D (`d/final.md` line 27). Say in `serve --help` that `url` ends in `/v1` and `api_key` goes as a Bearer token, as README lines 223 and 235 show.
- Code is the record. Caller C (`c/05-release.json`). Make README line 155 say `already_absent` appears only when the lease was already gone.

### A field to add or drop

- Pass through the provider. Caller F (`f/05-run.json`, `f/09-status.json`). Add `cost` and `uptime_s` to an auto-released `run`. This is F's vote (`f/final.md` line 44) and pass 2's note. Keep the clock fields null per README line 159.
- Pass through the provider. Caller G (`g/11-status.json`, then `g/12-status.json`). Add `destroy_pending` to `expired` rows with the meaning `release` gives it. Pass 2 proposed it after the same extra call. D and E spent the same command after `release`.

### A deferred item now confirmed by a live caller

`docs/surface-area-reduction-1.md` is absent (`run.md` line 14), so these come from pass 2's design notes. None was confirmed.

- Guards are direct and deterministic. Boot timeout counted from create. B's box sat `None` and `loading` for 3.5 min (`ledger.log` lines 6 to 9) and then ran, losing no clock. Commit `649f801` covers pass 2's never-ran box. No box failed to run this pass.
- One correct way to do each thing. `shadowed_by` on `config show`. `f/vasty.toml` sets no `max_price`, so `f/02-config-show.json` lines 15 to 18 read `source: "user"` with nothing shadowed.
- Guards are direct and deterministic. `destroyed_by` and `destroyed_at`. G asked for `destroyed_by` and `gone_at` (`g/final.md` line 34). The cost was `g/12-status.json`, which `destroy_pending` on `expired` rows would cover.

### Leave alone

- Build for the caller in front of you. A's cheapest-price vote (`a/final.md` line 32). The one retry was the task's planned escalation, and A finished in seven commands.
- Guards are direct and deterministic. B's earlier `expiring_with_running_job` or `run --wait` (`b/final.md` line 59). Vasty holds no runtime estimate. B extended and finished with 674 s left (`b/06-status.json` line 16). G's eight polls finished with no wrong guess.
- Guards are direct and deterministic. D's `serve` warning on little clock at return (`d/final.md` line 30). `serve` returned with 808 s left, and `expiring_soon` covers the short case. `config show` already reports the ttl source.
- One correct way to do each thing. Removing `--no-wait`, `--plain`, `--everyone` and `--cached` cost nothing. Each hint fixed its line on the first try (`e/01-reserve.json` line 4 then `e/02-reserve.rc` 0; `e/03-status.json` line 4 then `e/04-status.rc` 0).
- One correct way to do each thing. The account view put other owners' rows in front of D, E and G. All left them alone. No command cost.
- One correct way to do each thing. `tag LEASE` took two calls for b1 and b2, and C did not flag it. `release --group archive` and `extend --group hold --to 30m` took one call each (`c/05-release.json`, `c/02-extend.json`).
- Fix the guarantee. The orphan fix `vasty tag i-58740864 --ttl 30m` (`c/01-status.json` line 189) led C to adopt and release in two rc 0 commands (`c/07-tag.rc`, `c/08-release.rc`).
- TTL bounds spend. G's t6 was the only box nobody released. It left the ledger 33 s after its clock (`ledger.log` lines 35 to 36). `swept` stayed `[]` (`g/11-status.json` line 51, `manager/005218-status.json` line 289). Keep the sweep always on.
- Pass through the provider. Release cost, `uptime_s` and `duration_s: 0` readings match README lines 169 and 282, and none cost a command.
- One correct way to do each thing. `stop` reports `killed` with exit 0, `expiring_soon` rounds up, and exit code 1 on bad flags. README lines 158, 141 and 133 cover them.
- One correct way to do each thing. Profile ttl holds on an auto-reserved `run` (`ledger.log` line 7 `ttl=720`, `f/06-run.json` line 7) and on `serve` (`ledger.log` line 30 `ttl=1200`). `--startup FILE` ran (`f/05-run.err` lines 8 to 9). `config set` wrote the user file and `config show` reported it (`f/01-config-set.json` line 4, `f/02-config-show.json` lines 15 to 18).

### Harness

- The permission classifier denied `vasty release --all --yes --json` with "[Interfere With Workloads]" (`e/notes.md` line 16, `e/final.md` line 13). No file was written, so E failed its `--all` condition (`e/verdict.md` line 6). Commit `195a60b` changed the removed-flag hints, and the `--all` hint went unobserved. Run 7: persisted from the block on C's `release i-… --yes`. Pass 2: new. Suggestion: have the manager capture that error while the account is empty.
- C spawned at about 00:54:00Z, 8.5 min after setup DONE, because the orchestrator ran D in the foreground (`run.md` line 43). C found the inherited leases at 317 to 333 s left (`c/01-status.json` lines 16, 53, 90 and 127) and extended hold first (`c/final.md` line 30). C finished at 00:56:02Z (`c/09-status.rc`), 3m41s before the earliest inherited clock, b1's 00:59:43Z (`ledger.log` line 29). Pass 2: persisted, where C never spawned in wave 2. Suggestion: launch every wave 2 agent in the background.
- `setup-c.sh` created keep with `"group": null` (`c-setup/01-reserve-keep.json` line 5). The top layer tagged it into `hold` before C started (`run.md` line 83, `c-setup/06-tag-keep-hold.json` line 6). `d/01-status.json` line 6 records the gap at 00:45:39Z. `setup-c.sh` line 5 now passes `--group hold`. Pass 2: new.
- A and B wrapped commands in `$C`, which zsh did not word-split. Each first 02 failed rc 127, and both agents overwrote the 02 files (`a/notes.md` line 5, `b/notes.md` line 6). The failed tries left no record. Pass 2: new.
- `f/01-config-set.json` line 4 wrote `~/.config/vasty/config.toml`, which still holds `max_price = 0.08` after the run (`run.md` line 78). Every other fixture sets `max_price` in `./vasty.toml`, which outranks it (README line 311). Pass 2: persisted; pass 2 removed it at the end.
- `check.txt` agrees with `verdict.md` on every condition in all seven scenarios. A, E and F cite `ledger.log` line 10, an earlier snapshot with the same result (`run.md` line 75). `g/check.txt` line 1 cites `02-reserve.json:ttl`, a field that file lacks, and `g/check.sh` lines 75 to 78 matched `ttl_remaining_s` 354 (`run.md` line 85). The `.cmd` files let `c/check.txt` lines 4 to 6 test `--group` and the `i-` argument. Pass 2: fixed since its `check.sh` misses.
- B's follow-up went out at 00:30:07Z against a 00:30:00Z target (`run.md` lines 24 to 25), with 311 s left (`b/04-status.json` line 16). Pass 2: fixed since its 5.5 min delay.
- The orchestrator released keep at 00:57:07Z (`run.md` line 70, `c-cleanup-release.json` line 5 `cost: 0.013`). C's pass line reads "before cleanup", and `ledger.log` line 39 served. Pass 2: fixed.
- `run.md` lines 13 to 14: the branch sits at `b1eec1b`, and the plan names `49f00e7`.
- Plan rows with no caller:
  - `pending` while the startup hook runs (README line 337). F ran attached.
  - The `--yes` and `--config -` removals. `--yes` was blocked with `--all`, and `e/fx/nightly.sh` has no `--config -`.
  - Job `duration_s` capped at lease end. B's j-1 ended before the clock (`b/06-status.json` line 24). C released `old` while j-1 ran (`c/06-release.json` line 12).
  - `release --owner`, `stop` and `status --group` in C. C released `old` by lease id (`c/06-release.cmd`). `release --owner` ran in E (`e/08-release.cmd`).
  - D's release cost against a later status. `d/05-status.json` under `--owner r8cd` returned `leases: []`.
  - The watchdog versus sweep race in G. No file names the layer that destroyed t6.
