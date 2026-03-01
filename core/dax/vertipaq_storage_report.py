"""
Enhanced VertiPaq storage reporting with segment-level analysis.

Provides detailed storage metrics for Power BI models including:
- Column-level storage info (dictionary size, data size, encoding)
- Segment-level data for detailed analysis
- Table-level storage summaries
- Optimization recommendations based on storage patterns
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

# Encoding type constants from DMV
ENCODING_HASH = "HASH"
ENCODING_VALUE = "VALUE"
ENCODING_RUN_LENGTH = "RUN_LENGTH"

# Thresholds for recommendations
HIGH_CARDINALITY_THRESHOLD = 1_000_000
POOR_COMPRESSION_RATIO = 0.5
MANY_SEGMENTS_THRESHOLD = 8
LARGE_DICTIONARY_MB = 50
HIGH_CARDINALITY_COLUMN_THRESHOLD = 100_000


@dataclass
class ColumnStorage:
    """Storage metrics for a single column."""

    table_name: str
    column_name: str
    data_type: str
    cardinality: int
    dictionary_size: int  # bytes
    data_size: int  # bytes
    total_size: int  # bytes
    encoding: str  # "HASH", "VALUE", "RUN_LENGTH"
    segments: int
    partitions: int
    bits_per_value: int = 0
    compression_ratio: float = 0.0


@dataclass
class TableStorage:
    """Storage metrics for a single table."""

    table_name: str
    row_count: int
    total_size: int  # bytes
    dictionary_size: int
    data_size: int
    columns: List[ColumnStorage] = field(default_factory=list)
    relationships_size: int = 0


@dataclass
class StorageReport:
    """Complete storage report for the model."""

    tables: List[TableStorage]
    total_model_size: int
    total_rows: int
    recommendations: List[Dict[str, str]]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON response."""
        table_dicts = []
        for t in self.tables:
            col_dicts = []
            for c in t.columns:
                col_dicts.append({
                    "table": c.table_name,
                    "column": c.column_name,
                    "data_type": c.data_type,
                    "cardinality": c.cardinality,
                    "dictionary_size_bytes": c.dictionary_size,
                    "data_size_bytes": c.data_size,
                    "total_size_bytes": c.total_size,
                    "encoding": c.encoding,
                    "segments": c.segments,
                    "partitions": c.partitions,
                    "bits_per_value": c.bits_per_value,
                    "compression_ratio": round(
                        c.compression_ratio, 3
                    ),
                })
            table_dicts.append({
                "table_name": t.table_name,
                "row_count": t.row_count,
                "total_size_bytes": t.total_size,
                "total_size_mb": round(
                    t.total_size / (1024 * 1024), 2
                ),
                "dictionary_size_bytes": t.dictionary_size,
                "data_size_bytes": t.data_size,
                "relationships_size_bytes": t.relationships_size,
                "column_count": len(t.columns),
                "columns": col_dicts,
            })

        # Sort tables by total_size descending
        table_dicts.sort(
            key=lambda x: x["total_size_bytes"], reverse=True
        )

        total_mb = round(
            self.total_model_size / (1024 * 1024), 2
        )

        return {
            "success": True,
            "total_model_size_bytes": self.total_model_size,
            "total_model_size_mb": total_mb,
            "total_rows": self.total_rows,
            "table_count": len(self.tables),
            "tables": table_dicts,
            "recommendations": self.recommendations,
            "top_tables_by_size": [
                {
                    "table": t["table_name"],
                    "size_mb": t["total_size_mb"],
                    "row_count": t["row_count"],
                    "columns": t["column_count"],
                }
                for t in table_dicts[:10]
            ],
        }


class VertiPaqStorageReport:
    """Enhanced VertiPaq storage reporting using DMV queries."""

    def __init__(self, query_executor):
        self._qe = query_executor

    def generate_report(self) -> StorageReport:
        """Generate full storage report using DMVs."""
        # Step 1: Get column-level storage info
        columns = self._query_column_storage()

        # Step 2: Get segment-level data for enrichment
        segment_data = self._query_segment_data()

        # Step 3: Enrich columns with segment info
        self._enrich_with_segments(columns, segment_data)

        # Step 4: Get table-level row counts
        table_rows = self._query_table_rows()

        # Step 5: Aggregate into table storage objects
        tables = self._aggregate_tables(columns, table_rows)

        # Step 6: Calculate totals
        total_size = sum(t.total_size for t in tables)
        total_rows = sum(t.row_count for t in tables)

        # Step 7: Generate recommendations
        recommendations = self._generate_recommendations(
            tables
        )

        return StorageReport(
            tables=tables,
            total_model_size=total_size,
            total_rows=total_rows,
            recommendations=recommendations,
        )

    def _query_column_storage(self) -> List[ColumnStorage]:
        """Query column storage info via DMV."""
        dmv_query = (
            "SELECT "
            "[DIMENSION_NAME], "
            "[ATTRIBUTE_NAME], "
            "[ATTRIBUTE_COUNT], "
            "[DICTIONARY_SIZE], "
            "[COLUMN_ENCODING], "
            "[COLUMN_TYPE], "
            "[DATATYPE], "
            "[ATTRIBUTE_SIZE] "
            "FROM $SYSTEM.DISCOVER_STORAGE_TABLE_COLUMNS"
        )

        columns: List[ColumnStorage] = []

        try:
            result = self._qe.execute_dmv_query(dmv_query)
            if not result.get("success"):
                logger.warning(
                    "DISCOVER_STORAGE_TABLE_COLUMNS failed: "
                    f"{result.get('error', 'Unknown')}"
                )
                return self._query_column_storage_fallback()

            for row in result.get("data", []):
                col_type = row.get(
                    "COLUMN_TYPE", "BASIC_DATA"
                )
                # Skip internal RowNumber columns
                attr_name = row.get("ATTRIBUTE_NAME", "")
                if (
                    col_type == "ROWNUM"
                    or attr_name.startswith("RowNumber-")
                ):
                    continue

                dict_size = _safe_int(
                    row.get("DICTIONARY_SIZE", 0)
                )
                attr_size = _safe_int(
                    row.get("ATTRIBUTE_SIZE", 0)
                )
                data_size = max(0, attr_size - dict_size)

                columns.append(
                    ColumnStorage(
                        table_name=row.get(
                            "DIMENSION_NAME", ""
                        ),
                        column_name=attr_name,
                        data_type=row.get("DATATYPE", ""),
                        cardinality=_safe_int(
                            row.get("ATTRIBUTE_COUNT", 0)
                        ),
                        dictionary_size=dict_size,
                        data_size=data_size,
                        total_size=attr_size,
                        encoding=_normalize_encoding(
                            row.get("COLUMN_ENCODING", "")
                        ),
                        segments=0,
                        partitions=0,
                    )
                )

            logger.info(
                f"Retrieved storage info for "
                f"{len(columns)} columns"
            )

        except Exception as e:
            logger.error(
                f"Error querying column storage: {e}",
                exc_info=True,
            )
            return self._query_column_storage_fallback()

        return columns

    def _query_column_storage_fallback(
        self,
    ) -> List[ColumnStorage]:
        """
        Fallback using INFO.STORAGETABLECOLUMNS() DAX
        function when DMV is unavailable.
        """
        dax_query = (
            "EVALUATE INFO.STORAGETABLECOLUMNS()"
        )

        columns: List[ColumnStorage] = []

        try:
            result = self._qe.validate_and_execute_dax(
                dax_query, top_n=10000
            )
            if not result.get("success"):
                logger.warning(
                    "INFO.STORAGETABLECOLUMNS() "
                    "fallback also failed: "
                    f"{result.get('error', 'Unknown')}"
                )
                return columns

            for row in result.get("data", []):
                # INFO function uses different column names
                table = row.get(
                    "TableName",
                    row.get("DIMENSION_NAME", ""),
                )
                col_name = row.get(
                    "ColumnName",
                    row.get("ATTRIBUTE_NAME", ""),
                )

                if not table or not col_name:
                    continue

                # Skip RowNumber columns
                if col_name.startswith("RowNumber-"):
                    continue

                dict_size = _safe_int(
                    row.get(
                        "DictionarySize",
                        row.get("DICTIONARY_SIZE", 0),
                    )
                )
                total = _safe_int(
                    row.get(
                        "ColumnSize",
                        row.get("ATTRIBUTE_SIZE", 0),
                    )
                )
                data_size = max(0, total - dict_size)

                columns.append(
                    ColumnStorage(
                        table_name=table,
                        column_name=col_name,
                        data_type=row.get(
                            "DataType",
                            row.get("DATATYPE", ""),
                        ),
                        cardinality=_safe_int(
                            row.get(
                                "ColumnCardinality",
                                row.get(
                                    "ATTRIBUTE_COUNT", 0
                                ),
                            )
                        ),
                        dictionary_size=dict_size,
                        data_size=data_size,
                        total_size=total,
                        encoding=_normalize_encoding(
                            row.get(
                                "ColumnEncoding",
                                row.get(
                                    "COLUMN_ENCODING", ""
                                ),
                            )
                        ),
                        segments=0,
                        partitions=0,
                    )
                )

            logger.info(
                f"Fallback retrieved storage info for "
                f"{len(columns)} columns"
            )

        except Exception as e:
            logger.error(
                f"Fallback column storage query failed: "
                f"{e}",
                exc_info=True,
            )

        return columns

    def _query_segment_data(self) -> Dict[str, Dict]:
        """
        Query segment-level data for detailed analysis.

        Returns a dict keyed by 'TableName|ColumnName'
        with segment counts and partition counts.
        """
        dmv_query = (
            "SELECT "
            "[DIMENSION_NAME], "
            "[ATTRIBUTE_NAME], "
            "[SEGMENT_NUMBER], "
            "[TABLE_PARTITION_NUMBER], "
            "[RECORDS_COUNT], "
            "[USED_SIZE], "
            "[COMPRESSION_TYPE], "
            "[BITS_COUNT] "
            "FROM "
            "$SYSTEM.DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS"
        )

        segment_map: Dict[str, Dict] = {}

        try:
            result = self._qe.execute_dmv_query(dmv_query)
            if not result.get("success"):
                logger.warning(
                    "DISCOVER_STORAGE_TABLE_COLUMN_"
                    "SEGMENTS unavailable: "
                    f"{result.get('error', 'Unknown')}"
                )
                return segment_map

            for row in result.get("data", []):
                table = row.get("DIMENSION_NAME", "")
                col = row.get("ATTRIBUTE_NAME", "")
                if not table or not col:
                    continue

                key = f"{table}|{col}"
                if key not in segment_map:
                    segment_map[key] = {
                        "segments": set(),
                        "partitions": set(),
                        "total_records": 0,
                        "total_used_size": 0,
                        "max_bits": 0,
                    }

                entry = segment_map[key]
                seg_num = row.get("SEGMENT_NUMBER", 0)
                part_num = row.get(
                    "TABLE_PARTITION_NUMBER", 0
                )
                entry["segments"].add(seg_num)
                entry["partitions"].add(part_num)
                entry["total_records"] += _safe_int(
                    row.get("RECORDS_COUNT", 0)
                )
                entry["total_used_size"] += _safe_int(
                    row.get("USED_SIZE", 0)
                )
                bits = _safe_int(
                    row.get("BITS_COUNT", 0)
                )
                if bits > entry["max_bits"]:
                    entry["max_bits"] = bits

            # Convert sets to counts
            for key, entry in segment_map.items():
                entry["segment_count"] = len(
                    entry["segments"]
                )
                entry["partition_count"] = len(
                    entry["partitions"]
                )
                del entry["segments"]
                del entry["partitions"]

            logger.info(
                f"Retrieved segment data for "
                f"{len(segment_map)} columns"
            )

        except Exception as e:
            logger.warning(
                f"Segment data query failed "
                f"(non-critical): {e}"
            )

        return segment_map

    def _enrich_with_segments(
        self,
        columns: List[ColumnStorage],
        segment_data: Dict[str, Dict],
    ) -> None:
        """Enrich column storage objects with segment data."""
        for col in columns:
            key = f"{col.table_name}|{col.column_name}"
            seg_info = segment_data.get(key)
            if seg_info:
                col.segments = seg_info.get(
                    "segment_count", 0
                )
                col.partitions = seg_info.get(
                    "partition_count", 0
                )
                col.bits_per_value = seg_info.get(
                    "max_bits", 0
                )

                # Calculate compression ratio
                total_records = seg_info.get(
                    "total_records", 0
                )
                used_size = seg_info.get(
                    "total_used_size", 0
                )
                if total_records > 0 and used_size > 0:
                    # Ratio of actual size to raw size
                    # (assuming 8 bytes per value raw)
                    raw_size = total_records * 8
                    col.compression_ratio = (
                        used_size / raw_size
                    )

    def _query_table_rows(self) -> Dict[str, int]:
        """Query row counts per table via DMV."""
        dmv_query = (
            "SELECT "
            "[DIMENSION_NAME], "
            "[DIMENSION_CARDINALITY] "
            "FROM $SYSTEM.DISCOVER_STORAGE_TABLES "
            "WHERE [DIMENSION_IS_VISIBLE]"
        )

        table_rows: Dict[str, int] = {}

        try:
            result = self._qe.execute_dmv_query(dmv_query)
            if not result.get("success"):
                logger.warning(
                    "DISCOVER_STORAGE_TABLES failed, "
                    "row counts unavailable"
                )
                return table_rows

            for row in result.get("data", []):
                table = row.get("DIMENSION_NAME", "")
                if table:
                    rows = _safe_int(
                        row.get(
                            "DIMENSION_CARDINALITY", 0
                        )
                    )
                    # Keep the max if a table appears
                    # multiple times
                    if table not in table_rows:
                        table_rows[table] = rows
                    else:
                        table_rows[table] = max(
                            table_rows[table], rows
                        )

        except Exception as e:
            logger.warning(
                f"Table row count query failed: {e}"
            )

        return table_rows

    def _aggregate_tables(
        self,
        columns: List[ColumnStorage],
        table_rows: Dict[str, int],
    ) -> List[TableStorage]:
        """Aggregate column storage into table storage objects."""
        table_map: Dict[str, TableStorage] = {}

        for col in columns:
            tname = col.table_name
            if tname not in table_map:
                table_map[tname] = TableStorage(
                    table_name=tname,
                    row_count=table_rows.get(tname, 0),
                    total_size=0,
                    dictionary_size=0,
                    data_size=0,
                    columns=[],
                )

            ts = table_map[tname]
            ts.columns.append(col)
            ts.total_size += col.total_size
            ts.dictionary_size += col.dictionary_size
            ts.data_size += col.data_size

        # Sort columns within each table by size desc
        for ts in table_map.values():
            ts.columns.sort(
                key=lambda c: c.total_size, reverse=True
            )

        # Sort tables by total_size descending
        return sorted(
            table_map.values(),
            key=lambda t: t.total_size,
            reverse=True,
        )

    def _generate_recommendations(
        self, tables: List[TableStorage]
    ) -> List[Dict[str, str]]:
        """Generate optimization recommendations."""
        recommendations: List[Dict[str, str]] = []

        all_columns: List[ColumnStorage] = []
        for t in tables:
            all_columns.extend(t.columns)

        # 1. High-cardinality columns
        high_card = [
            c
            for c in all_columns
            if c.cardinality > HIGH_CARDINALITY_THRESHOLD
        ]
        for col in high_card:
            size_mb = round(
                col.total_size / (1024 * 1024), 2
            )
            recommendations.append({
                "severity": "high",
                "category": "cardinality",
                "column": (
                    f"{col.table_name}"
                    f"[{col.column_name}]"
                ),
                "message": (
                    f"High cardinality "
                    f"({col.cardinality:,} unique "
                    f"values, {size_mb} MB). "
                    f"Consider removing, aggregating, "
                    f"or splitting into a separate "
                    f"table."
                ),
            })

        # 2. Poor compression ratio columns
        poor_compress = [
            c
            for c in all_columns
            if c.compression_ratio > POOR_COMPRESSION_RATIO
            and c.compression_ratio > 0
            and c.total_size > 1024 * 1024  # >1MB
        ]
        for col in poor_compress:
            ratio_pct = round(
                col.compression_ratio * 100, 1
            )
            recommendations.append({
                "severity": "medium",
                "category": "compression",
                "column": (
                    f"{col.table_name}"
                    f"[{col.column_name}]"
                ),
                "message": (
                    f"Poor compression ratio "
                    f"({ratio_pct}%). Column data "
                    f"is not compressing well. "
                    f"Consider data type changes or "
                    f"reducing precision."
                ),
            })

        # 3. HASH encoding on low-cardinality columns
        hash_low_card = [
            c
            for c in all_columns
            if c.encoding == ENCODING_HASH
            and c.cardinality < 1000
            and c.total_size > 100 * 1024  # >100KB
        ]
        for col in hash_low_card:
            recommendations.append({
                "severity": "low",
                "category": "encoding",
                "column": (
                    f"{col.table_name}"
                    f"[{col.column_name}]"
                ),
                "message": (
                    f"HASH encoding on low-cardinality "
                    f"column ({col.cardinality} unique "
                    f"values). VALUE encoding might "
                    f"be more efficient."
                ),
            })

        # 4. Tables with many segments
        for t in tables:
            max_segs = max(
                (c.segments for c in t.columns),
                default=0,
            )
            if max_segs > MANY_SEGMENTS_THRESHOLD:
                recommendations.append({
                    "severity": "medium",
                    "category": "segments",
                    "table": t.table_name,
                    "message": (
                        f"Table has columns with up to "
                        f"{max_segs} segments. Many "
                        f"segments can increase memory "
                        f"and slow scans. Consider "
                        f"partition management."
                    ),
                })

        # 5. Large dictionary sizes
        large_dict = [
            c
            for c in all_columns
            if c.dictionary_size
            > LARGE_DICTIONARY_MB * 1024 * 1024
        ]
        for col in large_dict:
            dict_mb = round(
                col.dictionary_size / (1024 * 1024), 2
            )
            recommendations.append({
                "severity": "high",
                "category": "dictionary",
                "column": (
                    f"{col.table_name}"
                    f"[{col.column_name}]"
                ),
                "message": (
                    f"Very large dictionary "
                    f"({dict_mb} MB). This column "
                    f"stores many unique values. "
                    f"Consider removing if unused "
                    f"or reducing granularity."
                ),
            })

        # 6. Overall model size warning
        total_mb = sum(
            t.total_size for t in tables
        ) / (1024 * 1024)
        if total_mb > 1000:
            recommendations.append({
                "severity": "high",
                "category": "model_size",
                "message": (
                    f"Total model storage is "
                    f"{round(total_mb, 1)} MB. "
                    f"Consider incremental refresh, "
                    f"aggregation tables, or removing "
                    f"unused columns to reduce size."
                ),
            })

        # Sort by severity: high > medium > low
        severity_order = {
            "high": 0,
            "medium": 1,
            "low": 2,
        }
        recommendations.sort(
            key=lambda r: severity_order.get(
                r.get("severity", "low"), 3
            )
        )

        return recommendations


def _safe_int(value: Any) -> int:
    """Safely convert a value to int."""
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _normalize_encoding(raw: Any) -> str:
    """Normalize encoding string from DMV."""
    if not raw:
        return "unknown"
    enc = str(raw).upper().strip()
    # Map numeric/variant names to standard labels
    encoding_map = {
        "0": ENCODING_HASH,
        "1": ENCODING_VALUE,
        "2": ENCODING_RUN_LENGTH,
        "HASH": ENCODING_HASH,
        "VALUE": ENCODING_VALUE,
        "RLE": ENCODING_RUN_LENGTH,
        "RUN_LENGTH": ENCODING_RUN_LENGTH,
        "RUNLENGTH": ENCODING_RUN_LENGTH,
    }
    return encoding_map.get(enc, enc)
