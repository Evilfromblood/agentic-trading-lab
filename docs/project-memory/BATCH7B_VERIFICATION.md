# Batch 7b Verification Report

Environment: Windows 11, Python 3.11.9 (`.venv311`), Python 3.14.4 (`.venv`), `kiteconnect 5.2.2`, `keyring 25.7.0`, `requests 2.34.2`, `detect-secrets 1.5.0`, `pytest 9.2.0`, `pytest-cov 7.1.0`, `ruff 0.17.3`.

| Check | Result |
| --- | --- |
| New batch 7b regression tests | 11 new tests (F1 × 4, F3 × 4, coverage × 3) |
| Full pytest suite (Python 3.11.9) | 338 passed in 2.24s |
| Full pytest suite (Python 3.14.4) | 338 passed in 1.42s |
| Test coverage | 85.02% (threshold: 85%) |
| Ruff (`src`, `tests`, `v3-zerodha/src`) | passed (0 errors) |
| Python compileall (`src`, `tests`, `v3-zerodha/src`) | passed (0 errors, both 3.11 and 3.14) |
| detect-secrets hook against baseline | passed (0 unbaselined secrets) |
| pip-audit dependency vulnerability check | passed (0 vulnerabilities) |

## Summary of Remediations (F1, F3)

1. **F1 (Zero mutation of injected clients):**
   - Stored `(client, injected: bool)` tuple in the closure-encapsulated `_connector_registry` instead of bare `client`.
   - `_require_session()`: when `injected is True`, verifies `raw_client.access_token` is already a non-empty string; if missing/empty, raises `KiteConfigurationError("Injected client must be pre-authenticated with an active access_token")` without calling `set_access_token()` or querying keyring.
   - `logout()`: when `injected is True`, only calls `_safe_delete_stored_token()` and returns immediately without touching `raw_client.access_token` or `raw_client.reqsession.headers`.
   - `client` property unpacks the registry tuple before constructing the `_ReadOnlyKiteWrapper`.
   - Injected genuine `KiteConnect.__dict__` and `reqsession.headers` are identical before and after wrapping, `profile()`, and `logout()`.

2. **F3 (Block POST margin/contract-note endpoints before transport):**
   - Removed `order_margins`, `basket_order_margins`, and `get_virtual_contract_note` from `_READ_ONLY_ALLOWLIST`.
   - Added them to `_BLOCKED_METHODS`.
   - Added explicit method overrides on `ReadOnlyKiteConnect`, `_ReadOnlyKiteWrapper`, and `ZerodhaReadOnlyConnector` raising `PermissionError` via `_blocked()`.
   - Added messages to `_OPERATION_MESSAGES` for each blocked method.
   - All three methods raise `PermissionError` on both default and injected genuine `KiteConnect` clients before any network transport.

No live broker credentials or network requests were used. The KiteConnect integration test intercepts the genuine library's `requests.Session.request` transport.

This is not an M2b acceptance result. Independent adversarial review remains required; see `AUDIT_BRIEF.md`.
