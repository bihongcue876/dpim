import { ref } from 'vue'
import { getStateHash } from '@/api/client'

const pageKey = ref('')
const keyStatus = ref<'unknown' | 'synced' | 'stale'>('unknown')
const changedAt = ref('')

export function useStateKey() {
  /** 页面加载 / 切换 Tab 时调用：获取最新 key，存为页面基准。 */
  async function init() {
    const res = await getStateHash()
    pageKey.value = res.hash
    changedAt.value = res.changed_at
    keyStatus.value = 'unknown'
  }

  /** 提交前调用：获取最新 key 与页面基准比对。
   *  true  → 一致，可以提交
   *  false → 不一致，调用方应刷新数据后保留编辑 */
  async function validate(): Promise<boolean> {
    const res = await getStateHash()
    if (res.hash === pageKey.value) {
      keyStatus.value = 'synced'
      return true
    }
    // 不一致：更新页面基准为最新 key，返回 false
    pageKey.value = res.hash
    changedAt.value = res.changed_at
    keyStatus.value = 'stale'
    return false
  }

  /** 提交成功后调用：刷新 key 作为新页面基准。 */
  async function onCommitted() {
    const res = await getStateHash()
    pageKey.value = res.hash
    changedAt.value = res.changed_at
    keyStatus.value = 'synced'
  }

  return { pageKey, keyStatus, changedAt, init, validate, onCommitted }
}
