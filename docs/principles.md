# Principles

Vasty does two things: provisioning comes with a TTL and cleans up after itself, and the API doesn't suck. Measure every change against those two lines.

## Build for the caller in front of you

- Name the caller, input or failing test that needs a change today. Without one, drop it.
- Make the smallest change that serves that caller. Reuse the local, branch or helper already in reach.
- Ground scope in a real scenario from a live run. Cut speculative items.

## One correct way to do each thing

- Verbs are cheap. Flags, duplicate paths and flag-combination rules are the cost.
- For every flag, ask whether another flag or config key already reaches the result, and whether it adds a combination rule. Merge or drop on a yes.
- Remove a flag before adding an escalation option.
- Stop cutting when a fresh agent would need a long or obtuse command chain for a common scenario.

## TTL bounds spend

- `max_price` times the TTL, plus prepaid credit, bounds spend per box. Add no account-level spend checks.
- `max_price` is an offer filter, the same kind of thing as `--vram`.
- Drop belt-and-suspenders guards that insure against what the TTL already covers.

## Guards are direct and deterministic

- Compute guards from inputs vasty already holds: rate cap, time cap, box count, Vast's reported balance. Skip projections and estimators.
- Keep guards that protect the TTL promise always on, with no config switch. The deferred sweep is one.
- Keep retries short and fixed, around 5 tries 60 s apart. The watchdog backstops the rest.

## Pass through the provider

- Return what the Vast API reports for balance, billing and offers.

## Fix the guarantee

- When a documented guarantee breaks, fix the cause.
- Point recovery hints at the safest action available at that stage.

## Code is the record

- The code and README are the record. Docs trail the code and get updated in passing.
- Spec files, loop outputs, validation reports and per-run test plans are cruft. Delete them once their items land.
- Edit the existing doc before creating a new one.
