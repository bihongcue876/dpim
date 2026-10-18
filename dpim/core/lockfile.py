"""单实例锁：同一库同时只允许一个写进程。

用 **OS 级文件锁**（Windows `msvcrt.locking` / POSIX `fcntl.flock`）：

- 非阻塞获取，拿不到即说明已有实例在写；
- 进程退出（含被 kill / 断电）时由内核自动释放，**不会留下陈旧锁**——
  这也是不用「写 pid 文件 + 探活」方案的原因（pid 复用与探活在 Windows 上不可靠）。

为什么需要：`graph.json` 是整文件读改写，两个进程同时写会「后写者覆盖先写者」
（丢更新）；SQLite 侧也会撞忙等待超时。此前「写者串行」只在单个 asyncio 循环内成立，
跨进程是**假设**而非约束。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class LockError(RuntimeError):
    """锁被其它实例持有。"""


class SingleInstanceLock:
    """基于 OS 文件锁的单实例锁（可作上下文管理器）。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._fh = None

    def acquire(self) -> bool:
        """尝试非阻塞获取；成功返回 True，已被占用返回 False。"""
        if self._fh is not None:
            return True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(self.path, "a+", encoding="utf-8")
        except OSError as exc:
            logger.warning("锁文件无法打开（%s），跳过跨进程互斥: %s", self.path, exc)
            return True  # 打不开锁文件不应阻断启动（例如只读目录）
        try:
            self._lock(fh)
        except OSError:
            fh.close()
            return False
        try:
            fh.seek(0)
            fh.truncate()
            fh.write(f"{os.getpid()}\n")
            fh.flush()
        except OSError:
            pass  # 写 pid 只是给人看的提示，失败不影响锁本身
        self._fh = fh
        return True

    def release(self) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            self._unlock(fh)
        except OSError:
            pass
        finally:
            try:
                fh.close()
            except OSError:
                pass

    def acquire_or_raise(self, *, what: str = "库") -> None:
        if not self.acquire():
            owner = ""
            try:
                owner = self.path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
            raise LockError(
                f"{what}正被另一个进程写入（锁文件 {self.path}"
                + (f"，持有者 pid={owner}" if owner else "")
                + "）。同一库同时只允许一个写进程：请先停掉另一个实例，"
                "或用 REST 客户端（dpimCLI / WebUI）而不是直连存储。"
            )

    def __enter__(self) -> SingleInstanceLock:
        self.acquire_or_raise()
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()

    # ── 平台差异封装 ──
    @staticmethod
    def _lock(fh) -> None:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(fh) -> None:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
