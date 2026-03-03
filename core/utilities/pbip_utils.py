"""
PBIP Utilities - Shared helper functions for Power BI PBIP file operations.

Extracted from slicer_operations_handler.py and visual_operations_handler.py
to eliminate code duplication and fix known issues.
"""
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from core.utilities.json_utils import load_json

logger = logging.getLogger(__name__)

# Pre-compiled regex for WSL path detection (avoids recompiling on every call)
_WSL_PATH_PATTERN = re.compile(r'^/mnt/([a-z])/', re.IGNORECASE)


def normalize_path(path: str) -> str:
    """Normalize path to handle Unix-style paths on Windows.

    Fixes:
    - Eliminated double regex match (was matching twice, now matches once)
    - Fixed hardcoded index 7 for rest_of_path (now uses match.end() for correctness)
    """
    match = _WSL_PATH_PATTERN.match(path)
    if match:
        drive_letter = match.group(1)
        rest_of_path = path[match.end():].replace('/', '\\')
        return f"{drive_letter.upper()}:\\{rest_of_path}"
    elif path.startswith('/'):
        return path.replace('/', '\\')

    return path


def find_definition_folder(pbip_path: str) -> Optional[Path]:
    """Find the definition folder for a PBIP project.

    Accepts a path to a .pbip file, a .Report folder, a definition folder,
    or a directory containing a .Report folder.
    """
    path = Path(normalize_path(pbip_path))

    if not path.exists():
        return None

    # If it's a .pbip file, look for .Report folder
    if path.is_file() and path.suffix == '.pbip':
        report_folder = path.parent / f"{path.stem}.Report"
        if report_folder.exists():
            definition = report_folder / "definition"
            if definition.exists():
                return definition

    # If it's a .Report folder
    if path.is_dir() and path.name.endswith('.Report'):
        definition = path / "definition"
        if definition.exists():
            return definition

    # If it's already a definition folder
    if path.is_dir() and path.name == "definition":
        return path

    # If it's a directory, search for .Report folders
    if path.is_dir():
        for item in path.iterdir():
            if item.is_dir() and item.name.endswith('.Report'):
                definition = item / "definition"
                if definition.exists():
                    return definition
        # Also check if definition exists directly
        definition = path / "definition"
        if definition.exists():
            return definition

    return None


def resolve_report_folder_from_pbip(pbip_file_path: str) -> Optional[str]:
    """Resolve a .pbip file path to its matching .Report folder.

    PBIP convention: filename.pbip → filename.Report/ in the same directory.
    Example: C:/Repo/MyDashboard.pbip → C:/Repo/MyDashboard.Report/

    Falls back to parsing the .pbip JSON for artifact path hints.

    Args:
        pbip_file_path: Absolute path to a .pbip file

    Returns:
        Path to the .Report folder if found, or None
    """
    path = Path(normalize_path(pbip_file_path))

    if not path.is_file() or path.suffix.lower() != '.pbip':
        return None

    pbip_dir = path.parent
    project_name = path.stem

    # Primary: matching .Report folder by name convention
    report_folder = pbip_dir / f"{project_name}.Report"
    if report_folder.is_dir():
        return str(report_folder)

    # Fallback: parse .pbip JSON for artifact path
    try:
        pbip_data = load_json(str(path))
        if isinstance(pbip_data, dict):
            for artifact in pbip_data.get("artifacts", []):
                report_info = artifact.get("report", {})
                report_path = report_info.get("path", "")
                if report_path:
                    # Path is relative, e.g. "MyDashboard.Report"
                    candidate = pbip_dir / report_path
                    if candidate.is_dir():
                        return str(candidate)
    except Exception:
        pass

    return None


def resolve_pbip_report_path(input_path: str) -> Optional[str]:
    """Resolve any path to a valid PBIP .Report folder.

    Handles:
    - .pbip file → matching .Report folder
    - .Report folder → returned as-is
    - Directory with definition/ → returned as-is
    - Directory containing .pbip files → .Report from first Report-type .pbip

    Args:
        input_path: Path to .pbip file, directory, or .Report folder

    Returns:
        Path to the best .Report folder or valid PBIP folder, or None
    """
    path = Path(normalize_path(input_path))

    if not path.exists():
        return None

    # Case 1: .pbip file
    if path.is_file() and path.suffix.lower() == '.pbip':
        return resolve_report_folder_from_pbip(str(path))

    # Case 2: Already a .Report folder
    if path.is_dir() and path.name.endswith('.Report'):
        return str(path)

    # Case 3: Has definition/ directly (already a valid PBIP folder)
    if path.is_dir() and (path / 'definition').is_dir():
        return str(path)

    # Case 4: Directory containing .pbip files — resolve from those
    if path.is_dir():
        for pbip_file in sorted(path.glob('*.pbip')):
            report_folder = resolve_report_folder_from_pbip(str(pbip_file))
            if report_folder:
                return report_folder

    return None


def load_json_file(file_path: Path) -> Optional[Dict]:
    """Load JSON file safely.

    Catches specific exceptions instead of bare Exception:
    - json.JSONDecodeError for malformed JSON
    - FileNotFoundError for missing files
    - PermissionError for access issues
    """
    try:
        return load_json(file_path)
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in {file_path}: {e}")
        return None
    except FileNotFoundError:
        logger.warning(f"File not found: {file_path}")
        return None
    except PermissionError as e:
        logger.warning(f"Permission denied reading {file_path}: {e}")
        return None


def save_json_file(file_path: Path, data: Dict) -> bool:
    """Save JSON file with proper formatting.

    Catches specific exceptions instead of bare Exception:
    - FileNotFoundError for missing parent directories
    - PermissionError for access issues
    - TypeError for non-serializable data
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except FileNotFoundError as e:
        logger.error(f"Parent directory not found for {file_path}: {e}")
        return False
    except PermissionError as e:
        logger.error(f"Permission denied writing {file_path}: {e}")
        return False
    except TypeError as e:
        logger.error(f"Non-serializable data when saving {file_path}: {e}")
        return False


def get_page_display_name(page_folder: Path) -> str:
    """Get the display name for a page from its page.json file."""
    page_json_path = page_folder / "page.json"
    if page_json_path.exists():
        page_data = load_json_file(page_json_path)
        if page_data:
            return page_data.get('displayName', page_folder.name)
    return page_folder.name
