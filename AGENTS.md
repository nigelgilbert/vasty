# Vasty

Read @docs/principles.md before proposing or reviewing a change. Reviewers work from docs/review-brief.md.

## Talking to Nigel

- Write plainly, at an engineer's level. Skip analogies and jargon-heavy summaries.
- Keep answers short. Skip context Nigel already has and get to the question.
- Ask questions that make sense without reading the code.
- Use consistent units and numbers across one explanation.
- When you disagree, say so once with the reason, then follow Nigel's call. Change position only on a new argument, and name it.
- Apply a recommendation Nigel left unopposed. Skip confirmation on a cut that is plainly warranted.
- Answer a message that reads as a question. Act once Nigel confirms.
- Call the project vasty.

## Workflow

- Stay on the named task or defect list. Raise anything else as a one-line note.
- A design problem or a change to the API surface gets options first. Implement one after Nigel picks.
- Name branches `<type>/<description>`.
- Squash merge PRs with `gh pr merge N --squash`, after deleting loop outputs, validation reports and test plans from the branch.
- Write PR descriptions that stand alone, with no pointers to internal docs.
- Don't propose a merge while fix items remain on the branch.
- Check for a live run before starting one. Live runs share one account.
- Run `uv run pytest`, `uv run ruff check .` and `uv run mypy` before calling work done.
