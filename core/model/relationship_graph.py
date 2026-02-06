"""
Relationship Graph Analyzer

This module provides graph-based analysis of model relationships using network theory.
Requires networkx library for graph operations.
"""

from typing import List, Dict, Any, Tuple, Set, Optional
import logging

logger = logging.getLogger(__name__)

# Try to import networkx, but make it optional
try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False
    logger.warning("networkx not available - relationship graph analysis will use fallback implementation")


class RelationshipGraph:
    """Graph-based relationship analysis"""

    def __init__(self, relationships: List[Dict[str, Any]]):
        """
        Initialize relationship graph

        Args:
            relationships: List of relationship dictionaries from list_relationships
        """
        self.relationships = relationships

        if NETWORKX_AVAILABLE:
            self.graph = nx.DiGraph()
            self._build_networkx_graph(relationships)
        else:
            # Fallback implementation without networkx
            self.adjacency = {}
            self._build_fallback_graph(relationships)

    def _build_networkx_graph(self, relationships: List[Dict[str, Any]]):
        """Build NetworkX graph from relationships"""
        for rel in relationships:
            from_table = rel.get('fromTable')
            to_table = rel.get('toTable')
            is_active = rel.get('isActive', True)

            if from_table and to_table:
                self.graph.add_edge(
                    from_table,
                    to_table,
                    active=is_active,
                    from_column=rel.get('fromColumn', ''),
                    to_column=rel.get('toColumn', ''),
                    from_cardinality=rel.get('fromCardinality', ''),
                    to_cardinality=rel.get('toCardinality', ''),
                    cross_filter=rel.get('crossFilteringBehavior', 'single')
                )

    def _build_fallback_graph(self, relationships: List[Dict[str, Any]]):
        """Build simple adjacency list without networkx"""
        for rel in relationships:
            from_table = rel.get('fromTable')
            to_table = rel.get('toTable')

            if from_table and to_table:
                if from_table not in self.adjacency:
                    self.adjacency[from_table] = []

                self.adjacency[from_table].append({
                    'to': to_table,
                    'active': rel.get('isActive', True),
                    'metadata': rel
                })

    def find_path(self, from_table: str, to_table: str, active_only: bool = True) -> List[str]:
        """
        Find shortest path between tables

        Args:
            from_table: Starting table
            to_table: Destination table
            active_only: Only use active relationships

        Returns:
            List of table names forming the path, or empty list if no path exists
        """
        if NETWORKX_AVAILABLE:
            return self._find_path_networkx(from_table, to_table, active_only)
        else:
            return self._find_path_fallback(from_table, to_table, active_only)

    def _find_path_networkx(self, from_table: str, to_table: str, active_only: bool) -> List[str]:
        """Find path using NetworkX"""
        if active_only:
            # Filter to active relationships
            active_graph = nx.DiGraph()
            for u, v, data in self.graph.edges(data=True):
                if data.get('active', True):
                    active_graph.add_edge(u, v, **data)
            graph = active_graph
        else:
            graph = self.graph

        try:
            # Try undirected for bidirectional search
            undirected = graph.to_undirected()
            path = nx.shortest_path(undirected, from_table, to_table)
            return path
        except nx.NetworkXNoPath:
            return []
        except nx.NodeNotFound:
            return []

    def _find_path_fallback(self, from_table: str, to_table: str, active_only: bool) -> List[str]:
        """Find path using BFS without NetworkX"""
        if from_table not in self.adjacency:
            return []

        # BFS to find path
        queue = [(from_table, [from_table])]
        visited = {from_table}

        while queue:
            current, path = queue.pop(0)

            if current == to_table:
                return path

            if current in self.adjacency:
                for edge in self.adjacency[current]:
                    neighbor = edge['to']

                    if active_only and not edge['active']:
                        continue

                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append((neighbor, path + [neighbor]))

        return []

    def find_all_paths(
        self,
        from_table: str,
        to_table: str,
        max_length: int = 5
    ) -> List[List[str]]:
        """
        Find all paths between tables (identifies ambiguous relationships)

        Args:
            from_table: Starting table
            to_table: Destination table
            max_length: Maximum path length to consider

        Returns:
            List of paths, each path is a list of table names
        """
        if NETWORKX_AVAILABLE:
            try:
                undirected = self.graph.to_undirected()
                paths = list(nx.all_simple_paths(undirected, from_table, to_table, cutoff=max_length))
                return paths
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                return []
        else:
            # Simplified fallback - just return single shortest path
            path = self.find_path(from_table, to_table)
            return [path] if path else []

    def find_disconnected_tables(self, all_tables: List[str]) -> List[List[str]]:
        """
        Find groups of disconnected tables (islands in the graph)

        Args:
            all_tables: List of all table names in the model

        Returns:
            List of groups, where each group is a list of connected tables
        """
        if NETWORKX_AVAILABLE:
            # Add all tables as nodes (even if they have no edges)
            for table in all_tables:
                if table not in self.graph:
                    self.graph.add_node(table)

            undirected = self.graph.to_undirected()
            components = list(nx.connected_components(undirected))

            return [list(comp) for comp in components]
        else:
            # Fallback: find tables not in adjacency list
            connected_tables = set(self.adjacency.keys())
            for edges in self.adjacency.values():
                for edge in edges:
                    connected_tables.add(edge['to'])

            orphaned = [t for t in all_tables if t not in connected_tables]

            if orphaned:
                return [[t] for t in orphaned] + [list(connected_tables)]
            else:
                return [list(connected_tables)]

    def get_table_centrality(self) -> Dict[str, float]:
        """
        Calculate centrality scores for tables (which tables are most connected)

        Returns:
            Dictionary mapping table names to centrality scores (0-1)
        """
        if NETWORKX_AVAILABLE:
            try:
                centrality = nx.degree_centrality(self.graph.to_undirected())
                return dict(sorted(centrality.items(), key=lambda x: x[1], reverse=True))
            except Exception:
                return {}
        else:
            # Fallback: simple degree count
            degree = {}

            for from_table, edges in self.adjacency.items():
                degree[from_table] = degree.get(from_table, 0) + len(edges)

                for edge in edges:
                    to_table = edge['to']
                    degree[to_table] = degree.get(to_table, 0) + 1

            # Normalize
            max_degree = max(degree.values()) if degree else 1
            centrality = {table: count / max_degree for table, count in degree.items()}

            return dict(sorted(centrality.items(), key=lambda x: x[1], reverse=True))

    def identify_hub_tables(self, threshold: float = 0.5) -> List[Dict[str, Any]]:
        """
        Identify hub tables (tables with high centrality)

        Args:
            threshold: Centrality threshold for hub identification

        Returns:
            List of hub tables with their centrality scores
        """
        centrality = self.get_table_centrality()

        hubs = [
            {'table': table, 'centrality': score, 'role': 'hub'}
            for table, score in centrality.items()
            if score >= threshold
        ]

        return hubs

    def suggest_missing_relationships(
        self,
        tables_used_together: List[Tuple[str, str]]
    ) -> List[Dict[str, Any]]:
        """
        Suggest potential missing relationships based on table usage patterns

        Args:
            tables_used_together: List of (table1, table2) tuples that are used together

        Returns:
            List of suggestions for missing relationships
        """
        suggestions = []

        for table1, table2 in tables_used_together:
            path = self.find_path(table1, table2)

            if not path:
                # No path exists - might need a relationship
                suggestions.append({
                    'from_table': table1,
                    'to_table': table2,
                    'reason': 'Tables used together but not connected',
                    'severity': 'high',
                    'recommendation': f'Check if {table1} and {table2} should have a direct relationship'
                })
            elif len(path) > 3:
                # Path exists but is long - might benefit from shortcut
                suggestions.append({
                    'from_table': table1,
                    'to_table': table2,
                    'reason': f'Tables connected via long path ({len(path)} hops)',
                    'severity': 'low',
                    'recommendation': f'Consider adding direct relationship if frequently used together',
                    'current_path': ' → '.join(path)
                })

        return suggestions

    def detect_relationship_issues(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Detect common relationship issues

        Returns:
            Dictionary of issue categories with lists of specific issues
        """
        issues = {
            'many_to_many': [],
            'inactive': [],
            'bidirectional': [],
            'circular': [],
            'ambiguous_paths': []
        }

        # Check for many-to-many relationships
        for rel in self.relationships:
            from_card = rel.get('fromCardinality', '')
            to_card = rel.get('toCardinality', '')
            from_table = rel.get('fromTable', '')
            to_table = rel.get('toTable', '')

            if from_card == 'many' and to_card == 'many':
                issues['many_to_many'].append({
                    'from_table': from_table,
                    'to_table': to_table,
                    'issue': 'Many-to-many relationship can cause unexpected aggregation',
                    'severity': 'high'
                })

            # Check for inactive relationships
            if not rel.get('isActive', True):
                issues['inactive'].append({
                    'from_table': from_table,
                    'to_table': to_table,
                    'issue': 'Inactive relationship must be explicitly activated with USERELATIONSHIP',
                    'severity': 'low'
                })

            # Check for bidirectional filtering
            if rel.get('crossFilteringBehavior') == 'bothDirections':
                issues['bidirectional'].append({
                    'from_table': from_table,
                    'to_table': to_table,
                    'issue': 'Bidirectional filtering can cause performance issues',
                    'severity': 'medium'
                })

        # Check for circular relationships (if networkx available)
        if NETWORKX_AVAILABLE:
            try:
                cycles = list(nx.simple_cycles(self.graph))
                if cycles:
                    for cycle in cycles:
                        issues['circular'].append({
                            'cycle': ' → '.join(cycle + [cycle[0]]),
                            'issue': 'Circular relationship path detected',
                            'severity': 'high'
                        })
            except Exception:
                pass

        return issues

    def get_relationship_metrics(self) -> Dict[str, Any]:
        """
        Get overall relationship metrics

        Returns:
            Dictionary of metrics about the relationship graph
        """
        metrics = {
            'total_relationships': len(self.relationships),
            'active_relationships': sum(1 for r in self.relationships if r.get('isActive', True)),
            'inactive_relationships': sum(1 for r in self.relationships if not r.get('isActive', True)),
            'many_to_many': sum(
                1 for r in self.relationships
                if r.get('fromCardinality') == 'many' and r.get('toCardinality') == 'many'
            ),
            'one_to_many': sum(
                1 for r in self.relationships
                if (r.get('fromCardinality') == 'one' and r.get('toCardinality') == 'many') or
                   (r.get('fromCardinality') == 'many' and r.get('toCardinality') == 'one')
            ),
            'bidirectional': sum(
                1 for r in self.relationships
                if r.get('crossFilteringBehavior') == 'bothDirections'
            )
        }

        if NETWORKX_AVAILABLE and self.graph:
            try:
                metrics['connected_components'] = nx.number_weakly_connected_components(self.graph)
                metrics['is_dag'] = nx.is_directed_acyclic_graph(self.graph)
            except Exception:
                pass

        return metrics

    def visualize_subgraph(
        self,
        tables: List[str],
        include_neighbors: bool = True
    ) -> Dict[str, Any]:
        """
        Get a subgraph visualization data for specific tables

        Args:
            tables: List of tables to include
            include_neighbors: Include directly connected tables

        Returns:
            Dictionary with nodes and edges for visualization
        """
        nodes = set(tables)

        if include_neighbors:
            for table in tables:
                if NETWORKX_AVAILABLE and table in self.graph:
                    # Add predecessors and successors
                    nodes.update(self.graph.predecessors(table))
                    nodes.update(self.graph.successors(table))
                elif table in self.adjacency:
                    # Add connected tables from adjacency
                    for edge in self.adjacency[table]:
                        nodes.add(edge['to'])

        # Get edges between nodes
        edges = []
        for rel in self.relationships:
            from_table = rel.get('fromTable')
            to_table = rel.get('toTable')

            if from_table in nodes and to_table in nodes:
                edges.append({
                    'from': from_table,
                    'to': to_table,
                    'active': rel.get('isActive', True),
                    'cardinality': f"{rel.get('fromCardinality')}:{rel.get('toCardinality')}",
                    'bidirectional': rel.get('crossFilteringBehavior') == 'bothDirections'
                })

        return {
            'nodes': list(nodes),
            'edges': edges,
            'node_count': len(nodes),
            'edge_count': len(edges)
        }

    def find_fact_and_dimension_tables(self) -> Dict[str, List[str]]:
        """
        Attempt to identify fact and dimension tables based on relationship patterns

        Returns:
            Dictionary with 'fact_tables' and 'dimension_tables' lists
        """
        # Heuristic: Fact tables typically have many outgoing one-to-many relationships
        # Dimension tables typically have few or no outgoing relationships

        table_outgoing = {}
        table_incoming = {}

        for rel in self.relationships:
            from_table = rel.get('fromTable', '')
            to_table = rel.get('toTable', '')
            from_card = rel.get('fromCardinality', '')
            to_card = rel.get('toCardinality', '')

            # Count many-side relationships
            if from_card == 'many':
                table_outgoing[from_table] = table_outgoing.get(from_table, 0) + 1

            if to_card == 'many':
                table_incoming[to_table] = table_incoming.get(to_table, 0) + 1

        # Fact tables likely have high outgoing count (many-to-one relationships)
        fact_tables = [
            table for table, count in table_outgoing.items()
            if count >= 2  # Connected to at least 2 dimension tables
        ]

        # Dimension tables have low or no outgoing relationships
        all_tables = set(table_outgoing.keys()) | set(table_incoming.keys())
        dimension_tables = [
            table for table in all_tables
            if table_outgoing.get(table, 0) <= 1 and table not in fact_tables
        ]

        return {
            'fact_tables': fact_tables,
            'dimension_tables': dimension_tables
        }


def analyze_relationship_structure(relationships: List[Dict[str, Any]], all_tables: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Comprehensive relationship structure analysis

    Args:
        relationships: List of relationships from list_relationships
        all_tables: Optional list of all tables in the model

    Returns:
        Complete analysis of relationship structure
    """
    graph = RelationshipGraph(relationships)

    analysis = {
        'metrics': graph.get_relationship_metrics(),
        'issues': graph.detect_relationship_issues(),
        'centrality': graph.get_table_centrality(),
        'hubs': graph.identify_hub_tables()
    }

    # Add disconnected tables if all_tables provided
    if all_tables:
        components = graph.find_disconnected_tables(all_tables)
        analysis['connected_components'] = len(components)
        analysis['largest_component_size'] = max(len(c) for c in components) if components else 0

        # Find orphaned tables
        orphaned = [c for c in components if len(c) == 1]
        if orphaned:
            analysis['orphaned_tables'] = [t[0] for t in orphaned]

    # Identify fact and dimension tables
    fact_dim = graph.find_fact_and_dimension_tables()
    analysis['model_structure'] = fact_dim

    return analysis
