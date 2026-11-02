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

## D-005 — Cross-market product direction and Time Machine priority
- Status: Accepted (2026-11-03)
- Decision: Build Agentic Trading Lab for both Indian markets (NSE/BSE) and US markets (NYSE/NASDAQ), extending the existing codebase. The first major product priority after the reliable data foundation is the Time Machine: historical backtesting and reproducible Monte Carlo simulation.
- Architecture: Shared domain and simulation core with market-specific adapters, calendars, sessions, instrument metadata, currencies and transaction-cost models. Do not create separate India and US platforms.
- Consequences: Complete and verify M2b first; then establish cross-market instrument/session/data foundations, strategy and deterministic simulation contracts, and build the Time Machine. Scanner, news intelligence, multi-agent research and dashboard capabilities follow rather than displacing this priority.
- Safety: Remains strictly paper-only. No real-money order execution, no agent access to broker order-placement APIs, and no autonomous live trading. AI agents may research and propose; deterministic risk controls remain authoritative. Missing, stale, malformed or contradictory data fails closed.
- Approval: User/product owner.

## D-006 — Iterative verification/remediation workflow
- Status: Accepted (2026-11-03)
- Decision: Use a resource-efficient cycle: Claude independent verification -> ChatGPT finding triage and technical direction -> Antigravity scoped remediation -> focused independent verification of the changed snapshot.
- Consequences: Do not require multiple overlapping audits before fixing a verified defect. Use Claude reviews at meaningful quality gates, preserve each audited snapshot and its SHA-256, and ensure reviewers inspect the exact same snapshot. Antigravity must add regression tests and report actual commands/results. ChatGPT distinguishes confirmed defects, design decisions and false positives before authorising scope.
- Safety: No concurrent edits to a frozen audit snapshot. No destructive Git operations. No commit, push or merge without explicit user approval; never modify `main`.
