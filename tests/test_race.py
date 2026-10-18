"""Sandbox races: concurrent first requests must seed a session exactly once, and results must not repeat."""
import threading

from fastapi.testclient import TestClient

from app import db, queries, sandbox, seed
from app.main import app


def counts(sid):
    g = db.connect(graph_name=sandbox.graph_name(sid))
    labels = {r["label"]: r["c"] for r in db.read(g, queries.COUNT_NODES_BY_LABEL)}
    edges = {r["type"]: r["c"] for r in db.read(g, queries.COUNT_EDGES_BY_TYPE)}
    open_owns = [r["open"] for r in db.read(g, queries.INVARIANT_OPEN_OWNS)]
    return labels, edges, open_owns


def test_five_concurrent_first_requests_seed_the_sandbox_once():
    sid = sandbox.new_sid()
    statuses = []
    errors = []

    def first_request():
        try:
            client = TestClient(app, cookies={"hv_sid": sid})
            statuses.append(client.get("/api/overview").status_code)
        except Exception as e:  # collected and asserted below
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=first_request) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert statuses == [200] * 5
    labels, edges, open_owns = counts(sid)
    assert labels["Person"] == 9
    assert labels["Ticket"] == 4
    assert edges["OWNS"] == 7
    assert open_owns == [1, 1, 1, 1, 1, 1]


def test_demo_handover_summary_is_exact_and_has_no_repeats():
    client = TestClient(app)  # a new visitor, so a new sandbox
    result = client.post("/events", json={"demo": True}).json()
    assert result["status"] == "applied"
    closed = {c["service"] for c in result["closed"]}
    opened = {o["service"] for o in result["opened"]}
    moved = [t["ticket_id"] for t in result["tickets_moved"]]
    assert len(result["closed"]) == len(closed) == 2
    assert len(result["opened"]) == len(opened) == 2
    assert len(moved) == len(set(moved))
    summary = (f"closed {len(closed)} · opened {len(opened)} · "
               f"moved {', '.join(sorted(set(moved)))} → Ada Okafor")
    assert summary == "closed 2 · opened 2 · moved t-101, t-102 → Ada Okafor"


def test_verify_repairs_a_sandbox_that_was_seeded_twice():
    sid = sandbox.new_sid()
    sandbox.ensure(sid)
    graph = db.connect(graph_name=sandbox.graph_name(sid))
    seed.run_file(graph, seed.ROOT / "db" / "seed.cypher")  # simulate a duplicate seed
    assert sandbox.check_invariants(graph) != []
    assert sandbox.verify(sid, graph) is False
    assert sandbox.check_invariants(graph) == []
    labels, _, _ = counts(sid)
    assert labels["Ticket"] == 4 and labels["Person"] == 9


def test_reset_rebuilds_only_the_callers_sandbox_cleanly():
    a = TestClient(app)
    b = TestClient(app)
    a.post("/events", json={"demo": True})
    b.post("/events", json={"demo": True})
    a.post("/reset")
    labels, edges, open_owns = counts(a.cookies.get("hv_sid"))
    assert labels["Ticket"] == 4 and labels["Person"] == 9
    assert edges["OWNS"] == 7 and open_owns == [1, 1, 1, 1, 1, 1]


def test_ticket_reassignment_query_returns_each_ticket_once():
    assert "RETURN DISTINCT t.id AS ticket_id" in queries.T6_REASSIGN_TICKETS


def test_purge_all_removes_every_sandbox_and_the_registry():
    sids = [sandbox.new_sid() for _ in range(2)]
    for sid in sids:
        sandbox.ensure(sid)
    removed = sandbox.purge_all()
    assert removed >= 3  # two sandboxes plus the control graph
    client = db.client()
    names = client.list_graphs()
    assert not any(n.startswith("tidewell-") for n in names)
    assert sandbox.CONTROL not in names
