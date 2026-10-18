"""应用配置，环境变量驱动（支持 .env 文件）+ dpim.json 结构化配置"""

import json
import logging
import os
import warnings
from dataclasses import dataclass
from os import getenv
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── LLM 接口格式（v1.43）：一个 provider 条目 = 一套协议 ──────────────────
# 此前网关只认 OpenAI 兼容 Chat Completions（`core/llm.py` 写死
# `chat.completions.create`），于是 Anthropic 的 `/v1/messages` 与 OpenAI 的
# `/v1/responses` **根本接不上**（连模型列表都拉不出来）。现在把「格式」做成
# provider 条目的一个字段，四套各按真实协议收发：
#
# - `openai`（默认，老条目零迁移）：`POST {base}/chat/completions`，`Authorization: Bearer`
# - `responses`：`POST {base}/responses`——body 是 `input` / `instructions` /
#   `max_output_tokens` / `text.format`（**不是** messages/max_tokens）
# - `anthropic`：`POST {base}/messages`——`x-api-key` + `anthropic-version` 头，
#   `system` 是**顶层字段**，`max_tokens` **必填**
# - `custom`：自定路径 + 额外请求头，仍按 chat completions 形状收发
PROVIDER_FORMATS = ("openai", "responses", "anthropic", "custom")
# 各格式的默认请求路径（custom 未填 api_path 时也用它）
DEFAULT_API_PATHS = {
    "openai": "/chat/completions",
    "responses": "/responses",
    "anthropic": "/messages",
    "custom": "/chat/completions",
}
# Anthropic Messages 的 max_tokens 是必填项：条目与全局都没填时用它兜底。
# 为什么是 4096：它等于**各家 Claude 模型输出上限里的最小值**（Claude 3 Haiku / Opus = 4096，
# 3.5 Sonnet = 8192，3.7 / 4 系列 = 64000）——取它保证换任何模型都不会因「超过模型输出上限」被 400。
# 它只是**上限**（cap）不是目标长度：按实际输出计费，填大不会更贵，填小才会截断；
# 要更长输出就在界面「输出上限 tokens」里填，或给全局 env `DPIM_LLM_MAX_TOKENS`。
ANTHROPIC_DEFAULT_MAX_TOKENS = 4096
# 思考（extended thinking）的 token **计入** max_tokens，且 Anthropic 硬性要求
# `max_tokens > thinking.budget_tokens`（不满足直接 400）。余量不足时按「预算 + 这段」抬升，
# 给正文留出空间——否则思考刚结束就被 `stop_reason=max_tokens` 截断（半截 JSON = 校验必失败）。
ANTHROPIC_THINKING_HEADROOM = 1024
ANTHROPIC_VERSION = "2023-06-01"


def normalize_format(raw: Any) -> str:
    """接口格式归一：未知/空 → `openai`（并告警），保证老条目零迁移。"""
    value = str(raw or "").strip().lower()
    if value in PROVIDER_FORMATS:
        return value
    if value:
        logger.warning("provider 的 format='%s' 未知，按 openai 处理", value)
    return "openai"


@dataclass
class ProviderConfig:
    """一个 LLM 提供商实例：接口格式 + 厂商适配参数。

    - format：接口格式（openai | responses | anthropic | custom，见 `PROVIDER_FORMATS`）
    - api_path：自定义请求路径（仅 custom 有意义；空 = 用 `DEFAULT_API_PATHS`）
    - extra_headers：额外 HTTP 请求头（各格式通用，如自建网关的鉴权头）
    - max_tokens：输出 token 上限（None = 不传，用服务端默认；Anthropic 必填，见上）
    - enable_thinking：思考开关（None = 不干预，用服务端默认）
    - thinking_budget：思考 token 预算（None = 不传）
    - thinking_style：思考参数的载体：top_level（SiliconFlow/DeepSeek 顶层字段）
      | chat_template_kwargs（llama.cpp）| auto（本地地址自动选 chat_template_kwargs）
    - extra_body：任意厂商参数透传（如 DeepSeek 的 reasoning_effort 等）
    - structured_mode：结构化输出模式覆盖（md_json | json | tools，空 = 用全局）
    """

    name: str
    base_url: str
    api_key: str
    model: str
    timeout: int
    max_tokens: int | None = None
    enable_thinking: bool | None = None
    thinking_budget: int | None = None
    thinking_style: str = "auto"
    extra_body: dict | None = None
    structured_mode: str | None = None
    format: str = "openai"
    api_path: str = ""
    extra_headers: dict | None = None


def _parse_bool_or_none(raw: str) -> bool | None:
    """env 布尔解析：true/1/yes → True，false/0/no → False，其余（含空）→ None。"""
    v = raw.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return None


def _as_bool(raw: Any, default: bool) -> bool:
    """布尔取值：真布尔直接用；字符串按 `_parse_bool_or_none` 解析；无法判断 → default。

    用于「env（字符串）与 dpim.json（真布尔）混在一处」的读取链。
    """
    if isinstance(raw, bool):
        return raw
    parsed = _parse_bool_or_none(str(raw))
    return default if parsed is None else parsed


# Agent 角色
ROLES = ("cr", "in", "gr", "meta")


class Settings:
    def __init__(self) -> None:
        # ── dpim.json 结构化配置（BYOK/Agent；env DPIM_* 优先于文件）──
        self.config_file = getenv(
            "DPIM_CONFIG_FILE",
            str(Path(__file__).resolve().parent.parent / "dpim.json"),
        )
        cfg = self._read_dpim_config()
        self._cfg = cfg if isinstance(cfg, dict) else {}
        # ── 前端可配置面（v1.36）：**每一项**都要真的落到 dpim.json ──
        # 读取链统一为 env（部署覆盖）→ dpim.json 对应段（前端修改持久化）→ 内置默认；
        # `self._sources[字段]` 记录值从哪来（`env:DPIM_X` / `file` / `default`），
        # 经 `GET /settings` 的 `config_sources` 下发 —— 前端必须看得见哪一项被
        # 环境变量顶掉了（否则「界面改了没效果」又是一次静默失败）。
        self._sources: dict[str, str] = {}
        self._sections: dict[str, dict[str, Any]] = {
            name: (self._cfg.get(name) if isinstance(self._cfg.get(name), dict) else {})
            for name in ("agent", "storage", "retrieval", "health", "maintenance", "logs")
        }
        # 读取链：env（部署覆盖）→ dpim.json storage（前端修改持久化）→ 内置默认
        self.memory_db_path = self._pick(
            "memory_db_path", "DPIM_MEMORY_DB_PATH", "./data/memory.db", str, "storage"
        )
        self.graph_json_path = self._pick(
            "graph_json_path", "DPIM_GRAPH_JSON_PATH", "./data/graph.json", str, "storage"
        )
        # ── 全局调优默认（v1.34：只含调优，不含身份；provider 条目可逐项覆盖）──
        # 身份三项（base_url / api_key / model）**一律属于 provider 条目**，
        # 没有内置默认提供商：一个都没登记时 AI 就是「未配置」。
        # 生成请求超时（秒）：本地模型慢，默认放宽到 666；provider 条目可单独覆盖
        self.llm_timeout = int(getenv("DPIM_LLM_TIMEOUT", "666"))
        # 输出 token 上限（0 = 不传，用服务端默认）
        self.llm_max_tokens = int(getenv("DPIM_LLM_MAX_TOKENS", "0")) or None
        # 思考开关（空 = 不干预；SiliconFlow 顶层 enable_thinking / llama.cpp chat_template_kwargs）
        self.llm_enable_thinking = _parse_bool_or_none(getenv("DPIM_LLM_ENABLE_THINKING", ""))
        # 思考 token 预算（0 = 不传）
        self.llm_thinking_budget = int(getenv("DPIM_LLM_THINKING_BUDGET", "0")) or None
        # ── BYOK 多提供商注册：env DPIM_PROVIDERS 优先，否则读 dpim.json ──
        self.providers: dict[str, dict[str, Any]] = {}
        raw_providers = getenv("DPIM_PROVIDERS", "").strip()
        if raw_providers:
            try:
                parsed = json.loads(raw_providers)
                if isinstance(parsed, dict):
                    self.providers = parsed
                else:
                    warnings.warn("DPIM_PROVIDERS 应为 JSON 对象 {name: {...}}", stacklevel=2)
            except json.JSONDecodeError:
                warnings.warn("DPIM_PROVIDERS 解析失败，已忽略", stacklevel=2)
        elif isinstance(cfg.get("providers"), dict):
            self.providers = cfg["providers"]
        # 纯环境变量部署：**显式**给了 DPIM_LLM_BASE_URL 且注册表为空 → 合成一条 `default`
        # 条目（保住部署覆盖能力）。没显式给就不合成——不再有 ollama / llama3:8b 写死默认。
        env_base = getenv("DPIM_LLM_BASE_URL", "").strip()
        if not self.providers and env_base:
            env_model = getenv("DPIM_LLM_MODEL_NAME", "").strip()
            entry: dict[str, Any] = {
                "base_url": env_base,
                "api_key": getenv("DPIM_LLM_API_KEY", ""),
            }
            if env_model:
                entry["models"] = [env_model]
            self.providers = {"default": entry}
        # 注册表来源（界面据此提示「提供商注册表由环境变量提供，界面改动不生效」）
        if raw_providers:
            self._sources["providers"] = "env:DPIM_PROVIDERS"
        elif not self.providers and env_base:
            self._sources["providers"] = "env:DPIM_LLM_BASE_URL"
        elif isinstance(cfg.get("providers"), dict):
            self._sources["providers"] = "file"
        else:
            self._sources["providers"] = "default"
        # 活动提供商：env → dpim.json → 注册表首个；显式指定但不在注册表内则**原样保留**
        # （由 llm_config_error 如实报出「未登记」，不静默换一个）
        self.active_provider = self._pick("active_provider", "DPIM_ACTIVE_PROVIDER", "", str)
        if not self.active_provider:
            self.active_provider = next(iter(self.providers), "")
        # ── API 访问认证：非空时所有端点要求 X-API-Key 头匹配（空 = 禁用，本地默认）
        # 仅 env 配置，不经 dpim.json / PUT /settings 下发，避免密钥经 API 自我暴露
        self.api_key = getenv("DPIM_API_KEY", "").strip()
        # ── AI 调用日志全文开关：false 时 GET /agent/logs 忽略 full 参数（防隐私泄露）──
        self.agent_logs_full = self._pick(
            "agent_logs_full", "DPIM_AGENT_LOGS_FULL", True,
            lambda r: _as_bool(r, True), "logs",
        )
        # ── Agent 管线开关 ──
        self.agent_mode = self._pick(
            "agent_mode", "DPIM_AGENT_MODE", "disabled", str, "agent", "mode"
        )
        self.agent_max_retries = self._pick(
            "agent_max_retries", "DPIM_AGENT_MAX_RETRIES", 2, int, "agent", "max_retries"
        )
        # ── 上下文护栏：单次 LLM 输入中 raw_content 最大字符数（超限截断）──
        # 默认 200000 字符（≈5 万 token 输入）：足够容纳长文档，又不会像
        # 600000 那样把内存/上下文撑爆；不依赖任何"默认模型"的上下文窗口
        self.max_raw_content = self._pick(
            "max_raw_content", "DPIM_MAX_RAW_CONTENT", 200000, int, "retrieval"
        )
        # ── 结构化输出模式：md_json（默认，兼容 llama.cpp）| json | tools ──
        self.llm_structured_mode = self._pick(
            "llm_structured_mode", "DPIM_LLM_STRUCTURED_MODE", "md_json", str,
            "agent", "structured_mode",
        )
        # ── 角色模型路由（空值 → 回退活动 provider 默认模型）──
        self.agent_cr_model = self._pick(
            "agent_cr_model", "DPIM_AGENT_CR_MODEL", "", str, "agent", "cr_model"
        )
        self.agent_in_model = self._pick(
            "agent_in_model", "DPIM_AGENT_IN_MODEL", "", str, "agent", "in_model"
        )
        self.agent_gr_model = self._pick(
            "agent_gr_model", "DPIM_AGENT_GR_MODEL", "", str, "agent", "gr_model"
        )
        self.agent_meta_model = self._pick(
            "agent_meta_model", "DPIM_AGENT_META_MODEL", "", str, "agent", "meta_model"
        )
        # ── 使用中的模型（活动 provider 的默认选用模型，空 → provider 首个/默认）──
        self.active_model = self._pick("active_model", "DPIM_ACTIVE_MODEL", "", str)
        self.max_graph_hops = self._pick(
            "max_graph_hops", "DPIM_MAX_GRAPH_HOPS", 2, int, "retrieval"
        )
        self.rrf_k = self._pick("rrf_k", "DPIM_RRF_K", 60, int, "retrieval")
        self.jaccard_threshold = self._pick(
            "jaccard_threshold", "DPIM_JACCARD_THRESHOLD", 0.85, float, "retrieval"
        )
        self.health_check_interval = self._pick(
            "health_check_interval", "DPIM_HEALTH_CHECK_INTERVAL", 60, int, "health"
        )
        # 健康检查超时（秒）：与生成超时分离，模型加载/单槽忙碌时不至于 3 连败假降级
        self.health_check_timeout = self._pick(
            "health_check_timeout", "DPIM_HEALTH_CHECK_TIMEOUT", 120, int, "health"
        )
        self.compensate_batch_size = self._pick(
            "compensate_batch_size", "DPIM_COMPENSATE_BATCH_SIZE", 20, int, "health"
        )
        # 补偿批次结果检查间隔（秒）：独立于健康检查周期（60s），失败批次
        # 快速被发现并进入退避，避免积压迟迟不处理
        self.compensate_check_interval = self._pick(
            "compensate_check_interval", "DPIM_COMPENSATE_CHECK_INTERVAL", 5, int, "health"
        )
        # ── 图维护自动触发：AI 恢复触发补偿时顺带整理图谱（手动触发不受限）──
        # 默认开启；小图由 min_nodes 阈值拦截（避免空转）
        self.agent_maintain_auto = self._pick(
            "agent_maintain_auto", "DPIM_AGENT_MAINTAIN_AUTO", True,
            lambda r: _as_bool(r, True), "maintenance",
        )
        self.agent_maintain_min_nodes = self._pick(
            "agent_maintain_min_nodes", "DPIM_AGENT_MAINTAIN_MIN_NODES", 10, int, "maintenance"
        )
        # ── 节点规模高水位：总节点数达到该阈值后每个冷却周期自动触发图维护
        #（合并冗余/压缩/清理僵尸节点等，独立于 AI 恢复触发）。默认 200：此后每次
        # 健康周期都准备压缩；也可在信息传入框输入 ^compress、^update 随时手动触发 ──
        self.agent_maintain_max_nodes = self._pick(
            "agent_maintain_max_nodes", "DPIM_AGENT_MAINTAIN_MAX_NODES", 200, int, "maintenance"
        )
        # 自动维护触发冷却（秒）：超过高水位后避免每个健康周期重复触发空转 LLM
        self.agent_maintain_cooldown = self._pick(
            "agent_maintain_cooldown", "DPIM_AGENT_MAINTAIN_COOLDOWN", 60, int, "maintenance"
        )
        # ^cmdmsg 指令消息多轮封顶：每轮 = 重扫 → Gr 按指令决策 → Meta 审 → 执行；
        # 空计划/被驳回/无候选即提前停（防指令驱动的无限循环）
        self.agent_cmdmsg_max_rounds = self._pick(
            "agent_cmdmsg_max_rounds", "DPIM_AGENT_CMDMSG_MAX_ROUNDS", 3, int, "maintenance"
        )
        # Cr 短路（v1.29）：原文不超过该长度时跳过 Cr 概括，短事件省一次 LLM 调用
        self.agent_cr_skip_chars = self._pick(
            "agent_cr_skip_chars", "DPIM_AGENT_CR_SKIP_CHARS", 200, int, "maintenance"
        )
        # 日志级别读取链同存储路径：env → dpim.json 顶层 → 默认（前端可改并持久化）
        self.log_level = self._pick("log_level", "DPIM_LOG_LEVEL", "INFO", str)
        # ── 本地日志系统（前后端分文件、按天轮转）──
        # 日志目录默认 <dpim>/logs：与存储文件同级，便于用户直接打开翻看。
        # **目录本身仍 env-only**（改路径要重开文件句柄），只读下发供界面显示。
        self.log_dir = getenv(
            "DPIM_LOG_DIR", str(Path(__file__).resolve().parent.parent / "logs")
        )
        # 保留天数（0 = 不清理）
        self.log_retention_days = self._pick(
            "log_retention_days", "DPIM_LOG_RETENTION_DAYS", 14, int, "logs"
        )
        # 额外输出 JSONL（程序读；默认关，人读的文本格式为主）
        self.log_jsonl = self._pick(
            "log_jsonl", "DPIM_LOG_JSONL", False, lambda r: _as_bool(r, False), "logs"
        )
        # ── WAL 治理（P4）：周期检查点，防长期运行 WAL 无界增长 ──
        self.wal_checkpoint_interval = self._pick(
            "wal_checkpoint_interval", "DPIM_WAL_CHECKPOINT_INTERVAL", 300, int, "storage"
        )
        self.wal_checkpoint_bytes = self._pick(
            "wal_checkpoint_bytes", "DPIM_WAL_CHECKPOINT_BYTES",
            8 * 1024 * 1024, int, "storage",
        )
        # ── 保留策略（v1.39）：让 graph_ops 表与 trash/ 目录有界 ──
        # 图层操作日志保留条数：**压实而非截断**（把最老明细压成等价快照，重放/恢复能力不变）；
        # 0 = 不压实。下限见 compact_ops：1 + 节点数 + 边数（快照本身）
        self.graph_ops_retention = self._pick(
            "graph_ops_retention", "DPIM_GRAPH_OPS_RETENTION", 5000, int, "storage"
        )
        # 回收站留档保留天数：留档是**已删数据的最后一份副本**，清理即永久丢失；
        # 0 = 永不清理（默认 30 天）
        self.trash_retention_days = self._pick(
            "trash_retention_days", "DPIM_TRASH_RETENTION_DAYS", 30, int, "storage"
        )
        self._validate()

    def _validate(self) -> None:
        """启动时校验关键配置项，尽早暴露问题。

        v1.34：逐 provider 校验 base_url；v1.43：接口格式与自定义路径。
        """
        for name, entry in self.providers.items():
            url = str((entry or {}).get("base_url") or "").strip()
            if not url:
                continue  # 未填地址由 llm_config_error() 如实报出，不在这里刷警告
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                warnings.warn(
                    f"提供商 {name} 的 base_url='{url}' 格式无效，"
                    "应为 http://host:port/v1 格式",
                    stacklevel=2,
                )
            raw_format = str((entry or {}).get("format") or "").strip().lower()
            if raw_format and raw_format not in PROVIDER_FORMATS:
                warnings.warn(
                    f"提供商 {name} 的 format='{raw_format}' 非法，"
                    f"应为 {' | '.join(PROVIDER_FORMATS)}（已按 openai 处理）",
                    stacklevel=2,
                )
            path = str((entry or {}).get("api_path") or "").strip()
            if path and not path.startswith("/"):
                warnings.warn(
                    f"提供商 {name} 的 api_path='{path}' 建议以 / 开头（拼接时会自动补）",
                    stacklevel=2,
                )
        if self.agent_mode not in ("disabled", "pipeline"):
            warnings.warn(
                f"DPIM_AGENT_MODE='{self.agent_mode}' 非法，应为 disabled | pipeline",
                stacklevel=2,
            )
        if self.llm_structured_mode not in ("md_json", "json", "tools"):
            warnings.warn(
                f"DPIM_LLM_STRUCTURED_MODE='{self.llm_structured_mode}' 非法，"
                "应为 md_json | json | tools",
                stacklevel=2,
            )

    def _pick(
        self,
        field: str,
        env: str,
        default: Any,
        cast: Any = str,
        section: str = "",
        key: str = "",
    ) -> Any:
        """统一读取链：env → dpim.json 的 `section.key` → default，并记录来源。

        来源写进 `self._sources[field]`（`env:VAR` / `file` / `default`），
        经 `GET /settings` 的 `config_sources` 下发——前端要能看见「这一项现在是
        谁在说话」，否则「界面改了没效果」无法自查（环境变量优先级高于文件）。
        """
        sec = self._sections.get(section, {}) if section else self._cfg
        name = key or field
        raw_env = getenv(env, "").strip()
        if raw_env != "":
            source, raw = f"env:{env}", raw_env
        elif name in sec and sec[name] is not None:
            source, raw = "file", sec[name]
        else:
            source, raw = "default", default
        try:
            value = cast(raw)
        except (TypeError, ValueError):
            logger.warning("配置项 %s 取值非法（%r），回退默认 %r", field, raw, default)
            source, value = "default", cast(default)
        self._sources[field] = source
        return value

    @property
    def config_sources(self) -> dict[str, str]:
        """各配置项的取值来源（`env:DPIM_X` / `file` / `default`）。"""
        return dict(self._sources)

    def mark_source(self, field: str, source: str) -> None:
        """标注某配置项当前由谁说话（PUT /settings 落盘后调用）。"""
        self._sources[field] = source

    def _read_dpim_config(self) -> dict[str, Any]:
        """读取 dpim.json 结构化配置（BYOK/Agent）。文件不存在或损坏返回 {}。"""
        path = Path(self.config_file)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            logger.warning("dpim.json 解析失败，已忽略: %s", path)
            return {}

    def save_dpim_config(self) -> None:
        """把当前 BYOK/Agent/存储配置持久化到 dpim.json（前端改配置后调用）。

        v1.34：不再写 `llm` 段——AI 身份（base_url / api_key / model）**只存在于
        providers 条目里**，一个提供商 = 一条记录，落盘即全部。
        v1.36：**前端能改的每一项都在这里落盘**。此前 `max_graph_hops` / `rrf_k` /
        `jaccard_threshold` / `health_check_interval` / `health_check_timeout` /
        `compensate_batch_size` 只在内存生效（PUT 后立刻有效、**重启即回默认**）——
        与链 Y 的 `llm_*` 是同一类静默失败；现在统一进 `retrieval` / `health` /
        `maintenance` / `logs` / `storage` / `agent` 段，重启后仍在。
        """
        payload = {
            "active_provider": self.active_provider,
            "active_model": self.active_model,
            "providers": self.providers,
            "agent": {
                "mode": self.agent_mode,
                "max_retries": self.agent_max_retries,
                "cr_model": self.agent_cr_model,
                "in_model": self.agent_in_model,
                "gr_model": self.agent_gr_model,
                "meta_model": self.agent_meta_model,
                "structured_mode": self.llm_structured_mode,
            },
            "retrieval": {
                "max_graph_hops": self.max_graph_hops,
                "rrf_k": self.rrf_k,
                "jaccard_threshold": self.jaccard_threshold,
                "max_raw_content": self.max_raw_content,
            },
            "health": {
                "health_check_interval": self.health_check_interval,
                "health_check_timeout": self.health_check_timeout,
                "compensate_batch_size": self.compensate_batch_size,
                "compensate_check_interval": self.compensate_check_interval,
            },
            "maintenance": {
                "agent_maintain_auto": self.agent_maintain_auto,
                "agent_maintain_min_nodes": self.agent_maintain_min_nodes,
                "agent_maintain_max_nodes": self.agent_maintain_max_nodes,
                "agent_maintain_cooldown": self.agent_maintain_cooldown,
                "agent_cmdmsg_max_rounds": self.agent_cmdmsg_max_rounds,
                "agent_cr_skip_chars": self.agent_cr_skip_chars,
            },
            "logs": {
                "log_retention_days": self.log_retention_days,
                "log_jsonl": self.log_jsonl,
                "agent_logs_full": self.agent_logs_full,
            },
            "storage": {
                "memory_db_path": self.memory_db_path,
                "graph_json_path": self.graph_json_path,
                "wal_checkpoint_interval": self.wal_checkpoint_interval,
                "wal_checkpoint_bytes": self.wal_checkpoint_bytes,
                "graph_ops_retention": self.graph_ops_retention,
                "trash_retention_days": self.trash_retention_days,
            },
            "log_level": self.log_level,
        }
        path = Path(self.config_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _provider_models(self, entry: dict[str, Any] | None) -> list[str]:
        """provider 条目模型列表：支持 models:[...] 或旧式 model:'...'。"""
        if not entry:
            return []
        if isinstance(entry.get("models"), list):
            return [str(m) for m in entry["models"] if m]
        if entry.get("model"):
            return [str(entry["model"])]
        return []

    def provider_config(self, provider_name: str | None = None) -> ProviderConfig:
        """解析 provider：**只认注册表**（v1.34 起没有 primary 特殊分支）。

        未登记 / 未填 base_url → 返回空配置（base_url 为空串）。调用方应先看
        `llm_configured` / `llm_config_error()`，不要拿空配置去建客户端。
        """
        name = provider_name or self.active_provider
        return self._entry_provider_config(name, self.providers.get(name))

    def _entry_provider_config(
        self, name: str, entry: dict[str, Any] | None
    ) -> ProviderConfig:
        """把 provider 条目 + 全局调优默认合成完整 ProviderConfig（身份只取条目）。"""
        if entry is None:
            entry = {}
        conf = ProviderConfig(
            name=name,
            base_url=str(entry.get("base_url") or ""),
            api_key=str(entry.get("api_key") or ""),
            model=self._resolve_model(name, entry),
            timeout=int(entry.get("timeout") or self.llm_timeout),
        )
        # 厂商适配参数：provider 条目优先，未设则用全局 env 默认
        conf.max_tokens = (
            int(entry["max_tokens"]) if entry.get("max_tokens") else self.llm_max_tokens
        )
        conf.enable_thinking = (
            _parse_bool_or_none(str(entry["enable_thinking"]))
            if entry.get("enable_thinking") is not None
            else self.llm_enable_thinking
        )
        conf.thinking_budget = (
            int(entry["thinking_budget"])
            if entry.get("thinking_budget")
            else self.llm_thinking_budget
        )
        conf.thinking_style = str(entry.get("thinking_style", "auto"))
        conf.extra_body = (
            entry.get("extra_body")
            if isinstance(entry.get("extra_body"), dict)
            else None
        )
        conf.structured_mode = (
            str(entry["structured_mode"]) if entry.get("structured_mode") else None
        )
        # 接口格式（v1.43）：身份四项之外的第五个维度——同一个地址/密钥，
        # 走哪套协议由它决定；老条目没有这个键 → openai（与从前完全一致）
        conf.format = normalize_format(entry.get("format"))
        conf.api_path = str(entry.get("api_path") or "").strip()
        conf.extra_headers = (
            {str(k): str(v) for k, v in entry["extra_headers"].items()}
            if isinstance(entry.get("extra_headers"), dict)
            else None
        )
        return conf

    def _resolve_model(self, name: str, entry: dict[str, Any] | None) -> str:
        """模型解析链：active_model（在该 provider 模型列表内）→ 列表首个 → 空串（未配置）。"""
        models = self._provider_models(entry)
        if self.active_model and self.active_model in models:
            return self.active_model
        if models:
            return models[0]
        return ""

    def llm_config_error(self) -> str:
        """AI 未配置的原因（中文，可直接展示）；已配置返回空串。

        与「降级」严格区分：未配置 = **没有 AI**（无 AI 模式是默认运行态，
        存储/检索/指令照常可用）；降级 = 配好了但连不上（网络/密钥/服务端问题）。
        """
        if not self.providers:
            return "未配置任何 AI 提供商（无 AI 模式：存储、检索与指令照常可用）"
        name = self.active_provider
        if not name:
            return "未选择使用中的提供商"
        entry = self.providers.get(name)
        if entry is None:
            return f"使用中的提供商「{name}」未登记（可能已被删除，请在运行配置里重新选择）"
        if not str(entry.get("base_url") or "").strip():
            return f"提供商「{name}」未填模型地址（base_url）"
        if not self._resolve_model(name, entry):
            return f"提供商「{name}」未登记任何模型"
        return ""

    @property
    def llm_configured(self) -> bool:
        """是否具备可用的 AI 调用条件（提供商 + 地址 + 模型齐备）。"""
        return not self.llm_config_error()

    def role_model(self, role: str) -> str:
        """角色 → 模型名：角色显式指定则优先，否则用活动 provider 解析的模型。"""
        override = getattr(self, f"agent_{role}_model", "") or ""
        return override if override else self.provider_config().model

    def role_provider(self, role: str) -> ProviderConfig:
        """角色 → ProviderConfig：厂商参数取活动 provider，model 按角色解析。"""
        conf = self.provider_config()
        return ProviderConfig(
            name=conf.name,
            base_url=conf.base_url,
            api_key=conf.api_key,
            model=self.role_model(role),
            timeout=conf.timeout,
            max_tokens=conf.max_tokens,
            enable_thinking=conf.enable_thinking,
            thinking_budget=conf.thinking_budget,
            thinking_style=conf.thinking_style,
            extra_body=conf.extra_body,
            structured_mode=conf.structured_mode,
            format=conf.format,
            api_path=conf.api_path,
            extra_headers=conf.extra_headers,
        )

    def available_models(self) -> list[str]:
        """活动 provider 的可用模型列表（供前端「使用中的模型」选择）；未配置 = 空列表。"""
        return self._provider_models(self.providers.get(self.active_provider))


settings = Settings()
