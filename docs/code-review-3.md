# Code review 3

Range: `ffcb65a..df3d66f`. Effort: medium. The review did not verify its findings.

1. `src/rig/engine.py:200`
   - Problem: `_retry_destroy` treats a False return from `destroy_checked` as an accepted destroy. It bumps the attempt count, clears `last_provider_error` and sends nothing. A released lease whose `expires` moved after release gets no destroy and no warning, and the box keeps billing.
   - Fix: on False, re-read the row. When it is gone, move the lease to history. When `expires` moved, clear `destroy_pending`, keep the lease active and set `last_provider_error` to name `rig release`.
   - Verdict: correctness bug, unverified.

2. `src/rig/commands/reserve.py:414`
   - Problem: after a failed refresh, `wait_ready` passes `_give_up` the lease from the previous poll. A probe in the failed refresh may already have written `expires`, so `destroy_checked` sees a mismatch and leaves the new box running.
   - Fix: re-read the row in `_give_up` and destroy a box this call created whatever its `expires`.
   - Verdict: correctness bug, unverified.

3. `src/rig/engine.py:316`
   - Problem: the adoption script reruns over SSH on every probe while `watchdog` or `destroy_key` is missing, with no backoff. A box with no curl reruns it on every refresh and wait poll.
   - Fix: add a backoff capped at 60s, matching the destroy and key-attach retries.
   - Verdict: efficiency, unverified.

4. `src/rig/engine.py:302`
   - Problem: `_reruns_adoption` treats a new reserved box without `startup.started` as an adopted orphan. It runs adoption alongside onstart and sets `adopted` for good.
   - Fix: rerun adoption only for leases `tag` adopted. Leave reserved boxes to onstart.
   - Verdict: correctness bug, unverified.

5. `src/rig/engine.py:142`
   - Problem: `lease_from_row` and `_new_cached` start every unprobed lease with all three guard layers missing. JSON then reports `guard: partial` before any probe, while the `guard_partial` warning is suppressed.
   - Fix: report unprobed guard state distinctly, or keep `guard_missing` empty until a probe answers. Keep the field and the warning consistent.
   - Verdict: correctness bug, unverified.

6. `src/rig/remote.py:698`
   - Problem: under `-s`, `_rsync_path` rewrites `~` and `~/` and passes `~user/...` through unchanged. The remote rsync reads it as a literal path.
   - Fix: reject `~user` paths under `-s` with `invalid_arguments`, or drop `-s` for them.
   - Verdict: correctness bug, unverified.

7. `src/rig/remote.py:687`
   - Problem: `-s` follows the local rsync version only. A box with rsync older than 3.0 rejects it, and every sync fails.
   - Fix: check the remote rsync version during the probe, or pass `-s` only when both sides support it.
   - Verdict: correctness bug, unverified.

8. `src/rig/engine.py:335`
   - Problem: `engine._retry_key` imports `public_key` from `rig.commands.reserve`. The engine then depends on a command module.
   - Fix: move `public_key` to a shared keys module and import it from engine, reserve and tag.
   - Verdict: cleanup, unverified.

9. `src/rig/remote.py:545`
   - Problem: `remote.py` adds a second `_JOB_NUMBER` regex and `following_job_id`, duplicating `next_job_id` in `commands/_common.py`.
   - Fix: keep one definition in `rig.ids` and import it in both places.
   - Verdict: cleanup, unverified.

10. `src/rig/engine.py:343`
    - Problem: `_retry_key` sets `last_provider_error` on a failed attach and never clears it after a later success.
    - Fix: clear `last_provider_error` when the attach succeeds.
    - Verdict: correctness bug, unverified.
