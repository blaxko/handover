# Handover

Handover is a company brain on a graph that always knows who owns what now: it shows the path that proves each answer, and when someone leaves it hands their work to the new owner without deleting the history.

## Live demo

LIVE-URL-HERE

Each visitor gets a private sandbox. The first load takes about 10 seconds while your workspace is set up.

## Tracks: Company Brain; Agent Memory and Coordination

- **Company Brain** (primary)
- **Agent Memory and Coordination** (secondary)
- Each visitor gets an isolated graph (FalkorDB multigraph): `tidewell-<session id>`, seeded on the first visit and deleted after 2 hours idle.

## How it works

1. **Ask.** A question goes to an LLM, which picks one of five fixed read tools. If the model fails, a keyword router picks the tool. The tool resolves names and runs a fixed Cypher template on FalkorDB. The model never writes Cypher.
2. **Answer with receipts.** The answer comes back with the graph path it used and the source messages it cites.
3. **Hand over.** A pasted change event (“Tunde left, Ada takes over”) is turned into one fixed JSON shape. Old ownership closes, new ownership opens, and open tickets move. Nothing is deleted.
4. **Compare.** The keyword-search baseline answers the same question from the top 3 matching messages.

## Architecture

```
Visitor (browser, anonymous session cookie hv_sid)
   │
   ▼
FastAPI (app/main.py) ── each session gets its own graph, tidewell-<sid> (app/sandbox.py)
   │
   ├─ /ask ────────► LLM picks a tool (keyword router if it fails) ─► 5 read tools (app/tools.py)
   │                                                                   └─► fixed Cypher (app/queries.py) ─► FalkorDB
   ├─ /events ─────► LLM extracts one fixed JSON shape ─► validation ─► apply_handover + reassign_tickets ─► FalkorDB
   ├─ /baseline ───► full-text candidates ─► keyword re-rank ─► LLM phrases the top 3 ─► answer
   └─ /graph, /api/overview, /graph/all ─► FalkorDB ─► JSON for the page
```

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

Every query the product runs, copied from `app/queries.py` (the only place Cypher lives). Parameters are prefixed with `$`. `$at` defaults to today, and in T6 `$today` is the event's `effective` date.

**`T0_RESOLVE_ENTITY`** — Resolve a name or alias to one Person or Service. Zero rows means unknown; more than one Person means ambiguous.
```cypher
MATCH (n) WHERE (n:Person OR n:Service)
  AND (toLower(n.name) = toLower($q) OR toLower($q) IN [a IN n.aliases | toLower(a)])
RETURN n.id AS id, n.name AS name, labels(n)[0] AS kind, n.status AS status
```

**`ALL_ENTITIES`** — Every person and service, used for suggestions and for the name-to-id map in the path view.
```cypher
MATCH (n) WHERE (n:Person OR n:Service)
RETURN n.id AS id, n.name AS name, labels(n)[0] AS kind, n.aliases AS aliases
```

**`ENTITY_BY_ID`** — Resolve an exact id such as `p-ada`, used by the clarification chips.
```cypher
MATCH (n) WHERE (n:Person OR n:Service) AND n.id = $q
RETURN n.id AS id, n.name AS name, labels(n)[0] AS kind, n.status AS status
```

**`T1_WHO_OWNS`** — Who owns a service on a date. The only edge that answers ownership is an OWNS edge open on that date.
```cypher
MATCH (p:Person)-[o:OWNS]->(s:Service {id:$service})
WHERE o.valid_from <= $at AND (o.valid_to IS NULL OR o.valid_to > $at)
OPTIONAL MATCH (m:Message {id:o.source})
RETURN p, o, s, m
```

**`T2_WHO_KNOWS`** — Who has worked on a service, most active first. The current owner is removed in code, not here.
```cypher
MATCH (p:Person {status:'active'})-[w:WORKED_ON]->(s:Service {id:$service})
OPTIONAL MATCH (p)-[:AUTHORED]->(m:Message)-[:ABOUT]->(s)
RETURN p.name AS person, w.last AS last_worked, count(m) AS messages, collect(m.id) AS sources
ORDER BY messages DESC, last_worked DESC LIMIT 5
```

**`T3_WHAT_CHANGED`** — Ownership, membership and assignment changes since a date.
```cypher
MATCH (a)-[r]->(b)
WHERE type(r) IN ['OWNS','MEMBER_OF','ASSIGNED_TO']
  AND (r.valid_from >= $since OR (r.valid_to IS NOT NULL AND r.valid_to >= $since))
RETURN a.name AS from, type(r) AS rel, b.name AS to,
       r.valid_from AS opened, r.valid_to AS closed, r.source AS source
ORDER BY coalesce(r.valid_to, r.valid_from) DESC
```

**`T4_BLAST_RADIUS`** — What a person owns now, the services that depend on it (up to three hops), and their open tickets.
```cypher
MATCH (p:Person {id:$person})-[o:OWNS]->(s:Service) WHERE o.valid_to IS NULL
OPTIONAL MATCH (up:Service)-[:DEPENDS_ON*1..3]->(s)
OPTIONAL MATCH (t:Ticket {status:'open'})-[:FOR]->(s)
RETURN s.name AS owned, collect(DISTINCT up.name) AS dependents, collect(DISTINCT t.name) AS open_tickets
```

**`T5_APPLY_HANDOVER`** — Records the event as a message, closes the old OWNS edges and opens the new ones in one request. Nothing is deleted.
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

**`T5_DEPARTURE`** — Marks a person who left and closes their team memberships. Runs after T5 for a departure.
```cypher
MATCH (p:Person {id:$from}) SET p.status = 'left', p.left_on = $effective
WITH p MATCH (p)-[m:MEMBER_OF]->() WHERE m.valid_to IS NULL SET m.valid_to = $effective
```

**`T6_REASSIGN_TICKETS`** — Moves open tickets from someone who left to the current owner. The new assignment starts on the event's effective date.
```cypher
MATCH (t:Ticket {status:'open'})-[:FOR]->(s:Service {id:$service})
MATCH (t)-[a:ASSIGNED_TO]->(old:Person {status:'left'}) WHERE a.valid_to IS NULL
MATCH (new:Person)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
SET a.valid_to = $today
CREATE (t)-[:ASSIGNED_TO {valid_from:$today, reason:'owner_left', source:$event_id}]->(new)
RETURN t.id AS ticket_id, t.name AS ticket, old.name AS from, new.name AS to
```

**`T7_TICKET_ASSIGNEE`** — The current assignee of one ticket.
```cypher
MATCH (t:Ticket {id:$ticket})-[a:ASSIGNED_TO]->(p:Person) WHERE a.valid_to IS NULL
RETURN t.id AS ticket_id, t.name AS ticket, p.id AS person_id, p.name AS person, a.valid_from AS since, a.source AS source
```

**`B1_KEYWORD_SEARCH`** — The baseline's keyword search: the top 3 messages from the full-text index.
```cypher
CALL db.idx.fulltext.queryNodes('Message', $q) YIELD node, score
RETURN node.id AS id, node.text AS text, score
ORDER BY score DESC LIMIT 3
```

**`EVENT_EXISTS`** — Has this event already been recorded? A repeat then changes nothing.
```cypher
MATCH (e:Message {id:$event_id}) RETURN e.id AS id
```

**`OPEN_SERVICES_OF`** — The services a person owns now. Used to check that the 'from' person owns each service in an event.
```cypher
MATCH (p:Person {id:$person})-[o:OWNS]->(s:Service) WHERE o.valid_to IS NULL
RETURN s.id AS service, s.name AS name
```

**`B1_CANDIDATES`** — The baseline's candidate pool (25 messages), which is re-ranked by keyword overlap before the top 3 are kept.
```cypher
CALL db.idx.fulltext.queryNodes('Message', $q) YIELD node, score
RETURN node.id AS id, node.text AS text, score
ORDER BY score DESC LIMIT 25
```

**`GRAPH_ALL`** — The whole graph, closed edges included, for the full-graph view and the dashboard counts.
```cypher
MATCH (a)-[r]->(b)
RETURN DISTINCT a.id AS src, coalesce(a.name, a.id) AS src_name, labels(a)[0] AS src_label,
       b.id AS dst, coalesce(b.name, b.id) AS dst_name, labels(b)[0] AS dst_label,
       type(r) AS type, r.valid_from AS valid_from, r.valid_to AS valid_to, r.source AS source
```

**`MESSAGES_BY_ID`** — The text of the messages a response cites.
```cypher
MATCH (m:Message) WHERE m.id IN $ids
RETURN m.id AS id, m.text AS text, m.ts AS ts, m.channel AS channel
ORDER BY m.ts
```

**`DEPENDENCY_HOPS`** — The real DEPENDS_ON hops into an owned service, so the graph draws stored edges only.
```cypher
MATCH p=(up:Service)-[:DEPENDS_ON*1..3]->(s:Service {id:$service})
UNWIND relationships(p) AS r
RETURN DISTINCT startNode(r).id AS src, startNode(r).name AS src_name,
       endNode(r).id AS dst, endNode(r).name AS dst_name, type(r) AS type
```

**`FOCUS_NODE`** — One node, to return 404 for an unknown focus.
```cypher
MATCH (f {id:$focus}) RETURN f.id AS id, labels(f)[0] AS label, coalesce(f.name, f.id) AS name
```

**`GRAPH_NEIGHBOURHOOD`** — The graph around a focus node, both directions, up to three hops. Closed edges are included and marked.
```cypher
MATCH p=(f {id:$focus})-[*1..3]-(n)
WHERE length(p) <= $depth
UNWIND relationships(p) AS r
RETURN DISTINCT startNode(r).id AS src, coalesce(startNode(r).name, startNode(r).id) AS src_name,
       labels(startNode(r))[0] AS src_label,
       endNode(r).id AS dst, coalesce(endNode(r).name, endNode(r).id) AS dst_name,
       labels(endNode(r))[0] AS dst_label,
       type(r) AS type, r.valid_from AS valid_from, r.valid_to AS valid_to
```

**`OPEN_TICKETS`** — Open tickets, with ids, for the path view.
```cypher
MATCH (t:Ticket {status:'open'}) RETURN t.id AS id, t.name AS name
```

**`INVARIANT_OPEN_OWNS`** — Open OWNS edges per service. Each service must show exactly one.
```cypher
MATCH (s:Service)
OPTIONAL MATCH (:Person)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
RETURN s.id AS service, count(o) AS open
ORDER BY service
```

**`SANDBOX_LOOKUP`** — Does this visitor's sandbox exist, and when was it last used?
```cypher
MATCH (s:Sandbox {sid:$sid}) RETURN s.last_seen AS seen
```

**`SANDBOX_CREATE`** — Registers a new sandbox in the control graph.
```cypher
MERGE (s:Sandbox {sid:$sid}) SET s.graph=$graph, s.last_seen=$now
```

**`SANDBOX_TOUCH`** — Records that a sandbox was used just now.
```cypher
MATCH (s:Sandbox {sid:$sid}) SET s.last_seen=$now
```

**`SANDBOX_STALE`** — Sandboxes idle for longer than two hours. They are deleted.
```cypher
MATCH (s:Sandbox) WHERE s.last_seen < $cutoff RETURN s.sid AS sid, s.graph AS graph
```

**`SANDBOX_LIVE_OLDEST_FIRST`** — Live sandboxes, least recently used first. The oldest go when the cap of 50 is exceeded.
```cypher
MATCH (s:Sandbox) RETURN s.sid AS sid, s.graph AS graph, s.last_seen AS seen ORDER BY s.last_seen ASC
```

**`SANDBOX_DELETE`** — Removes a sandbox from the control graph after its graph is deleted.
```cypher
MATCH (s:Sandbox {sid:$sid}) DELETE s
```

**`PING`** — Database health check.
```cypher
RETURN 1
```

**`COUNT_NODES_BY_LABEL`** — Node counts for `db/load.py --check`.
```cypher
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS c ORDER BY label
```

**`COUNT_EDGES_BY_TYPE`** — Edge counts for `db/load.py --check`.
```cypher
MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS c ORDER BY type
```

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
- `DEMO_TOKEN`: optional. Nothing needs it: each visitor has a private sandbox.
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

The tests reset the demo graph and leave it seeded. The golden tests call the real LLM, and the suite takes about 7 minutes.

**Troubleshooting**
- `py` not found on Windows: install Python 3.11 from python.org, or run `winget install -e --id Python.Python.3.11`.
- `503 ... FalkorDB is unreachable`: check the `FALKORDB_*` values. If your provider needs TLS, set `FALKORDB_SSL=true`.
- `429` or "rate limited": wait a few seconds and retry. The page says so.

## Baseline comparison

Baseline = FalkorDB full-text index + simple keyword re-rank, top 3 messages, no hand-picked answers.

| | Score |
|---|---|
| Graph | **12/12** |
| Keyword search | **3/12** |

Keyword search gets the owner right for payments-api now (question 1), for who owned payments-api on 2026-09-01 (question 8), and for "who owns billing" (an unknown service, question 12). It misses the ledger owner, the June 2025 ledger owner, the change event, the ticket owner, the clarification and the multi-hop question. The row-by-row verdicts, with reasons, are in [docs/baseline_results.md](docs/baseline_results.md) and on the `/accuracy` page.

## AI assistance disclosure

Built with Claude Code (Anthropic) for scaffolding the API and UI. Graph model, seed data, and Cypher queries were written and verified by the author.

## Synthetic data statement

All data is synthetic. The company "Tidewell (sample workspace)", its people, services, tickets, and messages are fictional. No real employees, companies, or Slack/Gmail/Jira data are used.

## Credits

- Hero photo by Alexander Mass on Pexels: https://www.pexels.com/@rebornfilmes/
