/**
 * 导航结构（四区 + 帮助）。
 *
 * 依据设计规约 §3：旧「六标签页平级导航」作废，改为按**四种活动**分组：
 * 观测 / 查阅 / 写入 / 维护。侧边栏与路由表共用本文件，避免两处漂移。
 */
export type ZoneKey = 'observe' | 'browse' | 'write' | 'maintain' | 'help'

export interface NavItem {
  name: string
  path: string
  title: string
  /** 一句话说明（侧边栏 tooltip 与页头共用） */
  desc: string
}

export interface NavZone {
  key: ZoneKey
  title: string
  /** 该区依据（原设计思维，取自设计大纲） */
  basis: string
  items: NavItem[]
}

export const NAV_ZONES: NavZone[] = [
  {
    key: 'observe',
    title: '观测',
    basis: '使 DPIM 监测和配置更方便',
    items: [
      { name: 'overview', path: '/overview', title: '概览台', desc: '一眼看清这座图书馆现在怎么样' },
      { name: 'logs', path: '/logs', title: '日志', desc: '本地翻看前后端运行日志' },
      { name: 'storage', path: '/storage', title: '存储体检', desc: '存储层到底可不可信' },
    ],
  },
  {
    key: 'browse',
    title: '查阅',
    basis: '知识可视 / 本地资料库',
    items: [
      { name: 'events', path: '/events', title: '信息列表', desc: '查原文、修订原文、看衍生关联' },
      { name: 'graph', path: '/graph', title: '信息图谱', desc: '看衍生知识的关联结构' },
      { name: 'search', path: '/search', title: '检索', desc: '跨书目找东西，并看清来自哪本书目' },
    ],
  },
  {
    key: 'write',
    title: '写入',
    basis: '手工贮存与管理',
    items: [
      { name: 'ingest', path: '/ingest', title: '信息传入', desc: '手工贮存原文与发送指令' },
    ],
  },
  {
    key: 'maintain',
    title: '维护',
    basis: '配置高于 AI / 可行性测试',
    items: [
      { name: 'repos', path: '/repos', title: '书目管理', desc: '管理这座图书馆的书目与书架' },
      { name: 'backup', path: '/backup', title: '备份与恢复', desc: '可复原：备份、校验、恢复路径' },
      { name: 'trash', path: '/trash', title: '回收站', desc: '删除可回收' },
      { name: 'settings', path: '/settings', title: '运行配置', desc: '环境变量与运行参数' },
    ],
  },
  {
    key: 'help',
    title: '帮助',
    basis: '使用说明',
    items: [{ name: 'help', path: '/help', title: '帮助', desc: '这是什么、怎么用、常见问题' }],
  },
]

/** 扁平化的全部导航项（路由标题、面包屑用） */
export const NAV_ITEMS: NavItem[] = NAV_ZONES.flatMap((z) => z.items)

export function titleOfRoute(name: string | symbol | null | undefined): string {
  const item = NAV_ITEMS.find((i) => i.name === String(name))
  return item?.title ?? 'DPIM'
}

export function zoneOfRoute(name: string | symbol | null | undefined): NavZone | null {
  return NAV_ZONES.find((z) => z.items.some((i) => i.name === String(name))) ?? null
}
