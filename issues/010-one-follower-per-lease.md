# One follower per lease per machine

**Type**: AFK

**Status:** ✅ Done, commit 101c4b5

## Parent

`docs/decisions.md`, rows "`reserve` and each `extend` spawn a follower", "A follower started before a shortening `extend --to`", "Followers outlive `release`".

## What to build

The lease cache records the follower pid. `reserve`, `extend` and `tag` on adopt spawn a follower only when no recorded follower is alive.

After each sleep chunk the follower re-reads the lease's expiry and recomputes its wait, so an `extend --to` that shortens the clock holds within one 300 s chunk. The on-box clock file carries the exact time.

`release` sends TERM to the lease's recorded follower after checking that the pid still runs `vasty sweep --follow` for that lease. A destroy left `destroy_pending` falls to the next command's sweep, as today.

## Acceptance criteria

- [ ] `reserve` then `extend` on the same lease spawns one follower; a test counts spawn calls
- [ ] `extend` after the recorded pid has exited spawns a new follower
- [ ] A follower whose lease is shortened by `extend --to` mid-sleep wakes at the chunk boundary and sweeps at the new expiry; a fake-clock test asserts the destroy time
- [ ] `release` sends TERM to the recorded pid when its command line is `vasty sweep --follow LEASE`, and leaves a reused pid alone
- [ ] The cache entry for a lease holds `follower_pid`; `status --verbose` does not expose it

## Blocked by

None - can start immediately
