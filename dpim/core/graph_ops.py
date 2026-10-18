"""图层操作日志（graph_ops）：追加型、可重放、可审计。

定位（对齐 `docs/图层派生关系核实20261003.md` 的方案①）：

- **让「图层是派生 read-model」名实相符**：`graph.json` 丢失或损坏时，可从
  `graph_ops` 重放图层，而不是以空图启动；
- **可审计**：每批落盘变更带 `reason`（因何改了图）与 `actor`。

写入方式：`GraphStore.save()` 落盘 JSON 后，把「相对上次落盘的状态差分」写成一批 op。
**差分而非逐方法埋点**：单一收口，不会因为漏埋一个方法就让重放发散。
代价：内存里多保留一份上次落盘快照（实验规模可忽略）。

op 种类（重放只需这五种）：

| kind | 载荷 | 说明 |
|---|---|---|
| `node_upsert` | `{node}` | 新增/修改节点（含合并后的目标节点） |
| `node_delete` | `{node_id, node}` | 删除节点（`node` = 被删节点原数据） |
| `edge_upsert` | `{edge}` | 新增/修改边 |
| `edge_delete` | `{source, target, edge}` | 删除边（`edge` = 被删边原数据，v1.42） |
| `graph_clear` | `{}` | 清空图谱 |

两类删除都带上被删对象的原数据：重放只按 id / 端点删，但审计与人工抢救需要看到
**删了什么**——合并吸收的 source 节点、整图清空后的边细节（relation / evidence），
都靠这份载荷留痕。

纪律：JSON 是主产物，ops 是审计与恢复依据。ops 写入失败只记 ERROR 不阻断
（否则会出现「JSON 已写、调用方却收到 500」的错觉）；`verify` 会核对两者是否一致。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

NODE_UPSERT = "node_upsert"
NODE_DELETE = "node_delete"
EDGE_UPSERT = "edge_upsert"
EDGE_DELETE = "edge_delete"
GRAPH_CLEAR = "graph_clear"

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS graph_ops (
    op_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    op_kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT 'system'
);
CREATE INDEX IF NOT EXISTS idx_graph_ops_ts ON graph_ops(created_at);
"""


def snapshot_graph(graph) -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    """把 NetworkX 图拍成两份纯 dict 快照（节点按 id，边按 (source, target)）。"""
    nodes: dict[str, dict] = {}
    for nid, ndata in graph.nodes(data="data"):
        if ndata is not None:
            nodes[nid] = ndata.model_dump()
    edges: dict[tuple[str, str], dict] = {}
    for src, dst, edata in graph.edges(data="data"):
        if edata is not None:
            edges[(src, dst)] = edata.model_dump()
    return nodes, edges


def diff_ops(
    prev_nodes: dict[str, dict],
    prev_edges: dict[tuple[str, str], dict],
    nodes: dict[str, dict],
    edges: dict[tuple[str, str], dict],
) -> list[dict[str, Any]]:
    """计算「上次落盘 → 当前」的差分操作序列。

    顺序固定：节点增改 → 节点删除 → 边增改 → 边删除（保证重放时先有端点再有边）。
    """
    ops: list[dict[str, Any]] = []
    for nid, data in nodes.items():
        if prev_nodes.get(nid) != data:
            ops.append({"kind": NODE_UPSERT, "node": data})
    for nid in prev_nodes:
        if nid not in nodes:
            # 带上被删节点的原数据：重放只按 id 删除，但审计/人工抢救需要看到删了什么
            # （合并吸收的 source 节点就靠这里留痕）
            ops.append({"kind": NODE_DELETE, "node_id": nid, "node": prev_nodes.get(nid, {})})
    for key, data in edges.items():
        if prev_edges.get(key) != data:
            ops.append({"kind": EDGE_UPSERT, "edge": data})
    for key in prev_edges:
        if key not in edges:
            # 与 node_delete 对称：带上被删边的原数据。重放只按端点删（见 replay），
            # 但审计与人工抢救需要看到删的是哪条关系、证据事件是什么——
            # 整图清空之后，这份 op 是边细节的唯一来源。
            ops.append({
                "kind": EDGE_DELETE,
                "source": key[0],
                "target": key[1],
                "edge": prev_edges.get(key, {}),
            })
    return ops


def replay(ops: list[dict]) -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    """纯函数重放：把 op 序列应用到空图上，返回 `(nodes, edges)`。

    不依赖 NetworkX，便于单测；`node_delete` 同时移除其关联边
    （与 NetworkX `remove_node` 语义一致）。
    """
    nodes: dict[str, dict] = {}
    edges: dict[tuple[str, str], dict] = {}
    for op in ops:
        kind = op.get("kind")
        if kind == NODE_UPSERT:
            node = op.get("node") or {}
            nid = node.get("node_id")
            if nid:
                nodes[nid] = node
        elif kind == NODE_DELETE:
            nid = op.get("node_id")
            nodes.pop(nid, None)
            for key in [k for k in edges if nid in k]:
                edges.pop(key, None)
        elif kind == EDGE_UPSERT:
            edge = op.get("edge") or {}
            src, dst = edge.get("source"), edge.get("target")
            if src and dst:
                edges[(src, dst)] = edge
        elif kind == EDGE_DELETE:
            edges.pop((op.get("source"), op.get("target")), None)
        elif kind == GRAPH_CLEAR:
            nodes.clear()
            edges.clear()
    return nodes, edges


async def record_ops(conn, ops: list[dict], *, reason: str = "", actor: str = "system") -> int:
    """把一批 op 追加写入 graph_ops（一次提交）。返回写入条数。"""
    if not ops:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            now,
            str(op.get("kind", "")),
            json.dumps(op, ensure_ascii=False),
            reason[:200],
            actor[:40],
        )
        for op in ops
    ]
    await conn.executemany(
        "INSERT INTO graph_ops (created_at, op_kind, payload, reason, actor) VALUES (?,?,?,?,?)",
        rows,
    )
    await conn.commit()
    return len(rows)


async def list_ops(conn, *, limit: int = 100, offset: int = 0) -> list[dict]:
    """按写入顺序读取 op（分页），payload 解析为对象。"""
    cursor = await conn.execute(
        "SELECT op_id, created_at, op_kind, payload, reason, actor FROM graph_ops"
        " ORDER BY op_id ASC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    rows = await cursor.fetchall()
    out: list[dict] = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item["payload"])
        except (json.JSONDecodeError, TypeError):
            pass
        out.append(item)
    return out


async def count_ops(conn) -> int:
    cursor = await conn.execute("SELECT COUNT(*) AS c FROM graph_ops")
    row = await cursor.fetchone()
    return int(row["c"]) if row else 0


async def load_all_ops(conn) -> list[dict]:
    """按写入顺序读取全部 op（重放用）；单条 payload 解析失败只告警跳过。"""
    cursor = await conn.execute("SELECT payload FROM graph_ops ORDER BY op_id ASC")
    rows = await cursor.fetchall()
    ops: list[dict] = []
    for row in rows:
        try:
            ops.append(json.loads(row["payload"]))
        except (json.JSONDecodeError, TypeError):
            logger.warning("graph_ops 单条 payload 解析失败，重放时跳过")
    return ops


async def compact_ops(
    conn, *, keep: int, reason: str = "retention-compaction"
) -> dict[str, Any]:
    """把最老的明细 op **压实**成一批等价快照 op，使表行数有界而**重放结果不变**（v1.39）。

    为什么不是直接截断：`graph_ops` 是「`graph.json` 丢失/损坏且无备份时的重放恢复依据」，
    `POST /maintenance/verify` 也按「重放全部 op == 内存图」判一致性——直接删掉老 op 会让
    重放只能还原后半段（恢复不完整、体检恒红）。故这里把 `[0, cut)` 段重放出的状态写成
    `graph_clear` + 逐节点/逐边 upsert 的**等价快照**，接在保留的明细段之前：
    `replay(压实后) == replay(压实前)`，于是恢复能力与体检口径都不变。

    边界（如实记录）：
    - 被压掉的明细**不再可审计**（这正是保留策略的本意：留近不留远）；
    - 表行数下限 = **1 + 节点数 + 边数**（快照本身），故 `keep` 应显著大于图规模；
      快照比被替换的明细还大时**原样不动**（避免越压越多）；
    - 压实会**重写 op_id**（顺序与内容等价），保留段的 `created_at`/`reason`/`actor` 原样保留。

    返回 `{before, after, removed, compacted}`；`keep <= 0` = 不压实。
    """
    if keep <= 0:
        return {"before": 0, "after": 0, "removed": 0, "compacted": False}
    cursor = await conn.execute(
        "SELECT created_at, op_kind, payload, reason, actor FROM graph_ops ORDER BY op_id ASC"
    )
    rows = await cursor.fetchall()
    before = len(rows)
    if before <= keep:
        return {"before": before, "after": before, "removed": 0, "compacted": False}

    cut = before - keep
    head, tail = rows[:cut], rows[cut:]
    ops: list[dict] = []
    for row in head:
        try:
            ops.append(json.loads(row["payload"]))
        except (json.JSONDecodeError, TypeError):
            continue
    nodes, edges = replay(ops)

    now = datetime.now(timezone.utc).isoformat()
    snapshot: list[tuple[str, str]] = []
    if nodes or edges:
        snapshot.append((GRAPH_CLEAR, json.dumps({"kind": GRAPH_CLEAR}, ensure_ascii=False)))
        for data in nodes.values():
            snapshot.append((
                NODE_UPSERT,
                json.dumps({"kind": NODE_UPSERT, "node": data}, ensure_ascii=False),
            ))
        for data in edges.values():
            snapshot.append((
                EDGE_UPSERT,
                json.dumps({"kind": EDGE_UPSERT, "edge": data}, ensure_ascii=False),
            ))
    if len(snapshot) >= cut:
        # 压不动（快照比被替换的明细还大）→ 不动，否则越压越多
        return {"before": before, "after": before, "removed": 0, "compacted": False}

    new_rows = [(now, kind, payload, reason[:200], "system") for kind, payload in snapshot]
    new_rows += [
        (row["created_at"], row["op_kind"], row["payload"], row["reason"], row["actor"])
        for row in tail
    ]
    # 整表重写：DELETE 与 INSERT 在同一事务里（commit 前崩溃则整体回滚，不会只剩空表）
    await conn.execute("DELETE FROM graph_ops")
    await conn.executemany(
        "INSERT INTO graph_ops (created_at, op_kind, payload, reason, actor) VALUES (?,?,?,?,?)",
        new_rows,
    )
    await conn.commit()
    logger.info(
        "graph_ops 压实：%d → %d 行（压掉最老 %d 条明细，保留最近 %d 条）",
        before, len(new_rows), cut, keep,
    )
    return {"before": before, "after": len(new_rows), "removed": cut, "compacted": True}
