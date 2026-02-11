"""
Shared Mermaid diagram utilities.

Centralizes sanitize_node_id and measure_name_to_table lookup
that were duplicated across dependency_analyzer.py and diagram_html_generator.py.
"""

import re
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def sanitize_node_id(name: str, prefix: str = "") -> str:
    """Convert a name to a valid Mermaid node ID (alphanumeric and underscores only).

    Args:
        name: The raw name (e.g., "Table[Measure Name]")
        prefix: Optional prefix (e.g., "M" for measure nodes)

    Returns:
        A sanitized string safe for use as a Mermaid node ID
    """
    clean = name.replace("[", "_").replace("]", "").replace(" ", "_")
    clean = clean.replace("-", "_").replace("/", "_").replace("\\", "_")
    clean = clean.replace("(", "_").replace(")", "_").replace("%", "pct")
    clean = clean.replace("&", "and").replace("'", "").replace('"', "")
    clean = clean.replace(".", "_").replace(",", "_").replace(":", "_")
    clean = clean.replace("+", "plus").replace("*", "x").replace("=", "eq")
    clean = clean.replace("<", "lt").replace(">", "gt").replace("!", "not")
    clean = clean.replace("#", "num").replace("@", "at").replace("$", "dollar")
    # Remove any remaining non-alphanumeric chars except underscore
    clean = re.sub(r'[^a-zA-Z0-9_]', '', clean)
    # Collapse multiple underscores
    clean = re.sub(r'_+', '_', clean)
    # Ensure it starts with a letter (Mermaid requirement)
    if clean and not clean[0].isalpha():
        clean = 'n_' + clean
    clean = clean.strip("_")
    if prefix:
        return f"{prefix}_{clean}" if clean else f"{prefix}_node"
    return clean or "node"


def build_measure_name_lookup(measures_result: Dict) -> Dict[str, str]:
    """Build a measure-name-to-table lookup dict from a MEASURES DMV query result.

    Stores multiple key formats for robust matching:
    - exact name
    - lowercase name
    - normalized whitespace + lowercase

    Args:
        measures_result: Result dict from execute_info_query("MEASURES")

    Returns:
        Dict mapping measure name variants to their table name
    """
    lookup: Dict[str, str] = {}
    if not measures_result.get('success'):
        return lookup

    for m in measures_result.get('rows', []):
        m_table = m.get('Table', '') or m.get('[Table]', '') or ''
        m_name = m.get('Name', '') or m.get('[Name]', '') or ''
        if m_table and m_name:
            lookup[m_name] = m_table
            lookup[m_name.lower()] = m_table
            lookup[' '.join(m_name.lower().split())] = m_table

    return lookup


def resolve_measure_table(
    dep_table: str,
    dep_name: str,
    lookup: Dict[str, str],
    context: str = "",
) -> str:
    """Resolve a measure's table name using a lookup dict.

    Args:
        dep_table: Known table name (may be empty)
        dep_name: Measure name to look up
        lookup: Dict from build_measure_name_lookup()
        context: Optional context string for log messages

    Returns:
        Resolved table name, or 'Unknown'
    """
    if dep_table:
        return dep_table
    if dep_name:
        # Try exact match
        if dep_name in lookup:
            return lookup[dep_name]
        # Try lowercase
        if dep_name.lower() in lookup:
            return lookup[dep_name.lower()]
        # Try normalized
        normalized = ' '.join(dep_name.lower().split())
        if normalized in lookup:
            return lookup[normalized]
        log_prefix = f"{context}: " if context else ""
        logger.warning(f"{log_prefix}Could not resolve table for [{dep_name}]")
    return 'Unknown'
