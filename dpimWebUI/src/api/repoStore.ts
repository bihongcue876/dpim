/** 库上下文单一来源（链 U）：全部标签页共享的 repos 清单与活动库。
 *
 * ConfigTab 的库操作后调用 loadRepos() 刷新；其余组件挂载时 loadRepos() 即可。
 */
import { computed, ref } from 'vue'
import type { RepoInfo } from './client'
import * as api from './client'

export const repos = ref<RepoInfo[]>([])
export const reposLoaded = ref(false)

export async function loadRepos() {
  try {
    repos.value = (await api.listRepos()).repos
    reposLoaded.value = true
  } catch { /* 后端未升级或离线：保持空清单，下拉自动隐藏 */ }
}

/** 活动库（后端 /repos 的 active 标记） */
export const activeRepo = computed(() => repos.value.find(r => r.active) ?? null)

/** 受管且已加载的库（下拉选项用；休眠库不可选） */
export const selectableRepos = computed(() =>
  (repos.value ?? []).filter(r => r.managed && r.loaded),
)
