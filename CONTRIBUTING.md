# Contributing & Development Workflow

Thank you for considering a contribution to Agentic Trading Lab. This platform is a local-first, multi-agent equity research and paper-trading system with strict deterministic risk controls.

## Community Contributions
1. Read the root [README.md](README.md), [ROADMAP.md](ROADMAP.md), and [SECURITY.md](SECURITY.md).
2. Check existing issues and project memory before starting substantial work.
3. For a large change, open an issue to discuss the design first.
4. Never include API keys, access tokens, account data, or other secrets in commits, issues, logs, or screenshots (see [SECURITY.md](SECURITY.md)).

## Core Development Principles
- Prefer small, focused pull requests.
- Keep external services behind explicit interfaces.
- Make tests deterministic; mock network and broker calls.
- Document data sources, assumptions, timestamps, and known limitations.
- Keep broker integrations strictly read-only unless an explicit architectural decision changes the safety model.
- Do not describe simulated results as real trading performance.

## Collaboration Roles
- **ChatGPT (architecture lead):** requirements, system boundaries, risk policy, implementation plans, and final review.
- **Antigravity (implementation):** edits code, runs commands, tests, and prepares focused commits.
- **Claude Code (independent reviewer):** reviews diffs, threat models, and test gaps.
- **Human owner:** approves merges, credentials, financial assumptions, and any change that could affect live execution.

## Change Protocol
1. Start from an issue or written task with acceptance criteria.
2. Create a focused branch from `main`; never work directly on `main` without approval.
3. One implementation agent owns a given set of files at a time.
4. Add tests with every behavior change. Prefer deterministic unit tests before network or broker integration tests.
5. Run formatting, static checks, and the full test suite locally across Python 3.11 and 3.14.
6. Ask a second agent to review the diff independently.
7. Resolve all critical/high findings; document accepted lower-severity risks.
8. Merge only after human approval and green CI.
9. Record architecture changes in `docs/project-memory/DECISION_LOG.md`.

## Financial Safety Rules
- Paper trading is the only permitted execution mode in the current project.
- No live order-placement endpoint, method, CLI option, or credential flow may be added without a separate design review and explicit owner approval.
- AI agents may produce analysis and proposals; deterministic risk controls own the final allow/reject decision.
- Missing, stale, malformed, or contradictory market data must fail closed.
- Never commit API keys, secrets, access tokens, broker statements, or personal account data.
- Do not claim profitability from backtests without fees, slippage, survivorship-bias controls, and out-of-sample evaluation.

## Pull Requests & Definition of Done
- Acceptance criteria are met.
- Unit and integration tests pass with $\ge 85\%$ coverage across Python 3.11 and 3.14.
- Risk and failure paths are tested, not only happy paths.
- Logs are auditable and exclude secrets.
- Documentation and project-memory records are updated.
- Independent review is complete.
- Changes are committed on a feature branch and merged by the owner.
