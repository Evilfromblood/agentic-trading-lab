# Batch 6 Remediation Audit Brief

Status: **remediation complete — M2b awaits independent review; M2c has not begun.**

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
- Full suite: 310 passed.
- Ruff and tracked-file `detect-secrets-hook --baseline .secrets.baseline`: passed.

## Required follow-up before independent acceptance

1. Have Claude perform an independent adversarial review of this frozen bundle.
2. Do not begin M2c until that review closes all critical and high-severity findings.
