"""Change events (F5, F6).

text -> LLM extracts the fixed JSON -> pydantic validation -> resolve names
-> plan (rejects are decided before any write) -> T5 handover -> T5 departure
-> T6 reassign tickets for each affected service.

Events are never deleted. A repeat of the same text (after normalising) is a no-op.
"""
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app import llm, queries, resolve

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "extract_event.txt"

DEMO_EVENT_TEXT = (
    "Tunde Bakare's last day was Friday. Ada Okafor takes over payments-api and ledger, "
    "effective 2026-10-17."
)
# Known-good extraction of DEMO_EVENT_TEXT. Used when the LLM is down (fallback path).
DEMO_EVENT_JSON = {
    "type": "departure",
    "from": "Tunde Bakare",
    "to": "Ada Okafor",
    "services": ["payments-api", "ledger"],
    "effective": "2026-10-17",
}


class EventError(Exception):
    def __init__(self, message: str, raw: str | None = None):
        super().__init__(message)
        self.raw = raw


class ChangeEvent(BaseModel):
    """The only shape an event may take. Extra keys are rejected."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["handover", "departure", "join"]
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    services: list[str] = Field(default_factory=list)
    effective: str | None = None

    @field_validator("effective")
    @classmethod
    def _iso_date(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError("effective must be YYYY-MM-DD")
        date.fromisoformat(v)  # rejects impossible dates such as 2026-02-30
        return v


def normalise(text: str) -> str:
    return " ".join(text.split()).lower()


def event_id(text: str) -> str:
    return "evt-" + hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()[:16]


# ---- extraction ----

def _strip_fence(raw: str) -> str:
    s = raw.strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", s, re.S)
    return m.group(1) if m else s


def extract_event(text: str, complete_text=llm.complete_text) -> ChangeEvent:
    system = PROMPT_PATH.read_text(encoding="utf-8")
    user = f"Event text:\n<<<\n{text}\n>>>"
    raw, reason = "", ""
    for attempt in (1, 2):
        message = user if attempt == 1 else user + "\n\nReturn only the JSON object."
        raw = complete_text(system, message)
        try:
            return ChangeEvent.model_validate(json.loads(_strip_fence(raw)))
        except (json.JSONDecodeError, ValidationError) as e:
            reason = str(e)
    raise EventError(f"Could not extract a valid event: {reason}", raw=raw)


# ---- planning (no writes) ----

def _unique(values) -> list:
    """Keep the first of each value, in order."""
    seen, out = set(), []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _unique_tickets(tickets: list[dict]) -> list[dict]:
    """Keep the first entry for each ticket id."""
    seen, out = set(), []
    for t in tickets:
        if t["ticket_id"] not in seen:
            seen.add(t["ticket_id"])
            out.append(t)
    return out


def _reject(reasons: list[str]) -> dict:
    return {"status": "rejected", "reasons": reasons}


def _resolve_person(graph, name: str, role: str):
    r = resolve.resolve(graph, name)
    if r["status"] == "ok" and r["kind"] == "Person":
        return r, None
    if r["status"] == "clarify":
        names = ", ".join(c["name"] for c in r["candidates"])
        return None, f"{role} '{name}' is ambiguous: {names}"
    return None, f"{role} '{name}' is not a known person"


def _resolve_service(graph, name: str):
    r = resolve.resolve(graph, name)
    if r["status"] == "ok" and r["kind"] == "Service":
        return r, None
    return None, f"service '{name}' is not a known service"


def plan_event(graph, ev: ChangeEvent) -> dict:
    if ev.type == "join":
        return _reject(["join events are not applied yet"])
    if not ev.from_ or not ev.to:
        return _reject(["handover and departure need both 'from' and 'to'"])
    if not ev.services:
        return _reject(["no services named"])

    frm, why = _resolve_person(graph, ev.from_, "from")
    if why:
        return _reject([why])
    to, why = _resolve_person(graph, ev.to, "to")
    if why:
        return _reject([why])
    if to["entity_status"] == "left":
        return _reject([f"{to['name']} has left and cannot take ownership"])

    owned = {r["service"] for r in queries.open_services_of(graph, frm["id"])}
    services, skipped, notes = [], [], []
    for name in ev.services:
        svc, why = _resolve_service(graph, name)
        if why:
            skipped.append(why)
        elif svc["id"] not in owned:
            skipped.append(f"{frm['name']} does not own {svc['name']}")
        else:
            services.append(svc)
    if not services:
        return _reject(skipped)

    effective = ev.effective
    if effective is None:
        effective = date.today().isoformat()
        notes.append(f"no effective date given; using today ({effective})")

    return {
        "status": "ok",
        "type": ev.type,
        "from": frm,
        "to": to,
        "services": services,
        "effective": effective,
        "skipped": skipped,
        "notes": notes,
    }


# ---- apply (writes) ----

def _apply(graph, plan: dict, text: str, eid: str) -> dict:
    frm, to = plan["from"], plan["to"]
    effective = plan["effective"]
    service_ids = [s["id"] for s in plan["services"]]

    # T5: close the old OWNS edges and open new ones, with this event as provenance.
    rows = queries.apply_handover(graph, {
        "event_id": eid,
        "text": text,
        "effective": effective,
        "from": frm["id"],
        "to": to["id"],
        "services": service_ids,
    })
    # One entry per service and per ticket: a result never lists the same id twice.
    closed = [{"service": s, "from": frm["name"]} for s in _unique(r["service"] for r in rows)]
    opened = [{"service": s, "to": to["name"]} for s in _unique(r["service"] for r in rows)]

    if plan["type"] == "departure":
        queries.apply_departure(graph, {"from": frm["id"], "effective": effective})

    # T6: move open tickets from anyone who left to the current owner.
    # $today in T6 is the event's effective date, so ticket dates match the event.
    moved = []
    for svc_id in service_ids:
        moved += queries.reassign_tickets(graph, {"service": svc_id, "today": effective, "event_id": eid})

    return {
        "status": "applied",
        "event_id": eid,
        "event": {"type": plan["type"], "from": frm["name"], "to": to["name"],
                  "services": [s["name"] for s in plan["services"]], "effective": effective},
        # Ids, so the page can focus on exactly the people, services and tickets involved.
        "ids": {
            "from": frm["id"],
            "to": to["id"],
            "services": service_ids,
            "tickets": [m["ticket_id"] for m in moved],
            "effective": effective,
        },
        "closed": closed,
        "opened": opened,
        "tickets_moved": _unique_tickets([
            {"ticket_id": m["ticket_id"], "ticket": m["ticket"], "from": m["from"], "to": m["to"]}
            for m in moved
        ]),
        "rejected": plan["skipped"],
        "notes": plan["notes"],
    }


def apply_parsed_event(graph, ev: ChangeEvent, text: str) -> dict:
    eid = event_id(text)
    if queries.event_exists(graph, eid):
        return {"status": "already_applied", "event_id": eid}
    plan = plan_event(graph, ev)
    if plan["status"] != "ok":
        return {"status": "rejected", "event_id": eid, "reasons": plan["reasons"]}
    return _apply(graph, plan, text, eid)


def apply_event_text(graph, text: str, complete_text=llm.complete_text) -> dict:
    eid = event_id(text)
    # Check first, so a repeat never spends an LLM call.
    if queries.event_exists(graph, eid):
        return {"status": "already_applied", "event_id": eid}
    ev = extract_event(text, complete_text=complete_text)
    return apply_parsed_event(graph, ev, text)


def apply_known_event(graph, data: dict, text: str) -> dict:
    """Fallback: apply an event JSON directly, with no LLM. Same validation and writes."""
    return apply_parsed_event(graph, ChangeEvent.model_validate(data), text)


def apply_demo_event(graph) -> dict:
    return apply_known_event(graph, DEMO_EVENT_JSON, DEMO_EVENT_TEXT)
