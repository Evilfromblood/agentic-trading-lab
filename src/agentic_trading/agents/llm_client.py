"""Framework-independent LLM client protocol, offline deterministic stub, and local Ollama client."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Protocol

_SAFE_MODEL_REGEX = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _reject_constant(val: str) -> None:
    raise ValueError(f"Invalid non-finite JSON constant: {val}")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Rejects HTTP redirects to prevent loopback bypass or host escalation."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise urllib.error.URLError(f"HTTP redirects are forbidden: status={code}")


def _extract_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    return text


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
    """Local Ollama client using standard library urllib with loopback isolation."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "gemma4:12b",
        timeout_seconds: float = 15.0,
        transport_fn: Callable[[urllib.request.Request, float], bytes] | None = None,
    ) -> None:
        clean_url = base_url.rstrip("/")
        parsed = urllib.parse.urlparse(clean_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"Invalid scheme for LocalOllamaJSONClient: {parsed.scheme!r}")
        hostname = (parsed.hostname or "").lower()
        if hostname not in _LOOPBACK_HOSTS:
            raise ValueError("LocalOllamaJSONClient requires a loopback host")

        if not _SAFE_MODEL_REGEX.match(default_model):
            raise ValueError(f"Invalid model identifier: {default_model!r}")

        self.base_url = clean_url
        self.default_model = default_model
        self.timeout_seconds = timeout_seconds
        self.transport_fn = transport_fn

    def complete_json(
        self,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        model: str,
    ) -> str:
        chosen_model = model or self.default_model
        if not _SAFE_MODEL_REGEX.match(chosen_model):
            raise ValueError(f"Invalid model identifier: {chosen_model!r}")

        prompt_text = (
            f"SYSTEM:\n{system_prompt}\n\nUSER INPUT:\n"
            f"{json.dumps(dict(user_payload), sort_keys=True)}"
        )
        data = json.dumps({
            "model": chosen_model,
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

        if self.transport_fn is not None:
            raw_bytes = self.transport_fn(req, self.timeout_seconds)
        else:
            opener = urllib.request.build_opener(_NoRedirectHandler())
            with opener.open(req, timeout=self.timeout_seconds) as resp:
                raw_bytes = resp.read(262145)

        if len(raw_bytes) > 262144:
            raise ValueError("Ollama response payload exceeded 262144 bytes limit")

        body = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_constant)
        if not isinstance(body, dict):
            raise ValueError("Ollama outer response must be a JSON object")

        raw_response = str(body.get("response", "{}"))
        inner_text = _extract_json_text(raw_response)
        parsed_inner = json.loads(inner_text, parse_constant=_reject_constant)
        if not isinstance(parsed_inner, dict):
            raise ValueError("Ollama inner response must be a JSON object")
        return inner_text


class FailoverLLMClient:
    """Invokes primary LLMClient with clean failover on connectivity or parsing failures."""

    def __init__(
        self,
        primary: LLMClient,
        fallback: LLMClient | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    def complete_json(
        self,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        model: str,
    ) -> str:
        try:
            resp = self.primary.complete_json(system_prompt, user_payload, model)
            parsed = json.loads(resp, parse_constant=_reject_constant)
            if not isinstance(parsed, dict):
                raise ValueError("Primary client response must be a JSON object")
            return resp
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            OSError,
            json.JSONDecodeError,
            ValueError,
        ):
            if self.fallback is not None:
                return self.fallback.complete_json(system_prompt, user_payload, model)
            return json.dumps({
                "data_quality": "missing",
                "fallback_reason": "primary_unreachable",
            })
