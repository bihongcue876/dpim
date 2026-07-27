"""CLI 配置管理 — 环境变量 + 默认值。"""

import os

DEFAULTS = {
    "api_url": "http://localhost:8000",
    "format": "table",     # table | json | yaml
    "timeout": "30",
    "color": "on",
}


def get(key: str) -> str:
    """获取 CLI 配置，环境变量优先。"""
    env_map = {
        "api_url": "DPIM_API_URL",
        "format": "DPIM_FORMAT",
        "timeout": "DPIM_TIMEOUT",
        "color": "DPIM_COLOR",
    }
    env_key = env_map.get(key)
    if env_key:
        val = os.environ.get(env_key)
        if val is not None:
            return val
    return DEFAULTS.get(key, "")
