"""共享运行时状态 — AI 可用性封装"""

from __future__ import annotations

import threading


class AIState:
    """AI 可用性的线程安全封装。

    单例，所有模块通过 core.state.ai_state 访问。测试中可安全重置。
    """

    def __init__(self) -> None:
        self._available: bool = False
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        with self._lock:
            return self._available

    @available.setter
    def available(self, value: bool) -> None:
        with self._lock:
            self._available = value

    def set_available(self, value: bool) -> None:
        """线程安全地设置 AI 可用性状态。"""
        self.available = value

    def get_available(self) -> bool:
        """线程安全地获取 AI 可用性状态。"""
        return self.available


# 模块级单例
ai_state = AIState()


# 临时兼容：保留旧名称供逐步迁移
ai_available = ai_state.available
