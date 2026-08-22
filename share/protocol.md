# DPIM Spec 规约

> 版本：1.18
> 日期：2026-08-21
> 范围：原型阶段 + dpim-webui + 状态校验密钥 + 事件内容修订 + system 源过滤 + BYOK 多模型网关 + Agent 管线 + 运维可靠性（图谱加载容错）+ 检索（FTS5 + 图扩散两路 RRF）+ 上下文护栏回调（MAX_RAW_CONTENT 默认 600000 → 200000）+ 补偿批检查独立间隔（COMPENSATE_CHECK_INTERVAL）+ 图维护任务（调整/合并/删改/节点压缩，POST /agent/maintain，23 端点）+ 安全加固（API Key 掩码 + 可选 API 访问认证 + 输入上限/值域约束 + 日志全文开关）+ 防冗余节点硬规则（redundant_node）+ 节点规模高水位自动维护（AGENT_MAINTAIN_MAX_NODES / COOLDOWN）+ 存储路径/日志级别 dpim.json 持久化 + 事件类型必填化（auto 移除）与类型修订（PUT /events 可改 event_type）+ source 类型管线跳过构图 + max_hops 允许 0（纯检索不扩散）

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
| raw_content | string | 是 | 原始内容（默认不可变，可通过 PUT /events/{event_id} 修订） |
| content_hash | string | 是 | BLAKE2s-8B 十六进制（16 字符；实现为 hashlib.blake2s(digest_size=8)） |
| event_type | enum | 是 | interaction / data / source |
| status | enum | 是 | raw / indexed / linked / failed / skipped |
| graph_refs | string[] | 否 | 关联的图节点 ID 列表 |

**事件类型：**

- `interaction`：对话记录、Agent 决策与行动轨迹。可多次压缩。
- `data`：搜索事实、用户导入资料。最多压缩一次。
- `source`：原始证据。仅存于线层，不进入图构建（管线遇到 source 类型停留 indexed，不调用 LLM 构图）。

类型规则（v1.17）：写入时 `event_type` **必填**（枚举校验，非法值 422）；`auto` 模式已移除（历史上 auto 仅静默落库为 interaction，并无 AI 分类）。写入后可经 `PUT /events/{event_id}` 修订类型（可选字段，缺省保持不变）。

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
| type | enum | hallucination / illegal_edge / conflict / empty_node / redundant_node |
| description | string | 问题描述 |
| suggestion | string | 修正建议 |

**审查规则**：
- 边合法性：source 和 target 必须存在于图中，纯逻辑检查
- 冲突检测：新关系是否与已有关系矛盾，调 LLM 语义判断
- 来源锚定：evidence_quote 是否出现在 raw_content 中，优先子串匹配
- 空节点检查：content 不得为空

#### 4.4 图维护任务（调整/合并/删改/节点压缩）

**职责**：整理已有图结构——合并重合节点、删除僵尸节点、修正过时内容、删除错误边、概括压缩 data 节点。与「4.2 图构建（存）」互补：构图是增，维护是改删压。

**触发**：
- 手动：`POST /agent/maintain`（入队 `maintain_graph`，与写入共用串行队列）
- 自动（AI 恢复）：AI 恢复触发补偿时顺带入队一次（`AGENT_MAINTAIN_AUTO` 默认开启；图节点数 < `AGENT_MAINTAIN_MIN_NODES` 时自动触发跳过，手动不受限）
- 自动（节点规模高水位）：总节点数达到 `AGENT_MAINTAIN_MAX_NODES`（默认 900 ≈ 1000 软上限 90%）时由健康检查循环入队一次（清理僵尸节点）；`AGENT_MAINTAIN_COOLDOWN`（默认 300s）冷却期内不重复触发
- AI 不可用或管线未启用时跳过

**流程**：

1. **候选扫描**（确定性，无 LLM）：同类型相似节点对（词重叠 Jaccard ≥ 0.6，词桶优化）、无有效源证的僵尸节点、低置信度（<0.4）且无边的孤立节点、可压缩 data 节点（有效源证 ≥ 3 或内容 ≥ 500 字符）
2. **Gr 维护计划**：一次 LLM 调用输出 GraphMaintenancePlan（merges / deletes / updates / edge_removes / compresses，每条带 reason）
3. **Meta 审核**：本地硬规则（存在性/类型边界/删除保护/压缩仅 data）+ LLM 语义复核（合并是否真重合、删除是否安全、修改是否违背证据、压缩是否损坏语义）
4. **执行**：审核通过则执行（合并 = target 吸收 source 源证/内容/边迁移后删 source；删除/修改/删边/压缩各按规则），驳回即放弃本轮（无修正循环，保守优先）
5. **空计划合法**：无必要整理时 Gr 输出空计划，不做任何改动

**边界**（与删除保护对齐）：

| 操作 | 允许范围 |
|------|----------|
| 合并 | 仅同类型（data-data / interaction-interaction）；system 永不参与；源证并集不丢失证据 |
| 删除 | interaction 节点（Meta 审核）；data 仅当无有效源证；system 永不删除 |
| 修改 | interaction 覆盖内容；data 只允许追加（不得概括）；system 禁改；修改须仍能被源证支撑 |
| 删边 | 按 (source, target) 删除，须有依据 |
| 压缩 | 仅 data 概括压缩（覆盖 content + 可精炼 title + 可补边）；source_refs 保留不动（溯源锚定不破坏）；system / interaction 永不压缩；概括不得引入新论断/丢失关键语义 |

**GraphMaintenancePlan**：

| 字段 | 类型 | 说明 |
|------|------|------|
| merges | MaintenanceMerge[] | 合并：target_id 吸收 source_ids（源证/内容/边）后删 source |
| deletes | MaintenanceDelete[] | 删除节点（node_id + reason） |
| updates | MaintenanceUpdate[] | 调整内容（node_id + content + reason） |
| edge_removes | MaintenanceEdgeRemove[] | 删除边（source + target + reason） |
| compresses | MaintenanceCompress[] | 概括压缩 data 节点（node_id + content + 可选 title + 可选 new_edges + reason） |
| confidence | number | 计划整体置信度 0.0~1.0 |

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
2. 图扩散：以 C1 为种子，2 跳扩散，得分 = 1/(hop+1)，取 top-200 得 C2；扩散取**无向邻域**（v1.16：召回不区分边方向，A→B 时命中 B 也能跳回 A；边方向语义保留在图数据与前端展示中，溯源不受影响——溯源靠 source_refs 事件锚定，与边方向无关）
3. RRF 融合：`Σ 1/(60 + rank_i)`（两路），交互类乘以时间衰减 `1/(1+days×0.05)`
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

> 当前共 23 个端点。查询同步返回；写操作在 Agent 管线启用时异步入队，否则同步确认。

**访问认证（可选，v1.13 新增）：** 环境变量 `DPIM_API_KEY` 非空时，所有端点要求请求头 `X-API-Key` 匹配，不匹配返回 `401`；默认为空（本地模式零配置不启用）。WebUI 通过 localStorage `dpim_api_key` 自动附带该头。此密钥仅经环境变量配置，不经 `GET /settings` 下发、不经 `PUT /settings` 修改。

#### 8.1 写入类

| 方法 | 路径 | 说明 | 请求体 |
|------|------|------|--------|
| POST | /ingest | 写入事件（event_type 必填） | IngestRequest |
| PUT | /events/{event_id} | 修改事件内容与类型（更新 raw_content + FTS5；event_type 可选修订） | `{"content": "...", "event_type": "..."}` |
| PUT | /events/{event_id}/status | 修改事件状态 | ModifyEventStatusRequest |
| DELETE | /events/{event_id} | 删除事件（带源证保护） | — |
| POST | /nodes | 人工创建图节点（source_event_id 可选） | CreateNodeRequest |
| PUT | /nodes/{node_id} | 修改节点内容（重置 confidence=0.7，system 禁止） | ModifyNodeRequest |
| DELETE | /nodes/{node_id} | 删除节点（force=true 覆盖源证保护） | DeleteNodeRequest |
| POST | /edges | 创建关联边 | CreateEdgeRequest |
| DELETE | /edges | 删除关联边（query: source, target） | — |
| DELETE | /graph | 清空图谱（节点 + 边，同步清 node_fts） | — |
| PUT | /settings | 批量更新配置项（持久化 dpim.json） | SettingsUpdateRequest |
| POST | /agent/compensate | 手动触发补偿：积压 raw/indexed 事件重入队 | — |
| POST | /agent/maintain | 手动触发图维护：扫描候选 → Gr 计划 → Meta 审核 → 执行（合并/删除/修改/删边） | — |

#### 8.2 读取类

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /query | 混合检索（Agent 可用时走 Agent 检索，失败回退） |
| POST | /feedback | 检索反馈（调整节点置信度） |
| GET | /health | 健康检查 + 双区统计 |
| GET | /state-hash | 状态校验密钥 |
| GET | /events | 分页事件列表 |
| GET | /events/{event_id} | 事件详情 |
| GET | /nodes | 分页节点列表 |
| GET | /nodes/{node_id} | 节点详情（含关联边） |
| GET | /settings | 获取所有配置项 |
| GET | /agent/logs | AI 调用日志（环形缓冲，新→旧） |

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

**配置更新请求：** 接受完整的配置键值对 JSON，只下发需要修改的字段即可（详见第九节配置项）。

**配置读写安全语义（v1.13 新增）：**

- `GET /settings` 下发的 `llm_api_key` 与 `providers[*].api_key` 一律为**掩码值**（格式 `{前3字符}****{后4字符}`，短密钥全掩码，空密钥为空串），明文密钥绝不出网。
- `PUT /settings` 对密钥字段采用**掩码幂等保留**：提交掩码值或空串 = 保留现值不变；提交其他非空值 = 替换。前端把 GET 下发的掩码原样回传不会清掉密钥。
- `SettingsUpdateRequest` 值域约束（越界 422）：`agent_mode ∈ {disabled, pipeline}`、`log_level ∈ {DEBUG, INFO, WARNING, ERROR}`、数值字段范围与前端输入框一致（如 `max_graph_hops 1-5`、`rrf_k 1-200`、`jaccard_threshold 0-1` 等）；`memory_db_path` / `graph_json_path` 为可选字符串（v1.16），修改后持久化 dpim.json、重启生效（运行中句柄不切换，数据文件不自动迁移）。
- `IngestRequest.content` / `ModifyEventRequest.content` 上限 **1,000,000 字符**（超限 422，防磁盘耗尽 DoS）。
- `IngestRequest.event_type` **必填枚举**（v1.17）：`interaction / data / source`，缺省或非法值（含 `auto`）422。
- `SearchRequest` 服务端范围约束（越界 422）：`max_hops 0-5`（v1.18：0 = 不扩散，事件原文/知识节点纯检索用；1-5 = 图扩散跳数）、`limit 1-100`、`offset ≥ 0`。

**事件内容修改请求（PUT /events/{event_id}，v1.17 扩展）：**

```json
{
  "content": "更新后的事件内容",
  "event_type": "data"
}
```

`event_type` 可选（缺省保持不变，枚举校验同写入路径）。类型修订**仅改线层事件**：不联动已生成图节点（图层为派生物，节点层变更走图维护或删除重建），也不改事件状态机——source 改回 interaction/data 后如需重新构图，走既有 `PUT /events/{event_id}/status` 重试入队路径。

响应：`{"status": "ok", "message": "Event content updated", "event_id": "..."}`

**创建节点请求（POST /nodes）：**

```json
{
  "title": "节点标题（≤60 字符）",
  "content": "节点内容（缺省等于 title）",
  "node_type": "data",
  "source_event_id": "可选，关联来源事件 ID"
}
```

响应：`{"status": "ok", "node_id": "...", "message": "Node created"}`

**AI 调用日志响应（GET /agent/logs）：**

```json
{
  "logs": [
    {
      "role": "cr|in|gr|meta",
      "model": "模型名",
      "timestamp": 1754294400.0,
      "input_preview": "LLM 输入前 2000 字符",
      "output": "LLM 输出前 2000 字符",
      "error": "错误信息（空 = 成功）"
    }
  ]
}
```

> `full=true` 返回完整 input/output/error（不做 2000 字符截断）。`DPIM_AGENT_LOGS_FULL=false` 时忽略 full 参数（日志含事件原文，部署环境可关闭全文防泄露；默认 true 保持本地观测能力）。

---

### 九、配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| MEMORY_DB_PATH | ./data/memory.db | SQLite 数据库路径（v1.16：env → dpim.json storage → 默认；可经 PUT /settings 修改，重启生效） |
| GRAPH_JSON_PATH | ./data/graph.json | 图层 JSON 路径（v1.16：同上，持久化 dpim.json；数据文件不自动迁移） |
| LLM_BASE_URL | http://localhost:11434/v1 | LLM 服务地址（主 provider，向后兼容） |
| LLM_API_KEY | (空) | LLM API Key |
| LLM_MODEL_NAME | llama3:8b | 模型名称 |
| LLM_TIMEOUT | 666 | LLM 生成请求超时（秒，本地模型宽容默认；provider 条目可覆盖） |
| **LLM_MAX_TOKENS** | (空) | 输出 token 上限（0/空 = 服务端默认；provider 条目可覆盖） |
| **LLM_ENABLE_THINKING** | (空) | 思考开关（true/false/空 = 服务端默认；provider 条目可覆盖） |
| **LLM_THINKING_BUDGET** | (空) | 思考预算 tokens（0/空 = 不设；provider 条目可覆盖） |
| **PROVIDERS** | (空 JSON) | BYOK 多 provider 注册（JSON dict：name → {base_url, api_key, model, timeout, max_tokens, enable_thinking, thinking_budget, thinking_style, extra_body, structured_mode}） |
| **ACTIVE_PROVIDER** | primary | 活动 provider（primary = LLM_* 主配置） |
| **AGENT_MODE** | disabled | Agent 管线开关：disabled \| pipeline |
| **AGENT_MAX_RETRIES** | 2 | Meta 驳回时的最大修正轮次 |
| **ACTIVE_MODEL** | (空) | 使用中的模型（活动 provider 模型列表内；空 → provider 首个/默认） |
| **LLM_STRUCTURED_MODE** | md_json | 结构化输出模式：md_json（默认，兼容 llama.cpp）\| json \| tools |
| **MAX_RAW_CONTENT** | 200000 | 上下文护栏：单次 LLM 输入中 raw_content 最大字符数（超限截断；默认 200000 ≈ 5 万 token 输入，不依赖特定模型上下文） |
| **AGENT_CR_MODEL** | (空) | Cr 角色模型覆盖（空 → 回退活动 provider） |
| **AGENT_IN_MODEL** | (空) | In 角色模型覆盖 |
| **AGENT_GR_MODEL** | (空) | Gr 角色模型覆盖 |
| **AGENT_META_MODEL** | (空) | Meta 角色模型覆盖 |
| MAX_GRAPH_HOPS | 2 | 图扩散最大跳数 |
| RRF_K | 60 | RRF 融合 k 值 |
| JACCARD_THRESHOLD | 0.85 | 去重预检相似度阈值 |
| HEALTH_CHECK_INTERVAL | 60 | 健康检查间隔（秒） |
| HEALTH_CHECK_TIMEOUT | 120 | 健康检查超时（秒，与生成超时分离） |
| COMPENSATE_BATCH_SIZE | 20 | 补偿批次大小 |
| **COMPENSATE_CHECK_INTERVAL** | 5 | 补偿批次结果检查间隔（秒，独立于健康检查周期，失败批次快速进入退避） |
| **AGENT_MAINTAIN_AUTO** | true | 图维护自动触发：AI 恢复触发补偿时顺带整理图谱（合并/删除/修改/删边） |
| **AGENT_MAINTAIN_MIN_NODES** | 10 | 自动维护最小图规模（节点数；小图跳过，手动触发不受限） |
| **AGENT_MAINTAIN_MAX_NODES** | 900 | 节点规模高水位：总节点数达到即由健康检查循环自动触发一次图维护（清理僵尸节点；≈ 1000 软上限 90%） |
| **AGENT_MAINTAIN_COOLDOWN** | 300 | 高水位自动维护触发冷却（秒）：避免超过阈值后每个健康周期空转 LLM |
| **API_KEY** | (空) | API 访问认证（v1.13）：非空时所有端点要求 `X-API-Key` 请求头匹配；仅 env 配置，不经 API 下发/修改 |
| **AGENT_LOGS_FULL** | true | AI 调用日志全文开关（v1.13）：false 时 GET /agent/logs 忽略 full 参数 |
| LOG_LEVEL | INFO | 日志级别（v1.16：env → dpim.json → 默认；可经 PUT /settings 修改） |

> 2026-08-01：新增 BYOK 多模型网关与 Agent 管线配置（PROVIDERS / ACTIVE_PROVIDER / AGENT_*）。
> 2026-08-02：BYOK/Agent 结构化配置迁入 `dpim/dpim.json`（env DPIM_* 可覆盖）；前端 `PUT /settings` 写回 dpim.json 持久化。
> 2026-08-03：厂商适配（LLM_MAX_TOKENS / LLM_ENABLE_THINKING / LLM_THINKING_BUDGET + provider 条目 thinking_style/extra_body/structured_mode）；provider 条目字段可在前端「提供商注册表(JSON)」编辑。
> 2026-08-04：规约升级至 v1.6。补全 API 端点清单至 22 个（新增 POST /nodes、DELETE /graph、GET /agent/logs、POST /agent/compensate 的说明与请求/响应结构）；图谱 JSON 加载增加容错（损坏时从 .bak 恢复或空图启动）。
> 2026-08-04：超时放宽（本地模型宽容）：LLM_TIMEOUT 默认 300→666、HEALTH_CHECK_TIMEOUT 60→120；`GET /agent/logs` 新增 `full=true` 参数返回完整 input/output/error（前端折叠查看）。
> 2026-08-04：规约升级至 v1.7。新增语义检索（embedding）：EMBEDDING_MODEL / EMBEDDING_DIM 配置项 + provider 条目级覆盖；检索三路 RRF（FTS5 + 向量 + 图扩散）；向量表 event_embeddings / node_embeddings；`SettingsResponse/UpdateRequest` 新增 embedding_model / embedding_dim 字段。
> 2026-08-04：规约升级至 v1.8。嵌入服务独立化：EMBEDDING_BASE_URL / EMBEDDING_API_KEY 配置项（空 = 跟随活动提供商），provider 条目级覆盖 embedding_base_url / embedding_api_key；嵌入配置随 dpim.json 持久化（重启保留）；`SettingsResponse/UpdateRequest` 新增 embedding_base_url / embedding_api_key 字段。
> 2026-08-04：规约升级至 v1.9。移除语义检索（embedding）整链：EMBEDDING_* 配置项、向量表 event_embeddings / node_embeddings、`LLMGateway.embed()`、检索向量路（三路 RRF 回到两路：FTS5 + 图扩散）；`SettingsResponse/UpdateRequest` 移除 embedding_* 字段。
> 2026-08-14：规约升级至 v1.10。上下文护栏放宽：MAX_RAW_CONTENT 默认 10000 → 600000 字符（避免长输入被截断）。
> 2026-08-18：规约升级至 v1.11。上下文护栏回调：MAX_RAW_CONTENT 默认 600000 → 200000 字符（≈5 万 token 输入，不依赖默认模型上下文，避免内存/上下文撑爆）；新增 COMPENSATE_CHECK_INTERVAL（默认 5s）：补偿批次结果检查间隔独立于健康检查周期（60s），失败批次快速进入退避。
> 2026-08-18：规约升级至 v1.12。新增图维护任务（4.4 节）：调整/合并/删改已有图结构——候选扫描（相似对/僵尸节点/孤立低置信）→ Gr 维护计划（GraphMaintenancePlan）→ Meta 审核（本地硬规则 + LLM 语义复核）→ 执行；边界与删除保护对齐（system 永不参与、data 仅无有效源证可删、合并仅同类型、修改仅 interaction 覆盖/data 追加）；新增端点 POST /agent/maintain（22 → 23 端点）；自动触发：AI 恢复时顺带维护（AGENT_MAINTAIN_AUTO 默认开启，AGENT_MAINTAIN_MIN_NODES 默认 10 拦截小图）。
> 2026-08-19：规约升级至 v1.13。安全加固：① GET /settings 密钥掩码下发（`llm_api_key` / `providers[*].api_key` → `{前3}****{后4}`），PUT /settings 掩码幂等保留（掩码/空 = 保留现值）；② 新增可选 API 访问认证 DPIM_API_KEY（非空时全部端点要求 X-API-Key 头，默认空不启用），WebUI/请求层自动附带；③ 输入上限：IngestRequest.content / ModifyEventRequest.content ≤ 1,000,000 字符；SearchRequest 服务端值域（max_hops 1-5 / limit 1-100 / offset ≥ 0）；SettingsUpdateRequest 枚举与数值范围校验（越界 422）；④ 新增 DPIM_AGENT_LOGS_FULL（默认 true，false 时 /agent/logs 忽略 full 参数）；⑤ 前端提供商注册表由 JSON textarea 改为表单化弹窗管理（密钥掩码显示、留空保持不变）；⑥ event_fts LIKE 降级分支补 LIMIT 500 护栏。
> 2026-08-19：规约升级至 v1.14。① 防冗余节点硬规则：`run_local_checks` 新增 redundant_node issue 类型（new_node 与 similar_nodes 高度重合且同类型 → 驳回并要求 merged_into），Gr 构图提示词强化「重合即合并」决策优先级；② 节点规模高水位自动维护：新增 AGENT_MAINTAIN_MAX_NODES（默认 900，总节点数达到即由健康检查循环自动入队一次维护清理僵尸节点）与 AGENT_MAINTAIN_COOLDOWN（默认 300s，冷却防空转）；③ 修正 data 节点维护追加统计口径（空/重复追加不计 updated、不重建 FTS）。
> 2026-08-20：规约升级至 v1.15。节点压缩：图维护新增 compresses 操作（MaintenanceCompress），仅 data 节点可概括压缩——覆盖 content + 可选精炼 title + 补充 new_edges；source_refs 保留不动（溯源锚定不破坏）；system/interaction 永不压缩；候选扫描新增 compress_candidates（data 节点有效源证 ≥ 3 或内容 ≥ 500 字符）；Gr/Meta 提示词新增压缩决策与审查规则。事件压缩仍不实施（compressed 状态预留）。
> 2026-08-20：规约升级至 v1.16。存储路径与日志级别持久化：① `SettingsUpdateRequest` 新增 `memory_db_path` / `graph_json_path` 字段（此前前端虽有输入框但请求被白名单静默丢弃，属缺陷修复）；② 读取链统一为 env → dpim.json（storage 段 / log_level 键）→ 内置默认，`save_dpim_config()` 持久化存储路径与日志级别，前端修改重启保留；③ 存储路径修改重启生效（运行中句柄不切换，数据文件不自动迁移）；④ `.env` 精简为部署级安全开关与临时覆盖，日常配置全部走 WebUI/dpim.json；⑤ 前端「主配置 API Key」行移除（primary 密钥经 .env 或 dpim.json 管理，providers 注册表保留卡片化编辑），Agent 四角色模型字段改下拉框（跟随使用模型/当前提供商模型列表）。⑥ 图扩散双向化：ego_graph 扩散改无向邻域（A→B 时命中 B 也能跳回 A，提升召回；方向语义保留在边数据与前端展示；溯源靠 source_refs 锚定不受影响）。
> 2026-08-21：规约升级至 v1.17。事件类型治理：① `IngestRequest.event_type` 必填枚举化（interaction / data / source，缺省或 `auto` 均 422）——auto 模式移除（历史上 auto 仅静默落库为 interaction，并无 AI 分类，属名不副实的假模式）；② `PUT /events/{event_id}` 新增可选 `event_type` 修订（缺省保持不变；仅改线层，不联动已生成图节点，不改状态机）；③ 管线补 source 类型跳过：`_handle_ingest` 遇 source 停留 indexed 不调用 LLM 构图（补齐「source 仅存储不进图谱」宣称与实现间的缺口，此前 source 事件实际会被构图）。
> 2026-08-21：规约升级至 v1.18。检索值域修正：`SearchRequest.max_hops` 下限 1 → 0（0 = 不扩散，事件原文/知识节点纯 FTS 检索用）——此前前端这两类检索传 `max_hops=0` 被 Pydantic `ge=1` 拦成 422（"Input should be greater than or equal to 1"），事件原文/知识节点检索完全不可用；`ego_graph(hops=0)`（radius=0 + center=False）本就返回空集，0 的语义即"不扩散只 FTS"。

---

### 十、原型范围

**本期实现**：
- 事件存取、FTS5 索引、物理删除
- 图节点和边增删改查、JSON 持久化、反向索引
- 信息处理 Agent、图构建 Agent
- 元认知裁判（单次审查）
- 混合检索（FTS5 + 图扩散 + RRF）
- 图维护（合并/删除/修改/删边/节点压缩）
- 降级与补偿
- FastAPI 接口层
- Typer CLI
- dpim-webui 前端

**本期暂缓**：
- 事件压缩（compressed 状态预留）
- 检索缓存
- 多用户多租户
