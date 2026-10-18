"""FastAPI app: the API for PRD §6.4. The page in web/ is added in Phase 7.

Error shape everywhere: {"error": {"code": str, "message": str, "details"?: any}}.
"""
import hmac
import os
from pathlib import Path

import redis
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
import html

from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import agent, baseline, config, db, events, llm, paths, queries, seed
from app.models import AskRequest, BaselineRequest, EventRequest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}

app = FastAPI(title="Handover", version="0.7.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.get_app_origin()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Demo-Token"],
)
app.mount("/static", StaticFiles(directory=WEB), name="static")

UNREACHABLE = "FalkorDB is unreachable. Check FALKORDB_* in .env and that the instance is running."
_graph = None


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


# Database unreachable: 503 with a clear message, never a stack trace.
@app.exception_handler(redis.exceptions.ConnectionError)
@app.exception_handler(redis.exceptions.TimeoutError)
@app.exception_handler(ConnectionError)
@app.exception_handler(TimeoutError)
async def db_unreachable(request: Request, exc: Exception):
    return _error(503, "DB_UNREACHABLE", UNREACHABLE)


def get_graph():
    global _graph
    if _graph is None:
        _graph = db.connect()
    return _graph


def require_token(x_demo_token: str | None = Header(default=None)):
    expected = os.environ.get("DEMO_TOKEN")
    if not expected:
        raise StarletteHTTPException(503, "DEMO_TOKEN is not set in .env; demo endpoints are disabled.")
    if not x_demo_token or not hmac.compare_digest(x_demo_token, expected):
        raise StarletteHTTPException(401, "Missing or wrong X-Demo-Token header.")


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
        for i, c in enumerate(row):
            text = c if c else "—"
            out.append(f"<td>{html.escape(text)}</td>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


@app.get("/proof", include_in_schema=False)
def proof():
    text = (WEB / "proof.html").read_text(encoding="utf-8")
    text = text.replace("{{GOLDEN}}", html.escape(
        "12 of 12 golden questions passed in the last run, through the API with the live LLM. "
        "The keyword baseline is shown beside the graph answers, unscored."))
    text = text.replace("{{BASELINE_TABLE}}", _baseline_table())
    return HTMLResponse(text)


@app.get("/config")
def page_config(request: Request):
    """The demo token goes to the page only when the server is reached from this machine."""
    local = request.client is not None and request.client.host in LOCAL_HOSTS
    token = os.environ.get("DEMO_TOKEN") if local else None
    return {"local": local, "demo_token": token or None}


@app.post("/ask")
def ask(body: AskRequest, graph=Depends(get_graph)):
    return agent.answer(graph, body.question, default_at=body.at)


@app.post("/baseline")
def ask_baseline(body: BaselineRequest, graph=Depends(get_graph)):
    return baseline.answer(graph, body.question)


@app.post("/events", dependencies=[Depends(require_token)])
def post_event(body: EventRequest, graph=Depends(get_graph)):
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
    focus: str | None = Query(default=None, min_length=1, max_length=64),
    depth: int = Query(default=2, ge=1, le=3),
    graph=Depends(get_graph),
):
    # Same path, two uses: a browser asking for the page gets HTML; the API gets JSON.
    if focus is None and "text/html" in request.headers.get("accept", ""):
        return _graph_page()
    if focus is None:
        raise StarletteHTTPException(422, "Query parameter 'focus' is required.")
    view = paths.neighbourhood(graph, focus, depth)
    if view is None:
        raise StarletteHTTPException(404, f"No node with id '{focus}'.")
    return view


@app.get("/graph/all")
def graph_everything(graph=Depends(get_graph)):
    return paths.whole_graph(graph)


@app.post("/reset", dependencies=[Depends(require_token)])
def reset(graph=Depends(get_graph)):
    seed.reset(graph)
    return {"ok": True}


@app.get("/health")
def health():
    try:
        get_graph().ro_query("RETURN 1")
        db_status = "ok"
    except Exception:
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
