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

信息线层是**时序事件存储**（SQLite + FTS5）：按时间顺序追加，**大模型不可轻易调整**，人类可通过显式端点修订与删除；
信息图层（NetworkX + JSON）是知识图谱。核心存储的所有基础操作**不调用任何 LLM**，确保存储层的可靠性和响应速度。

> 「不可变日志」是早期不准确的提法（系统本就有 `PUT /events/{id}`、`DELETE /events/{id}`）；
> 准确表述是**大模型不可轻易调整**——修正的是表述，不是实现。

### 4. 存储文件开放可编辑

- `data/memory.db`：标准 SQLite 数据库，可用 `sqlite3`、DB Browser 等工具直接操作
- `data/graph.json`：带缩进的 JSON 文件，可用任意文本编辑器修改
- 手动编辑后重启服务即可生效
- 运行 `dpim storage-path` 查看文件准确路径

### 5. 配置方式

日常配置（提供商/密钥/模型路由/存储路径/日志级别等）通过 **WebUI 配置页**修改，
持久化在 `dpim/dpim.json`（重启保留）；`.env` 只承载部署级安全开关（`DPIM_API_KEY` /
`DPIM_AGENT_LOGS_FULL`）与少量临时覆盖（env 显式设置优先于 dpim.json 同名项）：

- **AI 身份（`base_url` / `api_key` / `model`）只存在于 `providers` 条目**（v1.34 起）：原先与 provider
  平行的「主 provider」特殊分支已删除，`primary` 现在只是一个普通 provider 键名；`providers` 读
  **env `DPIM_PROVIDERS`（最高优先）或 `dpim.json` 的 `providers` 段**。
- **不再有任何内置身份默认值**：没有默认 base_url、没有默认 api_key、没有默认模型名。
  > v1.34 前 `LLM_BASE_URL` 默认 `http://localhost:11434/v1`、`LLM_MODEL_NAME` 默认 `llama3:8b`——
  > 任何未配置的部署都静默指向并不存在的本地 llama，而界面看不出「其实没配」。
- **纯 env 种子**：**仅当 `DPIM_LLM_BASE_URL` 显式设置且注册表为空**时，后端才合成一个名为 `default`
  的 provider 条目（保住纯 env 部署）；`DPIM_LLM_API_KEY` / `DPIM_LLM_MODEL_NAME` 只用于该种子条目。
- **`active_provider` 解析**：env → `dpim.json` → 注册表第一个键；显式指定但未登记时**原样保留**并如实报「未登记」，绝不静默替换。
- **`DPIM_LLM_TIMEOUT`（默认 666）/ `DPIM_LLM_MAX_TOKENS` / `DPIM_LLM_ENABLE_THINKING` / `DPIM_LLM_THINKING_BUDGET`
  只是全局调优兜底**（仅 env，provider 条目省略时使用），不再是身份配置，也不再属于 `PUT /settings`。
- **密钥掩码幂等**：`GET /settings` 只下发掩码（`sk-****abcd`），`PUT` 提交掩码或留空 = 保持现值；
  **掩码形状的值一律不落库**（含 provider 重命名/复制时带过来的掩码）。`dpim.json` 在 `.gitignore` 内，明文密钥不出仓库。
  > 已知边界：密钥**仍无法经前端清空**（「留空 = 保持现值」）——要清只能删掉 provider 条目再新建。

`dpim.json` 现在**没有 `llm` 段**，并且 **WebUI 能改的东西全都写在这里、重启后仍在**（v1.36 起；此前
`max_graph_hops` / `rrf_k` / `jaccard_threshold` / `health_check_interval` / `health_check_timeout` /
`compensate_batch_size` 六项**只改内存**——界面改完立刻有效、`GET /settings` 也回显，但重启即回默认，
与链 Y 的 `llm_*` 是同一类静默失败）：

| 段 | 字段 |
|----|------|
| 顶层 | `active_provider` / `active_model` / `providers` / `log_level` |
| `agent` | `mode` / `max_retries` / `cr_model` / `in_model` / `gr_model` / `meta_model` / `structured_mode` |
| `retrieval` | `max_graph_hops` / `rrf_k` / `jaccard_threshold` / `max_raw_content` |
| `health` | `health_check_interval` / `health_check_timeout` / `compensate_batch_size` / `compensate_check_interval` |
| `maintenance` | `agent_maintain_auto` / `agent_maintain_min_nodes` / `agent_maintain_max_nodes` / `agent_maintain_cooldown` / `agent_cmdmsg_max_rounds` / `agent_cr_skip_chars` |
| `logs` | `log_retention_days` / `log_jsonl` / `agent_logs_full` |
| `storage` | `memory_db_path` / `graph_json_path` / `wal_checkpoint_interval` / `wal_checkpoint_bytes` |

**每一项的读取链都是 env → `dpim.json` 对应段 → 内置默认**：环境变量（含 `load_dotenv()` 加载的
`dpim/.env`）仍然**优先于文件**，被 env 顶掉的项 `PUT /settings` **不再写入内存**，而是在响应里以
`ignored_by_env: ["rrf_k(DPIM_RRF_K)"]` + 中文 `message` 如实报出；`GET /settings` 另下发
`config_sources`（逐项标 `env:DPIM_X` / `file` / `default`）、`config_file`（配置写到哪个文件）与
`log_dir`（日志目录，只读）——**每个值现在来自谁，界面上看得见**。
**有意保留 env-only（前端不可配）**：`DPIM_API_KEY`（访问认证密钥，不得经 API 读/写）、`DPIM_LOG_DIR`
（改路径要重开文件句柄）、`DPIM_LLM_TIMEOUT` / `DPIM_LLM_MAX_TOKENS` / `DPIM_LLM_ENABLE_THINKING` /
`DPIM_LLM_THINKING_BUDGET`（provider 条目已各自拥有这些调优项，全局兜底仅 env）。
（2026-10-05 清理：历史 `llm` 段与整条 `providers.localhost` 已删——后者含旧掩码 bug 留下的字面
`"****"` api_key；备份见 `dpim/dpim.json.bak-20261005`。）

```json
{
  "active_provider": "siliconflow",
  "active_model": "deepseek-ai/DeepSeek-V4-Flash",
  "providers": {
    "siliconflow": {
      "base_url": "https://api.siliconflow.cn/v1",
      "api_key": "sk-xxx",
      "models": ["Qwen/Qwen3.5-4B", "deepseek-ai/DeepSeek-V4-Flash"]
    }
  }
}
```

> 上面是占位示例（密钥一律写 `sk-xxx`）；真实密钥只留在本机 `dpim.json`（已 gitignore），不要写进任何文档。

```bash
# 最小运行：无 AI 模式是默认运行态，未配置 AI 也能完整运行（写入 / 检索 / 指令 / 库管理）
python main.py serve

# 配置 AI：WebUI「维护 → 运行配置」填 provider（地址 / 密钥 / 模型），或直接编辑 dpim.json 的 providers 段
```

**BYOK 多模型网关**（支持 DeepSeek / SiliconFlow / OpenRouter 等任意 OpenAI 兼容 API，按角色路由模型）：

```bash
# 方式一：纯 env 注册多个 provider（JSON dict）——AI 身份只写在这里
DPIM_PROVIDERS='{"deepseek": {"base_url": "https://api.deepseek.com/v1", "api_key": "sk-x", "model": "deepseek-chat"}, "siliconflow": {"base_url": "https://api.siliconflow.cn/v1", "api_key": "sk-y", "model": "deepseek-ai/DeepSeek-V4-Flash"}}'
# 选择活动 provider（只能是注册表里的键名；显式指定但未登记会如实报「未登记」）
DPIM_ACTIVE_PROVIDER=deepseek

# 方式二：单 provider 的纯 env 种子——仅当注册表为空且 DPIM_LLM_BASE_URL 显式给出时才合成 default 条目
DPIM_LLM_BASE_URL=https://api.deepseek.com/v1
DPIM_LLM_API_KEY=sk-x
DPIM_LLM_MODEL_NAME=deepseek-chat

# 按角色覆盖模型（Cr/Meta 用强模型，In/Gr 用轻模型）
DPIM_AGENT_CR_MODEL=deepseek-reasoner
DPIM_AGENT_IN_MODEL=deepseek-chat
# 管线开关
DPIM_AGENT_MODE=pipeline
DPIM_AGENT_MAX_RETRIES=2
```

详见 `dpim/.env.example`。

### 6. LLM 服务可选，降级自动生效

系统启动时 `ai_available = False`，所有操作以降级模式运行。若配置了 LLM 服务：
- 后台每 60s 自动检测连通性
- 连接成功 → 自动升级为完整模式（图构建 + 元认知审查）
- 连接断开 → 自动降级回基础模式
- 恢复后自动补偿积压事件

**未配置 ≠ 降级**（v1.34 起）：`GET /settings` 增 `llm_configured` / `llm_unavailable_reason`
（4 种中文原因：完全没有 provider / 活动 provider 未登记 / base_url 为空 / 模型列表为空）；
未配置时补偿器**不探测、不计失败**。`GET /health` 的 `status` 因此是三态：
`ok` | `unconfigured` | `degraded`（附 `ai_unavailable_reason`）——只有「已配置但连续 3 次不可达」才算 `degraded`。

### 7. 所有组件无状态

除存储文件外，系统所有组件（Agent、中控、接口）均无状态。每次请求从存储读取数据，处理完毕后不保留会话历史。支持随时启停。

### 8. 存储保障与本地日志（2026-10-03）

**图层操作日志 `graph_ops`**：每次落盘把「相对上次落盘的状态差分」写入同库追加表（带「因何改图」的 reason）。
用途是审计与恢复——`graph.json` 丢失或损坏且无可用备份时，**从操作日志重放恢复图层**，而不是以空图启动。
恢复链：`graph.json` → `.bak.N`（默认 3 代，**覆盖前**留存）→ `graph_ops` 重放 → 空图。

| 机制 | 说明 |
|------|------|
| 整库备份 | `VACUUM INTO` 在线副本 + `graph.json` + `manifest.json`，保留最近 5 份 |
| 一致性校验 | SQLite 完整性/外键、`events↔events_fts`、节点↔`node_fts`、**操作日志重放 == 内存图**、悬空源证 |
| 跨进程互斥 | 每库一把 OS 文件锁（进程退出自动释放）：本地 CLI 与 serve 不能同时写同一库 |
| 回收站 | 物理删除前留档 `trash/{events,nodes}/<id>.json`；恢复按**原 id** 入库（源证随之对上） |
| WAL 治理 | 周期检查点（超 8 MiB 才 TRUNCATE），`/health` 回报 db/wal/json 体积 |
| 本地日志 | `logs/backend-*.log` 与 `logs/frontend-*.log` **分文件**按天轮转（保留 14 天，可选 JSONL） |

相关命令：

```bash
python main.py backup [--note "说明"]   # 整库备份
python main.py backups                   # 列出备份
python main.py verify                    # 一致性校验（只读）
python main.py restore <时间戳> --yes    # 从备份恢复（须先停服务；自动先做安全备份）
python main.py trash-list                # 列出回收站留档
python main.py trash-restore <event_id>  # 从回收站恢复事件
python main.py logs --list               # 列出日志文件
python main.py logs --tail 50 --grep 事件写入 --stream backend
```

REST 侧对应 `POST /maintenance/backup`、`GET /maintenance/backups`、`POST /maintenance/verify`、
`GET /maintenance/ops`、`POST /maintenance/checkpoint`、`POST /repos/{id}/refresh`（后端共 45 个端点，契约 v1.37）。
**恢复刻意不提供 REST 端点**：恢复必须停服务（内存图会陈旧），只能走本地 CLI。

日志与 WAL 的环境变量：`DPIM_LOG_DIR` / `DPIM_LOG_RETENTION_DAYS` / `DPIM_LOG_JSONL` /
`DPIM_WAL_CHECKPOINT_INTERVAL` / `DPIM_WAL_CHECKPOINT_BYTES`（详见 `dpim/.env.example`）。

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

**先看文档地图：`docs/README.md`**（哪份是权威、哪份已归档、为什么）。

- `share/protocol.md` — **接口契约权威**（v1.44 / 45 端点）
- `docs/DPIM项目总览20260805.md` — **项目唯一入口**（核心特点 / 四层架构 / 线层与图层 / 检索 / 降级补偿 / 端点概览 / WebUI / CLI / 配置 / 测试 / 目录布局）
- `docs/DPIM-WebUI设计规约20261003.md` — **前端唯一依据**（原则 / 库模型 / 四区信息架构 / 12 页规约 / 行为要求 / 视觉与组件 / 技术骨架）
- `docs/DPIM-WebUI重设计实施记录20261004.md` — 前端重设计的落地记录与实测结论
- `docs/存储保障与本地日志设计20261003.md` — 存储保障/日志/联合检索修正的设计决策记录
- `docs/图层派生关系核实20261003.md` — 「图层是派生 read-model」的核实证据与方案对比
- `docs/archive/` — 已被取代的设计稿（旧大纲/详纲/旧 WebUI 稿等 6 份），**仅供追溯，不作为依据**
- `docs/elder_design/执行进度.md` — 逐轮实现状态追踪
- `docs/elder_design/项目结构描述管理.md` — 模块与函数清单（已归档）
- `docs/elder_design/测试结论.md` — 测试记录（已归档）
