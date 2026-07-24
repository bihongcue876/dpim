import { ref } from 'vue'
import { getStateHash } from '@/api/client'

const isLocked = ref(true)
const currentHash = ref('')
const changedAt = ref('')
const hashStatus = ref<'loading' | 'locked' | 'unlocked'>('loading')

export function useStateHash() {
  async function refresh() {
    hashStatus.value = 'loading'
    const res = await getStateHash()
    const fresh = res.hash
    if (currentHash.value === fresh) {
      isLocked.value = false
      hashStatus.value = 'unlocked'
    } else {
      currentHash.value = fresh
      changedAt.value = res.changed_at
      isLocked.value = true
      hashStatus.value = 'locked'
    }
  }

  function unlock() {
    isLocked.value = false
    hashStatus.value = 'unlocked'
  }

  return { isLocked, currentHash, changedAt, hashStatus, refresh, unlock }
}
