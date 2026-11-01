# Owner scope reads clearly

**Type**: AFK

**Status:** ✅ Done, commit 490f134

## Parent

`docs/decisions.md`, rows "Untargeted `status --verbose` lists every owner's history", "`status --everyone` without `--all` is `invalid_arguments`", "`lease_not_found` for a name other owners hold", "`swept` entries carry no owner".

## What to build

`status --everyone` alone reads as `--all --everyone`. `release` and `extend` keep requiring `--all` or `--group`.

Untargeted `status --verbose` lists the current owner's history, or `--owner O`'s. `--everyone` widens it to the account. Active leases keep listing every owner. The README line "History states show when named directly" changes to say this.

`lease_not_found` for a name other owners hold lists their active lease ids in `details.matches` and hints `vasty status <id>`.

Each `swept` entry carries `owner`.

## Acceptance criteria

- [ ] `vasty status --everyone` returns `ok` with every owner's leases
- [ ] `vasty release --everyone` still returns `invalid_arguments`
- [ ] `status --verbose` with two owners' history in the cache lists only the caller's; `--owner B` lists B's; `--everyone` lists both
- [ ] `status NAME` where NAME is active under another owner returns `lease_not_found` with `details.matches` holding that lease id and a hint naming it
- [ ] Every entry in `swept` carries `owner`
- [ ] README owner section describes the history scope and the `--everyone` shorthand

## Blocked by

None - can start immediately
