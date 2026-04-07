"""
Model Diff Engine

Compares two Power BI models (parsed from TMDL) and identifies all differences
including schema changes, measure modifications, and relationship updates.
"""

import logging
import difflib
from typing import Dict, Any, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class ModelDiffer:
    """
    Compares two Power BI models and identifies differences.

    Performs deep comparison of tables, columns, measures, relationships,
    and other model components to generate comprehensive diff reports.
    """

    def __init__(self, model1: Dict[str, Any], model2: Dict[str, Any]):
        """
        Initialize model differ.

        Args:
            model1: First model (parsed TMDL structure)
            model2: Second model (parsed TMDL structure)
        """
        self.model1 = model1
        self.model2 = model2
        self.diff_result = None

    def compare(self) -> Dict[str, Any]:
        """
        Perform complete model comparison.

        Returns:
            Comprehensive diff dictionary with all changes categorized
        """
        logger.info("Starting model comparison")

        tables_diff = self._compare_tables()

        self.diff_result = {
            "summary": {
                "model1_name": self._get_model_name(self.model1),
                "model2_name": self._get_model_name(self.model2),
                "total_changes": 0,
                "changes_by_category": {}
            },
            "tables": tables_diff,
            "measures": self._extract_all_measures(tables_diff),
            "relationships": self._compare_relationships(),
            "roles": self._compare_roles(),
            "perspectives": self._compare_perspectives(),
            "model_properties": self._compare_model_properties()
        }

        # Calculate totals
        self._calculate_summary()

        logger.info(
            f"Comparison complete: {self.diff_result['summary']['total_changes']} total changes"
        )

        return self.diff_result

    def _get_model_name(self, model: Dict[str, Any]) -> str:
        """Extract model name from parsed model."""
        # Try different model structure formats
        # First try model.tmdl name (most descriptive)
        if model.get('model') and model['model'].get('name'):
            model_name = model['model']['name']
            # If it's a UUID, try database name instead
            if not self._is_uuid(model_name):
                return model_name

        # Try database.tmdl name
        if model.get('database') and model['database'].get('name'):
            db_name = model['database']['name']
            # If it's not a UUID, use it
            if not self._is_uuid(db_name):
                return db_name

        # Fallback: use any available name even if it's a UUID
        if model.get('model') and model['model'].get('name'):
            return model['model']['name']
        if model.get('database') and model['database'].get('name'):
            return model['database']['name']

        return "Unknown Model"

    def _is_uuid(self, value: str) -> bool:
        """Check if a string looks like a UUID."""
        import re
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        return bool(re.match(uuid_pattern, value, re.IGNORECASE))

    def _compare_tables(self) -> Dict[str, Any]:
        """Compare tables between models."""
        logger.debug("Comparing tables")

        tables1 = {t['name']: t for t in self.model1.get('tables', [])}
        tables2 = {t['name']: t for t in self.model2.get('tables', [])}

        tables1_names = set(tables1.keys())
        tables2_names = set(tables2.keys())

        result = {
            "added": [],
            "removed": [],
            "modified": [],
            "unchanged": []
        }

        # Tables added in model2
        for table_name in tables2_names - tables1_names:
            table = tables2[table_name]
            result['added'].append({
                "name": table_name,
                "columns_count": len(table.get('columns', [])),
                "measures_count": len(table.get('measures', [])),
                "is_calculation_group": table.get('is_calculation_group', False)
            })

        # Tables removed from model2
        for table_name in tables1_names - tables2_names:
            table = tables1[table_name]
            result['removed'].append({
                "name": table_name,
                "columns_count": len(table.get('columns', [])),
                "measures_count": len(table.get('measures', []))
            })

        # Tables present in both - check for modifications
        for table_name in tables1_names & tables2_names:
            table1 = tables1[table_name]
            table2 = tables2[table_name]

            table_diff = self._compare_table_details(table1, table2)

            if table_diff['has_changes']:
                result['modified'].append({
                    "name": table_name,
                    "changes": table_diff
                })
            else:
                result['unchanged'].append(table_name)

        logger.debug(
            f"Tables: {len(result['added'])} added, "
            f"{len(result['removed'])} removed, "
            f"{len(result['modified'])} modified"
        )

        return result

    def _compare_table_details(
        self,
        table1: Dict[str, Any],
        table2: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Compare details of a single table.

        Returns:
            Dictionary with column, measure, and hierarchy changes
        """
        result = {
            "has_changes": False,
            "columns": self._compare_columns(
                table1.get('columns', []),
                table2.get('columns', [])
            ),
            "measures": self._compare_measures(
                table1.get('measures', []),
                table2.get('measures', [])
            ),
            "hierarchies": self._compare_hierarchies(
                table1.get('hierarchies', []),
                table2.get('hierarchies', [])
            ),
            "partitions": self._compare_partitions(
                table1.get('partitions', []),
                table2.get('partitions', [])
            )
        }

        # Check if calculation group status changed
        if table1.get('is_calculation_group') != table2.get('is_calculation_group'):
            result['calculation_group_changed'] = {
                "from": table1.get('is_calculation_group', False),
                "to": table2.get('is_calculation_group', False)
            }
            result['has_changes'] = True

        # Check table metadata changes
        table_metadata_fields = ['description', 'is_hidden']
        for field in table_metadata_fields:
            if table1.get(field) != table2.get(field):
                result[f'{field}_changed'] = {
                    "from": table1.get(field),
                    "to": table2.get(field)
                }
                result['has_changes'] = True

        # Check annotations
        annot_changes = self._compare_annotations(
            table1.get('annotations', []),
            table2.get('annotations', [])
        )
        if annot_changes:
            result['annotations'] = annot_changes
            result['has_changes'] = True

        # Check calculation items (for calculation groups)
        if table1.get('is_calculation_group') or table2.get('is_calculation_group'):
            calc_items_diff = self._compare_calculation_items(
                table1.get('calculation_items', []),
                table2.get('calculation_items', [])
            )
            if calc_items_diff['added'] or calc_items_diff['removed'] or calc_items_diff['modified']:
                result['calculation_items'] = calc_items_diff
                result['has_changes'] = True

        # Check if there are any changes in sub-components
        if (result['columns']['added'] or result['columns']['removed'] or result['columns']['modified'] or
            result['measures']['added'] or result['measures']['removed'] or result['measures']['modified'] or
            result['hierarchies']['added'] or result['hierarchies']['removed'] or result['hierarchies']['modified'] or
            result['partitions']['added'] or result['partitions']['removed'] or result['partitions']['modified']):
            result['has_changes'] = True

        return result

    def _compare_columns(
        self,
        columns1: List[Dict[str, Any]],
        columns2: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Compare columns within a table."""
        cols1 = {c['name']: c for c in columns1}
        cols2 = {c['name']: c for c in columns2}

        cols1_names = set(cols1.keys())
        cols2_names = set(cols2.keys())

        result = {
            "added": [],
            "removed": [],
            "modified": []
        }

        # Added columns
        for col_name in cols2_names - cols1_names:
            col = cols2[col_name]
            result['added'].append({
                "name": col_name,
                "data_type": col.get('data_type'),
                "is_calculated": col.get('is_calculated', False),
                "expression": col.get('expression')
            })

        # Removed columns
        for col_name in cols1_names - cols2_names:
            col = cols1[col_name]
            result['removed'].append({
                "name": col_name,
                "data_type": col.get('data_type'),
                "is_calculated": col.get('is_calculated', False)
            })

        # Modified columns
        for col_name in cols1_names & cols2_names:
            col1 = cols1[col_name]
            col2 = cols2[col_name]

            changes = {}

            # Check data type change
            if col1.get('data_type') != col2.get('data_type'):
                changes['data_type'] = {
                    "from": col1.get('data_type'),
                    "to": col2.get('data_type')
                }

            # Check if column became calculated or vice versa
            if col1.get('is_calculated') != col2.get('is_calculated'):
                changes['is_calculated'] = {
                    "from": col1.get('is_calculated', False),
                    "to": col2.get('is_calculated', False)
                }

            # Check expression changes for calculated columns
            if col1.get('expression') != col2.get('expression'):
                expr1 = col1.get('expression') or ""
                expr2 = col2.get('expression') or ""

                if expr1 or expr2:
                    changes['expression'] = {
                        "from": expr1,
                        "to": expr2,
                        "diff": self._generate_text_diff(expr1, expr2)
                    }

            # Check metadata changes
            metadata_fields = [
                'description', 'display_folder', 'format_string', 'data_category',
                'summarize_by', 'sort_by_column', 'is_key', 'is_hidden'
            ]
            for field in metadata_fields:
                if col1.get(field) != col2.get(field):
                    changes[field] = {
                        "from": col1.get(field),
                        "to": col2.get(field)
                    }

            # Check annotations changes
            annot_changes = self._compare_annotations(
                col1.get('annotations', []),
                col2.get('annotations', [])
            )
            if annot_changes:
                changes['annotations'] = annot_changes

            # Check property changes
            prop_changes = self._compare_properties(
                col1.get('properties', {}),
                col2.get('properties', {})
            )
            if prop_changes:
                changes['properties'] = prop_changes

            if changes:
                result['modified'].append({
                    "name": col_name,
                    "changes": changes
                })

        return result

    def _compare_measures(
        self,
        measures1: List[Dict[str, Any]],
        measures2: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Compare measures within a table."""
        meas1 = {m['name']: m for m in measures1}
        meas2 = {m['name']: m for m in measures2}

        meas1_names = set(meas1.keys())
        meas2_names = set(meas2.keys())

        result = {
            "added": [],
            "removed": [],
            "modified": []
        }

        # Added measures
        for meas_name in meas2_names - meas1_names:
            meas = meas2[meas_name]
            result['added'].append({
                "name": meas_name,
                "expression": meas.get('expression'),
                "format_string": meas.get('format_string'),
                "display_folder": meas.get('display_folder')
            })

        # Removed measures
        for meas_name in meas1_names - meas2_names:
            meas = meas1[meas_name]
            result['removed'].append({
                "name": meas_name,
                "expression": meas.get('expression'),
                "format_string": meas.get('format_string')
            })

        # Modified measures
        for meas_name in meas1_names & meas2_names:
            meas1_data = meas1[meas_name]
            meas2_data = meas2[meas_name]

            changes = {}

            # Check expression changes (most important)
            expr1 = meas1_data.get('expression') or ""
            expr2 = meas2_data.get('expression') or ""

            if self._normalize_dax(expr1) != self._normalize_dax(expr2):
                changes['expression'] = {
                    "from": expr1,
                    "to": expr2,
                    "diff": self._generate_text_diff(expr1, expr2),
                    "impact": "high"  # Expression changes are always high impact
                }

            # Check format string changes
            if meas1_data.get('format_string') != meas2_data.get('format_string'):
                changes['format_string'] = {
                    "from": meas1_data.get('format_string'),
                    "to": meas2_data.get('format_string')
                }

            # Check display folder changes
            if meas1_data.get('display_folder') != meas2_data.get('display_folder'):
                changes['display_folder'] = {
                    "from": meas1_data.get('display_folder'),
                    "to": meas2_data.get('display_folder')
                }

            # Check metadata changes
            metadata_fields = ['description', 'is_hidden', 'data_category']
            for field in metadata_fields:
                if meas1_data.get(field) != meas2_data.get(field):
                    changes[field] = {
                        "from": meas1_data.get(field),
                        "to": meas2_data.get(field)
                    }

            # Check annotations changes
            annot_changes = self._compare_annotations(
                meas1_data.get('annotations', []),
                meas2_data.get('annotations', [])
            )
            if annot_changes:
                changes['annotations'] = annot_changes

            # Check property changes
            prop_changes = self._compare_properties(
                meas1_data.get('properties', {}),
                meas2_data.get('properties', {})
            )
            if prop_changes:
                changes['properties'] = prop_changes

            if changes:
                result['modified'].append({
                    "name": meas_name,
                    "changes": changes
                })

        return result

    def _compare_hierarchies(
        self,
        hierarchies1: List[Dict[str, Any]],
        hierarchies2: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Compare hierarchies within a table."""
        hier1 = {h['name']: h for h in hierarchies1}
        hier2 = {h['name']: h for h in hierarchies2}

        hier1_names = set(hier1.keys())
        hier2_names = set(hier2.keys())

        result = {
            "added": list(hier2_names - hier1_names),
            "removed": list(hier1_names - hier2_names),
            "modified": []
        }

        # Check modified hierarchies
        for hier_name in hier1_names & hier2_names:
            h1 = hier1[hier_name]
            h2 = hier2[hier_name]

            # Compare levels
            levels1 = h1.get('levels', [])
            levels2 = h2.get('levels', [])

            if levels1 != levels2:
                result['modified'].append({
                    "name": hier_name,
                    "levels_from": [l.get('name') for l in levels1],
                    "levels_to": [l.get('name') for l in levels2]
                })

        return result

    def _compare_partitions(
        self,
        partitions1: List[Dict[str, Any]],
        partitions2: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Compare partitions within a table."""
        part1 = {p['name']: p for p in partitions1}
        part2 = {p['name']: p for p in partitions2}

        part1_names = set(part1.keys())
        part2_names = set(part2.keys())

        result = {
            "added": list(part2_names - part1_names),
            "removed": list(part1_names - part2_names),
            "modified": []
        }

        # Check modified partitions
        for part_name in part1_names & part2_names:
            p1 = part1[part_name]
            p2 = part2[part_name]

            changes = {}

            # Check mode change
            if p1.get('mode') != p2.get('mode'):
                changes['mode'] = {
                    "from": p1.get('mode'),
                    "to": p2.get('mode')
                }

            # Check source expression change
            source1 = p1.get('source') or ""
            source2 = p2.get('source') or ""

            if source1 != source2:
                changes['source'] = {
                    "from": source1,
                    "to": source2,
                    "diff": self._generate_text_diff(source1, source2)
                }

            if changes:
                result['modified'].append({
                    "name": part_name,
                    "changes": changes
                })

        return result

    def _compare_calculation_items(
        self,
        items1: List[Dict[str, Any]],
        items2: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Compare calculation items within a calculation group."""
        calc1 = {c['name']: c for c in items1}
        calc2 = {c['name']: c for c in items2}

        calc1_names = set(calc1.keys())
        calc2_names = set(calc2.keys())

        result = {
            "added": list(calc2_names - calc1_names),
            "removed": list(calc1_names - calc2_names),
            "modified": []
        }

        # Check modified calculation items
        for calc_name in calc1_names & calc2_names:
            c1 = calc1[calc_name]
            c2 = calc2[calc_name]

            changes = {}

            # Check expression changes
            expr1 = c1.get('expression') or ""
            expr2 = c2.get('expression') or ""

            if self._normalize_dax(expr1) != self._normalize_dax(expr2):
                changes['expression'] = {
                    "from": expr1,
                    "to": expr2,
                    "diff": self._generate_text_diff(expr1, expr2)
                }

            # Check format string definition changes
            fsd1 = c1.get('format_string_definition') or ""
            fsd2 = c2.get('format_string_definition') or ""

            if fsd1 != fsd2:
                changes['format_string_definition'] = {
                    "from": fsd1,
                    "to": fsd2
                }

            # Check ordinal changes
            if c1.get('ordinal') != c2.get('ordinal'):
                changes['ordinal'] = {
                    "from": c1.get('ordinal'),
                    "to": c2.get('ordinal')
                }

            # Check description
            if c1.get('description') != c2.get('description'):
                changes['description'] = {
                    "from": c1.get('description'),
                    "to": c2.get('description')
                }

            # Check annotations
            annot_changes = self._compare_annotations(
                c1.get('annotations', []),
                c2.get('annotations', [])
            )
            if annot_changes:
                changes['annotations'] = annot_changes

            if changes:
                result['modified'].append({
                    "name": calc_name,
                    "changes": changes
                })

        return result

    def _extract_all_measures(self, tables_diff: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract all measure changes from table changes into a separate top-level section.

        Returns measures organized as: modified, removed, added (in that order)
        """
        all_measures = {
            "modified": [],
            "removed": [],
            "added": []
        }

        # Extract from modified tables
        for table in tables_diff.get('modified', []):
            table_name = table['name']
            measures_changes = table.get('changes', {}).get('measures', {})

            # Modified measures
            for meas in measures_changes.get('modified', []):
                meas_with_table = meas.copy()
                meas_with_table['table'] = table_name
                all_measures['modified'].append(meas_with_table)

            # Removed measures
            for meas in measures_changes.get('removed', []):
                meas_with_table = meas.copy()
                meas_with_table['table'] = table_name
                all_measures['removed'].append(meas_with_table)

            # Added measures
            for meas in measures_changes.get('added', []):
                meas_with_table = meas.copy()
                meas_with_table['table'] = table_name
                all_measures['added'].append(meas_with_table)

        # Extract from added tables (all their measures are "added")
        for table in tables_diff.get('added', []):
            table_name = table['name']
            for meas in table.get('measures', []):
                meas_with_table = meas.copy()
                meas_with_table['table'] = table_name
                all_measures['added'].append(meas_with_table)

        # Extract from removed tables (all their measures are "removed")
        for table in tables_diff.get('removed', []):
            table_name = table['name']
            for meas in table.get('measures', []):
                meas_with_table = meas.copy()
                meas_with_table['table'] = table_name
                all_measures['removed'].append(meas_with_table)

        return all_measures

    def _compare_relationships(self) -> Dict[str, Any]:
        """Compare relationships between models."""
        logger.debug("Comparing relationships")

        rels1 = {self._relationship_key(r): r for r in self.model1.get('relationships', [])}
        rels2 = {self._relationship_key(r): r for r in self.model2.get('relationships', [])}

        rels1_keys = set(rels1.keys())
        rels2_keys = set(rels2.keys())

        result = {
            "added": [],
            "removed": [],
            "modified": []
        }

        # Added relationships
        for rel_key in rels2_keys - rels1_keys:
            rel = rels2[rel_key]
            rel_normalized = self._normalize_relationship(rel)

            result['added'].append({
                "from_table": rel_normalized['from_table'],
                "from_column": rel_normalized['from_column'],
                "to_table": rel_normalized['to_table'],
                "to_column": rel_normalized['to_column'],
                "from_cardinality": rel.get('from_cardinality'),
                "to_cardinality": rel.get('to_cardinality'),
                "is_active": rel.get('is_active', True),
                "cross_filtering_behavior": rel.get('cross_filtering_behavior') or rel.get('cross_filter_direction')
            })

        # Removed relationships
        for rel_key in rels1_keys - rels2_keys:
            rel = rels1[rel_key]
            rel_normalized = self._normalize_relationship(rel)

            result['removed'].append({
                "from_table": rel_normalized['from_table'],
                "from_column": rel_normalized['from_column'],
                "to_table": rel_normalized['to_table'],
                "to_column": rel_normalized['to_column'],
                "from_cardinality": rel.get('from_cardinality'),
                "to_cardinality": rel.get('to_cardinality')
            })

        # Modified relationships (same from/to but different properties)
        for rel_key in rels1_keys & rels2_keys:
            rel1 = rels1[rel_key]
            rel2 = rels2[rel_key]

            changes = {}

            # Check cardinality changes
            if rel1.get('from_cardinality') != rel2.get('from_cardinality'):
                changes['from_cardinality'] = {
                    "from": rel1.get('from_cardinality'),
                    "to": rel2.get('from_cardinality')
                }

            if rel1.get('to_cardinality') != rel2.get('to_cardinality'):
                changes['to_cardinality'] = {
                    "from": rel1.get('to_cardinality'),
                    "to": rel2.get('to_cardinality')
                }

            # Check active status
            if rel1.get('is_active') != rel2.get('is_active'):
                changes['is_active'] = {
                    "from": rel1.get('is_active', True),
                    "to": rel2.get('is_active', True)
                }

            # Check cross-filtering behavior
            if rel1.get('cross_filtering_behavior') != rel2.get('cross_filtering_behavior'):
                changes['cross_filtering_behavior'] = {
                    "from": rel1.get('cross_filtering_behavior'),
                    "to": rel2.get('cross_filtering_behavior')
                }

            # Check security filtering behavior
            if rel1.get('security_filtering_behavior') != rel2.get('security_filtering_behavior'):
                changes['security_filtering_behavior'] = {
                    "from": rel1.get('security_filtering_behavior'),
                    "to": rel2.get('security_filtering_behavior')
                }

            # Check referential integrity
            if rel1.get('rely_on_referential_integrity') != rel2.get('rely_on_referential_integrity'):
                changes['rely_on_referential_integrity'] = {
                    "from": rel1.get('rely_on_referential_integrity'),
                    "to": rel2.get('rely_on_referential_integrity')
                }

            # Check annotations
            annot_changes = self._compare_annotations(
                rel1.get('annotations', []),
                rel2.get('annotations', [])
            )
            if annot_changes:
                changes['annotations'] = annot_changes

            if changes:
                rel_normalized = self._normalize_relationship(rel1)

                result['modified'].append({
                    "from_table": rel_normalized['from_table'],
                    "from_column": rel_normalized['from_column'],
                    "to_table": rel_normalized['to_table'],
                    "to_column": rel_normalized['to_column'],
                    "changes": changes
                })

        logger.debug(
            f"Relationships: {len(result['added'])} added, "
            f"{len(result['removed'])} removed, "
            f"{len(result['modified'])} modified"
        )

        return result

    def _normalize_relationship(self, rel: Dict[str, Any]) -> Dict[str, str]:
        """
        Normalize relationship to a standard format with separate table and column fields.

        Handles two input formats:
        1. export_tmdl_structure format: has 'from_table', 'from_column', 'to_table', 'to_column'
        2. TMDL file format: has 'from_column' and 'to_column' as combined references

        Args:
            rel: Relationship dict in either format

        Returns:
            Dict with 'from_table', 'from_column', 'to_table', 'to_column' keys
        """
        # Check if already in normalized format (has separate from_table field)
        if 'from_table' in rel and 'to_table' in rel:
            return {
                'from_table': rel.get('from_table', 'Unknown'),
                'from_column': rel.get('from_column', 'Unknown'),
                'to_table': rel.get('to_table', 'Unknown'),
                'to_column': rel.get('to_column', 'Unknown')
            }

        # Otherwise, parse from combined references
        from_parts = self._parse_column_ref(rel.get('from_column', ''))
        to_parts = self._parse_column_ref(rel.get('to_column', ''))

        return {
            'from_table': from_parts['table'],
            'from_column': from_parts['column'],
            'to_table': to_parts['table'],
            'to_column': to_parts['column']
        }

    def _parse_column_ref(self, col_ref: str) -> Dict[str, str]:
        """
        Parse a column reference into table and column names.

        Args:
            col_ref: Column reference in format like:
                - 'TableName'[ColumnName]
                - TableName[ColumnName]
                - TableName.ColumnName

        Returns:
            Dict with 'table' and 'column' keys
        """
        import re

        if not col_ref:
            return {'table': 'Unknown', 'column': 'Unknown'}

        # Pattern: 'TableName'[ColumnName] or TableName[ColumnName]
        match = re.match(r"^'?([^'\[]+)'?\[([^\]]+)\]$", col_ref)
        if match:
            return {'table': match.group(1), 'column': match.group(2)}

        # Pattern: TableName.ColumnName
        if '.' in col_ref and '[' not in col_ref:
            parts = col_ref.split('.', 1)
            return {'table': parts[0], 'column': parts[1]}

        # Fallback: couldn't parse
        return {'table': 'Unknown', 'column': col_ref}

    def _relationship_key(self, rel: Dict[str, Any]) -> str:
        """
        Generate unique key for a relationship.

        Handles both export_tmdl_structure format and TMDL file format.
        """
        # Normalize the relationship first
        norm = self._normalize_relationship(rel)

        # Create key from table.column references
        from_ref = f"{norm['from_table']}[{norm['from_column']}]"
        to_ref = f"{norm['to_table']}[{norm['to_column']}]"

        return f"{from_ref}|{to_ref}"

    def _compare_roles(self) -> Dict[str, Any]:
        """Compare roles between models."""
        roles1 = {r['name']: r for r in self.model1.get('roles', [])}
        roles2 = {r['name']: r for r in self.model2.get('roles', [])}

        roles1_names = set(roles1.keys())
        roles2_names = set(roles2.keys())

        modified = []
        for name in roles1_names & roles2_names:
            r1, r2 = roles1[name], roles2[name]
            changes = {}

            # Compare filter expressions per table
            filters1 = {f.get('table', ''): f.get('expression', '') for f in r1.get('table_permissions', [])}
            filters2 = {f.get('table', ''): f.get('expression', '') for f in r2.get('table_permissions', [])}
            if filters1 != filters2:
                added_tables = set(filters2) - set(filters1)
                removed_tables = set(filters1) - set(filters2)
                changed_tables = {t for t in set(filters1) & set(filters2) if filters1[t] != filters2[t]}
                changes["filter_expressions"] = {
                    "added_tables": list(added_tables),
                    "removed_tables": list(removed_tables),
                    "changed_tables": list(changed_tables),
                }

            # Compare members
            members1 = set(r1.get('members', []))
            members2 = set(r2.get('members', []))
            if members1 != members2:
                changes["members"] = {
                    "added": list(members2 - members1),
                    "removed": list(members1 - members2),
                }

            if changes:
                modified.append({"name": name, "changes": changes})

        return {
            "added": list(roles2_names - roles1_names),
            "removed": list(roles1_names - roles2_names),
            "modified": modified,
        }

    def _compare_perspectives(self) -> Dict[str, Any]:
        """Compare perspectives between models."""
        persp1 = {p['name']: p for p in self.model1.get('perspectives', [])}
        persp2 = {p['name']: p for p in self.model2.get('perspectives', [])}

        persp1_names = set(persp1.keys())
        persp2_names = set(persp2.keys())

        modified = []
        for name in persp1_names & persp2_names:
            p1, p2 = persp1[name], persp2[name]
            objects1 = set()
            objects2 = set()
            for t in p1.get('tables', []):
                tname = t.get('name', '')
                objects1.add(f"table:{tname}")
                for c in t.get('columns', []):
                    objects1.add(f"column:{tname}.{c}")
                for m in t.get('measures', []):
                    objects1.add(f"measure:{tname}.{m}")
                for h in t.get('hierarchies', []):
                    objects1.add(f"hierarchy:{tname}.{h}")
            for t in p2.get('tables', []):
                tname = t.get('name', '')
                objects2.add(f"table:{tname}")
                for c in t.get('columns', []):
                    objects2.add(f"column:{tname}.{c}")
                for m in t.get('measures', []):
                    objects2.add(f"measure:{tname}.{m}")
                for h in t.get('hierarchies', []):
                    objects2.add(f"hierarchy:{tname}.{h}")

            if objects1 != objects2:
                modified.append({
                    "name": name,
                    "added_objects": sorted(objects2 - objects1),
                    "removed_objects": sorted(objects1 - objects2),
                })

        return {
            "added": list(persp2_names - persp1_names),
            "removed": list(persp1_names - persp2_names),
            "modified": modified,
        }

    def _compare_model_properties(self) -> Dict[str, Any]:
        """Compare high-level model properties."""
        model1_props = self.model1.get('model', {}).get('properties', {})
        model2_props = self.model2.get('model', {}).get('properties', {})

        db1_props = self.model1.get('database', {}).get('properties', {})
        db2_props = self.model2.get('database', {}).get('properties', {})

        changes = {}

        # Compare database properties
        db_changes = self._compare_properties(db1_props, db2_props)
        if db_changes:
            changes['database'] = db_changes

        # Compare model properties
        model_changes = self._compare_properties(model1_props, model2_props)
        if model_changes:
            changes['model'] = model_changes

        return changes

    def _compare_properties(
        self,
        props1: Dict[str, Any],
        props2: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compare two property dictionaries."""
        all_keys = set(props1.keys()) | set(props2.keys())
        changes = {}

        for key in all_keys:
            val1 = props1.get(key)
            val2 = props2.get(key)

            if val1 != val2:
                changes[key] = {
                    "from": val1,
                    "to": val2
                }

        return changes

    def _compare_annotations(
        self,
        annots1: List[Dict[str, Any]],
        annots2: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Compare two annotation lists."""
        # Create dictionaries keyed by annotation name
        a1_dict = {a['name']: a['value'] for a in annots1} if annots1 else {}
        a2_dict = {a['name']: a['value'] for a in annots2} if annots2 else {}

        all_keys = set(a1_dict.keys()) | set(a2_dict.keys())

        changes = {}
        for key in all_keys:
            val1 = a1_dict.get(key)
            val2 = a2_dict.get(key)

            if val1 != val2:
                changes[key] = {
                    "from": val1,
                    "to": val2
                }

        return changes

    def _normalize_dax(self, dax: str) -> str:
        """
        Normalize DAX expression for comparison.

        Removes insignificant whitespace differences to avoid false positives.
        """
        if not dax:
            return ""

        # Remove extra whitespace
        normalized = ' '.join(dax.split())

        # Remove whitespace around operators
        for op in ['=', '+', '-', '*', '/', '(', ')', ',', '[', ']']:
            normalized = normalized.replace(f' {op} ', op)
            normalized = normalized.replace(f' {op}', op)
            normalized = normalized.replace(f'{op} ', op)

        return normalized.strip()

    def _generate_text_diff(self, text1: str, text2: str) -> List[str]:
        """
        Generate unified diff for text comparison.

        Args:
            text1: Original text
            text2: Modified text

        Returns:
            List of diff lines
        """
        if not text1 and not text2:
            return []

        lines1 = text1.splitlines() if text1 else []
        lines2 = text2.splitlines() if text2 else []

        # Generate unified diff
        diff = list(difflib.unified_diff(
            lines1,
            lines2,
            fromfile='original',
            tofile='modified',
            lineterm=''
        ))

        return diff

    def _calculate_summary(self) -> None:
        """Calculate summary statistics for the diff."""
        summary = self.diff_result['summary']

        # Count changes by category
        changes_by_category = {
            "tables_added": len(self.diff_result['tables']['added']),
            "tables_removed": len(self.diff_result['tables']['removed']),
            "tables_modified": len(self.diff_result['tables']['modified']),
            "relationships_added": len(self.diff_result['relationships']['added']),
            "relationships_removed": len(self.diff_result['relationships']['removed']),
            "relationships_modified": len(self.diff_result['relationships']['modified']),
            "roles_added": len(self.diff_result['roles']['added']),
            "roles_removed": len(self.diff_result['roles']['removed']),
            "perspectives_added": len(self.diff_result['perspectives']['added']),
            "perspectives_removed": len(self.diff_result['perspectives']['removed'])
        }

        # Count detailed changes within modified tables
        columns_added = columns_removed = columns_modified = 0
        measures_added = measures_removed = measures_modified = 0

        for table_diff in self.diff_result['tables']['modified']:
            changes = table_diff['changes']
            columns_added += len(changes['columns']['added'])
            columns_removed += len(changes['columns']['removed'])
            columns_modified += len(changes['columns']['modified'])
            measures_added += len(changes['measures']['added'])
            measures_removed += len(changes['measures']['removed'])
            measures_modified += len(changes['measures']['modified'])

        changes_by_category.update({
            "columns_added": columns_added,
            "columns_removed": columns_removed,
            "columns_modified": columns_modified,
            "measures_added": measures_added,
            "measures_removed": measures_removed,
            "measures_modified": measures_modified
        })

        summary['changes_by_category'] = changes_by_category
        summary['total_changes'] = sum(changes_by_category.values())


def compare_models(model1: Dict[str, Any], model2: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to compare two models.

    Args:
        model1: First parsed model
        model2: Second parsed model

    Returns:
        Diff result dictionary
    """
    differ = ModelDiffer(model1, model2)
    return differ.compare()
