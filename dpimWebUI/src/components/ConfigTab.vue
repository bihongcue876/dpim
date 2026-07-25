<template>
  <div class="config-tab">
    <div class="config-table">
      <div class="config-header">
        <span class="ch-name">参数名</span>
        <span class="ch-current">现有值</span>
        <span class="ch-edit">修改</span>
      </div>
      <div v-for="field in fields" :key="field.key" class="config-row">
        <span class="cf-name">{{ field.label }}</span>
        <span class="cf-current" :title="String(original[field.key] ?? '')">{{ original[field.key] ?? '—' }}</span>
        <div class="cf-edit">
          <n-input v-if="field.type === 'text'" v-model:value="edits[field.key]" size="small" :placeholder="String(original[field.key] ?? '')" />
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
import { ref, reactive, onMounted } from 'vue'
import type { SettingsResponse, HealthResponse } from '@/api/client'
import * as api from '@/api/client'

const props = defineProps<{
  health: HealthResponse | null
  validate: () => Promise<boolean>
  onCommitted: () => Promise<void>
}>()

const original = ref<SettingsResponse>({
  memory_db_path: '', graph_json_path: '', llm_base_url: '', llm_api_key: '',
  llm_model_name: '', llm_timeout: 30, max_graph_hops: 2, rrf_k: 60,
  jaccard_threshold: 0.85, health_check_interval: 60, compensate_batch_size: 20, log_level: 'INFO',
})
const edits = reactive<Record<string, any>>({})
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

const fields: ConfigField[] = [
  { key: 'memory_db_path', label: 'MEMORY_DB_PATH', type: 'text' },
  { key: 'graph_json_path', label: 'GRAPH_JSON_PATH', type: 'text' },
  { key: 'llm_base_url', label: 'LLM_BASE_URL', type: 'text' },
  { key: 'llm_api_key', label: 'LLM_API_KEY', type: 'password' },
  { key: 'llm_model_name', label: 'LLM_MODEL_NAME', type: 'text' },
  { key: 'llm_timeout', label: 'LLM_TIMEOUT', type: 'number', min: 5, max: 300 },
  { key: 'max_graph_hops', label: 'MAX_GRAPH_HOPS', type: 'number', min: 1, max: 5 },
  { key: 'rrf_k', label: 'RRF_K', type: 'number', min: 1, max: 200 },
  { key: 'jaccard_threshold', label: 'JACCARD_THRESHOLD', type: 'number', min: 0, max: 1 },
  { key: 'health_check_interval', label: 'HEALTH_CHECK_INTERVAL', type: 'number', min: 10, max: 600 },
  { key: 'compensate_batch_size', label: 'COMPENSATE_BATCH_SIZE', type: 'number', min: 5, max: 100 },
  { key: 'log_level', label: 'LOG_LEVEL', type: 'select', options: [
    { label: 'DEBUG', value: 'DEBUG' }, { label: 'INFO', value: 'INFO' },
    { label: 'WARNING', value: 'WARNING' }, { label: 'ERROR', value: 'ERROR' },
  ]},
]

async function load() {
  try {
    original.value = { ...(await api.getSettings()) }
    // 用现有值初始化编辑框，以便用户看到在哪里修改
    for (const f of fields) {
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
    for (const f of fields) {
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
  display: flex; align-items: center; gap: 8px; padding: 6px 0;
  border-bottom: 1px solid var(--n-border-color);
  font-size: 13px;
}
.config-header { font-weight: 600; position: sticky; top: 0; background: var(--n-color); z-index: 1; }
.ch-name, .cf-name { width: 200px; flex-shrink: 0; }
.ch-current, .cf-current { width: 240px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: monospace; font-size: 12px; }
.ch-edit, .cf-edit { flex: 1; }
.config-bottom { flex-shrink: 0; padding: 12px 0; }
</style>
