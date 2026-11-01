# Create and wait failures leave no ghost

**Type**: AFK

**Status:** 🔲 Not started

## Parent

`docs/decisions.md`, rows "A Vast list timeout during reserve's readiness wait" and "A create that returns `success: false`".

## What to build

After a create that returns `success: false`, reserve lists instances by the lease label and destroys what it finds. It returns `provider_error` with `lease`, `instance_id` and `destroyed` in details. A create timeout keeps its recovery: adopt the labelled instance.

During the readiness wait, a refresh error writes one stderr line and the wait continues until the lease's clock. Ctrl-C still destroys a box this call created.

Every error raised after create names the lease and whether the box was destroyed.

Run 4 left an instance billing in `loading` after a `success: false` create. Run 3 destroyed a healthy box on one list timeout.

## Acceptance criteria

- [ ] A fake create returning `success: false` with a labelled instance present yields `provider_error` with `details.destroyed: true` and `details.instance_id` set, and the fake records one destroy
- [ ] A fake create returning `success: false` with no labelled instance yields `provider_error` with `destroyed: false`
- [ ] A create timeout followed by a labelled instance adopts it, as today
- [ ] One refresh error during the wait writes one stderr line; the wait continues and reserve returns `ok` when the box reaches `running`
- [ ] Refresh errors for the whole clock end with the lease's existing wait timeout error, naming the lease
- [ ] A test walks every error path after create and asserts `details.lease` and `details.destroyed` are present

## Blocked by

None - can start immediately
