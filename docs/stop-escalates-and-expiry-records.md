# `stop` escalates to KILL, expiry warning retired, release uptime fixed

Decided on 2026-11-01 after an Opus agent exercised `stop` on a job that ignores TERM. The agent read the result correctly, found no next step in the tool, and killed the process by hand over `vasty ssh` after reading the job directory on the box. The same run surfaced a warning that repeats with a fix that reproduces it, and uptime growing after release. Astra reviewed the first draft; its trims are folded in.

## 1. `stop` ends the job

### Contract

`stop` sends TERM to the job's process group and waits up to 10 s. A job still live after that gets KILL and up to 5 s more. The record carries the job's own exit code: the usual signal exits are 143 after TERM and 137 after KILL, and a handler that exits with another code keeps that code. The result shape stays as it is. A job still live after KILL returns its live state and exit code 2, the one case left on that path.

### Mechanism

`run.sh` leads the group and cannot trap KILL. A KILL to the whole group ends `run.sh` before it writes `exit`, so the record never closes. KILL goes to every process in the group except the leader:

```
ps -eo pid=,pgid= | awk -v g="$p" '$2==g && $1!=g {print $1}' | xargs -r kill -KILL
```

`run.sh` sees its child die, writes `finished` and `exit`, and leaves. TERM and INT keep the atomic `kill -- -$p` to the group, since `run.sh` traps both.

Two races stay open and need no mechanism:

- The list is a snapshot. A job that forks between the `ps` and the `kill` can leave a descendant in the group. The record closes on the direct child; `status` shows the box free while the descendant holds it.
- A job that exits between the last poll and the KILL puts `run.sh`'s own `date` or `mv` on the list. The record then ends without an exit and `stop` reports `killed` with a null exit, as it does today for a wrapper that died.

### Changes

- `signal_job` in `src/vasty/remote.py`: KILL uses the except-leader list above.
- `stop.execute` in `src/vasty/commands/stop.py`: after `signal_and_wait(TERM, 10)` returns a live record, call `signal_and_wait(KILL, 5)`. Record `killed` with the exit the box wrote. Constants `STOP_WAIT_S = 10.0` and `KILL_WAIT_S = 5.0`.
- `stop` docstring and the still-running message: "j-1 still runs 5s after KILL".
- README `stop` row: "sends TERM, waits up to 10s, then KILL and waits up to 5s. A job still live after KILL keeps its `state` and `stop` exits 2."
- `FakeBox`: `signal_exits` defaults to `{"TERM": 143, "KILL": 137}`. `ignores_term` leaves TERM ignored; KILL always lands. A test that needs the residual path sets `signal_exits = {}`.

### Acceptance

- [ ] `stop` on a job that ignores TERM returns `killed`, exit 137, process exit 0, after at least 10 s; the fake's signal log reads TERM then KILL
- [ ] `stop` on a job that takes TERM returns `killed`, exit 143, with no KILL sent
- [ ] `stop` on a job that survives KILL returns its live state and exit 2 after at least 15 s
- [ ] LocalBox test: KILL through `signal_job` leaves `run.sh` alive and the record reads exit 137
- [ ] LocalBox test: KILL on a job that forked a child ends both when both are in the group
- [ ] Live check with `stubborn.py`: `stop` returns `killed` 137, `ps` on the box shows neither the python nor `run.sh`, `status` reads `busy: false`, a second `run --on` starts

## 2. The expiry warning goes

### Today

`expired_with_running_jobs` fires on every untargeted `status` for every expired lease in the machine's cache, including other owners'. Its message says "running" while the job entry reads `unknown`, and its fix is `status` on the same lease, which prints the warning again. No command clears it.

### Change

Delete the warning: its row in the fix table in `src/vasty/state.py`, the expired branch of `lease_warnings`, the untargeted history pass in `src/vasty/commands/status.py`, and its entry in the README warning list. Records stay as they are. A job the clock cut shows `unknown` on an expired lease in targeted `status`, and an attached `run` already exits 2 when the clock kills its job.

### Acceptance

- [ ] Untargeted `status` with an expired lease in the cache returns no warning for it
- [ ] Targeted `status` on that lease shows its job `unknown`
- [ ] `expired_with_running_jobs` appears nowhere in `src`, `tests` or the README

## 3. Released leases stop counting uptime

### Today

While a destroy is pending and the provider still lists the instance, refresh skips the lease. `history_since` stays unset and `uptime_end` falls back to now, so `uptime_s` grows until a refresh sees the instance gone.

### Changes

- `mark_released` sets `history_since = now`.
- `_to_history` sets `history_since` only when it is None and keeps clearing the destroy bookkeeping on every confirmed absence.
- `history_since` also starts the 24 h history window, so a released lease now leaves history 24 h after the release call instead of 24 h after the provider confirmed it gone.

`cost` is the sum of Vast's charge rows for the instance and can rise after release as rows post. It stays as it is.

### Acceptance

- [ ] `release` and a `status` 60 s later report the same `uptime_s` while the destroy is pending

## 4. README

- `release` row: "`destroy_pending` is true from the destroy call until a refresh sees the instance gone from the provider listing."

## Out of scope

- Attached `run` on Ctrl-C keeps its single INT and 10 s wait. A job that ignores INT shows in `status` and `stop` ends it.
- No `--kill` or `--signal` flag. Escalation is the default.
- `signal_job` trusts the saved pid. A pid-reuse check is a change for a caller that hits it.
