# Review 1

Target: the diff for `2afb912..005e728` on `refactor/live-run-followups`, which implements issues 001 to 003. HEAD `d7d5b86` adds only `docs/code-review-1.md`.

**Verdict: ready after fixes.** Every acceptance criterion in issues 001 to 003 holds and has a test. Four gaps remain: three in how the README describes Vast's figures, and one in how `status --cached` reports a stale `credit`.

## Checks

- `uv run pytest`: 1118 passed, 1 skipped.
- `uv run mypy`: `Success: no issues found in 33 source files`.

Both match the implementer's report. Neither command failed.

## Findings

### Gaps

1. **`status --cached` reports a stale `credit` as current**
   - Location: `src/vasty/engine.py:699` in `cached_snapshot`, with `_cached_balance` at `src/vasty/engine.py:726`.
   - Problem: `status --cached` returns `balance` and `credit` of any age. It drops charges unless they were read on the same UTC day. The `cached_at` field does not show the balance's age, because `refresh` sets `data.cached_at = now` at `engine.py:659` on every networked command and never touches `balance_at`.
   - Evidence: `read_balance` at t0, then `refresh` 5 days later, then `cached_snapshot` gives `cached_at` equal to now with `Balance(balance=Decimal('0'), credit=Decimal('20'))` 5 days old. README.md:229 tells agents to read `credit` over `burn_per_hr` for runway. Issue 001 caches `balance` and `credit` "with the same 60 s freshness as charges". `tests/test_engine.py:870` asserts `cached.balance == snap.balance` after 86 400 s.
   - Fix: at `engine.py:699`, pass `balance=_cached_balance(data) if data.balance_at is not None and day_start(data.balance_at) == day_start(now) else None`. Change `tests/test_engine.py:870` to `assert cached.balance is None`. `status` already warns `spend_unavailable` on a null balance.
   - Settled in: exchange 1. This is code-review-1 finding 9.

2. **The README calls the prepaid credit "balance"**
   - Location: `README.md:220` and `README.md:250`.
   - Problem: README.md:224-225 define `credit` as the prepaid money and `balance` as a separate field. Two other lines still call the account bound "balance". An agent that reads `totals.balance` for the bound sees $0 on a healthy account.
   - Evidence: line 220 reads "The account bound is the prepaid balance." Line 250 reads "for example at $0 balance". `docs/live/setup-1-user.txt` and `docs/live/p6-04-user.txt` record `'balance': 0` beside a positive `credit`.
   - Fix: change line 220 to "The account bound is the prepaid `credit`." Change line 250 to "for example at $0 credit".
   - Settled in: exchange 1.

3. **The README definition of `balance` is inferred**
   - Location: `README.md:225`.
   - Problem: "`balance` is what the account owes Vast beyond its credit, billed to a saved card" claims debt and saved-card semantics. No recorded output shows them. Swarm report open item 1 flags it.
   - Evidence: `docs/live/setup-1-user.txt` records `'balance': 0, 'credit': 20.0`. `docs/live/p6-04-user.txt` records `'balance': 0, 'credit': 19.90616859492`. Both ledgers keep `balance` at 0.0000 while `credit` falls. Credit never reached 0, so the run never showed a non-zero `balance`.
   - Fix: replace the line with "- `balance` is the `balance` field of Vast's `GET /users/current`, passed through unchanged."
   - Settled in: initial match.

4. **The README and a docstring overstate `cost` for tagged boxes and orphans**
   - Location: `README.md:231` and the `charges_start` docstring at `src/vasty/engine.py:704-709`.
   - Problem: the README says `cost` sums the charge rows "since it started", and the docstring says `cost` "is its lifetime billing". The window starts at 00:00 UTC on the day of the earlier of today and the oldest cached lease's `created`. `tag` sets `created` to the adoption time, and orphans add nothing to the window. A box that billed before that day reports a partial sum. The window itself follows issue 001 and stays.
   - Evidence: `charges_start` returns `day_start(min([now, *(lease.label.created for lease in leases)]))`. `tag.adopt` builds `Label(..., created=now, ...)` at `src/vasty/commands/tag.py:200`.
   - Fix: change README.md:231 to "A lease's `cost` sums Vast's charge rows for its instance since 00:00 UTC on the day the oldest cached lease was created. A box adopted with `tag`, or an orphan, reports only the rows from that day on. `release` reports the same figure." In the docstring, change "the oldest lease's `created`" to "the oldest cached lease's `created`, history included". Change "so its `cost` is its lifetime billing" to "so a lease `reserve` created reports its lifetime billing".
   - Settled in: initial match. This keeps code-review-1 finding 2's "document the window" alternative.

### Nits

5. **A pre-upgrade cache reports `charges_today` as 0**
   - Location: `src/vasty/cache.py:161` in `decode`.
   - Problem: a cache written by `2afb912` code decodes its charges with `today=Decimal("0")`. It already carries `charges_start` and `charges_at`, so `_cached_charges` accepts it and `status` reports `charges_today: 0.00` with no warning. This lasts 60 s on live `status` and until the next 00:00 UTC on `status --cached`, once per upgrade.
   - Evidence: decoding the base commit's cache shape gives `Charges(per_instance={999: Decimal('1.00')}, today=Decimal('0'))`, and `read_charges` returns it with no provider call.
   - Fix: in `decode`, when `body["charges"]` is a dict without a `today` key, set `charges`, `charges_at` and `charges_start` to None and keep the leases. Leave `Charges.today` optional, since a required field raises `CorruptCache` and loses the leases. Add a `tests/test_cache.py` case for the old shape that loads with `charges is None` and `rebuilt` false.
   - Settled in: initial match. This is code-review-1 finding 3.

6. **`Instance.start_date` is dead**
   - Location: `src/vasty/models.py:75`, `src/vasty/provider.py:261`, `tests/fakes.py:142` and `tests/test_provider.py:236-247`.
   - Problem: the deleted `budget.instance_start` was the only reader of `Instance.start_date`. The field is still declared, parsed, faked and tested.
   - Evidence: `grep -rn "\.start_date" src tests` returns only `tests/test_provider.py:241`. The `"start_date": int(start)` at `provider.py:505` is a charges request parameter, which stays.
   - Fix: delete the field at `models.py:75`, the `start_date=` line at `provider.py:261`, the `start_date=` line at `fakes.py:142`, `test_normalize_instance_reads_start_date`, and the `start_date=None` argument at `test_provider.py:247`.
   - Settled in: initial match.

7. **`parse_charges` has an unused `start` parameter**
   - Location: `src/vasty/provider.py:265`.
   - Problem: `start` fed `covered_through`, which is gone. The body reads only `end`.
   - Evidence: `def parse_charges(rows: list[Any], start: int, end: int) -> Charges:` with `today_start = timeutil.day_start(int(end))` as the only time input.
   - Fix: change the signature to `parse_charges(rows: list[Any], end: int)`. Update the callers at `provider.py:525`, `tests/fakes.py:176` and `tests/test_provider.py:509` and `:515`.
   - Settled in: initial match.

8. **Two billing docstrings are stale**
   - Location: `src/vasty/commands/status.py:7-8` and the `Snapshot` docstring at `src/vasty/engine.py:127-129`.
   - Problem: the status docstring says `spend_unavailable` fires when a read fails. `status.py:94` warns whenever `snap.charges` or `snap.balance` is None, which includes `--cached` with no read. The `Snapshot` docstring says `balance` holds the cached billing after a refresh. `refresh` leaves `balance` None until `read_balance` runs.
   - Evidence: `status.py:94` reads `if snap.charges is None or snap.balance is None:`. `refresh` builds the snapshot with `charges=_cached_charges(...)` and no `balance` argument.
   - Fix: in `status.py`, change "when the balance or charges read fails" to "when the balance or charges are unavailable". In `engine.py`, replace the sentence with "`charges` holds the cached charges after `refresh`, and `balance` is None. `read_charges` and `read_balance` set them, and `cached_snapshot` sets both from the cache file."
   - Settled in: exchange 1.

9. **`test_status_spend_unavailable` asserts `cost` vacuously**
   - Location: `tests/test_status.py:149` and `:154`.
   - Problem: `billed` is keyed by instance 1, while `add_lease` creates instance 1001. `cost is None` holds whether or not the charges read failed.
   - Evidence: `harness.provider.billed = {1: Decimal("1.00")}`. The fake's `_ids` starts at 1001.
   - Fix: key `billed` by the instance id from `add_lease`. Assert `cost is None` in the `charges` case and `cost == 1.0` in the `balance` case.
   - Settled in: exchange 1.

10. **Formatting left by the deletions**
    - Location: `src/vasty/commands/extend.py:43` and `src/vasty/commands/reserve.py:71`.
    - Problem: removing `EXTEND_BUDGET_HINT` left one blank line before the `Change` class. The edited `reserve_lease` docstring has a 124-character line, the longest in the file.
    - Evidence: `uvx ruff check --preview --select E3` reports `Expected 2 blank lines, found 1` at `extend.py:43`. `awk 'length>99'` reports `reserve.py:71: 124`.
    - Fix: add a blank line before `extend.py:43`. Rewrap the `reserve_lease` docstring paragraph at `reserve.py:70-72`.
    - Settled in: initial match.

## Disagreements

None.

## Swarm report open items

- **Item 1, the README definition of `balance`.** Still open as a live-run question. The recorded output supports `credit` as the prepaid money that charges draw down. It shows nothing about `balance` beyond a constant 0. Finding 3 narrows the README to what is recorded. Issue 009 lists no check on `balance` or `credit`, so the live run will leave this unconfirmed unless the user adds one there.
- **Item 2, `reserve --cuda abc`.** Closed. In the test harness `reserve` and `serve` each make one `list_instances` call before `invalid_arguments`, and `run` makes none. The report's claim that `serve` makes no call is wrong. In production `Context.provider` resolves settings before it builds `VastProvider`, so no live call happens on any of the three. `reserve --vram abc` behaves the same at `2afb912`, so the order predates the diff. Issue 002 asks only for `invalid_arguments`, which all three raise.

## Findings dropped

Code review 1:

1. **Auto-reserve `serve` boots without a vLLM image.** Refuted. Issue 003 specifies reserving on `defaults.image`, finding no `vllm`, releasing the box and reporting `vllm_missing`. Serve decision 3 accepts that boot, and the second Astra review declines refusing before boot. `test_bare_serve_reserves_default_image_and_releases_without_vllm` covers the path.
2. **`charges_start` uses `label.created`.** The code fix is refuted. Issue 001 and budget decision 3 set the window from the oldest lease's `created`. The "document the window" alternative is kept as finding 4.
3. **Old cached charges decode with `today` 0.** Kept as finding 5.
4. **`daily_budget` and `[models]` fail with `invalid_config`.** Refuted. Issues 001 and 003 specify `invalid_config` naming the key or table. The second Astra review in `docs/serve-decisions.md` declines migration errors beyond it.
5. **`parse_charges` drops a row that crosses 00:00 UTC.** Refuted. Vast's charge rows are daily buckets: the SDK filters charges on the `day` column, and serve decision 2 calls the `gpu` item "a daily bucket". No recorded row crosses midnight. Assigning by overlap or by `end` would change `charges_today` from Vast's billed total, which issue 001 requires unchanged.
6. **The charges window reaches back to `created` 0.** Refuted. The window is prescribed. A `created` of 0 comes only from a hand-edited label, and `_sweep` destroys that lease on the next refresh: user decision, batteries included. Paging is bounded by charge rows and `PAGE_LIMIT`. A clamp would cut lifetime billing for long-TTL leases.
7. **`status` reads charges and balance under two locks.** Refuted. Each read reloads the cache under its own lock, so no update is lost. One lock across both network calls would hold it longer for other vasty processes.
8. **`check_extra` misses abbreviated owned flags.** Refuted. Issue 003 prescribes rejecting the exact `--flag value` and `--flag=value` forms, which landed with tests. The trigger is the user abbreviating a flag `serve` owns in their own command: user decision, batteries included. An "unambiguous prefix" rule needs vLLM's full flag list, and a naive prefix match rejects real flags such as `--api-server-count`. Astra raised this and withdrew it in exchange 1.
9. **`cached_snapshot` returns a balance of any age.** Kept as finding 1. The review's 60 s fix is dropped, since it would null the balance on almost every `--cached` call. The same-day rule replaces it.

Other findings:

- `read_charges` and `read_balance` return values that only tests read. Style preference with no rule behind it.
- `status._dollars` duplicates `release._cost`. The placeholders differ on purpose ("unknown" and "?").
- `PROFILE_KEYS = dict(DEFAULT_KEYS)` is now a copy. The name keeps the profile key set explicit at its callers.
- `charges_start` counts history leases where issue 001 says active leases. Swarm report 0 records this as a judgment call, and finding 4 updates the docstring to say so.
- "With no saved card, Vast stops instances at $0" has no recorded evidence. The claim predates the diff.
- `parse_charges` counts a row with neither `start` nor `end` toward today. No recorded row lacks both times.
- Swarm report 0 says "ten other test files" where commit `85633ca` touched thirteen, and its open item 2 misstates `serve`. The report is a loop artifact due for deletion, so the settlement above records the correction.
- Astra's README-reading acceptance tests. Withdrawn in exchange 1. The issues phrase those criteria as greps and README checks the reviewer runs.
- Astra's swarm report style edits. Withdrawn in exchange 1 for the loop-artifact reason.

## Run

- Angles: billing correctness with code-review-1 findings 2, 3, 5, 6, 7 and 9; serve, config and CLI correctness with findings 1, 4 and 8; issue 001 conformance with swarm open item 1; issues 002 and 003 conformance with swarm open item 2; slop and doc style over the diff.
- Agents: 5 Sonnet agents, one per angle.
- Reviewer model: GPT-6 Astra through the `codex` skill.
- Exchanges: 1 of a cap of 2. Every dispute settled in exchange 1.
