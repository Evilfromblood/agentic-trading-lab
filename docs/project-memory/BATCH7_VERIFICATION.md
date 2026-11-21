# Batch 7 Verification Report

Environment: Windows 11, Python 3.11.9 (`.venv311`), Python 3.14.4 (`.venv`), `kiteconnect 5.2.2`, `keyring 25.7.0`, `requests 2.34.2`, `detect-secrets 1.5.0`, `pytest 9.2.0`, `pytest-cov 7.1.0`, `ruff 0.17.3`.

| Check | Result |
| --- | --- |
| `tests/test_claude_batch7_regressions.py` | 17 passed |
| Full pytest suite (Python 3.11.9) | 327 passed in 2.00s |
| Full pytest suite (Python 3.14.4) | 327 passed in 1.73s |
| Test coverage | 85.55% (threshold: 85%) |
| Ruff (`src`, `tests`, `v3-zerodha/src`) | passed (0 errors) |
| Python compileall (`src`, `tests`, `v3-zerodha/src`) | passed (0 errors) |
| detect-secrets hook against baseline | passed (0 unbaselined secrets) |
| pip-audit dependency vulnerability check | passed (0 vulnerabilities) |

## Summary of Remediations (D1–D7)

1. **D1 (Hide raw client completely):** Removed `_target` from `__slots__` on `_ReadOnlyKiteWrapper` and `ZerodhaReadOnlyConnector` (`__slots__ = ("__weakref__",)` only). Injected and default underlying clients are stored inside closure-encapsulated `WeakKeyDictionary` registries (`_wrapper_registry`, `_connector_registry` in `_init_facades()`). Zero instance attributes, zero slots, zero module-level dictionaries. `__getattribute__` blocks access to `_target`, `_client`, `__client`, `_raw_client`, `raw_client`, `__raw_client`, `_underlying`, `_dispatch`, `__dict__`, and `reqsession` with `PermissionError`. Method dispatch uses `types.MethodType(bound_call, self)` ensuring `method.__self__ is wrapper`. Caller-injected `KiteConnect` instances remain 100% unmutated.
2. **D2 & D3 (Complete login & session generation fail closed):** Removed `generate_session`, `renew_access_token`, `invalidate_access_token`, `invalidate_refresh_token`, and `set_access_token` from `_READ_ONLY_ALLOWLIST` and added to `_BLOCKED_METHODS`. Both default `ReadOnlyKiteConnect` and injected clients raise `PermissionError` before transport. `complete_login` consistently fails closed with `PermissionError`. Added explicit `store_access_token(token)` helper and static method.
3. **D4 (Graceful keyring degradation):** In `_require_session()`, checks if the underlying client already holds a non-empty `access_token` in memory; if present, read operations (`profile`, `margins`, `holdings`, `positions`, `orders`, `trades`, `quote`, `ltp`, `ohlc`, `historical_data`, `instruments`) proceed cleanly without querying `keyring`. Keyring is queried only when no in-memory token exists, catching backend errors as `KiteConfigurationError` without swallowing `KeyboardInterrupt` or `SystemExit`.
4. **D5 (Ingestion error code & docstring alignment):** In `ingest_historical`, when missing intermediate trading days or intervals occur (`DataQualityErrorCode.MISSING_INTERVAL`), sets both `coverage_status = CoverageStatus.TRUNCATED_COVERAGE.value` and `error_code = "TRUNCATED_COVERAGE"`. Updated `ExchangeCalendar` docstring to state that unlisted weekdays do NOT count as verified non-trading days; when `complete=True`, explicit holiday evidence is required for omitted weekdays, and when `complete=False`, unlisted dates return `has_evidence_for_date == False` and fail closed.
5. **D6 (Secret scanning baseline & CI fix):** Removed `{"path": "detect_secrets.filters.heuristic.is_lock_file"}` from `filters_used` in `.secrets.baseline` so `requirements.lock` is actively scanned. Removed stray comment from `.github/workflows/ci.yml`. Verified scanner catches leaks in `requirements.lock`.
6. **D7 (Dependency pinning & lockfile):** Added `"requests>=2.32.0"` to `[project.optional-dependencies] zerodha-readonly` in `pyproject.toml`. Pinned exact dependencies in `requirements.lock` (`kiteconnect==5.2.2`, `keyring==25.7.0`, `requests==2.34.2`, `ruff==0.17.3`, `pytest==9.2.0`, `pytest-cov==7.1.0`, `detect-secrets==1.5.0`). Added lockfile installation step in CI.

No live broker credentials or network requests were used. The KiteConnect integration test intercepts the genuine library's `requests.Session.request` transport.

This is not an M2b acceptance result. Independent adversarial review remains required; see `AUDIT_BRIEF.md`.
