# Batch 6 Remediation Audit Brief

Status: **remediation snapshot only — M2b is not accepted and M2c has not begun.**

## Implemented direction

- The Zerodha facade no longer overwrites methods on an injected KiteConnect client.
- Its public allowlist admits read operations only and rejects order, GTT, MF/SIP,
  token/session mutation, and low-level request entry points before its transport.
- The threat model is explicit: Python objects in the same process are not a hostile-code
  security boundary. Broker-scoped read-only credentials and egress controls are required.
- Keyring calls are best effort, so absent or unconfigured OS keyrings do not prevent
  construction of a connector with an injected client.
- Complete explicit calendars now require holiday or special-session evidence for each
  omitted weekday and reject contradictory declarations.
- CI installs the `zerodha-readonly` extra and pins detect-secrets 1.5.0. The baseline
  now uses anchored directory/file exclusions and no longer excludes `.github` or ZIP files.

## Verification evidence

- Targeted genuine KiteConnect 5.2.2 integration: 8 passed. Its HTTP transport was
  intercepted; `profile()` made one GET and each blocked operation made zero requests.
- Targeted Ruff and detect-secrets checks: passed.
- Full suite: 275 passed, 15 failed. These failures are obsolete Batch 2–5 tests that
  assert the rejected reflection-hiding architecture, permit `generate_session`, or
  rely on sparse complete calendars. The two ingestion tests reach the gate but currently
  return `QUALITY_GATE_REJECTED` rather than the expected `MARKET_CALENDAR_REQUIRED`.

## Required follow-up before independent acceptance

1. Replace the obsolete Batch 2–5 safety tests with the Batch 6 threat model and exact
   request-level assertions.
2. Correct the ingestion error classification and add D1/M5 exact-code coverage for NSE,
   BSE, NYSE, and NASDAQ.
3. Add a CI fixture that proves detection across workflow files, `.env`, and nested ZIP
   content without putting a real secret in the repository.
4. Re-run all supported Python environments and freeze a clean, fully passing bundle.
