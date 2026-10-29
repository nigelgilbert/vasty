# Validation 0: spec.md

Verdict: **rework.** Six blockers in core paths and forty-eight definitional gaps need fixes and a second validation pass before implementation.

Target: `spec.md` working tree as of 2026-10-29. Line numbers refer to that file.

## How to apply

Apply blockers, then gaps, then nits. Nit fixes apply to the text left after the gap fixes. Several fixes add error codes, warning codes or states; finding 7 holds the full code table and finding 22 the state table, so later fixes only name the code. "Effective expiry" is defined in finding 22 and used throughout.

## Agreed findings

### Blockers

**1. `guard: full` names a layer v1 does not have**
- Location: §3.1 Lease states, spec.md:67; §4.4 example, spec.md:211; §6, spec.md:392.
- Problem: `full` requires "provider auto-stop", which §6 defers to v1.1. No lease can be `full`. The status example repeats the missing layer.
- Evidence: :67 "`full` (provider auto-stop + on-box watchdog + local sweep all set)"; :406 "Provider scheduled job (optional, v1.1) ... v1 does not depend on it."; :211 "expiry enforced by provider + local sweep only".
- Fix:
  - Replace :67 with: "Each lease carries `guard` and `guard_missing`. `guard` is `full` when the watchdog is running, its destroy key is present, and the clock file matches the label. Otherwise it is `partial`, and `guard_missing` lists `watchdog`, `destroy_key` or `clock_file`. The sweep runs on every networked command and is not listed."
  - Replace the :211 line with `  l-7f3a  guard_partial       on-box watchdog not running; the sweep enforces expiry`.
  - Replace :392 "Three layers, in order of importance:" with "v1 has two layers. A third is planned for v1.1."
- Settled: exchange 0 (both lists).

**2. `tag` setter flags collide with TARGET selectors**
- Location: §4 synopsis, spec.md:80; §4.0, spec.md:92-93, :100; §4.5, spec.md:245-247.
- Problem: `--group` and `--owner` select targets (§4.0) and set values on `tag`. `tag --group old --group new` has no parse. `tag --group exp42` cannot tell selection from assignment.
- Evidence: :80 `rig tag TARGET [--name NAME] [--group G] [--owner O] [--ttl 30m]`; :100 "`--owner` on the command (sets ownership at `reserve`, filters elsewhere)"; :247 "`tag --group old --group new` renames a group across every member".
- Fix:
  - Replace :80 with `rig tag       TARGET [--set-name NAME] [--set-group G] [--set-owner O] [--ttl 30m]`.
  - Replace the first bullet of §4.5 (:247) with: "On a lease, `--set-name`, `--set-group` and `--set-owner` rewrite the label. `--group` and `--owner` select targets (§4.0). `tag ft --set-group exp42` moves a box into a group. `tag --group old --set-group new` renames a group across every member. An empty value clears `name` or `group`."
  - In :248 replace "with the current owner" with "with the owner from `--set-owner`, or the current owner".
- Settled: exchange 0.

**3. Streaming verbs break the one-JSON-object stdout rule**
- Location: §7, spec.md:415; §4.6, spec.md:255; §4.8, spec.md:291; §4.9, spec.md:295.
- Problem: `run` streams remote output and `ssh` runs a shell, yet JSON mode promises one parseable object on stdout. Where rig's result or error goes for these verbs is undefined.
- Evidence: :415 "stdout is a single parseable object in JSON mode."; :255 "run the command, stream output, release when it exits".
- Fix: insert after :415: "In JSON mode, attached `run` and `sync` send remote and rsync output to stderr and write one result object to stdout when they finish. Interactive `ssh` uses the terminal and emits no JSON. `ssh LEASE -- COMMAND` passes remote stdout, stderr and exit code through."
- Settled: exchange 0. The lead adopted the reviewer's stream layout.

**4. Bulk write scope is undefined for `--group` and `--owner`**
- Location: §4.0 Targeting, spec.md:88-113; §8.2, spec.md:476; §9.4, spec.md:523.
- Problem: Only `--all` is scoped to the caller. A group can span owners, and §9.4 promises `release --group exp42` spares other owners' boxes. Whether `release --group` destroys another owner's lease is a guess. Combinations of `--all`, `--everyone`, `--owner`, `--group` and a LEASE are undefined, as is an empty match.
- Evidence: :92 "`--group G` every active lease in group G"; :105 "`release --all` and `extend --all` touch only your own leases unless `--everyone` is given."; :106 "only bulk writes are scoped"; :111 "Leases in a group may have different clocks, hardware, and owners."; :523 "The human's own boxes, made under a different owner, are untouched by that last line."
- Fix: replace :105-106 with:
  - "Bulk writes (`extend`, `release`, `tag`) act on the current owner's leases, including `--group` writes. `--owner O` selects owner O instead. `--everyone` removes the owner filter and combines with `--all` or `--group`."
  - "Reads span every owner unless `--owner` filters them."
  - "`--all` combined with `--group` or `--owner`, `--everyone` combined with `--owner`, and a LEASE combined with any selector return `invalid_arguments`."
  - "A bulk target that matches no lease returns an empty result with exit 0."
- Settled: exchange 1. The reviewer rated it a blocker; the lead agreed.

**5. The clock premise conflicts with provider evidence on `start_date`**
- Location: §3 Rules, spec.md:49-50; §4.1, spec.md:138; §6, spec.md:403-404; §10.5; §12.
- Problem: The design assumes Vast sets `start_date` when the instance leaves `loading`, so boot is free and a loading box has no `start_date`. The SDK and docs treat `start_date` as creation time. If they are right, boot counts against the TTL, the "no `start_date`" sweep branch never fires, and the first-write runs while SSH is down. The spec also says storage accrues from creation; the docs say loading is free.
- Evidence: vastai 1.9.1 `api/instances.py:51` and `:89` `row['duration'] = time.time() - row['start_date']`; `cli/display.py:189` labels it `"age(hours)"`; docs.vast.ai manage-instances "Instance age (time since creation)" and "No, you're not charged while instances show \"Loading\" status."; OpenAPI "start_date: Instance start time (epoch seconds)."; spec :49 "The clock measures paid GPU time; storage accrues from creation."
- Fix:
  - In :49 replace "Boot time (image pull, container start) is not counted against the TTL." with "Boot time is free of the TTL when Vast sets `start_date` at running (§12)."
  - In :49 replace "storage accrues from creation" with "storage billing during `loading` follows Vast's rules".
  - In :49 replace "The first rig command that sees the instance running" with "The first rig command that sees `actual_status` `running`".
  - Add a §10.5 row: "| `start_date` is \"Instance start time\"; the SDK computes age as `now - start_date` | Live test: does Vast set `start_date` at create or at running? At create, boot counts against the TTL and the no-`start_date` rule never fires. |".
  - Replace the §12 bullet at :608 with: "- When does Vast set `start_date`: at create or at running? Does a host-side restart reset it? A live test settles both. The once-only `expires` write guards against a reset."
- Settled: exchange 1.

**6. `serve` exposure is still an open question**
- Location: §12, spec.md:602; §4.7, spec.md:270-285; §9.2, spec.md:498-500.
- Problem: §4.7 already returns a public URL and an `api_key`, yet §12 leaves public vs tunnel open. `serve` cannot be built until this is settled.
- Evidence: :602 "Does `serve` expose the endpoint publicly with a generated key, or tunnel it over SSH to localhost by default?"; :281-282 `"url": "http://198.51.100.7:8000/v1"`, `"api_key": "rig-local-xxxx"`.
- Fix:
  - Delete the :602 bullet.
  - Add to §4.7 after :285: "The endpoint is public on the external port mapped to container port 8000. rig generates a new API key per job, starts vLLM with `--api-key` and `--host 0.0.0.0`, and polls `/v1/models` with that key."
  - Add to §12 Settled: "- ~~Does `serve` expose the endpoint publicly?~~ Yes, with a generated key per job. See §4.7."
- Settled: exchange 1.

### Gaps

**7. Error codes and exit codes have no table**
- Location: §7, spec.md:416-428; §4.2, spec.md:166.
- Problem: `lease_pending` (:166) is missing from the core list. Many cases have no code. No code maps to an exit code. Bulk `extend` exits 2 for any failed entry, user errors included. The prose says "stable `code`" and the example uses `error`. A remote exit code of 1, 2 or 3 from `run` collides with rig's own exit codes.
- Evidence: :426 "Core error codes: `no_offers`, `budget_exceeded`, `lease_not_found`, `lease_expired`, `box_unreachable`, `job_failed`, `provider_error`, `auth_missing`."; :417 "a stable `code`"; :420 `"error": "no_offers"`; :166 "Exit code is 2 if any entry failed."; :428 "job exit code passed through for `run`".
- Fix:
  - Replace :417 with "- Every error object has `error` (the stable code), `message`, `hint`, and optional `details`:".
  - Replace :426-428 with this table and these lines:

    | Code | Exit | Raised when |
    |---|---|---|
    | `invalid_arguments` | 1 | a flag combination, name, duration, TIME or port list is invalid |
    | `invalid_config` | 1 | a config key or value is invalid |
    | `auth_missing` | 1 | no API key |
    | `dependency_missing` | 1 | `ssh` or `rsync` is not on PATH |
    | `no_offers` | 1 | no offer matches |
    | `lease_not_found` | 1 | unknown id or name |
    | `ambiguous_target` | 1 | a name or id matches more than one active lease |
    | `orphan_unmanaged` | 1 | an orphan id is passed to `extend`, `run`, `serve`, `sync` or `ssh` |
    | `lease_expired` | 1 | the lease is in history |
    | `lease_pending` | 1 | `extend`, `run --on`, `serve --on`, `sync` or `ssh` on a lease SSH cannot reach yet |
    | `name_conflict` | 1 | a new name matches another active lease of the same owner |
    | `confirmation_required` | 1 | orphan `release` without `--yes` in non-TTY mode |
    | `model_unknown` | 1 | `serve` model has no table entry and no `--vram` and `--image` |
    | `image_unsupported` | 1 | a custom image lacks bash, root or apt-get |
    | `startup_too_large` | 1 | the encoded `onstart` exceeds 4048 characters |
    | `provider_error` | 2 | a provider call fails |
    | `box_unreachable` | 2 | the box does not answer SSH |
    | `spend_unavailable` | 2 | billing coverage for today cannot be read |
    | `sync_failed` | 2 | rsync fails |
    | `serve_failed` | 2 | the inference server fails to install or exits before `/v1/models` answers |
    | `port_mapping_missing` | 2 | a required port has no external mapping at the readiness deadline |
    | `budget_exceeded` | 3 | the projection passes `daily_budget` |

    "Exit 0 covers success, warnings and empty bulk results. A bulk command exits with the highest exit code among failed entries. Parser errors use the same error object. `run` and `ssh -- COMMAND` exit codes follow §4.6."
  - In :166 replace "Exit code is 2 if any entry failed." with "Each entry's `error` is a code from §7."
  - Delete `job_failed`; `serve_failed` replaces it.
- Settled: exchange 0.

**8. `run` exit codes, signals and supervision are undefined**
- Location: §4.6, spec.md:255-264; §8.2, spec.md:475.
- Problem: A remote exit code is indistinguishable from rig's 1, 2 and 3. Exit codes for `--detach`, a job killed by expiry, and a dropped connection are unstated. Ctrl-C behavior is unstated. "tmux or nohup" is unresolved. :475 suggests "reattach with `--on`", which starts a new job.
- Evidence: :264 "Exit code mirrors the remote command's exit code."; :261 "under a supervisor on the box (tmux or nohup)"; :475 "reattach with `--on`".
- Fix:
  - Replace :264 with: "Errors before the job starts use §7 codes. After the job starts, `run` exits with the remote exit code, and the result object carries `exit` or `error` so a job's `2` differs from a provider error. `--detach` exits 0 once the job starts. A job killed with its box returns `lease_expired`, exit 2. A dropped connection returns `box_unreachable`, exit 2."
  - Replace "(tmux or nohup)" at :261 with "(tmux)". Add: "A foreground `run` also starts its job under tmux."
  - Add to §4.6: "On SIGINT, `run` forwards SIGINT to the remote job, waits up to 10s, then exits 130. An auto-reserved box is released. Named and `--on` boxes stay alive. Detached jobs continue after the client exits."
  - In :475 replace "reattach with `--on`" with "read the log with `rig ssh`".
- Settled: exchange 0.

**9. The synopsis omits flags and a verb, and TARGET is claimed for every command**
- Location: §4, spec.md:71-88; §10.3, spec.md:558; §10.4, spec.md:569.
- Problem: Flags used elsewhere are absent from the synopsis. `rig completion` exists in §10 and nowhere in §4. :88 says every lease command takes a TARGET, but `run --on`, `serve --on`, `sync` and `ssh` take one lease.
- Evidence: `--yes` (:182), `--detach` and `--sync` (:261-262), `--startup` (:366), `--no-wait` (:141), `--cached` and `--verbose` (:188), `--json` and `--plain` (:414), `--config -` (:345), `--delete` (:291), `--everyone` (:95); :84 "Nine verbs plus `config`."; :569 "`rig completion bash|zsh|fish`".
- Fix:
  - Replace :72-82 with:
    ```
    rig reserve   [--name NAME] [--group G] [--owner O] [--ttl 30m] [--profile P] [--startup FILE|-] [--no-wait] [--config -] [hardware flags]
    rig extend    TARGET  (--by 30m | --to 2h | --until TIME)
    rig release   TARGET [--yes]
    rig status    [TARGET] [--cached]
    rig run       [--on LEASE] [--detach] [--sync DIR] [reserve flags] -- COMMAND...
    rig serve     [--on LEASE] --model MODEL [--quant Q] [reserve flags]
    rig sync      LEASE (push [--delete] SRC DEST | pull SRC DEST)
    rig ssh       LEASE [-- COMMAND...]
    rig tag       TARGET [--set-name NAME] [--set-group G] [--set-owner O] [--ttl 30m]
    rig config    (show | set KEY VALUE | profiles)
    rig completion (bash | zsh | fish)
    ```
  - Replace :84 with "Nine verbs plus `config` and `completion`. Every verb takes `--json`, `--plain` and `--verbose`. Spend is part of `status`. Adopting an orphan is `tag`."
  - Replace :88 with "`extend`, `release`, `status` and `tag` take a **TARGET**. `run --on`, `serve --on`, `sync` and `ssh` take one lease id or name. A TARGET is one of:".
- Settled: exchange 1.

**10. Name, group, owner and lease id syntax and resolution are undefined**
- Location: §3, spec.md:37; §4.0, spec.md:91, :98, :104; §8.0, spec.md:437.
- Problem: The label is `;`- and `=`-delimited, but names have no charset or length. A name can look like a lease id or instance id. Lease ids are 4 hex digits drawn on separate machines. Ambiguous resolution has no rule.
- Evidence: :437 `rig:v1;lease=l-7f3a;name=trainer;...`; :91 "a lease id or name"; :98 "Name orphans by instance id."; :205 `i-55120`.
- Fix: insert after :104:
  - "Lease ids are `l-` plus 8 random hex digits. `reserve` redraws when the id is already in the instance list."
  - "`name`, `group` and `owner` match `[A-Za-z0-9][A-Za-z0-9._-]{0,62}`. A value outside that pattern, or a name matching `l-[0-9a-f]+` or `i-[0-9]+`, returns `invalid_arguments`."
  - "An orphan id is `i-` plus the Vast instance id."
  - "A LEASE resolves as an id first, then as a name under the selected owner. More than one match returns `ambiguous_target` with the matching ids."
- Settled: exchange 0.

**11. `tag` edge cases are undefined**
- Location: §4.5, spec.md:245-249.
- Problem: Undefined: `--set-name` on a bulk target, a name that collides, `--ttl` on an existing lease, an orphan without `--ttl`, `tag` with no setter, and the output shape.
- Evidence: :248 "`--ttl` is required for an orphan because it has no clock yet."; :249 "`tag` never touches the clock on an existing lease".
- Fix: add after :249:
  - "`--set-name` needs a single LEASE. On a bulk target it returns `invalid_arguments`. A name used by another active lease of the same owner returns `name_conflict`. `--set-owner` checks the new owner's names."
  - "`--ttl` on a lease returns `invalid_arguments` with the hint `rig extend`. An orphan without `--ttl` returns `invalid_arguments`."
  - "`tag` with no setter and no `--ttl` returns `invalid_arguments`."
  - "`tag` returns `{results, warnings, swept}`. Each result holds `lease`, `name`, `group`, `owner`, `expires_at`, `ttl_remaining_s`, `guard` and `guard_missing`."
- Settled: exchange 0.

**12. Duration and TIME grammar; `extend` into the past or on an unreachable box**
- Location: §4.2, spec.md:164-166; §4.1, spec.md:116.
- Problem: No grammar for durations or `--until`. `--to` or `--until` at or before now is undefined. `extend` on an expired or unreachable lease has no stated result.
- Evidence: :164 "`--to` (duration from now), or `--until` (timestamp)".
- Fix: insert after :166:
  - "A duration is a positive integer followed by `s`, `m`, `h` or `d`; units chain (`1h30m`). TIME is RFC 3339 with an offset. rig stores times as UTC epoch seconds."
  - "A bulk `extend` takes one `now` for every target."
  - "An expiry at or before `now` returns `invalid_arguments` with the hint `rig release`. An earlier expiry shortens the lease."
  - "A lease in history returns `lease_expired`. A lease whose clock file cannot be reached returns `box_unreachable` and changes nothing."
- Settled: exchange 0.

**13. Flag combinations with no meaning**
- Location: §4 synopsis, spec.md:76-77; §5, spec.md:345; §5.1, spec.md:366; §7, spec.md:414.
- Problem: `--on` with reserve flags, `--config -` with `--startup -` (both read stdin), and `--json` with `--plain` are undefined.
- Evidence: :76 `[--on LEASE] [reserve flags]`; :345 "`rig reserve --config -` reads JSON from stdin"; :366 "`--startup -` reads the script from stdin."; :414 "`--json` and `--plain` force either."
- Fix: insert after :82:
  - "With `--on`, creation flags (name, group, owner, profile, ttl, hardware, ports, image, startup, no-wait) return `invalid_arguments`. `--sync` works with `run --on`."
  - "Auto-reserved `run` and `serve` reject `--no-wait`."
  - "`--config -` with `--startup -`, and either with interactive `ssh`, return `invalid_arguments`."
  - "`--json` with `--plain` returns `invalid_arguments`."
- Settled: exchange 0.

**14. `run` and `serve` auto-release cannot work for `--detach` and `serve`**
- Location: §3, spec.md:52; §4.6, spec.md:255-261; §4.7, spec.md:271-272.
- Problem: rig has no daemon, so nothing releases a box after a detached job or a server ends. `run --name X` without `--on` gets opposite answers from :52 and :255. `serve` has no default TTL. Whether auto-reserve runs the budget check is unstated.
- Evidence: :52 "`run` and `serve` on an unnamed box auto-reserve one and auto-release it when the job ends. On a named box they reuse it and leave it alive."; :255 "No `--on`: reserve a box ..., release when it exits."; :261 "return a job id immediately"; :271 "waits for `/v1/models` to answer, returns the URL."
- Fix:
  - Replace :52 with: "`run` without `--on` reserves a box and releases it when the command exits. `run --detach` and `serve` without `--on` leave the box alive until `release` or expiry, and the response names the lease. `--name` without `--on` follows `reserve` idempotency (§4.1) and leaves the box alive. `--on LEASE` reuses that box and leaves it alive."
  - Add to :255: "Auto-reserve runs the §5.2 check with `run_ttl`."
  - Replace :272 "Same auto-reserve/`--on` semantics as `run`." with "Without `--on`, `serve` reserves a box with `run_ttl` and the §5.2 check. A failed `serve` releases a box it reserved."
- Settled: exchange 1. The reviewer's variant required a working destroy key and was dropped (see Dropped).

**15. `serve` on an existing box and on custom images has no install path**
- Location: §5.1, spec.md:349, :367; §4.7, spec.md:270-272; §9.3, spec.md:508.
- Problem: The base image has no inference server, yet `serve --on ft` runs on a `rig/base` box. Custom images assume an unstated OS, package manager and shell.
- Evidence: :349 "sshd, rsync, tmux, curl, python3, and the watchdog script"; :271 "Launches an inference server (vLLM by default)"; :367 "rig then installs its essentials via `onstart` if they are missing".
- Fix: insert after :367:
  - "A custom image needs Linux, bash, root and apt-get. Otherwise `reserve` returns `image_unsupported`."
  - "`serve` installs the pinned vLLM version into `/workspace/.rig/venv` when absent, `--on` boxes included. An install failure returns `serve_failed`."
- Settled: exchange 1.

**16. The model table and local checkpoints are undefined**
- Location: §4.7, spec.md:270; §5, spec.md:339-343; §9.3, spec.md:508; §12, spec.md:603.
- Problem: §12 leaves the table's home open. A model with no entry, and a local path like `./out/checkpoint`, have no rule.
- Evidence: :270 "The mapping is a small table in config, overridable per call."; :603 "How much of the model-to-hardware table ships built in versus lives in user config?"; :508 `rig serve --on ft --model ./out/checkpoint`.
- Fix:
  - Replace the second sentence of :270 with: "The mapping is the `[models.\"NAME\"]` tables in config. v1 ships the Qwen entry in §5. `--vram`, `--gpu`, `--quant` and `--image` override an entry. A model with no entry needs `--vram` and `--image` to auto-reserve, else `model_unknown`. A path is a directory on the box."
  - Delete :603. Add to Settled: "- ~~Built-in model table?~~ One entry; config adds more. See §4.7."
- Settled: exchange 1.

**17. Output shapes are missing for most commands**
- Location: §4.1, spec.md:139-160; §4.2, spec.md:164-166; §4.3, spec.md:182; §4.6, spec.md:261; §4.8; §4.10.
- Problem: `reserve` has no field for the idempotent-hit warning, no `--no-wait` shape, and calls the state `status` where §4.4 calls it `state`. Single `extend`, `tag`, detached `run`, `sync`, `config` and a no-op `release` have no shape. Bulk results are bare arrays under a one-object rule. A typo in `release` exits 0 silently.
- Evidence: :139 "Flag mismatches produce a warning."; :149 `"status": "running",`; :233 `"state": "running"`; :164 "Returns the new `expires_at`."; :182 "Releasing an unknown or already-dead lease is a no-op success."
- Fix:
  - At :149 replace `"status": "running",` with `"state": "running",`. Add `"owner"`, `"group"`, `"guard"`, `"guard_missing"`, `"reused": false`, `"ports"`, `"warnings": []` and `"swept": []` to the example.
  - Add after :160: "A hit on an existing lease returns it with `\"reused\": true`, a `flag_mismatch` warning listing differing flags, and no budget check. `--no-wait` returns `state: \"pending\"` with `expires_at`, `ttl_remaining_s`, `ssh`, `ssh_port`, `rsync_target` and `ports` set to `null`."
  - Insert after :415: "Bulk results are `{results, warnings, swept}`; each result has `lease`, `ok` and nullable `error`. Single `extend` returns `{lease, expires_at, ttl_remaining_s, warnings, swept}`. Detached `run` returns `{lease, job, log_path, expires_at, warnings, swept}`. Attached `run` returns `{lease, job, exit, duration_s, released, warnings, swept}`. `sync` returns `{lease, direction, src, dest, warnings, swept}`. `config` returns `{values}`, `{key, value}` or `{profiles}`."
  - Replace the second sentence of :182 with: "Releasing an unknown lease returns `{lease, already_absent: true}` with exit 0 and a stderr line naming the lookup. A job still running at release has `\"exit\": null`."
  - Add `flag_mismatch` to the warning codes at :192.
- Settled: exchange 0.

**18. `status` JSON lacks sources, orphans, guard detail and `swept`; other verbs have no place for warnings**
- Location: §4.4, spec.md:186-192, :227-241; §6, spec.md:401.
- Problem: The JSON omits remaining budget, spend source, budget source, orphan entries, guard detail, the log tail and `swept`. Every networked command sweeps, but only `status` says where swept leases appear, and the sweep's reach beyond the target is unstated.
- Evidence: :186 "remaining daily budget"; :187 "the output says which"; :190 "anything it released appears in a `swept` array"; :227 field list; :401 "Every networked `rig` command lists instances".
- Fix: insert after :241:
  - "`status` returns `{leases, warnings, totals, swept, cached_at}`. `cached_at` is `null` on a fresh result."
  - "Each lease adds `guard_missing` and `cost_source` (`billing`, `estimated` or `mixed`). A single-lease target adds `log_tail`, the last 100 lines."
  - "Orphans appear in `leases` with `lease` set to the `i-` id, `state: \"orphan\"`, and `owner`, `expires_at`, `ttl_remaining_s` and `guard` set to `null`."
  - "`totals` adds `remaining_budget`, `daily_budget_source` and `spend_source`, and covers the whole account."
  - "A `swept` entry is `{lease, name, expired_at, ok, error}`."
  - "Every networked command sweeps all managed leases on the account before it resolves its target. Its JSON carries `warnings` and `swept`."
- Settled: exchange 0.

**19. `status --cached` and the sweep**
- Location: §4.4, spec.md:188-190.
- Problem: `--cached` makes no network call, yet `status` "also performs" the sweep and reconciliation.
- Evidence: :188 "`--cached` answers from the local file without a network call"; :190 "Also performs the **expiry sweep** ... and **reconciliation**".
- Fix: add after :188: "`--cached` skips the sweep and reconciliation, returns `swept: []`, and derives warnings from cached data. It accepts a TARGET."
- Settled: exchange 0.

**20. Warning `fix` strings break their own rule**
- Location: §4.4, spec.md:192, :208-211; §8.2, spec.md:474.
- Problem: `fix` is "a runnable rig command", but :209 is prose, :210 holds two commands, and :211 holds none. Account warnings have no lease. No fix is defined for `budget_low`, `startup_failed` or `guard_partial`.
- Evidence: :192 "a `fix` string that is a runnable rig command"; :209 "rig release l-8b11 and re-reserve"; :210 "rig tag i-55120 --ttl 30m   or  rig release i-55120".
- Fix:
  - Replace the first sentence of :192 with: "Output always includes a `warnings` array. Each entry has `code`, `lease` (`null` for account warnings), `message`, and `fix`, one runnable rig command."
  - Add: "Fixes: `expiring_soon` and `expiring_with_running_job` use `rig extend L --by 30m`. `box_unreachable` and `guard_partial` use `rig release L`. `orphan` uses `rig tag ID --ttl 30m`. `startup_failed` uses `rig ssh L -- cat /workspace/.rig/startup.log`. `budget_low` and `spend_unavailable` use `rig status`. Fixes shell-quote their arguments."
  - Replace :208-211 with:
    ```
      l-8b12  expiring_soon       3m left                      fix: rig extend l-8b12 --by 30m
      l-8b11  box_unreachable     no answer for 6m             fix: rig release l-8b11
      i-55120 orphan              not created by rig           fix: rig tag i-55120 --ttl 30m
      l-7f3a  guard_partial       watchdog not running         fix: rig release l-7f3a
    ```
  - Add `"message": "3m left"` to the JSON warning at :237.
- Settled: exchange 0.

**21. `release` of an unreachable lease and orphan confirmation**
- Location: §4.3, spec.md:170-182; §12, spec.md:605.
- Problem: §12 leaves the unreachable case open. Destroy acknowledgment, bulk partial failure, and the TTY prompt for an orphan are undefined.
- Evidence: :605 "Should `release` of an `unreachable` lease wait for provider confirmation, or mark it released locally and move on?"; :182 "requires `--yes` in non-TTY mode".
- Fix:
  - Delete :605. Add to Settled: "- ~~Does `release` of an `unreachable` lease wait?~~ It waits for the destroy call only. See §4.3."
  - Add after :182: "`release` returns when the provider accepts the destroy call, for `unreachable` leases too. The lease is `released` with `destroy_pending: true` until a list call shows it gone. `uptime_s` and `jobs` come from the local cache. A failed destroy returns `provider_error`. In TTY mode an orphan release prompts unless `--yes` is given. In non-TTY mode a missing `--yes` returns `confirmation_required`."
- Settled: exchange 0.

**22. The state table is wrong, and "effective expiry" is undefined**
- Location: §3.1, spec.md:57-65; §3, spec.md:50; §4.6, spec.md:259; §8.2, spec.md:468; §8.1, spec.md:458.
- Problem: `expiring_soon` is a state in the table and a warning on a `running` lease in the JSON. `expired_with_running_jobs` is a history state in :259 and :468 and a warning in :192, and is missing from the table. "Kept in history briefly" disagrees with 24h. Sweep, status, reconciliation and the reserve wait all need the clock of a lease whose label lacks `expires`.
- Evidence: :62 "`expiring_soon` | Running, under the warn threshold"; :233-237 `"state": "running"` with warning `expiring_soon`; :468 "stays in history as `expired_with_running_jobs`"; :63 "Kept in history briefly."; :458 "stay in history for 24h".
- Fix:
  - Delete the :62 row. Add under the table: "A `running` lease with `0 < ttl_remaining_s <= warn_before_expiry` carries the `expiring_soon` warning."
  - In :63 and :64 replace "Kept in history briefly." with "Kept in history for 24h."
  - In :259 and :468 replace "stays in history as `expired_with_running_jobs`" with "stays in history as `expired` with an `expired_with_running_jobs` warning".
  - Add after the table: "History states take precedence over `pending` and `unreachable`. `ttl_remaining_s` floors at 0."
  - Insert after :50: "- A lease's effective expiry is `expires` from the label, else `start_date + ttl`, else `created + ttl`."
- Settled: exchange 0. The lead adopted the reviewer's fix.

**23. `pending` has two definitions and the `reserve` wait has no deadline**
- Location: §3.1, spec.md:59; §4.1, spec.md:141; §4.2, spec.md:166; §5.1, spec.md:365; §8.2, spec.md:469.
- Problem: `pending` means "not yet SSH-reachable" and also "startup script still running". A box running a long startup script is billing and has a clock file, yet `extend` refuses it. `reserve` waits for SSH; whether it waits for startup is unstated. A box that runs but never answers SSH has no give-up point.
- Evidence: :59 "Reserved on the provider, not yet SSH-reachable."; :365 "the box is reported `pending` until it exits 0"; :166 "A `pending` lease has no clock file yet, so `extend` on it returns `lease_pending`."; :469 handles only a box that never leaves `loading`.
- Fix:
  - Replace :59 with "| `pending` | Reserved and not ready: booting, SSH not answering, or the startup script still running. |".
  - Replace the second sentence of :166 with "`extend` returns `lease_pending` until SSH answers. A lease running its startup script accepts `extend`."
  - Replace :141 with "- Waits until the lease leaves `pending` (skip with `--no-wait`). The wait ends at the effective expiry (§3). At that point `reserve` destroys the box and returns `box_unreachable`. A startup exit other than 0 ends the wait with a `startup_failed` warning."
  - In :469 replace "gives up at the same point" with "gives up at the effective expiry".
- Settled: exchange 0.

**24. No mapping from Vast instance status to rig state**
- Location: §3.1, spec.md:57-65; §4.4, spec.md:209.
- Problem: The spec never maps `actual_status` values to rig states, never says how `unreachable` is detected, and has no state for a provider-stopped box. ":209 6m ago" needs a stored last-reachable time.
- Evidence: OpenAPI "if `actual_status` becomes `exited`, `unknown`, or `offline` it will never reach `running`"; `actual_status` is string or null; :61 "the box stopped responding".
- Fix: insert after the §3.1 table:

  | `actual_status` | Probe (§3.2) | State |
  |---|---|---|
  | null, `created`, `loading` | not run | `pending` |
  | `running` | never answered | `pending` |
  | `running` | answered before, fails now | `unreachable` |
  | `running` | answers, startup unfinished | `pending` |
  | `running` | answers, startup done or failed | `running` |
  | `exited`, `stopped` | not run | `stopped` |
  | `offline`, `unknown` | not run | `unreachable` |

  Add the row "| `stopped` | The provider stopped the instance, for example at $0 balance. The sweep still destroys it past its clock. |" to §3.1. Add: "The cache stores `reachable_at`, the last time the probe answered."
- Settled: exchange 1.

**25. rig has no way to learn guard status**
- Location: §6, spec.md:399; §8.1, spec.md:451; §4.4, spec.md:211.
- Problem: `onstart` finds a missing `CONTAINER_API_KEY` on the box, and nothing carries that to rig. "Last known guard" lives only in the local cache, so another machine or a rebuilt cache cannot see it. "Watchdog not running" has no liveness signal.
- Evidence: :399 "When `onstart` finds it missing, the lease is `guard: partial`"; :451 "and the last known `guard` status"; :470 "Only job history is lost."
- Fix:
  - Insert a new "### 3.2 Probe": "The probe is one SSH command. It reads `/workspace/.rig/clock`, `/workspace/.rig/guard`, `/workspace/.rig/startup.exit` and the mtime of `/workspace/.rig/alive`. `status` and the sweep run it on each `running` instance in parallel with a 5s timeout. `onstart` writes missing layers to `guard`. The watchdog touches `alive` each loop; an `alive` older than 3m means the watchdog is down. The probe rewrites the clock file when it differs from the label. A probe that finds missing layers writes `miss=LAYERS` to the label."
  - Add `;miss=watchdog` as an optional field to the :437 example description.
  - In :451 delete "and the last known `guard` status".
- Settled: exchange 1.

**26. The cron-restarted watchdog has no credentials, and cron is not in the image**
- Location: §6, spec.md:394-399; §5.1, spec.md:349.
- Problem: Cron jobs do not inherit the container environment, so a watchdog restarted by cron has no `CONTAINER_API_KEY`. The base image list omits cron.
- Evidence: docs.vast.ai docker-environment: "If you're in an SSH session and the predefined variables are missing, you may need to export them to `/etc/environment`"; :397 "runs under cron every minute"; :349 "sshd, rsync, tmux, curl, python3, and the watchdog script".
- Fix:
  - Add to §6 layer 1 after the first watchdog bullet: "- reads `CONTAINER_ID` and `CONTAINER_API_KEY` from `/workspace/.rig/env`, which `onstart` writes with mode 600;".
  - In :349 replace "sshd, rsync, tmux, curl, python3" with "sshd, cron, rsync, tmux, curl, python3".
- Settled: exchange 1.

**27. The first-write is mislabeled and has no failure path**
- Location: §3, spec.md:49; §6, spec.md:395, :403.
- Problem: The first-write moves the clock file from `onstart`'s `now + ttl` to the earlier `start_date + ttl`. That is a shortening, so §6 orders the label first. A failed SSH write is never retried, because :403 fires only while the label lacks `expires`.
- Evidence: :49 "in the `extend` lengthening order (§6)"; :395 "Container time is at or after `start_date`"; :408 "when shortening, the label first and the clock file second".
- Fix:
  - In :49 replace "in the `extend` lengthening order (§6)" with "in the `extend` shortening order (§6)".
  - Append to :403: "If the clock-file write fails, the label keeps the value and the lease reports `guard_missing: [clock_file]`. The next probe rewrites the file."
- Settled: exchange 1.

**28. Watchdog and first-write robustness**
- Location: §6, spec.md:395-404.
- Problem: A first-write can compute an expiry already past. Clock-file writes are not atomic. Cron can start a second watchdog. Failed destroys and unreadable clock files have no rule.
- Evidence: :395 "`onstart` writes `now + ttl`"; :403 "gets `expires = start_date + ttl` written to it"; :397 "runs under cron every minute alongside the sleeping process".
- Fix: insert after :404:
  - "A first-write whose expiry is at or before `now` destroys the box at once."
  - "Clock-file writes go to a temp file and rename."
  - "The watchdog holds a lock file so cron starts at most one."
  - "A failed destroy retries with backoff capped at 60s."
  - "An unreadable clock file is logged and re-read within 60s. The probe reports it as `guard_missing: [clock_file]`."
- Settled: exchange 1.

**29. Clock writes race across clients, and restore failure is undefined**
- Location: §6, spec.md:401, :408.
- Problem: A sweep can list a lease, another client can extend it, and the sweep then destroys it. A failed restore in `extend` leaves label and file unstated.
- Evidence: :401 "reads each `rig:` label, and destroys anything past its clock"; :408 "If the second write fails, `extend` restores the first, fails with `provider_error`".
- Fix: insert after :408: "Before destroying or writing a label, a command re-reads the instance row and aborts when `expires` differs from the value it read. A window remains between that read and the write: two clients acting on one lease inside it can lose an `extend` or destroy a just-extended box. rig accepts this race. If the restore in an `extend` also fails, `extend` returns `provider_error` naming both values, and the next networked command rewrites the clock file from the label."
- Settled: exchange 2.

**30. The sweep trusts the client clock**
- Location: §6, spec.md:402-404; §4.5, spec.md:248.
- Problem: The sweep compares the client clock with provider and label times and destroys irreversibly. A fast client destroys healthy boxes. `tag` writes `expires` from the client clock.
- Evidence: :402 "past its clock when `now > expires`"; :404 "`now > created + ttl`".
- Fix: append after :404: "`now` is the `Date` header of the latest provider response plus the local monotonic time since that response. When the header is missing or unparsable, rig uses the local clock and adds a `clock_unverified` warning. `reserve` and `tag` take `now` the same way." Add `clock_unverified` to :192.
- Settled: exchange 2.

**31. Orphan adoption has no install path or partial-failure rule**
- Location: §4.5, spec.md:248; §8.2, spec.md:471.
- Problem: "installs the watchdog" names no access path or tools. An orphan may lack rig's key, sshd, cron or curl. A restart drops a watchdog that no `onstart` reinstalls. A failure part way leaves an undefined lease.
- Evidence: :248 "writes the same expiry to the box's clock file, installs the watchdog, and from then on it is a lease like any other".
- Fix: insert after :248: "`tag` writes the label first and keeps it if a later step fails. It then connects over SSH (§5.3), writes the clock file, copies `CONTAINER_ID` and `CONTAINER_API_KEY` from `/proc/1/environ` to `/workspace/.rig/env`, and starts the watchdog under cron or `nohup`. A failed step returns the lease with `guard: partial` and a `guard_partial` warning; the sweep enforces the clock. Later networked commands retry the missing steps. A container restart removes the watchdog from an adopted box."
- Settled: exchange 0.

**32. Reconciliation cannot classify a vanished lease**
- Location: §8.1, spec.md:455-458.
- Problem: Only the releasing machine knows it called `release`. A box can vanish with time left (dashboard destroy, $0 deletion, host eviction). Cache writes from parallel processes have no lock, and a corrupt cache has no rule.
- Evidence: :455 "moved to history as `expired` or `released`"; :26 "at $0 Vast stops every instance and schedules it for deletion".
- Fix:
  - Replace :455 with: "A lease in the file that Vast no longer lists moves to history: `released` when this machine released it, `expired` when its effective expiry has passed, otherwise `gone`." Add a §3.1 row: "| `gone` | Vanished with time left on its clock. Kept in history for 24h. |"
  - Append after :458: "rig takes an exclusive lock on `leases.json.lock` for each read-modify-write and replaces the file by temp file and rename. A corrupt file is rebuilt from the provider with a `cache_rebuilt` warning. The 24h window starts when rig first sees the lease gone."
- Settled: exchange 0.

**33. Malformed and unknown-version labels are unhandled**
- Location: §8.0, spec.md:443, :447.
- Problem: A label that starts `rig:` but is not v1, or lacks fields, is neither an orphan nor parseable. A sweep on it destroys a box rig cannot read.
- Evidence: :443 "An **orphan** is precisely an instance whose label does not start with `rig:`."; :447 "so it can change later without breaking older boxes".
- Fix: insert after :447: "Labels are `;`-separated `key=value` fields with unique keys. `lease`, `owner`, `created` and a positive integer `ttl` are required; `expires` is optional. Times are UTC epoch seconds. Metadata updates keep unknown fields. A generated label over 1024 characters returns `invalid_arguments`. A `rig:` label with an unknown version or missing fields shows as `orphan` with a `label_unreadable` warning. The sweep and bulk writes skip it, `tag` refuses it, and `release` by instance id works." Add `label_unreadable` to :192.
- Settled: exchange 0.

**34. Parallel processes on one machine race**
- Location: §4.1, spec.md:139-140; §8.2, spec.md:472; §5.2, spec.md:373; §2.1, spec.md:26.
- Problem: Two parallel `reserve --name ft` calls both see no lease and both create. Two spending commands both pass the budget check. :472 promises idempotency it cannot deliver.
- Evidence: :472 "Within one owner, idempotency returns the existing lease."; :114 "An agent that wants three boxes calls `reserve` three times (or loops in its skill)."
- Fix:
  - Add to §5.2: "- `reserve`, `extend`, `run` and `serve` hold the `leases.json` lock from the name check and budget check until the provider call returns. Separate machines check independently."
  - Replace the last sentence of :472 with "On one machine the lock makes the second call return the first lease. Two machines can create two; a later command naming it returns `ambiguous_target`."
  - Add to :139: "The name check runs before offer search and the budget check."
- Settled: exchange 0.

**35. Job records live only in the local cache**
- Location: §8.1, spec.md:451, :470; §8.2, spec.md:475; §4.4, spec.md:192.
- Problem: Live job state drives `expiring_with_running_job`, yet job records exist only on the machine that started the job. Another machine, or a lost cache, cannot see live jobs.
- Evidence: :451 "job records (command, start time, exit code, log path)"; :470 "Only job history is lost."; :475 "Next `status` shows it with the job state".
- Fix: insert after :451: "Each job also writes `/workspace/.rig/jobs/<job-id>/` on the box with command, start time, pid, exit code and log. Job ids are unique per lease. The probe reads these records and the cache stores them. An unreachable box reports its jobs as `unknown` with `exit: null`. A lost cache loses records of destroyed boxes only."
- Settled: exchange 1.

**36. "Best offer" is undefined**
- Location: §4.1, spec.md:137.
- Problem: The ranking that picks an offer has no order or tie-break.
- Evidence: :137 "\"Best\" weighs reliability and bandwidth; the cheapest offer breaks ties."
- Fix: replace :137 with "- Filters offers by the resolved constraints, then sorts by reliability descending, download bandwidth descending, `dph_total` ascending and offer id ascending."
- Settled: exchange 1.

**37. SSH access is unspecified**
- Location: §4.1; §4.2; §4.6; §4.8; §4.9; §6, spec.md:408; new §5.3.
- Problem: `extend`, the first-write, the probe, `sync`, `ssh`, `run` and adoption depend on SSH. The spec names no key, no registration step, no direct-vs-proxy rule and no host-key policy. Vast reuses host and port pairs.
- Evidence: OpenAPI "SSH keys must be registered BEFORE creating an instance"; docs ssh guide "Adding a key to your account keys only applies to **new instances**"; create `runtype` accepts `ssh`, `ssh_proxy`, `ssh_direct`; spec :156 `ssh -p 41022 root@198.51.100.7`.
- Fix: add after §5.2:

  "### 5.3 SSH access

  rig connects as root with the key at config `ssh_key` (default: the first of `~/.ssh/id_ed25519` and `~/.ssh/id_rsa`). `reserve` registers the public key on the account before create when no matching key exists. `tag` attaches it to an orphan. rig creates instances with `runtype` `ssh_direct` when the offer has direct ports, else `ssh_proxy`. It connects to `public_ipaddr` and the port mapped to 22, or `ssh_host` and `ssh_port` for proxy. ssh runs with `StrictHostKeyChecking=accept-new`, `UserKnownHostsFile=~/.local/state/rig/known_hosts` and `HostKeyAlias=vast-<instance id>`."

  Add `ssh_key` to the example config at :317.
- Settled: exchange 0.

**38. `sync` paths, `--sync DIR` and local tools are undefined**
- Location: §4.8, spec.md:291; §4.6, spec.md:262; §10.2, spec.md:544.
- Problem: Relative DEST, the destination of `--sync DIR`, transfer failure, and the local `ssh` and `rsync` prerequisites are unstated.
- Evidence: :262 "use `--sync DIR` as sugar for push-then-run"; :544 "`subprocess` for `rsync`/`ssh`".
- Fix: insert after :291: "A relative remote path resolves under `/workspace`. rsync trailing-slash rules apply. `--sync DIR` pushes the contents of DIR into `/workspace/` before the job starts. A failed transfer returns `sync_failed` and starts no job; an auto-reserved box is released. A missing local `ssh` or `rsync` returns `dependency_missing`."
- Settled: exchange 0.

**39. Port lists and the `serve` URL**
- Location: §4.1, spec.md:130-133; §4.7, spec.md:281.
- Problem: Port validation and missing mappings are undefined. The `serve` example uses container port 8000, but external ports are random. The port map appears only in `--verbose`.
- Evidence: :133 "Vast maps each to a random external port; rig reads the mapping ... and reports it in `--verbose` output"; :281 `"url": "http://198.51.100.7:8000/v1",`.
- Fix:
  - Insert after :133: "Ports are TCP integers from 1 to 65535. rig deduplicates the list, defaults included, before the 64-port limit. An invalid list returns `invalid_arguments`. A required port with no mapping at the readiness deadline returns `port_mapping_missing`."
  - In :133 replace "reports it in `--verbose` output" with "returns it in the `ports` field".
  - Replace :281 with `  "url": "http://198.51.100.7:41080/v1",`.
- Settled: exchange 0.

**40. `startup` mixes paths and inline scripts, and "runs once" has no marker**
- Location: §5.1, spec.md:356-366.
- Problem: A string is a path or inline shell with no rule to tell them apart. A container restart reruns or skips the hook with no stated marker.
- Evidence: :356 `startup = "setup.sh"                 # path to a bash script, or inline below`; :365 "`startup` runs once on the box".
- Fix:
  - Replace :356 with `startup_file = "setup.sh"            # path to a bash script`, and keep `startup` for inline scripts at :359.
  - Add to §5.1: "Setting both `startup_file` and `startup` returns `invalid_config`. A config path resolves relative to its config file; a CLI path resolves relative to the working directory. The wrapper writes started and exit markers under `/workspace/.rig/`. A restart skips a hook that already started. A hook cut off by a restart reports `startup_failed`."
- Settled: exchange 1.

**41. `onstart` is limited to 4048 characters**
- Location: §5.1, spec.md:365-367; §6, spec.md:394; §10.5.
- Problem: rig puts the clock write, startup wrapper, user script and, for custom images, the watchdog into `onstart` with no size rule and no completion signal.
- Evidence: OpenAPI Key Quirks: "`onstart` field is limited to 4048 characters -- gzip+base64 for longer scripts".
- Fix: add to §5.1: "rig builds `onstart` from the clock-file write, the startup wrapper and the user's `startup` script, compressed with gzip and base64. With `--image`, `onstart` also carries the watchdog and the essentials installer. When the encoded `onstart` exceeds 4048 characters, `reserve`, `run` and `serve` return `startup_too_large` before any create call. The wrapper writes the exit code to `/workspace/.rig/startup.exit` and the output to `/workspace/.rig/startup.log`." Add a §10.5 row: "| `onstart` is limited to 4048 characters | rig compresses it and refuses larger scripts |".
- Settled: exchange 2.

**42. The configuration contract is incomplete**
- Location: §5, spec.md:305-345; §4.10, spec.md:297-301.
- Problem: Built-in defaults are never listed. `--config -` sits outside the resolution order with no schema. Two project files have no precedence. Env var names are unstated. `config set` has no key syntax for nested tables.
- Evidence: :312 "Built-in defaults"; :310 "`./rig.toml` or `./.rig/config.toml`"; :345 "`rig reserve --config -` reads JSON from stdin"; :300 "`set KEY VALUE` writes to the user config file."
- Fix:
  - Insert after :312: "`--config -` sits just below flags. Its JSON object uses the `[defaults]` keys. `./rig.toml` wins over `./.rig/config.toml`. Profiles merge by name and field across files before the selected profile applies. Each `[defaults]` key maps to `RIG_<KEY>` in upper case. Unknown keys or bad types return `invalid_config`. Built-in defaults: `ttl` 30m, `run_ttl` 2h, `max_price` 0.60, `daily_budget` 10.00, `warn_before_expiry` 5m, `disk` 50, `gpus` 1, `image` `rig/base:cuda12.4`."
  - Replace :299-301 with: "- `show` prints each effective value and its source (`flag`, `stdin`, `profile`, `env`, `project`, `user`, `default`).\n- `set KEY VALUE` writes to the user config file. KEY is a dotted TOML path (`defaults.ttl`, `profiles.big.vram`). VALUE parses as a TOML scalar.\n- `profiles` lists named profiles."
- Settled: exchange 0.

**43. `daily_budget` is account-scoped but resolves per profile**
- Location: §5, spec.md:324, :337; §5.2, spec.md:385-386; §3, spec.md:42; §4.4, spec.md:213, :227, :239.
- Problem: `reserve --profile big` checks against 40.00 and a bare `reserve` against 10.00 on one account. The status example shows $40.00 with no profile. :386 says status shows the source; the JSON has no source field.
- Evidence: :337 `daily_budget = 40.00`; :324 `daily_budget = 10.00`; :385 "The scope is the whole account."; :213 "spent $7.12 of $40.00".
- Fix:
  - Delete :337. In :42 replace "(hardware preferences, image, TTL, budget)" with "(hardware preferences, image, TTL)".
  - Replace :386 with "- `daily_budget` has no flag and no profile key. It resolves from `RIG_DAILY_BUDGET`, the project file, the user file, then the built-in default."
  - Change :213 to "spent $7.12 of $10.00". Change `"daily_budget": 40.00` at :239 to `10.00`.
- Settled: exchange 1.

**44. The projected-spend formula has undefined terms**
- Location: §5.2, spec.md:373-384; §4.5, spec.md:248.
- Problem: Σ uses `expires_at`, which a pending lease lacks. Orphans bill but have no clock. A shortening gives a negative term. `--to` and `--until` have no per-lease extension. An overdue lease gives negative hours. `tag` cites a projection with no `tag` term.
- Evidence: :377 "Σ live leases: dph_total × hours from now to expires_at"; :379 "target leases: dph_total × extension (extend)"; :248 "when the projection (§5.2) passes `daily_budget`".
- Fix: add after :380:
  - "Each managed lease counts `dph_total` × hours from now to its effective expiry, floored at 0."
  - "Orphans count in `spent_today` only. `tag` adds `dph_total × ttl` for the orphan."
  - "`extend` replaces each target's current commitment with the new one. A change that holds or lowers the projection always passes."
- Settled: exchange 1. The reviewer rated it a blocker; it settled as a gap.

**45. `spent_today` drops billed spend when billing is stale**
- Location: §5.2, spec.md:382; §4.4, spec.md:187; §10.5, spec.md:583.
- Problem: "Otherwise price × uptime since the last billing update" replaces the billed figure. "Fresh" has no threshold. Charges before 00:00 UTC are not clipped. Deleted instances and other owners are not named.
- Evidence: :382 "`spent_today` is Vast's billing figure when fresh, otherwise price × uptime since the last billing update."; vastai 1.9.1 `show_invoices_v1(charges=True)` calls `/api/v0/charges` with a required `day` range and returns per-contract `amount` with gpu/disk/bwd/bwu items.
- Fix: replace :382 with: "- `spent_today` is billed charges from 00:00 UTC through `covered_through`, for every instance on the account, deleted ones included, plus `dph_total` × time since `covered_through` for each live instance, clipped to today. When coverage cannot be read, spending commands return `spend_unavailable` and `status` reports null spend with a `spend_unavailable` warning. A live test confirms the charges endpoint clips to the day range (§12)."
- Settled: exchange 1. The reviewer rated it a blocker; it settled as a gap with a live test.

**46. `budget_low`, `remaining` and burn rate are undefined**
- Location: §4.4, spec.md:192; §5.2, spec.md:387; §4.0, spec.md:113; §4.2, spec.md:164.
- Problem: `status` lists `budget_low` with no trigger. `remaining` and `projected` have no definition and no place in the error object. Burn rate does not say whether orphans count.
- Evidence: :192 "`budget_low`"; :387 "Refusal returns `budget_exceeded` with `remaining` and `projected`, exit code 3."
- Fix: add after :388:
  - "Billing data is fresh for 60s. Money uses decimal arithmetic and prints to 2 places."
  - "`budget_low` fires when the projection reaches 90% of `daily_budget`."
  - "`budget_exceeded` puts `projected` (with the action), `remaining` (`daily_budget` minus the projection without the action) and `daily_budget` in `details`."
  - "`burn_per_hr` sums `dph_total` over live leases and orphans."
- Settled: exchange 0.

**47. `--max-price` has no comparand**
- Location: §4.1, spec.md:128; §5.2, spec.md:383.
- Problem: `--max-price` is a $/hr ceiling. `dph_total` is GPU plus disk, and disk varies per call.
- Evidence: :128 "`--max-price $/HR    hard ceiling for this lease`"; :383 "`dph_total` is the offer's GPU price plus disk."
- Fix: replace :128 with `--max-price $/HR    ceiling on the offer's dph_total, GPU plus requested disk`.
- Settled: exchange 1.

**48. `provider.py` lacks functions the spec needs**
- Location: §10.2, spec.md:549.
- Problem: The list misses balance, single-instance get, SSH key list and attach. vastai 1.9.1 has no `charges` method. The label goes in at create.
- Evidence: :549 "`search_offers`, `create`, `list_instances`, `destroy`, `set_label`, `charges`"; vastai 1.9.1 has `show_user`, `show_instance`, `show_ssh_keys`, `attach_ssh` and `show_invoices_v1(charges=True)`.
- Fix: replace the :549 sentences with "It exposes ten functions: `search_offers`, `create`, `list_instances`, `get_instance`, `destroy`, `set_label`, `charges`, `balance`, `list_ssh_keys`, `attach_ssh_key`. `create` takes the label. `set_label` backs `tag` and `extend`. `charges` wraps `show_invoices_v1(charges=True)` with a UTC-day range."
- Settled: exchange 1.

**49. SDK search adds default filters and prices 5 GB of disk**
- Location: §10.5, spec.md:579; §5.2, spec.md:383.
- Problem: `search_offers` merges its own filters unless told not to, and prices storage at 5.0 GB. rig's disk default is 50, so `dph_total` in the budget is low.
- Evidence: vastai 1.9.1 `api/offers.py:12-58`: `q = {"verified": {"eq": True}, "external": {"eq": False}, "rentable": {"eq": True}, "rented": {"eq": False}}` unless `no_default`; `q["allocated_storage"] = storage`.
- Fix: replace the right cell of :579 with "rig builds the query dict and passes it to SDK `search_offers` with `no_default=True` and `storage` set to the requested disk." Add to :383: "Search passes `storage = disk`, so `dph_total` covers the requested disk."
- Settled: exchange 1.

**50. A timed-out `create` can duplicate an instance**
- Location: §4.1 Behavior; §10.1, spec.md:532.
- Problem: The SDK retries every method, `PUT /asks/{id}/` included, on timeout or connection error. A create can succeed twice or succeed unseen. The docs say the API sets no `Retry-After`.
- Evidence: vastai 1.9.1 `api/client.py` retries on ConnectionError and Timeout, 3 attempts; docs "The API does not currently set standard rate-limit headers (for example `Retry-After`)"; :532 "handles `Retry-After` on 429s".
- Fix: add to §4.1 Behavior: "- `reserve` draws the lease id before `create` and writes it into the create label. `provider.py` sends `create` with SDK retries off. On a timeout or connection error, `reserve` lists instances for that `lease=` label every 5s for up to 60s. One match is the lease. More than one: keep the lowest instance id and destroy the rest. None: return `provider_error` with the lease id in the hint, and send no second create." In :532 replace "handles `Retry-After` on 429s" with "backs off on 429 and 502/503/504, honoring `Retry-After` when present".
- Settled: exchange 2.

**51. §10 dependency claims do not match the package**
- Location: §10.1, spec.md:532; §10.2, spec.md:538-544; §10.3, spec.md:559; §10.5, spec.md:578-579.
- Problem: vastai 1.9.1 pulls 19 runtime dependencies and imports its async and serverless clients eagerly, which threatens the 250ms target. `tomllib` needs Python 3.11. rig also needs local `ssh` and `rsync`. §10.1 credits the SDK with the query mini-language, while §10.5 says rig builds JSON with no mini-language.
- Evidence: wheel metadata lists aiohttp, cryptography, pillow, borb, pycares, psutil and others; `vastai/__init__.py` imports the serverless clients; :578 "SDK is plain `requests`"; :532 "the query mini-language"; :579 "no mini-language".
- Fix:
  - In :532 delete "the query mini-language,".
  - Replace the right cell of :578 with "SDK uses `requests` over HTTPS".
  - Add to §10.2: "rig needs Python 3.11 or newer, and `ssh` and `rsync` on PATH."
  - Add to §10.3: "`import vastai` loads aiohttp and the serverless clients. Measure it on day one. Over 250ms, `provider.py` calls the REST endpoints through `requests`."
- Settled: exchange 1.

**52. `label_counts` cannot give group sizes**
- Location: §8.0, spec.md:445.
- Problem: `label_counts` keys on the whole label, and every rig label carries a unique lease id, so each count is 1. The list endpoint pages at 25 rows.
- Evidence: OpenAPI `/api/v1/instances/`: "label_counts: Count of instances grouped by label."; "max 25 per page".
- Fix: replace :445 with "- Group sizes come from parsing `group=` in each `rig:` label. The list call follows `next_token`."
- Settled: exchange 0.

**53. The $0-balance behavior is stated as settled**
- Location: §2.1, spec.md:26; §10.5, spec.md:588.
- Problem: Vast's pages disagree on whether a $0 balance deletes instances. Stopped instances keep accruing storage and run no watchdog.
- Evidence: docs billing.md says instances stop and are scheduled for deletion after a grace buffer; docs faq/billing.md "your instances will be stopped automatically, but not destroyed".
- Fix: in :26 replace "at $0 Vast stops every instance and schedules it for deletion." with "at $0 Vast stops every instance. Vast's pages differ on later deletion, and stopped instances keep accruing storage."
- Settled: exchange 1.

**54. Provider claims that need a live test**
- Location: §10.5, spec.md:574-589; §6, spec.md:399; §12.
- Problem: These claims have no support in the OpenAPI spec, the docs or the 1.9.1 source.
- Evidence: the swarm's provider check verified the rest of §10.5 (create route, label PUT limit, balance, container key injection and self-destroy, `balance_threshold`, port syntax and cap).
- Fix: add to §12: "- Live tests before relying on: `CONTAINER_API_KEY` bound to the box's IP and sometimes absent; `/charges` clipping to a day range and its lag; `ports` absent until running; adding a port recreates the container; the `on-demand`/`ondemand` inconsistency (absent from 1.9.1); 404 meaning unauthorized; `label` length at create; `schedule_job` cadences below one hour; container-key `DELETE` while `loading`."
- Settled: exchange 1. The reviewer's broader fix was rejected (see Dropped).

### Nits

**55. §12 still asks a settled question**
- Location: §12, spec.md:601.
- Problem: §4.6 sets `run_ttl` to 2h, yet §12 still asks.
- Evidence: :601 "Should `run` without `--on` default to a longer TTL than `reserve`"; :255 "the profile's `run_ttl` (default 2h)".
- Fix: delete :601. Add to Settled: "- ~~Should `run` default to a longer TTL?~~ Yes. `run_ttl`, default 2h. See §4.6."
- Settled: exchange 0.

**56. Status example arithmetic**
- Location: §4.4, spec.md:213, :239.
- Problem: The $/HR column sums to 5.79, or 6.01 with the orphan. The footer says 6.21.
- Evidence: 2.40 + 0.82 + 0.82 + 0.82 + 0.55 + 0.38 + 0.22 = 6.01.
- Fix: change "burning $6.21/hr" at :213 and `"burn_per_hr": 6.21` at :239 to 6.01.
- Settled: exchange 1.

**57. Label example and lease name**
- Location: §8.0, spec.md:437; §4.1, spec.md:148; §4.3, spec.md:175.
- Problem: `created=1761699840` is 2025-10-29 while the JSON examples are 2026. `created + ttl == expires` implies zero boot. `l-7f3a` is `finetune` in §4.1 and §4.3 and `trainer` in §4.4 and §8.0.
- Evidence: :437 `created=1761699840;ttl=10800;expires=1761710640`; :148 `"name": "finetune"`; :199 `l-7f3a   trainer`.
- Fix: replace the :437 label with `rig:v1;lease=l-7f3a;name=trainer;owner=claude-code;group=exp42;created=1793235840;ttl=10800;expires=1793247000`. Change `"finetune"` to `"trainer"` at :148 and :175.
- Settled: exchange 1.

**58. The Clock row says the clock starts at `reserve`**
- Location: §3, spec.md:40; §4.1, spec.md:118.
- Problem: §3 starts the clock when the box runs.
- Evidence: :40 "Set at `reserve`, moved by `extend`."; :118 "Rents a box and starts its clock."
- Fix: :40 becomes "The lease's expiry timestamp. Set when the box starts running, moved by `extend`." :118 becomes "Rents a box. The clock starts when the box runs."
- Settled: exchange 1.

**59. §11 names a flag that does not exist**
- Location: §11, spec.md:596.
- Evidence: "Spot/interruptible instance handling beyond surfacing it as a flag".
- Fix: replace with "Spot/interruptible instances".
- Settled: exchange 1.

**60. Principle 6 vs `VAST_API_KEY`**
- Location: §2, spec.md:20; §5, spec.md:309, :317.
- Evidence: :20 "Nothing user-facing says \"Vast\"."; :309 "plus `VAST_API_KEY`".
- Fix: replace the second and third sentences of :20 with "Commands, flags, output fields and messages use rig terms. Credentials use the provider's variable, `VAST_API_KEY`."
- Settled: exchange 1.

**61. API key source**
- Location: §11, spec.md:597; §5, spec.md:309, :317.
- Problem: §11 says the key comes from "env or config", but config only names the env var.
- Fix: :597 becomes "Secrets management beyond reading the API key from the variable named by `api_key_env` (default `VAST_API_KEY`)". :309 becomes "Environment variables (`RIG_*` and the variable named by `api_key_env`)".
- Settled: exchange 1.

**62. Style: sentences that announce the next**
- Rule: no sentence whose only job is to announce the next sentence.
- Fix:
  - :9 "The whole tool fits in one sentence: **a box is a lease with a clock; jobs run on it.**" → "**A box is a lease with a clock; jobs run on it.**"
  - :24 delete "rig is deliberately lightweight, so its guardrails are conventions enforced by the CLI:".
  - :256 delete "rig warns before expiry:" and lift its three sub-bullets one level.
  - :351 "Users bring their own setup through startup hooks:" → "Startup hooks run a user script on each box."
  - :392 handled by finding 1.
  - :440 delete "Consequences:".
  - :529 "Python was chosen over TypeScript for these reasons:" → "rig is written in Python."
  - :546 "So:" → end the sentence at "ship together)." and start the list with "rig isolates the package:".
- Settled: exchange 1.

**63. Style: absolutes and editorializing**
- Rule: no absolutes or editorializing.
- Fix:
  - :532 "(which must not be retried)" → ", which rig does not retry"; delete "A zero-dependency TS client would own all of that forever."
  - :114 delete "This keeps partial-failure semantics out of rig entirely."
  - :406 "It is cron-shaped and thinly documented. Add it once its first-fire semantics are verified." → "Add it after a live test confirms its first-fire behavior (§12)."
  - :295 delete "Escape hatch."
  - :394 "uses exactly this call" → "uses the same call".
  - :443 "precisely" → delete the word.
  - :533 "Python is already on their machines and in their heads." → "Python is on their machines."
- Settled: exchange 0.

**64. Style: contrastive framing**
- Rule: no contrastive framing.
- Fix:
  - :22 heading "What rig guarantees, and what it only encourages" → "Guardrails".
  - :227 "No nested topology. Agents filter by `group` or `owner` themselves." → "Agents filter by `group` or `owner`."
  - :249 "`tag` never touches the clock on an existing lease; that is `extend`'s job." → "`tag` on an existing lease leaves the clock alone."
  - :568 delete "No binaries, no GitHub release assets."
- Settled: exchange 0.

**65. Style: parentheticals that restate**
- Rule: no parentheticals that restate the sentence.
- Fix: delete "(or loops in its skill)" at :114, "(default set is always opened, see below)" at :130, "(writes a label and installs the watchdog)" at :471, and "(adapter boundary exists, only Vast is implemented)" at :593.
- Settled: exchange 1.

**66. Style: stray sentence**
- Rule: say each idea once; no sentence without a job.
- Fix: delete :30 "The spec and the README say \"won't by accident.\"" and the blank line after it.
- Settled: exchange 1.

**67. Style: ideas stated more than once**
- Rule: say each idea once.
- Fix: keep the first statement and replace the rest with a section pointer:
  - Client-side budgets: keep :26; :588 right cell → "See §2.1."; :616 → "~~Is there an account-level hard cap?~~ No. See §2.1."
  - Extend write order: keep :408; :444 delete; :166 first sentence → "`extend` writes the expiry as §6 describes."
  - One lease never drives another: keep :53; :462 → "For mess, rig shows the state and gives the one-line fix."; delete "rig never auto-replaces." at :467.
  - Job at expiry: keep §4.6; delete the second sentence of :51; :468 right cell → "See §4.6."
  - Bulk extend budget: keep :113; :473 right cell → "See §4.0."
  - Boot bound: keep :50; :469 right cell starts "See §3."
  - Orphan definition: delete the :457 bullet.
  - Release scope: delete :523.
  - Pin version: delete :550.
- Settled: exchange 1.

**68. Style: bullets that read as paragraphs**
- Rule: short sentences; trim a paragraph bullet to the instruction.
- Fix: split :49, :133, :248, :365, :395 and :408 into one-idea sentences or sub-bullets after the gap fixes above land. For :49: "The clock starts when the instance leaves `loading`." / "`expires_at` is `start_date + ttl`." / "The first rig command that sees the instance running writes it (§6). `reserve` with wait does this before it returns; the sweep does it otherwise." / "After that only `extend` changes it."
- Settled: exchange 1.

## Disagreements

None. Every dispute settled by exchange 2.

## Dropped

- Reviewer C4 variant that made a working destroy key a precondition for auto-reserved jobs and returned `guard_unavailable`: user decision 3 (missing key means `guard: partial`; the sweep enforces).
- Reviewer C5 clock-revision field and cross-client serialization: withdrawn by the reviewer in exchange 2. Vast labels have no compare-and-set.
- Reviewer C34 blanket fix marking all of §10.5 unverified: the swarm verified most claims against the OpenAPI copy, docs and the 1.9.1 source. The reviewer accepted the narrower list in finding 54.
- Reviewer C37 rewrite of §12 :606-608 as "deferred validation": no rule behind it; the items are already open live tests.
- Reviewer C38 replacement of §10.3 :554: that text is the rationale the Settled entry points to; no style rule removes it. Its :532 rewrite is superseded by finding 51.
- Reviewer C26 clause partitioning the cache by account identity: user decision: batteries included.
- Swarm proposals to delete `--config -`, `--sync DIR`, `--startup -` and :410 as scope creep: no rule behind them; the definitional gaps in those features are covered by findings 13, 38 and 42.
- Swarm style items ", since jobs are longer than interactive sessions" (:255), ", so you can `ssh` in and look" (:365) and ", since the box is already billing" (:388): they give reasons and restate nothing; no rule applies.
- Swarm proposal that rig upload an oversized startup script over SSH: replaced in exchange 2 by the refuse-before-create rule in finding 41.

## Run

- Angles: command surface and errors (§4, §7); clock, states and enforcement (§3, §5.1, §6, §8); budget and configuration (§2.1, §5, §5.2); provider feasibility with web and package checks (§10, §6, §8.0); contradictions, open questions and style (whole spec).
- Agents: 5 Sonnet agents.
- Reviewer: sol (Codex).
- Exchanges: 2 of a cap of 3.
