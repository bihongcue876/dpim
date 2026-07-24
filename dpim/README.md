# DPIM — Double-Place Intelligence Memory

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

信息处理 Agent、图构建 Agent、元认知裁判**仅在提示词配置后**才会参与工作流。未配置时系统不受影响，事件停留在 `indexed` 状态等待处理。

### 3. 核心存储独立于 AI

信息线层（SQLite + FTS5）和信息图层（NetworkX + JSON）构成核心存储，所有基础操作**不调用任何 LLM**，确保存储层的可靠性和响应速度。

### 4. 存储文件开放可编辑

- `data/memory.db`：标准 SQLite 数据库，可用 `sqlite3`、DB Browser 等工具直接操作
- `data/graph.json`：带缩进的 JSON 文件，可用任意文本编辑器修改
- 手动编辑后重启服务即可生效
- 运行 `dpim storage-path` 查看文件准确路径

### 5. 配置方式

所有配置通过 `.env` 文件或 `DPIM_` 前缀环境变量设置：

```bash
# 最小配置（使用默认 Ollama 地址时无需任何配置）
python main.py serve

# 切换到 OpenAI
DPIM_LLM_BASE_URL=https://api.openai.com/v1 \
DPIM_LLM_API_KEY=sk-xxx \
DPIM_LLM_MODEL_NAME=gpt-4o-mini \
python main.py serve
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

详见 `docs/项目结构描述管理.md`。

## 设计文档

- `docs/DPIM设计大纲20260724.md` — 顶层概念与架构
- `docs/DPIM设计详纲20260724.md` — 完整设计参考
- `docs/项目结构描述管理.md` — 模块与函数清单
- `docs/测试结论.md` — 测试记录
- `docs/执行进度.md` — 实现状态追踪
