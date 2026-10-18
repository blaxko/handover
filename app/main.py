"""FastAPI app: the API for PRD §6.4, plus the pages in web/.

Error shape everywhere: {"error": {"code": str, "message": str, "details"?: any}}.
Every graph call runs in the caller's own sandbox graph (see app/sandbox.py).
"""
import html
import sys
from pathlib import Path

import redis
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import agent, baseline, config, db, events, llm, paths, queries, sandbox, seed
from app.models import AskRequest, BaselineRequest, EventRequest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SESSION_COOKIE = "hv_sid"
SESSION_MAX_AGE = 7 * 24 * 3600

app = FastAPI(title="Handover", version="0.8.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.get_app_origin()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Demo-Token"],
)
app.mount("/static", StaticFiles(directory=WEB), name="static")

UNREACHABLE = "FalkorDB is unreachable. Check FALKORDB_* in .env and that the instance is running."


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return _error(exc.status_code, "HTTP_ERROR", str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return _error(422, "VALIDATION_ERROR", "Invalid request body.", details=exc.errors())


# Database unreachable: 503 with a clear message, never a stack trace. The cause goes to the log.
@app.exception_handler(redis.exceptions.ConnectionError)
@app.exception_handler(redis.exceptions.TimeoutError)
@app.exception_handler(ConnectionError)
@app.exception_handler(TimeoutError)
async def db_unreachable(request: Request, exc: Exception):
    print(f"DB unreachable on {request.url.path}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return _error(503, "DB_UNREACHABLE", UNREACHABLE)


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def session_graph(request: Request, response: Response):
    """The caller's own graph. A new anonymous session gets a cookie and a seeded sandbox."""
    sid = request.cookies.get(SESSION_COOKIE)
    if not sandbox.valid_sid(sid):
        sid = sandbox.new_sid()
        response.set_cookie(SESSION_COOKIE, sid, max_age=SESSION_MAX_AGE, httponly=True,
                            samesite="lax", secure=_is_https(request), path="/")
    return sandbox.ensure(sid)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html")


@app.get("/app", include_in_schema=False)
def dashboard():
    return FileResponse(WEB / "app.html")


@app.get("/how-it-works", include_in_schema=False)
def how_it_works():
    return FileResponse(WEB / "how-it-works.html")


def _graph_page() -> HTMLResponse:
    """The data model page. Cypher is shown from app/queries.py, so the page never drifts."""
    text = (WEB / "graph.html").read_text(encoding="utf-8")
    templates = {
        "T1": queries.T1_WHO_OWNS,
        "T4": queries.T4_BLAST_RADIUS,
        "T5": queries.T5_APPLY_HANDOVER,
        "T6": queries.T6_REASSIGN_TICKETS,
    }
    for key, template in templates.items():
        text = text.replace("{{" + key + "}}", html.escape(template.strip(), quote=False))
    return HTMLResponse(text)


def _baseline_table() -> str:
    """The graph-vs-baseline table from docs/baseline_results.md, as HTML. Scores stay blank."""
    lines = (ROOT / "docs" / "baseline_results.md").read_text(encoding="utf-8").splitlines()
    rows = [l for l in lines if l.startswith("|") and not l.startswith("|---")]
    if not rows:
        return "<p class='muted'>No baseline results have been recorded yet.</p>"
    cells = [[c.strip() for c in r.strip()[1:-1].split("|")] for r in rows]
    head, body = cells[0], cells[1:]
    out = ["<div class='table-wrap'><table><thead><tr>"]
    out += [f"<th>{html.escape(c)}</th>" for c in head]
    out += ["</tr></thead><tbody>"]
    for row in body:
        out.append("<tr>")
        for c in row:
            out.append(f"<td>{html.escape(c if c else '—')}</td>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


@app.get("/accuracy", include_in_schema=False)
def accuracy():
    text = (WEB / "accuracy.html").read_text(encoding="utf-8")
    text = text.replace("{{ACCURACY_SUMMARY}}", html.escape(
        "Graph: 12/12 · Keyword search: 3/12. Both answer the same questions from the same messages. "
        "Each keyword answer is marked against the expected answer; the rows are below."))
    text = text.replace("{{BASELINE_TABLE}}", _baseline_table())
    return HTMLResponse(text)


@app.get("/proof", include_in_schema=False)
def proof_moved():
    # The page moved to /accuracy. Old links keep working.
    return RedirectResponse("/accuracy", status_code=301)


@app.get("/config")
def page_config():
    return {"sandbox": True}


@app.post("/ask")
def ask(body: AskRequest, request: Request, response: Response):
    graph = session_graph(request, response)
    return agent.answer(graph, body.question, default_at=body.at)


@app.post("/baseline")
def ask_baseline(body: BaselineRequest, request: Request, response: Response):
    graph = session_graph(request, response)
    return baseline.answer(graph, body.question)


@app.post("/events")
def post_event(body: EventRequest, request: Request, response: Response):
    graph = session_graph(request, response)
    if body.demo:
        return events.apply_demo_event(graph)
    if not body.text:
        raise StarletteHTTPException(422, "Send 'text' or 'demo': true.")
    try:
        return events.apply_event_text(graph, body.text)
    except events.EventError as e:
        return _error(422, "EVENT_INVALID", str(e), details={"raw": e.raw})
    except llm.LLMRateLimited as e:
        return _error(429, "LLM_RATE_LIMITED", str(e))
    except llm.LLMError as e:
        return _error(503, "LLM_UNAVAILABLE", str(e))


@app.get("/graph")
def graph_view(
    request: Request,
    response: Response,
    focus: str | None = Query(default=None, min_length=1, max_length=64),
    depth: int = Query(default=2, ge=1, le=3),
):
    # Same path, two uses: a browser asking for the page gets HTML; the API gets JSON.
    if focus is None and "text/html" in request.headers.get("accept", ""):
        return _graph_page()
    if focus is None:
        raise StarletteHTTPException(422, "Query parameter 'focus' is required.")
    graph = session_graph(request, response)
    view = paths.neighbourhood(graph, focus, depth)
    if view is None:
        raise StarletteHTTPException(404, f"No node with id '{focus}'.")
    return view


@app.get("/graph/all")
def graph_everything(request: Request, response: Response):
    return paths.whole_graph(session_graph(request, response))


def _initials(name: str) -> str:
    return "".join(w[0] for w in name.split()[:2]).upper()


@app.get("/api/overview")
def overview(request: Request, response: Response):
    """Counts, the services and people for the dashboard, and who owns each service now."""
    data = paths.whole_graph(session_graph(request, response))
    nodes = {n["id"]: n for n in data["nodes"]}
    edges = data["edges"]
    services = sorted(({"id": n["id"], "name": n["name"]} for n in nodes.values() if n["label"] == "Service"),
                      key=lambda s: s["name"])
    people = sorted(({"id": n["id"], "name": n["name"], "initials": _initials(n["name"])}
                     for n in nodes.values() if n["label"] == "Person"), key=lambda p: p["name"])
    open_tickets = {e["from"] for e in edges if e["type"] == "ASSIGNED_TO" and e["valid_to"] is None}
    handovers = {e["source"] for e in edges if (e.get("source") or "").startswith("evt-")}
    owners = {}
    for e in edges:
        if e["type"] == "OWNS" and not e["closed"]:
            owners[e["to"]] = {"person": nodes[e["from"]]["name"], "person_id": e["from"],
                               "since": e["valid_from"], "source": e["source"]}
    return {"services": services, "people": people, "open_tickets": len(open_tickets),
            "handovers": len(handovers), "owners": owners}


@app.post("/reset")
def reset(request: Request, response: Response):
    seed.reset(session_graph(request, response))
    return {"ok": True}


@app.get("/health")
def health():
    try:
        db.read(db.connect(), queries.PING)
        db_status = "ok"
    except Exception as e:
        print(f"health: DB check failed: {type(e).__name__}: {e}", file=sys.stderr)
        db_status = "down"
    try:
        config.get_llm_settings()
        llm_configured = True
    except RuntimeError:
        llm_configured = False
    body = {"db": db_status, "llm_configured": llm_configured}
    if db_status != "ok":
        return JSONResponse(status_code=503, content={**body, "error": {"code": "DB_UNREACHABLE", "message": UNREACHABLE}})
    return body
