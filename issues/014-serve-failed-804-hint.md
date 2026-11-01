# `serve_failed` names the fix for error 804

**Type**: AFK

**Status:** 🔲 Not started

## Parent

`docs/decisions.md`, row "`serve --on` a vLLM box on a 12.x host returns `serve_failed`".

## What to build

When a `serve_failed` `log_tail` holds `Error 804`, the hint reads: the host driver is below the image's CUDA; serve on a new box with `--image IMAGE --cuda 13`, keeping the caller's `--model`, `--ttl` and `--name`. #002 covers the reserve path; this covers `serve --on`.

## Acceptance criteria

- [ ] A fake vLLM log containing `Error 804` yields `serve_failed` with a hint containing `--cuda 13` and the caller's `--model`, `--ttl` and `--name`
- [ ] A `serve_failed` without `Error 804` keeps today's hint
- [ ] README error table shows the 804 hint

## Blocked by

None - can start immediately
