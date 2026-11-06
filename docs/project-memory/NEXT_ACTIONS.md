# Next Actions

Current priority: Independent audit verification of M2b Remediation Batch 5.

## Immediate sequence
1. Baseline M2a committed (`1b7e582`) and pushed to `origin/feature/reliable-foundation`.
2. M2b Ingestion Foundation and Claude Batch 5 audit remediations verified in working tree:
   - F-1 (Critical): Removed module-level raw-client registries (`_wrapper_clients`, `_connector_clients`) and getters (`_get_client_for_wrapper`, `_get_client_for_connector`) in `zerodha_connector.py`. Implemented closure-held dispatch with `__slots__ = ("_dispatch", "__weakref__")`. Blocked all reflection bypasses and neutralized mutation methods on underlying client instances upon initialization.
   - F-2 (High): Hardened `ExchangeCalendar` evidence completeness contract: incomplete calendars (`complete=False`) never mark unlisted weekdays as verified non-trading days. `has_evidence_for_range` fails closed unless every date has explicit evidence. Verified D1 and M5 sequences fail closed and reject `require_full_coverage=True` across NSE, BSE, NYSE, and NASDAQ.
   - F-3 (Medium): Configured blocking secret scanning via `detect-secrets-hook --baseline .secrets.baseline` in `.github/workflows/ci.yml`. Generated UTF-8 `.secrets.baseline` with 0 leaks.
   - Test Isolation: Fixed `sys.modules["keyring"]` and `sys.modules["kiteconnect"]` pollution using scoped `patch.dict`. Added 14 targeted tests in `tests/test_claude_batch5_regressions.py`.
   - Coverage: Verified **87.12% genuine coverage** across **283 tests** passing on both Python 3.11.9 (`.venv311`) and Python 3.14.4 (`.venv`).
3. Prepare verified audit bundle ZIP `m2b-remediated-batch5-bundle.zip` outside repo for Claude independent audit.
4. Next M2b increments:
   - Production exchange calendar integration with automated feed ingestion.
   - Corporate actions and dividend/split price adjustments.
   - Stored replay fixture subsystem.

## Non-negotiable boundaries
- Work exclusively on `feature/reliable-foundation`. Do not touch `main`.
- Paper-only architecture; no live broker connectivity or order execution.
- No hardcoded secrets, API keys, or live credentials.
- No destructive Git operations (reset, clean, checkout, stash).
- Do not commit or push M2b without human approval.
