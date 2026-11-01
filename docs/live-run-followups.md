# Follow-ups from live runs 2 to 5

Decided 2026-10-31 from live runs 2 to 5; the raw output is under `docs/live/`. Each item has an issue under `issues/`: items 4 and 5 share #005, items 8 and 16 split across #007 and #008, item 12 is in #008, and the rest map one to one in the order below. `docs/decisions.md` holds the one-row form of each item and the Declined list.

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

- After a create that returns `success: false`, list instances by the lease label. Destroy what is found. Return `provider_error` with `lease`, `instance_id` and `destroyed` in details. A create timeout keeps its recovery in `create_with_recovery`: adopt the labelled instance.
- During the readiness wait, a refresh error writes one stderr line and the wait continues until the lease's clock. Ctrl-C still destroys a box this call created.
- Every error raised after create names the lease and whether the box was destroyed.

Source: run 3 phase 1 first reserve, run 4 ghost instance.

## 7. One job entry shape

- The job id key is `job` in every result: `status`, `release`, `run`, `serve`, `stop`.
- `release` job entries gain `state`.
- `release` finishes every live job record: `state: killed`, `exit: null`, `duration_s` frozen at release. A live job on a lease that reached history without `release` freezes `duration_s` at the first sample that found the lease gone. `unknown` stays for a pid that vanished without a record.
- README result table lists the job entry fields.
- `run` and `status` report the same `duration_s` for a job.

Source: run 3 items 7 and 12, run 4 lists 1 and 3, run 5 hiccups.

## 8. History leases stop reporting live fields

- `ttl_remaining_s` is null and `verbose.actual_status` is absent on `released`, `expired` and `gone` leases.
- Untargeted `status --verbose` lists the current owner's history, or `--owner O`'s. `--everyone` widens it to the account. Active leases keep listing every owner. README line "History states show when named directly" changes to say this.
- Single-lease `status` returns `log_tail` in every state, `[]` when empty.

Source: run 3 items 11 and 13, run 4 list 3.

## 9. `sync push` creates the destination's parent

Pass `--rsync-path` with `mkdir -p` of the destination's parent.

Source: run 3 w1 and w2, both attempts.

## 10. One follower per lease per machine

- Record the follower pid in the lease cache. `reserve` and `extend` spawn only when no recorded follower is alive.
- After each sleep chunk the follower re-reads the lease's expiry and recomputes its wait, so an `extend --to` that shortens the clock holds.
- `release` sends TERM to the lease's recorded follower after checking that the pid still runs `vasty sweep --follow` for that lease. A destroy left `destroy_pending` falls to the next command's sweep, as today.
- A shortened clock is picked up within one 300 s sleep chunk. The on-box clock file carries the exact time.

Source: run 3 item 15, run 4 hiccups, run 5 followers.

## 11. README follows the code

- Result tables: `error` and `released` on attached `run`, `model` on `serve`, per-lease fields on bulk `release`, job entry fields, the `stop` result.
- Where `run --sync DIR` lands and the remote working directory.
- Offer order: reliability, then download bandwidth, then price, then id.
- The clock starts when Vast reports `running`; the startup hook runs on it.
- `pending` lasts while the hook runs. A hook that exits nonzero leaves the box `running` with `startup_failed`, as `state.py` does today; the README's "until it exits 0" goes.
- Swarm workers set `VASTY_OWNER`.
- Plain `status` lists every owner's active leases. `totals.live_mine` counts the caller's.
- The vLLM example says to pass `--gpu` on a mixed pool. Run 2's `--profile vllm` picked a Tesla V100, and vLLM 0.32 ships no Volta kernels.

## 12. Owner scope reads clearly

- `status --everyone` alone reads as `--all --everyone`. `release` and `extend` keep requiring `--all` or `--group`.
- `lease_not_found` for a name other owners hold lists their active lease ids in `details.matches` and hints `vasty status <id>`.
- Each `swept` entry carries `owner`.

Source: run 5 gates 1 and 3, lists 2 to 4.

## 13. `extend` returns the previous clock

The result gains `previous_expires_at`. The label's `ttl` stays the reserve's ttl, since item 5 sizes the `expiring_*` fix from it. README says so.

Source: run 5 gate 3, B's `extend ft --by 20m`.

## 14. JSON money to four places

`to_jsonable` rounds Decimals to 0.0001. Human output stays at cents. This covers `cost`, `totals.credit` and `config show` `max_price`.

Source: run 5 numbers, `cost` 0.0 against a $0.003 charge row and `max_price` 0.27 for 0.272. Run 4 showed the same rounding.

## 15. API key from the vastai CLI file

When the env var named by `api_key_env` is unset, read `~/.config/vastai/vast_api_key`. `config show` reports which source won. `auth_missing` names both.

Source: run 2 setup, every vasty call set the key inline. Run 3, every worker that needed the key loaded it from that file by hand.

## 16. Pending leases carry no clock

`status` returns `expires_at` and `ttl_remaining_s` null while a lease is `pending`, as `reserve --no-wait` does. The clock starts at `running`.

Source: run 4 list 3, `nowait/02` to `05`.

## 17. `serve_failed` names the fix for error 804

When `log_tail` holds `Error 804`, the hint reads: the host driver is below the image's CUDA; serve on a new box with `--image IMAGE --cuda 13`, keeping the caller's `--model`, `--ttl` and `--name`. Item 2 covers the reserve path; this covers `serve --on`.

Source: run 2 item 7a, the dropped image and the 708 s reserve.

## Declined

- Prefer cheaper offers. `max_price` is the filter; item 11 documents the order.
- Start the clock after the startup hook. Vast bills from `running`, so ttl equals billed time.
- A readiness deadline shorter than the clock. Item 6 removes the ghost behind it.
- Retry `release` until the endpoint stops answering. `destroy_pending: true` already says the destroy is unconfirmed.
- Rename `api_key_env`, warn on `state: unknown` jobs, profile inheriting defaults.
- Stop counting `unknown` jobs as `busy`. Run 4 step 3 produced the case by editing a pid file by hand; no caller hit it.
- Report a missing follower in `status`. The on-box watchdog destroyed B's `ft` 7 s past its clock with none, and the next command sweeps a box both layers miss.
- Filter plain `status` to the caller's leases. Both drivers read `owner` and `totals.live_mine` correctly; item 11 documents it.
- Update or drop `ttl` in the label. Item 5 reads it; item 13 returns the previous clock.
- A compute-capability floor on the vLLM image. `--gpu` already filters the card; item 11 documents it.

