import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    username: str | None
    password: str | None
    graph_name: str
    ssl: bool


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    api_key: str
    model: str


def get_llm_settings() -> LLMSettings:
    missing = [k for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing env keys in .env: {', '.join(missing)}")
    return LLMSettings(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        model=os.environ["LLM_MODEL"],
    )


def get_settings() -> Settings:
    host = os.environ.get("FALKORDB_HOST", "")
    missing = [k for k in ("FALKORDB_HOST", "FALKORDB_PORT") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing env keys in .env: {', '.join(missing)}")
    return Settings(
        host=host,
        port=int(os.environ["FALKORDB_PORT"]),
        username=os.environ.get("FALKORDB_USERNAME") or None,
        password=os.environ.get("FALKORDB_PASSWORD") or None,
        graph_name=os.environ.get("GRAPH_NAME") or "tidewell",
        # Plain TCP works on this instance (TLS handshake timed out).
        # Set FALKORDB_SSL=true only if the provider requires TLS.
        ssl=os.environ.get("FALKORDB_SSL", "").lower() == "true",
    )
