# Live run 8 fixes

Plan for the changes live run 8 pass 4 calls for, and the reduced loop that confirms them. Evidence is in [live-run-8-findings.md](live-run-8-findings.md) and `/private/tmp/vasty-live-8d/out/run-report.md`. Paths under `out/` are relative to that run dir. Branch `feature/reduce-api-surface` at `06a715c`.

Review against [review-brief.md](review-brief.md). Each item names the caller, the code it touches, the change and the test that covers it. Design questions carry options and a recommendation.

## 1. Boot deadline counted from create

Caller: B, E and F in wave 1. Four boxes sat in Vast `loading` for about 10 minutes each until the TTL ended them (`out/b-wave1/02-run.json:2-3`, `out/e/06-reserve.json`, `out/f-wave1/05-run.json`, `out/f-wave1/08-run.json`). 41 minutes of blocked waits, three retries, five extra commands and F's wave 1 fail.

Code: `wait_ready` in `src/vasty/commands/reserve.py:530`. The only give-up before expiry is `_no_ssh`, which starts counting at `running_at`. A box that never leaves `created` or `loading` waits to the clock.

Change: add `LOAD_WAIT_S` beside `SSH_WAIT_S` in `src/vasty/state.py:33`. In `wait_ready`, when `lease.running_at is None` and `now - lease.label.created >= LOAD_WAIT_S`, raise through `_give_up` so a box this call created is destroyed, with code `box_unreachable`, message `Lease L stayed loading on Vast for 10m after create.` and hint `Run vasty reserve again; another offer boots faster.` Set `LOAD_WAIT_S` to 10 minutes.

Length. B's healthy rerun box 59348065 was created at 01:17:40Z and first read `running` between the 01:21:25Z and 01:22:26Z samples (`out/ledger.log:41-45`), 3m45s to 4m46s in `loading`. Pass 3 saw a 3.5 min boot and the partial pass 4 a 12m42s one. 5 minutes would have destroyed B's box. 10 minutes is twice the longest healthy boot in this pass and saves time on TTLs above 10 minutes, such as F's 15 minute profile.

Test: `tests/test_reserve.py`, a fake that holds `actual_status` at `loading` past `LOAD_WAIT_S`, asserting the error code, the destroy call and the message. README line 264 gains one sentence: a box still loading 10 minutes after create is destroyed and `reserve` returns `box_unreachable`. Write the `--ttl` help line in item 6 to match.

## 2. Name the verb in the hint

Caller: B and F ran `run` and got a hint naming `reserve` (`out/b-wave1/02-run.json:4`, `out/f-wave1/05-run.json:4`).

Code: `_not_ready` at `src/vasty/commands/reserve.py:512`.

Change: give `wait_ready` a `verb` argument that `reserve`, `run` and `serve` pass, and build the hint from it: `Run vasty run again, or pick another offer with --gpu or --region.`

Test: `tests/test_run.py` for the verb in the hint.

## 3. `run --detach` reports an instant exit

Caller: B rerun. `run --detach -- python train.py` returned rc 0 (`out/b/02-run.rc`) while the job had exited 127 because the default image has no `python` (`out/b/03-status.json:19-28`, `duration_s` 0). B paid a `status` and a second `run`. Persisted from pass 3.

Code: the detach branch at `src/vasty/commands/run.py:187`, `RunDetachedResult` in `src/vasty/models.py`.

Change: the detach branch sleeps 2 seconds after the start and calls `ctx.box.job_status` once, as `_box_finished` does. `RunDetachedResult` gains `state` and `exit` from that read, `running` and null while the job runs, `exited` and the code when it has ended. The human line names the exit when there is one: `j-1 exited 127 within 2s. Log: ...`. The exit code of `run --detach` stays 0; the caller reads `exit`.

Fixed check length is a design choice. 2 seconds catches a missing interpreter and a bad path. Nothing longer belongs here, since the attached form already waits.

Test: `tests/test_run.py` with a fake `job_status` returning `exit` 127, asserting the fields and the human line.

README: line 133 adds `state` and `exit` to the detached row. Line 202 changes `python` to `python3`. Line 37 names `python3` as the interpreter the default image ships.

## 4. Auto-released attached `run` returns the final clock

Caller: F, both attempts. `expires_at` and `cost` came back null on an attached `run` that reserved and released its own box (`out/f/05-run.json:6-10`). F added `--name` plus a `release` to read them each time. Pass 3's F did the same.

Code: `_attach` in `src/vasty/commands/run.py` and the `RunResult` clock fields at `src/vasty/models.py:371`.

Change: fill `expires_at` from `effective_expiry(lease.label)` taken before the release. `ttl_remaining_s` stays null. `cost` stays null, per README line 282, until Vast posts a row. README line 159 changes with it.

Test: `tests/test_run.py` asserting `expires_at` on an auto-released result.

## 5. `destroy_pending` on release

Caller: A, B rerun, C, D and F rerun each ran a confirming `status` after `release` returned `destroy_pending: true` (`out/a/07-status.cmd`, `out/b/12-status.cmd`, `out/c/09-status.cmd`, `out/d/06-status.cmd`, `out/f/08-status.cmd`). Six commands across the pass.

Code: `summarize` at `src/vasty/commands/release.py:156` emits `destroy_pending` only when true, and after a destroy call it is always true unless `already_absent`.

Change: drop `destroy_pending` from the `release` output. `status` keeps it, where it varies. README line 154 loses the field.

Test: `tests/test_release.py` asserting the key is absent after a destroy.

## 6. Doc lines

- README line 183: `release` on a history lease returns rc 0 with `already_absent`, as line 154 says. Caller B (`out/b-wave1/07-release.json:15`).
- README line 83 and the `--ports` help at `src/vasty/cli.py:134`, which reads `default: none`: ports 22, 8000 and 8080 map by default. Caller G (`out/g/02-reserve.json:17-21`). Pass 3 and the partial pass 4 raised it.
- `--ttl` help: a box a waiting command created ends 10 minutes after create if still loading, and any other box that never boots ends at `created + ttl`, matching README line 264. Callers B and E.
- README line 169: adoption with `tag` restarts `uptime_s` at the adoption time. Caller C (`out/c/08-release.json:4-5`). C voted to carry `start_date` into the adopted lease instead. That adds a label field for one reader. Take the doc line.
- README line 282: `cost` can read `0.0` when Vast has posted a zero charge row. `lease_cost` at `src/vasty/views.py:66` sums the rows and returns null only when none exist, so the `0.0` A, E and F saw came from Vast. Callers A, E and F (`out/a/06-release.json:5`).

## Leave alone

Judged in the findings as one caller at no command cost, or a flag combination rule: A's cheapest-price pick, G's wait verb, C's `tag` selectors, D's disk note, F's previous value on `config set`, E's `extend` on a pending lease, the release cost below a later `status`.

## Harness, before the next loop

- Skill `~/.claude/skills/live-run`: the phase orchestrator's turn blocks while a spawned child runs, so B's follow-up went out 12 minutes late in wave 1 and C spawned 10 minutes after its setup in wave 2 (`out/run.md:23`, `:33`). Fire the follow-up from a background Bash timer started at the child's report, and spawn children one per message so a later spawn never waits on an earlier child.
- `docs/live/8d-seed/out/check.py`: test the `--profile prep` condition on its own. It currently fails whenever the `extra.ok` condition fails (`out/f-wave1/check.txt:5`).
- `docs/live/8d-seed/setup-c.sh`: strip `instance_api_key` from `05-orphan-create.json` before writing it.
- Stop `ledger.sh` and `manager.sh` once the account reads `[]` and the credit holds for two lines.

## Live run 9

One wave, three agents on opus at medium, fresh owners r9a, r9b, r9f. Spend cap $0.50.

- A: cold start under price pressure, as in run 8. Confirms item 1 only if a box stalls, and otherwise costs 7 commands.
- B: detached job with the follow-up at 4 minutes. Confirms item 3 with `python` in the task so the instant exit shows in `02-run.json`, then items 5 and 6 on release. Pass adds: the `run` `.json` has `exit` 127 and `state` `exited`.
- F: configuration, as in run 8. Confirms item 4. Pass adds: the auto-released `run` `.json` has `expires_at`.

Pass: all three verdicts PASS, and no `status` follows a `release` in any `.cmd` sequence. Merge when the loop returns only doc lines.

## Order

Items 1 and 2 together in one commit, with their tests. Item 3 next. Items 4, 5 and 6 in one commit. Harness changes before spawning run 9. `uv run pytest`, `uv run ruff check .` and `uv run mypy` before each commit.
