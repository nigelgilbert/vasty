# Swarm report 0

Work file: `docs/surface-area-reduction-1.md`. Base commit `1ea0454` on `feature/reduce-api-surface`. Four Opus agents, one per file group, merged by the overseer. No validation pass ran; the caller validates by hand.

Final checks on `01d0a47`:

```
uv run pytest -q    1427 passed, 1 skipped
uv run mypy         Success: no issues found in 35 source files
uv run ruff check   All checks passed!
```

## Per item

Commits: `97f2ec2` (group 3), `6da4a66` `fad9ae3` `82e411c` (group 4), `a153872` (group 2), `e705438` (group 1), merges `9aa89ee` `105a002` `1ebce49`, overseer `28744d7` `01d0a47`.

| Item | Landed | Files |
|---|---|---|
| `run_ttl`, `auto_ttl` | One `ttl` key through flag > profile > env > project > user > builtin for `reserve`, `run`, `serve`. README names the 2h to 30m change | `config.py`, `commands/run.py`, `commands/serve.py`, `commands/config.py` |
| `--config -` | `stdin_json`, `config_stdin`, the stdin layer and both combination rules removed. `--startup -` keeps stdin | `config.py`, `context.py`, `cli.py` |
| `startup_file` | `startup` holds text; `_flag_layer` turns `--startup PATH` into a file spec and `-` into stdin. `overlay` is a plain merge | `config.py` |
| `api_key_env` | `api_key(env, home)` reads `VAST_API_KEY`, then the vastai key file | `config.py`, `context.py`, `commands/config.py` |
| `--plain` | `--json` forces JSON; stdout TTY picks the rest | `cli.py` |
| `status --all`, `--everyone` | Plain `status` is the account view; `--owner` and `--group` filter active leases | `targeting.py`, `commands/status.py`, `cli.py` |
| `--all`, `--everyone` on `release`, `extend`, `tag` | Selectors are `--group` and `--owner`. `_check_target` removed. A LEASE with a selector raises `invalid_arguments` through `targeting.check_selector` | `targeting.py`, `commands/release.py`, `commands/extend.py`, `cli.py` |
| `tag` selectors and setters | `tag LEASE [--name N] [--group G] [--owner O] [--ttl D]`, one lease per call | `commands/tag.py`, `cli.py`, `commands/completion.py` |
| `release --yes`, `confirmation_required` | Orphan release by `i-` id destroys without a prompt. Hints and README updated. Error code removed | `commands/release.py`, `commands/reserve.py`, `errors.py` |
| bulk `status --verbose` history | `_history` removed; `--verbose` adds fields only | `commands/status.py` |
| `warn_before_expiry` | `state.EXPIRY_WARN_S = 300`; parameter dropped from `lease_warnings` and `warnings_for` | `state.py`, `views.py`, callers |
| `--no-wait` | `reserve_lease(ctx, args, snap, ttl=...)` always waits | `commands/reserve.py`, `run.py`, `serve.py`, `cli.py` |
| `extend --until` | Removed with `timeutil.parse_time` | `commands/extend.py`, `timeutil.py`, `cli.py` |
| `status --cached` | Removed with `engine.cached_snapshot`, `Snapshot.cached_at`, `StatusResult.cached_at` | `engine.py`, `models.py`, `commands/status.py`, `cache.py` |
| `config show` flags | Keeps `--profile` | `cli.py`, `commands/config.py` |
| `--help` labels | `builtin default: X; see vasty config show` on every flag with a config key; one `--ttl` string across the three verbs | `cli.py` |
| README `cost` on release | Spend paragraph states arrears and the 60 s cache | `README.md` |
| `any` clears `gpu`, `region` | Normalized in `_convert_table`; the clearing layer keeps the key. `--gpu ""` behaves the same | `config.py` |
| `no_offers` price | First tip is `a higher --max-price` with no number | `commands/reserve.py` |
| `run --detach` fields | Adds `gpu`, `price_per_hr`, `ttl_remaining_s` | `commands/run.py`, `models.py` |
| `log_tail` | `remote.tail_lines` collapses `\r` frames, keeps the last N lines within 16 KiB; `SshBox.log_tail` moves the tail through base64 so `\r` survives text capture; `serve.redact_tail` reuses it | `remote.py`, `commands/serve.py` |
| `sync pull` parent | Local `mkdir -p` of DEST's parent before rsync | `commands/sync.py` |
| orphan `uptime_s` | `Instance.start_date` from `normalize_instance`; `orphan_view` takes `now` | `provider.py`, `models.py`, `views.py` |
| `job_duration` cap | Open end is `uptime_end(lease, now)`; `job_view` takes the lease | `views.py`, `commands/release.py`, `commands/stop.py` |
| `duration_s` integer | Unchanged, integer seconds | |

Tests follow each item. Tests for removed surfaces are deleted; new tests cover rejection of each removed flag, ttl precedence on `run` and `serve`, help text, `any` clearing, orphan uptime, the duration cap, `tail_lines` and the pull parent.

## Findings dropped and why

None dropped. Every item in the work file landed.

## Open items

- `reserve_result` and `reserve.render` still handle a `pending` lease. That path is unreachable from the CLI now that every create waits.
- `CacheData.instances` and `CacheData.cached_at` are written by `refresh` and read by nothing. Dropping them changes the cache file format.
- `SshBox.log_tail` decodes base64 without catching `binascii.Error`. Every `_script` caller sees clean stdout today.
- `tail -n N` on the box has no byte cap before the local 16 KiB bound.
- The README `no_offers` example message still reads `gpu=4090` with no cuda constraint.
- The three deferred items in the work file stand: constraint sources in `no_offers`, `serve` milestone lines, clock versus running job.
