# Swarm report 1

Work: findings 1 to 10 of `docs/review-1.md`.
Branch `refactor/live-run-followups`, base commit `a88ce6c`. Run without the validation pass.

## Grouping

Four Opus agents ran concurrently in worktrees from `a88ce6c`, one per file group:

- A: findings 1, 2, 3, 4 and 8, over `engine.py`, `status.py`, `README.md` and `tests/test_engine.py`.
- B: findings 6 and 7, over `models.py`, `provider.py`, `tests/fakes.py` and `tests/test_provider.py`.
- C: finding 5, over `cache.py` and `tests/test_cache.py`.
- D: findings 9 and 10, over `tests/test_status.py`, `extend.py` and `reserve.py`.

The groups share no file. Every commit was cherry-picked onto the branch in the order A, B, C, D with no conflict. Each agent passed on the first report, so no corrections went back.

## Per item

### 1. `status --cached` reports a stale `credit` as current

- Landed: `cached_snapshot` returns the cached balance only when `balance_at` falls on today's UTC day. Its docstring now says both figures come back only when read today in UTC. `test_cached_snapshot_keeps_billing_read_today_only` asserts `cached.balance is None` after 86 400 s. The new `test_cached_snapshot_keeps_balance_read_earlier_today` reads the balance, advances 6 hours, refreshes, and checks that `cached_snapshot` still returns it.
- Files: `src/vasty/engine.py`, `tests/test_engine.py`.
- Commit: `a2f9e0c`.
- Item note: issue 001 says "`CacheData` caches both with the same 60 s freshness as charges". The review says "The review's 60 s fix is dropped, since it would null the balance on almost every `--cached` call. The same-day rule replaces it." Live `status` keeps the 60 s rule. `--cached` now applies the same-day rule it already applied to charges.

### 2. The README calls the prepaid credit "balance"

- Landed: the spend section says "The account bound is the prepaid `credit`." The `stopped` row says "for example at $0 credit". No other README line calls the credit "balance".
- Files: `README.md`.
- Commit: `a2f9e0c`.

### 3. The README definition of `balance` is inferred

- Landed: "`balance` is the `balance` field of Vast's `GET /users/current`, passed through unchanged."
- Files: `README.md`.
- Commit: `a2f9e0c`.

### 4. The README and a docstring overstate `cost` for tagged boxes and orphans

- Landed: the README `cost` paragraph uses the fix text and keeps the `cost: null` sentences. The `charges_start` docstring names "the oldest cached lease's `created`, history included" and says "a lease `reserve` created reports its lifetime billing". Its summary line wraps onto two lines to stay under 100 characters.
- Files: `README.md`, `src/vasty/engine.py`.
- Commit: `a2f9e0c`.
- Item note: issue 001 says "The charges query starts at the earlier of today and the oldest active lease's `created`". The review's docstring text says "the oldest cached lease's `created`, history included". The code counts history leases, as swarm report 0 recorded. The docstring now states what the code does.

### 5. A pre-upgrade cache reports `charges_today` as 0

- Landed: `decode` clears `charges`, `charges_at` and `charges_start` when `charges` is a dict without `today`, and keeps the leases. `Charges.today` stays optional. `test_charges_without_today_load_as_absent` writes the `2afb912` shape, `covered_through` included, and checks the leases load, `rebuilt` is false, and all three charge fields are None.
- Files: `src/vasty/cache.py`, `tests/test_cache.py`.
- Commit: `6fd2306`.

### 6. `Instance.start_date` is dead

- Landed: the field, its parse in `normalize_instance`, the fake's value, `test_normalize_instance_reads_start_date` and the `start_date=None` argument are gone. `grep -rn start_date src tests` returns only the charges request parameter in `provider.py`.
- Files: `src/vasty/models.py`, `src/vasty/provider.py`, `tests/fakes.py`, `tests/test_provider.py`.
- Commit: `94c084d`.

### 7. `parse_charges` has an unused `start` parameter

- Landed: `parse_charges(rows, end)`. The provider, the fake and both tests pass two arguments. The docstring's `start` names the row field and stays.
- Files: `src/vasty/provider.py`, `tests/fakes.py`, `tests/test_provider.py`.
- Commit: `94c084d`.

### 8. Two billing docstrings are stale

- Landed: the `status` module docstring says "when the balance or charges are unavailable". The `Snapshot` docstring uses the fix text. README line 229 now uses the same "are unavailable" wording, since finding 1 nulls the totals on `--cached` with no failed read.
- Files: `src/vasty/commands/status.py`, `src/vasty/engine.py`, `README.md`.
- Commit: `a2f9e0c`.

### 9. `test_status_spend_unavailable` asserts `cost` vacuously

- Landed: `billed` is keyed by the id `add_lease` returns. The test asserts `cost is None` when charges fail and `cost == 1.0` when the balance fails. `status` emits money as a float.
- Files: `tests/test_status.py`.
- Commit: `bfdfa08`.

### 10. Formatting left by the deletions

- Landed: two blank lines before `class Change` in `extend.py`, and the `reserve_lease` docstring rewrapped with the wording unchanged. `uvx --offline ruff check --preview --select E3` passes on `extend.py`.
- Files: `src/vasty/commands/extend.py`, `src/vasty/commands/reserve.py`.
- Commit: `c988b08`.

### README test count

- Landed: the README says 1117 unit tests. Finding 6 removed three parametrized cases, and findings 1 and 5 added one test each.
- Commit: `ddb642f`.

## Tests

On `ddb642f`: `uv run pytest` 1117 passed, 1 skipped. `uv run mypy` reports no issues in 33 source files.

## Findings dropped

None. The review's own "Findings dropped" section stands as written.

## Open items

- `docs/budget-decisions.md` still describes `instance_start` in `src/vasty/budget.py` returning `start_date`. Both are gone. No issue covers that doc.
- The meaning of Vast's `balance` field is unconfirmed beyond a constant 0. Issue 009 lists no check on it.
- `reserve.py` and `extend.py` keep code lines over 99 characters that predate the diff. Finding 10 covered only the docstring.
