# DPIM Spec 规约

> 版本：1.5
> 日期：2026-08-01
> 范围：原型阶段 + dpim-webui + 状态校验密钥 + 事件内容修订 + system 源过滤 + BYOK 多模型网关 + Agent 管线

---

### 一、项目定义

DPIM（Double-Place Intelligence Memory）是一个独立于大模型上下文窗口的外部记忆模块。系统通过不可变日志（信息线层）与知识图谱（信息图层）的双区结构，在 AI 可用时持续衍生结构化知识，在 AI 不可用时降级为基础全文检索存储。

---

### 二、核心实体

#### 2.1 事件 (Event)

事件是系统的最小存储单元，所有信息以事件形式写入信息线层。事件写入后默认不可变，但可通过 `PUT /events/{event_id}` 端点手动修订其 raw_content（同步更新 FTS5 索引，自动刷新状态校验密钥）。

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| event_id | string | 是 | 全局唯一，格式 `{timestamp_ms}-{random_hex_8}` |
| created_at | string | 是 | ISO8601 时间戳 |
| raw_content | string | 是 | 原始内容，不可变 |
| content_hash | string | 是 | BLAKE3 前 16 位十六进制 |
| event_type | enum | 是 | interaction / data / source |
| status | enum | 是 | raw / indexed / linked / failed / skipped |
| graph_refs | string[] | 否 | 关联的图节点 ID 列表 |

**事件类型：**

- `interaction`：对话记录、Agent 决策与行动轨迹。可多次压缩。
- `data`：搜索事实、用户导入资料。最多压缩一次。
- `source`：原始证据。仅存于线层，不进入图构建。

**状态流转：**

```
raw → indexed → linked
       ↓          ↑
     failed ──────┘ (手动重试)
     skipped (人工跳过，不参与处理)
```

- `raw`：刚写入
- `indexed`：已建全文索引，基础检索可用
- `linked`：图构建完成，终态
- `failed`：AI 处理异常
- `skipped`：人工跳过

#### 2.2 图节点 (GraphNode)

图节点是信息图层的核心单元，由 AI 从事件中提炼或手动创建。

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| node_id | string | 是 | 全局唯一 |
| title | string | 是 | 简洁标题，≤60 字符 |
| content | string | 是 | 摘要或完整描述 |
| node_type | enum | 是 | system / interaction / data |
| source_refs | SourceRef[] | 是 | 源证指针数组 |
| confidence | number | 是 | 0.0 ~ 1.0 |
| metadata | object | 是 | 扩展字段 |

**metadata 结构：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| evidence_quote | string | 是 | 源事件原文摘录 |
| tags | string[] | 否 | 标签列表 |
| protected | boolean | 否 | 是否排除在自动操作之外 |
| conflict | boolean | 否 | 是否存在未解决的冲突 |

**节点类型行为：**

- `system`：手动创建。Agent 不得修改其 content，允许建立边。失去所有源证时禁止删除关联事件。
- `interaction`：从交互事件提取。允许自动更新和合并。失去所有源证时可删除。
- `data`：从资料事件提取。允许追加但不得概括。失去所有源证时禁止删除关联事件。

**SourceRef 结构：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| event_id | string | 是 | 来源事件 ID |
| valid | boolean | 是 | 事件删除时标记 false |
| hash | string | 是 | 对应事件的 content_hash |

#### 2.3 图边 (GraphEdge)

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| source | string | 是 | 源节点 ID |
| target | string | 是 | 目标节点 ID |
| relation | string | 是 | 自然语言关系短语 |
| evidence_event_id | string | 是 | 来源事件 ID |
| note | string | 否 | 额外描述 |

(source, target, relation) 三元组自然唯一，不设独立 ID。

---

### 三、状态校验密钥

系统使用一个不透明的状态校验密钥（UUID）作为前后端数据一致性的凭证。它不是内容的哈希值，不暴露任何数据结构信息，也不用于加密。它的唯一作用是回答："前端持有的这份数据，和后端当前的数据，是不是同一份？"

**后端规则：**

- `GET /state-hash` 返回当前 UUID 及最近变更时间
- 任何写操作（ingest、delete、modify、status change）完成后自动刷新 UUID
- AI 可用性切换时也刷新 UUID
- 系统启动时生成初始 UUID

**前端流程：**

1. 页面加载时调 `GET /state-hash` 获取 UUID，存入页面内存
2. 用户执行写操作（保存配置、删除事件、创建节点等）时，提交前再次调 `GET /state-hash` 比对
3. 密钥一致 → 允许提交 → 提交成功后重新获取 UUID 作为新基准
4. 密钥不一致 → 拒绝提交，刷新页面数据但保留用户编辑内容，提示用户重新确认

**不受限操作：** 查看详情、检索查询、搜索反馈（有用/无用）不校验密钥，始终可用。

---

### 四、Agent 体系

系统包含两个功能 Agent 和一个内嵌于总控的元认知裁判。所有 Agent 无状态，每次调用从存储拉取数据。

#### 4.1 信息处理 Agent

**职责**：解析 raw_content，自动分类提取。

**输入**：
- `raw_content`：事件原始文本
- `existing_titles`：最多 5 个相关已有节点标题

**输出**：InformationFragment

| 字段 | 类型 | 说明 |
|------|------|------|
| interaction | string[] | 对话流转、用户意图、Agent 决策 |
| data | string[] | 事实陈述、引用来源 |
| source | string | 原始内容保留（若需作为证据），否则为空字符串 |

#### 4.2 图构建 Agent

**职责**：将 interaction 和 data 片段转化为知识节点和边。

**输入**：
- `fragments`：信息处理 Agent 输出的 interaction 和 data 片段
- `context_nodes`：最多 10 个近邻图层节点

**输出**：GraphBuildOutput

| 字段 | 类型 | 说明 |
|------|------|------|
| new_nodes | NodeCreate[] | 待创建节点 |
| new_edges | EdgeCreate[] | 待创建边 |
| merged_into | string \| null | 合并到已有节点的 node_id |

**NodeCreate**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| title | string | 是 | 节点标题 |
| content | string | 是 | 节点内容 |
| node_type | enum | 是 | interaction / data |
| confidence | number | 是 | 初始置信度 |
| evidence_quote | string | 是 | 源事件原文摘录 |

**EdgeCreate**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| source | string | 是 | 源节点 title 或已有 node_id |
| target | string | 是 | 目标节点 title 或已有 node_id |
| relation | string | 是 | 关系短语 |
| evidence_event_id | string | 是 | 来源事件 ID |

#### 4.3 元认知裁判

**职责**：审查图构建 Agent 输出，决定通过或驳回。

**输入**：
- `build_output`：图构建 Agent 完整输出
- `source_event`：来源事件对象

**输出**：MetaCogVerdict

| 字段 | 类型 | 说明 |
|------|------|------|
| verdict | enum | pass / fail |
| issues | Issue[] | 问题列表 |

**Issue**：

| 字段 | 类型 | 说明 |
|------|------|------|
| type | enum | hallucination / illegal_edge / conflict / empty_node |
| description | string | 问题描述 |
| suggestion | string | 修正建议 |

**审查规则**：
- 边合法性：source 和 target 必须存在于图中，纯逻辑检查
- 冲突检测：新关系是否与已有关系矛盾，调 LLM 语义判断
- 来源锚定：evidence_quote 是否出现在 raw_content 中，优先子串匹配
- 空节点检查：content 不得为空

---

### 五、工作流规范

#### 5.1 增加 (Ingest)

**流程**：

1. 写入事件，状态为 raw
2. 建立 FTS5 索引，状态变为 indexed
3. 检查 AI 可用性，不可用则停留等待补偿
4. 去重预检（Jaccard 相似度 > 0.85 则直接关联已有节点，状态变为 linked）
5. 调用信息处理 Agent 分类提取
6. 若为 source 类，直接状态变为 linked（不产生图节点）
7. 调用图构建 Agent 生成节点和边
8. 元认知裁判审查
9. 审查通过，写入图层，状态变为 linked；不通过则标记 failed

**错误处理**：
- LLM 调用失败重试一次，再失败标记 failed
- 元认知驳回标记 failed

#### 5.2 删除 (Delete)

**删除事件**：

1. 查找 graph_refs 获得关联节点
2. 在节点 source_refs 中标记 valid=false
3. 若节点失去所有有效源证：
   - system 或 data 类型：禁止删除，返回 PROTECTED_NODE 错误
   - interaction 类型：删除节点及其边
4. 物理删除事件行，同步清理 FTS5 索引

**删除节点（人工）**：

1. 检查 source_refs 是否有 valid=true 条目
2. 若有且 force=false，返回警告
3. 若 force=true，删除节点、关联边、FTS5 条目

#### 5.3 修改 (Modify)

**修改节点**：
- 更新 content，重置 confidence 为 0.7
- 同步更新 FTS5 索引

**修改事件状态**：
- 允许：failed → indexed，skipped ↔ indexed
- 不允许：linked → indexed（图已构建）

#### 5.4 降级与补偿

**降级触发**：LLM 连续 3 次失败。

**降级行为**：
- 新事件仅处理到 indexed
- 检索仅用 FTS5
- 健康检查返回 degraded

**恢复条件**：连续 3 次健康检查成功。

**补偿**：查询所有 raw 和 indexed 事件，每批 20 条重新入队处理。

---

### 六、检索规范

**流程**：

1. 关键词召回：events_fts 和 node_fts 同时 FTS5 匹配，各取 top-100，合并去重得 C1
2. 图扩散：以 C1 为种子，2 跳扩散，得分 = 1/(hop+1)，取 top-200 得 C2
3. RRF 融合：`Σ 1/(60 + rank_i)`，交互类乘以时间衰减 `1/(1+days×0.05)`
4. 降级模式：仅执行步骤 1

**检索结果**：

| 字段 | 类型 | 说明 |
|------|------|------|
| node_id | string | 节点或事件 ID |
| title | string | 标题 |
| snippet | string | 匹配片段，前 200 字符 |
| score | number | RRF 得分 |
| source_events | string[] | 源事件 ID 列表 |
| source_type | enum | interaction / data / source / system |
| confidence | number | 节点置信度均值 |
| degraded | boolean | 是否降级结果 |

---

### 七、存储规范

#### 7.1 信息线层 (SQLite)

**events 表**：

```sql
event_id    TEXT PRIMARY KEY
created_at  TEXT NOT NULL
raw_content TEXT NOT NULL
content_hash TEXT NOT NULL
event_type  TEXT NOT NULL CHECK(event_type IN ('interaction','data','source'))
status      TEXT NOT NULL DEFAULT 'raw' CHECK(status IN ('raw','indexed','linked','failed','skipped'))
graph_refs  TEXT  -- JSON 数组
```

索引：created_at, status, event_type

**events_fts 表**（FTS5 虚拟表）：

```sql
event_id UNINDEXED
raw_content
```

#### 7.2 信息图层 (JSON 文件)

文件路径：`./data/graph.json`

```json
{
  "nodes": {
    "node_id": {
      "title": "...",
      "content": "...",
      "node_type": "system",
      "source_refs": [
        {"event_id": "...", "valid": true, "hash": "..."}
      ],
      "confidence": 1.0,
      "metadata": {"evidence_quote": "..."}
    }
  },
  "edges": [
    {
      "source": "node_id",
      "target": "node_id",
      "relation": "subtopic_of",
      "evidence_event_id": "...",
      "note": ""
    }
  ]
}
```

持久化采用原子写入：先写 .tmp 文件，成功后再重命名覆盖原文件。

**node_fts 表**（SQLite FTS5 虚拟表，与 events 同库）：

```sql
node_id UNINDEXED
title
content
```

#### 7.3 反向索引 (内存)

`event_id → [node_id]` 映射，启动时从 graph.json 的 source_refs 重建。

---

### 八、API 端点

#### 已有接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /ingest | 写入事件 |
| DELETE | /events/{event_id} | 删除事件 |
| DELETE | /nodes/{node_id} | 删除节点 |
| PUT | /nodes/{node_id} | 修改节点内容 |
| PUT | /events/{event_id}/status | 修改事件状态 |
| PUT | /events/{event_id} | 修改事件内容（更新 raw_content + FTS5） |
| POST | /edges | 创建关联边（source, target, relation, evidence_event_id） |
| DELETE | /edges | 删除关联边（query: source, target） |
| POST | /query | 检索 |
| POST | /feedback | 检索反馈 |
| GET | /health | 健康检查 |

查询同步返回，写操作异步返回确认。

#### 新增接口（dpim-webui）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /state-hash | 获取当前存储状态哈希 |
| GET | /events | 分页事件列表 |
| GET | /events/{event_id} | 事件详情 |
| GET | /nodes | 分页节点列表 |
| GET | /nodes/{node_id} | 节点详情（含关联边） |
| GET | /settings | 获取所有配置项 |
| PUT | /settings | 批量更新配置项 |

**分页约定（适用于 GET /events 和 GET /nodes）：**

| 查询参数 | 类型 | 默认值 | 说明 |
|----------|------|--------|------|
| limit | int | 20 | 每页条数，最大 100 |
| offset | int | 0 | 偏移量 |

额外参数：
- `GET /events`：`status`（事件状态筛选），`type`（事件类型筛选）
- `GET /nodes`：`type`（节点类型筛选）

**分页响应结构：**

```json
{
  "items": [...],
  "total": 86,
  "limit": 20,
  "offset": 0
}
```

**状态哈希响应：**

```json
{
  "hash": "a1b2c3d4e5f6...",
  "changed_at": "2026-07-24T12:00:00Z"
}
```

**配置更新请求：** 接受完整的配置键值对 JSON，只下发需要修改的字段即可。

**事件内容修改请求（PUT /events/{event_id}）：**

```json
{
  "content": "更新后的事件内容"
}
```

响应：`{"status": "ok", "message": "Event content updated", "event_id": "..."}`

---

### 九、配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| MEMORY_DB_PATH | ./data/memory.db | SQLite 数据库路径 |
| GRAPH_JSON_PATH | ./data/graph.json | 图层 JSON 路径 |
| LLM_BASE_URL | http://localhost:11434/v1 | LLM 服务地址（主 provider，向后兼容） |
| LLM_API_KEY | (空) | LLM API Key |
| LLM_MODEL_NAME | llama3:8b | 模型名称 |
| LLM_TIMEOUT | 30 | LLM 请求超时（秒） |
| **PROVIDERS** | (空 JSON) | BYOK 多 provider 注册（JSON dict：name → {base_url, api_key, model, timeout}） |
| **ACTIVE_PROVIDER** | primary | 活动 provider（primary = LLM_* 主配置） |
| **AGENT_MODE** | disabled | Agent 管线开关：disabled \| pipeline |
| **AGENT_MAX_RETRIES** | 2 | Meta 驳回时的最大修正轮次 |
| **ACTIVE_MODEL** | (空) | 使用中的模型（活动 provider 模型列表内；空 → provider 首个/默认） |
| **LLM_STRUCTURED_MODE** | md_json | 结构化输出模式：md_json（默认，兼容 llama.cpp）\| json \| tools |
| **MAX_RAW_CONTENT** | 10000 | 上下文护栏：单次 LLM 输入中 raw_content 最大字符数（超限截断） |
| **AGENT_CR_MODEL** | (空) | Cr 角色模型覆盖（空 → 回退活动 provider） |
| **AGENT_IN_MODEL** | (空) | In 角色模型覆盖 |
| **AGENT_GR_MODEL** | (空) | Gr 角色模型覆盖 |
| **AGENT_META_MODEL** | (空) | Meta 角色模型覆盖 |
| MAX_GRAPH_HOPS | 2 | 图扩散最大跳数 |
| RRF_K | 60 | RRF 融合 k 值 |
| JACCARD_THRESHOLD | 0.85 | 去重预检相似度阈值 |
| HEALTH_CHECK_INTERVAL | 60 | 健康检查间隔（秒） |
| COMPENSATE_BATCH_SIZE | 20 | 补偿批次大小 |
| LOG_LEVEL | INFO | 日志级别 |

> 2026-08-01：新增 BYOK 多模型网关与 Agent 管线配置（PROVIDERS / ACTIVE_PROVIDER / AGENT_*）。
> 2026-08-02：BYOK/Agent 结构化配置迁入 `dpim/dpim.json`（env DPIM_* 可覆盖）；前端 `PUT /settings` 写回 dpim.json 持久化。

---

### 十、原型范围

**本期实现**：
- 事件存取、FTS5 索引、物理删除
- 图节点和边增删改查、JSON 持久化、反向索引
- 信息处理 Agent、图构建 Agent
- 元认知裁判（单次审查）
- 混合检索（FTS5 + 图扩散 + RRF）
- 降级与补偿
- FastAPI 接口层
- Typer CLI
- dpim-webui 前端

**本期暂缓**：
- 压缩功能（compressed 状态预留）
- 检索缓存
- 多用户多租户
