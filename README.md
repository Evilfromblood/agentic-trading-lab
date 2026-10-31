# Agentic Trading Lab

Multi-agent AI equity research and paper-trading project for Indian markets (NSE/BSE), evolving from a US-market prototype to a Zerodha read-only integration.

## Versions
- `v1/`: Initial US-market prototype (AAPL/GOOGL/AMZN), OpenAI analyst committee, Yahoo Finance data, local paper broker.
- `v2-india/`: India-market version with hybrid OpenAI/Anthropic/Gemini agents, INR paper portfolio and risk gates.
- `v3-zerodha/`: India version plus a read-only Kite Connect bridge and local login callback.

## Safety
**Paper trading only. Live order placement is not implemented or enabled.** Zerodha does not provide an official Kite Connect sandbox, so use the local paper broker for simulated orders. Never commit API keys, secrets, access tokens, or account data. Copy `.env.example` to `.env` locally.

## Limitations
- Early prototypes use Yahoo Finance, which is not exchange-grade market data.
- v3 Kite integration is read-only: profile, holdings, positions and margins.
- Kite access tokens expire and must be refreshed through the official login flow.
- Educational software only; not investment advice or a promise of returns.

Each version directory contains its own README and setup instructions. Original ZIP snapshots are retained under `releases/`.
