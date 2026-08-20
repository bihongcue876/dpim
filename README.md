# 双区智能内存 DPIM
Double-Place Intelligence Memory — 独立于 LLM 上下文窗口的外部记忆系统。

## 工程简介

DPIM 是一个双区智能贮存系统，同时承担两个角色：

- **第二上下文**：存储外部 Agent 与用户的交互记录，替代 LLM 的上下文窗口
- **长期知识库**：存储搜索到的事实和用户导入的资料，供后续检索与引用

系统通过不可变事件日志（信息线层）与知识图谱（信息图层）的双区结构，在 AI 可用时持续衍生结构化知识，在 AI 不可用时退化为基础全文检索存储。

## 快速使用

### 启动后端

```bash
cd dpim
uv sync                       # 首次：同步环境
uv run python main.py serve   # 启动服务，默认 :8000
```

启动后访问 http://localhost:8000/docs 查看接口文档。

### 启动前端 WebUI

```bash
cd dpimWebUI
pnpm install
pnpm dev      # 开发：http://localhost:5173
```

### 命令行管理

```bash
uv run python main.py ingest "用户询问了 Python 异步编程"   # 写入事件
uv run python main.py query "Python 异步"                    # 检索
uv run python main.py status                                 # 查看状态
```

### 独立 CLI（可选）

```bash
cd dpimCLI
pip install -e .
dpim --help   # 24 条命令
dpim shell    # 交互式 Shell
```

## 核心特性

- **双区存储**：不可变事件日志（SQLite + FTS5）+ 知识图谱（NetworkX + JSON），双向溯源
- **智能可选**：Cr/In/Gr/Meta 四角色 Agent 管线自动衍生结构化知识，无 AI 时降级为基础全文检索
- **降低错觉**：每条图节点锚定来源事件，元认知裁判做子串校验
- **自动维护**：AI 自动扫描冗余/僵尸节点并合并、删改（降级保连接、恢复自动补偿）

## 项目结构

```
DPIM/
├── dpim/         # 后端（core / controller / interface / prompts / tests）
├── dpimWebUI/    # Vue 3 前端
├── dpimCLI/      # 独立 CLI 客户端
├── share/        # 共享契约（protocol.md）
└── docs/         # 设计文档

存储文件：dpim/data/memory.db（SQLite）和 dpim/data/graph.json（JSON）
```

详细设计见 `docs/` 与 `share/protocol.md`。