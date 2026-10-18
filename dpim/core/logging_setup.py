"""本地日志系统：前端与后端分文件、按天轮转、保留期清理。

设计要点（对齐「能在本地翻看日志」的诉求）：

1. **前后端分开**：后端 root logger 落 `backend-YYYY-MM-DD.log`；前端日志走专用通道落
   `frontend-YYYY-MM-DD.log`（浏览器经 `POST /logs/client` 送入，见 `write_frontend_log`）。
2. **文件名带日期**：今天的日志就是今天那一份，不依赖进程启动时刻。
3. **日志是旁路**：写失败只记 stderr，绝不阻断业务。
4. **保留期清理只在启动时做一次**，不挂在写路径上。
5. **敏感值不入日志**：密钥掩码由 `core/security.py` 保证，本模块只负责落盘纪律。
"""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

from core.config import settings

BACKEND = "backend"
FRONTEND = "frontend"
STREAMS = (BACKEND, FRONTEND)

_TEXT_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_TEXT_DATEFMT = "%Y-%m-%d %H:%M:%S"

# 噪声较大的第三方 logger：文件里压到 WARNING，避免淹没业务流水
_NOISY_LOGGERS = ("httpx", "httpcore", "aiosqlite", "asyncio", "urllib3", "multipart")

_NAME_RE = re.compile(r"^(?P<stream>[a-z]+)-(?P<day>\d{4}-\d{2}-\d{2})\.(?P<ext>log|jsonl)$")

# 前端日志单条上限（v1.31 对齐 `POST /logs/client` 契约：message ≤ 8000 字符，超出截断）
MAX_FRONTEND_MESSAGE = 8000
MAX_FRONTEND_SOURCE = 40

logger = logging.getLogger(__name__)


class DailyFileHandler(logging.Handler):
    """按日期切换文件的 handler：跨天自动切到新文件。"""

    def __init__(
        self,
        log_dir: str | Path,
        stream: str = BACKEND,
        *,
        jsonl: bool = False,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__()
        self.log_dir = Path(log_dir)
        self.stream = stream
        self.jsonl = jsonl
        self.encoding = encoding
        self._day = ""
        self._fh = None

    def path_for_day(self, day: str) -> Path:
        ext = ".jsonl" if self.jsonl else ".log"
        return self.log_dir / f"{self.stream}-{day}{ext}"

    @property
    def current_path(self) -> Path:
        return self.path_for_day(self._day or datetime.now().strftime("%Y-%m-%d"))

    def _file(self):
        day = datetime.now().strftime("%Y-%m-%d")
        if self._fh is not None and day == self._day:
            return self._fh
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path_for_day(day), "a", encoding=self.encoding)
        self._day = day
        return self._fh

    def write_line(self, line: str) -> None:
        """直接写入一行（前端日志通道用，绕过 logging 记录结构）。"""
        fh = self._file()
        fh.write(line + "\n")
        fh.flush()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.jsonl:
                line = json.dumps(self._as_dict(record), ensure_ascii=False)
            else:
                line = self.format(record)
            self.write_line(line)
        except Exception:
            self.handleError(record)

    @staticmethod
    def _as_dict(record: logging.LogRecord) -> dict:
        return {
            "time": datetime.fromtimestamp(record.created).strftime(_TEXT_DATEFMT),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

    def close(self) -> None:
        try:
            if self._fh is not None:
                self._fh.close()
        finally:
            self._fh = None
            super().close()


def parse_log_name(name: str) -> tuple[str, str] | None:
    """解析日志文件名 → (stream, day)；不匹配返回 None。"""
    m = _NAME_RE.match(name)
    if not m:
        return None
    return m.group("stream"), m.group("day")


def prune_old_logs(
    log_dir: str | Path | None = None,
    retention_days: int | None = None,
    *,
    streams: tuple[str, ...] = STREAMS,
) -> int:
    """删除超过保留期的日志文件，返回删除数（0 天 = 不清理）。失败只告警。"""
    days = settings.log_retention_days if retention_days is None else retention_days
    if days <= 0:
        return 0
    target = Path(log_dir or settings.log_dir)
    if not target.is_dir():
        return 0
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    removed = 0
    for item in target.iterdir():
        if not item.is_file():
            continue
        parsed = parse_log_name(item.name)
        if parsed is None or parsed[0] not in streams:
            continue
        if parsed[1] >= cutoff:  # 文件名日期为 ISO 格式，字符串比较即时间比较
            continue
        try:
            item.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("旧日志清理失败（不影响运行）: %s (%s)", item.name, exc)
    return removed


_configured: set[str] = set()


def setup_file_logging(
    *,
    stream: str = BACKEND,
    log_dir: str | Path | None = None,
    level: str | None = None,
    retention_days: int | None = None,
    jsonl: bool | None = None,
    force: bool = False,
) -> Path:
    """挂载文件日志 handler（幂等）。返回日志目录。

    只挂文件 handler：控制台输出保持 uvicorn/原有行为不变。
    root 默认 WARNING 会挡掉 INFO，因此这里把 root 放宽到文件级别，
    再把噪声第三方 logger 单独压回 WARNING。
    """
    target = Path(log_dir or settings.log_dir)
    if stream in _configured and not force:
        return target
    level_name = str(level or settings.log_level or "INFO").upper()
    lvl = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    text_handler = DailyFileHandler(target, stream)
    text_handler.setFormatter(logging.Formatter(_TEXT_FORMAT, _TEXT_DATEFMT))
    text_handler.setLevel(lvl)
    root.addHandler(text_handler)

    if settings.log_jsonl if jsonl is None else jsonl:
        jsonl_handler = DailyFileHandler(target, stream, jsonl=True)
        jsonl_handler.setLevel(lvl)
        root.addHandler(jsonl_handler)

    if root.level == logging.NOTSET or root.level > lvl:
        root.setLevel(lvl)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(lvl, logging.WARNING))

    days = settings.log_retention_days if retention_days is None else retention_days
    # 当天日志是否首次建立：决定横幅用 INFO（每天一条）还是 DEBUG——CLI 每次调用
    # 都是新进程，若一律 INFO 会把同一行横幅反复刷进日志
    fresh = not text_handler.path_for_day(datetime.now().strftime("%Y-%m-%d")).exists()
    removed = prune_old_logs(target, days)
    _configured.add(stream)
    logger.log(
        logging.INFO if fresh else logging.DEBUG,
        "日志系统就绪：通道=%s 目录=%s 级别=%s 保留=%s 天 清理旧文件=%d 个",
        stream, target, level_name, days, removed,
    )
    return target


_frontend_handler: DailyFileHandler | None = None


def _frontend_writer(log_dir: str | Path | None = None) -> DailyFileHandler:
    """前端日志 writer（进程内单例；显式换目录时重建）。"""
    global _frontend_handler
    target = Path(log_dir or settings.log_dir)
    if _frontend_handler is None:
        _frontend_handler = DailyFileHandler(target, FRONTEND)
    elif log_dir is not None and _frontend_handler.log_dir != target:
        _frontend_handler.close()
        _frontend_handler = DailyFileHandler(target, FRONTEND)
    return _frontend_handler


def write_frontend_log(entries: list[dict], *, log_dir: str | Path | None = None) -> int:
    """把前端送来的日志条目写入 `frontend-YYYY-MM-DD.log`，返回写入条数。

    条目形如 `{level, message, ts?, source?}`；字段缺失按默认补齐，
    单条异常只跳过该条，绝不因日志失败影响接口。
    `message` 超 `MAX_FRONTEND_MESSAGE` 字符截断（对齐 `POST /logs/client` 契约）。
    """
    writer = _frontend_writer(log_dir)
    written = 0
    for entry in entries:
        try:
            level = str(entry.get("level") or "INFO").upper()[:7]
            ts = str(entry.get("ts") or datetime.now().strftime(_TEXT_DATEFMT))[:19]
            source = str(entry.get("source") or "webui")[:MAX_FRONTEND_SOURCE]
            message = (
                str(entry.get("message") or "")[:MAX_FRONTEND_MESSAGE].replace("\n", " ")
            )
            writer.write_line(f"{ts} | {level:<7} | {source} | {message}")
            written += 1
        except Exception:  # 日志永不阻断业务
            continue
    return written


def list_log_files(log_dir: str | Path | None = None) -> list[dict]:
    """列出日志文件（新到旧）：`{name, stream, day, size, mtime, path}`。"""
    target = Path(log_dir or settings.log_dir)
    if not target.is_dir():
        return []
    out: list[dict] = []
    for item in target.iterdir():
        if not item.is_file():
            continue
        parsed = parse_log_name(item.name)
        if parsed is None:
            continue
        try:
            stat = item.stat()
            size = stat.st_size
            mtime = stat.st_mtime
        except OSError:
            size = 0
            mtime = 0.0
        out.append(
            {
                "name": item.name,
                "stream": parsed[0],
                "day": parsed[1],
                "size": size,
                "mtime": mtime,
                "path": str(item),
            }
        )
    out.sort(key=lambda x: (x["day"], x["name"]), reverse=True)
    return out


def read_log_lines(
    *,
    stream: str = BACKEND,
    day: str | None = None,
    level: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
    log_dir: str | Path | None = None,
) -> list[str]:
    """读取日志**尾部**若干行，支持级别/关键词过滤（新到旧取文件，文件内保序）。

    实验规模下日志文件很小，直接整读后过滤再取尾；不做分页倒读。
    """
    files = [
        f
        for f in list_log_files(log_dir)
        if (stream == "all" or f["stream"] == stream)
        and (day is None or f["day"] == day)
        and f["name"].endswith(".log")
    ]
    if not files:
        return []
    needle = (keyword or "").lower()
    wanted = (level or "").upper()
    tail: deque[str] = deque(maxlen=max(1, limit))
    for info in reversed(files):  # 旧 → 新，保证尾部是全局最新
        try:
            with open(info["path"], encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    line = raw.rstrip("\n")
                    if wanted and f"| {wanted}" not in line.upper():
                        continue
                    if needle and needle not in line.lower():
                        continue
                    tail.append(line)
        except OSError as exc:
            logger.warning("日志读取失败: %s (%s)", info["name"], exc)
    return list(tail)
