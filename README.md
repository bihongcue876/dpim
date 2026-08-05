# 双区智能内存 DPIM
Double-Place Intelligence Memory — 独立于 LLM 上下文窗口的外部记忆系统。

---

## 工程简介

DPIM 是一个双区智能贮存系统，同时承担两个角色：

- **第二上下文**：存储外部 Agent 与用户的交互记录，替代 LLM 的上下文窗口
- **长期知识库**：存储搜索到的事实和用户导入的资料，供后续检索与引用

系统通过不可变事件日志（信息线层）与知识图谱（信息图层）的双区结构，在 AI 可用时持续衍生结构化知识，在 AI 不可用时退化为基础全文检索存储。

---

## 项目特色

- 事件写入与 FTS5 全文索引，支持 interaction / data / source 三种类型，原子写入接口（insert_event）
- 事件状态机：raw → indexed → linked（终态），failed / skipped 异常路径
- 知识图谱节点与边的人工增删改查，JSON 文件持久化（防抖自动保存，5 次修改阈值）
- 混合检索：FTS5 关键词召回 + 图扩散两路 RRF 融合排序（无 Agent 默认仅 FTS5），中文自动降级 LIKE
- **Agent 管线（方案A，硬编码编排）**：Cr/In/Gr/Meta 四 Agent，ingest 并行拆分与查图、
  Gr 修正循环（仅重试 Gr）、Meta 硬关卡审核；检索意图分析 + Meta 复核
- **BYOK 多模型网关**：多 provider 注册（DeepSeek/SiliconFlow/Ollama/llama.cpp…），按角色路由模型，
  一次调用打包完整上下文（chat_structured）；厂商适配：思考开关/预算（enable_thinking、thinking_budget，
  SiliconFlow 顶层字段、llama.cpp chat_template_kwargs 自动适配）、输出上限 max_tokens、任意参数 extra_body 透传
- 来源锚定防幻觉：每条图节点必含 source_refs 与 evidence_quote，元认知裁判做子串校验
- 删除保护：system 和 data 类型节点失去所有源证时禁止删除
- 降级与补偿：LLM 不可用时自动降级，恢复后批量补偿积压事件；补偿带退避（首条试探 + 指数退避 + 连续失败暂停）
- 超时包容：生成请求超时默认 666s（provider 可覆盖）、健康检查独立超时 120s；超时/断连等瞬时错误不判死事件，自动回到 indexed 等待补偿重试
- AI 调用日志：每次 LLM 调用的输入/输出/错误环形缓冲（GET /agent/logs，支持 full 参数返回全文），前端「信息传入」页实时观测、可折叠展开
- 上下文护栏：单次 LLM 输入中 raw_content 最大字符数（默认 10000），超限截断
- 状态校验密钥：UUID 机制保证前后端写操作一致性，冲突时自动提示刷新
- 线程安全的 AI 可用性状态管理（AIState 单例封装）
- 启动时配置校验：LLM 地址格式 + API Key 空值警告
- FastAPI REST 接口层，22 个端点
- 命令行管理：内置 Typer CLI + 独立 dpim-cli（推荐，支持 Shell/管道/JSON/YAML 输出）

---

## 工作原则

1. **无 AI 为默认运行态**
   系统不依赖 AI 模型或 Agent 即可完整运行。启动后默认以降级模式运行，事件写入、全文检索、CLI 管理、存储文件人工编辑等功能立即可用。
2. **智能为可选增强**
   设计信息 Agent（In）、图 Agent（Gr）、核心 Agent（Cr）、元认知审核 Agent（Meta）四角色，参与信息管线处理。未配置提示词时系统不受影响。
3. **核心存储独立于 AI**
   信息线层（SQLite + FTS5）和信息图层（NetworkX + JSON）构成核心存储，所有基础操作不调用任何 LLM。
4. **存储文件可编辑**
   data/memory.db 为标准 SQLite 数据库，data/graph.json 为带缩进的 JSON 文件，均支持人工编辑后重启生效。
5. **配置层次清晰**
   所有配置通过 .env 文件或 DPIM_ 前缀环境变量设置。默认连接 localhost:11434（Ollama），切换 OpenAI 仅需修改环境变量。前端配置页支持可视化编辑。
6. **所有组件无状态**
   除存储文件外，Agent、中控、接口均无状态。每次请求从存储读取数据，处理完毕后不保留会话历史。
7. **降级即常态**
   AI 断连自动降级，恢复自动补偿。降级不是异常状态，而是系统的默认运行态。

---

## 快速使用

### 启动 API 服务

```bash
cd dpim
uv sync                    # 首次：同步环境
uv run python main.py serve  # 启动 FastAPI 服务，默认 :8000
```

服务启动后访问 http://localhost:8000/docs 查看 OpenAPI 文档。

### 写入与检索

```bash
# 写入事件
uv run python main.py ingest "用户询问了 Python 异步编程"

# 检索
uv run python main.py query "Python 异步"

# 查看系统状态
uv run python main.py status

# 查看存储文件路径
uv run python main.py storage-path
```

### 安装独立 CLI

```bash
cd dpimCLI
pip install -e .
dpim --help      # 查看全部 24 条命令
dpim status      # 查看系统状态
dpim shell       # 进入交互式 Shell 模式
```

---

## WebUI 启动

```bash
cd dpimWebUI

# 安装依赖（首次）
pnpm install

# 开发模式（热更新，代理后端 localhost:8000）
pnpm dev

# 生产构建
pnpm build

# 类型检查（无需构建即可验证代码）
pnpm typecheck

# 单元测试
pnpm test

# 访问地址
# 开发：http://localhost:5173
# 生产：dist/ 目录由后端 FastAPI 托管
```

前端通过 Vite 代理（vite.config.ts 配置）访问后端 API，开发时无需配置跨域。

---

## WebUI 界面说明

dpim-webui 提供五个标签页管理 DPIM 系统的全部功能：

| 标签页 | 功能 |
|--------|------|
| **配置** | 系统参数可视化编辑（存储/模型与提供商/Agent 管线/检索/系统/前端 6 板块），状态校验密钥锁保护 |
| **信息列表** | 事件分页展示、类型/状态筛选、行内编辑、删除确认、新建事件、失败重试 |
| **信息图** | D3.js 力导向知识图谱 + ForceAtlas2 预布局，节点按类型着色（data=浅蓝/interaction=绿/system=蓝），边带箭头标记，双向边弯曲错开；点击节点查看/编辑详情面板，面板可向下收起释放画布空间；节点上限 400 |
| **检索** | 三维度搜索：综合检索（分组展示◆事件原文/■知识节点/▲系统事件）/ 事件原文 / 知识节点；高级可折叠筛选面板（来源类型、图扩散跳数、最低置信度、结果数量）；翻页功能（服务端 offset 分页） |
| **信息传入** | 人工写入事件（内容 + 类型 auto/interaction/data/source）+ AI 状态监控（就绪/未连接，30s 轮询）+ 处理历史（localStorage 10 条，5s 轮询状态）+ 补偿积压事件按钮 + AI 调用日志面板（5s 轮询，可展开看全文） |

核心交互：检索结果可跳转到信息图定位节点；信息传入历史可跳转到信息列表定位事件；所有写操作受状态校验密钥保护。组件库：Naive UI（暗色模式）。

---

## CLI 工具

dpim-cli 是通过 HTTP API 管理 DPIM 系统的命令行工具，与 dpim-webui 平级。安装后提供 `dpim` 命令，支持单次命令模式和交互式 Shell 模式。

### 命令一览

| 类别 | 命令 | 说明 |
|------|------|------|
| 系统 | `status` | 查看系统健康状态 |
|  | `state-key` | 显示状态校验密钥 |
| 事件 | `ingest <内容>` | 写入事件 [--type auto\|interaction\|data\|source] |
|  | `events` | 分页事件列表 [--type] [--status] [--limit] |
|  | `event <id>` | 查看事件详情 |
|  | `event edit/retry/skip/unskip/delete <id>` | 事件操作 |
| 节点 | `nodes` | 分页节点列表 [--type] [--limit] |
|  | `node <id>` | 查看节点详情 |
|  | `node create` | 创建节点 [--title] [--content] [--type] |
|  | `node edit/delete <id>` | 节点操作 |
| 边 | `edge create/delete` | 边操作 [--source] [--target] [--relation] |
| 检索 | `search <关键词>` | 混合检索 [--type] [--hops] [--limit] |
|  | `feedback <id>` | 反馈 --accept \| --reject |
| 配置 | `config` / `config set <k> <v>` | 配置管理 |
| 图谱 | `graph clear` | 清空图谱 |

### 输出格式

支持 `--format table|json|yaml` 全局选项切换输出格式。

### Shell 模式

交互式 Shell 支持语法高亮、Tab 补全、命令历史、执行计时，适合人工探索和管理：

```bash
dpim shell
dpim shell --api http://remote:8000
dpim shell -c 'ingest "测试内容"'   # 单条命令后退出
```

详细说明和所有命令参见 [dpimCLI/](dpimCLI/)。

---

## 设计描述

系统采用四层架构：

- **接口层**：FastAPI 22 端点 + Typer CLI，对外统一 API
- **中控层**：asyncio.Queue 调度 + 可选 Agent 管线（Cr/In/Gr/Meta 四角色，提示词在 `dpim/prompts/`）+ 补偿调度（退避/试探/暂停）
- **信息线层**：SQLite + FTS5，不可变事件日志，完全独立于 AI
- **信息图层**：NetworkX + JSON，知识图谱节点与边，双向溯源（source_refs / graph_refs）

详细设计参见 docs/ 目录下的设计文档。

---

## 技术栈

| 层 | 技术栈 |
|----|--------|
| 后端语言 | Python 3.14 |
| Web 框架 | FastAPI + uvicorn |
| 数据校验 | Pydantic V2 |
| 关系存储 | aiosqlite（SQLite + FTS5）|
| 图存储 | NetworkX（内存）+ JSON 持久化 |
| LLM SDK | openai SDK + instructor |
| 内置 CLI | Typer |
| 进程管理 | asyncio |
| 前端框架 | Vue 3 + TypeScript |
| 构建工具 | Vite |
| UI 组件 | Naive UI（暗色模式）|
| 可视化 | D3.js + ForceAtlas2（graphology）|
| 独立 CLI | httpx + prompt-toolkit + tabulate + PyYAML |
| 代码质量 | ruff + mypy（后端）/ vue-tsc（前端）|
| 测试 | pytest 235 用例 / vitest 41 用例，全部通过 |

---

## 项目目录布局

```
DPIM/
├── dpim/                     # 唯一后端
│   ├── core/                 # 核心层（config / models / database / event_store / graph_store / search / llm / state）
│   ├── controller/           # 中控层（orchestrator / compensator / task_memory / prompt_loader / tools/）
│   ├── interface/            # 接口层（api.py 22 端点 / cli.py）
│   ├── prompts/              # 四角色提示词（已定稿）
│   ├── tests/                # pytest 235 用例
│   ├── data/                 # 运行时存储文件
│   ├── main.py               # 程序入口
│   ├── pyproject.toml        # 项目配置
│   └── dpim.json             # 结构化配置（运行时持久化）
├── dpimWebUI/                # Vue 3 前端
├── dpimCLI/                  # 独立 CLI 客户端
├── share/                    # 共享契约（protocol.md v1.9 / protocol.ts）
├── docs/                     # 设计文档
└── AGENTS.md                 # Agent 工作引导

存储文件：dpim/data/memory.db（SQLite）和 dpim/data/graph.json（JSON），均支持人工编辑。
```