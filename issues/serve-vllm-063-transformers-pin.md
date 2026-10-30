# `serve` fails: vllm 0.6.3 installs with transformers 5.x

Live run 2026-10-30, lease `l-c38505e0`, RTX 3060, `vastai/base-image:cuda-12.6.3-auto`.

## Command

```
vasty serve --on sv --model Qwen/Qwen2.5-0.5B-Instruct
```

## Output

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

Installed in `/workspace/.vasty/venv`: vllm 0.6.3, torch 2.4.0, transformers 5.22.0, tokenizers 0.23.3.

## Cause

`install_command` in `src/vasty/commands/serve.py` runs `pip install vllm==0.6.3`. That pin fixes torch at 2.4.0 and leaves transformers open, so pip resolves transformers 5.22.0. transformers 5 drops torch below 2.6 and normalises Qwen2.5's `rope_scaling` into a dict without `factor`, which vLLM 0.6.3 asserts on. Every model with a `rope_scaling` entry fails the same way. The retry reuses the venv and fails in 8 s.

## Fix options

- Add `transformers<4.50` to the install spec for the 0.6.3 pin (4.46 is the version vLLM 0.6.3 shipped against).
- Or raise `DEFAULT_VLLM` to a release whose dependency set includes a transformers upper bound, and update the `[models]` Qwen entry's image tag to match.

Either way, record the full resolved set so the venv marker `.vasty-vllm` changes when the spec changes.

## Also seen

`serve_failed` returns `details.exit` only. The live test plan expected `details.output`. Adding the last lines of the job log would save the ssh round trip.
