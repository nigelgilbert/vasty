# Vasty

Provisioning on Vast.ai comes with a TTL and cleans up after itself.

The API doesn't suck.

```
vasty reserve --gpu 4090 --ttl 30m
```

That rents a GPU box with a 30-minute clock. When the clock runs out, a watchdog on the box is meant to destroy it, and a sweep on the next `vasty` command catches anything the watchdog missed. `extend` keeps a box. `run`, `serve`, `sync`, `ssh`, `tag`, `status` and `release` do the rest.

**Status: work in progress.** Every verb is implemented and unit-tested against fakes, and one funded live run has confirmed unattended expiry. See [Status](#status) before spending money.

## What it is

A coding agent such as Claude Code reserves a box, pushes code, runs a job or serves a model, pulls results, and releases. If the agent crashes, loses its connection or forgets, the clock still runs out. A human can drive it the same way.

Every box is a **lease**: a machine plus an expiry time. Vasty adds clocks, owners and groups on top of Vast's API. `max_price` is an offer filter beside `--vram`, in dollars per hour.

- **Expire by default.** `reserve` gives a box 30 minutes. Auto-reserved `run` and `serve` boxes get 2 hours. Keeping a box alive takes an explicit `extend`.
- **Light.** One Python package, one runtime dependency, no daemon, no database. The lease lives in the instance label on Vast, plus one local cache file.
- **Agent-first I/O.** JSON on stdout when stdout is a pipe, tables when it is a terminal. `ssh` passes remote output through, and `completion` prints a shell script unless `--json` is passed. Every error carries a stable code, a message and a recovery hint.

## Quick start

Prerequisites: Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), `ssh` and `rsync` on PATH, an SSH key pair at `~/.ssh/id_ed25519` or `~/.ssh/id_rsa`, and a funded Vast.ai account. `reserve` registers the public key with Vast on first use.

```sh
git clone https://github.com/nigelgilbert/vasty.git && cd vasty
uv tool install .                                    # or: uv sync && export PATH=$PWD/.venv/bin:$PATH
export VAST_API_KEY=...                              # from console.vast.ai
export VASTY_OWNER=claude-code                         # names the boxes you make; see below
vasty config show
```

The default image is `vastai/base-image:cuda-12.6.3-auto`. Vasty installs what it needs at boot, which slows the first start. Any image works given Linux, bash, root and apt-get.

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
vasty serve     [--on LEASE | reserve flags] --model MODEL [--bind-local] [-- VLLM_ARGS...]
vasty stop      LEASE [JOB]
vasty sync      LEASE (push [--delete] SRC DEST | pull SRC DEST)
vasty ssh       LEASE [-- COMMAND...]
vasty tag       TARGET [--set-name NAME] [--set-group G] [--set-owner O] [--ttl 30m]
vasty sweep     [--follow LEASE]
vasty config    (show | set KEY VALUE | profiles)
vasty completion (bash | zsh | fish)
```

Hardware flags on `reserve`, `run` and `serve`: `--gpu NAME`, `--vram MIN_GB`, `--cuda FLOOR`, `--gpus N`, `--disk GB`, `--image IMAGE`, `--max-price $/HR`, `--region R`, `--ports N[,N...]`. A profile or config file supplies defaults for any of them. `--cuda` is the minimum CUDA version the host driver supports. With no `cuda` set, Vasty applies the floor of an image it names: 13 for `vllm/vllm-openai:v0.32.0`, 12.6 for `vastai/base-image:cuda-12.6.3-auto`. For any other image, read its floor from `NVIDIA_REQUIRE_CUDA` in `docker inspect IMAGE`. `run --on` and `serve --on` reuse a box and reject creation flags. Auto-reserved `run` and `serve` reject `--no-wait`.

A new box comes from the matching offer with the highest reliability, then the highest download bandwidth, then the lowest price, then the lowest offer id.

`run --sync DIR` pushes the contents of DIR into `/workspace/` before the command starts. Every `run` job starts in `/workspace`.

Every verb takes `--json`, `--plain` and `--verbose`.

A `TARGET` is a lease id or name, or a selector: `--group G`, `--owner O`, `--all`, or `--all --everyone` for every lease on the account. Bulk writes act on the current owner's leases. `--owner O` selects another owner's; `--everyone` selects all.

## For agents

Run `vasty status` before reserving. Reuse a lease with `--on` when it is yours, `state` is `running`, `busy` is false, `gpu`, `vram_gb` and `gpus` cover the job, and `ttl_remaining_s` covers the job or `extend` can. `run --on` leaves the lease up after the job. Auto-reserved attached `run` releases it.

Owner comes from `--owner`, then `VASTY_OWNER`, then config, then `$USER`. An agent running under the human's login shares their owner unless it sets `VASTY_OWNER`. Each swarm worker sets its own `VASTY_OWNER`. With its own owner, `release --all` from an agent leaves other owners' boxes alone. `status --verbose` lists the current owner's history, or `--owner O`'s, and `--everyone` widens it to the account. `status --everyone` alone reads as `--all --everyone`; `release` and `extend` need `--all` or `--group` with it. A name resolves under the current owner. When other owners hold it, `lease_not_found` lists their lease ids in `details.matches`.

In JSON mode stdout is one object per command. Remote output from `run` and `sync` goes to stderr. `ssh` passes remote output through and prints no object. Selected fields from `reserve`:

```sh
vasty reserve --name ft --gpu A100 --ttl 3h --json
```

```json
{
  "lease": "l-7f3a2b1c",
  "name": "ft",
  "state": "running",
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

Exit codes: 0 success, 1 bad input or lookup, 2 provider or box failure. Once a job has started, attached `run` exits with the remote command's code, 2 when the clock or a dropped connection kills the job, and 130 on SIGINT. `run --detach` exits 0 as soon as the job starts. `ssh -- COMMAND` passes through ssh's own exit status.

`status` returns a `warnings` array. Each entry has a code, the lease, a message and `fix`, one runnable `vasty` command. An agent can loop over the warnings and run the fixes. A `guard_partial` warning names the missing layer, so an agent knows how much to trust that box's clock. `status --verbose` lists each layer under `guard_layers`.

Warning codes: `expiring_soon`, `expiring_with_running_job`, `box_unreachable`, `orphan`, `guard_partial`, `expired_with_running_jobs`, `startup_failed`, `flag_mismatch`, `idle_box_available`, `clock_skew`, `clock_skew_unknown`, `sweep_not_spawned`, `clock_unverified`, `label_unreadable`, `spend_unavailable`, `cache_rebuilt`.

| Warning | Fix |
|---|---|
| `expiring_soon`, `expiring_with_running_job` | `vasty extend LEASE --by TTL`, with the lease's reserve ttl; the message rounds time left up to the minute |
| `box_unreachable` | `vasty status LEASE` |

When `reserve`, or `run` or `serve` without `--on`, creates a box, it warns `idle_box_available` for up to three idle leases that would have fit.

### Result shapes

Every JSON result carries `warnings` and `swept`. `swept` lists what the expiry sweep destroyed during the command, each entry `{lease, name, owner, expired_at, ok, error}`.

| Command | Returns |
|---|---|
| `reserve` | the lease: `lease`, `name`, `owner`, `group`, `state`, `reused`, `gpu`, `gpus`, `vram_gb`, `price_per_hr`, `expires_at`, `ttl_remaining_s`, `ssh`, `rsync_target`, `ssh_port`, `ports` |
| `extend` on one lease | `lease`, `previous_expires_at`, `expires_at`, `ttl_remaining_s`. The label's `ttl` keeps the reserve's value |
| `release` on one lease | `lease`, `uptime_s`, `cost`, `jobs`, `destroy_pending` |
| bulk `extend`, `release` | `results`, each with `lease`, `ok` and a nullable `error`; `extend` adds `previous_expires_at` and `expires_at`; `release` adds `name`, `uptime_s`, `cost`, `jobs` and `destroy_pending`, or `name` and `message` when it fails |
| `tag` | `results`, each with `lease`, `name`, `group`, `owner`, `expires_at`, `ttl_remaining_s` |
| `status` | `leases`, `totals`, `cached_at`. Each lease has `lease`, `name`, `group`, `owner`, `state`, `gpu`, `gpus`, `vram_gb`, `price_per_hr`, `cost`, `uptime_s`, `expires_at`, `ttl_remaining_s`, `busy` and `jobs`. `expires_at` is null while `pending`. `ttl_remaining_s` is null while `pending` and in `released`, `expired` and `gone`. A single-lease target adds `log_tail` in every state, `[]` when empty |
| job entry in `status` and `release` `jobs` | `job`, `cmd`, `state`, `exit`, `duration_s`. `state` is `running`, `serving`, `exited`, `killed` or `unknown`. `release` marks live jobs `killed` with a null `exit` and freezes `duration_s`. `stop` marks its job `killed` with the job's exit code |
| attached `run` | `lease`, `job`, `exit`, `duration_s`, `released`, `error`. `error` is null unless the attach was lost, then `box_unreachable` or `lease_expired` with a null `exit` |
| `run --detach` | `lease`, `job`, `log_path`, `expires_at` |
| `serve` | `lease`, `job`, `model`, `url`, `api_key`, `expires_at` |
| `stop` | `lease`, `job`, `cmd`, `state`, `exit`, `duration_s`. `stop` sends TERM to the job's process group and waits up to 10s. JOB is required when several jobs run. A job still live after the wait keeps its `state` and `stop` exits 2 |
| `sync` | `lease`, `direction`, `src`, `dest` |
| `sweep` | `swept`, `warnings` |
| `config` | `values`, `{key, value}` or `profiles` |

A `--no-wait` reserve returns `state: "pending"` with the clock and endpoint fields null. `reserve --name X` on an existing active lease returns it with `reused: true`. Orphans appear in `status` with an `i-` id, `state: "orphan"`, and null `owner`, `expires_at` and `ttl_remaining_s`.

`busy` is true when a job vasty started is running, serving or unknown, false on a running lease with none, and null in any other state. Jobs started by hand over `ssh` do not count. `uptime_s` counts from vasty's first `running` sample and is null before it. `--verbose` shows that sample as `running_at`.

### Error codes

| Code | Exit | Raised when |
|---|---|---|
| `invalid_arguments` | 1 | a flag combination, name, duration, TIME or port list is invalid |
| `invalid_config` | 1 | a config key or value is invalid |
| `auth_missing` | 1 | no API key in the `api_key_env` variable or `~/.config/vastai/vast_api_key` |
| `dependency_missing` | 1 | `ssh` or `rsync` is not on PATH |
| `no_offers` | 1 | no offer matches |
| `lease_not_found` | 1 | unknown id or name |
| `ambiguous_target` | 1 | a name or id matches more than one active lease |
| `orphan_unmanaged` | 1 | an orphan id is passed to `extend`, `run`, `serve`, `sync` or `ssh` |
| `lease_expired` | 1 | the lease is in history |
| `lease_pending` | 1 | `extend`, `run --on`, `serve --on`, `sync` or `ssh` on a lease SSH cannot reach yet |
| `name_conflict` | 1 | a new name matches another active lease of the same owner |
| `confirmation_required` | 1 | orphan `release` without `--yes` in non-TTY mode |
| `image_unsupported` | 1 | the image lacks bash, root or apt-get |
| `startup_too_large` | 1 | the encoded `onstart` exceeds 4048 characters |
| `vllm_missing` | 1 | `serve` finds no `vllm` on the box's PATH |
| `provider_error` | 2 | a provider call fails |
| `box_unreachable` | 2 | the box does not answer SSH |
| `sync_failed` | 2 | rsync fails |
| `serve_failed` | 2 | the inference server exits or times out before `/v1/models` answers; `details` carries `exit` and `lease`, plus `log_tail` when the read succeeds. When `log_tail` holds `Error 804`, the host driver is below the image's CUDA, and the hint reads `vasty serve --model M --image IMAGE --cuda 13` with the caller's `--ttl` and `--name` |
| `port_mapping_missing` | 2 | a required port has no external mapping at the readiness deadline |

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
vasty serve --profile vllm --model Qwen/Qwen3-14B-AWQ --ttl 1h
vasty serve --profile vllm --model Qwen/Qwen3-14B-AWQ --ttl 1h -- --max-model-len 16384
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

On a 24 GB RTX 3090 the first command served Qwen3-14B-AWQ at its full 40,960-token context with 9.95 GiB of KV cache. The box booted in 5 minutes, the 9.6 GB of weights downloaded and loaded in 104 seconds, and `serve` returned the endpoint 9 minutes 21 seconds after it started. A 12,039-token prompt answered in 9 seconds cold. The second command caps the context at 16,384 tokens and lets four such requests run at once.

The box's image supplies vLLM, and `serve` launches `vllm` from PATH. The `vllm` profile in the [sample config](#configuration) reserves on `vllm/vllm-openai:v0.32.0`. Pass `--gpu` with it on a mixed pool: the profile alone once picked a Tesla V100, and vLLM 0.32 ships no Volta kernels. A box reserved with a `startup` hook that installs `vllm`, or one set up through `run --on`, can serve with `serve --on`.

Tokens after `--` go to `vllm serve` after the model name. `serve` sets `--host` and `--port` itself, passes the key in `VLLM_API_KEY`, and rejects `--host`, `--port` and `--api-key` there.

Point an OpenAI-compatible client at `url` with `api_key`. The endpoint is public on a random port, protected by a fresh key per job. The key prints once. `--bind-local` keeps vLLM on `127.0.0.1` for use through `vasty ssh -L`. The endpoint dies with the lease.

Several boxes that belong together share a `--group`. `status --group exp42` shows them on one screen, `extend --group exp42 --to 2h` aligns their clocks, and `release --group exp42` tears them down.

## How the clock holds

Vast has no expiry field on an instance, so Vasty enforces the clock itself with two layers.

1. **On the box.** `reserve` injects a watchdog through Vast's `onstart` hook. It reads the expiry from `/workspace/.vasty/clock`, sleeps until then, re-reads the file so a late `extend` is honored, and destroys the instance with the per-instance key Vast injects into the container. Cron restarts it if it dies. At start and hourly it reads its own instance row with that key; a 401 or 403 marks the key missing until a later read passes. A box without `curl` marks the watchdog layer. Either way the lease carries a `guard_partial` warning and the sweep is the enforcer.
2. **Local sweep.** Every networked `vasty` command lists the account's instances, reads each lease label, and destroys anything past its clock. Whatever it destroys shows up in `swept`. `reserve`, `extend` and `tag` on adopt also start a detached `vasty sweep --follow LEASE` on the laptop when the lease has no live follower; `leases.json` records its pid. It sleeps to the lease's expiry, runs the sweep, and repeats until the row is gone, so a failed destroy and a moved expiry are each picked up on the next pass. It re-reads the expiry every five minutes, so a shortening `extend --to` holds within five minutes. `release` stops the lease's follower. A sweep that fails is retried five times a minute apart, then the follower exits with the error. A spawn that fails warns `sweep_not_spawned` and the command succeeds.

`vasty sweep` alone runs one sweep with no probe, for a scheduler. A GitHub Actions cron every five minutes:

```yaml
on:
  schedule:
    - cron: "*/5 * * * *"
jobs:
  sweep:
    runs-on: ubuntu-latest
    steps:
      - run: pipx install git+https://github.com/nigelgilbert/vasty
      - run: vasty sweep
        env:
          VAST_API_KEY: ${{ secrets.VAST_API_KEY }}
```

GitHub runs schedules best effort, so a sweep can land minutes late or skip a slot. The watchdog and the follower remain the first two enforcers.

The clock starts when Vast reports the instance `running`, which is when Vast starts charging GPU rent. The startup hook runs on that clock, so a waiting `reserve` returns with the hook's run time already spent. Storage and bandwidth bill from creation. A box that never reaches SSH is destroyed by the waiting `reserve` or by the next sweep once `created + ttl` passes.

The label holds the expiry in provider time and the clock file holds it in the box's own time. Every write to the clock file carries the provider clock at send, and the box adds its own offset before writing. The probe measures the offset on each visit, copies a fresh box's clock file into the label with the offset removed, and warns `clock_skew` when the box clock sits more than two minutes from the provider. `status --verbose` shows the measured offset as `clock_skew_s`. While `clock_unverified` is set, values cross unchanged.

## Spend

Per-box spend is `max_price` times `ttl`, since the clock ends the box. Storage and bandwidth bill outside that product. The account bound is the prepaid `credit`. With no saved card, Vast stops instances at $0.

`status` reports Vast's own figures in `totals`:

- `credit` is the prepaid money left on the account, which Vast draws charges from.
- `balance` is the `balance` field of Vast's `GET /users/current`, passed through unchanged.
- `charges_today` is what Vast has billed since 00:00 UTC.
- `burn_per_hr` sums `price_per_hr` over live leases and orphans.

For runway, read `credit` over `burn_per_hr`. When the balance or charges are unavailable, those totals are null and `status` warns with `spend_unavailable`.

A lease's `cost` sums the Vast charge rows available for its instance. A box adopted with `tag`, or an orphan, can show partial history. `release` reports the same figure. `cost` is null when no charge row is available, and `status` warns `spend_unavailable` when the read failed. `price_per_hr` times `uptime_s` approximates it.

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
| `stopped` | The provider stopped the instance, for example at $0 credit. The sweep still destroys it past its clock. |
| `expired` | The clock ran out. Destroyed or being destroyed. Kept in history for 24h. |
| `released` | Destroyed by `release`. Kept in history for 24h. |
| `gone` | Vanished with time left on its clock. Kept in history for 24h. |
| `orphan` | An instance vasty did not create. No clock until `tag` gives it one. |

`status` with no target lists every owner's active leases, then orphans. `totals.live` counts the active leases and `totals.live_mine` the caller's. `--verbose` adds the current owner's history, or `--owner O`'s, or every owner's with `--everyone`. A named lease shows in any state. A lease with the watchdog running, its destroy key present and the clock file matching the label has no `guard_partial` warning. Otherwise the warning names `watchdog`, `destroy_key` or `clock_file`.

## Configuration

Resolution order, highest first: flags, `--config -` JSON on stdin, `--profile NAME`, `VASTY_*` environment variables, `./vasty.toml`, `~/.config/vasty/config.toml`, built-in defaults. `vasty config show` prints every effective value and its source.

```toml
owner = "nigel"                 # overridden by VASTY_OWNER or --owner

[defaults]
ttl = "30m"
run_ttl = "2h"
max_price = 0.60

[profiles.train]
gpu = "A100"
vram = 80
max_price = 2.50
startup = '''
pip install -U transformers peft
'''

[profiles.vllm]
image = "vllm/vllm-openai:v0.32.0"
vram = 24
```

`startup` runs once on each box as root in `/workspace` after Vasty's own setup. The box reports `pending` while the hook runs. A hook that exits nonzero leaves the box `running` with a `startup_failed` warning so you can `ssh` in and look.

The API key comes from the environment variable named by `api_key_env`, `VAST_API_KEY` by default. When that is unset, vasty reads `~/.config/vastai/vast_api_key`, the file the `vastai` CLI writes. `config show` names the source in `api_key_source` and never prints the key.

## Status

Done:

- Every verb above, in `src/vasty/`.
- 1246 unit tests pass against a fake provider and a fake box. `mypy --strict` is clean.
- Two funded live runs on Vast, 2026-10-29 and 2026-10-31. The second covered `serve` end to end. See [docs/live-test-report.md](docs/live-test-report.md).

Not done:

- Not on PyPI. Install from the repo.

## Development

```sh
uv sync
uv run pytest
uv run mypy
```

`src/vasty/provider.py` is the only file that imports `vastai`. `tests/fakes.py` holds the fake provider and fake box the suite runs on.

## Non-goals

Scheduling, queues, fleet management, account-level spend limits, multiple providers, a daemon, a web UI, spot instances, secrets management beyond reading the API key from an environment variable.
