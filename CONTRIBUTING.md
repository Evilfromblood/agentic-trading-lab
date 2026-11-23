# Development workflow

## Roles
- **ChatGPT (architecture lead):** requirements, system boundaries, risk policy, implementation plans and final review.
- **Antigravity (implementation):** edits code, runs commands, tests and prepares focused commits.
- **Claude Code (independent reviewer):** reviews diffs, threat models and test gaps. It must not silently rewrite the same files being implemented.
- **Human owner:** approves merges, credentials, financial assumptions and any change that could enable live execution.

## Change protocol
1. Start from an issue or written task with acceptance criteria.
2. Create a focused branch from `main`; never work directly on `main`.
3. One implementation agent owns a given set of files at a time.
4. Add tests with every behavior change. Prefer deterministic unit tests before network or broker integration tests.
5. Run formatting, static checks and the full test suite locally.
6. Ask a second agent to review the diff independently.
7. Resolve all critical/high findings; document accepted lower-severity risks.
8. Merge only after human approval and green CI.
9. Record architecture changes in `docs/decisions/`.

## Financial safety rules
- Paper trading is the only permitted execution mode in the current project.
- No live order-placement endpoint, method, CLI option or credential flow may be added without a separate design review and explicit owner approval.
- AI agents may produce analysis and proposals; deterministic risk controls own the final allow/reject decision.
- Missing, stale, malformed or contradictory market data must fail closed.
- Never commit API keys, secrets, access tokens, broker statements or personal account data.
- Do not claim profitability from backtests without fees, slippage, survivorship-bias controls and out-of-sample evaluation.

## Definition of done
- Acceptance criteria are met.
- Unit and integration tests pass.
- Risk and failure paths are tested, not only happy paths.
- Logs are auditable and exclude secrets.
- README/configuration are updated.
- Independent review is complete.
- Changes are committed on a feature branch and merged by the owner.
