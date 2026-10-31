# Review 2: loop 1 diff, `44760b8..2b03a1f`

Verdict: ready after fixes. The five review-1 fixes are applied as their Fix lines say and nothing beyond them; one stale test count in the README remains.

`uv run pytest` at HEAD `f44cc4e`: 1170 passed, 1 skipped. `uv run mypy`: no issues in 33 source files.

## Findings

### Nits

1. **The README test count is stale.**
   - Location: `README.md:301`, Status section.
   - Problem: the range adds `test_name_miss_extend_to_keeps_seconds` and `test_status_busy_null_while_unreachable`, so the count no longer matches the suite. The repo keeps this line current.
   - Evidence: "- 1168 unit tests pass against a fake provider and a fake box. `mypy --strict` is clean." `uv run pytest` at HEAD: 1170 passed, 1 skipped. Commits ddb642f, 7fc0a42, 2c012c5 and 8099123 each update the count. Swarm report 1 lists the line as an open item.
   - Fix: change `1168` to `1170` on that line.
   - Settled: exchange 1. Confirms code review finding 1.

## Disagreements

None.

## Dropped

Code review 2:

- Finding 1. Kept as finding 1 above.
- Finding 2, render `extend --to` with `config.format_duration`. Refuted. Review-1 finding 1 prescribes `extend --to {ttl}s`. `5430s` is exact and `parse_duration` accepts it. `config.format_duration` serves only `config` command values at `commands/config.py:50`, and every other human duration uses `timeutil.format_duration`. The change is an alternative rendering with no defect behind it.
- Finding 3, render the shortfall losslessly. Refuted. Issue 007 asks only that the tier two message add the shortfall and `extend --to`. `left` in the same message floors through the same helper. The `--to` value is the one a user runs, and review-1 made it exact.
- Finding 4, loop reports committed as tracked docs. Dropped as a code finding. The loop deletes its reports at the end.
- Finding 5, assert the full warning tail. Refuted. The `endswith("short; extend --to 5430s")` assertion fails on the old `format_duration(ttl)` rendering, which prints `1h30m`. A fixture default of 5430 s or more removes the `short;` clause and fails the test loudly. A full-tail assertion would pin the floored shortfall and the fixture value with no regression behind it.
- Finding 6, locate the `JOBS` column from the header. Refuted. `JOBS` is the last column in `lease_table` (`commands/status.py:230`) and `test_status_human_table` pins the header order. With `jobs_cell` returning `idle` for any non-true `busy`, the test fails with `assert 'idle' == '—'`. The pending test uses the same check.

Other findings:

- `docs/swarm-report-1.md:43` says `state.py` reports `unreachable` only for a box reached before (Astra). Withdrawn in exchange 1. `derive_state` does map `offline` and `unknown` to `unreachable` unconditionally, but the sentence explains a test whose fake row is `running`, where it holds. The report is a loop artifact the cleanup deletes.

Swarm report 1 claims checked: the four commit hashes and file lists, the test counts, the quoted README text, the `3600s`, `1800s` and `7200s` expectations, and the `jobs_cell` mutation claim all hold. Restoring `format_duration(ttl)` fails four tests, the new `ttl=5430` case among them.

## Run

- Angles: (a) each review-1 fix applied as written and each swarm report claim; (b) each code review 2 finding; (c) correctness, slop and style of the diff.
- Agents: 3 Sonnet, one per angle, each over the full range.
- Reviewer model: Astra.
- Exchanges: 1 of 3. Every dispute settled in exchange 1.
