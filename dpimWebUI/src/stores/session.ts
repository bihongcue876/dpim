/**
 * 会话级状态（store：session）——状态校验密钥 + 全局刷新信号。
 *
 * 行为要求（规约 §5.3）：写成功后刷新；**失败不刷新**
 * （密钥是随机 UUID，不是状态派生值，失败时刷新会掩盖问题）。
 *
 * `revision` 是给页面用的「数据已变更」信号：写操作成功 → revision+1，
 * 页面 watch 它即可决定是否重取，取代旧的 window 字符串事件。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '@/api/health'

export const useSessionStore = defineStore('session', () => {
  const stateKey = ref('')
  const stateChangedAt = ref('')
  const revision = ref(0)
  const loading = ref(false)
  const error = ref('')

  /** 拉取状态校验密钥；失败不改变现有密钥（不掩盖问题） */
  async function validate(): Promise<string> {
    loading.value = true
    try {
      const res = await api.getStateHash()
      const changed = res.hash !== stateKey.value
      stateKey.value = res.hash
      stateChangedAt.value = res.changed_at
      error.value = ''
      if (changed && revision.value > 0) revision.value += 1
      return res.hash
    } catch (e) {
      error.value = (e as Error).message
      throw e
    } finally {
      loading.value = false
    }
  }

  /** 写操作成功后的统一收口 */
  async function commit(): Promise<void> {
    revision.value += 1
    try {
      await validate()
    } catch {
      /* 写已成功；密钥刷新失败只记录，不向用户报错 */
    }
  }

  return { stateKey, stateChangedAt, revision, loading, error, validate, commit }
})
