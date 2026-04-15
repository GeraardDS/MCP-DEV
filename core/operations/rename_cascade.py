"""
DAX Reference Cascade for TOM Rename Operations

TOM/AMO does NOT auto-cascade name changes through DAX expressions.
When renaming a measure, column, or table, all DAX string references
(measure expressions, calculated columns, KPIs, RLS, detail rows,
calculation items, field parameters) must be updated manually.

Structural object references (relationships, sort-by-column, hierarchy
levels, perspectives) DO survive column/table renames automatically
in TOM because they store object pointers, not name strings.
"""

import re
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def _get_first_partition(table):
    """
    Get the first partition from a TOM table.
    pythonnet's PartitionCollection indexer only accepts string keys,
    so we must iterate rather than use [0].
    """
    try:
        if table.Partitions.Count == 0:
            return None
        for p in table.Partitions:
            return p
    except Exception:
        return None


def _get_partition_expression(partition) -> Optional[str]:
    """Safely get partition source expression (only exists on CalculatedPartitionSource)."""
    try:
        source = partition.Source
        if source is not None and hasattr(source, 'Expression'):
            return source.Expression
    except Exception:
        pass
    return None


def _set_partition_expression(partition, expr: str) -> bool:
    """Safely set partition source expression."""
    try:
        partition.Source.Expression = expr
        return True
    except Exception as e:
        logger.error(f"Failed to set partition expression: {e}")
        return False


def cascade_measure_rename(model, old_name: str, new_name: str, table_name: str = '') -> List[str]:
    """
    After renaming a measure, update all DAX expressions that reference [old_name].

    Covers: measure expressions, calculated column expressions, KPI expressions,
    detail rows expressions, calculation item expressions, RLS filter expressions,
    calculated table / field parameter expressions.

    NAMEOF() requires fully-qualified references for names with special characters,
    so we replace NAMEOF([old]) with NAMEOF('Table'[new]) to ensure it always works.

    Args:
        model: TOM model object
        old_name: Previous measure name
        new_name: New measure name
        table_name: Table containing the measure (needed for NAMEOF qualification)

    Returns list of updated object paths for logging.
    """
    # If table_name not provided, find it from the model
    if not table_name:
        for tbl in model.Tables:
            for m in tbl.Measures:
                if m.Name == new_name:
                    table_name = tbl.Name
                    break
            if table_name:
                break

    pattern = re.compile(r'\[' + re.escape(old_name) + r'\]', re.IGNORECASE)
    replacement = f'[{new_name}]'

    # NAMEOF-specific: match NAMEOF( [old] ) or NAMEOF( 'AnyTable'[old] )
    # Replace with fully-qualified NAMEOF('Table'[new]) so special chars always work
    nameof_pattern = re.compile(
        r"NAMEOF\s*\(\s*(?:'[^']*'\s*)?\[" + re.escape(old_name) + r"\]\s*\)",
        re.IGNORECASE
    )
    if table_name:
        nameof_replacement = f"NAMEOF('{table_name}'[{new_name}])"
    else:
        nameof_replacement = f"NAMEOF([{new_name}])"

    return _apply_bracketed_replacement(model, pattern, replacement, nameof_pattern, nameof_replacement)


def cascade_column_rename(model, table_name: str, old_name: str, new_name: str) -> List[str]:
    """
    After renaming a column, update all DAX expressions that reference 'Table'[old_name]
    or just [old_name] (unqualified).

    Columns can appear as:
      - 'Table Name'[Column Name]  (qualified)
      - [Column Name]              (unqualified, within same table context)
      - TableName[Column Name]     (unquoted table)

    We update BOTH qualified and unqualified forms.

    Returns list of updated object paths for logging.
    """
    # Pattern 1: Qualified reference — 'Table Name'[old_name] or TableName[old_name]
    qualified_pattern = re.compile(
        r"(?:'" + re.escape(table_name) + r"'|" + re.escape(table_name) + r")\[" + re.escape(old_name) + r"\]",
        re.IGNORECASE
    )

    # Pattern 2: Unqualified [old_name]
    unqualified_pattern = re.compile(r'\[' + re.escape(old_name) + r'\]', re.IGNORECASE)

    updated = []

    def _qualified_replacer(match):
        text = match.group(0)
        bracket_start = text.rfind('[')
        return text[:bracket_start] + f'[{new_name}]'

    for tbl in model.Tables:
        for m in tbl.Measures:
            if m.Expression and (qualified_pattern.search(m.Expression) or unqualified_pattern.search(m.Expression)):
                m.Expression = qualified_pattern.sub(_qualified_replacer, m.Expression)
                m.Expression = unqualified_pattern.sub(f'[{new_name}]', m.Expression)
                updated.append(f"'{tbl.Name}'[{m.Name}]")

            # FormatStringDefinition
            if hasattr(m, 'FormatStringDefinition') and m.FormatStringDefinition:
                fsd = m.FormatStringDefinition
                if hasattr(fsd, 'Expression') and fsd.Expression:
                    if qualified_pattern.search(fsd.Expression) or unqualified_pattern.search(fsd.Expression):
                        fsd.Expression = qualified_pattern.sub(_qualified_replacer, fsd.Expression)
                        fsd.Expression = unqualified_pattern.sub(f'[{new_name}]', fsd.Expression)
                        updated.append(f"'{tbl.Name}'[{m.Name}] (format string)")

            # Detail rows expression
            if hasattr(m, 'DetailRowsDefinition') and m.DetailRowsDefinition:
                drd = m.DetailRowsDefinition
                if hasattr(drd, 'Expression') and drd.Expression:
                    if qualified_pattern.search(drd.Expression) or unqualified_pattern.search(drd.Expression):
                        drd.Expression = qualified_pattern.sub(_qualified_replacer, drd.Expression)
                        drd.Expression = unqualified_pattern.sub(f'[{new_name}]', drd.Expression)
                        updated.append(f"'{tbl.Name}'[{m.Name}] (detail rows)")

            # KPI expressions
            if hasattr(m, 'KPI') and m.KPI:
                kpi = m.KPI
                for attr in ('TargetExpression', 'StatusExpression', 'TrendExpression'):
                    expr = getattr(kpi, attr, None)
                    if expr and (qualified_pattern.search(expr) or unqualified_pattern.search(expr)):
                        expr = qualified_pattern.sub(_qualified_replacer, expr)
                        expr = unqualified_pattern.sub(f'[{new_name}]', expr)
                        setattr(kpi, attr, expr)
                        updated.append(f"'{tbl.Name}'[{m.Name}] (KPI {attr})")

        # Calculated column expressions
        for col in tbl.Columns:
            if hasattr(col, 'Expression') and col.Expression:
                if qualified_pattern.search(col.Expression) or unqualified_pattern.search(col.Expression):
                    col.Expression = qualified_pattern.sub(_qualified_replacer, col.Expression)
                    col.Expression = unqualified_pattern.sub(f'[{new_name}]', col.Expression)
                    updated.append(f"'{tbl.Name}'[{col.Name}] (calc column)")

    # Calculated table / field parameter expressions (partition source)
    updated.extend(_cascade_partitions(model, qualified_pattern, _qualified_replacer, unqualified_pattern, f'[{new_name}]'))

    # Calculation items
    updated.extend(_cascade_calculation_items(model, qualified_pattern, _qualified_replacer, unqualified_pattern, f'[{new_name}]'))

    # RLS filter expressions
    updated.extend(_cascade_rls(model, qualified_pattern, _qualified_replacer, unqualified_pattern, f'[{new_name}]'))

    return updated


def cascade_table_rename(model, old_name: str, new_name: str) -> List[str]:
    """
    After renaming a table, update all DAX expressions that reference 'old_name'
    or old_name (unquoted) as a table qualifier.

    Returns list of updated object paths for logging.
    """
    quoted_pattern = re.compile(r"'" + re.escape(old_name) + r"'", re.IGNORECASE)
    quoted_replacement = f"'{new_name}'"

    unquoted_pattern = None
    unquoted_replacement = None
    if ' ' not in old_name:
        unquoted_pattern = re.compile(
            r'(?<![\'"\w])' + re.escape(old_name) + r'(?=\[)',
            re.IGNORECASE
        )
        unquoted_replacement = new_name

    updated = []

    for tbl in model.Tables:
        for m in tbl.Measures:
            changed = False
            if m.Expression:
                new_expr = quoted_pattern.sub(quoted_replacement, m.Expression)
                if unquoted_pattern:
                    new_expr = unquoted_pattern.sub(unquoted_replacement, new_expr)
                if new_expr != m.Expression:
                    m.Expression = new_expr
                    changed = True

            # FormatStringDefinition
            if hasattr(m, 'FormatStringDefinition') and m.FormatStringDefinition:
                fsd = m.FormatStringDefinition
                if hasattr(fsd, 'Expression') and fsd.Expression:
                    new_expr = quoted_pattern.sub(quoted_replacement, fsd.Expression)
                    if unquoted_pattern:
                        new_expr = unquoted_pattern.sub(unquoted_replacement, new_expr)
                    if new_expr != fsd.Expression:
                        fsd.Expression = new_expr
                        changed = True

            # Detail rows
            if hasattr(m, 'DetailRowsDefinition') and m.DetailRowsDefinition:
                drd = m.DetailRowsDefinition
                if hasattr(drd, 'Expression') and drd.Expression:
                    new_expr = quoted_pattern.sub(quoted_replacement, drd.Expression)
                    if unquoted_pattern:
                        new_expr = unquoted_pattern.sub(unquoted_replacement, new_expr)
                    if new_expr != drd.Expression:
                        drd.Expression = new_expr
                        changed = True

            # KPI
            if hasattr(m, 'KPI') and m.KPI:
                kpi = m.KPI
                for attr in ('TargetExpression', 'StatusExpression', 'TrendExpression'):
                    expr = getattr(kpi, attr, None)
                    if expr:
                        new_expr = quoted_pattern.sub(quoted_replacement, expr)
                        if unquoted_pattern:
                            new_expr = unquoted_pattern.sub(unquoted_replacement, new_expr)
                        if new_expr != expr:
                            setattr(kpi, attr, new_expr)
                            changed = True

            if changed:
                updated.append(f"'{tbl.Name}'[{m.Name}]")

        # Calc columns
        for col in tbl.Columns:
            if hasattr(col, 'Expression') and col.Expression:
                new_expr = quoted_pattern.sub(quoted_replacement, col.Expression)
                if unquoted_pattern:
                    new_expr = unquoted_pattern.sub(unquoted_replacement, new_expr)
                if new_expr != col.Expression:
                    col.Expression = new_expr
                    updated.append(f"'{tbl.Name}'[{col.Name}] (calc column)")

    # Calculated table / field parameter partition expressions
    _cascade_partitions_simple(model, quoted_pattern, quoted_replacement, unquoted_pattern, unquoted_replacement, updated)

    # Calculation items
    _cascade_calc_items_simple(model, quoted_pattern, quoted_replacement, unquoted_pattern, unquoted_replacement, updated)

    # RLS
    _cascade_rls_simple(model, quoted_pattern, quoted_replacement, unquoted_pattern, unquoted_replacement, updated)

    return updated


def _apply_bracketed_replacement(model, pattern, replacement, nameof_pattern=None, nameof_replacement=None) -> List[str]:
    """
    Apply a [name] pattern replacement across all DAX expression locations in the model.
    Used for measure renames where the reference is always [MeasureName].

    If nameof_pattern/nameof_replacement are provided, NAMEOF() calls are replaced
    first with fully-qualified form before the general bracketed replacement.
    """
    updated = []

    def _replace(expr):
        """Apply NAMEOF-specific replacement first, then general replacement."""
        if nameof_pattern:
            expr = nameof_pattern.sub(nameof_replacement, expr)
        expr = pattern.sub(replacement, expr)
        return expr

    def _has_match(expr):
        return pattern.search(expr) or (nameof_pattern and nameof_pattern.search(expr))

    for tbl in model.Tables:
        for m in tbl.Measures:
            # Main expression
            if m.Expression and _has_match(m.Expression):
                m.Expression = _replace(m.Expression)
                updated.append(f"'{tbl.Name}'[{m.Name}]")

            # FormatStringDefinition (separate DAX expression for dynamic format strings)
            if hasattr(m, 'FormatStringDefinition') and m.FormatStringDefinition:
                fsd = m.FormatStringDefinition
                if hasattr(fsd, 'Expression') and fsd.Expression and _has_match(fsd.Expression):
                    fsd.Expression = _replace(fsd.Expression)
                    updated.append(f"'{tbl.Name}'[{m.Name}] (format string)")

            # Detail rows expression
            if hasattr(m, 'DetailRowsDefinition') and m.DetailRowsDefinition:
                drd = m.DetailRowsDefinition
                if hasattr(drd, 'Expression') and drd.Expression and _has_match(drd.Expression):
                    drd.Expression = _replace(drd.Expression)
                    updated.append(f"'{tbl.Name}'[{m.Name}] (detail rows)")

            # KPI expressions
            if hasattr(m, 'KPI') and m.KPI:
                kpi = m.KPI
                for attr in ('TargetExpression', 'StatusExpression', 'TrendExpression'):
                    expr = getattr(kpi, attr, None)
                    if expr and _has_match(expr):
                        setattr(kpi, attr, _replace(expr))
                        updated.append(f"'{tbl.Name}'[{m.Name}] (KPI {attr})")

        # Calculated column expressions
        for col in tbl.Columns:
            if hasattr(col, 'Expression') and col.Expression and _has_match(col.Expression):
                col.Expression = _replace(col.Expression)
                updated.append(f"'{tbl.Name}'[{col.Name}] (calc column)")

    # Calculated table / field parameter expressions (partition source)
    for tbl in model.Tables:
        partition = _get_first_partition(tbl)
        if partition is None:
            continue
        expr = _get_partition_expression(partition)
        if expr and _has_match(expr):
            new_expr = _replace(expr)
            if _set_partition_expression(partition, new_expr):
                updated.append(f"'{tbl.Name}' (calc table / field parameter)")

    # Calculation items
    for tbl in model.Tables:
        try:
            if not hasattr(tbl, 'CalculationGroup') or not tbl.CalculationGroup:
                continue
            cg = tbl.CalculationGroup
            if not hasattr(cg, 'CalculationItems'):
                continue
            for item in cg.CalculationItems:
                if hasattr(item, 'Expression') and item.Expression and _has_match(item.Expression):
                    item.Expression = _replace(item.Expression)
                    updated.append(f"'{tbl.Name}' calc item '{item.Name}'")
        except Exception:
            pass

    # RLS filter expressions
    for role in model.Roles:
        try:
            for tp in role.TablePermissions:
                if hasattr(tp, 'FilterExpression') and tp.FilterExpression and _has_match(tp.FilterExpression):
                    tp.FilterExpression = _replace(tp.FilterExpression)
                    updated.append(f"Role '{role.Name}' -> '{tp.Table.Name}' (RLS)")
        except Exception:
            pass

    return updated


def _cascade_partitions(model, qualified_pattern, qualified_replacer, unqualified_pattern, unqualified_replacement) -> List[str]:
    """Cascade column rename through calculated table / field parameter partition expressions."""
    updated = []
    for tbl in model.Tables:
        partition = _get_first_partition(tbl)
        if partition is None:
            continue
        expr = _get_partition_expression(partition)
        if not expr:
            continue
        if qualified_pattern.search(expr) or unqualified_pattern.search(expr):
            expr = qualified_pattern.sub(qualified_replacer, expr)
            expr = unqualified_pattern.sub(unqualified_replacement, expr)
            if _set_partition_expression(partition, expr):
                updated.append(f"'{tbl.Name}' (calc table / field parameter)")
    return updated


def _cascade_partitions_simple(model, quoted_pattern, quoted_replacement, unquoted_pattern, unquoted_replacement, updated):
    """Cascade table rename through calculated table / field parameter partition expressions."""
    for tbl in model.Tables:
        partition = _get_first_partition(tbl)
        if partition is None:
            continue
        expr = _get_partition_expression(partition)
        if not expr:
            continue
        new_expr = quoted_pattern.sub(quoted_replacement, expr)
        if unquoted_pattern:
            new_expr = unquoted_pattern.sub(unquoted_replacement, new_expr)
        if new_expr != expr:
            if _set_partition_expression(partition, new_expr):
                updated.append(f"'{tbl.Name}' (calc table / field parameter)")


def _cascade_calculation_items(model, qualified_pattern, qualified_replacer, unqualified_pattern, unqualified_replacement) -> List[str]:
    """Cascade column rename through calculation item expressions."""
    updated = []
    for tbl in model.Tables:
        try:
            if not hasattr(tbl, 'CalculationGroup') or not tbl.CalculationGroup:
                continue
            cg = tbl.CalculationGroup
            if not hasattr(cg, 'CalculationItems'):
                continue
            for item in cg.CalculationItems:
                if hasattr(item, 'Expression') and item.Expression:
                    if qualified_pattern.search(item.Expression) or unqualified_pattern.search(item.Expression):
                        item.Expression = qualified_pattern.sub(qualified_replacer, item.Expression)
                        item.Expression = unqualified_pattern.sub(unqualified_replacement, item.Expression)
                        updated.append(f"'{tbl.Name}' calc item '{item.Name}'")
        except Exception:
            pass
    return updated


def _cascade_rls(model, qualified_pattern, qualified_replacer, unqualified_pattern, unqualified_replacement) -> List[str]:
    """Cascade column rename through RLS filter expressions."""
    updated = []
    for role in model.Roles:
        try:
            for tp in role.TablePermissions:
                if hasattr(tp, 'FilterExpression') and tp.FilterExpression:
                    if qualified_pattern.search(tp.FilterExpression) or unqualified_pattern.search(tp.FilterExpression):
                        tp.FilterExpression = qualified_pattern.sub(qualified_replacer, tp.FilterExpression)
                        tp.FilterExpression = unqualified_pattern.sub(unqualified_replacement, tp.FilterExpression)
                        updated.append(f"Role '{role.Name}' -> '{tp.Table.Name}' (RLS)")
        except Exception:
            pass
    return updated


def _cascade_calc_items_simple(model, quoted_pattern, quoted_replacement, unquoted_pattern, unquoted_replacement, updated):
    """Cascade table rename through calculation item expressions."""
    for tbl in model.Tables:
        try:
            if not hasattr(tbl, 'CalculationGroup') or not tbl.CalculationGroup:
                continue
            cg = tbl.CalculationGroup
            if not hasattr(cg, 'CalculationItems'):
                continue
            for item in cg.CalculationItems:
                if hasattr(item, 'Expression') and item.Expression:
                    new_expr = quoted_pattern.sub(quoted_replacement, item.Expression)
                    if unquoted_pattern:
                        new_expr = unquoted_pattern.sub(unquoted_replacement, new_expr)
                    if new_expr != item.Expression:
                        item.Expression = new_expr
                        updated.append(f"'{tbl.Name}' calc item '{item.Name}'")
        except Exception:
            pass


def _cascade_rls_simple(model, quoted_pattern, quoted_replacement, unquoted_pattern, unquoted_replacement, updated):
    """Cascade table rename through RLS filter expressions."""
    for role in model.Roles:
        try:
            for tp in role.TablePermissions:
                if hasattr(tp, 'FilterExpression') and tp.FilterExpression:
                    new_expr = quoted_pattern.sub(quoted_replacement, tp.FilterExpression)
                    if unquoted_pattern:
                        new_expr = unquoted_pattern.sub(unquoted_replacement, new_expr)
                    if new_expr != tp.FilterExpression:
                        tp.FilterExpression = new_expr
                        updated.append(f"Role '{role.Name}' -> '{tp.Table.Name}' (RLS)")
        except Exception:
            pass
