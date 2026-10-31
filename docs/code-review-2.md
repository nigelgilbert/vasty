# Code review 2

Range `a88ce6c..e1b042a`, effort medium. The review reported each finding without a verify pass, so every verdict is "reported".

1. `README.md:231`. The README says `cost: null` means Vast has posted no row yet. `cost` is also null when the charges read fails, and on `status --cached` after 00:00 UTC. Fix: say `cost` is null when no charge row is available, and point to the `spend_unavailable` warning. Verdict: reported.
2. `src/vasty/engine.py:700`. `cached_snapshot` applies the same-day check for the balance inline, while `_cached_charges` holds its own check. Fix: move the check into `_cached_balance(data, now)`. Verdict: reported.
3. `src/vasty/models.py:93`. `Charges.today` keeps its `Decimal("0")` default, the source of the pre-upgrade zero bug. Fix: drop the default. Verdict: reported.
4. `src/vasty/cache.py:157`. The old-shape fix is a one-off key check in `decode`. Fix: decode `charges` and `balance` with a `CorruptCache`-to-None fallback. Verdict: reported.
5. `docs/budget-decisions.md:7`. The doc describes `instance_start` and `start_date`, which are deleted. Fix: update the doc. Verdict: reported.
6. `docs/swarm-report-1.md:1`. Loop reports are committed to `docs/`, against the convention that loop artifacts are deleted. Fix: delete them. Verdict: reported.
7. `tests/test_engine.py:878`. `test_cached_snapshot_keeps_balance_read_earlier_today` passes because the fake clock starts at 01:00 UTC. A start after 18:00 UTC would cross midnight. Fix: derive the advance from `day_start`. Verdict: reported.
8. `tests/test_cache.py:111`. The old-shape decode test deletes the balance fields first, so it never checks that they survive. Fix: keep them in the fixture and assert them. Verdict: reported.
9. `src/vasty/engine.py:708`. The rewrap splits the `charges_start` docstring summary across two lines. Fix: fit the summary on one line. Verdict: reported.
