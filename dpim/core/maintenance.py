"""存储维护：整库备份、一致性校验、（由本地 CLI 提供的）恢复。

对齐「存储系统的底线」——这些入口此前**完全缺失**：事件层零备份、无 `VACUUM`、
无 `integrity_check`、无容量观测。图层那边只有一代 `.bak`，且是「先写后备份」
（等于当前文件的副本，不是上一代）。

设计取舍：

- **备份**用 `VACUUM INTO`：SQLite 3.27+ 原生，产出一致且紧凑的整库副本，零新依赖；
  连同 `graph.json` 与 `manifest.json`（计数/版本/体积）一起放进
  `<库目录>/backups/<时间戳>/`，保留最近 N 份。
- **恢复不做 REST 端点**：恢复必须停服务（内存图会陈旧），做成 REST 反而危险；
  由本地 CLI `main.py restore <时间戳>` 执行，并强制先给当前状态做一次安全备份。
- **校验**只读：SQLite 完整性/外键、`events↔events_fts`、`节点↔node_fts`、
  **`graph_ops` 重放结果与内存图一致**（差分日志可信度）、悬空源证、无边端点的边、
  **`graph.json` 文件里的悬空边**（v1.42：端点不在 nodes 中的边，加载时会被跳过）。
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.graph_ops import load_all_ops, replay, snapshot_graph
from core.graph_store import GRAPH_FORMAT_VERSION
from core.trash import list_archived

logger = logging.getLogger(__name__)

BACKUP_DIRNAME = "backups"
KEEP_BACKUPS = 5
# 悬空源证检查的取样上限（防大图全量 IN 查询）
_MAX_REF_SAMPLE = 2000


async def _count(db, sql: str) -> int:
    cursor = await db.conn.execute(sql)
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


def _is_memory_db(db_path: str) -> bool:
    return not db_path or db_path == ":memory:"


async def create_backup(
    db, graph_store, *, note: str = "", keep: int = KEEP_BACKUPS
) -> dict[str, Any]:
    """整库备份（SQLite 在线副本 + graph.json + 清单）。返回备份信息。"""
    if _is_memory_db(db.db_path):
        raise RuntimeError("内存库不支持备份（请用真实文件库）")
    root = Path(db.db_path).parent / BACKUP_DIRNAME
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = root / stamp
    if target.exists():  # 同秒重复备份：加后缀避免覆盖
        stamp = f"{stamp}-{datetime.now().microsecond:06d}"
        target = root / stamp
    target.mkdir(parents=True, exist_ok=False)

    db_copy = target / Path(db.db_path).name
    # VACUUM INTO：一致且紧凑的整库副本（不能与其它语句同事务）
    await db.conn.execute("VACUUM INTO ?", (str(db_copy),))
    await db.conn.commit()

    src_json = Path(graph_store.json_path)
    json_copy: Path | None = None
    if src_json.exists():
        json_copy = target / src_json.name
        shutil.copy2(src_json, json_copy)

    manifest: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": note[:200],
        "db_path": str(db.db_path),
        "json_path": str(src_json),
        "total_events": await _count(db, "SELECT COUNT(*) FROM events"),
        "total_nodes": graph_store.total_nodes(),
        "total_edges": graph_store.total_edges(),
        "graph_ops": await graph_store.ops_count(),
        "schema_version": (await _pragma(db, "user_version")),
        "graph_format_version": GRAPH_FORMAT_VERSION,
        "db_bytes": db_copy.stat().st_size if db_copy.exists() else 0,
        "json_bytes": json_copy.stat().st_size if json_copy else 0,
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pruned = prune_backups(db.db_path, keep)
    logger.info("整库备份完成: %s（清理旧备份 %d 份）", target, pruned)
    return {"backup_dir": str(target), "stamp": stamp, "manifest": manifest, "pruned": pruned}


async def _pragma(db, name: str) -> int:
    try:
        cursor = await db.conn.execute(f"PRAGMA {name}")
        row = await cursor.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def list_backups(db_path: str | Path) -> list[dict[str, Any]]:
    """列出整库备份（新到旧）：`{stamp, path, bytes, manifest}`。"""
    root = Path(db_path).parent / BACKUP_DIRNAME
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for item in root.iterdir():
        if not item.is_dir():
            continue
        manifest: dict[str, Any] = {}
        manifest_path = item / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                manifest = {}
        total = sum(f.stat().st_size for f in item.iterdir() if f.is_file())
        out.append({"stamp": item.name, "path": str(item), "bytes": total, "manifest": manifest})
    out.sort(key=lambda x: x["stamp"], reverse=True)
    return out


def prune_backups(db_path: str | Path, keep: int = KEEP_BACKUPS) -> int:
    """只保留最近 `keep` 份整库备份，返回清理数（keep <= 0 = 不清理）。"""
    if keep <= 0:
        return 0
    backups = list_backups(db_path)
    removed = 0
    for item in backups[keep:]:
        try:
            shutil.rmtree(item["path"])
            removed += 1
        except OSError as exc:
            logger.warning("旧备份清理失败: %s (%s)", item["path"], exc)
    return removed


async def verify_storage(db, graph_store) -> dict[str, Any]:
    """只读一致性校验，返回 `{ok, checks, sizes, counts}`。"""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    # 1) SQLite 页面完整性
    try:
        cursor = await db.conn.execute("PRAGMA integrity_check")
        row = await cursor.fetchone()
        integrity = str(row[0]) if row else "unknown"
    except Exception as exc:
        integrity = f"检查失败: {exc}"
    add("sqlite_integrity", integrity == "ok", integrity)

    # 2) 外键一致性
    try:
        cursor = await db.conn.execute("PRAGMA foreign_key_check")
        violations = len(await cursor.fetchall())
    except Exception as exc:
        violations = -1
        add("foreign_keys", False, f"检查失败: {exc}")
    else:
        add("foreign_keys", violations == 0, f"{violations} 条违规")

    # 3) events ↔ events_fts 行数一致（FTS 是手工同步的副本，最易漂移）
    events_total = await _count(db, "SELECT COUNT(*) FROM events")
    fts_total = await _count(db, "SELECT COUNT(*) FROM events_fts")
    add("events_fts_consistency", events_total == fts_total,
        f"events={events_total} events_fts={fts_total}")

    # 4) 内存图 ↔ node_fts 行数一致（node_fts 以内存图为唯一真源）
    nodes_total = graph_store.total_nodes()
    node_fts_total = await _count(db, "SELECT COUNT(*) FROM node_fts")
    add("node_fts_consistency", nodes_total == node_fts_total,
        f"nodes={nodes_total} node_fts={node_fts_total}")

    # 5) graph_ops 重放结果 == 内存图（差分日志可信度；不等说明重放依据缺失）
    try:
        ops = await load_all_ops(db.conn)
        replayed_nodes, replayed_edges = replay(ops)
        live_nodes, live_edges = snapshot_graph(graph_store.graph)
        same = replayed_nodes == live_nodes and replayed_edges == live_edges
        add("ops_replay_matches_graph", same,
            f"ops={len(ops)} 重放 nodes={len(replayed_nodes)}/live={len(live_nodes)} "
            f"edges={len(replayed_edges)}/live={len(live_edges)}")
    except Exception as exc:
        add("ops_replay_matches_graph", False, f"重放检查失败: {exc}")

    # 6) 悬空源证（引用的事件已不存在）
    ref_ids: list[str] = []
    for _, ndata in graph_store.graph.nodes(data="data"):
        if ndata is None:
            continue
        for sr in ndata.source_refs:
            if sr.valid and sr.event_id and sr.event_id not in ref_ids:
                ref_ids.append(sr.event_id)
            if len(ref_ids) >= _MAX_REF_SAMPLE:
                break
    dangling = 0
    if ref_ids:
        placeholders = ",".join("?" * len(ref_ids))
        cursor = await db.conn.execute(
            f"SELECT COUNT(*) FROM events WHERE event_id IN ({placeholders})", ref_ids
        )
        row = await cursor.fetchone()
        dangling = len(ref_ids) - (int(row[0]) if row else 0)
    add("no_dangling_source_refs", dangling == 0,
        f"检查 {len(ref_ids)} 条有效源证，悬空 {dangling} 条")

    # 7) 无边端点的边（NetworkX 会自动造出无 data 的节点，属隐患）
    orphan_nodes = [
        nid for nid, ndata in graph_store.graph.nodes(data="data") if ndata is None
    ]
    add("no_dateless_nodes", not orphan_nodes,
        f"{len(orphan_nodes)} 个节点缺 data" + (f"（如 {orphan_nodes[:3]}）" if orphan_nodes else ""))

    # 8) graph.json 文件里的悬空边（端点不在 nodes 中，v1.42）
    # 加载时会跳过这类边（否则 NetworkX 会造出无 data 的空壳节点）并标记脏位，
    # 下次落盘即清除；此处直接读文件，把「文件级残留」如实报出来而不是静默吞掉。
    if str(graph_store.json_path) == ":memory:":
        add("no_dangling_edges_in_file", True, "内存图（无文件）")
    else:
        try:
            raw = json.loads(
                Path(graph_store.json_path).read_text(encoding="utf-8")
            )
            file_nodes = set(raw.get("nodes") or {})
            file_dangling = [
                e for e in (raw.get("edges") or [])
                if e.get("source") not in file_nodes or e.get("target") not in file_nodes
            ]
            add("no_dangling_edges_in_file", not file_dangling,
                f"{len(file_dangling)} 条边的端点不在 nodes"
                + ("（加载时已跳过，下次落盘即清除）" if file_dangling else ""))
        except FileNotFoundError:
            add("no_dangling_edges_in_file", True, "graph.json 不存在（空库）")
        except Exception as exc:
            add("no_dangling_edges_in_file", False, f"检查失败: {exc}")

    sizes = {
        "db_bytes": await db.db_size(),
        "wal_bytes": await db.wal_size(),
        "json_bytes": Path(graph_store.json_path).stat().st_size
        if Path(graph_store.json_path).exists() else 0,
        "backups": len(list_backups(db.db_path)),
        "trash_items": len(list_archived(db.db_path)),
    }
    counts = {
        "events": events_total,
        "nodes": nodes_total,
        "edges": graph_store.total_edges(),
        "graph_ops": await graph_store.ops_count(),
    }
    return {
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "sizes": sizes,
        "counts": counts,
    }
