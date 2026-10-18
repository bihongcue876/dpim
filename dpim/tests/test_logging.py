"""本地日志系统测试：前后端分文件、按天命名、保留期清理、读取过滤。

覆盖 `core/logging_setup.py` 的落盘纪律；不覆盖 REST 端点（前端日志送入端点随
契约 v1.30 一起加，见 P5）。
"""

import logging
from datetime import datetime, timedelta

import pytest

from core.logging_setup import (
    BACKEND,
    FRONTEND,
    DailyFileHandler,
    list_log_files,
    parse_log_name,
    prune_old_logs,
    read_log_lines,
    setup_file_logging,
    write_frontend_log,
)

TODAY = datetime.now().strftime("%Y-%m-%d")


@pytest.fixture
def log_dir(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture
def clean_root_handlers():
    """记录并回收本测试新加的 root handler，避免污染后续测试。"""
    root = logging.getLogger()
    before = list(root.handlers)
    yield
    for handler in list(root.handlers):
        if handler not in before:
            root.removeHandler(handler)
            handler.close()


def _record(message: str, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord("t", level, __file__, 1, message, None, None)


class TestDailyFileHandler:
    def test_writes_to_dated_file(self, log_dir):
        handler = DailyFileHandler(log_dir, BACKEND)
        handler.setFormatter(logging.Formatter("%(levelname)s|%(message)s"))
        handler.emit(_record("hello"))
        handler.close()
        target = log_dir / f"backend-{TODAY}.log"
        assert target.exists()
        assert "hello" in target.read_text(encoding="utf-8")

    def test_current_path_matches_today(self, log_dir):
        handler = DailyFileHandler(log_dir, FRONTEND)
        assert handler.current_path.name == f"frontend-{TODAY}.log"

    def test_appends_instead_of_truncating(self, log_dir):
        handler = DailyFileHandler(log_dir, BACKEND)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(_record("first"))
        handler.emit(_record("second"))
        handler.close()
        text = (log_dir / f"backend-{TODAY}.log").read_text(encoding="utf-8")
        assert text.splitlines() == ["first", "second"]

    def test_jsonl_variant_uses_jsonl_ext(self, log_dir):
        handler = DailyFileHandler(log_dir, BACKEND, jsonl=True)
        handler.emit(_record("j"))
        handler.close()
        target = log_dir / f"backend-{TODAY}.jsonl"
        assert target.exists()
        assert '"message": "j"' in target.read_text(encoding="utf-8")

    def test_frontend_and_backend_are_separate_files(self, log_dir):
        write_frontend_log(
            [{"level": "error", "message": "前端崩了", "source": "webui"}],
            log_dir=log_dir,
        )
        assert (log_dir / f"frontend-{TODAY}.log").exists()
        assert not (log_dir / f"backend-{TODAY}.log").exists()


class TestParseAndPrune:
    def test_parse_log_name(self):
        assert parse_log_name("backend-2026-10-03.log") == ("backend", "2026-10-03")
        assert parse_log_name("frontend-2026-10-03.jsonl") == ("frontend", "2026-10-03")
        assert parse_log_name("random.txt") is None
        assert parse_log_name("backend-not-a-day.log") is None

    def test_prune_removes_only_expired(self, log_dir):
        old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        recent = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        for name in (
            f"backend-{old}.log",
            f"frontend-{old}.log",
            f"backend-{recent}.log",
            "unrelated.txt",
        ):
            (log_dir / name).write_text("x", encoding="utf-8")
        assert prune_old_logs(log_dir, retention_days=14) == 2
        assert (log_dir / f"backend-{recent}.log").exists()
        assert (log_dir / "unrelated.txt").exists()

    def test_prune_disabled_when_zero(self, log_dir):
        old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        (log_dir / f"backend-{old}.log").write_text("x", encoding="utf-8")
        assert prune_old_logs(log_dir, retention_days=0) == 0
        assert (log_dir / f"backend-{old}.log").exists()


class TestReadAndList:
    def test_list_files_newest_first(self, log_dir):
        (log_dir / "backend-2026-10-01.log").write_text("a\n", encoding="utf-8")
        (log_dir / "backend-2026-10-03.log").write_text("b\n", encoding="utf-8")
        assert [f["day"] for f in list_log_files(log_dir)] == ["2026-10-03", "2026-10-01"]

    def test_read_tail_and_filter(self, log_dir):
        (log_dir / f"backend-{TODAY}.log").write_text(
            "2026-10-03 10:00:00 | INFO    | core.a | first\n"
            "2026-10-03 10:00:01 | WARNING | core.b | second\n"
            "2026-10-03 10:00:02 | ERROR   | core.c | third\n",
            encoding="utf-8",
        )
        assert read_log_lines(stream=BACKEND, limit=1, log_dir=log_dir) == [
            "2026-10-03 10:00:02 | ERROR   | core.c | third"
        ]
        assert read_log_lines(stream=BACKEND, level="WARNING", log_dir=log_dir) == [
            "2026-10-03 10:00:01 | WARNING | core.b | second"
        ]
        assert read_log_lines(stream=BACKEND, keyword="third", log_dir=log_dir) == [
            "2026-10-03 10:00:02 | ERROR   | core.c | third"
        ]

    def test_frontend_stream_isolated(self, log_dir):
        write_frontend_log([{"level": "info", "message": "前端一行"}], log_dir=log_dir)
        lines = read_log_lines(stream=FRONTEND, log_dir=log_dir)
        assert len(lines) == 1 and "前端一行" in lines[0]
        assert read_log_lines(stream=BACKEND, log_dir=log_dir) == []

    def test_write_frontend_log_skips_bad_entry(self, log_dir):
        written = write_frontend_log(
            [{"message": "ok"}, {"message": None}, {"level": "warn"}], log_dir=log_dir
        )
        assert written == 3  # 缺失字段按默认补齐，不因单条异常中断

    def test_read_missing_dir_returns_empty(self, tmp_path):
        assert read_log_lines(stream=BACKEND, log_dir=tmp_path / "nope") == []
        assert list_log_files(tmp_path / "nope") == []


class TestSetup:
    def test_setup_lands_records_in_backend_file(self, log_dir, clean_root_handlers):
        setup_file_logging(log_dir=log_dir, level="INFO", retention_days=0, force=True)
        logging.getLogger("core.probe").info("setup 探针")
        for handler in logging.getLogger().handlers:
            handler.flush()
        text = (log_dir / f"backend-{TODAY}.log").read_text(encoding="utf-8")
        assert "setup 探针" in text
        assert "日志系统就绪" in text  # 自描述：日志里能直接看到目录与保留期

    def test_setup_idempotent_without_force(self, log_dir, clean_root_handlers):
        setup_file_logging(log_dir=log_dir, retention_days=0, force=True)
        before = len(logging.getLogger().handlers)
        setup_file_logging(log_dir=log_dir, retention_days=0)
        assert len(logging.getLogger().handlers) == before

    def test_setup_prunes_on_start(self, log_dir, clean_root_handlers):
        old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        stale = log_dir / f"backend-{old}.log"
        stale.write_text("x", encoding="utf-8")
        setup_file_logging(log_dir=log_dir, retention_days=7, force=True)
        assert not stale.exists()
