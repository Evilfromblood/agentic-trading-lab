"""Agent 2 — Data Analyst: fundamental financial snapshot evaluation and filing staleness checks."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from agentic_trading.agents.envelope import AgentEnvelope, invoke_with_schema_guard
from agentic_trading.agents.llm_client import LLMClient

AGENT_NAME = "data_analyst"
AGENT_VERSION = "1.0.0"
PROMPT_VERSION = "1.0.0"
SYSTEM_PROMPT = """You are a Fundamental Financial Data Analyst.
Evaluate corporate filing metrics and return a structured JSON response with:
- "quality": integer 1 to 5
- "growth": integer 1 to 5
- "valuation": integer 1 to 5
- "safety": integer 1 to 5
- "red_flags": list of identified risk flags
- "summary": concise narrative thesis
- "data_quality": "ok", "stale", or "missing"
"""


@dataclass(frozen=True)
class FundamentalSnapshot:
    symbol: str
    as_of_filing: date
    revenue_growth_yoy: Decimal
    operating_margin: Decimal
    fcf_margin: Decimal
    debt_to_equity: Decimal
    interest_coverage: Decimal
    pe_vs_peer_median: Decimal
    dilution_yoy: Decimal
    peer_set: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        if not isinstance(self.as_of_filing, date):
            raise TypeError("as_of_filing must be a date instance")
        if not isinstance(self.peer_set, tuple):
            object.__setattr__(self, "peer_set", tuple(self.peer_set))


class DataAnalyst:
    """Evaluates corporate financial statements and enforces filing staleness guards."""

    def __init__(
        self,
        llm_client: LLMClient,
        model: str = "default-analyst",
        max_filing_age_days: int = 180,
    ) -> None:
        self.llm_client = llm_client
        self.model = model
        self.max_filing_age_days = max_filing_age_days

    def analyze(
        self,
        snapshot: FundamentalSnapshot | None,
        ticker: str,
        as_of: datetime,
        run_id: str,
    ) -> AgentEnvelope:
        if snapshot is None:
            return AgentEnvelope(
                run_id=run_id,
                agent=AGENT_NAME,
                agent_version=AGENT_VERSION,
                prompt_version=PROMPT_VERSION,
                model=self.model,
                ticker=ticker,
                as_of=as_of,
                inputs_hash=f"sha256:missing_fundamentals_{ticker}",
                output={
                    "quality": 1,
                    "growth": 1,
                    "valuation": 1,
                    "safety": 1,
                    "red_flags": ["NO_FUNDAMENTAL_DATA"],
                    "summary": "No fundamental filing data available",
                    "data_quality": "missing",
                },
                errors=("No fundamental snapshot provided",),
                latency_ms=0,
                cost_usd=Decimal("0"),
            )

        filing_age_days = (as_of.date() - snapshot.as_of_filing).days
        is_stale = filing_age_days > self.max_filing_age_days
        data_quality = "stale" if is_stale else "ok"

        user_payload: dict[str, Any] = {
            "ticker": ticker,
            "as_of_filing": snapshot.as_of_filing.isoformat(),
            "filing_age_days": filing_age_days,
            "revenue_growth_yoy": str(snapshot.revenue_growth_yoy),
            "operating_margin": str(snapshot.operating_margin),
            "fcf_margin": str(snapshot.fcf_margin),
            "debt_to_equity": str(snapshot.debt_to_equity),
            "interest_coverage": str(snapshot.interest_coverage),
            "pe_vs_peer_median": str(snapshot.pe_vs_peer_median),
            "dilution_yoy": str(snapshot.dilution_yoy),
            "peer_set": list(snapshot.peer_set),
            "data_quality": data_quality,
        }

        envelope = invoke_with_schema_guard(
            run_id=run_id,
            agent=AGENT_NAME,
            agent_version=AGENT_VERSION,
            prompt_version=PROMPT_VERSION,
            model=self.model,
            ticker=ticker,
            as_of=as_of,
            user_payload=user_payload,
            caller=self.llm_client.complete_json,
            system_prompt=SYSTEM_PROMPT,
            required_keys=(
                "quality",
                "growth",
                "valuation",
                "safety",
                "red_flags",
                "summary",
                "data_quality",
            ),
        )

        out = dict(envelope.output)
        red_flags = list(out.get("red_flags", []))
        if not isinstance(red_flags, list):
            red_flags = [str(red_flags)]

        if is_stale:
            data_quality = "stale"
            if "STALE_FILING" not in red_flags:
                red_flags.append("STALE_FILING")

        def clamp_score(key: str, default: int = 3) -> int:
            try:
                val = int(out.get(key, default))
                clamped = max(1, min(5, val))
                return min(clamped, 3) if is_stale else clamped
            except (ValueError, TypeError):
                return default

        out["quality"] = clamp_score("quality")
        out["growth"] = clamp_score("growth")
        out["valuation"] = clamp_score("valuation")
        out["safety"] = clamp_score("safety")
        out["red_flags"] = red_flags
        out["data_quality"] = data_quality

        return AgentEnvelope(
            run_id=envelope.run_id,
            agent=envelope.agent,
            agent_version=envelope.agent_version,
            prompt_version=envelope.prompt_version,
            model=envelope.model,
            ticker=envelope.ticker,
            as_of=envelope.as_of,
            inputs_hash=envelope.inputs_hash,
            output=out,
            errors=envelope.errors,
            latency_ms=envelope.latency_ms,
            cost_usd=envelope.cost_usd,
        )
