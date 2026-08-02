"""提示词加载器 — 从 dpim/prompts/{role}.md 按需加载 system prompt。

角色与文件映射：
  cr   → core.md        中央控制 Agent
  in   → infomater.md   信息管理 Agent
  gr   → grapher.md     图对接 Agent
  meta → metacognition.md 元认知裁判

文件内容作为 system prompt 注入 LLM 调用，改文件即生效（按文件加载 + 缓存）。
具体提示词正文由使用者填写；当前骨架文件仅含结构说明与占位符。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

ROLE_FILES = {
    "cr": "core.md",
    "in": "infomater.md",
    "gr": "grapher.md",
    "meta": "metacognition.md",
}


class PromptLoader:
    def __init__(self, prompts_dir: Path | None = None) -> None:
        self.prompts_dir = prompts_dir or PROMPTS_DIR

    @lru_cache(maxsize=32)
    def load(self, role: str) -> str:
        """按角色读取提示词文件；文件缺失时返回最小骨架。"""
        filename = ROLE_FILES.get(role, f"{role}.md")
        path = self.prompts_dir / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return f"# {role} Agent\n\n（提示词骨架，待填写）\n"


prompt_loader = PromptLoader()
