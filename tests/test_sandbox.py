"""Per-visitor sandboxes, the JSON the dashboard reads, and the front-end wiring that uses them."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, sandbox
from app.main import app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def visitor():
    with TestClient(app) as c:
        yield c


def owner_of_payments(client):
    return client.get("/api/overview").json()["owners"]["s-payments"]["person"]


def test_visitors_do_not_see_each_others_handovers():
    a = TestClient(app)
    b = TestClient(app)
    assert owner_of_payments(a) == "Tunde Bakare"
    a.post("/events", json={"demo": True})
    assert owner_of_payments(a) == "Ada Okafor"
    assert owner_of_payments(b) == "Tunde Bakare"  # B's own graph is untouched


def test_reset_only_re_seeds_the_callers_graph():
    a = TestClient(app)
    b = TestClient(app)
    a.post("/events", json={"demo": True})
    b.post("/events", json={"demo": True})
    a.post("/reset")
    assert owner_of_payments(a) == "Tunde Bakare"
    assert owner_of_payments(b) == "Ada Okafor"  # B keeps its own handover


def test_session_cookie_is_httponly_and_samesite_lax():
    with TestClient(app) as c:
        resp = c.get("/api/overview")
        cookie = resp.headers["set-cookie"]
        assert "hv_sid=" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Secure" not in cookie  # plain http locally; Secure is added behind https


def test_overview_is_json_with_what_the_dashboard_needs(visitor):
    resp = visitor.get("/api/overview")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert len(data["services"]) == 6
    assert data["open_tickets"] == 4
    assert data["handovers"] == 0
    assert {"id", "name", "initials"} <= set(data["people"][0])
    assert data["owners"]["s-payments"]["since"] == "2025-11-03"
    assert data["owners"]["s-payments"]["source"] == "m01"


def test_overview_counts_the_handover_after_an_event(visitor):
    visitor.post("/events", json={"demo": True})
    data = visitor.get("/api/overview").json()
    assert data["handovers"] == 1
    assert data["owners"]["s-payments"]["person"] == "Ada Okafor"
    assert data["owners"]["s-payments"]["source"].startswith("evt-")


def test_graph_all_is_json_even_with_a_browser_accept_header(visitor):
    resp = visitor.get("/graph/all", headers={"Accept": "text/html,*/*"})
    assert resp.headers["content-type"].startswith("application/json")


def test_reap_removes_idle_sandboxes_and_caps_the_rest(monkeypatch):
    monkeypatch.setattr(sandbox, "CAP", 2)
    sids = [sandbox.new_sid() for _ in range(3)]
    for sid in sids:
        sandbox.ensure(sid)
    # The first one has been idle for longer than the limit.
    db.write(db.connect(graph_name=sandbox.CONTROL),
             "MATCH (s:Sandbox {sid:$sid}) SET s.last_seen = 1", {"sid": sids[0]})
    sandbox.reap()
    live = {r["sid"] for r in db.read(db.connect(graph_name=sandbox.CONTROL),
                                      "MATCH (s:Sandbox) RETURN s.sid AS sid")}
    assert sids[0] not in live  # idle: removed
    assert sids[2] in live      # most recent: kept
    assert len([s for s in sids if s in live]) <= 2


def test_dashboard_reads_json_and_fills_the_kpi_people_and_owner_elements():
    js = (ROOT / "web" / "dashboard.js").read_text(encoding="utf-8")
    html = (ROOT / "web" / "app.html").read_text(encoding="utf-8")
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    # The dashboard fetches the JSON overview and refuses non-JSON replies.
    assert "'/api/overview'" in js
    assert "application/json" in js
    # Every element it fills exists on the page.
    for element_id in ("kpi-services", "kpi-tickets", "kpi-handovers", "hero-answer", "people-pills",
                       "tree-services", "tree-people", "kpi-error", "kpi-retry"):
        assert f'id="{element_id}"' in html, element_id
        assert element_id in js, element_id
    # The events it listens for are dispatched by app.js.
    for event_name in ("handover:answer", "handover:event", "handover:reset"):
        assert event_name in js, event_name
        assert event_name in app_js, event_name


def test_app_html_has_the_sandbox_note_and_no_token_prompt_in_use():
    html = (ROOT / "web" / "app.html").read_text(encoding="utf-8")
    assert "This is your private sandbox. Changes only affect you." in html
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "demo_token" not in app_js


def test_readme_names_the_isolation_model():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Each visitor gets an isolated graph (FalkorDB multigraph)" in readme


def test_about_statement_keeps_the_sentence_and_its_three_highlights():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    text = re.sub(r"<[^>]+>", "", html[html.index('<p class="statement">'):])
    text = text.split("</p>")[0]
    assert "Handover keeps who owns what current, shows the path behind every answer, and moves the work when people move on." in " ".join(text.split())
    assert html.count("<mark>") == 3
    assert "cursor-tunde" in html and "cursor-ada" in html


def test_loading_states_show_setup_text_shimmer_and_handing_over():
    js = (ROOT / "web" / "dashboard.js").read_text(encoding="utf-8")
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "web" / "app.html").read_text(encoding="utf-8")
    css = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
    # The friendly setup line, in the KPI area and the dark card.
    assert "Setting up your private workspace…" in js and "Setting up your private workspace…" in html
    assert 'id="workspace-status"' in html and 'id="kpis"' in html
    assert "is-loading" in js and ".kpis.is-loading" in css and "#hero-card.is-loading" in css
    # The error only appears after the last attempt fails.
    assert "if (firstLoad) setLoading(false);" in js and "setError(true)" in js
    # "Hand it over" shows its own progress state, not "Applying…".
    assert "Handing over…" in app_js and "Applying…" not in app_js and "notice shimmer" in app_js
    assert ".notice.shimmer" in css and "prefers-reduced-motion" in css
