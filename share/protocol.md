# DPIM Spec 规约

> 版本：1.46
> 日期：2026-10-17
> 范围（v1.46 追加）：**系统性审计后的第一批修正（端点仍 45）**——起因：用户提出「是不是一定存在其他问题，或者说这个前端就没写到整洁完备」，于是按**缺陷类别**派 5 路并行审计（密钥外泄 / 草稿与已存错位 / 静默失败与说谎界面 / 前后端契约一致性 / 边界与交互细节），合计 52 条。本版收的是其中**后端与契约**那部分：① **错误原文不得回显密钥**——`httpx`/`h11` 的报错会把**整条请求头值**原样写进异常文本（实测：`api_key` 含换行时 `probe_models` 抛 `LocalProtocolError: Illegal header value b'sk-abc\nSECRETTAIL'`，明文密钥进异常），而这段原文会显示在卡片 / 概览台 / 顶栏，还会写进 `logs/backend-*.log`。现在**双保险**：请求头值先过 `security.sanitize_secret()`（清 `\x00-\x1f\x7f`，含换行——跨行粘贴的密钥很常见），异常原文在**交给界面或落盘之前**过 `security.scrub_secrets()`（连转义形态 `\n` 与 `repr` 形态一起擦，三处：探测端点 `POST /settings/models`、健康检查的 WARNING、降级原因 `ai_state`）。② **`reconcile_changed` 不再恒 0**——`RepoManager.refresh_repo()` 返回的键是 **`changed`**，而 `RepoRefreshResponse` 要的是 `reconcile_changed`；Pydantic 对未知键是 `extra='ignore'`，于是**真值被静默丢弃、恒为 0**（`message` 也恒空）：`POST /repos/{id}/refresh` 的「刷新修复」永远报「源证对账变更 0 条」，存储体检页同一数字也恒 0——**"修没修好"这个唯一判断依据一直是假的**。router 补键名映射并补一句可展示文案。③ **类型修正两处**（同「类型在骗人」类）：`ClearGraphResponse` 补齐 v1.42 的 7 个字段（`archived` / `archive_id` / 四个计数，原停在 `status`+`message`；前端 `api/nodes.ts` 因此绕开契约自写类型——下一次有人顺手 `import type` 就会重演 LayerStats 那类事故）、`LLMCallLog.input`（`full=true` 取全文时后端下发的是 `input`，**没有** `input_preview` → 前端只读后者导致「输入」区恒空白，形似模型没收到输入）。测试：后端 +4（`sanitize_secret`/`scrub_secrets` 三例含转义形态与短值不擦、`reconcile_changed` 键名映射的回归守卫）。
> 范围（v1.45 追加）：**AI 可用性判定与 BYOK 界面三处真缺陷（端点仍 45）**——① **LLM 健康检查按接口格式分流**：旧实现走 OpenAI SDK 的 `client.models.list()`，对 `format=anthropic` 的 provider **永远发 `Authorization: Bearer`**，而真 Anthropic / OpenCode Zen 这类网关在 Anthropic 面要 `x-api-key`（[同款踩坑](https://github.com/can1357/oh-my-pi/issues/6510)）→ 回 401 → **AI 被误判「连不上」：降级、补偿、自动维护永远不会启动**（密钥其实完全正确）。现改为调用与 `POST /settings/models` 同一套的 `probe_models(conf)`（按格式分流），失败计数与三连败判降级的口径不变。② **`POST /settings/models` 增 `api_path` / `extra_headers`（请求体优先 → 已登记条目）**：前端卡片的「拉取模型」此前**只发 provider 名字**，后端只能去**已保存配置**里查该条目——于是「刚新增、还没点提交配置」的条目一律报 `未填模型地址（base_url）`（而地址就显示在卡片上，用户实测：弹窗里能拉到 37 个模型、卡片上报这个），自定义格式的条目还会因缺额外请求头而 401。③ **前端草稿只存掩码密钥**：旧实现把你在弹窗里输入的**明文**直接写进草稿，而草稿被卡片与弹窗占位符直接渲染 → **卡片「密钥 oc_sk_…」与占位符「当前 oc_sk_…，留空保持不变」都显示明文**（同一行的提示还写着「界面不回显明文」）。现在草稿只存 `maskLocal()` 掩码（与后端 `mask_secret` 同规则），明文只活在输入框与「待提交暂存」里，**提交那一刻才下发**；重命名条目时暂存随之迁移；提交成功/重新拉取后清空。
> 范围（v1.44 追加）：**Anthropic 的 `max_tokens` 与思考预算不再互相打架（端点仍 45、字段无增删）**——① Anthropic 要求 `max_tokens` **严格大于** `thinking.budget_tokens`，而 v1.43 是「先定死 max_tokens 再算 thinking」，于是 `thinking_budget=8192` + 未填 `max_tokens` 会发出 `4096 < 8192` → **必定 400**；且思考 token **计入** `max_tokens`，余量不足会被 `stop_reason=max_tokens` 截断（半截 JSON）。现改为：定上限（条目 → 全局 `DPIM_LLM_MAX_TOKENS` → 兜底 4096）→ 算 thinking → 若 `max_tokens <= budget_tokens` 就抬到「预算 + 1024」并 WARNING 留痕。兜底仍是 **4096**（= 各家 Claude 模型输出上限的最小值，换任何模型都不会因超限 400；它是**上限**不是目标长度，按实际输出计费）。② 优先级修正：`enable_thinking=False`（显式关）**压过**残留的 `thinking_budget`（旧顺序会让「关掉思考」被无声推翻，还连带丢掉 temperature）。③ 界面把实际生效值说出来（弹窗「输出上限」提示 + 卡片摘要显示 `默认（4096）` / `2048（思考预算更大，实际按 5120）`）。
> 范围（v1.43 追加）：**接口格式：模型配置可选四套主流协议（端点仍 45）**——此前网关写死 OpenAI 兼容 Chat Completions（`core/llm.py` 唯一调用是 `chat.completions.create`），**Anthropic 的 `/v1/messages` 与 OpenAI 的 `/v1/responses` 完全接不上**（连模型列表都拉不出来：`POST /settings/models` 只会用 Bearer 打 `{base}/models`）。现在 provider 条目增三个字段：**`format`**（`openai` | `responses` | `anthropic` | `custom`，缺省 `openai` = 老条目零迁移）、**`api_path`**（仅 custom）、**`extra_headers`**（各格式通用）。四套的真实口径：① **openai**：`POST {base}/chat/completions`，`Authorization: Bearer`，结构化输出仍按 `md_json` / `json` / `tools`（`structured_mode` **只对这一套生效**）；② **responses**：`POST {base}/responses`，body 用 **`input`**（整段消息，含 system 角色条目）/ **`max_output_tokens`**（**不是 `max_tokens`**，传错会被 SDK 拒收）/ `text.format`，结构化输出**固定**走 instructor 的 `RESPONSES_TOOLS`（工具调用）——`openai` SDK 自带 `.responses` + instructor 自带 handler，故这一套是**现成路径**；③ **anthropic**：`POST {base}/messages`，**`x-api-key` + `anthropic-version: 2023-06-01`** 头（不是 Bearer），**`system` 是顶层字段**、**`max_tokens` 必填**（未填按 4096 兜底），`enable_thinking` / `thinking_budget` 映射到 `thinking`（**开启时不传 `temperature`**——Anthropic 要求 1；关闭时照常传），无原生 JSON Schema 输出 → 按「system 附 JSON Schema → 只许输出一个 JSON 对象 → 解析 → Pydantic 校验 → **把校验错误回喂重问**」实现（至多 `max_retries` 次）；④ **custom**：`POST {base}{api_path}`（缺省 `/chat/completions`，未写前导 `/` 会自动补），Bearer + `extra_headers`，仍按 chat completions 形状收发（`extra_body` 透传照旧）。**为什么 anthropic 不走官方 SDK**：`instructor.from_anthropic` 需要 `anthropic` 包，而本项目依赖表里没有（本环境也无法安全新增：`uv lock` 需联网重建）→ 用已装的 `httpx` 实现，**零新依赖**，自建「Anthropic 兼容」网关换个 `base_url` 即可用。**探测分流**：`POST /settings/models` 增 `format`（请求体优先 → 已登记条目 → openai），anthropic 用同一套头打 `{base}/models`。**失败语义**：httpx 适配的 5xx / 429 / 408 计入可重试（`is_transient_error` 扩了 `httpx.HTTPStatusError` 分支），4xx 不可自愈；错误原文带状态码与响应片段（界面直接可读）。
> 范围（v1.42 追加）：**图层一致性：悬空端点不再造空壳节点 + 清空图层可恢复且不留下「已入图」谎报（端点仍 45）**——① **空壳节点根因**：`GraphStore.add_edge` 此前直接交给 NetworkX，而 `nx.add_edge` 遇到未知端点会**自动造出一个无 `data` 的空壳节点**。实测活动库 `graph.json` 里 **51 个真节点、56 条边，其中 15 个端点不在 `nodes` 里**（29 条边悬空）→ 内存图 **66** 个节点（`/health` 的 `total_nodes` 报 66）而 `GET /nodes`、`node_fts`、`node_counts_by_type` 只有 **51**，`POST /maintenance/verify` 三项 False（`no_dateless_nodes` / `node_fts_consistency` / `ops_replay_matches_graph`）；更糟的是**自续循环**：`save()` 不写无 `data` 的节点、却会写它们的边，于是每次加载都从文件里把空壳重新造出来。现改为：`add_edge` **拒绝未知端点**（返回 `False` + WARNING 留痕，绝不静默造节点）；`load()` **跳过** `graph.json` 里端点不在 `nodes` 的边并标记脏位（下次落盘即清除，原件进 `.bak`）；`replay_recover` 跳过条数也留痕；`verify` 新增 `no_dangling_edges_in_file`（直接读文件，把「文件级残留」如实报出来而不是静默吞掉）。② **清空图层（`DELETE /graph`）不再不可逆、也不再留下谎报**：此前 `DELETE /graph` 只做 `clear_all()` + 重建 `node_fts`——**应用内没有任何恢复路径**（单个节点删除都有回收站留档，一次删掉整图反而无处可恢复），而且线层那 10 条事件仍是 `status=linked`、`graph_refs` 全指向已不存在的节点（概览台照旧显示「已入图事件 10」，`verify` 却全绿）。现在清空前**先把整图留档**到 `trash/graphs/graph-<时间戳>.json`（`data = {nodes, edges}`、`stats` 记计数），恢复走**既有** `POST /trash/restore`（`kind` 增 `graph`，**合并式**：已存在的节点/边跳过、不覆盖、不报 409），`GET /trash` 清单出现第三类；同时**撤销线层派生链接**——清空 `graph_refs` 并把 `linked` 回退为 `indexed`（`EventStore.unlink_graph_refs()`），于是概览台如实显示「待处理 10」，AI 可用时补偿队列会重新入图（`linked` 不在补偿的 raw/indexed 队列里，不撤销就永远长不回来）。`linked → indexed` 因此进入状态转换白名单（撤销入图，与 `PUT /events/{id}/status` 的 indexed 重试入队分支一致）。响应回 `{archived, archive_id, cleared_nodes, cleared_edges, unlinked_events, relinked_events}`；**留档失败仍照常清空，但 message 明说「留档失败，此操作不可恢复」**（不让用户以为还能找回来）。③ **`graph_ops` 的 `edge_delete` 补上被删边原数据**（与 `node_delete` 携带 `node` 对称）：整图清空后，这份 op 是边细节（relation / evidence_event_id）的唯一来源，此前只留 `{source, target}`。
> 范围（v1.41 追加）：**`GET /health` 分层统计的键名明确 + 前端契约类型修正（纯类型/口径修正，端点仍 45）**——`layers.event_line` 实际下发的是 `{total_events, raw, indexed, linked, failed, skipped}`，`layers.knowledge_graph` 是 `{total_nodes, system, interaction, data}`；而 `protocol.ts` 的 `LayerStats` 一直写成 `status_raw` / `status_indexed` / `status_linked` / `status_failed` / `status_skipped` / `system_nodes` / `interaction_nodes` / `data_nodes`——**后端从来没这么下发过**。后果：**类型在骗人**——概览台照着类型取 `health.eventLine.status_linked`，于是「已入图事件 / 失败事件 / 待处理（raw）/ 已跳过（skipped）」四个分项**恒显示「—」**，而 `vue-tsc` 毫无反应（类型允许错的键，反过来禁止正确的键）。链 AE 补概览台页面级单测时抓到（新用例断言「已入图事件 = 10」直接失败）。现把类型改成真实形状（拆成 `EventLineStats` / `GraphLayerStats`，去掉不存在的 `LayerStats`），概览台取值同步修正——改完后 `vue-tsc` 会**拒绝** `status_linked` 这类写法，这类缺陷不再能靠类型蒙混过去。
> 范围（v1.40 追加）：**联合节点列表的 `node_type` 口径修正（纯响应值修正，端点仍 45）**——`GET /nodes?repo_ids=a,b`（v1.30 联合列表）此前用 `str(data.get("node_type"))` 拼装响应项，而 Python 3.11+ 的 `str(NodeType.data)` 是 **`"NodeType.data"`**（不是 `"data"`）：单库 `GET /nodes` 走 Pydantic 落成 `"data"`，两条路**不同口径**。后果：前端「全部书目」作用域下按类型筛选（`node_type === 'data'`）**一个节点都匹配不上**，类型标签也显示成 `NodeType.data`。现统一取枚举的**值文本**（`getattr(v, "value", None) or str(v)`），与单库路径、与契约 `NodeListItem.node_type: NodeType` 一致。链 AD 做 CLI 活体冒烟时发现（`dpim nodes --repos …` 打出 `NodeType.data`）。
> 范围（v1.39 追加）：**保留策略（`graph_ops` 表与 `trash/` 目录不再只增不减；端点仍 45）**——① **`graph_ops` 压实而非截断**：它是「`graph.json` 丢失/损坏且无备份时的重放恢复依据」，`POST /maintenance/verify` 也按「重放全部 op == 内存图」判一致性——**直接删老 op 会让重放只能还原后半段**（恢复不完整、体检恒红）。故新增 `GRAPH_OPS_RETENTION`（默认 **5000**，0 = 不压实）：超限时把最老明细压成一批**等价快照 op**（`graph_clear` + 逐节点/逐边 upsert，`reason=retention-compaction`），`replay(压实后) == replay(压实前)`，**恢复能力与体检口径都不变**；表行数下限 = 1 + 节点数 + 边数（快照本身），快照不比被替换的明细小时原样不动；压实重写 `op_id`（顺序与内容等价），保留段的 `created_at`/`reason`/`actor` 原样保留。② **回收站按年龄清**：`TRASH_RETENTION_DAYS`（默认 **30** 天，**0 = 永不清理**）按文件 mtime 清理 `trash/{events,nodes}/` 与 `trash/restored/` 里的 `.json`——留档是已删数据的**最后一份副本**，故默认宽、可关、只动这三个目录。③ **执行时机**：启动时先跑一轮，此后并入既有存储卫生循环（与 WAL 检查点同一循环），**最多每小时一次**（`_RETENTION_EVERY_SECONDS = 3600`）；失败只记日志，不影响服务可用性。④ 两项均进 `GET/PUT /settings`（值域：0..1000000 / 0..3650，越界 422）并落盘 `dpim.json` 的 `storage` 段。
> 范围（v1.38 追加）：**多库自动维护口径归一（纯行为修正，端点仍 45）**——自动图维护有三条路：① **补偿**（AI 恢复时把积压 raw/indexed 事件重入队）早已逐受管库收集并逐条带 `repo_id`；② **节点规模高水位**（v1.29 起）逐受管库检查、带 `repo_id` 入队，每冷却周期至多一册；③ **AI 恢复后的顺带整理**此前只入队**一条不带 `repo_id`** 的消息，而 `Orchestrator._resolve_stores` 对缺省 `repo_id` 回退**默认库**——于是这一路**永远只整理默认库**：活动库若不是默认库、以及其余各库，一次都拿不到（小库也永远轮不到高水位那条路）。现改为与②同口径：**逐受管库各入队一次**（带 `repo_id`），规模闸门唯一留在 orchestrator（那里才知道该库真实节点数，小库到点即拦、不产生 LLM 调用）；无库管理器（单库部署）时仍是一条不带 `repo_id` 的消息。`Compensator._maintain_targets()` 统一两条路的候选库解析。
> 范围（v1.37 追加）：**边列表端点 `GET /edges` + 图谱页取边收口（+1 端点，44→45）**——此前**没有边列表端点**，信息图谱页只能「先取节点列表、再逐节点 `GET /nodes/{id}` 汇总边」：节点上限 400 时是 ⌈400/24⌉ = **17 批请求**，每批把节点全文（title / content / metadata / source_refs）取回来只为摘出那几条边；且任一节点详情失败即**静默少一批边**（前端 `.catch(() => null)`），图上表现为「莫名不连通」而没有任何提示。现在新增 `GET /edges`：筛选 `node_id`（**两侧**命中，出边 + 入边）/ `source` / `target` / `relation`；作用域 `repo_id`（缺省活动库）或 `repo_ids=a,b`（联合：按 (source, target) 去重 + 首命中库归属）；`limit` 默认 200、**0..5000（越界 400）**、`offset` 负数 400；items = `EdgeListItem`（`source`/`target`/`relation`/`evidence_event_id` + `repo_id`/`repo_name`），**按 (source, target) 稳定排序**故分页可复现。前端改为**一次请求取全**，并把「边取失败」显式报在页面上（不再静默丢边），边数被 `limit` 截断时显示「已取前 N / 共 M」。
> 范围（v1.36 追加）：**前端可配置面补齐（前端要能配置后端的东西）+ 来源可见**——① **真缺陷修复**：`max_graph_hops` / `rrf_k` / `jaccard_threshold` / `health_check_interval` / `health_check_timeout` / `compensate_batch_size` 这 6 项此前**只改内存**（`PUT /settings` 后立刻有效、**重启即回默认**，`save_dpim_config()` 不写它们、读取链也只读 env）——与链 Y 的 `llm_*` 是同一类静默失败。现在读取链统一为 **env → `dpim.json` 段 → 内置默认**，`save_dpim_config()` 按段落盘（`agent` / `retrieval` / `health` / `maintenance` / `logs` / `storage`），前端改过的值重启后仍在。② **可配置面扩到后端真正可调的东西**：`max_raw_content`、`compensate_check_interval`、`agent_maintain_auto` / `min_nodes` / `max_nodes` / `cooldown`、`agent_cmdmsg_max_rounds`、`agent_cr_skip_chars`、`llm_structured_mode`、`log_retention_days`、`log_jsonl`、`agent_logs_full`、`wal_checkpoint_interval`、`wal_checkpoint_bytes` 全部纳入 `GET/PUT /settings`。③ **来源可见（config_sources）**：响应新增 `config_sources`（每项标 `env:DPIM_X` / `file` / `default`）、`config_file`（配置写到哪个文件）、`log_dir`（日志目录，env-only 只读显示）；**被环境变量顶掉的项 PUT 不再写入内存**（否则运行时值与 env 不一致、重启又变回去），响应新增 `ignored_by_env` 点名是哪个变量锁的。**有意保留 env-only**：`DPIM_API_KEY`（访问认证密钥，避免经 API 自我暴露）、`DPIM_LOG_DIR`（改路径要重开文件句柄）、`DPIM_LLM_TIMEOUT` / `MAX_TOKENS` / `ENABLE_THINKING` / `THINKING_BUDGET`（provider 条目已拥有这些调优项，全局兜底仅 env）。
> 范围（v1.35 追加）：**BYOK 前端可调性补完**——① **提交已移除的 `llm_*` 字段一律 422**（v1.34 删字段后旧界面/旧脚本提交这些字段被**静默忽略**：界面显示「配置已保存并写入 dpim.json」，实际一个字段都没改 → 用户看到的现象正是「以前能配、现在怎么都不生效」。现在返回 422 并给出中文指引：AI 身份只在 `providers` 里、请强制刷新页面后改用「模型与提供商」）；② **`providers[*].clear_api_key: true` = 显式清空密钥**——「空串/掩码 = 保持现值」的幂等语义使已存密钥**无法从前端清掉**（只能删条目重建），清空必须单独声明；该标记 PUT 专用、解析后不入库、GET 从不下发。
> 范围（v1.34 追加）：**AI 配置归一（可调 BYOK，提供商任选模型）+ 未配置状态可见**——**删掉主 provider（primary）特殊分支与全部身份默认值**（此前 `LLM_BASE_URL=http://localhost:11434/v1` / `LLM_MODEL_NAME=llama3:8b` 是内置默认，任何未配置的部署都会静默指向一个不存在的本地 llama）：从此 **AI 身份（base_url / api_key / model）只存在于 `providers` 条目里**，一个提供商 = 一条记录；`providers` 只读 env `DPIM_PROVIDERS` 或 `dpim.json`，**仅当 `DPIM_LLM_BASE_URL` 被显式给出且注册表为空**时才合成名为 `default` 的条目（保住纯 env 部署）；`LLM_*` 降级为**全局调优默认**（timeout/max_tokens/enable_thinking/thinking_budget，仅 env，不进 API 请求体）。`GET /settings` 删 7 个 `llm_*` 字段、增 `llm_configured: bool` 与 `llm_unavailable_reason: str`（**未配置 ≠ 降级**：未配置不发起探测、不计失败）；`GET /health` 的 `status` 变为三态 `ok` \| `unconfigured` \| `degraded` 并带 `ai_unavailable_reason`。新增 `POST /settings/models`（**联网探测某个提供商的可用模型列表**，前端「拉取模型」按钮 + 下拉选择）。
> 范围（v1.33 追加）：**主 provider（BYOK）配置持久化修复**——`PUT /settings` 提交的 `llm_base_url` / `llm_api_key` / `llm_model_name` / `llm_timeout` / `llm_max_tokens` / `llm_enable_thinking` / `llm_thinking_budget` 此前**只改内存**：`save_dpim_config()` 只写 `active_provider` / `active_model` / `providers` / `agent` / `storage` / `log_level`，读取链（`core/config.py`）也只读 env → 界面显示「已保存并写入 dpim.json」，重启后 AI 静默退回内置默认（`http://localhost:11434/v1` + `llama3:8b` + 空密钥）→ 全链路不可用。本次新增 `dpim.json` 的 `llm` 段（读写链与 storage 一致：**env → dpim.json → 内置默认**）+ **掩码形状的提交值一律不落库**（`core/security.py` `looks_like_mask`：新条目/重命名/复制 provider 时带过来的 `sk-****abcd` 不再被当成真钥写盘，`resolve_provider_secret` 旧实现拿 `mask_secret("")` 比较恒为假等于没拦）
> 范围（v1.32 追加）：书目**收养** `POST /repos/adopt`（目录里至少有一个库文件即可登记为 external 书目；缺 `memory.db` 补空库、缺 `graph.json` 补空图并**顺带尝试从 `graph_ops` 重放恢复图层**；只补空件、绝不覆盖已存在文件；重复登记 409、一个文件都没有 400）+ 书目**未加载原因可见**（`RepoInfo.load_error`，P6 失败可见）+ **`POST /agent/maintain` 补 `mode` 请求体**（`compress` \| `update`，默认 `update`；此前该端点完全不读 body，payload 恒为 `{}` → 前端选 update 实际走 compress，`^update` 两阶段能力 REST 端到端不可用）+ **`health_check_timeout` 契约补齐**（`SettingsResponse` / `SettingsUpdateRequest` 与 `protocol.ts` 对齐）
> 范围（v1.31 追加）：本地日志接口（`GET /logs` 按通道/日期/级别/关键词翻看尾部 + `POST /logs/client` 浏览器日志回传落 `frontend-*.log`）+ 回收站接口（`GET /trash` 留档清单 + `POST /trash/restore` 按原 id 恢复事件/节点，节点连带留档边信息尽力恢复；恢复成功把留档**移入 `trash/restored/`**）+ 登记表重建 `POST /repos/rebuild`（坏索引恢复，只扫盘重建不删数据）+ 书目清除 `POST /repos/{id}/purge`（先备份再删库文件，外部库只摘登记）+ 外部库重指向（`PUT /repos/{id}` 增 `root`，受管库 400）+ 事件/节点列表项增来源库归属 `repo_id`/`repo_name`
> 范围（v1.30 追加）：存储保障（整库备份 / 一致性校验 / 图层操作日志 graph_ops 与重放恢复 / graph.json format_version / 跨进程单实例锁 / 回收站留档 / WAL 检查点 / 容量可见）+ 本地日志系统（前后端分文件按天轮转，本地 CLI 翻看）+ 联合检索修正（每库候选池 + 分页只切一次 + 融合轨迹 trace）+ 库作用域贯穿（feedback / events{id} / nodes{id} / ^指令 / agent 维护与补偿）+ 事件与节点联合列表（repo_ids）+ 术语修正（「不可变日志」→「时序事件存储：大模型不可轻易调整，人类可显式修订」）
> 范围（截至 v1.29）：原型阶段 + dpim-webui + 状态校验密钥 + 事件内容修订 + system 源过滤 + BYOK 多模型网关 + Agent 管线 + 运维可靠性（图谱加载容错）+ 检索（FTS5 + 图扩散两路 RRF）+ 上下文护栏回调（MAX_RAW_CONTENT 默认 600000 → 200000）+ 补偿批检查独立间隔（COMPENSATE_CHECK_INTERVAL）+ 图维护任务（调整/合并/删改/节点压缩，POST /agent/maintain，23 端点）+ 安全加固（API Key 掩码 + 可选 API 访问认证 + 输入上限/值域约束 + 日志全文开关）+ 防冗余节点硬规则（redundant_node）+ 节点规模高水位自动维护（AGENT_MAINTAIN_MAX_NODES / COOLDOWN）+ 存储路径/日志级别 dpim.json 持久化 + 事件类型必填化（auto 移除）与类型修订（PUT /events 可改 event_type）+ source 类型管线跳过构图 + max_hops 允许 0（纯检索不扩散）+ GET /events、GET /nodes 支持 query 关键词检索（事件原文/知识节点独立检索）+ 对话指令系统（^compress ^merge ^delete ^data ^node ^cmdmsg 等；语义层需 AI、确定层无 LLM 同步执行、存储类纯离线可用）+ 高水位默认 900→200 / 冷却 300→60 + 压缩底线（内容 <200 字符不再压缩）与合并底线（无规模压力仅近似等价可合并）+ 指令语法收紧（仅 ^英文动词 空格分隔一种形式，其余一律普通文本落库）+ ^help 用法指令 + 前端指令候选弹层（信息传入框，opencode 风格）+ 节点语义（一节点一要点 / 多事件关联 / 子节点层级）+ PUT /nodes 源事件增删（最少保留 1 条有效源证）+ 维护补边通道（edge_adds，孤立节点连线回图）+ 构图边 title 解析修复（弱模型 title 引用不再静默丢边）+ ^update 两阶段结构优化（减碎+补缺失要点 node_adds → 连线，一轮封顶）+ 待连线对候选（link_candidates：词面相关未连边节点对，补边治不连通的主力候选）+ 事件关联节点实时派生（GET /events/{id} 读路径以图层反向索引为准）+ ^cmdmsg 指令消息（笼统自然语言意图 → Gr 读取 Meta 审核，多轮封顶，外部 Agent 调用入口）+ 存储修复（图层双损坏留档不覆盖 + 64MiB 上限 / 节点合并 content·源证上限 / events_fts 启动自愈 / 事件失败原因落库 events.error / 检索排除 skipped）+ 库与分组（一库 = 一 memory.db + 一 graph.json；书库 = 文件夹分组；repos/index.json 登记表持久化受管开关与活动库；legacy 零移动迁移；+7 库端点；ingest/query/events/nodes 库参数；联合检索 = 册间等权 RRF + content_hash/标题去重 + 来源册锚定；health 暴露队列深度/运行态/活动库）+ Cr 短路（AGENT_CR_SKIP_CHARS 默认 200，短文省一次 LLM 调用）

---

### 一、项目定义

DPIM（Double-Place Intelligence Memory）是一个独立于大模型上下文窗口的外部记忆模块。系统通过时序事件存储（信息线层）与知识图谱（信息图层）的双区结构，在 AI 可用时持续衍生结构化知识，在 AI 不可用时降级为基础全文检索存储。

---

### 二、核心实体

#### 2.1 事件 (Event)

事件是系统的最小存储单元，所有信息以事件形式写入信息线层。线层是**按时间追加的时序事件存储**：**大模型不可轻易调整**，人类可通过显式端点改写——`PUT /events/{event_id}` 修订其 raw_content（同步更新 FTS5 索引，自动刷新状态校验密钥）。

**字段定义：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| event_id | string | 是 | 全局唯一，格式 `{timestamp_ms}-{random_hex_8}` |
| created_at | string | 是 | ISO8601 时间戳 |
| raw_content | string | 是 | 原始内容（追加写入；仅人类可通过 PUT /events/{event_id} 显式修订） |
| content_hash | string | 是 | BLAKE2s-8B 十六进制（16 字符；实现为 hashlib.blake2s(digest_size=8)） |
| event_type | enum | 是 | interaction / data / source |
| status | enum | 是 | raw / indexed / linked / failed / skipped |
| graph_refs | string[] | 否 | 关联的图节点 ID 列表（行字段为构图写入时的一次性快照；**API 读路径实时派生**——以图层反向索引为准、仅含有效源证，v1.26） |
| error | string | 否 | 失败原因（v1.28）：脱敏错误摘要（错误类型 + 截断 200 字符，单行），仅 failed 事件非空；重试转回时清空 |

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

**节点语义（v1.22）：**

- **一节点一要点**：每个节点只表达一个要点（单一主张/事实/决策点），title 即该要点；不同要点不得塞进同一节点，用子节点表达从属
- **多事件关联为常态**：一个节点可关联多个源事件（`source_refs` 并集）——同一要点出现在新事件时并入已有节点（merged_into / 去重预检自动改道），而非重复新建
- **允许子节点**：主题节点下的方面/细节/子话题 → 新建子节点 + `subtopic_of`（或 `extends`）关系边挂到主题节点下，构成层级结构

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

**输出**：AnnotatedChunks

| 字段 | 类型 | 说明 |
|------|------|------|
| chunks | SemanticChunk[] | 语义分块列表 |

**SemanticChunk**：

| 字段 | 类型 | 说明 |
|------|------|------|
| content | string | **原文连续子串**（不可增删改；元认知在解析期即完成来源锚定校验） |
| chunk_type | enum | interaction / data / source / ignore |
| label | string | 10 字以内中文标签 |

> `InformationFragment` 是早期模型，已被 `AnnotatedChunks` 取代，**v1.30 从契约与代码中移除**（此前契约仍写着它是本 Agent 的输出，属文档漂移）。

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
- 对话指令：`^compress [节点ID]`（压缩维护轮，删繁就简）、`^update [节点ID]`（结构优化轮，v1.24）与 `^cmdmsg <自然语言指令>`（指令消息，v1.27）入队 `maintain_graph`；不受节点规模阈值约束，可带节点 ID 限定范围（cmdmsg 为全图无 scope）
- 自动（AI 恢复）：AI 恢复触发补偿时**逐库各入队一次**（`AGENT_MAINTAIN_AUTO` 默认开启；图节点数 < `AGENT_MAINTAIN_MIN_NODES` 时自动触发跳过，手动不受限）。**v1.38 修正**：此前只入队**一条不带 `repo_id`** 的消息，而 `Orchestrator._resolve_stores` 对缺省 `repo_id` 回退**默认库**——于是「AI 恢复后的顺带整理」永远只落在默认库：活动库若不是默认库、以及其余各库，一次都拿不到（高水位路径又只覆盖 ≥ `AGENT_MAINTAIN_MAX_NODES` 的大库）
- 自动（节点规模高水位）：**逐受管库检查**，某库总节点数达到 `AGENT_MAINTAIN_MAX_NODES`（默认 **200**）即入队一次**该库**（带 `repo_id`）的维护；每个冷却周期（`AGENT_MAINTAIN_COOLDOWN`，默认 **60s**）**至多触发一册**（防积压期雪崩）；达到高水位即视为「资料库太过庞大」，此时计划附带规模压力标记，允许放宽合并调节
- AI 不可用或管线未启用时跳过

**两阶段结构优化（v1.24，^update 专属）**：
- Phase 1 减碎+补缺：候选 = merge_candidates + oversplit_events（附事件原文摘录）+ zombie_nodes + low_conf_isolated；通道 = merges / deletes / edge_removes / **node_adds**（补缺失要点：锚定已有事件，evidence_quote 须为事件原文连续子串——本地硬校验；可选 parent_node_id 挂 subtopic_of 子节点边；system 禁止）
- Phase 2 连线：**在 Phase 1 执行后的新图上重新扫描** → isolated_nodes；通道 = edge_adds（端点保证幸存——先连线后减碎会让新边指向被合并掉的节点）

**指令消息多轮（v1.27，^cmdmsg 专属）**：
- 指令（≤2000 字符）透传为 payload `instruction`——Gr 读取后在候选内决定通道与力度（增强/减少/整理三类意图），Meta 审「计划是否回应指令」；指令只影响决策倾向，不扩大权限（所有底线与保护照常生效）
- 每轮：候选扫描 + mineable_events 可挖掘事件池（node_adds 锚定源）→ Gr 计划 → Meta 审核 → 执行；空计划/被驳回/无可动对象即停
- 多轮封顶 `AGENT_CMDMSG_MAX_ROUNDS`（默认 3）：每轮在执行后的新图上重扫续轮，直到指令意图被充分响应或无可动对象
- 每阶段空候选即跳过；总封顶一次两阶段，不循环（防震荡）
- 通道收敛（防御）：Gr 越界输出的通道由执行前过滤丢弃（update_reduce 仅 merges/deletes/edge_removes/node_adds；update_connect 仅 edge_adds；compress 全通道禁 node_adds）

**压缩与合并底线（v1.20，防过度整理的损失螺旋；v1.21 补同源豁免）**：
- 压缩底线：概括必然有损——内容已足够精炼（< 200 字符，确定性：不进压缩候选）或证据已颗粒分明的节点禁止再压缩；压缩后内容不得比原文更长（本地硬规则 + Meta 审查）
- 合并底线：两节点共性已被充分描述（相关而非重复）时不再调节，除非规模压力（总节点数 ≥ 高水位）；本地硬规则：无规模压力时重合度 < `JACCARD_THRESHOLD`（0.85）的合并一律驳回（仅近似等价可合并）
- **同源豁免（v1.21）**：同一过碎事件（单事件 ≥ 6 节点）拆出的碎片节点对不受合并底线约束——它们本就是同一件事的拆分，聚合粗化正是压缩的目的；源证相同，合并不丢溯源；严禁把不同事件的节点混入聚合
- 内容合并语义：合并 = target 吸收 source 的源证（并集）+ 内容（整段去重追加）+ 边迁移，**不丢失任何一方内容**

**流程**：

1. **候选扫描**（确定性，无 LLM）：同类型相似节点对（词重叠 Jaccard ≥ 0.6，词桶优化）、无有效源证的僵尸节点、低置信度（<0.4）且无边的孤立节点、可压缩 data 节点（有效源证 ≥ 3 且内容 ≥ 200 字符，或内容 ≥ 500 字符）、**同源过碎事件**（单条事件拆出 ≥ 6 个有效节点，v1.21 新增——治「图太碎」，供 Gr 把同一事件的碎片节点聚合粗化为少数主题节点）、**孤立节点**（无任何边、置信度 ≥ 0.4 且有有效源证，v1.23 新增——治「图不连通」，供 Gr 用补边连回相关节点）、**待连线对**（词重叠 ≥ 0.35 但未连边的节点对，任意类型组合、双方非 system，v1.25 新增——补边主力候选，Gr 判断存在合理关系则连）
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
| edge_adds | MaintenanceEdgeAdd[] | 补边（v1.23）：把孤立节点连回图（source/target 须为已有节点 + relation + reason；evidence 取 source 首条有效源证） |
| node_adds | MaintenanceNodeAdd[] | 补缺失要点（v1.24，仅 update 模式）：锚定已有事件新建节点（title ≤60 + content + node_type + event_id + evidence_quote 原文连续子串 + 可选 parent_node_id 挂子节点边） |
| compresses | MaintenanceCompress[] | 概括压缩 data 节点（node_id + content + 可选 title + 可选 new_edges + reason） |
| confidence | number | 计划整体置信度 0.0~1.0 |

#### 4.5 对话指令系统（v1.20 引入；v1.21 语法收紧）

信息传入框（`POST /ingest`）输入指令文本时，系统解析并执行运维动作，**不把指令本身落库为事件**（存储类指令除外——它本身就是写事件）。解析纯确定性（无 LLM）。

**语法（v1.21，仅此一种形式）**：`^动词 [参数...]` —— 仅 `^` 前缀 + 英文指令词（大小写不敏感）+ **空格分隔**（冒号不是分隔符）；全角 `＾ ｜` 归一化为 `^ |`。**其余一律不是指令**（`/` 前缀、中文指令词、`^data: 内容` 冒号形式、未知 `^词`、裸 `^`）——按普通文本正常落库为事件。前端「信息传入」框输入 `^` 时自动弹出指令候选（opencode 风格：前缀过滤、↑↓ 换选、Enter/Tab 填入、Esc 关闭）。

**响应语义**：`IngestResponse` 新增 `command_triggered: bool = false`。指令未创建事件时 `event_id=""`、`status="skipped"`，`message` 携带面向用户的执行结果；存储类指令创建真实事件，返回常规响应（`command_triggered=false`）。

**指令集**：

| 指令 | 层级 | 语义 | AI 不可用时 |
|------|------|------|------------|
| `^compress [节点ID]` | 语义层 | 触发图维护轮（扫描 → Gr → Meta → 执行）；保守语义：全图足够简练则空计划、不做任何改动；可带节点 ID 限定只处理该节点相关候选（`maintain_graph` payload `scope`，节点须存在否则入队前拒绝）。定位：删繁就简 | 明示拒绝（不入队），提示纯存储指令不受影响 |
| `^update [节点ID]` | 语义层 | 触发**两阶段结构优化**（v1.24）：Phase1 减碎+补缺（聚合过碎/清僵尸低置信/删错误边/补缺失要点 node_adds——锚定已有事件 + quote 原文子串硬校验）→ 重扫 → Phase2 连线（edge_adds 孤岛回图）；一轮封顶；节点已良好则不动 | 明示拒绝（不入队） |
| `^cmdmsg <自然语言指令>` | 语义层 | **指令消息**（v1.27，Command message）：给在线 Agent 发笼统调整意图（如「帮我减少某些记忆」，≤2000 字符，不带节点数据）；入队 `maintain_graph` payload `instruction`——Gr 读取指令在候选内决定通道与力度（增加类意图可从 mineable_events 最近已构图事件池锚定 node_adds），Meta 审「计划是否回应指令」；**指令只影响候选内决策倾向，不扩大权限**（所有底线与保护照常生效）；多轮封顶（`AGENT_CMDMSG_MAX_ROUNDS` 默认 3，每轮执行后重扫续轮，空计划/被驳回/无可动对象即停）。外部 Agent 经 `POST /ingest` + `X-API-Key` 调用即此接口 | 明示拒绝（不入队），提示纯存储指令不受影响 |
| `^merge <目标ID> <源ID>` | 确定层 | 同步执行 `merge_nodes`：源证并集 + 内容整段去重合并 + 边迁移 + FTS 同步；仅同类型、system 拒绝、缺失报错 | 正常执行（无 LLM） |
| `^delete <节点ID>` | 确定层 | 同步删除节点：删除保护（有有效源证拒绝）+ system 保护（手工节点无事件来源，删除后不可恢复，指向图页/REST 通道） | 正常执行（无 LLM） |
| `^data <内容>` / `^interaction <内容>` / `^source <内容>` | 存储 | 显式类型写入线层（指令前缀不落库，仅存 `<内容>`），管线启用时照常入队构图 | 正常写入（停留 indexed 等补偿） |
| `^node system <标题> \| <内容>` | 确定层 | 手工系统节点直建（无源证要求，`source_refs=[]`，confidence=0.7，标题 ≤60 字符）+ FTS 索引；data/interaction 不开放直建（必须保留事件证据链） | 正常执行（无 LLM） |
| `^help` | — | 返回全部指令用法说明，不动数据 | — |

**纪律**：指令是入口不是特权——所有指令动作均受既有硬规则约束（system 保护、data 只追加、source_refs 保留、删除保护）；指令执行留日志不建事件审计（与图维护行为一致）。

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

#### 7.4 存储保障（v1.30）

| 机制 | 说明 |
|------|------|
| 图层操作日志 `graph_ops` | 同库追加表（schema v3）。每次落盘把「相对上次落盘的状态差分」写成一批 op：`node_upsert` / `node_delete`（**附带被删节点原数据**）/ `edge_upsert` / `edge_delete`，带 `reason`（因何改图）。用途：审计 + `graph.json` 丢失/损坏且无可用备份时的**重放恢复**。**保留策略（v1.39）**：行数超过 `GRAPH_OPS_RETENTION`（默认 **5000**，0 = 不压实）时，把最老明细**压实**成一批**等价快照 op**（`graph_clear` + 逐节点/逐边 upsert，`reason=retention-compaction`）——`replay(压实后) == replay(压实前)`，故**重放恢复能力与 `verify` 口径都不变**，只是老明细不再可审计；表行数下限 = **1 + 节点数 + 边数**（快照本身），快照不比被替换的明细小时**原样不动**（避免越压越多）；压实会重写 `op_id`（顺序与内容等价） |
| `format_version` | `graph.json` 顶层字段。版本高于本程序支持 → 留档拒读（`.newer-vN-<时间戳>`），绝不用旧格式覆盖新数据 |
| 多代备份 | `<name>.bak.1..N`（默认 3 代），**覆盖前**留存上一代；加载成功也会留一代 |
| 整库备份 | `<数据根>/backups/<时间戳>/`：`memory.db`（`VACUUM INTO` 在线副本）+ `graph.json` + `manifest.json`；保留最近 5 份 |
| 一致性校验 | SQLite 完整性/外键、`events↔events_fts`、节点↔`node_fts`、**`graph_ops` 重放 == 内存图**、悬空源证、缺 data 的节点 |
| 跨进程互斥 | 每库一把 OS 文件锁（`<db>.lock`）：Windows `msvcrt.locking` / POSIX `flock`，非阻塞获取、进程退出由内核释放（无陈旧锁）；拿不到锁的库跳过打开并进诊断 |
| 回收站 | 物理删除前留档 `<数据根>/trash/{events,nodes}/<id>.json`；`EventStore.restore()` 按**原 id** 重新入库（源证随之重新对上）。**保留策略（v1.39）**：留档文件**按年龄**清理——超过 `TRASH_RETENTION_DAYS`（默认 **30** 天，0 = **永不清理**）按文件 mtime 删除，`trash/restored/` 的痕迹同样按年龄清；只动这三个目录里的 `.json`，其余文件一律不碰（留档是已删数据的**最后一份副本**，故默认宽、可关） |
| WAL 治理 | 周期检查点（超阈值 `TRUNCATE`，默认阈值 8 MiB / 间隔 300s）；`/health` 与校验回报 db/wal/json 体积 |
| 本地日志 | `logs/backend-YYYY-MM-DD.log` 与 `logs/frontend-YYYY-MM-DD.log` **分文件**按天轮转，保留 14 天，可选 JSONL；写请求统一收口（落盘脏图 + 刷新状态密钥 + 写操作流水） |

> **恢复不提供 REST 端点**：恢复须停服务（内存图会陈旧），由本地 CLI 执行并强制先做一次安全备份。

---

### 八、API 端点

> 当前共 45 个端点（v1.30：+6 存储维护与库刷新端点；v1.31：+6 本地日志 / 回收站 / 登记表重建 / 书目清除端点；v1.32：+1 书目收养端点；v1.34：+1 模型列表探测端点；v1.37：+1 边列表端点 `GET /edges`）。查询同步返回；写操作在 Agent 管线启用时异步入队，否则同步确认。

**访问认证（可选，v1.13 新增）：** 环境变量 `DPIM_API_KEY` 非空时，所有端点要求请求头 `X-API-Key` 匹配，不匹配返回 `401`；默认为空（本地模式零配置不启用）。WebUI 通过 localStorage `dpim_api_key` 自动附带该头。此密钥仅经环境变量配置，不经 `GET /settings` 下发、不经 `PUT /settings` 修改。

#### 8.1 写入类

| 方法 | 路径 | 说明 | 请求体 |
|------|------|------|--------|
| POST | /ingest | 写入事件（event_type 必填；`repo_id` 可选指定目标库，缺省活动库，v1.29；识别对话指令 ^compress ^merge ^delete ^data ^node 等，见 4.5） | IngestRequest |
| PUT | /events/{event_id} | 修改事件内容与类型（更新 raw_content + FTS5；event_type 可选修订） | `{"content": "...", "event_type": "..."}` |
| PUT | /events/{event_id}/status | 修改事件状态 | ModifyEventStatusRequest |
| DELETE | /events/{event_id} | 删除事件（带源证保护） | — |
| POST | /nodes | 人工创建图节点（source_event_id 可选） | CreateNodeRequest |
| PUT | /nodes/{node_id} | 修改节点：content（system 禁改）+ 源事件增删（add 幂等 / remove 最少保留 1 条有效源证，v1.22） | ModifyNodeRequest |
| DELETE | /nodes/{node_id} | 删除节点（force=true 覆盖源证保护） | DeleteNodeRequest |
| POST | /edges | 创建关联边 | CreateEdgeRequest |
| DELETE | /edges | 删除关联边（query: source, target） | — |
| DELETE | /graph | 清空图谱（节点 + 边，同步清 node_fts） | — |
| PUT | /settings | 批量更新配置项（持久化 dpim.json）。**v1.35**：提交已移除的 `llm_*` 字段 → **422**（不再静默忽略）；`providers[*].clear_api_key: true` = 显式清空该条密钥（标记不入库）。**v1.36**：可配置面扩到检索/健康/维护/日志/WAL 各项；**被环境变量顶掉的项不写入内存**，响应 `ignored_by_env` 点名（如 `["rrf_k(DPIM_RRF_K)"]`），`message` 同步说明 | SettingsUpdateRequest |
| POST | /repos | 建库（v1.29）：managed 落分组目录 `<group_key>/<repo_id>/`；external 登记既有目录（须含两文件，禁设清单校验，只登记不复制） | RepoCreateRequest |
| POST | /repos/adopt | **收养既有目录**（v1.32）：目录里 `memory.db` / `graph.json` **至少有一个**即可登记为 external 书目；缺 `memory.db` 补空库（走 `Database` 建表路径，当前 schema）、缺 `graph.json` 补空图（带 `format_version`）并**顺带尝试从 `graph_ops` 重放恢复图层**（恢复不了就留空图，不报错）；**只补空件、绝不覆盖已存在的文件**；一个文件都没有 400、该目录已登记为某书目 409、禁设清单照旧生效；`adopt_missing=false` 时缺件即 400。响应 `{repo_id, message, created}`（`created` = 实际补出来的文件名，如 `["graph.json"]`） | RepoAdoptRequest |
| PUT | /repos/{repo_id} | 改库信息 / 受管开关（false = 休眠：不加载不检索不构图，文件不动；切换即时生效）；**v1.31 增可选 `root`** = 外部库**重指向**（换目录，须含 memory.db + graph.json 且过禁设清单）；受管库传 `root` 直接 **400**（受管库目录由系统管理） | RepoUpdateRequest |
| DELETE | /repos/{repo_id} | 摘除登记（**不删磁盘文件**；默认库与活动库不可摘 409） | — |
| POST | /repos/{repo_id}/activate | 切换活动库（未受管 409） | — |
| POST | /repos/{repo_id}/generate | 库级联合生成知识：该库全部待构图事件（raw/indexed）批量入队（AI 不可用 409） | — |
| POST | /agent/compensate | 手动触发补偿：积压 raw/indexed 事件重入队（v1.29 起逐受管库收集；v1.30 增 `repo_id` 指定库） | — |
| POST | /agent/maintain | 手动触发图维护：扫描候选 → Gr 计划 → Meta 审核 → 执行。**v1.32 增请求体 `{mode: 'compress'\|'update'}`**（默认 `update` = 两阶段结构优化：Phase1 减碎+补缺 → Phase2 连线；`compress` = 删繁就简；body 可省略，缺省 `update`）；**v1.32 修复**：此前该端点完全不读 body、payload 恒为 `{}` → `payload.get("mode")` 永远为 None →「前端选 update 实际走 compress」，`^update` 能力只有 `^指令` 一条路可达。非法 `mode` → 422。query：`repo_id`（v1.30 指定库，缺省活动库）；AI 可用性不由端点判定（入队后 worker 处理，不可用时自行跳过） | MaintainRequest |

#### 8.2 读取类

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /query | 混合检索（Agent 可用时走 Agent 检索，失败回退）。`repo_ids` 可选（v1.29）：单库 = 指定库检索；缺省多库 = **联合检索**（逐受管库检索 → 库间等权 RRF 融合 + 去重（事件按 content_hash、节点按类型+标题）+ 来源库锚定 `repo_id/repo_name/source_repos`，纯本地降级可用）；列表含未知库 422。**v1.30 修正**：每库取候选池（`limit×3`，下限 50）后融合、分页**只切一次**（原双重分页使第二页错乱、total 失真）；响应增 `trace`（每库候选数/耗时 + 本页每条结果在各库的排名/原始分/RRF 贡献），单库检索 `trace` 为 null |
| POST | /feedback | 检索反馈（调整节点置信度）；`repo_id`（v1.30）指定库，缺省活动库——跨库结果必须带上，否则静默落在活动库 |
| GET | /health | 健康检查 + 双区统计（v1.29 增 `queue_depth`/`worker_running`/`active_repo_id`；v1.30 增 `storage`：db/wal/json 体积、备份份数、操作日志条数；v1.34 起 `status` 三态 `ok`\|`unconfigured`\|`degraded` + `ai_unavailable_reason`。**v1.41 明确分层统计的键名**：`layers.event_line` = `{total_events, raw, indexed, linked, failed, skipped}`、`layers.knowledge_graph` = `{total_nodes, system, interaction, data}`——**没有** `status_*` / `*_nodes` 前缀那种写法，前端类型此前写错了，界面照着类型取值 → 概览台四个分项恒显示「—」） |
| GET | /state-hash | 状态校验密钥 |
| GET | /repos | 库登记列表（计数仅已加载库给出；休眠库为 null，v1.29；**v1.32 增 `load_error`：未加载原因**） |
| GET | /repos/{repo_id} | 库详情（含状态分布；休眠库计数 null；v1.32 同样带 `load_error`） |
| GET | /events | 分页事件列表（v1.19 增 `query` 关键词检索：事件 FTS 中文降级，可叠加 status/type 过滤；v1.29 增 `repo_id` 库过滤；**v1.30 增 `repo_ids=a,b` 联合列表**（逐库候选池 → 按 content_hash 去重 → 时间倒序 → 分页只切一次）；v1.28 起 items 携带 `error` 失败原因；**v1.31 起 items 携带来源库归属 `repo_id`/`repo_name`**（单库查询填该库；库登记未初始化时为空串）） |
| GET | /events/{event_id} | 事件详情（graph_refs 实时派生，v1.26；v1.28 起含 `error`；v1.30 增 `repo_id` 库作用域——跨库跳转必须带上，否则 404） |
| GET | /nodes | 分页节点列表（v1.19 增 `query` 关键词检索：节点 FTS 中文降级，可叠加 type 过滤；v1.29 增 `repo_id` 库过滤；**v1.30 增 `repo_ids=a,b` 联合列表**（按类型+标题归一去重）；**v1.31 起 items 携带来源库归属 `repo_id`/`repo_name`**；**v1.40 修正**：联合列表的 `node_type` 此前写成 `str(枚举)` → `"NodeType.data"`（单库路径是 `"data"`），前端「全部书目」下按类型筛选会**全部失配**，现统一为值文本） |
| GET | /nodes/{node_id} | 节点详情（含关联边；v1.30 增 `repo_id` 库作用域） |
| GET | /edges | **边列表（v1.37）**：图谱页一次取全（此前靠逐节点 `GET /nodes/{id}` 汇总边：400 节点 ≈ 17 批请求，且单批失败静默丢边）。query：`node_id`（**两侧**命中）/ `source` / `target` / `relation` 筛选；作用域 `repo_id`（缺省活动库）或 `repo_ids=a,b`（联合：按 (source, target) 去重 + 首命中库归属）；`limit` 默认 **200**、**0..5000（越界 400）**，`offset` 负数 400。items = `EdgeListItem`（`source`/`target`/`relation`/`evidence_event_id` + `repo_id`/`repo_name`），**按 (source, target) 稳定排序**（分页可复现） |
| GET | /settings | 获取所有配置项（v1.34：**不再下发 7 个 `llm_*` 身份字段**——身份只存在于 `providers` 条目里；增 `llm_configured`（是否已有一个可用的 provider 条目）与 `llm_unavailable_reason`（未配置/未登记的中文原因，已配置为空串）；`available_providers` 默认空列表。**v1.36**：可配置面扩到检索/健康/维护/日志/WAL（+14 字段，见 §9），并新增三个**只读可见性**字段——`config_sources`（逐项标 `env:DPIM_X` / `file` / `default`，界面据此把被环境变量顶掉的项置灰并注明变量名）、`config_file`（在用的 `dpim.json` 绝对路径）、`log_dir`（本地日志目录）；响应按字段名自动从运行时配置取值，故新增配置项必随契约同步下发。**v1.39**：增 `graph_ops_retention` / `trash_retention_days`（保留策略，见 §9）） |
| POST | /settings/models | **联网探测某提供商的模型列表**（v1.34）：body `{provider, base_url, api_key}`（`api_key` 可为空 = 用已登记的密钥），走该提供商的 OpenAI 兼容 `GET /v1/models`；响应 `{models:[str], error:str, elapsed_ms:int}`——**探测失败不报 4xx/5xx**，错误摘要放 `error`（如 `AuthenticationError: ...`），`models` 为空；超时取 `min(health_check_timeout, 60)` 秒。**不改任何配置、不触发状态校验密钥刷新**（只读探测） |
| GET | /agent/logs | AI 调用日志（环形缓冲，新→旧） |

#### 8.3 存储维护类（v1.30）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /maintenance/backup | 整库备份：SQLite `VACUUM INTO` 在线副本 + graph.json + manifest.json（计数/版本/体积），保留最近 N 份（默认 5）；内存库 409。query：`note`、`repo_id` |
| GET | /maintenance/backups | 列出整库备份（新到旧，含 manifest） |
| POST | /maintenance/verify | **只读**一致性校验：SQLite 完整性/外键、`events↔events_fts` 行数、节点↔`node_fts` 行数、**`graph_ops` 重放结果 == 内存图**、悬空源证、缺 data 的节点；返回 `{ok, checks, sizes, counts}` |
| GET | /maintenance/ops | 图层操作日志（审计）：谁 / 何时 / 因何改了图。`payload` 为变更明细；`node_delete` 附带被删节点原数据（合并吸收的节点靠此留痕）。query：`limit`（≤500）、`offset`、`repo_id` |
| POST | /maintenance/checkpoint | WAL 检查点（TRUNCATE）：收回主库并截断 WAL；返回 busy/帧数与 WAL 体积 |
| POST | /repos/{repo_id}/refresh | 显式刷新/修复一个库：重新对账源证 → 脏则落盘 → 回报统计；未知库 404，休眠库 409 |

> **恢复（restore）不提供 REST 端点**：恢复必须停服务（内存图会陈旧），由本地 CLI
> `python main.py restore <时间戳>` 执行，且强制先给当前状态做一次安全备份；
> 留档删除的事件用 `python main.py trash-restore <event_id>` 按原 id 重新入库。

#### 8.4 本地日志与回收站（v1.31）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /logs | 翻看本地日志尾部。query：`kind`（`backend`\|`frontend`，默认 `backend`；非法 400）、`date`（`YYYY-MM-DD`，可空 = 该通道**最新**日期；格式非法 400）、`level`（可空，大小写不敏感，按行内级别词过滤）、`keyword`（可空，子串匹配）、`tail`（默认 200，1..2000，越界 400）。响应 `{kind, date, dir, files:[{name,kind,date,size,mtime}], lines:[str], truncated}`——`files` 是该通道**全部**可用日志（按日期倒序），`dir` 是日志目录绝对路径，`truncated` 表示**过滤后**匹配行数超过 `tail`（返回的仍是最新 tail 行）。只读：不改任何状态、不触发状态校验密钥刷新 |
| POST | /logs/client | 浏览器把一条前端日志送回本地：body `{level: debug\|info\|warning\|error, message: str, source: str}`（`message` 超 8000 字符**截断**；空 message 400），落 `frontend-YYYY-MM-DD.log`；响应 `{ok: true}`。**不刷新状态校验密钥**——日志上报属旁路而非数据写入（`write_commit` 显式豁免，路径+方法精确匹配），否则前端每次上报日志都会让密钥变化、把「写前比对密钥」的护栏变成噪声 |
| GET | /trash | 回收站留档清单。query：`repo_id`（可空 = 活动库）。响应 `{items:[{kind:'event'\|'node', id, archived_at, size, title, path}], dir}`，按 `archived_at` 倒序；`title` 取留档内容里的标题/内容摘要（没有则空串）。留档目录 = 库文件同级的 `trash/`（`trash/events/<event_id>.json`、`trash/nodes/<node_id>.json`） |
| POST | /trash/restore | 从留档恢复。body `{kind:'event'\|'node', id}`；响应 `{message}`。事件走 `EventStore.restore()` **按原 id** 重新入库（FTS 重建，既有图节点源证随之重新对上）；节点恢复节点本体 + `source_refs`，并**尽力恢复留档边信息**（删除时随节点一并留档的关联边，仅当两端节点都在图中且该边不存在时才补回）。**已存在同 id → 409**，**找不到留档 → 404**；恢复成功后留档文件**移入 `trash/restored/`**（不删原文件：保留「恢复过什么」的痕迹，与损坏原件留档 `.corrupt-*` 同一纪律）。query：`repo_id`（可空 = 活动库） |
| POST | /repos/rebuild | **重建 `repos/index.json` 登记表**（坏索引恢复）。语义：清掉只读锁存 → 扫描磁盘上可识别的库（受管库根下每个含 `memory.db` 或 `graph.json` 的目录（**排除 `backups/`、`trash/` 内的副本**）+ 现役默认库 + 仍存在的外部库根）→ 重建登记表并保存。响应 `{message, repos, latched_before}`（`latched_before` = 重建前是否处于锁存态）。**绝不删除任何磁盘数据文件**；受管库的休眠标记只存在于登记表，磁盘上无痕迹，故重建时无法还原（重塑库一律按受管恢复） |
| POST | /repos/{repo_id}/purge | **清除书目**：先对 db 做一次整库备份（`create_backup`，路径回填 `backup_path`），再删除 `memory.db`（含 `-wal`/`-shm`/`.lock`）与 `graph.json` 及其 `.bak.*`，最后从登记表摘除。**默认库 400、活动库 409**（中文原因）；**外部库只摘除登记、不删外部目录文件**（message 说明）。响应 `{message, backup_path}` |

> **为什么 `purge` 与 `DELETE /repos/{id}` 并存**：`DELETE` 是「只摘登记、文件一个不动」，
> `purge` 是「备份后连文件一起清」。要放弃数据但连备份都不想要时，仍可用 `DELETE` 摘登记后手工删目录。

**分页约定（适用于 GET /events、GET /nodes、GET /edges）：**

| 查询参数 | 类型 | 默认值 | 说明 |
|----------|------|--------|------|
| limit | int | 20（`GET /edges` 为 200） | 每页条数（上限口径见下） |
| offset | int | 0 | 偏移量 |

> **`limit` 上限的真实口径（v1.37 逐条核实）**：
> ① `GET /events` —— **两个分支都收到 100**（`min(limit, 100)`，**静默**）；
> ② `GET /nodes` —— **`query` 关键词分支**收到 100（`min(limit, 100)`，静默），**非 query 分支不设上限**
> （信息图谱页正是靠 `limit=400` 一次取全节点；本节此前写的「最大 100」与实况不符，已按实况改写）；
> ③ `GET /edges`（v1.37 新增）—— **0..5000 显式校验，越界 400**，不静默截断：
> 「少了一半边」比「报错」更难察觉（图看起来只是不连通），故这里选择响亮地失败。

额外参数：
- `GET /events`：`status`（事件状态筛选），`type`（事件类型筛选）
- `GET /nodes`：`type`（节点类型筛选）
- `GET /edges`：`node_id`（两侧命中）/ `source` / `target` / `relation`（v1.37）

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

- `GET /settings` 下发的 `providers[*].api_key` 一律为**掩码值**（格式 `{前3字符}****{后4字符}`，短密钥全掩码，空密钥为空串），明文密钥绝不出网。**v1.34 起 `llm_api_key` 字段不再存在**——密钥只在 provider 条目里。
- `PUT /settings` 对密钥字段采用**掩码幂等保留**：提交掩码值或空串 = 保留现值不变；提交其他非空值 = 替换。前端把 GET 下发的掩码原样回传不会清掉密钥。**掩码形状的值绝不被当作真钥落盘**（v1.33 `core/security.py` `looks_like_mask()`：`xxx****xxxx` 或全掩码 `****`，无论现值是否为空都保留现值；新建/重命名 provider 时前端把别处的掩码带过来会被丢弃）。
- **未配置 ≠ 降级（v1.34）**：`llm_configured=false`（没有任何 provider 条目、活动 provider 未登记、base_url 为空、模型列表为空）时系统**不发起任何探测、不计失败次数**，`AIState` 置为未配置并带中文原因；健康状态 `unconfigured`。只有**已配置但连不上**（连续失败 3 次）才是 `degraded`。此区分是「无 AI 模式是默认运行态」的落地：未配置不发告警、不刷退避。
- 配置身份只经 `providers`（`dpim.json` 的 `providers` 段或 env `DPIM_PROVIDERS`）；**`primary` 只是普通 provider 键名**，不再有特殊语义。显式指定 `active_provider` 但未登记时**原样保留该名字并报「未登记」**，不静默换一个。
- **清空密钥必须显式声明（v1.35）**：`providers[*].clear_api_key: true` 时该条目的 `api_key` 置空（本地服务无需密钥的场景）；标记本身不入库、GET 从不下发。不带该标记时「空串 / 掩码形状 = 保持现值」的幂等语义不变（前端原样回传掩码绝不会误删密钥）。
- **提交已移除的字段是错误而非噪声（v1.35）**：`PUT /settings` 收到 `llm_base_url` / `llm_api_key` / `llm_model_name` / `llm_timeout` / `llm_max_tokens` / `llm_enable_thinking` / `llm_thinking_budget` 任一 → **422**（`detail[].loc` 指向具体字段，`msg` 说明已改用 `providers` 并要求刷新页面）。此前静默忽略会让旧界面误以为保存成功。
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

> **v1.36 起「前端可配置面」**：除下面标注 **env-only** 的项外，本表各项都可经 `PUT /settings` 修改并**落盘 `dpim.json`**，读取链统一为 **env → `dpim.json` 对应段 → 内置默认**；env 仍然优先（`dpim/.env` 经 `load_dotenv()` 也算 env），被 env 顶掉的项界面上会显示「由环境变量 DPIM_X 决定」并且 PUT 不会写入内存。取值来源可经 `GET /settings` 的 `config_sources` 逐项查（`env:DPIM_X` / `file` / `default`）。
> **有意保留 env-only**：`API_KEY`（访问认证密钥，经 API 自我暴露不可接受）、`LOG_DIR`（改路径需重开文件句柄）、`LLM_TIMEOUT` / `LLM_MAX_TOKENS` / `LLM_ENABLE_THINKING` / `LLM_THINKING_BUDGET`（这四项是 provider 条目的全局兜底，条目里已可直接配置）。
> **生效时机**：存储路径 / `LOG_LEVEL` / `LOG_RETENTION_DAYS` / `LOG_JSONL` 需重启（读取点在启动时的存储句柄与 `setup_file_logging`）；其余各项在循环内或按请求读取，**改完即时生效**。

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| MEMORY_DB_PATH | ./data/memory.db | SQLite 数据库路径（v1.16：env → dpim.json storage → 默认；可经 PUT /settings 修改，重启生效） |
| GRAPH_JSON_PATH | ./data/graph.json | 图层 JSON 路径（v1.16：同上，持久化 dpim.json；数据文件不自动迁移） |
| **LLM_BASE_URL** | (空) | **v1.34**：不再是身份配置，仅作**纯 env 部署的种子**——只有显式给出且 `providers` 为空时才合成名为 `default` 的条目（`{base_url, api_key: LLM_API_KEY, models: [LLM_MODEL_NAME]?}`）。未给出即「未配置」，不再回退本地 llama 地址 |
| **LLM_API_KEY** | (空) | 同上：只在该 env 种子条目里使用 |
| **LLM_MODEL_NAME** | (空) | 同上：只在该 env 种子条目里使用（v1.34 起**无内置默认模型名**） |
| LLM_TIMEOUT | 666 | **全局调优默认**（v1.34：仅 env，不进 API）：provider 条目未写 `timeout` 时用此值（秒，本地模型宽容默认） |
| **LLM_MAX_TOKENS** | (空) | **全局调优默认**（v1.34：仅 env）：provider 条目未写时用此值（0/空 = 服务端默认） |
| **LLM_ENABLE_THINKING** | (空) | **全局调优默认**（v1.34：仅 env）：provider 条目未写时用此值（true/false/空 = 服务端默认） |
| **LLM_THINKING_BUDGET** | (空) | **全局调优默认**（v1.34：仅 env）：provider 条目未写时用此值（0/空 = 不设） |
| **PROVIDERS** | (空 JSON) | BYOK 多 provider 注册（JSON dict：name → {base_url, api_key, models, timeout, max_tokens, enable_thinking, thinking_budget, thinking_style, extra_body, structured_mode}）；**v1.34：AI 身份的唯一来源**（env `DPIM_PROVIDERS` 优先，否则 `dpim.json` 的 `providers` 段） |
| **ACTIVE_PROVIDER** | (空 = 注册表首个) | 活动 provider 键名（v1.34：**无 `primary` 特殊语义**，就是一个普通键名）；显式指定但未登记则原样保留并报「未登记」 |
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
| **AGENT_MAINTAIN_AUTO** | true | 图维护自动触发：AI 恢复触发补偿时**逐库各入队一次**整理（合并/删除/修改/删边，v1.38）＋ 节点规模高水位逐册触发 |
| **AGENT_MAINTAIN_MIN_NODES** | 10 | 自动维护最小图规模（节点数；小图跳过，手动触发不受限） |
| **AGENT_MAINTAIN_MAX_NODES** | 200 | 节点规模高水位（v1.20 调降）：总节点数达到后每个冷却周期自动入队一次图维护；达到即视为「资料库太过庞大」，允许放宽合并（规模压力标记） |
| **AGENT_MAINTAIN_COOLDOWN** | 60 | 高水位自动维护触发冷却（秒，v1.20 调降）：此后每个冷却周期都准备压缩 |
| **AGENT_CMDMSG_MAX_ROUNDS** | 3 | cmdmsg 指令消息多轮封顶（v1.27）：每轮重扫 + Gr 按指令决策 + Meta 审 + 执行；空计划/被驳回/无可动对象即停，防指令驱动的无限循环 |
| **AGENT_CR_SKIP_CHARS** | 200 | Cr 短路阈值（v1.29）：原文长度不超过该值时跳过 Cr 概括，短事件管线省一次 LLM 调用；0 = 关闭短路 |
| **API_KEY** | (空) | API 访问认证（v1.13）：非空时所有端点要求 `X-API-Key` 请求头匹配；仅 env 配置，不经 API 下发/修改 |
| **LOG_DIR** | `<dpim>/logs` | 本地日志目录（v1.30）：`backend-*.log` 与 `frontend-*.log` 分文件存放；仅 env，不经 API 下发 |
| **LOG_RETENTION_DAYS** | 14 | 日志保留天数（0 = 不清理旧文件） |
| **LOG_JSONL** | false | 额外输出 JSONL（程序读；人读用默认文本格式） |
| **WAL_CHECKPOINT_INTERVAL** | 300 | WAL 检查点周期（秒，v1.30） |
| **WAL_CHECKPOINT_BYTES** | 8388608 | WAL 体积超过该值才做检查点（默认 8 MiB） |
| **GRAPH_OPS_RETENTION** | 5000 | 图层操作日志保留条数（v1.39）：超限把最老明细**压实**成等价快照（重放/恢复能力不变）；0 = 不压实；值域 0..1000000 |
| **TRASH_RETENTION_DAYS** | 30 | 回收站留档保留天数（v1.39）：**按 mtime** 清理过期留档（含 `restored/` 痕迹）；0 = 永不清理；值域 0..3650 |
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
> 2026-08-21：规约升级至 v1.19。检索页「事件原文/知识节点」独立化：`GET /events` 与 `GET /nodes` 新增可选 `query` 关键词参数（事件/节点 FTS，中文自动降级；可叠加既有 status/type 过滤与分页）——此前前端这两类模式经由 `/query` 混合检索的 `source_filter` 过滤，会滤成"类型匹配的图节点"而非事件原文/节点本身（interaction 事件构图后多为 data 节点 → 事件原文检索经常搜空）；前端检索页改为直接调用列表端点，混合检索仅「综合检索」模式使用。
> 2026-08-29：规约升级至 v1.20。对话指令系统 + 高水位调降：① `POST /ingest` 识别对话指令（4.5 节）：`/compress [节点ID]`（`/压缩` `^压缩`，语义层需 AI，不可用时明示拒绝）触发图维护轮；`/merge`（`/合并`）、`/delete`（`/删除`）、`/node system:`（`/建节点`）确定层无 LLM 同步执行；`/data:`（`/数据:`）、`/interaction:`（`/对话:`）、`/source:`（`/来源:`）显式类型存储（纯离线可用，指令前缀不落库）；未知指令返回用法；`IngestResponse` 新增 `command_triggered`（未创建事件时 event_id=""、status=skipped、message 携带结果）；POST /nodes 补 FTS 索引（顺带修复手工节点不可检索缺口）。② 高水位 `AGENT_MAINTAIN_MAX_NODES` 默认 900 → **200**、`AGENT_MAINTAIN_COOLDOWN` 默认 300 → **60s**（此后每个冷却周期都准备压缩）。③ 压缩与合并底线：压缩候选内容 < 200 字符不再压缩（防损失螺旋）；概括不得比原文更长（本地硬规则）；无规模压力（总节点数 < 高水位）时重合 < JACCARD_THRESHOLD 的合并本地驳回（共性已被充分描述则不再调节，除非资料库太过庞大）。④ Gr/Meta 提示词编码两条底线；扫描结果新增 size_pressure 标记。
> 2026-08-29：规约升级至 v1.21。指令语法收紧 + 前端指令候选 + 同源聚合（治碎）：① 4.5 指令语法收敛为**仅 `^英文动词`（空格分隔）一种形式**——`/` 前缀、中文指令词（^压缩 等）、冒号分隔（`^data: 内容`）、未知 `^词`、裸 `^` 一律**不是指令**，按普通文本正常落库（用户定夺：最严格 ban）；指令集更名 `^compress [节点ID]` / `^merge` / `^delete` / `^data` / `^interaction` / `^source` / `^node system <标题> \| <内容>`，新增 `^help` 用法指令。② 收尾链 Q 自查修复：`^node` 标题超 60 字符守卫（防 500）、`^delete` 对 system 节点拒绝（无事件来源不可恢复）、`^compress` scope 节点存在性预检（防静默空转）、维护 scope 过滤保留 size_pressure、前端降级态允许提交（AI 不可用时纯存储/指令照常可用，普通事件提示等待补偿）。③ 前端「信息传入」框新增指令候选弹层（opencode 风格）：输入 `^` 自动弹出、前缀过滤、↑↓ 换选、Enter/Tab 填入 `^verb `、Esc 关闭、可点击；候选清单单一来源 `src/api/commands.ts`；全角 `＾` 触发候选；长指令结果（如 ^help）改对话框展示；空事件 ID 守卫（提示后端版本可能过旧）。④ Gr 提示词补「全图足够简练 → 宁可空计划」显式表述。⑤ **候选扫描新增同源过碎类（oversplit_events，v1.21）**：单条事件拆出 ≥ 6 个有效节点 → 过碎候选（event_id + 节点清单，system 不计），供 Gr 把同一事件的碎片节点按主题聚合粗化为少数节点（走 merges 通道）；合并底线新增**同源豁免**——同一过碎事件内的节点对不受「重合 ≥ 0.85」约束（源证相同聚合不丢溯源），组外节点仍受约束；Gr/Meta 提示词编码聚合规则与审查规则。⑥ `^compress` 候选扫描前移至响应前（纯本地毫秒级）：无候选立即明示「无需压缩」不入队，有候选入队并在消息中报出各类候选数量（重合对/僵尸/孤立低置信/冗长可压缩/同源过碎）——消除「静默正确」造成的没反应错觉。
> 2026-08-29：规约升级至 v1.22。节点语义与源证管理：① **节点语义**（2.2 节）：一节点一要点（title 即该要点，不同要点用子节点表达）；多事件关联为常态（source_refs 并集，同要点新事件并入已有节点）；允许子节点（方面/细节节点经 subtopic_of / extends 边挂到主题节点下）。② **`PUT /nodes/{node_id}` 扩展源事件管理**：`ModifyNodeRequest` 新增 `add_source_event_id`（幂等追加，事件须存在，hash 取事件 content_hash）与 `remove_source_event_id`（移除单条源证并同步反向索引）；**最少源证守卫**——移除后须仍保留 ≥1 条有效源证（否则 409）；content 改为可选（至少一项变更），system 节点仅允许源事件操作（内容仍禁改 403）。③ GraphStore 新增 `add_source_ref` / `remove_source_ref`（反向索引同步 + 脏位）。④ Gr 构图提示词：一节点一要点 + 同要点跨事件一律并入已有节点 + 子节点鼓励；Meta 审查新增多要点节点驳回（建议拆子节点）；同源聚合提示词补「聚合时保留子节点结构」。
> 2026-08-29：规约升级至 v1.23。图连通性治理：① **构图边解析修复**：`tool_apply_to_store` 新建边时 source/target 新增「已有节点 title」解析（全图 title 索引兜底）——弱模型用 title 引用已有节点此前被当 node_id 解析失败、**边被静默丢弃**（图连通性退化的主要根因之一）；无法解析的边仍丢弃但必须输出 WARNING 日志留痕。② **维护计划新增 `edge_adds` 通道**（GraphMaintenancePlan.edge_adds，MaintenanceEdgeAdd）：把孤立节点连回图——source/target 须为已有节点 + relation + reason（本地硬规则校验端点存在性与 relation 非空），执行时 evidence_event_id 取 source 节点首条有效源证。③ **候选扫描新增孤立节点类（isolated_nodes）**：无任何边、置信度 ≥ 0.4 且有 ≥1 条有效源证的非 system 节点（低置信孤立方仍走 low_conf_isolated 删除判断）；`^compress` 候选计数与无候选判据同步纳入该类。④ Gr 维护提示词新增补边决策规则（判断不了相关性就不硬连，严禁凭空想象关系）；Meta 审查新增补边规则（关系须被两端内容支撑、不得与已有边矛盾）。
> 2026-08-29：规约升级至 v1.24。^update 两阶段结构优化：① **新指令 `^update [节点ID]`**（语义层，需 AI；与 ^compress 分工——compress 删繁就简，update 优化图结构）：入队 maintain_graph payload mode=update，两阶段一轮封顶不循环。② **Phase 1 减碎+补缺**：候选 = 重合对 + 过碎事件（附事件原文摘录供锚定）+ 僵尸 + 低置信孤立；通道 = merges/deletes/edge_removes/**node_adds**——新增 MaintenanceNodeAdd（title ≤60 + content + node_type 禁 system + event_id 锚定已有事件 + evidence_quote 事件原文连续子串**本地硬校验**（event_content_map 注入式，run_maintenance_local_checks 增可选参数）+ 可选 parent_node_id 挂 subtopic_of 子节点边）；执行建节点 + 源证/反向索引/FTS + 可选挂边。③ **Phase 2 连线**：Phase 1 执行后的新图重新扫描 → isolated_nodes → edge_adds（端点保证幸存）。④ 通道收敛防御：filter_plan_channels 按阶段丢弃越界通道（compress 全通道禁 node_adds；update_reduce/update_connect 白名单）。⑤ Gr 提示词新增 task_mode 约束与 node_adds 决策规则（节点已良好不补，只补确实缺失且原文可锚定的要点）；Meta 审查新增补节点规则（quote 锚定/确实缺失/克制）。⑥ `^update` API 候选预扫描可感知化：无结构候选立即「无需优化」，有候选入队并报各类数量与两阶段说明。
> 2026-08-29：规约升级至 v1.25。待连线对候选（治「Phase 2 无活可干/补边为零」）：用户实测 ^update 后反馈「没有第二轮、完全没有补边」——根因是连线候选只覆盖 degree=0 的孤立节点（真实图中仅 2~3 个），41 个 degree=1 的弱连接节点无候选可依。① 候选扫描新增**第六类 `link_candidates`**：未连边且词重叠 ≥ 0.35 的节点对（任意类型组合、双方非 system；高重合同类型对仍归 merge_candidates 不重复入选；已连边排除）——补边的主力候选面；② `^update` Phase 2 候选 = isolated_nodes + link_candidates，`^compress` 的补边通道同步受益；③ Phase 1 补全过碎事件原文摘录注入（node_adds 锚定上下文，v1.24 规划项落地）；④ `^update`/`^compress` 响应消息与无候选判据纳入待连线对计数；Gr 补边规则扩展为双来源（孤立节点 + 待连线对）。
> 2026-08-29：规约升级至 v1.26。事件关联节点实时派生：用户反馈「处理历史等处的事件关联节点数是旧的、加起来对不上」。根因——事件行上的 `graph_refs` 是构图写入时的一次性快照，此后的节点合并/删除/聚合均不回写行字段（被合并节点 id 残留、归并节点缺失）；多重关联（一节点多源事件，设计行为）会使其出现在多个事件的列表中，跨事件加总 ≠ 总节点数。修复：`GET /events/{event_id}` 读路径改为**实时派生**——以图层反向索引（event_to_nodes，所有图操作同步维护）为准、仅保留有效源证；前端「处理历史」节点数与「图关联」展示随之变准。注意：跨事件加总仍不等于总节点数——手工 system 节点无事件来源、多重关联节点在多个事件下各计一次，均为设计语义。
> 2026-09-05：规约升级至 v1.27。**^cmdmsg 指令消息**：① 新指令 `^cmdmsg <自然语言指令>`（语义层，需 AI）：用户/外部 Agent 给管线发笼统调整意图（如「帮我减少某些记忆」「补充游戏相关记忆」，≤2000 字符，不带节点数据）；入队 `maintain_graph` payload `instruction`。② Gr 读取指令在候选内决定通道与力度（增加/减少/整理三类），node_adds 从 mineable_events 可挖掘事件池锚定；Meta 审「计划是否回应指令」（第 9 条审查规则）；指令只影响决策倾向，不扩大权限（所有底线与保护照常生效）。③ 多轮封顶 `AGENT_CMDMSG_MAX_ROUNDS`（默认 3）：每轮执行后重扫续轮，空计划/被驳回/无可动对象即停。④ 外部调用：`POST /ingest` + `X-API-Key` 即通用入口，无需新端点。
> 2026-09-26：规约升级至 v1.28。**存储修复链（先修易错点）**：① **图层损坏留档**——graph.json 主文件与 .bak 双损坏（或超 64MiB 体量上限）时，损坏原件改名留档 `graph.json.corrupt-<时间戳>` 后以空图启动，不再静默以空图覆盖可恢复原件；写入超 64MiB 上限拒绝。② **节点合并护栏**——merge_into/merge_nodes 的 content 追加封顶 20000 字符、source_refs 并集封顶 500 条（保留最新），防反复合并致节点无限膨胀。③ **events_fts 启动自愈**——启动时以事件表为唯一真源全量重建 FTS（对齐 node_fts 先例），修「insert 与 insert_fts 分离提交中途崩溃 → 事件存在但检索不到」。④ **事件失败原因落库**——events 表增 `error` 列（PRAGMA user_version 1→2，ALTER TABLE 只增列，旧库无感迁移），管线判死写脱敏单行摘要（类型+截断 200 字符），瞬时错误回 indexed 时清空；GET /events 列表与详情透出。⑤ **检索排除 skipped**——search_fts 的 FTS 与 LIKE 降级分支均加 `status != 'skipped'`（用户明确跳过 = 不再召回）。
> 2026-09-26：规约升级至 v1.29。**库与分组 + 联合检索 + Agent 优化**：① **库模型**——一库 = 一 memory.db + 一 graph.json，完全隔离（独立线层/图层/FTS/管线，不跨册建边扩散）；书库 = 文件夹（managed 册落 `<数据根>/repos/<group_key>/<repo_id>/`，展示名不入路径）；登记表 `repos/index.json` 原子写持久化库记录、受管开关与活动库，坏索引保留原件仅以默认库启动。② **legacy 零移动迁移**——首次运行把现行 memory.db/graph.json 登记为外部默认库 `rp_default`（不移动不复制不改名）。③ **+7 库端点**（23→30）：POST/GET/PUT/DELETE /repos、GET /repos/{id}、POST /repos/{id}/activate、POST /repos/{id}/generate（库级联合生成知识）；摘登记不删文件；受管开关即时加载/卸载。④ **库参数**——ingest `repo_id`（缺省活动库）、GET /events 与 /nodes `repo_id` 过滤、/query `repo_ids`（单册 = 指定册；缺省多册 = 联合检索：册间等权 RRF + 去重（事件 content_hash / 节点类型+标题）+ 来源册锚定 repo_id/repo_name/source_repos，纯本地降级可用；结果 SearchResult 增 kind/repo_id/repo_name/source_repos/content_hash 字段）。⑤ **队列与册可见性**——/health 增 queue_depth/worker_running/active_repo_id；补偿逐受管库收集；高水位维护逐册检查。⑥ **Cr 短路**——AGENT_CR_SKIP_CHARS（默认 200）内跳过 Cr 概括，短事件管线 4-5 次 LLM 调用降至 3-4 次。

---

> 2026-10-03：规约升级至 v1.30。**存储保障 + 本地日志 + 联合检索修正 + 库作用域贯穿**：① **图层操作日志 `graph_ops`**（同库追加表，schema v3）——每次落盘把「相对上次落盘的状态差分」写成一批 op（node_upsert / node_delete / edge_upsert / edge_delete，其中 `node_delete` 附带被删节点原数据），带 `reason`（因何改图）；**`graph.json` 丢失或损坏且无可用备份时，从操作日志重放恢复图层**，让「图层是派生 read-model」在故障路径上真正成立。② **`graph.json` 增 `format_version`**：版本高于本程序支持时留档拒读，绝不用旧格式覆盖新数据。③ **多代备份**：`<name>.bak.1..N`（默认 3 代），且**改为覆盖前备份**——旧实现「先写后备份」使 `.bak` 只是当前文件副本，等于没有上一代。④ **备份/校验/审计入口（+6 端点，30→36）**：`POST /maintenance/backup`（`VACUUM INTO` 在线整库副本 + graph.json + manifest）、`GET /maintenance/backups`、`POST /maintenance/verify`（SQLite 完整性/外键 + FTS 行数一致 + **操作日志重放一致性** + 悬空源证 + 缺 data 节点）、`GET /maintenance/ops`、`POST /maintenance/checkpoint`、`POST /repos/{id}/refresh`；恢复仅经本地 CLI（须停服务，且先做安全备份）。⑤ **跨进程单实例锁**：OS 文件锁（Windows `msvcrt` / POSIX `flock`）按库持有、进程退出由内核释放——此前「写者串行」只在单个 asyncio 循环内成立，跨进程整文件改写会「后写者覆盖先写者」。⑥ **回收站**：物理删除前留档到 `<数据根>/trash/{events,nodes}/<id>.json`，`EventStore.restore()` 按**原 id** 重新入库（图节点源证随之重新对上）；不做软删（软删要给 FTS/检索/reconcile/统计等所有读路径加过滤，改动面大且易漏）。⑦ **WAL 治理**：周期检查点（超阈值 TRUNCATE），`/health` 与校验回报 db/wal/json 体积与备份份数。⑧ **本地日志系统**：`backend-YYYY-MM-DD.log` 与 `frontend-YYYY-MM-DD.log` **分文件**按天轮转（保留 14 天，可选 JSONL），配置项 `DPIM_LOG_DIR` / `DPIM_LOG_RETENTION_DAYS` / `DPIM_LOG_JSONL`；写请求统一收口（落盘脏图 + 刷新状态密钥 + 写操作流水），本地 CLI `logs` 翻看；前端日志送入端点随新前端一起加。⑨ **联合检索修正**：每库取**候选池**（`limit × 3`，下限 50）后再融合、**分页只切一次**（原实现把 limit/offset 传给每库、融合后又切一次 → 双重分页使第二页错乱、`total` 失真）；`SearchResponse.trace` 给出每库候选数/耗时与每条结果在各库的排名/原始分/RRF 贡献；`GET /events`、`GET /nodes` 增 `repo_ids` **联合列表**。⑩ **库作用域贯穿**：`/feedback`、`GET /events/{id}`、`GET /nodes/{id}`、`^指令`、`/agent/maintain`、`/agent/compensate` 均接受库参数（此前静默作用于活动库）。⑪ **术语修正**：「不可变日志」→「**时序事件存储**：按时间追加，大模型不可轻易调整，人类可显式修订」——修正的是表述，不是实现。

> 2026-10-03：规约升级至 v1.31。**本地日志接口 + 回收站接口 + 库登记恢复/清除（+6 端点，36→42）**：① **`GET /logs`**（本地日志翻看）：按 `kind`（backend/frontend）/`date`/`level`/`keyword`/`tail` 读尾部，响应含该通道全部日志文件（`files`，日期倒序）、日志目录绝对路径（`dir`）与 `truncated`（过滤后匹配行数超过 tail）；`POST /logs/client` 把浏览器日志按级别送回 `frontend-YYYY-MM-DD.log`（message 超 8000 字符截断）；二者复用链 W 的 `core/logging_setup`（按天轮转、前后端分文件），**两侧都不触发状态密钥刷新**（`GET /logs` 只读；`POST /logs/client` 属日志旁路，在 `write_commit` 里按「路径 + 方法」精确豁免——日志上报不该让状态密钥变成噪声）。② **`GET /trash` + `POST /trash/restore`**：留档清单（含内容摘要 title，按 archived_at 倒序）与恢复入口——事件走 `EventStore.restore()` 按**原 id** 重新入库（FTS 重建，既有图节点源证随之重新对上）；节点恢复本体 + `source_refs` 并**尽力恢复留档边信息**（`DELETE /nodes` 起把关联边随节点一并留档，恢复时仅当两端节点都在图中且该边不存在才补回）；已存在同 id → 409、留档不存在 → 404；**恢复成功后留档移入 `trash/restored/`**（不删原文件，保留恢复痕迹）。③ **`POST /repos/rebuild`**：坏索引恢复——清掉只读锁存、扫描磁盘（受管库根下含 `memory.db`/`graph.json` 的目录，排除 `backups/`、`trash/` 内的副本 + 现役默认库 + 仍存在的外部库根）重建登记表并保存，返回 `{message, repos, latched_before}`，**绝不删任何数据文件**。④ **`POST /repos/{id}/purge`**：先整库备份（`backup_path` 回填）再删 `memory.db`（含 `-wal`/`-shm`/`.lock`）与 `graph.json` 及其 `.bak.*`，最后摘登记；默认库 400 / 活动库 409（中文原因）；外部库只摘登记、不删外部目录文件。⑤ **外部库重指向**：`PUT /repos/{id}` 增可选 `root`（换目录，须含两文件并过禁设清单），受管库传 `root` 直接 400。⑥ **列表项来源库归属**：`EventListItem` / `NodeListItem` 增 `repo_id` / `repo_name`（默认空串），单库查询填该库、联合列表按首命中库填充——联合列出的行此前分不清来自哪个库。

> 2026-10-03：规约升级至 v1.32。**书目收养 + 未加载原因可见 + 维护 mode 修复 + 配置字段契约补齐**：① **`POST /repos/adopt`（+1 端点，42→43）**——补上 external 登记的半损口子：`RepoCreateRequest(root_kind="external")` 强制要求 `memory.db` 与 `graph.json` **同时**存在，于是「graph.json 被误删」「只有一份 memory.db 要接管」这类状态无出路。收养的语义：目录里**至少有一个**库文件才叫收养（一个都没有 400：那是「新建」不是「收养」）；缺 `memory.db` → 建一个**空库并建好当前 schema**（走 `Database` 的建表路径，不手写 SQL）；缺 `graph.json` → 写一份带 `format_version` 的空图层，并**顺带尝试从 `graph_ops` 重放恢复图层**（恢复不了就留空图，绝不报错）；**只补空件、绝不覆盖已存在的文件**；登记为 **external** 书目（不移动文件、不建受管目录）；该目录已登记为某书目 → 409；禁设清单（数据根内外包含 / 符号链接 / 磁盘根 / 用户主目录）照旧生效。响应 `{repo_id, message, created}`。② **`RepoInfo.load_error`**（P6 失败可见）：前端此前只能显示「未加载」却说不出**为什么**。新字段给出未加载原因——**显式加载失败原因优先**（`RepoManager.load_errors`），否则按可下手程度给出：库目录不存在 / 登记文件缺失 / 休眠（未受管）；已加载为空串。**不改变任何加载行为**，只是把已有信息暴露出来；`GET /repos` 与 `GET /repos/{id}` 都带。③ **`POST /agent/maintain` 补 `mode` 请求体（真缺陷修复）**：`MaintainRequest {mode: 'compress'|'update'}`（默认 `update`）——此前该端点**完全不读 body**，payload 恒为 `{}` → orchestrator `payload.get("mode")` 永远为 None →「前端选 update 实际走 compress」，链 Q18 的两阶段结构优化只有 `^update` 指令一条路可达、REST 端到端不可用；body 可省略（缺省 update）以兼容只带 query 的既有调用，非法 mode 422，`repo_id` 仍走 query。④ **配置字段契约补齐**：`health_check_timeout` 此前只存在于 `core/models.py` 与 `routers/settings.py`，`protocol.ts` 的 `SettingsResponse` / `SettingsUpdateRequest` 缺该字段（前端只能本地扩展类型硬接）——本次按 `int` / `int|None` 补齐（§9 配置表早已有 `HEALTH_CHECK_TIMEOUT` 行，无需改）；同时**逐字段核对**了两个接口与 `models.py` 的其余字段（名称/可选性/类型）。

> 2026-10-05：规约升级至 v1.33。**主 provider（BYOK）配置持久化修复 + 掩码绝不落库（真缺陷修复，端点仍 43）**：① **`llm` 段落盘**——`PUT /settings` 提交的 `llm_base_url` / `llm_api_key` / `llm_model_name` / `llm_timeout` / `llm_max_tokens` / `llm_enable_thinking` / `llm_thinking_budget` 此前**只在内存生效**：`save_dpim_config()` 的 payload 只含 `active_provider` / `active_model` / `providers` / `agent` / `storage` / `log_level`，而读取链（`core/config.py`）这七项只读 env、不读文件。后果：用户在前端「运行配置 → 模型与提供商」填完主配置密钥/地址/模型名，界面回「配置已保存并写入 dpim.json」，**重启后 AI 静默退回内置默认**（`http://localhost:11434/v1` + `llama3:8b` + 空密钥）→ 管线全链路不可用，且界面无从看出密钥其实没存。修复：`dpim.json` 增 `llm` 段，读写链与 storage 一致（**env → dpim.json → 内置默认**，env 仍是部署覆盖）；`dpim/dpim.json` 在 `.gitignore` 内，明文密钥不出仓库。② **掩码形状的值绝不落库**——`core/security.py` 新增 `looks_like_mask()`（`xxx****xxxx` 或全掩码 `****`）：`resolve_secret` 遇到掩码形状的值一律保留现值（**现值为空时也不写入**），`resolve_provider_secret` 对**新条目**（重命名/复制 provider 时前端会把别处的掩码原样带过来）丢弃掩码形状的 key。旧实现 `entry["api_key"] = "" if key == mask_secret("") else key` 里 `mask_secret("")` 恒为空串，等于没拦——掩码被当真钥写盘，AI 侧 401 而界面显示「已设置」。端点与请求/响应字段均无变化。

> 2026-10-05：规约升级至 v1.34。**AI 配置归一（可调 BYOK）+ 未配置状态可见（+1 端点，43→44）**：① **删掉主 provider（`primary`）特殊分支与全部身份默认值**——旧实现内置 `LLM_BASE_URL=http://localhost:11434/v1` / `LLM_MODEL_NAME=llama3:8b`，于是**任何未配置的部署都会静默指向一个不存在的本地 llama**，界面看不出「其实没配」。现在：**AI 身份（base_url / api_key / model）只存在于 `providers` 条目里**，一个提供商 = 一条记录；`providers` 只读 env `DPIM_PROVIDERS`（优先）或 `dpim.json` 的 `providers` 段；**仅当 `DPIM_LLM_BASE_URL` 被显式给出且注册表为空**时才合成名为 `default` 的条目（保住纯 env 部署）；`LLM_TIMEOUT` / `LLM_MAX_TOKENS` / `LLM_ENABLE_THINKING` / `LLM_THINKING_BUDGET` 降级为**全局调优默认**（provider 条目未写时兜底，仅 env，不进 `PUT /settings` 请求体）；`active_provider` 解析链 = env → `dpim.json` → 注册表首个，**显式指定但未登记则原样保留该名字并如实报「未登记」**（不静默换一个）；`save_dpim_config()` **不再写 `llm` 段**（payload = `active_provider` / `active_model` / `providers` / `agent` / `storage` / `log_level`）。② **契约收窄**：`SettingsResponse` 删 7 个 `llm_*` 字段，增 `llm_configured: bool` 与 `llm_unavailable_reason: str`（4 种中文原因：没有任何提供商 / 活动提供商未登记 / 未填地址 / 模型列表为空）；`SettingsUpdateRequest` 同步删这 7 个字段；`available_providers` 默认改为空列表。③ **未配置 ≠ 降级**：`AIState` 增 `reason` 与原子 `set_state(available, reason)`；`compensator._check_llm()` 先取 `settings.llm_config_error()`——非空则**置未配置 + 记录原因 + 直接返回，不发起探测、不计失败次数**（未配置不该刷退避、不该发告警）；只有**已配置但连不上**（连续 3 次失败）才 `degraded`（带 `AI 连接失败（连续 N 次）：<detail>`）。④ **`GET /health` 三态**：`status ∈ {ok, unconfigured, degraded}`（**未配置优先判定**，避免未配置被归入 degraded）+ 新字段 `ai_unavailable_reason`。⑤ **`POST /settings/models`（+1 端点）**：联网探测某提供商的可用模型列表（`{provider, base_url, api_key}` → `{models, error, elapsed_ms}`），走该提供商 OpenAI 兼容 `GET /v1/models`；**探测失败不报 4xx/5xx**，错误摘要（`类型: 消息`，截 400 字符）放 `error` 而 `models` 为空；超时 `min(health_check_timeout, 60)` 秒；不改任何配置、不刷新状态校验密钥。前端「运行配置 → 模型与提供商」据此加「拉取模型」按钮 + 模型下拉（新 provider 的模型同轮可选），`TopBar` / 概览 / 信息传入 的 AI 状态改用三态文案（未配置 / 降级 / 就绪，单一文案源 `stores/health.ts`）。⑥ **清理**：`dpim/dpim.json` 的 `llm` 段（历史默认值）与 `providers.localhost.api_key: "****"`（链 Y 掩码落库的历史产物）随本轮删除。

> 2026-10-05：规约升级至 v1.35。**BYOK 前端可调性补完（真缺陷修复，端点仍 44）**：① **提交已移除的 `llm_*` 字段由「静默忽略」改为 422**——v1.34 删掉这 7 个字段后，`SettingsUpdateRequest` 按 Pydantic 默认行为丢弃白名单外字段：旧界面（浏览器缓存的旧包）或旧脚本照旧提交「主配置 地址/密钥/模型」，服务端**一个字段都没改**却回 200，界面显示「配置已保存并写入 dpim.json」——用户看到的现象正是「以前能配、现在怎么都不生效」。现在 `PUT /settings` 先看原始 body，命中任一 `llm_base_url` / `llm_api_key` / `llm_model_name` / `llm_timeout` / `llm_max_tokens` / `llm_enable_thinking` / `llm_thinking_budget` 即 **422**，`detail[].loc` 指向具体字段、`msg` 说明「已改用 `providers`，请强制刷新页面（Ctrl+F5）后到「模型与提供商」保存」——把静默失败变成看得见的错误。② **`providers[*].clear_api_key: true` = 显式清空密钥**（新字段，PUT 专用）：`api_key` 的「空串 / 掩码形状 = 保持现值」幂等语义（v1.13/v1.33）保护了「原样回传掩码不误删密钥」，代价是**已存密钥无法从前端清掉**（只能删 provider 条目重建），而本地 llama.cpp 之类无需密钥的服务恰恰需要清空。现在清空必须单独声明：`clear_api_key` 为真 → 该条目 `api_key` 置空；该标记**解析后立即弹出、绝不入库**，`GET /settings` 也从不下发（响应字段无变化）。③ 前端配套（`SettingsPage.vue`）：提供商弹窗新增「清除该条目的密钥」开关（仅当该条已有密钥时出现，打开后 API Key 输入框置灰）与「保存后设为使用中」开关（**新增提供商时默认开**，少一步下拉、避免「加了但没生效」）；提供商卡片对非使用中的条目加「设为使用中」按钮；拉取模型后卡片直接显示「已拉取 N 个模型，点提交配置后保存」。

> 2026-10-05：规约升级至 v1.36。**前端可配置面补齐 + 来源可见（真缺陷修复，端点仍 44）**：① **6 项「只改内存」修复**——`max_graph_hops` / `rrf_k` / `jaccard_threshold` / `health_check_interval` / `health_check_timeout` / `compensate_batch_size` 经 `PUT /settings` 修改后**只在内存生效**：`save_dpim_config()` 的 payload 不含它们，而读取链（`core/config.py`）这六项只读 env + 内置默认。后果与链 Y 的 `llm_*` 完全同构：界面改完立刻有效、`GET /settings` 也回显新值，**重启即回默认**，用户无从察觉。修复：`core/config.py` 引入统一读取助手 `_pick()`，读取链一律 **env → `dpim.json` 对应段 → 内置默认**；`save_dpim_config()` 按 `agent`（含 `structured_mode`）/ `retrieval` / `health` / `maintenance` / `logs` / `storage` 段落盘。② **可配置面扩到后端真正可调的东西**（+14 字段）：`max_raw_content`、`compensate_check_interval`、`agent_maintain_auto` / `agent_maintain_min_nodes` / `agent_maintain_max_nodes` / `agent_maintain_cooldown`、`agent_cmdmsg_max_rounds`、`agent_cr_skip_chars`、`llm_structured_mode`、`log_retention_days`、`log_jsonl`、`agent_logs_full`、`wal_checkpoint_interval`、`wal_checkpoint_bytes`——全部进 `GET /settings` 与 `PUT /settings`（含值域约束：如 `max_raw_content 1000..10000000`、`wal_checkpoint_bytes 1MiB..1GiB`、`llm_structured_mode ∈ {md_json, json, tools}`）。`GET /settings` 改为**按响应字段名自动从 `settings` 取值**（今后新增配置项忘接线 = 不再可能）。③ **来源可见（穿透）**：响应新增 `config_sources`（每项标 `env:DPIM_X` / `file` / `default`）、`config_file`（配置写到哪个文件）、`log_dir`（日志目录，只读）；`PUT /settings` 对**被环境变量顶掉的项不再写入内存**（否则运行时值与 env 不一致、重启又变回去——正是「点了保存没效果」的来源），并在响应里给 `ignored_by_env: ["rrf_k(DPIM_RRF_K)"]` 与中文 `message`，界面据此明确提示「此项由环境变量锁定」。**有意保留 env-only**：`DPIM_API_KEY`（访问认证密钥，经 API 自我暴露不可接受）、`DPIM_LOG_DIR`（改路径需重开文件句柄）、`DPIM_LLM_TIMEOUT` / `DPIM_LLM_MAX_TOKENS` / `DPIM_LLM_ENABLE_THINKING` / `DPIM_LLM_THINKING_BUDGET`（这四项是 provider 条目的全局兜底，条目已可直接配置）。④ **顺手抓出一个「死旋钮」**：`max_graph_hops` 虽在 `GET/PUT /settings`、界面与 `dpim.json` 里都存在，但**没有任何生产代码读它**——`SearchRequest.max_hops` 写死 `default=2`，于是「图谱最大跳数」配了等于没配。现改为 `default_factory=lambda: settings.max_graph_hops`：不传 `max_hops` 时跟随该配置（显式传入仍然优先），并在 §9 注明生效时机（存储路径 / 日志三项需重启，其余即时）。后端测试 706 → **707**。

> 2026-10-15：规约升级至 v1.37。**边列表端点 `GET /edges` + 图谱页取边收口（+1 端点，44→45）**：① **补上缺失的读端点**——此前 `/edges` 只有 POST / DELETE，**没有列表**，于是信息图谱页只能「`GET /nodes?limit=400` 取节点 → 逐节点 `GET /nodes/{id}` 汇总边」：400 节点 = ⌈400/24⌉ = **17 批请求**，每批把 title / content / metadata / source_refs 全取回来只为摘边；更糟的是每批 `.catch(() => null)`，**任一节点详情失败就静默少一批边**，用户看到的是「图莫名不连通」而没有任何提示。② **`GET /edges` 语义**：query `node_id`（**两侧**命中，出边 + 入边，与 `GET /nodes/{id}` 的 `edges` 同口径）/ `source` / `target` / `relation`；作用域 `repo_id`（缺省活动库，未知库 404）或 `repo_ids=a,b`（联合：逐库取边 → 按 **(source, target)** 去重 → 首命中库归属 `repo_id`/`repo_name`，未知库 422——与 `/nodes` 联合列表同纪律）；`limit` 默认 **200**、**0..5000 显式校验（越界 400）**、`offset` 负数 400；items 为 `EdgeListItem`（`GraphEdge` + 来源库归属），**按 (source, target) 稳定排序**故分页可复现。③ **`GraphStore.list_edges` 增筛选参数** `source` / `target` / `relation`（`node_id` 行为不变），供单库与联合两条路径复用。④ **契约顺带纠错**：§8.2 分页约定此前写「limit 最大 100（适用于 GET /events 和 GET /nodes）」，逐条核实后改为真实口径——`GET /events` 两分支都静默收到 100；`GET /nodes` **仅 `query` 分支**收到 100，**非 query 分支不设上限**（图谱页 `limit=400` 正依赖于此）；`GET /edges` 则显式 0..5000、越界 400。⑤ **前端**：`api/nodes.ts` 增 `listEdges`，`GraphPage` 的取边改为**一次请求**（不再逐节点取详情），边取失败**显式报在页面上**（`error` 常驻条，节点仍照常显示），边数被截断时工具栏显示「已取前 N / 共 M」；且**只把两端都在已加载节点里的边计入「关联」数**（画布本来就只画这种边——图里可能残留指向已不存在节点的悬空边），被滤掉时另点名「另有 N 条边的端点不在已加载节点里，未绘制」。后端测试 707 → **718**；前端 vitest 90 → **94**。

> 2026-10-16：规约升级至 v1.38。**多库自动维护口径归一（纯行为修正，端点仍 45）**：自动图维护共三条路，逐条核实后只有一条是「单库」的——① **补偿**（AI 恢复时重入队积压 raw/indexed 事件）自 v1.29 起逐受管库收集，每条 ingest 带 `repo_id`，**无问题**；② **节点规模高水位**自 v1.29 起逐受管库检查、带 `repo_id` 入队，且每冷却周期至多一册（防积压期雪崩），**无问题**；③ **AI 恢复后的顺带整理**（`Compensator._trigger_compensate`）只入队**一条 `{"auto": True}`**，**不带 `repo_id`**，而 `Orchestrator._resolve_stores` 对缺省 `repo_id` 回退**默认库三件套**——于是这一路**永远只整理默认库**：活动库若不是默认库、以及其余各库，一次都拿不到；而小库（< `AGENT_MAINTAIN_MAX_NODES`）又永远轮不到②那条路，等于**只有默认库能被自动整理**。现改为与②同口径：`Compensator._maintain_targets()` 统一解析候选库（有库管理器 = 逐受管库，登记序稳定；无 = 仅默认库），**逐库各入队一次**并带 `repo_id`；**规模闸门唯一留在 orchestrator**（`payload.auto` 时按该库真实节点数对 `AGENT_MAINTAIN_MIN_NODES` 判断），故小库的消息到点即拦、不产生 LLM 调用。无库管理器（单库部署）时行为与从前一致（一条不带 `repo_id` 的消息）。后端测试 718 → **722**（+4：多库各入队一次 / 单库不带 `repo_id` / 登记表为空回退默认库 / 高水位逐册只触发首个达标库）。

> 2026-10-17：规约升级至 v1.39。**保留策略：`graph_ops` 表与 `trash/` 目录不再只增不减（端点仍 45）**：① **`graph_ops` 走「压实」而不是「截断」**——这张表是「`graph.json` 丢失/损坏且无可用备份时的重放恢复依据」，`POST /maintenance/verify` 也按「重放全部 op == 内存图」判一致性，**直接删老 op 会让重放只能还原后半段**（恢复不完整、体检恒红，久了就没人看体检了）。新增 `GRAPH_OPS_RETENTION`（默认 **5000**，0 = 不压实）：超限时把最老明细压成一批**等价快照 op**（`graph_clear` + 逐节点/逐边 upsert，`reason=retention-compaction`），于是 `replay(压实后) == replay(压实前)`——**恢复能力与体检口径都不变**，代价是老明细不再可审计（这正是保留策略的本意）。表行数下限 = **1 + 节点数 + 边数**（快照本身），故 `keep` 应显著大于图规模；**快照不比被替换的明细小时原样不动**（避免越压越多——纯追加式增长正是这种情况）；压实重写 `op_id`（顺序与内容等价），保留段的 `created_at`/`reason`/`actor` 原样保留；`DELETE`+`INSERT` 同事务（commit 前崩溃整体回滚，不会只剩空表）。② **回收站按年龄清**：新增 `TRASH_RETENTION_DAYS`（默认 **30** 天，**0 = 永不清理**），按**文件 mtime** 清理 `trash/{events,nodes}/` 与 `trash/restored/` 里的 `.json`——留档是已删数据的**最后一份副本**，故默认宽、可关、只动这三个目录（其它文件与目录一律不碰），逐文件 try、单个失败只告警。③ **执行时机**：启动时先跑一轮，此后并入既有存储卫生循环（与 WAL 检查点同一循环），**最多每小时一次**（`_RETENTION_EVERY_SECONDS = 3600`）；失败只记日志，绝不影响服务可用性（`_run_retention_once` 每库独立 try）。④ **契约**：两项进 `GET/PUT /settings`（值域 `0..1000000` / `0..3650`，越界 422）并落盘 `dpim.json` 的 `storage` 段；§7.4 两条机制行与 §9 配置表同步；前端运行配置页新增「保留策略」板块（含来源 chip 与 env 锁定置灰）。后端测试 722 → **734**；前端 vitest **94**（扩测既有页面级用例，不增文件）。

> 2026-10-17：规约升级至 v1.40。**联合节点列表的 `node_type` 口径修正（纯响应值修正，端点仍 45）**：`GET /nodes?repo_ids=a,b` 的响应项此前是 `NodeListItem(node_type=str(data.get("node_type")))`——`data` 来自 `model_dump()`，`node_type` 是 **枚举成员**，而 **Python 3.11+ 的 `str(NodeType.data)` 返回 `"NodeType.data"`**（不是 `"data"`）。于是同一个字段在两条路上口径不同：单库 `GET /nodes` 经 Pydantic 落成 `"data"`，联合列表落成 `"NodeType.data"`。**后果（用户可见）**：WebUI 在「全部书目」作用域下按节点类型筛选（`node_type === 'data'`）**一个都匹配不上**（看起来像"这个库没有数据节点"），类型标签也显示成 `NodeType.data`；`dpim nodes --repos …` 同样打出枚举名。现统一取**值文本**（`getattr(value, "value", None) or str(value)`），与单库路径、与契约 `NodeListItem.node_type: NodeType` 一致。发现路径：链 AD 给 dpimCLI 补维护类端点时做**活体冒烟**（`dpim nodes --repos rp_default,rp-fc53ea…`）打出 `NodeType.data` 才暴露——单测此前只断言了 `node_id` 集合，没有断言类型字段。后端测试 **734**（联合列表用例补断言：`node_type` 必须是值文本——只加断言、不增用例）。

> 2026-10-17：规约升级至 v1.41。**`GET /health` 分层统计键名明确 + 前端契约类型修正（纯类型/口径修正，端点仍 45）**：`layers.event_line` 实际下发 `{total_events, raw, indexed, linked, failed, skipped}`、`layers.knowledge_graph` 下发 `{total_nodes, system, interaction, data}`（后端 = `es.count_by_status()` / `gs.node_counts_by_type()` 直接展开）；但 `protocol.ts` 的 `LayerStats` 一直声明成 `status_raw` / `status_indexed` / `status_linked` / `status_failed` / `status_skipped` / `system_nodes` / `interaction_nodes` / `data_nodes`——**后端从未下发过这些键**。**后果（用户可见）**：概览台「双区统计」里「已入图事件 / 失败事件 / 待处理（raw）/ 已跳过（skipped）」四个指标块**恒显示「—」**（看起来像"这个库没有数据"），而 `vue-tsc` 完全无感——因为**类型在骗人**：它允许错的键、反过来禁止正确的键。发现路径：链 AE 补**概览台页面级单测**（断言「已入图事件 = 10」），用例直接失败 → 顺着断言查回契约类型。修复：类型拆成 `EventLineStats` / `GraphLayerStats`（真实形状，删掉 `LayerStats`），概览台取值改为 `eventLine.linked` / `.failed` / `.raw` / `.skipped`；改完后 `vue-tsc` 会**拒绝** `status_linked` 这类写法（类型与运行时口径一致，同类缺陷不再能蒙混）。前端 vitest 94 → **144**（+50，见链 AE）。

> 2026-10-17：规约升级至 v1.42。**图层一致性：悬空端点不再造空壳节点 + 清空图层可恢复且不留下「已入图」谎报（端点仍 45）**：① **空壳节点（phantom node）根因修复**——`GraphStore.add_edge` 此前直接 `self.graph.add_edge(...)` 交给 NetworkX，而 `nx.add_edge` 遇到未知端点会**自动造出一个无 `data` 的空壳节点**。实测（活动库 `dpim/data/graph.json`）：文件里 **51 个真节点 / 56 条边，15 个端点不在 `nodes` 里**（29 条边一端或两端悬空）→ 加载后内存图 **66** 个节点（`/health` 的 `total_nodes` 报 66），而 `GET /nodes` / `node_fts` / `node_counts_by_type` 都只有 **51**；`verify` 三项 False（`no_dateless_nodes` 15 个、`node_fts_consistency` nodes=66 vs node_fts=51、`ops_replay_matches_graph`）。且这是**自续循环**：`save()` 跳过无 `data` 的节点、却照写它们的边，于是每次加载都把空壳从文件里重新造出来。修复：`add_edge` **拒绝未知端点**（返回 `False` + WARNING 留痕；生产调用方——`POST /edges`、AI 工具、回收站恢复——本就先校验端点，故只拦漏校验路径，如 `Orchestrator._handle_modify_edge` 的队列消息）；`load()` **跳过**端点不在 `nodes` 的边、计数留痕并标记脏位（下次落盘即从文件清除，原件进 `.bak`）；`replay_recover` 的跳过条数同样留痕；`verify` 新增 **`no_dangling_edges_in_file`**（直接读 `graph.json`，把文件级残留如实报出来，而不是「加载时静默吞掉」）。② **`DELETE /graph` 由「不可逆 + 留下谎报」改为「可恢复 + 口径自洽」**——此前只做 `clear_all()` + 重建 `node_fts`：**应用内没有任何恢复路径**（删单个节点都有回收站留档，一次删掉整图反而无处可恢复，只能靠 `graph.json.bak` 轮转，且界面看不到），同时线层 10 条事件仍是 `status=linked`、`graph_refs` 共 133 条全指向已不存在的节点（概览台照旧显示「已入图事件 10」，`verify` 却全绿）。现在：**先留档整图**到 `trash/graphs/graph-<时间戳>.json`（`data = {nodes, edges}`，`stats` 记计数），恢复走**既有** `POST /trash/restore`（`TrashRestoreRequest.kind` 增 `graph`；**合并式**恢复：已存在的节点/边跳过、不覆盖、不报 409，清空后恢复即完整回填），`GET /trash` 清单出现第三类 `kind=graph`（`title` 显示「整图留档：N 节点 / M 边」），回收站页显示并支持恢复；**同时撤销线层派生链接**（`EventStore.unlink_graph_refs()`：清 `graph_refs` + `linked → indexed`）——否则 `linked` 不在补偿的 raw/indexed 队列里，**图永远长不回来**；`linked → indexed` 因此进入 `ALLOWED_EVENT_TRANSITIONS`（撤销入图，与 `PUT /events/{id}/status` 的 indexed 重试入队分支同语义）。响应 `{archived, archive_id, cleared_nodes, cleared_edges, unlinked_events, relinked_events}`；**留档失败仍照常清空，但 message 明说「留档失败，此操作不可恢复」**。③ **`graph_ops` 的 `edge_delete` 携带被删边原数据**（与 `node_delete` 携带 `node` 对称）——整图清空后这是边细节（relation / evidence_event_id）的唯一来源，此前只留 `{source, target}`，审计与人工抢救都拿不到关系语义。

> 2026-10-17：规约升级至 v1.43。**接口格式：模型配置可选四套主流协议（端点仍 45）**：① **provider 条目增 `format` / `api_path` / `extra_headers`**——`format` 缺省 `openai`，老条目零迁移；`api_path` 仅 `custom` 有意义；`extra_headers` 各格式通用（透传给 openai SDK 的 `default_headers` 或 httpx 请求头）。② **网关按格式分派**（`core/llm.py` + 新模块 `core/llm_formats.py`）：`openai` / `responses` 走 instructor（`responses` 固定 `Mode.RESPONSES_TOOLS`，并把 `max_tokens` 翻译成 `max_output_tokens`；该格式不套用 `enable_thinking`/`thinking_budget`——Responses 里对应 `reasoning.effort`，语义不同，硬塞会 400，需要时写进 `extra_body`）；`anthropic` / `custom` 走 httpx 适配（`x-api-key` + `anthropic-version` + `max_tokens` 兜底 + JSON 校验回喂重问 / 自定路径 + Bearer + 额外头）。③ **探测按格式分流**：`POST /settings/models` 增 `format`，anthropic 用同一套头打 `{base}/models`，其余用 Bearer。④ **失败可见**：httpx 适配的 HTTP 错误带状态码与响应片段抛出；`is_transient_error` 增 `httpx.HTTPStatusError` 分支（5xx / 429 / 408 可重试，4xx 不可自愈）。⑤ **测试**：新增 `test_llm_formats.py` 用**本地真 HTTP 服务器**收原始请求，钉死三套协议的路径 / 鉴权头 / body 字段名（含坏 JSON 回喂重问、思考字段与 temperature 的互斥、错误分类）；`test_security` 的探测用例改为验证「路由把格式传下去了」。

> 2026-10-17：规约升级至 v1.44。**Anthropic 的 `max_tokens` 与思考预算不再互相打架（纯请求体修正，端点仍 45、字段无增删）**：① **修掉一个必 400 的组合**——Anthropic 硬性要求 `max_tokens` **严格大于** `thinking.budget_tokens`，而 v1.43 的实现是「`max_tokens` 取条目值 → 全局 `DPIM_LLM_MAX_TOKENS` → 兜底 4096」**先定死**、再据此算 `thinking`，于是 `thinking_budget=8192` 而 `max_tokens` 未填时，发出去的是 `max_tokens=4096 < budget_tokens=8192` → 请求**必定 400**；即便预算较小，**思考 token 也计入 `max_tokens`**，余量不足会在思考结束前被 `stop_reason=max_tokens` 截断（半截 JSON → 校验必失败，白烧一次调用）。现在改为两步：先按「条目 → 全局 → 兜底 **4096**」定上限，算出 `thinking` 后若发现 `max_tokens <= budget_tokens`，就**抬到「预算 + 1024」**并 WARNING 留痕（日志页可见，不静默）。**为什么兜底仍是 4096**：它等于各家 Claude 模型输出上限里的**最小值**（Claude 3 Haiku / Opus = 4096，3.5 Sonnet = 8192，3.7 / 4 系列 = 64000），取它保证换任何模型都不会因「超过模型输出上限」被 400；而它只是**上限**（cap）不是目标长度——按实际输出计费，填大不会更贵、填小才会截断，要更长输出在界面「输出上限 tokens」里填即可（**不要求逐模型配置**）。② **思考开关的优先级修正**：`enable_thinking=False`（显式关）现在**压过**残留的 `thinking_budget`——旧顺序（预算优先）会让一个残留预算值**无声推翻「关掉思考」**（用户以为关了、实际开着，还连带丢掉 `temperature`、白烧 token）；现顺序为「显式关 > 显式预算 > 显式开 > 三态都不设（不发 `thinking` 字段）」。③ **界面把「实际会发出去多少」说出来**：提供商弹窗的「输出上限」提示按格式改写（Anthropic 写明必填 + 兜底 4096 + 「上限不是目标长度」+ 思考余量规则，其余格式写明「留空 = 不传，服务端决定」），卡片摘要由「默认」改为**实际生效值**（如 `默认（4096）` / `2048（思考预算更大，实际按 5120）`），思考开关与思考预算两行也标注了优先级与计入关系。④ **测试**：`test_llm_formats.py` +3（预算大过兜底时抬升 / 显式上限小于预算时抬升 / 显式关压过残留预算），前端 `SettingsPage.test.ts` +3（提示按格式说清 / 卡片显示实际兜底值 / 卡片点名抬升后的值）；后端 **767 → 770**，前端 vitest **159 → 162**。

> 2026-10-17：规约升级至 v1.45。**AI 可用性判定与 BYOK 界面三处真缺陷（端点仍 45）**：① **健康检查按格式分流**——`Compensator._check_llm` 旧实现 `client.models.list()`（OpenAI SDK，Bearer），对 `format=anthropic` 的 provider 打 `{base}/models` 必被 401（真 Anthropic / OpenCode Zen 的 Anthropic 面要 `x-api-key`），于是 AI 恒判「连不上」，**降级/补偿/自动维护永不启动**；现改用 `probe_models(settings.provider_config())`（与探测端点同一套分流逻辑），三连败判降级与失败计数口径不变。**发现路径**：本轮端到端实测时桩服务器日志打出 `GET /v1/models  authorization: Bearer …` 而 `x-api-key: null`——`format=anthropic` 却发了 Bearer。② **`ProviderModelsRequest` 增 `api_path` / `extra_headers`**（两者与既有的 `base_url`/`api_key`/`format` 一样：**请求体优先 → 已登记条目**）：修掉「卡片拉取模型只发名字」导致的两类失败——未保存条目报 `未填模型地址（base_url）`、自定义格式条目缺额外请求头而 401。③ **前端不再把明文密钥放进草稿**（`maskLocal` + 待提交暂存）：草稿被卡片与弹窗占位符直接渲染，旧实现因此**在界面上显示明文密钥**，与同一行的「界面不回显明文」提示直接矛盾。测试：后端 `test_compensation` +2（探测拿到的是含 format 的完整 provider 配置 / 分流后三连败仍判降级且原因带原文）、`test_security` 探测用例扩测（body 的 api_path/extra_headers 生效）；前端 `SettingsPage.test.ts` 扩测（草稿存掩码、卡片不出现明文、提交下发真值、卡片拉取带草稿值）。

> 2026-10-17：规约升级至 v1.46。**系统性审计后的第一批修正（端点仍 45）**：① **错误原文不得回显密钥**（httpx/h11 会把整条头值写进异常，实测 `LocalProtocolError: Illegal header value b'sk-abc\nSECRETTAIL'`）→ 请求头值 `sanitize_secret()` + 异常原文 `scrub_secrets()`（探测端点 / 健康检查 WARNING / 降级原因三处，且擦除要覆盖转义形态）。② **`reconcile_changed` 恒 0 修复**：`refresh_repo()` 的键是 `changed`，模型要 `reconcile_changed`，Pydantic `extra='ignore'` 静默丢真值 → router 补映射 + 文案。③ 类型修正：`ClearGraphResponse` 补齐 v1.42 的 7 字段、`LLMCallLog.input`。**审计来源**：5 路并行审计（密钥外泄 / 草稿错位 / 静默失败 / 契约一致性 / 边界细节）共 52 条，前端那部分同轮修复，余下条目登记在 AGENTS §十。

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
