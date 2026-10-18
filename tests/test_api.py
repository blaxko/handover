"""HTTP contract checks: auth, error shapes, CORS, health, graph view, baseline shape."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import baseline, db, llm, main
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


def test_event_result_carries_ids_and_graph_all_marks_closed(client):
    result = client.post("/events", json={"demo": True}).json()
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
    assert "Who owns it" in page.text  # landing page
    for path in ("/static/app.js", "/static/style.css", "/static/theme.css", "/static/site.js",
                 "/static/logo.svg", "/static/logo-mark.svg"):
        assert client.get(path).status_code == 200, path


def test_dashboard_moved_to_app(client):
    resp = client.get("/app")
    assert resp.status_code == 200
    assert 'id="ask-form"' in resp.text and 'id="graph"' in resp.text
    assert "Hand it over" in resp.text and "← Home" in resp.text


def test_marketing_pages_return_200(client):
    assert client.get("/how-it-works").status_code == 200
    accuracy = client.get("/accuracy")
    assert accuracy.status_code == 200
    assert "Graph: 11/11 questions · Keyword search: 3/11 · Handover event applied correctly" in accuracy.text
    assert "Who owns payments-api?" in accuracy.text  # a row from docs/baseline_results.md
    assert "hackathon" not in accuracy.text.lower()


def test_proof_redirects_to_accuracy(client):
    resp = client.get("/proof", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/accuracy"


def test_landing_has_no_hackathon_wording(client):
    text = client.get("/").text.lower()
    for word in ("hackathon", "graph hacks", "golden", "built for"):
        assert word not in text, word

def test_graph_page_shows_templates_from_queries(client):
    resp = client.get("/graph", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert "T5 · apply_handover" in resp.text
    # The page is built from queries.py. The arrows are HTML-escaped on the way in.
    assert "MATCH (p:Person)-[o:OWNS]-&gt;(s:Service {id:$service})" in resp.text
    assert "{{T1}}" not in resp.text


def test_graph_json_api_unchanged_without_html_accept(client):
    # No focus and no HTML accept header is still a 422, as before.
    assert client.get("/graph").status_code == 422
    assert client.get("/graph", params={"focus": "p-tunde", "depth": 1}).json()["nodes"]


def test_logo_mark_has_no_background_and_uses_current_colour():
    mark = (ROOT / "web" / "logo-mark.svg").read_text(encoding="utf-8")
    assert "<rect" not in mark
    assert 'stroke="currentColor"' in mark


def test_config_never_exposes_a_token(client, monkeypatch):
    monkeypatch.setenv("DEMO_TOKEN", "secret-for-test")
    data = client.get("/config").json()
    assert "demo_token" not in data
    assert "secret-for-test" not in client.get("/config").text

def test_config_reports_sandbox_mode(client):
    assert client.get("/config").json() == {"sandbox": True}

def test_event_endpoint_needs_no_token(client):
    # Each visitor has a private sandbox, so no token is required any more.
    resp = client.post("/events", json={"demo": True})
    assert resp.status_code == 200
    assert resp.json()["status"] == "applied"

def test_event_endpoint_ignores_a_token_header(client):
    resp = client.post("/events", json={"demo": True}, headers={"X-Demo-Token": "anything"})
    assert resp.status_code == 200

def test_reset_needs_no_token(client):
    resp = client.post("/reset")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

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


def test_graph_marks_closed_edges(client):
    client.post("/events", json={"demo": True})
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
    monkeypatch.setattr(db, "_client", None)  # force a new client that uses the bad settings below
    monkeypatch.setenv("FALKORDB_HOST", "127.0.0.1")
    monkeypatch.setenv("FALKORDB_PORT", "1")  # nothing listens here
    with TestClient(app) as c:
        resp = c.post("/ask", json={"question": "Who owns ledger?"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "DB_UNREACHABLE"

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


def test_demo_event_via_api(client):
    resp = client.post("/events", json={"demo": True})
    assert resp.status_code == 200
    assert resp.json()["status"] == "applied"

