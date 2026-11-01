# Decisions

Design decisions for vasty, one row each. Finding, fix, status. Each Decided row from 2026-10-31, runs 2 to 5, has an issue in `issues/001` to `issues/015`; the issue names its rows under Parent. `docs/live-run-followups.md` keeps the longer form of each item.

| Finding | Fix | Status |
|---|---|---|
| A Vast list timeout during reserve's readiness wait destroys the box and exits (run 3) | The wait logs the refresh error to stderr and keeps polling until the lease's clock. Ctrl-C still destroys. | Decided 2026-10-31 |
| A create that returns `success: false` can leave a labelled instance billing in `loading` (run 4) | After a `success: false` create, list by label, destroy what is found, return `provider_error` with `lease`, `instance_id`, `destroyed`. Timeout recovery keeps adopting the labelled instance. | Decided 2026-10-31 |
| A vLLM image on a 12.x host fails with error 804; the `vllm_missing` hint drops the caller's flags and names no floor (runs 2, 3) | Apply the image's floor when the image is one vasty names and no `--cuda` is set: 13 for the vLLM image, 12.6 for the base image. A `--cuda` flag, profile or config value wins; `config show` names the image as the source. The hint keeps `--ttl` and `--name` and adds `--cuda 13`. | Decided 2026-10-31 |
| No verb stops a job; agents use `ps` and `kill` over ssh (runs 2, 4) | `vasty stop LEASE [JOB]`. JOB implied with one live job, required with several. TERM to the process group, 10 s grace, exit recorded, job entry returned. | Decided 2026-10-31 |
| `box_unreachable` fix is `vasty release` after one missed probe (runs 2, 3) | Fix becomes `vasty status LEASE`. State derivation unchanged. | Decided 2026-10-31 |
| `expiring_*` fix is a fixed `--by 30m`; "2m left" at 174 s (runs 3, 4) | `--by` the lease's own ttl. Time left rounds up. | Decided 2026-10-31 |
| Job id key is `id` in status and release, `job` in run and serve (runs 3, 4) | `job` everywhere. `release` job entries gain `state`. README lists the entry fields. | Decided 2026-10-31 |
| A job alive at release reads `state: unknown, exit: null` with a growing `duration_s` (runs 3, 4) | `release` finishes live job records: `state: killed`, `exit: null`, duration frozen at release. A lease that reaches history without `release` freezes its live jobs at the first sample that found it gone. | Decided 2026-10-31 |
| Released leases report `ttl_remaining_s` and `actual_status: running` (runs 2, 3) | Null `ttl_remaining_s` and no `actual_status` on history leases. | Decided 2026-10-31 |
| Untargeted `status --verbose` lists every owner's history (runs 3, 4) | History lists the current owner's or `--owner O`'s; `--everyone` widens it. Active leases keep listing every owner. README follows. | Decided 2026-10-31 |
| `sync push` into a missing parent fails with rsync exit 11 (run 3) | `--rsync-path` with `mkdir -p` of the destination's parent. | Decided 2026-10-31 |
| `reserve` and each `extend` spawn a follower; several run per lease (runs 2 to 5) | Record the follower pid in the lease cache. Spawn only when none is alive. | Decided 2026-10-31 |
| A follower started before a shortening `extend --to` keeps the longer wait (run 5) | The follower re-reads the expiry after each sleep chunk. | Decided 2026-10-31 |
| `status --everyone` without `--all` is `invalid_arguments`; both drivers tried it first (run 5) | `status --everyone` reads as `--all --everyone`. `release` and `extend` unchanged. | Decided 2026-10-31 |
| `lease_not_found` for a name other owners hold hints only `vasty status` (run 5) | List their active lease ids in `details.matches`, hint `vasty status <id>`. | Decided 2026-10-31 |
| `swept` entries carry no owner (run 5) | Add `owner`. | Decided 2026-10-31 |
| An `extend` result alone cannot explain the clock move (run 5) | Add `previous_expires_at`. | Decided 2026-10-31 |
| JSON money rounds to cents: `cost` 0.0 for $0.003, `max_price` 0.27 for 0.272 (runs 4, 5) | JSON Decimals round to 0.0001. Human output stays at cents. | Decided 2026-10-31 |
| `run` and `status` report different `duration_s` for one job (run 5) | Both report the same value. | Decided 2026-10-31 |
| Followers outlive `release` by up to one sleep chunk (run 5) | `release` sends TERM to the recorded follower after checking the pid still runs `vasty sweep --follow` for that lease. A `destroy_pending` destroy falls to the next command's sweep. | Decided 2026-10-31 |
| Single-lease `status` omits `log_tail` while `pending` (run 4) | `log_tail` in every state, `[]` when empty. | Decided 2026-10-31 |
| README says `pending` until the hook exits 0; a failing hook returned `running` with `startup_failed` (run 4) | README follows `state.py`: `pending` while the hook runs, `running` with the warning after a nonzero exit. | Decided 2026-10-31 |
| Flags have no help text; `ssh --help` and `sync --help` omit their positionals; no `--version` (runs 2, 3, 4) | One help line per flag with unit and default. Show `-- COMMAND` and `push|pull SRC DEST`. Add `--version`. | Decided 2026-10-31 |
| README result tables and the `run --sync` destination lag the code (runs 3, 4) | README gains the missing fields, the sync destination and remote cwd, the offer order, the clock start at `running`, and `VASTY_OWNER` for workers. | Decided 2026-10-31 |
| Offer ranking picks reliability over price; a $0.14 box beside $0.05 offers (run 3) | Keep the order. `max_price` is the filter. Document the order. | Rejected 2026-10-31 |
| The startup hook runs on the clock, so `--ttl 12m` returned 9 minutes (run 3) | Keep the clock start at `running`; it matches Vast billing. Document it. | Rejected 2026-10-31 |
| A box stuck in `loading` waits the whole clock (run 4) | No separate readiness deadline. The create-failure fix removes the case. | Rejected 2026-10-31 |
| Nothing reports a lease with no follower (run 5) | No warning or field. The on-box watchdog and the next command's sweep cover the box. | Rejected 2026-10-31 |
| Plain `status` lists every owner's leases (run 5) | Keep it. README says so and names `totals.live_mine`. | Rejected 2026-10-31 |
| The label's `ttl` stays at the reserve's value after `extend` (run 5) | Keep it. The `expiring_*` fix reads it; `previous_expires_at` explains the move. | Rejected 2026-10-31 |
| A serve endpoint answers for 28 s after `release` returns (run 3) | No wait. `destroy_pending: true` says the destroy is unconfirmed. | Rejected 2026-10-31 |
| `config show` prints `api_key_env`, which one worker read as the key (run 3) | Keep the name. | Rejected 2026-10-31 |
| No warning on a job in `state: unknown`; `unknown` sets `busy` (run 4) | Keep both. The case came from a hand-edited pid file. | Rejected 2026-10-31 |
| `[defaults]` values flow into a named profile and can make it unreservable (run 2) | Keep the inheritance. | Rejected 2026-10-31 |
| `vasty` reads the API key from the env var only; every run 2 call and every run 3 worker loaded `~/.config/vastai/vast_api_key` by hand | Fall back to `~/.config/vastai/vast_api_key` when the env var is unset; `config show` names the source. | Decided 2026-10-31 |
| `reserve --no-wait` returns null clock fields while `status` on the pending lease shows a clock that later moves (run 4) | `status` returns both null while `pending`. The clock starts at `running`. | Decided 2026-10-31 |
| `--profile vllm` picked a Tesla V100; vLLM 0.32 has no Volta kernels (run 2) | No new filter. The README vLLM example says to pass `--gpu` on a mixed pool. | Rejected 2026-10-31 |
| `serve --on` a vLLM box on a 12.x host returns `serve_failed` with error 804 buried in `log_tail`; the floor fix covers reserve only (run 2) | When `log_tail` holds `Error 804`, the hint names `--image IMAGE --cuda 13` on a new box, keeping the caller's flags. | Decided 2026-10-31 |
