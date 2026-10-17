"""FastAPI app: the API for PRD §6.4. The page in web/ is added in Phase 7.

Error shape everywhere: {"error": {"code": str, "message": str, "details"?: any}}.
"""
import hmac
import os

import redis
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import agent, baseline, config, db, events, llm, paths, seed
from app.models import AskRequest, BaselineRequest, EventRequest

app = FastAPI(title="Handover", version="0.6.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.get_app_origin()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Demo-Token"],
)

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
    focus: str = Query(min_length=1, max_length=64),
    depth: int = Query(default=2, ge=1, le=3),
    graph=Depends(get_graph),
):
    view = paths.neighbourhood(graph, focus, depth)
    if view is None:
        raise StarletteHTTPException(404, f"No node with id '{focus}'.")
    return view


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
