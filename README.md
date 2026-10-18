# Handover

## Overview

Handover is a company-brain agent that knows who owns what *now*. It answers from a temporal FalkorDB graph, shows the path and source message behind every answer, and reassigns open tickets when people leave. Nothing is deleted: closed ownership stays queryable as history.

## Tracks: Company Brain; Agent Memory and Coordination

- **Company Brain** (primary)
- **Agent Memory and Coordination** (secondary)

## Live demo

_Not yet deployed. Replace with the live URL if Railway is used, or keep the local setup below._

## Setup (local)

Runs on Windows (PowerShell) and Linux (bash). About 5 minutes, plus the first package install.

**You need:** Python 3.11, git, a free FalkorDB Cloud instance (host, port, username, password), and a free Groq API key with a tool-calling model.

Commands are shown for Windows first, then Linux. The app runs the venv's Python directly, so you never activate the venv and never change PowerShell's execution policy.

**1. Clone the repo**

Windows and Linux:
```bash
git clone https://github.com/blaxko/handover.git
cd handover
```

**2. Create the venv and install packages**

Windows:
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Linux:
```bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

**3. Create `.env` and fill it in**

Windows:
```powershell
Copy-Item .env.example .env
```

Linux:
```bash
cp .env.example .env
```

Then edit `.env`:
- `FALKORDB_HOST`, `FALKORDB_PORT`, `FALKORDB_USERNAME`, `FALKORDB_PASSWORD`: from the FalkorDB Cloud dashboard.
- `FALKORDB_SSL`: leave `false` unless your provider requires TLS.
- `LLM_BASE_URL`: `https://api.groq.com/openai/v1`.
- `LLM_API_KEY`: your Groq key (starts with `gsk_`).
- `LLM_MODEL`: a tool-calling model ID from the Groq console.
- `DEMO_TOKEN`: a random string. Windows: `[guid]::NewGuid().ToString("N")`. Linux: `python3 -c "import uuid; print(uuid.uuid4().hex)"`.
- `APP_ORIGIN`: leave empty for local use.

`.env` holds secrets. It is git-ignored. Never commit it.

**4. Load the demo graph**

Windows:
```powershell
.\.venv\Scripts\python.exe db\load.py --reset
.\.venv\Scripts\python.exe db\load.py --check
```

Linux:
```bash
./.venv/bin/python db/load.py --reset
./.venv/bin/python db/load.py --check
```

`--check` should print Message 15, Person 9, Service 6, Team 5, Ticket 4, and `invariant ... OK`.

**5. Start the app**

Windows:
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Linux:
```bash
./.venv/bin/python -m uvicorn app.main:app --port 8000
```

Open http://localhost:8000 for the demo page. Check http://localhost:8000/health. It should return `{"db":"ok","llm_configured":true}`. Stop the server with Ctrl+C.

**6. Run the tests (optional, about 5 minutes)**

Windows: `.\.venv\Scripts\python.exe -m pytest -q`
Linux: `./.venv/bin/python -m pytest -q`

The tests reset the demo graph and leave it seeded. The golden tests call the real LLM, so they take about 2 minutes.

**Troubleshooting**
- `py` not found on Windows: install Python 3.11 from python.org, or run `winget install -e --id Python.Python.3.11`.
- `503 ... FalkorDB is unreachable`: check the `FALKORDB_*` values. If your provider needs TLS, set `FALKORDB_SSL=true`.
- `429` or "rate limited": wait a few seconds and retry. The page says so.
- Apply or Reset asks for a token: paste your `DEMO_TOKEN`. The page only receives it when served from this machine.

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

Parameters are prefixed with `$`. `$at` defaults to today. In T6, `$today` is the event's `effective` date, not the wall-clock date.

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
RETURN t.id AS ticket_id, t.name AS ticket, old.name AS from, new.name AS to
```

**T7 — `ticket_assignee(ticket)`** (read-only; used by the agent)
```cypher
MATCH (t:Ticket {id:$ticket})-[a:ASSIGNED_TO]->(p:Person) WHERE a.valid_to IS NULL
RETURN t.id AS ticket_id, t.name AS ticket, p.id AS person_id, p.name AS person, a.valid_from AS since, a.source AS source
```

**Support query — dependency paths for `blast_radius`** (`app/queries.py`, `DEPENDENCY_HOPS`; run once per owned service)
```cypher
MATCH p=(up:Service)-[:DEPENDS_ON*1..3]->(s:Service {id:$service})
UNWIND relationships(p) AS r
RETURN DISTINCT startNode(r).id AS src, startNode(r).name AS src_name,
       endNode(r).id AS dst, endNode(r).name AS dst_name, type(r) AS type
```
Each row is one stored `DEPENDS_ON` edge, so the graph view draws real hops, not shortcuts.

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

Baseline = FalkorDB full-text index + simple keyword re-rank, top 3 messages, no hand-picked answers.

The baseline sees the same messages as the graph, including the event message after a change event. It answers only from its top 3 snippets. Per-question answers are in [docs/baseline_results.md](docs/baseline_results.md). Scores are recorded there by hand.

## AI assistance disclosure

Built with Claude Code (Anthropic) for scaffolding the API and UI. Graph model, seed data, and Cypher queries were written and verified by the author.

## Synthetic data statement

All data is synthetic. The company "Tidewell", its people, services, tickets, and messages are fictional. No real employees, companies, or Slack/Gmail/Jira data are used.
