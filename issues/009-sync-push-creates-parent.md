# `sync push` creates the destination's parent

**Type**: AFK

**Status:** ✅ Done, commit 691239f

## Parent

`docs/decisions.md`, row "`sync push` into a missing parent fails with rsync exit 11".

## What to build

`sync push` passes `--rsync-path` with `mkdir -p` of the destination's parent, so a push into a path whose parent is absent on the box succeeds.

## Acceptance criteria

- [ ] The rsync argv for `sync LEASE push SRC /workspace/a/b/` contains `--rsync-path` with `mkdir -p /workspace/a/b` followed by `rsync`
- [ ] `sync pull` argv is unchanged
- [ ] A destination of `/` or a bare path with no parent passes a plain `rsync` path

## Blocked by

None - can start immediately
