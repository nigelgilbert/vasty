# Code review 7

Range: `305b32a..cb1ee1f`. Effort: medium. The review did not verify its findings.

1. `src/rig/commands/serve.py:195`
   - Problem: `serve` auto-reserves through `reserve_lease` and reports only `list(snap.swept)`. It drops the reserve-wait `swept` entries this range fixed for `run`.
   - Fix: merge `reserved.result.swept` with `merge_swept`, as `run` does.
   - Verdict: correctness bug, unverified.

2. `src/rig/commands/reserve.py:409`
   - Problem: `wait_ready` appends each refresh's `swept` with no dedup, so `rig reserve` and `serve` list a failing destroy retry once per poll.
   - Fix: use `merge_swept` inside `wait_ready`.
   - Verdict: correctness bug, unverified.

3. `src/rig/commands/_common.py:144`
   - Problem: `merge_swept` keys on `(lease, ok, error)`. A lease whose destroy fails on one refresh and succeeds on a later one appears twice, once failed and once ok.
   - Fix: keep the latest entry per lease, with an ok entry replacing a failed one.
   - Verdict: correctness bug, unverified.

4. `src/rig/commands/run.py:162`
   - Problem: `reserve_lease` already starts its `swept` from `snap.swept`, so merging `snap.swept` again is redundant. The tests pass only because `FakeReserve` differs from the real function.
   - Fix: use `merge_swept(reserved.result.swept)` and make `FakeReserve` match `reserve_lease`.
   - Verdict: cleanup, unverified.

5. `src/rig/engine.py:46`
   - Problem: the engine docstring says `run`'s `swept` covers the reserve wait and the release refresh. It omits the first refresh and the lost-attach refresh, which the run module docstring includes.
   - Fix: list every refresh `run` merges, matching the run docstring.
   - Verdict: doc, unverified.

6. `src/rig/onstart.py:281`
   - Problem: the adoption script writes the `adopted` marker first. A run that stops before the guard write leaves a marked box with no guard, and reruns may stop if `guard_missing` stays empty.
   - Fix: check that a probe with no guard file reports the missing layers in `guard_missing`, and add a test.
   - Verdict: correctness question, unverified.

7. `src/rig/commands/_common.py:134`
   - Problem: `merge_swept` also dedups within the first list, which the old code did not, and the docstring does not say so.
   - Fix: state the dedup in the docstring, or dedup only across lists.
   - Verdict: doc, unverified.
