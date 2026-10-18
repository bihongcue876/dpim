"""密钥掩码与幂等保留 — 防止 API Key 明文经 GET /settings 下发。

约定：
- GET /settings 下发掩码值（如 `sk-****abcd`），绝不下发明文；
- PUT /settings 提交掩码值或空值 = 「保持原值不变」，提交其他非空值 = 替换。
"""

from __future__ import annotations

import re

_MASK_FILL = "****"
_TAIL_LEN = 4
_HEAD_LEN = 3
# 掩码形状：`xxx****xxxx`（头 3 + **** + 尾 4）或全掩码 `****`（短钥）
_MASK_SHAPE = re.compile(r"(?:.{3}\*{4}.{4}|\*{4})", re.S)


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


def looks_like_mask(value: str | None) -> bool:
    """提交值是否呈掩码形状（`xxx****xxxx` 或全掩码 `****`）。

    用于**永不把掩码当真钥落库**：真钥不含 `****` 这种填充串，而前端会把
    `GET /settings` 下发的掩码原样带回来（编辑/重命名/复制条目时尤甚）。
    """
    if not value:
        return False
    return _MASK_SHAPE.fullmatch(value) is not None


def resolve_secret(submitted: str | None, current: str) -> str:
    """解析 PUT 提交的密钥值：掩码/空 = 保留原值，其余 = 替换。

    - submitted 为 None（字段缺省）或空串 → current
    - submitted 等于 mask_secret(current)（前端原样回传掩码）→ current
    - submitted 只是「像掩码」但现值不同/为空（例：把 `sk-****abcd` 粘到新条目）→ current
    - 其他非空值 → submitted（用户主动更换密钥）
    """
    if not submitted:
        return current
    if submitted == mask_secret(current):
        return current
    if looks_like_mask(submitted):
        return current
    return submitted


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_secret(value: str) -> str:
    """清掉密钥/请求头值里的控制字符（含换行）。

    HTTP 头里放控制字符会让客户端**直接报错**，而报错正文会**原样回显整条头值**（含真钥）：
    实测 `api_key` 含换行时得到 `LocalProtocolError: Illegal header value b'…'`，
    这段原文会显示在卡片/概览台/顶栏，也会写进后端日志。
    """
    return _CONTROL_CHARS.sub("", str(value or ""))


def _secret_variants(secret: str) -> set[str]:
    """密钥在错误文本里的几种渲染形态（原文 / 转义后 / repr 形式）——h11 给的是转义形态。"""
    raw = str(secret or "")
    if not raw:
        return set()
    escaped = raw.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return {v for v in {raw, escaped, repr(raw)[1:-1]} if len(v) >= 4}


def scrub_secrets(text: str, *secrets: str) -> str:
    """把已知密钥从任意文本里擦掉——**交给界面或落盘之前**必须过这一道。

    为什么需要：异常原文可能带上请求头值（httpx / h11 的 `Illegal header value b'…'`
    就是原样回显），而这段原文会显示在卡片/概览台/顶栏，也会写进 `logs/backend-*.log`。
    """
    out = str(text)
    for secret in secrets:
        for variant in _secret_variants(secret):
            out = out.replace(variant, mask_secret(str(secret or "")))
    return out


def mask_provider_secret(entry: dict) -> dict:
    """掩码单个 provider 条目中的 api_key（返回浅拷贝，不改原 dict）。"""
    masked = dict(entry)
    if "api_key" in masked:
        masked["api_key"] = mask_secret(str(masked.get("api_key") or ""))
    return masked


def resolve_provider_secret(submitted: dict, current_entry: dict | None) -> dict:
    """解析 PUT 提交的 provider 条目：api_key 为掩码/空且有现值 → 保留。

    - 已有 provider：空/掩码 api_key 回退现值，避免前端回显掩码把真钥抹掉
    - 全新 provider（current_entry 为 None）：空 api_key 按空处理（本地服务无 key）；
      **掩码形状的值一律视为「未填」**——前端在重命名/复制条目时会把别处的掩码带过来，
      旧实现只比较 `mask_secret("")`（恒为空串）等于没拦，于是 `sk-****abcd`
      被当成真钥写进 dpim.json（AI 侧表现为 401，界面却显示「已设置」）。
    - **显式清空**（v1.35）：条目带 `clear_api_key: true` 时把 `api_key` 置空——
      「空串 = 保持现值」的幂等语义使已存密钥无法从前端清掉（只能删条目重建），
      清空必须由调用方显式声明；该标记本身**不入库**（解析后即弹出）。
    """
    entry = dict(submitted)
    clear = bool(entry.pop("clear_api_key", False))
    key = str(entry.get("api_key") or "")
    if clear:
        entry["api_key"] = ""
        return entry
    if current_entry is not None:
        entry["api_key"] = resolve_secret(key, str(current_entry.get("api_key") or ""))
    else:
        entry["api_key"] = "" if looks_like_mask(key) else key
    return entry
