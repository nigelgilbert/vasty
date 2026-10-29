# rig — leased GPU compute for agents

> Working name. `rig` is a placeholder for the command; it has not been checked for availability.

## 1. Summary

`rig` is a small CLI that lets an AI agent (or a human) borrow a GPU machine from Vast.ai for a bounded amount of time. Every machine is a **lease**: it has a clock, and when the clock runs out the machine is destroyed. Nothing runs forever by accident.

The whole tool fits in one sentence: **a box is a lease with a clock; jobs run on it.**

Primary consumer: coding agents such as Claude Code, invoked from a skill or script. Secondary consumer: the human running them.

## 2. Design principles

1. **Expire by default.** Every lease has a TTL. Keeping something alive requires an explicit `extend`. Forgetting is the safe outcome.
2. **Bounded spend.** Time caps hours; a budget caps dollars. Both have defaults. rig refuses to exceed either by accident; it does not pretend to be a security boundary (see §2.1).
3. **Light.** No daemon, no database server, no background process on the user's machine. State lives in Vast and in a small local file.
4. **Agent-first I/O.** JSON on stdout when not a TTY, human-readable when it is. Every error names a next action.
5. **Few verbs.** The command set should fit on one line of a README.
6. **Vast today, not Vast forever.** The provider is an implementation detail behind a thin adapter. Nothing user-facing says "Vast".

### 2.1 What rig guarantees, and what it only encourages

rig is deliberately lightweight, so its guardrails are conventions enforced by the CLI, not account-level controls. Stated plainly:

- **Budgets are client-side.** rig checks the daily cap before it spends. A direct `vastai` call, the dashboard, or a second machine with its own config can go past it. The account-level stop is a prepaid balance with autobilling off: at $0 Vast stops every instance and schedules it for deletion. Vast has no spend-cap setting.
- **Owner is self-declared.** `RIG_OWNER` is an environment variable. It stops an agent from releasing someone else's box by accident, not on purpose. Anyone with the API key can do anything.
- **The clock is enforced by rig's own machinery** (§6), not by Vast. It is reliable to the degree the watchdog and sweep are, which is why `guard` is reported on every lease.

This is the right trade for a thin tool. The spec and the README say "won't by accident," never "can't."


## 3. Concepts

| Term | Meaning |
|---|---|
| **Lease** | One rented machine plus an expiry time. Identified by a short id and an optional name. |
| **Box** | The machine behind a lease. "Lease" and "box" are used interchangeably. |
| **Job** | A process started on a box by `run` or `serve`. A box may host many jobs over its life. |
| **Clock** | The lease's expiry timestamp. Set at `reserve`, moved by `extend`. |
| **Budget** | A per-day dollar cap on the whole account. See §5.2. |
| **Profile** | A named bundle of defaults (hardware preferences, image, TTL, budget). |
| **Group** | A label shared by several leases so they can be acted on together. Has no state of its own. |
| **Owner** | Who created a lease: an agent or human id. Scopes names and bulk operations. |

Rules:

- The lease is the box, not the job. Releasing the box ends every job on it.
- The clock starts when Vast starts charging GPU rent, which is when the instance leaves `loading` and begins running. Boot time (image pull, container start) is not counted against the TTL. `expires_at` is `start_date + ttl` from the instance's own `start_date`. The first rig command that sees the instance running writes it to the label, then to the box's clock file, in the `extend` lengthening order (§6); `reserve` with wait does this before it returns, and the sweep does it otherwise. It is never recomputed from `start_date` after that; only `extend` changes it. The clock measures paid GPU time; storage accrues from creation.
- A box that never reaches `running` is destroyed once `now > created + ttl`, so the TTL also bounds boot.
- The clock is the clock. A lease expires when its clock runs out, whether or not a job is running on it. `status` warns when a job is at risk (§4.4) and `extend` is the way to keep it.
- `run` and `serve` on an unnamed box auto-reserve one and auto-release it when the job ends. On a named box they reuse it and leave it alive.
- rig never makes a decision about one lease based on another. No auto-replacement, no dependency ordering, no rebalancing. Multi-box setups are many leases that share a group; anything smarter lives in the agent above rig.

### 3.1 Lease states

| State | Meaning |
|---|---|
| `pending` | Reserved on the provider, not yet SSH-reachable. |
| `running` | Healthy and reachable. |
| `unreachable` | Provider says it exists, but the box stopped responding. Clock keeps running. |
| `expiring_soon` | Running, under the warn threshold (default 5m). Surfaced as a warning, not a separate state in JSON. |
| `expired` | Clock ran out; destroyed (or being destroyed). Kept in history briefly. |
| `released` | Destroyed by `release`. Kept in history briefly. |
| `orphan` | An instance on the account that rig did not create. No clock until `tag` gives it one. |

Each lease also carries a `guard` field: `full` (provider auto-stop + on-box watchdog + local sweep all set), or `partial` with a list of which layers are missing.

## 4. Commands

```
rig reserve   [--name NAME] [--group G] [--ttl 30m] [--profile P] [hardware flags]
rig extend    TARGET  (--by 30m | --to 2h | --until TIME)
rig release   TARGET
rig status    [TARGET]
rig run       [--on LEASE] [reserve flags] -- COMMAND...
rig serve     [--on LEASE] --model MODEL [--quant Q] [reserve flags]
rig sync      LEASE (push SRC DEST | pull SRC DEST)
rig ssh       LEASE [-- COMMAND...]
rig tag       TARGET [--name NAME] [--group G] [--owner O] [--ttl 30m]
rig config    (show | set KEY VALUE | profiles)
```

Nine verbs plus `config`. Spend is part of `status`, not its own command. Adopting an orphan is `tag`.

### 4.0 Targeting: `--group` and `--owner`

Every command that acts on leases takes a **TARGET**, which is one of:

```
LEASE                 a lease id or name (names are scoped to the current owner)
--group G             every active lease in group G
--owner O             every active lease owned by O
--all                 every active lease you own
--all --everyone      every active lease on the account, regardless of owner
```

`--group` and `--owner` can be combined (`--group exp42 --owner claude`). Bulk targets never include orphans; those must be named by instance id.

Owner comes from, in order: `--owner` on the command (sets ownership at `reserve`, filters elsewhere), `RIG_OWNER`, config `owner`, or `$USER`. An agent skill should set `RIG_OWNER` to something stable like `claude-code` so its boxes are distinguishable from the human's.

Ownership rules:

- Names are unique per owner, not per account. Two owners can each have a lease named `ft`.
- `release --all` and `extend --all` touch only your own leases unless `--everyone` is given.
- Any owner can read any lease; only bulk writes are scoped.

Group rules:

- A group exists as long as at least one active lease carries the label. There is nothing to create or delete.
- Leases in a group may have different clocks, hardware, and owners. rig shows this plainly rather than normalizing it.
- `extend --group G --by D` extends each lease by D. `extend --group G --to D` aligns them all to one expiry.
- Bulk `extend` is atomic with respect to budget: if extending the whole target would exceed the daily budget, nothing is extended and the response says how much budget remains.
- There is no batch reserve. An agent that wants three boxes calls `reserve` three times (or loops in its skill). This keeps partial-failure semantics out of rig entirely.

### 4.1 `reserve`

Rents a box and starts its clock.

Hardware flags (all optional; profile and config supply defaults):

```
--gpu NAME          e.g. 4090, A6000, L40S, A100
--vram MIN_GB       minimum VRAM per GPU
--gpus N            number of GPUs (default 1)
--disk GB           disk size (default 50)
--image IMAGE       docker image (default from profile)
--max-price $/HR    hard ceiling for this lease
--region R          optional
--ports N[,N...]    extra container ports to expose (default set is always opened, see below)
```

Ports are fixed when a Vast instance is created; adding one later means recreating the container and renumbering external ports. So every `reserve` opens a small default set: `22` (SSH), `8000` (inference, used by `serve`), and `8080` (spare, for Jupyter or a user service). `--ports` adds to that, up to Vast's limit of 64. Vast maps each to a random external port; rig reads the mapping from the instance's `ports` field and reports it in `--verbose` output, and `serve` resolves the public URL from it.

Behavior:

- Picks the best offer that satisfies the constraints. "Best" weighs reliability and bandwidth, not only price; cheapest is the tiebreaker.
- Writes the label at create with `created=now` and `ttl`. Vast's instance schema has no creation timestamp, so `created` lives in the label.
- Idempotent on name: `reserve --name X` when an active lease named `X` already exists returns that lease instead of creating a second one. Flag mismatches are a warning, not an error.
- Fails before spending if the projected spend would exceed the daily budget (§5.2).
- Waits for the box to be SSH-reachable before returning (configurable `--no-wait`).

Output (JSON mode):

```json
{
  "lease": "l-7f3a",
  "name": "finetune",
  "status": "running",
  "gpu": "RTX 4090",
  "gpus": 1,
  "vram_gb": 24,
  "price_per_hr": 0.38,
  "expires_at": "2026-10-29T01:04:00Z",
  "ttl_remaining_s": 1800,
  "ssh": "ssh -p 41022 root@198.51.100.7",
  "rsync_target": "root@198.51.100.7:",
  "ssh_port": 41022
}
```

### 4.2 `extend`

Moves the clock. Exactly one of `--by`, `--to` (duration from now), or `--until` (timestamp). Returns the new `expires_at`. Refuses if the extension would exceed the daily budget (§5.2), and says by how much.

`extend` writes the new expiry to the label and to the box's clock file (§6). A `pending` lease has no clock file yet, so `extend` on it returns `lease_pending`. Bulk `extend` checks the budget once for the whole target, then writes each lease in turn and returns a per-lease array of `{lease, ok, expires_at, error}`. Exit code is 2 if any entry failed.

### 4.3 `release`

Destroys the box now. Returns a summary:

```json
{
  "lease": "l-7f3a",
  "name": "finetune",
  "uptime_s": 5820,
  "cost": 0.61,
  "jobs": [{"id": "j-1", "cmd": "python train.py", "exit": 0, "duration_s": 5400}]
}
```

Bulk targets return an array of summaries. Releasing an unknown or already-dead lease is a no-op success. Releasing an orphan by instance id is allowed and requires `--yes` in non-TTY mode.

### 4.4 `status`

With no target: every active lease on the account, time remaining, cost so far, running jobs, orphans, and a totals line with today's spend, remaining daily budget, and current burn rate. With a target: those leases in detail; a single lease also includes a job log tail. There is no separate `cost` command; the totals are here. Spend figures come from Vast's billing where available and from price × uptime between billing updates, and the output says which.

`status` is a networked command: it lists instances from Vast every time so what it shows is true. `--cached` answers from the local file without a network call (fast, possibly stale, says so with a `cached_at` timestamp) for agents that poll tightly. `--verbose` adds per-lease detail that is normally hidden: full label, guard layer breakdown, instance id, image, ports, and the last provider error if any.

Also performs the **expiry sweep** (see §6) and **reconciliation** (see §8) as side effects, so any CLI call keeps the world honest. Because a read command can therefore destroy an expired box, it never does so silently: anything the sweep released appears in a `swept` array in the output and as a line in human mode.

Output always includes a `warnings` array, each with a `code`, the affected lease, and a `fix` string that is a runnable rig command. Warning codes: `expiring_soon`, `expiring_with_running_job`, `box_unreachable`, `orphan`, `guard_partial`, `expired_with_running_jobs`, `budget_low`, `startup_failed`. `expiring_with_running_job` replaces `expiring_soon` on a lease that has a live job; its `fix` is the same `extend` command.

Human-mode output for an ugly account (an experiment group, a served sub-agent, a dead host, an orphan, and another owner's box):

```
$ rig status
LEASE    NAME        GROUP   OWNER    GPU        STATE        EXPIRES  $/HR   COST   JOBS
l-7f3a   trainer     exp42   claude   2× A100    running      1h12m    2.40   4.86   j-1 train.py (running 2h01m)
l-8b10   eval-0      exp42   claude   L40S       running      12m      0.82   0.71   j-2 vllm (serving :8000)
l-8b11   eval-1      exp42   claude   L40S       unreachable  12m      0.82   0.68   j-3 vllm (unknown)
l-8b12   eval-2      exp42   claude   L40S       running      ⚠ 3m     0.82   0.70   —
l-9c21   subagent    —       claude   A6000      running      44m      0.55   0.12   j-1 qwen3-72b (serving :8000)
l-a003   scratch     —       nick     4090       running      19m      0.38   0.05   —
i-55120  —           —       ?        3090       orphan       none     0.22   ?      —

WARNINGS
  l-8b12  expiring_soon       extend with: rig extend l-8b12 --by 30m
  l-8b11  box_unreachable     host stopped responding 6m ago; rig release l-8b11 and re-reserve
  i-55120 orphan              not created by rig; rig tag i-55120 --ttl 30m   or  rig release i-55120
  l-7f3a  guard_partial       on-box watchdog not running; expiry enforced by provider + local sweep only

TODAY  spent $7.12 of $40.00  ·  6 leases live (5 yours)  ·  burning $6.21/hr
```

Group view collapses the noise:

```
$ rig status --group exp42
GROUP exp42 · 4 leases · 3 healthy, 1 unreachable · expiries 3m–1h12m · $6.95 so far · $4.86/hr
  l-7f3a trainer  running      1h12m   j-1 train.py running
  l-8b10 eval-0   running      12m     j-2 serving
  l-8b11 eval-1   unreachable  12m     j-3 unknown
  l-8b12 eval-2   running      ⚠ 3m    idle
```

JSON mode is the same data, deliberately flat: a `leases` array (each with `lease`, `name`, `group`, `owner`, `state`, `guard`, `gpu`, `price_per_hr`, `cost`, `expires_at`, `ttl_remaining_s`, `jobs`), a `warnings` array, and a `totals` object (`spent_today`, `daily_budget`, `burn_per_hr`, `live`, `live_mine`). No nested topology. Agents filter by `group` or `owner` themselves.

```json
{
  "leases": [
    {"lease": "l-8b12", "name": "eval-2", "group": "exp42", "owner": "claude",
     "state": "running", "guard": "full", "gpu": "L40S", "price_per_hr": 0.82,
     "cost": 0.70, "expires_at": "2026-10-29T05:23:00Z", "ttl_remaining_s": 180, "jobs": []}
  ],
  "warnings": [
    {"code": "expiring_soon", "lease": "l-8b12", "fix": "rig extend l-8b12 --by 30m"}
  ],
  "totals": {"spent_today": 7.12, "daily_budget": 40.00, "burn_per_hr": 6.21, "live": 6, "live_mine": 5}
}
```

### 4.5 `tag`

The one verb for labels. Sets or changes `name`, `group`, and `owner` on existing leases, and gives a clock to an orphan.

- On a lease: rewrites the label. `tag ft --group exp42` moves a box into a group; `tag --group old --group new` renames a group across every member.
- On an orphan (by instance id): `tag i-55120 --ttl 30m` writes a `rig:` label with the current owner, `created=now`, `ttl`, and `expires = now + ttl`, writes the same expiry to the box's clock file, installs the watchdog, and from then on it is a lease like any other. `--ttl` is required for an orphan because it has no clock yet. The orphan's own `start_date` is ignored; its clock starts at adoption. Adoption is never refused by the budget; `tag` returns a `budget_low` warning when the projection (§5.2) passes `daily_budget`. This is the only way an orphan becomes a lease.
- `tag` never touches the clock on an existing lease; that is `extend`'s job.

### 4.6 `run`

Executes a command on a box.

- No `--on`: reserve a box with the given flags, run the command, stream output, release when it exits. The default TTL for an auto-reserved `run` box is the profile's `run_ttl` (default 2h), since jobs are longer than interactive sessions. `--ttl` overrides it.
- **The clock applies to jobs.** A job still running at expiry dies with the box. rig reminds rather than holds:
  - `run` warns on stderr when the box's remaining clock is under `warn_before_expiry` at job start, and prints the `extend` command.
  - `status` reports `expiring_with_running_job` for a lease with a live job under the warn threshold (§4.4).
  - A lease whose clock ran out with a job alive stays in history as `expired_with_running_jobs` for 24h.
- `--on LEASE`: run on the existing box, leave it alive.
- `--detach`: start the job under a supervisor on the box (tmux or nohup), return a job id immediately, log to a file on the box. `status LEASE` reports the job; `rig ssh` or `sync pull` fetches logs.
- Working directory on the box is `/workspace`. `run` does not sync code; pair it with `sync push` or use `--sync DIR` as sugar for push-then-run.

Exit code mirrors the remote command's exit code.

### 4.7 `serve`

Brings up a model behind an OpenAI-compatible endpoint.

- Maps `--model` (and optional `--quant`) to hardware: required VRAM, acceptable GPU tier, image. The mapping is a small table in config, overridable per call.
- Launches an inference server (vLLM by default), waits for `/v1/models` to answer, returns the URL.
- Same auto-reserve/`--on` semantics as `run`. A served model is a job; the box is still the lease.

Output:

```json
{
  "lease": "l-9c21",
  "job": "j-1",
  "model": "Qwen/Qwen3-72B-Instruct",
  "url": "http://198.51.100.7:8000/v1",
  "api_key": "rig-local-xxxx",
  "expires_at": "2026-10-29T02:04:00Z"
}
```

The endpoint dies with the lease. A sub-agent spun up this way literally expires.

### 4.8 `sync`

`push SRC DEST` and `pull SRC DEST` wrap rsync over the lease's SSH connection. Sensible excludes by default (`.git`, `__pycache__`, `.venv`, `node_modules`); `--delete` on push makes the box mirror your tree exactly. Large datasets should be fetched by the box itself inside `run` (from S3, Hugging Face, etc.) rather than routed through your machine. Exists so skills never assemble scp strings from JSON.

### 4.9 `ssh`

Opens a shell or runs a one-off command. Escape hatch; most workflows should not need it.

### 4.10 `config`

- `show` prints effective config and where each value came from.
- `set KEY VALUE` writes to the user config file.
- `profiles` lists named profiles.

## 5. Configuration

Resolution order, highest first:

1. Command-line flags
2. `--profile NAME`
3. Environment variables (`RIG_*`, plus `VAST_API_KEY`)
4. Project file `./rig.toml` or `./.rig/config.toml`
5. User file `~/.config/rig/config.toml`
6. Built-in defaults

Example user config:

```toml
api_key_env = "VAST_API_KEY"
owner = "nick"            # overridden by RIG_OWNER or --owner

[defaults]
ttl = "30m"
run_ttl = "2h"
max_price = 0.60
daily_budget = 10.00
warn_before_expiry = "5m"
image = "rig/base:cuda12.4"
disk = 50

[profiles.small]
gpu = "4090"
vram = 24

[profiles.big]
gpu = "A100"
vram = 80
max_price = 2.50
daily_budget = 40.00

[models."Qwen/Qwen3-72B-Instruct"]
vram = 80
quant = "awq"
image = "vllm/vllm-openai:latest"
```

A config object can also be piped in: `rig reserve --config -` reads JSON from stdin, matching the AWS-CLI `--cli-input-json` habit.

### 5.1 Base image and startup hooks

rig ships a **known base image** and uses it by default. It is built from Vast's official `vast-ai/base-image` and adds only what rig itself needs: sshd, rsync, tmux, curl, python3, and the watchdog script. Everything rig does is tested against this image, which is what makes `run`, `sync`, and `serve` reliable without per-box surprises.

Users bring their own setup through startup hooks, not by replacing the image:

```toml
[defaults]
image = "rig/base:cuda12.4"          # the default; override only if you know why
startup = "setup.sh"                 # path to a bash script, or inline below

[profiles.ft]
startup = '''
pip install -U transformers peft
apt-get install -y ffmpeg
'''
```

- `startup` runs once on the box after rig's own `onstart` (the watchdog and sshd setup), as root, in `/workspace`, with the lease's env available. Its output is logged to `/workspace/.rig/startup.log` and the box is reported `pending` until it exits 0. A non-zero exit makes the lease `running` with a `startup_failed` warning; the box is not released, so you can `ssh` in and look.
- `--startup FILE` on `reserve`, `run`, and `serve` overrides the profile for one lease. `--startup -` reads the script from stdin.
- `--image` still works for people who want a different base. rig then installs its essentials via `onstart` if they are missing, at the cost of a slower boot, and marks `guard: partial` if it cannot get the watchdog running.

The split is: the image is rig's responsibility, the startup script is yours.

### 5.2 Budget

`daily_budget` caps projected spend for the account on a UTC calendar day. `reserve` and `extend` compute:

```
projected = spent_today
          + Σ live leases: dph_total × hours from now to expires_at
          + new lease: dph_total × ttl          (reserve)
          + target leases: dph_total × extension (extend)
```

- `spent_today` is Vast's billing figure when fresh, otherwise price × uptime since the last billing update.
- `dph_total` is the offer's GPU price plus disk.
- Remaining time on a live lease counts on the day the check runs, even when it crosses midnight.
- The scope is the whole account. Two owners sharing an API key share the budget.
- `daily_budget` resolves through the §5 order. `status` totals show the resolved value and its source.
- Refusal returns `budget_exceeded` with `remaining` and `projected`, exit code 3.
- `tag` on an orphan is never refused; it warns with `budget_low` instead, since the box is already billing.

## 6. Expiry enforcement (no daemon)

The clock must be enforced even when no one is running `rig`. Vast has no `max_duration`, `auto_stop`, or `expires_at` field on an instance, so expiry is rig's responsibility. Three layers, in order of importance:

1. **On the box (primary).** `reserve` injects a watchdog via `onstart`. This is a documented, supported pattern: Vast injects `CONTAINER_ID` and a per-instance `CONTAINER_API_KEY` into every container, its docs show `vastai destroy instance $CONTAINER_ID` run from inside, and Vast's own base image uses exactly this call in its provisioner. The watchdog:
   - reads `expires_at` from `/workspace/.rig/clock`, so it does not depend on the container key being able to read or write labels. `onstart` writes `now + ttl` to the file only when it is absent, so a container restart keeps an extended value. Container time is at or after `start_date`, so the watchdog never fires before the label's clock. `extend` and the first-write in §3 rewrite the file over SSH;
   - sleeps until then, re-reads the clock file (so a late `extend` is honored), and if still expired calls `DELETE /api/v0/instances/$CONTAINER_ID/` with the container key;
   - runs under cron every minute as a belt-and-braces alongside the sleeping process, so a killed watchdog is restarted.

   `CONTAINER_API_KEY` is bound to the box's own public IP (fine, that is where the watchdog runs) and is documented as occasionally absent. When `onstart` finds it missing, the lease is `guard: partial` with `watchdog` listed, and the sweep is the enforcer. A per-lease scoped key as a fallback is a v1.1 candidate.

2. **Local sweep.** Every networked `rig` command lists instances, reads each `rig:` label, and destroys anything past its clock. Catches a dead watchdog. Cheap because it piggybacks on the list call `status` already makes. Anything it destroys is reported in `swept`. Sweep rules:
   - A label with `expires=` is past its clock when `now > expires`.
   - A label without `expires=` on an instance with a `start_date` gets `expires = start_date + ttl` written to it and to the clock file, once. Only `reserve` produces such a label; `tag` always writes `expires`.
   - A label without `expires=` on an instance with no `start_date` is past its clock when `now > created + ttl`.

3. **Provider scheduled job (optional, v1.1).** Vast's scheduled-jobs API (`/commands/schedule_job/`) can call `DELETE /instances/{id}/` on a cadence between a start and end time. It is cron-shaped rather than one-shot and thinly documented, so it is a belt-and-braces layer to add once its first-fire semantics are verified, not something v1 depends on.

`extend` writes the new expiry to the instance label (which the sweep reads) and to `/workspace/.rig/clock` over SSH (which the watchdog reads). Write order keeps the earlier-firing enforcer behind what `extend` reports: when lengthening, write the clock file first and the label second; when shortening, the label first and the clock file second. If the second write fails, `extend` restores the first, fails with `provider_error`, and the lease shows `guard: partial` until the next successful write.

Interruptible (bid) instances stop when outbid, which is a crude cost cap but not a clock; rig does not rely on it.

## 7. Output and errors

- JSON on stdout when stdout is not a TTY; tables when it is. `--json` and `--plain` force either.
- Diagnostics go to stderr. stdout is always a single parseable object in JSON mode.
- Every error has a stable `code`, a human `message`, and a `hint` naming the next action:

```json
{
  "error": "no_offers",
  "message": "No offers match gpu=4090 under $0.40/hr.",
  "hint": "Try --max-price 0.60, --gpu 3090, or relax --region."
}
```

Core error codes: `no_offers`, `budget_exceeded`, `lease_not_found`, `lease_expired`, `box_unreachable`, `job_failed`, `provider_error`, `auth_missing`.

Exit codes: 0 success, 1 user/config error, 2 provider error, 3 budget refused, job exit code passed through for `run`.

## 8. State

### 8.0 The lease lives on the provider

Vast instances carry a free-text `label` (≤1024 chars), settable at create and via `PUT /instances/{id}/`, returned on every instance row. rig stores the lease itself there, so the provider is the source of truth for everything that matters:

```
rig:v1;lease=l-7f3a;name=trainer;owner=claude-code;group=exp42;created=1761699840;ttl=10800;expires=1761710640
```

Consequences:

- Any machine on the account sees the same leases, owners, and groups. There is no "second laptop sees orphans" problem.
- An **orphan** is precisely an instance whose label does not start with `rig:`.
- The sweep reads the clock from the label. The watchdog reads it from the box's clock file. `extend` writes both (§6).
- `label_counts` from `GET /api/v1/instances/` gives group sizes for free.

Label format is versioned (`rig:v1`) so it can change later without breaking older boxes.

### 8.1 Local cache

A single file, `~/.local/state/rig/leases.json`, is a **cache** of the label data plus things the provider does not hold: job records (command, start time, exit code, log path) and the last known `guard` status. It exists so that `status` on a cached lease can answer instantly without a network call, and so that job history survives a box being destroyed.

Reconciliation runs on every networked command:

- A lease in the file that Vast no longer knows about is moved to history as `expired` or `released`.
- An instance on Vast with a `rig:` label that is not in the file is adopted into the file silently (another machine made it).
- An instance with no `rig:` label is shown as `orphan`.
- Expired and released leases stay in history for 24h so an agent can find out what happened to a job, then are pruned.

### 8.2 Messy cases

rig's rule for mess is: show it honestly, give the one-line fix, never act on one lease because of another.

| Case | What rig does |
|---|---|
| Group leases on different clocks | Allowed. `status --group` shows the expiry range. `extend --to` aligns them if wanted. |
| Box dies with time left on the clock | State becomes `unreachable`. Clock keeps running. Warning suggests `release` and re-reserve. rig never auto-replaces. |
| Job still running when the clock expires | Job is killed with the box. `status` warned with `expiring_with_running_job` beforehand. Lease stays in history as `expired_with_running_jobs` for 24h so the agent learns why its job vanished. |
| Box never leaves `loading` | Swept once `now > created + ttl`. `reserve` without `--no-wait` gives up at the same point, destroys the box, and returns `box_unreachable`. |
| Local state file lost | Leases are rebuilt from instance labels on the next networked command. Only job history is lost. |
| Box made in the Vast dashboard, or by another tool | No `rig:` label, so shown as `orphan`. Untouched until `tag` (writes a label and installs the watchdog) or `release` by instance id. |
| Two owners `reserve --name ft` at the same time | Names are per owner, so two boxes. Within one owner, idempotency returns the existing lease. |
| Bulk extend would cross the daily budget | Nothing is extended. Response reports remaining budget. |
| Expiry guard could not be fully set | Lease is `guard: partial` with the missing layers listed. Warning on every `status` until fixed or released. |
| Agent crashes mid-`run` on an auto-reserved box | The job keeps running until it exits or the clock runs out. Next `status` shows it with the job state and warns as expiry nears; the agent can `release`, `extend`, reattach with `--on`, or let it finish. |
| `release --all` from an agent on a shared account | Only that owner's leases. The human's `scratch` box survives unless `--everyone` was passed. |

## 9. Workflows

### 9.1 Post-training from a coding agent

```
rig reserve --name ft --profile big --ttl 3h
rig sync ft push ./ /workspace/
rig run --on ft --detach -- python train.py --config cfg.yaml
# ... agent does other work, polls ...
rig status ft              # expiring_soon? then:
rig extend ft --by 1h
rig sync ft pull /workspace/out/ ./out/
rig release ft             # returns cost + job exit codes for the report
```

A Claude Code skill can wrap exactly this, using `release`'s summary as the report.

### 9.2 Sub-agent spin-up

```
rig serve --model Qwen/Qwen3-72B-Instruct --ttl 1h
# -> {"url": "http://.../v1", "api_key": "...", "expires_at": ...}
```

The local harness points its OpenAI-compatible client at `url`. If the harness also needs a sandbox VM, a second `rig reserve --name sandbox` provides it. Both expire on their own.

### 9.3 Reuse a warm box

```
rig run --on ft -- python eval.py
rig serve --on ft --model ./out/checkpoint
rig release ft
```

### 9.4 Multi-box experiment with a group

```
export RIG_OWNER=claude-code
rig reserve --name trainer --group exp42 --profile big --ttl 3h
for i in 0 1 2; do rig reserve --name eval-$i --group exp42 --gpu L40S --ttl 1h; done
rig status --group exp42                 # one line per box, expiry range, group cost
rig extend --group exp42 --to 2h         # align every clock
rig release --group exp42                # tear down the experiment, get per-box summaries
```

The human's own boxes, made under a different owner, are untouched by that last line.

## 10. Implementation decisions

### 10.1 Language: Python

Chosen over TypeScript after weighing both. The deciding factors:

- **The hard parts are Python-shaped.** The on-box watchdog, `onstart` scripts, `serve` launching vLLM and polling its health, and model-to-VRAM sizing all live in Python's world. Writing them from TypeScript means generating Python and shell from TS strings.
- **The official client absorbs API drift.** The `vastai` package already handles `Retry-After` on 429s, backoff on 502/503/504, the search daily quota (which must not be retried), the `on-demand`/`ondemand` inconsistency, the query mini-language, and the v0 → v1 migration. A zero-dependency TS client would own all of that forever. Being thin means letting someone else carry the plumbing.
- **Distribution is no longer a gap.** `uvx rig` is one line with no install, equivalent to `npx`.
- **Users are ML people.** Python is already on their machines and in their heads.

Accepted costs: startup is ~200ms when the SDK is imported (mitigated below), and Python's type system is weaker than TS's (mitigated with strict mypy and dataclasses for every output shape).

### 10.2 Dependencies: exactly one

```
rig → vastai → Vast
```

`vastai` is the only runtime dependency, pinned to a known version. The dependency tree is the product's shape: rig adds policy (clocks, budgets, owners, groups), not plumbing. Everything else is standard library: `argparse`, `json`, `tomllib`, `subprocess` for `rsync`/`ssh`, `dataclasses`.

The `vastai` package has itself churned recently (`vastai-sdk` was deprecated and merged into `vastai`; CLI and SDK ship together). So:

- Every SDK call goes through a single `provider.py`. No `vastai` type or call appears above that file.
- `provider.py` is the adapter boundary for a future second provider. It exposes roughly six functions: `search_offers`, `create`, `list_instances`, `destroy`, `set_label`, `charges`. (`set_label` backs `tag`, `extend`, and `reserve`.)
- Pin the version in `pyproject.toml`; bump deliberately.

### 10.3 Performance: lazy imports, no compilation

Compiling (PyInstaller, Nuitka) was considered and rejected. Startup cost is imports, not interpretation, so a binary saves 10–20% while adding a five-platform build matrix, macOS signing and notarization, 30–80MB artifacts, and antivirus false positives. Wrong lever for a thin tool.

The right lever is lazy imports:

- `rig --help`, `rig config show`, `rig status --cached`, and `rig completion` import only the standard library. Target: under 50ms.
- `reserve`, `extend`, `release`, `tag`, and any reconciliation import `vastai` inside the function that needs it. Target: under 250ms before the HTTP round-trip, which dominates anyway.
- Verify on day one with `python -X importtime` and keep a budget in CI.

Nuitka can still produce a static binary from the same source later without changing rig, if demand appears. The door is open; v1 does not walk through it.

### 10.4 Distribution

- **Headline:** `uvx rig reserve`. This is the first line of the README and the line in the Claude Code skill.
- **Permanent install:** `uv tool install rig` or `pipx install rig`.
- **Source of truth:** PyPI only. No binaries, no GitHub release assets.
- **Shell completions:** shipped in the package (`rig completion bash|zsh|fish`), including lease names and group names from the cache. Small, but it is what makes a CLI feel finished to a human.
- **Homebrew tap:** later, if humans ask. Not v1.

### 10.5 Provider facts that shaped the design

Confirmed against docs.vast.ai (OpenAPI spec at `/api-reference/openapi.yaml`) and the `vastai` 1.9.1 source:

| Fact | Effect on rig |
|---|---|
| Base URL `https://console.vast.ai/api/v0`; auth is `Authorization: Bearer <key>` | Nothing clever to hide; SDK is plain `requests` |
| Search is `POST /bundles/` with `{field:{op:value}}` JSON; the `gpu_name=RTX_4090` syntax is client-side sugar | rig builds the JSON directly from its flags; no mini-language |
| Create is `PUT /asks/{offer_id}/`; only `image` is required; returns `new_contract` as the instance id | `reserve` is one call after search |
| No server-side expiry field | Watchdog-first guard stack (§6) |
| `label` is a single ≤1024-char string, settable and returned on every row | Lease data lives in the label (§8.0) |
| `GET /charges/` is per-instance with GPU/disk/bandwidth breakdown; `GET /users/current` has `balance` | `status` totals report real numbers, estimates between billing updates |
| Rate limits are unnumbered per-endpoint intervals; 429 bodies are sometimes plain text; search has a daily quota | SDK's retry logic is used as-is; `status` polling is gentle; search quota errors are surfaced, never retried |
| Responses are loosely typed (`extra_env` as pair array, `ports` absent until running, 404 sometimes means unauthorized) | All normalized inside `provider.py` |
| `/api/v1/instances/` and `/search/asks/` are the newer style; `/bundles/` may be deprecated | Another reason the adapter is one file |
| Instances get `CONTAINER_ID` and a per-instance `CONTAINER_API_KEY`; Vast's docs and base image show self-destroy with it | The watchdog is a supported pattern; when the key is absent the lease is `guard: partial` and the sweep enforces |
| `balance_threshold` is the autobilling trigger; there is no spend-cap field | Budgets are client-side; the account-level stop is a prepaid balance with autobilling off |
| Ports are fixed at creation (`-p N:N` in `env`), no ranges, 64 max, random external numbers | `reserve` always opens 22, 8000, 8080; `serve --on` works on any rig box |

## 11. Non-goals (v1)

- Scheduling, queues, or fleet management
- Multi-provider support (adapter boundary exists, only Vast is implemented)
- A long-running daemon or web UI
- Spot/interruptible instance handling beyond surfacing it as a flag
- Secrets management beyond reading the API key from env or config

## 12. Open questions

- Should `run` without `--on` default to a longer TTL than `reserve`, or should they share one default and rely on `extend`?
- Does `serve` expose the endpoint publicly with a generated key, or tunnel it over SSH to localhost by default? Tunnel is safer; public is simpler for harnesses on other machines.
- How much of the model-to-hardware table ships built in versus lives in user config?
- MCP: ship a thin wrapper over the CLI later if demand appears, or never.
- Should `release` of an `unreachable` lease wait for provider confirmation, or mark it released locally and move on?
- Do Vast's scheduled jobs fire once at `start_time` when `end_time` is less than one cadence away? Needs a live test before it can be the third guard layer.
- Can `CONTAINER_API_KEY` read its own instance row? If so, the watchdog reads the label and the clock file goes away. Needs a live test.
- Does Vast reset `start_date` on a host-side restart? The once-only `expires` write guards against it; a live test confirms whether the guard is needed.

### Settled

- ~~Can the watchdog destroy its own box?~~ Yes, documented and used by Vast's own base image. See §6.
- ~~Does every `reserve` open ports?~~ Yes. Vast fixes ports at creation; adding one later recreates the container. See §4.1.
- ~~Should a running `run` job hold the clock?~~ No. The clock is strict; `run` and `status` warn instead. See §4.6.
- ~~When does the clock start?~~ When Vast starts charging GPU rent. A box that never runs is bounded by `created + ttl`. See §3.
- ~~Is there an account-level hard cap?~~ No. Budgets are client-side; a prepaid balance with autobilling off is the stop. See §2.1.
- ~~Per-lease budget?~~ Cut. `--max-price` and `--ttl` bound a lease. See §5.2.
- ~~Fallback destroy key when `CONTAINER_API_KEY` is absent?~~ Not in v1. `guard: partial` and the sweep. See §6.

- ~~Store group/owner on the provider or locally?~~ On the provider, in the instance label. See §8.0.
- ~~Python or TypeScript?~~ Python. See §10.1.
- ~~Compile to a binary?~~ No. Lazy imports instead. See §10.3.

## 13. One-line README

> `rig reserve` gets you a GPU box with a 30-minute clock. `extend` keeps it. `run`, `serve`, `sync`, `ssh`, `tag`, `status`, `release`. That's it.
