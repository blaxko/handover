"""Load the Tidewell seed and indexes into FalkorDB.

    python db/load.py --reset    drop graph, run seed.cypher + indexes.cypher
    python db/load.py --check    print node and edge counts
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, queries  # noqa: E402
from app.config import get_settings  # noqa: E402


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


def reset(graph) -> None:
    try:
        graph.delete()
    except Exception:
        # Graph does not exist yet on a fresh instance.
        pass
    n_seed = run_file(graph, ROOT / "db" / "seed.cypher")
    n_idx = run_file(graph, ROOT / "db" / "indexes.cypher")
    print(f"loaded {n_seed} seed statements, {n_idx} index statements")


def check(graph) -> None:
    nodes = db.read(graph, "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS c ORDER BY label")
    edges = db.read(graph, "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS c ORDER BY type")
    print("nodes:")
    for r in nodes:
        print(f"  {r['label']:<10} {r['c']}")
    print("edges:")
    for r in edges:
        print(f"  {r['type']:<12} {r['c']}")
    bad = [r for r in queries.open_owns_counts(graph) if r["open"] != 1]
    print("invariant (one open OWNS per service):", "OK" if not bad else f"FAILED {bad}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not (args.reset or args.check):
        parser.error("pass --reset or --check")

    graph = db.connect(get_settings())
    if args.reset:
        reset(graph)
    if args.check:
        check(graph)
    return 0


if __name__ == "__main__":
    sys.exit(main())
