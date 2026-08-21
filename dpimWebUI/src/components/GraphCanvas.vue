<template>
  <div ref="containerRef" class="graph-canvas" @dblclick="resetZoom">
    <div v-if="!initialized" class="empty-hint">初始化中…</div>
    <div v-else-if="nodes.length === 0" class="empty-hint">暂无节点数据</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
import Graph from 'graphology'
import forceatlas2 from 'graphology-layout-forceatlas2'
import type { NodeListItem, EdgeInfo } from '@/api/client'

const props = defineProps<{
  nodes: NodeListItem[]
  edges: EdgeInfo[]
  highlightNodeId: string | null
  refreshEpoch?: number
}>()

const emit = defineEmits<{
  'select-node': [id: string]
  'double-click-node': [id: string]
  'select-edge': [source: string, target: string, relation: string]
}>()

const containerRef = ref<HTMLDivElement>()
const initialized = ref(false)

// ---------- D3 state (not reactive) ----------
let svg: SVGSVGElement | null = null
let svgSel: d3.Selection<SVGSVGElement, unknown, null, undefined> | null = null
let mainG: d3.Selection<SVGGElement, unknown, null, undefined> | null = null
let simulation: d3.Simulation<SimNode, SimLink> | null = null
let zoom: d3.ZoomBehavior<SVGSVGElement, unknown> | null = null
let resizeObs: ResizeObserver | null = null
let resizeTimer: ReturnType<typeof setTimeout>
let destroyed = false

interface SimNode extends d3.SimulationNodeDatum {
  id: string; title: string; node_type: string; confidence: number
}
interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  relation: string
}

const COLOR_MAP: Record<string, string> = {
  system: '#5b8cff',       // 蓝
  interaction: '#3fb68b',  // 绿
  data: '#4cb5f5',         // 浅蓝
}

/** 获取圆半径：根据置信度 + 最少可见大小 */
function nodeRadius(n: SimNode): number {
  return Math.max(8, Math.min(20, 6 + n.confidence * 14))
}

function destroy() {
  destroyed = true
  if (simulation) { simulation.stop(); simulation = null }
  if (svg && svg.parentNode) svg.parentNode.removeChild(svg)
  svg = null; svgSel = null; mainG = null; zoom = null
  // 注意：不 disconnect ResizeObserver —— 观察的是常驻容器 div，
  // 重建 SVG 不影响观察；断开会导致后续容器尺寸变化（面板收起等）无人响应
}

function build() {
  if (!containerRef.value) return
  destroy()
  destroyed = false

  const w = containerRef.value.clientWidth || 400
  const h = containerRef.value.clientHeight || 300
  if (w < 10 || h < 10) { initialized.value = true; return }

  // SVG
  svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  svg.setAttribute('width', String(w))
  svg.setAttribute('height', String(h))
  svg.style.display = 'block'
  svg.style.cursor = 'grab'
  containerRef.value.appendChild(svg)
  svgSel = d3.select(svg)

  // Arrow marker
  const defs = svgSel.append('defs')
  defs.append('marker')
    .attr('id', 'arrow')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 22)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#666')

  // Zoom
  zoom = d3.zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.1, 5])
    .on('zoom', (event) => {
      if (mainG) mainG.attr('transform', event.transform)
    })
  svgSel.call(zoom)

  // Main group
  mainG = svgSel.append('g')

  initialized.value = true
}

function render() {
  if (!mainG || !svg || !containerRef.value) return
  if (props.nodes.length === 0) return

  const w = containerRef.value.clientWidth || 400
  const h = containerRef.value.clientHeight || 300

  const simNodes: SimNode[] = props.nodes.map(n => ({
    id: n.node_id,
    title: n.title,
    node_type: n.node_type,
    confidence: n.confidence,
  }))
  const nodeIds = new Set(simNodes.map(n => n.id))
  const simLinks: SimLink[] = props.edges
    .filter(e => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map(e => ({ source: e.source, target: e.target, relation: e.relation }))

  if (simulation) simulation.stop()

  // --- 连通分量检测（先分离再布局，分量间互不粘连） ---
  const adj = new Map<string, string[]>()
  for (const n of simNodes) adj.set(n.id, [])
  const rawEdges: [string, string][] = []
  for (const link of simLinks) {
    const s = typeof link.source === 'string' ? link.source : (link.source as SimNode).id
    const t = typeof link.target === 'string' ? link.target : (link.target as SimNode).id
    if (!adj.has(s) || !adj.has(t)) continue
    adj.get(s)!.push(t); adj.get(t)!.push(s)
    rawEdges.push([s, t])
  }
  const seen = new Set<string>()
  const components: string[][] = []
  for (const n of simNodes) {
    if (seen.has(n.id)) continue
    const comp = [n.id]; seen.add(n.id)
    const queue = [n.id]
    while (queue.length) {
      const cur = queue.shift()!
      for (const nb of adj.get(cur) || []) {
        if (!seen.has(nb)) { seen.add(nb); queue.push(nb); comp.push(nb) }
      }
    }
    components.push(comp)
  }
  // 稳定排序：大分量在前，同规模按首节点出现序 —— 同样数据每次刷新排布一致
  const orderOf = new Map(simNodes.map((n, i) => [n.id, i] as const))
  components.sort((a, b) => b.length - a.length || (orderOf.get(a[0]) ?? 0) - (orderOf.get(b[0]) ?? 0))

  // 边按分量归类（一次性，避免每分量全量过滤）
  const compIndexOf = new Map<string, number>()
  components.forEach((c, i) => c.forEach(id => compIndexOf.set(id, i)))
  const compEdgeLists: [string, string][][] = components.map(() => [])
  for (const [s, t] of rawEdges) {
    const ci = compIndexOf.get(s)
    if (ci != null && compIndexOf.get(t) === ci) compEdgeLists[ci].push([s, t])
  }

  // --- 确定性初始位置：黄金角螺旋（phyllotaxis），替代 Math.random ---
  function spiralInit(ids: string[]): Map<string, { x: number; y: number }> {
    const pos = new Map<string, { x: number; y: number }>()
    ids.forEach((id, i) => {
      const r = 14 * Math.sqrt(i + 1)
      const a = i * 2.399963229728653
      pos.set(id, { x: r * Math.cos(a), y: r * Math.sin(a) })
    })
    return pos
  }

  // --- 每分量独立 FA2：确定性起点 → 收敛结果稳定；分量间无引力干扰 ---
  function layoutComponent(ids: string[], edgeSet: [string, string][]): Map<string, { x: number; y: number }> {
    const init = spiralInit(ids)
    if (ids.length <= 2) return init // 1-2 个节点：初始位置即最终位置
    try {
      const g = new Graph()
      for (const [id, p] of init) g.addNode(id, { x: p.x, y: p.y })
      for (const [s, t] of edgeSet) {
        try { g.addEdge(s, t) } catch { /* 重复边跳过 */ }
      }
      const settings = forceatlas2.inferSettings(g)
      const out = forceatlas2(g, {
        iterations: 100,
        settings: { ...settings, gravity: 1, barnesHutOptimize: true },
      })
      const final = new Map<string, { x: number; y: number }>()
      for (const id of ids) {
        const p = out[id]
        if (p && isFinite(p.x) && isFinite(p.y)) final.set(id, { x: p.x, y: p.y })
        else final.set(id, init.get(id)!)
      }
      return final
    } catch {
      return init // FA2 失败回退：确定性螺旋位置
    }
  }

  // --- 分量网格打包：每个分量独占一格，从根上分开 ---
  const nodeById = new Map(simNodes.map(n => [n.id, n] as const))
  const cols = Math.max(1, Math.ceil(Math.sqrt(components.length)))
  const rows = Math.ceil(components.length / cols)
  const pad = 30
  const cellW = (w - pad * 2) / cols
  const cellH = (h - pad * 2) / rows
  const compCenters = new Map<string, { x: number; y: number }>()
  components.forEach((comp, idx) => {
    const col = idx % cols
    const row = Math.floor(idx / cols)
    const cellCx = pad + cellW * (col + 0.5)
    const cellCy = pad + cellH * (row + 0.5)
    const pos = layoutComponent(comp, compEdgeLists[idx])

    // 分量包围盒 → 等比缩放进本格（四周留边距），居中于格心
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
    for (const p of pos.values()) {
      minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x)
      minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y)
    }
    const bw = maxX - minX || 1, bh = maxY - minY || 1
    const scale = Math.min((cellW - 72) / bw, (cellH - 72) / bh)
    const safeScale = isFinite(scale) && scale > 0 ? Math.min(scale, 4) : 1
    const ccx = (minX + maxX) / 2, ccy = (minY + maxY) / 2
    for (const id of comp) {
      const p = pos.get(id)!
      const node = nodeById.get(id)
      if (!node) continue
      node.x = cellCx + (p.x - ccx) * safeScale
      node.y = cellCy + (p.y - ccy) * safeScale
      compCenters.set(id, { x: cellCx, y: cellCy })
    }
  })

  // FA2/网格定好位置后，D3 仅负责交互与轻微碰撞避让（link 力弱化，避免撑开已缩放的分量）
  simulation = d3.forceSimulation<SimNode>(simNodes)
    .force('link', d3.forceLink<SimNode, SimLink>(simLinks)
      .id(d => d.id).distance(80).strength(0.05))
    .force('collision', d3.forceCollide<SimNode>(d => nodeRadius(d) + 20).strength(0.5))
    .force('x', d3.forceX<SimNode>(d => (compCenters.get(d.id)?.x ?? w / 2)).strength(0.01))
    .force('y', d3.forceY<SimNode>(d => (compCenters.get(d.id)?.y ?? h / 2)).strength(0.01))
    .alpha(0.12)
    .alphaDecay(0.15)
    .velocityDecay(0.5)

  // ---- Edges with curvature ----
  // 按无向对分组（A|B 和 B|A 视为同一组），双向边自动错开弯曲
  const pairGroups = new Map<string, { fwd: any[]; rev: any[] }>()
  for (const link of simLinks) {
    const src = typeof link.source === 'object' ? (link.source as SimNode).id : String(link.source)
    const tgt = typeof link.target === 'object' ? (link.target as SimNode).id : String(link.target)
    const pairKey = src < tgt ? `${src}|${tgt}` : `${tgt}|${src}`
    if (!pairGroups.has(pairKey)) pairGroups.set(pairKey, { fwd: [], rev: [] })
    const group = pairGroups.get(pairKey)!
    if (src < tgt) group.fwd.push(link)
    else group.rev.push(link)
  }
  // 为每个无向对分配曲率
  for (const [, group] of pairGroups) {
    const { fwd, rev } = group
    const fwdCount = fwd.length
    const revCount = rev.length
    const total = fwdCount + revCount
    if (total <= 1) {
      // 只有一条边，直线
      for (const link of fwd) (link as any).curvature = 0
      for (const link of rev) (link as any).curvature = 0
    } else if (revCount === 0 || fwdCount === 0) {
      // 只有单向的多条边：对称分布
      const count = Math.max(fwdCount, revCount)
      const links = fwdCount > 0 ? fwd : rev
      links.forEach((link: any, idx: number) => {
        const spacing = 0.35
        ;(link as any).curvature = count === 1 ? 0 : (idx - (count - 1) / 2) * spacing
      })
    } else {
      // 双向边：正方向和反方向用相同 curvature 符号
      // 注意：反方向的 (dx,dy) 天然反转，法线方向自动相反，所以 curvature 符号相同即可实现错开
      const spacing = 0.35
      fwd.forEach((link: any, idx: number) => {
        const subOffset = fwdCount > 1 ? (idx - (fwdCount - 1) / 2) * spacing * 0.5 : 0
        ;(link as any).curvature = spacing + subOffset
      })
      rev.forEach((link: any, idx: number) => {
        const subOffset = revCount > 1 ? (idx - (revCount - 1) / 2) * spacing * 0.5 : 0
        ;(link as any).curvature = spacing + subOffset
      })
    }
  }

  const linkG = mainG.selectAll<SVGGElement, any>('g.link-group')
    .data(simLinks, (d: any) => {
      const src = typeof d.source === 'object' ? (d.source as SimNode).id : String(d.source)
      const tgt = typeof d.target === 'object' ? (d.target as SimNode).id : String(d.target)
      return `${src}|${tgt}`
    })
    .join('g')
    .attr('class', 'link-group')

  // 用 path 代替 line，支持弯曲
  linkG.selectAll<SVGPathElement, any>('path')
    .data(d => [d])
    .join('path')
    .attr('fill', 'none')
    .attr('stroke', '#7c8694')
    .attr('stroke-width', 1.2)
    .attr('stroke-opacity', 0.45)
    .attr('marker-end', 'url(#arrow)')
    .style('cursor', 'pointer')

  // Edge click
  linkG.on('click', (event: MouseEvent, d: any) => {
    event.stopPropagation()
    const src = typeof d.source === 'object' ? (d.source as SimNode).id : String(d.source)
    const tgt = typeof d.target === 'object' ? (d.target as SimNode).id : String(d.target)
    emit('select-edge', src, tgt, d.relation || '')
  })

  linkG.selectAll<SVGTextElement, any>('text')
    .data(d => [d])
    .join('text')
    .text(d => d.relation)
    .attr('font-size', 9)
    .attr('fill', '#777')
    .attr('text-anchor', 'middle')
    .attr('dy', -6)

  // ---- Nodes ----
  const nodeG = mainG.selectAll<SVGGElement, SimNode>('g.node-group')
    .data(simNodes, d => d.id)
    .join('g')
    .attr('class', 'node-group')

  // Circle with glow for highlight
  nodeG.selectAll<SVGCircleElement, SimNode>('circle')
    .data(d => [d])
    .join('circle')
    .attr('r', d => nodeRadius(d))
    .attr('fill', d => COLOR_MAP[d.node_type] || '#888')
    .attr('stroke', d => d.id === props.highlightNodeId ? '#fff' : 'transparent')
    .attr('stroke-width', d => d.id === props.highlightNodeId ? 3 : 2)
    .attr('stroke-opacity', d => d.id === props.highlightNodeId ? 0.9 : 0)
    .style('cursor', 'pointer')
    .style('transition', 'stroke-opacity 0.15s')

  // Label
  nodeG.selectAll<SVGTextElement, SimNode>('text.label')
    .data(d => [d])
    .join('text')
    .attr('class', 'label')
    .text(d => d.title.length > 12 ? d.title.slice(0, 12) + '…' : d.title)
    .attr('font-size', 10)
    .attr('dx', d => nodeRadius(d) + 5)
    .attr('dy', 4)
    .attr('fill', '#bbb')
    .style('pointer-events', 'none')

  // Confidence badge (small, inside circle bottom-right)
  nodeG.selectAll<SVGTextElement, SimNode>('text.badge')
    .data(d => [d])
    .join('text')
    .attr('class', 'badge')
    .text(d => d.confidence.toFixed(2))
    .attr('font-size', 7)
    .attr('dx', d => nodeRadius(d) + 5)
    .attr('dy', 15)
    .attr('fill', '#666')
    .style('pointer-events', 'none')

  // Highlight glow: extra translucent ring behind the node
  nodeG.selectAll<SVGCircleElement, SimNode>('circle.glow')
    .data(d => d.id === props.highlightNodeId ? [d] : [])
    .join('circle')
    .attr('class', 'glow')
    .attr('r', d => nodeRadius(d) + 5)
    .attr('fill', 'none')
    .attr('stroke', '#fff')
    .attr('stroke-width', 1)
    .attr('stroke-opacity', 0.3)
    .style('pointer-events', 'none')

  // Drag：拖动固定节点；松手后停留在拖放位置（不弹回），邻接节点仅轻微跟随（一点弹性）
  nodeG.call(d3.drag<SVGGElement, SimNode>()
    .on('start', (event, d) => {
      // 微量回温，让邻接节点轻微跟随但不弹跳
      if (!event.active && simulation) simulation.alphaTarget(0.05).restart()
      d.fx = d.x; d.fy = d.y
    })
    .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
    .on('end', (event, d) => {
      if (!event.active && simulation) simulation.alphaTarget(0)
      // 关键：保持 fx/fy，节点停留在拖放位置，不记忆、不弹回
      d.fx = d.x; d.fy = d.y
    }) as any)

  // Click / dblclick on nodes
  nodeG.on('click', (_event, d) => emit('select-node', d.id))
  nodeG.on('dblclick', (_event, d) => emit('double-click-node', d.id))

  // Hover tooltip
  nodeG.append('title').text(d => `${d.title}\n类型: ${d.node_type}\n置信度: ${d.confidence}`)

  // Simulation tick — draw curved paths
  simulation.on('tick', () => {
    linkG.each(function (d: any) {
      const src = typeof d.source === 'object' ? (d.source as SimNode) : null
      const tgt = typeof d.target === 'object' ? (d.target as SimNode) : null
      if (!src || !tgt) return
      const x1 = src.x!, y1 = src.y!, x2 = tgt.x!, y2 = tgt.y!

      // Quadratic bezier with perpendicular offset for curvature
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2
      const dx = x2 - x1, dy = y2 - y1
      const len = Math.sqrt(dx * dx + dy * dy) || 1
      const curvature = d.curvature || 0
      const nx = -dy / len * 80 * curvature
      const ny = dx / len * 80 * curvature
      const cx = mx + nx, cy = my + ny

      d3.select(this).select('path')
        .attr('d', `M${x1},${y1} Q${cx},${cy} ${x2},${y2}`)

      // Edge label at the midpoint with slight perpendicular offset
      const labelOffset = 10  // 距边线 10px
      const nx2 = -dy / len * labelOffset
      const ny2 = dx / len * labelOffset
      d3.select(this).select('text')
        .attr('x', mx + nx2)
        .attr('y', my + ny2)
    })
    nodeG.attr('transform', d => `translate(${(d as SimNode).x!},${(d as SimNode).y!})`)
  })
}

function refresh() {
  if (destroyed) return
  build()
  render()
}

// Watch data changes
watch(() => [props.nodes, props.edges], () => {
  if (!destroyed) refresh()
}, { deep: true })

// Watch refreshEpoch (e.g. panel toggle) — force full re-render
// 面板收起/展开带 0.25s max-height 过渡：立即重建会拿到过渡前的旧尺寸，
// 等 300ms 过渡结束后再按最终尺寸重建（ResizeObserver 兜底）
watch(() => props.refreshEpoch, () => {
  setTimeout(() => { if (!destroyed) refresh() }, 300)
})

// Watch highlight changes
watch(() => props.highlightNodeId, (newVal) => {
  if (destroyed || !mainG) return
  // Update circle stroke
  mainG.selectAll<SVGCircleElement, SimNode>('circle:not(.glow)')
    .attr('stroke', d => d.id === newVal ? '#fff' : 'transparent')
    .attr('stroke-width', d => d.id === newVal ? 3 : 2)
    .attr('stroke-opacity', d => d.id === newVal ? 0.9 : 0)
  // Update glow
  const glow = mainG.selectAll<SVGCircleElement, SimNode>('circle.glow')
    .data(newVal ? (props.nodes.find(n => n.node_id === newVal) ? [{ id: newVal } as SimNode] : []) : [], d => d.id)
  glow.exit().remove()
  glow.join('circle')
    .attr('class', 'glow')
    .attr('r', d => nodeRadius(d) + 5)
    .attr('fill', 'none')
    .attr('stroke', '#fff')
    .attr('stroke-width', 1)
    .attr('stroke-opacity', 0.3)
    .style('pointer-events', 'none')
})

onMounted(async () => {
  await new Promise(r => requestAnimationFrame(r))
  if (containerRef.value) {
    resizeObs = new ResizeObserver(() => {
      clearTimeout(resizeTimer)
      resizeTimer = setTimeout(() => refresh(), 200)
    })
    resizeObs.observe(containerRef.value)
  }
  refresh()
})

onUnmounted(() => {
  if (resizeObs) { resizeObs.disconnect(); resizeObs = null }
  clearTimeout(resizeTimer)
  destroy()
})

function resetZoom() {
  if (svgSel && zoom) {
    svgSel.transition().duration(500).call(zoom.transform, d3.zoomIdentity)
  }
}
</script>

<style scoped>
.graph-canvas {
  width: 100%; height: 100%; overflow: hidden; position: relative;
  background-color: var(--dpim-bg, #0e1217);
  background-image: radial-gradient(rgba(255,255,255,0.05) 1px, transparent 1px);
  background-size: 22px 22px;
}
.empty-hint {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  color: var(--dpim-text-3, #7c8694); font-size: 14px;
}
</style>
