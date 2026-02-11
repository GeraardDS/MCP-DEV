"""
Dependency and usage analyzer for Power BI models.
Tracks dependencies and usage patterns across measures, columns, and relationships.
"""

import logging
import time
from typing import Dict, List, Set, Tuple, Optional, Any
from core.config.config_manager import config

# Import from dedicated parser module (breaks circular dependency)
from core.dax.dax_reference_parser import DaxReferenceIndex, parse_dax_references

logger = logging.getLogger(__name__)


class DependencyAnalyzer:
    """Analyzes usage patterns and dependencies in Power BI models."""

    def __init__(self, query_executor):
        self.query_executor = query_executor
        self._ref_index = None

        # DAX Parse Cache: (measure_name, expression_hash) -> parsed_references
        # This cache avoids re-parsing the same DAX expressions repeatedly
        self._parse_cache: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self._parse_cache_timestamps: Dict[Tuple[str, int], float] = {}
        self._cache_ttl = config.get('performance.dependency_cache_ttl', 600)  # 10 minutes default

        # Cache statistics
        self._cache_hits = 0
        self._cache_misses = 0
    
    def _ensure_reference_index(self):
        """Lazily build the reference index"""
        if self._ref_index is not None:
            return self._ref_index

        measures_result = self.query_executor.execute_info_query("MEASURES")
        columns_result = self.query_executor.execute_info_query("COLUMNS")

        measure_rows = measures_result.get('rows', []) if measures_result.get('success') else []
        column_rows = columns_result.get('rows', []) if columns_result.get('success') else []

        self._ref_index = DaxReferenceIndex(measure_rows, column_rows)
        return self._ref_index

    def _parse_dax_cached(self, measure_name: str, expression: str) -> Dict[str, Any]:
        """
        Parse DAX expression with caching to avoid re-parsing the same expressions.

        Args:
            measure_name: Name of the measure (for cache key)
            expression: DAX expression to parse

        Returns:
            Parsed references dictionary
        """
        # Create cache key from measure name and expression hash
        cache_key = (measure_name, hash(expression))

        # Check if cache is valid
        if cache_key in self._parse_cache:
            # Check TTL
            timestamp = self._parse_cache_timestamps.get(cache_key, 0)
            age = time.time() - timestamp

            if age <= self._cache_ttl:
                self._cache_hits += 1
                logger.debug(f"DAX parse cache hit for {measure_name} (age: {age:.1f}s)")
                return self._parse_cache[cache_key]
            else:
                # Expired, remove from cache
                del self._parse_cache[cache_key]
                del self._parse_cache_timestamps[cache_key]

        # Cache miss - parse the DAX
        self._cache_misses += 1
        ref_index = self._ensure_reference_index()
        refs = parse_dax_references(expression, ref_index)

        # Store in cache with timestamp
        self._parse_cache[cache_key] = refs
        self._parse_cache_timestamps[cache_key] = time.time()

        logger.debug(f"DAX parse cache miss for {measure_name} (cache size: {len(self._parse_cache)})")
        return refs

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for monitoring performance."""
        total_requests = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total_requests * 100) if total_requests > 0 else 0

        return {
            'success': True,
            'cache_size': len(self._parse_cache),
            'cache_hits': self._cache_hits,
            'cache_misses': self._cache_misses,
            'total_requests': total_requests,
            'hit_rate_percent': round(hit_rate, 1),
            'ttl_seconds': self._cache_ttl
        }

    def clear_cache(self) -> Dict[str, Any]:
        """Clear the DAX parse cache and reference index."""
        cache_size = len(self._parse_cache)
        self._parse_cache.clear()
        self._parse_cache_timestamps.clear()
        self._ref_index = None  # Force rebuild of reference index
        logger.info(f"Cleared DAX parse cache ({cache_size} entries) and reference index")

        return {
            'success': True,
            'cleared_entries': cache_size,
            'message': f'Cleared {cache_size} cached parse results and reference index'
        }
    
    def analyze_measure_dependencies(self, table: str, measure: str, include_diagram: bool = False) -> Dict:
        """Analyze dependencies for a specific measure

        Args:
            table: Table name containing the measure
            measure: Measure name
            include_diagram: If True, include a Mermaid diagram in the response

        Returns:
            Dictionary with dependency information and optionally a Mermaid diagram
        """
        # Use get_measure_details_with_fallback for proper table+measure filtering
        result = self.query_executor.get_measure_details_with_fallback(table, measure)
        if not result.get('success'):
            return {'success': False, 'error': result.get('error')}

        rows = result.get('rows', [])
        if not rows:
            return {'success': False, 'error': f"Measure {table}[{measure}] not found"}

        measure_row = rows[0]
        expression = measure_row.get('Expression', '')

        # Use cached parsing (PERFORMANCE IMPROVEMENT)
        measure_key = f"{table}[{measure}]"
        refs = self._parse_dax_cached(measure_key, expression)

        response = {
            'success': True,
            'measure': {'table': table, 'name': measure},
            'expression': expression,
            'dependencies': refs,
            'referenced_measures': refs.get('measures', []),
            'referenced_columns': refs.get('columns', []),
            'referenced_tables': refs.get('tables', [])
        }

        # Include Mermaid diagram if requested
        if include_diagram:
            diagram_result = self.generate_dependency_mermaid(table, measure, direction="upstream", depth=3)
            if diagram_result.get('success'):
                response['mermaid_diagram'] = diagram_result.get('mermaid', '')

        return response
    
    def find_measure_usage(self, table: str, measure: str) -> Dict:
        """Find where a measure is used by other measures"""
        measures_result = self.query_executor.execute_info_query("MEASURES")
        if not measures_result.get('success'):
            return {'success': False, 'error': measures_result.get('error')}

        all_measures = measures_result.get('rows', [])
        usage_list = []

        for m in all_measures:
            m_table = m.get('Table', '')
            m_name = m.get('Name', '')
            if m_table == table and m_name == measure:
                continue

            expression = m.get('Expression', '')

            # Use cached parsing (PERFORMANCE IMPROVEMENT)
            measure_key = f"{m_table}[{m_name}]"
            refs = self._parse_dax_cached(measure_key, expression)

            for ref_table, ref_name in refs.get('measures', []):
                if (ref_table == table or ref_table == '') and ref_name == measure:
                    usage_list.append({
                        'table': m_table,
                        'measure': m_name,
                        'display_folder': m.get('DisplayFolder', '') or ''
                    })
                    break

        return {
            'success': True,
            'measure': {'table': table, 'name': measure},
            'used_by': usage_list,
            'usage_count': len(usage_list)
        }
    
    def build_dependency_tree(self, table: str, measure: str, max_depth: int = 5) -> Dict:
        """Build a full dependency tree for a measure"""
        def recurse(tbl, msr, depth, visited):
            if depth > max_depth:
                return {'table': tbl, 'measure': msr, 'max_depth_reached': True}

            key = f"{tbl}|{msr}"
            if key in visited:
                return {'table': tbl, 'measure': msr, 'circular': True}

            visited.add(key)
            deps_result = self.analyze_measure_dependencies(tbl, msr)

            if not deps_result.get('success'):
                return {'table': tbl, 'measure': msr, 'error': deps_result.get('error')}

            children = []
            for dep_table, dep_name in deps_result.get('referenced_measures', []):
                if dep_table:
                    child = recurse(dep_table, dep_name, depth + 1, visited.copy())
                    children.append(child)

            return {
                'table': tbl,
                'measure': msr,
                'expression': deps_result.get('expression', ''),
                'dependencies': children,
                'depth': depth
            }

        tree = recurse(table, measure, 0, set())
        return {'success': True, 'tree': tree}

    def analyze_dependencies(self, table: str, measure: str, depth: int = 3, include_diagram: bool = True) -> Dict:
        """
        Alias for analyze_measure_dependencies with optional depth parameter.
        Used by tool handlers for backward compatibility.

        Args:
            table: Table name containing the measure
            measure: Measure name
            depth: Maximum depth for tree traversal (default: 3)
            include_diagram: If True, include a Mermaid diagram in the response (default: True)
        """
        result = self.analyze_measure_dependencies(table, measure, include_diagram=include_diagram)
        if not result.get('success'):
            return result

        # If depth > 1, build full dependency tree
        if depth > 1:
            tree_result = self.build_dependency_tree(table, measure, depth)
            if tree_result.get('success'):
                result['dependency_tree'] = tree_result.get('tree')

        return result

    def get_measure_impact(self, table: str, measure: str, depth: int = 3) -> Dict:
        """
        Alias that combines find_measure_usage with dependency analysis.
        Returns both upstream dependencies and downstream usage.
        """
        # Get downstream usage (what uses this measure)
        usage_result = self.find_measure_usage(table, measure)

        # Get upstream dependencies (what this measure uses)
        deps_result = self.analyze_measure_dependencies(table, measure)

        # Combine results
        result = {
            'success': True,
            'measure': {'table': table, 'name': measure},
            'downstream_usage': usage_result.get('used_by', []) if usage_result.get('success') else [],
            'downstream_count': usage_result.get('usage_count', 0) if usage_result.get('success') else 0,
            'upstream_dependencies': {
                'measures': deps_result.get('referenced_measures', []) if deps_result.get('success') else [],
                'columns': deps_result.get('referenced_columns', []) if deps_result.get('success') else [],
                'tables': deps_result.get('referenced_tables', []) if deps_result.get('success') else []
            }
        }

        return result

    def get_measure_impact_score(self, table: str, measure: str, depth: int = 10) -> Dict[str, Any]:
        """
        Calculate comprehensive impact score for a measure to prioritize refactoring.

        Impact Score is calculated based on:
        - Number of direct dependent measures
        - Number of total (transitive) dependent measures
        - Presence in calculation groups
        - Usage in RLS rules (future enhancement)

        Args:
            table: Table name containing the measure
            measure: Measure name
            depth: Maximum depth for transitive dependency analysis (default: 10)

        Returns:
            Dictionary with impact score and breakdown
        """
        try:
            # Get direct downstream usage
            usage_result = self.find_measure_usage(table, measure)
            if not usage_result.get('success'):
                return {'success': False, 'error': usage_result.get('error')}

            direct_dependents = usage_result.get('used_by', [])
            direct_count = len(direct_dependents)

            # Calculate transitive dependents (recursive depth search)
            all_dependents = set()
            visited = set()

            def find_transitive_dependents(t, m, current_depth):
                if current_depth > depth:
                    return
                key = f"{t}[{m}]"
                if key in visited:
                    return
                visited.add(key)

                usage = self.find_measure_usage(t, m)
                if usage.get('success'):
                    for dep in usage.get('used_by', []):
                        dep_key = f"{dep['table']}[{dep['measure']}]"
                        all_dependents.add(dep_key)
                        find_transitive_dependents(dep['table'], dep['measure'], current_depth + 1)

            # Start recursive search
            find_transitive_dependents(table, measure, 0)
            total_dependents = len(all_dependents)

            # Check calculation group usage (placeholder - requires TOM access)
            in_calc_groups = self._check_calc_group_usage(table, measure)

            # Check RLS usage (placeholder - requires TOM access)
            in_rls = self._check_rls_usage(table, measure)

            # Calculate impact level
            if total_dependents > 10 or in_calc_groups:
                impact_level = 'HIGH'
            elif total_dependents > 3:
                impact_level = 'MEDIUM'
            else:
                impact_level = 'LOW'

            return {
                'success': True,
                'measure': {'table': table, 'name': measure},
                'impact_score': {
                    'direct_dependents': direct_count,
                    'total_dependents': total_dependents,
                    'transitive_dependents': total_dependents - direct_count,
                    'in_calculation_groups': in_calc_groups,
                    'in_rls_rules': in_rls,
                    'impact_level': impact_level
                },
                'direct_dependent_list': direct_dependents[:10],  # Limit to first 10 for readability
                'recommendation': self._get_impact_recommendation(impact_level, total_dependents)
            }

        except Exception as e:
            logger.error(f"Error calculating impact score for {table}[{measure}]: {e}")
            return {'success': False, 'error': str(e)}

    def _check_calc_group_usage(self, table: str, measure: str) -> bool:
        """
        Check if measure is referenced in calculation groups.

        Uses DMV query to get calculation items and checks if the measure
        is referenced in any calculation item expression.

        Args:
            table: Table name containing the measure
            measure: Measure name

        Returns:
            True if measure is used in any calculation group
        """
        try:
            # Cache calculation group items to avoid repeated queries
            if not hasattr(self, '_calc_group_items_cache'):
                self._calc_group_items_cache = None
                self._calc_group_cache_built = False

            if not self._calc_group_cache_built:
                # Build cache of all calculation item expressions
                self._calc_group_items_cache = []

                # Query calculation groups using DMV
                calc_groups_query = """
                SELECT
                    [ID] AS [CalcGroupID],
                    [Name] AS [CalcGroupName],
                    [TableID]
                FROM $SYSTEM.TMSCHEMA_CALCULATION_GROUPS
                """
                calc_groups_result = self.query_executor.execute_dax_query(calc_groups_query, top_n=1000)

                if calc_groups_result.get('success') and calc_groups_result.get('rows'):
                    # Get calculation items for each group
                    calc_items_query = """
                    SELECT
                        [ID] AS [ItemID],
                        [Name] AS [ItemName],
                        [Expression],
                        [CalculationGroupID]
                    FROM $SYSTEM.TMSCHEMA_CALCULATION_ITEMS
                    """
                    calc_items_result = self.query_executor.execute_dax_query(calc_items_query, top_n=10000)

                    if calc_items_result.get('success') and calc_items_result.get('rows'):
                        for item in calc_items_result.get('rows', []):
                            expression = item.get('Expression', '') or item.get('[Expression]', '')
                            if expression:
                                self._calc_group_items_cache.append(expression)

                self._calc_group_cache_built = True

            # Check if measure is referenced in any calculation item
            if self._calc_group_items_cache:
                measure_patterns = [
                    f"[{measure}]",  # Unqualified reference
                    f"'{table}'[{measure}]",  # Qualified reference
                    f'"{table}"[{measure}]',  # Alternative qualified syntax
                ]

                for expr in self._calc_group_items_cache:
                    expr_lower = expr.lower()
                    for pattern in measure_patterns:
                        if pattern.lower() in expr_lower:
                            logger.debug(f"Measure {table}[{measure}] found in calculation group")
                            return True

            return False

        except Exception as e:
            logger.debug(f"Error checking calc group usage for {table}[{measure}]: {e}")
            return False

    def _check_rls_usage(self, table: str, measure: str) -> bool:
        """
        Check if measure is used in RLS (Row-Level Security) rules.

        Uses DMV query to get role table permissions and checks if the measure
        is referenced in any filter expression.

        Args:
            table: Table name containing the measure
            measure: Measure name

        Returns:
            True if measure is used in any RLS rule
        """
        try:
            # Cache RLS expressions to avoid repeated queries
            if not hasattr(self, '_rls_expressions_cache'):
                self._rls_expressions_cache = None
                self._rls_cache_built = False

            if not self._rls_cache_built:
                # Build cache of all RLS filter expressions
                self._rls_expressions_cache = []

                # Query role table permissions (RLS filters)
                rls_query = """
                SELECT
                    [ID],
                    [RoleID],
                    [TableID],
                    [FilterExpression]
                FROM $SYSTEM.TMSCHEMA_ROLE_TABLE_PERMISSIONS
                """
                rls_result = self.query_executor.execute_dax_query(rls_query, top_n=10000)

                if rls_result.get('success') and rls_result.get('rows'):
                    for row in rls_result.get('rows', []):
                        filter_expr = row.get('FilterExpression', '') or row.get('[FilterExpression]', '')
                        if filter_expr:
                            self._rls_expressions_cache.append(filter_expr)

                self._rls_cache_built = True

            # Check if measure is referenced in any RLS filter
            if self._rls_expressions_cache:
                measure_patterns = [
                    f"[{measure}]",  # Unqualified reference
                    f"'{table}'[{measure}]",  # Qualified reference
                    f'"{table}"[{measure}]',  # Alternative qualified syntax
                ]

                for expr in self._rls_expressions_cache:
                    expr_lower = expr.lower()
                    for pattern in measure_patterns:
                        if pattern.lower() in expr_lower:
                            logger.debug(f"Measure {table}[{measure}] found in RLS rule")
                            return True

            return False

        except Exception as e:
            logger.debug(f"Error checking RLS usage for {table}[{measure}]: {e}")
            return False

    def clear_security_caches(self) -> None:
        """
        Clear the RLS and calculation group caches.
        Call this when the model changes or after significant edits.
        """
        self._calc_group_items_cache = None
        self._calc_group_cache_built = False
        self._rls_expressions_cache = None
        self._rls_cache_built = False
        logger.debug("Cleared RLS and calculation group caches")

    def _get_impact_recommendation(self, impact_level: str, dependent_count: int) -> str:
        """Generate recommendation based on impact level."""
        if impact_level == 'HIGH':
            return f"High-impact measure ({dependent_count} dependents). Changes will affect many calculations. Test thoroughly."
        elif impact_level == 'MEDIUM':
            return f"Medium-impact measure ({dependent_count} dependents). Review downstream measures before modifying."
        else:
            return "Low-impact measure. Safe to modify or delete with minimal risk."

    def find_unused_measures(self, include_hidden: bool = False) -> Dict[str, Any]:
        """
        Identify measures with zero dependents and not used in calculation groups or RLS.
        These measures are safe to delete.

        Args:
            include_hidden: Include hidden measures in results (default: False)

        Returns:
            Dictionary with list of unused measures
        """
        try:
            # Get all measures
            measures_result = self.query_executor.execute_info_query("MEASURES")
            if not measures_result.get('success'):
                return {'success': False, 'error': measures_result.get('error')}

            all_measures = measures_result.get('rows', [])
            unused_measures = []

            logger.info(f"Analyzing {len(all_measures)} measures for usage...")

            for m in all_measures:
                m_table = m.get('Table', '') or m.get('[Table]', '')
                m_name = m.get('Name', '') or m.get('[Name]', '')
                is_hidden = m.get('IsHidden', False) or m.get('[IsHidden]', False)

                if not m_table or not m_name:
                    continue

                # Skip hidden measures unless explicitly included
                if is_hidden and not include_hidden:
                    continue

                # Get impact score
                impact = self.get_measure_impact_score(m_table, m_name, depth=3)  # Lower depth for performance

                if impact.get('success'):
                    score = impact.get('impact_score', {})
                    total_deps = score.get('total_dependents', 0)
                    in_calc_groups = score.get('in_calculation_groups', False)
                    in_rls = score.get('in_rls_rules', False)

                    # Measure is unused if it has no dependents and not used in calc groups/RLS
                    if total_deps == 0 and not in_calc_groups and not in_rls:
                        unused_measures.append({
                            'table': m_table,
                            'measure': m_name,
                            'is_hidden': is_hidden
                        })

            logger.info(f"Found {len(unused_measures)} unused measures")

            return {
                'success': True,
                'unused_measures': unused_measures,
                'total_unused': len(unused_measures),
                'total_analyzed': len(all_measures),
                'unused_percentage': round(len(unused_measures) / len(all_measures) * 100, 1) if all_measures else 0,
                'recommendation': f"Consider removing {len(unused_measures)} unused measures to simplify the model"
            }

        except Exception as e:
            logger.error(f"Error finding unused measures: {e}")
            return {'success': False, 'error': str(e)}

    def get_deep_dependencies(self, table: str, measure: str, depth: int = 10) -> Dict[str, Any]:
        """
        Analyze dependencies to specified depth (default 10) with visualization data.

        Args:
            table: Table name containing the measure
            measure: Measure name
            depth: Maximum depth to traverse (default: 10)

        Returns:
            Dictionary with deep dependency tree and visualization data
        """
        try:
            # Build deep dependency tree
            tree_result = self.build_dependency_tree(table, measure, depth)
            if not tree_result.get('success'):
                return tree_result

            tree = tree_result.get('tree', {})

            # Extract metrics from tree
            metrics = self._extract_tree_metrics(tree)

            return {
                'success': True,
                'measure': {'table': table, 'name': measure},
                'max_depth': depth,
                'actual_depth': metrics['max_depth_reached'],
                'dependency_tree': tree,
                'metrics': metrics,
                'visualization_data': self._generate_tree_visualization_data(tree)
            }

        except Exception as e:
            logger.error(f"Error analyzing deep dependencies for {table}[{measure}]: {e}")
            return {'success': False, 'error': str(e)}

    def _extract_tree_metrics(self, tree: Dict[str, Any]) -> Dict[str, Any]:
        """Extract metrics from dependency tree."""
        total_measures = 0
        max_depth = 0
        circular_refs = 0
        max_depth_exceeded = False

        def traverse(node, current_depth=0):
            nonlocal total_measures, max_depth, circular_refs, max_depth_exceeded

            total_measures += 1
            max_depth = max(max_depth, current_depth)

            if node.get('circular'):
                circular_refs += 1
            if node.get('max_depth_reached'):
                max_depth_exceeded = True

            for child in node.get('dependencies', []):
                traverse(child, current_depth + 1)

        traverse(tree)

        return {
            'total_measures': total_measures,
            'max_depth_reached': max_depth,
            'circular_references': circular_refs,
            'max_depth_exceeded': max_depth_exceeded
        }

    def _generate_tree_visualization_data(self, tree: Dict[str, Any]) -> Dict[str, Any]:
        """Generate data structure suitable for tree visualization (e.g., D3.js)."""
        def convert_node(node):
            result = {
                'name': f"{node.get('table', '')}[{node.get('measure', '')}]",
                'table': node.get('table', ''),
                'measure': node.get('measure', ''),
                'depth': node.get('depth', 0)
            }

            if node.get('circular'):
                result['circular'] = True
            if node.get('max_depth_reached'):
                result['max_depth_reached'] = True
            if node.get('error'):
                result['error'] = node['error']

            children = node.get('dependencies', [])
            if children:
                result['children'] = [convert_node(child) for child in children]

            return result

        return {
            'format': 'hierarchical',
            'tree': convert_node(tree),
            'description': 'Tree structure suitable for D3.js or similar visualization libraries'
        }

    def generate_dependency_mermaid(
        self,
        table: str,
        measure: str,
        direction: str = "upstream",
        depth: int = 5,
        include_columns: bool = True
    ) -> Dict[str, Any]:
        """
        Generate a Mermaid flowchart diagram of measure dependencies with subgraphs by table.

        Args:
            table: Table name containing the measure
            measure: Measure name
            direction: "downstream" (what depends on this) or "upstream" (what this depends on)
            depth: Maximum depth to traverse (default: 5)
            include_columns: Include column references in the diagram (default: True)

        Returns:
            Dictionary with Mermaid diagram code and metadata

        Example output:
            graph TB
                M_m_Amount_in_selected_currency["<b>Amount in selected currency</b><br/>(m)"]

                subgraph T1_s_Reporting_Currency["s Reporting Currency<br/>(Selection Table)"]
                    C1_0_Reporting_Currency["Reporting Currency"]
                end

                subgraph T2_f_Valtrans["f Valtrans<br/>(Fact Table)"]
                    C2_0_Amount_Base_Curr["Amount (Base Curr.)"]
                    C2_1_Amount_EUR["Amount (EUR)"]
                end

                M_m_Amount_in_selected_currency -->|"SELECTEDVALUE"| T1_s_Reporting_Currency
                M_m_Amount_in_selected_currency -->|"SUMX Iterator"| T2_f_Valtrans

                %% Styling
                classDef measureClass fill:#e1f5fe,stroke:#01579b,stroke-width:3px,color:#000
                classDef tableClass fill:#fff3e0,stroke:#e65100,stroke-width:2px,color:#000
        """
        try:
            measure_key = f"{table}[{measure}]"
            nodes_by_table: Dict[str, List[Tuple[str, str, str]]] = {}  # table -> [(node_key, node_name, node_type)]
            edges = []  # (source, target, label)
            visited = set()
            column_nodes = set()  # Track which nodes are columns

            from core.utilities.mermaid_utils import sanitize_node_id as _sanitize_node_id

            def sanitize_node_id(name: str, prefix: str = "M") -> str:
                return _sanitize_node_id(name, prefix=prefix)

            def get_table_type(tbl_name: str) -> str:
                """Determine table type hint based on naming convention"""
                tbl_lower = tbl_name.lower()
                if "_s_" in tbl_lower or tbl_lower.startswith("s_") or "selection" in tbl_lower:
                    return "(Selection Table)"
                elif "_f_" in tbl_lower or tbl_lower.startswith("f_") or "fact" in tbl_lower:
                    return "(Fact Table)"
                elif "_d_" in tbl_lower or tbl_lower.startswith("d_") or "dim" in tbl_lower:
                    return "(Dimension Table)"
                return ""

            def add_node_to_table(tbl: str, node_key: str, node_name: str, node_type: str):
                """Add a node to its table's subgraph"""
                if tbl not in nodes_by_table:
                    nodes_by_table[tbl] = []
                # Check if node already exists
                for existing_key, _, _ in nodes_by_table[tbl]:
                    if existing_key == node_key:
                        return
                nodes_by_table[tbl].append((node_key, node_name, node_type))

            # Build measure name lookup for resolving unqualified references
            from core.utilities.mermaid_utils import build_measure_name_lookup, resolve_measure_table as _resolve
            measures_result = self.query_executor.execute_info_query("MEASURES")
            measure_name_to_table = build_measure_name_lookup(measures_result)
            logger.debug(f"Built measure lookup with {len(measure_name_to_table)} entries for {len(measures_result.get('rows', []))} measures")

            def resolve_measure_table(dep_tbl: str, dep_name: str) -> str:
                return _resolve(dep_tbl, dep_name, measure_name_to_table)

            if direction == "upstream":
                # Get what this measure depends on
                def traverse_upstream(tbl: str, msr: str, current_depth: int):
                    if current_depth > depth:
                        return
                    key = f"{tbl}[{msr}]"
                    if key in visited:
                        return
                    visited.add(key)

                    # Add this measure to its table
                    add_node_to_table(tbl, key, msr, "measure")

                    deps_result = self.analyze_measure_dependencies(tbl, msr)
                    if deps_result.get('success'):
                        # Add measure dependencies
                        for dep_table, dep_name in deps_result.get('referenced_measures', []):
                            if dep_name:  # Only need name, table can be empty
                                effective_table = resolve_measure_table(dep_table, dep_name)
                                dep_key = f"{effective_table}[{dep_name}]"
                                add_node_to_table(effective_table, dep_key, dep_name, "measure")
                                edges.append((dep_key, key, ""))  # dependency -> measure
                                if effective_table and effective_table != 'Unknown':  # Only recurse if we have a valid table
                                    traverse_upstream(effective_table, dep_name, current_depth + 1)

                        # Add column dependencies
                        if include_columns:
                            for col_table, col_name in deps_result.get('referenced_columns', []):
                                col_key = f"{col_table}[{col_name}]"
                                add_node_to_table(col_table, col_key, col_name, "column")
                                column_nodes.add(col_key)
                                edges.append((col_key, key, ""))

                traverse_upstream(table, measure, 0)

            else:  # downstream
                # Get what depends on this measure
                def traverse_downstream(tbl: str, msr: str, current_depth: int):
                    if current_depth > depth:
                        return
                    key = f"{tbl}[{msr}]"
                    if key in visited:
                        return
                    visited.add(key)

                    # Add this measure to its table
                    add_node_to_table(tbl, key, msr, "measure")

                    usage_result = self.find_measure_usage(tbl, msr)
                    if usage_result.get('success'):
                        for dep in usage_result.get('used_by', []):
                            dep_table = dep.get('table', '')
                            dep_name = dep.get('measure', '')
                            if dep_table and dep_name:
                                dep_key = f"{dep_table}[{dep_name}]"
                                add_node_to_table(dep_table, dep_key, dep_name, "measure")
                                edges.append((key, dep_key, ""))  # measure -> dependent
                                traverse_downstream(dep_table, dep_name, current_depth + 1)

                traverse_downstream(table, measure, 0)

            # Generate Mermaid code with subgraphs
            lines = ["graph TB"]

            # Add root measure node first (outside subgraphs for emphasis)
            root_id = sanitize_node_id(measure, "M_m")
            lines.append(f'    {root_id}["<b>{measure}</b><br/>(m)"]')
            lines.append("")

            # Track node IDs for styling
            column_node_ids = []
            measure_node_ids = [root_id]

            # Add subgraphs for each table
            table_counter = 1
            node_id_map = {}  # Map original keys to Mermaid node IDs

            for tbl_name, nodes in sorted(nodes_by_table.items()):
                if tbl_name == table and len(nodes) == 1:
                    # Skip the root measure's table if it only contains the root
                    node_id_map[f"{tbl_name}[{nodes[0][1]}]"] = root_id
                    continue

                table_id = sanitize_node_id(tbl_name, f"T{table_counter}")
                table_type = get_table_type(tbl_name)

                lines.append(f'    subgraph {table_id}["{tbl_name}<br/>{table_type}"]')

                node_counter = 0
                for node_key, node_name, node_type in nodes:
                    # Skip root measure - already added above
                    if node_key == measure_key:
                        node_id_map[node_key] = root_id
                        continue

                    node_id = sanitize_node_id(node_name, f"C{table_counter}_{node_counter}")
                    node_id_map[node_key] = node_id

                    if node_type == "column":
                        lines.append(f'        {node_id}["{node_name}"]')
                        column_node_ids.append(node_id)
                    else:
                        lines.append(f'        {node_id}["{node_name}"]')
                        measure_node_ids.append(node_id)

                    node_counter += 1

                lines.append("    end")
                lines.append("")
                table_counter += 1

            # Add edges
            for source, target, label in edges:
                source_id = node_id_map.get(source, sanitize_node_id(source.split("[")[1].rstrip("]"), "M"))
                target_id = node_id_map.get(target, sanitize_node_id(target.split("[")[1].rstrip("]"), "M"))

                if label:
                    lines.append(f'    {source_id} -->|"{label}"| {target_id}')
                else:
                    lines.append(f"    {source_id} --> {target_id}")

            # Add styling
            lines.append("")
            lines.append("    %% Styling")
            lines.append("    classDef measureClass fill:#e1f5fe,stroke:#01579b,stroke-width:3px,color:#000")
            lines.append("    classDef tableClass fill:#fff3e0,stroke:#e65100,stroke-width:2px,color:#000")
            lines.append("    classDef columnClass fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px,color:#000")

            # Apply measure class to root
            lines.append(f"    class {root_id} measureClass")

            # Apply column class
            if column_node_ids:
                lines.append(f"    class {','.join(column_node_ids)} columnClass")

            mermaid_code = "\n".join(lines)

            # Return raw Mermaid code (no markdown fence) for API rendering
            # Markdown wrapping can be done at presentation layer if needed
            return {
                'success': True,
                'measure': {'table': table, 'name': measure},
                'direction': direction,
                'depth': depth,
                'mermaid': mermaid_code,
                'node_count': sum(len(nodes) for nodes in nodes_by_table.values()),
                'edge_count': len(edges),
                'format': 'mermaid_flowchart'
            }

        except Exception as e:
            logger.error(f"Error generating Mermaid diagram for {table}[{measure}]: {e}")
            return {'success': False, 'error': str(e)}

    def generate_full_dependency_matrix(self, max_measures: int = 100) -> Dict[str, Any]:
        """
        Generate a dependency matrix for all measures in the model.

        Useful for identifying "hub" measures that many others depend on.

        Args:
            max_measures: Maximum number of measures to analyze (default: 100)

        Returns:
            Dictionary with adjacency matrix and analysis
        """
        try:
            measures_result = self.query_executor.execute_info_query("MEASURES")
            if not measures_result.get('success'):
                return {'success': False, 'error': measures_result.get('error')}

            all_measures = measures_result.get('rows', [])[:max_measures]

            # Build measure list
            measure_list = []
            for m in all_measures:
                tbl = m.get('Table', '') or m.get('[Table]', '')
                name = m.get('Name', '') or m.get('[Name]', '')
                if tbl and name:
                    measure_list.append({'table': tbl, 'name': name, 'key': f"{tbl}[{name}]"})

            # Build adjacency data
            adjacency = {}  # measure_key -> list of dependent measure keys
            hub_scores = {}  # measure_key -> number of dependents

            for m in measure_list:
                key = m['key']
                usage = self.find_measure_usage(m['table'], m['name'])
                if usage.get('success'):
                    dependents = [f"{d['table']}[{d['measure']}]" for d in usage.get('used_by', [])]
                    adjacency[key] = dependents
                    hub_scores[key] = len(dependents)

            # Find top hubs (most depended-upon measures)
            sorted_hubs = sorted(hub_scores.items(), key=lambda x: x[1], reverse=True)
            top_hubs = [{'measure': k, 'dependents': v} for k, v in sorted_hubs[:10] if v > 0]

            # Find orphans (measures with no dependents and no dependencies)
            orphans = []
            for m in measure_list:
                key = m['key']
                deps = self.analyze_measure_dependencies(m['table'], m['name'])
                has_dependencies = bool(deps.get('referenced_measures', []))
                has_dependents = hub_scores.get(key, 0) > 0
                if not has_dependencies and not has_dependents:
                    orphans.append(m)

            return {
                'success': True,
                'total_measures': len(measure_list),
                'adjacency_list': adjacency,
                'hub_measures': top_hubs,
                'orphan_measures': orphans[:20],  # Limit orphans list
                'orphan_count': len(orphans),
                'summary': {
                    'total_edges': sum(len(deps) for deps in adjacency.values()),
                    'avg_dependents': round(sum(hub_scores.values()) / len(hub_scores), 2) if hub_scores else 0,
                    'max_dependents': max(hub_scores.values()) if hub_scores else 0
                }
            }

        except Exception as e:
            logger.error(f"Error generating dependency matrix: {e}")
            return {'success': False, 'error': str(e)}

    def generate_impact_mermaid(self, table: str, measure: str) -> Dict[str, Any]:
        """
        Generate a bidirectional Mermaid diagram showing both upstream and downstream dependencies.

        Args:
            table: Table name containing the measure
            measure: Measure name

        Returns:
            Dictionary with comprehensive Mermaid diagram
        """
        try:
            # Get upstream dependencies
            upstream = self.generate_dependency_mermaid(table, measure, "upstream", depth=3)
            # Get downstream dependencies
            downstream = self.generate_dependency_mermaid(table, measure, "downstream", depth=3)

            # Combine into single diagram
            measure_key = f"{table}[{measure}]"
            all_nodes = set()
            column_nodes = set()  # Track column nodes for different styling
            upstream_edges = []
            downstream_edges = []
            visited_upstream = set()
            visited_downstream = set()

            from core.utilities.mermaid_utils import sanitize_node_id

            def sanitize_label(name: str) -> str:
                return name.replace('"', '\\"')

            # Build measure name lookup for resolving unqualified references
            from core.utilities.mermaid_utils import build_measure_name_lookup, resolve_measure_table as _resolve_impact
            measures_result = self.query_executor.execute_info_query("MEASURES")
            measure_name_to_table = build_measure_name_lookup(measures_result)
            logger.debug(f"Impact mermaid: Built lookup with {len(measure_name_to_table)} entries")

            def resolve_table(dep_tbl: str, dep_name: str) -> str:
                return _resolve_impact(dep_tbl, dep_name, measure_name_to_table, context="Impact mermaid")

            # Collect upstream (measures AND columns)
            def collect_upstream(tbl: str, msr: str, depth: int):
                if depth > 3:
                    return
                key = f"{tbl}[{msr}]"
                if key in visited_upstream:
                    return
                visited_upstream.add(key)
                all_nodes.add(key)

                deps = self.analyze_measure_dependencies(tbl, msr)
                if deps.get('success'):
                    # Add referenced measures
                    for dep_tbl, dep_name in deps.get('referenced_measures', []):
                        if dep_name:  # Only need name, table can be empty
                            effective_tbl = resolve_table(dep_tbl, dep_name)
                            dep_key = f"{effective_tbl}[{dep_name}]"
                            all_nodes.add(dep_key)
                            upstream_edges.append((dep_key, key))
                            if effective_tbl and effective_tbl != 'Unknown':  # Recurse if we have a valid table
                                collect_upstream(effective_tbl, dep_name, depth + 1)
                    # Add referenced columns (only at depth 0 to avoid clutter)
                    if depth == 0:
                        for col_tbl, col_name in deps.get('referenced_columns', []):
                            if col_tbl:
                                col_key = f"{col_tbl}[{col_name}]"
                                all_nodes.add(col_key)
                                column_nodes.add(col_key)
                                upstream_edges.append((col_key, key))

            # Collect downstream
            def collect_downstream(tbl: str, msr: str, depth: int):
                if depth > 3:
                    return
                key = f"{tbl}[{msr}]"
                if key in visited_downstream:
                    return
                visited_downstream.add(key)
                all_nodes.add(key)

                usage = self.find_measure_usage(tbl, msr)
                if usage.get('success'):
                    for dep in usage.get('used_by', []):
                        dep_tbl = dep.get('table', '')
                        dep_name = dep.get('measure', '')
                        if dep_tbl and dep_name:
                            dep_key = f"{dep_tbl}[{dep_name}]"
                            all_nodes.add(dep_key)
                            downstream_edges.append((key, dep_key))
                            collect_downstream(dep_tbl, dep_name, depth + 1)

            collect_upstream(table, measure, 0)
            collect_downstream(table, measure, 0)

            # Generate combined diagram
            lines = ["flowchart LR"]
            lines.append("    %% Impact Analysis Diagram")
            lines.append("    %% Left = Dependencies (upstream), Right = Dependents (downstream)")
            lines.append("")

            # Subgraphs for organization
            upstream_nodes = set(e[0] for e in upstream_edges) - {measure_key}
            downstream_nodes = set(e[1] for e in downstream_edges) - {measure_key}
            upstream_measures = upstream_nodes - column_nodes
            upstream_columns = upstream_nodes & column_nodes

            if upstream_nodes:
                lines.append("    subgraph Dependencies")
                lines.append("    direction TB")
                # Add measure nodes
                for node in sorted(upstream_measures):
                    node_id = sanitize_node_id(node)
                    lines.append(f'    {node_id}["{sanitize_label(node)}"]:::upstream')
                # Add column nodes with different style
                for node in sorted(upstream_columns):
                    node_id = sanitize_node_id(node)
                    lines.append(f'    {node_id}["{sanitize_label(node)}"]:::column')
                lines.append("    end")
                lines.append("")

            # Root measure
            root_id = sanitize_node_id(measure_key)
            lines.append(f'    {root_id}["{sanitize_label(measure_key)}"]:::root')
            lines.append("")

            if downstream_nodes:
                lines.append("    subgraph Dependents")
                lines.append("    direction TB")
                for node in sorted(downstream_nodes):
                    node_id = sanitize_node_id(node)
                    lines.append(f'    {node_id}["{sanitize_label(node)}"]:::downstream')
                lines.append("    end")
                lines.append("")

            # Edges
            lines.append("    %% Dependency edges (upstream)")
            for source, target in upstream_edges:
                lines.append(f"    {sanitize_node_id(source)} --> {sanitize_node_id(target)}")

            lines.append("")
            lines.append("    %% Impact edges (downstream)")
            for source, target in downstream_edges:
                lines.append(f"    {sanitize_node_id(source)} --> {sanitize_node_id(target)}")

            # Styles
            lines.append("")
            lines.append("    classDef root fill:#2196F3,stroke:#1565C0,color:#fff,stroke-width:3px")
            lines.append("    classDef upstream fill:#4CAF50,stroke:#388E3C,color:#fff")
            lines.append("    classDef downstream fill:#FF9800,stroke:#F57C00,color:#fff")
            lines.append("    classDef column fill:#9C27B0,stroke:#7B1FA2,color:#fff")

            mermaid_code = "\n".join(lines)

            # Calculate total counts
            total_edges = len(upstream_edges) + len(downstream_edges)
            total_nodes = len(all_nodes)

            # Return raw Mermaid code (no markdown fence) for API rendering
            return {
                'success': True,
                'measure': {'table': table, 'name': measure},
                'mermaid': mermaid_code,
                'upstream_count': len(upstream_nodes),
                'downstream_count': len(downstream_nodes),
                'node_count': total_nodes,
                'edge_count': total_edges,
                'format': 'mermaid_flowchart_bidirectional'
            }

        except Exception as e:
            logger.error(f"Error generating impact Mermaid diagram for {table}[{measure}]: {e}")
            return {'success': False, 'error': str(e)}
