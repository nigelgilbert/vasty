# Review 4

Range: `e53eb3de74e2348bf8d4dda4f238611e604c5458..5b4da2d5b45b44dc5cee8e487de5066547a9320d`. Target: the `rig` diff in `src/rig` and `tests` that implements `docs/review-3.md`. References: `spec.md`, `docs/review-3.md`, `docs/review-1.md`, `docs/swarm-report-3.md`, `docs/code-review-4.md`. Line numbers are at `5b4da2d`.

**Verdict: ready after fixes.** The suite and mypy pass and all 17 review-3 items hold, but item 10's backoff stops adoption retries on a box the adoption script never reached, and two more gaps remain.

## Destroy re-read rule

A destroy compares the re-read row's `expires` against the last value this command read for the lease:

- the sweep and its retries: the row listed in this refresh;
- `release`: the cached label that `refresh` copied;
- the `reserve` give-up: the stored label, or a row read at give-up when the stored label has no `expires`.

A pending user release survives a skip and retries against the next refresh's listed value. The range implements this rule. Finding 6 writes it into the engine docstring.

## Findings

### Gaps

1. **A held adoption rerun clears the label's `watchdog` and `destroy_key`**
   - Location: `src/rig/engine.py:522-534` (`_apply_probe`), with `_reruns_adoption` at `:424-435`.
   - Problem: a probe inside the item 10 backoff takes the `else` branch, `missing = _layers(result.guard_missing)`. On a box without the guard file or `startup.started`, `parse_probe` (`src/rig/remote.py:333-343`) never reports `watchdog` or `destroy_key`. The held probe writes `miss` without them, resets `adopt_attempts` and `adopt_at`, and adoption retries stop with `guard: full`. Before this range every listed probe reran adoption and kept the label's layers.
   - Evidence: a scratch test with label `miss=[watchdog,destroy_key,clock_file]`, no box markers and a raising `adopt`. Refreshes at +0, +1, +10 and +10 seconds gave `(adopt_attempts, adopt_at, guard_missing, label.miss)` = `[(1, 1793235600, ['watchdog','destroy_key'], ['watchdog','destroy_key']), (0, None, [], []), (0, None, [], []), (0, None, [], [])]`.
   - Fix: change `elif probed.adopt_ran:` to `elif probed.adopt_ran or not (result.startup_started or result.guard_file):`. Add a test: an orphan label with `miss`, no box markers, a failing `adopt` and two refreshes inside the backoff. Assert that `label.miss` keeps `watchdog` and `destroy_key` and that `adopt_attempts` stays 1.
   - Settled: exchange 1.

2. **An adopted box that loses its cache entry gets no adoption rerun after a container restart**
   - Location: `src/rig/engine.py:435`, `src/rig/onstart.py:291-293` (`adopt_script`), `src/rig/remote.py:259` and `:356`. This is swarm report 3 open item 1.
   - Problem: `adopt_script` writes the guard file and `startup.started`. With the cache entry gone, `adopted` is False and the probe sees a `reserve` box. Spec §4.5 says "Later networked commands retry the missing steps" after "A container restart removes the watchdog from an adopted box", and §8.2 rebuilds a lost state file from labels. The fix stays inside the spec. The probe already reads box files beyond §3.2's list.
   - Evidence: a harness with `guard_file` and `startup_started` set, a stale `alive` and no cache entry gave `adopts []` over two refreshes. The control with `adopted=True` gave `adopts [1001]`.
   - Fix:
     - In `adopt_script`, add `: >"$R/adopted"` before `echo "missing=$g"`.
     - In the probe script, add `[ -e "$R/adopted" ] && echo adopted=1`.
     - Add `ProbeResult.adopted: bool = False` and set it in `parse_probe`.
     - In `_reruns_adoption`, return `lease.adopted or result.adopted or not (result.startup_started or result.guard_file)`.
     - In `_apply_probe`, set `lease.adopted = True` when `result.adopted`.
     - Add `adopted` to `FakeBox` and set it in `FakeBox.adopt`.
     - Add a test for a lost cache entry with a stale `alive` that expects one adopt call.
     - Boxes adopted before this change lack the marker and keep the current behaviour.
   - Settled: exchange 1.

3. **`extend` skips `check_writable` on the copy it reloads under the lock**
   - Location: `src/rig/commands/extend.py:130-141` (`_reload`). Code review 4 finding 4.
   - Problem: `_reload` rejects only history and `destroy_pending`. Another local process can save the lease as `unreachable`, `stopped` or `pending` with no SSH answer after this command's `check_writable` passed on the snapshot copy. Shortening writes the label before the clock (`apply`, `:191-193`), so the call restores the label and returns `provider_error`. Spec §4.2 says such a lease "returns `box_unreachable` and changes nothing".
   - Evidence: a harness rewrote the cache copy after `refresh` with the box down. `unreachable` with `--by 30m` gave `box_unreachable`. With `--to 10m` it gave `provider_error` "Clock write ... failed ... The label is back at ..." and `guard_missing ['clock_file']`. `pending` with `reachable_at None` behaved the same.
   - Fix: in `_reload`, raise `_expired(found)` when `found.destroy_pending`, then call `check_writable(found)` and return `found`. Add single and bulk tests for `unreachable`, `stopped` and `pending` with `reachable_at None`. Edit the cache copy after `refresh` and assert no label or clock write.
   - Settled: initial match. Severity set in exchange 1.

### Nits

4. **A failed retry for a user-released lease reports a future `expired_at`**
   - Location: `src/rig/engine.py:344`. This is swarm report 3 open item 2.
   - Problem: `iso(effective_expiry(label))` is in the future for a lease released early. Human `status` prints `SWEPT l-x  expired 2026-10-29T01:50:00Z  destroy failed (provider_error)` at 01:00.
   - Evidence: a harness released a lease expiring at 01:50 at about 01:00 and failed the retry. It got `('l-0000a001', '2026-10-29T01:50:00Z', False, 'provider_error')` with `now` 01:00:06Z.
   - Fix: return `SweptEntry(lease.lease, label.name, iso(min(now, effective_expiry(label))), False, error)`. A swept lease is past its clock, so its value does not change. Add a test that releases a lease with time left, fails the retry, and asserts `expired_at <= iso(now)`. The fix stays inside spec §4.4's `{lease, name, expired_at, ok, error}` entry.
   - Settled: exchange 1.

5. **`run` drops the `swept` entries of its release refresh**
   - Location: `src/rig/commands/run.py:69-83` (`release_quietly`), `:197-200` (`_attach`), `:267-270` (`_interrupted`).
   - Problem: `release_quietly` runs `engine.refresh`, which sweeps the account, and returns only a boolean. The attached result carries `swept=list(snap.swept)` from the earlier snapshot. A destroy made by the release refresh goes unreported. Spec §4.4: every networked command's "JSON carries `warnings` and `swept`".
   - Evidence: `snap = engine.refresh(ctx, probe=False)` inside `release_quietly`; `return not summary.already_absent`.
   - Fix: make `release_quietly` return `(released, swept)` with the entries of its refresh. In `_attach` and `_interrupted`, append them to the result's `swept`. The error-path callers in `run.py` and `serve.py:151` ignore the return and stay as they are.
   - Settled: exchange 1.

6. **The engine docstring does not state the destroy re-read baseline**
   - Location: `src/rig/engine.py:12-43` ("Destroy lifecycle").
   - Problem: review-3 and code review 4 disagreed on which `expires` a destroy compares against, and the docstring leaves it implicit.
   - Evidence: code review 4 findings 2 and 3 propose reversing review-3 items 1 and 2.
   - Fix: add "A destroy compares the re-read row's `expires` against the last value this command read for the lease: the listed row for the sweep and its retries, the cached label for `release`, and for the `reserve` give-up the stored label, or the row read at give-up when the stored label has none."
   - Settled: exchange 1.

7. **`SshBox.adopt` imports `rig.onstart` inline after the module imports it**
   - Location: `src/rig/remote.py:490`, with `:27`.
   - Problem: item 14 added `from rig.onstart import ROOT, WORKDIR` at module level, so the inline import saves nothing.
   - Evidence: `:27 from rig.onstart import ROOT, WORKDIR` and `:490 from rig.onstart import LAYERS, adopt_script`.
   - Fix: change `:27` to `from rig.onstart import LAYERS, ROOT, WORKDIR, adopt_script` and delete `:490`.
   - Settled: exchange 1.

8. **The release-on-error block appears three times in `run.py`**
   - Location: `src/rig/commands/run.py:148-151`, `:193-196`, `:263-266`. Code review 4 finding 8.
   - Problem: each block is `except BaseException:`, then `if <flag>: release_quietly(ctx, lease)`, then `raise`.
   - Evidence: the first block tests `created`, the other two test `release_on_exit`.
   - Fix: add `_release_on_error(ctx, lease, flag)`, a `contextlib.contextmanager` that calls `release_quietly` on `BaseException` when `flag` is set and re-raises. Wrap the three bodies with it and pass each block's flag. Leave `_lost` outside it. The review's caller `try/finally` releases on a dropped connection and is rejected.
   - Settled: exchange 1.

9. **The row-label lookup is written three times**
   - Location: `src/rig/commands/reserve.py:359-363` (`_row_expires`), `src/rig/engine.py:219-224` (`_reread_matches`), `src/rig/engine.py:545-548` (`_apply_probe`).
   - Problem: each calls `get_instance`, `labels.parse(row.label)` and `isinstance(parsed, Label)`. `_row_expires` is the new copy.
   - Evidence: `parsed = labels.parse(row.label) if row is not None else None` at `reserve.py:362` and `engine.py:546`.
   - Fix: add `engine.row_label(ctx, instance_id) -> Label | None` that returns None for a missing row or an unreadable label and lets provider errors raise. Use it in the three places. `_row_expires` becomes `label = engine.row_label(ctx, instance_id); return label.expires if label else None`. Keep `release.py:104`, which tells a missing row from an unreadable one.
   - Settled: exchange 1.

## Disagreements

None. Every dispute settled in exchange 1.

## Findings dropped

- **Code review 4 finding 1** (`guard_file` stops reruns after cache loss): `adopt_script` writes `startup.started` too (`onstart.py:291`), so the base condition already skipped that box. Dropping `guard_file` reverses review-3 item 9 and reruns adoption on `reserve` boxes without `CONTAINER_API_KEY`. Finding 2 covers the real limitation. Both reviewers refuted it.
- **Code review 4 finding 2** (`_retry_destroy` skip leaves the lease stuck): the skip lasts one refresh. A harness showed a swept lease with moved `expires` turns `running` on the next refresh, a vanished row moves to history, and a `released_here` lease sends its destroy against the newly listed value. Clearing `destroy_pending` drops a user release, which review-3 item 1 rejected. Both reviewers refuted it.
- **Code review 4 finding 3** (`_give_up` compares the row against itself): `_row_expires` and the `destroy_checked` re-read are separate reads, and the stored value wins once any refresh completes. The cache reload the review proposes carries an extend's new value, and the probe's value is lost on interrupt. The re-read rule above keeps review-3 item 2. Both reviewers refuted it.
- **Code review 4 finding 5** (cleanup exception replaces the original): Python chains the original as `__context__`, the box outcome is unchanged, and `release_quietly` reports its own `RigError`. Codex withdrew it in exchange 1.
- **Code review 4 finding 6** (`_unprobed_guard` marks a fully probed lease missing): a full probe leaves no `miss` on the label, so an empty `miss` cannot show that layers were observed. `lease_from_row` applies the same default, and review-1 item 31 and review-3 item 11 prescribe it. Both reviewers refuted it.
- **Code review 4 finding 7** (unreadable re-read leaves the cache entry active): the error names the label and the `rig release i-N --yes` fix. The next `status` shows the row as an orphan with `label_unreadable` and moves the entry to history. Both reviewers refuted it.
- **Code review 4 finding 9** (two cache loads under the extend lock): this costs one small JSON decode and changes no behaviour, and the fix widens the `locked_active` contract that review-3 item 15 set. Codex withdrew it in exchange 1.
- **Code review 4 finding 10** (three `get_instance` calls in `_give_up`): spec §6 requires the re-read after the value is taken, and the third read runs only on a skip. Both reviewers refuted it.
- **Persistent cache failure blocks the auto-release** (Codex): a cache that cannot save breaks every command, and the watchdog destroys the box at its clock. Review-3 item 5 scoped the fix to the release call. Codex withdrew it in exchange 1.
- **No diagnostic for a retry skipped by a moved `expires`** (Codex): the skip lasts one refresh, and review-3 item 1 prescribed it silent. Codex withdrew it in exchange 1.
- **Stale `last_provider_error` on a lease that turns active again** (swarm): review-3 kept the field as a record of the latest failure when it dropped code review 3 finding 10.
- **A vanished row on a skipped retry stays in that refresh's listing** (swarm): the next list call drops it, and the agent advised against the change.

## Run

- Commands: `.venv/bin/pytest -q` gave `1070 passed, 1 skipped in 24.54s`. `.venv/bin/mypy --strict` gave `Success: no issues found in 34 source files`.
- Destroy lifecycle: sweep and retry calls went out at 0, 5, 10, 20, 40, 60 and 60s with every destroy failing. Each failed retry reported `ok: false` in `swept`. A failed give-up printed a stderr line and left the lease active and swept at its clock. No path leaves a listed, billing box that every command skips. Finding 5 covers the one unreported sweep.
- Angles: code review 4 findings 1-5 with the destroy re-read rule; code review 4 findings 6-10; the destroy lifecycle and the swarm report open items; swarm report claims, acceptance and tests for review-3 items 1-17; correctness, security and slop in the changed `src`.
- Agents: 5 Sonnet.
- Reviewer model: astra.
- Exchanges: 1.
