"""
JSON Utilities with orjson Optimization

Provides JSON loading/dumping functions with automatic fallback from orjson to standard json.
"""

import json
import logging
from typing import Any, Union
from pathlib import Path

logger = logging.getLogger(__name__)

# Try to import orjson for better performance
try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    HAS_ORJSON = False
    logger.debug("orjson not available, using standard json")


# Maximum file size for JSON loading (500 MB)
MAX_JSON_FILE_SIZE = 500 * 1024 * 1024


def load_json(file_path: Union[str, Path], max_size: int = MAX_JSON_FILE_SIZE) -> Any:
    """
    Load JSON from file with orjson optimization.

    Args:
        file_path: Path to JSON file
        max_size: Maximum file size in bytes (default 500MB)

    Returns:
        Parsed JSON data

    Raises:
        ValueError: If file exceeds max_size

    Example:
        >>> data = load_json("model.json")
    """
    file_path = Path(file_path)
    file_size = file_path.stat().st_size
    if file_size > max_size:
        raise ValueError(
            f"JSON file too large: {file_size / 1024 / 1024:.1f}MB exceeds "
            f"limit of {max_size / 1024 / 1024:.1f}MB"
        )
    with open(file_path, 'rb') as f:
        if HAS_ORJSON:
            return orjson.loads(f.read())
        return json.load(f)


def loads_json(data: Union[bytes, str]) -> Any:
    """
    Parse JSON string/bytes with orjson optimization.

    Args:
        data: JSON string or bytes

    Returns:
        Parsed JSON data

    Example:
        >>> obj = loads_json('{"key": "value"}')
        >>> obj = loads_json(b'{"key": "value"}')
    """
    if HAS_ORJSON and isinstance(data, bytes):
        return orjson.loads(data)
    if isinstance(data, bytes):
        data = data.decode('utf-8')
    return json.loads(data)


def dump_json(data: Any, file_path: Union[str, Path], indent: int = 2) -> None:
    """
    Dump data to JSON file with orjson optimization.

    Args:
        data: Data to serialize
        file_path: Output file path
        indent: Indentation level (default: 2)

    Example:
        >>> dump_json({"key": "value"}, "output.json")
    """
    with open(file_path, 'wb' if HAS_ORJSON else 'w') as f:
        if HAS_ORJSON:
            # orjson option for pretty printing
            f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))
        else:
            json.dump(data, f, indent=indent)


def dumps_json(data: Any, indent: int = 2) -> str:
    """
    Serialize data to JSON string with orjson optimization.

    Args:
        data: Data to serialize
        indent: Indentation level (default: 2)

    Returns:
        JSON string

    Example:
        >>> json_str = dumps_json({"key": "value"})
    """
    if HAS_ORJSON:
        return orjson.dumps(data, option=orjson.OPT_INDENT_2).decode('utf-8')
    return json.dumps(data, indent=indent)
