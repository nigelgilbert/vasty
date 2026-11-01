# Decisions

Design decisions for vasty, one row each. Finding, fix, status. Detail for the 2026-10-31 live-run rows is in `docs/live-run-followups.md`.

| Finding | Fix | Status |
|---|---|---|
| A Vast list timeout during reserve's readiness wait destroys the box and exits (run 3) | The wait logs the refresh error to stderr and keeps polling until the lease's clock. Ctrl-C still destroys. | Decided 2026-10-31 |
| A create that returns `success: false` can leave a labelled instance billing in `loading` (run 4) | After any create failure, list by label, destroy what is found, return `provider_error` with `lease`, `instance_id`, `destroyed`. | Decided 2026-10-31 |
| A vLLM image on a 12.x host fails with error 804; the `vllm_missing` hint drops the caller's flags and names no floor (runs 2, 3) | Apply the image's floor when the image is one vasty names and no `--cuda` is set: 13 for the vLLM image, 12.6 for the base image. The hint keeps `--ttl` and `--name` and adds `--cuda 13`. | Decided 2026-10-31 |
| No verb stops a job; agents use `ps` and `kill` over ssh (runs 2, 4) | `vasty stop LEASE [JOB]`. JOB implied with one live job, required with several. TERM to the process group, 10 s grace, exit recorded, job entry returned. | Decided 2026-10-31 |
| `box_unreachable` fix is `vasty release` after one missed probe (runs 2, 3) | Fix becomes `vasty status LEASE`. State derivation unchanged. | Decided 2026-10-31 |
| `expiring_*` fix is a fixed `--by 30m`; "2m left" at 174 s (runs 3, 4) | `--by` the lease's own ttl. Time left rounds up. | Decided 2026-10-31 |
| Job id key is `id` in status and release, `job` in run and serve (runs 3, 4) | `job` everywhere. `release` job entries gain `state`. README lists the entry fields. | Decided 2026-10-31 |
| A job alive at release reads `state: unknown, exit: null` with a growing `duration_s` (runs 3, 4) | `release` finishes live job records: `state: killed`, `exit: null`, duration frozen at release. | Decided 2026-10-31 |
| Released leases report `ttl_remaining_s` and `actual_status: running` (runs 2, 3) | Null `ttl_remaining_s` and no `actual_status` on history leases. | Decided 2026-10-31 |
| Untargeted `status --verbose` lists every owner's history (runs 3, 4) | History follows the same owner scope as the active list. | Decided 2026-10-31 |
| `sync push` into a missing parent fails with rsync exit 11 (run 3) | `--rsync-path` with `mkdir -p` of the destination's parent. | Decided 2026-10-31 |
| `reserve` and each `extend` spawn a follower; several run per lease (runs 2, 3, 4) | Record the follower pid in the lease cache. Spawn only when none is alive. | Decided 2026-10-31 |
| Flags have no help text; `ssh --help` and `sync --help` omit their positionals; no `--version` (runs 2, 3, 4) | One help line per flag with unit and default. Show `-- COMMAND` and `push|pull SRC DEST`. Add `--version`. | Decided 2026-10-31 |
| README result tables and the `run --sync` destination lag the code (runs 3, 4) | README gains the missing fields, the sync destination and remote cwd, the offer order, the clock start at `running`, and `VASTY_OWNER` for workers. | Decided 2026-10-31 |
| Offer ranking picks reliability over price; a $0.14 box beside $0.05 offers (run 3) | Keep the order. `max_price` is the filter. Document the order. | Rejected 2026-10-31 |
| The startup hook runs on the clock, so `--ttl 12m` returned 9 minutes (run 3) | Keep the clock start at `running`; it matches Vast billing. Document it. | Rejected 2026-10-31 |
| A box stuck in `loading` waits the whole clock (run 4) | No separate readiness deadline. The create-failure fix removes the case. | Rejected 2026-10-31 |
| `serve_failed` hint says read the log while `log_tail` holds the cause (run 2) | No error 804 mapping. The floor fix removes the failure. | Rejected 2026-10-31 |
