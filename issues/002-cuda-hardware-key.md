# `cuda` hardware key

**Type**: AFK

**Status:** ✅ Done in 8e922bf

## Parent

`docs/followups-plan.md`, step 1b item 1. Decision in `docs/filter-offers-on-host-cuda.md` and serve decision 1 of `docs/serve-decisions.md`.

## What to build

Add `cuda` as a hardware key beside `vram` and `gpu`. It is the minimum host `cuda_max_good`, a number such as `13` or `12.8`. It appears in `DEFAULT_KEYS`, `PROFILE_KEYS`, `FLAG_KEYS` and `SHOWN`, as `Settings.cuda: float | None`, as `VASTY_CUDA`, and as `--cuda FLOOR` on `reserve`, `run` and `serve`. `config show` and `config set` handle it like the other number keys.

`OfferQuery` gains `cuda: float | None`. `build_offer_query` adds `"cuda_max_good": {"gte": cuda}` when it is set and leaves the dict unchanged otherwise. Vast applies the filter server-side, so `rank_offers` needs no change. The `no_offers` message and hint name `cuda` beside `max_price` and `region` when a floor is set.

README: `--cuda` joins the hardware flags line, and one line says to read an image's floor from `NVIDIA_REQUIRE_CUDA` in `docker inspect IMAGE`.

Out of scope: a cached lease CUDA field, a `cuda_too_low` refusal on `serve --on`, and a model entry key. A host under the floor fails inside a minute and `serve_failed` carries the log tail.

## Acceptance criteria

- [ ] `build_offer_query` with `cuda` 13.0 emits `{"cuda_max_good": {"gte": 13.0}}`; without it the dict has no `cuda_max_good` key.
- [ ] `reserve --image vllm/vllm-openai:v0.32.0 --cuda 13` sends the filter to the fake provider.
- [ ] `reserve --profile vllm` with `cuda = 13` in the profile sends the filter.
- [ ] `VASTY_CUDA=13 vasty reserve` sends the filter and `config show` reports its source as `env`.
- [ ] `reserve` with no `cuda` in any layer sends no `cuda_max_good` key.
- [ ] `no_offers` with a floor set names `cuda` in the message and the hint.
- [ ] `--cuda` parses on `reserve`, `run` and `serve`, and `--cuda abc` raises `invalid_arguments`.
- [ ] The README hardware flags line lists `--cuda FLOOR`, and `grep -n NVIDIA_REQUIRE_CUDA README.md` returns one line.
- [ ] `uv run pytest` and `uv run mypy` pass.

## Blocked by

None - can start immediately
