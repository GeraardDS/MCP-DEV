"""
Connection Manager for PBIXRay MCP Server

Manages Power BI Desktop connections, instance detection, and connection state.
"""

import logging
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to load ADOMD.NET
ADOMD_AVAILABLE = False
AdomdConnection = None

try:
    from core.infrastructure.dll_paths import load_adomd_assembly
    if load_adomd_assembly():
        from Microsoft.AnalysisServices.AdomdClient import AdomdConnection
        ADOMD_AVAILABLE = True
        logger.info("ADOMD.NET available for connections")
except Exception as e:
    logger.warning(f"ADOMD.NET not available: {e}")


class PowerBIDesktopDetector:
    """
    Detects running Power BI Desktop instances using optimized netstat-based approach.

    Based on fabric-toolbox ultra-fast detection methods.
    """

    @staticmethod
    def find_powerbi_instances() -> List[Dict[str, Any]]:
        """
        Find running Power BI Desktop instances.

        Uses netstat to detect listening ports and tasklist to verify msmdsrv.exe processes.

        Returns:
            List of instance dictionaries with port, PID, and connection info
        """
        instances = []

        try:
            # Run netstat to get listening ports
            result = subprocess.run(
                ['netstat', '-ano'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                logger.error("netstat command failed")
                return instances

            # Parse netstat output for listening ports
            port_pid_map = {}
            for line in result.stdout.splitlines():
                if 'LISTENING' in line and ('[::]' in line or '127.0.0.1' in line):
                    parts = line.split()
                    if len(parts) >= 5:
                        try:
                            address = parts[1]
                            # Extract port number
                            if ']:' in address:  # IPv6 format
                                port = int(address.split(']:')[1])
                            else:  # IPv4 format
                                port = int(address.split(':')[-1])

                            pid = int(parts[4])
                            port_pid_map[port] = pid
                        except (ValueError, IndexError):
                            continue

            # Run tasklist to find msmdsrv.exe processes
            tasklist_result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq msmdsrv.exe', '/FO', 'CSV', '/NH'],
                capture_output=True,
                text=True,
                timeout=10
            )

            msmdsrv_pids = set()
            if tasklist_result.returncode == 0:
                for line in tasklist_result.stdout.splitlines():
                    if 'msmdsrv.exe' in line:
                        parts = line.split(',')
                        if len(parts) >= 2:
                            try:
                                pid = int(parts[1].strip('"'))
                                msmdsrv_pids.add(pid)
                            except ValueError:
                                pass

            # Match ports to msmdsrv PIDs and get database names
            for port, pid in port_pid_map.items():
                if pid in msmdsrv_pids:
                    # Try to get the actual .pbix filename from PBIDesktop.exe command line
                    db_name = f"Port {port}"  # Default fallback
                    file_full_path = None  # Full path to .pbix or .pbip file
                    pbip_folder_path = None  # For PBIP projects, the folder containing the project
                    file_type = None  # 'pbix' or 'pbip'
                    try:
                        import psutil
                        import os
                        import re

                        # Get the msmdsrv.exe process
                        msmdsrv_proc = psutil.Process(pid)

                        # Get parent process (should be PBIDesktop.exe)
                        parent = msmdsrv_proc.parent()
                        if parent and 'PBIDesktop' in parent.name():
                            # Get command line arguments - should contain the .pbix file path
                            cmdline = parent.cmdline()

                            # Look for .pbix or .pbip file in command line arguments
                            for arg in cmdline:
                                if '.pbix' in arg.lower() or '.pbip' in arg.lower():
                                    # Store the full path
                                    file_full_path = arg
                                    db_name = os.path.basename(arg)

                                    # Determine file type and derive PBIP folder
                                    if '.pbip' in arg.lower():
                                        file_type = 'pbip'
                                        # Resolve to matching .Report folder (not just parent dir)
                                        from core.utilities.pbip_utils import resolve_report_folder_from_pbip
                                        resolved = resolve_report_folder_from_pbip(arg)
                                        if resolved:
                                            pbip_folder_path = resolved
                                        else:
                                            pbip_folder_path = os.path.dirname(arg)
                                        logger.info(f"Found PBIP project for port {port}: {db_name}, folder: {pbip_folder_path}")
                                    else:
                                        file_type = 'pbix'
                                        logger.info(f"Found PBIX file for port {port}: {db_name}")
                                    break

                            # If still not found, search in full command line string
                            if db_name == f"Port {port}":
                                cmdline_str = ' '.join(cmdline)
                                # Look for both .pbix and .pbip files - capture full path
                                match = re.search(r'([^\s"]+\.pbi[xp])', cmdline_str, re.IGNORECASE)
                                if match:
                                    file_full_path = match.group(1)
                                    db_name = os.path.basename(file_full_path)
                                    if '.pbip' in file_full_path.lower():
                                        file_type = 'pbip'
                                        from core.utilities.pbip_utils import resolve_report_folder_from_pbip
                                        resolved = resolve_report_folder_from_pbip(file_full_path)
                                        pbip_folder_path = resolved if resolved else os.path.dirname(file_full_path)
                                    else:
                                        file_type = 'pbix'
                                    logger.info(f"Found Power BI file for port {port}: {db_name} (regex)")
                                else:
                                    logger.warning(f"No .pbix or .pbip found for port {port}. Cmdline: {cmdline_str[:200]}")
                    except Exception as e:
                        logger.error(f"Error getting filename for port {port}: {e}", exc_info=True)

                    instances.append({
                        'port': port,
                        'pid': pid,
                        'database': db_name if db_name else f'Port {port}',
                        'workspace': f'msmdsrv_pid_{pid}',
                        'path': f'localhost:{port}',
                        'connection_string': f'Data Source=localhost:{port}',
                        'display_name': db_name if db_name else f'Power BI Desktop (Port {port})',
                        'file_full_path': file_full_path,  # Full path to .pbix/.pbip file
                        'pbip_folder_path': pbip_folder_path,  # Folder for PBIP projects (None for PBIX)
                        'file_type': file_type  # 'pbix', 'pbip', or None
                    })

            # Sort by port (highest first - usually most recent)
            instances.sort(key=lambda x: x['port'], reverse=True)

            logger.info(f"Detected {len(instances)} Power BI Desktop instance(s)")

        except subprocess.TimeoutExpired:
            logger.error("Detection timed out")
        except Exception as e:
            logger.error(f"Detection error: {e}")

        return instances


class ConnectionManager:
    """
    Manages active Power BI Desktop connections.

    Handles:
    - Connection establishment
    - Connection state tracking
    - Connection reuse
    - Connection health checks
    """

    def __init__(self):
        """Initialize connection manager."""
        self.active_connection = None
        self.active_instance = None
        self.connection_string = None

    def detect_instances(self) -> List[Dict[str, Any]]:
        """
        Detect available Power BI Desktop instances.

        Returns:
            List of detected instances
        """
        detector = PowerBIDesktopDetector()
        return detector.find_powerbi_instances()

    def connect(self, model_index: int = 0) -> Dict[str, Any]:
        """
        Connect to a Power BI Desktop instance.

        Args:
            model_index: Index of instance to connect to (0 = most recent)

        Returns:
            Connection result dictionary
        """
        if not ADOMD_AVAILABLE:
            return {
                'success': False,
                'error': 'ADOMD.NET not available',
                'error_type': 'adomd_unavailable'
            }

        try:
            # Detect instances
            instances = self.detect_instances()

            if not instances:
                return {
                    'success': False,
                    'error': 'No Power BI Desktop instances detected',
                    'error_type': 'no_instances',
                    'suggestions': [
                        'Ensure Power BI Desktop is running with .pbix file open',
                        'Verify msmdsrv.exe process is running'
                    ]
                }

            if model_index >= len(instances):
                return {
                    'success': False,
                    'error': f'Invalid model index {model_index}, only {len(instances)} instance(s) found',
                    'error_type': 'invalid_index',
                    'available_instances': len(instances)
                }

            # Get selected instance
            instance = instances[model_index]
            conn_str = instance['connection_string']

            # Close existing connection if any
            if self.active_connection:
                try:
                    self.active_connection.Close()
                except Exception:
                    pass

            # Create new connection
            self.active_connection = AdomdConnection(conn_str)
            self.active_connection.Open()
            self.active_instance = instance
            self.connection_string = conn_str

            logger.info(f"Connected to Power BI Desktop on port {instance['port']}")

            return {
                'success': True,
                'instance': instance,
                'connection_string': conn_str,
                'model_index': model_index,
                'total_instances': len(instances),
                'message': f"Successfully connected to Power BI Desktop on port {instance['port']}"
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Connection error: {error_msg}")

            return {
                'success': False,
                'error': error_msg,
                'error_type': 'connection_error',
                'suggestions': [
                    'Verify Power BI Desktop is running with model loaded',
                    'Check firewall settings',
                    'Try detecting instances again'
                ]
            }

    def connect_to_port(self, port: int) -> Dict[str, Any]:
        """
        Connect directly to a Power BI Desktop instance on a specific port.

        Args:
            port: Port number of the Power BI Desktop instance

        Returns:
            Connection result dictionary
        """
        if not ADOMD_AVAILABLE:
            return {
                'success': False,
                'error': 'ADOMD.NET not available'
            }

        try:
            # Build connection string
            conn_str = f'Data Source=localhost:{port}'

            # Close existing connection if any
            if self.active_connection:
                try:
                    self.active_connection.Close()
                except Exception:
                    pass

            # Create and open connection
            self.active_connection = AdomdConnection(conn_str)
            self.active_connection.Open()

            # Get database name - try to get actual .pbix filename
            db_name = None
            try:
                # Simpler approach: find PBIDesktop.exe process with this port
                import psutil
                import os

                # First, find which msmdsrv.exe is listening on this port
                msmdsrv_pid = None
                for proc in psutil.process_iter(['pid', 'name']):
                    try:
                        if proc.info['name'] == 'msmdsrv.exe':
                            # Get connections separately (not available in process_iter attrs)
                            process = psutil.Process(proc.info['pid'])
                            connections = process.net_connections()
                            for conn in connections:
                                if hasattr(conn, 'laddr') and conn.laddr.port == port:
                                    msmdsrv_pid = proc.info['pid']
                                    logger.debug(f"Found msmdsrv.exe (PID {msmdsrv_pid}) on port {port}")
                                    break
                            if msmdsrv_pid:
                                break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                # Now find the PBIDesktop.exe process that spawned this msmdsrv
                if msmdsrv_pid:
                    msmdsrv_proc = psutil.Process(msmdsrv_pid)
                    parent = msmdsrv_proc.parent()

                    # The parent might be PBIDesktop or might be another intermediate process
                    # Walk up the process tree to find PBIDesktop
                    while parent:
                        try:
                            parent_name = parent.name()
                            logger.debug(f"Checking parent process: {parent_name}")

                            if 'PBIDesktop' in parent_name:
                                # Found PBIDesktop.exe, get its command line
                                cmdline = parent.cmdline()
                                logger.debug(f"PBIDesktop cmdline: {cmdline}")

                                for arg in cmdline:
                                    if '.pbix' in arg.lower():
                                        db_name = os.path.basename(arg)
                                        logger.info(f"Found .pbix filename from cmdline: {db_name}")
                                        break

                                # If we didn't find it in cmdline, try to get it from window title
                                if not db_name:
                                    try:
                                        import win32gui
                                        import win32process

                                        def enum_windows_callback(hwnd, results):
                                            if win32gui.IsWindowVisible(hwnd):
                                                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                                                if found_pid == parent.pid:
                                                    title = win32gui.GetWindowText(hwnd)
                                                    if title and '.pbix' in title.lower():
                                                        results.append(title)

                                        windows = []
                                        win32gui.EnumWindows(enum_windows_callback, windows)

                                        if windows:
                                            # Extract filename from title (usually "filename.pbix - Power BI Desktop")
                                            title = windows[0]
                                            if ' - ' in title:
                                                db_name = title.split(' - ')[0].strip()
                                            else:
                                                db_name = title.strip()

                                            # Ensure it ends with .pbix
                                            if not db_name.endswith('.pbix'):
                                                db_name += '.pbix'

                                            logger.info(f"Found .pbix filename from window title: {db_name}")

                                    except ImportError:
                                        logger.debug("pywin32 not available, cannot get window title")
                                    except Exception as e:
                                        logger.debug(f"Could not get window title: {e}")

                                break

                            # Move up to next parent
                            parent = parent.parent()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            break

            except Exception as e:
                logger.debug(f"Could not get .pbix filename from process tree: {e}")

            # Fallback to CATALOG_NAME if we couldn't get the filename
            if not db_name:
                cmd = self.active_connection.CreateCommand()
                cmd.CommandText = "SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS"
                reader = cmd.ExecuteReader()
                try:
                    if reader.Read():
                        db_name = str(reader.GetValue(0))
                finally:
                    try:
                        reader.Close()
                    except Exception:
                        pass

            # Store instance info
            self.active_instance = {
                'port': port,
                'database': db_name,
                'connection_string': conn_str,
                'display_name': f'Power BI Desktop (Port {port})'
            }
            self.connection_string = conn_str

            logger.info(f"Connected to Power BI Desktop on port {port}")

            return {
                'success': True,
                'port': port,
                'database_name': db_name,
                'connection_string': conn_str,
                'instance': self.active_instance,
                'message': f'Successfully connected to port {port}'
            }

        except Exception as e:
            logger.error(f"Failed to connect to port {port}: {e}")
            return {
                'success': False,
                'port': port,
                'error': str(e),
                'error_type': 'connection_failed'
            }

    def test_connection(self, port: Optional[int] = None) -> Dict[str, Any]:
        """
        Test connection to a specific port or current connection.

        Args:
            port: Optional port to test, uses current connection if None

        Returns:
            Test result dictionary
        """
        if not ADOMD_AVAILABLE:
            return {
                'success': False,
                'error': 'ADOMD.NET not available'
            }

        try:
            if port:
                # Test specific port
                conn_str = f'Data Source=localhost:{port}'
                test_conn = AdomdConnection(conn_str)
                test_conn.Open()

                # Get server info
                cmd = test_conn.CreateCommand()
                cmd.CommandText = "SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS"
                reader = cmd.ExecuteReader()
                try:
                    db_name = None
                    if reader.Read():
                        db_name = str(reader.GetValue(0))
                finally:
                    try:
                        reader.Close()
                    except Exception:
                        pass
                test_conn.Close()

                return {
                    'success': True,
                    'port': port,
                    'database_name': db_name,
                    'connection_string': conn_str,
                    'message': f'Successfully connected to port {port}'
                }

            elif self.active_connection:
                # Test current connection
                if self.active_connection.State.ToString() != 'Open':
                    return {
                        'success': False,
                        'error': 'Connection is not open',
                        'connection_state': self.active_connection.State.ToString()
                    }

                # Test with simple query
                cmd = self.active_connection.CreateCommand()
                cmd.CommandText = "EVALUATE { 1 }"
                reader = cmd.ExecuteReader()
                try:
                    has_data = reader.Read()
                finally:
                    try:
                        reader.Close()
                    except Exception:
                        pass

                return {
                    'success': True,
                    'connection_state': 'Open',
                    'instance': self.active_instance,
                    'message': 'Connection is healthy'
                }

            else:
                return {
                    'success': False,
                    'error': 'No active connection to test'
                }

        except Exception as e:
            logger.error(f"Connection test error: {e}")
            return {
                'success': False,
                'error': str(e),
                'error_type': 'connection_test_error'
            }

    def get_connection(self):
        """
        Get active connection.

        Returns:
            Active ADOMD connection or None
        """
        return self.active_connection

    def get_instance_info(self) -> Optional[Dict[str, Any]]:
        """
        Get current instance information.

        Returns:
            Instance info dictionary or None
        """
        return self.active_instance

    def is_connected(self) -> bool:
        """
        Check if there's an active connection.

        Returns:
            True if connected, False otherwise
        """
        if not self.active_connection:
            return False

        try:
            return self.active_connection.State.ToString() == 'Open'
        except Exception:
            return False

    def disconnect(self):
        """Disconnect from current instance."""
        if self.active_connection:
            try:
                self.active_connection.Close()
                logger.info("Disconnected from Power BI Desktop")
            except Exception:
                pass
            finally:
                self.active_connection = None
                self.active_instance = None
                self.connection_string = None

    def reconnect(self, max_retries: int = 3, retry_delay: float = 0.5) -> Dict[str, Any]:
        """
        Attempt to reconnect to the last connected instance.
        Uses exponential backoff for retries.

        Args:
            max_retries: Maximum number of reconnection attempts (default 3)
            retry_delay: Initial delay between retries in seconds (default 0.5)

        Returns:
            Connection result dictionary
        """
        import time

        if not self.connection_string:
            return {
                'success': False,
                'error': 'No previous connection to reconnect to',
                'error_type': 'no_previous_connection'
            }

        # Store instance info for potential restoration
        saved_instance = self.active_instance

        for attempt in range(max_retries):
            try:
                # Close existing connection if any
                if self.active_connection:
                    try:
                        self.active_connection.Close()
                    except Exception:
                        pass
                    self.active_connection = None

                # Create new connection
                self.active_connection = AdomdConnection(self.connection_string)
                self.active_connection.Open()

                # Verify connection is healthy
                if self.active_connection.State.ToString() == 'Open':
                    logger.info(f"Reconnected successfully on attempt {attempt + 1}")
                    return {
                        'success': True,
                        'reconnected': True,
                        'attempt': attempt + 1,
                        'instance': self.active_instance,
                        'message': f'Successfully reconnected on attempt {attempt + 1}'
                    }

            except Exception as e:
                logger.warning(f"Reconnection attempt {attempt + 1} failed: {e}")

                # Exponential backoff
                if attempt < max_retries - 1:
                    sleep_time = retry_delay * (2 ** attempt)
                    time.sleep(sleep_time)

        # All retries failed
        logger.error(f"Failed to reconnect after {max_retries} attempts")
        return {
            'success': False,
            'error': f'Failed to reconnect after {max_retries} attempts',
            'error_type': 'reconnection_failed',
            'attempts': max_retries
        }

    def ensure_connected(self, max_retries: int = 3) -> Dict[str, Any]:
        """
        Ensure connection is open, attempting reconnection if needed.

        Args:
            max_retries: Maximum reconnection attempts if connection is lost

        Returns:
            Dict with 'connected' (bool) and optional error info
        """
        # Check if currently connected
        if self.is_connected():
            return {'connected': True, 'reconnected': False}

        # Not connected - try to reconnect if we have a previous connection
        if self.connection_string:
            logger.info("Connection lost, attempting to reconnect...")
            result = self.reconnect(max_retries=max_retries)
            if result.get('success'):
                return {'connected': True, 'reconnected': True}
            else:
                return {
                    'connected': False,
                    'reconnected': False,
                    'error': result.get('error'),
                    'error_type': result.get('error_type')
                }

        return {
            'connected': False,
            'reconnected': False,
            'error': 'No active or previous connection',
            'error_type': 'no_connection'
        }

    def connect_by_stable_id(self, port: int, database_id: str) -> Dict[str, Any]:
        """
        Connect to a Power BI instance using stable ID (port:databaseId)

        Args:
            port: Port number
            database_id: Database ID

        Returns:
            Connection result dictionary
        """
        if not ADOMD_AVAILABLE:
            return {
                'success': False,
                'error': 'ADOMD.NET not available',
                'error_type': 'adomd_unavailable'
            }

        try:
            # Close existing connection if any
            if self.active_connection:
                try:
                    self.active_connection.Close()
                except Exception:
                    pass

            # Create connection string with database
            conn_str = f"Data Source=localhost:{port};Initial Catalog={database_id}"

            # Create new connection
            self.active_connection = AdomdConnection(conn_str)
            self.active_connection.Open()

            self.active_instance = {
                'port': port,
                'database': database_id,
                'stable_id': f"{port}:{database_id}",
                'connection_string': conn_str,
                'process_name': 'msmdsrv.exe',
                'pid': 0
            }
            self.connection_string = conn_str

            logger.info(f"Connected to model at {port}:{database_id}")

            return {
                'success': True,
                'stable_id': f"{port}:{database_id}",
                'port': port,
                'database': database_id,
                'connection_string': conn_str,
                'message': f'Successfully connected to model at {port}:{database_id}'
            }

        except Exception as e:
            logger.error(f"Failed to connect by stable ID: {e}")
            return {
                'success': False,
                'error': str(e),
                'error_type': 'connection_error'
            }
