# Live run 6: the fixes from runs 2 to 5 on real boxes

Run on 2026-11-01, 05:22Z to 06:44Z, Vast account 836500. An Opus agent drove the plan with a second Opus agent as the blind driver in phase 5. Spend $0.158 of the $3.00 cap. Every clock ran 20 minutes or shorter. The account was empty at the end with no follower process left.

Raw output lives at `/private/tmp/vasty-live-6/out/`: `report.md` has one line per step, `notes.md` the surprises, `ledger.md` the credit every 60 s, and `<phase>/NN-<verb>.{cmd,json,stderr,exit}` each command. Two files there hold API keys for vLLM endpoints that died with their boxes: `4/02r-serve.json` and `5/03-serve.json`. Redact them before copying anything into the repo.

## Verdict

PR #4 closed issues 001 to 015 against fakes. On real boxes, 14 of the 15 held. Issue 004's grace path fails: `stop` records a job as killed when the signal killed only its wrapper. Issue 006, which the plan listed as having no live trigger, met its trigger twice and passed both times.

| Issue | Fix | Result |
|---|---|---|
| 001 | help text, `--version` | Pass |
| 002 | image CUDA floor, `vllm_missing` hint | Pass |
| 003 | one job entry shape, frozen `duration_s` | Pass |
| 004 | `vasty stop` | Fail on the grace path, pass otherwise |
| 005 | `box_unreachable` and `expiring_*` fixes | Pass |
| 006 | create and wait failures leave no ghost | Pass, two live triggers |
| 007 | status fields by state | Pass |
| 008 | owner scope | Pass |
| 009 | `sync push` creates the parent | Pass |
| 010 | one follower per lease | Pass |
| 011 | `previous_expires_at` | Pass |
| 012 | JSON money to four places | Pass |
| 013 | API key from the vastai file | Pass, every networked call |
| 014 | `serve_failed` hint for error 804 | Pass, on retry |
| 015 | README follows the code | Pass, blind driver made zero errors |
| review | `run --on` expiry line rounds up | Pass |

## Setup

- `VAST_API_KEY` unset in every shell. Every call read `~/.config/vastai/vast_api_key`.
- Config: ttl 15m, run_ttl 15m, gpu 3060, max_price 0.272, warn_before_expiry 5m, disk 16, base image. Profile `vllm`: the vLLM image, gpu "5060 Ti", max_price 0.40, ttl 20m.
- Owners: `run6` for the manager, `agent-b` and `victim` in phase 3, `agent-a` for the phase 5 driver. `agent-b` was a mistake; see phase 3.
- Offer pool: 29 RTX 3060 offers, 6 of the top 10 on CUDA 12.x. 37 RTX 5060 Ti offers, cheapest $0.1055/hr at CUDA 13.2.
- Start credit 18.7133.

## Phase 0: local checks

No spend. All pass.

- `vasty --version` prints 0.1.0, matching `pyproject.toml`.
- Every flag on every verb has a help line. `--ttl`, `--cuda`, `--max-price`, `--image` and `--by` name a unit and a default. `ssh --help` shows `-- COMMAND`. `sync --help` shows `push|pull [--delete] SRC DEST`. `stop` is listed.
- `config show`: `api_key` source is the vastai file, `cuda` 12.6 from the image, `max_price` 0.272 in JSON. `--profile vllm` gives cuda 13.0 from the image. `--cuda 12.4` gives source `flag`.
- `HOME=$(mktemp -d) vasty status` returns `auth_missing` naming both `VAST_API_KEY` and the file path.
- `status --everyone` on the empty account returns `leases: []`, exit 0. `release --everyone` and `extend --everyone` return `invalid_arguments`.
- `totals.credit` 18.7133 matches `vastai show user` to four places.

## Phase 1: one box, the lifecycle fixes

Box `p1`, RTX 3060 at $0.0778/hr. Spend $0.010.

- `reserve --no-wait` and `status` while pending: `expires_at` and `ttl_remaining_s` null, `log_tail: []` present. Running 40 s later.
- One follower after reserve, the same pid after `extend --by 5m`. The extend returned `previous_expires_at` equal to the prior clock and `expires_at` 300 s later. The label kept `ttl=900`.
- `sync push fx/ /workspace/a/b/c/` into a missing parent: exit 0. `ssh ls` listed the fixtures. `sync pull` returned a byte-identical file.
- Two detached jobs. `status` showed two entries with keys `job`, `cmd`, `state`, `exit`, `duration_s` and `busy: true`. `stop p1` with two live jobs returned `invalid_arguments` listing both. `stop p1 j-1` returned `killed`, exit 143, `duration_s` 26, and a later `status` kept those values.
- `stop p1` on `stubborn.py`, which ignores TERM: returned after 9 s with `killed`, exit 143, command exit 0. The plan expected `running` with exit 2. See Defects.
- Watchdog killed on the box, then `extend --to 4m`. The result carried `expiring_with_running_job`, "4m left", fix `vasty extend l-400d6072 --by 15m`. `run --on p1 -- hello.py` 20 s later printed `expires in 4m` on stderr and the same warning. Both round up.
- No vasty command from 05:28:44Z until the box left. New expiry 05:32:24Z. The provider listed it at 05:32:17Z and not at 05:32:33Z. The follower alone destroyed it within 9 s of a clock shortened mid-sleep.
- `status --verbose` afterwards: `expired`, `ttl_remaining_s` null, no `actual_status`, `log_tail: []`, the stubborn job `unknown` with `duration_s` 262. A second sample 60 s later read 262. The follower was gone 85 s after the sweep.

## Phase 2: release

Boxes `p2` and `p3`. Spend $0.006.

- `run --on p2 --sync fx -- short.py` exited 3 with `duration_s` 20. `status` listed the job with `duration_s` 20.
- `release p2` with a live sleeper: the entry read `killed`, `exit: null`, `duration_s` 11. `cost` 0.001 for 67 s up. `destroy_pending: true`. The follower pid was gone 5 s later.
- Two `status --verbose` calls 60 s apart: `released`, `ttl_remaining_s` null, no `actual_status`, `duration_s` 11 both times.
- `p3` destroyed by hand with `vastai destroy instance`, then `release p3`: `already_absent: true`, `uptime_s` 16, `cost` null, `jobs: []`. No `destroy_pending` key. The next `status` listed no p3 and no orphan.

## Phase 3: owners

Boxes `ft` under `run6` and `victim` under `victim`. Spend $0.046.

- Under `agent-b`, `status ft` returned agent-b's own expired lease from run 5, exit 0. The shared cache at `~/.local/state/vasty/leases.json` keeps 24 h of history, and run 5 used the same owner name. Rerun under a never-used owner `agent-c`: `lease_not_found`, `details.matches` holding run6's ft, hint `Run vasty status l-541fc49c.`
- `status --everyone` under agent-b: exit 0, ft listed under run6.
- `status --verbose` under agent-b listed agent-b's run 5 history. `--owner run6` listed p1, p2 and p3. `--everyone` listed 31 history rows across every owner of the last 24 h. Active leases appeared in all three.
- `victim` reserved with an 8 m clock, all guard layers ok. Followers killed on the laptop, watchdog killed on the box. No vasty command from 05:42:55Z to 05:51:37Z. The provider still listed victim 63 s past its 05:50:31Z expiry.
- `status --everyone` under agent-b: `swept` held `{lease l-b8eb5a38, name victim, owner victim, expired_at 05:50:31Z, ok true}`. Victim left the provider 10 s later.
- `release ft`: `uptime_s` 711, `cost` 0.013, `destroy_pending: true`. Account empty at 05:51:55Z.

## Phase 4: the vLLM path

Boxes `p4`, `n`, `sv` twice, `old`. Spend $0.051 across both passes.

- `serve --on p4 --model M --ttl 20m --name n`, as the plan wrote it, returned `invalid_arguments`: `--on` takes no creation flags. `serve --on p4 --model M` returned `vllm_missing` with the hint to `pip install vllm` on the lease.
- `serve --model M --ttl 20m --name n` with no `--on` auto-reserved a base box, returned `vllm_missing` with the hint `vasty reserve --profile vllm --ttl 20m --name n --cuda 13, then vasty serve --on n --model M`, and destroyed the box it had made. This matches issue 002's acceptance line.
- `serve --profile vllm --name sv`: the auto-reserved 5060 Ti sat in `loading` for 15 minutes pulling the image. The label read `ttl=900`. Serve used `run_ttl`, and the profile's 20 m ttl never reached it. The clock, based at create because the box never ran, expired at 06:09:40Z. Serve returned `box_unreachable` "Lease l-f5f5d4a1 ended before it became ready", exit 2, `destroyed: false`, and the sweep destroyed the box. Cost 0.001, since a loading box bills no GPU time. The provider listed nothing 9 s and 26 s later.
- Retry with `--ttl 20m --max-price 0.30`: a 5060 Ti at $0.3379/hr on CUDA 13.2 served in 10 m 45 s. `/v1/models` listed the model. A chat completion answered. `stop sv` returned the serving job `killed`, exit 143, `duration_s` 230. `status` and `release` kept that record. `release` reported `uptime_s` 239, `cost` 0.008.
- `p4` left the provider within 10 s of its own 15 m clock while the serve was waiting, with no manager command.
- `reserve --name old --image vllm/vllm-openai:v0.32.0 --cuda 12.4` on the 3060 pool: Vast answered `success: false` with an empty body and still created a row carrying the lease label, instance 58626392. Reserve found it, destroyed it, and returned `provider_error` with `details {lease, instance_id 58626392, destroyed true}` in 3 s. The provider listed nothing 8 s and 63 s later. This is run 4's ghost, and the fix from issue 006 handled it.
- Retry after phase 5: `old` came up on a 3060 at CUDA 12.8, driver 570.172.08. `serve --on old --model M` returned `serve_failed` in 64 s, exit 2, with "Error 804: forward compatibility was attempted on non supported HW" in `log_tail` and the hint "The host driver is below the image's CUDA. Serve on a new box: vasty serve --model Qwen/Qwen2.5-0.5B-Instruct --image vllm/vllm-openai:v0.32.0 --cuda 13." Released at `cost` 0.002.

## Phase 5: a fresh agent with the help text

Driver: Opus, `VASTY_OWNER=agent-a`, given the task line, the README "For agents" section and the help output. Finished in 17 of 40 minutes. Spend $0.045.

Commands in order: `status`, `status l-400d6072`, `serve --profile vllm --model Qwen/Qwen2.5-0.5B-Instruct --name qwen --ttl 20m --disk 40`, `status qwen`, a curl chat completion, `stop qwen`, `release qwen`, `status --all`, `status l-609d39ee`. Nine commands, nine exit 0.

- Zero `invalid_arguments`, zero `no_offers`. Runs 2 to 4 saw every fresh agent guess `--cuda`, `--ttl` and the image.
- One guessed flag, `--disk 40`, because no doc names the disk the vLLM image needs. The 16 GB default was never tested.
- The serve blocked 14 m 42 s with nothing on stderr: about 8 m boot and 6 m of vLLM compile and graph capture. The driver polled `status qwen` from a second shell and read `log_tail`.
- The chat answered "Paris". A request without the key got 401.
- `stop qwen` with no JOB: `killed`, exit 143, `duration_s` 397. Runs 2 and 4 used `ps` and `kill` over ssh here.
- `release qwen`: `uptime_s` 408, `cost` 0.035, `destroy_pending: true`. The driver read that as unconfirmed and ran `status --all` to see the box gone.
- The driver ran the fix on the `expired_with_running_jobs` warning it saw for run6's p1, found another owner's expired lease, and left it alone.

## Defects

### `stop` records the wrapper's exit as the job's

`start_script` in `remote.py` writes `run.sh`, which traps INT TERM HUP and runs `bash $J/script`. The script runs the job. `stop` sends TERM to the process group. `run.sh` ignores it, the inner bash dies with 143, `run.sh` records 143, and the tmux session closes. A job that ignores TERM survives that signal and dies only from the HUP tmux sends at teardown. The record says `killed`, exit 143, after 9 s. A job that ignores TERM and HUP outlives its own `killed` record. The unit test for the grace path passed against a fake with no wrapper.

Fix options: `exec` the job from `script` so it is the direct child and its exit is the one recorded, or have `signal_and_wait` confirm the process group is empty before accepting a `killed` record. Issue 004 reopens on this.

### Profile `ttl` never reaches `run` or `serve`

`serve --profile vllm` took the profile's image, gpu and max_price and the `run_ttl` clock. `config show --profile vllm` reports the profile's ttl. A caller who writes `ttl = "2h"` in the profile gets 15 minutes. Decide whether `run_ttl` falls back to a profile ttl, or whether `config show --profile` stops showing a ttl that serve ignores.

### A history warning reaches every owner's plain `status`

`expired_with_running_jobs` on a lease already in history has the fix `vasty status LEASE`, which changes nothing. It appeared in run6's untargeted `status` and in agent-a's, which listed no leases. The blind driver ran the fix. The warning cleared on its own once the lease aged out of the sample. Decide whether history leases emit warnings at all.

### `release` results and the README disagree

- `release` on a box already gone returns `already_absent: true` and no `destroy_pending` key. The README result row lists `destroy_pending` for single-lease release.
- `release` on an expired lease returns `already_absent: true`, exit 0. The README error table lists `lease_expired` for a lease in history.

Docs follow code: update both rows unless the code is the thing to change.

### `serve` prints nothing while it waits

Two waits of 15 minutes passed with no stderr line. One was a host that never left `loading`; the other was a healthy boot plus vLLM startup. A caller cannot tell the two apart without a second shell. One line at `running` and one at each minute of the readiness wait would do.

## Observations

Recorded, no action proposed.

- A job alive at expiry reads `state: unknown` in history. `release` marks such jobs `killed`. Issue 003 chose this; the README could say it.
- `cost` at release was 0.001 and 0.003 seventy seconds later. History `uptime_s` read 408 at release and 416 eight seconds later. Charge rows and the destroy confirmation land after the release call returns. `destroy_pending: true` already says so.
- An owner's expired lease shadows another owner's active lease of the same name. `status ft` under agent-b found agent-b's dead ft and said nothing about run6's live one. The README rule "a name resolves under the current owner" covers it.
- `release --everyone` and `extend --everyone` hint `vasty status --all --everyone`.
- `run --help` and `serve --help` list `--no-wait` without saying auto-reserve rejects it. Help shows built-in defaults, and the effective config can differ.
- The `vllm_missing` hint under `--on` says to `pip install vllm` on the lease. The auto-reserve hint names the profile and `--cuda 13`.
- A slow image pull can consume a short clock. The box never reached `running`, so the clock ran from create. The README's 2 h default for `run` and `serve` hides this; the test config's 15 m exposed it. Run 2 saw a 708 s reserve on the same image.
- `swept` entries carry `owner`. `status --everyone` without `--all` works. Both landed in this PR and both were used by the phase 3 commands without comment.

## Plan errors

- Phase 4 step 01 combined `--on` with `--ttl` and `--name`, which `--on` rejects. The manager ran the auto-reserve form instead, which is the form issue 002 specifies.
- Phase 1 step 20 wrote the warning `fix` as a list. The code returns one string, as the README says.
- Phase 0 step 3 expected `$0.27` in the table. The table prints `0.27` and no doc sets a format.
- Phase 3 reused the owner `agent-b` from run 5. Give every live run owner names it has never used, or a fresh state dir.
- The driver prompt pointed at `out/5/help.txt`; the file was at `out/0/help.txt`. The driver regenerated it with `vasty --help`.
- `pgrep -af` on macOS matches the calling shell. Count followers with `ps aux | grep "[s]weep --follow"`.

## Spend

| Phase | Boxes | Drop |
|---|---|---|
| 0 | none | 0 |
| 1 | p1 | 0.010 |
| 2 | p2, p3 | 0.006 |
| 3 | ft, victim | 0.046 |
| 4 | p4, n, sv ×2, old (rejected) | 0.040 |
| 5 | qwen | 0.045 |
| 4 retry | old | 0.011 |
| total | | 0.158 |

Drops are credit readings at phase boundaries. Charge rows land a minute or two after a box leaves, so some of each phase's cost shows in the next row.

Final credit 18.5549. `vastai show instances --raw` returned `[]` at 06:44:08Z. `release --all` under run6, agent-b, victim and agent-a each returned no results.

## Next

1. Reopen issue 004 for the stop wrapper and add a unit test whose fake job survives TERM.
2. Add decision rows for the profile ttl, the history warning, the two README release rows, and serve progress output.
3. Redact the two endpoint keys, then decide what of `/private/tmp/vasty-live-6/out/` to keep.
