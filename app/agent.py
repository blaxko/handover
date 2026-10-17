"""The agent: route a question to one tool, run it, phrase the answer with citations.

Router order: the LLM picks a tool (tool calling). If the LLM errors, is rate
limited, times out, or returns no valid tool call, a deterministic keyword
router takes over. The LLM never writes Cypher; tools run fixed templates.
"""
import json
import re
from pathlib import Path

from app import llm, queries, tools

PROMPTS = Path(__file__).resolve().parent / "prompts"
ROUTER_PROMPT = (PROMPTS / "router.txt").read_text(encoding="utf-8")
ANSWER_PROMPT = (PROMPTS / "answer.txt").read_text(encoding="utf-8")

EXAMPLES = [
    "Who owns payments-api?",
    "What breaks if TB leaves?",
    "Who owned ledger in 2025-06?",
]
NO_TOOL_MESSAGE = "I can't answer that from the company graph. Try one of these:"

_TICKET = re.compile(r"\b(t-\d+)\b", re.I)
_BREAKS = re.compile(r"what\s+breaks\s+if\s+(.+?)\s+leaves\b", re.I)
_CHANGED = re.compile(r"what\s+changed\s+since\s+(\d{4}-\d{2}(?:-\d{2})?)", re.I)
_KNOWS = re.compile(r"who\s+knows\s+(.+?)(?:\s+besides\b.*)?\s*\??\s*$", re.I)
_WORKS = re.compile(r"what\s+does\s+(.+?)\s+work\s+on\b", re.I)
_OWNER = re.compile(
    r"who\s+(?:owns|owned|own)\s+(.+?)"
    r"(?:\s+(?:on|in|as of|at)\s+(\d{4}-\d{2}(?:-\d{2})?))?\s*\??\s*$",
    re.I,
)


def route_with_llm(question: str, complete=llm.complete):
    """Return (tool, args) or None when the LLM gives no single valid tool call."""
    msg = complete(
        [{"role": "system", "content": ROUTER_PROMPT}, {"role": "user", "content": question}],
        tools=tools.TOOL_SCHEMAS,
    )
    calls = getattr(msg, "tool_calls", None) or []
    if len(calls) != 1:
        return None
    fn = calls[0].function
    try:
        args = json.loads(fn.arguments or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    if tools.validate_args(fn.name, args):
        return None
    return fn.name, args


def keyword_route(question: str):
    """Deterministic fallback. Returns (tool, args) or None."""
    q = question.strip()
    m = _TICKET.search(q)
    if m and re.search(r"\bassign", q, re.I):
        return "ticket_assignee", {"ticket": m.group(1).lower()}
    m = _BREAKS.search(q)
    if m:
        return "blast_radius", {"person": m.group(1)}
    m = _CHANGED.search(q)
    if m:
        return "what_changed", {"since": m.group(1)}
    m = _KNOWS.search(q)
    if m:
        return "who_knows", {"service": m.group(1)}
    m = _WORKS.search(q)
    if m:
        return "blast_radius", {"person": m.group(1)}
    m = _OWNER.search(q)
    if m:
        args = {"service": m.group(1)}
        if m.group(2):
            args["at"] = m.group(2)
        return "who_owns", args
    return None


def _template_answer(name: str, result: dict) -> str:
    rows = result["rows"]
    if name == "who_owns":
        if not rows:
            return f"No recorded owner for {result['service']} on {result['at']}."
        r = rows[0]
        text = f"{r['person']} owns {result['service']} as of {result['at']}."
        if result["conflict"]:
            text += " Conflict: more than one open owner."
        return text
    if name == "who_knows":
        if not rows:
            return f"No one besides the owner is recorded for {result['service']}."
        return "Others who know " + result["service"] + ": " + ", ".join(r["person"] for r in rows) + "."
    if name == "what_changed":
        if not rows:
            return f"No changes since {result['since']}."
        return f"{len(rows)} change(s) since {result['since']}."
    if name == "blast_radius":
        if not rows:
            return f"{result['person']} owns no services now."
        owned = ", ".join(r["owned"] for r in rows)
        deps = sorted({d for r in rows for d in r["dependents"]})
        tickets = sorted({t for r in rows for t in r["open_tickets"]})
        return (f"{result['person']} owns {owned}. Dependents: {', '.join(deps) or 'none'}. "
                f"Open tickets: {', '.join(tickets) or 'none'}.")
    if name == "ticket_assignee":
        r = rows[0]
        return f"{result['ticket']} is assigned to {r['person']}."
    return ""


def _cite(text: str, sources: list[str]) -> str:
    if sources and not any(f"[{s}]" in text for s in sources):
        text = f"{text} " + " ".join(f"[{s}]" for s in sources)
    return text


def _phrase(question: str, name: str, result: dict, complete):
    """Return (text, phrased_by). The LLM phrases tool results; it does not add facts."""
    fallback = _template_answer(name, result)
    if not result["rows"]:
        return _cite(fallback, result["sources"]), "template"
    user = (
        f"Question: {question}\n"
        f"Tool: {name}\n"
        f"Results (JSON): {json.dumps({'rows': result['rows'], 'sources': result['sources']}, default=str)}"
    )
    try:
        text = complete([{"role": "system", "content": ANSWER_PROMPT},
                         {"role": "user", "content": user}]).content or ""
    except llm.LLMError:
        return _cite(fallback, result["sources"]), "template"
    text = text.strip()
    if not text:
        return _cite(fallback, result["sources"]), "template"
    return _cite(text, result["sources"]), "llm"


def answer(graph, question: str, complete=None, default_at: str | None = None) -> dict:
    complete = complete or llm.complete
    note = None
    route, router = None, None
    try:
        route = route_with_llm(question, complete)
        router = "llm" if route else None
    except llm.LLMError as e:
        note = str(e)
    if route is None:
        route = keyword_route(question)
        router = "keyword" if route else None
    if route is None:
        return {"status": "no_tool", "router": None, "llm_note": note,
                "message": NO_TOOL_MESSAGE, "examples": EXAMPLES}

    name, args = route
    if default_at and name == "who_owns" and "at" not in args:
        args = {**args, "at": default_at}  # POST /ask body "at" applies when the question has no date
    result = tools.run(graph, name, args)
    base = {"router": router, "llm_note": note, "tool": name, "params": args}
    if result["status"] != "ok":
        return {**base, "status": result["status"], "message": result.get("message"),
                "clarify": result.get("clarify"), "suggestions": result.get("suggestions")}

    text, phrased_by = _phrase(question, name, result, complete)
    sources = queries.messages_by_id(graph, result["sources"]) if result["sources"] else []
    return {
        **base,
        "status": "ok",
        "answer": text,
        "phrased_by": phrased_by,
        "rows": result["rows"],
        "path": result["path"],
        "sources": sources,
        "cypher": result["cypher"],
    }
