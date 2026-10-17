from falkordb import FalkorDB

from app.config import Settings, get_settings


def connect(settings: Settings | None = None):
    s = settings or get_settings()
    client = FalkorDB(
        host=s.host,
        port=s.port,
        username=s.username,
        password=s.password,
        ssl=s.ssl,
    )
    return client.select_graph(s.graph_name)


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


def read(graph, cypher: str, params: dict | None = None) -> list[dict]:
    """Read path. Uses ro_query so writes cannot run from here."""
    return to_dicts(graph.ro_query(cypher, params or {}))


def write(graph, cypher: str, params: dict | None = None) -> list[dict]:
    """Write path. Only load.py, apply_handover and reassign_tickets use this."""
    return to_dicts(graph.query(cypher, params or {}))
