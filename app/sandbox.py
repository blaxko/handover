"""Per-visitor sandboxes: one FalkorDB graph per anonymous session.

A control graph (CONTROL) holds one :Sandbox node per session: sid, graph name, last_seen.
Each sandbox graph is named tidewell-<sid> and starts as a copy of the seed.

Limits: a sandbox idle for more than IDLE_S is deleted, and at most CAP live sandboxes
are kept (the least recently used go first). Reaping runs at most every REAP_EVERY_S.
"""
import re
import secrets
import time

import redis

from app import db, queries, seed

CONTROL = "handover-sandboxes"
IDLE_S = 2 * 60 * 60
CAP = 50
REAP_EVERY_S = 60
TOUCH_EVERY_S = 60
SID_RE = re.compile(r"[0-9a-f]{24}")

_last_reap = 0.0


def new_sid() -> str:
    return secrets.token_hex(12)


def valid_sid(sid: str | None) -> bool:
    return bool(sid) and SID_RE.fullmatch(sid) is not None


def graph_name(sid: str) -> str:
    return f"tidewell-{sid}"


def _control():
    return db.connect(graph_name=CONTROL)


def _read(ctrl, cypher: str, params: dict | None = None) -> list[dict]:
    """Read the control graph. A graph that does not exist yet has no rows."""
    try:
        return db.read(ctrl, cypher, params)
    except redis.exceptions.ResponseError as e:
        if "empty key" in str(e):
            return []
        raise


def reap(now: float | None = None) -> int:
    """Delete idle sandboxes, then the least recently used ones beyond CAP. Returns how many went."""
    now = time.time() if now is None else now
    ctrl = _control()
    stale = _read(ctrl, queries.SANDBOX_STALE,
                    {"cutoff": now - IDLE_S})
    live = _read(ctrl, queries.SANDBOX_LIVE_OLDEST_FIRST)
    stale_ids = {r["sid"] for r in stale}
    live = [r for r in live if r["sid"] not in stale_ids]
    overflow = max(0, len(live) - CAP)
    doomed = stale + live[:overflow]
    for row in doomed:
        db.connect(graph_name=row["graph"]).delete()
        db.write(ctrl, queries.SANDBOX_DELETE, {"sid": row["sid"]})
    return len(doomed)


def _reap_if_due(now: float) -> None:
    global _last_reap
    if now - _last_reap >= REAP_EVERY_S:
        _last_reap = now
        reap(now)


def ensure(sid: str):
    """Return this session's graph, creating and seeding it on first use."""
    now = time.time()
    ctrl = _control()
    rows = _read(ctrl, queries.SANDBOX_LOOKUP, {"sid": sid})
    if not rows:
        _reap_if_due(now)
        graph = db.connect(graph_name=graph_name(sid))
        seed.reset(graph)
        db.write(ctrl, queries.SANDBOX_CREATE,
                 {"sid": sid, "graph": graph_name(sid), "now": now})
        return graph
    if now - (rows[0]["seen"] or 0) >= TOUCH_EVERY_S:
        db.write(ctrl, queries.SANDBOX_TOUCH, {"sid": sid, "now": now})
    return db.connect(graph_name=graph_name(sid))
