"""任务级临时内存 — 单次 ingest/search 任务生命周期内的共享上下文。

各工具调用之间通过 TaskMemory 传递中间产物与审核反馈。
任务结束时（成功/失败/异常）由管线负责释放，不保留跨任务状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import AnnotatedChunks, GraphBuildOutput, GraphNode, MetaCogVerdict


@dataclass
class TaskMemory:
    """一次 Agent 管线的临时上下文载体。

    - ingest 任务：raw_content / annotated_chunks / similar_nodes / graph_proposal
    - search 任务：query / intent / results
    - 修正循环：last_feedback（Meta issues）、attempts
    """

    task_id: str = ""
    event_id: str = ""
    raw_content: str = ""

    # ingest 中间产物
    annotated_chunks: AnnotatedChunks | None = None
    similar_nodes: list[GraphNode] = field(default_factory=list)
    graph_proposal: GraphBuildOutput | None = None
    meta_verdict: MetaCogVerdict | None = None
    created_node_ids: list[str] = field(default_factory=list)

    # search 中间产物
    query: str = ""
    intent: dict[str, Any] | None = None
    results: list[Any] = field(default_factory=list)

    # 修正循环控制
    last_feedback: str = ""
    attempts: int = 0
