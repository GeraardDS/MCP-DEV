"""
Multi-Instance Connection Manager

Manages multiple simultaneous connections to Power BI Desktop instances
for model comparison and cross-instance analysis.
"""

import logging
import threading
from typing import Dict, Any, Optional, List
from core.infrastructure.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


class MultiInstanceManager:
    """
    Manages multiple connections to Power BI Desktop instances. Thread-safe.

    Enables simultaneous connections to different Power BI Desktop instances
    for model comparison, cross-instance queries, and parallel analysis.
    """

    MAX_INSTANCES = 10  # Prevent unbounded instance accumulation

    def __init__(self):
        """Initialize multi-instance manager."""
        self.instances: Dict[int, ConnectionManager] = {}
        self.active_ports: List[int] = []
        self._lock = threading.RLock()

    def detect_instances(self) -> List[Dict[str, Any]]:
        """
        Detect available Power BI Desktop instances.

        Returns:
            List of detected instances with port, database_name, etc.
        """
        try:
            # Create temporary ConnectionManager to detect instances
            temp_conn = ConnectionManager()
            instances = temp_conn.detect_instances()
            logger.info(f"Detected {len(instances)} Power BI Desktop instance(s)")
            return instances
        except Exception as e:
            logger.error(f"Error detecting Power BI instances: {e}", exc_info=True)
            return []

    def connect_to_instance(self, port: int) -> Dict[str, Any]:
        """
        Connect to a specific Power BI Desktop instance.

        Args:
            port: Port number of the Power BI Desktop instance (1-65535)

        Returns:
            Connection result dictionary
        """
        # Validate port range
        if not isinstance(port, int) or port < 1 or port > 65535:
            return {
                "success": False,
                "port": port,
                "error": f"Invalid port number: {port}. Must be between 1 and 65535."
            }

        with self._lock:
            if port in self.instances:
                logger.info(f"Already connected to instance on port {port}")
                return {
                    "success": True,
                    "port": port,
                    "status": "already_connected"
                }

            if len(self.instances) >= self.MAX_INSTANCES:
                return {
                    "success": False,
                    "port": port,
                    "error": f"Maximum number of instances ({self.MAX_INSTANCES}) reached. Disconnect an instance first."
                }

            try:
                logger.info(f"Connecting to Power BI Desktop instance on port {port}")

                # Create new connection manager
                conn_manager = ConnectionManager()

                # Connect to specific port
                result = conn_manager.connect_to_port(port)

                if not result.get('success'):
                    return {
                        "success": False,
                        "port": port,
                        "error": result.get('error', 'Connection failed')
                    }

                # Store connection
                self.instances[port] = conn_manager
                if port not in self.active_ports:
                    self.active_ports.append(port)

                logger.info(f"Successfully connected to instance on port {port}")

                return {
                    "success": True,
                    "port": port,
                    "status": "connected",
                    "database_name": result.get('database_name'),
                    "instance_info": result.get('instance')
                }

            except Exception as e:
                logger.error(f"Failed to connect to port {port}: {e}", exc_info=True)
                return {
                    "success": False,
                    "port": port,
                    "error": str(e)
                }

    def disconnect_instance(self, port: int) -> Dict[str, Any]:
        """
        Disconnect from a specific instance.

        Args:
            port: Port number to disconnect from

        Returns:
            Disconnection result
        """
        with self._lock:
            if port not in self.instances:
                return {
                    "success": False,
                    "port": port,
                    "error": "Instance not connected"
                }

            try:
                logger.info(f"Disconnecting from instance on port {port}")

                conn_manager = self.instances[port]
                conn_manager.disconnect()

                del self.instances[port]
                if port in self.active_ports:
                    self.active_ports.remove(port)

                return {
                    "success": True,
                    "port": port,
                    "status": "disconnected"
                }

            except Exception as e:
                logger.error(f"Error disconnecting from port {port}: {e}")
                # Still remove from tracking even if disconnect throws
                self.instances.pop(port, None)
                if port in self.active_ports:
                    self.active_ports.remove(port)
                return {
                    "success": False,
                    "port": port,
                    "error": str(e)
                }

    def get_instance(self, port: int) -> Optional[ConnectionManager]:
        """
        Get connection manager for a specific port.

        Args:
            port: Port number

        Returns:
            ConnectionManager instance or None if not connected
        """
        with self._lock:
            return self.instances.get(port)

    def get_connection_string(self, port: int) -> Optional[str]:
        """
        Get connection string for a specific port.

        Args:
            port: Port number

        Returns:
            Connection string or None if not connected
        """
        instance = self.get_instance(port)
        if instance:
            return instance.connection_string
        return None

    def get_all_instances(self) -> List[Dict[str, Any]]:
        """
        Get information about all connected instances.

        Returns:
            List of instance information dictionaries
        """
        with self._lock:
            instances_snapshot = list(self.instances.items())

        instances_info = []
        for port, conn_manager in instances_snapshot:
            try:
                info = conn_manager.get_instance_info()
                if info:
                    info['port'] = port
                    info['connected'] = conn_manager.is_connected()
                    instances_info.append(info)
            except Exception as e:
                logger.warning(f"Error getting info for port {port}: {e}")

        return instances_info

    def disconnect_all(self) -> Dict[str, Any]:
        """
        Disconnect from all instances.

        Returns:
            Disconnection summary
        """
        ports_to_disconnect = list(self.active_ports)
        disconnected = []
        failed = []

        for port in ports_to_disconnect:
            result = self.disconnect_instance(port)
            if result.get('success'):
                disconnected.append(port)
            else:
                failed.append({
                    "port": port,
                    "error": result.get('error')
                })

        return {
            "success": len(failed) == 0,
            "disconnected_count": len(disconnected),
            "failed_count": len(failed),
            "disconnected_ports": disconnected,
            "failed_ports": failed
        }

    def get_status(self) -> Dict[str, Any]:
        """
        Get status of all connections.

        Returns:
            Status dictionary
        """
        with self._lock:
            return {
                "total_instances": len(self.instances),
                "active_ports": list(self.active_ports),
                "instances": self.get_all_instances()
            }

    def close(self) -> None:
        """Explicit cleanup - preferred over __del__."""
        try:
            self.disconnect_all()
        except Exception as e:
            logger.warning(f"Error during cleanup: {e}")

    def __del__(self):
        """Cleanup on deletion - best effort only."""
        try:
            self.close()
        except Exception:
            pass


# Global multi-instance manager
multi_instance_manager = MultiInstanceManager()
