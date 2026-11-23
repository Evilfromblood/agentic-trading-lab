"""Agent 1 — Market Analyst: algorithmic indicator calculation and structured model interpretation."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from agentic_trading.agents.envelope import AgentEnvelope, invoke_with_schema_guard
from agentic_trading.agents.llm_client import LLMClient
from agentic_trading.strategy.contracts import BarContext
from agentic_trading.strategy.indicators import atr, rsi, sma

AGENT_NAME = "market_analyst"
AGENT_VERSION = "1.0.0"
PROMPT_VERSION = "1.0.0"
SYSTEM_PROMPT = """You are a Quantitative Technical Market Analyst.
Analyze the provided algorithmic indicators and return a structured JSON response with:
- "view": "bullish", "neutral", or "bearish"
- "confidence": float in [0.0, 1.0]
- "evidence": list of strings citing specific numbers from the input payload
- "invalidation": price level where this view is invalidated (< close for bullish, > close for bearish)
- "risks": list of risk factors
- "data_quality": "ok" or "missing"
"""


def _extract_numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


class MarketAnalyst:
    """Computes technical indicators deterministically in Python and interprets via LLM."""

    def __init__(self, llm_client: LLMClient, model: str = "default-analyst") -> None:
        self.llm_client = llm_client
        self.model = model

    def analyze(self, context: BarContext, run_id: str) -> AgentEnvelope:
        bars = context.bars
        ticker = context.instrument.symbol
        as_of = context.decision_time

        if len(bars) < 20:
            user_payload: dict[str, Any] = {
                "ticker": ticker,
                "data_quality": "missing",
                "error": "insufficient_bars",
            }
            return AgentEnvelope(
                run_id=run_id,
                agent=AGENT_NAME,
                agent_version=AGENT_VERSION,
                prompt_version=PROMPT_VERSION,
                model=self.model,
                ticker=ticker,
                as_of=as_of,
                inputs_hash=f"sha256:insufficient_{ticker}",
                output={
                    "view": "neutral",
                    "confidence": 0.0,
                    "evidence": ["Insufficient bar count (< 20)"],
                    "invalidation": 0.0,
                    "risks": ["Data unavailable"],
                    "data_quality": "missing",
                },
                errors=("Insufficient bar count (< 20)",),
                latency_ms=0,
                cost_usd=Decimal("0"),
            )

        current_bar = bars[-1]
        close = current_bar.close
        s20 = sma(bars, 20)
        s50 = sma(bars, 50) if len(bars) >= 50 else None
        s200 = sma(bars, 200) if len(bars) >= 200 else None
        r14 = rsi(bars, 14)
        a14 = atr(bars, 14)

        last_20 = bars[-20:]
        avg_vol = sum((Decimal(b.volume) for b in last_20), Decimal("0")) / Decimal(len(last_20))
        vol_ratio = (
            (Decimal(current_bar.volume) / avg_vol)
            if avg_vol > Decimal("0")
            else Decimal("1.0")
        )

        lookback_high = bars[-50:] if len(bars) >= 50 else bars
        highest_high = max(b.high for b in lookback_high)
        dist_high_pct = (
            ((close - highest_high) / highest_high * Decimal("100"))
            if highest_high > Decimal("0")
            else Decimal("0")
        )

        support = min(b.low for b in last_20)
        resistance = max(b.high for b in last_20)

        data_quality = (
            "ok" if s20 is not None and r14 is not None and a14 is not None else "missing"
        )

        user_payload = {
            "ticker": ticker,
            "close": str(close),
            "sma_20": str(s20) if s20 is not None else "None",
            "sma_50": str(s50) if s50 is not None else "None",
            "sma_200": str(s200) if s200 is not None else "None",
            "rsi_14": str(r14) if r14 is not None else "None",
            "atr_14": str(a14) if a14 is not None else "None",
            "volume_ratio_20d": str(vol_ratio.quantize(Decimal("0.01"))),
            "distance_from_high_pct": str(dist_high_pct.quantize(Decimal("0.01"))),
            "support": str(support),
            "resistance": str(resistance),
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
            required_keys=("view", "confidence", "evidence", "invalidation", "risks", "data_quality"),
        )

        out = dict(envelope.output)
        view = str(out.get("view", "neutral")).lower()
        if view not in {"bullish", "neutral", "bearish"}:
            view = "neutral"
        out["view"] = view

        try:
            confidence = Decimal(str(out.get("confidence", "0.5")))
        except (ValueError, TypeError, ArithmeticError):
            confidence = Decimal("0.5")

        if data_quality != "ok":
            out["view"] = "neutral"
            confidence = min(confidence, Decimal("0.2"))
            out["data_quality"] = "missing"
        out["confidence"] = float(confidence)

        try:
            inv = Decimal(str(out.get("invalidation", "0")))
        except (ValueError, TypeError, ArithmeticError):
            inv = support if view == "bullish" else resistance

        if view == "bullish" and inv >= close:
            view = "neutral"
            out["view"] = "neutral"
            inv = support
            out["data_quality"] = "missing"
            confidence = min(confidence, Decimal("0.2"))
            out["confidence"] = float(confidence)
        elif view == "bearish" and inv <= close:
            view = "neutral"
            out["view"] = "neutral"
            inv = resistance
            out["data_quality"] = "missing"
            confidence = min(confidence, Decimal("0.2"))
            out["confidence"] = float(confidence)
        out["invalidation"] = float(inv)

        evidence_list = out.get("evidence", [])
        if not isinstance(evidence_list, list):
            evidence_list = [str(evidence_list)]

        payload_numbers: set[str] = set()
        for v in user_payload.values():
            payload_numbers.update(_extract_numbers(str(v)))

        has_hallucinated_number = False
        validated_evidence: list[str] = []
        for ev in evidence_list:
            ev_str = str(ev)
            ev_nums = _extract_numbers(ev_str)
            if ev_nums and any(n not in payload_numbers for n in ev_nums):
                has_hallucinated_number = True
                validated_evidence.append(
                    f"{ev_str} [UNVERIFIED NUMERIC EVIDENCE]"
                )
            elif ev_nums and all(n in payload_numbers for n in ev_nums):
                validated_evidence.append(ev_str)
            else:
                validated_evidence.append(
                    f"{ev_str} [Verified metrics: close={close}, support={support}, rsi={r14}]"
                )
        if has_hallucinated_number:
            out["data_quality"] = "missing"
            confidence = min(confidence, Decimal("0.3"))
            out["confidence"] = float(confidence)
        out["evidence"] = validated_evidence

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
