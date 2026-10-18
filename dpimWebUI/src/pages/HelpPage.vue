<template>
  <PageShell zone="帮助" title="帮助" description="DPIM 双区智能记忆系统 · 使用说明">
    <!-- 帮助页为纯静态说明：无主操作（页头 actions 留空） -->
    <div class="help-scroll">
      <div class="help-inner">
        <!-- 目录：点击平滑滚动到对应分节 -->
        <SectionCard>
          <nav class="help-toc">
            <a
              v-for="s in SECTIONS"
              :key="s.id"
              class="toc-item"
              :href="`#help-${s.id}`"
              @click.prevent="scrollTo(s.id)"
            >
              <span class="toc-no">{{ s.no }}</span>
              <span class="toc-text">{{ s.title }}</span>
            </a>
          </nav>
        </SectionCard>

        <!-- 01 DPIM 是什么（用户原文） -->
        <section id="help-what" class="help-section">
          <header class="section-head">
            <span class="section-no">01</span>
            <h2 class="section-title">DPIM 是什么</h2>
          </header>
          <SectionCard>
            <p class="para">
              双区智能存储系统（Double-Place Intelligence Memory, DPIM）是一个知识存储系统，
              存储结构特质为信息链与信息图谱分别管理并相互关联，使用 AI 能力且 AI 能力可选，
              不作为强制必定选项。
            </p>
          </SectionCard>
        </section>

        <!-- 02 基本功能（用户原文） -->
        <section id="help-features" class="help-section">
          <header class="section-head">
            <span class="section-no">02</span>
            <h2 class="section-title">基本功能</h2>
          </header>
          <SectionCard>
            <p class="para">
              DPIM 用于存储数据，可通过与 AI 交互或信息手工贮存的方式管理，同时在前端可以使用 Agent
              功能存取信息。同时外部部分可以调用 DPIM 存储部分本身来调用和管理数据。
            </p>
            <p class="para">
              DPIM 的定位用途比较宽泛，以存储知识为基本要务，可以用于存储对话上下文、知识部分、流水账
              信息记录、要点管理、图谱关系集成等，基于知识可视、分区关联性贮存，设计双区结构。系统中，
              信息链（信息线层）数据用于原始数据存储，按时间顺序追加、大模型不可轻易调整（人类可显式
              修订），信息图谱用于数据关联展现，可以人工关联，
              也可以由内置 Agent 关联。
            </p>
            <p class="para">
              总而言之，此物的定位，不属于上下文存储器（如 Mem0），不属于纯粹知识库，不属于纯粹图谱，
              倒像是一个本地 Wiki（或者说一座不动的地方资料库），可以作为大智能体集合的器官，
              也可以作为一个有智能的信息管理器。
            </p>
          </SectionCard>
        </section>

        <!-- 03 书目与分组（新版新增） -->
        <section id="help-books" class="help-section">
          <header class="section-head">
            <span class="section-no">03</span>
            <h2 class="section-title">书目与分组</h2>
          </header>
          <SectionCard>
            <p class="para">
              这套系统本身是一座本地小图书馆（地方资料库）。它的最小单位是<span class="ftag">书目</span>：
              一本书目 = 一个 <code>memory.db</code> 加一个 <code>graph.json</code>，两者完全隔离、
              互不干扰——同一本书目的原文与它的衍生知识图谱放在一起，不同书目之间不共享数据。
            </p>
            <p class="para">
              <span class="ftag">分组</span>是书架：书目按分组归档，同名分组共用一个文件夹。
              分组只决定归档位置，不改变书目里的数据。
            </p>
            <ul class="help-list">
              <li>
                <span class="ftag">顶栏的全局书目选择器</span>决定全站作用域：观测、查阅、写入、维护四个区的
                页面全部跟随它，不需要在每个页面里各选一次。选择器是<span class="ftag">勾选式</span>的——
                列出所有书目，勾选任意子集（「全选」「清空」在菜单底部），勾选集合会记住，刷新后保持。
              </li>
              <li>
                <span class="ftag">勾 1 本 = 单库，勾 ≥2 本 = 联查</span>：勾一本时读与写都对着这一本；
                勾多本时把这几本放在一起检索，结果是只读的聚合视图，并且能看出每条结果来自哪本书目。
                <span class="ftag">至少勾一本</span>（取消最后一本会被拒绝并提示）。写入时落到
                <span class="ftag">活动书目</span>（当前正在使用的那一本），不会写进联查里——所以联查态下
                每个写按钮旁边都会写明「只作用于活动书目《X》」。
              </li>
              <li>
                <span class="ftag">原文</span>（线层）按时间追加，大模型不可轻易调整，只有人类可以显式修订；
                界面上标注「原文 · 仅人类可修订」。
              </li>
              <li>
                <span class="ftag">衍生知识</span>（图层）是 AI 从原文提炼的节点与边，可由 AI 维护
                （合并 / 压缩 / 补边）；界面上标注「衍生知识 · 可由 AI 维护」。
              </li>
              <li>
                书目允许联查统调，但不许擅改原文：AI 只能派生图层，界面不提供任何让 AI 改写原文的入口。
              </li>
            </ul>
          </SectionCard>
        </section>

        <!-- 04 Web UI 使用方法（按新版四区 + 12 页重写） -->
        <section id="help-usage" class="help-section">
          <header class="section-head">
            <span class="section-no">04</span>
            <h2 class="section-title">DPIM Web UI 使用方法</h2>
          </header>
          <SectionCard>
            <p class="para">
              打开网页后，左侧是分组导航（观测 / 查阅 / 写入 / 维护 + 帮助，共 12 页），顶栏是品牌、
              全局书目选择器、状态徽章、主题切换与刷新。每个页面都有可深链的地址（hash 形式，如
              <code>#/events</code>），刷新后仍停在原处。
            </p>

            <p class="para group-title"><span class="ftag">观测区</span></p>
            <ul class="help-list">
              <li>
                <span class="ftag">概览台</span>（<code>#/overview</code>）：一眼看清这座图书馆现在怎么样——
                后端连接与版本、AI 状态与降级原因、当前书目与书目总数、双区统计（事件 / 知识节点）、
                容量（主库 / WAL / 图层文件体积）、备份份数、图层操作日志条数、队列深度与最近事件时间。
              </li>
              <li>
                <span class="ftag">日志</span>（<code>#/logs</code>）：本地翻看前后端运行日志，后端日志与
                前端日志分栏切换，可按日期、级别、关键词过滤并查看尾部若干行。
              </li>
              <li>
                <span class="ftag">存储体检</span>（<code>#/storage</code>）：运行一致性校验（SQLite 完整性、
                事件与全文索引是否一致、节点与索引是否一致、图层操作日志重放一致性、悬空源证等），
                查看容量与图层操作日志，并可执行 WAL 检查点。
              </li>
            </ul>

            <p class="para group-title"><span class="ftag">查阅区</span></p>
            <ul class="help-list">
              <li>
                <span class="ftag">信息列表</span>（<code>#/events</code>）：查原文、修订原文、看衍生关联。
                左列表右详情，详情区分「原文（仅人类可修订）」与「衍生知识（关联节点、生成知识、
                状态重试、失败原因）」。
              </li>
              <li>
                <span class="ftag">信息图谱</span>（<code>#/graph</code>）：看衍生知识的关联结构。画布支持
                拖拽、缩放、点选，节点详情可管理源事件。
              </li>
              <li>
                <span class="ftag">检索</span>（<code>#/search</code>）：综合 / 原文 / 知识节点三种模式，
                可跨书目联查，结果标明来自哪本书目；反馈与跳转都带着书目参数。
              </li>
            </ul>

            <p class="para group-title"><span class="ftag">写入区</span></p>
            <ul class="help-list">
              <li>
                <span class="ftag">信息传入</span>（<code>#/ingest</code>）：手工贮存原文与发送指令。
                目标书目跟随顶栏全局作用域；类型只能选 interaction / data / source（没有 auto 模式）；
                输入 <code>^</code> 呼出指令候选（↑↓ 选择，Enter / Tab 确认，Esc 收起）；提交后可在
                处理历史里看到状态变化。
              </li>
            </ul>

            <p class="para group-title"><span class="ftag">维护区</span></p>
            <ul class="help-list">
              <li>
                <span class="ftag">书目管理</span>（<code>#/repos</code>）：管理这座图书馆的书目与书架——
                新建、编辑、重指向、收养、设为活动、刷新修复、摘除登记、删除书目及其文件、重建登记表。
              </li>
              <li>
                <span class="ftag">备份与恢复</span>（<code>#/backup</code>）：新建备份、查看备份列表与清单
                摘要；恢复刻意保持「停服务 + 本地 CLI」，界面只给命令与路径指引。
              </li>
              <li>
                <span class="ftag">回收站</span>（<code>#/trash</code>）：删除前留档的事件与节点，
                可按原 ID 恢复。
              </li>
              <li>
                <span class="ftag">运行配置</span>（<code>#/settings</code>）：顶端只读显示后端实际读写的
                配置文件与日志目录；每项字段旁标出该值来自环境变量 / dpim.json / 内置默认——被环境变量
                锁定的项会置灰（界面改不动，保存时后端也会点名）。可调项：后端地址与访问密钥（浏览器本地）、
                模型与提供商（BYOK 卡片化、密钥掩码显示）、Agent 管线、检索与护栏、健康检查与补偿、
                图维护自动化、本地日志与 WAL、存储路径与日志级别（日志级别与日志保留需重启后生效），
                以及维护动作（手动补偿、手动维护、AI 调用日志）。
              </li>
            </ul>

            <p class="para group-title"><span class="ftag">帮助</span>：本页。</p>
            <p class="para">
              AI 能力始终可选：不配置或断连时，写入、检索、指令、书目管理照常可用，只是不进图谱；
              模型恢复后自动补偿积压的事件。
            </p>
          </SectionCard>
        </section>

        <!-- 05 常见问题（用户原文） -->
        <section id="help-faq" class="help-section">
          <header class="section-head">
            <span class="section-no">05</span>
            <h2 class="section-title">常见问题</h2>
          </header>
          <SectionCard>
            <ul class="help-list">
              <li><span class="ftag">中文检索如何工作？</span>SQLite 内置 FTS5 分词器不识别中文，系统在召回不足时自动降级为 LIKE 检索，中英文均可正常使用，多词查询按词数主导计分。</li>
              <li><span class="ftag">没有配置 AI 模型还能用吗？</span>可以。AI 能力可选，未配置或断连时系统降级为基础全文检索存储，模型恢复后自动补偿补跑积压。</li>
              <li><span class="ftag">事件状态是什么意思？</span>raw（待处理）→ indexed（已索引）→ linked（已关联图谱，终态），异常为 failed / skipped；linked 为终态不可回退。</li>
              <li><span class="ftag">删除事件为什么可能被阻止？</span>删除前会预检该事件关联的 system / data 图谱节点，防止误删被锚定的证据源。</li>
              <li><span class="ftag">API 需要认证吗？</span>设置 <code>DPIM_API_KEY</code> 后所有请求需携带 <code>X-API-Key</code> 头；密钥在设置接口中一律掩码显示，修改时留空即保持不变。</li>
            </ul>
          </SectionCard>
        </section>

        <!-- 06 网站（用户原文） -->
        <section id="help-site" class="help-section">
          <header class="section-head">
            <span class="section-no">06</span>
            <h2 class="section-title">网站</h2>
          </header>
          <SectionCard>
            <p class="para">
              <a class="link" href="https://github.com/bihongcue876/dpim" target="_blank" rel="noopener">
                https://github.com/bihongcue876/dpim
              </a>
            </p>
            <p class="para-date">编写日期：2026 年 8 月 20 日</p>
          </SectionCard>
        </section>
      </div>
    </div>
  </PageShell>
</template>

<script setup lang="ts">
/**
 * 帮助（规约：这是什么、怎么用、常见问题）。
 *
 * 正文来自旧 `components/HelpTab.vue` 的用户供稿（DPIM 是什么 / 基本功能 / 常见问题 / 网站），
 * 文字未改写、未删减；「Web UI 使用方法」一节按新版四区分组导航 + 12 页重写，
 * 并新增「书目与分组」一节（书目 = 一本书，分组 = 书架，顶栏选择器决定全站作用域）。
 *
 * 保留旧版交互：目录锚点平滑滚动 + 分节卡片结构；全文不加粗，页面与关键词用主色区分。
 */
import PageShell from '@/components/ui/PageShell.vue'
import SectionCard from '@/components/ui/SectionCard.vue'

const SECTIONS = [
  { no: '01', id: 'what', title: 'DPIM 是什么' },
  { no: '02', id: 'features', title: '基本功能' },
  { no: '03', id: 'books', title: '书目与分组' },
  { no: '04', id: 'usage', title: 'Web UI 使用方法' },
  { no: '05', id: 'faq', title: '常见问题' },
  { no: '06', id: 'site', title: '网站' },
] as const

function scrollTo(id: string): void {
  document.getElementById(`help-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<style scoped>
.help-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding-bottom: var(--dpim-space-5);
}
/* 长文列：限宽居中，行宽友好；scroll 容器里的单项不许被压缩（否则滚动链失效） */
.help-inner {
  flex-shrink: 0;
  max-width: 860px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-4);
}
.help-inner > * {
  flex-shrink: 0;
}

/* ── 目录 ── */
.help-toc {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: var(--dpim-space-2);
}
.toc-item {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-2);
  padding: var(--dpim-space-1) var(--dpim-space-2);
  border-radius: var(--dpim-radius-xs);
  text-decoration: none;
  color: var(--dpim-text-2);
  font-size: var(--dpim-fs-md);
  transition: background var(--dpim-dur) ease, color var(--dpim-dur) ease;
}
.toc-item:hover {
  background: var(--dpim-surface-hover);
  color: var(--dpim-primary);
}
.toc-no {
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-text-3);
}

/* ── 分节 ── */
.help-section {
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-2);
  scroll-margin-top: var(--dpim-space-4);
}
.section-head {
  display: flex;
  align-items: center;
  gap: var(--dpim-space-3);
}
.section-no {
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-md);
  color: var(--dpim-primary);
  background: var(--dpim-primary-soft);
  border-radius: var(--dpim-radius-xs);
  padding: 0 var(--dpim-space-2);
}
.section-title {
  margin: 0;
  font-size: var(--dpim-fs-lg);
  font-weight: 500;
  color: var(--dpim-text);
}

/* ── 正文（全文不加粗；关键词与标签名用主色区分） ── */
.para {
  margin: 0;
  font-size: var(--dpim-fs-base);
  line-height: 1.8;
  color: var(--dpim-text-2);
}
.group-title {
  padding-top: var(--dpim-space-2);
}
.para-date {
  margin: 0;
  font-size: var(--dpim-fs-md);
  color: var(--dpim-text-3);
}
.link {
  color: var(--dpim-primary);
  text-decoration: none;
}
.link:hover {
  text-decoration: underline;
}
.help-list {
  margin: 0;
  padding-left: var(--dpim-space-5);
  display: flex;
  flex-direction: column;
  gap: var(--dpim-space-2);
}
.help-list li {
  font-size: var(--dpim-fs-base);
  line-height: 1.8;
  color: var(--dpim-text-2);
}
.ftag {
  /* 关键词只靠主色区分，不加粗（沿用旧版） */
  color: var(--dpim-primary);
}
code {
  font-family: var(--dpim-font-mono);
  font-size: var(--dpim-fs-sm);
  color: var(--dpim-primary);
  background: var(--dpim-primary-soft);
  border-radius: var(--dpim-radius-xs);
  padding: 0 var(--dpim-space-1);
}
</style>
