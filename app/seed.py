"""Load the Tidewell seed and indexes into FalkorDB. Shared by db/load.py, tests and POST /reset."""
from pathlib import Path

from app import db

ROOT = Path(__file__).resolve().parent.parent


def split_statements(text: str) -> list[str]:
    """Drop full-line // comments, split on ';' outside string literals."""
    kept = [line for line in text.splitlines() if not line.lstrip().startswith("//")]
    pieces, buf, quote = [], [], None
    for ch in "\n".join(kept):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == ";":
            pieces.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    pieces.append("".join(buf))
    return [p.strip() for p in pieces if p.strip()]


def run_file(graph, path: Path) -> int:
    statements = split_statements(path.read_text(encoding="utf-8"))
    for stmt in statements:
        db.write(graph, stmt)
    return len(statements)


def reset(graph) -> tuple[int, int]:
    """Drop the graph, then run seed.cypher and indexes.cypher. Returns statement counts."""
    try:
        graph.delete()
    except Exception:
        # Graph does not exist yet on a fresh instance.
        pass
    n_seed = run_file(graph, ROOT / "db" / "seed.cypher")
    n_idx = run_file(graph, ROOT / "db" / "indexes.cypher")
    return n_seed, n_idx
