"""信息图层：NetworkX 内存图 + JSON 原子持久化 + 反向索引"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import networkx as nx

from core.atomic import atomic_write_text, backup_candidates, backup_file
from core.config import settings
from core.database import Database
from core.graph_ops import (
    count_ops,
    diff_ops,
    load_all_ops,
    record_ops,
    replay,
    snapshot_graph,
)
from core.models import GraphEdge, GraphNode, SourceRef

logger = logging.getLogger(__name__)

# 图层文件体量上限（v1.28 T0-1）：超限视为损坏走留档/拒绝写入，防异常膨胀拖垮内存
MAX_GRAPH_BYTES = 64 * 1024 * 1024
# 图层文件格式版本（写进 graph.json）：格式演进时识别并拒绝读取更高版本
GRAPH_FORMAT_VERSION = 1
# 节点合并护栏（v1.28 T0-2）：content 追加与源证并集上限，防反复合并致节点无限膨胀
_MAX_NODE_CONTENT = 20_000
_MAX_SOURCE_REFS = 500


def _cap_source_refs(node: GraphNode, node_id: str) -> None:
    """源证上限护栏：超出则截断最旧并**留痕**（静默丢溯源信息不可接受）。"""
    if len(node.source_refs) > _MAX_SOURCE_REFS:
        dropped = len(node.source_refs) - _MAX_SOURCE_REFS
        logger.warning(
            "节点 %s 源证 %d 条超过上限 %d，截断最旧 %d 条（溯源信息丢失）",
            node_id, len(node.source_refs), _MAX_SOURCE_REFS, dropped,
        )
        node.source_refs = node.source_refs[-_MAX_SOURCE_REFS:]


def _cap_content(node: GraphNode, node_id: str) -> None:
    """内容上限护栏：超出则截断并**留痕**（原文仍在事件层可追溯）。"""
    if len(node.content) > _MAX_NODE_CONTENT:
        logger.warning(
            "节点 %s 内容 %d 字超过上限 %d，已截断（原文仍在事件层）",
            node_id, len(node.content), _MAX_NODE_CONTENT,
        )
        node.content = node.content[:_MAX_NODE_CONTENT]


def _quarantine_corrupt(path: Path, label: str = "corrupt") -> None:
    """原件留档改名（T0-1）：绝不用空图覆盖可恢复数据。

    主文件与备份均不可读（或超体量上限/格式版本更高）时，把原件改名留存，
    再尝试从 `graph_ops` 重放恢复（P4）；仍不可恢复才以空图启动。
    原件必须给用户留观察与手工抢救的余地。
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.{label}-{stamp}")
    try:
        os.replace(path, target)
        logger.warning("graph.json 不可用（损坏/超限），原件已留档 %s，以空图启动", target)
    except OSError as exc:
        logger.error("损坏原件留档失败（不影响启动，请手工处理）: %s", exc)


class GraphStore:
    def __init__(self, db: Database, json_path: str | None = None) -> None:
        self.db = db
        self.json_path = json_path or settings.graph_json_path
        self.graph = nx.DiGraph()
        self.event_to_nodes: dict[str, list[str]] = {}
        self._dirty = False
        # 图层操作日志（graph_ops）：上次落盘快照 + 本批变更的「因何」标签
        self._saved_nodes: dict[str, dict] = {}
        self._saved_edges: dict[tuple[str, str], dict] = {}
        self._op_reason = ""
        # 上次 load 从 graph.json 里跳过的悬空边条数（v1.42）：端点不在 nodes 里的边，
        # 加载时跳过并落盘清除；verify 会把它作为「文件级残留」报出来。
        self.dropped_dangling_edges = 0

    async def load(self):
        """从 graph.json 加载图谱，并重建 node_fts。

        恢复链（依次尝试）：graph.json → `.bak` 备份 → **graph_ops 重放**（P4）→ 空图。
        重放让「图层是派生 read-model」在故障路径上真正成立：文件丢了也能从操作日志复原。
        `format_version` 高于本程序支持的版本时留档拒读，避免用旧格式覆盖新数据。

        node_fts 以内存图为唯一真源全量重建：解决手动编辑 graph.json、
        清空图谱、备份恢复后索引与图层不一致的问题（新节点检索不到、
        已删节点检索残留）。
        """
        path = Path(self.json_path)
        data: dict | None = None
        # 图层文件是否不可用（不存在/损坏）——只有不可用才走重放恢复，
        # 避免把「用户手动清空 graph.json」也当成故障而复活旧节点
        file_unusable = not path.exists()
        if path.exists() and path.stat().st_size > MAX_GRAPH_BYTES:
            logger.error("graph.json 超过 %d 字节读取上限", MAX_GRAPH_BYTES)
            _quarantine_corrupt(path)
            file_unusable = True
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("graph.json 解析失败，尝试从备份恢复: %s", exc)
                file_unusable = True
                restored = False
                for cand in backup_candidates(path):
                    try:
                        data = json.loads(cand.read_text(encoding="utf-8"))
                        logger.warning("已从备份 %s 恢复图谱", cand.name)
                        file_unusable = False
                        restored = True
                        break
                    except (json.JSONDecodeError, OSError) as bexc:
                        logger.error("备份 %s 不可读: %s", cand.name, bexc)
                if not restored:
                    logger.error("graph.json 无可用备份（请检查存储文件）")
                    _quarantine_corrupt(path)
                    data = None
        if data is not None:
            version = int(data.get("format_version") or 0)
            if version > GRAPH_FORMAT_VERSION:
                logger.error(
                    "graph.json 格式版本 %s 高于本程序支持的 %s，留档拒读"
                    "（避免用旧格式覆盖新数据）",
                    version, GRAPH_FORMAT_VERSION,
                )
                _quarantine_corrupt(path, label=f"newer-v{version}")
                data = None
                file_unusable = False  # 不用旧日志重放，防止覆盖更新格式的数据
        if data is not None:
            nodes_data = data.get("nodes", {})
            edges_data = data.get("edges", [])
            try:
                for nid, ndata in nodes_data.items():
                    node = GraphNode(**ndata)
                    self.graph.add_node(nid, data=node)
                dropped = 0
                for edata in edges_data:
                    edge = GraphEdge(**edata)
                    # v1.42：端点不在 nodes 里的边一律跳过。以前直接交给 NetworkX，
                    # 而 `add_edge` 遇到未知端点会**自动造出无 data 的空壳节点**——
                    # 于是节点数（/health）、node_fts 一致性、verify 口径全被污染，
                    # 且每次加载都从文件里把空壳重新造出来（自续循环）。
                    if edge.source not in self.graph or edge.target not in self.graph:
                        dropped += 1
                        continue
                    self.graph.add_edge(edge.source, edge.target, data=edge)
            except Exception as exc:
                logger.error("图谱节点/边构建失败，尝试从操作日志重放: %s", exc)
                _quarantine_corrupt(path)
                self.graph.clear()
                file_unusable = True
            else:
                self._rebuild_reverse_index()
                # 留存最近一次可用快照，供下次加载损坏时恢复
                backup_file(path)
                if dropped:
                    self.dropped_dangling_edges = dropped
                    logger.warning(
                        "graph.json 有 %d 条边的端点不在 nodes 中（悬空边），已跳过；"
                        "已标记脏位，本次落盘即从文件中清除（原件进 .bak）",
                        dropped,
                    )
                    self._mark_dirty()
        if file_unusable and self.graph.number_of_nodes() == 0:
            restored = await self.replay_recover()
            if restored:
                logger.warning(
                    "graph.json 不可用，已从 graph_ops 重放恢复 %d 个节点（待落盘）",
                    restored,
                )
        # 基线快照：本进程启动时的图层状态，供 save() 计算差分 ops
        self._saved_nodes, self._saved_edges = snapshot_graph(self.graph)
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
        payload = {
            "format_version": GRAPH_FORMAT_VERSION,
            "nodes": nodes_data,
            "edges": edges_data,
        }
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        if len(encoded.encode("utf-8")) > MAX_GRAPH_BYTES:
            raise RuntimeError(
                f"graph.json 序列化超过 {MAX_GRAPH_BYTES} 字节上限，拒绝写入"
                "（请先压缩/清理图层，或调低节点规模）"
            )
        # 备份必须在覆盖前做（否则备份到的是刚写的新内容 = 没有上一代）
        had_backup = backup_file(path)
        # 原子写（pid 临时名 + fsync + Windows 共享冲突重试），见 core/atomic.py
        atomic_write_text(path, encoded)
        self._dirty = False
        if not had_backup:
            backup_file(path)  # 首次写入没有上一代：以当前内容建立第一代备份
        # 落盘成功后把「相对上次落盘的差分」追加到 graph_ops（审计 + 重放依据）
        await self._record_diff()

    def _mark_dirty(self) -> None:
        """标记脏位：任何内存图修改后必须调用，flush/save 据此落盘。"""
        self._dirty = True

    def set_op_reason(self, reason: str) -> None:
        """给下一批落盘变更打「因何」标签（审计用；save 后自动清空）。"""
        self._op_reason = reason[:200]

    async def _record_diff(self) -> None:
        """把「上次落盘 → 当前」的差分追加到 graph_ops。

        ops 写入失败只记 ERROR 不阻断：JSON 是主产物，ops 是审计/恢复依据，
        不能因为日志表写失败就让调用方收到「写失败」的错觉。失败时不更新基线快照，
        下一轮 save 会重试同一批差分（自愈）。
        """
        nodes, edges = snapshot_graph(self.graph)
        ops = diff_ops(self._saved_nodes, self._saved_edges, nodes, edges)
        if not ops:
            self._op_reason = ""
            return
        try:
            await record_ops(self.db.conn, ops, reason=self._op_reason)
        except Exception:
            logger.exception("graph_ops 写入失败（图层已落盘，重放依据缺 %d 条）", len(ops))
            return
        self._saved_nodes, self._saved_edges = nodes, edges
        self._op_reason = ""

    async def replay_recover(self) -> int:
        """从 graph_ops 重放图层，返回恢复的节点数（无日志返回 0）。

        用于 graph.json 丢失/损坏且无可用备份时的恢复；结果标记脏位，
        由调用方（启动路径的 reconcile+flush 或显式 refresh）落盘成新的 graph.json。
        """
        try:
            ops = await load_all_ops(self.db.conn)
        except Exception as exc:
            logger.warning("graph_ops 读取失败，跳过重放恢复: %s", exc)
            return 0
        if not ops:
            return 0
        nodes, edges = replay(ops)
        self.graph.clear()
        for nid, ndata in nodes.items():
            try:
                self.graph.add_node(nid, data=GraphNode(**ndata))
            except Exception as exc:
                logger.warning("重放节点 %s 失败（跳过）: %s", nid, exc)
        skipped = 0
        for (src, dst), edata in edges.items():
            if src not in self.graph or dst not in self.graph:
                skipped += 1
                continue  # 端点缺失的边不重建（NetworkX 会造出无 data 的节点）
            try:
                self.graph.add_edge(src, dst, data=GraphEdge(**edata))
            except Exception as exc:
                logger.warning("重放边 %s→%s 失败（跳过）: %s", src, dst, exc)
        if skipped:
            logger.warning(
                "重放恢复：%d 条边的端点不在重放结果里，未重建（不造空壳节点）", skipped
            )
        self._rebuild_reverse_index()
        self._mark_dirty()
        return self.graph.number_of_nodes()

    async def ops_count(self) -> int:
        """graph_ops 累计条数（health / verify 用）。"""
        try:
            return await count_ops(self.db.conn)
        except Exception:
            return 0

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

    def add_edge(self, edge: GraphEdge) -> bool:
        """加边（v1.42 起**拒绝未知端点**），返回是否真的加上。

        以前直接交给 NetworkX：`add_edge` 遇到未知端点会**自动造出一个无 data 的
        空壳节点**，于是 `/health` 的节点数、`node_fts` 一致性、`verify` 的口径
        全被污染（实测活动库 51 个真节点被算成 66 个），且每次 load 都从文件里
        把空壳重新造出来。端点缺失一律拒绝并留痕，绝不静默造节点。

        生产调用方（`POST /edges`、AI 工具、回收站恢复）都已先校验端点存在，
        故本守卫只拦「漏校验」的路径；调用方若忽略返回值，日志里有 WARNING。
        """
        if self.get_node(edge.source) is None or self.get_node(edge.target) is None:
            logger.warning(
                "边被拒绝（端点不存在）：%s→%s relation=%s（不造空壳节点）",
                edge.source, edge.target, edge.relation,
            )
            return False
        self.graph.add_edge(edge.source, edge.target, data=edge)
        self._mark_dirty()
        return True

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
        title: str | None = None,
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
        if title is not None:
            node.title = title
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
            _cap_source_refs(node, target_id)
        if content and content not in node.content:
            node.content = (node.content + "\n" + content).strip()
            _cap_content(node, target_id)
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
            # ── 吸收 source_refs（并集 + 上限护栏，保留最新）+ 反向索引 ──
            known = {sr.event_id for sr in target.source_refs}
            for sr in src_node.source_refs:
                if sr.event_id not in known:
                    target.source_refs.append(sr)
                    known.add(sr.event_id)
                    self.event_to_nodes.setdefault(sr.event_id, []).append(target_id)
            # ── content 合并（整段去重 + 上限护栏）──
            if src_node.content and src_node.content not in target.content:
                target.content = (target.content + "\n" + src_node.content).strip()
                _cap_content(target, target_id)
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
        _cap_source_refs(target, target_id)
        self.graph.nodes[target_id]["data"] = target
        self._mark_dirty()
        return removed

    def add_source_ref(self, node_id: str, event_id: str, content_hash: str = "") -> bool:
        """给节点追加源证（幂等：已存在同事件源证时直接成功）。

        同步反向索引 event_to_nodes；标记脏位（调用方负责 flush 落盘）。
        节点不存在返回 False。
        """
        node = self.get_node(node_id)
        if node is None:
            return False
        if any(sr.event_id == event_id for sr in node.source_refs):
            return True
        node.source_refs.append(
            SourceRef(event_id=event_id, valid=True, hash=content_hash)
        )
        self.event_to_nodes.setdefault(event_id, []).append(node_id)
        self.graph.nodes[node_id]["data"] = node
        self._mark_dirty()
        return True

    def remove_source_ref(self, node_id: str, event_id: str) -> bool:
        """移除节点的一条源证并同步反向索引。

        「最少一条有效源证」守卫由调用方执行（需结合全部节点状态判断）；
        节点或该源证不存在返回 False。标记脏位（调用方负责 flush）。
        """
        node = self.get_node(node_id)
        if node is None:
            return False
        before = len(node.source_refs)
        node.source_refs = [sr for sr in node.source_refs if sr.event_id != event_id]
        if len(node.source_refs) == before:
            return False
        refs = self.event_to_nodes.get(event_id, [])
        if node_id in refs:
            refs.remove(node_id)
            if not refs:
                self.event_to_nodes.pop(event_id, None)
        self.graph.nodes[node_id]["data"] = node
        self._mark_dirty()
        return True

    def get_edge(self, source: str, target: str) -> GraphEdge | None:
        edata = self.graph.edges.get((source, target), {}).get("data")
        return edata

    def ego_graph(self, seeds: list[str], hops: int = 2) -> dict[str, float]:
        """种子节点的 ego-graph 扩散得分（检索用，双向）。

        图为有向（边承载语义方向），但检索扩散取无向邻域：
        相关性召回不区分边方向（A→B 时命中 B 也能跳回 A），
        方向语义保留在边数据与前端展示中，不因扩散丢失。
        """
        result: dict[str, float] = {}
        undirected = self.graph.to_undirected(as_view=True)
        for seed in seeds:
            if seed not in self.graph:
                continue
            ego = nx.ego_graph(undirected, seed, radius=hops, center=False)
            for n in ego.nodes():
                hop_dist = nx.shortest_path_length(undirected, seed, n)
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

    def total_edges(self) -> int:
        return self.graph.number_of_edges()

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

    def list_edges(
        self,
        node_id: str | None = None,
        source: str | None = None,
        target: str | None = None,
        relation: str | None = None,
    ) -> list[dict]:
        """返回边列表，可选筛选（v1.37 增 source/target/relation）。

        `node_id` 命中**两侧**（出边 + 入边，与 `GET /nodes/{node_id}` 的 edges 同口径）。
        返回顺序 = NetworkX 边迭代顺序（插入序），分页稳定性由调用方排序保证。
        """
        result: list[dict] = []
        for s, t, edata in self.graph.edges(data="data"):
            if edata is None:
                continue
            if node_id and node_id not in (s, t):
                continue
            if source and s != source:
                continue
            if target and t != target:
                continue
            if relation and edata.relation != relation:
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
