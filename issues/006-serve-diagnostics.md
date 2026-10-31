# Serve diagnostics: log tail on `serve_failed`, key in the environment

**Type**: AFK

**Status:** 🔲 Not started

## Parent

`docs/followups-plan.md`, step 2. Serve decision 4 of `docs/serve-decisions.md` and finding 2 of the PR #1 code review.

## What to build

`serve_failed` details gain `log_tail`: the last 100 lines of the job log, capped at 64 KiB, with the serve key replaced by `<redacted>` wherever its value appears. Details also gain `lease`. `_wait_ready` reads the tail with one `ctx.box.log_tail(target, job_id, LOG_LINES)` call on the failure path, for both the exit case and the deadline case. On the deadline the read happens before `TERM`, so shutdown output does not displace the cause. A failed tail read is swallowed and `serve_failed` goes out with `exit` and `lease` alone. `_wait_ready` runs inside `_bring_up`, so the tail is read before `execute` releases an auto-created box.

`server_argv` drops `--api-key`. The job script exports `VLLM_API_KEY` with the key, so the command line, `ps` output and any argv echo carry no secret. The redaction helper stays as a second guard, shared by the two raise sites.

`LOG_LINES` moves from `status.py` to a shared constant that `status` and `serve` both import.

The `vllm_missing` hint under `--on` names the lease and says to install `vllm` on it through `run --on LEASE` or `ssh`. The hint under auto-reserve keeps naming `--image vllm/vllm-openai:v0.32.0`.

## Acceptance criteria

- [ ] `serve` on a fake box whose job exits 1 raises `serve_failed` with `details.exit`, `details.lease` and `details.log_tail`, and the fake records one `log_tail` call.
- [ ] `serve` past the readiness deadline raises `serve_failed` with `details.log_tail`, and the fake records the `log_tail` call before the `TERM` signal.
- [ ] A tail read that raises leaves `serve_failed` with `exit` and `lease` and no `log_tail`.
- [ ] A log of 200 lines yields 100 lines; a log whose last 100 lines exceed 64 KiB is cut to 64 KiB.
- [ ] A log line that contains the key comes back with `<redacted>` in its place.
- [ ] The started job's command contains no `--api-key`, the displayed `cmd` contains no key, and the job script sets `VLLM_API_KEY`.
- [ ] `grep -rn "LOG_LINES = " src/` returns one line.
- [ ] `serve --on LEASE` on a box without `vllm` raises `vllm_missing` with a hint naming `LEASE` and no `reserve` or `--image`.
- [ ] `uv run pytest` and `uv run mypy` pass.

## Blocked by

None - can start immediately
