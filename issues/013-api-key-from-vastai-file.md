# API key from the vastai CLI file

**Type**: AFK

**Status:** 🔲 Not started

## Parent

`docs/decisions.md`, row "`vasty` reads the API key from the env var only".

## What to build

When the env var named by `api_key_env` is unset, vasty reads `~/.config/vastai/vast_api_key`. `config show` reports which source won. `auth_missing` names both sources.

Every call in run 2 set the key inline. Every run 3 worker loaded it from that file by hand.

## Acceptance criteria

- [ ] With the env var unset and the file present, a provider call authenticates with the file's key
- [ ] With both set, the env var wins
- [ ] `config show` names the winning source, the env var name or the file path, and never prints the key
- [ ] With neither set, `auth_missing` names the env var and the file path

## Blocked by

None - can start immediately
