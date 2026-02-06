"""
Model Comparison Orchestrator

High-level orchestration for comparing two Power BI models using TMDL export,
parsing, diffing, and report generation.
"""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from core.comparison.model_diff_engine import ModelDiffer
from core.comparison.model_diff_report_v2 import ModelDiffReportV2
from core.infrastructure.multi_instance_manager import multi_instance_manager

logger = logging.getLogger(__name__)


class ModelComparisonOrchestrator:
    """
    Orchestrates the complete model comparison workflow.

    Workflow:
    1. Connect to two Power BI Desktop instances
    2. Export both models to TMDL format
    3. Parse TMDL structures
    4. Run comparison engine
    5. Generate HTML report
    6. Cleanup temporary files
    """

    def __init__(self):
        """Initialize orchestrator."""
        self.temp_files: list[str] = []

    def cleanup_temp_files(self) -> int:
        """Clean up temporary files created during comparison.

        Returns:
            Number of files cleaned up
        """
        cleaned = 0
        for file_path in self.temp_files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    cleaned += 1
                    logger.debug(f"Cleaned up temp file: {file_path}")
            except OSError as e:
                logger.warning(f"Failed to clean up temp file {file_path}: {e}")
        self.temp_files.clear()
        return cleaned

    def compare_models(
        self,
        port1: int,
        port2: int,
        output_path: Optional[str] = None,
        include_restricted: bool = False,
        generate_json: bool = False,
        model1_label: Optional[str] = None,
        model2_label: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Compare two Power BI models and generate diff report.

        Args:
            port1: Port of first Power BI Desktop instance (BASE/OLD model)
            port2: Port of second Power BI Desktop instance (NEW model)
            output_path: Optional custom output path for HTML report
            include_restricted: Include restricted information in TMDL export
            generate_json: Also generate JSON export of diff data
            model1_label: Optional label for model 1 (e.g., "Sales_Model_v1.pbix" or "BASE")
            model2_label: Optional label for model 2 (e.g., "Sales_Model_v2.pbix" or "NEW")

        Returns:
            Comparison result dictionary with report paths and summary
        """
        logger.info(f"Starting model comparison: port {port1} vs port {port2}")

        try:
            # Step 1: Connect to both instances
            conn_result1 = multi_instance_manager.connect_to_instance(port1)
            if not conn_result1.get('success'):
                raise RuntimeError(
                    f"Failed to connect to instance 1 (port {port1}): "
                    f"{conn_result1.get('error')}"
                )

            conn_result2 = multi_instance_manager.connect_to_instance(port2)
            if not conn_result2.get('success'):
                raise RuntimeError(
                    f"Failed to connect to instance 2 (port {port2}): "
                    f"{conn_result2.get('error')}"
                )

            logger.info("Successfully connected to both instances")

            # Get database names from connections for auto-labeling
            # Remove port suffix if present in database name
            db_name1 = conn_result1.get('database_name', f'Model (Port {port1})')
            db_name2 = conn_result2.get('database_name', f'Model (Port {port2})')

            # Clean up database names - remove port suffix if present
            db_name1 = re.sub(r'\s*\(Port\s+\d+\)\s*$', '', db_name1)
            db_name2 = re.sub(r'\s*\(Port\s+\d+\)\s*$', '', db_name2)

            # If database names are UUIDs, try to get better names
            # (the ModelDiffer will also try to extract better names from TMDL,
            # but we can set a better default here if available)
            db_name1 = self._clean_model_label(db_name1, port1)
            db_name2 = self._clean_model_label(db_name2, port2)

            # Use database names as default labels if not provided
            if not model1_label:
                model1_label = db_name1
            if not model2_label:
                model2_label = db_name2

            logger.info(f"Model labels: BASE='{model1_label}' vs NEW='{model2_label}'")

            # Step 2: Export both models using model_exporter (JSON TMDL structure)
            logger.info("Exporting models to TMDL structure...")

            # Get model exporters for each instance
            from core.model.model_exporter import ModelExporter

            conn_manager1 = multi_instance_manager.get_instance(port1)
            conn_manager2 = multi_instance_manager.get_instance(port2)

            if not conn_manager1 or not conn_manager2:
                raise RuntimeError("Failed to get connection managers")

            # Create model exporters with connections
            exporter1 = ModelExporter(conn_manager1.get_connection())
            exporter2 = ModelExporter(conn_manager2.get_connection())

            # Export to files (export_to_file=True by default)
            tmdl_export1 = exporter1.export_tmdl_structure(export_to_file=True)
            tmdl_export2 = exporter2.export_tmdl_structure(export_to_file=True)

            if not tmdl_export1.get('success') or not tmdl_export2.get('success'):
                raise RuntimeError(
                    f"TMDL export failed: "
                    f"Model 1: {tmdl_export1.get('error', 'Unknown')}, "
                    f"Model 2: {tmdl_export2.get('error', 'Unknown')}"
                )

            logger.info(
                f"TMDL exports complete: "
                f"{tmdl_export1['statistics']['tables']} tables (model 1), "
                f"{tmdl_export2['statistics']['tables']} tables (model 2)"
            )

            # Store file paths for cleanup
            self.temp_files.append(tmdl_export1['export_file'])
            self.temp_files.append(tmdl_export2['export_file'])

            # Step 3: Load TMDL structures from exported JSON files
            logger.info("Loading TMDL structures from files...")

            with open(tmdl_export1['export_file'], 'r', encoding='utf-8') as f:
                export1_data = json.load(f)
                model1 = export1_data['tmdl']

            with open(tmdl_export2['export_file'], 'r', encoding='utf-8') as f:
                export2_data = json.load(f)
                model2 = export2_data['tmdl']

            # Convert tables dict to list (differ expects list format)
            if isinstance(model1.get('tables'), dict):
                model1['tables'] = list(model1['tables'].values())
            if isinstance(model2.get('tables'), dict):
                model2['tables'] = list(model2['tables'].values())

            logger.info(
                f"Loaded structures: "
                f"{len(model1.get('tables', []))} tables (model 1), "
                f"{len(model2.get('tables', []))} tables (model 2)"
            )

            # Step 4: Run comparison engine
            logger.info("Running comparison engine...")

            differ = ModelDiffer(model1, model2)
            diff_result = differ.compare()

            # Override model names with user-provided labels if given
            # Otherwise, use the model names from the TMDL exports if they're better than UUIDs
            if model1_label:
                # Check if the diff result has a UUID as model name
                if self._is_uuid(diff_result['summary']['model1_name']):
                    # User label is better than UUID
                    diff_result['summary']['model1_name'] = model1_label
                elif not self._is_uuid(model1_label):
                    # User label is not a UUID, prefer it
                    diff_result['summary']['model1_name'] = model1_label

            if model2_label:
                # Check if the diff result has a UUID as model name
                if self._is_uuid(diff_result['summary']['model2_name']):
                    # User label is better than UUID
                    diff_result['summary']['model2_name'] = model2_label
                elif not self._is_uuid(model2_label):
                    # User label is not a UUID, prefer it
                    diff_result['summary']['model2_name'] = model2_label

            total_changes = diff_result['summary']['total_changes']

            logger.info(f"Comparison complete: {total_changes} total changes detected")

            # Step 5: Generate HTML report
            logger.info("Generating HTML report...")

            if output_path is None:
                # Generate default output path in project exports directory
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                project_root = Path(__file__).parent.parent  # Go up from core/ to project root
                output_dir = project_root / "exports" / "model_diffs"
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(output_dir / f"model_diff_{timestamp}.html")

            # Use V2 report generator (modern, clean layout) with full TMDL data for tabs
            report_generator = ModelDiffReportV2(diff_result, tmdl1_data=model1, tmdl2_data=model2)
            html_report_path = report_generator.generate_html(output_path)

            logger.info(f"HTML report generated: {html_report_path}")

            # Step 6: Generate JSON export if requested
            json_report_path = None
            if generate_json:
                json_path = Path(html_report_path).with_suffix('.json')
                self._write_json_export(diff_result, str(json_path))
                json_report_path = str(json_path)
                logger.info(f"JSON export generated: {json_report_path}")

            # Return result
            result = {
                "success": True,
                "summary": {
                    "model1_name": diff_result['summary']['model1_name'],
                    "model2_name": diff_result['summary']['model2_name'],
                    "total_changes": total_changes,
                    "changes_by_category": diff_result['summary']['changes_by_category']
                },
                "reports": {
                    "html": html_report_path,
                    "json": json_report_path
                },
                "tmdl_exports": {
                    "model1": {
                        "path": tmdl_export1['export_file'],
                        "statistics": tmdl_export1['statistics']
                    },
                    "model2": {
                        "path": tmdl_export2['export_file'],
                        "statistics": tmdl_export2['statistics']
                    }
                }
            }

            logger.info("Model comparison completed successfully")

            return result

        except Exception as e:
            logger.error(f"Model comparison failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

        finally:
            # Cleanup: disconnect instances and remove temp files
            try:
                if port1 in multi_instance_manager.instances:
                    multi_instance_manager.disconnect_instance(port1)
                if port2 in multi_instance_manager.instances:
                    multi_instance_manager.disconnect_instance(port2)
            except Exception as e:
                logger.warning(f"Error during instance cleanup: {e}")

            cleaned = self.cleanup_temp_files()
            if cleaned:
                logger.debug(f"Cleaned up {cleaned} temporary files")

    def _is_uuid(self, value: str) -> bool:
        """Check if a string looks like a UUID."""
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        return bool(re.match(uuid_pattern, value, re.IGNORECASE))

    def _clean_model_label(self, label: str, port: int) -> str:
        """
        Clean up model label - if it's a UUID, replace with a more readable default.

        Args:
            label: The raw label (could be UUID, .pbix filename, etc.)
            port: Port number for fallback naming

        Returns:
            Cleaned label
        """
        # Check if label is a UUID
        if self._is_uuid(label):
            return f'Model (Port {port})'

        return label

    def _write_json_export(self, diff_result: Dict[str, Any], json_path: str) -> None:
        """Write diff result to JSON file."""
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(diff_result, f, indent=2, ensure_ascii=False)

        logger.debug(f"JSON export written: {json_path}")

    def compare_with_detected_instances(
        self,
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Detect and compare two available Power BI Desktop instances.

        Automatically detects running instances and compares the first two found.

        Args:
            output_path: Optional custom output path for HTML report

        Returns:
            Comparison result dictionary
        """
        try:
            # Detect instances
            from core.infrastructure.connection_manager import PowerBIDesktopDetector

            detector = PowerBIDesktopDetector()
            instances = detector.find_powerbi_instances()

            if len(instances) < 2:
                return {
                    "success": False,
                    "error": f"Need at least 2 Power BI Desktop instances running. Found: {len(instances)}"
                }

            # Get first two instances
            instance1 = instances[0]
            instance2 = instances[1]

            port1 = instance1['port']
            port2 = instance2['port']

            logger.info(f"Auto-detected instances: ports {port1} and {port2}")

            # Perform comparison
            return self.compare_models(port1, port2, output_path)

        except Exception as e:
            logger.error(f"Auto-detection comparison failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }


# Convenience function
def compare_pbi_models(
    port1: int,
    port2: int,
    output_path: Optional[str] = None,
    include_restricted: bool = False,
    generate_json: bool = False,
    model1_label: Optional[str] = None,
    model2_label: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to compare two Power BI models.

    Args:
        port1: Port of first Power BI Desktop instance (BASE/OLD)
        port2: Port of second Power BI Desktop instance (NEW)
        output_path: Optional custom output path for HTML report
        include_restricted: Include restricted information
        generate_json: Also generate JSON export
        model1_label: Label for base model (e.g., "Sales_v1.pbix" or "BASE")
        model2_label: Label for new model (e.g., "Sales_v2.pbix" or "NEW")

    Returns:
        Comparison result dictionary
    """
    orchestrator = ModelComparisonOrchestrator()
    return orchestrator.compare_models(port1, port2, output_path, include_restricted, generate_json, model1_label, model2_label)
