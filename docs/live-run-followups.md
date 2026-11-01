# Follow-ups from live runs 2, 3 and 4

Decided 2026-10-31 from `docs/live-test-report-2.md`, `-3.md` and `-4.md`. Input to the issue split. Delete after the issues exist.

## 1. Help text for every flag, plus `--version`

One line per flag with unit and default. `ssh --help` shows `-- COMMAND`. `sync --help` shows `push|pull SRC DEST` and `--delete`. `vasty --version` prints the package version.

Source: every fresh agent in runs 2, 3 and 4 guessed `--cuda`, `--ttl` and the default image.

## 2. The vLLM path carries its CUDA floor

- When the image is one vasty names itself and no `--cuda` is set, apply the image's floor: 13 for `vllm/vllm-openai:v0.32.0`, 12.6 for `vastai/base-image:cuda-12.6.3-auto`. A `--cuda` flag, profile or config value wins. `config show` reports the source as the image.
- The auto-reserve `vllm_missing` hint keeps the caller's `--ttl` and `--name` and adds `--cuda 13`.

Source: run 2 items 7a and 7b, run 3 attempt 1.

## 3. `vasty stop LEASE [JOB]`

LEASE resolves like `status`. JOB is implied when one job is live and required when several are; the error lists them. Send TERM to the job's process group, poll up to a 10 s grace, write the exit record. Return `lease`, `job`, `state`, `exit`, `duration_s`. A job still running after the grace returns `state: running` with exit 2.

Source: run 2 item 5 setup, run 4 scenario 4B.

## 4. `box_unreachable` fix is `vasty status LEASE`

Change the table entry in `state.py`. State derivation stays as it is.

Source: run 3 w3 and attempt 1, run 2 boot sample.

## 5. `expiring_*` fix sized from the lease

Fix is `vasty extend LEASE --by TTL` with the lease's own ttl from the label. The message rounds the time up, so 174 s reads `3m`.

Source: run 3 phase 2, run 4 scenario 4A.

## 6. Create and wait failures

- After any create failure, list instances by the lease label. Destroy what is found. Return `provider_error` with `lease`, `instance_id` and `destroyed` in details.
- During the readiness wait, a refresh error writes one stderr line and the wait continues until the lease's clock. Ctrl-C still destroys a box this call created.
- Every error raised after create names the lease and whether the box was destroyed.

Source: run 3 phase 1 first reserve, run 4 ghost instance.

## 7. One job entry shape

- The job id key is `job` in every result: `status`, `release`, `run`, `serve`, `stop`.
- `release` job entries gain `state`.
- `release` finishes every live job record: `state: killed`, `exit: null`, `duration_s` frozen at release. `unknown` stays for a pid that vanished without a record.
- README result table lists the job entry fields.

Source: run 3 items 7 and 12, run 4 lists 1 and 3.

## 8. History leases stop reporting live fields

- `ttl_remaining_s` is null and `verbose.actual_status` is absent on `released`, `expired` and `gone` leases.
- Untargeted `status --verbose` applies the same owner scope to history as to active leases.
- Single-lease `status` returns `log_tail` in every state, `[]` when empty.

Source: run 3 items 11 and 13, run 4 list 3.

## 9. `sync push` creates the destination's parent

Pass `--rsync-path` with `mkdir -p` of the destination's parent.

Source: run 3 w1 and w2, both attempts.

## 10. One follower per lease per machine

Record the follower pid in the lease cache. `reserve` and `extend` spawn only when no recorded follower is alive.

Source: run 3 item 15, run 4 hiccups.

## 11. README follows the code

- Result tables: `error` and `released` on attached `run`, `model` on `serve`, per-lease fields on bulk `release`, job entry fields, the `stop` result.
- Where `run --sync DIR` lands and the remote working directory.
- Offer order: reliability, then download bandwidth, then price, then id.
- The clock starts when Vast reports `running`; the startup hook runs on it.
- Swarm workers set `VASTY_OWNER`.

## Declined

- Prefer cheaper offers. `max_price` is the filter; item 11 documents the order.
- Start the clock after the startup hook. Vast bills from `running`, so ttl equals billed time.
- A readiness deadline shorter than the clock. Item 6 removes the ghost behind it.
- Map error 804 to `--cuda` in `serve_failed`. Item 2 removes the failure; agents read the cause from `log_tail`.
- Retry `release` until the endpoint stops answering. `destroy_pending: true` already says the destroy is unconfirmed.
- Rename `api_key_env`, warn on `state: unknown` jobs, `config show` money precision, profile inheriting defaults.
