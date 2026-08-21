"""事件溯源研究内核 — 实验图谱与谱系网络 (Experiment Graph & Lineage Network).

记录实验节点、父代变异关系、验证关卡与决策谱系，实现任意候选的 100% 溯源。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass(frozen=True)
class GraphNode:
    """实验图谱节点 (不可变实体)."""

    node_id: str
    node_type: str                  # candidate / validation / decision / batch / hypothesis
    payload_ref: Optional[str]      # 关联的 Artifact Hash
    created_at_event_id: str


@dataclass(frozen=True)
class GraphEdge:
    """实验图谱边 (父子变异、验证隶属、决策关联)."""

    source_node_id: str
    target_node_id: str
    relation_type: str             # mutated_from / validated_by / decided_by / spawned_by


class ExperimentGraph:
    """实验图谱管理器 (Experiment Graph)."""

    def __init__(self, graph_id: str, policy_id: str, random_seed: int = 42, code_sha: str = "HEAD"):
        self.graph_id = graph_id
        self.policy_id = policy_id
        self.random_seed = random_seed
        self.code_sha = code_sha
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: List[GraphEdge] = []

    def add_node(self, node_id: str, node_type: str, payload_ref: Optional[str], event_id: str) -> GraphNode:
        """添加图节点."""
        node = GraphNode(
            node_id=node_id,
            node_type=node_type,
            payload_ref=payload_ref,
            created_at_event_id=event_id,
        )
        self.nodes[node_id] = node
        return node

    def add_edge(self, source_id: str, target_id: str, relation_type: str) -> GraphEdge:
        """添加图关系边."""
        edge = GraphEdge(
            source_node_id=source_id,
            target_node_id=target_id,
            relation_type=relation_type,
        )
        self.edges.append(edge)
        return edge

    def get_ancestors(self, node_id: str) -> List[str]:
        """递归获取指定节点的所有祖先节点 ID (完整父代溯源)."""
        ancestors: List[str] = []
        visited: Set[str] = set()

        def _dfs(curr_id: str):
            for edge in self.edges:
                if edge.target_node_id == curr_id and edge.source_node_id not in visited:
                    visited.add(edge.source_node_id)
                    ancestors.append(edge.source_node_id)
                    _dfs(edge.source_node_id)

        _dfs(node_id)
        return ancestors

    def get_descendants(self, node_id: str) -> List[str]:
        """获取指定节点衍生的所有子孙节点 ID."""
        descendants: List[str] = []
        visited: Set[str] = set()

        def _dfs(curr_id: str):
            for edge in self.edges:
                if edge.source_node_id == curr_id and edge.target_node_id not in visited:
                    visited.add(edge.target_node_id)
                    descendants.append(edge.target_node_id)
                    _dfs(edge.target_node_id)

        _dfs(node_id)
        return descendants
