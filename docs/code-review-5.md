# Code review 5

Range: `715a592..a94be3e`. Effort: medium. The review did not verify its findings.

1. `src/rig/onstart.py:294`
   - Problem: the adoption script writes the `adopted` marker last. A run that dies after the guard file and `startup.started` leaves a box that looks reserved, and a lost cache entry then stops adoption reruns.
   - Fix: write the marker at the top of the script, before `_GUARD_WRITE`.
   - Verdict: correctness bug, unverified.

2. `src/rig/engine.py:370`
   - Problem: a failed retry reports `expired_at` as `min(now, effective_expiry)`, which changes on every retry. The `entry not in swept` dedup in `run` then lists one lease twice, and `_sweep` still uses plain `effective_expiry`.
   - Fix: use one stable `expired_at` for both paths, such as the time of the first destroy.
   - Verdict: correctness bug, unverified.

3. `src/rig/commands/run.py:165`
   - Problem: the attached and detached results drop the `swept` entries from `reserve_lease`'s wait refreshes.
   - Fix: merge `reserved.result.swept` into the result's `swept`.
   - Verdict: correctness bug, unverified.

4. `src/rig/commands/extend.py:141`
   - Problem: when `leases.json` lacks the lease, `_reload` falls back to the stale snapshot copy and extends a box another process released.
   - Fix: return `lease_expired` when the cache lacks the lease under the lock.
   - Verdict: correctness bug, unverified.

5. `src/rig/engine.py:333`
   - Problem: the new `elif` copies label `miss` adoption layers into `guard_missing` for any box without the guard file and `startup.started`, adopted or not. A stale `miss` keeps `adopt_attempts` from resetting.
   - Fix: limit the branch to leases with the `adopted` marker or `adopted` set.
   - Verdict: correctness bug, unverified.

6. `src/rig/commands/run.py:107`
   - Problem: `release_quietly` now returns a tuple. A future `if release_quietly(...)` caller would always see it as truthy.
   - Fix: return a small dataclass, or expose `swept` through a separate helper.
   - Verdict: cleanup, unverified.

7. `src/rig/commands/run.py:105`
   - Problem: `_released_swept` duplicates the swept-merge expression in `_lost`.
   - Fix: add one `merge_swept(a, b)` helper and use it in both.
   - Verdict: cleanup, unverified.

8. `src/rig/commands/extend.py:272`
   - Problem: `_single` runs `check_writable` before `_reload`, which runs it again.
   - Fix: drop the pre-lock check.
   - Verdict: cleanup, unverified.

9. `src/rig/commands/reserve.py:362`
   - Problem: `_row_expires` tests a Label by truthiness.
   - Fix: use `label.expires if label is not None else None`.
   - Verdict: cleanup, unverified.
