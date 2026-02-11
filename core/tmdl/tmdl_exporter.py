"""
TMDL Exporter Module

Exports Power BI models to TMDL (Tabular Model Definition Language) format
using TOM (Tabular Object Model).
"""

import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Try to load TOM assemblies
TOM_AVAILABLE = False
Server = None
SaveOptions = None

try:
    from core.infrastructure.dll_paths import load_amo_assemblies
    load_amo_assemblies()
    from Microsoft.AnalysisServices.Tabular import Server, SaveOptions
    TOM_AVAILABLE = True
    logger.info("TOM (Tabular Object Model) available for TMDL export")
except Exception as e:
    logger.warning(f"TOM not available for TMDL export: {e}")


class TmdlExporter:
    """
    Handles exporting Power BI models to TMDL format.

    TMDL (Tabular Model Definition Language) is a human-readable, text-based
    format for tabular models that enables version control and diff analysis.
    """

    def __init__(self):
        """Initialize TMDL exporter."""
        if not TOM_AVAILABLE:
            raise RuntimeError(
                "TOM (Tabular Object Model) not available. "
                "Ensure Microsoft.AnalysisServices.Tabular.dll is present."
            )
        self.temp_dirs: list[str] = []

    def export_to_tmdl(
        self,
        connection_string: str,
        output_path: Optional[str] = None,
        include_restricted: bool = False
    ) -> Dict[str, Any]:
        """
        Export a Power BI model to TMDL format.

        Args:
            connection_string: ADOMD connection string to Power BI Desktop instance
            output_path: Optional path for TMDL output. If None, uses temp directory
            include_restricted: Include restricted information in export (default: False)

        Returns:
            Dictionary with export results:
            {
                "success": bool,
                "tmdl_path": str,
                "model_name": str,
                "compatibility_level": int,
                "file_count": int,
                "export_timestamp": str
            }

        Raises:
            RuntimeError: If export fails
        """
        server = None
        temp_dir = None

        try:
            logger.info(f"Starting TMDL export from connection: {connection_string}")

            # Create output directory
            if output_path is None:
                temp_dir = tempfile.mkdtemp(prefix="tmdl_export_")
                self.temp_dirs.append(temp_dir)
                output_path = temp_dir
                logger.debug(f"Using temporary directory: {temp_dir}")
            else:
                output_path = os.path.abspath(output_path)
                os.makedirs(output_path, exist_ok=True)
                logger.debug(f"Using specified output directory: {output_path}")

            # Connect to server
            server = Server()
            server.Connect(connection_string)
            logger.info("Connected to Analysis Services instance")

            # Get database (first one, which is the open .pbix)
            if server.Databases.Count == 0:
                raise RuntimeError(
                    "No database found on server. Ensure Power BI Desktop has a file loaded."
                )

            database = server.Databases[0]
            model_name = database.Name
            compatibility_level = database.CompatibilityLevel

            logger.info(f"Exporting model: {model_name} (compatibility: {compatibility_level})")

            # Configure save options
            save_options = SaveOptions()
            save_options.IncludeRestrictedInformation = include_restricted

            # Export to TMDL folder structure
            # Creates definition/ folder with tables/, roles/, perspectives/, etc.
            tmdl_output_path = os.path.join(output_path, "definition")

            logger.info(f"Saving TMDL to: {tmdl_output_path}")
            database.Model.SaveToFolder(tmdl_output_path, save_options)

            # Count exported files
            file_count = self._count_tmdl_files(tmdl_output_path)

            logger.info(f"TMDL export completed successfully: {file_count} files")

            return {
                "success": True,
                "tmdl_path": output_path,
                "definition_path": tmdl_output_path,
                "model_name": model_name,
                "compatibility_level": compatibility_level,
                "file_count": file_count,
                "export_timestamp": datetime.utcnow().isoformat() + "Z"
            }

        except Exception as e:
            logger.error(f"TMDL export failed: {e}", exc_info=True)
            raise RuntimeError(f"Failed to export TMDL: {str(e)}") from e

        finally:
            if server is not None:
                try:
                    server.Disconnect()
                    logger.debug("Disconnected from server")
                except Exception as e:
                    logger.warning(f"Error disconnecting from server: {e}")

    def _count_tmdl_files(self, tmdl_path: str) -> int:
        """Count .tmdl files in the exported structure."""
        count = 0
        for root, dirs, files in os.walk(tmdl_path):
            count += sum(1 for f in files if f.endswith('.tmdl'))
        return count

    def cleanup_temp_dirs(self) -> None:
        """Clean up temporary directories created during exports."""
        for temp_dir in self.temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    logger.debug(f"Cleaned up temp directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory {temp_dir}: {e}")
        self.temp_dirs.clear()

    def __del__(self):
        """Cleanup on deletion."""
        self.cleanup_temp_dirs()


def export_model_to_tmdl(
    connection_string: str,
    output_path: Optional[str] = None,
    include_restricted: bool = False
) -> Dict[str, Any]:
    """
    Convenience function to export a model to TMDL format.

    Args:
        connection_string: ADOMD connection string
        output_path: Optional output path (uses temp dir if None)
        include_restricted: Include restricted information

    Returns:
        Export result dictionary
    """
    exporter = TmdlExporter()
    return exporter.export_to_tmdl(connection_string, output_path, include_restricted)
