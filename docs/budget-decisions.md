# Budget decisions, 2026-10-30

Two decisions from code review 0 on PR #1.

## 1. `spent_today` clamps at Vast's `start_date` only

`instance_start` in `src/vasty/budget.py` returns Vast's `start_date`, or None. The fallback to the label's `created` field is deleted.

Why. `reserve` writes `created` when it makes a box, so there it matches the start time. `tag` writes `created` when it adopts a box that already exists, so there it is the adoption time. The estimator read both as the start time and undercounted a tagged box by everything it ran before `tag`.

Scope. The fallback only ran when Vast omitted `start_date`. Vast sends it on every instance row. The undercount is bounded by one box's hourly rate over the gap since the last billing post.

Behaviour after the change. With no `start_date`, the estimate runs from the last billing post, so it errs high. `test_spent_today_ignores_label_created_without_start_date` asserts that.

## 2. `daily_budget` becomes a pass-through of Vast's figures

`daily_budget` and the spend estimator are removed. Filed as `docs/replace-daily-budget-with-vast-pass-through.md`, a follow-up to PR #1.

Why. Vast has no daily spending cap to defer to. The estimator guesses the spend between billing posts, and that guess needed two fixes in one live run. Vast already returns the numbers the guess approximates.

What `status` reports. `balance` and `credit` from `GET /users/current`, and today's billed charges from `GET /charges/`, as Vast returns them. The live run showed credit tracking real spend within a cent.

What stays. `max_price` filters offers by dollars per hour, and `ttl` ends the box. Per-box spend is the product. The account bound is the prepaid balance.

What goes. `budget_exceeded`, `budget_low`, `spend_source`, exit code 3 and `src/vasty/budget.py`. No account-level check replaces them. Revised 2026-10-30 in the second pass: the first draft kept an optional `min_credit` floor, which was a credit-minus-commitments projection on `reserve` and `extend`. It moved Vast's own $0 stop up by a configured amount and refused `extend` on a running job, so it was dropped.

The README section on `daily_budget` is rewritten around the per-box product and the pass-through fields.

## 3. Per-lease `cost` is Vast's billed amount or null

`lease_cost` in `src/vasty/views.py` returns the sum of Vast's charge rows for the instance, or null when none exist. `cost_source` goes with `spend_source`. The charges query starts at the earlier of today and the oldest active lease's `created`, so a lease that crossed midnight UTC reports its lifetime billing. `release` reports the same figure.

Why. The estimate blended billed rows with price times the gap since the last post, and the gap counted the unbilled image pull. Vast posts a row within minutes of a box running, so null covers the first minutes only. Decided 2026-10-30.
