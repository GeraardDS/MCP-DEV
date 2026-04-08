"""Bridge to existing measure CRUD for applying optimized DAX."""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class MeasureApplier:
    """Applies optimized DAX to Power BI models via existing infrastructure."""

    def __init__(self, connection_state: Any = None):
        self._connection_state = connection_state

    def apply(self, measure_name: str, table_name: str, new_dax: str) -> Dict[str, Any]:
        """Apply new DAX expression to an existing measure."""
        if not self._connection_state:
            return {"success": False, "error": "No connection to Power BI model"}
        try:
            from core.dax.dax_injector import DAXInjector

            injector = DAXInjector(self._connection_state)
            return injector.upsert_measure(
                measure_name=measure_name,
                table_name=table_name,
                expression=new_dax,
            )
        except Exception as e:
            logger.error(f"Failed to apply measure: {e}")
            return {"success": False, "error": str(e)}

    def is_connected(self) -> bool:
        """Check if we have an active connection."""
        return (
            self._connection_state is not None
            and hasattr(self._connection_state, "is_connected")
            and self._connection_state.is_connected()
        )
