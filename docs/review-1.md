# Review 1: loop 0 diff, `fe08718..d52871e`

Verdict: ready after fixes. Every acceptance criterion in issues 004 to 008 holds and the tests and types are green; one hint loses time on uncommon TTLs, and four doc and test nits remain.

`uv run pytest` at HEAD `356b9f4`: 1168 passed, 1 skipped. `uv run mypy`: no issues in 33 source files.

## Findings

### Gaps

1. **The tier two `extend --to` value floors the TTL.**
   - Location: `src/vasty/commands/reserve.py:238`, `idle_warning`.
   - Problem: `format_duration` floors to two units, so the `extend --to` value in the tier two message can fall short of the requested TTL. Issue 007 asks for the `extend --to` that covers it.
   - Evidence: `message += f", {format_duration(shortfall)} short; extend --to {format_duration(ttl)}"`. `format_duration(5430)` returns `1h30m` (5400 s). `format_duration(88200)` returns `1d`, 30 minutes short of `--ttl 1d30m`.
   - Fix: render the value in seconds: `extend --to {ttl}s`. `parse_duration` accepts it. Update the expectations at `tests/test_reserve.py:690` (`extend --to 3600s`), `tests/test_reserve.py:702` (`extend --to 1800s`) and `tests/test_integration.py:90` (`extend --to 7200s`). Add a case with `ttl=5430` that asserts `extend --to 5430s`.
   - Settled: exchange 1. Confirms code review finding 2.

### Nits

2. **The `reuse_candidates` docstring pre-empts an objection.**
   - Location: `src/vasty/state.py:193-194`.
   - Problem: the sentence answers an imagined question about the missing guard check, which the writing rules rule out.
   - Evidence: "Every managed lease has a guard of `full` or `partial`, so the guard needs no check."
   - Fix: delete the sentence. The docstring then runs "... no `hardware_mismatch` and time left. The shortfall is the seconds ...".
   - Settled: exchange 1. Confirms code review finding 8.

3. **The `uptime_s` README sentence restates the billing start and overstates it.**
   - Location: `README.md:149`, after the result shapes table.
   - Problem: "when Vast starts GPU billing" repeats `README.md:225`, and the first sample vasty sees can land after billing starts on a `--no-wait` box.
   - Evidence: "`uptime_s` counts from the first `running` sample, when Vast starts GPU billing, and is null before it." Line 225: "The clock starts when the container starts, which is when Vast starts charging GPU rent." `docs/uptime-counts-the-image-pull.md`: "a `--no-wait` box gets it at the next command that refreshes."
   - Fix: replace the sentence with "`uptime_s` counts from vasty's first `running` sample and is null before it."
   - Settled: exchange 1.

4. **The error table promises `log_tail` on every `serve_failed`.**
   - Location: `README.md:173`, error table, `serve_failed` row.
   - Problem: a failed tail read leaves `log_tail` out, as issue 006 prescribes, so the row overstates the details.
   - Evidence: "`details` carries `exit`, `lease` and `log_tail`". Issue 006: "A tail read that raises leaves `serve_failed` with `exit` and `lease` and no `log_tail`." `test_serve_failed_without_log_tail_when_read_fails` asserts that shape.
   - Fix: replace the clause with "`details` carries `exit` and `lease`, plus `log_tail` when the read succeeds".
   - Settled: exchange 1.

5. **No test covers the jobs cell of an unreachable lease with no jobs.**
   - Location: `tests/test_status.py`, beside `test_status_busy_null_while_pending` (line 131).
   - Problem: issue 005 says the jobs cell keeps its current text for `pending` and `unreachable`. Only the pending case is asserted. The one unreachable fixture lease, `l-8b11`, carries job `j-3`, so its cell shows the job whatever `busy` returns.
   - Evidence: `jobs_cell` in `src/vasty/commands/status.py` ends `return "idle" if view.busy is False else DASH`. `test_status_unreachable_jobs_unknown` (line 167) and `test_status_human_group_view` assert `j-3 unknown` for `l-8b11`.
   - Fix: add a test with an unreachable lease and no jobs that asserts `busy` is null in JSON and the table jobs cell is `—`.
   - Settled: exchange 1.

## Disagreements

None.

## Dropped

Code review 1:

- Finding 1, spurious `--cuda` in `flag_mismatch` when the row or `cuda_max_good` is absent. Refuted. Issue 007 has `hardware_mismatch` count unknown CUDA as a mismatch when a floor is set, and `flag_mismatch` keeps the flag-sourced keys from it. `--cuda` is a flag. The proposed skip adds a special case the issue does not ask for.
- Finding 2. Kept as finding 1 above.
- Finding 3, reset `running_at` when a lease leaves history. Refuted. Issue 004 sets it once and leaves it unchanged, and the uptime decision counts stopped intervals. A lease returns from history only when its instance row reappears, and `engine.py:646` would then restart the uptime of a box that ran through the gap.
- Finding 4, read the tail after `TERM`. Refuted. Issue 006 and serve decision 4 prescribe the read before `TERM`.
- Finding 5, route `group_jobs_cell` through `busy`. Refuted. The function is unchanged from `fe08718`, and issue 005 keeps the current cell for pending and unreachable leases.
- Finding 6, accept more GPUs for reuse. Refuted. Issue 007 and `docs/box-reuse-decisions.md` prescribe `gpus` equal. The README line is guidance for picking a lease by hand.
- Finding 7, a shared `vram_text` helper. Refuted. The duplicate is one expression in two different renderings, and a helper adds an export for it.
- Finding 8. Kept as finding 2 above.

Scope candidates from the swarm report, each prescribed or the smallest form that meets its issue:

- `reserve_lease(..., reuse_ports=)`. `docs/box-reuse-decisions.md` checks ports "when `serve` is the caller". The local `ports` in `reserve_lease` would apply the clause to `reserve` and `run` too.
- `_Plan.auto`. Issue 006 asks for two `vllm_missing` hints, one per path. A created flag cannot tell them apart on an auto-reserve name hit.
- `flag_mismatch` taking the instance row and reporting `--cuda`. Issue 007 gives `hardware_mismatch(lease, inst, settings, ports)` with the CUDA clause and has `flag_mismatch` call it.
- `exit: null` on the deadline `serve_failed`. Issue 006 gives the details `exit` and `lease` on both paths, and one helper builds them.
- `OSError` beside `VastyError` on the tail read. Issue 006 swallows a failed read. `status._log_tail` catches the same pair.
- The tier two message format. Issue 007: "a tier two message adds the shortfall and `extend --to`". The value is finding 1.
- `LeaseView.uptime_s` and the `UPTIME` column. Issue 004: a null `uptime_s` "in `release` and `status`", and "The table shows a dash."
- `state.gpu_matches`. `hardware_mismatch` lives in `state.py` per issue 007 and needs it. Leaving it in `reserve.py` would make `state` import `reserve`.
- Checked-off criteria boxes. `a938a02` is Nigel's own commit and sets the convention. The plan deletes the generated issues before merge.

Other findings:

- Group view without GPU and uptime columns (Astra). Withdrawn in exchange 1. `group_lines` showed no GPU column at `fe08718`, and the box-reuse doc has group rendering follow from `LeaseView`, which the JSON tests assert.
- Trim the docstrings of `busy`, `hardware_mismatch`, `flag_mismatch`, `idle_warning`, `_preflight` and `reserve_lease` (Astra). Withdrawn in exchange 1. Docstrings may run several sentences, and these state contracts the issues prescribe.
- Uncheck the 001 to 003 boxes (Astra). Withdrawn in exchange 1, as above.
- README serve sentence names `--host` and `--port` twice. Style preference. Setting and rejecting are two facts.
- `uptime_s` "includes any interval the box spent stopped" in the README. Issue 008 does not ask for it.
- Result shapes table omits `name` on `release` and `model` on `serve`. Both rows predate the range, and the issue 008 criterion checks that each named field exists, which holds.
- Human `status --group` lacks hardware fields. Same as the Astra group finding.
- VRAM floors to whole GB. The `2x12` format is prescribed and the floor is display only.
- `release` human output prints `?` for a null uptime. Issue 004 names the dash for the `status` table only.
- Catch `Exception` for a `UnicodeDecodeError` on the tail read. A fallback for a hypothetical log encoding.
- `redact_tail` drops trailing empty lines, and an empty key would misbehave. The key is always `vasty-` and 32 hex characters.
- `--bind-local` probe puts the key in `curl -H` argv. Pre-existing, outside issue 006, and declined in swarm report 0.
- `running_at` set on the first refresh on a new machine or after a cache rebuild. Follows issue 004's first-sample definition.
- Duplicated `idle` test helpers in `tests/test_reserve.py` and `tests/test_integration.py`. They return different shapes.
- `2×` in `reserve` human output against `2x12` in the `status` table. `reserve` output is outside issue 005.
- README test count. Accurate at 1168.
- `shlex.quote` on a key that needs no quoting. Correct quoting in a shell string builder.
- Swarm report wording on the Spend sentence. The clause it names did go.

Open items in swarm report 0:

| Item | Still open | Assessment |
|---|---|---|
| Commit trailer names Opus 5.5 | yes | Fine. Nigel's call. |
| `a938a02` ticks 001 to 003 from outside the run | yes | Fine. Nigel's commit. |
| 004: `LeaseView.uptime_s` and `UPTIME` are new | yes | Fine. Issue 004 prescribes both. |
| 004: `release` prints `?` for a null uptime | yes | Fine. Unspecified. |
| 005: `2x12 3060` cell, whole GB, real orphan count | yes | Fine. Prescribed format. |
| 005: `--group` jobs cell reads `idle` for pending and unreachable | yes | Fine. Pre-existing, and issue 005 keeps the current cell. |
| 006: deadline `exit: null` | yes | Fine. Prescribed details. |
| 006: `VastyError` or `OSError` on the tail read | yes | Fine. Matches `status`. |
| 006: `_Plan.auto` | yes | Fine. Picks the prescribed hint. |
| 007: `reuse_ports` keyword | yes | Fine. Serve-only port check. |
| 007: `--cuda` on a `--name` hit | yes | Fine. Prescribed by issue 007. |
| 007: `state.gpu_matches` | yes | Fine. Needed by `hardware_mismatch`. |
| 007: no explicit guard check | yes | Fine. `guard()` returns only `full` or `partial`. The docstring sentence is finding 2. |
| 007: tier two message format | yes | Format fine. The `--to` value is finding 1. |
| 008: `tag` row split | yes | Fine. Matches `TagResult` and `TagEntry`. |
| 008: Spend sentence drops its `max_price` clause | yes | Fine. The intro states it once. |

## Run

- Angles: code review 1 findings; acceptance criteria, tests, swarm report claims and open items; scope discipline; correctness and security of the changed source; slop and writing style.
- Agents: 5 Sonnet, one per angle, each over the full range.
- Reviewer model: Astra.
- Exchanges: 1 of 3. Every dispute settled in exchange 1.
