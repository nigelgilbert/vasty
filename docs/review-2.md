# Review 2

Target: the loop 1 diff `a88ce6c..e1b042a`, plus a slop pass over the branch diff `2afb912..e1b042a`. The lens is a tight API with one clear mental model. Each change below either deletes code or corrects what the README tells an agent.

**Verdict: ready after fixes.** Loop 1 met review 1. Five trims and one README correction remain.

## Findings

### Gaps

1. **README `cost` paragraph misstates null and exposes query mechanics**
   - Location: `README.md:231`.
   - Problem: the paragraph says `cost: null` means Vast has posted no row yet. A failed charges read also nulls it, and so does `status --cached` after 00:00 UTC. The window explanation describes the query rather than the field.
   - Fix: replace the paragraph with: "A lease's `cost` sums the Vast charge rows available for its instance. A box adopted with `tag`, or an orphan, can show partial history. `release` reports the same figure. `cost` is null when no charge row is available, and `status` warns `spend_unavailable` when the read failed. `price_per_hr` times `uptime_s` approximates it."
   - Source: code-review-2 finding 1, with Sol's README trim.

### Nits

2. **Delete the old-cache-shape shim**
   - Location: `src/vasty/cache.py:157-160` and `tests/test_cache.py:108`, `test_charges_without_today_load_as_absent`.
   - Problem: the branch drops pre-upgrade charges once per upgrade. That falls outside the acceptance criteria and adds a migration path to `decode`.
   - Fix: delete the `raw_charges` lines and the conditional block, and delete the test. Keep `Charges.today`'s default so old caches still load.
   - Source: Sol, slop pass. This reverts review-1 finding 5.

3. **Make `read_charges` and `read_balance` set the snapshot and return None**
   - Location: `src/vasty/engine.py:736` and `:760`.
   - Problem: each helper sets `snap.charges` or `snap.balance` and also returns the value. Production callers ignore the return, so one operation has two ways to be consumed.
   - Fix: annotate both as `-> None`, replace value returns with bare `return`, and drop the final return. Update the docstrings to "Set `snap.charges` to ..." and "Set `snap.balance` to ...". Change tests that use the return value to assert on `snap.charges` or `snap.balance`.
   - Source: Sol, slop pass.

4. **Cut the `charges_start` docstring to one sentence**
   - Location: `src/vasty/engine.py:708-713`.
   - Problem: the loop 1 rewrap split the summary over two lines, and the second paragraph repeats what the day floor does.
   - Fix: replace the docstring with `"""Return 00:00 UTC of the earlier of `now` and the oldest cached lease's `created`."""`.
   - Source: code-review-2 finding 9, with Sol's trim.

5. **Delete the removed-budget env test**
   - Location: `tests/test_config.py:424`, `test_removed_budget_key_in_env_is_ignored`.
   - Problem: issue 001 asks for `invalid_config` on the config key. The test pins behaviour for an env variable that no longer exists.
   - Fix: delete the test.
   - Source: Sol, slop pass.

## Disagreements

None.

## Findings dropped

- Code-review-2 finding 2, which moves the same-day check into `_cached_balance`. Dropped: it moves working code without fixing a defect.
- Finding 3, which drops the `Charges.today` default. Dropped: every constructor passes `today`, and with the shim gone the default keeps old caches loading.
- Finding 4, the generic decode fallback. Dropped: it adds defensive machinery, and finding 2 above deletes the shim instead.
- Finding 5, which updates `docs/budget-decisions.md`. Dropped: the file is a historical decision record.
- Finding 6, which deletes the loop reports. Handled at the end of the run.
- Finding 7, the midnight-crossing clock test. Dropped: it guards a hypothetical fixture change.
- Finding 8, the decode test fixture. Dropped: finding 2 above deletes the test.

## Run

Code review at effort medium, then one Sol check that settled code-review-2 and ran a slop pass over the branch. The orchestrator verified each Sol item against the code at `e1b042a`. No swarm and no Astra ran.
