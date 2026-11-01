# `box_unreachable` and `expiring_*` name the right fix

**Type**: AFK

**Status:** 🔲 Not started

## Parent

`docs/decisions.md`, rows "`box_unreachable` fix is `vasty release`" and "`expiring_*` fix is a fixed `--by 30m`".

## What to build

The `box_unreachable` warning's fix becomes `vasty status LEASE`. State derivation stays as it is.

The `expiring_soon` and `expiring_with_running_job` fix becomes `vasty extend LEASE --by TTL`, where TTL is the lease's own ttl read from the label. The time-left message rounds up, so 174 s reads `3m`.

## Acceptance criteria

- [ ] `box_unreachable` warning carries `fix: ["vasty", "status", LEASE]`
- [ ] A lease reserved with `--ttl 45m` and 170 s left carries `fix: ["vasty", "extend", LEASE, "--by", "45m"]` and message `3m left`
- [ ] A lease with 60 s left reads `1m left`
- [ ] README warning table shows both fixes

## Blocked by

None - can start immediately
