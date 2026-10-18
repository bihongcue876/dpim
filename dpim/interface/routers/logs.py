"""本地日志 router：`GET /logs`、`POST /logs/client`（v1.31）。

前端「日志页」的数据面，复用链 W 的 `core/logging_setup`（前后端分文件、按天轮转）：

- `GET /logs`：按通道 / 日期 / 级别 / 关键词翻看尾部。**只读**——不改任何状态、
  也不触发状态校验密钥刷新（读端点不参与 `write_commit` 的刷新）；
- `POST /logs/client`：浏览器把前端日志按级别送回 `frontend-YYYY-MM-DD.log`。
  它虽是 POST，但属**日志旁路而非数据写入**：`write_commit` 已显式豁免
  （`api._NO_REFRESH_WRITES`），**成功也不刷新状态校验密钥**——否则前端每次
  上报日志都会让密钥变化，把护栏变成噪声。

`dir` 一律回报**日志目录的绝对路径**（用户能直接照着去打开文件）；
`truncated` 表示**过滤后**匹配行数超过 `tail`（返回的仍是最新 tail 行）。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from core.config import settings
from core.logging_setup import (
    BACKEND,
    MAX_FRONTEND_MESSAGE,
    STREAMS,
    list_log_files,
    read_log_lines,
    write_frontend_log,
)
from core.models import (
    ClientLogRequest,
    ClientLogResponse,
    LogFileInfo,
    LogsResponse,
)

router = APIRouter()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TAIL_MIN = 1
_TAIL_MAX = 2000
_MAX_KEYWORD = 200


def _log_dir() -> Path:
    return Path(settings.log_dir).resolve()


def _files_of(kind: str) -> list[LogFileInfo]:
    """该通道的全部日志文件（`list_log_files` 已按日期 + 文件名倒序 = 新到旧）。"""
    out: list[LogFileInfo] = []
    for info in list_log_files(str(_log_dir())):
        if info["stream"] != kind:
            continue
        out.append(
            LogFileInfo(
                name=str(info["name"]),
                kind=kind,
                date=str(info["day"]),
                size=int(info.get("size") or 0),
                mtime=float(info.get("mtime") or 0.0),
            )
        )
    return out


@router.get("/logs", response_model=LogsResponse)
async def get_logs(
    kind: str = BACKEND,
    date: str | None = None,
    level: str | None = None,
    keyword: str | None = None,
    tail: int = 200,
):
    """翻看本地日志尾部：`date` 可空 = 该通道最新一天；`tail` 取**最新**的 N 行。"""
    kind_norm = (kind or "").strip().lower()
    if kind_norm not in STREAMS:
        raise HTTPException(
            status_code=400,
            detail=f"kind 非法：{kind}（仅支持 {' / '.join(STREAMS)}）",
        )
    if not (_TAIL_MIN <= tail <= _TAIL_MAX):
        raise HTTPException(
            status_code=400,
            detail=f"tail 须在 {_TAIL_MIN}..{_TAIL_MAX} 之间（收到 {tail}）",
        )
    day = (date or "").strip()
    if day and not _DATE_RE.match(day):
        raise HTTPException(
            status_code=400, detail=f"date 格式非法：{date}（须为 YYYY-MM-DD）"
        )

    files = _files_of(kind_norm)
    if not day:
        day = files[0].date if files else ""  # 可空 = 最新一天（无日志则为空）
    kw = (keyword or "").strip()[:_MAX_KEYWORD]

    # 多取一行用于判断「过滤后是否被 tail 截断」：过滤发生在取尾之前
    matched = read_log_lines(
        stream=kind_norm,
        day=day or None,
        level=level,
        keyword=kw or None,
        limit=tail + 1,
        log_dir=str(_log_dir()),
    )
    truncated = len(matched) > tail
    lines = matched[-tail:] if truncated else matched
    return LogsResponse(
        kind=kind_norm,
        date=day,
        dir=str(_log_dir()),
        files=files,
        lines=lines,
        truncated=truncated,
    )


@router.post("/logs/client", response_model=ClientLogResponse)
async def post_client_log(body: ClientLogRequest):
    """接收浏览器送来的一条前端日志（落 `frontend-YYYY-MM-DD.log`）。

    `message` 超 `MAX_FRONTEND_MESSAGE`（8000）字符**截断**而非报错——
    日志通道不该因为一条过长记录让前端报错；空 message 才拒绝（无意义写入）。

    **不刷新状态校验密钥**：日志上报不是数据写入，写侧豁免见
    `interface/api.py::_NO_REFRESH_WRITES`（与 `GET /logs` 只读同一条纪律）。
    """
    message = (body.message or "")[:MAX_FRONTEND_MESSAGE]
    if not message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")
    written = write_frontend_log(
        [
            {
                "level": body.level,
                "message": message,
                "source": (body.source or "webui"),
            }
        ],
        # 显式传目录：settings.log_dir 可在运行期被改（测试/重配），
        # 而 core 的前端 writer 是进程内单例，只有显式传目录才会跟着换
        log_dir=str(_log_dir()),
    )
    if written <= 0:
        raise HTTPException(status_code=500, detail="前端日志写入失败（见后端日志）")
    return ClientLogResponse(ok=True)
