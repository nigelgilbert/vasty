# Budget decisions, 2026-10-30

Two decisions from code review 0 on PR #1.

## 1. `spent_today` clamps at Vast's `start_date` only

`instance_start` in `src/vasty/budget.py` returns Vast's `start_date`, or None. The fallback to the label's `created` field is deleted.

Why. `reserve` writes `created` when it makes a box, so there it matches the start time. `tag` writes `created` when it adopts a box that already exists, so there it is the adoption time. The estimator read both as the start time and undercounted a tagged box by everything it ran before `tag`.

Scope. The fallback only ran when Vast omitted `start_date`. Vast sends it on every instance row. The undercount is bounded by one box's hourly rate over the gap since the last billing post.

Behaviour after the change. With no `start_date`, the estimate runs from the last billing post, so it errs high. `test_spent_today_ignores_label_created_without_start_date` asserts that.

## 2. `daily_budget` becomes a pass-through of Vast's figures

`daily_budget` and the spend estimator are removed. Filed as `issues/replace-daily-budget-with-vast-pass-through.md`, a follow-up to PR #1.

Why. Vast has no daily spending cap to defer to. The estimator guesses the spend between billing posts, and that guess needed two fixes in one live run. Vast already returns the numbers the guess approximates.

What `status` reports. `balance` and `credit` from `GET /users/current`, and today's billed charges from `GET /charges/`, as Vast returns them. The live run showed credit tracking real spend within a cent.

Guards that stay. `max_price` caps dollars per hour per box at `reserve`. An optional `min_credit` floor refuses `reserve` and `extend` when credit minus the remaining commitment of live leases would drop under it. With no `min_credit` set, nothing blocks.

What goes. `budget_exceeded` on projected spend, `budget_low`, `spend_source`, the `covered_through` arithmetic and most of `src/vasty/budget.py`. The README section on `daily_budget` is rewritten around `min_credit`.

Known limit. On an account with auto top-up, credit never runs out, so `min_credit` never triggers and `max_price` is the only guard.
