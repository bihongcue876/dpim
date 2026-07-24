<template>
  <div ref="containerRef" class="graph-canvas" @dblclick="onDoubleClick">
    <div v-if="nodes.length === 0" class="empty-hint">暂无节点数据</div>
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

let svg: d3.Selection<SVGSVGElement, unknown, null, undefined> | null = null
let simulation: d3.Simulation<SimNode, SimLink> | null = null
let g: d3.Selection<SVGGElement, unknown, null, undefined> | null = null
let zoom: d3.ZoomBehavior<SVGSVGElement, unknown> | null = null

interface SimNode extends d3.SimulationNodeDatum {
  id: string
  title: string
  node_type: string
  confidence: number
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  relation: string
}

function destroy() {
  if (simulation) { simulation.stop(); simulation = null }
  if (svg) { svg.remove(); svg = null }
  g = null
  zoom = null
}

function init() {
  destroy()
  if (!containerRef.value) return
  const w = containerRef.value.clientWidth
  const h = containerRef.value.clientHeight
  if (w === 0 || h === 0) return

  svg = d3.select(containerRef.value)
    .append('svg')
    .attr('width', w)
    .attr('height', h)
    .style('cursor', 'grab')
    .style('display', 'block')

  zoom = d3.zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.1, 4])
    .on('zoom', (event) => {
      if (g) g.attr('transform', event.transform)
    })

  svg.call(zoom)
  g = svg.append('g')
}

function render() {
  if (!containerRef.value || !svg || !g) return
  const w = containerRef.value.clientWidth
  const h = containerRef.value.clientHeight
  if (props.nodes.length === 0) return

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

  const colorMap: Record<string, string> = {
    system: '#4a90d9',
    interaction: '#52c41a',
    data: '#fa8c16',
  }

  if (simulation) simulation.stop()

  simulation = d3.forceSimulation<SimNode>(simNodes)
    .force('link', d3.forceLink<SimNode, SimLink>(simLinks).id(d => d.id).distance(80))
    .force('charge', d3.forceManyBody().strength(-150))
    .force('center', d3.forceCenter(w / 2, h / 2))
    .force('collision', d3.forceCollide(30))

  const link = g
    .selectAll<SVGLineElement, SimLink>('line')
    .data(simLinks)
    .join('line')
    .attr('stroke', '#666')
    .attr('stroke-width', 1)
    .attr('stroke-opacity', 0.6)

  const node = g
    .selectAll<SVGCircleElement, SimNode>('circle')
    .data(simNodes)
    .join('circle')
    .attr('r', d => Math.max(6, Math.min(16, d.confidence * 14)))
    .attr('fill', d => colorMap[d.node_type] || '#999')
    .attr('stroke', d => d.id === props.highlightNodeId ? '#fff' : 'none')
    .attr('stroke-width', 2)
    .style('cursor', 'pointer')
    .call(d3.drag<SVGCircleElement, SimNode>()
      .on('start', (event, d) => {
        if (!event.active && simulation) simulation.alphaTarget(0.3).restart()
        d.fx = d.x
        d.fy = d.y
      })
      .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
      .on('end', (event, d) => {
        if (!event.active && simulation) simulation.alphaTarget(0)
        d.fx = null; d.fy = null
      }) as any,
    )
    .on('click', (_event, d) => emit('select-node', d.id))
    .on('dblclick', (_event, d) => emit('double-click-node', d.id))

  node.append('title').text(d => `${d.title}\n置信度: ${d.confidence}`)

  g.selectAll<SVGTextElement, SimNode>('text')
    .data(simNodes)
    .join('text')
    .text(d => d.title.length > 8 ? d.title.slice(0, 8) + '…' : d.title)
    .attr('font-size', 10)
    .attr('dx', 12)
    .attr('dy', 4)
    .attr('fill', '#ccc')

  simulation.on('tick', () => {
    link
      .attr('x1', d => (d.source as SimNode).x!)
      .attr('y1', d => (d.source as SimNode).y!)
      .attr('x2', d => (d.target as SimNode).x!)
      .attr('y2', d => (d.target as SimNode).y!)
    node.attr('cx', d => d.x!).attr('cy', d => d.y!)
    g!.selectAll<SVGTextElement, SimNode>('text')
      .attr('x', d => d.x!).attr('y', d => d.y!)
  })
}

function refresh() {
  init()
  render()
}

let resizeTimer: ReturnType<typeof setTimeout>
function onResize() {
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => refresh(), 200)
}

function onDoubleClick() {
  if (svg && zoom) {
    svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity)
  }
}

watch(() => [props.nodes, props.edges], () => refresh(), { deep: true })
watch(() => props.highlightNodeId, () => {
  if (g) {
    g.selectAll('circle')
      .attr('stroke', d => (d as SimNode).id === props.highlightNodeId ? '#fff' : 'none')
  }
})

onMounted(() => {
  refresh()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  destroy()
})
</script>

<style scoped>
.graph-canvas { width: 100%; height: 100%; overflow: hidden; background: #1a1a2e; position: relative; }
.empty-hint { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #666; font-size: 14px; }
</style>
