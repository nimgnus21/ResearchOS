"""LLM providers behind one interface: `complete_json(system, user, schema) -> dict`.

Providers:
* anthropic  — official Anthropic SDK, structured output via output_config.format (JSON schema).
* openai     — any OpenAI-compatible /chat/completions endpoint (response_format=json_schema).
* none       — no model configured. Callers must detect this and report it; nothing is faked.

API keys come only from environment variables and are never logged.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.config import Settings, get_settings

log = logging.getLogger(__name__)


class LLMNotConfigured(Exception):
    pass


class LLMError(Exception):
    pass


@dataclass
class LLMResult:
    data: dict
    model: str
    provider: str
    latency_ms: int
    usage: dict = field(default_factory=dict)


class LLMProvider(Protocol):
    provider: str
    model: str

    def complete_json(self, system: str, user: str, schema: dict, max_tokens: int | None = None) -> LLMResult: ...


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"模型输出不是合法 JSON：{exc}") from exc


class AnthropicProvider:
    provider = "anthropic"

    def __init__(self, settings: Settings):
        import anthropic

        if not settings.llm_api_key:
            raise LLMNotConfigured("LLM_PROVIDER=anthropic 但未设置 LLM_API_KEY")
        self._anthropic = anthropic
        kwargs = {"api_key": settings.llm_api_key, "timeout": settings.llm_timeout_s, "max_retries": 2}
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url
        self.client = anthropic.Anthropic(**kwargs)
        self.model = settings.llm_model
        self.settings = settings

    def complete_json(self, system: str, user: str, schema: dict, max_tokens: int | None = None) -> LLMResult:
        a = self._anthropic
        started = time.monotonic()
        extra: dict = {}
        if self.settings.llm_fallbacks == "default":
            # Server-side refusal fallback: the API re-runs a declined request on a fallback model.
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        try:
            with self.client.beta.messages.stream(
                **extra,
                model=self.model,
                max_tokens=max_tokens or self.settings.llm_max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                thinking={"type": "adaptive"},
                output_config={
                    "effort": self.settings.llm_effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
            ) as stream:
                response = stream.get_final_message()
        except a.AuthenticationError as exc:
            raise LLMError("Anthropic 认证失败（请检查 LLM_API_KEY）") from exc
        except a.RateLimitError as exc:
            raise LLMError("Anthropic 速率限制（HTTP 429），请稍后重试") from exc
        except a.BadRequestError as exc:
            raise LLMError(f"Anthropic 请求无效：{exc.message}") from exc
        except a.APIStatusError as exc:
            raise LLMError(f"Anthropic API 错误 HTTP {exc.status_code}") from exc
        except a.APIConnectionError as exc:
            raise LLMError("无法连接 Anthropic API（网络错误）") from exc

        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None) if response.stop_details else None
            raise LLMError(f"模型拒绝回答（refusal, category={category}）")
        if response.stop_reason == "max_tokens":
            raise LLMError("模型输出被 max_tokens 截断，请提高 LLM_MAX_TOKENS")
        text = next((b.text for b in response.content if b.type == "text"), "")
        usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
        return LLMResult(
            data=_parse_json(text),
            model=response.model,
            provider=self.provider,
            latency_ms=int((time.monotonic() - started) * 1000),
            usage=usage,
        )


class OpenAICompatibleProvider:
    provider = "openai"

    def __init__(self, settings: Settings):
        if not settings.llm_api_key:
            raise LLMNotConfigured("LLM_PROVIDER=openai 但未设置 LLM_API_KEY")
        self.settings = settings
        self.model = settings.llm_model
        self.base_url = (settings.llm_base_url or "https://api.openai.com/v1").rstrip("/")

    def complete_json(self, system: str, user: str, schema: dict, max_tokens: int | None = None) -> LLMResult:
        started = time.monotonic()
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "research_output", "schema": schema, "strict": False},
            },
            "max_tokens": max_tokens or self.settings.llm_max_tokens,
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                timeout=self.settings.llm_timeout_s,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"无法连接模型接口：{type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise LLMError(f"模型接口返回 HTTP {resp.status_code}: {resp.text[:300]}")
        payload = resp.json()
        choice = payload["choices"][0]
        if choice.get("finish_reason") == "length":
            raise LLMError("模型输出被截断（finish_reason=length）")
        return LLMResult(
            data=_parse_json(choice["message"]["content"] or ""),
            model=payload.get("model", self.model),
            provider=self.provider,
            latency_ms=int((time.monotonic() - started) * 1000),
            usage=payload.get("usage", {}),
        )


_override: LLMProvider | None = None
_cached: LLMProvider | None = None


def set_llm(provider: LLMProvider | None):
    """Inject a provider (used by tests with a scripted test double)."""
    global _override, _cached
    _override = provider
    _cached = None


def get_llm() -> LLMProvider:
    """Return the configured provider or raise LLMNotConfigured."""
    global _cached
    if _override is not None:
        return _override
    if _cached is not None:
        return _cached
    s = get_settings()
    if s.llm_provider in ("", "none"):
        raise LLMNotConfigured("未配置大模型（LLM_PROVIDER=none）")
    if s.llm_provider == "anthropic":
        _cached = AnthropicProvider(s)
    elif s.llm_provider == "openai":
        _cached = OpenAICompatibleProvider(s)
    else:
        raise LLMNotConfigured(f"未知的 LLM_PROVIDER: {s.llm_provider}")
    return _cached


def llm_status() -> dict:
    try:
        p = get_llm()
        return {"configured": True, "provider": p.provider, "model": p.model}
    except LLMNotConfigured as exc:
        return {"configured": False, "provider": None, "model": None, "reason": str(exc)}
