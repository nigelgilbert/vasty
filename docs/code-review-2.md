# Code review 2: loop 1 diff, `44760b8..2b03a1f`

Inline `code-review` at effort medium. The review gave each finding without a confirmed or plausible verdict; each is listed as reported.

1. `README.md:301`. The Status section says 1168 unit tests; the suite is 1170 passed, 1 skipped after this range. Proposed fix: update the count. Verdict: reported.
2. `src/vasty/commands/reserve.py:238`. `extend --to {ttl}s` renders raw seconds while `vasty.config.format_duration` already renders losslessly: `5430` gives `1h30m30s`, `88200` gives `1d30m`, both accepted by `parse_duration`. `timeutil.format_duration` floors to two units. Proposed fix: render the `--to` value with `config.format_duration` and drop the `s` suffix; update the test expectations. Verdict: reported. Checked by the orchestrator: both helpers exist and behave as described.
3. `src/vasty/commands/reserve.py:238`. The shortfall in the same message still goes through the flooring `timeutil.format_duration`, so `40m short; extend --to 5430s` does not add up. Proposed fix: render the shortfall with the same lossless helper. Verdict: reported. Follows from 2.
4. `docs/swarm-report-1.md:1`. A loop report is committed as a tracked doc; the repo rule classes loop reports and review files as cruft to delete once their findings land. Verdict: reported. Note: the loop deletes them at the end, as `b1551ac` did; no code change.
5. `tests/test_reserve.py:695`. `test_name_miss_extend_to_keeps_seconds` asserts only the `endswith` suffix and depends silently on the fixture's default 3000 s left. Proposed fix: assert the full `..., 40m30s short; extend --to 1h30m30s` tail. Verdict: reported.
6. `tests/test_status.py:146`. The plain-table assertion checks the last whitespace token rather than the jobs column, copied from the pending test. Proposed fix: locate the `JOBS` column from the header. Verdict: reported.
