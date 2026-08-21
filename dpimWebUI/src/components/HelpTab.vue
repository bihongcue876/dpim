<template>
  <div class="help-page">
    <div class="help-inner">
      <!-- ── 页头 ── -->
      <header class="help-header">
        <h1 class="help-title">帮助</h1>
        <p class="help-subtitle">DPIM 双区智能记忆系统 · 使用说明</p>
      </header>

      <!-- ── 目录：点击平滑滚动到对应分节 ── -->
      <nav class="help-toc">
        <a
          v-for="s in sections"
          :key="s.id"
          class="toc-item"
          :href="`#help-${s.id}`"
          @click.prevent="scrollTo(s.id)"
        >
          <span class="toc-no">{{ s.no }}</span>
          <span class="toc-text">{{ s.title }}</span>
        </a>
      </nav>

      <!-- ── 分节内容 ── -->
      <section id="help-what" class="help-section">
        <div class="section-head">
          <span class="section-no">01</span>
          <h2 class="section-title">DPIM 是什么</h2>
        </div>
        <p class="para">
          双区智能存储系统（Double-Place Intelligence Memory, DPIM）是一个知识存储系统，
          存储结构特质为信息链与信息图谱分别管理并相互关联，使用 AI 能力且 AI 能力可选，
          不作为强制必定选项。
        </p>
      </section>

      <section id="help-features" class="help-section">
        <div class="section-head">
          <span class="section-no">02</span>
          <h2 class="section-title">基本功能</h2>
        </div>
        <p class="para">
          DPIM 用于存储数据，可通过与 AI 交互或信息手工贮存的方式管理，同时在前端可以使用 Agent
          功能存取信息。同时外部部分可以调用 DPIM 存储部分本身来调用和管理数据。
        </p>
        <p class="para">
          DPIM 的定位用途比较宽泛，以存储知识为基本要务，可以用于存储对话上下文、知识部分、流水账
          信息记录、要点管理、图谱关系集成等，基于知识可视、分区关联性贮存，设计双区结构。系统中，
          信息链（信息线层）数据用于原始数据存储，基本不可变，信息图谱用于数据关联展现，可以人工关联，
          也可以由内置 Agent 关联。
        </p>
        <p class="para">
          总而言之，此物的定位，不属于上下文存储器（如 Mem0），不属于纯粹知识库，不属于纯粹图谱，
          倒像是一个本地 Wiki（或者说不动的小图书馆），可以作为大智能体集合的器官，
          也可以作为一个有智能的信息管理器。
        </p>
      </section>

      <section id="help-usage" class="help-section">
        <div class="section-head">
          <span class="section-no">03</span>
          <h2 class="section-title">DPIM Web UI 使用方法</h2>
        </div>
        <p class="para">打开网页后，通过顶部六个标签页完成全部操作，各部分各自独立、互不依赖：</p>
        <ol class="help-list">
          <li><span class="ftag">配置</span>：连接后端地址、管理模型与提供商、设置管线角色、检索参数与存储路径。</li>
          <li><span class="ftag">信息列表</span>：查看事件，支持状态 / 类型筛选、内容修订与失败重试。</li>
          <li><span class="ftag">信息图</span>：查看、编辑知识图谱节点，观察数据间的关联。</li>
          <li><span class="ftag">检索</span>：综合检索 / 事件原文 / 知识节点三维检索，返回结果后可跨跳转定位。</li>
          <li><span class="ftag">信息传入</span>：手工录入信息，或经 Agent 管线自动构图入库。</li>
          <li><span class="ftag">帮助</span>：本页。</li>
        </ol>
      </section>

      <section id="help-faq" class="help-section">
        <div class="section-head">
          <span class="section-no">04</span>
          <h2 class="section-title">常见问题</h2>
        </div>
        <ul class="help-list">
          <li><span class="ftag">中文检索如何工作？</span>SQLite 内置 FTS5 分词器不识别中文，系统在召回不足时自动降级为 LIKE 检索，中英文均可正常使用，多词查询按词数主导计分。</li>
          <li><span class="ftag">没有配置 AI 模型还能用吗？</span>可以。AI 能力可选，未配置或断连时系统降级为基础全文检索存储，模型恢复后自动补偿补跑积压。</li>
          <li><span class="ftag">事件状态是什么意思？</span>raw（待处理）→ indexed（已索引）→ linked（已关联图谱，终态），异常为 failed / skipped；linked 为终态不可回退。</li>
          <li><span class="ftag">删除事件为什么可能被阻止？</span>删除前会预检该事件关联的 system / data 图谱节点，防止误删被锚定的证据源。</li>
          <li><span class="ftag">API 需要认证吗？</span>设置 <code>DPIM_API_KEY</code> 后所有请求需携带 <code>X-API-Key</code> 头；密钥在设置接口中一律掩码显示，修改时留空即保持不变。</li>
        </ul>
      </section>

      <section id="help-site" class="help-section">
        <div class="section-head">
          <span class="section-no">05</span>
          <h2 class="section-title">网站</h2>
        </div>
        <p class="para"><a class="link" href="https://github.com/bihongcue876/dpim" target="_blank" rel="noopener">https://github.com/bihongcue876/dpim</a></p>
        <p class="para-date">编写日期：2026 年 8 月 20 日</p>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
// ── 目录分节定义（标题锚点用；正文为上方静态模板） ──
const sections = [
  { no: '01', id: 'what', title: 'DPIM 是什么' },
  { no: '02', id: 'features', title: '基本功能' },
  { no: '03', id: 'usage', title: 'Web UI 使用方法' },
  { no: '04', id: 'faq', title: '常见问题' },
  { no: '05', id: 'site', title: '网站' },
] as const

function scrollTo(id: string) {
  document.getElementById(`help-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<style scoped>
/* 页面容器：全高 + 独立滚动（与其他 Tab 的 flex 全高布局约束配合） */
.help-page {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 24px 40px;
}

/* 内容列：限宽居中，长文行宽友好 */
.help-inner {
  max-width: 860px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--dpim-gap);
}

/* ── 页头 ── */
.help-header {
  padding: 6px 2px 2px;
}
.help-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--dpim-text);
}
.help-subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--dpim-text-3);
}

/* ── 目录 ── */
.help-toc {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 8px;
  padding: 12px 14px;
  background: var(--dpim-surface);
  border: 1px solid var(--dpim-border);
  border-radius: var(--dpim-radius-sm);
}
.toc-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  text-decoration: none;
  color: var(--dpim-text-2);
  transition: background 0.15s ease, color 0.15s ease;
}
.toc-item:hover {
  background: var(--dpim-surface-hover);
  color: var(--dpim-primary);
}
.toc-no {
  font-family: 'Cascadia Code', 'JetBrains Mono', Consolas, monospace;
  font-size: 12px;
  color: var(--dpim-text-3);
}

/* ── 分节卡片 ── */
.help-section {
  padding: 16px 18px;
  background: var(--dpim-surface);
  border: 1px solid var(--dpim-border);
  border-left: 3px solid var(--dpim-primary);
  border-radius: var(--dpim-radius-sm);
  box-shadow: var(--dpim-shadow);
  scroll-margin-top: 16px;
}
.section-head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.section-no {
  font-family: 'Cascadia Code', 'JetBrains Mono', Consolas, monospace;
  font-size: 13px;
  line-height: 22px;
  color: var(--dpim-primary);
  background: var(--dpim-primary-soft);
  border-radius: 6px;
  padding: 0 8px;
}
.section-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--dpim-text);
}

/* ── 正文 ── */
.para {
  margin: 12px 0 0;
  font-size: 14px;
  line-height: 1.8;
  color: var(--dpim-text-2);
}
.para + .para {
  margin-top: 10px;
}
.para-date {
  margin: 8px 0 0;
  font-size: 13px;
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
  margin: 12px 0 0;
  padding-left: 22px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.help-list li {
  font-size: 14px;
  line-height: 1.8;
  color: var(--dpim-text-2);
}
.ftag {
  color: var(--dpim-primary);
  font-weight: 500;
}
code {
  font-family: 'Cascadia Code', 'JetBrains Mono', Consolas, monospace;
  font-size: 12.5px;
  color: var(--dpim-primary);
  background: var(--dpim-primary-soft);
  border-radius: 4px;
  padding: 1px 5px;
}
</style>