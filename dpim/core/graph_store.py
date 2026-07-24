"""信息图层：NetworkX 内存图 + JSON 原子持久化 + 反向索引"""

import json
import os
import tempfile
from pathlib import Path

import networkx as nx

from core.config import settings
from core.database import Database
from core.models import GraphEdge, GraphNode


class GraphStore:
    def __init__(self, db: Database, json_path: str | None = None) -> None:
        self.db = db
        self.json_path = json_path or settings.graph_json_path
        self.graph = nx.DiGraph()
        self.event_to_nodes: dict[str, list[str]] = {}
        self._dirty = False
        self._dirty_count = 0
        self._auto_save_threshold = 5

    async def load(self):
        path = Path(self.json_path)
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        nodes_data = data.get("nodes", {})
        edges_data = data.get("edges", [])
        for nid, ndata in nodes_data.items():
            node = GraphNode(**ndata)
            self.graph.add_node(nid, data=node)
        for edata in edges_data:
            edge = GraphEdge(**edata)
            self.graph.add_edge(edge.source, edge.target, data=edge)
        self._rebuild_reverse_index()

    async def save(self):
        path = Path(self.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        nodes_data = {}
        for nid, ndata in self.graph.nodes(data="data"):
            if ndata is not None:
                nodes_data[nid] = ndata.model_dump()
        edges_data = []
        for u, v, edata in self.graph.edges(data="data"):
            if edata is not None:
                edges_data.append(edata.model_dump())
        payload = {"nodes": nodes_data, "edges": edges_data}
        fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            os.unlink(tmp)
            raise
        self._dirty = False
        self._dirty_count = 0

    def _mark_dirty(self) -> None:
        """标记脏位并触发防抖式自动保存阈值计数。"""
        self._dirty = True
        self._dirty_count += 1

    def _rebuild_reverse_index(self):
        self.event_to_nodes.clear()
        for nid, ndata in self.graph.nodes(data="data"):
            if ndata is None:
                continue
            for sr in ndata.source_refs:
                if sr.event_id not in self.event_to_nodes:
                    self.event_to_nodes[sr.event_id] = []
                self.event_to_nodes[sr.event_id].append(nid)

    async def flush(self) -> None:
        """防抖式自动持久化：累计修改达到阈值后写入磁盘。

        调用方可定期或在安全点调用此方法，
        防抖逻辑保证批量操作时不会频繁 IO。
        """
        if self._dirty_count >= self._auto_save_threshold:
            await self.save()

    def add_node(self, node: GraphNode):
        self.graph.add_node(node.node_id, data=node)
        for sr in node.source_refs:
            self.event_to_nodes.setdefault(sr.event_id, []).append(node.node_id)
        self._mark_dirty()

    def remove_node(self, node_id: str) -> bool:
        ndata = self.graph.nodes.get(node_id, {}).get("data")
        if ndata is None:
            return False
        for sr in ndata.source_refs:
            nodes = self.event_to_nodes.get(sr.event_id, [])
            if node_id in nodes:
                nodes.remove(node_id)
        self.graph.remove_node(node_id)
        self._mark_dirty()
        return True

    def add_edge(self, edge: GraphEdge):
        self.graph.add_edge(edge.source, edge.target, data=edge)
        self._mark_dirty()

    def remove_edge(self, source: str, target: str) -> bool:
        if self.graph.has_edge(source, target):
            self.graph.remove_edge(source, target)
            self._mark_dirty()
            return True
        return False

    def invalidate_source_ref(self, event_id: str, new_valid: bool = False):
        for nid in self.event_to_nodes.get(event_id, []):
            ndata = self.graph.nodes.get(nid, {}).get("data")
            if ndata is None:
                continue
            for sr in ndata.source_refs:
                if sr.event_id == event_id:
                    sr.valid = new_valid
            self.graph.nodes[nid]["data"] = ndata
        self._mark_dirty()

    def get_node(self, node_id: str) -> GraphNode | None:
        ndata = self.graph.nodes.get(node_id, {}).get("data")
        return ndata

    def get_edge(self, source: str, target: str) -> GraphEdge | None:
        edata = self.graph.edges.get((source, target), {}).get("data")
        return edata

    def ego_graph(self, seeds: list[str], hops: int = 2) -> dict[str, float]:
        result: dict[str, float] = {}
        for seed in seeds:
            if seed not in self.graph:
                continue
            ego = nx.ego_graph(self.graph, seed, radius=hops, center=False)
            for n in ego.nodes():
                hop_dist = nx.shortest_path_length(self.graph, seed, n)
                score = 1.0 / (hop_dist + 1)
                if n not in result or score > result[n]:
                    result[n] = score
        return result

    def get_nodes_for_event(self, event_id: str) -> list[str]:
        return self.event_to_nodes.get(event_id, [])

    def total_nodes(self) -> int:
        return self.graph.number_of_nodes()

    def node_counts_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {"system": 0, "interaction": 0, "data": 0}
        for _, ndata in self.graph.nodes(data="data"):
            if ndata is not None:
                t = ndata.node_type.value
                counts[t] = counts.get(t, 0) + 1
        return counts

    async def upsert_node_fts(self, node_id: str, title: str, content: str):
        await self.db.conn.execute(
            "DELETE FROM node_fts WHERE node_id = ?", (node_id,)
        )
        await self.db.conn.execute(
            "INSERT INTO node_fts (node_id, title, content) VALUES (?, ?, ?)",
            (node_id, title, content),
        )
        await self.db.conn.commit()

    async def delete_node_fts(self, node_id: str):
        await self.db.conn.execute("DELETE FROM node_fts WHERE node_id = ?", (node_id,))
        await self.db.conn.commit()

    async def search_node_fts(self, query: str, limit: int = 100) -> list[dict]:
        cursor = await self.db.conn.execute(
            "SELECT node_id,title,content,rank FROM node_fts"
            " WHERE node_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    @property
    def dirty(self) -> bool:
        return self._dirty
