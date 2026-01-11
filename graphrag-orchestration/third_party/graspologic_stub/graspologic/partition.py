"""Minimal stub of graspologic.partition.hierarchical_leiden.
This provides a tiny, dependency-free placeholder so builds can succeed in environments
where the full `graspologic` package should be installed optionally (via extras).

Behavior: returns an empty list (no clusters). Consumer code falls back to single-community behavior.
"""
from typing import Any, List


class HierarchicalCluster:
    def __init__(self, node: int, cluster: int, level: int = 0, is_final_cluster: bool = True):
        self.node = node
        self.cluster = cluster
        self.level = level
        self.is_final_cluster = is_final_cluster


def hierarchical_leiden(graph_or_matrix: Any, resolution: float = 1.0, max_cluster_size: int = 10) -> List[HierarchicalCluster]:
    """Return no clusters (empty list) so application fallbacks are used.

    This intentionally does NOT implement the real Leiden algorithm.
    Install the real `graspologic` package if you need accurate communities:
      pip install -r requirements.community.txt
    """
    return []
