<template>
  <div class="right-panel">
    <!-- 配置视图（无选中时默认显示） -->
    <template v-if="view === 'config'">
      <h4>系统配置</h4>
      <n-form size="small" label-placement="left" label-width="150">
        <n-form-item label="LLM 地址">
          <n-input v-model:value="localSettings.llm_base_url" />
        </n-form-item>
        <n-form-item label="API Key">
          <n-input v-model:value="localSettings.llm_api_key" type="password" />
        </n-form-item>
        <n-form-item label="模型名称">
          <n-input v-model:value="localSettings.llm_model_name" />
        </n-form-item>
        <n-form-item label="超时(秒)">
          <n-input-number v-model:value="localSettings.llm_timeout" :min="5" :max="300" />
        </n-form-item>
        <n-form-item label="图扩散跳数">
          <n-input-number v-model:value="localSettings.max_graph_hops" :min="1" :max="5" />
        </n-form-item>
        <n-form-item label="RRF k值">
          <n-input-number v-model:value="localSettings.rrf_k" :min="1" :max="200" />
        </n-form-item>
        <n-form-item label="Jaccard 阈值">
          <n-input-number v-model:value="localSettings.jaccard_threshold" :min="0" :max="1" :step="0.01" />
        </n-form-item>
        <n-form-item label="健康检查间隔(秒)">
          <n-input-number v-model:value="localSettings.health_check_interval" :min="10" :max="600" />
        </n-form-item>
        <n-form-item label="补偿批次">
          <n-input-number v-model:value="localSettings.compensate_batch_size" :min="5" :max="100" />
        </n-form-item>
        <n-form-item label="日志级别">
          <n-select v-model:value="localSettings.log_level" :options="logLevelOptions" />
        </n-form-item>
      </n-form>
      <n-button size="small" type="primary" :disabled="locked" @click="$emit('save-settings', localSettings)">保存配置</n-button>
      <n-alert v-if="savedHint" type="info" closable style="margin-top:8px;font-size:12px">{{ savedHint }}</n-alert>

      <n-divider />

      <h4>创建节点</h4>
      <n-form size="small" label-placement="top">
        <n-form-item label="标题">
          <n-input v-model:value="newNodeTitle" placeholder="节点标题（必填）" />
        </n-form-item>
        <n-form-item label="内容">
          <n-input v-model:value="newNodeContent" type="textarea" placeholder="节点内容" />
        </n-form-item>
        <n-form-item label="类型">
          <n-select v-model:value="newNodeType" :options="[
            { label: 'interaction', value: 'interaction' },
            { label: 'data', value: 'data' },
          ]" />
        </n-form-item>
        <n-form-item label="源证事件 ID（可选）">
          <n-input v-model:value="newNodeEventId" placeholder="关联的事件 ID" />
        </n-form-item>
      </n-form>
      <n-button size="small" type="primary" :disabled="locked || !newNodeTitle.trim()" @click="doCreateNode">创建</n-button>
    </template>

    <!-- 事件详情视图 -->
    <template v-if="view === 'event' && event">
      <h4>事件详情</h4>
      <n-description size="small" :column="1">
        <n-description-item label="ID">{{ event.event_id }}</n-description-item>
        <n-description-item label="类型">{{ event.event_type }}</n-description-item>
        <n-description-item label="状态">{{ event.status }}</n-description-item>
        <n-description-item label="时间">{{ event.created_at }}</n-description-item>
        <n-description-item label="内容">
          <n-input type="textarea" :value="event.raw_content as string" readonly autosize />
        </n-description-item>
      </n-description>
      <div style="display:flex;gap:6px;margin-top:8px">
        <n-button size="small" type="error" :disabled="locked" @click="$emit('delete-event', event.event_id as string)">删除</n-button>
        <n-button size="small" :disabled="locked || (event.status as string) !== 'failed'" @click="$emit('retry-event', event.event_id as string)">重试</n-button>
      </div>
    </template>

    <!-- 节点详情视图 -->
    <template v-if="view === 'node' && node">
      <h4>节点详情</h4>
      <n-description size="small" :column="1">
        <n-description-item label="ID">{{ node.node_id }}</n-description-item>
        <n-description-item label="标题">{{ node.title }}</n-description-item>
        <n-description-item label="类型">{{ node.node_type }}</n-description-item>
        <n-description-item label="置信度">{{ node.confidence }}</n-description-item>
        <n-description-item label="内容">
          <n-input type="textarea" v-model:value="editContent" autosize placeholder="编辑节点内容（保存前可自由修改）" />
        </n-description-item>
        <n-description-item label="源证">
          <div v-for="sr in node.source_refs" :key="sr.event_id" style="font-size:12px">
            {{ sr.event_id }}<n-tag v-if="!sr.valid" size="tiny" type="error" style="margin-left:4px">失效</n-tag>
          </div>
        </n-description-item>
        <n-description-item v-if="node.edges.length" label="关联边">
          <div v-for="e in node.edges" :key="`${e.source}→${e.target}`" style="font-size:12px">
            {{ e.source }} → {{ e.target }} ({{ e.relation }})
          </div>
        </n-description-item>
      </n-description>
      <div style="display:flex;gap:6px;margin-top:8px">
        <n-button size="small" type="primary" :disabled="locked" @click="$emit('save-node', { node_id: node.node_id, content: editContent })">保存</n-button>
        <n-button size="small" type="error" :disabled="locked" @click="$emit('delete-node', node.node_id)">删除</n-button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { NodeDetail, SettingsResponse } from '@/api/client'

const props = defineProps<{
  view: string
  locked: boolean
  event: Record<string, unknown> | null
  node: NodeDetail | null
  settings: SettingsResponse | null
  savedHint: string
}>()

const emit = defineEmits<{
  'delete-event': [id: string]
  'retry-event': [id: string]
  'save-node': [payload: { node_id: string; content: string }]
  'delete-node': [id: string]
  'save-settings': [settings: SettingsResponse]
  'create-node': [payload: { title: string; content: string; node_type: string; event_id: string }]
}>()

// Node editing
const editContent = ref('')

// New node form
const newNodeTitle = ref('')
const newNodeContent = ref('')
const newNodeType = ref('interaction')
const newNodeEventId = ref('')

function doCreateNode() {
  emit('create-node', {
    title: newNodeTitle.value,
    content: newNodeContent.value,
    node_type: newNodeType.value,
    event_id: newNodeEventId.value,
  })
  newNodeTitle.value = ''
  newNodeContent.value = ''
  newNodeType.value = 'interaction'
  newNodeEventId.value = ''
}

// Settings
const localSettings = ref<SettingsResponse>({
  memory_db_path: '', graph_json_path: '', llm_base_url: '', llm_api_key: '',
  llm_model_name: '', llm_timeout: 30, available_providers: ['primary'],
  providers: {},
  active_provider: 'primary',
  available_models: [], active_model: '',
  agent_mode: 'disabled', agent_max_retries: 2, agent_cr_model: '',
  agent_in_model: '', agent_gr_model: '', agent_meta_model: '',
  max_graph_hops: 2, rrf_k: 60,
  jaccard_threshold: 0.85, health_check_interval: 60, compensate_batch_size: 20, log_level: 'INFO',
})

const logLevelOptions = [
  { label: 'DEBUG', value: 'DEBUG' },
  { label: 'INFO', value: 'INFO' },
  { label: 'WARNING', value: 'WARNING' },
  { label: 'ERROR', value: 'ERROR' },
]

watch(() => props.node, (n) => { if (n) editContent.value = n.content }, { immediate: true })
watch(() => props.settings, (s) => { if (s) localSettings.value = { ...s } }, { immediate: true })
</script>

<style scoped>
.right-panel { height: 100%; padding: 8px; overflow-y: auto; }
h4 { margin: 0 0 8px 0; font-size: 14px; }
</style>
