# `stop` escalates TERM to KILL

**Type**: AFK

**Status:** ✅ Done in ed63e43

## Parent

`docs/stop-escalates-and-expiry-records.md`, section 1.

## Command

```
vasty run --on t --detach -- python3 /workspace/fx/stubborn.py   # ignores SIGTERM
vasty stop t --json
```

## Output

```json
{"lease": "l-cd222322", "job": "j-1", "state": "running", "exit": null, "duration_s": 21}
```

Exit code 2. A second `stop` returns the same. An Opus agent given the README killed the pid by hand over `vasty ssh` after reading the job directory on the box.

## Fix

1. `stop` sends TERM and waits up to 10 s. A job still live after that gets KILL and up to 5 s more. The record carries the job's own exit code. A job still live after KILL keeps its live state and `stop` exits 2.
2. KILL goes to every process in the job's group except the leader, so `run.sh` stays alive to write `finished` and `exit`:

   ```
   ps -eo pid=,pgid= | awk -v g="$p" '$2==g && $1!=g {print $1}' | xargs -r kill -KILL
   ```

   TERM and INT keep the atomic group kill, since `run.sh` traps both.
3. The still-running message reads "still runs 5s after KILL". The README `stop` row states the escalation and the two waits.
4. `FakeBox.signal_exits` defaults to TERM 143 and KILL 137. `ignores_term` leaves TERM ignored; KILL always lands. A test that needs the residual path sets `signal_exits` empty.

Two races stay open: a job that forks between the `ps` and the `kill` can leave a descendant, and a job that exits in the instant before KILL can take `run.sh`'s own `date` or `mv` with it, ending the record without an exit.

## Tests

- [ ] `stop` on a job that ignores TERM returns `killed`, exit 137, process exit 0, after at least 10 s; the fake's signal log reads TERM then KILL
- [ ] `stop` on a job that takes TERM returns `killed`, exit 143, with no KILL sent
- [ ] `stop` on a job that survives KILL returns its live state and exit 2 after at least 15 s
- [ ] LocalBox: KILL through `signal_job` leaves `run.sh` alive and the record reads exit 137
- [ ] LocalBox: KILL on a job that forked a child ends both
- [ ] Live check with `stubborn.py`: `stop` returns `killed` 137, `ps` on the box shows neither the python nor `run.sh`, `status` reads `busy: false`, a second `run --on` starts

## Blocked by

None - can start immediately. The `exec` change to the job script in `start_script`, in the working tree on `live-run-2` as of 2026-11-01, lands first.
