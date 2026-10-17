"""Load the Tidewell seed and indexes into FalkorDB.

    python db/load.py --reset    drop graph, run seed.cypher + indexes.cypher
    python db/load.py --check    print node and edge counts
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, queries, seed  # noqa: E402
from app.config import get_settings  # noqa: E402


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
        n_seed, n_idx = seed.reset(graph)
        print(f"loaded {n_seed} seed statements, {n_idx} index statements")
    if args.check:
        check(graph)
    return 0


if __name__ == "__main__":
    sys.exit(main())
