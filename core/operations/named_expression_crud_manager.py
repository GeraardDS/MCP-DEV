"""Named Expression CRUD Manager — manage Power Query parameters/expressions via TOM."""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class NamedExpressionCrudManager:
    """CRUD operations for model named expressions (Power Query parameters)."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def list_expressions(self) -> Dict[str, Any]:
        """List all named expressions in the model."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        expressions = []
        for expr in model.Expressions:
            expressions.append({
                "name": expr.Name,
                "kind": str(expr.Kind) if hasattr(expr, 'Kind') else "M",
                "description": expr.Description or "",
            })
        return {"success": True, "expressions": expressions, "count": len(expressions)}

    def describe_expression(self, expression_name: str) -> Dict[str, Any]:
        """Get detailed info about a named expression."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        expr = model.Expressions.Find(expression_name)
        if not expr:
            return {"success": False, "error": f"Expression '{expression_name}' not found"}
        return {
            "success": True,
            "expression": {
                "name": expr.Name,
                "kind": str(expr.Kind) if hasattr(expr, 'Kind') else "M",
                "expression": expr.Expression,
                "description": expr.Description or "",
            },
        }

    def create_expression(self, expression_name: str, expression: str, **kwargs) -> Dict[str, Any]:
        """Create a new named expression."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        try:
            import Microsoft.AnalysisServices.Tabular as TOM
            ne = TOM.NamedExpression()
            ne.Name = expression_name
            ne.Expression = expression
            ne.Kind = TOM.ExpressionKind.M
            if kwargs.get("description"):
                ne.Description = kwargs["description"]
            model.Expressions.Add(ne)
            model.SaveChanges()
            return {"success": True, "message": f"Expression '{expression_name}' created"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def update_expression(self, expression_name: str, expression: str = None, **kwargs) -> Dict[str, Any]:
        """Update a named expression."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        expr = model.Expressions.Find(expression_name)
        if not expr:
            return {"success": False, "error": f"Expression '{expression_name}' not found"}
        try:
            if expression is not None:
                expr.Expression = expression
            if kwargs.get("description") is not None:
                expr.Description = kwargs["description"]
            model.SaveChanges()
            return {"success": True, "message": f"Expression '{expression_name}' updated"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_expression(self, expression_name: str) -> Dict[str, Any]:
        """Delete a named expression."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        expr = model.Expressions.Find(expression_name)
        if not expr:
            return {"success": False, "error": f"Expression '{expression_name}' not found"}
        try:
            model.Expressions.Remove(expr)
            model.SaveChanges()
            return {"success": True, "message": f"Expression '{expression_name}' deleted"}
        except Exception as e:
            return {"success": False, "error": str(e)}
