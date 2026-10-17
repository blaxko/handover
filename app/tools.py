"""The five read tools the agent can call.

Each tool resolves names through resolve.py first, then runs a fixed template
from queries.py. The LLM only picks a tool and fills names or dates; it never
supplies Cypher.
"""
import re
from datetime import date

from app import paths, queries, resolve

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "who_owns",
            "description": "Who owns a service, now or at a date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "Service name or alias, e.g. payments-api"},
                    "at": {"type": "string", "description": "YYYY-MM-DD or YYYY-MM. Omit for today."},
                },
                "required": ["service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "who_knows",
            "description": "Who else knows a service, besides its current owner.",
            "parameters": {
                "type": "object",
                "properties": {"service": {"type": "string"}},
                "required": ["service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "what_changed",
            "description": "Ownership and assignment changes since a date.",
            "parameters": {
                "type": "object",
                "properties": {"since": {"type": "string", "description": "YYYY-MM-DD or YYYY-MM"}},
                "required": ["since"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "blast_radius",
            "description": "What a person owns now, what depends on it, and their open tickets.",
            "parameters": {
                "type": "object",
                "properties": {"person": {"type": "string", "description": "Person name, alias or handle"}},
                "required": ["person"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ticket_assignee",
            "description": "Who a ticket is currently assigned to.",
            "parameters": {
                "type": "object",
                "properties": {"ticket": {"type": "string", "description": "Ticket id, e.g. t-101"}},
                "required": ["ticket"],
            },
        },
    },
]

REQUIRED = {
    "who_owns": ["service"],
    "who_knows": ["service"],
    "what_changed": ["since"],
    "blast_radius": ["person"],
    "ticket_assignee": ["ticket"],
}

# Tool name -> (template id in PRD §6.6, template text) for "show Cypher".
TEMPLATES = {
    "who_owns": ("T1", queries.T1_WHO_OWNS),
    "who_knows": ("T2", queries.T2_WHO_KNOWS),
    "what_changed": ("T3", queries.T3_WHAT_CHANGED),
    "blast_radius": ("T4", queries.T4_BLAST_RADIUS),
    "ticket_assignee": ("T7", queries.T7_TICKET_ASSIGNEE),
}

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH = re.compile(r"^\d{4}-\d{2}$")
_TICKET = re.compile(r"^t-\d+$")


def normalise_date(value: str | None) -> tuple[str | None, str | None]:
    """Return (iso_date, error). A YYYY-MM means the first of that month. None means today."""
    if value is None or str(value).strip() == "":
        return date.today().isoformat(), None
    v = str(value).strip()
    if _MONTH.match(v):
        v = v + "-01"
    if not _DATE.match(v):
        return None, f"'{value}' is not a date; use YYYY-MM-DD or YYYY-MM"
    try:
        date.fromisoformat(v)
    except ValueError:
        return None, f"'{value}' is not a real date"
    return v, None


def validate_args(name: str, args) -> str | None:
    if name not in REQUIRED:
        return f"unknown tool '{name}'"
    if not isinstance(args, dict):
        return "arguments must be an object"
    for key in REQUIRED[name]:
        if not isinstance(args.get(key), str) or not args[key].strip():
            return f"missing '{key}'"
    return None


def _error(message: str) -> dict:
    return {"status": "error", "message": message}


def _entity(graph, name: str, kind: str):
    """Resolve a name. Returns (entity, None) or (None, non-ok result)."""
    r = resolve.resolve(graph, name)
    if r["status"] == "ok" and r["kind"] == kind:
        return r, None
    if r["status"] == "clarify":
        return None, {"status": "clarify", "clarify": r["candidates"],
                      "message": f"'{name}' matches more than one {kind.lower()}."}
    if r["status"] == "unknown":
        return None, {"status": "unknown", "suggestions": r["suggestions"],
                      "message": f"I don't know a {kind.lower()} called '{name}'."}
    return None, {"status": "unknown", "suggestions": [],
                  "message": f"'{name}' is not a {kind.lower()}."}


def _ok(tool: str, params: dict, rows: list, bound: dict, sources=None, extra=None) -> dict:
    return {
        "status": "ok",
        "tool": tool,
        "params": params,
        "bound": bound,
        "rows": rows,
        "sources": list(dict.fromkeys(sources or [])),
        **(extra or {}),
    }


# ---- the five tools ----

def who_owns(graph, args):
    svc, early = _entity(graph, args["service"], "Service")
    if early:
        return early
    at, err = normalise_date(args.get("at"))
    if err:
        return _error(err)
    rows = queries.who_owns(graph, svc["id"], at)
    return _ok("who_owns", args, rows, bound={"service": svc["id"], "at": at},
               sources=[r["source"] for r in rows if r.get("source")],
               extra={"service": svc["name"], "service_id": svc["id"], "at": at,
                      "conflict": len(rows) > 1})


def who_knows(graph, args):
    svc, early = _entity(graph, args["service"], "Service")
    if early:
        return early
    # Drop the current owner: the question asks for someone *besides* them.
    owners = {r["person"] for r in queries.who_owns(graph, svc["id"], date.today().isoformat())}
    rows = [r for r in queries.who_knows(graph, svc["id"]) if r["person"] not in owners]
    return _ok("who_knows", args, rows, bound={"service": svc["id"]},
               sources=[m for r in rows for m in r["sources"]],
               extra={"service": svc["name"], "service_id": svc["id"], "dropped_owner": sorted(owners)})


def what_changed(graph, args):
    since, err = normalise_date(args["since"])
    if err:
        return _error(err)
    rows = queries.what_changed(graph, since)
    return _ok("what_changed", args, rows, bound={"since": since},
               sources=[r["source"] for r in rows if r.get("source")],
               extra={"since": since})


def blast_radius(graph, args):
    person, early = _entity(graph, args["person"], "Person")
    if early:
        return early
    rows = queries.blast_radius(graph, person["id"])
    # Real DEPENDS_ON hops into each owned service, for drawing (no shortcut edges).
    hops, seen = [], set()
    for owned in queries.open_services_of(graph, person["id"]):
        for hop in queries.dependency_hops(graph, owned["service"]):
            key = (hop["src"], hop["dst"], hop["type"])
            if key not in seen:
                seen.add(key)
                hops.append(hop)
    return _ok("blast_radius", args, rows, bound={"person": person["id"]},
               extra={"person": person["name"], "person_id": person["id"], "hops": hops})


def ticket_assignee(graph, args):
    ticket = args["ticket"].strip().lower()
    if not _TICKET.match(ticket):
        return _error(f"'{args['ticket']}' is not a ticket id; use something like t-101")
    rows = queries.ticket_assignee(graph, ticket)
    if not rows:
        return {"status": "unknown", "suggestions": [],
                "message": f"No current assignment found for {ticket}."}
    first = rows[0]
    return _ok("ticket_assignee", args, rows, bound={"ticket": ticket},
               sources=[first["source"]] if first.get("source") else [],
               extra={"ticket_id": ticket, "ticket": first["ticket"]})


_FUNCS = {
    "who_owns": who_owns,
    "who_knows": who_knows,
    "what_changed": what_changed,
    "blast_radius": blast_radius,
    "ticket_assignee": ticket_assignee,
}


def _name_ids(graph) -> dict:
    ids = {e["name"]: e["id"] for e in queries.all_entities(graph)}
    ids.update({t["name"]: t["id"] for t in queries.open_tickets(graph)})
    return ids


def run(graph, name: str, args: dict) -> dict:
    err = validate_args(name, args)
    if err:
        return {"status": "error", "tool": name, "message": err}
    result = _FUNCS[name](graph, args)
    result.setdefault("tool", name)
    if result["status"] == "ok":
        tid, template = TEMPLATES[name]
        result["cypher"] = {"id": tid, "template": template.strip(), "params": result["bound"]}
        result["path"] = paths.build(name, result, _name_ids(graph))
    return result
