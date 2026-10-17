"""Cypher templates from PRD §6.6. The only place Cypher lives.

Templates are constants. Values go in as parameters ($name), never by
string formatting. Reads use db.read (ro_query); writes use db.write.
"""
from datetime import date

from app import db

# T0 — resolve_entity (used by every tool; not exposed to the LLM)
T0_RESOLVE_ENTITY = """
MATCH (n) WHERE (n:Person OR n:Service)
  AND (toLower(n.name) = toLower($q) OR toLower($q) IN [a IN n.aliases | toLower(a)])
RETURN n.id AS id, n.name AS name, labels(n)[0] AS kind, n.status AS status
"""

# Suggestions for unknown names (resolve.py ranks them in Python)
ALL_ENTITIES = """
MATCH (n) WHERE (n:Person OR n:Service)
RETURN n.id AS id, n.name AS name, labels(n)[0] AS kind, n.aliases AS aliases
"""

# T1 — who_owns(service, at)
T1_WHO_OWNS = """
MATCH (p:Person)-[o:OWNS]->(s:Service {id:$service})
WHERE o.valid_from <= $at AND (o.valid_to IS NULL OR o.valid_to > $at)
OPTIONAL MATCH (m:Message {id:o.source})
RETURN p, o, s, m
"""

# T2 — who_knows(service)
T2_WHO_KNOWS = """
MATCH (p:Person {status:'active'})-[w:WORKED_ON]->(s:Service {id:$service})
OPTIONAL MATCH (p)-[:AUTHORED]->(m:Message)-[:ABOUT]->(s)
RETURN p.name AS person, w.last AS last_worked, count(m) AS messages, collect(m.id) AS sources
ORDER BY messages DESC, last_worked DESC LIMIT 5
"""

# T3 — what_changed(since)
T3_WHAT_CHANGED = """
MATCH (a)-[r]->(b)
WHERE type(r) IN ['OWNS','MEMBER_OF','ASSIGNED_TO']
  AND (r.valid_from >= $since OR (r.valid_to IS NOT NULL AND r.valid_to >= $since))
RETURN a.name AS from, type(r) AS rel, b.name AS to,
       r.valid_from AS opened, r.valid_to AS closed, r.source AS source
ORDER BY coalesce(r.valid_to, r.valid_from) DESC
"""

# T4 — blast_radius(person) (multi-hop)
T4_BLAST_RADIUS = """
MATCH (p:Person {id:$person})-[o:OWNS]->(s:Service) WHERE o.valid_to IS NULL
OPTIONAL MATCH (up:Service)-[:DEPENDS_ON*1..3]->(s)
OPTIONAL MATCH (t:Ticket {status:'open'})-[:FOR]->(s)
RETURN s.name AS owned, collect(DISTINCT up.name) AS dependents, collect(DISTINCT t.name) AS open_tickets
"""

# T5 — apply_handover(event) (write; one request)
T5_APPLY_HANDOVER = """
// 1. record the event as provenance
MERGE (e:Message {id:$event_id})
  ON CREATE SET e.ts = $effective, e.channel = '#handover', e.text = $text
// 2. close old ownership, open new (idempotent: skip if already closed by this event)
WITH e
MATCH (from:Person {id:$from})-[o:OWNS]->(s:Service)
WHERE s.id IN $services AND o.valid_to IS NULL
MATCH (to:Person {id:$to})
SET o.valid_to = $effective, o.closed_by = $event_id
CREATE (to)-[:OWNS {valid_from:$effective, source:$event_id}]->(s)
RETURN s.name AS service
"""

# T5 departure step (run after T5 when event type is 'departure')
T5_DEPARTURE = """
MATCH (p:Person {id:$from}) SET p.status = 'left', p.left_on = $effective
WITH p MATCH (p)-[m:MEMBER_OF]->() WHERE m.valid_to IS NULL SET m.valid_to = $effective
"""

# T6 — reassign_tickets(service) (the agent's action)
T6_REASSIGN_TICKETS = """
MATCH (t:Ticket {status:'open'})-[:FOR]->(s:Service {id:$service})
MATCH (t)-[a:ASSIGNED_TO]->(old:Person {status:'left'}) WHERE a.valid_to IS NULL
MATCH (new:Person)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
SET a.valid_to = $today
CREATE (t)-[:ASSIGNED_TO {valid_from:$today, reason:'owner_left', source:$event_id}]->(new)
RETURN t.name AS ticket, old.name AS from, new.name AS to
"""

# B1 — baseline retrieval (keyword RAG)
B1_KEYWORD_SEARCH = """
CALL db.idx.fulltext.queryNodes('Message', $q) YIELD node, score
RETURN node.id AS id, node.text AS text, score
ORDER BY score DESC LIMIT 3
"""

# Invariant check (test and load --check): open OWNS edges per service
INVARIANT_OPEN_OWNS = """
MATCH (s:Service)
OPTIONAL MATCH (:Person)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
RETURN s.id AS service, count(o) AS open
ORDER BY service
"""


def resolve_entity(graph, q: str) -> list[dict]:
    return db.read(graph, T0_RESOLVE_ENTITY, {"q": q})


def all_entities(graph) -> list[dict]:
    return db.read(graph, ALL_ENTITIES)


def who_owns(graph, service: str, at: str | None = None) -> list[dict]:
    rows = db.read(graph, T1_WHO_OWNS, {"service": service, "at": at or date.today().isoformat()})
    out = []
    for r in rows:
        out.append({
            "person": r["p"]["name"],
            "person_id": r["p"]["id"],
            "service": r["s"]["name"],
            "valid_from": r["o"]["valid_from"],
            "valid_to": r["o"].get("valid_to"),
            "source": r["o"].get("source"),
        })
    return out


def who_knows(graph, service: str) -> list[dict]:
    return db.read(graph, T2_WHO_KNOWS, {"service": service})


def what_changed(graph, since: str) -> list[dict]:
    return db.read(graph, T3_WHAT_CHANGED, {"since": since})


def blast_radius(graph, person: str) -> list[dict]:
    return db.read(graph, T4_BLAST_RADIUS, {"person": person})


def open_owns_counts(graph) -> list[dict]:
    return db.read(graph, INVARIANT_OPEN_OWNS)
