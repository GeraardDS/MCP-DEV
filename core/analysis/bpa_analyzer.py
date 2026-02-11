"""
Best Practice Analyzer for Semantic Models
Analyzes TMSL models against a comprehensive set of best practice rules
"""

import json
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
            # Extract the object being evaluated (measure, column, table, etc.)
            obj_type = context.get('_ObjectType', '')
            obj_name = context.get('Name', context.get('name', ''))
            table_name = context.get('Table', context.get('table', ''))

            # Create a minimal frozen representation
            # We don't freeze the entire context (would be too heavy), just the identifying parts
            frozen = (
                obj_type,
                str(obj_name),
                str(table_name),
                # Add a few other commonly accessed properties that affect evaluation
                str(context.get('Expression', context.get('expression', ''))),
                str(context.get('IsHidden', context.get('isHidden', ''))),
                str(context.get('DataType', context.get('dataType', '')))
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
                self._eval_depth -= 1
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
                            self._eval_depth -= 1
                            return str(c.get('name'))
                # Fallback to returning the literal reference string
                self._eval_depth -= 1
                return expression

            # IMPORTANT: Handle certain function patterns first to avoid corrupting
            # their arguments with the generic parentheses reducer.

            # Handle RegEx.IsMatch(field, "pattern") optionally with third arg
            regex_match = re.match(r'RegEx\.IsMatch\(([^,]+),\s*"([^"]+)"(,.*)?\)', expression)
            if regex_match:
                field = regex_match.group(1).strip()
                pattern = regex_match.group(2)
                value = self.evaluate_expression(field, context)
                flags = re.IGNORECASE if '(?i)' in pattern else 0
                pattern = pattern.replace('(?i)', '')
                compiled = self._compile_regex(pattern, flags)
                result = bool(compiled.search(str(value) if value is not None else ''))
                self._eval_depth -= 1
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
                self._eval_depth -= 1
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
                self._eval_depth -= 1
                return result

            # Handle string.IsNullOrWhitespace(field)
            null_match = re.match(r'string\.IsNullOrWhite?[Ss]pace\((.+)\)', expression)
            if null_match:
                field = null_match.group(1)
                value = self.evaluate_expression(field, context)
                result = not str(value).strip() if value is not None else True
                self._eval_depth -= 1
                return result

            # Handle Name.ToUpper().Contains("str")
            contains_match = re.match(r'Name\.ToUpper\(\)\.Contains\("([^"]+)"\)', expression)
            if contains_match:
                substring = contains_match.group(1)
                name = context.get('obj', {}).get('name', '')
                result = substring.upper() in str(name).upper()
                self._eval_depth -= 1
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
                self._eval_depth -= 1
                return result

            # Handle GetAnnotation("name")
            ann_match = re.match(r'GetAnnotation\("([^"]+)"\)', expression)
            if ann_match:
                ann_name = ann_match.group(1)
                result = self.get_annotation(context.get('obj', {}), ann_name)
                self._eval_depth -= 1
                return result if result is not None else ""

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
                self._eval_depth -= 1
                return result

            # Handle logical AND
            if ' and ' in expression or ' && ' in expression:
                delimiter = ' and ' if ' and ' in expression else ' && '
                parts = expression.split(delimiter)
                result = all(self.evaluate_expression(p.strip(), context) for p in parts)
                self._eval_depth -= 1
                return result

            # Handle NOT
            if expression.startswith('not ') or expression.startswith('!'):
                result = not self.evaluate_expression(expression.lstrip('not !').strip(), context)
                self._eval_depth -= 1
                return result

            # Handle .Any(condition)
            any_match = re.match(r'([A-Za-z0-9_.]+)\.Any\((.*)\)', expression)
            if any_match:
                collection_path = any_match.group(1)
                inner_expr = any_match.group(2)
                collection = self._get_by_path(context, collection_path)
                if not isinstance(collection, list):
                    self._eval_depth -= 1
                    return False
                for item in collection:
                    item_context = {**context, 'it': item, 'current': item}
                    if self.evaluate_expression(inner_expr, item_context):
                        self._eval_depth -= 1
                        return True
                self._eval_depth -= 1
                return False

            # Handle .Count() or .Count
            count_match = re.match(r'([A-Za-z0-9_.]+)\.Count(\(\))?', expression)
            if count_match:
                collection_path = count_match.group(1)
                collection = self._get_by_path(context, collection_path)
                result = len(collection) if isinstance(collection, list) else 0
                self._eval_depth -= 1
                return result

            # Handle .Where(condition).Count()
            where_count_match = re.match(r'([A-Za-z0-9_.]+)\.Where\((.*)\)\.Count\(\)', expression)
            if where_count_match:
                collection_path = where_count_match.group(1)
                inner_expr = where_count_match.group(2)
                collection = self._get_by_path(context, collection_path)
                if not isinstance(collection, list):
                    self._eval_depth -= 1
                    return 0
                filtered = []
                for item in collection:
                    if self.evaluate_expression(inner_expr, {**context, 'it': item, 'current': item}):
                        filtered.append(item)
                self._eval_depth -= 1
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
                self._eval_depth -= 1
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
                self._eval_depth -= 1
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
                self._eval_depth -= 1
                return result

            # Handle addition
            if '+' in expression:
                parts = expression.split('+')
                try:
                    result = sum(float(self.evaluate_expression(p.strip(), context) or 0) for p in parts if p.strip())
                except (ValueError, TypeError):
                    result = 0
                self._eval_depth -= 1
                return result

            # Handle property access (support dotted paths)
            if re.match(r'^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$', expression):
                result = self._get_by_path(context, expression)
                self._eval_depth -= 1
                return result

            # If unhandled, log and return False
            logger.debug(f"Unhandled expression: {expression[:100]}")
            self._eval_depth -= 1
            return False

        except Exception as e:
            logger.warning(f"Expression evaluation error: {e} for: {expression[:100]}")
            self._eval_depth -= 1
            return False

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
        elif first in ('current', 'it', 'obj', 'table', 'model'):
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
            if part == 'RowLevelSecurity':
                current = context.get('table', {}).get('roles', [])
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