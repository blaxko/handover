"""Per-visitor sandboxes: one FalkorDB graph per anonymous session.

A control graph (CONTROL) holds one :Sandbox node per session: sid, graph name, last_seen.
Each sandbox graph is named tidewell-<sid> and starts as a copy of the seed.

Rules that keep a sandbox correct:
- Every change to a session's graph (creating it, resetting it, applying a handover) runs under that
  session's lock, so concurrent requests cannot seed or write the same graph twice.
- A session is registered only after its seed has succeeded and passed the invariant checks.
- After seeding and after every handover, the invariants are checked. If one fails, the sandbox is
  re-seeded from scratch and the failure is logged.

Limits: a sandbox idle for more than IDLE_S is deleted, and at most CAP live sandboxes are kept
(the least recently used go first). Reaping runs at most every REAP_EVERY_S.
"""
import re
import secrets
import sys
import threading
import time
from contextlib import contextmanager

import redis

from app import db, queries, seed

CONTROL = "handover-sandboxes"
IDLE_S = 2 * 60 * 60
CAP = 50
REAP_EVERY_S = 60
TOUCH_EVERY_S = 60
SID_RE = re.compile(r"[0-9a-f]{24}")
EXPECTED_PEOPLE = 9
EXPECTED_TICKETS = 4

_last_reap = 0.0
_locks_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}


def new_sid() -> str:
    return secrets.token_hex(12)


def valid_sid(sid: str | None) -> bool:
    return bool(sid) and SID_RE.fullmatch(sid) is not None


def graph_name(sid: str) -> str:
    return f"tidewell-{sid}"


@contextmanager
def locked(sid: str):
    """One lock per session, held for every write to that session's graph."""
    with _lock(sid):
        yield


def _lock(sid: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(sid, threading.RLock())


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


def check_invariants(graph) -> list[str]:
    """What must be true of every sandbox. An empty list means it is sound."""
    problems = []
    labels = {r["label"]: r["c"] for r in db.read(graph, queries.COUNT_NODES_BY_LABEL)}
    if labels.get("Person") != EXPECTED_PEOPLE:
        problems.append(f"Person count is {labels.get('Person')}, expected {EXPECTED_PEOPLE}")
    if labels.get("Ticket") != EXPECTED_TICKETS:
        problems.append(f"Ticket count is {labels.get('Ticket')}, expected {EXPECTED_TICKETS}")
    bad = [r["service"] for r in db.read(graph, queries.INVARIANT_OPEN_OWNS) if r["open"] != 1]
    if bad:
        problems.append(f"services without exactly one open OWNS: {', '.join(bad)}")
    return problems


def _seed_checked(sid: str):
    """Drop the graph, seed it, and check it. One re-seed is allowed if the check fails."""
    graph = db.connect(graph_name=graph_name(sid))
    seed.reset(graph)
    problems = check_invariants(graph)
    if problems:
        print(f"sandbox {sid}: invariants failed after seeding ({'; '.join(problems)}); re-seeding", file=sys.stderr)
        seed.reset(graph)
        problems = check_invariants(graph)
        if problems:
            raise RuntimeError(f"sandbox {sid} is not sound after re-seeding: {'; '.join(problems)}")
    return graph


def _retry_once(fn):
    """Run an idempotent step again after one dropped connection."""
    try:
        return fn()
    except db.CONNECTION_ERRORS:
        db.reset_client()
        return fn()


def _register(sid: str, now: float) -> None:
    db.write(_control(), queries.SANDBOX_CREATE, {"sid": sid, "graph": graph_name(sid), "now": now})


def reap(now: float | None = None) -> int:
    """Delete idle sandboxes, then the least recently used ones beyond CAP. Returns how many went."""
    now = time.time() if now is None else now
    ctrl = _control()
    stale = _read(ctrl, queries.SANDBOX_STALE, {"cutoff": now - IDLE_S})
    live = _read(ctrl, queries.SANDBOX_LIVE_OLDEST_FIRST)
    stale_ids = {r["sid"] for r in stale}
    live = [r for r in live if r["sid"] not in stale_ids]
    overflow = max(0, len(live) - CAP)
    doomed = stale + live[:overflow]
    for row in doomed:
        # A sandbox that is in use is not idle: skip it rather than wait, so two reaps cannot deadlock.
        lock = _lock(row["sid"])
        if not lock.acquire(blocking=False):
            continue
        try:
            db.connect(graph_name=row["graph"]).delete()
            db.write(ctrl, queries.SANDBOX_DELETE, {"sid": row["sid"]})
        finally:
            lock.release()
    return len(doomed)


def _reap_if_due(now: float) -> None:
    global _last_reap
    if now - _last_reap >= REAP_EVERY_S:
        _last_reap = now
        reap(now)


def ensure(sid: str):
    """Return this session's graph. A new session is seeded once, checked, and only then registered."""
    with locked(sid):
        now = time.time()
        rows = _read(_control(), queries.SANDBOX_LOOKUP, {"sid": sid})
        if not rows:
            _reap_if_due(now)
            _retry_once(lambda: _seed_checked(sid))
            _retry_once(lambda: _register(sid, now))
            return db.connect(graph_name=graph_name(sid))
        if now - (rows[0]["seen"] or 0) >= TOUCH_EVERY_S:
            db.write(_control(), queries.SANDBOX_TOUCH, {"sid": sid, "now": now})
        return db.connect(graph_name=graph_name(sid))


def reset(sid: str):
    """Re-seed this session's own graph. Uses the same lock as creation, so the two cannot overlap."""
    with locked(sid):
        now = time.time()
        graph = _retry_once(lambda: _seed_checked(sid))
        if not _read(_control(), queries.SANDBOX_LOOKUP, {"sid": sid}):
            _retry_once(lambda: _register(sid, now))
        return graph


def verify(sid: str, graph) -> bool:
    """Check after a handover. If the sandbox is unsound, re-seed it, log it, and return False."""
    with locked(sid):
        problems = check_invariants(graph)
        if not problems:
            return True
        print(f"sandbox {sid}: invariants failed after a handover ({'; '.join(problems)}); re-seeding", file=sys.stderr)
        _seed_checked(sid)
        return False


def purge_all() -> int:
    """Startup clean-up: delete every tidewell-* sandbox graph and the registry. Returns how many went."""
    client = db.client()
    doomed = [n for n in client.list_graphs() if n.startswith("tidewell-") or n == CONTROL]
    for name in doomed:
        client.select_graph(name).delete()
    return len(doomed)
