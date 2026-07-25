import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/client', () => ({
  getStateHash: vi.fn(),
}))

import { getStateHash } from '@/api/client'
import { useStateKey } from '@/composables/useStateKey'

describe('useStateKey', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('init fetches and stores key', async () => {
    vi.mocked(getStateHash).mockResolvedValue({ hash: 'abc', changed_at: '2026-07-24T12:00:00Z' })
    const { pageKey, keyStatus, init } = useStateKey()
    expect(pageKey.value).toBe('')
    expect(keyStatus.value).toBe('unknown')
    await init()
    expect(pageKey.value).toBe('abc')
  })

  it('validate returns true when keys match', async () => {
    vi.mocked(getStateHash).mockResolvedValue({ hash: 'same', changed_at: '' })
    const { init, validate } = useStateKey()
    await init()
    vi.mocked(getStateHash).mockResolvedValue({ hash: 'same', changed_at: '' })
    expect(await validate()).toBe(true)
  })

  it('validate returns false when keys differ, updates pageKey', async () => {
    vi.mocked(getStateHash).mockResolvedValue({ hash: 'old', changed_at: '' })
    const { init, validate, pageKey } = useStateKey()
    await init()
    expect(pageKey.value).toBe('old')
    vi.mocked(getStateHash).mockResolvedValue({ hash: 'new', changed_at: '' })
    expect(await validate()).toBe(false)
    expect(pageKey.value).toBe('new')
  })

  it('onCommitted refreshes pageKey', async () => {
    vi.mocked(getStateHash).mockResolvedValue({ hash: 'first', changed_at: '' })
    const { init, onCommitted, pageKey } = useStateKey()
    await init()
    expect(pageKey.value).toBe('first')
    vi.mocked(getStateHash).mockResolvedValue({ hash: 'second', changed_at: '' })
    await onCommitted()
    expect(pageKey.value).toBe('second')
  })
})
