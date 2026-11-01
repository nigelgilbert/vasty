# The vLLM path carries its CUDA floor

**Type**: AFK

**Status:** ✅ Done, commit a8af11e

## Parent

`docs/decisions.md`, row "A vLLM image on a 12.x host fails with error 804".

## What to build

When the image is one vasty names itself and no `--cuda` is set, reserve applies the image's floor: 13 for `vllm/vllm-openai:v0.32.0`, 12.6 for `vastai/base-image:cuda-12.6.3-auto`. A `--cuda` flag, profile value or config value wins over the floor. `config show` reports the source of the resolved `cuda` as the image.

The auto-reserve `vllm_missing` hint keeps the caller's `--ttl` and `--name` and adds `--cuda 13`.

## Acceptance criteria

- [ ] `reserve --image vllm/vllm-openai:v0.32.0` with no `--cuda` filters offers at CUDA 13; a test asserts the filter
- [ ] `reserve` with the base image and no `--cuda` filters at 12.6
- [ ] `--cuda 12.4`, a profile `cuda` and a config `cuda` each override the floor
- [ ] `config show --profile vllm` names the image as the `cuda` source
- [ ] The `vllm_missing` hint for `serve --model M --ttl 2h --name n` reads `vasty reserve --profile vllm --ttl 2h --name n --cuda 13`

## Blocked by

None - can start immediately
