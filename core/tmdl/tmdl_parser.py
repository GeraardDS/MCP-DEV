"""
TMDL Parser Module (Facade)

This module is maintained for backward compatibility.
All parsing is delegated to core.tmdl.unified_parser.UnifiedTmdlParser.

Consumers should migrate to:
    from core.tmdl.unified_parser import UnifiedTmdlParser
    from core.tmdl.models import TmdlModel
"""

import logging
from typing import Any, Dict, List, Optional

from .unified_parser import UnifiedTmdlParser

logger = logging.getLogger(__name__)


class TmdlParser:
    """
    Facade for backward compatibility.

    Delegates to UnifiedTmdlParser for all parsing operations.
    New code should use UnifiedTmdlParser directly.
    """

    def __init__(self, tmdl_path: str):
        """
        Initialize TMDL parser.

        Args:
            tmdl_path: Path to the root TMDL export (contains definition/ folder)
        """
        self._parser = UnifiedTmdlParser(tmdl_path)
        logger.info(f"Initialized TMDL parser facade for: {tmdl_path}")

    def parse_full_model(self) -> Dict[str, Any]:
        """
        Parse the complete TMDL model structure.

        Returns:
            Dictionary containing all model components.
        """
        parsed = self._parser.parse_full_model()
        return parsed.to_dict()


def parse_tmdl_model(tmdl_path: str) -> Dict[str, Any]:
    """
    Convenience function to parse a TMDL model.

    Args:
        tmdl_path: Path to TMDL export directory

    Returns:
        Parsed model dictionary
    """
    parser = TmdlParser(tmdl_path)
    return parser.parse_full_model()
