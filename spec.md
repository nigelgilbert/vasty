# vasty — leased GPU compute for agents

## 1. Summary

`vasty` is a small CLI that lets an AI agent (or a human) borrow a GPU machine from Vast.ai for a bounded amount of time. Every machine is a **lease**: it has a clock, and when the clock runs out the machine is destroyed. Nothing runs forever by accident.

**A box is a lease with a clock; jobs run on it.**

Primary consumer: coding agents such as Claude Code, invoked from a skill or script. Secondary consumer: the human running them.

## 2. Design principles

1. **Expire by default.** Every lease has a TTL. Keeping something alive requires an explicit `extend`.
2. **Bounded spend.** Time caps hours; a budget caps dollars. Both have defaults. vasty refuses to exceed either by accident (see §2.1).
3. **Light.** No daemon, no database server, no background process on the user's machine. State lives in Vast and in a small local file.
4. **Agent-first I/O.** JSON on stdout when not a TTY, human-readable when it is. Every error names a next action.
5. **Few verbs.** The command set should fit on one line of a README.
6. **Provider behind an adapter.** Commands, flags, output fields and messages use vasty terms. Credentials use the provider's variable, `VAST_API_KEY`.

### 2.1 Guardrails

- **Budgets are client-side.** vasty checks the daily cap before it spends. A direct `vastai` call, the dashboard, or a second machine with its own config can go past it. The account-level stop is a prepaid balance with autobilling off: at $0 Vast stops every instance. Vast's pages differ on later deletion, and stopped instances keep accruing storage. Vast has no spend-cap setting.
- **Owner is self-declared.** `VASTY_OWNER` is an environment variable. It stops an agent from releasing someone else's box by accident. Anyone with the API key can do anything.
- **The clock is enforced by vasty's own machinery** (§6). It is reliable to the degree the watchdog and sweep are, which is why `guard` is reported on every lease.

## 3. Concepts

| Term | Meaning |
|---|---|
| **Lease** | One rented machine plus an expiry time. Identified by a short id and an optional name. |
| **Box** | The machine behind a lease. "Lease" and "box" are used interchangeably. |
| **Job** | A process started on a box by `run` or `serve`. A box may host many jobs over its life. |
| **Clock** | The lease's expiry timestamp. Set when the box starts running, moved by `extend`. |
| **Budget** | A per-day dollar cap on the whole account. See §5.2. |
| **Profile** | A named bundle of defaults (hardware preferences, image, TTL). |
| **Group** | A label shared by several leases so they can be acted on together. Has no state of its own. |
| **Owner** | Who created a lease: an agent or human id. Scopes names and bulk operations. |

Rules:

- The lease is the box. Releasing the box ends every job on it.
- The clock starts when the container starts, which is when Vast starts charging GPU rent. Boot time (image pull, container start) is not counted against the TTL.
- The box is the authority on when it started. `onstart` writes `expires_at = now + ttl` to `/workspace/.vasty/clock` the moment the container starts (§6). The first vasty command that reaches the box over SSH copies that value to the label's `expires=`. `reserve` with wait does this before it returns; the probe (§3.2) does it otherwise. After that only `extend` changes it.
- A lease's effective expiry is `expires` from the label, else `created + ttl`. A box that never reaches SSH is destroyed once `now > created + ttl`, so the TTL also bounds boot.
- A lease expires when its clock runs out, whether or not a job is running on it. `status` warns when a job is at risk (§4.4) and `extend` is the way to keep it.
- `run` without `--on` reserves a box and releases it when the command exits. `run --detach` and `serve` without `--on` leave the box alive until `release` or expiry, and the response names the lease. `--name` without `--on` follows `reserve` idempotency (§4.1) and leaves the box alive. `--on LEASE` reuses that box and leaves it alive.
- vasty never makes a decision about one lease based on another. No auto-replacement, no dependency ordering, no rebalancing. Multi-box setups are many leases that share a group; anything smarter lives in the agent above vasty.
- `now` is the `Date` header of the latest provider response plus the local monotonic time since that response. When the header is missing or unparsable, vasty uses the local clock and adds a `clock_unverified` warning. `reserve`, `tag` and the sweep take `now` the same way.

### 3.1 Lease states

| State | Meaning |
|---|---|
| `pending` | Reserved and not ready: booting, SSH not answering, or the startup script still running. |
| `running` | Healthy and reachable. |
| `unreachable` | Provider says it exists, but the box stopped responding. Clock keeps running. |
| `stopped` | The provider stopped the instance, for example at $0 balance. The sweep still destroys it past its clock. |
| `expired` | Clock ran out; destroyed (or being destroyed). Kept in history for 24h. |
| `released` | Destroyed by `release`. Kept in history for 24h. |
| `gone` | Vanished with time left on its clock. Kept in history for 24h. |
| `orphan` | An instance on the account that vasty did not create. No clock until `tag` gives it one. |

A `running` lease with `0 < ttl_remaining_s <= warn_before_expiry` carries the `expiring_soon` warning. History states take precedence over `pending` and `unreachable`. `ttl_remaining_s` floors at 0.

vasty state follows the provider's `actual_status` and the probe:

| `actual_status` | Probe (§3.2) | State |
|---|---|---|
| null, `created`, `loading` | not run | `pending` |
| `running` | never answered | `pending` |
| `running` | answered before, fails now | `unreachable` |
| `running` | answers, startup unfinished | `pending` |
| `running` | answers, startup done or failed | `running` |
| `exited`, `stopped` | not run | `stopped` |
| `offline`, `unknown` | not run | `unreachable` |

The cache stores `reachable_at`, the last time the probe answered.

Each lease carries `guard` and `guard_missing`. `guard` is `full` when the watchdog is running, its destroy key is present, and the clock file matches the label. Otherwise it is `partial`, and `guard_missing` lists `watchdog`, `destroy_key` or `clock_file`. The sweep runs on every networked command and is not listed.

### 3.2 Probe

The probe is one SSH command. It reads `/workspace/.vasty/clock`, `/workspace/.vasty/guard`, `/workspace/.vasty/startup.exit`, the job records under `/workspace/.vasty/jobs/`, and the mtime of `/workspace/.vasty/alive`. `status` and the sweep run it on each `running` instance in parallel with a 5s timeout. `onstart` writes missing layers to `guard`. The watchdog touches `alive` each loop; an `alive` older than 3m means the watchdog is down. When the label lacks `expires`, the probe copies the clock file's value to the label. When the label has `expires` and the clock file differs, the probe rewrites the clock file. A probe that finds missing layers writes `miss=LAYERS` to the label.

## 4. Commands

```
vasty reserve   [--name NAME] [--group G] [--owner O] [--ttl 30m] [--profile P] [--startup FILE|-] [--no-wait] [--config -] [hardware flags]
vasty extend    TARGET  (--by 30m | --to 2h | --until TIME)
vasty release   TARGET [--yes]
vasty status    [TARGET] [--cached]
vasty run       [--on LEASE] [--detach] [--sync DIR] [reserve flags] -- COMMAND...
vasty serve     [--on LEASE] --model MODEL [--quant Q] [--bind-local] [reserve flags]
vasty sync      LEASE (push [--delete] SRC DEST | pull SRC DEST)
vasty ssh       LEASE [-- COMMAND...]
vasty tag       TARGET [--set-name NAME] [--set-group G] [--set-owner O] [--ttl 30m]
vasty config    (show | set KEY VALUE | profiles)
vasty completion (bash | zsh | fish)
```

Nine verbs plus `config` and `completion`. Every verb takes `--json`, `--plain` and `--verbose`. Spend is part of `status`. Adopting an orphan is `tag`.

Flag combinations:

- With `--on`, creation flags (name, group, owner, profile, ttl, hardware, ports, image, startup, no-wait) return `invalid_arguments`. `--sync` works with `run --on`.
- Auto-reserved `run` and `serve` reject `--no-wait`.
- `--config -` with `--startup -`, and either with interactive `ssh`, return `invalid_arguments`.
- `--json` with `--plain` returns `invalid_arguments`.

### 4.0 Targeting: `--group` and `--owner`

`extend`, `release`, `status` and `tag` take a **TARGET**. `run --on`, `serve --on`, `sync` and `ssh` take one lease id or name. A TARGET is one of:

```
LEASE                 a lease id or name (names are scoped to the current owner)
--group G             every active lease in group G
--owner O             every active lease owned by O
--all                 every active lease you own
--all --everyone      every active lease on the account, regardless of owner
```

`--group` and `--owner` can be combined (`--group exp42 --owner claude`). Bulk targets never include orphans. Name orphans by instance id.

Owner comes from, in order: `--owner` on the command (sets ownership at `reserve`, filters elsewhere), `VASTY_OWNER`, config `owner`, or `$USER`. An agent skill should set `VASTY_OWNER` to something stable like `claude-code` so its boxes are distinguishable from the human's.

Ids and names:

- Lease ids are `l-` plus 8 random hex digits. `reserve` redraws when the id is already in the instance list.
- `name`, `group` and `owner` match `[A-Za-z0-9][A-Za-z0-9._-]{0,62}`. A value outside that pattern, or a name matching `l-[0-9a-f]+` or `i-[0-9]+`, returns `invalid_arguments`.
- An orphan id is `i-` plus the Vast instance id.
- A LEASE resolves as an id first, then as a name under the selected owner. More than one match returns `ambiguous_target` with the matching ids.

Ownership rules:

- Names are unique per owner. Two owners can each have a lease named `ft`.
- Bulk writes (`extend`, `release`, `tag`) act on the current owner's leases, including `--group` writes. `--owner O` selects owner O instead. `--everyone` removes the owner filter and combines with `--all` or `--group`.
- Reads span every owner unless `--owner` filters them.
- `--all` combined with `--group` or `--owner`, `--everyone` combined with `--owner`, and a LEASE combined with any selector return `invalid_arguments`.
- A bulk target that matches no lease returns an empty result with exit 0.

Group rules:

- A group exists as long as at least one active lease carries the label. There is nothing to create or delete.
- Leases in a group may have different clocks, hardware, and owners. vasty shows each lease's own values.
- `extend --group G --by D` extends each lease by D. `extend --group G --to D` aligns them all to one expiry.
- Bulk `extend` is atomic with respect to budget: if extending the whole target would exceed the daily budget, nothing is extended and the response says how much budget remains.
- There is no batch reserve. An agent that wants three boxes calls `reserve` three times.

### 4.1 `reserve`

Rents a box. The clock starts when the box runs.

Hardware flags (all optional; profile and config supply defaults):

```
--gpu NAME          e.g. 4090, A6000, L40S, A100
--vram MIN_GB       minimum VRAM per GPU
--gpus N            number of GPUs (default 1)
--disk GB           disk size (default 50)
--image IMAGE       docker image (default from profile)
--max-price $/HR    ceiling on the offer's dph_total, GPU plus requested disk
--region R          optional
--ports N[,N...]    extra container ports to expose
```

Ports are fixed when a Vast instance is created; adding one later means recreating the container and renumbering external ports. So every `reserve` opens a small default set: `22` (SSH), `8000` (inference, used by `serve`), and `8080` (spare, for Jupyter or a user service). `--ports` adds to that, up to Vast's limit of 64. Ports are TCP integers from 1 to 65535. vasty deduplicates the list, defaults included, before the 64-port limit. An invalid list returns `invalid_arguments`. Vast maps each to a random external port; vasty reads the mapping from the instance's `ports` field and returns it in the `ports` field, and `serve` resolves the public URL from it. A required port with no mapping at the readiness deadline returns `port_mapping_missing`.

Behavior:

- Filters offers by the resolved constraints, then sorts by reliability descending, download bandwidth descending, `dph_total` ascending and offer id ascending.
- Writes the label at create with `lease`, `owner`, `created=now` and `ttl`. Vast's instance schema has no creation timestamp, so `created` lives in the label.
- Idempotent on name: `reserve --name X` when an active lease named `X` already exists returns that lease instead of creating a second one. The name check runs before offer search and the budget check. Flag mismatches produce a warning.
- Fails before spending if the projected spend would exceed the daily budget (§5.2).
- Draws the lease id before `create` and writes it into the create label. `provider.py` sends `create` with SDK retries off. On a timeout or connection error, `reserve` lists instances for that `lease=` label every 5s for up to 60s. One match is the lease. More than one: keep the lowest instance id and destroy the rest. None: return `provider_error` with the lease id in the hint, and send no second create.
- Waits until the lease leaves `pending` (skip with `--no-wait`). The wait ends at the effective expiry (§3). At that point `reserve` destroys the box and returns `box_unreachable`. A startup exit other than 0 ends the wait with a `startup_failed` warning.

Output (JSON mode):

```json
{
  "lease": "l-7f3a",
  "name": "trainer",
  "owner": "claude",
  "group": "exp42",
  "state": "running",
  "guard": "full",
  "guard_missing": [],
  "reused": false,
  "gpu": "RTX 4090",
  "gpus": 1,
  "vram_gb": 24,
  "price_per_hr": 0.38,
  "expires_at": "2026-10-29T01:04:00Z",
  "ttl_remaining_s": 1800,
  "ssh": "ssh -p 41022 root@198.51.100.7",
  "rsync_target": "root@198.51.100.7:",
  "ssh_port": 41022,
  "ports": {"22": 41022, "8000": 41080, "8080": 41081},
  "warnings": [],
  "swept": []
}
```

A hit on an existing lease returns it with `"reused": true`, a `flag_mismatch` warning listing differing flags, and no budget check. `--no-wait` returns `state: "pending"` with `expires_at`, `ttl_remaining_s`, `ssh`, `ssh_port`, `rsync_target` and `ports` set to `null`.

### 4.2 `extend`

Moves the clock. Exactly one of `--by`, `--to` (duration from now), or `--until` (timestamp). Returns the new `expires_at`. Refuses if the extension would exceed the daily budget (§5.2), and says by how much.

- A duration is a positive integer followed by `s`, `m`, `h` or `d`; units chain (`1h30m`). TIME is RFC 3339 with an offset. vasty stores times as UTC epoch seconds.
- A bulk `extend` takes one `now` for every target.
- An expiry at or before `now` returns `invalid_arguments` with the hint `vasty release`. An earlier expiry shortens the lease.
- A lease in history returns `lease_expired`. A lease whose clock file cannot be reached returns `box_unreachable` and changes nothing.
- `extend` writes the expiry as §6 describes. `extend` returns `lease_pending` until SSH answers. A lease running its startup script accepts `extend`.
- Bulk `extend` checks the budget once for the whole target, then writes each lease in turn and returns a per-lease array of `{lease, ok, expires_at, error}`. Each entry's `error` is a code from §7.

### 4.3 `release`

Destroys the box now. Returns a summary:

```json
{
  "lease": "l-7f3a",
  "name": "trainer",
  "uptime_s": 5820,
  "cost": 0.61,
  "jobs": [{"id": "j-1", "cmd": "python train.py", "exit": 0, "duration_s": 5400}]
}
```

Bulk targets return an array of summaries. Releasing an unknown lease returns `{lease, already_absent: true}` with exit 0 and a stderr line naming the lookup. A job still running at release has `"exit": null`. Releasing an orphan by instance id is allowed and requires `--yes` in non-TTY mode.

`release` returns when the provider accepts the destroy call, for `unreachable` leases too. The lease is `released` with `destroy_pending: true` until a list call shows it gone. `uptime_s` and `jobs` come from the local cache. A failed destroy returns `provider_error`. In TTY mode an orphan release prompts unless `--yes` is given. In non-TTY mode a missing `--yes` returns `confirmation_required`.

### 4.4 `status`

With no target: every active lease on the account, time remaining, cost so far, running jobs, orphans, and a totals line with today's spend, remaining daily budget, and current burn rate. With a target: those leases in detail; a single lease also includes a job log tail. Spend figures come from Vast's billing where available and from price × uptime between billing updates, and the output says which.

`status` is a networked command: it lists instances from Vast every time. `--cached` answers from the local file without a network call (fast, possibly stale, says so with a `cached_at` timestamp) for agents that poll tightly. `--cached` skips the sweep and reconciliation, returns `swept: []`, and derives warnings from cached data. It accepts a TARGET. `--verbose` adds per-lease detail that is normally hidden: full label, guard layer breakdown, instance id, image, ports, and the last provider error if any.

Also performs the **expiry sweep** (see §6) and **reconciliation** (see §8) as side effects. The sweep can destroy an expired box, so anything it released appears in a `swept` array in the output and as a line in human mode.

Output always includes a `warnings` array. Each entry has `code`, `lease` (`null` for account warnings), `message`, and `fix`, one runnable vasty command. Warning codes: `expiring_soon`, `expiring_with_running_job`, `box_unreachable`, `orphan`, `guard_partial`, `expired_with_running_jobs`, `budget_low`, `startup_failed`, `flag_mismatch`, `clock_unverified`, `label_unreadable`, `spend_unavailable`, `cache_rebuilt`. `expiring_with_running_job` replaces `expiring_soon` on a lease that has a live job.

Fixes: `expiring_soon` and `expiring_with_running_job` use `vasty extend L --by 30m`. `box_unreachable` and `guard_partial` use `vasty release L`. `orphan` uses `vasty tag ID --ttl 30m`. `startup_failed` uses `vasty ssh L -- cat /workspace/.vasty/startup.log`. `budget_low` and `spend_unavailable` use `vasty status`. Fixes shell-quote their arguments.

Human-mode output for an account with an experiment group, a served sub-agent, a dead host, an orphan, and another owner's box:

```
$ vasty status
LEASE    NAME        GROUP   OWNER    GPU        STATE        EXPIRES  $/HR   COST   JOBS
l-7f3a   trainer     exp42   claude   2× A100    running      1h12m    2.40   4.86   j-1 train.py (running 2h01m)
l-8b10   eval-0      exp42   claude   L40S       running      12m      0.82   0.71   j-2 vllm (serving :8000)
l-8b11   eval-1      exp42   claude   L40S       unreachable  12m      0.82   0.68   j-3 vllm (unknown)
l-8b12   eval-2      exp42   claude   L40S       running      ⚠ 3m     0.82   0.70   —
l-9c21   subagent    —       claude   A6000      running      44m      0.55   0.12   j-1 qwen3-72b (serving :8000)
l-a003   scratch     —       nick     4090       running      19m      0.38   0.05   —
i-55120  —           —       ?        3090       orphan       none     0.22   ?      —

WARNINGS
  l-8b12  expiring_soon       3m left                      fix: vasty extend l-8b12 --by 30m
  l-8b11  box_unreachable     no answer for 6m             fix: vasty release l-8b11
  i-55120 orphan              not created by vasty           fix: vasty tag i-55120 --ttl 30m
  l-7f3a  guard_partial       watchdog not running         fix: vasty release l-7f3a

TODAY  spent $7.12 of $10.00  ·  6 leases live (5 yours)  ·  burning $6.01/hr
```

Group view:

```
$ vasty status --group exp42
GROUP exp42 · 4 leases · 3 healthy, 1 unreachable · expiries 3m–1h12m · $6.95 so far · $4.86/hr
  l-7f3a trainer  running      1h12m   j-1 train.py running
  l-8b10 eval-0   running      12m     j-2 serving
  l-8b11 eval-1   unreachable  12m     j-3 unknown
  l-8b12 eval-2   running      ⚠ 3m    idle
```

JSON mode returns the same data in a flat structure: a `leases` array (each with `lease`, `name`, `group`, `owner`, `state`, `guard`, `guard_missing`, `gpu`, `price_per_hr`, `cost`, `cost_source`, `expires_at`, `ttl_remaining_s`, `jobs`), a `warnings` array, and a `totals` object. Agents filter by `group` or `owner`.

```json
{
  "leases": [
    {"lease": "l-8b12", "name": "eval-2", "group": "exp42", "owner": "claude",
     "state": "running", "guard": "full", "guard_missing": [], "gpu": "L40S", "price_per_hr": 0.82,
     "cost": 0.70, "cost_source": "billing", "expires_at": "2026-10-29T05:23:00Z", "ttl_remaining_s": 180, "jobs": []}
  ],
  "warnings": [
    {"code": "expiring_soon", "lease": "l-8b12", "message": "3m left", "fix": "vasty extend l-8b12 --by 30m"}
  ],
  "totals": {"spent_today": 7.12, "daily_budget": 10.00, "remaining_budget": 2.88, "burn_per_hr": 6.01, "live": 6, "live_mine": 5,
             "spend_source": "billing", "daily_budget_source": "user"},
  "swept": [],
  "cached_at": null
}
```

- `status` returns `{leases, warnings, totals, swept, cached_at}`. `cached_at` is `null` on a fresh result.
- `cost_source` is `billing`, `estimated` or `mixed`. A single-lease target adds `log_tail`, the last 100 lines.
- Orphans appear in `leases` with `lease` set to the `i-` id, `state: "orphan"`, and `owner`, `expires_at`, `ttl_remaining_s` and `guard` set to `null`.
- `totals` covers the whole account. `spend_source` and `daily_budget_source` name where the figures came from.
- A `swept` entry is `{lease, name, expired_at, ok, error}`.
- Every networked command sweeps all managed leases on the account before it resolves its target. Its JSON carries `warnings` and `swept`.

### 4.5 `tag`

The one verb for labels. Sets or changes `name`, `group`, and `owner` on existing leases, and gives a clock to an orphan.

- On a lease, `--set-name`, `--set-group` and `--set-owner` rewrite the label. `--group` and `--owner` select targets (§4.0). `tag ft --set-group exp42` moves a box into a group. `tag --group old --set-group new` renames a group across every member. An empty value clears `name` or `group`.
- On an orphan (by instance id): `tag i-55120 --ttl 30m` writes a `vasty:` label with the owner from `--set-owner`, or the current owner, plus `created=now`, `ttl`, and `expires = now + ttl`. It then writes the same expiry to the box's clock file and installs the watchdog. `--ttl` is required for an orphan because it has no clock yet. The orphan's own age is ignored; its clock starts at adoption. Adoption is never refused by the budget; `tag` returns a `budget_low` warning when the projection (§5.2) passes `daily_budget`. This is the only way an orphan becomes a lease.
- `tag` writes the label first and keeps it if a later step fails. It then connects over SSH (§5.3), writes the clock file, copies `CONTAINER_ID` and `CONTAINER_API_KEY` from `/proc/1/environ` to `/workspace/.vasty/env`, and starts the watchdog under cron or `nohup`. A failed step returns the lease with `guard: partial` and a `guard_partial` warning; the sweep enforces the clock. Later networked commands retry the missing steps. A container restart removes the watchdog from an adopted box.
- `tag` on an existing lease leaves the clock alone.
- `--set-name` needs a single LEASE. On a bulk target it returns `invalid_arguments`. A name used by another active lease of the same owner returns `name_conflict`. `--set-owner` checks the new owner's names.
- `--ttl` on a lease returns `invalid_arguments` with the hint `vasty extend`. An orphan without `--ttl` returns `invalid_arguments`.
- `tag` with no setter and no `--ttl` returns `invalid_arguments`.
- `tag` returns `{results, warnings, swept}`. Each result holds `lease`, `name`, `group`, `owner`, `expires_at`, `ttl_remaining_s`, `guard` and `guard_missing`.

### 4.6 `run`

Executes a command on a box.

- No `--on`: reserve a box with the given flags, run the command, stream output, release when it exits. The default TTL for an auto-reserved `run` box is the profile's `run_ttl` (default 2h), since jobs are longer than interactive sessions. `--ttl` overrides it. Auto-reserve runs the §5.2 check with `run_ttl`.
- **The clock applies to jobs.** A job still running at expiry dies with the box.
- `run` warns on stderr when the box's remaining clock is under `warn_before_expiry` at job start, and prints the `extend` command.
- `status` reports `expiring_with_running_job` for a lease with a live job under the warn threshold (§4.4).
- A lease whose clock ran out with a job alive stays in history as `expired` with an `expired_with_running_jobs` warning.
- `--on LEASE`: run on the existing box, leave it alive.
- `--detach`: start the job under a supervisor on the box (tmux), return a job id immediately, log to a file on the box. `status LEASE` reports the job; `vasty ssh` or `sync pull` fetches logs. A foreground `run` also starts its job under tmux.
- Working directory on the box is `/workspace`. `run` does not sync code; pair it with `sync push` or use `--sync DIR` as sugar for push-then-run.
- On SIGINT, `run` forwards SIGINT to the remote job, waits up to 10s, then exits 130. An auto-reserved box is released. Named and `--on` boxes stay alive. Detached jobs continue after the client exits.
- **Losing the attach keeps the box.** After the job starts, an SSH drop or an error while streaming output leaves the box up and the job running within its clock. `run` prints the lease, the job id, the expiry, `vasty status LEASE` and `vasty release LEASE` on stderr when stderr still works. No client is attached, so the box stays up after the job exits until `release` or the clock ends. SIGINT is the one way to cancel from the client.

Errors before the job starts use §7 codes. After the job starts, `run` exits with the remote exit code, and the result object carries `exit` or `error` so a job's `2` differs from a provider error. `--detach` exits 0 once the job starts. A job killed with its box returns `lease_expired`, exit 2. A dropped connection returns `box_unreachable`, exit 2.

### 4.7 `serve`

Brings up a model behind an OpenAI-compatible endpoint.

- Maps `--model` (and optional `--quant`) to hardware: required VRAM, acceptable GPU tier, image. The mapping is the `[models."NAME"]` tables in config. v1 ships the Qwen entry in §5. `--vram`, `--gpu`, `--quant` and `--image` override an entry. A model with no entry needs `--vram` and `--image` to auto-reserve, else `model_unknown`. A path is a directory on the box.
- Launches an inference server (vLLM by default), waits for `/v1/models` to answer, returns the URL.
- Without `--on`, `serve` reserves a box with `run_ttl` and the §5.2 check. A failed `serve` releases a box it reserved. A served model is a job; the box is still the lease.

Output:

```json
{
  "lease": "l-9c21",
  "job": "j-1",
  "model": "Qwen/Qwen3-72B-Instruct",
  "url": "http://198.51.100.7:41080/v1",
  "api_key": "vasty-local-xxxx",
  "expires_at": "2026-10-29T02:04:00Z"
}
```

The endpoint dies with the lease.

Exposure:

- The endpoint is public on the external port mapped to container port 8000. Every Vast instance has a public IP, and SSH on port 22 is already reachable the same way; the API key is what protects the endpoint.
- vasty generates a fresh 32-byte random key per job and never reuses one. It starts vLLM with `--api-key KEY --host 0.0.0.0 --port 8000` and polls `/v1/models` with that key. A request without the key gets 401.
- `api_key` appears once in `serve`'s output. Human mode prints it with a note that it will not be shown again.
- `--bind-local` starts vLLM on `127.0.0.1` for users who tunnel with `vasty ssh -L`. The user holds the tunnel; vasty runs no local process.
- The vLLM image is pinned in the model table, so a vulnerability in the HTTP layer is fixed by bumping the pin.

### 4.8 `sync`

`push SRC DEST` and `pull SRC DEST` wrap rsync over the lease's SSH connection. Default excludes are `.git`, `__pycache__`, `.venv`, and `node_modules`. `--delete` on push makes the box mirror your tree exactly. Fetch large datasets from the box itself inside `run` (from S3, Hugging Face, etc.). Skills use `sync` instead of assembling scp strings from JSON.

A relative remote path resolves under `/workspace`. rsync trailing-slash rules apply. `--sync DIR` pushes the contents of DIR into `/workspace/` before the job starts. A failed transfer returns `sync_failed` and starts no job; an auto-reserved box is released. A missing local `ssh` or `rsync` returns `dependency_missing`.

### 4.9 `ssh`

Opens a shell or runs a one-off command.

### 4.10 `config`

- `show` prints each effective value and its source (`flag`, `stdin`, `profile`, `env`, `project`, `user`, `default`).
- `set KEY VALUE` writes to the user config file. KEY is a dotted TOML path (`defaults.ttl`, `profiles.big.vram`). VALUE parses as a TOML scalar.
- `profiles` lists named profiles.

## 5. Configuration

Resolution order, highest first:

1. Command-line flags
2. `--config -` (JSON on stdin)
3. `--profile NAME`
4. Environment variables (`VASTY_*` and the variable named by `api_key_env`)
5. Project file `./vasty.toml` or `./.vasty/config.toml`
6. User file `~/.config/vasty/config.toml`
7. Built-in defaults

- `--config -` reads a JSON object from stdin using the `[defaults]` keys, matching the AWS-CLI `--cli-input-json` habit.
- `./vasty.toml` wins over `./.vasty/config.toml`. Profiles merge by name and field across files before the selected profile applies.
- Each `[defaults]` key maps to `VASTY_<KEY>` in upper case. Unknown keys or bad types return `invalid_config`.
- Built-in defaults: `ttl` 30m, `run_ttl` 2h, `max_price` 0.60, `daily_budget` 10.00, `warn_before_expiry` 5m, `disk` 50, `gpus` 1, `image` `vasty/base:cuda12.4`.

Example user config:

```toml
api_key_env = "VAST_API_KEY"
owner = "nick"            # overridden by VASTY_OWNER or --owner
ssh_key = "~/.ssh/id_ed25519"

[defaults]
ttl = "30m"
run_ttl = "2h"
max_price = 0.60
daily_budget = 10.00
warn_before_expiry = "5m"
image = "vasty/base:cuda12.4"
disk = 50

[profiles.small]
gpu = "4090"
vram = 24

[profiles.big]
gpu = "A100"
vram = 80
max_price = 2.50

[models."Qwen/Qwen3-72B-Instruct"]
vram = 80
quant = "awq"
image = "vllm/vllm-openai:v0.6.3"
```

### 5.1 Base image and startup hooks

vasty ships a **known base image** and uses it by default. It is built from Vast's official `vast-ai/base-image` and adds only what vasty itself needs: sshd, cron, rsync, tmux, curl, python3, and the watchdog script. vasty tests everything against this image, so `run`, `sync`, and `serve` behave the same on every box.

Startup hooks run a user script on each box:

```toml
[defaults]
image = "vasty/base:cuda12.4"          # the default
startup_file = "setup.sh"            # path to a bash script

[profiles.ft]
startup = '''
pip install -U transformers peft
apt-get install -y ffmpeg
'''
```

- `startup` runs once on the box after vasty's own `onstart` (the watchdog and sshd setup), as root, in `/workspace`, with the lease's env available. Its output is logged to `/workspace/.vasty/startup.log` and the box is reported `pending` until it exits 0. A non-zero exit makes the lease `running` with a `startup_failed` warning; the box is not released, so you can `ssh` in and look.
- Setting both `startup_file` and `startup` returns `invalid_config`. A config path resolves relative to its config file; a CLI path resolves relative to the working directory. The wrapper writes started and exit markers under `/workspace/.vasty/`. A restart skips a hook that already started. A hook cut off by a restart reports `startup_failed`.
- `--startup FILE` on `reserve`, `run`, and `serve` overrides the profile for one lease. `--startup -` reads the script from stdin.
- `--image` selects a different base. vasty then installs its essentials via `onstart` if they are missing, at the cost of a slower boot, and marks `guard: partial` if it cannot get the watchdog running. A custom image needs Linux, bash, root and apt-get. Otherwise `reserve` returns `image_unsupported`.
- `serve` installs the pinned vLLM version into `/workspace/.vasty/venv` when absent, `--on` boxes included. An install failure returns `serve_failed`.
- vasty builds `onstart` from the clock-file write, the startup wrapper and the user's `startup` script, compressed with gzip and base64. With `--image`, `onstart` also carries the watchdog and the essentials installer. When the encoded `onstart` exceeds 4048 characters, `reserve`, `run` and `serve` return `startup_too_large` before any create call. The wrapper writes the exit code to `/workspace/.vasty/startup.exit` and the output to `/workspace/.vasty/startup.log`.

vasty maintains the image. You maintain the startup script.

### 5.2 Budget

`daily_budget` caps projected spend for the account on a UTC calendar day. `reserve`, `extend`, `run`, `serve` and `tag` compute:

```
projected = spent_today
          + Σ managed leases: dph_total × hours from now to effective expiry, floored at 0
          + new lease: dph_total × ttl          (reserve, run, serve)
          + target leases: dph_total × extension (extend)
          + orphan: dph_total × ttl              (tag)
```

- `spent_today` is billed charges from 00:00 UTC through `covered_through`, for every instance on the account, deleted ones included, plus `dph_total` × time since `covered_through` for each live instance, clipped to today. When coverage cannot be read, spending commands return `spend_unavailable` and `status` reports null spend with a `spend_unavailable` warning. A live test confirms the charges endpoint clips to the day range (§12).
- `dph_total` is the offer's GPU price plus disk. Search passes `storage = disk`, so `dph_total` covers the requested disk.
- Orphans count in `spent_today` only. `tag` adds `dph_total × ttl` for the orphan.
- `extend` replaces each target's current commitment with the new one. A change that holds or lowers the projection always passes.
- Remaining time on a live lease counts on the day the check runs, even when it crosses midnight.
- The scope is the whole account. Two owners sharing an API key share the budget.
- `daily_budget` has no flag and no profile key. It resolves from `VASTY_DAILY_BUDGET`, the project file, the user file, then the built-in default.
- Refusal returns `budget_exceeded`, exit code 3. It puts `projected` (with the action), `remaining` (`daily_budget` minus the projection without the action) and `daily_budget` in `details`.
- `tag` on an orphan is never refused; it warns with `budget_low` instead, since the box is already billing.
- Billing data is fresh for 60s. Money uses decimal arithmetic and prints to 2 places.
- `budget_low` fires when the projection reaches 90% of `daily_budget`.
- `burn_per_hr` sums `dph_total` over live leases and orphans.
- `reserve`, `extend`, `run` and `serve` hold the `leases.json` lock from the name check and budget check until the provider call returns. Separate machines check independently.

### 5.3 SSH access

vasty connects as root with the key at config `ssh_key` (default: the first of `~/.ssh/id_ed25519` and `~/.ssh/id_rsa`). `reserve` registers the public key on the account before create when no matching key exists. `tag` attaches it to an orphan. vasty creates instances with `runtype` `ssh_direct` when the offer has direct ports, else `ssh_proxy`. It connects to `public_ipaddr` and the port mapped to 22, or `ssh_host` and `ssh_port` for proxy. ssh runs with `StrictHostKeyChecking=accept-new`, `UserKnownHostsFile=~/.local/state/vasty/known_hosts` and `HostKeyAlias=vast-<instance id>`.

## 6. Expiry enforcement (no daemon)

The clock is enforced even when no one is running `vasty`. Vast has no `max_duration`, `auto_stop`, or `expires_at` field on an instance, so expiry is vasty's responsibility. v1 has two layers. A third is planned for v1.1.

1. **On the box (primary).** `reserve` injects a watchdog via `onstart`. Vast injects `CONTAINER_ID` and a per-instance `CONTAINER_API_KEY` into every container. Its docs show `vastai destroy instance $CONTAINER_ID` run from inside, and Vast's own base image uses the same call in its provisioner. The watchdog:
   - reads `expires_at` from `/workspace/.vasty/clock`, so it does not depend on the container key being able to read or write labels. `onstart` writes `now + ttl` to the file only when it is absent, so a container restart keeps an extended value. `extend` and the probe rewrite the file over SSH;
   - reads `CONTAINER_ID` and `CONTAINER_API_KEY` from `/workspace/.vasty/env`, which `onstart` writes with mode 600;
   - sleeps until then, re-reads the clock file (so a late `extend` is honored), and if still expired calls `DELETE /api/v0/instances/$CONTAINER_ID/` with the container key;
   - runs under cron every minute alongside the sleeping process, so a killed watchdog is restarted.

   `CONTAINER_API_KEY` is bound to the box's own public IP and is documented as occasionally absent. When `onstart` finds it missing, the lease is `guard: partial` with `destroy_key` listed, and the sweep is the enforcer. A per-lease scoped key as a fallback is a v1.1 candidate.

2. **Local sweep.** Every networked `vasty` command lists instances, reads each `vasty:` label, and destroys anything past its clock. Catches a dead watchdog. Cheap because it piggybacks on the list call `status` already makes. Anything it destroys is reported in `swept`. Sweep rules:
   - A label with `expires=` is past its clock when `now > expires`.
   - A label without `expires=` is past its clock when `now > created + ttl`. Only `reserve` produces such a label; `tag` always writes `expires`.
   - The probe (§3.2) fills `expires=` from the clock file on the first SSH contact. If the clock-file write in the other direction fails, the label keeps its value and the lease reports `guard_missing: [clock_file]`. The next probe rewrites the file.

3. **Provider scheduled job (optional, v1.1).** Vast's scheduled-jobs API (`/commands/schedule_job/`) can call `DELETE /instances/{id}/` on a cadence between a start and end time. Add it after a live test confirms its first-fire behavior (§12). v1 does not depend on it.

`extend` writes the new expiry to the instance label (which the sweep reads) and to `/workspace/.vasty/clock` over SSH (which the watchdog reads). Write order keeps the earlier-firing enforcer behind what `extend` reports: when lengthening, write the clock file first and the label second; when shortening, the label first and the clock file second. If the second write fails, `extend` restores the first, fails with `provider_error`, and the lease shows `guard: partial` until the next successful write.

Robustness:

- A clock-file value at or before `now` destroys the box at once.
- Clock-file writes go to a temp file and rename.
- The watchdog holds a lock file so cron starts at most one.
- A failed destroy retries with backoff capped at 60s.
- An unreadable clock file is logged and re-read within 60s. The probe reports it as `guard_missing: [clock_file]`.
- Before destroying or writing a label, a command re-reads the instance row and aborts when `expires` differs from the value it read. A window remains between that read and the write: two clients acting on one lease inside it can lose an `extend` or destroy a just-extended box. vasty accepts this race. If the restore in an `extend` also fails, `extend` returns `provider_error` naming both values, and the next networked command rewrites the clock file from the label.

Interruptible (bid) instances stop when outbid, and vasty does not rely on this for expiry.

## 7. Output and errors

- JSON on stdout when stdout is not a TTY; tables when it is. `--json` and `--plain` force either.
- Diagnostics go to stderr. stdout is a single parseable object in JSON mode.
- In JSON mode, attached `run` and `sync` send remote and rsync output to stderr and write one result object to stdout when they finish. Interactive `ssh` uses the terminal and emits no JSON. `ssh LEASE -- COMMAND` passes remote stdout, stderr and exit code through.
- Bulk results are `{results, warnings, swept}`; each result has `lease`, `ok` and nullable `error`. Single `extend` returns `{lease, expires_at, ttl_remaining_s, warnings, swept}`. Detached `run` returns `{lease, job, log_path, expires_at, warnings, swept}`. Attached `run` returns `{lease, job, exit, duration_s, released, warnings, swept}`. `sync` returns `{lease, direction, src, dest, warnings, swept}`. `config` returns `{values}`, `{key, value}` or `{profiles}`.
- Every error object has `error` (the stable code), `message`, `hint`, and optional `details`:

```json
{
  "error": "no_offers",
  "message": "No offers match gpu=4090 under $0.40/hr.",
  "hint": "Try --max-price 0.60, --gpu 3090, or relax --region."
}
```

| Code | Exit | Raised when |
|---|---|---|
| `invalid_arguments` | 1 | a flag combination, name, duration, TIME or port list is invalid |
| `invalid_config` | 1 | a config key or value is invalid |
| `auth_missing` | 1 | no API key |
| `dependency_missing` | 1 | `ssh` or `rsync` is not on PATH |
| `no_offers` | 1 | no offer matches |
| `lease_not_found` | 1 | unknown id or name |
| `ambiguous_target` | 1 | a name or id matches more than one active lease |
| `orphan_unmanaged` | 1 | an orphan id is passed to `extend`, `run`, `serve`, `sync` or `ssh` |
| `lease_expired` | 1 | the lease is in history |
| `lease_pending` | 1 | `extend`, `run --on`, `serve --on`, `sync` or `ssh` on a lease SSH cannot reach yet |
| `name_conflict` | 1 | a new name matches another active lease of the same owner |
| `confirmation_required` | 1 | orphan `release` without `--yes` in non-TTY mode |
| `model_unknown` | 1 | `serve` model has no table entry and no `--vram` and `--image` |
| `image_unsupported` | 1 | a custom image lacks bash, root or apt-get |
| `startup_too_large` | 1 | the encoded `onstart` exceeds 4048 characters |
| `provider_error` | 2 | a provider call fails |
| `box_unreachable` | 2 | the box does not answer SSH |
| `spend_unavailable` | 2 | billing coverage for today cannot be read |
| `sync_failed` | 2 | rsync fails |
| `serve_failed` | 2 | the inference server fails to install or exits before `/v1/models` answers |
| `port_mapping_missing` | 2 | a required port has no external mapping at the readiness deadline |
| `budget_exceeded` | 3 | the projection passes `daily_budget` |

Exit 0 covers success, warnings and empty bulk results. A bulk command exits with the highest exit code among failed entries. Parser errors use the same error object. `run` and `ssh -- COMMAND` exit codes follow §4.6.

## 8. State

### 8.0 The lease lives on the provider

Vast instances carry a free-text `label` (≤1024 chars), settable at create and via `PUT /instances/{id}/`, returned on every instance row. vasty stores the lease itself there, so the provider is the source of truth:

```
vasty:v1;lease=l-7f3a;name=trainer;owner=claude-code;group=exp42;created=1793235840;ttl=10800;expires=1793247000
```

- Any machine on the account sees the same leases, owners, and groups.
- An **orphan** is an instance whose label does not start with `vasty:`.
- Group sizes come from parsing `group=` in each `vasty:` label. The list call follows `next_token`.

Labels are `;`-separated `key=value` fields with unique keys. `lease`, `owner`, `created` and a positive integer `ttl` are required; `expires` and `miss` are optional. Times are UTC epoch seconds. Metadata updates keep unknown fields. A generated label over 1024 characters returns `invalid_arguments`. A `vasty:` label with an unknown version or missing fields shows as `orphan` with a `label_unreadable` warning. The sweep and bulk writes skip it, `tag` refuses it, and `release` by instance id works.

Label format is versioned (`vasty:v1`) so it can change later without breaking older boxes.

### 8.1 Local cache

A single file, `~/.local/state/vasty/leases.json`, is a **cache** of the label data plus things the provider does not hold: job records (command, start time, exit code, log path). It exists so that `status` on a cached lease can answer instantly without a network call, and so that job history survives a box being destroyed.

Each job also writes `/workspace/.vasty/jobs/<job-id>/` on the box with command, start time, pid, exit code and log. Job ids are unique per lease. The probe reads these records and the cache stores them. An unreachable box reports its jobs as `unknown` with `exit: null`. A lost cache loses records of destroyed boxes only.

Reconciliation runs on every networked command:

- A lease in the file that Vast no longer lists moves to history: `released` when this machine released it, `expired` when its effective expiry has passed, otherwise `gone`.
- An instance on Vast with a `vasty:` label that is not in the file is adopted into the file silently (another machine made it).
- Expired, released and gone leases stay in history for 24h so an agent can find out what happened to a job, then are pruned. The 24h window starts when vasty first sees the lease gone.

vasty takes an exclusive lock on `leases.json.lock` for each read-modify-write and replaces the file by temp file and rename. A corrupt file is rebuilt from the provider with a `cache_rebuilt` warning.

### 8.2 Messy cases

For mess, vasty shows the state and gives the one-line fix.

| Case | What vasty does |
|---|---|
| Group leases on different clocks | Allowed. `status --group` shows the expiry range. `extend --to` aligns them if wanted. |
| Box dies with time left on the clock | State becomes `unreachable`. Clock keeps running. Warning suggests `release` and re-reserve. |
| Job still running when the clock expires | See §4.6. |
| Box never leaves `loading` | See §3. `reserve` without `--no-wait` gives up at the effective expiry, destroys the box, and returns `box_unreachable`. |
| Local state file lost | Leases are rebuilt from instance labels on the next networked command. Only job history of destroyed boxes is lost. |
| Box made in the Vast dashboard, or by another tool | No `vasty:` label, so shown as `orphan`. Untouched until `tag` or `release` by instance id. |
| Two owners `reserve --name ft` at the same time | Names are per owner, so two boxes. On one machine the lock makes the second call return the first lease. Two machines can create two; a later command naming it returns `ambiguous_target`. |
| Bulk extend would cross the daily budget | See §4.0. |
| Expiry guard could not be fully set | Lease is `guard: partial` with the missing layers listed. Warning on every `status` until fixed or released. |
| Agent crashes or loses its attach mid-`run` on an auto-reserved box | See §4.6. The job keeps running until it exits or the clock runs out, and the box stays up after the job exits. Next `status` shows it with the job state and warns as expiry nears; the agent can `release`, `extend`, read the log with `vasty ssh`, or let it finish. |
| `release --all` from an agent on a shared account | Only that owner's leases. The human's `scratch` box survives unless `--everyone` was passed. |

## 9. Workflows

### 9.1 Post-training from a coding agent

```
vasty reserve --name ft --profile big --ttl 3h
vasty sync ft push ./ /workspace/
vasty run --on ft --detach -- python train.py --config cfg.yaml
# ... agent does other work, polls ...
vasty status ft              # expiring_with_running_job? then:
vasty extend ft --by 1h
vasty sync ft pull /workspace/out/ ./out/
vasty release ft             # returns cost + job exit codes for the report
```

A Claude Code skill can wrap exactly this, using `release`'s summary as the report.

### 9.2 Sub-agent spin-up

```
vasty serve --model Qwen/Qwen3-72B-Instruct --ttl 1h
# -> {"url": "http://.../v1", "api_key": "...", "expires_at": ...}
```

The local harness points its OpenAI-compatible client at `url`. If the harness also needs a sandbox VM, a second `vasty reserve --name sandbox` provides it. Both expire on their own.

### 9.3 Reuse a warm box

```
vasty run --on ft -- python eval.py
vasty serve --on ft --model ./out/checkpoint
vasty release ft
```

### 9.4 Multi-box experiment with a group

```
export VASTY_OWNER=claude-code
vasty reserve --name trainer --group exp42 --profile big --ttl 3h
for i in 0 1 2; do vasty reserve --name eval-$i --group exp42 --gpu L40S --ttl 1h; done
vasty status --group exp42                 # one line per box, expiry range, group cost
vasty extend --group exp42 --to 2h         # align every clock
vasty release --group exp42                # tear down the experiment, get per-box summaries
```

## 10. Implementation decisions

### 10.1 Language: Python

vasty is written in Python.

- **The hard parts are Python-shaped.** The on-box watchdog, `onstart` scripts, `serve` launching vLLM and polling its health, and model-to-VRAM sizing all live in Python's world. Writing them from TypeScript means generating Python and shell from TS strings.
- **The official client absorbs API drift.** The `vastai` package backs off on 429 and 502/503/504, honoring `Retry-After` when present, and handles the search daily quota, which vasty does not retry, the `on-demand`/`ondemand` inconsistency, and the v0 → v1 migration.
- **Distribution.** `uvx vasty` runs with no install, like `npx`.
- **Users are ML people.** Python is on their machines.

Accepted costs: startup is ~200ms when the SDK is imported (mitigated below), and Python's type system is weaker than TS's (mitigated with strict mypy and dataclasses for every output shape).

### 10.2 Dependencies: exactly one

```
vasty → vastai → Vast
```

`vastai` is the only runtime dependency, pinned to a known version. vasty adds policy (clocks, budgets, owners, groups) and leaves plumbing to `vastai`. Everything else is standard library: `argparse`, `json`, `tomllib`, `subprocess` for `rsync`/`ssh`, `dataclasses`. vasty needs Python 3.11 or newer, and `ssh` and `rsync` on PATH.

The `vastai` package has itself churned recently (`vastai-sdk` was deprecated and merged into `vastai`; CLI and SDK ship together). vasty isolates the package:

- Every SDK call goes through a single `provider.py`. No `vastai` type or call appears above that file.
- `provider.py` is the adapter boundary for a future second provider. It exposes ten functions: `search_offers`, `create`, `list_instances`, `get_instance`, `destroy`, `set_label`, `charges`, `balance`, `list_ssh_keys`, `attach_ssh_key`. `create` takes the label. `set_label` backs `tag` and `extend`. `charges` wraps `show_invoices_v1(charges=True)` with a UTC-day range.

### 10.3 Performance: lazy imports, no compilation

vasty does not compile (PyInstaller, Nuitka). Startup cost comes from imports, so a binary saves 10–20% while adding a five-platform build matrix, macOS signing and notarization, 30–80MB artifacts, and antivirus false positives.

vasty uses lazy imports:

- `vasty --help`, `vasty config show`, `vasty status --cached`, and `vasty completion` import only the standard library. Target: under 50ms.
- `reserve`, `extend`, `release`, `tag`, and any reconciliation import `vastai` inside the function that needs it. Target: under 250ms before the HTTP round-trip.
- `import vastai` loads aiohttp and the serverless clients. Measure it on day one. Over 250ms, `provider.py` calls the REST endpoints through `requests`.
- Verify on day one with `python -X importtime` and keep a budget in CI.

Nuitka can produce a static binary from the same source later if demand appears.

### 10.4 Distribution

- **Headline:** `uvx vasty reserve`. This is the first line of the README and the line in the Claude Code skill.
- **Permanent install:** `uv tool install vasty` or `pipx install vasty`.
- **Source of truth:** PyPI only.
- **Shell completions:** shipped in the package (`vasty completion bash|zsh|fish`), including lease names and group names from the cache.
- **Homebrew tap:** later, if humans ask. Not v1.

### 10.5 Provider facts that shaped the design

Confirmed against docs.vast.ai (OpenAPI spec at `/api-reference/openapi.yaml`) and the `vastai` 1.9.1 source:

| Fact | Effect on vasty |
|---|---|
| Base URL `https://console.vast.ai/api/v0`; auth is `Authorization: Bearer <key>` | SDK uses `requests` over HTTPS |
| Search is `POST /bundles/` with `{field:{op:value}}` JSON; the `gpu_name=RTX_4090` syntax is client-side sugar | vasty builds the query dict and passes it to SDK `search_offers` with `no_default=True` and `storage` set to the requested disk |
| Create is `PUT /asks/{offer_id}/`; only `image` is required; returns `new_contract` as the instance id | `reserve` is one call after search |
| No server-side expiry field | Watchdog-first guard stack (§6) |
| `label` is a single ≤1024-char string, settable and returned on every row | Lease data lives in the label (§8.0) |
| `start_date` is "Instance start time"; the SDK computes age as `now - start_date` | vasty does not use it. The box's clock file is the authority on paid time (§3). |
| `GET /charges/` is per-instance with GPU/disk/bandwidth breakdown; `GET /users/current` has `balance` | `status` totals report real numbers, estimates between billing updates |
| Rate limits are unnumbered per-endpoint intervals; 429 bodies are sometimes plain text; search has a daily quota | SDK's retry logic is used as-is; `status` polling is gentle; search quota errors are surfaced, never retried |
| Responses are loosely typed (`extra_env` as pair array, `ports` absent until running, 404 sometimes means unauthorized) | All normalized inside `provider.py` |
| `/api/v1/instances/` and `/search/asks/` are the newer style; `/bundles/` may be deprecated | Another reason the adapter is one file |
| Instances get `CONTAINER_ID` and a per-instance `CONTAINER_API_KEY`; Vast's docs and base image show self-destroy with it | The watchdog is a supported pattern; when the key is absent the lease is `guard: partial` and the sweep enforces |
| `balance_threshold` is the autobilling trigger; there is no spend-cap field | See §2.1. |
| `onstart` is limited to 4048 characters | vasty compresses it and refuses larger scripts |
| Ports are fixed at creation (`-p N:N` in `env`), no ranges, 64 max, random external numbers | `reserve` always opens 22, 8000, 8080; `serve --on` works on any vasty box |

## 11. Non-goals (v1)

- Scheduling, queues, or fleet management
- Multi-provider support
- A long-running daemon or web UI
- Spot/interruptible instances
- Secrets management beyond reading the API key from the variable named by `api_key_env` (default `VAST_API_KEY`)

## 12. Open questions

- MCP: ship a thin wrapper over the CLI later if demand appears, or never.
- Do Vast's scheduled jobs fire once at `start_time` when `end_time` is less than one cadence away? Needs a live test before it can be the third guard layer.
- Can `CONTAINER_API_KEY` read its own instance row? If so, the watchdog reads the label and the clock file goes away. Needs a live test.
- Live tests before relying on: `CONTAINER_API_KEY` bound to the box's IP and sometimes absent; `/charges` clipping to a day range and its lag; `ports` absent until running; adding a port recreates the container; the `on-demand`/`ondemand` inconsistency (absent from 1.9.1); 404 meaning unauthorized; `label` length at create; `schedule_job` cadences below one hour; container-key `DELETE` while `loading`.

### Settled

- ~~Can the watchdog destroy its own box?~~ Yes, documented and used by Vast's own base image. See §6.
- ~~Does every `reserve` open ports?~~ Yes. Vast fixes ports at creation; adding one later recreates the container. See §4.1.
- ~~Should a running `run` job hold the clock?~~ No. `run` and `status` warn instead. See §4.6.
- ~~Should `run` default to a longer TTL?~~ Yes. `run_ttl`, default 2h. See §4.6.
- ~~When does the clock start?~~ When the container starts. The box's clock file is the authority; `start_date` is not used. A box that never reaches SSH is bounded by `created + ttl`. See §3.
- ~~Is there an account-level hard cap?~~ No. See §2.1.
- ~~Per-lease budget?~~ Cut. `--max-price` and `--ttl` bound a lease. See §5.2.
- ~~Fallback destroy key when `CONTAINER_API_KEY` is absent?~~ Not in v1. `guard: partial` and the sweep. See §6.
- ~~Does `serve` expose the endpoint publicly?~~ Yes, with a generated key per job. `--bind-local` for tunnelling. See §4.7.
- ~~Built-in model table?~~ One entry; config adds more. See §4.7.
- ~~Does `release` of an `unreachable` lease wait?~~ It waits for the destroy call only. See §4.3.
- ~~Store group/owner on the provider or locally?~~ On the provider, in the instance label. See §8.0.
- ~~Python or TypeScript?~~ Python. See §10.1.
- ~~Compile to a binary?~~ No. Lazy imports instead. See §10.3.

## 13. One-line README

> `vasty reserve` gets you a GPU box with a 30-minute clock. `extend` keeps it. `run`, `serve`, `sync`, `ssh`, `tag`, `status`, `release`.
