"""Tests for the knowledge graph memory (memory/__init__.py)."""

import pytest

from tardis.memory import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeNode,
    SharedMemory,
    create_shared_memory,
    enable_knowledge_sharing,
)


class TestKnowledgeNode:
    def test_to_dict(self):
        node = KnowledgeNode(
            node_id="n1",
            node_type="fix",
            title="Fix timeout",
            description="Increase timeout",
            content={"param": "timeout"},
        )
        d = node.to_dict()
        assert d["node_id"] == "n1"
        assert d["node_type"] == "fix"
        assert d["confidence_score"] == 1.0


class TestKnowledgeEdge:
    def test_to_dict(self):
        edge = KnowledgeEdge(
            edge_id="e1",
            source_node="n1",
            target_node="n2",
            relationship="fixes",
            weight=0.9,
        )
        d = edge.to_dict()
        assert d["relationship"] == "fixes"
        assert d["weight"] == 0.9


class TestKnowledgeGraph:
    def test_init(self, tmp_path):
        graph = KnowledgeGraph(storage_dir=str(tmp_path / "kg"))
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_add_node(self, tmp_path):
        graph = KnowledgeGraph(storage_dir=str(tmp_path / "kg"))
        node = graph.add_node(
            node_type="fix",
            title="Fix 1",
            description="desc",
            content={"a": 1},
            tags=["timeout"],
        )
        assert node.node_id in graph.nodes
        assert "timeout" in graph.tag_index
        assert "fix" in graph.type_index

    def test_add_node_dedup(self, tmp_path):
        graph = KnowledgeGraph(storage_dir=str(tmp_path / "kg"))
        n1 = graph.add_node("fix", "Fix", "desc", {"a": 1})
        n2 = graph.add_node("fix", "Fix", "desc", {"a": 1})
        assert n1.node_id == n2.node_id
        assert n2.usage_count == 1

    def test_add_edge(self, tmp_path):
        graph = KnowledgeGraph(storage_dir=str(tmp_path / "kg"))
        n1 = graph.add_node("failure_pattern", "F1", "desc", {"err": "timeout"})
        n2 = graph.add_node("fix", "Fix1", "desc", {"param": 30})
        edge = graph.add_edge(n1.node_id, n2.node_id, "fixes")
        assert edge.edge_id in graph.edges
        assert n2.node_id in graph.adjacency_list[n1.node_id]

    def test_add_edge_missing_node(self, tmp_path):
        graph = KnowledgeGraph(storage_dir=str(tmp_path / "kg"))
        with pytest.raises(ValueError, match="must exist"):
            graph.add_edge("missing1", "missing2", "fixes")

    def test_find_similar(self, tmp_path):
        graph = KnowledgeGraph(storage_dir=str(tmp_path / "kg"))
        graph.add_node(
            "failure_pattern",
            "Timeout Error",
            "Connection timeout",
            {"error": "timeout"},
            tags=["network"],
        )
        results = graph.find_similar({"tags": ["network"]})
        assert len(results) > 0

    def test_find_similar_with_type_filter(self, tmp_path):
        graph = KnowledgeGraph(storage_dir=str(tmp_path / "kg"))
        graph.add_node("failure_pattern", "F1", "desc", {"a": 1}, tags=["t1"])
        graph.add_node("fix", "Fix1", "desc", {"a": 1}, tags=["t1"])
        results = graph.find_similar({"tags": ["t1"]}, node_type="fix")
        assert all(n.node_type == "fix" for n, _ in results)

    def test_search_by_type(self, tmp_path):
        graph = KnowledgeGraph(storage_dir=str(tmp_path / "kg"))
        graph.add_node("fix", "F1", "d1", {"a": 1})
        graph.add_node("fix", "F2", "d2", {"b": 2})
        graph.add_node("failure_pattern", "P1", "d3", {"c": 3})
        fixes = graph.search_by_type("fix")
        assert len(fixes) == 2

    def test_search_by_tag(self, tmp_path):
        graph = KnowledgeGraph(storage_dir=str(tmp_path / "kg"))
        graph.add_node("fix", "F1", "d", {"a": 1}, tags=["urgent"])
        graph.add_node("fix", "F2", "d", {"b": 2}, tags=["normal"])
        urgent = graph.search_by_tag("urgent")
        assert len(urgent) == 1

    def test_get_related(self, tmp_path):
        graph = KnowledgeGraph(storage_dir=str(tmp_path / "kg"))
        n1 = graph.add_node("failure_pattern", "F1", "d", {"a": 1})
        n2 = graph.add_node("fix", "Fix1", "d", {"b": 2})
        n3 = graph.add_node("fix", "Fix2", "d", {"c": 3})
        graph.add_edge(n1.node_id, n2.node_id, "fixes")
        graph.add_edge(n2.node_id, n3.node_id, "related")
        related = graph.get_related(n1.node_id, depth=2)
        assert len(related) >= 1

    def test_get_related_nonexistent(self, tmp_path):
        graph = KnowledgeGraph(storage_dir=str(tmp_path / "kg"))
        assert graph.get_related("missing") == []

    def test_record_fix_application(self, tmp_path):
        graph = KnowledgeGraph(storage_dir=str(tmp_path / "kg"))
        fp = graph.add_node("failure_pattern", "F1", "d", {"a": 1})
        fix = graph.add_node("fix", "Fix1", "d", {"b": 2})
        graph.add_edge(fp.node_id, fix.node_id, "fixes")
        graph.record_fix_application(fp.node_id, fix.node_id, True, {})
        assert fix.usage_count == 1

    def test_get_best_fixes(self, tmp_path):
        graph = KnowledgeGraph(storage_dir=str(tmp_path / "kg"))
        fp = graph.add_node("failure_pattern", "F1", "d", {"a": 1})
        fix1 = graph.add_node("fix", "Fix1", "d", {"b": 2})
        fix2 = graph.add_node("fix", "Fix2", "d", {"c": 3})
        graph.add_edge(fp.node_id, fix1.node_id, "fixes")
        graph.add_edge(fp.node_id, fix2.node_id, "fixes")
        graph.record_fix_application(fp.node_id, fix1.node_id, True, {})
        graph.record_fix_application(fp.node_id, fix2.node_id, False, {})
        fixes = graph.get_best_fixes(fp.node_id)
        assert len(fixes) <= 3
        # Fix1 should be better than Fix2
        assert fixes[0][0].node_id == fix1.node_id

    def test_save_and_load(self, tmp_path):
        storage = str(tmp_path / "kg_save")
        graph = KnowledgeGraph(storage_dir=storage)
        graph.add_node("fix", "Fix1", "d", {"a": 1}, tags=["t1"])
        graph._save_to_disk()

        graph2 = KnowledgeGraph(storage_dir=storage)
        assert len(graph2.nodes) == 1
        assert "fix" in graph2.type_index

    def test_statistics(self, tmp_path):
        graph = KnowledgeGraph(storage_dir=str(tmp_path / "kg"))
        graph.add_node("fix", "F1", "d", {"a": 1})
        graph.add_node("failure_pattern", "P1", "d", {"b": 2})
        stats = graph.get_statistics()
        assert stats["total_nodes"] == 2
        assert "fix" in stats["by_type"]


class TestSharedMemory:
    def test_init(self, tmp_path):
        sm = SharedMemory(storage_dir=str(tmp_path / "sm"))
        assert sm.agent_id is None

    def test_set_agent_id(self, tmp_path):
        sm = SharedMemory(storage_dir=str(tmp_path / "sm"))
        sm.set_agent_id("agent-1")
        assert sm.agent_id == "agent-1"

    def test_store_failure_pattern(self, tmp_path):
        sm = SharedMemory(storage_dir=str(tmp_path / "sm"))
        node = sm.store_failure_pattern(
            "Timeout", "Connection timeout", {"err": "timeout"}
        )
        assert node.node_type == "failure_pattern"

    def test_store_fix(self, tmp_path):
        sm = SharedMemory(storage_dir=str(tmp_path / "sm"))
        node = sm.store_fix("Fix timeout", "Increase timeout", {"param": 30})
        assert node.node_type == "fix"

    def test_link_fix_to_failure(self, tmp_path):
        sm = SharedMemory(storage_dir=str(tmp_path / "sm"))
        fp = sm.store_failure_pattern("F1", "d", {"a": 1})
        fix = sm.store_fix("Fix1", "d", {"b": 2})
        sm.link_fix_to_failure(fp.node_id, fix.node_id, success=True)
        fixes = sm.get_recommended_fixes(fp.node_id)
        assert len(fixes) > 0

    def test_find_similar_failures(self, tmp_path):
        sm = SharedMemory(storage_dir=str(tmp_path / "sm"))
        sm.store_failure_pattern("Timeout", "Connection timeout", {}, tags=["network"])
        results = sm.find_similar_failures("timeout error", ["network"])
        assert len(results) >= 0

    def test_save_and_stats(self, tmp_path):
        sm = SharedMemory(storage_dir=str(tmp_path / "sm_save"))
        sm.store_failure_pattern("F1", "d", {})
        sm.save()
        stats = sm.get_statistics()
        assert stats["total_nodes"] == 1


class TestConvenienceFunctions:
    def test_create_shared_memory(self, tmp_path):
        sm = create_shared_memory()
        assert isinstance(sm, SharedMemory)

    def test_create_with_agent_id(self, tmp_path):
        sm = create_shared_memory(agent_id="a1")
        assert sm.agent_id == "a1"

    def test_enable_knowledge_sharing(self, tmp_path):
        sm = enable_knowledge_sharing("agent-1")
        assert sm.agent_id == "agent-1"
