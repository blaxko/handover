"""Change events. The LLM is always mocked; graph tests use a re-seeded graph."""
import json
from datetime import date

import pytest
from pydantic import ValidationError

from app import db, events, llm, queries
from app.events import ChangeEvent, EventError

DEMO_JSON = {
    "type": "departure",
    "from": "Tunde Bakare",
    "to": "Ada Okafor",
    "services": ["payments-api", "ledger"],
    "effective": "2026-10-17",
}
DEMO_TEXT = (
    "Tunde Bakare's last day was Friday. Ada Okafor takes over payments-api and ledger, "
    "effective 2026-10-17."
)


def fake_llm(*replies):
    """Mock complete_text: returns the replies in order and records each call."""
    queue = list(replies)
    calls = []

    def complete(system, user):
        calls.append(user)
        return queue.pop(0)

    complete.calls = calls
    return complete


def owner_of(graph, service, at):
    return [r["person"] for r in queries.who_owns(graph, service, at)]


def all_owns_count(graph):
    return db.read(graph, "MATCH ()-[o:OWNS]->() RETURN count(o) AS c")[0]["c"]


def ticket_owners(graph):
    rows = db.read(
        graph,
        "MATCH (t:Ticket)-[a:ASSIGNED_TO]->(p:Person) WHERE a.valid_to IS NULL "
        "RETURN t.id AS ticket, p.id AS person",
    )
    return {r["ticket"]: r["person"] for r in rows}


# ---- pure: ids, schema, extraction (no graph) ----

def test_event_id_ignores_case_and_spacing():
    a = events.event_id("Tunde  left.\nAda takes over")
    b = events.event_id("  tunde LEFT. ada takes over ")
    assert a == b
    assert a.startswith("evt-")


def test_event_id_differs_for_different_text():
    assert events.event_id("a") != events.event_id("b")


def test_schema_accepts_demo_json():
    ev = ChangeEvent.model_validate(DEMO_JSON)
    assert ev.from_ == "Tunde Bakare"
    assert ev.services == ["payments-api", "ledger"]


@pytest.mark.parametrize(
    "bad",
    [
        {**DEMO_JSON, "role": "owner"},           # extra key is an injection vector
        {**DEMO_JSON, "effective": "17/10/2026"},  # wrong date format
        {**DEMO_JSON, "effective": "2026-02-30"},  # not a real date
        {**DEMO_JSON, "type": "promote"},          # unknown type
    ],
)
def test_schema_rejects(bad):
    with pytest.raises(ValidationError):
        ChangeEvent.model_validate(bad)


def test_extract_uses_llm_json():
    complete = fake_llm(json.dumps(DEMO_JSON))
    ev = events.extract_event(DEMO_TEXT, complete_text=complete)
    assert ev.to == "Ada Okafor"


def test_extract_strips_code_fence():
    complete = fake_llm("```json\n" + json.dumps(DEMO_JSON) + "\n```")
    assert events.extract_event(DEMO_TEXT, complete_text=complete).type == "departure"


def test_extract_retries_once_then_succeeds():
    complete = fake_llm("not json", json.dumps(DEMO_JSON))
    ev = events.extract_event(DEMO_TEXT, complete_text=complete)
    assert ev.type == "departure"
    assert len(complete.calls) == 2
    assert "Return only the JSON object" in complete.calls[1]


def test_extract_fails_cleanly_after_two_bad_replies():
    complete = fake_llm("nope", "still nope")
    with pytest.raises(EventError) as exc:
        events.extract_event(DEMO_TEXT, complete_text=complete)
    assert exc.value.raw == "still nope"
    assert len(complete.calls) == 2


# ---- graph writes (re-seeded before and after each test) ----

def test_demo_event_closes_opens_and_reassigns(reseeded_graph):
    g = reseeded_graph
    before = all_owns_count(g)
    result = events.apply_event_text(g, DEMO_TEXT, complete_text=fake_llm(json.dumps(DEMO_JSON)))

    assert result["status"] == "applied"
    assert len(result["closed"]) == 2
    assert len(result["opened"]) == 2
    assert {t["ticket"] for t in result["tickets_moved"]} == {
        "Refund webhook returns 500",
        "Reconciliation drift in ledger",
    }
    assert all_owns_count(g) == before + 2  # nothing deleted
    assert owner_of(g, "s-payments", "2026-10-17") == ["Ada Okafor"]
    assert owner_of(g, "s-payments", "2026-09-01") == ["Tunde Bakare"]  # history kept
    assert ticket_owners(g) == {"t-101": "p-ada", "t-102": "p-ada", "t-103": "p-tunde", "t-104": "p-chidi"}
    assert all(r["open"] == 1 for r in queries.open_owns_counts(g))
    tunde = db.read(g, "MATCH (p:Person {id:'p-tunde'}) RETURN p.status AS s")[0]["s"]
    assert tunde == "left"


def test_repeat_event_is_a_no_op(reseeded_graph):
    g = reseeded_graph
    events.apply_event_text(g, DEMO_TEXT, complete_text=fake_llm(json.dumps(DEMO_JSON)))
    before = all_owns_count(g)
    # fake_llm() has no replies: any LLM call here fails the test.
    again = events.apply_event_text(g, "  " + DEMO_TEXT.upper() + " ", complete_text=fake_llm())
    assert again["status"] == "already_applied"
    assert all_owns_count(g) == before


def test_handover_to_someone_who_left_is_rejected(reseeded_graph):
    g = reseeded_graph
    events.apply_event_text(g, DEMO_TEXT, complete_text=fake_llm(json.dumps(DEMO_JSON)))
    back = {"type": "handover", "from": "Ada Okafor", "to": "Tunde Bakare",
            "services": ["payments-api"], "effective": "2026-10-18"}
    before = all_owns_count(g)
    result = events.apply_event_text(g, "Ada hands payments-api back to Tunde", complete_text=fake_llm(json.dumps(back)))
    assert result["status"] == "rejected"
    assert all_owns_count(g) == before


def test_service_the_from_person_does_not_own_is_skipped(reseeded_graph):
    g = reseeded_graph
    ev = {"type": "handover", "from": "Chidi Eze", "to": "Ada Okafor",
          "services": ["payments-api", "auth"], "effective": "2026-10-17"}
    result = events.apply_event_text(g, "Chidi hands payments-api and auth to Ada",
                                     complete_text=fake_llm(json.dumps(ev)))
    assert result["status"] == "applied"
    assert [c["service"] for c in result["closed"]] == ["auth"]
    assert any("payments-api" in r for r in result["rejected"])
    assert owner_of(g, "s-payments", "2026-10-17") == ["Tunde Bakare"]


def test_unknown_name_rejects_without_writing(reseeded_graph):
    g = reseeded_graph
    ev = {"type": "handover", "from": "Nobody Here", "to": "Ada Okafor",
          "services": ["payments-api"], "effective": "2026-10-17"}
    before = all_owns_count(g)
    result = events.apply_event_text(g, "Nobody hands payments to Ada", complete_text=fake_llm(json.dumps(ev)))
    assert result["status"] == "rejected"
    assert all_owns_count(g) == before


def test_ambiguous_name_rejects_with_candidates(reseeded_graph):
    g = reseeded_graph
    ev = {"type": "handover", "from": "Tunde Bakare", "to": "Ada",
          "services": ["payments-api"], "effective": "2026-10-17"}
    result = events.apply_event_text(g, "Tunde hands payments-api to Ada", complete_text=fake_llm(json.dumps(ev)))
    assert result["status"] == "rejected"
    assert any("Ada Okafor" in r and "Ada Nwankwo" in r for r in result["reasons"])


def test_missing_effective_defaults_to_today_and_says_so(reseeded_graph):
    g = reseeded_graph
    ev = {"type": "handover", "from": "Tunde Bakare", "to": "Ada Okafor",
          "services": ["payments-api"], "effective": None}
    result = events.apply_event_text(g, "Tunde hands payments-api to Ada", complete_text=fake_llm(json.dumps(ev)))
    assert result["status"] == "applied"
    assert result["event"]["effective"] == date.today().isoformat()
    assert any("today" in n for n in result["notes"])


def test_join_type_is_rejected_for_now(reseeded_graph):
    g = reseeded_graph
    ev = {"type": "join", "from": None, "to": "Ada Okafor",
          "services": ["payments-api"], "effective": "2026-10-17"}
    result = events.apply_event_text(g, "Ada joins payments", complete_text=fake_llm(json.dumps(ev)))
    assert result["status"] == "rejected"


def test_rate_limit_from_llm_writes_nothing(reseeded_graph):
    g = reseeded_graph
    before = all_owns_count(g)

    def limited(system, user):
        raise llm.LLMRateLimited("slow down")

    with pytest.raises(llm.LLMRateLimited):
        events.apply_event_text(g, DEMO_TEXT, complete_text=limited)
    assert all_owns_count(g) == before


def test_known_demo_event_applies_without_llm(reseeded_graph):
    g = reseeded_graph
    result = events.apply_demo_event(g)
    assert result["status"] == "applied"
    assert len(result["closed"]) == 2
    assert owner_of(g, "s-ledger", "2026-10-17") == ["Ada Okafor"]
