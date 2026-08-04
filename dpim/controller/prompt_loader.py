"""提示词加载器 — 从 dpim/prompts/{role}.md 按需加载 system prompt。

角色与文件映射：
  cr   → core.md        中央控制 Agent
  in   → infomater.md   信息管理 Agent
  gr   → grapher.md     图对接 Agent
  meta → metacognition.md 元认知裁判

文件内容作为 system prompt 注入 LLM 调用，改文件即生效（mtime 缓存：文件修改后
自动重新读取，无需重启）。
"""

from __future__ import annotations

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
        self._cache: dict[str, tuple[float, str]] = {}

    def load(self, role: str) -> str:
        """按角色读取提示词文件；文件缺失时返回最小骨架。

        按文件 mtime 缓存：提示词文件被修改后，下次调用自动加载新内容。
        """
        filename = ROLE_FILES.get(role, f"{role}.md")
        path = self.prompts_dir / filename
        if path.exists():
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            cached = self._cache.get(role)
            if cached is not None and cached[0] == mtime:
                return cached[1]
            content = path.read_text(encoding="utf-8")
            self._cache[role] = (mtime, content)
            return content
        return f"# {role} Agent\n\n（提示词骨架，待填写）\n"


prompt_loader = PromptLoader()
