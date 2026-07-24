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
async def real_db(tmp_path):
    """使用真实文件路径的数据库 fixture，用于验证 WAL 模式等文件级行为。

    默认不启用，CI 中通过 `pytest -m real_fs` 运行。
    """
    db_path = str(tmp_path / "test_memory.db")
    database = Database(db_path)
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
