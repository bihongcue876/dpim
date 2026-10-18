"""原子写与备份（Windows 加固）——基层存储纪律，供登记表/图层等 JSON 落盘复用。

三条纪律（对齐言明通（YMT）项目 `core/store/atomic.py` 的踩坑经验）：

1. **临时名带 pid**：固定 `X.tmp` 会撞上用户/其它进程的同名文件，改名用 `<name>.<pid>.tmp`。
2. **写完 fsync 再 rename**：只 rename 不刷盘，断电/崩溃可能留下「已就位但内容为空」的文件。
3. **`os.replace` 遇 Windows 共享冲突要退避重试**：杀毒/索引器/编辑器短暂占用会抛
   `PermissionError`（WinError 5），重试三次（0.05/0.1/0.2s）后仍失败则原样抛出——
   失败必须可见，绝不静默吞掉（fail-closed 语义不变）。
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_REPLACE_RETRIES = 3
_REPLACE_BACKOFF = (0.05, 0.1, 0.2)


def _unlink_quiet(path: str | Path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _replace_with_retry(src: str, dst: Path) -> None:
    """`os.replace` + Windows 共享冲突退避重试（最后一次失败原样抛出）。"""
    last: OSError | None = None
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:  # Windows: WinError 5（拒绝访问）/ 32（占用）
            last = exc
            if attempt < _REPLACE_RETRIES - 1:
                time.sleep(_REPLACE_BACKOFF[attempt])
    assert last is not None
    logger.warning("原子替换失败（已重试 %d 次）: %s", _REPLACE_RETRIES, last)
    raise last


def atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> None:
    """原子写文本文件：pid 临时名 → fsync → replace（带重试）。失败不留残file。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode(encoding)
    fd, tmp = tempfile.mkstemp(suffix=f".{os.getpid()}.tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        _replace_with_retry(tmp, target)
    except Exception:
        _unlink_quiet(tmp)
        raise


# 备份代数：`<name>.bak.1` 最新，依次 `.2`/`.3` 更旧
BACKUP_GENERATIONS = 3


def backup_file(path: str | Path, *, generations: int = BACKUP_GENERATIONS) -> bool:
    """留存多代备份：`<name>.bak.1` 最新，`.2`/`.3` 更旧。返回是否成功。

    **必须在覆盖主文件之前调用**，否则备份到的是刚写的新内容（等于没有上一代）——
    这正是旧实现的失效点：`save()` 先原子写再备份，`.bak` 只是当前文件的副本。
    失败只告警不阻断主流程。
    """
    src = Path(path)
    if not src.exists():
        return False
    try:
        for gen in range(generations, 1, -1):
            older = src.with_name(f"{src.name}.bak.{gen}")
            newer = src.with_name(f"{src.name}.bak.{gen - 1}")
            if newer.exists():
                os.replace(newer, older)
        shutil.copy2(src, src.with_name(f"{src.name}.bak.1"))
        return True
    except OSError as exc:
        logger.warning("备份 %s 失败（不影响运行）: %s", src.name, exc)
        return False


def backup_candidates(path: str | Path, *, generations: int = BACKUP_GENERATIONS) -> list[Path]:
    """可用的备份候选（新一代优先；兼容旧的单代 `<name>.bak`）。"""
    src = Path(path)
    candidates = [src.with_name(f"{src.name}.bak.{i}") for i in range(1, generations + 1)]
    candidates.append(src.with_name(src.name + ".bak"))  # 旧命名兼容
    return [item for item in candidates if item.exists()]
