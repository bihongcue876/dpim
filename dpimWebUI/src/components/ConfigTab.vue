<template>
  <div class="config-tab">
    <div class="config-scroll">
      <section v-for="sec in sections" :key="sec.name" class="config-section">
        <header class="section-header">
          <span class="section-title">{{ sec.name }}</span>
          <span class="section-count">{{ sec.fields.length }}</span>
        </header>
        <div class="section-body">
          <div v-for="field in sec.fields" :key="field.key" class="config-row">
            <span class="cf-name">{{ field.label }}</span>
            <span class="cf-current" :title="currentTitle(field)">{{ currentText(field) }}</span>
            <div class="cf-edit">
              <template v-if="field.key === 'backend_url'">
                <n-input v-model:value="backendUrl" size="small" placeholder="http://localhost:8000" />
              </template>
              <template v-else-if="field.type === 'text'">
                <n-input v-model:value="edits[field.key]" size="small" :placeholder="String(orig(field.key) ?? '')" />
              </template>
              <n-input v-else-if="field.type === 'password'" v-model:value="edits[field.key]" type="password" size="small" placeholder="••••••" />
              <n-input-number v-else-if="field.type === 'number'" v-model:value="edits[field.key]" size="small" style="width:100%" :min="field.min ?? 0" :max="field.max ?? 9999" />
              <n-select v-else-if="field.type === 'select'" v-model:value="edits[field.key]" :options="field.options" size="small" />
              <n-input v-else-if="field.type === 'json'" v-model:value="edits[field.key]" type="textarea" :rows="5" size="small" placeholder='{"provider名": {"base_url": "...", "api_key": "...", "models": ["模型1", "模型2"], "timeout": 120}}' style="font-family: Consolas, monospace" />
            </div>
          </div>
        </div>
      </section>
    </div>
    <div class="config-bottom">
      <n-alert v-if="staleHint" type="warning" closable style="margin-bottom:8px;font-size:12px">{{ staleHint }}</n-alert>
      <n-alert v-if="savedHint" type="info" closable style="margin-bottom:8px;font-size:12px">{{ savedHint }}</n-alert>
      <n-button type="primary" @click="onSubmit" :loading="submitting">提交配置</n-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import type { SettingsResponse, HealthResponse } from '@/api/client'
import * as api from '@/api/client'

const props = defineProps<{
  health: HealthResponse | null
  validate: () => Promise<boolean>
  onCommitted: () => Promise<void>
}>()

const original = ref<SettingsResponse>({
  memory_db_path: '', graph_json_path: '', llm_base_url: '', llm_api_key: '',
  llm_model_name: '', llm_timeout: 30, available_providers: ['primary'],
  providers: {},
  active_provider: 'primary',
  available_models: [], active_model: '',
  agent_mode: 'disabled', agent_max_retries: 2, agent_cr_model: '',
  agent_in_model: '', agent_gr_model: '', agent_meta_model: '',
  max_graph_hops: 2, rrf_k: 60,
  jaccard_threshold: 0.85, health_check_interval: 60, health_check_timeout: 60, compensate_batch_size: 20, log_level: 'INFO',
})
const edits = reactive<Record<string, any>>({})

/** 安全读取配置项现值（field.key 为动态字符串） */
function orig(key: string): unknown {
  return (original.value as Record<string, unknown>)[key]
}

/** 当前值显示文本（JSON 字段显示概要） */
function currentText(field: ConfigField): string {
  if (field.key === 'backend_url') return backendUrl.value
  if (field.type === 'json') return summaryJson(orig(field.key))
  const v = orig(field.key)
  return v == null || v === '' ? '—' : String(v)
}
function currentTitle(field: ConfigField): string {
  if (field.type === 'json') return String(orig(field.key) ?? '')
  return currentText(field)
}
function summaryJson(v: unknown): string {
  if (v && typeof v === 'object') {
    const keys = Object.keys(v as Record<string, unknown>)
    return keys.length ? `${keys.length} 个提供商` : '{}'
  }
  return String(v ?? '—')
}
const backendUrl = ref('http://localhost:8000')
const submitting = ref(false)
const staleHint = ref('')
const savedHint = ref('')

interface ConfigField {
  key: string
  label: string
  type: 'text' | 'password' | 'number' | 'select' | 'json'
  section?: string
  min?: number
  max?: number
  options?: Array<{ label: string; value: string }>
}

// 活动提供商下拉选项：来自后端 available_providers（含 'primary' + 注册的 provider）
const providerOptions = computed(() =>
  (original.value.available_providers ?? ['primary']).map(p => ({
    label: p === 'primary' ? 'primary（环境变量主配置）' : p,
    value: p,
  })),
)

// 使用模型下拉选项：来自后端 available_models（活动 provider 的模型列表）
const modelOptions = computed(() =>
  (original.value.available_models ?? []).map(m => ({ label: m, value: m })),
)

const fields = computed<ConfigField[]>(() => [
  { key: 'memory_db_path', label: '记忆库路径', type: 'text', section: '存储' },
  { key: 'graph_json_path', label: '图谱文件路径', type: 'text', section: '存储' },
  { key: 'providers', label: '提供商注册表(JSON)', type: 'json', section: '模型与提供商' },
  { key: 'active_provider', label: '活动提供商', type: 'select', options: providerOptions.value, section: '模型与提供商' },
  { key: 'active_model', label: '使用模型', type: 'select', options: modelOptions.value, section: '模型与提供商' },
  { key: 'agent_mode', label: 'Agent 管线模式', type: 'select', section: 'Agent 管线', options: [
    { label: 'disabled（默认）', value: 'disabled' },
    { label: 'pipeline（四 Agent 管线）', value: 'pipeline' },
  ]},
  { key: 'agent_max_retries', label: 'Agent 最大修正轮次', type: 'number', min: 0, max: 10, section: 'Agent 管线' },
  { key: 'agent_cr_model', label: 'Cr 模型（空=活动提供商）', type: 'text', section: 'Agent 管线' },
  { key: 'agent_in_model', label: 'In 模型（空=活动提供商）', type: 'text', section: 'Agent 管线' },
  { key: 'agent_gr_model', label: 'Gr 模型（空=活动提供商）', type: 'text', section: 'Agent 管线' },
  { key: 'agent_meta_model', label: 'Meta 模型（空=活动提供商）', type: 'text', section: 'Agent 管线' },
  { key: 'max_graph_hops', label: '图谱最大跳数', type: 'number', min: 1, max: 5, section: '检索' },
  { key: 'rrf_k', label: 'RRF 参数 K', type: 'number', min: 1, max: 200, section: '检索' },
  { key: 'jaccard_threshold', label: '杰卡德阈值', type: 'number', min: 0, max: 1, section: '检索' },
  { key: 'health_check_interval', label: '健康检查间隔（秒）', type: 'number', min: 10, max: 600, section: '系统' },
  { key: 'health_check_timeout', label: '健康检查超时（秒）', type: 'number', min: 10, max: 600, section: '系统' },
  { key: 'compensate_batch_size', label: '补偿批处理大小', type: 'number', min: 5, max: 100, section: '系统' },
  { key: 'log_level', label: '日志级别', type: 'select', section: '系统', options: [
    { label: 'DEBUG', value: 'DEBUG' }, { label: 'INFO', value: 'INFO' },
    { label: 'WARNING', value: 'WARNING' }, { label: 'ERROR', value: 'ERROR' },
  ]},
  { key: 'backend_url', label: '后端地址', type: 'text', section: '前端' },
])

// 按板块分组渲染，保持固定顺序
const sections = computed(() => {
  const order = ['存储', '模型与提供商', 'Agent 管线', '检索', '系统', '前端']
  const groups: Record<string, ConfigField[]> = {}
  for (const f of fields.value) {
    const s = f.section ?? '其他'
    if (!groups[s]) groups[s] = []
    groups[s].push(f)
  }
  return order.filter(s => groups[s]).map(s => ({ name: s, fields: groups[s] }))
})

async function refreshOriginal() {
  // 只刷新后端最新值（显示 + 比较基准），不重置用户编辑
  try {
    original.value = { ...(await api.getSettings()) }
    backendUrl.value = localStorage.getItem('dpim_backend_url') || 'http://localhost:8000'
  } catch { /* ignore */ }
}

async function load() {
  // 初次加载 / 提交成功后：刷新基准并初始化编辑框
  await refreshOriginal()
  for (const f of fields.value) {
    if (f.key === 'backend_url') continue
    if (f.type === 'json') {
      edits[f.key] = JSON.stringify(original.value[f.key as keyof SettingsResponse] ?? {}, null, 2)
      continue
    }
    edits[f.key] = original.value[f.key as keyof SettingsResponse] ?? ''
  }
}

onMounted(load)

async function onSubmit() {
  staleHint.value = ''
  savedHint.value = ''

  // 校验 key
  const ok = await props.validate()
  if (!ok) {
    staleHint.value = '数据已变更，已刷新最新值。请重新确认修改后再次提交。'
    await refreshOriginal()  // 只刷新基准，保留用户已有编辑，可再次提交
    return
  }

  // key 一致，提交
  submitting.value = true
  try {
    const changed: Record<string, any> = {}
    for (const f of fields.value) {
      if (f.key === 'backend_url') {
        // 前端本地配置，不提交到后端 API
        const newUrl = backendUrl.value.trim()
        const oldUrl = localStorage.getItem('dpim_backend_url') || 'http://localhost:8000'
        if (newUrl !== oldUrl) {
          localStorage.setItem('dpim_backend_url', newUrl)
          savedHint.value = '后端地址已更新，下次请求将使用新地址'
        }
        continue
      }
      if (f.type === 'json') {
        // JSON 字段：解析后按对象比较
        let parsed: unknown
        try { parsed = JSON.parse(String(edits[f.key] ?? '{}')) }
        catch { continue }  // 无效 JSON 不提交
        const origVal = original.value[f.key as keyof SettingsResponse] ?? {}
        if (JSON.stringify(parsed) !== JSON.stringify(origVal)) {
          changed[f.key] = parsed
        }
        continue
      }
      if (String(edits[f.key]) !== String(original.value[f.key as keyof SettingsResponse])) {
        changed[f.key] = edits[f.key]
      }
    }
    if (Object.keys(changed).length === 0) {
      savedHint.value = '没有需要保存的修改'
      return
    }
    await api.putSettings(changed)
    savedHint.value = '配置已保存（部分项需重启生效）'
    await props.onCommitted()
    await load()
  } catch (e: any) {
    staleHint.value = e.message
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.config-tab { height: 100%; display: flex; flex-direction: column; padding: 16px 24px 12px; }
.config-scroll { flex: 1; overflow-y: auto; min-height: 0; padding-right: 4px; }

.config-section {
  margin-bottom: 18px;
  border: 1px solid var(--dpim-border, rgba(255,255,255,0.09));
  border-radius: var(--dpim-radius, 12px);
  background: var(--dpim-surface, #161b22);
  overflow: hidden;
}
.section-header {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 16px;
  background: var(--dpim-surface-2, #1c2230);
  border-bottom: 1px solid var(--dpim-border, rgba(255,255,255,0.09));
}
.section-title { font-size: 13px; font-weight: 600; color: var(--dpim-text, #e6edf3); letter-spacing: 0.3px; }
.section-count {
  font-size: 11px; color: var(--dpim-text-3, #7c8694);
  background: rgba(255,255,255,0.06); padding: 0 8px; border-radius: 999px;
}
.section-body { padding: 4px 16px 8px; }

.config-row {
  display: flex; align-items: center; gap: 12px; padding: 7px 0;
  border-bottom: 1px dashed var(--dpim-border, rgba(255,255,255,0.07));
  font-size: 13px;
}
.config-row:last-child { border-bottom: none; }
.cf-name { flex: 0 0 200px; color: var(--dpim-text-2, #aab4c0); }
.cf-current {
  flex: 0 1 300px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: 12px; font-family: 'Cascadia Code', Consolas, monospace; color: var(--dpim-text-3, #7c8694);
}
.cf-edit { flex: 1 1 220px; min-width: 140px; }
.cf-edit :deep(input),
.cf-edit :deep(textarea),
.cf-edit :deep(.n-base-selection-input__input) {
  font-family: 'Cascadia Code', Consolas, monospace;
}
.config-bottom { flex-shrink: 0; padding: 12px 0 0; }
</style>
