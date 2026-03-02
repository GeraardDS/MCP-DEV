"""
Visual Query Builder

Builds executable DAX queries that reproduce visual behavior by combining:
- PBIP report/page/visual filter definitions
- Slicer selections (saved state from PBIP)
- Live model query execution
"""

import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from .filter_to_dax import FilterToDaxConverter, FilterExpression

logger = logging.getLogger(__name__)

# Visual types that are slicers (standard slicer + advanced/chiclet slicers)
SLICER_VISUAL_TYPES = {'slicer', 'advancedSlicerVisual'}

# Visual types that are UI/layout elements, not data-bearing visuals
UI_VISUAL_TYPES = {
    'shape', 'basicShape', 'image', 'textbox',
    'button', 'actionButton',
    'bookmarkNavigator', 'pageNavigator', 'navigatorButton',
    'visualGroup', 'group',
    'slicer', 'advancedSlicerVisual',
    'multiRowCard',  # Multi-row cards are typically label/context displays
}

# Visual types that display actual data (analytical visuals)
DATA_VISUAL_TYPES = {
    'pivotTable', 'matrix', 'table', 'tableEx',
    'barChart', 'clusteredBarChart', 'stackedBarChart', 'hundredPercentStackedBarChart',
    'columnChart', 'clusteredColumnChart', 'stackedColumnChart', 'hundredPercentStackedColumnChart',
    'lineChart', 'areaChart', 'stackedAreaChart', 'lineStackedColumnComboChart', 'lineClusteredColumnComboChart',
    'pieChart', 'donutChart', 'treemap', 'funnel',
    'scatterChart', 'bubbleChart',
    'map', 'filledMap', 'azureMap', 'shapeMap',
    'gauge', 'kpi', 'card', 'multiRowCard',
    'waterfallChart', 'ribbonChart', 'decompositionTreeVisual',
    'keyInfluencers', 'qnaVisual',
    'scriptVisual', 'pythonVisual', 'rScript',
}

# Visual types that include grand total rows (need ROLLUPADDISSUBTOTAL in SUMMARIZECOLUMNS)
SUBTOTAL_VISUAL_TYPES = {'pivotTable', 'matrix', 'table', 'tableEx'}


@dataclass
class VisualInfo:
    """Information about a visual from PBIP."""
    visual_id: str
    visual_type: str
    visual_name: Optional[str]
    page_name: str
    page_id: str
    title: Optional[str]
    measures: List[str] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    filters: List[Dict] = field(default_factory=list)


@dataclass
class SlicerState:
    """Current slicer state from PBIP."""
    slicer_id: str
    page_name: str
    table: str
    column: str
    field_reference: str
    selected_values: List[Any]
    selection_mode: str
    is_inverted: bool
    affects_all_pages: bool = False
    # Multi-column composite TREATAS support (sf Row Drill, sf Slicer 1, etc.)
    extra_columns: List[str] = field(default_factory=list)  # Additional 'Table'[Col] refs
    composite_values: Optional[List[List[Any]]] = None  # Value tuples, one per selected row


@dataclass
class FilterContext:
    """Complete filter context for a visual."""
    report_filters: List[FilterExpression] = field(default_factory=list)
    page_filters: List[FilterExpression] = field(default_factory=list)
    visual_filters: List[FilterExpression] = field(default_factory=list)
    slicer_filters: List[FilterExpression] = field(default_factory=list)

    def all_filters(self) -> List[FilterExpression]:
        """Get all filters combined."""
        return self.report_filters + self.page_filters + self.visual_filters + self.slicer_filters

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        def filter_to_dict(f):
            """Convert a FilterExpression to a dict with all relevant fields."""
            return {
                'dax': f.dax,
                'source': f.source,
                'table': f.table,
                'column': f.column,
                'values': f.values,
                'condition_type': f.condition_type,
                'is_field_parameter': f.is_field_parameter,
                'classification': getattr(f, 'classification', 'data'),
                'has_null_values': getattr(f, 'has_null_values', False)
            }

        return {
            'report_filters': [filter_to_dict(f) for f in self.report_filters],
            'page_filters': [filter_to_dict(f) for f in self.page_filters],
            'visual_filters': [filter_to_dict(f) for f in self.visual_filters],
            'slicer_filters': [filter_to_dict(f) for f in self.slicer_filters]
        }

    def data_filters_only(self) -> List:
        """Get only data filters (excluding field parameters and UI controls)."""
        from .filter_to_dax import FilterClassification
        all_f = self.all_filters()
        return [f for f in all_f if getattr(f, 'classification', 'data') == FilterClassification.DATA]

    def field_parameter_filters(self) -> List:
        """Get only field parameter filters."""
        from .filter_to_dax import FilterClassification
        all_f = self.all_filters()
        return [f for f in all_f if getattr(f, 'classification', 'data') == FilterClassification.FIELD_PARAMETER]

    def ui_control_filters(self) -> List:
        """Get only UI control filters."""
        from .filter_to_dax import FilterClassification
        all_f = self.all_filters()
        return [f for f in all_f if getattr(f, 'classification', 'data') == FilterClassification.UI_CONTROL]


@dataclass
class MeasureDefinition:
    """Measure definition from the model."""
    name: str
    expression: str
    table: Optional[str] = None
    format_string: Optional[str] = None


@dataclass
class VisualQueryResult:
    """Result of building a visual query."""
    visual_info: VisualInfo
    filter_context: FilterContext
    dax_query: str
    measure_name: str
    measure_expression: Optional[str] = None
    measure_definitions: List[MeasureDefinition] = field(default_factory=list)
    expanded_query: Optional[str] = None  # Query with measure expressions inline
    filter_breakdown: Dict[str, Any] = field(default_factory=dict)


class VisualQueryBuilder:
    """
    Builds executable DAX queries that reproduce visual behavior.

    Combines PBIP analysis with live model capabilities to:
    - Extract complete filter context for any visual
    - Generate DAX queries with all filters applied
    - Support measure comparison and detail drilling
    """

    def __init__(self, pbip_folder_path: str):
        """
        Initialize the builder.

        Args:
            pbip_folder_path: Path to the PBIP project folder (contains definition/)
        """
        self.pbip_folder = Path(pbip_folder_path)
        self.definition_path = self.pbip_folder / 'definition'

        # For .Report folders, definition is directly inside
        if not self.definition_path.exists():
            # Check if this is a .Report folder structure
            report_path = self.pbip_folder / 'report.json'
            if report_path.exists():
                self.definition_path = self.pbip_folder

        self.converter = FilterToDaxConverter()
        self.logger = logging.getLogger(__name__)

        # Cache
        self._report_filters_cache: Optional[List[Dict]] = None
        self._slicers_cache: Dict[str, List[SlicerState]] = {}  # Per-page slicer cache
        self._page_filters_cache: Dict[str, List[Dict]] = {}  # Per-page filter cache
        self._page_path_cache: Dict[str, Optional[Path]] = {}  # Page name -> path cache
        self._column_types_loaded: bool = False
        self._query_executor = None  # Reference to connected query executor
        self._measure_cache: Dict[str, MeasureDefinition] = {}  # Cache measure definitions
        self._all_measures_loaded: bool = False  # Flag for batch measure loading

        # Advanced analysis components (lazy initialized)
        self._semantic_classifier = None
        self._relationship_resolver = None
        self._aggregation_matcher = None

    def _init_semantic_classifier(self):
        """Lazy initialize semantic classifier."""
        if self._semantic_classifier is None and self._query_executor:
            from .semantic_classifier import SemanticFilterClassifier
            self._semantic_classifier = SemanticFilterClassifier(self._query_executor)
        return self._semantic_classifier

    def _init_relationship_resolver(self):
        """Lazy initialize relationship resolver."""
        if self._relationship_resolver is None and self._query_executor:
            from .relationship_resolver import RelationshipResolver
            self._relationship_resolver = RelationshipResolver(self._query_executor)
        return self._relationship_resolver

    def _init_aggregation_matcher(self):
        """Lazy initialize aggregation matcher."""
        if self._aggregation_matcher is None and self._query_executor:
            from .aggregation_matcher import AggregationMatcher
            self._aggregation_matcher = AggregationMatcher(self._query_executor)
        return self._aggregation_matcher

    def load_column_types(self, query_executor) -> int:
        """
        Load column data types from the connected model.

        This improves type detection for filter values, ensuring
        string columns get string filter values (e.g., "0" not 0).

        Args:
            query_executor: Connected QueryExecutor instance

        Returns:
            Number of column types loaded
        """
        # Store reference to query executor for later use
        self._query_executor = query_executor

        if self._column_types_loaded:
            return 0

        count = self.converter.load_column_types_from_model(query_executor)
        if count > 0:
            self._column_types_loaded = True
        return count

    def _load_all_measures_from_dmv(self) -> bool:
        """
        Batch load all measures from DMV in a single query.

        This is much faster than querying measures individually, especially
        for documentation operations that need all measure definitions.

        Returns:
            True if measures were loaded, False otherwise
        """
        if self._all_measures_loaded or not self._query_executor:
            return self._all_measures_loaded

        try:
            # Query all measures in one call
            measures_result = self._query_executor.execute_info_query("MEASURES")
            if not measures_result.get('success') or not measures_result.get('rows'):
                return False

            # Query all tables once for ID -> name mapping
            table_id_to_name = {}
            tables_result = self._query_executor.execute_info_query("TABLES")
            if tables_result.get('success') and tables_result.get('rows'):
                for table_row in tables_result['rows']:
                    tid = str(table_row.get('ID', table_row.get('[ID]', '')))
                    tname = table_row.get('Name', table_row.get('[Name]', ''))
                    if tid and tname:
                        table_id_to_name[tid] = tname

            # Populate the cache with all measures
            for row in measures_result['rows']:
                name = row.get('Name', row.get('[Name]', ''))
                if not name:
                    continue

                expression = row.get('Expression', row.get('[Expression]', ''))
                table_id = str(row.get('TableID', row.get('[TableID]', '')))
                format_string = row.get('FormatString', row.get('[FormatString]', ''))

                table_name = table_id_to_name.get(table_id)

                measure_def = MeasureDefinition(
                    name=name,
                    expression=expression,
                    table=table_name,
                    format_string=format_string
                )
                # Cache by both original and lowercase name for case-insensitive lookup
                self._measure_cache[name] = measure_def
                self._measure_cache[name.lower()] = measure_def

            self._all_measures_loaded = True
            self.logger.debug(f"Batch loaded {len(measures_result['rows'])} measures from DMV")
            return True

        except Exception as e:
            self.logger.debug(f"Error batch loading measures: {e}")
            return False

    def get_measure_expression(self, measure_name: str) -> Optional[MeasureDefinition]:
        """
        Get the DAX expression for a measure from the model.

        Tries multiple sources in order:
        1. Cache (populated by batch load if available)
        2. Live model via batch DMV query (loads all measures at once)
        3. PBIP TMDL files (offline fallback)

        Args:
            measure_name: Measure name (with or without brackets)

        Returns:
            MeasureDefinition with the measure's DAX expression, or None
        """
        # Clean measure name
        clean_name = measure_name.strip('[]')

        # Check cache first
        if clean_name in self._measure_cache:
            return self._measure_cache[clean_name]
        if clean_name.lower() in self._measure_cache:
            return self._measure_cache[clean_name.lower()]

        # Try batch loading all measures (much faster for multiple lookups)
        if self._query_executor and not self._all_measures_loaded:
            self._load_all_measures_from_dmv()
            # Check cache again after batch load
            if clean_name in self._measure_cache:
                return self._measure_cache[clean_name]
            if clean_name.lower() in self._measure_cache:
                return self._measure_cache[clean_name.lower()]

        # Try 2: Search PBIP TMDL files (offline fallback)
        measure_def = self._get_measure_from_tmdl(clean_name)
        if measure_def:
            self._measure_cache[clean_name] = measure_def
            return measure_def

        self.logger.debug(f"Could not find measure '{clean_name}' in model or TMDL files")
        return None

    def _get_measure_from_dmv(self, measure_name: str) -> Optional[MeasureDefinition]:
        """Get measure expression from live model via MEASURES DMV."""
        if not self._query_executor:
            return None

        try:
            result = self._query_executor.execute_info_query("MEASURES")
            if not result.get('success') or not result.get('rows'):
                return None

            for row in result['rows']:
                name = row.get('Name', row.get('[Name]', ''))
                if name.lower() == measure_name.lower():
                    expression = row.get('Expression', row.get('[Expression]', ''))
                    table_id = row.get('TableID', row.get('[TableID]', ''))
                    format_string = row.get('FormatString', row.get('[FormatString]', ''))

                    # Get table name from TableID if possible
                    table_name = None
                    if table_id:
                        tables_result = self._query_executor.execute_info_query("TABLES")
                        if tables_result.get('success') and tables_result.get('rows'):
                            for table_row in tables_result['rows']:
                                tid = table_row.get('ID', table_row.get('[ID]', ''))
                                if str(tid) == str(table_id):
                                    table_name = table_row.get('Name', table_row.get('[Name]', ''))
                                    break

                    return MeasureDefinition(
                        name=measure_name,
                        expression=expression,
                        table=table_name,
                        format_string=format_string
                    )

            return None

        except Exception as e:
            self.logger.warning(f"Error fetching measure from DMV: {e}")
            return None

    def _get_measure_from_tmdl(self, measure_name: str) -> Optional[MeasureDefinition]:
        """
        Get measure expression from PBIP TMDL files.

        TMDL files are located in the semantic model folder with .tmdl extension.
        Measures are defined in table-specific .tmdl files with syntax:
            measure 'Measure Name' = <DAX expression>

        Args:
            measure_name: The measure name to search for

        Returns:
            MeasureDefinition if found, None otherwise
        """
        try:
            # Find semantic model folder - look for .tmdl files
            semantic_model_path = self._find_semantic_model_path()
            if not semantic_model_path:
                self.logger.debug("No semantic model path found for TMDL lookup")
                return None

            # Search all .tmdl files for the measure
            tmdl_files = list(semantic_model_path.glob('**/*.tmdl'))
            self.logger.debug(f"Searching {len(tmdl_files)} TMDL files for measure '{measure_name}'")

            for tmdl_file in tmdl_files:
                try:
                    result = self._parse_measure_from_tmdl(tmdl_file, measure_name)
                    if result:
                        return result
                except Exception as e:
                    self.logger.debug(f"Error parsing {tmdl_file}: {e}")
                    continue

            return None

        except Exception as e:
            self.logger.warning(f"Error searching TMDL files: {e}")
            return None

    def _find_semantic_model_path(self) -> Optional[Path]:
        """Find the semantic model folder containing TMDL files."""
        # Common locations relative to PBIP folder
        possible_paths = [
            self.pbip_folder / 'definition' / 'model.bim',
            self.pbip_folder.parent / f'{self.pbip_folder.stem.replace(".Report", ".SemanticModel")}',
            self.pbip_folder.parent / f'{self.pbip_folder.stem}.SemanticModel',
        ]

        # Check for .SemanticModel folder sibling to .Report folder
        if '.Report' in str(self.pbip_folder):
            semantic_folder = Path(str(self.pbip_folder).replace('.Report', '.SemanticModel'))
            if semantic_folder.exists():
                definition_folder = semantic_folder / 'definition'
                if definition_folder.exists():
                    return definition_folder

        # Check for model folder within PBIP
        for path_pattern in ['definition/tables', 'definition/model', 'model/definition/tables']:
            model_path = self.pbip_folder / path_pattern
            if model_path.exists():
                return model_path.parent

        # Check if there are any .tmdl files in definition folder
        definition_tmdl = list((self.pbip_folder / 'definition').glob('**/*.tmdl'))
        if definition_tmdl:
            return self.pbip_folder / 'definition'

        return None

    def _parse_measure_from_tmdl(self, tmdl_file: Path, measure_name: str) -> Optional[MeasureDefinition]:
        """
        Parse a measure definition from a TMDL file.

        TMDL syntax for measures:
            measure 'Measure Name' = <DAX expression>
            or
            measure MeasureName = <DAX expression>

        Args:
            tmdl_file: Path to the TMDL file
            measure_name: Name of the measure to find

        Returns:
            MeasureDefinition if found, None otherwise
        """
        try:
            content = tmdl_file.read_text(encoding='utf-8')

            # Get table name from file path (usually tables/TableName.tmdl)
            table_name = None
            if 'tables' in str(tmdl_file):
                table_name = tmdl_file.stem

            # Search for measure definition
            # Patterns: measure 'Name' = ... or measure Name = ...
            import re

            # Pattern 1: measure 'Measure Name' = ...
            pattern_quoted = rf"measure\s+'({re.escape(measure_name)})'\s*=\s*"
            # Pattern 2: measure MeasureName = ...
            pattern_unquoted = rf"measure\s+({re.escape(measure_name)})\s*=\s*"

            match = None
            for pattern in [pattern_quoted, pattern_unquoted]:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    break

            if not match:
                return None

            # Found the measure - now extract the expression
            start_pos = match.end()

            # The expression continues until we hit certain keywords or end of section
            # Look for: formatString, displayFolder, another measure, or section end
            end_markers = [
                r'\n\s*measure\s+',       # Next measure
                r'\n\s*column\s+',         # Column definition
                r'\n\s*formatString\s*=',  # Format string property
                r'\n\s*displayFolder\s*=', # Display folder property
                r'\n\s*description\s*=',   # Description property
                r'\n\s*isHidden\s*=',      # Hidden property
                r'\ntable\s+',             # Next table
                r'\n\s*\n\s*\n',           # Double newline (section break)
            ]

            expression_end = len(content)
            for marker in end_markers:
                marker_match = re.search(marker, content[start_pos:], re.IGNORECASE)
                if marker_match:
                    end_pos = start_pos + marker_match.start()
                    if end_pos < expression_end:
                        expression_end = end_pos

            expression = content[start_pos:expression_end].strip()

            # Extract format string if present
            format_string = None
            format_match = re.search(
                rf"formatString\s*=\s*(['\"])(.+?)\1",
                content[expression_end:expression_end + 500],
                re.IGNORECASE
            )
            if format_match:
                format_string = format_match.group(2)

            if expression:
                self.logger.debug(f"Found measure '{measure_name}' in {tmdl_file}")
                return MeasureDefinition(
                    name=measure_name,
                    expression=expression,
                    table=table_name,
                    format_string=format_string
                )

            return None

        except Exception as e:
            self.logger.debug(f"Error parsing TMDL file {tmdl_file}: {e}")
            return None

    def get_measure_expressions(self, measure_names: List[str]) -> Dict[str, MeasureDefinition]:
        """
        Get DAX expressions for multiple measures.

        Args:
            measure_names: List of measure names

        Returns:
            Dict mapping measure name to MeasureDefinition
        """
        result = {}
        for name in measure_names:
            measure_def = self.get_measure_expression(name)
            if measure_def:
                result[measure_def.name] = measure_def
        return result

    def get_visual_filter_context(
        self,
        page_name: str,
        visual_id: Optional[str] = None,
        visual_name: Optional[str] = None,
        include_slicers: bool = True
    ) -> Tuple[Optional[VisualInfo], FilterContext]:
        """
        Get complete filter context for a visual.

        Args:
            page_name: Display name of the page
            visual_id: ID of the visual (optional if visual_name provided)
            visual_name: Name of the visual (optional if visual_id provided)
            include_slicers: Whether to include slicer selections

        Returns:
            Tuple of (VisualInfo, FilterContext) or (None, empty FilterContext)
        """
        filter_context = FilterContext()

        # Find the page
        page_path = self._find_page_by_name(page_name)
        if not page_path:
            self.logger.warning(f"Page not found: {page_name}")
            return None, filter_context

        # Find the visual
        visual_info = self._find_visual(page_path, visual_id, visual_name)
        if not visual_info:
            self.logger.warning(f"Visual not found: id={visual_id}, name={visual_name}")
            return None, filter_context

        # 1. Get report-level filters
        report_filters = self._get_report_filters()
        for f in report_filters:
            expr = self.converter.convert_filter(f, source='report')
            if expr:
                filter_context.report_filters.append(expr)

        # 2. Get page-level filters
        page_filters = self._get_page_filters(page_path)
        for f in page_filters:
            expr = self.converter.convert_filter(f, source='page')
            if expr:
                filter_context.page_filters.append(expr)

        # 3. Get visual-level filters
        for f in visual_info.filters:
            expr = self.converter.convert_filter(f, source='visual')
            if expr:
                filter_context.visual_filters.append(expr)

        # 4. Get slicer selections
        if include_slicers:
            slicers = self._get_page_slicers(page_path, page_name)
            for slicer in slicers:
                slicer_info = {
                    'entity': slicer.table,
                    'property': slicer.column,
                    'selected_values': slicer.selected_values,
                    'is_inverted_selection': slicer.is_inverted,
                    'selection_mode': slicer.selection_mode,
                    'extra_columns': slicer.extra_columns,
                    'composite_values': slicer.composite_values,
                }
                expr = self.converter.convert_slicer_selection(slicer_info)
                if expr:
                    filter_context.slicer_filters.append(expr)

        return visual_info, filter_context

    def build_visual_query(
        self,
        page_name: str,
        visual_id: Optional[str] = None,
        visual_name: Optional[str] = None,
        measure_name: Optional[str] = None,
        include_slicers: bool = True,
        expand_measures: bool = True,
        measures: Optional[List[str]] = None,
    ) -> Optional[VisualQueryResult]:
        """
        Build a DAX query that reproduces what a visual shows.

        Args:
            page_name: Display name of the page
            visual_id: ID of the visual
            visual_name: Name of the visual
            measure_name: Specific measure to query (default: all measures in visual)
            include_slicers: Whether to include slicer selections
            expand_measures: Whether to fetch and expand actual measure DAX expressions

        Returns:
            VisualQueryResult with DAX query and context, or None if failed
        """
        visual_info, filter_context = self.get_visual_filter_context(
            page_name, visual_id, visual_name, include_slicers
        )

        if not visual_info:
            return None

        # Determine measures to use (explicit list > single name > visual auto-discovery)
        if measures:
            target_measures = [m if m.startswith('[') else f'[{m}]' for m in measures]
        elif measure_name:
            target_measures = [measure_name if measure_name.startswith('[') else f'[{measure_name}]']
        elif visual_info.measures:
            target_measures = [m if m.startswith('[') else f'[{m}]' for m in visual_info.measures]
        else:
            self.logger.warning("No measure specified and visual has no measures")
            return None

        # Get grouping columns from the visual
        grouping_columns = visual_info.columns if visual_info.columns else []

        # All filters assembled here; _build_visual_dax_query handles classification
        all_filters = filter_context.all_filters()

        # For backward compatibility, use first measure as the target
        target_measure = target_measures[0]

        # Fetch actual measure expressions from the model (needed for table-qualified
        # refs, format-string detection, and the expanded query)
        measure_definitions = []
        expanded_query = None
        measure_table_map: Dict[str, str] = {}
        format_string_measures: List[str] = []

        if expand_measures and self._query_executor:
            measure_defs = self.get_measure_expressions(target_measures)
            measure_definitions = list(measure_defs.values())

            # Table-qualified measure references (e.g. 'm Measure'[Net Asset Value])
            measure_table_map = {m.name: m.table for m in measure_definitions if m.table}

            # Detect format-string companion measures (_MeasureName FormatString)
            # and add them with IGNORE() so SUMMARIZECOLUMNS doesn't blank-filter them
            if self._all_measures_loaded:
                for m_def in measure_definitions:
                    fs_name = f"_{m_def.name} FormatString"
                    fs_def = self._measure_cache.get(fs_name)
                    if fs_def and fs_def.table:
                        format_string_measures.append(f"'{fs_def.table}'[{fs_name}]")

            # Build expanded query with actual measure DAX
            if measure_definitions:
                expanded_query = self._build_expanded_dax_query(
                    measure_definitions, grouping_columns, all_filters
                )

        # Use ROLLUPADDISSUBTOTAL for matrix/table visuals (they have grand total rows)
        include_grand_total = getattr(visual_info, 'visual_type', None) in SUBTOTAL_VISUAL_TYPES

        # Build the PBI-accurate DEFINE/EVALUATE query with TREATAS filter vars
        dax_query = self._build_visual_dax_query(
            target_measures,
            grouping_columns,
            all_filters,
            measure_table_map=measure_table_map,
            include_grand_total=include_grand_total,
            format_string_measures=format_string_measures,
        )

        # Build filter breakdown for documentation
        filter_breakdown = {
            'report_level': [
                {'table': f.table, 'column': f.column, 'type': f.condition_type, 'values': f.values, 'dax': f.dax}
                for f in filter_context.report_filters
            ],
            'page_level': [
                {'table': f.table, 'column': f.column, 'type': f.condition_type, 'values': f.values, 'dax': f.dax}
                for f in filter_context.page_filters
            ],
            'visual_level': [
                {'table': f.table, 'column': f.column, 'type': f.condition_type, 'values': f.values, 'dax': f.dax}
                for f in filter_context.visual_filters
            ],
            'slicer': [
                {'table': f.table, 'column': f.column, 'type': f.condition_type, 'values': f.values, 'dax': f.dax}
                for f in filter_context.slicer_filters
            ]
        }

        return VisualQueryResult(
            visual_info=visual_info,
            filter_context=filter_context,
            dax_query=dax_query,
            measure_name=target_measure,
            measure_definitions=measure_definitions,
            expanded_query=expanded_query,
            filter_breakdown=filter_breakdown
        )

    def _format_value_for_treatas(self, val: Any) -> str:
        """Format a single value for inclusion in a TREATAS set literal.

        Handles TypedValue wrappers (duck-typed) as well as raw Python scalars.
        """
        # Duck-type TypedValue (has .value + .value_type attributes)
        if hasattr(val, 'value') and hasattr(val, 'value_type'):
            if val.value is None:
                return 'BLANK()'
            raw, vt = val.value, val.value_type
            if vt == 'string':
                escaped = str(raw).replace('"', '""')
                return f'"{escaped}"'
            if vt == 'boolean':
                return 'TRUE' if str(raw).lower() == 'true' else 'FALSE'
            if vt in ('integer', 'decimal'):
                return str(raw)
            val = raw  # unknown sub-type — fall through
        if val is None:
            return 'BLANK()'
        if isinstance(val, bool):
            return 'TRUE' if val else 'FALSE'
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return str(val)
        escaped = str(val).replace('"', '""')
        return f'"{escaped}"'

    def _format_values_as_treatas_set(self, values: List[Any]) -> str:
        """Format a list of filter values as a DAX set literal: {v1, v2, ...}"""
        parts = [self._format_value_for_treatas(v) for v in (values or [])]
        return '{' + ', '.join(parts) + '}' if parts else '{BLANK()}'

    def _build_composite_treatas(self, f) -> str:
        """Build a multi-column composite TREATAS expression.

        Produces:
            TREATAS(
                {("Cat1", "Field1"), ("Cat2", "Field2")},
                'Table'[Column1],
                'Table'[Column2]
            )
        """
        rows = []
        for tuple_vals in (f.composite_tuples or []):
            parts = [self._format_value_for_treatas(v) for v in tuple_vals]
            rows.append('(' + ', '.join(parts) + ')')

        values_set = '{' + ',\n                '.join(rows) + '}' if rows else '{}'
        col_refs = ',\n            '.join(f.composite_columns)
        return f"TREATAS(\n            {values_set},\n            {col_refs}\n        )"

    def _build_visual_dax_query(
        self,
        measures: List[str],
        grouping_columns: List[str],
        filters: List,
        fact_table: Optional[str] = None,
        measure_table_map: Optional[Dict[str, str]] = None,
        include_grand_total: bool = False,
        row_limit: int = 502,
        format_string_measures: Optional[List[str]] = None,
    ) -> str:
        """
        Build a DAX query that reproduces the visual's data.

        Uses the same DEFINE/EVALUATE + TREATAS filter vars + SUMMARIZECOLUMNS
        structure that Power BI Desktop actually sends to the engine, producing
        accurate SE/FE timing profiles when run via NativeTraceRunner.

        For visuals with grouping columns (matrix, chart, table) the query is:
            DEFINE
                VAR __DS0FilterTable  = TREATAS({val}, 'T'[C])
                ...
                VAR __DS0Core         = SUMMARIZECOLUMNS(col, __DS0FilterTable..., "M", [M])
                VAR __DS0PrimaryWindowed = TOPN(502, __DS0Core, col, 1)
            EVALUATE __DS0PrimaryWindowed
            ORDER BY col

        For card/KPI visuals (no grouping columns) a ROW() query is returned,
        with TREATAS filter vars passed to CALCULATE when filters are present.

        Args:
            measures: List of measure references (e.g., ['[Total Sales]', '[Profit]'])
            grouping_columns: List of column refs for grouping (e.g., ["'Date'[Year]"])
            filters: List of FilterExpression objects
            fact_table: Unused (kept for backward compatibility)
            measure_table_map: Optional dict mapping measure name -> table name for
                               table-qualified refs like 'm Measure'[Net Asset Value]
            include_grand_total: When True, wraps groupby column in ROLLUPADDISSUBTOTAL
                                 and orders by [IsGrandTotalRowTotal] DESC (matrix/table)
            row_limit: Row limit passed to TOPN (default 502 matches PBI page size)
            format_string_measures: Optional list of table-qualified format-string measure
                                    refs to add with IGNORE(), e.g.
                                    ["'m Measure'[_Net Asset Value FormatString]"]

        Returns:
            Complete DAX query string starting with DEFINE or EVALUATE
        """
        from .filter_to_dax import FilterClassification

        # --- 1. Classify filters ---
        data_filters: List = []
        field_param_filters: List = []

        for f in filters:
            if not f.dax:
                continue
            classification = getattr(f, 'classification', FilterClassification.DATA)
            if classification == FilterClassification.UI_CONTROL:
                continue  # formatting/display only — never affects data
            elif classification == FilterClassification.FIELD_PARAMETER:
                field_param_filters.append(f)
            else:
                data_filters.append(f)

        # Data filters first, then field parameter filters (matches PBI ordering)
        active_filters = data_filters + field_param_filters

        # --- 2. Build TREATAS var declarations ---
        # Each filter becomes either:
        #   Single-col: VAR __DS0FilterTableN = TREATAS({values}, 'T'[C])
        #   Composite:  VAR __DS0FilterTableN = TREATAS({(v1a,v1b),...}, 'T'[C1], 'T'[C2])
        treatas_vars: List[Tuple[str, str]] = []
        for i, f in enumerate(active_filters):
            var_name = "__DS0FilterTable" if i == 0 else f"__DS0FilterTable{i + 1}"
            if f.composite_columns and f.composite_tuples is not None:
                treatas_expr = self._build_composite_treatas(f)
            else:
                values_set = self._format_values_as_treatas_set(f.values)
                treatas_expr = f"TREATAS({values_set}, '{f.table}'[{f.column}])"
            treatas_vars.append((var_name, treatas_expr))

        # --- 3. No grouping columns → ROW() query for card/KPI visuals ---
        if not grouping_columns:
            if treatas_vars:
                # Build DEFINE block so we can reference filter vars in CALCULATE
                define_lines = [
                    f"    VAR {vn} =\n        {expr}" for vn, expr in treatas_vars
                ]
                filter_var_refs = ", ".join(vn for vn, _ in treatas_vars)
                row_parts = []
                for m in measures:
                    alias = m.strip('[]').replace(' ', '_')
                    row_parts.append(f'    "{alias}", CALCULATE({m}, {filter_var_refs})')
                define_block = "\n".join(define_lines)
                row_body = ",\n".join(row_parts)
                return f"DEFINE\n{define_block}\n\nEVALUATE\nROW(\n{row_body}\n)"
            else:
                # No filters — simple ROW
                row_parts = [f'    "{m.strip("[]").replace(" ", "_")}", {m}' for m in measures]
                return f"EVALUATE\nROW(\n{','.join(row_parts)}\n)"

        # --- 4. Build SUMMARIZECOLUMNS arguments ---
        sc_args: List[str] = []

        # 4a. Groupby columns — with optional ROLLUPADDISSUBTOTAL for matrix/table
        first_col = grouping_columns[0]
        if include_grand_total:
            sc_args.append(f"        ROLLUPADDISSUBTOTAL({first_col}, \"IsGrandTotalRowTotal\")")
            for col in grouping_columns[1:]:
                sc_args.append(f"        {col}")
        else:
            for col in grouping_columns:
                sc_args.append(f"        {col}")

        # 4b. Filter table references (direct SUMMARIZECOLUMNS args — not CALCULATETABLE)
        for var_name, _ in treatas_vars:
            sc_args.append(f"        {var_name}")

        # 4c. Measure name-expression pairs (table-qualified when available)
        for m in measures:
            m_name = m.strip('[]')
            alias = m_name.replace(' ', '_')
            if measure_table_map and m_name in measure_table_map:
                m_ref = f"'{measure_table_map[m_name]}'[{m_name}]"
            else:
                m_ref = m
            sc_args.append(f"        \"{alias}\", {m_ref}")

        # 4d. Format string companion measures wrapped in IGNORE()
        for fs_ref in (format_string_measures or []):
            # Derive alias from measure name inside the ref: 'Table'[_Name] -> v__Name_FormatString
            try:
                fs_name = fs_ref.split('[')[1].rstrip(']')
                fs_alias = "v_" + fs_name.replace(' ', '_').lstrip('_')
            except (IndexError, AttributeError):
                fs_alias = "v_FormatString"
            sc_args.append(f"        \"{fs_alias}\", IGNORE({fs_ref})")

        sc_body = ",\n".join(sc_args)

        # --- 5. Build DEFINE block ---
        define_lines: List[str] = []

        # TREATAS filter vars
        for var_name, treatas_expr in treatas_vars:
            define_lines.append(f"    VAR {var_name} =\n        {treatas_expr}")

        # Core SUMMARIZECOLUMNS var
        define_lines.append(
            f"    VAR __DS0Core =\n        SUMMARIZECOLUMNS(\n{sc_body}\n        )"
        )

        # TOPN windowed var
        if include_grand_total:
            define_lines.append(
                f"    VAR __DS0PrimaryWindowed =\n"
                f"        TOPN({row_limit}, __DS0Core, [IsGrandTotalRowTotal], 0, {first_col}, 1)"
            )
            order_by = f"[IsGrandTotalRowTotal] DESC, {first_col}"
        else:
            define_lines.append(
                f"    VAR __DS0PrimaryWindowed =\n"
                f"        TOPN({row_limit}, __DS0Core, {first_col}, 1)"
            )
            order_by = first_col

        define_block = "\n".join(define_lines)
        return (
            f"DEFINE\n{define_block}\n\n"
            f"EVALUATE __DS0PrimaryWindowed\n"
            f"ORDER BY {order_by}"
        )

    def _build_expanded_dax_query(
        self,
        measure_definitions: List[MeasureDefinition],
        grouping_columns: List[str],
        filters: List
    ) -> str:
        """
        Build a DAX query with the actual measure expressions expanded inline.

        This shows exactly what DAX is being evaluated with filters applied,
        which is useful for debugging measure behavior.

        Args:
            measure_definitions: List of MeasureDefinition objects with actual DAX
            grouping_columns: List of column references for grouping
            filters: List of FilterExpression objects

        Returns:
            Complete DAX query with measure expressions expanded
        """
        # Filter out non-data filters (same as _build_visual_dax_query)
        from .filter_to_dax import FilterClassification

        data_filters = []
        for f in filters:
            if f.dax:
                classification = getattr(f, 'classification', FilterClassification.DATA)
                if classification in (FilterClassification.FIELD_PARAMETER, FilterClassification.UI_CONTROL):
                    continue  # Skip field parameters and UI controls
                data_filters.append(f)

        # Build optimized filter list
        filter_dax_list = []
        for f in data_filters:
            if len(f.values) == 1 and f.condition_type == 'In':
                val = f.values[0]
                if val is None or str(val).lower() == 'null':
                    filter_dax_list.append(f"ISBLANK('{f.table}'[{f.column}])")
                elif isinstance(val, bool):
                    filter_dax_list.append(f"'{f.table}'[{f.column}] = {str(val).upper()}")
                elif isinstance(val, (int, float)):
                    filter_dax_list.append(f"'{f.table}'[{f.column}] = {val}")
                else:
                    val_str = str(val).replace('"', '""')
                    filter_dax_list.append(f"'{f.table}'[{f.column}] = \"{val_str}\"")
            else:
                filter_dax_list.append(f.dax)

        # Build measure parts with actual expressions
        measure_parts = []
        for measure_def in measure_definitions:
            expr = measure_def.expression.strip()
            # Wrap in CALCULATE if we have filters
            if filter_dax_list:
                filters_str = ',\n        '.join(filter_dax_list)
                measure_parts.append(f'''"{measure_def.name}",
    CALCULATE(
        {expr},
        {filters_str}
    )''')
            else:
                measure_parts.append(f'"{measure_def.name}",\n    {expr}')

        if not measure_parts:
            return ""

        if grouping_columns:
            # Extract tables from all columns to detect multi-table scenarios
            tables_in_columns = set()
            for col in grouping_columns:
                if "'" in col and '[' in col:
                    table_name = col.split('[')[0]
                    tables_in_columns.add(table_name)

            # Determine if we can use SUMMARIZE (single table) or need SUMMARIZECOLUMNS (multi-table)
            fact_table = None
            use_summarize = False
            if len(tables_in_columns) == 1:
                fact_table = list(tables_in_columns)[0]
                use_summarize = True

            columns_str = ',\n        '.join(grouping_columns)
            measures_str = ',\n    '.join(measure_parts)

            if filter_dax_list:
                filters_str = ',\n    '.join(filter_dax_list)
                if use_summarize and fact_table:
                    query = f'''EVALUATE
CALCULATETABLE(
    ADDCOLUMNS(
        SUMMARIZE(
            {fact_table},
            {columns_str}
        ),
        {measures_str}
    ),
    {filters_str}
)'''
                else:
                    # Multi-table: Use SUMMARIZECOLUMNS
                    query = f'''EVALUATE
CALCULATETABLE(
    SUMMARIZECOLUMNS(
        {columns_str},
        {measures_str}
    ),
    {filters_str}
)'''
            else:
                if use_summarize and fact_table:
                    query = f'''EVALUATE
ADDCOLUMNS(
    SUMMARIZE(
        {fact_table},
        {columns_str}
    ),
    {measures_str}
)'''
                else:
                    query = f'''EVALUATE
SUMMARIZECOLUMNS(
    {columns_str},
    {measures_str}
)'''
        else:
            # Simple ROW query for card/KPI visuals
            measures_str = ',\n    '.join(measure_parts)
            query = f'''EVALUATE
ROW(
    {measures_str}
)'''

        return query

    def build_detail_rows_query(
        self,
        page_name: str,
        visual_id: Optional[str] = None,
        visual_name: Optional[str] = None,
        fact_table: Optional[str] = None,
        columns: Optional[List[str]] = None,
        limit: int = 100,
        include_slicers: bool = True
    ) -> Optional[str]:
        """
        Build a query to show detail rows with filter context applied.

        Args:
            page_name: Display name of the page
            visual_id: ID of the visual
            visual_name: Name of the visual
            fact_table: Table to query (default: infer from visual)
            columns: Specific columns to include (default: all)
            limit: Maximum rows to return
            include_slicers: Whether to include slicer selections

        Returns:
            DAX query string or None
        """
        visual_info, filter_context = self.get_visual_filter_context(
            page_name, visual_id, visual_name, include_slicers
        )

        if not visual_info and not fact_table:
            return None

        # Determine table to query
        if fact_table:
            table = fact_table
        elif visual_info and visual_info.columns:
            # Extract table from first column reference
            first_col = visual_info.columns[0]
            if '[' in first_col:
                table = first_col.split('[')[0].strip("'")
            else:
                self.logger.warning("Could not determine fact table")
                return None
        else:
            self.logger.warning("No fact table specified")
            return None

        # Build filter expressions - exclude field parameters and UI controls
        from .filter_to_dax import FilterClassification

        all_filters = filter_context.all_filters()
        data_filters = [
            f for f in all_filters
            if f.dax and getattr(f, 'classification', FilterClassification.DATA) == FilterClassification.DATA
        ]
        filter_dax = ', '.join([f.dax for f in data_filters])

        # Build query
        if filter_dax:
            query = f"""EVALUATE
TOPN(
    {limit},
    CALCULATETABLE(
        '{table}',
        {filter_dax}
    )
)"""
        else:
            query = f"""EVALUATE
TOPN(
    {limit},
    '{table}'
)"""

        return query

    def list_pages(self) -> List[Dict[str, str]]:
        """List all pages in the report."""
        pages = []
        pages_path = self.definition_path / 'pages'

        if not pages_path.exists():
            return pages

        for page_folder in pages_path.iterdir():
            if page_folder.is_dir():
                page_json = page_folder / 'page.json'
                if page_json.exists():
                    try:
                        with open(page_json, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            pages.append({
                                'id': page_folder.name,
                                'name': data.get('displayName', page_folder.name),
                                'ordinal': data.get('ordinal', 0)
                            })
                    except Exception as e:
                        self.logger.debug(f"Error reading page: {e}")

        # Sort by ordinal
        pages.sort(key=lambda x: x.get('ordinal', 0))
        return pages

    def list_visuals(self, page_name: str, include_ui_elements: bool = True) -> List[Dict[str, Any]]:
        """
        List all visuals on a page with friendly names.

        Args:
            page_name: Page name to list visuals for
            include_ui_elements: If False, excludes UI elements (shapes, buttons, groups)
                               for cleaner documentation output. Default True for backwards compatibility.
        """
        visuals = []
        page_path = self._find_page_by_name(page_name)

        if not page_path:
            return visuals

        visuals_path = page_path / 'visuals'
        if not visuals_path.exists():
            return visuals

        for visual_folder in visuals_path.iterdir():
            if visual_folder.is_dir():
                visual_json = visual_folder / 'visual.json'
                if visual_json.exists():
                    try:
                        with open(visual_json, 'r', encoding='utf-8') as f:
                            data = json.load(f)

                            # Check for visual groups FIRST (containers without 'visual' property)
                            is_visual_group = 'visualGroup' in data
                            visual = data.get('visual', {})

                            if is_visual_group:
                                visual_type = 'visualGroup'
                                # Get displayName from visualGroup for naming
                                group_info = data.get('visualGroup', {})
                                title = group_info.get('displayName')
                            else:
                                visual_type = visual.get('visualType', 'unknown')
                                # Extract title from visualContainerObjects
                                title = self._extract_visual_title(visual)

                            # Determine if this is a data-bearing visual
                            is_data_visual = self._is_data_visual(visual_type, data)

                            # Skip UI elements if requested
                            if not include_ui_elements and not is_data_visual:
                                continue

                            # Extract measures and columns for better naming
                            measures, columns = self._extract_visual_fields(visual)

                            # Extract visual-level filters for documentation
                            visual_filters = visual.get('filters', [])

                            # Build friendly name
                            friendly_name = self._build_visual_friendly_name(
                                title=title,
                                visual_type=visual_type,
                                measures=measures,
                                columns=columns,
                                visual_id=visual_folder.name
                            )

                            visuals.append({
                                'id': visual_folder.name,
                                'name': data.get('name', ''),
                                'friendly_name': friendly_name,
                                'title': title,
                                'type': visual_type,
                                'type_display': self._get_visual_type_display(visual_type),
                                'is_slicer': visual_type in SLICER_VISUAL_TYPES,
                                'is_visual_group': is_visual_group,
                                'is_data_visual': is_data_visual,
                                'measures': measures,
                                'columns': columns,
                                'filters': visual_filters  # Include for lightweight documentation
                            })
                    except Exception as e:
                        self.logger.debug(f"Error reading visual: {e}")

        return visuals

    def _extract_visual_title(self, visual: Dict) -> Optional[str]:
        """Extract the display title from a visual's configuration."""
        # Try visualContainerObjects.title (most common location)
        visual_container_objects = visual.get('visualContainerObjects', {})
        title_config = visual_container_objects.get('title', [])
        if title_config:
            title_props = title_config[0].get('properties', {})
            text_expr = title_props.get('text', {}).get('expr', {})
            if 'Literal' in text_expr:
                title = text_expr['Literal'].get('Value', '').strip("'\"")
                if title:
                    return title

        # Try vcObjects.title (alternative location)
        vc_objects = visual.get('vcObjects', {})
        title_config = vc_objects.get('title', [])
        if title_config:
            title_props = title_config[0].get('properties', {})
            text_val = title_props.get('text', {})
            if isinstance(text_val, str):
                return text_val.strip("'\"")
            text_expr = text_val.get('expr', {})
            if 'Literal' in text_expr:
                title = text_expr['Literal'].get('Value', '').strip("'\"")
                if title:
                    return title

        return None

    def _extract_visual_fields(self, visual: Dict) -> tuple:
        """Extract measures and columns from a visual's query configuration."""
        measures = []
        columns = []

        query = visual.get('query', {})
        query_state = query.get('queryState', {})

        # Look in various projection types
        projection_types = ['Values', 'Y', 'Rows', 'Columns', 'Category', 'X', 'Size', 'Legend', 'Tooltips']
        for proj_type in projection_types:
            projections = query_state.get(proj_type, {}).get('projections', [])
            for proj in projections:
                field = proj.get('field', {})

                if 'Measure' in field:
                    measure_ref = field['Measure']
                    prop = measure_ref.get('Property', '')
                    if prop and prop not in measures:
                        measures.append(prop)

                if 'Column' in field:
                    col_ref = field['Column']
                    table = col_ref.get('Expression', {}).get('SourceRef', {}).get('Entity', '')
                    prop = col_ref.get('Property', '')
                    if prop and prop not in columns:
                        columns.append(prop)

        return measures, columns

    def _build_visual_friendly_name(
        self,
        title: Optional[str],
        visual_type: str,
        measures: List[str],
        columns: List[str],
        visual_id: str
    ) -> str:
        """Build a human-friendly name for a visual."""
        # Priority 1: Use title if available
        if title:
            return title

        # Priority 2: Build name from type + fields
        type_display = self._get_visual_type_display(visual_type)

        if measures:
            # Use first measure for naming
            measure_name = measures[0]
            if len(measures) > 1:
                return f"{type_display}: {measure_name} (+{len(measures)-1})"
            return f"{type_display}: {measure_name}"

        if columns:
            # Use first column for naming
            col_name = columns[0]
            if len(columns) > 1:
                return f"{type_display}: {col_name} (+{len(columns)-1})"
            return f"{type_display}: {col_name}"

        # Priority 3: Just type + short ID
        short_id = visual_id[:8] if len(visual_id) > 8 else visual_id
        return f"{type_display} ({short_id})"

    def _is_data_visual(self, visual_type: str, data: Dict) -> bool:
        """
        Determine if a visual is a data-bearing visual vs UI element.

        Data visuals display analytical data (charts, tables, matrices).
        UI/context visuals are layout elements or simple info displays.

        Args:
            visual_type: The visual type string
            data: The full visual JSON data

        Returns:
            True if this is a data-bearing visual
        """
        # Visual groups are never data visuals
        if 'visualGroup' in data:
            return False

        # Empty/unknown type with no visual property is a group/container
        if not visual_type or visual_type == 'unknown':
            return False

        # Check against known UI types
        if visual_type.lower() in {t.lower() for t in UI_VISUAL_TYPES}:
            return False

        # Special handling for card visuals - single-field cards showing context (date, user)
        # are UI elements, cards with actual measures are data visuals
        # Note: multiRowCard is always UI (in UI_VISUAL_TYPES) since they're used for labels
        visual_type_lower = visual_type.lower()
        if visual_type_lower == 'card':
            visual = data.get('visual', {})
            measures, columns = self._extract_visual_fields(visual)
            # Cards with measures are data visuals, pure column cards are context/UI
            return len(measures) > 0

        # Check against known data visual types
        if visual_type_lower in {t.lower() for t in DATA_VISUAL_TYPES}:
            return True

        # For unknown types, check if it has data bindings
        visual = data.get('visual', {})
        query = visual.get('query', {})
        query_state = query.get('queryState', {})

        # If it has query projections, it's likely a data visual
        has_projections = any(
            proj_type in query_state
            for proj_type in ['Category', 'Y', 'Values', 'Rows', 'Columns',
                            'Legend', 'X', 'Size', 'Details']
        )

        return has_projections

    def _get_visual_type_display(self, visual_type: str) -> str:
        """Get human-friendly display name for visual type."""
        type_mapping = {
            'pivotTable': 'Matrix',
            'tableEx': 'Table',
            'columnChart': 'Column Chart',
            'barChart': 'Bar Chart',
            'lineChart': 'Line Chart',
            'areaChart': 'Area Chart',
            'lineStackedColumnComboChart': 'Combo Chart',
            'clusteredBarChart': 'Clustered Bar',
            'clusteredColumnChart': 'Clustered Column',
            'stackedBarChart': 'Stacked Bar',
            'stackedColumnChart': 'Stacked Column',
            'hundredPercentStackedBarChart': '100% Stacked Bar',
            'hundredPercentStackedColumnChart': '100% Stacked Column',
            'pieChart': 'Pie Chart',
            'donutChart': 'Donut Chart',
            'treemap': 'Treemap',
            'map': 'Map',
            'filledMap': 'Filled Map',
            'shapeMap': 'Shape Map',
            'slicer': 'Slicer',
            'advancedSlicerVisual': 'Advanced Slicer',
            'card': 'Card',
            'multiRowCard': 'Multi-row Card',
            'kpi': 'KPI',
            'gauge': 'Gauge',
            'scatterChart': 'Scatter Chart',
            'funnel': 'Funnel',
            'waterfallChart': 'Waterfall',
            'ribbonChart': 'Ribbon Chart',
            'decompositionTreeVisual': 'Decomposition Tree',
            'keyInfluencers': 'Key Influencers',
            'qnaVisual': 'Q&A',
            'textbox': 'Text Box',
            'image': 'Image',
            'shape': 'Shape',
            'actionButton': 'Button',
            'bookmarkNavigator': 'Bookmark Navigator',
            'pageNavigator': 'Page Navigator',
            'visualGroup': 'Visual Group',
            'unknown': 'Unknown',
        }
        return type_mapping.get(visual_type, visual_type.replace('Chart', ' Chart').title())

    def list_slicers(self, page_name: Optional[str] = None) -> List[SlicerState]:
        """
        List all slicers and their current selections.

        Args:
            page_name: Filter to specific page (optional)

        Returns:
            List of SlicerState objects
        """
        all_slicers = []
        pages_path = self.definition_path / 'pages'

        if not pages_path.exists():
            return all_slicers

        for page_folder in pages_path.iterdir():
            if not page_folder.is_dir():
                continue

            # Get page display name
            page_display_name = self._get_page_display_name(page_folder)

            if page_name and page_display_name.lower() != page_name.lower():
                continue

            slicers = self._get_page_slicers(page_folder, page_display_name)
            all_slicers.extend(slicers)

        return all_slicers

    def _find_page_by_name(self, page_name: str) -> Optional[Path]:
        """Find page folder by display name. Results are cached."""
        # Check cache first (case-insensitive key)
        cache_key = page_name.lower()
        if cache_key in self._page_path_cache:
            return self._page_path_cache[cache_key]

        pages_path = self.definition_path / 'pages'

        if not pages_path.exists():
            self._page_path_cache[cache_key] = None
            return None

        for page_folder in pages_path.iterdir():
            if page_folder.is_dir():
                display_name = self._get_page_display_name(page_folder)
                if display_name.lower() == cache_key:
                    self._page_path_cache[cache_key] = page_folder
                    return page_folder

        self._page_path_cache[cache_key] = None
        return None

    def _get_page_display_name(self, page_folder: Path) -> str:
        """Get display name from page.json."""
        page_json = page_folder / 'page.json'
        if page_json.exists():
            try:
                with open(page_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('displayName', page_folder.name)
            except Exception:
                pass
        return page_folder.name

    def _find_visual(
        self,
        page_path: Path,
        visual_id: Optional[str],
        visual_name: Optional[str]
    ) -> Optional[VisualInfo]:
        """
        Find and parse a visual by ID, name, or friendly name.

        Matching priority:
        1. Exact ID match
        2. Exact name match (from visual.json 'name' field)
        3. Title match (from visualContainerObjects.title)
        4. Friendly name match (type + measures)
        5. Partial/fuzzy match on title or friendly name
        """
        visuals_path = page_path / 'visuals'

        if not visuals_path.exists():
            return None

        page_display_name = self._get_page_display_name(page_path)

        # First pass: Try exact matches
        for visual_folder in visuals_path.iterdir():
            if not visual_folder.is_dir():
                continue

            # Exact ID match
            if visual_id and visual_folder.name == visual_id:
                visual_json = visual_folder / 'visual.json'
                if visual_json.exists():
                    try:
                        with open(visual_json, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        visual = data.get('visual', {})
                        return self._parse_visual_info(data, visual, visual_folder.name, page_display_name, page_path.name)
                    except Exception as e:
                        self.logger.debug(f"Error reading visual: {e}")

        # Second pass: Try name/title/friendly_name matches
        if visual_name:
            visual_name_lower = visual_name.lower().strip()

            for visual_folder in visuals_path.iterdir():
                if not visual_folder.is_dir():
                    continue

                visual_json = visual_folder / 'visual.json'
                if not visual_json.exists():
                    continue

                try:
                    with open(visual_json, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    visual = data.get('visual', {})
                    visual_type = visual.get('visualType', 'unknown')

                    # Check stored name
                    stored_name = data.get('name', '')
                    if stored_name and stored_name.lower() == visual_name_lower:
                        return self._parse_visual_info(data, visual, visual_folder.name, page_display_name, page_path.name)

                    # Check title
                    title = self._extract_visual_title(visual)
                    if title and title.lower() == visual_name_lower:
                        return self._parse_visual_info(data, visual, visual_folder.name, page_display_name, page_path.name)

                    # Check friendly name
                    measures, columns = self._extract_visual_fields(visual)
                    friendly_name = self._build_visual_friendly_name(
                        title=title,
                        visual_type=visual_type,
                        measures=measures,
                        columns=columns,
                        visual_id=visual_folder.name
                    )
                    if friendly_name.lower() == visual_name_lower:
                        return self._parse_visual_info(data, visual, visual_folder.name, page_display_name, page_path.name)

                except Exception as e:
                    self.logger.debug(f"Error reading visual: {e}")

            # Third pass: Try partial/contains matches
            for visual_folder in visuals_path.iterdir():
                if not visual_folder.is_dir():
                    continue

                visual_json = visual_folder / 'visual.json'
                if not visual_json.exists():
                    continue

                try:
                    with open(visual_json, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    visual = data.get('visual', {})
                    visual_type = visual.get('visualType', 'unknown')

                    # Check if search term is contained in title
                    title = self._extract_visual_title(visual)
                    if title and visual_name_lower in title.lower():
                        return self._parse_visual_info(data, visual, visual_folder.name, page_display_name, page_path.name)

                    # Check if search term is contained in friendly name
                    measures, columns = self._extract_visual_fields(visual)
                    friendly_name = self._build_visual_friendly_name(
                        title=title,
                        visual_type=visual_type,
                        measures=measures,
                        columns=columns,
                        visual_id=visual_folder.name
                    )
                    if visual_name_lower in friendly_name.lower():
                        return self._parse_visual_info(data, visual, visual_folder.name, page_display_name, page_path.name)

                    # Check if search term matches visual type
                    type_display = self._get_visual_type_display(visual_type)
                    if visual_name_lower == type_display.lower() or visual_name_lower == visual_type.lower():
                        return self._parse_visual_info(data, visual, visual_folder.name, page_display_name, page_path.name)

                except Exception as e:
                    self.logger.debug(f"Error reading visual: {e}")

        return None

    def _parse_visual_info(
        self,
        data: Dict,
        visual: Dict,
        visual_id: str,
        page_name: str,
        page_id: str
    ) -> VisualInfo:
        """Parse visual information from JSON."""
        measures = []
        columns = []
        filters = []

        # Extract fields from query
        query = visual.get('query', {})
        query_state = query.get('queryState', {})

        # Look in various projection types
        projection_types = ['Values', 'Y', 'Rows', 'Columns', 'Category', 'X', 'Size', 'Legend', 'Tooltips']
        for proj_type in projection_types:
            projections = query_state.get(proj_type, {}).get('projections', [])
            for proj in projections:
                field = proj.get('field', {})

                if 'Measure' in field:
                    measure_ref = field['Measure']
                    table = measure_ref.get('Expression', {}).get('SourceRef', {}).get('Entity', '')
                    prop = measure_ref.get('Property', '')
                    if prop:
                        measures.append(f"[{prop}]")

                if 'Column' in field:
                    # Skip inactive projections — these are field-parameter-controlled
                    # alternatives that Power BI does NOT include as direct groupby axes
                    # (e.g., 'd Asset Class'[Asset Class] with active:false on a matrix
                    # whose rows are driven by sf Row Drill field parameter)
                    if not proj.get('active', True):
                        continue
                    col_ref = field['Column']
                    table = col_ref.get('Expression', {}).get('SourceRef', {}).get('Entity', '')
                    prop = col_ref.get('Property', '')
                    if table and prop:
                        columns.append(f"'{table}'[{prop}]")

        # Extract visual filters
        visual_filters = visual.get('filters', [])
        for vf in visual_filters:
            filters.append(vf)

        # Get title
        title = None
        visual_container_objects = visual.get('visualContainerObjects', {})
        title_config = visual_container_objects.get('title', [])
        if title_config:
            title_props = title_config[0].get('properties', {})
            text_expr = title_props.get('text', {}).get('expr', {})
            if 'Literal' in text_expr:
                title = text_expr['Literal'].get('Value', '').strip("'")

        return VisualInfo(
            visual_id=visual_id,
            visual_type=visual.get('visualType', 'unknown'),
            visual_name=data.get('name'),
            page_name=page_name,
            page_id=page_id,
            title=title,
            measures=measures,
            columns=columns,
            filters=filters
        )

    def _get_report_filters(self) -> List[Dict]:
        """Get report-level filters."""
        if self._report_filters_cache is not None:
            return self._report_filters_cache

        filters = []
        report_json = self.definition_path / 'report.json'

        if report_json.exists():
            try:
                with open(report_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    filter_config = data.get('filterConfig', {})
                    filters = filter_config.get('filters', [])
            except Exception as e:
                self.logger.debug(f"Error reading report filters: {e}")

        self._report_filters_cache = filters
        return filters

    def _get_page_filters(self, page_path: Path) -> List[Dict]:
        """Get page-level filters. Results are cached."""
        # Use page path as cache key
        cache_key = str(page_path)
        if cache_key in self._page_filters_cache:
            return self._page_filters_cache[cache_key]

        filters = []
        page_json = page_path / 'page.json'

        if page_json.exists():
            try:
                with open(page_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    filter_config = data.get('filterConfig', {})
                    filters = filter_config.get('filters', [])
            except Exception as e:
                self.logger.debug(f"Error reading page filters: {e}")

        self._page_filters_cache[cache_key] = filters
        return filters

    def _get_page_slicers(self, page_path: Path, page_name: str) -> List[SlicerState]:
        """Get all slicers on a page with their current selections. Results are cached."""
        # Check cache first
        cache_key = page_name.lower()
        if cache_key in self._slicers_cache:
            return self._slicers_cache[cache_key]

        slicers = []
        visuals_path = page_path / 'visuals'

        if not visuals_path.exists():
            self._slicers_cache[cache_key] = slicers
            return slicers

        for visual_folder in visuals_path.iterdir():
            if not visual_folder.is_dir():
                continue

            visual_json = visual_folder / 'visual.json'
            if not visual_json.exists():
                continue

            try:
                with open(visual_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                visual = data.get('visual', {})
                if visual.get('visualType') not in SLICER_VISUAL_TYPES:
                    continue

                slicer_state = self._parse_slicer_state(data, visual, visual_folder.name, page_name)
                if slicer_state:
                    slicers.append(slicer_state)

            except Exception as e:
                self.logger.debug(f"Error reading slicer: {e}")

        self._slicers_cache[cache_key] = slicers
        return slicers

    @staticmethod
    def _resolve_field_param_column(table: str, prop: str) -> str:
        """
        Resolve the actual DAX column name for a field parameter slicer projection.

        Power BI field parameter tables store selections in a hidden 'Fields' column
        (e.g., 'sf Filter 1'[sf Filter 1 Fields]).  The visual.json projection records
        the *display* column whose Property name matches the table name.  When we detect
        this pattern we append ' Fields' to get the real TREATAS target column.

        Rule:  if is_field_parameter AND property == table_name  →  use '{property} Fields'
               otherwise keep property as-is  (e.g., 'Category' stays 'Category')
        """
        from .filter_to_dax import is_field_parameter_table
        if is_field_parameter_table(table) and prop == table:
            return f"{prop} Fields"
        return prop

    def _parse_slicer_state(
        self,
        data: Dict,
        visual: Dict,
        visual_id: str,
        page_name: str
    ) -> Optional[SlicerState]:
        """Parse slicer state from visual JSON.

        Handles both single-column slicers (regular and single-field-param like sf Filter 1)
        and multi-column composite field parameter slicers (sf Row Drill, sf Slicer 1) that
        require composite-key TREATAS with tuple values.
        """
        try:
            from .filter_to_dax import is_field_parameter_table

            # Get field reference(s)
            query = visual.get('query', {})
            query_state = query.get('queryState', {})
            values_section = query_state.get('Values', {})
            projections = values_section.get('projections', [])

            if not projections:
                return None

            # Parse ALL projections (field param slicers can have 2: Category + Fields)
            proj_columns: List[Dict] = []  # [{table, column}]
            for proj in projections:
                field = proj.get('field', {})
                col_ref = field.get('Column', {})
                if not col_ref:
                    continue
                expr = col_ref.get('Expression', {})
                source_ref = expr.get('SourceRef', {})
                t = source_ref.get('Entity', '')
                p = col_ref.get('Property', '')
                if t and p:
                    # Resolve to actual DAX column (handles 'sf Filter 1' → 'sf Filter 1 Fields')
                    resolved_p = self._resolve_field_param_column(t, p)
                    proj_columns.append({'table': t, 'column': resolved_p})

            if not proj_columns:
                return None

            table = proj_columns[0]['table']
            column = proj_columns[0]['column']

            # Get selection state
            objects = visual.get('objects', {})

            # Selection mode
            selection_config = objects.get('selection', [{}])
            selection_props = selection_config[0].get('properties', {}) if selection_config else {}
            single_select = (
                selection_props.get('singleSelect', {}).get('expr', {}).get('Literal', {}).get('Value', 'false') == 'true' or
                selection_props.get('strictSingleSelect', {}).get('expr', {}).get('Literal', {}).get('Value', 'false') == 'true'
            )

            # Inverted selection
            data_config = objects.get('data', [{}])
            data_props = data_config[0].get('properties', {}) if data_config else {}
            is_inverted = data_props.get('isInvertedSelectionMode', {}).get('expr', {}).get('Literal', {}).get('Value', 'false') == 'true'

            # Current selections — parse as tuples to support multi-column slicers
            general_config = objects.get('general', [{}])
            general_props = general_config[0].get('properties', {}) if general_config else {}
            current_filter = general_props.get('filter', {}).get('filter', {})

            is_multi_col = len(proj_columns) > 1
            selected_values: List[Any] = []
            composite_values: Optional[List[List[Any]]] = [] if is_multi_col else None

            if current_filter:
                where_clause = current_filter.get('Where', [])
                for condition in where_clause:
                    in_clause = condition.get('Condition', {}).get('In', {})
                    values_list = in_clause.get('Values', [])
                    for value_group in values_list:
                        if is_multi_col:
                            # Each value_group is a tuple: one literal per projection column
                            tuple_row = []
                            for value_item in value_group:
                                literal = value_item.get('Literal', {})
                                tuple_row.append(literal.get('Value', ''))
                            composite_values.append(tuple_row)
                            # Also store just the first column's value in selected_values (for display)
                            if tuple_row:
                                selected_values.append(tuple_row[0])
                        else:
                            # Single-column: keep flat list of literal values
                            for value_item in value_group:
                                literal = value_item.get('Literal', {})
                                val = literal.get('Value', '')
                                selected_values.append(val)
            else:
                self.logger.debug(f"Slicer {visual_id} ({table}.{column}): No current_filter found")

            # Determine selection mode
            if is_inverted and single_select:
                selection_mode = 'single_select_all'
            elif single_select:
                selection_mode = 'single_select'
            else:
                selection_mode = 'multi_select'

            # Extra columns for composite TREATAS (second projection onwards, same table)
            extra_columns: List[str] = []
            if is_multi_col:
                for pc in proj_columns[1:]:
                    extra_columns.append(f"'{pc['table']}'[{pc['column']}]")

            self.logger.debug(
                f"Slicer {visual_id} ({table}.{column}): "
                f"{len(selected_values)} values, mode={selection_mode}, "
                f"multi_col={is_multi_col}, extra_cols={extra_columns}"
            )

            return SlicerState(
                slicer_id=visual_id,
                page_name=page_name,
                table=table,
                column=column,
                field_reference=f"'{table}'[{column}]",
                selected_values=selected_values,
                selection_mode=selection_mode,
                is_inverted=is_inverted,
                extra_columns=extra_columns,
                composite_values=composite_values if composite_values else None,
            )

        except Exception as e:
            self.logger.debug(f"Error parsing slicer state: {e}")
            return None
