import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import DataTable from '@/components/ui/DataTable.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import StatTile from '@/components/ui/StatTile.vue'
import OriginBadge from '@/components/ui/OriginBadge.vue'
import ConfirmDialog from '@/components/ui/ConfirmDialog.vue'
import PageShell from '@/components/ui/PageShell.vue'
import FieldRow from '@/components/ui/FieldRow.vue'

const COLUMNS = [
  { key: 'name', label: '名称', width: 'sm' as const },
  { key: 'count', label: '数量', width: 'xs' as const, align: 'right' as const },
]

describe('DataTable', () => {
  it('渲染表头与单元格；插槽可覆盖单元格内容', () => {
    const wrapper = mount(DataTable, {
      props: {
        columns: COLUMNS,
        rows: [{ name: '甲', count: 3 }],
        rowKey: 'name',
        total: 1,
      },
      slots: { 'cell-name': '<b class="custom">覆盖</b>' },
    })
    expect(wrapper.findAll('thead th').map((th) => th.text())).toEqual(['名称', '数量'])
    expect(wrapper.find('.custom').text()).toBe('覆盖')
    expect(wrapper.find('td.align-right').text()).toBe('3')
  })

  it('行点击抛出 row-click，携带整行与下标', async () => {
    const wrapper = mount(DataTable, {
      props: { columns: COLUMNS, rows: [{ name: '甲', count: 1 }], rowKey: 'name' },
    })
    await wrapper.find('tbody tr').trigger('click')
    expect(wrapper.emitted('row-click')?.[0]).toEqual([{ name: '甲', count: 1 }, 0])
  })

  it('空态：无数据时显示 StateBlock（空文案 + 引导），有数据时不显示', async () => {
    const empty = mount(DataTable, {
      props: {
        columns: COLUMNS,
        rows: [],
        emptyText: '没有事件',
        emptyHint: '去写入一条',
      },
    })
    expect(empty.text()).toContain('没有事件')
    expect(empty.text()).toContain('去写入一条')

    const filled = mount(DataTable, {
      props: { columns: COLUMNS, rows: [{ name: '甲', count: 1 }], rowKey: 'name' },
    })
    expect(filled.findComponent(StateBlock).exists()).toBe(false)
  })

  it('加载态与错误态由 StateBlock 承接，错误原文不被吞', () => {
    const wrapper = mount(DataTable, {
      props: { columns: COLUMNS, rows: [], loading: true },
    })
    expect(wrapper.text()).toContain('加载中')

    const failed = mount(DataTable, {
      props: { columns: COLUMNS, rows: [], error: '409 节点受保护' },
    })
    expect(failed.text()).toContain('409 节点受保护')
  })

  it('真分页：total 超过 pageSize 才出现分页条，翻页发出 update:offset', async () => {
    const short = mount(DataTable, {
      props: { columns: COLUMNS, rows: [{ name: '甲', count: 1 }], total: 5, pageSize: 20 },
    })
    expect(short.find('.table-foot').exists()).toBe(false)

    const long = mount(DataTable, {
      props: {
        columns: COLUMNS,
        rows: [{ name: '甲', count: 1 }],
        total: 100,
        pageSize: 20,
        offset: 20,
      },
    })
    expect(long.find('.table-foot').exists()).toBe(true)
    const items = long.findAll('.n-pagination-item')
    const page3 = items.find((i) => i.text() === '3')
    expect(page3).toBeTruthy()
    await page3!.trigger('click')
    expect(long.emitted('update:offset')?.[0]).toEqual([40])
  })
})

describe('StateBlock', () => {
  it('三态互斥渲染：loading / error / empty 各自只出现一个', () => {
    const loading = mount(StateBlock, { props: { loading: true } })
    expect(loading.find('.state-spinner').exists()).toBe(true)
    expect(loading.find('.state-icon--error').exists()).toBe(false)

    const failed = mount(StateBlock, { props: { error: '读取失败' } })
    expect(failed.find('.state-icon--error').exists()).toBe(true)
    expect(failed.find('.state-spinner').exists()).toBe(false)

    const empty = mount(StateBlock, { props: { emptyText: '暂无' } })
    expect(empty.text()).toContain('暂无')
    expect(empty.find('.state-icon--error').exists()).toBe(false)
  })

  it('固定高度开关影响类名（防布局跳动）', () => {
    expect(mount(StateBlock, { props: { fixedHeight: true } }).classes()).toContain(
      'state-block--fixed',
    )
  })
})

describe('OriginBadge（原文 / 衍生必须可区分）', () => {
  it('默认文案写明可否修改', () => {
    const origin = mount(OriginBadge, { props: { kind: 'origin' } })
    const derived = mount(OriginBadge, { props: { kind: 'derived' } })
    expect(origin.text()).toContain('仅人类可修订')
    expect(derived.text()).toContain('可由 AI 维护')
    expect(origin.classes()).toContain('badge--origin')
    expect(derived.classes()).toContain('badge--derived')
  })

  it('可覆盖文案', () => {
    expect(mount(OriginBadge, { props: { kind: 'origin', text: '原文' } }).text()).toContain('原文')
  })
})

describe('PageShell', () => {
  it('渲染分区、标题、说明与主操作槽', () => {
    const wrapper = mount(PageShell, {
      props: { title: '信息列表', description: '查原文', zone: '查阅' },
      slots: { actions: '<button class="main">新建</button>', default: '<p>正文</p>' },
    })
    expect(wrapper.find('.page-zone').text()).toBe('查阅')
    expect(wrapper.find('.page-title').text()).toBe('信息列表')
    expect(wrapper.find('.main').exists()).toBe(true)
    expect(wrapper.find('.page-body').text()).toContain('正文')
  })
})

describe('SectionCard / StatTile / FieldRow', () => {
  it('SectionCard 渲染标题、说明、操作槽与 flush 类名', () => {
    const wrapper = mount(SectionCard, {
      props: { title: '容量与保障', hint: '看得见', flush: true },
      slots: { actions: '<button class="act">刷新</button>', default: '<div>x</div>' },
    })
    expect(wrapper.find('.card-title').text()).toBe('容量与保障')
    expect(wrapper.find('.card-hint').text()).toBe('看得见')
    expect(wrapper.find('.act').exists()).toBe(true)
    expect(wrapper.find('.card-body').classes()).toContain('card-body--flush')
  })

  it('StatTile 渲染数值/单位/提示与色调类名', () => {
    const wrapper = mount(StatTile, {
      props: { label: '备份份数', value: 3, unit: '份', hint: '保留最近 N 份', tone: 'success' },
    })
    expect(wrapper.find('.tile-label').text()).toBe('备份份数')
    expect(wrapper.find('.tile-value').text()).toContain('3')
    expect(wrapper.find('.tile-value').classes()).toContain('tile-value--success')
    expect(wrapper.find('.tile-hint').text()).toContain('保留最近')
  })

  it('FieldRow 渲染标签、说明与控件槽', () => {
    const wrapper = mount(FieldRow, {
      props: { label: '日志级别', hint: '重启生效' },
      slots: { default: '<input class="ctl" />' },
    })
    expect(wrapper.find('label').text()).toBe('日志级别')
    expect(wrapper.find('.field-hint').text()).toBe('重启生效')
    expect(wrapper.find('.ctl').exists()).toBe(true)
  })
})

describe('ConfirmDialog', () => {
  // n-modal 会 teleport 到 body，故断言走 document（不 stub，测真实渲染）
  function mountDialog(props: Record<string, unknown>) {
    return mount(ConfirmDialog, { props: props as never, attachTo: document.body })
  }

  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('危险操作必须列出影响清单', async () => {
    mountDialog({
      show: true,
      danger: true,
      title: '删除书目及其文件？',
      message: 'rp_x',
      impacts: ['会先备份 memory.db', '不可逆'],
      confirmText: '删除',
    })
    await nextTick()
    const title = document.querySelector('.confirm-title')
    expect(title).toBeTruthy()
    expect(title!.classList.contains('confirm-title--danger')).toBe(true)
    expect(document.querySelector('.confirm-message')!.textContent).toContain('rp_x')
    const items = [...document.querySelectorAll('.confirm-impacts li')].map((li) =>
      li.textContent?.trim(),
    )
    expect(items).toEqual(['会先备份 memory.db', '不可逆'])
  })

  it('确认与取消各自发出事件（取消同时关闭）', async () => {
    const wrapper = mountDialog({ show: true, title: 't' })
    await nextTick()
    const buttons = [...document.querySelectorAll('.confirm-actions button')] as HTMLElement[]
    expect(buttons).toHaveLength(2)

    buttons[1].click()
    await nextTick()
    expect(wrapper.emitted('confirm')).toHaveLength(1)

    buttons[0].click()
    await nextTick()
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(wrapper.emitted('update:show')?.[0]).toEqual([false])
  })
})

describe('内联样式规约', () => {
  it('统一层组件不得出现内联 style', () => {
    const props = { columns: COLUMNS, rows: [], title: 't', label: 'l', value: 1, kind: 'origin' }
    const components = [DataTable, StateBlock, SectionCard, StatTile, OriginBadge, PageShell, FieldRow]
    for (const comp of components) {
      const wrapper = mount(comp as never, { props: props as never })
      expect(wrapper.html()).not.toMatch(/\sstyle="/)
    }
  })

  it('ConfirmDialog 同样无内联 style', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { show: true, title: 't' },
      attachTo: document.body,
    })
    await nextTick()
    expect(wrapper.html()).not.toMatch(/\sstyle="/)
    document.body.innerHTML = ''
  })
})

// 保持 vi 被使用（部分环境会因未使用 import 报警）
void vi
