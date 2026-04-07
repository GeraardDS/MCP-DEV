"""Partition CRUD Manager — manage table partitions via TOM."""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class PartitionCrudManager:
    """CRUD operations for table partitions."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def list_partitions(self, table_name: str) -> Dict[str, Any]:
        """List all partitions for a table."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        table = model.Tables.Find(table_name)
        if not table:
            return {"success": False, "error": f"Table '{table_name}' not found"}
        partitions = []
        for partition in table.Partitions:
            partitions.append({
                "name": partition.Name,
                "source_type": str(partition.SourceType),
                "mode": str(partition.Mode) if hasattr(partition, 'Mode') else None,
                "state": str(partition.State) if hasattr(partition, 'State') else None,
                "refreshed_time": str(partition.RefreshedTime) if hasattr(partition, 'RefreshedTime') else None,
            })
        return {"success": True, "table": table_name, "partitions": partitions, "count": len(partitions)}

    def describe_partition(self, table_name: str, partition_name: str) -> Dict[str, Any]:
        """Get detailed info about a partition."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        table = model.Tables.Find(table_name)
        if not table:
            return {"success": False, "error": f"Table '{table_name}' not found"}
        partition = table.Partitions.Find(partition_name)
        if not partition:
            return {"success": False, "error": f"Partition '{partition_name}' not found in '{table_name}'"}
        info = {
            "name": partition.Name,
            "source_type": str(partition.SourceType),
            "mode": str(partition.Mode) if hasattr(partition, 'Mode') else None,
            "state": str(partition.State) if hasattr(partition, 'State') else None,
            "refreshed_time": str(partition.RefreshedTime) if hasattr(partition, 'RefreshedTime') else None,
        }
        try:
            if hasattr(partition, 'Source') and hasattr(partition.Source, 'Expression'):
                info["expression"] = partition.Source.Expression
        except Exception:
            pass
        return {"success": True, "partition": info}

    def refresh_partition(self, table_name: str, partition_name: str) -> Dict[str, Any]:
        """Refresh a specific partition."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        table = model.Tables.Find(table_name)
        if not table:
            return {"success": False, "error": f"Table '{table_name}' not found"}
        partition = table.Partitions.Find(partition_name)
        if not partition:
            return {"success": False, "error": f"Partition '{partition_name}' not found in '{table_name}'"}
        try:
            partition.RequestRefresh(1)
            model.SaveChanges()
            return {"success": True, "message": f"Refresh requested for partition '{partition_name}'"}
        except Exception as e:
            return {"success": False, "error": f"Refresh failed: {str(e)}"}
