"""
Performance Optimizer for PBIXRay MCP Server
Analyzes cardinality, encoding, and provides optimization recommendations
"""

import logging
from typing import Dict, Any, List, Optional
from core.execution.dmv_helper import get_field_value
from core.utilities.type_conversions import safe_int, safe_bool

logger = logging.getLogger(__name__)


class PerformanceOptimizer:
    """Analyze model performance and provide optimization recommendations."""

    def __init__(self, query_executor):
        """Initialize with query executor."""
        self.executor = query_executor

    def analyze_relationship_cardinality(self) -> Dict[str, Any]:
        """Analyze actual vs configured relationship cardinality."""
        try:
            # Helpers for robust DMV field access and ID->name mapping
            def _build_maps():
                tables_map = {}
                cols_map = {}
                # Tables
                t_res = self.executor.execute_info_query("TABLES", top_n=5000)
                if t_res.get('success'):
                    for tr in t_res.get('rows', []):
                        tid = get_field_value(tr, ['ID', 'TableID'])
                        name = get_field_value(tr, ['Name', 'Table'])
                        try:
                            if tid is not None and name:
                                tables_map[int(str(tid))] = str(name)
                        except Exception:
                            pass
                # Columns
                c_res = self.executor.execute_info_query("COLUMNS", top_n=5000)
                if c_res.get('success'):
                    for cr in c_res.get('rows', []):
                        cid = get_field_value(cr, ['ID', 'ColumnID'])
                        cname = get_field_value(cr, ['Name'])
                        try:
                            if cid is not None and cname:
                                cols_map[int(str(cid))] = str(cname)
                        except Exception:
                            pass
                return tables_map, cols_map

            tables_by_id, columns_by_id = _build_maps()

            # Get all relationships
            rels_result = self.executor.execute_info_query("RELATIONSHIPS", top_n=5000)
            if not rels_result.get('success'):
                return {'success': False, 'error': 'Failed to get relationships'}

            relationships = rels_result['rows']
            issues = []

            for rel in relationships:
                # Prefer name fields; if missing, resolve from IDs
                from_table = get_field_value(rel, ['FromTable'])
                to_table = get_field_value(rel, ['ToTable'])
                from_col = get_field_value(rel, ['FromColumn'])
                to_col = get_field_value(rel, ['ToColumn'])
                if not from_table:
                    ftid = get_field_value(rel, ['FromTableID'])
                    try:
                        from_table = tables_by_id.get(int(str(ftid))) if ftid is not None else None
                    except Exception:
                        from_table = None
                if not to_table:
                    ttid = get_field_value(rel, ['ToTableID'])
                    try:
                        to_table = tables_by_id.get(int(str(ttid))) if ttid is not None else None
                    except Exception:
                        to_table = None
                if not from_col:
                    fcid = get_field_value(rel, ['FromColumnID'])
                    try:
                        from_col = columns_by_id.get(int(str(fcid))) if fcid is not None else None
                    except Exception:
                        from_col = None
                if not to_col:
                    tcid = get_field_value(rel, ['ToColumnID'])
                    try:
                        to_col = columns_by_id.get(int(str(tcid))) if tcid is not None else None
                    except Exception:
                        to_col = None

                configured_card = str(get_field_value(rel, ['Cardinality']) or 'Unknown')

                # Skip incomplete rows to avoid 'None' table references
                if not to_table or not to_col or not from_table or not from_col:
                    continue

                # Query to check for duplicates in "one" side
                if 'One' in configured_card:
                    # Check to-side (should be unique)
                    # Quote identifiers defensively for tables/columns that contain special chars
                    def _qt(s: str) -> str:
                        return "'" + str(s).replace("'", "''") + "'"
                    def _qc(c: str) -> str:
                        return "[" + str(c).replace("]", "]]" ) + "]"
                    check_query = (
                        "EVALUATE\nROW(\"TotalRows\", COUNTROWS(" + _qt(to_table) + "), "
                        "\"UniqueValues\", DISTINCTCOUNT(" + _qt(to_table) + _qc(to_col) + "))"
                    )

                    result = self.executor.validate_and_execute_dax(check_query)
                    if result.get('success') and result.get('rows'):
                        row = result['rows'][0]
                        total = safe_int(row.get('TotalRows', 0))
                        unique = safe_int(row.get('UniqueValues', 0))

                        if total > 0 and total != unique:
                            duplicate_count = total - unique
                            issues.append({
                                'relationship': f"{from_table}[{from_col}] -> {to_table}[{to_col}]",
                                'configured_cardinality': configured_card,
                                'issue': 'Duplicate keys in one-side',
                                'details': f"{to_table}[{to_col}] has {duplicate_count} duplicate values",
                                'severity': 'high',
                                'recommendation': f"Remove duplicates from {to_table}[{to_col}] or change relationship to Many-to-Many",
                                'total_rows': total,
                                'unique_values': unique
                            })

            return {
                'success': True,
                'relationships_analyzed': len(relationships),
                'issues_found': len(issues),
                'issues': issues,
                'summary': {
                    'healthy_relationships': len(relationships) - len(issues),
                    'relationships_with_issues': len(issues)
                }
            }

        except Exception as e:
            logger.error(f"Error analyzing cardinality: {e}")
            return {'success': False, 'error': str(e)}

    def analyze_column_cardinality(self, table: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze column cardinality and provide recommendations.

        Args:
            table: Optional table name to limit analysis

        Returns:
            Cardinality analysis with recommendations
        """
        try:
            # Build table and column ID maps
            tables_by_id = {}
            t_res = self.executor.execute_info_query("TABLES", top_n=5000)
            if t_res.get('success'):
                for tr in t_res.get('rows', []):
                    tid = get_field_value(tr, ['ID', 'TableID'])
                    tname = get_field_value(tr, ['Name', 'Table'])
                    try:
                        if tid is not None and tname:
                            tables_by_id[int(str(tid))] = str(tname)
                    except Exception:
                        pass

            # Get columns
            cols_result = self.executor.execute_info_query("COLUMNS", table_name=table)
            # Desktop variants occasionally fail on table-scoped DMV; fallback to all-cols and filter
            if not cols_result.get('success'):
                all_cols = self.executor.execute_info_query("COLUMNS", top_n=5000)
                if all_cols.get('success'):
                    def _norm(s: Optional[str]) -> str:
                        if not s:
                            return ""
                        s = str(s)
                        if s.startswith('[') and s.endswith(']'):
                            s = s[1:-1]
                        if s.startswith('"') and s.endswith('"'):
                            s = s[1:-1]
                        return s
                    t_norm = _norm(table)
                    rows = []
                    for r in all_cols.get('rows', []) or []:
                        rt = _norm(r.get('Table') or r.get('TableName') or r.get('TABLE_NAME'))
                        if rt == t_norm:
                            rows.append(r)
                    cols_result = {'success': True, 'rows': rows, 'row_count': len(rows)}
                else:
                    return {'success': False, 'error': 'Failed to get columns'}

            columns = cols_result['rows']
            analysis = []

            # Analyze up to 20 columns to avoid long execution
            for col in columns[:20]:
                col_table = get_field_value(col, ['Table', 'TableName', 'TABLE_NAME'])
                # Prefer explicit/inferred names when standard Name is absent
                col_name = get_field_value(col, ['Name', 'ExplicitName', 'InferredName', 'COLUMN_NAME'])
                if not col_table:
                    tid = get_field_value(col, ['TableID'])
                    try:
                        col_table = tables_by_id.get(int(str(tid))) if tid is not None else None
                    except Exception:
                        col_table = None
                if not col_table or not col_name:
                    # Skip incomplete rows to avoid queries like 'None'[col]
                    continue
                data_type = col.get('DataType', 'Unknown')

                # Skip hidden columns
                hidden_val = col.get('IsHidden') or col.get('[IsHidden]') or col.get('HIDDEN') or col.get('[HIDDEN]')
                if isinstance(hidden_val, str):
                    hidden = hidden_val.strip().lower() == 'true'
                else:
                    hidden = bool(hidden_val)
                if hidden:
                    continue

                # Query cardinality
                # Defensive quoting for identifiers
                def _qt(s: str) -> str:
                    return "'" + str(s).replace("'", "''") + "'"
                def _qc(c: str) -> str:
                    return "[" + str(c).replace("]", "]]" ) + "]"
                card_query = (
                    "EVALUATE\nROW("
                    "\"RowCount\", COUNTROWS(" + _qt(col_table) + "), "
                    "\"DistinctCount\", DISTINCTCOUNT(" + _qt(col_table) + _qc(col_name) + "), "
                    "\"NullCount\", COUNTBLANK(" + _qt(col_table) + _qc(col_name) + ")"
                    ")"
                )

                result = self.executor.validate_and_execute_dax(card_query)
                if result.get('success') and result.get('rows'):
                    row = result['rows'][0]
                    row_count = safe_int(row.get('RowCount', 0))
                    distinct_count = safe_int(row.get('DistinctCount', 0))
                    null_count = safe_int(row.get('NullCount', 0))

                    # Calculate metrics
                    cardinality_ratio = distinct_count / row_count if row_count > 0 else 0

                    # Determine cardinality level
                    if cardinality_ratio > 0.95:
                        cardinality_level = 'very_high'
                        recommendation = f"Very high cardinality ({distinct_count:,} unique values). Consider removing if not needed for analysis."
                        severity = 'high'
                    elif cardinality_ratio > 0.50:
                        cardinality_level = 'high'
                        recommendation = f"High cardinality ({distinct_count:,} unique values). May impact performance and memory."
                        severity = 'medium'
                    elif cardinality_ratio < 0.01 and row_count > 100:
                        cardinality_level = 'very_low'
                        recommendation = f"Very low cardinality ({distinct_count} unique values). Good for compression."
                        severity = 'low'
                    else:
                        cardinality_level = 'normal'
                        recommendation = "Cardinality is acceptable."
                        severity = 'low'

                    analysis.append({
                        'table': col_table,
                        'column': col_name,
                        'data_type': data_type,
                        'row_count': row_count,
                        'distinct_count': distinct_count,
                        'null_count': null_count,
                        'cardinality_ratio': round(cardinality_ratio, 4),
                        'cardinality_level': cardinality_level,
                        'severity': severity,
                        'recommendation': recommendation
                    })

            # Sort by severity
            analysis.sort(key=lambda x: {'high': 0, 'medium': 1, 'low': 2}.get(x['severity'], 3))

            return {
                'success': True,
                'columns_analyzed': len(analysis),
                'analysis': analysis,
                'summary': {
                    'high_severity': len([a for a in analysis if a['severity'] == 'high']),
                    'medium_severity': len([a for a in analysis if a['severity'] == 'medium']),
                    'low_severity': len([a for a in analysis if a['severity'] == 'low'])
                }
            }

        except Exception as e:
            logger.error(f"Error analyzing column cardinality: {e}")
            return {'success': False, 'error': str(e)}

    def analyze_encoding_efficiency(self, table: str) -> Dict[str, Any]:
        """
        Analyze VertiPaq encoding efficiency for a table.

        Args:
            table: Table name to analyze

        Returns:
            Encoding analysis with recommendations
        """
        try:
            # Query full VertiPaq storage info and filter client-side for maximum compatibility
            all_vp = self.executor.validate_and_execute_dax("EVALUATE INFO.STORAGETABLECOLUMNS()")
            if not all_vp.get('success'):
                return {'success': False, 'error': 'Failed to query VertiPaq stats'}

            target = str(table)
            def _row_matches(r: Dict[str, Any]) -> bool:
                keys = (
                    'TABLE_FULL_NAME', 'TABLE_ID', 'TABLE_NAME', 'Table', 'TABLE', 'Name'
                )
                for k in keys:
                    if k in r and r[k] is not None:
                        sv = str(r[k])
                        if sv == target or target in sv:
                            return True
                return False

            rows = [r for r in (all_vp.get('rows') or []) if isinstance(r, dict) and _row_matches(r)]
            if not rows:
                # Fallback: compute lightweight per-column metrics without true dictionary sizes
                # This provides actionable guidance even when VertiPaq DMV isn't available
                cols_result = self.executor.execute_info_query("COLUMNS", table_name=table)
                if not cols_result.get('success'):
                    # last-chance: all columns then filter by table name
                    all_cols = self.executor.execute_info_query("COLUMNS", top_n=5000)
                    if all_cols.get('success'):
                        trows = [r for r in all_cols.get('rows', []) if str(r.get('Table') or r.get('TableName')) == str(table)]
                        cols_result = {'success': True, 'rows': trows}
                analysis = []
                total_cardinality = 0
                if cols_result.get('success'):
                    for col in (cols_result.get('rows') or [])[:20]:
                        col_table = str(col.get('Table') or table)
                        col_name = str(col.get('Name'))
                        # Skip hidden columns to avoid noise
                        if col.get('IsHidden'):
                            continue
                        # Quoted identifiers
                        qt = "'" + col_table.replace("'", "''") + "'"
                        qc = "[" + col_name.replace("]", "]]" ) + "]"
                        q = (
                            "EVALUATE ROW(\"DistinctCount\", DISTINCTCOUNT(" + qt + qc + "), "
                            "\"NullCount\", COUNTBLANK(" + qt + qc + "))"
                        )
                        r = self.executor.validate_and_execute_dax(q)
                        if r.get('success') and r.get('rows'):
                            distinct = safe_int(r['rows'][0].get('DistinctCount', 0))
                            nulls = safe_int(r['rows'][0].get('NullCount', 0))
                            total_cardinality += distinct
                            analysis.append({
                                'column': col_name,
                                'cardinality': distinct,
                                'null_count': nulls,
                                'dictionary_size_bytes': None,
                                'dictionary_size_mb': None,
                                'severity': 'info',
                                'recommendation': 'VertiPaq DMV unavailable; estimated via DISTINCTCOUNT/COUNTBLANK.'
                            })
                return {
                    'success': True,
                    'table': table,
                    'columns_analyzed': len(analysis),
                    'total_size_mb': None,
                    'total_cardinality': total_cardinality,
                    'analysis': analysis,
                    'notes': ['VertiPaq DMV returned no rows; used fallback estimation']
                }

            analysis = []
            total_size = 0
            total_cardinality = 0

            for row in rows:
                column = row.get('COLUMN_ID') or row.get('COLUMN_NAME') or row.get('Column') or 'Unknown'
                data_size = safe_int(row.get('DICTIONARY_SIZE') or row.get('DICTIONARY_SIZE_BYTES') or row.get('DictionarySize') or 0)
                cardinality = safe_int(row.get('DICTIONARY_COUNT') or row.get('Cardinality') or 0)

                total_size += data_size
                total_cardinality += cardinality

                # Estimate encoding efficiency
                if cardinality > 0:
                    avg_bytes_per_value = data_size / cardinality
                else:
                    avg_bytes_per_value = 0

                # Recommendations based on size and cardinality
                if data_size > 10_000_000:  # > 10MB
                    severity = 'high'
                    recommendation = f"Large dictionary size ({data_size/1_000_000:.1f}MB). Consider reducing cardinality or removing if not needed."
                elif cardinality > 1_000_000:
                    severity = 'medium'
                    recommendation = f"High cardinality ({cardinality:,} values). May benefit from binning or aggregation."
                else:
                    severity = 'low'
                    recommendation = "Encoding efficiency is acceptable."

                analysis.append({
                    'column': column,
                    'dictionary_size_bytes': data_size,
                    'dictionary_size_mb': round(data_size / 1_000_000, 2),
                    'cardinality': cardinality,
                    'avg_bytes_per_value': round(avg_bytes_per_value, 2),
                    'severity': severity,
                    'recommendation': recommendation
                })

            # Sort by size
            analysis.sort(key=lambda x: x['dictionary_size_bytes'], reverse=True)

            return {
                'success': True,
                'table': table,
                'columns_analyzed': len(analysis),
                'total_size_mb': round(total_size / 1_000_000, 2),
                'total_cardinality': total_cardinality,
                'analysis': analysis[:20],  # Top 20 columns
                'summary': {
                    'largest_column': analysis[0]['column'] if analysis else None,
                    'largest_column_size_mb': analysis[0]['dictionary_size_mb'] if analysis else 0
                }
            }

        except Exception as e:
            logger.error(f"Error analyzing encoding: {e}")
            return {'success': False, 'error': str(e)}

