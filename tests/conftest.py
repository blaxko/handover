import importlib.util
from pathlib import Path

import pytest

from app.db import connect

ROOT = Path(__file__).resolve().parent.parent


def _load_loader():
    # db/ is not a package; load load.py by path to reuse its reset().
    spec = importlib.util.spec_from_file_location("handover_loader", ROOT / "db" / "load.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def reseeded_graph():
    """Drop and re-seed the graph before the test; re-seed again after it."""
    loader = _load_loader()
    graph = connect()
    loader.reset(graph)
    yield graph
    loader.reset(connect())
