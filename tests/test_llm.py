import httpx
import pytest
from openai import APITimeoutError, RateLimitError

from app import llm


def _settings_env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")


class _Completions:
    def __init__(self, exc):
        self.exc = exc

    def create(self, **kwargs):
        raise self.exc


class _FakeClient:
    def __init__(self, exc):
        self.chat = type("Chat", (), {"completions": _Completions(exc)})()


def _request():
    return httpx.Request("POST", "https://example.invalid/v1/chat/completions")


def test_client_has_8_second_timeout_and_no_retries(monkeypatch):
    _settings_env(monkeypatch)
    client = llm.build_client()
    assert client.timeout == 8.0
    assert client.max_retries == 0


def test_missing_config_raises_naming_keys_only(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    with pytest.raises(RuntimeError) as exc:
        llm.build_client()
    assert "LLM_API_KEY" in str(exc.value)
    assert "https://example.invalid" not in str(exc.value)


def test_http_429_becomes_rate_limited(monkeypatch):
    response = httpx.Response(429, request=_request())
    monkeypatch.setattr(llm, "_get_client", lambda: _FakeClient(RateLimitError("limit", response=response, body=None)))
    with pytest.raises(llm.LLMRateLimited) as exc:
        llm.complete_text("system", "user")
    assert "retry" in str(exc.value).lower()


def test_timeout_becomes_llm_error(monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda: _FakeClient(APITimeoutError(request=_request())))
    with pytest.raises(llm.LLMError) as exc:
        llm.complete_text("system", "user")
    assert "timed out" in str(exc.value)
