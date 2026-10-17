import os

import pytest

from app import seed  # importing app.config loads .env via db.connect
from app.db import connect


def pytest_addoption(parser):
    parser.addoption("--base-url", default=None,
                     help="Run the golden tests against a live server instead of TestClient.")
    parser.addoption("--write-baseline-doc", action="store_true", default=False,
                     help="Write docs/baseline_results.md from the golden run (calls /baseline too).")


@pytest.fixture(scope="session", autouse=True)
def seeded_session():
    """Every run starts and ends with the seed loaded, so no test sees leftovers from another."""
    seed.reset(connect())
    yield
    seed.reset(connect())


@pytest.fixture
def reseeded_graph():
    """Drop and re-seed the graph before the test; re-seed again after it."""
    graph = connect()
    seed.reset(graph)
    yield graph
    seed.reset(connect())


@pytest.fixture
def demo_token():
    return os.environ.get("DEMO_TOKEN", "")
