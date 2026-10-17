"""Agent, tools and paths. The LLM is mocked everywhere; graph reads hit the seed."""
import json
from types import SimpleNamespace as NS

import pytest

from app import agent, events, llm, tools
from app.db import connect


@pytest.fixture(scope="module")
def graph():
    return connect()


def tool_call_msg(name, args):
    return NS(content=None, tool_calls=[NS(function=NS(name=name, arguments=json.dumps(args)))])


def text_msg(text):
    return NS(content=text, tool_calls=None)


def scripted(router_reply=None, router_exc=None, answer_text="", answer_exc=None):
    """Fake llm.complete: the router call passes tools=..., the answer call does not."""
    def complete(messages, tools=None):
        if tools is not None:
            if router_exc:
                raise router_exc
            return router_reply
        if answer_exc:
            raise answer_exc
        return text_msg(answer_text)
    return complete


def names(rows, key="person"):
    return [r[key] for r in rows]


# ---- routing ----

def test_llm_route_is_used_when_valid(graph):
    res = agent.answer(graph, "Who owns payments-api?", complete=scripted(
        router_reply=tool_call_msg("who_owns", {"service": "payments-api"}),
        answer_text="Tunde Bakare owns payments-api [m01]."))
    assert res["status"] == "ok"
    assert res["router"] == "llm"
    assert res["tool"] == "who_owns"
    assert res["phrased_by"] == "llm"
    assert names(res["rows"]) == ["Tunde Bakare"]
    assert res["cypher"]["id"] == "T1"
    assert [s["id"] for s in res["sources"]] == ["m01"]


@pytest.mark.parametrize("exc", [
    llm.LLMRateLimited("The LLM provider is rate limited (HTTP 429)."),
    llm.LLMError("LLM timed out after 8 s."),
])
def test_llm_errors_fall_back_to_keyword(graph, exc):
    res = agent.answer(graph, "What breaks if TB leaves?", complete=scripted(router_exc=exc, answer_text="x"))
    assert res["router"] == "keyword"
    assert res["tool"] == "blast_radius"
    assert res["llm_note"] == str(exc)


def test_no_tool_call_falls_back_to_keyword(graph):
    res = agent.answer(graph, "Who owns ledger?", complete=scripted(
        router_reply=text_msg("I think it is Tunde."), answer_text="x"))
    assert res["router"] == "keyword"
    assert res["tool"] == "who_owns"


def test_unknown_tool_name_falls_back_to_keyword(graph):
    res = agent.answer(graph, "Who owns ledger?", complete=scripted(
        router_reply=tool_call_msg("drop_everything", {}), answer_text="x"))
    assert res["router"] == "keyword"


def test_missing_required_arg_falls_back_to_keyword(graph):
    res = agent.answer(graph, "Who owns ledger?", complete=scripted(
        router_reply=tool_call_msg("who_owns", {}), answer_text="x"))
    assert res["router"] == "keyword"


def test_llm_cannot_inject_cypher(graph):
    evil = "x} MATCH (n) DETACH DELETE n //"
    res = agent.answer(graph, "Who owns ledger?", complete=scripted(
        router_reply=tool_call_msg("who_owns", {"service": evil}), answer_text="x"))
    # The text is only ever resolved as a name. It is never executed.
    assert res["router"] == "llm"
    assert res["status"] == "unknown"
    # The graph is untouched: the ledger owner is still there.
    assert names(_keyword_only(graph, "Who owns ledger?")["rows"]) == ["Tunde Bakare"]


def test_answer_phrasing_falls_back_to_template_with_citation(graph):
    res = agent.answer(graph, "Who owns payments-api?", complete=scripted(
        router_exc=llm.LLMError("down"), answer_exc=llm.LLMError("down")))
    assert res["status"] == "ok"
    assert res["phrased_by"] == "template"
    assert "Tunde Bakare" in res["answer"]
    assert "[m01]" in res["answer"]


def test_missing_citation_is_appended(graph):
    res = agent.answer(graph, "Who owns payments-api?", complete=scripted(
        router_exc=llm.LLMError("down"), answer_text="Tunde Bakare owns it."))
    assert res["answer"].endswith("[m01]")


# ---- golden questions through the agent (keyword router, mocked phrasing) ----

def _keyword_only(graph, question):
    return agent.answer(graph, question, complete=scripted(router_exc=llm.LLMError("off"), answer_text="x"))


def test_golden_1_owner_and_path(graph):
    res = _keyword_only(graph, "Who owns payments-api?")
    node_ids = {n["id"] for n in res["path"]["nodes"]}
    assert {"p-tunde", "s-payments", "m01"} <= node_ids
    owns = [e for e in res["path"]["edges"] if e["type"] == "OWNS"]
    assert owns == [{"from": "p-tunde", "to": "s-payments", "type": "OWNS", "closed": False}]


def test_golden_2_ledger_owner(graph):
    assert names(_keyword_only(graph, "Who owns ledger?")["rows"]) == ["Tunde Bakare"]


def test_golden_3_history_by_month(graph):
    res = _keyword_only(graph, "Who owned ledger in 2025-06?")
    assert names(res["rows"]) == ["Segun Bello"]
    assert res["cypher"]["params"]["at"] == "2025-06-01"


def test_golden_4_blast_radius(graph):
    res = _keyword_only(graph, "What breaks if TB leaves?")
    assert res["status"] == "ok"
    owned = {r["owned"] for r in res["rows"]}
    assert owned == {"payments-api", "ledger"}
    node_ids = {n["id"] for n in res["path"]["nodes"]}
    assert {"p-tunde", "s-payments", "s-ledger", "s-mobile", "s-notify", "t-101", "t-102"} <= node_ids


def test_blast_path_draws_only_real_dependency_hops(graph):
    # Stored DEPENDS_ON edges into Tunde's services. No shortcut edge mobile-app -> ledger.
    res = _keyword_only(graph, "What breaks if TB leaves?")
    deps = {(e["from"], e["to"]) for e in res["path"]["edges"] if e["type"] == "DEPENDS_ON"}
    assert deps == {("s-mobile", "s-payments"), ("s-payments", "s-ledger"), ("s-notify", "s-payments")}


def test_golden_5_who_knows_drops_the_owner(graph):
    res = _keyword_only(graph, "Who knows payments-api besides the owner?")
    assert res["tool"] == "who_knows"
    people = names(res["rows"])
    assert "Tunde Bakare" not in people
    assert people[0] == "Ada Okafor"


def test_golden_7_8_history_queries(graph):
    # Before the demo event both answers match the seed; the event test covers "after".
    assert names(_keyword_only(graph, "Who owned payments-api on 2026-09-01?")["rows"]) == ["Tunde Bakare"]


def test_golden_9_what_changed_before_event_is_empty(graph):
    res = _keyword_only(graph, "What changed since 2026-10-15?")
    assert res["status"] == "ok"
    assert res["rows"] == []
    assert "No changes" in res["answer"]


def test_golden_10_ticket_assignee_before_event(graph):
    res = _keyword_only(graph, "Who is t-101 assigned to?")
    assert res["tool"] == "ticket_assignee"
    assert names(res["rows"]) == ["Tunde Bakare"]
    assert res["path"]["nodes"][0]["id"] == "t-101"


def test_golden_11_two_adas_clarify(graph):
    res = _keyword_only(graph, "What does Ada work on?")
    assert res["status"] == "clarify"
    assert {c["name"] for c in res["clarify"]} == {"Ada Okafor", "Ada Nwankwo"}


def test_golden_12_unknown_service_with_suggestions(graph):
    res = _keyword_only(graph, "Who owns billing?")
    assert res["status"] == "unknown"
    assert len(res["suggestions"]) == 3


def test_no_route_returns_examples(graph):
    res = agent.answer(graph, "Tell me a joke", complete=scripted(router_reply=text_msg("hi")))
    assert res["status"] == "no_tool"
    assert res["examples"]


# ---- tool checks ----

def test_ticket_id_must_look_like_a_ticket(graph):
    res = tools.run(graph, "ticket_assignee", {"ticket": "t-abc"})
    assert res["status"] == "error"


def test_unknown_ticket_is_unknown(graph):
    res = tools.run(graph, "ticket_assignee", {"ticket": "t-999"})
    assert res["status"] == "unknown"


def test_bad_date_is_an_error(graph):
    res = tools.run(graph, "who_owns", {"service": "ledger", "at": "2026-02-30"})
    assert res["status"] == "error"


def test_ambiguous_person_for_blast_radius_clarifies(graph):
    res = tools.run(graph, "blast_radius", {"person": "Ada"})
    assert res["status"] == "clarify"


# ---- after the demo event (writes; re-seeded afterwards) ----

def test_after_event_answers_change_and_history_survives(reseeded_graph):
    g = reseeded_graph
    events.apply_demo_event(g)
    eid = events.event_id(events.DEMO_EVENT_TEXT)

    now = _keyword_only(g, "Who owns payments-api?")
    assert names(now["rows"]) == ["Ada Okafor"]
    assert now["rows"] and [s["id"] for s in now["sources"]] == [eid]

    past = _keyword_only(g, "Who owned payments-api on 2026-09-01?")
    assert names(past["rows"]) == ["Tunde Bakare"]

    ticket = _keyword_only(g, "Who is t-101 assigned to?")
    assert names(ticket["rows"]) == ["Ada Okafor"]
    assert [s["id"] for s in ticket["sources"]] == [eid]


# ---- LLM phrasing sees only tool results ----

def test_phrasing_prompt_contains_results_not_cypher(graph):
    seen = []

    def complete(messages, tools=None):
        if tools is not None:
            return tool_call_msg("who_owns", {"service": "ledger"})
        seen.append(messages[-1]["content"])
        return text_msg("Tunde Bakare owns ledger [m02].")

    agent.answer(graph, "Who owns ledger?", complete=complete)
    assert seen and "Results (JSON)" in seen[0]
    assert "MATCH" not in seen[0]
