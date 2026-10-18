<template>
  <PageShell zone="维护" title="运行配置" description="配置环境变量与运行参数">
    <!-- 本页唯一主操作：提交配置（P4） -->
    <template #actions>
      <n-button
        type="primary"
        size="small"
        :loading="submitting"
        :disabled="loading || !!loadError"
        @click="submit"
      >
        提交配置
      </n-button>
    </template>

    <!-- 三态之一：加载 -->
    <StateBlock v-if="loading" loading loading-text="正在读取配置…" fixed-height />

    <!-- 三态之二：读取失败（后端原文 + 重试） -->
    <StateBlock v-else-if="loadError" :error="loadError" fixed-height>
      <template #retry>
        <n-button size="small" @click="load">重试</n-button>
      </template>
    </StateBlock>

    <template v-else>
      <!-- 三态之三：提交结果（常驻可见，含「哪些字段需重启」） -->
      <div v-if="submitError || savedHint" class="banner" :class="submitError ? 'banner--bad' : 'banner--ok'">
        <p class="banner-title">{{ submitError ? '提交失败（后端原文如下，已保留你的编辑）' : '提交结果' }}</p>
        <p v-if="submitError" class="banner-text">{{ submitError }}</p>
        <p v-else class="banner-text">{{ savedHint }}</p>
        <p v-if="ignoredByEnv.length" class="banner-locked">
          以下项由环境变量锁定，本次未生效：<span v-for="x in ignoredByEnv" :key="x" class="ftag">{{ x }}</span>
        </p>
        <p class="banner-note">{{ RESTART_NOTE }}</p>
        <p v-if="failedFields.length" class="banner-fields">
          涉及字段：<span v-for="f in failedFields" :key="f" class="ftag">{{ f }}</span>
        </p>
      </div>

      <div class="settings-scroll">
        <!-- 0. 配置来源（只读）：后端读写哪个文件、日志落哪个目录 -->
        <SectionCard
          title="配置来源"
          hint="后端实际读写的文件与目录（只读）；字段旁的标签标出该项取值来自环境变量 / dpim.json / 内置默认"
        >
          <div class="src-row">
            <span class="src-key">配置文件</span>
            <span class="src-val mono">{{ original?.config_file || '（后端未上报）' }}</span>
          </div>
          <div class="src-row">
            <span class="src-key">日志目录</span>
            <span class="src-val mono">{{ original?.log_dir || '（后端未上报）' }}</span>
          </div>
          <p class="note">
            改动会写进上面的配置文件（<span class="mono">dpim.json</span>），重启后仍在；标「由环境变量 … 决定」的项
            被环境变量顶掉，界面改不动——保存时后端也会点名这些项，见页面顶部「提交结果」。
          </p>
        </SectionCard>

        <!-- 1. 后端地址（浏览器本地，不经后端 API） -->
        <SectionCard
          title="后端地址与访问密钥"
          hint="只存浏览器 localStorage，不随「提交配置」发往后端"
        >
          <FieldRow label="后端地址" hint="默认空 = 走同源 vite 代理（开发服务器把请求转发到后端）">
            <n-input v-model:value="form.backend_url" size="small" placeholder="http://localhost:8000（留空 = 同源代理）" />
          </FieldRow>
          <FieldRow
            label="访问密钥"
            hint="DPIM_API_KEY 非空时全端点要求 X-API-Key；留空 = 保持现值，界面不回显明文"
          >
            <n-input
              v-model:value="form.api_key"
              type="password"
              show-password-on="click"
              size="small"
              :placeholder="hasApiKey ? '已设置（留空保持不变）' : '未设置（后端 DPIM_API_KEY 为空时不启用认证）'"
            />
          </FieldRow>
          <!-- 访问密钥只活在本机 localStorage（明文、永不过期）→ 撤销必须有一个正经出口，
               不能让用户去 devtools 里手删 -->
          <FieldRow
            label="已保存的访问密钥"
            hint="存在本机浏览器 localStorage（dpim_api_key），不随后端提交；清除后本机请求不再携带 X-API-Key"
          >
            <span class="note">{{ hasApiKey ? '本机已保存（明文不回显）' : '本机未保存' }}</span>
            <n-button size="tiny" type="error" ghost :disabled="!hasApiKey" @click="askClearApiKey">
              清除已保存的访问密钥
            </n-button>
          </FieldRow>
          <p class="note">{{ localNote || '这两项改动在浏览器本地即时生效，下一次请求即用新值。' }}</p>
        </SectionCard>

        <!-- 2. 模型与提供商（v1.34：注册表是 AI 配置的唯一入口，不再有「主配置」） -->
        <SectionCard
          title="模型与提供商"
          hint="BYOK 注册表：一条记录 = 一个提供商（地址 / 密钥 / 模型列表）；密钥一律掩码下发（前3****后4），留空 = 保持现值"
        >
          <StateBlock
            v-if="providerNames.length === 0"
            empty-text="尚未配置任何 AI 提供商"
            hint="不配置也能用：存储、检索与确定层指令照常。需要 AI 时点下方「新增提供商」，填地址与密钥后点「拉取模型列表」。"
            fixed-height
          />
          <template v-else>
            <FieldRow label="使用中的提供商" hint="active_provider：全站 AI 调用用哪一条记录">
              <n-select
                v-model:value="form.active_provider"
                size="small"
                class="f-select"
                :options="providerOptions"
                :disabled="locked('active_provider')"
              />
              <ConfigSourceTag :source="sourceOf('active_provider')" />
              <FieldError :msg="fieldErrors.active_provider" />
            </FieldRow>
            <FieldRow label="使用中的模型" hint="active_model：空 = 取该提供商模型列表首个">
              <n-select
                v-model:value="form.active_model"
                size="small"
                class="f-select"
                clearable
                :options="activeModelOptions"
                :placeholder="activeModelOptions.length ? '选择模型' : '该提供商还没有模型（先拉取或手工登记）'"
                :disabled="locked('active_model')"
              />
              <ConfigSourceTag :source="sourceOf('active_model')" />
              <FieldError :msg="fieldErrors.active_model" />
            </FieldRow>
          </template>

          <!-- 提供商卡片化 -->
          <div class="prov-block">
            <Toolbar>
              <span class="prov-hint">BYOK 注册表 · 每个提供商一张卡片 · 密钥掩码显示，编辑留空即保持不变</span>
              <ConfigSourceTag :source="sourceOf('providers')" />
              <template #right>
                <n-button size="tiny" type="primary" ghost @click="openAdd">新增提供商</n-button>
              </template>
            </Toolbar>
            <StateBlock
              v-if="providerNames.length === 0"
              empty-text="暂无注册的提供商"
              hint="点「新增提供商」填写地址与密钥；不配置时系统以无 AI 模式运行（存储与检索照常）。"
              fixed-height
            />
            <div v-for="name in providerNames" :key="name" class="prov-card">
              <div class="prov-main">
                <div class="prov-name">
                  <span class="prov-name-text">{{ name }}</span>
                  <span v-if="name === form.active_provider" class="chip chip--primary">使用中</span>
                  <span class="chip">{{ FORMAT_LABEL[providersDraft[name].format || 'openai'] || 'OpenAI 兼容' }}</span>
                </div>
                <div class="prov-meta mono">{{ providersDraft[name].base_url || '（未设置 base_url）' }}</div>
                <div v-if="providersDraft[name].format === 'custom'" class="prov-meta mono">
                  路径 {{ providersDraft[name].api_path || '/chat/completions' }}
                </div>
                <div class="prov-meta">
                  密钥 {{ providersDraft[name].api_key || '（未设置）' }} · {{ modelsOf(providersDraft[name]).length }} 个模型
                </div>
                <div class="prov-meta">
                  超时 {{ providersDraft[name].timeout ?? '默认' }} · 输出上限 {{ maxTokensText(providersDraft[name]) }} ·
                  思考 {{ thinkingText(providersDraft[name]) }} · 思考风格 {{ providersDraft[name].thinking_style || '默认' }} ·
                  结构化 {{ providersDraft[name].structured_mode || '默认' }}
                </div>
                <!-- 卡片只报**键名与项数**：整段 JSON 会把塞进 extra_body 的密钥摊在页面上，
                     打开本页无需任何点击就能看到明文（后端不掩 extra_body）。要编辑点「编辑」进弹窗。 -->
                <div v-if="extraBodyKeys(providersDraft[name]).length" class="prov-meta">
                  厂商参数 {{ extraBodyKeys(providersDraft[name]).length }} 项：{{
                    extraBodyKeys(providersDraft[name]).join('、')
                  }}
                </div>
                <div v-if="probeNoteOf(name)" class="prov-meta prov-probe">{{ probeNoteOf(name) }}</div>
              </div>
              <div class="prov-actions">
                <n-button size="tiny" :loading="probing === name" @click="pullModels(name)">拉取模型</n-button>
                <n-button v-if="name !== form.active_provider" size="tiny" @click="setActive(name)">
                  设为使用中
                </n-button>
                <n-button size="tiny" @click="openEdit(name)">编辑</n-button>
                <n-button size="tiny" type="error" ghost @click="askRemove(name)">删除</n-button>
              </div>
            </div>
            <FieldError :msg="fieldErrors.providers" />
          </div>
        </SectionCard>

        <!-- 3. Agent 管线 -->
        <SectionCard title="Agent 管线" hint="方案A 硬编码编排：Cr 收集 → In 录入 → Gr 构图 → Meta 审查">
          <FieldRow label="管线模式" hint="disabled = 只存储不构图；pipeline = 四 Agent 管线">
            <n-select
              v-model:value="form.agent_mode"
              size="small"
              class="f-select"
              :options="AGENT_MODE_OPTIONS"
              :disabled="locked('agent_mode')"
            />
            <ConfigSourceTag :source="sourceOf('agent_mode')" />
            <FieldError :msg="fieldErrors.agent_mode" />
          </FieldRow>
          <FieldRow
            label="结构化输出模式"
            hint="llm_structured_mode：非角色 LLM 默认（provider 条目可单独覆盖）；md_json 兼容 llama.cpp"
          >
            <n-select
              v-model:value="form.llm_structured_mode"
              size="small"
              class="f-select"
              :options="STRUCTURED_MODE_OPTIONS"
              :disabled="locked('llm_structured_mode')"
            />
            <ConfigSourceTag :source="sourceOf('llm_structured_mode')" />
            <FieldError :msg="fieldErrors.llm_structured_mode" />
          </FieldRow>
          <FieldRow label="Meta 最大修正轮次" hint="值域 0–10">
            <n-input-number
              v-model:value="form.agent_max_retries"
              size="small"
              class="f-number"
              :min="0"
              :max="10"
              :disabled="locked('agent_max_retries')"
            />
            <ConfigSourceTag :source="sourceOf('agent_max_retries')" />
            <FieldError :msg="fieldErrors.agent_max_retries" />
          </FieldRow>
          <FieldRow label="Cr 模型" hint="收集角色；空 = 跟随使用模型">
            <n-select
              v-model:value="form.agent_cr_model"
              size="small"
              class="f-select"
              :options="roleModelOptions(form.agent_cr_model)"
              :disabled="locked('agent_cr_model')"
            />
            <ConfigSourceTag :source="sourceOf('agent_cr_model')" />
            <FieldError :msg="fieldErrors.agent_cr_model" />
          </FieldRow>
          <FieldRow label="In 模型" hint="录入角色；空 = 跟随使用模型">
            <n-select
              v-model:value="form.agent_in_model"
              size="small"
              class="f-select"
              :options="roleModelOptions(form.agent_in_model)"
              :disabled="locked('agent_in_model')"
            />
            <ConfigSourceTag :source="sourceOf('agent_in_model')" />
            <FieldError :msg="fieldErrors.agent_in_model" />
          </FieldRow>
          <FieldRow label="Gr 模型" hint="构图角色；空 = 跟随使用模型">
            <n-select
              v-model:value="form.agent_gr_model"
              size="small"
              class="f-select"
              :options="roleModelOptions(form.agent_gr_model)"
              :disabled="locked('agent_gr_model')"
            />
            <ConfigSourceTag :source="sourceOf('agent_gr_model')" />
            <FieldError :msg="fieldErrors.agent_gr_model" />
          </FieldRow>
          <FieldRow label="Meta 模型" hint="审查角色；空 = 跟随使用模型">
            <n-select
              v-model:value="form.agent_meta_model"
              size="small"
              class="f-select"
              :options="roleModelOptions(form.agent_meta_model)"
              :disabled="locked('agent_meta_model')"
            />
            <ConfigSourceTag :source="sourceOf('agent_meta_model')" />
            <FieldError :msg="fieldErrors.agent_meta_model" />
          </FieldRow>
        </SectionCard>

        <!-- 4. 检索与护栏 -->
        <SectionCard title="检索与护栏" hint="综合检索的融合 / 图扩散口径，以及送进 LLM 的上下文上限">
          <FieldRow label="图谱最大跳数" hint="max_graph_hops：值域 1–5">
            <n-input-number
              v-model:value="form.max_graph_hops"
              size="small"
              class="f-number"
              :min="1"
              :max="5"
              :disabled="locked('max_graph_hops')"
            />
            <ConfigSourceTag :source="sourceOf('max_graph_hops')" />
            <FieldError :msg="fieldErrors.max_graph_hops" />
          </FieldRow>
          <FieldRow label="RRF 参数 K" hint="rrf_k：值域 1–200">
            <n-input-number
              v-model:value="form.rrf_k"
              size="small"
              class="f-number"
              :min="1"
              :max="200"
              :disabled="locked('rrf_k')"
            />
            <ConfigSourceTag :source="sourceOf('rrf_k')" />
            <FieldError :msg="fieldErrors.rrf_k" />
          </FieldRow>
          <FieldRow label="杰卡德阈值" hint="jaccard_threshold：值域 0–1，用于同类型节点去重预检">
            <n-input-number
              v-model:value="form.jaccard_threshold"
              size="small"
              class="f-number"
              :min="0"
              :max="1"
              :step="0.05"
              :precision="2"
              :disabled="locked('jaccard_threshold')"
            />
            <ConfigSourceTag :source="sourceOf('jaccard_threshold')" />
            <FieldError :msg="fieldErrors.jaccard_threshold" />
          </FieldRow>
          <FieldRow
            label="单次输入字符上限"
            hint="max_raw_content：上下文护栏，超限截断；值域 1000–10000000（默认 200000）"
          >
            <n-input-number
              v-model:value="form.max_raw_content"
              size="small"
              class="f-number"
              :min="1000"
              :max="10000000"
              :step="10000"
              :disabled="locked('max_raw_content')"
            />
            <ConfigSourceTag :source="sourceOf('max_raw_content')" />
            <FieldError :msg="fieldErrors.max_raw_content" />
          </FieldRow>
        </SectionCard>

        <!-- 5. 健康检查与补偿 -->
        <SectionCard title="健康检查与补偿" hint="AI 断连自动降级、恢复自动补偿的节律">
          <FieldRow label="健康检查间隔（秒）" hint="health_check_interval：值域 10–86400">
            <n-input-number
              v-model:value="form.health_check_interval"
              size="small"
              class="f-number"
              :min="10"
              :max="86400"
              :disabled="locked('health_check_interval')"
            />
            <ConfigSourceTag :source="sourceOf('health_check_interval')" />
            <FieldError :msg="fieldErrors.health_check_interval" />
          </FieldRow>
          <FieldRow label="健康检查超时（秒）" hint="与生成超时分离；值域 10–3600">
            <n-input-number
              v-model:value="form.health_check_timeout"
              size="small"
              class="f-number"
              :min="10"
              :max="3600"
              :disabled="locked('health_check_timeout')"
            />
            <ConfigSourceTag :source="sourceOf('health_check_timeout')" />
            <FieldError :msg="fieldErrors.health_check_timeout" />
          </FieldRow>
          <FieldRow label="补偿批处理大小" hint="compensate_batch_size：值域 5–100">
            <n-input-number
              v-model:value="form.compensate_batch_size"
              size="small"
              class="f-number"
              :min="5"
              :max="100"
              :disabled="locked('compensate_batch_size')"
            />
            <ConfigSourceTag :source="sourceOf('compensate_batch_size')" />
            <FieldError :msg="fieldErrors.compensate_batch_size" />
          </FieldRow>
          <FieldRow
            label="补偿结果检查间隔（秒）"
            hint="compensate_check_interval：值域 1–3600（独立于健康周期，失败批次快速进入退避）"
          >
            <n-input-number
              v-model:value="form.compensate_check_interval"
              size="small"
              class="f-number"
              :min="1"
              :max="3600"
              :disabled="locked('compensate_check_interval')"
            />
            <ConfigSourceTag :source="sourceOf('compensate_check_interval')" />
            <FieldError :msg="fieldErrors.compensate_check_interval" />
          </FieldRow>
        </SectionCard>

        <!-- 6. 图维护自动化 -->
        <SectionCard
          title="图维护自动化"
          hint="AI 恢复时自动整理图谱（衍生知识，不动原文）与 ^cmdmsg 指令的轮次口径"
        >
          <FieldRow
            label="自动维护开关"
            hint="agent_maintain_auto：AI 恢复触发补偿时顺带整理图谱（手动「触发维护」不受此开关限制）"
          >
            <n-switch
              v-model:value="form.agent_maintain_auto"
              size="small"
              :disabled="locked('agent_maintain_auto')"
            />
            <ConfigSourceTag :source="sourceOf('agent_maintain_auto')" />
            <FieldError :msg="fieldErrors.agent_maintain_auto" />
          </FieldRow>
          <FieldRow
            label="自动维护最小节点数"
            hint="agent_maintain_min_nodes：小图跳过自动维护；值域 1–100000（默认 10）"
          >
            <n-input-number
              v-model:value="form.agent_maintain_min_nodes"
              size="small"
              class="f-number"
              :min="1"
              :max="100000"
              :disabled="locked('agent_maintain_min_nodes')"
            />
            <ConfigSourceTag :source="sourceOf('agent_maintain_min_nodes')" />
            <FieldError :msg="fieldErrors.agent_maintain_min_nodes" />
          </FieldRow>
          <FieldRow
            label="节点规模高水位"
            hint="agent_maintain_max_nodes：达到后每个冷却周期自动入队维护；值域 1–1000000（默认 200）"
          >
            <n-input-number
              v-model:value="form.agent_maintain_max_nodes"
              size="small"
              class="f-number"
              :min="1"
              :max="1000000"
              :step="10"
              :disabled="locked('agent_maintain_max_nodes')"
            />
            <ConfigSourceTag :source="sourceOf('agent_maintain_max_nodes')" />
            <FieldError :msg="fieldErrors.agent_maintain_max_nodes" />
          </FieldRow>
          <FieldRow
            label="高水位冷却（秒）"
            hint="agent_maintain_cooldown：值域 10–86400（默认 60）"
          >
            <n-input-number
              v-model:value="form.agent_maintain_cooldown"
              size="small"
              class="f-number"
              :min="10"
              :max="86400"
              :disabled="locked('agent_maintain_cooldown')"
            />
            <ConfigSourceTag :source="sourceOf('agent_maintain_cooldown')" />
            <FieldError :msg="fieldErrors.agent_maintain_cooldown" />
          </FieldRow>
          <FieldRow
            label="指令消息轮次封顶"
            hint="agent_cmdmsg_max_rounds：^cmdmsg 多轮上限，防无限循环；值域 1–10（默认 3）"
          >
            <n-input-number
              v-model:value="form.agent_cmdmsg_max_rounds"
              size="small"
              class="f-number"
              :min="1"
              :max="10"
              :disabled="locked('agent_cmdmsg_max_rounds')"
            />
            <ConfigSourceTag :source="sourceOf('agent_cmdmsg_max_rounds')" />
            <FieldError :msg="fieldErrors.agent_cmdmsg_max_rounds" />
          </FieldRow>
          <FieldRow
            label="Cr 短路阈值（字符）"
            hint="agent_cr_skip_chars：原文不超过该值时跳过 Cr 概括；0 = 关闭短路；值域 0–100000（默认 200）"
          >
            <n-input-number
              v-model:value="form.agent_cr_skip_chars"
              size="small"
              class="f-number"
              :min="0"
              :max="100000"
              :disabled="locked('agent_cr_skip_chars')"
            />
            <ConfigSourceTag :source="sourceOf('agent_cr_skip_chars')" />
            <FieldError :msg="fieldErrors.agent_cr_skip_chars" />
          </FieldRow>
        </SectionCard>

        <!-- 7. 本地日志与 WAL -->
        <SectionCard
          title="本地日志与 WAL"
          hint="本地日志按天轮转（backend-*.log / frontend-*.log）与 SQLite WAL 检查点阈值"
        >
          <FieldRow
            label="日志保留天数"
            hint="log_retention_days：0 = 不清理；值域 0–3650（默认 14）。重启后端后生效"
          >
            <n-input-number
              v-model:value="form.log_retention_days"
              size="small"
              class="f-number"
              :min="0"
              :max="3650"
              :disabled="locked('log_retention_days')"
            />
            <ConfigSourceTag :source="sourceOf('log_retention_days')" />
            <FieldError :msg="fieldErrors.log_retention_days" />
          </FieldRow>
          <FieldRow label="额外输出 JSONL" hint="log_jsonl：程序读用；人读用默认文本格式。重启后端后生效">
            <n-switch v-model:value="form.log_jsonl" size="small" :disabled="locked('log_jsonl')" />
            <ConfigSourceTag :source="sourceOf('log_jsonl')" />
            <FieldError :msg="fieldErrors.log_jsonl" />
          </FieldRow>
          <FieldRow
            label="AI 调用日志取全文"
            hint="agent_logs_full：false 时「AI 调用日志」忽略「取全文」（日志含事件原文，可防泄露）"
          >
            <n-switch
              v-model:value="form.agent_logs_full"
              size="small"
              :disabled="locked('agent_logs_full')"
            />
            <ConfigSourceTag :source="sourceOf('agent_logs_full')" />
            <FieldError :msg="fieldErrors.agent_logs_full" />
          </FieldRow>
          <FieldRow
            label="WAL 检查点周期（秒）"
            hint="wal_checkpoint_interval：值域 10–86400（默认 300）"
          >
            <n-input-number
              v-model:value="form.wal_checkpoint_interval"
              size="small"
              class="f-number"
              :min="10"
              :max="86400"
              :disabled="locked('wal_checkpoint_interval')"
            />
            <ConfigSourceTag :source="sourceOf('wal_checkpoint_interval')" />
            <FieldError :msg="fieldErrors.wal_checkpoint_interval" />
          </FieldRow>
          <FieldRow
            label="WAL 触发体积（字节）"
            hint="wal_checkpoint_bytes：WAL 超过该体积才做检查点；值域 1048576–1073741824（默认 8388608 = 8 MiB）"
          >
            <n-input-number
              v-model:value="form.wal_checkpoint_bytes"
              size="small"
              class="f-number"
              :min="1048576"
              :max="1073741824"
              :step="1048576"
              :disabled="locked('wal_checkpoint_bytes')"
            />
            <ConfigSourceTag :source="sourceOf('wal_checkpoint_bytes')" />
            <FieldError :msg="fieldErrors.wal_checkpoint_bytes" />
          </FieldRow>
        </SectionCard>

        <!-- 8. 保留策略（v1.39） -->
        <SectionCard
          title="保留策略"
          hint="让「图层操作日志」表与回收站目录不再只增不减；改完在下一次存储卫生轮次生效（最多 1 小时）"
        >
          <FieldRow
            label="图层操作日志保留条数"
            hint="graph_ops_retention：超限把最老明细压成等价快照（重放/恢复能力不变，老明细不再可审计）；0 = 不压实；值域 0–1000000（默认 5000）"
          >
            <n-input-number
              v-model:value="form.graph_ops_retention"
              size="small"
              class="f-number"
              :min="0"
              :max="1000000"
              :disabled="locked('graph_ops_retention')"
            />
            <ConfigSourceTag :source="sourceOf('graph_ops_retention')" />
            <FieldError :msg="fieldErrors.graph_ops_retention" />
          </FieldRow>
          <FieldRow
            label="回收站留档保留天数"
            hint="trash_retention_days：按文件时间清理过期留档（含 restored/ 痕迹）——留档是已删数据的最后一份副本，0 = 永不清理；值域 0–3650（默认 30）"
          >
            <n-input-number
              v-model:value="form.trash_retention_days"
              size="small"
              class="f-number"
              :min="0"
              :max="3650"
              :disabled="locked('trash_retention_days')"
            />
            <ConfigSourceTag :source="sourceOf('trash_retention_days')" />
            <FieldError :msg="fieldErrors.trash_retention_days" />
          </FieldRow>
        </SectionCard>

        <!-- 9. 存储路径与日志级别 -->
        <SectionCard
          title="存储路径与日志级别"
          hint="写入 dpim.json 后需重启后端才生效（数据文件不自动迁移）；日志保留天数与 JSONL 同上"
        >
          <FieldRow label="主库路径（memory.db）" hint="重启后生效；改路径不会迁移现有数据">
            <n-input
              v-model:value="form.memory_db_path"
              size="small"
              :disabled="locked('memory_db_path')"
            />
            <ConfigSourceTag :source="sourceOf('memory_db_path')" />
            <FieldError :msg="fieldErrors.memory_db_path" />
          </FieldRow>
          <FieldRow label="图层文件（graph.json）" hint="重启后生效；改路径不会迁移现有数据">
            <n-input
              v-model:value="form.graph_json_path"
              size="small"
              :disabled="locked('graph_json_path')"
            />
            <ConfigSourceTag :source="sourceOf('graph_json_path')" />
            <FieldError :msg="fieldErrors.graph_json_path" />
          </FieldRow>
          <FieldRow label="日志级别" hint="重启后生效">
            <n-select
              v-model:value="form.log_level"
              size="small"
              class="f-select"
              :options="LOG_LEVEL_OPTIONS"
              :disabled="locked('log_level')"
            />
            <ConfigSourceTag :source="sourceOf('log_level')" />
            <FieldError :msg="fieldErrors.log_level" />
          </FieldRow>
        </SectionCard>

        <!-- 9. 维护动作（独立卡片） -->
        <SectionCard title="维护动作" :hint="`作用书目：${actionScopeLabel}`">
          <div class="action-block">
            <div class="action-head">
              <span class="action-title">手动补偿</span>
              <span class="action-desc">把 raw / indexed 积压事件重新入队走 Agent 管线</span>
            </div>
            <div class="action-row">
              <n-button size="small" :loading="compensating" @click="doCompensate">触发补偿</n-button>
            </div>
            <p v-if="compensateMsg" class="action-msg ok">{{ compensateMsg }}</p>
            <p v-if="compensateError" class="action-msg bad">{{ compensateError }}</p>
          </div>

          <div class="action-block">
            <div class="action-head">
              <span class="action-title">手动维护</span>
              <span class="action-desc">优化图结构：减碎 + 补缺 → 再连线（衍生知识，不动原文）</span>
            </div>
            <div class="action-row">
              <n-select v-model:value="maintainMode" size="small" class="f-select" :options="MAINTAIN_MODE_OPTIONS" />
              <n-button size="small" :loading="maintaining" @click="doMaintain">触发维护</n-button>
            </div>
            <p v-if="maintainMsg" class="action-msg ok">{{ maintainMsg }}</p>
            <p v-if="maintainError" class="action-msg bad">{{ maintainError }}</p>
          </div>

          <div class="action-block">
            <div class="action-head">
              <span class="action-title">AI 调用日志</span>
              <span class="action-desc">角色 / 模型 / 时间；失败（error 非空）用危险色标出</span>
            </div>
            <div class="action-row">
              <n-select v-model:value="logLimit" size="small" class="f-narrow" :options="LOG_LIMIT_OPTIONS" />
              <n-switch v-model:value="logFull" size="small">
                <template #checked>取全文</template>
                <template #unchecked>仅摘要</template>
              </n-switch>
              <n-button size="small" :loading="logsLoading" @click="loadLogs">刷新日志</n-button>
              <span class="action-note">
                共 {{ logs.length }} 条 · 全文需后端允许（DPIM_AGENT_LOGS_FULL）
              </span>
            </div>
            <n-collapse v-if="logs.length" accordion class="log-list">
              <n-collapse-item
                v-for="(log, i) in logs"
                :key="`${log.timestamp}-${i}`"
                :name="String(i)"
              >
                <template #header>
                  <span class="log-head">
                    <span class="log-role" :class="{ 'log-role--bad': !!log.error }">{{ log.role }}</span>
                    <span class="log-model mono">{{ log.model || '—' }}</span>
                    <span class="log-time mono">{{ fmtTs(log.timestamp) }}</span>
                    <span v-if="log.error" class="chip chip--bad">失败</span>
                  </span>
                </template>
                <div class="log-body">
                  <p v-if="log.error" class="log-error">{{ log.error }}</p>
                  <template v-else>
                    <p class="log-label">输入</p>
                    <!-- full=true 时后端（core/llm.py:176）直接下发 `log.__dict__`，字段名是 `input`；
                         `input_preview` 只在摘要分支存在 → 只读 input_preview 会让「取全文」的输入区恒空白 -->
                    <pre class="log-text mono">{{ log.input_preview ?? log.input ?? '' }}</pre>
                    <p class="log-label">输出</p>
                    <pre class="log-text mono">{{ log.output }}</pre>
                  </template>
                </div>
              </n-collapse-item>
            </n-collapse>
            <StateBlock
              v-else
              :loading="logsLoading"
              :error="logsError"
              empty-text="暂无调用记录"
              hint="Agent 管线未运行时不会有调用记录；点「刷新日志」重取。"
              fixed-height
            />
          </div>
        </SectionCard>
      </div>
    </template>

    <!-- 提供商编辑弹窗：逐字段表单（密钥留空 = 保持现值） -->
    <n-modal :show="providerOpen" :mask-closable="false" @update:show="onProviderToggle">
      <div class="modal-box">
        <h3 class="modal-title">
          {{ editingName ? `编辑提供商 · ${editingName}` : '新增提供商' }}
        </h3>
        <div class="modal-body">
          <FieldRow label="名称" hint="注册表键名，须唯一">
            <n-input v-model:value="pForm.name" size="small" placeholder="如 siliconflow" />
          </FieldRow>
          <FieldRow label="接口格式" :hint="FORMAT_HINT[pForm.format] || ''">
            <n-select v-model:value="pForm.format" size="small" class="f-select" :options="FORMAT_OPTIONS" />
          </FieldRow>
          <FieldRow label="Base URL" :hint="`模型地址（${FORMAT_LABEL[pForm.format] || 'OpenAI 兼容'}）`">
            <n-input
              v-model:value="pForm.base_url"
              size="small"
              :placeholder="FORMAT_PLACEHOLDER[pForm.format] || 'https://api.siliconflow.cn/v1'"
            />
          </FieldRow>
          <FieldRow
            v-if="pForm.format === 'custom'"
            label="请求路径"
            hint="api_path：拼在 Base URL 后面；留空 = /chat/completions"
          >
            <n-input v-model:value="pForm.api_path" size="small" placeholder="/chat/completions" />
          </FieldRow>
          <FieldRow
            v-if="pForm.format === 'custom'"
            label="额外请求头（JSON）"
            hint="extra_headers：如自建网关的鉴权头；必须是合法 JSON 对象。回填时值显示为 **** = 保持原值；整段重填则覆盖（新增的键若只写 **** 又没有原值，保存时该键会被丢弃并提示）"
          >
            <n-input
              v-model:value="pForm.extra_headers_text"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder='{"X-API-Key": "…"}'
            />
          </FieldRow>
          <FieldRow label="API Key" hint="留空 = 保持现值；界面不回显明文">
            <n-input
              v-model:value="pForm.api_key"
              type="password"
              show-password-on="click"
              size="small"
              :disabled="pForm.clear_key"
              :placeholder="editingName && providersDraft[editingName]?.api_key
                ? `当前 ${providersDraft[editingName].api_key}，留空保持不变`
                : 'sk-…（本地服务可留空）'"
            />
          </FieldRow>
          <FieldRow
            v-if="editingName && providersDraft[editingName]?.api_key"
            label="清除该条目的密钥"
            hint="开关打开后保存并提交，密钥被清空（本地服务无需密钥时用）"
          >
            <n-switch v-model:value="pForm.clear_key" size="small" />
          </FieldRow>
          <FieldRow label="保存后设为使用中" hint="把「使用中的提供商」指向本条（提交配置后生效）">
            <n-switch v-model:value="pForm.make_active" size="small" />
          </FieldRow>
          <FieldRow label="单模型（旧式）" hint="model：与下面的模型列表二选一即可">
            <n-input v-model:value="pForm.model" size="small" placeholder="Qwen3.5-9B" />
          </FieldRow>
          <FieldRow label="模型列表" hint="models：逗号或换行分隔；也可从端点一键拉取">
            <n-input
              v-model:value="pForm.models_text"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
              placeholder="Qwen3.5-9B, deepseek-v4"
            />
            <div class="row-inline">
              <n-button size="tiny" :loading="probingDraft" @click="pullModelsDraft">拉取模型列表</n-button>
              <span v-if="pFormProbeNote" class="note">{{ pFormProbeNote }}</span>
            </div>
          </FieldRow>
          <FieldRow label="超时（秒）" hint="1–3600，留空 = 默认">
            <n-input-number v-model:value="pForm.timeout" size="small" class="f-number" :min="1" :max="3600" />
          </FieldRow>
          <FieldRow label="输出上限 tokens" :hint="maxTokensHint">
            <n-input-number v-model:value="pForm.max_tokens" size="small" class="f-number" :min="0" :max="32768" />
          </FieldRow>
          <FieldRow label="思考开关" hint="未设置 = 服务端默认；显式「关」优先于思考预算（关就是关）">
            <n-select v-model:value="pForm.enable_thinking" size="small" class="f-select" :options="TRIPLE_OPTIONS" />
          </FieldRow>
          <FieldRow label="思考预算 tokens" hint="0 = 不设，留空 = 未设置；思考 token 计入输出上限（Anthropic 下上限不足会自动抬到预算 + 1024）">
            <n-input-number v-model:value="pForm.thinking_budget" size="small" class="f-number" :min="0" :max="32768" />
          </FieldRow>
          <FieldRow label="思考风格" hint="thinking_style：厂商适配（仅 OpenAI 兼容格式）">
            <n-select v-model:value="pForm.thinking_style" size="small" class="f-select" :options="THINKING_STYLE_OPTIONS" />
          </FieldRow>
          <FieldRow label="结构化模式" hint="structured_mode：厂商适配（仅 OpenAI 兼容格式）">
            <n-select v-model:value="pForm.structured_mode" size="small" class="f-select" :options="STRUCTURED_OPTIONS" />
          </FieldRow>
          <FieldRow
            label="厂商参数（JSON）"
            hint="extra_body：任意透传参数，必须是合法 JSON 对象。这里的内容在卡片上只显示键名（值不渲染）；不要放密钥——密钥请填上面的 API Key 或额外请求头"
          >
            <n-input
              v-model:value="pForm.extra_body_text"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 6 }"
              placeholder='{"enable_thinking": false}'
            />
          </FieldRow>
        </div>
        <p v-if="pFormError" class="modal-error">{{ pFormError }}</p>
        <div class="modal-actions">
          <n-button size="small" quaternary @click="providerOpen = false">取消</n-button>
          <n-button size="small" type="primary" @click="saveProvider">保存</n-button>
        </div>
      </div>
    </n-modal>

    <ConfirmDialog
      v-model:show="removeOpen"
      danger
      :title="`删除提供商「${removeTarget}」？`"
      message="从 BYOK 注册表移除该条目"
      :impacts="[
        '只是从本地草稿移除，点「提交配置」后才写回后端。',
        '若「使用中的提供商」仍指向它，请先改成其它提供商再提交。',
      ]"
      confirm-text="删除"
      @confirm="doRemove"
    />

    <ConfirmDialog
      v-model:show="clearKeyOpen"
      danger
      title="清除已保存的访问密钥？"
      message="从本机浏览器的 localStorage 里真删「dpim_api_key」"
      :impacts="[
        '只影响这台浏览器：之后所有请求都不再带 X-API-Key。',
        '后端若仍设 DPIM_API_KEY，之后的写操作会 401，需要重新填一次。',
        '后端配置（dpim.json）与环境变量不受影响，不会被改动。',
      ]"
      confirm-text="清除"
      @confirm="doClearApiKey"
    />
  </PageShell>
</template>

<script setup lang="ts">
/**
 * 运行配置（维护区，规约 §4.11）：环境变量与运行参数。
 *
 * 硬要求：
 * - 板块分组（SectionCard + FieldRow）+ 提供商卡片化 + 密钥掩码（留空 = 保持现值）。
 * - 三态：加载 / 就绪 / 提交结果（含「哪些字段需重启」）。
 * - 失败路径：校验失败**保留用户编辑**并指出字段（后端 422 的 detail 已格式化成 `字段: 消息`）。
 * - 书目作用域由顶栏全局作用域决定（联查时留空 = 活动书目），维护动作随该作用域下发。
 */
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue'
import {
  NButton,
  NCollapse,
  NCollapseItem,
  NInput,
  NInputNumber,
  NModal,
  NSelect,
  NSwitch,
  useMessage,
} from 'naive-ui'
import PageShell from '@/components/ui/PageShell.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import Toolbar from '@/components/ui/Toolbar.vue'
import FieldRow from '@/components/ui/FieldRow.vue'
import ConfigSourceTag from '@/components/ui/ConfigSourceTag.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import ConfirmDialog from '@/components/ui/ConfirmDialog.vue'
import * as settingsApi from '@/api/settings'
import * as healthApi from '@/api/health'
import { apiKey, backendBase, clearApiKey, setApiKey, setBackendBase } from '@/api/http'
import type {
  LLMCallLog,
  ProviderEntry,
  ProviderFormat,
  SettingsResponse,
  SettingsUpdateRequest,
} from '@/api/types'
import { useRepoScope } from '@/composables/useRepoScope'
import { useUnsavedGuard } from '@/composables/useUnsavedGuard'
import { useSessionStore } from '@/stores/session'

/**
 * 契约别名（v1.32 已把 `health_check_timeout` 收录进 `share/protocol.ts`，
 * 此前的本地扩展类型已删除——契约是唯一来源，这里只留可读别名）。
 */
type SettingsLike = SettingsResponse
type SettingsUpdateLike = SettingsUpdateRequest

/** 字段级错误提示（挂在该字段的控件下方，危险色） */
const FieldError = defineComponent({
  props: { msg: { type: String, default: '' } },
  setup: (props) => () => (props.msg ? h('p', { class: 'field-error' }, props.msg) : null),
})

const message = useMessage()
const session = useSessionStore()
const scope = useRepoScope()

const RESTART_NOTE =
  '即时生效：后端地址与访问密钥（浏览器本地）、模型与提供商、Agent 管线、检索与护栏、健康检查与补偿、图维护自动化、WAL 检查点、保留策略（下一次存储卫生轮次，最多 1 小时）。需重启后端：存储路径（主库 / 图层文件）、日志级别、日志保留天数与 JSONL 开关——它们写入 dpim.json，由后端下次启动读取。'

const AGENT_MODE_OPTIONS = [
  { label: 'disabled（只存储，不进图谱）', value: 'disabled' },
  { label: 'pipeline（四 Agent 管线）', value: 'pipeline' },
]
/** llm_structured_mode（v1.36）：非角色 LLM 默认的结构化输出模式 */
const STRUCTURED_MODE_OPTIONS = [
  { label: 'md_json（默认，兼容 llama.cpp）', value: 'md_json' },
  { label: 'json（严格 JSON 输出）', value: 'json' },
  { label: 'tools（函数调用模式）', value: 'tools' },
]
const LOG_LEVEL_OPTIONS = [
  { label: 'DEBUG', value: 'DEBUG' },
  { label: 'INFO', value: 'INFO' },
  { label: 'WARNING', value: 'WARNING' },
  { label: 'ERROR', value: 'ERROR' },
]
const MAINTAIN_MODE_OPTIONS = [
  { label: 'update（减碎 + 补缺 → 再连线）', value: 'update' },
  { label: 'compress（删繁就简，可补边）', value: 'compress' },
]
const TRIPLE_OPTIONS = [
  { label: '未设置（服务端默认）', value: 'default' },
  { label: '开启', value: 'on' },
  { label: '关闭', value: 'off' },
]
const THINKING_STYLE_OPTIONS = [
  { label: '未设置', value: '' },
  { label: 'auto', value: 'auto' },
  { label: 'top_level', value: 'top_level' },
  { label: 'chat_template_kwargs', value: 'chat_template_kwargs' },
]
const STRUCTURED_OPTIONS = [
  { label: '未设置', value: '' },
  { label: 'md_json', value: 'md_json' },
  { label: 'json', value: 'json' },
  { label: 'tools', value: 'tools' },
]
/** 接口格式（v1.43）：一个 provider 条目 = 一套协议 */
const FORMAT_OPTIONS = [
  { label: 'OpenAI 兼容（chat/completions）', value: 'openai' },
  { label: 'OpenAI Responses（/responses）', value: 'responses' },
  { label: 'Anthropic Messages（/messages）', value: 'anthropic' },
  { label: '自定义（自定路径与请求头）', value: 'custom' },
]
const FORMAT_LABEL: Record<string, string> = {
  openai: 'OpenAI 兼容',
  responses: 'OpenAI Responses',
  anthropic: 'Anthropic',
  custom: '自定义',
}
const FORMAT_HINT: Record<string, string> = {
  openai: 'POST {base}/chat/completions，Bearer 鉴权；思考开关/思考风格/结构化模式三项只对这一套生效',
  responses: 'POST {base}/responses：body 用 input 与 max_output_tokens（不是 messages/max_tokens），结构化输出走工具调用',
  anthropic: 'POST {base}/messages：x-api-key + anthropic-version 头，system 是顶层字段、max_tokens 必填（未填按 4096，见下方「输出上限」）',
  custom: '自定请求路径与额外请求头，仍按 chat completions 形状收发（模型列表探测也按这套）',
}
/** Anthropic Messages 的 max_tokens 是必填项，后端没填时按此兜底。
 *  与 `dpim/core/config.py` 的 `ANTHROPIC_DEFAULT_MAX_TOKENS` / `ANTHROPIC_THINKING_HEADROOM` 对齐——
 *  界面要把「实际会发出去多少」说清楚，不能只写「默认」（改后端常量时记得同步这两行）。 */
const ANTHROPIC_DEFAULT_MAX_TOKENS = 4096
const ANTHROPIC_THINKING_HEADROOM = 1024
const FORMAT_PLACEHOLDER: Record<string, string> = {
  openai: 'https://api.siliconflow.cn/v1',
  responses: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com/v1',
  custom: 'https://your-gateway/v1',
}
const LOG_LIMIT_OPTIONS = [
  { label: '最近 20 条', value: 20 },
  { label: '最近 50 条', value: 50 },
  { label: '最近 100 条', value: 100 },
]

/** 后端 422 会报到的字段名（用于把错误定位到具体字段） */
const FIELD_KEYS = [
  'active_provider',
  'active_model',
  'providers',
  'agent_mode',
  'agent_max_retries',
  'llm_structured_mode',
  'agent_cr_model',
  'agent_in_model',
  'agent_gr_model',
  'agent_meta_model',
  'max_graph_hops',
  'rrf_k',
  'jaccard_threshold',
  'max_raw_content',
  'health_check_interval',
  'health_check_timeout',
  'compensate_batch_size',
  'compensate_check_interval',
  'agent_maintain_auto',
  'agent_maintain_min_nodes',
  'agent_maintain_max_nodes',
  'agent_maintain_cooldown',
  'agent_cmdmsg_max_rounds',
  'agent_cr_skip_chars',
  'log_retention_days',
  'log_jsonl',
  'agent_logs_full',
  'wal_checkpoint_interval',
  'wal_checkpoint_bytes',
  'graph_ops_retention',
  'trash_retention_days',
  'memory_db_path',
  'graph_json_path',
  'log_level',
] as const

// ── 状态 ──
const original = ref<SettingsLike | null>(null)
const loading = ref(true)
const loadError = ref('')
const submitting = ref(false)
const savedHint = ref('')
const submitError = ref('')
/** PUT 响应里的 ignored_by_env：被环境变量锁定、本次未写入的字段（形如 `rrf_k(DPIM_RRF_K)`） */
const ignoredByEnv = ref<string[]>([])
const fieldErrors = ref<Record<string, string>>({})
const localNote = ref('')
const hasApiKey = ref(Boolean(apiKey()))
/** 清除访问密钥的二次确认（ConfirmDialog） */
const clearKeyOpen = ref(false)

const form = reactive({
  // 浏览器本地
  backend_url: '',
  api_key: '',
  // 模型与提供商（v1.34：身份只在 providers 注册表里）
  active_provider: '',
  active_model: '',
  // Agent 管线
  agent_mode: 'disabled' as 'disabled' | 'pipeline',
  llm_structured_mode: 'md_json' as 'md_json' | 'json' | 'tools',
  agent_max_retries: null as number | null,
  agent_cr_model: '',
  agent_in_model: '',
  agent_gr_model: '',
  agent_meta_model: '',
  // 检索与护栏
  max_graph_hops: null as number | null,
  rrf_k: null as number | null,
  jaccard_threshold: null as number | null,
  max_raw_content: null as number | null,
  // 健康检查与补偿
  health_check_interval: null as number | null,
  health_check_timeout: null as number | null,
  compensate_batch_size: null as number | null,
  compensate_check_interval: null as number | null,
  // 图维护自动化
  agent_maintain_auto: true,
  agent_maintain_min_nodes: null as number | null,
  agent_maintain_max_nodes: null as number | null,
  agent_maintain_cooldown: null as number | null,
  agent_cmdmsg_max_rounds: null as number | null,
  agent_cr_skip_chars: null as number | null,
  // 本地日志与 WAL
  log_retention_days: null as number | null,
  log_jsonl: false,
  agent_logs_full: true,
  wal_checkpoint_interval: null as number | null,
  wal_checkpoint_bytes: null as number | null,
  // 保留策略（v1.39）
  graph_ops_retention: null as number | null,
  trash_retention_days: null as number | null,
  // 存储路径与日志级别
  memory_db_path: '',
  graph_json_path: '',
  log_level: 'INFO',
})

const providersDraft = ref<Record<string, ProviderEntry>>({})
const providerNames = computed(() => Object.keys(providersDraft.value).sort())

const failedFields = computed(() => Object.keys(fieldErrors.value))

// ── 配置来源（v1.36）：回答「这个值来自哪里」；env 锁定的项界面改不动，必须看得见 ──
/** `config_sources[字段]` 原文：`env:DPIM_X` / `file` / `default`（空 = 后端未上报） */
function sourceOf(field: string): string {
  return original.value?.config_sources?.[field] ?? ''
}

/** 该字段是否被环境变量顶掉（是 → 控件置灰；PUT 也不会写入内存，后端在 ignored_by_env 里点名） */
function locked(field: string): boolean {
  return sourceOf(field).startsWith('env:')
}

// ── 选项 ──
const providerOptions = computed(() => {
  const names = new Set<string>(original.value?.available_providers ?? [])
  for (const n of Object.keys(providersDraft.value)) names.add(n)
  if (form.active_provider) names.add(form.active_provider) // 已删但仍在用 → 显式标出
  return [...names].sort((a, b) => a.localeCompare(b)).map((n) => ({
    label: providersDraft.value[n] ? n : `${n}（未登记）`,
    value: n,
  }))
})

/** 当前所选提供商可用的模型（优先用草稿：新增/改动/刚拉取的模型即时可选） */
const providerModelList = computed<string[]>(() => {
  const s = original.value
  if (!s) return []
  const name = form.active_provider
  const draft = providersDraft.value[name]
  const fromDraft = draft ? modelsOf(draft) : []
  if (fromDraft.length) return fromDraft
  return name === s.active_provider ? (s.available_models ?? []) : []
})

const activeModelOptions = computed(() => {
  const opts = [{ label: '（跟随使用模型 = 空）', value: '' }]
  for (const m of providerModelList.value) opts.push({ label: m, value: m })
  if (form.active_model && !providerModelList.value.includes(form.active_model)) {
    opts.push({ label: `${form.active_model}（当前，不在列表）`, value: form.active_model })
  }
  return opts
})

function roleModelOptions(current: string): Array<{ label: string; value: string }> {
  const opts = [{ label: '（跟随使用模型）', value: '' }]
  for (const m of providerModelList.value) opts.push({ label: m, value: m })
  if (current && !providerModelList.value.includes(current)) {
    opts.push({ label: `${current}（当前，不在列表）`, value: current })
  }
  return opts
}

// ── 模型列表探测（POST /settings/models，v1.34）──
const probing = ref('')
const probeNotes = ref<Record<string, string>>({})
const probingDraft = ref(false)
const pFormProbeNote = ref('')

function probeNoteOf(name: string): string {
  return probeNotes.value[name] ?? ''
}

/** 本地掩码：与后端 `core/security.py` 的 `mask_secret` **同规则**（头 3 + `****` + 尾 4；≤7 字符全掩码）。
 *
 *  为什么前端也要掩：草稿会被卡片与弹窗占位符**直接渲染**。旧实现把刚输入的明文写进草稿 →
 *  卡片「密钥 oc_sk_…」与占位符「当前 oc_sk_…，留空保持不变」**都显示明文**（用户实测截图确认，
 *  而同一行的提示还写着「界面不回显明文」——界面在说谎）。现在：**草稿只存掩码**，
 *  明文只活在输入框与 `pendingSecrets` 里，直到「提交配置」那一刻才下发。
 */
function maskLocal(secret: string): string {
  if (!secret) return ''
  return secret.length <= 7 ? '****' : `${secret.slice(0, 3)}****${secret.slice(-4)}`
}

/** 已输入但**尚未提交**的明文密钥（按 provider 名）；提交成功或重新拉取后清空。 */
const pendingSecrets: Record<string, string> = {}

/** 提交用：把草稿里的掩码换回真值（仅对 `pendingSecrets` 里记着的条目）。 */
function withPendingSecrets(
  draft: Record<string, ProviderEntry>,
): Record<string, ProviderEntry> {
  const out: Record<string, ProviderEntry> = {}
  for (const [k, v] of Object.entries(draft)) {
    out[k] = pendingSecrets[k] ? { ...v, api_key: pendingSecrets[k] } : v
  }
  return out
}

/** 有「未提交的密钥」吗——草稿与已存配置**看起来一样**时也要发 PUT（否则新密钥永远存不下去）。 */
function hasPendingSecret(): boolean {
  return Object.keys(pendingSecrets).some((k) => k in providersDraft.value)
}

/**
 * 提供商草稿是否**脏**（离开守卫判据）：与 `submit()` 的提交判定**同一写法**
 * （两处必须同步——否则会出现「守卫说有改动」而提交说「没有需要保存的修改」，或反过来
 * 「有刚输入的密钥但守卫放行、切页即丢」）。待提交的明文密钥只在内存里，刷新即消失。
 */
const providersDirty = computed(
  () =>
    JSON.stringify(providersDraft.value) !== JSON.stringify(original.value?.providers ?? {}) ||
    hasPendingSecret(),
)

// 未保存草稿的离开守卫（链 AM）：切页 / 刷新 / 关标签前拦一次，绝不无声丢弃
useUnsavedGuard(
  () => providersDirty.value,
  '提供商配置还没提交（若有刚输入的密钥：明文只在本页内存里，离开即丢）。确定离开吗？',
)

// ── 额外请求头（extra_headers）的「只回填键名」：值与 api_key 同一类敏感面 ──
/** 回填占位符：值显示为 `****` = 保持原值（语义写在字段提示里）。 */
const HEADER_VALUE_MASK = '****'

/**
 * 回填弹窗用：**只保留键名**，值一律掩成 `****`。
 *
 * 为什么：该控件是普通 textarea，占位符本身就是 `{"X-API-Key": "…"}`——用户照着示范把鉴权头
 * 填进去后，点「编辑」就把明文摊在框里（后端只掩 `api_key`，**不掩 `extra_headers`**）。
 * 与 `maskLocal()` 同一口径：明文不落草稿、不落 DOM，只在用户重新输入时存在。
 */
function maskedHeadersText(headers: Record<string, string> | undefined): string {
  if (!headers) return ''
  const masked: Record<string, string> = {}
  for (const k of Object.keys(headers)) masked[k] = HEADER_VALUE_MASK
  return JSON.stringify(masked, null, 2)
}

/**
 * 保存用：把回填的 `****` 占位符换回**该条目已存的原值**。
 *
 * - 值不是 `****`（用户重填了）→ 按用户输入走；
 * - 值是 `****` 且条目里有同名键 → 取回原值（回填后原样保存不丢头）；
 * - 值是 `****` 但取不到原值（新增条目、或该键本来不存在）→ **丢弃该键**，
 *   由调用方把原因明确告诉用户（不能静默写一个字面 `****` 上去）。
 * - 整段删掉/重写 → 调用方拿到的就是 undefined / 全新键集，按「用户就是要覆盖」处理，不硬塞回原值。
 */
function restoreMaskedHeaders(
  headers: Record<string, string> | undefined,
  stored: Record<string, string> | undefined,
): { headers: Record<string, string> | undefined; dropped: string[] } {
  if (!headers) return { headers: undefined, dropped: [] }
  const out: Record<string, string> = {}
  const dropped: string[] = []
  for (const [k, v] of Object.entries(headers)) {
    if (v !== HEADER_VALUE_MASK) {
      out[k] = v
      continue
    }
    const kept = stored?.[k]
    if (typeof kept === 'string') out[k] = kept
    else dropped.push(k)
  }
  return { headers: Object.keys(out).length ? out : undefined, dropped }
}

/** 卡片用：`extra_body` 的**键名**列表（值一律不渲染——里面可能被塞了密钥）。 */
function extraBodyKeys(entry: ProviderEntry | undefined): string[] {
  const body = entry?.extra_body
  if (!body || typeof body !== 'object') return []
  return Object.keys(body)
}

/** 卡片「拉取模型」：**用草稿的值**探测。
 *
 *  旧实现只发 `{provider: 名字}`，后端只能去**已保存配置**里查该条目——于是刚新增、
 *  还没点「提交配置」的条目一律报「未填模型地址（base_url）」，而地址明明就显示在卡片上
 *  （用户实测：弹窗里能拉到 37 个模型，卡片上却报这个）。现在把草稿的地址/密钥/格式/
 *  自定义路径与额外请求头一起带上；密钥只带**未提交的真值**，留空 = 后端用已存密钥。
 */
async function pullModels(name: string): Promise<void> {
  const draft = providersDraft.value[name]
  const baseUrl = String(draft?.base_url ?? '').trim()
  if (!baseUrl) {
    probeNotes.value = {
      ...probeNotes.value,
      [name]: '拉取失败：该条目还没填地址（base_url）——点「编辑」填好地址再拉取',
    }
    return
  }
  probing.value = name
  probeNotes.value = { ...probeNotes.value, [name]: '' }
  try {
    const res = await settingsApi.probeProviderModels({
      provider: name,
      base_url: baseUrl,
      api_key: pendingSecrets[name] ?? '',
      // v1.43：把该条目的格式显式带上（Anthropic 的头与端点都不同）
      format: draft?.format ?? 'openai',
      api_path: String(draft?.api_path ?? ''),
      extra_headers: draft?.extra_headers,
    })
    if (res.error) {
      probeNotes.value = { ...probeNotes.value, [name]: `拉取失败：${res.error}` }
      message.error(`「${name}」拉取失败，原因见卡片`)
      return
    }
    const entry = providersDraft.value[name]
    if (entry) entry.models = res.models
    probeNotes.value = {
      ...probeNotes.value,
      [name]: `已拉取 ${res.models.length} 个模型（${res.elapsed_ms} ms），点「提交配置」后保存`,
    }
    message.success(`已拉取 ${res.models.length} 个模型`)
  } catch (e) {
    probeNotes.value = { ...probeNotes.value, [name]: `拉取失败：${(e as Error).message}` }
  } finally {
    probing.value = ''
  }
}

/** 弹窗内探测：地址 + 密钥用当前草稿（密钥留空时借用已保存条目的密钥） */
async function pullModelsDraft(): Promise<void> {
  const baseUrl = pForm.base_url.trim()
  if (!baseUrl) {
    pFormError.value = '请先填写 Base URL'
    return
  }
  probingDraft.value = true
  pFormProbeNote.value = ''
  try {
    const res = await settingsApi.probeProviderModels({
      provider: editingName.value ?? '',
      base_url: baseUrl,
      api_key: pForm.api_key.trim(),
      format: pForm.format,
    })
    if (res.error) {
      pFormProbeNote.value = `拉取失败：${res.error}`
      return
    }
    pForm.models_text = res.models.join(', ')
    pFormProbeNote.value = `已拉取 ${res.models.length} 个模型（${res.elapsed_ms} ms）`
  } catch (e) {
    pFormProbeNote.value = `拉取失败：${(e as Error).message}`
  } finally {
    probingDraft.value = false
  }
}

// ── 作用域（维护动作） ──
const actionScopeLabel = computed(() =>
  scope.isJoint.value
    ? `活动书目《${scope.repo.activeRepo?.name ?? '—'}》（联查作用域留空 = 活动书目）`
    : `《${scope.repo.nameOf(scope.effectiveRepoId.value)}》`,
)

// ── 载入 ──
function fillForm(s: SettingsLike): void {
  form.backend_url = backendBase()
  form.api_key = ''
  form.active_provider = s.active_provider || ''
  form.active_model = s.active_model ?? ''
  form.agent_mode = s.agent_mode === 'pipeline' ? 'pipeline' : 'disabled'
  const mode = s.llm_structured_mode
  form.llm_structured_mode = mode === 'json' || mode === 'tools' ? mode : 'md_json'
  form.agent_max_retries = s.agent_max_retries ?? null
  form.agent_cr_model = s.agent_cr_model ?? ''
  form.agent_in_model = s.agent_in_model ?? ''
  form.agent_gr_model = s.agent_gr_model ?? ''
  form.agent_meta_model = s.agent_meta_model ?? ''
  form.max_graph_hops = s.max_graph_hops ?? null
  form.rrf_k = s.rrf_k ?? null
  form.jaccard_threshold = s.jaccard_threshold ?? null
  form.max_raw_content = s.max_raw_content ?? null
  form.health_check_interval = s.health_check_interval ?? null
  form.health_check_timeout = s.health_check_timeout ?? null
  form.compensate_batch_size = s.compensate_batch_size ?? null
  form.compensate_check_interval = s.compensate_check_interval ?? null
  form.agent_maintain_auto = s.agent_maintain_auto ?? true
  form.agent_maintain_min_nodes = s.agent_maintain_min_nodes ?? null
  form.agent_maintain_max_nodes = s.agent_maintain_max_nodes ?? null
  form.agent_maintain_cooldown = s.agent_maintain_cooldown ?? null
  form.agent_cmdmsg_max_rounds = s.agent_cmdmsg_max_rounds ?? null
  form.agent_cr_skip_chars = s.agent_cr_skip_chars ?? null
  form.log_retention_days = s.log_retention_days ?? null
  form.log_jsonl = s.log_jsonl ?? false
  form.agent_logs_full = s.agent_logs_full ?? true
  form.wal_checkpoint_interval = s.wal_checkpoint_interval ?? null
  form.wal_checkpoint_bytes = s.wal_checkpoint_bytes ?? null
  form.graph_ops_retention = s.graph_ops_retention ?? null
  form.trash_retention_days = s.trash_retention_days ?? null
  form.memory_db_path = s.memory_db_path ?? ''
  form.graph_json_path = s.graph_json_path ?? ''
  form.log_level = s.log_level || 'INFO'
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const res = (await settingsApi.getSettings()) as SettingsLike
    original.value = res
    fillForm(res)
    providersDraft.value = JSON.parse(JSON.stringify(res.providers ?? {})) as Record<
      string,
      ProviderEntry
    >
    fieldErrors.value = {}
    submitError.value = ''
    hasApiKey.value = Boolean(apiKey())
  } catch (e) {
    loadError.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
  void loadLogs()
})

// ── 校验与提交 ──
/** 本地必填校验：数值字段留空不提交（保留编辑，指出字段） */
function localValidate(): boolean {
  const errs: Record<string, string> = {}
  const required: Array<[string, number | null, string]> = [
    ['agent_max_retries', form.agent_max_retries, 'Meta 最大修正轮次'],
    ['max_graph_hops', form.max_graph_hops, '图谱最大跳数'],
    ['rrf_k', form.rrf_k, 'RRF 参数 K'],
    ['jaccard_threshold', form.jaccard_threshold, '杰卡德阈值'],
    ['max_raw_content', form.max_raw_content, '单次输入字符上限'],
    ['health_check_interval', form.health_check_interval, '健康检查间隔'],
    ['health_check_timeout', form.health_check_timeout, '健康检查超时'],
    ['compensate_batch_size', form.compensate_batch_size, '补偿批处理大小'],
    ['compensate_check_interval', form.compensate_check_interval, '补偿结果检查间隔'],
    ['agent_maintain_min_nodes', form.agent_maintain_min_nodes, '自动维护最小节点数'],
    ['agent_maintain_max_nodes', form.agent_maintain_max_nodes, '节点规模高水位'],
    ['agent_maintain_cooldown', form.agent_maintain_cooldown, '高水位冷却'],
    ['agent_cmdmsg_max_rounds', form.agent_cmdmsg_max_rounds, '指令消息轮次封顶'],
    ['agent_cr_skip_chars', form.agent_cr_skip_chars, 'Cr 短路阈值'],
    ['log_retention_days', form.log_retention_days, '日志保留天数'],
    ['wal_checkpoint_interval', form.wal_checkpoint_interval, 'WAL 检查点周期'],
    ['wal_checkpoint_bytes', form.wal_checkpoint_bytes, 'WAL 触发体积'],
    ['graph_ops_retention', form.graph_ops_retention, '图层操作日志保留条数'],
    ['trash_retention_days', form.trash_retention_days, '回收站留档保留天数'],
  ]
  for (const [key, value, label] of required) {
    if (value === null || value === undefined) errs[key] = `${key}: ${label}不能留空`
  }
  fieldErrors.value = errs
  if (Object.keys(errs).length) {
    submitError.value = Object.values(errs).join('; ')
    return false
  }
  return true
}

/** 提交（只下发改动字段；密钥留空 = 保持现值） */
async function submit(): Promise<void> {
  savedHint.value = ''
  localNote.value = ''
  ignoredByEnv.value = []
  if (!localValidate()) {
    message.warning('有字段留空，未提交（已保留你的编辑）')
    return
  }
  const s = original.value
  if (!s) return

  // 浏览器本地两项：不随后端提交
  const url = form.backend_url.trim()
  if (url !== backendBase()) {
    setBackendBase(url)
    localNote.value = '后端地址已更新（浏览器本地，下次请求生效）'
  }
  if (form.api_key.trim()) {
    setApiKey(form.api_key.trim())
    hasApiKey.value = true
    form.api_key = ''
    localNote.value = `${localNote.value} 访问密钥已更新（浏览器本地）。`.trim()
  }

  const body: SettingsUpdateLike = {}
  if (form.active_provider !== (s.active_provider ?? '')) body.active_provider = form.active_provider
  if (form.active_model !== (s.active_model ?? '')) body.active_model = form.active_model
  if (form.agent_mode !== s.agent_mode) body.agent_mode = form.agent_mode
  if (form.llm_structured_mode !== (s.llm_structured_mode ?? 'md_json')) {
    body.llm_structured_mode = form.llm_structured_mode
  }
  if (form.agent_max_retries !== (s.agent_max_retries ?? null)) {
    body.agent_max_retries = form.agent_max_retries ?? undefined
  }
  if (form.agent_cr_model !== (s.agent_cr_model ?? '')) body.agent_cr_model = form.agent_cr_model
  if (form.agent_in_model !== (s.agent_in_model ?? '')) body.agent_in_model = form.agent_in_model
  if (form.agent_gr_model !== (s.agent_gr_model ?? '')) body.agent_gr_model = form.agent_gr_model
  if (form.agent_meta_model !== (s.agent_meta_model ?? '')) {
    body.agent_meta_model = form.agent_meta_model
  }
  if (form.max_graph_hops !== (s.max_graph_hops ?? null)) {
    body.max_graph_hops = form.max_graph_hops ?? undefined
  }
  if (form.rrf_k !== (s.rrf_k ?? null)) body.rrf_k = form.rrf_k ?? undefined
  if (form.jaccard_threshold !== (s.jaccard_threshold ?? null)) {
    body.jaccard_threshold = form.jaccard_threshold ?? undefined
  }
  if (form.max_raw_content !== (s.max_raw_content ?? null)) {
    body.max_raw_content = form.max_raw_content ?? undefined
  }
  if (form.health_check_interval !== (s.health_check_interval ?? null)) {
    body.health_check_interval = form.health_check_interval ?? undefined
  }
  // health_check_timeout：后端已支持，前端契约（protocol.ts）尚未收录 → 本地扩展类型承接
  if (form.health_check_timeout !== (s.health_check_timeout ?? null)) {
    body.health_check_timeout = form.health_check_timeout
  }
  if (form.compensate_batch_size !== (s.compensate_batch_size ?? null)) {
    body.compensate_batch_size = form.compensate_batch_size ?? undefined
  }
  if (form.compensate_check_interval !== (s.compensate_check_interval ?? null)) {
    body.compensate_check_interval = form.compensate_check_interval ?? undefined
  }
  if (form.agent_maintain_auto !== (s.agent_maintain_auto ?? true)) {
    body.agent_maintain_auto = form.agent_maintain_auto
  }
  if (form.agent_maintain_min_nodes !== (s.agent_maintain_min_nodes ?? null)) {
    body.agent_maintain_min_nodes = form.agent_maintain_min_nodes ?? undefined
  }
  if (form.agent_maintain_max_nodes !== (s.agent_maintain_max_nodes ?? null)) {
    body.agent_maintain_max_nodes = form.agent_maintain_max_nodes ?? undefined
  }
  if (form.agent_maintain_cooldown !== (s.agent_maintain_cooldown ?? null)) {
    body.agent_maintain_cooldown = form.agent_maintain_cooldown ?? undefined
  }
  if (form.agent_cmdmsg_max_rounds !== (s.agent_cmdmsg_max_rounds ?? null)) {
    body.agent_cmdmsg_max_rounds = form.agent_cmdmsg_max_rounds ?? undefined
  }
  if (form.agent_cr_skip_chars !== (s.agent_cr_skip_chars ?? null)) {
    body.agent_cr_skip_chars = form.agent_cr_skip_chars ?? undefined
  }
  if (form.log_retention_days !== (s.log_retention_days ?? null)) {
    body.log_retention_days = form.log_retention_days ?? undefined
  }
  if (form.log_jsonl !== (s.log_jsonl ?? false)) body.log_jsonl = form.log_jsonl
  if (form.agent_logs_full !== (s.agent_logs_full ?? true)) {
    body.agent_logs_full = form.agent_logs_full
  }
  if (form.wal_checkpoint_interval !== (s.wal_checkpoint_interval ?? null)) {
    body.wal_checkpoint_interval = form.wal_checkpoint_interval ?? undefined
  }
  if (form.wal_checkpoint_bytes !== (s.wal_checkpoint_bytes ?? null)) {
    body.wal_checkpoint_bytes = form.wal_checkpoint_bytes ?? undefined
  }
  if (form.graph_ops_retention !== (s.graph_ops_retention ?? null)) {
    body.graph_ops_retention = form.graph_ops_retention ?? undefined
  }
  if (form.trash_retention_days !== (s.trash_retention_days ?? null)) {
    body.trash_retention_days = form.trash_retention_days ?? undefined
  }
  if (form.memory_db_path !== (s.memory_db_path ?? '')) body.memory_db_path = form.memory_db_path
  if (form.graph_json_path !== (s.graph_json_path ?? '')) body.graph_json_path = form.graph_json_path
  if (form.log_level !== (s.log_level ?? '')) body.log_level = form.log_level
  if (
    JSON.stringify(providersDraft.value) !== JSON.stringify(s.providers ?? {}) ||
    hasPendingSecret()
  ) {
    // 下发**真值**：草稿里存的是掩码，待提交的真值在 pendingSecrets（后端对掩码/空 = 保持现值）
    body.providers = withPendingSecrets(providersDraft.value)
  }

  if (Object.keys(body).length === 0) {
    savedHint.value = localNote.value || '没有需要保存的修改'
    submitError.value = ''
    return
  }

  submitting.value = true
  submitError.value = ''
  fieldErrors.value = {}
  try {
    const res = await settingsApi.putSettings(body as SettingsUpdateRequest)
    // v1.36：被环境变量顶掉的项后端不写入内存，响应点名是哪些（界面必须看得见，不再静默无效）
    ignoredByEnv.value = res.ignored_by_env ?? []
    // 行为要求 §5.3：写成功后刷新状态校验密钥；失败不刷新（在 catch 里不 commit）
    await session.commit()
    const lockedNote = ignoredByEnv.value.length ? '（部分项被环境变量锁定，见下方说明）' : '。'
    savedHint.value = `${localNote.value ? `${localNote.value} ` : ''}配置已保存并写入 dpim.json${lockedNote}`
    await load()
    // 已写回后端：清掉待提交的真值（`load()` 已把草稿刷成后端下发的掩码）
    for (const k of Object.keys(pendingSecrets)) delete pendingSecrets[k]
    await loadLogs()
  } catch (e) {
    // 校验失败：保留用户编辑，把后端原文（`字段: 消息`）显示出来并定位到字段
    const text = (e as Error).message || String(e)
    submitError.value = text
    fieldErrors.value = parseFieldErrors(text)
    message.error('提交失败，原因见页面上方')
  } finally {
    submitting.value = false
  }
}

/** 后端 422 detail 已由 http.ts 格式化成 `字段: 消息`（分号分隔）→ 定位到字段 */
function parseFieldErrors(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  const chunks = text.split('; ')
  for (const key of FIELD_KEYS) {
    const hit = chunks.find((c) => c.includes(key))
    if (hit) out[key] = hit
  }
  return out
}

// ── 访问密钥（浏览器本地）：撤销出口 ──
/** 访问密钥是**明文存在 localStorage** 的（长期留在浏览器 profile 磁盘、永不过期），
 *  旧实现全仓没有一个 `removeItem` → 用户想撤销只能自己去 devtools 里清。这里给它一个正经出口。 */
const CLEAR_KEY_NOTE =
  '已从本机浏览器移除访问密钥；后端若仍设 DPIM_API_KEY，之后的写操作会 401，需要重新填。'

function askClearApiKey(): void {
  if (!hasApiKey.value) return
  clearKeyOpen.value = true
}

function doClearApiKey(): void {
  clearApiKey() // 真删 localStorage 的 dpim_api_key（removeItem，不是写空串）
  clearKeyOpen.value = false
  form.api_key = '' // 输入框里可能还有刚输入但未提交的值，一并清掉
  hasApiKey.value = false
  localNote.value = CLEAR_KEY_NOTE
  message.success(CLEAR_KEY_NOTE)
}

// ── 提供商 CRUD（草稿态，提交配置后生效） ──
const providerOpen = ref(false)
const editingName = ref<string | null>(null)
const pFormError = ref('')
const pForm = reactive({
  name: '',
  base_url: '',
  api_key: '',
  /** 接口格式（v1.43）：openai | responses | anthropic | custom */
  format: 'openai' as ProviderFormat,
  /** 自定义请求路径（仅 custom） */
  api_path: '',
  /** 额外请求头 JSON 文本（仅 custom 表单露出，其它格式保留原值） */
  extra_headers_text: '',
  model: '',
  models_text: '',
  timeout: null as number | null,
  max_tokens: null as number | null,
  enable_thinking: 'default' as 'default' | 'on' | 'off',
  thinking_budget: null as number | null,
  thinking_style: '',
  structured_mode: '',
  extra_body_text: '',
  /** 显式清空已存密钥（v1.35）：空串仍是「保持现值」，清空必须单独声明 */
  clear_key: false,
  /** 保存后把「使用中的提供商」指向本条（新增时默认开） */
  make_active: false,
})

function modelsOf(entry: ProviderEntry | undefined): string[] {
  if (!entry) return []
  const list = entry.models ?? (entry.model ? [entry.model] : [])
  return list.map(String).filter(Boolean)
}

function thinkingText(entry: ProviderEntry): string {
  if (entry.enable_thinking === true) return '开启'
  if (entry.enable_thinking === false) return '关闭'
  return '默认'
}

/** 该条目**实际会发出去**的输出上限文案（不是「默认」两个字就完事——Anthropic 必填且有兜底）。 */
function maxTokensText(entry: ProviderEntry): string {
  const budget = typeof entry.thinking_budget === 'number' && entry.thinking_budget > 0
    ? entry.thinking_budget
    : 0
  // 后端「显式关 > 预算 > 显式开」：显式关时预算不参与
  const thinkingOn = entry.enable_thinking !== false && (entry.enable_thinking === true || budget > 0)
  const set = typeof entry.max_tokens === 'number' && entry.max_tokens > 0 ? entry.max_tokens : 0
  if (set) {
    if (entry.format === 'anthropic' && thinkingOn && budget >= set) {
      return `${set}（思考预算更大，实际按 ${budget + ANTHROPIC_THINKING_HEADROOM}）`
    }
    return String(set)
  }
  if (entry.format !== 'anthropic') return '默认（不传，服务端决定）'
  if (thinkingOn && budget) return `默认（思考预算 ${budget} + 余量 = ${budget + ANTHROPIC_THINKING_HEADROOM}）`
  return `默认（${ANTHROPIC_DEFAULT_MAX_TOKENS}）`
}

/** 「输出上限」行的提示：把「留空到底会发出去什么」写清楚——各格式语义不同，别只写「默认」。 */
const maxTokensHint = computed(() => {
  if (pForm.format === 'anthropic') {
    return `Anthropic 必填：留空按 ${ANTHROPIC_DEFAULT_MAX_TOKENS} 发送。它是上限而不是目标长度（按实际输出计费：填大不会更贵、填小才会截断）；开了思考时思考 token 也计入，留空会自动按「思考预算 + ${ANTHROPIC_THINKING_HEADROOM}」留出正文余量`
  }
  return '留空 = 不传，由服务端决定（它是上限不是目标长度：填大不会更贵，填小才会截断）'
})

function openAdd(): void {
  editingName.value = null
  pFormError.value = ''
  pForm.name = ''
  pForm.base_url = ''
  pForm.api_key = ''
  pForm.format = 'openai'
  pForm.api_path = ''
  pForm.extra_headers_text = ''
  pForm.model = ''
  pForm.models_text = ''
  pForm.timeout = null
  pForm.max_tokens = null
  pForm.enable_thinking = 'default'
  pForm.thinking_budget = null
  pForm.thinking_style = ''
  pForm.structured_mode = ''
  pForm.extra_body_text = ''
  pForm.clear_key = false
  pForm.make_active = true // 新增即启用：少一步下拉，避免「加了但没生效」
  providerOpen.value = true
}

function openEdit(name: string): void {
  const entry = providersDraft.value[name] ?? { base_url: '', api_key: '' }
  editingName.value = name
  pFormError.value = ''
  pForm.name = name
  pForm.base_url = String(entry.base_url ?? '')
  pForm.api_key = '' // 不回填密钥：留空 = 保持现值
  pForm.format = (entry.format ?? 'openai') as ProviderFormat
  pForm.api_path = String(entry.api_path ?? '')
  pForm.extra_headers_text = maskedHeadersText(entry.extra_headers)
  pForm.model = String(entry.model ?? '')
  pForm.models_text = modelsOf(entry).join(', ')
  pForm.timeout = typeof entry.timeout === 'number' ? entry.timeout : null
  pForm.max_tokens = typeof entry.max_tokens === 'number' ? entry.max_tokens : null
  pForm.enable_thinking =
    entry.enable_thinking === true ? 'on' : entry.enable_thinking === false ? 'off' : 'default'
  pForm.thinking_budget = typeof entry.thinking_budget === 'number' ? entry.thinking_budget : null
  pForm.thinking_style = String(entry.thinking_style ?? '')
  pForm.structured_mode = String(entry.structured_mode ?? '')
  pForm.extra_body_text = entry.extra_body ? JSON.stringify(entry.extra_body, null, 2) : ''
  pForm.clear_key = false
  pForm.make_active = false
  providerOpen.value = true
}

function onProviderToggle(show: boolean): void {
  providerOpen.value = show
}

function saveProvider(): void {
  const name = pForm.name.trim()
  if (!name) {
    pFormError.value = '请填写提供商名称'
    return
  }
  if (!editingName.value && providersDraft.value[name]) {
    pFormError.value = `名称「${name}」已存在`
    return
  }
  if (editingName.value && name !== editingName.value && providersDraft.value[name]) {
    pFormError.value = `名称「${name}」已存在`
    return
  }
  if (!pForm.base_url.trim()) {
    pFormError.value = '请填写 Base URL'
    return
  }
  let extraBody: Record<string, unknown> | undefined
  if (pForm.extra_body_text.trim()) {
    try {
      const parsed = JSON.parse(pForm.extra_body_text) as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        pFormError.value = '厂商参数（extra_body）必须是 JSON 对象'
        return
      }
      extraBody = parsed as Record<string, unknown>
    } catch (e) {
      pFormError.value = `厂商参数（extra_body）不是合法 JSON：${(e as Error).message}`
      return
    }
  }
  // 额外请求头（v1.43）：与 extra_body 同一套校验——必须是 JSON 对象且值为字符串
  let extraHeaders: Record<string, string> | undefined
  if (pForm.extra_headers_text.trim()) {
    try {
      const parsed = JSON.parse(pForm.extra_headers_text) as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        pFormError.value = '额外请求头（extra_headers）必须是 JSON 对象'
        return
      }
      extraHeaders = Object.fromEntries(
        Object.entries(parsed as Record<string, unknown>).map(([k, v]) => [k, String(v)]),
      )
    } catch (e) {
      pFormError.value = `额外请求头（extra_headers）不是合法 JSON：${(e as Error).message}`
      return
    }
  }

  const prev = editingName.value ? providersDraft.value[editingName.value] : undefined
  // 回填的 `****` = 「保持原值」占位符 → 从该条目取回真值（取不到就丢弃该键，下面点名说明）。
  // 「整段删掉/重写」不在此列：那样拿到的是 undefined 或全新键集，按用户就是要覆盖处理。
  const restored = restoreMaskedHeaders(extraHeaders, prev?.extra_headers)
  extraHeaders = restored.headers
  const droppedHeaders = restored.dropped
  const dropNote = droppedHeaders.length
    ? `额外请求头里的 ${droppedHeaders.join('、')} 值是占位符 ${HEADER_VALUE_MASK}，但该条目里没有它们的原值 → 这些键未保存，请重新填写。`
    : ''
  // 保留原条目的其它厂商字段，仅覆盖表单管理的项
  const entry: ProviderEntry = { ...(prev ?? { base_url: '', api_key: '' }) }
  delete entry.clear_api_key
  entry.base_url = pForm.base_url.trim()
  const typedKey = pForm.api_key.trim()
  if (pForm.clear_key) {
    // v1.35：显式清空——单独带 clear_api_key 标记，后端据此把密钥置空
    entry.api_key = ''
    entry.clear_api_key = true
    delete pendingSecrets[name] // 清空 = 连「待提交的真值」一起丢掉
  } else if (typedKey) {
    // **草稿只存掩码**（卡片/占位符都渲染它）；真值暂存到 pendingSecrets，提交时才下发
    pendingSecrets[name] = typedKey
    entry.api_key = maskLocal(typedKey)
  } else {
    // 留空 = 保持现值：草稿沿用现值（掩码）；上一轮输入但未提交的真值继续留着
    entry.api_key = String(prev?.api_key ?? '')
  }
  if (pForm.model.trim()) entry.model = pForm.model.trim()
  else delete entry.model
  const models = pForm.models_text
    .split(/[,，\n]/)
    .map((x) => x.trim())
    .filter(Boolean)
  if (models.length) entry.models = models
  else delete entry.models
  if (pForm.timeout !== null) entry.timeout = pForm.timeout
  else delete entry.timeout
  if (pForm.max_tokens !== null) entry.max_tokens = pForm.max_tokens
  else delete entry.max_tokens
  if (pForm.enable_thinking === 'default') delete entry.enable_thinking
  else entry.enable_thinking = pForm.enable_thinking === 'on'
  if (pForm.thinking_budget !== null) entry.thinking_budget = pForm.thinking_budget
  else delete entry.thinking_budget
  if (pForm.thinking_style) entry.thinking_style = pForm.thinking_style
  else delete entry.thinking_style
  if (pForm.structured_mode) entry.structured_mode = pForm.structured_mode
  else delete entry.structured_mode
  if (extraBody) entry.extra_body = extraBody
  else delete entry.extra_body
  // 接口格式（v1.43）：openai 是缺省值，不写进条目（保持老条目形状干净）
  if (pForm.format && pForm.format !== 'openai') entry.format = pForm.format
  else delete entry.format
  if (pForm.format === 'custom' && pForm.api_path.trim()) entry.api_path = pForm.api_path.trim()
  else delete entry.api_path
  if (extraHeaders && Object.keys(extraHeaders).length) entry.extra_headers = extraHeaders
  else delete entry.extra_headers

  const key = editingName.value
  if (key && key !== name) {
    // 重命名：保序迁移条目，并同步「使用中的提供商」引用
    const renamed: Record<string, ProviderEntry> = {}
    for (const [k, v] of Object.entries(providersDraft.value)) {
      renamed[k === key ? name : k] = v
    }
    renamed[name] = entry
    providersDraft.value = renamed
    if (form.active_provider === key) form.active_provider = name
    // 待提交的真值也跟着改名（否则提交时按旧名找不到 → 密钥静默丢失）
    if (pendingSecrets[key]) {
      pendingSecrets[name] = pendingSecrets[key]
      delete pendingSecrets[key]
    }
  } else {
    providersDraft.value = { ...providersDraft.value, [name]: entry }
  }
  if (pForm.make_active) form.active_provider = name
  providerOpen.value = false
  const baseHint = pForm.make_active
    ? `提供商「${name}」已就绪并设为使用中，点「提交配置」后写回后端并即时生效。`
    : '提供商草稿已更新，点「提交配置」后写回后端。'
  // 丢弃了键就必须被看见：pFormError 在弹窗内（用户回头再进编辑可见），
  // 而保存成功即关弹窗 → 同一句话同时写进页面顶部常驻的「提交结果」横幅。
  if (dropNote) pFormError.value = dropNote
  savedHint.value = dropNote ? `${dropNote}${baseHint}` : baseHint
  submitError.value = ''
}

const removeOpen = ref(false)
const removeTarget = ref('')

function askRemove(name: string): void {
  removeTarget.value = name
  removeOpen.value = true
}

function doRemove(): void {
  const name = removeTarget.value
  const next = { ...providersDraft.value }
  delete next[name]
  providersDraft.value = next
  removeOpen.value = false
  savedHint.value = `提供商「${name}」已从草稿移除，点「提交配置」后写回后端。`
  submitError.value = ''
}

/** 一键把某条设为「使用中的提供商」（草稿态，仍需「提交配置」写回后端） */
function setActive(name: string): void {
  form.active_provider = name
  savedHint.value = `「${name}」已设为使用中，点「提交配置」后写回后端并即时生效。`
  submitError.value = ''
}

// ── 维护动作：作用书目 = 顶栏全局作用域（联查时留空 = 活动书目） ──
const compensating = ref(false)
const compensateMsg = ref('')
const compensateError = ref('')
const maintaining = ref(false)
const maintainMode = ref('update')
const maintainMsg = ref('')
const maintainError = ref('')
const logs = ref<LLMCallLog[]>([])
const logsLoading = ref(false)
const logsError = ref('')
const logLimit = ref(50)
const logFull = ref(false)

async function doCompensate(): Promise<void> {
  compensating.value = true
  compensateMsg.value = ''
  compensateError.value = ''
  try {
    const res = await healthApi.compensate(scope.effectiveRepoId.value || undefined)
    compensateMsg.value = res.message || '已触发补偿，积压事件开始重新入队处理'
    message.success('已触发补偿')
  } catch (e) {
    compensateError.value = (e as Error).message
  } finally {
    compensating.value = false
  }
}

async function doMaintain(): Promise<void> {
  maintaining.value = true
  maintainMsg.value = ''
  maintainError.value = ''
  try {
    const res = await healthApi.maintain(maintainMode.value, scope.effectiveRepoId.value || undefined)
    maintainMsg.value = res.message || '已入队图维护'
    message.success('图维护已入队')
  } catch (e) {
    maintainError.value = (e as Error).message
  } finally {
    maintaining.value = false
  }
}

async function loadLogs(): Promise<void> {
  logsLoading.value = true
  logsError.value = ''
  try {
    const res = await healthApi.getAgentLogs(logLimit.value, logFull.value)
    logs.value = res.logs ?? []
  } catch (e) {
    logsError.value = (e as Error).message
    logs.value = []
  } finally {
    logsLoading.value = false
  }
}

function fmtTs(ts: number): string {
  const d = new Date(ts * 1000)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('zh-CN')
}
</script>

<style scoped>
.banner {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-1);
  padding: var(--dpim-space-3);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius-sm);
}
.banner--bad {
  border-color: var(--dpim-danger);
  background: var(--dpim-danger-soft);
}
.banner--ok {
  border-color: var(--dpim-success);
  background: var(--dpim-success-soft);
}
.banner-title {
  margin: 0;
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text);
}
.banner-text {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
  line-height: 1.6;
  word-break: break-word;
}
.banner--bad .banner-text {
  font-family: var(--dpim-font-mono);
  color: var(--dpim-danger);
}
.banner-note {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.6;
}
.banner-fields {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
}
.banner-locked {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-warning);
  line-height: 1.6;
  word-break: break-word;
}
/* 配置来源（只读行）：字段名 + 等宽值 */
.src-row {
  display: flex;
  align-items: baseline;
  gap: var(--dpim-space-3);
}
.src-key {
  flex-shrink: 0;
  width: 84px;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
}
.src-val {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
  word-break: break-all;
}
.mono {
  font-family: var(--dpim-font-mono);
}
.settings-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-3);
}
.settings-scroll > * {
  flex-shrink: 0;
}
.note {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
  line-height: 1.6;
}
.field-error {
  flex-basis: 100%;
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-danger);
  line-height: 1.5;
  word-break: break-word;
}
.ftag {
  color: var(--dpim-primary);
  font-family: var(--dpim-font-mono);
  margin-right: var(--dpim-space-2);
}
.f-number {
  width: 160px;
}
.f-select {
  width: 260px;
}
.f-narrow {
  width: 140px;
}
.prov-block {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-2);
  padding-top: var(--dpim-space-2);
  border-top: var(--dpim-hairline) solid var(--dpim-border);
}
.prov-hint {
  font-size: var(--dpim-fs-xs);
  color: var(--dpim-text-3);
}
.prov-card {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-3);
  padding: var(--dpim-space-2) var(--dpim-space-3);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius-sm);
  background: var(--dpim-inset);
  box-shadow: var(--dpim-inset-shadow);
}
.prov-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-1);
}
.prov-name {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
}
.prov-name-text {
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text);
}
.prov-meta {
  font-size: var(--dpim-fs-xs);
  color: var(--dpim-text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.prov-actions {
  display: flex;
  gap: var(--dpim-space-1);
  flex-shrink: 0;
}
.chip {
  padding: 0 var(--dpim-space-2);
  border-radius: var(--dpim-radius-pill);
  font-size: var(--dpim-fs-xs);
}
.chip--primary {
  background: var(--dpim-primary-soft);
  color: var(--dpim-primary);
}
.chip--bad {
  background: var(--dpim-danger-soft);
  color: var(--dpim-danger);
}
.action-block {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-2);
  padding-bottom: var(--dpim-space-3);
  border-bottom: var(--dpim-hairline) solid var(--dpim-border);
}
.action-block:last-child {
  padding-bottom: 0;
  border-bottom: none;
}
.action-head {
  display: flex;
  align-items: baseline;
  gap: var(--dpim-space-3);
  flex-wrap: wrap;
}
.action-title {
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text);
}
.action-desc {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
}
.action-row {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  flex-wrap: wrap;
}
.action-note {
  font-size: var(--dpim-fs-xs);
  color: var(--dpim-text-3);
}
.action-msg {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  line-height: 1.6;
  word-break: break-word;
}
.action-msg.ok {
  color: var(--dpim-success);
}
.action-msg.bad {
  color: var(--dpim-danger);
}
.log-list {
  max-height: 40vh;
  overflow: auto;
}
.log-head {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  min-width: 0;
}
.log-role {
  padding: 0 var(--dpim-space-2);
  border-radius: var(--dpim-radius-pill);
  background: var(--dpim-primary-soft);
  color: var(--dpim-primary);
  font-size: var(--dpim-fs-xs);
}
.log-role--bad {
  background: var(--dpim-danger-soft);
  color: var(--dpim-danger);
}
.log-model {
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
}
.log-time {
  font-size: var(--dpim-fs-xs);
  color: var(--dpim-text-3);
}
.log-body {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-1);
}
.log-label {
  margin: 0;
  font-size: var(--dpim-fs-xs);
  color: var(--dpim-text-3);
  letter-spacing: 0.05em;
}
.log-text {
  margin: 0;
  padding: var(--dpim-space-2);
  background: var(--dpim-log-bg);
  border-radius: var(--dpim-radius-xs);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-2);
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 30vh;
  overflow: auto;
}
.log-error {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-danger);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.modal-box {
  width: min(720px, calc(100vw - var(--dpim-space-6)));
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-3);
  padding: var(--dpim-space-5);
  background: var(--dpim-surface);
  border: var(--dpim-hairline) solid var(--dpim-border);
  border-radius: var(--dpim-radius);
  box-shadow: var(--dpim-shadow);
}
.modal-title {
  margin: 0;
  font-size: var(--dpim-fs-lg);
  color: var(--dpim-text);
}
.modal-body {
  max-height: 60vh;
  overflow: auto;
}
.modal-error {
  margin: 0;
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-danger);
  word-break: break-word;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--dpim-space-2);
}
</style>
