# Live run before merge

**Type**: HITL (spends money on Vast; needs Nigel's go and a spend cap before any box is created)

**Status:** 🔲 Not started

## Parent

`docs/followups-plan.md`, step 4.

## What to build

Run the serve path and the new fields against Vast, with the cap Nigel sets. Cover:

- the README serve example as written, `vasty serve --profile vllm --model Qwen/Qwen3-14B-AWQ --ttl 1h`, on a 24 GB CUDA 13 host, through to one `/v1/chat/completions` call with a long prompt, so the README can state the context it served and the load time for the weights;
- `serve ... -- --max-model-len 16384` passing through to the job, read from the job's `cmd` and the vLLM log;
- `uptime_s` against the balance ledger, comparing the first `running` sample with the GPU hours Vast bills;
- per-lease `cost` going from null to billed within the first minutes;
- `idle_box_available` on a second `reserve` while the first box sits idle;
- two failure paths, driven by an agent reading only the error objects: `serve --on` a box reserved with the vLLM image and no `cuda` floor that landed on a 12.x host, and a bare `serve --model X` with no profile. Record whether the agent recovers from `serve_failed` with its log tail and from `vllm_missing` with its hint. A miss on either is the evidence for `cuda_too_low` or a builtin `vllm` profile, both deferred.

Record the run in `docs/live-test-report.md` with the commands, the JSON returned and the ledger lines, in the style of the earlier phases. Fill in the README context number from the result.

Then delete `docs/filter-offers-on-host-cuda.md`, `docs/uptime-counts-the-image-pull.md`, `docs/replace-daily-budget-with-vast-pass-through.md`, `docs/followups-plan.md` and the issue files this PR closes, including this one. The decision docs and the live test docs stay.

## Acceptance criteria

- [ ] Nigel's go and the cap are recorded at the top of the new report section before the first `reserve`.
- [ ] `docs/live-test-report.md` has a section for this run covering the six items above, each marked PASS or FAIL with the JSON returned.
- [ ] The README serve section states the context served on the 24 GB host, taken from the run.
- [ ] Every box the run created shows as `released` or `expired` in `vasty status --all --everyone` at the end, and the total spend is under the cap.
- [ ] `ls docs/filter-offers-on-host-cuda.md docs/uptime-counts-the-image-pull.md docs/replace-daily-budget-with-vast-pass-through.md docs/followups-plan.md` reports every file missing, and `ls issues/` is empty.
- [ ] `uv run pytest` and `uv run mypy` pass.

## Blocked by

- #001
- #002
- #003
- #004
- #005
- #006
- #007
- #008
