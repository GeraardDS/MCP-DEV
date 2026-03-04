"""
VertiPaq Metrics Analyzer - Column cardinality and memory impact analysis

Integrates with Power BI DMVs to provide:
- Column cardinality analysis
- Memory footprint analysis
- Data type optimization suggestions
- High-cardinality column detection
"""

import logging
import re
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ColumnMetrics:
    """Metrics for a single column"""

    table_name: str
    column_name: str
    cardinality: int
    size_bytes: int
    data_type: str
    encoding: str = "unknown"
    dictionary_size_bytes: int = 0
    hierarchy_size_bytes: int = 0
    is_referenced: bool = False
    reference_count: int = 0

    @property
    def full_name(self) -> str:
        """Get fully qualified column name"""
        return f"{self.table_name}[{self.column_name}]"

    @property
    def cardinality_level(self) -> str:
        """Classify cardinality level"""
        if self.cardinality < 100:
            return "low"
        elif self.cardinality < 10_000:
            return "medium"
        elif self.cardinality < 100_000:
            return "high"
        else:
            return "very_high"

    @property
    def size_mb(self) -> float:
        """Get size in megabytes"""
        return self.size_bytes / (1024 * 1024)


@dataclass
class DataTypeOptimization:
    """Data type optimization suggestion"""

    column: str
    current_type: str
    suggested_type: str
    reason: str
    estimated_savings_bytes: int
    priority: str  # "high", "medium", "low"


@dataclass
class CardinalityImpact:
    """Impact assessment for high-cardinality columns"""

    column: str
    cardinality: int
    size_bytes: int
    usage_context: str  # "iterator", "filter", "calculate"
    performance_impact: str  # "critical", "high", "medium", "low"
    recommendation: str


class VertiPaqAnalyzer:
    """
    VertiPaq Metrics Analyzer

    Analyzes column-level metrics from VertiPaq storage engine
    to provide performance optimization guidance
    """

    # Cardinality thresholds for performance warnings
    ITERATOR_CARDINALITY_WARNING = 100_000
    ITERATOR_CARDINALITY_CRITICAL = 1_000_000
    FILTER_CARDINALITY_WARNING = 500_000

    def __init__(self, connection_state=None):
        """
        Initialize VertiPaq Analyzer

        Args:
            connection_state: Optional connection state for DMV queries
        """
        self.connection_state = connection_state
        self._column_cache: Dict[str, ColumnMetrics] = {}
        self._cache_loaded = False

    def load_column_metrics(self) -> bool:
        """
        Load column metrics from DMVs

        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.connection_state or not self.connection_state.is_connected():
                logger.warning("Not connected - cannot load VertiPaq metrics")
                return False

            qe = self.connection_state.query_executor
            if not qe:
                logger.warning("Query executor not available")
                return False

            # Query DMVs for column statistics
            # Remove WHERE clause to capture all column types
            dmv_query = """
            SELECT
                [DIMENSION_NAME] as TableName,
                [ATTRIBUTE_NAME] as ColumnName,
                [ATTRIBUTE_COUNT] as Cardinality,
                [ATTRIBUTE_SIZE] as SizeBytes,
                [DATATYPE] as DataType,
                [DICTIONARY_SIZE] as DictionarySizeBytes,
                [HIERARCHY_SIZE] as HierarchySizeBytes,
                [ATTRIBUTE_ENCODING] as Encoding,
                [COLUMN_TYPE] as ColumnType
            FROM $SYSTEM.DISCOVER_STORAGE_TABLE_COLUMNS
            """

            result = qe.execute_dmv_query(dmv_query)

            if not result.get("success"):
                logger.error(f"DMV query failed: {result.get('error', 'Unknown error')}")
                return False

            if not result.get("data"):
                logger.warning("DMV query returned no data")
                return False

            # Process DMV results
            self._column_cache.clear()
            skipped_columns = 0

            for row in result["data"]:
                table_name = row.get("TableName", "")
                column_name = row.get("ColumnName", "")
                column_type = row.get("ColumnType", "BASIC_DATA")

                # Skip internal/system columns (RowNumber columns)
                if column_type == "ROWNUM" or column_name.startswith("RowNumber-"):
                    skipped_columns += 1
                    continue

                # Add column type info to encoding for better visibility
                encoding = row.get("Encoding", "unknown")
                if column_type == "CALCULATED":
                    encoding = f"{encoding} (Calculated Column)"
                elif column_type == "UNKNOWN":
                    encoding = f"{encoding} (Type Unknown)"

                metrics = ColumnMetrics(
                    table_name=table_name,
                    column_name=column_name,
                    cardinality=int(row.get("Cardinality", 0)),
                    size_bytes=int(row.get("SizeBytes", 0)),
                    data_type=row.get("DataType", "unknown"),
                    encoding=encoding,
                    dictionary_size_bytes=int(row.get("DictionarySizeBytes", 0)),
                    hierarchy_size_bytes=int(row.get("HierarchySizeBytes", 0)),
                )

                self._column_cache[metrics.full_name] = metrics

            self._cache_loaded = True
            logger.info(
                f"Loaded metrics for {len(self._column_cache)} columns (skipped {skipped_columns} internal columns)"
            )
            return True

        except Exception as e:
            logger.error(f"Error loading VertiPaq metrics: {e}", exc_info=True)
            return False

    def get_column_metrics(self, column_ref: str) -> Optional[ColumnMetrics]:
        """
        Get metrics for a specific column

        Args:
            column_ref: Column reference like "Sales[Amount]" or "TableName[ColumnName]"

        Returns:
            ColumnMetrics if found, None otherwise
        """
        # Ensure cache is loaded
        if not self._cache_loaded:
            cache_success = self.load_column_metrics()
            if not cache_success:
                logger.warning(
                    f"Failed to load DMV cache, will attempt direct calculation for {column_ref}"
                )

        # Normalize column reference
        normalized = self._normalize_column_ref(column_ref)
        logger.debug(f"Looking up column: original='{column_ref}', normalized='{normalized}'")

        # First, try to get from cache (DMV data)
        cached = self._column_cache.get(normalized)

        if cached:
            logger.debug(f"Found {normalized} in cache with cardinality {cached.cardinality:,}")
            return cached

        # If not in cache, log available columns for debugging
        if self._cache_loaded and len(self._column_cache) > 0:
            # Log a few similar column names to help diagnose
            similar_cols = [k for k in self._column_cache.keys() if normalized.split("[")[0] in k]
            if similar_cols:
                logger.debug(
                    f"Column {normalized} not found. Similar columns in cache: {similar_cols[:5]}"
                )
            else:
                logger.debug(
                    f"Column {normalized} not found. Cache has {len(self._column_cache)} columns"
                )

        # Try to calculate cardinality directly using DAX
        logger.debug(f"Column {normalized} not in cache, attempting fallback calculation")
        cached = self._calculate_column_cardinality(column_ref)
        if cached:
            # Add to cache for future use
            self._column_cache[normalized] = cached
            logger.info(
                f"Successfully calculated metrics for {normalized} using DAX fallback: cardinality={cached.cardinality:,}"
            )
        else:
            logger.warning(
                f"Could not retrieve metrics for {normalized} from either DMV or DAX calculation"
            )

        return cached

    def analyze_dax_columns(self, dax_expression: str) -> Dict[str, Any]:
        """
        Analyze columns referenced in DAX expression

        Args:
            dax_expression: DAX expression to analyze

        Returns:
            Dictionary with column analysis results
        """
        try:
            # Ensure cache is loaded first
            if not self._cache_loaded:
                cache_loaded = self.load_column_metrics()
                if cache_loaded:
                    logger.info("VertiPaq metrics loaded from DMV")
                else:
                    logger.warning(
                        "VertiPaq metrics not available from DMV - will use fallback calculation"
                    )

            # Extract column references from DAX
            column_refs = self._extract_column_references(dax_expression)

            if not column_refs:
                return {
                    "success": True,
                    "columns_analyzed": 0,
                    "column_analysis": {},
                    "total_cardinality": 0,
                    "total_size_mb": 0.0,
                    "high_cardinality_columns": [],
                    "optimizations": [],
                    "note": "No column references found in DAX expression (might be using only measures)",
                }

            # Get metrics for each column
            column_analysis = {}
            total_cardinality = 0
            total_size_bytes = 0
            high_cardinality_columns = []
            metrics_available_count = 0

            for col_ref in column_refs:
                metrics = self.get_column_metrics(col_ref)

                if metrics:
                    metrics_available_count += 1

                    # Determine usage context
                    usage_context = self._determine_usage_context(dax_expression, col_ref)

                    # Assess impact
                    impact = self._assess_column_impact(metrics, usage_context)

                    column_analysis[col_ref] = {
                        "cardinality": metrics.cardinality,
                        "cardinality_level": metrics.cardinality_level,
                        "size_bytes": metrics.size_bytes,
                        "size_mb": round(metrics.size_mb, 2),
                        "data_type": metrics.data_type,
                        "encoding": metrics.encoding,
                        "usage_context": usage_context,
                        "performance_impact": impact.performance_impact,
                        "recommendation": impact.recommendation,
                        "metrics_source": "dmv" if self._cache_loaded else "calculated",
                    }

                    total_cardinality += metrics.cardinality
                    total_size_bytes += metrics.size_bytes

                    if metrics.cardinality_level in ["high", "very_high"]:
                        high_cardinality_columns.append(col_ref)
                else:
                    # Column not found - might be measure, calculated column, or invalid reference
                    logger.warning(f"No metrics available for {col_ref}")
                    column_analysis[col_ref] = {
                        "status": "metrics_unavailable",
                        "message": "No metrics available",
                        "note": "This might be a measure, calculated column, or the column doesn't exist in the model",
                    }

            # Get optimization suggestions
            optimizations = self._get_optimization_suggestions(column_analysis, dax_expression)

            # Prepare result with metadata about data quality
            result = {
                "success": True,
                "columns_analyzed": len(column_refs),
                "columns_with_metrics": metrics_available_count,
                "column_analysis": column_analysis,
                "total_cardinality": total_cardinality,
                "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
                "high_cardinality_columns": high_cardinality_columns,
                "optimizations": optimizations,
                "data_source": "dmv" if self._cache_loaded else "calculated",
            }

            # Add warning if no metrics were available
            if metrics_available_count == 0:
                result["warning"] = (
                    "No VertiPaq metrics available for any columns. "
                    "This could mean: (1) Only measures are referenced, (2) DMV access failed, "
                    "or (3) Column references couldn't be matched to model columns."
                )
                logger.warning(result["warning"])

            return result

        except Exception as e:
            logger.error(f"Error analyzing DAX columns: {e}", exc_info=True)
            return {"success": False, "error": str(e), "columns_analyzed": 0}

    def _extract_column_references(self, dax: str) -> Set[str]:
        """Extract column references from DAX expression"""
        column_refs = set()

        # Pattern for Table[Column] or 'Table'[Column]
        pattern = r"(?:'([^']+)'|\b(\w+))\[([^\]]+)\]"

        for match in re.finditer(pattern, dax):
            table = match.group(1) or match.group(2)
            column = match.group(3)

            # Skip if it looks like just a measure reference [MeasureName]
            if table:
                column_refs.add(f"{table}[{column}]")

        return column_refs

    def _normalize_column_ref(self, col_ref: str) -> str:
        """Normalize column reference to standard format"""
        # Remove quotes
        col_ref = col_ref.replace("'", "")
        return col_ref

    def _calculate_column_cardinality(self, column_ref: str) -> Optional[ColumnMetrics]:
        """
        Calculate column cardinality using DAX query (fallback when DMV data unavailable)

        Args:
            column_ref: Column reference like "Sales[Amount]"

        Returns:
            ColumnMetrics with calculated cardinality, or None if calculation fails
        """
        try:
            if not self.connection_state or not self.connection_state.is_connected():
                logger.debug("Cannot calculate cardinality: not connected")
                return None

            qe = self.connection_state.query_executor
            if not qe:
                logger.debug("Cannot calculate cardinality: no query executor")
                return None

            # Parse table and column name - support spaces in names
            match = re.match(r"(?:'([^']+)'|(\w+))\[([^\]]+)\]", column_ref)
            if not match:
                logger.debug(f"Could not parse column reference: {column_ref}")
                return None

            table_name = match.group(1) or match.group(2)
            column_name = match.group(3)

            # Build DAX query to calculate cardinality
            # Use quotes around table name if it contains spaces or special characters
            table_ref = (
                f"'{table_name}'" if " " in table_name or not table_name.isalnum() else table_name
            )

            dax_query = f"""
            EVALUATE
            ROW(
                "Cardinality", COUNTROWS(DISTINCT({column_ref})),
                "TotalRows", COUNTROWS({table_ref})
            )
            """

            logger.debug(f"Executing fallback DAX query for {column_ref}")
            result = qe.validate_and_execute_dax(dax_query, top_n=1)

            if result.get("success") and result.get("data"):
                data = result["data"]
                if len(data) > 0:
                    cardinality = int(data[0].get("Cardinality", 0))
                    total_rows = int(data[0].get("TotalRows", 0))

                    logger.info(
                        f"Calculated cardinality for {column_ref}: {cardinality:,} (table has {total_rows:,} rows)"
                    )

                    # Create metrics object with calculated cardinality
                    # Note: Size estimation is approximate without DMV data
                    estimated_size = self._estimate_column_size(cardinality, total_rows)

                    return ColumnMetrics(
                        table_name=table_name,
                        column_name=column_name,
                        cardinality=cardinality,
                        size_bytes=estimated_size,
                        data_type="unknown",  # Can't determine without DMV
                        encoding="calculated",
                        dictionary_size_bytes=0,
                        hierarchy_size_bytes=0,
                    )
                else:
                    logger.debug(f"DAX query returned no data for {column_ref}")
            else:
                error_msg = result.get("error", "Unknown error")
                logger.debug(f"Failed to calculate cardinality for {column_ref}: {error_msg}")

            return None

        except Exception as e:
            logger.warning(f"Error calculating cardinality for {column_ref}: {e}", exc_info=True)
            return None

    def _estimate_column_size(self, cardinality: int, total_rows: int) -> int:
        """
        Estimate column size in bytes based on cardinality

        This is a rough approximation when DMV data is unavailable:
        - Dictionary size: cardinality * average_value_size (assume 20 bytes)
        - Data column: total_rows * bytes_per_entry (4 bytes for integer references)

        Args:
            cardinality: Number of distinct values
            total_rows: Total rows in table

        Returns:
            Estimated size in bytes
        """
        # Dictionary: cardinality * assumed average value size
        avg_value_size = 20  # Conservative estimate for string values
        dictionary_size = cardinality * avg_value_size

        # Data column: references to dictionary (4 bytes per row for most cases)
        data_column_size = total_rows * 4

        # Total estimated size
        return dictionary_size + data_column_size

    def _determine_usage_context(self, dax: str, column_ref: str) -> str:
        """Determine how a column is used in the DAX expression"""
        # Find the position of the column reference
        pos = dax.find(column_ref)
        if pos == -1:
            # Try without table name
            col_name_match = re.search(r"\[([^\]]+)\]", column_ref)
            if col_name_match:
                col_name = col_name_match.group(0)
                pos = dax.find(col_name)

        if pos == -1:
            return "unknown"

        # Look for context around the column
        context_before = dax[max(0, pos - 50) : pos].upper()

        # Check for iterator functions
        iterator_functions = [
            "SUMX",
            "AVERAGEX",
            "MINX",
            "MAXX",
            "COUNTX",
            "FILTER",
            "ADDCOLUMNS",
            "SELECTCOLUMNS",
        ]

        for func in iterator_functions:
            if func in context_before:
                return "iterator"

        # Check for CALCULATE/FILTER
        if "CALCULATE" in context_before or "FILTER" in context_before:
            return "filter"

        # Check for aggregation functions
        if any(agg in context_before for agg in ["SUM", "AVERAGE", "MIN", "MAX", "COUNT"]):
            return "aggregation"

        return "general"

    def _assess_column_impact(
        self, metrics: ColumnMetrics, usage_context: str
    ) -> CardinalityImpact:
        """Assess performance impact of column usage"""

        cardinality = metrics.cardinality
        performance_impact = "low"
        recommendation = "No optimization needed"

        if usage_context == "iterator":
            if cardinality >= self.ITERATOR_CARDINALITY_CRITICAL:
                performance_impact = "critical"
                recommendation = (
                    f"CRITICAL: Iterator over {cardinality:,} rows will cause severe performance issues. "
                    f"Consider pre-aggregating data or using set-based operations instead of row-by-row iteration."
                )
            elif cardinality >= self.ITERATOR_CARDINALITY_WARNING:
                performance_impact = "high"
                recommendation = (
                    f"HIGH: Iterator over {cardinality:,} rows may impact performance. "
                    f"Consider using variables to cache calculations or reducing iterations."
                )
            elif cardinality >= 10_000:
                performance_impact = "medium"
                recommendation = (
                    f"MEDIUM: Iterator over {cardinality:,} rows. "
                    f"Monitor performance and consider optimization if slow."
                )

        elif usage_context == "filter":
            if cardinality >= self.FILTER_CARDINALITY_WARNING:
                performance_impact = "medium"
                recommendation = (
                    f"High-cardinality column ({cardinality:,} unique values) used in filter context. "
                    f"Consider using surrogate keys or reducing cardinality if possible."
                )

        # Check data type optimization opportunities
        if metrics.data_type == "String" and cardinality < 1000:
            recommendation += (
                " Consider converting to integer type with lookup table for better compression."
            )

        return CardinalityImpact(
            column=metrics.full_name,
            cardinality=cardinality,
            size_bytes=metrics.size_bytes,
            usage_context=usage_context,
            performance_impact=performance_impact,
            recommendation=recommendation,
        )

    def _get_optimization_suggestions(
        self, column_analysis: Dict[str, Any], dax_expression: str
    ) -> List[Dict[str, Any]]:
        """Get optimization suggestions based on column analysis"""
        suggestions = []

        for col_ref, analysis in column_analysis.items():
            if isinstance(analysis, dict) and "performance_impact" in analysis:
                impact = analysis["performance_impact"]

                if impact in ["critical", "high"]:
                    suggestions.append(
                        {
                            "column": col_ref,
                            "severity": impact,
                            "issue": f"High cardinality ({analysis['cardinality']:,}) in {analysis['usage_context']} context",
                            "recommendation": analysis["recommendation"],
                            "data_type": analysis.get("data_type", "unknown"),
                            "size_mb": analysis.get("size_mb", 0),
                        }
                    )

        # Check for string columns that could be optimized
        for col_ref, analysis in column_analysis.items():
            if isinstance(analysis, dict) and analysis.get("data_type") == "String":
                cardinality = analysis.get("cardinality", 0)
                if cardinality < 1000:
                    suggestions.append(
                        {
                            "column": col_ref,
                            "severity": "medium",
                            "issue": "String column with low cardinality",
                            "recommendation": (
                                f"Convert to integer type with lookup table. "
                                f"Current: {analysis.get('size_mb', 0):.2f} MB, "
                                f"Estimated savings: {analysis.get('size_mb', 0) * 0.7:.2f} MB"
                            ),
                            "optimization_type": "data_type",
                        }
                    )

        # Encoding-aware suggestions
        for col_ref, analysis in column_analysis.items():
            if not isinstance(analysis, dict):
                continue
            encoding = (analysis.get("encoding") or "").upper()
            cardinality = analysis.get("cardinality", 0)
            size_mb = analysis.get("size_mb", 0)

            # Hash-encoded column with very high cardinality
            if "HASH" in encoding and cardinality > 500_000:
                suggestions.append(
                    {
                        "column": col_ref,
                        "severity": "critical",
                        "issue": (
                            f"Hash-encoded column with {cardinality:,} distinct values — "
                            f"hash encoding is expensive at high cardinality"
                        ),
                        "recommendation": (
                            "Review column necessity. Consider splitting into "
                            "multiple lower-cardinality columns, or remove if unused. "
                            "Hash encoding at this cardinality causes significant memory "
                            "and query overhead."
                        ),
                        "optimization_type": "encoding",
                    }
                )
            # Numeric column with hash encoding — could benefit from value encoding
            elif "HASH" in encoding and analysis.get("data_type") in (
                "Int64",
                "Double",
                "Decimal",
                "Currency",
            ):
                suggestions.append(
                    {
                        "column": col_ref,
                        "severity": "medium",
                        "issue": (
                            f"Numeric column using hash encoding ({cardinality:,} distinct values)"
                        ),
                        "recommendation": (
                            "Reduce distinct values to enable value encoding. "
                            "Value encoding is more efficient for numeric columns — "
                            "consider rounding, binning, or removing unnecessary precision."
                        ),
                        "optimization_type": "encoding",
                    }
                )

            # Very high cardinality + large size — column splitting opportunity
            if cardinality > 1_000_000 and size_mb > 50:
                suggestions.append(
                    {
                        "column": col_ref,
                        "severity": "high",
                        "issue": (
                            f"Column has {cardinality:,} distinct values and "
                            f"{size_mb:.1f} MB — candidate for column splitting"
                        ),
                        "recommendation": (
                            "Split into multiple columns with lower cardinality. "
                            "Per SQLBI research, splitting a high-cardinality column "
                            "can reduce memory by 93%+. Example: split a datetime "
                            "column into separate date and time columns."
                        ),
                        "optimization_type": "column_splitting",
                    }
                )

        return suggestions

    def get_summary_statistics(self) -> Dict[str, Any]:
        """Get summary statistics for all columns in cache"""
        if not self._cache_loaded:
            self.load_column_metrics()

        if not self._column_cache:
            return {"error": "No metrics available"}

        total_columns = len(self._column_cache)
        total_size_bytes = sum(m.size_bytes for m in self._column_cache.values())

        # Categorize by cardinality
        cardinality_distribution = {"low": 0, "medium": 0, "high": 0, "very_high": 0}

        for metrics in self._column_cache.values():
            cardinality_distribution[metrics.cardinality_level] += 1

        # Top 10 largest columns
        largest_columns = sorted(
            self._column_cache.values(), key=lambda m: m.size_bytes, reverse=True
        )[:10]

        return {
            "total_columns": total_columns,
            "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
            "cardinality_distribution": cardinality_distribution,
            "largest_columns": [
                {
                    "column": m.full_name,
                    "size_mb": round(m.size_mb, 2),
                    "cardinality": m.cardinality,
                    "data_type": m.data_type,
                }
                for m in largest_columns
            ],
        }
