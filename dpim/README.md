# DPIM — Double-Place Intelligence Memory

> 由Deepseek v4 flash 0731编写于2026-8

双区智能贮存：独立于 LLM 上下文窗口的外部记忆模块。

---

## 运行原则

### 1. 无 Agent 模式为默认运行态

系统**不依赖任何 AI 模型或 Agent 提示词**即可完整运行。启动后默认处于降级态，以下功能立即可用：

- 事件写入 + FTS5 全文索引
- 事件/节点的人工增删改查
- FTS5 关键词检索
- CLI 全部管理命令
- 存储文件的人工编辑

### 2. Agent 模式为可选增强

管线模式（`DPIM_AGENT_MODE=pipeline`）启用后，四个 Agent 参与工作流：

| Agent | 文件 | 职责 |
|-------|------|------|
| 中央控制 Cr | `prompts/core.md` | 存入概括 + 检索意图分析 |
| 信息管理 In | `prompts/infomater.md` | 内容分拣标注（原文子串） |
| 图对接 Gr | `prompts/grapher.md` | 存图计划生成 + 图维护计划（合并/删改/补边/压缩） |
| 元认知 Meta | `prompts/metacognition.md` | 存图审核 + 维护审查 + 检索复核（硬关卡） |

**提示词正文已定稿**（Phase A，2026-08-01）：Cr 概括/意图、In 分拣、Gr 构图（含 event_id）、Meta 审核（4 类型），
含上下文护栏（DPIM_MAX_RAW_CONTENT 截断、similar_nodes 瘦身、instructor 重试、邻域边）。
未配置（agent_mode=disabled）时系统不受影响，事件停留在 `indexed` 状态等待补偿；AI 恢复后自动批量处理积压事件。

**图维护与对话指令**（2026-08-29）：信息传入框支持 `^` 指令——`^compress`（删繁就简维护轮）、
`^update`（两阶段结构优化：减碎+补缺失要点 → 连线孤岛）、`^merge` / `^delete`（确定层同步执行）、
`^data` / `^interaction` / `^source`（显式类型存入，离线可用）、`^node system`（手工系统节点）、`^help`。
维护候选六类：重合对 / 僵尸 / 低置信孤立 / 冗长可压缩 / 同源过碎事件 / 待连线对（含孤立节点），
带压缩与合并底线（防过度整理的损失螺旋）；详见 `share/protocol.md` 4.4/4.5 节。

### 3. 核心存储独立于 AI

信息线层（SQLite + FTS5）和信息图层（NetworkX + JSON）构成核心存储，所有基础操作**不调用任何 LLM**，确保存储层的可靠性和响应速度。

### 4. 存储文件开放可编辑

- `data/memory.db`：标准 SQLite 数据库，可用 `sqlite3`、DB Browser 等工具直接操作
- `data/graph.json`：带缩进的 JSON 文件，可用任意文本编辑器修改
- 手动编辑后重启服务即可生效
- 运行 `dpim storage-path` 查看文件准确路径

### 5. 配置方式

日常配置（提供商/密钥/模型路由/存储路径/日志级别等）通过 **WebUI 配置页**修改，
持久化在 `dpim/dpim.json`（重启保留）；`.env` 只承载部署级安全开关（`DPIM_API_KEY` /
`DPIM_AGENT_LOGS_FULL`）与少量临时覆盖（env 显式设置优先于 dpim.json 同名项）：

```bash
# 最小配置（使用默认 Ollama 地址时无需任何配置）
python main.py serve
```

**BYOK 多模型网关**（支持 DeepSeek / Ollama / OpenRouter 等任意 OpenAI 兼容 API，按角色路由模型）：

```bash
# 注册多个 provider（JSON dict）
DPIM_PROVIDERS='{"deepseek": {"base_url": "https://api.deepseek.com/v1", "api_key": "sk-x", "model": "deepseek-chat"}, "ollama": {"base_url": "http://localhost:11434/v1", "model": "llama3:8b"}}'
# 选择活动 provider（默认 primary = DPIM_LLM_*）
DPIM_ACTIVE_PROVIDER=deepseek
# 按角色覆盖模型（Cr/Meta 用强模型，In/Gr 用轻模型）
DPIM_AGENT_CR_MODEL=deepseek-reasoner
DPIM_AGENT_IN_MODEL=deepseek-chat
# 管线开关
DPIM_AGENT_MODE=pipeline
DPIM_AGENT_MAX_RETRIES=2
```

详见 `dpim/.env` 模板。

### 6. LLM 服务可选，降级自动生效

系统启动时 `ai_available = False`，所有操作以降级模式运行。若配置了 LLM 服务：
- 后台每 60s 自动检测连通性
- 连接成功 → 自动升级为完整模式（图构建 + 元认知审查）
- 连接断开 → 自动降级回基础模式
- 恢复后自动补偿积压事件

### 7. 所有组件无状态

除存储文件外，系统所有组件（Agent、中控、接口）均无状态。每次请求从存储读取数据，处理完毕后不保留会话历史。支持随时启停。

---

## 快速开始

```bash
# 启动 API 服务
python main.py serve

# 写入事件
python main.py ingest "用户询问了 Python 异步编程"

# 检索
python main.py query "Python 异步"

# 查看存储路径
python main.py storage-path

# 列出所有事件
python main.py list-events

# 查看事件详情
python main.py view-event <event_id>
```

API 服务启动后访问 http://localhost:8000/docs 查看 OpenAPI 文档。

---

## 项目结构

详见 `docs/elder_design/项目结构描述管理.md`。

## 设计文档

- `docs/DPIM设计大纲20260724.md` — 顶层概念与架构
- `docs/DPIM设计详纲20260724.md` — 完整设计参考
- `docs/elder_design/项目结构描述管理.md` — 模块与函数清单（已归档）
- `docs/elder_design/测试结论.md` — 测试记录（已归档）
- `docs/elder_design/执行进度.md` — 实现状态追踪
