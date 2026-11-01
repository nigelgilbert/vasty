# Surface area reduction 1

Flags and config keys come out. Each remaining fix changes a default, a message or an output field. Evidence comes from live run 7 on 2026-11-01: four fresh Opus agents, one per scenario, each with the README, `--help` and a `vasty.toml`, and no source access. Raw material under `/private/tmp/vasty-live-7`.

## Flags and keys removed

| Surface | Evidence | Replacement |
|---|---|---|
| `run_ttl` config key, `auto_ttl` | `[profiles.vllm] ttl = "20m"` did nothing for `serve`; `auto_ttl` returns `run_ttl` unless `--ttl` came from a flag (`run.py:76`) | One `ttl` key, builtin 30m, precedence flag > profile > env > project file > user file > builtin, the same for `reserve`, `run` and `serve`. Auto-reserved `run` and `serve` without `--ttl` get 30m where they got 2h; the README names the change |
| `--config -` stdin JSON on `reserve`, `run`, `serve`, `config show` | No agent used it. Flags, profiles and `config set` cover one-off and persistent settings | Drop `stdin_json`, the `config_stdin` plumbing and the two combination rules it carries. `--startup -` keeps stdin |
| `startup_file` config key | A second spelling of `startup` with a mutual exclusion rule (`config.py:274`) | The `startup` config key holds script text. `--startup` takes a path or `-`. `_flag_layer` converts the flag to a file spec under the `startup` key |
| `api_key_env` config key | Indirection over the variable name | `VAST_API_KEY`, then the vastai CLI key file |
| `--plain` | Terminals already get human output; the flag exists to be rejected beside `--json` | `--json` forces JSON. Stdout type picks the rest |
| `status --all`, `status --everyone` | `status --everyone` listed three live leases at $0.3624/hr against `burn_per_hr` 0.4135 and no orphan row; selectors match active leases only (`targeting.py:7`, `status.py:70`) | Plain `status` is the account view: every owner, orphans, warnings. `--owner O` and `--group G` filter it |
| `--all` and `--everyone` on `release`, `extend`, `tag` | `--all` duplicates `--owner O` and feeds two `_check_target` rules; `--everyone` needs a third | `--owner O` per owner. Swarm cleanup is `release --owner "$VASTY_OWNER"`. `_check_target` goes |
| `tag` selectors and `--set-name`, `--set-group`, `--set-owner` | `--group` and `--owner` select on `tag` and set on `reserve`; the setters carry a second spelling | `tag LEASE [--name N] [--group G] [--owner O] [--ttl D]`, one lease per call. Bulk relabel is `status --group old` then one `tag` per id |
| `release --yes`, `confirmation_required` | The Claude Code permission classifier blocked `vasty release i-58641852 --yes` as "Interfere With Workloads" | An `i-` id typed on the command line is the confirmation, in a terminal too, as `release LEASE` already behaves. Update the recovery hints in `release.py` and say so in the README release section |
| history under bulk `status --verbose` | `status --everyone --verbose` returned 37 leases and 53 KB of history; the agent filtered it in python | `--verbose` adds fields only. `status <id>` still resolves a released lease. A released box is gone; the pattern is to reserve a new one |
| `warn_before_expiry` config key | | One fixed 5 min threshold |
| `--no-wait` on `run`, `serve`, `reserve` | `serve --help` lists it and serve rejects it under auto-reserve | Every create waits for `running`. `reserve_lease` loses its `wait` parameter |
| `extend --until` | Agents used `--by` | `--by` and `--to` remain |
| `status --cached` | | Removed, with `engine.cached_snapshot` |
| `config show` setting flags | | `config show` keeps `--profile` |

`run --sync`, `extend --by` and `extend --to` stay. Their replacements are command chains.

## Defaults and messages

- `--help` labels each setting flag's value `builtin default` and appends `see vasty config show`. Evidence: with the toml setting ttl 15m, disk 16 and max_price 0.09, `reserve --help` said 30m, 50 and 0.60; one agent passed `--ttl 30m` and `--disk 40` as guesses.
- README: `cost` on `release` is the charge rows posted so far. Vast posts charges in arrears. `status <id>` later reads the rows posted since. Charges are cached 60 s. Evidence: release 0.011 then status 0.013; release 0.029 then status 0.034.
- `any` clears `gpu` and `region`. Normalize once in config resolution and keep the cleared value in its layer so a lower layer's pin stays cleared. Evidence: `--gpu any` searched for a GPU named "any"; `--gpu ""` returned `invalid_arguments`.
- `no_offers` drops the suggested price. The hint keeps `a higher --max-price` as its first tip without a number, so a query with no other constraint still reads a full sentence. Evidence: four reserves at cap $0.059 returned `Try --max-price 0.09`, cap times 1.5 (`reserve.py:273`), while the blocker was the image's CUDA floor; a 3060 at $0.0578 existed at `--cuda 12.0`.
- `run --detach` adds `gpu`, `price_per_hr` and `ttl_remaining_s`. Job identity and `log_path` stay. Evidence: the result carried only `lease`, `job`, `log_path` and `expires_at`, and the agent issued a second `status`.
- `remote.log_tail` collapses carriage-return updates to their last frame before splitting lines and bounds bytes in one place; `serve.redact_tail` reuses it. Evidence: a 20 KB `log_tail` of tqdm bars during serve boot.
- `sync pull` creates DEST's parent locally, as `push` does on the box. rsync file-versus-directory rules are unchanged. Evidence: two agents ran `mkdir -p` first.
- `normalize_instance` reads `start_date`. Orphan rows show `uptime_s`.
- `job_duration` caps at the lease end through `views.uptime_end` when the lease is in a history state. `job_view` receives the lease in place of its state. Evidence: a pre-freeze lease released at uptime 486 s carries a job with `state: running` and `duration_s` 20920.
- `duration_s` stays integer seconds.

## Deferred

After the removals land.

- `no_offers` names each active constraint with its source. `_no_offers` receives only `OfferQuery` today, and the query built inline in `reserve_lease` (`reserve.py:120`) adds verified, rentable and external constraints the message would also have to show.
- `serve` prints one stderr line per milestone: created, running, process started, endpoint ready. Creation and readiness happen inside `reserve_lease` and `wait_ready`, so this needs a hook into `reserve`.
- Clock versus running job: an agent with 533 s on the clock and 427 s of training left saw an empty `warnings`. `expiring_with_running_job` fires at 5 min with no view of the job. No reliable input inside vasty.

## Order

1. Removals: `run_ttl`, `--config -`, `startup_file`, `api_key_env`, `--plain`, status selectors, `--all`, `--everyone`, `tag` selectors and setters, `--yes`, bulk history, `warn_before_expiry`, `--no-wait`, `--until`, `--cached`, `config show` flags. README and tests follow each.
2. Help text: `builtin default` label and the `config show` hint.
3. Output fields and messages: `no_offers` price, detach fields, log tail, pull parent, orphan age, history duration cap, `any`.
