"""共享运行时状态 — AI 可用性封装 + 状态校验密钥"""

from __future__ import annotations

import threading
import uuid


class AIState:
    """AI 可用性的线程安全封装。

    单例，所有模块通过 core.state.ai_state 访问。测试中可安全重置。

    v1.34：带**原因**——「未配置」（没有 AI，无 AI 模式的默认运行态）与
    「降级」（配好了但连不上）必须能区分，否则界面只能笼统说「AI 不可用」。
    """

    def __init__(self) -> None:
        self._available: bool = False
        self._reason: str = ""
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        with self._lock:
            return self._available

    @available.setter
    def available(self, value: bool) -> None:
        with self._lock:
            self._available = value
            if value:
                self._reason = ""

    @property
    def reason(self) -> str:
        """不可用原因（可用时为空串）。"""
        with self._lock:
            return self._reason

    def set_state(self, available: bool, reason: str = "") -> None:
        """原子设置「可用性 + 原因」（避免中间态被读到）。"""
        with self._lock:
            self._available = available
            self._reason = "" if available else reason


# 模块级单例
ai_state = AIState()


# ── 状态校验密钥 ──

class StateKey:
    """状态校验密钥：任何数据写入后自动刷新。

    前端提交修改时，先获取当前 key 与页面加载时的 key 比对。
    一致则提交成功并刷新 key；不一致则要求前端刷新数据。
    """

    def __init__(self) -> None:
        self._key: str = ""
        self._lock = threading.Lock()

    def refresh(self) -> str:
        """生成新 UUID 并返回。"""
        with self._lock:
            self._key = uuid.uuid4().hex
            return self._key

    def get(self) -> str:
        """获取当前密钥，首次调用自动初始化。"""
        with self._lock:
            if not self._key:
                self._key = uuid.uuid4().hex
            return self._key


state_key = StateKey()


def refresh_key() -> str:
    """快捷函数：刷新密钥，返回新值。"""
    return state_key.refresh()


def get_key() -> str:
    """快捷函数：获取当前密钥。"""
    return state_key.get()
