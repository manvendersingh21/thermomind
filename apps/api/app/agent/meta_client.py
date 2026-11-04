"""Thin, redacting wrapper around the Meta Model API (OpenAI-compatible).

Live-verified behaviour of https://api.meta.ai/v1 with muse-spark-1.3 (2026-11-04):
  * `/chat/completions` with `tools=[{"type":"function",...}]` + `tool_choice="auto"` returns
    finish_reason "tool_calls" and `message.tool_calls[i].{id,function.name,function.arguments}`.
  * The standard OpenAI tool-result turn (`{"role":"tool","tool_call_id":..,"content":..}`)
    is accepted; the assistant message with tool_calls must be echoed back verbatim first.
  * `response_format={"type":"json_object"}` is accepted and yields JSON-only content.
  * muse-spark-1.3 is a reasoning model: `usage.completion_tokens_details.reasoning_tokens`
    counts against max_tokens. Small max_tokens (e.g. 20) produces content=None with
    finish_reason "length"; use >= 4000 for real work (config.META_MAX_TOKENS).
  * The message we store/re-send is reduced to role/content/tool_calls only, so no
    provider-specific reasoning payload is ever persisted or shown.

Secrets: the API key is never logged, never included in exceptions, never returned by ping().
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

_KEY_LIKE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9_\-\.]{8,})")


class MetaClientError(RuntimeError):
    """Safe, key-free description of a failed Meta API call."""


@dataclass
class ChatResult:
    message: dict[str, Any]
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    model: str = ""
    finish_reason: str | None = None


def _redact(text: str, api_key: str | None) -> str:
    text = str(text)
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = _KEY_LIKE.sub("[REDACTED]", text)
    return text[:400]


def _serialize_message(msg: Any) -> dict[str, Any]:
    """Reduce an SDK ChatCompletionMessage to a plain, re-sendable dict."""
    out: dict[str, Any] = {"role": getattr(msg, "role", "assistant") or "assistant",
                           "content": getattr(msg, "content", None)}
    tool_calls = getattr(msg, "tool_calls", None) or []
    if tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
            }
            for tc in tool_calls
        ]
    return out


def _usage_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    try:
        d = usage.model_dump(exclude_none=True)
    except Exception:  # pragma: no cover - defensive
        return {}
    out: dict[str, Any] = {k: v for k, v in d.items() if isinstance(v, int)}
    details = d.get("completion_tokens_details") or {}
    if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int):
        out["reasoning_tokens"] = details["reasoning_tokens"]
    return out


class MetaClient:
    def __init__(self, api_key: str | None, base_url: str, model: str, timeout_s: float):
        self._api_key = api_key or None
        self.base_url = base_url
        self.model = model
        self.timeout_s = float(timeout_s)
        self._client = None
        if self._api_key:
            from openai import OpenAI  # imported lazily so offline mode needs no SDK init

            self._client = OpenAI(api_key=self._api_key, base_url=base_url,
                                  timeout=self.timeout_s, max_retries=2)

    @property
    def configured(self) -> bool:
        return self._client is not None

    # ------------------------------------------------------------------
    def chat(self, messages: list[dict], tools: list[dict] | None, max_tokens: int,
             response_format: dict | None = None) -> ChatResult:
        if not self.configured:
            raise MetaClientError("Meta API key not configured")
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": int(max_tokens),
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if response_format:
            kwargs["response_format"] = response_format
        t0 = time.perf_counter()
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - everything becomes a safe error
            raise MetaClientError(self._safe_error(exc)) from None
        latency_ms = int((time.perf_counter() - t0) * 1000)
        if not getattr(resp, "choices", None):
            raise MetaClientError("Meta API returned no choices")
        choice = resp.choices[0]
        return ChatResult(
            message=_serialize_message(choice.message),
            usage=_usage_dict(getattr(resp, "usage", None)),
            latency_ms=latency_ms,
            model=getattr(resp, "model", None) or self.model,
            finish_reason=getattr(choice, "finish_reason", None),
        )

    def ping(self) -> dict:
        if not self.configured:
            return {"ok": False, "model": self.model, "latency_ms": 0, "error": "not configured"}
        try:
            res = self.chat(
                [{"role": "user", "content": "Reply with the single word: pong"}],
                tools=None, max_tokens=300,
            )
        except MetaClientError as exc:
            return {"ok": False, "model": self.model, "latency_ms": 0, "error": str(exc)}
        return {"ok": True, "model": res.model or self.model, "latency_ms": res.latency_ms, "error": None}

    # ------------------------------------------------------------------
    def _safe_error(self, exc: Exception) -> str:
        name = type(exc).__name__
        status = getattr(exc, "status_code", None)
        if name == "AuthenticationError" or status == 401:
            return "Meta API authentication failed (401); check the configured key"
        if name == "RateLimitError" or status == 429:
            return "Meta API rate limited (429)"
        if name == "APITimeoutError":
            return f"Meta API timed out after {self.timeout_s:.0f}s"
        if name == "APIConnectionError":
            return "Meta API connection error"
        detail = _redact(getattr(exc, "message", None) or str(exc), self._api_key)
        if status:
            return f"Meta API error {status}: {detail}"
        return f"Meta API error ({name}): {detail}"
