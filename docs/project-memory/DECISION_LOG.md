# Project Decision Log

Append decisions; do not silently rewrite historical decisions. Mark superseded decisions explicitly.

## D-001 — Paper-only development boundary
- Status: Accepted
- Decision: The platform remains paper-trading-only during the current development phase.
- Rationale: Establish deterministic controls and auditable behaviour before considering any live execution.
- Consequences: No live order placement; AI agents propose research/actions only; deterministic risk engine is authoritative for paper-order approval. Zerodha integration is initially read-only.
- Approval: User/product owner.

## D-002 — Hybrid development workflow
- Status: Accepted
- Decision: User owns product decisions and approvals; ChatGPT handles architecture/review; Antigravity is primary implementation environment; Claude Free may independently review GitHub changes.
- Consequences: Human approval required for commits/pushes when requested, merges, credentials, financial assumptions, and any future live-trading scope. Avoid concurrent edits to the same files.

## D-003 — Feature branch isolation
- Status: Accepted
- Decision: Active development occurs on `feature/reliable-foundation`; do not merge to `main` without explicit approval.
- Consequences: Verify branch and working tree before every Git operation that changes history or remote state.

## D-004 — M2 split
- Status: Accepted
- Decision: Split market-data work into M2a (normalized candle contracts and quality gate) and M2b (provider adapters, complete exchange calendars, corporate actions, symbol changes, replayable snapshots).
- Rationale: Do not imply calendar-aware correctness without a real exchange calendar.
- Consequences: Ambiguous gaps must be surfaced as requiring calendar knowledge, not silently accepted.
