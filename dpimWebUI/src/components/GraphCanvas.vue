<template>
  <div ref="containerRef" class="graph-canvas" @dblclick="resetZoom">
    <div v-if="!initialized" class="empty-hint">初始化中…</div>
    <div v-else-if="nodes.length === 0" class="empty-hint">暂无节点数据</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as d3 from 'd3'
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
  if (resizeObs) { resizeObs.disconnect(); resizeObs = null }
  if (simulation) { simulation.stop(); simulation = null }
  if (svg && svg.parentNode) svg.parentNode.removeChild(svg)
  svg = null; svgSel = null; mainG = null; zoom = null
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

  // 力导向参数：保留一点弹性（平滑铺开/落定），但不过度回弹
  simulation = d3.forceSimulation<SimNode>(simNodes)
    .force('link', d3.forceLink<SimNode, SimLink>(simLinks)
      .id(d => d.id).distance(120).strength(0.25))
    .force('charge', d3.forceManyBody().strength(-280))
    .force('center', d3.forceCenter(w / 2, h / 2))
    .force('collision', d3.forceCollide(d => nodeRadius(d as SimNode) + 8).strength(0.8))
    .alphaDecay(0.045)      // 稍快冷却，缩短初始摆动时长
    .velocityDecay(0.5)     // 更高摩擦阻尼，减少弹性震荡

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
      // 轻微回温，让邻接节点有一点弹性跟随，但不剧烈
      if (!event.active && simulation) simulation.alphaTarget(0.12).restart()
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
watch(() => props.refreshEpoch, () => {
  if (!destroyed) refresh()
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
