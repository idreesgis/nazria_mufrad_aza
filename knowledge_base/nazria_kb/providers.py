"""LLM provider layer: one small interface, three adapters, one retry policy.

    LLMProvider.complete(messages, max_tokens=, temperature=) -> Completion
    LLMProvider.stream(messages, max_tokens=, temperature=)   -> Iterator[str]   (text deltas)

| NAZRIA_LLM_PROVIDER | adapter                    | SDK            | runs off-premises |
|---------------------|----------------------------|----------------|-------------------|
| openai              | OpenAICompatibleProvider   | openai         | yes               |
| deepseek            | OpenAICompatibleProvider   | openai         | yes               |
| local               | OpenAICompatibleProvider   | openai         | no (vLLM / Ollama / LM Studio / llama.cpp) |
| anthropic           | AnthropicProvider          | anthropic      | yes               |
| gemini              | GeminiProvider             | google-genai   | yes               |

* Model names always come from configuration (``NAZRIA_LLM_MODEL``); nothing here hard-codes a model id.
* API keys are read from the environment variable *named* by ``NAZRIA_LLM_API_KEY_ENV`` (default per provider);
  they are never logged, stored or put into error messages.
* External providers refuse to run unless ``NAZRIA_ALLOW_EXTERNAL_PROVIDERS=true``.
* SDK-internal retries are disabled; ``_with_retries`` applies one policy (exponential backoff + jitter) to every
  provider and turns every failure into a ``ProviderError`` with a clear, key-free message.
"""
from __future__ import annotations

import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator, Protocol

log = logging.getLogger("nazria_kb.providers")

PROVIDERS = {
    "openai": "OpenAI Chat Completions API",
    "deepseek": "DeepSeek (OpenAI-compatible API)",
    "local": "Locally deployed model behind an OpenAI-compatible server (vLLM, Ollama, LM Studio, llama.cpp)",
    "anthropic": "Anthropic Claude Messages API",
    "gemini": "Google Gemini API",
}
EXTERNAL_PROVIDERS = frozenset({"openai", "deepseek", "anthropic", "gemini"})
LOCAL_STACKS = {                       # default OpenAI-compatible endpoints; NAZRIA_LLM_BASE_URL overrides
    "vllm": "http://localhost:8000/v1",
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "llamacpp": "http://localhost:8080/v1",
}
DEFAULT_BASE_URLS = {"deepseek": "https://api.deepseek.com", "anthropic": "https://api.anthropic.com"}
DEFAULT_API_KEY_ENV = {"openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
                       "gemini": "GEMINI_API_KEY", "local": "NAZRIA_LOCAL_API_KEY"}
_TRUE = {"1", "true", "yes", "on"}


def env_flag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in _TRUE


# --------------------------------------------------------------------------- data types
@dataclass
class Completion:
    text: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int
    provider: str = ""


class ProviderError(RuntimeError):
    """Any provider failure. ``kind``: config | policy | sdk_missing | auth | not_found | bad_request |
    rate_limit | timeout | connection | server | empty | unknown."""

    def __init__(self, provider: str, kind: str, message: str, retryable: bool = False):
        super().__init__(f"[{provider}] {kind}: {message}")
        self.provider, self.kind, self.retryable = provider, kind, retryable


class LLMProvider(Protocol):
    name: str          # provider id, e.g. "local"
    model: str
    external: bool     # True if patient text leaves the premises

    def complete(self, messages: list[dict], *, max_tokens: int, temperature: float | None) -> Completion: ...

    def stream(self, messages: list[dict], *, max_tokens: int, temperature: float | None) -> Iterator[str]: ...


# --------------------------------------------------------------------------- configuration
@dataclass
class ProviderConfig:
    provider: str
    model: str
    base_url: str | None = None
    local_stack: str | None = None
    api_key_env: str | None = None
    timeout_s: float = 60.0
    max_retries: int = 3               # retries after the first attempt
    backoff_s: float = 1.0
    backoff_max_s: float = 20.0
    allow_external: bool = False

    @classmethod
    def from_env(cls, provider: str | None = None, model: str | None = None) -> "ProviderConfig":
        e = os.environ.get
        return cls(provider=(provider or e("NAZRIA_LLM_PROVIDER") or "").strip().lower(),
                   model=model or e("NAZRIA_LLM_MODEL") or "", base_url=e("NAZRIA_LLM_BASE_URL") or None,
                   local_stack=(e("NAZRIA_LOCAL_STACK") or "").strip().lower() or None,
                   api_key_env=e("NAZRIA_LLM_API_KEY_ENV") or None,
                   timeout_s=float(e("NAZRIA_LLM_TIMEOUT_S", "60")), max_retries=int(e("NAZRIA_LLM_MAX_RETRIES", "3")),
                   allow_external=env_flag("NAZRIA_ALLOW_EXTERNAL_PROVIDERS"))

    @property
    def external(self) -> bool:
        return self.provider in EXTERNAL_PROVIDERS

    def resolved_base_url(self) -> str | None:
        if self.base_url:
            return self.base_url.rstrip("/")
        if self.provider == "local":
            return LOCAL_STACKS.get(self.local_stack or "")
        return DEFAULT_BASE_URLS.get(self.provider)

    def key_env(self) -> str:
        return self.api_key_env or DEFAULT_API_KEY_ENV.get(self.provider, "")

    def validate(self) -> None:
        p = self.provider
        if p not in PROVIDERS:
            raise ProviderError(p or "?", "config", f"NAZRIA_LLM_PROVIDER must be one of {sorted(PROVIDERS)}, got {p!r}")
        if not self.model:
            raise ProviderError(p, "config", "NAZRIA_LLM_MODEL is required (the model name comes from configuration)")
        if p == "local":
            if self.local_stack and self.local_stack not in LOCAL_STACKS:
                raise ProviderError(p, "config", f"NAZRIA_LOCAL_STACK must be one of {sorted(LOCAL_STACKS)}, "
                                                 f"got {self.local_stack!r}")
            if not self.resolved_base_url():
                raise ProviderError(p, "config", "set NAZRIA_LOCAL_STACK (vllm|ollama|lmstudio|llamacpp) "
                                                 "or NAZRIA_LLM_BASE_URL for the local provider")
        if self.external and not self.allow_external:
            raise ProviderError(p, "policy", "external providers are disabled; set NAZRIA_ALLOW_EXTERNAL_PROVIDERS=true "
                                             "to allow patient text to be sent off-premises (see the data policy)")
        if self.timeout_s <= 0 or self.max_retries < 0:
            raise ProviderError(p, "config", "NAZRIA_LLM_TIMEOUT_S must be > 0 and NAZRIA_LLM_MAX_RETRIES >= 0")

    def api_key(self) -> str | None:
        name = self.key_env()
        key = os.environ.get(name) if name else None
        if not key and self.provider != "local":
            raise ProviderError(self.provider, "config", f"API key not found: set the environment variable {name} "
                                                         f"(or point NAZRIA_LLM_API_KEY_ENV at the variable that holds it)")
        return key or None


# --------------------------------------------------------------------------- reasoning models
_THINK_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.S | re.I)
_THINK_OPEN_RE = re.compile(r"<(?:think|thinking|reasoning)>.*\Z", re.S | re.I)


def strip_reasoning(text: str | None) -> str:
    """Remove the chain of thought that reasoning models (DeepSeek-R1, QwQ …) put in <think>…</think>.
    It is never shown to a patient. An unclosed block (answer cut off by max_tokens) leaves no answer."""
    text = _THINK_RE.sub("", text or "")
    text = _THINK_OPEN_RE.sub("", text)
    return text.replace("</think>", "").strip()


# --------------------------------------------------------------------------- errors and retries
def classify_error(provider: str, exc: BaseException, secret: str | None = None) -> ProviderError:
    """Map SDK / transport exceptions of any provider to a ProviderError (duck-typed, no SDK imports)."""
    if isinstance(exc, ProviderError):
        return exc
    names = {c.__name__ for c in type(exc).__mro__}
    msg = str(exc).strip().splitlines()[0][:300] if str(exc).strip() else type(exc).__name__
    if secret:
        msg = msg.replace(secret, "<key>")
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = getattr(exc, "code", None) if isinstance(getattr(exc, "code", None), int) else None
    if any("Timeout" in n or "DeadlineExceeded" in n for n in names) or isinstance(exc, TimeoutError):
        return ProviderError(provider, "timeout", f"request timed out ({msg})", True)
    if status is not None:
        if status in (401, 403):
            return ProviderError(provider, "auth", f"HTTP {status}: authentication failed – check the API key "
                                                   f"variable and the account's access ({msg})")
        if status == 404:
            return ProviderError(provider, "not_found", f"HTTP 404 – check NAZRIA_LLM_MODEL and the base URL ({msg})")
        if status in (408, 409, 425, 429):
            return ProviderError(provider, "rate_limit", f"HTTP {status}: rate limited or busy ({msg})", True)
        if status >= 500:
            return ProviderError(provider, "server", f"HTTP {status}: provider server error ({msg})", True)
        return ProviderError(provider, "bad_request", f"HTTP {status}: request rejected ({msg})")
    if any("Connect" in n or "Transport" in n or "NetworkError" in n for n in names) or isinstance(exc, OSError):
        return ProviderError(provider, "connection", f"cannot reach the provider – is the server running and the "
                                                     f"base URL correct? ({msg})", True)
    return ProviderError(provider, "unknown", f"{type(exc).__name__}: {msg}")


def _with_retries(fn: Callable[[], Completion], provider: str, cfg: ProviderConfig, secret: str | None,
                  sleep: Callable[[float], None] = time.sleep) -> Completion:
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - every failure becomes a ProviderError
            err = classify_error(provider, exc, secret)
            if not err.retryable or attempt >= cfg.max_retries:
                raise err from None
            delay = min(cfg.backoff_max_s, cfg.backoff_s * (2 ** attempt)) * (0.5 + random.random() / 2)
            log.warning("%s (attempt %d/%d), retrying in %.1fs", err, attempt + 1, cfg.max_retries + 1, delay)
            sleep(delay)
            attempt += 1


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """System text joined; remaining turns with consecutive same-role turns merged; first turn is 'user'."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            continue
        role = "assistant" if m["role"] == "assistant" else "user"
        if turns and turns[-1]["role"] == role:
            turns[-1] = {"role": role, "content": turns[-1]["content"] + "\n\n" + m["content"]}
        else:
            turns.append({"role": role, "content": m["content"]})
    if turns and turns[0]["role"] != "user":
        turns.insert(0, {"role": "user", "content": "…"})
    return system, turns


# --------------------------------------------------------------------------- adapters
class _Base:
    name = ""
    external = False

    def __init__(self, cfg: ProviderConfig, client=None, sleep: Callable[[float], None] = time.sleep):
        self.cfg, self.model, self.name, self.external = cfg, cfg.model, cfg.provider, cfg.external
        self._key = cfg.api_key()
        self._sleep = sleep
        self.client = client if client is not None else self._make_client()

    def _make_client(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def _once(self, messages, max_tokens, temperature) -> tuple[str, str | None, int | None, int | None]:
        raise NotImplementedError  # pragma: no cover

    def complete(self, messages: list[dict], *, max_tokens: int, temperature: float | None) -> Completion:
        def call() -> Completion:
            t0 = time.perf_counter()
            text, model, pt, ct = self._once(messages, max_tokens, temperature)
            text = strip_reasoning(text)
            if not (text or "").strip():
                raise ProviderError(self.name, "empty", "the model returned no answer text (blocked, empty, or only "
                                                        "reasoning – raise NAZRIA_LLM_MAX_TOKENS for reasoning models)",
                                    True)
            return Completion(text.strip(), model or self.model, pt, ct, int((time.perf_counter() - t0) * 1000), self.name)
        return _with_retries(call, self.name, self.cfg, self._key, self._sleep)

    def stream(self, messages: list[dict], *, max_tokens: int, temperature: float | None) -> Iterator[str]:
        """Text deltas. Connection errors before the first delta are retried; later ones raise ProviderError."""
        attempt = 0
        while True:
            started = False
            try:
                for delta in self._stream_once(messages, max_tokens, temperature):
                    started = True
                    if delta:
                        yield delta
                return
            except Exception as exc:  # noqa: BLE001
                err = classify_error(self.name, exc, self._key)
                if started or not err.retryable or attempt >= self.cfg.max_retries:
                    raise err from None
                self._sleep(min(self.cfg.backoff_max_s, self.cfg.backoff_s * (2 ** attempt)))
                attempt += 1

    def _stream_once(self, messages, max_tokens, temperature) -> Iterator[str]:  # pragma: no cover
        raise NotImplementedError


class OpenAICompatibleProvider(_Base):
    """openai, deepseek and every local stack (vLLM, Ollama, LM Studio, llama.cpp) – Chat Completions API."""

    def _make_client(self):
        try:
            import openai
        except ImportError:
            raise ProviderError(self.name, "sdk_missing", "pip install openai") from None
        return openai.OpenAI(api_key=self._key or "not-needed", base_url=self.cfg.resolved_base_url(),
                             timeout=self.cfg.timeout_s, max_retries=0)

    def _params(self, messages, max_tokens, temperature) -> dict:
        p = {"model": self.model, "messages": [{"role": m["role"], "content": m["content"]} for m in messages]}
        # OpenAI deprecated max_tokens for max_completion_tokens; compatible servers still expect max_tokens.
        p["max_completion_tokens" if self.name == "openai" else "max_tokens"] = max_tokens
        if temperature is not None:
            p["temperature"] = temperature
        return p

    def _once(self, messages, max_tokens, temperature):
        r = self.client.chat.completions.create(**self._params(messages, max_tokens, temperature))
        if not r.choices:
            return "", r.model, None, None
        u = r.usage
        return (r.choices[0].message.content or ""), r.model, getattr(u, "prompt_tokens", None), \
            getattr(u, "completion_tokens", None)

    def _stream_once(self, messages, max_tokens, temperature):
        for chunk in self.client.chat.completions.create(stream=True, **self._params(messages, max_tokens, temperature)):
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class AnthropicProvider(_Base):
    """Claude Messages API. The system prompt is a separate parameter. The current Messages API has no
    ``temperature`` parameter, so the configured temperature is not sent (generation is not guaranteed
    deterministic on this provider)."""

    def _make_client(self):
        try:
            import anthropic
        except ImportError:
            raise ProviderError(self.name, "sdk_missing", "pip install anthropic") from None
        # explicit base_url so an unrelated ANTHROPIC_BASE_URL in the environment is never picked up
        return anthropic.Anthropic(api_key=self._key, base_url=self.cfg.resolved_base_url(),
                                   timeout=self.cfg.timeout_s, max_retries=0)

    def _params(self, messages, max_tokens):
        system, turns = _split_system(messages)
        p = {"model": self.model, "max_tokens": max_tokens, "messages": turns}
        if system:
            p["system"] = system
        return p

    def _once(self, messages, max_tokens, temperature):
        r = self.client.messages.create(**self._params(messages, max_tokens))
        text = "".join(getattr(b, "text", "") for b in r.content if getattr(b, "type", "") == "text")
        u = r.usage
        return text, r.model, getattr(u, "input_tokens", None), getattr(u, "output_tokens", None)

    def _stream_once(self, messages, max_tokens, temperature):
        with self.client.messages.stream(**self._params(messages, max_tokens)) as st:
            yield from st.text_stream


class GeminiProvider(_Base):
    """Google Gemini via google-genai. Roles: assistant -> model; system -> system_instruction."""

    def _make_client(self):
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ProviderError(self.name, "sdk_missing", "pip install google-genai") from None
        opts = types.HttpOptions(timeout=int(self.cfg.timeout_s * 1000),   # milliseconds in google-genai
                                 base_url=self.cfg.base_url or None)
        return genai.Client(api_key=self._key, http_options=opts)

    def _request(self, messages, max_tokens, temperature):
        from google.genai import types
        system, turns = _split_system(messages)
        contents = [types.Content(role="model" if t["role"] == "assistant" else "user",
                                  parts=[types.Part.from_text(text=t["content"])]) for t in turns]
        cfg = types.GenerateContentConfig(system_instruction=system or None, max_output_tokens=max_tokens,
                                          temperature=temperature)
        return {"model": self.model, "contents": contents, "config": cfg}

    def _once(self, messages, max_tokens, temperature):
        r = self.client.models.generate_content(**self._request(messages, max_tokens, temperature))
        u = r.usage_metadata
        return (r.text or ""), getattr(r, "model_version", None), getattr(u, "prompt_token_count", None), \
            getattr(u, "candidates_token_count", None)

    def _stream_once(self, messages, max_tokens, temperature):
        for chunk in self.client.models.generate_content_stream(**self._request(messages, max_tokens, temperature)):
            if chunk.text:
                yield chunk.text


ADAPTERS = {"openai": OpenAICompatibleProvider, "deepseek": OpenAICompatibleProvider,
            "local": OpenAICompatibleProvider, "anthropic": AnthropicProvider, "gemini": GeminiProvider}


def build_provider(cfg: ProviderConfig, client=None) -> LLMProvider:
    """Validated provider instance. Raises ProviderError (config / policy / sdk_missing) with a clear message."""
    cfg.validate()
    return ADAPTERS[cfg.provider](cfg, client=client)


# --------------------------------------------------------------------------- fake provider (tests, offline demos)
@dataclass
class FakeProvider:
    """Deterministic stand-in. ``responses``: list of strings / exceptions consumed in order (the last one
    repeats), or a callable(messages) -> str."""
    responses: list | Callable[[list[dict]], str] = field(default_factory=lambda: ["[NOT_COVERED]"])
    name: str = "fake"
    model: str = "fake-model"
    external: bool = False
    calls: list = field(default_factory=list)

    def complete(self, messages, *, max_tokens, temperature) -> Completion:
        self.calls.append({"messages": messages, "max_tokens": max_tokens, "temperature": temperature})
        if callable(self.responses):
            out = self.responses(messages)
        else:
            out = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(out, BaseException):
            raise out
        prompt = sum(len(m["content"]) for m in messages) // 4
        return Completion(out, self.model, prompt, len(out) // 4, 5, self.name)

    def stream(self, messages, *, max_tokens, temperature) -> Iterator[str]:
        yield from self.complete(messages, max_tokens=max_tokens, temperature=temperature).text.split(" ")
