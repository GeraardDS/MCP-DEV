"""
PBIP Utilities - Shared helper functions for Power BI PBIP file operations.

Extracted from slicer_operations_handler.py and visual_operations_handler.py
to eliminate code duplication and fix known issues.
"""
import json
import logging
import re
from pathlib import Path
from typing import Dict, Optional

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


def load_json_file(file_path: Path) -> Optional[Dict]:
    """Load JSON file safely.

    Catches specific exceptions instead of bare Exception:
    - json.JSONDecodeError for malformed JSON
    - FileNotFoundError for missing files
    - PermissionError for access issues
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
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
