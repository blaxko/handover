"""Alias resolution (F2): free text -> one entity id, or a clarification, or unknown.

Result shapes:
  {"status": "ok", "id", "name", "kind"}
  {"status": "clarify", "candidates": [{"id", "name", "kind"}, ...]}
  {"status": "unknown", "suggestions": [{"id", "name", "kind"}, ...]}
"""
from difflib import SequenceMatcher

from app import queries

SUGGESTION_COUNT = 3


def _brief(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "kind": row["kind"]}


def _suggestions(q: str, rows: list[dict]) -> list[dict]:
    needle = q.strip().lower().lstrip("@")

    def score(row: dict) -> float:
        names = [row["name"], *(row["aliases"] or [])]
        return max(SequenceMatcher(None, needle, n.lower().lstrip("@")).ratio() for n in names)

    ranked = sorted(rows, key=score, reverse=True)
    return [_brief(r) for r in ranked[:SUGGESTION_COUNT]]


def resolve(graph, text: str) -> dict:
    q = text.strip()
    if not q:
        return {"status": "unknown", "suggestions": []}

    # An exact id (p-ada, s-payments) wins; otherwise match names and aliases.
    matches = queries.entity_by_id(graph, q) or queries.resolve_entity(graph, q)
    if not matches:
        return {"status": "unknown", "suggestions": _suggestions(q, queries.all_entities(graph))}

    # Several people with the same name or alias: never pick one silently.
    people = [m for m in matches if m["kind"] == "Person"]
    if len(people) > 1:
        return {"status": "clarify", "candidates": [_brief(m) for m in people]}

    if len(matches) > 1:
        return {"status": "clarify", "candidates": [_brief(m) for m in matches]}

    m = matches[0]
    return {
        "status": "ok",
        "id": m["id"],
        "name": m["name"],
        "kind": m["kind"],
        "entity_status": m.get("status"),  # Person: 'active' or 'left'; Service: None
    }
