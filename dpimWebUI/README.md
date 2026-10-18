# dpimWebUI — DPIM 控制面板

> 纯 REST 客户端（Vue 3 + Naive UI + D3）。**不含任何本体逻辑**：所有存储语义都在 `dpim/` 后端。
> 设计依据：`docs/DPIM-WebUI设计规约20261003.md`（唯一依据）。
> 落地记录：`docs/DPIM-WebUI重设计实施记录20261004.md`。

---

## 快速开始

```bash
pnpm install
pnpm dev        # http://localhost:5173（后端默认 :8000，经 vite 代理）
```

> **若 `pnpm install` 报 `ERR_PNPM_IGNORED_BUILDS`（esbuild）**：pnpm 11 起依赖的安装脚本默认拒绝执行，
> 裁决位置是 `pnpm-workspace.yaml` 的 `allowBuilds`。pnpm 自动脚手架写进去的占位串
> `set this to true or false` 是「**未裁决**」，仍按拒绝处理，必须改成 `true`（本项目已裁决 `esbuild: true`）。
> 也可以用 `pnpm approve-builds` 交互裁决，效果相同。

后端端口不是 8000 时：

```bash
# PowerShell
$env:DPIM_API_PORT = "8899"; pnpm dev
```

也可以在「维护 → 运行配置」页把**后端地址**填成绝对地址（存 `localStorage.dpim_backend_url`），
此时不走代理，直接请求该地址。

## 命令

| 命令 | 说明 |
|---|---|
| `pnpm dev` | 开发服务器（含 `/health`、`/logs`、`/trash` 等全部前缀的代理） |
| `pnpm build` | 类型检查 + 生产构建 |
| `pnpm typecheck` | `vue-tsc --noEmit` |
| `pnpm test` | vitest |

> **注意**：仓库路径含括号时 `node_modules/.bin/vue-tsc.cmd` 会被 cmd.exe 拆坏。
> 请直接调用：`node ./node_modules/vue-tsc/bin/vue-tsc.js --noEmit -p tsconfig.app.json`。

---

## 页面结构（四区 + 帮助 = 12 页）

| 区 | 页面 | 路由 |
|---|---|---|
| 观测 | 概览台 / 日志 / 存储体检 | `#/overview` `#/logs` `#/storage` |
| 查阅 | 信息列表 / 信息图谱 / 检索 | `#/events` `#/graph` `#/search` |
| 写入 | 信息传入 | `#/ingest` |
| 维护 | 书目管理 / 备份与恢复 / 回收站 / 运行配置 | `#/repos` `#/backup` `#/trash` `#/settings` |
| — | 帮助 | `#/help` |

路由是 **hash 模式**：可深链、刷新不丢位置、从 `dist/` 静态打开也能用。
部分页面接受查询参数：`#/events?event=<event_id>`、`#/graph?node=<node_id>`。

---

## AI 状态与运行配置

- **AI 状态文案只有一个来源**：`stores/health.ts`。`aiStatus` 四态 `ready` / `unconfigured` / `degraded` / `offline`
  与配套的 `aiStatusText` / `aiReason` 由此统一派生，顶栏徽章、概览台、信息传入页都取这里——
  **未配置 ≠ 降级**（`unconfigured` 会给出中文原因，如「活动提供商未登记」「模型列表为空」）。
- **运行配置页（`SettingsPage.vue`）已删去 7 个 `llm_*` 主配置字段**：AI 身份（地址/密钥/模型）只存在于
  **提供商卡片**的条目里。卡片与新建/编辑提供商弹窗都有「**拉取模型**」按钮（`POST /settings/models`，
  只读探测、失败不报 4xx 而是把错误摘要回填 `error`），新建提供商可在同一轮拉到模型列表并选中；
  活动模型下拉对未登记的提供商标注「（未登记）」。
- **运行配置页现在也能配后端的运行参数（v1.36）**：字段按「检索与护栏 / 健康检查与补偿 / 图维护自动化 /
  本地日志与 WAL」等板块分组（连同原有的后端地址、提供商、存储路径与日志级别）；全部落盘 `dpim.json`，
  重启后仍在。页首显示只读的**配置文件**（当前 dpim.json 的绝对路径）与**日志目录**，让用户知道改的是哪份文件。
- **每个字段旁有来源标记**：来自 `GET /settings` 的 `config_sources`，三态为「已存 dpim.json」/「默认值」/
  「**由环境变量 DPIM_X 决定（界面不可改）**」；最后一种会**禁用该控件**。提交时若仍命中 env 锁定项，
  响应里的 `ignored_by_env`（如 `["rrf_k(DPIM_RRF_K)"]`）会把这些项列进结果横幅，并说明后端未写入内存。
- **改动是草稿**：编辑字段与提供商卡片只改本地状态，必须再点「**提交配置**」才写回后端。
- **生效时机分两种**：存储路径、`log_level`、日志保留天数与 JSONL 开关**重启后**生效；
  其余（WAL 检查点、健康检查、补偿、图维护、检索与管线参数）在循环内或每请求读取，**立即生效**。

---

## 两条必须遵守的界面纪律

1. **书目是全局上下文，不是页面。** 顶栏一个选择器决定全站作用域：
   - 选单本书目 → 只查/只写那一本；
   - 选「全部书目」→ **联查**（只读聚合，结果标明来自哪本书目）。
   > 后端只有 `GET /events/{id}`、`GET /nodes/{id}`、`/feedback` 接受 `repo_id`；
   > **所有写操作只作用于「活动书目」**。因此从联查结果里修订他库条目时，
   > 界面会先说明并请你确认「切换活动书目」（`composables/useRepoWrite.ts`），
   > 不静默切换、也不静默写错库。

2. **原文与衍生知识必须看得出区别。**
   - **原文**（线层事件）：按时间追加、大模型不可轻易调整、**只有人类可显式修订**；
   - **衍生知识**（图节点/边）：AI 从原文提炼，**可由 AI 维护**（合并/压缩/补边）。
   > 界面上不存在任何「让 AI 改写原文」的通道。

---

## 代码结构

```
src/
├── styles/       tokens.css（唯一色源）· base.css · naive-theme.ts（Naive 侧镜像）
├── router/       index.ts（hash 路由）· nav.ts（四区导航结构，侧边栏与路由共用）
├── stores/       repo（书目与全局作用域）· health · session（状态密钥+revision）· theme
├── api/          http（基座）· types（re-export @protocol）· 按域拆的 10 个模块
├── composables/  useRepoScope · useRepoWrite · useListPage · useAsyncAction · usePolling
├── components/
│   ├── layout/   AppShell · NavSidebar · TopBar · RepoScopePicker
│   ├── ui/       PageShell · Toolbar · StateBlock · SectionCard · DataTable
│   │             DetailPanel · ConfirmDialog · FieldRow · OriginBadge · StatTile
│   ├── GraphCanvas.vue    D3 力导向画布（从 CSS 令牌读色，随主题重绘）
│   ├── CommandHints.vue   ^指令候选弹层
│   └── IngestHistory.vue  传入历史
└── pages/        12 个页面
```

### 三条硬性约定（改代码前先看）

1. **样式只用令牌**：`var(--dpim-*)`。禁止内联 `style=`、禁止魔法数字、禁止在组件里写颜色字面量。
   换配色只改 `styles/tokens.css` 与 `styles/naive-theme.ts` 各一处。
2. **契约类型不手抄**：`src/api/types.ts` 从仓库根的 `share/protocol.ts`（alias `@protocol`）re-export。
   接口改动顺序仍是 `dpim/core/models.py` → `share/protocol.md` → `share/protocol.ts`。
3. **失败必须可见**：错误原文要显示在页面上，不能只在 toast 里闪；所有请求失败经 `api/http.ts`
   注入的上报通道写进后端 `frontend-*.log`（维护 → 日志 页可翻看）。
