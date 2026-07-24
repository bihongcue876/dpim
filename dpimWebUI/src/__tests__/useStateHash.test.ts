import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/client', () => ({
  getStateHash: vi.fn(),
}))

import { getStateHash } from '@/api/client'
import { useStateHash } from '@/composables/useStateHash'

describe('useStateHash', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('starts locked with loading status', () => {
    const { isLocked, hashStatus } = useStateHash()
    expect(isLocked.value).toBe(true)
    expect(hashStatus.value).toBe('loading')
  })

  it('refresh locks on first call (fresh hash)', async () => {
    vi.mocked(getStateHash).mockResolvedValue({
      hash: 'abc',
      changed_at: '2026-07-24T12:00:00Z',
    })
    const { isLocked, hashStatus, refresh } = useStateHash()
    await refresh()
    expect(getStateHash).toHaveBeenCalledTimes(1)
    expect(isLocked.value).toBe(true)
    expect(hashStatus.value).toBe('locked')
  })

  it('refresh unlocks when hash matches', async () => {
    vi.mocked(getStateHash).mockResolvedValue({
      hash: 'same',
      changed_at: '2026-07-24T12:00:00Z',
    })
    const { isLocked, hashStatus, refresh } = useStateHash()
    await refresh()
    await refresh()  // same hash → unlock
    expect(isLocked.value).toBe(false)
    expect(hashStatus.value).toBe('unlocked')
  })

  it('refresh stays locked when hash changes', async () => {
    vi.mocked(getStateHash)
      .mockResolvedValueOnce({ hash: 'abc', changed_at: '2026-07-24T12:00:00Z' })
      .mockResolvedValueOnce({ hash: 'def', changed_at: '2026-07-24T12:01:00Z' })
    const { isLocked, refresh } = useStateHash()
    await refresh()
    await refresh()
    expect(isLocked.value).toBe(true)
  })

  it('unlock() sets locked false', () => {
    const { isLocked, hashStatus, unlock } = useStateHash()
    unlock()
    expect(isLocked.value).toBe(false)
    expect(hashStatus.value).toBe('unlocked')
  })
})
