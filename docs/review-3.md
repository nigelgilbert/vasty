# Review 3

Range: `ffcb65a9592ec6331d0119e03307ef8e3bc3bc47..df3d66f3c9a55e5257c60d7267ebca985d2a5398`. Target: the `rig` diff in `src/rig` and `tests` that implements `docs/review-1.md`. References: `spec.md`, `docs/review-1.md`, `docs/swarm-report-2.md`, `docs/code-review-3.md`.

**Verdict: ready after fixes.** The suite and mypy pass and no blocker remains, but 8 gaps hide or skip a destroy, leave an auto-reserved box billing, or leave review-1 items 5 and 29 incomplete.

## Findings

### Gaps

1. **`_retry_destroy` records a skipped destroy as an accepted call**
   - Location: `src/rig/engine.py:312-317`. Code review 3 finding 1.
   - Problem: `destroy_checked` returns False when the row vanished or `expires` moved between the list and the re-read. `_retry_destroy` still calls `mark_destroy_sent(lease, now, None)`. That bumps `destroy_attempts`, resets `destroy_at` and clears an earlier `last_provider_error`, so the next real call waits one step longer and the last failure disappears.
   - Evidence: a harness run released a lease, moved `expires` between the list and the re-read, and refreshed. Result: `destroyed == []`, `destroy_pending True`, `destroy_attempts 2`, `last_provider_error None`. The destroy went out on the next refresh, 10s later.
   - Fix: inside the `try`, write `if not destroy_checked(ctx, inst.id, label.expires): return`. Keep `mark_destroy_sent(lease, now, error)` after the `try` for sent and failed calls. Add a test that moves `expires` between list and re-read and asserts attempts, `destroy_at` and `last_provider_error` are unchanged. The review's fix (clear `destroy_pending` and keep the lease active) drops a destroy the user asked for and is rejected.
   - Settled: initial match. Fix and severity set in exchange 1.

2. **`_give_up` skips the destroy after the first probe fills `expires`**
   - Location: `src/rig/commands/reserve.py:384`, reached from `wait_ready` at `:409-411`. Code review 3 finding 2.
   - Problem: a reserve label starts without `expires`. A refresh whose probe writes the clock value to the label and is then interrupted leaves `wait_ready` holding the old lease. `_give_up` passes `expires=None`, the re-read sees a value, and the box this call created keeps running until its clock.
   - Evidence: a harness that ran the real `_probe_all` and then raised `KeyboardInterrupt` ended with `destroyed []`, `instances [1001]` and the label `...;ttl=1800;expires=1793237400`.
   - Fix: in `_give_up`, when `lease.label.expires is None`, call `ctx.provider.get_instance(lease.instance_id)`, parse its label, and pass the parsed `expires` to `destroy_checked`. Keep the stored value when it is set. Add tests: probe publishes `expires` then refresh is interrupted, and the box is destroyed; `expires` changes after that re-read, and the destroy is skipped with the warning; a stored non-None `expires` that differs from the row still skips. The review's fix (destroy whatever the `expires`) breaks the spec §6 re-read rule and is rejected.
   - Settled: exchange 2.

3. **Failed destroy retries show only under `--verbose`**
   - Location: `src/rig/engine.py:305-317` (`_retry_destroy`) and `:332-336` (`_sweep`).
   - Problem: a `destroy_pending` lease is in a history state, so default `status` omits it and `burn_per_hr` and `live` exclude its row. `swept` shows `ok: false` only in the refresh that first sent the destroy. Later failed retries only set `last_provider_error`, which `views.py:150` prints under `--verbose`. Spec §6 item 2: "Anything it destroys is reported in `swept`."
   - Evidence: with the destroy failing on every call, the first `status` returned `swept: [{ok: false, error: "provider_error"}]`. A second `status` 6s later returned `"leases": []`, `"burn_per_hr": 0.0, "live": 0`, `"swept": []` and empty stderr.
   - Fix: make `_retry_destroy` return `SweptEntry(lease.lease, label.name, iso(effective_expiry(label)), False, code)` when a sent call fails, and None otherwise. Append the entry to `swept` in `_sweep`. Skipped and backoff-gated calls return None. Add a test that a failed retry on a second refresh appears in `swept`.
   - Settled: exchange 1.

4. **`extend` overwrites a release another local process made after `refresh`**
   - Location: `src/rig/commands/extend.py:252-255` (`_single`), `:305-308` (`_bulk`), `:174-175` (`apply`).
   - Problem: `_single` and `_bulk` pass `apply` the lease objects read before the lock. `apply` ends with `engine.store_lease(ctx, lease)`, which writes back an active lease over a cached `released` one and clears `released_here` and `destroy_pending`. If Vast keeps the row, no refresh retries the destroy until the new expiry. Spec §4.2: "A lease in history returns `lease_expired`."
   - Evidence: `leases=engine.locked_active(ctx, snap)` is passed to the budget check, then `apply(ctx, lease, expires)` runs on the pre-lock object, and `apply` stores it in `finally`.
   - Fix: under the lock, reload each target from `ctx.cache.load().leases`. Return `lease_expired` with no write for a target in history or with `destroy_pending`. Compute the new expiry and the budget `replace` map from the reloaded copies and pass those to `apply`. Add single and bulk tests that release the target between refresh and lock.
   - Settled: exchange 1.

5. **A second Ctrl-C or a failed save after the job exits skips the auto-release**
   - Location: `src/rig/commands/run.py:189-190` (`_attach`) and `:227-255` (`_interrupted`).
   - Problem: `_attach` calls `save_lease(... finish_job ...)` before `release_quietly`, so an exception from the save skips the release. `_interrupted` catches only `RigError` around the 10s wait, so a second Ctrl-C skips `release_quietly`. The auto-reserved box then bills until its clock. Spec §4.6: "On SIGINT, `run` forwards SIGINT to the remote job, waits up to 10s, then exits 130. An auto-reserved box is released."
   - Evidence: `save_lease(ctx, lease, lambda record: finish_job(record, job.id, code, now))` precedes `released = release_quietly(ctx, lease) if release_on_exit else False`. `_interrupted` has `except RigError as err:` around the signal and wait loop.
   - Fix: in both functions, wrap the post-exit save and the wait in `try`/`except BaseException`, call `release_quietly(ctx, lease)` when `release_on_exit`, and re-raise. Leave the dropped-connection path in `_lost` unchanged. Add tests with a raising `save_lease` and with a second `KeyboardInterrupt` from `ctx.sleep`, each asserting `provider.destroyed == [1001]`.
   - Settled: exchange 1.

6. **`~user` remote paths reach the remote shell unquoted**
   - Location: `src/rig/remote.py:702-716` (`_rsync_path`). Code review 3 finding 6. Review-1 item 29.
   - Problem: without `-s`, the head before the first `/` of a `~` path goes to the remote shell raw, so `~$(id)/x` runs a command on the box. With `-s`, `~user/x` is a literal relative path, so a pull fails and a push creates a directory named `~user`.
   - Evidence: `_rsync_path("~$(id)/foo", False)` returns `~$(id)/foo`. `_rsync_path("~root/x", True)` returns `~root/x`.
   - Fix: after the `~` and `~/` rewrite, raise `invalid_arguments` with message "Remote path {path} uses ~user." and hint "Use an absolute path or ~/." when `resolved` still starts with `~`, on both branches. Change the `~bob/a b` and `~bob` cases in `tests/test_remote.py` to expect the error. Delete the "~user/ prefix" sentence from the docstring. Dropping `-s` for these paths leaves the shell exposure and is rejected.
   - Settled: initial match. Severity set in exchange 1.

7. **Bash completion runs command substitutions from profile names**
   - Location: `src/rig/commands/completion.py:111` (`_profile_names`), called at `:322`. Review-1 item 5.
   - Problem: review-1 item 5 filtered cached lease, name and group values. Profile names still pass raw to `compgen -W`, which expands `$(...)`. A project `./rig.toml` in a cloned repo can name a profile `$(...)`.
   - Evidence: a scratch `rig.toml` with `[profiles."$(touch <scratch>/pwned)"]` made `rig completion --list profiles` print `$(touch <scratch>/pwned)`. `bash -c 'compgen -W "$1" -- ""' _ "$OUT"` created the file.
   - Fix: `return sorted(n for n in ctx.settings.profiles if ids.VALUE.fullmatch(n))`. Add a completion test with a hostile profile name.
   - Settled: exchange 1.

8. **No test covers a cached lease replacing its snapshot copy in `locked_active`**
   - Location: `src/rig/engine.py:663-678`, `tests/test_extend.py:322-383`, `tests/test_reserve.py:528`. Report item 3.
   - Problem: the report says tests cover "a second local reserve or extend landing between the refresh and the lock". Every race test injects a reserve, which adds a new lease. The rule that the cache copy replaces the snapshot copy of the same lease has no test.
   - Evidence: `reserve_after_refresh` is the only injector, and both extend race tests call it.
   - Fix: add a test that extends an existing lease from a second local process between refresh and lock. Assert the larger commitment replaces the snapshot's and changes the budget decision.
   - Settled: exchange 1.

### Nits

9. **A reserve box in the guard-file window counts as an adopted orphan**
   - Location: `src/rig/engine.py:395-399` (`_reruns_adoption`). Code review 3 finding 4.
   - Problem: `onstart` writes the guard file (`onstart.py:223`) just before `startup.started` (`:224`). A probe between the two sees `watchdog` or `destroy_key` missing with no `startup.started`, reruns the adoption script and sets `adopted` for good. The report's claim that a `reserve` lease never reruns adoption is too strong.
   - Evidence: `parse_probe` (`remote.py:329-341`) reports those layers only once `guard_file=1` or `startup_started`. A harness probe in that window gave `adopts [1001] adopted True`. A probe during the essentials install gave `([], False)`.
   - Fix: add `guard_file: bool = False` to `ProbeResult`, set from `values.get("guard_file") == "1"` in `parse_probe`. Change the last line of `_reruns_adoption` to `return lease.adopted or not (result.startup_started or result.guard_file)`. Add `guard_file` to `FakeBox`. Add a test for a reserve box in the window and keep the cache-loss recovery test. Update the engine module docstring. The review's fix (rerun only for `adopted` leases) breaks review-1 item 9's cache-loss recovery and is rejected.
   - Settled: initial match. Fix and severity set in exchange 1.

10. **The adoption rerun has no backoff**
    - Location: `src/rig/engine.py:402-417` (`_probe_one`). Code review 3 finding 3. Report "Open items".
    - Problem: an adopted lease that still lacks `watchdog` or `destroy_key` reruns the adoption script on every successful probe, inside the probe pool.
    - Evidence: five refreshes with no time passing gave five adopt calls.
    - Fix: add `adopt_attempts: int = 0` and `adopt_at: int | None = None` to `CachedLease`. Pass `now` to `_probe_one`. Run the rerun only when `adopt_at is None or now - adopt_at >= retry_delay(adopt_attempts)`. In `_apply_probe`, bump both when `adopt_ran` and reset them when no `ADOPT_LAYERS` remain missing. Keep `key_attach_at` separate, since `_apply_probe` resets it. Add a test of repeated probes with a layer still missing.
    - Settled: initial match.

11. **Leases cached before this change still read `guard: full` until a probe answers**
    - Location: `src/rig/engine.py:460` and `:559`, `src/rig/engine.py:585` (`cached_snapshot`). Report "Open items".
    - Problem: an entry with an empty `guard_missing` from an older cache keeps it through failed and skipped probes.
    - Evidence: `lease.guard_missing = _layers(lease.guard_missing + lease.label.miss)` keeps `[]` when the label has no `miss`. `guard` returns `("full", [])`.
    - Fix: when `reachable_at is None`, the label has no `miss` and the lease is not `adopted`, set `guard_missing` to all three `GUARD_LAYERS`. Apply it at `:460`, at `:559`, and to each lease in `cached_snapshot`. Add a test with a legacy entry.
    - Settled: exchange 1.

12. **`release` reports "its expiry moved" for an unreadable label**
    - Location: `src/rig/commands/release.py:101-107`.
    - Problem: `destroy_checked` also returns False when the re-read label is unreadable. The error then says the expiry moved, and its hint `rig release L` repeats the failure.
    - Evidence: after the label became `rig:v9;garbage`, `release l-0000a001` returned `provider_error` "Lease l-0000a001 changed while releasing: its expiry moved." `status` listed `i-1001` as an orphan with `label_unreadable`.
    - Fix: parse the re-read row's label. When it is not a `Label`, raise `provider_error` "Lease {lease}'s label is unreadable." with hint `rig release i-{instance_id} --yes`.
    - Settled: exchange 1.

13. **The exec timeout test does not pin the `TimeoutExpired` cause**
    - Location: `tests/test_remote.py:131-140`. Review-1 item 25.
    - Problem: `serve._install` maps a timeout by `__cause__`. The serve test sets the cause by hand, and the remote test checks only the exception type.
    - Evidence: `with pytest.raises(BoxUnreachableError): box.exec(TARGET, "true", timeout=3)`.
    - Fix: bind `as err` and add `assert isinstance(err.value.__cause__, subprocess.TimeoutExpired)`.
    - Settled: exchange 1.

14. **`SshBox` repeats the `onstart` paths**
    - Location: `src/rig/remote.py:379-380`. Review-1 item 27.
    - Problem: `root="/workspace/.rig"` and `workdir="/workspace"` repeat `onstart.ROOT` and `onstart.WORKDIR`.
    - Evidence: `onstart.py:31-32` defines both. `onstart` imports only `rig.errors`.
    - Fix: import `ROOT` and `WORKDIR` from `rig.onstart` and use them as the defaults.
    - Settled: exchange 1.

15. **`locked_active` takes the lock that `load` already takes**
    - Location: `src/rig/engine.py:666-672`.
    - Problem: `with ctx.cache.lock():` wraps only `ctx.cache.load()`, which takes the re-entrant lock itself.
    - Evidence: `cache.py:86-88`, `def load(self) -> CacheData: ... with self.lock():`.
    - Fix: write `cached = ctx.cache.load().leases`. Change the docstring sentence to "The caller holds the `leases.json` lock so a reserve, release or extend by another local process since `refresh` counts."
    - Settled: exchange 1.

16. **The engine imports `public_key` from a command module**
    - Location: `src/rig/engine.py:430`, `src/rig/commands/tag.py:241`, `src/rig/commands/reserve.py:277`. Code review 3 finding 8.
    - Problem: `engine` is the only non-command module that imports `rig.commands`, and the import sits inside `_retry_key` to dodge a cycle.
    - Evidence: `from rig.commands.reserve import public_key`.
    - Fix: add `src/rig/keys.py` with `public_key(ctx)`, importing `Context` under `TYPE_CHECKING`. Delete it from `reserve.py`. Import it at the top of `engine.py`, `reserve.py` and `tag.py` and drop both function-local imports.
    - Settled: initial match.

17. **The `j-N` regex is defined twice**
    - Location: `src/rig/remote.py:162` and `:179` (`following_job_id`), `src/rig/commands/_common.py:26` and `:67` (`next_job_id`). Code review 3 finding 9.
    - Problem: both modules define `_JOB_NUMBER = re.compile(r"j-([0-9]+)")` and parse the number on their own.
    - Evidence: `grep -rn _JOB_NUMBER src` returns both definitions.
    - Fix: add `JOB_NUMBER` and `job_number(job_id) -> int | None` to `src/rig/ids.py`. Call `job_number` from `following_job_id` and `next_job_id` and delete both regexes. Keep the name `following_job_id`, which `tests/fakes.py` imports.
    - Settled: initial match.

## Item notes

The three spec choices in `docs/swarm-report-2.md` "Spec conflicts" hold.

- Item 15: spec §4.6 releases an auto-reserved box on SIGINT and says "A dropped connection returns `box_unreachable`". `SshBox.attach_job` maps a dropped connection to None, and `_lost` keeps the box up. A blanket release on any attach error would kill a live job after a network blip. Finding 5 covers the two release paths that SIGINT handling still misses.
- Item 16: spec §4.10 lists the `config show` sources. `ctx.model` is set only in `serve.execute`, so `config show` never prints `model`. `test_config_show_never_reports_model_source` pins it.
- Item 31: spec §3.1 defines `full` by observed layers, so an unprobed lease reads `partial`. Spec §8.2 ties the warning to a guard that "could not be fully set", and §4.5 requires it after a failed adoption step, which leaves the lease `pending`. The item's "not `pending`" rule would drop that warning.

## Disagreements

None. Every dispute settled within two exchanges.

## Findings dropped

- **Code review 3 finding 5** (unprobed lease reports `partial` with no warning): review-1 item 31 prescribes it and spec §3.1 allows only `full` and `partial`. Both reviewers refuted it.
- **Code review 3 finding 7** (remote rsync older than 3.0 rejects `-s`): spec §5.1 ships rsync in the base image, and a custom image needs apt-get, whose rsync has been 3.x since 2008. Codex withdrew it in exchange 1.
- **Code review 3 finding 10** (`_retry_key` never clears `last_provider_error`): spec §4.4 names the field "the last provider error", a record of the latest failure. Codex refuted it and Opus agreed.
- **Adoption after restart and cache loss** (Codex): spec §4.5 says "A container restart removes the watchdog from an adopted box", the sweep enforces the clock, and a fix needs a label field spec §8.0 does not define. The report lists it as open. Codex withdrew it in exchange 1.
- **Docstring length in `engine`, `budget` and `config`** (Codex): the user's rules allow docstrings and header blocks of several sentences, and the cited text states behaviour and reasons. Codex withdrew it in exchange 1.
- **Report citations for items 15 and 31** (swarm): both choices hold, and an added citation changes no code.
- **`guard_partial` on a probed lease still booting** (swarm): unchanged from the base commit, and the agent proposed no fix.

## Run

- Commands: `.venv/bin/pytest -q` gave `1031 passed, 1 skipped in 30.21s`. `.venv/bin/mypy --strict` gave `Success: no issues found in 33 source files`.
- Destroy lifecycle: every listed `destroy_pending` or `released` lease reaches `_retry_destroy` on each refresh, and `release` resends for a listed history lease. Retries wait 5, 10, 20, 40, 60, 60s. Findings 1 to 5 hold the remaining paths.
- Angles: code review 3 findings 1-5; code review 3 findings 6-10; the destroy lifecycle (`destroy_pending`, `released_here`, the sweep, `_retry_destroy`, `release_lease`, `reserve._give_up`); swarm report claims, acceptance and tests for items 1-16 with the item 15 and 16 spec choices; the same for items 17-31 with the item 31 spec choice and the open items; correctness, security and slop in the changed `src`.
- Agents: 6 Sonnet.
- Reviewer model: astra.
- Exchanges: 2.
