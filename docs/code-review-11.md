# Code review 11

Range: `58bb487687edcd3bb484417e897daf4c71c42596..da7c4438755bf0253e59193312e2338cfa02ad09`. Effort: medium. Line numbers are at `da7c443`. The review returned each finding without a confidence verdict; the verdict column records the review's own framing.

1. `tests/fakes.py:410` (`Harness.run`)
   - Problem: dropping the `finally` leaves `last_ctx` pointing at the inner context after a hook nests `Harness.run`. A test that combines a nesting hook, as in `tests/test_extend.py:129`, with a `last_ctx` read after the outer run reads the inner context's streams. No current test does this.
   - Proposed fix: restore the `finally`, or document the nesting caveat.
   - Verdict: latent trap. Review 10 finding 1 prescribed the deletion.

2. `tests/fakes.py:361` (`last_ctx` docstring)
   - Problem: the docstring says "the latest `run`" while the return path reads `holder[0]`, the outermost. The two records diverge under nesting with nothing saying which one tests use. Swarm report 9 records a draft that swapped the return path to `last_ctx` and failed 6 tests.
   - Proposed fix: add a one-line note on `holder` ("outermost context, for the return value") or name the nesting caveat in the `last_ctx` docstring.
   - Verdict: documentation.

3. `docs/swarm-report-10.md:13`
   - Problem: swarm report 9's deviation paragraph at `docs/swarm-report-9.md:31` still describes the deleted `finally`. Report 10 does not say so.
   - Proposed fix: add a cross-reference line to report 10's item 1 saying report 9's deviation text describes the removed code.
   - Verdict: documentation.
