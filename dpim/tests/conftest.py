import pytest

from core.database import Database
from core.event_store import EventStore
from core.graph_store import GraphStore


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def event_store(db):
    return EventStore(db)


@pytest.fixture
async def graph_store(db, tmp_path):
    json_path = tmp_path / "test_graph.json"
    gs = GraphStore(db, json_path=str(json_path))
    await gs.load()
    return gs
