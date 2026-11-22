"""Provider adapters: OpenAI-compatible (openai / deepseek / every local stack) against a mock HTTP server,
Claude and Gemini through their real SDKs with an httpx mock transport. No real API calls."""
import json
import sys
from pathlib import Path

import httpx2 as httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mock_openai import MockOpenAIServer  # noqa: E402
from nazria_kb.providers import (LOCAL_STACKS, AnthropicProvider, GeminiProvider,  # noqa: E402
                                 OpenAICompatibleProvider, ProviderConfig, ProviderError, build_provider,
                                 classify_error)

MSGS = [{"role": "system", "content": "آپ حکیم ہیں"}, {"role": "user", "content": "قبض کا علاج؟"}]
NO_SLEEP = lambda s: None  # noqa: E731


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("NAZRIA_LLM_PROVIDER", "NAZRIA_LLM_MODEL", "NAZRIA_LLM_BASE_URL", "NAZRIA_LOCAL_STACK",
              "NAZRIA_LLM_API_KEY_ENV", "NAZRIA_ALLOW_EXTERNAL_PROVIDERS", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
              "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "NAZRIA_LOCAL_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def local_cfg(url, **kw):
    return ProviderConfig(provider="local", model="my-local-model", base_url=url, backoff_s=0, **kw)


# --------------------------------------------------------------------------- configuration / policy
@pytest.mark.parametrize("stack", sorted(LOCAL_STACKS))
def test_local_stack_presets_and_override(monkeypatch, stack):
    monkeypatch.setenv("NAZRIA_LLM_PROVIDER", "local")
    monkeypatch.setenv("NAZRIA_LLM_MODEL", "m")
    monkeypatch.setenv("NAZRIA_LOCAL_STACK", stack)
    cfg = ProviderConfig.from_env()
    assert cfg.resolved_base_url() == LOCAL_STACKS[stack] and not cfg.external
    cfg.validate()                                   # local always runs, no key needed
    monkeypatch.setenv("NAZRIA_LLM_BASE_URL", "http://gpu-box:9000/v1/")
    assert ProviderConfig.from_env().resolved_base_url() == "http://gpu-box:9000/v1"


def test_local_defaults():
    assert LOCAL_STACKS == {"vllm": "http://localhost:8000/v1", "ollama": "http://localhost:11434/v1",
                            "lmstudio": "http://localhost:1234/v1", "llamacpp": "http://localhost:8080/v1"}
    with pytest.raises(ProviderError, match="NAZRIA_LOCAL_STACK"):
        ProviderConfig(provider="local", model="m").validate()
    with pytest.raises(ProviderError, match="must be one of"):
        ProviderConfig(provider="local", model="m", local_stack="tgi").validate()


@pytest.mark.parametrize("provider", ["openai", "deepseek", "anthropic", "gemini"])
def test_external_providers_refuse_without_setting(monkeypatch, provider):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = ProviderConfig(provider=provider, model="m", api_key_env="OPENAI_API_KEY")
    with pytest.raises(ProviderError) as e:
        build_provider(cfg)
    assert e.value.kind == "policy" and "NAZRIA_ALLOW_EXTERNAL_PROVIDERS" in str(e.value)
    monkeypatch.setenv("NAZRIA_ALLOW_EXTERNAL_PROVIDERS", "true")
    assert ProviderConfig.from_env(provider, "m").allow_external


def test_missing_model_and_key_messages(monkeypatch):
    with pytest.raises(ProviderError, match="NAZRIA_LLM_MODEL"):
        ProviderConfig(provider="openai", model="", allow_external=True).validate()
    with pytest.raises(ProviderError, match="DEEPSEEK_API_KEY") as e:
        build_provider(ProviderConfig(provider="deepseek", model="m", allow_external=True))
    assert e.value.kind == "config"


def test_deepseek_uses_openai_adapter_with_its_base_url(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    p = build_provider(ProviderConfig(provider="deepseek", model="m", allow_external=True))
    assert isinstance(p, OpenAICompatibleProvider) and str(p.client.base_url).startswith("https://api.deepseek.com")
    assert p.client.max_retries == 0 and p.external


def test_anthropic_client_ignores_unrelated_base_url_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://somewhere-else.invalid")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-test")
    p = build_provider(ProviderConfig(provider="anthropic", model="m", allow_external=True))
    assert str(p.client.base_url).startswith("https://api.anthropic.com")


# --------------------------------------------------------------------------- OpenAI-compatible over HTTP
@pytest.mark.parametrize("stack", sorted(LOCAL_STACKS))
def test_local_adapter_against_mock_server(stack):
    with MockOpenAIServer() as srv:
        cfg = local_cfg(srv.url, local_stack=stack)
        c = build_provider(cfg).complete(MSGS, max_tokens=100, temperature=0.0)
    assert c.text.startswith("جواب") and c.model == "mock-model" and (c.prompt_tokens, c.completion_tokens) == (42, 7)
    body = srv.requests[0]["body"]
    assert srv.requests[0]["path"] == "/v1/chat/completions" and body["model"] == "my-local-model"
    assert body["max_tokens"] == 100 and body["temperature"] == 0.0 and body["messages"][0]["role"] == "system"
    assert c.latency_ms >= 0 and c.provider == "local"


def test_openai_uses_max_completion_tokens_and_bearer_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-test")
    with MockOpenAIServer() as srv:
        cfg = ProviderConfig(provider="openai", model="cfg-model", base_url=srv.url, allow_external=True)
        build_provider(cfg).complete(MSGS, max_tokens=50, temperature=None)
    body = srv.requests[0]["body"]
    assert body["max_completion_tokens"] == 50 and "max_tokens" not in body and "temperature" not in body
    assert srv.requests[0]["auth"] == "Bearer sk-secret-test"


def test_retries_with_backoff_then_success():
    sleeps = []
    with MockOpenAIServer([("status", 503), ("status", 429), ("ok", "ٹھیک")]) as srv:
        p = OpenAICompatibleProvider(local_cfg(srv.url, max_retries=3), sleep=sleeps.append)
        assert p.complete(MSGS, max_tokens=10, temperature=0).text == "ٹھیک"
    assert len(srv.requests) == 3 and len(sleeps) == 2


def test_non_retryable_and_exhausted_errors_are_clear():
    with MockOpenAIServer([("status", 401)]) as srv:
        with pytest.raises(ProviderError) as e:
            OpenAICompatibleProvider(local_cfg(srv.url), sleep=NO_SLEEP).complete(MSGS, max_tokens=10, temperature=0)
    assert e.value.kind == "auth" and len(srv.requests) == 1
    with MockOpenAIServer([("status", 500)]) as srv:
        with pytest.raises(ProviderError) as e:
            OpenAICompatibleProvider(local_cfg(srv.url, max_retries=2), sleep=NO_SLEEP).complete(
                MSGS, max_tokens=10, temperature=0)
    assert e.value.kind == "server" and len(srv.requests) == 3
    with MockOpenAIServer([("empty", None)]) as srv:
        with pytest.raises(ProviderError) as e:
            OpenAICompatibleProvider(local_cfg(srv.url, max_retries=0), sleep=NO_SLEEP).complete(
                MSGS, max_tokens=10, temperature=0)
    assert e.value.kind == "empty"


def test_timeout_and_connection_refused():
    with MockOpenAIServer([("sleep", 2)]) as srv:
        with pytest.raises(ProviderError) as e:
            OpenAICompatibleProvider(local_cfg(srv.url, timeout_s=0.3, max_retries=0), sleep=NO_SLEEP).complete(
                MSGS, max_tokens=10, temperature=0)
    assert e.value.kind == "timeout" and e.value.retryable
    with pytest.raises(ProviderError) as e:
        OpenAICompatibleProvider(local_cfg("http://127.0.0.1:9/v1", max_retries=1), sleep=NO_SLEEP).complete(
            MSGS, max_tokens=10, temperature=0)
    assert e.value.kind == "connection" and "base URL" in str(e.value)


def test_streaming_from_mock_server():
    with MockOpenAIServer([("sse", "عضلاتی قبض شدید ہوتی ہے")]) as srv:
        out = "".join(OpenAICompatibleProvider(local_cfg(srv.url)).stream(MSGS, max_tokens=10, temperature=0))
    assert out.strip() == "عضلاتی قبض شدید ہوتی ہے" and srv.requests[0]["body"]["stream"] is True


def test_error_messages_never_contain_the_key():
    class E(Exception):
        status_code = 400
    err = classify_error("openai", E("bad key sk-live-123 rejected"), secret="sk-live-123")
    assert "sk-live-123" not in str(err) and err.kind == "bad_request"


# --------------------------------------------------------------------------- Claude (anthropic SDK, mocked transport)
def _anthropic(handler, monkeypatch):
    import anthropic
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-test")
    cfg = ProviderConfig(provider="anthropic", model="claude-from-config", allow_external=True, backoff_s=0)
    client = anthropic.Anthropic(api_key="a-test", base_url="https://api.anthropic.test", max_retries=0,
                                 http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return AnthropicProvider(cfg, client=client, sleep=NO_SLEEP)


def test_anthropic_adapter_maps_system_and_usage(monkeypatch):
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-from-config",
            "content": [{"type": "text", "text": "جواب (جلد دوم، صفحہ 127)"}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 11, "output_tokens": 4}})
    c = _anthropic(handler, monkeypatch).complete(MSGS + [{"role": "user", "content": "اور؟"}], max_tokens=64,
                                                   temperature=0.0)
    body = seen[0]
    assert body["system"] == "آپ حکیم ہیں" and body["model"] == "claude-from-config" and body["max_tokens"] == 64
    assert [m["role"] for m in body["messages"]] == ["user"]          # consecutive user turns merged
    assert "temperature" not in body                                   # not part of the current Messages API
    assert (c.text, c.prompt_tokens, c.completion_tokens) == ("جواب (جلد دوم، صفحہ 127)", 11, 4)


def test_anthropic_retries_overloaded(monkeypatch):
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
        return httpx.Response(200, json={"id": "m", "type": "message", "role": "assistant", "model": "x",
                                         "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
                                         "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})
    assert _anthropic(handler, monkeypatch).complete(MSGS, max_tokens=8, temperature=0).text == "ok"
    assert len(calls) == 2


# --------------------------------------------------------------------------- Gemini (google-genai SDK, mocked transport)
def test_gemini_adapter_maps_roles_and_config(monkeypatch):
    from google import genai
    from google.genai import types
    seen = []

    def handler(req):
        seen.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": "جواب (جلد اول، صفحہ 5)"}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 21, "candidatesTokenCount": 6}, "modelVersion": "gem-cfg"})
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    cfg = ProviderConfig(provider="gemini", model="gem-cfg", allow_external=True)
    client = genai.Client(api_key="g-test", http_options=types.HttpOptions(
        httpx_client=httpx.Client(transport=httpx.MockTransport(handler))))
    msgs = MSGS + [{"role": "assistant", "content": "جی"}, {"role": "user", "content": "مزید؟"}]
    c = GeminiProvider(cfg, client=client).complete(msgs, max_tokens=99, temperature=0.0)
    url, body = seen[0]
    assert "models/gem-cfg:generateContent" in url
    assert [x["role"] for x in body["contents"]] == ["user", "model", "user"]
    assert body["systemInstruction"]["parts"][0]["text"] == "آپ حکیم ہیں"
    assert body["generationConfig"]["maxOutputTokens"] == 99 and body["generationConfig"]["temperature"] == 0.0
    assert (c.text, c.model, c.prompt_tokens, c.completion_tokens) == ("جواب (جلد اول، صفحہ 5)", "gem-cfg", 21, 6)


def test_gemini_client_error_classified(monkeypatch):
    from google.genai import errors
    err = classify_error("gemini", errors.ClientError(429, {"error": {"message": "quota"}}))
    assert err.kind == "rate_limit" and err.retryable
    err = classify_error("gemini", errors.ClientError(403, {"error": {"message": "denied"}}))
    assert err.kind == "auth"
    bad_key = errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                                                 "status": "INVALID_ARGUMENT"}})
    err = classify_error("gemini", bad_key)
    assert err.kind == "auth" and not err.retryable and "API key not valid" in str(err)


@pytest.mark.parametrize("raw", ['"g-abc"', "'g-abc'", "  g-abc \n", '" g-abc "'])
def test_api_key_whitespace_and_quotes_are_stripped(monkeypatch, raw):
    monkeypatch.setenv("GEMINI_API_KEY", raw)
    assert ProviderConfig(provider="gemini", model="m").api_key() == "g-abc"


def test_reasoning_blocks_are_removed_before_the_patient_sees_them():
    from nazria_kb.providers import strip_reasoning
    assert strip_reasoning("<think>\nسوچ: شنگرف؟\n</think>\n\nجواب (جلد دوم، صفحہ 127)") == "جواب (جلد دوم، صفحہ 127)"
    assert strip_reasoning("<think>cut off by max_tokens") == ""
    think = "<think>reasoning about the passages</think>جواب (جلد دوم، صفحہ 127)"
    with MockOpenAIServer([("ok", think)]) as srv:
        c = build_provider(local_cfg(srv.url, local_stack="ollama")).complete(MSGS, max_tokens=10, temperature=0)
    assert c.text == "جواب (جلد دوم، صفحہ 127)"
    with MockOpenAIServer([("ok", "<think>only thinking, never finished")]) as srv:
        with pytest.raises(ProviderError) as e:
            OpenAICompatibleProvider(local_cfg(srv.url, max_retries=0), sleep=NO_SLEEP).complete(
                MSGS, max_tokens=10, temperature=0)
    assert e.value.kind == "empty" and "NAZRIA_LLM_MAX_TOKENS" in str(e.value)
