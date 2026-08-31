// 对话指令候选（与后端 core/commands.py 语法对齐：^英文动词、空格分隔）
// 仅 ^ 形式是指令；其余输入一律按普通文本落库

export interface CommandCandidate {
  name: string // 指令名（含 ^ 前缀）
  args: string // 参数提示（展示用）
  desc: string // 功能说明
  needsAI: boolean // 是否需要 AI 可用（语义层指令）
}

export const COMMAND_CANDIDATES: CommandCandidate[] = [
  {
    name: '^compress',
    args: ' [节点ID]',
    desc: '图压缩维护：删繁就简（合并/清僵尸/压缩冗长），可补边',
    needsAI: true,
  },
  {
    name: '^update',
    args: ' [节点ID]',
    desc: '图结构优化两阶段：减碎+补缺失要点 → 连线孤岛',
    needsAI: true,
  },
  {
    name: '^merge',
    args: ' <目标ID> <源ID>',
    desc: '合并节点：源证并集 + 内容合并不丢失',
    needsAI: false,
  },
  {
    name: '^delete',
    args: ' <节点ID>',
    desc: '删除节点：受删除保护与 system 保护',
    needsAI: false,
  },
  {
    name: '^data',
    args: ' <内容>',
    desc: '按 data 类型存入（纯存储，AI 不可用也可用）',
    needsAI: false,
  },
  {
    name: '^interaction',
    args: ' <内容>',
    desc: '按 interaction 类型存入（对话/决策记录）',
    needsAI: false,
  },
  {
    name: '^source',
    args: ' <内容>',
    desc: '按 source 类型存入（仅存储不构图）',
    needsAI: false,
  },
  {
    name: '^node',
    args: ' system <标题> | <内容>',
    desc: '手工创建系统节点（无源证要求）',
    needsAI: false,
  },
  {
    name: '^help',
    args: '',
    desc: '查看全部指令用法',
    needsAI: false,
  },
]

/**
 * 解析输入框当前是否处于「打指令词」阶段：
 * 内容以 ^ 开头且 ^ 后尚无空白（空格后即进入参数阶段，收起候选）。
 * 全角 ＾ 归一化（与后端解析器一致，中文输入法友好）。
 * 返回指令词 token（不含 ^，小写）；非指令阶段返回 null。
 */
export function commandToken(content: string): string | null {
  // 仅归一化前导空白与全角 ＾；保留尾部空白——"^data " 的尾随空格是
  // 「已进入参数阶段」的信号，不能 trim 掉
  const text = content.replace(/^\s+/, '').replace(/＾/g, '^')
  if (!text.startsWith('^')) return null
  const body = text.slice(1)
  if (/\s/.test(body)) return null
  return body.toLowerCase()
}

/** 按前缀过滤候选 */
export function filterCommands(token: string): CommandCandidate[] {
  return COMMAND_CANDIDATES.filter(c => c.name.slice(1).startsWith(token))
}
