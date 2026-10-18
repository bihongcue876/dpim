# DPIM CLI

> 由Deepseek v4 flash 0731编写于2026-8

DPIM 命令行交互工具 — 通过 HTTP API 管理双区智能内存（事件线层 + 知识图谱层）。

纯 REST 客户端，不含业务逻辑：所有数据操作均转发给 DPIM 后端服务（`dpim/interface/api.py`，**45 端点**）。适合脚本化批处理、状态观察、以及交给其他 AI Agent 作为只读/受控操作入口使用。

> **覆盖范围说明（2026-10-17 更新）**：本 CLI 覆盖 **19 命令 / 47 操作**，对应 **45 端点中的 44 个**——
> 唯一没覆盖的是 `POST /logs/client`（浏览器把前端日志回传本地文件，CLI 不在浏览器里，无意义；要看本地日志用 `dpim logs`）。
>
> **库作用域（v1.29/v1.30）**：读命令一律支持 `--repo <id>`（缺省 = 活动库），列表/检索类另支持 `--repos a,b`（联查多个书目）。
> 写命令（`event edit/delete`、`node edit/delete`、`edge create/delete`、`graph clear`）**只能作用于活动库**——
> 后端语义如此（只有 `POST /ingest` 能带 `repo_id`）；要改别的库，先 `dpim repo activate <id>`。CLI 不越权、也不静默换库。
>
> **备份恢复仍然只有本地 CLI**：`cd dpim && python main.py restore <stamp> --yes`
> （须先停服务——内存图会陈旧；且会强制先做一次安全备份）。本地 CLI 另覆盖 `serve / query / status / verify / logs / trash-list` 等离线操作。
> 注意命令名归属：`dpim` 是本 REST CLI；`python main.py` 才是本地直连 CLI。

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
| `dpim ingest <内容> [--type interaction\|data\|source] [--repo <id>]` | 写入事件（`--repo` 指定目标库，缺省活动库） |
| `dpim events [--type] [--status] [--limit N] [--offset N] [--repo <id>] [--repos a,b]` | 分页事件列表（`--repos` = 联查多库，按 content_hash 去重） |
| `dpim event view <id> [--repo <id>]` | 事件详情（跨库必须带 `--repo`，否则只在活动库里找 → 404） |
| `dpim event edit <id> <新内容>` | 修订事件 raw_content（活动库） |
| `dpim event retry <id>` | 重试 failed 事件（状态 → indexed） |
| `dpim event skip <id>` | 跳过事件（不参与构图） |
| `dpim event unskip <id>` | 取消跳过 |
| `dpim event delete <id>` | 删除事件（有受保护节点依赖时拒绝；删除前留档到回收站） |

### 节点管理（图层）

| 命令 | 说明 |
|------|------|
| `dpim nodes [--type system\|interaction\|data] [--limit N] [--offset N] [--repo <id>] [--repos a,b]` | 分页节点列表 |
| `dpim node view <id> [--repo <id>]` | 节点详情（含关联边） |
| `dpim node create --title <标题> [--content <内容>] [--type data] [--event <源事件ID>]` | 手动创建节点 |
| `dpim node edit <id> <新内容>` | 修改节点 content |
| `dpim node delete <id> [--force]` | 删除节点（system 类型 / 有有效源证时需 --force） |

### 边管理

| 命令 | 说明 |
|------|------|
| `dpim edge create --source <id> --target <id> --relation <关系> [--event <证据事件ID>]` | 创建边 |
| `dpim edge delete --source <id> --target <id>` | 删除边 |
| `dpim edges [--node <id>] [--source <id>] [--target <id>] [--relation <R>] [--limit N] [--offset N] [--repo <id>] [--repos a,b]` | **边列表**（v1.37 `GET /edges`）：`--node` 两侧命中；按 (source,target) 稳定排序；`--limit` 默认 200、上限 5000（越界后端 400） |

### 检索与反馈

| 命令 | 说明 |
|------|------|
| `dpim search <关键词> [--type all\|interaction\|data\|system] [--hops N] [--limit N] [--offset N] [--repos a,b]` | 混合检索（FTS5 + 图扩散双向 RRF；`--repos` 多库 = 联合检索） |
| `dpim feedback <结果ID> --accept\|--reject [--repo <id>]` | 检索结果反馈（作用于节点置信度；跨库结果必须带 `--repo`） |

### 库管理（v1.29+，11 个端点）

| 命令 | 说明 |
|------|------|
| `dpim repo list` | 库登记列表（活动库 / 休眠 / 未加载原因 / 计数） |
| `dpim repo show <id>` | 库详情（含事件状态分布） |
| `dpim repo create --name <名> [--group <分组>] [--note <备注>] [--kind managed\|external] [--root <目录>]` | 建库（managed 落分组目录；external 只登记既有目录） |
| `dpim repo update <id> [--name] [--note] [--group] [--root] [--managed true\|false]` | 改库信息 / 受管开关（false = 休眠）/ 外部库重指向 |
| `dpim repo activate <id>` | 切换活动库（写命令的作用目标） |
| `dpim repo refresh <id>` | 显式刷新/修复：对账源证 → 脏则落盘 → 回报统计 |
| `dpim repo generate <id>` | 库级联合生成知识（该库全部待构图事件入队；AI 不可用 409） |
| `dpim repo adopt --root <目录> [--name] [--group] [--no-missing]` | 收养既有目录（至少有一个库文件；缺件默认补空件） |
| `dpim repo rebuild` | 重建登记表（坏索引恢复；**绝不删任何数据文件**） |
| `dpim repo delete <id>` | 摘除登记（**不删磁盘文件**；默认库与活动库不可摘） |
| `dpim repo purge <id> --yes` | 清除书目：后端**先自动整库备份**再删 `memory.db` + `graph.json`；必须显式 `--yes` |

### 存储维护（v1.30，5 个端点）

| 命令 | 说明 |
|------|------|
| `dpim maintenance backup [--note <备注>] [--repo <id>]` | 整库备份（`VACUUM INTO` 在线副本 + graph.json + manifest） |
| `dpim maintenance backups [--repo <id>]` | 列出整库备份（新到旧） |
| `dpim maintenance verify [--repo <id>]` | **只读**一致性校验（SQLite 完整性/外键、FTS 行数、`graph_ops` 重放 == 内存图、悬空源证、缺 data 节点） |
| `dpim maintenance ops [--limit N] [--offset N] [--repo <id>]` | 图层操作日志（审计：谁 / 何时 / 因何改了图） |
| `dpim maintenance checkpoint [--repo <id>]` | WAL 检查点（TRUNCATE） |

### 本地日志与回收站（v1.31）

| 命令 | 说明 |
|------|------|
| `dpim logs [--kind backend\|frontend] [--date YYYY-MM-DD] [--level L] [--keyword K] [--tail N]` | 翻看本地日志尾部（按天轮转、前后端分文件） |
| `dpim trash list [--repo <id>]` | 回收站留档清单（事件/节点/**整图**，按留档时间倒序） |
| `dpim trash restore <id> [--kind event\|node\|graph] [--repo <id>]` | 从留档恢复（事件/节点**按原 id** 重新入库；节点连带尽力补回关联边；`--kind graph` 为整图留档，**合并式**补回——已存在的节点/边跳过、不覆盖、不造悬空边） |

### Agent 运维

| 命令 | 说明 |
|------|------|
| `dpim agent logs [--limit N] [--full]` | AI 调用日志（环形缓冲，新→旧；`--full` 取全文，后端 `AGENT_LOGS_FULL=false` 时忽略） |
| `dpim agent compensate [--repo <id>]` | 手动触发补偿：积压 raw/indexed 事件重入队 |
| `dpim agent maintain [--mode update\|compress] [--repo <id>]` | 手动触发图维护（`update` 两阶段结构优化 / `compress` 删繁就简） |

### 配置与图谱

| 命令 | 说明 |
|------|------|
| `dpim config list` | 列出全部配置项（密钥已掩码） |
| `dpim config set <key> <value>` | 修改配置项（持久化 dpim.json；存储路径类重启生效） |
| `dpim config probe <提供商> [--base-url U] [--api-key K]` | 联网探测该提供商的可用模型列表（探测失败**不报错退出**，错误摘要照样显示） |
| `dpim graph clear` | 清空图谱（事件层不动；**v1.42 起清空前自动把整图留档到 `trash/graphs/`**，可 `trash restore --kind graph` 找回；线层事件由「已入图」回到「待处理」，AI 可用时补偿会重新入图） |

### 交互模式

| 命令 | 说明 |
|------|------|
| `dpim shell` | 进入交互式 Shell（无参数直接运行 `dpim` 同效） |

## 三、输出格式

三种格式，`--format` 参数或 Shell 内 `format <fmt>` 切换：

- **table**（默认）：带颜色的对齐表格 / 摘要块，适合人读
- **json**：后端原始响应，适合管道处理（`dpim search 关键词 --format json | jq ...`）与外部程序解析
- **yaml**：结构化输出，配置项浏览友好

**对话指令结果**：`dpim ingest "^compress"` 等输入 `^` 指令时，后端不创建事件、
直接返回执行结果（显示为「指令结果 + 消息」）；支持的指令见 WebUI 帮助页或
协议 4.5 节（^compress / ^update / ^merge / ^delete / ^data 等）。

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
pytest tests/ -q          # 105 用例，全部 mock api_client（无网络依赖）
```

测试全部 mock `api_client`（无网络依赖）；端到端冒烟需先启动后端。**注意**：本包依赖 `tabulate` / `prompt-toolkit` / `pyyaml`，
用项目内 venv 跑测试前需先装上（`dpim/.venv` 里默认没有这三个）。

## 边界

- 本 CLI 为纯 REST 客户端，协议契约以 `share/protocol.md` 为权威
- 密钥相关字段一律掩码显示，不支持明文读取
- **写命令只作用于活动库**（后端语义：只有 `POST /ingest` 能带 `repo_id`）；要改别的库先 `dpim repo activate <id>`，
  CLI 不做静默换库
- **破坏性操作一律要显式确认**：`repo purge` 必须带 `--yes`（后端还会先自动整库备份）
- 备份**恢复**不在本 CLI（须停服务），走 `cd dpim && python main.py restore <stamp> --yes`
- 图谱渲染请使用 WebUI（`dpimWebUI/`）；CLI 定位是脚本化与状态观察
