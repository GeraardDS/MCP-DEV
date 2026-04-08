"""
Best Practice Analyzer for Semantic Models
Analyzes TMSL models against a comprehensive set of best practice rules
"""

import glob
import json
import os
import re
import time
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass
from enum import IntEnum
import logging

from core.utilities.json_utils import load_json

logger = logging.getLogger(__name__)

class BPASeverity(IntEnum):
    """BPA Rule Severity Levels"""
    INFO = 1
    WARNING = 2
    ERROR = 3

@dataclass
class BPAViolation:
    """Represents a Best Practice Analyzer rule violation"""
    rule_id: str
    rule_name: str
    category: str
    severity: BPASeverity
    description: str
    object_type: str
    object_name: str
    table_name: Optional[str] = None
    fix_expression: Optional[str] = None
    details: Optional[str] = None

@dataclass
class BPARule:
    """Represents a Best Practice Analyzer rule"""
    id: str
    name: str
    category: str
    description: str
    severity: BPASeverity
    scope: List[str]
    expression: str
    fix_expression: Optional[str] = None
    compatibility_level: int = 1200

class BPAAnalyzer:
    """
    Best Practice Analyzer for Semantic Models
    Analyzes TMSL models against best practice rules
    """
    
    def __init__(self, rules_file_path: Optional[str] = None):
        """
        Initialize the BPA Analyzer

        Args:
            rules_file_path: Path to the BPA rules JSON file
        """
        self.rules: List[BPARule] = []
        self.violations: List[BPAViolation] = []
        self._eval_depth = 0  # Track recursion depth
        self._max_depth = 50  # Prevent stack overflow
        self._regex_cache: Dict[str, re.Pattern] = {}
        self._run_notes: List[str] = []
        # Fast-mode limits injected by analyze_model_fast
        self._fast_cfg: Dict[str, Any] = {}

        # Expression evaluation cache (PERFORMANCE IMPROVEMENT)
        # Cache key: (expression_str, frozen_context_state)
        # This avoids re-evaluating the same expression with same context repeatedly
        self._expression_cache: Dict[tuple, Union[bool, int, float, str]] = {}
        self._cache_hits = 0
        self._cache_misses = 0

        if rules_file_path:
            self.load_rules(rules_file_path)

        # Load built-in enhanced rules and custom rules
        self._init_builtin_rules()
        self._load_custom_rules()

    def _init_builtin_rules(self) -> None:
        """Add built-in enhanced BPA rules to the rule set.

        These rules supplement whatever was loaded from the JSON
        rules file and cover categories like DAX Expressions,
        Naming, Formatting, Relationships, Calculation Groups,
        and Performance.
        """
        builtin = self._get_builtin_rules()
        existing_ids = {r.id for r in self.rules}
        added = 0
        for rule_data in builtin:
            rid = rule_data.get("ID", "")
            if rid and rid not in existing_ids:
                scope_raw = rule_data.get("Scope", "")
                scope = (
                    [s.strip() for s in scope_raw.split(",")]
                    if isinstance(scope_raw, str)
                    else scope_raw
                )
                rule = BPARule(
                    id=rid,
                    name=rule_data.get("Name", ""),
                    category=rule_data.get("Category", ""),
                    description=rule_data.get(
                        "Description", ""
                    ),
                    severity=BPASeverity(
                        rule_data.get("Severity", 1)
                    ),
                    scope=scope,
                    expression=rule_data.get(
                        "Expression", ""
                    ),
                    fix_expression=rule_data.get(
                        "FixExpression"
                    ),
                    compatibility_level=rule_data.get(
                        "CompatibilityLevel", 1200
                    ),
                )
                self.rules.append(rule)
                existing_ids.add(rid)
                added += 1
        if added:
            logger.info(
                f"Added {added} built-in enhanced BPA rules"
            )

    def _load_custom_rules(self) -> None:
        """Load custom BPA rules from config/bpa_rules/*.json.

        Each JSON file should have a top-level ``rules`` array
        following the same schema as the main rules file.
        Rules whose ID already exists are silently skipped to
        avoid duplicates.
        """
        # Resolve config/bpa_rules/ relative to project root.
        # Assumes layout: <project_root>/core/analysis/bpa_analyzer.py
        # (two parent directories up from this file reaches the project root).
        script_dir = os.path.dirname(
            os.path.abspath(__file__)
        )
        # core/analysis -> core -> project root
        root_dir = os.path.dirname(
            os.path.dirname(script_dir)
        )
        custom_dir = os.path.join(
            root_dir, "config", "bpa_rules"
        )
        if not os.path.isdir(custom_dir):
            return

        pattern = os.path.join(custom_dir, "*.json")
        json_files = sorted(glob.glob(pattern))
        if not json_files:
            return

        existing_ids = {r.id for r in self.rules}
        total_added = 0

        for fpath in json_files:
            try:
                with open(
                    fpath, "r", encoding="utf-8"
                ) as f:
                    data = json.load(f)
                rules_list = data.get("rules", [])
                added = 0
                for rule_data in rules_list:
                    rid = rule_data.get("ID", "")
                    if not rid or rid in existing_ids:
                        continue
                    scope_raw = rule_data.get("Scope", "")
                    scope = (
                        [
                            s.strip()
                            for s in scope_raw.split(",")
                        ]
                        if isinstance(scope_raw, str)
                        else scope_raw
                    )
                    rule = BPARule(
                        id=rid,
                        name=rule_data.get("Name", ""),
                        category=rule_data.get(
                            "Category", ""
                        ),
                        description=rule_data.get(
                            "Description", ""
                        ),
                        severity=BPASeverity(
                            rule_data.get("Severity", 1)
                        ),
                        scope=scope,
                        expression=rule_data.get(
                            "Expression", ""
                        ),
                        fix_expression=rule_data.get(
                            "FixExpression"
                        ),
                        compatibility_level=rule_data.get(
                            "CompatibilityLevel", 1200
                        ),
                    )
                    self.rules.append(rule)
                    existing_ids.add(rid)
                    added += 1
                if added:
                    fname = os.path.basename(fpath)
                    logger.info(
                        f"Loaded {added} custom BPA rules "
                        f"from {fname}"
                    )
                total_added += added
            except (
                json.JSONDecodeError,
                FileNotFoundError,
                OSError,
            ) as e:
                logger.warning(
                    f"Failed to load custom BPA rules "
                    f"from {fpath}: {e}"
                )
            except Exception as e:
                logger.warning(
                    f"Unexpected error loading custom "
                    f"BPA rules from {fpath}: {e}"
                )

        if total_added:
            logger.info(
                f"Total custom BPA rules loaded: "
                f"{total_added}"
            )

    @staticmethod
    def _get_builtin_rules() -> List[Dict[str, Any]]:
        """Return built-in enhanced BPA rule definitions.

        These are programmatic rules that don't rely on the
        expression evaluator's regex engine but are instead
        checked via standard expression evaluation patterns
        already supported by ``evaluate_expression``.
        """
        rules: List[Dict[str, Any]] = []

        # ── DAX Expressions ─────────────────────────────
        rules.append({
            "ID": "DAX_CALCULATE_COUNTROWS",
            "Name": "Avoid CALCULATE(COUNTROWS(...))",
            "Category": "DAX Expressions",
            "Severity": 2,
            "Description": (
                "CALCULATE(COUNTROWS(...)) can often be "
                "simplified. Use COUNTROWS with CALCULATE "
                "wrapping the table filter instead."
            ),
            "Scope": "Measure",
            "Expression": (
                'RegEx.IsMatch(Expression, '
                '"CALCULATE\\s*\\(\\s*COUNTROWS"'
                ', "(?i)")'
            ),
            "FixExpression": (
                "Restructure to use CALCULATE with "
                "COUNTROWS and explicit filter arguments."
            ),
        })
        rules.append({
            "ID": "DAX_ISBLANK_ZERO",
            "Name": (
                "Simplify IF(ISBLANK(...), 0, ...)"
            ),
            "Category": "DAX Expressions",
            "Severity": 1,
            "Description": (
                "IF(ISBLANK(x), 0, x) can be simplified "
                "to x + 0 or COALESCE(x, 0) for cleaner "
                "DAX."
            ),
            "Scope": "Measure",
            "Expression": (
                'RegEx.IsMatch(Expression, '
                '"IF\\s*\\(\\s*ISBLANK\\s*\\('
                '.+?\\)\\s*,\\s*0"'
                ', "(?i)")'
            ),
            "FixExpression": (
                "Use COALESCE(expression, 0) or "
                "expression + 0 instead."
            ),
        })
        rules.append({
            "ID": "DAX_NESTED_IF",
            "Name": "Avoid deeply nested IF statements",
            "Category": "DAX Expressions",
            "Severity": 2,
            "Description": (
                "Multiple nested IF statements reduce "
                "readability. Use SWITCH for multi-"
                "condition logic."
            ),
            "Scope": "Measure",
            "Expression": (
                'RegEx.IsMatch(Expression, '
                '"IF\\s*\\([^)]*IF\\s*\\([^)]*'
                'IF\\s*\\("'
                ', "(?i)")'
            ),
            "FixExpression": (
                "Replace nested IFs with SWITCH(TRUE(), "
                "condition1, result1, condition2, result2"
                ", ..., default)."
            ),
        })

        # ── Naming ──────────────────────────────────────
        rules.append({
            "ID": "NAMING_MEASURE_LEADING_TRAILING_SPACE",
            "Name": (
                "Measure name has leading/trailing spaces"
            ),
            "Category": "Naming",
            "Severity": 2,
            "Description": (
                "Measure names should not start or end "
                "with spaces. This can cause unexpected "
                "behavior in DAX references."
            ),
            "Scope": "Measure",
            "Expression": (
                'RegEx.IsMatch(Name, '
                '"^\\s|\\s$")'
            ),
            "FixExpression": (
                "Trim leading and trailing spaces from "
                "the measure name."
            ),
        })
        rules.append({
            "ID": "NAMING_TABLE_CONVENTION",
            "Name": (
                "Table name should follow consistent "
                "naming convention"
            ),
            "Category": "Naming",
            "Severity": 1,
            "Description": (
                "Table names should use PascalCase or a "
                "consistent naming pattern. Names with "
                "leading/trailing spaces or special "
                "characters at the start are discouraged."
            ),
            "Scope": "Table",
            "Expression": (
                'RegEx.IsMatch(Name, '
                '"^[\\s_\\-]|[\\s]$")'
            ),
            "FixExpression": (
                "Rename the table to follow PascalCase "
                "or your project's naming convention."
            ),
        })
        rules.append({
            "ID": "NAMING_COLUMN_SPECIAL_CHAR_START",
            "Name": (
                "Column name starts with special "
                "character"
            ),
            "Category": "Naming",
            "Severity": 2,
            "Description": (
                "Column names should not start with "
                "special characters like @, #, $, etc. "
                "This can cause issues in DAX expressions."
            ),
            "Scope": "DataColumn, CalculatedColumn",
            "Expression": (
                'RegEx.IsMatch(Name, '
                '"^[^a-zA-Z0-9_]")'
            ),
            "FixExpression": (
                "Rename the column to start with a "
                "letter, number, or underscore."
            ),
        })

        # ── Formatting ──────────────────────────────────
        rules.append({
            "ID": "FORMAT_MEASURE_NO_FORMAT_STRING",
            "Name": "Measure has no format string",
            "Category": "Formatting",
            "Severity": 1,
            "Description": (
                "Measures should have a format string "
                "defined for consistent display in "
                "reports and visuals."
            ),
            "Scope": "Measure",
            "Expression": (
                'string.IsNullOrWhitespace('
                'FormatString)'
            ),
            "FixExpression": (
                "Add an appropriate format string, "
                "e.g. '#,0', '#,0.00', '0.0%', etc."
            ),
        })
        rules.append({
            "ID": "FORMAT_PERCENTAGE_CONSISTENCY",
            "Name": (
                "Percentage measure should use % format"
            ),
            "Category": "Formatting",
            "Severity": 1,
            "Description": (
                "Measures whose names suggest a "
                "percentage (containing '%', 'pct', or "
                "'percent') should use a percentage "
                "format string."
            ),
            "Scope": "Measure",
            "Expression": (
                'RegEx.IsMatch(Name, '
                '"(%|pct|percent)", "(?i)") '
                'and not RegEx.IsMatch(FormatString, '
                '"%")'
            ),
            "FixExpression": (
                "Set the format string to '0.0%' or "
                "'0.00%'."
            ),
        })

        # ── Relationships ───────────────────────────────
        rules.append({
            "ID": "REL_BIDIRECTIONAL_WARNING",
            "Name": (
                "Bidirectional cross-filter relationship"
            ),
            "Category": "Relationships",
            "Severity": 2,
            "Description": (
                "Bidirectional cross-filtering can cause "
                "ambiguous filter propagation and "
                "performance issues. Use single-direction "
                "unless strictly required."
            ),
            "Scope": "Relationship",
            "Expression": (
                'crossFilteringBehavior == '
                '"BothDirections"'
            ),
            "FixExpression": (
                "Change the relationship to single-"
                "direction cross-filtering."
            ),
        })
        rules.append({
            "ID": "REL_TABLE_NO_RELATIONSHIPS",
            "Name": "Table has no relationships",
            "Category": "Relationships",
            "Severity": 1,
            "Description": (
                "Tables without any relationships may "
                "be disconnected from the model. Ensure "
                "this is intentional (e.g., parameter "
                "tables, disconnected slicers)."
            ),
            "Scope": "Table",
            "Expression": (
                'Model.AllRelationships.Any('
                'FromTable == outerIt.Name or '
                'ToTable == outerIt.Name'
                ') == false'
            ),
            "FixExpression": (
                "Create a relationship to connect this "
                "table to the model, or document why it "
                "is intentionally disconnected."
            ),
        })

        # ── Calculation Groups ──────────────────────────
        rules.append({
            "ID": "CALCGROUP_ORDINAL_GAPS",
            "Name": (
                "Calculation group has ordinal gaps"
            ),
            "Category": "Calculation Groups",
            "Severity": 1,
            "Description": (
                "Calculation items should have "
                "sequential ordinal values without gaps "
                "for predictable evaluation order. "
                "Only applies when there are 2+ items."
            ),
            "Scope": "CalculationGroup",
            "Expression": (
                'calculationItems.Count > 1'
            ),
            "FixExpression": (
                "Review and re-number calculation item "
                "ordinals to be sequential (0, 1, 2...)."
            ),
        })

        # ── Performance ─────────────────────────────────
        rules.append({
            "ID": "PERF_TABLE_TOO_MANY_COLUMNS",
            "Name": "Table has too many columns",
            "Category": "Performance",
            "Severity": 2,
            "Description": (
                "Tables with more than 30 columns may "
                "indicate a need to split into multiple "
                "tables or remove unused columns to "
                "improve model performance."
            ),
            "Scope": "Table",
            "Expression": (
                'Columns.Count > 30'
            ),
            "FixExpression": (
                "Remove unused columns or split the "
                "table into smaller, focused tables."
            ),
        })
        rules.append({
            "ID": "PERF_WIDE_TABLE_WARNING",
            "Name": (
                "Table has excessive columns (>50)"
            ),
            "Category": "Performance",
            "Severity": 3,
            "Description": (
                "Tables with more than 50 columns are "
                "likely to cause significant performance "
                "issues. Consider removing unnecessary "
                "columns."
            ),
            "Scope": "Table",
            "Expression": (
                'Columns.Count > 50'
            ),
            "FixExpression": (
                "Aggressively prune unused columns. "
                "Consider splitting into fact and "
                "dimension tables."
            ),
        })

        return rules

    def _precompile_common_patterns(self):
        """Eagerly compile common regex patterns used in BPA rules for performance"""
        # Common patterns found in BPA rules - precompile them at initialization
        common_patterns = [
            (r'\bCOUNT(ROWS)?\s*\(', 0),
            (r'\bSUM\s*\(', 0),
            (r'\bAVERAGE\s*\(', 0),
            (r'\bCALCULATE\s*\(', 0),
            (r'\bFILTER\s*\(', 0),
            (r'\bALL\s*\(', 0),
            (r'\bVALUES\s*\(', 0),
            (r'^\s*IF\s*\(', 0),
            (r'\bRELATED\s*\(', 0),
            (r'\bSUMX\s*\(', 0),
            (r'\bUNION\s*\(', 0),
            (r'Key|ID|Code', re.IGNORECASE),
            (r'^_', 0),
            (r'\s{2,}', 0)
        ]
        for pattern, flags in common_patterns:
            key = f"{pattern}__{flags}"
            if key not in self._regex_cache:
                try:
                    self._regex_cache[key] = re.compile(pattern, flags)
                except re.error:
                    pass

    def load_rules(self, rules_file_path: str) -> None:
        """Load BPA rules from JSON file"""
        try:
            rules_data = load_json(rules_file_path)

            self.rules = []
            for rule_data in rules_data.get('rules', []):
                rule = BPARule(
                    id=rule_data.get('ID', ''),
                    name=rule_data.get('Name', ''),
                    category=rule_data.get('Category', ''),
                    description=rule_data.get('Description', ''),
                    severity=BPASeverity(rule_data.get('Severity', 1)),
                    scope=rule_data.get('Scope', '').split(', '),
                    expression=rule_data.get('Expression', ''),
                    fix_expression=rule_data.get('FixExpression'),
                    compatibility_level=rule_data.get('CompatibilityLevel', 1200)
                )
                self.rules.append(rule)

            logger.info(f"Loaded {len(self.rules)} BPA rules")

            # Eagerly compile common patterns for performance
            self._precompile_common_patterns()

        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Error loading BPA rules: {str(e)}")
            raise

    def validate_rules_file(self, rules_file_path: str) -> bool:
        """Validate BPA rules file schema"""
        try:
            rules_data = load_json(rules_file_path)
            for rule in rules_data.get('rules', []):
                required = ['ID', 'Name', 'Category', 'Description', 'Severity', 'Scope', 'Expression']
                for key in required:
                    if key not in rule:
                        logger.error(f"Missing key {key} in rule {rule.get('ID')}")
                        return False
            return True
        except Exception as e:
            logger.error(f"Validation failed: {str(e)}")
            return False

    def get_run_notes(self) -> List[str]:
        """Return notes from the most recent run (timeouts, filters applied, etc.)."""
        return list(self._run_notes)

    def _compile_regex(self, pattern: str, flags: int = 0) -> re.Pattern:
        """Return a compiled regex from cache for faster repeated matches."""
        key = f"{pattern}__{flags}"
        cached = self._regex_cache.get(key)
        if cached is not None:
            return cached
        try:
            compiled = re.compile(pattern, flags)
        except re.error:
            # Fallback to a pattern that never matches to avoid runtime errors
            compiled = re.compile(r"a\b\B")
        self._regex_cache[key] = compiled
        return compiled

    def _build_model_index(self, model: Dict[str, Any]) -> Dict[str, Any]:
        """Precompute commonly accessed collections to avoid O(N) rebuilds per lookup."""
        tables = model.get('tables', []) or []
        all_columns: List[Dict[str, Any]] = []
        all_measures: List[Dict[str, Any]] = []
        all_calc_items: List[Dict[str, Any]] = []
        tables_by_name: Dict[str, Dict[str, Any]] = {}
        for t in tables:
            try:
                tname = t.get('name')
                if isinstance(tname, str):
                    tables_by_name[tname] = t
                cols = t.get('columns', []) or []
                if cols:
                    all_columns.extend(cols)
                meas = t.get('measures', []) or []
                if meas:
                    all_measures.extend(meas)
                cg = t.get('calculationGroup') or {}
                if isinstance(cg, dict):
                    items = cg.get('calculationItems', []) or []
                    if items:
                        all_calc_items.extend(items)
            except Exception:
                continue
        return {
            'all_columns': all_columns,
            'all_measures': all_measures,
            'all_calc_items': all_calc_items,
            'tables_by_name': tables_by_name,
            'relationships': model.get('relationships', []) or [],
            'tables': tables,
        }

    def _freeze_context_for_cache(self, context: Dict) -> tuple:
        """
        Create a hashable cache key from context state.
        We freeze the essential parts of the context that affect evaluation results.

        Args:
            context: The evaluation context dictionary

        Returns:
            Frozen tuple representation of context for cache key
        """
        try:
            # The object being evaluated lives inside
            # context['obj'] or context['current'], not
            # at the context root.
            obj = (
                context.get('obj')
                or context.get('current')
                or {}
            )
            tbl = context.get('table') or {}
            obj_type = context.get('_ObjectType', '')
            obj_name = (
                obj.get('Name', obj.get('name', ''))
                if isinstance(obj, dict) else str(obj)
            )
            table_name = (
                tbl.get('name', tbl.get('Name', ''))
                if isinstance(tbl, dict) else str(tbl)
            )

            frozen = (
                obj_type,
                str(obj_name),
                str(table_name),
                str(
                    obj.get(
                        'Expression',
                        obj.get('expression', '')
                    )
                    if isinstance(obj, dict) else ''
                ),
                str(
                    obj.get(
                        'IsHidden',
                        obj.get('isHidden', '')
                    )
                    if isinstance(obj, dict) else ''
                ),
                str(
                    obj.get(
                        'DataType',
                        obj.get('dataType', '')
                    )
                    if isinstance(obj, dict) else ''
                ),
            )

            return frozen

        except Exception as e:
            # If freezing fails, return a unique key to prevent caching
            # This ensures we don't cache potentially unstable results
            logger.debug(f"Failed to freeze context for caching: {e}")
            return (str(id(context)),)  # Unique key that won't match anything

    def get_expression_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for monitoring performance."""
        total_requests = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total_requests * 100) if total_requests > 0 else 0

        return {
            'cache_size': len(self._expression_cache),
            'cache_hits': self._cache_hits,
            'cache_misses': self._cache_misses,
            'total_requests': total_requests,
            'hit_rate_percent': round(hit_rate, 1)
        }

    def clear_expression_cache(self) -> None:
        """Clear the expression evaluation cache."""
        cache_size = len(self._expression_cache)
        self._expression_cache.clear()
        logger.debug(f"Cleared BPA expression cache ({cache_size} entries)")

    def evaluate_expression(self, expression: str, context: Dict) -> Union[bool, int, float, str]:
        """
        Cached wrapper for expression evaluation with memoization (PERFORMANCE IMPROVEMENT).
        This wrapper checks the cache before calling the actual evaluator implementation.
        """
        # Check cache FIRST
        cache_key = (expression, self._freeze_context_for_cache(context))
        if cache_key in self._expression_cache:
            self._cache_hits += 1
            return self._expression_cache[cache_key]

        self._cache_misses += 1

        # Cache miss - evaluate and store result
        result = self._evaluate_expression_impl(expression, context)

        # Cache the result (only cache stable results, not depth-exceeded or error cases)
        # We cache False results too, as they're often repeated for invalid expressions
        self._expression_cache[cache_key] = result

        return result

    def _evaluate_expression_impl(self, expression: str, context: Dict) -> Union[bool, int, float, str]:
        """Recursive evaluator for rule expressions with depth protection

        Notes:
        - Handle specific function patterns (RegEx.IsMatch, string.IsNullOrWhiteSpace, Convert.ToInt64, etc.)
          BEFORE applying generic parentheses reduction so we don't split or recurse into regex pattern strings.
        - Support dotted property access (e.g., Table.IsHidden) and case-insensitive key lookup.
        """
        # Depth check to prevent stack overflow
        self._eval_depth += 1
        if self._eval_depth > self._max_depth:
            self._eval_depth -= 1
            logger.warning(f"Max evaluation depth reached for expression: {expression[:50]}")
            return False

        try:
            # Safety checks
            if not expression or not isinstance(expression, str):
                return False

            expression = re.sub(r'\s+', ' ', expression).strip()

            # Short-circuit: DAX-style column reference 'Table'[Column] or Table[Column]
            dax_col = re.match(r"^'?([^']+?)'?\[([^\]]+)\]$", expression)
            if dax_col:
                tbl = dax_col.group(1)
                col = dax_col.group(2)
                idx = context.get('index') or {}
                tmap = idx.get('tables_by_name') or {}
                t = tmap.get(tbl) or tmap.get(str(tbl).strip())
                if isinstance(t, dict):
                    for c in t.get('columns', []) or []:
                        if str(c.get('name')) == col:
                            # Return the column name for regex/name checks
                            return str(c.get('name'))
                # Fallback to returning the literal reference string
                return expression

            # IMPORTANT: Handle certain function patterns first to avoid corrupting
            # their arguments with the generic parentheses reducer.

            # Handle RegEx.IsMatch(field, "pattern") optionally with third arg
            regex_match = re.match(r'RegEx\.IsMatch\(([^,]+),\s*"([^"]+)"(,.*)?\)', expression)
            if regex_match:
                field = regex_match.group(1).strip()
                pattern = regex_match.group(2)
                third_arg = regex_match.group(3) or ''
                value = self.evaluate_expression(
                    field, context
                )
                has_ignorecase = (
                    '(?i)' in pattern
                    or '(?i)' in third_arg
                )
                flags = (
                    re.IGNORECASE if has_ignorecase else 0
                )
                pattern = pattern.replace('(?i)', '')
                compiled = self._compile_regex(pattern, flags)
                result = bool(compiled.search(str(value) if value is not None else ''))
                return result

            # Handle Collection.AnyFalse / Collection.AnyTrue
            anyfalse_match = re.match(r'([A-Za-z0-9_.]+)\.AnyFalse$', expression)
            if anyfalse_match:
                collection_path = anyfalse_match.group(1)
                collection = self._get_by_path(context, collection_path)
                result = False
                if isinstance(collection, list):
                    # Interpret truthiness of items
                    for item in collection:
                        if isinstance(item, dict):
                            # If item has 'value' or 'used' keys, use them; else use truthiness
                            v = item.get('value') if 'value' in item else (item.get('used') if 'used' in item else item)
                            if not bool(v):
                                result = True
                                break
                        else:
                            if not bool(item):
                                result = True
                                break
                elif isinstance(collection, dict):
                    # Any dict value false
                    result = any(not bool(v) for v in collection.values())
                return result

            anytrue_match = re.match(r'([A-Za-z0-9_.]+)\.AnyTrue$', expression)
            if anytrue_match:
                collection_path = anytrue_match.group(1)
                collection = self._get_by_path(context, collection_path)
                result = False
                if isinstance(collection, list):
                    for item in collection:
                        if isinstance(item, dict):
                            v = item.get('value') if 'value' in item else (item.get('used') if 'used' in item else item)
                            if bool(v):
                                result = True
                                break
                        else:
                            if bool(item):
                                result = True
                                break
                elif isinstance(collection, dict):
                    result = any(bool(v) for v in collection.values())
                return result

            # Handle string.IsNullOrWhitespace(field)
            null_match = re.match(r'string\.IsNullOrWhite?[Ss]pace\((.+)\)', expression)
            if null_match:
                field = null_match.group(1)
                value = self.evaluate_expression(field, context)
                result = not str(value).strip() if value is not None else True
                return result

            # Handle Name.ToUpper().Contains("str")
            contains_match = re.match(r'Name\.ToUpper\(\)\.Contains\("([^"]+)"\)', expression)
            if contains_match:
                substring = contains_match.group(1)
                name = context.get('obj', {}).get('name', '')
                result = substring.upper() in str(name).upper()
                return result

            # Handle Convert.ToInt64(expr) op value
            convert_match = re.match(r'Convert\.ToInt64\((.+)\)\s*([><]=?|==|!=)\s*(\d+)', expression)
            if convert_match:
                inner = convert_match.group(1)
                operator = convert_match.group(2)
                value = int(convert_match.group(3))
                inner_val = self.evaluate_expression(inner, context)
                try:
                    int_val = int(inner_val) if inner_val is not None else 0
                except (ValueError, TypeError):
                    int_val = 0
                if operator == '>':
                    result = int_val > value
                elif operator == '<':
                    result = int_val < value
                elif operator == '>=':
                    result = int_val >= value
                elif operator == '<=':
                    result = int_val <= value
                elif operator == '==':
                    result = int_val == value
                elif operator == '!=':
                    result = int_val != value
                else:
                    result = False
                return result

            # Handle GetAnnotation("name")
            ann_match = re.match(r'GetAnnotation\("([^"]+)"\)', expression)
            if ann_match:
                ann_name = ann_match.group(1)
                result = self.get_annotation(context.get('obj', {}), ann_name)
                return result if result is not None else ""

            # Handle .Any(condition) BEFORE paren reducer
            # to preserve the inner expression for
            # per-item evaluation.
            any_pre = re.match(
                r'([A-Za-z0-9_.]+)\.Any\((.+)\)'
                r'(\s*==\s*(true|false))?$',
                expression,
            )
            if any_pre:
                coll_path = any_pre.group(1)
                inner_expr = any_pre.group(2)
                collection = self._get_by_path(
                    context, coll_path
                )
                if not isinstance(collection, list):
                    any_result = False
                else:
                    any_result = False
                    for item in collection:
                        item_ctx = {
                            **context,
                            'it': item,
                            'current': item,
                        }
                        if self.evaluate_expression(
                            inner_expr, item_ctx
                        ):
                            any_result = True
                            break
                # Handle optional == true/false suffix
                cmp_val = any_pre.group(4)
                if cmp_val == 'false':
                    any_result = not any_result
                # cmp_val == 'true' or None: keep as-is
                return any_result

            # Now reduce simple parenthesis outside of the handled patterns above
            paren_count = 0
            while paren_count < 10:  # Limit iterations
                # Find innermost parentheses that are NOT inside double-quoted strings
                s = expression
                i = 0
                match_span = None
                in_str = False
                while i < len(s):
                    ch = s[i]
                    if ch == '"':
                        in_str = not in_str
                        i += 1
                        continue
                    if not in_str and ch == '(':
                        # find matching ')'
                        depth = 1
                        j = i + 1
                        in_str2 = False
                        while j < len(s):
                            ch2 = s[j]
                            if ch2 == '"':
                                in_str2 = not in_str2
                            elif not in_str2:
                                if ch2 == '(':
                                    depth += 1
                                elif ch2 == ')':
                                    depth -= 1
                                    if depth == 0:
                                        match_span = (i, j)
                                        break
                            j += 1
                        break
                    i += 1
                if not match_span:
                    break
                inner = expression[match_span[0] + 1: match_span[1]]
                inner_result = self.evaluate_expression(inner, context)
                expression = expression[:match_span[0]] + str(inner_result) + expression[match_span[1] + 1:]
                paren_count += 1

            # Handle logical OR
            if ' or ' in expression or ' || ' in expression:
                delimiter = ' or ' if ' or ' in expression else ' || '
                parts = expression.split(delimiter)
                result = any(self.evaluate_expression(p.strip(), context) for p in parts)
                return result

            # Handle logical AND
            if ' and ' in expression or ' && ' in expression:
                delimiter = ' and ' if ' and ' in expression else ' && '
                parts = expression.split(delimiter)
                result = all(self.evaluate_expression(p.strip(), context) for p in parts)
                return result

            # Handle NOT
            if expression.startswith('not ') or expression.startswith('!'):
                result = not self.evaluate_expression(expression.lstrip('not !').strip(), context)
                return result

            # Handle .Any(condition)
            any_match = re.match(r'([A-Za-z0-9_.]+)\.Any\((.*)\)', expression)
            if any_match:
                collection_path = any_match.group(1)
                inner_expr = any_match.group(2)
                collection = self._get_by_path(context, collection_path)
                if not isinstance(collection, list):
                    return False
                for item in collection:
                    item_context = {**context, 'it': item, 'current': item}
                    if self.evaluate_expression(inner_expr, item_context):
                        return True
                return False

            # Handle .Count() or .Count with optional comparison
            count_match = re.match(
                r'([A-Za-z0-9_.]+)\.Count(?:\(\))?'
                r'(?:\s*([><!=]+)\s*(\d+\.?\d*))?$',
                expression,
            )
            if count_match:
                collection_path = count_match.group(1)
                collection = self._get_by_path(
                    context, collection_path
                )
                count_val = (
                    len(collection)
                    if isinstance(collection, list)
                    else 0
                )
                cmp_op = count_match.group(2)
                if cmp_op and count_match.group(3):
                    threshold = float(
                        count_match.group(3)
                    )
                    if cmp_op == '>':
                        result = count_val > threshold
                    elif cmp_op == '<':
                        result = count_val < threshold
                    elif cmp_op == '>=':
                        result = count_val >= threshold
                    elif cmp_op == '<=':
                        result = count_val <= threshold
                    elif cmp_op in ('==', '='):
                        result = count_val == threshold
                    elif cmp_op in ('!=', '<>'):
                        result = count_val != threshold
                    else:
                        result = count_val
                else:
                    result = count_val
                return result

            # Handle .Where(condition).Count()
            where_count_match = re.match(r'([A-Za-z0-9_.]+)\.Where\((.*)\)\.Count\(\)', expression)
            if where_count_match:
                collection_path = where_count_match.group(1)
                inner_expr = where_count_match.group(2)
                collection = self._get_by_path(context, collection_path)
                if not isinstance(collection, list):
                    return 0
                filtered = []
                for item in collection:
                    if self.evaluate_expression(inner_expr, {**context, 'it': item, 'current': item}):
                        filtered.append(item)
                return len(filtered)

            # Handle simple property == value (support dotted left side)
            prop_match = re.match(r'([A-Za-z0-9_.]+)\s*(==|<>|!=)\s*("([^"]+)"|null|true|false|\d+)$', expression)
            if prop_match:
                prop = prop_match.group(1)
                operator = prop_match.group(2)
                value_str = prop_match.group(3).strip('"')
                if value_str == 'true':
                    value = True
                elif value_str == 'false':
                    value = False
                elif value_str == 'null':
                    value = None
                else:
                    value = value_str

                prop_value = self.evaluate_expression(prop, context)
                if operator in ['<>', '!=']:
                    result = prop_value != value
                else:
                    result = prop_value == value
                return result

            # Handle numeric comparisons: prop > N, prop < N, etc.
            num_cmp = re.match(
                r'([A-Za-z0-9_.]+)\s*([><]=?)\s*'
                r'(\d+\.?\d*)$',
                expression,
            )
            if num_cmp:
                prop = num_cmp.group(1)
                operator = num_cmp.group(2)
                threshold = float(num_cmp.group(3))
                prop_value = self.evaluate_expression(
                    prop, context
                )
                try:
                    num_val = (
                        float(prop_value)
                        if prop_value is not None
                        else 0
                    )
                except (ValueError, TypeError):
                    num_val = 0
                if operator == '>':
                    result = num_val > threshold
                elif operator == '<':
                    result = num_val < threshold
                elif operator == '>=':
                    result = num_val >= threshold
                elif operator == '<=':
                    result = num_val <= threshold
                else:
                    result = False
                return result

            # Handle property-to-property comparison (e.g., Name == current.Name)
            prop_prop_match = re.match(r'([A-Za-z0-9_.]+)\s*(==|!=)\s*([A-Za-z0-9_.]+)$', expression)
            if prop_prop_match:
                left = prop_prop_match.group(1)
                operator = prop_prop_match.group(2)
                right = prop_prop_match.group(3)
                lv = self.evaluate_expression(left, context)
                rv = self.evaluate_expression(right, context)
                if operator == '==':
                    result = lv == rv
                else:
                    result = lv != rv
                return result

            # Handle math expressions like (a + b) / Math.Max(c,d) > e
            math_match = re.match(r'\((.+)\)\s*/\s*Math\.Max\((.+),(\d+)\)\s*>\s*(\d+\.?\d*)', expression)
            if math_match:
                numerator_expr = math_match.group(1)
                max_expr = math_match.group(2)
                min_val = int(math_match.group(3))
                threshold = float(math_match.group(4))
                try:
                    numerator = float(self.evaluate_expression(numerator_expr, context) or 0)
                    max_val_result = float(self.evaluate_expression(max_expr, context) or 0)
                    max_val = max(max_val_result, min_val)
                    result = (numerator / max_val) > threshold if max_val > 0 else False
                except (ValueError, TypeError, ZeroDivisionError):
                    result = False
                return result

            # Handle addition
            if '+' in expression:
                parts = expression.split('+')
                try:
                    result = sum(float(self.evaluate_expression(p.strip(), context) or 0) for p in parts if p.strip())
                except (ValueError, TypeError):
                    result = 0
                return result

            # Handle property access (support dotted paths)
            if re.match(r'^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$', expression):
                result = self._get_by_path(context, expression)
                return result

            # If unhandled, log and return False
            logger.debug(f"Unhandled expression: {expression[:100]}")
            return False

        except Exception as e:
            logger.warning(f"Expression evaluation error: {e} for: {expression[:100]}")
            return False
        finally:
            self._eval_depth -= 1

    def _get_by_path(self, context: Dict, path: str) -> Any:
        """Get value by dot path.

        Important: include the first segment when resolving properties like
        DataCategory (previously skipped), to avoid returning the whole object
        instead of the property's value. This ensures expressions such as
        `DataCategory == "Time"` evaluate correctly.
        """
        if not path:
            return None

        parts = path.split('.')

        # Determine root object and starting index
        first = parts[0]
        if first == 'Model':
            current = context.get('model', {})
            idx = 1
        elif first in (
            'current', 'it', 'obj', 'table',
            'model', 'outerIt',
        ):
            current = context.get(first, context.get(first.lower(), {}))
            idx = 1
        else:
            # Default to the current object context
            current = context.get('current', context.get('obj', context.get('table', {})))
            idx = 0  # include the first segment as a property lookup

        # Navigate path from idx (including first property when idx == 0)
        for i in range(idx, len(parts)):
            part = parts[i]
            index = context.get('index') or {}
            if part == 'AllColumns':
                current = index.get('all_columns') or []
                continue
            if part == 'AllMeasures':
                current = index.get('all_measures') or []
                continue
            if part == 'AllCalculationItems':
                current = index.get('all_calc_items') or []
                continue
            if part == 'AllRelationships':
                current = (
                    index.get('relationships') or []
                )
                continue
            if part == 'Columns':
                # Table-level column list
                if isinstance(current, dict):
                    current = (
                        current.get('columns') or []
                    )
                continue
            if part == 'Measures':
                # Table-level measure list
                if isinstance(current, dict):
                    current = (
                        current.get('measures') or []
                    )
                continue
            if part == 'RowLevelSecurity':
                tbl = context.get('table', {})
                current = tbl.get('roles', [])
                continue
            # Relationship property aliases
            if part == 'FromTable':
                if isinstance(current, dict):
                    current = (
                        current.get('fromTable')
                        or current.get('FromTable', '')
                    )
                continue
            if part == 'ToTable':
                if isinstance(current, dict):
                    current = (
                        current.get('toTable')
                        or current.get('ToTable', '')
                    )
                continue

            if isinstance(current, dict):
                # Case-insensitive key access, try common Name vs name
                if part in current:
                    current = current.get(part)
                elif part.lower() in current:
                    current = current.get(part.lower())
                else:
                    # Try typical TitleCase to camelCase mapping
                    lowered = part[:1].lower() + part[1:]
                    current = current.get(lowered, None)
            else:
                current = None

            if current is None:
                break

        return current

    def get_annotation(self, obj: Dict, name: str) -> Optional[str]:
        """Get annotation value from object"""
        if not obj or not isinstance(obj, dict):
            return None
        annotations = obj.get('annotations', [])
        for a in annotations:
            if isinstance(a, dict) and a.get('name') == name:
                return a.get('value')
        return None

    def check_required_annotations(self, model: Dict) -> List[str]:
        """Check for missing required annotations"""
        required = set()
        for rule in self.rules:
            if 'GetAnnotation' in rule.expression:
                matches = re.findall(r'GetAnnotation\("([^"]+)"\)', rule.expression)
                required.update(matches)
        
        missing = []
        for table in model.get('tables', []):
            for column in table.get('columns', []):
                annotations = {a.get('name') for a in column.get('annotations', []) if isinstance(a, dict)}
                for req in required:
                    if req not in annotations:
                        missing.append(f"{req} missing in {table.get('name', 'unknown')}.{column.get('name', 'unknown')}")
        return list(set(missing))[:10]  # Limit to first 10

    def analyze_model(self, tmsl_json: Union[str, Dict]) -> List[BPAViolation]:
        """Analyze model against BPA rules"""
        # Reset violations at the start of each analysis run
        self.violations = []
        self._run_notes = []

        if isinstance(tmsl_json, str):
            try:
                tmsl_model = json.loads(tmsl_json)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid TMSL JSON: {e}")
                return []
        else:
            tmsl_model = tmsl_json
            
        # Resolve model from common shapes:
        # - create.database.model
        # - { model: {...} }
        # - model object at root (has 'tables' etc.)
        model = (
            tmsl_model.get('create', {}).get('database', {}).get('model', {})
            or tmsl_model.get('model', {})
        )
        if not model and isinstance(tmsl_model, dict) and (
            'tables' in tmsl_model or 'measures' in tmsl_model or 'relationships' in tmsl_model
        ):
            model = tmsl_model
        
        if not model:
            logger.warning("No model found in TMSL structure")
            return []
        
        # Build index and check for missing annotations
        index = self._build_model_index(model)
        missing_ann = self.check_required_annotations(model)
        if missing_ann:
            logger.warning(f"Missing annotations detected: {len(missing_ann)} items")
            self.violations.append(BPAViolation(
                rule_id="MISSING_ANNOTATIONS",
                rule_name="Missing required annotations",
                category="Error Prevention",
                severity=BPASeverity.WARNING,
                description="Some rules require Vertipaq annotations. Run the Vertipaq script to add them.",
                object_type="Model",
                object_name="Model",
                details=", ".join(missing_ann[:5])  # Show first 5
            ))

        start_time = time.perf_counter()
        # Generous default budget for full analyze
        max_seconds = 60.0
        for rule in self.rules:
            try:
                self._eval_depth = 0  # Reset depth counter for each rule
                self._analyze_rule(rule, model, index)
                if (time.perf_counter() - start_time) > max_seconds:
                    self._run_notes.append(f"BPA analyze_model timed out after {int(max_seconds)}s; results may be partial")
                    break
            except Exception as e:
                logger.error(f"Rule {rule.id} evaluation failed: {str(e)}")
                # Don't add error violations for failed rules - just skip them

        return self.violations

    def analyze_model_fast(self, tmsl_json: Union[str, Dict], cfg: Optional[Dict[str, Any]] = None) -> List[BPAViolation]:
        """Faster analysis with configurable sampling/filters.

        cfg keys (optional):
          - max_rules: int (limit number of rules evaluated)
          - severity_at_least: 'INFO'|'WARNING'|'ERROR' (filter rules below threshold)
          - include_categories: list[str] (only evaluate these categories)
          - max_tables: int (limit number of tables processed)
        """
        if isinstance(tmsl_json, str):
            try:
                tmsl_model = json.loads(tmsl_json)
            except json.JSONDecodeError:
                return []
        else:
            tmsl_model = tmsl_json

        model = (
            tmsl_model.get('create', {}).get('database', {}).get('model', {})
            or tmsl_model.get('model', {})
        )
        if not model and isinstance(tmsl_model, dict) and (
            'tables' in tmsl_model or 'measures' in tmsl_model or 'relationships' in tmsl_model
        ):
            model = tmsl_model
        if not model:
            return []

        cfg = cfg or {}
        # Prepare filtered rules list
        rules = list(self.rules)
        # severity filter
        sev = str(cfg.get('severity_at_least', '')).upper()
        level = {'INFO': 1, 'WARNING': 2, 'ERROR': 3}.get(sev)
        if level:
            rules = [r for r in rules if int(r.severity) >= level]
        # category filter
        cats = cfg.get('include_categories') or []
        if isinstance(cats, list) and cats:
            lc = set(str(c).lower() for c in cats)
            rules = [r for r in rules if str(r.category).lower() in lc]
        # limit number of rules
        try:
            mr_val = cfg.get('max_rules')
            mr = int(mr_val) if mr_val is not None and str(mr_val).strip() != '' else None
        except Exception:
            mr = None
        if mr and mr > 0 and len(rules) > mr:
            rules = rules[:mr]

        # Optionally limit number of tables (lightweight sampling)
        try:
            mt_val = cfg.get('max_tables')
            mt = int(mt_val) if mt_val is not None and str(mt_val).strip() != '' else None
        except Exception:
            mt = None
        if mt and mt > 0 and isinstance(model.get('tables'), list) and len(model['tables']) > mt:
            model = dict(model)
            model['tables'] = model['tables'][:mt]

        # Evaluate filtered/limited rule set
        self.violations = []
        self._run_notes = []
        # Capture config for use inside per-scope checks
        self._fast_cfg = dict(cfg or {})
        index = self._build_model_index(model)
        # Time budgets
        try:
            max_seconds = float(cfg.get('max_seconds', 20))
        except Exception:
            max_seconds = 20.0
        try:
            per_rule_max_ms = float(cfg.get('per_rule_max_ms', 150))
        except Exception:
            per_rule_max_ms = 150.0
        start_time = time.perf_counter()
        evaluated_rules = 0
        for rule in rules:
            try:
                self._eval_depth = 0
                rule_start = time.perf_counter()
                self._analyze_rule(rule, model, index)
                evaluated_rules += 1
                # Check per rule budget
                elapsed_ms = (time.perf_counter() - rule_start) * 1000.0
                if elapsed_ms > per_rule_max_ms:
                    self._run_notes.append(f"Rule {rule.id} exceeded {int(per_rule_max_ms)}ms ({int(elapsed_ms)}ms)")
                # Check global budget
                if (time.perf_counter() - start_time) > max_seconds:
                    self._run_notes.append(f"BPA fast mode budget reached after {evaluated_rules} rules and {int(max_seconds)}s; results truncated")
                    break
            except Exception:
                pass
        return self.violations

    def get_violations_summary(self) -> Dict[str, int]:
        """Return a summary of violations by severity and category"""
        summary = {
            "total": len(self.violations),
            "by_severity": {"INFO": 0, "WARNING": 0, "ERROR": 0},
            "by_category": {}
        }
        for violation in self.violations:
            severity = BPASeverity(violation.severity).name
            summary["by_severity"][severity] += 1
            category = violation.category
            summary["by_category"][category] = summary["by_category"].get(category, 0) + 1
        return summary

    def get_violations_by_category(
        self,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Return violations grouped by category.

        Returns a dict mapping category names to lists of
        violation dicts, with a ``_categories`` key listing
        all known category names (even if empty).
        """
        known_categories = [
            "DAX Expressions",
            "Naming",
            "Formatting",
            "Relationships",
            "Calculation Groups",
            "Performance",
            "Maintenance",
            "Metadata",
            "Data Model",
            "Data Types",
            "Time Intelligence",
            "Security",
            "Error Prevention",
        ]

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for v in self.violations:
            cat = v.category or "Uncategorized"
            if cat not in grouped:
                grouped[cat] = []
            grouped[cat].append({
                "rule_id": v.rule_id,
                "rule_name": v.rule_name,
                "severity": BPASeverity(
                    v.severity
                ).name,
                "description": v.description,
                "object_type": v.object_type,
                "object_name": v.object_name,
                "table_name": v.table_name,
                "fix": v.fix_expression,
            })

        # Ensure all known categories appear in output
        for cat in known_categories:
            if cat not in grouped:
                grouped[cat] = []

        # Add discovered categories not in known list
        for cat in list(grouped.keys()):
            if cat not in known_categories:
                known_categories.append(cat)

        # Add metadata
        result: Dict[str, Any] = {
            "_categories": known_categories,
            "_total": len(self.violations),
        }
        result.update(grouped)
        return result

    def get_rule_categories(self) -> List[str]:
        """Return sorted list of unique categories across
        all loaded rules (built-in + custom)."""
        cats = sorted({r.category for r in self.rules})
        return cats

    def _analyze_rule(self, rule: BPARule, model: Dict, index: Optional[Dict[str, Any]] = None) -> None:
        """Analyze a single rule against the model"""
        if "Table" in rule.scope or "CalculatedTable" in rule.scope:
            self._check_table_rule(rule, model, index)
        if any(s in rule.scope for s in ["DataColumn", "CalculatedColumn", "CalculatedTableColumn"]):
            self._check_column_rule(rule, model, rule.scope, index)
        if "Measure" in rule.scope:
            self._check_measure_rule(rule, model, index)
        if "Model" in rule.scope:
            self._check_model_rule(rule, model, index)
        if "Hierarchy" in rule.scope:
            self._check_hierarchy_rule(rule, model, index)
        if "CalculationGroup" in rule.scope:
            self._check_calculation_group_rule(rule, model, index)
        if "Relationship" in rule.scope:
            self._check_relationship_rule(rule, model, index)
        if "Partition" in rule.scope:
            self._check_partition_rule(rule, model, index)

    def _check_table_rule(self, rule: BPARule, model: Dict, index: Optional[Dict[str, Any]] = None) -> None:
        """Check rule against tables"""
        tables = model.get('tables', [])
        for table in tables:
            is_calc = table.get('partitions', [{}])[0].get('source', {}).get('type') == 'calculated'
            if ("Table" in rule.scope and not is_calc) or ("CalculatedTable" in rule.scope and is_calc):
                context = {'obj': table, 'table': table, 'model': model, 'index': index, 'current': table, 'outerIt': table}
                try:
                    if self.evaluate_expression(rule.expression, context):
                        self.violations.append(BPAViolation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            category=rule.category,
                            severity=rule.severity,
                            description=rule.description,
                            object_type="CalculatedTable" if is_calc else "Table",
                            object_name=table.get('name', 'unknown')
                        ))
                except Exception as e:
                    logger.debug(f"Error checking table rule {rule.id}: {e}")

    def _check_column_rule(self, rule: BPARule, model: Dict, scope: List[str], index: Optional[Dict[str, Any]] = None) -> None:
        """Check rule against columns"""
        tables = model.get('tables', [])
        # Apply fast-mode limits if present
        max_items = None
        per_rule_ms = None
        if self._fast_cfg:
            try:
                max_items = int(self._fast_cfg.get('max_columns_per_rule') or self._fast_cfg.get('max_items_per_rule') or 0)
            except Exception:
                max_items = None
            try:
                per_rule_ms = float(self._fast_cfg.get('per_rule_max_ms') or 0)
            except Exception:
                per_rule_ms = None
        evaluated = 0
        rule_start = time.perf_counter()
        for table in tables:
            columns = table.get('columns', [])
            for column in columns:
                column_type = column.get('type', 'DataColumn')
                if column_type in scope or 'DataColumn' in scope:
                    context = {'obj': column, 'table': table, 'model': model, 'index': index, 'current': column, 'outerIt': column}
                    try:
                        if self.evaluate_expression(rule.expression, context):
                            self.violations.append(BPAViolation(
                                rule_id=rule.id,
                                rule_name=rule.name,
                                category=rule.category,
                                severity=rule.severity,
                                description=rule.description,
                                object_type=column_type,
                                object_name=column.get('name', 'unknown'),
                                table_name=table.get('name', 'unknown'),
                                fix_expression=rule.fix_expression
                            ))
                    except Exception as e:
                        logger.debug(f"Error checking column rule {rule.id}: {e}")
                    evaluated += 1
                    # Enforce fast-mode iteration/time budgets
                    if max_items and evaluated >= max_items:
                        self._run_notes.append(f"Rule {rule.id} truncated after {evaluated} column evaluations")
                        return
                    if per_rule_ms and ((time.perf_counter() - rule_start) * 1000.0) > per_rule_ms:
                        self._run_notes.append(f"Rule {rule.id} truncated due to per-rule time budget ({int(per_rule_ms)}ms)")
                        return

    def _check_measure_rule(self, rule: BPARule, model: Dict, index: Optional[Dict[str, Any]] = None) -> None:
        """Check rule against measures"""
        tables = model.get('tables', [])
        max_items = None
        per_rule_ms = None
        if self._fast_cfg:
            try:
                max_items = int(self._fast_cfg.get('max_measures_per_rule') or self._fast_cfg.get('max_items_per_rule') or 0)
            except Exception:
                max_items = None
            try:
                per_rule_ms = float(self._fast_cfg.get('per_rule_max_ms') or 0)
            except Exception:
                per_rule_ms = None
        evaluated = 0
        rule_start = time.perf_counter()
        for table in tables:
            measures = table.get('measures', [])
            for measure in measures:
                context = {'obj': measure, 'table': table, 'model': model, 'index': index, 'current': measure, 'outerIt': measure}
                try:
                    if self.evaluate_expression(rule.expression, context):
                        self.violations.append(BPAViolation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            category=rule.category,
                            severity=rule.severity,
                            description=rule.description,
                            object_type="Measure",
                            object_name=measure.get('name', 'unknown'),
                            table_name=table.get('name', 'unknown'),
                            fix_expression=rule.fix_expression
                        ))
                except Exception as e:
                    logger.debug(f"Error checking measure rule {rule.id}: {e}")
                evaluated += 1
                if max_items and evaluated >= max_items:
                    self._run_notes.append(f"Rule {rule.id} truncated after {evaluated} measure evaluations")
                    return
                if per_rule_ms and ((time.perf_counter() - rule_start) * 1000.0) > per_rule_ms:
                    self._run_notes.append(f"Rule {rule.id} truncated due to per-rule time budget ({int(per_rule_ms)}ms)")
                    return

    def _check_model_rule(self, rule: BPARule, model: Dict, index: Optional[Dict[str, Any]] = None) -> None:
        """Check rule against model"""
        context = {'obj': model, 'model': model, 'index': index, 'current': model, 'outerIt': model}
        try:
            if self.evaluate_expression(rule.expression, context):
                self.violations.append(BPAViolation(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    category=rule.category,
                    severity=rule.severity,
                    description=rule.description,
                    object_type="Model",
                    object_name="Model"
                ))
        except Exception as e:
            logger.debug(f"Error checking model rule {rule.id}: {e}")

    def _check_hierarchy_rule(self, rule: BPARule, model: Dict, index: Optional[Dict[str, Any]] = None) -> None:
        """Check rule against hierarchies"""
        tables = model.get('tables', [])
        for table in tables:
            hierarchies = table.get('hierarchies', [])
            for hierarchy in hierarchies:
                context = {'obj': hierarchy, 'table': table, 'model': model, 'index': index, 'current': hierarchy, 'outerIt': hierarchy}
                try:
                    if self.evaluate_expression(rule.expression, context):
                        self.violations.append(BPAViolation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            category=rule.category,
                            severity=rule.severity,
                            description=rule.description,
                            object_type="Hierarchy",
                            object_name=hierarchy.get('name', 'unknown'),
                            table_name=table.get('name', 'unknown')
                        ))
                except Exception as e:
                    logger.debug(f"Error checking hierarchy rule {rule.id}: {e}")

    def _check_calculation_group_rule(self, rule: BPARule, model: Dict, index: Optional[Dict[str, Any]] = None) -> None:
        """Check rule against calculation groups"""
        tables = model.get('tables', [])
        for table in tables:
            calc_group = table.get('calculationGroup', {})
            if calc_group:
                context = {'obj': calc_group, 'table': table, 'model': model, 'index': index, 'current': calc_group, 'outerIt': calc_group}
                try:
                    if self.evaluate_expression(rule.expression, context):
                        self.violations.append(BPAViolation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            category=rule.category,
                            severity=rule.severity,
                            description=rule.description,
                            object_type="CalculationGroup",
                            object_name=calc_group.get('name', 'unknown'),
                            table_name=table.get('name', 'unknown')
                        ))
                except Exception as e:
                    logger.debug(f"Error checking calc group rule {rule.id}: {e}")

    def _check_relationship_rule(self, rule: BPARule, model: Dict, index: Optional[Dict[str, Any]] = None) -> None:
        """Check rule against relationships"""
        relationships = model.get('relationships', [])
        max_items = None
        per_rule_ms = None
        if self._fast_cfg:
            try:
                max_items = int(self._fast_cfg.get('max_relationships_per_rule') or self._fast_cfg.get('max_items_per_rule') or 0)
            except Exception:
                max_items = None
            try:
                per_rule_ms = float(self._fast_cfg.get('per_rule_max_ms') or 0)
            except Exception:
                per_rule_ms = None
        evaluated = 0
        rule_start = time.perf_counter()
        for relationship in relationships:
            context = {'obj': relationship, 'model': model, 'index': index, 'current': relationship, 'outerIt': relationship}
            try:
                if self.evaluate_expression(rule.expression, context):
                    self.violations.append(BPAViolation(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        category=rule.category,
                        severity=rule.severity,
                        description=rule.description,
                        object_type="Relationship",
                        object_name=f"{relationship.get('fromTable', 'unknown')}.{relationship.get('fromColumn', 'unknown')}"
                    ))
            except Exception as e:
                logger.debug(f"Error checking relationship rule {rule.id}: {e}")
            evaluated += 1
            if max_items and evaluated >= max_items:
                self._run_notes.append(f"Rule {rule.id} truncated after {evaluated} relationship evaluations")
                return
            if per_rule_ms and ((time.perf_counter() - rule_start) * 1000.0) > per_rule_ms:
                self._run_notes.append(f"Rule {rule.id} truncated due to per-rule time budget ({int(per_rule_ms)}ms)")
                return

    def _check_partition_rule(self, rule: BPARule, model: Dict, index: Optional[Dict[str, Any]] = None) -> None:
        """Check rule against partitions"""
        tables = model.get('tables', [])
        for table in tables:
            partitions = table.get('partitions', [])
            for partition in partitions:
                context = {'obj': partition, 'table': table, 'model': model, 'index': index, 'current': partition, 'outerIt': partition}
                try:
                    if self.evaluate_expression(rule.expression, context):
                        self.violations.append(BPAViolation(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            category=rule.category,
                            severity=rule.severity,
                            description=rule.description,
                            object_type="Partition",
                            object_name=partition.get('name', 'unknown'),
                            table_name=table.get('name', 'unknown')
                        ))
                except Exception as e:
                    logger.debug(f"Error checking partition rule {rule.id}: {e}")