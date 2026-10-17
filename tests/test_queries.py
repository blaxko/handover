"""Data-level checks of the Cypher templates against the seeded graph.

Needs the seed loaded first: python db/load.py --reset
"""
import pytest

from app import queries
from app.db import connect


@pytest.fixture(scope="module")
def graph():
    return connect()


def test_golden_1_who_owns_payments_before_event(graph):
    rows = queries.who_owns(graph, "s-payments", "2026-10-16")
    assert [r["person"] for r in rows] == ["Tunde Bakare"]
    assert rows[0]["source"] == "m01"


def test_golden_2_who_owns_ledger_before_event(graph):
    rows = queries.who_owns(graph, "s-ledger", "2026-10-16")
    assert [r["person"] for r in rows] == ["Tunde Bakare"]
    assert rows[0]["source"] == "m02"


def test_golden_3_who_owned_ledger_in_2025_06(graph):
    rows = queries.who_owns(graph, "s-ledger", "2025-06-01")
    assert [r["person"] for r in rows] == ["Segun Bello"]
    assert rows[0]["source"] == "m00"


def test_golden_4_blast_radius_for_tunde(graph):
    rows = queries.blast_radius(graph, "p-tunde")
    owned = {r["owned"] for r in rows}
    assert owned == {"payments-api", "ledger"}

    dependents = set()
    tickets = set()
    for r in rows:
        dependents.update(r["dependents"])
        tickets.update(r["open_tickets"])
    assert {"mobile-app", "notifications"} <= dependents
    assert {"Refund webhook returns 500", "Reconciliation drift in ledger"} <= tickets


def test_golden_5_who_knows_payments_besides_owner(graph):
    # T2 does not exclude the current owner; the caller drops them.
    rows = queries.who_knows(graph, "s-payments")
    others = [r["person"] for r in rows if r["person"] != "Tunde Bakare"]
    assert others[0] == "Ada Okafor"


def test_one_open_owns_per_service(graph):
    rows = queries.open_owns_counts(graph)
    assert len(rows) == 6
    for r in rows:
        assert r["open"] == 1, f"{r['service']} has {r['open']} open OWNS edges"
