# Swarm report 0: rig from spec.md

Base commit: `62901614febe2c42cc1a386b69b342b85a3e5d95`. Branch: `spec-validation`.

## Commands

```
uv sync
uv run pytest -q
uv run mypy --strict
```

Result on the final commit: 898 passed, 1 skipped. mypy strict reports no issues in 33 source files. The skipped test checks fish completion syntax and needs `fish` on PATH.

`uv` was absent on the host. The run used a copy installed into a scratchpad venv.

## Layout

- `src/rig/` holds the package. `provider.py` is the only file that imports `vastai`.
- `tests/fakes.py` holds `FakeProvider`, `FakeBox` and `Harness`. No test makes a network call. Provider tests stub the HTTP session.

## Per item

### G0 scaffold (overseer)

- Landed: uv project pinned to `vastai==1.9.1`, strict mypy, the §7 error table, shared dataclasses, the `Provider` and `BoxAccess` protocols, the CLI parser with the §4 and §4.0 flag-combination checks, the per-invocation `Context`, stubs and the fakes.
- Files: `pyproject.toml`, `uv.lock`, `.gitignore`, `src/rig/{errors,models,provider,remote,cli,context,output}.py`, module stubs, `tests/fakes.py`, `tests/conftest.py`, `tests/test_cli.py`.
- Commits: `9a97809`, `62deb01`, `ebe6c95`.

### G1 configuration, `rig config`, `rig completion` (§5, §4.10, §10.4)

- Landed: seven-layer resolution with per-key sources, profile merging across files, `RIG_<KEY>` env mapping, `startup`/`startup_file` rules, `daily_budget` sources, the built-in Qwen model entry, `config show|set|profiles`, and bash/zsh/fish completion with lease and group names from the cache.
- Files: `src/rig/config.py`, `src/rig/commands/config.py`, `src/rig/commands/completion.py`, `tests/test_config.py`, `tests/test_completion.py`.
- Commits: `66f7980`, merge `b3f4f9b`.
- Choices: an unknown `--profile` returns `invalid_arguments`. `config set` drops TOML comments when it rewrites the file. A subprocess test confirms `config show` and `completion` load no third-party module.

### G2 labels, ids, time, cache (§8.0, §4.0, §4.2, §3, §8.1)

- Landed: `rig:v1` label parse and format with unknown fields kept, lease ids and name validation, durations, RFC 3339 times, the `Date`-header clock, and `leases.json` with a re-entrant `flock` and temp-file replace.
- Files: `src/rig/{labels,ids,timeutil,cache}.py`, `tests/test_{labels,ids,timeutil,cache}.py`.
- Commits: `a14b15c`, merge `cb84954`.
- Choices: duration units appear in d, h, m, s order, once each. `miss` uses a comma separator.

### G3 Vast provider adapter (§10.2, §10.3, §10.5)

- Landed: the ten provider functions and `last_date` over the SDK's `VastClient`. Create runs with retries off and raises `ProviderTimeout`. Listing follows `next_token`. Ports, `dph_total` and 404 rows are normalized.
- Files: `src/rig/provider.py`, `tests/test_provider.py`.
- Commits: `f9664c0`, merge `7458c2d`.
- Import time: `import vastai` measured 160–175 ms warm, under the 250 ms threshold, so the SDK stays. `import rig.provider` loads neither `vastai` nor `requests`.
- Choices: with no instance charge rows, `covered_through` is the day start, so the first reserve of a quiet day can proceed.

### G4 onstart, watchdog, probe, `SshBox` (§3.2, §5.1, §5.3, §6, §4.6, §4.8)

- Landed: gzip+base64 `onstart` with the 4048-character limit, the clock-file write, the env file, the startup wrapper, the essentials installer for custom images, the watchdog script (lock, cron restart, backoff, late-extend re-read), the one-command probe, tmux job supervision with on-box job records, rsync and interactive ssh.
- Files: `src/rig/onstart.py`, `src/rig/scripts/watchdog.sh`, `src/rig/remote.py`, `tests/test_onstart.py`, `tests/test_remote.py`.
- Commits: `6f8edcc`, merge `9294da0`.
- Encoded `onstart` size: 1003 characters on the default image, 2473 with `--image`.
- Choices: a startup hook cut off by a restart writes `-1` to `startup.exit`. A custom image's gaps go to `/workspace/.rig/unsupported` and surface as `image_unsupported`.

### G5 state, guard, warnings, budget (§3, §3.1, §4.4, §5.2)

- Landed: the §3.1 state table, history precedence, guard layers, per-lease warnings with one shared fix table, and the Decimal budget projection with refusal details and the 90% `budget_low` threshold.
- Files: `src/rig/state.py`, `src/rig/budget.py`, `tests/test_state.py`, `tests/test_budget.py`.
- Commits: `1f94425`, merge `adb854b`.
- Choices: warning fixes name the lease id, matching the §4.4 examples.

### G6 engine, targeting, `rig status` (§4.0, §4.4, §6 sweep, §8.1)

- Landed: `engine.refresh` lists, sweeps with the re-read check, reconciles history with the 24h window, probes running boxes in parallel and writes `expires=` and `miss=` to labels. Also TARGET resolution, shared output builders, 60s billing cache, `budget_check`, and `status` in JSON, table, group, `--cached` and `--verbose` forms.
- Files: `src/rig/engine.py`, `src/rig/targeting.py`, `src/rig/views.py`, `src/rig/commands/status.py`, `src/rig/cache.py`, `tests/test_{engine,targeting,status}.py`.
- Commits: `b331d0e`, merge `4d87228`.
- Choices: history leases appear in `status` when named or with `--verbose`. A second instance carrying an existing lease id is treated as unreadable.

### G7 `reserve`, `extend`, `tag` (§4.1, §4.2, §4.5, §6 write order)

- Landed: offer ranking, name idempotency with `flag_mismatch`, budget refusal, create recovery by `lease=` label, the readiness wait with destroy at the effective expiry, port validation, SSH key registration, extend write order with restore, atomic bulk extend, label setters and orphan adoption.
- Files: `src/rig/commands/{reserve,extend,tag}.py`, `src/rig/engine.py`, `tests/test_{reserve,extend,tag}.py`.
- Commits: `70edc2b`, merge `6ac4e04`.
- Choices: with no `.pub` file next to `ssh_key`, `reserve` skips key registration and prints one stderr line.

### G8 `release`, `run`, `serve`, `sync`, `ssh` (§4.3, §4.6–§4.9)

- Landed: release summaries, `already_absent`, orphan confirmation, attached and detached `run` with SIGINT forwarding and exit-code passthrough, `--sync`, `serve` with per-job keys, vLLM venv install and readiness polling, `sync` with default excludes, and `ssh` passthrough.
- Files: `src/rig/commands/{release,run,serve,sync,ssh,_common}.py`, `tests/test_{release,run,serve,sync,ssh}.py`.
- Commits: `936d873`, merge `e27daf8`.
- Choices: a dropped connection on an auto-reserved `run` leaves the box up for its TTL, since the job may still run.

### Integration (overseer)

- Landed: end-to-end tests that drive `run` and `serve` through the real `reserve_lease`, plus the §9.1 and §9.4 workflows and the sweep.
- Files: `tests/test_integration.py`.
- Commit: `1be32a9`.

## Findings dropped

None. No item guarded only against misuse of the user's own configuration.

## Open items

Live tests from spec §12. None ran, because live calls spend money:

- Scheduled jobs: does `schedule_job` fire once at `start_time` when `end_time` is under one cadence away? Do cadences below one hour work?
- `CONTAINER_API_KEY`: is it bound to the box's IP, and is it sometimes absent? Can it read its own instance row? Does a container-key `DELETE` work while the instance is `loading`?
- `/charges`: does it clip to the day range, and how far does it lag?
- `ports`: is the field absent until the instance runs? Does adding a port recreate the container?
- The `on-demand`/`ondemand` inconsistency.
- Does a 404 mean unauthorized?
- The `label` length limit at create.

Provider assumptions from G3 that need the same live check:

- The `/charges/` row shape and the `day` filter.
- The `GET /ssh/` response shape.
- `balance` versus `credit` on `/users/current`.
- Exact `gpu_name` strings for each family.
- Whether `/api/v1/instances/` rows include `ports`, `gpu_ram` and `image_runtype`.
- Whether `-p 22:22` in `env` is harmless with the ssh runtypes.
- Which shell Vast uses to run `onstart`.

Deferred work:

- Build and publish the `rig/base:cuda12.4` image. It copies `src/rig/scripts/watchdog.sh` to `/opt/rig/watchdog.sh`.
- Add CI with the §10.3 import-time budget.
- Publish to PyPI and check the `rig` name (§10.4).
- Third guard layer through scheduled jobs (§6, v1.1).
- MCP wrapper (§12).
