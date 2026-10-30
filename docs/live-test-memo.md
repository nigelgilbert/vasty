# Live test memo, 2026-10-29

Interpretation of [live-test-report.md](live-test-report.md). The report records what happened. This memo says what it means and what to do.

## Outcome

The core product works on real hardware. Lifecycle, clock, run, sync, owner and group checks all passed. Twelve boxes were created and all twelve are gone. Spend was $0.094 against the $5.50 ceiling. Phase 5, `serve`, failed on a dependency pin. One further defect surfaced in phase 1 and is unfiled.

## What the run proved

- All three guard layers hold. The on-box watchdog destroyed four boxes on its own, 4 to 31 seconds after the clock. The laptop sweep destroyed a box whose watchdog had been killed. A shortened clock from `extend --to` was honored after the watchdog's sleep.
- The container key reads its own instance row and DELETEs a running instance. These were the plan's open questions.
- The orphan flow works end to end. A box created with `vastai create` showed as an orphan, `tag` gave it a full guard, and the watchdog destroyed it on schedule.
- Owner scoping holds. `release --all` under another owner released nothing.
- `ports` is null until `actual_status` is `running`, then arrives with it.

## Defects

### 1. `serve` fails on every model with `rope_scaling`

Fixed in PR #1. The vllm 0.6.3 pin leaves transformers open, pip resolves transformers 5.22, and vLLM asserts before the model downloads. This blocks the sub-agent endpoint use case. Fix first.

### 2. `spent_today` bills every live box from midnight on a fresh day

Fixed in PR #1. Phase 1 reported `spent_today` 1.5 and `remaining_budget` 4.5 after one cent of real spend. The report calls this the plan's section 2 caveat. It is a code defect.

`spent_today` in `src/vasty/budget.py` estimates each live instance from `covered_through`. With no charge rows yet, `parse_charges` sets `covered_through` to the day start, so a box created minutes ago is billed for the whole day so far. `lease_cost` in `src/vasty/views.py` clamps the same gap at the lease's `created` time. The account total skips that clamp.

Consequence: under the default $5 daily budget, the first box of the day on a $0.25/hr GPU projects over budget late in the UTC day and `reserve` refuses. Fix: clamp each instance's estimate at its start time. Use the label's `created` for vasty leases and Vast's `start_date` for orphans.

## Design questions

- `status` with no selector hides expired leases. The design lists active leases by default and keeps expired leases in history for 24 hours, so this is as designed. Decide whether agents should see what just expired in the default list.
- The builtin model entry names `Qwen/Qwen3-72B-Instruct`, which does not exist on Hugging Face. Qwen3 dense sizes stop at 32B. The README's sub-agent example uses this name. Candidate replacement: `Qwen/Qwen3-32B-AWQ`, vram 24, which fits a 24 GB card.
- Decided 2026-10-29: `serve` runs the vLLM the image ships and the venv install is deleted. Two Fable judges and GPT-6 Astra each read the README independently and picked this over honoring a preinstalled vLLM beside the venv, on Light, Bounded spend and Agent-first I/O. Train-then-serve is two boxes.
- `serve_failed` returns `details.exit` only. The plan expected the log tail in `details.output`. The design promised neither. Adding the tail saves an ssh round trip at the moment an agent is stuck. Recommend adding it.

## Cosmetic

- The guard file on a healthy box is empty. `onstart` writes only missing layers, so this is correct.
- The label's `ttl=` keeps its original value after `extend`. Expiry reads `expires=`, so nothing consumes the stale value.
- `tag` on a box whose key is already attached prints `SSH key already associated with instance` on stderr and exits 0. Consider suppressing that one message.

## Limits of the evidence

- Every phase ran on RTX 3060s at $0.06 to $0.08 per hour. Cost assertions passed with a $0.02 tolerance against costs of $0.01 to $0.03, so they verify little. The watchdog and sweep timings are the meaningful numbers.
- The phase 1 box-ready check ran 10 minutes late because of a poll-script bug. The earliest point at which the watchdog lands is measured only by phase 2a, where it was present when blocking `reserve` returned.
- Boot times ran 26 seconds to 4m13s, driven by image pulls. A 4 minute boot consumes half of an 8 minute TTL. This matters for the `run` auto-reserve path on a cold host.

## Order of work

1. File and fix the `spent_today` clamp.
2. Fix the vllm pin and rerun phase 5 alone.
3. Decide the two design questions.
