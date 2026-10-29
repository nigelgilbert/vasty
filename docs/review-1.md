# Review 1

Range: `6290161..d765775`. Target: the `rig` diff in `src/rig` and `tests`. References: `spec.md`, `docs/swarm-report-0.md`, `docs/code-review-1.md`.

**Verdict: ready after fixes.** The venv suite passes, and 13 gaps remain, three of which can leave a box billing unnoticed (items 2, 4 and 10).

## Findings

### Gaps

1. **uv is missing on the host**
   - Location: host environment, against `docs/swarm-report-0.md` "Commands".
   - Problem: the project's two check commands fail before they start.
   - Evidence: `uv run pytest -q` and `uv run mypy --strict` from the repo root each print `(eval):1: command not found: uv`. `.venv/bin/pytest -q` gives `898 passed, 1 skipped`. `.venv/bin/mypy --strict` gives `Success: no issues found in 33 source files`.
   - Fix: install uv (`brew install uv`), run `uv sync`, then rerun both commands.
   - Settled: exchange 2.

2. **`_give_up` marks a box released when the destroy was skipped**
   - Location: `src/rig/commands/reserve.py:385-388`.
   - Problem: `destroy_checked` returns False when the row's `expires` moved, and `_give_up` sets `released_here` and `destroy_pending` anyway. The sweep (`engine.py:245`), the probe (`engine.py:416`) and `release_lease` (`release.py:91`) then skip a box that still bills.
   - Evidence: `engine.destroy_checked(ctx, lease.instance_id, lease.label.expires)` with the result discarded, followed by `lease.released_here = True; lease.destroy_pending = True`.
   - Fix: set `released_here`, `destroy_pending` and `state = "released"` only when `destroy_checked` returns True or `ctx.provider.get_instance(lease.instance_id)` returns None. Otherwise keep the lease active and warn `rig: {lease} changed before it could be destroyed. Run rig release {lease}.` Return the original `err` in every case. Add the `rig release` fix to the `except RigError` warning too.
   - Settled: initial match. Severity set in exchange 1.

3. **Budget check reads a snapshot taken before the lock**
   - Location: `src/rig/commands/reserve.py:104-106`, `src/rig/commands/extend.py:245` (`_single`) and `:291` (`_bulk`).
   - Problem: `projection_for` sums `snap.active()` from the `refresh` that ran before `ctx.cache.lock()`. Two local processes can both pass and together exceed `daily_budget`. Spec §5.2 holds the lock from the budget check through the provider call.
   - Evidence: `engine.budget_check(ctx, snap, budget.cost(offer.dph_total, ttl), RESERVE_BUDGET_HINT)` inside `with ctx.cache.lock():`, with `snap` passed in from `execute`.
   - Fix: under the lock, build the active pool from `ctx.cache.load().leases` filtered by `state not in HISTORY_STATES` and pass it to `projection_for` through a `leases` argument. Keep `snap.instances` for the spend estimate. Apply it at all three sites.
   - Settled: initial match. Severity set in exchange 1.

4. **`wait_ready` leaks the box on a refresh error or Ctrl-C**
   - Location: `src/rig/commands/reserve.py:406` and `:445`. Callers `run.py:127` and `serve.py:144` call `reserve_lease` above their `try`.
   - Problem: a `RigError` from `engine.refresh` or a `KeyboardInterrupt` during `ctx.sleep` leaves the created box running until its watchdog fires. Spec §4.6 releases an auto-reserved box on SIGINT.
   - Evidence: a harness run with `start_status="loading"` and a sleep that raises `KeyboardInterrupt` ended with `instances alive: [1001] destroyed: []`.
   - Fix: wrap only `snap = engine.refresh(ctx)` and `ctx.sleep(WAIT_POLL_S)` in `except (RigError, KeyboardInterrupt) as exc:`. Call `_give_up` for a created box and re-raise `exc`. Leave the `_give_up` raise sites outside the handler so the destroy runs once.
   - Settled: initial match. Severity set in exchange 1.

5. **Bash completion runs command substitutions from lease names**
   - Location: `src/rig/labels.py:41-80` (`parse`), `src/rig/commands/completion.py:88-100` (`cached_names`) and `:132`, `:149-150`.
   - Problem: `labels.parse` checks keys and leaves values unchecked. A label on the shared account can carry `$(...)` in `name`, `group` or `owner`. The bash script passes cached names to `compgen -W`, which expands them on the user's machine.
   - Evidence: `labels.parse('rig:v1;lease=l-aa;owner=a;name=x y$(id);created=1;ttl=5')` returns a `Label` with `name='x y$(id)'`. `bash -c 'compgen -W "$(printf "ok\n\$(echo PWNED >&2)\n")" -- ""'` prints `PWNED`.
   - Fix: in `labels.parse`, return `Unreadable` when `lease` fails `ids.LEASE_ID` or when `owner`, or a non-empty `name` or `group`, fails `ids.VALUE`. In `cached_names`, keep only values that fullmatch those patterns. Add a completion test with a hostile name.
   - Settled: initial match. Severity set in exchange 1.

6. **An oversized epoch in a label crashes `status`**
   - Location: `src/rig/labels.py:65-79`, `src/rig/timeutil.py:106`.
   - Problem: `parse` accepts any non-negative integer for `created`, `ttl` and `expires`. `iso` then raises on one shared-account label.
   - Evidence: `labels.parse('rig:v1;lease=l-0000aaaa;owner=a;created=1;ttl=5;expires=999999999999999999999')` returns a `Label`. `timeutil.iso(p.expires)` raises `OverflowError: timestamp out of range for platform time_t`.
   - Fix: in `parse`, return `Unreadable` when `created`, `expires` or `created + ttl` exceeds `253402300799`.
   - Settled: exchange 1.

7. **`sync push --delete` deletes rig's state on the box**
   - Location: `src/rig/remote.py:609-622` (`rsync_argv`), called from `src/rig/commands/sync.py:28`.
   - Problem: `rig sync L push --delete ./ /workspace/` removes `/workspace/.rig`. That drops the clock file, the destroy key in `env`, job records, the vLLM venv and, on custom images, `watchdog.sh`.
   - Evidence: argv is `rsync -az --partial --delete --exclude=.git --exclude=__pycache__ --exclude=.venv --exclude=node_modules ...`. A local rsync run with that argv removed `dst/.rig/clock`.
   - Fix: when `delete` is true, append `--filter=P .rig` before `-e`.
   - Settled: exchange 1.

8. **`tag` raises `name_conflict` for a name it does not change**
   - Location: `src/rig/commands/tag.py:150-151` (`update`) and `:79-94` (`check_names`).
   - Problem: every target goes into `planned` with its current name. When two leases of one owner share a name, which §8.2 allows across machines, `tag l-a --set-group g` fails.
   - Evidence: with two `claude` leases named `ft`, `tag l-0000a001 --set-group g` exits 1 with `name_conflict: Name 'ft' is already used by l-0000a002`.
   - Fix: pass `check_names` only the leases whose `(name, owner)` changes. Keep unchanged leases in `claimed`.
   - Settled: exchange 1.

9. **Adoption never retries a failed key attach, and cache loss stops retries**
   - Location: `src/rig/engine.py:302-316` (`_probe_one`), `src/rig/commands/tag.py:237-251` (`_guard_steps`).
   - Problem: a failed `attach_ssh_key` blocks SSH, the probe fails, and `_probe_one` returns before any retry. The retry also keys off the cache-only `adopted` flag. Spec §4.5: "Later networked commands retry the missing steps."
   - Evidence: `except (RigError, OSError): return _Probed(None)` precedes `if lease.adopted and _layers(result.guard_missing):`.
   - Fix: select adoption retries by label `miss` containing `watchdog` or `destroy_key`. When the probe of such a lease fails, retry `attach_ssh_key`. Run `ctx.box.adopt` on the next successful probe. Add tests for attach failure and for retry after cache loss.
   - Settled: exchange 1.

10. **`release` reports `already_absent` after a failed sweep destroy**
    - Location: `src/rig/commands/release.py:91`, `src/rig/engine.py:264-271`.
    - Problem: a failed sweep destroy sets `state = "expired"` and keeps the row. `release_lease` then returns `already_absent` with exit 0 for a box that still bills. Spec §4.3: "A failed destroy returns `provider_error`."
    - Evidence: `if lease.state in HISTORY_STATES or lease.destroy_pending: return summarize(..., already_absent=True)`.
    - Fix: when the lease is in history and `snap.instance(lease.instance_id)` is still listed, run `destroy_checked` and raise `provider_error` on failure.
    - Settled: exchange 1.

11. **Custom images can lack `python3-venv`**
    - Location: `src/rig/onstart.py:39-46` (`ESSENTIALS`), `src/rig/commands/serve.py:89`.
    - Problem: the essentials check covers `python3` only. `serve` runs `python3 -m venv`, which fails on Debian and Ubuntu images without `python3-venv`.
    - Evidence: `("python3", "python3")` is the only Python entry. `else python3 -m venv "$V" && "$V/bin/pip" install ...`.
    - Fix: in the essentials installer, run `python3 -c 'import ensurepip, venv'` and `apt-get install -y python3-venv` when it fails. Add an installer test for that branch.
    - Settled: exchange 1.

12. **`auth_missing` has no test**
    - Location: `src/rig/context.py:97`.
    - Problem: the §7 code has no test, because `Harness` always supplies a `provider_factory`.
    - Evidence: `grep -rn auth_missing tests` returns nothing.
    - Fix: add a test to `tests/test_cli.py` that builds a `Context` with `provider_factory=None` and no `VAST_API_KEY`, runs `status`, and asserts exit 1, `error == "auth_missing"` and `VAST_API_KEY` in the hint. Add a case with `RIG_API_KEY_ENV=MY_KEY`.
    - Settled: exchange 1.

13. **The missing `.pub` branch of `reserve` has no test**
    - Location: `src/rig/commands/reserve.py:291-295`. Report G7 "Choices".
    - Problem: the report says `reserve` skips key registration and prints one stderr line. No test checks either.
    - Evidence: `grep -n "skipping key\|no SSH public" tests/*.py` returns nothing.
    - Fix: add a test to `tests/test_reserve.py` that reserves without `add_key` and asserts exit 0, `err.count("skipping key registration") == 1`, and no `list_ssh_keys` or `attach_ssh_key` call.
    - Settled: exchange 1.

### Nits

14. **`--sync` validates one path and transfers another**
    - Location: `src/rig/commands/run.py:84` and `:138`.
    - Problem: `_check_sync_dir` expands `~` and resolves against `ctx.cwd`, then `push_dir` gets the raw string. `--sync=~/proj` passes the check and fails with `sync_failed`.
    - Evidence: `src = os.path.join(directory, "")` on the original `sync_dir`.
    - Fix: return the resolved `Path` from `_check_sync_dir` and push `os.path.join(str(path), "")`. Update `tests/test_run.py:329` to expect `f"{harness.home}/project/src/"`.
    - Settled: initial match. Severity set in exchange 1.

15. **Pre-job cleanup misses `OSError`**
    - Location: `src/rig/commands/run.py:143`, `:147`, `:192`; `src/rig/commands/serve.py:153`.
    - Problem: cleanup catches `(RigError, KeyboardInterrupt)`. An `OSError` from `SshBox._run` (`remote.py:385` mkdir, or a subprocess error other than `FileNotFoundError`) skips `release_quietly`. `save_lease` and `attach_job` after job start are unguarded too.
    - Evidence: `except (RigError, KeyboardInterrupt): if created: release_quietly(ctx, lease); raise`.
    - Fix: use `except BaseException:` with the `if created:` guard and the re-raise at `run.py:143` and `serve.py:153`. Move `save_lease` inside that `try`. In `_attach`, release a release-on-exit box on any exception from `attach_job` and re-raise.
    - Settled: initial match. Severity set in exchange 1.

16. **Model-table values carry source `flag`**
    - Location: `src/rig/commands/serve.py:75` (`apply_overrides`), `src/rig/commands/reserve.py:199`.
    - Problem: model vram, gpu and image are written into `ctx.flags`. `serve --name X --model M` reusing lease X warns `flag_mismatch` for flags the user never passed, and `config show` labels them `flag`.
    - Evidence: `resolve({"vram":80.0,"image":"vllm/vllm-openai:v0.6.3"}, ..., {"RIG_VRAM":"24"}, ...)` gives `vram=flag image=flag`.
    - Fix: add a `model` argument to `config.resolve`. Build a layer from the entry's vram, gpu and image through `_convert_table` with origin `model`, inserted directly after `flag`. Pass the model from `serve` when `--on` is absent. Delete `apply_overrides`. Add `model` to the `config show` source list. Add a test for `--name` plus `--model` reuse.
    - Settled: initial match. Severity set in exchange 1.

17. **`parse_date_header` duplicates `parse_http_date` and misses `OverflowError`**
    - Location: `src/rig/provider.py:327`, `src/rig/timeutil.py:113`.
    - Problem: the copy omits `OverflowError`, raised for a year of about 20 digits. A create that succeeds with such a header becomes `provider_error` with no recovery.
    - Evidence: `parse_date_header('Mon, 01 Jan 100000000000000000000 00:00:00 GMT')` raises `OverflowError: Python int too large to convert to C long`.
    - Fix: delete `parse_date_header`. In `provider._record`, call `timeutil.parse_http_date(value if isinstance(value, str) else None)`. Move `tests/test_provider.py:412-416` to a `_record` test. Add an overflow case to `tests/test_timeutil.py`.
    - Settled: initial match. Severity set in exchange 1.

18. **Job and taken-id helpers are duplicated**
    - Location: `src/rig/commands/serve.py:205`, `:266`; `src/rig/commands/run.py:168`, `:172`; `src/rig/commands/tag.py:176`; `src/rig/commands/reserve.py:303`.
    - Problem: `serve._put_job` and `run._put_job` match character for character. `serve._record_exit` matches `run._finish_job`. `tag._taken` matches `reserve._taken_ids`.
    - Evidence: both `_put_job` bodies read `lease.jobs = [j for j in lease.jobs if j.id != job.id] + [job]`.
    - Fix: add `put_job`, `finish_job(lease, job_id, exit_code, finished: int | None)` and `taken_ids(snap)` to `commands/_common.py`. Import them at the four sites and delete the copies.
    - Settled: initial match. Severity set in exchange 1.

19. **`state.span` duplicates `format_duration` with different rules**
    - Location: `src/rig/state.py:117`, `src/rig/commands/run.py:100`.
    - Problem: one `status` output prints `1h5m` in the table and `1h05m` in a warning for the same time. `span` has no day unit.
    - Evidence: 3900s gives `1h05m` and `1h5m`. 90000s gives `25h00m` and `1d1h`.
    - Fix: delete `span`. Call `timeutil.format_duration` in `state.py` and `run.py:100`. Change `tests/test_state.py:116` to call `format_duration`, expect `"2h1m"` for 7260, and add a day case.
    - Settled: exchange 1.

20. **Two duration parsers accept different grammars**
    - Location: `src/rig/config.py:81-83`, `:159`, `:167`; `src/rig/timeutil.py:28`.
    - Problem: config accepts `1h1h`, `30m1h` and `1h0m`, which `timeutil` rejects. `reserve --ttl 1h1h` works and `extend --by 1h1h` fails. The report's G2 choice says units appear once each, in order.
    - Evidence: `config.parse_duration('1h1h')` returns 7200. `timeutil.parse_duration('1h1h')` raises.
    - Fix: delete `_DURATION`, `_DURATION_PART` and `_UNITS` in config. Make `config.parse_duration` call `timeutil.parse_duration` and return None on its `RigError`. Add cross-command test cases.
    - Settled: initial match. Severity set in exchange 1.

21. **A label over 1024 characters returns `provider_error`**
    - Location: `src/rig/commands/tag.py:154-160`, `src/rig/commands/extend.py:145`.
    - Problem: `format_label` raises `invalid_arguments`, and both callers rewrap it as `provider_error` with exit 2. `extend` first writes the clock file and then restores it. Spec §8.0 gives `invalid_arguments`.
    - Evidence: `tag ft --set-group g` on a 1023-character label exits 2 with `provider_error: Label write for l-0000a001 failed: Label is 1031 characters`.
    - Fix: call `labels.format_label` on every planned label before the write loop in `tag.update`. In `extend.apply`, format the new label before the first write.
    - Settled: exchange 1.

22. **The sweep re-destroys a swept lease while Vast still lists it**
    - Location: `src/rig/engine.py:259-273` (`_sweep`), `:277-283` (`_to_history`).
    - Problem: a successful sweep destroy leaves `destroy_pending` False. Each later refresh destroys the row again and adds another `swept` entry.
    - Evidence: three `rig status` runs against a provider that keeps the row each returned `swept: ['l-0000a003']`, and `provider.destroyed` ended as `[1001, 1001, 1001]`.
    - Fix: set `lease.destroy_pending = True` after a successful sweep destroy. In `_to_history`, clear `destroy_pending` and set `history_since = now` for any history state once the row is gone.
    - Settled: exchange 1.

23. **The `config set` comment choice has no test**
    - Location: `tests/test_config.py:547-580`. Report G1 "Choices".
    - Problem: the report says `config set` drops TOML comments. No test pins it.
    - Evidence: `grep -n comment tests/test_config.py` returns nothing.
    - Fix: add `test_config_set_drops_comments`. Write `# note\n[defaults]\nttl = "1h"\n`, run `config set defaults.disk 80`, and assert no `#` and values `{"defaults": {"ttl": "1h", "disk": 80}}`.
    - Settled: exchange 1.

24. **`serve` and `sync` warnings use a stale `now`**
    - Location: `src/rig/commands/serve.py:159`, `src/rig/commands/sync.py:41`.
    - Problem: `snap.now` predates the reserve wait, the vLLM install and model load, or a long rsync. A lease near expiry can miss `expiring_soon`.
    - Evidence: `lease_warnings(ctx, snap, lease, snap.now)` at both sites.
    - Fix: pass `ctx.clock.now()` at both sites.
    - Settled: exchange 1.

25. **A vLLM install timeout returns `box_unreachable`**
    - Location: `src/rig/commands/serve.py:209` (`_install`), `src/rig/remote.py:388-389`.
    - Problem: a timeout after 1800s raises `BoxUnreachableError`. Spec §5.1 and §7 give `serve_failed` for an install failure.
    - Evidence: `except subprocess.TimeoutExpired as exc: raise BoxUnreachableError(...)`.
    - Fix: in `_install`, catch the timeout from `ctx.box.exec` and raise `serve_failed` with the install hint.
    - Settled: exchange 1.

26. **Dead and redundant code**
    - Location: `src/rig/config.py:32` `SOURCES`; `src/rig/state.py:42` `WARNING_CODES`; `src/rig/views.py:45` `ZERO`; `src/rig/context.py:49` `Context.verbose` (set at `cli.py:265`); `src/rig/commands/reserve.py:367-368`; `src/rig/engine.py:220-222` `lease_from_row`; `src/rig/commands/reserve.py:150`.
    - Problem: the first four have no readers in `src` or `tests`. `reserve.py:367-368` re-set `label` and `state` that the constructors set. `lease_from_row` only calls `_new_lease`. `request_ports` re-checks type and range that `config._ports` enforces.
    - Evidence: `grep -rn '\bSOURCES\b' src tests` and `grep -rn '\bWARNING_CODES\b' src tests` each return the definition only.
    - Fix: delete the four names and the two assignments. Rename `_new_lease` to `lease_from_row` and delete the wrapper. Keep only dedup and the `MAX_PORTS` check in `request_ports`.
    - Settled: exchange 1.

27. **Duplicated constants**
    - Location: `ZERO` in `budget.py:21`, `engine.py:47`, `views.py:45`; the budget hint in `budget.py:102` and `engine.py:48`; `config.py:80` `_OWNER` and `ids.VALUE`; `WORKDIR` in `commands/_common.py:24` and `onstart.py:32`; `commands/completion.py:24` `HISTORY` and `models.HISTORY_STATES`; `commands/status.py:46` `DEFAULT_SERVE_PORT` and `serve.PORT`; `engine.py:308`, `:342` `== -1` and `onstart.STARTUP_INTERRUPTED`.
    - Problem: each value has two definitions that can drift.
    - Evidence: `_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")` repeats the `ids.VALUE` pattern.
    - Fix: import the single definition at each site. Drop the owner re-validation at `reserve.py:83`.
    - Settled: exchange 1.

28. **Two clients can claim the same job id**
    - Location: `src/rig/remote.py:473-474`, `src/rig/commands/_common.py:67`.
    - Problem: the start script tests `[ -e "$J/started" ]` and then runs `mkdir -p "$J"`. Two clients starting jobs on one lease at once can share an id.
    - Evidence: `'[ -e "$J/started" ] && { echo rig_job=exists; exit 0; }', 'mkdir -p "$J" || exit 3'`.
    - Fix: run `mkdir -p "$R/jobs" && mkdir "$J"` as the claim. On failure print `rig_job=exists`. Make `start_job` retry with the next id.
    - Settled: exchange 1.

29. **The rsync remote path is exposed to the remote shell on old rsync**
    - Location: `src/rig/remote.py:617-621` (`rsync_argv`).
    - Problem: rsync older than 3.2.4 re-parses the remote path in the remote shell, so a path with a space breaks the transfer.
    - Evidence: `argv += [src, remote + self.remote_path(dest)]` with no `-s` and no quoting.
    - Fix: add `-s` when `rsync --version` reports 3.0 or later. Otherwise apply `shlex.quote` to the remote path part. Add tests for a path with a space.
    - Settled: exchange 1.

30. **The report overstates the fakes' reach**
    - Location: `docs/swarm-report-0.md` "Layout", line 20.
    - Problem: the line says every test runs against `FakeProvider`, `FakeBox` and `Harness`. `tests/test_provider.py` stubs the HTTP session, and the remote and onstart tests run local scripts.
    - Evidence: "Every test runs against them. No test makes a network call."
    - Fix: change the line to "No test makes a network call. Provider tests stub the HTTP session."
    - Settled: exchange 1.

31. **An unprobed lease reports `guard: full`**
    - Location: `src/rig/models.py:175`, `src/rig/state.py:169-172`, `src/rig/commands/reserve.py:360` (`_new_cached`).
    - Problem: `guard_missing` defaults to `[]`, so a lease no probe has seen reads `full`. Spec §3.1 defines `full` by observed layers.
    - Evidence: `guard_missing: list[str] = field(default_factory=list)`. `guard` returns `("full", [])` for a new pending lease.
    - Fix: in `_new_cached`, set `guard_missing` to all three `GUARD_LAYERS`. In `state.lease_warnings`, emit `guard_partial` only when the state is not `pending`. Add tests: a `--no-wait` reserve shows `guard: partial` with three layers and no `guard_partial` warning, and a probed lease with no missing layers shows `full`.
    - Settled: exchange 2.

## Disagreements

None. Every dispute settled within two exchanges.

## Findings dropped

- **Review finding 6** (stopped instances at full `dph_total`): spec §5.2 prescribes `dph_total` for live instances, managed-lease commitments and `burn_per_hr`, and §3.1 keeps `stopped` active. `models.Instance` holds no storage rate. `tests/test_budget.py:107-117` asserts the current behaviour. Codex withdrew it in exchange 1.
- **Tag name check outside the lock** (Codex): spec §5.2 names the lock for `reserve`, `extend`, `run` and `serve`. §8.2 accepts duplicate names across clients. Codex withdrew it in exchange 1.
- **Base image not built** (Codex): the report lists it under "Deferred work" and it is still open. Codex withdrew it in exchange 1.
- **`--config -` `ttl` ignored by auto-reserved `run` and `serve`** (swarm): spec §4.6 says `--ttl` overrides `run_ttl`. `--config -` can set `run_ttl` itself.
- **`_JOB_ID` and `_SIGNAL` accept a trailing newline** (swarm): no payload can follow the newline.
- **State directory and lock file permissions** (swarm): `leases.json` is `0600` and the lock file holds no data.
- **Watchdog passes the destroy key on the curl command line** (swarm): the process runs as root in a single-tenant container.
- **`--bind-local` poll puts the serve key in local ssh argv** (swarm): the endpoint listens on the box's loopback and is reached only through the user's tunnel.
- **Test-only symbols in `src`** (swarm): `decode_onstart` is the inverse of `build_onstart` in the same module, and moving `VERBS` is a style preference with no rule behind it.

## Run

- Angles: review findings 1-5; review findings 6-10; correctness and spec conformance for the lease lifecycle (`engine`, `state`, `budget`, `targeting`, `labels`, `ids`, `cache`, `timeutil`, `views`, `reserve`, `extend`, `tag`, `release`, `status`); correctness and spec conformance for jobs, remote and config (`run`, `serve`, `sync`, `ssh`, `_common`, `config`, `completion`, `remote`, `onstart`, `watchdog.sh`, `cli`, `context`, `output`, `errors`, `provider`, `models`); swarm report claims and test coverage; security and slop. The lead ran the `uv` commands.
- Agents: 6 Sonnet.
- Reviewer model: astra.
- Exchanges: 2.
