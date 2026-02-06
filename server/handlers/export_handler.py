"""
Export Handler
Handles TMDL and schema export operations.

Note: Export functionality was previously provided by get_live_model_schema which has been
removed. Export operations are now handled by TMDL Operations (02_TMDL_Operations) and
documentation handlers. This module is kept as a placeholder for future export tools.
"""
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


def register_export_handlers(registry):
    """Register export handlers.

    Currently no standalone export handlers are registered.
    Export functionality is provided by:
    - 02_TMDL_Operations (TMDL export)
    - 08_Generate_Documentation_Word (Word doc export)
    - 05_Export_DAX_Measures (DAX CSV export)
    """
    logger.debug("Export handler registration complete (no standalone export tools)")
    pass
