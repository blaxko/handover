# CLAUDE.md — Handover

**Handover is a company-brain agent that knows who owns what *now*. It answers from a temporal FalkorDB graph, shows the path and source behind every answer, and reassigns work when people leave.**

Full spec: `PRD.md`. If this file and the PRD disagree, the PRD wins. Flag the conflict instead of guessing.

---

## What we're building and why it qualifies

- **Event:** Graph Hacks: Context for AI Agents (WeMakeDevs × FalkorDB).
- **Deadline:** Sun Oct 18, 7:29 PM Lagos (11:59 PM IST). Feature freeze 3:00 PM Lagos. Submit by 6:30 PM Lagos.
- **Tracks:** Company Brain (primary), Agent Memory and Coordination (secondary).
- **Builder:** Solo: Oladipupo Ayoola.
- **Budget:** $0. Free tiers only (FalkorDB Cloud free, Groq free, Gemini free as fallback).

**Core loop:**
1. A question goes to an LLM, which picks one of five fixed Cypher tools.
2. FalkorDB returns the rows, the path, and the source messages.
3. The LLM phrases the answer and cites sources.
4. A pasted change event ("Tunde left, Ada takes payments-api") closes old edges and opens new ones. **Nothing is deleted.**
5. Open tickets move from the person who left to the new owner.
6. A plain-RAG panel answers the same question from keyword-matched text (FalkorDB full-text index), for comparison.

**Why it qualifies (rules 2 and 3):** FalkorDB is the only store. Ownership history, multi-hop blast radius, provenance, and ticket reassignment all exist only as graph traversals and graph writes. Remove FalkorDB and the product does nothing. Data is synthetic (rule 6). AI-assistant use is disclosed in the README (rule 11).

---

## Tech stack

Pin exact versions in `requirements.txt` after the first install (`pip freeze`). These are the minimums.

| Layer | Tech | Version |
|---|---|---|
| Graph DB | FalkorDB Cloud (free tier) | current cloud release |
| DB client | `falkordb` (falkordb-py) | ≥ 1.0 |
| Runtime | Python | 3.11 |
| API | `fastapi` + `uvicorn[standard]` | fastapi ≥ 0.115, uvicorn ≥ 0.30 |
| Models | `pydantic` | v2 |
| LLM client | `openai` SDK pointed at an OpenAI-compatible endpoint | ≥ 1.40 |
| LLM provider (primary) | **Groq** free tier, `LLM_BASE_URL=https://api.groq.com/openai/v1`, a model that supports tool calling | free, no card |
| LLM provider (fallback) | **Gemini** free tier (Flash), via Gemini's OpenAI-compatible endpoint (verify the base URL in Google's docs) | free |
| Baseline retrieval | FalkorDB **full-text index** ("keyword RAG"). Vectors only as a stretch. | — |
| Config | `python-dotenv` | latest |
| Tests | `pytest`, `httpx`, `pyyaml` | latest |
| Frontend | one static HTML page + `vis-network` from cdnjs | no build step |
| Hosting | Railway if its free trial covers it; otherwise local-only with full setup steps in the README (allowed by the rules) | — |
| Dev machine | Windows, PowerShell, Claude Code desktop app | **no Docker** |

---

## Repo structure

```
handover/
├── CLAUDE.md              # this file
├── PRD.md                 # full spec, source of truth
├── README.md              # judges read this: setup, data model, Cypher, tracks, AI disclosure
├── requirements.txt
├── .env.example           # FALKORDB_HOST, FALKORDB_PORT, FALKORDB_USERNAME, FALKORDB_PASSWORD,
│                          # GRAPH_NAME, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, DEMO_TOKEN
├── railway.json           # start command
├── db/
│   ├── seed.cypher        # synthetic company "Tidewell" (PRD §6.5); hand-written, do not regenerate
│   ├── indexes.cypher     # range and full-text indexes (vector only if stretch)
│   └── load.py            # drops the graph, runs seed + indexes statement by statement
├── app/
│   ├── main.py            # FastAPI app, routes, serves web/
│   ├── config.py          # env loading
│   ├── db.py              # FalkorDB connection; query() vs ro_query() helpers
│   ├── queries.py         # Cypher templates T0–T6 + B1 as constants (PRD §6.6). ONLY place Cypher lives
│   ├── resolve.py         # alias resolution, ambiguity, suggestions
│   ├── tools.py           # tool schemas for the LLM + dispatch to queries.py
│   ├── llm.py             # ONE OpenAI-compatible client; provider set only by LLM_BASE_URL/LLM_API_KEY/LLM_MODEL
│   ├── prompts/           # router.txt, extract_event.txt, answer.txt, baseline.txt (pre-written)
│   ├── agent.py           # LLM router and answer phrasing
│   ├── events.py          # event text → validated JSON → apply_handover + reassign_tickets
│   ├── baseline.py        # keyword RAG: top-3 Messages from full-text index → LLM answer
│   ├── paths.py           # turns query results into {nodes, edges} for the UI
│   └── models.py          # pydantic request/response models
├── web/
│   ├── index.html         # ask box, answer card, graph view, Cypher toggle, baseline panel, event panel
│   ├── app.js
│   └── style.css
├── tests/
│   ├── golden.yaml        # the 12 golden questions + expected answers (PRD §8.0)
│   ├── test_golden.py     # runs the golden set against the API
│   ├── test_queries.py    # each template against the seed
│   └── test_events.py     # handover, idempotency, rejects
└── docs/
    └── architecture.md    # diagram for the README
```

---

## Build phases

Mark each box when its tests pass. Work strictly in order.

- [ ] **1. Graph.** `db/seed.cypher` and `db/indexes.cypher` load cleanly via `db/load.py`. Counts match PRD §8.1 F1. One open `OWNS` per service.
- [ ] **2. Queries.** `app/queries.py` holds T0–T6 and B1. `tests/test_queries.py` passes on the seed: golden Qs 1–5 at the data level.
- [ ] **3. Resolution.** `resolve.py`: "TB", "@tunde", and "T. Bakare" resolve to `p-tunde`. "Ada" returns 2 candidates. Unknown names return suggestions.
- [ ] **4. Events.** `events.py`: extraction → schema validation → T5 → T6. Idempotent. All rejects in PRD §7 covered. `tests/test_events.py` passes.
- [ ] **5. Agent.** `agent.py` and `tools.py`: router picks the right tool for all 12 golden questions. Answers cite Message ids. No LLM-written Cypher.
- [ ] **6. API.** `/ask`, `/events`, `/baseline`, `/graph`, `/reset`, `/health`. `tests/test_golden.py` passes 12/12.
- [ ] **7. UI.** `web/` covers every panel in the repo tree. Path highlight matches the returned nodes and edges. Readable at phone width.
- [ ] **8. Deploy.** If Railway's free trial covers it: live, golden set passes against the live URL, `/reset` works there. If not: README local setup is complete and tested from a fresh clone.
- [ ] **9. Stretch (only if 1–8 are green, before 3:00 PM Sun).** First S2 (manual tool form as LLM fallback), then S1 (PageRank in `who_knows`).
- [ ] **10. Ship.** README final: setup, data model, Cypher queries, tracks, baseline score, AI disclosure, synthetic-data note. Video recorded. Submitted.

**Skills to use per phase.** Load the named skill before starting the phase.

| Phase | Skill |
|---|---|
| 1–6 | `superpowers` (plan first, then test-driven: write the test, see it fail, implement) |
| 6 (API shape and review) | `agent-skills` |
| 7 (UI) | `frontend-design`; `impeccable` to polish |
| 10 (README diagram) | `archify` |

---

## Commands (Windows PowerShell)

```powershell
# --- setup ---
git clone https://github.com/blaxko/handover.git; cd handover
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # once, if venv activation is blocked
.\.venv\Scripts\Activate.ps1
pip install fastapi "uvicorn[standard]" falkordb openai pydantic python-dotenv pytest httpx pyyaml
pip freeze > requirements.txt
Copy-Item .env.example .env    # then fill in values

# --- database ---
python db/load.py --reset      # drop graph, load seed + indexes
python db/load.py --check      # print node and edge counts

# --- run ---
uvicorn app.main:app --reload --port 8000
# open http://localhost:8000

# --- test ---
pytest -q
pytest tests/test_golden.py -q
pytest tests/test_golden.py -q --base-url https://<railway-url>   # against live

# --- manual API checks ---
Invoke-RestMethod -Method Post -Uri http://localhost:8000/ask -ContentType 'application/json' -Body '{"question":"Who owns payments-api?"}'
Invoke-RestMethod -Method Post -Uri http://localhost:8000/events -Headers @{ 'X-Demo-Token' = $env:DEMO_TOKEN } -ContentType 'application/json' -Body '{"text":"Tunde Bakare''s last day was Friday. Ada Okafor takes over payments-api and ledger, effective 2026-10-17."}'
Invoke-RestMethod -Method Post -Uri http://localhost:8000/reset -Headers @{ 'X-Demo-Token' = $env:DEMO_TOKEN }

# --- switch LLM provider (edit .env only, no code change) ---
# Groq:   LLM_BASE_URL=https://api.groq.com/openai/v1   LLM_API_KEY=gsk_...   LLM_MODEL=<tool-calling model from Groq console>
# Gemini: LLM_BASE_URL=<Gemini OpenAI-compatible URL>    LLM_API_KEY=AIza...   LLM_MODEL=<Flash model id>

# --- deploy (Railway, optional — only if free trial covers it) ---
npm i -g @railway/cli
railway login
railway init
railway variables set FALKORDB_HOST=... FALKORDB_PORT=... FALKORDB_USERNAME=... FALKORDB_PASSWORD=... GRAPH_NAME=tidewell LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=... DEMO_TOKEN=...
railway up
# start command (railway.json): uvicorn app.main:app --host 0.0.0.0 --port $PORT

# --- git ---
git add -A; git commit -m "feat: <what>"; git push
```

---

## Demo plan (what the judge sees, in order)

Target ≤ 90 seconds in the video. The full video is ≤ 3 min.

1. **Ask "Who owns payments-api?"** → Tunde Bakare. The graph highlights Tunde → OWNS → payments-api. Source message m01 is shown. The baseline panel also says Tunde.
2. **Ask "What breaks if TB leaves?"** → "TB" resolves to Tunde. Owned: payments-api, ledger. Dependents: mobile-app, notifications. Open tickets t-101, t-102. Multi-hop path drawn.
3. **Paste the change event.** Two old edges turn grey (closed, not deleted). Two new edges appear for Ada Okafor. Tickets t-101 and t-102 move to Ada.
4. **Ask "Who owns payments-api?" again** → Ada Okafor, with the event as the source.
5. **Ask "Who owned payments-api on 2026-09-01?"** → Tunde. History survives.
6. **Ask "Who owned ledger in 2025-06?"** → Graph says Segun Bello. The baseline guesses wrong, shown side by side.
7. **Click "show Cypher"** on one answer, then cut to FalkorDB Browser showing closed and open `OWNS` edges.
8. **End card:** "The graph is the product. Remove FalkorDB and none of this works."

---

## 60-second pitch

> Ask any company "who owns payments?" and you'll get an answer from a wiki someone wrote a year ago. People leave, the docs don't notice, and AI assistants make it worse: vector search finds the most *similar* text, which is usually the oldest claim.
>
> Handover is a company brain built on FalkorDB. Ownership isn't a sentence in a document. It's an edge in a graph, with a start date, an end date, and the message that proves it.
>
> Ask who owns a service, and you see the answer *and* the path behind it. Tell it "Tunde left, Ada's taking over," and it closes Tunde's edges, opens Ada's, and moves his open tickets to her. Nothing is deleted, so you can still ask who owned it last month.
>
> Ask what breaks if someone leaves, and it walks the dependency graph to show every service and ticket at risk.
>
> Side by side, plain RAG gives you the stale answer. Handover gives you the current one, with receipts.

---

## Known errors and bad patterns

- **One statement per query.** falkordb-py runs one Cypher statement per call. `load.py` must strip `//` comment lines, split on `;`, and run each non-empty statement.
- **Null properties.** Setting a property to `null` means it isn't stored. Test for open edges with `r.valid_to IS NULL`, never `= null`. Confirm in phase 1 that `CREATE ... {valid_to:null}` loads without error. If it doesn't, omit the key.
- **Dates are `YYYY-MM-DD` strings.** They compare correctly as strings. Never mix in datetimes or epoch numbers.
- **Read vs write.** Use `graph.ro_query()` for T0–T4 and B1, and `graph.query()` for T5, T6, and the seed. Never run writes from a read path.
- **Always parameterise.** `graph.query(TEMPLATE, {"service": sid})`. Never f-string user text into Cypher.
- **Resolve before querying.** Tools take ids (`p-tunde`, `s-payments`), never raw names. Resolution happens in `resolve.py` first.
- **Ambiguity is a response, not an error.** Return `{clarify:[...]}`. Never pick the first match silently.
- **Check the invariant.** At most one open `OWNS` per service. Tests must assert it after the seed and after every event.
- **Verify FalkorDB-specific syntax.** Full-text (`db.idx.fulltext.*`), vector (`CREATE VECTOR INDEX`, `db.idx.vector.queryNodes`, `vecf32`), and algorithm syntax must be checked against the FalkorDB docs before use. The baseline uses full-text and is labelled "keyword RAG".
- **Free-tier rate limits.** Groq and Gemini free tiers return HTTP 429 when limits are hit. Catch it, show "rate limited, retry in a few seconds", and never retry in a tight loop. Tests that call the LLM must run sequentially, not in parallel.
- **Tool-calling support varies by model.** Pick a Groq model listed as supporting tool use. If the router returns malformed tool calls, try another model before changing code.
- **Provider lock-in.** No provider-specific SDK (`groq`, `google-genai`, `anthropic`). Everything goes through `app/llm.py` using the `openai` client and `LLM_BASE_URL`.
- **Railway.** Bind to `0.0.0.0` and `$PORT`. FalkorDB Cloud credentials go in env vars only.
- **Windows.** Use PowerShell syntax (`;`, not `&&`, in older shells). Escape apostrophes in JSON bodies by doubling them (`''`). Use path separators that work on both Windows and Linux (`pathlib`).
- **LLM timeout.** Set 8 s on every LLM call and surface a clear error. Never hang the UI.

---

## Things NOT to do

- **Don't let the LLM write Cypher.** It only picks a tool and fills ids or dates. All Cypher lives in `app/queries.py`.
- **Don't delete edges or nodes** outside `/reset` and `load.py --reset`. History is the product.
- **Don't rewrite or regenerate `db/seed.cypher`.** It's hand-written so we can explain it (rules 12 and 13). Propose changes; don't make them silently.
- **Don't rig the baseline.** It sees the same messages and answers only from its top-3 snippets.
- **Don't add a second database.** No Postgres, Redis, vector DB, or SQLite. FalkorDB only.
- **Don't add auth, user accounts, Slack/Gmail/Jira connectors, or a build-step frontend.** All out of scope (PRD §9).
- **Don't use real people's data or real company names.** Synthetic only.
- **Don't add features after 3:00 PM Sunday.** Bug fixes and demo polish only.
- **Don't add `Co-Authored-By` or any AI attribution lines to commits.** AI use is disclosed in the README instead.
- **Don't commit `.env`** or any key.
- **Don't use Docker** or ask the user to install it.
- **Don't add anything that costs money.** No paid APIs, paid tiers, or services that need a credit card.
- **Don't mark a phase done** until its tests pass and you've shown the output.
