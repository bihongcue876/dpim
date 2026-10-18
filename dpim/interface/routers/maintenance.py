"""存储维护 router：`/maintenance/*`（备份 / 校验 / 操作日志 / WAL 检查点）。

P4：备份、一致性校验、图层操作日志、WAL 治理——「结构之外」的体量与保障可见性。
"""

from fastapi import APIRouter, HTTPException

from core.graph_ops import list_ops
from core.maintenance import create_backup, list_backups, verify_storage
from core.models import (
    BackupListResponse,
    BackupResponse,
    CheckpointResponse,
    GraphOpItem,
    GraphOpListResponse,
    VerifyResponse,
)
from interface.deps import _database, _stores

router = APIRouter()


@router.post("/maintenance/backup", response_model=BackupResponse)
async def maintenance_backup(note: str = "", repo_id: str | None = None):
    """整库备份：SQLite 在线副本 + graph.json + 清单，保留最近 N 份。"""
    _es, gs = _stores(repo_id)
    database = _database(repo_id)
    try:
        result = await create_backup(database, gs, note=note)
    except RuntimeError as exc:  # 内存库等不支持备份的情形
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return BackupResponse(**result)


@router.get("/maintenance/backups", response_model=BackupListResponse)
async def maintenance_backups(repo_id: str | None = None):
    """列出整库备份（新到旧）。"""
    database = _database(repo_id)
    return BackupListResponse(backups=list_backups(database.db_path))


@router.post("/maintenance/verify", response_model=VerifyResponse)
async def maintenance_verify(repo_id: str | None = None):
    """只读一致性校验：SQLite 完整性 / FTS 行数一致 / 操作日志可重放 / 悬空源证。"""
    _es, gs = _stores(repo_id)
    database = _database(repo_id)
    return VerifyResponse(**await verify_storage(database, gs))


@router.get("/maintenance/ops", response_model=GraphOpListResponse)
async def maintenance_ops(
    repo_id: str | None = None, limit: int = 50, offset: int = 0
):
    """图层操作日志（审计）：谁 / 何时 / 因何改了图，以及删掉的节点原数据。"""
    _es, gs = _stores(repo_id)
    database = _database(repo_id)
    ops = await list_ops(
        database.conn, limit=max(1, min(limit, 500)), offset=max(0, offset)
    )
    return GraphOpListResponse(
        ops=[GraphOpItem(**item) for item in ops], total=await gs.ops_count()
    )


@router.post("/maintenance/checkpoint", response_model=CheckpointResponse)
async def maintenance_checkpoint(repo_id: str | None = None):
    """WAL 检查点（TRUNCATE）：收回主库并截断 WAL，防长期运行无界增长。"""
    database = _database(repo_id)
    busy, log_frames, checkpointed = await database.checkpoint("TRUNCATE")
    return CheckpointResponse(
        busy=busy,
        log_frames=log_frames,
        checkpointed_frames=checkpointed,
        wal_bytes=await database.wal_size(),
    )
