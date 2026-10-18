/**
 * 未保存草稿的离开守卫（链 AM）。
 *
 * 为什么需要：设置页的**提供商草稿**（含只在内存里的待提交密钥）、图谱页的**节点修订**、
 * 信息列表的**内容修订**都是纯内存草稿——切页或刷新即**无声丢弃**，用户没有任何提示。
 * 审计把这一类列为 P1（「能否静默丢失」）。
 *
 * 为什么用浏览器原生确认框而不是项目自己的 `ConfirmDialog`：
 * ① `beforeunload` 要求**同步**返回，拿不到弹窗的异步结果；
 * ② 本 composable 要被多个页面复用，不能假设调用方一定在 `NDialogProvider` 之内。
 * 页内的破坏性操作（删除 / 清空 / 恢复）仍走项目自己的 `ConfirmDialog`——那类需要展示影响说明。
 *
 * 用法（在 setup 里调用一次即可）：
 * ```ts
 * useUnsavedGuard(() => draftDirty.value || hasPendingSecret(), '提供商配置还没提交，离开将丢失。确定离开吗？')
 * ```
 */
import { onBeforeUnmount, onMounted } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'

export function useUnsavedGuard(
  isDirty: () => boolean,
  message = '有未提交的改动，离开将丢弃它们。确定离开吗？',
): void {
  const onBeforeUnload = (e: BeforeUnloadEvent): void => {
    if (!isDirty()) return
    // 现代浏览器只认「阻止默认行为」这个信号，提示文案由浏览器自己决定（无法自定义）
    e.preventDefault()
    e.returnValue = ''
  }

  onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
  onBeforeUnmount(() => window.removeEventListener('beforeunload', onBeforeUnload))

  onBeforeRouteLeave(() => {
    if (!isDirty()) return true
    return window.confirm(message)
  })
}
