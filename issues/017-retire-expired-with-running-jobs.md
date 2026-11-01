# Retire `expired_with_running_jobs`

**Type**: AFK

**Status:** ✅ Done in 768f292

## Parent

`docs/stop-escalates-and-expiry-records.md`, section 2.

## Command

```
vasty status --json
```

## Output

```json
{"code": "expired_with_running_jobs", "lease": "l-400d6072",
 "message": "expired with j-3 running", "fix": "vasty status l-400d6072"}
```

The lease belongs to another owner and expired hours ago. Its job entry reads `unknown`. Running the fix prints the warning again. No command clears it.

## Cause

Expiry freezes job durations and leaves live jobs `running` in the cache. `lease_warnings` fires on that for every expired lease, and untargeted `status` adds every history lease's copy.

## Fix

Delete the warning: its row in the fix table, the expired branch of `lease_warnings`, the untargeted history pass in `status`, and its entry in the README warning list. Records stay as they are. A job the clock cut shows `unknown` on an expired lease in targeted `status`, and an attached `run` already exits 2 when the clock kills its job.

## Tests

- [ ] Untargeted `status` with an expired lease holding a `running` job in the cache returns no warning for it
- [ ] Targeted `status` on that lease shows the job `unknown`
- [ ] `expired_with_running_jobs` appears nowhere in `src`, `tests` or the README

## Blocked by

None - can start immediately.
