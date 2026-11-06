# Live-run harness changes

The harness has three parts:

- The skill: `~/.claude/skills/live-run/SKILL.md`. Owns the method.
- The plan: `docs/live-run-8.md`. Owns the scenarios, owners, limits and `Pass:` lines.
- The seed: `docs/live/8d-seed/` (gitignored). Owns the files a run copies into its run dir.

Touch nothing under `src/` or `tests/`. Start no live run. Line numbers refer to the files before any edit.

Each work item owns one set of files, so the three can run in parallel.

## 1. Checkers in the seed

Files: `docs/live/8d-seed/out/check.py` and `docs/live/8d-seed/out/{a,b,c,d,e,f,g}/check.sh`.

- Write one `check.py` holding the shared helpers and one plain function per scenario. Build no framework.
- Each `check.sh` is two lines: the shebang, then `exec python3 "$(dirname "$0")/../check.py" <d>`.
- `check.py` prints to stdout and writes no file. The phase orchestrator redirects it into `check.txt`.
- Set `RUN = os.environ.get("RUN", "/private/tmp/vasty-live-8d")`. Hardcode the owners r8da to r8dg.
- Each output line reads `PASS` or `FAIL`, the condition, then the file and field it read.
- A ledger token reads `instanceid:status:label:price`. The label packs `lease=<id>;name=<name>;owner=<owner>;...`. Find a box by matching `lease=<id>;` inside a token.
- Under `--json`, errors are in the stdout `.json` and job output is in the `.err`. A check on an argument reads `NN-<verb>.cmd`.
- Port A, E and G from `/private/tmp/vasty-live-8d/out/{a,e,g}/check.sh`. Write B, C, D and F from their `Pass:` lines in the plan.
- F's `--startup` condition looks for `/workspace/extra.ok` in a `run` `.err`, the path `fx/extra.sh` writes.
- C's ledger condition reads the last line with an r8dc token.

Done when:

- `bash -n` passes on every `check.sh`.
- With the default `RUN`, `check.py` reports A 4 of 4, E 7 of 7 and G 4 of 4 PASS against the raw output there. Send the output to the scratchpad and leave that run dir unchanged.
- With `RUN` set to an empty dir, every scenario prints FAIL lines and no traceback.
- The handoff report names B, C, D and F as untested against raw output.

## 2. Skill

File: `~/.claude/skills/live-run/SKILL.md`.

- Line 3: open the description with "Run a plan of vasty CLI scenarios against the live Vast account."
- Line 6: cut the last sentence, on the matrix.
- Layout block: add a line for `<run>/out/check.py`, described as shared check code.
- Line 29: replace the paragraph with: "Spawn one chores agent. It copies the seed to the run dir, starts the ledger and manager loops, and writes the start credit to `run.md`."
- Line 31: cut.
- Line 33: cut.
- Line 44: replace with: "Spawns the observer with the `Pass:` lines, the NN file paths and `check.txt`. The observer writes `verdict.md` with pass or fail per condition, each line citing an NN file and a line range or field. It then writes the findings file the plan names, with the same citations."
- Lines 55 and 62: change `report.md` to `run-report.md`.
- Line 65: replace with: "Subagent Write refuses the basenames `findings.md` and `report.md`."

Done when:

- `grep -n 'report.md' ~/.claude/skills/live-run/SKILL.md | grep -v 'run-report.md\|Subagent Write'` returns nothing.
- `grep -n 'matrix\|owner map' ~/.claude/skills/live-run/SKILL.md` returns nothing.
- The file stays under 70 lines.

## 3. Plan

File: `docs/live-run-8.md`.

- Line 5: replace "every surface that `docs/surface-area-reduction-1.md` changed" with "the reduced surface".
- Line 7: cut the last sentence, on run 7's spend.
- Lines 11 to 32: cut the "What changed since run 7" heading and table.
- Line 37: replace "sooner than run 7's four tries" with "in few tries".
- Line 44: cut the sentence starting "Run 7's harness classifier".
- Line 50: cut `docs/surface-area-reduction-1.md` from the inputs. Cut the last sentence, "It does not read `src/`."
- Line 52: change "Two sections" to "Three sections".
- After line 55: add "- Disputed claims: each claim in `notes.md` or `final.md` that disagrees with the raw output, citing both."
- Line 55: replace "a deferred item from the work file now confirmed by a live caller" with "a deferred item now confirmed by a live caller".
- Lines 59 to 61: cut. Keep lines 62 to 64.
- Line 71: replace with: "- A recorder agent that breaks its read-only rule is restarted with the brief restated."
- Line 75: add `out/check.py` and `out/<d>/check.sh` to the list of seed contents.

Done when:

- `grep -n 'surface-area-reduction\|[Rr]un 7\|work file' docs/live-run-8.md` returns nothing.

## Leave alone

- The rest of the skill's phase steps and Rules list.
- The brief template.
- `ledger.sh`, `manager.sh`, `removed-flags.sh` and `setup-c.sh`.
- The per-scenario `fx/` copies and `out/pass-3-findings.md`.
