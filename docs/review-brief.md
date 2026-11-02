# Review brief

Brief for any reviewer of a vasty plan or diff: swarm validate, Codex, Astra, or a single review agent. Judge against [principles.md](principles.md).

## Raise

- Bugs: wrong behavior, crashes, lost leases, boxes left billing.
- A broken guarantee: expiry, cleanup, the error contract or JSON output shape.
- Surface growth: a new flag, config key, duplicate path or combination rule. Name the caller that needs it, or flag it for removal.
- Code that re-derives what the Vast API already reports.

## Skip

- Insurance against cases the TTL already bounds.
- Hardening, keyword arguments or branches with no current caller or failing test behind them.
- A doc that disagrees with the code. Judge the code on its merits and update the doc line in the fix.
- Cosmetic changes outside the defect or task in scope.
- Test hardening with no regression behind it.

## Each finding

- One finding per item, in plain language an engineer can act on without opening the code.
- State the caller or input that triggers it and what goes wrong.
- Rank by severity. Cap the list at the findings that change behavior.
- End with what you checked and declined, one line each.

## Process

- Run the full validate swarm on a branch's first review pass. Later passes get a single code review.
- Astra is billed. Run it only when Nigel asks.
- A finding list is input to a decision. Accept, decline or defer each one by name.
