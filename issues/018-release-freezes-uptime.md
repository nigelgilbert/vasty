# `release` freezes `uptime_s`; document `destroy_pending`

**Type**: AFK

**Status:** ✅ Done in b7b9d72

## Parent

`docs/stop-escalates-and-expiry-records.md`, sections 3 and 4.

## Command

```
vasty release t --json      # uptime_s 118
sleep 20
vasty status t --json       # uptime_s 141, state released
```

## Cause

While a destroy is pending and the provider still lists the instance, refresh skips the lease. `history_since` stays unset and `uptime_end` falls back to now.

## Fix

1. `mark_released` sets `history_since` to the release time.
2. `_to_history` sets `history_since` only when it is unset and keeps clearing the destroy bookkeeping on every confirmed absence.
3. `history_since` also starts the 24 h history window, so a released lease leaves history 24 h after the release call. State that in the engine docstring.
4. `cost` is the sum of Vast's charge rows and can rise after release as rows post. It stays as it is.
5. README `release` row: "`destroy_pending` is true from the destroy call until a refresh sees the instance gone from the provider listing."

## Tests

- [ ] `release` and a `status` 60 s later report the same `uptime_s` while the destroy is pending
- [ ] A refresh that sees the instance gone clears `destroy_pending` on a lease whose `history_since` is already set
- [ ] The README `release` row names what `destroy_pending` means

## Blocked by

None - can start immediately.
