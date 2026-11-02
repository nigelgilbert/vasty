# Live run 8, second pass: review and plan

Run dir `/private/tmp/vasty-live-8b`. Branch `feature/reduce-api-surface` at `754929c`. Verdicts: A, B, C, D, E and G pass. F fails on its fixture. Spend $0.197 of $2.00. Account empty at close.

## What the raw files show

- G, g/02-reserve.json. Vast held instance 58721333 in `loading` then `created` (ledger lines 25 to 30) and never reported `running`. The 5 minute give-up arms on `running_at` (`reserve.py` 586 to 590), so the wait ran to `created + ttl`. The sweep follower destroyed the box at the clock, and the wait took the history branch (`reserve.py` 553 to 559), whose hint sends the caller to `status`. Reserve blocked 6m05s. The retry's 3m12s boot was ordinary.
- D, d/03-serve.err. `_bring_up` and `_wait_ready` (`serve.py` 158 to 252) write no stderr line. Silence ran from "startup done" at 22:19:24Z to the result at 22:25:48Z.
- B, b/04-status.json. The extend covered the pull and eval, which the training clock left no room for (b/notes.md line 11). j-1 ended about 22:07:38Z and 06-status ran at 22:08:08Z. No defect.
- A, a/02-reserve.json. `provider.py` 182 filters on `disk_space`, and `_no_offers` (`reserve.py` 267 to 278) never names disk.
- E, e/03-extend.json and e/04-release.json. The hints come from `cli.py` 59 to 60 and cost E one help read and one README read.

## Confirmed since pass 1 and run 7

- Boot milestones on stderr: a/03-reserve.err, b/02-run.err, d/03-serve.err.
- `destroyed: true` after a give-up: g/02-reserve.json.
- Removed-flag hints name a replacement: e/01 to e/04.
- `serve` returns `gpu`, `price_per_hr`, `ttl_remaining_s` and honors the profile ttl: d/03-serve.json, ledger line 25 `ttl=1200`.
- `run --detach` names the lease at create and returns gpu and price: b/02-run.err line 1, b/02-run.json.
- `expiring_with_running_job` fires with a runnable fix: b/04-status.json, b/05-extend.rc 0.
- `--gpu any` clears the pin and `no_offers` suggests no price: a/02-reserve.json.
- `sync pull` creates the parent: a/out born inside a/05-sync, b/logs inside b/07-sync.
- Orphan row with `uptime_s` in plain `status`, and `burn_per_hr_mine`: c/01-status.json.
- `config set` returns `path`: f/06-config-set.json.
- Orphan adoption and release with no classifier block: c/08-tag.rc, c/09-release.rc.
- TTL promise: five unreleased boxes left the ledger within about a minute of their clocks (ledger lines 37 to 40).
- Unexercised: the 5 minute no-SSH give-up from 059bd21.

## Claims the files contradict

- "G lost about 9 minutes." Vasty's share is 6m05s.
- "A fixed deadline from create would return sooner." At a 6m TTL it saves nothing. Healthy boots ran up to about 5 min (ledger lines 23 to 28).
- "B: one extend and two minutes waited." The task needed the extend. Idle time after the job ended was about 30 s.
- "G ran the account view g/16-status.json." g/notes.md line 28 names `status --owner r8g`.
- "Box 2's spend is not reported anywhere." `status LEASE` shows a named lease in any state (README line 300).
- The uncovered-row list in the brief names `status --owner` and `release --owner`. a/notes.md line 14, g/notes.md line 28 and e/notes.md line 19 ran them. Only `status --group` went unexercised among the selector rows.

## Decisions

- Stay on `feature/reduce-api-surface`. The merge waits on the fix items.
- `serve` gets two stderr lines.
- No boot deadline counted from create.
- `config set` stays as is. `config show` names the source.
- After the fixes, pass 3 runs on the branch, then the PR.
- `docs/live-run-8.md` is edited in place for pass 3. It and `docs/live-run-8-findings.md` are deleted in the last commit before the PR.
- Harness rules go in the live-run skill. Per-scenario file names go in the `Pass:` lines.

Dropped for lack of a live caller: a wait-until-gone verb, `destroy_pending` on expired rows, `cmd` in attached `run` JSON, `tag --group`, a default for `release --owner`, `source` per profile, `cost` on an auto-released `run`, a README line on `--sync` with `--on`, a README line on adoption restarting `uptime_s`.

## Step 1: vasty fixes

One commit per item. Each code change carries a test and the README edit.

1. Serve progress. `serve.py` 158 to 252. `ctx.warn` after `start_job`: `vasty: L vllm started as J; polling /v1/models, up to 30m. Log: vasty ssh L -- tail -n 100 /workspace/.vasty/jobs/J/log`. `ctx.warn` when `_ready` returns true: `vasty: L /v1/models answers`. README line 94 lists both milestones. Test: both lines in the fake ctx's stderr.
2. Box expired before running. `reserve.py` 553 to 559. When `lease.running_at is None`, raise `_not_ready` with the history branch's `lease` and `destroyed` details and Vast's last `actual_status` in the message: `Lease L did not become ready before its clock ran out; Vast last reported it created.` README line 183 reads "the box never became ready or stopped answering SSH". Test: a snapshot that puts the lease in history with `running_at` None.
3. Removed-flag hints. `cli.py` 59 to 60. `--until`: `use --by D or --to D, both counted from now`. `--all`: `use --owner "$VASTY_OWNER"`. Update the hint tests.
4. Disk in `no_offers`. `reserve.py` 267 to 278. Add `disk>={disk_gb}GB` to `parts` and `a lower --disk` to `tips`. One test row.
5. Round the milestone price. `reserve.py` 152 to 153. Format with the JSON's rounding. Adjust the milestone test.
6. Wording. README line 306: the 30m built-in applies when no layer sets `ttl`. README line 64 and `extend --help`: `--to` is a duration from now. `run --help` for `--sync`: DIR's contents land in `/workspace`. README line 148: `already_absent` appears when the lease was already gone.

Run `uv run pytest`, `uv run ruff check .` and `uv run mypy`.

## Step 2: harness and plan

In `~/.claude/skills/live-run/SKILL.md`:

- check.sh rule: under `--json`, errors are in the stdout `.json` and job output in `.err`. A check on an argument reads `NN-<verb>.cmd`. Add the `.cmd` rule to the brief beside the `.rc` rule.
- Orchestration: spawn each wave 2 child in the step that sees its DONE; read the owner from one place; send follow-ups at the plan's minute; check a last-ledger condition before cleanup; pass `-y` to `vastai destroy`; retry one failed ledger sample; stop ledger.sh and manager.sh at close.

In `docs/live-run-8.md`:

- F fixture loses `max_price`. The `config set` step moves ahead of the runs. F's second run is `run --profile prep` with no reserve.
- C's keep step is `extend --group`.
- G's `Pass:` keys `expired` on the lease from the reserve with rc 0.
- B's `Pass:` names `release .json jobs[].cmd`.
- Drop the rows with no task: tqdm collapse, explicit `sweep --follow`, `--help` default labels, `status --group`, LEASE plus selector.
- Pass 3 header: run dir `/private/tmp/vasty-live-8c`, owners `r8ca` to `r8cg`.

## Step 3: pass 3

Check for a live run first. Run `/live-run docs/live-run-8.md opus medium`. Evidence that the fixes landed: D's serve `.err` has the two new lines; E's hints read as changed; F's `config show` reports `max_price` from the user file; any box that expires before running returns the new message.

## Step 4: close

Delete `docs/live-run-8.md` and `docs/live-run-8-findings.md`. Run the three checks. Open the PR with a standalone description. Squash merge.
