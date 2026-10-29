# Validation 0: live test plan

Target: `docs/live-test-plan.md`. Reference: `spec.md`. Code: commit 018ade9. Line numbers refer to the plan unless a file is named.

**Verdict: ready after fixes.** The phases and cost scale suit a supervised first run, but four steps fail or leave a box billing as written: 2b, phase 5 serve, teardown of orphans, and the one-TTL safety claim.

## Agreed findings

### Blockers

1. **2b leaves the watchdog running.**
   - Location: Phase 2b, line 110. Phase 1, line 72.
   - Problem: Onstart schedules the watchdog in `/etc/cron.d/vasty`. `crontab -r` leaves that file, so cron restarts the watchdog within a minute. The watchdog then destroys `sw` and 2b never tests the sweep. `pkill -f watchdog.sh` also matches the remote `bash -c '...'` that carries the command, so the shell can die before `rm -f alive` runs. Phase 1's `crontab -l` prints nothing for the same reason.
   - Evidence: `src/vasty/onstart.py:141-143` writes `* * * * * root VASTY_ROOT=$R /bin/bash $WD...` to `/etc/cron.d/vasty` and starts cron.
   - Fix: Replace line 110 with:
     ```
     vasty ssh sw -- 'rm -f /etc/cron.d/vasty; pkill -f "[w]atchdog.sh"; sleep 2; rm -f /workspace/.vasty/alive; pgrep -f "[w]atchdog.sh" || echo watchdog_dead'
     vasty status sw                 # expect guard_partial, watchdog missing
     # after 70s
     vasty ssh sw -- 'pgrep -f "[w]atchdog.sh" || echo watchdog_dead; ls /workspace/.vasty/alive'
     ```
     Continue only when both checks print `watchdog_dead` and `alive` is absent. In line 72 replace `crontab -l` with `cat /etc/cron.d/vasty` and `pgrep -af watchdog` with `pgrep -af "[w]atchdog.sh"`.
   - Settled: independent match. Phase 1 part folded in at exchange 1.

2. **Phase 5 `serve` fails before it reserves, and a failed retry has no box to read.**
   - Location: Phase 5, lines 190 and 196.
   - Problem: An auto-reserved `serve` of a model with no `[models]` entry needs `--vram` and `--image` as flags. `defaults.image` does not count, so the command returns `model_unknown`. A failed auto-reserved `serve` also releases its box, so `vasty ssh LEASE -- cat .../log` finds nothing and the retry reserves a fresh box and downloads the wheels again.
   - Evidence: `src/vasty/commands/serve.py:121` checks `ctx.flags.get("vram") is None or ctx.flags.get("image") is None`. `serve.py:150-155` calls `release_quietly` when `created`. Install failures return diagnostics in `details.output` (`serve.py:203-228`).
   - Fix: Replace the phase 5 block with:
     ```
     vasty reserve --name sv --gpu 3060 --vram 12 --ttl 45m --disk 40
     vasty ssh sv -- df -h /workspace
     vasty serve --on sv --model Qwen/Qwen2.5-0.5B-Instruct
     curl -H "Authorization: Bearer $KEY" URL/models
     curl URL/models                        # expect 401
     vasty release sv
     ```
     Replace the retry sentence with: "On `serve_failed`, save the error's `details.output` and run `vasty ssh sv -- 'tail -n 100 /workspace/.vasty/jobs/*/log'`. Rerun `vasty serve --on sv` once. Stop after the retry." `--on` skips the model check and keeps the box on failure. The retry reuses the installed venv.
   - Settled: independent match. Fix chosen at exchange 1.

3. **Teardown cannot reach orphans.**
   - Location: Phase 6, lines 198-207. Guardrails, line 232.
   - Problem: Bulk selectors exclude orphans and unreadable labels, even with `--everyone --yes`. A phase 4 box that was never tagged survives `vasty release --all --everyone --yes` and keeps billing. The phase has no step for a box vasty cannot release, or for vasty itself failing.
   - Evidence: `src/vasty/targeting.py:7`, "Selectors match active leases only and never orphans." `spec.md:124`, "Bulk targets never include orphans." `vastai destroy instance --help` lists `-y, --yes  Skip confirmation prompt`.
   - Fix: After the phase 6 block add:
     ```
     For each id that `vastai show instances --raw` still lists, run `vasty release i-ID --yes`.
     If vasty fails, run `vastai destroy instance ID -y` for each id.
     Rerun `vastai show instances --raw` until it returns `[]`.
     ```
     Change the pass line to: "`vastai show instances --raw` returns `[]`. Final balance recorded."
   - Settled: independent match.

4. **The one-TTL bound fails in two places, and nothing outside the agent stops a box.**
   - Location: Phases intro, line 61. Guardrails, lines 231-232. Report, line 238.
   - Problem: Line 61 says a forgotten box costs at most one TTL. That assumes the watchdog the run is testing. 2b kills it on purpose, and the phase 4 orphan has no clock before `tag`. If the agent dies in either window, nothing destroys the box until the next networked vasty command. "End every session with the phase 6 commands" does not run when the agent process is killed. Setup assumes an empty account without checking. The report is written only at the end.
   - Evidence: The sweep runs only inside `refresh` (`src/vasty/engine.py:593`). `watchdog.sh:51-52` only logs when the key is missing.
   - Fix: Replace line 61 with: "Boxes carry a 15m default TTL. Two windows have no working clock: 2b after the watchdog is killed, and the phase 4 orphan before `vasty tag`. Nigel watches both. If the agent stops, Nigel runs `vastai show instances --raw` and destroys each id." Add setup step 0: "Run `vastai show instances --raw`. Destroy anything listed. Record the ids in the ledger." Add to 2b: "If `sw` is still listed at `expires_at` + 3m, run `vasty release sw` and fail 2b." Add to §7: "After each phase, append its results to the report."
   - Settled: independent match.

### Gaps

5. **The detached job runs as one quoted word.**
   - Location: Phase 3, lines 147-149 and 159.
   - Problem: `run` joins its arguments with `shlex.join`. The single argument `'sleep 120; echo done > work/out.txt'` becomes one quoted command name, so the job exits 127. The pull then follows `status rb` at once, before any file exists. The redirect also keeps `done` out of the job log, so `log_tail` stays empty.
   - Evidence: `src/vasty/commands/run.py:147`, `command = shlex.join(args.command)`.
   - Fix: Use `vasty run --on rb --detach -- bash -c 'sleep 120; echo done | tee work/out.txt'`. After `vasty status rb` add: "Poll `vasty status rb` until the job exits 0, with a 3 minute deadline. Pass: `log_tail` ends with `done`." Then pull and check the file holds `done`.
   - Settled: independent match. Severity set at exchange 1.

6. **Live credentials go into the recorded transcript inside the repo.**
   - Location: Phase 1, lines 71 and 81. Phase 5, lines 191 and 196. Line 14. Guardrails, line 233.
   - Problem: `cat /workspace/.vasty/env` prints `CONTAINER_API_KEY`. The phase 5 curl line carries the serve key, and "records every command" saves it. vLLM logs its arguments, so the job log can hold the key too. `docs/live/` sits in the repo, and `docs/` is untracked. Both keys die with their box.
   - Evidence: `src/vasty/onstart.py:98` writes `CONTAINER_API_KEY=%s`. `git status` shows `?? docs/`.
   - Fix: Write recordings to `/private/tmp/vasty-live/out/`. Copy reviewed files to `docs/live/` after the run. Replace `cat ... /workspace/.vasty/env` with `sed 's/^CONTAINER_API_KEY=.*/CONTAINER_API_KEY=<redacted>/' /workspace/.vasty/env`. In line 81, record the container id and whether the key is set. Change line 233 to: "Redact `CONTAINER_API_KEY` and the serve key by value in every saved file. After phase 5, run `grep -r "$KEY" /private/tmp/vasty-live/out` and expect no match."
   - Settled: independent match. Severity set at exchange 1.

7. **The watch method names the wrong views.**
   - Location: Facts, line 25. Phase 2a, lines 98 and 102. Phase 2b, line 114. Guardrails, line 229.
   - Problem: `vasty status --cached` reads `leases.json` only. It shows a local countdown and never shows the box leave. Plain `vasty status` hides history, so "`expired` in history" shows only with a named target or `--verbose`. A `swept` entry can carry `ok: false`. Line 229 is broader than the code: the sweep fires only once `now > expires`.
   - Evidence: `src/vasty/commands/status.py:69`, `snap.active() + (snap.history() if verbose else [])`. `src/vasty/engine.py:230-234` `past_clock`.
   - Fix: In 2a drop the `--cached` line, or mark it "local countdown only". Make `vastai show instances --raw` the disappearance check. After the box is gone run `vasty status wd`. Pass: `state: expired`, `swept: []`. In 2b, confirm the box is still listed after `expires_at`, then run `vasty status sw`. Pass: `swept` names `sw` with `ok: true` and `error: null`. Replace line 229 with: "Run no networked vasty command from `expires_at` until `vastai show instances --raw` no longer lists the box."
   - Settled: independent match. Line 229 part at exchange 1.

8. **`tag` runs while the orphan is still loading.**
   - Location: Phase 4, lines 166-172.
   - Problem: `tag` writes the label, then needs an SSH endpoint to install the watchdog. A loading orphan has none, so `tag` catches `lease_pending` and installs nothing. The plan then watches with `vastai` only, so "the watchdog destroys the box at the clock" fails. The box lives until a later networked command sweeps it.
   - Evidence: `src/vasty/commands/tag.py:222-236` catches the error into `last_provider_error`. `src/vasty/engine.py:217-227` raises `lease_pending` without `ssh_host` and `ssh_port`.
   - Fix: Before `vasty tag` add: "Poll `vastai show instances --raw` until the row shows `actual_status: running` with `ssh_host` and `ssh_port` set." Change the pass line to: "`tag` returns `results[0].guard: full`. If `partial`, record it and run `vasty status i-ID` once to retry the adoption."
   - Settled: exchange 1.

9. **The raw create names no offer and no id.**
   - Location: Phase 4, line 166.
   - Problem: `OFFER` has no source, price or GPU bound, and the plan does not say how to read the new instance id.
   - Evidence: `vastai create instance --help` shows the response `{'success': True, 'new_contract': 7835610}`. vasty reads the same field (`src/vasty/provider.py:436-438`).
   - Fix: Before the command add: "Pick OFFER as the first `id` from `vastai search offers 'gpu_name=RTX_3060 verified=true rentable=true rented=false num_gpus=1 dph_total<=0.12 disk_space>=16 direct_port_count>=3' -o dph_total --raw`. The orphan is `i-<new_contract>`. Record it in the ledger at once."
   - Settled: exchange 1.

10. **The phase 5 clock equals the install timeout.**
    - Location: Phase 5, lines 190 and 196. Guardrails, line 228.
    - Problem: The box clock starts at onstart and covers the essentials install. `serve` then allows 30m for the vLLM install and 30m more for readiness. A 30m lease can expire mid-install. The box dies and `serve` reports a lost connection.
    - Evidence: `src/vasty/commands/serve.py:48-49`, `INSTALL_TIMEOUT_S = 1800.0`, `READY_DEADLINE_S = 1800.0`.
    - Fix: Reserve `sv` with `--ttl 45m` (finding 2). Add: "Stop the phase if the install runs past 20 minutes. Check the remaining lease time before the retry." Change line 228 to "Phase 5 is the one 45m lease."
    - Settled: exchange 1.

11. **16 GB disk is likely too small for phase 5.**
    - Location: Setup step 5, `disk = 16`. Phase 5.
    - Problem: The image, a torch and vLLM venv under `/workspace/.vasty/venv`, and the 988 MB model share the disk. This is a sizing estimate the code cannot confirm.
    - Evidence: `src/vasty/commands/serve.py:75-85` installs the venv on the box disk.
    - Fix: `--disk 40` on the `sv` reserve and `df -h /workspace` before `serve` (finding 2). Add the disk to the phase 5 cost row.
    - Settled: exchange 1.

12. **`reserve` can return `running` before onstart finishes.**
    - Location: Phase 1 pass, line 81. Phase 2b, line 109. Phase 3, lines 144-146.
    - Problem: Onstart writes `startup.started` last, after the installer, the watchdog and the cron entry. A probe that lands earlier sees no guard file and no `startup.started`. It flags nothing and derives `running`. So `reserve` can return `guard: full` before the watchdog exists, 2b can kill a watchdog that onstart starts afterwards, and a first `run` can find no tmux. Spec §3.1 maps "answers, startup unfinished" to `pending`.
    - Evidence: `src/vasty/onstart.py:212-224` sets the order. `src/vasty/remote.py:333-338` sets `watchdog_down = onstart_done` when `alive` is absent. `src/vasty/state.py:77-79` needs `startup_started`.
    - Fix: After each `reserve` that precedes guard checks, 2b or a `run`, add `vasty ssh L -- 'cat /workspace/.vasty/startup.exit; ls /workspace/.vasty/alive /workspace/.vasty/guard; command -v tmux'`. Continue when `startup.exit` holds `0`, both files exist and tmux resolves. If `reserve` returned before that, file a bug against spec §3.1.
    - Settled: exchange 1.

13. **A proxy offer has no 8000 or 8080 mapping.**
    - Location: Phase 1 pass, line 79. Phase 5.
    - Problem: vasty creates `ssh_proxy` when an offer has no direct ports and then requires no port mapping. Search does not filter on `direct_port_count`. The phase 1 port check and the phase 5 endpoint then fail through the offer.
    - Evidence: `src/vasty/commands/reserve.py:123` picks the runtype. `reserve.py:129`, `required = ports if request.runtype == "ssh_direct" else []`.
    - Fix: Add `direct_port_count>=3` to the step 7 search as information. In phase 1, record a proxy box as an offer note. Before phase 5 `serve`, check that `sv` returned `ports` with `8000`. If it is missing, release `sv` and reserve again.
    - Settled: exchange 1.

14. **The estimate rate ignores how vasty picks offers.**
    - Location: Setup steps 5 and 7, lines 37-53. Cost proposal, line 211.
    - Problem: vasty ranks by reliability first, then bandwidth, then price. No command in phases 1 to 4 passes `--gpu 3060`. Each box can land on any GPU up to `max_price` $0.25, so the $0.10/hr rate has no basis. `| head -40` cuts the step 7 JSON to part of one offer.
    - Evidence: `src/vasty/commands/reserve.py:237`, `sorted(kept, key=lambda o: (-o.reliability, -o.inet_down, o.dph_total, o.id))`. `gpu` is a valid `[defaults]` key (`src/vasty/config.py:44`).
    - Fix: Add `gpu = "3060"` to `[defaults]`. In step 7 search with `gpu_name=RTX_3060` and drop `| head -40`. Print `gpu_name`, `dph_total`, `reliability`, `cuda_max_good` and `direct_port_count` for each row. Set `max_price` to the highest price among the top 5 by reliability, about 0.12. Replace line 211 with: "vasty takes the most reliable offer under `max_price`. The estimate uses `max_price`."
    - Settled: independent match.

15. **The bandwidth bound and the table rows are wrong.**
    - Location: Cost proposal, lines 213-224.
    - Problem: "A dozen 6 GB pulls plus 3 GB of wheels stays under $1 even at the $27/TB outlier" is false. 75 GB at $27/TB is $2.03. The plan has 13 boxes. Phase 1 has one 15m box. The estimates sum to $1.75.
    - Evidence: 13 boxes are p1; wd, wd rerun, sw, ex; three run boxes and rb; orphan, g0, g1; sv. 13 × 6 GB + 3 GB wheels + 1 GB model = 82 GB.
    - Fix: Replace the sentence with: "Bandwidth is host-priced at $3 to $14 per TB, with outliers to $27. 13 boxes pull about 82 GB: $0.25 at $3/TB, $1.15 at $14/TB, $2.21 at $27/TB. Layers cached on the host cost nothing." Set the Bandwidth row to "$0.25 to $1.15". Set Phase 1 box time to 15m and Phase 5 to "1 box, 45m". Set the Total estimate to "$1.75 to $2.60". Add each host's bandwidth rate to the ledger.
    - Settled: independent match.

16. **Stop rules disagree and name no action.**
    - Location: Header, line 3. Phases intro, line 63. Cost proposal, line 224. Guardrails, lines 230-231.
    - Problem: The plan gives four figures: target under $10, estimate ~$2, "expected under $3", and caps summing to $5.50. It has no whole-run stop. It reads the balance only at phase edges, so a long phase has no reading, and balance lag credits spend to the next phase. "An instance lives that `vasty status` does not list" rarely fires, since `status` lists orphans. A stop names no next step.
    - Evidence: Line 230, "at the start and end of each phase". Line 224, "Spending past $10 means something has gone wrong".
    - Fix: Change line 3 to "Spend ceiling: $20 on the account. Stop the run at a cumulative balance drop of $5.50." Delete "Expected spend is under $3" and the "$10" sentence. Keep the per-phase caps. Replace line 63 and line 230 with: "Read the balance before each create and every 60 seconds while any instance exists. After a phase's last box leaves `vastai show instances --raw`, read it twice 120 seconds apart and keep the second reading." Change the second stop condition in line 231 to "an id in `vastai show instances --raw` matches no `instance_id` in `vasty status --verbose`, apart from the phase 4 orphan before `tag`". Add: "On any stop, create nothing more, run phase 6, then write the report."
    - Settled: independent match. The $5.50 figure set at exchange 1.

17. **`spent_today` counts a fresh account's boxes from midnight UTC.**
    - Location: Setup step 9. Phases 3 and 4.
    - Problem: With no charge rows, `covered_through` is the day start. Each live box is then estimated as running since 00:00 UTC. At 16:00 UTC two $0.25 boxes estimate $8. That passes the $6.00 `daily_budget` and returns `budget_exceeded` on a valid reserve.
    - Evidence: `src/vasty/provider.py:280-285` returns `start` with no instance rows. `src/vasty/budget.py:49-51` estimates from `since`.
    - Fix: In phase 1, record `totals.spent_today` beside the balance drop and file a gap as a §12 answer. Add to phases 3 and 4: "On `budget_exceeded`, record `details` and compare with the balance drop before any retry."
    - Settled: exchange 1.

18. **`run -- false` exits 1.**
    - Location: Phase 3, line 157.
    - Problem: `run` exits with the remote exit code. The plan expects 2.
    - Evidence: `src/vasty/commands/run.py:224-228` returns `exit=code` and `exit_code=code`. `spec.md:336`, "`run` exits with the remote exit code".
    - Fix: "`run -- false` exits 1 with `exit: 1`, `error: null`, `released: true`, and the box is gone."
    - Settled: independent match.

19. **The phase 1 cost check cannot pass.**
    - Location: Phase 1 pass, line 82.
    - Problem: Money prints to 2 places. One minute at $0.06/hr is $0.001, so `cost` reads the same on both calls.
    - Evidence: `src/vasty/output.py:13-15` quantizes to `Decimal("0.01")`.
    - Fix: "`status` reports `cost_source` in billing, mixed or estimated, and a numeric `cost`. Record `cost` and `uptime_s` from both calls. At `release`, `cost` is within $0.02 of `price_per_hr` × `uptime_s` / 3600."
    - Settled: independent match.

20. **Commands and paths do not resolve from the working directory.**
    - Location: Setup, lines 33-54. Lines 14 and 238. Every `.venv/bin/vastai`.
    - Problem: The run's working directory is `/private/tmp/vasty-live`. From there `.venv/bin/vastai`, `docs/live/` and `issues/` resolve to nothing, and `vasty` is not on PATH. Bare `python` lacks `vastai`. The directory and fixtures have no creation step.
    - Evidence: `src/vasty/config.py:398-400` reads `cwd/vasty.toml` and `cwd/.vasty/config.toml` only. `which vasty` prints `vasty not found`.
    - Fix: Add to setup: "`export PATH=/Users/nigel.gilbert/Desktop/bench/vasty/.venv/bin:$PATH`. `mkdir -p /private/tmp/vasty-live/fx /private/tmp/vasty-live/out`. Write `vasty.toml` and the fixtures there. Run every command from `/private/tmp/vasty-live`." Replace each `.venv/bin/vastai` with `vastai`. In step 8 use `/Users/nigel.gilbert/Desktop/bench/vasty/.venv/bin/python`. Name the report and `issues/` by absolute repo path.
    - Settled: independent match.

21. **Phase 1 releases `p1` before the checks that need it.**
    - Location: Phase 1, lines 74 and 86-90.
    - Problem: The block ends with `vasty release p1`. The curl and reuse checks follow it, and the reuse check would create a new box.
    - Evidence: Line 89, "`vasty reserve --name p1 --ttl 15m` while `p1` lives".
    - Fix: Move the three "Also on this box" checks into the block before `vasty release p1`.
    - Settled: independent match.

22. **2d tests `reserve` and leaves the `extend` budget path untested.**
    - Location: Phase 2d, lines 128-134.
    - Problem: The heading says "Extend past budget". The only command is `reserve`.
    - Evidence: Line 131, `VASTY_DAILY_BUDGET=0.01 vasty reserve --name nope`.
    - Fix: Rename to "2d. Reserve past budget." In 2c, before `--to 3m`, add `VASTY_DAILY_BUDGET=0.01 vasty extend ex --by 10m`. Pass: `budget_exceeded`, exit 3, and the clock file and label `expires=` unchanged.
    - Settled: independent match.

23. **SIGINT has no working recipe.**
    - Location: Phase 3, lines 150 and 160.
    - Problem: A non-interactive shell starts `vasty run ... &` with SIGINT ignored. Python then installs no `KeyboardInterrupt` handler, so `kill -INT` does nothing.
    - Evidence: `src/vasty/commands/run.py:210-213` cancels through `except KeyboardInterrupt`.
    - Fix: Replace line 150 with `python3 -c 'import subprocess,signal,time;p=subprocess.Popen(["vasty","run","--on","rb","--","sleep","300"]);time.sleep(10);t=time.time();p.send_signal(signal.SIGINT);rc=p.wait(timeout=30);print(rc,round(time.time()-t,1))'`. Pass: `130` within 10s of the signal, and `rb` stays listed.
    - Settled: exchange 1.

24. **§1 names no §12 question.**
    - Location: §1 item 3, line 11. Facts, line 22. §7.
    - Problem: Phase 1 covers key presence and whether the key reads its own row. `ports` absent until running needs `--no-wait` and polling, and `reserve` waits. Charges clipping and lag are touched only in setup step 9. Line 22 says 2a tests the key `DELETE`, but 2a only destroys a running box, and the open question is `DELETE` while `loading`. Label length, 404 as unauthorized, the `on-demand` spelling and `schedule_job` are untouched.
    - Evidence: `spec.md:739-741`.
    - Fix: Add a table to §1: question, phase, command, recorded answer. For ports add `vasty reserve --name p1 --no-wait`, then poll `vastai show instances --raw` every 10s and record "transition not observed" when ports appear before the first sample. Mark the untouched questions deferred.
    - Settled: exchange 1.

### Nits

25. **`config show` reports `default` for keys the test config leaves out.**
    - Location: Setup step 6, line 52.
    - Problem: `api_key_env`, `ssh_key`, `gpus` and other unset keys report `default`.
    - Evidence: `src/vasty/config.py:60-63` lists the shown keys.
    - Fix: "`env | grep '^VASTY_'` prints nothing and `~/.config/vasty/config.toml` is absent. `vasty config show` reports `project` for owner, ttl, run_ttl, max_price, daily_budget, warn_before_expiry, disk, image and gpu."
    - Settled: independent match.

26. **The `--ttl` guardrail contradicts the phases.**
    - Location: Guardrails, line 228. Setup step 5, `run_ttl = "20m"`.
    - Problem: 2c extends `ex` to 20m. `rb`, `g0` and `g1` pass no `--ttl`. `run_ttl` is 20m.
    - Evidence: Lines 120, 144, 175-176.
    - Fix: Set `run_ttl = "15m"`. Add `--ttl 15m` to `rb`, `g0` and `g1`. Replace line 228 with: "Every clock runs at most 20m from its start, except phase 5."
    - Settled: exchange 1.

27. **Phase 1 pass checks compare unlike forms.**
    - Location: Phase 1 pass, lines 79-81.
    - Problem: `expires_at` is ISO and the clock file holds epoch seconds. The label for `--name p1` carries `name=p1`. The guard file holds a blank line when guard is full.
    - Evidence: `src/vasty/labels.py:103-112` orders lease, name, owner. `src/vasty/onstart.py:163` prints the missing layers.
    - Fix: "`expires_at` as epoch seconds equals the clock file. The label parses as `vasty:v1;lease=X;name=p1;owner=live-test;created=N;ttl=900;expires=M`. The JSON `guard` is `full`."
    - Settled: exchange 1.

28. **Bulk `extend` returns an object.**
    - Location: Phase 4 pass, line 183.
    - Problem: The plan says "a per-lease array". The response is `{results, warnings, swept}`.
    - Evidence: `src/vasty/commands/extend.py:350-359`.
    - Fix: "bulk `extend` returns `results` with two entries, each `ok: true`."
    - Settled: exchange 1.

## Disagreements

None.

## Dropped

- `reserve` leaves Nigel's public key registered on the account. Dropped: spec §5.3 prescribes the registration, and a public key on the owner's account exposes nothing.
- Fund the account with $10. Dropped: the caller set the $20 ceiling. Finding 16 adds a $5.50 run stop under it.
- Lower per-phase caps to $4.05 in total. Dropped: the caps act as alarms, and finding 16 adds the cumulative stop.
- Start the run between 00:00 and 02:00 UTC and set `daily_budget` to 4.00. Dropped: finding 17 records the effect, and a scheduling rule adds nothing the record does not.
- The test count reads 1128 where collection finds 1129. Dropped: the brief gives 1128 passing, and the count changes no step.
- §1 "in order of value" differs from phase order. Dropped: phase order follows dependencies, and the rest is style preference.
- The 2a 6m rerun wording. Dropped: "boot eats the TTL" matches the `created + ttl` deadline that applies before the first probe, and the rest is style preference.
- `vastai show instances` pages without `--raw`. Dropped: every call in the plan passes `--raw`.

## Run

- Angles: feasibility for setup and phases 1 and 3; feasibility for phases 4 to 6; watchdog and sweep observation method; cost proposal soundness; security, operational risk, contradictions and sequencing.
- Agents: 5 Sonnet.
- Reviewer: astra.
- Exchanges: 1 of 3. All 16 Codex findings matched swarm findings. Codex backed all 14 Opus-only findings and the four open severity and fix points in exchange 1.
