# 双区智能内存 DPIM

Double-Place Intelligence Memory — 独立于 LLM 上下文窗口的外部记忆模块。

---

## 工程简介

DPIM 是一个双区智能贮存系统，同时承担两个角色：

- 第二上下文：存储外部 Agent 与用户的交互记录，替代 LLM 上下文窗口
- 长期知识库：存储搜索到的事实和用户导入的资料，供后续检索与引用

系统通过不可变事件日志（信息线层）与知识图谱（信息图层）的双区结构，在 AI 可用时持续衍生结构化知识，在 AI 不可用时退化为基础全文检索存储。

---

## 功能体现

- 事件写入与 FTS5 全文索引，支持 interaction / data / source 三种类型，原子写入接口（insert_event）
- 事件状态机：raw → indexed → linked（终态），failed / skipped 异常路径
- 知识图谱节点与边的人工增删改查，JSON 文件持久化（防抖自动保存，5 次修改阈值）
- 混合检索：FTS5 召回 → 2 跳图扩散 → RRF 融合排序（无 Agent 默认仅 FTS5）
- 事件源证锚定：每条图节点必含 source_refs 与 evidence_quote，杜绝幻觉
- 删除保护：system 和 data 类型节点失去所有源证时禁止删除
- 降级与补偿：LLM 不可用时自动降级，恢复后批量补偿积压事件
- 线程安全的 AI 可用性状态管理（AIState 单例封装）
- 启动时配置校验：LLM 地址格式 + API Key 空值警告
- FastAPI 接口层，8 个 REST 端点（统一成功响应信封）
- Typer CLI 管理，9 个命令

---

## 运行原则

1. 无 Agent 模式为默认运行态
   系统不依赖任何 AI 模型或 Agent 提示词即可完整运行。启动后默认处于降级态，事件写入、全文检索、CLI 管理、存储文件人工编辑等功能立即可用。

2. Agent 模式为可选增强
   信息处理 Agent、图构建 Agent、元认知裁判仅在提示词配置后才会参与工作流。未配置时系统不受影响。

3. 核心存储独立于 AI
   信息线层（SQLite + FTS5）和信息图层（NetworkX + JSON）构成核心存储，所有基础操作不调用任何 LLM。

4. 存储文件开放可编辑
   data/memory.db 为标准 SQLite 数据库，data/graph.json 为带缩进的 JSON 文件，均支持人工编辑后重启生效。

5. 配置方式
   所有配置通过 .env 文件或 DPIM_ 前缀环境变量设置。默认连接 localhost:11434（Ollama），切换 OpenAI 仅需修改环境变量。

6. LLM 服务可选，降级自动生效
   系统启动时 ai_available = False，以降级模式运行。检测到 LLM 后自动升级，断开后自动降级，恢复后自动补偿。

7. 所有组件无状态
   除存储文件外，Agent、中控、接口均无状态。每次请求从存储读取数据，处理完毕后不保留会话历史。

---

## 快速使用

```bash
# 进入项目目录
cd dpim

# 同步环境（首次）
uv sync

# 启动 API 服务
uv run python main.py serve

# 写入事件
uv run python main.py ingest "用户询问了 Python 异步编程"

# 检索
uv run python main.py query "Python 异步"

# 查看系统状态
uv run python main.py status

# 查看存储文件路径
uv run python main.py storage-path
```

API 服务启动后访问 http://localhost:8000/docs 查看 OpenAPI 文档。

---

## WebUI 启动

```bash
# 进入前端项目目录
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

## 设计描述

系统采用四层架构：

- 信息线层：SQLite + FTS5，不可变事件日志，完全独立于 AI
- 信息图层：NetworkX + JSON，知识图谱节点与边
- 中控层：asyncio.Queue 调度 + 可选 Agent 管线
- 接口层：FastAPI + Typer，对外统一 API 和 CLI

详细设计参见 docs/ 目录下的设计文档。

---

## 其他说明

- 后端技术栈：Python 3.14 + asyncio + FastAPI + SQLite(FTS5) + NetworkX + openai SDK + instructor + Typer
- 前端技术栈：Vue 3 + TypeScript + Vite + Naive UI + D3.js
- 包管理：后端 uv（64 依赖） / 前端 pnpm
- 测试：pytest 113 用例 + vitest 13 用例，全部通过
- 代码质量：ruff + mypy（后端）/ vue-tsc（前端）
- 存储文件：data/memory.db（SQLite）和 data/graph.json（JSON），位于 dpim/data/
