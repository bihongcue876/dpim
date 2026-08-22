# DPIM CLI

> 由Deepseek v4 flash 0731编写于2026-8

DPIM 命令行交互工具 — 通过 HTTP API 管理双区智能内存（事件线层 + 知识图谱层）。

纯 REST 客户端，不含业务逻辑：所有数据操作均转发给 DPIM 后端服务（`dpim/interface/api.py`，23 端点）。适合脚本化批处理、状态观察、以及交给其他 AI Agent 作为只读/受控操作入口使用。

## 一、安装

```bash
# 需先启动后端服务（仓库根目录）
cd dpim && uv run python main.py serve   # 默认 http://127.0.0.1:8000

# 安装 CLI（可编辑模式，开发推荐）
cd dpimCLI && pip install -e .

# 验证
dpim --help
```

依赖：Python ≥ 3.12，`httpx` / `prompt-toolkit` / `tabulate` / `pyyaml`（随包自动安装）。

### 环境变量配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DPIM_API_URL` | `http://localhost:8000` | 后端地址 |
| `DPIM_FORMAT` | `table` | 默认输出格式（table / json / yaml） |
| `DPIM_TIMEOUT` | `30` | 请求超时（秒） |
| `DPIM_COLOR` | `on` | 颜色开关 |

也可用 `--api URL` / `--format FORMAT` 全局参数临时覆盖（优先级高于环境变量）。

## 二、命令表

单次命令模式：`dpim <command> [options]`。

### 系统状态

| 命令 | 说明 |
|------|------|
| `dpim status` | 系统健康状态（AI 可用性、事件/节点规模、图统计） |
| `dpim state-key` | 显示状态校验密钥（写操作前的一致性校验用） |

### 事件管理（线层）

| 命令 | 说明 |
|------|------|
| `dpim ingest <内容> [--type interaction\|data\|source]` | 写入事件 |
| `dpim events [--type] [--status] [--limit N] [--offset N]` | 分页事件列表 |
| `dpim event view <id>` | 事件详情 |
| `dpim event edit <id> <新内容>` | 修订事件 raw_content |
| `dpim event retry <id>` | 重试 failed 事件（状态 → indexed） |
| `dpim event skip <id>` | 跳过事件（不参与构图） |
| `dpim event unskip <id>` | 取消跳过 |
| `dpim event delete <id>` | 删除事件（有受保护节点依赖时拒绝） |

### 节点管理（图层）

| 命令 | 说明 |
|------|------|
| `dpim nodes [--type system\|interaction\|data] [--limit N] [--offset N]` | 分页节点列表 |
| `dpim node view <id>` | 节点详情（含关联边） |
| `dpim node create --title <标题> [--content <内容>] [--type data] [--event <源事件ID>]` | 手动创建节点 |
| `dpim node edit <id> <新内容>` | 修改节点 content |
| `dpim node delete <id> [--force]` | 删除节点（system 类型 / 有有效源证时需 --force） |

### 边管理

| 命令 | 说明 |
|------|------|
| `dpim edge create --source <id> --target <id> --relation <关系> [--event <证据事件ID>]` | 创建边 |
| `dpim edge delete --source <id> --target <id>` | 删除边 |

### 检索与反馈

| 命令 | 说明 |
|------|------|
| `dpim search <关键词> [--type all\|interaction\|data\|system] [--hops N] [--limit N] [--offset N]` | 混合检索（FTS5 + 图扩散双向 RRF） |
| `dpim feedback <结果ID> --accept\|--reject` | 检索结果反馈（作用于节点置信度） |

### 配置与图谱

| 命令 | 说明 |
|------|------|
| `dpim config list` | 列出全部配置项（密钥已掩码） |
| `dpim config set <key> <value>` | 修改配置项（持久化 dpim.json；存储路径类重启生效） |
| `dpim graph clear` | 清空图谱（事件层不动，图层可由管线重建） |

### 交互模式

| 命令 | 说明 |
|------|------|
| `dpim shell` | 进入交互式 Shell（无参数直接运行 `dpim` 同效） |

## 三、输出格式

三种格式，`--format` 参数或 Shell 内 `format <fmt>` 切换：

- **table**（默认）：带颜色的对齐表格 / 摘要块，适合人读
- **json**：后端原始响应，适合管道处理（`dpim search 关键词 --format json | jq ...`）与外部程序解析
- **yaml**：结构化输出，配置项浏览友好

### 错误处理

- 连接失败：`错误: 无法连接到 DPIM 服务 - ...` → 退出码 1
- API 错误：`错误 [<code>]: <message>`（如 422 值域校验、404 不存在、删除保护拒绝）→ 退出码 1
- 成功 → 退出码 0（便于脚本判断 `&&` / `||`）

## 四、Shell 模式

```bash
dpim          # 或 dpim shell
```

启动时连接后端并打印横幅（状态 / AI 可用性 / 事件与节点数）。特性：

- **命令复用**：所有单次命令均可直接使用（如 `search "记忆" --hops 3`）
- **Tab 补全**：命令名、子命令、选项、选项值（--type 等）上下文补全
- **历史记录**：↑/↓ 翻阅，`history` 查看
- **引号支持**：`ingest "一段 带空格 的内容"`

Shell 专属控制命令：

| 命令 | 说明 |
|------|------|
| `help` / `-h` | 命令帮助 |
| `quit` / `exit` / `\q` | 退出 |
| `format <table\|json\|yaml>` | 切换输出格式 |
| `timing on\|off` | 命令耗时显示 |
| `clear` | 清屏 |
| `history` | 查看历史 |

## 开发与测试

```bash
cd dpimCLI
pip install -e ".[dev]"
pytest tests/ -q
```

测试全部 mock `api_client`（无网络依赖）；端到端冒烟需先启动后端。

## 边界

- 本 CLI 为纯 REST 客户端，协议契约以 `share/protocol.md` 为权威
- 密钥相关字段一律掩码显示，不支持明文读取
- 图谱渲染请使用 WebUI（`dpimWebUI/`）；CLI 定位是脚本化与状态观察
