<template>
  <div class="config-tab">
    <div class="config-scroll">
      <section v-for="sec in sections" :key="sec.name" class="config-section">
        <header class="section-header">
          <span class="section-title">{{ sec.name }}</span>
          <span class="section-count">{{ sec.fields.length }}</span>
        </header>
        <div class="section-body">
          <!-- 提供商表单化管理（取代整块 JSON 暴露）：密钥掩码显示，弹窗逐字段配置 -->
          <div v-if="sec.name === '模型与提供商'" class="prov-block">
            <div class="prov-toolbar">
              <span class="prov-hint">BYOK 注册表 · 密钥掩码显示，编辑留空即保持不变</span>
              <n-button size="tiny" type="primary" ghost @click="openAdd">新增提供商</n-button>
            </div>
            <div v-if="!providerNames.length" class="prov-empty">暂无注册提供商，可点击「新增提供商」添加</div>
            <div v-for="name in providerNames" :key="name" class="prov-card">
              <div class="prov-main">
                <div class="prov-name">{{ name }}</div>
                <div class="prov-meta">{{ providersDraft[name].base_url }}</div>
                <div class="prov-meta">
                  密钥 {{ providersDraft[name].api_key || '（未设置）' }} · {{ providerModels(name).length }} 个模型
                </div>
              </div>
              <div class="prov-actions">
                <n-button size="tiny" @click="openEdit(name)">编辑</n-button>
                <n-button size="tiny" type="error" ghost @click="removeProvider(name)">删除</n-button>
              </div>
            </div>
            <div class="prov-divider"></div>
          </div>
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
              <n-auto-complete
                v-else-if="field.type === 'path'"
                v-model:value="edits[field.key]"
                size="small"
                :options="pathOptions(field.key)"
                :placeholder="String(orig(field.key) ?? '')"
                :input-props="{ autocomplete: 'off' }"
              />
              <n-input v-else-if="field.type === 'password'" v-model:value="edits[field.key]" type="password" show-password-on="click" size="small" :placeholder="passwordPlaceholder(field)" />
              <n-input-number v-else-if="field.type === 'number'" v-model:value="edits[field.key]" size="small" style="width:100%" :min="field.min ?? 0" :max="field.max ?? 9999" />
              <n-select v-else-if="field.type === 'select'" v-model:value="edits[field.key]" :options="field.options" size="small" />
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- 提供商编辑弹窗：逐字段表单（参考主流 AI 平台的 provider 配置交互） -->
    <n-modal v-model:show="showModal" preset="card" :title="editingName ? `编辑提供商 · ${editingName}` : '新增提供商'" class="prov-modal" :mask-closable="false">
      <n-form label-placement="left" label-width="92">
        <n-form-item label="名称">
          <n-input v-if="!editingName" v-model:value="form.name" placeholder="如 siliconflow" />
          <span v-else class="prov-name">{{ editingName }}</span>
        </n-form-item>
        <n-form-item label="Base URL">
          <n-input v-model:value="form.base_url" placeholder="https://api.siliconflow.cn/v1" />
        </n-form-item>
        <n-form-item label="API Key">
          <n-input
            v-model:value="form.api_key"
            type="password"
            show-password-on="click"
            :placeholder="editingName && providersDraft[editingName]?.api_key
              ? `当前 ${providersDraft[editingName].api_key}，留空保持不变`
              : 'sk-...（本地服务可留空）'"
          />
        </n-form-item>
        <n-form-item label="模型列表">
          <n-input v-model:value="form.models_text" type="textarea" :rows="2" placeholder="逗号或换行分隔，如 Qwen3.5-9B, deepseek-v4" />
        </n-form-item>
        <n-form-item label="超时（秒）">
          <n-input-number v-model:value="form.timeout" :min="1" :max="3600" style="width:100%" placeholder="默认 666" />
        </n-form-item>
      </n-form>
      <template #footer>
        <div class="prov-modal-footer">
          <n-button size="small" @click="showModal = false">取消</n-button>
          <n-button size="small" type="primary" @click="saveModal">保存</n-button>
        </div>
      </template>
    </n-modal>

    <div class="config-bottom">
      <n-alert v-if="staleHint" type="warning" closable style="margin-bottom:8px;font-size:12px">{{ staleHint }}</n-alert>
      <n-alert v-if="savedHint" type="info" closable style="margin-bottom:8px;font-size:12px">{{ savedHint }}</n-alert>
      <n-button type="primary" @click="onSubmit" :loading="submitting">提交配置</n-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { createDiscreteApi } from 'naive-ui'
import type { SettingsResponse, HealthResponse } from '@/api/client'
import * as api from '@/api/client'

const { message, dialog } = createDiscreteApi(['message', 'dialog'])

const props = defineProps<{
  health: HealthResponse | null
  validate: () => Promise<boolean>
  onCommitted: () => Promise<void>
}>()

const original = ref<SettingsResponse>({
  memory_db_path: '', graph_json_path: '', llm_base_url: '', llm_api_key: '',
  llm_model_name: '', llm_timeout: 30, llm_max_tokens: null, llm_enable_thinking: null, llm_thinking_budget: null,
  available_providers: ['primary'],
  providers: {},
  active_provider: 'primary',
  available_models: [], active_model: '',
  agent_mode: 'disabled', agent_max_retries: 2, agent_cr_model: '',
  agent_in_model: '', agent_gr_model: '', agent_meta_model: '',
  max_graph_hops: 2, rrf_k: 60,
  jaccard_threshold: 0.85, health_check_interval: 60, health_check_timeout: 60, compensate_batch_size: 20, log_level: 'INFO',
})
const edits = reactive<Record<string, any>>({})

// ── 提供商表单化状态（取代 JSON textarea）──
interface ProviderEntry {
  base_url: string
  api_key: string // 掩码值（来自 GET）或用户新输入的明文
  models?: string[]
  model?: string
  timeout?: number
  [k: string]: unknown // 保留 max_tokens / thinking_style 等厂商适配字段
}
const providersDraft = ref<Record<string, ProviderEntry>>({})
const showModal = ref(false)
const editingName = ref<string | null>(null) // null = 新增
const form = reactive({
  name: '',
  base_url: '',
  api_key: '',
  models_text: '',
  timeout: null as number | null,
})

const providerNames = computed(() => Object.keys(providersDraft.value).sort())

function providerModels(name: string): string[] {
  const entry = providersDraft.value[name]
  if (!entry) return []
  const list = Array.isArray(entry.models) ? entry.models : (entry.model ? [entry.model] : [])
  return list.map(String).filter(Boolean)
}

function openAdd() {
  editingName.value = null
  form.name = ''
  form.base_url = ''
  form.api_key = ''
  form.models_text = ''
  form.timeout = null
  showModal.value = true
}

function openEdit(name: string) {
  const entry = providersDraft.value[name] ?? { base_url: '', api_key: '' }
  editingName.value = name
  form.name = name
  form.base_url = String(entry.base_url ?? '')
  form.api_key = '' // 不回填密钥（避免明文/掩码误提交），留空 = 保持不变
  form.models_text = providerModels(name).join(', ')
  form.timeout = typeof entry.timeout === 'number' ? entry.timeout : null
  showModal.value = true
}

function saveModal() {
  const key = editingName.value
  const name = (key ?? form.name).trim()
  if (!name) { message.error('请填写提供商名称'); return }
  if (!key && providersDraft.value[name]) { message.error(`名称「${name}」已存在`); return }
  if (!form.base_url.trim()) { message.error('请填写 Base URL'); return }
  const models = form.models_text.split(/[,，\n]/).map(s => s.trim()).filter(Boolean)
  // 保留原有厂商适配字段，仅覆盖表单管理的四项
  const entry: ProviderEntry = key
    ? { ...providersDraft.value[key] }
    : { base_url: '', api_key: '' }
  entry.base_url = form.base_url.trim()
  // 编辑留空 = 回传原掩码值（后端识别为「保持现值」）；新增留空 = 未设置密钥
  entry.api_key = form.api_key.trim() || (key ? String(providersDraft.value[key]?.api_key ?? '') : '')
  if (models.length) entry.models = models
  else delete entry.models
  if (form.timeout != null) entry.timeout = form.timeout
  else delete entry.timeout
  providersDraft.value[name] = entry
  showModal.value = false
}

function removeProvider(name: string) {
  dialog.warning({
    title: '删除提供商',
    content: `确认从注册表移除「${name}」？提交配置后生效。`,
    positiveText: '移除',
    negativeText: '取消',
    onPositiveClick() { delete providersDraft.value[name] },
  })
}

/** 安全读取配置项现值（field.key 为动态字符串） */
function orig(key: string): unknown {
  return (original.value as Record<string, unknown>)[key]
}

/** 当前值显示文本 */
function currentText(field: ConfigField): string {
  if (field.key === 'backend_url') return backendUrl.value
  const v = orig(field.key)
  return v == null || v === '' ? '—' : String(v)
}
function currentTitle(field: ConfigField): string {
  return currentText(field)
}
/** 密码字段输入框提示：显示当前掩码，留空保持不变 */
function passwordPlaceholder(field: ConfigField): string {
  const cur = orig(field.key)
  return cur ? `当前 ${String(cur)}，留空保持不变` : '未设置，可输入新密钥'
}
const backendUrl = ref('http://localhost:8000')
const submitting = ref(false)
const staleHint = ref('')
const savedHint = ref('')

interface ConfigField {
  key: string
  label: string
  type: 'text' | 'password' | 'number' | 'select' | 'path'
  section?: string
  min?: number
  max?: number
  placeholder?: string
  options?: Array<{ label: string; value: string }>
}

// 活动提供商下拉选项：来自后端 available_providers（含 'primary' + 注册的 provider）
const providerOptions = computed(() =>
  (original.value.available_providers ?? ['primary']).map(p => ({
    label: p === 'primary' ? 'primary（环境变量主配置）' : p,
    value: p,
  })),
)

// 使用模型下拉选项：按「用户当前选择的提供商」从 providersDraft 取模型列表
// （切换提供商或编辑提供商后立即生效，不依赖后端旧缓存）；
// primary 回退环境变量主模型；取不到时用后端 available_models 兜底
const modelOptions = computed(() => {
  const provider = String(edits['active_provider'] ?? original.value.active_provider ?? 'primary')
  let models: string[] = []
  if (provider === 'primary') {
    models = [original.value.llm_model_name].filter(Boolean)
  } else {
    const entry = providersDraft.value[provider]
    if (entry) models = providerModels(provider)
  }
  if (models.length === 0) models = (original.value.available_models ?? []).slice()
  return models.map(m => ({ label: m, value: m }))
})

// 切换提供商时：若当前「使用模型」不在新提供商列表内则清空，避免提交陈旧值
watch(
  () => edits['active_provider'],
  () => {
    const cur = String(edits['active_model'] ?? '')
    if (cur && !modelOptions.value.some(o => o.value === cur)) {
      edits['active_model'] = ''
    }
  },
)

// Agent 角色模型下拉选项：空 = 跟随使用模型；其余为当前提供商模型列表
// （后端语义：agent_*_model 在活动提供商上使用该模型，故选项随提供商联动；
//   当前值不在列表时追加显示，避免历史手填值丢失）
function roleModelOptions(key: string): Array<{ label: string; value: string }> {
  const opts = modelOptions.value.map(o => ({ ...o }))
  const cur = String(edits[key] ?? '')
  if (cur && !opts.some(o => o.value === cur)) opts.push({ label: cur, value: cur })
  return [{ label: '（跟随使用模型）', value: '' }, ...opts]
}

const fields = computed<ConfigField[]>(() => [
  { key: 'memory_db_path', label: '记忆库路径', type: 'path', section: '存储' },
  { key: 'graph_json_path', label: '图谱文件路径', type: 'path', section: '存储' },
  { key: 'active_provider', label: '活动提供商', type: 'select', options: providerOptions.value, section: '模型与提供商' },
  { key: 'active_model', label: '使用模型', type: 'select', options: modelOptions.value, section: '模型与提供商' },
  { key: 'llm_max_tokens', label: '输出上限 tokens（0=服务端默认）', type: 'number', min: 0, max: 32768, section: '模型与提供商' },
  { key: 'llm_thinking_budget', label: '思考预算 tokens（0=不设）', type: 'number', min: 0, max: 32768, section: '模型与提供商' },
  { key: 'agent_mode', label: 'Agent 管线模式', type: 'select', section: 'Agent 管线', options: [
    { label: 'disabled（默认）', value: 'disabled' },
    { label: 'pipeline（四 Agent 管线）', value: 'pipeline' },
  ]},
  { key: 'agent_max_retries', label: 'Agent 最大修正轮次', type: 'number', min: 0, max: 10, section: 'Agent 管线' },
  { key: 'agent_cr_model', label: 'Cr 模型', type: 'select', options: roleModelOptions('agent_cr_model'), section: 'Agent 管线' },
  { key: 'agent_in_model', label: 'In 模型', type: 'select', options: roleModelOptions('agent_in_model'), section: 'Agent 管线' },
  { key: 'agent_gr_model', label: 'Gr 模型', type: 'select', options: roleModelOptions('agent_gr_model'), section: 'Agent 管线' },
  { key: 'agent_meta_model', label: 'Meta 模型', type: 'select', options: roleModelOptions('agent_meta_model'), section: 'Agent 管线' },
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

// ── 存储路径历史记忆（localStorage，浏览器本地；不涉及后端） ──
// 有效性闭环：当前生效路径（后端正在使用）必入历史；PUT 成功的路径入史置顶；
// 提交失败的路径若在历史中则移除——「无效的不显示」。上限 8 条，超出淘汰最旧。
const PATH_KEYS = ['memory_db_path', 'graph_json_path'] as const
const PATH_HISTORY_STORE: Record<string, string> = {
  memory_db_path: 'dpim_path_history_db',
  graph_json_path: 'dpim_path_history_graph',
}
const PATH_HISTORY_MAX = 8
const pathHistories = ref<Record<string, string[]>>({ memory_db_path: [], graph_json_path: [] })

function loadPathHistory(key: string): string[] {
  try {
    const raw = localStorage.getItem(PATH_HISTORY_STORE[key])
    const list = raw ? JSON.parse(raw) : []
    return Array.isArray(list) ? list.filter(p => typeof p === 'string' && p.trim()) : []
  } catch { return [] }
}
function savePathHistory(key: string, list: string[]) {
  localStorage.setItem(PATH_HISTORY_STORE[key], JSON.stringify(list.slice(0, PATH_HISTORY_MAX)))
}
/** 当前生效路径并入历史首位（后端正在使用 = 已验证有效） */
function mergeCurrentIntoHistory() {
  for (const k of PATH_KEYS) {
    const cur = String(original.value[k as keyof SettingsResponse] ?? '').trim()
    const list = loadPathHistory(k).filter(p => p !== cur)
    pathHistories.value[k] = cur ? [cur, ...list].slice(0, PATH_HISTORY_MAX) : list.slice(0, PATH_HISTORY_MAX)
    savePathHistory(k, pathHistories.value[k])
  }
}
/** 提交结果回写历史：成功置顶去重；失败移除（路径失效/不可用即不再显示） */
function commitPathHistory(changed: Record<string, any>, ok: boolean) {
  for (const k of PATH_KEYS) {
    const val = String(changed[k] ?? '').trim()
    if (!val) continue
    let list = loadPathHistory(k)
    list = ok
      ? [val, ...list.filter(p => p !== val)].slice(0, PATH_HISTORY_MAX)
      : list.filter(p => p !== val)
    pathHistories.value[k] = list
    savePathHistory(k, list)
  }
}
/** auto-complete 选项：当前生效路径带「（当前）」标记 */
function pathOptions(key: string): Array<{ label: string; value: string }> {
  const cur = String(original.value[key as keyof SettingsResponse] ?? '').trim()
  return pathHistories.value[key].map(p => ({ label: p === cur ? `${p}（当前）` : p, value: p }))
}

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
  providersDraft.value = JSON.parse(JSON.stringify(original.value.providers ?? {}))
  for (const f of fields.value) {
    if (f.key === 'backend_url') continue
    if (f.type === 'password') {
      // 密钥类字段：不回填（后端下发的是掩码），留空 = 保持不变
      edits[f.key] = ''
      continue
    }
    // number 字段用 null 表示「未设置」（后端可空数字），避免空串 '' 提交后触发 422
    edits[f.key] = f.type === 'number'
      ? (original.value[f.key as keyof SettingsResponse] ?? null)
      : (original.value[f.key as keyof SettingsResponse] ?? '')
  }
  mergeCurrentIntoHistory()
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
  const changed: Record<string, any> = {}
  try {
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
      if (f.type === 'password') {
        // 密钥类字段：留空 = 保持不变，不提交
        if (String(edits[f.key] ?? '') !== '') {
          changed[f.key] = edits[f.key]
        }
        continue
      }
      if (String(edits[f.key]) !== String(original.value[f.key as keyof SettingsResponse])) {
        changed[f.key] = edits[f.key]
      }
    }
    // providers 草稿与基准（掩码版）不一致 → 提交（掩码回传由后端幂等保留）
    if (JSON.stringify(providersDraft.value) !== JSON.stringify(original.value.providers ?? {})) {
      changed.providers = providersDraft.value
    }
    if (Object.keys(changed).length === 0) {
      savedHint.value = '没有需要保存的修改'
      return
    }
    await api.putSettings(changed)
    commitPathHistory(changed, true)
    savedHint.value = '配置已保存（部分项需重启生效）'
    await props.onCommitted()
    await load()
  } catch (e: any) {
    commitPathHistory(changed, false)  // 提交失败的路径若在历史中则移除（无效不显示）
    staleHint.value = e.message
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.config-tab { flex: 1; display: flex; flex-direction: column; min-height: 0; padding: 16px 24px 12px; }
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

/* ── 提供商管理块 ── */
.prov-block { padding: 6px 0 10px; }
.prov-toolbar {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 6px 0 8px;
}
.prov-hint { font-size: 11px; color: var(--dpim-text-3, #7c8694); }
.prov-empty {
  font-size: 12px; color: var(--dpim-text-3, #7c8694);
  padding: 10px 0; text-align: center;
  border: 1px dashed var(--dpim-border, rgba(255,255,255,0.12));
  border-radius: 8px;
}
.prov-card {
  display: flex; align-items: center; gap: 12px;
  padding: 8px 10px; margin-bottom: 6px;
  border: 1px solid var(--dpim-border, rgba(255,255,255,0.09));
  border-radius: 8px;
  background: var(--dpim-surface-2, rgba(255,255,255,0.02));
}
.prov-main { flex: 1; min-width: 0; }
.prov-name { font-size: 13px; font-weight: 600; color: var(--dpim-text, #e6edf3); }
.prov-meta {
  font-size: 11px; color: var(--dpim-text-3, #7c8694);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-family: 'Cascadia Code', Consolas, monospace;
}
.prov-actions { display: flex; gap: 6px; flex-shrink: 0; }
.prov-divider { border-bottom: 1px dashed var(--dpim-border, rgba(255,255,255,0.07)); margin-top: 4px; }
.prov-modal { max-width: 480px; }
.prov-modal-footer { display: flex; justify-content: flex-end; gap: 8px; }

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
