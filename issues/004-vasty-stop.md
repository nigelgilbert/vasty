# `vasty stop LEASE [JOB]`

**Type**: AFK

**Status:** ✅ Done, commit 827eb9a

## Parent

`docs/decisions.md`, row "No verb stops a job".

## What to build

A new verb `stop`. LEASE resolves like `status`. JOB is implied when one job is live and required when several are; the error lists the live jobs. `stop` sends TERM to the job's process group, polls up to a 10 s grace, and writes the exit record. The result carries `lease`, `job`, `state`, `exit`, `duration_s`. A job still running after the grace returns `state: running` with exit code 2.

Agents in runs 2 and 4 used `ps` and `kill` over ssh to do this.

## Acceptance criteria

- [ ] `vasty stop LEASE` with one live job returns `state: killed` with the job entry fields from #003
- [ ] `vasty stop LEASE` with two live jobs returns `invalid_arguments` listing both job ids
- [ ] `vasty stop LEASE JOB` stops the named job and leaves the other running
- [ ] A fake job that ignores TERM returns `state: running` and the process exits 2
- [ ] A later `status` reports the stopped job with the same `exit` and `duration_s`
- [ ] README result table lists the `stop` result and the usage block lists `stop`
- [ ] Shell completion lists `stop`

## Blocked by

- #003
