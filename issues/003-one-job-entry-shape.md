# One job entry shape

**Type**: AFK

**Status:** 🔲 Not started

## Parent

`docs/decisions.md`, rows "Job id key is `id` in status and release", "A job alive at release reads `state: unknown`", "`run` and `status` report different `duration_s`".

## What to build

The job id key is `job` in every result: `status`, `release`, `run`, `serve` and the coming `stop`. `release` job entries gain `state`.

`release` finishes every live job record: `state: killed`, `exit: null`, `duration_s` frozen at the release time. A live job on a lease that reached history without `release` freezes `duration_s` at the first sample that found the lease gone. `unknown` stays for a pid that vanished without a record.

`run` and `status` compute `duration_s` for a job from the same timestamps.

The README result table lists the job entry fields.

## Acceptance criteria

- [ ] The job view dataclass field is `job`; tests for `status`, `release`, `run` and `serve` assert the `job` key and no `id` key in the JSON
- [ ] `release` on a lease with a live job returns the entry with `state: killed`, `exit: null`
- [ ] Two `status` calls after `release` return the same `duration_s` for that job
- [ ] A lease found gone by `sweep` freezes its live jobs; a later `status` returns the frozen `duration_s`
- [ ] A test runs a job, reads `duration_s` from `run` and from `status` on the same fake clock, and asserts equality
- [ ] README result table has a row set for job entries: `job`, `state`, `exit`, `duration_s`

## Blocked by

None - can start immediately
