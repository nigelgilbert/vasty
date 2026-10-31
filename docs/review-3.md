# Review 3

Target: the loop 2 diff `30a358f..f344651`. Code review at effort medium, then one Sol check. No swarm and no Astra ran.

**Verdict: ready after fixes.** Loop 2 met review 2 with no regressions. Three test and dead-code nits remain.

## Findings

### Nits

1. **`test_read_charges_failure_sets_none` is vacuous.** `tests/test_engine.py:832`. `refresh` fills `snap.charges` from a same-day cache after the 60 s freshness expires, so the except branch does real work, but the test never seeds charges. Fix: seed same-day charges older than 60 s, assert `snap.charges` is set, then run the failing read.
2. **The failed-read assertion in `test_read_balance_caches_balance_and_credit` is vacuous.** `tests/test_engine.py:853`. `refresh` never sets `snap.balance`. Fix: delete the trailing failure scenario.
3. **`snap.balance = None` in `read_balance` is dead.** `src/vasty/engine.py:762`. Both callers pass a fresh `refresh` snapshot whose balance is None. Fix: delete the assignment and keep the bare `return`.

## Disagreements

None.

## Findings dropped

- Code-review-3 findings 1, 5 and 8 reopen review-2 decisions: the cache shim, the `charges_start` docstring and the env test.
- Finding 4: the README promises the `spend_unavailable` warning on `status` only, and the paragraph above it covers cached unavailability.
- Finding 7: loop artifacts are deleted at the end of the run.
