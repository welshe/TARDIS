"""
Cross-Agent Knowledge Graph Memory

A shared persistent memory layer where debugging agents store learned fixes 
and patterns, allowing insights from one session to instantly protect all 
other deployments. Creates a network effect that makes the system smarter with use.
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class KnowledgeNode:
    """A node in the knowledge graph representing a concept, pattern, or fix."""
    node_id: str
    node_type: str  # failure_pattern, fix, insight, tool_usage, best_practice
    title: str
    description: str
    content: Dict[str, Any]
    confidence_score: float = 1.0
    usage_count: int = 0
    last_used: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    created_by: str = "system"
    tags: List[str] = field(default_factory=list)
    related_nodes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "title": self.title,
            "description": self.description,
            "content": self.content,
            "confidence_score": self.confidence_score,
            "usage_count": self.usage_count,
            "last_used": self.last_used,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "tags": self.tags,
            "related_nodes": self.related_nodes,
        }


@dataclass
class KnowledgeEdge:
    """An edge connecting two knowledge nodes."""
    edge_id: str
    source_node: str
    target_node: str
    relationship: str  # causes, fixes, similar_to, precedes, depends_on
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_node": self.source_node,
            "target_node": self.target_node,
            "relationship": self.relationship,
            "weight": self.weight,
            "metadata": self.metadata,
        }


class KnowledgeGraph:
    """Graph-based memory structure for cross-agent knowledge sharing."""
    
    def __init__(self, storage_dir: str = ".tardis/memory"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.nodes: Dict[str, KnowledgeNode] = {}
        self.edges: Dict[str, KnowledgeEdge] = {}
        self.adjacency_list: Dict[str, Set[str]] = {}  # node_id -> connected node_ids
        
        # Indexes for fast lookup
        self.type_index: Dict[str, Set[str]] = {}  # node_type -> node_ids
        self.tag_index: Dict[str, Set[str]] = {}   # tag -> node_ids
        
        self._load_from_disk()
    
    def _generate_node_id(self, content: Dict[str, Any]) -> str:
        """Generate deterministic node ID based on content."""
        content_str = json.dumps(content, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()[:16]
    
    def _generate_edge_id(self, source: str, target: str, relationship: str) -> str:
        """Generate deterministic edge ID."""
        key = f"{source}_{target}_{relationship}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]
    
    def add_node(
        self,
        node_type: str,
        title: str,
        description: str,
        content: Dict[str, Any],
        tags: Optional[List[str]] = None,
        created_by: str = "system",
    ) -> KnowledgeNode:
        """Add a new knowledge node."""
        node_id = self._generate_node_id(content)
        
        # Check if node already exists
        if node_id in self.nodes:
            existing = self.nodes[node_id]
            existing.usage_count += 1
            existing.last_used = time.time()
            return existing
        
        node = KnowledgeNode(
            node_id=node_id,
            node_type=node_type,
            title=title,
            description=description,
            content=content,
            created_by=created_by,
            tags=tags or [],
        )
        
        self.nodes[node_id] = node
        
        # Update indexes
        if node_type not in self.type_index:
            self.type_index[node_type] = set()
        self.type_index[node_type].add(node_id)
        
        for tag in node.tags:
            if tag not in self.tag_index:
                self.tag_index[tag] = set()
            self.tag_index[tag].add(node_id)
        
        # Initialize adjacency list entry
        if node_id not in self.adjacency_list:
            self.adjacency_list[node_id] = set()
        
        return node
    
    def add_edge(
        self,
        source_node_id: str,
        target_node_id: str,
        relationship: str,
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeEdge:
        """Add an edge between two nodes."""
        if source_node_id not in self.nodes or target_node_id not in self.nodes:
            raise ValueError("Both source and target nodes must exist")
        
        edge_id = self._generate_edge_id(source_node_id, target_node_id, relationship)
        
        edge = KnowledgeEdge(
            edge_id=edge_id,
            source_node=source_node_id,
            target_node=target_node_id,
            relationship=relationship,
            weight=weight,
            metadata=metadata or {},
        )
        
        self.edges[edge_id] = edge
        
        # Update adjacency list
        self.adjacency_list[source_node_id].add(target_node_id)
        self.adjacency_list[target_node_id].add(source_node_id)  # Bidirectional
        
        # Update related_nodes in both nodes
        if target_node_id not in self.nodes[source_node_id].related_nodes:
            self.nodes[source_node_id].related_nodes.append(target_node_id)
        if source_node_id not in self.nodes[target_node_id].related_nodes:
            self.nodes[target_node_id].related_nodes.append(source_node_id)
        
        return edge
    
    def find_similar(
        self,
        query_content: Dict[str, Any],
        node_type: Optional[str] = None,
        limit: int = 5,
    ) -> List[Tuple[KnowledgeNode, float]]:
        """Find nodes similar to query content using simple similarity."""
        results = []
        
        for node_id, node in self.nodes.items():
            if node_type and node.node_type != node_type:
                continue
            
            # Simple similarity based on shared tags and type
            similarity = 0.0
            
            # Tag overlap
            query_tags = set(query_content.get("tags", []))
            if query_tags:
                shared_tags = query_tags & set(node.tags)
                similarity += len(shared_tags) / max(len(query_tags), 1) * 0.5
            
            # Content keyword overlap
            query_keywords = set(str(v).lower() for v in query_content.values() if isinstance(v, str))
            node_keywords = set()
            for v in node.content.values():
                if isinstance(v, str):
                    node_keywords.update(v.lower().split())
            
            if query_keywords:
                shared_keywords = query_keywords & node_keywords
                similarity += len(shared_keywords) / max(len(query_keywords), 1) * 0.5
            
            if similarity > 0.1:  # Threshold
                results.append((node, similarity))
        
        # Sort by similarity
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]
    
    def search_by_type(self, node_type: str) -> List[KnowledgeNode]:
        """Get all nodes of a specific type."""
        node_ids = self.type_index.get(node_type, set())
        return [self.nodes[nid] for nid in node_ids if nid in self.nodes]
    
    def search_by_tag(self, tag: str) -> List[KnowledgeNode]:
        """Get all nodes with a specific tag."""
        node_ids = self.tag_index.get(tag, set())
        return [self.nodes[nid] for nid in node_ids if nid in self.nodes]
    
    def get_related(self, node_id: str, depth: int = 1) -> List[KnowledgeNode]:
        """Get nodes related to a given node up to specified depth."""
        if node_id not in self.nodes:
            return []
        
        visited = {node_id}
        queue = [(node_id, 0)]
        related = []
        
        while queue:
            current_id, current_depth = queue.pop(0)
            
            if current_depth >= depth:
                continue
            
            for neighbor_id in self.adjacency_list.get(current_id, set()):
                if neighbor_id not in visited and neighbor_id in self.nodes:
                    visited.add(neighbor_id)
                    related.append(self.nodes[neighbor_id])
                    
                    if current_depth + 1 < depth:
                        queue.append((neighbor_id, current_depth + 1))
        
        return related
    
    def record_fix_application(
        self,
        failure_pattern_id: str,
        fix_id: str,
        success: bool,
        context: Dict[str, Any],
    ) -> None:
        """Record when a fix is applied to a failure pattern."""
        # Ensure edge exists
        edge_id = self._generate_edge_id(failure_pattern_id, fix_id, "fixes")
        
        if edge_id not in self.edges:
            self.add_edge(failure_pattern_id, fix_id, "fixes", metadata={"applications": 0, "successes": 0})
        
        edge = self.edges[edge_id]
        edge.metadata["applications"] = edge.metadata.get("applications", 0) + 1
        
        if success:
            edge.metadata["successes"] = edge.metadata.get("successes", 0) + 1
        
        # Update confidence scores
        if success:
            self.nodes[fix_id].confidence_score = min(1.0, self.nodes[fix_id].confidence_score + 0.05)
            self.nodes[fix_id].usage_count += 1
            self.nodes[fix_id].last_used = time.time()
        else:
            self.nodes[fix_id].confidence_score = max(0.1, self.nodes[fix_id].confidence_score - 0.1)
    
    def get_best_fixes(
        self,
        failure_pattern_id: str,
        limit: int = 3,
    ) -> List[Tuple[KnowledgeNode, float]]:
        """Get best fixes for a failure pattern based on success rate."""
        if failure_pattern_id not in self.nodes:
            return []
        
        fixes = []
        
        for neighbor_id in self.adjacency_list.get(failure_pattern_id, set()):
            if neighbor_id in self.nodes and self.nodes[neighbor_id].node_type == "fix":
                edge_id = self._generate_edge_id(failure_pattern_id, neighbor_id, "fixes")
                
                if edge_id in self.edges:
                    edge = self.edges[edge_id]
                    apps = edge.metadata.get("applications", 1)
                    successes = edge.metadata.get("successes", 0)
                    success_rate = successes / apps
                    
                    # Combined score: confidence * success_rate
                    combined_score = self.nodes[neighbor_id].confidence_score * success_rate
                    fixes.append((self.nodes[neighbor_id], combined_score))
        
        fixes.sort(key=lambda x: x[1], reverse=True)
        return fixes[:limit]
    
    def _save_to_disk(self) -> None:
        """Persist knowledge graph to disk."""
        graph_file = self.storage_dir / "knowledge_graph.json"
        
        data = {
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
            "edges": {eid: edge.to_dict() for eid, edge in self.edges.items()},
            "type_index": {k: list(v) for k, v in self.type_index.items()},
            "tag_index": {k: list(v) for k, v in self.tag_index.items()},
            "saved_at": datetime.now().isoformat(),
        }
        
        with open(graph_file, "w") as f:
            json.dump(data, f, indent=2)
    
    def _load_from_disk(self) -> None:
        """Load knowledge graph from disk."""
        graph_file = self.storage_dir / "knowledge_graph.json"
        
        if not graph_file.exists():
            return
        
        try:
            with open(graph_file, "r") as f:
                data = json.load(f)
            
            # Reconstruct nodes
            for node_id, node_data in data.get("nodes", {}).items():
                self.nodes[node_id] = KnowledgeNode(
                    node_id=node_data["node_id"],
                    node_type=node_data["node_type"],
                    title=node_data["title"],
                    description=node_data["description"],
                    content=node_data["content"],
                    confidence_score=node_data.get("confidence_score", 1.0),
                    usage_count=node_data.get("usage_count", 0),
                    last_used=node_data.get("last_used"),
                    created_at=node_data.get("created_at", time.time()),
                    created_by=node_data.get("created_by", "system"),
                    tags=node_data.get("tags", []),
                    related_nodes=node_data.get("related_nodes", []),
                )
                
                # Rebuild indexes
                node_type = node_data["node_type"]
                if node_type not in self.type_index:
                    self.type_index[node_type] = set()
                self.type_index[node_type].add(node_id)
                
                for tag in node_data.get("tags", []):
                    if tag not in self.tag_index:
                        self.tag_index[tag] = set()
                    self.tag_index[tag].add(node_id)
                
                if node_id not in self.adjacency_list:
                    self.adjacency_list[node_id] = set()
            
            # Reconstruct edges
            for edge_id, edge_data in data.get("edges", {}).items():
                self.edges[edge_id] = KnowledgeEdge(
                    edge_id=edge_data["edge_id"],
                    source_node=edge_data["source_node"],
                    target_node=edge_data["target_node"],
                    relationship=edge_data["relationship"],
                    weight=edge_data.get("weight", 1.0),
                    metadata=edge_data.get("metadata", {}),
                )
                
                # Rebuild adjacency list
                src, tgt = edge_data["source_node"], edge_data["target_node"]
                self.adjacency_list.setdefault(src, set()).add(tgt)
                self.adjacency_list.setdefault(tgt, set()).add(src)
            
            # Rebuild type and tag indexes from saved data
            for node_type, node_ids in data.get("type_index", {}).items():
                self.type_index[node_type] = set(node_ids)
            
            for tag, node_ids in data.get("tag_index", {}).items():
                self.tag_index[tag] = set(node_ids)
                
        except Exception as e:
            print(f"Warning: Could not load knowledge graph: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get knowledge graph statistics."""
        by_type = {}
        for node in self.nodes.values():
            by_type[node.node_type] = by_type.get(node.node_type, 0) + 1
        
        total_edges = len(self.edges)
        avg_confidence = sum(n.confidence_score for n in self.nodes.values()) / max(len(self.nodes), 1)
        
        return {
            "total_nodes": len(self.nodes),
            "total_edges": total_edges,
            "by_type": by_type,
            "average_confidence": avg_confidence,
            "most_used_nodes": sorted(
                [(n.node_id, n.title, n.usage_count) for n in self.nodes.values()],
                key=lambda x: x[2],
                reverse=True,
            )[:5],
        }


class SharedMemory:
    """High-level interface for cross-agent memory sharing."""
    
    def __init__(self, storage_dir: str = ".tardis/memory"):
        self.graph = KnowledgeGraph(storage_dir)
        self.agent_id: Optional[str] = None
    
    def set_agent_id(self, agent_id: str) -> None:
        """Set the current agent's ID for attribution."""
        self.agent_id = agent_id
    
    def store_failure_pattern(
        self,
        title: str,
        description: str,
        pattern_data: Dict[str, Any],
        tags: Optional[List[str]] = None,
    ) -> KnowledgeNode:
        """Store a learned failure pattern."""
        return self.graph.add_node(
            node_type="failure_pattern",
            title=title,
            description=description,
            content=pattern_data,
            tags=tags,
            created_by=self.agent_id or "unknown",
        )
    
    def store_fix(
        self,
        title: str,
        description: str,
        fix_data: Dict[str, Any],
        tags: Optional[List[str]] = None,
    ) -> KnowledgeNode:
        """Store a fix solution."""
        return self.graph.add_node(
            node_type="fix",
            title=title,
            description=description,
            content=fix_data,
            tags=tags,
            created_by=self.agent_id or "unknown",
        )
    
    def link_fix_to_failure(self, failure_id: str, fix_id: str, success: bool = True) -> None:
        """Link a fix to a failure pattern and record application result."""
        self.graph.add_edge(failure_id, fix_id, "fixes")
        self.graph.record_fix_application(failure_id, fix_id, success, {})
    
    def find_similar_failures(self, failure_description: str, tags: List[str]) -> List[Tuple[KnowledgeNode, float]]:
        """Find similar failure patterns."""
        return self.graph.find_similar(
            {"description": failure_description, "tags": tags},
            node_type="failure_pattern",
        )
    
    def get_recommended_fixes(self, failure_id: str) -> List[Tuple[KnowledgeNode, float]]:
        """Get recommended fixes for a failure pattern."""
        return self.graph.get_best_fixes(failure_id)
    
    def save(self) -> None:
        """Persist memory to disk."""
        self.graph._save_to_disk()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get memory statistics."""
        return self.graph.get_statistics()


# Convenience functions
def create_shared_memory(agent_id: Optional[str] = None) -> SharedMemory:
    """Create a shared memory instance."""
    memory = SharedMemory()
    if agent_id:
        memory.set_agent_id(agent_id)
    return memory


def enable_knowledge_sharing(agent_id: str) -> SharedMemory:
    """Enable knowledge sharing for an agent."""
    return create_shared_memory(agent_id)


# Alias for consistency
KnowledgeGraphMemory = SharedMemory
