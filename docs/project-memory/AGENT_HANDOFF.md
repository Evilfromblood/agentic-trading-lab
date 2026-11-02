# Agent Handoff Protocol

## ChatGPT
- Read `README.md`, then `docs/project-memory/CURRENT_STATE.md`, `NEXT_ACTIONS.md`, `ISSUES_AND_RISKS.md` and `DECISION_LOG.md` when resuming.
- Treat repository files as durable project continuity, but verify live Git and local working-tree state before acting.
- Never assume local working-tree state from GitHub state.
- Review actual source diffs and evidence; do not accept agent claims without verification.
- Act as architect, technical lead, reviewer and remediation triage owner.
- Separate confirmed defects, theoretical risks, design decisions and false positives.
- Update project memory after meaningful approved changes.
- Never claim tests or changes were completed unless verified.

## Antigravity
- Primary local implementation environment on the user's Windows machine.
- Implement only the scoped task authorised by ChatGPT/user.
- Inspect the working tree first and preserve unrelated/uncommitted work.
- Do not modify frozen audit snapshots.
- Do not commit, push, merge or modify `main` unless explicitly authorised.
- Never reset, clean, stash, overwrite or discard user work.
- Add regression tests for every fixed defect.
- Run requested tests with explicit project Python executables; report exact commands, versions and results.
- Identify every changed file, unresolved finding and policy assumption.
- Do not claim a milestone complete while material review findings remain.

## Claude reviewers
- Independent, adversarial reviewers; do not implement fixes unless explicitly asked.
- Review the exact supplied snapshot and verify its SHA-256 before analysis.
- Do not treat reports, implementation claims or test names as proof; inspect source and execute tests where possible.
- Clearly distinguish executed tests from static inspection.
- Report severity, file/line evidence, reproducible probes, missing regression tests, limitations and verdict.
- Avoid duplicating earlier audits of unchanged code; focus on the assigned quality gate and remediation verification.

## Standard iterative workflow
1. Freeze and identify the source snapshot (SHA-256).
2. Claude independently verifies the assigned scope.
3. ChatGPT triages findings and defines the smallest safe remediation scope.
4. Antigravity implements fixes and regression tests without changing the frozen snapshot.
5. Create a new snapshot and SHA-256.
6. Claude independently verifies the new snapshot and the fixes.
7. Repeat only for material remaining defects.

## Human approval gates
User approval is required before:
- Commits/pushes when the workflow asks for approval, and all implementation-history changes.
- Merge to `main`.
- Credentials, broker permissions, financial assumptions or any change to the paper-only boundary.
- Any future consideration of live trading.
