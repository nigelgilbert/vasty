# `status` fields match the lease state

**Type**: AFK

**Status:** 🔲 Not started

## Parent

`docs/decisions.md`, rows "Released leases report `ttl_remaining_s`", "Single-lease `status` omits `log_tail` while `pending`", "`reserve --no-wait` returns null clock fields".

## What to build

History leases stop reporting live fields: `ttl_remaining_s` is null and `verbose.actual_status` is absent on `released`, `expired` and `gone` leases.

Pending leases carry no clock: `status` returns `expires_at` and `ttl_remaining_s` null while a lease is `pending`, matching `reserve --no-wait`. The clock starts at `running`.

Single-lease `status` returns `log_tail` in every state, `[]` when empty.

## Acceptance criteria

- [ ] `status LEASE --verbose` on a released lease returns `ttl_remaining_s: null` and no `actual_status` key
- [ ] The same holds for `expired` and `gone`
- [ ] `status LEASE` on a pending lease returns `expires_at: null` and `ttl_remaining_s: null`
- [ ] `status LEASE` on a pending lease and on a released lease each return a `log_tail` key
- [ ] README status result table marks the three fields with the states they apply to

## Blocked by

None - can start immediately
