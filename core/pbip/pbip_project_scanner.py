"""
PBIP Project Scanner - Scans repositories for Power BI Project files.

This module identifies .pbip files and their associated folders (semantic models
and reports) within a repository, excluding specified folders.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from core.utilities.json_utils import load_json

logger = logging.getLogger(__name__)


class PbipProjectScanner:
    """Scans PBIP repository and identifies all projects and their components."""

    def __init__(self):
        """Initialize the scanner."""
        self.logger = logger

    def scan_repository(
        self,
        repo_path: str,
        exclude_folders: Optional[List[str]] = None
    ) -> Dict[str, List[Dict[str, str]]]:
        """
        Scan repository for .pbip files and their associated folders.

        Args:
            repo_path: Path to the repository root
            exclude_folders: List of folder names to exclude from scanning

        Returns:
            Dictionary with 'semantic_models' and 'reports' lists containing
            project information

        Raises:
            FileNotFoundError: If repo_path doesn't exist
            PermissionError: If unable to read directory
        """
        if not os.path.exists(repo_path):
            raise FileNotFoundError(f"Repository path not found: {repo_path}")

        if not os.path.isdir(repo_path):
            raise ValueError(f"Path is not a directory: {repo_path}")

        exclude_set: Set[str] = set(exclude_folders or [])

        self.logger.info(f"Scanning repository: {repo_path}")
        if exclude_set:
            self.logger.info(f"Excluding folders: {exclude_set}")

        result = {
            "semantic_models": [],
            "reports": []
        }

        try:
            # Find all .pbip files
            pbip_files = self._find_pbip_files(repo_path, exclude_set)
            self.logger.info(f"Found {len(pbip_files)} .pbip files")

            # Process each .pbip file
            for pbip_file in pbip_files:
                project_info = self._parse_pbip_file(pbip_file, repo_path)
                if project_info:
                    if project_info["type"] == "SemanticModel":
                        result["semantic_models"].append(project_info)
                    elif project_info["type"] == "Report":
                        result["reports"].append(project_info)

                        # Check for adjacent semantic model folder
                        adjacent_sm = self._find_adjacent_semantic_model(pbip_file, repo_path)
                        if adjacent_sm and not any(sm['name'] == adjacent_sm['name'] for sm in result["semantic_models"]):
                            result["semantic_models"].append(adjacent_sm)
                            self.logger.info(f"Found adjacent semantic model: {adjacent_sm['name']}")

            # Link reports to their semantic models
            self._link_reports_to_models(result)

            self.logger.info(
                f"Scan complete: {len(result['semantic_models'])} models, "
                f"{len(result['reports'])} reports"
            )

        except Exception as e:
            self.logger.error(f"Error scanning repository: {e}")
            raise

        return result

    def _find_pbip_files(
        self,
        repo_path: str,
        exclude_set: Set[str]
    ) -> List[str]:
        """
        Recursively find all .pbip files in the repository.

        Args:
            repo_path: Repository root path
            exclude_set: Set of folder names to exclude

        Returns:
            List of absolute paths to .pbip files
        """
        pbip_files = []

        for root, dirs, files in os.walk(repo_path):
            # Remove excluded directories from the search
            dirs[:] = [d for d in dirs if d not in exclude_set]

            for file in files:
                if file.endswith('.pbip'):
                    pbip_files.append(os.path.join(root, file))

        return pbip_files

    def _parse_pbip_file(
        self,
        pbip_file: str,
        repo_path: str
    ) -> Optional[Dict[str, str]]:
        """
        Parse a .pbip file to extract project information.

        Args:
            pbip_file: Path to the .pbip file
            repo_path: Repository root path

        Returns:
            Dictionary with project information or None if parsing fails
        """
        try:
            pbip_data = load_json(pbip_file)

            # Get project name (filename without extension)
            project_name = os.path.splitext(os.path.basename(pbip_file))[0]

            # Determine project type from artifacts
            project_type = None
            artifacts = pbip_data.get("artifacts", [])

            if artifacts and len(artifacts) > 0:
                artifact = artifacts[0]

                # Check what type of artifact this is
                if "report" in artifact:
                    # This could be a report or a semantic model with embedded report
                    report_path = artifact["report"].get("path", "")

                    # If path ends with .SemanticModel, it's a semantic model
                    # If it ends with .Report, it's a report
                    if ".SemanticModel" in report_path or "SemanticModel" in project_name:
                        project_type = "SemanticModel"
                    elif ".Report" in report_path or "Report" in project_name:
                        project_type = "Report"
                    else:
                        # Default to semantic model
                        project_type = "SemanticModel"

                elif "datasetReference" in artifact:
                    # References a dataset, so this is a report
                    project_type = "Report"

            # Fallback: infer from folder names
            if not project_type:
                if "SemanticModel" in project_name:
                    project_type = "SemanticModel"
                elif "Report" in project_name:
                    project_type = "Report"
                else:
                    self.logger.warning(f"Could not determine type for {pbip_file}")
                    return None

            # Find associated folder
            pbip_dir = os.path.dirname(pbip_file)

            project_info = {
                "pbip_file": pbip_file,
                "name": project_name,
                "type": project_type,
                "relative_path": os.path.relpath(pbip_file, repo_path)
            }

            if project_type == "SemanticModel":
                # Look for .SemanticModel folder
                model_folder = os.path.join(pbip_dir, f"{project_name}.SemanticModel")
                if os.path.isdir(model_folder):
                    project_info["model_folder"] = model_folder
                    project_info["has_tmdl"] = self._has_tmdl_format(model_folder)

                    # Set definition_path to the definition subfolder
                    definition_path = os.path.join(model_folder, "definition")
                    if os.path.isdir(definition_path):
                        project_info["definition_path"] = definition_path
                    else:
                        self.logger.warning(
                            f"Definition folder not found in {model_folder}"
                        )
                else:
                    self.logger.warning(
                        f"Semantic model folder not found for {pbip_file}"
                    )
                    return None

            elif project_type == "Report":
                # Look for .Report folder
                report_folder = os.path.join(pbip_dir, f"{project_name}.Report")
                if os.path.isdir(report_folder):
                    project_info["report_folder"] = report_folder
                    # Extract linked model information if available
                    project_info["linked_model"] = self._extract_linked_model(
                        pbip_data
                    )
                else:
                    self.logger.warning(
                        f"Report folder not found for {pbip_file}"
                    )
                    return None

            return project_info

        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in {pbip_file}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error parsing {pbip_file}: {e}")
            return None

    def _has_tmdl_format(self, model_folder: str) -> bool:
        """
        Check if semantic model uses TMDL format.

        Args:
            model_folder: Path to the .SemanticModel folder

        Returns:
            True if TMDL format is detected, False otherwise
        """
        definition_path = os.path.join(model_folder, "definition")
        if not os.path.isdir(definition_path):
            return False

        # Check for key TMDL files
        tmdl_markers = ["model.tmdl", "database.tmdl", "relationships.tmdl"]
        for marker in tmdl_markers:
            if os.path.exists(os.path.join(definition_path, marker)):
                return True

        return False

    def _extract_linked_model(self, pbip_data: Dict) -> Optional[str]:
        """
        Extract linked semantic model name from report .pbip file.

        Args:
            pbip_data: Parsed .pbip JSON data

        Returns:
            Linked model name or None
        """
        try:
            # Look for datasetReference in the pbip data
            if "datasetReference" in pbip_data:
                dataset_ref = pbip_data["datasetReference"]
                if isinstance(dataset_ref, dict):
                    return dataset_ref.get("byPath", {}).get("path")
            return None
        except Exception as e:
            self.logger.warning(f"Could not extract linked model: {e}")
            return None

    def _find_adjacent_semantic_model(
        self,
        pbip_file: str,
        repo_path: str
    ) -> Optional[Dict[str, str]]:
        """
        Find semantic model folder adjacent to a report's .pbip file.

        When a .pbip file references a report, check if there's a .SemanticModel
        folder with the same base name in the same directory.

        Args:
            pbip_file: Path to the .pbip file
            repo_path: Repository root path

        Returns:
            Dictionary with semantic model information or None
        """
        pbip_dir = os.path.dirname(pbip_file)
        base_name = os.path.splitext(os.path.basename(pbip_file))[0]

        # Look for .SemanticModel folder with same base name
        model_folder = os.path.join(pbip_dir, f"{base_name}.SemanticModel")

        if os.path.isdir(model_folder):
            # Found adjacent semantic model folder
            definition_path = os.path.join(model_folder, "definition")

            if os.path.isdir(definition_path):
                project_info = {
                    "pbip_file": pbip_file,  # Use same pbip file
                    "name": base_name,
                    "type": "SemanticModel",
                    "relative_path": os.path.relpath(pbip_file, repo_path),
                    "model_folder": model_folder,
                    "definition_path": definition_path,
                    "has_tmdl": self._has_tmdl_format(model_folder)
                }

                self.logger.info(f"Found adjacent semantic model folder: {model_folder}")
                return project_info
            else:
                self.logger.warning(f"Definition folder not found in {model_folder}")

        return None

    def _link_reports_to_models(self, result: Dict) -> None:
        """
        Link reports to their semantic models by matching names.

        Args:
            result: Dictionary with 'semantic_models' and 'reports'
        """
        # Build model name lookup
        model_names = {
            model["name"]: model for model in result["semantic_models"]
        }

        # Try to link reports
        for report in result["reports"]:
            linked_model_path = report.get("linked_model")
            if linked_model_path:
                # Extract model name from path
                model_name = os.path.splitext(
                    os.path.basename(linked_model_path)
                )[0]
                if model_name in model_names:
                    report["linked_model_name"] = model_name
                    self.logger.debug(
                        f"Linked report {report['name']} to model {model_name}"
                    )
