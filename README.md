# Vasty

Leased GPU compute for agents, on Vast.ai.

```
vasty reserve --gpu 4090 --ttl 30m
```

That rents a GPU box with a 30-minute clock. When the clock runs out, a watchdog on the box is meant to destroy it, and a sweep on the next `vasty` command catches anything the watchdog missed. `extend` keeps a box. `run`, `serve`, `sync`, `ssh`, `tag`, `status` and `release` do the rest.

**Status: work in progress.** Every verb is implemented and unit-tested against fakes, and one funded live run has confirmed unattended expiry. `serve` is broken and the default image is unpublished. See [Status](#status) before spending money.

## What it is

A coding agent such as Claude Code reserves a box, pushes code, runs a job or serves a model, pulls results, and releases. If the agent crashes, loses its connection or forgets, the clock still runs out. A human can drive it the same way.

Every box is a **lease**: a machine plus an expiry time. Vasty adds clocks, a daily budget, owners and groups on top of Vast's API.

- **Expire by default.** `reserve` gives a box 30 minutes. Auto-reserved `run` and `serve` boxes get 2 hours. Keeping a box alive takes an explicit `extend`.
- **Bounded spend.** `max_price` caps dollars per hour per box. `daily_budget` caps projected spend across the account.
- **Light.** One Python package, one runtime dependency, no daemon, no database. The lease lives in the instance label on Vast, plus one local cache file.
- **Agent-first I/O.** JSON on stdout when stdout is a pipe, tables when it is a terminal. `ssh` passes remote output through, and `completion` prints a shell script unless `--json` is passed. Every error carries a stable code, a message and a recovery hint.

## Quick start

Prerequisites: Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), `ssh` and `rsync` on PATH, an SSH key pair at `~/.ssh/id_ed25519` or `~/.ssh/id_rsa`, and a funded Vast.ai account. `reserve` registers the public key with Vast on first use.

```sh
git clone https://github.com/nigelgilbert/vasty.git && cd vasty
uv tool install .                                    # or: uv sync && export PATH=$PWD/.venv/bin:$PATH
export VAST_API_KEY=...                              # from console.vast.ai
export VASTY_OWNER=claude-code                         # names the boxes you make; see below
vasty config set defaults.image vastai/base-image:cuda-12.6.3-auto
vasty config show
```

Vasty's own image is unpublished, so the image line points at a Vast base image. Vasty installs what it needs at boot, which slows the first start. A custom image needs Linux, bash, root and apt-get.

Run one command on a fresh box:

```sh
vasty run --gpu 4090 -- nvidia-smi
```

Without `--on`, `run` reserves a box, streams the command's output, and releases the box when the command exits. Passing `--name` or `--detach`, or losing the connection mid-run, leaves the box up until `release` or its clock.

Keep a box around:

```sh
vasty reserve --name scratch --ttl 1h
vasty ssh scratch
vasty status                        # time left, cost so far, warnings with fixes
vasty extend scratch --by 30m
vasty release scratch               # uptime, cost and job exit codes
```

Once the package is on PyPI the first line becomes `uvx vasty reserve`.

## Commands

```
vasty reserve   [--name NAME] [--group G] [--owner O] [--ttl 30m] [--profile P] [--startup FILE|-] [--no-wait] [hardware flags]
vasty extend    TARGET  (--by 30m | --to 2h | --until TIME)
vasty release   TARGET [--yes]
vasty status    [TARGET] [--cached]
vasty run       [--on LEASE | reserve flags] [--detach] [--sync DIR] -- COMMAND...
vasty serve     [--on LEASE | reserve flags] --model MODEL [--quant Q] [--bind-local]
vasty sync      LEASE (push [--delete] SRC DEST | pull SRC DEST)
vasty ssh       LEASE [-- COMMAND...]
vasty tag       TARGET [--set-name NAME] [--set-group G] [--set-owner O] [--ttl 30m]
vasty config    (show | set KEY VALUE | profiles)
vasty completion (bash | zsh | fish)
```

Hardware flags on `reserve`, `run` and `serve`: `--gpu NAME`, `--vram MIN_GB`, `--gpus N`, `--disk GB`, `--image IMAGE`, `--max-price $/HR`, `--region R`, `--ports N[,N...]`. A profile or config file supplies defaults for any of them. `run --on` and `serve --on` reuse a box and reject creation flags. Auto-reserved `run` and `serve` reject `--no-wait`.

Every verb takes `--json`, `--plain` and `--verbose`.

A `TARGET` is a lease id or name, or a selector: `--group G`, `--owner O`, `--all`, or `--all --everyone` for every lease on the account. Bulk writes act on the current owner's leases. `--owner O` selects another owner's; `--everyone` selects all.

## For agents

Owner comes from `--owner`, then `VASTY_OWNER`, then config, then `$USER`. An agent running under the human's login shares their owner unless it sets `VASTY_OWNER`. With its own owner, `release --all` from the agent leaves the human's boxes alone.

In JSON mode stdout is one object per command. Remote output from `run` and `sync` goes to stderr. `ssh` passes remote output through and prints no object. Selected fields from `reserve`:

```sh
vasty reserve --name ft --gpu A100 --ttl 3h --json
```

```json
{
  "lease": "l-7f3a2b1c",
  "name": "ft",
  "state": "running",
  "guard": "full",
  "gpu": "A100",
  "price_per_hr": 1.80,
  "expires_at": "2026-10-29T20:04:00Z",
  "ttl_remaining_s": 10800,
  "ssh": "ssh -p 41022 root@198.51.100.7",
  "ports": {"22": 41022, "8000": 41080, "8080": 41081},
  "warnings": [],
  "swept": []
}
```

Errors are one object:

```json
{
  "error": "no_offers",
  "message": "No offers match gpu=4090 under $0.40/hr.",
  "hint": "Try --max-price 0.60, --gpu 3090, or relax --region."
}
```

Exit codes: 0 success, 1 bad input or lookup, 2 provider or box failure, 3 budget exceeded. Once a job has started, attached `run` exits with the remote command's code, 2 when the clock or a dropped connection kills the job, and 130 on SIGINT. `run --detach` exits 0 as soon as the job starts. `ssh -- COMMAND` passes through ssh's own exit status.

`status` returns a `warnings` array. Each entry has a code, the lease, a message and `fix`, one runnable `vasty` command. An agent can loop over the warnings and run the fixes. `guard` on each lease is `full` or `partial`, with the missing layer named, so an agent knows how much to trust that box's clock.

Warning codes: `expiring_soon`, `expiring_with_running_job`, `box_unreachable`, `orphan`, `guard_partial`, `expired_with_running_jobs`, `budget_low`, `startup_failed`, `flag_mismatch`, `clock_unverified`, `label_unreadable`, `spend_unavailable`, `cache_rebuilt`.

### Result shapes

Every JSON result carries `warnings` and `swept`. `swept` lists what the expiry sweep destroyed during the command, each entry `{lease, name, expired_at, ok, error}`.

| Command | Returns |
|---|---|
| `reserve`, `tag` on one lease | the lease: `lease`, `name`, `owner`, `group`, `state`, `guard`, `guard_missing`, `reused`, `gpu`, `gpus`, `vram_gb`, `price_per_hr`, `expires_at`, `ttl_remaining_s`, `ssh`, `rsync_target`, `ssh_port`, `ports` |
| `extend` on one lease | `lease`, `expires_at`, `ttl_remaining_s` |
| `release` on one lease | `lease`, `uptime_s`, `cost`, `jobs`, `destroy_pending` |
| bulk `extend`, `release`, `tag` | `results`, each with `lease`, `ok` and a nullable `error` |
| `status` | `leases`, `totals`, `cached_at`; a single-lease target adds `log_tail` |
| attached `run` | `lease`, `job`, `exit`, `duration_s`, `released` |
| `run --detach` | `lease`, `job`, `log_path`, `expires_at` |
| `serve` | `lease`, `job`, `url`, `api_key`, `expires_at` |
| `sync` | `lease`, `direction`, `src`, `dest` |
| `config` | `values`, `{key, value}` or `profiles` |

A `--no-wait` reserve returns `state: "pending"` with the clock and endpoint fields null. `reserve --name X` on an existing active lease returns it with `reused: true`. Orphans appear in `status` with an `i-` id, `state: "orphan"`, and null `owner`, `expires_at`, `ttl_remaining_s` and `guard`. `cost_source` and `spend_source` are `billing`, `estimated` or `mixed`.

### Error codes

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

A bulk command exits with the highest exit code among its failed entries. Parser errors use the same error object.

### Post-training from a coding agent

```sh
vasty reserve --name ft --gpu A100 --vram 80 --max-price 2.50 --ttl 3h
vasty sync ft push ./ /workspace/
vasty run --on ft --detach -- python train.py --config cfg.yaml
# ... do other work, poll ...
vasty status ft                  # expiring_with_running_job? then:
vasty extend ft --by 1h
vasty sync ft pull /workspace/out/ ./out/
vasty release ft                 # cost and job exit codes for the report
```

### A model endpoint for sub-agents

```sh
vasty serve --model Qwen/Qwen3-72B-Instruct --ttl 1h
```

Selected fields:

```json
{
  "lease": "l-9c21d4e0",
  "job": "j-1",
  "url": "http://198.51.100.7:41080/v1",
  "api_key": "vasty-...",
  "expires_at": "2026-10-29T18:04:00Z"
}
```

Point an OpenAI-compatible client at `url` with `api_key`. The endpoint is public on a random port, protected by a fresh key per job. The key prints once. `--bind-local` keeps vLLM on `127.0.0.1` for use through `vasty ssh -L`. The endpoint dies with the lease.

Several boxes that belong together share a `--group`. `status --group exp42` shows them on one screen, `extend --group exp42 --to 2h` aligns their clocks, and `release --group exp42` tears them down.

## How the clock holds

Vast has no expiry field on an instance, so Vasty enforces the clock itself with two layers.

1. **On the box.** `reserve` injects a watchdog through Vast's `onstart` hook. It reads the expiry from `/workspace/.vasty/clock`, sleeps until then, re-reads the file so a late `extend` is honored, and destroys the instance with the per-instance key Vast injects into the container. Cron restarts it if it dies. When the key is absent, the lease reports `guard: partial` and the sweep is the enforcer.
2. **Local sweep.** Every networked `vasty` command lists the account's instances, reads each lease label, and destroys anything past its clock. Whatever it destroys shows up in `swept`.

The clock starts when the container starts, which is when Vast starts charging GPU rent. Storage and bandwidth bill from creation. A box that never reaches SSH is destroyed by the waiting `reserve` or by the next sweep once `created + ttl` passes.

## Budget

`daily_budget` caps projected spend for the whole account on a UTC day. Before `reserve`, `extend`, `run` or `serve` spends, Vasty adds up today's charges, the remaining commitment of every live lease, and the new action. Today's charges are what Vast has billed plus an estimate since the last billing update. Past the cap it refuses with `budget_exceeded` and says how much room is left. At 90% it warns with `budget_low`. Adopting an orphan with `tag` only warns, since the box is already billing.

The check is client-side. The Vast dashboard, a direct `vastai` call, or a second machine with its own config can go past it. Vast has no spend-cap setting. The account-level stop is a prepaid balance with no saved card.

## State

The lease lives on the provider, in the instance's label:

```
vasty:v1;lease=l-7f3a2b1c;name=ft;owner=claude-code;created=1793235840;ttl=10800;expires=1793247000
```

Any machine with the API key sees the same leases, owners and groups. An instance without a `vasty:` label is an **orphan**: shown in `status`, left alone until `tag ID --ttl 30m` adopts it or `release ID` destroys it. One local file, `~/.local/state/vasty/leases.json`, caches label data plus job records. Losing it loses job history for destroyed boxes and nothing else.

### Lease states

| State | Meaning |
|---|---|
| `pending` | Reserved and not ready: booting, SSH not answering, or the startup script still running. |
| `running` | Healthy and reachable. |
| `unreachable` | The provider lists it, but the box stopped responding. The clock keeps running. |
| `stopped` | The provider stopped the instance, for example at $0 balance. The sweep still destroys it past its clock. |
| `expired` | The clock ran out. Destroyed or being destroyed. Kept in history for 24h. |
| `released` | Destroyed by `release`. Kept in history for 24h. |
| `gone` | Vanished with time left on its clock. Kept in history for 24h. |
| `orphan` | An instance vasty did not create. No clock until `tag` gives it one. |

`status` with no target lists active leases and orphans. History states show when named directly. `guard` is `full` when the watchdog is running, its destroy key is present and the clock file matches the label. Otherwise it is `partial` and `guard_missing` names `watchdog`, `destroy_key` or `clock_file`.

## Configuration

Resolution order, highest first: flags, the `[models]` entry for `serve`, `--config -` JSON on stdin, `--profile NAME`, `VASTY_*` environment variables, `./vasty.toml`, `~/.config/vasty/config.toml`, built-in defaults. `vasty config show` prints every effective value and its source.

```toml
owner = "nigel"                 # overridden by VASTY_OWNER or --owner

[defaults]
ttl = "30m"
run_ttl = "2h"
max_price = 0.60
daily_budget = 10.00
image = "vastai/base-image:cuda-12.6.3-auto"

[profiles.big]
gpu = "A100"
vram = 80
max_price = 2.50
startup = '''
pip install -U transformers peft
'''

[models."Qwen/Qwen3-72B-Instruct"]
vram = 80
quant = "awq"
image = "vllm/vllm-openai:v0.6.3"
```

A `[models]` entry sets `vram`, `gpu` and `image` for `serve --model NAME` ahead of every layer below flags, so `serve` ignores `defaults.image` unless `--image` is passed.

`startup` runs once on each box as root in `/workspace` after Vasty's own setup. The box reports `pending` until it exits 0. A failing hook leaves the box up with a `startup_failed` warning so you can `ssh` in and look.

## Status

Done:

- Every verb above, in `src/vasty/`.
- 1131 unit tests pass against a fake provider and a fake box. `mypy --strict` is clean.
- One funded live run on Vast, 2026-10-29. Every phase passed except `serve`. See [docs/live-test-report.md](docs/live-test-report.md).

Not done:

- `serve` fails on the vLLM 0.6.3 install. See [issues/serve-runs-the-image-vllm.md](issues/serve-runs-the-image-vllm.md).
- The default image `vasty/base:cuda12.4` is unpublished. See the quick start for the workaround.
- Not on PyPI. Install from the repo.

## Development

```sh
uv sync
uv run pytest
uv run mypy
```

`src/vasty/provider.py` is the only file that imports `vastai`. `tests/fakes.py` holds the fake provider and fake box the suite runs on.

## Non-goals

Scheduling, queues, fleet management, multiple providers, a daemon, a web UI, spot instances, secrets management beyond reading the API key from an environment variable.
