# Validation 0: `5c17670..2c012c5`

Verdict: ready after fixes. Both issues' Changes, Fix and Tests bullets landed and the code is correct, but the removed venv path leaves dead boot code and a stale live-test plan.

Target: the diff `5c17670..2c012c5` (e28f372 serve, b108291 budget, 2c012c5 README count). References: `issues/serve-runs-the-image-vllm.md`, `issues/spent-today-estimates-from-midnight.md`. At HEAD, `uv run pytest -q` gives 1141 passed, 1 skipped, and `uv run mypy` is clean.

## Settle points

1. Serve conformance: every Changes and Tests bullet is present at HEAD. `git grep` finds no `VENV`, `DEFAULT_VLLM`, `INSTALL_TIMEOUT_S`, `INSTALL_HINT`, `_TAG_VERSION`, `vllm_pin`, `install_command`, `_install` or `0.6.3` in `src/` or `tests/`. The message and hint at `src/vasty/commands/serve.py:182-185` match the issue. `vllm_missing` is exit 1 at `src/vasty/errors.py:28`. Deleting `test_serve_pin_from_config_entry` was right: it asserted `vllm==0.7.2` in the install command and has no subject now. It was also the only serve test that read a user `[models]` entry (finding 6).
2. Preflight timeout: 30 s is reasonable. ssh `ConnectTimeout` is 10 s and `start_job` also uses 30 s. A timeout raises `BoxUnreachableError("The box did not answer within 30s.")` (`src/vasty/remote.py:443-444`), and ssh exit 255 raises the same error (`remote.py:467-468`). Both surface as `box_unreachable`, exit 2, hint "Run vasty status." `execute` releases an auto-reserved box on any exception and keeps an `--on` box. The preflight and the job both run through the sshd shell, so their PATH matches.
3. Style: the `vllm_missing` row follows the rules. The serve paragraph restates the row (finding 8).
4. Budget: `labels.parse` returns `Label` for a valid `vasty:v1` label, `Unreadable` for a broken `vasty:` label, and None for no label or a non-vasty label. It calls `int()` only after the `_UINT` check, so it does not raise. `instance_start` accepts only `Label`, so orphans and malformed labels fall back to `max(covered_through, day_start)`. Real rows carry a float `start_date` (`1793318816.821275` in `docs/live/p2c-08-instances.json`), and `_to_int` truncates it. Reading `start_date` before the label bills an adopted box from its true start, since `tag` writes `created` at adopt time.
5. `test_spend_sources_and_charges_cache`: 1.10 is correct. Billed $1.00 covers through `NOW - 1800`. `add_lease` sets no `start_date`, so the label's `created = NOW - 600` applies. The estimate is 0.60 × 600 / 3600 = 0.10, and the total is 1.10. The old rule ran from `NOW - 1800` and gave 1.30.
6. Fixtures: `Instance(` is built in `normalize_instance`, `FakeProvider.add_instance` and `inst()` in `tests/test_budget.py`. `add_lease` and `FakeReserve` go through `add_instance` with a label `created` and no `start_date`. No bug is hidden, because `created` equals what `start_date` would be. No engine test has the two differ (finding 4).
7. README: the top blurb and Status no longer call `serve` broken. The test count of 1141 matches. No README text mentions a venv, a serve install or vLLM 0.6.3. "Vasty installs what it needs at boot" still holds. The stale text sits in `docs/live-test-plan.md` (finding 2) and the `_installer` docstring (finding 1).

## Agreed findings

### Gaps

1. **Dead python3-venv probe in onstart**
   - Location: `src/vasty/onstart.py:106-130`, `tests/test_onstart.py:456-486`.
   - Problem: `_installer` still checks `ensurepip` and apt-installs `python3-venv` on custom images for `serve`'s `python3 -m venv`, which the diff removed. Nothing else uses it. The docstring says `serve` reports `serve_failed` when `python3 -m venv` fails, which is false.
   - Evidence: `onstart.py:112` reads "`python3-venv`, which `serve` needs for `python3 -m venv`". `git grep -n "python3-venv\|ensurepip"` hits only `onstart.py:111-120` and `tests/test_onstart.py:468,471`.
   - Fix:
     - Replace the docstring at `onstart.py:107-115` with: "Install missing essentials with apt-get and record what the image lacks. `p` lists the packages for missing essentials. A missing essential on an image without apt-get adds `apt-get` to `unsupported`."
     - Delete lines 118-120 and `+ venv` at line 124.
     - Line 122: drop `v=;`.
     - Line 126: `[ -n "$p$v" ]` becomes `[ -n "$p" ]`.
     - Lines 128-129: drop ` $v` from the install command and from the `install failed:` echo.
     - Delete `test_custom_image_installs_python3_venv_when_python_lacks_it` (456-474) and `test_custom_image_without_apt_skips_python3_venv` (476-486). `test_custom_image_without_apt_is_unsupported` already covers the no-apt case.
     - Rerun `uv run pytest -q tests/test_onstart.py`.
   - Settled: initial review, both sides.

2. **Live-test plan describes the removed install and the fixed midnight estimate**
   - Location: `docs/live-test-plan.md:37`, `:40`, Phase 5 at `:242-256`.
   - Problem: the serve issue's Acceptance reruns Phase 5. The phase still reserves without `--image`, which now returns `vllm_missing`. It also describes the venv install. Line 37 still lists the midnight estimate as a known defect.
   - Evidence: line 242 reads "enough for a 0.5B model under vLLM 0.6.3. The install downloads about 3 GB of wheels into `/workspace/.vasty/venv`". Line 246 reads `vasty reserve --name sv --vram 12 --ttl 45m --disk 40`. Line 256 reads "the retry reuses the installed venv".
   - Fix:
     - Line 37: delete the `spent_today` bullet.
     - Line 40: replace with "vLLM ships in `vllm/vllm-openai:v0.32.0`. The 3060 (compute capability 8.6) qualifies for `serve`."
     - Line 242: replace with "A 3060 has 12 GB VRAM, enough for a 0.5B model. The model is ungated, 988 MB. `serve` allows 30m for readiness, so the lease runs 30m."
     - Line 246: use `vasty reserve --name sv --vram 12 --ttl 30m --disk 40 --image vllm/vllm-openai:v0.32.0`.
     - Line 253: delete "Stop the phase if the install runs past 20 minutes."
     - Line 256: replace "save the error's `details.output`" with "save the error's `details`". Replace "the retry reuses the installed venv" with "the retry reuses the running box".
     - Add the negative check from the issue's Acceptance: on a box from `vastai/base-image:cuda-12.6.3-auto`, `vasty serve --on BOX --model M` returns `vllm_missing`, exit 1, and the box stays up.
     - Leave `docs/live-test-report.md` and `docs/live-test-memo.md` as they are. They record the 2026-10-29 run.
   - Settled: initial review, both sides.

### Nits

3. **`VLLM_IMAGE` duplicates the builtin image**
   - Location: `src/vasty/commands/serve.py:49`, `src/vasty/config.py:78`.
   - Problem: the hint's image and the builtin entry's image are separate literals, so a version bump in one leaves the other stale.
   - Evidence: `VLLM_IMAGE = "vllm/vllm-openai:v0.32.0"` in serve.py and `"image": "vllm/vllm-openai:v0.32.0"` in `BUILTIN_MODELS`.
   - Fix: define `VLLM_IMAGE` in `config.py` and use it in `BUILTIN_MODELS`. In serve.py, delete the constant and import it with `from vasty.config import VLLM_IMAGE, ModelEntry, resolve`. Keep the literal in the tests.
   - Settled: initial review, both sides.

4. **No engine test has `start_date` and the label's `created` differ**
   - Location: `tests/test_engine.py`, spend tests at `:799-833`; `tests/fakes.py:435` (`add_lease`).
   - Problem: `add_lease` and `FakeReserve` set no `start_date`, so engine-level spend tests only exercise the label fallback.
   - Evidence: `add_lease` passes `**inst` to `add_instance`, which has no `start_date` default. Only `FakeProvider.create` sets it, to `wall_now`, which equals the label's `created`.
   - Fix: add one engine spend test that calls `add_lease(harness, start_date=NOW - 300)` while the label keeps `created = NOW - 600`. Assert that the estimate runs from `NOW - 300`.
   - Settled: exchange 1. Codex raised it as a gap and accepted nit.

5. **No serve test for a preflight `box_unreachable`**
   - Location: `tests/test_serve.py`.
   - Problem: the diff removed the install-path timeout and lost-connection tests. No serve test now drives a `BoxUnreachableError` through `_preflight`.
   - Evidence: `test_serve_os_error_releases_reserved_box` covers release with an `OSError`. `tests/test_remote.py` covers the timeout and exit-255 conversion apart from serve.
   - Fix: add a test parametrized over `--on ft` and auto-reserve. Set `exec_errors["command -v vllm"] = BoxUnreachableError("The box did not answer within 30s.")`. Assert exit 2, `error == "box_unreachable"` and `started == []`. Assert `destroyed == []` for `--on` and `destroyed == [1001]` for auto-reserve.
   - Settled: exchange 1. Codex raised it as a gap and accepted nit.

6. **No serve test reads a user `[models]` entry**
   - Location: `tests/test_serve.py`.
   - Problem: with `test_serve_pin_from_config_entry` gone, serve tests use only the builtin entry. `serve.py:101` reads `entry.quant` from a user config in no test.
   - Evidence: `git grep -n '\[models' HEAD -- tests` hits only `tests/test_config.py` and the hint string at `test_serve.py:120`.
   - Fix: add a test that writes `harness.home / ".config" / "vasty" / "config.toml"` with `[models."org/small"]\nvram = 24\nquant = "fp8"\nimage = "vllm/vllm-openai:v0.32.0"\n`. Run `serve --on ft --model org/small` and assert `started[0][1].endswith("--quantization fp8")`.
   - Settled: exchange 1.

7. **No budget test starts the instance before `day_start`**
   - Location: `tests/test_budget.py:75-116`.
   - Problem: no test covers a box started yesterday on a fresh day. The code handles it at `src/vasty/budget.py:61-65`.
   - Evidence: the start-date tests use starts inside today only, for example `NOW - 3000`.
   - Fix: add
     ```python
     def test_spent_today_start_before_day_runs_from_day_start() -> None:
         charges = Charges(per_instance={}, covered_through=MIDNIGHT)
         assert spent_today(charges, [inst(1, "1.00", start_date=MIDNIGHT - 7200)], NOW, MIDNIGHT) == D("1.00")
     ```
   - Settled: exchange 1.

8. **The serve paragraph restates the error-table row**
   - Location: `README.md:204`.
   - Problem: "returns `vllm_missing` when the image has none" repeats the error-table row at `README.md:162`. Rule: say each idea once.
   - Evidence: row 162 reads "`vllm_missing` | 1 | `serve` finds no `vllm` on the box's PATH".
   - Fix: "The box's image supplies vLLM, and `serve` launches `vllm` from PATH. The builtin `Qwen/Qwen3-72B-Instruct` entry uses `vllm/vllm-openai:v0.32.0`. On a plain image, install vLLM in a `startup` hook first."
   - Settled: exchange 1.

9. **The test comment is a fragment**
   - Location: `tests/test_engine.py:806`.
   - Problem: "Estimate from the label's `created` at NOW - 600, after coverage." reads as a fragment. Rule: code comments are one sentence with plain literal verbs.
   - Fix: `# Start the estimate at the label's created time, NOW - 600, after covered_through.`
   - Settled: exchange 1.

## Disagreements

None.

## Dropped

- `vllm_missing` hint omits `--vram` for unlisted models (`serve.py:182-185`). The issue prescribes the hint verbatim.
- Shell-quote the model name in the hint. User decision: batteries included. The model is the user's own input, and the argv that reaches the box is already quoted with `shlex.join`.
- Run `_preflight` before `_public_url` (`serve.py:150-151`). Both errors are real and the order is preference.
- Add a "serve is unverified" bullet to README Status. The issue prescribes dropping the line, and finding 2 covers the rerun. Codex raised a live-acceptance gap on the same ground and withdrew it in exchange 1.
- Drop the `python3` essential (`onstart.py:45`). User `run` and `startup` commands use python3.
- tmux server environment or a shell function making the preflight and the job see different PATHs. Unlikely, and both cases fail loudly.
- Codex: the nonexistent `Qwen/Qwen3-72B-Instruct` id. The serve issue's Out of scope names it. Withdrawn in exchange 1.
- Codex: the `serve_failed` row omits the readiness timeout. The issue prescribes that row text. Withdrawn in exchange 1.
- Codex: README announcement lines at `:39`, `:47`, `:108`, `:192`. These lines predate the range. Withdrawn in exchange 1.

## Run

- Angles: serve conformance against its issue; budget conformance and correctness; serve runtime, leftovers, slop and security; README and prose style.
- Agents: 4, Sonnet.
- Reviewer: GPT-6.1 Sol (`sol`), one independent review then one exchange.
- Exchanges run: 1 of a cap of 3. GPT-6.1 Sol backed A1-A3, accepted nit for findings 4, 5 and 9, and withdrew five of its own findings.
