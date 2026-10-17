# Handover

## Overview

Handover is a company-brain agent that knows who owns what *now*. It answers from a temporal FalkorDB graph, shows the path and source message behind every answer, and reassigns open tickets when people leave. Nothing is deleted: closed ownership stays queryable as history.

## Tracks: Company Brain; Agent Memory and Coordination

- **Company Brain** (primary)
- **Agent Memory and Coordination** (secondary)

## Live demo

_Not yet deployed. Replace with the live URL if Railway is used, or keep the local setup below._

## Setup (local)

_To be written in Phase 8._

## Graph data model

**Nodes**

| Label | Properties |
|---|---|
| `Person` | `id, name, aliases[], status ('active'/'left'), left_on?` |
| `Team` | `id, name` |
| `Service` | `id, name, aliases[]` |
| `Ticket` | `id, name, status ('open'/'closed')` |
| `Message` | `id, ts, channel, text` |
| `Decision` | `id, name, ts` (stretch S4) |

**Edges.** Dates are ISO strings `YYYY-MM-DD`, which compare correctly as strings.

| Edge | Properties |
|---|---|
| `(Person)-[:OWNS]->(Service)` | `valid_from, valid_to?, source, closed_by?` |
| `(Person)-[:MEMBER_OF]->(Team)` | `valid_from, valid_to?` |
| `(Person)-[:WORKED_ON]->(Service)` | `last` |
| `(Service)-[:DEPENDS_ON]->(Service)` | — |
| `(Ticket)-[:FOR]->(Service)` | — |
| `(Ticket)-[:ASSIGNED_TO]->(Person)` | `valid_from, valid_to?, reason?, source?` |
| `(Person)-[:AUTHORED]->(Message)` | — |
| `(Message)-[:ABOUT]->(Service)` | — |
| `(Message)-[:MENTIONS]->(Person)` | — |

**Invariant:** at most one `OWNS` edge with no `valid_to` per Service.

## Cypher queries

Parameters are prefixed with `$`. `$at` defaults to today.

**T0 — `resolve_entity`** (used by every tool; not exposed to the LLM)
```cypher
MATCH (n) WHERE (n:Person OR n:Service)
  AND (toLower(n.name) = toLower($q) OR toLower($q) IN [a IN n.aliases | toLower(a)])
RETURN n.id AS id, n.name AS name, labels(n)[0] AS kind, n.status AS status
```
- 0 rows means unknown.
- More than 1 Person row means ambiguous: return a clarification.

**T1 — `who_owns(service, at)`**
```cypher
MATCH (p:Person)-[o:OWNS]->(s:Service {id:$service})
WHERE o.valid_from <= $at AND (o.valid_to IS NULL OR o.valid_to > $at)
OPTIONAL MATCH (m:Message {id:o.source})
RETURN p, o, s, m
```

**T2 — `who_knows(service)`**
```cypher
MATCH (p:Person {status:'active'})-[w:WORKED_ON]->(s:Service {id:$service})
OPTIONAL MATCH (p)-[:AUTHORED]->(m:Message)-[:ABOUT]->(s)
RETURN p.name AS person, w.last AS last_worked, count(m) AS messages, collect(m.id) AS sources
ORDER BY messages DESC, last_worked DESC LIMIT 5
```
Stretch S1: blend in PageRank from FalkorDB's algorithms on the `WORKED_ON` subgraph.

**T3 — `what_changed(since)`**
```cypher
MATCH (a)-[r]->(b)
WHERE type(r) IN ['OWNS','MEMBER_OF','ASSIGNED_TO']
  AND (r.valid_from >= $since OR (r.valid_to IS NOT NULL AND r.valid_to >= $since))
RETURN a.name AS from, type(r) AS rel, b.name AS to,
       r.valid_from AS opened, r.valid_to AS closed, r.source AS source
ORDER BY coalesce(r.valid_to, r.valid_from) DESC
```

**T4 — `blast_radius(person)`** (multi-hop)
```cypher
MATCH (p:Person {id:$person})-[o:OWNS]->(s:Service) WHERE o.valid_to IS NULL
OPTIONAL MATCH (up:Service)-[:DEPENDS_ON*1..3]->(s)
OPTIONAL MATCH (t:Ticket {status:'open'})-[:FOR]->(s)
RETURN s.name AS owned, collect(DISTINCT up.name) AS dependents, collect(DISTINCT t.name) AS open_tickets
```

**T5 — `apply_handover(event)`** (write; run as one request)
```cypher
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
```
If the event type is `departure`, also run:
```cypher
MATCH (p:Person {id:$from}) SET p.status = 'left', p.left_on = $effective
WITH p MATCH (p)-[m:MEMBER_OF]->() WHERE m.valid_to IS NULL SET m.valid_to = $effective
```

**T6 — `reassign_tickets(service)`** (the agent's action)
```cypher
MATCH (t:Ticket {status:'open'})-[:FOR]->(s:Service {id:$service})
MATCH (t)-[a:ASSIGNED_TO]->(old:Person {status:'left'}) WHERE a.valid_to IS NULL
MATCH (new:Person)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
SET a.valid_to = $today
CREATE (t)-[:ASSIGNED_TO {valid_from:$today, reason:'owner_left', source:$event_id}]->(new)
RETURN t.name AS ticket, old.name AS from, new.name AS to
```

**B1 — baseline retrieval (keyword RAG)**
```cypher
CALL db.idx.fulltext.queryNodes('Message', $q) YIELD node, score
RETURN node.id AS id, node.text AS text, score
ORDER BY score DESC LIMIT 3
```
Verify whether `score` is yielded in your FalkorDB version; if not, drop it and keep `LIMIT 3`.

## Architecture

_Diagram to come (`docs/`). ASCII form in PRD §6.1:_

```
Seed (seed.cypher) ─┐
                    ├─► Ingest (alias resolve, close/open edges) ─► FalkorDB temporal graph
Change event ───────┘                                                   ▲          │
                                                                        │          ▼
Question ─► LLM router ─► 5 Cypher tools ─────────────────────────────────┘   Answer + path + sources
                                     └─► reassign_tickets (write) ─────► graph
Question ─► Baseline: full-text top-3 Messages ─► LLM ─► baseline answer
```

## Baseline comparison

_Keyword RAG (matching text) score on the golden set: to be measured in Phase 6._

## AI assistance disclosure

Built with Claude Code (Anthropic) for scaffolding the API and UI. Graph model, seed data, and Cypher queries were written and verified by the author.

## Synthetic data statement

All data is synthetic. The company "Tidewell", its people, services, tickets, and messages are fictional. No real employees, companies, or Slack/Gmail/Jira data are used.
