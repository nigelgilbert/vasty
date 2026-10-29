# Review 11

Range: `58bb487687edcd3bb484417e897daf4c71c42596..da7c4438755bf0253e59193312e2338cfa02ad09`. Target: the diff in `tests/fakes.py` that implements `docs/review-10.md`, plus `docs/swarm-report-10.md`. References: `docs/review-10.md`, `docs/swarm-report-10.md`, `docs/code-review-11.md`, `spec.md`, `docs/review-9.md`, `docs/swarm-report-9.md`, `docs/code-review-10.md`. Line numbers are at `da7c443`. The `src` and `tests` trees at `cec22e5` match it.

**Verdict: ready.** The diff matches review-10 finding 1 character for character, the suite and typecheck pass, and both reviewers refuted all 3 code review 11 findings.

## Billing impact

- No agreed finding leaves a box billing or misleads the user.

## Findings

No findings.

## Disagreements

None. Both reviewers returned no findings, so no dispute reached an exchange.

## Findings dropped

- **Code review 11 finding 1** (restore the `finally` or document the nesting caveat): review-10 finding 1 prescribed the deletion and Astra backed it. Restoring the `finally` reverses that. The only `last_ctx` readers are `tests/test_run.py:496-497`, `:509-510`, `:524-525` and `:536-537`, and none nests a run. The cited `tests/test_extend.py:129` is a sequential `h.run("status")`. The `h.run("reserve")` calls at `tests/test_reserve.py:468`, `:492` and `:522` are sequential calls inside `pytest.raises`. The only nesting hook is `run_after_refresh` (`tests/test_extend.py:322-335`), and its callers at lines 344, 365, 378, 391 and 500 do not read `last_ctx`. Both reviewers refuted it.
- **Code review 11 finding 2** (a note on `holder` or a nesting caveat in the `last_ctx` docstring): the docstring holds in every path. `make` sets `last_ctx` on each build, so after a nested run it holds the inner context, which is the latest one built. `make` runs before any command code, so an escaping exception leaves it set. `holder` is local to each call and supplies that call's returned streams (`tests/fakes.py:399`, `:413-414`). No rule or reference asks for the note. It is a style preference. Both reviewers refuted it.
- **Code review 11 finding 3** (cross-reference in swarm report 10 to swarm report 9's deviation paragraph): swarm reports record a finished run and the repo rules bar edits to them. Review 10 dropped a correction to the same paragraph on that ground and records why its rationale fails. Swarm report 10 item 1 states "The `try`/`finally` and its comment are gone." Both reviewers refuted it.

## Settled questions

- Commands: `.venv/bin/pytest -q` gave `1128 passed, 1 skipped in 34.02s`. `.venv/bin/mypy --strict` gave `Success: no issues found in 34 source files`. Both match the expected counts. No gap.
- Swarm report 10 claims: all hold at `da7c443`. `git diff --stat 58bb487..da7c443` shows `tests/fakes.py` (+2/-6) and `docs/swarm-report-10.md` only. The replacement line and the docstring match review-10 finding 1 exactly.
- Swarm report 10 open item: still open. `git diff 58bb487..da7c443 -- src` is empty, so `src/rig/onstart.py`, `_unmarked` (`engine.py:450`) and `_reruns_adoption` (`engine.py:455-466`) are unchanged. A box adopted before the marker that loses its cache entry reads as a `reserve` box. Review 5 deferred it. No finding.
- Code review 11 finding 1: contradicts review-10 finding 1. No current test reads `last_ctx` after a nesting hook. Dropped.
- Code review 11 finding 2: style preference with no rule behind it. Dropped.
- Code review 11 finding 3: asks for an edit to a finished swarm report. Dropped.

## Run

- Angles: code review 11 findings 1-3 with the finding 1, 2 and 3 questions; swarm report 10 claims, review-10 acceptance and the open item; correctness, coverage and slop in the changed lines.
- Agents: 3 Sonnet.
- Reviewer model: astra.
- Exchanges: 0. The independent Astra review returned no findings and refuted all 3 code review 11 findings, so no dispute remained.
