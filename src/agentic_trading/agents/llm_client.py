"""Framework-independent LLM client protocol, offline deterministic stub, and local Ollama client."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Protocol


class LLMClient(Protocol):
    """Protocol for synchronous structured JSON completions."""

    def complete_json(
        self,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        model: str,
    ) -> str:
        ...


class DeterministicStubLLMClient:
    """Offline rule-based stub returning deterministic, schema-compliant JSON responses."""

    def __init__(
        self,
        handler: Callable[[str, Mapping[str, Any], str], str] | None = None,
        responses: Mapping[str, str] | None = None,
    ) -> None:
        self._handler = handler
        self._responses = dict(responses or {})

    def complete_json(
        self,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        model: str,
    ) -> str:
        ticker = str(user_payload.get("ticker", "DEFAULT"))
        if ticker in self._responses:
            return self._responses[ticker]
        for key, val in self._responses.items():
            if key in system_prompt or key in str(user_payload):
                return val
        if self._handler is not None:
            return self._handler(system_prompt, user_payload, model)

        if "Market" in system_prompt or "sma_20" in user_payload:
            close_val = user_payload.get("close", "100.0")
            support_val = user_payload.get("support", "95.0")
            resistance_val = user_payload.get("resistance", "105.0")
            return json.dumps({
                "view": "bullish",
                "confidence": 0.85,
                "evidence": [f"Price {close_val} is above support {support_val}"],
                "invalidation": float(support_val),
                "risks": [f"Resistance at {resistance_val}"],
                "data_quality": user_payload.get("data_quality", "ok"),
            })

        if "Fundamental" in system_prompt or "revenue_growth_yoy" in user_payload:
            return json.dumps({
                "quality": 4,
                "growth": 4,
                "valuation": 3,
                "safety": 4,
                "red_flags": [],
                "summary": "Strong revenue growth and conservative debt metrics",
                "data_quality": user_payload.get("data_quality", "ok"),
            })

        if "News" in system_prompt or "untrusted_articles" in user_payload:
            return json.dumps({
                "events": ["Positive product announcement"],
                "scheduled": [],
                "net_sentiment": 0.5,
                "blackout_suggested": False,
                "data_quality": user_payload.get("data_quality", "ok"),
            })

        if "Strategist" in system_prompt or "mandate" in user_payload:
            curr = float(user_payload.get("current_price", "100.0"))
            stop = round(curr * 0.95, 2)
            target = round(curr * 1.10, 2)
            return json.dumps({
                "action": "buy",
                "entry": curr,
                "stop": stop,
                "target": target,
                "horizon_days": 5,
                "confidence": 0.8,
                "thesis": "Bullish momentum aligned with fundamentals",
                "disagreement": "None",
                "invalidation": f"Break below {stop}",
                "reasoning": "High reward-to-risk setup",
            })

        return json.dumps({"status": "ok", "echo": user_payload.get("ticker", "none")})


class LocalOllamaJSONClient:
    """Local Ollama client using standard library urllib."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def complete_json(
        self,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        model: str,
    ) -> str:
        prompt_text = (
            f"SYSTEM:\n{system_prompt}\n\nUSER INPUT:\n"
            f"{json.dumps(dict(user_payload), sort_keys=True)}"
        )
        data = json.dumps({
            "model": model,
            "prompt": prompt_text,
            "format": "json",
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return str(body.get("response", "{}"))
