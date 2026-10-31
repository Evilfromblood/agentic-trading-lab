# Agent Handoff Protocol

## ChatGPT
- Read `README.md`, then `docs/project-memory/CURRENT_STATE.md`, `NEXT_ACTIONS.md`, and `ISSUES_AND_RISKS.md` at the beginning of a resumed session.
- Treat repository files as the durable source of project continuity, but verify live Git state before acting.
- Never assume local working tree state from remote GitHub state.
- Review actual code diffs and evidence; do not accept agent claims without verification.
- Update the project-memory files after meaningful work and update README with a concise handoff pointer/status.
- If memory context is missing, ask for current branch/status/log and relevant diffs rather than guessing.

## Antigravity
- Implement only the scoped task provided.
- Do not commit, push, merge, or modify `main) unless explicitly instructed.
- Do not overwrite unrelated work or edit files concurrently with another agent.
- Run the requested tests and report exact commands/results.
- Identify all files changed and any limitations or assumptions.
- Do not claim a milestone complete if known review findings remain.

## Claude Free
- Act as an independent reviewer of a specified commit/branch.
- Report severity, file/line evidence, reproducible concerns, missing tests, and a clear verdict.
- Do not modify repository files unless explicitly requested.
- Review the exact commit SHA; do not audit an unspecified moving branch.

## Human approval gates
User approval is required before:
- Commit/push when the workflow asks for approval.
- Merge to `main`.
- Credentials, broker permissions, financial assumptions, or changes to paper-only safety boundary.
- Any future consideration of live trading.
