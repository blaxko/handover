import threading

import redis
from falkordb import FalkorDB

from app.config import Settings, get_settings

# One client per process, shared by every request. Creating a client costs about two seconds
# against FalkorDB Cloud, so a client per request made every page slow. If a call fails on the
# connection, the client is dropped and the call is retried once on a fresh one.
_lock = threading.Lock()
_client = None

CONNECTION_ERRORS = (
    redis.exceptions.ConnectionError,
    redis.exceptions.TimeoutError,
    ConnectionError,
    TimeoutError,
)


def _get_client(s: Settings):
    global _client
    with _lock:
        if _client is None:
            _client = FalkorDB(
                host=s.host,
                port=s.port,
                username=s.username,
                password=s.password,
                ssl=s.ssl,
            )
        return _client


def client(settings: Settings | None = None):
    """The shared client, for the few calls that need the server rather than one graph."""
    return _get_client(settings or get_settings())


def reset_client() -> None:
    global _client
    with _lock:
        _client = None


def connect(settings: Settings | None = None, graph_name: str | None = None):
    s = settings or get_settings()
    return _get_client(s).select_graph(graph_name or s.graph_name)


def _plain(value):
    # Nodes and edges come back as objects; the app works with dicts.
    if hasattr(value, "properties"):
        return dict(value.properties)
    return value


def to_dicts(result) -> list[dict]:
    names = [col[1] if isinstance(col, (list, tuple)) else col for col in result.header]
    return [
        {name: _plain(val) for name, val in zip(names, row)}
        for row in result.result_set
    ]


def _run(graph, call):
    """Run a query. On a connection error, reconnect once and try again."""
    try:
        return call(graph)
    except CONNECTION_ERRORS:
        reset_client()
        return call(connect(graph_name=graph.name))


def read(graph, cypher: str, params: dict | None = None) -> list[dict]:
    """Read path. Uses ro_query so writes cannot run from here."""
    return to_dicts(_run(graph, lambda g: g.ro_query(cypher, params or {})))


def write(graph, cypher: str, params: dict | None = None) -> list[dict]:
    """Write path. Never retried: a half-applied write must not run twice. A failed connection is dropped,
    so the next request reconnects."""
    try:
        return to_dicts(graph.query(cypher, params or {}))
    except CONNECTION_ERRORS:
        reset_client()
        raise
