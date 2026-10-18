"""本地日志端点测试（协议 v1.31）：`GET /logs`、`POST /logs/client`。

覆盖：默认通道与「可空=最新」日期解析、files 清单（kind 过滤 / 倒序 / mtime）、
tail 截断标记、level（大小写不敏感）与 keyword 过滤、中文错误信息（kind/tail/date）、
前端日志回传与 8000 字符截断，以及「读端点不刷新状态校验密钥」这条纪律。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.state import get_key
from interface import api, deps


def _line(ts: str, level: str, message: str, source: str = "core.test") -> str:
    return f"{ts} | {level:<7} | {source} | {message}"


@pytest.fixture
def logs_env(tmp_path, monkeypatch):
    """日志目录指向每个测试独立的 tmp；清空存储全局（日志端点不依赖库）。"""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "log_dir", str(log_dir))
    # 日志端点与存储无关：把共享状态清空，避免 write_commit 中间件碰到别的测试留下的库
    deps.db = None
    deps.event_store = None
    deps.graph_store = None
    deps.repos = None
    yield TestClient(api.app), log_dir


def _write(log_dir: Path, name: str, lines: list[str]) -> None:
    (log_dir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestLogsQuery:
    def test_default_kind_latest_day_and_file_list(self, logs_env):
        client, log_dir = logs_env
        _write(log_dir, "backend-2026-10-01.log",
               [_line("2026-10-01 10:00:00", "INFO", "旧的一天")])
        _write(log_dir, "backend-2026-10-02.log",
               [_line("2026-10-02 09:00:00", "INFO", "新的一天")])

        resp = client.get("/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "backend"
        assert data["date"] == "2026-10-02"  # date 可空 = 最新
        assert Path(data["dir"]).is_absolute()
        # files 是该通道全部日志，按日期倒序
        assert [f["name"] for f in data["files"]] == [
            "backend-2026-10-02.log", "backend-2026-10-01.log",
        ]
        assert all(f["kind"] == "backend" and f["date"] and f["size"] > 0 for f in data["files"])
        assert all(f["mtime"] > 0 for f in data["files"])
        assert len(data["lines"]) == 1 and "新的一天" in data["lines"][0]
        assert data["truncated"] is False

    def test_files_are_scoped_to_requested_kind(self, logs_env):
        client, log_dir = logs_env
        _write(log_dir, "backend-2026-10-02.log", [_line("2026-10-02 09:00:00", "INFO", "后端")])
        _write(log_dir, "frontend-2026-10-02.log", [_line("2026-10-02 09:01:00", "ERROR", "前端")])

        backend = client.get("/logs", params={"kind": "backend"}).json()
        assert [f["name"] for f in backend["files"]] == ["backend-2026-10-02.log"]
        frontend = client.get("/logs", params={"kind": "frontend"}).json()
        assert [f["name"] for f in frontend["files"]] == ["frontend-2026-10-02.log"]
        assert frontend["lines"] and "前端" in frontend["lines"][0]

    def test_date_selects_that_day(self, logs_env):
        client, log_dir = logs_env
        _write(log_dir, "backend-2026-10-01.log", [_line("2026-10-01 10:00:00", "INFO", "第一天")])
        _write(log_dir, "backend-2026-10-02.log", [_line("2026-10-02 10:00:00", "INFO", "第二天")])

        data = client.get("/logs", params={"date": "2026-10-01"}).json()
        assert data["date"] == "2026-10-01"
        assert len(data["lines"]) == 1 and "第一天" in data["lines"][0]
        # files 仍是该通道全部文件（供前端做日期下拉）
        assert len(data["files"]) == 2

    def test_tail_truncation_returns_newest_lines(self, logs_env):
        client, log_dir = logs_env
        _write(log_dir, "backend-2026-10-02.log", [
            _line(f"2026-10-02 10:0{i}:00", "INFO", f"第{i}条") for i in range(5)
        ])

        data = client.get("/logs", params={"tail": 2}).json()
        assert data["truncated"] is True
        assert [ln.split(" | ")[-1] for ln in data["lines"]] == ["第3条", "第4条"]

        full = client.get("/logs", params={"tail": 5}).json()
        assert full["truncated"] is False and len(full["lines"]) == 5

    def test_level_filter_is_case_insensitive(self, logs_env):
        client, log_dir = logs_env
        _write(log_dir, "backend-2026-10-02.log", [
            _line("2026-10-02 10:00:00", "ERROR", "出错了"),
            _line("2026-10-02 10:01:00", "WARNING", "警告"),
            _line("2026-10-02 10:02:00", "INFO", "正常"),
        ])

        lower = client.get("/logs", params={"level": "error"}).json()
        assert len(lower["lines"]) == 1 and "出错了" in lower["lines"][0]
        upper = client.get("/logs", params={"level": "WARNING"}).json()
        assert len(upper["lines"]) == 1 and "警告" in upper["lines"][0]

    def test_keyword_substring_filter(self, logs_env):
        client, log_dir = logs_env
        _write(log_dir, "backend-2026-10-02.log", [
            _line("2026-10-02 10:00:00", "INFO", "红石机关教程"),
            _line("2026-10-02 10:01:00", "INFO", "八段锦呼吸法"),
        ])

        data = client.get("/logs", params={"keyword": "红石"}).json()
        assert len(data["lines"]) == 1 and "红石" in data["lines"][0]

    def test_empty_log_dir_returns_empty_shape(self, logs_env):
        client, _log_dir = logs_env
        data = client.get("/logs").json()
        assert data["files"] == [] and data["lines"] == []
        assert data["date"] == "" and data["truncated"] is False
        assert Path(data["dir"]).is_absolute()


class TestLogsValidation:
    def test_invalid_kind_rejected_with_chinese_detail(self, logs_env):
        client, _log_dir = logs_env
        resp = client.get("/logs", params={"kind": "syslog"})
        assert resp.status_code == 400
        assert "kind 非法" in resp.json()["detail"]

    def test_tail_out_of_range_rejected(self, logs_env):
        client, _log_dir = logs_env
        for bad in (0, -3, 2001):
            resp = client.get("/logs", params={"tail": bad})
            assert resp.status_code == 400
            assert "tail 须在 1..2000 之间" in resp.json()["detail"]

    def test_invalid_date_format_rejected(self, logs_env):
        client, _log_dir = logs_env
        resp = client.get("/logs", params={"date": "2026/10/02"})
        assert resp.status_code == 400
        assert "date 格式非法" in resp.json()["detail"]


class TestClientLog:
    def test_client_log_lands_in_frontend_file(self, logs_env):
        client, log_dir = logs_env
        resp = client.post(
            "/logs/client",
            json={"level": "error", "message": "前端报错啦", "source": "unit-test"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        data = client.get("/logs", params={"kind": "frontend"}).json()
        assert data["kind"] == "frontend"
        assert len(data["lines"]) == 1
        line = data["lines"][0]
        assert "前端报错啦" in line and "ERROR" in line and "unit-test" in line
        # 落到 frontend-YYYY-MM-DD.log（按天轮转），不写 backend 文件
        assert data["files"][0]["name"].startswith("frontend-")
        assert list(log_dir.glob("backend-*.log")) == []

    def test_client_log_message_truncated_to_8000(self, logs_env):
        client, _log_dir = logs_env
        resp = client.post(
            "/logs/client", json={"level": "debug", "message": "x" * 9000}
        )
        assert resp.status_code == 200
        line = client.get("/logs", params={"kind": "frontend"}).json()["lines"][0]
        assert len(line.split(" | ")[-1]) == 8000

    def test_client_log_source_defaults_and_blank_message_rejected(self, logs_env):
        client, _log_dir = logs_env
        assert client.post(
            "/logs/client", json={"level": "info", "message": "有内容"}
        ).status_code == 200
        line = client.get("/logs", params={"kind": "frontend"}).json()["lines"][0]
        assert "webui" in line  # source 缺省 = webui

        blank = client.post("/logs/client", json={"level": "info", "message": "   "})
        assert blank.status_code == 400
        assert "message 不能为空" in blank.json()["detail"]

    def test_client_log_invalid_level_rejected(self, logs_env):
        client, _log_dir = logs_env
        resp = client.post("/logs/client", json={"level": "fatal", "message": "x"})
        assert resp.status_code == 422  # Literal 枚举校验


class TestReadEndpointsDoNotRefreshKey:
    def test_get_logs_keeps_state_hash(self, logs_env):
        """读端点不得触发状态校验密钥刷新。"""
        client, log_dir = logs_env
        _write(log_dir, "backend-2026-10-02.log", [_line("2026-10-02 09:00:00", "INFO", "x")])
        before = get_key()
        assert client.get("/logs").status_code == 200
        assert client.get("/logs", params={"keyword": "x"}).status_code == 200
        assert get_key() == before


class TestClientLogDoesNotRefreshKey:
    """日志上报是旁路而非数据写入：`write_commit` 显式豁免，不刷状态密钥。"""

    @pytest.fixture
    def state_env(self, db, event_store, graph_store, tmp_path, monkeypatch):
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "log_dir", str(log_dir))
        deps.db = db
        deps.event_store = event_store
        deps.graph_store = graph_store
        deps.repos = None
        yield TestClient(api.app), log_dir

    def test_client_log_keeps_state_hash_while_real_write_changes_it(self, state_env):
        client, _log_dir = state_env
        before = client.get("/state-hash").json()["hash"]

        resp = client.post(
            "/logs/client", json={"level": "error", "message": "前端上报一条"}
        )
        assert resp.status_code == 200 and resp.json() == {"ok": True}
        # 豁免生效：日志上报不改状态密钥（否则前端每次上报都会让密钥变成噪声）
        assert client.get("/state-hash").json()["hash"] == before

        # 对照：真写端点（POST /ingest）确实刷新状态密钥
        assert client.post(
            "/ingest", json={"content": "真实写入的事件", "event_type": "data"}
        ).status_code == 200
        assert client.get("/state-hash").json()["hash"] != before
