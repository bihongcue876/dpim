/**
 * 契约类型单一来源（重设计：不再手抄协议）。
 *
 * `@protocol` 指向仓库根的 `share/protocol.ts`（权威契约，v1.31），
 * 由 vite alias 与 tsconfig paths 同时指向同一文件——改契约即改前端类型。
 *
 * 说明：这些是**纯类型**导入/导出，编译期即被擦除，因此运行时不会真的去加载
 * 项目根之外的文件（alias 只需对 tsc / vue-tsc 生效）。
 */
export type * from '@protocol'

import type { EventDetail, GraphEdge } from '@protocol'

// ── 契约补丁（唯一一处）：GET /events/{id} 的实际响应 ──────────────────────
// v1.28 起后端在事件行上落库失败原因（events.error），但契约的 `Event`
// 接口尚未收录该字段。这里以视图类型收敛；契约补齐后本段删除。

/** GET /events/{event_id} 的响应（含 v1.28 失败原因字段） */
export type EventDetailResponse = EventDetail & { error?: string }

/** 兼容别名：画布消费的边形状就是契约里的 `GraphEdge`（旧 client.ts 曾叫 EdgeInfo） */
export type EdgeInfo = GraphEdge
