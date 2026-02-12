"""
DAX Reference Parser

Shared module for parsing DAX expressions and extracting references to tables, columns, and measures.
This module breaks the circular dependency between core/model and core/documentation.

Enhanced in v6.5.0:
- Added detection for RELATED/RELATEDTABLE relationship traversals
- Added USERELATIONSHIP detection for inactive relationship usage
- Added VAR/RETURN variable scope tracking
- Added CALCULATE filter argument parsing
- Added TREATAS, CROSSFILTER, KEEPFILTERS detection
- Added relationship function context for better dependency analysis
"""

import logging
import re
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Core reference patterns
_QUALIFIED_TOKEN = re.compile(r"'([^']+)'\s*\[([^\]]+)\]")
_UNQUALIFIED_TOKEN = re.compile(r"(?<!')\[(.+?)\]")

# Relationship function patterns - capture table/column references within these functions
_RELATED_PATTERN = re.compile(
    r"\bRELATED\s*\(\s*'?([^'\[\)]+)'?\s*\[([^\]]+)\]\s*\)",
    re.IGNORECASE
)
_RELATEDTABLE_PATTERN = re.compile(
    r"\bRELATEDTABLE\s*\(\s*'?([^'\)]+)'?\s*\)",
    re.IGNORECASE
)
_USERELATIONSHIP_PATTERN = re.compile(
    r"\bUSERELATIONSHIP\s*\(\s*'?([^'\[\)]+)'?\s*\[([^\]]+)\]\s*,\s*'?([^'\[\)]+)'?\s*\[([^\]]+)\]\s*\)",
    re.IGNORECASE
)
_TREATAS_PATTERN = re.compile(
    r"\bTREATAS\s*\(\s*([^,]+),\s*'?([^'\[\)]+)'?\s*\[([^\]]+)\]",
    re.IGNORECASE
)
_CROSSFILTER_PATTERN = re.compile(
    r"\bCROSSFILTER\s*\(\s*'?([^'\[\)]+)'?\s*\[([^\]]+)\]\s*,\s*'?([^'\[\)]+)'?\s*\[([^\]]+)\]\s*,\s*(\w+)\s*\)",
    re.IGNORECASE
)

# VAR/RETURN pattern - captures variable definitions
_VAR_PATTERN = re.compile(
    r"\bVAR\s+(__?[a-zA-Z_][a-zA-Z0-9_]*)\s*=",
    re.IGNORECASE
)

# CALCULATE filter patterns
_CALCULATE_FILTER_PATTERN = re.compile(
    r"'([^']+)'\s*\[([^\]]+)\]\s*(?:=|<>|<|>|<=|>=|IN)\s*",
    re.IGNORECASE
)

# Table-only reference patterns: functions that accept a bare table name
# e.g., REMOVEFILTERS('d Period'), ALL('Calendar'), ALLSELECTED('Sales'),
#        VALUES('Product'), DISTINCT('Orders'), KEEPFILTERS('Date'),
#        CALCULATETABLE('Fact'), SUMMARIZE('Table', ...), ADDCOLUMNS('Table', ...),
#        SELECTCOLUMNS('Table', ...), FILTER('Table', ...), GENERATE('T1', ...),
#        GENERATEALL('T1', ...), TOPN(N, 'Table', ...), SAMPLE(N, 'Table', ...),
#        NATURALINNERJOIN('T1', 'T2'), NATURALLEFTOUTERJOIN('T1', 'T2'),
#        UNION('T1', ...), INTERSECT('T1', ...), EXCEPT('T1', ...),
#        CROSSJOIN('T1', ...), DATATABLE('T', ...), COUNTROWS('T'),
#        ISEMPTY('T'), CONTAINS('T', ...), HASONEVALUE('T'[Col]),
#        ALLNOBLANKROW('T'), SUBSTITUTEWITHINDEX('T', ...)
_TABLE_ONLY_FUNCTIONS = (
    r"REMOVEFILTERS|ALL|ALLEXCEPT|ALLSELECTED|ALLNOBLANKROW|ALLCROSSFILTERED|"
    r"VALUES|DISTINCT|KEEPFILTERS|"
    r"CALCULATETABLE|SUMMARIZE|SUMMARIZECOLUMNS|ADDCOLUMNS|SELECTCOLUMNS|"
    r"FILTER|GENERATE|GENERATEALL|TOPN|SAMPLE|"
    r"NATURALINNERJOIN|NATURALLEFTOUTERJOIN|"
    r"UNION|INTERSECT|EXCEPT|CROSSJOIN|"
    r"COUNTROWS|ISEMPTY|CONTAINS|CONTAINSROW|"
    r"DATATABLE|SUBSTITUTEWITHINDEX|GROUPBY|ROLLUP|ROLLUPADDISSUBTOTAL|"
    r"TREATAS"
)

# Matches: FUNCTIONNAME ( 'Table Name' )  or  FUNCTIONNAME ( 'Table Name' ,
# The table name is in single quotes, followed by ) or , (with optional whitespace)
_TABLE_ONLY_PATTERN = re.compile(
    rf"\b(?:{_TABLE_ONLY_FUNCTIONS})\s*\(\s*'([^']+)'\s*[,\)]",
    re.IGNORECASE
)

# Also catch unquoted table references: FUNCTIONNAME( TableName ) or FUNCTIONNAME( TableName,
# Only matches single-word table names (no spaces) to avoid false positives
_TABLE_ONLY_UNQUOTED_PATTERN = re.compile(
    rf"\b(?:{_TABLE_ONLY_FUNCTIONS})\s*\(\s*(?!')((?:[A-Za-z_][A-Za-z0-9_]*))(?:\s*[,\)])",
    re.IGNORECASE
)


@dataclass
class RelationshipReference:
    """Represents a relationship reference in DAX (RELATED, USERELATIONSHIP, etc.)"""
    function: str  # RELATED, RELATEDTABLE, USERELATIONSHIP, TREATAS, CROSSFILTER
    from_table: str
    from_column: Optional[str]
    to_table: Optional[str] = None
    to_column: Optional[str] = None
    direction: Optional[str] = None  # For CROSSFILTER: NONE, ONEWAY, BOTH


@dataclass
class VariableDefinition:
    """Represents a VAR definition in DAX"""
    name: str
    position: int  # Character position in expression


@dataclass
class DaxReferenceResult:
    """Enhanced result structure for DAX reference parsing"""
    tables: List[str] = field(default_factory=list)
    columns: List[Tuple[str, str]] = field(default_factory=list)
    measures: List[Tuple[str, str]] = field(default_factory=list)
    identifiers: List[str] = field(default_factory=list)
    # Enhanced fields
    relationship_refs: List[RelationshipReference] = field(default_factory=list)
    variables: List[VariableDefinition] = field(default_factory=list)
    filter_columns: List[Tuple[str, str]] = field(default_factory=list)  # Columns used in CALCULATE filters
    uses_inactive_relationships: bool = False
    relationship_functions_used: List[str] = field(default_factory=list)  # RELATED, RELATEDTABLE, etc.

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for backward compatibility"""
        return {
            "tables": self.tables,
            "columns": self.columns,
            "measures": self.measures,
            "identifiers": self.identifiers,
            "relationship_refs": [
                {
                    "function": r.function,
                    "from_table": r.from_table,
                    "from_column": r.from_column,
                    "to_table": r.to_table,
                    "to_column": r.to_column,
                    "direction": r.direction,
                }
                for r in self.relationship_refs
            ],
            "variables": [{"name": v.name, "position": v.position} for v in self.variables],
            "filter_columns": self.filter_columns,
            "uses_inactive_relationships": self.uses_inactive_relationships,
            "relationship_functions_used": self.relationship_functions_used,
        }


def _normalize_name(name: str) -> str:
    """Normalize a name for lookup - lowercase and collapse whitespace."""
    if not name:
        return ''
    return ' '.join(name.lower().split())


class DaxReferenceIndex:
    """
    Index of known measures and columns for DAX reference resolution.

    Used to distinguish between measure and column references in DAX expressions.
    Enhanced to also track table relationships for better dependency analysis.
    """

    def __init__(self, measure_rows=None, column_rows=None, relationship_rows=None) -> None:
        """
        Initialize the reference index.

        Args:
            measure_rows: List of measure dictionaries with 'Table' and 'Name' keys
            column_rows: List of column dictionaries with 'Table' and 'Name' keys
            relationship_rows: Optional list of relationship dictionaries for relationship validation
        """
        self.measure_keys: Set[str] = set()
        self.measure_names: Dict[str, Set[str]] = {}  # normalized_name -> set of tables
        self.measure_name_original: Dict[str, str] = {}  # normalized_name -> original name (for case preservation)
        self.column_keys: Set[str] = set()
        self.column_names: Dict[str, Set[str]] = {}  # For column name to table mapping
        self.table_names: Set[str] = set()

        # Track relationships for USERELATIONSHIP validation
        self.relationship_pairs: Set[Tuple[str, str, str, str]] = set()  # (from_table, from_col, to_table, to_col)

        if measure_rows:
            for row in measure_rows:
                # Try both bracketed and non-bracketed column names (DMV queries vary)
                table = str(row.get("Table") or row.get("[Table]") or "").strip()
                name = str(row.get("Name") or row.get("[Name]") or "").strip()
                if table and name:
                    normalized = _normalize_name(name)
                    key = f"{table.lower()}|{normalized}"
                    self.measure_keys.add(key)
                    self.measure_names.setdefault(normalized, set()).add(table)
                    self.measure_name_original[normalized] = name  # Keep original casing
                    self.table_names.add(table)
                    logger.debug(f"Indexed measure: {table}[{name}] -> normalized: {normalized}")

        if column_rows:
            for row in column_rows:
                # Try both bracketed and non-bracketed column names (DMV queries vary)
                table = str(row.get("Table") or row.get("[Table]") or "").strip()
                name = str(row.get("Name") or row.get("[Name]") or "").strip()
                if table and name:
                    normalized = _normalize_name(name)
                    self.column_keys.add(f"{table.lower()}|{normalized}")
                    self.column_names.setdefault(normalized, set()).add(table)
                    self.table_names.add(table)

        if relationship_rows:
            for row in relationship_rows:
                from_table = str(row.get("FromTable") or row.get("FROMTABLE") or "").strip()
                from_col = str(row.get("FromColumn") or row.get("FROMCOLUMN") or "").strip()
                to_table = str(row.get("ToTable") or row.get("TOTABLE") or "").strip()
                to_col = str(row.get("ToColumn") or row.get("TOCOLUMN") or "").strip()
                if from_table and from_col and to_table and to_col:
                    self.relationship_pairs.add((
                        from_table.lower(), from_col.lower(),
                        to_table.lower(), to_col.lower()
                    ))

    def is_valid_relationship(self, table1: str, col1: str, table2: str, col2: str) -> bool:
        """Check if a relationship exists between two column references"""
        key1 = (table1.lower(), col1.lower(), table2.lower(), col2.lower())
        key2 = (table2.lower(), col2.lower(), table1.lower(), col1.lower())
        return key1 in self.relationship_pairs or key2 in self.relationship_pairs


def parse_dax_references(
    expression: Optional[str],
    reference_index: Optional[DaxReferenceIndex] = None,
    enhanced: bool = False,
) -> Dict[str, Any]:
    """
    Parse DAX expression and extract references to tables, columns, and measures.

    This parser extracts qualified ('Table'[Column]) and unqualified ([Measure]) references,
    plus enhanced relationship and variable tracking when enhanced=True.

    Args:
        expression: The DAX expression to parse
        reference_index: Optional index to distinguish measures from columns
        enhanced: If True, returns DaxReferenceResult with additional context

    Returns:
        Dictionary with keys:
        - tables: List of table names referenced
        - columns: List of (table, column) tuples
        - measures: List of (table, measure) tuples
        - identifiers: List of all bracket-enclosed identifiers

        When enhanced=True, also includes:
        - relationship_refs: List of relationship function usages
        - variables: List of VAR definitions
        - filter_columns: Columns used in CALCULATE filters
        - uses_inactive_relationships: Whether USERELATIONSHIP is used
        - relationship_functions_used: List of relationship functions used

    Example:
        >>> parse_dax_references("CALCULATE([Sales], 'Product'[Category] = \"Bikes\")")
        {
            "tables": ["Product"],
            "columns": [("Product", "Category")],
            "measures": [("", "Sales")],
            "identifiers": ["Sales", "Category"]
        }

        >>> parse_dax_references("SUMX(RELATEDTABLE('Orders'), RELATED('Product'[Price]))", enhanced=True)
        {
            "tables": ["Orders", "Product"],
            "columns": [("Product", "Price")],
            "measures": [],
            "identifiers": ["Price"],
            "relationship_refs": [...],
            "uses_inactive_relationships": False,
            "relationship_functions_used": ["RELATED", "RELATEDTABLE"]
        }
    """
    empty_result = {
        "tables": [], "columns": [], "measures": [], "identifiers": [],
        "relationship_refs": [], "variables": [], "filter_columns": [],
        "uses_inactive_relationships": False, "relationship_functions_used": []
    } if enhanced else {"tables": [], "columns": [], "measures": [], "identifiers": []}

    if not isinstance(expression, str) or not expression.strip():
        return empty_result

    # Remove comments
    cleaned = re.sub(r"/\*.*?\*/", "", expression, flags=re.DOTALL)
    cleaned = re.sub(r"//.*?$", "", cleaned, flags=re.MULTILINE)

    tables: Set[str] = set()
    columns: Set[Tuple[str, str]] = set()
    measures: Set[Tuple[str, str]] = set()
    identifiers: Set[str] = set()

    # Enhanced tracking
    relationship_refs: List[RelationshipReference] = []
    variables: List[VariableDefinition] = []
    filter_columns: Set[Tuple[str, str]] = set()
    relationship_functions_used: Set[str] = set()
    uses_inactive_relationships = False

    ref_idx = reference_index or DaxReferenceIndex()

    # Parse qualified references: 'Table'[Column]
    for table, name in _QUALIFIED_TOKEN.findall(cleaned):
        tbl = table.strip()
        obj = name.strip()
        if not obj:
            continue
        identifiers.add(obj)
        normalized_obj = _normalize_name(obj)
        key = f"{tbl.lower()}|{normalized_obj}"
        tables.add(tbl)
        if key in ref_idx.measure_keys:
            measures.add((tbl, obj))
        else:
            columns.add((tbl, obj))

    # Parse unqualified references: [Measure] or [Column]
    for match in _UNQUALIFIED_TOKEN.finditer(cleaned):
        name = match.group(1).strip()
        if not name or name.startswith("@"):  # Skip parameters
            continue
        identifiers.add(name)
        normalized_name = _normalize_name(name)
        # First check if it's a known measure
        measure_owners = ref_idx.measure_names.get(normalized_name)
        if measure_owners:
            for tbl in measure_owners:
                measures.add((tbl, name))
        else:
            # Not a measure - check if it's a known column
            column_owners = ref_idx.column_names.get(normalized_name)
            if column_owners:
                # Add ALL matching columns - even if ambiguous, we should be conservative
                # and mark all possible columns as used rather than missing real usage
                for tbl in column_owners:
                    columns.add((tbl, name))
                    tables.add(tbl)
            else:
                # Unknown - assume measure with no table
                measures.add(("", name))

    # Parse table-only references: REMOVEFILTERS('d Period'), ALL('Calendar'), etc.
    # These are functions that take a bare table name (no column specifier)
    for match in _TABLE_ONLY_PATTERN.finditer(cleaned):
        tbl = match.group(1).strip()
        if tbl:
            tables.add(tbl)

    # Also catch unquoted table references: COUNTROWS(MyTable), etc.
    for match in _TABLE_ONLY_UNQUOTED_PATTERN.finditer(cleaned):
        tbl = match.group(1).strip()
        if tbl and tbl.lower() not in {
            'true', 'false', 'blank', 'null', 'error',
            'var', 'return', 'if', 'switch', 'not', 'and', 'or',
        }:
            # Only add if it looks like a known table name
            if _normalize_name(tbl) in {_normalize_name(t) for t in ref_idx.table_names}:
                tables.add(tbl)

    # Enhanced parsing when requested
    if enhanced:
        # Parse RELATED() references
        for match in _RELATED_PATTERN.finditer(cleaned):
            tbl = match.group(1).strip().strip("'")
            col = match.group(2).strip()
            relationship_refs.append(RelationshipReference(
                function="RELATED",
                from_table=tbl,
                from_column=col
            ))
            relationship_functions_used.add("RELATED")
            tables.add(tbl)
            columns.add((tbl, col))

        # Parse RELATEDTABLE() references
        for match in _RELATEDTABLE_PATTERN.finditer(cleaned):
            tbl = match.group(1).strip().strip("'")
            relationship_refs.append(RelationshipReference(
                function="RELATEDTABLE",
                from_table=tbl,
                from_column=None
            ))
            relationship_functions_used.add("RELATEDTABLE")
            tables.add(tbl)

        # Parse USERELATIONSHIP() - indicates inactive relationship usage
        for match in _USERELATIONSHIP_PATTERN.finditer(cleaned):
            tbl1 = match.group(1).strip().strip("'")
            col1 = match.group(2).strip()
            tbl2 = match.group(3).strip().strip("'")
            col2 = match.group(4).strip()
            relationship_refs.append(RelationshipReference(
                function="USERELATIONSHIP",
                from_table=tbl1,
                from_column=col1,
                to_table=tbl2,
                to_column=col2
            ))
            relationship_functions_used.add("USERELATIONSHIP")
            uses_inactive_relationships = True
            tables.add(tbl1)
            tables.add(tbl2)
            columns.add((tbl1, col1))
            columns.add((tbl2, col2))

        # Parse TREATAS() - virtual relationship
        for match in _TREATAS_PATTERN.finditer(cleaned):
            tbl = match.group(2).strip().strip("'")
            col = match.group(3).strip()
            relationship_refs.append(RelationshipReference(
                function="TREATAS",
                from_table=tbl,
                from_column=col
            ))
            relationship_functions_used.add("TREATAS")
            tables.add(tbl)
            columns.add((tbl, col))

        # Parse CROSSFILTER()
        for match in _CROSSFILTER_PATTERN.finditer(cleaned):
            tbl1 = match.group(1).strip().strip("'")
            col1 = match.group(2).strip()
            tbl2 = match.group(3).strip().strip("'")
            col2 = match.group(4).strip()
            direction = match.group(5).strip().upper()
            relationship_refs.append(RelationshipReference(
                function="CROSSFILTER",
                from_table=tbl1,
                from_column=col1,
                to_table=tbl2,
                to_column=col2,
                direction=direction
            ))
            relationship_functions_used.add("CROSSFILTER")
            tables.add(tbl1)
            tables.add(tbl2)
            columns.add((tbl1, col1))
            columns.add((tbl2, col2))

        # Parse VAR definitions
        for match in _VAR_PATTERN.finditer(cleaned):
            var_name = match.group(1)
            variables.append(VariableDefinition(
                name=var_name,
                position=match.start()
            ))

        # Parse CALCULATE filter columns
        for match in _CALCULATE_FILTER_PATTERN.finditer(cleaned):
            tbl = match.group(1).strip()
            col = match.group(2).strip()
            filter_columns.add((tbl, col))

    # Build result
    result = {
        "tables": sorted(tables),
        "columns": sorted(columns),
        "measures": sorted(measures),
        "identifiers": sorted(identifiers),
    }

    if enhanced:
        result.update({
            "relationship_refs": [
                {
                    "function": r.function,
                    "from_table": r.from_table,
                    "from_column": r.from_column,
                    "to_table": r.to_table,
                    "to_column": r.to_column,
                    "direction": r.direction,
                }
                for r in relationship_refs
            ],
            "variables": [{"name": v.name, "position": v.position} for v in variables],
            "filter_columns": sorted(filter_columns),
            "uses_inactive_relationships": uses_inactive_relationships,
            "relationship_functions_used": sorted(relationship_functions_used),
        })

    return result


def parse_dax_references_enhanced(
    expression: Optional[str],
    reference_index: Optional[DaxReferenceIndex] = None,
) -> DaxReferenceResult:
    """
    Parse DAX expression with full enhanced analysis.

    This is a convenience wrapper that always returns a DaxReferenceResult
    with all enhanced fields populated.

    Args:
        expression: The DAX expression to parse
        reference_index: Optional index to distinguish measures from columns

    Returns:
        DaxReferenceResult dataclass with all fields populated
    """
    result_dict = parse_dax_references(expression, reference_index, enhanced=True)

    return DaxReferenceResult(
        tables=result_dict.get("tables", []),
        columns=result_dict.get("columns", []),
        measures=result_dict.get("measures", []),
        identifiers=result_dict.get("identifiers", []),
        relationship_refs=[
            RelationshipReference(
                function=r["function"],
                from_table=r["from_table"],
                from_column=r["from_column"],
                to_table=r.get("to_table"),
                to_column=r.get("to_column"),
                direction=r.get("direction"),
            )
            for r in result_dict.get("relationship_refs", [])
        ],
        variables=[
            VariableDefinition(name=v["name"], position=v["position"])
            for v in result_dict.get("variables", [])
        ],
        filter_columns=result_dict.get("filter_columns", []),
        uses_inactive_relationships=result_dict.get("uses_inactive_relationships", False),
        relationship_functions_used=result_dict.get("relationship_functions_used", []),
    )


__all__ = [
    "DaxReferenceIndex",
    "DaxReferenceResult",
    "RelationshipReference",
    "VariableDefinition",
    "parse_dax_references",
    "parse_dax_references_enhanced",
    "normalize_dax_name",
]


def normalize_dax_name(name: str) -> str:
    """
    Public alias for name normalization used in DAX reference lookups.
    Normalizes: lowercase + collapse whitespace.
    Use this when building lookups that need to match DAX references.
    """
    return _normalize_name(name)