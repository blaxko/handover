"""Deployment and setup files: what the README and Railway depend on."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_railway_start_command_binds_to_port_env():
    cfg = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
    assert cfg["deploy"]["startCommand"] == "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
    assert cfg["deploy"]["healthcheckPath"] == "/health"


def test_env_example_has_every_key_and_no_secrets():
    lines = [l for l in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
             if l and not l.startswith("#")]
    values = dict(l.split("=", 1) for l in lines)
    required = {"FALKORDB_HOST", "FALKORDB_PORT", "FALKORDB_USERNAME", "FALKORDB_PASSWORD",
                "FALKORDB_SSL", "GRAPH_NAME", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
                "DEMO_TOKEN", "APP_ORIGIN"}
    assert required <= set(values)
    # Only non-secret defaults may have values.
    assert {k for k, v in values.items() if v} == {"FALKORDB_SSL", "GRAPH_NAME"}


def test_readme_setup_and_baseline_note_present():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Setup (local)" in readme
    assert "Baseline = FalkorDB full-text index + simple keyword re-rank, top 3 messages, no hand-picked answers." in readme
    setup = readme.split("## Setup (local)", 1)[1].split("\n## ", 1)[0]
    assert "requirements.txt" in setup and "db/load.py --reset" in setup and "/health" in setup
