"""各职责 router 的汇总导出（`interface/api.py` 统一 `include_router`）。

纯搬移：路由路径、方法、响应模型与拆分前逐一对应（v1.31 起端点总数 42）。
"""

from interface.routers.agent import router as agent_router
from interface.routers.events import router as events_router
from interface.routers.logs import router as logs_router
from interface.routers.maintenance import router as maintenance_router
from interface.routers.nodes import router as nodes_router
from interface.routers.query import router as query_router
from interface.routers.repos import router as repos_router
from interface.routers.settings import router as settings_router
from interface.routers.trash import router as trash_router

__all__ = [
    "agent_router",
    "events_router",
    "logs_router",
    "maintenance_router",
    "nodes_router",
    "query_router",
    "repos_router",
    "settings_router",
    "trash_router",
]
