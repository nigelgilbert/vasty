# README follows the code

**Type**: AFK

**Status:** 🔲 Not started

## Parent

`docs/decisions.md`, rows "README says `pending` until the hook exits 0", "README result tables and the `run --sync` destination lag the code", and the Rejected rows that end "Document it".

## What to build

README changes for behaviour the code already has. Job entry fields and the `stop` result land with #003 and #004.

- Result tables: `error` and `released` on attached `run`, `model` on `serve`, per-lease fields on bulk `release`.
- Where `run --sync DIR` lands and the remote working directory.
- Offer order: reliability, then download bandwidth, then price, then id.
- The clock starts when Vast reports `running`; the startup hook runs on it.
- `pending` lasts while the hook runs. A hook that exits nonzero leaves the box `running` with `startup_failed`. The phrase "until it exits 0" goes.
- Swarm workers set `VASTY_OWNER`.
- Plain `status` lists every owner's active leases. `totals.live_mine` counts the caller's.
- The vLLM example says to pass `--gpu` on a mixed pool. Run 2's `--profile vllm` picked a Tesla V100, and vLLM 0.32 ships no Volta kernels.

## Acceptance criteria

- [ ] Each bullet above has a matching README line; a reviewer checks the list against the diff
- [ ] `grep -c "until it exits 0" README.md` returns 0
- [ ] Every field named in the README result tables appears in the corresponding result dataclass, checked by a test or a one-off script

## Blocked by

None - can start immediately
