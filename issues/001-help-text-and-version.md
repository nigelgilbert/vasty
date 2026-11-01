# Help text for every flag, plus `--version`

**Type**: AFK

**Status:** 🔲 Not started

## Parent

`docs/decisions.md`, row "Flags have no help text".

## What to build

Every flag on every verb gets one help line naming its unit and default. `ssh --help` shows the `-- COMMAND` positional. `sync --help` shows `push|pull SRC DEST` and `--delete`. `vasty --version` prints the installed package version.

Fresh agents in runs 2, 3 and 4 guessed `--cuda`, `--ttl` and the default image. The help text answers those guesses.

## Acceptance criteria

- [ ] `vasty VERB --help` for every verb prints a help line for each flag; a test walks the parser and fails on any flag with empty help
- [ ] Help for `--ttl`, `--cuda`, `--max-price`, `--image` and `--by` names the unit and the default
- [ ] `vasty ssh --help` shows `-- COMMAND`
- [ ] `vasty sync --help` shows `push|pull SRC DEST` and `--delete`
- [ ] `vasty --version` prints the version from package metadata and exits 0

## Blocked by

None - can start immediately
