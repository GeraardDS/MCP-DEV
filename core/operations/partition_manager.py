"""
Partition Manager for PBIXRay MCP Server
Manages table partitions for incremental refresh scenarios
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to load AMO
AMO_AVAILABLE = False
AMOServer = None
RefreshType = None

try:
    from core.infrastructure.dll_paths import load_amo_assemblies
    load_amo_assemblies()
    from Microsoft.AnalysisServices.Tabular import Server as AMOServer, RefreshType
    AMO_AVAILABLE = True
    logger.info("AMO available for partition management")
except Exception as e:
    logger.warning(f"AMO not available: {e}")


class PartitionManager:
    """Manage table partitions."""

    def __init__(self, connection):
        """Initialize with ADOMD connection."""
        self.connection = connection

    def list_table_partitions(self, table: Optional[str] = None) -> Dict[str, Any]:
        """
        List partitions for tables.

        Args:
            table: Optional table name to filter

        Returns:
            Partition information
        """
        if not AMO_AVAILABLE:
            return {
                'success': False,
                'error': 'AMO not available for partition management'
            }

        server = AMOServer()
        try:
            server.Connect(self.connection.ConnectionString)

            if server.Databases.Count == 0:
                return {'success': False, 'error': 'No database found'}

            db = server.Databases[0]
            model = db.Model

            partitions_info = []

            tables_to_check = [t for t in model.Tables if not table or t.Name == table]

            for tbl in tables_to_check:
                table_partitions = []

                for partition in tbl.Partitions:
                    # Get partition info
                    partition_data = {
                        'name': partition.Name,
                        'mode': str(partition.Mode) if hasattr(partition, 'Mode') else 'Import',
                        'state': str(partition.State) if hasattr(partition, 'State') else 'Unknown'
                    }

                    # Get source info
                    if hasattr(partition, 'Source'):
                        source = partition.Source
                        source_type = str(source.GetType().Name) if source else 'Unknown'
                        partition_data['source_type'] = source_type

                        # Try to get expression/query
                        if hasattr(source, 'Expression'):
                            partition_data['expression'] = str(source.Expression)[:500]  # Truncate
                        elif hasattr(source, 'Query'):
                            partition_data['query'] = str(source.Query)[:500]

                    # Get refresh info
                    if hasattr(partition, 'RefreshedTime'):
                        partition_data['last_refresh'] = str(partition.RefreshedTime)

                    # Get row count (may not be available)
                    if hasattr(partition, 'RowCount'):
                        partition_data['row_count'] = partition.RowCount

                    table_partitions.append(partition_data)

                partitions_info.append({
                    'table': tbl.Name,
                    'partition_count': len(table_partitions),
                    'partitions': table_partitions
                })

            return {
                'success': True,
                'tables': partitions_info,
                'total_tables': len(partitions_info),
                'total_partitions': sum(p['partition_count'] for p in partitions_info)
            }

        except Exception as e:
            logger.error(f"Error listing partitions: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            try:
                server.Disconnect()
            except Exception:
                pass

    # refresh_partition and refresh_table intentionally removed from server to avoid exposing refresh operations

    def list_partitions(self, table: Optional[str] = None) -> Dict[str, Any]:
        """
        Alias for list_table_partitions for backward compatibility.

        Args:
            table: Optional table name to filter

        Returns:
            Partition information
        """
        return self.list_table_partitions(table)
