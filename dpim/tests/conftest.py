import shutil
import uuid
from pathlib import Path

import pytest

from core.database import Database
from core.event_store import EventStore
from core.graph_store import GraphStore

# 沙箱环境（DSH）下系统临时目录（%TEMP%）受限：覆盖 pytest 内置 tmp_path，
# 固定使用工作区内目录，保证测试可写。目录名以 . 开头，pytest 收集自动忽略。
_WS_TMP = Path(__file__).resolve().parent / ".pytest_tmp_ws"


@pytest.fixture
def tmp_path():
    """覆盖 pytest 内置 tmp_path：固定工作区目录，每个测试独立子目录。"""
    _WS_TMP.mkdir(parents=True, exist_ok=True)
    p = _WS_TMP / uuid.uuid4().hex[:12]
    p.mkdir(parents=True, exist_ok=True)
    yield p
    # 测试后尝试清理（沙箱拒删目录时静默忽略，不影响测试）
    try:
        shutil.rmtree(p)
    except OSError:
        pass


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
