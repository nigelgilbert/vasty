# Live run 8: exercise the reduced surface

Pass 3. Raw material under `/private/tmp/vasty-live-8c`. Findings land in [live-run-8-findings.md](live-run-8-findings.md).

Branch `feature/reduce-api-surface` at `49f00e7`. Goal: watch fresh Opus agents drive every surface that `docs/surface-area-reduction-1.md` changed, with only the README, `--help` and a `vasty.toml`, and record each hiccup. A second kind of agent reads the notes and writes the friction and design record.

Account 836500. Start credit 18.41, 19:23Z. Spend cap for the run: $2.00. Boxes: RTX 3060 at <= $0.09/hr, 15 min clocks; one RTX 5060 Ti at <= $0.40/hr, 20 min clock, for serve. Run 7 spent $0.063 on four agents.

Owners never used before: r8ca to r8cg, manager r8cm. The shared cache keeps 24 h history and the state dir follows `$HOME`, so fresh owner names are the isolation.

## What changed since run 7 and which scenario covers it

| Change | Scenario |
|---|---|
| `no_offers` hint drops the price number | A |
| `any` clears a config-pinned `gpu` | A |
| `run --detach` returns gpu, price and ttl_remaining | B |
| `sync pull` creates DEST's parent | A, B |
| job `duration_s` capped at lease end | B, C |
| `release` cost described as provisional | B, D |
| plain `status` is the account view with orphans and orphan `uptime_s` | C |
| `--owner` and `--group` select | C |
| `tag LEASE` sets one lease; bulk relabel is a `status` then `tag` chain | C |
| `tag i-ID --ttl` adopts an orphan, then `release` by lease | C |
| `extend --by` and `--to` only | B, C, E |
| one `ttl` key, profile ttl honored by `serve` and `run`, auto-reserve 30m | D, F |
| `--startup FILE`, `startup` text in a profile | F |
| `config set`, `config show --profile`, `config profiles` | F |
| removed flags: `--all`, `--everyone`, `--yes`, `--until`, `--plain`, `--no-wait`, `--cached`, `--config -` | E |
| TTL promise: watchdog or sweep destroys past the clock | G |

## Scenarios

Wave 1, concurrent, four agents:

- A (r8ca): cold start under price pressure. `vasty.toml` pins `gpu = "3060"`. Task: run `fx/compute.py` on any GPU under $0.045/hr, with leave to go to $0.07/hr when nothing matches, and bring `/workspace/out/result.json` back to `./out/result.json`. Measures whether the new `no_offers` hint leads to `--cuda` sooner than run 7's four tries, and whether the agent uses `--gpu any` to drop the pin. Pass: `a/out/result.json` exists; one `reserve` `.json` has `price_per_hr` <= 0.07; the last `release` `.rc` is 0; no r8ca instance in the last ledger line.
- B (r8cb): detached job with a follow-up. Task 1: start `fx/train.py` detached on a 10 minute clock, report lease and job, wait. Task 2 at about 4 min: will it finish; keep it alive if needed; pull the log, run `fx/eval.py` on the same box, release. Measures whether the richer `run --detach` output removes the second `status`, `extend --by`, `run --on`, `sync pull` into a missing directory, and the `release` jobs report. Pass: the `run` `.json` has `gpu`, `price_per_hr` and `ttl_remaining`; an `extend` `.rc` is 0; a `sync` `.rc` is 0; the `release` `.json` `jobs[].cmd` names `train.py` and `eval.py`; no r8cb instance in the last ledger line.
- E (r8ce): stale script. The agent gets `fx/nightly.sh`, written against the old surface: `reserve --name ft --no-wait --plain`, `status --everyone --verbose --cached`, `extend ft --until`, `release --all --yes`. Task: this script stopped working after an upgrade; make the same workflow run on the installed version and report each change. One 10 minute box. Measures the error each removed flag produces and whether the hint names the replacement. Pass: a `.json` each naming `--no-wait`, `--everyone`, `--until` and `--all`; the last `release` `.rc` is 0; no r8ce instance in the last ledger line.
- F (r8cf): configuration. `vasty.toml` carries `[profiles.prep]` with `ttl = "12m"` and a `startup` script that writes `/workspace/prep.ok`, and sets no `max_price`. Task: set a user-level `max_price` with `config set`, show it with `config show --profile prep`, list profiles; then run `fx/hello.py` with `--startup fx/extra.sh` from a file; then run it with the prep profile in one `run` command, with no `reserve`, and confirm the startup script ran. Measures `config` subcommands, `--startup FILE`, profile ttl on an auto-reserved `run` (expires about 12 min out), the `startup` text key, and `pending` while the hook runs. Pass: `config set` `.rc` is 0; `config show` `.json` reports `max_price` from the user file; `config profiles` `.json` lists `prep`; a `run` `.err` names what `fx/extra.sh` writes; a later `run` `.cmd` has `--profile prep` and its `.err` names `/workspace/prep.ok`; no `reserve` `.json` under `out/f/`; no r8cf instance in the last ledger line.

Wave 2, concurrent, three agents, after wave 1 releases and the account reads empty:

- C (r8cc): inherited mess. Manager pre-creates under r8cc: `keep` idle in group `hold`; `old` running `fx/sleeper.py` detached; `b1` and `b2` in group `batch`; one unlabeled instance made with the vastai CLI. Task: find what is under your owner and what it costs per hour; keep group `hold` for another 30 minutes; move `b1` and `b2` into group `archive` and name them `arch-1` and `arch-2`; then release group `archive`; release everything else of yours except `keep`; report anything else on the account; an instance with no owner and no clock gets adopted with a 10 minute clock and released as one of yours. Measures the account view with an orphan row and `uptime_s`, `tag` per lease and `tag i-ID --ttl` adoption, `release --group`, `release --owner`, `extend --group`, `stop`. Run 7's harness classifier blocked a bare orphan destroy; adoption first turns it into a lease release. Pass: a `status` `.json` with an orphan row carrying `uptime_s`; `tag` `.json` for `arch-1` and `arch-2`; a `release --group archive` `.rc` of 0; a `tag i-… --ttl` `.rc` of 0; an `extend` `.cmd` with `--group hold` and its `.rc` of 0; the last ledger line before cleanup shows one r8cc instance, `keep`.
- D (r8cd): serve. `[profiles.vllm]` sets `ttl = "20m"`. Task: serve `Qwen/Qwen2.5-0.5B-Instruct` with the vllm profile, ask it one question through the endpoint, stop and release. The task does not mention `--ttl`. Measures profile ttl on `serve`, the progress lines during the 7 minute boot, `stop`, and release cost versus a later `status`. Pass: `serve` `.rc` is 0; the `serve` `.err` has `vllm started as` and `/v1/models answers`; a saved endpoint reply with non-empty `choices`; `stop` and `release` `.rc` are 0; no r8cd instance in the last ledger line.
- G (r8cg): expiry. Task: reserve a box with a 6 minute clock, confirm it is running, then watch it until vasty reports it gone without releasing it yourself. Measures `expiring_soon`, the `expired` state in `status`, and the watchdog versus sweep race. Manager confirms the instance left the account in the ledger. Pass: a `reserve` with `.rc` 0 has a 6 minute ttl in its `.json`; a `status` or `sweep` `.json` reports that reserve's lease `expired`; no `release` `.json` under `out/g/`; the ledger drops the instance within 3 minutes of the clock.

## Friction and design recorder

One Opus agent, read-only, owner none. It runs three times: after wave 1, after wave 2, and once more after the manager writes `out/report.md`. Input: every `<letter>/notes.md`, `out/<letter>/`, `out/manager/`, `out/ledger.log`, the README, `docs/principles.md` and `docs/surface-area-reduction-1.md`. It does not read `src/`.

It writes `docs/live-run-8-findings.md` in the vasty repo and rewrites it on each pass. Two sections:

- Friction: one bullet per hiccup, grouped by surface (hints, help and docs, output shape, timing, provider, harness). Each bullet names the scenario, the NN file, the exact message or field, and a status: new in run 8, persisted from run 7, or fixed since run 7 against the run 7 report at `/private/tmp/vasty-live-7/out/report.md`.
- Design notes: observations for the next surface pass. Each names the principle it touches, states the caller that hit it, and lands in one of: a removal that cost an agent something, a hint or message to change, a field to add or drop, a deferred item from the work file now confirmed by a live caller, or a non-finding to leave alone. Harness friction such as the permission classifier goes in its own subsection.

## Manager

- `ledger.sh` samples `vastai show instances --raw` and credit every 60 s into `out/ledger.log`.
- `manager.sh` runs `vasty status --json --verbose` as r8cm every 2 min into `out/manager/`.
- Briefs follow run 7's template with the run 8 paths. Agents write `notes.md` and save every command's stdout and stderr as `out/<letter>/NN-<verb>.json` and `.err`.
- After each wave: confirm `vastai show instances --raw` is `[]`, release anything left, note it.
- Final `out/report.md`: outcomes table, friction ranked by agent cost, manager observations, first-change votes.

## Stop rules

- Credit drops more than $2.00 from start: release everything, stop.
- An agent box runs past its clock with no follower, G excepted: release by hand, note it.
- Two consecutive create failures from Vast: pause 10 min, then retry once.
- A recorder agent that reads `src/` or runs vasty is restarted with the brief restated.

## Fixtures

Copy `fx/` from run 7 and add `fx/nightly.sh` for E and `fx/extra.sh` for F. Each scenario dir gets its own `vasty.toml`: A pins gpu, F adds the prep profile and drops `max_price`, D adds the vllm profile, the rest use the run 7 defaults with `run_ttl` removed.
