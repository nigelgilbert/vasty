# Defect: `vasty stop` records the wrapper's exit as the job's

Found on 2026-11-01 in live run 6, phase 1 steps 17 and 18, on a real RTX 3060 box. The README's `stop` result row holds the contract.

## Summary

`stop` sends TERM to the job's process group and waits up to 10 s for the box record to show an exit. The record comes from `run.sh`, a wrapper that traps TERM and runs the job through a second bash. TERM kills that second bash, `run.sh` writes its exit code 143 as the job's, and `stop` reports `state: killed, exit: 143`. The job itself received the same TERM and, if it ignores TERM, is still running at that moment. It dies a moment later from the HUP tmux sends when the pane closes. A job that ignores TERM and HUP outlives its own `killed` record.

The spec for this path reads: a job still running after the grace returns `state: running` with exit code 2. That path cannot occur today for any job, because the wrapper always exits within the grace.

## Evidence

Fixture `stubborn.py`:

```python
import signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
time.sleep(900)
```

Commands and results, lease `l-400d6072`, box `p1`:

```
vasty run --on p1 --detach --json -- python3 /workspace/a/b/c/stubborn.py
{"lease": "l-400d6072", "job": "j-2", ...}

vasty stop p1 --json                      # returned after 9 s, exit code 0
{"lease": "l-400d6072", "job": "j-2", "cmd": "python3 /workspace/a/b/c/stubborn.py",
 "state": "killed", "exit": 143, "duration_s": 39}

vasty status p1 --json                    # j-2 killed, exit 143, duration_s 39, busy false
```

Box state after the stop, from `ssh p1 -- ps -eo pid,pgid,stat,etime,args` and the job directory:

```
    379       1 S          02:23 bash /workspace/.vasty/watchdog.sh     # no python3, no bash script
---
/workspace/.vasty/jobs/j-2/
  cmd       python3 /workspace/a/b/c/stubborn.py
  exit      143
  finished  1793510819
  pid       771
  script    python3 /workspace/a/b/c/stubborn.py
  started   1793510780
```

Expected per the README: `state: running`, process exit code 2, and the python still in `ps`. Observed: `killed`, 143, exit 0, python gone.

The same TERM path on a job that honours TERM (step 15, `sleeper.py`) returned `killed`, 143, which is what the spec wants for that case. Phase 4 step 05 and phase 5 step 06 on vLLM serve jobs behaved the same way. Those results are correct; the defect is only visible on a job that survives TERM.

## Mechanism

`start_script` in `src/vasty/remote.py` writes two files per job and starts tmux:

```
run.sh:
  trap : INT TERM HUP
  cd /workspace || exit 1
  echo $$ >J/pid.tmp && mv -f J/pid.tmp J/pid
  bash J/script >>J/log 2>&1 </dev/null
  rc=$?
  date +%s >J/finished
  echo $rc >J/exit.tmp && mv -f J/exit.tmp J/exit

script:
  python3 /workspace/a/b/c/stubborn.py

tmux new-session -d -s vasty-j-2 -c /workspace 'exec bash J/run.sh'
```

So the process tree is `run.sh` (pid 771, the group leader) → `bash J/script` → `python3`. `signal_job` sends `kill -s TERM -- -771`, the whole group:

1. `run.sh` ignores TERM through its trap.
2. `bash J/script` has no trap and dies with 143.
3. `python3` ignores TERM and keeps running.
4. `run.sh` resumes after its child died, writes `finished` and `exit=143`, and exits.
5. `_job_lines` reads a non-empty `exit` file, so `_parse_job` returns `state: exited`, `exit: 143`.
6. `signal_and_wait` in `src/vasty/commands/_common.py` returns on the first record with an exit. `stop` writes the lease record as `killed` with that code.
7. `run.sh` exiting ends the tmux pane. tmux sends HUP to the pane's group. `python3` has the default HUP action and dies. By the time anyone looks, the python is gone, which is why the live-run `ps` is empty.

Step 7 is incidental. Nothing vasty does checks for it, and a job that ignores HUP as well, or that re-parented out of the group, stays alive with `state: killed` on record. `_job_lines` would still report it: `live` is computed only when `exit` is empty, so once `exit` exists the record is final.

## Why the unit test passed

`tests/test_stop.py::test_stop_job_that_ignores_term_stays_running` uses `FakeBox.signal_job`, which models a job as one process: `signal_exits` maps a signal to an exit code, and a signal with no mapping leaves the job running. The fake has no wrapper, so a TERM the job ignores produces no exit record and the grace path triggers. The real box always produces an exit record, from the wrapper.

## Impact

- `stop` on a job that ignores TERM reports success with a code that belongs to the wrapper. The job's own exit is never recorded.
- The "still running after 10 s, exit 2" contract in the README is dead code on a real box.
- `status` reads `busy: false` while the job may still hold the GPU. `run --on` and `serve --on` then treat the box as free.
- `release` destroys the instance without signalling jobs, so the job dies with the box either way. The wrong record, and the `busy: false` that follows from it, is the whole defect.
- vLLM, python, and shell jobs that take the default TERM action are unaffected.

## Fix

Make the job the process the record describes. Two independent changes, both small.

1. In `start_script`, write `script` so the job replaces the bash that runs it:

   ```
   script:  exec python3 /workspace/a/b/c/stubborn.py
   ```

   `run.sh` stays as it is, since it has to outlive the job to write `finished` and `exit`. The tree becomes `run.sh` → `python3`. TERM to the group reaches the python directly, `run.sh` waits on it, and `rc` is the job's own code. A job that ignores TERM keeps `run.sh` waiting, no `exit` file appears, `_job_lines` reports `live=1`, and `signal_and_wait` returns the running record after 10 s. For a command that is a pipeline or a `cd && cmd` sequence, write `exec bash -c '<command>'`; the extra bash is then the job's parent only for the lifetime of the pipeline and takes the default TERM action, which is the behaviour a shell pipeline has anywhere else.

2. In `stop`, accept an exit record as `killed` only when the group is empty. Add a `group_live(target, job_id)` box call that returns whether any process in the pid's group remains, and have `signal_and_wait` keep polling while it does. This covers jobs that spawn their own children and ignore TERM, which change 1 alone does not.

Change 1 is the one that fixes the observed case and restores the grace path. Change 2 is the guard for the general case.

## Acceptance criteria

- [ ] `stop` on a job that ignores TERM returns after 10 s with `state: running`, `exit: null`, process exit code 2, and `ps` on the box still shows the job
- [ ] `stop` on a job that honours TERM returns `state: killed` with the job's own exit code, 143 for a bash or python default
- [ ] `status` after a surviving `stop` reports the job `running` and `busy: true`
- [ ] `run --on` with a non-trivial command (a pipeline, a `cd && cmd`) still runs and records the right exit
- [ ] `FakeBox` models a wrapper: a job marked `ignores_term` leaves the record without an exit after TERM, and a test asserts `stop` returns exit 2 for it
- [ ] A live check on a real box with the `stubborn.py` fixture above

## Live reproduction

Any base-image box, 15 minute clock, about one cent:

```
vasty reserve --name t --ttl 15m
vasty sync t push fx/ /workspace/fx/              # fx/stubborn.py from above
vasty run --on t --detach -- python3 /workspace/fx/stubborn.py
vasty stop t --json                                # defect: killed/143 in 9 s
vasty ssh t -- 'ps -eo pid,pgid,args | grep [s]tubborn'
vasty release t
```

After the fix, `stop` returns `running` with exit code 2 and the `ps` line is still there.
