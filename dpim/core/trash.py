"""回收站：物理删除前留档；恢复 = 重新入库。

**为什么不做软删**（给 `events` 加 `deleted_at` 列）：软删要给 FTS、检索、reconcile、
`graph_refs`、统计**所有读路径**加过滤，改动面大且极易漏一处；留档方案的改动面是
「1 个函数 + 1 个目录 + 1 个恢复入口」，语义还更直白——用户能直接打开文件看。

目录结构（与库同级的 `<db 所在目录>/trash/`）：

```
trash/
  events/<event_id>.json   {archived_at, kind, data:{事件整行}}
  nodes/<node_id>.json     {archived_at, kind, data:{节点 JSON}, edges:[关联边]}
  graphs/graph-<时间戳>.json {archived_at, kind, data:{nodes:[…], edges:[…]}, stats:{…}}
  restored/                {恢复成功的留档（移入，不删）}
```

**留档边信息（v1.31）**：删除节点时把它的关联边一并写进同一份留档的 `edges` 字段
（`data` 仍是节点 JSON 本体，旧读取方不受影响）——恢复端点据此「能恢复多少恢复多少」。
**整图留档（v1.42）**：`DELETE /graph` 清空前把整图（全部节点 + 全部边）留成**一份**
`trash/graphs/` 留档——单个节点删除都有留档，一次删掉整图反而无处可恢复，
是此前最不对称的一处；恢复走同一 `/trash/restore`（`kind=graph`，**合并式**补回）。
**恢复后留档移入 `restored/`**（不删原文件：保留「恢复过什么」的痕迹，
与损坏原件留档 `.corrupt-*` 同一纪律）。
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TRASH_DIRNAME = "trash"
RESTORED_DIRNAME = "restored"
KINDS = ("events", "nodes", "graphs")


def trash_root(db_path: str | Path) -> Path:
    """回收站根目录（与库文件同级，便于用户直接翻看）。"""
    return Path(db_path).parent / TRASH_DIRNAME


def _archive(
    db_path: str | Path, kind: str, item_id: str, data: dict, extra: dict | None = None
) -> Path | None:
    if kind not in KINDS:
        raise ValueError(f"未知留档类型: {kind}")
    if not db_path or str(db_path) == ":memory:":
        # 内存库没有可落档的位置（测试/临时场景），不留档也不报错
        return None
    target = trash_root(db_path) / kind / f"{item_id or 'unknown'}.json"
    payload = {
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "data": data,
        **(extra or {}),
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("已留档到回收站: %s", target.name)
        return target
    except OSError as exc:
        logger.warning("留档失败（不影响删除）: %s (%s)", target, exc)
        return None


def archive_event(db_path: str | Path, event: dict) -> Path | None:
    """删除前留档一条事件（含 graph_refs）。失败只告警，不阻断删除。"""
    return _archive(db_path, "events", str(event.get("event_id", "")), event)


def archive_node(
    db_path: str | Path, node: dict, edges: list[dict] | None = None
) -> Path | None:
    """删除前留档一个图节点（v1.31：可附带关联边，供恢复时尽力补回）。失败只告警。"""
    extra = {"edges": list(edges)} if edges else None
    return _archive(db_path, "nodes", str(node.get("node_id", "")), node, extra)


def archive_graph(
    db_path: str | Path,
    nodes: list[dict],
    edges: list[dict],
    stats: dict | None = None,
) -> Path | None:
    """清空图层前留档**整图**（v1.42），返回留档路径（失败返回 None）。

    `data` = `{nodes: [...], edges: [...]}`（与 `graph.json` 同形状的节点/边数组），
    `stats` = 留档时的计数（清单页据此显示「N 节点 / M 边」）。
    留档失败只告警、不阻断清空——但调用方**必须**把结果回报给用户：
    没有留档的清空是不可恢复的，不能让用户以为还能从回收站找回来。
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return _archive(
        db_path,
        "graphs",
        f"graph-{stamp}",
        {"nodes": list(nodes), "edges": list(edges)},
        {"stats": dict(stats or {"nodes": len(nodes), "edges": len(edges)})},
    )


def load_archived_edges(db_path: str | Path, kind: str, item_id: str) -> list[dict]:
    """读取留档时一并记下的关联边（v1.31）；无此字段/损坏返回空列表。"""
    target = trash_root(db_path) / kind / f"{item_id}.json"
    if not target.exists():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("留档边信息读取失败: %s (%s)", target, exc)
        return []
    edges = payload.get("edges")
    return [e for e in edges if isinstance(e, dict)] if isinstance(edges, list) else []


def mark_restored(db_path: str | Path, kind: str, item_id: str) -> Path | None:
    """恢复成功后把留档文件移入 `trash/restored/`（不删原文件）。失败只告警。"""
    root = trash_root(db_path)
    src = root / kind / f"{item_id}.json"
    if not src.exists():
        return None
    target = root / RESTORED_DIRNAME / f"{kind}-{item_id}.json"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, target)
        logger.info("留档已移入 restored: %s", target.name)
        return target
    except OSError as exc:
        logger.warning("留档移入 restored 失败（恢复结果不受影响）: %s (%s)", src, exc)
        return None


def list_archived(db_path: str | Path, kind: str | None = None) -> list[dict]:
    """列出回收站条目（新到旧）：`{kind, item_id, archived_at, path, bytes}`。"""
    root = trash_root(db_path)
    out: list[dict] = []
    for folder in (kind,) if kind else KINDS:
        directory = root / folder
        if not directory.is_dir():
            continue
        for item in directory.iterdir():
            if not item.is_file() or item.suffix != ".json":
                continue
            archived_at = ""
            try:
                payload = json.loads(item.read_text(encoding="utf-8"))
                archived_at = str(payload.get("archived_at", ""))
            except (json.JSONDecodeError, OSError):
                pass
            out.append(
                {
                    "kind": folder,
                    "item_id": item.stem,
                    "archived_at": archived_at,
                    "path": str(item),
                    "bytes": item.stat().st_size if item.exists() else 0,
                }
            )
    out.sort(key=lambda x: x["archived_at"], reverse=True)
    return out


def load_archived(db_path: str | Path, kind: str, item_id: str) -> dict | None:
    """读取一条留档的原始数据（`data` 字段）；不存在或损坏返回 None。"""
    target = trash_root(db_path) / kind / f"{item_id}.json"
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("留档读取失败: %s (%s)", target, exc)
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def prune_trash(
    db_path: str | Path, days: int, *, now: float | None = None
) -> dict[str, int]:
    """清理回收站里超过 `days` 天的留档（`0` = 永不清理）。返回 `{removed, kept, bytes}`。

    **纪律（留档是已删数据的最后一份副本，清理即永久丢失）**：
    ① 只按**年龄**清，不看条数；默认 30 天，`0 = 永不清理`；
    ② 只动 `trash/{events,nodes,graphs}/` 与 `trash/restored/` 里的 `.json`（不碰其它任何东西）；
    ③ 逐文件 try，单个失败只告警，不中断整轮；
    ④ 依据**文件 mtime**（留档里的 `archived_at` 字段可能被手工编辑，mtime 更可靠）。
    """
    if days <= 0:
        return {"removed": 0, "kept": 0, "bytes": 0}
    root = trash_root(db_path)
    if not root.is_dir():
        return {"removed": 0, "kept": 0, "bytes": 0}
    cutoff = (now if now is not None else time.time()) - days * 86400
    removed = kept = freed = 0
    for folder in (*KINDS, RESTORED_DIRNAME):
        directory = root / folder
        if not directory.is_dir():
            continue
        for item in directory.iterdir():
            if not item.is_file() or item.suffix != ".json":
                continue
            try:
                stat = item.stat()
            except OSError:
                continue
            if stat.st_mtime >= cutoff:
                kept += 1
                continue
            try:
                item.unlink()
                removed += 1
                freed += stat.st_size
            except OSError as exc:
                logger.warning("过期留档清理失败（不影响运行）: %s (%s)", item.name, exc)
    if removed:
        logger.info(
            "回收站清理：删除 %d 份超过 %d 天的留档（释放 %d 字节）", removed, days, freed
        )
    return {"removed": removed, "kept": kept, "bytes": freed}
