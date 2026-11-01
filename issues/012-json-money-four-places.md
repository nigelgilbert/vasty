# JSON money to four places

**Type**: AFK

**Status:** 🔲 Not started

## Parent

`docs/decisions.md`, row "JSON money rounds to cents".

## What to build

`to_jsonable` rounds Decimals to 0.0001. Human output stays at cents. This covers `cost`, `totals.credit` and `config show` `max_price`.

Run 5 returned `cost` 0.0 against a $0.003 charge and `max_price` 0.27 for a configured 0.272.

## Acceptance criteria

- [ ] `to_jsonable(Decimal("0.0034"))` returns 0.0034
- [ ] `status --json` on a lease costing $0.003 returns `cost: 0.003`
- [ ] `config show --json` with `max_price = 0.272` returns 0.272
- [ ] Human `status` still prints `$0.00` for that lease

## Blocked by

None - can start immediately
