# Code review 3

Range `30a358f..f344651`, effort medium. The review reported each finding without a verify pass, so every verdict is "reported".

1. `src/vasty/cache.py:157`. With the shim gone, an old cache decodes `charges` with `today` 0. `status --cached` reports `charges_today: 0.00` with no warning until the next live read. Fix: restore the shim. Verdict: reported.
2. `tests/test_engine.py:832`. `test_read_charges_failure_sets_none` passes when `read_charges` does nothing, because `refresh` on an empty cache leaves `snap.charges` None. Fix: seed same-day cached charges older than 60 s before the failing read. Verdict: reported.
3. `tests/test_engine.py:853`. The failed-read assertion in `test_read_balance_caches_balance_and_credit` is vacuous, because `refresh` always leaves `snap.balance` None. Fix: seed `snap.balance` first, or drop the assertion. Verdict: reported.
4. `README.md:231`. The paragraph says `status` warns `spend_unavailable` when the read failed. The warning also fires on `status --cached` with no read, and `release` gives no warning when its read fails. Fix: reword. Verdict: reported.
5. `src/vasty/engine.py:708`. The one-line `charges_start` docstring drops the reason for whole UTC days. Fix: restore the reason. Verdict: reported.
6. `src/vasty/engine.py:762`. `snap.balance = None` in the except branch of `read_balance` is dead, because `refresh` leaves `balance` None. Fix: use a bare `return`. Verdict: reported.
7. `docs/swarm-report-2.md:1`. Loop reports are committed to `docs/`. Fix: delete them. Verdict: reported.
8. `tests/test_config.py:421`. With the env test deleted, nothing checks that `VASTY_DAILY_BUDGET` is ignored. Fix: restore the test. Verdict: reported.
