# Version 3 — Zerodha read-only connector

Builds on the India-market hybrid-agent project and adds a local FastAPI callback for Kite Connect authentication plus read-only endpoints for profile, holdings, positions and margins.

## Setup

1. Create a Kite Connect developer app in the official developer portal.
2. Configure the redirect URL as `http://127.0.0.1:8000/auth/callback`.
3. Copy `.env.example` to `.env` and add `KITE_API_KEY` and `KITE_API_SECRET` locally.
4. Create a Python 3.11+ virtual environment and run `pip install -e .`.
5. Start with `uvicorn agentic_trading.kite_web:app --host 127.0.0.1 --port 8000`.
6. Open `http://127.0.0.1:8000/login` and complete Zerodha login.

The Kite bridge is read-only. Live order placement is not implemented. Keep the local server bound to 127.0.0.1 and never commit `.env`, tokens or account data.