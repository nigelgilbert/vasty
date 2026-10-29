# Code review 4

Range: `e53eb3d..5b4da2d`. Effort: medium. The review did not verify its findings.

1. `src/rig/engine.py:538`
   - Problem: `result.guard_file` in the rerun condition stops adoption reruns for an adopted orphan whose cache entry was lost, since the adoption script also writes the guard file. A container restart then leaves `watchdog` and `destroy_key` missing indefinitely.
   - Fix: decide adoption reruns from the missing layers and the label's `miss`, without `guard_file`.
   - Verdict: correctness bug, unverified.

2. `src/rig/engine.py:485`
   - Problem: when `destroy_checked` returns False, `_retry_destroy` returns without touching `destroy_at` or `destroy_attempts`. Every refresh re-reads the row, the lease stays `destroy_pending` with no surfaced error, and a moved-expires row is never added to `replaced`.
   - Fix: on False, move a gone row to history. For a moved `expires`, clear `destroy_pending`, put the re-read row in `replaced` and set `last_provider_error`.
   - Verdict: correctness bug, unverified.

3. `src/rig/commands/reserve.py:295`
   - Problem: `_give_up` reads `expires` from the live row and passes it to `destroy_checked`, which compares the row against itself. A box another process just extended gets destroyed.
   - Fix: compare against the lease reloaded from the cache under the lock, or against the clock the probe wrote.
   - Verdict: correctness bug, unverified.

4. `src/rig/commands/extend.py:128`
   - Problem: `_reload` rejects only history and `destroy_pending` leases. A cache copy saved as `unreachable` or `stopped` skips `check_writable`, so the clock write fails with a raw `box_unreachable` or a partial write.
   - Fix: run `check_writable` on the reloaded copy.
   - Verdict: correctness bug, unverified.

5. `src/rig/commands/run.py:322`
   - Problem: `except BaseException: release_quietly(...); raise` loses the original exception when `release_quietly` raises an OSError or a second KeyboardInterrupt.
   - Fix: catch every exception inside the release attempt and re-raise the original.
   - Verdict: correctness bug, unverified.

6. `src/rig/engine.py:581`
   - Problem: `_keep_guard` runs for unprobed non-running rows, and `cached_snapshot` runs `_unprobed_guard` on history leases. A lease reserved elsewhere with an empty `miss` reports every guard layer missing.
   - Fix: take unprobed guard state from the label's `miss`. Skip history leases.
   - Verdict: correctness bug, unverified.

7. `src/rig/commands/release.py:218`
   - Problem: an unreadable re-read label makes `release` fail with a hint to run `rig release i-N --yes` and leaves the cache entry active.
   - Fix: keep the hint and mark the cached lease so `status` shows the unreadable label.
   - Verdict: correctness bug, unverified.

8. `src/rig/commands/run.py:320`
   - Problem: the release-on-exit block appears three times in `run.py`, each with a separate success-path release.
   - Fix: wrap the attach in one `try/finally` in the caller with a released flag.
   - Verdict: cleanup, unverified.

9. `src/rig/commands/extend.py:128`
   - Problem: extend loads `leases.json` twice under one lock, once in `_reload` and once in `engine.locked_active`.
   - Fix: load once and pass the leases to `locked_active`.
   - Verdict: efficiency, unverified.

10. `src/rig/commands/reserve.py:297`
    - Problem: the give-up path can call `get_instance` three times for one row.
    - Fix: read the row once and reuse it.
    - Verdict: efficiency, unverified.
