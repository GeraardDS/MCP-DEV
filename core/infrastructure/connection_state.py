"""
Connection State Manager for PBIXRay MCP Server

Manages connection state and service initialization to avoid repeated initialization.
"""

import logging
from typing import Any, Dict, Optional, Type, Tuple
from core.config.config_manager import config
import threading

logger = logging.getLogger(__name__)


class ConnectionState:
    """
    Manages connection state and service instances to avoid repeated initialization.
    """
    
    def __init__(self):
        """Initialize connection state manager."""
        self.connection_manager = None
        self.query_executor = None
        self.dax_injector = None
        self.bpa_analyzer = None
        self.dependency_analyzer = None
        self.bulk_operations = None
        self.calc_group_manager = None
        self.partition_manager = None
        self.rls_manager = None
        self.table_crud_manager = None
        self.column_crud_manager = None
        self.measure_crud_manager = None
        self.relationship_crud_manager = None
        self.model_exporter = None
        self.performance_optimizer = None
        self.model_validator = None
        self.agent_policy = None

        self._is_connected = False
        self._connection_info = None
        self._managers_initialized = False

        # PBIP/PBIX file information (for visual debugger integration)
        self._pbip_folder_path: Optional[str] = None  # Path to PBIP project folder
        self._file_full_path: Optional[str] = None  # Full path to .pbix or .pbip file
        self._file_type: Optional[str] = None  # 'pbix' or 'pbip'
        self._pbip_path_source: str = 'none'  # 'auto-detected', 'manual', 'none'

        # Rolling query history (lightweight)
        self._query_history = []
        self._query_history_max = 200
        # Agent context memory and safety limits
        self._context: Dict[str, Any] = {}
        self._safety_limits: Dict[str, Any] = {
            'max_rows_per_call': 10000,
        }
        # Performance baselines and last result summary
        self._perf_baselines: Dict[str, Any] = {}
        self._last_result_meta: Dict[str, Any] = {}
        # Init lock for lazy managers
        self._init_lock = threading.RLock()

        # Table mapping cache (shared across all tool invocations)
        # This cache persists table ID<->name mappings to avoid repeated INFO.TABLES() queries
        self._table_id_by_name: Optional[Dict[str, Any]] = None
        self._table_name_by_id: Optional[Dict[Any, str]] = None
        self._table_mapping_timestamp: Optional[float] = None
        self._table_mapping_ttl: int = config.get('performance.table_mapping_cache_ttl', 600)  # 10 minutes default

        # Intelligent analysis components (lazy loaded only when needed)
        self.context_tracker = None
        self.suggestion_engine = None
        self.smart_defaults = None
    
    def is_connected(self) -> bool:
        """Check if currently connected to Power BI."""
        return (self._is_connected and
                self.connection_manager is not None and
                self.connection_manager.is_connected())

    def verify_connection(self, auto_reconnect: bool = True) -> Dict[str, Any]:
        """
        Verify connection is alive and optionally attempt reconnection.

        Args:
            auto_reconnect: If True, attempt to reconnect on connection loss

        Returns:
            Dict with:
            - connected: bool - whether connection is healthy
            - reconnected: bool - whether a reconnection was performed
            - error: str - error message if not connected
        """
        if not self.connection_manager:
            return {
                'connected': False,
                'reconnected': False,
                'error': 'Connection manager not initialized'
            }

        # Check if currently connected
        if self.connection_manager.is_connected():
            return {'connected': True, 'reconnected': False}

        # Not connected
        if not auto_reconnect:
            return {
                'connected': False,
                'reconnected': False,
                'error': 'Connection lost and auto_reconnect is disabled'
            }

        # Attempt reconnection
        logger.info("Connection lost, attempting reconnection...")
        result = self.connection_manager.reconnect(max_retries=3, retry_delay=0.5)

        if result.get('success'):
            # Invalidate any cached connection states
            if self.query_executor and hasattr(self.query_executor, 'invalidate_connection_cache'):
                self.query_executor.invalidate_connection_cache()
            logger.info("Connection restored successfully")
            return {'connected': True, 'reconnected': True}
        else:
            self._is_connected = False
            return {
                'connected': False,
                'reconnected': False,
                'error': result.get('error', 'Reconnection failed')
            }

    def ensure_connected(self) -> Dict[str, Any]:
        """
        Ensure connection is alive, attempting reconnection if needed.
        Alias for verify_connection(auto_reconnect=True).

        Returns:
            Dict with connection status
        """
        return self.verify_connection(auto_reconnect=True)

    def set_connection_manager(self, connection_manager):
        """Set the connection manager instance."""
        self.connection_manager = connection_manager
        self._is_connected = connection_manager.is_connected() if connection_manager else False

    def _is_table_mapping_cache_valid(self) -> bool:
        """Check if table mapping cache is valid (not expired)."""
        if self._table_id_by_name is None or self._table_name_by_id is None:
            return False
        if self._table_mapping_timestamp is None:
            return False
        import time
        age = time.time() - self._table_mapping_timestamp
        return age <= self._table_mapping_ttl

    def get_table_mappings(self, refresh: bool = False) -> tuple[Optional[Dict[str, Any]], Optional[Dict[Any, str]]]:
        """
        Get cached table ID<->name mappings, loading them if needed.

        Args:
            refresh: Force refresh from database even if cache is valid

        Returns:
            Tuple of (id_by_name dict, name_by_id dict) or (None, None) on error
        """
        # Return cached mappings if valid and not forcing refresh
        if not refresh and self._is_table_mapping_cache_valid():
            logger.debug(f"Table mappings cache hit ({len(self._table_id_by_name or {})} tables)")
            return (self._table_id_by_name, self._table_name_by_id)

        # Load fresh mappings
        try:
            if not self.query_executor:
                logger.warning("Cannot load table mappings: query executor not initialized")
                return (None, None)

            logger.debug("Loading table mappings from INFO.TABLES()...")
            # NOTE: No circular dependency here - INFO.TABLES() is a system function that
            # doesn't require table name resolution, so validate_and_execute_dax() won't
            # call _ensure_table_mappings() for this query
            result = self.query_executor.validate_and_execute_dax("EVALUATE INFO.TABLES()", 0)

            if not result.get('success'):
                logger.error(f"Failed to load table mappings: {result.get('error')}")
                return (None, None)

            id_by_name: Dict[str, Any] = {}
            name_by_id: Dict[Any, str] = {}

            for row in result.get('rows', []):
                # Check bracketed keys FIRST since Power BI Desktop returns [ID] and [Name]
                name = row.get('[Name]') or row.get('Name') or row.get('[TABLE_NAME]') or row.get('TABLE_NAME')
                tid = row.get('[ID]') or row.get('ID') or row.get('[TableID]') or row.get('TableID')

                if name is not None and tid is not None:
                    id_by_name[name] = tid
                    name_by_id[tid] = name

            # Update cache with timestamp
            import time
            self._table_id_by_name = id_by_name
            self._table_name_by_id = name_by_id
            self._table_mapping_timestamp = time.time()

            logger.info(f"Table mappings loaded and cached: {len(id_by_name)} tables (TTL: {self._table_mapping_ttl}s)")
            return (self._table_id_by_name, self._table_name_by_id)

        except Exception as e:
            logger.error(f"Error loading table mappings: {e}")
            return (None, None)

    def invalidate_table_mappings(self) -> Dict[str, Any]:
        """
        Manually invalidate table mapping cache, forcing reload on next access.
        Useful after schema changes (e.g., table rename, add/delete).

        Returns:
            Status dictionary with invalidation result
        """
        try:
            had_cache = self._table_id_by_name is not None
            table_count = len(self._table_id_by_name) if self._table_id_by_name else 0

            self._table_id_by_name = None
            self._table_name_by_id = None
            self._table_mapping_timestamp = None

            if had_cache:
                logger.info(f"Table mapping cache invalidated ({table_count} tables)")
                return {
                    'success': True,
                    'message': f'Cache invalidated ({table_count} tables)',
                    'tables_cleared': table_count
                }
            else:
                return {
                    'success': True,
                    'message': 'No cache to invalidate',
                    'tables_cleared': 0
                }
        except Exception as e:
            logger.error(f"Error invalidating table mapping cache: {e}")
            return {'success': False, 'error': str(e)}
    
    def initialize_managers(self, force_reinit: bool = False):
        """
        Initialize all service managers with thread-safe locking.

        Args:
            force_reinit: Force reinitialization even if already initialized
        """
        # Quick check without lock
        if self._managers_initialized and not force_reinit:
            logger.debug("Managers already initialized, skipping")
            return

        # Thread-safe initialization with double-check locking pattern
        with self._init_lock:
            # Double-check after acquiring lock
            if self._managers_initialized and not force_reinit:
                logger.debug("Managers already initialized (double-check), skipping")
                return

            if not self.is_connected() or not self.connection_manager:
                logger.warning("Cannot initialize managers: not connected")
                return

            try:
                conn = self.connection_manager.get_connection()

                from core.infrastructure.query_executor import OptimizedQueryExecutor
                from core.dax.dax_injector import DAXInjector
                from core.model.dependency_analyzer import DependencyAnalyzer
                from core.operations.bulk_operations import BulkOperationsManager
                from core.operations.calculation_group_manager import CalculationGroupManager
                from core.operations.partition_manager import PartitionManager
                from core.operations.rls_manager import RLSManager
                from core.operations.table_crud_manager import TableCRUDManager
                from core.operations.column_crud_manager import ColumnCRUDManager
                from core.operations.measure_crud_manager import MeasureCRUDManager
                from core.operations.relationship_crud_manager import RelationshipCRUDManager
                from core.model.model_exporter import ModelExporter
                from core.performance.performance_optimizer import PerformanceOptimizer
                from core.model.model_validator import ModelValidator

                # Initialize query executor first (others depend on it)
                if not self.query_executor or force_reinit:
                    self.query_executor = OptimizedQueryExecutor(conn)
                    # Link to connection state for shared table mapping cache (PERFORMANCE)
                    try:
                        self.query_executor.set_connection_state(self)
                    except Exception as e:
                        logger.warning(f"Failed to link query executor to connection state: {e}")
                    # Register history logger to capture executions
                    try:
                        self.query_executor.set_history_logger(self._history_logger)
                    except Exception:
                        pass
                    logger.info("[OK] Query executor initialized")

                # Initialize other managers
                if not self.dax_injector or force_reinit:
                    self.dax_injector = DAXInjector(conn)
                    # Link to connection manager for reconnection support
                    if self.connection_manager and hasattr(self.dax_injector, 'set_connection_manager'):
                        self.dax_injector.set_connection_manager(self.connection_manager)
                    logger.debug("[OK] DAX injector initialized")

                if not self.dependency_analyzer or force_reinit:
                    self.dependency_analyzer = DependencyAnalyzer(self.query_executor)
                    logger.debug("[OK] Dependency analyzer initialized")

                if not self.bulk_operations or force_reinit:
                    self.bulk_operations = BulkOperationsManager(self.dax_injector)
                    # Link to connection manager for reconnection support
                    if self.connection_manager and hasattr(self.bulk_operations, 'set_connection_manager'):
                        self.bulk_operations.set_connection_manager(self.connection_manager)
                    logger.debug("[OK] Bulk operations initialized")

                if not self.calc_group_manager or force_reinit:
                    self.calc_group_manager = CalculationGroupManager(conn)
                    logger.debug("[OK] Calculation group manager initialized")

                if not self.partition_manager or force_reinit:
                    self.partition_manager = PartitionManager(conn)
                    logger.debug("[OK] Partition manager initialized")

                if not self.rls_manager or force_reinit:
                    self.rls_manager = RLSManager(conn, self.query_executor)
                    logger.debug("[OK] RLS manager initialized")

                if not self.table_crud_manager or force_reinit:
                    self.table_crud_manager = TableCRUDManager(conn)
                    logger.debug("[OK] Table CRUD manager initialized")

                if not self.column_crud_manager or force_reinit:
                    self.column_crud_manager = ColumnCRUDManager(conn)
                    logger.debug("[OK] Column CRUD manager initialized")

                if not self.measure_crud_manager or force_reinit:
                    self.measure_crud_manager = MeasureCRUDManager(conn)
                    logger.debug("[OK] Measure CRUD manager initialized")

                if not self.relationship_crud_manager or force_reinit:
                    self.relationship_crud_manager = RelationshipCRUDManager(conn)
                    logger.debug("[OK] Relationship CRUD manager initialized")

                if not self.model_exporter or force_reinit:
                    self.model_exporter = ModelExporter(conn)
                    logger.debug("[OK] Model exporter initialized")

                if not self.performance_optimizer or force_reinit:
                    self.performance_optimizer = PerformanceOptimizer(self.query_executor)
                    logger.debug("[OK] Performance optimizer initialized")

                if not self.model_validator or force_reinit:
                    self.model_validator = ModelValidator(self.query_executor)
                    logger.debug("[OK] Model validator initialized")

                # Initialize BPA if available
                if config.is_feature_enabled('enable_bpa'):
                    self._initialize_bpa(force_reinit)

                self._managers_initialized = True
                logger.info("[OK] All managers initialized successfully")

            except Exception as e:
                logger.error(f"Error initializing managers: {e}", exc_info=True)
                self._managers_initialized = False
    
    def _initialize_bpa(self, force_reinit: bool = False):
        """Initialize BPA analyzer if available."""
        if not self.bpa_analyzer or force_reinit:
            try:
                from core.analysis.bpa_analyzer import BPAAnalyzer
                import os

                # Locate BPA rules file - try comprehensive first, then fallback
                script_dir = os.path.dirname(os.path.abspath(__file__))
                root_dir = os.path.dirname(os.path.dirname(script_dir))

                # Try comprehensive rules file first (70 rules)
                rules_path = os.path.join(root_dir, "config", "bpa_rules_comprehensive.json")
                if not os.path.exists(rules_path):
                    # Fallback to default rules (20 rules)
                    rules_path = os.path.join(root_dir, "config", "bpa_rules_default.json")
                    logger.info("Using default BPA rules (20 rules)")
                else:
                    logger.info("Using comprehensive BPA rules (70 rules)")

                if not os.path.exists(rules_path):
                    # Last fallback to legacy location
                    rules_path = os.path.join(root_dir, "core", "bpa.json")

                self.bpa_analyzer = BPAAnalyzer(rules_path)
                logger.debug(f"[OK] BPA analyzer initialized with {len(self.bpa_analyzer.rules)} rules")
            except ImportError:
                logger.debug("BPA not available (import error)")
            except FileNotFoundError as e:
                logger.warning(f"BPA rules file not found: {e}")
            except Exception as e:
                logger.error(f"Error initializing BPA: {e}")

    # ---- Thread-safe lazy manager ensure helpers ----
    def _ensure_model_exporter(self):
        """Thread-safe lazy initialization for model_exporter manager."""
        if self.model_exporter is not None:
            return self.model_exporter
        with self._init_lock:
            if self.model_exporter is None:
                try:
                    from core.model.model_exporter import ModelExporter
                    conn = self.connection_manager.get_connection() if self.connection_manager else None
                    if conn is None:
                        raise RuntimeError("No active connection")
                    self.model_exporter = ModelExporter(conn)
                    logger.info("[OK] Initialized model_exporter")
                except Exception as e:
                    logger.error(f"Failed to initialize model_exporter: {e}")
                    raise
        return self.model_exporter
    
    def get_manager(self, manager_name: str) -> Optional[Any]:
        """
        Get a specific manager instance.
        
        Args:
            manager_name: Name of the manager to retrieve
            
        Returns:
            Manager instance or None if not available
        """
        return getattr(self, manager_name, None)
    
    def cleanup(self):
        """Clean up connection state and managers."""
        self.query_executor = None
        self.dax_injector = None
        self.bpa_analyzer = None
        self.dependency_analyzer = None
        self.bulk_operations = None
        self.calc_group_manager = None
        self.partition_manager = None
        self.rls_manager = None
        self.table_crud_manager = None
        self.column_crud_manager = None
        self.measure_crud_manager = None
        self.relationship_crud_manager = None
        self.model_exporter = None
        self.performance_optimizer = None
        self.model_validator = None
        self.agent_policy = None

        self._is_connected = False
        self._connection_info = None
        self._managers_initialized = False

        # Clear table mapping cache
        self._table_id_by_name = None
        self._table_name_by_id = None
        self._table_mapping_timestamp = None

        # Clear PBIP path information
        self._pbip_folder_path = None
        self._file_full_path = None
        self._file_type = None
        self._pbip_path_source = 'none'

        logger.info("Connection state cleaned up")

    # ---- PBIP Path Management ----
    def set_pbip_info(
        self,
        pbip_folder_path: Optional[str] = None,
        file_full_path: Optional[str] = None,
        file_type: Optional[str] = None,
        source: str = 'manual'
    ) -> Dict[str, Any]:
        """
        Set PBIP/PBIX file information.

        Args:
            pbip_folder_path: Path to PBIP project folder (for PBIP projects)
            file_full_path: Full path to .pbix or .pbip file
            file_type: 'pbix' or 'pbip'
            source: 'auto-detected' or 'manual'

        Returns:
            Status dictionary with current PBIP info
        """
        self._pbip_folder_path = pbip_folder_path
        self._file_full_path = file_full_path
        self._file_type = file_type
        self._pbip_path_source = source

        logger.info(f"PBIP info set: type={file_type}, folder={pbip_folder_path}, source={source}")
        return self.get_pbip_info()

    def get_pbip_info(self) -> Dict[str, Any]:
        """
        Get current PBIP/PBIX file information.

        Returns:
            Dictionary with:
            - pbip_folder_path: Path to PBIP folder (None for PBIX)
            - file_full_path: Full path to file
            - file_type: 'pbix', 'pbip', or None
            - source: 'auto-detected', 'manual', or 'none'
            - pbip_available: True if PBIP folder is available for analysis
        """
        return {
            'pbip_folder_path': self._pbip_folder_path,
            'file_full_path': self._file_full_path,
            'file_type': self._file_type,
            'source': self._pbip_path_source,
            'pbip_available': self._pbip_folder_path is not None and self._file_type == 'pbip'
        }

    def get_pbip_folder_path(self) -> Optional[str]:
        """Get the PBIP folder path if available."""
        return self._pbip_folder_path

    @property
    def pbip_path(self) -> Optional[str]:
        """Alias for get_pbip_folder_path for easier access."""
        return self._pbip_folder_path

    def is_pbip_available(self) -> bool:
        """Check if PBIP project folder is available for analysis."""
        return self._pbip_folder_path is not None and self._file_type == 'pbip'

    # ---- Query history helpers ----
    def _history_logger(self, entry: dict) -> None:
        """Internal callback used by query executor to log execution metadata."""
        try:
            # Attach timestamp and minimal connection hint
            import time as _t
            entry = dict(entry or {})
            entry.setdefault('ts', _t.time())
            try:
                if self.connection_manager:
                    info = self.connection_manager.get_instance_info() or {}
                    if 'port' in info:
                        entry.setdefault('port', info.get('port'))
            except Exception:
                pass
            self._query_history.append(entry)
            if len(self._query_history) > self._query_history_max:
                # Trim oldest
                overflow = len(self._query_history) - self._query_history_max
                if overflow > 0:
                    del self._query_history[0:overflow]
            # Update last result meta for successes
            try:
                if entry.get('success'):
                    keys = ['query', 'final_query', 'top_n', 'row_count', 'execution_time_ms', 'cached', 'columns', 'sample_rows', 'ts']
                    self._last_result_meta = {k: entry.get(k) for k in keys if k in entry}
            except Exception:
                pass
        except Exception:
            # Never break execution on history issues
            pass

    def get_query_history(self, limit: Optional[int] = None) -> list[dict]:
        """Return newest-first history up to limit (default: all)."""
        data = list(self._query_history)
        data.sort(key=lambda x: x.get('ts', 0), reverse=True)
        if isinstance(limit, int) and limit > 0:
            return data[:limit]
        return data

    def clear_query_history(self) -> int:
        """Clear history and return number of items removed."""
        n = len(self._query_history)
        self._query_history.clear()
        return n

    # ---- Last result summary ----
    def get_last_result_summary(self) -> Dict[str, Any]:
        if not self._last_result_meta:
            return {'success': False, 'error': 'No recent results'}
        out = dict(self._last_result_meta)
        out['success'] = True
        return out

    # ---- Performance baselines ----
    def set_perf_baseline_record(self, name: str, record: Dict[str, Any]) -> Dict[str, Any]:
        if not name:
            return {'success': False, 'error': 'Baseline name required'}
        self._perf_baselines[name] = dict(record or {})
        return {'success': True, 'name': name, 'baseline': self._perf_baselines[name]}

    def get_perf_baseline(self, name: str) -> Dict[str, Any]:
        if name in self._perf_baselines:
            return {'success': True, 'name': name, 'baseline': dict(self._perf_baselines[name])}
        return {'success': False, 'error': f'Baseline "{name}" not found'}

    def list_perf_baselines(self) -> Dict[str, Any]:
        return {'success': True, 'baselines': {k: v for k, v in self._perf_baselines.items()}}

    # ---- Context helpers ----
    def set_context(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Merge provided key/values into context and return current context."""
        try:
            self._context.update(dict(data or {}))
        except Exception:
            pass
        return dict(self._context)

    def get_context(self, keys: Optional[list[str]] = None) -> Dict[str, Any]:
        """Return full context or only selected keys."""
        if keys is None:
            return dict(self._context)
        out: Dict[str, Any] = {}
        for k in keys:
            if k in self._context:
                out[k] = self._context[k]
        return out

    # ---- Safety limits ----
    def set_safety_limits(self, limits: Dict[str, Any]) -> Dict[str, Any]:
        """Update safety limits; unknown keys ignored. Returns current limits."""
        allowed = {'max_rows_per_call'}
        try:
            for k, v in dict(limits or {}).items():
                if k in allowed:
                    self._safety_limits[k] = v
        except Exception:
            pass
        return dict(self._safety_limits)

    def get_safety_limits(self) -> Dict[str, Any]:
        return dict(self._safety_limits)
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get current connection and manager status.
        
        Returns:
            Status dictionary with connection and manager states
        """
        managers_status = {}
        manager_names = [
            'query_executor', 'dax_injector',
            'bpa_analyzer', 'dependency_analyzer', 'bulk_operations',
            'calc_group_manager', 'partition_manager', 'rls_manager',
            'model_exporter', 'performance_optimizer', 'model_validator'
        ]
        
        for name in manager_names:
            managers_status[name] = getattr(self, name) is not None
        
        return {
            'connected': self.is_connected(),
            'managers_initialized': self._managers_initialized,
            'managers': managers_status,
            'connection_info': self._connection_info
        }


# Global connection state instance
connection_state = ConnectionState()