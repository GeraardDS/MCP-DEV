"""Table and Column ID/Name mapping module."""
import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class TableMapper:
    """Handles bidirectional mapping between table/column IDs and names. Thread-safe."""

    def __init__(self):
        """Initialize the table mapper with empty caches."""
        self._table_id_by_name: Optional[Dict[str, Any]] = None
        self._table_name_by_id: Optional[Dict[Any, str]] = None
        self._column_name_by_id: Optional[Dict[Any, str]] = None
        self._lock = threading.RLock()

    def ensure_table_mappings(self, executor_callback) -> None:
        """Load table ID<->name mappings once for fast lookups."""
        with self._lock:
            try:
                if self._table_id_by_name is not None and self._table_name_by_id is not None:
                    return
                result = executor_callback("EVALUATE INFO.TABLES()", 0)
                if not result.get('success'):
                    logger.error(f"Failed to load table mappings: {result.get('error')}")
                    self._table_id_by_name, self._table_name_by_id = None, None
                    return
                id_by_name: Dict[str, Any] = {}
                name_by_id: Dict[Any, str] = {}
                for row in result.get('rows', []):
                    name = row.get('[Name]') or row.get('Name') or row.get('[TABLE_NAME]') or row.get('TABLE_NAME')
                    tid = row.get('[ID]') or row.get('ID') or row.get('[TableID]') or row.get('TableID')
                    if name is not None and tid is not None:
                        id_by_name[name] = tid
                        name_by_id[tid] = name
                self._table_id_by_name = id_by_name
                self._table_name_by_id = name_by_id
                logger.info(f"Table mappings loaded: {len(id_by_name)} tables")
            except Exception as e:
                logger.error(f"Error building table mappings: {e}")
                self._table_id_by_name, self._table_name_by_id = None, None

    def get_table_id_from_name(self, table_name: str, executor_callback) -> Optional[int]:
        """Get the numeric TableID from a table name."""
        try:
            self.ensure_table_mappings(executor_callback)
            return (self._table_id_by_name or {}).get(table_name)
        except Exception as e:
            logger.error(f"Error getting table ID for {table_name}: {e}")
            return None

    def get_table_name_from_id(self, table_id: Any, executor_callback) -> Optional[str]:
        """Map numeric/guid TableID back to human-readable table name."""
        try:
            self.ensure_table_mappings(executor_callback)
            return (self._table_name_by_id or {}).get(table_id)
        except Exception:
            return None

    def ensure_column_mappings(self, executor_callback) -> None:
        """Load column ID<->name mappings once for fast lookups."""
        with self._lock:
            try:
                if self._column_name_by_id is not None:
                    return
                result = executor_callback("EVALUATE INFO.COLUMNS()", 0)
                if not result.get('success'):
                    logger.error(f"Failed to load column mappings: {result.get('error')}")
                    self._column_name_by_id = None
                    return
                name_by_id: Dict[Any, str] = {}
                for row in result.get('rows', []):
                    col_name = (row.get('[ExplicitName]') or row.get('ExplicitName') or
                               row.get('[InferredName]') or row.get('InferredName') or
                               row.get('[Name]') or row.get('Name') or
                               row.get('[COLUMN_NAME]') or row.get('COLUMN_NAME'))
                    col_id = row.get('[ID]') or row.get('ID') or row.get('[ColumnID]') or row.get('ColumnID')
                    if col_name is not None and col_id is not None:
                        name_by_id[col_id] = col_name
                self._column_name_by_id = name_by_id
                logger.info(f"Column mappings loaded: {len(name_by_id)} columns")
            except Exception as e:
                logger.error(f"Error building column mappings: {e}")
                self._column_name_by_id = None

    def get_column_name_from_id(self, column_id: Any, executor_callback) -> Optional[str]:
        """Map numeric/guid ColumnID back to human-readable column name."""
        try:
            self.ensure_column_mappings(executor_callback)
            return (self._column_name_by_id or {}).get(column_id)
        except Exception:
            return None

    def reset(self) -> None:
        """Reset all mappings - useful after model changes."""
        with self._lock:
            self._table_id_by_name = None
            self._table_name_by_id = None
            self._column_name_by_id = None
