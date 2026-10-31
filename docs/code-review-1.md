# Code review 1

Range `2afb912..005e728`, effort medium. The review reported each finding without a verify pass, so every verdict is "reported".

1. `src/vasty/commands/serve.py:92`. Auto-reserve `serve` no longer checks for a vLLM image, so it rents a box on the default image, then hits `vllm_missing` and releases it. Fix: refuse before reserving when no image is set. Verdict: reported. Issue 003 specifies this reserve, release and `vllm_missing` path.
2. `src/vasty/engine.py:1001`. `charges_start` uses the leases' `label.created`, which is the adoption time for a tagged box and is absent for orphans. Charges from before that window drop out of `cost`. Fix: start the window from the instance start time, or document the window. Verdict: reported.
3. `src/vasty/cache.py:161`. A charges object cached before the upgrade decodes with `today` set to 0. `_cached_charges` accepts it, and `status` reports `charges_today: 0.00` with no warning. Fix: reject cached charges that lack the new fields. Verdict: reported.
4. `src/vasty/config.py:286`. A config that still sets `daily_budget` or a `[models]` table fails every command with `invalid_config`. Fix: add a deprecation path. Verdict: reported. Issues 001 and 003 specify the `invalid_config` error.
5. `src/vasty/provider.py:1338`. `parse_charges` assigns a row to a day by its `start`, so a row that crosses 00:00 UTC drops out of `charges_today`. Fix: assign by overlap or by `end`. Verdict: reported.
6. `src/vasty/engine.py:1031`. The charges window reaches back to the oldest lease's creation day and pages through it under the `leases.json` lock. A `created` of 0 reaches back to 1970. Fix: clamp the window. Verdict: reported.
7. `src/vasty/commands/status.py:56`. `status` reads charges and balance in sequence, with two lock, load and save cycles. Fix: read both under one lock. Verdict: reported.
8. `src/vasty/commands/serve.py:376`. `check_extra` matches owned flags exactly, and vLLM's argparse accepts prefixes such as `--api-k` and `--po`. Fix: reject unambiguous prefixes of `--host`, `--port` and `--api-key`. Verdict: reported.
9. `src/vasty/engine.py:987`. `cached_snapshot` returns a balance of any age but drops charges not read today, so `status --cached` shows a stale `credit` as current. Fix: apply the same freshness rule to balance, or mark it stale. Verdict: reported.
