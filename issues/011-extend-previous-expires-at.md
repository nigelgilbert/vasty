# `extend` returns the previous clock

**Type**: AFK

**Status:** 🔲 Not started

## Parent

`docs/decisions.md`, rows "An `extend` result alone cannot explain the clock move" and "The label's `ttl` stays at the reserve's value".

## What to build

The `extend` result gains `previous_expires_at` per lease. The label's `ttl` stays the reserve's ttl. README says both.

## Acceptance criteria

- [ ] `extend LEASE --by 20m` returns `previous_expires_at` equal to the clock before the call and `expires_at` 20 minutes later
- [ ] Bulk `extend --all` carries `previous_expires_at` on each entry
- [ ] The label `ttl` after `extend` equals the reserve ttl
- [ ] README `extend` result row lists `previous_expires_at` and the label note

## Blocked by

None - can start immediately
