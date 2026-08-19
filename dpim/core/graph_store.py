"""信息图层：NetworkX 内存图 + JSON 原子持久化 + 反向索引"""

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

import networkx as nx

from core.config import settings
from core.database import Database
from core.models import GraphEdge, GraphNode, SourceRef

logger = logging.getLogger(__name__)


class GraphStore:
    def __init__(self, db: Database, json_path: str | None = None) -> None:
        self.db = db
        self.json_path = json_path or settings.graph_json_path
        self.graph = nx.DiGraph()
        self.event_to_nodes: dict[str, list[str]] = {}
        self._dirty = False

    async def load(self):
        """从 graph.json 加载图谱（损坏自动回退 .bak / 空图），并重建 node_fts。

        node_fts 以内存图为唯一真源全量重建：解决手动编辑 graph.json、
        清空图谱、备份恢复后索引与图层不一致的问题（新节点检索不到、
        已删节点检索残留）。
        """
        path = Path(self.json_path)
        data: dict | None = None
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("graph.json 解析失败，尝试从备份恢复: %s", exc)
                backup = path.with_suffix(".json.bak")
                if backup.exists():
                    try:
                        data = json.loads(backup.read_text(encoding="utf-8"))
                        logger.warning("已从备份 %s 恢复图谱", backup)
                    except (json.JSONDecodeError, OSError) as bexc:
                        logger.error("graph.json 备份亦损坏，以空图启动: %s", bexc)
                        data = None
                else:
                    logger.error("graph.json 无可用备份，以空图启动（请检查存储文件）")
                    data = None
        if data is not None:
            nodes_data = data.get("nodes", {})
            edges_data = data.get("edges", [])
            try:
                for nid, ndata in nodes_data.items():
                    node = GraphNode(**ndata)
                    self.graph.add_node(nid, data=node)
                for edata in edges_data:
                    edge = GraphEdge(**edata)
                    self.graph.add_edge(edge.source, edge.target, data=edge)
            except Exception as exc:
                logger.error("图谱节点/边构建失败，以空图启动: %s", exc)
                self.graph.clear()
            else:
                self._rebuild_reverse_index()
                # 留存最近一次可用快照，供下次加载损坏时恢复
                try:
                    shutil.copy(path, path.with_suffix(".json.bak"))
                except OSError as exc:
                    logger.warning("备份 graph.json 失败（不影响运行）: %s", exc)
        # 统一收尾：node_fts 全量重建（含空图/损坏路径，清除残留索引）
        await self.rebuild_node_fts()

    async def rebuild_node_fts(self) -> None:
        """全量重建 node_fts：以内存图为唯一真源（先清后插，一次提交）。"""
        await self.db.conn.execute("DELETE FROM node_fts")
        rows = [
            (nid, ndata.title, ndata.content)
            for nid, ndata in self.graph.nodes(data="data")
            if ndata is not None
        ]
        if rows:
            await self.db.conn.executemany(
                "INSERT INTO node_fts (node_id, title, content) VALUES (?, ?, ?)",
                rows,
            )
        await self.db.conn.commit()

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
        # 保存成功后同步留存快照：下次加载损坏时可从最近一次成功保存恢复
        try:
            shutil.copy(path, path.with_suffix(".json.bak"))
        except OSError as exc:
            logger.warning("备份 graph.json 失败（不影响运行）: %s", exc)

    def _mark_dirty(self) -> None:
        """标记脏位：任何内存图修改后必须调用，flush/save 据此落盘。"""
        self._dirty = True

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
        """持久化：有脏位即写盘。

        写路径统一语义——任何修改（add/remove/update）标记脏位后，
        flush/save 必落盘，杜绝「修改不落盘」的静默丢失。
        实验规模下图 JSON 全量序列化开销可忽略，不再做批量阈值防抖。
        """
        if self._dirty:
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

    def clear_all(self):
        """清空所有节点和边"""
        self.graph.clear()
        self.event_to_nodes.clear()
        self._mark_dirty()

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

    def sync_source_ref_hash(self, event_id: str, new_hash: str) -> None:
        """事件内容修订后，同步引用该事件节点的 source_refs[].hash。

        保证「hash 快照与事件现 content_hash 一致」，供 reconcile 做锚定核对时
        不会因正常修订而误判为来源漂移。
        """
        nids = self.event_to_nodes.get(event_id, [])
        if not nids:
            return
        for nid in nids:
            ndata = self.graph.nodes.get(nid, {}).get("data")
            if ndata is None:
                continue
            for sr in ndata.source_refs:
                if sr.event_id == event_id:
                    sr.hash = new_hash
            self.graph.nodes[nid]["data"] = ndata
        self._mark_dirty()

    def get_node(self, node_id: str) -> GraphNode | None:
        ndata = self.graph.nodes.get(node_id, {}).get("data")
        return ndata

    def update_node(
        self,
        node_id: str,
        *,
        content: str | None = None,
        confidence: float | None = None,
    ) -> GraphNode | None:
        """就地更新节点字段并标记脏位（调用方随后 flush/save 落盘）。

        所有「修改已有节点」的路径都应走此方法，避免直接改内存图数据
        而遗漏脏位标记，导致修改永不落盘、重启即丢。
        """
        node = self.get_node(node_id)
        if node is None:
            return None
        if content is not None:
            node.content = content
        if confidence is not None:
            node.confidence = confidence
        self.graph.nodes[node_id]["data"] = node
        self._mark_dirty()
        return node

    def merge_into(
        self,
        target_id: str,
        *,
        event_id: str,
        content_hash: str = "",
        content: str | None = None,
        confidence: float | None = None,
    ) -> GraphNode | None:
        """把新事件的内容/源证合并进已有节点（Agent 图整合的统一入口）。

        - source_refs 并集去重（追加新事件 SourceRef，hash=新事件 content_hash）
        - 同步反向索引 event_to_nodes（缺失会导致删除该事件时节点源证不失效）
        - content 追加（整段去重）；confidence 取 max；evidence_quote 保留
        - 标记脏位（调用方随后 flush/save 落盘）
        """
        node = self.get_node(target_id)
        if node is None:
            return None
        if event_id not in {sr.event_id for sr in node.source_refs}:
            node.source_refs.append(SourceRef(event_id=event_id, valid=True, hash=content_hash))
            self.event_to_nodes.setdefault(event_id, []).append(target_id)
        if content and content not in node.content:
            node.content = (node.content + "\n" + content).strip()
        if confidence is not None and confidence > node.confidence:
            node.confidence = confidence
        self.graph.nodes[target_id]["data"] = node
        self._mark_dirty()
        return node

    def merge_nodes(self, target_id: str, source_ids: list[str]) -> list[str]:
        """合并多个已有节点进 target（图内整合，维护任务用）。

        - target 吸收 source 的 source_refs（并集去重）+ content（整段去重）
          + confidence（取 max）；同步反向索引
        - 边迁移：source 的出入边重定向到 target；与 target 直接相连的边删除；
          重定向目标已存在边则跳过（保留原边）
        - 删除 source 节点并清理反向索引
        - 标记脏位；FTS 更新由调用方（async）执行
        返回实际被合并删除的 source id 列表（跳过不存在的/自合并）。
        """
        target = self.get_node(target_id)
        if target is None:
            return []
        removed: list[str] = []
        for src in source_ids:
            if src == target_id:
                continue
            src_node = self.get_node(src)
            if src_node is None:
                continue
            # ── 吸收 source_refs（并集）+ 反向索引 ──
            known = {sr.event_id for sr in target.source_refs}
            for sr in src_node.source_refs:
                if sr.event_id not in known:
                    target.source_refs.append(sr)
                    known.add(sr.event_id)
                    self.event_to_nodes.setdefault(sr.event_id, []).append(target_id)
            # ── content 合并（整段去重）──
            if src_node.content and src_node.content not in target.content:
                target.content = (target.content + "\n" + src_node.content).strip()
            # ── confidence 取 max ──
            if src_node.confidence > target.confidence:
                target.confidence = src_node.confidence
            # ── 边迁移（先收集再改，避免迭代中修改图）──
            in_edges = list(self.graph.in_edges(src))
            out_edges = list(self.graph.out_edges(src))
            for u, v in in_edges:
                if u == target_id or v == target_id:
                    continue  # 与 target 直接相连：合并后成自环/重复，删除
                if self.graph.has_edge(u, target_id):
                    continue  # 重定向目标已存在：保留原边
                self.graph.add_edge(u, target_id, data=self.graph.edges[(u, v)]["data"])
                self.graph.remove_edge(u, v)
            for u, v in out_edges:
                if u == target_id or v == target_id:
                    continue
                if self.graph.has_edge(target_id, v):
                    continue
                self.graph.add_edge(target_id, v, data=self.graph.edges[(u, v)]["data"])
                self.graph.remove_edge(u, v)
            # ── 删除 source（GraphStore.remove_node 同步清理反向索引）──
            self.remove_node(src)
            removed.append(src)
        self.graph.nodes[target_id]["data"] = target
        self._mark_dirty()
        return removed

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

    async def reconcile(self, event_store) -> int:
        """启动自愈：把图内 source_refs 与事件表现状对齐。

        对每条 valid 源证：
        - 引用的事件已不存在 → 置 invalid（悬空引用）
        - hash 快照与事件现 content_hash 不一致 → 置 invalid（来源被修订/漂移）
        返回被置为 invalid 的源证数量，便于日志观测。
        """
        event_ids = {
            sr.event_id
            for _, ndata in self.graph.nodes(data="data")
            if ndata is not None
            for sr in ndata.source_refs
        }
        events = await event_store.get_many(list(event_ids))
        changed = 0
        for nid, ndata in self.graph.nodes(data="data"):
            if ndata is None:
                continue
            for sr in ndata.source_refs:
                if not sr.valid:
                    continue
                ev = events.get(sr.event_id)
                if ev is None:
                    sr.valid = False
                    changed += 1
                elif sr.hash and ev.get("content_hash") and sr.hash != ev["content_hash"]:
                    sr.valid = False
                    changed += 1
        if changed:
            self._mark_dirty()
        return changed

    def total_nodes(self) -> int:
        return self.graph.number_of_nodes()

    def node_counts_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {"system": 0, "interaction": 0, "data": 0}
        for _, ndata in self.graph.nodes(data="data"):
            if ndata is not None:
                t = ndata.node_type.value
                counts[t] = counts.get(t, 0) + 1
        return counts

    def list_nodes(self, node_type: str | None = None) -> list[dict]:
        """返回节点列表，可选按 node_type 筛选。"""
        result: list[dict] = []
        for _, ndata in self.graph.nodes(data="data"):
            if ndata is None:
                continue
            if node_type and ndata.node_type.value != node_type:
                continue
            result.append(ndata.model_dump())
        return result

    def list_edges(self, node_id: str | None = None) -> list[dict]:
        """返回边列表，可选按节点 ID 筛选（含出边和入边）。"""
        result: list[dict] = []
        for s, t, edata in self.graph.edges(data="data"):
            if edata is None:
                continue
            if node_id and node_id not in (s, t):
                continue
            result.append({
                "source": s,
                "target": t,
                "relation": edata.relation,
                "evidence_event_id": edata.evidence_event_id,
            })
        return result

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
        try:
            cursor = await self.db.conn.execute(
                "SELECT node_id,title,content,rank FROM node_fts"
                " WHERE node_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            )
            rows = await cursor.fetchall()
        except Exception:
            rows = []  # MATCH 语法错误（如含 - : " 等）→ 降级 LIKE
        if rows:
            return [dict(r) for r in rows]
        # FTS5 不命中（如中文），遍历内存图做多关键词 LIKE 匹配，按命中词数/位置计分排序
        from core.text_utils import like_rank_multi, tokenize_query

        tokens = tokenize_query(query)
        if not tokens:
            tokens = [query]
        results: list[dict] = []
        for nid, ndata in self.graph.nodes(data=True):
            data = ndata.get("data")
            if data is None:
                continue
            title = (data.title or "").lower()
            content = (data.content or "").lower()
            if any(t in title or t in content for t in tokens):
                results.append({
                    "node_id": nid,
                    "title": data.title,
                    "content": data.content,
                    "rank": like_rank_multi(tokens, data.title, data.content),
                })
        results.sort(key=lambda x: x["rank"])
        return results[:limit]

    @property
    def dirty(self) -> bool:
        return self._dirty
