"""Keyword router: deterministic, no LLM, no graph."""
import pytest

from app import agent, tools

# (golden id, question, expected tool, expected args)
GOLDEN_ROUTES = [
    (1, "Who owns payments-api?", "who_owns", {"service": "payments-api"}),
    (2, "Who owns ledger?", "who_owns", {"service": "ledger"}),
    (3, "Who owned ledger in 2025-06?", "who_owns", {"service": "ledger", "at": "2025-06"}),
    (4, "What breaks if TB leaves?", "blast_radius", {"person": "TB"}),
    (5, "Who knows payments-api besides the owner?", "who_knows", {"service": "payments-api"}),
    (7, "Who owns payments-api?", "who_owns", {"service": "payments-api"}),
    (8, "Who owned payments-api on 2026-09-01?", "who_owns", {"service": "payments-api", "at": "2026-09-01"}),
    (9, "What changed since 2026-10-15?", "what_changed", {"since": "2026-10-15"}),
    (10, "Who is t-101 assigned to?", "ticket_assignee", {"ticket": "t-101"}),
    (11, "What does Ada work on?", "blast_radius", {"person": "Ada"}),
    (12, "Who owns billing?", "who_owns", {"service": "billing"}),
]


@pytest.mark.parametrize("gid, question, tool, args", GOLDEN_ROUTES, ids=[str(g[0]) for g in GOLDEN_ROUTES])
def test_keyword_router_picks_expected_tool(gid, question, tool, args):
    assert agent.keyword_route(question) == (tool, args)


def test_golden_6_is_an_event_not_a_question():
    # The demo event goes to /events, so the question router must not pick a tool.
    event = ("Tunde Bakare's last day was Friday. Ada Okafor takes over payments-api and ledger, "
             "effective 2026-10-17.")
    assert agent.keyword_route(event) is None


def test_non_matching_text_routes_to_nothing():
    assert agent.keyword_route("Tell me a joke") is None


@pytest.mark.parametrize("raw, expected", [
    ("2025-06", "2025-06-01"),
    ("2026-09-01", "2026-09-01"),
])
def test_month_dates_mean_first_of_month(raw, expected):
    iso, err = tools.normalise_date(raw)
    assert err is None
    assert iso == expected


@pytest.mark.parametrize("raw", ["2026-02-30", "17/10/2026", "yesterday"])
def test_bad_dates_are_errors(raw):
    iso, err = tools.normalise_date(raw)
    assert iso is None
    assert err
