# README and skill text pass

**Type**: AFK

**Status:** 🔲 Not started

## Parent

`docs/followups-plan.md`, step 3. Agent guidance from `docs/box-reuse-decisions.md`.

## What to build

Rewrite the pitch to two lines: provisioning comes with a TTL and cleans up after itself, and the API doesn't suck. "Bounded spend" comes off the promise list. `max_price` is described as an offer filter beside `--vram`, and the sentence that introduces leases drops the daily budget.

Bring the `status` documentation up to date in one pass: `balance`, `credit`, `charges_today` and `burn_per_hr` in totals, `busy`, `gpus` and `vram_gb` on each lease, `cost: null` before the first charge row, `uptime_s: null` before the first `running` sample, and `--cuda` in the hardware flags.

Add the agent guidance under "For agents". Run `vasty status` before reserving. Reuse a lease with `--on` when it is yours, `state` is `running`, `busy` is false, `gpu`, `vram_gb` and `gpus` cover the job, and `ttl_remaining_s` covers the job or `extend` can. `run --on` leaves the lease up after the job. Auto-reserved attached `run` releases it. The "For agents" section is the skill text.

The warning codes line gains `idle_box_available` and loses `budget_low`. Non-goals gains account-level spend limits. The result shapes table and the error table match the code after #001, #002, #003, #005 and #007.

## Acceptance criteria

- [ ] `grep -n "Bounded spend\|daily budget\|daily_budget\|budget_low\|cost_source\|spend_source\|model_unknown\|--quant" README.md` returns nothing.
- [ ] `grep -c "idle_box_available" README.md` returns at least 1.
- [ ] The Non-goals line names account-level spend limits.
- [ ] The README intro states the two-line pitch and names `max_price` as an offer filter.
- [ ] The "For agents" section contains the reuse guidance with `busy`, `vram_gb`, `gpus` and `ttl_remaining_s` by name.
- [ ] Every field named in the result shapes table exists on the matching dataclass in `models.py`, checked by reading the table against the file.
- [ ] Every code in the error table exists in `EXIT_CODES`, and every code in `EXIT_CODES` appears in the table.

## Blocked by

- #001
- #002
- #003
- #005
- #007
