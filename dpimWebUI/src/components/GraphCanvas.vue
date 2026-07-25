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
}>()

const emit = defineEmits<{
  'select-node': [id: string]
  'double-click-node': [id: string]
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
  system: '#4a90d9',
  interaction: '#52c41a',
  data: '#fa8c16',
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

  // Defs: arrow marker
  const defs = svgSel.append('defs')
  defs.append('marker')
    .attr('id', 'arrow')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 20)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#888')

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

  simulation = d3.forceSimulation<SimNode>(simNodes)
    .force('link', d3.forceLink<SimNode, SimLink>(simLinks)
      .id(d => d.id).distance(100).strength(0.4))
    .force('charge', d3.forceManyBody().strength(-200))
    .force('center', d3.forceCenter(w / 2, h / 2))
    .force('collision', d3.forceCollide(35).strength(0.7))
    .alphaDecay(0.02)

  // Edges
  const linkG = mainG.selectAll<SVGGElement, SimLink>('g.link-group')
    .data(simLinks)
    .join('g')
    .attr('class', 'link-group')

  linkG.selectAll<SVGLineElement, SimLink>('line')
    .data(d => [d])
    .join('line')
    .attr('stroke', '#555')
    .attr('stroke-width', 1.5)
    .attr('stroke-opacity', 0.5)
    .attr('marker-end', 'url(#arrow)')

  linkG.selectAll<SVGTextElement, SimLink>('text')
    .data(d => [d])
    .join('text')
    .text(d => d.relation)
    .attr('font-size', 9)
    .attr('fill', '#888')
    .attr('text-anchor', 'middle')
    .attr('dy', -4)

  // Nodes
  const nodeG = mainG.selectAll<SVGGElement, SimNode>('g.node-group')
    .data(simNodes)
    .join('g')
    .attr('class', 'node-group')

  // Circle
  nodeG.selectAll<SVGCircleElement, SimNode>('circle')
    .data(d => [d])
    .join('circle')
    .attr('r', d => Math.max(7, Math.min(18, d.confidence * 16)))
    .attr('fill', d => COLOR_MAP[d.node_type] || '#999')
    .attr('stroke', d => d.id === props.highlightNodeId ? '#fff' : 'transparent')
    .attr('stroke-width', 2.5)
    .style('cursor', 'pointer')
    .style('transition', 'stroke 0.2s')

  // Label
  nodeG.selectAll<SVGTextElement, SimNode>('text.label')
    .data(d => [d])
    .join('text')
    .attr('class', 'label')
    .text(d => d.title.length > 10 ? d.title.slice(0, 10) + '…' : d.title)
    .attr('font-size', 10)
    .attr('dx', 14)
    .attr('dy', 4)
    .attr('fill', '#bbb')
    .style('pointer-events', 'none')

  // Confidence badge
  nodeG.selectAll<SVGTextElement, SimNode>('text.badge')
    .data(d => [d])
    .join('text')
    .attr('class', 'badge')
    .text(d => d.confidence.toFixed(2))
    .attr('font-size', 7)
    .attr('dx', 14)
    .attr('dy', 14)
    .attr('fill', '#666')
    .style('pointer-events', 'none')

  // Drag
  nodeG.call(d3.drag<SVGGElement, SimNode>()
    .on('start', (event, d) => {
      if (!event.active && simulation) simulation.alphaTarget(0.3).restart()
      d.fx = d.x; d.fy = d.y
    })
    .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
    .on('end', (_event, d) => {
      d.fx = null; d.fy = null
    }) as any)

  // Click / dblclick on nodes
  nodeG.on('click', (_event, d) => emit('select-node', d.id))
  nodeG.on('dblclick', (_event, d) => emit('double-click-node', d.id))

  // Hover tooltip
  nodeG.append('title').text(d => `${d.title}\n类型: ${d.node_type}\n置信度: ${d.confidence}`)

  // Simulation tick — use join-based selections for direct DOM access
  simulation.on('tick', () => {
    linkG.each(function (d: any) {
      const ld = d as SimLink
      const src = typeof ld.source === 'object' ? (ld.source as SimNode) : null
      const tgt = typeof ld.target === 'object' ? (ld.target as SimNode) : null
      d3.select(this).select('line')
        .attr('x1', src?.x ?? 0).attr('y1', src?.y ?? 0)
        .attr('x2', tgt?.x ?? 0).attr('y2', tgt?.y ?? 0)
      if (src && tgt) {
        d3.select(this).select('text')
          .attr('x', (src.x! + tgt.x!) / 2)
          .attr('y', (src.y! + tgt.y!) / 2)
      }
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

// Watch highlight changes — just update stroke, no full re-render
watch(() => props.highlightNodeId, () => {
  if (!destroyed && mainG) {
    mainG.selectAll<SVGCircleElement, SimNode>('circle')
      .attr('stroke', d => d.id === props.highlightNodeId ? '#fff' : 'transparent')
  }
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
.graph-canvas { width: 100%; height: 100%; overflow: hidden; background: #1a1a2e; position: relative; }
.empty-hint { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #666; font-size: 14px; }
</style>
