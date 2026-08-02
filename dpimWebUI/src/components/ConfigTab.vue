<template>
  <div class="config-tab">
    <div class="config-table">
      <div class="config-header">
        <span class="ch-name">配置项名</span>
        <span class="ch-current">现有参数</span>
        <span class="ch-edit">修改</span>
      </div>
      <div v-for="field in fields" :key="field.key" class="config-row">
        <span class="cf-name">{{ field.label }}</span>
        <span class="cf-current" :title="field.key === 'backend_url' ? backendUrl : String(orig(field.key) ?? '')">{{ field.key === 'backend_url' ? backendUrl : (orig(field.key) ?? '—') }}</span>
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
        </div>
      </div>
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
  active_provider: 'primary',
  agent_mode: 'disabled', agent_max_retries: 2, agent_cr_model: '',
  agent_in_model: '', agent_gr_model: '', agent_meta_model: '',
  max_graph_hops: 2, rrf_k: 60,
  jaccard_threshold: 0.85, health_check_interval: 60, compensate_batch_size: 20, log_level: 'INFO',
})
const edits = reactive<Record<string, any>>({})

/** 安全读取配置项现值（field.key 为动态字符串） */
function orig(key: string): unknown {
  return (original.value as Record<string, unknown>)[key]
}
const backendUrl = ref('http://localhost:8000')
const submitting = ref(false)
const staleHint = ref('')
const savedHint = ref('')

interface ConfigField {
  key: string
  label: string
  type: 'text' | 'password' | 'number' | 'select'
  min?: number
  max?: number
  options?: Array<{ label: string; value: string }>
}

// 活动提供商下拉选项：来自后端 available_providers（含 'primary' + 注册的 provider）
const providerOptions = computed(() =>
  (original.value.available_providers ?? ['primary']).map(p => ({
    label: p === 'primary' ? 'primary（DPIM_LLM_* 主配置）' : p,
    value: p,
  })),
)

const fields = computed<ConfigField[]>(() => [
  { key: 'memory_db_path', label: '记忆库路径', type: 'text' },
  { key: 'graph_json_path', label: '图谱文件路径', type: 'text' },
  { key: 'llm_base_url', label: 'LLM 地址', type: 'text' },
  { key: 'llm_api_key', label: 'LLM API 密钥', type: 'password' },
  { key: 'llm_model_name', label: 'LLM 模型名称', type: 'text' },
  { key: 'llm_timeout', label: 'LLM 超时（秒）', type: 'number', min: 5, max: 300 },
  { key: 'active_provider', label: '活动提供商', type: 'select', options: providerOptions.value },
  { key: 'agent_mode', label: 'Agent 管线模式', type: 'select', options: [
    { label: 'disabled（默认）', value: 'disabled' },
    { label: 'pipeline（四 Agent 管线）', value: 'pipeline' },
  ]},
  { key: 'agent_max_retries', label: 'Agent 最大修正轮次', type: 'number', min: 0, max: 10 },
  { key: 'agent_cr_model', label: 'Cr 模型（空=活动提供商）', type: 'text' },
  { key: 'agent_in_model', label: 'In 模型（空=活动提供商）', type: 'text' },
  { key: 'agent_gr_model', label: 'Gr 模型（空=活动提供商）', type: 'text' },
  { key: 'agent_meta_model', label: 'Meta 模型（空=活动提供商）', type: 'text' },
  { key: 'max_graph_hops', label: '图谱最大跳数', type: 'number', min: 1, max: 5 },
  { key: 'rrf_k', label: 'RRF 参数 K', type: 'number', min: 1, max: 200 },
  { key: 'jaccard_threshold', label: '杰卡德阈值', type: 'number', min: 0, max: 1 },
  { key: 'health_check_interval', label: '健康检查间隔（秒）', type: 'number', min: 10, max: 600 },
  { key: 'compensate_batch_size', label: '补偿批处理大小', type: 'number', min: 5, max: 100 },
  { key: 'log_level', label: '日志级别', type: 'select', options: [
    { label: 'DEBUG', value: 'DEBUG' }, { label: 'INFO', value: 'INFO' },
    { label: 'WARNING', value: 'WARNING' }, { label: 'ERROR', value: 'ERROR' },
  ]},
  { key: 'backend_url', label: '后端地址', type: 'text' },
])

async function load() {
  try {
    original.value = { ...(await api.getSettings()) }
    // 读取前端本地配置（后端地址）
    backendUrl.value = localStorage.getItem('dpim_backend_url') || 'http://localhost:8000'
    // 用现有值初始化编辑框，以便用户看到在哪里修改
    for (const f of fields.value) {
      if (f.key === 'backend_url') continue
      edits[f.key] = original.value[f.key as keyof SettingsResponse] ?? ''
    }
  } catch { /* ignore */ }
}

onMounted(load)

async function onSubmit() {
  staleHint.value = ''
  savedHint.value = ''

  // 校验 key
  const ok = await props.validate()
  if (!ok) {
    staleHint.value = '数据已变更，已刷新最新值。请重新确认修改后再次提交。'
    await load()  // 刷新最新值，但保留用户已有编辑（edits对象不重置）
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
.config-tab { height: 100%; display: flex; flex-direction: column; padding: 12px 24px; }
.config-table { flex: 1; overflow-y: auto; }
.config-header, .config-row {
  display: flex; align-items: center; gap: 8px; padding: 4px 0;
  border-bottom: 1px solid var(--n-border-color);
  font-size: 13px;
}
.config-header { font-weight: 600; position: sticky; top: 0; background: var(--n-color); z-index: 1; }
.ch-name, .cf-name { flex: 0 0 160px; }
.ch-current, .cf-current { flex: 0 1 320px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; font-family: 'Consolas', 'Cascadia Code', 'Fira Code', monospace; color: #999; }
.cf-edit :deep(input),
.cf-edit :deep(textarea),
.cf-edit :deep(.n-base-selection-input__input),
.cf-edit :deep(.n-select-menu-item) {
  font-family: 'Consolas', 'Cascadia Code', 'Fira Code', monospace;
}
.ch-edit, .cf-edit { flex: 1 1 200px; min-width: 120px; }
.config-bottom { flex-shrink: 0; padding: 12px 0; }
</style>
