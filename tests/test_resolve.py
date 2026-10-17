"""Alias resolution against the seeded graph (T0 + suggestions).

Needs the seed loaded first: python db/load.py --reset
"""
import pytest

from app import resolve
from app.db import connect


@pytest.fixture(scope="module")
def graph():
    return connect()


@pytest.mark.parametrize("text", ["TB", "@tunde", "T. Bakare"])
def test_person_aliases_resolve_to_tunde(graph, text):
    result = resolve.resolve(graph, text)
    assert result["status"] == "ok"
    assert result["id"] == "p-tunde"
    assert result["kind"] == "Person"


def test_ada_is_ambiguous_with_two_candidates(graph):
    result = resolve.resolve(graph, "Ada")
    assert result["status"] == "clarify"
    assert {c["id"] for c in result["candidates"]} == {"p-ada", "p-adan"}


def test_exact_id_resolves_to_one_person(graph):
    # Clarify chips re-ask with the chosen id, so "p-adan" must pick Ada Nwankwo alone.
    result = resolve.resolve(graph, "p-adan")
    assert result["status"] == "ok"
    assert result["id"] == "p-adan"


def test_service_alias_resolves(graph):
    result = resolve.resolve(graph, "payments")
    assert result["status"] == "ok"
    assert result["id"] == "s-payments"
    assert result["kind"] == "Service"


def test_unknown_name_returns_unknown_with_suggestions(graph):
    result = resolve.resolve(graph, "billing")
    assert result["status"] == "unknown"
    assert isinstance(result["suggestions"], list)
    assert len(result["suggestions"]) == 3
    for s in result["suggestions"]:
        assert {"id", "name", "kind"} <= set(s)
