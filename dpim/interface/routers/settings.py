"""配置与健康 router：`/settings`、`/settings/models`、`/health`。"""

from pathlib import Path
from time import time

from fastapi import APIRouter, HTTPException, Request

from core.config import ProviderConfig, normalize_format, settings
from core.llm import probe_models
from core.maintenance import list_backups
from core.models import (
    HealthResponse,
    ProviderModelsRequest,
    ProviderModelsResponse,
    SettingsResponse,
    SettingsUpdateRequest,
)
from core.security import (
    mask_provider_secret,
    resolve_provider_secret,
    scrub_secrets,
)
from core.state import ai_state
from interface import deps
from interface.deps import _database, _ok, _stores

router = APIRouter()

# v1.34 移除的「主配置」字段。旧界面（浏览器缓存的旧包）仍会提交它们——
# **明确报错，不静默丢弃**：静默丢弃会让旧界面显示「配置已保存」而实际什么都没改，
# 用户看到的现象正是「以前能配、现在怎么都不生效」。
_REMOVED_LLM_FIELDS = (
    "llm_base_url",
    "llm_api_key",
    "llm_model_name",
    "llm_timeout",
    "llm_max_tokens",
    "llm_enable_thinking",
    "llm_thinking_budget",
)
_REMOVED_LLM_HINT = (
    "该字段已在 v1.34 移除：AI 身份（地址 / 密钥 / 模型）只存在于 providers 条目里。"
    "请强制刷新页面（Ctrl+F5）后改用「模型与提供商」保存"
)


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """下发配置 — 提供商密钥一律掩码（`xxx****xxxx`），绝不明文出网。

    v1.34：AI 身份只在 `providers` 里；未配置状态由 `llm_configured` +
    `llm_unavailable_reason` 如实给出（不再有 primary 主配置字段）。
    v1.36：可配置项按字段名从 `settings` 自动取值（新增配置项忘接线 = 不再可能），
    并下发 `config_sources` / `config_file` / `log_dir`——前端要能"穿透"看到
    每一项的值来自 env 还是 dpim.json，以及配置到底写在哪个文件里。
    """
    data: dict = {
        name: getattr(settings, name)
        for name in SettingsResponse.model_fields
        if hasattr(settings, name)
    }
    data.update(
        available_providers=list(settings.providers.keys()),
        providers={
            name: mask_provider_secret(entry)
            for name, entry in settings.providers.items()
        },
        available_models=settings.available_models(),
        llm_configured=settings.llm_configured,
        llm_unavailable_reason=settings.llm_config_error(),
        config_sources=settings.config_sources,
    )
    return SettingsResponse(**data)


@router.post("/settings/models", response_model=ProviderModelsResponse)
async def probe_provider_models(body: ProviderModelsRequest):
    """探测提供商的可用模型列表（v1.34；v1.43 按接口格式分流）。

    - 已登记条目：传 `provider` 名，地址/密钥取该条目（`api_key` 留空 = 用已存密钥）
    - 新条目（保存前先试）：传 `base_url` + `api_key`（+ 可选 `format`）
    - **按格式走**：`anthropic` 用 `x-api-key` / `anthropic-version` 头打 `{base}/models`；
      `openai` / `responses` / `custom` 用 Bearer（额外请求头也带上）
    - **失败不抛异常**：把服务端/网络错误原文放进 `error`（界面必须看得见失败原因）
    """
    entry = settings.providers.get(body.provider) if body.provider else None
    base_url = (body.base_url or str((entry or {}).get("base_url") or "")).strip()
    api_key = body.api_key.strip() or str((entry or {}).get("api_key") or "")
    if not base_url:
        return ProviderModelsResponse(error="未填模型地址（base_url）")
    # v1.45：api_path / extra_headers 同样**请求体优先**——前端卡片的「拉取模型」用草稿值探测，
    # 而草稿里的条目后端还没保存（此前只发名字 → 一律「未填模型地址」；自定义格式还会因缺
    # 额外请求头而 401）。已保存条目仍可只传名字（回落到条目里的值）。
    api_path = (body.api_path or str((entry or {}).get("api_path") or "")).strip()
    headers = body.extra_headers
    if headers is None:
        stored = (entry or {}).get("extra_headers")
        headers = stored if isinstance(stored, dict) else None
    conf = ProviderConfig(
        name=body.provider or "(未保存)",
        base_url=base_url,
        api_key=api_key,
        model="",
        timeout=min(settings.health_check_timeout, 60),
        # 格式：请求体优先（弹窗里刚选的）→ 已登记条目 → openai
        format=normalize_format(body.format or (entry or {}).get("format") or "openai"),
        api_path=api_path,
        extra_headers={str(k): str(v) for k, v in headers.items()} if headers else None,
    )
    started = time()
    try:
        models = await probe_models(conf)
    except Exception as e:
        # v1.46：原文**先擦掉已知密钥**再交给界面——httpx/h11 的报错会回显整条请求头值
        # （实测 `api_key='sk-abc\nSECRET'` → `Illegal header value b'sk-abc\nSECRET'`）
        detail = scrub_secrets(
            f"{type(e).__name__}: {e}",
            api_key,
            *(conf.extra_headers or {}).values(),
        )[:400]
        return ProviderModelsResponse(error=detail, elapsed_ms=int((time() - started) * 1000))
    return ProviderModelsResponse(models=models, elapsed_ms=int((time() - started) * 1000))


@router.put("/settings")
async def update_settings(body: SettingsUpdateRequest, request: Request):
    raw = {}
    try:
        parsed = await request.json()
        if isinstance(parsed, dict):
            raw = parsed
    except Exception:  # 非法 JSON 交给 FastAPI 的既有校验路径
        raw = {}
    removed = [f for f in _REMOVED_LLM_FIELDS if f in raw]
    if removed:
        raise HTTPException(
            status_code=422,
            detail=[
                {"loc": ["body", f], "msg": _REMOVED_LLM_HINT, "type": "value_error.removed"}
                for f in removed
            ],
        )
    data = body.model_dump(exclude_none=True)
    # 密钥幂等保留：掩码/空值 = 保留现值（前端把 GET 下发的掩码原样回传时不清钥）
    if "providers" in data:
        data["providers"] = {
            name: resolve_provider_secret(entry, settings.providers.get(name))
            for name, entry in data["providers"].items()
        }
    # 环境变量优先：被 env 顶掉的项**不写入内存**（否则运行时值与 env 不一致，
    # 重启后又变回去——正是「界面改了没效果」的来源），只在响应里如实报出来。
    sources = settings.config_sources
    ignored: list[str] = []
    for field, value in data.items():
        if not hasattr(settings, field):
            continue
        src = sources.get(field, "default")
        if src.startswith("env:"):
            ignored.append(f"{field}({src[4:]})")
            continue
        setattr(settings, field, value)
        settings.mark_source(field, "file")
    settings.save_dpim_config()  # 持久化 BYOK/Agent/配置到 dpim.json，重启保留
    # 配置变更后立即健康检查一次：切换 provider/模型即刻生效，无需重启
    if deps.compensator is not None:
        await deps.compensator._check_llm()
    msg = "Settings updated and persisted to dpim.json; storage paths apply after restart"
    if ignored:
        msg += "；以下项被环境变量锁定，界面改动不生效：" + ", ".join(sorted(ignored))
    return _ok(message=msg, ignored_by_env=sorted(ignored))


@router.get("/health", response_model=HealthResponse)
async def health():
    es, gs = _stores()  # 活动库
    database = _database()
    total_events = await es.total_events()
    status_counts = await es.count_by_status()
    total_nodes = gs.total_nodes()
    node_counts = gs.node_counts_by_type()
    last = await es.last_event_at()
    # v1.34 三态：ok（AI 可用）/ unconfigured（没配 AI，无 AI 模式的正常态）/
    # degraded（配了但连不上）。原因取「未配置原因」优先，否则取最近一次连接失败原因。
    if not settings.llm_configured:
        status = "unconfigured"
        reason = settings.llm_config_error()
    elif ai_state.available:
        status = "ok"
        reason = ""
    else:
        status = "degraded"
        reason = ai_state.reason or "AI 连接失败（尚未恢复）"
    return HealthResponse(
        status=status,
        ai_available=ai_state.available,
        ai_unavailable_reason=reason,
        layers={
            "event_line": {
                "total_events": total_events,
                **status_counts,
            },
            "knowledge_graph": {
                "total_nodes": total_nodes,
                **node_counts,
            },
        },
        last_event_at=last or "",
        # 队列与册可见性（v1.29）
        queue_depth=deps.orchestrator.queue.qsize() if deps.orchestrator else 0,
        worker_running=bool(deps.orchestrator and deps.orchestrator._running),
        active_repo_id=deps.repos.active_id if deps.repos else "",
        # 存储容量与备份（P4）：此前健康位只看得到「结构」，看不到「体量与保障」
        storage={
            "db_bytes": await database.db_size(),
            "wal_bytes": await database.wal_size(),
            "json_bytes": Path(gs.json_path).stat().st_size
            if Path(gs.json_path).exists() else 0,
            "backups": len(list_backups(database.db_path)),
            "graph_ops": await gs.ops_count(),
        },
    )
