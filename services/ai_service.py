"""AI provider abstraction. Only this module knows about Groq."""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Callable

from utils.exceptions import AIConfigurationError, AIServiceError
from utils.security import scrub


class LLMProvider(ABC):
    name = "base"

    @abstractmethod
    def complete(self, system: str, user: str, json_mode: bool = False,
                 temperature: float = 0.0, max_tokens: int = 1500) -> str: ...


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile", timeout: float = 30.0):
        if not api_key:
            raise AIConfigurationError("No Groq API key configured. Add GROQ_API_KEY to .env or set it in Settings.")
        self._api_key = api_key
        self.model = model
        self._timeout = timeout
        self._client = None

    def _get_client(self):
        if self._client is None:
            from groq import Groq
            self._client = Groq(api_key=self._api_key, timeout=self._timeout, max_retries=1)
        return self._client

    def complete(self, system, user, json_mode=False, temperature=0.0, max_tokens=1500) -> str:
        kwargs = dict(model=self.model, temperature=temperature, max_tokens=max_tokens,
                      messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = self._get_client().chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as e:  # map provider errors to safe messages
            kind = type(e).__name__
            if kind == "AuthenticationError":
                raise AIConfigurationError("The Groq API key was rejected. Check the key in Settings / .env.") from e
            if kind == "RateLimitError":
                raise AIServiceError("The AI provider rate limit was reached. Wait a moment and try again.") from e
            if kind in ("APIConnectionError", "APITimeoutError"):
                raise AIServiceError("Could not reach the AI provider. Check your internet connection.") from e
            raise AIServiceError(f"The AI provider returned an error: {scrub(str(e), (self._api_key,))[:200]}") from e


class MockProvider(LLMProvider):
    """Deterministic provider for tests/offline demos. `responder(system, user) -> str`."""
    name = "mock"

    def __init__(self, responder: Callable[[str, str], str] | list[str]):
        self._responder = responder
        self.calls: list[tuple[str, str]] = []

    def complete(self, system, user, json_mode=False, temperature=0.0, max_tokens=1500) -> str:
        self.calls.append((system, user))
        if callable(self._responder):
            return self._responder(system, user)
        if not self._responder:
            raise AIServiceError("MockProvider has no more responses.")
        return self._responder.pop(0)


def build_provider(api_key: str | None, model: str) -> LLMProvider:
    return GroqProvider(api_key or "", model)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def parse_json_object(text: str) -> dict:
    text = _FENCE.sub("", (text or "").strip())
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        if a == -1 or b <= a:
            raise AIServiceError("The AI returned a response QueryMate could not read. Please try again.")
        try:
            obj = json.loads(text[a:b + 1])
        except json.JSONDecodeError as e:
            raise AIServiceError("The AI returned a malformed response. Please try again.") from e
    if not isinstance(obj, dict):
        raise AIServiceError("The AI returned an unexpected response shape.")
    return obj


class AIService:
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def complete_json(self, system: str, user: str, max_tokens: int = 1500) -> dict:
        return parse_json_object(self.provider.complete(system, user, json_mode=True, max_tokens=max_tokens))

    def complete_text(self, system: str, user: str, max_tokens: int = 900) -> str:
        return self.provider.complete(system, user, json_mode=False, temperature=0.2, max_tokens=max_tokens).strip()
