"""
Filter to DAX Converter

Converts PBIP filter definitions and slicer selections to executable DAX expressions.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TypedValue:
    """
    A value with preserved type information from PBIP literals.

    PBIP stores values with type indicators:
    - 'text'L for strings
    - 123L for integers
    - 123.45D for decimals
    - trueL/falseL for booleans

    This class preserves the original type so we generate correct DAX.
    """

    value: Any  # The actual value
    value_type: str  # 'string', 'integer', 'decimal', 'boolean', 'date', 'unknown'

    def __repr__(self):
        return f"TypedValue({self.value!r}, {self.value_type})"


@dataclass
class FilterExpression:
    """Represents a converted DAX filter expression."""

    dax: str  # The DAX expression (e.g., "'Date'[Year] IN {2024, 2025}")
    source: str  # Where it came from: 'report', 'page', 'visual', 'slicer', 'manual'
    table: str  # Table name
    column: str  # Column name
    condition_type: str  # 'In', 'Comparison', 'Between', 'Not', 'IsBlank', etc.
    values: List[Any]  # The filter values
    original: Dict[str, Any] = field(default_factory=dict)  # Original filter definition
    is_field_parameter: bool = False  # True if this is a field parameter table (has composite keys)
    classification: str = (
        "data"  # Filter classification: 'data', 'field_parameter', 'ui_control', 'unknown'
    )
    has_null_values: bool = False  # True if filter contains null/blank values
    # Composite TREATAS support (multi-column field params: sf Row Drill, sf Slicer 1, etc.)
    composite_columns: Optional[List[str]] = (
        None  # Full 'Table'[Col] refs for all columns; when set, use composite TREATAS
    )
    composite_tuples: Optional[List[List[Any]]] = None  # List of value tuples, one per selected row


# Field parameter table detection patterns
# These tables have composite keys and cause errors when used in filters
# NOTE: Only 'sf ' (slicer field) prefix indicates field parameters.
# The 's ' prefix is for regular selection/disconnected slicer tables (NOT field parameters).
# True field parameters have SystemFlags="2" or contain NAMEOF() in their DAX.
FIELD_PARAMETER_PATTERNS = [
    "sf filter",  # Field parameter filter tables (sf Filter 1, sf Filter X)
    "sf row",  # Row drill field parameters (sf Row Drill)
    "sf slicer",  # Slicer field parameters (sf Slicer 1, sf Slicer X)
    "sf column",  # Column field parameters (sf Column X)
    "sf period",  # Period field parameters (sf Period Slicer)
    "sf time",  # Time field parameters (sf Time Series)
    "mf ",  # Measure field parameters (mf Return (%), mf Performance)
    "field parameter",
    "fieldparameter",
    "_fp_",  # Alternative naming pattern
    "slicer param",
    "slicerparam",
    "_field_param",  # Another common pattern
]

# UI control / formatting table patterns - filters on these affect UI, not data
UI_CONTROL_PATTERNS = [
    "decimal",  # Decimal formatting tables
    "scale",  # Scale formatting tables
    "format",  # Format control tables
    "display",  # Display control tables
    "_ui_",  # UI control tables
    "_ctrl_",  # Control tables
]


# Filter classification types
class FilterClassification:
    """Classification of filters by their purpose."""

    DATA = "data"  # Actual data filters (Family, Period, Currency, etc.)
    FIELD_PARAMETER = "field_parameter"  # Field parameter tables (composite keys)
    UI_CONTROL = "ui_control"  # UI control filters (formatting, display options)
    UNKNOWN = "unknown"


def is_field_parameter_table(table_name: str) -> bool:
    """
    Detect if a table is a field parameter table.

    Field parameter tables have composite keys and should NOT be included
    in DAX filter expressions as they cause composite key errors.

    These tables are UI-control tables, not actual data filters. The measures
    in the model already handle field parameter logic internally.

    Args:
        table_name: The table name to check

    Returns:
        True if this appears to be a field parameter table
    """
    if not table_name:
        return False

    table_lower = table_name.lower().strip("'")

    # Check for common field parameter patterns
    for pattern in FIELD_PARAMETER_PATTERNS:
        if pattern in table_lower:
            return True

    # Check for specific naming conventions with space after prefix
    # Only 'sf ' (slicer field) prefix indicates field parameters
    # Tables like "sf Filter 1", "sf Row Drill", "sf Slicer 1"
    # NOTE: 's ' prefix is for regular selection tables (s Period View, s Reporting Currency)
    # which are NOT field parameters - they're disconnected slicer tables
    prefixes = ["sf ", "'sf ", "mf ", "'mf "]
    for prefix in prefixes:
        if table_lower.startswith(prefix):
            # sf/mf prefix tables are field parameters
            return True

    # Check for field parameter indicator (often have 'Fields' suffix)
    if table_lower.endswith(" fields") or table_lower.endswith("fields"):
        return True

    return False


def is_ui_control_table(table_name: str) -> bool:
    """
    Detect if a table is a UI control / formatting table.

    UI control tables affect visual formatting but not data.
    These can often be skipped for data analysis queries.

    NOTE: Tables with 's ' prefix (e.g., 's Scale', 's Decimal') are regular
    disconnected slicer / selection tables and are NOT UI controls — Power BI
    always includes them in the visual query. Only exclude truly formatting-only
    tables that have no 's ' or 'sf ' prefix.

    Args:
        table_name: The table name to check

    Returns:
        True if this appears to be a UI control table
    """
    if not table_name:
        return False

    table_lower = table_name.lower().strip("'")

    # 's ' prefix = regular selection / disconnected slicer tables (e.g., 's Scale',
    # 's Decimal', 's Reporting Currency'). Power BI always includes these in the
    # visual query TREATAS filters — never classify them as UI controls.
    if table_lower.startswith("s ") and not table_lower.startswith("sf "):
        return False

    for pattern in UI_CONTROL_PATTERNS:
        if pattern in table_lower:
            return True

    return False


def classify_filter(table_name: str, column_name: str = None) -> str:
    """
    Classify a filter by its purpose.

    Args:
        table_name: The table name
        column_name: Optional column name for additional context

    Returns:
        FilterClassification constant (DATA, FIELD_PARAMETER, UI_CONTROL, UNKNOWN)
    """
    if is_field_parameter_table(table_name):
        return FilterClassification.FIELD_PARAMETER

    if is_ui_control_table(table_name):
        return FilterClassification.UI_CONTROL

    # Default to data filter
    return FilterClassification.DATA


class FilterToDaxConverter:
    """
    Converts PBIP filter definitions to executable DAX expressions.

    Supports:
    - Report/Page/Visual level filters
    - Slicer selections
    - Various condition types (In, Comparison, Between, Not, IsBlank)
    - Type-aware value formatting (preserves string vs numeric types)
    """

    # Power BI data type mapping (covers string names, .NET types, and AS enum integers)
    POWERBI_TYPE_MAP = {
        "String": "string",
        "Int64": "integer",
        "Double": "decimal",
        "Decimal": "decimal",
        "Currency": "decimal",
        "DateTime": "date",
        "Date": "date",
        "Boolean": "boolean",
        "Binary": "string",  # Treat as string for filtering
        # .NET type names (returned by some DMV configurations)
        "System.String": "string",
        "System.Int64": "integer",
        "System.Double": "decimal",
        "System.Decimal": "decimal",
        "System.DateTime": "date",
        "System.Boolean": "boolean",
        # AS DataType enum integer values
        "2": "string",
        "6": "integer",
        "8": "decimal",
        "9": "date",
        "11": "boolean",
    }

    def __init__(self):
        """Initialize the converter."""
        self.logger = logging.getLogger(__name__)
        # Cache for column data types: {'TableName.ColumnName': 'string'|'integer'|...}
        self._column_types: Dict[str, str] = {}

    def set_column_types(self, column_types: Dict[str, str]) -> None:
        """
        Set column data types from model metadata.

        Args:
            column_types: Dict mapping 'TableName.ColumnName' to type string
                         Types: 'string', 'integer', 'decimal', 'boolean', 'date'
        """
        self._column_types = column_types

    def set_column_type(self, table: str, column: str, data_type: str) -> None:
        """
        Set a single column's data type.

        Args:
            table: Table name
            column: Column name
            data_type: Power BI type (e.g., 'String', 'Int64') or internal type
        """
        key = f"{table}.{column}"
        # Map Power BI type to internal type if needed
        mapped_type = self.POWERBI_TYPE_MAP.get(data_type, data_type.lower())
        self._column_types[key] = mapped_type
        self.logger.debug(f"Set column type: {key} = {mapped_type}")

    def get_column_type(self, table: str, column: str) -> Optional[str]:
        """Get the cached data type for a column."""
        key = f"{table}.{column}"
        return self._column_types.get(key)

    def load_column_types_from_model(self, query_executor) -> int:
        """
        Load column data types from the connected Power BI model.

        Args:
            query_executor: A QueryExecutor instance connected to the model

        Returns:
            Number of column types loaded
        """
        if not query_executor:
            return 0

        try:
            # Query COLUMNS DMV to get data types
            result = query_executor.execute_info_query("COLUMNS")
            if not result.get("success") or not result.get("rows"):
                return 0

            count = 0
            for row in result["rows"]:
                table_name = row.get("TableName", row.get("[TableName]", ""))
                column_name = row.get("ColumnName", row.get("[ColumnName]", ""))
                data_type = row.get("DataType", row.get("[DataType]", ""))

                # Clean up table name (remove quotes)
                if table_name.startswith("'") and table_name.endswith("'"):
                    table_name = table_name[1:-1]

                if table_name and column_name and data_type:
                    self.set_column_type(table_name, column_name, data_type)
                    count += 1

            self.logger.info(f"Loaded {count} column types from model")
            return count

        except Exception as e:
            self.logger.warning(f"Error loading column types from model: {e}")
            return 0

    def convert_filter(
        self, filter_def: Dict[str, Any], source: str = "unknown"
    ) -> Optional[FilterExpression]:
        """
        Convert a single PBIP filter definition to a DAX expression.

        Args:
            filter_def: The filter definition from PBIP (contains 'filter', 'type', etc.)
            source: Source of the filter ('report', 'page', 'visual', 'slicer')

        Returns:
            FilterExpression with DAX or None if conversion fails
        """
        try:
            # Extract table and column from filter target
            table, column = self._extract_target(filter_def)
            if not table or not column:
                self.logger.debug(f"Could not extract target from filter: {filter_def}")
                return None

            # Get the filter condition
            filter_condition = filter_def.get("filter", {})
            if not filter_condition:
                return None

            where_clauses = filter_condition.get("Where", [])
            if not where_clauses:
                return None

            # Process each condition
            dax_parts = []
            all_values = []
            condition_type = "Unknown"
            has_null_values = False

            for where in where_clauses:
                condition = where.get("Condition", {})
                dax_part, cond_type, values, contains_null = (
                    self._convert_condition_with_null_handling(condition, table, column)
                )
                if dax_part:
                    dax_parts.append(dax_part)
                    all_values.extend(values)
                    condition_type = cond_type
                    if contains_null:
                        has_null_values = True

            if not dax_parts:
                return None

            # Combine with AND if multiple conditions
            dax = " && ".join(dax_parts) if len(dax_parts) > 1 else dax_parts[0]

            # Classify the filter
            filter_classification = classify_filter(table, column)

            return FilterExpression(
                dax=dax,
                source=source,
                table=table,
                column=column,
                condition_type=condition_type,
                values=all_values,
                original=filter_def,
                is_field_parameter=is_field_parameter_table(table),
                classification=filter_classification,
                has_null_values=has_null_values,
            )

        except Exception as e:
            self.logger.warning(f"Error converting filter: {e}")
            return None

    def convert_slicer_selection(self, slicer_info: Dict[str, Any]) -> Optional[FilterExpression]:
        """
        Convert slicer selection state to a DAX filter expression.

        Args:
            slicer_info: Slicer info dictionary containing:
                - entity: Table name
                - property: Column name (already resolved to DAX column, e.g. 'sf Filter 1 Fields')
                - selected_values: List of selected values (can be raw or TypedValue)
                - is_inverted_selection: Whether selection is inverted
                - selection_mode: 'single_select', 'multi_select', 'single_select_all'
                - extra_columns: Optional list of additional 'Table'[Col] refs (composite TREATAS)
                - composite_values: Optional list of value tuples (one per row) for composite TREATAS

        Returns:
            FilterExpression or None if no filter needed
        """
        try:
            entity = slicer_info.get("entity", "")
            column = slicer_info.get("property", "")
            selected_values = slicer_info.get("selected_values", [])
            is_inverted = slicer_info.get("is_inverted_selection", False)
            selection_mode = slicer_info.get("selection_mode", "multi_select")
            extra_columns = slicer_info.get("extra_columns", [])
            composite_values = slicer_info.get("composite_values", None)

            if not entity or not column:
                return None

            # If "Select All" (inverted with no exclusions), no filter needed
            if selection_mode == "single_select_all" and not selected_values:
                return None

            # --- Composite multi-column TREATAS path (sf Row Drill, sf Slicer 1, etc.) ---
            if extra_columns and composite_values:
                all_col_refs = [f"'{entity}'[{column}]"] + list(extra_columns)
                # Clean each value in each tuple
                cleaned_tuples = []
                raw_first_col_values = []
                for row in composite_values:
                    cleaned_row = []
                    for val in row:
                        if isinstance(val, TypedValue):
                            cleaned_row.append(val)
                        else:
                            cleaned_row.append(
                                self._clean_literal_value(val)
                                if isinstance(val, str)
                                else TypedValue(val, "unknown")
                            )
                    cleaned_tuples.append(cleaned_row)
                    if cleaned_row:
                        raw_first_col_values.append(
                            cleaned_row[0].value
                            if isinstance(cleaned_row[0], TypedValue)
                            else cleaned_row[0]
                        )

                if not cleaned_tuples:
                    return None

                filter_classification = classify_filter(entity, column)
                # dax is a placeholder — _build_visual_dax_query uses composite_columns/tuples directly
                return FilterExpression(
                    dax=f"-- composite TREATAS on '{entity}'[{column}]",
                    source="slicer",
                    table=entity,
                    column=column,
                    condition_type="Composite",
                    values=raw_first_col_values,
                    original=slicer_info,
                    is_field_parameter=True,
                    classification=filter_classification,
                    has_null_values=False,
                    composite_columns=all_col_refs,
                    composite_tuples=cleaned_tuples,
                )

            # --- Standard single-column path ---
            if not selected_values:
                return None

            # Convert to TypedValue and separate null values
            typed_values = []
            raw_values = []
            null_values = []

            for val in selected_values:
                if isinstance(val, TypedValue):
                    typed_val = val
                else:
                    # Parse slicer values (they come from PBIP with type suffixes)
                    typed_val = (
                        self._clean_literal_value(val)
                        if isinstance(val, str)
                        else TypedValue(val, "unknown")
                    )

                if self._is_null_value(typed_val):
                    null_values.append(typed_val)
                else:
                    typed_values.append(typed_val)
                    raw_values.append(typed_val.value if isinstance(typed_val, TypedValue) else val)

            has_null = len(null_values) > 0

            # Build the DAX expression with proper null handling
            table_ref = f"'{entity}'"
            column_ref = f"{table_ref}[{column}]"

            dax_parts = []

            if is_inverted:
                # Inverted = exclude these values
                if null_values:
                    dax_parts.append(f"NOT(ISBLANK({column_ref}))")
                if typed_values:
                    formatted_values = self._format_values_for_dax(typed_values)
                    dax_parts.append(f"NOT({column_ref} IN {{{formatted_values}}})")
                # Combine with AND for NOT conditions
                if len(dax_parts) > 1:
                    dax = f"({' && '.join(dax_parts)})"
                elif dax_parts:
                    dax = dax_parts[0]
                else:
                    return None
                condition_type = "Not"
            else:
                # Normal = include only these values
                if null_values:
                    dax_parts.append(f"ISBLANK({column_ref})")
                if typed_values:
                    formatted_values = self._format_values_for_dax(typed_values)
                    dax_parts.append(f"{column_ref} IN {{{formatted_values}}}")
                # Combine with OR for IN conditions
                if len(dax_parts) > 1:
                    dax = f"({' || '.join(dax_parts)})"
                elif dax_parts:
                    dax = dax_parts[0]
                else:
                    return None
                condition_type = "In"

            # Classify the filter
            filter_classification = classify_filter(entity, column)

            return FilterExpression(
                dax=dax,
                source="slicer",
                table=entity,
                column=column,
                condition_type=condition_type,
                values=raw_values,
                original=slicer_info,
                is_field_parameter=is_field_parameter_table(entity),
                classification=filter_classification,
                has_null_values=has_null,
            )

        except Exception as e:
            self.logger.warning(f"Error converting slicer selection: {e}")
            return None

    def _convert_condition(
        self, condition: Dict[str, Any], table: str, column: str
    ) -> Tuple[Optional[str], str, List[Any]]:
        """
        Convert a single filter condition to DAX.

        Returns:
            Tuple of (dax_expression, condition_type, values)
        """
        # Use the enhanced method and ignore the null flag for backward compatibility
        dax, cond_type, values, _ = self._convert_condition_with_null_handling(
            condition, table, column
        )
        return dax, cond_type, values

    def _convert_condition_with_null_handling(
        self, condition: Dict[str, Any], table: str, column: str
    ) -> Tuple[Optional[str], str, List[Any], bool]:
        """
        Convert a single filter condition to DAX with proper null/blank handling.

        When a filter includes null values, generates ISBLANK() instead of IN {"null"}.

        Returns:
            Tuple of (dax_expression, condition_type, values, contains_null)
        """
        table_ref = f"'{table}'"
        column_ref = f"{table_ref}[{column}]"

        # Handle "In" conditions (categorical filters)
        if "In" in condition:
            return self._convert_in_condition_with_null(condition["In"], column_ref)

        # Handle "Comparison" conditions
        if "Comparison" in condition:
            dax, cond_type, values = self._convert_comparison_condition(
                condition["Comparison"], column_ref
            )
            return dax, cond_type, values, False

        # Handle "Between" conditions
        if "Between" in condition:
            dax, cond_type, values = self._convert_between_condition(
                condition["Between"], column_ref
            )
            return dax, cond_type, values, False

        # Handle "Not" conditions
        if "Not" in condition:
            return self._convert_not_condition_with_null(
                condition["Not"], column_ref, table, column
            )

        # Handle "IsBlank" / "IsNotBlank"
        if "IsBlank" in condition:
            return f"ISBLANK({column_ref})", "IsBlank", [], True

        if "IsNotBlank" in condition:
            return f"NOT(ISBLANK({column_ref}))", "IsNotBlank", [], False

        return None, "Unknown", [], False

    def _is_null_value(self, value: Any) -> bool:
        """Check if a value represents null/blank."""
        if value is None:
            return True
        if isinstance(value, str):
            val_lower = value.lower().strip()
            return val_lower in ("null", "'null'l", '"null"l', "blank", "'blank'l")
        if isinstance(value, TypedValue):
            return self._is_null_value(value.value)
        return False

    def _convert_in_condition_with_null(
        self, in_cond: Dict[str, Any], column_ref: str
    ) -> Tuple[Optional[str], str, List[Any], bool]:
        """Convert an IN condition to DAX with proper null handling."""
        values_list = in_cond.get("Values", [])
        typed_values = []  # TypedValue objects for correct DAX formatting
        raw_values = []  # Raw values for display/return
        null_values = []  # Track null values separately

        for value_group in values_list:
            for val in value_group:
                if "Literal" in val:
                    typed_value = self._clean_literal_value(val["Literal"].get("Value", ""))
                    if self._is_null_value(typed_value):
                        null_values.append(typed_value)
                    else:
                        typed_values.append(typed_value)
                        raw_values.append(typed_value.value)

        has_null = len(null_values) > 0

        # Build the DAX expression
        dax_parts = []

        # Add ISBLANK for null values
        if null_values:
            dax_parts.append(f"ISBLANK({column_ref})")

        # Add IN clause for non-null values
        if typed_values:
            formatted_values = self._format_values_for_dax(typed_values)
            dax_parts.append(f"{column_ref} IN {{{formatted_values}}}")

        if not dax_parts:
            return None, "In", [], False

        # Combine with OR if we have both null and non-null values
        if len(dax_parts) > 1:
            dax = f"({' || '.join(dax_parts)})"
        else:
            dax = dax_parts[0]

        return dax, "In", raw_values, has_null

    def _convert_in_condition(
        self, in_cond: Dict[str, Any], column_ref: str
    ) -> Tuple[Optional[str], str, List[Any]]:
        """Convert an IN condition to DAX."""
        values_list = in_cond.get("Values", [])
        typed_values = []  # TypedValue objects for correct DAX formatting
        raw_values = []  # Raw values for display/return

        for value_group in values_list:
            for val in value_group:
                if "Literal" in val:
                    typed_value = self._clean_literal_value(val["Literal"].get("Value", ""))
                    typed_values.append(typed_value)
                    raw_values.append(typed_value.value)

        if not typed_values:
            return None, "In", []

        formatted_values = self._format_values_for_dax(typed_values)
        dax = f"{column_ref} IN {{{formatted_values}}}"
        return dax, "In", raw_values

    def _convert_comparison_condition(
        self, comp: Dict[str, Any], column_ref: str
    ) -> Tuple[Optional[str], str, List[Any]]:
        """Convert a comparison condition to DAX."""
        comp_kind = comp.get("ComparisonKind", "")
        right = comp.get("Right", {})

        if "Literal" not in right:
            return None, "Comparison", []

        typed_value = self._clean_literal_value(right["Literal"].get("Value", ""))

        # Map comparison kinds to DAX operators
        operators = {
            "GreaterThan": ">",
            "GreaterThanOrEqual": ">=",
            "LessThan": "<",
            "LessThanOrEqual": "<=",
            "Equal": "=",
            "NotEqual": "<>",
        }

        operator = operators.get(comp_kind, "=")
        formatted_value = self._format_single_value_for_dax(typed_value)
        dax = f"{column_ref} {operator} {formatted_value}"

        return dax, "Comparison", [typed_value.value]

    def _convert_between_condition(
        self, between: Dict[str, Any], column_ref: str
    ) -> Tuple[Optional[str], str, List[Any]]:
        """Convert a BETWEEN condition to DAX."""
        lower_raw = between.get("Lower", {}).get("Literal", {}).get("Value", "")
        upper_raw = between.get("Upper", {}).get("Literal", {}).get("Value", "")

        if not lower_raw or not upper_raw:
            return None, "Between", []

        lower_typed = self._clean_literal_value(lower_raw)
        upper_typed = self._clean_literal_value(upper_raw)

        lower_fmt = self._format_single_value_for_dax(lower_typed)
        upper_fmt = self._format_single_value_for_dax(upper_typed)

        dax = f"{column_ref} >= {lower_fmt} && {column_ref} <= {upper_fmt}"
        return dax, "Between", [lower_typed.value, upper_typed.value]

    def _convert_not_condition(
        self, not_cond: Dict[str, Any], column_ref: str, table: str, column: str
    ) -> Tuple[Optional[str], str, List[Any]]:
        """Convert a NOT condition to DAX."""
        dax, cond_type, values, _ = self._convert_not_condition_with_null(
            not_cond, column_ref, table, column
        )
        return dax, cond_type, values

    def _convert_not_condition_with_null(
        self, not_cond: Dict[str, Any], column_ref: str, table: str, column: str
    ) -> Tuple[Optional[str], str, List[Any], bool]:
        """Convert a NOT condition to DAX with null handling."""
        expression = not_cond.get("Expression", {})

        # Handle NOT IN
        if "In" in expression:
            inner_dax, _, values, has_null = self._convert_in_condition_with_null(
                expression["In"], column_ref
            )
            if inner_dax:
                return f"NOT({inner_dax})", "Not", values, has_null

        return None, "Not", [], False

    def _extract_target(self, filter_def: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """Extract table and column from filter definition."""
        try:
            # Try target field first
            target = filter_def.get("target", {})
            if target:
                table = target.get("table", "")
                column = target.get("column", target.get("measure", ""))
                if table and column:
                    return table, column

            # Try expression path
            expression = filter_def.get("expression", {})
            if expression:
                column_expr = expression.get("Column", {})
                if column_expr:
                    expr = column_expr.get("Expression", {})
                    source_ref = expr.get("SourceRef", {})
                    table = source_ref.get("Entity", source_ref.get("Source", ""))
                    column = column_expr.get("Property", "")
                    if table and column:
                        return table, column

            # Try filter.From path
            filter_obj = filter_def.get("filter", {})
            from_list = filter_obj.get("From", [])
            if from_list:
                table = from_list[0].get("Entity", from_list[0].get("Name", ""))

                # Get column from Where clause
                where_list = filter_obj.get("Where", [])
                if where_list:
                    condition = where_list[0].get("Condition", {})
                    # Try In condition
                    in_cond = condition.get("In", {})
                    exprs = in_cond.get("Expressions", [])
                    if exprs:
                        col_expr = exprs[0].get("Column", {})
                        column = col_expr.get("Property", "")
                        if table and column:
                            return table, column

            return None, None

        except Exception as e:
            self.logger.debug(f"Error extracting target: {e}")
            return None, None

    def _clean_literal_value(self, value: Any) -> TypedValue:
        """
        Clean Power BI literal values from PBIP JSON format.

        Power BI stores literals with type suffixes:
        - 'text'L for strings
        - 123L for integers
        - 123.45D for decimals
        - 123.45M for currency
        - trueL or falseL for booleans

        Returns a TypedValue that preserves the original type information.
        """
        if not isinstance(value, str):
            # Already a Python type - infer type
            if isinstance(value, bool):
                return TypedValue(value, "boolean")
            elif isinstance(value, int):
                return TypedValue(value, "integer")
            elif isinstance(value, float):
                return TypedValue(value, "decimal")
            return TypedValue(value, "unknown")

        # Handle quoted literals with L suffix: 'value'L -> value (STRING)
        if value.endswith("'L") and value.startswith("'"):
            inner = value[1:-2].replace("''", "'")  # unescape embedded single quotes
            return TypedValue(inner, "string")  # Definitely a string!
        elif value.endswith('"L') and value.startswith('"'):
            return TypedValue(value[1:-2], "string")  # Definitely a string!

        # Handle quoted values without L suffix (still strings)
        elif value.startswith("'") and value.endswith("'"):
            inner = value[1:-1].replace("''", "'")  # unescape embedded single quotes
            return TypedValue(inner, "string")
        elif value.startswith('"') and value.endswith('"'):
            return TypedValue(value[1:-1], "string")

        # Handle unquoted boolean with L suffix: trueL, falseL
        elif value.lower() in ("truel", "falsel"):
            return TypedValue(value.lower() == "truel", "boolean")

        # Handle numeric with L suffix: 123L -> 123 (INTEGER)
        elif value.endswith("L") and value[:-1].lstrip("-").isdigit():
            return TypedValue(int(value[:-1]), "integer")

        # Handle decimal with D suffix: 123.45D -> 123.45 (DECIMAL)
        elif value.endswith("D"):
            try:
                return TypedValue(float(value[:-1]), "decimal")
            except ValueError:
                pass

        # Handle currency with M suffix: 123.45M -> 123.45 (DECIMAL)
        elif value.endswith("M"):
            try:
                return TypedValue(float(value[:-1]), "decimal")
            except ValueError:
                pass

        # Check if the value is a boolean string
        if value.lower() in ("true", "false"):
            return TypedValue(value.lower() == "true", "boolean")

        # Fallback - treat as unknown (will be auto-detected in format function)
        return TypedValue(value, "unknown")

    def _format_values_for_dax(self, values: List[Any]) -> str:
        """Format a list of values for DAX IN clause."""
        formatted = []
        for val in values:
            formatted.append(self._format_single_value_for_dax(val))
        return ", ".join(formatted)

    def _format_single_value_for_dax(self, value: Any) -> str:
        """
        Format a single value for DAX.

        Handles TypedValue objects to preserve original type information,
        preventing type mismatches like string "0" being formatted as integer 0.
        """
        # Handle TypedValue objects - respect the original type!
        if isinstance(value, TypedValue):
            typed_val = value
            raw_value = typed_val.value

            if raw_value is None:
                return "BLANK()"

            # Use the known type
            if typed_val.value_type == "string":
                # Always format as string, even if it looks numeric!
                str_val = str(raw_value).replace('"', '""')
                return f'"{str_val}"'
            elif typed_val.value_type == "boolean":
                if isinstance(raw_value, bool):
                    return "TRUE" if raw_value else "FALSE"
                return "TRUE" if str(raw_value).lower() == "true" else "FALSE"
            elif typed_val.value_type == "integer":
                return str(int(raw_value))
            elif typed_val.value_type == "decimal":
                return str(float(raw_value))
            elif typed_val.value_type == "date":
                # Format as DAX date
                str_val = str(raw_value)
                if len(str_val) >= 10:
                    return f"DATE({str_val[:4]}, {int(str_val[5:7])}, {int(str_val[8:10])})"
                return f'"{str_val}"'
            else:
                # 'unknown' type - fall through to auto-detection below
                value = raw_value

        # Handle raw values (backward compatibility and unknown types)
        if value is None:
            return "BLANK()"

        # Check if it's a boolean (Python bool or string representation)
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return "TRUE" if value.lower() == "true" else "FALSE"

        # Check if it's already a numeric Python type
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        if isinstance(value, float):
            return str(value)

        # Check if it's a date (ISO format)
        if isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-":
            try:
                # Format as DAX date
                return f"DATE({value[:4]}, {int(value[5:7])}, {int(value[8:10])})"
            except ValueError:
                pass

        # For string values that might look numeric:
        # Only parse as number if it's clearly numeric (no leading zeros except "0")
        if isinstance(value, str):
            stripped = value.strip()
            # Check if it's a clean numeric value (not a string that happens to contain digits)
            is_clean_integer = stripped.lstrip("-").isdigit() and (
                len(stripped.lstrip("-")) == 1 or not stripped.lstrip("-").startswith("0")
            )
            is_clean_decimal = False
            if not is_clean_integer and "." in stripped:
                parts = stripped.lstrip("-").split(".")
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    is_clean_decimal = True

            if is_clean_integer:
                return stripped
            elif is_clean_decimal:
                return stripped

        # Default: treat as string value - escape quotes
        str_val = str(value).replace('"', '""')
        return f'"{str_val}"'

    def build_calculate_expression(self, measure_expr: str, filters: List[FilterExpression]) -> str:
        """
        Build a CALCULATE expression with all filter expressions.

        Args:
            measure_expr: The measure expression (e.g., "[Total Sales]")
            filters: List of FilterExpression objects

        Returns:
            Complete CALCULATE expression
        """
        if not filters:
            return measure_expr

        filter_dax = [f.dax for f in filters if f.dax]
        if not filter_dax:
            return measure_expr

        filters_str = ",\n    ".join(filter_dax)
        return f"CALCULATE(\n    {measure_expr},\n    {filters_str}\n)"

    def build_evaluate_query(
        self, measure_name: str, filters: List[FilterExpression], result_name: str = "Result"
    ) -> str:
        """
        Build a complete EVALUATE ROW query with filters.

        Args:
            measure_name: Name of the measure (e.g., "[Total Sales]")
            filters: List of FilterExpression objects
            result_name: Name for the result column

        Returns:
            Complete DAX query
        """
        calculate_expr = self.build_calculate_expression(measure_name, filters)
        return f'EVALUATE\nROW("{result_name}", {calculate_expr})'
