"""密钥掩码与幂等保留 — 防止 API Key 明文经 GET /settings 下发。

约定：
- GET /settings 下发掩码值（如 `sk-****abcd`），绝不下发明文；
- PUT /settings 提交掩码值或空值 = 「保持原值不变」，提交其他非空值 = 替换。
"""

from __future__ import annotations

_MASK_FILL = "****"
_TAIL_LEN = 4
_HEAD_LEN = 3


def mask_secret(secret: str) -> str:
    """掩码密钥：`sk-****abcd`（头 3 + **** + 尾 4）。

    空串返回空串（未配置密钥无掩码必要）；短密钥（≤ HEAD 3 + TAIL 4 = 7 字符）
    全掩码，避免头尾拼起来几乎还原原文。
    """
    if not secret:
        return ""
    if len(secret) <= _HEAD_LEN + _TAIL_LEN:
        return _MASK_FILL
    return f"{secret[:_HEAD_LEN]}{_MASK_FILL}{secret[-_TAIL_LEN:]}"


def resolve_secret(submitted: str | None, current: str) -> str:
    """解析 PUT 提交的密钥值：掩码/空 = 保留原值，其余 = 替换。

    - submitted 为 None（字段缺省）或空串 → current
    - submitted 等于 mask_secret(current)（前端原样回传掩码）→ current
    - 其他非空值 → submitted（用户主动更换密钥）
    """
    if not submitted:
        return current
    if submitted == mask_secret(current):
        return current
    return submitted


def mask_provider_secret(entry: dict) -> dict:
    """掩码单个 provider 条目中的 api_key（返回浅拷贝，不改原 dict）。"""
    masked = dict(entry)
    if "api_key" in masked:
        masked["api_key"] = mask_secret(str(masked.get("api_key") or ""))
    return masked


def resolve_provider_secret(submitted: dict, current_entry: dict | None) -> dict:
    """解析 PUT 提交的 provider 条目：api_key 为掩码/空且有现值 → 保留。

    - 条目为全新 provider（current_entry 为 None）：空 api_key 按空处理（本地服务无 key）
    - 已有 provider：空/掩码 api_key 回退现值，避免前端回显掩码把真钥抹掉
    """
    entry = dict(submitted)
    key = str(entry.get("api_key") or "")
    if current_entry is not None:
        entry["api_key"] = resolve_secret(key, str(current_entry.get("api_key") or ""))
    else:
        entry["api_key"] = "" if key == mask_secret("") else key
    return entry
