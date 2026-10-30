# `serve` runs the vLLM the image ships

Live run 2026-10-30, lease `l-c38505e0`, RTX 3060, `vastai/base-image:cuda-12.6.3-auto`.

## What happened

```
vasty serve --on sv --model Qwen/Qwen2.5-0.5B-Instruct
```

```json
{"error": "serve_failed", "message": "vLLM exited 1 before /v1/models answered.",
 "hint": "Read the log: vasty ssh l-c38505e0 -- tail -n 100 /workspace/.vasty/jobs/j-1/log",
 "details": {"exit": 1}}
```

Job log:

```
[transformers] Disabling PyTorch because PyTorch >= 2.6 is required but found 2.4.0
  File ".../vllm/config.py", line 1764, in _get_and_verify_max_len
    assert "factor" in rope_scaling
AssertionError
```

`install_command` in `src/vasty/commands/serve.py` ran `pip install vllm==0.6.3` into `/workspace/.vasty/venv`. That pin fixes torch at 2.4.0 and leaves transformers open, so pip resolved transformers 5.22.0, which refuses torch below 2.6 and rewrites `rope_scaling` into a form vLLM 0.6.3 asserts on. The install took two minutes and 6.8 GB. The retry reused the venv and failed in 8 s.

## Decision

Delete the install path. `serve` launches the `vllm` the box's image ships. The `[models]` entry's `image` is where vLLM comes from; the config resolution order already puts it above `defaults.image`, and the `serve_failed` hint already says to pass `--image` with vLLM preinstalled. A box from a plain image does not serve. Train-then-serve is two boxes.

Reasons, against the README's principles:

- Light. The venv, its marker, the 30 m install timeout and the install-failure branch are a package manager inside one verb.
- Bounded spend. The install ran on a paid clock, with a timeout equal to the default TTL.
- Agent-first I/O. A stable `vllm_missing` error with a hint beats a nondeterministic install that fails through resolver noise.
- Testable. The preflight is one shell command the fake box can answer. The install never was.

## Changes

`src/vasty/commands/serve.py`:

1. Remove `VENV`, `DEFAULT_VLLM`, `INSTALL_TIMEOUT_S`, `INSTALL_HINT`, `_TAG_VERSION`, `vllm_pin`, `install_command` and `_install`.
2. `server_argv` launches `vllm` from PATH.
3. Before starting the job, `_bring_up` runs `command -v vllm` on the box. On a miss raise `vllm_missing`, exit 1, message `Lease L has no vllm on PATH.`, hint `Reserve with a vLLM image: vasty serve --model M --image vllm/vllm-openai:v0.32.0, or add image to the [models."M"] entry.`
4. `serve_failed` keeps the exit-before-ready and ready-timeout cases.

`src/vasty/errors.py`: add `vllm_missing` at exit 1.

`src/vasty/config.py`: the builtin entry's image becomes `vllm/vllm-openai:v0.32.0`.

README:

- Error table: add `vllm_missing`; `serve_failed` becomes "the inference server exits before `/v1/models` answers".
- `serve` section: state that the box's image supplies vLLM, the builtin entry and the `[models]` example use `vllm/vllm-openai:v0.32.0`, and a plain image serves after a `startup` hook installs vLLM.
- Status section: drop the serve-is-broken line.

Tests:

- Remove `test_serve_install_failure`, `test_serve_install_timeout_is_serve_failed`, `test_serve_install_lost_connection_stays_box_unreachable` and `test_serve_vllm_pin_parsing` in `tests/test_serve.py`.
- Update the argv assertions at `tests/test_serve.py:56-66` to the PATH `vllm`.
- Add: preflight miss raises `vllm_missing` with exit 1 and releases an auto-reserved box; preflight hit proceeds to `start_job`.
- Update the `v0.6.3` tag in `tests/test_config.py:265,453,458,463,470` and `tests/test_integration.py:74`.

## Acceptance

Rerun Phase 5 of `docs/live-test-plan.md` with the box reserved from `vllm/vllm-openai:v0.32.0`:

```
vasty reserve --name sv --vram 12 --ttl 30m --disk 40 --image vllm/vllm-openai:v0.32.0
vasty serve --on sv --model Qwen/Qwen2.5-0.5B-Instruct
```

Pass is the plan's pass: `url` and `api_key` returned, the authorized call lists the model, the unauthorized call gets 401. Then one negative check on a plain image: `vasty serve --on BOX --model M` returns `vllm_missing`, exit 1, and the box stays up.

## Out of scope

- `serve_failed` carries `details.exit` only. The log tail is a design question in `docs/live-test-memo.md`.
- The builtin entry's model id `Qwen/Qwen3-72B-Instruct` does not exist. Also a design question there.
