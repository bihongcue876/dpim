/**
 * 配置来源标签（v1.36）：`GET /settings` 的 `config_sources[字段]` 必须**看得见**。
 *
 * 用户诉求是「前端可以配置后端的东西」，而此前的静默失败来自「改了但被环境变量顶掉、
 * 界面毫无提示」。这里守住三条：
 * ① `env:DPIM_X` → 明示「由环境变量 DPIM_X 决定（界面不可改）」；
 * ② `file` → 说明已持久化（重启后仍在）；
 * ③ `default` → 说明还是内置默认值（从未改过）；
 * ④ 后端未上报来源（空串）→ 不渲染任何东西，不制造噪声。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ConfigSourceTag from '@/components/ui/ConfigSourceTag.vue'

describe('ConfigSourceTag（配置来源可见）', () => {
  it('env 锁定：点名环境变量，并用锁定态样式', () => {
    const wrapper = mount(ConfigSourceTag, { props: { source: 'env:DPIM_RRF_K' } })
    expect(wrapper.text()).toBe('由环境变量 DPIM_RRF_K 决定（界面不可改）')
    expect(wrapper.find('.chip--lock').exists()).toBe(true)
  })

  it('file：说明已写入 dpim.json', () => {
    const wrapper = mount(ConfigSourceTag, { props: { source: 'file' } })
    expect(wrapper.text()).toContain('已存')
    expect(wrapper.text()).toContain('dpim.json')
    expect(wrapper.find('.chip--file').exists()).toBe(true)
  })

  it('default：说明还是内置默认值', () => {
    const wrapper = mount(ConfigSourceTag, { props: { source: 'default' } })
    expect(wrapper.text()).toBe('默认值')
  })

  it('未上报来源：不渲染（后端旧版本也不炸）', () => {
    const wrapper = mount(ConfigSourceTag, { props: { source: '' } })
    expect(wrapper.text()).toBe('')
    expect(wrapper.find('.chip').exists()).toBe(false)
  })
})
