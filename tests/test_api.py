"""HTTP contract checks: auth, error shapes, CORS, health, graph view, baseline shape."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import baseline, llm, main
from app.main import app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_ask_golden_1_returns_a_nonempty_path(client, monkeypatch):
    # No LLM: keyword router and template answer. The path must still come back.
    def down(*a, **k):
        raise llm.LLMError("off")

    monkeypatch.setattr(llm, "complete", down)
    monkeypatch.setattr(llm, "complete_text", down)
    data = client.post("/ask", json={"question": "Who owns payments-api?"}).json()
    assert data["status"] == "ok"
    assert data["path"]["nodes"] and data["path"]["edges"]
    edge = next(e for e in data["path"]["edges"] if e["type"] == "OWNS")
    node_ids = {n["id"] for n in data["path"]["nodes"]}
    assert {edge["from"], edge["to"]} <= node_ids  # every edge end is a returned node


def test_app_js_uses_the_ask_path():
    # The page must read the path from the /ask response and draw it, not a separate copy.
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "graph.data.path" in js
    assert "state.hl = { mode: 'answer'" in js
    assert "setPathText()" in js and "highlightedEdges()" in js


def test_event_result_carries_ids_and_graph_all_marks_closed(client, reseeded_graph):
    from app import events

    result = events.apply_demo_event(reseeded_graph)
    assert result["ids"]["from"] == "p-tunde"
    assert result["ids"]["to"] == "p-ada"
    assert set(result["ids"]["services"]) == {"s-payments", "s-ledger"}
    assert set(result["ids"]["tickets"]) == {"t-101", "t-102"}
    whole = client.get("/graph/all").json()
    assert any(e["closed"] for e in whole["edges"])
    assert any(not e["closed"] for e in whole["edges"])


def test_index_and_static_files_load(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "<title>" in page.text
    for path in ("/static/app.js", "/static/style.css"):
        assert client.get(path).status_code == 200, path


def test_config_hides_token_from_non_local_clients(client, monkeypatch):
    # TestClient connects as "testclient", which is not this machine.
    monkeypatch.setenv("DEMO_TOKEN", "secret-for-test")
    data = client.get("/config").json()
    assert data == {"local": False, "demo_token": None}


def test_config_gives_token_to_local_clients(monkeypatch):
    monkeypatch.setenv("DEMO_TOKEN", "secret-for-test")
    with TestClient(app, client=("127.0.0.1", 50000)) as local:
        data = local.get("/config").json()
    assert data == {"local": True, "demo_token": "secret-for-test"}


def test_event_endpoint_needs_token(client):
    resp = client.post("/events", json={"demo": True})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "HTTP_ERROR"


def test_event_endpoint_rejects_wrong_token(client):
    resp = client.post("/events", json={"demo": True}, headers={"X-Demo-Token": "nope"})
    assert resp.status_code == 401


def test_reset_needs_token(client):
    assert client.post("/reset").status_code == 401


def test_validation_errors_use_the_error_shape(client):
    resp = client.post("/ask", json={"question": ""})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_health_reports_config_without_calling_the_llm(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("health must not call the LLM")

    monkeypatch.setattr(llm, "complete", boom)
    monkeypatch.setattr(llm, "complete_text", boom)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["db"] == "ok"
    assert resp.json()["llm_configured"] is True


def test_graph_unknown_focus_is_404(client):
    assert client.get("/graph", params={"focus": "nope-123"}).status_code == 404


def test_graph_marks_closed_edges(client, reseeded_graph, demo_token):
    from app import events

    events.apply_demo_event(reseeded_graph)
    resp = client.get("/graph", params={"focus": "p-tunde", "depth": 1})
    assert resp.status_code == 200
    owns = [e for e in resp.json()["edges"] if e["type"] == "OWNS" and e["from"] == "p-tunde"]
    closed = {e["to"]: e["closed"] for e in owns}
    assert closed["s-payments"] is True
    assert closed["s-ledger"] is True


def test_graph_depth_is_bounded(client):
    assert client.get("/graph", params={"focus": "p-tunde", "depth": 9}).status_code == 422


def test_cors_allows_only_the_app_origin(client):
    ok = client.options("/ask", headers={"Origin": "http://localhost:8000",
                                         "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8000"
    other = client.options("/ask", headers={"Origin": "https://evil.example",
                                            "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in other.headers


def test_falkordb_unreachable_gives_503(monkeypatch):
    monkeypatch.setattr(main, "_graph", None)
    monkeypatch.setenv("FALKORDB_HOST", "127.0.0.1")
    monkeypatch.setenv("FALKORDB_PORT", "1")  # nothing listens here
    with TestClient(app) as c:
        resp = c.post("/ask", json={"question": "Who owns ledger?"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "DB_UNREACHABLE"
    monkeypatch.setattr(main, "_graph", None)  # next test reconnects with the real settings


def test_baseline_shape_and_rank(client, monkeypatch):
    # The LLM cites m99, which is not a snippet here, so the guard must remove it.
    monkeypatch.setattr(llm, "complete_text", lambda system, user: "Tunde Bakare [m99].")
    resp = client.post("/baseline", json={"question": "Who owns payments-api?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "Tunde Bakare."
    assert data["snippets"]
    assert [s["rank"] for s in data["snippets"]] == list(range(1, len(data["snippets"]) + 1))
    assert all("score" in s for s in data["snippets"])


def test_baseline_search_terms_drop_question_words():
    assert baseline.search_terms("Who owns payments-api?") == "owns | payments | api"


def test_baseline_retrieves_m01_for_payments_api(graph_for_baseline):
    # Keyword retrieval, re-ranked: messages with the whole term "payments-api" rank first.
    found = baseline.snippets(graph_for_baseline, "Who owns payments-api?")
    ids = [s["id"] for s in found]
    assert "m01" in ids
    assert all("payments-api" in s["text"].lower() for s in found)


@pytest.fixture
def graph_for_baseline():
    from app.db import connect
    return connect()


def test_baseline_llm_error_is_reported_not_raised(client, monkeypatch):
    def down(system, user):
        raise llm.LLMError("LLM timed out after 8 s.")

    monkeypatch.setattr(llm, "complete_text", down)
    data = client.post("/baseline", json={"question": "Who owns ledger?"}).json()
    assert data["answer"] is None
    assert "timed out" in data["error"]


def test_demo_event_via_api_with_token(client, reseeded_graph, demo_token):
    resp = client.post("/events", json={"demo": True}, headers={"X-Demo-Token": demo_token})
    assert resp.status_code == 200
    assert resp.json()["status"] == "applied"
