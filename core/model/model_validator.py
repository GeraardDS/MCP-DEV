"""
Model Validator for PBIXRay MCP Server
Validates model integrity and data quality
"""

import logging
import random
from typing import Dict, Any, List, Optional
from core.config.config_manager import config
from core.execution.dmv_helper import get_field_value

logger = logging.getLogger(__name__)


class ModelValidator:
    """Validate model integrity and data quality."""

    def __init__(self, query_executor):
        """Initialize with query executor."""
        self.executor = query_executor
        self._sampling_warnings = []

    def _get_sampled_relationships(self, relationships: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply sampling to relationships list based on configuration.

        Args:
            relationships: Full list of relationships from INFO.RELATIONSHIPS()

        Returns:
            Sampled list (or full list if no limit configured)
        """
        max_items = config.get('validation.max_relationships_check', None)
        warn_on_sampling = config.get('validation.warn_on_sampling', True)

        # If no limit, return all relationships
        if max_items is None:
            return relationships

        # If limit is greater than or equal to actual count, return all
        if len(relationships) <= max_items:
            return relationships

        # Sample relationships
        sampled = random.sample(relationships, max_items)

        # Add warning about sampling
        if warn_on_sampling:
            warning_msg = f"Sampled {max_items} of {len(relationships)} relationships for validation (full validation disabled)"
            self._sampling_warnings.append(warning_msg)
            logger.warning(warning_msg)

        return sampled

    def validate_model_integrity(self) -> Dict[str, Any]:
        """
        Comprehensive model validation.

        Returns:
            Validation results with issues found
        """
        issues = []
        self._sampling_warnings = []  # Reset warnings for this validation run

        try:
            # Check 1: Relationships with missing keys
            logger.info("Checking relationships...")
            rel_issues = self._check_relationship_integrity()
            if rel_issues:
                issues.extend(rel_issues)

            # Check 2: Duplicate keys in dimension tables
            logger.info("Checking for duplicate keys...")
            dup_issues = self._check_duplicate_keys()
            if dup_issues:
                issues.extend(dup_issues)

            # Check 3: Null values in key columns
            logger.info("Checking for null keys...")
            null_issues = self._check_null_keys()
            if null_issues:
                issues.extend(null_issues)

            # Check 4: Invalid measure references
            logger.info("Checking measure references...")
            measure_issues = self._check_measure_references()
            if measure_issues:
                issues.extend(measure_issues)

            # Check 5: Circular relationships
            logger.info("Checking for circular relationships...")
            circular_issues = self._check_circular_relationships()
            if circular_issues:
                issues.extend(circular_issues)

            # Categorize by severity
            critical = [i for i in issues if i['severity'] == 'critical']
            high = [i for i in issues if i['severity'] == 'high']
            medium = [i for i in issues if i['severity'] == 'medium']
            low = [i for i in issues if i['severity'] == 'low']

            is_valid = len(critical) == 0 and len(high) == 0

            result = {
                'success': True,
                'is_valid': is_valid,
                'total_issues': len(issues),
                'issues': issues,
                'summary': {
                    'critical_issues': len(critical),
                    'high_issues': len(high),
                    'medium_issues': len(medium),
                    'low_issues': len(low)
                },
                'recommendation': 'Fix critical and high issues before deploying' if not is_valid else 'Model passed validation'
            }

            # Include sampling warnings if any
            if self._sampling_warnings:
                result['warnings'] = self._sampling_warnings
                result['validation_scope'] = 'sampled'
            else:
                result['validation_scope'] = 'full'

            return result

        except Exception as e:
            logger.error(f"Validation error: {e}")
            return {'success': False, 'error': str(e)}

    def _check_relationship_integrity(self) -> List[Dict[str, Any]]:
        """Check for orphaned records in relationships."""
        issues = []

        try:
            rels_result = self.executor.execute_info_query("RELATIONSHIPS", top_n=5000)
            if not rels_result.get('success'):
                return issues

            # Apply sampling based on configuration (default: unlimited)
            relationships = self._get_sampled_relationships(rels_result['rows'])

            for rel in relationships:
                from_table = get_field_value(rel, ['FromTable'])
                from_col = get_field_value(rel, ['FromColumn'])
                to_table = get_field_value(rel, ['ToTable'])
                to_col = get_field_value(rel, ['ToColumn'])
                if not from_table or not from_col or not to_table or not to_col:
                    # Skip incomplete rows
                    continue

                # Check for orphaned records
                query = f"""
                EVALUATE
                ROW(
                    "OrphanedRecords",
                    COUNTROWS(
                        FILTER(
                            '{from_table}',
                            ISBLANK(RELATED('{to_table}'[{to_col}]))
                        )
                    )
                )
                """

                result = self.executor.validate_and_execute_dax(query)
                if result.get('success') and result.get('rows'):
                    orphaned = result['rows'][0].get('OrphanedRecords', 0)
                    if orphaned > 0:
                        issues.append({
                            'type': 'orphaned_records',
                            'severity': 'high',
                            'relationship': f"{from_table}[{from_col}] -> {to_table}[{to_col}]",
                            'description': f"{orphaned} orphaned records in {from_table}",
                            'recommendation': f"Add records to {to_table} or filter out orphaned records"
                        })

        except Exception as e:
            logger.warning(f"Error checking relationship integrity: {e}")

        return issues

    def _check_duplicate_keys(self) -> List[Dict[str, Any]]:
        """Check for duplicate keys in dimension tables."""
        issues = []

        try:
            # Get relationships to identify dimension tables
            rels_result = self.executor.execute_info_query("RELATIONSHIPS", top_n=5000)
            if not rels_result.get('success'):
                return issues

            # Apply sampling based on configuration (default: unlimited)
            relationships = self._get_sampled_relationships(rels_result['rows'])

            # Check "to" side of relationships (dimension side)
            checked_tables = set()

            for rel in relationships:
                to_table = get_field_value(rel, ['ToTable'])
                to_col = get_field_value(rel, ['ToColumn'])
                if not to_table or not to_col:
                    continue

                table_col = f"{to_table}[{to_col}]"
                if table_col in checked_tables:
                    continue

                checked_tables.add(table_col)

                # Check for duplicates
                query = f"""
                EVALUATE
                ROW(
                    "TotalRows", COUNTROWS('{to_table}'),
                    "UniqueKeys", DISTINCTCOUNT('{to_table}'[{to_col}])
                )
                """

                result = self.executor.validate_and_execute_dax(query)
                if result.get('success') and result.get('rows'):
                    row = result['rows'][0]
                    total = row.get('TotalRows', 0)
                    unique = row.get('UniqueKeys', 0)

                    if total != unique and total > 0:
                        issues.append({
                            'type': 'duplicate_keys',
                            'severity': 'critical',
                            'table': to_table,
                            'column': to_col,
                            'description': f"Duplicate keys found in {to_table}[{to_col}]",
                            'duplicate_count': total - unique,
                            'recommendation': f"Remove duplicates from {to_table} or use SUMMARIZE to create unique keys"
                        })

        except Exception as e:
            logger.warning(f"Error checking duplicate keys: {e}")

        return issues

    def _check_null_keys(self) -> List[Dict[str, Any]]:
        """Check for null values in key columns."""
        issues = []

        try:
            rels_result = self.executor.execute_info_query("RELATIONSHIPS", top_n=5000)
            if not rels_result.get('success'):
                return issues

            # Apply sampling based on configuration (default: unlimited)
            relationships = self._get_sampled_relationships(rels_result['rows'])

            checked = set()

            for rel in relationships:
                # Check both sides
                for side in ['From', 'To']:
                    table = get_field_value(rel, [f'{side}Table'])
                    col = get_field_value(rel, [f'{side}Column'])
                    if not table or not col:
                        continue

                    table_col = f"{table}[{col}]"
                    if table_col in checked:
                        continue

                    checked.add(table_col)

                    query = f"""
                    EVALUATE
                    ROW("NullCount", COUNTBLANK('{table}'[{col}]))
                    """

                    result = self.executor.validate_and_execute_dax(query)
                    if result.get('success') and result.get('rows'):
                        null_count = result['rows'][0].get('NullCount', 0)
                        if null_count > 0:
                            issues.append({
                                'type': 'null_keys',
                                'severity': 'high',
                                'table': table,
                                'column': col,
                                'description': f"{null_count} null values in key column {table}[{col}]",
                                'recommendation': f"Replace null values in {table}[{col}] with valid keys or 'Unknown'"
                            })

        except Exception as e:
            logger.warning(f"Error checking null keys: {e}")

        return issues

    def _check_measure_references(self) -> List[Dict[str, Any]]:
        """Check for invalid measure references using basic bracket-reference extraction."""
        import re
        issues = []

        try:
            measures_result = self.executor.execute_info_query("MEASURES", top_n=5000)
            if not measures_result.get('success'):
                return issues

            # Build set of all known measure names
            measure_names = set()
            for m in measures_result['rows']:
                name = m.get('Name')
                if name:
                    measure_names.add(name)

            # Also get column names to exclude from measure-ref checks
            columns_result = self.executor.execute_info_query("COLUMNS", top_n=5000)
            column_names = set()
            if columns_result.get('success'):
                for c in columns_result['rows']:
                    col_name = c.get('Name') or c.get('[ExplicitName]')
                    if col_name:
                        column_names.add(col_name)

            # Pattern: standalone [Name] references (not preceded by table name or ')
            # This is a heuristic — a full DAX parser would be more accurate
            bracket_ref_pattern = re.compile(r'(?<![\'"\w])\[([^\]]+)\]')

            for measure in measures_result['rows']:
                expr = measure.get('Expression', '')
                if not expr:
                    continue

                measure_name = measure.get('Name', '')
                table_name = measure.get('TableName', '') or measure.get('[TableID]', '')

                # Extract bracket references from the expression
                refs = bracket_ref_pattern.findall(expr)
                for ref in refs:
                    # Skip known columns, the measure itself, and common DAX keywords
                    if ref in column_names or ref == measure_name:
                        continue
                    if ref.upper() in ('VALUE', 'VALUES', 'ROWS', 'COLUMNS'):
                        continue

                    # If ref looks like a measure name but isn't in our set, flag it
                    if ref not in measure_names and not ref.startswith('$'):
                        issues.append({
                            'type': 'invalid_measure_reference',
                            'severity': 'medium',
                            'table': table_name,
                            'measure': measure_name,
                            'reference': ref,
                            'description': f"Measure '{measure_name}' references unknown '[{ref}]' — may be a renamed or deleted measure",
                            'recommendation': f"Verify that '[{ref}]' exists in the model or update the reference"
                        })

        except Exception as e:
            logger.warning(f"Error checking measure references: {e}")

        return issues

    def _check_circular_relationships(self) -> List[Dict[str, Any]]:
        """Check for circular relationship chains."""
        issues = []

        try:
            rels_result = self.executor.execute_info_query("RELATIONSHIPS", top_n=5000)
            if not rels_result.get('success'):
                return issues

            # Build relationship graph
            graph = {}
            for rel in rels_result['rows']:
                from_table = rel.get('FromTable')
                to_table = rel.get('ToTable')

                if from_table not in graph:
                    graph[from_table] = []
                graph[from_table].append(to_table)

            # Check for cycles using DFS
            def has_cycle(node, visited, rec_stack):
                visited.add(node)
                rec_stack.add(node)

                if node in graph:
                    for neighbor in graph[node]:
                        if neighbor not in visited:
                            if has_cycle(neighbor, visited, rec_stack):
                                return True
                        elif neighbor in rec_stack:
                            return True

                rec_stack.remove(node)
                return False

            visited = set()
            for node in graph:
                if node not in visited:
                    if has_cycle(node, visited, set()):
                        issues.append({
                            'type': 'circular_relationship',
                            'severity': 'critical',
                            'description': 'Circular relationship chain detected',
                            'recommendation': 'Review relationship directions and remove circular chains'
                        })
                        break  # Only report once

        except Exception as e:
            logger.warning(f"Error checking circular relationships: {e}")

        return issues

    def validate_model(self) -> Dict[str, Any]:
        """
        Alias for validate_model_integrity for backward compatibility.

        Returns:
            Validation results with issues found
        """
        return self.validate_model_integrity()

    def analyze_data_freshness(self) -> Dict[str, Any]:
        """Check data refresh status."""
        try:
            # Attempt 1: Desktop-incompatible DMV may fail; try TMSCHEMA partitions first
            attempts = []
            query_tmschema = '''EVALUATE
            SELECTCOLUMNS(
                TOPN(999999, $SYSTEM.TMSCHEMA_TABLES),
                "Table", [Name],
                "LastRefresh", [ModifiedTime]
            )'''
            result = self.executor.validate_and_execute_dax(query_tmschema)
            attempts.append(('TMSCHEMA_TABLES', result.get('success')))
            if not result.get('success'):
                # Attempt 2: Legacy DISCOVER_STORAGE_TABLES (may fail on Desktop)
                query = '''EVALUATE
                SELECTCOLUMNS(
                    FILTER(
                        TOPN(999999, $SYSTEM.DISCOVER_STORAGE_TABLES),
                        [TABLE_TYPE] = "TABLE"
                    ),
                    "Table", [DIMENSION_NAME],
                    "LastRefresh", [LAST_DATA_UPDATE]
                )'''
                result = self.executor.validate_and_execute_dax(query)
                attempts.append(('DISCOVER_STORAGE_TABLES', result.get('success')))
            if not result.get('success'):
                # Attempt 3: TOM fallback - partitions LastProcessed
                try:
                    result = self.executor.get_partition_freshness_tom()
                    attempts.append(('TOM', result.get('success')))
                except Exception as _e:
                    result = {'success': False, 'error': str(_e)}

            if result.get('success'):
                rows = result.get('rows', []) or result.get('tables', [])
                return {
                    'success': True,
                    'tables': rows,
                    'attempts': attempts
                }
            else:
                result.setdefault('attempts', attempts)
                return result

        except Exception as e:
            logger.error(f"Error analyzing data freshness: {e}")
            return {'success': False, 'error': str(e)}
