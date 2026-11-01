# Swarm report 0: issues 001 to 015

Run 2026-10-31 on branch `live-run-2`. Base commit `9b7f2ad`, final commit named in the last section. Seven Opus agents implemented fourteen items in parallel from the base commit; one more implemented item 015 on top of the merged result. No validation pass ran.

Final checks on the last commit:

| Check | Result |
|---|---|
| `uv run pytest -q` | 1392 passed, 1 skipped (baseline 1246 passed, 1 skipped) |
| `uv run mypy` | no issues in 35 source files |
| `uv run ruff check src tests` | 98 errors, all present at the base commit, which had 99 |

## Per item

| Item | What landed | Files | Commit |
|---|---|---|---|
| 001 Help text and `--version` | One help line per flag and positional, with unit and default read from `config.BUILTIN`. `ssh`, `sync`, `run` and `serve` usage lines show their positionals. `vasty --version` prints the package version. A test walks every subparser and fails on empty help. | `cli.py`, `tests/test_cli.py` | `6f1da7d`, `6afc391` |
| 002 Image CUDA floor | `config.resolve` sets `cuda` from `IMAGE_CUDA` when no layer sets it, source `image`. Any layer's `cuda` wins. The `vllm_missing` hint keeps `--ttl` and `--name` and adds `--cuda 13`. README drops `cuda = 13` from the sample profile. | `config.py`, `commands/serve.py`, `README.md`, tests | `a8af11e` |
| 003 One job entry shape | `JobView.job` replaces `id`; `release` returns `JobView` entries with `state`. `release` marks live jobs `killed`, exit null, duration frozen. A lease that reaches history freezes its live jobs at that sample. `run` reads the box's finish time so its `duration_s` matches `status`. | `models.py`, `views.py`, `engine.py`, `commands/{release,run,status,_common}.py`, `README.md`, tests | `e397cf9` |
| 004 `vasty stop` | New verb. JOB implied with one live job, `invalid_arguments` listing the live ids otherwise. TERM to the process group, 10 s poll, `killed` recorded through `finish_job`. A job still live after the grace returns its live state with exit 2. Completion lists `stop`. | `commands/stop.py`, `cli.py`, `commands/completion.py`, `models.py`, `README.md`, `tests/test_stop.py` | `827eb9a` |
| 005 Warning fixes | `box_unreachable` fix is `vasty status LEASE`. `expiring_*` fix is `vasty extend LEASE --by TTL` from the label ttl. Time left rounds up to the minute. README gains a Warning/Fix table. | `state.py`, `timeutil.py`, `commands/run.py`, `README.md`, tests | `b98873b` |
| 006 Create and wait failures | A `success: false` create raises `CreateRejected`; reserve lists by label, destroys matches, returns `provider_error` with `lease`, `instance_id`, `destroyed`. A refresh error during the wait writes one stderr line and the wait continues to the lease's clock. Every error after create carries `details.lease` and `details.destroyed`. | `provider.py`, `commands/reserve.py`, tests | `59b8b5f` |
| 007 Status fields by state | `expires_at` and `ttl_remaining_s` null while `pending`; `ttl_remaining_s` null and no `actual_status` in history. Single-lease `log_tail` is a list in every state. | `views.py`, `commands/status.py`, `README.md`, tests | `1849d27` |
| 008 Owner scope | `status --everyone` alone parses. `--verbose` history scopes to the caller, `--owner O` or `--everyone`. `lease_not_found` for a name other owners hold carries `details.matches`. `SweptEntry` gains `owner`. | `cli.py`, `targeting.py`, `commands/status.py`, `engine.py`, `models.py`, `README.md`, tests | `490f134` |
| 009 `sync push` parent | `rsync_argv` adds `--rsync-path=mkdir -p PARENT && rsync` on push. Pull unchanged. `/`, `.` and home give plain rsync. | `remote.py`, `commands/sync.py`, `tests/test_remote.py` | `691239f` |
| 010 One follower per lease | `CachedLease.follower_pid`. `spawn_follow` starts a follower only when the recorded pid no longer runs `vasty sweep --follow LEASE`. The follower re-reads the cached expiry after each chunk. `release` TERMs the recorded follower through `stop_follower` after checking its command line. | `models.py`, `commands/sweep.py`, `commands/release.py`, `context.py`, `README.md`, tests | `101c4b5` |
| 011 `previous_expires_at` | `ExtendResult` and each bulk entry carry it. Label `ttl` stays the reserve's. | `commands/extend.py`, `models.py`, `README.md`, `tests/test_extend.py` | `9695137` |
| 012 JSON money | `to_jsonable` rounds Decimals to 0.0001 through `json_money`. Human output keeps cents. | `output.py`, tests | `d26f3db` |
| 013 API key file | `config.api_key` reads the env var, then `~/.config/vastai/vast_api_key`. `auth_missing` names both. `config show` adds `api_key_source`. | `config.py`, `context.py`, `commands/config.py`, `README.md`, tests | `54bc5e0` |
| 014 `serve_failed` 804 hint | A `log_tail` holding `Error 804` swaps the hint for `vasty serve --model M --image IMAGE --cuda 13` plus the caller's `--ttl` and `--name`. | `commands/serve.py`, `README.md`, `tests/test_serve.py` | `850a1e7` |
| 015 README follows code | Result table gains `error` on attached `run`, `model` on `serve` and the bulk `release` fields. New lines for the offer order, `run --sync`, the clock start, the hook and `pending`, `VASTY_OWNER` for workers, plain `status` scope and `totals.live_mine`, and `--gpu` with the vLLM profile. `tests/test_readme.py` checks every table field against its dataclass. | `README.md`, `tests/test_readme.py` | `0471d0a` |

Test command for every item: `uv run pytest -q` on the merged branch. Result after the final merge: 1392 passed, 1 skipped.

## Overseer edits

- `6afc391` removes a duplicated line in `build_parser` and updates the `--cuda` and `--everyone` help strings to match items 002 and 008.
- Cherry-pick conflicts in `README.md`, `tests/test_release.py` and `cli.py` were resolved by keeping both sides.
- `c8aa0b0` and the final commit mark the issue Status lines and update the README test count.

## Judgment calls the agents recorded

- Item 004: `stop` records the job's real exit code, normally 143 after TERM, with `state: killed`. `release` keeps `exit: null`. A serving job that ignores TERM reports `serving` rather than `running`, with exit 2 either way.
- Item 003: a live job on an expired or gone lease keeps `state: unknown`; only its `duration_s` is frozen. `killed` is reserved for `release` and `stop`.
- Item 006: `destroyed` means destroyed by this call. A lease that ended during the wait reports `destroyed: false`. One list follows a rejected create, with no polling. Every refresh error during the wait writes its own stderr line.
- Item 002: the `vllm_missing` hint uses `--profile vllm` when that profile exists, else `--image vllm/vllm-openai:v0.32.0`, and appends the follow-up `serve --on` command.
- Item 008: `--verbose` with a bulk selector now adds history in the same owner scope; `--group G --verbose` shows the caller's history in G.
- Item 009: `run --sync` pushes also carry `--rsync-path` with `mkdir -p /workspace`.
- Item 010: a lengthening `extend` also moves the follower's wait later. The command-line match accepts `python -m vasty` and the installed `vasty` script.
- Item 013: `api_key_source` is a top-level field of the `config show` result rather than a `values` entry.
- Item 015: "swarm workers set `VASTY_OWNER`" is written as each worker setting its own owner. Bulk `release` rows omit `already_absent`.

## Findings dropped and why

None. Every item in issues 001 to 015 was implemented.

## Open items

- `tests/test_remote.py::test_write_clock_translates_into_box_time` reads the wall clock twice and fails when the second ticks between the reads; its tolerance window is -5 to 0 and the observed difference was 1. It predates this run. Widening the window to 1 removes the flake.

## Closed after the report

- `8675205` names `stop` in the `orphan_unmanaged` and `lease_pending` README rows. The `lease_expired` row lists no verbs.
- `9f56d7a` drops the unused `__version__` constant.
- `a5087a2` documents `already_absent` on both `release` rows.
