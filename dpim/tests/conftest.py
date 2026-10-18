import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest


def _pick_tmp_root() -> Path:
    """挑一个**真实可写**的测试临时根。

    DSH 沙箱下子进程可能只能写工作区根与它提供的临时目录（工作区子目录拒写）；
    普通 shell 下则相反（系统临时目录可能受限）。因此按
    「显式 env `DPIM_TEST_TMP` → 工作区内目录 → 系统临时目录」顺序、**以真实写入为准**探测。
    """
    candidates: list[Path] = []
    env = os.environ.get("DPIM_TEST_TMP")
    if env:
        candidates.append(Path(env))
    candidates.append(Path(__file__).resolve().parent / ".pytest_tmp_ws")
    candidates.append(Path(tempfile.gettempdir()) / "dpim-pytest-tmp")
    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / f".probe-{uuid.uuid4().hex[:8]}"
            probe.mkdir()
            probe.rmdir()
            return cand
        except OSError:
            continue
    raise RuntimeError("找不到可写的测试临时目录（可用环境变量 DPIM_TEST_TMP 指定）")


_WS_TMP = _pick_tmp_root()

# 测试期的本地日志落到临时根，避免污染仓库内 dpim/logs/。
# 必须在 import core.* 之前设置：core.config 在导入时即实例化 settings。
os.environ.setdefault("DPIM_LOG_DIR", str(_WS_TMP / "logs"))

from core.database import Database  # noqa: E402
from core.event_store import EventStore  # noqa: E402
from core.graph_store import GraphStore  # noqa: E402


@pytest.fixture
def tmp_path():
    """覆盖 pytest 内置 tmp_path：可写临时根下每个测试独立子目录。"""
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
