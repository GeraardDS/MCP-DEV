"""
PBIP Reader - Read and parse PBIP (Power BI Project) folder structure

This module provides functionality to read TMDL files from a PBIP folder
created by Power BI Desktop when saving as PBIP format.
"""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from core.utilities.json_utils import load_json

logger = logging.getLogger(__name__)


class PBIPReader:
    """
    Read and parse PBIP (Power BI Project) folder structure

    PBIP Format:
    {ModelName}.SemanticModel/
    ├── definition/
    │   ├── database.tmdl
    │   ├── model.tmdl
    │   ├── expressions.tmdl
    │   ├── relationships.tmdl
    │   ├── tables/
    │   │   ├── Table1.tmdl
    │   │   └── Table2.tmdl
    │   ├── roles/
    │   │   └── Role1.tmdl
    │   └── cultures/
    │       └── en-US.tmdl
    ├── .pbi/
    └── item.metadata.json
    """

    def __init__(self, pbip_folder_path: str):
        """
        Initialize PBIP reader

        Args:
            pbip_folder_path: Path to .SemanticModel folder
        """
        self.pbip_path = Path(pbip_folder_path)
        self.definition_path = self.pbip_path / "definition"

        # Validate PBIP structure
        if not self.pbip_path.exists():
            raise ValueError(f"PBIP folder not found: {pbip_folder_path}")

        if not self.definition_path.exists():
            raise ValueError(f"PBIP definition folder not found: {self.definition_path}")

        logger.info(f"PBIP reader initialized for: {self.pbip_path}")

    def validate_pbip_structure(self) -> Dict[str, Any]:
        """
        Validate PBIP folder structure

        Returns:
            Validation result with file counts and status
        """
        validation = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "structure": {}
        }

        # Check required files
        required_files = ["database.tmdl", "model.tmdl"]
        for required_file in required_files:
            file_path = self.definition_path / required_file
            if not file_path.exists():
                validation["valid"] = False
                validation["errors"].append(f"Required file missing: {required_file}")

        # Check folders
        expected_folders = ["tables"]
        for folder in expected_folders:
            folder_path = self.definition_path / folder
            if folder_path.exists():
                file_count = len(list(folder_path.glob("*.tmdl")))
                validation["structure"][folder] = {
                    "exists": True,
                    "file_count": file_count
                }
            else:
                validation["warnings"].append(f"Expected folder not found: {folder}")
                validation["structure"][folder] = {
                    "exists": False,
                    "file_count": 0
                }

        # Optional folders
        optional_folders = ["roles", "cultures"]
        for folder in optional_folders:
            folder_path = self.definition_path / folder
            if folder_path.exists():
                file_count = len(list(folder_path.glob("*.tmdl")))
                validation["structure"][folder] = {
                    "exists": True,
                    "file_count": file_count
                }

        return validation

    def get_pbip_metadata(self) -> Dict[str, Any]:
        """
        Extract metadata from PBIP folder

        Returns:
            PBIP metadata including paths, file counts, timestamps
        """
        # Get modification time of definition folder
        definition_mtime = self.definition_path.stat().st_mtime
        definition_mtime_iso = datetime.fromtimestamp(definition_mtime).isoformat()

        # Count TMDL files
        tmdl_files = list(self.definition_path.rglob("*.tmdl"))
        tmdl_total_size = sum(f.stat().st_size for f in tmdl_files)

        # Parse model name from folder
        model_name = self.pbip_path.name.replace(".SemanticModel", "")

        # Check for item.metadata.json
        metadata_file = self.pbip_path / "item.metadata.json"
        item_metadata = {}
        if metadata_file.exists():
            try:
                item_metadata = load_json(metadata_file)
            except Exception as e:
                logger.warning(f"Could not parse item.metadata.json: {e}")

        return {
            "source_pbip_path": str(self.pbip_path),
            "source_pbip_absolute": str(self.pbip_path.absolute()),
            "pbip_last_modified": definition_mtime_iso,
            "model_name": model_name,
            "tmdl_file_count": len(tmdl_files),
            "tmdl_total_size_bytes": tmdl_total_size,
            "item_metadata": item_metadata
        }

    def discover_tables(self) -> List[str]:
        """
        Discover all tables from TMDL files

        Returns:
            List of table names
        """
        tables_path = self.definition_path / "tables"
        if not tables_path.exists():
            return []

        table_files = list(tables_path.glob("*.tmdl"))
        table_names = [f.stem for f in table_files]

        logger.info(f"Discovered {len(table_names)} tables in PBIP")
        return sorted(table_names)

    def discover_roles(self) -> List[str]:
        """
        Discover all roles from TMDL files

        Returns:
            List of role names
        """
        roles_path = self.definition_path / "roles"
        if not roles_path.exists():
            return []

        role_files = list(roles_path.glob("*.tmdl"))
        role_names = [f.stem for f in role_files]

        logger.info(f"Discovered {len(role_names)} roles in PBIP")
        return sorted(role_names)

    def get_table_tmdl_path(self, table_name: str) -> Optional[Path]:
        """
        Get path to table TMDL file

        Args:
            table_name: Name of table

        Returns:
            Path to TMDL file or None if not found
        """
        table_path = self.definition_path / "tables" / f"{table_name}.tmdl"
        return table_path if table_path.exists() else None

    def get_relationships_tmdl_path(self) -> Optional[Path]:
        """
        Get path to relationships TMDL file

        Returns:
            Path to relationships.tmdl or None
        """
        rel_path = self.definition_path / "relationships.tmdl"
        return rel_path if rel_path.exists() else None

    def get_expressions_tmdl_path(self) -> Optional[Path]:
        """
        Get path to expressions TMDL file (contains shared expressions/measures)

        Returns:
            Path to expressions.tmdl or None
        """
        expr_path = self.definition_path / "expressions.tmdl"
        return expr_path if expr_path.exists() else None

    def copy_or_symlink_tmdl(
        self,
        destination_path: Path,
        strategy: str = "symlink"
    ) -> Dict[str, Any]:
        """
        Copy or symlink TMDL files to destination

        Large files (>900KB) are automatically split when copying.

        Args:
            destination_path: Destination folder for TMDL files
            strategy: "symlink" (default) or "copy"

        Returns:
            Operation result with strategy used and file count
        """
        destination_path = Path(destination_path)

        # Create destination parent if needed
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing destination if present
        if destination_path.exists():
            if destination_path.is_symlink():
                destination_path.unlink()
            elif destination_path.is_dir():
                shutil.rmtree(destination_path)

        actual_strategy = strategy
        split_file_count = 0

        try:
            if strategy == "symlink":
                # Try to create symlink
                try:
                    os.symlink(
                        self.definition_path,
                        destination_path,
                        target_is_directory=True
                    )
                    logger.info(f"Created symlink: {destination_path} -> {self.definition_path}")
                except OSError as e:
                    # Symlink failed (permissions), fallback to copy
                    logger.warning(f"Symlink failed ({e}), falling back to copy")
                    actual_strategy = "copy"
                    # Use custom copy with file splitting
                    split_file_count = self._copy_with_splitting(self.definition_path, destination_path)
            else:
                # Copy strategy with file splitting
                split_file_count = self._copy_with_splitting(self.definition_path, destination_path)
                logger.info(f"Copied TMDL files to: {destination_path}")

        except Exception as e:
            logger.error(f"Failed to {strategy} TMDL files: {e}")
            raise

        # Write source info file
        source_info_path = destination_path / "_source_info.txt"
        with open(source_info_path, 'w', encoding='utf-8') as f:
            f.write(f"TMDL Source: {self.pbip_path.absolute()}\n")
            f.write(f"Strategy: {actual_strategy}\n")
            f.write(f"Created: {datetime.now().isoformat()}\n")
            if split_file_count > 0:
                f.write(f"Split Files: {split_file_count} large files were split\n")

        # Count files
        tmdl_files = list(destination_path.rglob("*.tmdl"))

        return {
            "success": True,
            "strategy": actual_strategy,
            "destination": str(destination_path),
            "file_count": len(tmdl_files),
            "split_files": split_file_count,
            "timestamp": datetime.now().isoformat()
        }

    def _copy_with_splitting(self, source_dir: Path, dest_dir: Path) -> int:
        """
        Copy directory with automatic splitting of large files (>900KB)

        Args:
            source_dir: Source directory
            dest_dir: Destination directory

        Returns:
            Number of files that were split
        """
        MAX_FILE_SIZE = 900_000  # 900KB
        split_count = 0

        dest_dir.mkdir(parents=True, exist_ok=True)

        # Walk through source directory
        for root, dirs, files in os.walk(source_dir):
            # Calculate relative path
            rel_root = Path(root).relative_to(source_dir)
            dest_root = dest_dir / rel_root

            # Create subdirectories
            for dir_name in dirs:
                (dest_root / dir_name).mkdir(parents=True, exist_ok=True)

            # Copy or split files
            for file_name in files:
                source_file = Path(root) / file_name
                dest_file = dest_root / file_name

                # Check file size
                file_size = source_file.stat().st_size

                if file_size > MAX_FILE_SIZE and file_name.endswith('.tmdl'):
                    # Split large TMDL file
                    logger.info(f"Splitting large file: {file_name} ({file_size:,} bytes)")
                    self._split_tmdl_file(source_file, dest_root, file_name)
                    split_count += 1
                else:
                    # Copy small file as-is
                    shutil.copy2(source_file, dest_file)

        return split_count

    def _split_tmdl_file(self, source_file: Path, dest_dir: Path, file_name: str) -> None:
        """
        Split a large TMDL file into multiple parts

        Args:
            source_file: Source TMDL file
            dest_dir: Destination directory
            file_name: Original file name
        """
        MAX_PART_SIZE = 800_000  # 800KB per part (safety margin)

        # Read entire file
        with open(source_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Calculate number of parts needed
        total_size = len(content.encode('utf-8'))
        num_parts = (total_size // MAX_PART_SIZE) + 1

        # Split by lines to maintain readability
        lines = content.split('\n')
        lines_per_part = len(lines) // num_parts

        base_name = file_name.replace('.tmdl', '')
        parts = []

        for i in range(num_parts):
            start_line = i * lines_per_part
            end_line = (i + 1) * lines_per_part if i < num_parts - 1 else len(lines)

            part_lines = lines[start_line:end_line]
            part_content = '\n'.join(part_lines)

            # Write part file
            part_file = dest_dir / f"{base_name}.part{i+1}.tmdl"
            with open(part_file, 'w', encoding='utf-8') as f:
                f.write(part_content)

            part_size = part_file.stat().st_size
            parts.append({
                "part_number": i + 1,
                "filename": part_file.name,
                "size_bytes": part_size,
                "line_range": f"{start_line}-{end_line}"
            })

            logger.debug(f"Created part {i+1}/{num_parts}: {part_file.name} ({part_size:,} bytes)")

        # Write manifest
        manifest = {
            "original_file": file_name,
            "total_parts": num_parts,
            "total_size_bytes": total_size,
            "split_strategy": "line_boundary",
            "parts": parts,
            "reassembly_instructions": "Concatenate all parts in order"
        }

        manifest_file = dest_dir / f"{base_name}.manifest.json"
        with open(manifest_file, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)

        logger.info(f"Split {file_name} into {num_parts} parts with manifest: {manifest_file.name}")

    def parse_tmdl_file(self, file_path: Path) -> str:
        """
        Read TMDL file content

        Args:
            file_path: Path to TMDL file

        Returns:
            File content as string
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read TMDL file {file_path}: {e}")
            raise

    def read_table_tmdl(self, table_name: str) -> Optional[str]:
        """
        Read table TMDL file content

        Args:
            table_name: Name of table

        Returns:
            TMDL content or None if not found
        """
        table_path = self.get_table_tmdl_path(table_name)
        if table_path:
            return self.parse_tmdl_file(table_path)
        return None

    def read_relationships_tmdl(self) -> Optional[str]:
        """
        Read relationships TMDL file content

        Returns:
            TMDL content or None if not found
        """
        rel_path = self.get_relationships_tmdl_path()
        if rel_path:
            return self.parse_tmdl_file(rel_path)
        return None

    def read_expressions_tmdl(self) -> Optional[str]:
        """
        Read expressions TMDL file content

        Returns:
            TMDL content or None if not found
        """
        expr_path = self.get_expressions_tmdl_path()
        if expr_path:
            return self.parse_tmdl_file(expr_path)
        return None
