"""The one LLM client. Provider is set only by LLM_BASE_URL, LLM_API_KEY, LLM_MODEL."""
from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from app.config import get_llm_settings

TIMEOUT_S = 8.0


class LLMError(Exception):
    pass


class LLMRateLimited(LLMError):
    pass


_client: OpenAI | None = None


def build_client() -> OpenAI:
    s = get_llm_settings()
    # No SDK retries: a retry would spend free-tier quota and blow the 8 s budget.
    return OpenAI(base_url=s.base_url, api_key=s.api_key, timeout=TIMEOUT_S, max_retries=0)


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = build_client()
    return _client


def complete(messages: list[dict], tools: list[dict] | None = None):
    try:
        model = get_llm_settings().model
        client = _get_client()
    except RuntimeError as e:  # missing LLM_* config: report as an LLM error, not a crash
        raise LLMError(str(e)) from e
    kwargs = {"model": model, "messages": messages, "temperature": 0}
    if tools:
        kwargs["tools"] = tools
    try:
        resp = client.chat.completions.create(**kwargs)
    except RateLimitError as e:
        raise LLMRateLimited("The LLM provider is rate limited (HTTP 429). Retry in a few seconds.") from e
    except APITimeoutError as e:
        raise LLMError(f"LLM timed out after {TIMEOUT_S:.0f} s.") from e
    except APIError as e:
        raise LLMError(f"LLM request failed ({type(e).__name__}).") from e
    return resp.choices[0].message


def complete_text(system: str, user: str) -> str:
    msg = complete([{"role": "system", "content": system}, {"role": "user", "content": user}])
    return msg.content or ""
