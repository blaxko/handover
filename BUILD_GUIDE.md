# BUILD_GUIDE.md — Handover

**You, alone, in 3 days: Fri night → Sat → Sun.**
**Deadline: Sun Oct 18, 7:29 PM Lagos. Your target: submitted by 6:30 PM.**

How to read this guide:
- Every step tells you **what to do**, the **exact prompt** (if Claude Code is used), what **success** looks like, and what to do **if it fails**.
- 🔴 = **critical path.** If this step isn't done, nothing after it works. Don't skip, don't stretch.
- 🛟 = a **fallback** for a hard step. Use it the moment the main plan eats more than the time limit shown.
- Claude Code is nearly out of quota until **Sun 4:00 AM**. Friday and Saturday are **by hand**. Sunday is the Claude Code build.
- **You make every commit yourself.** Every prompt tells Claude Code *not* to commit. That keeps `Co-Authored-By` lines out of your history.

Commit command, used after every phase (PowerShell, in the repo folder):
```powershell
git add -A; git status
git commit -m "<message from the step>"
git push
git log -1 --format=%B      # check: no "Co-Authored-By" line
```
Before every commit, check that `.env` is NOT in the `git status` list.

---

## DAY 0 — Friday night (about 2–3 hours, no Claude Code)

Goal: the database exists, the fake company is loaded, and you've seen the key queries work with your own eyes.

### 1. 🔴 Get your free Groq key
- **Do:** Go to https://console.groq.com, sign up (no card). Create an API key called `handover-dev`. Copy it into a private note. In the models list, pick one that says it supports **tool use** and note its exact ID.
- **Prompt:** none (by hand).
- **Success:** you have a key starting with `gsk_` and a model ID written down.
- **If it fails:** 🛟 Use Gemini instead. Get a free key at https://aistudio.google.com/apikey, pick a **Flash** model, and look up Gemini's OpenAI-compatible base URL in Google's docs. Everything else in this guide stays the same.

### 2. 🔴 Create your free FalkorDB Cloud database
- **Do:** Go to https://app.falkordb.cloud/signup. Create a **free** instance. Copy **host, port, username, password** into your private note. Open **FalkorDB Browser** from the dashboard.
- **Prompt:** none.
- **Success:** in Browser, `RETURN 1` shows `1`.
- **If it fails:** try another region, or wait 10 minutes and retry. If it still fails, post in the FalkorDB Discord (it's open for the whole hackathon) and move on to step 5 while you wait.

### 3. 🔴 Load the fake company (seed)
- **Do:** Open `handover-prd.md` §6.5. In Browser, create or select a graph named `tidewell`. Paste and run the seed **one block at a time** (each block ends with `;`). Skip the comment lines that start with `//`.
- **Prompt:** none.
- **Success:** run this and match the numbers exactly:
  ```cypher
  MATCH (n) RETURN labels(n)[0] AS label, count(*) ORDER BY label
  ```
  Message 15 · Person 9 · Service 6 · Team 5 · Ticket 4.
- **If it fails:**
  - **Error about `null`** in the `MEMBER_OF` or `OWNS` blocks: 🛟 split that block in two. One `UNWIND` for rows that have an end date, one for rows that don't, and leave `valid_to` out completely for the open ones.
  - **Error about `MERGE ... SET`** or list properties: run the people one at a time to find the bad row.
  - **Wrong counts:** run `MATCH (n) DETACH DELETE n` and start over.
  - Write down every fix. You'll copy it into `seed.cypher` in step 6.

### 4. 🔴 Test the key queries by hand
- **Do:** In Browser, run these from `handover-prd.md` §6.6, typing the values directly where you see `$`:
  - **T1** with `s-payments` and `'2026-10-16'` → should return **Tunde**
  - **T1** with `s-ledger` and `'2025-06-01'` → should return **Segun**
  - **T4** with `p-tunde` → should return payments-api and ledger, dependents mobile-app and notifications, and tickets t-101 and t-102
  - **T0** with `'TB'` → Tunde. With `'Ada'` → **two** people.
- **Prompt:** none.
- **Success:** all four give exactly those answers.
- **If it fails:** fix the query, not the data. Common fixes: change `IS NULL` checks, or remove `labels(n)[0]` if it errors. Write the fixed query down. Tomorrow you'll be glad you did, because judges will ask you to explain these.

### 5. 🔴 Create the GitHub repo and set your Git identity
- **Do:**
  1. On GitHub, create **public** repo `blaxko/handover` (empty, no README).
  2. GitHub → Settings → Emails → turn on "Keep my email address private". Copy your `@users.noreply.github.com` address.
  3. In PowerShell:
     ```powershell
     git config --global user.name "Oladipupo Ayoola"
     git config --global user.email "<your-noreply-address>"
     git config --global init.defaultBranch main
     git config --global core.autocrlf true
     git clone https://github.com/blaxko/handover.git
     cd handover
     ```
- **Prompt:** none.
- **Success:** `git config --global --list` shows your name and noreply email. The `handover` folder exists.
- **If it fails:** if `git` isn't found, install it with `winget install -e --id Git.Git`, then reopen PowerShell.

**Stop for the night.** Set an alarm for **Sun 3:45 AM** now, before you forget.

---

## DAY 1 — Saturday (about 4–5 hours, no Claude Code)

Goal: the repo has every file Claude Code needs, your prompts are proven in Groq's playground, and Python is installed.

### 6. 🔴 Lay out the repo and add your files
- **Do:** In the `handover` folder, create these folders: `db`, `app`, `app/prompts`, `web`, `tests`, `docs`. Then:
  - Copy `CLAUDE.md` into the root.
  - Copy `handover-prd.md` into the root and **rename it `PRD.md`**.
  - Create `db/seed.cypher` from PRD §6.5, **including your fixes from step 3**.
  - Create `db/indexes.cypher` from PRD §6.5's index block.
  - Create `app/prompts/router.txt`, `extract_event.txt`, `answer.txt`, and `baseline.txt` from `PHASE_0_CHECKLIST.md` §6.2.
  - Create `.gitignore`:
    ```powershell
    @"
    .venv/
    __pycache__/
    *.pyc
    .env
    .pytest_cache/
    "@ | Out-File -Encoding utf8 .gitignore
    ```
  - Create `.env.example` with these lines, no values: `FALKORDB_HOST=`, `FALKORDB_PORT=`, `FALKORDB_USERNAME=`, `FALKORDB_PASSWORD=`, `GRAPH_NAME=tidewell`, `LLM_BASE_URL=`, `LLM_API_KEY=`, `LLM_MODEL=`, `DEMO_TOKEN=`
  - Copy `.env.example` to `.env` and fill in the real values. For `DEMO_TOKEN`, run `[guid]::NewGuid().ToString("N")`.
- **Prompt:** none.
- **Success:** `git status` lists your new files and **does not** list `.env`.
- **If it fails:** if `.env` shows up in `git status`, your `.gitignore` is wrong or in the wrong folder. It must be in the repo root.

### 7. 🔴 Write the golden test file
- **Do:** Create `tests/golden.yaml` with exactly this content:
  ```yaml
  # Run in order. "event" step applies the demo change event.
  - id: 1
    question: "Who owns payments-api?"
    expect_tool: who_owns
    expect_contains: ["Tunde Bakare"]
    expect_source: m01
  - id: 2
    question: "Who owns ledger?"
    expect_tool: who_owns
    expect_contains: ["Tunde"]
    expect_source: m02
  - id: 3
    question: "Who owned ledger in 2025-06?"
    expect_tool: who_owns
    expect_contains: ["Segun Bello"]
    expect_source: m00
  - id: 4
    question: "What breaks if TB leaves?"
    expect_tool: blast_radius
    expect_contains: ["payments-api", "ledger", "mobile-app", "notifications", "Refund webhook returns 500", "Reconciliation drift in ledger"]
  - id: 5
    question: "Who knows payments-api besides the owner?"
    expect_tool: who_knows
    expect_first: "Ada Okafor"
  - id: 6
    event: "Tunde Bakare's last day was Friday. Ada Okafor takes over payments-api and ledger, effective 2026-10-17."
    expect_closed: 2
    expect_opened: 2
    expect_tickets_moved: ["t-101", "t-102"]
  - id: 7
    question: "Who owns payments-api?"
    expect_tool: who_owns
    expect_contains: ["Ada Okafor"]
    expect_source_is_event: true
  - id: 8
    question: "Who owned payments-api on 2026-09-01?"
    expect_tool: who_owns
    expect_contains: ["Tunde Bakare"]
  - id: 9
    question: "What changed since 2026-10-15?"
    expect_tool: what_changed
    expect_contains: ["Tunde Bakare", "Ada Okafor", "OWNS", "ASSIGNED_TO"]
  - id: 10
    question: "Who is t-101 assigned to?"
    expect_contains: ["Ada Okafor"]
  - id: 11
    question: "What does Ada work on?"
    expect_clarify: ["Ada Okafor", "Ada Nwankwo"]
  - id: 12
    question: "Who owns billing?"
    expect_unknown: true
  ```
- **Prompt:** none.
- **Success:** the file is saved. Question 10 has no tool listed on purpose; Sunday's build decides how it's answered.
- **If it fails:** nothing to fail here. Just double-check the indentation is 2 spaces.

### 8. Prove your prompts in Groq's playground (free)
- **Do:** In the Groq console playground, choose your model.
  1. Paste `router.txt` as the system prompt. Add the four tools (`who_owns`, `who_knows`, `what_changed`, `blast_radius`) in the tools area. Ask all the golden questions except 6. Note which tool it picks each time.
  2. New chat. Paste `extract_event.txt` as the system prompt and the step-6 event as the message. Check the JSON.
- **Prompt:** none.
- **Success:** the right tool for questions 1–5, 7–9, and 11–12, and clean JSON for the event:
  `{"type":"departure","from":"Tunde Bakare","to":"Ada Okafor","services":["payments-api","ledger"],"effective":"2026-10-17"}`
- **If it fails:**
  - Wrong tool picked: add one example line per tool to `router.txt` (for example `"what breaks if X leaves" → blast_radius`) and retry.
  - Still flaky after 30 minutes: try a different tool-use model from Groq's list.
  - 🛟 If no model is reliable: Sunday's build adds a **keyword router** (simple text rules that pick the tool) as a backup. It's already in the Phase 5 prompt.

### 9. Write the README skeleton
- **Do:** Create `README.md` with these headings and short notes under each:
  `Overview` · `Tracks: Company Brain; Agent Memory and Coordination` · `Live demo` · `Setup (local)` · `Graph data model` (paste PRD §6.3) · `Cypher queries` (paste PRD §6.6) · `Architecture` · `Baseline comparison` · `AI assistance disclosure` · `Synthetic data statement`
  For the AI disclosure, write: "Built with Claude Code (Anthropic) for scaffolding the API and UI. Graph model, seed data, and Cypher queries were written and verified by the author."
- **Prompt:** none.
- **Success:** the README has the model and queries in it. That's two required submission items already done.

### 10. 🔴 Install Python and the packages
- **Do:**
  ```powershell
  py -3.11 --version        # if missing: winget install -e --id Python.Python.3.11, then reopen PowerShell
  py -3.11 -m venv .venv
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  .\.venv\Scripts\Activate.ps1
  pip install fastapi "uvicorn[standard]" falkordb openai pydantic python-dotenv pytest httpx pyyaml
  pip freeze > requirements.txt
  ```
  Then test your Groq key:
  ```powershell
  $env:LLM_BASE_URL="https://api.groq.com/openai/v1"; $env:LLM_API_KEY="gsk_..."; $env:LLM_MODEL="<model id>"
  python -c "import os; from openai import OpenAI; c=OpenAI(base_url=os.environ['LLM_BASE_URL'],api_key=os.environ['LLM_API_KEY']); print(c.chat.completions.create(model=os.environ['LLM_MODEL'],max_tokens=10,messages=[{'role':'user','content':'say ok'}]).choices[0].message.content)"
  ```
- **Prompt:** none.
- **Success:** your prompt shows `(.venv)` and the test prints a short reply.
- **If it fails:**
  - "running scripts is disabled": run the `Set-ExecutionPolicy` line again, then reopen PowerShell.
  - 401: wrong key. 404: wrong model ID.
  - Low disk space: delete `.venv`, free up space, and run it again. The packages need roughly 300–500 MB.

### 11. Commit Day 1
- **Do:** run the commit command with message `chore: PRD, CLAUDE.md, seed, prompts, golden set, README skeleton`.
- **Success:** the files are on GitHub, `.env` isn't, and there's no `Co-Authored-By` line.

**Sleep early.** Alarm: **Sun 3:45 AM.**

---

## DAY 2 — Sunday (the build, with Claude Code)

Open Claude Code's **Code** tab on the `handover` folder at **4:00 AM**.
Each phase has a **time limit**. If you hit it, use the 🛟 fallback and move on. A finished small thing beats a perfect half-thing.

### 12. 🔴 Phase 1–2: Load the graph from code and wire the queries (4:00–5:15)
- **Do:** paste the prompt and approve its plan.
- **Prompt:**
  > Read CLAUDE.md and PRD.md fully before anything else. Use the superpowers skill: write a short plan for Phase 1 and Phase 2 only, show it to me, and wait for my OK. Then build test-first: `db/load.py` (with `--reset` and `--check`, strips `//` comments, splits on `;`, runs one statement per call) and `app/config.py`, `app/db.py`, `app/queries.py` holding T0–T6 and B1 exactly as in PRD §6.6. Write `tests/test_queries.py` covering golden questions 1–5 at the data level and the one-open-OWNS-per-service invariant. Do NOT change `db/seed.cypher`; if it needs a change, tell me why and wait. Do NOT commit. Show me the test output at the end.
- **Success:** `python db/load.py --reset` then `python db/load.py --check` shows the right counts, and `pytest tests/test_queries.py -q` passes.
- **If it fails:**
  - A FalkorDB syntax error: tell Claude Code "use the fix I made in Browser" and paste your fixed query.
  - Can't connect: check `.env` values against the Cloud dashboard. Some cloud instances need TLS; ask Claude Code to check the falkordb-py docs for the right connection options.
  - 🛟 **Over time limit:** load the seed by pasting it into Browser like you did Friday, and only build `queries.py` and its tests.
- **Commit:** `feat: graph loader and Cypher templates (phase 1-2)`

### 13. Phase 3: Name resolution (5:15–5:45)
- **Prompt:**
  > Use the superpowers skill. Build Phase 3 from CLAUDE.md: `app/resolve.py` using T0. Test-first: "TB", "@tunde", and "T. Bakare" resolve to p-tunde; "Ada" returns two candidates as a clarification; "billing" returns unknown plus closest suggestions by alias substring. Services resolve the same way ("payments" → s-payments). Do NOT commit. Show the test output.
- **Success:** `pytest -q` passes, including the new resolver tests.
- **If it fails:** 🛟 drop the suggestions for unknown names. Just return "unknown". That's acceptable.
- **Commit:** `feat: alias resolution (phase 3)`

### 14. 🔴 Phase 4: Change events (5:45–6:45)
- **Prompt:**
  > Use the superpowers skill. Build Phase 4 from CLAUDE.md and PRD §4.2 and §7: `app/llm.py` (one OpenAI-compatible client from LLM_BASE_URL, LLM_API_KEY, LLM_MODEL; 8-second timeout; clear error on HTTP 429), and `app/events.py` (event text → LLM with `app/prompts/extract_event.txt` → strict JSON validation with pydantic → resolve names → T5 apply_handover, plus the departure query → T6 reassign_tickets). event_id = hash of normalised text so a repeat does nothing. Cover every event row in PRD §7. Tests in `tests/test_events.py`; for unit tests, mock the LLM so tests don't spend free-tier requests. Do NOT commit. Show the test output.
- **Success:** tests pass. After applying the demo event, T1 for s-payments gives Ada Okafor, and t-101 and t-102 belong to Ada.
- **If it fails:**
  - The LLM returns bad JSON: tell Claude Code to retry once with "Return only the JSON object", then fail cleanly.
  - 🛟 **Over time limit:** add a **"demo event" button path** that skips the LLM and sends the known JSON straight to T5 and T6. The graph change is the impressive part, not the text parsing.
- **Commit:** `feat: change events and ticket reassignment (phase 4)`

### 15. 🔴 Phase 5: The agent (6:45–7:45)
- **Prompt:**
  > Use the superpowers skill. Build Phase 5 from CLAUDE.md and PRD §4.1: `app/tools.py` (OpenAI-format tool schemas for who_owns, who_knows, what_changed, blast_radius; each dispatches to resolve.py then queries.py) and `app/agent.py` (router with `app/prompts/router.txt`, then answer phrasing with `app/prompts/answer.txt`, citing message ids). Also add a deterministic keyword router as a fallback, used when the LLM fails or returns no valid tool call (for example "what breaks if" → blast_radius, "owned ... on/in <date>" → who_owns with at, "who knows" → who_knows, "what changed since" → what_changed). Add `app/paths.py` to turn results into {nodes, edges}. The LLM must never write Cypher. Do NOT commit. Show which tool each of the 12 golden questions gets.
- **Success:** the right tool for the golden questions, and every answer names its source message.
- **If it fails:**
  - Wrong tools from the LLM: tighten `router.txt` with examples.
  - 🛟 Ship with the **keyword router as the main path** and the LLM only phrasing the answer. It's still an agent choosing tools, and it's fully reliable for the demo.
- **Commit:** `feat: agent router, tools, keyword fallback (phase 5)`

### 16. 🔴 Phase 6: The API (7:45–8:45)
- **Prompt:**
  > Use the superpowers skill for the build and the agent-skills skill to check the API shape. Build Phase 6 from CLAUDE.md and PRD §6.4: FastAPI in `app/main.py` with /ask, /baseline (B1 full-text top 3 → LLM with `app/prompts/baseline.txt`), /events, /graph, /reset, /health. /events and /reset need the X-Demo-Token header. Return 503 with a clear message if FalkorDB is unreachable. Write `tests/test_golden.py` that runs `tests/golden.yaml` in order against the API (runs sequentially; reset first). Do NOT commit. Run the golden tests and show the output.
- **Success:** `uvicorn app.main:app --reload --port 8000` starts, and `pytest tests/test_golden.py -q` passes 12/12.
- **If it fails:**
  - Below 12/12: fix the failing ones in order. Questions 1, 4, 6, and 7 matter most for the demo.
  - Rate-limit errors (429) during tests: ask Claude Code to add a 2-second pause between golden questions.
  - 🛟 Question 10 ("who is t-101 assigned to") is the least important. Mark it as known-failing in the README rather than losing an hour.
- **Commit:** `feat: API and golden tests passing (phase 6)`

### 17. 🔴 Phase 7: The page (8:45–12:00)
- **Prompt:**
  > Use the frontend-design skill. Build Phase 7 from CLAUDE.md: one page in `web/` served by FastAPI, no build step, vis-network from cdnjs. Layout: ask box on top; left column has the graph answer card (answer, source messages, "show Cypher" toggle) and below it the keyword-RAG baseline card; right column is the graph view, where the returned path is highlighted, open edges are solid, and closed edges are grey and dashed with a "closed" label; bottom bar is the change-event box with a pre-filled demo event and an Apply button that shows edges closed and opened and tickets moved. Clarification answers show clickable name chips. Works at phone width. Do NOT commit. Tell me how to open it.
  
  When it works, paste a second prompt:
  > Use the impeccable skill to polish this page: clear hierarchy, readable type, consistent spacing. Don't add features.
- **Success:** at http://localhost:8000 you can run demo beats 1–6 (listed at the end of this guide) by clicking, without touching PowerShell.
- **If it fails:**
  - The graph view won't render: 🛟 show the path as text (`Tunde Bakare —OWNS→ payments-api`) and use FalkorDB Browser for the visual in the video.
  - Running out of time at 11:30: skip the polish prompt.
- **Commit:** `feat: demo page (phase 7)`

### 18. Phase 8: Deploy or document local setup (12:00–13:30)
- **Do:** try Railway first. If it asks for a card, go straight to the fallback.
  ```powershell
  winget install -e --id OpenJS.NodeJS.LTS     # if node is missing
  npm i -g @railway/cli
  railway login
  railway init
  ```
- **Prompt:**
  > Use the agent-skills skill (shipping). Prepare Phase 8 from CLAUDE.md: add `railway.json` with start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, and give me the exact `railway variables set` line using the names in `.env.example` (no values). Then finish the README "Setup (local)" section so a stranger on Windows or Linux can run it from a fresh clone. Do NOT commit.
- **Success:** the live URL loads and `pytest tests/test_golden.py -q --base-url <url>` passes. Or, if you're local-only, a fresh clone into another folder works by following the README alone.
- **If it fails:** 🛟 skip deployment. The rules accept **complete local setup instructions** instead of a live URL. Write in the README: "Live deployment not available; run locally in 5 minutes using the steps below."
- **Commit:** `chore: deployment config and local setup docs (phase 8)`

### 19. Phase 9: One stretch, only if everything above is green (13:30–15:00)
- **Do:** only if the golden tests pass and the page works. Otherwise skip to step 20.
- **Prompt:**
  > Use the superpowers skill. Build stretch S2 from PRD §3: a "manual mode" toggle on the page with a tool dropdown and parameter fields that call the same tools directly, for when the LLM is down or rate-limited. Keep all existing tests passing. Do NOT commit.
- **Success:** you can run beat 1 with the LLM key removed from `.env`.
- **If it fails:** undo it with `git checkout .` and move on. Stretch work never blocks shipping.
- **Commit:** `feat: manual mode fallback (stretch S2)`

**⏰ 3:00 PM — FEATURE FREEZE.** From here on: bug fixes, README, video. Nothing new.

### 20. 🔴 Finish the README (15:00–15:45)
- **Prompt:**
  > Use the archify skill to make a simple architecture diagram for README "Architecture" from CLAUDE.md's core loop, saved in `docs/`. Then fill every remaining README section: overview, tracks, setup, graph data model, all Cypher queries the product uses (copied from `app/queries.py`), the golden-set results for graph vs keyword baseline, the AI assistance disclosure as written, and the synthetic data statement. Don't invent results; run the golden tests to get the numbers. Do NOT commit.
- **Success:** every README section is filled, and the baseline score is a real measured number.
- **If it fails:** 🛟 skip the diagram and paste the ASCII architecture from PRD §6.1.
- **Commit:** `docs: final README`

### 21. 🔴 Record the demo video (15:45–17:00)
- **Do:**
  1. Run `/reset` (or the reset button) so the data is fresh.
  2. Close `.env`, PowerShell windows with keys, and the Groq and FalkorDB dashboards.
  3. Record with Windows Game Bar (**Win+Alt+R**) or OBS if you have it.
  4. Follow the **Demo checklist** below. Keep it under 3 minutes.
  5. Upload to YouTube as **Unlisted** and copy the link.
- **Success:** a video under 3 minutes where every demo beat is visible and readable.
- **If it fails:** a beat breaks during recording? Reset and record again. 🛟 After two failed takes, record the beats as separate clips and join them, or record FalkorDB Browser running T1, T4, and T5 directly.

### 22. 🔴 Submit (17:00–18:30)
- **Do:** follow the **Submission checklist** below and submit on the hackathon page.
- **Success:** you get a submission confirmation by 6:30 PM.
- **If it fails:** a form error or upload problem? Post in the FalkorDB Discord immediately. You still have until 7:29 PM.
- **Commit:** `chore: submission`

---

## Demo checklist (what the judge sees, in order)

Before recording:
- [ ] Data reset; golden question 1 gives Tunde
- [ ] Browser zoom at 125% so text is readable in the video
- [ ] No keys or passwords visible anywhere on screen
- [ ] FalkorDB Browser open in a second tab, on graph `tidewell`

The beats:
1. [ ] Ask **"Who owns payments-api?"** → Tunde Bakare. The path lights up. Source m01 is shown. The baseline also says Tunde.
2. [ ] Ask **"What breaks if TB leaves?"** → "TB" is understood as Tunde. Two services, two dependents, two open tickets.
3. [ ] Click **Apply** on the demo event → two edges closed (grey), two opened, tickets t-101 and t-102 move to Ada.
4. [ ] Ask **"Who owns payments-api?"** again → Ada Okafor, with the event as the source.
5. [ ] Ask **"Who owned payments-api on 2026-09-01?"** → Tunde. History is kept.
6. [ ] Ask **"Who owned ledger in 2025-06?"** → the graph says Segun Bello. Point out the baseline's answer beside it.
7. [ ] Click **show Cypher** on one answer. Switch to FalkorDB Browser and show the closed and open `OWNS` edges.
8. [ ] End card: **"The graph is the product. Remove FalkorDB and none of this works."**

---

## Submission checklist

- [ ] Repo `blaxko/handover` is **public**
- [ ] `.env` is **not** in the repo (check on GitHub)
- [ ] No commit has a `Co-Authored-By` line (`git log --format=%B | Select-String "Co-Authored"` returns nothing)
- [ ] README has: setup steps, **graph data model**, **Cypher queries**, architecture, tracks, baseline score, **AI assistance disclosure**, synthetic data statement
- [ ] Demo video link works in a private/incognito window
- [ ] Live URL works, **or** the README says local-only with full steps
- [ ] Tracks entered: **Company Brain** and **Agent Memory and Coordination**
- [ ] You've said the pitch out loud once, and you can explain T1, T4, and T5 without notes
- [ ] Submitted before **6:30 PM Lagos** (hard deadline 7:29 PM)

---

## Pitch script (60 seconds)

> Ask any company "who owns payments?" and you'll get an answer from a wiki someone wrote a year ago. People leave, the docs don't notice, and AI assistants make it worse: they find the text that *looks* most relevant, which is usually the oldest claim.
>
> Handover is a company brain built on FalkorDB. Ownership isn't a sentence in a document. It's an edge in a graph, with a start date, an end date, and the message that proves it.
>
> Ask who owns a service, and you see the answer *and* the path behind it. Tell it "Tunde left, Ada's taking over," and it closes Tunde's edges, opens Ada's, and moves his open tickets to her. Nothing is deleted, so you can still ask who owned it last month.
>
> Ask what breaks if someone leaves, and it walks the dependency graph to show every service and ticket at risk.
>
> Side by side, plain search gives you the stale answer. Handover gives you the current one, with receipts.
