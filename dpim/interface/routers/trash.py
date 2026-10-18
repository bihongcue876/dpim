"""回收站 router：`GET /trash`、`POST /trash/restore`（v1.31，v1.42 增整图）。

留档由 `core/trash.py` 在物理删除前写入 `trash/{events,nodes,graphs}/<id>.json`：

- **事件**：整行数据（含 graph_refs），恢复走 `EventStore.restore()` **按原 id** 重新入库，
  FTS 同步重建——既有图节点的源证随之重新对上；
- **节点**：节点 JSON 本体 + 删除时一并留档的**关联边**（v1.31）；
  恢复时节点本体与 `source_refs` 必回，关联边「能恢复多少恢复多少」
  （仅当两端节点都在图中且该边不存在时才补回）；
- **整图**（v1.42）：`DELETE /graph` 清空前留档的整张图（`{nodes, edges}`）；
  恢复为**合并式**——已存在的节点/边跳过不覆盖，清空后恢复即完整回填。

**恢复成功后留档文件移入 `trash/restored/`**（不删原文件）：保留「恢复过什么」的痕迹，
与损坏原件留档 `.corrupt-*` 同一纪律。

边界：一库 = 一 db + 一 json，且两者同目录（受管库与外部库登记都要求同目录），
故回收站根 = 库文件同级的 `trash/`。事件留档按 db 路径定位、节点留档按 graph.json
路径定位（与写入侧一一对应）；清单合并两处并按路径去重，避免配置把两者分开时漏项。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from core.models import (
    GraphEdge,
    GraphNode,
    TrashItem,
    TrashListResponse,
    TrashRestoreRequest,
    TrashRestoreResponse,
)
from core.trash import (
    list_archived,
    load_archived,
    load_archived_edges,
    mark_restored,
    trash_root,
)
from interface.deps import _database, _stores, logger

router = APIRouter()

_TITLE_MAX = 80


def _paths(db_path: str, json_path: str) -> list[str]:
    """留档定位用的库文件路径候选（db 侧 + graph.json 侧；同目录时只有一个）。

    比较用 resolve 后的回收站根：配置里 db/json 一个相对一个绝对时也能识别「同一处」。
    """
    paths = [str(db_path)]
    try:
        same = trash_root(json_path).resolve() == trash_root(db_path).resolve()
    except OSError:  # 路径异常时不赌，两侧都查（宁多查不漏项）
        same = False
    if not same:
        paths.append(str(json_path))
    return paths


def _title_of(folder: str, data: dict) -> str:
    """留档内容里的标题/内容摘要（没有则空串）。"""
    if folder == "events":
        text = str(data.get("raw_content") or "")
    elif folder == "graphs":
        # 整图留档（v1.42）：没有单一标题，用计数当摘要
        return (
            f"整图留档：{len(data.get('nodes') or [])} 节点 / "
            f"{len(data.get('edges') or [])} 边"
        )
    else:
        text = str(data.get("title") or data.get("content") or "")
    return " ".join(text.split())[:_TITLE_MAX]


# 留档目录 ↔ API 类型（v1.42 增 graphs/graph）
_FOLDER_OF = {"event": "events", "node": "nodes", "graph": "graphs"}
_KIND_OF = {folder: kind for kind, folder in _FOLDER_OF.items()}
_LABEL_OF = {"event": "事件", "node": "节点", "graph": "图层留档"}


def _find_archive(paths: list[str], kind: str, item_id: str) -> tuple[str, dict] | None:
    """定位留档：返回 `(留档所在库文件路径, 留档数据)`；找不到返回 None。"""
    folder = _FOLDER_OF.get(kind, "nodes")
    for path in paths:
        data = load_archived(path, folder, item_id)
        if data is not None:
            return path, data
    return None


@router.get("/trash", response_model=TrashListResponse)
async def list_trash(repo_id: str | None = None):
    """回收站留档清单（按 `archived_at` 倒序）：库作用域同其它端点（缺省 = 活动库）。"""
    _es, gs = _stores(repo_id)
    db = _database(repo_id)
    paths = _paths(db.db_path, gs.json_path)
    seen: set[str] = set()
    items: list[TrashItem] = []
    for path in paths:
        for row in list_archived(path):
            key = str(Path(row["path"]).resolve())
            if key in seen:
                continue
            seen.add(key)
            data = load_archived(path, row["kind"], row["item_id"]) or {}
            items.append(
                TrashItem(
                    kind=_KIND_OF.get(row["kind"], "node"),
                    id=str(row["item_id"]),
                    archived_at=str(row["archived_at"]),
                    size=int(row["bytes"] or 0),
                    title=_title_of(row["kind"], data),
                    path=str(row["path"]),
                )
            )
    items.sort(key=lambda item: item.archived_at, reverse=True)
    return TrashListResponse(items=items, dir=str(trash_root(paths[0])))


def _restore_node_edges(gs, archived_edges: list[dict]) -> int:
    """尽力补回留档的关联边：两端节点都在图中且该边不存在时才补。"""
    restored = 0
    for raw in archived_edges:
        source = str(raw.get("source") or "")
        target = str(raw.get("target") or "")
        if not source or not target:
            continue
        if source not in gs.graph or target not in gs.graph:
            continue  # 另一端还没回来 → 不造悬空边
        if gs.graph.has_edge(source, target):
            continue
        try:
            gs.add_edge(GraphEdge(**raw))
        except Exception as exc:  # 单条边不合法只跳过，不拖累节点恢复
            logger.warning("留档边恢复失败（跳过）%s→%s: %s", source, target, exc)
            continue
        restored += 1
    return restored


@router.post("/trash/restore", response_model=TrashRestoreResponse)
async def restore_trash(body: TrashRestoreRequest, repo_id: str | None = None):
    """从留档恢复（事件 / 节点 / 整图）。

    事件与节点：已存在同 id → 409（不覆盖）。整图（v1.42）：**合并式**补回，
    已存在的节点/边跳过、不覆盖、不报 409。找不到留档 → 404。
    """
    es, gs = _stores(repo_id)
    db = _database(repo_id)
    item_id = (body.id or "").strip()
    if not item_id:
        raise HTTPException(status_code=400, detail="id 不能为空")
    paths = _paths(db.db_path, gs.json_path)
    label = _LABEL_OF.get(body.kind, "留档")

    found = _find_archive(paths, body.kind, item_id)
    if found is None:
        raise HTTPException(
            status_code=404,
            detail=f"回收站中没有该{label}的留档：{item_id}"
            f"（目录 {trash_root(paths[0])}）",
        )
    archive_path, data = found

    if body.kind == "event":
        if await es.get(item_id) is not None:
            raise HTTPException(
                status_code=409,
                detail=f"事件已存在（id={item_id}），无需恢复；"
                "如需用留档覆盖，请先删除该事件",
            )
        if not await es.restore(data):
            raise HTTPException(
                status_code=500, detail=f"事件恢复失败：留档缺少 event_id（{item_id}）"
            )
        moved = mark_restored(archive_path, "events", item_id)
        logger.info("回收站恢复事件 %s（留档移入 restored=%s）", item_id, bool(moved))
        return TrashRestoreResponse(
            message=f"事件已恢复：{item_id}（按原 id 重新入库，FTS 已重建，"
            "既有图节点源证随之对上）"
            + ("；留档已移入 trash/restored/" if moved else "")
        )

    # ── 整图留档（v1.42）：合并式补回，不覆盖现有图层 ──
    if body.kind == "graph":
        raw_nodes = data.get("nodes") if isinstance(data.get("nodes"), list) else []
        raw_edges = data.get("edges") if isinstance(data.get("edges"), list) else []
        added_nodes = skipped_nodes = 0
        for nd in raw_nodes:
            try:
                node = GraphNode.model_validate(nd)
            except Exception as exc:  # 单个节点不合法只跳过，不拖累整图恢复
                logger.warning("留档节点不合法（跳过）: %s", exc)
                continue
            if gs.get_node(node.node_id) is not None:
                skipped_nodes += 1
                continue
            gs.add_node(node)
            added_nodes += 1
        if added_nodes:
            await gs.rebuild_node_fts()  # 批量恢复：一次全量重建，不逐节点 upsert
        # 边复用「两端在图中且边不存在才补」的守卫：不造悬空边、不覆盖现有边
        added_edges = _restore_node_edges(gs, raw_edges)
        moved = mark_restored(archive_path, "graphs", item_id)
        logger.info(
            "回收站恢复整图 %s（补节点 %d / 跳过已存在 %d，补边 %d，留档移入 restored=%s）",
            item_id, added_nodes, skipped_nodes, added_edges, bool(moved),
        )
        return TrashRestoreResponse(
            message=f"图层已恢复：{item_id}（补回节点 {added_nodes} 个"
            + (f"、跳过已存在 {skipped_nodes} 个" if skipped_nodes else "")
            + f"，补回边 {added_edges} 条；合并式恢复，未覆盖现有图层）"
            + ("；留档已移入 trash/restored/" if moved else "")
        )

    # ── 节点 ──
    node_id = str(data.get("node_id") or item_id)
    if gs.get_node(node_id) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"节点已存在（id={node_id}），无需恢复；"
            "如需用留档覆盖，请先删除该节点",
        )
    try:
        node = GraphNode.model_validate(data)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"留档节点数据不合法，无法恢复（{node_id}）：{exc}"
        ) from exc
    gs.add_node(node)
    await gs.upsert_node_fts(node.node_id, node.title, node.content)
    edge_count = _restore_node_edges(
        gs, load_archived_edges(archive_path, "nodes", item_id)
    )
    moved = mark_restored(archive_path, "nodes", item_id)
    logger.info(
        "回收站恢复节点 %s（源证 %d 条，补回边 %d 条，留档移入 restored=%s）",
        node.node_id, len(node.source_refs), edge_count, bool(moved),
    )
    return TrashRestoreResponse(
        message=f"节点已恢复：{node.node_id}（{node.title}；"
        f"源证 {len(node.source_refs)} 条，补回关联边 {edge_count} 条）"
        + ("；留档已移入 trash/restored/" if moved else "")
    )
